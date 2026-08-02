#!/usr/bin/env python3
"""
Utility: set a user's admin status in Firestore.

Usage:
    python set_admin.py <email>

Example:
    python set_admin.py aroojatifamna@gmail.com

This will set is_admin=true on the Firestore user document that matches the given email.
"""

import sys
import os
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import firestore_db


def main():
    if len(sys.argv) != 2:
        print("Usage: python set_admin.py <email>")
        sys.exit(1)

    email = sys.argv[1].strip().lower()
    if not email:
        print("Error: email is required")
        sys.exit(1)

    if not firestore_db.is_firestore_available():
        print("Error: Firestore is not available. Check FIREBASE_CREDENTIALS.")
        sys.exit(1)

    db = firestore_db.get_firestore_db()
    if db is None:
        print("Error: Firestore client is None.")
        sys.exit(1)

    # Find user by email
    docs = db.collection('users').where('email', '==', email).stream()
    matched = []
    for doc in docs:
        matched.append(doc)

    if not matched:
        print(f"Error: No user found with email '{email}' in Firestore.")
        sys.exit(1)

    for doc in matched:
        print(f"Found user document: id={doc.id}")
        data = doc.to_dict()
        print(f"Current is_admin: {data.get('is_admin')}")
        doc.reference.set({'is_admin': True}, merge=True)
        print(f"Updated: is_admin set to True for document {doc.id}")

    print("Done.")


if __name__ == '__main__':
    main()
