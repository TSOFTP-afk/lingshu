"""Pipeline V3 依赖注入配置数据类。

将 AnalysisPipelineV3 构造函数的大量参数分组为语义化的数据类，
简化实例创建并提高可读性。

公共 API：
  - PipelineV3Stores      存储层分组（AnalysisStore, EntityStore, FactStore）
  - PipelineV3Planners    规划器分组（BacktrackPlanner, ProbePlanner）
  - PipelineV3Memory      记忆层分组（MemoryClassifier, MemoryCompressor）
  - PipelineV3Config      顶层配置，组合上述分组
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from novel_app.analysis.backtrack import BacktrackPlanner
from novel_app.analysis.card_coordinator import CardCoordinator
from novel_app.analysis.entity_store import EntityStore
from novel_app.analysis.fact_store import FactStore
from novel_app.analysis.memory_classifier import MemoryClassifier
from novel_app.analysis.memory_compressor import MemoryCompressor
from novel_app.analysis.probe_planner import ProbePlanner
from novel_app.analysis.semantic_chunker import SemanticChunker
from novel_app.analysis.store import AnalysisStore
from novel_app.database import Database


@dataclass
class PipelineV3Stores:
    """存储层依赖分组。"""
    analysis: AnalysisStore
    entity: EntityStore
    fact: FactStore


@dataclass
class PipelineV3Planners:
    """规划器依赖分组。"""
    backtrack: BacktrackPlanner
    probe: ProbePlanner


@dataclass
class PipelineV3Memory:
    """记忆层依赖分组。"""
    classifier: MemoryClassifier
    compressor: MemoryCompressor


@dataclass
class PipelineV3Config:
    """AnalysisPipelineV3 的依赖注入配置。

    将构造函数的 12 个参数分组为 7 个语义化字段，
    简化实例创建。

    用法::

        config = PipelineV3Config(
            db=database,
            chunker=SemanticChunker(),
            stores=PipelineV3Stores(analysis=store, entity=entity_store, fact=fact_store),
            coordinator=card_coordinator,
            planners=PipelineV3Planners(backtrack=backtrack_planner, probe=probe_planner),
            memory=PipelineV3Memory(classifier=classifier, compressor=compressor),
            ai_provider=ai_provider,
        )
        pipeline = AnalysisPipelineV3.from_config(config)
    """
    db: Database
    chunker: SemanticChunker = field(default_factory=SemanticChunker)
    stores: PipelineV3Stores | None = None
    coordinator: CardCoordinator | None = None
    planners: PipelineV3Planners | None = None
    memory: PipelineV3Memory | None = None
    ai_provider: Any = None
