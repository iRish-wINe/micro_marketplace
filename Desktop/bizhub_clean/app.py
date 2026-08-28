import sqlite3
import os
import uuid
import re  # Added for browser compliance parsing
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, render_template_string
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# IMPORTANT: For final deployment, move secrets and passwords to secure environment variables
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

# =========================================================================
# 👑 DEVICE ENFORCEMENT ENGINE (Blocks Legacy/Incompatible Android Engines)
# =========================================================================
# Regular expression filtering out legacy Android frameworks (Versions 1.0 through 7.9)
OUTDATED_ANDROID_REGEX = re.compile(r'Android\s([1-7]\.\d)')

@app.before_request
def enforce_device_standards():
    # Allow asset pipelines and background service workers to load normally
    if request.path.startswith('/static') or request.path == '/service-worker.js':
        return None

    user_agent = request.headers.get('User-Agent', '')
    
    # Intercept and isolate outdated Android device engines
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
    
    # ⚠️ CLEAN RE-ALIGNMENT MATRIX: All tab/space mismatches removed cleanly


    # Core User Profiles Registry
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

    # Marketplace Product Manifest
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

    # Vendor Categorization Mapping
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vendor_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            UNIQUE(user_id, category),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Administrative Controls Registry
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # Escrow Order Header Track
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

    # Order Line Items Breakdowns
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

    # Account Recovery Lifeline Token Store
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

    # Mobile Money Cash Tracking Ledger Architecture
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

    # Schema Migration Checks: Dynamic User Table Realignment
    user_columns = {row[1] for row in cursor.execute("PRAGMA table_info(users)")}
    if "whatsapp_number" not in user_columns: cursor.execute("ALTER TABLE users ADD COLUMN whatsapp_number TEXT")
    if "plan" not in user_columns: cursor.execute("ALTER TABLE users ADD COLUMN plan TEXT NOT NULL DEFAULT 'basic'")
    if "trial_started_at" not in user_columns: cursor.execute("ALTER TABLE users ADD COLUMN trial_started_at TEXT")
    if "subscription_expires_at" not in user_columns: cursor.execute("ALTER TABLE users ADD COLUMN subscription_expires_at TEXT")
    if "upgrade_requested_at" not in user_columns: cursor.execute("ALTER TABLE users ADD COLUMN upgrade_requested_at TEXT")
    if "catalog_mode" not in user_columns: cursor.execute("ALTER TABLE users ADD COLUMN catalog_mode TEXT")
    if "company_logo" not in user_columns: cursor.execute("ALTER TABLE users ADD COLUMN company_logo TEXT")
    if "registered_at" not in user_columns: cursor.execute("ALTER TABLE users ADD COLUMN registered_at TEXT")

    # Schema Migration Checks: Dynamic Product Table Realignment
    product_columns = {row[1] for row in cursor.execute("PRAGMA table_info(products)")}
    if "seller_whatsapp" not in product_columns: cursor.execute("ALTER TABLE products ADD COLUMN seller_whatsapp TEXT")
    if "category" not in product_columns: cursor.execute("ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT 'Other'")
    if "video_file" not in product_columns: cursor.execute("ALTER TABLE products ADD COLUMN video_file TEXT")
    if "stock_quantity" not in product_columns: cursor.execute("ALTER TABLE products ADD COLUMN stock_quantity INTEGER NOT NULL DEFAULT 1")
    if "status" not in product_columns: cursor.execute("ALTER TABLE products ADD COLUMN status TEXT NOT NULL DEFAULT 'Available'")
    if "views" not in product_columns: cursor.execute("ALTER TABLE products ADD COLUMN views INTEGER NOT NULL DEFAULT 0")

    # Schema Migration Checks: Dynamic Order Table Realignment
    order_columns = {row[1] for row in cursor.execute("PRAGMA table_info(orders)")}
    if "payment_status" not in order_columns: cursor.execute("ALTER TABLE orders ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'Unpaid'")

    conn.commit()
    conn.close()

# Execute Database Bootup Sequence
init_db()
# =========================================================================
# GLOBAL MERCHANDISING LOGIC & FORMATTING FILTERS
# =========================================================================

