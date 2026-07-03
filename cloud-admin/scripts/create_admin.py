#!/usr/bin/env python3
"""Create admin_users table and insert initial admin account."""
import os
import sys
import sqlite3
import bcrypt
from datetime import datetime, timezone

_LINGSHU_CLOUD_DIR = os.environ.get("LISHU_CLOUD_DIR")
if not _LINGSHU_CLOUD_DIR:
    _LINGSHU_CLOUD_DIR = "/home/CODEX/lingshu-cloud"
    print(f"[WARN] LISHU_CLOUD_DIR 环境变量未设置，使用默认路径: {_LINGSHU_CLOUD_DIR}")
    print("       建议设置 LISHU_CLOUD_DIR 环境变量以指定灵枢云端部署目录")

DB_PATH = os.path.join(_LINGSHU_CLOUD_DIR, "data/bookstore_demo.db")

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Create admin_users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'operator',
            status TEXT NOT NULL DEFAULT 'active',
            last_login_at TEXT,
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
    """)

    # Create admin_audit_logs table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL DEFAULT '',
            detail_json TEXT NOT NULL DEFAULT '{}',
            ip_address TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT ''
        );
    """)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # Insert initial admin (username and password from env or argument)
    import getpass
    admin_username = os.environ.get("ADMIN_USERNAME") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not admin_username:
        admin_username = input("请输入管理员用户名: ").strip()
    if not admin_username:
        print("错误：未提供管理员用户名")
        sys.exit(1)
    admin_password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("设置管理员密码: ")
    if len(admin_password) < 8:
        print("错误：密码长度至少8位")
        sys.exit(1)
    password_hash = bcrypt.hashpw(admin_password.encode(), bcrypt.gensalt()).decode()
    try:
        cur.execute(
            "INSERT INTO admin_users (username, password_hash, display_name, role, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (admin_username, password_hash, f"{admin_username} Admin", "superadmin", "active", now, now),
        )
        print(f"Admin user '{admin_username}' created.")
    except sqlite3.IntegrityError:
        print(f"Admin user '{admin_username}' already exists, skipping.")

    conn.commit()
    conn.close()

    # Verify
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, username, role, status, created_at FROM admin_users")
    for row in cur.fetchall():
        print(f"  id={row[0]} username={row[1]} role={row[2]} status={row[3]} created_at={row[4]}")
    conn.close()
    print("Done.")

if __name__ == "__main__":
    main()
