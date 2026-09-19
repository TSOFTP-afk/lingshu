"""AI 审查服务 — 从 AIReviewMixin 解耦的独立服务

将 AIReviewMixin 的隐式耦合转为显式依赖，
通过包装 SimpleAIService 实例提供审查能力。
"""
from __future__ import annotations

from typing import Any


class ReviewService:
    """独立的 AI 审查服务，包装 AIReviewMixin 的功能

    实现 AIReviewProtocol 协议，将 Mixin 方法调用委托给
    SimpleAIService 实例，消除对 Mixin 继承的隐式依赖。
    """

    def __init__(self, service: Any) -> None:
        self._service = service

    def multi_agent_review(self, prompt_overrides: dict | None = None, **kwargs) -> dict[str, Any]:
        """多智能体审查章节内容

        Args:
            prompt_overrides: 可选的提示词覆盖，暂保留接口扩展点
            **kwargs: 传递给 AIReviewMixin.multi_agent_review 的参数
                book_title, chapter_title, outline, content, truth_file,
                selected_skills, require_remote, cancel_event, template_content
        """
        return self._service.multi_agent_review(**kwargs)

    def extract_relationships(self, prompt_overrides: dict | None = None, **kwargs) -> list[dict[str, str]]:
        """抽取人物关系

        委托给 AIReviewMixin.extract_character_relationships。

        Args:
            prompt_overrides: 可选的提示词覆盖
            **kwargs: 传递给 AIReviewMixin.extract_character_relationships 的参数
                book_title, characters, chapters, require_remote, cancel_event
        """
        return self._service.extract_character_relationships(**kwargs)