def normalize_whatsapp_number(number):
    """Parses international dial layouts for local West African nodes (Ghana country indicator)."""
    digits = "".join(character for character in (number or "") if character.isdigit())
    if digits.startswith("0"):
        digits = "233" + digits[1:]
    return digits


def subscription_status(user):
    """Computes subscription status matrix limits based on localized expiration timestamps."""
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


# =========================================================================
# ADMIN ENVIRONMENT SETTINGS AND FLAGS
# =========================================================================

def admin_configured():
    """Validates operational integrity of configuration states."""
    return bool(get_admin_username() and get_admin_password()) or bool(query_db("SELECT id FROM admin_users LIMIT 1"))


def get_admin_username():
    """Fetches core credentials prioritizing local environment injection."""
    return os.environ.get("BIZ_HUB_ADMIN_USERNAME") or LOCAL_ADMIN_USERNAME


def get_admin_password():
    """Fetches core keys prioritizing local environment injection."""
    return os.environ.get("BIZ_HUB_ADMIN_PASSWORD") or LOCAL_ADMIN_PASSWORD


def admin_signup_available():
    """Blocks multiple admin registrations to prevent privilege abuse."""
    return not bool(query_db("SELECT id FROM admin_users LIMIT 1"))


def is_admin():
    """Evaluates the authorization bit of active sessions."""
    return session.get("is_admin") is True


# =========================================================================
# ASSET SHUTTLE DEPLOYMENT PLUGINS
# =========================================================================

@app.route("/service-worker.js")
def service_worker():
    """Serves PWA asset components with exact MIME mapping headers."""
    return send_from_directory(app.static_folder, "service-worker.js", mimetype="application/javascript")


# =========================================================================
# SYSTEM STACK ROUTING LAYER (DATABASES METRICS)
# =========================================================================

def query_db(query, args=(), one=False):
    """Executes database transactions safely using row mapping structures."""
    conn = sqlite3.connect("marketplace.db", timeout=20)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(query, args)
    rv = cursor.fetchall()
    conn.commit()
    conn.close()
    
    # 🧠 FIXED: Standard companion parameters added to prevent dictionary key array crashes
    if rv:
        return rv[0] if one else rv
    return None



def get_vendor_categories(user_id):
    """Collects multi-range catalog bounds assigned to vendor identities."""
    return [row["category"] for row in query_db("SELECT category FROM vendor_categories WHERE user_id = ? ORDER BY category", (user_id,))]


def valid_reset_token(token):
    """Validates active tokens within the validation expiration window."""
    if not token:
        return None
    return query_db("SELECT * FROM password_resets WHERE token = ? AND used = 0", (token,), one=True)


def save_company_logo(upload):
    """Saves brand assets while safely converting them to dynamic identifiers."""
    if not upload or not upload.filename:
        return None
    extension = os.path.splitext(upload.filename).lower()
    if extension not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return None
    filename = f"company-{uuid.uuid4().hex}{extension}"
    upload.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    return filename
