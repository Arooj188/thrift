import os
import sqlite3

DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    if DATABASE_URL:
        import importlib
        try:
            psycopg2 = importlib.import_module('psycopg2')
        except ImportError:
            raise RuntimeError('psycopg2 is required when DATABASE_URL is configured')
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return psycopg2.connect(url)
    else:
        return sqlite3.connect('database.db')

def build_marketplace_tables():
    connection = get_db_connection()
    cursor = connection.cursor()

    print("Step 1: Dropping any old tables to start fresh...")
    cursor.execute("DROP TABLE IF EXISTS answers;")
    cursor.execute("DROP TABLE IF EXISTS questions;")
    cursor.execute("DROP TABLE IF EXISTS orders;")
    cursor.execute("DROP TABLE IF EXISTS Products;")
    cursor.execute("DROP TABLE IF EXISTS users;")

    id_autoincrement = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"

    print("Step 2: Building the master Users table...")
    cursor.execute(f'''
        CREATE TABLE users (
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

    print("Step 3: Building your original Products table with backend hooks...")
    cursor.execute(f'''
        CREATE TABLE Products (
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

    print("Step 4: Building the master Transactions Ledger...")
    cursor.execute(f'''
        CREATE TABLE orders (
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
            order_total REAL,
            payout_status TEXT DEFAULT 'Pending',
            payout_date TEXT,
            payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES Products (id),
            FOREIGN KEY (buyer_id) REFERENCES users (user_id),
            FOREIGN KEY (seller_id) REFERENCES users (user_id)
        )
    ''')

    print("Step 5: Building Questions & Answers tables...")
    cursor.execute(f'''
        CREATE TABLE questions (
            question_id {id_autoincrement},
            product_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES Products(id),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')
    cursor.execute(f'''
        CREATE TABLE answers (
            answer_id {id_autoincrement},
            question_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (question_id) REFERENCES questions(question_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')

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

    connection.commit()
    connection.close()
    print("🎉 Foundation completed successfully! Database is completely empty and ready.")

if __name__ == '__main__':
    build_marketplace_tables()
