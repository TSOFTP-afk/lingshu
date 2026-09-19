"""
AI 生成 WebSocket — 对应 Qt workers.py (AiWorker) + app_generation.py
协议:
  请求: {"type":"generate","task_id":"uuid","payload":{"mode":"draft|continue|polish","title":"书","outline":"...", ...}}
  进度: {"type":"progress","task_id":"uuid","payload":{"stage":"writing","percent":45}}
  文本: {"type":"chunk","task_id":"uuid","payload":{"text":"..."}}
  完成: {"type":"result","task_id":"uuid","payload":{"text":"完整文本","status":"ok"}}
"""
from __future__ import annotations

import asyncio
import json
import logging
from threading import Event
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket

from lingshu_api.dependencies import check_book_owner, check_chapter_owner
from lingshu_api.services.ai_settings import resolve_ai_profile
from lingshu_api.services.db_bridge import get_workspace_db
from lingshu_api.services.usage_recorder import record_ai_usage
from lingshu_api.ws.connection import ConnectionManager, authenticate_ws, get_ws_manager
from lingshu_api.ws.tasks import get_ws_task_registry
from novel_app.ai.service import SimpleAIService

logger = logging.getLogger(__name__)
router = APIRouter()
_generation_cancel_events: dict[str, Event] = {}


def _to_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _workspace_db_from_app(app):
    provider = getattr(getattr(app, "state", None), "workspace_db_provider", None)
    return provider.get() if provider is not None else get_workspace_db()


def _create_ai_service(purpose: str = "writing", workspace_db=None, *, user_id: int | None = None, **overrides) -> SimpleAIService:
    """从环境变量创建 SimpleAIService 实例。"""
    db = workspace_db or get_workspace_db()
    profile = resolve_ai_profile(db.db.data_dir, purpose, user_id=user_id)
    extra_body_str = profile.get("extra_body")
    extra_body = None
    if extra_body_str:
        try:
            extra_body = json.loads(extra_body_str) if isinstance(extra_body_str, str) else extra_body_str
        except (json.JSONDecodeError, TypeError):
            extra_body = None
    kwargs: dict = {
        "api_key": profile.get("api_key") or None,
        "base_url": profile.get("base_url") or None,
        "model": profile.get("model") or None,
    }
    if extra_body:
        kwargs["extra_body"] = extra_body
    kwargs.update(overrides)
    return SimpleAIService(**kwargs)


def _try_create_generation_snapshot(workspace_db, chapter_id, *, mode, payload, accumulated_text, status, task_id):
    """在生成结束时尝试自动创建快照，失败不阻塞 WS 响应。"""
    if not chapter_id:
        return
    try:
        chapter_id_int = int(chapter_id)
    except (TypeError, ValueError):
        logger.warning("无效的 chapter_id=%r，跳过生成快照创建", chapter_id)
        return
    if workspace_db is None:
        logger.warning("workspace_db 不可用，跳过生成快照创建 chapter_id=%s", chapter_id_int)
        return
    try:
        workspace_db.create_generation_snapshot(chapter_id_int, {
            "mode": mode,
            "outline": payload.get("outline", ""),
            "generated_text": accumulated_text or "",
            "selected_skills": payload.get("selected_skills", []),
            "status": status,
            "task_id": task_id,
        })
    except Exception:
        logger.exception("自动创建生成快照失败 chapter_id=%s", chapter_id_int)


@router.websocket("/ws/generation")
async def ws_generation(ws: WebSocket):
    conn = await authenticate_ws(ws)
    if conn is None:
        return
    manager = get_ws_manager()
    client_id = conn.client_id
    workspace_db = _workspace_db_from_app(ws.app)

    try:
        while True:
            raw = await ws.receive_text()
            if len(raw) > ConnectionManager.MAX_WS_MESSAGE_SIZE:
                await manager.send(client_id, {"type": "error", "task_id": "", "payload": {"message": "消息大小超过限制"}})
                await ws.close(code=1009, reason="消息过大")
                break
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send(client_id, {"type": "error", "task_id": "", "payload": {"message": "无效的 JSON 格式"}})
                continue

            # 处理 pong 响应，更新 last_pong 时间
            if msg.get("type") == "pong":
                conn = manager.connections.get(client_id)
                if conn:
                    conn.last_pong = asyncio.get_event_loop().time()
                continue

            if msg.get("type") == "cancel":
                active = _generation_cancel_events.get(client_id)
                if active:
                    active.set()
                get_ws_task_registry().cancel_client(client_id)
                await manager.send(client_id, {"type": "result", "task_id": msg.get("task_id", ""), "payload": {"status": "cancelled"}})
                continue

            if msg.get("type") != "generate":
                await manager.send(client_id, {"type": "error", "task_id": msg.get("task_id", ""), "payload": {"message": f"未知消息类型: {msg.get('type')}"}})
                continue

            task_id = msg.get("task_id", "")
            payload = msg.get("payload", {})
            mode = payload.get("mode", "draft")
            # 所有权校验（修复 V6-NEW-06：之前完全缺少 check_book_ownership，
            # 攻击者可传他人 chapter_id 在他人章节写入生成快照）。
            # 有 chapter_id 时通过 chapter 反查 book 校验；否则校验 book_id。
            chapter_id = _to_int(payload.get("chapter_id"))
            book_id = _to_int(payload.get("book_id"))
            if conn.user and (chapter_id or book_id) and workspace_db:
                try:
                    if chapter_id:
                        check_chapter_owner(workspace_db, chapter_id, dict(conn.user))
                    elif book_id:
                        check_book_owner(workspace_db, book_id, dict(conn.user))
                except HTTPException as exc:
                    await manager.send(client_id, {
                        "type": "error",
                        "task_id": task_id,
                        "payload": {"message": str(getattr(exc, "detail", "") or "无权操作该书籍")},
                    })
                    continue
            cancel_event = Event()
            _generation_cancel_events[client_id] = cancel_event

            # 在后台线程中运行 AI 生成
            try:
                get_ws_task_registry().create(
                    client_id,
                    _run_generation(ws.app.state.store, manager, client_id, task_id, mode, payload, cancel_event, workspace_db),
                    name=f"ws-generation:{client_id}:{task_id}",
                )
            except RuntimeError:
                await manager.send(client_id, {"type": "error", "task_id": task_id, "payload": {"message": "并发任务数已达上限，请等待当前任务完成"}})

    except Exception:
        pass
    finally:
        active = _generation_cancel_events.pop(client_id, None)
        if active:
            active.set()
        await get_ws_task_registry().cancel_client_and_wait(client_id)
        manager.disconnect(client_id)


