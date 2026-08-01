import os
import json
import logging
from datetime import datetime

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    if not firebase_admin._apps:
        cred_path = os.environ.get('FIREBASE_CREDENTIALS', '/home/Aroojatif/thrift/serviceAccountKey.json')
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    _db = firestore.client()
    _FIRESTORE_AVAILABLE = True
except Exception as e:
    logging.error(f"Firebase initialization failed: {e}")
    _db = None
    _FIRESTORE_AVAILABLE = False


def get_firestore_db():
    return _db


def is_firestore_available():
    return _FIRESTORE_AVAILABLE and _db is not None


# ============================
# User helpers
# ============================

def fs_get_user(uid):
    if not is_firestore_available():
        return None
    try:
        doc = _db.collection('users').document(str(uid)).get()
        if doc.exists:
            data = doc.to_dict()
            data['user_id'] = int(doc.id) if doc.id.isdigit() else doc.id
            return data
    except Exception as e:
        logging.error(f"Firestore get_user error: {e}")
    return None


def fs_get_user_by_email(email):
    if not is_firestore_available():
        return None
    try:
        docs = _db.collection('users').where('email', '==', email).stream()
        for doc in docs:
            data = doc.to_dict()
            data['user_id'] = int(doc.id) if doc.id.isdigit() else doc.id
            return data
    except Exception as e:
        logging.error(f"Firestore get_user_by_email error: {e}")
    return None


def fs_create_user(data):
    if not is_firestore_available():
        return None
    try:
        uid = data.get('user_id')
        if uid:
            _db.collection('users').document(str(uid)).set(data)
        else:
            doc_ref = _db.collection('users').add(data)
            uid = doc_ref[1].id
        return uid
    except Exception as e:
        logging.error(f"Firestore create_user error: {e}")
        return None


def fs_update_user(uid, data):
    if not is_firestore_available():
        return False
    try:
        _db.collection('users').document(str(uid)).set(data, merge=True)
        return True
    except Exception as e:
        logging.error(f"Firestore update_user error: {e}")
        return False


def fs_delete_user(uid):
    if not is_firestore_available():
        return False
    try:
        _db.collection('users').document(str(uid)).delete()
        return True
    except Exception as e:
        logging.error(f"Firestore delete_user error: {e}")
        return False


# ============================
# Product helpers
# ============================

def fs_get_product(pid):
    if not is_firestore_available():
        return None
    try:
        doc = _db.collection('Products').document(str(pid)).get()
        if doc.exists:
            data = doc.to_dict()
            data['id'] = int(doc.id) if doc.id.isdigit() else doc.id
            return data
    except Exception as e:
        logging.error(f"Firestore get_product error: {e}")
    return None


def fs_get_products_by_seller(seller_id):
    if not is_firestore_available():
        return []
    try:
        docs = _db.collection('Products').where('seller_id', '==', seller_id).stream()
        products = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = int(doc.id) if doc.id.isdigit() else doc.id
            products.append(data)
        return products
    except Exception as e:
        logging.error(f"Firestore get_products_by_seller error: {e}")
        return []


def fs_get_all_products(category=None):
    if not is_firestore_available():
        return []
    try:
        docs = _db.collection('Products').where('status', '==', 'available').stream()
        products = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = int(doc.id) if doc.id.isdigit() else doc.id
            if category and data.get('category') != category:
                continue
            products.append(data)
        return products
    except Exception as e:
        logging.error(f"Firestore get_all_products error: {e}")
        return []


def fs_create_product(data):
    if not is_firestore_available():
        return None
    try:
        pid = data.get('id')
        if pid:
            _db.collection('Products').document(str(pid)).set(data)
        else:
            doc_ref = _db.collection('Products').add(data)
            pid = doc_ref[1].id
        return pid
    except Exception as e:
        logging.error(f"Firestore create_product error: {e}")
        return None


def fs_update_product(pid, data):
    if not is_firestore_available():
        return False
    try:
        _db.collection('Products').document(str(pid)).set(data, merge=True)
        return True
    except Exception as e:
        logging.error(f"Firestore update_product error: {e}")
        return False


def fs_delete_product(pid):
    if not is_firestore_available():
        return False
    try:
        _db.collection('Products').document(str(pid)).delete()
        return True
    except Exception as e:
        logging.error(f"Firestore delete_product error: {e}")
        return False


# ============================
# Question helpers
# ============================

def fs_create_question(data):
    if not is_firestore_available():
        return None
    try:
        doc_ref = _db.collection('questions').add(data)
        return doc_ref[1].id
    except Exception as e:
        logging.error(f"Firestore create_question error: {e}")
        return None


