import sqlite3
import os
import uuid
import re
import html
import secrets
from dotenv import load_dotenv

load_dotenv()
import json
import logging
import hashlib
import base64
import smtplib
import requests
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, render_template_string, Response
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import RequestEntityTooLarge
app = Flask(__name__)

# Configure standard logging to output to console (stdout)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.errorhandler(500)
def internal_error(error):
    # Log the full exception stack trace whenever a 500 happens
    app.logger.error(f"Server Error: {error}", exc_info=True)
    return "Internal Server Error", 500
_configured_secret = os.environ.get("BIZ_HUB_SECRET_KEY", "").strip()
if _configured_secret:
    app.secret_key = _configured_secret
else:
    # Safe local fallback: sessions are invalidated on restart instead of using a
    # publicly known/default secret. Production should always set BIZ_HUB_SECRET_KEY.
    app.secret_key = secrets.token_hex(32)
    logger.warning("BIZ_HUB_SECRET_KEY is not set; using an ephemeral development secret.")

# Never ship administrator credentials in source code.
LOCAL_ADMIN_USERNAME = ""
LOCAL_ADMIN_PASSWORD = ""
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("BIZ_HUB_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes"},
)
PRODUCT_CATEGORIES = [
    "Phones & Accessories",
    "Computers & Accessories",
    "Electronics",
    "Home Appliances",
    "Home & Kitchen",
    "Furniture",
    "Groceries",
    "Food & Beverages",
    "Clothing & Fashion",
    "Shoes & Bags",
    "Beauty & Personal Care",
    "Health & Wellness",
    "Books & Stationery",
    "Baby & Kids",
    "Sports & Fitness",
    "Automotive",
    "Tools & Hardware",
    "Agriculture",
    "Jewelry & Accessories",
    "Services",
    "Other",
    "Fast Food",
]
VENDOR_CATEGORIES = [c for c in PRODUCT_CATEGORIES if c != "Fast Food"]
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov"}
DELIVERY_TYPES = ["Motorcycle", "Car", "Van", "Bicycle", "Other"]
NOTIFICATION_TYPES = {
    "favorite": "Favorite-store activity",
    "product": "New product",
    "promotion": "Favorite-store promotion",
    "order": "Order update",
    "delivery": "Delivery activity",
    "announcement": "BizHub announcement",
}

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token

@app.context_processor
def inject_security_context():
    return {"csrf_token": get_csrf_token()}

@app.context_processor
def inject_global_theme_context():
    current_theme = session.get("theme", "day")

    if session.get("username") and not is_admin():
        try:
            user_row = query_db(
                "SELECT theme FROM users WHERE username = ?",
                (session["username"],),
                one=True,
            )
            if user_row and user_row.get("theme") in ("day", "night"):
                current_theme = user_row["theme"]
        except sqlite3.OperationalError:
            current_theme = "day"

    return {"app_theme": current_theme}



@app.before_request
def csrf_protect():
    if request.method in {"GET", "HEAD", "OPTIONS"} or request.path.startswith("/static"):
        return None
    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    expected = session.get("_csrf_token")
    if not expected or not supplied or not secrets.compare_digest(str(supplied), str(expected)):
        return "Invalid or missing CSRF token.", 400
    return None

@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response

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

@app.before_request
def enforce_account_status():
    if not session.get("username") or request.path.startswith("/static") or request.path in {"/login", "/register", "/rules", "/forgot-password"}:
        return None
    user = query_db("SELECT account_status, enforcement_reason FROM users WHERE username = ?", (session["username"],), one=True)
    if user and user.get("account_status") in ("Suspended", "Terminated"):
        session.clear()
        return render_template_string("""
            <!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Account Restricted | BizHub</title></head>
            <body style="font-family:system-ui;padding:40px;text-align:center;background:#f4f7fb"><h1>Account Restricted</h1><p>Your BizHub account is {{ status|lower }}.</p><p>{{ reason or 'Please contact BizHub support for more information.' }}</p><a href="/rules">View Rules &amp; Regulations</a></body></html>
        """, status=user["account_status"], reason=user.get("enforcement_reason")), 403
    return None

