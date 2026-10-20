"""
工作台快照管理 API — 章节快照 + 生成快照（原 lingshu_api/routers/workspace.py 拆分而来）。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from lingshu_api.dependencies import check_book_owner, require_login
from lingshu_api.routers.workspace_common import _check_chapter_owner, logger
from lingshu_api.schemas.workspace import (
    ChapterItemResponse,
    GenerationSnapshotCreate,
    OkResponse,
    SnapshotCreate,
    SnapshotListResponse,
    SnapshotRestore,
)
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db

router = APIRouter(tags=["workspace"])


# ================================================================
#  快照管理
# ================================================================

@router.get("/chapters/{chapter_id}/snapshots", response_model=SnapshotListResponse)
async def list_snapshots(chapter_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """列出章节的所有快照。"""
    def _sync():
        ch = db.get_chapter(chapter_id)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        _check_chapter_owner(db, ch, user)
        return {"items": db.list_snapshots(chapter_id)}
    return await asyncio.to_thread(_sync)


@router.post("/chapters/{chapter_id}/snapshot", response_model=OkResponse)
async def create_snapshot(request: Request, chapter_id: int, body: SnapshotCreate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """为章节创建快照。"""
    def _sync():
        ch = db.get_chapter(chapter_id)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        book_id = int(ch.get("book_id") or 0)
        if book_id:
            check_book_owner(db, book_id, user)
        db.create_snapshot(chapter_id, body.label or "手动快照",
                           ch.get("outline", ""), ch.get("content", ""))
        return {"ok": True}
    return await asyncio.to_thread(_sync)


@router.post("/chapters/{chapter_id}/restore", response_model=ChapterItemResponse)
async def restore_snapshot(request: Request, chapter_id: int, body: SnapshotRestore, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """从快照恢复章节。"""
    def _sync():
        ch = db.get_chapter(chapter_id)
        book_id = int(ch.get("book_id") or 0) if ch else None
        if book_id:
            check_book_owner(db, book_id, user)
        result = db.restore_snapshot(chapter_id, body.snapshot_id)
        if not result:
            raise HTTPException(status_code=404, detail="快照不存在")
        ch = db.get_chapter(chapter_id)
        return {"ok": True, "item": db.get_chapter(chapter_id)}
    return await asyncio.to_thread(_sync)


# ================================================================
#  生成快照管理
# ================================================================

@router.get("/chapters/{chapter_id}/generation-snapshots", response_model=dict[str, Any])
async def list_generation_snapshots(chapter_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """列出章节的所有生成快照。"""
    def _sync():
        ch = db.get_chapter(chapter_id)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        _check_chapter_owner(db, ch, user)
        return {"items": db.list_generation_snapshots(chapter_id)}
    return await asyncio.to_thread(_sync)


@router.post("/chapters/{chapter_id}/generation-snapshots", response_model=dict[str, Any])
async def create_generation_snapshot(request: Request, chapter_id: int, payload: GenerationSnapshotCreate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """为章节创建生成快照。"""
    def _sync():
        try:
            ch = db.get_chapter(chapter_id)
            if not ch:
                raise HTTPException(status_code=404, detail="章节不存在")
            book_id = int(ch.get("book_id") or 0)
            if book_id:
                check_book_owner(db, book_id, user)
            data = payload.model_dump()
            item = db.create_generation_snapshot(chapter_id, data)
            return {"item": item}
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("创建生成快照失败 chapter_id=%s", chapter_id)
            raise HTTPException(status_code=500, detail="创建生成快照失败") from exc
    return await asyncio.to_thread(_sync)


@router.get("/generation-snapshots/{snapshot_id}", response_model=dict[str, Any])
async def get_generation_snapshot(snapshot_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """获取单个生成快照详情。"""
    def _sync():
        item = db.get_generation_snapshot(snapshot_id)
        if item is None:
            raise HTTPException(status_code=404, detail="快照不存在")
        # 鉴权：通过 chapter 的 book_id
        ch = db.get_chapter(int(item.get("chapter_id") or 0))
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        _check_chapter_owner(db, ch, user)
        return {"item": item}
    return await asyncio.to_thread(_sync)


@router.delete("/generation-snapshots/{snapshot_id}", status_code=204)
async def delete_generation_snapshot(request: Request, snapshot_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """删除生成快照。"""
    def _sync():
        try:
            item = db.get_generation_snapshot(snapshot_id)
            if item is None:
                raise HTTPException(status_code=404, detail="快照不存在")
            ch = db.get_chapter(int(item.get("chapter_id") or 0))
            if not ch:
                raise HTTPException(status_code=404, detail="章节不存在")
            book_id = int(ch.get("book_id") or 0)
            if book_id:
                check_book_owner(db, book_id, user)
            db.delete_generation_snapshot(snapshot_id)
            return None
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("删除生成快照失败 snapshot_id=%s", snapshot_id)
            raise HTTPException(status_code=500, detail="删除生成快照失败") from exc
    return await asyncio.to_thread(_sync)


@router.post("/generation-snapshots/{snapshot_id}/restore", response_model=dict[str, Any])
async def restore_generation_snapshot(request: Request, snapshot_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """从生成快照恢复章节内容。"""
    def _sync():
        try:
            item = db.get_generation_snapshot(snapshot_id)
            if item is None:
                raise HTTPException(status_code=404, detail="快照不存在")
            ch = db.get_chapter(int(item.get("chapter_id") or 0))
            if not ch:
                raise HTTPException(status_code=404, detail="章节不存在")
            book_id = int(ch.get("book_id") or 0)
            if book_id:
                check_book_owner(db, book_id, user)
            result = db.restore_generation_snapshot(snapshot_id)
            if result is None:
                raise HTTPException(status_code=500, detail="恢复失败")
            return {"item": result}
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("恢复生成快照失败 snapshot_id=%s", snapshot_id)
            raise HTTPException(status_code=500, detail="恢复生成快照失败") from exc
    return await asyncio.to_thread(_sync)
