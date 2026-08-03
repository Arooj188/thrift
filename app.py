from dotenv import load_dotenv

load_dotenv()

import importlib
import json
import logging
import os
import secrets
import sqlite3
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from urllib.parse import quote
from ai_service import analyze_item
import firestore_db
from email_service import send_email, send_password_reset_email
from PIL import Image

RESET_TOKEN_EXPIRY_MINUTES = 60

# CLOUDINARY IMPORTS (optional for local development)

try:
    cloudinary = importlib.import_module('cloudinary')
    cloudinary_uploader = importlib.import_module('cloudinary.uploader')
    cloudinary.config(
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
        api_key=os.environ.get('CLOUDINARY_API_KEY'),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET')
    )
    CLOUDINARY_AVAILABLE = True
except Exception:
    cloudinary = None
    cloudinary_uploader = None
    CLOUDINARY_AVAILABLE = False

# ==========================================
# SECURE FIREBASE CONNECTION SYSTEM
# ==========================================


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_production_key_98765')
app.config.update({
    'SESSION_COOKIE_HTTPONLY': True,
    'SESSION_COOKIE_SAMESITE': os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax'),
    'SESSION_COOKIE_SECURE': os.environ.get('FLASK_ENV') == 'production' or os.environ.get('FORCE_SECURE_COOKIES') == '1',
})

# Use short permanent session lifetime by default; can be overridden via env
app.permanent_session_lifetime = timedelta(days=int(os.environ.get('SESSION_DAYS', '7')))

if app.secret_key == 'super_secret_production_key_98765':
    logging.warning('Using default SECRET_KEY. Set SECRET_KEY env var for production.')
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def build_image_url(image_value):
    if not image_value:
        return f"{app.static_url_path}/placeholder.svg"
    if isinstance(image_value, (list, tuple)):
        image_value = image_value[0] if image_value else ''
    if not isinstance(image_value, str):
        return f"{app.static_url_path}/placeholder.svg"

    value = image_value.strip()
    if not value:
        return f"{app.static_url_path}/placeholder.svg"

    if value.startswith('[') and value.endswith(']'):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                if not parsed:
                    return f"{app.static_url_path}/placeholder.svg"
                return build_image_url(parsed[0])
        except Exception:
            pass

    if value.startswith(('http://', 'https://', 'data:')):
        return value

    normalized = value.replace('\\', '/').lstrip('/')
    if normalized.startswith('static/'):
        normalized = normalized[len('static/'):]

    if normalized.startswith('uploads/'):
        return f"{app.static_url_path}/{normalized}"

    return f"{app.static_url_path}/{normalized}"


def has_product_image(image_url, images):
    """Check if a product has at least one actual image."""
    if image_url and image_url.strip():
        return True
    if images:
        images_str = str(images).strip()
        if images_str.startswith('[') and images_str.endswith(']'):
            try:
                parsed = json.loads(images_str)
                if isinstance(parsed, list) and parsed:
                    return True
            except Exception:
                pass
        elif images_str:
            return True
    return False


def format_sold_date(value):
    if not value:
        return ''
    try:
        dt = datetime.strptime(str(value)[:10], '%Y-%m-%d')
        return f"{dt.day} {dt.strftime('%B')} {dt.year}"
    except Exception:
        return value


app.jinja_env.globals['build_image_url'] = build_image_url
app.jinja_env.globals['has_product_image'] = has_product_image
app.jinja_env.filters['format_sold_date'] = format_sold_date


def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = dict_factory
    return conn

