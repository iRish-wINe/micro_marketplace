import sqlite3
import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
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

def init_db():
    conn = sqlite3.connect("marketplace.db", timeout=20)
    cursor = conn.cursor()
    
    # 👥 1. Create Core Users Table Architecture
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
    
    # 🛍️ 2. Create Core Products Table Architecture
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
    
    # 🏬 3. Create Core Vendor Categories Table Architecture
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vendor_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            UNIQUE(user_id, category),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    
    # 🛡️ 4. Create Core Admin Users Table Architecture
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    
    # 🛒 5. Create Core Orders Table Architecture
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
    
    # 📦 6. Create Core Order Items Table Architecture
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
    
    # 🔐 7. Create Password Resets Table Architecture
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
    
    # 🧠 Safe Runtime Migration Array Scanners (Ensures zero missing column parameters)
    user_columns = {row[1] for row in cursor.execute("PRAGMA table_info(users)")}
    if "whatsapp_number" not in user_columns: cursor.execute("ALTER TABLE users ADD COLUMN whatsapp_number TEXT")
    if "plan" not in user_columns: cursor.execute("ALTER TABLE users ADD COLUMN plan TEXT NOT NULL DEFAULT 'basic'")
    if "trial_started_at" not in user_columns: cursor.execute("ALTER TABLE users ADD COLUMN trial_started_at TEXT")
    if "subscription_expires_at" not in user_columns: cursor.execute("ALTER TABLE users ADD COLUMN subscription_expires_at TEXT")
    if "upgrade_requested_at" not in user_columns: cursor.execute("ALTER TABLE users ADD COLUMN upgrade_requested_at TEXT")
    if "catalog_mode" not in user_columns: cursor.execute("ALTER TABLE users ADD COLUMN catalog_mode TEXT")
    if "company_logo" not in user_columns: cursor.execute("ALTER TABLE users ADD COLUMN company_logo TEXT")
    if "registered_at" not in user_columns: cursor.execute("ALTER TABLE users ADD COLUMN registered_at TEXT")
        
    product_columns = {row[1] for row in cursor.execute("PRAGMA table_info(products)")}
    if "seller_whatsapp" not in product_columns: cursor.execute("ALTER TABLE products ADD COLUMN seller_whatsapp TEXT")
    if "category" not in product_columns: cursor.execute("ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT 'Other'")
    if "video_file" not in product_columns: cursor.execute("ALTER TABLE products ADD COLUMN video_file TEXT")
    if "stock_quantity" not in product_columns: cursor.execute("ALTER TABLE products ADD COLUMN stock_quantity INTEGER NOT NULL DEFAULT 1")
    if "status" not in product_columns: cursor.execute("ALTER TABLE products ADD COLUMN status TEXT NOT NULL DEFAULT 'Available'")
    if "views" not in product_columns: cursor.execute("ALTER TABLE products ADD COLUMN views INTEGER NOT NULL DEFAULT 0")

    order_columns = {row[1] for row in cursor.execute("PRAGMA table_info(orders)")}
    if "payment_status" not in order_columns: cursor.execute("ALTER TABLE orders ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'Unpaid'")

    conn.commit()
    conn.close()


init_db()

def normalize_whatsapp_number(number):
    digits = "".join(character for character in (number or "") if character.isdigit())
    if digits.startswith("0"):
        digits = "233" + digits[1:]
    return digits

def subscription_status(user):
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
    conn = sqlite3.connect("marketplace.db", timeout=20)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(query, args)
    rv = cursor.fetchall()
    conn.commit()
    conn.close()
    return (rv[0] if rv else None) if one else rv

def get_vendor_categories(user_id):
    return [row["category"] for row in query_db("SELECT category FROM vendor_categories WHERE user_id = ? ORDER BY category", (user_id,))]

def valid_reset_token(token):
    if not token:
        return None
    reset_rows = query_db("SELECT * FROM password_resets WHERE token = ? AND used = 0", (token,))
    if not reset_rows:
        return None
    reset = reset_rows[0]
    if datetime.fromisoformat(reset["expires_at"]) <= datetime.now(timezone.utc):
        return None
    return reset

