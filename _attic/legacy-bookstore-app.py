from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

from .models import (
    DEFAULT_DB_PATH,
    DEFAULT_WEB_BASE_URL,
    AdminBookUpdatePayload,
    AdminChapterUpdatePayload,
    AdminUserUpdatePayload,
    AuthorBookCreatePayload,
    AuthorBookUpdatePayload,
    AuthorChapterUpdatePayload,
    BookshelfCreatePayload,
    BookshelfProgressPayload,
    LoginPayload,
    PublishChapterPayload,
    RegisterPayload,
    TrustDevicePayload,
    _admin_usernames_from_env,
    _normalize_web_base_url,
)
from .security import (
    _bearer_token,
    _public_user,
)
from .store import BookstoreStore


def create_app(
    db_path: Path | None = None,
    publish_token: str | None = None,
    web_base_url: str | None = None,
) -> FastAPI:
    resolved_db_path = db_path or Path(os.environ.get("BOOKSTORE_DB_PATH", "") or DEFAULT_DB_PATH)
    resolved_token = (publish_token if publish_token is not None else os.environ.get("BOOKSTORE_PUBLISH_TOKEN", "")).strip()
    resolved_web_base_url = _normalize_web_base_url(web_base_url or os.environ.get("BOOKSTORE_WEB_BASE_URL", DEFAULT_WEB_BASE_URL))
    store = BookstoreStore(resolved_db_path)
    store.sync_admin_users(_admin_usernames_from_env())
    app = FastAPI(title="灵枢本地书城 API")
    app_limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = app_limiter

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"})
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_origin_regex=(
            r"^http://(localhost|127\.0\.0\.1|0\.0\.0\.0|"
            r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
            r"192\.168\.\d{1,3}\.\d{1,3}|"
            r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(:\d+)?$"
        ),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def verify_token(x_publish_token: str = Header(default="")) -> bool:
        if not resolved_token:
            raise HTTPException(status_code=503, detail="发布令牌未配置，已拒绝写入")
        if not secrets.compare_digest(x_publish_token, resolved_token):
            raise HTTPException(status_code=401, detail="发布令牌无效")
        return True

    def user_from_authorization(authorization: str, active_store: BookstoreStore) -> dict[str, Any] | None:
        token = _bearer_token(authorization)
        if not token:
            return None
        return _public_user(active_store.get_user_by_token(token))

    def require_login_user(authorization: str, active_store: BookstoreStore) -> dict[str, Any]:
        token = _bearer_token(authorization)
        if not token:
            raise HTTPException(status_code=401, detail="未登录")
        user = active_store.get_user_by_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="登录已过期")
        return user

    def require_author_user(authorization: str, active_store: BookstoreStore) -> dict[str, Any]:
        token = _bearer_token(authorization)
        if not token:
            raise HTTPException(status_code=401, detail="未登录")
        user = active_store.get_user_by_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="登录已过期")
        if not int(user.get("is_author") or 0):
            raise HTTPException(status_code=403, detail="当前账号不是作者账号")
        return user

    def require_admin_user(authorization: str, active_store: BookstoreStore) -> dict[str, Any]:
        user = require_login_user(authorization, active_store)
        if not int(user.get("is_admin") or 0):
            raise HTTPException(status_code=403, detail="管理员权限不足")
        return user

    def get_store() -> BookstoreStore:
        return store

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/api/admin/overview")
    def admin_overview(
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        require_admin_user(authorization, active_store)
        return active_store.admin_overview()

    @app.get("/api/admin/user-stats")
    def admin_user_stats(
        granularity: str = Query(default="monthly"),
        year: int | None = Query(default=None),
        month: str | None = Query(default=None),
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        require_admin_user(authorization, active_store)
        return active_store.admin_user_stats(granularity=granularity, year=year, month=month)

    @app.get("/api/admin/quotas")
    def admin_quotas(
        q: str = Query(default=""),
        tier: str = Query(default=""),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=5, le=100),
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        require_admin_user(authorization, active_store)
        return active_store.admin_list_quotas(q=q, tier=tier, page=page, page_size=page_size)

    @app.get("/api/admin/users")
    def admin_users(
        q: str = Query(default=""),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=5, le=100),
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        require_admin_user(authorization, active_store)
        return active_store.admin_list_users(q=q, page=page, page_size=page_size)

    @app.get("/api/admin/users/{user_id}")
    def admin_user_detail(
        user_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        require_admin_user(authorization, active_store)
        item = active_store.admin_get_user(user_id)
        if not item:
            raise HTTPException(status_code=404, detail="用户不存在")
        return item

    @app.patch("/api/admin/users/{user_id}")
    def admin_update_user(
        user_id: int,
        payload: AdminUserUpdatePayload,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        admin = require_admin_user(authorization, active_store)
        item = active_store.admin_update_user(int(admin["id"]), user_id, payload)
        if not item:
            raise HTTPException(status_code=404, detail="用户不存在")
        return {"ok": True, "item": item}

    @app.delete("/api/admin/users/{user_id}")
    def admin_disable_user(
        user_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        admin = require_admin_user(authorization, active_store)
        if not active_store.admin_disable_user(int(admin["id"]), user_id):
            raise HTTPException(status_code=404, detail="用户不存在")
        return {"ok": True}

    @app.post("/api/admin/users/{user_id}/restore")
    def admin_restore_user(
        user_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        admin = require_admin_user(authorization, active_store)
        if not active_store.admin_restore_user(int(admin["id"]), user_id):
            raise HTTPException(status_code=404, detail="用户不存在")
        return {"ok": True}

    @app.get("/api/admin/books")
    def admin_books(
        q: str = Query(default=""),
        include_deleted: bool = Query(default=True),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=5, le=100),
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        require_admin_user(authorization, active_store)
        return active_store.admin_list_books(q=q, include_deleted=include_deleted, page=page, page_size=page_size)

    @app.get("/api/admin/books/{book_id}")
    def admin_book_detail(
        book_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        require_admin_user(authorization, active_store)
        item = active_store.admin_get_book(book_id)
        if not item:
            raise HTTPException(status_code=404, detail="作品不存在")
        return item

    @app.patch("/api/admin/books/{book_id}")
    def admin_update_book(
        book_id: int,
        payload: AdminBookUpdatePayload,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        admin = require_admin_user(authorization, active_store)
        item = active_store.admin_update_book(int(admin["id"]), book_id, payload)
        if not item:
            raise HTTPException(status_code=404, detail="作品不存在")
        return {"ok": True, "item": item}

    @app.delete("/api/admin/books/{book_id}")
    def admin_delete_book(
        book_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        admin = require_admin_user(authorization, active_store)
        if not active_store.admin_soft_delete_book(int(admin["id"]), book_id):
            raise HTTPException(status_code=404, detail="作品不存在")
        return {"ok": True}

    @app.post("/api/admin/books/{book_id}/restore")
    def admin_restore_book(
        book_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        admin = require_admin_user(authorization, active_store)
        if not active_store.admin_restore_book(int(admin["id"]), book_id):
            raise HTTPException(status_code=404, detail="作品不存在")
        return {"ok": True}

    @app.get("/api/admin/chapters")
    def admin_chapters(
        book_id: int | None = Query(default=None),
        q: str = Query(default=""),
        include_deleted: bool = Query(default=True),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=5, le=100),
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        require_admin_user(authorization, active_store)
        return active_store.admin_list_chapters(book_id=book_id, q=q, include_deleted=include_deleted, page=page, page_size=page_size)

    @app.get("/api/admin/chapters/{chapter_id}")
    def admin_chapter_detail(
        chapter_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        require_admin_user(authorization, active_store)
        item = active_store.admin_get_chapter(chapter_id)
        if not item:
            raise HTTPException(status_code=404, detail="章节不存在")
        return item

    @app.patch("/api/admin/chapters/{chapter_id}")
    def admin_update_chapter(
        chapter_id: int,
        payload: AdminChapterUpdatePayload,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        admin = require_admin_user(authorization, active_store)
        item = active_store.admin_update_chapter(int(admin["id"]), chapter_id, payload)
        if not item:
            raise HTTPException(status_code=404, detail="章节不存在")
        return {"ok": True, "item": item}

    @app.delete("/api/admin/chapters/{chapter_id}")
    def admin_delete_chapter(
        chapter_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        admin = require_admin_user(authorization, active_store)
        result = active_store.admin_soft_delete_chapter(int(admin["id"]), chapter_id)
        if not result:
            raise HTTPException(status_code=404, detail="章节不存在")
        return {"ok": True, "hard_deleted": result.get("hard_deleted", False)}

    @app.post("/api/admin/chapters/{chapter_id}/restore")
    def admin_restore_chapter(
        chapter_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        admin = require_admin_user(authorization, active_store)
        if not active_store.admin_restore_chapter(int(admin["id"]), chapter_id):
            raise HTTPException(status_code=404, detail="章节不存在")
        return {"ok": True}

    @app.get("/api/admin/bookshelf/shelves")
    def admin_bookshelf_shelves(
        include_deleted: bool = Query(default=True),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=5, le=100),
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        require_admin_user(authorization, active_store)
        return active_store.admin_list_bookshelf_shelves(include_deleted=include_deleted, page=page, page_size=page_size)

    @app.get("/api/admin/bookshelf/items")
    def admin_bookshelf_items(
        include_deleted: bool = Query(default=True),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=5, le=100),
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        require_admin_user(authorization, active_store)
        return active_store.admin_list_bookshelf_items(include_deleted=include_deleted, page=page, page_size=page_size)

    @app.delete("/api/admin/bookshelf/shelves/{shelf_id}")
    def admin_delete_bookshelf_shelf(
        shelf_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        admin = require_admin_user(authorization, active_store)
        if not active_store.admin_soft_delete_shelf(int(admin["id"]), shelf_id):
            raise HTTPException(status_code=404, detail="书架不存在")
        return {"ok": True}

    @app.post("/api/admin/bookshelf/shelves/{shelf_id}/restore")
    def admin_restore_bookshelf_shelf(
        shelf_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        admin = require_admin_user(authorization, active_store)
        if not active_store.admin_restore_shelf(int(admin["id"]), shelf_id):
            raise HTTPException(status_code=404, detail="书架不存在")
        return {"ok": True}

    @app.delete("/api/admin/bookshelf/items/{item_id}")
    def admin_delete_bookshelf_item(
        item_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        admin = require_admin_user(authorization, active_store)
        if not active_store.admin_soft_delete_shelf_item(int(admin["id"]), item_id):
            raise HTTPException(status_code=404, detail="书架条目不存在")
        return {"ok": True}

    @app.post("/api/admin/bookshelf/items/{item_id}/restore")
    def admin_restore_bookshelf_item(
        item_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        admin = require_admin_user(authorization, active_store)
        if not active_store.admin_restore_shelf_item(int(admin["id"]), item_id):
            raise HTTPException(status_code=404, detail="书架条目不存在")
        return {"ok": True}

    @app.get("/api/admin/tokens")
    def admin_tokens(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=5, le=100),
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        require_admin_user(authorization, active_store)
        return active_store.admin_list_tokens(page=page, page_size=page_size)

    @app.delete("/api/admin/tokens/{token}")
    def admin_revoke_token(
        token: str,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        admin = require_admin_user(authorization, active_store)
        if not active_store.admin_revoke_token(int(admin["id"]), token):
            raise HTTPException(status_code=404, detail="token 不存在")
        return {"ok": True}

    @app.get("/api/admin/devices")
    def admin_devices(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=5, le=100),
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        require_admin_user(authorization, active_store)
        return active_store.admin_list_devices(page=page, page_size=page_size)

    @app.delete("/api/admin/devices/{device_id}")
    def admin_revoke_device(
        device_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        admin = require_admin_user(authorization, active_store)
        if not active_store.admin_revoke_device(int(admin["id"]), device_id):
            raise HTTPException(status_code=404, detail="可信设备不存在")
        return {"ok": True}

    @app.get("/api/admin/audit-logs")
    def admin_audit_logs(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=5, le=100),
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        require_admin_user(authorization, active_store)
        return active_store.admin_list_audit_logs(page=page, page_size=page_size)

    @app.post("/api/auth/login")
    @app_limiter.limit("5/minute")
    def login(request: Request, payload: LoginPayload, active_store: BookstoreStore = Depends(get_store)) -> dict[str, Any]:
        token = active_store.login_user(payload.username, payload.password)
        if not token:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        user = active_store.get_user_by_token(token)
        return {"access_token": token, "token_type": "bearer", "user": user}

    @app.post("/api/auth/register")
    @app_limiter.limit("5/minute")
    def register(request: Request, payload: RegisterPayload, active_store: BookstoreStore = Depends(get_store)) -> dict[str, Any]:
        user = active_store.create_user(payload.username, payload.password, payload.is_author)
        token = active_store.login_user(payload.username, payload.password)
        return {"access_token": token, "token_type": "bearer", "user": user}

    @app.post("/api/auth/logout")
    def logout(authorization: str = Header(default=""), active_store: BookstoreStore = Depends(get_store)) -> dict[str, Any]:
        token = _bearer_token(authorization)
        if token:
            active_store.logout_token(token)
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(authorization: str = Header(default=""), active_store: BookstoreStore = Depends(get_store)) -> dict[str, Any]:
        token = _bearer_token(authorization)
        if not token:
            raise HTTPException(status_code=401, detail="未登录")
        user = active_store.get_user_by_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="登录已过期")
        return user

    @app.get("/api/bookshelf")
    def list_bookshelf(
        shelf_id: int | None = Query(default=None),
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = require_login_user(authorization, active_store)
        items = active_store.list_bookshelf_items(int(user["id"]), shelf_id=shelf_id)
        if items is None:
            raise HTTPException(status_code=404, detail="书架不存在")
        return {"items": items}

    @app.get("/api/bookshelf/shelves")
    def list_bookshelf_shelves(
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = require_login_user(authorization, active_store)
        return {"items": active_store.list_bookshelf_shelves(int(user["id"]))}

    @app.post("/api/bookshelf/shelves")
    def create_bookshelf_shelf(
        payload: BookshelfCreatePayload,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = require_login_user(authorization, active_store)
        return {"ok": True, "item": active_store.create_bookshelf_shelf(int(user["id"]), payload)}

    @app.get("/api/bookshelf/{book_id}")
    def get_bookshelf_status(
        book_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = require_login_user(authorization, active_store)
        if not active_store.get_book(book_id):
            raise HTTPException(status_code=404, detail="书籍不存在")
        item = active_store.get_bookshelf_item(int(user["id"]), book_id)
        return {"in_shelf": item is not None, "item": item}

    @app.put("/api/bookshelf/{book_id}")
    def add_bookshelf(
        book_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = require_login_user(authorization, active_store)
        item = active_store.add_bookshelf_item(int(user["id"]), book_id)
        if not item:
            raise HTTPException(status_code=404, detail="书籍不存在")
        return {"ok": True, "item": item}

    @app.delete("/api/bookshelf/{book_id}")
    def remove_bookshelf(
        book_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = require_login_user(authorization, active_store)
        active_store.remove_bookshelf_item(int(user["id"]), book_id)
        return {"ok": True}

    @app.patch("/api/bookshelf/{book_id}/progress")
    def update_bookshelf_progress(
        book_id: int,
        payload: BookshelfProgressPayload,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = require_login_user(authorization, active_store)
        item = active_store.update_bookshelf_progress(int(user["id"]), book_id, payload)
        if not item:
            raise HTTPException(status_code=404, detail="书籍未加入书架")
        return {"ok": True, "item": item}

    @app.get("/api/author/books")
    def author_books(authorization: str = Header(default=""), active_store: BookstoreStore = Depends(get_store)) -> dict[str, Any]:
        token = _bearer_token(authorization)
        if not token:
            raise HTTPException(status_code=401, detail="未登录")
        user = active_store.get_user_by_token(token)
        if not user or not user.get("is_author"):
            return {"items": []}
        return {"items": active_store.get_author_books(user["id"])}

    @app.post("/api/author/books")
    def create_author_book(
        payload: AuthorBookCreatePayload,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = require_author_user(authorization, active_store)
        return {"ok": True, "item": active_store.create_author_book(int(user["id"]), payload)}

    @app.patch("/api/author/books/{book_id}")
    def update_author_book(
        book_id: int,
        payload: AuthorBookUpdatePayload,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = require_author_user(authorization, active_store)
        item = active_store.update_author_book_summary(int(user["id"]), book_id, payload)
        if not item:
            raise HTTPException(status_code=404, detail="作品不存在")
        return {"ok": True, "item": item}

    @app.get("/api/author/books/{book_id}/chapters")
    def list_author_chapters(
        book_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = require_author_user(authorization, active_store)
        items = active_store.list_author_chapters(int(user["id"]), book_id)
        if items is None:
            raise HTTPException(status_code=404, detail="作品不存在")
        return {"items": items}

    @app.post("/api/author/books/{book_id}/chapters/next")
    def create_next_author_chapter(
        book_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = require_author_user(authorization, active_store)
        item = active_store.create_next_author_chapter(int(user["id"]), book_id)
        if not item:
            raise HTTPException(status_code=404, detail="作品不存在")
        return {"ok": True, "item": item}

    @app.get("/api/author/books/{book_id}/chapters/{chapter_id}")
    def get_author_chapter(
        book_id: int,
        chapter_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = require_author_user(authorization, active_store)
        item = active_store.get_author_chapter(int(user["id"]), book_id, chapter_id)
        if not item:
            raise HTTPException(status_code=404, detail="章节不存在")
        return item

    @app.patch("/api/author/books/{book_id}/chapters/{chapter_id}")
    def update_author_chapter(
        book_id: int,
        chapter_id: int,
        payload: AuthorChapterUpdatePayload,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = require_author_user(authorization, active_store)
        item = active_store.update_author_chapter(int(user["id"]), book_id, chapter_id, payload)
        if not item:
            raise HTTPException(status_code=404, detail="章节不存在")
        return {"ok": True, "item": item}

    @app.post("/api/author/books/{book_id}/chapters/{chapter_id}/publish")
    def publish_author_chapter(
        book_id: int,
        chapter_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = require_author_user(authorization, active_store)
        item = active_store.publish_author_chapter(int(user["id"]), book_id, chapter_id)
        if not item:
            raise HTTPException(status_code=404, detail="章节不存在")
        return {"ok": True, "item": item}

    @app.delete("/api/author/books/{book_id}/chapters/{chapter_id}")
    def delete_author_chapter(
        book_id: int,
        chapter_id: int,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = require_author_user(authorization, active_store)
        if not active_store.delete_author_chapter(int(user["id"]), book_id, chapter_id):
            raise HTTPException(status_code=404, detail="章节不存在")
        return {"ok": True}

    @app.post("/api/auth/check-device")
    def check_device(
        request: Request,
        payload: TrustDevicePayload,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        token = _bearer_token(authorization)
        if not token:
            raise HTTPException(status_code=401, detail="未登录")
        user = active_store.get_user_by_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="登录已过期")
        client_ip = request.client.host if request.client else "127.0.0.1"
        result = active_store.check_device_trusted(user["id"], payload.fingerprint, client_ip)
        return result

    @app.post("/api/auth/trust-device")
    def trust_device(
        request: Request,
        payload: TrustDevicePayload,
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        token = _bearer_token(authorization)
        if not token:
            raise HTTPException(status_code=401, detail="未登录")
        user = active_store.get_user_by_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="登录已过期")
        client_ip = request.client.host if request.client else "127.0.0.1"
        active_store.trust_device(user["id"], payload.fingerprint, payload.device_info, client_ip)
        return {"ok": True}

    @app.get("/api/auth/devices")
    def list_devices(
        authorization: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        token = _bearer_token(authorization)
        if not token:
            raise HTTPException(status_code=401, detail="未登录")
        user = active_store.get_user_by_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="登录已过期")
        return {"items": active_store.get_trusted_devices(user["id"])}

    @app.post("/api/publish/chapter")
    def publish_chapter(
        payload: PublishChapterPayload,
        authorization: str = Header(default=""),
        x_publish_token: str = Header(default=""),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        user = user_from_authorization(authorization, active_store)
        if user:
            if not int(user.get("is_author") or 0):
                raise HTTPException(status_code=403, detail="当前账号不是作者账号")
            payload_data = payload.model_dump()
            payload_data["source_app"] = f"user_{int(user['id'])}"
            payload = PublishChapterPayload(**payload_data)
        else:
            verify_token(x_publish_token)
        ids = active_store.publish_chapter(payload)
        return {
            "ok": True,
            **ids,
            "web_url": f"{resolved_web_base_url}/books/{ids['book_id']}/chapters/{ids['chapter_id']}",
        }

    @app.get("/api/books")
    def list_books(
        q: str = Query(default=""),
        category: str = Query(default="all"),
        active_store: BookstoreStore = Depends(get_store),
    ) -> dict[str, Any]:
        return {"items": active_store.list_books(query=q, category=category)}

    @app.get("/api/books/{book_id}")
    def get_book(book_id: int, active_store: BookstoreStore = Depends(get_store)) -> dict[str, Any]:
        book = active_store.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="书籍不存在")
        return book

    @app.get("/api/books/{book_id}/chapters")
    def list_chapters(book_id: int, active_store: BookstoreStore = Depends(get_store)) -> dict[str, Any]:
        if not active_store.get_book(book_id):
            raise HTTPException(status_code=404, detail="书籍不存在")
        return {"items": active_store.list_chapters(book_id)}

    @app.get("/api/chapters/{chapter_id}")
    def get_chapter(chapter_id: int, active_store: BookstoreStore = Depends(get_store)) -> dict[str, Any]:
        chapter = active_store.get_chapter(chapter_id)
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")
        return chapter

    return app
