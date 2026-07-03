"""管理员认证相关 Schema。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AdminLoginPayload(BaseModel):
    """管理员登录请求体。"""
    username: str = Field(..., min_length=1, max_length=64, description="管理员用户名")
    password: str = Field(..., min_length=1, max_length=128, description="管理员密码")
    key_id: str = Field(default="", description="HMAC 密钥 ID")
    timestamp: str = Field(default="", description="HMAC 时间戳")
    hmac_signature: str = Field(default="", description="HMAC 签名")


class AdminLoginResponse(BaseModel):
    """管理员登录响应体。"""
    access_token: str = Field(..., description="访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    admin: dict[str, Any] = Field(..., description="管理员信息")


class AdminInfoResponse(BaseModel):
    """管理员信息响应体。"""
    id: int = Field(..., description="管理员 ID")
    username: str = Field(..., description="管理员用户名")
    display_name: str = Field(default="", description="显示名称")
    role: str = Field(default="operator", description="角色")
    status: str = Field(default="active", description="状态")