# =========================================================================
# CENTRAL STOREFRONT FEED & CATALOG MATRIX CONTROLLER
# =========================================================================

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        # Authorization Barrier: Enforce merchant status for listing actions
        if "username" not in session or session.get("role") not in ["Vendor", "Fast Food"]:
            return redirect(url_for("home"))
            
        vendor = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
        vendor_subscription = subscription_status(vendor)
        listing_count = query_db("SELECT COUNT(*) AS count FROM products WHERE seller = ?", (session["username"],), one=True)["count"]
        
        # Guardrail: Free basic standard tier constraints
        if not vendor_subscription["is_premium"] and listing_count >= 3:
            return redirect(url_for("home", listing_error="Basic accounts can list up to 3 products. Upgrade to Premium for unlimited listings."))

        price = request.form.get("price")
        is_fast_food = vendor["seller_type"] == "Fast Food" or session.get("role") == "Fast Food"
        
        # Structural Mapping: Adapt form payload properties based on merchant specialization
        title = request.form.get("meal_name" if is_fast_food else "title")
        description = request.form.get("meal_description" if is_fast_food else "description")
        category = "Fast Food" if is_fast_food else request.form.get("category", "Other")
        stock_quantity = request.form.get("stock_quantity", "1")
        location = request.form.get("location")
        file = request.files.get("product_image")
        video = request.files.get("product_video")
        video_filename = None
        
        # Media Validation: Assess premium video allocation limits
        if video and video.filename:
            video_extension = os.path.splitext(video.filename).lower()
            if not vendor_subscription["is_premium"]:
                return redirect(url_for("home", listing_error="Only verified vendors with an active Premium Store or trial can upload product videos."))
            if video_extension not in VIDEO_EXTENSIONS:
                return redirect(url_for("home", listing_error="Product videos must be MP4, WebM, or MOV files."))
            video_filename = f"video-{uuid.uuid4().hex}{video_extension}"
            
        filename = "fast-food-placeholder.svg" if is_fast_food else secure_filename(file.filename) if file and file.filename else ""

        has_image = bool(file and file.filename)
        has_video = bool(video and video.filename)
        
        # Logic Constraint Check: Ensure single media component type rule
        if not is_fast_food and has_image == has_video:
            return redirect(url_for("home", listing_error="Choose exactly one product image or video."))

        try:
            stock_quantity = int(stock_quantity)
        except (TypeError, ValueError):
            return redirect(url_for("home", listing_error="Stock quantity must be a whole number greater than zero."))
        if stock_quantity < 1:
            return redirect(url_for("home", listing_error="Stock quantity must be a whole number greater than zero."))

        # Persist Entity Record inside Database Matrix
        if title and price and description and location:
            if has_image and not is_fast_food:
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            if video_filename:
                video.save(os.path.join(app.config["UPLOAD_FOLDER"], video_filename))
                
            b_label = session.get("company_name") if vendor_subscription["is_premium"] and session.get("company_name") else "Individual Vendor"
            
            query_db(
                "INSERT INTO products (title, price, description, image_file, video_file, stock_quantity, status, seller, seller_email, seller_whatsapp, location, business_label, category) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (title, float(price), description, filename, video_filename, stock_quantity, "Available", session["username"], session["email"], session.get("whatsapp_number"), location, b_label, category)
            )
            return redirect(url_for("home"))
            
    # Parse Request Arguments for Catalog View Trimming
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
    
    all_products = query_db(product_query, product_args)
    
    vendor_logos = {
        row["username"]: row["company_logo"]
        for row in query_db("SELECT username, company_logo FROM users WHERE company_logo IS NOT NULL")
    }

    cart_items = []
    cart_total = 0.0
    seller_orders = {}

    # Shopping Basket Computation Layer
    if "cart" in session and session["cart"]:
        placeholders = ",".join("?" for _ in session["cart"])
        items_in_db = query_db(f"SELECT * FROM products WHERE id IN ({placeholders})", session["cart"])
        if items_in_db:
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

    # West African P2P Checkout Engine: Formulating WhatsApp message payload strings cleanly
    for seller_order in seller_orders.values():
        message = f"Hello {seller_order['seller']}, I want to buy these products on Biz Hub:\n"
        for item in seller_order["items"]:
            message += f"- {item['title']} (GH₵{item['price']}) in {item['location']}\n"
        message += f"\nTotal Cost: GH₵{seller_order['total']:.2f}. Let's arrange for payment and delivery."
        seller_order["whatsapp_text"] = quote(message)

    # Priority Delivery Sorting Engine via active timestamp checking matrices
    premium_rows = query_db("SELECT username FROM users WHERE (role = 'Vendor' OR role = 'Fast Food') AND plan = 'premium' AND subscription_expires_at > ?", (datetime.now(timezone.utc).isoformat(),))
    premium_sellers = {row["username"] for row in premium_rows} if premium_rows else set()

    trial_rows = query_db("SELECT username FROM users WHERE (role = 'Vendor' OR role = 'Fast Food') AND plan = 'basic' AND subscription_expires_at > ?", (datetime.now(timezone.utc).isoformat(),))
    trial_sellers = {row["username"] for row in trial_rows} if trial_rows else set()

    premium_sellers.update(trial_sellers)
    for seller_order in seller_orders.values():
        seller_order["priority"] = seller_order["seller"] in premium_sellers

    vendor_subscription = None
    listing_count = 0
    fast_food_count = 0
    if session.get("role") in ["Vendor", "Fast Food"]:
        vendor = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
        vendor_subscription = subscription_status(vendor)
        listing_count = query_db("SELECT COUNT(*) AS count FROM products WHERE seller = ?", (session["username"],), one=True)["count"]
        if session.get("role") == "Fast Food":
            fast_food_count = query_db("SELECT COUNT(*) AS count FROM products WHERE seller = ? AND category = 'Fast Food'", (session["username"],), one=True)["count"]

    return render_template("index.html", products=all_products, active_filter=selected_filter, company_search=company_search, selected_category=selected_category, categories=PRODUCT_CATEGORIES, vendor_logos=vendor_logos, cart_items=cart_items, cart_total=cart_total, seller_orders=sorted(seller_orders.values(), key=lambda order: not order["priority"]), vendor_subscription=vendor_subscription, listing_count=listing_count, fast_food_count=fast_food_count, listing_error=listing_error, premium_sellers=premium_sellers)


