"""pipeline_v3 各分析阶段的执行逻辑。

包含 AnalysisPipelineV3 的各阶段方法（mentions/entities/facts/cards/memory/probes）、
向量索引、AI 并行调用、content_hash 过滤等辅助方法。
通过 Mixin 模式被 AnalysisPipelineV3 继承。
"""
from __future__ import annotations

import asyncio
import logging
import concurrent.futures
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from typing import Any

from novel_app.analysis.ai_provider import (
    AIMDConcurrencyController,
    _is_connection_error,
    _is_rate_limit_error,
)
from novel_app.analysis.coreference import CoreferenceResolver
from novel_app.analysis.fact_extractor import FactExtractor
from novel_app.analysis.mention_extractor import MentionExtractor
from novel_app.analysis.probe_executor import ProbeExecutionResult

logger = logging.getLogger(__name__)

AI_MAX_WORKERS = int(os.environ.get("LINGSHU_ANALYSIS_V3_AI_MAX_WORKERS", "425") or 425)
BURST_SUBMIT_CAP = int(os.environ.get("LINGSHU_AI_BURST_SUBMIT_CAP", "8") or 8)
CONTENT_HASH_SKIP = True
COREFERENCE_MENTION_LIMIT = int(os.environ.get("LINGSHU_ANALYSIS_V3_COREFERENCE_MENTION_LIMIT", "2500") or 2500)
COREFERENCE_MENTIONS_PER_NAME_LIMIT = int(os.environ.get("LINGSHU_ANALYSIS_V3_COREFERENCE_MENTIONS_PER_NAME_LIMIT", "30") or 30)


