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

AI_MAX_WORKERS = int(os.environ.get("LINGSHU_ANALYSIS_V3_AI_MAX_WORKERS", "2000") or 2000)
BURST_SUBMIT_CAP = int(os.environ.get("LINGSHU_AI_BURST_SUBMIT_CAP", "8") or 8)
CONTENT_HASH_SKIP = True
COREFERENCE_MENTION_LIMIT = int(os.environ.get("LINGSHU_ANALYSIS_V3_COREFERENCE_MENTION_LIMIT", "2500") or 2500)
COREFERENCE_MENTIONS_PER_NAME_LIMIT = int(os.environ.get("LINGSHU_ANALYSIS_V3_COREFERENCE_MENTIONS_PER_NAME_LIMIT", "30") or 30)
# M2 规则先行 + 标记打包 + 异常二次复查 参数
MENTION_SCREEN_BATCH_SIZE = int(os.environ.get("LINGSHU_MENTION_SCREEN_BATCH_SIZE", "100") or 100)
MENTION_REVIEW_CONTEXT_CHARS = int(os.environ.get("LINGSHU_MENTION_REVIEW_CONTEXT_CHARS", "300") or 300)
MENTION_AUTO_ACCEPT_THRESHOLD = float(os.environ.get("LINGSHU_MENTION_AUTO_ACCEPT_THRESHOLD", "0.85") or 0.85)


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
    window_chars = 8000  # 与 AI_TEXT_WINDOW_CHARS 保持一致
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
    cancel_event: Any | None = None,
    on_result: Any = None,
) -> list[Any]:
    """通用 AIMD 动态并发执行器，保护高 max_workers 下的 AI 批量调用。

    将一批 items 通过 worker_fn(item) 并发执行，使用 AIMDConcurrencyController
    动态管理并发上限（慢启动爬坡 + 三级失败回退），避免一次性提交全部任务
    在 max_workers=500 时打爆 API 连接。

    - 物理上限 max_workers（ThreadPoolExecutor 容量）
    - 逻辑上限由 controller 动态决定（初始保守，成功翻倍爬坡至 ssthresh 后 +1）
    - 失败按 限流(×0.5) / 连接错误(×0.7) / 普通(-1) 三级回退
    worker_fn 返回 None 视为空，返回 list 直接 extend，返回单值包装为单元素列表。

    cancel_event: 若设置（threading.Event.is_set()），立即停止提交新任务，
    取消未开始的 future，返回已完成的部分结果。防止 WebSocket 断开后
    worker 线程继续访问已关闭的数据库。

    on_result: 可选回调函数，签名 on_result(result)。
    传入时启用流式写入模式：每个任务完成后在主线程串行调用回调立即写库，
    结果不累积到内存列表，避免大文件场景 OOM。返回值为空列表。
    """
    results: list[Any] = []
    if not items:
        return results
    # 单项或低并发直接串行（保留原 extract_mentions/facts 的批量优化路径）
    if max_workers <= 1 or len(items) == 1:
        for item in items:
            try:
                r = worker_fn(item)
                if on_result is not None:
                    if r:
                        try:
                            on_result(r)
                        except Exception as cb_exc:
                            logger.warning("%s on_result callback failed: %s", stage_label, cb_exc)
                elif r:
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
            # 取消检查：若 cancel_event 已设置，立即停止提交新任务并退出
            if cancel_event is not None and callable(getattr(cancel_event, "is_set", None)) and cancel_event.is_set():
                logger.info("%s cancelled by cancel_event, completed %d/%d, draining pending", stage_label, completed, total)
                for fut in pending:
                    fut.cancel()
                break

            done, pending = concurrent.futures.wait(
                pending, timeout=1.0, return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                completed += 1
                try:
                    r = future.result(timeout=per_call_timeout)
                    if on_result is not None:
                        # 流式写入模式：每个结果立即通过回调写库，不累积到内存
                        if r:
                            try:
                                on_result(r)
                            except Exception as cb_exc:
                                logger.warning("%s on_result callback failed: %s", stage_label, cb_exc)
                    elif r:
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
        mentions: list[Any] = []
        # streamed_count 非 None 时表示已通过流式写入落库，跳过末尾的 replace_mentions
        streamed_count: int | None = None
        if use_ai and self.ai_provider is not None:
            # M2 优化：规则先行 + 标记打包 + 异常二次复查
            # 1. 规则全量扫描（毫秒级，无 AI 调用）
            # 2. 高置信度自动接受，其余打包标记送 LLM 批量筛查（仅元数据）
            # 3. 可疑标记拉取 ±300 字上下文送 LLM 二次复查
            # 4. 合并结果写库
            has_screen = hasattr(self.ai_provider, "screen_mention_markers") and hasattr(self.ai_provider, "review_suspicious_mention")
            try:
                rule_mentions = self._rule_extract_mentions(int(book_id), int(run_id), source_blocks)
                if rule_mentions and has_screen:
                    # 新流程：规则先行 + AI 筛查
                    final_mentions = self._run_m2_rule_first_screen(
                        rule_mentions, source_blocks, int(book_id), int(run_id),
                        max_workers=ai_max_workers,
                    )
                    if final_mentions is not None:
                        mentions = final_mentions
                        engine = "rule_plus_ai_screen"
                    else:
                        # AI 筛查整体失败，使用纯规则结果
                        mentions = rule_mentions
                        engine = "rule_only"
                elif rule_mentions and not has_screen:
                    # AI provider 不支持筛查，使用规则结果
                    mentions = rule_mentions
                    engine = "rule_only"
                else:
                    # 规则无结果，回退到 AI-only 全文提取
                    workers = _adaptive_workers(source_blocks, max_workers=ai_max_workers)
                    logger.info("M2 rule-first found 0 candidates, falling back to AI-only: %d blocks, workers=%d",
                                len(source_blocks), workers)
                    ai_mentions = self._parallel_ai_extract_mentions(
                        source_blocks, int(book_id), int(run_id), max_workers=workers)
                    if ai_mentions:
                        mentions = ai_mentions
                        engine = "ai"
                    else:
                        mentions = []
                        engine = "ai_empty"
            except Exception as exc:
                from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3Cancelled
                if isinstance(exc, AnalysisPipelineV3Cancelled):
                    raise
                logger.warning("M2 rule-first+screen failed, falling back to rule-only: %s", exc)
                mentions = self._rule_extract_mentions(int(book_id), int(run_id), source_blocks)
                engine = "rule_fallback"
        else:
            mentions = self._rule_extract_mentions(int(book_id), int(run_id), source_blocks)
        # 取消检查：run_aimd_pool 可能因 cancel 提前返回部分结果，此时不应继续写库
        _cancel = getattr(self, "_cancel_event", None)
        if _cancel is not None and callable(getattr(_cancel, "is_set", None)) and _cancel.is_set():
            from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3Cancelled
            raise AnalysisPipelineV3Cancelled("Analysis V3 run cancelled during M2 entity_mentions")
        if streamed_count is not None:
            mention_count = streamed_count
        else:
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

    # ------------------------------------------------------------------
    # M2 规则先行 + 标记打包 + 异常二次复查
    # ------------------------------------------------------------------

    def _run_m2_rule_first_screen(
        self,
        rule_mentions: list[Any],
        source_blocks: list[dict[str, Any]],
        book_id: int,
        run_id: int,
        *,
        max_workers: int = AI_MAX_WORKERS,
    ) -> list[Any] | None:
        """M2 规则先行 + AI 标记筛查 + 异常二次复查。

        流程：
        1. 预过滤：高置信度 mention 自动接受（formal_character/formal_world_entry/confidence≥0.85）
        2. 其余 mention 打包为标记（仅元数据） → LLM 批量筛查
        3. 可疑标记拉取 ±300 字上下文 → LLM 二次复查
        4. 合并：auto_accept + screen_confirmed + review_confirmed

        返回 None 表示 AI 筛查整体失败，调用方应使用纯规则结果。
        """
        import dataclasses

        # Step 1: 预过滤
        auto_accept, to_screen = self._split_rule_mentions_for_screening(rule_mentions)
        logger.info("M2 rule-first pre-filter: %d auto-accepted, %d to screen (total %d)",
                    len(auto_accept), len(to_screen), len(rule_mentions))

        if not to_screen:
            # 全部高置信度，无需 AI 筛查
            return list(auto_accept)

        # Step 2: 构建标记包（仅元数据）+ 共现信息
        co_occurrence_map = self._build_block_co_occurrence(rule_mentions)
        markers: list[dict[str, Any]] = []
        mention_by_id: dict[str, Any] = {}
        for m in to_screen:
            marker = self._build_mention_marker(m, co_occurrence_map)
            markers.append(marker)
            mention_by_id[marker["marker_id"]] = m

        # Step 3: 批量 LLM 筛查（AIMD 并发控制）
        screen_results = self._parallel_screen_mention_markers(
            markers, book_id, run_id, max_workers=max_workers,
        )

        if screen_results is None:
            logger.warning("M2 screening entirely failed, returning None for caller fallback")
            return None

        # Step 4: 分类筛查结果
        confirmed_ids: set[str] = set()
        suspicious_markers: list[dict[str, Any]] = []
        rejected_count = 0
        screen_map = {str(r.get("marker_id") or ""): r for r in screen_results}

        for marker in markers:
            mid = str(marker.get("marker_id") or "")
            result = screen_map.get(mid)
            if result is None:
                # LLM 遗漏，保守起见视为 suspicious
                suspicious_markers.append(marker)
            elif result["verdict"] == "confirmed":
                confirmed_ids.add(mid)
            elif result["verdict"] == "suspicious":
                suspicious_markers.append(marker)
            else:  # reject
                rejected_count += 1

        logger.info("M2 screening: %d confirmed, %d suspicious, %d rejected, %d missing",
                    len(confirmed_ids), len(suspicious_markers), rejected_count,
                    len(markers) - len(confirmed_ids) - len(suspicious_markers) - rejected_count)

        # Step 5: 异常标记二次复查（携带上下文）
        confirmed_by_review: dict[str, dict[str, Any]] = {}
        if suspicious_markers:
            block_index = {str(b.get("block_uid") or ""): b for b in source_blocks}
            review_results = self._parallel_review_suspicious_mentions(
                suspicious_markers, mention_by_id, block_index,
                book_id, run_id, max_workers=max_workers,
            )
            for r in review_results:
                if r and r.get("verdict") == "confirmed":
                    confirmed_by_review[str(r.get("marker_id") or "")] = r
            logger.info("M2 review: %d confirmed out of %d suspicious",
                        len(confirmed_by_review), len(suspicious_markers))

        # Step 6: 构建最终 mention 列表
        final_mentions: list[Any] = list(auto_accept)

        for marker in markers:
            mid = str(marker.get("marker_id") or "")
            original = mention_by_id.get(mid)
            if original is None:
                continue

            if mid in confirmed_ids:
                # 筛查确认，保留原 mention
                final_mentions.append(original)
            elif mid in confirmed_by_review:
                # 复查确认，可能需更新 entity_type/quote_text
                review = confirmed_by_review[mid]
                corrected = str(review.get("corrected_quote_text") or "").strip()
                new_type = str(review.get("entity_type") or "").strip()
                new_conf = float(review.get("confidence") or 0.0)
                orig_quote = str(getattr(original, "quote_text", "") or "")
                orig_type = str(getattr(original, "entity_type", "") or "")

                if corrected and corrected != orig_quote:
                    # 尝试在 block 中定位修正后的 quote_text
                    block_uid = str(getattr(original, "block_uid", "") or "")
                    block = block_index.get(block_uid)
                    if block:
                        text = str(block.get("text") or "")
                        block_start = int(block.get("char_start") or 0)
                        # 从原始位置附近搜索，避免多个相同文本取到同一位置导致 mention_uid 冲突
                        orig_char_start = int(getattr(original, "char_start", 0) or 0)
                        local_orig = max(0, orig_char_start - block_start)
                        search_start = max(0, local_orig - len(corrected))
                        rel = text.find(corrected, search_start)
                        if rel < 0:
                            # 附近找不到，从头搜索
                            rel = text.find(corrected)
                        if rel >= 0:
                            # 创建修正后的候选
                            try:
                                from novel_app.analysis.schemas_v3 import EntityMentionCandidate
                                from novel_app.analysis.entity_resolver import normalize_entity_alias
                                updated = EntityMentionCandidate.create(
                                    book_id=book_id,
                                    run_id=run_id,
                                    entity_type=new_type or orig_type,
                                    normalized_text=normalize_entity_alias(corrected),
                                    quote_text=corrected,
                                    chapter_id=getattr(original, "chapter_id", None),
                                    block_uid=block_uid,
                                    char_start=block_start + rel,
                                    char_end=block_start + rel + len(corrected),
                                    confidence=max(0.0, min(1.0, new_conf)),
                                    source_rule=str(getattr(original, "source_rule", "") or "") + "+ai_review",
                                    metadata=dict(getattr(original, "metadata", {}) or {}),
                                )
                                final_mentions.append(updated)
                                continue
                            except Exception:
                                pass  # 创建失败，回退到原 mention
                    # 无法定位修正文本，保留原 mention 但更新类型/置信度
                    if new_type and new_type != orig_type:
                        final_mentions.append(dataclasses.replace(original, entity_type=new_type, confidence=max(0.0, min(1.0, new_conf))))
                    else:
                        final_mentions.append(dataclasses.replace(original, confidence=max(0.0, min(1.0, new_conf))))
                elif new_type and new_type != orig_type:
                    # 仅类型变更
                    final_mentions.append(dataclasses.replace(original, entity_type=new_type, confidence=max(0.0, min(1.0, new_conf))))
                else:
                    # 仅更新置信度
                    final_mentions.append(dataclasses.replace(original, confidence=max(0.0, min(1.0, new_conf))))
            # else: rejected → 丢弃

        # 按 mention_uid 去重（保留置信度更高的），防止 UNIQUE 约束冲突
        seen_uids: set[str] = set()
        deduped: list[Any] = []
        for m in final_mentions:
            uid = str(getattr(m, "mention_uid", "") or "")
            if not uid:
                deduped.append(m)
                continue
            if uid in seen_uids:
                # 已存在，保留置信度更高的
                for i, existing in enumerate(deduped):
                    if str(getattr(existing, "mention_uid", "") or "") == uid:
                        if float(getattr(m, "confidence", 0.0) or 0.0) > float(getattr(existing, "confidence", 0.0) or 0.0):
                            deduped[i] = m
                        break
                continue
            seen_uids.add(uid)
            deduped.append(m)
        if len(deduped) < len(final_mentions):
            logger.info("M2 dedup: %d → %d mentions (removed %d duplicate mention_uids)",
                        len(final_mentions), len(deduped), len(final_mentions) - len(deduped))
        final_mentions = deduped

        logger.info("M2 rule-first+screen final: %d mentions (auto=%d, screen_confirmed=%d, review_confirmed=%d, rejected=%d)",
                    len(final_mentions), len(auto_accept), len(confirmed_ids), len(confirmed_by_review),
                    len(to_screen) - len(confirmed_ids) - len(confirmed_by_review))
        return final_mentions

    @staticmethod
    def _split_rule_mentions_for_screening(
        mentions: list[Any],
    ) -> tuple[list[Any], list[Any]]:
        """预过滤：高置信度 mention 自动接受，其余进入 LLM 筛查。

        自动接受条件（满足任一）：
        - source_rule 为 formal_character 或 formal_world_entry（来自数据库已知实体）
        - confidence >= MENTION_AUTO_ACCEPT_THRESHOLD (默认 0.85)
        其余进入筛查队列。
        """
        auto_accept: list[Any] = []
        to_screen: list[Any] = []
        for m in mentions:
            source_rule = str(getattr(m, "source_rule", "") or "")
            confidence = float(getattr(m, "confidence", 0.0) or 0.0)
            if source_rule in ("formal_character", "formal_world_entry") or confidence >= MENTION_AUTO_ACCEPT_THRESHOLD:
                auto_accept.append(m)
            else:
                to_screen.append(m)
        return auto_accept, to_screen

    @staticmethod
    def _build_block_co_occurrence(mentions: list[Any]) -> dict[str, list[str]]:
        """构建 block_uid → 同块内其他实体名称列表 的映射。

        用于标记打包时提供共现信息，帮助 LLM 判断实体可信度。
        """
        from collections import defaultdict
        block_names: dict[str, list[str]] = defaultdict(list)
        for m in mentions:
            block_uid = str(getattr(m, "block_uid", "") or "")
            quote_text = str(getattr(m, "quote_text", "") or "")
            if block_uid and quote_text:
                block_names[block_uid].append(quote_text)
        # 去重并限制每块最多 20 个共现名称
        return {
            uid: sorted(set(names))[:20]
            for uid, names in block_names.items()
        }

    @staticmethod
    def _build_mention_marker(
        mention: Any,
        co_occurrence_map: dict[str, list[str]],
    ) -> dict[str, Any]:
        """将 mention 候选打包为标记（仅元数据，不含原文）。

        标记包含：marker_id, quote_text, entity_type, confidence, source_rule,
        chapter_title, char_start, char_end, co_occurrence。
        """
        block_uid = str(getattr(mention, "block_uid", "") or "")
        metadata = getattr(mention, "metadata", {}) or {}
        chapter_title = str(metadata.get("chapter_title", "") or "")
        return {
            "marker_id": str(getattr(mention, "mention_uid", "") or ""),
            "quote_text": str(getattr(mention, "quote_text", "") or ""),
            "entity_type": str(getattr(mention, "entity_type", "") or ""),
            "confidence": float(getattr(mention, "confidence", 0.0) or 0.0),
            "source_rule": str(getattr(mention, "source_rule", "") or ""),
            "chapter_title": chapter_title,
            "char_start": int(getattr(mention, "char_start", 0) or 0),
            "char_end": int(getattr(mention, "char_end", 0) or 0),
            "co_occurrence": co_occurrence_map.get(block_uid, []),
        }

    def _parallel_screen_mention_markers(
        self,
        markers: list[dict[str, Any]],
        book_id: int,
        run_id: int,
        *,
        max_workers: int = AI_MAX_WORKERS,
    ) -> list[dict[str, Any]] | None:
        """并行批量调用 LLM 筛查标记（仅元数据）。

        将 markers 按 MENTION_SCREEN_BATCH_SIZE 分批，每批调用
        ai_provider.screen_mention_markers()，使用 run_aimd_pool 并发控制。

        返回 None 表示整体失败（无任何结果返回）。
        """
        if not markers:
            return []

        batch_size = max(1, MENTION_SCREEN_BATCH_SIZE)
        batches: list[list[dict[str, Any]]] = []
        for i in range(0, len(markers), batch_size):
            batches.append(markers[i:i + batch_size])

        logger.info("M2 screening: %d markers → %d batches (batch_size=%d)",
                    len(markers), len(batches), batch_size)

        def _work(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
            _cancel = getattr(self, "_cancel_event", None)
            if _cancel is not None and callable(getattr(_cancel, "is_set", None)) and _cancel.is_set():
                return []
            return self.ai_provider.screen_mention_markers(
                batch, book_id=book_id, run_id=run_id, raise_on_error=True,
            )

        results = run_aimd_pool(
            batches, _work,
            max_workers=min(max_workers, len(batches)),
            stage_label="ai_mention_screen",
            cancel_event=getattr(self, "_cancel_event", None),
        )

        if not results:
            # 所有批次都失败了
            return None

        # run_aimd_pool 已将各批次的 list 展平为单个 dict 列表
        return results

    def _parallel_review_suspicious_mentions(
        self,
        suspicious_markers: list[dict[str, Any]],
        mention_by_id: dict[str, Any],
        block_index: dict[str, dict[str, Any]],
        book_id: int,
        run_id: int,
        *,
        max_workers: int = AI_MAX_WORKERS,
    ) -> list[dict[str, Any] | None]:
        """并行调用 LLM 对可疑标记进行二次复查（携带上下文文本）。

        每个可疑标记独立调用 ai_provider.review_suspicious_mention()，
        使用 run_aimd_pool 并发控制。
        """
        if not suspicious_markers:
            return []

        # 预构建每个标记的上下文文本
        review_items: list[tuple[dict[str, Any], str]] = []
        for marker in suspicious_markers:
            mid = str(marker.get("marker_id") or "")
            original = mention_by_id.get(mid)
            if original is None:
                continue
            context_text = self._extract_context_with_marker(
                original, block_index, window=MENTION_REVIEW_CONTEXT_CHARS,
            )
            if context_text:
                review_items.append((marker, context_text))

        logger.info("M2 review: %d suspicious markers, %d have context",
                    len(suspicious_markers), len(review_items))

        if not review_items:
            return []

        def _work(item: tuple[dict[str, Any], str]) -> dict[str, Any] | None:
            marker, context_text = item
            _cancel = getattr(self, "_cancel_event", None)
            if _cancel is not None and callable(getattr(_cancel, "is_set", None)) and _cancel.is_set():
                return None
            return self.ai_provider.review_suspicious_mention(
                marker, context_text,
                book_id=book_id, run_id=run_id, raise_on_error=True,
            )

        results = run_aimd_pool(
            review_items, _work,
            max_workers=min(max_workers, len(review_items)),
            stage_label="ai_mention_review",
            cancel_event=getattr(self, "_cancel_event", None),
        )
        return results

    @staticmethod
    def _extract_context_with_marker(
        mention: Any,
        block_index: dict[str, dict[str, Any]],
        *,
        window: int = 300,
    ) -> str:
        """提取 mention 位置前后各 window 字的上下文文本，用标记标注位置。

        返回格式：前文 + 【标记开始】 + 标记文本 + 【标记结束】 + 后文。
        若找不到对应的 block 则返回空字符串。
        """
        block_uid = str(getattr(mention, "block_uid", "") or "")
        block = block_index.get(block_uid)
        if block is None:
            return ""

        text = str(block.get("text") or "")
        block_start = int(block.get("char_start") or 0)
        char_start = int(getattr(mention, "char_start", 0) or 0)
        char_end = int(getattr(mention, "char_end", 0) or 0)
        quote_text = str(getattr(mention, "quote_text", "") or "")

        # 计算在 block 内的局部位置
        local_start = max(0, char_start - block_start)
        local_end = min(len(text), char_end - block_start)

        if local_start >= len(text) or local_end <= local_start:
            return ""

        # 提取上下文窗口
        ctx_start = max(0, local_start - window)
        ctx_end = min(len(text), local_end + window)

        before = text[ctx_start:local_start]
        marked = text[local_start:local_end]
        after = text[local_end:ctx_end]

        return f"{before}【标记开始】{marked}【标记结束】{after}"

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
        facts: list[Any] = []
        # streamed_count 非 None 时表示已通过流式写入落库，跳过末尾的 replace_facts
        streamed_count: int | None = None
        if use_ai and self.ai_provider is not None:
            workers = _adaptive_workers(source_blocks, max_workers=ai_max_workers)
            logger.info("M4 fact extraction: %d blocks, adaptive workers=%d", len(source_blocks), workers)
            try:
                if workers > 1 and len(source_blocks) > 1:
                    # 流式写入：先清空旧数据，每个 block 完成后立即增量写库，避免内存累积 OOM
                    self.database.replace_analysis_facts(int(book_id), int(run_id), [])
                    counter = [0]

                    def _on_fact_result(result: Any) -> None:
                        if not result:
                            return
                        batch = result if isinstance(result, list) else [result]
                        if not batch:
                            return
                        self.fact_store.add_facts(int(book_id), int(run_id), batch)
                        counter[0] += len(batch)

                    self._parallel_ai_extract_facts(
                        source_blocks, entities, int(book_id), int(run_id),
                        max_workers=workers, on_result=_on_fact_result,
                    )
                    if counter[0] > 0:
                        streamed_count = counter[0]
                        engine = "ai"
                    else:
                        # AI 返回空，回退到规则提取（streamed_count 保持 None，走 replace_facts）
                        facts = self._rule_extract_facts(int(book_id), int(run_id), source_blocks, mentions, entities)
                        engine = "rule_fallback"
                else:
                    facts = self._parallel_ai_extract_facts(source_blocks, entities, int(book_id), int(run_id), max_workers=workers)
                    if facts:
                        engine = "ai"
                    else:
                        facts = self._rule_extract_facts(int(book_id), int(run_id), source_blocks, mentions, entities)
                        engine = "rule_fallback"
            except Exception as exc:
                # 取消异常直接向上传播，不回退到规则提取
                from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3Cancelled
                if isinstance(exc, AnalysisPipelineV3Cancelled):
                    raise
                logger.warning("AI extract_facts failed, falling back to rules: %s", exc)
                facts = self._rule_extract_facts(int(book_id), int(run_id), source_blocks, mentions, entities)
                engine = "rule_fallback"
        else:
            facts = self._rule_extract_facts(int(book_id), int(run_id), source_blocks, mentions, entities)
        # 取消检查：run_aimd_pool 可能因 cancel 提前返回部分结果，此时不应继续写库
        _cancel = getattr(self, "_cancel_event", None)
        if _cancel is not None and callable(getattr(_cancel, "is_set", None)) and _cancel.is_set():
            from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3Cancelled
            raise AnalysisPipelineV3Cancelled("Analysis V3 run cancelled during M4 atomic_facts")
        if streamed_count is not None:
            fact_count = streamed_count
        else:
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
        self, blocks: list[dict[str, Any]], book_id: int, run_id: int, *,
        max_workers: int = AI_MAX_WORKERS, on_result: Any = None,
    ) -> list[Any]:
        """并行调用 AI 提取实体提及。每个 block 独立调用，结果合并。

        使用 run_aimd_pool 动态并发控制（慢启动 + 三级失败回退），
        避免高 max_workers 下一次性提交全部 block 打爆 API 连接。

        on_result: 传入时启用流式写入，每个 block 结果立即通过回调写库，
        不累积到内存，避免大文件场景 OOM。
        """
        if not blocks or max_workers <= 1:
            return self.ai_provider.extract_mentions(blocks, book_id=book_id, run_id=run_id)

        def _work(block: dict[str, Any]) -> list[Any]:
            # 快速取消检查：已取消的任务不再调用 AI，避免无谓的 API 调用和 DB 访问
            _cancel = getattr(self, "_cancel_event", None)
            if _cancel is not None and callable(getattr(_cancel, "is_set", None)) and _cancel.is_set():
                return []
            return self.ai_provider.extract_mentions([block], book_id=book_id, run_id=run_id, raise_on_error=True)

        return run_aimd_pool(
            blocks, _work,
            max_workers=min(max_workers, len(blocks)),
            stage_label="ai_mention",
            cancel_event=getattr(self, "_cancel_event", None),
            on_result=on_result,
        )

    def _parallel_ai_extract_facts(
        self, blocks: list[dict[str, Any]], entities: list[dict[str, Any]],
        book_id: int, run_id: int, *, max_workers: int = AI_MAX_WORKERS, on_result: Any = None,
    ) -> list[Any]:
        """并行调用 AI 提取原子事实。每个 block 独立调用，结果合并。

        使用 run_aimd_pool 动态并发控制（慢启动 + 三级失败回退），
        避免高 max_workers 下一次性提交全部 block 打爆 API 连接。

        on_result: 传入时启用流式写入，每个 block 结果立即通过回调写库，
        不累积到内存，避免大文件场景 OOM。
        """
        if not blocks or max_workers <= 1:
            return self.ai_provider.extract_facts(blocks, entities, book_id=book_id, run_id=run_id)

        def _work(block: dict[str, Any]) -> list[Any]:
            # 快速取消检查：已取消的任务不再调用 AI，避免无谓的 API 调用和 DB 访问
            _cancel = getattr(self, "_cancel_event", None)
            if _cancel is not None and callable(getattr(_cancel, "is_set", None)) and _cancel.is_set():
                return []
            return self.ai_provider.extract_facts([block], entities, book_id=book_id, run_id=run_id, raise_on_error=True)

        return run_aimd_pool(
            blocks, _work,
            max_workers=min(max_workers, len(blocks)),
            stage_label="ai_fact",
            cancel_event=getattr(self, "_cancel_event", None),
            on_result=on_result,
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
