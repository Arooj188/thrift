import requests
import sqlite3
import os

base = 'http://127.0.0.1:8080'

with requests.Session() as s:
    s.post(base + '/login', data={'email': 'aroojatifamna@gmail.com', 'password': 'weirdbearhehe17!'}, allow_redirects=False)
    
    # Create a product
    png_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\xf8\x00\x00\x00\x01\x00\x01\x00\x00\x00\x00IEND\xaeB\x60\x82'
    data = {
        'title': 'Home Page Test',
        'brand': 'TestBrand',
        'category': 'Clothing',
        'size': 'M',
        'color': 'Blue',
        'gender': '',
        'tags': '',
        'description': 'Test',
        'times_worn': '1',
        'has_tears': 'None - Perfect Condition',
        'seller_condition': 'Good',
        'seller_address': 'Test Address',
        'asking_price': '1000'
    }
    files = {'images': ('home_test.png', png_bytes, 'image/png')}
    s.post(base + '/sell', data=data, files=files)
    
    # Get product ID
    conn = sqlite3.connect('C:/Users/HP/Documents/thrift/database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, status FROM Products WHERE title = ?', ('Home Page Test',))
    pid, status = cursor.fetchone()
    print(f'Product ID: {pid}, status: {status}')
    conn.close()
    
    # Check home page
    r = s.get(base + '/')
    print(f'Home status: {r.status_code}')
    print(f'Product in home: {"Home Page Test" in r.text}')
    
    # Check product details
    r = s.get(base + f'/product/{pid}')
    print(f'Product details status: {r.status_code}')
    print(f'Product in details: {"Home Page Test" in r.text}')
    import re
    img_srcs = re.findall(r'<img[^>]+src="([^"]+)"', r.text)
    print(f'Product details images: {img_srcs}')
    
    # Check seller listings
    r = s.get(base + '/seller/listings')
    print(f'Seller listings status: {r.status_code}')
    print(f'Product in listings: {"Home Page Test" in r.text}')
    img_srcs = re.findall(r'<img[^>]+src="([^"]+)"', r.text)
    print(f'Seller listings images: {img_srcs}')
    
    # Clean up
    conn = sqlite3.connect('C:/Users/HP/Documents/thrift/database.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM Products WHERE id = ?', (pid,))
    conn.commit()
    conn.close()

# Clean up files
for f in os.listdir('C:/Users/HP/Documents/thrift/static/uploads'):
    if 'home_test' in f:
        os.remove(os.path.join('C:/Users/HP/Documents/thrift/static/uploads', f))
        print(f'Removed: {f}')
