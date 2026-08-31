import sqlite3
import os
import mimetypes
import uuid
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, render_template_string, send_file
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import RequestEntityTooLarge
app = Flask(__name__)
app.secret_key = "commercial_marketplace_super_secret_token"
LOCAL_ADMIN_USERNAME = "Stapps Of Faith"
LOCAL_ADMIN_PASSWORD = "RICHARD10"
PRODUCT_CATEGORIES = ["Phones & Accessories", "Groceries", "Clothing", "Books", "Health & Beauty", "Beauty & Personal Care", "Home & Kitchen", "Electronics", "Fast Food", "Other"]
VENDOR_CATEGORIES = PRODUCT_CATEGORIES + ["Health & Beauty", "Fast Food"]
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov"}

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 60 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(error):
    return redirect(
        url_for(
            "home",
            listing_error="Video is too large. Maximum upload size is 50 MB."
        )
    )

OUTDATED_ANDROID_REGEX = re.compile(r'Android\s([1-7]\.\d)')

@app.before_request
def enforce_device_standards():
    if request.path.startswith('/static') or request.path == '/service-worker.js':
        return None
    user_agent = request.headers.get('User-Agent', '')
    if "Android" in user_agent and OUTDATED_ANDROID_REGEX.search(user_agent):
        return render_template_string("""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Incompatible Device | Biz Hub</title>
                <style>
                    body { font-family: system-ui, -apple-system, sans-serif; text-align: center; padding: 50px 20px; background: #f4f6f8; color: #2d3748; }
                    .card { max-width: 480px; margin: 40px auto; background: white; padding: 40px 30px; border-radius: 12px; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.05), 0 4px 6px -2px rgba(0,0,0,0.05); border-top: 5px solid #e53e3e; }
                    h1 { color: #e53e3e; font-size: 22px; margin-bottom: 16px; font-weight: 700; }
                    p { line-height: 1.6; color: #4a5568; font-size: 15px; margin-bottom: 20px; }
                    .footer-note { font-size: 13px; color: #718096; border-top: 1px solid #edf2f7; padding-top: 15px; }
                </style>
            </head>
            <body>
                <div class="card">
                    <h1>Browser Upgrade Required</h1>
                    <p>To preserve data session encryption, secure vendor verification pipelines, and modern layout alignment, Biz Hub no longer supports devices running Android 7.0 or below.</p>
                    <p>Please upgrade your browser application or system software to restore full commercial privileges.</p>
                    <div class="footer-note">Biz Hub Operations • Secure Marketplace Infrastructure</div>
                </div>
            </body>
            </html>
        """), 403

