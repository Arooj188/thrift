import unittest
import random
import os
import app as app_module
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash


class MarketplaceFlowTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()
        db_path = os.path.join(os.path.dirname(app_module.__file__), 'database.db')
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except PermissionError:
                pass
        app_module.init_db()
        app_module.ensure_schema()
        # Guard against stale data when the DB file can't be removed (e.g. on
        # Windows where an open handle can raise PermissionError).
        conn = app_module.get_db_connection()
        conn.execute('DELETE FROM password_resets')
        conn.execute('DELETE FROM users')
        conn.commit()
        conn.close()

    def test_build_image_url_normalizes_local_paths(self):
        self.assertEqual(app_module.build_image_url('uploads/demo.jpg'), '/static/uploads/demo.jpg')
        self.assertEqual(app_module.build_image_url('static/uploads/demo.jpg'), '/static/uploads/demo.jpg')
        self.assertEqual(app_module.build_image_url('https://cdn.example.com/demo.jpg'), 'https://cdn.example.com/demo.jpg')

    def test_signup_allows_new_user_and_rejects_real_duplicates(self):
        email = f'testuser{random.randint(100000, 999999)}@example.com'

        signup_resp = self.client.post('/signup', data={
            'name': 'Test User',
            'email': email,
            'password': 'TestPass123!',
            'phone': '03000000000',
        }, follow_redirects=True)
        self.assertEqual(signup_resp.status_code, 200)
        self.assertIn(b'Test User', signup_resp.data)

        dup_resp = self.client.post('/signup', data={
            'name': 'Duplicate',
            'email': email,
            'password': 'OtherPass123!',
            'phone': '03000000001',
        }, follow_redirects=True)
        self.assertEqual(dup_resp.status_code, 200)
        self.assertIn(b'already exists', dup_resp.data.lower())

    # ----- password reset helpers -----

    def _create_user(self, email=None, password='TestPass123!', name='Test User'):
        if email is None:
            email = f'user{random.randint(100000, 999999)}@example.com'
        conn = app_module.get_db_connection()
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO users (name, email, password, phone, join_date, contact_preference, contact_phone, contact_email) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (name, email, generate_password_hash(password), '03000000000',
             datetime.utcnow().isoformat(), 'whatsapp', '03000000000', email)
        )
        conn.commit()
        user_id = cur.lastrowid
        conn.close()
        return user_id, email, password

    def _make_token(self, email, expires_at=None, used=False):
        user = app_module.get_user_by_email(email)
        token = f'tok_{random.randint(100000, 999999)}'
        if expires_at is None:
            expires_at = datetime.utcnow() + timedelta(minutes=60)
        ok = app_module.create_password_reset(user, email, token, expires_at)
        self.assertTrue(ok)
        if used:
            conn = app_module.get_db_connection()
            conn.execute('UPDATE password_resets SET used = 1 WHERE token = ?', (token,))
            conn.commit()
            conn.close()
        return token

    def _login_succeeds(self, email, password):
        resp = self.client.post('/login', data={'email': email, 'password': password})
        return resp.status_code == 302

    # ----- login page link -----

    def test_login_page_has_forgot_password_link(self):
        resp = self.client.get('/login')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Forgot Password?', resp.data)
        self.assertIn(b'/forgot-password', resp.data)

    # ----- forgot-password flow -----

    def test_forgot_password_unknown_email_shows_safe_message(self):
        resp = self.client.post('/forgot-password',
                                data={'email': 'does-not-exist@example.com'},
                                follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'If an account with that email exists, a password reset link has been sent.', resp.data)
        conn = app_module.get_db_connection()
        count = conn.execute('SELECT COUNT(*) FROM password_resets').fetchone()['COUNT(*)']
        conn.close()
        self.assertEqual(count, 0)

    def test_forgot_password_known_email_creates_token_and_shows_message(self):
        _, email, _ = self._create_user()
        resp = self.client.post('/forgot-password', data={'email': email}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'a password reset link has been sent.', resp.data)
        conn = app_module.get_db_connection()
        row = conn.execute('SELECT email, used FROM password_resets WHERE email = ?', (email,)).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row['email'], email)
        self.assertEqual(row['used'], 0)

    # ----- reset-password token validation -----

    def test_reset_password_missing_token_redirects(self):
        resp = self.client.get('/reset-password', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/forgot-password', resp.headers.get('Location', ''))

    def test_reset_password_invalid_token_shows_message(self):
        resp = self.client.get('/reset-password/not-a-real-token')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'This password reset link is invalid or has expired.', resp.data)
        self.assertIn(b'Request New Link', resp.data)

    def test_reset_password_expired_token_shows_message(self):
        _, email, _ = self._create_user()
        token = self._make_token(email, expires_at=datetime.utcnow() - timedelta(minutes=10))
        resp = self.client.get(f'/reset-password/{token}')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'This password reset link is invalid or has expired.', resp.data)

    def test_reset_password_used_token_shows_message(self):
        _, email, old_password = self._create_user()
        token = self._make_token(email, used=True)
        resp = self.client.get(f'/reset-password/{token}')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'This password reset link is invalid or has expired.', resp.data)

    # ----- reset-password valid flow -----

    def test_reset_password_valid_token_updates_password(self):
        _, email, old_password = self._create_user()
        token = self._make_token(email)
        # GET shows the new-password form
        get_resp = self.client.get(f'/reset-password/{token}')
        self.assertEqual(get_resp.status_code, 200)
        self.assertIn(b'New Password', get_resp.data)
        self.assertIn(b'Confirm Password', get_resp.data)

        new_password = 'BrandNewPass456!'
        post_resp = self.client.post(f'/reset-password/{token}', data={
            'password': new_password,
            'confirm_password': new_password,
        }, follow_redirects=True)
        # Should redirect to login with success flash
        self.assertEqual(post_resp.status_code, 200)
        self.assertIn(b'Your password has been reset successfully. Please log in.', post_resp.data)

        # Old password no longer works
        self.assertFalse(self._login_succeeds(email, old_password))
        # New password works
        self.assertTrue(self._login_succeeds(email, new_password))

        # Token is now invalidated (used)
        conn = app_module.get_db_connection()
        row = conn.execute('SELECT used FROM password_resets WHERE token = ?', (token,)).fetchone()
        conn.close()
        self.assertEqual(row['used'], 1)

    def test_reset_password_mismatched_passwords_rejected(self):
        _, email, _ = self._create_user()
        token = self._make_token(email)
        resp = self.client.post(f'/reset-password/{token}', data={
            'password': 'NewPass123!', 'confirm_password': 'DifferentPass123!',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Passwords do not match', resp.data)
        # Token remains valid (not used)
        conn = app_module.get_db_connection()
        row = conn.execute('SELECT used FROM password_resets WHERE token = ?', (token,)).fetchone()
        conn.close()
        self.assertEqual(row['used'], 0)

    def test_reset_password_short_password_rejected(self):
        _, email, _ = self._create_user()
        token = self._make_token(email)
        resp = self.client.post(f'/reset-password/{token}', data={
            'password': 'short', 'confirm_password': 'short',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'at least 8 characters', resp.data)


if __name__ == '__main__':
    unittest.main()
