"""
V3 分析引擎 WebSocket — 实时进度推送。

协议:
  请求: {"type":"analyze_v3","task_id":"uuid","payload":{"book_id":...}}
  进度: {"type":"analysis_v3.progress","task_id":"uuid","payload":{"stage":"...","percent":45,"message":"..."}}
  完成: {"type":"analysis_v3.result","task_id":"uuid","payload":{"status":"ok","run_id":...,...}}
  错误: {"type":"analysis_v3.error","task_id":"uuid","payload":{"message":"..."}}
  取消: {"type":"cancel","task_id":"uuid"}
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, WebSocket

from lingshu_api.dependencies import check_book_owner
from lingshu_api.services.db_bridge import get_workspace_db
from lingshu_api.ws.connection import ConnectionManager, authenticate_ws, get_ws_manager
from lingshu_api.ws.generation import _workspace_db_from_app
from lingshu_api.ws.tasks import get_ws_task_registry
from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3, AnalysisPipelineV3Cancelled

logger = logging.getLogger(__name__)
router = APIRouter()
_active_analysis_v3_cancels: dict[str, threading.Event] = {}


def _record_failed_v3_run(db_obj, book_id: int, error_text: str, *, use_ai: bool = False) -> None:
    """记录失败的 V3 分析 run，便于前端展示失败原因。

    在 V3 分析异常时调用（如 AI 初始化失败、require_remote 抛异常等），
    创建一条 status=failed 的 run 记录，将 error_text 写入数据库。
    注意：pipeline.start_run 内部的失败由 pipeline 自己处理（已会 update_run_status 为 failed），
    此函数仅用于 start_run 之前就失败的场景（如 AI 初始化阶段）。
    """
    try:
        from novel_app.analysis.pipeline_v3 import PIPELINE_V3_VERSION
        from novel_app.analysis.store import AnalysisStore
        store = AnalysisStore(db_obj)
        run_id = store.create_run(
            int(book_id),
            scope_type="book",
            status="created",
            pipeline_version=PIPELINE_V3_VERSION,
            meta={"source": "ws_analysis_v3", "failed": True, "ai_invoked": use_ai},
            summary="分析失败",
        )
        store.update_run_status(
            run_id, "failed",
            error_text=str(error_text)[:2000],
            summary="分析失败",
        )
    except Exception:
        logger.exception("Failed to record failed V3 analysis run book_id=%s", book_id)


@router.websocket("/ws/analysis-v3")
async def ws_analysis_v3(ws: WebSocket):
    conn = await authenticate_ws(ws, error_type="analysis_v3.error")
    if conn is None:
        return
    manager = get_ws_manager()
    client_id = conn.client_id
    workspace_db = _workspace_db_from_app(ws.app)

    try:
        while True:
            raw = await ws.receive_text()
            if len(raw) > ConnectionManager.MAX_WS_MESSAGE_SIZE:
                await manager.send(client_id, {
                    "type": "analysis_v3.error",
                    "task_id": "",
                    "payload": {"message": "消息大小超过限制"},
                })
                await ws.close(code=1009, reason="消息过大")
                break
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send(client_id, {
                    "type": "analysis_v3.error",
                    "task_id": "",
                    "payload": {"message": "无效的 JSON 格式"},
                })
                continue

            # 处理 pong 响应，更新 last_pong 时间
            if msg.get("type") == "pong":
                conn = manager.connections.get(client_id)
                if conn:
                    conn.last_pong = asyncio.get_event_loop().time()
                continue

            task_id = msg.get("task_id", "")

            if msg.get("type") == "cancel":
                active = _active_analysis_v3_cancels.get(client_id)
                if active is not None:
                    active.set()
                await get_ws_task_registry().cancel_client_and_wait(client_id)
                await manager.send(client_id, {
                    "type": "analysis_v3.result",
                    "task_id": task_id,
                    "payload": {"status": "cancelled"},
                })
                continue

            if msg.get("type") != "analyze_v3":
                await manager.send(client_id, {
                    "type": "analysis_v3.error",
                    "task_id": task_id,
                    "payload": {"message": f"未知消息类型: {msg.get('type')}"},
                })
                continue

            payload = msg.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}
            book_id = int(payload.get("book_id", 0))
            use_ai = bool(payload.get("use_ai", False))
            if not book_id:
                await manager.send(client_id, {
                    "type": "analysis_v3.error",
                    "task_id": task_id,
                    "payload": {"message": "缺少 book_id"},
                })
                continue

            previous = _active_analysis_v3_cancels.get(client_id)
            if previous is not None:
                previous.set()
            cancel_event = threading.Event()
            _active_analysis_v3_cancels[client_id] = cancel_event
            try:
                get_ws_task_registry().create(
                    client_id,
                    _run_analysis_v3(
                        ws.app.state.store,
                        manager,
                        client_id,
                        task_id,
                        book_id,
                        workspace_db,
                        use_ai=use_ai,
                        cancel_event=cancel_event,
                    ),
                    name=f"ws-analysis-v3:{client_id}:{task_id}",
                )
            except RuntimeError:
                await manager.send(client_id, {
                    "type": "analysis_v3.error",
                    "task_id": task_id,
                    "payload": {"message": "并发任务数已达上限，请等待当前任务完成"},
                })

    except Exception:
        pass
    finally:
        active = _active_analysis_v3_cancels.get(client_id)
        if active is not None:
            active.set()
        await get_ws_task_registry().cancel_client_and_wait(client_id)
        manager.disconnect(client_id)


async def _run_analysis_v3(
    store,
    manager,
    client_id: str,
    task_id: str,
    book_id: int,
    workspace_db=None,
    *,
    use_ai: bool = False,
    cancel_event: threading.Event | None = None,
) -> None:
    """运行 V3 分析管线，通过 WebSocket 推送进度。"""
    db = workspace_db or get_workspace_db()
    book = db.get_book(book_id)
    if not book:
        await manager.send(client_id, {
            "type": "analysis_v3.error",
            "task_id": task_id,
            "payload": {"message": "作品不存在"},
        })
        return
    conn = manager.connections.get(client_id)
    user = dict(conn.user) if conn and conn.user else None
    if not user:
        await manager.send(client_id, {
            "type": "analysis_v3.error",
            "task_id": task_id,
            "payload": {"message": "未登录或登录已失效"},
        })
        return
    try:
        check_book_owner(db, book_id, user)
    except Exception as exc:
        await manager.send(client_id, {
            "type": "analysis_v3.error",
            "task_id": task_id,
            "payload": {"message": str(getattr(exc, "detail", "") or "无权访问作品")},
        })
        return

    chapters = _load_chapters(db, book_id)
    if not chapters:
        await manager.send(client_id, {
            "type": "analysis_v3.error",
            "task_id": task_id,
            "payload": {"message": "作品没有可分析正文"},
        })
        return

    await manager.send(client_id, {
        "type": "analysis_v3.progress",
        "task_id": task_id,
        "payload": {"stage": "init", "percent": 0, "message": "V3 分析启动中...", "engine": "ai" if use_ai else "rule"},
    })

    # 标记分析进行中，避免 ping_loop 因 AI 长调用误判僵尸连接
    conn.analysis_active = True

    progress_queue: asyncio.Queue[tuple[str, int, str]] = asyncio.Queue()
    # 心跳跟踪：记录最后一次真实进度，用于在长时间 AI 调用期间发送心跳保活
    last_real_progress: dict[str, Any] = {"stage": "init", "percent": 0, "message": "", "time": time.monotonic()}

    def progress_callback(stage: str, percent: int, message: str) -> None:
        last_real_progress["stage"] = stage
        last_real_progress["percent"] = percent
        last_real_progress["message"] = message
        last_real_progress["time"] = time.monotonic()
        with suppress(Exception):
            progress_queue.put_nowait((stage, percent, message))

    loop = asyncio.get_running_loop()

    async def _forward_progress():
        """将 pipeline 的进度回调转发到 WebSocket，并在长时间无进度时发送心跳保活。"""
        heartbeat_interval = 25.0  # 每 25 秒发送一次心跳，防止前端 60s 超时
        while True:
            try:
                stage, percent, message = await asyncio.wait_for(
                    progress_queue.get(), timeout=1.0
                )
                await manager.send(client_id, {
                    "type": "analysis_v3.progress",
                    "task_id": task_id,
                    "payload": {"stage": stage, "percent": percent, "message": message, "engine": "ai" if use_ai else "rule"},
                })
            except TimeoutError:
                # 无真实进度时，若超过心跳间隔则发送保活心跳
                now = time.monotonic()
                if now - last_real_progress["time"] >= heartbeat_interval:
                    last_real_progress["time"] = now
                    hb_stage = last_real_progress["stage"]
                    hb_percent = last_real_progress["percent"]
                    hb_msg = last_real_progress["message"] or "正在处理中..."
                    with suppress(Exception):
                        await manager.send(client_id, {
                            "type": "analysis_v3.progress",
                            "task_id": task_id,
                            "payload": {"stage": hb_stage, "percent": hb_percent, "message": f"⏳ {hb_msg}", "engine": "ai" if use_ai else "rule", "heartbeat": True},
                        })
                continue
            except Exception:
                break

    forwarder = asyncio.create_task(_forward_progress())

    try:
        def _do_run():
            ai_provider = None
            if use_ai:
                progress_callback("ai_init", 2, "正在初始化 AI 服务...")
                from lingshu_api.ws.generation import _create_ai_service
                from novel_app.analysis.ai_provider import AIAnalysisProvider
                from novel_app.analysis.llm_cache import LLMCache

                user_id = int(user["id"]) if user else None
                ai_service = _create_ai_service("book_analysis", workspace_db=db, user_id=user_id)
                ai_service.require_remote("V3 AI 增强分析")
                ai_provider = AIAnalysisProvider(ai_service, LLMCache(db.db), database=db.db)
                progress_callback("ai_init", 5, "AI 服务已就绪，开始语义分块...")
            else:
                progress_callback("init", 2, "正在启动分析管线...")

            pipeline = AnalysisPipelineV3(db.db, ai_provider=ai_provider)
            return pipeline.start_run(
                book_id,
                chapters=chapters,
                execute_l1=True,
                meta={"source": "ws_analysis_v3", "task_id": task_id},
                progress_callback=progress_callback,
                use_ai=use_ai,
                cancel_event=cancel_event,
            )

        result = await loop.run_in_executor(None, _do_run)
        if user:
            try:
                store.record_user_analysis_run(
                    user_id=int(user["id"]),
                    book_id=book_id,
                    analysis_mode="analysis_v3_l1",
                    input_chars=sum(len(str(chapter.get("content") or "")) for chapter in chapters),
                    status="completed",
                    source="analysis_v3_ws",
                    run_ref=str(result.run_id),
                    metadata={"block_count": result.block_count, "mention_count": result.mention_count},
                )
            except Exception:
                logger.exception("Failed to record V3 analysis usage")

        # 发送最终进度
        await progress_queue.put(("completed", 100, "V3 分析完成"))
        # 等待转发器处理完
        await asyncio.sleep(0.5)

        await manager.send(client_id, {
            "type": "analysis_v3.result",
            "task_id": task_id,
            "payload": {
                "status": "ok",
                "run_id": result.run_id,
                "block_count": result.block_count,
                "mention_count": result.mention_count,
                "entity_count": result.entity_count,
                "fact_count": result.fact_count,
                "card_count": result.card_count,
                "summary": result.summary,
            },
        })

    except asyncio.CancelledError:
        raise
    except AnalysisPipelineV3Cancelled:
        await manager.send(client_id, {
            "type": "analysis_v3.result",
            "task_id": task_id,
            "payload": {"status": "cancelled"},
        })
    except Exception as exc:
        exc_msg = str(exc)
        logger.exception("V3 analysis WS failed: book_id=%s", book_id)
        # 记录失败 run，便于前端展示失败原因
        _record_failed_v3_run(db.db, book_id, exc_msg, use_ai=use_ai)
        # 区分错误类型返回更有针对性的提示
        if "401" in exc_msg or "Authentication Fails" in exc_msg or ("invalid" in exc_msg.lower() and "api key" in exc_msg.lower()):
            err_msg = "AI 接口认证失败，请在设置中检查 API Key 是否正确"
        elif "429" in exc_msg or "rate limit" in exc_msg.lower():
            err_msg = "AI 接口被限流，请稍后重试"
        elif "timeout" in exc_msg.lower() or "timed out" in exc_msg.lower():
            err_msg = "AI 接口响应超时，请稍后重试"
        elif "没有配置可用 AI 接口" in exc_msg:
            err_msg = "未配置 AI 接口，请在设置中配置 AI API Key 后再使用 AI 增强分析"
        else:
            err_msg = "V3 分析失败，请稍后重试"
        await manager.send(client_id, {
            "type": "analysis_v3.error",
            "task_id": task_id,
            "payload": {"message": err_msg},
        })
    finally:
        forwarder.cancel()
        with suppress(asyncio.CancelledError):
            await forwarder
        if conn is not None:
            conn.analysis_active = False
        if cancel_event is not None and _active_analysis_v3_cancels.get(client_id) is cancel_event:
            _active_analysis_v3_cancels.pop(client_id, None)


def _load_chapters(db, book_id: int) -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = []
    for row in db.list_chapters(book_id):
        chapter = db.get_chapter(int(row["id"]))
        if chapter and str(chapter.get("content") or "").strip():
            chapters.append(chapter)
    return chapters
