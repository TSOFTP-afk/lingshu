"""
共享依赖注入 — 提供 BookstoreStore 实例和认证辅助函数。

状态存储在 FastAPI app.state 上，通过 Depends 提供依赖注入，
避免模块级全局变量，利于测试和多实例场景。
"""
from __future__ import annotations

import logging
import os
import secrets
import sqlite3
import threading
from collections.abc import Iterator
from typing import Any

from fastapi import Header, HTTPException, Request

from lingshu_api.services.book_sync import BookSyncService
from lingshu_api.services.db_bridge import WorkspaceDB
from novel_app.bookstore import BookstoreStore, CloudBookStore, _bearer_token, _public_user

# ── setter：由 main.py 在 create_app 时调用，写入 app.state ──────────

def set_store(app, store: BookstoreStore) -> None:
    """设置 store 实例到 app.state（在 create_app 时调用）。"""
    app.state.store = store


def set_cloud_store(app, cloud_store: CloudBookStore) -> None:
    """设置 CloudBookStore 实例到 app.state（在 create_app 时调用）。"""
    app.state.cloud_store = cloud_store


def set_sync_service(app, service: BookSyncService) -> None:
    """设置 BookSyncService 实例到 app.state（在 create_app 时调用）。"""
    app.state.sync_service = service


# ── FastAPI 依赖：通过 Request.app.state 读取 ──────────────────────

def get_store(request: Request) -> BookstoreStore:
    """FastAPI 依赖：获取 BookstoreStore 实例。"""
    store = getattr(request.app.state, 'store', None)
    if store is None:
        raise HTTPException(status_code=500, detail="Store 未初始化")
    return store


def get_cloud_store(request: Request) -> CloudBookStore:
    """FastAPI 依赖：获取 CloudBookStore 实例。"""
    cloud_store = getattr(request.app.state, 'cloud_store', None)
    if cloud_store is None:
        raise HTTPException(status_code=500, detail="CloudStore 未初始化")
    return cloud_store


def get_sync_service(request: Request) -> BookSyncService:
    """FastAPI 依赖：获取 BookSyncService 实例。"""
    sync_service = getattr(request.app.state, 'sync_service', None)
    if sync_service is None:
        raise HTTPException(status_code=500, detail="SyncService 未初始化")
    return sync_service


def get_optional_user(request: Request, authorization: str = Header(default="")) -> dict[str, Any] | None:
    """解析 Authorization 头，返回用户信息或 None。"""
    token = _bearer_token(authorization)
    if not token:
        return None
    return _public_user(get_store(request).get_user_by_token(token))


def require_login(request: Request, authorization: str = Header(default="")) -> dict[str, Any]:
    """要求已登录，返回用户信息。"""
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_store(request).get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="登录已过期")
    return user


def require_ai_access(request: Request, authorization: str = Header(default="")) -> Iterator[dict[str, Any]]:
    """AI 功能统一门禁：登录 + 账号状态 + 每日 token 预算 + 每用户并发上限。

    yield 形式依赖：请求结束后（含异常路径）在 finally 中必定释放并发槽位。
    """
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录后使用 AI 功能")
    user = get_store(request).get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录后使用 AI 功能")
    # 账号状态：get_user_by_token 只返回 status='active' 的用户，此处兜底防御
    if str(user.get("status") or "active") != "active":
        raise HTTPException(status_code=403, detail="当前账号已被禁用，无法使用 AI 功能")

    user_id = int(user["id"])
    _check_daily_ai_token_budget(get_store(request).db_path, user_id)
    _acquire_ai_slot(user_id)
    try:
        yield user
    finally:
        _release_ai_slot(user_id)


# ── AI 配额：每日 token 预算 + 进程内并发计数 ─────────────────────

_AI_DAILY_TOKEN_LIMIT_DEFAULT = 200_000
_AI_CONCURRENCY_PER_USER_DEFAULT = 3

_ai_concurrency_lock = threading.Lock()
_ai_concurrency: dict[int, int] = {}


