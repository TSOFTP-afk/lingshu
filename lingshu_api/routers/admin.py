"""
管理后台路由 — 用户管理、作品管理、章节管理、书架管理、审计日志。
"""
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from lingshu_api.dependencies import get_store
from lingshu_api.routers.admin_auth import (
    _admin_keys_configured,
    _ensure_admin_tables,
    _get_admin_by_token,
    _get_db_path,
    verify_admin_hmac_headers,
)
from novel_app.bookstore import (
    AdminBookUpdatePayload,
    AdminChapterUpdatePayload,
    AdminUserUpdatePayload,
    BookstoreStore,
    _bearer_token,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(request: Request, authorization: str, store: BookstoreStore) -> dict[str, Any]:
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    db_path = _get_db_path(store)
    _ensure_admin_tables(db_path)
    # 双因子验证：HMAC 签名 + Bearer Token
    if _admin_keys_configured(db_path):
        verify_admin_hmac_headers(db_path, request)
    admin = _get_admin_by_token(db_path, token)
    if not admin:
        raise HTTPException(status_code=401, detail="管理员登录已过期或无效")
    return admin


@router.get("/overview")
def overview(request: Request, authorization: str = Header(default=""), store: BookstoreStore = Depends(get_store)):
    _require_admin(request, authorization, store)
    return store.admin_overview()


@router.get("/user-stats")
def user_stats(
    request: Request,
    granularity: str = Query(default="monthly"),
    year: int | None = Query(default=None),
    month: str | None = Query(default=None),
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    _require_admin(request, authorization, store)
    return store.admin_user_stats(granularity=granularity, year=year, month=month)


@router.get("/quotas")
def list_quotas(
    request: Request,
    q: str = Query(default=""),
    tier: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    _require_admin(request, authorization, store)
    return store.admin_list_quotas(q=q, tier=tier, page=page, page_size=page_size)


@router.get("/users")
def list_users(
    request: Request,
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    _require_admin(request, authorization, store)
    return store.admin_list_users(q=q, page=page, page_size=page_size)


@router.get("/users/{user_id}")
def get_user(
    user_id: int,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    _require_admin(request, authorization, store)
    item = store.admin_get_user(user_id)
    if not item:
        raise HTTPException(status_code=404, detail="用户不存在")
    return item


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    payload: AdminUserUpdatePayload,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    admin = _require_admin(request, authorization, store)
    item = store.admin_update_user(int(admin["id"]), user_id, payload)
    if not item:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"ok": True, "item": item}


@router.delete("/users/{user_id}")
def disable_user(
    user_id: int,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    admin = _require_admin(request, authorization, store)
    if not store.admin_disable_user(int(admin["id"]), user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"ok": True}


@router.post("/users/{user_id}/restore")
def restore_user(
    user_id: int,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    admin = _require_admin(request, authorization, store)
    if not store.admin_restore_user(int(admin["id"]), user_id):
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"ok": True}


@router.get("/books")
def list_books(
    request: Request,
    q: str = Query(default=""),
    include_deleted: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    _require_admin(request, authorization, store)
    return store.admin_list_books(q=q, include_deleted=include_deleted, page=page, page_size=page_size)


@router.get("/books/{book_id}")
def get_book(
    book_id: int,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    _require_admin(request, authorization, store)
    item = store.admin_get_book(book_id)
    if not item:
        raise HTTPException(status_code=404, detail="作品不存在")
    return item


@router.patch("/books/{book_id}")
def update_book(
    book_id: int,
    payload: AdminBookUpdatePayload,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    admin = _require_admin(request, authorization, store)
    item = store.admin_update_book(int(admin["id"]), book_id, payload)
    if not item:
        raise HTTPException(status_code=404, detail="作品不存在")
    return {"ok": True, "item": item}


@router.delete("/books/{book_id}")
def delete_book(
    book_id: int,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    admin = _require_admin(request, authorization, store)
    if not store.admin_soft_delete_book(int(admin["id"]), book_id):
        raise HTTPException(status_code=404, detail="作品不存在")
    return {"ok": True}


@router.post("/books/{book_id}/restore")
def restore_book(
    book_id: int,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    admin = _require_admin(request, authorization, store)
    if not store.admin_restore_book(int(admin["id"]), book_id):
        raise HTTPException(status_code=404, detail="作品不存在")
    return {"ok": True}


@router.get("/chapters")
def list_chapters(
    request: Request,
    book_id: int | None = Query(default=None),
    q: str = Query(default=""),
    include_deleted: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    _require_admin(request, authorization, store)
    return store.admin_list_chapters(book_id=book_id, q=q, include_deleted=include_deleted, page=page, page_size=page_size)


@router.get("/chapters/{chapter_id}")
def get_chapter(
    chapter_id: int,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    _require_admin(request, authorization, store)
    item = store.admin_get_chapter(chapter_id)
    if not item:
        raise HTTPException(status_code=404, detail="章节不存在")
    return item


@router.patch("/chapters/{chapter_id}")
def update_chapter(
    chapter_id: int,
    payload: AdminChapterUpdatePayload,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    admin = _require_admin(request, authorization, store)
    item = store.admin_update_chapter(int(admin["id"]), chapter_id, payload)
    if not item:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"ok": True, "item": item}


@router.delete("/chapters/{chapter_id}")
def delete_chapter(
    chapter_id: int,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    admin = _require_admin(request, authorization, store)
    result = store.admin_soft_delete_chapter(int(admin["id"]), chapter_id)
    if not result:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"ok": True, "hard_deleted": result.get("hard_deleted", False)}


@router.post("/chapters/{chapter_id}/restore")
def restore_chapter(
    chapter_id: int,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    admin = _require_admin(request, authorization, store)
    if not store.admin_restore_chapter(int(admin["id"]), chapter_id):
        raise HTTPException(status_code=404, detail="章节不存在")
    return {"ok": True}


@router.get("/bookshelf/shelves")
def list_bookshelf_shelves(
    request: Request,
    include_deleted: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    _require_admin(request, authorization, store)
    return store.admin_list_bookshelf_shelves(include_deleted=include_deleted, page=page, page_size=page_size)


@router.get("/bookshelf/items")
def list_bookshelf_items(
    request: Request,
    include_deleted: bool = Query(default=True),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    _require_admin(request, authorization, store)
    return store.admin_list_bookshelf_items(include_deleted=include_deleted, page=page, page_size=page_size)


@router.delete("/bookshelf/shelves/{shelf_id}")
def delete_bookshelf_shelf(
    shelf_id: int,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    admin = _require_admin(request, authorization, store)
    if not store.admin_soft_delete_shelf(int(admin["id"]), shelf_id):
        raise HTTPException(status_code=404, detail="书架不存在")
    return {"ok": True}


@router.post("/bookshelf/shelves/{shelf_id}/restore")
def restore_bookshelf_shelf(
    shelf_id: int,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    admin = _require_admin(request, authorization, store)
    if not store.admin_restore_shelf(int(admin["id"]), shelf_id):
        raise HTTPException(status_code=404, detail="书架不存在")
    return {"ok": True}


@router.delete("/bookshelf/items/{item_id}")
def delete_bookshelf_item(
    item_id: int,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    admin = _require_admin(request, authorization, store)
    if not store.admin_soft_delete_shelf_item(int(admin["id"]), item_id):
        raise HTTPException(status_code=404, detail="书架条目不存在")
    return {"ok": True}


@router.post("/bookshelf/items/{item_id}/restore")
def restore_bookshelf_item(
    item_id: int,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    admin = _require_admin(request, authorization, store)
    if not store.admin_restore_shelf_item(int(admin["id"]), item_id):
        raise HTTPException(status_code=404, detail="书架条目不存在")
    return {"ok": True}


@router.get("/tokens")
def list_tokens(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    _require_admin(request, authorization, store)
    return store.admin_list_tokens(page=page, page_size=page_size)


@router.delete("/tokens/{token}")
def revoke_token(
    token: str,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    admin = _require_admin(request, authorization, store)
    if not store.admin_revoke_token(int(admin["id"]), token):
        raise HTTPException(status_code=404, detail="token 不存在")
    return {"ok": True}


@router.get("/devices")
def list_devices(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    _require_admin(request, authorization, store)
    return store.admin_list_devices(page=page, page_size=page_size)


@router.delete("/devices/{device_id}")
def revoke_device(
    device_id: int,
    request: Request,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    admin = _require_admin(request, authorization, store)
    if not store.admin_revoke_device(int(admin["id"]), device_id):
        raise HTTPException(status_code=404, detail="可信设备不存在")
    return {"ok": True}


@router.get("/audit-logs")
def audit_logs(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=5, le=100),
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    _require_admin(request, authorization, store)
    return store.admin_list_audit_logs(page=page, page_size=page_size)
