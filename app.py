import importlib
import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from ai_service import analyze_item

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
    print('WARNING: Using default SECRET_KEY. Set SECRET_KEY env var for production.')
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

DATABASE_URL = os.environ.get('DATABASE_URL')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')

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
            if isinstance(parsed, list) and parsed:
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

    candidate_path = os.path.normpath(os.path.join(app.root_path, 'static', normalized))
    if os.path.exists(candidate_path):
        return f"{app.static_url_path}/{normalized}"

    return f"{app.static_url_path}/placeholder.svg"


app.jinja_env.globals['build_image_url'] = build_image_url


def get_db_connection():
    if DATABASE_URL:
        import importlib
        try:
            psycopg2 = importlib.import_module('psycopg2')
        except ImportError:
            raise RuntimeError('psycopg2 is required when DATABASE_URL is configured')
        # Fix for Render/Neon connection strings that start with postgres://
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(url)
        conn.row_factory = dict_factory
        return conn
    else:
        conn = sqlite3.connect('database.db')
        conn.row_factory = dict_factory
        return conn

def schema_has_column(conn, table_name, column_name):
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='{table_name.lower()}' AND column_name='{column_name.lower()}'
        """)
        return cursor.fetchone() is not None
    else:
        cursor.execute(f"PRAGMA table_info({table_name})")
        rows = cursor.fetchall()
        if not rows:
            return False
        if isinstance(rows[0], dict):
            return any(row.get('name') == column_name for row in rows)
        return any(row[1] == column_name for row in rows)

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if we are using PostgreSQL or SQLite to apply the correct Autoincrement keyword
    id_autoincrement = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS users (
            user_id {id_autoincrement},
            name TEXT NOT NULL,
            username TEXT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            street_address TEXT DEFAULT '',
            city TEXT NOT NULL,
            province TEXT DEFAULT '',
            postal_code TEXT DEFAULT '',
            email_verified INTEGER DEFAULT 0,
            phone_verified INTEGER DEFAULT 0,
            profile_picture TEXT DEFAULT '',
            bio TEXT DEFAULT '',
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            seller_rating REAL DEFAULT 0.0,
            total_sales INTEGER DEFAULT 0
        )
    ''')
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS Products (
            id {id_autoincrement},
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
            order_id {id_autoincrement},
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
    # Questions & Answers tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            question_id {0},
            product_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES Products(id),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    '''.format("SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"))
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS answers (
            answer_id {0},
            question_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (question_id) REFERENCES questions(question_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    '''.format("SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"))
    
    if not DATABASE_URL:
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
        ("province", "TEXT DEFAULT ''"),
        ("postal_code", "TEXT DEFAULT ''"),
        ("profile_picture", "TEXT DEFAULT ''"),
        ("bio", "TEXT DEFAULT ''"),
        ("join_date", "TEXT"),
        ("joined_date", "TEXT"),
        ("seller_rating", "REAL DEFAULT 0.0"),
        ("total_sales", "INTEGER DEFAULT 0"),
        ("is_admin", "INTEGER DEFAULT 0"),
        ("verification_token", "TEXT"),
        ("verification_expires", "TEXT"),
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
        ("payout_status", "TEXT DEFAULT 'Pending'"),
        ("payout_date", "TEXT"),
        ("payment_date", "TEXT"),
        ("shipping_company", "TEXT"),
    ]
    if schema_has_column(conn, 'orders', 'order_id'):
        for column_name, definition in order_columns:
            if not schema_has_column(conn, 'orders', column_name):
                try:
                    cursor.execute(f"ALTER TABLE orders ADD COLUMN {column_name} {definition}")
                except Exception:
                    pass

    if not DATABASE_URL:
        try:
            if schema_has_column(conn, 'users', 'username'):
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_seller_id ON Products(seller_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_buyer_id ON orders(buyer_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_seller_id ON orders(seller_id)')
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg'}

def get_clean_cart_ids():
    current_cart = session.get('cart', [])
    clean_ids = []
    for item in current_cart:
        try:
            clean_ids.append(int(item))
        except (TypeError, ValueError):
            continue
    clean_ids = list(dict.fromkeys(clean_ids))
    session['cart'] = clean_ids
    return clean_ids


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

def get_cart_products():
    cart_ids = get_clean_cart_ids()
    if not cart_ids:
        return []
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholders = ','.join('%s' if DATABASE_URL else '?' for _ in cart_ids)
    cursor.execute(f"SELECT * FROM Products WHERE id IN ({placeholders}) AND status = 'available'", cart_ids)
    if DATABASE_URL:
        columns = [desc[0] for desc in cursor.description]
        products = [dict(zip(columns, row)) for row in cursor.fetchall()]
    else:
        products = cursor.fetchall()
    conn.close()
    return products



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
                image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_name))
                saved_paths.append(f"uploads/{unique_name}")
            except Exception as e:
                print(f"Image upload error: {e}")
                continue
    return saved_paths



def get_product_by_id(product_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute("SELECT * FROM Products WHERE id = %s", (product_id,))
        row = cursor.fetchone()
        product = dict(zip([desc[0] for desc in cursor.description], row)) if row else None
    else:
        product = cursor.execute("SELECT * FROM Products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    return product


def is_admin_user():
    if 'user_id' not in session:
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute('SELECT is_admin, email FROM users WHERE user_id = %s', (session['user_id'],))
        row = cursor.fetchone()
        user = dict(zip([desc[0] for desc in cursor.description], row)) if row else None
    else:
        user = cursor.execute('SELECT * FROM users WHERE user_id = ?', (session['user_id'],)).fetchone()
    conn.close()
    admin_email = os.environ.get('ADMIN_EMAIL')
    if not user:
        return False
    # Check explicit is_admin flag if present, otherwise fallback to ADMIN_EMAIL match
    try:
        if user.get('is_admin'):
            return True
    except Exception:
        pass
    if admin_email and user.get('email') and user.get('email').lower() == admin_email.lower():
        return True
    return False

try:
    init_db()
    ensure_schema()
except Exception as e:
    print(f"Database initialization status: {e}")

def _send_email_via_resend(to_email, subject, html_content):
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        params = {
            "from": "Thrift Marketplace <noreply@thrift.pk>",
            "to": [to_email],
            "subject": subject,
            "html": html_content,
        }
        result = resend.Emails.send(params)
        return result
    except Exception as e:
        print(f"Email send error: {e}")
        return None

def send_buyer_email(to_email, buyer_name, item_title, price, tracking_number, destination, payment_method):
    subject = f"Order Confirmed: {item_title}"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #1c1c1c;">
        <h1 style="font-size: 24px; font-weight: 800; margin-bottom: 16px;">Order Confirmed</h1>
        <p style="font-size: 14px; line-height: 1.6; color: #555;">Dear {buyer_name},</p>
        <p style="font-size: 14px; line-height: 1.6; color: #555;">Your order on thrift has been placed successfully!</p>
        <div style="background: #f2efea; border-radius: 8px; padding: 20px; margin: 20px 0;">
            <p style="margin: 0 0 8px 0; font-size: 14px;"><strong>Item:</strong> {item_title}</p>
            <p style="margin: 0 0 8px 0; font-size: 14px;"><strong>Total Paid:</strong> Rs. {price:.2f}</p>
            <p style="margin: 0 0 8px 0; font-size: 14px;"><strong>Payment Method:</strong> {payment_method}</p>
            <p style="margin: 0 0 8px 0; font-size: 14px;"><strong>Tracking Number:</strong> {tracking_number}</p>
            <p style="margin: 0; font-size: 14px;"><strong>Shipping To:</strong> {destination}</p>
        </div>
        <p style="font-size: 13px; color: #767676;">Thank you for shopping with us.</p>
    </div>
    """
    if RESEND_API_KEY:
        return _send_email_via_resend(to_email, subject, html)
    else:
        print("\n" + "="*60)
        print(f"[CONSOLE EMAIL OUTBOX] BUYER NOTIFICATION")
        print(f"TO: {to_email}")
        print(f"SUBJECT: {subject}")
        print(f"ITEM: {item_title} | PRICE: Rs. {price:.2f}")
        print(f"TRACKING: {tracking_number} | DEST: {destination}")
        print("="*60 + "\n")
        return None

