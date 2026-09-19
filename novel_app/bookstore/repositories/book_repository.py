"""书目/章节/作品仓储 — 从 store.py 按域搬移（SQL 与行为不变）。

承接：外部发书（publish_chapter）、公开书目浏览、作者工作台（作品与章节 CRUD/发布）。
连接与事务模式照搬原 store.py：``with _connect(self.db_path) as connection`` + 显式 ``connection.commit()``。
"""
from __future__ import annotations

import secrets
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..cloud_store import (
    _book_row,
    _chapter_list_row,
    _compact_summary,
    _normalize_book_tags,
)
from ..models import (
    AuthorBookCreatePayload,
    AuthorBookUpdatePayload,
    AuthorChapterUpdatePayload,
    PublishChapterPayload,
    _connect,
)
from ..security import _escape_like
from .common import _rebuild_book_fulltext


class BookRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def publish_chapter(self, payload: PublishChapterPayload) -> dict[str, int]:
        source_book_id = str(payload.source_book_id)
        source_chapter_id = str(payload.source_chapter_id)
        summary = _compact_summary(payload.summary_text or payload.outline or payload.content)
        with _connect(self.db_path) as connection:
            book = connection.execute(
                """
                SELECT id, summary
                FROM books
                WHERE source_app = ? AND source_book_id = ?
                """,
                (payload.source_app, source_book_id),
            ).fetchone()
            if book:
                book_id = int(book["id"])
                connection.execute(
                    """
                    UPDATE books
                    SET title = ?, summary = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (payload.book_title.strip(), summary, book_id),
                )
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO books (source_app, source_book_id, title, summary)
                    VALUES (?, ?, ?, ?)
                    """,
                    (payload.source_app, source_book_id, payload.book_title.strip(), summary),
                )
                book_id = int(cursor.lastrowid)

            existing = connection.execute(
                """
                SELECT id
                FROM chapters
                WHERE book_id = ? AND source_chapter_id = ?
                """,
                (book_id, source_chapter_id),
            ).fetchone()
            if existing:
                chapter_id = int(existing["id"])
                connection.execute(
                    """
                    UPDATE chapters
                    SET
                        source_volume_id = ?,
                        volume_title = ?,
                        title = ?,
                        outline = ?,
                        summary_text = ?,
                        content = ?,
                        sort_order = ?,
                        ai_probability = ?,
                        ai_probability_level = ?,
                        status = 'published',
                        source_updated_at = ?,
                        published_at = CASE
                            WHEN published_at IS NULL OR published_at = '' THEN CURRENT_TIMESTAMP
                            ELSE published_at
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        str(payload.source_volume_id or ""),
                        payload.volume_title,
                        payload.chapter_title.strip(),
                        payload.outline,
                        payload.summary_text,
                        payload.content,
                        int(payload.sort_order or 0),
                        int(payload.ai_probability),
                        payload.ai_probability_level,
                        payload.updated_at,
                        chapter_id,
                    ),
                )
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO chapters (
                        book_id,
                        source_chapter_id,
                        source_volume_id,
                        volume_title,
                        title,
                        outline,
                        summary_text,
                        content,
                        sort_order,
                        ai_probability,
                        ai_probability_level,
                        status,
                        source_updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        book_id,
                        source_chapter_id,
                        str(payload.source_volume_id or ""),
                        payload.volume_title,
                        payload.chapter_title.strip(),
                        payload.outline,
                        payload.summary_text,
                        payload.content,
                        int(payload.sort_order or 0),
                        int(payload.ai_probability),
                        payload.ai_probability_level,
                        "published",
                        payload.updated_at,
                    ),
                )
                chapter_id = int(cursor.lastrowid)

            _rebuild_book_fulltext(connection, book_id)
            connection.commit()
        return {"book_id": book_id, "chapter_id": chapter_id}

    def list_books(self, query: str = "", category: str = "all") -> list[dict[str, Any]]:
        where = ["b.deleted_at IS NULL"]
        params: list[Any] = []
        if query.strip():
            where.append("(b.title LIKE ? ESCAPE '\\' OR b.summary LIKE ? ESCAPE '\\' OR b.category LIKE ? ESCAPE '\\' OR b.sub_tags LIKE ? ESCAPE '\\')")
            like = f"%{_escape_like(query.strip())}%"
            params.extend([like, like, like, like])
        if category and category != "all":
            where.append("b.category = ?")
            params.append(category)
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        with _connect(self.db_path) as connection:
            query_sql = """
                SELECT
                    b.id,
                    b.title,
                    b.summary,
                    b.category,
                    b.sub_tags,
                    b.cover_url,
                    b.updated_at,
                    COUNT(c.id) AS chapter_count,
                    COALESCE(SUM(LENGTH(c.content)), 0) AS word_count,
                    (
                        SELECT title
                        FROM chapters AS latest
                        WHERE latest.book_id = b.id AND latest.status = 'published' AND latest.deleted_at IS NULL
                        ORDER BY latest.updated_at DESC, latest.id DESC
                        LIMIT 1
                    ) AS latest_chapter_title
                FROM books AS b
                LEFT JOIN chapters AS c ON c.book_id = b.id AND c.status = 'published' AND c.deleted_at IS NULL
                """
            if where_sql:
                query_sql += "\n" + where_sql
            query_sql += """
                GROUP BY b.id
                ORDER BY b.updated_at DESC, b.id DESC
                """
            rows = connection.execute(
                query_sql,
                params,
            ).fetchall()
        return [_book_row(row) for row in rows]

    def get_book(self, book_id: int) -> dict[str, Any] | None:
        with _connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT
                    b.id,
                    b.title,
                    b.summary,
                    b.category,
                    b.sub_tags,
                    b.cover_url,
                    b.updated_at,
                    COUNT(c.id) AS chapter_count,
                    COALESCE(SUM(LENGTH(c.content)), 0) AS word_count,
                    (
                        SELECT title
                        FROM chapters AS latest
                        WHERE latest.book_id = b.id AND latest.status = 'published' AND latest.deleted_at IS NULL
                        ORDER BY latest.updated_at DESC, latest.id DESC
                        LIMIT 1
                    ) AS latest_chapter_title
                FROM books AS b
                LEFT JOIN chapters AS c ON c.book_id = b.id AND c.status = 'published' AND c.deleted_at IS NULL
                WHERE b.id = ? AND b.deleted_at IS NULL
                GROUP BY b.id
                """,
                (book_id,),
            ).fetchone()
        return _book_row(row) if row else None

    def list_chapters(self, book_id: int) -> list[dict[str, Any]]:
        with _connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    book_id,
                    volume_title,
                    title,
                    outline,
                    summary_text,
                    sort_order,
                    LENGTH(content) AS word_count,
                    status,
                    published_at,
                    updated_at
                FROM chapters
                WHERE book_id = ? AND status = 'published' AND deleted_at IS NULL
                ORDER BY sort_order ASC, id ASC
                """,
                (book_id,),
            ).fetchall()
        return [_chapter_list_row(row) for row in rows]

    def get_chapter(self, chapter_id: int) -> dict[str, Any] | None:
        with _connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT
                    c.id,
                    c.book_id,
                    c.volume_title,
                    c.title,
                    c.outline,
                    c.summary_text,
                    c.content,
                    c.sort_order,
                    c.ai_probability,
                    c.ai_probability_level,
                    c.status,
                    c.published_at,
                    c.updated_at,
                    b.title AS book_title
                FROM chapters AS c
                JOIN books AS b ON b.id = c.book_id
                WHERE c.id = ? AND c.status = 'published' AND c.deleted_at IS NULL AND b.deleted_at IS NULL
                """,
                (chapter_id,),
            ).fetchone()
            if not row:
                return None
            previous_row = connection.execute(
                """
                SELECT id
                FROM chapters
                WHERE book_id = ?
                  AND status = 'published'
                  AND deleted_at IS NULL
                  AND (sort_order < ? OR (sort_order = ? AND id < ?))
                ORDER BY sort_order DESC, id DESC
                LIMIT 1
                """,
                (row["book_id"], row["sort_order"], row["sort_order"], row["id"]),
            ).fetchone()
            next_row = connection.execute(
                """
                SELECT id
                FROM chapters
                WHERE book_id = ?
                  AND status = 'published'
                  AND deleted_at IS NULL
                  AND (sort_order > ? OR (sort_order = ? AND id > ?))
                ORDER BY sort_order ASC, id ASC
                LIMIT 1
                """,
                (row["book_id"], row["sort_order"], row["sort_order"], row["id"]),
            ).fetchone()
        result = dict(row)
        result["previous_chapter_id"] = int(previous_row["id"]) if previous_row else None
        result["next_chapter_id"] = int(next_row["id"]) if next_row else None
        result["word_count"] = len(str(result.get("content") or ""))
        return result

    def get_author_books(self, user_id: int) -> list[dict[str, Any]]:
        with _connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT
                    b.id, b.source_app, b.source_book_id, b.title, b.summary, b.category, b.sub_tags,
                    b.cover_url, b.updated_at,
                    COUNT(c.id) AS chapter_count,
                    COALESCE(SUM(LENGTH(c.content)), 0) AS word_count,
                    (SELECT title FROM chapters AS latest WHERE latest.book_id = b.id
                     AND latest.deleted_at IS NULL
                     ORDER BY latest.updated_at DESC, latest.id DESC LIMIT 1) AS latest_chapter_title
                FROM books AS b
                LEFT JOIN chapters AS c ON c.book_id = b.id AND c.deleted_at IS NULL
                WHERE b.source_app = ? AND b.is_test = 0 AND b.deleted_at IS NULL
                GROUP BY b.id
                ORDER BY b.updated_at DESC, b.id DESC
                """,
                (f"user_{user_id}",),
            ).fetchall()
        return [_book_row(row) for row in rows]

    def get_author_book(self, user_id: int, book_id: int) -> dict[str, Any] | None:
        with _connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT
                    b.id, b.source_app, b.source_book_id, b.title, b.summary, b.category, b.sub_tags,
                    b.cover_url, b.updated_at,
                    COUNT(c.id) AS chapter_count,
                    COALESCE(SUM(LENGTH(c.content)), 0) AS word_count,
                    (SELECT title FROM chapters AS latest WHERE latest.book_id = b.id
                     AND latest.deleted_at IS NULL
                     ORDER BY latest.updated_at DESC, latest.id DESC LIMIT 1) AS latest_chapter_title
                FROM books AS b
                LEFT JOIN chapters AS c ON c.book_id = b.id AND c.deleted_at IS NULL
                WHERE b.id = ? AND b.source_app = ? AND b.is_test = 0 AND b.deleted_at IS NULL
                GROUP BY b.id
                """,
                (int(book_id), f"user_{user_id}"),
            ).fetchone()
        return _book_row(row) if row else None

    def create_author_book(self, user_id: int, payload: AuthorBookCreatePayload) -> dict[str, Any]:
        source_app = f"user_{user_id}"
        title = payload.title.strip()
        summary = str(payload.summary or "").strip()
        category = str(payload.category or "").strip() or "本地上传"
        sub_tags = _normalize_book_tags(payload.sub_tags)
        cover_url = str(payload.cover_url or "").strip()
        with _connect(self.db_path) as connection:
            for _ in range(5):
                source_book_id = f"web-{secrets.token_urlsafe(8)}"
                try:
                    cursor = connection.execute(
                        """
                        INSERT INTO books (
                            source_app, source_book_id, title, summary, category, sub_tags, cover_url
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (source_app, source_book_id, title, summary, category, sub_tags, cover_url),
                    )
                    _rebuild_book_fulltext(connection, int(cursor.lastrowid))
                    connection.commit()
                    book = self.get_author_book(user_id, int(cursor.lastrowid))
                    if not book:
                        raise HTTPException(status_code=500, detail="作品创建后读取失败")
                    return book
                except sqlite3.IntegrityError:
                    continue
        raise HTTPException(status_code=500, detail="作品编号生成失败")

    def update_author_book_summary(
        self,
        user_id: int,
        book_id: int,
        payload: AuthorBookUpdatePayload,
    ) -> dict[str, Any] | None:
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE books
                SET summary = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND source_app = ? AND is_test = 0 AND deleted_at IS NULL
                """,
                (str(payload.summary or "").strip(), int(book_id), f"user_{user_id}"),
            )
            connection.commit()
        if cursor.rowcount <= 0:
            return None
        return self.get_author_book(user_id, book_id)

    def list_author_chapters(self, user_id: int, book_id: int) -> list[dict[str, Any]] | None:
        source_app = f"user_{user_id}"
        with _connect(self.db_path) as connection:
            book = connection.execute(
                "SELECT id FROM books WHERE id = ? AND source_app = ? AND is_test = 0 AND deleted_at IS NULL",
                (int(book_id), source_app),
            ).fetchone()
            if not book:
                return None
            rows = connection.execute(
                """
                SELECT
                    id,
                    book_id,
                    volume_title,
                    title,
                    outline,
                    summary_text,
                    sort_order,
                    LENGTH(content) AS word_count,
                    status,
                    published_at,
                    updated_at
                FROM chapters
                WHERE book_id = ? AND deleted_at IS NULL
                ORDER BY sort_order ASC, id ASC
                """,
                (int(book_id),),
            ).fetchall()
        return [_chapter_list_row(row) for row in rows]

    def get_author_chapter(self, user_id: int, book_id: int, chapter_id: int) -> dict[str, Any] | None:
        source_app = f"user_{user_id}"
        with _connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT
                    c.id,
                    c.book_id,
                    c.volume_title,
                    c.title,
                    c.outline,
                    c.summary_text,
                    c.content,
                    c.sort_order,
                    c.ai_probability,
                    c.ai_probability_level,
                    c.status,
                    c.published_at,
                    c.updated_at,
                    b.title AS book_title
                FROM chapters AS c
                JOIN books AS b ON b.id = c.book_id
                WHERE c.id = ?
                  AND c.book_id = ?
                  AND b.source_app = ?
                  AND b.is_test = 0
                  AND b.deleted_at IS NULL
                  AND c.deleted_at IS NULL
                """,
                (int(chapter_id), int(book_id), source_app),
            ).fetchone()
            if not row:
                return None
            previous_row = connection.execute(
                """
                SELECT id
                FROM chapters
                WHERE book_id = ?
                  AND deleted_at IS NULL
                  AND (sort_order < ? OR (sort_order = ? AND id < ?))
                ORDER BY sort_order DESC, id DESC
                LIMIT 1
                """,
                (row["book_id"], row["sort_order"], row["sort_order"], row["id"]),
            ).fetchone()
            next_row = connection.execute(
                """
                SELECT id
                FROM chapters
                WHERE book_id = ?
                  AND deleted_at IS NULL
                  AND (sort_order > ? OR (sort_order = ? AND id > ?))
                ORDER BY sort_order ASC, id ASC
                LIMIT 1
                """,
                (row["book_id"], row["sort_order"], row["sort_order"], row["id"]),
            ).fetchone()
        result = dict(row)
        result["previous_chapter_id"] = int(previous_row["id"]) if previous_row else None
        result["next_chapter_id"] = int(next_row["id"]) if next_row else None
        result["word_count"] = len(str(result.get("content") or ""))
        return result

    def create_next_author_chapter(self, user_id: int, book_id: int) -> dict[str, Any] | None:
        source_app = f"user_{user_id}"
        chapter_id: int | None = None
        with _connect(self.db_path) as connection:
            book = connection.execute(
                "SELECT id FROM books WHERE id = ? AND source_app = ? AND is_test = 0 AND deleted_at IS NULL",
                (int(book_id), source_app),
            ).fetchone()
            if not book:
                return None
            latest = connection.execute(
                """
                SELECT sort_order, volume_title
                FROM chapters
                WHERE book_id = ? AND deleted_at IS NULL
                ORDER BY sort_order DESC, id DESC
                LIMIT 1
                """,
                (int(book_id),),
            ).fetchone()
            next_order = max(int(latest["sort_order"] or 0), 0) + 1 if latest else 1
            volume_title = str(latest["volume_title"] or "").strip() if latest else ""
            volume_title = volume_title or "正文"
            title = f"第{next_order}章 未命名"

            for _ in range(5):
                source_chapter_id = f"web-{secrets.token_urlsafe(8)}"
                try:
                    cursor = connection.execute(
                        """
                        INSERT INTO chapters (
                            book_id,
                            source_chapter_id,
                            source_volume_id,
                            volume_title,
                            title,
                            content,
                            sort_order,
                            status,
                            published_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (int(book_id), source_chapter_id, volume_title, volume_title, title, "", next_order, "draft", ""),
                    )
                    chapter_id = int(cursor.lastrowid)
                    connection.execute(
                        "UPDATE books SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (int(book_id),),
                    )
                    _rebuild_book_fulltext(connection, int(book_id))
                    connection.commit()
                    break
                except sqlite3.IntegrityError:
                    continue
            else:
                raise HTTPException(status_code=500, detail="章节编号生成失败")
        if chapter_id is None:
            raise HTTPException(status_code=500, detail="章节创建失败")
        return self.get_author_chapter(user_id, book_id, chapter_id)

    def update_author_chapter(
        self,
        user_id: int,
        book_id: int,
        chapter_id: int,
        payload: AuthorChapterUpdatePayload,
    ) -> dict[str, Any] | None:
        source_app = f"user_{user_id}"
        with _connect(self.db_path) as connection:
            book = connection.execute(
                "SELECT id FROM books WHERE id = ? AND source_app = ? AND is_test = 0 AND deleted_at IS NULL",
                (int(book_id), source_app),
            ).fetchone()
            if not book:
                return None
            cursor = connection.execute(
                """
                UPDATE chapters
                SET title = ?, volume_title = ?, content = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND book_id = ? AND deleted_at IS NULL
                """,
                (
                    payload.title.strip(),
                    payload.volume_title.strip() or "正文",
                    payload.content,
                    int(chapter_id),
                    int(book_id),
                ),
            )
            if cursor.rowcount <= 0:
                return None
            connection.execute(
                "UPDATE books SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(book_id),),
            )
            _rebuild_book_fulltext(connection, int(book_id))
            connection.commit()
        return self.get_author_chapter(user_id, book_id, chapter_id)

    def publish_author_chapter(self, user_id: int, book_id: int, chapter_id: int) -> dict[str, Any] | None:
        source_app = f"user_{user_id}"
        with _connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT c.id, c.content
                FROM chapters AS c
                JOIN books AS b ON b.id = c.book_id
                WHERE c.id = ?
                  AND c.book_id = ?
                  AND b.source_app = ?
                  AND b.is_test = 0
                  AND b.deleted_at IS NULL
                  AND c.deleted_at IS NULL
                """,
                (int(chapter_id), int(book_id), source_app),
            ).fetchone()
            if not row:
                return None
            if not str(row["content"] or "").strip():
                raise HTTPException(status_code=422, detail="章节正文为空，不能发布")
            connection.execute(
                """
                UPDATE chapters
                SET status = 'published',
                    published_at = CASE
                        WHEN published_at IS NULL OR published_at = '' THEN CURRENT_TIMESTAMP
                        ELSE published_at
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND book_id = ? AND deleted_at IS NULL
                """,
                (int(chapter_id), int(book_id)),
            )
            connection.execute(
                "UPDATE books SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(book_id),),
            )
            _rebuild_book_fulltext(connection, int(book_id))
            connection.commit()
        return self.get_author_chapter(user_id, book_id, chapter_id)

    def delete_author_chapter(self, user_id: int, book_id: int, chapter_id: int) -> bool:
        source_app = f"user_{user_id}"
        with _connect(self.db_path) as connection:
            book = connection.execute(
                "SELECT id FROM books WHERE id = ? AND source_app = ? AND is_test = 0 AND deleted_at IS NULL",
                (int(book_id), source_app),
            ).fetchone()
            if not book:
                return False
            cursor = connection.execute(
                """
                UPDATE chapters
                SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                    deleted_by = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND book_id = ? AND deleted_at IS NULL
                """,
                (int(user_id), int(chapter_id), int(book_id)),
            )
            if cursor.rowcount <= 0:
                return False
            connection.execute(
                "UPDATE books SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(book_id),),
            )
            _rebuild_book_fulltext(connection, int(book_id))
            connection.commit()
        return True
