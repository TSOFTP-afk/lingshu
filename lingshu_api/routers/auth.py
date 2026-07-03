"""
认证相关路由 — 登录、注册、设备管理。
"""
import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from lingshu_api.dependencies import get_store
from lingshu_api.schemas.auth import LoginResponse, OkResponse, UserInfoResponse
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db
from novel_app.bookstore import (
    BookstoreStore,
    LoginPayload,
    RegisterPayload,
    TrustDevicePayload,
    _bearer_token,
    _looks_like_client_hash,
)


def _seed_sample_to_workspace(workspace_db: WorkspaceDB, store: BookstoreStore, user_id: int) -> None:
    """注册后用 WorkspaceDB 将范例小说写入 novels.db（前端 /api/workspace/books 查此库）。

    用服务进程的同一个 Database 连接，避免 sqlite3 锁冲突。
    范例章节内容从 bookstore_demo.db 的 __sample__ cloud_chapters 读取。
    """
    import sqlite3 as _sqlite3

    # 1. 从 bookstore_demo.db 读取范例书 + 章节内容
    with _sqlite3.connect(str(store.db_path)) as conn:
        conn.row_factory = _sqlite3.Row
        sample_book = conn.execute(
            "SELECT b.title, b.outline_text, b.world_text "
            "FROM cloud_books b JOIN users u ON b.user_id=u.id "
            "WHERE u.username='__sample__' LIMIT 1"
        ).fetchone()
        chapters = conn.execute(
            "SELECT ch.title, ch.content, ch.summary_text, ch.sort_order, ch.chapter_type "
            "FROM cloud_chapters ch "
            "JOIN cloud_books b ON ch.cloud_book_id=b.id "
            "JOIN users u ON b.user_id=u.id "
            "WHERE u.username='__sample__' ORDER BY ch.sort_order, ch.id"
        ).fetchall()

    if not sample_book or not chapters:
        return

    # 2. 用 WorkspaceDB 创建书 + 章节（共享 Database 连接，无锁冲突）
    book = workspace_db.create_book(str(sample_book["title"]), user_id=user_id)
    book_id = int(book["id"])
    for ch in chapters:
        chapter = workspace_db.create_chapter(book_id, str(ch["title"]))
        workspace_db.update_chapter(
            chapter["id"],
            content=str(ch["content"]),
            outline="",
            summary_text=str(ch["summary_text"]),
        )

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


def _validate_password_strength(password: str) -> str | None:
    """校验密码强度，返回错误信息或 None。"""
    if len(password) < 8:
        return "密码长度不能少于 8 位"
    if not any(c.isalpha() for c in password):
        return "密码必须包含字母"
    if not any(c.isdigit() for c in password):
        return "密码必须包含数字"
    return None


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
async def login(request: Request, payload: LoginPayload, store: BookstoreStore = Depends(get_store)):
    def _sync():
        token = store.login_user(payload.username, payload.password)
        if not token:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        user = store.get_user_by_token(token)
        return {"access_token": token, "token_type": "bearer", "user": user}
    return await asyncio.to_thread(_sync)


@router.post("/register", response_model=LoginResponse)
@limiter.limit("5/minute")
async def register(
    request: Request,
    payload: RegisterPayload,
    store: BookstoreStore = Depends(get_store),
    workspace_db: WorkspaceDB = Depends(get_workspace_db),
):
    # 客户端哈希后的密码（64位hex）无法校验原始强度，仅对明文密码校验
    if not _looks_like_client_hash(payload.password):
        pw_error = _validate_password_strength(payload.password)
        if pw_error:
            raise HTTPException(status_code=400, detail=pw_error)

    def _sync():
        try:
            user = store.create_user(payload.username, payload.password, payload.is_author)
        except HTTPException as exc:
            if exc.status_code == 409:
                # 防用户名枚举: 返回与成功相同的 200 响应, 但不带有效 token
                return {
                    "access_token": "",
                    "token_type": "bearer",
                    "user": {
                        "id": 0,
                        "username": payload.username,
                        "is_author": payload.is_author,
                        "is_admin": 0,
                        "status": "active",
                    },
                }
            raise
        # 将范例小说写入 novels.db（前端 /api/workspace/books 查此库）
        try:
            _seed_sample_to_workspace(workspace_db, store, int(user["id"]))
        except Exception:  # noqa: BLE001 — 不阻断注册主流程
            pass
        token = store.login_user(payload.username, payload.password)
        return {"access_token": token, "token_type": "bearer", "user": user}
    return await asyncio.to_thread(_sync)


@router.post("/logout", response_model=OkResponse)
async def logout(authorization: str = Header(default=""), store: BookstoreStore = Depends(get_store)):
    token = _bearer_token(authorization)
    if token:
        await asyncio.to_thread(store.logout_token, token)
    return {"ok": True}


@router.get("/me", response_model=UserInfoResponse)
async def me(authorization: str = Header(default=""), store: BookstoreStore = Depends(get_store)):
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")

    def _sync():
        user = store.get_user_by_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="登录已过期")
        return user
    return await asyncio.to_thread(_sync)


@router.post("/check-device", response_model=dict[str, Any])  # TODO: 细化 response_model
async def check_device(
    request: Request,
    payload: TrustDevicePayload,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    client_ip = request.client.host if request.client else "127.0.0.1"

    def _sync():
        user = store.get_user_by_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="登录已过期")
        return store.check_device_trusted(user["id"], payload.fingerprint, client_ip)
    return await asyncio.to_thread(_sync)


@router.post("/trust-device", response_model=OkResponse)
async def trust_device(
    request: Request,
    payload: TrustDevicePayload,
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    client_ip = request.client.host if request.client else "127.0.0.1"

    def _sync():
        user = store.get_user_by_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="登录已过期")
        store.trust_device(user["id"], payload.fingerprint, payload.device_info, client_ip)
        return {"ok": True}
    return await asyncio.to_thread(_sync)


@router.get("/devices", response_model=dict[str, Any])  # TODO: 细化 response_model
async def list_devices(
    authorization: str = Header(default=""),
    store: BookstoreStore = Depends(get_store),
):
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")

    def _sync():
        user = store.get_user_by_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="登录已过期")
        return {"items": store.get_trusted_devices(user["id"])}
    return await asyncio.to_thread(_sync)
