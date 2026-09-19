"""
工作台写作探针伴随机制 API（原 lingshu_api/routers/workspace.py 拆分而来）。
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from lingshu_api.dependencies import check_book_owner, require_ai_access, require_login
from lingshu_api.services.ai_settings import load_ai_settings
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db

router = APIRouter(tags=["workspace"])


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
