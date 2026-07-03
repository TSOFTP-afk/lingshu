"""
云端书籍同步路由 — 列出、上传、同步云端书籍。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from lingshu_api.dependencies import get_cloud_store, get_sync_service, require_login
from lingshu_api.services.book_sync import BookSyncService
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db
from novel_app.bookstore import CloudBookStore

router = APIRouter(prefix="/api/cloud", tags=["cloud_books"])
logger = logging.getLogger(__name__)


class UploadBookPayload(BaseModel):
    """上传书籍到云端的请求体。"""
    pass  # 不需要额外字段，book_id 从 URL 路径获取


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


# ──────────────────── 上传 ────────────────────


@router.post("/books/{book_id}/upload", response_model=dict[str, Any])  # TODO: 细化 response_model
def upload_local_book(
    book_id: int,
    user: dict = Depends(require_login),
    sync_service: BookSyncService = Depends(get_sync_service),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """将本地书籍上传到云端（含全部关联数据）。"""
    user_id = int(user["id"])
    # 校验本地书籍归属
    if not db.check_book_ownership(book_id, user_id):
        raise HTTPException(status_code=403, detail="无权操作该书籍")

    cloud_book_id = sync_service.upload_book_to_cloud(book_id, user_id)
    if not cloud_book_id:
        raise HTTPException(status_code=500, detail="上传失败，请稍后重试")

    return {"ok": True, "cloud_book_id": cloud_book_id}


@router.post("/books/{cloud_book_id}/download", response_model=dict[str, Any])  # TODO: 细化 response_model
def download_cloud_book(
    cloud_book_id: int,
    user: dict = Depends(require_login),
    sync_service: BookSyncService = Depends(get_sync_service),
):
    """将云端书籍下载到本地。"""
    user_id = int(user["id"])

    local_book_id = sync_service.download_cloud_book(cloud_book_id, user_id)
    if not local_book_id:
        raise HTTPException(status_code=500, detail="下载失败，请稍后重试")

    return {"ok": True, "local_book_id": local_book_id}


# ──────────────────── 同步 ────────────────────


@router.post("/sync", response_model=dict[str, Any])  # TODO: 细化 response_model
def sync_uploaded_books(
    user: dict = Depends(require_login),
    sync_service: BookSyncService = Depends(get_sync_service),
):
    """对已上传书籍执行智能同步（按 updated_at 决定方向）。"""
    user_id = int(user["id"])

    result = sync_service.sync_uploaded_books(user_id)
    return {"ok": True, **result}


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
