from __future__ import annotations

from novel_app.prompt_settings import (
    AUDITOR_GENERATION_TEMPLATE_PROMPT,
    AUDITOR_REVIEW_TEMPLATE_PROMPT,
    AUDITOR_SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT,
    PLANNER_TEMPLATE_PROMPT,
    REVISER_SYSTEM_PROMPT,
    REVISER_TEMPLATE_PROMPT,
    WRITER_SYSTEM_PROMPT,
    WRITER_TEMPLATE_PROMPT,
)

_PLACEHOLDERS = {
    "book_title",
    "chapter_title",
    "outline",
    "truth_file",
    "sourcebook_context",
    "plan",
    "current_content",
    "skills",
    "template_content",
    "style_voices_block",
    "draft",
    "content",
    "findings",
}


class _DefaultFormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


class _SafePromptTemplate(str):
    def format(self, *args: object, **kwargs: object) -> str:
        if args:
            return super().format(*args, **kwargs)
        return super().format_map(_DefaultFormatDict({str(key): str(value) for key, value in kwargs.items()}))


def _format_safe(template: str) -> str:
    text = template.replace("{", "{{").replace("}", "}}")
    for key in _PLACEHOLDERS:
        text = text.replace("{{" + key + "}}", "{" + key + "}")
    return text


PLANNER_SYSTEM = PLANNER_SYSTEM_PROMPT
PLANNER_TEMPLATE = _SafePromptTemplate(_format_safe(PLANNER_TEMPLATE_PROMPT))
WRITER_SYSTEM = WRITER_SYSTEM_PROMPT
WRITER_TEMPLATE = _SafePromptTemplate(_format_safe(WRITER_TEMPLATE_PROMPT))
AUDITOR_SYSTEM = AUDITOR_SYSTEM_PROMPT
AUDITOR_GENERATION_TEMPLATE = _SafePromptTemplate(_format_safe(AUDITOR_GENERATION_TEMPLATE_PROMPT))
AUDITOR_REVIEW_TEMPLATE = _SafePromptTemplate(_format_safe(AUDITOR_REVIEW_TEMPLATE_PROMPT))
REVISER_SYSTEM = REVISER_SYSTEM_PROMPT
REVISER_TEMPLATE = _SafePromptTemplate(_format_safe(REVISER_TEMPLATE_PROMPT))


__all__ = [
    "PLANNER_SYSTEM",
    "PLANNER_TEMPLATE",
    "WRITER_SYSTEM",
    "WRITER_TEMPLATE",
    "AUDITOR_SYSTEM",
    "AUDITOR_GENERATION_TEMPLATE",
    "AUDITOR_REVIEW_TEMPLATE",
    "REVISER_SYSTEM",
    "REVISER_TEMPLATE",
]
