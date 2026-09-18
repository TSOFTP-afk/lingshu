from __future__ import annotations

import html
from typing import Any

from novel_app.analysis.models import AnalysisCardDraft
from novel_app.analysis.schemas_v3 import stable_hash

V3_CARD_MIN_FACT_CONFIDENCE = 0.55


def build_v3_entity_card(
    *,
    book_id: int,
    run_id: int,
    entity: dict[str, Any],
    facts: list[dict[str, Any]],
    card_type: str,
    dependency_hash: str,
    use_ai: bool = False,
    ai_provider: Any = None,
) -> AnalysisCardDraft:
    canonical_name = str(entity.get("canonical_name") or "未命名实体")
    card_uid = _card_uid(book_id, run_id, card_type, str(entity.get("entity_uid") or ""), dependency_hash)
    entity_type = str(entity.get("entity_type") or "unknown")
    writeback_target = _writeback_target_for_entity(entity_type)
    if writeback_target == "character":
        metadata = entity.get("metadata") if isinstance(entity.get("metadata"), dict) else {}
        writeback_fields: dict[str, str] = {
            "name": canonical_name,
            "role": str(metadata.get("role") or ""),
            "profile_text": _facts_summary_text(facts),
        }
        # 结构化提取静态属性字段（仅当 facts 中提取到对应内容时）
        static_attrs = _extract_static_attrs_from_facts(facts)
        if static_attrs:
            writeback_fields.update(static_attrs)
    elif writeback_target == "world_entry":
        writeback_fields = {
            "name": canonical_name,
            "category": entity_type,
            "content_text": _facts_summary_text(facts),
        }
    else:
        writeback_fields = {}
    card_title = f"{canonical_name} 候选卡"
    summary = _summary_from_facts(facts)
    # use_ai=False 时不修改 payload 字段集，保持与历史行为完全一致；
    # use_ai=True 时根据 AI 成功/失败分别标记 ai_llm_card / rule_v1。
    source_rule: str | None = "rule_v1" if use_ai else None
    if use_ai and ai_provider is not None:
        context = _context_from_facts(facts)
        ai_card: dict[str, Any] | None = None
        try:
            ai_card = ai_provider.generate_card_content(
                card_type=card_type,
                entity=entity,
                facts=facts,
                context=context,
                book_id=book_id,
                run_id=run_id,
            )
        except Exception:
            ai_card = None
        if isinstance(ai_card, dict):
            source_rule = "ai_llm_card"
            ai_title = str(ai_card.get("title") or "").strip()
            if ai_title:
                card_title = ai_title
            if writeback_target == "character":
                ai_role = str(ai_card.get("role") or "").strip()
                if ai_role:
                    writeback_fields["role"] = ai_role
                ai_profile = str(ai_card.get("profile_text") or "").strip()
                if ai_profile:
                    writeback_fields["profile_text"] = ai_profile
            elif writeback_target == "world_entry":
                ai_category = str(ai_card.get("category") or "").strip()
                if ai_category:
                    writeback_fields["category"] = ai_category
                ai_content = str(ai_card.get("content_text") or "").strip()
                if ai_content:
                    writeback_fields["content_text"] = ai_content
            ai_summary = str(ai_card.get("summary") or "").strip()
            if ai_summary:
                summary = ai_summary
    payload = {
        "schema_version": "analysis_v3_card_m5",
        "source": "analysis_v3",
        "title": card_title,
        "name": canonical_name,
        "entity_uid": str(entity.get("entity_uid") or ""),
        "entity_type": entity_type,
        "summary": summary,
        "fact_count": len(facts),
        "facts": [_fact_payload(fact) for fact in facts],
        "dependency_hash": dependency_hash,
        "writeback_target": writeback_target,
        "writeback_fields": writeback_fields,
    }
    if source_rule is not None:
        payload["source_rule"] = source_rule
    return AnalysisCardDraft(
        card_uid=card_uid,
        card_type=card_type,
        payload=payload,
        diff=_card_diff(facts, dependency_hash),
        status="draft",
        entity_uid=str(entity.get("entity_uid") or ""),
        ars_score=_average_confidence(facts),
    )


