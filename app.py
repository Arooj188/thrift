import os
import sqlite3
import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
from ai_service import analyze_item

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=BASE_DIR, static_folder=os.path.join(BASE_DIR, 'static'))
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_production_key_98765')
app.config['UPLOAD_FOLDER'] = os.path.join(app.static_folder, 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

DATABASE_URL = os.environ.get('DATABASE_URL')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY')


def rows_as_dicts(cursor):
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def row_as_dict(cursor):
    row = cursor.fetchone()
    if not row:
        return None
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))

def get_db_connection():
    if DATABASE_URL:
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    else:
        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Keep table creation idempotent so startup is safe in all environments.
    users_pk = 'SERIAL PRIMARY KEY' if DATABASE_URL else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    products_pk = 'SERIAL PRIMARY KEY' if DATABASE_URL else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    orders_pk = 'SERIAL PRIMARY KEY' if DATABASE_URL else 'INTEGER PRIMARY KEY AUTOINCREMENT'

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS users (
            user_id {users_pk},
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            city TEXT NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Products (
            id {products_pk},
            title TEXT NOT NULL,
            brand TEXT,
            category TEXT,
            size TEXT,
            color TEXT,
            asking_price REAL,
            status TEXT DEFAULT 'available',
            image_url TEXT,
            times_worn INTEGER,
            seller_condition TEXT,
            has_tears TEXT,
            seller_address TEXT,
            quality_score INTEGER,
            condition_summary TEXT,
            suggested_price REAL,
            buyer_address TEXT,
            tracking_number TEXT,
            buyer_name TEXT,
            buyer_email TEXT,
            payout_status TEXT DEFAULT 'Pending Delivery'
        )
    '''.format(products_pk=products_pk))

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS orders (
            order_id {orders_pk},
            product_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            seller_id INTEGER NOT NULL,
            status TEXT DEFAULT 'Pending',
            order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

try:
    init_db()
except Exception as e:
    print(f"Database initialization status: {e}")

def send_live_email(to_email, buyer_name, item_title, price, tracking_number, destination):
    if not RESEND_API_KEY:
        print("\n" + "="*60)
        print(f"📧 [CONSOLE EMAIL OUTBOX] SENT TO: {to_email}")
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
        products = rows_as_dicts(cursor)
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
        product = row_as_dict(cursor)
    else:
        product = cursor.execute("SELECT * FROM Products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    if not product:
        flash("Product not found!")
        return redirect(url_for('index'))
    return render_template('product_details.html', product=product)

@app.route('/cart/add/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    if product_id not in session['cart']:
        current_cart = list(session['cart'])
        current_cart.append(product_id)
        session['cart'] = current_cart
        flash("Item added to cart!")
    return redirect(url_for('view_cart'))

@app.route('/cart')
def view_cart():
    if not session['cart']:
        return render_template('cart.html', products=[], total=0)
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholders = ','.join('%s' if DATABASE_URL else '?' for _ in session['cart'])
    cursor.execute(f"SELECT * FROM Products WHERE id IN ({placeholders}) AND status = 'available'", session['cart'])
    if DATABASE_URL:
        products = rows_as_dicts(cursor)
    else:
        products = cursor.fetchall()
    conn.close()
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
    if not session['cart']:
        return redirect(url_for('index'))
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholders = ','.join('%s' if DATABASE_URL else '?' for _ in session['cart'])
    cursor.execute(f"SELECT * FROM Products WHERE id IN ({placeholders}) AND status = 'available'", session['cart'])
    if DATABASE_URL:
        products = rows_as_dicts(cursor)
    else:
        products = cursor.fetchall()
    conn.close()
    total = sum(p['asking_price'] for p in products)
    commission = total * 0.15
    final_payout = total - commission
    return render_template('checkout.html', products=products, total=total, commission=commission, final_payout=final_payout)
@app.route('/place_order', methods=['POST'])
def place_order():
    buyer_name = request.form.get('buyer_name')
    buyer_email = request.form.get('buyer_email')
    street = request.form.get('buyer_address_street', '')
    city = request.form.get('buyer_city', '')
    zipcode = request.form.get('buyer_zip', '')
    buyer_address = f"{street}, {city}, {zipcode}"
    
    conn = get_db_connection()
    cursor = conn.cursor()
    placeholders = ','.join('%s' if DATABASE_URL else '?' for _ in session['cart'])
    cursor.execute(f"SELECT * FROM Products WHERE id IN ({placeholders}) AND status = 'available'", session['cart'])
    if DATABASE_URL:
        products = rows_as_dicts(cursor)
    else:
        products = cursor.fetchall()
        
    for product in products:
        tracking_num = f"TRK{product['id']}98765PK"
        if DATABASE_URL:
            cursor.execute('UPDATE Products SET status=%s, buyer_address=%s, tracking_number=%s, buyer_name=%s, buyer_email=%s WHERE id=%s', 
                           ('sold', buyer_address, tracking_num, buyer_name, buyer_email, product['id']))
        else:
            cursor.execute('UPDATE Products SET status=?, buyer_address=?, tracking_number=?, buyer_name=?, buyer_email=? WHERE id=?', 
                           ('sold', buyer_address, tracking_num, buyer_name, buyer_email, product['id']))
        send_live_email(buyer_email, buyer_name, product['title'], product['asking_price'], tracking_num, buyer_address)
        
    conn.commit()
    conn.close()
    session['cart'] = []
    flash("Order Placed Successfully! Real-time logistics window activated.")
    return redirect(url_for('index'))

@app.route('/sell', methods=['GET', 'POST'])
def sell():
    # Smart User Alert Check
    if 'user_id' not in session:
        # This flashes a beautiful message onto their screen instead of blocking them silently!
        flash("Please log in or create an account first to start selling your pre-loved items.")
        return redirect(url_for('login'))

    if request.method == 'POST':
        # Your clean form data gathering remains untouched below
        title = request.form['title']


    if request.method == 'POST':
        # 1. Grab all text elements out of your form fields
        title = request.form['title']
        brand = request.form['brand']
        category = request.form['category']
        size = request.form['size']
        color = request.form['color']
        times_worn = request.form['times_worn']
        has_tears = request.form['has_tears']
        seller_condition = request.form['seller_condition']
        seller_address = request.form['seller_address']
        asking_price = float(request.form['asking_price'])
        
        # 2. Extract and save the uploaded image file safely
        image_file = request.files['image']
        image_url = ""
        if image_file:
            filename = secure_filename(image_file.filename)
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_url = f"uploads/{filename}"

        # 3. Call your updated AI Service logic block
        ai_result = analyze_item(category, times_worn, has_tears)
        quality_score = ai_result['score']
        condition_summary = ai_result['summary']

        # 4. Securely write this product into your database tables
        conn = get_db_connection()
        cursor = conn.cursor()

        if DATABASE_URL:
            cursor.execute('''
                INSERT INTO Products (title, brand, category, size, color, asking_price, image_url, times_worn, seller_condition, has_tears, seller_address, quality_score, condition_summary, seller_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (title, brand, category, size, color, asking_price, image_url, int(times_worn), seller_condition, has_tears, seller_address, int(quality_score), condition_summary, session['user_id']))
        else:
            cursor.execute('''
                INSERT INTO Products (title, brand, category, size, color, asking_price, image_url, times_worn, seller_condition, has_tears, seller_address, quality_score, condition_summary, seller_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (title, brand, category, size, color, asking_price, image_url, int(times_worn), seller_condition, has_tears, seller_address, int(quality_score), condition_summary, session['user_id']))
        
        conn.commit()
        conn.close()
        
        flash("Your thrift item has been successfully listed!")
        return redirect(url_for('index'))

    return render_template('sell.html')



@app.route('/orders', methods=['GET', 'POST'])
def track_orders():
    orders = []
    email_searched = ""
    if request.method == 'POST':
        email_searched = request.form.get('email')
        conn = get_db_connection()
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute("SELECT * FROM Products WHERE buyer_email = %s AND status = 'sold'", (email_searched,))
            orders = rows_as_dicts(cursor)
        else:
            orders = cursor.execute("SELECT * FROM Products WHERE buyer_email = ? AND status = 'sold'", (email_searched,)).fetchall()
        conn.close()
    return render_template('orders.html', orders=orders, email=email_searched)

@app.route('/admin-portal')
def admin_portal():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Products WHERE status = 'sold'")
    if DATABASE_URL:
        sold_items = rows_as_dicts(cursor)
    else:
        sold_items = cursor.fetchall()
    conn.close()
    
    total_revenue = sum(item['asking_price'] for item in sold_items)
    total_commission = total_revenue * 0.15
    return render_template('admin.html', sold_items=sold_items, total_revenue=total_revenue, total_commission=total_commission)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        # Retrieve form data submitted by the user
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        phone = request.form['phone']
        address = request.form['address']
        city = request.form['city']

        connection = get_db_connection()
        cursor = connection.cursor()

        try:
            if DATABASE_URL:
                cursor.execute('''
                    INSERT INTO users (name, email, password, phone, address, city)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (name, email, password, phone, address, city))
            else:
                cursor.execute('''
                    INSERT INTO users (name, email, password, phone, address, city)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (name, email, password, phone, address, city))
            
            connection.commit()
            print(f"Success: User {name} registered!")
            return redirect(url_for('index')) # Sends them back to home page after signing up
            
        except Exception:
            # This triggers if someone tries to sign up with an email that already exists
            connection.rollback()
            print("Error: That email is already registered.")
            return "Email already exists! Please try another one."
            
        finally:
            connection.close()

    # If they are just opening the page normally (GET request), show the form
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        connection = get_db_connection()
        cursor = connection.cursor()

        # Search for a user matching the provided email
        if DATABASE_URL:
            cursor.execute('SELECT user_id, name, password FROM users WHERE email = %s', (email,))
            user = row_as_dict(cursor)
        else:
            cursor.execute('SELECT user_id, name, password FROM users WHERE email = ?', (email,))
            user = cursor.fetchone()
        connection.close()

        # Check if the user exists and the password matches exactly
        if user and user['password'] == password:
            # Save the logged-in user's details into the secure browser session memory
            session['user_id'] = user['user_id']
            session['user_name'] = user['name']
            print(f"Logged in successfully as: {user['name']}")
            return redirect(url_for('index'))
        else:
            print("Login failed: Invalid email or password.")
            return "Invalid login details. Please try again."

    return render_template('login.html')

@app.route('/logout')
def logout():
    # Clear out the browser session memory to log the user out safely
    session.clear()
    return redirect(url_for('index'))

# --- PASTE THE ADMIN ROUTE CODE HERE ---
@app.route('/admin/orders')
def admin_orders():
    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute('''
        SELECT 
            o.order_id, o.status, p.title AS product_title, p.asking_price AS price,
            s.name AS seller_name, s.phone AS seller_phone, s.address AS seller_address, s.city AS seller_city,
            b.name AS buyer_name, b.phone AS buyer_phone, b.address AS buyer_address, b.city AS buyer_city
        FROM orders o
        JOIN Products p ON o.product_id = p.id
        JOIN users s ON o.seller_id = s.user_id
        JOIN users b ON o.buyer_id = b.user_id
        ORDER BY o.order_id DESC
    ''')
    if DATABASE_URL:
        orders = rows_as_dicts(cursor)
    else:
        orders = cursor.fetchall()

    total_commission = 0.0
    for order in orders:
        total_commission += (order['price'] * 0.10)

    connection.close()
    return render_template('admin.html', sold_items=orders, total_commission=total_commission)
# ---------------------------------------

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=os.environ.get('FLASK_DEBUG') == '1')