def fs_get_questions_by_product(product_id):
    if not is_firestore_available():
        return []
    try:
        docs = _db.collection('questions').where('product_id', '==', product_id).stream()
        questions = []
        for doc in docs:
            data = doc.to_dict()
            data['question_id'] = int(doc.id) if doc.id.isdigit() else doc.id
            questions.append(data)
        return questions
    except Exception as e:
        logging.error(f"Firestore get_questions_by_product error: {e}")
        return []


def fs_delete_questions_by_product(product_id):
    if not is_firestore_available():
        return False
    try:
        docs = _db.collection('questions').where('product_id', '==', product_id).stream()
        for doc in docs:
            doc.reference.delete()
        return True
    except Exception as e:
        logging.error(f"Firestore delete_questions_by_product error: {e}")
        return False


# ============================
# Answer helpers
# ============================

def fs_create_answer(data):
    if not is_firestore_available():
        return None
    try:
        doc_ref = _db.collection('answers').add(data)
        return doc_ref[1].id
    except Exception as e:
        logging.error(f"Firestore create_answer error: {e}")
        return None


def fs_get_answers_by_question(question_id):
    if not is_firestore_available():
        return []
    try:
        docs = _db.collection('answers').where('question_id', '==', question_id).stream()
        answers = []
        for doc in docs:
            data = doc.to_dict()
            data['answer_id'] = int(doc.id) if doc.id.isdigit() else doc.id
            answers.append(data)
        return answers
    except Exception as e:
        logging.error(f"Firestore get_answers_by_question error: {e}")
        return []


# ============================
# Message helpers
# ============================

def fs_create_message(data):
    if not is_firestore_available():
        return None
    try:
        doc_ref = _db.collection('messages').add(data)
        return doc_ref[1].id
    except Exception as e:
        logging.error(f"Firestore create_message error: {e}")
        return None


def fs_get_all_messages():
    if not is_firestore_available():
        return []
    try:
        docs = _db.collection('messages').stream()
        messages = []
        for doc in docs:
            data = doc.to_dict()
            data['message_id'] = int(doc.id) if doc.id.isdigit() else doc.id
            messages.append(data)
        return messages
    except Exception as e:
        logging.error(f"Firestore get_all_messages error: {e}")
        return []


# ============================
# Migration
# ============================

def migrate_to_firestore():
    if not is_firestore_available():
        logging.error("Firestore not available. Cannot migrate.")
        return False

    import sqlite3
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    batch = _db.batch()

    # Migrate users
    cur.execute("SELECT * FROM users")
    users = cur.fetchall()
    for user in users:
        user_data = dict(user)
        uid = user_data.get('user_id')
        if uid:
            doc_ref = _db.collection('users').document(str(uid))
            if not doc_ref.get().exists:
                batch.set(doc_ref, user_data)
                logging.info(f"Migrated user {uid}")
            else:
                logging.info(f"User {uid} already exists, skipping")

    # Migrate products
    cur.execute("SELECT * FROM Products")
    products = cur.fetchall()
    for product in products:
        product_data = dict(product)
        pid = product_data.get('id')
        
        # Normalize images field from JSON string to list
        if product_data.get('images') and isinstance(product_data['images'], str):
            try:
                product_data['images'] = json.loads(product_data['images'])
            except Exception:
                pass
        
        if pid:
            doc_ref = _db.collection('Products').document(str(pid))
            if not doc_ref.get().exists:
                batch.set(doc_ref, product_data)
                logging.info(f"Migrated product {pid}")
            else:
                logging.info(f"Product {pid} already exists, skipping")

    # Migrate questions
    cur.execute("SELECT * FROM questions")
    questions = cur.fetchall()
    for q in questions:
        q_data = dict(q)
        qid = q_data.get('question_id')
        if qid:
            doc_ref = _db.collection('questions').document(str(qid))
            if not doc_ref.get().exists:
                batch.set(doc_ref, q_data)
                logging.info(f"Migrated question {qid}")
            else:
                logging.info(f"Question {qid} already exists, skipping")

    # Migrate answers
    cur.execute("SELECT * FROM answers")
    answers = cur.fetchall()
    for a in answers:
        a_data = dict(a)
        aid = a_data.get('answer_id')
        if aid:
            doc_ref = _db.collection('answers').document(str(aid))
            if not doc_ref.get().exists:
                batch.set(doc_ref, a_data)
                logging.info(f"Migrated answer {aid}")
            else:
                logging.info(f"Answer {aid} already exists, skipping")

    # Migrate messages
    cur.execute("SELECT * FROM messages")
    messages = cur.fetchall()
    for m in messages:
        m_data = dict(m)
        mid = m_data.get('message_id')
        if mid:
            doc_ref = _db.collection('messages').document(str(mid))
            if not doc_ref.get().exists:
                batch.set(doc_ref, m_data)
                logging.info(f"Migrated message {mid}")
            else:
                logging.info(f"Message {mid} already exists, skipping")

    batch.commit()
    conn.close()
    logging.info("Migration complete")
    return True
