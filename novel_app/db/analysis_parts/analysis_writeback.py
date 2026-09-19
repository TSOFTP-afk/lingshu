from __future__ import annotations

from novel_app.db.analysis_parts.common import *


class AnalysisWritebackMixin:
    def create_analysis_apply_snapshot(
        self,
        book_id: int,
        run_id: int | None,
        label: str,
        snapshot: dict[str, Any],
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO analysis_apply_snapshots (book_id, run_id, label, snapshot_json)
            VALUES (?, ?, ?, ?)
            """,
            (book_id, run_id, label, self._json_payload(snapshot)),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def list_analysis_apply_snapshots(self, book_id: int, run_id: int | None = None) -> list[sqlite3.Row]:
        sql = """
            SELECT id, book_id, run_id, label, snapshot_json, created_at
            FROM analysis_apply_snapshots
            WHERE book_id = ?
        """
        params: list[Any] = [book_id]
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        sql += " ORDER BY id DESC"
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    @staticmethod
    def _analysis_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _analysis_block_chapter_ids(cls, value: Any) -> list[int]:
        if isinstance(value, (str, int)):
            value = [value]
        if not isinstance(value, list):
            return []
        chapter_ids: list[int] = []
        for item in value:
            try:
                chapter_id = int(item)
            except (TypeError, ValueError):
                continue
            if chapter_id not in chapter_ids:
                chapter_ids.append(chapter_id)
        return chapter_ids

    def create_analysis_audit_log(
        self,
        book_id: int,
        *,
        action: str,
        target_type: str,
        run_id: int | None = None,
        card_id: int | None = None,
        target_uid: str = "",
        old_value: Any = None,
        new_value: Any = None,
        reason: str = "",
        confidence: float = 0.0,
        actor: str = "system",
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO analysis_audit_logs (
                book_id, run_id, card_id, action, target_type, target_uid,
                old_value_json, new_value_json, reason, confidence, actor
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                run_id,
                card_id,
                action,
                target_type,
                target_uid,
                self._json_payload(old_value or {}),
                self._json_payload(new_value or {}),
                reason,
                float(confidence or 0.0),
                actor or "system",
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def list_analysis_audit_logs(self, book_id: int, run_id: int | None = None) -> list[sqlite3.Row]:
        sql = """
            SELECT *
            FROM analysis_audit_logs
            WHERE book_id = ?
        """
        params: list[Any] = [book_id]
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        sql += " ORDER BY id ASC"
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    # ==================================================================
    # 批量写入方法（hybrid-database-architecture spec Task 5）
    # ==================================================================
    # 设计原则：
    # - 接收 list 参数，循环 execute 但不每条 commit
    # - 循环结束后单次 commit（与 create_analysis_blocks 等已有批量方法一致）
    # - 保留原逐条方法不变，调用方可按场景选择
    # - 若调用方已用 database.transaction() 包裹，commit 会被自动抑制
    # ==================================================================

    def create_analysis_apply_snapshots_batch(
        self,
        snapshots: list[dict[str, Any]],
    ) -> list[int]:
        """批量创建写回快照。

        snapshots 每项需包含: book_id, run_id(int|None), label, snapshot(dict)。
        返回每条快照的 id 列表。
        """
        if not snapshots:
            return []
        snapshot_ids: list[int] = []
        for item in snapshots:
            cursor = self.connection.execute(
                """
                INSERT INTO analysis_apply_snapshots (book_id, run_id, label, snapshot_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    int(item["book_id"]),
                    item.get("run_id"),
                    str(item.get("label") or ""),
                    self._json_payload(item.get("snapshot") or {}),
                ),
            )
            snapshot_ids.append(int(cursor.lastrowid))
        self.connection.commit()
        return snapshot_ids

    def create_analysis_audit_logs_batch(
        self,
        book_id: int,
        entries: list[dict[str, Any]],
    ) -> list[int]:
        """批量创建审计日志。

        entries 每项需包含: action, target_type，可选 run_id/card_id/target_uid/
        old_value/new_value/reason/confidence/actor。返回每条日志的 id 列表。
        """
        if not entries:
            return []
        log_ids: list[int] = []
        for entry in entries:
            cursor = self.connection.execute(
                """
                INSERT INTO analysis_audit_logs (
                    book_id, run_id, card_id, action, target_type, target_uid,
                    old_value_json, new_value_json, reason, confidence, actor
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    entry.get("run_id"),
                    entry.get("card_id"),
                    str(entry.get("action") or ""),
                    str(entry.get("target_type") or ""),
                    str(entry.get("target_uid") or ""),
                    self._json_payload(entry.get("old_value") or {}),
                    self._json_payload(entry.get("new_value") or {}),
                    str(entry.get("reason") or ""),
                    float(entry.get("confidence") or 0.0),
                    str(entry.get("actor") or "system"),
                ),
            )
            log_ids.append(int(cursor.lastrowid))
        self.connection.commit()
        return log_ids