def init_db():
    conn = sqlite3.connect("marketplace.db", timeout=20)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'Customer',
            seller_type TEXT NOT NULL DEFAULT 'Individual',
            company_name TEXT,
            whatsapp_number TEXT,
            plan TEXT NOT NULL DEFAULT 'basic',
            trial_started_at TEXT,
            subscription_expires_at TEXT,
            upgrade_requested_at TEXT,
            catalog_mode TEXT,
            company_logo TEXT,
            business_location TEXT,
            registered_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            price REAL NOT NULL,
            description TEXT NOT NULL,
            image_file TEXT NOT NULL,
            video_file TEXT,
            stock_quantity INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'Available',
            seller TEXT NOT NULL,
            seller_email TEXT NOT NULL,
            seller_whatsapp TEXT,
            location TEXT NOT NULL DEFAULT 'Accra',
            business_label TEXT NOT NULL DEFAULT 'Individual Vendor',
            category TEXT NOT NULL DEFAULT 'Other',
            views INTEGER NOT NULL DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vendor_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            UNIQUE(user_id, category),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_username TEXT NOT NULL,
            total REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            payment_status TEXT NOT NULL DEFAULT 'Unpaid',
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            seller TEXT NOT NULL,
            title TEXT NOT NULL,
            price REAL NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            vendor_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(customer_id, vendor_id),
            FOREIGN KEY(customer_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(vendor_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vendor_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER NOT NULL,
            order_id INTEGER NOT NULL,
            product_id INTEGER,
            customer_username TEXT NOT NULL,
            item_name TEXT NOT NULL,
            price REAL NOT NULL,
            location TEXT,
            message TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(vendor_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS promotions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            discount REAL,
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY(vendor_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS financial_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_type TEXT NOT NULL,
            username TEXT NOT NULL,
            amount REAL NOT NULL,
            momo_reference TEXT UNIQUE,
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
        # 👑 PRODUCTION STRUCTURAL SCHEMA HOTFIX: Safe Column Alteration Injections
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN registered_at TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists safely in the workspace structure, skip altering
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN business_location TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN theme TEXT NOT NULL DEFAULT 'day'")
    except sqlite3.OperationalError:
        pass  # Column already exists safely in the workspace structure, skip altering

    conn.close()

init_db()

def normalize_whatsapp_number(number):
    digits = "".join(character for character in (number or "") if character.isdigit())
    if digits.startswith("0"):
        digits = "233" + digits[1:]
    return digits

def subscription_status(user):
    if not user:
        return {"name": "Basic", "is_premium": False, "trial": False, "expires": None}
    now = datetime.now(timezone.utc)
    trial_expiry = datetime.fromisoformat(user["subscription_expires_at"]) if user["subscription_expires_at"] else None
    is_vendor_role = user["role"] in ["Vendor", "Fast Food"]
    
    trial_active = is_vendor_role and trial_expiry and trial_expiry > now and user["plan"] == "basic"
    premium_active = is_vendor_role and ((user["plan"] == "premium" and trial_expiry and trial_expiry > now) or trial_active)
    
    if trial_active:
        return {"name": "Free trial", "is_premium": True, "trial": True, "expires": trial_expiry.strftime("%d %b %Y")}
    if premium_active:
        return {"name": "Premium Store", "is_premium": True, "trial": False, "expires": trial_expiry.strftime("%d %b %Y")}
        
    return {"name": "Basic", "is_premium": False, "trial": False, "expires": None}

def admin_configured():
    return bool(get_admin_username() and get_admin_password()) or bool(query_db("SELECT id FROM admin_users LIMIT 1"))

def get_admin_username():
    return os.environ.get("BIZ_HUB_ADMIN_USERNAME") or LOCAL_ADMIN_USERNAME

def get_admin_password():
    return os.environ.get("BIZ_HUB_ADMIN_PASSWORD") or LOCAL_ADMIN_PASSWORD

def admin_signup_available():
    return not bool(query_db("SELECT id FROM admin_users LIMIT 1"))

def is_admin():
    return session.get("is_admin") is True

@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(app.static_folder, "service-worker.js", mimetype="application/javascript")

def query_db(query, args=(), one=False):
    """Executes database transactions safely using row mapping structures."""
    conn = sqlite3.connect("marketplace.db", timeout=20)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(query, args)
    
    # 👑 STABLE DATABASE SERIALIZATION LAYER (FIXED FETCH MATRICES)
    if one:
        row = cursor.fetchone()
        res = dict(row) if row else None
    else:
        rows = cursor.fetchall()
        res = [dict(r) for r in rows] if rows else []
        
    conn.commit()
    conn.close()
    return res

def get_vendor_categories(user_id):
    return [row["category"] for row in query_db("SELECT category FROM vendor_categories WHERE user_id = ? ORDER BY category", (user_id,))]

   


def valid_reset_token(token):
    if not token:
        return None
    return query_db("SELECT * FROM password_resets WHERE token = ? AND used = 0", (token,), one=True)

def save_company_logo(upload):
    if not upload or not upload.filename:
        return None
    # 👑 FIXED INDEX CHANNELS: Grabs the extension string from the tuple safely
    extension = os.path.splitext(upload.filename)[1].lower()
    if extension not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return None
    filename = f"company-{uuid.uuid4().hex}{extension}"
    upload.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    return filename


@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        if "username" not in session or session.get("role") not in ["Vendor", "Fast Food"]:
            return redirect(url_for("home"))
            
        vendor = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
        vendor_subscription = subscription_status(vendor)
        listing_count_row = query_db("SELECT COUNT(*) AS count FROM products WHERE seller = ?", (session["username"],), one=True)
        listing_count = listing_count_row["count"] if listing_count_row else 0
        
        if not vendor_subscription["is_premium"] and listing_count >= 3:
            return redirect(url_for("home", listing_error="Basic accounts can list up to 3 products. Upgrade to Premium for unlimited listings."))

        price = request.form.get("price")
        is_fast_food = (vendor and vendor.get("seller_type") == "Fast Food") or session.get("role") == "Fast Food"
        
        title = request.form.get("meal_name" if is_fast_food else "title")
        description = request.form.get("meal_description" if is_fast_food else "description")
        category = "Fast Food" if is_fast_food else request.form.get("category", "Other")
        stock_quantity = request.form.get("stock_quantity", "1")
        location = request.form.get("location")
        file = request.files.get("product_image")
        video = request.files.get("product_video")
        
        # 👑 ONE-MEDIA-ONLY RULE: every listing must contain exactly one image OR one video.
        has_image = bool(file and file.filename)
        has_video = bool(video and video.filename)
        if has_image == has_video:
            return redirect(url_for("home", listing_error="Choose exactly one item image OR one showcase video. Image + video together, or no media, is not allowed."))

        filename = ""
        video_filename = None

        if has_image:
            image_extension = os.path.splitext(file.filename)[1].lower()
            if image_extension not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                return redirect(url_for("home", listing_error="Item images must be PNG, JPG, JPEG, WebP, or GIF files."))
            filename = f"product-{uuid.uuid4().hex}{image_extension}"

        if has_video:
            video_extension = os.path.splitext(video.filename)[1].lower()
            if not vendor_subscription["is_premium"]:
                return redirect(url_for("home", listing_error="Only verified vendors with an active Premium Store or trial can upload product videos."))
            if video_extension not in VIDEO_EXTENSIONS:
                return redirect(url_for("home", listing_error="Product videos must be MP4, WebM, or MOV files."))

            video_filename = f"video-{uuid.uuid4().hex}{video_extension}"

        try:
            stock_quantity = int(stock_quantity)
        except (TypeError, ValueError):
            return redirect(url_for("home", listing_error="Stock quantity must be a whole number greater than zero."))
        if stock_quantity < 1:
            return redirect(url_for("home", listing_error="Stock quantity must be a whole number greater than zero."))

        if not title or not price or not description or not location:
            return redirect(url_for("home", listing_error="Please complete the title, price, description, location, and media fields."))

        # Save media only after all validation passes, so a rejected listing cannot leave orphaned uploads.
        if has_image:
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
        elif has_video:
            video_path = os.path.join(app.config["UPLOAD_FOLDER"], video_filename)
            video.save(video_path)

            # Server-side duration guard when ffprobe is available. Client-side validation below
            # provides immediate feedback; this guard protects direct/non-browser submissions too.
            try:
                import shutil, subprocess
                ffprobe_path = shutil.which("ffprobe")
                if ffprobe_path:
                    ffprobe_command = [
                        ffprobe_path, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", video_path
                    ]
                    probe_output = subprocess.check_output(ffprobe_command, stderr=subprocess.STDOUT, timeout=15).decode("utf-8").strip()
                    parsed_duration = float(probe_output)
                    if parsed_duration > 20.0:
                        os.remove(video_path)
                        return redirect(url_for("home", listing_error="🚫 UPLOAD REFUSED: Showcase videos must be 20 seconds or shorter."))
            except (ValueError, subprocess.SubprocessError, OSError):
                # Do not break otherwise valid uploads when ffprobe is unavailable on the host.
                pass

        b_label = session.get("company_name") or "Individual Vendor"
        query_db(
            "INSERT INTO products (title, price, description, image_file, video_file, stock_quantity, status, seller, seller_email, seller_whatsapp, location, business_label, category) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (title, float(price), description, filename, video_filename, stock_quantity, "Available", session["username"], session["email"], session.get("whatsapp_number"), location, b_label, category)
        )
        return redirect(url_for("home"))

            
    selected_filter = request.args.get("filter_location", "All")
    company_search = request.args.get("company_search", "").strip()
    selected_category = request.args.get("category", "All")
    promo_only = request.args.get("promo") == "1"
    listing_error = request.args.get("listing_error")
    
    product_conditions = []
    product_args = [datetime.now(timezone.utc).isoformat()]
    
    if selected_filter != "All":
        product_conditions.append("location = ?")
        product_args.append(selected_filter)
    if company_search:
        product_conditions.append("(business_label LIKE ? OR seller LIKE ?)")
        search_pattern = f"%{company_search}%"
        product_args.extend([search_pattern, search_pattern])
    if selected_category != "All":
        product_conditions.append("category = ?")
        product_args.append(selected_category)
    if promo_only:
        now_iso = datetime.now(timezone.utc).isoformat()
        product_conditions.append("EXISTS (SELECT 1 FROM promotions pr JOIN users pu ON pu.id = pr.vendor_id WHERE pu.username = p.seller AND pr.active = 1 AND pr.starts_at <= ? AND pr.ends_at >= ?)")
        product_args.extend([now_iso, now_iso])
        
    product_query = "SELECT p.*, CASE WHEN EXISTS (SELECT 1 FROM users u WHERE u.username = p.seller AND u.role IN ('Vendor', 'Fast Food') AND u.plan = 'premium' AND u.subscription_expires_at > ?) THEN 1 ELSE 0 END AS is_verified FROM products p"
    if product_conditions:
        product_query += " WHERE " + " AND ".join(product_conditions)
    product_query += " ORDER BY id DESC"
    
    all_products = query_db(product_query, product_args) or []

    # Attach each vendor's currently active promotion to its marketplace cards.
    vendor_promos = {}
    now_iso = datetime.now(timezone.utc).isoformat()
    for promo_row in (query_db("SELECT pr.*, u.username FROM promotions pr JOIN users u ON u.id = pr.vendor_id WHERE pr.active = 1 AND pr.starts_at <= ? AND pr.ends_at >= ?", (now_iso, now_iso)) or []):
        vendor_promos[promo_row["username"]] = promo_row
    for product in all_products:
        product["active_promo"] = vendor_promos.get(product["seller"])
    
    vendor_logos = {}
    logo_rows = query_db("SELECT username, company_logo FROM users WHERE company_logo IS NOT NULL") or []
    for row in logo_rows:
        vendor_logos[row["username"]] = row["company_logo"]

    cart_items = []
    cart_total = 0.0
    seller_orders = {}

    if "cart" in session and session["cart"]:
        placeholders = ",".join("?" for _ in session["cart"])
        items_in_db = query_db(f"SELECT * FROM products WHERE id IN ({placeholders})", session["cart"]) or []
        for item in items_in_db:
            cart_items.append(item)
            cart_total += float(item["price"])
            seller_number = normalize_whatsapp_number(item["seller_whatsapp"])
            seller_key = (item["seller"], seller_number)
            
            seller_order = seller_orders.setdefault(seller_key, {
                "seller": item["seller"],
                "number": seller_number,
                "items": [],
                "total": 0.0,
            })
            seller_order["items"].append(item)
            seller_order["total"] += float(item["price"])

    for seller_order in seller_orders.values():
        message = f"Hello {seller_order['seller']}, I want to buy these products on Biz Hub:\n"
        for item in seller_order["items"]:
            message += f"- {item['title']} (GH₵{item['price']}) in {item['location']}\n"
        message += f"\nTotal Cost: GH₵{seller_order['total']:.2f}. Let's arrange for payment and delivery."
        seller_order["whatsapp_text"] = quote(message)

    premium_rows = query_db("SELECT username FROM users WHERE (role = 'Vendor' OR role = 'Fast Food') AND plan = 'premium' AND subscription_expires_at > ?", (datetime.now(timezone.utc).isoformat(),))
    premium_sellers = {row["username"] for row in premium_rows} if premium_rows else set()

    trial_rows = query_db("SELECT username FROM users WHERE (role = 'Vendor' OR role = 'Fast Food') AND plan = 'basic' AND subscription_expires_at > ?", (datetime.now(timezone.utc).isoformat(),))
    trial_sellers = {row["username"] for row in trial_rows} if trial_rows else set()

    premium_sellers.update(trial_sellers)
    for seller_order in seller_orders.values():
        seller_order["priority"] = seller_order["seller"] in premium_sellers

    vendor_subscription = {"name": "Free trial", "is_premium": False, "trial": True, "expires": "N/A"}
    listing_count = 0
    fast_food_count = 0
    vendor_notification_count = 0
    if session.get("role") in ["Vendor", "Fast Food"]:
        vendor = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
        vendor_subscription = subscription_status(vendor)
        if vendor:
            unread_row = query_db("SELECT COUNT(*) AS count FROM vendor_notifications WHERE vendor_id = ? AND is_read = 0", (vendor["id"],), one=True)
            vendor_notification_count = unread_row["count"] if unread_row else 0
        listing_count_row = query_db("SELECT COUNT(*) AS count FROM products WHERE seller = ?", (session["username"],), one=True)
        listing_count = listing_count_row["count"] if listing_count_row else 0
        if session.get("role") == "Fast Food":
            fast_food_count_row = query_db("SELECT COUNT(*) AS count FROM products WHERE seller = ? AND category = 'Fast Food'", (session["username"],), one=True)
            fast_food_count = fast_food_count_row["count"] if fast_food_count_row else 0

    return render_template("index.html", products=all_products, active_filter=selected_filter, company_search=company_search, selected_category=selected_category, categories=PRODUCT_CATEGORIES, vendor_logos=vendor_logos, cart_items=cart_items, cart_total=cart_total, seller_orders=sorted(seller_orders.values(), key=lambda order: not order["priority"]), vendor_subscription=vendor_subscription, listing_count=listing_count, fast_food_count=fast_food_count, listing_error=listing_error, premium_sellers=premium_sellers, vendor_notification_count=vendor_notification_count, promo_only=promo_only)
@app.route("/delete-item/<int:product_id>")
def delete_item(product_id):
    if "username" not in session:
        return redirect(url_for("login"))
    product = query_db("SELECT * FROM products WHERE id = ?", (product_id,), one=True)
    if product and product["seller"] == session["username"]:
        query_db("DELETE FROM products WHERE id = ?", (product_id,))
    return redirect(url_for("home"))

@app.route("/add-to-cart/<int:product_id>")
def add_to_cart(product_id):
    product = query_db("SELECT stock_quantity, status FROM products WHERE id = ?", (product_id,), one=True)
    if not product:
        return redirect(url_for("home"))
    if product["stock_quantity"] < 1 or product["status"] == "Sold":
        return redirect(url_for("home", listing_error="This product is sold out."))
    if "cart" not in session:
        session["cart"] = []
    current_cart = session["cart"]
    if product_id not in current_cart:
        current_cart.append(product_id)
        session["cart"] = current_cart
    return redirect(url_for("home"))

@app.route("/mark-sold/<int:product_id>", methods=["POST"])
def mark_sold(product_id):
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    product = query_db("SELECT stock_quantity FROM products WHERE id = ? AND seller = ?", (product_id, session["username"]), one=True)
    if product:
        try:
            sold_quantity = int(request.form.get("sold_quantity", "1"))
        except (TypeError, ValueError):
            sold_quantity = 0
        if 1 <= sold_quantity <= product["stock_quantity"]:
            query_db("UPDATE products SET stock_quantity = MAX(stock_quantity - ?, 0), status = CASE WHEN stock_quantity <= ? THEN 'Sold' ELSE 'Available' END WHERE id = ? AND seller = ?", (sold_quantity, sold_quantity, product_id, session["username"]))
    return redirect(url_for("home"))

@app.route("/clear-cart")
def clear_cart():
    session.pop("cart", None)
    return redirect(url_for("home"))
@app.route("/place-order", methods=["POST"])
def place_order():
    if "username" not in session:
        return redirect(url_for("login"))
    cart_ids = session.get("cart", [])
    if not cart_ids:
        return redirect(url_for("home"))
    placeholders = ",".join("?" for _ in cart_ids)
    items = query_db(f"SELECT * FROM products WHERE id IN ({placeholders}) AND stock_quantity > 0 AND status = 'Available'", cart_ids)
    if len(items) != len(cart_ids):
        return redirect(url_for("home", listing_error="One or more cart items are no longer available."))
    total = sum(float(item["price"]) for item in items)
    created_at = datetime.now(timezone.utc).isoformat()
    query_db("INSERT INTO orders (customer_username, total, status, payment_status, created_at) VALUES (?, ?, 'Pending', 'Unpaid', ?)", (session["username"], total, created_at))
    order_id = query_db("SELECT id FROM orders WHERE customer_username = ? AND created_at = ? ORDER BY id DESC LIMIT 1", (session["username"], created_at), one=True)["id"]
    for item in items:
        query_db("INSERT INTO order_items (order_id, product_id, seller, title, price, quantity) VALUES (?, ?, ?, ?, ?, 1)", (order_id, item["id"], item["seller"], item["title"], item["price"]))

        vendor = query_db(
            "SELECT id, company_name FROM users WHERE username = ? AND role IN ('Vendor', 'Fast Food')",
            (item["seller"],),
            one=True
        )
        if vendor:
            message = (
                f"New purchase from @{session['username']}: {item['title']} "
                f"for GH₵{float(item['price']):.2f}. Location: {item.get('location') or 'Not specified'}."
            )
            query_db(
                "INSERT INTO vendor_notifications (vendor_id, order_id, product_id, customer_username, item_name, price, location, message, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (vendor["id"], order_id, item["id"], session["username"], item["title"], float(item["price"]), item.get("location"), message, created_at)
            )
    session.pop("cart", None)
    return redirect(url_for("order_history"))

@app.route("/orders/<int:order_id>/payment-sent", methods=["POST"])
def mark_payment_sent(order_id):
    if "username" not in session:
        return redirect(url_for("login"))
    query_db("UPDATE orders SET payment_status = 'Marked paid' WHERE id = ? AND customer_username = ? AND status = 'Pending'", (order_id, session["username"]))
    return redirect(url_for("order_history"))

@app.route("/orders")
def order_history():
    if "username" not in session:
        return redirect(url_for("login"))
    customer_orders = query_db("SELECT * FROM orders WHERE customer_username = ? ORDER BY id DESC", (session["username"],))
    is_vendor = session.get("role") in ["Vendor", "Fast Food"]
    vendor_orders = query_db(
        "SELECT DISTINCT o.*, oi.seller FROM orders o JOIN order_items oi ON oi.order_id = o.id WHERE oi.seller = ? ORDER BY o.id DESC",
        (session["username"],)
    ) if is_vendor else []
    all_active_orders = (customer_orders or []) + (vendor_orders or [])
    order_items = {order["id"]: query_db("SELECT oi.*, p.location FROM order_items oi LEFT JOIN products p ON p.id = oi.product_id WHERE oi.order_id = ?", (order["id"],)) for order in all_active_orders}
    seller_names = {row["username"]: (row["company_name"] or row["username"]) for row in query_db("SELECT username, company_name FROM users")}
    order_sellers = {order["id"]: sorted({seller_names.get(item["seller"], item["seller"]) for item in order_items[order["id"]]}) for order in customer_orders}
    vendor_notification_count = 0
    vendor_notifications = []
    if is_vendor:
        vendor = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
        if vendor:
            vendor_notification_count_row = query_db("SELECT COUNT(*) AS count FROM vendor_notifications WHERE vendor_id = ? AND is_read = 0", (vendor["id"],), one=True)
            vendor_notification_count = vendor_notification_count_row["count"] if vendor_notification_count_row else 0
            vendor_notifications = query_db("SELECT * FROM vendor_notifications WHERE vendor_id = ? ORDER BY id DESC LIMIT 30", (vendor["id"],))
    return render_template("orders.html", customer_orders=customer_orders, vendor_orders=vendor_orders, order_items=order_items, order_sellers=order_sellers, vendor_notification_count=vendor_notification_count, vendor_notifications=vendor_notifications)

@app.route("/orders/<int:order_id>/confirm", methods=["POST"])
def confirm_order(order_id):
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    order = query_db("SELECT * FROM orders WHERE id = ?", (order_id,), one=True)
    order_items = query_db("SELECT * FROM order_items WHERE order_id = ? AND seller = ?", (order_id, session["username"]))
    if order and order["payment_status"] == "Marked paid" and order["status"] == "Pending" and order_items:
        for item in order_items:
            query_db("UPDATE products SET stock_quantity = MAX(stock_quantity - ?, 0), status = CASE WHEN stock_quantity <= ? THEN 'Sold' ELSE 'Available' END WHERE id = ?", (item["quantity"], item["quantity"], item["product_id"]))
        query_db("UPDATE orders SET status = 'Confirmed', payment_status = 'Confirmed' WHERE id = ?", (order_id,))
    return redirect(url_for("order_history"))

@app.route("/orders/<int:order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    if query_db("SELECT id FROM order_items WHERE order_id = ? AND seller = ?", (order_id, session["username"])):
        query_db("UPDATE orders SET status = 'Cancelled' WHERE id = ?", (order_id,))
    return redirect(url_for("order_history"))
@app.route("/vendor/<username>")
def vendor_profile(username):
    vendor = query_db(
        "SELECT * FROM users WHERE username = ? AND role IN ('Vendor', 'Fast Food')",
        (username,), one=True
    )
    if not vendor:
        return redirect(url_for("home"))
    products = query_db(
        "SELECT * FROM products WHERE seller = ? ORDER BY id DESC",
        (username,)
    )
    categories = get_vendor_categories(vendor["id"])
    now_iso = datetime.now(timezone.utc).isoformat()
    promo = query_db(
        "SELECT * FROM promotions WHERE vendor_id = ? AND active = 1 AND starts_at <= ? AND ends_at >= ? ORDER BY id DESC LIMIT 1",
        (vendor["id"], now_iso, now_iso), one=True
    )
    favorite = False
    if session.get("role") == "Customer":
        customer = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
        if customer:
            favorite = bool(query_db("SELECT id FROM favorites WHERE customer_id = ? AND vendor_id = ?", (customer["id"], vendor["id"]), one=True))
    return render_template("vendor_profile.html", vendor=vendor, products=products, categories=categories, promo=promo, favorite=favorite, product_count=len(products), subscription=subscription_status(vendor))

@app.route("/favorites")
def favorites():
    if "username" not in session or session.get("role") != "Customer":
        return redirect(url_for("login"))
    customer = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    vendors = []
    if customer:
        vendors = query_db("""
            SELECT u.*,
                   (SELECT COUNT(*) FROM products p WHERE p.seller = u.username) AS product_count
            FROM favorites f
            JOIN users u ON u.id = f.vendor_id
            WHERE f.customer_id = ? AND u.role IN ('Vendor', 'Fast Food')
            ORDER BY f.id DESC
        """, (customer["id"],))
        now_iso = datetime.now(timezone.utc).isoformat()
        for vendor in vendors:
            vendor["categories"] = get_vendor_categories(vendor["id"])
            vendor["promo"] = query_db("SELECT * FROM promotions WHERE vendor_id = ? AND active = 1 AND starts_at <= ? AND ends_at >= ? ORDER BY id DESC LIMIT 1", (vendor["id"], now_iso, now_iso), one=True)
    return render_template("favorites.html", vendors=vendors)

@app.route("/favorites/toggle/<username>", methods=["POST"])
def toggle_favorite(username):
    if "username" not in session or session.get("role") != "Customer":
        return redirect(url_for("login"))
    customer = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    vendor = query_db("SELECT id FROM users WHERE username = ? AND role IN ('Vendor', 'Fast Food')", (username,), one=True)
    if not customer or not vendor or customer["id"] == vendor["id"]:
        return redirect(url_for("home"))
    existing = query_db("SELECT id FROM favorites WHERE customer_id = ? AND vendor_id = ?", (customer["id"], vendor["id"]), one=True)
    if existing:
        query_db("DELETE FROM favorites WHERE id = ?", (existing["id"],))
    else:
        query_db("INSERT INTO favorites (customer_id, vendor_id, created_at) VALUES (?, ?, ?)", (customer["id"], vendor["id"], datetime.now(timezone.utc).isoformat()))
    return redirect(request.referrer or url_for("vendor_profile", username=username))

@app.route("/notifications/<int:notification_id>/read", methods=["POST"])
def mark_notification_read(notification_id):
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    vendor = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if vendor:
        query_db("UPDATE vendor_notifications SET is_read = 1 WHERE id = ? AND vendor_id = ?", (notification_id, vendor["id"]))
    return redirect(request.referrer or url_for("order_history"))

@app.route("/notifications/read-all", methods=["POST"])
def mark_all_notifications_read():
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    vendor = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if vendor:
        query_db("UPDATE vendor_notifications SET is_read = 1 WHERE vendor_id = ?", (vendor["id"],))
    return redirect(request.referrer or url_for("order_history"))

@app.route("/promotions", methods=["GET", "POST"])
def promotions():
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    vendor = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    if not vendor:
        return redirect(url_for("login"))
    promo_error = None
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip() or None
        discount_raw = request.form.get("discount", "").strip()
        starts_at = request.form.get("starts_at", "").strip()
        ends_at = request.form.get("ends_at", "").strip()
        try:
            discount = float(discount_raw) if discount_raw else None
        except ValueError:
            discount = None
        if not title or not starts_at or not ends_at:
            promo_error = "Promotion title, start date and end date are required."
        else:
            starts_iso = starts_at.replace("T", " ") + (":00" if len(starts_at) == 16 else "")
            ends_iso = ends_at.replace("T", " ") + (":00" if len(ends_at) == 16 else "")
            if ends_iso <= starts_iso:
                promo_error = "Promotion end date must be after the start date."
            elif discount is not None and not (0 <= discount <= 100):
                promo_error = "Discount must be between 0 and 100 percent."
            else:
                query_db("UPDATE promotions SET active = 0 WHERE vendor_id = ?", (vendor["id"],))
                query_db("INSERT INTO promotions (vendor_id, title, description, discount, starts_at, ends_at, active, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)", (vendor["id"], title, description, discount, starts_iso, ends_iso, datetime.now(timezone.utc).isoformat()))
                return redirect(url_for("vendor_profile", username=vendor["username"]))
    promo_rows = query_db("SELECT * FROM promotions WHERE vendor_id = ? ORDER BY id DESC", (vendor["id"],))
    return render_template("promotions.html", vendor=vendor, promotions=promo_rows, promo_error=promo_error)

@app.route("/promotions/<int:promotion_id>/deactivate", methods=["POST"])
def deactivate_promotion(promotion_id):
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    vendor = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if vendor:
        query_db("UPDATE promotions SET active = 0 WHERE id = ? AND vendor_id = ?", (promotion_id, vendor["id"]))
    return redirect(url_for("promotions"))

@app.route("/subscription")
def subscription():
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    if not user:
        session.clear()
        return redirect(url_for("login"))
    payment_number = normalize_whatsapp_number(os.environ.get("BIZ_HUB_PAYMENT_WHATSAPP", "233558272972"))
    payment_text = quote(f"Hello Biz Hub, I want to upgrade my {session['username']} account to Premium Store.")
    return render_template("subscription.html", user=user, subscription=subscription_status(user), payment_number=payment_number, payment_text=payment_text, requested=request.args.get("requested") == "1")

@app.route("/request-premium", methods=["POST"])
def request_premium():
    if "username" not in session or session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    query_db("UPDATE users SET upgrade_requested_at = ? WHERE username = ?", (datetime.now(timezone.utc).isoformat(), session["username"]))
    return redirect(url_for("subscription", requested="1"))

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if not admin_configured():
            return render_template("admin_login.html", admin_error="Admin credentials are not configured.")
        submitted_username = request.form.get("username", "").strip()
        submitted_password = request.form.get("password", "")
        database_admin = query_db("SELECT * FROM admin_users WHERE username = ?", (submitted_username,), one=True)
        database_login = database_admin and check_password_hash(database_admin["password_hash"], submitted_password)
        configured_login = submitted_username == os.environ.get("BIZ_HUB_ADMIN_USERNAME", "").strip() and submitted_password == os.environ.get("BIZ_HUB_ADMIN_PASSWORD", "")
        local_login = submitted_username == LOCAL_ADMIN_USERNAME and submitted_password == LOCAL_ADMIN_PASSWORD
        if database_login or configured_login or local_login:
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        return render_template("admin_login.html", admin_error="Invalid admin credentials.")
    return render_template("admin_login.html", admin_configured=admin_configured(), signup_available=admin_signup_available())

@app.route("/admin/signup", methods=["GET", "POST"])
def admin_signup():
    if not admin_signup_available():
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not username or not password:
            return render_template("admin_signup.html", admin_error="Username and password are required.")
        if password != confirm_password:
            return render_template("admin_signup.html", admin_error="The passwords do not match.")
        try:
            query_db("INSERT INTO admin_users (username, password_hash, created_at) VALUES (?, ?, ?)", (username, generate_password_hash(password), datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError:
            return render_template("admin_signup.html", admin_error="That admin username is already taken.")
        return redirect(url_for("admin_login", registered="1"))
    return render_template("admin_signup.html")

@app.route("/admin")
def admin_dashboard():
    if not is_admin():
        return redirect(url_for("admin_login"))
    users = query_db("SELECT * FROM users ORDER BY COALESCE(registered_at, '') DESC, username")
    listing_counts = {row["seller"]: row["count"] for row in query_db("SELECT seller, COUNT(*) AS count FROM products GROUP BY seller")}
    ledger_entries = query_db("SELECT * FROM financial_ledger ORDER BY id DESC") or []
    
    total_rev_row = query_db("SELECT SUM(amount) AS total FROM financial_ledger WHERE status = 'Verified'", one=True)
    total_revenue = total_rev_row["total"] if total_rev_row and total_rev_row["total"] is not None else 0.0
    
    pending_momo_row = query_db("SELECT SUM(amount) AS total FROM financial_ledger WHERE status = 'Pending'", one=True)
    pending_momo = pending_momo_row["total"] if pending_momo_row and pending_momo_row["total"] is not None else 0.0
    
    verified_count_row = query_db("SELECT COUNT(*) AS count FROM financial_ledger WHERE status = 'Verified'", one=True)
    verified_count = verified_count_row["count"] if verified_count_row and verified_count_row["count"] is not None else 0
    
    return render_template("admin.html", users=users, subscription_status=subscription_status, listing_counts=listing_counts, ledger_entries=ledger_entries, total_revenue=total_revenue, pending_momo=pending_momo, verified_count=verified_count)

@app.route("/admin/verify-transaction/<int:entry_id>", methods=["POST"])
def verify_transaction(entry_id):
    if not is_admin(): 
        return redirect(url_for("admin_login"))
    query_db("UPDATE financial_ledger SET status = 'Verified' WHERE id = ?", (entry_id,))
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/log-payment", methods=["POST"])
def log_payment():
    if not is_admin():
        return redirect(url_for("admin_login"))
    username = request.form.get("username")
    amount = float(request.form.get("amount", 0.0))
    tx_type = request.form.get("transaction_type", "Subscription")
    ref = request.form.get("momo_reference", "").strip() or f"WA-{uuid.uuid4().hex[:8].upper()}"
    query_db("INSERT INTO financial_ledger (transaction_type, username, amount, momo_reference, status, created_at) VALUES (?, ?, ?, ?, 'Pending', ?)", (tx_type, username, amount, ref, datetime.now(timezone.utc).isoformat()))
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/approve-premium/<int:user_id>", methods=["POST"])
def approve_premium(user_id):
    if not is_admin():
        return redirect(url_for("admin_login"))
    expiry = datetime.now(timezone.utc) + timedelta(days=30)
    query_db("UPDATE users SET plan = 'premium', subscription_expires_at = ?, upgrade_requested_at = NULL WHERE id = ? AND (role = 'Vendor' OR role = 'Fast Food')", (expiry.isoformat(), user_id))
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/delete-user/<int:user_id>", methods=["POST"])
def admin_delete_user(user_id):
    if not is_admin():
        return redirect(url_for("admin_login"))
    user = query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if not user:
        return redirect(url_for("admin_dashboard"))
    product_rows = query_db("SELECT image_file, video_file FROM products WHERE seller = ?", (user["username"],)) or []
    for product in product_rows:
        for filename in (product["image_file"], product["video_file"], user["company_logo"]):
            if filename:
                file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
    order_ids = {row["order_id"] for row in query_db("SELECT order_id FROM order_items WHERE seller = ?", (user["username"],)) if row}
    order_ids.update(row["id"] for row in query_db("SELECT id FROM orders WHERE customer_username = ?", (user["username"],)) if row)
    query_db("DELETE FROM order_items WHERE seller = ?", (user["username"],))
    for order_id in order_ids:
        if not query_db("SELECT id FROM order_items WHERE order_id = ?", (order_id,)):
            query_db("DELETE FROM orders WHERE id = ?", (order_id,))
    query_db("DELETE FROM products WHERE seller = ?", (user["username"],))
    query_db("DELETE FROM vendor_categories WHERE user_id = ?", (user["id"],))
    query_db("DELETE FROM favorites WHERE vendor_id = ? OR customer_id = ?", (user["id"], user["id"]))
    query_db("DELETE FROM vendor_notifications WHERE vendor_id = ?", (user["id"],))
    query_db("DELETE FROM promotions WHERE vendor_id = ?", (user["id"],))
    query_db("DELETE FROM password_resets WHERE user_id = ?", (user["id"],))
    query_db("DELETE FROM users WHERE id = ?", (user_id,))
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))

@app.route("/settings", methods=["GET", "POST"])
def settings():
    if "username" not in session:
        return redirect(url_for("login"))
    current_username = session["username"]
    user = query_db("SELECT * FROM users WHERE username = ?", (current_username,), one=True)
    if not user:
        session.clear()
        return redirect(url_for("login"))

    is_vendor_any = user["role"] in ["Vendor", "Fast Food"]
    vendor_categories = get_vendor_categories(user["id"]) if is_vendor_any else []

    if request.method == "POST":
        new_username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        whatsapp_number = normalize_whatsapp_number(request.form.get("whatsapp_number"))
        company_name = request.form.get("company_name", "").strip() or None
        business_location = request.form.get("business_location", "").strip() or None
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        theme = request.form.get("theme", "day")
        company_logo = user["company_logo"]
        logo_upload = request.files.get("company_logo")
        catalog_mode = request.form.get("catalog_mode", "Focused")
        selected_categories = [category for category in request.form.getlist("vendor_categories") if category in VENDOR_CATEGORIES]

        if not new_username:
            return render_template("settings.html", user=user, vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, settings_error="Username is required.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", new_username):
            return render_template("settings.html", user=user, vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, settings_error="Username must be 3-40 characters and use only letters, numbers, dots, underscores, or hyphens.")
        if new_username != current_username:
            existing = query_db("SELECT id FROM users WHERE username = ?", (new_username,), one=True)
            if existing:
                return render_template("settings.html", user=user, vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, settings_error="That username is already in use.")
        if not email:
            return render_template("settings.html", user=user, vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, settings_error="Email is required.")
        if is_vendor_any and not whatsapp_number:
            return render_template("settings.html", user=user, vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, settings_error="Vendor accounts need a WhatsApp number for payments.")
        if new_password and new_password != confirm_password:
            return render_template("settings.html", user=user, vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, settings_error="The new passwords do not match.")
        if theme not in ("day", "night"):
            theme = "day"
        if logo_upload and logo_upload.filename:
            company_logo = save_company_logo(logo_upload)
            if not company_logo:
                return render_template("settings.html", user=user, vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, settings_error="Upload a PNG, JPG, JPEG, WEBP, or GIF logo.")

        if not is_vendor_any:
            company_name = None
            business_location = None
            whatsapp_number = None
            catalog_mode = None
            selected_categories = []
            company_logo = None
        elif catalog_mode not in ("Variety", "Focused"):
            catalog_mode = user.get("catalog_mode") or "Focused"

        # Product ranges are optional in Settings. If none are checked, preserve the
        # vendor's existing ranges instead of blocking unrelated changes such as theme,
        # username, logo, business name or location.
        if is_vendor_any and not selected_categories:
            selected_categories = vendor_categories

        password_hash = generate_password_hash(new_password) if new_password else user["password_hash"]
        query_db(
            "UPDATE users SET username = ?, email = ?, password_hash = ?, company_name = ?, whatsapp_number = ?, catalog_mode = ?, company_logo = ?, business_location = ?, theme = ? WHERE id = ?",
            (new_username, email, password_hash, company_name, whatsapp_number, catalog_mode, company_logo, business_location, theme, user["id"])
        )

        # Keep username-based marketplace references synchronized when a user renames their account.
        if new_username != current_username:
            query_db("UPDATE products SET seller = ? WHERE seller = ?", (new_username, current_username))
            query_db("UPDATE order_items SET seller = ? WHERE seller = ?", (new_username, current_username))
            query_db("UPDATE orders SET customer_username = ? WHERE customer_username = ?", (new_username, current_username))
            query_db("UPDATE financial_ledger SET username = ? WHERE username = ?", (new_username, current_username))
            query_db("UPDATE vendor_notifications SET customer_username = ? WHERE customer_username = ?", (new_username, current_username))

        query_db("DELETE FROM vendor_categories WHERE user_id = ?", (user["id"],))
        for category in selected_categories:
            query_db("INSERT INTO vendor_categories (user_id, category) VALUES (?, ?)", (user["id"], category))

        session["username"] = new_username
        session["email"] = email
        session["company_name"] = company_name
        session["business_location"] = business_location
        session["whatsapp_number"] = whatsapp_number
        session["theme"] = theme
        return redirect(url_for("settings", updated="1"))

    return render_template(
        "settings.html",
        user=user,
        subscription=subscription_status(user),
        vendor_categories=vendor_categories,
        vendor_category_options=VENDOR_CATEGORIES,
        updated=request.args.get("updated") == "1"
    )
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("login_user")
        password = request.form.get("login_pass")
        user = query_db("SELECT * FROM users WHERE username = ?", (username,), one=True)
        if user and check_password_hash(user["password_hash"], password):
            session["username"] = user["username"]
            session["email"] = user["email"]
            session["role"] = user["role"]
            session["seller_type"] = user["seller_type"]
            session["company_name"] = user["company_name"]
            session["business_location"] = user.get("business_location")
            session["whatsapp_number"] = user["whatsapp_number"]
            session["theme"] = user["theme"] or "day"
            return redirect(url_for("home"))
        return render_template("login.html", login_error="Invalid username or password.")
    return render_template("login.html")

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    reset_error = None
    reset_link = None
    if request.method == "POST":
        whatsapp_number = normalize_whatsapp_number(request.form.get("whatsapp_number"))
        user = query_db("SELECT * FROM users WHERE whatsapp_number = ?", (whatsapp_number,), one=True)
        if not user:
            reset_error = "No account was found with that registered WhatsApp number."
        else:
            token = uuid.uuid4().hex
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
            query_db("INSERT INTO password_resets (user_id, token, expires_at) VALUES (?, ?, ?)", (user["id"], token, expires_at))
            reset_link = url_for("reset_credentials", token=token, _external=True)
            payment_number = normalize_whatsapp_number(os.environ.get("BIZ_HUB_PAYMENT_WHATSAPP", "233558272972"))
            reset_text = quote(f"Hello Biz Hub, I need to recover my account registered with WhatsApp {whatsapp_number}. My reset link is: {reset_link}")
            reset_link = f"https://wa.me{payment_number}?text={reset_text}"
    return render_template("forgot_password.html", reset_error=reset_error, reset_link=reset_link)

@app.route("/reset-credentials/<token>", methods=["GET", "POST"])
def reset_credentials(token):
    reset = valid_reset_token(token)
    if not reset:
        return render_template("reset_credentials.html", reset_error="This recovery link is invalid or has expired.", token=None)
    user = query_db("SELECT * FROM users WHERE id = ?", (reset["user_id"],), one=True)
    if request.method == "POST":
        new_username = request.form.get("username", "").strip()
        new_password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not new_username or not new_password:
            return render_template("reset_credentials.html", reset_error="Username and password are required.", token=token, user=user)
        if new_password != confirm_password:
            return render_template("reset_credentials.html", reset_error="The passwords do not match.", token=token, user=user)
        try:
            query_db("UPDATE users SET username = ?, password_hash = ? WHERE id = ?", (new_username, generate_password_hash(new_password), user["id"]))
            query_db("UPDATE password_resets SET used = 1 WHERE id = ?", (reset["id"],))
        except sqlite3.IntegrityError:
            return render_template("reset_credentials.html", reset_error="That username is already taken.", token=token, user=user)
        return redirect(url_for("login", recovered="1"))
    return render_template("reset_credentials.html", token=token, user=user)

@app.route("/register", methods=["GET", "POST"])
def register():
    """Handles multi-tier merchant registrations, configuring complementary trials securely."""
    if request.method == "POST":
        username = request.form.get("reg_user", "").strip()
        email = request.form.get("reg_email", "").strip()
        password = request.form.get("reg_pass", "")
        submitted_role = request.form.get("role", "").strip()
        role_aliases = {"customer": "Customer", "vendor": "Vendor", "fast food": "Fast Food"}
        role = role_aliases.get(submitted_role.lower(), submitted_role)
        
        if not username or not email or not password:
            return render_template("login.html", reg_error="Username, email, and password are required.")
            
        seller_type = request.form.get("seller_type", "Individual")
        catalog_mode = request.form.get("catalog_mode", "Focused")
        selected_categories = [category for category in request.form.getlist("vendor_categories") if category in VENDOR_CATEGORIES]
        company_name = request.form.get("company_name", "").strip() or None
        business_location = request.form.get("business_location", "").strip() or None
        whatsapp_number = normalize_whatsapp_number(request.form.get("whatsapp_number"))
        
        logo_upload = request.files.get("company_logo")
        company_logo_filename = None
        if logo_upload and logo_upload.filename:
            company_logo_filename = save_company_logo(logo_upload)
        
        if role == "Fast Food":
            seller_type = "Fast Food"
            catalog_mode = "Focused"
            selected_categories = ["Fast Food"]
        elif role == "Vendor" and seller_type == "Individual":
            company_name = None
            
        if role == "Customer":
            seller_type = "Individual"
            company_name = None
            whatsapp_number = None
            catalog_mode = None
            selected_categories = []
            company_logo_filename = None
            
        if role in ["Vendor", "Fast Food"] and not whatsapp_number:
            return render_template("login.html", reg_error="Merchant and Fast Food vendor accounts need a compulsory WhatsApp number to receive order tallies.")
        if role == "Vendor" and (catalog_mode not in ("Variety", "Focused") or not selected_categories):
            return render_template("login.html", reg_error="Choose a product range and select at least one category.")
            
        try:
            hashed_pwd = generate_password_hash(password)
            trial_started_at = datetime.now(timezone.utc)
            trial_expires_at = trial_started_at + timedelta(days=60) # 2-Month Promotional Package Active
            user_plan = "premium" if role in ["Vendor", "Fast Food"] else "basic"
            
            # 👑 EXPLICIT SAFE WRITE CONNECTOR - RE-ORDERED FOR FOREIGN KEY INTEGRITY
            conn = sqlite3.connect("marketplace.db", timeout=20)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, email, password_hash, role, seller_type, company_name, whatsapp_number, plan, trial_started_at, subscription_expires_at, catalog_mode, company_logo, business_location, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (username, email, hashed_pwd, role, seller_type, company_name, whatsapp_number, user_plan, trial_started_at.isoformat() if role in ["Vendor", "Fast Food"] else None, trial_expires_at.isoformat() if role in ["Vendor", "Fast Food"] else None, catalog_mode, company_logo_filename, business_location, datetime.now(timezone.utc).isoformat())
            )
            inserted_id = cursor.lastrowid
            
            # 🚀 CRITICAL STEP: Commit parent user record immediately so foreign keys can find it!
            conn.commit()
            
            if inserted_id and selected_categories:
                for category in selected_categories:
                    cursor.execute("INSERT INTO vendor_categories (user_id, category) VALUES (?, ?)", (inserted_id, category))
                # Commit secondary relational items safely
                conn.commit()
                    
            conn.close()
                    
            session.clear()
            session["username"] = username
            session["email"] = email
            session["role"] = role
            session["seller_type"] = seller_type
            session["company_name"] = company_name
            session["business_location"] = business_location
            session["whatsapp_number"] = whatsapp_number
            return redirect(url_for("home"))
            
        except sqlite3.IntegrityError:
            return render_template("login.html", reg_error="Username is already taken.")
            
    return redirect(url_for("login"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))
# 👑 MASTER VIDEO CHUNK STREAMING SYSTEM: Fixes blank video screens on mobile browsers
@app.route("/stream-video/<filename>")
def stream_video(filename):
    """Serve product videos with proper HTTP Range support for mobile browsers."""
    # Never allow a URL path to escape the uploads directory.
    safe_name = os.path.basename(filename)
    video_path = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)
    if not os.path.isfile(video_path):
        return "Video not found", 404

    # Flask/Werkzeug handles Range, Content-Range, Content-Length, 206/416,
    # HEAD requests, and conditional requests when conditional=True.
    video_mimetype = mimetypes.guess_type(video_path)[0] or "application/octet-stream"
    return send_file(
        video_path,
        mimetype=video_mimetype,
        conditional=True,
        etag=True,
        max_age=0,
    )

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