def schema_has_column(conn, table_name, column_name):
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    rows = cursor.fetchall()
    if not rows:
        return False
    return any(row.get('name') == column_name for row in rows)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT NOT NULL,
            email_verified INTEGER DEFAULT 0,
            phone_verified INTEGER DEFAULT 0,
            profile_picture TEXT DEFAULT '',
            seller_rating REAL DEFAULT 0.0,
            total_sales INTEGER DEFAULT 0,
            contact_preference TEXT DEFAULT 'whatsapp',
            contact_phone TEXT DEFAULT '',
            contact_email TEXT DEFAULT '',
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS Products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            brand TEXT,
            category TEXT,
            size TEXT,
            color TEXT,
            gender TEXT,
            asking_price REAL NOT NULL,
            status TEXT DEFAULT 'available',
            image_url TEXT,
            images TEXT DEFAULT '[]',
            description TEXT,
            tags TEXT,
            times_worn INTEGER,
            seller_condition TEXT,
            has_tears TEXT,
            seller_address TEXT,
            tracking_number TEXT,
            quality_score INTEGER,
            condition_summary TEXT,
            seller_id INTEGER,
            order_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (seller_id) REFERENCES users (user_id)
        )
    ''')
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            seller_id INTEGER NOT NULL,
            status TEXT DEFAULT 'Pending',
            order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            buyer_name TEXT,
            buyer_email TEXT,
            buyer_phone TEXT,
            buyer_street_address TEXT,
            buyer_city TEXT,
            buyer_province TEXT,
            buyer_postal_code TEXT,
            delivery_note TEXT,
            seller_amount REAL,
            platform_commission REAL,
            payout_status TEXT DEFAULT 'Pending',
            payout_date TEXT,
            payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES Products (id),
            FOREIGN KEY (buyer_id) REFERENCES users (user_id),
            FOREIGN KEY (seller_id) REFERENCES users (user_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            question_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES Products(id),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS answers (
            answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (question_id) REFERENCES questions(question_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total_users INTEGER DEFAULT 0,
            active_listings INTEGER DEFAULT 0,
            sold_items INTEGER DEFAULT 0,
            questions_asked INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('INSERT OR IGNORE INTO stats (id, total_users, active_listings, sold_items, questions_asked) VALUES (1, 0, 0, 0, 0)')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            email TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_password_resets_token ON password_resets(token)')

    try:
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_seller_id ON Products(seller_id)')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_buyer_id ON orders(buyer_id)')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_seller_id ON orders(seller_id)')
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()

def ensure_schema():
    conn = get_db_connection()
    cursor = conn.cursor()

    user_columns = [
        ("username", "TEXT"),
        ("email_verified", "INTEGER DEFAULT 0"),
        ("phone_verified", "INTEGER DEFAULT 0"),
        ("is_email_verified", "INTEGER DEFAULT 0"),
        ("is_phone_verified", "INTEGER DEFAULT 0"),
        ("street_address", "TEXT DEFAULT ''"),
        ("city", "TEXT DEFAULT ''"),
        ("province", "TEXT DEFAULT ''"),
        ("postal_code", "TEXT DEFAULT ''"),
        ("profile_picture", "TEXT DEFAULT ''"),
        ("bio", "TEXT DEFAULT ''"),
        ("join_date", "TEXT"),
        ("joined_date", "TEXT"),
        ("seller_rating", "REAL DEFAULT 0.0"),
        ("total_sales", "INTEGER DEFAULT 0"),
        ("is_admin", "INTEGER DEFAULT 0"),
        ("contact_preference", "TEXT DEFAULT 'whatsapp'"),
        ("contact_phone", "TEXT DEFAULT ''"),
        ("contact_email", "TEXT DEFAULT ''"),
    ]
    for column_name, definition in user_columns:
        if not schema_has_column(conn, 'users', column_name):
             try:
                 cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} {definition}")
             except Exception:
                 pass

    product_columns = [
        ("description", "TEXT"),
        ("images", "TEXT DEFAULT '[]'"),
        ("gender", "TEXT"),
        ("tags", "TEXT"),
        ("tracking_number", "TEXT"),
        ("created_at", "TEXT"),
        ("order_id", "INTEGER"),
        ("buyer_contact_method", "TEXT DEFAULT 'whatsapp'"),
        ("sold_date", "TEXT"),
    ]
    for column_name, definition in product_columns:
        if not schema_has_column(conn, 'Products', column_name):
            try:
                cursor.execute(f"ALTER TABLE Products ADD COLUMN {column_name} {definition}")
            except Exception:
                pass

    order_columns = [
        ("buyer_name", "TEXT"),
        ("tracking_number", "TEXT"),
        ("buyer_email", "TEXT"),
        ("buyer_phone", "TEXT"),
        ("buyer_street_address", "TEXT"),
        ("buyer_city", "TEXT"),
        ("buyer_province", "TEXT"),
        ("buyer_postal_code", "TEXT"),
        ("delivery_note", "TEXT"),
        ("seller_amount", "REAL"),
        ("platform_commission", "REAL"),
        ("order_total", "REAL"),
        ("payout_status", "TEXT DEFAULT 'Pending'"),
        ("payout_date", "TEXT"),
        ("payment_date", "TEXT"),
        ("shipping_company", "TEXT"),
        ("delivery_charges", "REAL DEFAULT 0"),
        ("payment_method", "TEXT DEFAULT ''"),
    ]
    if schema_has_column(conn, 'orders', 'order_id'):
        for column_name, definition in order_columns:
            if not schema_has_column(conn, 'orders', column_name):
                try:
                    cursor.execute(f"ALTER TABLE orders ADD COLUMN {column_name} {definition}")
                except Exception:
                    pass

    try:
        if schema_has_column(conn, 'users', 'username'):
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_seller_id ON Products(seller_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_buyer_id ON orders(buyer_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_seller_id ON orders(seller_id)')
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                order_id INTEGER,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (sender_id) REFERENCES users(user_id),
                FOREIGN KEY (receiver_id) REFERENCES users(user_id),
                FOREIGN KEY (order_id) REFERENCES orders(order_id)
            )
        ''')
    except Exception:
        pass

    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS password_resets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                used INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_password_resets_token ON password_resets(token)')
    except Exception:
        pass

    try:
        cursor.execute("UPDATE users SET contact_preference = 'whatsapp' WHERE contact_preference IS NULL")
    except Exception:
        pass
    try:
        cursor.execute("UPDATE users SET contact_phone = phone WHERE contact_phone IS NULL OR contact_phone = ''")
    except Exception:
        pass
    try:
        cursor.execute("UPDATE users SET contact_email = email WHERE contact_email IS NULL OR contact_email = ''")
    except Exception:
        pass

    conn.commit()
    conn.close()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg'}

def normalize_phone(raw_phone: str) -> str:
    if not raw_phone:
        return ''
    digits = ''.join(ch for ch in str(raw_phone) if ch.isdigit())
    if not digits:
        return ''
    if digits.startswith('0'):
        return '92' + digits[1:]
    return digits

def validate_email(email: str) -> bool:
    import re
    if not email or len(email) > 254:
        return False
    # basic email regex
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) is not None


def validate_username(username: str) -> bool:
    if not username:
        return True
    if len(username) > 32 or len(username) < 3:
        return False
    import re
    return re.match(r'^[A-Za-z0-9_.-]+$', username) is not None


def sanitize_input(s: str, max_len: int = 1024) -> str:
    if s is None:
        return ''
    s = s.strip()
    return s[:max_len]

def save_uploaded_images(files):
    saved_paths = []
    for image_file in files:
        if image_file and image_file.filename and allowed_file(image_file.filename):
            try:
                if CLOUDINARY_AVAILABLE and cloudinary_uploader:
                    upload_result = cloudinary_uploader.upload(image_file)
                    image_url = upload_result['secure_url']
                    saved_paths.append(image_url)
                    continue

                filename = secure_filename(image_file.filename)
                timestamp = int(datetime.utcnow().timestamp() * 1000)
                unique_name = f"{timestamp}_{filename}"
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)

                try:
                    image_file.seek(0)
                    img = Image.open(image_file)
                    img.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
                    if img.mode in ('RGBA', 'P'):
                        img = img.convert('RGB')
                    img.save(save_path, 'JPEG', quality=85, optimize=True)
                except Exception:
                    image_file.seek(0)
                    image_file.save(save_path)

                saved_paths.append(f"uploads/{unique_name}")
            except Exception as e:
                logging.error(f"Image upload error: {e}")
                continue
    return saved_paths



def get_product_by_id(product_id):
    if firestore_db.is_firestore_available():
        product = firestore_db.fs_get_product(product_id)
        if product:
            return product
    conn = get_db_connection()
    cursor = conn.cursor()
    product = cursor.execute("SELECT * FROM Products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    return dict(product) if product else None


def get_products_from_firestore(category=None):
    if firestore_db.is_firestore_available():
        return firestore_db.fs_get_all_products(category=category)
    conn = get_db_connection()
    cursor = conn.cursor()
    if category:
        cursor.execute("SELECT * FROM Products WHERE status = 'available' AND category = ?", (category,))
    else:
        cursor.execute("SELECT * FROM Products WHERE status = 'available'")
    products = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return products


def get_single_product_from_firestore(product_id):
    if firestore_db.is_firestore_available():
        product = firestore_db.fs_get_product(product_id)
        if product:
            return product
    return get_product_by_id(product_id)


# ============================
# Password reset helpers
# ============================

def validate_password(password: str) -> bool:
    if not password or len(password) < 8:
        return False
    return password.strip() != ''


def get_user_by_email(email):
    if firestore_db.is_firestore_available():
        user = firestore_db.fs_get_user_by_email(email)
        if user:
            return user
    conn = get_db_connection()
    cursor = conn.cursor()
    user = cursor.execute('SELECT * FROM users WHERE lower(email) = lower(?)', (email,)).fetchone()
    conn.close()
    return dict(user) if user else None


def create_password_reset(user, email, token, expires_at, created_at=None):
    if created_at is None:
        created_at = datetime.utcnow()
    if firestore_db.is_firestore_available():
        result = firestore_db.fs_create_password_reset({
            'token': token,
            'user_id': user['user_id'],
            'email': email,
            'created_at': created_at.isoformat(),
            'expires_at': expires_at.isoformat(),
            'used': False,
        })
        return result == token
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO password_resets (token, user_id, email, created_at, expires_at, used) VALUES (?, ?, ?, ?, ?, 0)',
        (token, user['user_id'], email, created_at.isoformat(), expires_at.isoformat()),
    )
    conn.commit()
    conn.close()
    return True


