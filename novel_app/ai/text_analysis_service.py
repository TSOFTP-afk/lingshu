"""AI 文本分析服务 — 从 AITextAnalysisMixin 解耦的独立服务

将 AITextAnalysisMixin 的隐式耦合转为显式依赖，
通过包装 SimpleAIService 实例提供文本分析能力。
"""
from __future__ import annotations

from typing import Any


class TextAnalysisService:
    """独立的 AI 文本分析服务，包装 AITextAnalysisMixin 的功能

    实现 AITextAnalysisProtocol 协议，将 Mixin 方法调用委托给
    SimpleAIService 实例，消除对 Mixin 继承的隐式依赖。
    """

    def __init__(self, service: Any) -> None:
        self._service = service

    def analyze_document(self, prompt_overrides: dict | None = None, **kwargs) -> str:
        """分析文档类型

        Args:
            prompt_overrides: 可选的提示词覆盖，暂保留接口扩展点
            **kwargs: 传递给 AITextAnalysisMixin.analyze_document 的参数
                text, require_remote
        """
        return self._service.analyze_document(**kwargs)

    def detect_ai_probability(self, prompt_overrides: dict | None = None, **kwargs) -> tuple[int, str]:
        """检测 AI 生成概率

        Args:
            prompt_overrides: 可选的提示词覆盖
            **kwargs: 传递给 AITextAnalysisMixin.detect_ai_probability 的参数
                text
        """
        return self._service.detect_ai_probability(**kwargs)
