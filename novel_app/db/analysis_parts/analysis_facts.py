from __future__ import annotations

from novel_app.db.analysis_parts.common import *


class AnalysisFactsMixin:
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

