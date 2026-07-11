import sqlite3

def build_marketplace_tables():
    # Connects to your database file (or creates it fresh)
    connection = sqlite3.connect('database.db')
    cursor = connection.cursor()

    print("Step 1: Dropping any old tables to start fresh...")
    cursor.execute("DROP TABLE IF EXISTS orders;")
    cursor.execute("DROP TABLE IF EXISTS Products;")
    cursor.execute("DROP TABLE IF EXISTS users;")

    print("Step 2: Building the master Users table...")
    # Stores profiles for both buyers and sellers in Pakistan
    cursor.execute('''
         (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT NOT NULL,         -- Vital for Trax/TCS courier updates
            address TEXT NOT NULL,       -- Used for seller pickup or buyer delivery
            city TEXT NOT NULL           -- e.g., Karachi, Lahore, Islamabad
        )
    ''')

    print("Step 3: Building your original Products table with backend hooks...")
    # Notice 'seller_id' at the bottom. This links the item to its owner!
    cursor.execute('''
        CREATE TABLE Products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            brand TEXT,
            category TEXT,
            size TEXT,
            color TEXT,
            asking_price REAL NOT NULL,
            status TEXT DEFAULT 'available', -- Can switch to 'sold' on checkout
            image_url TEXT,
            times_worn INTEGER,
            seller_condition TEXT,
            has_tears TEXT,
            seller_address TEXT,
            quality_score INTEGER,
            condition_summary TEXT,
            seller_id INTEGER,               -- The crucial multi-vendor connection line
            FOREIGN KEY (seller_id) REFERENCES users (user_id)
        )
    ''')

    print("Step 4: Building the master Transactions Ledger...")
    # Tracks which buyer purchased an item from which seller's house
    cursor.execute('''
        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            buyer_id INTEGER NOT NULL,
            seller_id INTEGER NOT NULL,
            status TEXT DEFAULT 'Pending',   -- Changes to 'Shipped' or 'Delivered'
            order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES Products (id),
            FOREIGN KEY (buyer_id) REFERENCES users (user_id),
            FOREIGN KEY (seller_id) REFERENCES users (user_id)
        )
    ''')

    connection.commit()
    connection.close()
    print("🎉 Foundation completed successfully! Database is completely empty and ready.")

if __name__ == '__main__':
    build_marketplace_tables()
CREATE TABLE users