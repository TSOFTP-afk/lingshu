"""
共享依赖注入 — 提供 BookstoreStore 实例和认证辅助函数。

状态存储在 FastAPI app.state 上，通过 Depends 提供依赖注入，
避免模块级全局变量，利于测试和多实例场景。
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections.abc import Iterator
from typing import Any

from fastapi import Header, HTTPException, Request

from lingshu_api.services.db_bridge import WorkspaceDB
from novel_app.bookstore import BookstoreStore, CloudBookStore, _bearer_token, _public_user

# ── setter：由 main.py 在 create_app 时调用，写入 app.state ──────────

def set_store(app, store: BookstoreStore) -> None:
    """设置 store 实例到 app.state（在 create_app 时调用）。"""
    app.state.store = store


def set_cloud_store(app, cloud_store: CloudBookStore) -> None:
    """设置 CloudBookStore 实例到 app.state（在 create_app 时调用）。"""
    app.state.cloud_store = cloud_store


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


# ── 本地单用户模式（personal-client 分支 P2）──────────────────────

_LOCAL_USER_USERNAME = "local"


def _local_user_mode() -> bool:
    """是否处于本地单用户模式（免登录直通）。

    读环境变量 ``LINGSHU_LOCAL_USER``，**默认开启（"1"）**：personal-client 分支的
    产品语义即"本人单用户的本地创作客户端"，登录不该是使用 AI/工作台的前置。
    仅当显式设置字面 ``"0"`` 时关闭，恢复多用户登录语义——存量测试（根 conftest）、
    Playwright 登录 E2E（playwright.config.ts）与 tools/seed_test_env.py 均依赖
    该开关保持原行为。
    """
    raw = os.environ.get("LINGSHU_LOCAL_USER", "1").strip()
    return raw != "0"


def _local_user() -> dict[str, Any]:
    """构造本地单用户的内存用户 dict（不查库，本地模式 bookstore 可能没有该用户）。

    结构与 ``novel_app.bookstore.security._public_user`` 返回的用户 dict 同构，
    字段覆盖下游全部使用点（user["id"]/user.get("is_author")/user.get("is_admin")/
    user.get("status")/user.get("username")）。id=1 与 is_admin=1/is_author=1 使
    require_login 等鉴权依赖在本地模式全部直通。
    """
    return {
        "id": 1,
        "username": _LOCAL_USER_USERNAME,
        "is_author": 1,
        "is_admin": 1,
        "status": "active",
        "bind_reader_id": None,
        "bind_reader_name": None,
    }


def get_optional_user(request: Request, authorization: str = Header(default="")) -> dict[str, Any] | None:
    """解析 Authorization 头，返回用户信息或 None。"""
    token = _bearer_token(authorization)
    if not token:
        return None
    return _public_user(get_store(request).get_user_by_token(token))


def require_login(request: Request, authorization: str = Header(default="")) -> dict[str, Any]:
    """要求已登录，返回用户信息。

    本地单用户模式（默认）下跳过 token 校验，直接返回内存构造的本地用户；
    显式设 ``LINGSHU_LOCAL_USER=0`` 恢复多用户登录语义（401 照旧）。
    """
    if _local_user_mode():
        return _local_user()
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    user = get_store(request).get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="登录已过期")
    return user


def require_ai_access(request: Request, authorization: str = Header(default="")) -> Iterator[dict[str, Any]]:
    """AI 功能统一门禁：登录 + 账号状态 + 每日 token 预算 + 每用户并发上限。

    本地单用户模式（默认）下跳过登录与配额校验，直通本地用户——单人本地使用
    自己的 Key，无需限额；显式设 ``LINGSHU_LOCAL_USER=0`` 恢复多用户语义。
    yield 形式依赖：请求结束后（含异常路径）在 finally 中必定释放并发槽位。
    """
    if _local_user_mode():
        yield _local_user()
        return
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


_logger = logging.getLogger(__name__)


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
