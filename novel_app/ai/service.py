from __future__ import annotations

import os
from dataclasses import dataclass

from .book_analysis import AIBookAnalysisMixin
from .client import AIClientMixin
from .generation import AIGenerationMixin
from .review import AIReviewMixin
from .text_analysis import AITextAnalysisMixin
from .types import DEFAULT_BASE_URL, SkillCard


@dataclass
class SimpleAIService(
    AIClientMixin,
    AIGenerationMixin,
    AIReviewMixin,
    AITextAnalysisMixin,
    AIBookAnalysisMixin,
):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    last_remote_error: str | None = None
    prompt_overrides: dict[str, str] | None = None
    extra_body: dict | None = None

    def __post_init__(self) -> None:
        self._request_timeout = int(os.environ.get("LINGSHU_AI_TIMEOUT", "30")) or None


__all__ = ["DEFAULT_BASE_URL", "SkillCard", "SimpleAIService"]