# =========================================================================
# ASSET MUTATION CONTROL CHANNELS (STOCK RE-ALIGNMENT METRICS)
# =========================================================================

@app.route("/delete-item/<int:product_id>")
def delete_item(product_id):
    if "username" not in session:
        return redirect(url_for("login"))
    product = query_db("SELECT * FROM products WHERE id = ?", (product_id,), one=True)
    if product and product["seller"] == session["username"]:
        query_db("DELETE FROM products WHERE id = ?", (product_id,))
    return redirect(url_for("home"))


# =========================================================================
# CART AND STOCK INVENTORY MANAGEMENT
# =========================================================================

@app.route("/add-to-cart/<int:product_id>")
def add_to_cart(product_id):
    """Adds an item to the session-based cart if it is in stock and available."""
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
    """Allows vendors to mark a specific quantity of a product as sold."""
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
        
    product = query_db("SELECT stock_quantity FROM products WHERE id = ? AND seller = ?", (product_id, session["username"]), one=True)
    if product:
        try:
            sold_quantity = int(request.form.get("sold_quantity", "1"))
        except (TypeError, ValueError):
            sold_quantity = 0
            
        if 1 <= sold_quantity <= product["stock_quantity"]:
            query_db(
                "UPDATE products SET stock_quantity = MAX(stock_quantity - ?, 0), "
                "status = CASE WHEN stock_quantity <= ? THEN 'Sold' ELSE 'Available' END "
                "WHERE id = ? AND seller = ?", 
                (sold_quantity, sold_quantity, product_id, session["username"])
            )
    return redirect(url_for("home"))


# =========================================================================
# ESCROW ORDER MANAGEMENT PIPELINE
# =========================================================================

@app.route("/place-order", methods=["POST"])
def place_order():
    """Converts items currently in the cart into a formal pending system order."""
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
    
    query_db(
        "INSERT INTO orders (customer_username, total, status, payment_status, created_at) VALUES (?, ?, 'Pending', 'Unpaid', ?)", 
        (session["username"], total, created_at)
    )
    
    order_id = query_db(
        "SELECT id FROM orders WHERE customer_username = ? AND created_at = ? ORDER BY id DESC LIMIT 1", 
        (session["username"], created_at), 
        one=True
    )["id"]
    
    for item in items:
        query_db(
            "INSERT INTO order_items (order_id, product_id, seller, title, price, quantity) VALUES (?, ?, ?, ?, ?, 1)", 
            (order_id, item["id"], item["seller"], item["title"], item["price"])
        )
        
    session.pop("cart", None)
    return redirect(url_for("order_history"))


@app.route("/orders/<int:order_id>/payment-sent", methods=["POST"])
def mark_payment_sent(order_id):
    """Allows buyers to flag a pending order as paid after sending funds via MoMo."""
    if "username" not in session:
        return redirect(url_for("login"))
        
    query_db(
        "UPDATE orders SET payment_status = 'Marked paid' WHERE id = ? AND customer_username = ? AND status = 'Pending'", 
        (order_id, session["username"])
    )
    return redirect(url_for("order_history"))
# =========================================================================
# CENTRAL LOGISTICS DASHBOARD AND ESCROW TERMINALS
# =========================================================================

