"""伏笔管理 API — 增删改查 + 从分析同步。

提供工作台伏笔界面的后端支持：
- 列出书籍所有伏笔（可按状态筛选）
- 新增伏笔（手工录入）
- 编辑伏笔字段（描述/状态/优先级/章节/回收说明）
- 删除伏笔
- 从 analysis_facts 同步自动抽取的伏笔

对应前端：ForeshadowTab.vue + stores/foreshadow.js
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from lingshu_api.dependencies import check_book_owner, require_login
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db

router = APIRouter(prefix="/api/workspace", tags=["foreshadows"])
logger = logging.getLogger(__name__)


class ForeshadowCreatePayload(BaseModel):
    """新增伏笔请求体。"""
    description: str
    status: str = "pending"
    priority: str = "medium"
    setup_chapter_id: int | None = None
    payoff_chapter_id: int | None = None
    resolution_note: str = ""


class ForeshadowUpdatePayload(BaseModel):
    """更新伏笔请求体。所有字段可选。"""
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    setup_chapter_id: int | None = None
    payoff_chapter_id: int | None = None
    resolution_note: str | None = None


def _row_to_dict(row: Any) -> dict[str, Any]:
    """将 sqlite3.Row 转为 dict。"""
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "book_id": int(row["book_id"]),
        "description": str(row["description"] or ""),
        "status": str(row["status"] or "pending"),
        "priority": str(row["priority"] or "medium"),
        "source": str(row["source"] or "manual"),
        "setup_chapter_id": row["setup_chapter_id"] if row["setup_chapter_id"] else None,
        "payoff_chapter_id": row["payoff_chapter_id"] if row["payoff_chapter_id"] else None,
        "setup_chapter_title": str(row["setup_chapter_title"]) if "setup_chapter_title" in row.keys() and row["setup_chapter_title"] else None,  # noqa: SIM118 — row 是 sqlite3.Row，`in row`/直接迭代产出的是值而非键，必须用 .keys()
        "payoff_chapter_title": str(row["payoff_chapter_title"]) if "payoff_chapter_title" in row.keys() and row["payoff_chapter_title"] else None,  # noqa: SIM118 — row 是 sqlite3.Row，`in row`/直接迭代产出的是值而非键，必须用 .keys()
        "resolution_note": str(row["resolution_note"] or ""),
        "fact_uid": str(row["fact_uid"] or ""),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
    }


@router.get("/books/{book_id}/foreshadows")
async def list_foreshadows(
    book_id: int,
    status: str | None = Query(default=None, description="按状态筛选: pending/resolved/abandoned"),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """列出书籍的伏笔列表。"""
    def _sync():
        check_book_owner(db, book_id, user)
        rows = db.db.list_foreshadows(book_id, status=status)
        return {"items": [_row_to_dict(r) for r in rows]}
    return await asyncio.to_thread(_sync)


@router.post("/books/{book_id}/foreshadows")
async def create_foreshadow(
    book_id: int,
    payload: ForeshadowCreatePayload,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """新增伏笔（手工录入）。"""
    def _sync():
        check_book_owner(db, book_id, user)
        if not payload.description.strip():
            raise HTTPException(status_code=400, detail="伏笔描述不能为空")
        foreshadow_id = db.db.create_foreshadow(
            book_id,
            payload.description.strip(),
            status=payload.status,
            priority=payload.priority,
            source="manual",
            setup_chapter_id=payload.setup_chapter_id,
            payoff_chapter_id=payload.payoff_chapter_id,
            resolution_note=payload.resolution_note,
        )
        row = db.db.get_foreshadow(foreshadow_id)
        return {"ok": True, "item": _row_to_dict(row)}
    return await asyncio.to_thread(_sync)


@router.patch("/foreshadows/{foreshadow_id}")
async def update_foreshadow(
    foreshadow_id: int,
    payload: ForeshadowUpdatePayload,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """更新伏笔字段。"""
    def _sync():
        row = db.db.get_foreshadow(foreshadow_id)
        if not row:
            raise HTTPException(status_code=404, detail="伏笔不存在")
        book_id = int(row["book_id"])
        check_book_owner(db, book_id, user)
        fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
        if "description" in fields and not str(fields["description"]).strip():
            raise HTTPException(status_code=400, detail="伏笔描述不能为空")
        updated = db.db.update_foreshadow(foreshadow_id, **fields)
        return {"ok": True, "item": _row_to_dict(updated)}
    return await asyncio.to_thread(_sync)


@router.delete("/foreshadows/{foreshadow_id}")
async def delete_foreshadow(
    foreshadow_id: int,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """删除伏笔。"""
    def _sync():
        row = db.db.get_foreshadow(foreshadow_id)
        if not row:
            raise HTTPException(status_code=404, detail="伏笔不存在")
        book_id = int(row["book_id"])
        check_book_owner(db, book_id, user)
        db.db.delete_foreshadow(foreshadow_id)
        return {"ok": True}
    return await asyncio.to_thread(_sync)


@router.post("/books/{book_id}/foreshadows/sync")
async def sync_foreshadows_from_analysis(
    book_id: int,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """从 analysis_facts 手动同步伏笔（自动抽取的 foreshadowing 事实）。"""
    def _sync():
        check_book_owner(db, book_id, user)
        from novel_app.analysis.foreshadow_sync import sync_foreshadows_from_facts
        added = sync_foreshadows_from_facts(db.db, book_id)
        return {"ok": True, "added": added}
    return await asyncio.to_thread(_sync)