def verify_password_reset_token(token):
    if not token:
        return None
    reset = None
    if firestore_db.is_firestore_available():
        reset = firestore_db.fs_get_password_reset(token)
    else:
        conn = get_db_connection()
        cursor = conn.cursor()
        row = cursor.execute('SELECT * FROM password_resets WHERE token = ?', (token,)).fetchone()
        conn.close()
        reset = dict(row) if row else None
    if not reset:
        return None
    if reset.get('used'):
        return None
    expires_at = reset.get('expires_at')
    if not expires_at:
        return None
    try:
        if hasattr(expires_at, 'isoformat'):
            exp_dt = expires_at
        else:
            exp_dt = datetime.fromisoformat(str(expires_at))
        if datetime.utcnow() > exp_dt:
            return None
    except Exception:
        return None
    return reset


def update_user_password(user_id, password_hash):
    if firestore_db.is_firestore_available():
        return firestore_db.fs_update_user(user_id, {'password': password_hash})
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET password = ? WHERE user_id = ?', (password_hash, user_id))
    updated = cursor.rowcount
    conn.commit()
    conn.close()
    return updated > 0


def invalidate_password_reset(token):
    if firestore_db.is_firestore_available():
        return firestore_db.fs_invalidate_password_reset(token)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE password_resets SET used = 1 WHERE token = ?', (token,))
    conn.commit()
    conn.close()
    return True


def is_truthy_field(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'y', 'on')
    return False


def user_has_admin_privilege(user):
    if not user:
        return False
    if is_truthy_field(user.get('is_admin')):
        return True
    if is_truthy_field(user.get('admin')):
        return True
    role_value = user.get('role') or user.get('user_role') or user.get('access_level')
    if isinstance(role_value, str) and role_value.strip().lower() in ('admin', 'administrator', 'superadmin', 'owner'):
        return True
    return False


def is_admin_user():
    if 'user_id' not in session:
        return False
    user = None
    if firestore_db.is_firestore_available():
        user = firestore_db.fs_get_user(session['user_id'])
        if user:
            try:
                if user_has_admin_privilege(user):
                    return True
            except Exception:
                pass
            admin_email = os.environ.get('ADMIN_EMAIL')
            if admin_email and user.get('email') and user.get('email').lower() == admin_email.lower():
                return True
            return False
    conn = get_db_connection()
    cursor = conn.cursor()
    user = cursor.execute('SELECT * FROM users WHERE user_id = ?', (session['user_id'],)).fetchone()
    conn.close()
    if not user:
        return False
    try:
        if user_has_admin_privilege(user):
            return True
    except Exception:
        pass
    admin_email = os.environ.get('ADMIN_EMAIL')
    if admin_email and user.get('email') and user.get('email').lower() == admin_email.lower():
        return True
    return False


def require_admin():
    if 'user_id' not in session:
        flash('Admin login required.', 'error')
        return redirect(url_for('login'))
    if not is_admin_user():
        flash('Access denied.', 'error')
        return redirect(url_for('index'))
    return None

try:
    init_db()
    ensure_schema()
except Exception as e:
    logging.error(f"Database initialization status: {e}")

@app.before_request
def ensure_cart_exists():
    if 'cart' not in session:
        session['cart'] = []

@app.route('/')
def index():
    category = request.args.get('category')
    products = get_products_from_firestore(category=category)
    safe_products = []
    for p in products:
        safe = {}
        for k, v in p.items():
            if hasattr(v, 'isoformat'):
                safe[k] = v.isoformat()
            else:
                safe[k] = v
        safe_products.append(safe)
    stats = get_marketplace_stats()
    return render_template('index.html', products=safe_products, selected_category=category or '', stats=stats)

@app.route('/how-it-works')
def how_it_works():
    return render_template('how_it_works.html')

@app.route('/product/<product_id>')
def product_details(product_id):
    product = get_single_product_from_firestore(product_id)
    if not product:
        flash("Product not found!")
        return redirect(url_for('index'))
    if product.get('status') == 'sold':
        flash('This item has been sold and is no longer available.')
        return redirect(url_for('index'))
    image_list = []
    if product.get('images'):
        try:
            image_list = json.loads(product['images']) if isinstance(product['images'], str) else product['images']
        except Exception:
            image_list = [product['images']] if product.get('image_url') else []
    elif product.get('image_url'):
        image_list = [product['image_url']]

    questions = []
    if firestore_db.is_firestore_available():
        questions = firestore_db.fs_get_questions_by_product(product_id)
        for q in questions:
            q['answers'] = firestore_db.fs_get_answers_by_question(q.get('question_id'))
            asker = firestore_db.fs_get_user(q.get('user_id'))
            q['asker'] = asker.get('name') if asker else 'Anonymous'
            for a in q['answers']:
                answerer = firestore_db.fs_get_user(a.get('user_id'))
                a['answerer'] = answerer.get('name') if answerer else 'Seller'
    else:
        conn = get_db_connection()
        cur = conn.cursor()
        rows = cur.execute('SELECT q.question_id, q.content, q.created_at, u.name as asker FROM questions q LEFT JOIN users u ON q.user_id = u.user_id WHERE q.product_id = ? ORDER BY q.created_at ASC', (product_id,)).fetchall()
        questions = [dict(r) for r in rows]
        for q in questions:
            qrows = cur.execute('SELECT a.answer_id, a.content, a.created_at, u.name as answerer FROM answers a LEFT JOIN users u ON a.user_id = u.user_id WHERE a.question_id = ? ORDER BY a.created_at ASC', (q['question_id'],)).fetchall()
            q['answers'] = [dict(ar) for ar in qrows]
        conn.close()

    seller_phone = ''
    seller_email = ''
    seller_contact_preference = 'whatsapp'
    seller_id = product.get('seller_id')
    if seller_id:
        seller = firestore_db.fs_get_user(seller_id)
        if seller:
            seller_phone = normalize_phone(seller.get('contact_phone', '') or seller.get('phone', ''))
            seller_email = (seller.get('contact_email', '') or seller.get('email', '') or '').strip()
            seller_contact_preference = seller.get('contact_preference', 'whatsapp') or 'whatsapp'
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            seller_row = cursor.execute('SELECT phone, email, contact_preference, contact_phone, contact_email FROM users WHERE user_id = ?', (seller_id,)).fetchone()
            conn.close()
            if seller_row:
                seller_phone = normalize_phone(seller_row.get('contact_phone', '') or seller_row.get('phone', ''))
                seller_email = (seller_row.get('contact_email', '') or seller_row.get('email', '') or '').strip()
                seller_contact_preference = seller_row.get('contact_preference', 'whatsapp') or 'whatsapp'

    listing_contact_method = product.get('buyer_contact_method') or seller_contact_preference

    whatsapp_url = ''
    gmail_url = ''
    mailto_url = ''
    if product.get('title'):
        if seller_phone and listing_contact_method == 'whatsapp':
            text = f"Hi! I came across your listing for \"{product['title']}\" on Thrift. Is it still available?"
            whatsapp_url = f"https://wa.me/{seller_phone}?text={quote(text)}"
        elif seller_email and listing_contact_method == 'email':
            subject = f"Interest in {product['title']}"
            body = f"Hi! I came across your listing for \"{product['title']}\" on Thrift. Is it still available?"
            gmail_url = f"https://mail.google.com/mail/?view=cm&fs=1&to={quote(seller_email)}&su={quote(subject)}&body={quote(body)}"
            mailto_url = f"mailto:{seller_email}?subject={quote(subject)}&body={quote(body)}"

    return render_template('product_details.html', product=product, image_list=image_list, questions=questions, seller_phone=seller_phone, seller_email=seller_email, seller_contact_preference=listing_contact_method, whatsapp_url=whatsapp_url, gmail_url=gmail_url, mailto_url=mailto_url)

