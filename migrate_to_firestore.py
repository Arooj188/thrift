import sqlite3
import firebase_admin
from firebase_admin import credentials, firestore

# Path to your downloaded Firebase service account JSON
SERVICE_ACCOUNT_FILE = "/home/Aroojatif/thrift-2ba27-firebase-adminsdk-fbsvc-4825b550d6.json"

TABLES = [
    "users",
    "Products",
    "orders",
    "messages",
    "questions",
    "answers"
]


def get_pk_column(cursor, table_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    for col in cursor.fetchall():
        if col[-1] == 1:   # Primary key
            return col[1]
    return None


def main():

    # Initialize Firebase
    if not firebase_admin._apps:
        cred = credentials.Certificate(SERVICE_ACCOUNT_FILE)
        firebase_admin.initialize_app(cred)

    db = firestore.client()

    # Open SQLite
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Copy every table
    for table in TABLES:
        print(f"Migrating {table}...")

        pk = get_pk_column(cursor, table)

        if pk is None:
            print(f"Skipped {table} (no primary key)")
            continue

        cursor.execute(f"SELECT * FROM {table}")
        rows = cursor.fetchall()

        count = 0

        for row in rows:
            data = dict(row)

            # Remove None values
            data = {k: v for k, v in data.items() if v is not None}

            # Use SQLite primary key as Firestore document ID
            doc_id = str(data[pk])

            db.collection(table).document(doc_id).set(data, merge=True)

            count += 1

        print(f"Migrated {count} {table}.")

    conn.close()

    print("\n✅ Migration complete!")


if __name__ == "__main__":
    main()