import sqlite3

def init_database():
    connection = sqlite3.connect('database.db')
    cursor = connection.cursor()

    print("Dropping mismatched tables...")
    cursor.execute("DROP TABLE IF EXISTS Products;")
    cursor.execute("DROP TABLE IF EXISTS users;")
    cursor.execute("DROP TABLE IF EXISTS orders;")

    print("Rebuilding clean unified database system...")

    # 1. USERS TABLE
    cursor.execute('''
        CREATE TABLE users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT NOT NULL,
            address TEXT NOT NULL,
            city TEXT NOT NULL
        )
    ''')

    # 2. PRODUCTS TABLE (Matches your absolute app.py schema rules!)
    cursor.execute('''
        CREATE TABLE Products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            payout_status TEXT DEFAULT 'Pending Delivery',
            seller_id INTEGER,
            FOREIGN KEY (seller_id) REFERENCES users (user_id)
        )
    ''')

    # 3. ORDERS LOG TABLE
    cursor.execute('''
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            seller_id INTEGER NOT NULL,
            status TEXT DEFAULT 'Pending',
            order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES Products (id),
            FOREIGN KEY (buyer_id) REFERENCES users (user_id),
            FOREIGN KEY (seller_id) REFERENCES users (user_id)
        )
    ''')

    connection.commit()
    connection.close()
    print("Database tables successfully synchronized!")

if __name__ == '__main__':
    init_database()