@app.route('/sell', methods=['GET', 'POST'])
def sell():
    if 'user_id' not in session:
        flash('Please log in or create an account first to start selling your pre-loved items.')
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form['title'].strip()
        brand = request.form['brand'].strip()
        category = request.form['category']
        size = request.form['size'].strip()
        color = request.form['color'].strip()
        gender = request.form.get('gender', '').strip()
        tags = request.form.get('tags', '').strip()
        description = request.form.get('description', '').strip()
        times_worn = request.form['times_worn']
        has_tears = request.form['has_tears']
        seller_condition = request.form['seller_condition'].strip()
        seller_city = request.form.get('seller_city', '').strip()
        seller_locality = request.form.get('seller_locality', '').strip()
        if seller_locality:
            seller_address = f"{seller_locality}, {seller_city}"
        else:
            seller_address = seller_city
        asking_price = float(request.form['asking_price'])
        buyer_contact_method = request.form.get('buyer_contact_method', 'whatsapp')
        if buyer_contact_method not in ('whatsapp', 'email'):
            buyer_contact_method = 'whatsapp'
        image_files = request.files.getlist('images') or []
        if not image_files:
            self_image = request.files.get('image')
            if self_image:
                image_files = [self_image]

        image_paths = save_uploaded_images(image_files)
        image_url = image_paths[0] if image_paths else ''
        images_json = json.dumps(image_paths)

        conn = get_db_connection()
        cursor = conn.cursor()
        raw = cursor.execute('SELECT title, description FROM Products').fetchall()
        existing_rows = [{'title': row['title'], 'description': row['description']} for row in raw]

        ai_result = analyze_item(category, times_worn, has_tears, description, tags, title=title, existing_listings=existing_rows)
        condition_summary = ai_result.get('summary')
        auto_category = ai_result.get('category')
        duplicate = ai_result.get('duplicate', False)
        if auto_category and auto_category != category:
            category = auto_category
        if duplicate:
            flash('Warning: this listing appears similar to another item already on the marketplace.')

        product_data = {
            'title': title,
            'brand': brand,
            'category': category,
            'size': size,
            'color': color,
            'gender': gender,
            'asking_price': asking_price,
            'image_url': image_url,
            'images': image_paths,
            'description': description,
            'tags': tags,
            'times_worn': int(times_worn),
            'seller_condition': seller_condition,
            'has_tears': has_tears,
            'seller_address': seller_address,
            'condition_summary': condition_summary,
            'seller_id': session['user_id'],
            'status': 'available',
            'buyer_contact_method': buyer_contact_method,
        }

        if firestore_db.is_firestore_available():
            product_id = firestore_db.fs_create_product(product_data)
        else:
            cursor.execute('''
                INSERT INTO Products (title, brand, category, size, color, gender, asking_price, image_url, images, description, tags, times_worn, seller_condition, has_tears, seller_address, condition_summary, seller_id, buyer_contact_method)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (title, brand, category, size, color, gender, asking_price, image_url, images_json, description, tags, int(times_worn), seller_condition, has_tears, seller_address, condition_summary, session['user_id'], buyer_contact_method))
            product_id = cursor.lastrowid
            conn.commit()
            conn.close()

        flash('Your thrift item has been successfully listed!')
        return redirect(url_for('seller_listings'))

    return render_template('sell.html')


@app.route('/seller/listings')
def seller_listings():
    if 'user_id' not in session:
        flash('Please log in to manage your listings.')
        return redirect(url_for('login'))

    if firestore_db.is_firestore_available():
        listings = firestore_db.fs_get_products_by_seller(session['user_id'])
    else:
        conn = get_db_connection()
        cursor = conn.cursor()
        listings = cursor.execute('SELECT * FROM Products WHERE seller_id = ?', (session['user_id'],)).fetchall()
        conn.close()
    total_sold = sum(1 for listing in listings if listing.get('status') == 'sold')
    stats = get_marketplace_stats()
    return render_template('seller_listings.html', listings=listings, stats=stats, total_sold=total_sold)


def get_marketplace_stats():
    stats = {
        'total_users': 0,
        'active_listings': 0,
        'sold_items': 0,
        'questions_asked': 0,
    }
    if firestore_db.is_firestore_available():
        firestore_stats = firestore_db.fs_get_stats()
        if firestore_stats:
            stats['total_users'] = firestore_stats.get('total_users', 0)
            stats['active_listings'] = firestore_stats.get('active_listings', 0)
            stats['sold_items'] = firestore_stats.get('sold_items', 0)
            stats['questions_asked'] = firestore_stats.get('questions_asked', 0)
            return stats
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        total_row = cursor.execute('SELECT COUNT(*) FROM users').fetchone()
        stats['total_users'] = total_row.get('COUNT(*)', 0) if total_row else 0
        active_row = cursor.execute("SELECT COUNT(*) FROM Products WHERE status = 'available'").fetchone()
        stats['active_listings'] = active_row.get('COUNT(*)', 0) if active_row else 0
        sold_row = cursor.execute("SELECT COUNT(*) FROM Products WHERE status = 'sold'").fetchone()
        stats['sold_items'] = sold_row.get('COUNT(*)', 0) if sold_row else 0
        questions_row = cursor.execute('SELECT COUNT(*) FROM questions').fetchone()
        stats['questions_asked'] = questions_row.get('COUNT(*)', 0) if questions_row else 0
    except Exception:
        pass
    conn.close()
    return stats


@app.route('/listing/<product_id>/mark-sold', methods=['POST'])
def mark_sold(product_id):
    if 'user_id' not in session:
        flash('Please log in to manage your listings.')
        return redirect(url_for('login'))

    product = get_product_by_id(product_id)
    if not product or product.get('seller_id') != session['user_id']:
        flash('Unable to update the listing.')
        return redirect(url_for('seller_listings'))

    if product.get('status') == 'sold':
        flash('This item is already marked as sold.')
        return redirect(url_for('seller_listings'))

    now = datetime.now().isoformat()
    if firestore_db.is_firestore_available():
        firestore_db.fs_update_product(product_id, {
            'status': 'sold',
            'sold_date': now,
        })
        firestore_db.fs_increment_stat('sold_items', 1)
    else:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE Products SET status = 'sold', sold_date = ? WHERE id = ?", (now, product_id))
        cursor.execute('UPDATE stats SET sold_items = sold_items + 1 WHERE id = 1')
        conn.commit()

    flash('Listing marked as sold.')
    return redirect(url_for('seller_listings'))


@app.route('/listing/<product_id>/delete', methods=['POST'])
def delete_listing(product_id):
    if 'user_id' not in session:
        flash('Please log in to delete your listing.')
        return redirect(url_for('login'))

    product = get_product_by_id(product_id)
    if not product or product.get('seller_id') != session['user_id']:
        flash('Unable to delete the listing.')
        return redirect(url_for('seller_listings'))

    was_sold = product.get('status') == 'sold'

    if firestore_db.is_firestore_available():
        firestore_db.fs_delete_product(product_id)
        if was_sold:
            firestore_db.fs_increment_stat('sold_items', -1)
    else:
        conn = get_db_connection()
        cursor = conn.cursor()
        if was_sold:
            cursor.execute('UPDATE stats SET sold_items = sold_items - 1 WHERE id = 1')
        cursor.execute('DELETE FROM Products WHERE id = ?', (product_id,))
        conn.commit()
        conn.close()

    # attempt to remove local image files if present
    try:
        images = []
        if product.get('images'):
            try:
                images = json.loads(product['images']) if isinstance(product['images'], str) else product['images']
            except Exception:
                images = [product['images']]
        if product.get('image_url') and not images:
            images = [product['image_url']]
        for img in images:
            if img and isinstance(img, str) and not img.startswith('http') and not img.startswith('data:'):
                # normalize and remove leading static/ if present
                path = img.replace('\\', '/').lstrip('/')
                if path.startswith('static/'):
                    path = path[len('static/'):]
                full = os.path.join(app.root_path, 'static', path)
                try:
                    if os.path.exists(full):
                        os.remove(full)
                except Exception:
                    pass
    except Exception:
        pass

    flash('Listing deleted successfully.')
    return redirect(url_for('seller_listings'))


@app.route('/listing/<product_id>/edit', methods=['GET', 'POST'])
def edit_listing(product_id):
    if 'user_id' not in session:
        flash('Please log in to edit your listing.')
        return redirect(url_for('login'))

    product = get_product_by_id(product_id)
    if not product or product['seller_id'] != session['user_id']:
        flash('Listing not found or you do not have permission to edit it.')
        return redirect(url_for('seller_listings'))
    if product.get('status') == 'sold':
        flash('Sold listings cannot be edited.')
        return redirect(url_for('seller_listings'))

    seller_address = product.get('seller_address', '') or ''
    parts = [p.strip() for p in seller_address.split(',')]
    seller_city = parts[0] if parts else ''
    seller_locality = ''
    if len(parts) >= 2:
        seller_locality = parts[0]
        seller_city = parts[1]

    product_images = []
    if product.get('images'):
        try:
            product_images = json.loads(product['images']) if isinstance(product['images'], str) else product['images']
        except Exception:
            product_images = [product['images']] if product.get('image_url') else []
    elif product.get('image_url'):
        product_images = [product['image_url']]

    if request.method == 'POST':
        title = request.form['title'].strip()
        brand = request.form['brand'].strip()
        category = request.form['category']
        size = request.form['size'].strip()
        color = request.form['color'].strip()
        gender = request.form.get('gender', '').strip()
        tags = request.form.get('tags', '').strip()
        description = request.form.get('description', '').strip()
        times_worn = request.form['times_worn']
        has_tears = request.form['has_tears']
        seller_condition = request.form['seller_condition'].strip()
        seller_city = request.form.get('seller_city', '').strip()
        seller_locality = request.form.get('seller_locality', '').strip()
        if seller_locality:
            seller_address = f"{seller_locality}, {seller_city}"
        else:
            seller_address = seller_city
        asking_price = float(request.form['asking_price'])
        buyer_contact_method = request.form.get('buyer_contact_method', 'whatsapp')
        if buyer_contact_method not in ('whatsapp', 'email'):
            buyer_contact_method = 'whatsapp'
        image_files = request.files.getlist('images')

        image_paths = save_uploaded_images(image_files)
        existing_images = []
        if product.get('images'):
            try:
                existing_images = json.loads(product['images']) if isinstance(product['images'], str) else product['images']
            except Exception:
                existing_images = [product['images']] if product.get('image_url') else []
        elif product.get('image_url'):
            existing_images = [product['image_url']]
        new_images = existing_images + image_paths
        images_json = json.dumps(new_images)
        image_url = image_paths[0] if image_paths else product.get('image_url', '')

        condition_summary = product.get('condition_summary', '')

        product_data = {
            'title': title,
            'brand': brand,
            'category': category,
            'size': size,
            'color': color,
            'gender': gender,
            'asking_price': asking_price,
            'image_url': image_url,
            'images': new_images,
            'description': description,
            'tags': tags,
            'times_worn': int(times_worn),
            'seller_condition': seller_condition,
            'has_tears': has_tears,
            'seller_address': seller_address,
            'condition_summary': condition_summary,
            'seller_id': session['user_id'],
            'status': product.get('status', 'available'),
            'buyer_contact_method': buyer_contact_method,
        }

        if firestore_db.is_firestore_available():
            firestore_db.fs_update_product(product_id, product_data)
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE Products SET title=?, brand=?, category=?, size=?, color=?, gender=?, asking_price=?,
                    image_url=?, images=?, description=?, tags=?, times_worn=?, seller_condition=?,
                    has_tears=?, seller_address=?, condition_summary=?, buyer_contact_method=?
                WHERE id=?
            ''', (title, brand, category, size, color, gender, asking_price, image_url, images_json, description, tags, int(times_worn), seller_condition, has_tears, seller_address, condition_summary, buyer_contact_method, product_id))
            conn.commit()
            conn.close()

        flash('Listing updated successfully.')
        return redirect(url_for('seller_listings'))

    return render_template('edit_listing.html', product=product, seller_city=seller_city, seller_locality=seller_locality, product_images=product_images)


