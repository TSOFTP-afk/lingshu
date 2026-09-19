from __future__ import annotations

from novel_app.db.analysis_parts.common import *


class AnalysisRunsMixin:
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

