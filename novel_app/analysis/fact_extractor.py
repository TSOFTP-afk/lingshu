from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from novel_app.analysis.schemas_v3 import AtomicFact

FACT_MIN_CONFIDENCE = 0.55
_SENTENCE_BOUNDARY_RE = re.compile(r"[。！？!?；;\n\r]+|(?<!\w\.\w)\.(?:\s|$)")


class FactExtractor:
    def __init__(self, *, min_confidence: float = FACT_MIN_CONFIDENCE) -> None:
        self.min_confidence = max(0.0, min(1.0, float(min_confidence)))
        self._llm_extractor: LLMFactExtractor | None = None

    def enable_llm(self, llm_extractor: LLMFactExtractor) -> None:
        """启用 LLM 增强事实抽取。传入 LLMFactExtractor 实例。"""
        self._llm_extractor = llm_extractor

    def extract_from_context(
        self,
        *,
        book_id: int,
        run_id: int,
        blocks: Iterable[Any],
        mentions: Iterable[dict[str, Any]],
        entities: Iterable[dict[str, Any]],
    ) -> list[AtomicFact]:
        block_by_uid = {_text_key(block, "block_uid"): _row_dict(block) for block in blocks}
        entity_by_uid = {_text_key(entity, "entity_uid"): dict(entity) for entity in entities}
        by_uid: dict[str, AtomicFact] = {}

        for mention in mentions:
            mention_data = dict(mention)
            subject_entity_uid = str(mention_data.get("entity_uid") or "").strip()
            if not subject_entity_uid or subject_entity_uid not in entity_by_uid:
                continue
            confidence = self._fact_confidence(mention_data, entity_by_uid[subject_entity_uid])
            if confidence < self.min_confidence:
                continue
            block = block_by_uid.get(str(mention_data.get("block_uid") or ""))
            if not block:
                continue
            fact = self._fact_from_mention(
                book_id=book_id,
                run_id=run_id,
                block=block,
                mention=mention_data,
                entity=entity_by_uid[subject_entity_uid],
                confidence=confidence,
            )
            if fact and fact.fact_uid not in by_uid:
                by_uid[fact.fact_uid] = fact

        # LLM 增强抽取：对规则未覆盖的 block 调用 LLM 补充
        if self._llm_extractor is not None:
            llm_facts = self._llm_extractor.extract(
                book_id=book_id,
                run_id=run_id,
                blocks=list(blocks),
                mentions=list(mentions),
                entities=list(entities),
                existing_facts=dict(by_uid),
            )
            for fact in llm_facts:
                if fact.fact_uid not in by_uid:
                    by_uid[fact.fact_uid] = fact

        return sorted(by_uid.values(), key=lambda item: (item.chapter_id or 0, item.block_uid, item.fact_uid))

    def _fact_from_mention(
        self,
        *,
        book_id: int,
        run_id: int,
        block: dict[str, Any],
        mention: dict[str, Any],
        entity: dict[str, Any],
        confidence: float,
    ) -> AtomicFact | None:
        text = str(block.get("text") or "")
        if not text:
            return None
        local_span = _mention_local_span(block, mention, text)
        if local_span is None:
            return None
        quote_start, quote_end = _sentence_span(text, local_span[0], local_span[1])
        quote_text = text[quote_start:quote_end].strip()
        if not quote_text or quote_text not in text:
            return None
        if str(mention.get("quote_text") or "").strip() not in quote_text:
            return None
        absolute_start = _int(block.get("char_start"), 0) + quote_start
        absolute_end = _int(block.get("char_start"), 0) + quote_end
        fact_type = _fact_type(quote_text)
        subject_name = str(entity.get("canonical_name") or mention.get("quote_text") or "").strip()
        return AtomicFact.create(
            book_id=book_id,
            run_id=run_id,
            subject_entity_uid=str(entity.get("entity_uid") or ""),
            fact_type=fact_type,
            value={
                "summary": quote_text[:180],
                "subject_name": subject_name,
                "subject_entity_type": str(entity.get("entity_type") or mention.get("entity_type") or "unknown"),
                "mention_uid": str(mention.get("mention_uid") or ""),
            },
            quote_text=quote_text,
            chapter_id=_int_or_none(block.get("chapter_id")),
            block_uid=str(block.get("block_uid") or ""),
            char_start=absolute_start,
            char_end=absolute_end,
            confidence=confidence,
            source_rule="sentence_with_entity_mention",
            metadata={
                "block_local_start": quote_start,
                "block_local_end": quote_end,
                "mention_uid": str(mention.get("mention_uid") or ""),
                "mention_quote": str(mention.get("quote_text") or ""),
                "mention_source_rule": str(mention.get("source_rule") or ""),
                "entity_confidence": float(entity.get("confidence") or 0.0),
                "mention_confidence": float(mention.get("confidence") or 0.0),
            },
        )

    @staticmethod
    def _fact_confidence(mention: dict[str, Any], entity: dict[str, Any]) -> float:
        mention_confidence = float(mention.get("confidence") or 0.0)
        entity_confidence = float(entity.get("confidence") or 0.0)
        confidence = (mention_confidence * 0.75) + (entity_confidence * 0.25)
        return round(max(0.0, min(0.92, confidence)), 3)