def _adaptive_workers(blocks: list[dict[str, Any]], max_workers: int = AI_MAX_WORKERS) -> int:
    """根据块数量和窗口大小自适应计算最优并发数。

    每个 block 约产生 ceil(chars / AI_TEXT_WINDOW_CHARS) 个窗口，
    每窗口产生 2 次 API 调用（mention + fact）。
    并发数 = min(块数, 上限)，保证小文本不浪费线程，大文本充分利用并行。
    """
    if not blocks:
        return 4
    block_count = len(blocks)
    # 估算总窗口数：每个 block 按文本长度估算
    total_chars = sum(len(str(b.get("text") or "")) for b in blocks)
    window_chars = 12000  # 与 AI_TEXT_WINDOW_CHARS 保持一致
    estimated_windows = max(1, total_chars // window_chars)
    # 并发 = min(块数, 窗口数/4, 上限)，至少 4 个
    workers = max(4, min(block_count, max(4, estimated_windows // 2), max_workers))
    return workers


def run_aimd_pool(
    items: list[Any],
    worker_fn: Any,
    *,
    max_workers: int,
    stage_label: str = "ai_parallel",
    per_call_timeout: float = 300.0,
) -> list[Any]:
    """通用 AIMD 动态并发执行器，保护高 max_workers 下的 AI 批量调用。

    将一批 items 通过 worker_fn(item) 并发执行，使用 AIMDConcurrencyController
    动态管理并发上限（慢启动爬坡 + 三级失败回退），避免一次性提交全部任务
    在 max_workers=425 时打爆 API 连接。

    - 物理上限 max_workers（ThreadPoolExecutor 容量）
    - 逻辑上限由 controller 动态决定（初始保守，成功翻倍爬坡至 ssthresh 后 +1）
    - 失败按 限流(×0.5) / 连接错误(×0.7) / 普通(-1) 三级回退
    worker_fn 返回 None 视为空，返回 list 直接 extend，返回单值包装为单元素列表。
    """
    results: list[Any] = []
    if not items:
        return results
    # 单项或低并发直接串行（保留原 extract_mentions/facts 的批量优化路径）
    if max_workers <= 1 or len(items) == 1:
        for item in items:
            try:
                r = worker_fn(item)
                if r:
                    results.extend(r if isinstance(r, list) else [r])
            except Exception as exc:
                logger.warning("%s single call failed: %s", stage_label, exc)
        return results

    controller = AIMDConcurrencyController(maximum=max_workers)
    pending: set[concurrent.futures.Future] = set()
    submit_times: dict[concurrent.futures.Future, float] = {}
    completed = 0
    total = len(items)
    start = time.monotonic()
    last_log = start
    last_log_conc = controller.current()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        it = iter(items)
        # 初始提交 controller.current() 个任务（慢启动从初始值开始）
        initial_submit = min(controller.current(), total)
        for _ in range(initial_submit):
            try:
                fut = executor.submit(worker_fn, next(it))
                pending.add(fut)
                submit_times[fut] = time.monotonic()
            except StopIteration:
                break

        while pending:
            done, pending = concurrent.futures.wait(
                pending, timeout=1.0, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                completed += 1
                try:
                    r = future.result(timeout=per_call_timeout)
                    if r:
                        results.extend(r if isinstance(r, list) else [r])
                    controller.on_success()
                    submit_t = submit_times.pop(future, None)
                    if submit_t is not None:
                        controller.record_latency(time.monotonic() - submit_t)
                except Exception as exc:
                    controller.on_failure(
                        rate_limited=_is_rate_limit_error(exc),
                        connection_error=_is_connection_error(exc),
                    )
                    submit_times.pop(future, None)
                    logger.warning("%s call failed (%d/%d): %s", stage_label, completed, total, exc)

            # 延迟退化检查：若中位延迟显著恶化则预防性回退
            if controller.check_latency_degrade():
                controller.on_latency_degrade()
                logger.warning("%s latency degraded, backing off concurrency to %d", stage_label, controller.current())

            # 周期性进度日志：每 15s 或并发数变化超过 5 记录一次
            now = time.monotonic()
            cur = controller.current()
            if now - last_log >= 15.0 or abs(cur - last_log_conc) >= 5:
                logger.info(
                    "%s progress: completed %d/%d, pending %d, concurrency %d (peak %d), %.1fs",
                    stage_label, completed, total, len(pending), cur, controller.stats()["peak"], now - start,
                )
                last_log = now
                last_log_conc = cur

            # 按动态并发上限继续提交新任务
            cur_limit = controller.current()
            submitted_this_cycle = 0
            while len(pending) < cur_limit and submitted_this_cycle < BURST_SUBMIT_CAP:
                try:
                    fut = executor.submit(worker_fn, next(it))
                    pending.add(fut)
                    submit_times[fut] = time.monotonic()
                    submitted_this_cycle += 1
                except StopIteration:
                    break

    stats = controller.stats()
    logger.info(
        "%s finished: %d/%d items, concurrency peak=%d (max=%d), "
        "AIMD success=%d failure=%d rate_limited=%d connection_error=%d, "
        "latency_baseline=%s latency_degrade_count=%d, %.1fs",
        stage_label, completed, total, stats["peak"], max_workers,
        stats["success"], stats["failure"], stats["rate_limited"], stats["connection_error"],
        stats["latency_baseline"], stats["latency_degrade_count"],
        time.monotonic() - start,
    )
    return results


def _existing_run_meta(run: Any) -> dict[str, Any]:
    if not run:
        return {}
    try:
        import json
        value = json.loads(str(run["meta_json"] or "{}"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _mention_key(mention: Any) -> tuple[str, str]:
    entity_type = str(mention.get("entity_type") or "unknown") if isinstance(mention, dict) else "unknown"
    text = str((mention.get("normalized_text") or mention.get("quote_text") or "") if isinstance(mention, dict) else "").strip()
    return entity_type, text


def _mention_priority(mention: Any) -> tuple[float, int, int]:
    if not isinstance(mention, dict):
        return (0.0, 0, 0)
    confidence = float(mention.get("confidence") or 0.0)
    chapter_id = int(mention.get("chapter_id") or 0)
    char_start = int(mention.get("char_start") or 0)
    return (-confidence, chapter_id, char_start)


def _limit_coreference_mentions(mentions: list[Any]) -> tuple[list[Any], dict[str, int | bool]]:
    original_count = len(mentions)
    global_limit = max(1, COREFERENCE_MENTION_LIMIT)
    per_name_limit = max(1, COREFERENCE_MENTIONS_PER_NAME_LIMIT)
    buckets: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for mention in mentions:
        buckets[_mention_key(mention)].append(mention)

    limited: list[Any] = []
    for bucket in sorted(buckets.values(), key=lambda items: (-len(items), str(_mention_key(items[0])))):
        limited.extend(sorted(bucket, key=_mention_priority)[:per_name_limit])

    if len(limited) > global_limit:
        limited = sorted(limited, key=_mention_priority)[:global_limit]
    limited = sorted(limited, key=lambda item: (int(item.get("chapter_id") or 0), int(item.get("char_start") or 0), str(item.get("mention_uid") or "")))
    return limited, {
        "coreference_input_capped": len(limited) < original_count,
        "coreference_original_mention_count": original_count,
        "coreference_input_mention_count": len(limited),
        "coreference_distinct_name_count": len(buckets),
        "coreference_mention_limit": global_limit,
        "coreference_mentions_per_name_limit": per_name_limit,
    }


class PipelineV3StagesMixin:
    """各分析阶段的执行方法 Mixin。"""

    database: Any
    store: Any
    entity_store: Any
    fact_store: Any
    memory_classifier: Any
    memory_compressor: Any
    card_coordinator: Any
    ai_provider: Any
    probe_planner: Any
    probe_executor: Any
    vector_store: Any

    def run_entity_mentions(
        self, book_id: int, run_id: int, *,
        blocks: list[dict[str, Any]] | None = None,
        update_run: bool = True, use_ai: bool = False,
        ai_max_workers: int = AI_MAX_WORKERS,
    ) -> int:
        source_blocks = blocks if blocks is not None else [dict(row) for row in self.store.list_blocks(int(book_id), run_id=int(run_id), limit=None)]
        engine = "rule"
        if use_ai and self.ai_provider is not None:
            # AI-only 模式：不再规则先行，直接调用 AI 提取（避免 rule-first merge 导致 mention 爆炸）
            workers = _adaptive_workers(source_blocks, max_workers=ai_max_workers)
            logger.info("M2 mention extraction: %d blocks, ~%d chars, adaptive workers=%d, engine=ai (AI-only mode)",
                        len(source_blocks),
                        sum(len(str(b.get('text') or '')) for b in source_blocks),
                        workers)
            try:
                ai_mentions = self._parallel_ai_extract_mentions(source_blocks, int(book_id), int(run_id), max_workers=workers)
                if ai_mentions:
                    # AI-only：直接使用 AI 结果，不与规则结果合并
                    mentions = ai_mentions
                    engine = "ai"
                else:
                    # AI 返回空，回退到规则提取
                    mentions = self._rule_extract_mentions(int(book_id), int(run_id), source_blocks)
                    engine = "rule_fallback"
            except Exception as exc:
                logger.warning("AI extract_mentions failed, falling back to rule-only extraction: %s", exc)
                mentions = self._rule_extract_mentions(int(book_id), int(run_id), source_blocks)
                engine = "rule_fallback"
        else:
            mentions = self._rule_extract_mentions(int(book_id), int(run_id), source_blocks)
        mention_ids = self.entity_store.replace_mentions(int(book_id), int(run_id), mentions)
        mention_count = len(mention_ids)
        _total_chars = sum(len(str(b.get('text') or '')) for b in source_blocks)
        _density = (mention_count / _total_chars * 1000) if _total_chars > 0 else 0.0
        logger.info("M2 mention extraction finished: %d mentions, density=%.1f/千字, engine=%s",
                    mention_count, _density, engine)
        self._last_mention_engine = engine
        self.store.create_audit_log(
            int(book_id), run_id=int(run_id), action="analysis_v3_mentions_created",
            target_type="analysis_run", target_uid=str(run_id),
            new_value={"mention_count": mention_count, "engine": engine},
            reason=f"analysis v3 m2 entity mention candidates created via {engine}",
        )
        if update_run:
            from novel_app.analysis.pipeline_v3 import PIPELINE_V3_VERSION
            run = self.store.get_run(int(run_id))
            meta = {}
            if run:
                meta = {"pipeline_version": str(run["pipeline_version"] or PIPELINE_V3_VERSION), "semantic_block_count": len(source_blocks)}
            meta.update({"pipeline_family": "analysis_v3", "current_phase": "M2", "current_step": "entity_mentions",
                         "next_step": "entity_coreference", "mention_count": mention_count, "card_count": 0,
                         "ai_invoked": use_ai and self.ai_provider is not None, "engine": engine})
            self.store.update_run_status(int(run_id), "mentions_ready",
                summary=f"Generated {mention_count} entity mention candidates for Analysis V3.", meta=meta)
        return mention_count

    def _rule_extract_mentions(self, book_id: int, run_id: int, blocks: list[dict[str, Any]]) -> list[Any]:
        extractor = MentionExtractor.from_database(self.database, book_id)
        return extractor.extract_from_blocks(book_id=book_id, run_id=run_id, blocks=blocks)

    @staticmethod
    def _merge_rule_and_ai_mentions(
        rule_mentions: list[Any],
        ai_mentions: list[Any],
    ) -> list[Any]:
        """[已弃用] 合并规则和 AI 提取的 mention。

        自 fix-m2-rule-merge-explosion 后，AI 模式下不再调用此函数。
        规则独有 mention 的合并会导致 M3 共指消解批次爆炸。
        保留函数定义仅为向后兼容；如需调用请改用 AI-only + 规则 fallback 策略。

        原合并策略：
        - 以 AI 结果为基础（AI 精度高）
        - 补充规则发现的、AI 未覆盖的 character mention（按 block_uid + char_start + char_end + normalized_text 去重）
        - 同位置取 confidence 更高者
        """
        if not rule_mentions:
            return ai_mentions
        if not ai_mentions:
            return rule_mentions
        # 用 mention 的唯一键去重：block_uid + char_start + char_end + entity_type + normalized_text
        merged: dict[tuple, Any] = {}
        for m in ai_mentions:
            key = (
                str(getattr(m, "block_uid", "") or ""),
                int(getattr(m, "char_start", 0) or 0),
                int(getattr(m, "char_end", 0) or 0),
                str(getattr(m, "entity_type", "") or ""),
                str(getattr(m, "normalized_text", "") or ""),
            )
            merged[key] = m
        rule_only_added = 0
        for m in rule_mentions:
            key = (
                str(getattr(m, "block_uid", "") or ""),
                int(getattr(m, "char_start", 0) or 0),
                int(getattr(m, "char_end", 0) or 0),
                str(getattr(m, "entity_type", "") or ""),
                str(getattr(m, "normalized_text", "") or ""),
            )
            if key not in merged:
                # 规则独有候选，补充进去（尤其是 dialogue_pattern 识别的 character）
                merged[key] = m
                rule_only_added += 1
            else:
                # 同位置取 confidence 更高者
                existing = merged[key]
                existing_conf = float(getattr(existing, "confidence", 0.0) or 0.0)
                new_conf = float(getattr(m, "confidence", 0.0) or 0.0)
                if new_conf > existing_conf:
                    merged[key] = m
        if rule_only_added > 0:
            logger.info("M2 rule-first merge: %d rule-only mentions added (mainly character candidates)", rule_only_added)
        return list(merged.values())

    def run_entity_coreference(
        self, book_id: int, run_id: int, *,
        update_run: bool = True, use_ai: bool = False,
    ) -> int:
        mentions = self.entity_store.list_mentions(int(book_id), run_id=int(run_id), limit=None)
        mentions_for_coreference, limit_meta = _limit_coreference_mentions([dict(item) for item in mentions])
        if limit_meta["coreference_input_capped"]:
            logger.warning(
                "Coreference mention input capped for run_id=%s: %s -> %s",
                run_id,
                limit_meta["coreference_original_mention_count"],
                limit_meta["coreference_input_mention_count"],
            )
            self.store.create_audit_log(
                int(book_id), run_id=int(run_id), action="analysis_v3_coreference_mentions_capped",
                target_type="analysis_run", target_uid=str(run_id),
                new_value=limit_meta,
                reason="analysis v3 m3 coreference input capped to avoid runaway pairwise matching",
            )
        engine = "rule"
        if use_ai and self.ai_provider is not None:
            try:
                entities = self.ai_provider.resolve_coreference(mentions_for_coreference, book_id=int(book_id), run_id=int(run_id))
                if entities:
                    engine = "ai"
                else:
                    entities = CoreferenceResolver(vector_store=self.vector_store).resolve_mentions(book_id=int(book_id), mentions=mentions_for_coreference)
                    engine = "rule_fallback"
            except Exception as exc:
                logger.warning("AI resolve_coreference failed, falling back to rules: %s", exc)
                entities = CoreferenceResolver(vector_store=self.vector_store).resolve_mentions(book_id=int(book_id), mentions=mentions_for_coreference)
                engine = "rule_fallback"
        else:
            entities = CoreferenceResolver(vector_store=self.vector_store).resolve_mentions(book_id=int(book_id), mentions=mentions_for_coreference)
        entity_ids = self.entity_store.replace_entities(int(book_id), int(run_id), entities)
        entity_count = len(entity_ids)
        self._last_coreference_engine = engine
        self.store.create_audit_log(
            int(book_id), run_id=int(run_id), action="analysis_v3_entities_resolved",
            target_type="analysis_run", target_uid=str(run_id),
            new_value={"entity_count": entity_count, "engine": engine},
            reason=f"analysis v3 m3 entity candidates resolved via {engine}",
        )
        if update_run:
            from novel_app.analysis.pipeline_v3 import PIPELINE_V3_VERSION
            run = self.store.get_run(int(run_id))
            meta = {}
            if run:
                current_meta = {}
                try:
                    import json
                    current_meta = json.loads(str(run["meta_json"] or "{}"))
                except Exception:
                    current_meta = {}
                meta = {"pipeline_version": str(run["pipeline_version"] or PIPELINE_V3_VERSION),
                        "semantic_block_count": int(current_meta.get("semantic_block_count") or 0), "mention_count": len(mentions)}
            meta.update({"pipeline_family": "analysis_v3", "current_phase": "M3", "current_step": "entity_coreference",
                         "next_step": "atomic_facts", "entity_count": entity_count, "card_count": 0,
                         "ai_invoked": use_ai and self.ai_provider is not None, "engine": engine, **limit_meta})
            self.store.update_run_status(int(run_id), "entities_ready",
                summary=f"Generated {entity_count} entity candidates for Analysis V3.", meta=meta)
        return entity_count

    def run_atomic_facts(
        self, book_id: int, run_id: int, *,
        blocks: list[dict[str, Any]] | None = None,
        update_run: bool = True, use_ai: bool = False,
        ai_max_workers: int = AI_MAX_WORKERS,
    ) -> int:
        source_blocks = blocks if blocks is not None else [dict(row) for row in self.store.list_blocks(int(book_id), run_id=int(run_id), limit=None)]
        mentions = self.entity_store.list_mentions(int(book_id), run_id=int(run_id), limit=None)
        entities = self.entity_store.list_entities(int(book_id), run_id=int(run_id), limit=None)
        engine = "rule"
        if use_ai and self.ai_provider is not None:
            workers = _adaptive_workers(source_blocks, max_workers=ai_max_workers)
            logger.info("M4 fact extraction: %d blocks, adaptive workers=%d", len(source_blocks), workers)
            try:
                facts = self._parallel_ai_extract_facts(source_blocks, entities, int(book_id), int(run_id), max_workers=workers)
                if facts:
                    engine = "ai"
                else:
                    facts = self._rule_extract_facts(int(book_id), int(run_id), source_blocks, mentions, entities)
                    engine = "rule_fallback"
            except Exception as exc:
                logger.warning("AI extract_facts failed, falling back to rules: %s", exc)
                facts = self._rule_extract_facts(int(book_id), int(run_id), source_blocks, mentions, entities)
                engine = "rule_fallback"
        else:
            facts = self._rule_extract_facts(int(book_id), int(run_id), source_blocks, mentions, entities)
        fact_ids = self.fact_store.replace_facts(int(book_id), int(run_id), facts)
        fact_count = len(fact_ids)
        self._last_facts_engine = engine
        self.store.create_audit_log(
            int(book_id), run_id=int(run_id), action="analysis_v3_facts_created",
            target_type="analysis_run", target_uid=str(run_id),
            new_value={"fact_count": fact_count, "engine": engine},
            reason=f"analysis v3 m4 atomic fact candidates created via {engine}",
        )
        if update_run:
            from novel_app.analysis.pipeline_v3 import PIPELINE_V3_VERSION
            run = self.store.get_run(int(run_id))
            meta = _existing_run_meta(run)
            meta.update({"pipeline_version": str(run["pipeline_version"] or PIPELINE_V3_VERSION) if run else PIPELINE_V3_VERSION,
                         "pipeline_family": "analysis_v3", "current_phase": "M4", "current_step": "atomic_facts",
                         "next_step": "card_events", "semantic_block_count": len(source_blocks),
                         "mention_count": len(mentions), "entity_count": len(entities), "fact_count": fact_count,
                         "card_count": 0, "ai_invoked": use_ai and self.ai_provider is not None, "engine": engine})
            self.store.update_run_status(int(run_id), "facts_ready",
                summary=f"Generated {fact_count} atomic fact candidates for Analysis V3.", meta=meta)
        return fact_count

    def _rule_extract_facts(self, book_id: int, run_id: int, blocks, mentions, entities) -> list[Any]:
        return FactExtractor().extract_from_context(book_id=book_id, run_id=run_id, blocks=blocks, mentions=mentions, entities=entities)

    def run_card_events(self, book_id: int, run_id: int, *, update_run: bool = True, use_ai: bool = False):
        result = self.card_coordinator.run(
            book_id=int(book_id),
            run_id=int(run_id),
            use_ai=use_ai,
            ai_provider=self.ai_provider if use_ai else None,
        )
        engine = getattr(result, "engine", None) or getattr(self, "_last_card_engine", None) or "rule"
        self._last_card_engine = engine
        self.store.create_audit_log(
            int(book_id), run_id=int(run_id), action="analysis_v3_cards_created",
            target_type="analysis_run", target_uid=str(run_id),
            new_value={**result.as_dict(), "engine": engine}, reason=f"analysis v3 m5 card events processed via {engine}",
        )
        if update_run:
            from novel_app.analysis.pipeline_v3 import PIPELINE_V3_VERSION
            run = self.store.get_run(int(run_id))
            meta = _existing_run_meta(run)
            meta.update({"pipeline_version": str(run["pipeline_version"] or PIPELINE_V3_VERSION) if run else PIPELINE_V3_VERSION,
                         "pipeline_family": "analysis_v3", "current_phase": "M5", "current_step": "card_events",
                         "next_step": "backtrack", "event_count": result.event_count, "card_count": result.active_card_count,
                         "ai_invoked": use_ai and self.ai_provider is not None, "engine": engine})
            self.store.update_run_status(int(run_id), "cards_ready",
                summary=f"Generated {result.active_card_count} V3 card candidates from {result.event_count} events.", meta=meta)
        return result

    def run_memory_layer(self, book_id: int, run_id: int, *, update_run: bool = True, use_ai: bool = False) -> dict[str, int]:
        source_facts = self.fact_store.list_facts(int(book_id), run_id=int(run_id), limit=None)
        # 临时设置 memory_classifier 和 memory_compressor 的 AI 配置，调用后恢复（避免影响其他调用）
        orig_classifier_use_ai = self.memory_classifier.use_ai
        orig_classifier_ai_provider = self.memory_classifier.ai_provider
        orig_compressor_use_ai = self.memory_compressor.use_ai
        orig_compressor_ai_provider = self.memory_compressor.ai_provider
        try:
            self.memory_classifier.use_ai = use_ai
            self.memory_classifier.ai_provider = self.ai_provider if use_ai else None
            self.memory_compressor.use_ai = use_ai
            self.memory_compressor.ai_provider = self.ai_provider if use_ai else None

            classified = self.memory_classifier.classify_facts(
                [f for f in source_facts if str(f.get("fact_type") or "") != "memory_summary"])
            migrated = self.memory_classifier.window_builder.migrate_expired_short_term(classified)
            compressed = self.memory_compressor.compress(migrated)
        finally:
            self.memory_classifier.use_ai = orig_classifier_use_ai
            self.memory_classifier.ai_provider = orig_classifier_ai_provider
            self.memory_compressor.use_ai = orig_compressor_use_ai
            self.memory_compressor.ai_provider = orig_compressor_ai_provider
        fact_ids = self.fact_store.replace_facts(int(book_id), int(run_id), compressed)
        summary_count = sum(1 for f in compressed if str(f.get("fact_type") or "") == "memory_summary")
        result = {"fact_count": len(fact_ids), "classified_fact_count": len(classified), "summary_fact_count": summary_count}
        # 动态决定 engine：两者都 ai → ai；都 rule → rule；混合 → rule_fallback
        classifier_engine = getattr(self.memory_classifier, "_last_engine", "rule")
        compressor_engine = getattr(self.memory_compressor, "_last_engine", "rule")
        if classifier_engine == "ai" and compressor_engine == "ai":
            engine = "ai"
        elif classifier_engine == "rule" and compressor_engine == "rule":
            engine = "rule"
        else:
            engine = "rule_fallback"
        self.store.create_audit_log(
            int(book_id), run_id=int(run_id), action="analysis_v3_memory_layer_ready",
            target_type="analysis_run", target_uid=str(run_id),
            new_value={**result, "engine": engine}, reason="analysis v3 m7 memory classification and compression completed",
        )
        if update_run:
            from novel_app.analysis.pipeline_v3 import PIPELINE_V3_VERSION
            run = self.store.get_run(int(run_id))
            meta = _existing_run_meta(run)
            meta.update({"pipeline_version": str(run["pipeline_version"] or PIPELINE_V3_VERSION) if run else PIPELINE_V3_VERSION,
                         "pipeline_family": "analysis_v3", "current_phase": "M7", "current_step": "memory_layer",
                         "next_step": "probe_planner", "fact_count": result["fact_count"],
                         "memory_fact_count": result["classified_fact_count"], "memory_summary_fact_count": result["summary_fact_count"],
                         "ai_invoked": use_ai and self.ai_provider is not None, "engine": engine})
            self.store.update_run_status(int(run_id), "memory_ready",
                summary=f"Classified {result['classified_fact_count']} facts and generated {result['summary_fact_count']} memory summary candidates for Analysis V3.",
                meta=meta)
        return result

    def run_memory_layer_background(self, book_id: int, run_id: int, *, use_ai: bool = False) -> None:
        """后台静默执行记忆分层，不阻塞主流程。

        主流程调用此方法后立即返回，记忆分层在后台线程中执行：
        1. 分类 facts（hot/warm/cold/archive）
        2. 迁移短期记忆
        3. 并行压缩 + 分组级流式 upsert（只追加 memory_summary，不 replace_facts）
        4. 更新 run 状态

        主流程的 card_events/probe_plans 会读到原始 facts（无 memory_summary），
        后台完成后 memory_summary 被追加到数据库，下次读取时可见。
        """
        thread = threading.Thread(
            target=self._memory_layer_background_worker,
            args=(int(book_id), int(run_id), use_ai),
            name=f"memory-layer-bg-run{run_id}",
            daemon=True,
        )
        thread.start()
        logger.info("Memory layer background thread started for run %s (book %s, use_ai=%s)", run_id, book_id, use_ai)

    def _memory_layer_background_worker(self, book_id: int, run_id: int, use_ai: bool) -> None:
        """记忆分层后台工作线程。"""
        t_start = time.monotonic()
        try:
            source_facts = self.fact_store.list_facts(book_id, run_id=run_id, limit=None)
            # 临时设置 AI 配置
            orig_classifier_use_ai = self.memory_classifier.use_ai
            orig_classifier_ai_provider = self.memory_classifier.ai_provider
            orig_compressor_use_ai = self.memory_compressor.use_ai
            orig_compressor_ai_provider = self.memory_compressor.ai_provider
            try:
                self.memory_classifier.use_ai = use_ai
                self.memory_classifier.ai_provider = self.ai_provider if use_ai else None
                self.memory_compressor.use_ai = use_ai
                self.memory_compressor.ai_provider = self.ai_provider if use_ai else None

                classified = self.memory_classifier.classify_facts(
                    [f for f in source_facts if str(f.get("fact_type") or "") != "memory_summary"])
                migrated = self.memory_classifier.window_builder.migrate_expired_short_term(classified)
            finally:
                self.memory_classifier.use_ai = orig_classifier_use_ai
                self.memory_classifier.ai_provider = orig_classifier_ai_provider
                self.memory_compressor.use_ai = orig_compressor_use_ai
                self.memory_compressor.ai_provider = orig_compressor_ai_provider

            # 并行压缩 + 流式 upsert
            collected: list[dict[str, Any]] = []

            def _on_group_done(summary: dict[str, Any]) -> None:
                collected.append(summary)
                # 分组级流式写回：每组完成立即 upsert 已收集的 summaries
                try:
                    self.fact_store.upsert_memory_summaries(book_id, run_id, collected)
                except Exception as exc:
                    logger.warning("Background memory layer upsert failed (collected=%d): %s", len(collected), exc)

            summaries = self.memory_compressor.compress_parallel(
                migrated, use_ai=use_ai, on_group_done=_on_group_done,
            )
            # 最终全量 upsert 确保完整性
            try:
                self.fact_store.upsert_memory_summaries(book_id, run_id, summaries)
            except Exception as exc:
                logger.warning("Background memory layer final upsert failed: %s", exc)

            summary_count = len(summaries)
            classifier_engine = getattr(self.memory_classifier, "_last_engine", "rule")
            compressor_engine = getattr(self.memory_compressor, "_last_engine", "rule")
            if classifier_engine == "ai" and compressor_engine == "ai":
                engine = "ai"
            elif classifier_engine == "rule" and compressor_engine == "rule":
                engine = "rule"
            else:
                engine = "rule_fallback"

            elapsed = time.monotonic() - t_start
            logger.info(
                "Memory layer background completed for run %s: %d classified, %d summaries, engine=%s, elapsed=%.1fs",
                run_id, len(classified), summary_count, engine, elapsed,
            )

            self.store.create_audit_log(
                book_id, run_id=run_id, action="analysis_v3_memory_layer_background_done",
                target_type="analysis_run", target_uid=str(run_id),
                new_value={"classified_fact_count": len(classified), "summary_fact_count": summary_count, "engine": engine, "elapsed_sec": round(elapsed, 1)},
                reason="analysis v3 m7 memory layer background compression completed",
            )
        except Exception as exc:
            elapsed = time.monotonic() - t_start
            logger.error("Memory layer background failed for run %s after %.1fs: %s", run_id, elapsed, exc, exc_info=True)
            try:
                self.store.create_audit_log(
                    book_id, run_id=run_id, action="analysis_v3_memory_layer_background_failed",
                    target_type="analysis_run", target_uid=str(run_id),
                    new_value={"error": str(exc)[:200], "elapsed_sec": round(elapsed, 1)},
                    reason="analysis v3 m7 memory layer background compression failed",
                )
            except Exception:
                pass

    def run_probe_plans(self, book_id: int, run_id: int, *, update_run: bool = True, use_ai: bool = False) -> ProbeExecutionResult:
        facts = self.fact_store.list_facts(int(book_id), run_id=int(run_id), limit=None)
        entities = self.entity_store.list_entities(int(book_id), run_id=int(run_id), limit=None)
        plans = self.probe_planner.plan(book_id=int(book_id), run_id=int(run_id), facts=facts, entities=entities, use_ai=use_ai, ai_provider=self.ai_provider if use_ai else None)
        self.store.replace_probe_plans(int(book_id), int(run_id), plans)
        result = self.probe_executor.execute(book_id=int(book_id), run_id=int(run_id), plans=plans, facts=facts)
        engine = getattr(self.probe_planner, "_last_engine", None) or "rule"
        self._last_probe_engine = engine
        self.store.create_audit_log(
            int(book_id), run_id=int(run_id), action="analysis_v3_probes_executed",
            target_type="analysis_run", target_uid=str(run_id),
            new_value={**result.as_dict(), "engine": engine},
            reason="analysis v3 m8 article probe plans and consistency results created",
        )
        if update_run:
            from novel_app.analysis.pipeline_v3 import PIPELINE_V3_VERSION
            run = self.store.get_run(int(run_id))
            meta = _existing_run_meta(run)
            meta.update({"pipeline_version": str(run["pipeline_version"] or PIPELINE_V3_VERSION) if run else PIPELINE_V3_VERSION,
                         "pipeline_family": "analysis_v3", "current_phase": "M8", "current_step": "article_probes",
                         "next_step": "workflow_ui", "probe_plan_count": result.plan_count,
                         "probe_result_count": result.result_count, "probe_inconsistent_count": result.inconsistent_count,
                         "probe_manual_review_count": result.manual_review_count, "backtrack_task_count": result.backtrack_task_count,
                         "ai_invoked": use_ai and self.ai_provider is not None, "engine": engine})
            self.store.update_run_status(int(run_id), "probes_ready",
                summary=f"Generated {result.plan_count} article probe plans and {result.result_count} consistency results for Analysis V3.",
                meta=meta)
        return result

    def plan_backtrack_task(self, book_id: int, run_id: int, *, trigger_type: str, target_uid: str, reason: str = "") -> dict[str, Any]:
        return self.backtrack_planner.plan_task(book_id=int(book_id), run_id=int(run_id), trigger_type=trigger_type, target_uid=target_uid, reason=reason)

    def run_backtrack_task(self, book_id: int, run_id: int, task_id: int):
        return self.backtrack_planner.execute_task(book_id=int(book_id), run_id=int(run_id), task_id=int(task_id))

    # ------------------------------------------------------------------
    # content_hash 跳过未变更 block
    # ------------------------------------------------------------------

    def _filter_unchanged_blocks(self, book_id: int, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """过滤掉 content_hash 与已有 block 相同的 block，仅返回新增/变更 block。"""
        if not CONTENT_HASH_SKIP or not blocks:
            return blocks
        existing_hashes: set[str] = set()
        try:
            existing_blocks = self.store.list_blocks(int(book_id), limit=None)
            for row in existing_blocks:
                row_hash = str(getattr(row, "content_hash", "") or dict(row).get("content_hash", "") or "")
                if row_hash:
                    existing_hashes.add(row_hash)
        except Exception:
            return blocks
        if not existing_hashes:
            return blocks
        filtered = [b for b in blocks if str(b.get("content_hash") or "") not in existing_hashes]
        return filtered if filtered else blocks

    # ------------------------------------------------------------------
    # 向量索引
    # ------------------------------------------------------------------

    def _index_blocks_to_vector_store(self, book_id: int, blocks: list[dict[str, Any]]) -> None:
        if not self.vector_store or not blocks:
            return
        try:
            count = self.vector_store.index_blocks_batch(book_id, blocks)
            logger.info("Indexed %d/%d blocks to vector store for book_id=%s", count, len(blocks), book_id)
        except Exception as exc:
            logger.warning("Failed to index blocks to vector store: %s", exc)

    def _index_mentions_to_vector_store(self, book_id: int, run_id: int) -> None:
        if not self.vector_store:
            return
        try:
            mentions = self.entity_store.list_mentions(int(book_id), run_id=int(run_id), limit=None)
            mention_dicts = [dict(m) for m in mentions]
            if mention_dicts:
                count = self.vector_store.index_mentions_batch(book_id, mention_dicts)
                logger.info("Indexed %d/%d mentions to vector store for book_id=%s", count, len(mention_dicts), book_id)
        except Exception as exc:
            logger.warning("Failed to index mentions to vector store: %s", exc)

    def _index_entities_to_vector_store(self, book_id: int, run_id: int) -> None:
        if not self.vector_store:
            return
        try:
            entities = self.entity_store.list_entities(int(book_id), run_id=int(run_id), limit=None)
            entity_dicts = [dict(e) for e in entities]
            if entity_dicts:
                count = self.vector_store.index_entity_summaries_batch(book_id, entity_dicts)
                logger.info("Indexed %d/%d entity summaries to vector store for book_id=%s", count, len(entity_dicts), book_id)
        except Exception as exc:
            logger.warning("Failed to index entity summaries to vector store: %s", exc)

    # ------------------------------------------------------------------
    # AI 调用并行化
    # ------------------------------------------------------------------

    def _parallel_ai_extract_mentions(
        self, blocks: list[dict[str, Any]], book_id: int, run_id: int, *, max_workers: int = AI_MAX_WORKERS,
    ) -> list[Any]:
        """并行调用 AI 提取实体提及。每个 block 独立调用，结果合并。

        使用 run_aimd_pool 动态并发控制（慢启动 + 三级失败回退），
        避免高 max_workers 下一次性提交全部 block 打爆 API 连接。
        """
        if not blocks or max_workers <= 1:
            return self.ai_provider.extract_mentions(blocks, book_id=book_id, run_id=run_id)

        def _work(block: dict[str, Any]) -> list[Any]:
            return self.ai_provider.extract_mentions([block], book_id=book_id, run_id=run_id, raise_on_error=True)

        return run_aimd_pool(
            blocks, _work,
            max_workers=min(max_workers, len(blocks)),
            stage_label="ai_mention",
        )

    def _parallel_ai_extract_facts(
        self, blocks: list[dict[str, Any]], entities: list[dict[str, Any]],
        book_id: int, run_id: int, *, max_workers: int = AI_MAX_WORKERS,
    ) -> list[Any]:
        """并行调用 AI 提取原子事实。每个 block 独立调用，结果合并。

        使用 run_aimd_pool 动态并发控制（慢启动 + 三级失败回退），
        避免高 max_workers 下一次性提交全部 block 打爆 API 连接。
        """
        if not blocks or max_workers <= 1:
            return self.ai_provider.extract_facts(blocks, entities, book_id=book_id, run_id=run_id)

        def _work(block: dict[str, Any]) -> list[Any]:
            return self.ai_provider.extract_facts([block], entities, book_id=book_id, run_id=run_id, raise_on_error=True)

        return run_aimd_pool(
            blocks, _work,
            max_workers=min(max_workers, len(blocks)),
            stage_label="ai_fact",
        )

    # ------------------------------------------------------------------
    # 异步包装方法 — 避免同步 AI 调用阻塞事件循环
    # ------------------------------------------------------------------

    async def arun_entity_mentions(
        self, book_id: int, run_id: int, *,
        blocks: list[dict[str, Any]] | None = None,
        update_run: bool = True, use_ai: bool = False,
        ai_max_workers: int = AI_MAX_WORKERS,
    ) -> int:
        """run_entity_mentions 的异步版本，通过 asyncio.to_thread 避免阻塞事件循环。"""
        return await asyncio.to_thread(
            self.run_entity_mentions, book_id, run_id,
            blocks=blocks, update_run=update_run, use_ai=use_ai,
            ai_max_workers=ai_max_workers,
        )

    async def arun_entity_coreference(
        self, book_id: int, run_id: int, *,
        update_run: bool = True, use_ai: bool = False,
    ) -> int:
        """run_entity_coreference 的异步版本。"""
        return await asyncio.to_thread(
            self.run_entity_coreference, book_id, run_id,
            update_run=update_run, use_ai=use_ai,
        )

    async def arun_atomic_facts(
        self, book_id: int, run_id: int, *,
        blocks: list[dict[str, Any]] | None = None,
        update_run: bool = True, use_ai: bool = False,
        ai_max_workers: int = AI_MAX_WORKERS,
    ) -> int:
        """run_atomic_facts 的异步版本。"""
        return await asyncio.to_thread(
            self.run_atomic_facts, book_id, run_id,
            blocks=blocks, update_run=update_run, use_ai=use_ai,
            ai_max_workers=ai_max_workers,
        )

    async def arun_card_events(
        self, book_id: int, run_id: int, *,
        update_run: bool = True, use_ai: bool = False,
    ) -> Any:
        """run_card_events 的异步版本，通过 asyncio.to_thread 避免阻塞事件循环。"""
        return await asyncio.to_thread(
            self.run_card_events, book_id, run_id,
            update_run=update_run, use_ai=use_ai,
        )

    async def arun_memory_layer(
        self, book_id: int, run_id: int, *,
        update_run: bool = True, use_ai: bool = False,
    ) -> dict[str, int]:
        """run_memory_layer 的异步版本，通过 asyncio.to_thread 避免阻塞事件循环。"""
        return await asyncio.to_thread(
            self.run_memory_layer, book_id, run_id,
            update_run=update_run, use_ai=use_ai,
        )
