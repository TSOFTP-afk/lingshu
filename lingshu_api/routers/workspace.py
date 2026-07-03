"""
工作台核心 API — 书籍/分卷/章节 CRUD + 导入。

对应迁移的 Qt 模块:
- app_tree.py    → 书籍/分卷/章节列表 + 树结构
- app_editor.py  → 章节正文+大纲保存/读取
- app_import.py  → 文件导入 (TXT/DOCX)
- forms.py       → 书籍大纲表单 (已有 structured_templates)
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel

from lingshu_api.dependencies import check_book_owner, get_store, require_ai_access, require_login, try_cloud_sync
from lingshu_api.schemas.analysis_v3 import AnalysisV1OneShotRunCreate
from lingshu_api.schemas.workspace import (
    BookCreate,
    BookItemResponse,
    BookListResponse,
    BookOutlineSave,
    BookUpdate,
    ChapterCreate,
    ChapterItemResponse,
    ChapterListResponse,
    ChapterMove,
    ChapterUpdate,
    GenerationSnapshotCreate,
    OkResponse,
    SnapshotCreate,
    SnapshotListResponse,
    SnapshotRestore,
    VolumeCreate,
    VolumeItemResponse,
    VolumeUpdate,
)
from lingshu_api.services.ai_settings import load_ai_settings, resolve_ai_profile
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db
from lingshu_api.services.usage_recorder import record_ai_usage
from novel_app.ai.service import SimpleAIService
from novel_app.analysis.diff_apply import apply_analysis_cards
from novel_app.analysis.store import AnalysisStore
from novel_app.database import ALL_VOLUMES, UNASSIGNED_VOLUMES
from novel_app.json_utils import extract_json_dict
from novel_app.structured_templates import BOOK_OUTLINE_FORM_SCHEMA
from novel_app.text_importer import ParsedBook, ParsedChapter, parse_long_text

router = APIRouter(prefix="/api/workspace", tags=["workspace"])
logger = logging.getLogger(__name__)


class AiProbabilityPayload(BaseModel):
    """AI 率检测请求体。"""
    content: str | None = None


class PolishSelectionPayload(BaseModel):
    """润色选区请求体。"""
    text: str = ""
    instruction: str = ""


class ApplyAnalysisPayload(BaseModel):
    """应用分析结果请求体。"""
    user_override: bool = False
    allow_weak_evidence: bool | None = None

    @property
    def weak_evidence_allowed(self) -> bool:
        return bool(self.user_override or self.allow_weak_evidence)


def _check_chapter_owner(db: WorkspaceDB, chapter: dict, user: dict) -> int:
    book_id = int(chapter.get("book_id") or 0)
    if book_id:
        check_book_owner(db, book_id, user)
    return book_id


@router.get("/health", response_model=OkResponse)
async def workspace_health():
    """工作台 API 健康检查。"""
    return {"ok": True}


# ================================================================
#  书籍 CRUD
# ================================================================

@router.get("/books", response_model=BookListResponse)
async def list_books(user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """列出所有作品（含分卷-章节树结构）。"""
    def _sync():
        user_id = int(user["id"])
        books = []
        for b in db.list_books(user_id=user_id):
            book_data = db.get_book(b["id"])
            if book_data:
                books.append(book_data)
        return {"items": books}
    return await asyncio.to_thread(_sync)


@router.post("/books", response_model=BookItemResponse)
async def create_book(request: Request, payload: BookCreate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """创建新作品。"""
    def _sync():
        user_id = int(user["id"])
        book = db.create_book(payload.title, user_id=user_id)
        book_id = int(book["id"])
        book = db.get_book(book_id) or book
        try_cloud_sync(request, book_id, user)
        return {"ok": True, "item": book}
    return await asyncio.to_thread(_sync)


@router.get("/books/{book_id}", response_model=dict[str, Any])  # TODO: 细化为 BookDetailResponse
async def get_book(book_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """获取作品详情（含全部分卷-章节树）。"""
    def _sync():
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
        check_book_owner(db, book_id, user)
        return book
    return await asyncio.to_thread(_sync)


@router.patch("/books/{book_id}", response_model=BookItemResponse)
async def update_book(request: Request, book_id: int, payload: BookUpdate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """更新作品信息（标题/简介）。"""
    def _sync():
        check_book_owner(db, book_id, user)
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
        if payload.title:
            db.rename_book(book_id, payload.title)
        try_cloud_sync(request, book_id, user)
        return {"ok": True, "item": db.get_book(book_id)}
    return await asyncio.to_thread(_sync)


@router.delete("/books/{book_id}", response_model=OkResponse)
async def delete_book(book_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """删除作品及其全部分卷/章节。"""
    def _sync():
        check_book_owner(db, book_id, user)
        if not db.get_book(book_id):
            raise HTTPException(status_code=404, detail="作品不存在")
        db.delete_book(book_id)
        return {"ok": True}
    return await asyncio.to_thread(_sync)


# ================================================================
#  分卷 CRUD
# ================================================================

@router.post("/books/{book_id}/volumes", response_model=VolumeItemResponse)
async def create_volume(request: Request, book_id: int, payload: VolumeCreate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """创建分卷。"""
    def _sync():
        check_book_owner(db, book_id, user)
        vol = db.create_volume(book_id, payload.title)
        try_cloud_sync(request, book_id, user)
        return {"ok": True, "item": vol}
    return await asyncio.to_thread(_sync)


@router.patch("/volumes/{volume_id}", response_model=OkResponse)
async def update_volume(request: Request, volume_id: int, payload: VolumeUpdate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """更新分卷（重命名/排序）。"""
    def _sync():
        volume = db.get_volume(volume_id)
        book_id = int(volume["book_id"]) if volume else None
        if book_id:
            check_book_owner(db, book_id, user)
        if payload.title:
            db.rename_volume(volume_id, payload.title)
        if book_id:
            try_cloud_sync(request, book_id, user)
        return {"ok": True}
    return await asyncio.to_thread(_sync)


@router.delete("/volumes/{volume_id}", response_model=OkResponse)
async def delete_volume(request: Request, volume_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """删除分卷及其下全部章节。"""
    def _sync():
        volume = db.get_volume(volume_id)
        book_id = int(volume["book_id"]) if volume else None
        if book_id:
            check_book_owner(db, book_id, user)
        db.delete_volume(volume_id)
        if book_id:
            try_cloud_sync(request, book_id, user)
        return {"ok": True}
    return await asyncio.to_thread(_sync)


# ================================================================
#  章节 CRUD
# ================================================================

@router.post("/volumes/{volume_id}/chapters", response_model=ChapterItemResponse)
async def create_chapter_in_volume(request: Request, volume_id: int, payload: ChapterCreate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """在某分卷下创建章节。"""
    def _sync():
        volume = db.get_volume(volume_id)
        if not volume:
            raise HTTPException(status_code=404, detail="分卷不存在")
        book_id = int(volume["book_id"])
        check_book_owner(db, book_id, user)
        ch = db.create_chapter(book_id, payload.title, volume_id)
        try_cloud_sync(request, book_id, user)
        return {"ok": True, "item": ch}
    return await asyncio.to_thread(_sync)


@router.post("/books/{book_id}/chapters", response_model=ChapterItemResponse)
async def create_chapter_in_book(request: Request, book_id: int, payload: ChapterCreate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """在作品下创建未分卷章节。"""
    def _sync():
        check_book_owner(db, book_id, user)
        ch = db.create_chapter(book_id, payload.title, None)
        try_cloud_sync(request, book_id, user)
        return {"ok": True, "item": ch}
    return await asyncio.to_thread(_sync)


@router.get("/books/{book_id}/chapters", response_model=ChapterListResponse)
async def list_chapters(
    book_id: int,
    volume_filter: int | str = Query(default=ALL_VOLUMES, alias="volume"),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """列出作品下的章节（可按分卷筛选）。"""
    def _sync():
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
        check_book_owner(db, book_id, user)
        try:
            vf = int(volume_filter)
        except (ValueError, TypeError):
            vf = ALL_VOLUMES if volume_filter == "all" else UNASSIGNED_VOLUMES
        chapters = db.list_chapters(book_id, vf)
        return {"items": chapters}
    return await asyncio.to_thread(_sync)


@router.get("/books/{book_id}/search", response_model=dict[str, Any])  # TODO: 细化为 SearchResponse
async def search_book_text(
    book_id: int,
    q: str = Query(default="", description="精确查找关键词"),
    limit: int = Query(default=100, ge=1, le=200),
    case_sensitive: bool = Query(default=False),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """在当前作品章节标题和正文中做精确文本查找。"""
    def _sync():
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
        check_book_owner(db, book_id, user)
        query = q.strip()
        if not query:
            return {"items": [], "query": query}
        return {
            "items": db.search_book(book_id, query, limit=limit, case_sensitive=case_sensitive),
            "query": query,
        }
    return await asyncio.to_thread(_sync)


@router.get("/chapters/{chapter_id}", response_model=dict[str, Any])  # TODO: 细化为 ChapterDetailResponse
async def get_chapter(chapter_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """获取章节完整内容（正文+大纲）。"""
    def _sync():
        ch = db.get_chapter(chapter_id)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        _check_chapter_owner(db, ch, user)
        return ch
    return await asyncio.to_thread(_sync)


@router.patch("/chapters/{chapter_id}", response_model=ChapterItemResponse)
async def update_chapter(request: Request, chapter_id: int, payload: ChapterUpdate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """保存章节（正文/大纲/标题）。"""
    def _sync():
        ch = db.get_chapter(chapter_id)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        book_id = int(ch.get("book_id") or 0)
        if book_id:
            check_book_owner(db, book_id, user)
        kwargs = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
        if kwargs:
            ch = db.update_chapter(chapter_id, **kwargs)
            book_id = int(ch.get("book_id") or 0) if ch else None
            if book_id:
                try_cloud_sync(request, book_id, user)
            return {"ok": True, "item": ch}
        if book_id:
            try_cloud_sync(request, book_id, user)
        return {"ok": True, "item": db.get_chapter(chapter_id)}
    return await asyncio.to_thread(_sync)


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


@router.delete("/chapters/{chapter_id}", response_model=OkResponse)
async def delete_chapter(request: Request, chapter_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """删除章节。"""
    def _sync():
        ch = db.get_chapter(chapter_id)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        book_id = int(ch.get("book_id") or 0)
        if book_id:
            check_book_owner(db, book_id, user)
        db.delete_chapter(chapter_id)
        if book_id:
            try_cloud_sync(request, book_id, user)
        return {"ok": True}
    return await asyncio.to_thread(_sync)


@router.patch("/chapters/{chapter_id}/move", response_model=OkResponse)
async def move_chapter(request: Request, chapter_id: int, payload: ChapterMove, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """移动章节到目标分卷并设置排序位置。"""
    def _sync():
        ch = db.get_chapter(chapter_id)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        book_id = int(ch.get("book_id") or 0)
        if book_id:
            check_book_owner(db, book_id, user)
        db.move_chapter(chapter_id, payload.target_volume_id, payload.sort_order)
        if book_id:
            try_cloud_sync(request, book_id, user)
        return {"ok": True}
    return await asyncio.to_thread(_sync)


# ====================================================================
# 写作探针伴随机制
# ====================================================================

def _get_probe_service(db: WorkspaceDB, *, user_id: int | None = None):
    """根据 AI 设置构造 WritingProbeService。"""
    from novel_app.analysis.writing_probe import WritingProbeService

    settings = load_ai_settings(db.db.data_dir, reveal_secrets=False, user_id=user_id)
    profiles = settings.get("profiles", {})
    probe_profile = profiles.get("writing_probe", {}) if isinstance(profiles, dict) else {}
    probe_enabled = bool(probe_profile.get("probe_enabled", False))
    interval_seconds = int(probe_profile.get("interval_seconds", 8) or 8)
    threshold = float(probe_profile.get("auto_write_threshold", 0.55) or 0.55)
    ai_available = probe_enabled and bool(
        probe_profile.get("api_key_configured") or probe_profile.get("api_key")
    )
    return WritingProbeService(
        db.db,
        probe_enabled=probe_enabled,
        ai_available=ai_available,
        interval_seconds=interval_seconds,
        auto_write_threshold=threshold,
        user_id=user_id,
    )


@router.post("/books/{book_id}/chapters/{chapter_id}/writing-probe")
async def trigger_writing_probe(
    book_id: int,
    chapter_id: int,
    user: dict = Depends(require_ai_access),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """触发写作探针扫描指定章节，生成草稿。"""
    def _sync():
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
        check_book_owner(db, book_id, user)
        service = _get_probe_service(db, user_id=int(user["id"]))
        if not service.probe_enabled:
            raise HTTPException(status_code=403, detail="写作探针未启用")
        return service.scan_chapter(book_id, chapter_id)
    return await asyncio.to_thread(_sync)


@router.get("/books/{book_id}/chapters/{chapter_id}/writing-probe/drafts")
async def list_writing_probe_drafts(
    book_id: int,
    chapter_id: int,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """获取指定章节的探针草稿列表。"""
    def _sync():
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
        check_book_owner(db, book_id, user)
        service = _get_probe_service(db, user_id=int(user["id"]))
        return {"items": service.list_chapter_drafts(book_id, chapter_id)}
    return await asyncio.to_thread(_sync)


@router.post("/books/{book_id}/chapters/{chapter_id}/writing-probe/writeback-all")
async def writeback_all_writing_probe_drafts(
    book_id: int,
    chapter_id: int,
    user: dict = Depends(require_ai_access),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """批量写回指定章节所有探针草稿。"""
    def _sync():
        import json as _json

        from novel_app.analysis.v3_writeback import writeback_v3_card

        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
        check_book_owner(db, book_id, user)
        service = _get_probe_service(db, user_id=int(user["id"]))
        drafts = service.list_chapter_drafts(book_id, chapter_id)
        results = []
        for draft in drafts:
            if draft["status"] == "applied":
                continue
            if draft["card_type"] == "writing_probe_summary":
                summary_text = draft["payload"].get("writeback_fields", {}).get("summary_text", "")
                if summary_text:
                    r = service.apply_summary(
                        book_id, chapter_id, summary_text, actor=str(user.get("id", "user"))
                    )
                    results.append({"card_uid": draft["card_uid"], "ok": r["ok"], "type": "summary"})
                continue
            if draft["card_type"] != "writing_probe_character":
                continue
            run_id = service._ensure_companion_run(book_id)
            try:
                card_row = {
                    "id": draft["id"],
                    "book_id": book_id,
                    "run_id": run_id,
                    "card_uid": draft["card_uid"],
                    "card_type": draft["card_type"],
                    "entity_uid": "",
                    "ars_score": 0.0,
                    "status": "draft",
                    "payload_json": _json.dumps(draft["payload"], ensure_ascii=False),
                    "diff_json": "{}",
                }
                wb_result = writeback_v3_card(db.db, book_id, card_row, require_generator=False)
                if wb_result.success:
                    db.db.connection.execute(
                        "UPDATE analysis_cards SET status='applied', applied_at=CURRENT_TIMESTAMP, "
                        "applied_table=?, applied_id=? WHERE id=?",
                        (wb_result.applied_table, wb_result.applied_id, draft["id"]),
                    )
                    db.db.connection.commit()
                    results.append({
                        "card_uid": draft["card_uid"], "ok": True, "type": "character",
                        "applied_table": wb_result.applied_table, "applied_id": wb_result.applied_id,
                    })
                else:
                    results.append({
                        "card_uid": draft["card_uid"], "ok": False, "type": "character",
                        "error": wb_result.detail,
                    })
            except Exception as e:
                results.append({
                    "card_uid": draft["card_uid"], "ok": False, "type": "character", "error": str(e),
                })
        # 广播事件总线
        try:
            from lingshu_api.services.events import get_event_bus
            get_event_bus().publish("writeback_completed", {
                "book_id": book_id,
                "actor": str(user.get("id", "user")),
                "writebackTarget": "character",
            })
        except Exception:
            pass
        success_count = sum(1 for r in results if r["ok"])
        return {"ok": True, "total": len(results), "success": success_count, "results": results}
    return await asyncio.to_thread(_sync)


@router.post("/chapters/{chapter_id}/apply-summary")
async def apply_chapter_summary(
    chapter_id: int,
    payload: dict,
    user: dict = Depends(require_ai_access),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """将概要草稿写回 chapters.summary_text。"""
    def _sync():
        chapter = db.db.get_chapter(chapter_id)
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")
        check_book_owner(db, int(chapter["book_id"]), user)
        summary_text = str(payload.get("summary_text") or "").strip()
        if not summary_text:
            raise HTTPException(status_code=400, detail="summary_text 不能为空")
        service = _get_probe_service(db, user_id=int(user["id"]))
        result = service.apply_summary(
            int(chapter["book_id"]), chapter_id, summary_text, actor=str(user.get("id", "user"))
        )
        if not result["ok"]:
            raise HTTPException(status_code=500, detail=result.get("error", "写回失败"))
        return result
    return await asyncio.to_thread(_sync)


@router.get("/books/{book_id}/chapters/{chapter_id}/appearing-characters")
async def list_appearing_characters(
    book_id: int,
    chapter_id: int,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """列出当前章节出场的现有人物（按出现次数排序）。"""
    def _sync():
        from novel_app.analysis.writing_probe import WritingProbeService

        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
        check_book_owner(db, book_id, user)
        # appearing-characters 不依赖探针开关，始终可用
        service = WritingProbeService(db.db, probe_enabled=True, ai_available=False)
        return {"items": service.find_appearing_characters(book_id, chapter_id)}
    return await asyncio.to_thread(_sync)


# ================================================================
#  书籍大纲 / 世界观读写（对接 structured_templates）
# ================================================================

@router.get("/books/{book_id}/outline", response_model=dict[str, Any])  # TODO: 细化为 BookOutlineResponse
async def get_book_outline(book_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """获取书籍大纲（Markdown + 表单数据）。"""
    def _sync():
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
        check_book_owner(db, book_id, user)
        outline_data = db.db.get_book_outline_form(book_id) if db.db else {}
        return {
            "outline_text": book.get("outline_text", ""),
            "outline_data": outline_data if isinstance(outline_data, dict) else {},
            "outline_schema": BOOK_OUTLINE_FORM_SCHEMA,
        }
    return await asyncio.to_thread(_sync)


@router.put("/books/{book_id}/outline", response_model=dict[str, Any])  # TODO: 细化为 BookOutlineResponse
async def save_book_outline(request: Request, book_id: int, payload: BookOutlineSave, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """保存书籍大纲（Markdown 文本 + 可选表单数据）。"""
    def _sync():
        check_book_owner(db, book_id, user)
        if not db.get_book(book_id):
            raise HTTPException(status_code=404, detail="作品不存在")
        outline_text = payload.resolved_outline_text
        outline_data = payload.outline_data if not outline_text.strip() else None
        if isinstance(outline_data, dict):
            updated = db.update_book_outline(book_id, outline_text, outline_data)
        else:
            updated = db.update_book_outline(book_id, outline_text)
        updated_data = db.db.get_book_outline_form(book_id) if db.db else {}
        try_cloud_sync(request, book_id, user)
        return {
            "ok": True,
            "outline_text": (updated or {}).get("outline_text", ""),
            "outline_data": updated_data if isinstance(updated_data, dict) else {},
            "outline_schema": BOOK_OUTLINE_FORM_SCHEMA,
        }
    return await asyncio.to_thread(_sync)


# ================================================================
#  快照管理
# ================================================================

@router.get("/chapters/{chapter_id}/snapshots", response_model=SnapshotListResponse)
async def list_snapshots(chapter_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """列出章节的所有快照。"""
    def _sync():
        ch = db.get_chapter(chapter_id)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        _check_chapter_owner(db, ch, user)
        return {"items": db.list_snapshots(chapter_id)}
    return await asyncio.to_thread(_sync)


@router.post("/chapters/{chapter_id}/snapshot", response_model=OkResponse)
async def create_snapshot(request: Request, chapter_id: int, body: SnapshotCreate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """为章节创建快照。"""
    def _sync():
        ch = db.get_chapter(chapter_id)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        book_id = int(ch.get("book_id") or 0)
        if book_id:
            check_book_owner(db, book_id, user)
        db.create_snapshot(chapter_id, body.label or "手动快照",
                           ch.get("outline", ""), ch.get("content", ""))
        if book_id:
            try_cloud_sync(request, book_id, user)
        return {"ok": True}
    return await asyncio.to_thread(_sync)


@router.post("/chapters/{chapter_id}/restore", response_model=ChapterItemResponse)
async def restore_snapshot(request: Request, chapter_id: int, body: SnapshotRestore, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """从快照恢复章节。"""
    def _sync():
        ch = db.get_chapter(chapter_id)
        book_id = int(ch.get("book_id") or 0) if ch else None
        if book_id:
            check_book_owner(db, book_id, user)
        result = db.restore_snapshot(chapter_id, body.snapshot_id)
        if not result:
            raise HTTPException(status_code=404, detail="快照不存在")
        ch = db.get_chapter(chapter_id)
        book_id = int(ch.get("book_id") or 0) if ch else None
        if book_id:
            try_cloud_sync(request, book_id, user)
        return {"ok": True, "item": db.get_chapter(chapter_id)}
    return await asyncio.to_thread(_sync)


# ================================================================
#  生成快照管理
# ================================================================

@router.get("/chapters/{chapter_id}/generation-snapshots", response_model=dict[str, Any])
async def list_generation_snapshots(chapter_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """列出章节的所有生成快照。"""
    def _sync():
        ch = db.get_chapter(chapter_id)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        _check_chapter_owner(db, ch, user)
        return {"items": db.list_generation_snapshots(chapter_id)}
    return await asyncio.to_thread(_sync)


@router.post("/chapters/{chapter_id}/generation-snapshots", response_model=dict[str, Any])
async def create_generation_snapshot(request: Request, chapter_id: int, payload: GenerationSnapshotCreate, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """为章节创建生成快照。"""
    def _sync():
        try:
            ch = db.get_chapter(chapter_id)
            if not ch:
                raise HTTPException(status_code=404, detail="章节不存在")
            book_id = int(ch.get("book_id") or 0)
            if book_id:
                check_book_owner(db, book_id, user)
            data = payload.model_dump()
            item = db.create_generation_snapshot(chapter_id, data)
            if book_id:
                try_cloud_sync(request, book_id, user)
            return {"item": item}
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("创建生成快照失败 chapter_id=%s", chapter_id)
            raise HTTPException(status_code=500, detail="创建生成快照失败") from exc
    return await asyncio.to_thread(_sync)


@router.get("/generation-snapshots/{snapshot_id}", response_model=dict[str, Any])
async def get_generation_snapshot(snapshot_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """获取单个生成快照详情。"""
    def _sync():
        item = db.get_generation_snapshot(snapshot_id)
        if item is None:
            raise HTTPException(status_code=404, detail="快照不存在")
        # 鉴权：通过 chapter 的 book_id
        ch = db.get_chapter(int(item.get("chapter_id") or 0))
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        _check_chapter_owner(db, ch, user)
        return {"item": item}
    return await asyncio.to_thread(_sync)


@router.delete("/generation-snapshots/{snapshot_id}", status_code=204)
async def delete_generation_snapshot(request: Request, snapshot_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """删除生成快照。"""
    def _sync():
        try:
            item = db.get_generation_snapshot(snapshot_id)
            if item is None:
                raise HTTPException(status_code=404, detail="快照不存在")
            ch = db.get_chapter(int(item.get("chapter_id") or 0))
            if not ch:
                raise HTTPException(status_code=404, detail="章节不存在")
            book_id = int(ch.get("book_id") or 0)
            if book_id:
                check_book_owner(db, book_id, user)
            db.delete_generation_snapshot(snapshot_id)
            if book_id:
                try_cloud_sync(request, book_id, user)
            return None
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("删除生成快照失败 snapshot_id=%s", snapshot_id)
            raise HTTPException(status_code=500, detail="删除生成快照失败") from exc
    return await asyncio.to_thread(_sync)


@router.post("/generation-snapshots/{snapshot_id}/restore", response_model=dict[str, Any])
async def restore_generation_snapshot(request: Request, snapshot_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """从生成快照恢复章节内容。"""
    def _sync():
        try:
            item = db.get_generation_snapshot(snapshot_id)
            if item is None:
                raise HTTPException(status_code=404, detail="快照不存在")
            ch = db.get_chapter(int(item.get("chapter_id") or 0))
            if not ch:
                raise HTTPException(status_code=404, detail="章节不存在")
            book_id = int(ch.get("book_id") or 0)
            if book_id:
                check_book_owner(db, book_id, user)
            result = db.restore_generation_snapshot(snapshot_id)
            if result is None:
                raise HTTPException(status_code=500, detail="恢复失败")
            if book_id:
                try_cloud_sync(request, book_id, user)
            return {"item": result}
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("恢复生成快照失败 snapshot_id=%s", snapshot_id)
            raise HTTPException(status_code=500, detail="恢复生成快照失败") from exc
    return await asyncio.to_thread(_sync)


# ================================================================
#  分析运行 / 草案卡 / 写回
# ================================================================

@router.get("/books/{book_id}/analysis/runs", response_model=dict[str, Any])  # TODO: 细化为 AnalysisRunListResponse
async def list_analysis_runs(book_id: int, limit: int = Query(default=20, ge=1, le=100), user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """列出作品的全书分析运行记录。"""
    def _sync():
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
        check_book_owner(db, book_id, user)
        store = AnalysisStore(db.db)
        return {
            "items": [
                _analysis_run_item(row)
                for row in store.list_runs(book_id, limit=limit)
                if not str(row["pipeline_version"] or "").startswith("analysis_v3")
            ]
        }
    return await asyncio.to_thread(_sync)


@router.post("/books/{book_id}/analysis-v1/one-shot", response_model=dict[str, Any], deprecated=True)
async def create_analysis_v1_one_shot_run(
    request: Request,
    book_id: int,
    payload: AnalysisV1OneShotRunCreate = AnalysisV1OneShotRunCreate(),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """[已弃用] V1 一次性读完分析 — 请使用 V3 分析 POST /api/workspace/books/{book_id}/analysis-v3/runs。"""
    if not await asyncio.to_thread(db.get_book, book_id):
        raise HTTPException(status_code=404, detail="作品不存在")
    await asyncio.to_thread(check_book_owner, db, book_id, user)

    # 加载章节
    chapters: list[dict[str, Any]] = []
    for row in await asyncio.to_thread(db.list_chapters, book_id):
        chapter = await asyncio.to_thread(db.get_chapter, int(row["id"]))
        if chapter and str(chapter.get("content") or "").strip():
            chapters.append(chapter)
    if not chapters:
        raise HTTPException(status_code=400, detail="作品没有可分析正文")

    # V1 分析字数上限检查：超过 30 万字提示切换 V3 分析
    # V1 一次性读完分析需要将全书文本塞入单次 LLM 请求，超长文本会触发 token 上限或超时
    V1_ANALYSIS_MAX_TOTAL_CHARS = 300_000
    total_content_chars = sum(len(str(ch.get("content") or "")) for ch in chapters)
    if total_content_chars > V1_ANALYSIS_MAX_TOTAL_CHARS:
        raise HTTPException(
            status_code=413,
            detail=(
                f"作品总字数约 {total_content_chars:,} 字，超过 V1 一次性分析上限 "
                f"{V1_ANALYSIS_MAX_TOTAL_CHARS:,} 字。请切换使用 V3 分析功能"
                f"（POST /api/workspace/books/{book_id}/analysis-v3/runs），"
                f"V3 支持分章节流式分析与 AI 增强，适合处理长篇作品。"
            ),
        )

    # 创建 AI 服务
    try:
        from lingshu_api.ws.generation import _create_ai_service

        ai_service = _create_ai_service("book_analysis", workspace_db=db, user_id=int(user["id"]))
        ai_service.require_remote("V1 一次性读完分析")
        # V1 一次性读完分析需要长上下文（全书塞入单次请求），
        # 将 HTTP 超时提升到 3000 秒，避免长文本分析超时失败
        ai_service._request_timeout = 3000
    except Exception as exc:
        logger.exception("V1 一次性读完分析 AI 不可用")
        _record_failed_analysis_run(db.db, book_id, f"AI 服务不可用: {exc}", source="v1_one_shot")
        raise HTTPException(status_code=503, detail="V1 一次性读完分析 AI 不可用，请稍后重试") from exc

    def _sync():
        from novel_app.analysis.chunker import AnalysisChunker
        from novel_app.analysis.pipeline import AnalysisPipeline, PIPELINE_VERSION
        from novel_app.analysis.utils import chapter_dict as _chapter_dict

        # 准备 source_blocks
        chunker = AnalysisChunker(max_chars=20000)
        blocks = chunker.chunk_chapters([_chapter_dict(item) for item in chapters])

        # 获取书籍信息
        book = db.get_book(book_id)
        book_title = str(book.get("title", "") or "") if book else ""
        book_outline = str(book.get("outline_text", "") or "") if book else ""

        # 获取现有人物和世界观（转为 dict 以支持 JSON 序列化）
        characters = [dict(c) for c in (db.db.list_characters(book_id) if hasattr(db.db, "list_characters") else [])]
        world_entries = [dict(w) for w in (db.db.list_world_entries(book_id) if hasattr(db.db, "list_world_entries") else [])]

        # 调用 AI 一次性分析
        analysis_payload = ai_service.analyze_book_one_shot(
            book_title=book_title,
            book_outline=book_outline,
            chapters=chapters,
            source_blocks=blocks,
            characters=characters,
            world_entries=world_entries,
        )

        # 通过 V1 pipeline 创建 draft run
        pipeline = AnalysisPipeline(db.db, chunker=chunker)
        result = pipeline.create_draft_run(
            book_id,
            analysis_payload,
            chapters=chapters,
            source_blocks=blocks,
            meta={"source": "workspace_api_v1_one_shot", "ai_invoked": True},
        )
        return result

    try:
        result = await asyncio.to_thread(_sync)
        store = AnalysisStore(db.db)
        run = await asyncio.to_thread(store.get_run, result.run_id)
        try_cloud_sync(request, book_id, user)
        return {"ok": True, "item": _analysis_run_item(run), **result.as_dict()}
    except HTTPException:
        raise
    except Exception as exc:
        # 区分错误类型返回用户友好的错误码，避免一律 500 暴露内部异常
        exc_msg = str(exc)
        logger.exception("V1 一次性读完分析失败 book_id=%s", book_id)
        # 记录失败 run，便于前端展示失败原因
        _record_failed_analysis_run(db.db, book_id, exc_msg, source="v1_one_shot")
        # AI 认证失败（401 / invalid api key）— 用户配置问题，返回 401 引导检查 AI 配置
        if "401" in exc_msg or "Authentication Fails" in exc_msg or "invalid" in exc_msg.lower() and "api key" in exc_msg.lower():
            raise HTTPException(
                status_code=401,
                detail="AI 接口认证失败，请检查 AI 设置中的 API Key 是否正确。",
            ) from exc
        # AI 限流（429）— 返回 429 引导稍后重试
        if "429" in exc_msg or "rate limit" in exc_msg.lower() or "Rate limit" in exc_msg:
            raise HTTPException(
                status_code=429,
                detail="AI 接口请求被限流，请稍后重试或降低并发数。",
            ) from exc
        # AI 超时 — 返回 504 引导重试或缩短文本
        if "timeout" in exc_msg.lower() or "timed out" in exc_msg.lower():
            raise HTTPException(
                status_code=504,
                detail="AI 接口响应超时，请稍后重试；长篇作品建议使用 V3 分析。",
            ) from exc
        # 其他未知错误 — 500 但不暴露原始异常
        raise HTTPException(status_code=500, detail="V1 一次性读完分析失败，请查看服务器日志") from exc


@router.get("/analysis/runs/{run_id}/cards", response_model=dict[str, Any])  # TODO: 细化为 AnalysisCardListResponse
async def list_analysis_cards(run_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """列出某次分析生成的草案卡。"""
    def _sync():
        store = AnalysisStore(db.db)
        run = store.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="分析运行不存在")
        check_book_owner(db, int(run["book_id"]), user)
        return {"run": _analysis_run_item(run), "items": [_analysis_card_item(row) for row in store.list_cards(run_id)]}
    return await asyncio.to_thread(_sync)


@router.post("/analysis/cards/{card_id}/reject", response_model=dict[str, Any])  # TODO: 细化 response_model
async def reject_analysis_card(card_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    """拒绝一张分析草案卡。"""
    def _sync():
        store = AnalysisStore(db.db)
        card = store.get_card(card_id)
        if not card:
            raise HTTPException(status_code=404, detail="分析卡不存在")
        check_book_owner(db, int(card["book_id"]), user)
        store.reject_card(card_id)
        return {"ok": True, "item": _analysis_card_item(store.get_card(card_id))}
    return await asyncio.to_thread(_sync)


@router.post("/analysis/runs/{run_id}/apply", response_model=dict[str, Any], deprecated=True)  # TODO: 细化 response_model
async def apply_analysis_run(
    request: Request,
    run_id: int,
    body: ApplyAnalysisPayload = Body(default=ApplyAnalysisPayload(), embed=False),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """[已弃用] 将分析运行中的 full_payload 草案写回正式层 — 请使用 V3 写回 POST /api/workspace/analysis-v3/runs/{run_id}/writeback。"""
    def _sync():
        store = AnalysisStore(db.db)
        run = store.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="分析运行不存在")
        book_id = int(run["book_id"])
        check_book_owner(db, book_id, user)
        cards = store.list_cards(run_id)
        if not any(str(card["card_type"] or "") == "full_payload" for card in cards):
            raise HTTPException(status_code=404, detail="未找到可写回的完整分析草案")
        result = apply_analysis_cards(
            db.db,
            int(run["book_id"]),
            run_id,
            [int(card["id"]) for card in cards],
            allow_weak_evidence=body.weak_evidence_allowed,
        )
        if result.applied_cards <= 0:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "分析草案证据不足或没有可写回内容",
                    "requires_user_override": True,
                },
            )
        artifact_meta = _sync_analysis_writeback_artifacts(db, int(run["book_id"]), sorted(result.updated_chapter_ids))
        store.update_run_status(run_id, "applied", meta={"writeback_artifacts": artifact_meta})
        try_cloud_sync(request, int(run["book_id"]), user)
        return {
            "ok": True,
            "updated_chapter_ids": sorted(result.updated_chapter_ids),
            "processed_chapters": result.processed_chapters,
            "unresolved_count": result.unresolved_count,
            "evidence_gate_dropped": result.evidence_gate_dropped,
            "snapshot_id": result.snapshot_id,
            "applied_cards": result.applied_cards,
            "skipped_cards": result.skipped_cards,
            "audit_log_ids": result.audit_log_ids,
            "weak_evidence_override": result.weak_evidence_override,
            "writeback_artifacts": artifact_meta,
        }
    return await asyncio.to_thread(_sync)


def _record_failed_analysis_run(
    db_obj, book_id: int, error_text: str, *,
    source: str = "v1_one_shot", pipeline_version: str = "draft_mvp_v1",
) -> None:
    """记录失败的分析 run，便于前端展示失败原因。

    在 V1/V3 分析异常时调用，创建一条 status=failed 的 run 记录，
    将 error_text 写入数据库，让用户在"分析结构"面板看到失败记录和原因。
    """
    try:
        from novel_app.analysis.store import AnalysisStore
        store = AnalysisStore(db_obj)
        run_id = store.create_run(
            int(book_id),
            scope_type="book",
            status="created",
            pipeline_version=pipeline_version,
            meta={"source": source, "failed": True},
            summary="分析失败",
        )
        # 截断 error_text 避免 TEXT 字段过长（保留前 2000 字符）
        store.update_run_status(
            run_id, "failed",
            error_text=str(error_text)[:2000],
            summary="分析失败",
        )
    except Exception:
        logger.exception("Failed to record failed analysis run book_id=%s", book_id)


def _classify_error_text(error_text: str) -> str:
    """将原始异常文本分类为用户友好的失败原因提示。

    不泄露内部堆栈，仅返回可操作的失败类别，便于用户排查（如检查 API Key、稍后重试等）。
    """
    raw = str(error_text or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    if "401" in raw or "authentication fails" in low or ("invalid" in low and "api key" in low):
        return "AI 接口认证失败，请检查 AI 设置中的 API Key 是否正确"
    if "429" in raw or "rate limit" in low:
        return "AI 接口被限流，请稍后重试"
    if "timeout" in low or "timed out" in low:
        return "AI 接口响应超时，请稍后重试；长篇作品建议使用 V3 分析"
    if "没有配置可用 ai" in low or "require_remote" in low or "未配置" in raw or "没有可用" in raw:
        return "未配置 AI 接口，请先在设置中配置 API Key 后再使用 AI 增强分析"
    if "没有可分析正文" in raw:
        return "作品没有可分析正文"
    if "concurrency" in low or "并发" in raw:
        return "并发任务数已达上限，请等待当前任务完成后再试"
    # 未匹配已知异常模式时，原样返回（可能是 pipeline 已写入的友好中文提示）
    return raw


def _analysis_run_item(row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "book_id": int(row["book_id"]),
        "scope_type": row["scope_type"],
        "status": row["status"],
        "pipeline_version": row["pipeline_version"],
        "summary": row["summary"],
        "error_text": _classify_error_text(str(row["error_text"] or "")),
        "card_count": int(row["card_count"] or 0),
        "draft_count": int(row["draft_count"] or 0),
        "applied_count": int(row["applied_count"] or 0),
        "blocked_count": int(row["blocked_count"] or 0),
        "meta": extract_json_dict(row["meta_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


def _analysis_card_item(row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "book_id": int(row["book_id"]),
        "run_id": int(row["run_id"]),
        "card_uid": row["card_uid"],
        "card_type": row["card_type"],
        "entity_uid": row["entity_uid"],
        "ars_score": float(row["ars_score"] or 0),
        "status": row["status"],
        "payload": extract_json_dict(row["payload_json"]),
        "diff": extract_json_dict(row["diff_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "applied_at": row["applied_at"],
    }



def _sync_analysis_writeback_artifacts(db: WorkspaceDB, book_id: int, updated_chapter_ids: list[int]) -> dict[str, Any]:
    from novel_app.rag.retriever import ChapterRetriever
    from novel_app.truth import TruthManager

    database = db.db
    book = database.get_book(book_id)
    title = str(book["title"] or "") if book else ""
    meta: dict[str, Any] = {
        "truth_files": [],
        "rag_indexed": [],
        "artifact_errors": [],
    }

    truth_files: dict[str, str] = {}
    try:
        truth_files = TruthManager(database.data_dir, database).build_all(book_id)
        meta["truth_files"] = sorted(truth_files.keys())
    except Exception:
        logger.exception("truth 文件构建失败")
        meta["artifact_errors"].append("truth: 构建失败")

    try:
        retriever = ChapterRetriever(storage_dir=str(database.data_dir / "rag_index"))
        design_markdown = _book_design_markdown(database, book_id)
        if design_markdown:
            retriever.index_book_design(book_id, title, design_markdown)
            meta["rag_indexed"].append("book_design")
        if truth_files:
            retriever.index_truth_snapshot(book_id, title, truth_files)
            meta["rag_indexed"].append("truth_snapshot")
        for chapter_id in updated_chapter_ids:
            chapter = database.get_chapter(int(chapter_id))
            if not chapter:
                continue
            retriever.index_chapter(
                book_id=book_id,
                chapter_id=int(chapter_id),
                title=str(chapter["title"] or ""),
                summary=str(chapter["summary_text"] or ""),
                outline=str(chapter["outline"] or ""),
                content_snippet=str(chapter["content"] or "")[:2000],
                metadata={"source": "analysis_writeback"},
            )
            meta["rag_indexed"].append(f"chapter:{int(chapter_id)}")
    except Exception:
        logger.exception("RAG 索引构建失败")
        meta["artifact_errors"].append("rag: 索引构建失败")
    return meta


def _book_design_markdown(database: Any, book_id: int) -> str:
    book = database.get_book(book_id)
    if not book:
        return ""
    title = str(book["title"] or "")
    parts = [f"# {title}" if title else "# 书籍设定"]
    outline = str(book["outline_text"] or "").strip()
    if outline:
        parts.extend(["", "## 书籍大纲", outline])
    world = str(book["world_text"] or "").strip()
    if world:
        parts.extend(["", "## 世界观", world])
    characters = database.list_characters(book_id)
    if characters:
        lines = []
        for row in characters[:40]:
            item = dict(row)
            name = str(item.get("name") or "").strip()
            role = str(item.get("role") or "").strip()
            profile = str(item.get("profile_text") or "").strip()
            if not name:
                continue
            line = f"- {name}"
            if role:
                line += f"（{role}）"
            if profile:
                line += f"：{profile[:240]}"
            lines.append(line)
        if lines:
            parts.extend(["", "## 人物", "\n".join(lines)])
    return "\n".join(parts).strip()


# ================================================================
#  文件导入 (TXT / MD / DOCX)
# ================================================================

@router.post("/books/{book_id}/import-file", response_model=dict[str, Any])  # TODO: 细化为 ImportFileResponse
async def import_file_to_book(
    request: Request,
    book_id: int,
    file: UploadFile = File(...),
    skip_volumes: bool = Query(default=False),
    user: dict = Depends(require_ai_access),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """导入文件到现有作品（新增为卷/章）。"""
    def _check():
        check_book_owner(db, book_id, user)
        book = db.get_book(book_id)
        if not book:
            raise HTTPException(status_code=404, detail="作品不存在")
    await asyncio.to_thread(_check)
    return await _handle_file_import(
        request,
        file,
        db,
        target_book_id=book_id,
        skip_volumes=skip_volumes,
        user_id=int(user["id"]),
        user=user,
    )


@router.post("/import-file", response_model=dict[str, Any])  # TODO: 细化为 ImportFileResponse
async def import_file_as_new_book(
    request: Request,
    title: str = Query(default="", description="新作品标题（可选，默认使用文件名）"),
    file: UploadFile = File(...),
    skip_volumes: bool = Query(default=False),
    user: dict = Depends(require_ai_access),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """导入文件创建为新作品。"""
    return await _handle_file_import(
        request,
        file,
        db,
        target_book_id=None,
        default_title=title,
        skip_volumes=skip_volumes,
        user_id=int(user["id"]),
        user=user,
    )


async def _handle_file_import(
    request: Request,
    file: UploadFile,
    db: WorkspaceDB,
    target_book_id: int | None = None,
    default_title: str = "",
    skip_volumes: bool = False,
    user_id: int | None = None,
    user: dict | None = None,
) -> dict[str, Any]:
    """处理文件导入的通用逻辑。"""
    raw_bytes = await file.read()

    if len(raw_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件超过 50MB，请先拆分后再导入")

    suffix = Path(file.filename or "import.txt").suffix.lower()

    # 文件扩展名白名单校验
    _ALLOWED_IMPORT_EXTENSIONS = {".txt", ".md", ".docx", ".epub"}
    if suffix not in _ALLOWED_IMPORT_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {suffix}，仅允许 {', '.join(sorted(_ALLOWED_IMPORT_EXTENSIONS))}")

    # 解码文本
    try:
        if suffix == ".docx":
            import io

            from docx import Document
            doc = Document(io.BytesIO(raw_bytes))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        else:
            text = _decode_text(raw_bytes)
    except Exception as exc:
        logger.exception("无法读取文件")
        raise HTTPException(status_code=400, detail="无法读取文件") from exc

    if not text.strip():
        raise HTTPException(status_code=400, detail="文件内容为空")

    # 书名
    title = default_title or Path(file.filename or "导入作品").stem.strip()
    if not title:
        title = "导入作品"

    # 拆分章节：统一使用 AI 辅助分段检测
    try:
        parsed = await _parse_large_text_with_ai_splits(title, text, db, skip_volumes=skip_volumes, user_id=int(user["id"]))
    except Exception as exc:
        logger.exception("文本拆分失败")
        raise HTTPException(status_code=400, detail="文本拆分失败，请检查文件格式") from exc

    if not parsed.chapters:
        raise HTTPException(status_code=400, detail="没有识别到可导入的章节")

    # 如果用户关闭分卷 或 第一个章节没有分卷标记，则强制清空所有 volume_title 归入未分卷
    if skip_volumes or not parsed.chapters[0].volume_title:
        parsed = dataclasses.replace(
            parsed,
            chapters=[dataclasses.replace(c, volume_title=None) for c in parsed.chapters],
        )

    # 导入
    try:
        if target_book_id:
            result = await asyncio.to_thread(_append_parsed_to_book, db, target_book_id, parsed)
        else:
            result = await asyncio.to_thread(_create_book_from_parsed, db, parsed, user_id)
    except Exception as exc:
        logger.exception("写入失败")
        raise HTTPException(status_code=500, detail="写入失败，请稍后重试") from exc

    book_id = int(result["book_id"])

    def _after_import():
        try_cloud_sync(request, book_id, user)
        return db.get_book(book_id)

    item = await asyncio.to_thread(_after_import)
    volume_count = len({c.volume_title for c in parsed.chapters if c.volume_title})
    return {
        "ok": True,
        **result,
        "item": item,
        "stats": {
            "volume_count": volume_count,
            "chapter_count": len(parsed.chapters),
            "total_chars": sum(len(c.content.strip()) for c in parsed.chapters),
        },
    }


async def _parse_large_text_with_ai_splits(
    title: str,
    text: str,
    db: WorkspaceDB,
    skip_volumes: bool = False,
    *,
    user_id: int | None = None,
) -> ParsedBook:
    """对文本使用 AI 检测章卷结构后解析。AI 不可用时回退到正则匹配。"""
    # 关闭分卷时跳过 AI 检测，直接分段解析
    if skip_volumes:
        return await asyncio.to_thread(_fallback_chunk_parse, title, text)

    # 使用 AI 检测全文章卷结构（ChapterStructureAgent 内部按约10万字分段检测）
    try:
        def _detect_structure():
            from lingshu_api.services.ai_settings import resolve_ai_profile
            profile = resolve_ai_profile(db.db.data_dir, "import", user_id=user_id)
            ai_service = SimpleAIService(
                api_key=profile.get("api_key") or None,
                base_url=profile.get("base_url") or None,
                model=profile.get("model") or None,
            )
            ai_service.require_remote("智能导入分段")
            return ai_service.detect_chapter_structure(text)

        structure = await asyncio.to_thread(_detect_structure)
    except Exception:
        structure = None

    if structure:
        # 用 AI 检测的结构一次性解析，保证卷归属和章节顺序正确
        return await asyncio.to_thread(parse_long_text, title, text, structure)

    # AI 不可用时回退到分段解析
    return await asyncio.to_thread(_fallback_chunk_parse, title, text)


def _fallback_chunk_parse(title: str, text: str) -> ParsedBook:
    """分段解析（AI 不可用或关闭分卷时的回退方案）。"""
    text_len = len(text)
    boundaries = list(range(500_000, text_len, 500_000))
    if not boundaries:
        return parse_long_text(title, text)

    segments: list[str] = []
    prev_end = 0
    for boundary in boundaries:
        segments.append(text[prev_end:boundary])
        prev_end = boundary
    segments.append(text[prev_end:])

    from novel_app.text_importer import _extract_book_outline

    all_chapters: list[ParsedChapter] = []
    for segment_text in segments:
        parsed = parse_long_text(title, segment_text)
        all_chapters.extend(parsed.chapters)

    return ParsedBook(
        title=title,
        outline=_extract_book_outline(title, all_chapters),
        chapters=all_chapters,
    )


def _decode_text(data: bytes) -> str:
    """智能解码文本文件（UTF-8 / UTF-16 / GBK）。"""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    if data.count(b"\x00") > max(8, len(data) // 100):
        raise ValueError("文件看起来不是纯文本")
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    raise ValueError("无法识别文本编码")


def _create_book_from_parsed(db: WorkspaceDB, parsed, user_id: int | None = None) -> dict:
    """从 ParsedBook 创建新书。"""
    book_id = db.db.create_book(parsed.title, user_id=user_id)

    # 保存自动生成的书籍大纲
    if parsed.outline:
        db.db.update_book_outline(book_id, parsed.outline)

    # 如果第一个章节就没有分卷，全部归入未分卷（无需检查后续）
    has_unassigned = not parsed.chapters[0].volume_title if parsed.chapters else True
    if has_unassigned:
        first_chapter_id = None
        for chapter in parsed.chapters:
            cid = db.db.create_chapter(book_id, chapter.title, None)
            db.db.update_chapter(cid, outline=chapter.outline, content=chapter.content, summary_text="", chapter_type=chapter.chapter_type)
            if first_chapter_id is None:
                first_chapter_id = cid
        return {"book_id": book_id, "first_chapter_id": first_chapter_id}

    volume_ids: dict[str, int] = {}
    first_chapter_id = None

    for chapter in parsed.chapters:
        vid = None
        if chapter.volume_title:
            vid = volume_ids.get(chapter.volume_title)
            if vid is None:
                vid = db.db.create_volume(book_id, chapter.volume_title)
                volume_ids[chapter.volume_title] = vid

        cid = db.db.create_chapter(book_id, chapter.title, vid)
        db.db.update_chapter(cid, outline=chapter.outline, content=chapter.content, summary_text="", chapter_type=chapter.chapter_type)
        if first_chapter_id is None:
            first_chapter_id = cid

    return {"book_id": book_id, "first_chapter_id": first_chapter_id}


def _append_parsed_to_book(db: WorkspaceDB, book_id: int, parsed) -> dict:
    """追加导入内容到已有书籍。"""
    # 追加导入的章节大纲
    if parsed.outline:
        db.db.update_book_outline(book_id, parsed.outline)

    # 如果第一个章节就没有分卷，全部归入未分卷（无需检查后续）
    has_unassigned = not parsed.chapters[0].volume_title if parsed.chapters else True
    if has_unassigned:
        first_chapter_id = None
        for chapter in parsed.chapters:
            cid = db.db.create_chapter(book_id, chapter.title, None)
            db.db.update_chapter(cid, outline=chapter.outline, content=chapter.content, summary_text="", chapter_type=chapter.chapter_type)
            if first_chapter_id is None:
                first_chapter_id = cid
        return {"book_id": book_id, "first_chapter_id": first_chapter_id}

    existing_volumes = {str(v["title"]): int(v["id"]) for v in db.db.list_volumes(book_id)}
    first_chapter_id = None

    for chapter in parsed.chapters:
        vid = None
        if chapter.volume_title:
            vid = existing_volumes.get(chapter.volume_title)
            if vid is None:
                vid = db.db.create_volume(book_id, chapter.volume_title)
                existing_volumes[chapter.volume_title] = vid

        cid = db.db.create_chapter(book_id, chapter.title, vid)
        db.db.update_chapter(cid, outline=chapter.outline, content=chapter.content, summary_text="", chapter_type=chapter.chapter_type)
        if first_chapter_id is None:
            first_chapter_id = cid

    return {"book_id": book_id, "first_chapter_id": first_chapter_id}