@app.route("/orders")
def order_history():
    """Compiles complete historic customer logs and merchant ledger logs."""
    if "username" not in session:
        return redirect(url_for("login"))
        
    # Fetch chronological buy sheets assigned to customer identity
    customer_orders = query_db("SELECT * FROM orders WHERE customer_username = ? ORDER BY id DESC", (session["username"],))
    
    # Isolate cross-joined distinct rows corresponding to vendor sales lines
    vendor_orders = query_db(
        "SELECT DISTINCT o.*, oi.seller FROM orders o "
        "JOIN order_items oi ON oi.order_id = o.id "
        "WHERE oi.seller = ? ORDER BY o.id DESC", 
        (session["username"],)
    ) if session.get("role") in ["Vendor", "Fast Food"] else []
    
    # Map item lists to respective order header contexts
    all_active_orders = (customer_orders or []) + (vendor_orders or [])
    order_items = {
        order["id"]: query_db("SELECT * FROM order_items WHERE order_id = ?", (order["id"],)) 
        for order in all_active_orders
    }
    
    # Index vendor brand alignments for lookup rendering
    seller_names = {
        row["username"]: (row["company_name"] or row["username"])
        for row in query_db("SELECT username, company_name FROM users")
    }
    
    order_sellers = {
        order["id"]: sorted({seller_names.get(item["seller"], item["seller"]) for item in order_items[order["id"]]})
        for order in (customer_orders or [])
    }
    
    return render_template(
        "orders.html", 
        customer_orders=customer_orders, 
        vendor_orders=vendor_orders, 
        order_items=order_items, 
        order_sellers=order_sellers
    )


@app.route("/orders/<int:order_id>/confirm", methods=["POST"])
def confirm_order(order_id):
    """Verifies marked incoming payments, decrements stock levels, and locks orders."""
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
        
    order = query_db("SELECT * FROM orders WHERE id = ?", (order_id,), one=True)
    order_items = query_db("SELECT * FROM order_items WHERE order_id = ? AND seller = ?", (order_id, session["username"]))
    
    # State Engine Guardrail: Confirm payment claims match vendor allocation lines
    if order and order["payment_status"] == "Marked paid" and order["status"] == "Pending" and order_items:
        for item in order_items:
            query_db(
                "UPDATE products SET stock_quantity = MAX(stock_quantity - ?, 0), "
                "status = CASE WHEN stock_quantity <= ? THEN 'Sold' ELSE 'Available' END "
                "WHERE id = ?", 
                (item["quantity"], item["quantity"], item["product_id"])
            )
            
        query_db("UPDATE orders SET status = 'Confirmed', payment_status = 'Confirmed' WHERE id = ?", (order_id,))
        
    return redirect(url_for("order_history"))


