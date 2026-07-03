"""
世界观管理 API — 对应 Qt drawer/world.py
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from lingshu_api.dependencies import check_book_owner, require_login, try_cloud_sync
from lingshu_api.schemas.workspace import WorldSave
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db
from novel_app.structured_templates import WORLD_FORM_SCHEMA

router = APIRouter(prefix="/api/workspace/books/{book_id}", tags=["world"])
_cloud_logger = logging.getLogger(__name__)


@router.get("/world")
def get_world(book_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """获取书籍世界观（Markdown + 表单数据）。"""
    check_book_owner(db, book_id, user)
    book = db.get_book(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="作品不存在")
    world_data = db.db.get_book_world_form(book_id)
    return {
        "world_text": book.get("world_text", ""),
        "world_data": world_data if isinstance(world_data, dict) else {},
        "world_schema": WORLD_FORM_SCHEMA,
    }


@router.put("/world")
def save_world(request: Request, book_id: int, payload: WorldSave, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """保存世界观。"""
    check_book_owner(db, book_id, user)
    if not db.get_book(book_id):
        raise HTTPException(status_code=404, detail="作品不存在")
    world_text = payload.resolved_world_text
    world_data = payload.world_data if not world_text.strip() else None
    updated = db.update_book_world(
        book_id,
        world_text,
        world_data,
    )
    world_data = db.db.get_book_world_form(book_id)
    try_cloud_sync(request, book_id, user)
    return {
        "ok": True,
        "world_text": (updated or {}).get("world_text", ""),
        "world_data": world_data if isinstance(world_data, dict) else {},
        "world_schema": WORLD_FORM_SCHEMA,
    }