@app.route('/account', methods=['GET', 'POST'])
def account_settings():
    if 'user_id' not in session:
        flash('Please log in to update your account settings.')
        return redirect(url_for('login'))

    user = firestore_db.fs_get_user(session['user_id'])
    if not user:
        conn = get_db_connection()
        cursor = conn.cursor()
        user = cursor.execute('SELECT name, email, phone, contact_preference, contact_phone, contact_email FROM users WHERE user_id = ?', (session['user_id'],)).fetchone()
        conn.close()
    if not user:
        flash('Account not found.')
        return redirect(url_for('index'))

    user = dict(user)
    contact_preference = user.get('contact_preference', 'whatsapp') or 'whatsapp'
    contact_phone = user.get('contact_phone', '') or user.get('phone', '')
    contact_email = user.get('contact_email', '') or user.get('email', '')

    if request.method == 'POST':
        contact_preference = request.form.get('contact_preference', 'whatsapp')
        if contact_preference not in ('whatsapp', 'email'):
            contact_preference = 'whatsapp'

        contact_phone = sanitize_input(request.form.get('contact_phone', ''))
        contact_email = sanitize_input(request.form.get('contact_email', '')).lower()

        phone_error = ''
        email_error = ''
        general_error = ''

        if contact_preference == 'whatsapp':
            if not contact_phone:
                phone_error = 'Phone number is required for WhatsApp contact.'
        elif contact_preference == 'email':
            if not contact_email:
                email_error = 'Email address is required for email contact.'
            elif not validate_email(contact_email):
                email_error = 'Please provide a valid email address.'

        if not any([phone_error, email_error, general_error]):
            update_data = {
                'contact_preference': contact_preference,
                'contact_phone': contact_phone,
                'contact_email': contact_email,
            }
            if firestore_db.is_firestore_available():
                firestore_db.fs_update_user(session['user_id'], update_data)
            else:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('UPDATE users SET contact_preference = ?, contact_phone = ?, contact_email = ? WHERE user_id = ?',
                    (contact_preference, contact_phone, contact_email, session['user_id']))
                conn.commit()
                conn.close()

            flash('Contact preferences updated successfully.')
            return redirect(url_for('account_settings'))

    else:
        phone_error = ''
        email_error = ''
        general_error = ''

    return render_template('account_settings.html', user=user, contact_preference=contact_preference, contact_phone=contact_phone, contact_email=contact_email, phone_error=phone_error, email_error=email_error, general_error=general_error)