def send_seller_email(to_email, seller_name, item_title, buyer_name, buyer_phone, buyer_address, tracking_number):
    subject = f"New Order Received: {item_title}"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #1c1c1c;">
        <h1 style="font-size: 24px; font-weight: 800; margin-bottom: 16px;">New Order Received</h1>
        <p style="font-size: 14px; line-height: 1.6; color: #555;">Dear {seller_name},</p>
        <p style="font-size: 14px; line-height: 1.6; color: #555;">Your item has been purchased on thrift!</p>
        <div style="background: #f2efea; border-radius: 8px; padding: 20px; margin: 20px 0;">
            <p style="margin: 0 0 8px 0; font-size: 14px;"><strong>Item:</strong> {item_title}</p>
            <p style="margin: 0 0 8px 0; font-size: 14px;"><strong>Buyer:</strong> {buyer_name}</p>
            <p style="margin: 0 0 8px 0; font-size: 14px;"><strong>Buyer Phone:</strong> {buyer_phone}</p>
            <p style="margin: 0 0 8px 0; font-size: 14px;"><strong>Shipping Address:</strong> {buyer_address}</p>
            <p style="margin: 0; font-size: 14px;"><strong>Tracking Number:</strong> {tracking_number}</p>
        </div>
        <p style="font-size: 13px; color: #767676;">Please prepare the item for shipment.</p>
    </div>
    """
    if RESEND_API_KEY:
        return _send_email_via_resend(to_email, subject, html)
    else:
        print("\n" + "="*60)
        print(f"[CONSOLE EMAIL OUTBOX] SELLER NOTIFICATION")
        print(f"TO: {to_email}")
        print(f"SUBJECT: {subject}")
        print(f"ITEM: {item_title} | BUYER: {buyer_name}")
        print(f"BUYER PHONE: {buyer_phone} | ADDRESS: {buyer_address}")
        print(f"TRACKING: {tracking_number}")
        print("="*60 + "\n")
        return None


def generate_verification_token():
    return secrets.token_urlsafe(32)


def send_verification_email(to_email, token):
    verification_url = url_for('verify_email', token=token, _external=True)
    subject = "Verify your email - Thrift Marketplace"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #1c1c1c;">
        <h1 style="font-size: 24px; font-weight: 800; margin-bottom: 16px;">Verify Your Email</h1>
        <p style="font-size: 14px; line-height: 1.6; color: #555;">Thank you for joining Thrift Marketplace!</p>
        <p style="font-size: 14px; line-height: 1.6; color: #555;">Please verify your email address by clicking the button below:</p>
        <div style="margin: 30px 0;">
            <a href="{verification_url}" style="background-color: #1c1c1c; color: #fbf9f6; padding: 14px 28px; border-radius: 999px; text-decoration: none; font-size: 14px; font-weight: 700; display: inline-block;">Verify Email Address</a>
        </div>
        <p style="font-size: 14px; line-height: 1.6; color: #555;">Or copy and paste this link into your browser:</p>
        <p style="font-size: 13px; color: #767676; word-break: break-all;">{verification_url}</p>
        <p style="font-size: 13px; color: #767676; margin-top: 30px;">This link will expire in 24 hours. If you did not create an account, please ignore this email.</p>
    </div>
    """
    if RESEND_API_KEY:
        return _send_email_via_resend(to_email, subject, html)
    else:
        print("\n" + "="*60)
        print(f"[CONSOLE EMAIL OUTBOX] VERIFICATION EMAIL")
        print(f"TO: {to_email}")
        print(f"SUBJECT: {subject}")
        print(f"VERIFICATION URL: {verification_url}")
        print("="*60 + "\n")
        return None

