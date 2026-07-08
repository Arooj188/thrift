import json
import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from ai_service import analyze_item

# CLOUDINARY IMPORTS
import cloudinary
import cloudinary.uploader

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_production_key_98765')

# Configure Cloudinary using environment variables
cloudinary.config(
  cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'),
  api_key = os.environ.get('CLOUDINARY_API_KEY'),
  api_secret = os.environ.get('CLOUDINARY_API_SECRET')
)

DATABASE_URL = os.environ.get('DATABASE_URL')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')

def dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

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
        return psycopg2.connect(url)
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
    
    if not DATABASE_URL:
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_seller_id ON Products(seller_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_buyer_id ON orders(buyer_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_seller_id ON orders(seller_id)')
    
    conn.commit()
    conn.close()

def ensure_schema():
    if DATABASE_URL:
        return
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
    ]
    for column_name, definition in user_columns:
        if not schema_has_column(conn, 'users', column_name):
            cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} {definition}")

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
            cursor.execute(f"ALTER TABLE Products ADD COLUMN {column_name} {definition}")

    order_columns = [
        ("buyer_name", "TEXT"),
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
    ]
    if schema_has_column(conn, 'orders', 'order_id'):
        for column_name, definition in order_columns:
            if not schema_has_column(conn, 'orders', column_name):
                cursor.execute(f"ALTER TABLE orders ADD COLUMN {column_name} {definition}")

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
                # Upload directly to Cloudinary using the file stream
                upload_result = cloudinary.uploader.upload(image_file)
                # Grab the secure web link of the uploaded image
                image_url = upload_result['secure_url']
                saved_paths.append(image_url)
            except Exception as e:
                print(f"Cloudinary upload error: {e}")
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

try:
    init_db()
    ensure_schema()
except Exception as e:
    print(f"Database initialization status: {e}")