def save_company_logo(upload):
    if not upload or not upload.filename:
        return None
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
        vendor = query_db("SELECT * FROM users WHERE username = ?", (session["username"],))[0]
        vendor_subscription = subscription_status(vendor)
        listing_count = query_db("SELECT COUNT(*) AS count FROM products WHERE seller = ?", (session["username"],))[0]["count"]
        if not vendor_subscription["is_premium"] and listing_count >= 3:
            return redirect(url_for("home", listing_error="Basic accounts can list up to 3 products. Upgrade to Premium for unlimited listings."))
            
        price = request.form.get("price")
        is_fast_food = vendor["seller_type"] == "Fast Food" or session.get("role") == "Fast Food"
        title = request.form.get("meal_name" if is_fast_food else "title")
        description = request.form.get("meal_description" if is_fast_food else "description")
        category = "Fast Food" if is_fast_food else request.form.get("category", "Other")
        stock_quantity = request.form.get("stock_quantity", "1")
        location = request.form.get("location")
        file = request.files.get("product_image")
        video = request.files.get("product_video")
        video_filename = None
        if video and video.filename:
            video_extension = os.path.splitext(video.filename)[1].lower()
            if not vendor_subscription["is_premium"]:
                return redirect(url_for("home", listing_error="Only verified vendors with an active Premium Store or trial can upload product videos."))
            if video_extension not in VIDEO_EXTENSIONS:
                return redirect(url_for("home", listing_error="Product videos must be MP4, WebM, or MOV files."))
            video_filename = f"video-{uuid.uuid4().hex}{video_extension}"
        filename = "fast-food-placeholder.svg" if is_fast_food else secure_filename(file.filename) if file and file.filename else ""
        
        has_image = bool(file and file.filename)
        has_video = bool(video and video.filename)
        if not is_fast_food and has_image == has_video:
            return redirect(url_for("home", listing_error="Choose exactly one product image or video."))

        try:
            stock_quantity = int(stock_quantity)
        except (TypeError, ValueError):
            return redirect(url_for("home", listing_error="Stock quantity must be a whole number greater than zero."))
        if stock_quantity < 1:
            return redirect(url_for("home", listing_error="Stock quantity must be a whole number greater than zero."))

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
    
    if 'cart' in session and session['cart']:
        placeholders = ",".join("?" for _ in session['cart'])
        items_in_db = query_db(f"SELECT * FROM products WHERE id IN ({placeholders})", session['cart'])
        if items_in_db:
            for item in items_in_db:
                cart_items.append(item)
                cart_total += float(item['price'])
                seller_number = normalize_whatsapp_number(item['seller_whatsapp'])
                seller_key = (item['seller'], seller_number)
                seller_order = seller_orders.setdefault(seller_key, {
                    "seller": item["seller"],
                    "number": seller_number,
                    "items": [],
                    "total": 0.0,
                })
                seller_order["items"].append(item)
                seller_order["total"] += float(item["price"])

       # 🛒 UPGRADED: FIXED WHATSAPP ORDER basket COMPILER UTILITY
    for seller_order in seller_orders.values():
        message = f"Hello {seller_order['seller']}, I want to buy these products on Biz Hub:\n"
        for item in seller_order["items"]:
            message += f"- {item['title']} (GH₵{item['price']}) in {item['location']}\n"
        # Enforces the unalterable payment reminder footnote layout parameters
        message += f"\nTotal Cost: GH₵{seller_order['total']:.2f}. Let's arrange for payment and delivery."
        seller_order["whatsapp_text"] = quote(message)


    premium_sellers = {row["username"] for row in query_db("SELECT username FROM users WHERE (role = 'Vendor' OR role = 'Fast Food') AND plan = 'premium' AND subscription_expires_at > ?", (datetime.now(timezone.utc).isoformat(),))}
    trial_sellers = {row["username"] for row in query_db("SELECT username FROM users WHERE (role = 'Vendor' OR role = 'Fast Food') AND plan = 'basic' AND subscription_expires_at > ?", (datetime.now(timezone.utc).isoformat(),))}
    premium_sellers.update(trial_sellers)
    for seller_order in seller_orders.values():
        seller_order["priority"] = seller_order["seller"] in premium_sellers
    vendor_subscription = None
    listing_count = 0
    if session.get("role") in ["Vendor", "Fast Food"]:
        vendor = query_db("SELECT * FROM users WHERE username = ?", (session["username"],))[0]
        vendor_subscription = subscription_status(vendor)
        listing_count = query_db("SELECT COUNT(*) AS count FROM products WHERE seller = ?", (session["username"],))[0]["count"]
    return render_template("index.html", products=all_products, active_filter=selected_filter, company_search=company_search, selected_category=selected_category, categories=PRODUCT_CATEGORIES, vendor_logos=vendor_logos, cart_items=cart_items, cart_total=cart_total, seller_orders=sorted(seller_orders.values(), key=lambda order: not order["priority"]), vendor_subscription=vendor_subscription, listing_count=listing_count, listing_error=listing_error, premium_sellers=premium_sellers)
