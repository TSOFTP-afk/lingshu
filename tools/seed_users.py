import bcrypt
import os
import secrets
import sqlite3
from pathlib import Path

from novel_app.bookstore import client_password_hash

ROOT_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ROOT_DIR / "data" / "bookstore_demo.db"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def seed_password() -> tuple[str, bool]:
    configured = os.environ.get("BOOKSTORE_SEED_PASSWORD", "").strip()
    if configured:
        return configured, False
    return secrets.token_urlsafe(14), True


def seed_users(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute("DELETE FROM auth_tokens")
    conn.execute("DELETE FROM users")
    conn.commit()

    password, generated_password = seed_password()
    users = [
        ("author001", password, 1),
        ("author002", password, 1),
        ("reader001", password, 0),
        ("reader002", password, 0),
        ("demo", password, 1),
    ]

    user_ids = []
    for username, password, is_author in users:
        pw_hash = hash_password(client_password_hash(password))
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, is_author) VALUES (?, ?, ?)",
            (username, pw_hash, is_author),
        )
        user_ids.append(cursor.lastrowid)

    conn.execute("UPDATE users SET bind_reader_id = ? WHERE id = ?", (user_ids[2], user_ids[0]))
    conn.execute("UPDATE users SET bind_reader_id = ? WHERE id = ?", (user_ids[3], user_ids[1]))
    conn.execute("UPDATE users SET bind_reader_id = ? WHERE id = ?", (user_ids[2], user_ids[4]))

    conn.commit()
    conn.close()
    print(f"已创建 {len(users)} 个测试账号 (bcrypt 加密)")
    if generated_password:
        print(f"未设置 BOOKSTORE_SEED_PASSWORD，已生成一次性演示密码：{password}")
    else:
        print("测试账号密码来自 BOOKSTORE_SEED_PASSWORD。")
    print(f"  author001 / reader001 绑定")
    print(f"  author002 / reader002 绑定")
    print(f"  demo / reader001 绑定")


if __name__ == "__main__":
    seed_users(DB_PATH)
