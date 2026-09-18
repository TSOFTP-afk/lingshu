from __future__ import annotations

from novel_app.db.common import *


class AnalysisMixin:
    def create_analysis_run(
        self,
        book_id: int,
        scope_type: str = "book",
        meta: dict[str, Any] | None = None,
        *,
        status: str = "created",
        pipeline_version: str = "draft_mvp_v1",
        input_hash: str = "",
        summary: str = "",
    ) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO analysis_runs (
                book_id, scope_type, status, pipeline_version, input_hash, summary, meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                scope_type or "book",
                status or "created",
                pipeline_version or "draft_mvp_v1",
                input_hash,
                summary,
                self._json_payload(meta or {}),
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def update_analysis_run_status(
        self,
        run_id: int,
        status: str,
        *,
        summary: str = "",
        error_text: str = "",
        meta: dict[str, Any] | None = None,
    ) -> None:
        existing = self.get_analysis_run(run_id)
        current_meta = self._json_object(str(existing["meta_json"] or "{}")) if existing else {}
        if meta:
            current_meta.update(meta)
        completed_statuses = {"awaiting_review", "failed", "cancelled", "applied"}
        self.connection.execute(
            """
            UPDATE analysis_runs
            SET status = ?,
                summary = CASE WHEN ? != '' THEN ? ELSE summary END,
                error_text = CASE WHEN ? != '' THEN ? ELSE error_text END,
                meta_json = ?,
                updated_at = CURRENT_TIMESTAMP,
                completed_at = CASE WHEN ? THEN COALESCE(completed_at, CURRENT_TIMESTAMP) ELSE completed_at END
            WHERE id = ?
            """,
            (
                status or "created",
                summary,
                summary,
                error_text,
                error_text,
                self._json_payload(current_meta),
                1 if status in completed_statuses else 0,
                run_id,
            ),
        )
        self.connection.commit()

    def get_analysis_run(self, run_id: int) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT
                r.*,
                (SELECT COUNT(*) FROM analysis_cards WHERE run_id = r.id) AS card_count,
                (SELECT COUNT(*) FROM analysis_cards WHERE run_id = r.id AND status = 'draft') AS draft_count,
                (SELECT COUNT(*) FROM analysis_cards WHERE run_id = r.id AND status = 'applied') AS applied_count,
                (SELECT COUNT(*) FROM analysis_cards WHERE run_id = r.id AND status = 'blocked') AS blocked_count
            FROM analysis_runs AS r
            WHERE r.id = ?
            """,
            (run_id,),
        )
        return cursor.fetchone()

    def list_analysis_runs(self, book_id: int, limit: int = 20) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT
                r.*,
                (SELECT COUNT(*) FROM analysis_cards WHERE run_id = r.id) AS card_count,
                (SELECT COUNT(*) FROM analysis_cards WHERE run_id = r.id AND status = 'draft') AS draft_count,
                (SELECT COUNT(*) FROM analysis_cards WHERE run_id = r.id AND status = 'applied') AS applied_count,
                (SELECT COUNT(*) FROM analysis_cards WHERE run_id = r.id AND status = 'blocked') AS blocked_count
            FROM analysis_runs AS r
            WHERE r.book_id = ?
            ORDER BY r.id DESC
            LIMIT ?
            """,
            (book_id, max(1, int(limit))),
        )
        return list(cursor.fetchall())

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

    def create_analysis_blocks(
        self,
        book_id: int,
        run_id: int,
        blocks: list[dict[str, Any]],
    ) -> list[int]:
        self.connection.execute(
            "DELETE FROM analysis_blocks WHERE book_id = ? AND run_id = ?",
            (book_id, run_id),
        )
        block_ids: list[int] = []
        for index, block in enumerate(blocks, start=1):
            text = str(block.get("text", "") or "")
            if not text.strip():
                continue
            chapter_ids = self._analysis_block_chapter_ids(block.get("chapter_ids"))
            chapter_refs = block.get("chapter_refs") if isinstance(block.get("chapter_refs"), list) else []
            chapter_id = chapter_ids[0] if chapter_ids else None
            summary = str(block.get("summary", "") or "").strip() or text.strip()[:500]
            metadata = block.get("metadata") if isinstance(block.get("metadata"), dict) else {}
            content_hash = str(block.get("content_hash") or "").strip() or hashlib.sha256(text.encode("utf-8")).hexdigest()
            structure_hash = str(block.get("structure_hash") or "").strip()
            pipeline_version = str(block.get("pipeline_version") or metadata.get("pipeline_version") or "").strip()
            cursor = self.connection.execute(
                """
                INSERT INTO analysis_blocks (
                    book_id, run_id, block_uid, chunk_id, chunk_index, chapter_id,
                    chapter_ids_json, chapter_refs_json, char_start, char_end,
                    text, summary, content_hash, structure_hash, pipeline_version, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    run_id,
                    str(block.get("block_uid") or block.get("chunk_id") or f"analysis-block-{index:04d}"),
                    str(block.get("chunk_id") or ""),
                    self._analysis_int(block.get("chunk_index"), index),
                    chapter_id,
                    self._json_payload(chapter_ids),
                    self._json_payload(chapter_refs),
                    self._analysis_int(block.get("char_start"), 0),
                    self._analysis_int(block.get("char_end"), len(text)),
                    text,
                    summary,
                    content_hash,
                    structure_hash,
                    pipeline_version,
                    self._json_payload(metadata),
                ),
            )
            block_ids.append(int(cursor.lastrowid))
        self.connection.commit()
        return block_ids

    def list_analysis_blocks(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        chapter_id: int | None = None,
        limit: int | None = 500,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT *
            FROM analysis_blocks
            WHERE book_id = ?
        """
        params: list[Any] = [book_id]
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        if chapter_id is not None:
            sql += " AND chapter_id = ?"
            params.append(chapter_id)
        sql += " ORDER BY run_id DESC, chunk_index ASC, id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def get_analysis_block(
        self,
        book_id: int,
        block_uid: str,
        *,
        run_id: int | None = None,
    ) -> sqlite3.Row | None:
        sql = """
            SELECT *
            FROM analysis_blocks
            WHERE book_id = ? AND block_uid = ?
        """
        params: list[Any] = [book_id, block_uid]
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        sql += " ORDER BY run_id DESC, id DESC LIMIT 1"
        return self.connection.execute(sql, params).fetchone()

    def find_reusable_run_for_input_hash(
        self,
        book_id: int,
        input_hash: str,
        *,
        exclude_run_id: int | None = None,
    ) -> sqlite3.Row | None:
        """查找具有相同 book_id + input_hash 且已产生 block 的历史 run，用于跨 run 复用 M1 分块结果。

        返回最近一个匹配的 run（id DESC），不含 block 的 run 会被过滤。
        """
        if not input_hash:
            return None
        sql = """
            SELECT r.*
            FROM analysis_runs AS r
            WHERE r.book_id = ? AND r.input_hash = ?
        """
        params: list[Any] = [book_id, input_hash]
        if exclude_run_id is not None:
            sql += " AND r.id != ?"
            params.append(exclude_run_id)
        sql += """
            AND EXISTS (SELECT 1 FROM analysis_blocks b WHERE b.run_id = r.id AND b.book_id = ?)
            ORDER BY r.id DESC
            LIMIT 1
        """
        params.append(book_id)
        return self.connection.execute(sql, params).fetchone()

    def clone_analysis_blocks(
        self,
        book_id: int,
        source_run_id: int,
        target_run_id: int,
    ) -> int:
        """从 source_run_id 克隆 analysis_blocks 到 target_run_id，返回克隆的行数。

        使用 INSERT...SELECT 复制全部 block 字段（id 自增，run_id 替换为目标）。
        克隆前会先删除 target_run_id 下已有的 block（防重复）。
        """
        self.connection.execute(
            "DELETE FROM analysis_blocks WHERE book_id = ? AND run_id = ?",
            (book_id, target_run_id),
        )
        cursor = self.connection.execute(
            """
            INSERT INTO analysis_blocks (
                book_id, run_id, block_uid, chunk_id, chunk_index, chapter_id,
                chapter_ids_json, chapter_refs_json, char_start, char_end,
                text, summary, content_hash, structure_hash, pipeline_version, metadata_json
            )
            SELECT
                book_id, ?, block_uid, chunk_id, chunk_index, chapter_id,
                chapter_ids_json, chapter_refs_json, char_start, char_end,
                text, summary, content_hash, structure_hash, pipeline_version, metadata_json
            FROM analysis_blocks
            WHERE book_id = ? AND run_id = ?
            ORDER BY chunk_index ASC, id ASC
            """,
            (target_run_id, book_id, source_run_id),
        )
        self.connection.commit()
        return int(cursor.rowcount)

    def delete_analysis_blocks_for_run(self, book_id: int, run_id: int) -> None:
        self.connection.execute(
            "DELETE FROM analysis_blocks WHERE book_id = ? AND run_id = ?",
            (book_id, run_id),
        )
        self.connection.commit()

    def delete_analysis_blocks_for_chapter(self, book_id: int, chapter_id: int) -> None:
        self.connection.execute(
            "DELETE FROM analysis_blocks WHERE book_id = ? AND chapter_id = ?",
            (book_id, chapter_id),
        )
        self.connection.commit()

    def mark_analysis_blocks_indexed(self, book_id: int, run_id: int, block_uids: list[str]) -> None:
        clean_uids = [str(item) for item in block_uids if str(item).strip()]
        if not clean_uids:
            return
        placeholders = ",".join("?" for _ in clean_uids)
        self.connection.execute(
            f"""
            UPDATE analysis_blocks
            SET indexed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE book_id = ? AND run_id = ? AND block_uid IN ({placeholders})
            """,
            [book_id, run_id, *clean_uids],
        )
        self.connection.commit()

    def replace_analysis_entity_mentions(
        self,
        book_id: int,
        run_id: int,
        mentions: list[dict[str, Any]],
    ) -> list[int]:
        self.connection.execute(
            "DELETE FROM analysis_entity_mentions WHERE book_id = ? AND run_id = ?",
            (book_id, run_id),
        )
        return self._insert_analysis_entity_mentions(book_id, run_id, mentions)

    def add_analysis_entity_mentions(
        self,
        book_id: int,
        run_id: int,
        mentions: list[dict[str, Any]],
    ) -> list[int]:
        """增量插入实体提及，不执行 DELETE。用于流式写入场景，逐批写入避免内存累积。"""
        return self._insert_analysis_entity_mentions(book_id, run_id, mentions)

    def _insert_analysis_entity_mentions(
        self,
        book_id: int,
        run_id: int,
        mentions: list[dict[str, Any]],
    ) -> list[int]:
        mention_ids: list[int] = []
        for mention in mentions:
            quote_text = str(mention.get("quote_text") or "").strip()
            normalized_text = str(mention.get("normalized_text") or "").strip()
            if not quote_text or not normalized_text:
                continue
            metadata = mention.get("metadata") if isinstance(mention.get("metadata"), dict) else {}
            cursor = self.connection.execute(
                """
                INSERT INTO analysis_entity_mentions (
                    book_id, run_id, mention_uid, entity_uid, entity_type,
                    normalized_text, quote_text, chapter_id, block_uid,
                    char_start, char_end, confidence, status, source_rule, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    run_id,
                    str(mention.get("mention_uid") or ""),
                    str(mention.get("entity_uid") or ""),
                    str(mention.get("entity_type") or "unknown"),
                    normalized_text,
                    quote_text,
                    self._analysis_int(mention.get("chapter_id"), 0) or None,
                    str(mention.get("block_uid") or ""),
                    self._analysis_int(mention.get("char_start"), 0),
                    self._analysis_int(mention.get("char_end"), 0),
                    float(mention.get("confidence") or 0.0),
                    str(mention.get("status") or "candidate"),
                    str(mention.get("source_rule") or ""),
                    self._json_payload(metadata),
                ),
            )
            mention_ids.append(int(cursor.lastrowid))
        self.connection.commit()
        return mention_ids

    def list_analysis_entity_mentions(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        chapter_id: int | None = None,
        limit: int | None = 1000,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT *
            FROM analysis_entity_mentions
            WHERE book_id = ?
        """
        params: list[Any] = [book_id]
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        if chapter_id is not None:
            sql += " AND chapter_id = ?"
            params.append(chapter_id)
        sql += " ORDER BY run_id DESC, chapter_id ASC, char_start ASC, id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def replace_analysis_entities(
        self,
        book_id: int,
        run_id: int,
        entities: list[dict[str, Any]],
    ) -> list[int]:
        self.connection.execute(
            "DELETE FROM analysis_entities WHERE book_id = ? AND run_id = ?",
            (book_id, run_id),
        )
        self.connection.execute(
            "DELETE FROM analysis_entity_aliases WHERE book_id = ? AND run_id = ?",
            (book_id, run_id),
        )
        self.connection.execute(
            "DELETE FROM analysis_entity_versions WHERE book_id = ? AND run_id = ?",
            (book_id, run_id),
        )
        self.connection.execute(
            "UPDATE analysis_entity_mentions SET entity_uid = '', updated_at = CURRENT_TIMESTAMP WHERE book_id = ? AND run_id = ?",
            (book_id, run_id),
        )
        entity_ids: list[int] = []
        for entity in entities:
            entity_uid = str(entity.get("entity_uid") or "").strip()
            canonical_name = str(entity.get("canonical_name") or "").strip()
            if not entity_uid or not canonical_name:
                continue
            metadata = entity.get("metadata") if isinstance(entity.get("metadata"), dict) else {}
            cursor = self.connection.execute(
                """
                INSERT INTO analysis_entities (
                    book_id, run_id, entity_uid, entity_type, canonical_name,
                    summary, confidence, status, source_rule, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    run_id,
                    entity_uid,
                    str(entity.get("entity_type") or "unknown"),
                    canonical_name,
                    str(entity.get("summary") or ""),
                    float(entity.get("confidence") or 0.0),
                    str(entity.get("status") or "candidate"),
                    str(entity.get("source_rule") or "auto_coreference"),
                    self._json_payload(metadata),
                ),
            )
            entity_ids.append(int(cursor.lastrowid))
            aliases = entity.get("aliases") if isinstance(entity.get("aliases"), list) else []
            for alias in [canonical_name, *aliases]:
                clean_alias = str(alias or "").strip()
                if not clean_alias:
                    continue
                self.connection.execute(
                    """
                    INSERT OR IGNORE INTO analysis_entity_aliases (
                        book_id, run_id, entity_uid, alias, source, confidence, status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        book_id,
                        run_id,
                        entity_uid,
                        clean_alias,
                        str(entity.get("source_rule") or "auto_coreference"),
                        float(entity.get("confidence") or 0.0),
                        "candidate",
                    ),
                )
            mention_uids = entity.get("mention_uids") if isinstance(entity.get("mention_uids"), list) else []
            for mention_uid in mention_uids:
                clean_mention_uid = str(mention_uid or "").strip()
                if not clean_mention_uid:
                    continue
                self.connection.execute(
                    """
                    UPDATE analysis_entity_mentions
                    SET entity_uid = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE book_id = ? AND run_id = ? AND mention_uid = ?
                    """,
                    (entity_uid, book_id, run_id, clean_mention_uid),
                )
            self._insert_analysis_entity_version(
                book_id,
                run_id,
                entity_uid,
                action="auto_coreference",
                old_value={},
                new_value=entity,
                actor="system",
            )
        self.connection.commit()
        return entity_ids

    def list_analysis_entities(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        limit: int | None = 1000,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT
                e.*,
                (SELECT COUNT(*) FROM analysis_entity_mentions AS m
                 WHERE m.book_id = e.book_id AND m.run_id = e.run_id AND m.entity_uid = e.entity_uid) AS mention_count
            FROM analysis_entities AS e
            WHERE e.book_id = ?
        """
        params: list[Any] = [book_id]
        if run_id is not None:
            sql += " AND e.run_id = ?"
            params.append(run_id)
        sql += " ORDER BY e.run_id DESC, e.entity_type ASC, e.canonical_name ASC, e.id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def list_analysis_entity_aliases(self, book_id: int, run_id: int, entity_uid: str) -> list[sqlite3.Row]:
        cursor = self.connection.execute(
            """
            SELECT *
            FROM analysis_entity_aliases
            WHERE book_id = ? AND run_id = ? AND entity_uid = ?
            ORDER BY id ASC
            """,
            (book_id, run_id, entity_uid),
        )
        return list(cursor.fetchall())

    def get_analysis_entity(self, book_id: int, run_id: int, entity_uid: str) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT *
            FROM analysis_entities
            WHERE book_id = ? AND run_id = ? AND entity_uid = ?
            """,
            (book_id, run_id, entity_uid),
        )
        return cursor.fetchone()

    def update_analysis_entity(
        self,
        book_id: int,
        run_id: int,
        entity_uid: str,
        *,
        canonical_name: str | None = None,
        status: str | None = None,
        summary: str | None = None,
        aliases: list[str] | None = None,
        actor: str = "user",
        action: str = "manual_update",
    ) -> sqlite3.Row | None:
        existing = self.get_analysis_entity(book_id, run_id, entity_uid)
        if not existing:
            return None
        old_value = {
            "canonical_name": str(existing["canonical_name"] or ""),
            "status": str(existing["status"] or ""),
            "summary": str(existing["summary"] or ""),
            "aliases": [str(row["alias"] or "") for row in self.list_analysis_entity_aliases(book_id, run_id, entity_uid)],
        }
        next_name = str(canonical_name if canonical_name is not None else existing["canonical_name"] or "").strip()
        next_status = str(status if status is not None else existing["status"] or "candidate").strip() or "candidate"
        next_summary = str(summary if summary is not None else existing["summary"] or "")
        self.connection.execute(
            """
            UPDATE analysis_entities
            SET canonical_name = ?, status = ?, summary = ?, updated_at = CURRENT_TIMESTAMP
            WHERE book_id = ? AND run_id = ? AND entity_uid = ?
            """,
            (next_name, next_status, next_summary, book_id, run_id, entity_uid),
        )
        if aliases is not None:
            clean_aliases = sorted({str(alias or "").strip() for alias in aliases if str(alias or "").strip()})
            if next_name:
                clean_aliases = sorted({next_name, *clean_aliases})
            self.connection.execute(
                "DELETE FROM analysis_entity_aliases WHERE book_id = ? AND run_id = ? AND entity_uid = ?",
                (book_id, run_id, entity_uid),
            )
            for alias in clean_aliases:
                self.connection.execute(
                    """
                    INSERT OR IGNORE INTO analysis_entity_aliases (
                        book_id, run_id, entity_uid, alias, source, confidence, status
                    )
                    VALUES (?, ?, ?, ?, 'manual', 1.0, ?)
                    """,
                    (book_id, run_id, entity_uid, alias, next_status),
                )
        elif next_name:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO analysis_entity_aliases (
                    book_id, run_id, entity_uid, alias, source, confidence, status
                )
                VALUES (?, ?, ?, ?, 'manual', 1.0, ?)
                """,
                (book_id, run_id, entity_uid, next_name, next_status),
            )
        new_value = {
            "canonical_name": next_name,
            "status": next_status,
            "summary": next_summary,
            "aliases": [str(row["alias"] or "") for row in self.list_analysis_entity_aliases(book_id, run_id, entity_uid)],
        }
        self._insert_analysis_entity_version(
            book_id,
            run_id,
            entity_uid,
            action=action or "manual_update",
            old_value=old_value,
            new_value=new_value,
            actor=actor,
        )
        self.connection.commit()
        return self.get_analysis_entity(book_id, run_id, entity_uid)

    def merge_analysis_entities(
        self,
        book_id: int,
        run_id: int,
        *,
        target_entity_uid: str,
        source_entity_uids: list[str],
        canonical_name: str = "",
        aliases: list[str] | None = None,
        summary: str = "",
        actor: str = "user",
    ) -> sqlite3.Row | None:
        clean_target = str(target_entity_uid or "").strip()
        clean_sources = sorted({str(item or "").strip() for item in source_entity_uids if str(item or "").strip() and str(item or "").strip() != clean_target})
        target = self.get_analysis_entity(book_id, run_id, clean_target)
        if not target or not clean_sources:
            return None
        source_rows = [self.get_analysis_entity(book_id, run_id, entity_uid) for entity_uid in clean_sources]
        source_rows = [row for row in source_rows if row is not None]
        if not source_rows:
            return None

        target_old = self._analysis_entity_snapshot(book_id, run_id, clean_target)
        target_aliases = {str(row["alias"] or "") for row in self.list_analysis_entity_aliases(book_id, run_id, clean_target)}
        for source_uid in clean_sources:
            target_aliases.update(str(row["alias"] or "") for row in self.list_analysis_entity_aliases(book_id, run_id, source_uid))
        target_aliases.update(str(alias or "").strip() for alias in (aliases or []) if str(alias or "").strip())
        next_name = str(canonical_name or target["canonical_name"] or "").strip()
        if next_name:
            target_aliases.add(next_name)
        next_summary = str(summary if summary else target["summary"] or "")

        placeholders = ",".join("?" for _ in clean_sources)
        self.connection.execute(
            f"""
            UPDATE analysis_entity_mentions
            SET entity_uid = ?, updated_at = CURRENT_TIMESTAMP
            WHERE book_id = ? AND run_id = ? AND entity_uid IN ({placeholders})
            """,
            [clean_target, book_id, run_id, *clean_sources],
        )
        self.connection.execute(
            f"""
            UPDATE analysis_facts
            SET subject_entity_uid = ?, updated_at = CURRENT_TIMESTAMP
            WHERE book_id = ? AND run_id = ? AND subject_entity_uid IN ({placeholders})
            """,
            [clean_target, book_id, run_id, *clean_sources],
        )
        self.connection.execute(
            f"""
            UPDATE analysis_card_dependencies
            SET dependency_uid = ?
            WHERE book_id = ? AND run_id = ? AND dependency_type = 'entity' AND dependency_uid IN ({placeholders})
            """,
            [clean_target, book_id, run_id, *clean_sources],
        )
        self.connection.execute(
            f"""
            UPDATE analysis_cards
            SET entity_uid = ?, updated_at = CURRENT_TIMESTAMP
            WHERE book_id = ? AND run_id = ? AND entity_uid IN ({placeholders})
            """,
            [clean_target, book_id, run_id, *clean_sources],
        )
        self.connection.execute(
            """
            UPDATE analysis_entities
            SET canonical_name = ?, summary = ?, status = 'reviewed', source_rule = 'manual_merge', updated_at = CURRENT_TIMESTAMP
            WHERE book_id = ? AND run_id = ? AND entity_uid = ?
            """,
            (next_name, next_summary, book_id, run_id, clean_target),
        )
        self.connection.execute(
            "DELETE FROM analysis_entity_aliases WHERE book_id = ? AND run_id = ? AND entity_uid = ?",
            (book_id, run_id, clean_target),
        )
        for alias in sorted(alias for alias in target_aliases if alias):
            self.connection.execute(
                """
                INSERT OR IGNORE INTO analysis_entity_aliases (
                    book_id, run_id, entity_uid, alias, source, confidence, status
                )
                VALUES (?, ?, ?, ?, 'manual_merge', 1.0, 'reviewed')
                """,
                (book_id, run_id, clean_target, alias),
            )
        for source_uid in clean_sources:
            source_old = self._analysis_entity_snapshot(book_id, run_id, source_uid)
            self.connection.execute(
                """
                UPDATE analysis_entities
                SET status = 'merged', source_rule = 'manual_merge', updated_at = CURRENT_TIMESTAMP
                WHERE book_id = ? AND run_id = ? AND entity_uid = ?
                """,
                (book_id, run_id, source_uid),
            )
            self._insert_analysis_entity_version(
                book_id,
                run_id,
                source_uid,
                action="manual_merged_into",
                old_value=source_old,
                new_value={**source_old, "status": "merged", "merged_into": clean_target},
                actor=actor,
            )
        target_new = self._analysis_entity_snapshot(book_id, run_id, clean_target)
        self._insert_analysis_entity_version(
            book_id,
            run_id,
            clean_target,
            action="manual_merge",
            old_value=target_old,
            new_value={**target_new, "merged_source_entity_uids": clean_sources},
            actor=actor,
        )
        self.connection.commit()
        return self.get_analysis_entity(book_id, run_id, clean_target)

    def split_analysis_entity(
        self,
        book_id: int,
        run_id: int,
        *,
        source_entity_uid: str,
        new_entity_uid: str,
        canonical_name: str,
        aliases: list[str] | None = None,
        mention_uids: list[str] | None = None,
        fact_uids: list[str] | None = None,
        actor: str = "user",
    ) -> sqlite3.Row | None:
        clean_source = str(source_entity_uid or "").strip()
        clean_new_uid = str(new_entity_uid or "").strip()
        clean_name = str(canonical_name or "").strip()
        source = self.get_analysis_entity(book_id, run_id, clean_source)
        if not source or not clean_new_uid or not clean_name:
            return None
        if self.get_analysis_entity(book_id, run_id, clean_new_uid):
            return None
        source_old = self._analysis_entity_snapshot(book_id, run_id, clean_source)
        metadata = {
            "manual_split_from": clean_source,
            "source_entity_name": str(source["canonical_name"] or ""),
        }
        self.connection.execute(
            """
            INSERT INTO analysis_entities (
                book_id, run_id, entity_uid, entity_type, canonical_name,
                summary, confidence, status, source_rule, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, '', 1.0, 'reviewed', 'manual_split', ?)
            """,
            (
                book_id,
                run_id,
                clean_new_uid,
                str(source["entity_type"] or "unknown"),
                clean_name,
                self._json_payload(metadata),
            ),
        )
        clean_aliases = sorted({clean_name, *(str(alias or "").strip() for alias in (aliases or []) if str(alias or "").strip())})
        for alias in clean_aliases:
            self.connection.execute(
                """
                INSERT OR IGNORE INTO analysis_entity_aliases (
                    book_id, run_id, entity_uid, alias, source, confidence, status
                )
                VALUES (?, ?, ?, ?, 'manual_split', 1.0, 'reviewed')
                """,
                (book_id, run_id, clean_new_uid, alias),
            )
        clean_mentions = sorted({str(item or "").strip() for item in (mention_uids or []) if str(item or "").strip()})
        if clean_mentions:
            placeholders = ",".join("?" for _ in clean_mentions)
            self.connection.execute(
                f"""
                UPDATE analysis_entity_mentions
                SET entity_uid = ?, updated_at = CURRENT_TIMESTAMP
                WHERE book_id = ? AND run_id = ? AND entity_uid = ? AND mention_uid IN ({placeholders})
                """,
                [clean_new_uid, book_id, run_id, clean_source, *clean_mentions],
            )
        clean_facts = sorted({str(item or "").strip() for item in (fact_uids or []) if str(item or "").strip()})
        if clean_facts:
            placeholders = ",".join("?" for _ in clean_facts)
            self.connection.execute(
                f"""
                UPDATE analysis_facts
                SET subject_entity_uid = ?, updated_at = CURRENT_TIMESTAMP
                WHERE book_id = ? AND run_id = ? AND subject_entity_uid = ? AND fact_uid IN ({placeholders})
                """,
                [clean_new_uid, book_id, run_id, clean_source, *clean_facts],
            )
        new_snapshot = self._analysis_entity_snapshot(book_id, run_id, clean_new_uid)
        self._insert_analysis_entity_version(
            book_id,
            run_id,
            clean_new_uid,
            action="manual_split",
            old_value={},
            new_value={**new_snapshot, "split_from": clean_source, "mention_uids": clean_mentions, "fact_uids": clean_facts},
            actor=actor,
        )
        self._insert_analysis_entity_version(
            book_id,
            run_id,
            clean_source,
            action="manual_split_source",
            old_value=source_old,
            new_value={**self._analysis_entity_snapshot(book_id, run_id, clean_source), "split_to": clean_new_uid},
            actor=actor,
        )
        self.connection.commit()
        return self.get_analysis_entity(book_id, run_id, clean_new_uid)

    def rollback_analysis_entity_to_version(
        self,
        book_id: int,
        run_id: int,
        entity_uid: str,
        version: int,
        *,
        actor: str = "user",
    ) -> sqlite3.Row | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM analysis_entity_versions
            WHERE book_id = ? AND run_id = ? AND entity_uid = ? AND version = ?
            LIMIT 1
            """,
            (book_id, run_id, entity_uid, int(version)),
        ).fetchone()
        if row is None:
            return None
        snapshot = self._json_object(str(row["new_value_json"] or "{}"))
        if not snapshot:
            return None
        return self.update_analysis_entity(
            book_id,
            run_id,
            entity_uid,
            canonical_name=str(snapshot.get("canonical_name") or ""),
            status=str(snapshot.get("status") or "candidate"),
            summary=str(snapshot.get("summary") or ""),
            aliases=[str(alias) for alias in snapshot.get("aliases") or []],
            actor=actor,
            action="manual_rollback",
        )

    def list_analysis_entity_versions(
        self,
        book_id: int,
        run_id: int,
        entity_uid: str,
        *,
        limit: int | None = 100,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT *
            FROM analysis_entity_versions
            WHERE book_id = ? AND run_id = ? AND entity_uid = ?
            ORDER BY version ASC, id ASC
        """
        params: list[Any] = [book_id, run_id, entity_uid]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def _analysis_entity_snapshot(self, book_id: int, run_id: int, entity_uid: str) -> dict[str, Any]:
        row = self.get_analysis_entity(book_id, run_id, entity_uid)
        if not row:
            return {}
        return {
            "entity_uid": str(row["entity_uid"] or ""),
            "entity_type": str(row["entity_type"] or "unknown"),
            "canonical_name": str(row["canonical_name"] or ""),
            "summary": str(row["summary"] or ""),
            "confidence": float(row["confidence"] or 0.0),
            "status": str(row["status"] or "candidate"),
            "source_rule": str(row["source_rule"] or ""),
            "aliases": [str(alias_row["alias"] or "") for alias_row in self.list_analysis_entity_aliases(book_id, run_id, entity_uid)],
        }

    def _insert_analysis_entity_version(
        self,
        book_id: int,
        run_id: int,
        entity_uid: str,
        *,
        action: str,
        old_value: Any,
        new_value: Any,
        actor: str,
    ) -> int:
        row = self.connection.execute(
            """
            SELECT COALESCE(MAX(version), 0) + 1 AS next_version
            FROM analysis_entity_versions
            WHERE book_id = ? AND run_id = ? AND entity_uid = ?
            """,
            (book_id, run_id, entity_uid),
        ).fetchone()
        version = int(row["next_version"] or 1) if row else 1
        cursor = self.connection.execute(
            """
            INSERT INTO analysis_entity_versions (
                book_id, run_id, entity_uid, version, action,
                old_value_json, new_value_json, actor
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                run_id,
                entity_uid,
                version,
                action,
                self._json_payload(old_value or {}),
                self._json_payload(new_value or {}),
                actor or "system",
            ),
        )
        return int(cursor.lastrowid)

    def replace_analysis_facts(
        self,
        book_id: int,
        run_id: int,
        facts: list[dict[str, Any]],
    ) -> list[int]:
        self.connection.execute(
            "DELETE FROM analysis_facts WHERE book_id = ? AND run_id = ?",
            (book_id, run_id),
        )
        return self._insert_analysis_facts(book_id, run_id, facts)

    def add_analysis_facts(
        self,
        book_id: int,
        run_id: int,
        facts: list[dict[str, Any]],
    ) -> list[int]:
        """增量插入原子事实，不执行 DELETE。用于流式写入场景，逐批写入避免内存累积。"""
        return self._insert_analysis_facts(book_id, run_id, facts)

    def replace_analysis_facts_for_scope(
        self,
        book_id: int,
        run_id: int,
        facts: list[dict[str, Any]],
        *,
        block_uids: list[str] | None = None,
        entity_uids: list[str] | None = None,
    ) -> list[int]:
        clean_blocks = sorted({str(item or "").strip() for item in (block_uids or []) if str(item or "").strip()})
        clean_entities = sorted({str(item or "").strip() for item in (entity_uids or []) if str(item or "").strip()})
        clauses: list[str] = []
        params: list[Any] = [book_id, run_id]
        if clean_blocks:
            clauses.append("block_uid IN (" + ",".join("?" for _ in clean_blocks) + ")")
            params.extend(clean_blocks)
        if clean_entities:
            clauses.append("subject_entity_uid IN (" + ",".join("?" for _ in clean_entities) + ")")
            params.extend(clean_entities)
        if not clauses:
            return []
        self.connection.execute(
            f"""
            DELETE FROM analysis_facts
            WHERE book_id = ? AND run_id = ? AND ({" OR ".join(clauses)})
            """,
            params,
        )
        return self._insert_analysis_facts(book_id, run_id, facts)

    def _insert_analysis_facts(
        self,
        book_id: int,
        run_id: int,
        facts: list[dict[str, Any]],
    ) -> list[int]:
        fact_ids: list[int] = []
        for fact in facts:
            fact_uid = str(fact.get("fact_uid") or "").strip()
            subject_entity_uid = str(fact.get("subject_entity_uid") or "").strip()
            quote_text = str(fact.get("quote_text") or "").strip()
            if not fact_uid or not subject_entity_uid or not quote_text:
                continue
            value = fact.get("value") if isinstance(fact.get("value"), dict) else {}
            metadata = fact.get("metadata") if isinstance(fact.get("metadata"), dict) else {}
            cursor = self.connection.execute(
                """
                INSERT INTO analysis_facts (
                    book_id, run_id, fact_uid, subject_entity_uid, fact_type,
                    value_json, quote_text, chapter_id, block_uid, confidence,
                    memory_scope, memory_importance, memory_type, importance_score,
                    status, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    run_id,
                    fact_uid,
                    subject_entity_uid,
                    str(fact.get("fact_type") or "event"),
                    self._json_payload(value),
                    quote_text,
                    self._analysis_int(fact.get("chapter_id"), 0) or None,
                    str(fact.get("block_uid") or ""),
                    float(fact.get("confidence") or 0.0),
                    str(fact.get("memory_scope") or "short_term"),
                    str(fact.get("memory_importance") or "normal"),
                    str(fact.get("memory_type") or "evidence"),
                    float(fact.get("importance_score") or fact.get("confidence") or 0.0),
                    str(fact.get("status") or "candidate"),
                    self._json_payload(metadata),
                ),
            )
            fact_ids.append(int(cursor.lastrowid))
        self.connection.commit()
        return fact_ids

    def upsert_analysis_memory_summaries(
        self,
        book_id: int,
        run_id: int,
        summaries: list[dict[str, Any]],
    ) -> list[int]:
        """仅追加/替换 memory_summary 类型的事实，不删除其他 facts。

        用于记忆分层后台静默写回：先删除该 run 下已有的 memory_summary 行，
        再插入新的，避免全量 replace_facts 影响主流程正在读取的原始 facts。
        """
        if not summaries:
            return []
        # 删除该 run 已有的 memory_summary（避免重复累积）
        self.connection.execute(
            "DELETE FROM analysis_facts WHERE book_id = ? AND run_id = ? AND fact_type = ?",
            (book_id, run_id, "memory_summary"),
        )
        # 只插入 memory_summary 类型
        clean = [s for s in summaries if str(s.get("fact_type") or "") == "memory_summary"]
        return self._insert_analysis_facts(book_id, run_id, clean)

    def list_analysis_facts(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        entity_uid: str | None = None,
        chapter_id: int | None = None,
        limit: int | None = 1000,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT *
            FROM analysis_facts
            WHERE book_id = ?
        """
        params: list[Any] = [book_id]
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        if entity_uid:
            sql += " AND subject_entity_uid = ?"
            params.append(str(entity_uid))
        if chapter_id is not None:
            sql += " AND chapter_id = ?"
            params.append(chapter_id)
        sql += " ORDER BY run_id DESC, chapter_id ASC, id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def replace_analysis_events(
        self,
        book_id: int,
        run_id: int,
        events: list[dict[str, Any]],
    ) -> list[int]:
        self.connection.execute(
            "DELETE FROM analysis_events WHERE book_id = ? AND run_id = ?",
            (book_id, run_id),
        )
        event_ids: list[int] = []
        for event in events:
            event_uid = str(event.get("event_uid") or "").strip()
            if not event_uid:
                continue
            cursor = self.connection.execute(
                """
                INSERT INTO analysis_events (
                    book_id, run_id, event_uid, event_type, payload_json,
                    status, priority, attempts, error_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    run_id,
                    event_uid,
                    str(event.get("event_type") or ""),
                    self._json_payload(event.get("payload") if isinstance(event.get("payload"), dict) else {}),
                    str(event.get("status") or "pending"),
                    self._analysis_int(event.get("priority"), 0),
                    self._analysis_int(event.get("attempts"), 0),
                    str(event.get("error_text") or ""),
                ),
            )
            event_ids.append(int(cursor.lastrowid))
        self.connection.commit()
        return event_ids

    def upsert_analysis_events(
        self,
        book_id: int,
        run_id: int,
        events: list[dict[str, Any]],
    ) -> list[int]:
        event_ids: list[int] = []
        for event in events:
            event_uid = str(event.get("event_uid") or "").strip()
            if not event_uid:
                continue
            cursor = self.connection.execute(
                """
                INSERT INTO analysis_events (
                    book_id, run_id, event_uid, event_type, payload_json,
                    status, priority, attempts, error_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(book_id, run_id, event_uid) DO UPDATE SET
                    event_type = excluded.event_type,
                    payload_json = excluded.payload_json,
                    status = excluded.status,
                    priority = excluded.priority,
                    attempts = excluded.attempts,
                    error_text = excluded.error_text,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    book_id,
                    run_id,
                    event_uid,
                    str(event.get("event_type") or ""),
                    self._json_payload(event.get("payload") if isinstance(event.get("payload"), dict) else {}),
                    str(event.get("status") or "pending"),
                    self._analysis_int(event.get("priority"), 0),
                    self._analysis_int(event.get("attempts"), 0),
                    str(event.get("error_text") or ""),
                ),
            )
            row = self.connection.execute(
                """
                SELECT id FROM analysis_events
                WHERE book_id = ? AND run_id = ? AND event_uid = ?
                """,
                (book_id, run_id, event_uid),
            ).fetchone()
            event_ids.append(int(row["id"] if row else cursor.lastrowid))
        self.connection.commit()
        return event_ids

    def list_analysis_events(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        status: str | None = None,
        limit: int | None = 1000,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT *
            FROM analysis_events
            WHERE book_id = ?
        """
        params: list[Any] = [book_id]
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY priority DESC, id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

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

    def replace_analysis_probe_plans(
        self,
        book_id: int,
        run_id: int,
        plans: list[dict[str, Any]],
    ) -> list[int]:
        self.connection.execute(
            "DELETE FROM analysis_probe_plans WHERE book_id = ? AND run_id = ?",
            (book_id, run_id),
        )
        plan_ids: list[int] = []
        for plan in plans:
            probe_uid = str(plan.get("probe_uid") or "").strip()
            if not probe_uid:
                continue
            cursor = self.connection.execute(
                """
                INSERT INTO analysis_probe_plans (
                    book_id, run_id, probe_uid, probe_type, subject_entity_uid,
                    plan_json, status, priority
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    run_id,
                    probe_uid,
                    str(plan.get("probe_type") or ""),
                    str(plan.get("subject_entity_uid") or ""),
                    self._json_payload(plan.get("plan") if isinstance(plan.get("plan"), dict) else {}),
                    str(plan.get("status") or "pending"),
                    self._analysis_int(plan.get("priority"), 0),
                ),
            )
            plan_ids.append(int(cursor.lastrowid))
        self.connection.commit()
        return plan_ids

    def list_analysis_probe_plans(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        status: str | None = None,
        limit: int | None = 1000,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT *
            FROM analysis_probe_plans
            WHERE book_id = ?
        """
        params: list[Any] = [book_id]
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        if status:
            sql += " AND status = ?"
            params.append(str(status))
        sql += " ORDER BY priority DESC, id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def replace_analysis_probe_results(
        self,
        book_id: int,
        run_id: int,
        results: list[dict[str, Any]],
    ) -> list[int]:
        self.connection.execute(
            "DELETE FROM analysis_probe_results WHERE book_id = ? AND run_id = ?",
            (book_id, run_id),
        )
        result_ids: list[int] = []
        for result in results:
            probe_uid = str(result.get("probe_uid") or "").strip()
            if not probe_uid:
                continue
            cursor = self.connection.execute(
                """
                INSERT INTO analysis_probe_results (
                    book_id, run_id, probe_uid, result_json,
                    consistency, confidence, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    run_id,
                    probe_uid,
                    self._json_payload(result.get("result") if isinstance(result.get("result"), dict) else {}),
                    str(result.get("consistency") or "unknown"),
                    float(result.get("confidence") or 0.0),
                    str(result.get("status") or "candidate"),
                ),
            )
            result_ids.append(int(cursor.lastrowid))
        self.connection.commit()
        return result_ids

    def list_analysis_probe_results(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        probe_uid: str | None = None,
        status: str | None = None,
        limit: int | None = 1000,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT *
            FROM analysis_probe_results
            WHERE book_id = ?
        """
        params: list[Any] = [book_id]
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        if probe_uid:
            sql += " AND probe_uid = ?"
            params.append(str(probe_uid))
        if status:
            sql += " AND status = ?"
            params.append(str(status))
        sql += " ORDER BY id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def create_analysis_backtrack_task(
        self,
        book_id: int,
        run_id: int,
        *,
        task_uid: str,
        trigger_type: str,
        target_uid: str,
        impact: dict[str, Any],
        status: str = "pending",
        priority: int = 50,
    ) -> sqlite3.Row:
        clean_task_uid = str(task_uid or "").strip()
        if not clean_task_uid:
            raise ValueError("backtrack task_uid is required")
        self.connection.execute(
            """
            INSERT INTO analysis_backtrack_tasks (
                book_id, run_id, task_uid, trigger_type, target_uid,
                impact_json, status, priority, error_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '')
            ON CONFLICT(book_id, run_id, task_uid) DO UPDATE SET
                trigger_type = excluded.trigger_type,
                target_uid = excluded.target_uid,
                impact_json = excluded.impact_json,
                status = excluded.status,
                priority = excluded.priority,
                error_text = '',
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                book_id,
                run_id,
                clean_task_uid,
                str(trigger_type or ""),
                str(target_uid or ""),
                self._json_payload(impact or {}),
                str(status or "pending"),
                self._analysis_int(priority, 50),
            ),
        )
        self.connection.commit()
        row = self.get_analysis_backtrack_task_by_uid(book_id, run_id, clean_task_uid)
        if row is None:
            raise RuntimeError("failed to create backtrack task")
        return row

    def get_analysis_backtrack_task(self, task_id: int) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            "SELECT * FROM analysis_backtrack_tasks WHERE id = ?",
            (int(task_id),),
        )
        return cursor.fetchone()

    def get_analysis_backtrack_task_by_uid(self, book_id: int, run_id: int, task_uid: str) -> sqlite3.Row | None:
        cursor = self.connection.execute(
            """
            SELECT *
            FROM analysis_backtrack_tasks
            WHERE book_id = ? AND run_id = ? AND task_uid = ?
            """,
            (book_id, run_id, str(task_uid or "")),
        )
        return cursor.fetchone()

    def list_analysis_backtrack_tasks(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        status: str | None = None,
        limit: int | None = 1000,
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT *
            FROM analysis_backtrack_tasks
            WHERE book_id = ?
        """
        params: list[Any] = [book_id]
        if run_id is not None:
            sql += " AND run_id = ?"
            params.append(run_id)
        if status:
            sql += " AND status = ?"
            params.append(str(status))
        sql += " ORDER BY priority DESC, id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        cursor = self.connection.execute(sql, params)
        return list(cursor.fetchall())

    def update_analysis_backtrack_task_status(
        self,
        task_id: int,
        status: str,
        *,
        impact: dict[str, Any] | None = None,
        error_text: str = "",
    ) -> sqlite3.Row | None:
        if impact is None:
            self.connection.execute(
                """
                UPDATE analysis_backtrack_tasks
                SET status = ?, error_text = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (str(status or "pending"), str(error_text or ""), int(task_id)),
            )
        else:
            self.connection.execute(
                """
                UPDATE analysis_backtrack_tasks
                SET status = ?, impact_json = ?, error_text = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (str(status or "pending"), self._json_payload(impact), str(error_text or ""), int(task_id)),
            )
        self.connection.commit()
        return self.get_analysis_backtrack_task(int(task_id))

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