@app.route("/delete-item/<int:product_id>")
def delete_item(product_id):
    if "username" not in session:
        return redirect(url_for("login"))
    product_list = query_db("SELECT * FROM products WHERE id = ?", (product_id,), one=True)
    product = product_list if product_list else None
    if product and product["seller"] == session["username"]:
        query_db("DELETE FROM products WHERE id = ?", (product_id,))
    return redirect(url_for("home"))

@app.route("/add-to-cart/<int:product_id>")
def add_to_cart(product_id):
    product_list = query_db("SELECT stock_quantity, status FROM products WHERE id = ?", (product_id,), one=True)
    product = product_list if product_list else None
    if not product:
        return redirect(url_for("home"))
    if product["stock_quantity"] < 1 or product["status"] == "Sold":
        return redirect(url_for("home", listing_error="This product is sold out."))
    if 'cart' not in session:
        session['cart'] = []
    current_cart = session['cart']
    if product_id not in current_cart:
        current_cart.append(product_id)
        session['cart'] = current_cart
    return redirect(url_for("home"))

@app.route("/mark-sold/<int:product_id>", methods=["POST"])
def mark_sold(product_id):
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    product_list = query_db("SELECT stock_quantity FROM products WHERE id = ? AND seller = ?", (product_id, session["username"]), one=True)
    product = product_list if product_list else None
    if product:
        try:
            sold_quantity = int(request.form.get("sold_quantity", "1"))
        except (TypeError, ValueError):
            sold_quantity = 0
        if 1 <= sold_quantity <= product["stock_quantity"]:
            query_db("UPDATE products SET stock_quantity = MAX(stock_quantity - ?, 0), status = CASE WHEN stock_quantity <= ? THEN 'Sold' ELSE 'Available' END WHERE id = ? AND seller = ?", (sold_quantity, sold_quantity, product_id, session["username"]))
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
    order_id = query_db("SELECT id FROM orders WHERE customer_username = ? AND created_at = ? ORDER BY id DESC LIMIT 1", (session["username"], created_at))["id"]
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
    order_items = {order["id"]: query_db("SELECT * FROM order_items WHERE order_id = ?", (order["id"],)) for order in customer_orders + vendor_orders}
    seller_names = {
        row["username"]: (row["company_name"] or row["username"])
        for row in query_db("SELECT username, company_name FROM users")
    }
    order_sellers = {
        order["id"]: sorted({seller_names.get(item["seller"], item["seller"]) for item in order_items[order["id"]]})
        for order in customer_orders
    }
    return render_template("orders.html", customer_orders=customer_orders, vendor_orders=vendor_orders, order_items=order_items, order_sellers=order_sellers)

@app.route("/orders/<int:order_id>/confirm", methods=["POST"])
def confirm_order(order_id):
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    order = query_db("SELECT * FROM orders WHERE id = ?", (order_id,))
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
@app.route("/clear-cart")
def clear_cart():
    session.pop('cart', None)
    return redirect(url_for("home"))

