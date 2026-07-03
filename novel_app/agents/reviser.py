from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from novel_app.agents.prompts import REVISER_SYSTEM, REVISER_TEMPLATE
from novel_app.ai.limits import REVIEW_CONTENT_CONTEXT_CHARS, TEMPLATE_CONTEXT_CHARS
from novel_app.json_utils import extract_json_object
from novel_app.prompt_utils import prompt_value, render_prompt

if TYPE_CHECKING:
    from novel_app.agents.graph import AgentState


class ReviserAgent:
    def __init__(self, post_chat: Callable[..., dict[str, Any]], prompt_overrides: dict[str, str] | None = None) -> None:
        self._post_chat = post_chat
        self._prompt_overrides = prompt_overrides or {}

    def revise(self, state: AgentState) -> None:
        content = state.draft or state.current_content
        if not state.audit_findings:
            state.revised_content = content
            state.revised_outline = state.outline
            state.risk_notes = ""
            state.template_comparison = ""
            state.log("无审计问题，跳过修订")
            return

        findings_text = "\n".join(
            f"[{f['severity']}] {f.get('agent', '')}/{f.get('category', '')}：{f['issue'][:200]} → {f['suggestion'][:200]}"
            for f in state.audit_findings[:15]
        )
        prompt = render_prompt(
            prompt_value(self._prompt_overrides, "agent.reviser.template", REVISER_TEMPLATE),
            {
                "book_title": state.book_title,
                "chapter_title": state.chapter_title,
                "outline": state.outline,
                "content": content[:REVIEW_CONTENT_CONTEXT_CHARS],
                "findings": findings_text,
                "template_content": state.template_content[:TEMPLATE_CONTEXT_CHARS],
            },
        )
        result = self._post_chat(
            messages=[
                {"role": "system", "content": prompt_value(self._prompt_overrides, "agent.reviser.system", REVISER_SYSTEM)},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
        )
        raw = result["choices"][0]["message"]["content"].strip()
        try:
            payload = extract_json_object(raw)
        except Exception as e:
            state.log(f"Reviser JSON 解析失败: {e}")
            state.revised_content = content
            state.revised_outline = state.outline
            state.risk_notes = ""
            state.template_comparison = ""
            return
        revised = str(payload.get("revised_content", "") or "").strip()
        if not revised:
            state.revised_content = content
            state.log("Reviser 返回空内容，保留原稿")
        else:
            state.revised_content = revised
        state.revised_outline = str(payload.get("revised_outline", "") or "").strip() or state.outline
        state.risk_notes = str(payload.get("risk_notes", "") or "").strip()
        state.template_comparison = str(payload.get("template_comparison", "") or "").strip()
        state.log(f"Reviser 完成修订，产出 {len(state.revised_content)} 字")
