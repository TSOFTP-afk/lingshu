"""AI 子模块 — 重新导出公共 API 以保持向后兼容。"""

from .book_analysis import AIBookAnalysisMixin
from .client import AIClientMixin
from .generation import AIGenerationMixin
from .generation_service import GenerationService
from .limits import (
    BOOK_ANALYSIS_LEVEL1_MAX_TOKENS,
    BOOK_ANALYSIS_LEVEL2_MAX_TOKENS,
    BOOK_ANALYSIS_LEVEL3_MAX_TOKENS,
    BOOK_OUTLINE_CONTEXT_CHARS,
    CHAT_CONTEXT_CHARS,
    CURRENT_CONTENT_CONTEXT_CHARS,
    JSON_OBJECT_DEFAULT_MAX_TOKENS,
    MAX_BOOK_ANALYSIS_INPUT_CHARS,
    REVIEW_CONTENT_CONTEXT_CHARS,
    SOURCEBOOK_CONTEXT_CHARS,
    STYLE_VOICES_CONTEXT_CHARS,
    TEMPLATE_CONTEXT_CHARS,
    TEXT_ANALYSIS_CONTEXT_CHARS,
    TRUTH_FILE_CONTEXT_CHARS,
)
from .protocols import (
    AIGenerationProtocol,
    AIProviderProtocol,
    AIReviewProtocol,
    AITextAnalysisProtocol,
)
from .provider import AIProvider
from .review import AIReviewMixin
from .review_service import ReviewService
from .service import SimpleAIService
from .text_analysis import AITextAnalysisMixin
from .text_analysis_service import TextAnalysisService
from .types import DEFAULT_BASE_URL, SkillCard

__all__ = [
    "DEFAULT_BASE_URL",
    "SkillCard",
    "CURRENT_CONTENT_CONTEXT_CHARS",
    "TRUTH_FILE_CONTEXT_CHARS",
    "SOURCEBOOK_CONTEXT_CHARS",
    "TEMPLATE_CONTEXT_CHARS",
    "STYLE_VOICES_CONTEXT_CHARS",
    "REVIEW_CONTENT_CONTEXT_CHARS",
    "CHAT_CONTEXT_CHARS",
    "BOOK_OUTLINE_CONTEXT_CHARS",
    "TEXT_ANALYSIS_CONTEXT_CHARS",
    "MAX_BOOK_ANALYSIS_INPUT_CHARS",
    "JSON_OBJECT_DEFAULT_MAX_TOKENS",
    "BOOK_ANALYSIS_LEVEL1_MAX_TOKENS",
    "BOOK_ANALYSIS_LEVEL2_MAX_TOKENS",
    "BOOK_ANALYSIS_LEVEL3_MAX_TOKENS",
    "AIClientMixin",
    "AIGenerationMixin",
    "AIReviewMixin",
    "AITextAnalysisMixin",
    "AIBookAnalysisMixin",
    "SimpleAIService",
    # 新增：协议接口与组合服务
    "AIGenerationProtocol",
    "AIReviewProtocol",
    "AITextAnalysisProtocol",
    "AIProviderProtocol",
    "GenerationService",
    "ReviewService",
    "TextAnalysisService",
    "AIProvider",
]
