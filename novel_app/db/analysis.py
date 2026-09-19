"""AnalysisMixin — 按域组合的分文件 mixin（原 2088 行单类拆分而来）。

各分域 mixin 定义在 ``novel_app/db/analysis_parts/`` 中，方法体逐字节保留。
组合顺序与分析原文件中各方法的首次出现顺序一致；原文件内无同名方法，
因此 MRO 方法解析结果与拆分前的单类完全一致。
"""
from __future__ import annotations

from novel_app.db.analysis_parts import (
    AnalysisCardsMixin,
    AnalysisEntitiesMixin,
    AnalysisFactsMixin,
    AnalysisProbesMixin,
    AnalysisRunsMixin,
    AnalysisWritebackMixin,
)


class AnalysisMixin(
    AnalysisRunsMixin,
    AnalysisCardsMixin,
    AnalysisEntitiesMixin,
    AnalysisFactsMixin,
    AnalysisProbesMixin,
    AnalysisWritebackMixin,
):
    pass
