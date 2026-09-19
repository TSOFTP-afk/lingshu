from __future__ import annotations

from novel_app.db.analysis_parts.common import *


class AnalysisEntitiesMixin:
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

