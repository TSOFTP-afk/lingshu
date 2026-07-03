"""统一的 AI 用量记录服务。

将 workspace / generation / chat / analysis 等场景中
重复的用量记录逻辑收敛到此处，保持 fallback 估算和错误隔离策略一致。
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from novel_app.bookstore import estimate_token_count

logger = logging.getLogger(__name__)


def record_ai_usage(
    *,
    store,
    user: dict[str, Any] | int,
    feature: str,
    ai_service: Any = None,
    book_id: int | None = None,
    analysis_run_id: int | None = None,
    fallback_input: str = "",
    fallback_output: str = "",
    fallback_token_source: str = "estimated",
    fallback_prompt_tokens: int | None = None,
) -> None:
    """记录一次 AI 调用的用量。

    优先从 ``ai_service.consume_usage_events()`` 获取精确 token 数据；
    若无事件则使用 fallback 文本估算。

    Parameters
    ----------
    store : BookstoreStore
        数据存储实例，需提供 ``record_user_ai_usage`` 方法。
    user : dict | int
        用户信息。dict 时取 ``user["id"]``，int 时直接使用。
    feature : str
        功能名称，如 ``"generation_draft"``、``"chat"``、``"analysis_pyramid"``。
    ai_service : Any, optional
        AI 服务实例，用于获取精确 token 用量。
    book_id : int | None
        关联的书籍 ID。
    analysis_run_id : int | None
        关联的分析运行 ID。
    fallback_input : str
        fallback 时用于估算 prompt_tokens 的输入文本。
    fallback_output : str
        fallback 时用于估算 completion_tokens 的输出文本。
    fallback_token_source : str
        fallback 记录的 token_source 值，默认 ``"estimated"``。
    fallback_prompt_tokens : int | None
        可直接指定 fallback 的 prompt_tokens，优先于文本估算。
    """
    try:
        user_id = int(user["id"]) if isinstance(user, dict) else int(user)
    except (TypeError, ValueError, KeyError):
        logger.warning("record_ai_usage: invalid user %r", user)
        return

    try:
        events = ai_service.consume_usage_events() if hasattr(ai_service, "consume_usage_events") else []
    except Exception:
        events = []

    try:
        if events:
            for event in events:
                store.record_user_ai_usage(
                    user_id=user_id,
                    book_id=book_id,
                    analysis_run_id=analysis_run_id,
                    feature=feature,
                    model=str(event.get("model") or getattr(ai_service, "model", "") or ""),
                    provider=str(event.get("provider") or getattr(ai_service, "base_url", "") or ""),
                    prompt_tokens=int(event.get("prompt_tokens") or 0),
                    completion_tokens=int(event.get("completion_tokens") or 0),
                    total_tokens=int(event.get("total_tokens") or 0),
                    token_source=str(event.get("token_source") or "unknown"),
                    input_chars=int(event.get("input_chars") or 0),
                    output_chars=int(event.get("output_chars") or 0),
                    trace_id=str(event.get("trace_id") or uuid.uuid4()),
                    prompt_version=str(event.get("prompt_version") or ""),
                    schema_version=str(event.get("schema_version") or ""),
                    latency_ms=int(event.get("latency_ms") or 0),
                    metadata={
                        "trace_source": "provider_usage",
                        "purpose": feature,
                    },
                )
            return

        if fallback_input or fallback_output:
            if fallback_prompt_tokens is not None:
                prompt_tokens = fallback_prompt_tokens
            else:
                prompt_tokens = estimate_token_count(fallback_input)
            completion_tokens = estimate_token_count(fallback_output)
            store.record_user_ai_usage(
                user_id=user_id,
                book_id=book_id,
                analysis_run_id=analysis_run_id,
                feature=feature,
                model=str(getattr(ai_service, "model", "") or "") if ai_service else "",
                provider=str(getattr(ai_service, "base_url", "") or "") if ai_service else "",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                token_source=fallback_token_source,
                input_chars=len(str(fallback_input or "")),
                output_chars=len(str(fallback_output or "")),
                trace_id=str(uuid.uuid4()),
                metadata={
                    "trace_source": "fallback_estimate",
                    "purpose": feature,
                },
            )
    except Exception:
        logger.exception("Failed to record AI usage")
