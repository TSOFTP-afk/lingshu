"""AI 服务统一协议接口 — 解耦 Mixin 隐式耦合

解决三个架构问题：
- P2-01: AI Mixin 隐式耦合 — 通过 Protocol 定义显式契约
- P2-03: AI 服务层缺少统一接口 — 通过组合协议提供统一入口
- P2-05: SimpleAIService 单体设计 — 通过子协议拆分关注点
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AIGenerationProtocol(Protocol):
    """AI 生成服务协议

    涵盖草稿生成、续写、润色等文本生成能力。
    """

    def generate_draft(self, prompt_overrides: dict | None = None, **kwargs) -> str:
        """生成章节草稿"""
        ...

    def continue_writing(self, prompt_overrides: dict | None = None, **kwargs) -> str:
        """续写章节正文"""
        ...

    def polish_text(self, prompt_overrides: dict | None = None, **kwargs) -> str:
        """润色章节正文"""
        ...


@runtime_checkable
class AIReviewProtocol(Protocol):
    """AI 审查服务协议

    涵盖多智能体审查、人物关系抽取等审查能力。
    """

    def multi_agent_review(self, prompt_overrides: dict | None = None, **kwargs) -> dict[str, Any]:
        """多智能体审查章节内容"""
        ...

    def extract_relationships(self, prompt_overrides: dict | None = None, **kwargs) -> list[dict[str, str]]:
        """抽取人物关系"""
        ...


@runtime_checkable
class AITextAnalysisProtocol(Protocol):
    """AI 文本分析服务协议

    涵盖文档分类、AI 概率检测等文本分析能力。
    """

    def analyze_document(self, prompt_overrides: dict | None = None, **kwargs) -> str:
        """分析文档类型"""
        ...

    def detect_ai_probability(self, prompt_overrides: dict | None = None, **kwargs) -> tuple[int, str]:
        """检测 AI 生成概率"""
        ...


@runtime_checkable
class AIProviderProtocol(Protocol):
    """AI 服务统一提供者协议 — 组合所有子协议

    通过组合模式替代 Mixin 继承，使各能力域可独立替换和测试。
    消费方只需依赖此协议，无需了解 SimpleAIService 的内部 Mixin 结构。
    """

    generation: AIGenerationProtocol
    review: AIReviewProtocol
    text_analysis: AITextAnalysisProtocol
