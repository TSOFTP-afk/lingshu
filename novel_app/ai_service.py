"""向后兼容入口 — 所有公开符号从 ai 子模块 re-export。"""
from novel_app.ai.service import *  # noqa: F401,F403
from novel_app.ai.service import DEFAULT_BASE_URL, SimpleAIService, SkillCard  # noqa: F401
