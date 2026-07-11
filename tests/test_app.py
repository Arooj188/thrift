import unittest
import random
import app as app_module


class MarketplaceFlowTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config['TESTING'] = True
        self.client = app_module.app.test_client()
        app_module.init_db()
        app_module.ensure_schema()

    def test_build_image_url_normalizes_local_paths(self):
        self.assertEqual(app_module.build_image_url('uploads/demo.jpg'), '/static/uploads/demo.jpg')
        self.assertEqual(app_module.build_image_url('static/uploads/demo.jpg'), '/static/uploads/demo.jpg')
        self.assertEqual(app_module.build_image_url('https://cdn.example.com/demo.jpg'), 'https://cdn.example.com/demo.jpg')

    def test_signup_allows_new_user_and_rejects_real_duplicates(self):
        email = f'testuser{random.randint(100000, 999999)}@example.com'
        username = f'user{random.randint(100000, 999999)}'

        signup_resp = self.client.post('/signup', data={
            'name': 'Test User',
            'username': username,
            'email': email,
            'password': 'TestPass123!',
            'phone': '03000000000',
            'address': '1 Test Street',
            'city': 'Lahore',
            'province': 'Punjab',
            'postal_code': '54000',
            'bio': 'Testing'
        }, follow_redirects=True)
        self.assertEqual(signup_resp.status_code, 200)
        self.assertIn(b'log in', signup_resp.data.lower())

        dup_resp = self.client.post('/signup', data={
            'name': 'Duplicate',
            'username': username,
            'email': email,
            'password': 'OtherPass123!',
            'phone': '03000000001',
            'address': '2 Test Street',
            'city': 'Karachi',
            'province': 'Sindh',
            'postal_code': '75000',
            'bio': 'Duplicate'
        }, follow_redirects=True)
        self.assertEqual(dup_resp.status_code, 200)
        self.assertIn(b'already exists', dup_resp.data.lower())


if __name__ == '__main__':
    unittest.main()
