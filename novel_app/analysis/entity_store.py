from __future__ import annotations

import json
import sqlite3
from typing import Any

from novel_app.analysis.schemas_v3 import EntityMentionCandidate, ResolvedEntityCandidate, stable_hash
from novel_app.database import Database


class EntityStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def replace_mentions(
        self,
        book_id: int,
        run_id: int,
        mentions: list[EntityMentionCandidate],
    ) -> list[int]:
        return self.database.replace_analysis_entity_mentions(
            int(book_id),
            int(run_id),
            [mention.as_analysis_mention() for mention in mentions],
        )

    def add_mentions(
        self,
        book_id: int,
        run_id: int,
        mentions: list[EntityMentionCandidate],
    ) -> list[int]:
        """增量插入提及，不执行 DELETE。用于流式写入场景。"""
        return self.database.add_analysis_entity_mentions(
            int(book_id),
            int(run_id),
            [mention.as_analysis_mention() for mention in mentions],
        )

    def list_mentions(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        chapter_id: int | None = None,
        limit: int | None = 1000,
    ) -> list[dict[str, Any]]:
        rows = self.database.list_analysis_entity_mentions(
            int(book_id),
            run_id=run_id,
            chapter_id=chapter_id,
            limit=limit,
        )
        return [_mention_row(row) for row in rows]

    def replace_entities(
        self,
        book_id: int,
        run_id: int,
        entities: list[ResolvedEntityCandidate],
    ) -> list[int]:
        return self.database.replace_analysis_entities(
            int(book_id),
            int(run_id),
            [entity.as_analysis_entity() for entity in entities],
        )

    def list_entities(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        limit: int | None = 1000,
    ) -> list[dict[str, Any]]:
        rows = self.database.list_analysis_entities(
            int(book_id),
            run_id=run_id,
            limit=limit,
        )
        return [self._entity_row(row) for row in rows]

    def update_entity(
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
    ) -> dict[str, Any] | None:
        row = self.database.update_analysis_entity(
            int(book_id),
            int(run_id),
            str(entity_uid),
            canonical_name=canonical_name,
            status=status,
            summary=summary,
            aliases=aliases,
            actor=actor,
            action=action,
        )
        return self._entity_row(row) if row else None

    def merge_entities(
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
    ) -> dict[str, Any] | None:
        row = self.database.merge_analysis_entities(
            int(book_id),
            int(run_id),
            target_entity_uid=str(target_entity_uid or ""),
            source_entity_uids=[str(entity_uid or "") for entity_uid in source_entity_uids],
            canonical_name=str(canonical_name or ""),
            aliases=[str(alias or "") for alias in aliases] if aliases is not None else None,
            summary=str(summary or ""),
            actor=str(actor or "user"),
        )
        return self._entity_row(row) if row else None

    def split_entity(
        self,
        book_id: int,
        run_id: int,
        *,
        source_entity_uid: str,
        canonical_name: str,
        aliases: list[str] | None = None,
        mention_uids: list[str] | None = None,
        fact_uids: list[str] | None = None,
        actor: str = "user",
    ) -> dict[str, Any] | None:
        clean_source = str(source_entity_uid or "").strip()
        clean_name = str(canonical_name or "").strip()
        clean_mentions = sorted({str(item or "").strip() for item in (mention_uids or []) if str(item or "").strip()})
        clean_facts = sorted({str(item or "").strip() for item in (fact_uids or []) if str(item or "").strip()})
        uid_seed = "|".join(
            [
                str(book_id),
                str(run_id),
                clean_source,
                clean_name,
                ",".join(clean_mentions),
                ",".join(clean_facts),
            ]
        )
        new_entity_uid = f"ENT-MANUAL-{stable_hash(uid_seed)[:16]}"
        row = self.database.split_analysis_entity(
            int(book_id),
            int(run_id),
            source_entity_uid=clean_source,
            new_entity_uid=new_entity_uid,
            canonical_name=clean_name,
            aliases=[str(alias or "") for alias in aliases] if aliases is not None else None,
            mention_uids=clean_mentions,
            fact_uids=clean_facts,
            actor=str(actor or "user"),
        )
        return self._entity_row(row) if row else None

    def rollback_entity(
        self,
        book_id: int,
        run_id: int,
        entity_uid: str,
        version: int,
        *,
        actor: str = "user",
    ) -> dict[str, Any] | None:
        row = self.database.rollback_analysis_entity_to_version(
            int(book_id),
            int(run_id),
            str(entity_uid or ""),
            int(version),
            actor=str(actor or "user"),
        )
        return self._entity_row(row) if row else None

    def list_entity_versions(
        self,
        book_id: int,
        run_id: int,
        entity_uid: str,
        *,
        limit: int | None = 100,
    ) -> list[dict[str, Any]]:
        rows = self.database.list_analysis_entity_versions(
            int(book_id),
            int(run_id),
            str(entity_uid),
            limit=limit,
        )
        return [_entity_version_row(row) for row in rows]

    def _entity_row(self, row: sqlite3.Row) -> dict[str, Any]:
        metadata = _json_object(str(row["metadata_json"] or "{}"))
        aliases = [
            str(alias_row["alias"] or "")
            for alias_row in self.database.list_analysis_entity_aliases(
                int(row["book_id"]),
                int(row["run_id"]),
                str(row["entity_uid"] or ""),
            )
        ]
        return {
            "id": int(row["id"]),
            "book_id": int(row["book_id"]),
            "run_id": int(row["run_id"]),
            "entity_uid": str(row["entity_uid"] or ""),
            "entity_type": str(row["entity_type"] or "unknown"),
            "canonical_name": str(row["canonical_name"] or ""),
            "aliases": aliases,
            "summary": str(row["summary"] or ""),
            "confidence": float(row["confidence"] or 0.0),
            "status": str(row["status"] or "candidate"),
            "source_rule": str(row["source_rule"] or ""),
            "mention_count": int(row["mention_count"] or 0) if _row_has_key(row, "mention_count") else 0,
            "metadata": metadata,
            "created_at": str(row["created_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
        }


def _mention_row(row: sqlite3.Row) -> dict[str, Any]:
    metadata = _json_object(str(row["metadata_json"] or "{}"))
    return {
        "id": int(row["id"]),
        "book_id": int(row["book_id"]),
        "run_id": int(row["run_id"]),
        "mention_uid": str(row["mention_uid"] or ""),
        "entity_uid": str(row["entity_uid"] or ""),
        "entity_type": str(row["entity_type"] or "unknown"),
        "normalized_text": str(row["normalized_text"] or ""),
        "quote_text": str(row["quote_text"] or ""),
        "chapter_id": row["chapter_id"],
        "block_uid": str(row["block_uid"] or ""),
        "char_start": int(row["char_start"] or 0),
        "char_end": int(row["char_end"] or 0),
        "confidence": float(row["confidence"] or 0.0),
        "status": str(row["status"] or "candidate"),
        "source_rule": str(row["source_rule"] or ""),
        "metadata": metadata,
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }


def _row_has_key(row: sqlite3.Row, key: str) -> bool:
    try:
        return key in row.keys()
    except Exception:
        return False


def _entity_version_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "book_id": int(row["book_id"]),
        "run_id": int(row["run_id"]),
        "entity_uid": str(row["entity_uid"] or ""),
        "version": int(row["version"] or 0),
        "action": str(row["action"] or ""),
        "old_value": _json_object(str(row["old_value_json"] or "{}")),
        "new_value": _json_object(str(row["new_value_json"] or "{}")),
        "actor": str(row["actor"] or ""),
        "created_at": str(row["created_at"] or ""),
    }


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