@app.route("/orders/<int:order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    """Terminates an unresolved or pending order if authorized by the merchant identity."""
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
        
    if query_db("SELECT id FROM order_items WHERE order_id = ? AND seller = ?", (order_id, session["username"])):
        query_db("UPDATE orders SET status = 'Cancelled' WHERE id = ?", (order_id,))
        
    return redirect(url_for("order_history"))


@app.route("/clear-cart")
def clear_cart():
    """Wipes active session-based cart memory keys completely."""
    session.pop("cart", None)
    return redirect(url_for("home"))
# =========================================================================
# VENDOR MEMBERSHIP TIERS AND PREMIUM PIPELINES
# =========================================================================

@app.route("/subscription")
def subscription():
    """Renders the subscription hub, calculating trial limits and localized MoMo text."""
    if "username" not in session:
        return redirect(url_for("login"))
        
    user = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    if not user:
        session.clear()
        return redirect(url_for("login"))
        
    # Dynamically build destination details for billing clearance
    payment_number = normalize_whatsapp_number(os.environ.get("BIZ_HUB_PAYMENT_WHATSAPP", "233558272972"))
    payment_text = quote(f"Hello Biz Hub, I want to upgrade my {session['username']} account to Premium Store.")
    
    return render_template(
        "subscription.html", 
        user=user, 
        subscription=subscription_status(user), 
        payment_number=payment_number, 
        payment_text=payment_text, 
        requested=request.args.get("requested") == "1"
    )


@app.route("/request-premium", methods=["POST"])
def request_premium():
    """Flags a vendor profile within the database as awaiting administrative approval."""
    if "username" not in session or session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
        
    # Timestamp the request using modern UTC offsets
    query_db(
        "UPDATE users SET upgrade_requested_at = ? WHERE username = ?", 
        (datetime.now(timezone.utc).isoformat(), session["username"])
    )
    
    return redirect(url_for("subscription", requested="1"))
# =========================================================================
# CENTRAL ADMINISTRATIVE ACCESS CONTROLLERS
# =========================================================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Evaluates multiple confirmation parameters to securely open the administration hub."""
    if request.method == "POST":
        if not admin_configured():
            return render_template("admin_login.html", admin_error="Admin credentials are not configured.")
            
        submitted_username = request.form.get("username", "").strip()
        submitted_password = request.form.get("password", "")
        
        # 1. Evaluate persistent entries stored inside the Database Architecture
        database_admin = query_db("SELECT * FROM admin_users WHERE username = ?", (submitted_username,), one=True)
        database_login = database_admin and check_password_hash(database_admin["password_hash"], submitted_password)
        
        # 2. Evaluate environmental runtime configurations
        configured_login = submitted_username == os.environ.get("BIZ_HUB_ADMIN_USERNAME", "").strip() and submitted_password == os.environ.get("BIZ_HUB_ADMIN_PASSWORD", "")
        
        # 3. Fallback matrix confirmation check
        local_login = submitted_username == LOCAL_ADMIN_USERNAME and submitted_password == LOCAL_ADMIN_PASSWORD
        
        if database_login or configured_login or local_login:
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
            
        return render_template("admin_login.html", admin_error="Invalid admin credentials.")
        
    return render_template("admin_login.html", admin_configured=admin_configured(), signup_available=admin_signup_available())


@app.route("/admin/signup", methods=["GET", "POST"])
def admin_signup():
    """Allows initial single-instance setup of standard administrative credentials."""
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
            query_db(
                "INSERT INTO admin_users (username, password_hash, created_at) VALUES (?, ?, ?)", 
                (username, generate_password_hash(password), datetime.now(timezone.utc).isoformat())
            )
        except sqlite3.IntegrityError:
            return render_template("admin_signup.html", admin_error="That admin username is already taken.")
            
        return redirect(url_for("admin_login", registered="1"))
        
    return render_template("admin_signup.html")


# =========================================================================
# SYSTEM CONTROL ROOM & LEDGER COMPUTATION ENGINE
# =========================================================================

@app.route("/admin")
def admin_dashboard():
    """Compiles analytic profiles and financial spreadsheets into a unified workspace view."""
    if not is_admin():
        return redirect(url_for("admin_login"))
        
    # Fetch metrics arrays
    users = query_db("SELECT * FROM users ORDER BY COALESCE(registered_at, '') DESC, username")
    listing_counts = {row["seller"]: row["count"] for row in query_db("SELECT seller, COUNT(*) AS count FROM products GROUP BY seller")}
    
    # Financial Bookkeeping Computations (MoMo Cash Tracking Engine)
    ledger_entries = query_db("SELECT * FROM financial_ledger ORDER BY id DESC") or []
    
    # Sum up performance sheets using standard dictionary property mapping loops
    total_rev_row = query_db("SELECT SUM(amount) AS total FROM financial_ledger WHERE status = 'Verified'", one=True)
    total_revenue = total_rev_row["total"] if total_rev_row and total_rev_row["total"] is not None else 0.0
    
    pending_momo_row = query_db("SELECT SUM(amount) AS total FROM financial_ledger WHERE status = 'Pending'", one=True)
    pending_momo = pending_momo_row["total"] if pending_momo_row and pending_momo_row["total"] is not None else 0.0
    
    verified_count_row = query_db("SELECT COUNT(*) AS count FROM financial_ledger WHERE status = 'Verified'", one=True)
    verified_count = verified_count_row["count"] if verified_count_row and verified_count_row["count"] is not None else 0
    
    return render_template(
        "admin.html", 
        users=users, 
        subscription_status=subscription_status, 
        listing_counts=listing_counts,
        ledger_entries=ledger_entries,
        total_revenue=total_revenue,
        pending_momo=pending_momo,
        verified_count=verified_count
    )


@app.route("/admin/verify-transaction/<int:entry_id>", methods=["POST"])
def verify_transaction(entry_id):
    """Updates manual transaction requests to Verified once verified via MoMo reference sheets."""
    if not is_admin(): 
        return redirect(url_for("admin_login"))
        
    query_db("UPDATE financial_ledger SET status = 'Verified' WHERE id = ?", (entry_id,))
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/log-payment", methods=["POST"])
def log_payment():
    """Manually registers vendor platform deposits into the fiscal tracker ledger sheets."""
    if not is_admin():
        return redirect(url_for("admin_login"))

    username = request.form.get("username")
    amount = float(request.form.get("amount", 0.0))
    tx_type = request.form.get("transaction_type", "Subscription")
    ref = request.form.get("momo_reference", "").strip() or f"WA-{uuid.uuid4().hex[:8].upper()}"
    
    query_db(
        "INSERT INTO financial_ledger (transaction_type, username, amount, momo_reference, status, created_at) VALUES (?, ?, ?, ?, 'Pending', ?)",
        (tx_type, username, amount, ref, datetime.now(timezone.utc).isoformat())
    )
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/approve-premium/<int:user_id>", methods=["POST"])
def approve_premium(user_id):
    """Extends a standard merchant account with full premium privileges for a 30-day term."""
    if not is_admin():
        return redirect(url_for("admin_login"))
        
    expiry = datetime.now(timezone.utc) + timedelta(days=30)
    query_db(
        "UPDATE users SET plan = 'premium', subscription_expires_at = ?, upgrade_requested_at = NULL "
        "WHERE id = ? AND (role = 'Vendor' OR role = 'Fast Food')", 
        (expiry.isoformat(), user_id)
    )
    return redirect(url_for("admin_dashboard"))


# =========================================================================
# USER DELETION CASCADE AND STORAGE PURGE SEQUENCE
# =========================================================================

@app.route("/admin/delete-user/<int:user_id>", methods=["POST"])
def admin_delete_user(user_id):
    """Performs full cascading deletions across product matrices, orders, and local files."""
    if not is_admin():
        return redirect(url_for("admin_login"))
        
    user = query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if not user:
        return redirect(url_for("admin_dashboard"))
        
    # Isolate associated brand layouts and clean files from storage directories
    product_rows = query_db("SELECT image_file, video_file FROM products WHERE seller = ?", (user["username"],)) or []
    for product in product_rows:
        for filename in (product["image_file"], product["video_file"], user["company_logo"]):
            if filename:
                file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    
    # Clean active transaction records linked to the target entity
    order_ids = {row["order_id"] for row in query_db("SELECT order_id FROM order_items WHERE seller = ?", (user["username"],)) if row}
    order_ids.update(row["id"] for row in query_db("SELECT id FROM orders WHERE customer_username = ?", (user["username"],)) if row)
    
    query_db("DELETE FROM order_items WHERE seller = ?", (user["username"],))
    for order_id in order_ids:
        if not query_db("SELECT id FROM order_items WHERE order_id = ?", (order_id,)):
            query_db("DELETE FROM orders WHERE id = ?", (order_id,))
            
    # Purge relational profile components cleanly
    query_db("DELETE FROM products WHERE seller = ?", (user["username"],))
    query_db("DELETE FROM vendor_categories WHERE user_id = ?", (user["id"],))
    query_db("DELETE FROM password_resets WHERE user_id = ?", (user["id"],))
    query_db("DELETE FROM users WHERE id = ?", (user_id,))
    
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/logout")
def admin_logout():
    """Wipes administrative bits out of context memory pools securely."""
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))
# =========================================================================
# VENDOR BRANDING AND IDENTITY PROFILE CONTEXTS
# =========================================================================

