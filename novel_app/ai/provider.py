"""AI 服务统一提供者 — 替代 SimpleAIService 单体

通过组合模式将 SimpleAIService 的各 Mixin 能力拆分为独立子服务，
消费方只需依赖 AIProviderProtocol，无需了解 SimpleAIService 的
内部 Mixin 继承结构。

解决：
- P2-01: AI Mixin 隐式耦合 → 组合替代继承
- P2-03: AI 服务层缺少统一接口 → AIProvider 作为统一入口
- P2-05: SimpleAIService 单体设计 → 子服务可独立替换和测试
"""
from __future__ import annotations

from novel_app.ai.generation_service import GenerationService
from novel_app.ai.review_service import ReviewService
from novel_app.ai.service import SimpleAIService
from novel_app.ai.text_analysis_service import TextAnalysisService


class AIProvider:
    """AI 服务统一提供者 — 组合模式替代 Mixin 继承

    将 SimpleAIService 的各 Mixin 能力拆分为独立子服务：
    - generation: 文本生成（草稿/续写/润色）
    - review: 内容审查（多智能体审查/人物关系抽取）
    - text_analysis: 文本分析（文档分类/AI 概率检测）

    用法::

        provider = AIProvider.from_env()
        draft = provider.generation.generate_draft(
            book_title="书名", chapter_title="第一章", outline="大纲"
        )
        review = provider.review.multi_agent_review(
            book_title="书名", chapter_title="第一章",
            outline="大纲", content="正文", truth_file="设定"
        )
    """

    def __init__(self, service: SimpleAIService) -> None:
        self._service = service
        self.generation: GenerationService = GenerationService(service)
        self.review: ReviewService = ReviewService(service)
        self.text_analysis: TextAnalysisService = TextAnalysisService(service)

    @classmethod
    def from_env(cls) -> AIProvider:
        """从环境变量创建 AIProvider

        读取 OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL 等环境变量，
        构造 SimpleAIService 并包装为 AIProvider。
        """
        return cls(SimpleAIService.from_env())

    @property
    def service(self) -> SimpleAIService:
        """访问底层 SimpleAIService 实例（向后兼容）"""
        return self._service
