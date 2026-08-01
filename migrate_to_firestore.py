import sqlite3
import firestore_db


def main():
    if not firestore_db.is_firestore_available():
        print("Firestore not available. Cannot migrate.")
        return

    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    tables = ["users", "Products", "orders", "messages", "questions", "answers"]

    for table in tables:
        print(f"Migrating {table}...")
        cur.execute(f"SELECT * FROM {table}")
        rows = cur.fetchall()

        count = 0
        for row in rows:
            data = dict(row)
            data = {k: v for k, v in data.items() if v is not None}

            # Normalize images field from JSON string to list
            if table == "Products" and data.get('images') and isinstance(data['images'], str):
                try:
                    data['images'] = __import__('json').loads(data['images'])
                except Exception:
                    pass

            pk = None
            if table == "users":
                pk = data.get('user_id')
            elif table == "Products":
                pk = data.get('id')
            elif table == "orders":
                pk = data.get('order_id')
            elif table == "messages":
                pk = data.get('message_id')
            elif table == "questions":
                pk = data.get('question_id')
            elif table == "answers":
                pk = data.get('answer_id')

            if pk is None:
                continue

            doc_id = str(pk)
            doc_ref = firestore_db.get_firestore_db().collection(table).document(doc_id)
            if not doc_ref.get().exists:
                doc_ref.set(data)
                count += 1
                print(f"  Migrated {table} id={pk}")
            else:
                print(f"  Skipped {table} id={pk} (already exists)")

        print(f"Migrated {count} {table}.")

    conn.close()
    print("\nMigration complete!")


if __name__ == "__main__":
    main()
