"""analysis_v3 分析步骤执行路由 — 实体提及/共指/原子事实/卡片事件/记忆层/探针/回溯。"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from slowapi import Limiter
from slowapi.util import get_remote_address

from lingshu_api.dependencies import check_book_owner, require_login
from lingshu_api.routers.analysis_v3_runs import (
    _analysis_v3_run_item,
    _check_run_book_owner,
    _create_required_analysis_ai_provider,
    _get_analysis_v3_run_or_404,
    _is_analysis_v3_run,
    _classify_error_text,
    _utc_to_beijing,
)
from lingshu_api.schemas.analysis_v3 import (
    ActiveProbeRequest,
    BacktrackTaskCreate,
    EntityMergeRequest,
    EntityRollbackRequest,
    EntitySplitRequest,
    EntityUpdateRequest,
    StepUseAiRequest,
)
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db
from novel_app.analysis.card_coordinator import CardCoordinator
from novel_app.analysis.entity_store import EntityStore
from novel_app.analysis.fact_store import FactStore
from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3
from novel_app.analysis.store import AnalysisStore
from novel_app.json_utils import extract_json_array, extract_json_object

router = APIRouter(prefix="/api/workspace", tags=["analysis-v3-steps"])
_cloud_logger = logging.getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _count_rows_by(rows: list[Any], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(_row_value(row, key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


def _analysis_v3_event_item(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "book_id": int(row["book_id"]),
        "run_id": int(row["run_id"]),
        "event_uid": str(row["event_uid"] or ""),
        "event_type": str(row["event_type"] or ""),
        "payload": extract_json_object(str(row["payload_json"] or "{}")),
        "status": str(row["status"] or ""),
        "priority": int(row["priority"] or 0),
        "attempts": int(row["attempts"] or 0),
        "error_text": _classify_error_text(str(row["error_text"] or "")),
        "created_at": _utc_to_beijing(row["created_at"]),
        "updated_at": _utc_to_beijing(row["updated_at"]),
    }


def _analysis_v3_backtrack_task_item(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "book_id": int(row["book_id"]),
        "run_id": int(row["run_id"]),
        "task_uid": str(row["task_uid"] or ""),
        "trigger_type": str(row["trigger_type"] or ""),
        "target_uid": str(row["target_uid"] or ""),
        "impact": extract_json_object(str(row["impact_json"] or "{}")),
        "status": str(row["status"] or ""),
        "priority": int(row["priority"] or 0),
        "error_text": _classify_error_text(str(row["error_text"] or "")),
        "created_at": _utc_to_beijing(row["created_at"]),
        "updated_at": _utc_to_beijing(row["updated_at"]),
    }


_WRITEBACK_READY_STATUSES = {"probes_ready", "backtrack_ready", "completed"}


# ------------------------------------------------------------------
# 实体提及步骤
# ------------------------------------------------------------------

@limiter.limit("5/minute")
@router.post("/analysis-v3/runs/{run_id}/steps/entity_mentions")
async def run_analysis_v3_entity_mentions(
    run_id: int,
    request: Request,
    payload: StepUseAiRequest | None = None,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    store = AnalysisStore(db.db)
    blocks = await asyncio.to_thread(store.list_blocks, int(run["book_id"]), run_id=run_id)
    blocks = [dict(row) for row in blocks]
    if not blocks:
        raise HTTPException(status_code=400, detail="当前 V3 运行没有 semantic blocks")
    use_ai = payload.use_ai if payload is not None else False

    ai_provider = _create_required_analysis_ai_provider(db, user_id=int(user["id"])) if use_ai else None

    mention_count = await asyncio.to_thread(
        AnalysisPipelineV3(db.db, ai_provider=ai_provider).run_entity_mentions,
        int(run["book_id"]),
        run_id,
        blocks=blocks,
        use_ai=use_ai,
    )
    refreshed = await asyncio.to_thread(store.get_run, run_id)
    return {
        "ok": True,
        "run": _analysis_v3_run_item(refreshed),
        "mention_count": mention_count,
    }


@router.get("/analysis-v3/runs/{run_id}/mentions")
async def list_analysis_v3_mentions(
    run_id: int,
    limit: int = Query(default=1000, ge=1, le=2000),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    mentions = await asyncio.to_thread(
        EntityStore(db.db).list_mentions, int(run["book_id"]), run_id=run_id, limit=limit,
    )
    return {
        "run": _analysis_v3_run_item(run),
        "items": mentions,
    }


# ------------------------------------------------------------------
# 实体共指步骤
# ------------------------------------------------------------------

@limiter.limit("5/minute")
@router.post("/analysis-v3/runs/{run_id}/steps/entity_coreference")
async def run_analysis_v3_entity_coreference(
    run_id: int,
    request: Request,
    payload: StepUseAiRequest | None = None,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    entity_store = EntityStore(db.db)
    mentions = await asyncio.to_thread(entity_store.list_mentions, int(run["book_id"]), run_id=run_id, limit=5000)
    if not mentions:
        raise HTTPException(status_code=400, detail="当前 V3 运行没有 entity mentions")
    use_ai = payload.use_ai if payload is not None else False

    ai_provider = _create_required_analysis_ai_provider(db, user_id=int(user["id"])) if use_ai else None

    entity_count = await asyncio.to_thread(
        AnalysisPipelineV3(db.db, ai_provider=ai_provider).run_entity_coreference,
        int(run["book_id"]), run_id, use_ai=use_ai,
    )
    refreshed = await asyncio.to_thread(AnalysisStore(db.db).get_run, run_id)
    return {
        "ok": True,
        "run": _analysis_v3_run_item(refreshed),
        "entity_count": entity_count,
    }


# ------------------------------------------------------------------
# 实体操作
# ------------------------------------------------------------------

@router.get("/analysis-v3/runs/{run_id}/entities")
async def list_analysis_v3_entities(
    run_id: int,
    limit: int = Query(default=1000, ge=1, le=2000),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    entities = await asyncio.to_thread(
        EntityStore(db.db).list_entities, int(run["book_id"]), run_id=run_id, limit=limit,
    )
    return {
        "run": _analysis_v3_run_item(run),
        "items": entities,
    }


@router.post("/analysis-v3/runs/{run_id}/entities/merge")
async def merge_analysis_v3_entities(
    run_id: int,
    payload: EntityMergeRequest,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    target_uid = payload.target_entity_uid
    source_uids = [uid for uid in payload.source_entity_uids if uid != target_uid]
    if not target_uid or not source_uids:
        raise HTTPException(status_code=400, detail="target_entity_uid and source_entity_uids are required")
    entity_store = EntityStore(db.db)
    item = await asyncio.to_thread(
        entity_store.merge_entities,
        int(run["book_id"]),
        run_id,
        target_entity_uid=target_uid,
        source_entity_uids=source_uids,
        canonical_name=payload.canonical_name,
        aliases=payload.aliases,
        summary=payload.summary,
        actor="user",
    )
    if not item:
        raise HTTPException(status_code=404, detail="analysis v3 entities to merge were not found")
    try:
        card_coordinator = CardCoordinator(db.db)
        card_coordinator.run(
            book_id=int(run["book_id"]),
            run_id=run_id,
            target_entity_uids=[item["entity_uid"]],
        )
    except Exception as exc:
        _cloud_logger.warning("Card regeneration after entity merge failed: %s", exc)
    backtrack_task = await asyncio.to_thread(
        AnalysisPipelineV3(db.db).plan_backtrack_task,
        int(run["book_id"]),
        run_id,
        trigger_type="entity_merged",
        target_uid=item["entity_uid"],
        reason=payload.reason,
    )
    refreshed = await asyncio.to_thread(AnalysisStore(db.db).get_run, run_id)
    versions = await asyncio.to_thread(entity_store.list_entity_versions, int(run["book_id"]), run_id, item["entity_uid"])
    return {
        "ok": True,
        "run": _analysis_v3_run_item(refreshed),
        "item": item,
        "versions": versions,
        "backtrack_task": backtrack_task,
    }


@router.patch("/analysis-v3/runs/{run_id}/entities/{entity_uid}")
async def update_analysis_v3_entity(
    run_id: int,
    entity_uid: str,
    payload: EntityUpdateRequest,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    item = await asyncio.to_thread(
        EntityStore(db.db).update_entity,
        int(run["book_id"]),
        run_id,
        entity_uid,
        canonical_name=payload.canonical_name,
        status=payload.status,
        summary=payload.summary,
        aliases=[str(alias) for alias in payload.aliases] if payload.aliases is not None else None,
        actor=payload.actor,
    )
    if not item:
        raise HTTPException(status_code=404, detail="实体候选不存在")
    # 审核通过后自动重新生成该实体的卡片并写回
    writeback_result = None
    if payload.status == "reviewed":
        try:
            card_coordinator = CardCoordinator(db.db)
            card_coordinator.run(
                book_id=int(run["book_id"]),
                run_id=run_id,
                target_entity_uids=[entity_uid],
            )
        except Exception as exc:
            logging.getLogger(__name__).warning("审核后卡片重新生成失败: %s", exc)
        # 自动写回该实体的卡片
        try:
            store = AnalysisStore(db.db)
            cards_raw = await asyncio.to_thread(store.list_cards, run_id)
            entity_cards = [
                row for row in cards_raw
                if str(row["entity_uid"] or "") == entity_uid
                and str(row["status"] or "") in ("draft", "reviewed")
                and str(row["card_type"] or "").startswith("v3_")
            ]
            if entity_cards:
                from lingshu_api.routers.analysis_v3_cards import _create_writeback_card_generator
                writeback_generator = _create_writeback_card_generator(db, user_id=int(user["id"]))
                for card in entity_cards:
                    card_uid = str(card["card_uid"] or "")
                    result = await asyncio.to_thread(
                        store.apply_card,
                        int(run["book_id"]),
                        run_id,
                        card_uid,
                        actor="user",
                        writeback_generator=writeback_generator,
                        require_writeback_generator=False,
                    )
                    if result:
                        writeback_result = {
                            "applied_table": str(result["applied_table"] or ""),
                            "applied_id": int(result["applied_id"] or 0),
                            "detail": str(result["detail"] or ""),
                        }
        except Exception as exc:
            logging.getLogger(__name__).warning("审核后自动写回失败: %s", exc)
    versions = await asyncio.to_thread(
        EntityStore(db.db).list_entity_versions, int(run["book_id"]), run_id, entity_uid,
    )
    backtrack_task = await asyncio.to_thread(
        AnalysisPipelineV3(db.db).plan_backtrack_task,
        int(run["book_id"]),
        run_id,
        trigger_type="entity_updated",
        target_uid=entity_uid,
        reason="manual entity candidate update",
    )
    return {
        "ok": True,
        "run": _analysis_v3_run_item(run),
        "item": item,
        "versions": versions,
        "backtrack_task": backtrack_task,
        "writeback_result": writeback_result,
    }


@router.post("/analysis-v3/runs/{run_id}/entities/{entity_uid}/split")
async def split_analysis_v3_entity(
    run_id: int,
    entity_uid: str,
    payload: EntitySplitRequest,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    canonical_name = payload.canonical_name
    mention_uids = payload.mention_uids
    fact_uids = payload.fact_uids
    if not canonical_name:
        raise HTTPException(status_code=400, detail="canonical_name is required")
    if not mention_uids and not fact_uids:
        raise HTTPException(status_code=400, detail="mention_uids or fact_uids are required")
    entity_store = EntityStore(db.db)
    item = await asyncio.to_thread(
        entity_store.split_entity,
        int(run["book_id"]),
        run_id,
        source_entity_uid=entity_uid,
        canonical_name=canonical_name,
        aliases=payload.aliases,
        mention_uids=mention_uids,
        fact_uids=fact_uids,
        actor="user",
    )
    if not item:
        raise HTTPException(status_code=404, detail="analysis v3 entity to split was not found")
    try:
        card_coordinator = CardCoordinator(db.db)
        card_coordinator.run(
            book_id=int(run["book_id"]),
            run_id=run_id,
            target_entity_uids=[str(entity_uid), item["entity_uid"]],
        )
    except Exception as exc:
        _cloud_logger.warning("Card regeneration after entity split failed: %s", exc)
    backtrack_task = await asyncio.to_thread(
        AnalysisPipelineV3(db.db).plan_backtrack_task,
        int(run["book_id"]),
        run_id,
        trigger_type="entity_split",
        target_uid=str(entity_uid),
        reason=payload.reason,
    )
    refreshed = await asyncio.to_thread(AnalysisStore(db.db).get_run, run_id)
    source_versions = await asyncio.to_thread(entity_store.list_entity_versions, int(run["book_id"]), run_id, entity_uid)
    versions = await asyncio.to_thread(entity_store.list_entity_versions, int(run["book_id"]), run_id, item["entity_uid"])
    return {
        "ok": True,
        "run": _analysis_v3_run_item(refreshed),
        "item": item,
        "source_versions": source_versions,
        "versions": versions,
        "backtrack_task": backtrack_task,
    }


@router.get("/analysis-v3/runs/{run_id}/entities/{entity_uid}/versions")
async def list_analysis_v3_entity_versions(
    run_id: int,
    entity_uid: str,
    limit: int = Query(default=100, ge=1, le=500),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    versions = await asyncio.to_thread(
        EntityStore(db.db).list_entity_versions,
        int(run["book_id"]),
        run_id,
        entity_uid,
        limit=limit,
    )
    return {
        "run": _analysis_v3_run_item(run),
        "items": versions,
    }


@router.post("/analysis-v3/runs/{run_id}/entities/{entity_uid}/versions/{version}/rollback")
async def rollback_analysis_v3_entity_version(
    run_id: int,
    entity_uid: str,
    version: int,
    payload: EntityRollbackRequest,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    entity_store = EntityStore(db.db)
    item = await asyncio.to_thread(
        entity_store.rollback_entity,
        int(run["book_id"]),
        run_id,
        entity_uid,
        version,
        actor=payload.actor,
    )
    if not item:
        raise HTTPException(status_code=404, detail="analysis v3 entity version was not found")
    backtrack_task = await asyncio.to_thread(
        AnalysisPipelineV3(db.db).plan_backtrack_task,
        int(run["book_id"]),
        run_id,
        trigger_type="entity_rollback",
        target_uid=entity_uid,
        reason=payload.reason or f"manual rollback to version {version}",
    )
    refreshed = await asyncio.to_thread(AnalysisStore(db.db).get_run, run_id)
    versions = await asyncio.to_thread(entity_store.list_entity_versions, int(run["book_id"]), run_id, entity_uid)
    return {
        "ok": True,
        "run": _analysis_v3_run_item(refreshed),
        "item": item,
        "versions": versions,
        "backtrack_task": backtrack_task,
    }


# ------------------------------------------------------------------
# 审核摘要
# ------------------------------------------------------------------

@router.get("/analysis-v3/runs/{run_id}/review")
async def get_analysis_v3_review_summary(
    run_id: int,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
    for_single_card: bool = False,
):
    """获取 V3 分析运行的审核摘要与写回门禁。"""
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    book_id = int(run["book_id"])
    store = AnalysisStore(db.db)
    entity_store = EntityStore(db.db)
    fact_store = FactStore(db.db)
    entities = await asyncio.to_thread(entity_store.list_entities, book_id, run_id=run_id, limit=5000)
    facts = await asyncio.to_thread(fact_store.list_facts, book_id, run_id=run_id, limit=10000)
    cards_raw = await asyncio.to_thread(store.list_cards, run_id)
    cards = [dict(row) for row in cards_raw if str(row["card_type"] or "").startswith("v3_")]
    backtrack_tasks = await asyncio.to_thread(store.list_backtrack_tasks, book_id, run_id=run_id, limit=10000)
    probe_results = await asyncio.to_thread(store.list_probe_results, book_id, run_id=run_id, limit=10000)
    entity_status_counts = _count_by(entities, "status")
    fact_status_counts = _count_by(facts, "status")
    card_status_counts = _count_rows_by(cards, "status")
    # pending/running 表示回溯尚未完成，会阻塞写回；failed 为终态（无自动恢复），
    # 不应永久阻塞写回，单独计数作为软提示。
    pending_backtrack = [row for row in backtrack_tasks if str(row["status"] or "") in {"pending", "running"}]
    failed_backtrack = [row for row in backtrack_tasks if str(row["status"] or "") == "failed"]
    manual_review_probes = [
        row
        for row in probe_results
        if str(row["status"] or "") in {"manual_review", "inconsistent", "failed"}
    ]
    blockers = []
    soft_blockers = []
    run_meta = {}
    try:
        run_meta = json.loads(str(run["meta_json"] or "{}"))
    except Exception:
        pass
    ai_invoked = run_meta.get("ai_invoked") or run_meta.get("ai_stages")

    if entity_status_counts.get("candidate", 0) and ai_invoked:
        if for_single_card:
            soft_blockers.append("candidate_entities")
        else:
            blockers.append("candidate_entities")
    # 单卡写回时，run 级回溯/探针问题降级为软阻塞（与 candidate_entities 一致），
    # 避免与目标卡无关的未决项硬拦单卡写回；批量写回仍硬阻塞以保安全。
    if pending_backtrack:
        if for_single_card:
            soft_blockers.append("pending_backtrack_tasks")
        else:
            blockers.append("pending_backtrack_tasks")
    if manual_review_probes:
        if for_single_card:
            soft_blockers.append("probe_manual_review")
        else:
            blockers.append("probe_manual_review")
    # failed 回溯为终态，仅作为软提示，不阻塞写回
    if failed_backtrack:
        soft_blockers.append("failed_backtrack_tasks")
    formal_writeback_allowed = str(run["status"] or "") in _WRITEBACK_READY_STATUSES and not blockers
    writeback_mode = "auto" if formal_writeback_allowed else "blocked"
    return {
        "run": _analysis_v3_run_item(run),
        "item": {
            "formal_writeback_allowed": formal_writeback_allowed,
            "writeback_mode": writeback_mode,
            "entity_status_counts": entity_status_counts,
            "fact_status_counts": fact_status_counts,
            "card_status_counts": card_status_counts,
            "pending_backtrack_count": len(pending_backtrack),
            "failed_backtrack_count": len(failed_backtrack),
            "manual_review_probe_count": len(manual_review_probes),
            "blockers": blockers,
            "soft_blockers": soft_blockers,
            "next_step": "formal_writeback_gate",
        },
    }


# ------------------------------------------------------------------
# 原子事实步骤
# ------------------------------------------------------------------

@router.post("/analysis-v3/runs/{run_id}/steps/atomic_facts")
async def run_analysis_v3_atomic_facts(
    run_id: int,
    payload: StepUseAiRequest | None = None,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    entity_store = EntityStore(db.db)
    entities = await asyncio.to_thread(entity_store.list_entities, int(run["book_id"]), run_id=run_id, limit=5000)
    if not entities:
        raise HTTPException(status_code=400, detail="当前 V3 运行没有 entity candidates")
    use_ai = payload.use_ai if payload is not None else False

    ai_provider = _create_required_analysis_ai_provider(db, user_id=int(user["id"])) if use_ai else None

    fact_count = await asyncio.to_thread(
        AnalysisPipelineV3(db.db, ai_provider=ai_provider).run_atomic_facts,
        int(run["book_id"]), run_id, use_ai=use_ai,
    )
    refreshed = await asyncio.to_thread(AnalysisStore(db.db).get_run, run_id)
    return {
        "ok": True,
        "run": _analysis_v3_run_item(refreshed),
        "fact_count": fact_count,
    }


@router.get("/analysis-v3/runs/{run_id}/facts")
async def list_analysis_v3_facts(
    run_id: int,
    limit: int = Query(default=1000, ge=1, le=3000),
    entity_uid: str | None = Query(default=None),
    chapter_id: int | None = Query(default=None),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    facts = await asyncio.to_thread(
        FactStore(db.db).list_facts,
        int(run["book_id"]),
        run_id=run_id,
        entity_uid=entity_uid,
        chapter_id=chapter_id,
        limit=limit,
    )
    return {
        "run": _analysis_v3_run_item(run),
        "items": facts,
    }


# ------------------------------------------------------------------
# 卡片事件 / 记忆层 / 探针步骤
# ------------------------------------------------------------------

@router.post("/analysis-v3/runs/{run_id}/steps/card_events")
async def run_analysis_v3_card_events(run_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    facts = await asyncio.to_thread(FactStore(db.db).list_facts, int(run["book_id"]), run_id=run_id, limit=5000)
    if not facts:
        raise HTTPException(status_code=400, detail="当前 V3 运行没有 atomic facts")
    result = await asyncio.to_thread(AnalysisPipelineV3(db.db).run_card_events, int(run["book_id"]), run_id)
    refreshed = await asyncio.to_thread(AnalysisStore(db.db).get_run, run_id)
    return {
        "ok": True,
        "run": _analysis_v3_run_item(refreshed),
        **result.as_dict(),
    }


@router.post("/analysis-v3/runs/{run_id}/steps/memory_layer")
async def run_analysis_v3_memory_layer(run_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    facts = await asyncio.to_thread(FactStore(db.db).list_facts, int(run["book_id"]), run_id=run_id, limit=5000)
    if not facts:
        raise HTTPException(status_code=400, detail="当前 V3 运行没有 atomic facts")
    result = await asyncio.to_thread(AnalysisPipelineV3(db.db).run_memory_layer, int(run["book_id"]), run_id)
    refreshed = await asyncio.to_thread(AnalysisStore(db.db).get_run, run_id)
    return {
        "ok": True,
        "run": _analysis_v3_run_item(refreshed),
        **result,
    }


@router.post("/analysis-v3/runs/{run_id}/steps/probes")
async def run_analysis_v3_probes(run_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    facts = await asyncio.to_thread(FactStore(db.db).list_facts, int(run["book_id"]), run_id=run_id, limit=5000)
    if not facts:
        raise HTTPException(status_code=400, detail="当前 V3 运行没有 atomic facts")
    result = await asyncio.to_thread(AnalysisPipelineV3(db.db).run_probe_plans, int(run["book_id"]), run_id)
    refreshed = await asyncio.to_thread(AnalysisStore(db.db).get_run, run_id)
    return {
        "ok": True,
        "run": _analysis_v3_run_item(refreshed),
        **result.as_dict(),
    }


@router.get("/analysis-v3/runs/{run_id}/probes/plans")
async def list_analysis_v3_probe_plans(
    run_id: int,
    limit: int = Query(default=1000, ge=1, le=3000),
    status: str | None = Query(default=None),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    plans = await asyncio.to_thread(
        AnalysisStore(db.db).list_probe_plans,
        int(run["book_id"]),
        run_id=run_id,
        status=status,
        limit=limit,
    )
    return {
        "run": _analysis_v3_run_item(run),
        "items": plans,
    }


@router.get("/analysis-v3/runs/{run_id}/probes/results")
async def list_analysis_v3_probe_results(
    run_id: int,
    limit: int = Query(default=1000, ge=1, le=3000),
    status: str | None = Query(default=None),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    results = await asyncio.to_thread(
        AnalysisStore(db.db).list_probe_results,
        int(run["book_id"]),
        run_id=run_id,
        status=status,
        limit=limit,
    )
    return {
        "run": _analysis_v3_run_item(run),
        "items": results,
    }


# ------------------------------------------------------------------
# 事件
# ------------------------------------------------------------------

@router.get("/analysis-v3/runs/{run_id}/events")
async def list_analysis_v3_events(
    run_id: int,
    limit: int = Query(default=1000, ge=1, le=3000),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    events = await asyncio.to_thread(AnalysisStore(db.db).list_events, int(run["book_id"]), run_id=run_id, limit=limit)
    return {
        "run": _analysis_v3_run_item(run),
        "items": [_analysis_v3_event_item(row) for row in events],
    }


# ------------------------------------------------------------------
# 回溯任务
# ------------------------------------------------------------------

@router.post("/analysis-v3/runs/{run_id}/backtrack/tasks")
async def create_analysis_v3_backtrack_task(
    run_id: int,
    payload: BacktrackTaskCreate,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    target_uid = payload.target_uid
    if not target_uid:
        raise HTTPException(status_code=400, detail="target_uid 不能为空")
    trigger_type = payload.trigger_type
    task = await asyncio.to_thread(
        AnalysisPipelineV3(db.db).plan_backtrack_task,
        int(run["book_id"]),
        run_id,
        trigger_type=trigger_type,
        target_uid=target_uid,
        reason=payload.reason,
    )
    refreshed = await asyncio.to_thread(AnalysisStore(db.db).get_run, run_id)
    return {
        "ok": True,
        "run": _analysis_v3_run_item(refreshed),
        "item": task,
    }


@router.get("/analysis-v3/runs/{run_id}/backtrack/tasks")
async def list_analysis_v3_backtrack_tasks(
    run_id: int,
    limit: int = Query(default=100, ge=1, le=1000),
    status: str | None = Query(default=None),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    tasks = await asyncio.to_thread(
        AnalysisStore(db.db).list_backtrack_tasks,
        int(run["book_id"]),
        run_id=run_id,
        status=status,
        limit=limit,
    )
    return {
        "run": _analysis_v3_run_item(run),
        "items": [_analysis_v3_backtrack_task_item(row) for row in tasks],
    }


@router.post("/analysis-v3/runs/{run_id}/backtrack/tasks/{task_id}/execute")
async def execute_analysis_v3_backtrack_task(
    run_id: int,
    task_id: int,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    try:
        result = await asyncio.to_thread(AnalysisPipelineV3(db.db).run_backtrack_task, int(run["book_id"]), run_id, task_id)
    except ValueError as exc:
        _cloud_logger.exception("回溯任务执行失败")
        raise HTTPException(status_code=404, detail="回溯任务执行失败，请检查参数") from exc
    refreshed = await asyncio.to_thread(AnalysisStore(db.db).get_run, run_id)
    return {
        "ok": True,
        "run": _analysis_v3_run_item(refreshed),
        **result.as_dict(),
    }


@router.post("/analysis-v3/runs/{run_id}/backtrack/tasks/{task_id}/cancel")
async def cancel_analysis_v3_backtrack_task(
    run_id: int,
    task_id: int,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    store = AnalysisStore(db.db)
    task = await asyncio.to_thread(store.get_backtrack_task, task_id)
    if task is None or int(task["book_id"]) != int(run["book_id"]) or int(task["run_id"]) != int(run_id):
        raise HTTPException(status_code=404, detail="backtrack task not found")
    if str(task["status"] or "") in {"running", "completed"}:
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "当前回溯任务不能取消"})
    updated = await asyncio.to_thread(store.update_backtrack_task_status, task_id, "cancelled")
    refreshed = await asyncio.to_thread(store.get_run, run_id)
    return {
        "ok": True,
        "run": _analysis_v3_run_item(refreshed),
        "item": _analysis_v3_backtrack_task_item(updated or task),
    }


# ------------------------------------------------------------------
# 主动探针 — 历史记录由前端管理
# ------------------------------------------------------------------

@router.post("/books/{book_id}/active-probe")
async def run_active_probe(
    book_id: int,
    payload: ActiveProbeRequest,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """执行主动探针 — 用户输入查询，RAG+LLM 检索总结剧情。"""
    await check_book_owner(db, book_id, user)
    from novel_app.analysis.active_probe_executor import ActiveProbeExecutor

    executor = ActiveProbeExecutor(db.db)
    result = await asyncio.to_thread(
        executor.execute,
        book_id=book_id,
        query=payload.query,
    )
    return result
