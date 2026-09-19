"""向后兼容入口 — 所有公开符号从 bookstore 子模块 re-export。"""
from novel_app.bookstore.app import *  # noqa: F401,F403
from novel_app.bookstore.app import create_app  # noqa: F401