@app.before_request
def ensure_cart_exists():
    if 'cart' not in session:
        session['cart'] = []
    get_clean_cart_ids()

@app.route('/')
def index():
    category = request.args.get('category')
    conn = get_db_connection()
    cursor = conn.cursor()
    if category:
        if DATABASE_URL:
            cursor.execute("SELECT * FROM Products WHERE status = 'available' AND category = %s", (category,))
        else:
            cursor.execute("SELECT * FROM Products WHERE status = 'available' AND category = ?", (category,))
    else:
        cursor.execute("SELECT * FROM Products WHERE status = 'available'")
    
    if DATABASE_URL:
        columns = [desc[0] for desc in cursor.description]
        products = [dict(zip(columns, row)) for row in cursor.fetchall()]
    else:
        products = cursor.fetchall()
    conn.close()
    return render_template('index.html', products=products, selected_category=category)

@app.route('/how-it-works')
def how_it_works():
    return render_template('how_it_works.html')

@app.route('/product/<int:product_id>')
def product_details(product_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute("SELECT * FROM Products WHERE id = %s", (product_id,))
        row = cursor.fetchone()
        product = dict(zip([desc[0] for desc in cursor.description], row)) if row else None
    else:
        product = cursor.execute("SELECT * FROM Products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    if not product:
        flash("Product not found!")
        return redirect(url_for('index'))
    image_list = []
    if product.get('images'):
        try:
            image_list = json.loads(product['images'])
        except Exception:
            image_list = [product['images']] if product.get('image_url') else []
    elif product.get('image_url'):
        image_list = [product['image_url']]
    # Load public questions and answers
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute('''
            SELECT q.question_id, q.content, q.created_at, u.name as asker
            FROM questions q
            LEFT JOIN users u ON q.user_id = u.user_id
            WHERE q.product_id = %s
            ORDER BY q.created_at ASC
        ''', (product_id,))
        qcols = [desc[0] for desc in cur.description]
        questions = [dict(zip(qcols, row)) for row in cur.fetchall()]
        for q in questions:
            cur.execute('SELECT a.answer_id, a.content, a.created_at, u.name as answerer FROM answers a LEFT JOIN users u ON a.user_id = u.user_id WHERE a.question_id = %s ORDER BY a.created_at ASC', (q['question_id'],))
            acol = [d[0] for d in cur.description]
            q['answers'] = [dict(zip(acol, r)) for r in cur.fetchall()]
    else:
        rows = cur.execute('SELECT q.question_id, q.content, q.created_at, u.name as asker FROM questions q LEFT JOIN users u ON q.user_id = u.user_id WHERE q.product_id = ? ORDER BY q.created_at ASC', (product_id,)).fetchall()
        questions = [dict(r) for r in rows]
        for q in questions:
            qrows = cur.execute('SELECT a.answer_id, a.content, a.created_at, u.name as answerer FROM answers a LEFT JOIN users u ON a.user_id = u.user_id WHERE a.question_id = ? ORDER BY a.created_at ASC', (q['question_id'],)).fetchall()
            q['answers'] = [dict(ar) for ar in qrows]
    conn.close()
    return render_template('product_details.html', product=product, image_list=image_list, questions=questions)

@app.route('/cart/add/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    cart_ids = get_clean_cart_ids()
    if product_id not in cart_ids:
        cart_ids.append(product_id)
        session['cart'] = cart_ids
        flash("Item added to cart!")
    return redirect(url_for('view_cart'))

@app.route('/cart')
def view_cart():
    products = get_cart_products()
    if not products:
        return render_template('cart.html', products=[], total=0)
    total = sum(p['asking_price'] for p in products)
    return render_template('cart.html', products=products, total=total)

@app.route('/cart/remove/<int:product_id>')
def remove_from_cart(product_id):
    current_cart = list(session['cart'])
    if product_id in current_cart:
        current_cart.remove(product_id)
        session['cart'] = current_cart
        flash("Item removed.")
    return redirect(url_for('view_cart'))

@app.route('/checkout')
def checkout():
    if 'user_id' not in session:
        flash('Please log in before checking out.')
        return redirect(url_for('login'))

    products = get_cart_products()
    if not products:
        flash('Your cart is empty or items are no longer available.')
        return redirect(url_for('index'))

    total = sum(p['asking_price'] for p in products)
    commission = round(total * 0.10, 2)
    final_payout = round(total - commission, 2)
    return render_template('checkout.html', products=products, total=total, commission=commission, final_payout=final_payout)

@app.route('/place_order', methods=['POST'])
def place_order():
    if 'user_id' not in session:
        flash('You must be logged in to place an order.')
        return redirect(url_for('login'))

    buyer_name = request.form.get('buyer_name', '').strip()
    buyer_phone = request.form.get('buyer_phone', '').strip()
    street = request.form.get('buyer_address_street', '').strip()
    city = request.form.get('buyer_city', '').strip()
    shipping_company = request.form.get('shipping_company', '').strip()
    payment_method = request.form.get('payment_method', '').strip()
    delivery_note = request.form.get('delivery_note', '').strip()

    required_fields = [buyer_name, buyer_phone, street, city, shipping_company, payment_method]
    if not all(required_fields):
        flash('Please complete all required shipping and payment fields before placing your order.')
        return redirect(url_for('checkout'))

    # Determine buyer email from form or user record
    buyer_email = request.form.get('buyer_email', '').strip()
    if not buyer_email:
        conn_temp = get_db_connection()
        cur_temp = conn_temp.cursor()
        if DATABASE_URL:
            cur_temp.execute('SELECT email FROM users WHERE user_id = %s', (session['user_id'],))
            row = cur_temp.fetchone()
            buyer_email = row[0] if row else ''
        else:
            row = cur_temp.execute('SELECT email FROM users WHERE user_id = ?', (session['user_id'],)).fetchone()
            buyer_email = row.get('email') if row else ''
        conn_temp.close()

    products = get_cart_products()
    if not products:
        flash('Your cart is empty or all items are unavailable.')
        return redirect(url_for('index'))

    conn = get_db_connection()
    cursor = conn.cursor()
    buyer_id = session['user_id']
    for product in products:
        if product['status'] != 'available':
            continue

        seller_id = product['seller_id']
        amount = float(product['asking_price'])
        seller_amount = round(amount * 0.90, 2)
        platform_commission = round(amount * 0.10, 2)
        tracking_num = f"TRK{product['id']}{int(datetime.utcnow().timestamp())}PK"

        # Build a consolidated delivery note to store shipping_company and payment_method
        full_delivery_note = f"{shipping_company} | {payment_method}"
        if delivery_note:
            full_delivery_note = f"{full_delivery_note} | {delivery_note}"

        if DATABASE_URL:
            cursor.execute('''
                INSERT INTO orders (product_id, buyer_id, seller_id, status, buyer_name, buyer_email, buyer_phone,
                    buyer_street_address, buyer_city, buyer_province, buyer_postal_code, delivery_note, tracking_number,
                    seller_amount, platform_commission, payout_status, payout_date, payment_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING order_id
            ''', (
                product['id'], buyer_id, seller_id, 'Paid', buyer_name, buyer_email, buyer_phone,
                street, city, '', '', full_delivery_note,
                    tracking_num, seller_amount, platform_commission, 'Pending', None, datetime.utcnow(),
            ))
            order_id = cursor.fetchone()[0]
            cursor.execute('UPDATE Products SET status=%s, tracking_number=%s, order_id=%s WHERE id=%s',
                           ('sold', tracking_num, order_id, product['id']))
        else:
            cursor.execute('''
                INSERT INTO orders (product_id, buyer_id, seller_id, status, buyer_name, buyer_email, buyer_phone,
                    buyer_street_address, buyer_city, buyer_province, buyer_postal_code, delivery_note, tracking_number,
                    seller_amount, platform_commission, payout_status, payout_date, payment_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                product['id'], buyer_id, seller_id, 'Paid', buyer_name, buyer_email, buyer_phone,
                street, city, '', '', full_delivery_note, tracking_num,
                seller_amount, platform_commission, 'Pending', None, datetime.utcnow(),
            ))
            order_id = cursor.lastrowid
            cursor.execute('UPDATE Products SET status=?, tracking_number=?, order_id=? WHERE id=?',
                           ('sold', tracking_num, order_id, product['id']))

        # Append shipping company and payment method to delivery note for record keeping
        full_delivery_note = f"{shipping_company} | {payment_method}"
        if delivery_note:
            full_delivery_note = f"{full_delivery_note} | {delivery_note}"
        
        send_buyer_email(buyer_email, buyer_name, product['title'], product['asking_price'], tracking_num, f"{street}, {city} | {full_delivery_note}", payment_method)
        
        seller_info = None
        conn_temp2 = get_db_connection()
        cur_temp2 = conn_temp2.cursor()
        if DATABASE_URL:
            cur_temp2.execute('SELECT name, email FROM users WHERE user_id = %s', (seller_id,))
            row = cur_temp2.fetchone()
            seller_info = dict(zip([d[0] for d in cur_temp2.description], row)) if row else None
        else:
            row = cur_temp2.execute('SELECT name, email FROM users WHERE user_id = ?', (seller_id,)).fetchone()
            seller_info = dict(row) if row else None
        conn_temp2.close()
        
        if seller_info:
            send_seller_email(
                seller_info['email'],
                seller_info['name'],
                product['title'],
                buyer_name,
                buyer_phone,
                f"{street}, {city} | {full_delivery_note}",
                tracking_num
            )

    conn.commit()
    conn.close()
    session['cart'] = []
    flash('Order placed successfully. Your purchase is now recorded with platform commission tracking.')
    return redirect(url_for('index'))

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
        seller_address = request.form['seller_address'].strip()
        asking_price = float(request.form['asking_price'])
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
        if DATABASE_URL:
            cursor.execute('SELECT title, description FROM Products')
            existing_rows = [dict(zip([desc[0] for desc in cursor.description], row)) for row in cursor.fetchall()]
        else:
            raw = cursor.execute('SELECT title, description FROM Products').fetchall()
            existing_rows = [{'title': row['title'], 'description': row['description']} for row in raw]

        ai_result = analyze_item(category, times_worn, has_tears, description, tags, title=title, existing_listings=existing_rows)
        # We no longer use a numeric AI quality score. Keep the descriptive summary for UI/AI-generated descriptions.
        condition_summary = ai_result.get('summary')
        auto_category = ai_result.get('category')
        duplicate = ai_result.get('duplicate', False)
        if auto_category and auto_category != category:
            category = auto_category
        if duplicate:
            flash('Warning: this listing appears similar to another item already on the marketplace.')

        if DATABASE_URL:
            cursor.execute('''
                INSERT INTO Products (title, brand, category, size, color, gender, asking_price, image_url, images, description, tags, times_worn, seller_condition, has_tears, seller_address, condition_summary, seller_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (title, brand, category, size, color, gender, asking_price, image_url, images_json, description, tags, int(times_worn), seller_condition, has_tears, seller_address, condition_summary, session['user_id']))
        else:
            cursor.execute('''
                INSERT INTO Products (title, brand, category, size, color, gender, asking_price, image_url, images, description, tags, times_worn, seller_condition, has_tears, seller_address, condition_summary, seller_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (title, brand, category, size, color, gender, asking_price, image_url, images_json, description, tags, int(times_worn), seller_condition, has_tears, seller_address, condition_summary, session['user_id']))
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

    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute('SELECT * FROM Products WHERE seller_id = %s', (session['user_id'],))
        columns = [desc[0] for desc in cursor.description]
        listings = [dict(zip(columns, row)) for row in cursor.fetchall()]
    else:
        listings = cursor.execute('SELECT * FROM Products WHERE seller_id = ?', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('seller_listings.html', listings=listings)


@app.route('/listing/<int:product_id>/delete', methods=['POST'])
def delete_listing(product_id):
    if 'user_id' not in session:
        flash('Please log in to delete your listing.')
        return redirect(url_for('login'))

    product = get_product_by_id(product_id)
    if not product or product['seller_id'] != session['user_id']:
        flash('Unable to delete the listing.')
        return redirect(url_for('seller_listings'))

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

    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute('DELETE FROM Products WHERE id = %s', (product_id,))
    else:
        cursor.execute('DELETE FROM Products WHERE id = ?', (product_id,))
    conn.commit()
    conn.close()
    flash('Listing deleted successfully.')
    return redirect(url_for('seller_listings'))


@app.route('/listing/<int:product_id>/mark_sold', methods=['POST'])
def mark_sold(product_id):
    if 'user_id' not in session:
        flash('Please log in to manage your listing.')
        return redirect(url_for('login'))

    product = get_product_by_id(product_id)
    if not product or product['seller_id'] != session['user_id']:
        flash('Unable to mark this listing as sold.')
        return redirect(url_for('seller_listings'))

    # Manual marking as sold is not permitted. Items become sold automatically after successful purchase.
    flash('Manual marking as sold is not allowed. Items become sold only after a successful purchase through the site.')
    return redirect(url_for('seller_listings'))


@app.route('/orders', methods=['GET', 'POST'])
def track_orders():
    if 'user_id' not in session:
        flash('Please log in to view your orders.')
        return redirect(url_for('login'))

    orders = []
    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute('''
            SELECT o.*, p.title AS product_title, p.brand, p.color, p.size, p.category,
                p.image_url, p.images,
                o.buyer_name, o.buyer_email, o.buyer_phone
            FROM orders o
            JOIN Products p ON o.product_id = p.id
            WHERE o.buyer_id = %s
            ORDER BY o.order_date DESC
        ''', (session['user_id'],))
        columns = [desc[0] for desc in cursor.description]
        orders = [dict(zip(columns, row)) for row in cursor.fetchall()]
    else:
        cursor.execute('''
            SELECT o.*, p.title AS product_title, p.brand, p.color, p.size, p.category,
                p.image_url, p.images,
                o.buyer_name, o.buyer_email, o.buyer_phone
            FROM orders o
            JOIN Products p ON o.product_id = p.id
            WHERE o.buyer_id = ?
            ORDER BY o.order_date DESC
        ''', (session['user_id'],))
        orders = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return render_template('orders.html', orders=orders)

@app.route('/admin')
def admin_dashboard():
    if not is_admin_user():
        flash('Admin access required.')
        return redirect(url_for('index'))
    
    section = request.args.get('section', 'dashboard')
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if DATABASE_URL:
        cursor.execute('''
            SELECT o.*, p.title AS product_title, p.asking_price AS product_price,
                s.name AS seller_name, s.phone AS seller_phone, s.email AS seller_email,
                b.name AS buyer_name, b.email AS buyer_email, b.phone AS buyer_phone
            FROM orders o
            LEFT JOIN Products p ON o.product_id = p.id
            LEFT JOIN users s ON o.seller_id = s.user_id
            LEFT JOIN users b ON o.buyer_id = b.user_id
            ORDER BY o.order_date DESC
        ''')
        columns = [desc[0] for desc in cursor.description]
        orders = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        cursor.execute('SELECT * FROM users ORDER BY join_date DESC')
        columns = [desc[0] for desc in cursor.description]
        users = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        cursor.execute('SELECT * FROM Products ORDER BY created_at DESC')
        columns = [desc[0] for desc in cursor.description]
        listings = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        cursor.execute('''
            SELECT category, COUNT(*) as count FROM Products 
            WHERE status = 'sold' AND category IS NOT NULL 
            GROUP BY category ORDER BY count DESC
        ''')
        columns = [desc[0] for desc in cursor.description]
        category_stats = [dict(zip(columns, row)) for row in cursor.fetchall()]
    else:
        orders = [dict(row) for row in cursor.execute('''
            SELECT o.*, p.title AS product_title, p.asking_price AS product_price,
                s.name AS seller_name, s.phone AS seller_phone, s.email AS seller_email,
                b.name AS buyer_name, b.email AS buyer_email, b.phone AS buyer_phone
            FROM orders o
            LEFT JOIN Products p ON o.product_id = p.id
            LEFT JOIN users s ON o.seller_id = s.user_id
            LEFT JOIN users b ON o.buyer_id = b.user_id
            ORDER BY o.order_date DESC
        ''').fetchall()]
        
        users = [dict(row) for row in cursor.execute('SELECT * FROM users ORDER BY join_date DESC').fetchall()]
        
        listings = [dict(row) for row in cursor.execute('SELECT * FROM Products ORDER BY created_at DESC').fetchall()]
        
        category_stats = [dict(row) for row in cursor.execute('''
            SELECT category, COUNT(*) as count FROM Products 
            WHERE status = 'sold' AND category IS NOT NULL 
            GROUP BY category ORDER BY count DESC
        ''').fetchall()]
    
    conn.close()
    
    total_revenue = round(sum(item.get('product_price', 0) or 0 for item in orders), 2)
    total_commission = round(sum(item.get('platform_commission', 0) or 0 for item in orders), 2)
    pending_payouts = sum(1 for item in orders if item.get('payout_status') == 'Pending')
    
    return render_template('admin_dashboard.html',
        section=section,
        orders=orders,
        users=users,
        listings=listings,
        total_revenue=total_revenue,
        total_commission=total_commission,
        pending_payouts=pending_payouts,
        category_stats=category_stats,
        current_admin_id=session.get('user_id')
    )

@app.route('/admin-portal')
def admin_portal():
    return redirect(url_for('admin_dashboard', section='dashboard'))

@app.route('/admin/users')
def admin_users():
    return redirect(url_for('admin_dashboard', section='users'))

@app.route('/admin/listings')
def admin_listings():
    return redirect(url_for('admin_dashboard', section='listings'))

@app.route('/admin/orders')
def admin_orders():
    return redirect(url_for('admin_dashboard', section='orders'))


@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
def admin_delete_user(user_id):
    if not is_admin_user():
        flash('Admin access required.')
        return redirect(url_for('index'))

    current_admin_id = session.get('user_id')
    if user_id == current_admin_id:
        flash('You cannot delete your own account.')
        return redirect(url_for('admin_dashboard', section='users'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Load the target user
        if DATABASE_URL:
            cursor.execute('SELECT is_admin, email FROM users WHERE user_id = %s', (user_id,))
        else:
            cursor.execute('SELECT is_admin, email FROM users WHERE user_id = ?', (user_id,))
        target = cursor.fetchone()
        if not target:
            flash('User not found.')
            return redirect(url_for('admin_dashboard', section='users'))

        # Determine whether the target is an administrator (explicit flag or ADMIN_EMAIL fallback)
        is_target_admin = bool(target.get('is_admin'))
        if not is_target_admin and os.environ.get('ADMIN_EMAIL') and target.get('email') and target['email'].lower() == os.environ.get('ADMIN_EMAIL').lower():
            is_target_admin = True

        # Count administrators remaining AFTER this deletion (exclude the target itself).
        # Rows use dict_factory, so read the count by its aliased column name (not integer index).
        if DATABASE_URL:
            cursor.execute(
                'SELECT COUNT(*) AS cnt FROM users WHERE (is_admin = 1 OR lower(email) = lower(%s)) AND user_id <> %s',
                (os.environ.get('ADMIN_EMAIL', ''), user_id),
            )
        else:
            cursor.execute(
                'SELECT COUNT(*) AS cnt FROM users WHERE (is_admin = 1 OR lower(email) = lower(?)) AND user_id <> ?',
                (os.environ.get('ADMIN_EMAIL', ''), user_id),
            )
        remaining_admins = cursor.fetchone()['cnt']

        if is_target_admin and remaining_admins == 0:
            flash('Cannot delete the final remaining administrator.')
            return redirect(url_for('admin_dashboard', section='users'))

        cursor.execute('UPDATE Products SET seller_id = NULL WHERE seller_id = ?', (user_id,))
        cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
        conn.commit()
        flash('User removed.')
    except Exception as e:
        conn.rollback()
        flash(f'Error removing user: {str(e)}')
    finally:
        conn.close()
    return redirect(url_for('admin_dashboard', section='users'))


@app.route('/admin/listing/<int:product_id>/delete', methods=['POST'])
def admin_delete_listing(product_id):
    if not is_admin_user():
        flash('Admin access required.')
        return redirect(url_for('index'))
    product = get_product_by_id(product_id)
    if not product:
        flash('Listing not found.')
        return redirect(url_for('admin_dashboard', section='listings'))
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
    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute('DELETE FROM Products WHERE id = %s', (product_id,))
    else:
        cursor.execute('DELETE FROM Products WHERE id = ?', (product_id,))
    conn.commit()
    conn.close()
    flash('Listing removed.')
    return redirect(url_for('admin_dashboard', section='listings'))


@app.route('/admin/order/<int:order_id>/update', methods=['POST'])
def admin_update_order(order_id):
    if not is_admin_user():
        flash('Admin access required.')
        return redirect(url_for('index'))
    new_status = sanitize_input(request.form.get('status', ''))
    if not new_status:
        flash('No status provided.')
        return redirect(url_for('admin_dashboard', section='orders'))
    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute('UPDATE orders SET status = %s WHERE order_id = %s', (new_status, order_id))
    else:
        cursor.execute('UPDATE orders SET status = ? WHERE order_id = ?', (new_status, order_id))
    conn.commit()
    conn.close()
    flash('Order status updated.')
    return redirect(url_for('admin_dashboard', section='orders'))


@app.route('/product/<int:product_id>/question', methods=['POST'])
def post_question(product_id):
    if 'user_id' not in session:
        flash('Please log in to ask questions.')
        return redirect(url_for('login'))
    content = sanitize_input(request.form.get('question_content', ''))
    if not content:
        flash('Please provide a question.')
        return redirect(url_for('product_details', product_id=product_id))
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute('INSERT INTO questions (product_id, user_id, content) VALUES (%s, %s, %s)', (product_id, session['user_id'], content))
    else:
        cur.execute('INSERT INTO questions (product_id, user_id, content) VALUES (?, ?, ?)', (product_id, session['user_id'], content))
    conn.commit()
    conn.close()
    flash('Your question has been posted publicly.')
    return redirect(url_for('product_details', product_id=product_id))


@app.route('/product/<int:product_id>/answer/<int:question_id>', methods=['POST'])
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
    conn = get_db_connection()
    cur = conn.cursor()
    if DATABASE_URL:
        cur.execute('INSERT INTO answers (question_id, user_id, content) VALUES (%s, %s, %s)', (question_id, session['user_id'], content))
    else:
        cur.execute('INSERT INTO answers (question_id, user_id, content) VALUES (?, ?, ?)', (question_id, session['user_id'], content))
    conn.commit()
    conn.close()
    flash('Your answer has been posted publicly.')
    return redirect(url_for('product_details', product_id=product_id))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = sanitize_input(request.form.get('name', ''))
        username = sanitize_input(request.form.get('username', ''))
        email = sanitize_input(request.form.get('email', '')).lower()
        password = request.form.get('password', '')
        phone = sanitize_input(request.form.get('phone', ''))
        address = sanitize_input(request.form.get('address', ''))
        city = sanitize_input(request.form.get('city', ''))
        province = sanitize_input(request.form.get('province', ''))
        postal_code = sanitize_input(request.form.get('postal_code', ''))
        bio = sanitize_input(request.form.get('bio', ''))

        def render_form():
            # Re-render with entered values so the user does not have to retype
            # Name/Email/Username after a validation error. Password is never echoed back.
            return render_template('signup.html', name=name, email=email, username=username)

        if not (name and email and password and phone and address and city):
            flash('Please complete all required fields.')
            return render_form()

        if not validate_email(email):
            flash('Please provide a valid email address.')
            return render_form()

        if not validate_username(username):
            flash('Please choose a valid username (3-32 chars, letters, numbers, _.-).')
            return render_form()

        if len(password) < 8:
            flash('Password must be at least 8 characters long.')
            return render_form()
        if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
            flash('Password must contain both letters and numbers.')
            return render_form()

        password_hash = generate_password_hash(password)
        join_date = datetime.utcnow()
        verification_token = generate_verification_token()
        verification_expires = (datetime.utcnow() + timedelta(hours=24)).isoformat()

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            if DATABASE_URL:
                cursor.execute('SELECT user_id FROM users WHERE lower(email) = lower(%s)', (email,))
            else:
                cursor.execute('SELECT user_id FROM users WHERE lower(email) = lower(?)', (email,))
            if cursor.fetchone():
                flash('An account with this email already exists.')
                return render_form()

            if username:
                if DATABASE_URL:
                    cursor.execute('SELECT user_id FROM users WHERE username IS NOT NULL AND lower(username) = lower(%s)', (username,))
                else:
                    cursor.execute('SELECT user_id FROM users WHERE username IS NOT NULL AND lower(username) = lower(?)', (username,))
                if cursor.fetchone():
                    flash('This username is already taken.')
                    return render_form()

            if DATABASE_URL:
                cursor.execute('''
                    INSERT INTO users (name, username, email, password, phone, address, street_address, city, province, postal_code, bio, join_date, verification_token, verification_expires)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (name, username, email, password_hash, phone, address, address, city, province, postal_code, bio, join_date, verification_token, verification_expires))
            else:
                cursor.execute('''
                    INSERT INTO users (name, username, email, password, phone, address, street_address, city, province, postal_code, bio, join_date, verification_token, verification_expires)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (name, username, email, password_hash, phone, address, address, city, province, postal_code, bio, join_date, verification_token, verification_expires))
            conn.commit()

            send_verification_email(email, verification_token)
            flash('Account created successfully! Please check your email to verify your account before logging in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            msg = str(e).lower()
            if 'unique' in msg or 'constraint' in msg:
                flash('An account with this email or username already exists.')
            else:
                flash('We could not create your account right now. Please try again.')
            return render_form()
        finally:
            conn.close()

    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = sanitize_input(request.form.get('email', '')).lower()
        password = request.form.get('password', '')

        if not validate_email(email):
            flash('Please provide a valid email address.')
            return redirect(url_for('login'))

        conn = get_db_connection()
        cursor = conn.cursor()

        if DATABASE_URL:
            cursor.execute('SELECT * FROM users WHERE lower(email) = lower(%s)', (email,))
            columns = [desc[0] for desc in cursor.description]
            row = cursor.fetchone()
            user = dict(zip(columns, row)) if row else None
        else:
            cursor.execute('SELECT * FROM users WHERE lower(email) = lower(?)', (email,))
            user = cursor.fetchone()

        conn.close()

        if user and check_password_hash(user['password'], password):
            if not user.get('email_verified'):
                flash('Please verify your email before logging in. Check your inbox for the verification link.', 'error')
                return redirect(url_for('login'))

            session.clear()
            session.permanent = True
            session['user_id'] = user['user_id']
            session['user_name'] = user['name']
            session['email_verified'] = bool(user.get('email_verified', 0))
            session['phone_verified'] = bool(user.get('phone_verified', 0))
            flash(f'Welcome back, {user["name"]}!')
            return redirect(url_for('index'))

        flash('Invalid email or password. Please try again.')
        return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/verify/<token>')
def verify_email(token):
    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute('SELECT user_id, email, email_verified, verification_expires FROM users WHERE verification_token = %s', (token,))
        row = cursor.fetchone()
        user = dict(zip([desc[0] for desc in cursor.description], row)) if row else None
    else:
        user = cursor.execute('SELECT user_id, email, email_verified, verification_expires FROM users WHERE verification_token = ?', (token,)).fetchone()
    conn.close()

    if not user:
        flash('Invalid or expired verification link.', 'error')
        return redirect(url_for('login'))

    if user.get('email_verified'):
        flash('Email already verified. Please log in.', 'success')
        return redirect(url_for('login'))

    expires = user.get('verification_expires')
    if expires:
        try:
            exp_dt = datetime.fromisoformat(expires)
            if datetime.utcnow() > exp_dt:
                flash('Verification link has expired. Please request a new one.', 'error')
                return redirect(url_for('login'))
        except Exception:
            pass

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET email_verified = 1, verification_token = NULL, verification_expires = NULL WHERE user_id = ?', (user['user_id'],))
    conn.commit()
    conn.close()

    flash('Email verified successfully! You can now log in.', 'success')
    return redirect(url_for('login'))


@app.route('/resend-verification', methods=['GET', 'POST'])
def resend_verification():
    if request.method == 'POST':
        email = sanitize_input(request.form.get('email', '')).lower()
        if not validate_email(email):
            flash('Please provide a valid email address.', 'error')
            return redirect(url_for('login'))

        conn = get_db_connection()
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute('SELECT user_id, email, email_verified FROM users WHERE lower(email) = lower(%s)', (email,))
            row = cursor.fetchone()
            user = dict(zip([desc[0] for desc in cursor.description], row)) if row else None
        else:
            user = cursor.execute('SELECT user_id, email, email_verified FROM users WHERE lower(email) = lower(?)', (email,)).fetchone()
        conn.close()

        if not user:
            flash('No account found with that email address.', 'error')
            return redirect(url_for('signup'))

        if user.get('email_verified'):
            flash('Your email is already verified. Please log in.', 'success')
            return redirect(url_for('login'))

        token = generate_verification_token()
        expires = (datetime.utcnow() + timedelta(hours=24)).isoformat()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET verification_token = ?, verification_expires = ? WHERE user_id = ?', (token, expires, user['user_id']))
        conn.commit()
        conn.close()

        send_verification_email(user['email'], token)
        flash('Verification email sent! Please check your inbox.', 'success')
        return redirect(url_for('login'))

    if 'user_id' not in session:
        return render_template('resend_verification.html')

    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute('SELECT email, email_verified FROM users WHERE user_id = %s', (session['user_id'],))
        row = cursor.fetchone()
        user = dict(zip([desc[0] for desc in cursor.description], row)) if row else None
    else:
        user = cursor.execute('SELECT email, email_verified FROM users WHERE user_id = ?', (session['user_id'],)).fetchone()
    conn.close()

    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('login'))

    if user.get('email_verified'):
        flash('Your email is already verified.', 'success')
        return redirect(url_for('index'))

    token = generate_verification_token()
    expires = (datetime.utcnow() + timedelta(hours=24)).isoformat()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET verification_token = ?, verification_expires = ? WHERE user_id = ?', (token, expires, session['user_id']))
    conn.commit()
    conn.close()

    send_verification_email(user['email'], token)
    flash('Verification email sent! Please check your inbox.', 'success')
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, port=8080)
