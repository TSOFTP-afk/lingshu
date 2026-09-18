import sqlite3
conn = sqlite3.connect('data/novels.db', timeout=30)
conn.execute('PRAGMA busy_timeout = 30000')
conn.execute(
    "UPDATE analysis_runs SET status='cancelled', "
    "error_text='用户手动暂停，调整并发上限和M2优化', "
    "updated_at=CURRENT_TIMESTAMP WHERE status='running'"
)
conn.commit()
rows = conn.execute("SELECT id, book_id, status FROM analysis_runs WHERE status='cancelled' ORDER BY id DESC LIMIT 3").fetchall()
for r in rows:
    print(f"run_id={r[0]} book_id={r[1]} status={r[2]}")
conn.close()
