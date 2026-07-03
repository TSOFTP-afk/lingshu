"""线上端到端 API 测试：完整走 register → /api/author/books 链路。"""
import json
import urllib.request

BASE = "http://127.0.0.1:8787"
USERNAME = "api_e2e_test"
PASSWORD = "Test12345678"  # 明文，注册接口会校验强度

# 1. 注册
print("=== 1. register ===")
reg_data = json.dumps({"username": USERNAME, "password": PASSWORD, "is_author": 1}).encode()
req = urllib.request.Request(f"{BASE}/api/auth/register", data=reg_data,
                             headers={"Content-Type": "application/json"}, method="POST")
try:
    with urllib.request.urlopen(req) as resp:
        reg_resp = json.loads(resp.read())
        print("register OK:", {k: v for k, v in reg_resp.items() if k != "access_token"})
        token = reg_resp["access_token"]
        user = reg_resp["user"]
        uid = user["id"]
        print("user_id:", uid, "is_author:", user.get("is_author"))
except urllib.error.HTTPError as e:
    print("register FAILED:", e.code, e.read().decode())
    raise

# 2. 调用 /api/author/books
print("\n=== 2. GET /api/author/books ===")
req2 = urllib.request.Request(f"{BASE}/api/author/books",
                              headers={"Authorization": f"Bearer {token}"}, method="GET")
try:
    with urllib.request.urlopen(req2) as resp:
        books_resp = json.loads(resp.read())
        items = books_resp.get("items", [])
        print("author/books count:", len(items))
        for b in items:
            print("  -", b.get("title"), "| chapters:", b.get("chapter_count"),
                  "| words:", b.get("word_count"), "| source_app:", b.get("source_app"))
except urllib.error.HTTPError as e:
    print("author/books FAILED:", e.code, e.read().decode())

# 3. 清理
print("\n=== 3. cleanup ===")
import sqlite3
c = sqlite3.connect("/home/CODEX/lingshu-cloud/data/bookstore_demo.db")
c.execute("DELETE FROM cloud_books WHERE user_id=?", (uid,))
c.execute("DELETE FROM books WHERE source_app=?", (f"user_{uid}",))
c.execute("DELETE FROM users WHERE id=?", (uid,))
c.commit()
c.close()
print("cleaned")
