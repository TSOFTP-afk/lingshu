from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Iterable
from typing import Any, Callable

from novel_app.analysis.memory_classifier import MemoryClassifier
from novel_app.analysis.schemas_v3 import stable_hash

logger = logging.getLogger(__name__)

DEFAULT_CACHE_COMPRESSION_THRESHOLD = 3
# 记忆压缩 AI 调用的单次超时（秒）。远小于通用 300s，因为压缩是轻量任务。
MEMORY_COMPRESS_AI_TIMEOUT = 90
# 记忆压缩所有分组的 AI 累计时间预算（秒）。超过后剩余分组跳过（AI 模式不回退规则）。
MEMORY_COMPRESS_AI_BUDGET = 600.0
# 并行压缩的线程数
MEMORY_COMPRESS_PARALLEL_WORKERS = 6


class MemoryCompressor:
    def __init__(self, *, cache_threshold: int = DEFAULT_CACHE_COMPRESSION_THRESHOLD, use_ai: bool = False, ai_provider: Any = None) -> None:
        self.cache_threshold = max(2, int(cache_threshold))
        self.use_ai = use_ai
        self.ai_provider = ai_provider
        self._last_engine: str = "rule"
        self._ai_time_used: float = 0.0
        self._ai_budget_lock = threading.Lock()

    def compress(self, facts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """同步压缩（向后兼容，供 backtrack 等同步调用）。

        返回 [*source, *summaries]。
        AI 模式下若失败则该组跳过（不回退规则），仅 use_ai=False 时用规则。
        """
        # 每次调用重置 AI 预算计时器，避免跨 run 累积
        with self._ai_budget_lock:
            self._ai_time_used = 0.0
        source = [dict(fact) for fact in facts if str(fact.get("fact_uid") or "").strip()]
        summaries = self._compress_groups(
            source,
            use_ai=self.use_ai,
            on_group_done=None,
        )
        self._last_engine = "ai" if self.use_ai and self.ai_provider is not None and any(
            str(s.get("metadata", {}).get("compress_engine")) == "ai" for s in summaries
        ) else "rule"
        return [*source, *summaries]

    def compress_parallel(
        self,
        facts: Iterable[dict[str, Any]],
        *,
        use_ai: bool = False,
        on_group_done: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[dict[str, Any]]:
        """并行压缩多组，返回 summaries 列表（不含原始 facts）。

        - 用 ThreadPoolExecutor 并行压缩多个分组
        - AI 模式下不回退规则：AI 失败的组跳过，不生成 summary
        - 每组完成立即调用 on_group_done 回调（流式写回）
        """
        # 每次调用重置 AI 预算计时器，避免跨 run 累积
        with self._ai_budget_lock:
            self._ai_time_used = 0.0
        source = [dict(fact) for fact in facts if str(fact.get("fact_uid") or "").strip()]
        summaries = self._compress_groups(
            source,
            use_ai=use_ai,
            on_group_done=on_group_done,
        )
        self._last_engine = "ai" if use_ai and self.ai_provider is not None and any(
            str(s.get("metadata", {}).get("compress_engine")) == "ai" for s in summaries
        ) else "rule"
        return summaries

    # ------------------------------------------------------------------
    # 内部：分组 + 并行压缩
    # ------------------------------------------------------------------

    def _compress_groups(
        self,
        source: list[dict[str, Any]],
        *,
        use_ai: bool,
        on_group_done: Callable[[dict[str, Any]], None] | None,
    ) -> list[dict[str, Any]]:
        by_group: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        existing_summary_uids = {str(fact.get("fact_uid") or "") for fact in source if str(fact.get("fact_type") or "") == "memory_summary"}
        for fact in source:
            if not self._compressible(fact):
                continue
            by_group[(str(fact.get("subject_entity_uid") or ""), str(fact.get("fact_type") or "event"))].append(fact)

        # 筛选待压缩的分组
        pending: list[tuple[str, str, list[dict[str, Any]]]] = []
        for (entity_uid, fact_type), group in sorted(by_group.items()):
            if len(group) < self.cache_threshold:
                continue
            source_fact_uids = sorted({str(fact.get("fact_uid") or "") for fact in group if str(fact.get("fact_uid") or "")})
            summary_uid = f"FACT-MEMCACHE-{stable_hash('|'.join([entity_uid, fact_type, *source_fact_uids]))[:16]}"
            if summary_uid in existing_summary_uids:
                continue
            pending.append((entity_uid, fact_type, group))

        if not pending:
            return []

        # 小规模分组直接串行；大规模分组并行
        if len(pending) <= 2 or (not use_ai and on_group_done is None):
            summaries: list[dict[str, Any]] = []
            for entity_uid, fact_type, group in pending:
                summary = self._compress_one_group(entity_uid, fact_type, group, use_ai=use_ai)
                if summary:
                    summaries.append(summary)
                    if on_group_done:
                        try:
                            on_group_done(summary)
                        except Exception as exc:
                            logger.warning("on_group_done callback failed: %s", exc)
            return summaries

        # 并行压缩
        summaries: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=MEMORY_COMPRESS_PARALLEL_WORKERS) as executor:
            future_to_group = {
                executor.submit(self._compress_one_group, entity_uid, fact_type, group, use_ai): (entity_uid, fact_type, group)
                for entity_uid, fact_type, group in pending
            }
            for future in concurrent.futures.as_completed(future_to_group):
                entity_uid, fact_type, group = future_to_group[future]
                try:
                    summary = future.result()
                except Exception as exc:
                    logger.warning("compress group failed (entity=%s type=%s): %s", entity_uid, fact_type, exc)
                    summary = None
                if summary:
                    summaries.append(summary)
                    if on_group_done:
                        try:
                            on_group_done(summary)
                        except Exception as exc:
                            logger.warning("on_group_done callback failed: %s", exc)
        return summaries

    def _compress_one_group(
        self,
        entity_uid: str,
        fact_type: str,
        group: list[dict[str, Any]],
        *,
        use_ai: bool,
    ) -> dict[str, Any] | None:
        """压缩单个分组。AI 模式下失败则返回 None（不回退规则）。"""
        source_fact_uids = sorted({str(fact.get("fact_uid") or "") for fact in group if str(fact.get("fact_uid") or "")})
        summary_uid = f"FACT-MEMCACHE-{stable_hash('|'.join([entity_uid, fact_type, *source_fact_uids]))[:16]}"
        source_quotes = [str(fact.get("quote_text") or "").strip() for fact in group if str(fact.get("quote_text") or "").strip()]
        subject_name = _subject_name(group)

        compress_engine = "rule"
        summary_text = ""

        if use_ai and self.ai_provider is not None:
            # 检查 AI 预算（线程安全）
            with self._ai_budget_lock:
                if self._ai_time_used >= MEMORY_COMPRESS_AI_BUDGET:
                    logger.info(
                        "Memory compress AI budget exhausted (%.1fs/%.1fs), skipping group (entity=%s type=%s)",
                        self._ai_time_used, MEMORY_COMPRESS_AI_BUDGET, entity_uid, fact_type,
                    )
                    return None  # AI 模式不回退规则，预算耗尽则跳过

            t0 = time.monotonic()
            try:
                ai_summary = self.ai_provider.compress_memory(
                    facts=list(group), target_ratio=0.3, book_id=0, run_id=0,
                    timeout=MEMORY_COMPRESS_AI_TIMEOUT,
                )
                elapsed = time.monotonic() - t0
                with self._ai_budget_lock:
                    self._ai_time_used += elapsed

                if ai_summary and isinstance(ai_summary, str) and ai_summary.strip():
                    summary_text = ai_summary.strip()
                    compress_engine = "ai"
                else:
                    # AI 返回空结果，不回退规则，跳过该组
                    logger.info("AI compress_memory returned empty for entity=%s type=%s, skipping", entity_uid, fact_type)
                    return None
            except Exception as exc:
                elapsed = time.monotonic() - t0
                with self._ai_budget_lock:
                    self._ai_time_used += elapsed
                # AI 失败不回退规则，跳过该组
                logger.warning("AI compress_memory failed, skipping group (entity=%s type=%s): %s", entity_uid, fact_type, exc)
                return None
        else:
            # 非 AI 模式：规则机械拼接
            summary_text = f"{subject_name} has {len(group)} cached {fact_type} memories."
            if source_quotes:
                summary_text += " " + " / ".join(quote[:80] for quote in source_quotes[:3])

        return {
            "fact_uid": summary_uid,
            "subject_entity_uid": entity_uid,
            "fact_type": "memory_summary",
            "value": {
                "summary": summary_text,
                "subject_name": subject_name,
                "source_fact_uids": source_fact_uids,
                "source_fact_type": fact_type,
            },
            "quote_text": summary_text,
            "chapter_id": _latest_chapter_id(group),
            "block_uid": str(group[-1].get("block_uid") or ""),
            "confidence": round(sum(float(fact.get("confidence") or 0.0) for fact in group) / len(group), 3),
            "memory_scope": "long_term",
            "memory_importance": "normal",
            "memory_type": "summary_cache",
            "importance_score": round(max(float(fact.get("importance_score") or 0.0) for fact in group), 3),
            "status": "candidate",
            "metadata": {
                "source_rule": "memory_cache_compression",
                "compress_engine": compress_engine,
                "source_fact_uids": source_fact_uids,
                "source_fact_count": len(group),
                "never_compress": False,
            },
        }

    @staticmethod
    def _compressible(fact: dict[str, Any]) -> bool:
        if MemoryClassifier.never_compress(fact):
            return False
        if str(fact.get("fact_type") or "") == "memory_summary":
            return False
        return str(fact.get("memory_type") or "") == "cache" and str(fact.get("memory_scope") or "") == "long_term"


def _subject_name(facts: list[dict[str, Any]]) -> str:
    for fact in facts:
        value = fact.get("value") if isinstance(fact.get("value"), dict) else {}
        name = str(value.get("subject_name") or "").strip()
        if name:
            return name
    return str(facts[0].get("subject_entity_uid") or "entity")


def _latest_chapter_id(facts: list[dict[str, Any]]) -> int | None:
    chapter_ids = []
    for fact in facts:
        try:
            chapter_id = int(fact.get("chapter_id") or 0)
        except (TypeError, ValueError):
            chapter_id = 0
        if chapter_id > 0:
            chapter_ids.append(chapter_id)
    return max(chapter_ids) if chapter_ids else None
