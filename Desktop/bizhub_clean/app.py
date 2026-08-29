import sqlite3
import os
import uuid
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, render_template_string
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "commercial_marketplace_super_secret_token"
LOCAL_ADMIN_USERNAME = "Stapps Of Faith"
LOCAL_ADMIN_PASSWORD = "RICHARD10"
PRODUCT_CATEGORIES = ["Phones & Accessories", "Groceries", "Clothing", "Books", "Health & Beauty", "Beauty & Personal Care", "Home & Kitchen", "Electronics", "Fast Food", "Other"]
VENDOR_CATEGORIES = PRODUCT_CATEGORIES + ["Health & Beauty", "Fast Food"]
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov"}

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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
        
        # 👑 BULLETPROOF MULTI-MEDIA FILE IDENTIFICATION MATRIX
        has_image = bool(file and file.filename)
        has_video = bool(video and video.filename)
        
        # 👑 THE MASTER BUSINESS RULE FILTER: Enforces exactly one image OR max 20s video
        if not is_fast_food and has_image == has_video:
            return redirect(url_for("home", listing_error="Invalid Media Config: You must choose exactly one option—either an Item Cover Photo OR a maximum 20-second Showcase Video loop."))

        if has_image:
            filename = secure_filename(file.filename)
        else:
            filename = "fast-food-placeholder.svg" if is_fast_food else ""

        if has_video:
            # 🚀 FIXED THE TUPLE EXTENSION TRACKER INDEX BLOCK
            video_extension = os.path.splitext(video.filename)[1].lower()
            if not vendor_subscription["is_premium"]:
                return redirect(url_for("home", listing_error="Only verified vendors with an active Premium Store or trial can upload product videos."))
            if video_extension not in VIDEO_EXTENSIONS:
                return redirect(url_for("home", listing_error="Product videos must be MP4, WebM, or MOV files."))
            
            video_filename = f"video-{uuid.uuid4().hex}{video_extension}"
            temp_video_path = os.path.join(app.config["UPLOAD_FOLDER"], video_filename)
            
            # Save the file exactly ONCE right here to analyze duration properties securely
            video.save(temp_video_path)

            # ⏱️ BACKEND BOUNDARY WALL: Verify that video runtime metadata does not exceed 20 seconds
            try:
                import subprocess
                ffprobe_command = [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", temp_video_path
                ]
                probe_output = subprocess.check_output(ffprobe_command).decode("utf-8").strip()
                parsed_duration = float(probe_output)
                
                if parsed_duration > 20.5:
                    os.remove(temp_video_path) # Instantly flush oversized file to save disk footprint
                    return redirect(url_for("home", listing_error="🚫 UPLOAD REFUSED: Showcase loops are strictly limited to a maximum of 20 seconds to keep load speeds instant for mobile users across Ghana."))
            except Exception:
                # Fallback guard if server utilities hit lock bounds
                pass
        else:
            video_filename = None

        try:
            stock_quantity = int(stock_quantity)
        except (TypeError, ValueError):
            return redirect(url_for("home", listing_error="Stock quantity must be a whole number greater than zero."))
        if stock_quantity < 1:
            return redirect(url_for("home", listing_error="Stock quantity must be a whole number greater than zero."))

        if title and price and description and location:
            # Save the product image if applicable (Videos are already saved safely above!)
            if has_image and not is_fast_food:
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                
            b_label = session.get("company_name") if vendor_subscription["is_premium"] and session.get("company_name") else "Individual Vendor"
            
            query_db(
                "INSERT INTO products (title, price, description, image_file, video_file, stock_quantity, status, seller, seller_email, seller_whatsapp, location, business_label, category) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (title, float(price), description, filename, video_filename, stock_quantity, "Available", session["username"], session["email"], session.get("whatsapp_number"), location, b_label, category)
            )
            return redirect(url_for("home"))

            
    selected_filter = request.args.get("filter_location", "All")
    company_search = request.args.get("company_search", "").strip()
    selected_category = request.args.get("category", "All")
    listing_error = request.args.get("listing_error")
    
    product_conditions = []
    product_args = []
    
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
        
    product_query = "SELECT * FROM products"
    if product_conditions:
        product_query += " WHERE " + " AND ".join(product_conditions)
    product_query += " ORDER BY id DESC"
    
    all_products = query_db(product_query, product_args) or []
    
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
    if session.get("role") in ["Vendor", "Fast Food"]:
        vendor = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
        vendor_subscription = subscription_status(vendor)
        listing_count_row = query_db("SELECT COUNT(*) AS count FROM products WHERE seller = ?", (session["username"],), one=True)
        listing_count = listing_count_row["count"] if listing_count_row else 0
        if session.get("role") == "Fast Food":
            fast_food_count_row = query_db("SELECT COUNT(*) AS count FROM products WHERE seller = ? AND category = 'Fast Food'", (session["username"],), one=True)
            fast_food_count = fast_food_count_row["count"] if fast_food_count_row else 0

    return render_template("index.html", products=all_products, active_filter=selected_filter, company_search=company_search, selected_category=selected_category, categories=PRODUCT_CATEGORIES, vendor_logos=vendor_logos, cart_items=cart_items, cart_total=cart_total, seller_orders=sorted(seller_orders.values(), key=lambda order: not order["priority"]), vendor_subscription=vendor_subscription, listing_count=listing_count, fast_food_count=fast_food_count, listing_error=listing_error, premium_sellers=premium_sellers)
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
    vendor_orders = query_db("SELECT DISTINCT o.*, oi.seller FROM orders o JOIN order_items oi ON oi.order_id = o.id WHERE oi.seller = ? ORDER BY o.id DESC", (session["username"],)) if session.get("role") in ["Vendor", "Fast Food"] else []
    all_active_orders = (customer_orders or []) + (vendor_orders or [])
    order_items = {order["id"]: query_db("SELECT * FROM order_items WHERE order_id = ?", (order["id"],)) for order in all_active_orders}
    seller_names = {row["username"]: (row["company_name"] or row["username"]) for row in query_db("SELECT username, company_name FROM users")}
    order_sellers = {order["id"]: sorted({seller_names.get(item["seller"], item["seller"]) for item in order_items[order["id"]]}) for order in customer_orders}
    return render_template("orders.html", customer_orders=customer_orders, vendor_orders=vendor_orders, order_items=order_items, order_sellers=order_sellers)

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
    user = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    if not user:
        session.clear()
        return redirect(url_for("login"))
    is_vendor_any = user["role"] in ["Vendor", "Fast Food"]
    vendor_categories = get_vendor_categories(user["id"]) if is_vendor_any else []

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        whatsapp_number = normalize_whatsapp_number(request.form.get("whatsapp_number"))
        company_name = request.form.get("company_name", "").strip() or None
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        company_logo = user["company_logo"]
        logo_upload = request.files.get("company_logo")
        catalog_mode = request.form.get("catalog_mode", "Focused")
        selected_categories = [category for category in request.form.getlist("vendor_categories") if category in VENDOR_CATEGORIES]

        if not email:
            return render_template("settings.html", user=user, settings_error="Email is required.")
        if is_vendor_any and not whatsapp_number:
            return render_template("settings.html", user=user, settings_error="Vendor accounts need a WhatsApp number for payments.")
        if new_password and new_password != confirm_password:
            return render_template("settings.html", user=user, settings_error="The new passwords do not match.")
        if logo_upload and logo_upload.filename:
            company_logo = save_company_logo(logo_upload)
            if not company_logo:
                return render_template("settings.html", user=user, vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, settings_error="Upload a PNG, JPG, JPEG, WEBP, or GIF logo.")

        password_hash = generate_password_hash(new_password) if new_password else user["password_hash"]
        if not is_vendor_any:
            company_name = None
            whatsapp_number = None
            catalog_mode = None
            selected_categories = []
            company_logo = None
        elif catalog_mode not in ("Variety", "Focused") or not selected_categories:
            return render_template("settings.html", user=user, vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, settings_error="Choose whether you sell a variety or focus on a category, then select at least one product range.")
        query_db(
            "UPDATE users SET email = ?, password_hash = ?, company_name = ?, whatsapp_number = ?, catalog_mode = ?, company_logo = ? WHERE username = ?",
            (email, password_hash, company_name, whatsapp_number, catalog_mode, company_logo, session["username"])
        )
        query_db("DELETE FROM vendor_categories WHERE user_id = ?", (user["id"],))
        for category in selected_categories:
            query_db("INSERT INTO vendor_categories (user_id, category) VALUES (?, ?)", (user["id"], category))
        session["email"] = email
        session["company_name"] = company_name
        session["whatsapp_number"] = whatsapp_number
        return redirect(url_for("settings", updated="1"))

    return render_template("settings.html", user=user, subscription=subscription_status(user), vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, updated=request.args.get("updated") == "1")
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
            session["whatsapp_number"] = user["whatsapp_number"]
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
        company_name = request.form.get("company_name")
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
                "INSERT INTO users (username, email, password_hash, role, seller_type, company_name, whatsapp_number, plan, trial_started_at, subscription_expires_at, catalog_mode, company_logo, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (username, email, hashed_pwd, role, seller_type, company_name, whatsapp_number, user_plan, trial_started_at.isoformat() if role in ["Vendor", "Fast Food"] else None, trial_expires_at.isoformat() if role in ["Vendor", "Fast Food"] else None, catalog_mode, company_logo_filename, datetime.now(timezone.utc).isoformat())
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
            session["whatsapp_number"] = whatsapp_number
            return redirect(url_for("home"))
            
        except sqlite3.IntegrityError:
            return render_template("login.html", reg_error="Username is already taken.")
            
    return redirect(url_for("login"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
