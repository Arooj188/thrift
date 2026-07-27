import sqlite3
import firebase_admin
from firebase_admin import credentials, firestore

TABLES = ['users', 'Products', 'orders', 'messages', 'questions', 'answers']


def get_pk_column(cursor, table_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    for col in cursor.fetchall():
        if col[-1]:
            return col[1]
    return None


def main():
    if not firebase_admin._apps:
        cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)

    db = firestore.client()

    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    for table in TABLES:
        print(f"Migrating {table}...")
        pk_col = get_pk_column(cursor, table)
        if pk_col is None:
            continue

        cursor.execute(f"SELECT * FROM {table}")
        rows = cursor.fetchall()
        count = 0
        for row in rows:
            doc_id = str(row[pk_col])
            doc_data = {k: v for k, v in dict(row).items() if v is not None}
            db.collection(table).document(doc_id).set(doc_data, merge=True)
            count += 1

        print(f"Migrated {count} {table}.")

    conn.close()


if __name__ == '__main__':
    main()