"""
认证相关路由 — personal-client 分支仅保留当前用户信息查询。

登录/注册/登出/设备管理端点已随书城多用户产品线剥离（P3）；
多用户模式的 token 校验语义由 require_login / get_user_by_token 在
数据层（novel_app.bookstore）继续承载。
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Header, HTTPException

from lingshu_api.dependencies import _local_user, _local_user_mode, get_store
from lingshu_api.schemas.auth import UserInfoResponse
from novel_app.bookstore import BookstoreStore, _bearer_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me", response_model=UserInfoResponse)
async def me(authorization: str = Header(default=""), store: BookstoreStore = Depends(get_store)):
    """当前用户信息。

    本地单用户模式（LINGSHU_LOCAL_USER 默认 "1"）下直接返回内存构造的本地用户
    （200），前端 init 无 token 也可借此免登录直达工作台；不校验传入 token，
    与 require_login 的直通语义一致，也避免本地模式陈旧 token 触发前端误登出。
    多用户模式（显式设 0）行为不变：无 token/失效 token 均 401。
    """
    if _local_user_mode():
        return _local_user()
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录")

    def _sync():
        user = store.get_user_by_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="登录已过期")
        return user
    return await asyncio.to_thread(_sync)
