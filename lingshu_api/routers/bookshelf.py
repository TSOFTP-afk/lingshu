"""
书架相关路由 — 书架管理、收藏、阅读进度。
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from lingshu_api.dependencies import get_store, require_login
from novel_app.bookstore import (
    BookshelfCreatePayload,
    BookshelfProgressPayload,
    BookstoreStore,
)

router = APIRouter(prefix="/api/bookshelf", tags=["bookshelf"])


@router.get("", response_model=dict[str, Any])  # TODO: 细化 response_model
def list_bookshelf(
    shelf_id: int | None = Query(default=None),
    user: dict[str, Any] = Depends(require_login),
    store: BookstoreStore = Depends(get_store),
):
    items = store.list_bookshelf_items(int(user["id"]), shelf_id=shelf_id)
    if items is None:
        raise HTTPException(status_code=404, detail="书架不存在")
    return {"items": items}


@router.get("/shelves", response_model=dict[str, Any])  # TODO: 细化 response_model
def list_shelves(
    user: dict[str, Any] = Depends(require_login),
    store: BookstoreStore = Depends(get_store),
):
    return {"items": store.list_bookshelf_shelves(int(user["id"]))}


@router.post("/shelves", response_model=dict[str, Any])  # TODO: 细化 response_model
def create_shelf(
    payload: BookshelfCreatePayload,
    user: dict[str, Any] = Depends(require_login),
    store: BookstoreStore = Depends(get_store),
):
    return {"ok": True, "item": store.create_bookshelf_shelf(int(user["id"]), payload)}


@router.get("/{book_id}", response_model=dict[str, Any])  # TODO: 细化 response_model
def get_bookshelf_status(
    book_id: int,
    user: dict[str, Any] = Depends(require_login),
    store: BookstoreStore = Depends(get_store),
):
    if not store.get_book(book_id):
        raise HTTPException(status_code=404, detail="书籍不存在")
    item = store.get_bookshelf_item(int(user["id"]), book_id)
    return {"in_shelf": item is not None, "item": item}


@router.put("/{book_id}", response_model=dict[str, Any])  # TODO: 细化 response_model
def add_to_bookshelf(
    book_id: int,
    user: dict[str, Any] = Depends(require_login),
    store: BookstoreStore = Depends(get_store),
):
    item = store.add_bookshelf_item(int(user["id"]), book_id)
    if not item:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return {"ok": True, "item": item}


@router.delete("/{book_id}", response_model=dict[str, Any])  # TODO: 细化 response_model
def remove_from_bookshelf(
    book_id: int,
    user: dict[str, Any] = Depends(require_login),
    store: BookstoreStore = Depends(get_store),
):
    store.remove_bookshelf_item(int(user["id"]), book_id)
    return {"ok": True}


@router.patch("/{book_id}/progress", response_model=dict[str, Any])  # TODO: 细化 response_model
def update_progress(
    book_id: int,
    payload: BookshelfProgressPayload,
    user: dict[str, Any] = Depends(require_login),
    store: BookstoreStore = Depends(get_store),
):
    item = store.update_bookshelf_progress(int(user["id"]), book_id, payload)
    if not item:
        raise HTTPException(status_code=404, detail="书籍未加入书架")
    return {"ok": True, "item": item}
