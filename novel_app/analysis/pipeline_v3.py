"""Analysis Pipeline V3 — 主入口和编排逻辑。

公共 API：
  - AnalysisPipelineV3       主类，通过 Mixin 组合各阶段和增量方法
  - AnalysisPipelineV3Result 分析结果 dataclass
  - PIPELINE_V3_VERSION      版本常量

各阶段执行逻辑见 pipeline_v3_stages.PipelineV3StagesMixin
增量分析逻辑见 pipeline_v3_incremental.PipelineV3IncrementalMixin
"""
from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from novel_app.analysis.backtrack import BacktrackPlanner
from novel_app.analysis.card_coordinator import CardCoordinator, CardCoordinatorResult
from novel_app.analysis.consistency_checker import ConsistencyChecker
from novel_app.analysis.entity_identity_resolver import EntityIdentityResolver
from novel_app.analysis.entity_store import EntityStore
from novel_app.analysis.fact_store import FactStore
from novel_app.analysis.memory_classifier import MemoryClassifier
from novel_app.analysis.memory_compressor import MemoryCompressor
from novel_app.analysis.pipeline_v3_config import (
    PipelineV3Config,
)
from novel_app.analysis.pipeline_v3_incremental import PipelineV3IncrementalMixin
from novel_app.analysis.pipeline_v3_stages import PipelineV3StagesMixin
from novel_app.analysis.probe_executor import ProbeExecutor
from novel_app.analysis.probe_planner import ProbePlanner
from novel_app.analysis.semantic_chunker import SemanticChunker
from novel_app.analysis.store import AnalysisStore
from novel_app.analysis.utils import chapter_dict as _chapter_dict
from novel_app.analysis.vector_store import AnalysisVectorStore
from novel_app.database import Database

if TYPE_CHECKING:
    from novel_app.ai.protocols import AIProviderProtocol

logger = logging.getLogger(__name__)
PIPELINE_V3_VERSION = "analysis_v3_m8_probes_v1"

CHAPTER_BATCH_SIZE = 200
AI_MAX_WORKERS = int(os.environ.get("LINGSHU_ANALYSIS_V3_AI_MAX_WORKERS", "2000") or 2000)
STAGE_TIMEOUT_SECONDS = int(os.environ.get("LINGSHU_ANALYSIS_V3_STAGE_TIMEOUT_SECONDS", "1200") or 1200)

PIPELINE_V3_STAGES = [
    {"key": "init", "phase": "M0", "label": "初始化"},
    {"key": "l1_semantic_blocks", "phase": "M1", "label": "语义分块"},
    {"key": "entity_mentions", "phase": "M2", "label": "实体提及抽取"},
    {"key": "entity_coreference", "phase": "M3", "label": "共指消解"},
    {"key": "identity_resolve", "phase": "M3+", "label": "身份消解"},
    {"key": "atomic_facts", "phase": "M4", "label": "原子事实抽取"},
    {"key": "memory_layer", "phase": "M7", "label": "记忆分层"},
    {"key": "card_events", "phase": "M5", "label": "卡片生成"},
    {"key": "card_post_process", "phase": "M5+", "label": "卡片后处理"},
    {"key": "probe_plans", "phase": "M8", "label": "文章探针"},
    {"key": "completed", "phase": "Done", "label": "完成"},
]
_PIPELINE_V3_STAGE_INDEX = {stage["key"]: index for index, stage in enumerate(PIPELINE_V3_STAGES)}
_PIPELINE_V3_STAGE_MAP = {stage["key"]: stage for stage in PIPELINE_V3_STAGES}


class AnalysisPipelineV3Cancelled(RuntimeError):  # noqa: N818 — 对外异常名已被 ws/测试引用，改名破坏兼容
    """Raised when a V3 analysis run is cancelled cooperatively."""


@dataclass(frozen=True)
class AnalysisPipelineV3Result:
    run_id: int
    status: str
    block_count: int
    mention_count: int
    entity_count: int
    fact_count: int
    card_count: int
    summary: str
    meta: dict[str, Any]
    memory_fact_count: int = 0
    memory_summary_fact_count: int = 0
    probe_plan_count: int = 0
    probe_result_count: int = 0
    probe_inconsistent_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "status": self.status, "block_count": self.block_count,
            "mention_count": self.mention_count, "entity_count": self.entity_count,
            "fact_count": self.fact_count, "card_count": self.card_count,
            "summary": self.summary, "meta": self.meta,
            "memory_fact_count": self.memory_fact_count,
            "memory_summary_fact_count": self.memory_summary_fact_count,
            "probe_plan_count": self.probe_plan_count, "probe_result_count": self.probe_result_count,
            "probe_inconsistent_count": self.probe_inconsistent_count,
        }