def build_v3_book_card(
    *,
    book_id: int,
    run_id: int,
    facts: list[dict[str, Any]],
    dependency_hash: str,
    use_ai: bool = False,
    ai_provider: Any = None,
) -> AnalysisCardDraft:
    entity_uid = f"BOOK-{int(book_id)}::V3-BOOK-SUMMARY"
    card_type = "v3_book_summary"
    card_uid = _card_uid(book_id, run_id, card_type, entity_uid, dependency_hash)
    card_title = "书籍候选卡"
    summary = _summary_from_facts(facts)
    outline_text = _facts_summary_text(facts, fact_type_filter="foreshadowing") or _facts_summary_text(facts, fact_type_filter="state")
    world_text = _facts_summary_text(facts, fact_type_filter="world_rule") or _facts_summary_text(facts, fact_type_filter="event")
    source_rule: str | None = "rule_v1" if use_ai else None
    if use_ai and ai_provider is not None:
        context = _context_from_facts(facts)
        ai_card: dict[str, Any] | None = None
        try:
            ai_card = ai_provider.generate_card_content(
                card_type=card_type,
                entity={"entity_uid": entity_uid, "entity_type": "book", "canonical_name": "书籍"},
                facts=facts,
                context=context,
                book_id=book_id,
                run_id=run_id,
            )
        except Exception:
            ai_card = None
        if isinstance(ai_card, dict):
            source_rule = "ai_llm_card"
            ai_title = str(ai_card.get("title") or "").strip()
            if ai_title:
                card_title = ai_title
            ai_outline = str(ai_card.get("outline_text") or "").strip()
            if ai_outline:
                outline_text = ai_outline
            ai_world = str(ai_card.get("world_text") or "").strip()
            if ai_world:
                world_text = ai_world
            ai_summary = str(ai_card.get("summary") or "").strip()
            if ai_summary:
                summary = ai_summary
    payload = {
        "schema_version": "analysis_v3_card_m5",
        "source": "analysis_v3",
        "title": card_title,
        "entity_uid": entity_uid,
        "entity_type": "book",
        "summary": summary,
        "fact_count": len(facts),
        "facts": [_fact_payload(fact) for fact in facts[:40]],
        "dependency_hash": dependency_hash,
        "writeback_target": "book",
        "writeback_fields": {
            "outline_text": outline_text,
            "world_text": world_text,
        },
    }
    if source_rule is not None:
        payload["source_rule"] = source_rule
    return AnalysisCardDraft(
        card_uid=card_uid,
        card_type=card_type,
        payload=payload,
        diff=_card_diff(facts, dependency_hash),
        status="draft",
        entity_uid=entity_uid,
        ars_score=_average_confidence(facts),
    )


def _card_uid(book_id: int, run_id: int, card_type: str, entity_uid: str, dependency_hash: str) -> str:
    seed = "|".join([str(book_id), str(run_id), card_type, entity_uid, dependency_hash])
    return f"CARD-V3-{stable_hash(seed)[:16]}"


def _fact_payload(fact: dict[str, Any]) -> dict[str, Any]:
    value = fact.get("value") if isinstance(fact.get("value"), dict) else {}
    return {
        "fact_uid": str(fact.get("fact_uid") or ""),
        "fact_type": str(fact.get("fact_type") or "event"),
        "summary": html.escape(str(value.get("summary") or fact.get("quote_text") or "")[:220]),
        "quote_text": str(fact.get("quote_text") or ""),
        "chapter_id": fact.get("chapter_id"),
        "block_uid": str(fact.get("block_uid") or ""),
        "confidence": float(fact.get("confidence") or 0.0),
    }


def _card_diff(facts: list[dict[str, Any]], dependency_hash: str) -> dict[str, Any]:
    return {
        "v3_candidate": True,
        "applyable": False,
        "reason": "M5 V3 card candidates are review-only and do not write formal settings.",
        "dependency_hash": dependency_hash,
        "fact_uids": [str(fact.get("fact_uid") or "") for fact in facts],
        "evidence_refs": [
            {
                "fact_uid": str(fact.get("fact_uid") or ""),
                "block_uid": str(fact.get("block_uid") or ""),
                "quote_text": str(fact.get("quote_text") or ""),
            }
            for fact in facts
        ],
        "notes": ["Generated from Analysis V3 atomic facts; formal writeback remains disabled in M5."],
    }


