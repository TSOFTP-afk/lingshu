from __future__ import annotations

from novel_app.analysis.backtrack import BacktrackPlanner, BacktrackTaskResult
from novel_app.analysis.card_builder import (
    AnalysisCardBuilder,
    BuiltAnalysisCards,
    build_analysis_card_drafts,
    verify_analysis_card_evidence,
)
from novel_app.analysis.card_coordinator import CardCoordinator, CardCoordinatorResult
from novel_app.analysis.card_generators_v3 import V3_CARD_MIN_FACT_CONFIDENCE
from novel_app.analysis.chunker import AnalysisChunk, AnalysisChunker
from novel_app.analysis.coreference import CoreferenceResolver
from novel_app.analysis.entity_resolver import (
    EntityMention,
    EntityResolutionResult,
    EntityResolver,
    ResolvedEntity,
    normalize_entity_alias,
    resolve_payload_entities,
    stable_entity_uid,
)
from novel_app.analysis.entity_store import EntityStore
from novel_app.analysis.evidence import (
    EvidenceGateResult,
    EvidenceRef,
    EvidenceResolution,
    evidence_gate_result,
    evidence_summary,
    extract_evidence_refs,
    resolve_evidence_refs,
)
from novel_app.analysis.fact_extractor import FACT_MIN_CONFIDENCE, FactExtractor
from novel_app.analysis.fact_store import FactStore
from novel_app.analysis.memory_classifier import MemoryClassifier
from novel_app.analysis.memory_compressor import MemoryCompressor
from novel_app.analysis.memory_window import MemoryWindow, MemoryWindowBuilder
from novel_app.analysis.mention_extractor import MENTION_MIN_CONFIDENCE, MentionExtractor, MentionSeed
from novel_app.analysis.models import AnalysisApplyResult, AnalysisCardDraft, AnalysisWritebackResult
from novel_app.analysis.payload_normalizer import (
    has_formal_writeback_content,
    has_unresolved_analysis_items,
    normalize_book_analysis_payload,
)

# DEPRECATED: 三层金字塔系统，已被 V3 替代。新代码应使用 AnalysisPipelineV3。
from novel_app.analysis.pipeline import AnalysisPipeline, AnalysisPipelineResult, extract_block_facts
from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3, AnalysisPipelineV3Result
from novel_app.analysis.probe_executor import ProbeExecutionResult, ProbeExecutor
from novel_app.analysis.probe_planner import SUPPORTED_PROBE_TYPES, ProbePlanner
from novel_app.analysis.schemas_v3 import (
    ANALYSIS_V3_SCHEMA_VERSION,
    AtomicFact,
    EntityMentionCandidate,
    ResolvedEntityCandidate,
    SemanticBlock,
)
from novel_app.analysis.semantic_chunker import SEMANTIC_CHUNKER_VERSION, SemanticChunker
from novel_app.analysis.store import AnalysisStore
from novel_app.analysis.writeback import apply_book_analysis_payload, filter_untrusted_book_analysis_payload
from novel_app.analysis.writeback_card_generator import (
    WritebackCardGenerationError,
    WritebackCardGenerationResult,
    WritebackCardGenerator,
)

__all__ = [
    "AnalysisApplyResult",
    "AnalysisCardBuilder",
    "AnalysisCardDraft",
    "AnalysisWritebackResult",
    "AnalysisChunk",
    "AnalysisChunker",
    "BacktrackPlanner",
    "BacktrackTaskResult",
    "CardCoordinator",
    "CardCoordinatorResult",
    "AnalysisPipeline",
    "AnalysisPipelineResult",
    "AnalysisPipelineV3",
    "AnalysisPipelineV3Result",
    "AnalysisStore",
    "AtomicFact",
    "BuiltAnalysisCards",
    "EntityMention",
    "EntityMentionCandidate",
    "EntityResolutionResult",
    "EntityResolver",
    "EntityStore",
    "CoreferenceResolver",
    "FactExtractor",
    "FactStore",
    "EvidenceGateResult",
    "EvidenceRef",
    "EvidenceResolution",
    "ResolvedEntity",
    "ResolvedEntityCandidate",
    "SemanticBlock",
    "SemanticChunker",
    "MentionExtractor",
    "MentionSeed",
    "MemoryClassifier",
    "MemoryCompressor",
    "MemoryWindow",
    "MemoryWindowBuilder",
    "ProbeExecutionResult",
    "ProbeExecutor",
    "ProbePlanner",
    "MENTION_MIN_CONFIDENCE",
    "FACT_MIN_CONFIDENCE",
    "SUPPORTED_PROBE_TYPES",
    "V3_CARD_MIN_FACT_CONFIDENCE",
    "ANALYSIS_V3_SCHEMA_VERSION",
    "SEMANTIC_CHUNKER_VERSION",
    "WritebackCardGenerationError",
    "WritebackCardGenerationResult",
    "WritebackCardGenerator",
    "build_analysis_card_drafts",
    "evidence_gate_result",
    "evidence_summary",
    "extract_block_facts",
    "extract_evidence_refs",
    "has_formal_writeback_content",
    "has_unresolved_analysis_items",
    "normalize_book_analysis_payload",
    "normalize_entity_alias",
    "resolve_payload_entities",
    "resolve_evidence_refs",
    "stable_entity_uid",
    "verify_analysis_card_evidence",
    "apply_book_analysis_payload",
    "filter_untrusted_book_analysis_payload",
]
