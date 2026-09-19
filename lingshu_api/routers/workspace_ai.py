"""
工作台 AI 能力入口 — AI 率检测 / 选区润色（原 lingshu_api/routers/workspace.py 拆分而来）。

这些端点使用 require_ai_access 依赖。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from lingshu_api.dependencies import get_store, require_ai_access
from lingshu_api.routers.workspace_common import _check_chapter_owner, logger
from lingshu_api.services.ai_settings import resolve_ai_profile
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db
from lingshu_api.services.usage_recorder import record_ai_usage
from novel_app.ai.service import SimpleAIService

router = APIRouter(tags=["workspace"])


class AiProbabilityPayload(BaseModel):
    """AI 率检测请求体。"""
    content: str | None = None


class PolishSelectionPayload(BaseModel):
    """润色选区请求体。"""
    text: str = ""
    instruction: str = ""


@router.post("/chapters/{chapter_id}/ai-probability", response_model=dict[str, Any])  # TODO: 细化 response_model
async def detect_chapter_ai_probability(
    request: Request,
    chapter_id: int,
    body: AiProbabilityPayload,
    user: dict = Depends(require_ai_access),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """检测当前章节 AI 生成概率，并写回章节元数据。"""
    def _sync():
        chapter = db.get_chapter(chapter_id)
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")
        _check_chapter_owner(db, chapter, user)
        content = str(body.content or chapter.get("content") or "")
        if not content.strip():
            raise HTTPException(status_code=400, detail="当前章节没有正文")
        try:
            profile = resolve_ai_profile(db.db.data_dir, "detector", user_id=int(user["id"]))
            ai_service = SimpleAIService(
                api_key=profile.get("api_key") or None,
                base_url=profile.get("base_url") or None,
                model=profile.get("model") or None,
            )
            probability, level = ai_service.detect_ai_probability(content)
            db.db.update_chapter_ai_probability(chapter_id, probability, level)
            record_ai_usage(
                store=get_store(request),
                user=user,
                feature="ai_probability",
                ai_service=ai_service,
                book_id=int(chapter.get("book_id") or 0) or None,
                fallback_input=content,
                fallback_output=f"{probability}:{level}",
                fallback_token_source="unknown",
            )
        except Exception as exc:
            logger.exception("AI 率检测失败")
            raise HTTPException(status_code=500, detail="AI 率检测失败，请稍后重试") from exc
        return {
            "ok": True,
            "chapter_id": chapter_id,
            "probability": probability,
            "level": level,
            "item": db.get_chapter(chapter_id),
        }
    return await asyncio.to_thread(_sync)


@router.post("/chapters/{chapter_id}/polish-selection", response_model=dict[str, Any])  # TODO: 细化 response_model
async def polish_chapter_selection(
    request: Request,
    chapter_id: int,
    body: PolishSelectionPayload,
    user: dict = Depends(require_ai_access),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """润色当前章节里用户选中的局部文本。"""
    def _load_chapter():
        chapter = db.get_chapter(chapter_id)
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")
        _check_chapter_owner(db, chapter, user)
        return chapter

    chapter = await asyncio.to_thread(_load_chapter)

    selected_text = str(body.text or "")
    instruction = str(body.instruction or "").strip()
    if not selected_text.strip():
        raise HTTPException(status_code=400, detail="请先选中需要润色的正文")

    def _load_book_and_profile():
        book = db.get_book(int(chapter.get("book_id") or 0)) if chapter.get("book_id") else None
        profile = resolve_ai_profile(db.db.data_dir, "writing", user_id=int(user["id"]))
        return book, profile

    book, profile = await asyncio.to_thread(_load_book_and_profile)

    ai_service = SimpleAIService(
        api_key=profile.get("api_key") or None,
        base_url=profile.get("base_url") or None,
        model=profile.get("model") or None,
    )

    outline = instruction or "请对用户选中的文本做局部润色，保持剧情事实、叙事视角和人物口吻不变。"

    try:
        def _run_polish() -> str:
            chunks = ai_service.stream_generate(
                mode="polish",
                book_title=(book or {}).get("title", ""),
                chapter_title=str(chapter.get("title") or ""),
                outline=outline,
                current_content=selected_text,
                summary_text="",
                selected_skills=[],
                sourcebook_context="",
                require_remote=True,
            )
            return "".join(chunks).strip()

        polished = await asyncio.to_thread(_run_polish)
        record_ai_usage(
            store=get_store(request),
            user=user,
            feature="polish_selection",
            ai_service=ai_service,
            book_id=int(chapter.get("book_id") or 0) or None,
            fallback_input=outline + "\n" + selected_text,
            fallback_output=polished,
            fallback_token_source="estimated",
        )
    except Exception as exc:
        logger.exception("润色失败")
        raise HTTPException(status_code=500, detail="润色失败，请稍后重试") from exc

    if not polished:
        raise HTTPException(status_code=500, detail="润色结果为空")

    return {
        "ok": True,
        "chapter_id": chapter_id,
        "original": selected_text,
        "polished": polished,
    }
