"""
云端书籍只读路由 — 列出、获取云端书籍与同步状态概览。

说明（personal-client P3）：上传/下载/双向同步端点已随 BookSyncService 一并
剥离；本文件仅保留基于 CloudBookStore 的只读查询，待 P3.5 双库合并后整体退场。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from lingshu_api.dependencies import get_cloud_store, require_login
from novel_app.bookstore import CloudBookStore

router = APIRouter(prefix="/api/cloud", tags=["cloud_books"])
logger = logging.getLogger(__name__)


# ──────────────────── 列出 / 获取 ────────────────────


@router.get("/books", response_model=dict[str, Any])  # TODO: 细化 response_model
def list_cloud_books(
    user: dict = Depends(require_login),
    cloud_store: CloudBookStore = Depends(get_cloud_store),
):
    """列出当前用户的云端书籍。"""
    items = cloud_store.list_cloud_books(int(user["id"]))
    return {"items": items}


@router.get("/books/{cloud_book_id}", response_model=dict[str, Any])  # TODO: 细化 response_model
def get_cloud_book(
    cloud_book_id: int,
    user: dict = Depends(require_login),
    cloud_store: CloudBookStore = Depends(get_cloud_store),
):
    """获取指定云端书籍详情。"""
    book = cloud_store.get_cloud_book(int(user["id"]), cloud_book_id)
    if not book:
        raise HTTPException(status_code=404, detail="云端书籍不存在")
    return book


# ──────────────────── 同步状态 ────────────────────


@router.get("/sync/status", response_model=dict[str, Any])  # TODO: 细化 response_model
def get_sync_status(
    user: dict = Depends(require_login),
    cloud_store: CloudBookStore = Depends(get_cloud_store),
):
    """获取当前用户的云端同步状态概览。"""
    user_id = int(user["id"])
    books = cloud_store.list_cloud_books(user_id)
    return {
        "ok": True,
        "cloud_book_count": len(books),
        "books": [
            {
                "cloud_book_id": b["id"],
                "title": b["title"],
                "updated_at": b.get("updated_at", ""),
                "local_book_id": b.get("local_book_id"),
            }
            for b in books
        ],
    }
