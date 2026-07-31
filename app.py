import importlib
import json
import logging
import os
import sqlite3
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from urllib.parse import quote
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


app.jinja_env.globals['build_image_url'] = build_image_url
app.jinja_env.globals['has_product_image'] = has_product_image


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
                image_file.save(save_path)
                saved_paths.append(f"uploads/{unique_name}")
            except Exception as e:
                logging.error(f"Image upload error: {e}")
                continue
    return saved_paths



def find_user_by_email_firestore(email):
    db = _get_firestore_db()
    if db is None:
        return None
    try:
        docs = db.collection('users').where('email', '==', email).stream()
        for doc in docs:
            data = doc.to_dict()
            data['user_id'] = int(doc.id) if doc.id.isdigit() else doc.id
            return data
    except Exception:
        pass
    return None


def get_product_by_id(product_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    product = cursor.execute("SELECT * FROM Products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    return product


def _get_firestore_db():
    try:
        if not firebase_admin._apps:
            cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception:
        return None


def get_products_from_firestore(category=None):
    db = _get_firestore_db()
    if db is None:
        conn = get_db_connection()
        cursor = conn.cursor()
        if category:
            cursor.execute("SELECT * FROM Products WHERE status = 'available' AND category = ?", (category,))
        else:
            cursor.execute("SELECT * FROM Products WHERE status = 'available'")
        products = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return products
    try:
        docs = db.collection('Products').where('status', '==', 'available').stream()
        products = []
        for doc in docs:
            product = doc.to_dict()
            product['id'] = int(doc.id)
            if category and product.get('category') != category:
                continue
            products.append(product)
        return products
    except Exception:
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
    db = _get_firestore_db()
    if db is None:
        return get_product_by_id(product_id)
    try:
        doc = db.collection('Products').document(str(product_id)).get()
        if doc.exists:
            product = doc.to_dict()
            product['id'] = int(doc.id)
            return product
    except Exception:
        pass
    return get_product_by_id(product_id)


def is_admin_user():
    if 'user_id' not in session:
        return False
    conn = get_db_connection()
    cursor = conn.cursor()
    user = cursor.execute('SELECT * FROM users WHERE user_id = ?', (session['user_id'],)).fetchone()
    conn.close()
    admin_email = os.environ.get('ADMIN_EMAIL')
    if not user:
        return False
    try:
        if user.get('is_admin'):
            return True
    except Exception:
        pass
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
    return render_template('index.html', products=safe_products, selected_category=category or '')

@app.route('/how-it-works')
def how_it_works():
    return render_template('how_it_works.html')

@app.route('/product/<int:product_id>')
def product_details(product_id):
    product = get_single_product_from_firestore(product_id)
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
    rows = cur.execute('SELECT q.question_id, q.content, q.created_at, u.name as asker FROM questions q LEFT JOIN users u ON q.user_id = u.user_id WHERE q.product_id = ? ORDER BY q.created_at ASC', (product_id,)).fetchall()
    questions = [dict(r) for r in rows]
    for q in questions:
        qrows = cur.execute('SELECT a.answer_id, a.content, a.created_at, u.name as answerer FROM answers a LEFT JOIN users u ON a.user_id = u.user_id WHERE a.question_id = ? ORDER BY a.created_at ASC', (q['question_id'],)).fetchall()
        q['answers'] = [dict(ar) for ar in qrows]

    seller_phone = ''
    seller_email = ''
    seller_contact_preference = 'whatsapp'
    seller_id = product.get('seller_id')
    if seller_id:
        seller_row = cur.execute('SELECT phone, email, contact_preference, contact_phone, contact_email FROM users WHERE user_id = ?', (seller_id,)).fetchone()
        if seller_row:
            seller_phone = normalize_phone(seller_row.get('contact_phone', '') or seller_row.get('phone', ''))
            seller_email = (seller_row.get('contact_email', '') or seller_row.get('email', '') or '').strip()
            seller_contact_preference = seller_row.get('contact_preference', 'whatsapp') or 'whatsapp'

    whatsapp_url = ''
    gmail_url = ''
    mailto_url = ''
    if product.get('title'):
        if seller_phone and seller_contact_preference == 'whatsapp':
            text = f"Hi! I came across your listing for \"{product['title']}\" on Thrift. Is it still available?"
            whatsapp_url = f"https://wa.me/{seller_phone}?text={quote(text)}"
        elif seller_email and seller_contact_preference == 'email':
            subject = f"Interest in {product['title']}"
            body = f"Hi! I came across your listing for \"{product['title']}\" on Thrift. Is it still available?"
            gmail_url = f"https://mail.google.com/mail/?view=cm&fs=1&to={quote(seller_email)}&su={quote(subject)}&body={quote(body)}"
            mailto_url = f"mailto:{seller_email}?subject={quote(subject)}&body={quote(body)}"

    conn.close()
    return render_template('product_details.html', product=product, image_list=image_list, questions=questions, seller_phone=seller_phone, seller_email=seller_email, seller_contact_preference=seller_contact_preference, whatsapp_url=whatsapp_url, gmail_url=gmail_url, mailto_url=mailto_url)

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
        seller_province = request.form.get('seller_province', '').strip()
        seller_locality = request.form.get('seller_locality', '').strip()
        if seller_locality:
            seller_address = f"{seller_locality}, {seller_city}, {seller_province}"
        else:
            seller_address = f"{seller_city}, {seller_province}"
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

        cursor.execute('''
            INSERT INTO Products (title, brand, category, size, color, gender, asking_price, image_url, images, description, tags, times_worn, seller_condition, has_tears, seller_address, condition_summary, seller_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (title, brand, category, size, color, gender, asking_price, image_url, images_json, description, tags, int(times_worn), seller_condition, has_tears, seller_address, condition_summary, session['user_id']))
        product_id = cursor.lastrowid
        conn.commit()
        conn.close()

        db = _get_firestore_db()
        if db is not None:
            try:
                product_data = {
                    'title': title,
                    'brand': brand,
                    'category': category,
                    'size': size,
                    'color': color,
                    'gender': gender,
                    'asking_price': asking_price,
                    'image_url': image_url,
                    'images': images_json,
                    'description': description,
                    'tags': tags,
                    'times_worn': int(times_worn),
                    'seller_condition': seller_condition,
                    'has_tears': has_tears,
                    'seller_address': seller_address,
                    'condition_summary': condition_summary,
                    'seller_id': session['user_id'],
                    'status': 'available',
                }
                db.collection('Products').document(str(product_id)).set(product_data)
            except Exception:
                pass

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

    db = _get_firestore_db()
    if db is not None:
        try:
            db.collection('Products').document(str(product_id)).delete()
        except Exception:
            pass

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
    cursor.execute('DELETE FROM Products WHERE id = ?', (product_id,))
    conn.commit()
    conn.close()
    
    flash('Listing deleted successfully.')
    return redirect(url_for('seller_listings'))


@app.route('/listing/<int:product_id>/edit', methods=['GET', 'POST'])
def edit_listing(product_id):
    if 'user_id' not in session:
        flash('Please log in to edit your listing.')
        return redirect(url_for('login'))

    product = get_product_by_id(product_id)
    if not product or product['seller_id'] != session['user_id']:
        flash('Listing not found or you do not have permission to edit it.')
        return redirect(url_for('seller_listings'))

    seller_address = product.get('seller_address', '') or ''
    parts = [p.strip() for p in seller_address.split(',')]
    if len(parts) == 3:
        seller_locality, seller_city, seller_province = parts
    elif len(parts) == 2:
        seller_city, seller_province = parts
        seller_locality = ''
    else:
        seller_city = seller_address
        seller_province = ''
        seller_locality = ''

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
        seller_province = request.form.get('seller_province', '').strip()
        seller_locality = request.form.get('seller_locality', '').strip()
        if seller_locality:
            seller_address = f"{seller_locality}, {seller_city}, {seller_province}"
        else:
            seller_address = f"{seller_city}, {seller_province}"
        asking_price = float(request.form['asking_price'])
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

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE Products SET title=?, brand=?, category=?, size=?, color=?, gender=?, asking_price=?,
                image_url=?, images=?, description=?, tags=?, times_worn=?, seller_condition=?,
                has_tears=?, seller_address=?, condition_summary=?
            WHERE id=?
        ''', (title, brand, category, size, color, gender, asking_price, image_url, images_json, description, tags, int(times_worn), seller_condition, has_tears, seller_address, condition_summary, product_id))
        conn.commit()
        conn.close()

        db = _get_firestore_db()
        if db is not None:
            try:
                product_data = {
                    'title': title,
                    'brand': brand,
                    'category': category,
                    'size': size,
                    'color': color,
                    'gender': gender,
                    'asking_price': asking_price,
                    'image_url': image_url,
                    'images': images_json,
                    'description': description,
                    'tags': tags,
                    'times_worn': int(times_worn),
                    'seller_condition': seller_condition,
                    'has_tears': has_tears,
                    'seller_address': seller_address,
                    'condition_summary': condition_summary,
                    'seller_id': session['user_id'],
                    'status': product.get('status', 'available'),
                }
                db.collection('Products').document(str(product_id)).set(product_data)
            except Exception:
                pass

        flash('Listing updated successfully.')
        return redirect(url_for('seller_listings'))

    return render_template('edit_listing.html', product=product, seller_city=seller_city, seller_province=seller_province, seller_locality=seller_locality, product_images=product_images)


@app.route('/account', methods=['GET', 'POST'])
def account_settings():
    if 'user_id' not in session:
        flash('Please log in to update your account settings.')
        return redirect(url_for('login'))

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
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET contact_preference = ?, contact_phone = ?, contact_email = ? WHERE user_id = ?', (contact_preference, contact_phone, contact_email, session['user_id']))
            conn.commit()
            conn.close()

            db = _get_firestore_db()
            if db is not None:
                try:
                    db.collection('users').document(str(session['user_id'])).set({
                        'contact_preference': contact_preference,
                        'contact_phone': contact_phone,
                        'contact_email': contact_email,
                    }, merge=True)
                except Exception:
                    pass

            flash('Contact preferences updated successfully.')
            return redirect(url_for('account_settings'))

        conn.close()
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
    conn = get_db_connection()
    cursor = conn.cursor()
    listings = [dict(row) for row in cursor.execute('SELECT * FROM Products ORDER BY created_at DESC').fetchall()]
    users = [dict(row) for row in cursor.execute('SELECT * FROM users ORDER BY join_date DESC').fetchall()]
    listing_counts_rows = cursor.execute('SELECT seller_id, COUNT(*) as cnt FROM Products GROUP BY seller_id').fetchall()
    listing_counts = {row['seller_id']: row['cnt'] for row in listing_counts_rows}
    conn.close()
    
    return render_template('admin_dashboard.html',
        section=section,
        listings=listings,
        users=users,
        listing_counts=listing_counts,
        current_admin_id=session.get('user_id')
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

    db = _get_firestore_db()
    if db is not None:
        try:
            user_doc = db.collection('users').document(str(user_id))
            user_doc.delete()

            products_query = db.collection('Products').where('seller_id', '==', user_id).stream()
            for doc in products_query:
                doc.delete()

            questions_query = db.collection('questions').where('user_id', '==', user_id).stream()
            for doc in questions_query:
                doc.delete()

            answers_query = db.collection('answers').where('user_id', '==', user_id).stream()
            for doc in answers_query:
                doc.delete()
        except Exception:
            pass

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM answers WHERE user_id = ?', (user_id,))
    cursor.execute('DELETE FROM questions WHERE user_id = ?', (user_id,))
    cursor.execute('DELETE FROM Products WHERE seller_id = ?', (user_id,))
    cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

    flash('User deleted successfully.')
    return redirect(url_for('admin_dashboard', section='users'))

@app.route('/admin/listing/<int:product_id>/delete', methods=['POST'])
def admin_delete_listing(product_id):
    guard = require_admin()
    if guard is not None:
        return guard
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
    cursor.execute('DELETE FROM Products WHERE id = ?', (product_id,))
    conn.commit()
    conn.close()
    flash('Listing removed.')
    return redirect(url_for('admin_dashboard', section='listings'))


@app.route('/messages')
def messages_page():
    if 'user_id' not in session:
        flash('Please log in to view messages.')
        return redirect(url_for('login'))
    return render_template('messages.html')

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
    cursor = conn.cursor()
    cursor.execute('INSERT INTO questions (product_id, user_id, content) VALUES (?, ?, ?)', (product_id, session['user_id'], content))
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
        contact_preference = request.form.get('contact_preference', 'whatsapp')
        if contact_preference not in ('whatsapp', 'email'):
            contact_preference = 'whatsapp'
        address = sanitize_input(request.form.get('address', ''))
        city = sanitize_input(request.form.get('city', ''))
        province = sanitize_input(request.form.get('province', ''))
        postal_code = sanitize_input(request.form.get('postal_code', ''))
        bio = sanitize_input(request.form.get('bio', ''))

        name_error = ''
        email_error = ''
        username_error = ''
        password_error = ''
        phone_error = ''
        address_error = ''
        city_error = ''
        general_error = ''

        if not name:
            name_error = 'Full name is required.'
        if not email:
            email_error = 'Email address is required.'
        elif not validate_email(email):
            email_error = 'Please provide a valid email address.'
        if not password:
            password_error = 'Password is required.'
        if contact_preference == 'whatsapp' and not phone:
            phone_error = 'Phone number is required for WhatsApp contact.'
        if not address:
            address_error = 'Address is required.'
        if not city:
            city_error = 'City is required.'

        cursor = None
        conn = None
        try:
            if not any([name_error, email_error, password_error, phone_error, address_error, city_error, username_error]):
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT user_id FROM users WHERE lower(email) = lower(?)', (email,))
                if cursor.fetchone():
                    email_error = 'An account with this email already exists.'

                if username:
                    cursor.execute('SELECT user_id FROM users WHERE username IS NOT NULL AND lower(username) = lower(?)', (username,))
                    if cursor.fetchone():
                        username_error = 'This username is already taken.'

                fire_user = find_user_by_email_firestore(email)
                if fire_user:
                    email_error = 'An account with this email already exists.'

            if any([name_error, email_error, username_error, password_error, phone_error, address_error, city_error]):
                general_error = 'Please correct the errors below.'

            if not any([name_error, email_error, username_error, password_error, phone_error, address_error, city_error]):
                password_hash = generate_password_hash(password)
                join_date = datetime.utcnow()

                cursor.execute('''
                    INSERT INTO users (name, username, email, password, phone, address, street_address, city, province, postal_code, bio, join_date, contact_preference, contact_phone, contact_email)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (name, username, email, password_hash, phone, address, address, city, province, postal_code, bio, join_date, contact_preference, phone, email))
                conn.commit()

                db = _get_firestore_db()
                if db is not None:
                    try:
                        user_data = {
                            'name': name,
                            'username': username,
                            'email': email,
                            'password': password_hash,
                            'phone': phone,
                            'address': address,
                            'street_address': address,
                            'city': city,
                            'province': province,
                            'postal_code': postal_code,
                            'bio': bio,
                            'join_date': join_date,
                            'email_verified': 0,
                            'phone_verified': 0,
                            'profile_picture': '',
                            'seller_rating': 0.0,
                            'total_sales': 0,
                            'contact_preference': contact_preference,
                            'contact_phone': phone,
                            'contact_email': email,
                        }
                        db.collection('users').add(user_data)
                    except Exception:
                        pass

                flash('Account created successfully! Please log in to continue.', 'success')
                return redirect(url_for('login'))
        except Exception as e:
            msg = str(e).lower()
            if conn:
                conn.rollback()
            if 'unique' in msg or 'constraint' in msg:
                general_error = 'An account with this email or username already exists.'
            else:
                general_error = 'We could not create your account right now. Please try again.'
        finally:
            if conn:
                conn.close()

        return render_template('signup.html',
            name=name, email=email, username=username,
            name_error=name_error, email_error=email_error, username_error=username_error,
            password_error=password_error, phone_error=phone_error, address_error=address_error,
            city_error=city_error, general_error=general_error
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

            fire_user = find_user_by_email_firestore(email_value)
            if fire_user and fire_user.get('password') and check_password_hash(fire_user['password'], password):
                session.clear()
                session.permanent = True
                session['user_id'] = fire_user['user_id']
                session['user_name'] = fire_user.get('name', '')
                session['email_verified'] = bool(fire_user.get('email_verified', 0))
                session['phone_verified'] = bool(fire_user.get('phone_verified', 0))
                flash(f'Welcome back, {fire_user.get("name", "")}!', 'success')
                return redirect(url_for('index'))

            password_error = 'Incorrect password.'
            general_error = 'Please correct the errors below.'

    return render_template('login.html', email_value=email_value, email_error=email_error, password_error=password_error, general_error=general_error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True, port=8080)