async def _run_generation(store, manager, client_id, task_id, mode, payload, cancel_event, workspace_db=None):
    """在后台运行 AI 生成任务。"""
    conn = manager.connections.get(client_id)
    user = dict(conn.user) if conn and conn.user else None
    user_id = int(user["id"]) if user else None
    ai_service = _create_ai_service("writing", workspace_db=workspace_db, user_id=user_id)
    label = {"draft": "草稿生成", "continue": "续写", "polish": "润色"}.get(mode, mode)
    accumulated = ""
    chapter_id = payload.get("chapter_id")

    try:
        await manager.send(client_id, {
            "type": "progress", "task_id": task_id,
            "payload": {"stage": "preparing", "percent": 0, "message": f"准备{label}..."},
        })

        # 在 executor 中运行阻塞的流式生成
        loop = asyncio.get_event_loop()

        def _stream():
            return list(ai_service.stream_generate(
                mode=mode,
                book_title=payload.get("book_title", ""),
                chapter_title=payload.get("chapter_title", ""),
                outline=payload.get("outline", ""),
                current_content=payload.get("current_content", ""),
                summary_text=payload.get("summary_text", ""),
                selected_skills=payload.get("selected_skills", []),
                sourcebook_context=payload.get("sourcebook_context", ""),
                cancel_event=cancel_event,
                require_remote=True,
            ))

        chunks = await loop.run_in_executor(None, _stream)

        accumulated = ""
        len(chunks) if chunks else 1
        for _i, chunk in enumerate(chunks):
            if cancel_event.is_set():
                _try_create_generation_snapshot(
                    workspace_db, chapter_id,
                    mode=mode, payload=payload,
                    accumulated_text=accumulated, status="cancelled", task_id=task_id,
                )
                await manager.send(client_id, {"type": "result", "task_id": task_id, "payload": {"status": "cancelled"}})
                return
            accumulated += chunk
            await manager.send(client_id, {
                "type": "chunk", "task_id": task_id,
                "payload": {"text": chunk, "accumulated": accumulated},
            })

        if user:
            input_text = "\n".join(
                str(payload.get(key) or "")
                for key in ("book_title", "chapter_title", "outline", "current_content", "summary_text", "sourcebook_context")
            )
            record_ai_usage(
                store=store,
                user=user,
                feature=f"generation_{mode}",
                ai_service=ai_service,
                fallback_input=input_text,
                fallback_output=accumulated,
            )
        _try_create_generation_snapshot(
            workspace_db, chapter_id,
            mode=mode, payload=payload,
            accumulated_text=accumulated, status="success", task_id=task_id,
        )
        await manager.send(client_id, {
            "type": "result", "task_id": task_id,
            "payload": {"text": accumulated, "status": "success", "mode": mode},
        })

    except asyncio.CancelledError:
        cancel_event.set()
        raise
    except Exception:
        if cancel_event.is_set():
            _try_create_generation_snapshot(
                workspace_db, chapter_id,
                mode=mode, payload=payload,
                accumulated_text=accumulated, status="cancelled", task_id=task_id,
            )
            await manager.send(client_id, {"type": "result", "task_id": task_id, "payload": {"status": "cancelled"}})
        else:
            logger.exception("Generation task failed: mode=%s chapter_id=%s", mode, chapter_id)
            _try_create_generation_snapshot(
                workspace_db, chapter_id,
                mode=mode, payload=payload,
                accumulated_text=accumulated, status="failed", task_id=task_id,
            )
            await manager.send(client_id, {
                "type": "error", "task_id": task_id,
                "payload": {"message": f"{label}失败，请稍后重试"},
            })
    finally:
        if _generation_cancel_events.get(client_id) is cancel_event:
            _generation_cancel_events.pop(client_id, None)
