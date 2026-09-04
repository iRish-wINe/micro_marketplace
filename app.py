import sqlite3
import os
import uuid
import re
import json
import logging
import hashlib
import base64
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, render_template_string, Response
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import RequestEntityTooLarge
app = Flask(__name__)
logger = logging.getLogger(__name__)
app.secret_key = os.environ.get("BIZ_HUB_SECRET_KEY", "commercial_marketplace_super_secret_token")
LOCAL_ADMIN_USERNAME = "Stapps Of Faith"
LOCAL_ADMIN_PASSWORD = "RICHARD10"
PRODUCT_CATEGORIES = ["Phones & Accessories", "Groceries", "Clothing", "Books", "Health & Beauty", "Beauty & Personal Care", "Home & Kitchen", "Electronics", "Fast Food", "Other"]
VENDOR_CATEGORIES = PRODUCT_CATEGORIES + ["Health & Beauty", "Fast Food"]
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

    try:
        cursor.execute("UPDATE products SET initial_stock_quantity = stock_quantity WHERE COALESCE(sold_quantity, 0) = 0 AND initial_stock_quantity = 1 AND stock_quantity > 1")
    except sqlite3.OperationalError:
        pass

    for statement in (
        "ALTER TABLE promotions ADD COLUMN product_id INTEGER",
        "ALTER TABLE promotions ADD COLUMN promo_price REAL",
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
                trial_expires_at = trial_started_at + timedelta(days=150)
                cursor.execute("UPDATE users SET plan = 'basic', trial_started_at = ?, subscription_expires_at = ? WHERE id = ?", (trial_started_at.isoformat(), trial_expires_at.isoformat(), user_id))
            except ValueError:
                pass
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()

init_db()

def normalize_whatsapp_number(number):
    digits = "".join(character for character in (number or "") if character.isdigit())
    if digits.startswith("0"):
        digits = "233" + digits[1:]
    return digits

def subscription_status(user):
    if not user:
        return {"name": "Basic", "is_premium": False, "trial": False, "expires": None, "expires_iso": None}
    now = datetime.now(timezone.utc)
    expiry_raw = user.get("subscription_expires_at")
    expiry = None
    if expiry_raw:
        try:
            expiry = datetime.fromisoformat(expiry_raw)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
        except ValueError:
            expiry = None
    is_vendor_role = user.get("role") in ["Vendor", "Fast Food", "Delivery Service"]
    trial_active = bool(is_vendor_role and expiry and expiry > now and user.get("plan") == "basic")
    premium_active = bool(is_vendor_role and expiry and expiry > now and user.get("plan") == "premium")
    if trial_active:
        return {"name": "Free trial", "is_premium": True, "trial": True, "expires": expiry.strftime("%d %b %Y"), "expires_iso": expiry.isoformat()}
    if premium_active:
        return {"name": "Premium Delivery" if user.get("role") == "Delivery Service" else "Premium Store", "is_premium": True, "trial": False, "expires": expiry.strftime("%d %b %Y"), "expires_iso": expiry.isoformat()}
    return {"name": "Basic", "is_premium": False, "trial": False, "expires": None, "expires_iso": None}

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
    return bool(get_admin_username() and get_admin_password()) or bool(query_db("SELECT id FROM admin_users LIMIT 1"))

def get_admin_username():
    return os.environ.get("BIZ_HUB_ADMIN_USERNAME") or LOCAL_ADMIN_USERNAME

def get_admin_password():
    return os.environ.get("BIZ_HUB_ADMIN_PASSWORD") or LOCAL_ADMIN_PASSWORD

def admin_signup_available():
    return not bool(query_db("SELECT id FROM admin_users LIMIT 1"))

def is_admin():
    return session.get("is_admin") is True

def _bizhub_vapid_material():
    """Return stable VAPID keys derived from the existing BizHub app secret."""
    secret = os.environ.get("BIZ_HUB_SECRET_KEY", "commercial_marketplace_super_secret_token")
    curve_order = int("FFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551", 16)
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
        icon: "/static/uploads/icon-192.png",
        badge: "/static/uploads/icon-192.png",
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
    welcome_message = bool(session.pop("welcome_message", False))
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
        stock_quantity = request.form.get("stock_quantity", "")
        location = request.form.get("location")
        file = request.files.get("product_image")
        video = request.files.get("product_video")
        
        # 👑 BULLETPROOF MULTI-MEDIA FILE IDENTIFICATION MATRIX
        has_image = bool(file and file.filename)
        has_video = bool(video and video.filename)
        
        # Marketplace listings require exactly one cover image OR showcase video.
        if not is_fast_food and has_image == has_video:
            return redirect(url_for("home", listing_error="Choose exactly one item media option: Image OR Showcase Video."))
        if is_fast_food and not has_image and not has_video:
            return redirect(url_for("home", listing_error="Add a meal image or showcase video before publishing."))

        if has_image:
            original_extension = os.path.splitext(secure_filename(file.filename))[1].lower()
            if original_extension not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                return redirect(url_for("home", listing_error="Item images must be PNG, JPG, JPEG, WEBP, or GIF files."))
            filename = f"product-{uuid.uuid4().hex}{original_extension}"
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
                
                if parsed_duration > 20.0:
                    os.remove(temp_video_path)
                    return redirect(url_for("home", listing_error="🚫 UPLOAD REFUSED: Showcase videos are limited to 20 seconds."))
            except Exception:
                # Fallback guard if server utilities hit lock bounds
                pass
        else:
            video_filename = None

        if is_fast_food:
            # Fast Food menu entries are permanent listings; quantity is not used.
            stock_quantity = 1
        else:
            try:
                stock_quantity = int(stock_quantity)
            except (TypeError, ValueError):
                return redirect(url_for("home", listing_error="Please enter how many units are available before publishing this item."))
            if stock_quantity < 1:
                return redirect(url_for("home", listing_error="Please enter a quantity greater than zero before publishing this item."))

        if title and price and description and location:
            # Save the product image for both Marketplace and Fast Food listings.
            if has_image:
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                
            b_label = session.get("company_name") or "Individual Vendor"
            
            query_db(
                "INSERT INTO products (title, price, description, image_file, video_file, stock_quantity, initial_stock_quantity, sold_quantity, status, seller, seller_email, seller_whatsapp, location, business_label, category) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
                (title, float(price), description, filename, video_filename, stock_quantity, stock_quantity, "Available", session["username"], session["email"], session.get("whatsapp_number"), location, b_label, category)
            )
            vendor_user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
            if vendor_user:
                notify_favorite_customers(vendor_user["id"], "product", f"{b_label} added a new item", title, url_for("vendor_profile", username=session["username"]))
            return redirect(url_for("home", published="fastfood" if is_fast_food else "1"))

            
    selected_filter = request.args.get("filter_location", "All")
    company_search = request.args.get("company_search", request.args.get("search", "")).strip()
    location_search = request.args.get("location_search", "").strip()
    selected_category = request.args.get("category", "All")
    promo_only = request.args.get("promo") == "1"
    listing_error = request.args.get("listing_error")
    favorite_vendor_usernames = set()
    if session.get("role") == "Customer":
        customer_user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
        if customer_user:
            favorite_rows = query_db("SELECT u.username FROM favorites f JOIN users u ON u.id = f.vendor_id WHERE f.customer_id = ?", (customer_user["id"],)) or []
            favorite_vendor_usernames = {row["username"] for row in favorite_rows}
    
    product_conditions = ["p.category != 'Fast Food'", "COALESCE(u.account_status, 'Active') NOT IN ('Suspended', 'Terminated')"]
    product_args = [datetime.now(timezone.utc).isoformat()]
    
    if selected_filter != "All":
        product_conditions.append("location = ?")
        product_args.append(selected_filter)
    if company_search:
        product_conditions.append("(p.title LIKE ? OR p.description LIKE ? OR p.business_label LIKE ? OR p.seller LIKE ? OR u.company_name LIKE ? OR u.username LIKE ? OR p.location LIKE ?)")
        search_pattern = f"%{company_search}%"
        product_args.extend([search_pattern] * 7)
    if location_search:
        product_conditions.append("(p.location LIKE ? OR u.business_location LIKE ?)")
        location_pattern = f"%{location_search}%"
        product_args.extend([location_pattern, location_pattern])
    if selected_category != "All":
        product_conditions.append("category = ?")
        product_args.append(selected_category)
    if promo_only:
        now_iso = datetime.now(timezone.utc).isoformat()
        product_conditions.append("EXISTS (SELECT 1 FROM promotions pr JOIN users pu ON pu.id = pr.vendor_id WHERE pu.username = p.seller AND pr.active = 1 AND pr.starts_at <= ? AND pr.ends_at >= ?)")
        product_args.extend([now_iso, now_iso])
        
    product_query = "SELECT p.*, COALESCE(u.company_name, p.business_label, p.seller) AS business_label, u.company_name AS vendor_company_name, CASE WHEN EXISTS (SELECT 1 FROM users vu WHERE vu.username = p.seller AND vu.role IN ('Vendor', 'Fast Food') AND (vu.plan = 'premium' OR (vu.plan = 'basic' AND vu.subscription_expires_at > ?))) THEN 1 ELSE 0 END AS is_verified FROM products p LEFT JOIN users u ON u.username = p.seller"
    if product_conditions:
        product_query += " WHERE " + " AND ".join(product_conditions)
    product_query += " ORDER BY p.id DESC"
    
    all_products = query_db(product_query, product_args) or []
    all_products.sort(key=lambda product: (product["seller"] not in favorite_vendor_usernames, -int(product["id"])))

    # Fast Food stays completely separate from the Amazon-style marketplace feed.
    fast_food_products = query_db("SELECT p.*, COALESCE(u.company_name, p.business_label, p.seller) AS business_label FROM products p LEFT JOIN users u ON u.username = p.seller WHERE p.category = 'Fast Food' AND COALESCE(u.account_status, 'Active') NOT IN ('Suspended', 'Terminated') ORDER BY p.id DESC") or []
    fast_food_products.sort(key=lambda product: (product["seller"] not in favorite_vendor_usernames, -int(product["id"])))
    fast_food_vendors = query_db("SELECT id, username, company_name, business_location, company_logo, whatsapp_number FROM users WHERE role = 'Fast Food' AND account_status NOT IN ('Suspended', 'Terminated') ORDER BY id DESC") or []
    for kitchen in fast_food_vendors:
        kitchen["business_label"] = kitchen.get("company_name") or kitchen.get("username")
        kitchen["menu_count"] = sum(1 for meal in fast_food_products if meal.get("seller") == kitchen.get("username"))

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
    marketplace_products = all_products
    todays_deals = [p for p in all_products if p.get("active_promo")][:12]
    inventory_items = []
    if session.get("role") == "Vendor":
        inventory_items = query_db("SELECT id, title, initial_stock_quantity, stock_quantity, sold_quantity, status FROM products WHERE seller = ? AND category != 'Fast Food' ORDER BY id DESC", (session["username"],)) or []

    customer_notification_count = 0
    if session.get("role") == "Customer":
        customer_user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
        if customer_user:
            row = query_db("SELECT COUNT(*) AS count FROM notifications WHERE recipient_id = ? AND is_read = 0", (customer_user["id"],), one=True)
            customer_notification_count = row["count"] if row else 0

    cart_items = []
    cart_total = 0.0
    active_coupon = get_valid_coupon(session.get("coupon_code"))
    if not active_coupon:
        session.pop("coupon_code", None)
    discount_total = 0.0
    seller_orders = {}

    cart = session.get("cart") or {}
    if isinstance(cart, list):
        cart = {str(pid): 1 for pid in cart}
    if cart:
        ids = [int(k) for k in cart]
        placeholders = ",".join("?" for _ in ids)
        items_in_db = query_db(f"SELECT * FROM products WHERE id IN ({placeholders}) AND category != 'Fast Food'", ids) or []
        for item in items_in_db:
            qty = min(int(cart.get(str(item["id"]), 1)), max(0, int(item.get("stock_quantity") or 0)))
            if qty <= 0:
                continue
            item["cart_quantity"] = qty
            item["cart_line_total"] = float(item["price"]) * qty
            cart_items.append(item)
            item_discount = 0.0
            if active_coupon and item["seller"] == active_coupon["username"]:
                item_discount = item["cart_line_total"] * float(active_coupon["discount"]) / 100
            item["discount_amount"] = item_discount
            item["discounted_line_total"] = item["cart_line_total"] - item_discount
            cart_total += item["discounted_line_total"]
            discount_total += item_discount
            seller_number = normalize_whatsapp_number(item["seller_whatsapp"])
            seller_key = (item["seller"], seller_number)
            seller_order = seller_orders.setdefault(seller_key, {"seller": item["seller"], "number": seller_number, "items": [], "total": 0.0})
            seller_order["items"].append(item)
            seller_order["total"] += item["discounted_line_total"]
        cart_count = sum(int(item.get("cart_quantity", 0)) for item in cart_items)
    else:
        cart_count = 0

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

    return render_template("index.html", products=marketplace_products, marketplace_products=marketplace_products, fast_food_products=fast_food_products, fast_food_vendors=fast_food_vendors, todays_deals=[p for p in marketplace_products if p.get("active_promo")][:12], active_filter=selected_filter, company_search=company_search, location_search=location_search, selected_category=selected_category, categories=PRODUCT_CATEGORIES, vendor_logos=vendor_logos, cart_items=cart_items, cart_total=cart_total, discount_total=discount_total, active_coupon=active_coupon, seller_orders=sorted(seller_orders.values(), key=lambda order: not order["priority"]), vendor_subscription=vendor_subscription, listing_count=listing_count, fast_food_count=fast_food_count, inventory_items=inventory_items, listing_error=listing_error, premium_sellers=premium_sellers, vendor_notification_count=vendor_notification_count, customer_notification_count=customer_notification_count, promo_only=promo_only, cart_added=request.args.get("cart_added") == "1", published=request.args.get("published") == "1", published_fastfood=request.args.get("published") == "fastfood", welcome_message=welcome_message)
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
    product = query_db("SELECT id, stock_quantity, status, category, title FROM products WHERE id = ?", (product_id,), one=True)
    if not product or product.get("category") == "Fast Food":
        return redirect(url_for("home"))
    if int(product.get("stock_quantity") or 0) < 1 or product.get("status") == "Sold":
        return redirect(url_for("home", listing_error="This product is sold out."))
    cart = session.get("cart") or {}
    if isinstance(cart, list):
        cart = {str(pid): 1 for pid in cart}
    key = str(product_id)
    current = int(cart.get(key, 0) or 0)
    if current >= int(product["stock_quantity"]):
        return redirect(url_for("home", listing_error=f"Only {product['stock_quantity']} available for {product['title']}."))
    cart[key] = current + 1
    session["cart"] = cart
    session.modified = True
    return redirect(url_for("home", cart_added="1"))

@app.route("/update-cart/<int:product_id>", methods=["POST"])
def update_cart(product_id):
    cart = session.get("cart") or {}
    if isinstance(cart, list):
        cart = {str(pid): 1 for pid in cart}
    key = str(product_id)
    try:
        requested = max(0, int(request.form.get("quantity", "0")))
    except (TypeError, ValueError):
        requested = 0
    product = query_db("SELECT stock_quantity, status, category FROM products WHERE id = ?", (product_id,), one=True)
    if not product or product.get("category") == "Fast Food" or product.get("status") == "Sold" or int(product.get("stock_quantity") or 0) <= 0:
        cart.pop(key, None)
    elif requested <= 0:
        cart.pop(key, None)
    else:
        cart[key] = min(requested, int(product["stock_quantity"]))
    session["cart"] = cart
    session.modified = True
    return redirect(url_for("home"))

@app.route("/mark-sold/<int:product_id>", methods=["POST"])
def mark_sold(product_id):
    if session.get("role") != "Vendor":
        return redirect(url_for("login"))
    product = query_db("SELECT stock_quantity, sold_quantity FROM products WHERE id = ? AND seller = ?", (product_id, session["username"]), one=True)
    if product:
        try:
            removed = int(request.form.get("sold_quantity", "1"))
        except (TypeError, ValueError):
            removed = 0
        if 1 <= removed <= int(product["stock_quantity"]):
            query_db("UPDATE products SET stock_quantity = MAX(stock_quantity - ?, 0), status = CASE WHEN stock_quantity <= ? THEN 'Sold' ELSE 'Available' END WHERE id = ? AND seller = ?", (removed, removed, product_id, session["username"]))
    return redirect(url_for("home"))

@app.route("/clear-cart")
def clear_cart():
    session.pop("cart", None)
    session.pop("coupon_code", None)
    return redirect(url_for("home"))

@app.route("/apply-coupon", methods=["POST"])
def apply_coupon():
    if session.get("role") != "Customer":
        return redirect(url_for("login"))
    coupon = get_valid_coupon(request.form.get("code", ""))
    if coupon:
        session["coupon_code"] = coupon["code"]
        return redirect(url_for("home", coupon_applied="1"))
    return redirect(url_for("home", listing_error="That coupon is invalid, inactive, or expired."))

@app.route("/remove-coupon", methods=["POST"])
def remove_coupon():
    session.pop("coupon_code", None)
    return redirect(url_for("home"))

@app.route("/place-order", methods=["POST"])
def place_order():
    if "username" not in session:
        return redirect(url_for("login"))
    cart = session.get("cart") or {}
    if isinstance(cart, list):
        cart = {str(pid): 1 for pid in cart}
    cart = {str(k): int(v) for k, v in cart.items() if int(v) > 0}
    if not cart:
        return redirect(url_for("home"))
    ids = [int(k) for k in cart]
    placeholders = ",".join("?" for _ in ids)
    items = query_db(f"SELECT * FROM products WHERE id IN ({placeholders}) AND category != 'Fast Food' AND status = 'Available'", ids) or []
    by_id = {int(item["id"]): item for item in items}
    if len(by_id) != len(ids):
        return redirect(url_for("home", listing_error="One or more cart items are no longer available."))
    for item in items:
        qty = cart[str(item["id"])]
        if qty > int(item["stock_quantity"]):
            return redirect(url_for("home", listing_error=f"Only {item['stock_quantity']} available for {item['title']}."))
    active_coupon = get_valid_coupon(session.get("coupon_code"))
    discount_amount = sum(float(item["price"]) * cart[str(item["id"])] * float(active_coupon["discount"]) / 100 for item in items if active_coupon and item["seller"] == active_coupon["username"])
    total = sum(float(item["price"]) * cart[str(item["id"])] for item in items) - discount_amount
    created_at = datetime.now(timezone.utc).isoformat()
    conn = open_db()
    try:
        conn.execute("BEGIN")
        cur = conn.execute("INSERT INTO orders (customer_username, total, status, payment_status, coupon_code, discount_amount, created_at) VALUES (?, ?, 'Pending', 'Unpaid', ?, ?, ?)", (session["username"], total, active_coupon["code"] if active_coupon else None, discount_amount, created_at))
        order_id = cur.lastrowid
        external_vendor_notifications = []
        for item in items:
            qty = cart[str(item["id"])]
            conn.execute("INSERT INTO order_items (order_id, product_id, seller, title, price, quantity) VALUES (?, ?, ?, ?, ?, ?)", (order_id, item["id"], item["seller"], item["title"], item["price"], qty))
            vendor = conn.execute("SELECT id FROM users WHERE username = ? AND role = 'Vendor'", (item["seller"],)).fetchone()
            if vendor:
                message = f"New purchase from @{session['username']}: {item['title']} x{qty} for GH₵{float(item['price']) * qty:.2f}. Location: {item.get('location') or 'Not specified'}."
                conn.execute("INSERT INTO vendor_notifications (vendor_id, order_id, product_id, customer_username, item_name, price, location, message, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (vendor["id"], order_id, item["id"], session["username"], item["title"], float(item["price"]) * qty, item.get("location"), message, created_at))
                external_vendor_notifications.append((vendor["id"], "New order", message))
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
            location = next((item.get("location") for item in items if item.get("location")), None)
            order_view = dict(order)
            order_view.update({"items": [{"name": i["title"], "price": i["price"], "quantity": i["quantity"], "image": i.get("image"), "vendor_name": i.get("vendor_company") or i["seller"], "vendor_id": i["seller"]} for i in items], "total": total, "location": location, "customer_whatsapp": customer.get("whatsapp_number") if customer else None})
        else:
            items = query_db("""SELECT oi.*, p.image_file AS image, p.location, u.id AS vendor_id, COALESCE(u.company_name, u.username) AS vendor_name
                               FROM order_items oi LEFT JOIN products p ON p.id = oi.product_id
                               LEFT JOIN users u ON u.username = oi.seller
                               WHERE oi.order_id = ?""", (order["id"],)) or []
            order_view = dict(order)
            order_view.update({"items": [{"name": i["title"], "price": i["price"], "quantity": i["quantity"], "image": i.get("image"), "vendor_name": i.get("vendor_name") or i["seller"], "vendor_id": i.get("vendor_id") or i["seller"]} for i in items], "location": next((i.get("location") for i in items if i.get("location")), None)})
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
    return redirect(request.referrer or url_for("order_history"))

@app.route("/orders/notifications/<int:notification_id>/read", methods=["POST"])
def mark_order_notification_read(notification_id):
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    vendor = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if vendor:
        query_db("UPDATE vendor_notifications SET is_read = 1 WHERE id = ? AND vendor_id = ?", (notification_id, vendor["id"]))
    return redirect(request.referrer or url_for("order_history"))

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
    if session.get("role") != "Vendor":
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
            updated = conn.execute("UPDATE products SET stock_quantity = stock_quantity - ?, sold_quantity = COALESCE(sold_quantity, 0) + ?, status = CASE WHEN stock_quantity - ? <= 0 THEN 'Sold' ELSE 'Available' END WHERE id = ? AND category != 'Fast Food' AND status = 'Available' AND stock_quantity >= ?", (qty, qty, qty, item["product_id"], qty))
            if updated.rowcount != 1:
                conn.rollback()
                return redirect(url_for("order_history", inventory_error=f"Sorry, {item['title']} just sold out or no longer has enough stock."))
        conn.execute("UPDATE orders SET status = 'Confirmed', payment_status = 'Confirmed' WHERE id = ?", (order_id,))
        conn.execute("INSERT INTO order_events (order_id, actor_username, status, reason, created_at) VALUES (?, ?, 'Confirmed', 'Payment and stock confirmed', ?)", (order_id, session["username"], datetime.now(timezone.utc).isoformat()))
        customer_username = order["customer_username"]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    customer = query_db("SELECT id FROM users WHERE username = ?", (customer_username,), one=True) if customer_username else None
    if customer:
        create_notification(customer["id"], "order", "Order confirmed", f"Order #{order_id} has been confirmed by the vendor.", url_for("order_history"))
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
    vendor = query_db(
        "SELECT * FROM users WHERE username = ? AND role IN ('Vendor', 'Fast Food')",
        (username,), one=True
    )
    if not vendor:
        return redirect(url_for("home"))
    vendor_status = subscription_status(vendor)
    vendor["is_verified"] = vendor_status["is_premium"]
    vendor["is_premium"] = vendor_status["is_premium"]
    products = query_db(
        "SELECT * FROM products WHERE seller = ? ORDER BY id DESC",
        (username,)
    )
    reviews = query_db("SELECT r.*, u.username AS reviewer_username FROM reviews r JOIN users u ON u.id = r.reviewer_id WHERE r.vendor_id = ? ORDER BY r.id DESC", (vendor["id"],)) or []
    review_summary = query_db("SELECT AVG(rating) AS average_rating, COUNT(*) AS review_count FROM reviews WHERE vendor_id = ?", (vendor["id"],), one=True) or {"average_rating": None, "review_count": 0}
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
    vendor_whatsapp = normalize_whatsapp_number(vendor.get("whatsapp_number"))
    vendor_whatsapp_text = quote(f"Hey {vendor.get('company_name') or vendor.get('username')}, I visited your store on BizHub and I'd love to know more about your brand.")
    for product in products:
        product["meal_whatsapp_number"] = vendor_whatsapp
        product["meal_whatsapp_text"] = quote(f"Hello {vendor.get('company_name') or vendor.get('username')}, I want to buy {product.get('title')} on BizHub, lets arrange for payment and delivery.")
    return render_template("vendor_profile.html", vendor=vendor, products=products, categories=categories, promo=promo, favorite=favorite, product_count=len(products), subscription=vendor_status, vendor_whatsapp=vendor_whatsapp, vendor_whatsapp_text=vendor_whatsapp_text, reviews=reviews, review_summary=review_summary)

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
        create_notification(vendor["id"], "favorite", "New Favorite", f"@{session['username']} added your store to their favorites.", url_for("vendor_profile", username=username))
    return redirect(request.referrer or url_for("vendor_profile", username=username))

@app.route("/notifications/<int:notification_id>/read", methods=["POST"])
def mark_notification_read(notification_id):
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if user:
        query_db("UPDATE notifications SET is_read = 1 WHERE id = ? AND recipient_id = ?", (notification_id, user["id"]))
    return redirect(request.referrer or url_for("notifications"))

@app.route("/notifications/read-all", methods=["POST"])
def mark_all_notifications_read():
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if user:
        query_db("UPDATE notifications SET is_read = 1 WHERE recipient_id = ?", (user["id"],))
    return redirect(request.referrer or url_for("notifications"))

@app.route("/notifications")
def notifications():
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    if not user:
        session.clear()
        return redirect(url_for("login"))
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
    return redirect(request.referrer or url_for("notifications"))

@app.route("/notifications/customer/read-all", methods=["POST"])
def mark_all_customer_notifications_read():
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if user:
        query_db("UPDATE notifications SET is_read = 1 WHERE recipient_id = ?", (user["id"],))
    return redirect(request.referrer or url_for("notifications"))

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
    saved_searches = query_db("SELECT * FROM saved_searches WHERE user_id = ? ORDER BY id DESC", (user["id"],)) or []
    analytics = None
    coupons = []
    if user["role"] in ["Vendor", "Fast Food"]:
        analytics = query_db("SELECT COUNT(*) AS listings, COALESCE(SUM(views), 0) AS views, COALESCE(SUM(sold_quantity), 0) AS sold_units FROM products WHERE seller = ?", (user["username"],), one=True)
        coupons = query_db("SELECT * FROM coupons WHERE vendor_id = ? ORDER BY id DESC", (user["id"],)) or []
    return render_template("features.html", user=user, loyalty=loyalty, reviews=reviews, delivery_requests=delivery_requests, saved_searches=saved_searches, analytics=analytics, coupons=coupons, verification_sent=request.args.get("verification_sent") == "1")

@app.route("/coupons", methods=["POST"])
def create_coupon():
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    vendor = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    code = request.form.get("code", "").strip().upper()
    description = request.form.get("description", "").strip()
    try:
        discount = float(request.form.get("discount", 0))
    except ValueError:
        discount = 0
    if vendor and code and description and 0 < discount <= 100:
        try:
            query_db("INSERT INTO coupons (vendor_id, code, description, discount, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?)", (vendor["id"], code, description, discount, request.form.get("expires_at") or None, datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError:
            pass
    return redirect(url_for("features"))

@app.route("/reviews/<int:vendor_id>", methods=["POST"])
def submit_review(vendor_id):
    if session.get("role") != "Customer":
        return redirect(url_for("login"))
    reviewer = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    vendor = query_db("SELECT id, username FROM users WHERE id = ? AND role IN ('Vendor', 'Fast Food')", (vendor_id,), one=True)
    try:
        rating = int(request.form.get("rating", 5))
    except ValueError:
        rating = 5
    comment = request.form.get("comment", "").strip()
    if reviewer and vendor and reviewer["id"] != vendor["id"] and 1 <= rating <= 5 and comment:
        query_db("INSERT INTO reviews (reviewer_id, vendor_id, rating, comment, created_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(reviewer_id, vendor_id) DO UPDATE SET rating = excluded.rating, comment = excluded.comment, created_at = excluded.created_at", (reviewer["id"], vendor["id"], rating, comment, datetime.now(timezone.utc).isoformat()))
        create_notification(vendor["id"], "announcement", "New customer review", f"A customer left your store a {rating}-star review.", url_for("vendor_profile", username=vendor["username"]))
    return redirect(request.referrer or url_for("vendor_profile", username=vendor["username"] if vendor else ""))

@app.route("/verification/request", methods=["POST"])
def request_verification():
    if session.get("role") not in ["Vendor", "Fast Food", "Delivery Service"]:
        return redirect(url_for("login"))
    user = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if user:
        pending = query_db("SELECT id FROM verification_requests WHERE user_id = ? AND status = 'Pending'", (user["id"],), one=True)
        if not pending:
            query_db("INSERT INTO verification_requests (user_id, created_at) VALUES (?, ?)", (user["id"], datetime.now(timezone.utc).isoformat()))
            create_notification(user["id"], "announcement", "Verification request sent", "Your BizHub verification request has been sent. BizHub will review it and notify you of the outcome.", url_for("features"))
        return redirect(url_for("features", verification_sent="1"))
    return redirect(url_for("features"))

@app.route("/delivery/request/<int:service_id>", methods=["POST"])
def request_delivery(service_id):
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    vendor = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    service = query_db("SELECT ds.id, ds.service_name, ds.user_id FROM delivery_services ds WHERE ds.id = ?", (service_id,), one=True)
    message = request.form.get("message", "Delivery request from BizHub.").strip() or "Delivery request from BizHub."
    if vendor and service:
        now = datetime.now(timezone.utc).isoformat()
        query_db("INSERT INTO delivery_requests (vendor_id, service_id, message, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (vendor["id"], service["id"], message, now, now))
        create_notification(service["user_id"], "delivery", "New delivery request", f"@{session['username']} requested delivery from {service['service_name']}.", url_for("features"))
    return redirect(request.referrer or url_for("delivery_services"))

@app.route("/delivery/requests/<int:request_id>/status", methods=["POST"])
def update_delivery_request(request_id):
    if "username" not in session:
        return redirect(url_for("login"))
    user = query_db("SELECT id, role FROM users WHERE username = ?", (session["username"],), one=True)
    allowed = {"Requested", "Accepted", "Picked Up", "Delivered", "Declined"}
    status = request.form.get("status", "Requested")
    if status not in allowed or not user:
        return redirect(request.referrer or url_for("features"))
    if user["role"] == "Delivery Service":
        query_db("UPDATE delivery_requests SET status = ?, updated_at = ? WHERE id = ? AND service_id IN (SELECT id FROM delivery_services WHERE user_id = ?)", (status, datetime.now(timezone.utc).isoformat(), request_id, user["id"]))
    else:
        query_db("UPDATE delivery_requests SET status = ?, updated_at = ? WHERE id = ? AND vendor_id = ?", (status, datetime.now(timezone.utc).isoformat(), request_id, user["id"]))
    return redirect(request.referrer or url_for("features"))

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
        promo_price_raw = request.form.get("promo_price", "").strip()
        product_id_raw = request.form.get("product_id", "").strip()
        starts_at = request.form.get("starts_at", "").strip()
        ends_at = request.form.get("ends_at", "").strip()
        promo_image = request.files.get("promo_image")
        promo_video = request.files.get("promo_video")
        try:
            discount = float(discount_raw) if discount_raw else None
        except ValueError:
            discount = None
        try:
            promo_price = float(promo_price_raw) if promo_price_raw else None
        except ValueError:
            promo_price = None
        try:
            product_id = int(product_id_raw) if product_id_raw else None
        except ValueError:
            product_id = None
        if product_id:
            product = query_db("SELECT * FROM products WHERE id = ? AND seller = ?", (product_id, vendor["username"]), one=True)
            if not product:
                product_id = None
                promo_error = "Choose one of your own products."
        if not title or not starts_at or not ends_at:
            promo_error = "Promotion title, start date and end date are required."
        else:
            starts_iso = starts_at.replace("T", " ") + (":00" if len(starts_at) == 16 else "")
            ends_iso = ends_at.replace("T", " ") + (":00" if len(ends_at) == 16 else "")
            if ends_iso <= starts_iso:
                promo_error = "Promotion end date must be after the start date."
            elif discount is not None and not (0 <= discount <= 100):
                promo_error = "Discount must be between 0 and 100 percent."
            elif promo_price is not None and promo_price < 0:
                promo_error = "Promotional price cannot be negative."
            if promo_video and promo_video.filename:
                ext = os.path.splitext(promo_video.filename)[1].lower()
                if ext not in VIDEO_EXTENSIONS:
                    promo_error = "Promotion videos must be MP4, WebM, or MOV files."
                else:
                    video_filename = f"promo-video-{uuid.uuid4().hex}{ext}"
                    video_path = os.path.join(app.config["UPLOAD_FOLDER"], video_filename)
                    promo_video.save(video_path)
                    try:
                        import subprocess
                        duration = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]).decode().strip())
                        if duration > 30.0:
                            os.remove(video_path)
                            video_filename = None
                            promo_error = "Short promo ad videos are limited to 30 seconds."
                    except Exception:
                        pass
            else:
                video_filename = None
            image_filename = None
            if promo_image and promo_image.filename:
                image_filename = save_company_logo(promo_image)
                if image_filename:
                    image_filename = "promo-" + image_filename[len("company-"):] if image_filename.startswith("company-") else image_filename
                else:
                    promo_error = "Promotion images must be PNG, JPG, JPEG, WEBP, or GIF."
            if not promo_error:
                query_db("UPDATE promotions SET active = 0 WHERE vendor_id = ?", (vendor["id"],))
                query_db("INSERT INTO promotions (vendor_id, product_id, title, description, discount, promo_price, image_file, video_file, starts_at, ends_at, active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)", (vendor["id"], product_id, title, description, discount, promo_price, image_filename, video_filename, starts_iso, ends_iso, datetime.now(timezone.utc).isoformat()))
                notify_favorite_customers(vendor["id"], "promotion", f"{vendor['company_name'] or vendor['username']} has a new promotion", title, url_for("vendor_profile", username=vendor["username"]))
                return redirect(url_for("promotions", saved="1"))
    promo_rows = query_db("SELECT pr.*, p.title AS product_title FROM promotions pr LEFT JOIN products p ON p.id = pr.product_id WHERE pr.vendor_id = ? ORDER BY pr.id DESC", (vendor["id"],))
    products = query_db("SELECT id, title, price FROM products WHERE seller = ? ORDER BY id DESC", (vendor["username"],)) or []
    return render_template("promotions.html", vendor=vendor, promotions=promo_rows, products=products, subscription=subscription, promo_error=promo_error, saved=request.args.get("saved") == "1")

@app.route("/promotions/<int:promotion_id>/deactivate", methods=["POST"])
def deactivate_promotion(promotion_id):
    if session.get("role") not in ["Vendor", "Fast Food"]:
        return redirect(url_for("login"))
    vendor = query_db("SELECT id FROM users WHERE username = ?", (session["username"],), one=True)
    if vendor:
        query_db("UPDATE promotions SET active = 0 WHERE id = ? AND vendor_id = ?", (promotion_id, vendor["id"]))
    return redirect(url_for("promotions"))

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
            trial_expires_at = trial_started_at + timedelta(days=150)
            user_id = query_db("INSERT INTO users (username, email, password_hash, role, seller_type, company_name, whatsapp_number, plan, trial_started_at, subscription_expires_at, registered_at) VALUES (?, ?, ?, 'Delivery Service', 'Delivery Service', ?, ?, 'basic', ?, ?, ?)", (username, email, generate_password_hash(password), service_name, phone_number, trial_started_at.isoformat(), trial_expires_at.isoformat(), trial_started_at.isoformat()))
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
    if session.get("role") != "Delivery Service":
        return redirect(url_for("delivery_register"))
    welcome_message = bool(session.pop("welcome_message", False))
    sync_delivery_availability()
    user = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    service = get_delivery_service(user["id"]) if user else None
    return render_template("delivery_dashboard.html", user=user, service=service, delivery_types=DELIVERY_TYPES, welcome_message=welcome_message)

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
    return render_template("delivery_service.html", services=rows, location=location, company=company)

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
    payment_text = quote(f"Hello Biz Hub, I want to upgrade my {session['username']} account to Premium Store.")
    upgrade_name = (user["company_name"] or user["username"]).strip()
    upgrade_price = "GH₵ 20 monthly" if user["role"] == "Delivery Service" else "the Premium Store plan"
    upgrade_message = f"hi biz hub, {user['username']} and {upgrade_name} wants to upgrade to {upgrade_price}. send account details."
    receipts = query_db("SELECT * FROM subscription_receipts WHERE user_id = ? ORDER BY id DESC", (user["id"],)) or []
    return render_template("subscription.html", user=user, subscription=subscription_status(user), receipts=receipts, payment_number=payment_number, payment_text=payment_text, upgrade_message=upgrade_message, requested=request.args.get("requested") == "1")

@app.route("/delivery/subscription")
def delivery_subscription():
    if "username" not in session or session.get("role") != "Delivery Service":
        return redirect(url_for("login"))
    user = query_db("SELECT * FROM users WHERE username = ?", (session["username"],), one=True)
    if not user:
        session.clear()
        return redirect(url_for("login"))
    payment_number = normalize_whatsapp_number(os.environ.get("BIZ_HUB_PAYMENT_WHATSAPP", "233558272972"))
    payment_text = quote(f"Hello Biz Hub, I want to upgrade my delivery service account {user['username']} to Premium Delivery for GH₵20 monthly.")
    upgrade_name = (user["company_name"] or user["username"]).strip()
    upgrade_message = f"Hello Biz Hub, {user['username']} from {upgrade_name} wants to subscribe to Premium Delivery for GH₵20 monthly."
    receipts = query_db("SELECT * FROM subscription_receipts WHERE user_id = ? ORDER BY id DESC", (user["id"],)) or []
    return render_template("delivery_subscription.html", user=user, subscription=subscription_status(user), receipts=receipts, payment_number=payment_number, payment_text=payment_text, upgrade_message=upgrade_message, requested=request.args.get("requested") == "1")

@app.route("/request-premium", methods=["POST"])
def request_premium():
    if "username" not in session or session.get("role") not in ["Vendor", "Fast Food", "Delivery Service"]:
        return redirect(url_for("login"))
    query_db("UPDATE users SET upgrade_requested_at = ? WHERE username = ?", (datetime.now(timezone.utc).isoformat(), session["username"]))
    return redirect(url_for("delivery_subscription" if session.get("role") == "Delivery Service" else "subscription", requested="1"))

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
    subscription_receipts = query_db("SELECT * FROM subscription_receipts ORDER BY id DESC") or []
    reports = query_db("SELECT r.*, u.username AS reporter_username FROM reports r JOIN users u ON u.id = r.reporter_id ORDER BY CASE WHEN r.status = 'Pending' THEN 0 ELSE 1 END, r.id DESC") or []
    verification_requests = query_db("SELECT vr.*, u.username, u.company_name, u.role FROM verification_requests vr JOIN users u ON u.id = vr.user_id ORDER BY CASE WHEN vr.status = 'Pending' THEN 0 ELSE 1 END, vr.id DESC") or []
    disputes = query_db("SELECT d.*, u.username AS reporter_username FROM disputes d JOIN users u ON u.id = d.reporter_id ORDER BY CASE WHEN d.status = 'Pending' THEN 0 ELSE 1 END, d.id DESC") or []
    admin_audit_logs = query_db("SELECT * FROM admin_audit_log ORDER BY id DESC LIMIT 100") or []
    
    total_rev_row = query_db("SELECT SUM(amount) AS total FROM financial_ledger WHERE status = 'Verified'", one=True)
    total_revenue = total_rev_row["total"] if total_rev_row and total_rev_row["total"] is not None else 0.0
    
    pending_momo_row = query_db("SELECT SUM(amount) AS total FROM financial_ledger WHERE status = 'Pending'", one=True)
    pending_momo = pending_momo_row["total"] if pending_momo_row and pending_momo_row["total"] is not None else 0.0
    
    verified_count_row = query_db("SELECT COUNT(*) AS count FROM financial_ledger WHERE status = 'Verified'", one=True)
    verified_count = verified_count_row["count"] if verified_count_row and verified_count_row["count"] is not None else 0
    
    return render_template("admin.html", users=users, subscription_status=subscription_status, listing_counts=listing_counts, ledger_entries=ledger_entries, subscription_receipts=subscription_receipts, reports=reports, verification_requests=verification_requests, disputes=disputes, admin_audit_logs=admin_audit_logs, total_revenue=total_revenue, pending_momo=pending_momo, verified_count=verified_count)

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
            query_db("UPDATE users SET account_status = COALESCE(account_status, 'Active') WHERE id = ?", (item["user_id"],))
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

@app.route("/admin/notify-all", methods=["POST"])
def notify_all_users():
    if not is_admin():
        return redirect(url_for("admin_login"))
    title = request.form.get("title", "").strip()
    message = request.form.get("message", "").strip()
    if title and message:
        users = query_db("SELECT id FROM users") or []
        for user in users:
            create_notification(user["id"], "announcement", title, message, url_for("notifications"))
    return redirect(url_for("admin_dashboard"))

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
    expiry = datetime.now(timezone.utc) + timedelta(days=30)
    query_db("UPDATE users SET plan = 'premium', subscription_expires_at = ?, upgrade_requested_at = NULL WHERE id = ? AND role IN ('Vendor', 'Fast Food', 'Delivery Service')", (expiry.isoformat(), user_id))
    query_db("UPDATE delivery_services SET availability = 'Unavailable', updated_at = ? WHERE user_id = ?", (datetime.now(timezone.utc).isoformat(), user_id))
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
        # Deduplicate submitted categories before writing to the UNIQUE(user_id, category) table.
        selected_categories = list(dict.fromkeys(
            category for category in request.form.getlist("vendor_categories")
            if category in VENDOR_CATEGORIES
        ))

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
        is_delivery_login = bool(request.form.get("delivery_login_user") is not None)
        username = request.form.get("login_user") if not is_delivery_login else request.form.get("delivery_login_user")
        password = request.form.get("login_pass") if not is_delivery_login else request.form.get("delivery_login_pass")
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
            return redirect(url_for("delivery_dashboard" if user["role"] == "Delivery Service" else "home"))
        if is_delivery_login:
            return render_template("login.html", delivery_login_error="Wrong delivery service username or password.")
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
        role_aliases = {"customer": "Customer", "vendor": "Vendor", "fast food": "Fast Food", "delivery service": "Delivery Service"}
        role = role_aliases.get(submitted_role.lower(), submitted_role)
        
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
            conn = sqlite3.connect(os.path.join(app.root_path, "marketplace.db"), timeout=60)
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
            session["theme"] = "day"
            session["welcome_message"] = True
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
    video_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if not os.path.exists(video_path):
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

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
