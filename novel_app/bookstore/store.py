from __future__ import annotations

import json
import logging
import secrets
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .cloud_store import (
    _book_row,
    _bookshelf_row,
    _bookshelf_shelf_row,
    _chapter_list_row,
    _compact_summary,
    _normalize_book_tags,
)
from .models import (
    DEFAULT_DB_PATH,
    AdminBookUpdatePayload,
    AdminChapterUpdatePayload,
    AdminUserUpdatePayload,
    AuthorBookCreatePayload,
    AuthorBookUpdatePayload,
    AuthorChapterUpdatePayload,
    BookshelfCreatePayload,
    BookshelfProgressPayload,
    PublishChapterPayload,
    _admin_usernames_from_env,
    _connect,
    _default_bookshelf_name,
    _system_default_bookshelf_names,
    initialize_database,
)
from .security import (
    _escape_like,
    _fulltext_content_hash,
    _generate_token,
    _hash_login_password,
    _masked_token,
    _online_seconds_expr,
    _safe_int,
    _seconds_between_sql,
    _token_hash,
    _verify_login_password,
)

logger = logging.getLogger(__name__)

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


class BookstoreStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        initialize_database(self.db_path)

    def _book_user_id(self, connection: sqlite3.Connection, book_id: int) -> int | None:
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

    def _rebuild_book_fulltext(self, connection: sqlite3.Connection, book_id: int) -> None:
        user_id = self._book_user_id(connection, book_id)
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

    def _record_login_session(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: int,
        token: str,
        expires_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO user_online_sessions (user_id, token_hash, login_at, expires_at, status)
            VALUES (?, ?, CURRENT_TIMESTAMP, ?, 'active')
            """,
            (int(user_id), _token_hash(token), expires_at),
        )

    def _settle_online_session(
        self,
        connection: sqlite3.Connection,
        *,
        token_hash: str,
        status: str,
    ) -> None:
        connection.execute(
            f"""
            UPDATE user_online_sessions
            SET logout_at = COALESCE(logout_at, CURRENT_TIMESTAMP),
                estimated_online_seconds = CASE
                    WHEN estimated_online_seconds > 0 THEN estimated_online_seconds
                    ELSE {_seconds_between_sql("CURRENT_TIMESTAMP")}
                END,
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE token_hash = ? AND status = 'active'
            """,
            (status, token_hash),
        )

    def _settle_expired_sessions(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            f"""
            UPDATE user_online_sessions
            SET logout_at = COALESCE(logout_at, expires_at),
                estimated_online_seconds = CASE
                    WHEN estimated_online_seconds > 0 THEN estimated_online_seconds
                    ELSE {_seconds_between_sql("expires_at")}
                END,
                status = 'expired',
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'active' AND expires_at <= CURRENT_TIMESTAMP
            """
        )

    def logout_token(self, token: str) -> bool:
        token_hash = _token_hash(token)
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE auth_tokens
                SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)
                WHERE token = ? AND revoked_at IS NULL
                """,
                (token,),
            )
            self._settle_online_session(connection, token_hash=token_hash, status="logged_out")
            connection.commit()
            return cursor.rowcount > 0

    def record_user_analysis_run(
        self,
        *,
        user_id: int,
        book_id: int | None = None,
        analysis_mode: str = "",
        input_chars: int = 0,
        status: str = "completed",
        source: str = "",
        run_ref: str = "",
        metadata: dict[str, Any] | None = None,
        error_text: str = "",
    ) -> int:
        # book_id 是 novels.db 的本地 book_id，而 user_analysis_runs 表的 book_id
        # 外键引用 bookstore_demo.db 的 books(id)。跨库引用会导致 FOREIGN KEY constraint failed。
        # 此处先尝试带 book_id 插入，外键失败则置 NULL 重试，保证统计记录不丢失。
        effective_book_id = int(book_id) if book_id is not None else None
        params = (
            int(user_id),
            effective_book_id,
            str(run_ref or ""),
            str(analysis_mode or ""),
            max(0, _safe_int(input_chars)),
            str(status or "completed"),
            str(source or ""),
            str(error_text or "")[:2000],
            json.dumps(metadata or {}, ensure_ascii=False, default=str),
        )
        insert_sql = """
            INSERT INTO user_analysis_runs (
                user_id, book_id, run_ref, analysis_mode, input_chars, status,
                source, error_text, metadata, completed_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
        with _connect(self.db_path) as connection:
            try:
                cursor = connection.execute(insert_sql, params)
            except sqlite3.IntegrityError as exc:
                if "FOREIGN KEY" in str(exc).upper() and effective_book_id is not None:
                    logger.warning(
                        "record_user_analysis_run FOREIGN KEY failed for book_id=%s, retrying with NULL",
                        effective_book_id,
                    )
                    params = (params[0], None) + params[2:]
                    cursor = connection.execute(insert_sql, params)
                else:
                    raise
            connection.commit()
            return int(cursor.lastrowid)

    def record_user_ai_usage(
        self,
        *,
        user_id: int,
        feature: str,
        book_id: int | None = None,
        analysis_run_id: int | None = None,
        model: str = "",
        provider: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        token_source: str = "unknown",
        input_chars: int = 0,
        output_chars: int = 0,
        trace_id: str = "",
        prompt_version: str = "",
        schema_version: str = "",
        latency_ms: int = 0,
        status: str = "completed",
        error_text: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        resolved_prompt = max(0, _safe_int(prompt_tokens))
        resolved_completion = max(0, _safe_int(completion_tokens))
        resolved_total = max(0, _safe_int(total_tokens))
        if not resolved_total and (resolved_prompt or resolved_completion):
            resolved_total = resolved_prompt + resolved_completion
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO user_ai_usage_events (
                    user_id, book_id, analysis_run_id, feature, model, provider,
                    prompt_tokens, completion_tokens, total_tokens, token_source,
                    input_chars, output_chars, trace_id, prompt_version, schema_version,
                    latency_ms, status, error_text, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(user_id),
                    int(book_id) if book_id is not None else None,
                    int(analysis_run_id) if analysis_run_id is not None else None,
                    str(feature or ""),
                    str(model or ""),
                    str(provider or ""),
                    resolved_prompt,
                    resolved_completion,
                    resolved_total,
                    str(token_source or "unknown"),
                    max(0, _safe_int(input_chars)),
                    max(0, _safe_int(output_chars)),
                    str(trace_id or ""),
                    str(prompt_version or ""),
                    str(schema_version or ""),
                    max(0, _safe_int(latency_ms)),
                    str(status or "completed"),
                    str(error_text or "")[:2000],
                    json.dumps(metadata or {}, ensure_ascii=False, default=str),
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def _usage_summary_for_users(self, connection: sqlite3.Connection, user_ids: list[int]) -> dict[int, dict[str, Any]]:
        result = {
            int(user_id): {
                "online_seconds": 0,
                "analysis_count": 0,
                "analysis_input_chars": 0,
                "ai_prompt_tokens": 0,
                "ai_completion_tokens": 0,
                "ai_total_tokens": 0,
                "ai_input_chars": 0,
                "ai_output_chars": 0,
                "total_input_chars": 0,
                "fulltext_book_count": 0,
                "fulltext_char_count": 0,
            }
            for user_id in user_ids
        }
        if not user_ids:
            return result
        placeholders = ",".join("?" for _ in user_ids)
        for row in connection.execute(
            f"""
            SELECT user_id, COALESCE(SUM({_online_seconds_expr()}), 0) AS online_seconds
            FROM user_online_sessions
            WHERE user_id IN ({placeholders})
            GROUP BY user_id
            """,
            user_ids,
        ).fetchall():
            result[int(row["user_id"])]["online_seconds"] = int(row["online_seconds"] or 0)
        for row in connection.execute(
            f"""
            SELECT user_id, COUNT(*) AS analysis_count, COALESCE(SUM(input_chars), 0) AS input_chars
            FROM user_analysis_runs
            WHERE user_id IN ({placeholders})
            GROUP BY user_id
            """,
            user_ids,
        ).fetchall():
            summary = result[int(row["user_id"])]
            summary["analysis_count"] = int(row["analysis_count"] or 0)
            summary["analysis_input_chars"] = int(row["input_chars"] or 0)
        for row in connection.execute(
            f"""
            SELECT
                user_id,
                COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(input_chars), 0) AS input_chars,
                COALESCE(SUM(output_chars), 0) AS output_chars
            FROM user_ai_usage_events
            WHERE user_id IN ({placeholders})
            GROUP BY user_id
            """,
            user_ids,
        ).fetchall():
            summary = result[int(row["user_id"])]
            summary["ai_prompt_tokens"] = int(row["prompt_tokens"] or 0)
            summary["ai_completion_tokens"] = int(row["completion_tokens"] or 0)
            summary["ai_total_tokens"] = int(row["total_tokens"] or 0)
            summary["ai_input_chars"] = int(row["input_chars"] or 0)
            summary["ai_output_chars"] = int(row["output_chars"] or 0)
        for row in connection.execute(
            f"""
            SELECT user_id, COUNT(*) AS book_count, COALESCE(SUM(char_count), 0) AS char_count
            FROM book_fulltexts
            WHERE user_id IN ({placeholders})
            GROUP BY user_id
            """,
            user_ids,
        ).fetchall():
            summary = result[int(row["user_id"])]
            summary["fulltext_book_count"] = int(row["book_count"] or 0)
            summary["fulltext_char_count"] = int(row["char_count"] or 0)
        for summary in result.values():
            summary["total_input_chars"] = int(summary["analysis_input_chars"] or 0) + int(summary["ai_input_chars"] or 0)
        return result

    def _usage_summary_for_user(self, connection: sqlite3.Connection, user_id: int) -> dict[str, Any]:
        return self._usage_summary_for_users(connection, [int(user_id)]).get(int(user_id), {})

    @staticmethod
    def _admin_user_row(row: sqlite3.Row | dict[str, Any], usage_summary: dict[str, Any] | None = None) -> dict[str, Any]:
        item = dict(row)
        item.pop("password_hash", None)
        if usage_summary:
            item.update(usage_summary)
            item["usage_summary"] = dict(usage_summary)
        return item

    @staticmethod
    def _admin_token_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        token = str(item.pop("token", "") or "")
        item["token_preview"] = _masked_token(token)
        item["token_hash"] = item.get("token_hash") or _token_hash(token)
        item["revoked"] = bool(item.get("revoked_at"))
        return item

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

            self._rebuild_book_fulltext(connection, book_id)
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

    def login_user(self, username: str, password: str) -> str | None:
        with _connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT id, password_hash, status FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if not row or not _verify_login_password(password, row["password_hash"]):
                return None
            if str(row["status"] or "active") != "active":
                return None
            token = _generate_token()
            token_hash = _token_hash(token)
            connection.execute(
                """
                INSERT INTO auth_tokens (token, token_hash, user_id, created_at, expires_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP, datetime('now', '+7 days'))
                """,
                (token, token_hash, row["id"]),
            )
            token_row = connection.execute("SELECT expires_at FROM auth_tokens WHERE token_hash = ?", (token_hash,)).fetchone()
            self._record_login_session(
                connection,
                user_id=int(row["id"]),
                token=token,
                expires_at=str(token_row["expires_at"] if token_row else ""),
            )
            connection.commit()
            return token

    def get_user_by_token(self, token: str) -> dict[str, Any] | None:
        token_hash = _token_hash(token)
        with _connect(self.db_path) as connection:
            self._settle_expired_sessions(connection)
            row = connection.execute(
                """
                SELECT u.id, u.username, u.is_author, u.is_admin, u.status,
                       u.disabled_at, u.updated_at, u.bind_reader_id,
                       b.username as bind_reader_name
                FROM auth_tokens t
                JOIN users u ON u.id = t.user_id
                LEFT JOIN users b ON b.id = u.bind_reader_id
                WHERE t.token_hash = ?
                  AND t.revoked_at IS NULL
                  AND t.expires_at > datetime('now')
                  AND u.status = 'active'
                """,
                (token_hash,),
            ).fetchone()
            if not row:
                connection.commit()
                return None
            connection.commit()
            return dict(row)

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
                    self._rebuild_book_fulltext(connection, int(cursor.lastrowid))
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
                    self._rebuild_book_fulltext(connection, int(book_id))
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
            self._rebuild_book_fulltext(connection, int(book_id))
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
            self._rebuild_book_fulltext(connection, int(book_id))
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
            self._rebuild_book_fulltext(connection, int(book_id))
            connection.commit()
        return True

    def ensure_default_bookshelf(self, user_id: int) -> dict[str, Any]:
        with _connect(self.db_path) as connection:
            item = self._ensure_default_bookshelf(connection, int(user_id))
            connection.commit()
            return item

    def _ensure_default_bookshelf(self, connection: sqlite3.Connection, user_id: int) -> dict[str, Any]:
        default_name = _default_bookshelf_name()
        row = connection.execute(
            """
            SELECT id, user_id, name, is_default, created_at, updated_at
            FROM bookshelf_shelves
            WHERE user_id = ? AND is_default = 1 AND deleted_at IS NULL
            ORDER BY id ASC
            LIMIT 1
            """,
            (int(user_id),),
        ).fetchone()
        if not row:
            cursor = connection.execute(
                """
                INSERT INTO bookshelf_shelves (user_id, name, is_default)
                VALUES (?, ?, 1)
                """,
                (int(user_id), default_name),
            )
            row = connection.execute(
                """
                SELECT id, user_id, name, is_default, created_at, updated_at
                FROM bookshelf_shelves
                WHERE id = ?
                """,
                (int(cursor.lastrowid),),
            ).fetchone()
        elif row["name"] != default_name and row["name"] in _system_default_bookshelf_names():
            connection.execute(
                """
                UPDATE bookshelf_shelves
                SET name = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (default_name, int(row["id"])),
            )
            row = connection.execute(
                """
                SELECT id, user_id, name, is_default, created_at, updated_at
                FROM bookshelf_shelves
                WHERE id = ?
                """,
                (int(row["id"]),),
            ).fetchone()
        connection.execute(
            """
            UPDATE bookshelf_items
            SET shelf_id = ?
            WHERE user_id = ? AND shelf_id IS NULL AND deleted_at IS NULL
            """,
            (int(row["id"]), int(user_id)),
        )
        return _bookshelf_shelf_row(row)

    def list_bookshelf_shelves(self, user_id: int) -> list[dict[str, Any]]:
        with _connect(self.db_path) as connection:
            self._ensure_default_bookshelf(connection, int(user_id))
            rows = connection.execute(
                """
                SELECT
                    s.id,
                    s.user_id,
                    s.name,
                    s.is_default,
                    s.created_at,
                    s.updated_at,
                    COUNT(i.id) AS book_count
                FROM bookshelf_shelves AS s
                LEFT JOIN bookshelf_items AS i ON i.shelf_id = s.id AND i.user_id = s.user_id AND i.deleted_at IS NULL
                WHERE s.user_id = ? AND s.deleted_at IS NULL
                GROUP BY s.id
                ORDER BY s.is_default DESC, s.updated_at DESC, s.id DESC
                """,
                (int(user_id),),
            ).fetchall()
            connection.commit()
        return [_bookshelf_shelf_row(row) for row in rows]

    def create_bookshelf_shelf(self, user_id: int, payload: BookshelfCreatePayload) -> dict[str, Any]:
        name = payload.name.strip()
        with _connect(self.db_path) as connection:
            self._ensure_default_bookshelf(connection, int(user_id))
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO bookshelf_shelves (user_id, name, is_default)
                    VALUES (?, ?, 0)
                    """,
                    (int(user_id), name),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail="书架名称已存在") from exc
            row = connection.execute(
                """
                SELECT id, user_id, name, is_default, created_at, updated_at, 0 AS book_count
                FROM bookshelf_shelves
                WHERE id = ? AND deleted_at IS NULL
                """,
                (int(cursor.lastrowid),),
            ).fetchone()
        return _bookshelf_shelf_row(row)

    def _bookshelf_shelf_exists(self, connection: sqlite3.Connection, user_id: int, shelf_id: int) -> bool:
        row = connection.execute(
            "SELECT id FROM bookshelf_shelves WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
            (int(shelf_id), int(user_id)),
        ).fetchone()
        return row is not None

    def list_bookshelf_items(self, user_id: int, shelf_id: int | None = None) -> list[dict[str, Any]] | None:
        with _connect(self.db_path) as connection:
            default_shelf = self._ensure_default_bookshelf(connection, int(user_id))
            target_shelf_id = int(shelf_id or default_shelf["id"])
            if not self._bookshelf_shelf_exists(connection, int(user_id), target_shelf_id):
                return None
            rows = connection.execute(
                """
                SELECT
                    b.id,
                    b.title,
                    b.summary,
                    b.category,
                    b.sub_tags,
                    b.cover_url,
                    b.updated_at,
                    bi.shelf_id,
                    bi.added_at,
                    bi.updated_at AS shelf_updated_at,
                    bi.last_chapter_id,
                    last.title AS last_chapter_title,
                    last.volume_title AS last_chapter_volume_title,
                    last.sort_order AS last_chapter_sort_order,
                    (
                        SELECT COUNT(*)
                        FROM chapters AS count_chapters
                        WHERE count_chapters.book_id = b.id
                          AND count_chapters.status = 'published'
                          AND count_chapters.deleted_at IS NULL
                    ) AS chapter_count,
                    (
                        SELECT COALESCE(SUM(LENGTH(word_chapters.content)), 0)
                        FROM chapters AS word_chapters
                        WHERE word_chapters.book_id = b.id
                          AND word_chapters.status = 'published'
                          AND word_chapters.deleted_at IS NULL
                    ) AS word_count,
                    (
                        SELECT id
                        FROM chapters AS first_chapter
                        WHERE first_chapter.book_id = b.id
                          AND first_chapter.status = 'published'
                          AND first_chapter.deleted_at IS NULL
                        ORDER BY first_chapter.sort_order ASC, first_chapter.id ASC
                        LIMIT 1
                    ) AS first_chapter_id,
                    (
                        SELECT title
                        FROM chapters AS first_chapter
                        WHERE first_chapter.book_id = b.id
                          AND first_chapter.status = 'published'
                          AND first_chapter.deleted_at IS NULL
                        ORDER BY first_chapter.sort_order ASC, first_chapter.id ASC
                        LIMIT 1
                    ) AS first_chapter_title,
                    (
                        SELECT id
                        FROM chapters AS latest
                        WHERE latest.book_id = b.id
                          AND latest.status = 'published'
                          AND latest.deleted_at IS NULL
                        ORDER BY latest.updated_at DESC, latest.id DESC
                        LIMIT 1
                    ) AS latest_chapter_id,
                    (
                        SELECT title
                        FROM chapters AS latest
                        WHERE latest.book_id = b.id
                          AND latest.status = 'published'
                          AND latest.deleted_at IS NULL
                        ORDER BY latest.updated_at DESC, latest.id DESC
                        LIMIT 1
                    ) AS latest_chapter_title,
                    (
                        SELECT volume_title
                        FROM chapters AS latest
                        WHERE latest.book_id = b.id
                          AND latest.status = 'published'
                          AND latest.deleted_at IS NULL
                        ORDER BY latest.updated_at DESC, latest.id DESC
                        LIMIT 1
                    ) AS latest_chapter_volume_title,
                    (
                        SELECT updated_at
                        FROM chapters AS latest
                        WHERE latest.book_id = b.id
                          AND latest.status = 'published'
                          AND latest.deleted_at IS NULL
                        ORDER BY latest.updated_at DESC, latest.id DESC
                        LIMIT 1
                    ) AS latest_chapter_updated_at,
                    (
                        SELECT COUNT(*)
                        FROM chapters AS progress_chapters
                        WHERE progress_chapters.book_id = b.id
                          AND progress_chapters.status = 'published'
                          AND progress_chapters.deleted_at IS NULL
                          AND last.id IS NOT NULL
                          AND (
                            progress_chapters.sort_order < last.sort_order
                            OR (
                                progress_chapters.sort_order = last.sort_order
                                AND progress_chapters.id <= last.id
                            )
                          )
                    ) AS last_chapter_index
                FROM bookshelf_items AS bi
                JOIN books AS b ON b.id = bi.book_id AND b.deleted_at IS NULL
                LEFT JOIN chapters AS last
                  ON last.id = bi.last_chapter_id
                 AND last.book_id = b.id
                 AND last.status = 'published'
                 AND last.deleted_at IS NULL
                WHERE bi.user_id = ? AND bi.shelf_id = ? AND bi.deleted_at IS NULL
                ORDER BY bi.updated_at DESC, bi.id DESC
                """,
                (int(user_id), target_shelf_id),
            ).fetchall()
            connection.commit()
        return [_bookshelf_row(row) for row in rows]

    def get_bookshelf_item(self, user_id: int, book_id: int) -> dict[str, Any] | None:
        items = self.list_bookshelf_items(user_id)
        if items is None:
            return None
        for item in items:
            if int(item["id"]) == int(book_id):
                return item
        return None

    def add_bookshelf_item(self, user_id: int, book_id: int) -> dict[str, Any] | None:
        if not self.get_book(book_id):
            return None
        with _connect(self.db_path) as connection:
            shelf = self._ensure_default_bookshelf(connection, int(user_id))
            connection.execute(
                """
                INSERT INTO bookshelf_items (user_id, shelf_id, book_id)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, book_id) DO UPDATE SET
                    shelf_id = COALESCE(bookshelf_items.shelf_id, excluded.shelf_id),
                    deleted_at = NULL,
                    deleted_by = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (int(user_id), int(shelf["id"]), int(book_id)),
            )
            connection.commit()
        return self.get_bookshelf_item(user_id, book_id)

    def remove_bookshelf_item(self, user_id: int, book_id: int) -> bool:
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE bookshelf_items
                SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP),
                    deleted_by = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND book_id = ? AND deleted_at IS NULL
                """,
                (int(user_id), int(user_id), int(book_id)),
            )
            connection.commit()
        return cursor.rowcount > 0

    def update_bookshelf_progress(
        self,
        user_id: int,
        book_id: int,
        payload: BookshelfProgressPayload,
    ) -> dict[str, Any] | None:
        with _connect(self.db_path) as connection:
            shelf = connection.execute(
                "SELECT id FROM bookshelf_items WHERE user_id = ? AND book_id = ? AND deleted_at IS NULL",
                (int(user_id), int(book_id)),
            ).fetchone()
            if not shelf:
                return None
            chapter = connection.execute(
                """
                SELECT id
                FROM chapters
                WHERE id = ?
                  AND book_id = ?
                  AND status = 'published'
                  AND deleted_at IS NULL
                """,
                (int(payload.chapter_id), int(book_id)),
            ).fetchone()
            if not chapter:
                raise HTTPException(status_code=422, detail="阅读进度章节不属于该书或尚未发布")
            connection.execute(
                """
                UPDATE bookshelf_items
                SET last_chapter_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND book_id = ? AND deleted_at IS NULL
                """,
                (int(payload.chapter_id), int(user_id), int(book_id)),
            )
            connection.commit()
        return self.get_bookshelf_item(user_id, book_id)

    def create_user(self, username: str, password: str, is_author: int = 1) -> dict[str, Any]:
        h = _hash_login_password(password)
        is_admin = 1 if username in _admin_usernames_from_env() else 0
        with _connect(self.db_path) as connection:
            try:
                cursor = connection.execute(
                    "INSERT INTO users (username, password_hash, is_author, is_admin) VALUES (?, ?, ?, ?)",
                    (username, h, is_author, is_admin),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=409, detail="用户名已存在") from exc
        user_id = int(cursor.lastrowid)
        # 注册钩子：复制范例小说《镜中蝉》到新用户云空间
        # __sample__ 自身不克隆，避免递归
        if username != SAMPLE_NOVEL_USERNAME:
            try:
                clone_result = self.clone_sample_novel_to_user(user_id)
            except Exception as exc:  # 范例分发失败不应阻断注册
                logger.warning("clone_sample_novel_to_user failed for user_id=%s: %s", user_id, exc, exc_info=True)
                clone_result = {"cloned": False, "reason": "exception"}
            if clone_result.get("cloned"):
                logger.info(
                    "sample novel cloned to user_id=%s: %s chapters, %s characters, %s cards",
                    user_id,
                    clone_result.get("chapters", 0),
                    clone_result.get("characters", 0),
                    clone_result.get("analysis_cards", 0),
                )
        result = {"id": user_id, "username": username, "is_author": is_author, "is_admin": is_admin}
        return result

    def clone_sample_novel_to_user(self, new_user_id: int) -> dict[str, Any]:
        """将 __sample__ 用户的范例小说《镜中蝉》复制到新用户云空间。

        复制范围（按依赖顺序）：
        - cloud_books / cloud_chapters / cloud_characters
        - cloud_character_state_machines / cloud_character_cycles / cloud_character_snapshots（状态机三表）
        - cloud_character_relationships / cloud_world_entries / cloud_chapter_events
        - cloud_analysis_runs / cloud_analysis_cards

        所有 local_*_id 字段置空（新用户无本地映射）。
        整个操作在单个 with _connect 事务内完成，失败则整体回滚。
        若 __sample__ 用户或其范例书不存在，返回 cloned=False 优雅降级。
        """
        with _connect(self.db_path) as connection:
            sample_row = connection.execute(
                "SELECT id FROM users WHERE username = ?", (SAMPLE_NOVEL_USERNAME,)
            ).fetchone()
            if not sample_row:
                return {"cloned": False, "reason": "sample_user_not_found"}
            sample_user_id = int(sample_row["id"])

            sample_books = connection.execute(
                "SELECT * FROM cloud_books WHERE user_id = ? AND source_type = 'sample' ORDER BY id",
                (sample_user_id,),
            ).fetchall()
            if not sample_books:
                return {"cloned": False, "reason": "sample_book_not_found"}

            stats = {
                "cloned": True, "user_id": new_user_id,
                "books": 0, "chapters": 0, "characters": 0,
                "state_machines": 0, "cycles": 0, "snapshots": 0,
                "relationships": 0, "world_entries": 0, "chapter_events": 0,
                "analysis_runs": 0, "analysis_cards": 0,
            }

            for book_row in sample_books:
                old_book_id = int(book_row["id"])
                # 1. cloud_books
                cursor = connection.execute(
                    """
                    INSERT INTO cloud_books (
                        user_id, title, outline_text, outline_data_json, world_text, world_data_json,
                        cover_image_path, source_type, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_user_id,
                        book_row["title"], book_row["outline_text"], book_row["outline_data_json"],
                        book_row["world_text"], book_row["world_data_json"], book_row["cover_image_path"],
                        "sample_clone", book_row["created_at"], book_row["updated_at"],
                    ),
                )
                new_book_id = int(cursor.lastrowid)
                stats["books"] += 1

                # 1b. books 本地表写入（前端 /api/author/books 只查 books 表，
                #     过滤 source_app=f"user_{user_id}"，必须同步写一份才能在前端"我的作品"看到）
                local_book_cursor = connection.execute(
                    """
                    INSERT INTO books (source_app, source_book_id, title, summary, category, cover_url, is_test)
                    VALUES (?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        f"user_{new_user_id}",
                        str(new_book_id),
                        book_row["title"],
                        book_row["outline_text"] or "",
                        "范例",
                        book_row["cover_image_path"] or "",
                    ),
                )
                local_book_id = int(local_book_cursor.lastrowid)
                stats["books_local"] = stats.get("books_local", 0) + 1

                # 2. cloud_chapters + chapters 本地表（建立 old_chapter_id -> new_chapter_id 映射）
                chapter_id_map: dict[int, int] = {}
                for ch_row in connection.execute(
                    "SELECT * FROM cloud_chapters WHERE cloud_book_id = ? ORDER BY sort_order, id",
                    (old_book_id,),
                ).fetchall():
                    c = connection.execute(
                        """
                        INSERT INTO cloud_chapters (
                            cloud_book_id, cloud_volume_id, title, outline, content, summary_text,
                            chapter_type, sort_order, ai_probability, ai_probability_level, created_at, updated_at
                        ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_book_id, ch_row["title"], ch_row["outline"], ch_row["content"],
                            ch_row["summary_text"], ch_row["chapter_type"], ch_row["sort_order"],
                            ch_row["ai_probability"], ch_row["ai_probability_level"],
                            ch_row["created_at"], ch_row["updated_at"],
                        ),
                    )
                    chapter_id_map[int(ch_row["id"])] = int(c.lastrowid)
                    stats["chapters"] += 1
                    # 同步写 chapters 本地表（前端 /api/author/books 统计 chapter_count/word_count 依赖）
                    connection.execute(
                        """
                        INSERT INTO chapters (
                            book_id, source_chapter_id, volume_title, title, outline, summary_text,
                            content, sort_order, ai_probability, ai_probability_level
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            local_book_id, str(c.lastrowid), "正文",
                            ch_row["title"], ch_row["outline"], ch_row["summary_text"],
                            ch_row["content"], ch_row["sort_order"],
                            ch_row["ai_probability"], ch_row["ai_probability_level"],
                        ),
                    )
                    stats["chapters_local"] = stats.get("chapters_local", 0) + 1

                # 3. cloud_characters + 状态机三表（建立 old_char_id -> new_char_id 映射）
                char_id_map: dict[int, int] = {}
                for char_row in connection.execute(
                    "SELECT * FROM cloud_characters WHERE cloud_book_id = ? ORDER BY id",
                    (old_book_id,),
                ).fetchall():
                    c = connection.execute(
                        """
                        INSERT INTO cloud_characters (
                            cloud_book_id, name, role, profile_text, profile_data_json, image_path,
                            graph_x, graph_y, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_book_id, char_row["name"], char_row["role"], char_row["profile_text"],
                            char_row["profile_data_json"], char_row["image_path"], char_row["graph_x"],
                            char_row["graph_y"], char_row["created_at"], char_row["updated_at"],
                        ),
                    )
                    old_cid = int(char_row["id"])
                    new_cid = int(c.lastrowid)
                    char_id_map[old_cid] = new_cid
                    stats["characters"] += 1

                    # 4. cloud_character_state_machines
                    sm_row = connection.execute(
                        "SELECT * FROM cloud_character_state_machines WHERE cloud_character_id = ?",
                        (old_cid,),
                    ).fetchone()
                    if sm_row:
                        connection.execute(
                            """
                            INSERT INTO cloud_character_state_machines (
                                cloud_character_id,
                                desire_text, desire_origin, desire_anchor, desire_extreme, desire_fear_mirror,
                                mbti_type, mbti_i_e, mbti_n_s, mbti_t_f, mbti_j_p,
                                mbti_strategy, mbti_advantage, mbti_blindspot,
                                fate_type, fate_content, fate_trigger, fate_target, fate_limit,
                                belief_core, belief_origin, belief_alignment, belief_sacrifice, belief_taboo,
                                current_desire_state, current_mbti_state, current_fate_state, current_belief_state,
                                current_friction, current_dilemma, total_change_score, last_update_source,
                                created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                new_cid,
                                sm_row["desire_text"], sm_row["desire_origin"], sm_row["desire_anchor"],
                                sm_row["desire_extreme"], sm_row["desire_fear_mirror"],
                                sm_row["mbti_type"], sm_row["mbti_i_e"], sm_row["mbti_n_s"], sm_row["mbti_t_f"],
                                sm_row["mbti_j_p"], sm_row["mbti_strategy"], sm_row["mbti_advantage"], sm_row["mbti_blindspot"],
                                sm_row["fate_type"], sm_row["fate_content"], sm_row["fate_trigger"], sm_row["fate_target"],
                                sm_row["fate_limit"],
                                sm_row["belief_core"], sm_row["belief_origin"], sm_row["belief_alignment"],
                                sm_row["belief_sacrifice"], sm_row["belief_taboo"],
                                sm_row["current_desire_state"], sm_row["current_mbti_state"], sm_row["current_fate_state"],
                                sm_row["current_belief_state"], sm_row["current_friction"], sm_row["current_dilemma"],
                                sm_row["total_change_score"], sm_row["last_update_source"],
                                sm_row["created_at"], sm_row["updated_at"],
                            ),
                        )
                        stats["state_machines"] += 1

                    # 5. cloud_character_cycles
                    for cycle_row in connection.execute(
                        "SELECT * FROM cloud_character_cycles WHERE cloud_character_id = ? ORDER BY sort_order, id",
                        (old_cid,),
                    ).fetchall():
                        connection.execute(
                            """
                            INSERT INTO cloud_character_cycles (
                                cloud_character_id, cycle_type, cycle_code, triggered_desire,
                                belief_filtered_strategy, action_taken, world_feedback, feedback_intensity,
                                mbti_change, star_state, fate_state, internal_friction,
                                change_score, cumulative_score, batch_span, batch_micro_count,
                                batch_summary, sort_order, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                new_cid, cycle_row["cycle_type"], cycle_row["cycle_code"],
                                cycle_row["triggered_desire"], cycle_row["belief_filtered_strategy"],
                                cycle_row["action_taken"], cycle_row["world_feedback"], cycle_row["feedback_intensity"],
                                cycle_row["mbti_change"], cycle_row["star_state"], cycle_row["fate_state"],
                                cycle_row["internal_friction"], cycle_row["change_score"], cycle_row["cumulative_score"],
                                cycle_row["batch_span"], cycle_row["batch_micro_count"], cycle_row["batch_summary"],
                                cycle_row["sort_order"], cycle_row["created_at"],
                            ),
                        )
                        stats["cycles"] += 1

                    # 6. cloud_character_snapshots
                    for snap_row in connection.execute(
                        "SELECT * FROM cloud_character_snapshots WHERE cloud_character_id = ? ORDER BY snapshot_no, id",
                        (old_cid,),
                    ).fetchall():
                        connection.execute(
                            """
                            INSERT INTO cloud_character_snapshots (
                                cloud_character_id, snapshot_no, trigger_type, trigger_detail, related_cycle_id,
                                desire_state, mbti_state, fate_state, belief_state, friction_level, phase_dilemma,
                                phase_change_summary, micro_cycle_summary, total_score_at_snapshot, created_at
                            ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                new_cid, snap_row["snapshot_no"], snap_row["trigger_type"], snap_row["trigger_detail"],
                                snap_row["desire_state"], snap_row["mbti_state"], snap_row["fate_state"],
                                snap_row["belief_state"], snap_row["friction_level"], snap_row["phase_dilemma"],
                                snap_row["phase_change_summary"], snap_row["micro_cycle_summary"],
                                snap_row["total_score_at_snapshot"], snap_row["created_at"],
                            ),
                        )
                        stats["snapshots"] += 1

                # 7. cloud_character_relationships
                for rel_row in connection.execute(
                    "SELECT * FROM cloud_character_relationships WHERE cloud_book_id = ? ORDER BY id",
                    (old_book_id,),
                ).fetchall():
                    new_src = char_id_map.get(int(rel_row["source_character_id"]))
                    new_tgt = char_id_map.get(int(rel_row["target_character_id"]))
                    if not new_src or not new_tgt:
                        continue
                    connection.execute(
                        """
                        INSERT INTO cloud_character_relationships (
                            cloud_book_id, source_character_id, target_character_id,
                            relationship_type, description, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_book_id, new_src, new_tgt,
                            rel_row["relationship_type"], rel_row["description"],
                            rel_row["created_at"], rel_row["updated_at"],
                        ),
                    )
                    stats["relationships"] += 1

                # 8. cloud_world_entries
                for we_row in connection.execute(
                    "SELECT * FROM cloud_world_entries WHERE cloud_book_id = ? ORDER BY id",
                    (old_book_id,),
                ).fetchall():
                    connection.execute(
                        """
                        INSERT INTO cloud_world_entries (
                            cloud_book_id, name, category, content_text, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_book_id, we_row["name"], we_row["category"], we_row["content_text"],
                            we_row["created_at"], we_row["updated_at"],
                        ),
                    )
                    stats["world_entries"] += 1

                # 9. cloud_chapter_events
                for ev_row in connection.execute(
                    "SELECT * FROM cloud_chapter_events WHERE cloud_book_id = ? ORDER BY sort_order, id",
                    (old_book_id,),
                ).fetchall():
                    new_ch_id = chapter_id_map.get(int(ev_row["cloud_chapter_id"]))
                    if not new_ch_id:
                        continue
                    connection.execute(
                        """
                        INSERT INTO cloud_chapter_events (
                            cloud_book_id, cloud_chapter_id, label, description, sort_order, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_book_id, new_ch_id, ev_row["label"], ev_row["description"],
                            ev_row["sort_order"], ev_row["created_at"], ev_row["updated_at"],
                        ),
                    )
                    stats["chapter_events"] += 1

                # 10. cloud_analysis_runs（建立 old_run_id -> new_run_id 映射）
                run_id_map: dict[int, int] = {}
                for run_row in connection.execute(
                    "SELECT * FROM cloud_analysis_runs WHERE cloud_book_id = ? ORDER BY id",
                    (old_book_id,),
                ).fetchall():
                    c = connection.execute(
                        """
                        INSERT INTO cloud_analysis_runs (
                            cloud_book_id, scope_type, status, pipeline_version, input_hash,
                            summary, error_text, meta_json, completed_at, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_book_id, run_row["scope_type"], run_row["status"], run_row["pipeline_version"],
                            run_row["input_hash"], run_row["summary"], run_row["error_text"], run_row["meta_json"],
                            run_row["completed_at"], run_row["created_at"], run_row["updated_at"],
                        ),
                    )
                    run_id_map[int(run_row["id"])] = int(c.lastrowid)
                    stats["analysis_runs"] += 1

                # 11. cloud_analysis_cards
                for card_row in connection.execute(
                    "SELECT * FROM cloud_analysis_cards WHERE cloud_book_id = ? ORDER BY id",
                    (old_book_id,),
                ).fetchall():
                    new_run_id = run_id_map.get(int(card_row["cloud_run_id"]))
                    if not new_run_id:
                        continue
                    connection.execute(
                        """
                        INSERT INTO cloud_analysis_cards (
                            cloud_book_id, cloud_run_id, card_uid, card_type, entity_uid, card_version,
                            ars_score, status, payload_json, diff_json, applied_table, applied_at,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            new_book_id, new_run_id, card_row["card_uid"], card_row["card_type"],
                            card_row["entity_uid"], card_row["card_version"], card_row["ars_score"],
                            card_row["status"], card_row["payload_json"], card_row["diff_json"],
                            card_row["applied_table"], card_row["applied_at"],
                            card_row["created_at"], card_row["updated_at"],
                        ),
                    )
                    stats["analysis_cards"] += 1

        # novels.db 的写入由 auth.py register 端点调用 _seed_sample_to_workspace 完成
        # （使用 WorkspaceDB 共享 Database 连接，避免 sqlite3 锁冲突）

        return stats

    def bind_reader(self, author_id: int, reader_id: int) -> None:
        with _connect(self.db_path) as connection:
            connection.execute("UPDATE users SET bind_reader_id = ? WHERE id = ?", (reader_id, author_id))
            connection.commit()

    def check_device_trusted(self, user_id: int, fingerprint: str, ip_address: str) -> dict[str, Any]:
        with _connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT id, trusted_until, ip_address
                FROM trusted_devices
                WHERE user_id = ? AND fingerprint = ? AND trusted_until > datetime('now')
                """,
                (user_id, fingerprint),
            ).fetchone()
        if row:
            return {
                "trusted": True,
                "requires_verification": False,
                "trusted_until": str(row["trusted_until"]),
                "last_ip": str(row["ip_address"] or ""),
            }
        return {
            "trusted": False,
            "requires_verification": True,
            "reason": "new_or_expired_device",
            "current_ip": ip_address,
        }

    def trust_device(self, user_id: int, fingerprint: str, device_info: str, ip_address: str) -> None:
        with _connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO trusted_devices (
                    user_id, fingerprint, device_info, ip_address, trusted_until
                )
                VALUES (?, ?, ?, ?, datetime('now', '+30 days'))
                ON CONFLICT(user_id, fingerprint) DO UPDATE SET
                    device_info = excluded.device_info,
                    ip_address = excluded.ip_address,
                    trusted_until = excluded.trusted_until,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, fingerprint, device_info, ip_address),
            )
            connection.commit()

    def get_trusted_devices(self, user_id: int) -> list[dict[str, Any]]:
        with _connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT fingerprint, device_info, ip_address, trusted_until, updated_at
                FROM trusted_devices
                WHERE user_id = ? AND trusted_until > datetime('now')
                ORDER BY updated_at DESC, id DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def sync_admin_users(self, usernames: set[str]) -> None:
        clean = [name.strip() for name in usernames if name.strip()]
        if not clean:
            return
        with _connect(self.db_path) as connection:
            connection.executemany(
                "UPDATE users SET is_admin = 1, updated_at = CURRENT_TIMESTAMP WHERE username = ?",
                [(name,) for name in clean],
            )
            connection.commit()

    def _record_admin_audit(
        self,
        connection: sqlite3.Connection,
        admin_user_id: int,
        action: str,
        object_type: str,
        object_id: int | str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO admin_audit_logs (admin_user_id, action, object_type, object_id, detail)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(admin_user_id),
                action,
                object_type,
                str(object_id or ""),
                json.dumps(detail or {}, ensure_ascii=False, default=str),
            ),
        )

    def admin_overview(self) -> dict[str, Any]:
        with _connect(self.db_path) as connection:
            self._settle_expired_sessions(connection)
            counts = {
                "users": connection.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                "active_users": connection.execute("SELECT COUNT(*) FROM users WHERE status = 'active'").fetchone()[0],
                "books": connection.execute("SELECT COUNT(*) FROM books").fetchone()[0],
                "active_books": connection.execute("SELECT COUNT(*) FROM books WHERE deleted_at IS NULL").fetchone()[0],
                "chapters": connection.execute("SELECT COUNT(*) FROM chapters").fetchone()[0],
                "active_chapters": connection.execute("SELECT COUNT(*) FROM chapters WHERE deleted_at IS NULL").fetchone()[0],
                "bookshelf_items": connection.execute("SELECT COUNT(*) FROM bookshelf_items").fetchone()[0],
                "active_tokens": connection.execute("SELECT COUNT(*) FROM auth_tokens WHERE revoked_at IS NULL AND expires_at > datetime('now')").fetchone()[0],
                "trusted_devices": connection.execute("SELECT COUNT(*) FROM trusted_devices WHERE trusted_until > datetime('now')").fetchone()[0],
                "book_fulltexts": connection.execute("SELECT COUNT(*) FROM book_fulltexts").fetchone()[0],
                "book_fulltext_chars": connection.execute("SELECT COALESCE(SUM(char_count), 0) FROM book_fulltexts").fetchone()[0],
                "online_seconds": connection.execute(f"SELECT COALESCE(SUM({_online_seconds_expr()}), 0) FROM {_validate_table('user_online_sessions')}").fetchone()[0],
                "analysis_runs": connection.execute("SELECT COUNT(*) FROM user_analysis_runs").fetchone()[0],
                "analysis_input_chars": connection.execute("SELECT COALESCE(SUM(input_chars), 0) FROM user_analysis_runs").fetchone()[0],
                "ai_prompt_tokens": connection.execute("SELECT COALESCE(SUM(prompt_tokens), 0) FROM user_ai_usage_events").fetchone()[0],
                "ai_completion_tokens": connection.execute("SELECT COALESCE(SUM(completion_tokens), 0) FROM user_ai_usage_events").fetchone()[0],
                "ai_total_tokens": connection.execute("SELECT COALESCE(SUM(total_tokens), 0) FROM user_ai_usage_events").fetchone()[0],
                "ai_input_chars": connection.execute("SELECT COALESCE(SUM(input_chars), 0) FROM user_ai_usage_events").fetchone()[0],
                "ai_output_chars": connection.execute("SELECT COALESCE(SUM(output_chars), 0) FROM user_ai_usage_events").fetchone()[0],
            }
            counts["total_input_chars"] = int(counts["analysis_input_chars"] or 0) + int(counts["ai_input_chars"] or 0)
            chapter_statuses = [
                dict(row)
                for row in connection.execute(
                    "SELECT status, COUNT(*) AS count FROM chapters GROUP BY status ORDER BY count DESC"
                ).fetchall()
            ]
            recent_audits = [
                dict(row)
                for row in connection.execute(
                    """
                SELECT l.*, COALESCE(au.username, u.username, '') AS admin_username
                FROM admin_audit_logs AS l
                LEFT JOIN admin_users AS au ON au.id = l.admin_user_id
                LEFT JOIN users AS u ON u.id = l.admin_user_id
                ORDER BY l.created_at DESC, l.id DESC
                LIMIT 10
                """
                ).fetchall()
            ]
            connection.commit()
        return {"counts": counts, "chapter_statuses": chapter_statuses, "recent_audits": recent_audits}

    def admin_user_stats(self, granularity: str = "monthly", year: int | None = None, month: str | None = None) -> dict[str, Any]:
        """用户统计：数据起始2026-06-01，支持 monthly/yearly/daily + 年份/月份筛选"""
        data_start = "2026-06-01 00:00:00"
        with _connect(self.db_path) as connection:
            now = connection.execute("SELECT datetime('now', 'localtime')").fetchone()[0]
            month_start = now[:8] + "01 00:00:00"
            three_months_ago = connection.execute(
                "SELECT datetime('now', 'localtime', '-3 months', 'start of month')"
            ).fetchone()[0]

            # 所有计数从2026-06-01起算
            total_users = connection.execute(
                "SELECT COUNT(*) FROM users WHERE created_at >= ?", (data_start,)
            ).fetchone()[0]
            new_this_month = connection.execute(
                "SELECT COUNT(*) FROM users WHERE created_at >= ? AND created_at >= ?", (data_start, month_start)
            ).fetchone()[0]
            dormant_users = connection.execute(
                "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at < ? AND created_at >= ?",
                (three_months_ago, data_start)
            ).fetchone()[0]
            active_this_month = connection.execute(
                "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at >= ? AND created_at >= ?",
                (month_start, data_start)
            ).fetchone()[0]

            trends: dict[str, list[dict[str, Any]]] = {"new_users": [], "dormant_users": [], "active_users": []}

            if granularity == "monthly" and month is not None:
                # 指定月份的按天明细 (1-30/31)
                year_part, mon_part = month.split("-")
                y, m = int(year_part), int(mon_part)
                import calendar
                days_in_month = calendar.monthrange(y, m)[1]
                for d in range(1, days_in_month + 1):
                    day_label = f"{m:02d}-{d:02d}"
                    day_begin = f"{y}-{m:02d}-{d:02d} 00:00:00"
                    day_end = f"{y}-{m:02d}-{d + 1:02d} 00:00:00" if d < days_in_month else f"{y}-{m + 1:02d}-01 00:00:00" if m < 12 else f"{y + 1}-01-01 00:00:00"
                    dormant_before = connection.execute(
                        "SELECT datetime(?, '-3 months')", (day_begin,)
                    ).fetchone()[0]

                    new_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE created_at >= ? AND created_at < ? AND created_at >= ?",
                        (day_begin, day_end, data_start),
                    ).fetchone()[0]
                    dormant_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at < ? AND created_at < ? AND created_at >= ?",
                        (dormant_before, day_end, data_start),
                    ).fetchone()[0]
                    active_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at >= ? AND updated_at < ? AND created_at >= ?",
                        (day_begin, day_end, data_start),
                    ).fetchone()[0]

                    trends["new_users"].append({"month": day_label, "count": new_count})
                    trends["dormant_users"].append({"month": day_label, "count": dormant_count})
                    trends["active_users"].append({"month": day_label, "count": active_count})
            elif granularity == "yearly" and year is not None:
                # 指定年份的1-12月月度明细
                for m_ in range(1, 13):
                    month_label = f"{year}-{m_:02d}"
                    month_begin = f"{year}-{m_:02d}-01 00:00:00"
                    month_end = f"{year}-{m_ + 1:02d}-01 00:00:00" if m_ < 12 else f"{year + 1}-01-01 00:00:00"
                    dormant_before_val = connection.execute(
                        "SELECT datetime(?, '-3 months')", (month_begin,)
                    ).fetchone()[0]

                    new_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE created_at >= ? AND created_at < ? AND created_at >= ?",
                        (month_begin, month_end, data_start),
                    ).fetchone()[0]
                    dormant_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at < ? AND created_at < ? AND created_at >= ?",
                        (dormant_before_val, month_end, data_start),
                    ).fetchone()[0]
                    active_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at >= ? AND updated_at < ? AND created_at >= ?",
                        (month_begin, month_end, data_start),
                    ).fetchone()[0]

                    trends["new_users"].append({"month": month_label, "count": new_count})
                    trends["dormant_users"].append({"month": month_label, "count": dormant_count})
                    trends["active_users"].append({"month": month_label, "count": active_count})
            elif granularity == "yearly":
                # 近5年（从2026起）
                current_year = int(now[:4])
                for y_ in range(2026, current_year + 1):
                    year_label = str(y_)
                    year_begin = f"{year_label}-01-01 00:00:00"
                    year_end = f"{y_ + 1}-01-01 00:00:00"
                    dormant_before_val = connection.execute(
                        "SELECT datetime(?, '-3 months')", (year_begin,)
                    ).fetchone()[0]

                    new_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE created_at >= ? AND created_at < ? AND created_at >= ?",
                        (year_begin, year_end, data_start),
                    ).fetchone()[0]
                    dormant_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at < ? AND created_at < ? AND created_at >= ?",
                        (dormant_before_val, year_end, data_start),
                    ).fetchone()[0]
                    active_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at >= ? AND updated_at < ? AND created_at >= ?",
                        (year_begin, year_end, data_start),
                    ).fetchone()[0]

                    trends["new_users"].append({"month": year_label, "count": new_count})
                    trends["dormant_users"].append({"month": year_label, "count": dormant_count})
                    trends["active_users"].append({"month": year_label, "count": active_count})
            else:
                # monthly: 从2026-06起的所有月份
                current_year = int(now[:4])
                current_mon = int(now[5:7])
                start_y, start_m = 2026, 6
                months_list: list[tuple[int, int]] = []
                for y_ in range(start_y, current_year + 1):
                    m_start = start_m if y_ == start_y else 1
                    m_end = current_mon if y_ == current_year else 12
                    for m_ in range(m_start, m_end + 1):
                        months_list.append((y_, m_))
                for (y_, m_) in months_list:
                    month_label = f"{y_}-{m_:02d}"
                    month_begin = f"{y_}-{m_:02d}-01 00:00:00"
                    month_end = f"{y_}-{m_ + 1:02d}-01 00:00:00" if m_ < 12 else f"{y_ + 1}-01-01 00:00:00"
                    dormant_before_val = connection.execute(
                        "SELECT datetime(?, '-3 months')", (month_begin,)
                    ).fetchone()[0]

                    new_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE created_at >= ? AND created_at < ? AND created_at >= ?",
                        (month_begin, month_end, data_start),
                    ).fetchone()[0]
                    dormant_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at < ? AND created_at < ? AND created_at >= ?",
                        (dormant_before_val, month_end, data_start),
                    ).fetchone()[0]
                    active_count = connection.execute(
                        "SELECT COUNT(*) FROM users WHERE status = 'active' AND updated_at >= ? AND updated_at < ? AND created_at >= ?",
                        (month_begin, month_end, data_start),
                    ).fetchone()[0]

                    trends["new_users"].append({"month": month_label, "count": new_count})
                    trends["dormant_users"].append({"month": month_label, "count": dormant_count})
                    trends["active_users"].append({"month": month_label, "count": active_count})

        result: dict[str, Any] = {
            "total_users": total_users,
            "new_this_month": new_this_month,
            "dormant_users": dormant_users,
            "active_this_month": active_this_month,
            "trends": trends,
            "granularity": granularity,
        }
        if year is not None:
            result["year"] = year
        if month is not None:
            result["month"] = month
        return result

    def admin_list_users(self, q: str = "", page: int = 1, page_size: int = 20) -> dict[str, Any]:
        params: list[Any] = []
        where = ""
        if q.strip():
            where = "WHERE username LIKE ? ESCAPE '\\'"
            params.append(f"%{_escape_like(q.strip())}%")
        preload_pages = 3
        limit = page_size * (1 + preload_pages)
        offset = (page - 1) * page_size
        with _connect(self.db_path) as connection:
            self._settle_expired_sessions(connection)
            count_row = connection.execute(
                f"SELECT COUNT(*) FROM (SELECT u.id FROM {_validate_table('users')} AS u {where} GROUP BY u.id)",
                params,
            ).fetchone()
            total = count_row[0] if count_row else 0
            rows = connection.execute(
                f"""
                SELECT
                    u.*,
                    COUNT(DISTINCT CASE WHEN at.revoked_at IS NULL AND at.expires_at > datetime('now') THEN at.token END) AS token_count,
                    COUNT(DISTINCT td.id) AS device_count,
                    COUNT(DISTINCT bi.id) AS bookshelf_item_count
                FROM users AS u
                LEFT JOIN auth_tokens AS at ON at.user_id = u.id
                LEFT JOIN trusted_devices AS td ON td.user_id = u.id
                LEFT JOIN bookshelf_items AS bi ON bi.user_id = u.id AND bi.deleted_at IS NULL
                {where}
                GROUP BY u.id
                ORDER BY u.id DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
            user_ids = [int(row["id"]) for row in rows]
            usage = self._usage_summary_for_users(connection, user_ids)
            items = [self._admin_user_row(row, usage.get(int(row["id"]))) for row in rows]
            connection.commit()
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def admin_get_user(self, user_id: int) -> dict[str, Any] | None:
        with _connect(self.db_path) as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
            if not row:
                return None
            self._settle_expired_sessions(connection)
            usage = self._usage_summary_for_user(connection, int(user_id))
            result = self._admin_user_row(row, usage)
            result["tokens"] = [
                self._admin_token_row(item)
                for item in connection.execute(
                    "SELECT * FROM auth_tokens WHERE user_id = ? ORDER BY expires_at DESC",
                    (int(user_id),),
                ).fetchall()
            ]
            result["trusted_devices"] = [
                dict(item)
                for item in connection.execute(
                    "SELECT * FROM trusted_devices WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
                    (int(user_id),),
                ).fetchall()
            ]
            result["online_sessions"] = [
                dict(item)
                for item in connection.execute(
                    """
                    SELECT
                        id, user_id, token_hash, login_at, expires_at, logout_at,
                        CASE
                            WHEN status = 'active' THEN """ + _online_seconds_expr() + """
                            ELSE COALESCE(estimated_online_seconds, 0)
                        END AS estimated_online_seconds,
                        status, created_at, updated_at
                    FROM user_online_sessions
                    WHERE user_id = ?
                    ORDER BY login_at DESC, id DESC
                    LIMIT 20
                    """,
                    (int(user_id),),
                ).fetchall()
            ]
            result["analysis_runs"] = [
                dict(item)
                for item in connection.execute(
                    """
                    SELECT id, user_id, book_id, run_ref, analysis_mode, input_chars,
                           status, source, error_text, metadata, started_at, completed_at, created_at, updated_at
                    FROM user_analysis_runs
                    WHERE user_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT 20
                    """,
                    (int(user_id),),
                ).fetchall()
            ]
            result["ai_usage_events"] = [
                dict(item)
                for item in connection.execute(
                    """
                    SELECT id, user_id, book_id, analysis_run_id, feature, model, provider,
                           prompt_tokens, completion_tokens, total_tokens, token_source,
                           input_chars, output_chars, trace_id, prompt_version, schema_version,
                           latency_ms, status, error_text, metadata, created_at
                    FROM user_ai_usage_events
                    WHERE user_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT 20
                    """,
                    (int(user_id),),
                ).fetchall()
            ]
            result["book_fulltexts"] = [
                dict(item)
                for item in connection.execute(
                    """
                    SELECT f.book_id, b.title, f.content_hash, f.chapter_count,
                           f.char_count, f.revision, f.updated_at
                    FROM book_fulltexts AS f
                    JOIN books AS b ON b.id = f.book_id
                    WHERE f.user_id = ?
                    ORDER BY f.updated_at DESC, f.book_id DESC
                    LIMIT 20
                    """,
                    (int(user_id),),
                ).fetchall()
            ]
            connection.commit()
        return result

    def admin_update_user(self, admin_user_id: int, user_id: int, payload: AdminUserUpdatePayload) -> dict[str, Any] | None:
        updates: list[str] = []
        params: list[Any] = []
        if payload.is_author is not None:
            _validate_column("is_author")
            updates.append("is_author = ?")
            params.append(int(payload.is_author))
        if payload.is_admin is not None:
            _validate_column("is_admin")
            updates.append("is_admin = ?")
            params.append(int(payload.is_admin))
        if payload.status is not None:
            status = payload.status.strip() or "active"
            _validate_column("status")
            updates.append("status = ?")
            params.append(status)
            _validate_column("disabled_at")
            updates.append("disabled_at = CASE WHEN ? = 'active' THEN NULL ELSE COALESCE(disabled_at, CURRENT_TIMESTAMP) END")
            params.append(status)
        if not updates:
            return self.admin_get_user(user_id)
        _validate_column("updated_at")
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(int(user_id))
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                f"UPDATE {_validate_table('users')} SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            if cursor.rowcount <= 0:
                return None
            self._record_admin_audit(connection, admin_user_id, "update", "user", user_id, payload.model_dump(exclude_none=True))
            connection.commit()
        return self.admin_get_user(user_id)

    def admin_disable_user(self, admin_user_id: int, user_id: int) -> bool:
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE users
                SET status = 'disabled', disabled_at = COALESCE(disabled_at, CURRENT_TIMESTAMP), updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (int(user_id),),
            )
            if cursor.rowcount <= 0:
                return False
            token_rows = connection.execute(
                "SELECT token_hash FROM auth_tokens WHERE user_id = ? AND revoked_at IS NULL",
                (int(user_id),),
            ).fetchall()
            connection.execute(
                "UPDATE auth_tokens SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP) WHERE user_id = ?",
                (int(user_id),),
            )
            for token_row in token_rows:
                self._settle_online_session(connection, token_hash=str(token_row["token_hash"] or ""), status="revoked")
            self._record_admin_audit(connection, admin_user_id, "disable", "user", user_id)
            connection.commit()
        return True

    def admin_restore_user(self, admin_user_id: int, user_id: int) -> bool:
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                "UPDATE users SET status = 'active', disabled_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(user_id),),
            )
            if cursor.rowcount <= 0:
                return False
            self._record_admin_audit(connection, admin_user_id, "restore", "user", user_id)
            connection.commit()
        return True

    def admin_list_books(self, q: str = "", include_deleted: bool = True, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        where = ["1 = 1"]
        params: list[Any] = []
        if not include_deleted:
            where.append("b.deleted_at IS NULL")
        if q.strip():
            where.append("(b.title LIKE ? ESCAPE '\\' OR b.category LIKE ? ESCAPE '\\' OR b.source_app LIKE ? ESCAPE '\\')")
            like = f"%{_escape_like(q.strip())}%"
            params.extend([like, like, like])
        preload_pages = 3
        limit = page_size * (1 + preload_pages)
        offset = (page - 1) * page_size
        where_clause = ' AND '.join(where)
        with _connect(self.db_path) as connection:
            count_row = connection.execute(
                f"SELECT COUNT(*) FROM {_validate_table('books')} AS b WHERE {where_clause}",
                params,
            ).fetchone()
            total = count_row[0] if count_row else 0
            rows = connection.execute(
                f"""
                SELECT
                    b.*,
                    COUNT(c.id) AS chapter_count,
                    COALESCE(SUM(LENGTH(c.content)), 0) AS word_count,
                    f.char_count AS fulltext_char_count,
                    f.chapter_count AS fulltext_chapter_count,
                    f.revision AS fulltext_revision,
                    f.updated_at AS fulltext_updated_at
                FROM books AS b
                LEFT JOIN chapters AS c ON c.book_id = b.id AND c.deleted_at IS NULL
                LEFT JOIN book_fulltexts AS f ON f.book_id = b.id
                WHERE {where_clause}
                GROUP BY b.id
                ORDER BY b.updated_at DESC, b.id DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
        return {"items": [_book_row(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    def admin_get_book(self, book_id: int) -> dict[str, Any] | None:
        with _connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT
                    b.*,
                    COUNT(c.id) AS chapter_count,
                    COALESCE(SUM(LENGTH(c.content)), 0) AS word_count,
                    f.content AS fulltext,
                    f.content_hash AS fulltext_hash,
                    f.char_count AS fulltext_char_count,
                    f.chapter_count AS fulltext_chapter_count,
                    f.revision AS fulltext_revision,
                    f.updated_at AS fulltext_updated_at
                FROM books AS b
                LEFT JOIN chapters AS c ON c.book_id = b.id AND c.deleted_at IS NULL
                LEFT JOIN book_fulltexts AS f ON f.book_id = b.id
                WHERE b.id = ?
                GROUP BY b.id
                """,
                (int(book_id),),
            ).fetchone()
        return _book_row(row) if row else None

    def admin_update_book(self, admin_user_id: int, book_id: int, payload: AdminBookUpdatePayload) -> dict[str, Any] | None:
        mapping = payload.model_dump(exclude_none=True)
        if "sub_tags" in mapping:
            mapping["sub_tags"] = _normalize_book_tags(str(mapping["sub_tags"]))
        allowed = ["title", "summary", "category", "sub_tags", "cover_url", "is_test"]
        _validate_columns(allowed)
        updates = [f"{key} = ?" for key in allowed if key in mapping]
        params = [mapping[key] for key in allowed if key in mapping]
        if not updates:
            return self.admin_get_book(book_id)
        _validate_column("updated_at")
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(int(book_id))
        with _connect(self.db_path) as connection:
            cursor = connection.execute(f"UPDATE {_validate_table('books')} SET {', '.join(updates)} WHERE id = ?", params)
            if cursor.rowcount <= 0:
                return None
            self._record_admin_audit(connection, admin_user_id, "update", "book", book_id, mapping)
            connection.commit()
        return self.admin_get_book(book_id)

    def admin_soft_delete_book(self, admin_user_id: int, book_id: int) -> bool:
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                "UPDATE books SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP), deleted_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(admin_user_id), int(book_id)),
            )
            if cursor.rowcount <= 0:
                return False
            self._record_admin_audit(connection, admin_user_id, "delete", "book", book_id)
            connection.commit()
        return True

    def admin_restore_book(self, admin_user_id: int, book_id: int) -> bool:
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                "UPDATE books SET deleted_at = NULL, deleted_by = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(book_id),),
            )
            if cursor.rowcount <= 0:
                return False
            self._record_admin_audit(connection, admin_user_id, "restore", "book", book_id)
            connection.commit()
        return True

    def admin_list_chapters(self, book_id: int | None = None, q: str = "", include_deleted: bool = True, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        where = ["1 = 1"]
        params: list[Any] = []
        if book_id:
            where.append("c.book_id = ?")
            params.append(int(book_id))
        if not include_deleted:
            where.append("c.deleted_at IS NULL")
        if q.strip():
            where.append("(c.title LIKE ? ESCAPE '\\' OR c.content LIKE ? ESCAPE '\\' OR b.title LIKE ? ESCAPE '\\')")
            like = f"%{_escape_like(q.strip())}%"
            params.extend([like, like, like])
        preload_pages = 3
        limit = page_size * (1 + preload_pages)
        offset = (page - 1) * page_size
        where_clause = ' AND '.join(where)
        with _connect(self.db_path) as connection:
            count_row = connection.execute(
                f"SELECT COUNT(*) FROM {_validate_table('chapters')} AS c JOIN {_validate_table('books')} AS b ON b.id = c.book_id WHERE {where_clause}",
                params,
            ).fetchone()
            total = count_row[0] if count_row else 0
            rows = connection.execute(
                f"""
                SELECT c.*, LENGTH(c.content) AS word_count, b.title AS book_title
                FROM chapters AS c
                JOIN books AS b ON b.id = c.book_id
                WHERE {where_clause}
                ORDER BY c.updated_at DESC, c.id DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
        return {"items": [_chapter_list_row(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    def admin_get_chapter(self, chapter_id: int) -> dict[str, Any] | None:
        with _connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT c.*, LENGTH(c.content) AS word_count, b.title AS book_title
                FROM chapters AS c
                JOIN books AS b ON b.id = c.book_id
                WHERE c.id = ?
                """,
                (int(chapter_id),),
            ).fetchone()
        return _chapter_list_row(row) if row else None

    def admin_update_chapter(self, admin_user_id: int, chapter_id: int, payload: AdminChapterUpdatePayload) -> dict[str, Any] | None:
        mapping = payload.model_dump(exclude_none=True)
        allowed = [
            "title",
            "volume_title",
            "outline",
            "summary_text",
            "content",
            "sort_order",
            "status",
            "published_at",
            "ai_probability",
            "ai_probability_level",
        ]
        _validate_columns(allowed)
        updates = [f"{key} = ?" for key in allowed if key in mapping]
        params = [mapping[key] for key in allowed if key in mapping]
        if not updates:
            return self.admin_get_chapter(chapter_id)
        _validate_column("updated_at")
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(int(chapter_id))
        with _connect(self.db_path) as connection:
            cursor = connection.execute(f"UPDATE {_validate_table('chapters')} SET {', '.join(updates)} WHERE id = ?", params)
            if cursor.rowcount <= 0:
                return None
            book_id = connection.execute("SELECT book_id FROM chapters WHERE id = ?", (int(chapter_id),)).fetchone()
            if book_id:
                connection.execute("UPDATE books SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (int(book_id["book_id"]),))
                self._rebuild_book_fulltext(connection, int(book_id["book_id"]))
            self._record_admin_audit(connection, admin_user_id, "update", "chapter", chapter_id, mapping)
            connection.commit()
        return self.admin_get_chapter(chapter_id)

    def admin_soft_delete_chapter(self, admin_user_id: int, chapter_id: int) -> dict | None:
        with _connect(self.db_path) as connection:
            # 检查章节字数，字数为0时直接硬删除
            chapter_row = connection.execute(
                "SELECT book_id, content FROM chapters WHERE id = ?", (int(chapter_id),)
            ).fetchone()
            if not chapter_row:
                return None
            word_count = len(str(chapter_row["content"] or ""))
            if word_count == 0:
                cursor = connection.execute("DELETE FROM chapters WHERE id = ?", (int(chapter_id),))
                if cursor.rowcount <= 0:
                    return None
                self._record_admin_audit(connection, admin_user_id, "hard_delete", "chapter", chapter_id,
                                        {"reason": "word_count_zero"})
                self._rebuild_book_fulltext(connection, int(chapter_row["book_id"]))
                connection.commit()
                return {"hard_deleted": True}
            cursor = connection.execute(
                "UPDATE chapters SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP), deleted_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(admin_user_id), int(chapter_id)),
            )
            if cursor.rowcount <= 0:
                return None
            self._record_admin_audit(connection, admin_user_id, "delete", "chapter", chapter_id)
            self._rebuild_book_fulltext(connection, int(chapter_row["book_id"]))
            connection.commit()
        return {"hard_deleted": False}

    def admin_restore_chapter(self, admin_user_id: int, chapter_id: int) -> bool:
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                "UPDATE chapters SET deleted_at = NULL, deleted_by = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(chapter_id),),
            )
            if cursor.rowcount <= 0:
                return False
            book_id = connection.execute("SELECT book_id FROM chapters WHERE id = ?", (int(chapter_id),)).fetchone()
            if book_id:
                self._rebuild_book_fulltext(connection, int(book_id["book_id"]))
            self._record_admin_audit(connection, admin_user_id, "restore", "chapter", chapter_id)
            connection.commit()
        return True

    def admin_list_bookshelf_shelves(self, include_deleted: bool = True, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        preload_pages = 3
        limit = page_size * (1 + preload_pages)
        offset = (page - 1) * page_size
        where_clause = "" if include_deleted else "WHERE s.deleted_at IS NULL"
        with _connect(self.db_path) as connection:
            count_row = connection.execute(
                f"SELECT COUNT(*) FROM {_validate_table('bookshelf_shelves')} AS s {where_clause}"
            ).fetchone()
            total = count_row[0] if count_row else 0
            rows = connection.execute(
                f"""
                SELECT s.*, u.username, COUNT(i.id) AS book_count
                FROM bookshelf_shelves AS s
                JOIN users AS u ON u.id = s.user_id
                LEFT JOIN bookshelf_items AS i ON i.shelf_id = s.id AND i.deleted_at IS NULL
                {where_clause}
                GROUP BY s.id
                ORDER BY s.updated_at DESC, s.id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return {"items": [_bookshelf_shelf_row(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    def admin_list_bookshelf_items(self, include_deleted: bool = True, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        preload_pages = 3
        limit = page_size * (1 + preload_pages)
        offset = (page - 1) * page_size
        where_clause = "" if include_deleted else "WHERE bi.deleted_at IS NULL"
        with _connect(self.db_path) as connection:
            count_row = connection.execute(
                f"SELECT COUNT(*) FROM {_validate_table('bookshelf_items')} AS bi {where_clause}"
            ).fetchone()
            total = count_row[0] if count_row else 0
            rows = connection.execute(
                f"""
                SELECT bi.*, u.username, s.name AS shelf_name, b.title AS book_title, c.title AS last_chapter_title
                FROM bookshelf_items AS bi
                JOIN users AS u ON u.id = bi.user_id
                LEFT JOIN bookshelf_shelves AS s ON s.id = bi.shelf_id
                JOIN books AS b ON b.id = bi.book_id
                LEFT JOIN chapters AS c ON c.id = bi.last_chapter_id
                {where_clause}
                ORDER BY bi.updated_at DESC, bi.id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    def admin_soft_delete_shelf(self, admin_user_id: int, shelf_id: int) -> bool:
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                "UPDATE bookshelf_shelves SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP), deleted_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(admin_user_id), int(shelf_id)),
            )
            if cursor.rowcount <= 0:
                return False
            self._record_admin_audit(connection, admin_user_id, "delete", "bookshelf_shelf", shelf_id)
            connection.commit()
        return True

    def admin_restore_shelf(self, admin_user_id: int, shelf_id: int) -> bool:
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                "UPDATE bookshelf_shelves SET deleted_at = NULL, deleted_by = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(shelf_id),),
            )
            if cursor.rowcount <= 0:
                return False
            self._record_admin_audit(connection, admin_user_id, "restore", "bookshelf_shelf", shelf_id)
            connection.commit()
        return True

    def admin_soft_delete_shelf_item(self, admin_user_id: int, item_id: int) -> bool:
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                "UPDATE bookshelf_items SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP), deleted_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(admin_user_id), int(item_id)),
            )
            if cursor.rowcount <= 0:
                return False
            self._record_admin_audit(connection, admin_user_id, "delete", "bookshelf_item", item_id)
            connection.commit()
        return True

    def admin_restore_shelf_item(self, admin_user_id: int, item_id: int) -> bool:
        with _connect(self.db_path) as connection:
            cursor = connection.execute(
                "UPDATE bookshelf_items SET deleted_at = NULL, deleted_by = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(item_id),),
            )
            if cursor.rowcount <= 0:
                return False
            self._record_admin_audit(connection, admin_user_id, "restore", "bookshelf_item", item_id)
            connection.commit()
        return True

    def admin_list_tokens(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        preload_pages = 3
        limit = page_size * (1 + preload_pages)
        offset = (page - 1) * page_size
        with _connect(self.db_path) as connection:
            self._settle_expired_sessions(connection)
            total = connection.execute("SELECT COUNT(*) FROM auth_tokens").fetchone()[0]
            rows = connection.execute(
                """
                SELECT t.*, u.username
                FROM auth_tokens AS t
                JOIN users AS u ON u.id = t.user_id
                ORDER BY t.expires_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            items = [self._admin_token_row(row) for row in rows]
            connection.commit()
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def admin_revoke_token(self, admin_user_id: int, token: str) -> bool:
        token_or_hash = str(token or "")
        with _connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT token_hash
                FROM auth_tokens
                WHERE revoked_at IS NULL AND (token = ? OR token_hash = ?)
                """,
                (token_or_hash, token_or_hash),
            ).fetchall()
            cursor = connection.execute(
                """
                UPDATE auth_tokens
                SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)
                WHERE revoked_at IS NULL AND (token = ? OR token_hash = ?)
                """,
                (token_or_hash, token_or_hash),
            )
            if cursor.rowcount <= 0:
                return False
            for row in rows:
                self._settle_online_session(connection, token_hash=str(row["token_hash"] or ""), status="revoked")
            self._record_admin_audit(
                connection,
                admin_user_id,
                "revoke",
                "auth_token",
                token_or_hash if len(token_or_hash) == 64 else _token_hash(token_or_hash),
            )
            connection.commit()
        return True

    def admin_list_quotas(
        self,
        q: str = "",
        tier: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        params: list[Any] = []
        where = ["1 = 1"]
        if q.strip():
            where.append("u.username LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(q.strip())}%")
        if tier.strip():
            where.append("? = 'free'")
            params.append(tier.strip())
        where_clause = " AND ".join(where)
        preload_pages = 3
        limit = page_size * (1 + preload_pages)
        offset = (page - 1) * page_size
        with _connect(self.db_path) as connection:
            self._settle_expired_sessions(connection)
            total = connection.execute(f"SELECT COUNT(*) FROM {_validate_table('users')} AS u WHERE {where_clause}", params).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT
                    u.id AS user_id,
                    u.id AS id,
                    u.username,
                    u.status,
                    u.created_at,
                    u.updated_at,
                    'free' AS tier,
                    104857600 AS sync_storage_limit_bytes,
                    50 AS ai_calls_limit,
                    3 AS book_limit,
                    2 AS device_limit,
                    NULL AS expires_at
                FROM users AS u
                WHERE {where_clause}
                ORDER BY u.id DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            ).fetchall()
            user_ids = [int(row["user_id"]) for row in rows]
            usage = self._usage_summary_for_users(connection, user_ids)
            items: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                summary = usage.get(int(row["user_id"]), {})
                item.update(summary)
                item["sync_storage_used_bytes"] = int(summary.get("fulltext_char_count") or 0)
                item["ai_calls_used"] = int(summary.get("analysis_count") or 0)
                items.append(item)
            connection.commit()
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def admin_list_devices(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        preload_pages = 3
        limit = page_size * (1 + preload_pages)
        offset = (page - 1) * page_size
        with _connect(self.db_path) as connection:
            total = connection.execute("SELECT COUNT(*) FROM trusted_devices").fetchone()[0]
            rows = connection.execute(
                """
                SELECT d.*, u.username
                FROM trusted_devices AS d
                JOIN users AS u ON u.id = d.user_id
                ORDER BY d.updated_at DESC, d.id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}

    def admin_revoke_device(self, admin_user_id: int, device_id: int) -> bool:
        with _connect(self.db_path) as connection:
            cursor = connection.execute("DELETE FROM trusted_devices WHERE id = ?", (int(device_id),))
            if cursor.rowcount <= 0:
                return False
            self._record_admin_audit(connection, admin_user_id, "revoke", "trusted_device", device_id)
            connection.commit()
        return True

    def admin_list_audit_logs(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        preload_pages = 3
        limit = page_size * (1 + preload_pages)
        offset = (page - 1) * page_size
        with _connect(self.db_path) as connection:
            total = connection.execute("SELECT COUNT(*) FROM admin_audit_logs").fetchone()[0]
            rows = connection.execute(
                """
                SELECT l.*, COALESCE(au.username, u.username, '') AS admin_username
                FROM admin_audit_logs AS l
                LEFT JOIN admin_users AS au ON au.id = l.admin_user_id
                LEFT JOIN users AS u ON u.id = l.admin_user_id
                ORDER BY l.created_at DESC, l.id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}
