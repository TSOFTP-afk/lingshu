"""
WebSocket 消息协议 Pydantic 模型。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WSMessage(BaseModel):
    """WebSocket 标准消息格式。"""
    type: str = Field(description="消息类型: request|progress|chunk|result|error|cancel|ping")
    task_id: str = Field(default="", description="任务唯一标识 (UUID)")
    payload: dict[str, Any] = Field(default_factory=dict, description="消息载荷")


class WSProgress(BaseModel):
    """进度消息载荷。"""
    task_id: str
    stage: str = ""
    percent: float = 0.0
    message: str = ""


class WSChunk(BaseModel):
    """流式文本块载荷。"""
    task_id: str
    text: str = ""


class WSResult(BaseModel):
    """结果消息载荷。"""
    task_id: str
    status: str = "ok"
    data: dict[str, Any] = Field(default_factory=dict)


class WSGenerateRequest(BaseModel):
    """AI 生成请求。"""
    book_id: int
    outline: str = ""
    chapter_count: int = Field(default=1, ge=1, le=50)
    style_guide: str = ""


class WSReviewRequest(BaseModel):
    """AI 审查请求。"""
    chapter_id: int
    content: str
    review_dimensions: list[str] = Field(default_factory=list)
