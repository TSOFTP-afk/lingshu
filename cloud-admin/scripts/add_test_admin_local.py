import sqlite3, bcrypt, datetime, shutil, os, getpass, sys

SRC = r"c:\Users\26455\AppData\Roaming\lingshu-electron\data\bookstore_demo.db"
TMP = r"c:\Users\26455\AppData\Roaming\lingshu-electron\data\bookstore_demo_tmp.db"

password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("设置管理员密码: ")
if len(password) < 8:
    print("错误：密码长度至少8位")
    sys.exit(1)

# Copy to avoid lock
shutil.copy2(SRC, TMP)

conn = sqlite3.connect(TMP)
cur = conn.cursor()

h = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

cur.execute(
    "INSERT OR IGNORE INTO users (username,password_hash,is_author,is_admin,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
    ("test", h, 1, 1, "active", now, now),
)
cur.execute("UPDATE users SET is_admin=1, password_hash=? WHERE username=?", (h, "test"))
conn.commit()

cur.execute("SELECT id, username, is_admin, is_author, status FROM users WHERE username='test'")
print(cur.fetchone())
conn.close()

# Overwrite original
shutil.move(TMP, SRC)
print("Done - database updated.")
