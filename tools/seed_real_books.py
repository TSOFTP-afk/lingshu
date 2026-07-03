"""从 novels.db 导入真实书籍到 bookstore_demo.db。"""
import sqlite3
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
NOVELS_DB = ROOT_DIR / "data" / "novels.db"
BOOKSTORE_DB = ROOT_DIR / "data" / "bookstore_demo.db"


def import_books():
    src = sqlite3.connect(str(NOVELS_DB))
    src.row_factory = sqlite3.Row

    dst = sqlite3.connect(str(BOOKSTORE_DB))
    dst.row_factory = sqlite3.Row
    dst.execute("PRAGMA foreign_keys = ON")
    dst.execute("PRAGMA journal_mode=WAL")

    # 读取所有书籍
    books = src.execute(
        "SELECT id, title, outline_text FROM books ORDER BY id"
    ).fetchall()

    imported_books = 0
    imported_chapters = 0

    for book in books:
        book_id = book["id"]
        title = book["title"].strip()
        outline = (book["outline_text"] or "").strip()
        summary = " ".join(outline.split())[:160] if outline else f"本地作品《{title}》"

        # 获取章节
        chapters = src.execute(
            """
            SELECT c.id, c.title, c.content, c.outline, c.summary_text,
                   c.sort_order, COALESCE(v.title, '') AS volume_title,
                   c.ai_probability, c.ai_probability_level
            FROM chapters c
            LEFT JOIN volumes v ON v.id = c.volume_id
            WHERE c.book_id = ?
            ORDER BY c.sort_order, c.id
            """,
            (book_id,),
        ).fetchall()

        if not chapters:
            continue

        source_book_id = f"local_{book_id}"

        # 插入或更新书籍
        existing = dst.execute(
            "SELECT id FROM books WHERE source_app = ? AND source_book_id = ?",
            ("local", source_book_id),
        ).fetchone()

        if existing:
            b_id = existing["id"]
            dst.execute(
                "UPDATE books SET title = ?, summary = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (title, summary, b_id),
            )
        else:
            cur = dst.execute(
                "INSERT INTO books (source_app, source_book_id, title, summary, category) VALUES (?, ?, ?, ?, ?)",
                ("local", source_book_id, title, summary, "本地上传"),
            )
            b_id = cur.lastrowid

        for ch in chapters:
            source_ch_id = f"local_{book_id}_ch_{ch['id']}"
            ch_title = ch["title"].strip() or f"第{ch['sort_order']+1}章"
            content = ch["content"] or ""

            ch_existing = dst.execute(
                "SELECT id FROM chapters WHERE book_id = ? AND source_chapter_id = ?",
                (b_id, source_ch_id),
            ).fetchone()

            if ch_existing:
                dst.execute(
                    """UPDATE chapters SET
                        title=?, volume_title=?, outline=?, summary_text=?,
                        content=?, sort_order=?, ai_probability=?,
                        ai_probability_level=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?""",
                    (
                        ch_title,
                        ch["volume_title"] or "",
                        ch["outline"] or "",
                        ch["summary_text"] or "",
                        content,
                        ch["sort_order"] or 0,
                        ch["ai_probability"] or 0,
                        ch["ai_probability_level"] or "none",
                        ch_existing["id"],
                    ),
                )
            else:
                dst.execute(
                    """INSERT INTO chapters (
                        book_id, source_chapter_id, volume_title,
                        title, outline, summary_text, content, sort_order,
                        ai_probability, ai_probability_level
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        b_id,
                        source_ch_id,
                        ch["volume_title"] or "",
                        ch_title,
                        ch["outline"] or "",
                        ch["summary_text"] or "",
                        content,
                        ch["sort_order"] or 0,
                        ch["ai_probability"] or 0,
                        ch["ai_probability_level"] or "none",
                    ),
                )
            imported_chapters += 1

        imported_books += 1

    dst.commit()
    src.close()
    dst.close()
    print(f"已导入 {imported_books} 本书，共 {imported_chapters} 章节")


if __name__ == "__main__":
    import_books()
