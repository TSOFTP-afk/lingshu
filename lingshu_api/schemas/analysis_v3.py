"""
V3 分析引擎 Pydantic 模型 — API 请求/响应校验。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

class AnalysisV3RunCreate(BaseModel):
    execute_l1: bool = Field(default=True, description="是否立即执行 L1 语义分块")
    use_ai: bool = Field(default=False, description="是否启用 AI 增强分析")


class AnalysisV1OneShotRunCreate(BaseModel):
    """V1 一次性读完分析 — 使用 AI 一次性读取全书并生成分析结果。"""
    use_ai: bool = Field(default=True, description="是否启用 AI（V1 一次性读完必须开启 AI）")


class AnalysisV3IncrementalRunCreate(BaseModel):
    base_run_id: int | None = Field(default=None, description="复用的基础运行 ID")
    use_ai: bool = Field(default=False, description="是否启用 AI 增强分析")


class AnalysisV3RunItem(BaseModel):
    id: int
    book_id: int
    scope_type: str = "book"
    status: str
    pipeline_version: str = ""
    input_hash: str = ""
    summary: str = ""
    error_text: str = ""
    meta: dict = Field(default_factory=dict)
    block_count: int = 0
    mention_count: int = 0
    entity_count: int = 0
    fact_count: int = 0
    memory_fact_count: int = 0
    memory_summary_fact_count: int = 0
    event_count: int = 0
    card_count: int = 0
    probe_plan_count: int = 0
    probe_result_count: int = 0
    probe_inconsistent_count: int = 0
    probe_manual_review_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    completed_at: str = ""


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------

class EntityMergeRequest(BaseModel):
    target_entity_uid: str = Field(min_length=1)
    source_entity_uids: list[str] = Field(min_length=1)
    canonical_name: str = Field(default="", max_length=200)
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""
    reason: str = "manual entity merge"


class EntityUpdateRequest(BaseModel):
    canonical_name: str | None = Field(default=None, max_length=200)
    status: Literal["candidate", "accepted", "rejected", "superseded", "reviewed"] | None = None
    summary: str | None = None
    aliases: list[str] | None = None
    actor: Literal["user", "system"] = "user"


class EntitySplitRequest(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list)
    mention_uids: list[str] = Field(default_factory=list)
    fact_uids: list[str] = Field(default_factory=list)
    reason: str = "manual entity split"


class EntityRollbackRequest(BaseModel):
    actor: str = "user"
    reason: str = ""


# ---------------------------------------------------------------------------
# Backtrack
# ---------------------------------------------------------------------------

class BacktrackTaskCreate(BaseModel):
    target_uid: str = Field(min_length=1)
    trigger_type: Literal["manual", "auto", "backtrack"] = "manual"
    reason: str = ""


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

class CardApplyRequest(BaseModel):
    actor: Literal["user", "system"] = "user"
    allow_soft_blockers: bool = Field(default=False, description="人工确认后允许带软阻塞执行单卡写回")


class StepUseAiRequest(BaseModel):
    use_ai: bool = Field(default=False, description="是否启用 AI 增强分析")


class ActiveProbeRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="用户查询文本")


class WritebackRunRequest(BaseModel):
    actor: Literal["user", "system"] = "user"
    allow_soft_blockers: bool = Field(default=False, description="人工确认后允许带软阻塞执行批量写回")


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

class ReviewSummaryItem(BaseModel):
    formal_writeback_allowed: bool = False
    writeback_mode: str = "disabled_for_phase_10"
    entity_status_counts: dict[str, int] = Field(default_factory=dict)
    fact_status_counts: dict[str, int] = Field(default_factory=dict)
    card_status_counts: dict[str, int] = Field(default_factory=dict)
    pending_backtrack_count: int = 0
    manual_review_probe_count: int = 0
    blockers: list[str] = Field(default_factory=list)
    next_step: str = "formal_writeback_gate"