def _summary_from_facts(facts: list[dict[str, Any]]) -> str:
    snippets: list[str] = []
    for fact in facts[:5]:
        value = fact.get("value") if isinstance(fact.get("value"), dict) else {}
        text = str(value.get("summary") or fact.get("quote_text") or "").strip()
        if text and text not in snippets:
            snippets.append(html.escape(text[:120]))
    return "；".join(snippets)


def _average_confidence(facts: list[dict[str, Any]]) -> float:
    if not facts:
        return 0.0
    return round(sum(float(fact.get("confidence") or 0.0) for fact in facts) / len(facts), 3)


def _facts_summary_text(facts: list[dict[str, Any]], fact_type_filter: str | None = None) -> str:
    """从 facts 中提取摘要文本，可选按 fact_type 过滤。"""
    snippets: list[str] = []
    for fact in facts:
        if fact_type_filter is not None:
            ft = str(fact.get("fact_type") or "")
            if fact_type_filter not in ft:
                continue
        value = fact.get("value") if isinstance(fact.get("value"), dict) else {}
        text = str(value.get("summary") or fact.get("quote_text") or "").strip()
        if text and text not in snippets:
            snippets.append(html.escape(text[:200]))
    return "；".join(snippets)


_STATIC_ATTR_KEYWORDS: dict[str, list[str]] = {
    "alias": ["alias", "别名", "称号", "绰号"],
    "age": ["age", "年龄", "岁数"],
    "gender": ["gender", "性别", "男女"],
    "appearance_keywords": ["appearance", "外貌", "形象", "外形", "容貌"],
    "signature_feature": ["signature_feature", "标志", "特征", "伤疤", "纹身", "饰品", "口癖"],
    "identity_occupation": ["identity", "身份", "职业", "职务", "职位"],
}


def _extract_static_attrs_from_facts(facts: list[dict[str, Any]]) -> dict[str, str]:
    """从 facts 中按关键词匹配提取静态属性字段，返回 dict 仅含匹配到的字段。

    关键词与 state_machine_writeback.py 的 _FACT_TO_AXIS_MAP 一致；
    fact 文本字段提取与 _facts_summary_text 保持一致。
    """
    result: dict[str, str] = {}
    for fact in facts:
        fact_type = str(fact.get("fact_type") or "").lower()
        if not fact_type:
            continue
        value = fact.get("value") if isinstance(fact.get("value"), dict) else {}
        fact_summary = str(value.get("summary") or fact.get("quote_text") or "").strip()
        if not fact_summary:
            continue
        for field_id, keywords in _STATIC_ATTR_KEYWORDS.items():
            if any(kw.lower() in fact_type for kw in keywords):
                if field_id not in result:
                    result[field_id] = fact_summary
                break
    return result


def _context_from_facts(facts: list[dict[str, Any]], max_chars: int = 2000) -> str:
    """从 facts 的 quote_text 拼接一段上下文，最多 max_chars 字。

    用于 AI 卡片生成时提供原文上下文，提升生成质量。
    """
    snippets: list[str] = []
    total = 0
    for fact in facts:
        quote = str(fact.get("quote_text") or "").strip()
        if not quote:
            continue
        if total + len(quote) > max_chars:
            remaining = max_chars - total
            if remaining <= 0:
                break
            snippets.append(quote[:remaining])
            break
        snippets.append(quote)
        total += len(quote)
    return "\n".join(snippets)


def _writeback_target_for_entity(entity_type: str) -> str:
    """根据 entity_type 决定 writeback_target。"""
    if entity_type == "character":
        return "character"
    # 组织、地点、概念、物品 → 全部归入世界观条目
    if entity_type in ("world_setting", "location", "concept", "organization", "item"):
        return "world_entry"
    return "world_entry"  # 兜底：未知类型也写入世界观