def _mention_local_span(block: dict[str, Any], mention: dict[str, Any], text: str) -> tuple[int, int] | None:
    block_start = _int(block.get("char_start"), 0)
    local_start = _int(mention.get("char_start"), 0) - block_start
    local_end = _int(mention.get("char_end"), 0) - block_start
    quote = str(mention.get("quote_text") or "")
    if 0 <= local_start < local_end <= len(text) and text[local_start:local_end] == quote:
        return local_start, local_end
    fallback = text.find(quote)
    if fallback >= 0 and quote:
        return fallback, fallback + len(quote)
    return None


def _sentence_span(text: str, local_start: int, local_end: int) -> tuple[int, int]:
    left = 0
    for match in _SENTENCE_BOUNDARY_RE.finditer(text[:local_start]):
        left = match.end()
    right = len(text)
    match = _SENTENCE_BOUNDARY_RE.search(text, max(local_end, 0))
    if match:
        right = match.end()
    while left < right and text[left].isspace():
        left += 1
    while right > left and text[right - 1].isspace():
        right -= 1
    if right - left > 260:
        right = min(len(text), local_end + 160)
        left = max(0, local_start - 80)
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
    return left, right


def _fact_type(quote_text: str) -> str:
    text = quote_text.lower()
    if any(token in text for token in ("伏笔", "线索", "clue", "hint", "secret")):
        return "foreshadowing"
    if any(token in text for token in ("遇见", "相遇", "帮助", "追随", "背叛", "结盟", "meets", "helps", "betrays")):
        return "relation"
    if any(token in text for token in ("获得", "得到", "取得", "拿到", "gains", "gets", "obtains", "marks")):
        return "event"
    if any(token in text for token in ("进入", "前往", "来到", "抵达", "离开", "enters", "arrives", "leaves")):
        return "event"
    if any(token in text for token in ("是", "为", "成为", "身份", "境界", "受伤", "死亡", "becomes", " is ", " was ")):
        return "state"
    if any(token in text for token in ("规则", "法则", "体系", "rule", "system")):
        return "world_rule"
    return "event"


def _row_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return dict(value)


def _text_key(value: Any, key: str) -> str:
    row = _row_dict(value)
    return str(row.get(key) or "")


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _int_or_none(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


class LLMFactExtractor:
    """LLM 增强原子事实抽取的抽象基类。

    子类需要实现 `extract()` 方法，调用 LLM 对文本块进行事实抽取，
    返回 AtomicFact 列表。LLM 抽取结果只进候选池，不直接写入正式层。

    使用方式：
        extractor = FactExtractor()
        extractor.enable_llm(MyLLMFactExtractor(ai_service, llm_cache))
        facts = extractor.extract_from_context(...)
    """

    def extract(
        self,
        *,
        book_id: int,
        run_id: int,
        blocks: list[Any],
        mentions: list[Any],
        entities: list[Any],
        existing_facts: dict[str, AtomicFact],
    ) -> list[AtomicFact]:
        """调用 LLM 对 blocks 进行事实抽取，返回新的候选列表。

        默认实现返回空列表（不调用 LLM）。子类应重写此方法。
        """
        return []
