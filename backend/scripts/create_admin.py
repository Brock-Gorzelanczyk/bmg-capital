"""
One-time script to create/reset the admin user in production.

Usage (run from backend/):
    DATABASE_URL=sqlite:///bmg_capital.db python scripts/create_admin.py

Or on Railway:
    railway run python scripts/create_admin.py
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import bcrypt
from sqlalchemy import create_engine, text

EMAIL    = os.environ.get("ADMIN_EMAIL",    "32bgorzelanczyk@gmail.com")
USERNAME = os.environ.get("ADMIN_USERNAME", "brock")
PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

if not PASSWORD:
    print("ERROR: set ADMIN_PASSWORD env var")
    sys.exit(1)

db_url = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(os.path.dirname(__file__), '..', 'bmg_capital.db')}")
engine = create_engine(db_url, connect_args={"check_same_thread": False} if "sqlite" in db_url else {})

hashed = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()

with engine.connect() as conn:
    existing = conn.execute(text("SELECT id FROM users WHERE email = :e"), {"e": EMAIL}).fetchone()
    if existing:
        conn.execute(text(
            "UPDATE users SET hashed_password=:h, is_admin=1, is_active=1 WHERE email=:e"
        ), {"h": hashed, "e": EMAIL})
        print(f"Updated password + set is_admin=1 for {EMAIL}")
    else:
        conn.execute(text(
            "INSERT INTO users (email, username, hashed_password, is_active, is_admin) "
            "VALUES (:e, :u, :h, 1, 1)"
        ), {"e": EMAIL, "u": USERNAME, "h": hashed})
        print(f"Created admin user: {EMAIL}")
    conn.commit()
print("Done.")
