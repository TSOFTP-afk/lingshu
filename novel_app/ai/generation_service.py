"""AI 生成服务 — 从 AIGenerationMixin 解耦的独立服务

将 AIGenerationMixin 的隐式耦合转为显式依赖，
通过包装 SimpleAIService 实例提供生成能力。
"""
from __future__ import annotations

from typing import Any

from novel_app.ai.protocols import AIGenerationProtocol


class GenerationService:
    """独立的 AI 生成服务，包装 AIGenerationMixin 的功能

    实现 AIGenerationProtocol 协议，将 Mixin 方法调用委托给
    SimpleAIService 实例，消除对 Mixin 继承的隐式依赖。
    """

    def __init__(self, service: Any) -> None:
        self._service = service

    def generate_draft(self, prompt_overrides: dict | None = None, **kwargs) -> str:
        """生成章节草稿

        Args:
            prompt_overrides: 可选的提示词覆盖，暂保留接口扩展点
            **kwargs: 传递给 AIGenerationMixin.generate_draft 的参数
                book_title, chapter_title, outline, current_content,
                summary_text, selected_skills, sourcebook_context
        """
        return self._service.generate_draft(**kwargs)

    def continue_writing(self, prompt_overrides: dict | None = None, **kwargs) -> str:
        """续写章节正文

        Args:
            prompt_overrides: 可选的提示词覆盖
            **kwargs: 传递给 AIGenerationMixin.continue_writing 的参数
                book_title, chapter_title, outline, current_content,
                summary_text, selected_skills, sourcebook_context
        """
        return self._service.continue_writing(**kwargs)

    def polish_text(self, prompt_overrides: dict | None = None, **kwargs) -> str:
        """润色章节正文

        Args:
            prompt_overrides: 可选的提示词覆盖
            **kwargs: 传递给 AIGenerationMixin.polish_text 的参数
                book_title, chapter_title, outline, current_content,
                summary_text, selected_skills, sourcebook_context
        """
        return self._service.polish_text(**kwargs)
