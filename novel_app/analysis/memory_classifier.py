from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from novel_app.analysis.memory_window import MemoryWindowBuilder

logger = logging.getLogger(__name__)

FOUNDATION_FACT_TYPES = {"world_rule", "state"}
HIGH_IMPORTANCE_FACT_TYPES = {"foreshadowing", "world_rule", "relation", "state"}
CACHEABLE_FACT_TYPES = {"event", "relation"}

# ARS 四维评分权重
_ARS_WEIGHTS = {
    "narrative_weight": 0.30,
    "entity_centrality": 0.25,
    "novelty_factor": 0.25,
    "causal_impact": 0.20,
}

# ARS 重要记忆阈值
_ARS_IMPORTANCE_THRESHOLD = 0.70

# 稀释记忆 TTL（天）
_DILUTED_TTL_DAYS = 90


class MemoryClassifier:
    def __init__(self, *, short_term_chapter_window: int = 3, use_ai: bool = False, ai_provider: Any = None) -> None:
        self.window_builder = MemoryWindowBuilder(short_term_chapter_window=short_term_chapter_window)
        self.use_ai = use_ai
        self.ai_provider = ai_provider
        self._last_engine: str = "rule"

    def classify_facts(self, facts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        source = [dict(fact) for fact in facts if str(fact.get("fact_uid") or "").strip()]
        window = self.window_builder.build(source)

        # AI 分支：尝试用 AI 评分覆盖 ARS 评分；失败时回退到 ARS
        ai_scores_map: dict[str, dict[str, Any]] = {}
        if self.use_ai and self.ai_provider is not None:
            try:
                context = self._build_context(source)
                ai_scores = self.ai_provider.score_memory_importance(
                    facts=list(source), context=context, book_id=0, run_id=0,
                )
                if ai_scores:
                    for item in ai_scores:
                        fact_uid = str(item.get("fact_uid") or "")
                        if fact_uid:
                            ai_scores_map[fact_uid] = item
                    self._last_engine = "ai"
                else:
                    self._last_engine = "rule"
            except Exception as exc:
                logger.warning("AI score_memory_importance failed, falling back to ARS: %s", exc)
                self._last_engine = "rule"
        else:
            self._last_engine = "rule"

        classified: list[dict[str, Any]] = []
        for fact in source:
            next_fact = dict(fact)
            fact_type = str(next_fact.get("fact_type") or "event")
            confidence = _float(next_fact.get("confidence"), 0.0)
            chapter_id = _int_or_none(next_fact.get("chapter_id"))
            memory_scope = "short_term" if window.contains_chapter(chapter_id) else "long_term"

            # ARS 四维评分（始终计算，用于回退与 metadata 记录）
            ars = self._ars_score(next_fact, source, window)
            memory_importance = self._importance_from_ars(ars, fact_type, confidence)
            memory_type = self._memory_type(fact_type, memory_scope, memory_importance)
            importance_score = ars["final_score"]

            # AI 评分覆盖 ARS 评分（仅在匹配到 AI 评分时）
            fact_uid = str(next_fact.get("fact_uid") or "")
            if fact_uid in ai_scores_map:
                ai_item = ai_scores_map[fact_uid]
                memory_level = str(ai_item.get("memory_level") or "")
                ai_importance_score = _float(ai_item.get("importance_score"), importance_score)
                # memory_level 映射：hot/warm → high/normal, cold/archive → low
                if memory_level == "hot":
                    memory_importance = "high"
                elif memory_level == "warm":
                    memory_importance = "normal"
                elif memory_level in {"cold", "archive"}:
                    memory_importance = "low"
                importance_score = ai_importance_score
                # 基于新的重要性重新计算 memory_type（cache/evidence 可能因重要性变化而切换）
                memory_type = self._memory_type(fact_type, memory_scope, memory_importance)

            metadata = dict(next_fact.get("metadata") if isinstance(next_fact.get("metadata"), dict) else {})
            metadata["memory_classification"] = {
                "classifier": "ars_v2",
                "engine": self._last_engine,
                "latest_chapter_id": window.latest_chapter_id,
                "short_term_chapter_ids": list(window.short_term_chapter_ids),
                "never_compress": self.never_compress(next_fact),
                "ars_scores": ars,
            }
            next_fact.update(
                {
                    "memory_scope": memory_scope,
                    "memory_importance": memory_importance,
                    "memory_type": memory_type,
                    "importance_score": importance_score,
                    "is_foreshadowing": 1 if fact_type == "foreshadowing" else 0,
                    "is_compressible": 0 if self.never_compress(next_fact) else 1,
                    "metadata": metadata,
                }
            )

            # TTL：稀释记忆设置过期天数
            if memory_importance == "low":
                next_fact["ttl_days"] = _DILUTED_TTL_DAYS

            # 短期记忆降级章节号
            if memory_scope == "short_term" and window.short_term_chapter_ids:
                next_fact["memory_expires_at_chapter"] = min(window.short_term_chapter_ids)

            classified.append(next_fact)
        return classified

    @staticmethod
    def _build_context(facts: list[dict[str, Any]]) -> str:
        """从 facts 的 quote_text 拼接上下文（最多 2000 字）。"""
        parts: list[str] = []
        total = 0
        for fact in facts:
            quote = str(fact.get("quote_text") or "").strip()
            if not quote:
                continue
            if total + len(quote) > 2000:
                remaining = 2000 - total
                if remaining > 0:
                    parts.append(quote[:remaining])
                break
            parts.append(quote)
            total += len(quote)
        return " / ".join(parts)

    @staticmethod
    def never_compress(fact: dict[str, Any]) -> bool:
        fact_type = str(fact.get("fact_type") or "")
        memory_type = str(fact.get("memory_type") or "")
        return fact_type == "foreshadowing" or memory_type == "foundation" or fact_type in FOUNDATION_FACT_TYPES

    # ------------------------------------------------------------------
    # ARS 四维评分
    # ------------------------------------------------------------------

    @staticmethod
    def _ars_score(
        fact: dict[str, Any],
        all_facts: list[dict[str, Any]],
        window: Any,
    ) -> dict[str, float]:
        """ARS (Analysis Relevance Score) 四维评分。

        narrative_weight: 是否改变角色状态/关系/世界状态
        entity_centrality: 涉及实体的重要程度
        novelty_factor: 是否首次出现或显著不同
        causal_impact: 是否被后续事件引用
        """
        fact_type = str(fact.get("fact_type") or "event")
        confidence = _float(fact.get("confidence"), 0.0)
        subject_uid = str(fact.get("subject_entity_uid") or "")
        chapter_id = _int_or_none(fact.get("chapter_id"))
        quote_text = str(fact.get("quote_text") or "")

        # 1. narrative_weight: 事实类型 + 置信度
        narrative_weight = confidence * 0.5
        if fact_type in {"foreshadowing", "world_rule", "relation"}:
            narrative_weight += 0.35
        elif fact_type == "state":
            narrative_weight += 0.25
        elif fact_type == "event":
            narrative_weight += 0.10
        # 长引用文本通常包含更多叙事信息
        if len(quote_text) > 100:
            narrative_weight += 0.10
        narrative_weight = min(1.0, narrative_weight)

        # 2. entity_centrality: 实体在全书中的出现频率
        entity_mention_counts: dict[str, int] = {}
        for f in all_facts:
            uid = str(f.get("subject_entity_uid") or "")
            if uid:
                entity_mention_counts[uid] = entity_mention_counts.get(uid, 0) + 1
        if subject_uid and entity_mention_counts:
            max_mentions = max(entity_mention_counts.values())
            entity_mentions = entity_mention_counts.get(subject_uid, 0)
            entity_centrality = min(1.0, entity_mentions / max(1, max_mentions)) * 0.7 + 0.3
        else:
            entity_centrality = 0.3

        # 3. novelty_factor: 该实体的此类型事实是否首次出现
        seen_types_for_entity: set[str] = set()
        entity_first_chapter: dict[str, int] = {}
        for f in all_facts:
            uid = str(f.get("subject_entity_uid") or "")
            ft = str(f.get("fact_type") or "")
            f_chapter = _int_or_none(f.get("chapter_id")) or 0
            if uid == subject_uid:
                seen_types_for_entity.add(ft)
                if uid not in entity_first_chapter or f_chapter < entity_first_chapter[uid]:
                    entity_first_chapter[uid] = f_chapter
        if fact_type not in seen_types_for_entity or len(seen_types_for_entity) <= 1:
            novelty_factor = 0.85
        elif chapter_id is not None and subject_uid in entity_first_chapter:
            first_ch = entity_first_chapter[subject_uid]
            distance = abs((chapter_id or 0) - first_ch)
            novelty_factor = max(0.3, 1.0 - distance * 0.05)
        else:
            novelty_factor = 0.5

        # 4. causal_impact: 该事实的 block_uid 是否被其他事实引用
        block_uid = str(fact.get("block_uid") or "")
        causal_impact = 0.3
        if block_uid:
            ref_count = sum(
                1 for f in all_facts
                if str(f.get("block_uid") or "") == block_uid
                and str(f.get("fact_uid") or "") != str(fact.get("fact_uid") or "")
            )
            causal_impact = min(1.0, 0.3 + ref_count * 0.15)

        final_score = (
            _ARS_WEIGHTS["narrative_weight"] * narrative_weight
            + _ARS_WEIGHTS["entity_centrality"] * entity_centrality
            + _ARS_WEIGHTS["novelty_factor"] * novelty_factor
            + _ARS_WEIGHTS["causal_impact"] * causal_impact
        )
        final_score = round(max(0.0, min(1.0, final_score)), 3)

        return {
            "narrative_weight": round(narrative_weight, 3),
            "entity_centrality": round(entity_centrality, 3),
            "novelty_factor": round(novelty_factor, 3),
            "causal_impact": round(causal_impact, 3),
            "final_score": final_score,
        }

    @staticmethod
    def _importance_from_ars(ars: dict[str, float], fact_type: str, confidence: float) -> str:
        """基于 ARS 四维评分判定重要性。"""
        final_score = ars.get("final_score", 0.0)
        if fact_type in HIGH_IMPORTANCE_FACT_TYPES:
            return "high"
        if final_score >= _ARS_IMPORTANCE_THRESHOLD:
            return "high"
        if final_score < 0.35 and confidence < 0.62:
            return "low"
        return "normal"

    @staticmethod
    def _memory_type(fact_type: str, memory_scope: str, memory_importance: str) -> str:
        if fact_type in FOUNDATION_FACT_TYPES:
            return "foundation"
        if fact_type == "foreshadowing":
            return "evidence"
        if memory_scope == "long_term" and fact_type in CACHEABLE_FACT_TYPES and memory_importance != "high":
            return "cache"
        return "evidence"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_or_none(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None
