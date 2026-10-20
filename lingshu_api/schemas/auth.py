"""用户认证响应 Schema — personal-client 分支仅保留当前用户信息响应。"""
from __future__ import annotations

from pydantic import BaseModel


class UserInfoResponse(BaseModel):
    """当前用户信息响应。"""
    # TODO: 细化字段 — 当前 bookstore_api 返回的 user dict 结构不固定
    model_config = {"extra": "allow"}
