"""analysis_v3 卡片操作路由 — 查询/写回/批量写回。"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from slowapi import Limiter
from slowapi.util import get_remote_address

from lingshu_api.dependencies import require_login
from lingshu_api.routers.analysis_v3_runs import (
    _analysis_v3_run_item,
    _check_run_book_owner,
    _create_required_analysis_ai_provider,
    _get_analysis_v3_run_or_404,
    _classify_error_text,
    _utc_to_beijing,
)
from lingshu_api.routers.analysis_v3_steps import _row_value, get_analysis_v3_review_summary
from lingshu_api.schemas.analysis_v3 import CardApplyRequest, WritebackRunRequest
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db
from novel_app.analysis.store import AnalysisStore
from novel_app.json_utils import extract_json_array, extract_json_object

router = APIRouter(prefix="/api/workspace", tags=["analysis-v3-cards"])
_cloud_logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)


def _create_writeback_card_generator(db: WorkspaceDB, *, user_id: int | None = None):
    """尝试创建写回卡片生成器，AI 不可用时返回 None 允许降级。"""
    try:
        from novel_app.analysis.writeback_card_generator import WritebackCardGenerator
        return WritebackCardGenerator(_create_required_analysis_ai_provider(db, purpose="V3 写回卡片生成", user_id=user_id))
    except Exception as exc:
        _cloud_logger.warning("写回卡片生成器不可用，将跳过 LLM 精炼: %s", exc)
        return None


def _analysis_v3_dependency_item(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "card_uid": str(row["card_uid"] or ""),
        "dependency_type": str(row["dependency_type"] or ""),
        "dependency_uid": str(row["dependency_uid"] or ""),
        "dependency_hash": str(row["dependency_hash"] or ""),
        "created_at": _utc_to_beijing(row["created_at"]),
    }


def _analysis_v3_card_item(store: AnalysisStore, book_id: int, row: Any) -> dict[str, Any]:
    card_uid = str(row["card_uid"] or "")
    dependencies = store.list_card_dependencies(book_id, run_id=int(row["run_id"]), card_uid=card_uid)
    return {
        "id": int(row["id"]),
        "book_id": int(row["book_id"]),
        "run_id": int(row["run_id"]),
        "card_uid": card_uid,
        "card_type": str(row["card_type"] or ""),
        "entity_uid": str(row["entity_uid"] or ""),
        "ars_score": float(row["ars_score"] or 0.0),
        "status": str(row["status"] or ""),
        "payload": extract_json_object(str(row["payload_json"] or "{}")),
        "diff": extract_json_object(str(row["diff_json"] or "{}")),
        "dependencies": [
            _analysis_v3_dependency_item(dependency)
            for dependency in dependencies
        ],
        "created_at": _utc_to_beijing(row["created_at"]),
        "updated_at": _utc_to_beijing(row["updated_at"]),
        "applied_at": _utc_to_beijing(row["applied_at"]),
    }


# ------------------------------------------------------------------
# 卡片依赖查询
# ------------------------------------------------------------------

@router.get("/analysis-v3/runs/{run_id}/cards/{card_uid}/dependencies")
async def list_analysis_v3_card_dependencies(
    run_id: int,
    card_uid: str,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    store = AnalysisStore(db.db)
    book_id = int(run["book_id"])
    dependencies = await asyncio.to_thread(store.list_card_dependencies, book_id, run_id=run_id, card_uid=card_uid)
    return {
        "run": _analysis_v3_run_item(run),
        "items": [_analysis_v3_dependency_item(row) for row in dependencies],
    }


# ------------------------------------------------------------------
# 卡片列表
# ------------------------------------------------------------------

@router.get("/analysis-v3/runs/{run_id}/cards")
async def list_analysis_v3_cards(
    run_id: int,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    store = AnalysisStore(db.db)
    cards_raw = await asyncio.to_thread(store.list_cards, run_id)
    cards = [
        row
        for row in cards_raw
        if str(row["card_type"] or "").startswith("v3_")
    ]
    return {
        "run": _analysis_v3_run_item(run),
        "items": [await asyncio.to_thread(_analysis_v3_card_item, store, int(run["book_id"]), row) for row in cards],
    }


# ------------------------------------------------------------------
# 单卡写回（apply — Phase 11 门禁占位）
# ------------------------------------------------------------------

@router.post("/analysis-v3/runs/{run_id}/cards/{card_uid}/apply")
async def apply_analysis_v3_card(
    run_id: int,
    card_uid: str,
    payload: CardApplyRequest | None = None,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """正式写回门禁 — Phase 11。

    将候选卡片的变更写入正式层。当前为门禁占位，始终拒绝。
    """
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    store = AnalysisStore(db.db)
    book_id = int(run["book_id"])
    cards_raw = await asyncio.to_thread(store.list_cards, run_id)
    cards = [row for row in cards_raw if str(row["card_uid"] or "") == card_uid]
    if not cards:
        raise HTTPException(status_code=404, detail="卡片不存在")
    card = cards[0]
    card_status = str(card["status"] or "")
    if card_status == "applied":
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "卡片已写回，不可重复操作"})
    if card_status == "superseded":
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "已被取代的卡片不能写回"})
    allow_soft_blockers = bool(getattr(payload, "allow_soft_blockers", False))
    review = await get_analysis_v3_review_summary(run_id, user=user, db=db, for_single_card=allow_soft_blockers)
    review_item = review.get("item", {})
    if not review_item.get("formal_writeback_allowed"):
        blockers = review_item.get("blockers", [])
        raise HTTPException(
            status_code=409,
            detail={"code": "CONFLICT", "message": f"写回门禁未通过: {', '.join(blockers) if blockers else '运行状态未就绪'}"},
        )
    actor = payload.actor if payload is not None else "user"
    run_meta = {}
    try:
        run_meta = json.loads(str(run["meta_json"] or "{}"))
    except Exception:
        pass
    ai_invoked = bool(run_meta.get("ai_invoked") or run_meta.get("ai_stages"))
    use_writeback_generator = bool(ai_invoked) and not allow_soft_blockers
    writeback_generator = _create_writeback_card_generator(db, user_id=int(user["id"])) if use_writeback_generator else None
    require_wb_gen = use_writeback_generator
    result = await asyncio.to_thread(
        store.apply_card,
        book_id,
        run_id,
        card_uid,
        actor=actor,
        writeback_generator=writeback_generator,
        require_writeback_generator=require_wb_gen,
    )
    if not result or str(_row_value(result, "status") or "") != "applied":
        raise HTTPException(status_code=500, detail="写回执行失败")
    refreshed = await asyncio.to_thread(store.get_run, run_id)
    applied_payload = extract_json_object(str(_row_value(result, "payload_json") or "{}"))
    return {
        "ok": True,
        "run": _analysis_v3_run_item(refreshed),
        "card_uid": card_uid,
        "applied_table": _row_value(result, "applied_table"),
        "applied_id": _row_value(result, "applied_id"),
        "writeback_generation_used": bool((applied_payload.get("writeback_generation") or {}).get("used")),
    }


# ------------------------------------------------------------------
# 单卡写回（writeback）
# ------------------------------------------------------------------

@limiter.limit("10/minute")
@router.post("/analysis-v3/runs/{run_id}/cards/{card_uid}/writeback")
async def writeback_analysis_v3_card(
    request: Request,
    run_id: int,
    card_uid: str,
    payload: CardApplyRequest | None = None,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """将单张 V3 分析卡片写回到业务表。"""
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    book_id = int(run["book_id"])

    allow_soft_blockers = bool(getattr(payload, "allow_soft_blockers", False))
    review = await get_analysis_v3_review_summary(run_id, user=user, db=db, for_single_card=True)
    if not review.get("item", {}).get("formal_writeback_allowed"):
        blockers = review.get("item", {}).get("blockers", [])
        raise HTTPException(
            status_code=409,
            detail={"code": "CONFLICT", "message": f"写回门禁未通过: {', '.join(blockers) if blockers else '未知原因'}"},
        )

    store = AnalysisStore(db.db)
    cards_raw = await asyncio.to_thread(store.list_cards, run_id)
    cards = [row for row in cards_raw if str(_row_value(row, "card_uid") or "") == card_uid]
    if not cards:
        raise HTTPException(status_code=404, detail="卡片不存在")

    card = cards[0]
    card_status = str(_row_value(card, "status") or "")
    if card_status == "applied":
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "卡片已写回，不可重复操作"})
    if card_status == "superseded":
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "已被取代的卡片不能写回"})

    actor = payload.actor if payload is not None else "user"
    run_meta = {}
    try:
        run_meta = json.loads(str(run["meta_json"] or "{}"))
    except Exception:
        pass
    ai_invoked = bool(run_meta.get("ai_invoked") or run_meta.get("ai_stages"))
    use_writeback_generator = bool(ai_invoked) and not allow_soft_blockers
    writeback_generator = _create_writeback_card_generator(db, user_id=int(user["id"])) if use_writeback_generator else None
    require_wb_gen = use_writeback_generator
    result = await asyncio.to_thread(
        store.apply_card,
        book_id,
        run_id,
        card_uid,
        actor=actor,
        writeback_generator=writeback_generator,
        require_writeback_generator=require_wb_gen,
    )
    if not result or str(_row_value(result, "status") or "") != "applied":
        raise HTTPException(status_code=500, detail="写回执行失败")

    refreshed = await asyncio.to_thread(store.get_run, run_id)
    applied_payload = extract_json_object(str(_row_value(result, "payload_json") or "{}"))
    applied_table = _row_value(result, "applied_table")
    applied_id = _row_value(result, "applied_id")

    try:
        from novel_app.core.event_bus import get_event_bus
        get_event_bus().publish(
            "writeback_completed",
            book_id=book_id,
            run_id=run_id,
            card_uid=card_uid,
            applied_table=applied_table,
            applied_id=applied_id,
            actor=actor,
        )
    except Exception:
        _cloud_logger.warning("发布 writeback_completed 事件失败", exc_info=True)

    try:
        from lingshu_api.ws.connection import get_ws_manager
        manager = get_ws_manager()
        await manager.broadcast({
            "type": "analysis_v3.writeback_completed",
            "payload": {
                "book_id": book_id,
                "run_id": run_id,
                "card_uid": card_uid,
                "applied_table": applied_table,
                "applied_id": applied_id,
            },
        })
    except Exception:
        _cloud_logger.warning("广播 writeback_completed WebSocket 消息失败", exc_info=True)

    return {
        "ok": True,
        "run": _analysis_v3_run_item(refreshed),
        "card_uid": card_uid,
        "applied_table": applied_table,
        "applied_id": applied_id,
        "writeback_generation_used": bool((applied_payload.get("writeback_generation") or {}).get("used")),
    }


# ------------------------------------------------------------------
# 批量写回
# ------------------------------------------------------------------

@limiter.limit("3/minute")
@router.post("/analysis-v3/runs/{run_id}/writeback")
async def writeback_analysis_v3_run(
    request: Request,
    run_id: int,
    payload: WritebackRunRequest | None = None,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """批量写回 V3 分析运行中所有通过门禁的卡片。"""
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    book_id = int(run["book_id"])

    allow_soft_blockers = bool(getattr(payload, "allow_soft_blockers", False))
    review = await get_analysis_v3_review_summary(run_id, user=user, db=db, for_single_card=allow_soft_blockers)
    if not review.get("item", {}).get("formal_writeback_allowed"):
        blockers = review.get("item", {}).get("blockers", [])
        raise HTTPException(
            status_code=409,
            detail={"code": "CONFLICT", "message": f"写回门禁未通过: {', '.join(blockers) if blockers else '未知原因'}"},
        )

    store = AnalysisStore(db.db)
    cards = await asyncio.to_thread(store.list_cards, run_id)

    writebackable = []
    for card in cards:
        card_status = str(_row_value(card, "status") or "")
        payload_json = extract_json_object(str(_row_value(card, "payload_json") or "{}"))
        if card_status in ("draft", "reviewed") and payload_json.get("writeback_target") and isinstance(payload_json.get("writeback_fields"), dict):
            writebackable.append(card)

    if not writebackable:
        return {"ok": True, "writeback_count": 0, "message": "无可写回的卡片"}

    run_meta = {}
    try:
        run_meta = json.loads(str(run["meta_json"] or "{}"))
    except Exception:
        pass
    ai_invoked = bool(run_meta.get("ai_invoked") or run_meta.get("ai_stages"))
    use_writeback_generator = bool(ai_invoked) and not allow_soft_blockers
    writeback_generator = _create_writeback_card_generator(db, user_id=int(user["id"])) if use_writeback_generator else None
    require_wb_gen = use_writeback_generator
    results = []
    for card in writebackable:
        card_uid = str(_row_value(card, "card_uid") or "")
        actor = payload.actor if payload is not None else "user"
        try:
            result = await asyncio.to_thread(
                store.apply_card,
                book_id,
                run_id,
                card_uid,
                actor=actor,
                writeback_generator=writeback_generator,
                require_writeback_generator=require_wb_gen,
            )
            success = result is not None and str(_row_value(result, "status") or "") == "applied"
            applied_payload = extract_json_object(str(_row_value(result, "payload_json") or "{}")) if result is not None else {}
            result_entry = {
                "card_uid": card_uid,
                "success": success,
                "applied_table": _row_value(result, "applied_table") if result is not None else None,
                "applied_id": _row_value(result, "applied_id") if result is not None else None,
                "writeback_generation_used": bool((applied_payload.get("writeback_generation") or {}).get("used")),
            }
            if not success:
                result_entry["error"] = "写回执行失败：卡片状态未变为 applied"
        except Exception as exc:
            _cloud_logger.warning("批量写回卡片 %s 异常: %s", card_uid, exc)
            result_entry = {
                "card_uid": card_uid,
                "success": False,
                "applied_table": None,
                "applied_id": None,
                "writeback_generation_used": False,
                "error": str(exc),
            }
        results.append(result_entry)

    refreshed = await asyncio.to_thread(store.get_run, run_id)
    success_count = sum(1 for r in results if r["success"])
    failure_count = len(results) - success_count

    if success_count > 0:
        try:
            from novel_app.core.event_bus import get_event_bus
            get_event_bus().publish(
                "writeback_completed",
                book_id=book_id,
                run_id=run_id,
                batch=True,
                success_count=success_count,
                actor=payload.actor if payload is not None else "user",
            )
        except Exception:
            _cloud_logger.warning("发布 writeback_completed 批量事件失败", exc_info=True)

        try:
            from lingshu_api.ws.connection import get_ws_manager
            manager = get_ws_manager()
            await manager.broadcast({
                "type": "analysis_v3.writeback_completed",
                "payload": {
                    "book_id": book_id,
                    "run_id": run_id,
                    "batch": True,
                    "success_count": success_count,
                },
            })
        except Exception:
            _cloud_logger.warning("批量写回 WebSocket 广播失败", exc_info=True)

    from fastapi.responses import JSONResponse

    response_body = {
        "ok": True,
        "run": _analysis_v3_run_item(refreshed),
        "writeback_count": len(results),
        "success_count": success_count,
        "failure_count": failure_count,
        "results": results,
    }

    if failure_count > 0 and success_count > 0:
        return JSONResponse(status_code=207, content=response_body)
    if failure_count > 0 and success_count == 0:
        response_body["ok"] = False
        return JSONResponse(status_code=500, content=response_body)

    return response_body
