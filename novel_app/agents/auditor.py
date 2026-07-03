from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from novel_app.agents.prompts import (
    AUDITOR_GENERATION_TEMPLATE,
    AUDITOR_REVIEW_TEMPLATE,
    AUDITOR_SYSTEM,
)
from novel_app.ai.limits import (
    REVIEW_CONTENT_CONTEXT_CHARS,
    SOURCEBOOK_CONTEXT_CHARS,
    TEMPLATE_CONTEXT_CHARS,
    TRUTH_FILE_CONTEXT_CHARS,
)
from novel_app.json_utils import extract_json_object
from novel_app.prompt_utils import prompt_value, render_prompt

if TYPE_CHECKING:
    from novel_app.agents.graph import AgentState


class AuditorAgent:
    def __init__(self, post_chat: Callable[..., dict[str, Any]], prompt_overrides: dict[str, str] | None = None) -> None:
        self._post_chat = post_chat
        self._prompt_overrides = prompt_overrides or {}

    def audit(self, state: AgentState) -> None:
        content = state.draft or state.current_content
        template_key = "agent.auditor.generation_template" if state.draft else "agent.auditor.review_template"
        template = AUDITOR_GENERATION_TEMPLATE if state.draft else AUDITOR_REVIEW_TEMPLATE
        prompt = render_prompt(
            prompt_value(self._prompt_overrides, template_key, template),
            {
                "book_title": state.book_title,
                "chapter_title": state.chapter_title,
                "outline": state.outline,
                "draft": state.draft,
                "content": content[:REVIEW_CONTENT_CONTEXT_CHARS],
                "truth_file": state.truth_file[:TRUTH_FILE_CONTEXT_CHARS],
                "sourcebook_context": state.sourcebook_context[:SOURCEBOOK_CONTEXT_CHARS],
                "template_content": state.template_content[:TEMPLATE_CONTEXT_CHARS],
            },
        )
        result = self._post_chat(
            messages=[
                {"role": "system", "content": prompt_value(self._prompt_overrides, "agent.auditor.system", AUDITOR_SYSTEM)},
                {"role": "user", "content": prompt},
            ],
            temperature=0.25,
        )
        raw = result["choices"][0]["message"]["content"].strip()
        try:
            payload = extract_json_object(raw)
        except Exception as e:
            state.log(f"Auditor JSON 解析失败: {e}")
            state.audit_findings = []
            state.summary = ""
            return
        findings_raw = payload.get("findings", [])
        if not isinstance(findings_raw, list):
            findings_raw = []
        findings: list[dict[str, Any]] = []
        for f in findings_raw[:30]:
            if not isinstance(f, dict):
                continue
            severity = str(f.get("severity", "low")).strip().lower()
            if severity not in {"high", "medium", "low"}:
                severity = "low"
            issue = str(f.get("issue", "")).strip()
            suggestion = str(f.get("suggestion", "")).strip()
            if not issue and not suggestion:
                continue
            findings.append({
                "agent": str(f.get("agent", "auditor")).strip(),
                "severity": severity,
                "category": str(f.get("category", "")).strip(),
                "location_hint": str(f.get("location_hint", "")).strip(),
                "quote": str(f.get("quote", "")).strip(),
                "issue": issue,
                "suggestion": suggestion,
            })
        state.audit_findings = findings
        state.summary = str(payload.get("summary", "")).strip()
        high = sum(1 for f in findings if f["severity"] == "high")
        medium = sum(1 for f in findings if f["severity"] == "medium")
        state.log(f"Auditor 发现 {len(findings)} 个问题 (high={high}, medium={medium})")
