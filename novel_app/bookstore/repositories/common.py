"""仓储层共享辅助 — 从 store.py 原样搬移（SQL 与行为不变）。

包含：动态表/列名白名单校验、书籍全文重建（books/chapters/book_fulltexts 跨域共用）。
"""
from __future__ import annotations

import sqlite3

from ..security import _fulltext_content_hash

# 范例小说归属的系统用户名（由 tools/sample_novel/seed_sample_novel.py 写入）
SAMPLE_NOVEL_USERNAME = "__sample__"

_VALID_TABLES = frozenset({
    "users", "books", "chapters", "bookshelf_shelves", "bookshelf_items",
    "user_online_sessions", "admin_users", "admin_keys", "admin_auth_tokens",
})

_VALID_COLUMNS = frozenset({
    # users table
    "id", "username", "email", "password_hash", "display_name", "role", "status",
    "created_at", "updated_at", "last_login_at", "avatar_url", "bio",
    "is_author", "is_admin", "disabled_at",
    # books table
    "title", "description", "cover_url", "author", "word_count", "sort_order", "deleted_at", "summary", "category", "sub_tags", "is_test",
    "source_app",
    # chapters table
    "book_id", "content", "chapter_number", "volume_id", "volume_title",
    "outline", "summary_text", "published_at", "ai_probability",
    "ai_probability_level",
    # bookshelf tables
    "shelf_id", "user_id", "added_at", "last_chapter_id", "name",
    # online sessions
    "login_at", "logout_at", "duration_seconds", "expires_at",
    "estimated_online_seconds",
})


def _validate_table(table_name: str) -> str:
    """Validate dynamic table name against whitelist."""
    if table_name not in _VALID_TABLES:
        raise ValueError(f"Invalid table name: {table_name}")
    return table_name


def _validate_column(column_name: str) -> str:
    """Validate dynamic column name against whitelist."""
    if column_name not in _VALID_COLUMNS:
        raise ValueError(f"Invalid column name: {column_name}")
    return column_name


def _validate_columns(columns: list[str]) -> list[str]:
    """Validate a list of dynamic column names against whitelist."""
    return [_validate_column(col) for col in columns]


def _book_user_id(connection: sqlite3.Connection, book_id: int) -> int | None:
    row = connection.execute("SELECT source_app FROM books WHERE id = ?", (int(book_id),)).fetchone()
    if not row:
        return None
    source_app = str(row["source_app"] or "")
    if not source_app.startswith("user_"):
        return None
    try:
        return int(source_app.removeprefix("user_"))
    except ValueError:
        return None


def _rebuild_book_fulltext(connection: sqlite3.Connection, book_id: int) -> None:
    user_id = _book_user_id(connection, book_id)
    if user_id is None:
        return
    chapters = connection.execute(
        """
        SELECT volume_title, title, content
        FROM chapters
        WHERE book_id = ? AND deleted_at IS NULL
        ORDER BY sort_order ASC, id ASC
        """,
        (int(book_id),),
    ).fetchall()
    parts: list[str] = []
    last_volume = object()
    for row in chapters:
        volume_title = str(row["volume_title"] or "").strip()
        title = str(row["title"] or "").strip()
        content = str(row["content"] or "")
        header_lines: list[str] = []
        if volume_title and volume_title != last_volume:
            header_lines.append(f"## {volume_title}")
            last_volume = volume_title
        if title:
            header_lines.append(f"# {title}")
        block = "\n".join(header_lines + ([content] if content else [])).strip()
        if block:
            parts.append(block)
    fulltext = "\n\n".join(parts)
    content_hash = _fulltext_content_hash(fulltext)
    existing = connection.execute(
        "SELECT revision, content_hash FROM book_fulltexts WHERE book_id = ?",
        (int(book_id),),
    ).fetchone()
    if existing and str(existing["content_hash"] or "") == content_hash:
        connection.execute(
            """
            UPDATE book_fulltexts
            SET chapter_count = ?, char_count = ?, updated_at = CURRENT_TIMESTAMP
            WHERE book_id = ?
            """,
            (len(chapters), len(fulltext), int(book_id)),
        )
        return
    next_revision = int(existing["revision"] or 0) + 1 if existing else 1
    connection.execute(
        """
        INSERT INTO book_fulltexts (
            book_id, user_id, content, content_hash, chapter_count, char_count, revision, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(book_id) DO UPDATE SET
            user_id = excluded.user_id,
            content = excluded.content,
            content_hash = excluded.content_hash,
            chapter_count = excluded.chapter_count,
            char_count = excluded.char_count,
            revision = excluded.revision,
            updated_at = CURRENT_TIMESTAMP
        """,
        (int(book_id), user_id, fulltext, content_hash, len(chapters), len(fulltext), next_revision),
    )
