"""用户认证响应 Schema。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoginResponse(BaseModel):
    """登录/注册成功响应。"""
    access_token: str = Field(..., description="访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    user: dict[str, Any] = Field(..., description="用户信息")


class UserInfoResponse(BaseModel):
    """当前用户信息响应。"""
    # TODO: 细化字段 — 当前 bookstore_api 返回的 user dict 结构不固定
    model_config = {"extra": "allow"}


class OkResponse(BaseModel):
    """通用成功响应。"""
    ok: bool = Field(default=True, description="操作是否成功")
