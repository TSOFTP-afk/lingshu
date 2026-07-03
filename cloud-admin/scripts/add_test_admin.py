#!/usr/bin/env python3
"""Insert test admin user into users table. Password from env or prompt."""
import os
import sys
import sqlite3
import bcrypt
from datetime import datetime, timezone

DB_PATH = "/home/CODEX/lingshu-cloud/data/bookstore_demo.db"

def main():
    password = os.environ.get("ADMIN_PASSWORD") or input("设置管理员密码: ")
    if len(password) < 8:
        print("错误：密码长度至少8位")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    try:
        cur.execute(
            "INSERT INTO users (username, password_hash, is_author, is_admin, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test", password_hash, 1, 1, "active", now, now),
        )
        conn.commit()
        print(f"User 'test' created with is_admin=1")
    except sqlite3.IntegrityError:
        cur.execute("UPDATE users SET is_admin=1, password_hash=? WHERE username=?", (password_hash, "test"))
        conn.commit()
        print(f"User 'test' updated: is_admin=1, password reset")

    cur.execute("SELECT id, username, is_admin, is_author, status FROM users WHERE username='test'")
    row = cur.fetchone()
    print(f"  id={row[0]} username={row[1]} is_admin={row[2]} is_author={row[3]} status={row[4]}")
    conn.close()

if __name__ == "__main__":
    main()
