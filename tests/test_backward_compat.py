import unittest
import app as app_module
from werkzeug.security import generate_password_hash
from datetime import datetime


class BackwardCompatibilityTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()
        db_path = 'database.db'
        import os
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except PermissionError:
                pass
        app_module.init_db()
        app_module.ensure_schema()
        conn = app_module.get_db_connection()
        conn.execute('DELETE FROM password_resets')
        conn.execute('DELETE FROM users')
        conn.execute('DELETE FROM Products')
        conn.execute('DELETE FROM questions')
        conn.execute('DELETE FROM answers')
        conn.execute('DELETE FROM orders')
        conn.execute('DELETE FROM messages')
        conn.commit()
        conn.close()

    def _create_user(self, email, password, name='Test User', is_admin=0):
        now = datetime.utcnow().isoformat()
        conn = app_module.get_db_connection()
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO users (name, email, password, phone, join_date, contact_preference, contact_phone, contact_email, is_admin, email_verified, phone_verified) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (name, email, generate_password_hash(password), '03001234567', now, 'whatsapp', '03001234567', email, is_admin, 1, 1)
        )
        conn.commit()
        user_id = cur.lastrowid
        conn.close()
        return user_id

    def test_old_listing_without_buyer_contact_method_uses_seller_preference(self):
        seller_id = self._create_user('seller@example.com', 'SellerPass123!')
        buyer_id = self._create_user('buyer@example.com', 'BuyerPass123!')

        conn = app_module.get_db_connection()
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO Products (title, brand, category, size, color, gender, asking_price, status, seller_id, description, times_worn, seller_condition, has_tears, seller_address, buyer_contact_method) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ('Old Jacket', 'Nike', 'Clothing', 'M', 'Black', 'Men', 1500, 'available', seller_id, 'Nice jacket', 2, 'Good', 'None - Perfect Condition', 'Lahore', None)
        )
        product_id = cur.lastrowid
        conn.commit()
        conn.close()

        self.client.post('/login', data={'email': 'buyer@example.com', 'password': 'BuyerPass123!'}, follow_redirects=False)
        resp = self.client.get(f'/product/{product_id}')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Contact Seller', resp.data)
        self.assertIn(b'Preferred method: WhatsApp', resp.data)
        self.assertNotIn(b'seller has not provided contact details', resp.data.lower())

    def test_old_listing_with_null_buyer_contact_method_in_db(self):
        seller_id = self._create_user('seller2@example.com', 'SellerPass123!')
        buyer_id = self._create_user('buyer2@example.com', 'BuyerPass123!')

        conn = app_module.get_db_connection()
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO Products (title, brand, category, size, color, gender, asking_price, status, seller_id, description, times_worn, seller_condition, has_tears, seller_address, buyer_contact_method) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ('Null Contact Jacket', 'Nike', 'Clothing', 'M', 'Black', 'Men', 1500, 'available', seller_id, 'Nice jacket', 2, 'Good', 'None - Perfect Condition', 'Lahore', None)
        )
        product_id = cur.lastrowid
        conn.commit()
        conn.close()

        self.client.post('/login', data={'email': 'buyer2@example.com', 'password': 'BuyerPass123!'}, follow_redirects=False)
        resp = self.client.get(f'/product/{product_id}')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Contact Seller', resp.data)
        self.assertIn(b'Preferred method: WhatsApp', resp.data)

    def test_old_listing_seller_prefers_email(self):
        seller_id = self._create_user('seller_email@example.com', 'SellerPass123!')
        conn = app_module.get_db_connection()
        cur = conn.cursor()
        cur.execute('UPDATE users SET contact_preference = ? WHERE user_id = ?', ('email', seller_id))
        conn.commit()
        conn.close()

        buyer_id = self._create_user('buyer_email@example.com', 'BuyerPass123!')

        conn = app_module.get_db_connection()
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO Products (title, brand, category, size, color, gender, asking_price, status, seller_id, description, times_worn, seller_condition, has_tears, seller_address, buyer_contact_method) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ('Old Email Jacket', 'Nike', 'Clothing', 'M', 'Black', 'Men', 1500, 'available', seller_id, 'Nice jacket', 2, 'Good', 'None - Perfect Condition', 'Lahore', None)
        )
        product_id = cur.lastrowid
        conn.commit()
        conn.close()

        self.client.post('/login', data={'email': 'buyer_email@example.com', 'password': 'BuyerPass123!'}, follow_redirects=False)
        resp = self.client.get(f'/product/{product_id}')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Preferred method: Email', resp.data)
        self.assertIn(b'Send Email', resp.data)
        self.assertNotIn(b'Preferred method: WhatsApp', resp.data)


if __name__ == '__main__':
    unittest.main()
