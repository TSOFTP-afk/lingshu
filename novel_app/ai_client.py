"""向后兼容入口 — 所有公开符号从 ai 子模块 re-export。"""
from novel_app.ai.client import *  # noqa: F401,F403
from novel_app.ai.client import AIClientMixin, _select_windows_proxy  # noqa: F401
