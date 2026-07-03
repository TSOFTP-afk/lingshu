from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AnalysisCardDraft:
    card_uid: str
    card_type: str
    payload: dict[str, Any]
    diff: dict[str, Any]
    status: str = "draft"
    entity_uid: str = ""
    ars_score: float = 0.0


@dataclass(frozen=True)
class AnalysisApplyResult:
    applied_cards: int
    skipped_cards: int
    snapshot_id: int | None
    audit_log_ids: list[int] = field(default_factory=list)
    updated_chapter_ids: set[int] = field(default_factory=set)
    processed_chapters: int = 0
    unresolved_count: int = 0
    evidence_gate_dropped: int = 0
    weak_evidence_override: bool = False


@dataclass(frozen=True)
class AnalysisWritebackResult:
    updated_chapter_ids: set[int] = field(default_factory=set)
    processed_chapters: int = 0
    unresolved_count: int = 0
    evidence_gate_dropped: int = 0
