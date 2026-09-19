from __future__ import annotations

from novel_app.db.analysis_parts.common import *


class AnalysisCardsMixin:
    def create_analysis_card(
        self,
        book_id: int,
        run_id: int,
        card_uid: str,
        card_type: str,
        payload: dict[str, Any],
        diff: dict[str, Any] | None = None,
        status: str = "draft",
        *,
        entity_uid: str = "",
        ars_score: float = 0.0,
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO analysis_cards (
                book_id, run_id, card_uid, card_type, entity_uid, ars_score, status, payload_json, diff_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                run_id,
                card_uid,
                card_type,
                entity_uid,
                float(ars_score or 0.0),
                status or "draft",
                self._json_payload(payload),
                self._json_payload(diff or {}),
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def create_analysis_card_if_absent(
        self,
        book_id: int,
        run_id: int,
        card_uid: str,
        card_type: str,
        payload: dict[str, Any],
        diff: dict[str, Any] | None = None,
        status: str = "draft",
        *,
        entity_uid: str = "",
        ars_score: float = 0.0,
    ) -> int:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO analysis_cards (
                book_id, run_id, card_uid, card_type, entity_uid, ars_score, status, payload_json, diff_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                run_id,
                card_uid,
                card_type,
                entity_uid,
                float(ars_score or 0.0),
                status or "draft",
                self._json_payload(payload),
                self._json_payload(diff or {}),
            ),
        )
        row = self.connection.execute(
            "SELECT id FROM analysis_cards WHERE run_id = ? AND card_uid = ?",
            (run_id, card_uid),
        ).fetchone()
        self.connection.commit()
        return int(row["id"]) if row else 0

    def mark_analysis_cards_superseded(
        self,
        book_id: int,
        run_id: int,
        *,
        card_type: str,
        entity_uid: str,
        keep_card_uid: str,
    ) -> None:
        self.connection.execute(
            """
            UPDATE analysis_cards
            SET status = 'superseded', updated_at = CURRENT_TIMESTAMP
            WHERE book_id = ?
              AND run_id = ?
              AND card_type = ?
              AND entity_uid = ?
              AND card_uid != ?
              AND status IN ('draft', 'blocked')
            """,
            (book_id, run_id, card_type, entity_uid, keep_card_uid),
        )
        self.connection.commit()

    def upsert_analysis_card_by_uid(
        self,
        book_id: int,
        run_id: int,
        card_uid: str,
        card_type: str,
        payload: dict[str, Any],
        diff: dict[str, Any] | None = None,
        status: str = "draft",
        *,
        entity_uid: str = "",
        ars_score: float = 0.0,
    ) -> int:
        """按 (run_id, card_uid) 幂等写入草稿：已存在则覆盖 payload，否则插入。"""
        self.connection.execute(
            "DELETE FROM analysis_cards WHERE run_id = ? AND card_uid = ?",
            (run_id, card_uid),
        )
        cursor = self.connection.execute(
            """
            INSERT INTO analysis_cards (
                book_id, run_id, card_uid, card_type, entity_uid, ars_score, status, payload_json, diff_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                run_id,
                card_uid,
                card_type,
                entity_uid,
                float(ars_score or 0.0),
                status or "draft",
                self._json_payload(payload),
                self._json_payload(diff or {}),
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def list_analysis_cards(self, run_id: int) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT *
            FROM analysis_cards
            WHERE run_id = ?
            ORDER BY
                CASE card_type
                    WHEN 'full_payload' THEN 0
                    WHEN 'book_summary' THEN 1
                    WHEN 'world' THEN 2
                    WHEN 'characters' THEN 3
                    WHEN 'chapters' THEN 4
                    WHEN 'unresolved' THEN 5
                    ELSE 9
                END,
                id ASC
            """,
            (run_id,),
        )
        return list(cursor.fetchall())

    def list_analysis_cards_by_chapter(
        self,
        book_id: int,
        chapter_id: int,
        *,
        card_type: str | None = None,
        limit: int = 500,
    ) -> list[sqlite3.Row]:
        """按 chapter_id 过滤 analysis_cards（chapter_id 存于 payload_json）。

        用于写作探针草稿按章节查询。
        """
        sql = """
            SELECT * FROM analysis_cards
            WHERE book_id = ?
              AND CAST(json_extract(payload_json, '$.chapter_id') AS INTEGER) = ?
        """
        params: list[Any] = [book_id, int(chapter_id)]
        if card_type:
            sql += " AND card_type = ?"
            params.append(card_type)
        sql += " ORDER BY id ASC LIMIT ?"
        params.append(max(1, int(limit)))
        return list(self.connection.execute(sql, params).fetchall())

    def replace_analysis_card_dependencies(
        self,
        book_id: int,
        run_id: int,
        card_uid: str,
        dependencies: list[dict[str, Any]],
    ) -> list[int]:
        self.connection.execute(
            "DELETE FROM analysis_card_dependencies WHERE book_id = ? AND run_id = ? AND card_uid = ?",
            (book_id, run_id, card_uid),
        )
        dependency_ids: list[int] = []
        for dependency in dependencies:
            dependency_uid = str(dependency.get("dependency_uid") or "").strip()
            if not dependency_uid:
                continue
            cursor = self.connection.execute(
                """
                INSERT INTO analysis_card_dependencies (
                    book_id, run_id, card_uid, dependency_type, dependency_uid, dependency_hash
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    run_id,
                    card_uid,
                    str(dependency.get("dependency_type") or ""),
                    dependency_uid,
                    str(dependency.get("dependency_hash") or ""),
                ),
            )
            dependency_ids.append(int(cursor.lastrowid))
        self.connection.commit()
        return dependency_ids

    def list_analysis_card_dependencies(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        card_uid: str | None = None,
        limit: int | None = 1000,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT *
            FROM analysis_card_dependencies
            WHERE book_id = ?
        """
        params: list[Any] = [book_id]
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        if card_uid:
            sql += " AND card_uid = ?"
            params.append(str(card_uid))
        sql += " ORDER BY id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def get_analysis_card(self, card_id: int) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            "SELECT * FROM analysis_cards WHERE id = ?",
            (card_id,),
        )
        return cursor.fetchone()

    def get_analysis_full_payload_card(self, run_id: int) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT *
            FROM analysis_cards
            WHERE run_id = ? AND card_type = 'full_payload'
            ORDER BY id ASC
            LIMIT 1
            """,
            (run_id,),
        )
        return cursor.fetchone()

    def mark_analysis_card_applied(
        self,
        card_id: int,
        applied_table: str = "",
        applied_id: int | None = None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE analysis_cards
            SET status = 'applied',
                applied_table = ?,
                applied_id = ?,
                applied_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (applied_table, applied_id, card_id),
        )
        self.connection.commit()

    def mark_analysis_card_rejected(self, card_id: int) -> None:
        self.connection.execute(
            """
            UPDATE analysis_cards
            SET status = 'rejected', updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status IN ('draft', 'blocked')
            """,
            (card_id,),
        )
        self.connection.commit()

    def update_analysis_card_diff(
        self,
        card_id: int,
        diff: dict[str, Any],
        *,
        status: str | None = None,
    ) -> None:
        if status is None:
            self.connection.execute(
                """
                UPDATE analysis_cards
                SET diff_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (self._json_payload(diff), card_id),
            )
        else:
            self.connection.execute(
                """
                UPDATE analysis_cards
                SET diff_json = ?, status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (self._json_payload(diff), status, card_id),
            )
        self.connection.commit()

    def create_analysis_cards_batch(
        self,
        book_id: int,
        run_id: int,
        drafts: list[dict[str, Any]],
    ) -> list[int]:
        """批量创建分析卡片。

        drafts 每项需包含: card_uid, card_type, payload(dict), diff(dict|None),
        status, entity_uid, ars_score。返回每张卡片的 id 列表（按输入顺序）。
        """
        if not drafts:
            return []
        card_ids: list[int] = []
        for draft in drafts:
            cursor = self.connection.execute(
                """
                INSERT INTO analysis_cards (
                    book_id, run_id, card_uid, card_type, entity_uid, ars_score,
                    status, payload_json, diff_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    run_id,
                    str(draft.get("card_uid") or ""),
                    str(draft.get("card_type") or ""),
                    str(draft.get("entity_uid") or ""),
                    float(draft.get("ars_score") or 0.0),
                    str(draft.get("status") or "draft"),
                    self._json_payload(draft.get("payload") or {}),
                    self._json_payload(draft.get("diff") or {}),
                ),
            )
            card_ids.append(int(cursor.lastrowid))
        self.connection.commit()
        return card_ids

    def mark_analysis_cards_applied_batch(
        self,
        updates: list[dict[str, Any]],
    ) -> int:
        """批量将卡片标记为已写回。

        updates 每项需包含: card_id, applied_table, applied_id。
        返回更新的行数。
        """
        if not updates:
            return 0
        affected = 0
        for item in updates:
            cursor = self.connection.execute(
                """
                UPDATE analysis_cards
                SET status = 'applied',
                    applied_table = ?,
                    applied_id = ?,
                    applied_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    str(item.get("applied_table") or ""),
                    item.get("applied_id"),
                    int(item["card_id"]),
                ),
            )
            affected += cursor.rowcount or 0
        self.connection.commit()
        return affected

    def update_analysis_card_payloads_batch(
        self,
        updates: list[dict[str, Any]],
    ) -> int:
        """批量更新卡片 payload_json。

        updates 每项需包含: book_id, run_id, card_uid, payload_json(str)。
        payload_json 由调用方负责 JSON 序列化（便于复用已有 payload dict）。
        """
        if not updates:
            return 0
        affected = 0
        for item in updates:
            cursor = self.connection.execute(
                """
                UPDATE analysis_cards
                SET payload_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE book_id = ? AND run_id = ? AND card_uid = ?
                """,
                (
                    str(item["payload_json"]),
                    int(item["book_id"]),
                    int(item["run_id"]),
                    str(item["card_uid"]),
                ),
            )
            affected += cursor.rowcount or 0
        self.connection.commit()
        return affected

