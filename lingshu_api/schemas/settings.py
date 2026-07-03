"""设置相关 Schema。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AIProfilePayload(BaseModel):
    """单个 AI 用途配置。"""
    remote_enabled: bool = Field(default=False, description="是否启用远程 AI")
    provider: str = Field(default="custom", description="模型服务商")
    api_key: str = Field(default="", description="API Key")
    base_url: str = Field(default="", description="API Base URL")
    model: str = Field(default="", description="模型名称")
    temperature: float = Field(default=0.7, description="温度参数")
    max_tokens: int = Field(default=0, description="最大 token 数（0 表示不限制）")
    thinking_enabled: bool = Field(default=False, description="是否启用思考模式")
    thinking_budget_tokens: int = Field(default=10000, description="思考模式预算 token 数")
    interval_seconds: int | None = Field(default=None, description="写作探针扫描间隔（秒）")
    auto_write_threshold: float | None = Field(default=None, description="写作探针入草稿置信度阈值")
    probe_enabled: bool | None = Field(default=None, description="是否启用写作探针")


class AISettingsPayload(BaseModel):
    """AI 设置完整请求体 — 对应 PUT /api/settings/ai。"""
    version: str = Field(default="", description="设置版本标识")
    profiles: dict[str, Any] = Field(default_factory=dict, description="各用途的 AI 配置")
    request_retries: int = Field(default=2, description="请求重试次数")
    book_analysis_concurrency: int = Field(default=3, description="全书分析并发数")
    book_analysis_fast_extra_body: str = Field(default="", description="快速分析额外请求体")
    book_analysis_final_extra_body: str = Field(default="", description="最终分析额外请求体")


class AITestRequest(BaseModel):
    """AI 配置测试请求体。"""
    purpose: str = Field(default="writing", description="AI 用途标识")
    profile: AIProfilePayload | None = Field(default=None, description="待测试的配置（为空则使用已保存配置）")


class WorkspaceSettingsPayload(BaseModel):
    """工作台设置请求体。"""
    analysis_pipeline_mode: str = Field(default="legacy", description="分析管线模式: legacy / v3")


# ================================================================
#  响应 Schema
# ================================================================


class AITestResponse(BaseModel):
    """AI 配置测试响应。"""
    ok: bool = Field(..., description="配置是否可用")
    message: str = Field(default="", description="测试结果消息")


class AISettingsResponse(BaseModel):
    """AI 设置响应。"""
    # TODO: 细化 profiles 内部结构为 AIProfileResponse
    model_config = {"extra": "allow"}


class WorkspaceSettingsResponse(BaseModel):
    """工作台设置响应。"""
    # TODO: 细化字段
    model_config = {"extra": "allow"}
