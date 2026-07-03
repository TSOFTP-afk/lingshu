"""pipeline_v3 增量分析逻辑。

包含 AnalysisPipelineV3 的增量分析方法（start_incremental_run）
以及章节差异计算、数据复用、增量提取等辅助方法。
通过 Mixin 模式被 AnalysisPipelineV3 继承。
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from novel_app.analysis.fact_extractor import FactExtractor
from novel_app.analysis.mention_extractor import MentionExtractor
from novel_app.analysis.utils import chapter_dict as _chapter_dict
from novel_app.analysis.utils import safe_int as _int_or_none

logger = logging.getLogger(__name__)


class PipelineV3IncrementalMixin:
    """增量分析方法 Mixin。"""

    database: Any
    store: Any
    entity_store: Any
    fact_store: Any
    ai_provider: Any
    chunker: Any

    def start_incremental_run(
        self, book_id: int, *, base_run_id: int | None = None,
        chapters: list[dict[str, Any]] | None = None,
        meta: dict[str, Any] | None = None, progress_callback: Any | None = None,
        use_ai: bool = False, chapter_batch_size: int = 20, ai_max_workers: int = 4,
    ):
        """增量分析：对比已有 run 的章节内容，仅处理新增/变更章节。"""
        from novel_app.analysis.pipeline_v3 import PIPELINE_V3_VERSION, AnalysisPipelineV3Result, _emit_progress
        from novel_app.analysis.pipeline_v3_stages import _existing_run_meta

        chapter_payload = [_chapter_dict(item) for item in (chapters if chapters is not None else self._load_book_chapters(book_id))]
        if not chapter_payload:
            raise ValueError("没有可分析的章节")

        base_run = self._find_base_run(int(book_id), base_run_id)
        if base_run is None:
            logger.info("No base run found for book_id=%s, falling back to full analysis", book_id)
            return self.start_run(book_id, chapters=chapter_payload, meta=meta,
                progress_callback=progress_callback, use_ai=use_ai,
                chapter_batch_size=chapter_batch_size, ai_max_workers=ai_max_workers)

        base_run_id_resolved = int(base_run["id"])
        logger.info("Incremental analysis: base_run_id=%s for book_id=%s", base_run_id_resolved, book_id)

        chapter_diff = self._compute_chapter_diff(int(book_id), base_run_id_resolved, chapter_payload)
        changed_chapters = chapter_diff["changed"] + chapter_diff["added"]
        unchanged_chapter_ids = chapter_diff["unchanged_ids"]
        deleted_chapter_ids = chapter_diff["deleted_ids"]

        if not changed_chapters and not deleted_chapter_ids:
            logger.info("No chapter changes detected, returning base run result")
            base_meta_raw = _existing_run_meta(base_run)
            return AnalysisPipelineV3Result(
                run_id=base_run_id_resolved, status=str(base_run["status"] or "probes_ready"),
                block_count=int(base_meta_raw.get("semantic_block_count", 0)),
                mention_count=int(base_meta_raw.get("mention_count", 0)),
                entity_count=int(base_meta_raw.get("entity_count", 0)),
                fact_count=int(base_meta_raw.get("fact_count", 0)),
                card_count=int(base_meta_raw.get("card_count", 0)),
                summary="No changes detected since last analysis.",
                meta={**base_meta_raw, "incremental": True, "chapters_changed": 0})

        _emit_progress(progress_callback, stage="incremental_diff", percent=5,
            message=f"章节差异: {len(changed_chapters)} 变更, {len(unchanged_chapter_ids)} 未变更, {len(deleted_chapter_ids)} 删除")

        base_meta = self._stage_meta({
            "pipeline_version": PIPELINE_V3_VERSION, "pipeline_family": "analysis_v3",
            "ai_invoked": use_ai and self.ai_provider is not None, "incremental": True,
            "base_run_id": base_run_id_resolved, "chapters_added": len(chapter_diff["added"]),
            "chapters_changed": len(chapter_diff["changed"]), "chapters_unchanged": len(unchanged_chapter_ids),
            "chapters_deleted": len(deleted_chapter_ids), **(meta or {}),
        }, "init", source_chapter_count=len(chapter_payload))
        run_id = self.store.create_run(
            int(book_id), scope_type="book", status="running",
            pipeline_version=PIPELINE_V3_VERSION, input_hash=self._input_hash(chapter_payload),
            meta=base_meta, summary=f"Incremental analysis: {len(changed_chapters)} chapters changed.")

        try:
            # Step 1: 仅对变更章节分块
            stage_started = self._mark_stage(run_id, base_meta, "l1_semantic_blocks", source_chapter_count=len(chapter_payload))
            changed_block_payloads: list[dict[str, Any]] = []
            for batch_start in range(0, max(1, len(changed_chapters)), chapter_batch_size):
                batch = changed_chapters[batch_start:batch_start + chapter_batch_size]
                batch_blocks = self.chunker.chunk_chapters(int(book_id), batch, pipeline_version=PIPELINE_V3_VERSION)
                changed_block_payloads.extend(b.as_analysis_block() for b in batch_blocks)
            _emit_progress(progress_callback, stage="incremental_blocks", percent=10,
                message=f"变更章节分块: {len(changed_block_payloads)} 个新 block")

            # Step 2: 复用未变更章节的已有 blocks
            reused_block_payloads = self._reuse_blocks_from_run(int(book_id), base_run_id_resolved, unchanged_chapter_ids)
            _emit_progress(progress_callback, stage="incremental_reuse", percent=15,
                message=f"复用已有 block: {len(reused_block_payloads)} 个")

            all_block_payloads = reused_block_payloads + changed_block_payloads
            block_ids = self.store.save_blocks(int(book_id), run_id, all_block_payloads) if all_block_payloads else []
            self._check_stage_timeout(stage_started, "l1_semantic_blocks")

            # Step 3: 仅对变更 blocks 提取新 mentions
            stage_started = self._mark_stage(run_id, base_meta, "entity_mentions", semantic_block_count=len(block_ids))
            new_mentions = self._extract_mentions_for_blocks(
                int(book_id), run_id, changed_block_payloads, use_ai=use_ai, ai_max_workers=ai_max_workers)
            new_mention_count = len(new_mentions)
            _emit_progress(progress_callback, stage="entity_mentions_new", percent=25,
                message=f"新 mentions: {new_mention_count} 个")

            # Step 4: 合并复用 mentions + 新 mentions
            reused_mentions = self._collect_mentions_from_run(int(book_id), base_run_id_resolved, unchanged_chapter_ids)
            reused_mention_count = len(reused_mentions)
            all_mentions = reused_mentions + new_mentions
            if all_mentions:
                self.database.replace_analysis_entity_mentions(int(book_id), int(run_id), all_mentions)
            mention_count = len(all_mentions)
            self._check_stage_timeout(stage_started, "entity_mentions")
            _emit_progress(progress_callback, stage="entity_mentions", percent=30,
                message=f"实体提及: {mention_count} 个 (复用 {reused_mention_count}, 新增 {new_mention_count})")

            # Step 5: 全量共指消解
            stage_started = self._mark_stage(run_id, base_meta, "entity_coreference", mention_count=mention_count)
            entity_count = self.run_entity_coreference(int(book_id), run_id, update_run=False, use_ai=use_ai)
            self._check_stage_timeout(stage_started, "entity_coreference")
            _emit_progress(progress_callback, stage="entity_coreference", percent=45,
                message=f"共指消解: {entity_count} 个实体")

            # Step 6: 仅对变更 blocks 提取新 facts
            stage_started = self._mark_stage(run_id, base_meta, "atomic_facts", mention_count=mention_count, entity_count=entity_count)
            new_facts = self._extract_facts_for_blocks(
                int(book_id), run_id, changed_block_payloads, use_ai=use_ai, ai_max_workers=ai_max_workers)
            new_fact_count = len(new_facts)
            _emit_progress(progress_callback, stage="atomic_facts_new", percent=50,
                message=f"新 facts: {new_fact_count} 个")

            # Step 7: 合并复用 facts + 新 facts
            reused_facts = self._collect_facts_from_run(int(book_id), base_run_id_resolved, unchanged_chapter_ids)
            reused_fact_count = len(reused_facts)
            all_facts = reused_facts + new_facts
            if all_facts:
                self.database.replace_analysis_facts(int(book_id), int(run_id), all_facts)
            fact_count = len(all_facts)
            self._check_stage_timeout(stage_started, "atomic_facts")
            _emit_progress(progress_callback, stage="atomic_facts", percent=60,
                message=f"原子事实: {fact_count} 个 (复用 {reused_fact_count}, 新增 {new_fact_count})")

            # Step 8: 记忆分层（后台静默）、卡片、探针（全量重新执行）
            self._mark_stage(run_id, base_meta, "memory_layer", mention_count=mention_count, entity_count=entity_count, fact_count=fact_count)
            self.run_memory_layer_background(int(book_id), run_id, use_ai=False)
            # 后台执行中，主流程使用占位结果
            memory_result = {"fact_count": fact_count, "classified_fact_count": 0, "summary_fact_count": 0}
            _emit_progress(progress_callback, stage="memory_layer", percent=70,
                message="记忆分层：后台静默进行中")
            stage_started = self._mark_stage(run_id, base_meta, "card_events", mention_count=mention_count, entity_count=entity_count, fact_count=fact_count)
            card_result = self.run_card_events(int(book_id), run_id, update_run=False)
            self._check_stage_timeout(stage_started, "card_events")
            _emit_progress(progress_callback, stage="card_events", percent=85,
                message=f"卡片生成: {card_result.active_card_count} 张")
            stage_started = self._mark_stage(run_id, base_meta, "probe_plans", card_count=card_result.active_card_count)
            probe_result = self.run_probe_plans(int(book_id), run_id, update_run=False)
            self._check_stage_timeout(stage_started, "probe_plans")
            _emit_progress(progress_callback, stage="probe_plans", percent=95,
                message=f"探针: {probe_result.plan_count} 个")

            summary = (
                f"Incremental: {len(changed_chapters)} chapters changed, "
                f"{reused_block_payloads} blocks reused, {len(changed_block_payloads)} new blocks, "
                f"{reused_mention_count} mentions reused, {new_mention_count} new, "
                f"{reused_fact_count} facts reused, {new_fact_count} new, "
                f"{card_result.active_card_count} cards, {probe_result.plan_count} probes.")
            result_meta = self._stage_meta({
                **base_meta,
                "semantic_block_count": len(block_ids), "mention_count": mention_count, "entity_count": entity_count,
                "fact_count": memory_result["fact_count"], "memory_fact_count": memory_result["classified_fact_count"],
                "memory_summary_fact_count": memory_result["summary_fact_count"],
                "event_count": card_result.event_count, "card_count": card_result.active_card_count,
                "probe_plan_count": probe_result.plan_count, "probe_result_count": probe_result.result_count,
                "probe_inconsistent_count": probe_result.inconsistent_count,
                "probe_manual_review_count": probe_result.manual_review_count,
                "backtrack_task_count": probe_result.backtrack_task_count,
                "source_chapter_count": len(chapter_payload), "reused_block_count": len(reused_block_payloads),
                "new_block_count": len(changed_block_payloads), "reused_mention_count": reused_mention_count,
                "new_mention_count": new_mention_count, "reused_fact_count": reused_fact_count,
                "new_fact_count": new_fact_count,
            }, "completed")
            if use_ai and self.ai_provider is not None:
                result_meta["ai_cache_hits"] = self.ai_provider.cache_hits
                result_meta["ai_call_count"] = self.ai_provider.call_count

            self.store.create_audit_log(
                int(book_id), run_id=run_id, action="analysis_v3_incremental_run_completed",
                target_type="analysis_run", target_uid=str(run_id), new_value=result_meta,
                reason=f"incremental analysis: {len(changed_chapters)} chapters changed, base_run_id={base_run_id_resolved}")
            self.store.update_run_status(run_id, "probes_ready", summary=summary, meta=result_meta)
            return AnalysisPipelineV3Result(
                run_id=run_id, status="probes_ready", block_count=len(block_ids),
                mention_count=mention_count, entity_count=entity_count,
                fact_count=memory_result["fact_count"], card_count=card_result.active_card_count,
                summary=summary, meta=result_meta,
                memory_fact_count=memory_result["classified_fact_count"],
                memory_summary_fact_count=memory_result["summary_fact_count"],
                probe_plan_count=probe_result.plan_count, probe_result_count=probe_result.result_count,
                probe_inconsistent_count=probe_result.inconsistent_count)
        except TimeoutError as exc:
            logger.warning("Incremental analysis V3 timeout for book_id=%s run_id=%s: %s", book_id, run_id, exc)
            self.store.update_run_status(
                run_id,
                "failed",
                error_text="分析阶段超时，请稍后重试或降低批量上限",
                meta={**base_meta, "pipeline_failed": True, "pipeline_timeout": True, "timeout_error": str(exc)},
            )
            raise
        except Exception as exc:
            logger.exception("Incremental analysis V3 failed for book_id=%s run_id=%s", book_id, run_id)
            self.store.update_run_status(run_id, "failed", error_text=str(exc), meta={**base_meta, "pipeline_failed": True})
            raise

    def _find_base_run(self, book_id: int, base_run_id: int | None = None):
        if base_run_id is not None:
            run = self.store.get_run(int(base_run_id))
            if run and str(run["pipeline_version"] or "").startswith("analysis_v3"):
                return run
            return None
        runs = self.store.list_runs(int(book_id), limit=20)
        for row in reversed(runs):
            status = str(row["status"] or "")
            version = str(row["pipeline_version"] or "")
            if status in {"probes_ready", "cards_ready", "facts_ready", "entities_ready", "mentions_ready"} and version.startswith("analysis_v3"):
                return row
        return None

    def _compute_chapter_diff(self, book_id: int, base_run_id: int, current_chapters: list[dict[str, Any]]) -> dict[str, Any]:
        existing_blocks = self.store.list_blocks(int(book_id), run_id=base_run_id, limit=None)
        chapter_hashes: dict[int, str] = {}
        fallback_hashers: dict[int, Any] = {}
        for row in existing_blocks:
            cid = _int_or_none(row["chapter_id"])
            if cid is None:
                continue
            stored_hash = _chapter_content_hash_from_block(row)
            if stored_hash:
                chapter_hashes[cid] = stored_hash
                fallback_hashers.pop(cid, None)
                continue
            if cid in chapter_hashes:
                continue
            if cid not in fallback_hashers:
                fallback_hashers[cid] = hashlib.sha256()
            fallback_hashers[cid].update(str(row["text"] or "").encode("utf-8"))

        current_hashes: dict[int, str] = {}
        for ch in current_chapters:
            cid = _int_or_none(ch.get("id"))
            if cid is None:
                continue
            current_hashes[cid] = hashlib.sha256(str(ch.get("content") or "").encode("utf-8")).hexdigest()

        existing_chapter_hashes = {
            **{cid: h.hexdigest() for cid, h in fallback_hashers.items()},
            **chapter_hashes,
        }
        current_ids = set(current_hashes.keys())
        existing_ids = set(existing_chapter_hashes.keys())
        added_ids = current_ids - existing_ids
        deleted_ids = existing_ids - current_ids
        common_ids = current_ids & existing_ids
        changed_ids = {cid for cid in common_ids if current_hashes[cid] != existing_chapter_hashes[cid]}
        unchanged_ids = common_ids - changed_ids

        return {
            "added": [ch for ch in current_chapters if _int_or_none(ch.get("id")) in added_ids],
            "changed": [ch for ch in current_chapters if _int_or_none(ch.get("id")) in changed_ids],
            "unchanged_ids": list(unchanged_ids), "deleted_ids": list(deleted_ids),
        }

    def _reuse_blocks_from_run(self, book_id: int, base_run_id: int, chapter_ids: list[int]) -> list[dict[str, Any]]:
        if not chapter_ids:
            return []
        result: list[dict[str, Any]] = []
        for cid in chapter_ids:
            for row in self.store.list_blocks(int(book_id), run_id=base_run_id, chapter_id=cid, limit=500):
                result.append(dict(row))
        return result

    def _collect_mentions_from_run(self, book_id: int, base_run_id: int, chapter_ids: list[int]) -> list[dict[str, Any]]:
        if not chapter_ids:
            return []
        mentions = self.entity_store.list_mentions(int(book_id), run_id=base_run_id, limit=None)
        return [dict(m) for m in mentions if _int_or_none(m.get("chapter_id")) in set(chapter_ids)]

    def _collect_facts_from_run(self, book_id: int, base_run_id: int, chapter_ids: list[int]) -> list[dict[str, Any]]:
        if not chapter_ids:
            return []
        facts = self.fact_store.list_facts(int(book_id), run_id=base_run_id, limit=None)
        return [dict(f) for f in facts if _int_or_none(f.get("chapter_id")) in set(chapter_ids)]

    def _extract_mentions_for_blocks(
        self, book_id: int, run_id: int, blocks: list[dict[str, Any]], *,
        use_ai: bool = False, ai_max_workers: int = 4,
    ) -> list[dict[str, Any]]:
        if not blocks:
            return []
        if use_ai and self.ai_provider is not None:
            try:
                mentions = self._parallel_ai_extract_mentions(blocks, int(book_id), int(run_id), max_workers=ai_max_workers)
                if mentions:
                    return [m.as_analysis_mention() for m in mentions]
            except Exception as exc:
                logger.warning("AI extract_mentions failed, falling back to rules: %s", exc)
        extractor = MentionExtractor.from_database(self.database, int(book_id))
        mentions = extractor.extract_from_blocks(book_id=int(book_id), run_id=int(run_id), blocks=blocks)
        return [m.as_analysis_mention() for m in mentions]

    def _extract_facts_for_blocks(
        self, book_id: int, run_id: int, blocks: list[dict[str, Any]], *,
        use_ai: bool = False, ai_max_workers: int = 4,
    ) -> list[dict[str, Any]]:
        if not blocks:
            return []
        mentions = self.entity_store.list_mentions(int(book_id), run_id=int(run_id), limit=None)
        entities = self.entity_store.list_entities(int(book_id), run_id=int(run_id), limit=None)
        if use_ai and self.ai_provider is not None:
            try:
                facts = self._parallel_ai_extract_facts(blocks, entities, int(book_id), int(run_id), max_workers=ai_max_workers)
                if facts:
                    return [f.as_dict() for f in facts]
            except Exception as exc:
                logger.warning("AI extract_facts failed, falling back to rules: %s", exc)
        facts = FactExtractor().extract_from_context(
            book_id=int(book_id), run_id=int(run_id), blocks=blocks, mentions=mentions, entities=entities)
        return [f.as_dict() for f in facts]


def _chapter_content_hash_from_block(row: Any) -> str:
    raw: Any = ""
    try:
        raw = row["metadata_json"] or ""
    except (KeyError, IndexError, TypeError):
        if isinstance(row, dict):
            raw = row.get("metadata_json") or row.get("metadata") or ""
    if not raw:
        return ""
    if isinstance(raw, str):
        try:
            metadata = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return ""
    else:
        metadata = raw
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("chapter_content_hash") or "").strip()
