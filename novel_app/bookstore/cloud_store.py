from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Any

from .models import (
    DEFAULT_DB_PATH,
    _connect,
)

_VALID_CLOUD_TABLES = frozenset({
    "cloud_books", "cloud_volumes", "cloud_chapters",
    "cloud_characters", "cloud_character_relationships",
    "cloud_world_entries", "cloud_analysis_runs", "cloud_analysis_cards",
    "cloud_review_runs", "cloud_review_findings",
    "cloud_chapter_events", "cloud_chapter_tags", "cloud_book_metas",
})

def _validate_cloud_table(table_name: str) -> str:
    """校验动态表名是否在白名单中，防止 SQL 注入。"""
    if table_name not in _VALID_CLOUD_TABLES:
        raise ValueError(f"Invalid cloud table name: {table_name}")
    return table_name


class CloudBookStore:
    """云端书籍数据存储，与 BookstoreStore 共享同一数据库连接。"""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self._transaction_conn: sqlite3.Connection | None = None

    # ──────────────────── 事务控制 ────────────────────

    def begin_transaction(self) -> None:
        """开始显式事务。调用后所有写入操作共享同一连接，直到 commit/rollback。"""
        if self._transaction_conn is not None:
            raise RuntimeError("事务已在进行中")
        self._transaction_conn = _connect(self.db_path)
        self._transaction_conn.execute("BEGIN IMMEDIATE")

    def commit_transaction(self) -> None:
        """提交当前事务并释放连接。"""
        if self._transaction_conn is None:
            raise RuntimeError("没有进行中的事务")
        try:
            self._transaction_conn.execute("COMMIT")
        finally:
            self._transaction_conn.close()
            self._transaction_conn = None

    def rollback_transaction(self) -> None:
        """回滚当前事务并释放连接。"""
        if self._transaction_conn is None:
            raise RuntimeError("没有进行中的事务")
        try:
            self._transaction_conn.execute("ROLLBACK")
        finally:
            self._transaction_conn.close()
            self._transaction_conn = None

    def delete_cloud_book_relations(self, cloud_book_id: int) -> None:
        """删除云端书籍的所有关联数据（保留 cloud_books 记录本身）。

        可在事务中调用，也可独立调用。
        """
        if self._transaction_conn is not None:
            conn = self._transaction_conn
            own_conn = False
        else:
            conn = _connect(self.db_path)
            own_conn = True
        try:
            for table in (
                "cloud_chapter_tags",
                "cloud_chapter_events",
                "cloud_review_findings",
                "cloud_review_runs",
                "cloud_analysis_cards",
                "cloud_analysis_runs",
                "cloud_character_relationships",
                "cloud_characters",
                "cloud_world_entries",
                "cloud_chapters",
                "cloud_volumes",
            ):
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.execute(
                        f"DELETE FROM {_validate_cloud_table(table)} WHERE cloud_book_id = ?",
                        (cloud_book_id,),
                    )
            # review_findings 通过 cloud_run_id 关联
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute(
                    "DELETE FROM cloud_review_findings WHERE cloud_run_id IN "
                    "(SELECT id FROM cloud_review_runs WHERE cloud_book_id = ?)",
                    (cloud_book_id,),
                )
            if own_conn:
                conn.commit()
        finally:
            if own_conn:
                conn.close()

    # ──────────────────── 书籍 CRUD ────────────────────

    def create_cloud_book(
        self,
        user_id: int,
        title: str,
        outline_text: str = "",
        outline_data_json: str = "",
        world_text: str = "",
        world_data_json: str = "",
        cover_image_path: str = "",
        local_book_id: int | None = None,
        source_type: str = "user_upload",
    ) -> int:
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(
                """
                INSERT INTO cloud_books
                    (user_id, title, outline_text, outline_data_json, world_text,
                     world_data_json, cover_image_path, local_book_id, source_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, title, outline_text, outline_data_json, world_text,
                 world_data_json, cover_image_path, local_book_id, source_type),
            )
            return int(cursor.lastrowid)
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO cloud_books
                    (user_id, title, outline_text, outline_data_json, world_text,
                     world_data_json, cover_image_path, local_book_id, source_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, title, outline_text, outline_data_json, world_text,
                 world_data_json, cover_image_path, local_book_id, source_type),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def get_cloud_book(self, user_id: int, cloud_book_id: int) -> dict[str, Any] | None:
        with _connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM cloud_books WHERE id = ? AND user_id = ?",
                (cloud_book_id, user_id),
            ).fetchone()
            if not row:
                return None
            return dict(row)

    def list_cloud_books(self, user_id: int) -> list[dict[str, Any]]:
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM cloud_books WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_cloud_books_by_ids(self, user_id: int, cloud_book_ids: list[int]) -> list[dict[str, Any]]:
        """批量获取指定 ID 的云端书籍。"""
        if not cloud_book_ids:
            return []
        placeholders = ",".join("?" * len(cloud_book_ids))
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM cloud_books WHERE user_id = ? AND id IN ({placeholders})",
                [user_id, *cloud_book_ids],
            ).fetchall()
        return [dict(r) for r in rows]

    def update_cloud_book(self, user_id: int, cloud_book_id: int, **fields: Any) -> bool:
        if not fields:
            return False
        allowed = {
            "title", "outline_text", "outline_data_json", "world_text",
            "world_data_json", "cover_image_path", "local_book_id",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        updates["updated_at"] = "CURRENT_TIMESTAMP"
        set_clause = ", ".join(f"{k} = ?" if k != "updated_at" else f"{k} = CURRENT_TIMESTAMP" for k in updates)
        values = [v for k, v in updates.items() if k != "updated_at"]
        values.extend([cloud_book_id, user_id])
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(
                f"UPDATE cloud_books SET {set_clause} WHERE id = ? AND user_id = ?",
                values,
            )
            return cursor.rowcount > 0
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                f"UPDATE cloud_books SET {set_clause} WHERE id = ? AND user_id = ?",
                values,
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_cloud_book(self, user_id: int, cloud_book_id: int) -> bool:
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(
                "DELETE FROM cloud_books WHERE id = ? AND user_id = ?",
                (cloud_book_id, user_id),
            )
            return cursor.rowcount > 0
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM cloud_books WHERE id = ? AND user_id = ?",
                (cloud_book_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    # ──────────────────── 分卷 CRUD ────────────────────

    def create_cloud_volume(
        self,
        cloud_book_id: int,
        title: str,
        outline_text: str = "",
        sort_order: int = 0,
        local_volume_id: int | None = None,
    ) -> int:
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(
                """
                INSERT INTO cloud_volumes
                    (cloud_book_id, title, outline_text, sort_order, local_volume_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cloud_book_id, title, outline_text, sort_order, local_volume_id),
            )
            return int(cursor.lastrowid)
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO cloud_volumes
                    (cloud_book_id, title, outline_text, sort_order, local_volume_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cloud_book_id, title, outline_text, sort_order, local_volume_id),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_cloud_volume(self, cloud_volume_id: int, user_id: int = 0, **fields: Any) -> bool:
        if not fields:
            return False
        allowed = {"title", "outline_text", "sort_order", "local_volume_id"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        updates["updated_at"] = "CURRENT_TIMESTAMP"
        set_clause = ", ".join(f"{k} = ?" if k != "updated_at" else f"{k} = CURRENT_TIMESTAMP" for k in updates)
        values = [v for k, v in updates.items() if k != "updated_at"]
        values.append(cloud_volume_id)
        if user_id:
            sql = f"UPDATE cloud_volumes SET {set_clause} WHERE id = ? AND cloud_book_id IN (SELECT id FROM cloud_books WHERE user_id = ?)"
            values.append(user_id)
        else:
            sql = f"UPDATE cloud_volumes SET {set_clause} WHERE id = ?"
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(sql, values)
            return cursor.rowcount > 0
        with _connect(self.db_path) as conn:
            cursor = conn.execute(sql, values)
            conn.commit()
            return cursor.rowcount > 0

    def delete_cloud_volume(self, cloud_volume_id: int, user_id: int = 0) -> bool:
        if user_id:
            sql = "DELETE FROM cloud_volumes WHERE id = ? AND cloud_book_id IN (SELECT id FROM cloud_books WHERE user_id = ?)"
            params = (cloud_volume_id, user_id)
        else:
            sql = "DELETE FROM cloud_volumes WHERE id = ?"
            params = (cloud_volume_id,)
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(sql, params)
            return cursor.rowcount > 0
        with _connect(self.db_path) as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.rowcount > 0

    # ──────────────────── 章节 CRUD ────────────────────

    def create_cloud_chapter(
        self,
        cloud_book_id: int,
        title: str,
        outline: str = "",
        content: str = "",
        summary_text: str = "",
        chapter_type: str = "正文",
        sort_order: int = 0,
        ai_probability: int = 0,
        ai_probability_level: str = "none",
        cloud_volume_id: int | None = None,
        local_chapter_id: int | None = None,
    ) -> int:
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(
                """
                INSERT INTO cloud_chapters
                    (cloud_book_id, cloud_volume_id, title, outline, content,
                     summary_text, chapter_type, sort_order, ai_probability,
                     ai_probability_level, local_chapter_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cloud_book_id, cloud_volume_id, title, outline, content,
                 summary_text, chapter_type, sort_order, ai_probability,
                 ai_probability_level, local_chapter_id),
            )
            return int(cursor.lastrowid)
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO cloud_chapters
                    (cloud_book_id, cloud_volume_id, title, outline, content,
                     summary_text, chapter_type, sort_order, ai_probability,
                     ai_probability_level, local_chapter_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cloud_book_id, cloud_volume_id, title, outline, content,
                 summary_text, chapter_type, sort_order, ai_probability,
                 ai_probability_level, local_chapter_id),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_cloud_chapter(self, cloud_chapter_id: int, user_id: int = 0, **fields: Any) -> bool:
        if not fields:
            return False
        allowed = {
            "cloud_volume_id", "title", "outline", "content", "summary_text",
            "chapter_type", "sort_order", "ai_probability", "ai_probability_level",
            "local_chapter_id",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        updates["updated_at"] = "CURRENT_TIMESTAMP"
        set_clause = ", ".join(f"{k} = ?" if k != "updated_at" else f"{k} = CURRENT_TIMESTAMP" for k in updates)
        values = [v for k, v in updates.items() if k != "updated_at"]
        values.append(cloud_chapter_id)
        if user_id:
            sql = f"UPDATE cloud_chapters SET {set_clause} WHERE id = ? AND cloud_book_id IN (SELECT id FROM cloud_books WHERE user_id = ?)"
            values.append(user_id)
        else:
            sql = f"UPDATE cloud_chapters SET {set_clause} WHERE id = ?"
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(sql, values)
            return cursor.rowcount > 0
        with _connect(self.db_path) as conn:
            cursor = conn.execute(sql, values)
            conn.commit()
            return cursor.rowcount > 0

    def delete_cloud_chapter(self, cloud_chapter_id: int, user_id: int = 0) -> bool:
        if user_id:
            sql = "DELETE FROM cloud_chapters WHERE id = ? AND cloud_book_id IN (SELECT id FROM cloud_books WHERE user_id = ?)"
            params = (cloud_chapter_id, user_id)
        else:
            sql = "DELETE FROM cloud_chapters WHERE id = ?"
            params = (cloud_chapter_id,)
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(sql, params)
            return cursor.rowcount > 0
        with _connect(self.db_path) as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.rowcount > 0

    # ──────────────────── 人物卡 CRUD ────────────────────

    def create_cloud_character(
        self,
        cloud_book_id: int,
        name: str,
        role: str = "",
        profile_text: str = "",
        profile_data_json: str = "",
        image_path: str = "",
        graph_x: float = 0,
        graph_y: float = 0,
        local_character_id: int | None = None,
    ) -> int:
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(
                """
                INSERT INTO cloud_characters
                    (cloud_book_id, name, role, profile_text, profile_data_json,
                     image_path, graph_x, graph_y, local_character_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cloud_book_id, name, role, profile_text, profile_data_json,
                 image_path, graph_x, graph_y, local_character_id),
            )
            return int(cursor.lastrowid)
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO cloud_characters
                    (cloud_book_id, name, role, profile_text, profile_data_json,
                     image_path, graph_x, graph_y, local_character_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cloud_book_id, name, role, profile_text, profile_data_json,
                 image_path, graph_x, graph_y, local_character_id),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_cloud_character(self, cloud_character_id: int, user_id: int = 0, **fields: Any) -> bool:
        if not fields:
            return False
        allowed = {
            "name", "role", "profile_text", "profile_data_json",
            "image_path", "graph_x", "graph_y", "local_character_id",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        updates["updated_at"] = "CURRENT_TIMESTAMP"
        set_clause = ", ".join(f"{k} = ?" if k != "updated_at" else f"{k} = CURRENT_TIMESTAMP" for k in updates)
        values = [v for k, v in updates.items() if k != "updated_at"]
        values.append(cloud_character_id)
        if user_id:
            sql = f"UPDATE cloud_characters SET {set_clause} WHERE id = ? AND cloud_book_id IN (SELECT id FROM cloud_books WHERE user_id = ?)"
            values.append(user_id)
        else:
            sql = f"UPDATE cloud_characters SET {set_clause} WHERE id = ?"
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(sql, values)
            return cursor.rowcount > 0
        with _connect(self.db_path) as conn:
            cursor = conn.execute(sql, values)
            conn.commit()
            return cursor.rowcount > 0

    def delete_cloud_character(self, cloud_character_id: int, user_id: int = 0) -> bool:
        if user_id:
            sql = "DELETE FROM cloud_characters WHERE id = ? AND cloud_book_id IN (SELECT id FROM cloud_books WHERE user_id = ?)"
            params = (cloud_character_id, user_id)
        else:
            sql = "DELETE FROM cloud_characters WHERE id = ?"
            params = (cloud_character_id,)
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(sql, params)
            return cursor.rowcount > 0
        with _connect(self.db_path) as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.rowcount > 0

    # ──────────────────── 人物关系 CRUD ────────────────────

    def create_cloud_relationship(
        self,
        cloud_book_id: int,
        source_character_id: int,
        target_character_id: int,
        relationship_type: str = "",
        description: str = "",
    ) -> int:
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(
                """
                INSERT INTO cloud_character_relationships
                    (cloud_book_id, source_character_id, target_character_id,
                     relationship_type, description)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cloud_book_id, source_character_id, target_character_id,
                 relationship_type, description),
            )
            return int(cursor.lastrowid)
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO cloud_character_relationships
                    (cloud_book_id, source_character_id, target_character_id,
                     relationship_type, description)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cloud_book_id, source_character_id, target_character_id,
                 relationship_type, description),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def delete_cloud_relationship(self, cloud_relationship_id: int, user_id: int = 0) -> bool:
        if user_id:
            sql = "DELETE FROM cloud_character_relationships WHERE id = ? AND cloud_book_id IN (SELECT id FROM cloud_books WHERE user_id = ?)"
            params = (cloud_relationship_id, user_id)
        else:
            sql = "DELETE FROM cloud_character_relationships WHERE id = ?"
            params = (cloud_relationship_id,)
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(sql, params)
            return cursor.rowcount > 0
        with _connect(self.db_path) as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.rowcount > 0

    # ──────────────────── 世界观 CRUD ────────────────────

    def create_cloud_world_entry(
        self,
        cloud_book_id: int,
        name: str,
        category: str = "设定",
        content_text: str = "",
        local_world_entry_id: int | None = None,
    ) -> int:
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(
                """
                INSERT INTO cloud_world_entries
                    (cloud_book_id, name, category, content_text, local_world_entry_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cloud_book_id, name, category, content_text, local_world_entry_id),
            )
            return int(cursor.lastrowid)
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO cloud_world_entries
                    (cloud_book_id, name, category, content_text, local_world_entry_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cloud_book_id, name, category, content_text, local_world_entry_id),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update_cloud_world_entry(self, cloud_world_entry_id: int, user_id: int = 0, **fields: Any) -> bool:
        if not fields:
            return False
        allowed = {"name", "category", "content_text", "local_world_entry_id"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        updates["updated_at"] = "CURRENT_TIMESTAMP"
        set_clause = ", ".join(f"{k} = ?" if k != "updated_at" else f"{k} = CURRENT_TIMESTAMP" for k in updates)
        values = [v for k, v in updates.items() if k != "updated_at"]
        values.append(cloud_world_entry_id)
        if user_id:
            sql = f"UPDATE cloud_world_entries SET {set_clause} WHERE id = ? AND cloud_book_id IN (SELECT id FROM cloud_books WHERE user_id = ?)"
            values.append(user_id)
        else:
            sql = f"UPDATE cloud_world_entries SET {set_clause} WHERE id = ?"
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(sql, values)
            return cursor.rowcount > 0
        with _connect(self.db_path) as conn:
            cursor = conn.execute(sql, values)
            conn.commit()
            return cursor.rowcount > 0

    def delete_cloud_world_entry(self, cloud_world_entry_id: int, user_id: int = 0) -> bool:
        if user_id:
            sql = "DELETE FROM cloud_world_entries WHERE id = ? AND cloud_book_id IN (SELECT id FROM cloud_books WHERE user_id = ?)"
            params = (cloud_world_entry_id, user_id)
        else:
            sql = "DELETE FROM cloud_world_entries WHERE id = ?"
            params = (cloud_world_entry_id,)
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(sql, params)
            return cursor.rowcount > 0
        with _connect(self.db_path) as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.rowcount > 0

    # ──────────────────── 分析数据 CRUD ────────────────────

    def create_cloud_analysis_run(
        self,
        cloud_book_id: int,
        scope_type: str = "book",
        status: str = "created",
        pipeline_version: str = "draft_mvp_v1",
        input_hash: str = "",
        summary: str = "",
        error_text: str = "",
        meta_json: str = "{}",
        local_run_id: int | None = None,
    ) -> int:
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(
                """
                INSERT INTO cloud_analysis_runs
                    (cloud_book_id, scope_type, status, pipeline_version,
                     input_hash, summary, error_text, meta_json, local_run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cloud_book_id, scope_type, status, pipeline_version,
                 input_hash, summary, error_text, meta_json, local_run_id),
            )
            return int(cursor.lastrowid)
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO cloud_analysis_runs
                    (cloud_book_id, scope_type, status, pipeline_version,
                     input_hash, summary, error_text, meta_json, local_run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cloud_book_id, scope_type, status, pipeline_version,
                 input_hash, summary, error_text, meta_json, local_run_id),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def create_cloud_analysis_card(
        self,
        cloud_book_id: int,
        cloud_run_id: int,
        card_uid: str,
        card_type: str,
        payload_json: str,
        entity_uid: str = "",
        card_version: int = 1,
        ars_score: float = 0.0,
        status: str = "draft",
        diff_json: str = "{}",
        applied_table: str = "",
        applied_id: int | None = None,
        applied_at: str | None = None,
        local_card_id: int | None = None,
    ) -> int:
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(
                """
                INSERT INTO cloud_analysis_cards
                    (cloud_book_id, cloud_run_id, card_uid, card_type, payload_json,
                     entity_uid, card_version, ars_score, status, diff_json,
                     applied_table, applied_id, applied_at, local_card_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cloud_book_id, cloud_run_id, card_uid, card_type, payload_json,
                 entity_uid, card_version, ars_score, status, diff_json,
                 applied_table, applied_id, applied_at, local_card_id),
            )
            return int(cursor.lastrowid)
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO cloud_analysis_cards
                    (cloud_book_id, cloud_run_id, card_uid, card_type, payload_json,
                     entity_uid, card_version, ars_score, status, diff_json,
                     applied_table, applied_id, applied_at, local_card_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cloud_book_id, cloud_run_id, card_uid, card_type, payload_json,
                 entity_uid, card_version, ars_score, status, diff_json,
                 applied_table, applied_id, applied_at, local_card_id),
            )
            conn.commit()
            return int(cursor.lastrowid)

    # ──────────────────── 审查数据 CRUD ────────────────────

    def create_cloud_review_run(
        self,
        cloud_book_id: int,
        cloud_chapter_id: int | None = None,
        scope_type: str = "chapter",
        status: str = "completed",
        truth_snapshot: str = "",
        summary: str = "",
        overall_score: int = 0,
        local_run_id: int | None = None,
    ) -> int:
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(
                """
                INSERT INTO cloud_review_runs
                    (cloud_book_id, cloud_chapter_id, scope_type, status,
                     truth_snapshot, summary, overall_score, local_run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cloud_book_id, cloud_chapter_id, scope_type, status,
                 truth_snapshot, summary, overall_score, local_run_id),
            )
            return int(cursor.lastrowid)
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO cloud_review_runs
                    (cloud_book_id, cloud_chapter_id, scope_type, status,
                     truth_snapshot, summary, overall_score, local_run_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cloud_book_id, cloud_chapter_id, scope_type, status,
                 truth_snapshot, summary, overall_score, local_run_id),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def create_cloud_review_finding(
        self,
        cloud_run_id: int,
        agent: str = "",
        severity: str = "low",
        category: str = "",
        location_hint: str = "",
        quote_text: str = "",
        issue_text: str = "",
        suggestion_text: str = "",
    ) -> int:
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(
                """
                INSERT INTO cloud_review_findings
                    (cloud_run_id, agent, severity, category, location_hint,
                     quote_text, issue_text, suggestion_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cloud_run_id, agent, severity, category, location_hint,
                 quote_text, issue_text, suggestion_text),
            )
            return int(cursor.lastrowid)
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO cloud_review_findings
                    (cloud_run_id, agent, severity, category, location_hint,
                     quote_text, issue_text, suggestion_text)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cloud_run_id, agent, severity, category, location_hint,
                 quote_text, issue_text, suggestion_text),
            )
            conn.commit()
            return int(cursor.lastrowid)

    # ──────────────────── 章节事件/标签 CRUD ────────────────────

    def create_cloud_chapter_event(
        self,
        cloud_book_id: int,
        cloud_chapter_id: int,
        label: str,
        description: str = "",
        sort_order: int = 0,
    ) -> int:
        if self._transaction_conn is not None:
            cursor = self._transaction_conn.execute(
                """
                INSERT INTO cloud_chapter_events
                    (cloud_book_id, cloud_chapter_id, label, description, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cloud_book_id, cloud_chapter_id, label, description, sort_order),
            )
            return int(cursor.lastrowid)
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO cloud_chapter_events
                    (cloud_book_id, cloud_chapter_id, label, description, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cloud_book_id, cloud_chapter_id, label, description, sort_order),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def add_cloud_chapter_tag(self, cloud_chapter_id: int, tag: str) -> bool:
        if self._transaction_conn is not None:
            try:
                self._transaction_conn.execute(
                    "INSERT INTO cloud_chapter_tags (cloud_chapter_id, tag) VALUES (?, ?)",
                    (cloud_chapter_id, tag),
                )
                return True
            except sqlite3.IntegrityError:
                return False
        with _connect(self.db_path) as conn:
            try:
                conn.execute(
                    "INSERT INTO cloud_chapter_tags (cloud_chapter_id, tag) VALUES (?, ?)",
                    (cloud_chapter_id, tag),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    # ──────────────────── 元数据 ────────────────────

    def upsert_cloud_book_meta(
        self,
        user_id: int,
        local_book_id: int,
        title: str,
        chapter_count: int = 0,
        word_count: int = 0,
        character_count: int = 0,
    ) -> int:
        if self._transaction_conn is not None:
            existing = self._transaction_conn.execute(
                "SELECT id FROM cloud_book_metas WHERE user_id = ? AND local_book_id = ?",
                (user_id, local_book_id),
            ).fetchone()
            if existing:
                self._transaction_conn.execute(
                    """
                    UPDATE cloud_book_metas
                    SET title = ?, chapter_count = ?, word_count = ?,
                        character_count = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND local_book_id = ?
                    """,
                    (title, chapter_count, word_count, character_count, user_id, local_book_id),
                )
                return int(existing["id"])
            else:
                cursor = self._transaction_conn.execute(
                    """
                    INSERT INTO cloud_book_metas
                        (user_id, local_book_id, title, chapter_count, word_count, character_count)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, local_book_id, title, chapter_count, word_count, character_count),
                )
                return int(cursor.lastrowid)
        with _connect(self.db_path) as conn:
            existing = conn.execute(
                "SELECT id FROM cloud_book_metas WHERE user_id = ? AND local_book_id = ?",
                (user_id, local_book_id),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE cloud_book_metas
                    SET title = ?, chapter_count = ?, word_count = ?,
                        character_count = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ? AND local_book_id = ?
                    """,
                    (title, chapter_count, word_count, character_count, user_id, local_book_id),
                )
                conn.commit()
                return int(existing["id"])
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO cloud_book_metas
                        (user_id, local_book_id, title, chapter_count, word_count, character_count)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, local_book_id, title, chapter_count, word_count, character_count),
                )
                conn.commit()
                return int(cursor.lastrowid)


def _compact_summary(text: str, limit: int = 160) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return "由灵枢桌面端发布的本地演示作品。"
    return cleaned[:limit]


def _normalize_book_tags(value: str) -> str:
    text = str(value or "").strip()
    for sep in ("，", "、", ";", "；", "\n", "\t"):
        text = text.replace(sep, ",")
    tags: list[str] = []
    seen: set[str] = set()
    for chunk in text.split(","):
        for tag in chunk.split():
            normalized = tag.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                tags.append(normalized)
    return ",".join(tags[:20])


def _book_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["chapter_count"] = int(item.get("chapter_count") or 0)
    item["word_count"] = int(item.get("word_count") or 0)
    return item


def _chapter_list_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["word_count"] = int(item.get("word_count") or 0)
    return item


def _bookshelf_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["chapter_count"] = int(item.get("chapter_count") or 0)
    item["word_count"] = int(item.get("word_count") or 0)
    item["last_chapter_index"] = int(item.get("last_chapter_index") or 0)
    if item["chapter_count"] > 0 and item["last_chapter_index"] > 0:
        item["progress_percent"] = min(100, round(item["last_chapter_index"] * 100 / item["chapter_count"]))
    else:
        item["progress_percent"] = 0
    return item


def _bookshelf_shelf_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["id"] = int(item.get("id") or 0)
    item["user_id"] = int(item.get("user_id") or 0)
    item["is_default"] = int(item.get("is_default") or 0)
    item["book_count"] = int(item.get("book_count") or 0)
    return item
