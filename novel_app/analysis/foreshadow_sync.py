"""伏笔同步：从 analysis_facts 抽取 foreshadowing 事实到 foreshadows 表。

V3 pipeline M4 完成后调用 sync_foreshadows_from_facts()，
将 fact_type="foreshadowing" 的事实同步为伏笔记录（按 fact_uid 去重）。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from novel_app.database import Database

logger = logging.getLogger(__name__)


def sync_foreshadows_from_facts(
    database: Database,
    book_id: int,
    *,
    run_id: int | None = None,
) -> int:
    """从 analysis_facts 同步 foreshadowing 事实到 foreshadows 表。

    Args:
        database: Database 实例
        book_id: 书籍 ID
        run_id: 可选，限定某个 run 的范围；为 None 时取最新 run 的 facts

    Returns:
        新增的伏笔数量
    """
    facts = database.list_analysis_facts(book_id, run_id=run_id, limit=5000)
    foreshadow_facts = [f for f in facts if str(f["fact_type"]) == "foreshadowing"]
    if not foreshadow_facts:
        return 0

    added = 0
    for fact in foreshadow_facts:
        fact_uid = str(fact["fact_uid"] or "")
        # 按 fact_uid 去重
        if fact_uid and database.find_foreshadow_by_fact_uid(book_id, fact_uid):
            continue

        description = _extract_description(fact)
        if not description:
            continue

        chapter_id = fact["chapter_id"] if fact["chapter_id"] else None
        priority = _infer_priority(fact)

        try:
            database.create_foreshadow(
                book_id,
                description,
                status="pending",
                priority=priority,
                source="auto",
                setup_chapter_id=chapter_id,
                fact_uid=fact_uid,
            )
            added += 1
        except Exception as exc:
            logger.warning("Failed to create foreshadow from fact %s: %s", fact_uid, exc)

    if added:
        logger.info("Synced %d foreshadows for book %d", added, book_id)
    return added


def _extract_description(fact: Any) -> str:
    """从 fact 的 value_json 或 quote_text 提取伏笔描述。"""
    # 优先用 value_json 中的 description/text 字段
    try:
        value = json.loads(str(fact["value_json"] or "{}"))
        if isinstance(value, dict):
            for key in ("description", "text", "content", "summary"):
                v = value.get(key)
                if v and isinstance(v, str) and v.strip():
                    return v.strip()
    except (json.JSONDecodeError, TypeError):
        pass

    # 回退到 quote_text
    quote = str(fact["quote_text"] or "").strip()
    if quote:
        return quote

    return ""


def _infer_priority(fact: Any) -> str:
    """根据 importance_score 推断优先级。"""
    try:
        score = float(fact["importance_score"] or 0)
    except (TypeError, ValueError):
        score = 0.0
    if score >= 0.7:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"