@app.route("/settings", methods=["GET", "POST"])
def settings():
    """Manages profile upgrades, security hashes, and vendor classification bounds."""
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

        # Parameter Sanitation Filters
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

        # Recompute Security Hash Block if parameters changed
        password_hash = generate_password_hash(new_password) if new_password else user["password_hash"]
        
        if not is_vendor_any:
            company_name = None
            whatsapp_number = None
            catalog_mode = None
            selected_categories = []
            company_logo = None
        elif catalog_mode not in ("Variety", "Focused") or not selected_categories:
            return render_template("settings.html", user=user, vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, settings_error="Choose whether you sell a variety or focus on a category, then select at least one product range.")
            
        # Synchronize Data Repositories
        query_db(
            "UPDATE users SET email = ?, password_hash = ?, company_name = ?, whatsapp_number = ?, catalog_mode = ?, company_logo = ? WHERE username = ?",
            (email, password_hash, company_name, whatsapp_number, catalog_mode, company_logo, session["username"])
        )
        
        query_db("DELETE FROM vendor_categories WHERE user_id = ?", (user["id"],))
        for category in selected_categories:
            query_db("INSERT INTO vendor_categories (user_id, category) VALUES (?, ?)", (user["id"], category))
            
        # Re-index Session Track Matrix States
        session["email"] = email
        session["company_name"] = company_name
        session["whatsapp_number"] = whatsapp_number
        return redirect(url_for("settings", updated="1"))

    return render_template("settings.html", user=user, subscription=subscription_status(user), vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, updated=request.args.get("updated") == "1")


