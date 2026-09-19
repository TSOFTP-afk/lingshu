"""
AI 审查 WebSocket — 对应 Qt app_review_tasks.py
协议:
  请求: {"type":"review","task_id":"uuid","payload":{"book_id":...,"chapter_id":...,"content":"..."}}
  进度: {"type":"progress","task_id":"uuid","payload":{"stage":"auditor|reviser","percent":50}}
  完成: {"type":"result","task_id":"uuid","payload":{"findings":[...],"score":85}}
"""
from __future__ import annotations

import asyncio
import json
import logging
from threading import Event

from fastapi import APIRouter, HTTPException, WebSocket

from lingshu_api.dependencies import check_chapter_owner
from lingshu_api.services.db_bridge import get_workspace_db
from lingshu_api.ws.connection import ConnectionManager, authenticate_ws, get_ws_manager
from lingshu_api.ws.generation import _create_ai_service, _workspace_db_from_app
from lingshu_api.ws.tasks import get_ws_task_registry

logger = logging.getLogger(__name__)
router = APIRouter()

_active_reviews: dict[str, Event] = {}


@router.websocket("/ws/review")
async def ws_review(ws: WebSocket):
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
                active = _active_reviews.get(client_id)
                if active:
                    active.set()
                get_ws_task_registry().cancel_client(client_id)
                await manager.send(client_id, {"type": "result", "task_id": msg.get("task_id", ""), "payload": {"status": "cancelled"}})
                continue

            if msg.get("type") != "review":
                await manager.send(client_id, {"type": "error", "task_id": msg.get("task_id", ""), "payload": {"message": f"未知消息类型: {msg.get('type')}"}})
                continue

            task_id = msg.get("task_id", "")
            payload = msg.get("payload", {})
            chapter_id = int(payload.get("chapter_id", 0))
            book_id = int(payload.get("book_id", 0))
            content = payload.get("content", "")

            if not chapter_id or not content:
                await manager.send(client_id, {"type": "error", "task_id": task_id, "payload": {"message": "缺少 chapter_id 或 content"}})
                continue

            # 所有权校验（修复 V6 IDOR：之前仅当 book_id 存在时校验，
            # 攻击者只传 chapter_id 可绕过并读取他人章节内容）。
            # chapter_id 已必填，通过它反查 book_id 并校验归属。
            if conn.user and workspace_db:
                try:
                    check_chapter_owner(workspace_db, chapter_id, dict(conn.user))
                except HTTPException as exc:
                    await manager.send(client_id, {
                        "type": "error",
                        "task_id": task_id,
                        "payload": {"message": str(getattr(exc, "detail", "") or "无权操作该书籍")},
                    })
                    continue

            cancel_event = Event()
            _active_reviews[client_id] = cancel_event
            try:
                get_ws_task_registry().create(
                    client_id,
                    _run_review(
                        manager,
                        client_id,
                        task_id,
                        book_id,
                        chapter_id,
                        content,
                        payload.get("sourcebook_context", ""),
                        cancel_event,
                        workspace_db,
                    ),
                    name=f"ws-review:{client_id}:{task_id}",
                )
            except RuntimeError:
                await manager.send(client_id, {"type": "error", "task_id": task_id, "payload": {"message": "并发任务数已达上限，请等待当前任务完成"}})

    except Exception:
        pass
    finally:
        active = _active_reviews.pop(client_id, None)
        if active:
            active.set()
        await get_ws_task_registry().cancel_client_and_wait(client_id)
        manager.disconnect(client_id)


async def _run_review(manager, client_id, task_id, book_id, chapter_id, content, sourcebook_context, cancel_event, workspace_db=None):
    db = workspace_db or get_workspace_db()
    conn = manager.connections.get(client_id)
    user_id = int(conn.user["id"]) if conn and conn.user else None
    ai_service = _create_ai_service("review", workspace_db=db, user_id=user_id)
    chapter = db.get_chapter(chapter_id)

    try:
        await manager.send(client_id, {
            "type": "progress", "task_id": task_id,
            "payload": {"stage": "auditor", "percent": 0, "message": "审查中..."},
        })

        loop = asyncio.get_event_loop()

        def _do_review():
            return ai_service.review_chapter(
                book_title=chapter.get("title", "") if chapter else "",
                chapter_title=chapter.get("title", "") if chapter else "",
                outline=chapter.get("outline", "") if chapter else "",
                content=content,
                sourcebook_context=sourcebook_context,
                require_remote=True,
            )

        result = await loop.run_in_executor(None, _do_review)

        findings = result if isinstance(result, list) else [result] if result else []
        score = _extract_score(findings)

        await manager.send(client_id, {
            "type": "result", "task_id": task_id,
            "payload": {"status": "ok", "findings": findings, "score": score},
        })

    except asyncio.CancelledError:
        cancel_event.set()
        raise
    except Exception:
        if cancel_event.is_set():
            await manager.send(client_id, {"type": "result", "task_id": task_id, "payload": {"status": "cancelled"}})
        else:
            await manager.send(client_id, {
                "type": "error", "task_id": task_id,
                "payload": {"message": "审查失败，请稍后重试"},
            })
    finally:
        if _active_reviews.get(client_id) is cancel_event:
            _active_reviews.pop(client_id, None)


def _extract_score(findings):
    """从审查结果中提取评分。"""
    if not findings:
        return 0
    if isinstance(findings, dict):
        return int(findings.get("score", findings.get("overall_score", 0)))
    scores = [int(f.get("score", 0) or 0) for f in findings if isinstance(f, dict)]
    return int(sum(scores) / len(scores)) if scores else 0
