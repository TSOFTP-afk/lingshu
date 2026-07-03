"""analysis_v3 运行管理路由 — 创建/查询/取消分析运行。"""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from slowapi import Limiter
from slowapi.util import get_remote_address

from lingshu_api.dependencies import check_book_owner, get_store, require_login, try_cloud_sync
from lingshu_api.schemas.analysis_v3 import AnalysisV3IncrementalRunCreate, AnalysisV3RunCreate
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db
from novel_app.analysis.pipeline_v3 import PIPELINE_V3_VERSION, AnalysisPipelineV3
from novel_app.analysis.store import AnalysisStore
from novel_app.json_utils import extract_json_object

router = APIRouter(prefix="/api/workspace", tags=["analysis-v3-runs"])
_cloud_logger = __import__("logging").getLogger(__name__)
limiter = Limiter(key_func=get_remote_address)


def _create_required_analysis_ai_provider(db: WorkspaceDB, *, purpose: str = "V3 AI 增强分析", user_id: int | None = None):
    """为显式 use_ai 请求创建 V3 AI provider，失败时禁止静默降级。"""
    try:
        from lingshu_api.ws.generation import _create_ai_service
        from novel_app.analysis.ai_provider import AIAnalysisProvider
        from novel_app.analysis.llm_cache import LLMCache

        ai_service = _create_ai_service("book_analysis", workspace_db=db, user_id=user_id)
        ai_service.require_remote(purpose)
        return AIAnalysisProvider(ai_service, LLMCache(db.db), database=db.db)
    except Exception as exc:
        _cloud_logger.exception("%s不可用", purpose)
        raise HTTPException(status_code=503, detail=f"{purpose}不可用，请稍后重试") from exc


def _load_chapters_for_analysis(db: WorkspaceDB, book_id: int) -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = []
    for row in db.list_chapters(book_id):
        chapter = db.get_chapter(int(row["id"]))
        if chapter and str(chapter.get("content") or "").strip():
            chapters.append(chapter)
    return chapters


async def _get_analysis_v3_run_or_404(db: WorkspaceDB, run_id: int):
    store = AnalysisStore(db.db)
    run = await asyncio.to_thread(store.get_run, run_id)
    if not run or not _is_analysis_v3_run(run):
        raise HTTPException(status_code=404, detail="Analysis V3 运行不存在")
    return run


async def _check_run_book_owner(db: WorkspaceDB, run_id: int, user: dict) -> None:
    """从分析运行中获取 book_id 并校验归属。"""
    run = await _get_analysis_v3_run_or_404(db, run_id)
    book_id = int(run["book_id"])
    await asyncio.to_thread(check_book_owner, db, book_id, user)


async def _check_run_book_owner_for_book(db: WorkspaceDB, book_id: int, user: dict) -> None:
    """校验 book_id 归属（用于已知 book_id 的路由）。"""
    await asyncio.to_thread(check_book_owner, db, book_id, user)


def _is_analysis_v3_run(row: Any) -> bool:
    return str(row["pipeline_version"] or "").startswith("analysis_v3")


# 北京时间时区（UTC+8），SQLite CURRENT_TIMESTAMP 存储 UTC，需转换后返回前端
_BEIJING_TZ = timezone(timedelta(hours=8))


def _utc_to_beijing(value: Any) -> str:
    """将 SQLite 存储的 UTC 时间字符串转换为北京时间字符串。

    SQLite CURRENT_TIMESTAMP 格式: 'YYYY-MM-DD HH:MM:SS'（UTC）。
    转换后格式: 'YYYY-MM-DD HH:MM:SS'（北京时间）。
    无法解析或空值时返回原始字符串，保证向前兼容。
    """
    raw = str(value or "") if value is not None else ""
    if not raw.strip():
        return ""
    # 兼容 'YYYY-MM-DD HH:MM:SS' 和 'YYYY-MM-DDTHH:MM:SS' 两种格式
    text = raw.strip().replace("T", " ")
    # 截取到秒，避免尾部时区标记干扰
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(text[:19] if len(text) >= 19 else text, fmt)
            dt = dt.replace(tzinfo=timezone.utc).astimezone(_BEIJING_TZ)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return raw