# =========================================================================
# SYSTEM SECURITY GATEWAY (AUTHENTICATION PIPELINES)
# =========================================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    """Validates user security configurations to establish contextual browsing bits."""
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
    """Generates encrypted recovery tokens packaged safely inside WhatsApp redirect triggers."""
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
    """Processes account updates if the unique identification token passes integrity matrix limits."""
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
    """Handles multi-tier registrations, configuring complementary trials for new vendors."""
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

              # =========================================================================
        # ROLE PARAMETER SANITIZATION MATRIX
        # =========================================================================
        # Structural Re-alignment Engine depending on role targets
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

        # Enforce business parameter validation criteria
        if role in ["Vendor", "Fast Food"] and not whatsapp_number:
            return render_template("login.html", reg_error="Merchant and Fast Food vendor accounts need a compulsory WhatsApp number to receive order tallies.")
        if role == "Vendor" and (catalog_mode not in ("Variety", "Focused") or not selected_categories):
            return render_template("login.html", reg_error="Choose a product range and select at least one category.")

        # =========================================================================
        # DATABASE ACCOUNT PERSISTENCE LAYER
        # =========================================================================
        # =========================================================================
        # DATABASE ACCOUNT PERSISTENCE LAYER (60-DAY FREE PREMIUM TRIAL)
        # =========================================================================
        try:
            hashed_pwd = generate_password_hash(password)
            trial_started_at = datetime.now(timezone.utc)
            trial_expires_at = trial_started_at + timedelta(days=60) # 🧠 UPGRADED: 2-Month Free Premium Trial Window
            
            # Set default plan to 'premium' for the duration of the 60-day free introductory offer
            user_plan = "premium" if role in ["Vendor", "Fast Food"] else "basic"
            
            query_db(
                "INSERT INTO users (username, email, password_hash, role, seller_type, company_name, whatsapp_number, plan, trial_started_at, subscription_expires_at, catalog_mode, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (username, email, hashed_pwd, role, seller_type, company_name, whatsapp_number, user_plan, trial_started_at.isoformat() if role in ["Vendor", "Fast Food"] else None, trial_expires_at.isoformat() if role in ["Vendor", "Fast Food"] else None, catalog_mode, datetime.now(timezone.utc).isoformat())
            )
            
            new_user = query_db("SELECT id FROM users WHERE username = ?", (username,), one=True)
            if new_user and selected_categories:
                for category in selected_categories:
                    query_db("INSERT INTO vendor_categories (user_id, category) VALUES (?, ?)", (new_user["id"], category))
                    
            # Auto-login the newly provisioned profile session tracking arrays
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


# =========================================================================
# SESSION DISCONNECTION CONTAINER
# =========================================================================

@app.route("/logout")
def logout():
    """Wipes active customer and merchant parameters out of active runtime cookies completely."""
    session.clear()
    return redirect(url_for("home"))


# =========================================================================
# CENTRAL KERNEL BOOT SEQUENCE EXECUTION LOGIC
# =========================================================================

if __name__ == "__main__":
    # Launch system instance over local interfaces on public access network nodes
    app.run(debug=True, host="0.0.0.0")

