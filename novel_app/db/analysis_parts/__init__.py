"""AnalysisMixin 按域拆分的子 mixin 包。

原 ``novel_app/db/analysis.py``（单类 69 个方法）按域拆分为多个 mixin 文件，
方法名、签名、SQL 与行为完全不变；由 ``analysis.py`` 中的 ``AnalysisMixin``
按原方法排列顺序组合这些 mixin，MRO 解析结果与拆分前一致。
"""
from __future__ import annotations

from novel_app.db.analysis_parts.analysis_cards import AnalysisCardsMixin
from novel_app.db.analysis_parts.analysis_entities import AnalysisEntitiesMixin
from novel_app.db.analysis_parts.analysis_facts import AnalysisFactsMixin
from novel_app.db.analysis_parts.analysis_probes import AnalysisProbesMixin
from novel_app.db.analysis_parts.analysis_runs import AnalysisRunsMixin
from novel_app.db.analysis_parts.analysis_writeback import AnalysisWritebackMixin

__all__ = [
    "AnalysisCardsMixin",
    "AnalysisEntitiesMixin",
    "AnalysisFactsMixin",
    "AnalysisProbesMixin",
    "AnalysisRunsMixin",
    "AnalysisWritebackMixin",
]