@app.route('/admin')
def admin_dashboard():
    guard = require_admin()
    if guard is not None:
        return guard

    section = request.args.get('section', 'listings')
    user_search = (request.args.get('user_search') or '').strip()
    listing_search = (request.args.get('listing_search') or '').strip()
    listing_status = request.args.get('listing_status', 'all')
    if section == 'sold':
        listing_status = 'sold'

    stats = {
        'total_users': 0,
        'active_listings': 0,
        'sold_items': 0,
        'questions_asked': 0,
    }

    listings = []
    users = []
    listing_counts = {}
    backend = 'none'

    if firestore_db.is_firestore_available():
        try:
            db = firestore_db.get_firestore_db()
            if db is not None:
                listings_ref = db.collection('Products').order_by('created_at', direction='DESCENDING')
                listings_query = listings_ref
                if listing_status == 'available':
                    listings_query = listings_ref.where('status', '==', 'available')
                elif listing_status == 'sold':
                    listings_query = listings_ref.where('status', '==', 'sold')
                for doc in listings_query.stream():
                    p = doc.to_dict()
                    p['id'] = int(doc.id) if doc.id.isdigit() else doc.id
                    if listing_search:
                        title = (p.get('title') or '').lower()
                        if listing_search.lower() not in title:
                            continue
                    listings.append(p)

                users_query = db.collection('users').order_by('join_date', direction='DESCENDING')
                for doc in users_query.stream():
                    u = doc.to_dict()
                    u['user_id'] = int(doc.id) if doc.id.isdigit() else doc.id
                    if user_search:
                        name = (u.get('name') or '').lower()
                        email = (u.get('email') or '').lower()
                        if user_search.lower() not in name and user_search.lower() not in email:
                            continue
                    users.append(u)

                seller_counts = {}
                for p in listings:
                    sid = p.get('seller_id')
                    if sid:
                        seller_counts[sid] = seller_counts.get(sid, 0) + 1
                listing_counts = seller_counts

                users_count_snapshot = db.collection('users').count().get()
                stats['total_users'] = users_count_snapshot[0].value if users_count_snapshot else 0
                active_snapshot = db.collection('Products').where('status', '==', 'available').count().get()
                stats['active_listings'] = active_snapshot[0].value if active_snapshot else 0
                sold_snapshot = db.collection('Products').where('status', '==', 'sold').count().get()
                stats['sold_items'] = sold_snapshot[0].value if sold_snapshot else 0
                questions_snapshot = db.collection('questions').count().get()
                stats['questions_asked'] = questions_snapshot[0].value if questions_snapshot else 0

                backend = 'firestore'
        except Exception as e:
            logging.error(f"Admin dashboard Firestore error: {e}")
            backend = 'error'

    if backend == 'error' or not firestore_db.is_firestore_available() or (backend == 'firestore' and not listings):
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            if user_search:
                users = [dict(row) for row in cursor.execute(
                    'SELECT * FROM users WHERE lower(name) LIKE ? OR lower(email) LIKE ? ORDER BY join_date DESC',
                    (f'%{user_search.lower()}%', f'%{user_search.lower()}%')
                ).fetchall()]
            else:
                users = [dict(row) for row in cursor.execute('SELECT * FROM users ORDER BY join_date DESC').fetchall()]

            if listing_status == 'available':
                listings = [dict(row) for row in cursor.execute("SELECT * FROM Products WHERE status = 'available' ORDER BY created_at DESC").fetchall()]
            elif listing_status == 'sold':
                listings = [dict(row) for row in cursor.execute("SELECT * FROM Products WHERE status = 'sold' ORDER BY created_at DESC").fetchall()]
            else:
                listings = [dict(row) for row in cursor.execute('SELECT * FROM Products ORDER BY created_at DESC').fetchall()]
            if listing_search:
                listings = [l for l in listings if listing_search.lower() in (l.get('title') or '').lower()]

            listing_counts_rows = cursor.execute('SELECT seller_id, COUNT(*) as cnt FROM Products GROUP BY seller_id').fetchall()
            listing_counts = {row['seller_id']: row['cnt'] for row in listing_counts_rows}

            stats['total_users'] = cursor.execute('SELECT COUNT(*) AS total_users FROM users').fetchone()['total_users']
            stats['active_listings'] = cursor.execute("SELECT COUNT(*) AS active_listings FROM Products WHERE status = 'available'").fetchone()['active_listings']
            stats['sold_items'] = cursor.execute("SELECT COUNT(*) AS sold_items FROM Products WHERE status = 'sold'").fetchone()['sold_items']
            stats['questions_asked'] = cursor.execute('SELECT COUNT(*) AS questions_asked FROM questions').fetchone()['questions_asked']
            backend = 'sqlite'
        except Exception as e:
            logging.error(f"Admin dashboard SQLite error: {e}")
            flash('Error loading dashboard data.', 'error')
        conn.close()

    viewing_sold = section == 'sold' or listing_status == 'sold'
    return render_template('admin_dashboard.html',
        section=section,
        listings=listings,
        users=users,
        listing_counts=listing_counts,
        current_admin_id=session.get('user_id'),
        stats=stats,
        user_search=user_search,
        listing_search=listing_search,
        listing_status=listing_status,
        viewing_sold=viewing_sold,
    )

