from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from novel_app.agents.prompts import PLANNER_SYSTEM, PLANNER_TEMPLATE
from novel_app.ai.limits import SOURCEBOOK_CONTEXT_CHARS, TRUTH_FILE_CONTEXT_CHARS
from novel_app.json_utils import extract_json_object
from novel_app.prompt_utils import prompt_value, render_prompt

if TYPE_CHECKING:
    from novel_app.agents.graph import AgentState


class PlannerAgent:
    def __init__(self, post_chat: Callable[..., dict[str, Any]], prompt_overrides: dict[str, str] | None = None) -> None:
        self._post_chat = post_chat
        self._prompt_overrides = prompt_overrides or {}

    def plan(self, state: AgentState) -> None:
        prompt = render_prompt(
            prompt_value(self._prompt_overrides, "agent.planner.template", PLANNER_TEMPLATE),
            {
                "book_title": state.book_title,
                "chapter_title": state.chapter_title,
                "outline": state.outline,
                "truth_file": state.truth_file[:TRUTH_FILE_CONTEXT_CHARS],
                "sourcebook_context": state.sourcebook_context[:SOURCEBOOK_CONTEXT_CHARS],
            },
        )
        result = self._post_chat(
            messages=[
                {"role": "system", "content": prompt_value(self._prompt_overrides, "agent.planner.system", PLANNER_SYSTEM)},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        raw = result["choices"][0]["message"]["content"].strip()
        try:
            payload = extract_json_object(raw)
        except Exception as e:
            state.log(f"Planner JSON 解析失败: {e}")
            state.plan = f"围绕「{state.outline[:200]}」按场景推进"
            return
        scenes = payload.get("scene_plan", [])
        if not isinstance(scenes, list):
            scenes = []
        plan_lines = []
        for s in scenes[:5]:
            if not isinstance(s, dict):
                continue
            beats = s.get("key_beats", s.get("beats", []))
            parts = [
                f"场景{s.get('scene_number', s.get('title', '?'))}：{s.get('scene_goal', s.get('purpose', '未指定'))}",
                f"地点：{s.get('location', '未指定')}",
            ]
            if isinstance(beats, list):
                parts.append("关键节拍：" + "；".join(str(b) for b in beats[:3]))
            plan_lines.append(" | ".join(parts))
        state.plan = "\n".join(plan_lines) if plan_lines else f"围绕「{state.outline[:200]}」按场景推进"
        state.log(f"Planner 生成 {len(scenes)} 个场景计划")
