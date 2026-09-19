"""
工作台分析运行 / 草案卡 / 写回 API（原 lingshu_api/routers/workspace.py 拆分而来）。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from lingshu_api.dependencies import check_book_owner, require_login, try_cloud_sync
from lingshu_api.routers.workspace_common import logger
from lingshu_api.schemas.analysis_v3 import AnalysisV1OneShotRunCreate
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db
from novel_app.analysis.diff_apply import apply_analysis_cards
from novel_app.analysis.store import AnalysisStore
from novel_app.json_utils import extract_json_dict

router = APIRouter(tags=["workspace"])


class ApplyAnalysisPayload(BaseModel):
    """应用分析结果请求体。"""
    user_override: bool = False
    allow_weak_evidence: bool | None = None

    @property
    def weak_evidence_allowed(self) -> bool:
        return bool(self.user_override or self.allow_weak_evidence)


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
    v1_analysis_max_total_chars = 300_000
    total_content_chars = sum(len(str(ch.get("content") or "")) for ch in chapters)
    if total_content_chars > v1_analysis_max_total_chars:
        raise HTTPException(
            status_code=413,
            detail=(
                f"作品总字数约 {total_content_chars:,} 字，超过 V1 一次性分析上限 "
                f"{v1_analysis_max_total_chars:,} 字。请切换使用 V3 分析功能"
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
        from novel_app.analysis.pipeline import AnalysisPipeline
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
