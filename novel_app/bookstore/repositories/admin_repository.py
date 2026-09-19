"""管理后台仓储 — 从 store.py 按域搬移（SQL 与行为不变）。

承接：admin_* 管理端 CRUD、管理员同步（sync_admin_users）与管理审计写入（_record_admin_audit）。
事务模式照搬原 store.py：``with _connect(self.db_path)`` + 显式 commit()。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..cloud_store import (
    _book_row,
    _bookshelf_shelf_row,
    _chapter_list_row,
    _normalize_book_tags,
)
from ..models import (
    AdminBookUpdatePayload,
    AdminChapterUpdatePayload,
    AdminUserUpdatePayload,
    _connect,
)
from ..security import (
    _escape_like,
    _masked_token,
    _online_seconds_expr,
    _token_hash,
)
from .auth_repository import _settle_expired_sessions, _settle_online_session
from .common import (
    _rebuild_book_fulltext,
    _validate_column,
    _validate_columns,
    _validate_table,
)
from .stats_repository import _usage_summary_for_user, _usage_summary_for_users


def _admin_user_row(row: sqlite3.Row | dict[str, Any], usage_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    item = dict(row)
    item.pop("password_hash", None)
    if usage_summary:
        item.update(usage_summary)
        item["usage_summary"] = dict(usage_summary)
    return item


def _admin_token_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    # 安全：token 列已不再存明文（历史明文行由 schema 迁移清空），
    # 预览从残留明文或 token_hash 前缀派生，均不泄露完整凭证
    token = str(item.pop("token", "") or "")
    token_hash = str(item.get("token_hash") or "")
    item["token_preview"] = _masked_token(token or token_hash)
    if not token_hash and token:
        item["token_hash"] = _token_hash(token)
    item["revoked"] = bool(item.get("revoked_at"))
    return item


def _record_admin_audit(
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


class AdminRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

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
            _settle_expired_sessions(connection)
            count_row = connection.execute(
                f"SELECT COUNT(*) FROM (SELECT u.id FROM {_validate_table('users')} AS u {where} GROUP BY u.id)",
                params,
            ).fetchone()
            total = count_row[0] if count_row else 0
            rows = connection.execute(
                f"""
                SELECT
                    u.*,
                    COUNT(DISTINCT CASE WHEN at.revoked_at IS NULL AND at.expires_at > datetime('now') THEN at.rowid END) AS token_count,
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
            usage = _usage_summary_for_users(connection, user_ids)
            items = [_admin_user_row(row, usage.get(int(row["id"]))) for row in rows]
            connection.commit()
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def admin_get_user(self, user_id: int) -> dict[str, Any] | None:
        with _connect(self.db_path) as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
            if not row:
                return None
            _settle_expired_sessions(connection)
            usage = _usage_summary_for_user(connection, int(user_id))
            result = _admin_user_row(row, usage)
            result["tokens"] = [
                _admin_token_row(item)
                for item in connection.execute(
                    """
                    SELECT rowid AS id, user_id, token_hash, created_at, revoked_at, expires_at
                    FROM auth_tokens WHERE user_id = ? ORDER BY expires_at DESC
                    """,
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
            _record_admin_audit(connection, admin_user_id, "update", "user", user_id, payload.model_dump(exclude_none=True))
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
                _settle_online_session(connection, token_hash=str(token_row["token_hash"] or ""), status="revoked")
            _record_admin_audit(connection, admin_user_id, "disable", "user", user_id)
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
            _record_admin_audit(connection, admin_user_id, "restore", "user", user_id)
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
            _record_admin_audit(connection, admin_user_id, "update", "book", book_id, mapping)
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
            _record_admin_audit(connection, admin_user_id, "delete", "book", book_id)
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
            _record_admin_audit(connection, admin_user_id, "restore", "book", book_id)
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
                _rebuild_book_fulltext(connection, int(book_id["book_id"]))
            _record_admin_audit(connection, admin_user_id, "update", "chapter", chapter_id, mapping)
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
                _record_admin_audit(connection, admin_user_id, "hard_delete", "chapter", chapter_id,
                                    {"reason": "word_count_zero"})
                _rebuild_book_fulltext(connection, int(chapter_row["book_id"]))
                connection.commit()
                return {"hard_deleted": True}
            cursor = connection.execute(
                "UPDATE chapters SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP), deleted_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (int(admin_user_id), int(chapter_id)),
            )
            if cursor.rowcount <= 0:
                return None
            _record_admin_audit(connection, admin_user_id, "delete", "chapter", chapter_id)
            _rebuild_book_fulltext(connection, int(chapter_row["book_id"]))
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
                _rebuild_book_fulltext(connection, int(book_id["book_id"]))
            _record_admin_audit(connection, admin_user_id, "restore", "chapter", chapter_id)
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
            _record_admin_audit(connection, admin_user_id, "delete", "bookshelf_shelf", shelf_id)
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
            _record_admin_audit(connection, admin_user_id, "restore", "bookshelf_shelf", shelf_id)
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
            _record_admin_audit(connection, admin_user_id, "delete", "bookshelf_item", item_id)
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
            _record_admin_audit(connection, admin_user_id, "restore", "bookshelf_item", item_id)
            connection.commit()
        return True

    def admin_list_tokens(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        preload_pages = 3
        limit = page_size * (1 + preload_pages)
        offset = (page - 1) * page_size
        with _connect(self.db_path) as connection:
            _settle_expired_sessions(connection)
            total = connection.execute("SELECT COUNT(*) FROM auth_tokens").fetchone()[0]
            rows = connection.execute(
                """
                SELECT t.rowid AS id, t.user_id, t.token_hash, t.created_at, t.revoked_at, t.expires_at, u.username
                FROM auth_tokens AS t
                JOIN users AS u ON u.id = t.user_id
                ORDER BY t.expires_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            items = [_admin_token_row(row) for row in rows]
            connection.commit()
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def admin_revoke_token(self, admin_user_id: int, token: str) -> bool:
        token_or_hash = str(token or "")
        # 安全：token 列已不存明文，统一按 token_hash 匹配。
        # 入参兼容明文 token（先哈希）与管理端直接传哈希两种情况
        token_hash = _token_hash(token_or_hash)
        with _connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT token_hash
                FROM auth_tokens
                WHERE revoked_at IS NULL AND token_hash IN (?, ?)
                """,
                (token_or_hash, token_hash),
            ).fetchall()
            cursor = connection.execute(
                """
                UPDATE auth_tokens
                SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)
                WHERE revoked_at IS NULL AND token_hash IN (?, ?)
                """,
                (token_or_hash, token_hash),
            )
            if cursor.rowcount <= 0:
                return False
            for row in rows:
                _settle_online_session(connection, token_hash=str(row["token_hash"] or ""), status="revoked")
            _record_admin_audit(
                connection,
                admin_user_id,
                "revoke",
                "auth_token",
                token_hash,
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
            _settle_expired_sessions(connection)
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
            usage = _usage_summary_for_users(connection, user_ids)
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
            _record_admin_audit(connection, admin_user_id, "revoke", "trusted_device", device_id)
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