def send_live_email(to_email, buyer_name, item_title, price, tracking_number, destination):
    if not RESEND_API_KEY:
        print("\n" + "="*60)
        print(f"[CONSOLE EMAIL OUTBOX] SENT TO: {to_email}")
        print("="*60)
        print(f"Dear {buyer_name},")
        print(f"Your order on thrift has been placed successfully!")
        print(f"Item: {item_title} - Total Paid: Rs. {price:.2f}")
        print(f"Tracking Number: {tracking_number}")
        print(f"Shipping To: {destination}")
        print("="*60 + "\n")
        return False
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
    return render_template('product_details.html', product=product, image_list=image_list)

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
    buyer_email = request.form.get('buyer_email', '').strip()
    buyer_phone = request.form.get('buyer_phone', '').strip()
    street = request.form.get('buyer_address_street', '').strip()
    city = request.form.get('buyer_city', '').strip()
    province = request.form.get('buyer_province', '').strip()
    postal_code = request.form.get('buyer_postal_code', '').strip()
    delivery_note = request.form.get('delivery_note', '').strip()

    required_fields = [buyer_name, buyer_email, buyer_phone, street, city, province, postal_code]
    if not all(required_fields):
        flash('Please complete all shipping fields before placing your order.')
        return redirect(url_for('checkout'))

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

        if DATABASE_URL:
            cursor.execute('''
                INSERT INTO orders (product_id, buyer_id, seller_id, status, buyer_name, buyer_email, buyer_phone,
                    buyer_street_address, buyer_city, buyer_province, buyer_postal_code, delivery_note,
                    seller_amount, platform_commission, payout_status, payout_date, payment_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING order_id
            ''', (
                product['id'], buyer_id, seller_id, 'Paid', buyer_name, buyer_email, buyer_phone,
                street, city, province, postal_code, delivery_note,
                seller_amount, platform_commission, 'Pending', None, datetime.utcnow(),
            ))
            order_id = cursor.fetchone()[0]
            cursor.execute('UPDATE Products SET status=%s, tracking_number=%s, order_id=%s WHERE id=%s',
                           ('sold', tracking_num, order_id, product['id']))
        else:
            cursor.execute('''
                INSERT INTO orders (product_id, buyer_id, seller_id, status, buyer_name, buyer_email, buyer_phone,
                    buyer_street_address, buyer_city, buyer_province, buyer_postal_code, delivery_note,
                    seller_amount, platform_commission, payout_status, payout_date, payment_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                product['id'], buyer_id, seller_id, 'Paid', buyer_name, buyer_email, buyer_phone,
                street, city, province, postal_code, delivery_note,
                seller_amount, platform_commission, 'Pending', None, datetime.utcnow(),
            ))
            order_id = cursor.lastrowid
            cursor.execute('UPDATE Products SET status=?, tracking_number=?, order_id=? WHERE id=?',
                           ('sold', tracking_num, order_id, product['id']))

        send_live_email(buyer_email, buyer_name, product['title'], product['asking_price'], tracking_num, f"{street}, {city}, {province}, {postal_code}")

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
        quality_score = ai_result['score']
        condition_summary = ai_result['summary']
        auto_category = ai_result.get('category')
        duplicate = ai_result.get('duplicate', False)
        if auto_category and auto_category != category:
            category = auto_category
        if duplicate:
            flash('Warning: this listing appears similar to another item already on the marketplace.')

        if DATABASE_URL:
            cursor.execute('''
                INSERT INTO Products (title, brand, category, size, color, gender, asking_price, image_url, images, description, tags, times_worn, seller_condition, has_tears, seller_address, quality_score, condition_summary, seller_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (title, brand, category, size, color, gender, asking_price, image_url, images_json, description, tags, int(times_worn), seller_condition, has_tears, seller_address, int(quality_score), condition_summary, session['user_id']))
        else:
            cursor.execute('''
                INSERT INTO Products (title, brand, category, size, color, gender, asking_price, image_url, images, description, tags, times_worn, seller_condition, has_tears, seller_address, quality_score, condition_summary, seller_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (title, brand, category, size, color, gender, asking_price, image_url, images_json, description, tags, int(times_worn), seller_condition, has_tears, seller_address, int(quality_score), condition_summary, session['user_id']))
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


@app.route('/listing/<int:product_id>/edit', methods=['GET', 'POST'])
def edit_listing(product_id):
    if 'user_id' not in session:
        flash('Please log in to edit your listing.')
        return redirect(url_for('login'))

    product = get_product_by_id(product_id)
    if not product or product['seller_id'] != session['user_id']:
        flash('Listing not found or you do not have permission to edit it.')
        return redirect(url_for('seller_listings'))

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
        existing_images = json.loads(product['images']) if product['images'] else []
        new_images = existing_images + image_paths
        images_json = json.dumps(new_images)
        image_url = image_paths[0] if image_paths else product['image_url']

        ai_result = analyze_item(category, times_worn, has_tears, description, tags)
        quality_score = ai_result['score']
        condition_summary = ai_result['summary']

        conn = get_db_connection()
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute('''
                UPDATE Products SET title=%s, brand=%s, category=%s, size=%s, color=%s, gender=%s, asking_price=%s,
                    image_url=%s, images=%s, description=%s, tags=%s, times_worn=%s, seller_condition=%s,
                    has_tears=%s, seller_address=%s, quality_score=%s, condition_summary=%s
                WHERE id=%s
            ''', (title, brand, category, size, color, gender, asking_price, image_url, images_json, description, tags, int(times_worn), seller_condition, has_tears, seller_address, int(quality_score), condition_summary, product_id))
        else:
            cursor.execute('''
                UPDATE Products SET title=?, brand=?, category=?, size=?, color=?, gender=?, asking_price=?,
                    image_url=?, images=?, description=?, tags=?, times_worn=?, seller_condition=?,
                    has_tears=?, seller_address=?, quality_score=?, condition_summary=?
                WHERE id=?
            ''', (title, brand, category, size, color, gender, asking_price, image_url, images_json, description, tags, int(times_worn), seller_condition, has_tears, seller_address, int(quality_score), condition_summary, product_id))
        conn.commit()
        conn.close()

        flash('Listing updated successfully.')
        return redirect(url_for('seller_listings'))

    return render_template('edit_listing.html', product=product)


@app.route('/listing/<int:product_id>/delete', methods=['POST'])
def delete_listing(product_id):
    if 'user_id' not in session:
        flash('Please log in to delete your listing.')
        return redirect(url_for('login'))

    product = get_product_by_id(product_id)
    if not product or product['seller_id'] != session['user_id']:
        flash('Unable to delete the listing.')
        return redirect(url_for('seller_listings'))

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

    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute('UPDATE Products SET status = %s WHERE id = %s', ('sold', product_id))
    else:
        cursor.execute('UPDATE Products SET status = ? WHERE id = ?', ('sold', product_id))
    conn.commit()
    conn.close()
    flash('Listing has been marked as sold.')
    return redirect(url_for('seller_listings'))


@app.route('/orders', methods=['GET', 'POST'])
def track_orders():
    orders = []
    email_searched = ""
    if request.method == 'POST':
        email_searched = request.form.get('email', '').strip().lower()
        conn = get_db_connection()
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute('''
                SELECT o.*, p.title AS product_title, p.brand, p.color, p.size, p.category,
                    o.buyer_name, o.buyer_email, o.buyer_phone
                FROM orders o
                JOIN Products p ON o.product_id = p.id
                WHERE lower(o.buyer_email) = %s
                ORDER BY o.order_date DESC
            ''', (email_searched,))
            columns = [desc[0] for desc in cursor.description]
            orders = [dict(zip(columns, row)) for row in cursor.fetchall()]
        else:
            cursor.execute('''
                SELECT o.*, p.title AS product_title, p.brand, p.color, p.size, p.category,
                    o.buyer_name, o.buyer_email, o.buyer_phone
                FROM orders o
                JOIN Products p ON o.product_id = p.id
                WHERE lower(o.buyer_email) = ?
                ORDER BY o.order_date DESC
            ''', (email_searched,))
            orders = [dict(row) for row in cursor.fetchall()]
        conn.close()
    return render_template('orders.html', orders=orders, email=email_searched)

@app.route('/admin-portal')
def admin_portal():
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
        sold_items = [dict(zip(columns, row)) for row in cursor.fetchall()]
    else:
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
        sold_items = [dict(row) for row in cursor.fetchall()]
    conn.close()
    total_revenue = round(sum(item.get('product_price', 0) or 0 for item in sold_items), 2)
    total_commission = round(sum(item.get('platform_commission', 0) or 0 for item in sold_items), 2)
    pending_payouts = sum(1 for item in sold_items if item.get('payout_status') == 'Pending')
    return render_template('admin.html', sold_items=sold_items, total_revenue=total_revenue, total_commission=total_commission, pending_payouts=pending_payouts)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name'].strip()
        username = request.form.get('username', '').strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        phone = request.form['phone'].strip()
        address = request.form['address'].strip()
        city = request.form['city'].strip()
        province = request.form.get('province', '').strip()
        postal_code = request.form.get('postal_code', '').strip()
        bio = request.form.get('bio', '').strip()

        if not (name and email and password and phone and address and city):
            flash('Please complete all required fields.')
            return redirect(url_for('signup'))

        password_hash = generate_password_hash(password)
        join_date = datetime.utcnow()

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            if DATABASE_URL:
                cursor.execute('''
                    INSERT INTO users (name, username, email, password, phone, address, street_address, city, province, postal_code, bio, join_date)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (name, username, email, password_hash, phone, address, address, city, province, postal_code, bio, join_date))
            else:
                cursor.execute('''
                    INSERT INTO users (name, username, email, password, phone, address, street_address, city, province, postal_code, bio, join_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (name, username, email, password_hash, phone, address, address, city, province, postal_code, bio, join_date))
            conn.commit()
            flash('Account created successfully! Please log in to continue.')
            return redirect(url_for('login'))
        except Exception as e:
            flash('A user with that email or username may already exist.')
            return redirect(url_for('signup'))
        finally:
            conn.close()

    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor()

        if DATABASE_URL:
            cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
            columns = [desc[0] for desc in cursor.description]
            row = cursor.fetchone()
            user = dict(zip(columns, row)) if row else None
        else:
            cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
            user = cursor.fetchone()

        conn.close()

        if user and check_password_hash(user['password'], password):
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
    # Clear out the browser session memory to log the user out safely
    session.clear()
    return redirect(url_for('index'))

@app.route('/admin/orders')
def admin_orders():
    conn = get_db_connection()
    cursor = conn.cursor()
    if DATABASE_URL:
        cursor.execute('''
            SELECT o.*, p.title AS product_title, p.asking_price AS product_price,
                s.name AS seller_name, s.phone AS seller_phone, s.address AS seller_address, s.city AS seller_city,
                b.name AS buyer_name, b.phone AS buyer_phone, b.address AS buyer_address, b.city AS buyer_city
            FROM orders o
            JOIN Products p ON o.product_id = p.id
            JOIN users s ON o.seller_id = s.user_id
            JOIN users b ON o.buyer_id = b.user_id
            ORDER BY o.order_id DESC
        ''')
        columns = [desc[0] for desc in cursor.description]
        orders = [dict(zip(columns, row)) for row in cursor.fetchall()]
    else:
        cursor.execute('''
            SELECT o.*, p.title AS product_title, p.asking_price AS product_price,
                s.name AS seller_name, s.phone AS seller_phone, s.address AS seller_address, s.city AS seller_city,
                b.name AS buyer_name, b.phone AS buyer_phone, b.address AS buyer_address, b.city AS buyer_city
            FROM orders o
            JOIN Products p ON o.product_id = p.id
            JOIN users s ON o.seller_id = s.user_id
            JOIN users b ON o.buyer_id = b.user_id
            ORDER BY o.order_id DESC
        ''')
        orders = [dict(row) for row in cursor.fetchall()]
    conn.close()
    total_commission = round(sum(order.get('platform_commission') or 0 for order in orders), 2)
    pending_payouts = sum(1 for order in orders if order.get('payout_status') == 'Pending')
    return render_template('admin.html', sold_items=orders, total_revenue=round(sum(order.get('product_price', 0) or 0 for order in orders), 2), total_commission=total_commission, pending_payouts=pending_payouts)


if __name__ == '__main__':
    app.run(debug=True, port=8080)