@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
def admin_delete_user(user_id):
    guard = require_admin()
    if guard is not None:
        return guard

    current_admin_id = session.get('user_id')
    if user_id == current_admin_id:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('admin_dashboard', section='users'))

    if firestore_db.is_firestore_available():
        try:
            db = firestore_db.get_firestore_db()
            user_doc = db.collection('users').document(str(user_id))
            user_doc.delete()

            products_query = db.collection('Products').where('seller_id', '==', user_id).stream()
            for doc in products_query:
                doc.reference.delete()

            questions_query = db.collection('questions').where('user_id', '==', user_id).stream()
            for doc in questions_query:
                doc.reference.delete()

            answers_query = db.collection('answers').where('user_id', '==', user_id).stream()
            for doc in answers_query:
                doc.reference.delete()

            orders_query = db.collection('orders').where('buyer_id', '==', user_id).stream()
            for doc in orders_query:
                doc.reference.delete()
            orders_query = db.collection('orders').where('seller_id', '==', user_id).stream()
            for doc in orders_query:
                doc.reference.delete()

            firestore_db.fs_increment_stat('total_users', -1)
        except Exception:
            pass
    else:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM answers WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM questions WHERE user_id = ?', (user_id,))
        cursor.execute('DELETE FROM Products WHERE seller_id = ?', (user_id,))
        cursor.execute('DELETE FROM orders WHERE buyer_id = ? OR seller_id = ?', (user_id, user_id))
        cursor.execute('UPDATE stats SET total_users = total_users - 1 WHERE id = 1')
        cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()

    flash('User deleted successfully.')
    return redirect(url_for('admin_dashboard', section='users'))

@app.route('/admin/listing/<product_id>/delete', methods=['POST'])
def admin_delete_listing(product_id):
    guard = require_admin()
    if guard is not None:
        return guard
    product = get_product_by_id(product_id)
    if not product:
        flash('Listing not found.')
        return redirect(url_for('admin_dashboard', section='listings'))
    was_sold = product.get('status') == 'sold'
    if firestore_db.is_firestore_available():
        firestore_db.fs_delete_product(product_id)
        if was_sold:
            firestore_db.fs_increment_stat('sold_items', -1)
    else:
        conn = get_db_connection()
        cursor = conn.cursor()
        if was_sold:
            cursor.execute('UPDATE stats SET sold_items = sold_items - 1 WHERE id = 1')
        cursor.execute('DELETE FROM Products WHERE id = ?', (product_id,))
        conn.commit()
        conn.close()

    try:
        images = []
        if product.get('images'):
            try:
                images = json.loads(product['images']) if isinstance(product['images'], str) else product['images']
            except Exception:
                images = [product['images']]
        if product.get('image_url') and not images:
            images = [product['image_url']]
        for img in images:
            if img and isinstance(img, str) and not img.startswith('http') and not img.startswith('data:'):
                path = img.replace('\\', '/').lstrip('/')
                if path.startswith('static/'):
                    path = path[len('static/'):]
                full = os.path.join(app.root_path, 'static', path)
                try:
                    if os.path.exists(full):
                        os.remove(full)
                except Exception:
                    pass
    except Exception:
        pass

    flash('Listing removed.')
    return redirect(url_for('admin_dashboard', section='listings'))


@app.route('/messages')
def messages_page():
    if 'user_id' not in session:
        flash('Please log in to view messages.')
        return redirect(url_for('login'))
    if firestore_db.is_firestore_available():
        messages = firestore_db.fs_get_all_messages()
    else:
        conn = get_db_connection()
        cursor = conn.cursor()
        messages = cursor.execute('SELECT * FROM messages').fetchall()
        conn.close()
    return render_template('messages.html', messages=messages)

@app.route('/admin-portal')
def admin_portal():
    guard = require_admin()
    if guard is not None:
        return guard
    return redirect(url_for('admin_dashboard', section='listings'))

@app.route('/admin/users')
def admin_users():
    guard = require_admin()
    if guard is not None:
        return guard
    return redirect(url_for('admin_dashboard', section='users'))

@app.route('/admin/orders')
def admin_orders():
    guard = require_admin()
    if guard is not None:
        return guard
    return redirect(url_for('admin_dashboard', section='orders'))

@app.route('/product/<product_id>/question', methods=['POST'])
def post_question(product_id):
    if 'user_id' not in session:
        flash('Please log in to ask questions.')
        return redirect(url_for('login'))
    content = sanitize_input(request.form.get('question_content', ''))
    if not content:
        flash('Please provide a question.')
        return redirect(url_for('product_details', product_id=product_id))
    question_data = {
        'product_id': product_id,
        'user_id': session['user_id'],
        'content': content,
        'created_at': datetime.utcnow().isoformat(),
    }
    if firestore_db.is_firestore_available():
        firestore_db.fs_create_question(question_data)
    else:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO questions (product_id, user_id, content) VALUES (?, ?, ?)', (product_id, session['user_id'], content))
        conn.commit()
        conn.close()
    flash('Your question has been posted publicly.')
    return redirect(url_for('product_details', product_id=product_id))