class AnalysisPipelineV3(PipelineV3StagesMixin, PipelineV3IncrementalMixin):
    """Analysis Pipeline V3 主类。

    通过 Mixin 继承组合：
    - PipelineV3StagesMixin: 各分析阶段的执行方法
    - PipelineV3IncrementalMixin: 增量分析方法
    """

    def __init__(
        self, database: Database, *,
        chunker: SemanticChunker | None = None, store: AnalysisStore | None = None,
        entity_store: EntityStore | None = None, fact_store: FactStore | None = None,
        card_coordinator: CardCoordinator | None = None,
        backtrack_planner: BacktrackPlanner | None = None,
        memory_classifier: MemoryClassifier | None = None,
        memory_compressor: MemoryCompressor | None = None,
        probe_planner: ProbePlanner | None = None, probe_executor: ProbeExecutor | None = None,
        ai_provider: AIProviderProtocol | Any | None = None,
    ) -> None:
        self.database = database
        self.chunker = chunker or SemanticChunker()
        self.store = store or AnalysisStore(database)
        self.entity_store = entity_store or EntityStore(database)
        self.fact_store = fact_store or FactStore(database)
        self.memory_classifier = memory_classifier or MemoryClassifier()
        self.memory_compressor = memory_compressor or MemoryCompressor()
        self.card_coordinator = card_coordinator or CardCoordinator(database, store=self.store, entity_store=self.entity_store, fact_store=self.fact_store)
        self.backtrack_planner = backtrack_planner or BacktrackPlanner(
            database, store=self.store, entity_store=self.entity_store,
            fact_store=self.fact_store, card_coordinator=self.card_coordinator)
        self.ai_provider = ai_provider
        self.probe_planner = probe_planner or ProbePlanner()
        self.probe_executor = probe_executor or ProbeExecutor(
            database, store=self.store, fact_store=self.fact_store,
            checker=ConsistencyChecker(ai_provider=self.ai_provider),
            backtrack_planner=self.backtrack_planner)
        self.vector_store: AnalysisVectorStore | None = None
        try:
            storage_dir = str(database.db_path.parent / "analysis_vectors")
            self.vector_store = AnalysisVectorStore(storage_dir)
        except Exception:
            logger.warning("Failed to initialize AnalysisVectorStore, vector features disabled")

    def _stage_meta(self, current_meta: dict[str, Any] | None, stage_key: str, **extra: Any) -> dict[str, Any]:
        meta = dict(current_meta or {})
        stage = _PIPELINE_V3_STAGE_MAP.get(stage_key) or _PIPELINE_V3_STAGE_MAP["init"]
        stage_key = str(stage["key"])
        stage_index = _PIPELINE_V3_STAGE_INDEX.get(stage_key, 0)
        next_stage = PIPELINE_V3_STAGES[stage_index + 1]["key"] if stage_index + 1 < len(PIPELINE_V3_STAGES) else ""
        meta.update({
            "stages": [dict(item) for item in PIPELINE_V3_STAGES],
            "current_step": stage_key,
            "current_phase": stage["phase"],
            "current_stage_label": stage["label"],
            "current_stage_index": stage_index,
            "stage_count": len(PIPELINE_V3_STAGES),
            "next_step": next_stage,
            "stage_timeout_seconds": STAGE_TIMEOUT_SECONDS,
        })
        meta.update(extra)
        return meta

    def _mark_stage(self, run_id: int, base_meta: dict[str, Any], stage_key: str, **extra: Any) -> float:
        meta = self._stage_meta(base_meta, stage_key, **extra)
        base_meta.clear()
        base_meta.update(meta)
        self.store.update_run_status(
            int(run_id),
            "running",
            summary=f"Running: {meta.get('current_stage_label') or stage_key}",
            meta=meta,
        )
        return time.monotonic()

    def _check_stage_timeout(self, started_at: float, stage_key: str) -> None:
        if STAGE_TIMEOUT_SECONDS <= 0:
            return
        elapsed = time.monotonic() - started_at
        if elapsed > STAGE_TIMEOUT_SECONDS:
            stage = _PIPELINE_V3_STAGE_MAP.get(stage_key, {"label": stage_key})
            raise TimeoutError(
                f"Analysis V3 stage timeout: {stage.get('label', stage_key)} exceeded {STAGE_TIMEOUT_SECONDS} seconds"
            )

    @classmethod
    def from_config(cls, config: PipelineV3Config) -> AnalysisPipelineV3:
        """从 PipelineV3Config 创建实例（推荐方式）。"""
        database = config.db
        stores = config.stores
        planners = config.planners
        memory = config.memory
        return cls(
            database,
            chunker=config.chunker,
            store=stores.analysis if stores else None,
            entity_store=stores.entity if stores else None,
            fact_store=stores.fact if stores else None,
            card_coordinator=config.coordinator,
            backtrack_planner=planners.backtrack if planners else None,
            memory_classifier=memory.classifier if memory else None,
            memory_compressor=memory.compressor if memory else None,
            probe_planner=planners.probe if planners else None,
            ai_provider=config.ai_provider,
        )

    @classmethod
    def from_params(
        cls, database: Database, *,
        chunker: SemanticChunker | None = None, store: AnalysisStore | None = None,
        entity_store: EntityStore | None = None, fact_store: FactStore | None = None,
        card_coordinator: CardCoordinator | None = None,
        backtrack_planner: BacktrackPlanner | None = None,
        memory_classifier: MemoryClassifier | None = None,
        memory_compressor: MemoryCompressor | None = None,
        probe_planner: ProbePlanner | None = None, probe_executor: ProbeExecutor | None = None,
        ai_provider: AIProviderProtocol | Any | None = None,
    ) -> AnalysisPipelineV3:
        """从位置参数创建实例（向后兼容的工厂方法）。

        等价于直接调用构造函数，保留此方法以便旧代码迁移。
        """
        return cls(
            database,
            chunker=chunker, store=store, entity_store=entity_store,
            fact_store=fact_store, card_coordinator=card_coordinator,
            backtrack_planner=backtrack_planner, memory_classifier=memory_classifier,
            memory_compressor=memory_compressor, probe_planner=probe_planner,
            probe_executor=probe_executor, ai_provider=ai_provider,
        )

    def start_run(
        self, book_id: int, *, chapters: list[dict[str, Any]] | None = None,
        execute_l1: bool = True, meta: dict[str, Any] | None = None,
        progress_callback: Any | None = None, use_ai: bool = False,
        chapter_batch_size: int = CHAPTER_BATCH_SIZE, ai_max_workers: int = AI_MAX_WORKERS,
        cancel_event: Any | None = None,
) -> AnalysisPipelineV3Result:
        # 存储 cancel_event 到实例，供 run_aimd_pool 等阶段方法检查取消信号
        self._cancel_event = cancel_event
        if hasattr(self, "chunker") and self.chunker is not None:
            self.chunker._cancel_event = cancel_event
        _raise_if_cancelled(cancel_event)
        chapter_payload = [_chapter_dict(item) for item in (chapters if chapters is not None else self._load_book_chapters(book_id))]
        input_hash = self._input_hash(chapter_payload)
        base_meta = self._stage_meta({
            "pipeline_version": PIPELINE_V3_VERSION, "pipeline_family": "analysis_v3",
            "ai_invoked": use_ai and self.ai_provider is not None,
            "ai_stages": [], "ai_fallback_stages": [], "ai_cache_hits": 0, "ai_call_count": 0,
            **(meta or {}),
        }, "init", source_chapter_count=len(chapter_payload))
        run_id = self.store.create_run(
            int(book_id), scope_type="book", status="running",
            pipeline_version=PIPELINE_V3_VERSION, input_hash=input_hash,
            meta=base_meta, summary="Analysis V3 run created.")
        try:
            _raise_if_cancelled(cancel_event)
            if not execute_l1:
                return self._create_pending_result(int(book_id), run_id, base_meta)

            stage_started = self._mark_stage(run_id, base_meta, "l1_semantic_blocks", source_chapter_count=len(chapter_payload))

            # 尝试跨 run 复用 M1 分块结果（相同 book_id + input_hash 的历史 run 已有 block）
            reused_source_run_id: int | None = None
            all_block_payloads: list[dict[str, Any]] = []
            try:
                source_run = self.store.find_reusable_run_for_input_hash(
                    int(book_id), input_hash, exclude_run_id=run_id,
                )
                if source_run is not None:
                    source_run_id = int(source_run["id"])
                    cloned_count = self.store.clone_blocks(int(book_id), source_run_id, run_id)
                    if cloned_count > 0:
                        for row in self.store.list_blocks(int(book_id), run_id=run_id, limit=None):
                            all_block_payloads.append(self._block_row_to_payload(row))
                        reused_source_run_id = source_run_id
                        logger.info("M1 blocks reused from run_id=%d → run_id=%d: %d blocks cloned (skipping chunking)",
                                    source_run_id, run_id, cloned_count)
                        _emit_progress(progress_callback, stage="l1_semantic_blocks", percent=10,
                            message=f"语义分块复用: 从 run {source_run_id} 克隆 {cloned_count} 个 block，跳过分块")
            except Exception as exc:
                logger.warning("M1 block reuse failed, falling back to chunking: %s", exc)

            if reused_source_run_id is None:
                # 正常分批处理章节：大书分批分块，减少内存峰值
                total_chapters = len(chapter_payload)
                for batch_start in range(0, max(1, total_chapters), chapter_batch_size):
                    _raise_if_cancelled(cancel_event)
                    batch_chapters = chapter_payload[batch_start:batch_start + chapter_batch_size]
                    _emit_progress(progress_callback, stage="l1_semantic_blocks",
                        percent=5, message=f"正在语义分块: 章节 {batch_start + 1}-{min(batch_start + chapter_batch_size, total_chapters)}/{total_chapters}...")
                    batch_blocks = self.chunker.chunk_chapters(int(book_id), batch_chapters, pipeline_version=PIPELINE_V3_VERSION, use_ai=use_ai, ai_provider=self.ai_provider if use_ai else None)
                    all_block_payloads.extend(block.as_analysis_block() for block in batch_blocks)
                    _emit_progress(progress_callback, stage="l1_semantic_blocks",
                        percent=min(10, 5 + 5 * (batch_start + 1) // max(1, total_chapters)),
                        message=f"语义分块: {len(all_block_payloads)} 个 block (章节 {batch_start + 1}-{min(batch_start + chapter_batch_size, total_chapters)}/{total_chapters})")
                _emit_progress(progress_callback, stage="l1_semantic_blocks", percent=10, message=f"语义分块完成: {len(all_block_payloads)} 个 block")
                _raise_if_cancelled(cancel_event)
                block_ids = self.store.save_blocks(int(book_id), run_id, all_block_payloads) if all_block_payloads else []
            else:
                # 复用模式下 blocks 已通过 clone 落库，不需要再 save_blocks
                block_ids = []
            self._check_stage_timeout(stage_started, "l1_semantic_blocks")

            # 预估 AI 调用量
            if use_ai and self.ai_provider is not None:
                total_chars = sum(len(str(b.get("text") or "")) for b in all_block_payloads)
                block_count = len(all_block_payloads)
                est_windows = max(1, total_chars // 8000)
                est_calls = est_windows * 2 + 2 + 3  # mention + fact + coreference + post-process
                adaptive_w = max(4, min(block_count, max(4, est_windows // 2), AI_MAX_WORKERS))
                logger.info("AI analysis estimate: %d blocks, %d chars, ~%d windows, ~%d API calls, %d workers",
                            block_count, total_chars, est_windows, est_calls, adaptive_w)

            self._index_blocks_to_vector_store(int(book_id), all_block_payloads)

            blocks_to_process = all_block_payloads
            skipped_block_count = 0

            _raise_if_cancelled(cancel_event)
            stage_started = self._mark_stage(run_id, base_meta, "entity_mentions", semantic_block_count=len(all_block_payloads))
            mention_count = self.run_entity_mentions(int(book_id), run_id, blocks=blocks_to_process, update_run=False, use_ai=use_ai, ai_max_workers=ai_max_workers)
            self._check_stage_timeout(stage_started, "entity_mentions")
            _emit_progress(progress_callback, stage="entity_mentions", percent=25, message=f"实体提及抽取完成: {mention_count} 个候选")
            _raise_if_cancelled(cancel_event)
            stage_started = self._mark_stage(run_id, base_meta, "entity_coreference", semantic_block_count=len(all_block_payloads), mention_count=mention_count)
            self._index_mentions_to_vector_store(int(book_id), run_id)
            entity_count = self.run_entity_coreference(int(book_id), run_id, update_run=False, use_ai=use_ai)
            self._check_stage_timeout(stage_started, "entity_coreference")
            _emit_progress(progress_callback, stage="entity_coreference", percent=40, message=f"共指消解完成: {entity_count} 个实体候选")

            # ── 全局身份消解：跨章节识别同一角色的不同称号/身份 ──
            _raise_if_cancelled(cancel_event)
            stage_started = self._mark_stage(run_id, base_meta, "identity_resolve", mention_count=mention_count, entity_count=entity_count)
            identity_result = self._run_identity_resolve(int(book_id), run_id, use_ai)
            if identity_result and identity_result.merge_count:
                base_meta["identity_merges"] = identity_result.merge_count
                entity_count = len(self.entity_store.list_entities(int(book_id), run_id=int(run_id), limit=None))
                _emit_progress(progress_callback, stage="identity_resolve", percent=43,
                    message=f"身份消解: 合并 {identity_result.merge_count} 个跨身份实体")
            self._check_stage_timeout(stage_started, "identity_resolve")

            _raise_if_cancelled(cancel_event)
            stage_started = self._mark_stage(run_id, base_meta, "atomic_facts", mention_count=mention_count, entity_count=entity_count)
            self._index_entities_to_vector_store(int(book_id), run_id)
            fact_count = self.run_atomic_facts(int(book_id), run_id, blocks=blocks_to_process, update_run=False, use_ai=use_ai, ai_max_workers=ai_max_workers)
            self._check_stage_timeout(stage_started, "atomic_facts")
            _emit_progress(progress_callback, stage="atomic_facts", percent=55, message=f"原子事实抽取完成: {fact_count} 个候选")

            # M4 完成后同步伏笔到 foreshadows 表（容错，失败不影响主流程）
            try:
                from novel_app.analysis.foreshadow_sync import sync_foreshadows_from_facts
                synced = sync_foreshadows_from_facts(self.database, int(book_id), run_id=run_id)
                if synced:
                    _emit_progress(progress_callback, stage="atomic_facts", percent=56, message=f"伏笔同步完成: {synced} 条")
            except Exception as _e:
                logger.warning("foreshadow sync failed (non-fatal): %s", _e)

            _raise_if_cancelled(cancel_event)
            stage_started = self._mark_stage(run_id, base_meta, "memory_layer", mention_count=mention_count, entity_count=entity_count, fact_count=fact_count)
            memory_result = self.run_memory_layer(int(book_id), run_id, update_run=False, use_ai=use_ai)
            self._check_stage_timeout(stage_started, "memory_layer")
            _emit_progress(progress_callback, stage="memory_layer", percent=65,
                           message=f"记忆分层完成: 分类 {memory_result['classified_fact_count']} 条, 摘要 {memory_result['summary_fact_count']} 条")
            _raise_if_cancelled(cancel_event)
            stage_started = self._mark_stage(run_id, base_meta, "card_events", mention_count=mention_count, entity_count=entity_count, fact_count=fact_count)
            card_result = self.run_card_events(int(book_id), run_id, update_run=False, use_ai=use_ai)
            self._check_stage_timeout(stage_started, "card_events")
            _emit_progress(progress_callback, stage="card_events", percent=80, message=f"卡片生成完成: {card_result.active_card_count} 张候选卡")

            # ── 卡片后处理：LLM 去重合并 + 质量审核 ──
            _raise_if_cancelled(cancel_event)
            stage_started = self._mark_stage(run_id, base_meta, "card_post_process", card_count=card_result.active_card_count)
            post_result = self._run_card_post_process(int(book_id), run_id, use_ai)
            if post_result and (post_result.merge_count or post_result.delete_count or post_result.type_fix_count):
                base_meta["card_post_merges"] = post_result.merge_count
                base_meta["card_post_deletes"] = post_result.delete_count
                base_meta["card_post_type_fixes"] = post_result.type_fix_count
                _emit_progress(progress_callback, stage="card_post_process", percent=83,
                    message=f"卡片后处理: 合并{post_result.merge_count} 删除{post_result.delete_count} 修正{post_result.type_fix_count}")
                # 重新统计活跃卡片数
                cards = [dict(row) for row in self.store.list_cards(int(run_id))]
                active = [c for c in cards if str(c.get("status") or "") != "superseded"]
                card_result = CardCoordinatorResult(
                    event_count=card_result.event_count,
                    card_count=card_result.card_count,
                    active_card_count=len(active),
                    dependency_count=card_result.dependency_count,
                    engine=card_result.engine,  # 保留原有 engine
                )
            self._check_stage_timeout(stage_started, "card_post_process")

            _raise_if_cancelled(cancel_event)
            stage_started = self._mark_stage(run_id, base_meta, "probe_plans", card_count=card_result.active_card_count)
            probe_result = self.run_probe_plans(int(book_id), run_id, update_run=False, use_ai=use_ai)
            self._check_stage_timeout(stage_started, "probe_plans")
            _emit_progress(progress_callback, stage="probe_plans", percent=95, message=f"探针规划完成: {probe_result.plan_count} 个探针")

            _raise_if_cancelled(cancel_event)
            if use_ai and self.ai_provider is not None:
                ai_stages, ai_fallback_stages = [], []
                # M1 语义分块（可选）
                chunk_engine = getattr(self.chunker, '_last_engine', 'rule')
                if chunk_engine == "ai_assisted":
                    ai_stages.append("chunks")
                # M2/M3/M4（已有）
                for stage_name, stage_engine in [
                    ("mentions", getattr(self, '_last_mention_engine', 'rule')),
                    ("coreference", getattr(self, '_last_coreference_engine', 'rule')),
                    ("facts", getattr(self, '_last_facts_engine', 'rule')),
                    # M7 记忆分层
                    ("memory", getattr(self.memory_classifier, '_last_engine', 'rule')),
                    # M5 卡片生成
                    ("cards", getattr(self, '_last_card_engine', getattr(self.card_coordinator, '_last_card_engine', 'rule'))),
                    # M8 探针规划
                    ("probes", getattr(self.probe_planner, '_last_engine', 'rule')),
                ]:
                    if stage_engine == "ai":
                        ai_stages.append(stage_name)
                    elif stage_engine == "rule_fallback":
                        ai_fallback_stages.append(stage_name)
                base_meta["ai_stages"] = ai_stages
                base_meta["ai_fallback_stages"] = ai_fallback_stages

            _raise_if_cancelled(cancel_event)
            return self._finalize_run(
                int(book_id), run_id, base_meta, chapter_payload, block_ids,
                mention_count, entity_count, fact_count, memory_result, card_result, probe_result,
                skipped_block_count, chapter_batch_size, use_ai)
        except AnalysisPipelineV3Cancelled:
            logger.info("Analysis V3 pipeline cancelled for book_id=%s run_id=%s", book_id, run_id)
            self.store.update_run_status(run_id, "cancelled", error_text="分析运行已取消", meta={**base_meta, "pipeline_cancelled": True})
            raise
        except TimeoutError as exc:
            logger.warning("Analysis V3 pipeline timeout for book_id=%s run_id=%s: %s", book_id, run_id, exc)
            self.store.update_run_status(
                run_id,
                "failed",
                error_text="分析阶段超时，请稍后重试或降低批量上限",
                meta={**base_meta, "pipeline_failed": True, "pipeline_timeout": True, "timeout_error": str(exc)},
            )
            raise
        except Exception:
            logger.exception("Analysis V3 pipeline failed for book_id=%s run_id=%s", book_id, run_id)
            self.store.update_run_status(run_id, "failed", error_text="分析运行失败，请稍后重试", meta={**base_meta, "pipeline_failed": True})
            raise

    def _create_pending_result(self, book_id: int, run_id: int, base_meta: dict) -> AnalysisPipelineV3Result:
        summary = "Analysis V3 run created; L1 semantic block generation is pending."
        result_meta = self._stage_meta({**base_meta,
                       "semantic_block_count": 0, "mention_count": 0, "entity_count": 0,
                       "fact_count": 0, "card_count": 0, "probe_plan_count": 0,
                       "probe_result_count": 0, "probe_inconsistent_count": 0}, "init")
        self.store.update_run_status(run_id, "created", summary=summary, meta=result_meta)
        return AnalysisPipelineV3Result(run_id=run_id, status="created", block_count=0,
            mention_count=0, entity_count=0, fact_count=0, card_count=0, summary=summary, meta=result_meta)

    def _finalize_run(self, book_id, run_id, base_meta, chapter_payload, block_ids,
                      mention_count, entity_count, fact_count, memory_result, card_result, probe_result,
                      skipped_block_count, chapter_batch_size, use_ai) -> AnalysisPipelineV3Result:
        summary = (
            f"Generated {len(block_ids)} semantic blocks, {mention_count} entity mention candidates, "
            f"{entity_count} entity candidates, {fact_count} atomic fact candidates, "
            f"{memory_result['summary_fact_count']} memory summary candidates, "
            f"{card_result.active_card_count} V3 card candidates, "
            f"and {probe_result.plan_count} article probe plans.")
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
            "source_chapter_count": len(chapter_payload), "skipped_block_count": skipped_block_count,
            "chapter_batch_size": chapter_batch_size,
        }, "completed")
        if use_ai and self.ai_provider is not None:
            result_meta["ai_stages"] = base_meta.get("ai_stages", [])
            result_meta["ai_fallback_stages"] = base_meta.get("ai_fallback_stages", [])
            result_meta["ai_cache_hits"] = self.ai_provider.cache_hits
            result_meta["ai_call_count"] = self.ai_provider.call_count
        self.store.create_audit_log(
            book_id, run_id=run_id, action="analysis_v3_l1_blocks_created",
            target_type="analysis_run", target_uid=str(run_id),
            new_value={
                "semantic_block_count": len(block_ids), "mention_count": mention_count,
                "entity_count": entity_count, "fact_count": memory_result["fact_count"],
                "memory_fact_count": memory_result["classified_fact_count"],
                "memory_summary_fact_count": memory_result["summary_fact_count"],
                "event_count": card_result.event_count, "card_count": card_result.active_card_count,
                "probe_plan_count": probe_result.plan_count, "probe_result_count": probe_result.result_count,
                "probe_inconsistent_count": probe_result.inconsistent_count,
                "probe_manual_review_count": probe_result.manual_review_count,
                "backtrack_task_count": probe_result.backtrack_task_count,
                "source_chapter_count": len(chapter_payload),
            },
            reason="analysis v3 m8 semantic blocks, mentions, entities, facts, memory layer, card candidates, and article probes created")
        self.store.update_run_status(run_id, "probes_ready", summary=summary, meta=result_meta)

        # ── 高可信度卡片自动写回 ──
        # 仅在 AI 模式下执行：AI 生成的卡片质量足够高，ars_score >= 阈值且有
        # writeback_target/writeback_fields 的卡片自动写回到业务表，无需用户手动审核。
        # 绕过 candidate_entities 门禁——高可信度卡片不依赖实体审核状态。
        # 规则模式下卡片质量参差，保留 draft 状态等待用户手动审核。
        auto_wb_count = 0
        if use_ai and result_meta.get("ai_stages"):
            auto_wb_count = self._auto_writeback_high_confidence_cards(
                int(book_id), run_id, use_ai=use_ai, ai_invoked=True)
            if auto_wb_count > 0:
                result_meta["auto_writeback_count"] = auto_wb_count

        return AnalysisPipelineV3Result(
            run_id=run_id, status="probes_ready", block_count=len(block_ids),
            mention_count=mention_count, entity_count=entity_count,
            fact_count=memory_result["fact_count"], card_count=card_result.active_card_count,
            summary=summary, meta=result_meta,
            memory_fact_count=memory_result["classified_fact_count"],
            memory_summary_fact_count=memory_result["summary_fact_count"],
            probe_plan_count=probe_result.plan_count, probe_result_count=probe_result.result_count,
            probe_inconsistent_count=probe_result.inconsistent_count)

    def _run_card_post_process(self, book_id: int, run_id: int, use_ai: bool):
        """卡片后处理：LLM 去重合并 + 质量审核。

        仅在 AI 可用时执行。读取当前 run 的所有卡片，
        发送给 LLM 审查，根据返回的 merge/delete/type_fix 指令修改数据库。
        """
        if not use_ai or self.ai_provider is None:
            return None

        try:
            from novel_app.analysis.card_post_processor import CardPostProcessor

            processor = CardPostProcessor(self.ai_provider)
            cards = [dict(row) for row in self.store.list_cards(int(run_id))]
            if not cards:
                return None

            result = processor.process(book_id=int(book_id), run_id=int(run_id), cards=cards)

            # 应用合并
            for merge in result.merges:
                keep_uid = str(merge.get("keep_card_uid") or "")
                merge_uids = merge.get("merge_card_uids") or []
                if not keep_uid or not merge_uids:
                    continue
                for uid in merge_uids:
                    if str(uid) != keep_uid:
                        self.store.supersede_card_by_uid(int(run_id), str(uid))
                logger.info("Card post-process merged %d cards into %s: %s",
                            len(merge_uids), keep_uid, merge.get("reason", ""))

            # 应用删除
            for delete in result.deletes:
                uid = str(delete.get("card_uid") or "")
                if uid:
                    self.store.supersede_card_by_uid(int(run_id), uid)
                    logger.info("Card post-process deleted %s: %s", uid, delete.get("reason", ""))

            # 应用类型修正
            for fix in result.type_fixes:
                uid = str(fix.get("card_uid") or "")
                new_entity_type = str(fix.get("new_entity_type") or "")
                if uid and new_entity_type:
                    self.store.fix_card_entity_type(int(run_id), uid, new_entity_type)
                    logger.info("Card post-process fixed entity type of %s → %s: %s",
                                uid, new_entity_type, fix.get("reason", ""))

            return result
        except Exception as exc:
            logger.warning("Card post-process failed: %s", exc)
            return None

    def _run_identity_resolve(self, book_id: int, run_id: int, use_ai: bool):
        """全局身份消解：跨章节识别同一角色的不同称号/身份。

        仅在 AI 可用时执行。在共指消解之后、事实抽取之前运行，
        将不同名称但实为同一人的实体合并。
        """
        if not use_ai or self.ai_provider is None:
            return None

        try:
            resolver = EntityIdentityResolver(self.ai_provider, self.entity_store, self.fact_store)
            result = resolver.resolve(book_id=int(book_id), run_id=int(run_id))
            if result.merge_count > 0:
                applied = resolver.apply_merges(int(book_id), int(run_id), result.merges)
                logger.info("Identity resolution: merged %d entities across identities", applied)
            return result
        except Exception as exc:
            logger.warning("Identity resolution failed: %s", exc)
            return None

    # 高可信度卡片自动写回的 ars_score 阈值
    _AUTO_WRITEBACK_SCORE_THRESHOLD = float(
        os.environ.get("LINGSHU_V3_AUTO_WRITEBACK_SCORE_THRESHOLD", "0.85") or 0.85)

    def _auto_writeback_high_confidence_cards(
        self,
        book_id: int,
        run_id: int,
        *,
        use_ai: bool,
        ai_invoked: bool,
    ) -> int:
        """高可信度卡片自动写回。

        分析完成后，ars_score >= 阈值且有 writeback_target/writeback_fields 的卡片
        自动写回到业务表。绕过 candidate_entities 门禁——高可信度卡片不依赖
        实体审核状态，避免用户必须先审核所有候选实体才能写回。

        返回成功写回的卡片数。
        """
        import json as _json

        from novel_app.analysis.writeback_card_generator import WritebackCardGenerator

        threshold = self._AUTO_WRITEBACK_SCORE_THRESHOLD
        try:
            cards_raw = self.store.list_cards(run_id)
        except Exception as exc:
            logger.warning("Auto-writeback: list_cards failed for run_id=%s: %s", run_id, exc)
            return 0

        # 筛选高可信度且有写回目标的草案卡片
        qualifying: list[tuple[str, dict[str, Any]]] = []
        for row in cards_raw:
            try:
                status = str(row["status"] or "")
                if status != "draft":
                    continue
                ars_score = float(row["ars_score"] or 0.0)
                if ars_score < threshold:
                    continue
                card_uid = str(row["card_uid"] or "")
                if not card_uid:
                    continue
                payload = _json.loads(str(row["payload_json"] or "{}"))
                if not isinstance(payload, dict):
                    continue
                target = str(payload.get("writeback_target") or "").strip()
                if not target or target == "none":
                    continue
                if not isinstance(payload.get("writeback_fields"), dict):
                    continue
                qualifying.append((card_uid, payload))
            except Exception:
                continue

        if not qualifying:
            return 0

        # 创建写回卡片生成器（AI 模式下需要 LLM 精炼字段）
        writeback_generator = None
        if ai_invoked and self.ai_provider is not None:
            try:
                writeback_generator = WritebackCardGenerator(self.ai_provider)
            except Exception as exc:
                logger.warning("Auto-writeback: writeback generator unavailable: %s", exc)

        applied_count = 0
        # 用 transaction 包裹整个批次：apply_card 内部的 commit 会被抑制，
        # 所有卡片写回作为一个事务提交，大幅减少 SQLite 锁竞争与 fsync 开销。
        # 若某张卡片写回抛异常，仅跳过该卡，不影响其他卡片（异常被捕获）。
        # 注意：内层 _writeback_character 已使用 transaction()，嵌套时内层 commit
        # 会真正提交子事务边界，符合"子操作原子、外层最终统一提交"的语义。
        try:
            with self.database.transaction():
                for card_uid, _payload in qualifying:
                    try:
                        result = self.store.apply_card(
                            book_id,
                            run_id,
                            card_uid,
                            actor="auto_writeback",
                            writeback_generator=writeback_generator,
                            require_writeback_generator=bool(writeback_generator is not None),
                        )
                        if result is not None and str(result["status"] or "") == "applied":
                            applied_count += 1
                            logger.info(
                                "Auto-writeback: card %s applied to %s #%s (book_id=%s run_id=%s)",
                                card_uid,
                                result["applied_table"],
                                result["applied_id"],
                                book_id,
                                run_id,
                            )
                        else:
                            logger.warning(
                                "Auto-writeback: card %s did not reach applied status (book_id=%s run_id=%s)",
                                card_uid, book_id, run_id,
                            )
                    except Exception as exc:
                        logger.warning(
                            "Auto-writeback: card %s failed (book_id=%s run_id=%s): %s",
                            card_uid, book_id, run_id, exc,
                        )
        except Exception as exc:
            # 外层事务回滚意味着已 apply 的卡片状态也回滚——这是有意的：
            # 批次原子性优先，单卡失败不污染数据库状态。下次重试可重新处理。
            logger.error(
                "Auto-writeback: transaction rolled back (book_id=%s run_id=%s): %s",
                book_id, run_id, exc,
            )
            return 0

        if applied_count > 0:
            self.store.create_audit_log(
                book_id, run_id=run_id,
                action="analysis_v3_auto_writeback",
                target_type="analysis_run", target_uid=str(run_id),
                new_value={
                    "auto_writeback_count": applied_count,
                    "qualifying_count": len(qualifying),
                    "score_threshold": threshold,
                },
                reason="high confidence cards auto-applied after v3 analysis",
                actor="auto_writeback",
            )
            logger.info(
                "Auto-writeback: %d/%d cards applied (book_id=%s run_id=%s threshold=%.2f)",
                applied_count, len(qualifying), book_id, run_id, threshold,
            )
        return applied_count

    def _load_book_chapters(self, book_id: int) -> list[dict[str, Any]]:
        rows = self.database.list_chapters(int(book_id))
        chapters: list[dict[str, Any]] = []
        for row in rows:
            chapter = self.database.get_chapter(int(row["id"]))
            if chapter:
                chapters.append(_chapter_dict(chapter))
        return chapters

    @staticmethod
    def _input_hash(chapters: list[dict[str, Any]]) -> str:
        digest = hashlib.sha256()
        for chapter in chapters:
            digest.update(str(chapter.get("id") or "").encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(chapter.get("title") or "").encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(chapter.get("content") or "").encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def _block_row_to_payload(row: Any) -> dict[str, Any]:
        """将 analysis_blocks 的 Row 转换为与 SemanticBlock.as_analysis_block() 一致的 dict 格式。

        解析 chapter_ids_json / chapter_refs_json / metadata_json 为 Python 对象。
        """
        import json as _json
        result = dict(row)
        # 解析 JSON 字段为 Python 对象
        for key_json, key in (("chapter_ids_json", "chapter_ids"), ("chapter_refs_json", "chapter_refs"), ("metadata_json", "metadata")):
            raw = result.pop(key_json, None)
            if raw is None:
                result.setdefault(key, [] if key != "metadata" else {})
            elif isinstance(raw, str):
                try:
                    result[key] = _json.loads(raw)
                except (TypeError, ValueError, _json.JSONDecodeError):
                    result[key] = [] if key != "metadata" else {}
            else:
                result[key] = raw
        return result


def _emit_progress(callback: Any, *, stage: str, percent: int, message: str) -> None:
    """调用进度回调（如果提供）。callback 签名: (stage, percent, message) -> None"""
    if callback is not None and callable(callback):
        with contextlib.suppress(Exception):
            callback(stage, percent, message)


def _raise_if_cancelled(cancel_event: Any | None) -> None:
    if cancel_event is not None and callable(getattr(cancel_event, "is_set", None)) and cancel_event.is_set():
        raise AnalysisPipelineV3Cancelled("Analysis V3 run cancelled")