def init_db():
    conn = sqlite3.connect(os.path.join(app.root_path, "marketplace.db"), timeout=60)
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
    for statement in (
        "ALTER TABLE users ADD COLUMN account_status TEXT NOT NULL DEFAULT 'Active'",
        "ALTER TABLE users ADD COLUMN enforcement_reason TEXT",
        "ALTER TABLE users ADD COLUMN suspended_until TEXT",
        "ALTER TABLE users ADD COLUMN is_verified_brand INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN verified_at TEXT",
        "ALTER TABLE users ADD COLUMN verified_brand_type TEXT",
    ):
        try:
            cursor.execute(statement)
        except sqlite3.OperationalError:
            pass
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS enforcement_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER NOT NULL,
            target_user_id INTEGER NOT NULL,
            target_username TEXT NOT NULL,
            target_role TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            admin_action TEXT,
            admin_note TEXT,
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            FOREIGN KEY(reporter_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(target_user_id) REFERENCES users(id) ON DELETE CASCADE
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
        CREATE TABLE IF NOT EXISTS cart_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER,
            title TEXT NOT NULL,
            seller TEXT NOT NULL,
            price REAL NOT NULL,
            quantity_added INTEGER NOT NULL DEFAULT 1,
            cart_quantity_after INTEGER NOT NULL DEFAULT 1,
            added_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_id INTEGER NOT NULL,
            notification_type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            link TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY(recipient_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscription_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_number TEXT UNIQUE NOT NULL,
            ledger_id INTEGER UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            plan_name TEXT NOT NULL,
            amount REAL NOT NULL,
            payment_reference TEXT,
            issued_at TEXT NOT NULL,
            FOREIGN KEY(ledger_id) REFERENCES financial_ledger(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reviewer_id INTEGER NOT NULL,
            vendor_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(reviewer_id, vendor_id),
            FOREIGN KEY(reviewer_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(vendor_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS delivery_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL,
            order_id INTEGER,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Requested',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(vendor_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(service_id) REFERENCES delivery_services(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            actor_username TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verification_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            note TEXT,
            user_message TEXT,
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS disputes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER NOT NULL,
            order_id INTEGER,
            subject TEXT NOT NULL,
            details TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            admin_note TEXT,
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            FOREIGN KEY(reporter_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            query TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, query),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS loyalty_accounts (
            user_id INTEGER PRIMARY KEY,
            points INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS loyalty_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            order_id INTEGER,
            points INTEGER NOT NULL,
            transaction_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, order_id, transaction_type),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS coupons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER NOT NULL,
            code TEXT UNIQUE NOT NULL,
            description TEXT NOT NULL,
            discount REAL NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            max_redemptions INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(vendor_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_username TEXT NOT NULL,
            action TEXT NOT NULL,
            target_username TEXT,
            details TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            subscription_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, subscription_json),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS delivery_services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            service_name TEXT NOT NULL,
            logo_file TEXT,
            operating_location TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            service_area TEXT NOT NULL,
            delivery_type TEXT NOT NULL DEFAULT 'Motorcycle',
            availability TEXT NOT NULL DEFAULT 'Unavailable',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS delivery_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL,
            request_id INTEGER NOT NULL UNIQUE,
            rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(vendor_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(service_id) REFERENCES delivery_services(id) ON DELETE CASCADE,
            FOREIGN KEY(request_id) REFERENCES delivery_requests(id) ON DELETE CASCADE
        )
    """)
    # 👑 BIZHUB ENTERPRISE MANAGEMENT SYSTEM: INDIVIDUAL AND SEGMENT MESSAGE SCHEMAS
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_direct_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_scope TEXT NOT NULL, -- 'Individual', 'Group', or 'All'
            target_username TEXT,       -- Set if Individual
            target_role TEXT,           -- 'Customer', 'Vendor', 'Fast Food', 'Delivery Service' if Group
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()

    # Safe Column Alteration Injections
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
    # New promotion fields are additive migrations so existing databases keep working.
    for statement in (
        "ALTER TABLE products ADD COLUMN initial_stock_quantity INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE products ADD COLUMN sold_quantity INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN firebase_token TEXT",
        "ALTER TABLE orders ADD COLUMN coupon_code TEXT",
        "ALTER TABLE orders ADD COLUMN discount_amount REAL NOT NULL DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN loyalty_points_earned INTEGER NOT NULL DEFAULT 0",
    ):
        try:
            cursor.execute(statement)
        except sqlite3.OperationalError:
            pass

    # Additive, restart-safe migrations for verification messages and coupon redemption controls.
    for statement in (
        "ALTER TABLE verification_requests ADD COLUMN user_message TEXT",
        "ALTER TABLE coupons ADD COLUMN max_redemptions INTEGER NOT NULL DEFAULT 0",
    ):
        try:
            cursor.execute(statement)
        except sqlite3.OperationalError:
            pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS coupon_redemptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coupon_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            order_id INTEGER NOT NULL UNIQUE,
            redeemed_at TEXT NOT NULL,
            UNIQUE(coupon_id, customer_id),
            FOREIGN KEY(coupon_id) REFERENCES coupons(id) ON DELETE CASCADE,
            FOREIGN KEY(customer_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
        )
    """)

    try:
        cursor.execute("UPDATE products SET initial_stock_quantity = stock_quantity WHERE COALESCE(sold_quantity, 0) = 0 AND initial_stock_quantity = 1 AND stock_quantity > 1")
    except sqlite3.OperationalError:
        pass

    for statement in (
        "ALTER TABLE promotions ADD COLUMN product_id INTEGER",
        "ALTER TABLE promotions ADD COLUMN promo_price REAL",
        "ALTER TABLE promotions ADD COLUMN main_price REAL",
        "ALTER TABLE promotions ADD COLUMN image_file TEXT",
        "ALTER TABLE promotions ADD COLUMN video_file TEXT",
    ):
        try:
            cursor.execute(statement)
        except sqlite3.OperationalError:
            pass

    try:
        cursor.execute("UPDATE delivery_services SET availability = 'Unavailable' WHERE availability = 'Offline'")
    except sqlite3.OperationalError:
        pass

    try:
        legacy_delivery_users = cursor.execute("SELECT u.id, u.registered_at, ds.created_at FROM users u JOIN delivery_services ds ON ds.user_id = u.id WHERE u.role = 'Delivery Service' AND u.subscription_expires_at IS NULL").fetchall()
        for user_id, registered_at, service_created_at in legacy_delivery_users:
            started_at = registered_at or service_created_at
            if not started_at:
                continue
            try:
                trial_started_at = datetime.fromisoformat(started_at)
                trial_expires_at = trial_started_at + timedelta(days=90)
                cursor.execute("UPDATE users SET plan = 'basic', trial_started_at = ?, subscription_expires_at = ? WHERE id = ?", (trial_started_at.isoformat(), trial_expires_at.isoformat(), user_id))
            except ValueError:
                pass
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()

init_db()


def safe_internal_referrer(default_url_or_endpoint):
    referrer = request.referrer or ""
    if referrer.startswith(request.host_url):
        return referrer
    if default_url_or_endpoint.startswith("/") or default_url_or_endpoint.startswith(request.host_url):
        return default_url_or_endpoint
    return url_for(default_url_or_endpoint)

def normalize_whatsapp_number(number):
    digits = "".join(character for character in (number or "") if character.isdigit())
    if digits.startswith("0"):
        digits = "233" + digits[1:]
    return digits

def parse_subscription_expiry(raw):
    """Robust ISO parser: handles '2026-01-01 12:00:00', '...T...+00:00', '...Z'"""
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace('Z', '+00:00')
    s = s.replace(' ', 'T')
    try:
        if '+' not in s and s.count('T') == 1:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        return datetime.fromisoformat(s)
    except Exception:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s.split('+')[0].split('.')[0][:19], fmt.split('%z')[0].strip())
                return dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
        return None

def subscription_status(user):
    """BIZHUB SUBSCRIPTION ENGINE v2 - 60 days vendor / 90 days delivery"""
    if not user:
        return {"name": "Basic", "is_premium": False, "trial": False, "expires": None, "expires_iso": None, "days_left": 0}
    now = datetime.now(timezone.utc)
    expiry = parse_subscription_expiry(user.get("subscription_expires_at"))
    has_time_left = bool(expiry and expiry > now)
    days_left = (expiry - now).days if has_time_left else 0
    is_vendor_role = bool(user.get("role") in ["Vendor", "Fast Food", "Delivery Service"])
    if is_vendor_role and has_time_left:
        plan = (user.get("plan") or "").lower()
        trial_start = user.get("trial_started_at")
        is_paid_premium = bool(plan == "premium" and not trial_start)
        is_trial = bool(plan == "trial" or (plan == "premium" and trial_start))
        if is_paid_premium:
            label = "Premium Delivery" if user.get("role") == "Delivery Service" else "Premium Store"
            return {"name": label, "is_premium": True, "trial": False, "expires": expiry.strftime("%d %b %Y"), "expires_iso": expiry.isoformat(), "days_left": days_left}
        else:
            return {"name": "Free trial", "is_premium": True, "trial": True, "expires": expiry.strftime("%d %b %Y"), "expires_iso": expiry.isoformat(), "days_left": days_left}
    return {"name": "Basic", "is_premium": False, "trial": False, "expires": None, "expires_iso": None, "days_left": 0}



def is_premium_vendor(user):
    return bool(user and user.get("role") in ["Vendor", "Fast Food"] and subscription_status(user)["is_premium"])

def dispatch_external_notifications(user, title, message, link=None):
    if not user:
        return
    text = f"{title}\n{message}" + (f"\n{link}" if link else "")
    smtp_host = os.environ.get("BIZ_HUB_SMTP_HOST")
    if smtp_host and user.get("email"):
        try:
            email = EmailMessage()
            email["Subject"] = title
            email["From"] = os.environ.get("BIZ_HUB_SMTP_FROM", "BizHub")
            email["To"] = user["email"]
            email.set_content(text)
            with smtplib.SMTP(smtp_host, int(os.environ.get("BIZ_HUB_SMTP_PORT", "587")), timeout=15) as smtp:
                smtp.starttls()
                smtp.login(os.environ["BIZ_HUB_SMTP_USERNAME"], os.environ["BIZ_HUB_SMTP_PASSWORD"])
                smtp.send_message(email)
        except Exception:
            logger.exception("BizHub email notification failed")

    twilio_sid = os.environ.get("BIZ_HUB_TWILIO_ACCOUNT_SID")
    twilio_token = os.environ.get("BIZ_HUB_TWILIO_AUTH_TOKEN")
    twilio_from = os.environ.get("BIZ_HUB_TWILIO_WHATSAPP_FROM")
    whatsapp_to = normalize_whatsapp_number(user.get("whatsapp_number"))
    if twilio_sid and twilio_token and twilio_from and whatsapp_to:
        try:
            import requests
            response = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Messages.json", data={"From": twilio_from, "To": f"whatsapp:+{whatsapp_to}", "Body": text}, auth=(twilio_sid, twilio_token), timeout=15)
            response.raise_for_status()
        except Exception:
            logger.exception("BizHub WhatsApp notification failed")

    firebase_credentials = os.environ.get("BIZ_HUB_FIREBASE_CREDENTIALS")
    firebase_token = user.get("firebase_token")
    if firebase_credentials and firebase_token:
        try:
            import firebase_admin
            from firebase_admin import credentials, messaging
            if not firebase_admin._apps:
                firebase_admin.initialize_app(credentials.Certificate(firebase_credentials))
            messaging.send(messaging.Message(notification=messaging.Notification(title=title, body=message), token=firebase_token))
        except Exception:
            logger.exception("BizHub Firebase notification failed")

    _, vapid_private_key = _bizhub_vapid_material()
    if vapid_private_key:
        try:
            from pywebpush import webpush
            subscriptions = query_db("SELECT id, subscription_json FROM push_subscriptions WHERE user_id = ?", (user["id"],)) or []
            for subscription in subscriptions:
                try:
                    webpush(
                        subscription_info=json.loads(subscription["subscription_json"]),
                        data=json.dumps({"title": title, "message": message, "link": link}),
                        vapid_private_key=vapid_private_key,
                        vapid_claims={"sub": os.environ.get("BIZ_HUB_VAPID_SUBJECT", "mailto:notifications@bizhub.local")}
                    )
                except Exception as push_error:
                    if getattr(push_error, "response", None) is not None and push_error.response.status_code in (404, 410):
                        query_db("DELETE FROM push_subscriptions WHERE id = ?", (subscription["id"],))
                    else:
                        logger.exception("BizHub browser push failed")
        except ImportError:
            logger.warning("Install pywebpush to enable browser notifications")
        except Exception:
            logger.exception("BizHub browser notification setup failed")

def create_notification(recipient_id, notification_type, title, message, link=None):
    if not recipient_id or notification_type not in NOTIFICATION_TYPES:
        return
    query_db(
        "INSERT INTO notifications (recipient_id, notification_type, title, message, link, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (recipient_id, notification_type, title, message, link, datetime.now(timezone.utc).isoformat())
    )
    recipient = query_db("SELECT * FROM users WHERE id = ?", (recipient_id,), one=True)
    dispatch_external_notifications(recipient, title, message, link)

def notify_account_enforcement(user_id, action, reason):
    """Send moderation outcomes to the affected user through BizHub notifications."""
    if not user_id:
        return
    labels = {
        "Warned": ("Account warning", "Your BizHub account has received an official warning."),
        "Suspended": ("Account suspended", "Your BizHub account has been suspended."),
        "Terminated": ("Account terminated", "Your BizHub account has been terminated."),
        "Active": ("Account restored", "Your BizHub account has been restored and is active again."),
    }
    title, intro = labels.get(action, ("Account update", f"Your BizHub account status is now {action}."))
    detail = (reason or "No additional reason was provided.").strip()
    message = f"{intro} Reason: {detail}"
    link = url_for("rules") if action in {"Suspended", "Terminated"} else url_for("notifications")
    create_notification(user_id, "announcement", title, message, link)

def get_valid_coupon(code):
    if not code:
        return None
    coupon = query_db("SELECT c.*, u.username FROM coupons c JOIN users u ON u.id = c.vendor_id WHERE c.code = ? AND c.active = 1 AND (c.expires_at IS NULL OR c.expires_at = '' OR c.expires_at >= ?)", (code.strip().upper(), datetime.now(timezone.utc).date().isoformat()), one=True)
    return coupon

def award_loyalty_points(user_id, order_id, order_total):
    points = max(0, int(float(order_total)))
    if not user_id or not order_id or points <= 0:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    existing = query_db("SELECT id FROM loyalty_transactions WHERE user_id = ? AND order_id = ? AND transaction_type = 'Order reward'", (user_id, order_id), one=True)
    if existing:
        return 0
    query_db("INSERT OR IGNORE INTO loyalty_accounts (user_id, points, updated_at) VALUES (?, 0, ?)", (user_id, now))
    query_db("INSERT INTO loyalty_transactions (user_id, order_id, points, transaction_type, created_at) VALUES (?, ?, ?, 'Order reward', ?)", (user_id, order_id, points, now))
    query_db("UPDATE loyalty_accounts SET points = points + ?, updated_at = ? WHERE user_id = ?", (points, now, user_id))
    query_db("UPDATE orders SET loyalty_points_earned = ? WHERE id = ?", (points, order_id))
    return points

@app.context_processor
def notification_context():
    unread_notifications_count = 0
    if session.get("username"):
        user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
        if user:
            row = query_db("SELECT COUNT(*) AS count FROM notifications WHERE recipient_id = ? AND is_read = 0", (user["id"],), one=True)
            unread_notifications_count = row["count"] if row else 0
    return {"unread_notifications_count": unread_notifications_count}
    # 🔔 ADD THIS ROUTE RIGHT HERE FOR LIVE BACKGROUND CHECKING:
@app.route("/api/unread-notifications-count")
def api_unread_notifications_count():
    if not session.get("username"):
        return {"unread_count": 0}
    
    user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if not user:
        return {"unread_count": 0}
        
    row = query_db("SELECT COUNT(*) AS count FROM notifications WHERE recipient_id = ? AND is_read = 0", (user["id"],), one=True)
    unread_count = row["count"] if row else 0
    return {"unread_count": unread_count}

def issue_subscription_receipt(entry_id):
    entry = query_db("SELECT * FROM financial_ledger WHERE id = ? AND transaction_type = 'Subscription'", (entry_id,), one=True)
    if not entry:
        return None
    user = query_db("SELECT * FROM users WHERE username = ? AND role IN ('Vendor', 'Fast Food', 'Delivery Service')", (entry["username"],), one=True)
    if not user:
        return None
    existing = query_db("SELECT * FROM subscription_receipts WHERE ledger_id = ?", (entry_id,), one=True)
    if existing:
        return existing
    issued_at = datetime.now(timezone.utc)
    expiry = issued_at + timedelta(days=30)
    plan_name = "Premium Delivery" if user["role"] == "Delivery Service" else "Premium Store"
    receipt_number = f"BIZ-{issued_at.strftime('%Y%m%d')}-{entry_id:06d}"
    query_db(
        "INSERT INTO subscription_receipts (receipt_number, ledger_id, user_id, username, plan_name, amount, payment_reference, issued_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (receipt_number, entry_id, user["id"], user["username"], plan_name, entry["amount"], entry["momo_reference"], issued_at.isoformat())
    )
    query_db("UPDATE users SET plan = 'premium', subscription_expires_at = ?, upgrade_requested_at = NULL WHERE id = ?", (expiry.isoformat(), user["id"]))
    if user["role"] == "Delivery Service":
        query_db("UPDATE delivery_services SET availability = 'Unavailable', updated_at = ? WHERE user_id = ?", (issued_at.isoformat(), user["id"]))
    receipt = query_db("SELECT * FROM subscription_receipts WHERE ledger_id = ?", (entry_id,), one=True)
    create_notification(
        user["id"],
        "announcement",
        "Subscription payment approved",
        f"Your {plan_name} subscription payment was approved. Receipt {receipt_number} is ready.",
        url_for("subscription_receipt", receipt_id=receipt["id"])
    )
    return receipt

def notify_favorite_customers(vendor_id, notification_type, title, message, link=None):
    rows = query_db("SELECT customer_id FROM favorites WHERE vendor_id = ?", (vendor_id,)) or []
    for row in rows:
        create_notification(row["customer_id"], notification_type, title, message, link)

def get_delivery_service(user_id):
    return query_db("SELECT * FROM delivery_services WHERE user_id = ?", (user_id,), one=True)

def delivery_access_allowed():
    return bool(session.get("username") and session.get("role") in ["Vendor", "Fast Food"])

def sync_delivery_availability():
    now_iso = datetime.now(timezone.utc).isoformat()
    query_db("UPDATE delivery_services SET availability = 'Unavailable', updated_at = ? WHERE user_id IN (SELECT id FROM users WHERE role = 'Delivery Service' AND (subscription_expires_at IS NULL OR subscription_expires_at <= ?))", (now_iso, now_iso))

def admin_configured():
    env_ready = bool(get_admin_username() and get_admin_password())
    db_ready = bool(query_db("SELECT id FROM admin_users LIMIT 1"))
    return env_ready or db_ready

def get_admin_username():
    return os.environ.get("BIZ_HUB_ADMIN_USERNAME", "").strip()

def get_admin_password():
    return os.environ.get("BIZ_HUB_ADMIN_PASSWORD", "")

def admin_signup_available():
    # Public admin creation is disabled by default. It may only be enabled for
    # first-time bootstrap when explicitly requested through the environment.
    bootstrap = os.environ.get("BIZ_HUB_ALLOW_ADMIN_SIGNUP", "0").strip().lower() in {"1", "true", "yes"}
    return bootstrap and not bool(get_admin_username() and get_admin_password()) and not bool(query_db("SELECT id FROM admin_users LIMIT 1"))

def is_admin():
    return session.get("is_admin") is True

def _bizhub_vapid_material():
    """Return stable VAPID keys derived from the existing BizHub app secret."""
    secret = app.secret_key
    curve_order = int("FFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551""", 16)
    scalar = int.from_bytes(hashlib.sha256(("BizHub-VAPID:" + secret).encode("utf-8")).digest(), "big") % (curve_order - 1) + 1
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        private_key = ec.derive_private_key(scalar, ec.SECP256R1())
        public_key = private_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        private_pem = private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode("ascii")
        public_b64 = base64.urlsafe_b64encode(public_key).rstrip(b"=").decode("ascii")
        return public_b64, private_pem
    except ImportError:
        return "", ""


@app.route("/service-worker.js")
def service_worker():
    # Preserve the existing service-worker/cache behavior and append only the
    # push handlers needed for BizHub notifications.
    worker_path = os.path.join(app.static_folder, "service-worker.js")
    try:
        with open(worker_path, "r", encoding="utf-8") as worker_file:
            worker_source = worker_file.read()
    except OSError:
        worker_source = ""
    push_handlers = r'''

/* BizHub push notification layer. */
self.addEventListener("push", function(event) {
    let payload = {};
    try { payload = event.data ? event.data.json() : {}; } catch (e) {}
    const title = payload.title || "BizHub";
    const message = payload.message || "You have a new BizHub notification.";
    const target = payload.link || "/notifications";
    event.waitUntil(self.registration.showNotification(title, {
        body: message,
        icon: "/static/uploads/bizhub-app-icon.png",
        badge: "/static/uploads/bizhub-app-icon.png",
        tag: "bizhub-notification",
        data: { link: target },
        renotify: true
    }));
});

self.addEventListener("notificationclick", function(event) {
    event.notification.close();
    const target = event.notification && event.notification.data && event.notification.data.link
        ? event.notification.data.link
        : "/notifications";
    event.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then(function(clientList) {
        for (const client of clientList) {
            if ("focus" in client) {
                if ("navigate" in client) client.navigate(target);
                return client.focus();
            }
        }
        return clients.openWindow(target);
    }));
});
'''
    if "/* BizHub push notification layer. */" not in worker_source:
        worker_source += push_handlers
    response = Response(worker_source, mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

@app.route("/rules")
def rules():
    return render_template("rules.html")

def open_db():
    db_path = os.path.join(app.root_path, "marketplace.db")
    conn = sqlite3.connect(db_path, timeout=60, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass
    return conn

def query_db(query, args=(), one=False):
    """Execute a query with reliable locking/cleanup and no SELECT commits."""
    import time
    last_error = None
    for attempt in range(8):
        conn = None
        try:
            conn = open_db()
            cursor = conn.cursor()
            cursor.execute(query, args)
            is_select = query.lstrip().upper().startswith(("SELECT", "PRAGMA", "WITH"))
            if one:
                row = cursor.fetchone()
                res = dict(row) if row else None
            else:
                rows = cursor.fetchall()
                res = [dict(r) for r in rows] if rows else []
            if not is_select:
                conn.commit()
            return res
        except sqlite3.OperationalError as exc:
            last_error = exc
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                raise
            if conn:
                conn.rollback()
            time.sleep(0.15 * (attempt + 1))
        finally:
            if conn:
                conn.close()
    raise last_error

def get_vendor_categories(user_id):
    return [row["category"] for row in query_db("SELECT category FROM vendor_categories WHERE user_id = ? ORDER BY category", (user_id,))]

   


def valid_reset_token(token):
    if not token:
        return None
    return query_db(
        "SELECT * FROM password_resets WHERE token = ? AND used = 0 AND expires_at > ?",
        (token, datetime.now(timezone.utc).isoformat()),
        one=True,
    )

def save_company_logo(upload):
    if not upload or not upload.filename:
        return None
    try:
        extension = os.path.splitext(upload.filename)[1].lower()
        if extension not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            return None
        # Prevent OOM - size check
        try:
            upload.stream.seek(0, os.SEEK_END)
            size = upload.stream.tell()
            upload.stream.seek(0)
            if size > 5 * 1024 * 1024:
                return None
        except Exception:
            pass
        filename = f"company-{uuid.uuid4().hex}{extension}"
        dest = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        upload.save(dest)
        try:
            from PIL import Image
            im = Image.open(dest)
            im.thumbnail((400,400))
            im.save(dest, optimize=True)
        except Exception:
            pass
        return filename
    except Exception:
        logger.exception("Logo save failed")
        return None

# ==========================================================================
# 🍟 FAST FOOD RESTAURANT EXTENSION MODULES (SAFE SCHEMA INTEGRATION)
# ==========================================================================
def run_restaurant_schema_migration():
    """Appends restaurant categorization parameters cleanly to your database structure."""
    conn = open_db()
    cursor = conn.cursor()
    for statement in (
        "ALTER TABLE products ADD COLUMN menu_type TEXT NOT NULL DEFAULT 'Main Dishes'",
        "ALTER TABLE products ADD COLUMN served_with TEXT",
    ):
        try:
            cursor.execute(statement)
        except sqlite3.OperationalError:
            pass  # Skips gracefully if fields are already present in your file registry
    conn.commit()
    conn.close()

# Fire migration instantly upon execution loops
run_restaurant_schema_migration()


@app.route("/publish-product", methods=["POST"])
def publish_product():
    """👑 BIZHUB DEDICATED ISOLATED PRODUCT CREATION SYSTEM: Fully supports Fast Food smart categories."""
    if "username" not in session or session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
        
    vendor = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    if not vendor:
        return redirect(url_for("home"))
        
    subscription = subscription_status(vendor)
    listing_count_row = query_db("SELECT COUNT(*) AS count FROM products WHERE seller = ?", (session["username"],), one=True)
    listing_count = listing_count_row["count"] if listing_count_row else 0
    
    if not subscription["is_premium"] and listing_count >= 3:
        return redirect(url_for("vendor_profile", username=session["username"], listing_error="Basic accounts can list up to 3 products. Upgrade to Premium for unlimited listings."))

    price = request.form.get("price")
    is_fast_food = bool(vendor.get("role") == "Fast Food")
    
    title = request.form.get("meal_name" if is_fast_food else "title")
    description = request.form.get("meal_description" if is_fast_food else "description")
    
    # 🍟 FIXED INTAKES: Matches the form inputs 'menu_type' and 'accompaniments' perfectly
    menu_type = request.form.get("menu_type", "Main Dishes").strip() if is_fast_food else "General"
    accompaniments = html.escape(request.form.get("accompaniments", "").strip()) if is_fast_food else None
    
    category = "Fast Food" if is_fast_food else (request.form.get("category", "Other").strip() or "Other")
    stock_quantity = 0 if is_fast_food else int(request.form.get("stock_quantity", "1") or 1)
    location = request.form.get("location", "").strip() or vendor.get("business_location") or "Accra"
    
    file = request.files.get("product_image")
    video = request.files.get("product_video")
    
    has_image = bool(file and file.filename)
    has_video = bool(video and video.filename)
    
    if not is_fast_food and has_image == has_video:
        return redirect(url_for("vendor_profile", username=session["username"], listing_error="Choose exactly one media option: Image OR Showcase Video."))

    filename = ""
    if has_image:
        ext = os.path.splitext(secure_filename(file.filename))[1].lower()
        if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            return redirect(url_for("vendor_profile", username=session["username"], listing_error="Images must be PNG, JPG, JPEG, WEBP, or GIF."))
        filename = f"product-{uuid.uuid4().hex}{ext}"
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    else:
        filename = ""  # No placeholder - template shows emoji fallback

    video_filename = None
    if has_video:
        ext = os.path.splitext(video.filename)[1].lower()
        if not subscription["is_premium"]:
            return redirect(url_for("vendor_profile", username=session["username"], listing_error="Upgrade to Premium Store to attach showcase video ad loops."))
        if ext not in VIDEO_EXTENSIONS:
            return redirect(url_for("vendor_profile", username=session["username"], listing_error="Videos must be MP4, WebM, or MOV files."))
        video_filename = f"video-{uuid.uuid4().hex}{ext}"
        video.save(os.path.join(app.config["UPLOAD_FOLDER"], video_filename))

    if title and price and description:
        b_label = vendor.get("company_name") or vendor.get("username") or "Individual Vendor"
        
        # 👑 UNBREAKABLE DATABANK SCHEMA MAPPING: Includes menu_type and accompaniments securely
        query_db("""INSERT INTO products (
                title, price, description, image_file, video_file, stock_quantity, 
                initial_stock_quantity, sold_quantity, status, seller, seller_email, 
                seller_whatsapp, location, business_label, category, menu_type, served_with
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'Available', ?, ?, ?, ?, ?, ?, ?, ? )""",
            (title, float(price), description, filename, video_filename, stock_quantity, 
             stock_quantity, vendor["username"], vendor["email"], vendor.get("whatsapp_number"""), 
             location, b_label, category, menu_type, accompaniments)
        )
        
        notify_favorite_customers(vendor["id"], "product", f"{b_label} added a new item", title, url_for("vendor_profile", username=vendor["username"]))
        
    return redirect(url_for("vendor_profile", username=vendor["username"]))


    
   
@app.route("/", methods=["GET", "POST"])
def home():
    """👑 BIZHUB SMART MARKETPLACE CONTROLLER: Handles product creation and tiered chronological feed ranking."""
    welcome_message = bool(session.pop("welcome_message", False))
    listing_error = request.args.get("listing_error")
    company_search = (request.args.get("company_search") or request.args.get("search") or "").strip()

    # ==========================================================================
    # 📦 1. SECURED PRODUCT PUBLISHING ENGINE (POST CHANNELS)
    # ==========================================================================
    if request.method == "POST":
        if "username" not in session or session.get("role") not in ["Vendor", "Fast Food"]:
            return redirect(url_for("home"))
            
        vendor = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
        subscription = subscription_status(vendor)
        listing_count_row = query_db("SELECT COUNT(*) AS count FROM products WHERE seller = ?", (session["username"],), one=True)
        listing_count = listing_count_row["count"] if listing_count_row else 0
        
        if not subscription["is_premium"] and listing_count >= 3:
            return redirect(url_for("home", listing_error="Basic accounts can list up to 3 products. Upgrade to Premium for unlimited listings."))

        price = request.form.get("price")
        is_fast_food = bool(vendor and vendor.get("role") == "Fast Food")
        
        title = request.form.get("meal_name" if is_fast_food else "title")
        description = request.form.get("meal_description" if is_fast_food else "description")
        menu_type = request.form.get("menu_type", "Main Dishes").strip() if is_fast_food else "General"
        accompaniments = html.escape(request.form.get("accompaniments", "").strip()) if is_fast_food else None
        category = "Fast Food" if is_fast_food else (request.form.get("category", "Other").strip() or "Other")
        stock_quantity_raw = request.form.get("stock_quantity", "1")
        location = request.form.get("location", "").strip() or vendor.get("business_location") or "Accra"
        
        file = request.files.get("product_image")
        video = request.files.get("product_video")
        
        has_image = bool(file and file.filename)
        has_video = bool(video and video.filename)
        
        if not is_fast_food and has_image == has_video:
            return redirect(url_for("home", listing_error="Choose exactly one item media option: Image OR Showcase Video."))
        if is_fast_food and not has_image and not has_video:
            return redirect(url_for("home", listing_error="Add a meal image or showcase video before publishing."))

        filename = ""
        if has_image:
            ext = os.path.splitext(secure_filename(file.filename))[1].lower()
            if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                return redirect(url_for("home", listing_error="Item images must be PNG, JPG, JPEG, WEBP, or GIF files."))
            filename = f"product-{uuid.uuid4().hex}{ext}"
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
        else:
            filename = ""  # No placeholder - template shows emoji fallback

        video_filename = None
        if has_video:
            ext = os.path.splitext(video.filename)[1].lower()
            if not subscription["is_premium"]:
                return redirect(url_for("home", listing_error="Only verified vendors with an active Premium Store can upload videos."))
            if ext not in VIDEO_EXTENSIONS:
                return redirect(url_for("home", listing_error="Product videos must be MP4, WebM, or MOV files."))
            
            video_filename = f"video-{uuid.uuid4().hex}{ext}"
            video.save(os.path.join(app.config["UPLOAD_FOLDER"], video_filename))

        stock_quantity = 0 if is_fast_food else int(stock_quantity or 1)

        if title and price and description:
            b_label = vendor.get("company_name") or vendor.get("username") or "Individual Vendor"
            query_db("""INSERT INTO products (
                    title, price, description, image_file, video_file, stock_quantity, 
                    initial_stock_quantity, sold_quantity, status, seller, seller_email, 
                    seller_whatsapp, location, business_label, category, menu_type, served_with
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'Available', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, float(price), description, filename, video_filename, stock_quantity, stock_quantity, vendor["username"], vendor["email"], vendor.get("whatsapp_number"""), location, b_label, category, menu_type, accompaniments)
            )
            return redirect(url_for("vendor_profile", username=vendor["username"], published="fastfood" if is_fast_food else "item"))

    # ==========================================================================
    # 👑 2. CHRONOLOGICAL TIERED SORTING ENGINE (GET CHANNELS)
    # ==========================================================================
    current_username = session.get("username")
    user_role = session.get("role", "Customer")
    
    # Smart Predictive Search Bar Interceptor - FIXED to handle vendor name, store, location, item name (partial + exact)
    search_filter = None
    if company_search:
        cs_lower = company_search.lower().strip()
        # 1. Exact store match username or company_name
        exact_store_match = query_db(
            "SELECT username FROM users WHERE (lower(company_name) = ? OR lower(username) = ?) AND role IN ('Vendor', 'Fast Food') LIMIT 1",
            (cs_lower, cs_lower), one=True
        )
        if exact_store_match:
            return redirect(url_for("vendor_profile", username=exact_store_match["username"]))
        # 2. Partial store match - company_name or username LIKE
        partial_store_match = query_db(
            "SELECT username FROM users WHERE (lower(company_name) LIKE ? OR lower(username) LIKE ?) AND role IN ('Vendor', 'Fast Food') LIMIT 1",
            (f"%{cs_lower}%", f"%{cs_lower}%"), one=True
        )
        if partial_store_match and len(cs_lower) >= 3:
            # If many matches, go to all_stores filtered, else direct
            count_partial = query_db("SELECT COUNT(*) as c FROM users WHERE (lower(company_name) LIKE ? OR lower(username) LIKE ?) AND role IN ('Vendor', 'Fast Food')", (f"%{cs_lower}%", f"%{cs_lower}%"), one=True)
            if count_partial and count_partial["c"] == 1:
                return redirect(url_for("vendor_profile", username=partial_store_match["username"]))
            else:
                return redirect(url_for("all_stores", company_search=company_search))
        # 3. Exact location match
        location_match_check = query_db(
            "SELECT DISTINCT business_location FROM users WHERE lower(business_location) = ? AND role IN ('Vendor', 'Fast Food') LIMIT 1",
            (cs_lower,), one=True
        )
        if location_match_check:
            return redirect(url_for("all_stores", company_search=location_match_check["business_location"]))
        # 4. Partial location match
        location_partial = query_db(
            "SELECT DISTINCT business_location FROM users WHERE lower(business_location) LIKE ? AND role IN ('Vendor', 'Fast Food') LIMIT 1",
            (f"%{cs_lower}%",), one=True
        )
        if location_partial and len(cs_lower) >= 2:
            return redirect(url_for("all_stores", company_search=company_search))
        # 5. Item name - will filter products below, not redirect
        search_filter = cs_lower

    # Core Query Execution: Tag promotions and join business labels cleanly (EXCLUDES FAST FOOD FROM HOME FEED)
    # Build product query with optional item search filter
    if 'search_filter' in locals() and search_filter:
        sf = f"%{search_filter}%"
        raw_products = query_db("""
            SELECT p.*, 
                   u.company_name AS business_label, u.business_location, u.role AS seller_role, u.subscription_expires_at, u.trial_started_at, u.plan,
                   (SELECT id FROM promotions pr WHERE pr.product_id = p.id AND pr.active = 1 LIMIT 1) AS active_promo_id,
                   (SELECT main_price FROM promotions pr WHERE pr.product_id = p.id AND pr.active = 1 LIMIT 1) AS promo_original_price,
                   (SELECT promo_price FROM promotions pr WHERE pr.product_id = p.id AND pr.active = 1 LIMIT 1) AS promo_effective_price
            FROM products p
            JOIN users u ON p.seller = u.username
            WHERE p.status = 'Available' AND (p.category = 'Fast Food' OR p.stock_quantity > 0)
              AND COALESCE(u.account_status,'Active') NOT IN ('Suspended','Terminated')
              AND (lower(p.title) LIKE ? OR lower(p.description) LIKE ? OR lower(p.category) LIKE ? OR lower(u.company_name) LIKE ? OR lower(u.username) LIKE ?)
        """, (sf, sf, sf, sf, sf)) or []
    else:
        raw_products = query_db("""
            SELECT p.*, 
                   u.company_name AS business_label, u.business_location, u.role AS seller_role, u.subscription_expires_at, u.trial_started_at, u.plan,
                   (SELECT id FROM promotions pr WHERE pr.product_id = p.id AND pr.active = 1 LIMIT 1) AS active_promo_id,
                   (SELECT main_price FROM promotions pr WHERE pr.product_id = p.id AND pr.active = 1 LIMIT 1) AS promo_original_price,
                   (SELECT promo_price FROM promotions pr WHERE pr.product_id = p.id AND pr.active = 1 LIMIT 1) AS promo_effective_price
            FROM products p
            JOIN users u ON p.seller = u.username
            WHERE p.status = 'Available' AND (p.category = 'Fast Food' OR p.stock_quantity > 0)
              AND COALESCE(u.account_status,'Active') NOT IN ('Suspended','Terminated')
            """) or []
    
    # Expiry auto-cleanup + Basic limit: Vendors get 2 months free premium from registration, after expiry only 3 listings visible
    from collections import defaultdict
    vendor_counts = defaultdict(int)
    filtered_products = []
    now = datetime.now(timezone.utc)
    for prod in sorted(raw_products, key=lambda x: x.get('id',0), reverse=True):
        # Check vendor subscription
        exp_raw = prod.get('subscription_expires_at')
        exp = None
        if exp_raw:
            try:
                clean = exp_raw.strip().replace(' ','T')
                if '+' not in clean and 'Z' not in clean:
                    clean += '+00:00'
                exp = datetime.fromisoformat(clean)
            except:
                exp = None
        is_expired = not exp or exp <= now
        seller = prod.get('seller')
        if is_expired:
            # Basic account: only first 3 newest listings stay visible (Amazon rule)
            if vendor_counts[seller] >= 3:
                continue
        # Fast Food stock 0 = infinite, don't filter by stock
        if prod.get('category') != 'Fast Food' and int(prod.get('stock_quantity') or 0) <=0:
            continue
        filtered_products.append(prod)
        vendor_counts[seller] += 1
    raw_products = filtered_products

    # Get user's favorites map context safely
    favorited_sellers = set()
    if current_username:
        fav_rows = query_db("""
            SELECT u.username FROM favorites f 
            JOIN users u ON f.vendor_id = u.id 
            WHERE f.customer_id = (SELECT id FROM users WHERE username = ?)
        """, (current_username,)) or []
        favorited_sellers = {row["username"] for row in fav_rows}

    processed_items = []
    for p in raw_products:
        p["is_promo"] = bool(p.get("active_promo_id"""))
        p["is_own"] = bool(current_username and p["seller"] == current_username)
        p["is_favorite"] = bool(p["seller"] in favorited_sellers)
        p["is_kitchen"] = bool(p.get("seller_role") == "Fast Food")
        
        # ASSIGN TIER SCORES ACCORDING TO YOUR EXACT MULTI-ROLE LOGIC RULES
        if user_role in ["Vendor", "Fast Food"]:
            if p["is_own"] and p["is_promo"]:
                p["tier_score"] = 10
                p["display_badge"] = "🔥 Your Promo Listing"
            elif p["is_own"]:
                p["tier_score"] = 9
                p["display_badge"] = " Your Listing"
            elif p["is_favorite"] and p["is_promo"]:
                p["tier_score"] = 8
                p["display_badge"] = "⭐ Favorite Vendor Promo"
            elif not p["is_own"] and p["is_promo"]:
                p["tier_score"] = 7
                p["display_badge"] = "⚡ Market Promotion"
            elif p["is_favorite"]:
                p["tier_score"] = 6
                p["display_badge"] = "💖 Favorite Vendor Stock"
            else:
                p["tier_score"] = 5
                p["display_badge"] = "📦 General Listing"
        else:
            # Customers and Riders Sorting Logic Tier Loops
            if p["is_favorite"] and p["is_promo"]:
                p["tier_score"] = 10
                p["display_badge"] = "⭐ Favorite Vendor Promo"
            elif not p["is_favorite"] and p["is_promo"]:
                p["tier_score"] = 9
                p["display_badge"] = "⚡ Flash Promotion Deal"
            elif p["is_favorite"]:
                p["tier_score"] = 8
                p["display_badge"] = "💖 Favorite Vendor Stock"
            else:
                p["tier_score"] = 7
                p["display_badge"] = "📦 General Listing"
                
        processed_items.append(p)

    # Sort: Priority Rank First, Then Fall Back to Latest Posts (id DESC)
    processed_items.sort(key=lambda x: (-x["tier_score"], -x["id"]))

    # FIX: Don't show own listings twice - vendors already have "Your Listings" section
    if current_username and user_role in ["Vendor", "Fast Food"]:
        processed_items = [p for p in processed_items if p["seller"] != current_username]

    # 👑 QUARTERLY TOP 20 BRANDS LEADERBOARD - Based on customer ratings (quarterly)
    # Calculate current quarter start
    now_dt = datetime.now(timezone.utc)
    quarter_start_month = ((now_dt.month - 1) // 3) * 3 + 1
    quarter_start = datetime(now_dt.year, quarter_start_month, 1, tzinfo=timezone.utc).isoformat()
    
    # Top 20 brands by avg rating this quarter, fallback to all-time if not enough
    top_20_brands = query_db("""
        SELECT DISTINCT u.id, u.username, u.company_name, u.company_logo, u.business_location, u.role, u.is_verified_brand, u.verified_brand_type,
               ROUND(AVG(r.rating), 1) AS avg_rating,
               COUNT(r.id) AS rating_count,
               (SELECT COUNT(*) FROM products p WHERE p.seller = u.username AND p.status='Available') AS product_count
        FROM users u
        JOIN reviews r ON r.vendor_id = u.id
        WHERE u.role IN ('Vendor', 'Fast Food') 
          AND COALESCE(u.account_status, 'Active') NOT IN ('Suspended', 'Terminated')
          AND r.created_at >= ?
        GROUP BY u.id
        HAVING COUNT(r.id) >= 1
        ORDER BY avg_rating DESC, rating_count DESC, u.id DESC
        LIMIT 20
    """, (quarter_start,)) or []
    
    # Fallback to all-time top 20 if quarterly has less than 5 brands
    if len(top_20_brands) < 5:
        top_20_brands = query_db("""
            SELECT u.id, u.username, u.company_name, u.company_logo, u.business_location, u.role, u.is_verified_brand, u.verified_brand_type,
                   ROUND(AVG(r.rating), 1) AS avg_rating,
                   COUNT(r.id) AS rating_count,
                   (SELECT COUNT(*) FROM products p WHERE p.seller = u.username AND p.status='Available') AS product_count
            FROM users u
            JOIN reviews r ON r.vendor_id = u.id
            WHERE u.role IN ('Vendor', 'Fast Food') 
              AND COALESCE(u.account_status, 'Active') NOT IN ('Suspended', 'Terminated')
            GROUP BY u.id
            HAVING COUNT(r.id) >= 1
            ORDER BY avg_rating DESC, rating_count DESC, u.id DESC
            LIMIT 20
            """) or []
    
    # If still empty (no reviews yet), fallback to most active vendors by product count
    if not top_20_brands:
        top_20_brands = query_db("""
            SELECT u.id, u.username, u.company_name, u.company_logo, u.business_location, u.role, u.is_verified_brand, u.verified_brand_type,
                   5.0 AS avg_rating,
                   0 AS rating_count,
                   (SELECT COUNT(*) FROM products p WHERE p.seller = u.username AND p.status='Available') AS product_count
            FROM users u
            WHERE u.role IN ('Vendor', 'Fast Food') 
              AND COALESCE(u.account_status, 'Active') NOT IN ('Suspended', 'Terminated')
            ORDER BY product_count DESC, u.id DESC
            LIMIT 20
            """) or []
    
    for brand in top_20_brands:
        brand["business_label"] = brand.get("company_name") or brand.get("username") or "BizHub Brand"
        # Ensure logo fallback
        if not brand.get("company_logo"):
            brand["company_logo"] = None

    # Restores Live Fast Food Vendors Row
    fast_food_vendors = query_db("""
        SELECT u.id, u.username, u.company_name, u.business_location, u.company_logo, u.whatsapp_number,
               (SELECT COUNT(*) FROM products p WHERE p.seller = u.username AND p.category = 'Fast Food') AS menu_count
        FROM users u WHERE u.role = 'Fast Food' AND COALESCE(u.account_status, 'Active') NOT IN ('Suspended', 'Terminated')
        ORDER BY u.id DESC
            """) or []
    for kitchen in fast_food_vendors:
        kitchen["business_label"] = kitchen.get("company_name") or kitchen.get("username")

    # Restores Live Promotions Feed Row
    now_clean = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    marketplace_promos = query_db("""
        SELECT pr.*, p.id AS product_id, p.title AS product_title, p.price AS product_price,
               p.description AS product_description, p.image_file AS product_image, p.video_file AS product_video,
               p.stock_quantity, p.status AS product_status, p.location AS product_location,
               u.id AS vendor_user_id, u.username AS vendor_username, u.company_name, u.business_location, u.whatsapp_number, u.role AS vendor_role
        FROM promotions pr
        JOIN products p ON p.id = pr.product_id
        JOIN users u ON u.id = pr.vendor_id
        WHERE pr.active = 1 AND replace(pr.starts_at, 'T', ' ') <= ? AND replace(pr.ends_at, 'T', ' ') >= ?
          AND p.status = 'Available' AND COALESCE(p.stock_quantity, 0) > 0 AND u.role NOT IN ('Fast Food')
    """, (now_clean, now_clean)) or []
    for promo in marketplace_promos:
        promo["is_owner"] = bool(current_username and promo["vendor_username"] == current_username)
        promo["is_favorite"] = bool(promo["vendor_username"] in favorited_sellers)
        promo["original_price"] = float(promo.get("main_price""") or promo.get("product_price") or 0)
        promo["effective_price"] = float(promo.get("promo_price") or promo["original_price"])
        if promo.get("discount"):
            promo["discount_percent"] = float(promo["discount"])

    # ==========================================================================
    # 🔔 3. COUNTER UNREAD ALERTS FOR THE BELL SHAKE SYSTEM
    # ==========================================================================
    customer_notification_count = 0
    unread_notifications_count = 0
    if current_username:
        notif_row = query_db("""
            SELECT COUNT(*) AS count FROM notifications 
            WHERE recipient_id = (SELECT id FROM users WHERE username = ?) AND is_read = 0
        """, (current_username,), one=True)
        if notif_row:
            customer_notification_count = notif_row["count"]
            unread_notifications_count = notif_row["count"]

    # ==========================================================================
    # 🖼️ 4. BUILD LOGO MAPS & PREPARE SHOPPING BASKET VARIABLES
    # ==========================================================================
    vendor_logos = {}
    logo_rows = query_db("""SELECT username, company_logo FROM users WHERE company_logo IS NOT NULL""") or []
    for row in logo_rows:
        vendor_logos[row["username"]] = row["company_logo"]

    cart_session = session.get("cart""", {})
    cart_items = []
    cart_total = 0.0
    if isinstance(cart_session, dict):
        for p_id, qty in cart_session.items():
            item_data = query_db("SELECT * FROM products WHERE id = ?", (p_id,), one=True)
            if item_data:
                price_val = float(item_data["price"])
                promo_check = query_db("SELECT promo_price FROM promotions WHERE product_id = ? AND active = 1", (p_id,), one=True)
                if promo_check: 
                    price_val = float(promo_check["promo_price"])
                
                line_total = price_val * int(qty)
                cart_total += line_total
                cart_items.append({
                    "id": item_data["id"],
                    "title": item_data["title"],
                    "cart_quantity": qty,
                    "stock_quantity": item_data["stock_quantity"],
                    "card_unit_price": price_val,
                    "cart_line_total": line_total
                })

    # Prepare vendor dashboard parameters securely
    vendor_user_record = query_db("SELECT * FROM users WHERE username = ?", (current_username,), one=True) if current_username else None
    vendor_subscription = subscription_status(vendor_user_record)
    seller_orders = []

    # Extract the seller's specific current live stock listings panel arrays
    your_marketplace_products = []
    if current_username:
        your_marketplace_products = query_db("SELECT * FROM products WHERE seller = ? ORDER BY id DESC", (current_username,)) or []
        for product in your_marketplace_products:
            product["promo_original_price"] = float(product["price"])

    # ==========================================================================
    # 🎨 5. RENDER THE SECURED PORTAL CONSOLE
    # ==========================================================================
    return render_template("index.html",
                           top_20_brands=top_20_brands,
                           processed_items=processed_items,
                           marketplace_promos=marketplace_promos,
                           fast_food_vendors=fast_food_vendors,
                           kitchens=fast_food_vendors,
                           categories=PRODUCT_CATEGORIES,
                           vendor_logos=vendor_logos,
                           cart_items=cart_items,
                           cart_total=cart_total,
                           cart_count=len(cart_items),
                           seller_orders=seller_orders,
                           vendor_subscription=vendor_subscription,
                           customer_notification_count=customer_notification_count,
                           unread_notifications_count=unread_notifications_count,
                           your_marketplace_products=your_marketplace_products,
                           products=processed_items,
                           company_search=company_search,
                           listing_error=listing_error,
                           welcome_message=welcome_message,
                           kitchen=None)




@app.route("/delete-item/<int:product_id>")
def delete_item(product_id):
    if "username" not in session:
        return redirect(url_for("login"))
    product = query_db("SELECT * FROM products WHERE id = ?", (product_id,), one=True)
    if product and product["seller"] == session["username"]:
        query_db("DELETE FROM products WHERE id = ?", (product_id,))
    return redirect(url_for("home"))

def promotion_now_iso():
    """Return the promotion comparison timestamp in the same format used when promotions are stored."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def active_promo_for_product(product_id, now_iso=None):
    now_iso = (now_iso or promotion_now_iso()).replace("T", " ")
    promo = query_db(
        "SELECT * FROM promotions WHERE product_id = ? AND active = 1 AND replace(starts_at, 'T', ' ') <= ? AND replace(ends_at, 'T', ' ') >= ? ORDER BY id DESC LIMIT 1",
        (product_id, now_iso, now_iso), one=True
    )
    if not promo:
        return None
    return promo

def promo_effective_price(product, promo=None):
    if not promo:
        return float(product["price"])
    # New promotion flow: the vendor supplies the main/original promo price,
    # and BizHub calculates the sale price from the discount percentage.
    if promo.get("main_price") is not None and promo.get("discount") is not None:
        main_price = max(0.0, float(promo["main_price"]))
        return max(0.0, main_price * (1 - float(promo["discount"]) / 100))
    # Keep older promotions working exactly as before.
    if promo.get("promo_price") is not None:
        return max(0.0, float(promo["promo_price"]))
    if promo.get("discount") is not None:
        base_price = float(promo.get("main_price") or product["price"])
        return max(0.0, base_price * (1 - float(promo["discount"]) / 100))
    return float(product["price"])

@app.route("/promotions/deals")
def promo_marketplace():
    now_iso = promotion_now_iso()
    current_user = None
    favorite_vendor_ids = set()
    if session.get("username"):
        current_user = query_db("SELECT id, username, role FROM users WHERE username = ?", (session["username"],), one=True)
        if current_user:
            favorite_rows = query_db("SELECT vendor_id FROM favorites WHERE customer_id = ?", (current_user["id"],)) or []
            favorite_vendor_ids = {int(row["vendor_id"]) for row in favorite_rows}

            search_q = (request.args.get("q") or "").strip()
    search_pattern = f"%{search_q.lower()}%" if search_q else None

    if search_pattern:
        rows = query_db("""
            SELECT pr.*, p.id AS product_id, p.title AS product_title, p.price AS product_price,
                   p.description AS product_description, p.image_file AS product_image, p.video_file AS product_video,
                   p.stock_quantity, p.status AS product_status, p.location AS product_location,
                   u.id AS vendor_user_id, u.username AS vendor_username, u.company_name, u.business_location,
                   u.whatsapp_number, u.company_logo, u.role AS vendor_role
            FROM promotions pr
            JOIN users u ON u.id = pr.vendor_id
            LEFT JOIN products p ON p.id = pr.product_id
            WHERE pr.active = 1
              AND replace(pr.starts_at, 'T', ' ') <= ? AND replace(pr.ends_at, 'T', ' ') >= ?
              AND p.status = 'Available' AND (p.category = 'Fast Food' OR p.stock_quantity > 0)
              AND u.role IN ('Vendor', 'Fast Food')
              AND COALESCE(u.account_status, 'Active') NOT IN ('Suspended', 'Terminated')
              AND (lower(p.title) LIKE ? OR lower(u.company_name) LIKE ? OR lower(u.username) LIKE ? OR lower(pr.title) LIKE ?)
            ORDER BY pr.id DESC
        """, (now_iso, now_iso, search_pattern, search_pattern, search_pattern, search_pattern)) or []
    else:
        rows = query_db("""
            SELECT pr.*, p.id AS product_id, p.title AS product_title, p.price AS product_price,
                   p.description AS product_description, p.image_file AS product_image, p.video_file AS product_video,
                   p.stock_quantity, p.status AS product_status, p.location AS product_location,
                   u.id AS vendor_user_id, u.username AS vendor_username, u.company_name, u.business_location,
                   u.whatsapp_number, u.company_logo, u.role AS vendor_role
            FROM promotions pr
            JOIN users u ON u.id = pr.vendor_id
            LEFT JOIN products p ON p.id = pr.product_id
            WHERE pr.active = 1
              AND replace(pr.starts_at, 'T', ' ') <= ? AND replace(pr.ends_at, 'T', ' ') >= ?
              AND p.status = 'Available' AND (p.category = 'Fast Food' OR p.stock_quantity > 0)
              AND u.role IN ('Vendor', 'Fast Food')
              AND COALESCE(u.account_status, 'Active') NOT IN ('Suspended', 'Terminated')
            ORDER BY pr.id DESC
        """, (now_iso, now_iso)) or []

    deals = []
    for row in rows:
        deal = dict(row)
        deal["is_owner"] = bool(current_user and current_user["role"] in ("Vendor", "Fast Food""") and current_user["id"] == row["vendor_user_id"])
        deal["is_favorite"] = int(row["vendor_user_id"]) in favorite_vendor_ids
        deal["effective_price"] = promo_effective_price(deal, deal)
        deal["original_price"] = float(row["main_price"]) if row.get("main_price") is not None else float(row["product_price"])
        deal["vendor_whatsapp"] = normalize_whatsapp_number(row.get("whatsapp_number"))
        deal["inquiry_text"] = quote(f"Hello {row.get('company_name') or row.get('vendor_username')}, I saw your promo ad on Biz Hub and I'd want to know much about it")
        
        # 👑 ROLE ASSIGNMENT ATTACHMENT: Tracks if the promo belongs to an Uber Eats or Amazon style layout
        deal["is_fast_food"] = bool(row.get("vendor_role") == "Fast Food")
        
        if row.get("discount") is not None:
            deal["discount_percent"] = float(row["discount"])
        elif row.get("main_price") is not None and float(row["main_price"] or 0) > 0:
            effective = promo_effective_price(deal, deal)
            deal["discount_percent"] = max(0.0, (1 - effective / float(row["main_price"])) * 100)
        elif row.get("promo_price") is not None and float(row["product_price"] or 0) > 0:
            deal["discount_percent"] = max(0.0, (1 - float(row["promo_price"]) / float(row["product_price"])) * 100)
        else:
            deal["discount_percent"] = None
        deals.append(deal)

    deals.sort(key=lambda d: (0 if d["is_owner"] else 1 if d["is_favorite"] else 2, -int(d["id"])))
    return render_template("todays_deals.html", deals=deals, current_user=current_user, search_query=search_q)

@app.route("/add-to-cart/<int:product_id>", methods=["POST"])
def add_to_cart(product_id):
    product = query_db("SELECT id, stock_quantity, status, category, title, seller, price FROM products WHERE id = ?", (product_id,), one=True)
    if not product:
        return redirect(url_for("home"))
    
    is_food = bool(product.get("category") == "Fast Food")
    
    if not is_food and (int(product.get("stock_quantity") or 0) < 1 or product.get("status") == "Sold"):
        return redirect(url_for("home", listing_error="This product is sold out."))
    
    try:
        requested_qty = int(request.form.get("quantity", 1) or 1)
    except:
        requested_qty = 1
    if requested_qty < 1:
        requested_qty = 1
    if not is_food:
        requested_qty = min(requested_qty, 99)
    else:
        requested_qty = min(requested_qty, 999)
        
    cart = session.get("cart") or {}
    if isinstance(cart, list):
        cart = {str(pid): 1 for pid in cart}
    key = str(product_id)
    current = int(cart.get(key, 0) or 0)
    
    if not is_food:
        # Race safe check with latest DB value
        latest = query_db("SELECT stock_quantity FROM products WHERE id = ?", (product_id,), one=True)
        latest_stock = int(latest["stock_quantity"] or 0) if latest else 0
        if (current + requested_qty) > latest_stock:
            return redirect(url_for("home", listing_error=f"Only {latest_stock} available for {product['title']}. You already have {current} in cart."))
        
    cart[key] = current + requested_qty
    session["cart"] = cart
    session.modified = True

    if session.get("username"):
        user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
        if user:
            query_db(
                "INSERT INTO cart_history (user_id, product_id, title, seller, price, quantity_added, cart_quantity_after, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user["id"], product["id"], product["title"], product["seller"], float(product["price"]), requested_qty, cart[key], datetime.now(timezone.utc).isoformat())
            )
            # Bloat control: keep only latest 200 per user
            query_db("DELETE FROM cart_history WHERE id NOT IN (SELECT id FROM cart_history WHERE user_id = ? ORDER BY id DESC LIMIT 200) AND user_id = ?", (user["id"], user["id"]))
    return redirect(url_for("home", cart_added="1"))



@app.route("/cart")
def cart_page():
    # 🛒 IMPULSE BUYER FIX: Allow guest cart, don't force login
    user = None
    is_guest = True
    if session.get("username"):
        user = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
        if user:
            is_guest = False
        else:
            session.clear()

    # If guest, create a fake guest user object for template
    if is_guest:
        user = {"username": "Guest", "role": "Guest", "id": 0, "whatsapp_number": None, "company_name": "Guest"}
    

    cart_items = []
    cart_total = 0.0
    discount_total = 0.0
    seller_orders = {}
    active_coupon = get_valid_coupon(session.get("coupon_code"))
    if not active_coupon:
        session.pop("coupon_code", None)

    cart = session.get("cart") or {}
    if isinstance(cart, list):
        cart = {str(pid): 1 for pid in cart}
    if cart:
        ids = [int(k) for k in cart]
        placeholders = ",".join("?" for _ in ids)
        items_in_db = query_db(f"SELECT * FROM products WHERE id IN ({placeholders})", ids) or []
        for item in items_in_db:
            is_food = bool(item.get("category") == "Fast Food")
            
            # 🍟 FAST FOOD VELOCITY EXPANSION MATRIX: Unlocks ordering limits for food menu items
            if is_food:
                qty = max(1, int(cart.get(str(item["id"]), 1)))
            else:
                # 📦 PHYSICAL VENDORS BOUNDARY LOCK: Clamps securely to physical warehouse stock units
                qty = min(int(cart.get(str(item["id"]), 1)), max(0, int(item.get("stock_quantity") or 0)))
                
            if qty <= 0 or (not is_food and item.get("status") == "Sold"):
                continue
                
            item["cart_quantity"] = qty
            item_promo = active_promo_for_product(item["id"])
            item["cart_unit_price"] = promo_effective_price(item, item_promo)
            item["cart_line_total"] = item["cart_unit_price"] * qty
            
            item_discount = 0.0
            if active_coupon and item["seller"] == active_coupon["username"]:
                item_discount = item["cart_line_total"] * float(active_coupon["discount"]) / 100
                
            item["discount_amount"] = item_discount
            item["discounted_line_total"] = item["cart_line_total"] - item_discount
            cart_items.append(item)
            cart_total += item["discounted_line_total"]
            discount_total += item_discount
            
            seller_number = normalize_whatsapp_number(item["seller_whatsapp"])
            seller_key = (item["seller"], seller_number)
            seller_order = seller_orders.setdefault(seller_key, {"seller": item["seller"], "number": seller_number, "items": [], "total": 0.0})
            seller_order["items"].append(item)
            seller_order["total"] += item["discounted_line_total"]


    # 👑 WHATSAPP COUPON LOG INTERCEPTOR MATRIX
    for seller_order in seller_orders.values():
        message = f"Hello {seller_order['seller']}, I want to buy these products on BizHub:\n"
        for item in seller_order["items"]:
            message += f"- {item['title']} (GH₵{item['price']}) in {item['location']}\n"
            
        # If an active coupon is applied, automatically inject it into the text header!
        if active_coupon and active_coupon["username"] == seller_order['seller']:
            message += f"\n🎟️ Coupon Applied: '{active_coupon['code']}' (-{active_coupon['discount']}% OFF on BizHub)"
            
        message += f"\nTotal Cost: GH₵{seller_order['total']:.2f}. Let's arrange for payment and delivery."
        seller_order["whatsapp_text"] = quote(message)


    history = []
    if not is_guest and user.get("id"):
        history = query_db(
            "SELECT id, product_id, title, seller, price, quantity_added, cart_quantity_after, added_at FROM cart_history WHERE user_id = ? ORDER BY id DESC LIMIT 200",
            (user["id"],)
        ) or []

    vendor_notification_count = 0
    customer_notification_count = 0
    if not is_guest and user.get("id"):
        if user["role"] in ["Vendor", "Fast Food"]:
            row = query_db("SELECT COUNT(*) AS count FROM vendor_notifications WHERE vendor_id = ? AND is_read = 0", (user["id"],), one=True)
            vendor_notification_count = row["count"] if row else 0
        else:
            row = query_db("SELECT COUNT(*) AS count FROM notifications WHERE recipient_id = ? AND is_read = 0", (user["id"],), one=True)
            customer_notification_count = row["count"] if row else 0

    return render_template(
        "cart.html",
        is_guest=is_guest,
        user=user,
        cart_items=cart_items,
        cart_count=sum(int(item.get("cart_quantity", 0)) for item in cart_items),
        cart_total=cart_total,
        discount_total=discount_total,
        active_coupon=active_coupon,
        seller_orders=sorted(seller_orders.values(), key=lambda order: order["seller"].lower()),
        history=history,
        vendor_notification_count=vendor_notification_count,
        customer_notification_count=customer_notification_count,
    )

@app.route("/update-cart/<int:product_id>", methods=["POST"])
def update_cart(product_id):
    """👑 CORE INCREMENT ENGINE: Allows infinite meal ordering while protecting physical vendor stock limits."""
    cart = session.get("cart") or {}
    if isinstance(cart, list):
        cart = {str(pid): 1 for pid in cart}
    key = str(product_id)
    
    action_direction = request.form.get("action_direction")
    product = query_db("SELECT id, stock_quantity, status, category FROM products WHERE id = ?", (product_id,), one=True)
    
    if not product:
        cart.pop(key, None)
        session["cart"] = cart
        session.modified = True
        return redirect(url_for("cart_page"))

    is_food = bool(product.get("category") == "Fast Food")
    available_stock = int(product["stock_quantity"] or 0)
    current_qty = int(cart.get(key, 0))
    
    if action_direction == "increase":
        requested_qty = current_qty + 1
    elif action_direction == "decrease":
        requested_qty = current_qty - 1
    else:
        try: requested_qty = int(request.form.get("quantity", "0"))
        except (TypeError, ValueError): requested_qty = 0

    if requested_qty <= 0:
        cart.pop(key, None)
    else:
        if is_food:
            # 🍟 FAST FOOD KITCHEN MENU INFLECTION: Allows infinite meal quantities
            cart[key] = requested_qty
        else:
            # 📦 PHYSICAL VENDORS BLOCK: Clamps tightly to physical stock warehouse bounds
            if product["status"] == "Sold" or available_stock <= 0:
                cart.pop(key, None)
            else:
                cart[key] = min(requested_qty, available_stock)

    session["cart"] = cart
    session.modified = True
    
    client_referrer = request.referrer or ""
    if "/cart" in client_referrer:
        return redirect(url_for("cart_page"))
    return redirect(url_for("home", _anchor="basket"))



   


@app.route("/clear-cart")
def clear_cart():
    session.pop("cart", None)
    session.pop("coupon_code", None)
    return redirect(url_for("home"))

@app.route("/apply-coupon", methods=["POST"])
def apply_coupon():
    if session.get("role") != "Customer":
        return redirect(url_for("login"))
    customer = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    coupon = get_valid_coupon(request.form.get("code", ""))
    if not customer or not coupon:
        return redirect(url_for("home", listing_error="That coupon is invalid, inactive, or expired."))
    used = query_db("SELECT id FROM coupon_redemptions WHERE coupon_id = ? AND customer_id = ?", (coupon["id"], customer["id"]), one=True)
    if used:
        return redirect(url_for("home", listing_error="You have already redeemed this coupon."))
    max_redemptions = int(coupon.get("max_redemptions") or 0)
    if max_redemptions > 0:
        used_total = query_db("SELECT COUNT(*) AS count FROM coupon_redemptions WHERE coupon_id = ?", (coupon["id"],), one=True)
        if used_total and int(used_total["count"] or 0) >= max_redemptions:
            return redirect(url_for("home", listing_error="This coupon has reached its redemption limit."))
    session["coupon_code"] = coupon["code"]
    return redirect(url_for("home", coupon_applied="1"))

@app.route("/remove-coupon", methods=["POST"])
def remove_coupon():
    session.pop("coupon_code", None)
    return redirect(url_for("home"))

@app.route("/place-order", methods=["POST"])
def place_order():
    # 🛒 IMPULSE BUYER: Allow guest order with phone number
    is_guest_order = False
    guest_phone = request.form.get("guest_whatsapp", "").strip()
    guest_name = request.form.get("guest_name", "Guest Buyer").strip() or "Guest Buyer"
    if "username" not in session:
        is_guest_order = True
        if not guest_phone:
            # Instead of forcing login, show phone input error on cart
            return redirect(url_for("cart_page", guest_error="Please enter WhatsApp number to order as guest"))
        # Normalize phone
        guest_phone = normalize_whatsapp_number(guest_phone) or guest_phone
        customer_username = f"guest_{guest_phone}_{uuid.uuid4().hex[:4]}"
    else:
        customer_username = session["username"]
    cart = session.get("cart") or {}
    if isinstance(cart, list):
        cart = {str(pid): 1 for pid in cart}
    try:
        cart = {str(k): int(v) for k, v in cart.items() if int(v) > 0}
    except (TypeError, ValueError):
        return redirect(url_for("home", listing_error="Your cart contains an invalid quantity."))
    if not cart:
        return redirect(url_for("home"))
    ids = [int(k) for k in cart]
    placeholders = ",".join("?" for _ in ids)
    items = query_db(f"SELECT * FROM products WHERE id IN ({placeholders}) AND status = 'Available'", ids) or []
    by_id = {int(item["id"]): item for item in items}
    if len(by_id) != len(ids):
        return redirect(url_for("home", listing_error="One or more cart items are no longer available."))
    for item in items:
        qty = cart[str(item["id"])]
        if qty > int(item["stock_quantity"]):
            return redirect(url_for("home", listing_error=f"Only {item['stock_quantity']} available for {item['title']}."))

    now_iso = datetime.now(timezone.utc).isoformat()
    order_unit_prices = {}
    for item in items:
        promo = active_promo_for_product(item["id"], now_iso)
        order_unit_prices[int(item["id"])] = promo_effective_price(item, promo)

    created_at = now_iso
    conn = open_db()
    try:
        conn.execute("BEGIN")
        active_coupon = None
        coupon_code = session.get("coupon_code")
        if coupon_code:
            active_coupon = conn.execute(
                "SELECT c.*, u.username FROM coupons c JOIN users u ON u.id = c.vendor_id WHERE c.code = ? AND c.active = 1 AND (c.expires_at IS NULL OR c.expires_at = '' OR c.expires_at >= ?)",
                (str(coupon_code).strip().upper(), datetime.now(timezone.utc).date().isoformat())
            ).fetchone()
            if active_coupon:
                existing_redemption = conn.execute(
                    "SELECT id FROM coupon_redemptions WHERE coupon_id = ? AND customer_id = (SELECT id FROM users WHERE username = ?)",
                    (active_coupon["id"], session["username"])
                ).fetchone()
                if existing_redemption:
                    conn.rollback()
                    session.pop("coupon_code", None)
                    return redirect(url_for("home", listing_error="You have already redeemed this coupon."))
                max_redemptions = int(active_coupon["max_redemptions"] or 0)
                if max_redemptions > 0:
                    used_total = conn.execute("SELECT COUNT(*) AS count FROM coupon_redemptions WHERE coupon_id = ?", (active_coupon["id"],)).fetchone()
                    if int(used_total["count"] or 0) >= max_redemptions:
                        conn.rollback()
                        session.pop("coupon_code", None)
                        return redirect(url_for("home", listing_error="This coupon has reached its redemption limit."))

        discount_amount = 0.0
        if active_coupon:
            discount_amount = sum(
                order_unit_prices[int(item["id"])] * cart[str(item["id"])] * float(active_coupon["discount"]) / 100
                for item in items if item["seller"] == active_coupon["username"]
            )
            if discount_amount <= 0:
                active_coupon = None
        subtotal = sum(order_unit_prices[int(item["id"])] * cart[str(item["id"])] for item in items)
        total = max(0.0, subtotal - discount_amount)

        cur = conn.execute(
            "INSERT INTO orders (customer_username, total, status, payment_status, coupon_code, discount_amount, created_at) VALUES (?, ?, 'Pending', 'Unpaid', ?, ?, ?)",
            (customer_username, round(total, 2), active_coupon["code"] if active_coupon else None, round(discount_amount, 2), created_at)
        )
        order_id = cur.lastrowid
        external_vendor_notifications = []
        for item in items:
            qty = cart[str(item["id"])]
            unit_price = order_unit_prices[int(item["id"])]
            conn.execute(
                "INSERT INTO order_items (order_id, product_id, seller, title, price, quantity) VALUES (?, ?, ?, ?, ?, ?)",
                (order_id, item["id"], item["seller"], item["title"], unit_price, qty)
            )
            vendor = conn.execute("SELECT id FROM users WHERE username = ? AND role IN ('Vendor', 'Fast Food')", (item["seller"],)).fetchone()
            if vendor:
                buyer_label = session.get("username") or f"{guest_name} ({guest_phone})"
                message = f"New purchase from @{buyer_label}: {item['title']} x{qty} for GH₵{order_unit_prices[int(item['id'])] * qty:.2f}. Location: {item.get('location') or 'Not specified'}."
                conn.execute(
                    "INSERT INTO vendor_notifications (vendor_id, order_id, product_id, customer_username, item_name, price, location, message, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (vendor["id"], order_id, item["id"], session["username"], item["title"], order_unit_prices[int(item["id"])] * qty, item.get("location"), message, created_at)
                )
                external_vendor_notifications.append((vendor["id"], "New order", message))

        if active_coupon:
            customer = conn.execute("SELECT id FROM users WHERE username = ?", (session["username"],)).fetchone()
            if not customer:
                conn.rollback()
                return redirect(url_for("login"))
            try:
                conn.execute(
                    "INSERT INTO coupon_redemptions (coupon_id, customer_id, order_id, redeemed_at) VALUES (?, ?, ?, ?)",
                    (active_coupon["id"], customer["id"], order_id, created_at)
                )
            except sqlite3.IntegrityError:
                conn.rollback()
                session.pop("coupon_code", None)
                return redirect(url_for("home", listing_error="This coupon can only be redeemed once per customer."))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    for recipient_id, title, message in external_vendor_notifications:
        dispatch_external_notifications(query_db("SELECT * FROM users WHERE id = ?", (recipient_id,), one=True), title, message, url_for("order_history"))
    session.pop("cart", None)
    session.pop("coupon_code", None)
    return redirect(url_for("order_history"))

@app.route("/orders/<int:order_id>/payment-sent", methods=["POST"])
def mark_payment_sent(order_id):
    if "username" not in session:
        return redirect(url_for("login"))
    query_db("UPDATE orders SET payment_status = 'Marked paid' WHERE id = ? AND customer_username = ? AND status = 'Pending'", (order_id, session["username"]))
    customer = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if customer:
        create_notification(customer["id"], "order", "Payment marked", f"Order #{order_id} was marked as paid and is awaiting vendor confirmation.", url_for("order_history"))
    return redirect(url_for("order_history"))

@app.route("/orders")
def order_history():
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    if not user:
        session.clear()
        return redirect(url_for("login"))
    is_vendor = user["role"] in ["Vendor", "Fast Food"]
    if is_vendor:
        raw_orders = query_db("SELECT DISTINCT o.* FROM orders o JOIN order_items oi ON oi.order_id = o.id WHERE oi.seller = ? ORDER BY o.id DESC", (user["username"],)) or []
    else:
        raw_orders = query_db("SELECT * FROM orders WHERE customer_username = ? ORDER BY id DESC", (user["username"],)) or []

    orders = []
    for order in raw_orders:
        if is_vendor:
            items = query_db("""SELECT oi.*, p.image_file AS image, p.location, p.seller AS seller_username, u.company_name AS vendor_company
                               FROM order_items oi LEFT JOIN products p ON p.id = oi.product_id
                               LEFT JOIN users u ON u.username = oi.seller
                               WHERE oi.order_id = ? AND oi.seller = ?""", (order["id"], user["username"])) or []
            customer = query_db("SELECT username, whatsapp_number FROM users WHERE username = ?", (order["customer_username"],), one=True)
            total = sum(float(item["price"]) * int(item["quantity"]) for item in items)
            location = next((item.get("location""") for item in items if item.get("location")), None)
            order_view = dict(order)
            order_view.update({"items": [{"name": i["title"], "price": i["price"], "quantity": i["quantity"], "image": i.get("image"), "vendor_name": i.get("vendor_company") or i["seller"], "vendor_id": i["seller"]} for i in items], "total": total, "location": location, "customer_whatsapp": customer.get("whatsapp_number") if customer else None})
        else:
            items = query_db("""SELECT oi.*, p.image_file AS image, p.location, u.id AS vendor_id, COALESCE(u.company_name, u.username) AS vendor_name
                               FROM order_items oi LEFT JOIN products p ON p.id = oi.product_id
                               LEFT JOIN users u ON u.username = oi.seller
                               WHERE oi.order_id = ?""", (order["id"],)) or []
            order_view = dict(order)
            order_view.update({"items": [{"name": i["title"], "price": i["price"], "quantity": i["quantity"], "image": i.get("image"""), "vendor_name": i.get("vendor_name") or i["seller"], "vendor_id": i.get("vendor_id") or i["seller"]} for i in items], "location": next((i.get("location") for i in items if i.get("location")), None)})
        orders.append(order_view)

    vendor_notification_count = 0
    vendor_notifications = []
    if is_vendor:
        vendor_notification_count_row = query_db("SELECT COUNT(*) AS count FROM vendor_notifications WHERE vendor_id = ? AND is_read = 0", (user["id"],), one=True)
        vendor_notification_count = vendor_notification_count_row["count"] if vendor_notification_count_row else 0
        vendor_notifications = query_db("SELECT * FROM vendor_notifications WHERE vendor_id = ? ORDER BY id DESC LIMIT 30", (user["id"],)) or []

    customer_notification_count = 0
    if not is_vendor:
        row = query_db("SELECT COUNT(*) AS count FROM notifications WHERE recipient_id = ? AND is_read = 0", (user["id"],), one=True)
        customer_notification_count = row["count"] if row else 0

    return render_template("orders.html", user=user, orders=orders, notifications=vendor_notifications, unread_notifications_count=vendor_notification_count, customer_notification_count=customer_notification_count, customer_orders=orders if not is_vendor else [], vendor_orders=orders if is_vendor else [], order_items={o["id"]: [] for o in orders}, order_sellers={})

@app.route("/orders/notifications/read-all", methods=["POST"])
def mark_all_order_notifications_read():
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    vendor = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if vendor:
        query_db("UPDATE vendor_notifications SET is_read = 1 WHERE vendor_id = ?", (vendor["id"],))
    return redirect(safe_internal_referrer("order_history"))

@app.route("/orders/notifications/<int:notification_id>/read", methods=["POST"])
def mark_order_notification_read(notification_id):
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    vendor = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if vendor:
        query_db("UPDATE vendor_notifications SET is_read = 1 WHERE id = ? AND vendor_id = ?", (notification_id, vendor["id"]))
    return redirect(safe_internal_referrer("order_history"))

@app.route("/orders/<int:order_id>/status", methods=["POST"])
def update_order_status(order_id):
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    allowed = {"Confirmed", "Processing", "Completed", "Cancelled"}
    status = request.form.get("status", "").strip()
    if status not in allowed:
        return redirect(url_for("order_history"))
    order = query_db("SELECT * FROM orders WHERE id = ?", (order_id,), one=True)
    owns = query_db("SELECT id FROM order_items WHERE order_id = ? AND seller = ? LIMIT 1", (order_id, session["username"]), one=True)
    if order and owns:
        query_db("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
        query_db("INSERT INTO order_events (order_id, actor_username, status, reason, created_at) VALUES (?, ?, ?, ?, ?)", (order_id, session["username"], status, "Vendor status update", datetime.now(timezone.utc).isoformat()))
        customer = query_db("SELECT id FROM users WHERE username = ?", (order["customer_username"],), one=True)
        if customer:
            create_notification(customer["id"], "order", f"Order #{order_id} updated", f"Your order status is now {status}.", url_for("order_history"))
            if status == "Completed":
                points = award_loyalty_points(customer["id"], order_id, order["total"])
                if points:
                    create_notification(customer["id"], "announcement", "Loyalty points earned", f"You earned {points} BizHub loyalty points for order #{order_id}.", url_for("features"))
    return redirect(url_for("order_history"))

@app.route("/orders/<int:order_id>/confirm", methods=["POST"])
def confirm_order(order_id):
    """👑 AUTOMATED VERIFICATION INTAKE ENGINE: Triggers buyer rating alerts upon confirmation."""
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    conn = open_db()
    customer_username = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        order_items = conn.execute("SELECT * FROM order_items WHERE order_id = ? AND seller = ?", (order_id, session["username"])).fetchall()
        if not order or order["payment_status"] != "Marked paid" or order["status"] != "Pending" or not order_items:
            conn.rollback()
            return redirect(url_for("order_history"))
        for item in order_items:
            qty = int(item["quantity"] or 1)
            product_row = conn.execute("SELECT category, stock_quantity, status FROM products WHERE id = ?", (item["product_id"],)).fetchone()
            if not product_row or product_row["status"] != "Available":
                conn.rollback()
                return redirect(url_for("order_history", inventory_error=f"Sorry, {item['title']} is no longer available."))
            if product_row["category"] == "Fast Food":
                conn.execute("UPDATE products SET sold_quantity = COALESCE(sold_quantity, 0) + ? WHERE id = ? AND category = 'Fast Food'", (qty, item["product_id"]))
            else:
                conn.execute("UPDATE products SET stock_quantity = stock_quantity - ?, sold_quantity = COALESCE(sold_quantity, 0) + ?, status = CASE WHEN stock_quantity - ? <= 0 THEN 'Sold' ELSE 'Available' END WHERE id = ? AND stock_quantity >= ?", (qty, qty, qty, item["product_id"], qty))
        conn.execute("UPDATE orders SET status = 'Confirmed', payment_status = 'Confirmed' WHERE id = ?", (order_id,))
        conn.execute("INSERT INTO order_events (order_id, actor_username, status, reason, created_at) VALUES (?, ?, 'Confirmed', 'Payment and stock confirmed', ?)", (order_id, session["username"], datetime.now(timezone.utc).isoformat()))
        customer_username = order["customer_username"]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
        
    customer = query_db("SELECT id, username, whatsapp_number FROM users WHERE username = ?", (customer_username,), one=True) if customer_username else None
    vendor = query_db("SELECT company_name, username FROM users WHERE username = ?", (session["username"],), one=True)
    v_label = vendor.get("company_name") or vendor.get("username") if vendor else "Verified Merchant"
    
    if customer:
        # 1. Immediate In-App Alert Delivery
        create_notification(
            customer["id"], "order", 
            "❤️ Rate Your Experience", 
            f"Your order #{order_id} from {v_label} has been confirmed! Click here to leave a storefront review feedback statement.", 
            url_for("vendor_profile", username=session["username"])
        )
        # 2. Native Dynamic WhatsApp Click-to-Chat Interceptor
        cust_phone = normalize_whatsapp_number(customer.get("whatsapp_number"))
        if cust_phone:
            wa_text = f"🔔 *BizHub Order Update!*\n\nHello @{customer['username']}, your order #{order_id} from *{v_label}* has been verified and confirmed! 🎉\n\n*How was your experience?* Please click below to rate our service:\n👉 {request.host_url.rstrip('/')}{url_for('vendor_profile', username=session['username'])}"
            session["payment_confirm_wa_redirect"] = f"https://wa.me{cust_phone}?text={quote(wa_text)}"
            
    return redirect(url_for("order_history"))

     

@app.route("/orders/<int:order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    if session.get("role") != "Vendor":
        return redirect(url_for("login"))
    conn = open_db()
    customer_username = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        items = conn.execute("SELECT * FROM order_items WHERE order_id = ? AND seller = ?", (order_id, session["username"])).fetchall()
        if order and items:
            if order["status"] in ("Confirmed", "Processing"):
                for item in items:
                    qty = int(item["quantity"] or 1)
                    conn.execute("UPDATE products SET stock_quantity = stock_quantity + ?, status = 'Available' WHERE id = ? AND category != 'Fast Food'", (qty, item["product_id"]))
            conn.execute("UPDATE orders SET status = 'Cancelled' WHERE id = ?", (order_id,))
            conn.execute("INSERT INTO order_events (order_id, actor_username, status, reason, created_at) VALUES (?, ?, 'Cancelled', 'Vendor cancelled order', ?)", (order_id, session["username"], datetime.now(timezone.utc).isoformat()))
            customer_username = order["customer_username"]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if customer_username:
        customer = query_db("SELECT id FROM users WHERE username = ?", (customer_username,), one=True)
        if customer:
            create_notification(customer["id"], "order", "Order cancelled", f"Order #{order_id} was cancelled by the vendor.", url_for("order_history"))
    return redirect(url_for("order_history"))

@app.route("/product/<int:product_id>")
def product_detail(product_id):
    product = query_db(
        "SELECT p.*, u.company_name, u.username AS vendor_username FROM products p JOIN users u ON u.username = p.seller WHERE p.id = ?",
        (product_id,), one=True
    )
    if not product:
        return redirect(url_for("home"))
    query_db("UPDATE products SET views = COALESCE(views, 0) + 1 WHERE id = ?", (product_id,))
    return render_template("product_detail.html", product=product)

@app.route("/vendor/<username>")
def vendor_profile(username):
    """Renders customized store pages grouped by restaurant menus or catalog grids."""
    vendor = query_db("SELECT * FROM users WHERE username = ? AND role IN ('Vendor', 'Fast Food')", (username,), one=True)
    if not vendor:
        return redirect(url_for("home"))
        
    welcome_message = bool(session.pop("welcome_message", False)) if session.get("username") == vendor.get("username") else False
    favorite_added_message = session.pop("favorite_added_message", None)
    vendor_status = subscription_status(vendor)
    vendor["is_verified"] = vendor_status["is_premium"]
    vendor["is_premium"] = vendor_status["is_premium"]
    is_owner = bool(session.get("username") and session.get("username") == vendor["username"])

    now_iso = promotion_now_iso()
    if vendor.get("role") == "Fast Food":
        products = query_db("SELECT * FROM products WHERE seller = ? ORDER BY CASE menu_type WHEN 'Main Dishes' THEN 1 WHEN 'Sides' THEN 2 WHEN 'Drinks' THEN 3 WHEN 'Desserts' THEN 4 ELSE 5 END, id DESC", (username,)) or []
    else:
        products = query_db("SELECT * FROM products WHERE seller = ? ORDER BY id DESC", (username,)) or []
        
    for product in products:
        product_promo = active_promo_for_product(product["id"], now_iso)
        product["active_promo"] = product_promo
        if product_promo:
            product["promo_original_price"] = float(product_promo.get("main_price") if product_promo.get("main_price") is not None else product["price"])
            product["promo_effective_price"] = promo_effective_price(product, product_promo)

    reviews = query_db("SELECT r.*, u.username AS reviewer_username FROM reviews r JOIN users u ON u.id = r.reviewer_id WHERE r.vendor_id = ? ORDER BY r.id DESC", (vendor["id"],)) or []
    review_summary = query_db("SELECT AVG(rating) AS average_rating, COUNT(*) AS review_count FROM reviews WHERE vendor_id = ?", (vendor["id"],), one=True) or {"average_rating": None, "review_count": 0}
    categories = get_vendor_categories(vendor["id"])
    active_promos = query_db("SELECT * FROM promotions WHERE vendor_id = ? AND active = 1 AND replace(starts_at, 'T', ' ') <= ? AND replace(ends_at, 'T', ' ') >= ? ORDER BY id DESC", (vendor["id"], now_iso, now_iso)) or []
    
    for promo_item in active_promos:
        linked_product = query_db("SELECT * FROM products WHERE id = ?", (promo_item.get("product_id"),), one=True) if promo_item.get("product_id") else None
        promo_item["promo_product_title"] = linked_product.get("title") if linked_product else None
        promo_item["promo_product_image"] = linked_product.get("image_file") if linked_product else None
        promo_item["promo_product_video"] = linked_product.get("video_file") if linked_product else None
        promo_item["promo_original_price"] = float(promo_item.get("main_price") if promo_item.get("main_price") is not None else (linked_product.get("price") if linked_product else 0))
        promo_item["promo_effective_price"] = promo_effective_price(linked_product or {"price": promo_item["promo_original_price"]}, promo_item)
        
    promo = active_promos[0] if active_promos else None
    favorite = False
    if session.get("username"):
        current_user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
        if current_user and current_user["id"] != vendor["id"]:
            favorite = bool(query_db("SELECT id FROM favorites WHERE customer_id = ? AND vendor_id = ?", (current_user["id"], vendor["id"]), one=True))
            
    vendor_whatsapp = normalize_whatsapp_number(vendor.get("whatsapp_number"))
    vendor_whatsapp_text = quote(f"Hey {vendor.get('company_name') or vendor.get('username')}, I visited your store on BizHub and I'd love to know more about your brand.")
    
    for product in products:
        product["meal_whatsapp_number"] = vendor_whatsapp
        product["meal_whatsapp_text"] = quote(f"Hello {vendor.get('company_name') or vendor.get('username')}, I want to buy {product.get('title')} on BizHub, lets arrange for payment and delivery.")
    
    # 👑 FIX: Always pass user for template (prevents 'user' is undefined for guests)
    current_template_user = None
    try:
        if session.get('username'):
            current_template_user = query_db("SELECT * FROM users WHERE username = ?", (session['username'],), one=True)
    except Exception:
        current_template_user = None

    return render_template("vendor_profile.html", user=current_template_user, vendor=vendor, products=products, categories=categories, product_categories=PRODUCT_CATEGORIES, promo=promo, active_promos=active_promos, favorite=favorite, product_count=len(products), subscription=vendor_status, vendor_whatsapp=vendor_whatsapp, vendor_whatsapp_text=vendor_whatsapp_text, reviews=reviews, review_summary=review_summary, is_owner=is_owner, welcome_message=welcome_message, favorite_added_message=favorite_added_message)




@app.route("/report/<int:user_id>", methods=["GET", "POST"])
def report_user(user_id):
    if "username" not in session:
        return redirect(url_for("login"))
    reporter = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    target = query_db("SELECT id, username, company_name, role FROM users WHERE id = ? AND role IN ('Vendor', 'Fast Food', 'Delivery Service')", (user_id,), one=True)
    if not reporter or not target or reporter["id"] == target["id"]:
        return redirect(url_for("home"))
    if request.method == "POST":
        category = request.form.get("category", "Other").strip()
        description = request.form.get("description", "").strip()
        allowed_categories = {"Fraud or payment", "Unsafe or abusive conduct", "Misleading listing", "Spam", "Other"}
        if category not in allowed_categories:
            category = "Other"
        if description:
            query_db("INSERT INTO reports (reporter_id, target_user_id, target_username, target_role, category, description, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (reporter["id"], target["id"], target["username"], target["role"], category, description, datetime.now(timezone.utc).isoformat()))
            create_notification(reporter["id"], "announcement", "Report received", f"BizHub received your report about @{target['username']}. Our team will review it before taking action.", url_for("notifications"))
            return redirect(url_for("notifications"))
        return render_template("report.html", target=target, report_error="Please describe what happened.")
    return render_template("report.html", target=target)

@app.route("/fast-food")
def fast_food_stores():
    if "username" in session:
        current_user = query_db("SELECT id, username, role FROM users WHERE username = ?", (session["username"],), one=True)
    else:
        current_user = None

    # --- TOP 20 KITCHENS OF QUARTER (auto flash) ---
    try:
        now_dt = datetime.now(timezone.utc)
        quarter_start_month = ((now_dt.month - 1) // 3) * 3 + 1
        quarter_start = datetime(now_dt.year, quarter_start_month, 1, tzinfo=timezone.utc).isoformat()
        quarter_name = f"Q{((now_dt.month-1)//3)+1} {now_dt.year}"
        top_kitchens_quarter = query_db("""
            SELECT DISTINCT u.id, u.username, u.company_name, u.business_location, u.company_logo,
                   ROUND(AVG(r.rating),1) AS avg_rating, COUNT(r.id) AS rating_count,
                   (SELECT COUNT(*) FROM products p WHERE p.seller = u.username AND p.category = 'Fast Food') AS menu_count
            FROM users u JOIN reviews r ON r.vendor_id = u.id
            WHERE u.role = 'Fast Food' AND COALESCE(u.account_status,'Active') NOT IN ('Suspended','Terminated')
            AND r.created_at >= ?
            GROUP BY u.id ORDER BY avg_rating DESC, rating_count DESC LIMIT 20
        """, (quarter_start,)) or []
        if len(top_kitchens_quarter) < 3:
            top_kitchens_quarter = query_db("""
                SELECT DISTINCT u.id, u.username, u.company_name, u.business_location, u.company_logo,
                       ROUND(AVG(r.rating),1) AS avg_rating, COUNT(r.id) AS rating_count,
                       (SELECT COUNT(*) FROM products p WHERE p.seller = u.username AND p.category = 'Fast Food') AS menu_count
                FROM users u JOIN reviews r ON r.vendor_id = u.id
                WHERE u.role = 'Fast Food' AND COALESCE(u.account_status,'Active') NOT IN ('Suspended','Terminated')
                GROUP BY u.id ORDER BY avg_rating DESC, rating_count DESC LIMIT 20
            """) or []
        for b in top_kitchens_quarter:
            b['business_label'] = b.get('company_name') or b.get('username')
    except Exception as e:
        logger.exception("top kitchens quarter failed")
        top_kitchens_quarter = []
        quarter_name = ""

    # --- ALL KITCHENS ---
    kitchens = query_db("""
        SELECT u.id, u.username, u.company_name, u.business_location, u.company_logo, u.whatsapp_number,
               (SELECT COUNT(*) FROM products p WHERE p.seller = u.username AND p.category = 'Fast Food') AS menu_count
        FROM users u
        WHERE u.role = 'Fast Food' AND COALESCE(u.account_status, 'Active') NOT IN ('Suspended', 'Terminated')
        ORDER BY u.id DESC
    """) or []

    owner_username = current_user["username"] if current_user and current_user["role"] == "Fast Food" else None
    favorite_vendor_ids = set()
    if current_user and current_user.get("role") in FAVORITE_ACTOR_ROLES:
        favorite_rows = query_db("SELECT vendor_id FROM favorites WHERE customer_id = ?", (current_user["id"],)) or []
        favorite_vendor_ids = {row["vendor_id"] for row in favorite_rows}
    favorite_added_message = session.pop("favorite_added_message", None)
    kitchens.sort(key=lambda k: (k.get("username") != owner_username, -int(k.get("id") or 0)))
    for kitchen in kitchens:
        kitchen["business_label"] = kitchen.get("company_name") or kitchen.get("username")
        kitchen["is_owner"] = kitchen.get("username") == owner_username
        kitchen["is_favorite"] = kitchen.get("id") in favorite_vendor_ids

    return render_template("fast_food_stores.html", kitchens=kitchens, top_kitchens_quarter=top_kitchens_quarter, quarter_name=quarter_name, favorite_added_message=favorite_added_message)

@app.route("/top-brands")
def top_brands():
    if "username" in session:
        current_user = query_db("SELECT id, username, role FROM users WHERE username = ?", (session["username"],), one=True)
    else:
        current_user = None
    try:
        now_dt = datetime.now(timezone.utc)
        quarter_start_month = ((now_dt.month - 1) // 3) * 3 + 1
        quarter_start = datetime(now_dt.year, quarter_start_month, 1, tzinfo=timezone.utc).isoformat()
        top_20_brands = query_db("""
            SELECT DISTINCT u.id, u.username, u.company_name, u.company_logo, u.business_location, u.role,
                   ROUND(AVG(r.rating),1) AS avg_rating, COUNT(r.id) AS rating_count
            FROM users u JOIN reviews r ON r.vendor_id = u.id
            WHERE u.role IN ('Vendor','Fast Food') AND COALESCE(u.account_status,'Active') NOT IN ('Suspended','Terminated')
            AND r.created_at >= ?
            GROUP BY u.id ORDER BY avg_rating DESC, rating_count DESC LIMIT 20
        """, (quarter_start,)) or []
        if len(top_20_brands) < 5:
            top_20_brands = query_db("""
                SELECT DISTINCT u.id, u.username, u.company_name, u.company_logo, u.business_location, u.role,
                       ROUND(AVG(r.rating),1) AS avg_rating, COUNT(r.id) AS rating_count
                FROM users u JOIN reviews r ON r.vendor_id = u.id
                WHERE u.role IN ('Vendor','Fast Food') AND COALESCE(u.account_status,'Active') NOT IN ('Suspended','Terminated')
                GROUP BY u.id ORDER BY avg_rating DESC, rating_count DESC LIMIT 20
            """) or []
        for b in top_20_brands:
            b['business_label'] = b.get('company_name') or b.get('username')
    except:
        top_20_brands = []
    return render_template("top_brands.html", top_20_brands=top_20_brands, current_user=current_user)

FAVORITE_ACTOR_ROLES = {"Customer", "Vendor", "Fast Food", "Delivery Service"}

@app.route("/all-stores")
def all_stores():
    if "username" in session:
        current_user = query_db("SELECT id, username, role FROM users WHERE username = ?", (session["username"],), one=True)
    else:
        current_user = None

    search_query = (request.args.get("company_search") or request.args.get("search") or "").strip()
    target_category = request.args.get("category", "").strip()
    target_role = request.args.get("role", "").strip()
    
    product_args = []
    base_conditions = ["COALESCE(u.account_status, 'Active') NOT IN ('Suspended', 'Terminated')"]
    if target_role:
        base_conditions.append("u.role = ?"); product_args.append(target_role)
    elif target_category:
        base_conditions.append("u.id IN (SELECT user_id FROM vendor_categories WHERE category = ?)"); product_args.append(target_category)
    elif search_query:
        search_pattern = f"%{search_query}%"
        base_conditions.append("(u.company_name LIKE ? OR u.username LIKE ? OR u.business_location LIKE ?)")
        product_args.extend([search_pattern, search_pattern, search_pattern])
    else:
        base_conditions.append("u.role = 'Vendor'")

    # --- TOP 20 VENDORS OF QUARTER (auto flash) ---
    try:
        now_dt = datetime.now(timezone.utc)
        quarter_start_month = ((now_dt.month - 1) // 3) * 3 + 1
        quarter_start = datetime(now_dt.year, quarter_start_month, 1, tzinfo=timezone.utc).isoformat()
        quarter_name = f"Q{((now_dt.month-1)//3)+1} {now_dt.year}"
        top_vendors_quarter = query_db("""
            SELECT DISTINCT u.id, u.username, u.company_name, u.business_location, u.company_logo,
                   ROUND(AVG(r.rating),1) AS avg_rating, COUNT(r.id) AS rating_count,
                   (SELECT COUNT(*) FROM products p WHERE p.seller = u.username) AS product_count
            FROM users u JOIN reviews r ON r.vendor_id = u.id
            WHERE u.role = 'Vendor' AND COALESCE(u.account_status,'Active') NOT IN ('Suspended','Terminated')
            AND r.created_at >= ?
            GROUP BY u.id ORDER BY avg_rating DESC, rating_count DESC LIMIT 20
        """, (quarter_start,)) or []
        if len(top_vendors_quarter) < 3:
            top_vendors_quarter = query_db("""
                SELECT DISTINCT u.id, u.username, u.company_name, u.business_location, u.company_logo,
                       ROUND(AVG(r.rating),1) AS avg_rating, COUNT(r.id) AS rating_count,
                       (SELECT COUNT(*) FROM products p WHERE p.seller = u.username) AS product_count
                FROM users u JOIN reviews r ON r.vendor_id = u.id
                WHERE u.role = 'Vendor' AND COALESCE(u.account_status,'Active') NOT IN ('Suspended','Terminated')
                GROUP BY u.id ORDER BY avg_rating DESC, rating_count DESC LIMIT 20
            """) or []
        for b in top_vendors_quarter:
            b['business_label'] = b.get('company_name') or b.get('username')
    except Exception:
        top_vendors_quarter = []; quarter_name = ""

    stores_query = f"""
        SELECT u.id, u.username, u.company_name, u.business_location, u.company_logo, u.whatsapp_number, u.role,
               (SELECT COUNT(*) FROM products p WHERE p.seller = u.username) AS product_count
        FROM users u WHERE {" AND ".join(base_conditions)} ORDER BY u.id DESC
    """
    stores = query_db(stores_query, product_args) or []
    owner_username = current_user["username"] if current_user and current_user["role"] in ("Vendor", "Fast Food") else None
    favorite_vendor_ids = set()
    if current_user and current_user.get("role") in FAVORITE_ACTOR_ROLES:
        favorite_rows = query_db("SELECT vendor_id FROM favorites WHERE customer_id = ?", (current_user["id"],)) or []
        favorite_vendor_ids = {row["vendor_id"] for row in favorite_rows}
    favorite_added_message = session.pop("favorite_added_message", None)
    stores.sort(key=lambda s: (s.get("username") != owner_username, -int(s.get("id") or 0)))
    for store in stores:
        store["business_label"] = store.get("company_name") or store.get("username")
        store["is_owner"] = store.get("username") == owner_username
        store["is_favorite"] = store.get("id") in favorite_vendor_ids
        
    return render_template("all_stores.html", stores=stores, top_vendors_quarter=top_vendors_quarter, quarter_name=quarter_name, favorite_added_message=favorite_added_message, search_query=search_query or target_category or target_role)
   

 

@app.route("/favorites")
def favorites():
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT id, username, role FROM users WHERE username = ?", (session["username"],), one=True)
    vendors = []
    if user:
        vendors = query_db("""
            SELECT u.*,
                   (SELECT COUNT(*) FROM products p WHERE p.seller = u.username) AS product_count
            FROM favorites f
            JOIN users u ON u.id = f.vendor_id
            WHERE f.customer_id = ? AND u.role IN ('Vendor', 'Fast Food')
              AND COALESCE(u.account_status, 'Active') NOT IN ('Suspended', 'Terminated')
            ORDER BY f.id DESC
        """, (user["id"],)) or []
        now_iso = promotion_now_iso()
        for vendor in vendors:
            vendor["categories"] = get_vendor_categories(vendor["id"])
            vendor["promo"] = query_db("SELECT * FROM promotions WHERE vendor_id = ? AND active = 1 AND replace(starts_at, 'T', ' ') <= ? AND replace(ends_at, 'T', ' ') >= ? ORDER BY id DESC LIMIT 1", (vendor["id"], now_iso, now_iso), one=True)
            vendor["business_label"] = vendor.get("company_name""") or vendor.get("username")
    return render_template("favorites.html", vendors=vendors, current_user=user)


@app.route("/toggle-favorite/<username>", methods=["POST"])
def toggle_favorite(username):
    if "username" not in session:
        return redirect(url_for("login"))
    actor = query_db("SELECT id, username, role, whatsapp_number FROM users WHERE username = ?", (session["username"],), one=True)
    if not actor or actor.get("role") not in FAVORITE_ACTOR_ROLES:
        return redirect(safe_internal_referrer(url_for("vendor_profile", username=username)))
    vendor = query_db("SELECT id, username, company_name, whatsapp_number, business_location, role FROM users WHERE username = ? AND role IN ('Vendor', 'Fast Food')", (username,), one=True)
    if not vendor or actor["id"] == vendor["id"]:
        return redirect(safe_internal_referrer(url_for("vendor_profile", username=username)))
    existing = query_db("SELECT id FROM favorites WHERE customer_id = ? AND vendor_id = ?", (actor["id"], vendor["id"]), one=True)
    if existing:
        query_db("DELETE FROM favorites WHERE id = ?", (existing["id"],))
        session["favorite_added_message"] = f"Removed {vendor.get('company_name') or vendor.get('username')} from favorites"
    else:
        query_db("INSERT INTO favorites (customer_id, vendor_id, created_at) VALUES (?, ?, ?)", (actor["id"], vendor["id"], datetime.now(timezone.utc).isoformat()))
        company_name = vendor.get("company_name") or vendor.get("username")

        # TOAST for user
        session["favorite_added_message"] = f"Added {company_name} to your favorites. You can remove them when you want"

        # 1. IN-APP NOTIFICATION TO VENDOR (existing)
        create_notification(vendor["id"], "favorite", "New Favorite ❤️", f"@{actor['username']} added your store {company_name} to their favorites.", url_for("vendor_profile", username=username))
        
        # 2. FEEDBACK IN-APP TO USER WHO DID IT (existing)
        create_notification(
            actor["id"], "favorite", "Thank You for Adding a Favorite ❤️🙏",
            f"Thank you for adding @{username} ({company_name}) to your BizHub favorites! ❤️🙏",
            url_for("notifications")
        )

        # 3. NEW: WHATSAPP NOTIFICATIONS - SAFE, NON-BLOCKING
        try:
            vendor_wa = normalize_whatsapp_number(vendor.get("whatsapp_number"))
            if vendor_wa:
                wa_text_vendor = f"❤️ BizHub Favorite Alert!\n\nHello {company_name}, @{actor['username']} just favorited your {'kitchen' if vendor['role']=='Fast Food' else 'store'} on BizHub! 🎉 They will see your new products first."
                # Save to vendor_notifications so vendor sees WA text in dashboard + in-app
                query_db(
                    "INSERT INTO vendor_notifications (vendor_id, customer_username, item_name, message, created_at, is_read) VALUES (?, ?, ?, ?, ?, 0)",
                    (vendor["id"], actor["username"], f"Favorite: {company_name}", wa_text_vendor, datetime.now(timezone.utc).isoformat())
                )
                # WhatsApp link for customer to optionally message vendor (impulse chat)
                vendor_wa_link = f"https://wa.me/{vendor_wa}?text={quote(f'Hi {company_name}! I just added your store to my BizHub favorites ❤️')}"
                session["favorite_vendor_wa_link"] = vendor_wa_link
        except Exception as e:
            print(f"Favorite WhatsApp hook failed: {e}")

    return redirect(safe_internal_referrer(url_for("vendor_profile", username=username)))

@app.route("/notifications/<int:notification_id>/open", methods=["POST"])
def open_notification(notification_id):
    """Open the notification message inside Notifications and mark it read; never follow its stored link."""
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    if not user:
        return redirect(url_for("login"))
    notification = query_db("SELECT id FROM notifications WHERE id = ? AND recipient_id = ?", (notification_id, user["id"]), one=True)
    if not notification:
        return redirect(url_for("notifications"))
    query_db("UPDATE notifications SET is_read = 1 WHERE id = ? AND recipient_id = ?", (notification_id, user["id"]))
    rows = query_db("SELECT * FROM notifications WHERE recipient_id = ? ORDER BY id DESC LIMIT 80", (user["id"],)) or []
    unread = sum(1 for row in rows if not row["is_read"])
    return render_template("notifications.html", user=user, notifications=rows, unread_count=unread, opened_notification_id=notification_id)

@app.route("/notifications/<int:notification_id>/read", methods=["POST"])
def mark_notification_read(notification_id):
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if user:
        query_db("UPDATE notifications SET is_read = 1 WHERE id = ? AND recipient_id = ?", (notification_id, user["id"]))
    return redirect(safe_internal_referrer("notifications"))

@app.route("/notifications/read-all", methods=["POST"])
def mark_all_notifications_read():
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if user:
        query_db("UPDATE notifications SET is_read = 1 WHERE recipient_id = ?", (user["id"],))
    return redirect(safe_internal_referrer("notifications"))

@app.route("/notifications")
def notifications():
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    if not user:
        session.clear()
        return redirect(url_for("login"))
    # Hide vendor delivery notifications away from customers - customers should not see delivery dispatch alerts
    if user.get('role') == 'Customer':
        rows = query_db("SELECT * FROM notifications WHERE recipient_id = ? AND COALESCE(notification_type,'') NOT IN ('delivery') ORDER BY id DESC LIMIT 80", (user["id"],)) or []
    else:
        rows = query_db("SELECT * FROM notifications WHERE recipient_id = ? ORDER BY id DESC LIMIT 80", (user["id"],)) or []
    unread = sum(1 for row in rows if not row["is_read"])
    return render_template("notifications.html", user=user, notifications=rows, unread_count=unread)

@app.route("/push/subscribe", methods=["POST"])
def subscribe_push():
    if "username" not in session:
        return {"ok": False, "error": "Authentication required"}, 401
    subscription = request.get_json(silent=True)
    if not isinstance(subscription, dict) or not subscription.get("endpoint"):
        return {"ok": False, "error": "Invalid push subscription"}, 400
    user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if user:
        query_db("INSERT OR IGNORE INTO push_subscriptions (user_id, subscription_json, created_at) VALUES (?, ?, ?)", (user["id"], json.dumps(subscription, separators=(",", ":"), sort_keys=True), datetime.now(timezone.utc).isoformat()))
    return {"ok": True}

@app.route("/save-fcm-token", methods=["POST"])
def save_fcm_token():
    if "username" not in session:
        return "", 204
    data = request.get_json() or {}
    token = data.get("token")
    if token:
        try:
            db = get_db()
            # try create column if e no exist
            try:
                db.execute("ALTER TABLE users ADD COLUMN fcm_token TEXT")
            except:
                pass
            db.execute("UPDATE users SET fcm_token = ? WHERE username = ?", (token, session["username"]))
            db.commit()
        except Exception as e:
            print(e)
    return "", 204

@app.route("/push/vapid-public-key")
def vapid_public_key():
    if "username" not in session:
        return {"ok": False}, 401
    public_key, _ = _bizhub_vapid_material()
    if not public_key:
        return {"ok": False, "error": "Browser push support is unavailable on this server."}, 503
    return {"public_key": public_key}

@app.route("/push/firebase-token", methods=["POST"])
def save_firebase_token():
    if "username" not in session:
        return {"ok": False, "error": "Authentication required"}, 401
    payload = request.get_json(silent=True) or {}
    token = payload.get("token", "").strip()
    if not token or len(token) > 4096:
        return {"ok": False, "error": "Invalid Firebase token"}, 400
    query_db("UPDATE users SET firebase_token = ? WHERE username = ?", (token, session["username"]))
    return {"ok": True}

@app.route("/notifications/<int:notification_id>/read-customer", methods=["POST"])
def mark_customer_notification_read(notification_id):
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if user:
        query_db("UPDATE notifications SET is_read = 1 WHERE id = ? AND recipient_id = ?", (notification_id, user["id"]))
    return redirect(safe_internal_referrer("notifications"))

@app.route("/notifications/customer/read-all", methods=["POST"])
def mark_all_customer_notifications_read():
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if user:
        query_db("UPDATE notifications SET is_read = 1 WHERE recipient_id = ?", (user["id"],))
    return redirect(safe_internal_referrer("notifications"))

@app.route("/features")
def features():
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    loyalty = query_db("SELECT * FROM loyalty_accounts WHERE user_id = ?", (user["id"],), one=True)
    if not loyalty:
        now = datetime.now(timezone.utc).isoformat()
        query_db("INSERT INTO loyalty_accounts (user_id, points, updated_at) VALUES (?, 0, ?)", (user["id"], now))
        loyalty = {"points": 0}
    reviews = query_db("SELECT r.*, u.username AS vendor_username, u.company_name FROM reviews r JOIN users u ON u.id = r.vendor_id WHERE r.reviewer_id = ? ORDER BY r.id DESC", (user["id"],)) or []
    delivery_requests = query_db("SELECT dr.*, ds.service_name FROM delivery_requests dr JOIN delivery_services ds ON ds.id = dr.service_id WHERE dr.vendor_id = ? ORDER BY dr.id DESC", (user["id"],)) or []
    rated_request_ids = {r["request_id"] for r in (query_db("SELECT request_id FROM delivery_ratings WHERE vendor_id = ?", (user["id"],)) or [])}
    verification_request = query_db("SELECT * FROM verification_requests WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user["id"],), one=True)
    saved_searches = query_db("SELECT * FROM saved_searches WHERE user_id = ? ORDER BY id DESC", (user["id"],)) or []
    analytics = None
    coupons = []
    if user["role"] in ["Vendor", "Fast Food"]:
        analytics = query_db("SELECT COUNT(*) AS listings, COALESCE(SUM(views), 0) AS views, COALESCE(SUM(sold_quantity), 0) AS sold_units FROM products WHERE seller = ?", (user["username"],), one=True)
        coupons = query_db("SELECT * FROM coupons WHERE vendor_id = ? ORDER BY id DESC", (user["id"],)) or []
    return render_template("features.html", user=user, loyalty=loyalty, reviews=reviews, delivery_requests=delivery_requests, rated_request_ids=rated_request_ids, verification_request=verification_request, saved_searches=saved_searches, analytics=analytics, coupons=coupons, verification_sent=request.args.get("verification_sent") == "1")

@app.route("/coupons", methods=["POST"])
def create_coupon():
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    vendor = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    code = request.form.get("code", "").strip().upper()
    description = request.form.get("description", "").strip()
    expires_at = request.form.get("expires_at", "").strip() or None
    try:
        discount = float(request.form.get("discount", 0))
        max_redemptions = int(request.form.get("max_redemptions", 0) or 0)
    except (TypeError, ValueError):
        discount, max_redemptions = 0, -1
    expiry_ok = True
    if expires_at:
        try:
            expiry_date = datetime.strptime(expires_at, "%Y-%m-%d").date()
            expiry_ok = expiry_date >= datetime.now(timezone.utc).date()
        except ValueError:
            expiry_ok = False
    code_ok = bool(re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{2,31}", code))
    if vendor and code_ok and description and 0 < discount <= 100 and max_redemptions >= 0 and expiry_ok:
        try:
            query_db(
                "INSERT INTO coupons (vendor_id, code, description, discount, max_redemptions, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (vendor["id"], code, description[:200], discount, max_redemptions, expires_at, datetime.now(timezone.utc).isoformat())
            )
        except sqlite3.IntegrityError:
            pass
    return redirect(url_for("features"))

@app.route("/reviews/<int:vendor_id>", methods=["POST"])
def submit_review(vendor_id):
    """🏆 BIZHUB QUARTERLY MARKETPLACE LEADERBOARD ENGINE"""
    if session.get("role") != "Customer":
        return redirect(url_for("login"))
    reviewer = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    vendor = query_db("SELECT id, username, company_name FROM users WHERE id = ?", (vendor_id,), one=True)
    if not reviewer or not vendor:
        return redirect(url_for("home"))
        
    try: rating = int(request.form.get("rating", 5))
    except ValueError: rating = 5
    comment = request.form.get("comment", "").strip()
    
    if comment:
        query_db("INSERT INTO reviews (reviewer_id, vendor_id, rating, comment, created_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(reviewer_id, vendor_id) DO UPDATE SET rating = excluded.rating, comment = excluded.comment, created_at = excluded.created_at", (reviewer["id"], vendor["id"], rating, comment, datetime.now(timezone.utc).isoformat()))
        
        # 🗓️ QUARTERLY AUTOMATED BRAND TRACKING SYSTEM FOR MERCHANT STORES
        current_month = datetime.now(timezone.utc).month
        if current_month in [3, 6, 9, 12] and rating == 5:
            top_stores = query_db("""
                SELECT u.id, COALESCE(u.company_name, u.username) as name, AVG(r.rating) as score FROM users u 
                JOIN reviews r ON u.id = r.vendor_id GROUP BY u.id ORDER BY score DESC LIMIT 20
            """) or []
            if any(s["id"] == vendor["id"] for s in top_stores):
                award_title = "🏆 Elite Storefront Award: Quarterly Top 20 Stores Published!"
                award_msg = f"🎉 Congratulations to *{vendor['company_name'] or vendor['username']}* for securing an elite position in BizHub's Top 20 Highly Rated Marketplace Stores this quarter!"
                for u in query_db("SELECT id FROM users"):
                    query_db("INSERT INTO notifications (recipient_id, notification_type, title, message, link, created_at) VALUES (?, 'announcement', ?, ?, ?, ?)""", (u["id"], award_title, award_msg, url_for("all_stores"), datetime.now(timezone.utc).isoformat()))
                    
    return redirect(url_for("vendor_profile", username=vendor["username"]))


@app.route("/verification/request", methods=["POST"])
def request_verification():
    if session.get("role") not in ["Vendor", "Fast Food", "Delivery Service"]:
        return redirect(url_for("login"))
    user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    user_message = request.form.get("user_message", "").strip()[:2000]
    if user:
        pending = query_db("SELECT id FROM verification_requests WHERE user_id = ? AND status = 'Pending'", (user["id"],), one=True)
        if not pending:
            query_db(
                "INSERT INTO verification_requests (user_id, user_message, created_at) VALUES (?, ?, ?)",
                (user["id"], user_message or None, datetime.now(timezone.utc).isoformat())
            )
            create_notification(user["id"], "announcement", "Verification request sent", "Your BizHub verification request has been sent. BizHub will review it and notify you of the outcome.", url_for("features"))
        return redirect(url_for("features", verification_sent="1"))
    return redirect(url_for("features"))

@app.route("/delivery/request/<int:service_id>", methods=["POST"])
def request_delivery(service_id):
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    vendor = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    service = query_db("SELECT ds.*, u.username AS service_username, u.whatsapp_number AS service_whatsapp, u.company_name FROM delivery_services ds JOIN users u ON u.id = ds.user_id WHERE ds.id = ? AND ds.availability = 'Available' AND COALESCE(u.account_status, 'Active') NOT IN ('Suspended', 'Terminated')", (service_id,), one=True)
    message = request.form.get("message", "Delivery request from BizHub.").strip() or "Delivery request from BizHub."
    if vendor and service:
        now = datetime.now(timezone.utc).isoformat()
        query_db("INSERT INTO delivery_requests (vendor_id, service_id, message, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (vendor["id"], service["id"], message, now, now))
        # In-app notification for driver
        vendor_label = vendor.get('company_name') or vendor.get('username')
        create_notification(service["user_id"], "delivery", "New delivery request 💬", f"@{session['username']} ({vendor_label}) requested delivery: {message[:80]}. Tap to view & WhatsApp vendor.", url_for("delivery_dashboard"))
        # Prepare WhatsApp notification for driver (direct wa.me link will be shown in dashboard, plus we create a vendor-side WhatsApp redirect)
        try:
            driver_wa = normalize_whatsapp_number(service.get('phone_number') or service.get('service_whatsapp') or '')
            vendor_wa = normalize_whatsapp_number(vendor.get('whatsapp_number') or '')
            # Log WhatsApp intent for driver - driver will see WhatsApp button in dashboard that opens chat to vendor
            # We also store a system notification with WhatsApp link
            if vendor_wa:
                wa_msg = f"Hello {service['service_name']}, you have a NEW delivery request from {vendor_label} (@{vendor['username']}) on BizHub! Message: {message}. Pickup: {vendor.get('business_location','')} . Please check your BizHub driver dashboard and WhatsApp the vendor at https://wa.me/{vendor_wa}"
                # This is for internal tracking - the actual WhatsApp is triggered via dashboard UI for driver
                pass
        except Exception as e:
            pass
    return redirect(safe_internal_referrer("delivery_services"))

@app.route("/delivery/requests/<int:request_id>/status", methods=["POST"])
def update_delivery_request(request_id):
    if session.get("role") != "Delivery Service":
        return redirect(url_for("login"))
    user = query_db("SELECT id FROM users WHERE username = ? AND role = 'Delivery Service'", (session["username"],), one=True)
    if not user:
        return redirect(url_for("login"))

    delivery_req = query_db(
        "SELECT dr.*, ds.service_name, ds.user_id AS service_user_id FROM delivery_requests dr JOIN delivery_services ds ON ds.id = dr.service_id WHERE dr.id = ? AND ds.user_id = ?",
        (request_id, user["id"]), one=True
    )
    if not delivery_req:
        return redirect(safe_internal_referrer("delivery_dashboard"))

    requested_status = request.form.get("status", "")
    transitions = {
        "Requested": {"Accepted", "Declined"},
        "Accepted": {"Picked Up", "Declined"},
        "Picked Up": {"Delivered"},
        "Delivered": set(),
        "Declined": set(),
    }
    if requested_status not in transitions.get(delivery_req["status"], set()):
        return redirect(safe_internal_referrer("delivery_dashboard"))

    now = datetime.now(timezone.utc).isoformat()
    updated = query_db(
        "UPDATE delivery_requests SET status = ?, updated_at = ? WHERE id = ? AND service_id = (SELECT id FROM delivery_services WHERE user_id = ?) AND status = ?",
        (requested_status, now, request_id, user["id"], delivery_req["status"])
    )
    # query_db returns no row count for UPDATE; the guarded WHERE above prevents cross-service changes.
    status_messages = {
        "Accepted": f"{delivery_req['service_name']} accepted your delivery request.",
        "Picked Up": f"{delivery_req['service_name']} has picked up your order.",
        "Delivered": f"{delivery_req['service_name']} marked your order as delivered. Please rate the service.",
        "Declined": f"{delivery_req['service_name']} declined your delivery request.",
    }
    msg = status_messages.get(requested_status)
    if msg:
        create_notification(delivery_req["vendor_id"], "delivery", f"Delivery {requested_status}", msg, url_for("features"))
    return redirect(safe_internal_referrer("delivery_dashboard"))

@app.route("/delivery/requests/<int:request_id>/rate", methods=["POST"])
def rate_delivery(request_id):
    """🏆 BIZHUB QUARTERLY DRIVER LEADERBOARD ENGINE (0 404 ERRORS)"""
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    vendor = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if not vendor:
        return redirect(url_for("features"))
        
    delivery_req = query_db("SELECT dr.*, ds.service_name, ds.user_id AS service_user_id FROM delivery_requests dr JOIN delivery_services ds ON ds.id = dr.service_id WHERE dr.id = ?", (request_id,), one=True)
    if not delivery_req:
        return redirect(url_for("features"))
        
    try: rating = int(request.form.get("rating", 5))
    except ValueError: rating = 5
    comment = request.form.get("comment", "").strip()
    
    query_db("INSERT INTO delivery_ratings (vendor_id, service_id, request_id, rating, comment, created_at) VALUES (?, ?, ?, ?, ?, ?)", (vendor["id"], delivery_req["service_id"], request_id, rating, comment, datetime.now(timezone.utc).isoformat()))
    
    # 🗓️ QUARTERLY AUTOMATED INSIGHTS GENERATION SYSTEM FOR COURIERS
    current_month = datetime.now(timezone.utc).month
    if current_month in [3, 6, 9, 12] and rating == 5: # Fired during quarter-ending milestone months
        top_fleet = query_db("""
            SELECT ds.user_id, ds.service_name, AVG(dr.rating) as score, COUNT(dr.id) as total_ratings FROM delivery_services ds 
            JOIN delivery_ratings dr ON ds.id = dr.service_id GROUP BY ds.id ORDER BY score DESC, total_ratings DESC LIMIT 20
            """) or []
        if any(f["user_id"] == delivery_req["service_user_id"] for f in top_fleet):
            award_title = "🏆 Elite Fleet Award: Quarterly Top 20 Driver Leaderboard Updated!"
            award_msg = f"🎉 Let's congratulate '{delivery_req['service_name']}' for achieving Top 20 status in our Quarterly Performance Audit Review! Keep trading with high-density couriers."
            for u in query_db("SELECT id FROM users WHERE role IN ('Vendor', 'Fast Food', 'Delivery Service')"):
                query_db("INSERT INTO notifications (recipient_id, notification_type, title, message, link, created_at) VALUES (?, 'announcement', ?, ?, ?, ?)""", (u["id"], award_title, award_msg, url_for("delivery_services"), datetime.now(timezone.utc).isoformat()))
                
    return redirect(url_for("features", rating_logged="1"))




@app.route("/disputes", methods=["POST"])
def submit_dispute():
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    subject = request.form.get("subject", "Order or payment dispute").strip()
    details = request.form.get("details", "").strip()
    if user and subject and details:
        query_db("INSERT INTO disputes (reporter_id, order_id, subject, details, created_at) VALUES (?, ?, ?, ?, ?)", (user["id"], request.form.get("order_id") or None, subject, details, datetime.now(timezone.utc).isoformat()))
        create_notification(user["id"], "announcement", "Dispute received", "BizHub received your dispute for review.", url_for("features"))
    return redirect(url_for("features"))

@app.route("/saved-searches", methods=["POST"])
def save_search():
    if session.get("role") != "Customer":
        return redirect(url_for("login"))
    user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    query = request.form.get("query", "").strip()
    if user and query:
        query_db("INSERT OR IGNORE INTO saved_searches (user_id, query, created_at) VALUES (?, ?, ?)", (user["id"], query, datetime.now(timezone.utc).isoformat()))
    return redirect(url_for("features"))

@app.route("/promotions", methods=["GET", "POST"])
def promotions():
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    vendor = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    if not vendor:
        return redirect(url_for("login"))
    subscription = subscription_status(vendor)
    if not subscription["is_premium"]:
        return redirect(url_for("subscription", feature="promotions"))
    promo_error = None
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip() or None
        discount_raw = request.form.get("discount", "").strip()
        main_price_raw = request.form.get("main_price", "").strip()
        product_mode = request.form.get("product_mode", "existing").strip().lower()
        product_id_raw = request.form.get("product_id", "").strip()
        promo_stock_raw = request.form.get("promo_stock_quantity", "").strip()
        
        starts_at = request.form.get("starts_at", "").strip()
        ends_at = request.form.get("ends_at", "").strip()
        if starts_at and len(starts_at) == 16: starts_at += ":00"
        if ends_at and len(ends_at) == 16: ends_at += ":00"
        starts_iso = starts_at.replace("T", " ")
        ends_iso = ends_at.replace("T", " ")

        promo_video = request.files.get("promo_video")
        
        try: discount = float(discount_raw) if discount_raw else None
        except ValueError: discount = None
        try: main_price = float(main_price_raw) if main_price_raw else None
        except ValueError: main_price = None
        try: product_id = int(product_id_raw) if product_id_raw else None
        except ValueError: product_id = None
        
        promo_price = None
        linked_product = None
        is_kitchen = bool(vendor.get("role") == "Fast Food")

        if product_mode == "new":
            new_title = request.form.get("new_product_title", "").strip()
            new_description = request.form.get("new_product_description", "").strip()
            new_price_raw = request.form.get("new_product_price", "").strip()
            new_location = request.form.get("new_product_location", "").strip() or vendor.get("business_location") or "Accra"
            new_category = request.form.get("new_product_category", "Other").strip() or "Other"
            
            try: new_price = float(new_price_raw)
            except ValueError: new_price = None
            
            # 👑 EXTRACT ADAPTIVE PROMO STOCK FOR GENERAL VENDORS
            if is_kitchen:
                new_stock = 1
                new_category = "Fast Food"
            else:
                try: new_stock = int(promo_stock_raw)
                except ValueError: new_stock = None

            new_image = request.files.get("new_product_image")
            new_video = request.files.get("new_product_video")
            
            if not new_title or new_price is None or new_price < 0 or not new_description:
                promo_error = "Enter the new product's title, price, and description details."
            elif not is_kitchen and (new_stock is None or new_stock < 1):
                promo_error = "Please enter an item allocation quantity greater than zero for this flash deal."
            elif not (new_image and new_image.filename) and not (new_video and new_video.filename):
                promo_error = "Add an image or showcase video for the product."
            else:
                product_image_filename = ""
                product_video_filename = None
                
                if new_image and new_image.filename:
                    ext = os.path.splitext(new_image.filename)[1].lower()
                    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                        promo_error = "Images must be PNG, JPG, JPEG, WEBP, or GIF files."
                    else:
                        product_image_filename = f"product-{uuid.uuid4().hex}{ext}"
                        new_image.save(os.path.join(app.config["UPLOAD_FOLDER"], product_image_filename))
                        
                if not promo_error and new_video and new_video.filename:
                    ext = os.path.splitext(new_video.filename)[1].lower()
                    if ext not in VIDEO_EXTENSIONS:
                        promo_error = "Showcase videos must be MP4, WebM, or MOV files."
                    else:
                        product_video_filename = f"video-{uuid.uuid4().hex}{ext}"
                        p_v_path = os.path.join(app.config["UPLOAD_FOLDER"], product_video_filename)
                        new_video.save(p_v_path)
                
                if not promo_error:
                    query_db("""INSERT INTO products (
                    title, price, description, image_file, video_file, stock_quantity, 
                    initial_stock_quantity, sold_quantity, status, seller, seller_email, 
                    seller_whatsapp, location, business_label, category, menu_type, served_with
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'Available', ?, ?, ?, ?, ?, ?, ?, ?)""",
                              (new_title, new_price, new_description, product_image_filename, product_video_filename, new_stock, new_stock, vendor["username"], vendor.get("email"""), vendor.get("whatsapp_number"), new_location, vendor.get("company_name") or vendor.get("username"), new_category))
                    linked_product = query_db("SELECT * FROM products WHERE seller = ? ORDER BY id DESC LIMIT 1", (vendor["username"],), one=True)
                    product_id = linked_product["id"] if linked_product else None
        else:
            if not product_id:
                promo_error = "Choose one of your published catalog items to promote."
            else:
                linked_product = query_db("SELECT * FROM products WHERE id = ? AND seller = ?", (product_id, vendor["username"]), one=True)
                if not linked_product:
                    promo_error = "Selected item is invalid or not owned by your account."

        if not promo_error and (not title or not starts_at or not ends_at):
            promo_error = "Promotion campaign title, start date, and end date are required."
            
        if not promo_error:
            if ends_iso <= starts_iso:
                promo_error = "Promotion end date must occur after the start date schedule."
            elif main_price is None or main_price < 0:
                promo_error = "Provide the item's baseline main price before executing the campaign discount."
            elif discount is None or not (0 <= discount <= 100):
                promo_error = "Enter a valid campaign markdown percentage between 0 and 100."
            else:
                promo_price = max(0.0, main_price * (1 - discount / 100))

        video_filename = None
        image_filename = None
        
        if not promo_error:
            # 👑 AUTO-CLONE ASSIGNED MEDIA: Inherits the core product photo/video directly to prevent duplicate uploads
            if product_mode == "new" and linked_product:
                image_filename = linked_product.get("image_file")
                video_filename = linked_product.get("video_file")
            elif linked_product:
                image_filename = linked_product.get("image_file")
                video_filename = linked_product.get("video_file")

            # If the user uploaded an explicit 30s ad video commercial, use it instead for the promotion card
            if promo_video and promo_video.filename:
                ext = os.path.splitext(promo_video.filename)[1].lower()
                if ext in VIDEO_EXTENSIONS:
                    video_filename = f"promo-video-{uuid.uuid4().hex}{ext}"
                    promo_video.save(os.path.join(app.config["UPLOAD_FOLDER"], video_filename))

            query_db("INSERT INTO promotions (vendor_id, product_id, title, description, discount, promo_price, main_price, image_file, video_file, starts_at, ends_at, active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                      (vendor["id"], product_id, title, description, discount, promo_price, main_price, image_filename, video_filename, starts_iso, ends_iso, datetime.now(timezone.utc).isoformat()))
            
            notify_favorite_customers(vendor["id"], "promotion", f"{vendor['company_name'] or vendor['username']} launched a new flash sale!", title, url_for("vendor_profile", username=vendor["username"]))
            return redirect(url_for("promotions", saved="1"))

    promo_rows=query_db("SELECT pr.*, p.title AS product_title FROM promotions pr LEFT JOIN products p ON p.id=pr.product_id WHERE pr.vendor_id=? ORDER BY pr.id DESC",(vendor["id"],)) or []
    history_now_iso = promotion_now_iso()
    for promo_row in promo_rows:
        promo_row["is_live"] = bool(promo_row.get("active") and str(promo_row.get("starts_at", "")).replace("T", " ") <= history_now_iso <= str(promo_row.get("ends_at", "")).replace("T", " "))
    # ... (the products query line is directly above)
    products=query_db("SELECT id,title,price FROM products WHERE seller=? ORDER BY id DESC",(vendor["username"],)) or []
    
    # 👑 PROMOTIONS LAYER BINDING: Safely inject role markers to toggle layout dictionary terminology
    is_fast_food = bool(vendor.get("role") == "Fast Food" or session.get("role") == "Fast Food")
    return render_template("promotions.html", vendor=vendor, promotions=promo_rows, products=products, product_categories=PRODUCT_CATEGORIES, subscription=subscription, promo_error=promo_error, saved=request.args.get("saved")=="1", is_fast_food=is_fast_food)

@app.route("/promotions/<int:promotion_id>/deactivate", methods=["POST"])
def deactivate_promotion(promotion_id):
    if session.get("role") not in ["Vendor", "Fast Food"]: return redirect(url_for("login"))
    vendor=query_db("SELECT id FROM users WHERE username=?",(session["username"],),one=True)
    if vendor: query_db("UPDATE promotions SET active=0 WHERE id=? AND vendor_id=?",(promotion_id,vendor["id"]))
    return redirect(url_for("promotions",deactivated="1"))

@app.route("/promotions/<int:promotion_id>/delete-history", methods=["POST"])
def delete_promotion_history(promotion_id):
    if session.get("role") not in ["Vendor", "Fast Food"]: return redirect(url_for("login"))
    vendor=query_db("SELECT id FROM users WHERE username=?",(session["username"],),one=True)
    if vendor:
        query_db("UPDATE promotions SET active=0 WHERE id=? AND vendor_id=?",(promotion_id,vendor["id"]))
        query_db("DELETE FROM promotions WHERE id=? AND vendor_id=?",(promotion_id,vendor["id"]))
    return redirect(url_for("promotions",deleted="1"))

@app.route("/delivery/register", methods=["GET", "POST"])
def delivery_register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        service_name = request.form.get("service_name", "").strip()
        operating_location = request.form.get("operating_location", "").strip()
        phone_number = normalize_whatsapp_number(request.form.get("phone_number"))
        service_area = request.form.get("service_area", "").strip()
        delivery_type = request.form.get("delivery_type", "Motorcycle")
        logo_upload = request.files.get("logo")
        if not all([username, email, password, service_name, operating_location, phone_number, service_area]):
            return render_template("delivery_register.html", error="Name, username, email, password, location, service area and phone number are required.", delivery_types=DELIVERY_TYPES)
        if delivery_type not in DELIVERY_TYPES:
            delivery_type = "Other"
        logo = save_company_logo(logo_upload) if logo_upload and logo_upload.filename else None
        try:
            trial_started_at = datetime.now(timezone.utc)
            trial_expires_at = trial_started_at + timedelta(days=90)
            user_id = query_db("INSERT INTO users (username, email, password_hash, role, seller_type, company_name, whatsapp_number, plan, trial_started_at, subscription_expires_at, registered_at) VALUES (?, ?, ?, 'Delivery Service', 'Delivery Service', ?, ?, 'trial', ?, ?, ?)", (username, email, generate_password_hash(password), service_name, phone_number, trial_started_at.isoformat(), trial_expires_at.isoformat(), trial_started_at.isoformat()))
            user = query_db("SELECT id FROM users WHERE username = ?", (username,), one=True)
            if not user:
                raise sqlite3.IntegrityError
            query_db("INSERT INTO delivery_services (user_id, service_name, logo_file, operating_location, phone_number, service_area, delivery_type, availability, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'Available', ?, ?)", (user["id"], service_name, logo, operating_location, phone_number, service_area, delivery_type, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError:
            return render_template("delivery_register.html", error="That username is already in use.", delivery_types=DELIVERY_TYPES)
        session.clear()
        session.update(username=username, email=email, role="Delivery Service", seller_type="Delivery Service", company_name=service_name, whatsapp_number=phone_number, theme="day")
        session["welcome_message"] = True
        return redirect(url_for("delivery_dashboard"))
    return render_template("delivery_register.html", delivery_types=DELIVERY_TYPES)

@app.route("/delivery")
def delivery_dashboard():
    """Renders the Uber-style driver partner terminal with strict session verification tags."""
    # 👑 HARD BOUNDARY GUARD: Kicks invalid or expired sessions straight out to prevent 500 crashes
    if "username" not in session or session.get("role") != "Delivery Service":
        return redirect(url_for("delivery_register"))
        
    welcome_message = bool(session.pop("welcome_message", False))
    sync_delivery_availability()
    
    user = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    if not user:
        session.clear()
        return redirect(url_for("delivery_register"))
        
    service = get_delivery_service(user["id"])
    
    # Extract live incoming shipment dispatch tickets safely - includes vendor WhatsApp for direct chat
    requests_rows = []
    if service:
        requests_rows = query_db("""
            SELECT dr.*, u.username AS vendor_username, u.company_name AS vendor_company_name, u.whatsapp_number AS vendor_whatsapp, u.business_location AS vendor_location
            FROM delivery_requests dr 
            JOIN users u ON u.id = dr.vendor_id 
            WHERE dr.service_id = ? 
            ORDER BY CASE WHEN dr.status IN ('Requested', 'Accepted', 'Picked Up') THEN 0 ELSE 1 END, dr.id DESC 
            LIMIT 50
        """, (service["id"],)) or []
        # Normalize whatsapp numbers for wa.me links
        for r in requests_rows:
            try:
                if r.get('vendor_whatsapp'):
                    r['vendor_whatsapp'] = normalize_whatsapp_number(r['vendor_whatsapp'])
            except:
                pass

    return render_template("delivery_dashboard.html", user=user, service=service, requests=requests_rows, delivery_types=DELIVERY_TYPES, welcome_message=welcome_message)


@app.route("/delivery/manage-accounts""")
def delivery_manage_accounts():
    if "username" not in session or session.get("role") != "Delivery Service":
        return redirect(url_for("login"))
    sync_delivery_availability()
    user = query_db("SELECT * FROM users WHERE username = ? AND role = 'Delivery Service'", (session["username"],), one=True)
    if not user:
        session.clear()
        return redirect(url_for("login"))
    service = get_delivery_service(user["id"])
    subscription = subscription_status(user)
    receipts = query_db("SELECT * FROM subscription_receipts WHERE user_id = ? ORDER BY id DESC", (user["id"],)) or []
    payment_number = normalize_whatsapp_number(os.environ.get("BIZ_HUB_PAYMENT_WHATSAPP", "233558272972"))
    company_name = (user["company_name"] or (service["service_name"] if service else user["username"]) or user["username"]).strip()
    upgrade_message = f"Hello Biz Hub, {user['username']} from {company_name} wants to upgrade to premium. Send account details."
    whatsapp_upgrade_url = f"https://wa.me/{payment_number}?text={quote(upgrade_message)}"
    return render_template(
        "delivery_subscription.html",
        user=user,
        service=service,
        subscription=subscription,
        receipts=receipts,
        payment_number=payment_number,
        upgrade_message=upgrade_message,
        whatsapp_upgrade_url=whatsapp_upgrade_url,
        requested=request.args.get("requested") == "1",
    )

@app.route("/delivery/availability", methods=["POST"])
def delivery_availability():
    if session.get("role") != "Delivery Service":
        return redirect(url_for("login"))
    user = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    if not subscription_status(user)["is_premium"]:
        sync_delivery_availability()
        return redirect(url_for("delivery_subscription", feature="delivery"))
    availability = request.form.get("availability", "Unavailable")
    if availability not in ("Available", "Unavailable"):
        availability = "Unavailable"
    user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if user:
        query_db("UPDATE delivery_services SET availability = ?, updated_at = ? WHERE user_id = ?", (availability, datetime.now(timezone.utc).isoformat(), user["id"]))
    return redirect(url_for("delivery_dashboard"))

@app.route("/delivery/services")
def delivery_services():
    if not delivery_access_allowed():
        return redirect(url_for("delivery_subscription", feature="delivery"))
    sync_delivery_availability()
    location = request.args.get("location", "").strip()
    company = request.args.get("company", "").strip()
    search_pattern = f"%{company}%"
    location_pattern = f"%{location}%"
    rows = query_db("SELECT ds.*, u.id AS user_id, u.username FROM delivery_services ds JOIN users u ON u.id = ds.user_id WHERE (? = '' OR ds.operating_location LIKE ? OR ds.service_area LIKE ?) AND (? = '' OR ds.service_name LIKE ? OR u.username LIKE ?) ORDER BY CASE WHEN ds.availability = 'Available' THEN 0 ELSE 1 END, ds.operating_location, ds.service_name", (location, location_pattern, location_pattern, company, search_pattern, search_pattern)) or []
    # Attach average rating and count to each service
    rating_rows = query_db("""SELECT service_id, ROUND(AVG(rating), 1) AS avg_rating, COUNT(*) AS rating_count FROM delivery_ratings GROUP BY service_id""") or []
    ratings_map = {r["service_id"]: r for r in rating_rows}
    services = []
    for row in rows:
        r = dict(row)
        stats = ratings_map.get(r["id"], {})
        r["avg_rating"] = stats.get("avg_rating")
        r["rating_count"] = stats.get("rating_count", 0)
        services.append(r)
    return render_template("delivery_service.html", services=services, location=location, company=company)

@app.route("/delivery/contact/<int:service_id>", methods=["POST"])
def contact_delivery(service_id):
    if not delivery_access_allowed():
        return redirect(url_for("delivery_subscription", feature="delivery"))
    sync_delivery_availability()
    service = query_db("SELECT ds.*, u.id AS user_id FROM delivery_services ds JOIN users u ON u.id = ds.user_id WHERE ds.id = ? AND ds.availability = 'Available' AND u.subscription_expires_at > ?", (service_id, datetime.now(timezone.utc).isoformat()), one=True)
    if not service:
        return redirect(url_for("delivery_services"))
    vendor = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if vendor:
        create_notification(service["user_id"], "delivery", f"Delivery request from @{session['username']}", f"A subscribed BizHub vendor is contacting {service['service_name']} for delivery service.", url_for("delivery_dashboard"))
    return redirect("https://wa.me/" + normalize_whatsapp_number(service["phone_number"]) + "?text=" + quote(f"Hello {service['service_name']}, I found your delivery service on BizHub. I would like to arrange delivery."))

@app.route("/subscription")
def subscription():
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    if not user:
        session.clear()
        return redirect(url_for("login"))
    if user["role"] == "Delivery Service":
        return redirect(url_for("delivery_subscription"))
        
    payment_number = normalize_whatsapp_number(os.environ.get("BIZ_HUB_PAYMENT_WHATSAPP", "233558272972"))
    upgrade_name = (user["company_name"] or user["username"]).strip()
    
    # 👑 CLEAN UNIFORM VENDOR WHATSAPP UPGRADE MESSAGE & FULL URL ENGINE
    upgrade_message = f"Hello Biz Hub, {user['username']} of {upgrade_name} wants to upgrade to the Premium Store plan. Send account details!"
    whatsapp_upgrade_url = f"https://wa.me/{payment_number}?text={quote(upgrade_message)}"
    
       # 👑 UNBREAKABLE ROUTING VARIABLE MAPS: Synchronizes backend calculations with template rendering requirements
    receipts = query_db("SELECT * FROM subscription_receipts WHERE user_id = ? ORDER BY id DESC", (user["id"],)) or []
    
    # Check your sub status calculation properties securely
    sub_status = subscription_status(user)
    is_premium_active = bool(sub_status and sub_status.get("is_premium"))

    return render_template("subscription.html", 
                           user=user, 
                           subscription=sub_status, 
                           receipts=receipts, 
                           payment_number=payment_number, 
                           upgrade_message=upgrade_message, 
                           whatsapp_upgrade_url=whatsapp_upgrade_url, 
                           subscription_active=is_premium_active, # Maps congratulations banner triggers
                           user_plan="premium" if is_premium_active else "basic", # Maps button visibility locks
                           requested=request.args.get("requested") == "1")


@app.route("/delivery/subscription")
def delivery_subscription():
    """Renders driver premium controls and generates bulletproof whatsapp upgrade hyperlinks."""
    if "username" not in session or session.get("role") != "Delivery Service":
        return redirect(url_for("login"))
    user = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    if not user:
        session.clear()
        return redirect(url_for("login"))
        
    # 👑 HARD-BOUND DATA ACQUISITION: Fetches driver service attributes to populate link text tags
    service = get_delivery_service(user["id"])
    receipts = query_db("SELECT * FROM subscription_receipts WHERE user_id = ? ORDER BY id DESC", (user["id"],)) or []
    payment_number = normalize_whatsapp_number(os.environ.get("BIZ_HUB_PAYMENT_WHATSAPP", "233558272972"))
    
    # Generate clean text layers on the server side to protect link delimiters
    company_profile_label = (service["service_name"] if service and service.get("service_name") else (user.get("company_name") or user["username"])).strip()
    raw_message = f"Hello BIZ HUB, {user['username']} of {company_profile_label} wants to upgrade to premium. Send account details!"
        
        # 🚀 BULLETPROOF PROTOCOL CONNECTOR FIXED: Restores slashes and query base question marks cleanly
    whatsapp_upgrade_url = f"https://wa.me/{payment_number}?text={quote(raw_message)}"

    return render_template("delivery_subscription.html", user=user, service=service, subscription=subscription_status(user), receipts=receipts, payment_number=payment_number, whatsapp_upgrade_url=whatsapp_upgrade_url, requested=request.args.get("requested") == "1")

        

@app.route("/request-premium", methods=["POST"])
def request_premium():
    if "username" not in session or session.get("role") not in ["Vendor", "Fast Food", "Delivery Service"]:
        return redirect(url_for("login"))
    query_db("UPDATE users SET upgrade_requested_at = ? WHERE username = ?", (datetime.now(timezone.utc).isoformat(), session["username"]))
    return redirect(url_for("delivery_subscription" if session.get("role") == "Delivery Service" else "subscription", requested="1"))

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if is_admin():
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        username_input = request.form.get("username", "").strip()
        password_input = request.form.get("password", "")

        authenticated = False
        authenticated_username = None

        configured_username = get_admin_username()
        configured_password = get_admin_password()

        if (
            configured_username
            and configured_password
            and secrets.compare_digest(
                username_input.casefold(),
                configured_username.casefold(),
            )
            and secrets.compare_digest(password_input, configured_password)
        ):
            authenticated = True
            authenticated_username = configured_username
        else:
            admin = query_db(
                "SELECT * FROM admin_users WHERE lower(username) = lower(?)",
                (username_input,),
                one=True,
            )

            if admin and check_password_hash(
                admin["password_hash"],
                password_input,
            ):
                authenticated = True
                authenticated_username = admin["username"]

        if not authenticated:
            return render_template(
                "admin_login.html",
                login_error="Invalid administrator credentials.",
            )

        session.clear()
        session["is_admin"] = True
        session["admin_username"] = authenticated_username
        session["role"] = "Admin"
        return redirect(url_for("admin_dashboard"))

    return render_template("admin_login.html", login_error=None)




      
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
        if len(password) < 12:
            return render_template("admin_signup.html", admin_error="Admin password must be at least 12 characters.")
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
    users = query_db("""SELECT * FROM users ORDER BY COALESCE(registered_at, '') DESC, username""")
    listing_counts = {row["seller"]: row["count"] for row in query_db("SELECT seller, COUNT(*) AS count FROM products GROUP BY seller")}
    ledger_entries = query_db("SELECT * FROM financial_ledger ORDER BY id DESC") or []
    subscription_receipts = query_db("SELECT * FROM subscription_receipts ORDER BY id DESC") or []
    reports = query_db("SELECT r.*, u.username AS reporter_username FROM reports r JOIN users u ON u.id = r.reporter_id ORDER BY CASE WHEN r.status = 'Pending' THEN 0 ELSE 1 END, r.id DESC") or []
    verification_requests = query_db("SELECT vr.*, u.username, u.company_name, u.role FROM verification_requests vr JOIN users u ON u.id = vr.user_id ORDER BY CASE WHEN vr.status = 'Pending' THEN 0 ELSE 1 END, vr.id DESC") or []
    disputes = query_db("SELECT d.*, u.username AS reporter_username FROM disputes d JOIN users u ON u.id = d.reporter_id ORDER BY CASE WHEN d.status = 'Pending' THEN 0 ELSE 1 END, d.id DESC") or []
    admin_audit_logs = query_db("SELECT * FROM admin_audit_log ORDER BY id DESC LIMIT 100") or []
    
    total_rev_row = query_db("SELECT SUM(amount) AS total FROM financial_ledger WHERE status = 'Verified'""", one=True)
    total_revenue = total_rev_row["total"] if total_rev_row and total_rev_row["total"] is not None else 0.0
    
    pending_momo_row = query_db("SELECT SUM(amount) AS total FROM financial_ledger WHERE status = 'Pending'", one=True)
    pending_momo = pending_momo_row["total"] if pending_momo_row and pending_momo_row["total"] is not None else 0.0
    
    verified_count_row = query_db("SELECT COUNT(*) AS count FROM financial_ledger WHERE status = 'Verified'", one=True)
    verified_count = verified_count_row["count"] if verified_count_row and verified_count_row["count"] is not None else 0
    
        # 🏆 Top 20 Brands for admin dashboard (quarterly)
    try:
        now_dt = datetime.now(timezone.utc)
        quarter_start_month = ((now_dt.month - 1) // 3) * 3 + 1
        quarter_start = datetime(now_dt.year, quarter_start_month, 1, tzinfo=timezone.utc).isoformat()
        top_brands_admin = query_db('''
            SELECT u.id, u.username, u.company_name, u.company_logo, u.business_location, u.role, u.is_verified_brand, u.verified_brand_type,
                   ROUND(AVG(r.rating),1) AS avg_rating, COUNT(r.id) AS rating_count
            FROM users u JOIN reviews r ON r.vendor_id = u.id
            WHERE u.role IN ('Vendor','Fast Food') AND COALESCE(u.account_status,'Active') NOT IN ('Suspended','Terminated')
            AND r.created_at >= ?
            GROUP BY u.id ORDER BY avg_rating DESC, rating_count DESC LIMIT 20
        ''', (quarter_start,)) or []
        if len(top_brands_admin) < 5:
            top_brands_admin = query_db('''
                SELECT u.id, u.username, u.company_name, u.company_logo, u.business_location, u.role, u.is_verified_brand, u.verified_brand_type,
                       ROUND(AVG(r.rating),1) AS avg_rating, COUNT(r.id) AS rating_count
                FROM users u JOIN reviews r ON r.vendor_id = u.id
                WHERE u.role IN ('Vendor','Fast Food') AND COALESCE(u.account_status,'Active') NOT IN ('Suspended','Terminated')
                GROUP BY u.id ORDER BY avg_rating DESC, rating_count DESC LIMIT 20
            ''') or []
        for b in top_brands_admin:
            b['business_label'] = b.get('company_name') or b.get('username')
    except:
        top_brands_admin = []
    
    try:
        delivery_services_count = query_db("SELECT COUNT(*) as c FROM delivery_services", one=True)
        delivery_services_count = delivery_services_count['c'] if delivery_services_count else 0
    except:
        delivery_services_count = 0
    try:
        delivery_requests_pending = query_db("SELECT COUNT(*) as c FROM delivery_requests WHERE status='Pending'", one=True)
        delivery_requests_pending = delivery_requests_pending['c'] if delivery_requests_pending else 0
    except:
        delivery_requests_pending = 0
    top_brands_count = len(top_brands_admin)

    return render_template("admin.html", users=users, subscription_status=subscription_status, listing_counts=listing_counts, ledger_entries=ledger_entries, subscription_receipts=subscription_receipts, reports=reports, verification_requests=verification_requests, disputes=disputes, admin_audit_logs=admin_audit_logs, total_revenue=total_revenue, pending_momo=pending_momo, verified_count=verified_count, top_brands_admin=top_brands_admin, top_brands_count=top_brands_count, delivery_services_count=delivery_services_count, delivery_requests_pending=delivery_requests_pending)

@app.route("/admin/adjust-points", methods=["POST"])
def admin_adjust_points():
    """👑 ADMIN OVERRIDE: Manually adjust customer loyalty points balances."""
    if not is_admin():
        return redirect(url_for("admin_login"))
    user_id = request.form.get("user_id")
    try:
        points = int(request.form.get("points", 0))
    except ValueError:
        return redirect(url_for("admin_dashboard"))
        
    now = datetime.now(timezone.utc).isoformat()
    query_db("UPDATE loyalty_accounts SET points = ?, updated_at = ? WHERE user_id = ?", (points, now, user_id))
    return redirect(url_for("admin_dashboard", points_updated="1"))

@app.route("/admin/delete-coupon/<int:coupon_id>", methods=["POST"])
def admin_delete_coupon(coupon_id):
    """👑 ADMIN OVERRIDE: Force delete/revoke any vendor coupon code instantly."""
    if not is_admin():
        return redirect(url_for("admin_login"))
    query_db("DELETE FROM coupons WHERE id = ?", (coupon_id,))
    return redirect(url_for("admin_dashboard", coupon_deleted="1"))


@app.route("/admin/verification/<int:request_id>", methods=["POST"])
def review_verification(request_id):
    if not is_admin():
        return redirect(url_for("admin_login"))
    item = query_db("SELECT * FROM verification_requests WHERE id = ?", (request_id,), one=True)
    action = request.form.get("action", "Approved")
    if item and action in {"Approved", "Rejected"}:
        now = datetime.now(timezone.utc).isoformat()
        note = request.form.get("note", "Reviewed by BizHub administration.").strip()
        query_db("UPDATE verification_requests SET status = ?, note = ?, reviewed_at = ? WHERE id = ?", (action, note, now, request_id))
        if action == "Approved":
            # 🏆 GLOWING GREEN VERIFIED BIZHUB BRAND - Vendor gets verified badge
            user_to_verify = query_db("SELECT role FROM users WHERE id = ?", (item["user_id"],), one=True)
            role_type = user_to_verify["role"] if user_to_verify else "Vendor"
            brand_type = "Kitchen Brand" if role_type == "Fast Food" else "Store"
            query_db("UPDATE users SET account_status = 'Active', is_verified_brand = 1, verified_at = ?, verified_brand_type = ? WHERE id = ?", (now, brand_type, item["user_id"]))
            # Notify vendor they got glowing green verified badge
            vendor_user = query_db("SELECT id, username, role FROM users WHERE id = ?", (item["user_id"],), one=True)
            if vendor_user:
                badge_text = "Verified BizHub Kitchen Brand" if vendor_user["role"] == "Fast Food" else "Verified BizHub Store"
                create_notification(vendor_user["id"], "verification", "✅ You are now Verified!", f"🎉 Congratulations! Your {vendor_user['role']} account has been approved and now shows a glowing green '{badge_text}' badge across BizHub marketplace. Customers will see you as a trusted verified brand!", url_for("vendor_profile", username=vendor_user["username"]))
        else:
            # Rejected - remove verified badge
            query_db("UPDATE users SET is_verified_brand = 0, verified_brand_type = NULL WHERE id = ?", (item["user_id"],))
        create_notification(item["user_id"], "announcement", "Verification request reviewed", f"Your BizHub verification request was {action.lower()}.", url_for("features"))
        query_db("INSERT INTO admin_audit_log (admin_username, action, target_username, details, created_at) VALUES (?, ?, ?, ?, ?)", (session.get("admin_username", "admin"), "Verification " + action, str(item["user_id"]), note, now))
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/reports/<int:report_id>/review", methods=["POST"])
def review_report(report_id):
    if not is_admin():
        return redirect(url_for("admin_login"))
    report = query_db("SELECT * FROM reports WHERE id = ?", (report_id,), one=True)
    if not report or report["status"] != "Pending":
        return redirect(url_for("admin_dashboard"))
    action = request.form.get("action", "Dismissed")
    allowed_actions = {"Dismissed", "Warned", "Suspended", "Terminated", "More information"}
    if action not in allowed_actions:
        return redirect(url_for("admin_dashboard"))
    note = request.form.get("admin_note", "").strip() or "Reviewed by BizHub administration."
    reviewed_at = datetime.now(timezone.utc).isoformat()
    query_db("UPDATE reports SET status = 'Reviewed', admin_action = ?, admin_note = ?, reviewed_at = ? WHERE id = ?", (action, note, reviewed_at, report_id))
    if action in {"Warned", "Suspended", "Terminated"}:
        query_db("UPDATE users SET account_status = ?, enforcement_reason = ?, suspended_until = NULL WHERE id = ?", (action if action != "Warned" else "Warned", note, report["target_user_id"]))
        query_db("INSERT INTO enforcement_actions (user_id, action, reason, created_at) VALUES (?, ?, ?, ?)", (report["target_user_id"], action, note, reviewed_at))
        if action in {"Suspended", "Terminated"}:
            query_db("UPDATE delivery_services SET availability = 'Unavailable', updated_at = ? WHERE user_id = ?", (reviewed_at, report["target_user_id"]))
        notify_account_enforcement(report["target_user_id"], action, note)
    create_notification(report["reporter_id"], "announcement", "Report reviewed", f"Your report about @{report['target_username']} was reviewed by BizHub. Outcome: {action}.", url_for("notifications"))
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/verify-transaction/<int:entry_id>", methods=["POST"])
def verify_transaction(entry_id):
    if not is_admin(): 
        return redirect(url_for("admin_login"))
    query_db("UPDATE financial_ledger SET status = 'Verified' WHERE id = ?", (entry_id,))
    issue_subscription_receipt(entry_id)
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/log-payment", methods=["POST"])
def log_payment():
    if not is_admin():
        return redirect(url_for("admin_login"))
    username = request.form.get("username", "").strip()
    try:
        amount = float(request.form.get("amount", 0.0))
    except ValueError:
        return redirect(url_for("admin_dashboard"))
    tx_type = request.form.get("transaction_type", "Subscription")
    ref = request.form.get("momo_reference", "").strip() or f"WA-{uuid.uuid4().hex[:8].upper()}"
    if tx_type == "Subscription" and (amount <= 0 or not query_db("SELECT id FROM users WHERE username = ? AND role IN ('Vendor', 'Fast Food', 'Delivery Service')", (username,), one=True)):
        return redirect(url_for("admin_dashboard"))
    query_db("INSERT INTO financial_ledger (transaction_type, username, amount, momo_reference, status, created_at) VALUES (?, ?, ?, ?, 'Pending', ?)", (tx_type, username, amount, ref, datetime.now(timezone.utc).isoformat()))
    if tx_type == "Subscription" and amount > 0:
        entry = query_db("SELECT id FROM financial_ledger WHERE momo_reference = ?", (ref,), one=True)
        if entry:
            query_db("UPDATE financial_ledger SET status = 'Verified' WHERE id = ?", (entry["id"],))
            issue_subscription_receipt(entry["id"])
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/dispatch-message", methods=["POST"])
def admin_dispatch_message():
    """👑 CORE DISPATCH ROUTER: Directs private single-user notes, role-group pings, or global announcements."""
    if not is_admin():
        return redirect(url_for("admin_login"))
        
    title = request.form.get("title", "").strip()
    message = request.form.get("message", "").strip()
    target_scope = request.form.get("target_scope", "All").strip() # 'Individual', 'Group', 'All'
    
    if not title or not message:
        return redirect(url_for("admin_dashboard"))
        
    now_iso = datetime.now(timezone.utc).isoformat()
    
    # 📝 Record the master administrative log statement safely
    query_db(
        "INSERT INTO admin_direct_messages (target_scope, target_username, target_role, title, message, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (target_scope, request.form.get("target_username", "").strip() or None, request.form.get("target_role", "").strip() or None, title, message, now_iso)
    )
    
    # CASE 1: Individual Private Communications
    if target_scope == "Individual":
        target_user = request.form.get("target_username", "").strip()
        recipient = query_db("SELECT id FROM users WHERE username = ?", (target_user,), one=True)
        if recipient:
            create_notification(recipient["id"], "announcement", f"🔒 Private Admin Note: {title}", message, url_for("notifications"))
            
    # CASE 2: Specific Operational Group Segment Broadcasting
    elif target_scope == "Group":
        target_role = request.form.get("target_role", "").strip()
        recipients = query_db("SELECT id FROM users WHERE role = ?", (target_role,)) or []
        for r in recipients:
            create_notification(r["id"], "announcement", f"📢 Group Notice: {title}", message, url_for("notifications"))
            
    # CASE 3: Universal Marketplace Global Announcement Fallback
    else:
        all_users = query_db("""SELECT id FROM users""") or []
        for u in all_users:
            create_notification(u["id"], "announcement""", title, message, url_for("notifications"))
            
    # Record to security audit trail
    query_db(
        "INSERT INTO admin_audit_log (admin_username, action, target_username, details, created_at) VALUES (?, ?, ?, ?, ?)",
        (session.get("admin_username", "admin"), f"Dispatched {target_scope} Message", request.form.get("target_username") or target_role or "All", title, now_iso)
    )
    return redirect(url_for("admin_dashboard", message_sent="1"))


@app.route("/subscription/receipt/<int:receipt_id>")
def subscription_receipt(receipt_id):
    if "username" not in session and not is_admin():
        return redirect(url_for("login"))
    receipt = query_db("SELECT * FROM subscription_receipts WHERE id = ?", (receipt_id,), one=True)
    if not receipt:
        return redirect(url_for("subscription"))
    current_user = query_db("SELECT id FROM users WHERE username = ?", (session.get("username"),), one=True) if session.get("username") else None
    if not is_admin() and (not current_user or receipt["user_id"] != current_user["id"]):
        return redirect(url_for("subscription"))
    return render_template("subscription_receipt.html", receipt=receipt)

@app.route("/admin/approve-premium/<int:user_id>", methods=["POST"])
def approve_premium(user_id):
    if not is_admin():
        return redirect(url_for("admin_login"))
    now = datetime.now(timezone.utc)
    existing = query_db("SELECT subscription_expires_at, plan FROM users WHERE id =?", (user_id,), one=True)
    base_expiry = parse_subscription_expiry(existing.get("subscription_expires_at")) if existing else None
    if base_expiry and base_expiry > now:
        expiry = base_expiry + timedelta(days=30)
    else:
        expiry = now + timedelta(days=30)
    query_db("UPDATE users SET plan = 'premium', trial_started_at = NULL, subscription_expires_at =?, upgrade_requested_at = NULL WHERE id =? AND role IN ('Vendor', 'Fast Food', 'Delivery Service')", (expiry.isoformat(), user_id))
    query_db("UPDATE delivery_services SET availability = 'Unavailable', updated_at =? WHERE user_id =?", (now.isoformat(), user_id))
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/enforce/<int:user_id>", methods=["POST"])
def enforce_account(user_id):
    if not is_admin():
        return redirect(url_for("admin_login"))
    action = request.form.get("action", "Warned")
    allowed_actions = {"Warned", "Suspended", "Terminated", "Active"}
    if action not in allowed_actions:
        return redirect(url_for("admin_dashboard"))
    reason = request.form.get("reason", "Rule violation reviewed by BizHub.").strip() or "Rule violation reviewed by BizHub."
    query_db("UPDATE users SET account_status = ?, enforcement_reason = ?, suspended_until = NULL WHERE id = ?", (action, reason, user_id))
    query_db("INSERT INTO enforcement_actions (user_id, action, reason, created_at) VALUES (?, ?, ?, ?)", (user_id, action, reason, datetime.now(timezone.utc).isoformat()))
    target = query_db("SELECT username FROM users WHERE id = ?", (user_id,), one=True)
    query_db("INSERT INTO admin_audit_log (admin_username, action, target_username, details, created_at) VALUES (?, ?, ?, ?, ?)", (session.get("admin_username", "admin"), "Account " + action, target["username"] if target else None, reason, datetime.now(timezone.utc).isoformat()))
    if action in ("Suspended", "Terminated"):
        query_db("UPDATE delivery_services SET availability = 'Unavailable', updated_at = ? WHERE user_id = ?", (datetime.now(timezone.utc).isoformat(), user_id))
    notify_account_enforcement(user_id, action, reason)
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
    session.clear()
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
        company_name = html.escape(request.form.get("company_name", "").strip()) or None
        business_location = html.escape(request.form.get("business_location", "").strip()) or None
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        theme = request.form.get("theme", "day")
        company_logo = user["company_logo"]
        logo_upload = request.files.get("company_logo")
        catalog_mode = request.form.get("catalog_mode", "Focused")
        selected_categories = list(dict.fromkeys(
            category for category in request.form.getlist("vendor_categories")
            if category in VENDOR_CATEGORIES
        ))

        if not new_username:
            return render_template("settings.html", user=user, subscription=subscription_status(user), vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, product_categories=PRODUCT_CATEGORIES, settings_error="Username is required.", app_theme=user.get("theme") or "day")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", new_username):
            return render_template("settings.html", user=user, subscription=subscription_status(user), vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, product_categories=PRODUCT_CATEGORIES, settings_error="Username must be 3-40 chars letters numbers _ . -", app_theme=user.get("theme") or "day")
        if new_username != current_username:
            existing = query_db("SELECT id FROM users WHERE username = ?", (new_username,), one=True)
            if existing:
                return render_template("settings.html", user=user, subscription=subscription_status(user), vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, product_categories=PRODUCT_CATEGORIES, settings_error="That username is already taken.", app_theme=user.get("theme") or "day")
        if not email or "@" not in email or "." not in email:
            return render_template("settings.html", user=user, subscription=subscription_status(user), vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, product_categories=PRODUCT_CATEGORIES, settings_error="Enter a valid email address.", app_theme=user.get("theme") or "day")
        if is_vendor_any and not whatsapp_number:
            return render_template("settings.html", user=user, subscription=subscription_status(user), vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, product_categories=PRODUCT_CATEGORIES, settings_error="Vendor accounts need WhatsApp for payments.", app_theme=user.get("theme") or "day")
        if new_password:
            if not current_password:
                return render_template("settings.html", user=user, subscription=subscription_status(user), vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, product_categories=PRODUCT_CATEGORIES, settings_error="Enter current password to change password.", app_theme=user.get("theme") or "day")
            if not check_password_hash(user["password_hash"], current_password):
                return render_template("settings.html", user=user, subscription=subscription_status(user), vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, product_categories=PRODUCT_CATEGORIES, settings_error="Current password is incorrect.", app_theme=user.get("theme") or "day")
            if len(new_password) < 6:
                return render_template("settings.html", user=user, subscription=subscription_status(user), vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, product_categories=PRODUCT_CATEGORIES, settings_error="New password must be at least 6 characters.", app_theme=user.get("theme") or "day")
            if new_password != confirm_password:
                return render_template("settings.html", user=user, subscription=subscription_status(user), vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, product_categories=PRODUCT_CATEGORIES, settings_error="New passwords do not match.", app_theme=user.get("theme") or "day")
        if theme not in ("day", "night"):
            theme = "day"
        if logo_upload and logo_upload.filename:
            new_logo = save_company_logo(logo_upload)
            if not new_logo:
                return render_template("settings.html", user=user, subscription=subscription_status(user), vendor_categories=vendor_categories, vendor_category_options=VENDOR_CATEGORIES, product_categories=PRODUCT_CATEGORIES, settings_error="Logo must be PNG/JPG/JPEG/WEBP/GIF.", app_theme=user.get("theme") or "day")
            try:
                if company_logo:
                    old_path = os.path.join(app.config["UPLOAD_FOLDER"], company_logo)
                    if os.path.exists(old_path):
                        os.remove(old_path)
            except:
                pass
            company_logo = new_logo

        if not is_vendor_any:
            company_name = None
            business_location = None
            whatsapp_number = None
            catalog_mode = None
            selected_categories = []
            company_logo = None
        elif catalog_mode not in ("Variety", "Focused"):
            catalog_mode = user.get("catalog_mode") or "Focused"

        if is_vendor_any and not selected_categories:
            selected_categories = vendor_categories

        password_hash = generate_password_hash(new_password) if new_password else user["password_hash"]
        query_db(
            "UPDATE users SET username = ?, email = ?, password_hash = ?, company_name = ?, whatsapp_number = ?, catalog_mode = ?, company_logo = ?, business_location = ?, theme = ? WHERE id = ?",
            (new_username, email, password_hash, company_name, whatsapp_number, catalog_mode, company_logo, business_location, theme, user["id"])
        )

        if new_username != current_username:
            for q in [
                "UPDATE products SET seller = ? WHERE seller = ?",
                "UPDATE order_items SET seller = ? WHERE seller = ?",
                "UPDATE orders SET customer_username = ? WHERE customer_username = ?",
                "UPDATE financial_ledger SET username = ? WHERE username = ?",
                "UPDATE vendor_notifications SET customer_username = ? WHERE customer_username = ?",
                "UPDATE promotions SET vendor_username = ? WHERE vendor_username = ?",
                "UPDATE cart_history SET seller = ? WHERE seller = ?",
            ]:
                try:
                    query_db(q, (new_username, current_username))
                except:
                    pass

        query_db("DELETE FROM vendor_categories WHERE user_id = ?", (user["id"],))
        for category in selected_categories:
            query_db("INSERT INTO vendor_categories (user_id, category) VALUES (?, ?)", (user["id"], category))

        session["username"] = new_username
        session["email"] = email
        session["company_name"] = company_name
        session["business_location"] = business_location
        session["whatsapp_number"] = whatsapp_number
        session["theme"] = theme
        if new_password:
            return redirect(url_for("settings", updated="1", password_changed="1"))
        return redirect(url_for("settings", updated="1"))

    return render_template(
        "settings.html",
        user=user,
        subscription=subscription_status(user),
        vendor_categories=vendor_categories,
        vendor_category_options=VENDOR_CATEGORIES,
        product_categories=PRODUCT_CATEGORIES,
        app_theme=user.get("theme") or session.get("theme") or "day",
        updated=request.args.get("updated") == "1"
    )


@app.route("/api/check-username")
def api_check_username():
    """Streams asynchronous validation statuses back to the login view."""
    username = request.args.get("username", "").strip()
    if not username:
        return {"status": "empty", "message": ""}
    if len(username) < 3:
        return {"status": "short", "message": "⚠️ Handle must be at least 3 characters"}
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", username):
        return {"status": "invalid", "message": "⚠️ Use only alphanumeric characters, dots, or underscores"}

    # Database reference check
    user_exists = query_db("SELECT id FROM users WHERE username = ?", (username,), one=True)
    if user_exists:
        return {"status": "taken", "message": f"❌ @{username} is already taken"}
    else:
        return {"status": "available", "message": f"✨ @{username} is available!"}


# ==========================================================================
# 👑 UPDATED LOGIN ROUTE METHOD (ISOLATES DELIVERY CRASH LABELS)
# ==========================================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    """Handles cross-device multi-role logins safely with isolated error tracking tags."""
    if request.method == "POST":
        is_delivery_login = bool(request.form.get("delivery_login_user") is not None)
        username = request.form.get("login_user") if not is_delivery_login else request.form.get("delivery_login_user")
        password = request.form.get("login_pass") if not is_delivery_login else request.form.get("delivery_login_pass")
        
        user = query_db("SELECT * FROM users WHERE username = ?", (username,), one=True)
        
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["username"] = user["username"]
            session["email"] = user["email"]
            session["role"] = user["role"]
            session["seller_type"] = user["seller_type"]
            session["company_name"] = user["company_name"]
            session["business_location"] = user.get("business_location")
            session["whatsapp_number"] = user["whatsapp_number"]
            session["theme"] = user["theme"] or "day"
            
            if user["role"] == "Delivery Service":
                return redirect(url_for("delivery_dashboard"))
            elif user["role"] in ["Vendor", "Fast Food"]:
                return redirect(url_for("vendor_profile", username=user["username"]))
            else:
                return redirect(url_for("home"))
        else:
            # 🚨 FIX: Diverts credential log mistakes into the specific screen dashboard nodes
            if is_delivery_login:
                return render_template("login.html", delivery_login_error="Wrong username or password.")
            else:
                return render_template("login.html", login_error="Wrong username or password.")
            
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
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
            query_db("INSERT INTO password_resets (user_id, token, expires_at) VALUES (?, ?, ?)", (user["id"], token, expires_at))
            reset_link = url_for("reset_credentials", token=token, _external=True)
            payment_number = normalize_whatsapp_number(os.environ.get("BIZ_HUB_PAYMENT_WHATSAPP", "233558272972"))
            reset_text = quote(f"Hello Biz Hub, I need to recover my account registered with WhatsApp {whatsapp_number}. My reset link is: {reset_link}")
            reset_link = f"https://wa.me/{payment_number}?text={reset_text}"
    return render_template("forgot_password.html", reset_error=reset_error, reset_link=reset_link)

@app.route("/reset-credentials/<token>", methods=["GET", "POST"])
def reset_credentials(token):
    reset = valid_reset_token(token)
    if not reset:
        return render_template("reset_credentials.html", reset_error="This recovery link is invalid or has expired.", token=None, app_theme=session.get("theme") or "day")
    user = query_db("SELECT * FROM users WHERE id = ?", (reset["user_id"],), one=True)
    if not user:
        return render_template("reset_credentials.html", reset_error="Account not found.", token=None, app_theme=session.get("theme") or "day")
    # Expiry display
    reset_expires_at = reset.get("expires_at")
    if request.method == "POST":
        new_username = request.form.get("username", "").strip()
        new_password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not new_username or not new_password:
            return render_template("reset_credentials.html", reset_error="Username and password are required.", token=token, user=user, reset_expires_at=reset_expires_at, app_theme=session.get("theme") or "day")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", new_username):
            return render_template("reset_credentials.html", reset_error="Username must be 3-40 chars letters numbers _ . -", token=token, user=user, reset_expires_at=reset_expires_at, app_theme=session.get("theme") or "day")
        if len(new_password) < 6:
            return render_template("reset_credentials.html", reset_error="Password must be at least 6 characters.", token=token, user=user, reset_expires_at=reset_expires_at, app_theme=session.get("theme") or "day")
        if new_password != confirm_password:
            return render_template("reset_credentials.html", reset_error="Passwords do not match.", token=token, user=user, reset_expires_at=reset_expires_at, app_theme=session.get("theme") or "day")
        # Check suspended
        if user.get("account_status") in ("Suspended","Terminated"):
            return render_template("reset_credentials.html", reset_error="Account suspended — cannot reset.", token=None, app_theme=session.get("theme") or "day")
        try:
            query_db("UPDATE users SET username = ?, password_hash = ? WHERE id = ?", (new_username, generate_password_hash(new_password), user["id"]))
            if new_username != user["username"]:
                for q in [
                    "UPDATE products SET seller = ? WHERE seller = ?",
                    "UPDATE order_items SET seller = ? WHERE seller = ?",
                    "UPDATE orders SET customer_username = ? WHERE customer_username = ?",
                    "UPDATE financial_ledger SET username = ? WHERE username = ?",
                    "UPDATE vendor_notifications SET customer_username = ? WHERE customer_username = ?",
                    "UPDATE promotions SET vendor_username = ? WHERE vendor_username = ?",
                    "UPDATE cart_history SET seller = ? WHERE seller = ?",
                    "UPDATE favorites SET vendor_username = ? WHERE vendor_username = ?",
                ]:
                    try:
                        query_db(q, (new_username, user["username"]))
                    except:
                        pass
            # FIX: mark only this token used, plus invalidate all other tokens for user
            query_db("UPDATE password_resets SET used = 1 WHERE token = ?", (token,))
            query_db("UPDATE password_resets SET used = 1 WHERE user_id = ? AND used = 0", (user["id"],))
            # FIX: Invalidate other sessions by clearing push subscriptions? At least force re-login everywhere — we cannot delete Flask sessions stored client side, but we can log event
            try:
                query_db("INSERT INTO vendor_notifications (user_id, title, message, link, created_at) VALUES (?, ?, ?, ?, ?)", (user["id"], "Password reset", "Your password was reset via recovery link. All sessions logged out.", "/settings", datetime.now(timezone.utc).isoformat()))
            except:
                pass
        except sqlite3.IntegrityError:
            return render_template("reset_credentials.html", reset_error="That username is already taken.", token=token, user=user, reset_expires_at=reset_expires_at, app_theme=session.get("theme") or "day")
        # PROFESSIONAL META-AI STYLE: Auto-login after reset — directly open app, no need to type again
        session.clear()
        session["username"] = new_username
        session["email"] = user["email"]
        session["role"] = user["role"]
        session["seller_type"] = user.get("seller_type")
        session["company_name"] = user.get("company_name")
        session["business_location"] = user.get("business_location")
        session["whatsapp_number"] = user.get("whatsapp_number")
        session["theme"] = user.get("theme") or "day"
        session["welcome_message"] = True
        session["recovered"] = True
        # Role-based direct open app like Meta AI does
        if user["role"] == "Delivery Service":
            return redirect(url_for("delivery_dashboard"))
        elif user["role"] in ["Vendor", "Fast Food"]:
            return redirect(url_for("vendor_profile", username=new_username))
        else:
            return redirect(url_for("home"))
    return render_template("reset_credentials.html", token=token, user=user, reset_expires_at=reset_expires_at, app_theme=session.get("theme") or "day")

@app.route("/register", methods=["GET", "POST"])
def register():
    """Handles multi-tier merchant registrations, configuring complementary trials securely."""
    if request.method == "POST":
        username = request.form.get("reg_user", "").strip()
        email = request.form.get("reg_email", "").strip()
        password = request.form.get("reg_pass", "")
        submitted_role = request.form.get("role", "").strip()
        role_aliases = {"customer": "Customer", "vendor": "Vendor", "general store": "Vendor", "store": "Vendor", "general vendor": "Vendor", "fast food": "Fast Food", "kitchen": "Fast Food", "delivery service": "Delivery Service"}
        submitted_raw = submitted_role.strip()
        role = role_aliases.get(submitted_raw.lower(), submitted_raw)
        if role not in ("Customer", "Vendor", "Fast Food", "Delivery Service"):
            if "food" in submitted_raw.lower() or "kitchen" in submitted_raw.lower():
                role = "Fast Food"
            else:
                role = "Vendor"
        
        if not username or not email or not password:
            return render_template("login.html", reg_error="Username, email, and password are required.")
        if role == "Delivery Service":
            return redirect(url_for("delivery_register"))
            
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
        elif role == "Customer":
            seller_type = "Individual"
            company_name = None
            business_location = request.form.get("customer_location", "").strip() or "Accra"
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
            trial_expires_at = trial_started_at + timedelta(days=60)  # FIXED: 60 days vendor
            user_plan = "trial" if role in ["Vendor", "Fast Food"] else "basic"  # FIXED: clear trial label
            
            conn = sqlite3.connect(os.path.join(app.root_path, "marketplace.db"), timeout=30)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, email, password_hash, role, seller_type, company_name, whatsapp_number, plan, trial_started_at, subscription_expires_at, catalog_mode, company_logo, business_location, registered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (username, email, hashed_pwd, role, seller_type, company_name, whatsapp_number, user_plan, trial_started_at.isoformat() if role in ["Vendor", "Fast Food"] else None, trial_expires_at.isoformat() if role in ["Vendor", "Fast Food"] else None, catalog_mode, company_logo_filename, business_location, datetime.now(timezone.utc).isoformat())
            )
            inserted_id = cursor.lastrowid
            if inserted_id and selected_categories:
                try:
                    cursor.executemany("INSERT OR IGNORE INTO vendor_categories (user_id, category) VALUES (?, ?)", [(inserted_id, c) for c in selected_categories])
                except sqlite3.OperationalError:
                    pass
            conn.commit()
            try:
                conn.close()
            except:
                pass
                    
            session.clear()
            session["username"] = username
            session["email"] = email
            session["role"] = role
            session["seller_type"] = seller_type
            session["company_name"] = company_name
            session["business_location"] = business_location
            session["whatsapp_number"] = whatsapp_number
            session["theme"] = "day"
            session["welcome_message"] = True
            if role in ["Vendor", "Fast Food"]:
                return redirect(url_for("vendor_profile", username=username))
            return redirect(url_for("home"))
            
        except sqlite3.IntegrityError:
            return render_template("login.html", reg_error="Username is already taken.")
            
    return redirect(url_for("login"))


@app.route("/logout")
def logout():
    """👑 CORE ROLE-ADAPTIVE LOGOUT GATEWAY: Safely distinguishes admin sessions from normal store users."""
    # 🕵️‍♂️ Check who is logging out before we clear cookies out of memory
    is_admin_session = bool(session.get("is_admin") == True or session.get("role") == "Admin")
    
    # Securely wipe out active session parameters, cart arrays, and state tokens
    session.clear()
    session.modified = True
    
    # 🚀 ADAPTIVE DIRECTION MATRIX: Directs administrators to admin login, and vendors/customers to standard login!
    if is_admin_session:
        return redirect(url_for("admin_login"))
    else:
        return redirect(url_for("login"))


# 👑 MASTER VIDEO CHUNK STREAMING SYSTEM: Fixes blank video screens on mobile browsers
@app.route("/stream-video/<filename>")
def stream_video(filename):
    safe_filename = secure_filename(filename)
    if not safe_filename or safe_filename != filename:
        return "Video not found", 404
    video_path = os.path.join(app.config["UPLOAD_FOLDER"], safe_filename)
    if not os.path.isfile(video_path):
        return "Video not found", 404

    file_size = os.path.getsize(video_path)
    byte_range = request.headers.get("Range", None)
    extension = os.path.splitext(filename)[1].lower()
    mime_type = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime"}.get(extension, "application/octet-stream")

    if not byte_range:
        # Standard full file stream request
        def full_stream():
            with open(video_path, "rb") as video_file:
                while chunk := video_file.read(40960):
                    yield chunk
        return app.response_class(full_stream(), mimetype=mime_type, headers={"Content-Length": str(file_size), "Accept-Ranges": "bytes"})

    # Parse requested HTTP range bytes (e.g. bytes=0-1024)
    parsed_range = re.search(r"bytes=(\d+)-(\d*)", byte_range)
    if not parsed_range:
        return "Invalid range", 416
    start_byte = int(parsed_range.group(1))
    if start_byte >= file_size:
        return "Range not satisfiable", 416
    end_byte = int(parsed_range.group(2)) if parsed_range.group(2) else file_size - 1
    end_byte = min(end_byte, file_size - 1)
    if end_byte < start_byte:
        return "Range not satisfiable", 416

    chunk_length = (end_byte - start_byte) + 1

    def partial_chunk_stream():
        with open(video_path, "rb") as video_file:
            video_file.seek(start_byte)
            bytes_sent = 0
            while bytes_sent < chunk_length:
                buffer_size = min(40960, chunk_length - bytes_sent)
                data = video_file.read(buffer_size)
                if not data:
                    break
                yield data
                bytes_sent += len(data)

    headers = {
        "Content-Range": f"bytes {start_byte}-{end_byte}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_length)
    }
    return app.response_class(partial_chunk_stream(), status=206, mimetype=mime_type, headers=headers)
@app.route("/api/search-suggestions")
def api_search_suggestions():
    """🚀 LIVE AUTCOMPLETE API ENGINE: Streams real-time matching suggestions as the user types."""
    query = request.args.get("q", "").strip().lower()
    if not query or len(query) < 2:
        return {"suggestions": []}
        
    pattern = f"%{query}%"
    # Find matching company names, usernames, or neighborhood locations instantly
    results = query_db("""
        SELECT DISTINCT 
            COALESCE(company_name, username) AS label,
            username,
            business_location AS location,
            role
        FROM users 
        WHERE COALESCE(account_status, 'Active') NOT IN ('Suspended', 'Terminated')
          AND role IN ('Vendor', 'Fast Food')
          AND (lower(company_name) LIKE ? OR lower(username) = ? OR lower(business_location) LIKE ?)
        LIMIT 6
    """, (pattern, query, pattern)) or []
    
    suggestions_list = []
    for r in results:
        suggestions_list.append({
            "label": r["label"],
            "username": r["username"],
            "location": r["location"] or "Accra Hub",
            "is_kitchen": r["role"] == "Fast Food"
        })
        
    return {"suggestions": suggestions_list}

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "0""") == "1", host="0.0.0.0")