@app.route("/subscription")
def subscription():
    if "username" not in session:
        return redirect(url_for("login"))
    user_list = query_db("SELECT * FROM users WHERE username = ?", (session["username"],))
    if not user_list:
        session.clear()
        return redirect(url_for("login"))
    user = user_list[0]
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
        database_admin = query_db("SELECT * FROM admin_users WHERE username = ?", (submitted_username,))
        database_login = database_admin and check_password_hash(database_admin[0]["password_hash"], submitted_password)
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
    return render_template("admin.html", users=users, subscription_status=subscription_status, listing_counts=listing_counts)

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
    user_list = query_db("SELECT * FROM users WHERE id = ?", (user_id,))
    if not user_list:
        return redirect(url_for("admin_dashboard"))
    user = user_list[0]
    product_rows = query_db("SELECT image_file, video_file FROM products WHERE seller = ?", (user["username"],))
    for product in product_rows:
        for filename in (product["image_file"], product["video_file"], user["company_logo"]):
            if filename:
                file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
    order_ids = {row["order_id"] for row in query_db("SELECT order_id FROM order_items WHERE seller = ?", (user["username"],))}
    order_ids.update(row["id"] for row in query_db("SELECT id FROM orders WHERE customer_username = ?", (user["username"],)))
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

    user_list = query_db("SELECT * FROM users WHERE username = ?", (session["username"],))
    if not user_list:
        session.clear()
        return redirect(url_for("login"))
    user = user_list[0]
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
        username = request.form.get("login_user", "").strip()
        password = request.form.get("login_pass", "")
        user = query_db("SELECT * FROM users WHERE username = ?", (username,), one=True)

        valid_password = False
        if user is not None:
            try:
                valid_password = bool(user["password_hash"]) and check_password_hash(user["password_hash"], password)
            except (TypeError, ValueError):
                valid_password = False

        if valid_password:
            session.clear()
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
        users = query_db("SELECT * FROM users WHERE whatsapp_number = ?", (whatsapp_number,), one=True)
        if not users:
            reset_error = "No account was found with that registered WhatsApp number."
        else:
            token = uuid.uuid4().hex
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
            query_db("INSERT INTO password_resets (user_id, token, expires_at) VALUES (?, ?, ?)", (users["id"], token, expires_at))
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
    if request.method == "POST":
        username = request.form.get("reg_user", "").strip()
        email = request.form.get("reg_email", "").strip()
        password = request.form.get("reg_pass", "")
        submitted_role = request.form.get("role", "").strip()
        role_aliases = {
            "customer": "Customer",
            "vendor": "Vendor",
            "fast food": "Fast Food",
        }
        role = role_aliases.get(submitted_role.casefold())

        if not username or not email or not password:
            return render_template("login.html", reg_error="Username, email, and password are required.")
        if not role:
            return render_template("login.html", reg_error="Choose Customer, General Merchant, or Fast Food Vendor before registering.")
        seller_type = request.form.get("seller_type")
        catalog_mode = request.form.get("catalog_mode")
        selected_categories = [category for category in request.form.getlist("vendor_categories") if category in VENDOR_CATEGORIES]
        company_name = request.form.get("company_name")
        whatsapp_number = normalize_whatsapp_number(request.form.get("whatsapp_number"))
        
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
            
        if role in ["Vendor", "Fast Food"] and not whatsapp_number:
            return render_template("login.html", reg_error="Merchant and Fast Food vendor accounts need a compulsory WhatsApp number to receive order tallies.")
        if role == "Vendor" and (catalog_mode not in ("Variety", "Focused") or not selected_categories):
            return render_template("login.html", reg_error="Choose a product range and select at least one category.")
            
        try:
            hashed_pwd = generate_password_hash(password)
            trial_started_at = datetime.now(timezone.utc)
            trial_expires_at = trial_started_at + timedelta(days=61)
            
            query_db(
                "INSERT INTO users (username, email, password_hash, role, seller_type, company_name, whatsapp_number, plan, trial_started_at, subscription_expires_at, catalog_mode, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                (username, email, hashed_pwd, role, seller_type, company_name, whatsapp_number, "basic", trial_started_at.isoformat() if role in ["Vendor", "Fast Food"] else None, trial_expires_at.isoformat() if role in ["Vendor", "Fast Food"] else None, catalog_mode, datetime.now(timezone.utc).isoformat())
            )
            
            new_user = query_db("SELECT id FROM users WHERE username = ?", (username,), one=True)
            for category in selected_categories:
                query_db("INSERT INTO vendor_categories (user_id, category) VALUES (?, ?)", (new_user["id"], category))
                
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