def _analysis_v3_run_item(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    meta = extract_json_object(str(row["meta_json"] or "{}"))
    return {
        "id": int(row["id"]),
        "book_id": int(row["book_id"]),
        "scope_type": str(row["scope_type"] or "book"),
        "status": str(row["status"] or ""),
        "pipeline_version": str(row["pipeline_version"] or PIPELINE_V3_VERSION),
        "input_hash": str(row["input_hash"] or ""),
        "summary": str(row["summary"] or ""),
        "error_text": _classify_error_text(str(row["error_text"] or "")),
        "meta": meta,
        "block_count": int(meta.get("semantic_block_count") or 0),
        "mention_count": int(meta.get("mention_count") or 0),
        "entity_count": int(meta.get("entity_count") or 0),
        "fact_count": int(meta.get("fact_count") or 0),
        "memory_fact_count": int(meta.get("memory_fact_count") or 0),
        "memory_summary_fact_count": int(meta.get("memory_summary_fact_count") or 0),
        "event_count": int(meta.get("event_count") or 0),
        "card_count": int(meta.get("card_count") or row["card_count"] or 0),
        "probe_plan_count": int(meta.get("probe_plan_count") or 0),
        "probe_result_count": int(meta.get("probe_result_count") or 0),
        "probe_inconsistent_count": int(meta.get("probe_inconsistent_count") or 0),
        "probe_manual_review_count": int(meta.get("probe_manual_review_count") or 0),
        "created_at": _utc_to_beijing(row["created_at"]),
        "updated_at": _utc_to_beijing(row["updated_at"]),
        "completed_at": _utc_to_beijing(row["completed_at"]),
    }


def _analysis_v3_block_item(row: Any) -> dict[str, Any]:
    text = str(row["text"] or "")
    metadata = extract_json_object(str(row["metadata_json"] or "{}"))
    return {
        "id": int(row["id"]),
        "book_id": int(row["book_id"]),
        "run_id": int(row["run_id"]),
        "block_uid": str(row["block_uid"] or ""),
        "chunk_id": str(row["chunk_id"] or ""),
        "chunk_index": int(row["chunk_index"] or 0),
        "chapter_id": row["chapter_id"],
        "chapter_refs": __import__("novel_app.json_utils", fromlist=["extract_json_array"]).extract_json_array(str(row["chapter_refs_json"] or "[]")),
        "char_start": int(row["char_start"] or 0),
        "char_end": int(row["char_end"] or 0),
        "text_length": len(text),
        "snippet": text[:240],
        "summary": str(row["summary"] or ""),
        "content_hash": str(row["content_hash"] or ""),
        "structure_hash": str(row["structure_hash"] or ""),
        "pipeline_version": str(row["pipeline_version"] or ""),
        "metadata": metadata,
        "created_at": _utc_to_beijing(row["created_at"]),
        "updated_at": _utc_to_beijing(row["updated_at"]),
    }


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


@limiter.limit("3/minute")
@router.post("/books/{book_id}/analysis-v3/runs")
async def create_analysis_v3_run(
    request: Request,
    book_id: int,
    payload: AnalysisV3RunCreate,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    if not await asyncio.to_thread(db.get_book, book_id):
        raise HTTPException(status_code=404, detail="作品不存在")
    await _check_run_book_owner_for_book(db, book_id, user)
    chapters = await asyncio.to_thread(_load_chapters_for_analysis, db, book_id)
    if not chapters:
        raise HTTPException(status_code=400, detail="作品没有可分析正文")
    execute_l1 = payload.execute_l1
    use_ai = payload.use_ai

    ai_provider = _create_required_analysis_ai_provider(db, user_id=int(user["id"])) if use_ai else None

    result = await asyncio.to_thread(
        AnalysisPipelineV3(db.db, ai_provider=ai_provider).start_run,
        book_id,
        chapters=chapters,
        execute_l1=execute_l1,
        meta={"source": "workspace_api"},
        use_ai=use_ai,
    )
    with contextlib.suppress(Exception):
        get_store(request).record_user_analysis_run(
            user_id=int(user["id"]),
            book_id=book_id,
            analysis_mode="analysis_v3_l1" if execute_l1 else "analysis_v3_shell",
            input_chars=sum(len(str(chapter.get("content") or "")) for chapter in chapters),
            status="completed",
            source="analysis_v3_api",
            run_ref=str(result.run_id),
            metadata={"block_count": result.block_count, "mention_count": result.mention_count},
        )
    store = AnalysisStore(db.db)
    run = await asyncio.to_thread(store.get_run, result.run_id)
    try_cloud_sync(request, book_id, user)
    return {"ok": True, "item": _analysis_v3_run_item(run), **result.as_dict()}


@router.post("/books/{book_id}/analysis-v3/incremental")
async def create_analysis_v3_incremental_run(
    request: Request,
    book_id: int,
    payload: AnalysisV3IncrementalRunCreate,
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    """增量分析：仅处理新增/变更章节，复用已有 run 的结果。"""
    if not await asyncio.to_thread(db.get_book, book_id):
        raise HTTPException(status_code=404, detail="作品不存在")
    await _check_run_book_owner_for_book(db, book_id, user)
    chapters = await asyncio.to_thread(_load_chapters_for_analysis, db, book_id)
    if not chapters:
        raise HTTPException(status_code=400, detail="作品没有可分析正文")
    base_run_id = payload.base_run_id
    use_ai = payload.use_ai

    ai_provider = _create_required_analysis_ai_provider(db, user_id=int(user["id"])) if use_ai else None

    result = await asyncio.to_thread(
        AnalysisPipelineV3(db.db, ai_provider=ai_provider).start_incremental_run,
        book_id,
        base_run_id=base_run_id,
        chapters=chapters,
        meta={"source": "workspace_api_incremental"},
        use_ai=use_ai,
    )
    with contextlib.suppress(Exception):
        get_store(request).record_user_analysis_run(
            user_id=int(user["id"]),
            book_id=book_id,
            analysis_mode="analysis_v3_incremental",
            input_chars=sum(len(str(chapter.get("content") or "")) for chapter in chapters),
            status="completed",
            source="analysis_v3_api",
            run_ref=str(result.run_id),
            metadata={"block_count": result.block_count, "incremental": True},
        )
    store = AnalysisStore(db.db)
    run = await asyncio.to_thread(store.get_run, result.run_id)
    try_cloud_sync(request, book_id, user)
    return {"ok": True, "item": _analysis_v3_run_item(run), **result.as_dict()}


@router.get("/books/{book_id}/analysis-v3/runs")
async def list_analysis_v3_runs(
    book_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    if not await asyncio.to_thread(db.get_book, book_id):
        raise HTTPException(status_code=404, detail="作品不存在")
    await _check_run_book_owner_for_book(db, book_id, user)
    store = AnalysisStore(db.db)
    runs = await asyncio.to_thread(store.list_runs, book_id, limit=limit)
    return {"items": [_analysis_v3_run_item(row) for row in runs if _is_analysis_v3_run(row)]}


@router.post("/analysis-v3/runs/{run_id}/cancel")
async def cancel_analysis_v3_run(run_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    store = AnalysisStore(db.db)
    current_status = str(run["status"] or "")
    if current_status not in {"pending", "running"}:
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": "只有 pending/running 状态的运行可以取消"})
    await asyncio.to_thread(store.update_run_status, run_id, "cancelled")
    refreshed = await asyncio.to_thread(store.get_run, run_id)
    return {
        "ok": True,
        "item": _analysis_v3_run_item(refreshed),
    }


@router.get("/analysis-v3/runs/{run_id}")
async def get_analysis_v3_run(run_id: int, user: dict = Depends(require_login), db: WorkspaceDB = Depends(get_workspace_db)):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    return {"item": _analysis_v3_run_item(run)}


@router.get("/analysis-v3/runs/{run_id}/blocks")
async def list_analysis_v3_blocks(
    run_id: int,
    limit: int = Query(default=500, ge=1, le=1000),
    user: dict = Depends(require_login),
    db: WorkspaceDB = Depends(get_workspace_db),
):
    await _check_run_book_owner(db, run_id, user)
    run = await _get_analysis_v3_run_or_404(db, run_id)
    store = AnalysisStore(db.db)
    blocks = await asyncio.to_thread(store.list_blocks, int(run["book_id"]), run_id=run_id, limit=limit)
    return {
        "run": _analysis_v3_run_item(run),
        "items": [_analysis_v3_block_item(row) for row in blocks],
    }
