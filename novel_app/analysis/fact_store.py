from __future__ import annotations

import json
import sqlite3
from typing import Any

from novel_app.analysis.schemas_v3 import AtomicFact
from novel_app.database import Database


class FactStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def replace_facts(
        self,
        book_id: int,
        run_id: int,
        facts: list[AtomicFact | dict[str, Any]],
    ) -> list[int]:
        return self.database.replace_analysis_facts(
            int(book_id),
            int(run_id),
            [fact.as_analysis_fact() if isinstance(fact, AtomicFact) else dict(fact) for fact in facts],
        )

    def add_facts(
        self,
        book_id: int,
        run_id: int,
        facts: list[AtomicFact | dict[str, Any]],
    ) -> list[int]:
        """增量插入事实，不执行 DELETE。用于流式写入场景。"""
        return self.database.add_analysis_facts(
            int(book_id),
            int(run_id),
            [fact.as_analysis_fact() if isinstance(fact, AtomicFact) else dict(fact) for fact in facts],
        )

    def replace_facts_for_scope(
        self,
        book_id: int,
        run_id: int,
        facts: list[AtomicFact | dict[str, Any]],
        *,
        block_uids: list[str] | None = None,
        entity_uids: list[str] | None = None,
    ) -> list[int]:
        return self.database.replace_analysis_facts_for_scope(
            int(book_id),
            int(run_id),
            [fact.as_analysis_fact() if isinstance(fact, AtomicFact) else dict(fact) for fact in facts],
            block_uids=block_uids,
            entity_uids=entity_uids,
        )

    def upsert_memory_summaries(
        self,
        book_id: int,
        run_id: int,
        summaries: list[dict[str, Any]],
    ) -> list[int]:
        """仅追加/替换 memory_summary 类型事实，不删除其他 facts。

        用于记忆分层后台静默写回，避免全量 replace_facts 与主流程并发读取冲突。
        """
        return self.database.upsert_analysis_memory_summaries(
            int(book_id),
            int(run_id),
            [dict(s) for s in summaries],
        )

    def list_facts(
        self,
        book_id: int,
        *,
        run_id: int | None = None,
        entity_uid: str | None = None,
        chapter_id: int | None = None,
        limit: int | None = 1000,
    ) -> list[dict[str, Any]]:
        rows = self.database.list_analysis_facts(
            int(book_id),
            run_id=run_id,
            entity_uid=entity_uid,
            chapter_id=chapter_id,
            limit=limit,
        )
        return [_fact_row(row) for row in rows]


def _fact_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "book_id": int(row["book_id"]),
        "run_id": int(row["run_id"]),
        "fact_uid": str(row["fact_uid"] or ""),
        "subject_entity_uid": str(row["subject_entity_uid"] or ""),
        "fact_type": str(row["fact_type"] or "event"),
        "value": _json_object(str(row["value_json"] or "{}")),
        "quote_text": str(row["quote_text"] or ""),
        "chapter_id": row["chapter_id"],
        "block_uid": str(row["block_uid"] or ""),
        "confidence": float(row["confidence"] or 0.0),
        "memory_scope": str(row["memory_scope"] or ""),
        "memory_importance": str(row["memory_importance"] or ""),
        "memory_type": str(row["memory_type"] or ""),
        "importance_score": float(row["importance_score"] or 0.0),
        "status": str(row["status"] or "candidate"),
        "metadata": _json_object(str(row["metadata_json"] or "{}")),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
