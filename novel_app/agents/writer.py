from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from novel_app.agents.prompts import WRITER_SYSTEM, WRITER_TEMPLATE
from novel_app.ai.limits import (
    CURRENT_CONTENT_CONTEXT_CHARS,
    SOURCEBOOK_CONTEXT_CHARS,
    STYLE_VOICES_CONTEXT_CHARS,
    TEMPLATE_CONTEXT_CHARS,
    TRUTH_FILE_CONTEXT_CHARS,
)
from novel_app.prompt_utils import prompt_value, render_prompt

if TYPE_CHECKING:
    from novel_app.agents.graph import AgentState


class WriterAgent:
    def __init__(self, post_chat: Callable[..., dict[str, Any]], prompt_overrides: dict[str, str] | None = None) -> None:
        self._post_chat = post_chat
        self._prompt_overrides = prompt_overrides or {}

    def write(self, state: AgentState) -> None:
        skills = state.selected_skills or []
        skill_text = "\n".join(
            f"- {s.get('name', '')}：{s.get('instruction_text', s.get('instruction', ''))}"
            for s in skills[:8]
        ) if skills else "无"

        prompt = render_prompt(
            prompt_value(self._prompt_overrides, "agent.writer.template", WRITER_TEMPLATE),
            {
                "book_title": state.book_title,
                "chapter_title": state.chapter_title,
                "outline": state.outline,
                "plan": state.plan,
                "current_content": state.current_content[:CURRENT_CONTENT_CONTEXT_CHARS],
                "skills": skill_text,
                "truth_file": state.truth_file[:TRUTH_FILE_CONTEXT_CHARS],
                "sourcebook_context": state.sourcebook_context[:SOURCEBOOK_CONTEXT_CHARS],
                "template_content": state.template_content[:TEMPLATE_CONTEXT_CHARS],
                "style_voices_block": state.style_voices_block[:STYLE_VOICES_CONTEXT_CHARS],
            },
        )
        try:
            result = self._post_chat(
                messages=[
                    {"role": "system", "content": prompt_value(self._prompt_overrides, "agent.writer.system", WRITER_SYSTEM)},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
            )
            raw = result["choices"][0]["message"]["content"].strip()
            state.draft = raw
        except (KeyError, IndexError) as e:
            state.log(f"Writer JSON 解析失败: {e}")
            state.draft = (
                f"【AI 写作异常】{state.chapter_title}\n\n"
                "写作模块返回格式异常，请检查 AI 配置或使用本地 Mock 生成。"
            )
        state.log(f"Writer 生成正文 {len(state.draft)} 字")
