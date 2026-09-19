"""
工作台书籍/分卷/章节 API — CRUD + 搜索 + 大纲读写。

对应迁移的 Qt 模块:
- app_tree.py    → 书籍/分卷/章节列表 + 树结构
- app_editor.py  → 章节正文+大纲保存/读取
- forms.py       → 书籍大纲表单 (已有 structured_templates)
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from lingshu_api.dependencies import check_book_owner, require_login, try_cloud_sync
from lingshu_api.routers.workspace_common import _check_chapter_owner
from lingshu_api.schemas.workspace import (
    BookCreate,
    BookItemResponse,
    BookListResponse,
    BookOutlineSave,
    BookUpdate,
    ChapterCreate,
    ChapterItemResponse,
    ChapterListResponse,
    ChapterMove,
    ChapterUpdate,
    OkResponse,
    VolumeCreate,
    VolumeItemResponse,
    VolumeUpdate,
)
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db
from novel_app.database import ALL_VOLUMES, UNASSIGNED_VOLUMES
from novel_app.structured_templates import BOOK_OUTLINE_FORM_SCHEMA

router = APIRouter(tags=["workspace"])


@router.get("/health", response_model=OkResponse)
async def workspace_health():
    """工作台 API 健康检查。"""
    return {"ok": True}


# ================================================================
#  书籍 CRUD
# ================================================================

@router.get("/books", response_model=BookListResponse)
async def list_books(user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """列出所有作品（含分卷-章节树结构）。"""
    def _sync():
        user_id = int(user["id"])
        books = []
        for b in db.list_books(user_id=user_id):
            book_data = db.get_book(b["id"])
            if book_data:
                books.append(book_data)
        return {"items": books}
    return await asyncio.to_thread(_sync)


@router.post("/books", response_model=BookItemResponse)
async def create_book(request: Request, payload: BookCreate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """创建新作品。"""
    def _sync():
        user_id = int(user["id"])
        book = db.create_book(payload.title, user_id=user_id)
        book_id = int(book["id"])
        book = db.get_book(book_id) or book
        try_cloud_sync(request, book_id, user)
        return {"ok": True, "item": book}
    return await asyncio.to_thread(_sync)


@router.get("/books/{book_id}", response_model=dict[str, Any])  # TODO: 细化为 BookDetailResponse
async def get_book(book_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """获取作品详情（含全部分卷-章节树）。"""
    def _sync():
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
        check_book_owner(db, book_id, user)
        return book
    return await asyncio.to_thread(_sync)


@router.patch("/books/{book_id}", response_model=BookItemResponse)
async def update_book(request: Request, book_id: int, payload: BookUpdate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """更新作品信息（标题/简介）。"""
    def _sync():
        check_book_owner(db, book_id, user)
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
        if payload.title:
            db.rename_book(book_id, payload.title)
        try_cloud_sync(request, book_id, user)
        return {"ok": True, "item": db.get_book(book_id)}
    return await asyncio.to_thread(_sync)


@router.delete("/books/{book_id}", response_model=OkResponse)
async def delete_book(book_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """删除作品及其全部分卷/章节。"""
    def _sync():
        check_book_owner(db, book_id, user)
        if not db.get_book(book_id):
            raise HTTPException(status_code=404, detail="作品不存在")
        db.delete_book(book_id)
        return {"ok": True}
    return await asyncio.to_thread(_sync)


# ================================================================
#  分卷 CRUD
# ================================================================

@router.post("/books/{book_id}/volumes", response_model=VolumeItemResponse)
async def create_volume(request: Request, book_id: int, payload: VolumeCreate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """创建分卷。"""
    def _sync():
        check_book_owner(db, book_id, user)
        vol = db.create_volume(book_id, payload.title)
        try_cloud_sync(request, book_id, user)
        return {"ok": True, "item": vol}
    return await asyncio.to_thread(_sync)


@router.patch("/volumes/{volume_id}", response_model=OkResponse)
async def update_volume(request: Request, volume_id: int, payload: VolumeUpdate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """更新分卷（重命名/排序）。"""
    def _sync():
        volume = db.get_volume(volume_id)
        book_id = int(volume["book_id"]) if volume else None
        if book_id:
            check_book_owner(db, book_id, user)
        if payload.title:
            db.rename_volume(volume_id, payload.title)
        if book_id:
            try_cloud_sync(request, book_id, user)
        return {"ok": True}
    return await asyncio.to_thread(_sync)


@router.delete("/volumes/{volume_id}", response_model=OkResponse)
async def delete_volume(request: Request, volume_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """删除分卷及其下全部章节。"""
    def _sync():
        volume = db.get_volume(volume_id)
        book_id = int(volume["book_id"]) if volume else None
        if book_id:
            check_book_owner(db, book_id, user)
        db.delete_volume(volume_id)
        if book_id:
            try_cloud_sync(request, book_id, user)
        return {"ok": True}
    return await asyncio.to_thread(_sync)


# ================================================================
#  章节 CRUD
# ================================================================

@router.post("/volumes/{volume_id}/chapters", response_model=ChapterItemResponse)
async def create_chapter_in_volume(request: Request, volume_id: int, payload: ChapterCreate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """在某分卷下创建章节。"""
    def _sync():
        volume = db.get_volume(volume_id)
        if not volume:
            raise HTTPException(status_code=404, detail="分卷不存在")
        book_id = int(volume["book_id"])
        check_book_owner(db, book_id, user)
        ch = db.create_chapter(book_id, payload.title, volume_id)
        try_cloud_sync(request, book_id, user)
        return {"ok": True, "item": ch}
    return await asyncio.to_thread(_sync)


@router.post("/books/{book_id}/chapters", response_model=ChapterItemResponse)
async def create_chapter_in_book(request: Request, book_id: int, payload: ChapterCreate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """在作品下创建未分卷章节。"""
    def _sync():
        check_book_owner(db, book_id, user)
        ch = db.create_chapter(book_id, payload.title, None)
        try_cloud_sync(request, book_id, user)
        return {"ok": True, "item": ch}
    return await asyncio.to_thread(_sync)


@router.get("/books/{book_id}/chapters", response_model=ChapterListResponse)
async def list_chapters(
    book_id: int,
    volume_filter: int | str = Query(default=ALL_VOLUMES, alias="volume"),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """列出作品下的章节（可按分卷筛选）。"""
    def _sync():
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
        check_book_owner(db, book_id, user)
        try:
            vf = int(volume_filter)
        except (ValueError, TypeError):
            vf = ALL_VOLUMES if volume_filter == "all" else UNASSIGNED_VOLUMES
        chapters = db.list_chapters(book_id, vf)
        return {"items": chapters}
    return await asyncio.to_thread(_sync)


@router.get("/books/{book_id}/search", response_model=dict[str, Any])  # TODO: 细化为 SearchResponse
async def search_book_text(
    book_id: int,
    q: str = Query(default="", description="精确查找关键词"),
    limit: int = Query(default=100, ge=1, le=200),
    case_sensitive: bool = Query(default=False),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """在当前作品章节标题和正文中做精确文本查找。"""
    def _sync():
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
        check_book_owner(db, book_id, user)
        query = q.strip()
        if not query:
            return {"items": [], "query": query}
        return {
            "items": db.search_book(book_id, query, limit=limit, case_sensitive=case_sensitive),
            "query": query,
        }
    return await asyncio.to_thread(_sync)


@router.get("/chapters/{chapter_id}", response_model=dict[str, Any])  # TODO: 细化为 ChapterDetailResponse
async def get_chapter(chapter_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """获取章节完整内容（正文+大纲）。"""
    def _sync():
        ch = db.get_chapter(chapter_id)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        _check_chapter_owner(db, ch, user)
        return ch
    return await asyncio.to_thread(_sync)


@router.patch("/chapters/{chapter_id}", response_model=ChapterItemResponse)
async def update_chapter(request: Request, chapter_id: int, payload: ChapterUpdate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """保存章节（正文/大纲/标题）。"""
    def _sync():
        ch = db.get_chapter(chapter_id)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        book_id = int(ch.get("book_id") or 0)
        if book_id:
            check_book_owner(db, book_id, user)
        kwargs = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
        if kwargs:
            ch = db.update_chapter(chapter_id, **kwargs)
            book_id = int(ch.get("book_id") or 0) if ch else None
            if book_id:
                try_cloud_sync(request, book_id, user)
            return {"ok": True, "item": ch}
        if book_id:
            try_cloud_sync(request, book_id, user)
        return {"ok": True, "item": db.get_chapter(chapter_id)}
    return await asyncio.to_thread(_sync)


@router.delete("/chapters/{chapter_id}", response_model=OkResponse)
async def delete_chapter(request: Request, chapter_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """删除章节。"""
    def _sync():
        ch = db.get_chapter(chapter_id)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        book_id = int(ch.get("book_id") or 0)
        if book_id:
            check_book_owner(db, book_id, user)
        db.delete_chapter(chapter_id)
        if book_id:
            try_cloud_sync(request, book_id, user)
        return {"ok": True}
    return await asyncio.to_thread(_sync)


@router.patch("/chapters/{chapter_id}/move", response_model=OkResponse)
async def move_chapter(request: Request, chapter_id: int, payload: ChapterMove, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """移动章节到目标分卷并设置排序位置。"""
    def _sync():
        ch = db.get_chapter(chapter_id)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        book_id = int(ch.get("book_id") or 0)
        if book_id:
            check_book_owner(db, book_id, user)
        db.move_chapter(chapter_id, payload.target_volume_id, payload.sort_order)
        if book_id:
            try_cloud_sync(request, book_id, user)
        return {"ok": True}
    return await asyncio.to_thread(_sync)


# ================================================================
#  书籍大纲 / 世界观读写（对接 structured_templates）
# ================================================================

@router.get("/books/{book_id}/outline", response_model=dict[str, Any])  # TODO: 细化为 BookOutlineResponse
async def get_book_outline(book_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """获取书籍大纲（Markdown + 表单数据）。"""
    def _sync():
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
        check_book_owner(db, book_id, user)
        outline_data = db.db.get_book_outline_form(book_id) if db.db else {}
        return {
            "outline_text": book.get("outline_text", ""),
            "outline_data": outline_data if isinstance(outline_data, dict) else {},
            "outline_schema": BOOK_OUTLINE_FORM_SCHEMA,
        }
    return await asyncio.to_thread(_sync)


@router.put("/books/{book_id}/outline", response_model=dict[str, Any])  # TODO: 细化为 BookOutlineResponse
async def save_book_outline(request: Request, book_id: int, payload: BookOutlineSave, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """保存书籍大纲（Markdown 文本 + 可选表单数据）。"""
    def _sync():
        check_book_owner(db, book_id, user)
        if not db.get_book(book_id):
            raise HTTPException(status_code=404, detail="作品不存在")
        outline_text = payload.resolved_outline_text
        outline_data = payload.outline_data if not outline_text.strip() else None
        if isinstance(outline_data, dict):
            updated = db.update_book_outline(book_id, outline_text, outline_data)
        else:
            updated = db.update_book_outline(book_id, outline_text)
        updated_data = db.db.get_book_outline_form(book_id) if db.db else {}
        try_cloud_sync(request, book_id, user)
        return {
            "ok": True,
            "outline_text": (updated or {}).get("outline_text", ""),
            "outline_data": updated_data if isinstance(updated_data, dict) else {},
            "outline_schema": BOOK_OUTLINE_FORM_SCHEMA,
        }
    return await asyncio.to_thread(_sync)
