import sqlite3

def build_marketplace_tables():
    connection = sqlite3.connect('database.db')
    cursor = connection.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            brand TEXT,
            category TEXT,
            size TEXT,
            color TEXT,
            asking_price REAL NOT NULL,
            status TEXT DEFAULT 'available',
            image_url TEXT,
            times_worn INTEGER,
            seller_condition TEXT,
            has_tears TEXT,
            seller_address TEXT,
            quality_score INTEGER,
            condition_summary TEXT,
            seller_id INTEGER,
            FOREIGN KEY (seller_id) REFERENCES users (user_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
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
    print("Tables ensured successfully.")

if __name__ == '__main__':
    build_marketplace_tables()