@app.route('/product/<product_id>/answer/<question_id>', methods=['POST'])
def post_answer(product_id, question_id):
    if 'user_id' not in session:
        flash('Please log in to answer questions.')
        return redirect(url_for('login'))
    product = get_product_by_id(product_id)
    if not product or product.get('seller_id') != session['user_id']:
        flash('Only the seller can answer questions on this product.')
        return redirect(url_for('product_details', product_id=product_id))
    content = sanitize_input(request.form.get('answer_content', ''))
    if not content:
        flash('Please provide an answer.')
        return redirect(url_for('product_details', product_id=product_id))
    answer_data = {
        'question_id': question_id,
        'user_id': session['user_id'],
        'content': content,
        'created_at': datetime.utcnow().isoformat(),
    }
    if firestore_db.is_firestore_available():
        firestore_db.fs_create_answer(answer_data)
    else:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('INSERT INTO answers (question_id, user_id, content) VALUES (?, ?, ?)', (question_id, session['user_id'], content))
        conn.commit()
        conn.close()
    flash('Your answer has been posted publicly.')
    return redirect(url_for('product_details', product_id=product_id))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = sanitize_input(request.form.get('name', ''))
        email = sanitize_input(request.form.get('email', '')).lower()
        password = request.form.get('password', '')
        phone = sanitize_input(request.form.get('phone', ''))

        name_error = ''
        email_error = ''
        password_error = ''
        phone_error = ''
        general_error = ''

        if not name:
            name_error = 'Full name is required.'
        if not email:
            email_error = 'Email address is required.'
        elif not validate_email(email):
            email_error = 'Please provide a valid email address.'
        if not password:
            password_error = 'Password is required.'
        if not phone:
            phone_error = 'Phone number is required.'

        if not any([name_error, email_error, password_error, phone_error]):
            if firestore_db.is_firestore_available():
                existing = firestore_db.fs_get_user_by_email(email)
                if existing:
                    email_error = 'An account with this email already exists.'
            else:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT user_id FROM users WHERE lower(email) = lower(?)', (email,))
                if cursor.fetchone():
                    email_error = 'An account with this email already exists.'
                conn.close()

        if any([name_error, email_error, password_error, phone_error]):
            general_error = 'Please correct the errors below.'

        if not any([name_error, email_error, password_error, phone_error]):
            password_hash = generate_password_hash(password)
            join_date = datetime.utcnow()

            user_data = {
                'name': name,
                'email': email,
                'password': password_hash,
                'phone': phone,
                'join_date': join_date,
                'email_verified': 0,
                'phone_verified': 0,
                'contact_preference': 'whatsapp',
                'contact_phone': phone,
                'contact_email': email,
            }

            if firestore_db.is_firestore_available():
                user_id = firestore_db.fs_create_user(user_data)
                firestore_db.fs_increment_stat('total_users', 1)
                session.clear()
                session.permanent = True
                session['user_id'] = user_id
                session['user_name'] = name
                flash(f'Welcome, {name}!', 'success')
                return redirect(url_for('index'))
            else:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO users (name, email, password, phone, join_date, contact_preference, contact_phone, contact_email)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (name, email, password_hash, phone, join_date, 'whatsapp', phone, email))
                cursor.execute('UPDATE stats SET total_users = total_users + 1 WHERE id = 1')
                conn.commit()
                user_id = cursor.lastrowid
                conn.close()

                session.clear()
                session.permanent = True
                session['user_id'] = user_id
                session['user_name'] = name
                flash(f'Welcome, {name}!', 'success')
                return redirect(url_for('index'))

        return render_template('signup.html',
            name=name, email=email, phone=phone,
            name_error=name_error, email_error=email_error,
            password_error=password_error, phone_error=phone_error,
            general_error=general_error
        )

    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    email_value = ''
    email_error = ''
    password_error = ''
    general_error = ''
    if request.method == 'POST':
        email_value = sanitize_input(request.form.get('email', '')).lower()
        password = request.form.get('password', '')

        if not validate_email(email_value):
            email_error = 'Please provide a valid email address.'
            general_error = 'Please correct the errors below.'
        else:
            user = None
            if firestore_db.is_firestore_available():
                user = firestore_db.fs_get_user_by_email(email_value)
            else:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM users WHERE lower(email) = lower(?)', (email_value,))
                user = cursor.fetchone()
                conn.close()

            if user and check_password_hash(user['password'], password):
                session.clear()
                session.permanent = True
                session['user_id'] = user['user_id']
                session['user_name'] = user['name']
                session['email_verified'] = bool(user.get('email_verified', 0))
                session['phone_verified'] = bool(user.get('phone_verified', 0))
                flash(f'Welcome back, {user["name"]}!', 'success')
                return redirect(url_for('index'))

            password_error = 'Incorrect password.'
            general_error = 'Please correct the errors below.'

    return render_template('login.html', email_value=email_value, email_error=email_error, password_error=password_error, general_error=general_error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = sanitize_input(request.form.get('email', '')).lower()
        if validate_email(email):
            user = get_user_by_email(email)
            if user:
                token = secrets.token_urlsafe(32)
                created_at = datetime.utcnow()
                expires_at = created_at + timedelta(minutes=RESET_TOKEN_EXPIRY_MINUTES)
                if create_password_reset(user, email, token, expires_at, created_at=created_at):
                    base_url = os.environ.get('BASE_URL') or request.host_url.rstrip('/')
                    reset_link = base_url + url_for('reset_password', token=token)
                    send_password_reset_email(email, reset_link)
        flash('If an account with that email exists, a password reset link has been sent.', 'success')
        return redirect(url_for('forgot_password'))
    return render_template('forgot_password.html')


@app.route('/reset-password')
def reset_password_missing():
    return redirect(url_for('forgot_password'))


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    token = sanitize_input(token, max_len=128)
    reset = verify_password_reset_token(token)
    if not reset:
        return render_template('reset_password.html', invalid_token=True, token=token)

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        password_error = ''
        confirm_error = ''

        if not password:
            password_error = 'Password is required.'
        elif not validate_password(password):
            password_error = 'Password must be at least 8 characters.'
        if not confirm:
            confirm_error = 'Please confirm your password.'
        elif password != confirm:
            confirm_error = 'Passwords do not match.'

        if not password_error and not confirm_error:
            password_hash = generate_password_hash(password)
            if update_user_password(reset['user_id'], password_hash):
                invalidate_password_reset(token)
                flash('Your password has been reset successfully. Please log in.', 'success')
                return redirect(url_for('login'))
            flash('Unable to update your password. Please try again.', 'error')
            return redirect(url_for('reset_password', token=token))

        return render_template('reset_password.html', invalid_token=False, reset=reset,
                               password_error=password_error, confirm_error=confirm_error, token=token)

    return render_template('reset_password.html', invalid_token=False, reset=reset, token=token)


if __name__ == '__main__':
    app.run(debug=True, port=8080)
