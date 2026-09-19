"""
工作台路由共享辅助（原 lingshu_api/routers/workspace.py 拆分而来）。

被 workspace_books / workspace_ai / workspace_probes / workspace_snapshots /
workspace_writeback / workspace_import 等域模块共用。
"""
from __future__ import annotations

import logging

from lingshu_api.dependencies import check_book_owner
from lingshu_api.services.db_bridge import WorkspaceDB

# 保持拆分前统一的日志通道名
logger = logging.getLogger("lingshu_api.routers.workspace")


def _check_chapter_owner(db: WorkspaceDB, chapter: dict, user: dict) -> int:
    book_id = int(chapter.get("book_id") or 0)
    if book_id:
        check_book_owner(db, book_id, user)
    return book_id