def _ai_daily_token_limit() -> int:
    """每日 AI token 预算，读 env ``LINGSHU_DAILY_AI_TOKEN_LIMIT``，非法或非正值回退默认。"""
    raw = os.environ.get("LINGSHU_DAILY_AI_TOKEN_LIMIT", "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if value > 0:
            return value
    return _AI_DAILY_TOKEN_LIMIT_DEFAULT


def _ai_concurrency_limit() -> int:
    """每用户 AI 并发上限，读 env ``LINGSHU_AI_CONCURRENCY_PER_USER``，非法或非正值回退默认。"""
    raw = os.environ.get("LINGSHU_AI_CONCURRENCY_PER_USER", "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if value > 0:
            return value
    return _AI_CONCURRENCY_PER_USER_DEFAULT


def _check_daily_ai_token_budget(db_path, user_id: int) -> None:
    """查询当天该用户已消耗 token 总和（单条带索引条件的 SUM），超预算抛 429。"""
    limit = _ai_daily_token_limit()
    try:
        with sqlite3.connect(str(db_path)) as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(total_tokens), 0)
                FROM user_ai_usage_events
                WHERE user_id = ? AND created_at >= datetime('now', 'start of day')
                """,
                (int(user_id),),
            ).fetchone()
            used = int(row[0] or 0) if row else 0
    except sqlite3.Error:
        # 用量统计失败时放行，不阻断业务（记录告警便于排查）
        _logger.warning("每日 AI 用量查询失败，跳过预算校验: user_id=%s", user_id, exc_info=True)
        return
    if used >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"今日 AI 用量已达到上限（{used}/{limit} tokens），请明日再试或在 AI 设置中配置自己的 API Key",
        )


def _acquire_ai_slot(user_id: int) -> None:
    """获取该用户的 AI 并发槽位，超过上限抛 429。"""
    limit = _ai_concurrency_limit()
    with _ai_concurrency_lock:
        current = _ai_concurrency.get(user_id, 0)
        if current >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"AI 请求并发已达上限（{limit}），请等待进行中的请求完成后再试",
            )
        _ai_concurrency[user_id] = current + 1


def _release_ai_slot(user_id: int) -> None:
    """释放该用户的 AI 并发槽位（请求结束时必定调用）。"""
    with _ai_concurrency_lock:
        remaining = _ai_concurrency.get(user_id, 0) - 1
        if remaining > 0:
            _ai_concurrency[user_id] = remaining
        else:
            _ai_concurrency.pop(user_id, None)


def require_author(request: Request, authorization: str = Header(default="")) -> dict[str, Any]:
    """要求已登录且为作者身份。"""
    user = require_login(request, authorization)
    if not int(user.get("is_author") or 0):
        raise HTTPException(status_code=403, detail="当前账号不是作者账号")
    return user


def require_admin(request: Request, authorization: str = Header(default="")) -> dict[str, Any]:
    """要求已登录且为管理员身份。"""
    user = require_login(request, authorization)
    if not int(user.get("is_admin") or 0):
        raise HTTPException(status_code=403, detail="管理员权限不足")
    return user


def verify_publish_token(
    x_publish_token: str = Header(default=""),
    resolved_token: str | None = None,
) -> bool:
    """验证桌面端发布令牌。"""
    if not resolved_token:
        raise HTTPException(status_code=503, detail="发布令牌未配置，已拒绝写入")
    if not secrets.compare_digest(x_publish_token, resolved_token):
        raise HTTPException(status_code=401, detail="发布令牌无效")
    return True


_logger = logging.getLogger(__name__)


def try_cloud_sync(request: Request, book_id: int, user: dict | None) -> None:
    """已登录时执行云端同步：静默收集 + 已上传书籍编辑同步。"""
    if not user:
        return
    try:
        sync_service = get_sync_service(request)
        user_id = int(user["id"])
        sync_service.silent_collect(book_id, user_id)
        sync_service.sync_book_edit(book_id, user_id)
    except Exception as e:
        _logger.warning("云端同步失败: book_id=%s, user_id=%s, error=%s", book_id, user.get("id"), e)


def check_book_owner(db: WorkspaceDB, book_id: int, user: dict) -> None:
    """校验书籍归属，不属于当前用户则抛 403。"""
    if not db.check_book_ownership(book_id, int(user["id"])):
        raise HTTPException(status_code=403, detail="无权操作该书籍")


def check_chapter_owner(db: WorkspaceDB, chapter_id: int, user: dict) -> int:
    """通过 chapter_id 反查 book_id 并校验所有权。

    用于 WebSocket 等 only-chapter_id 场景，防止攻击者只传 chapter_id 绕过 book_id 所有权校验（V6 IDOR）。
    章节不存在抛 404；不属于当前用户抛 403。返回归属的 book_id。
    """
    chapter = db.get_chapter(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    book_id = int(chapter.get("book_id") or 0)
    if not book_id:
        raise HTTPException(status_code=404, detail="章节未关联书籍")
    check_book_owner(db, book_id, user)
    return book_id
