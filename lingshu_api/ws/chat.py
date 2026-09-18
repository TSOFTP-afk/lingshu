"""
AI 对话 WebSocket。

协议:
  请求: {"type":"chat","task_id":"uuid","payload":{"messages":[{"role":"user|assistant","content":"..."}]}}
  文本: {"type":"chunk","task_id":"uuid","payload":{"text":"流式 token"}}
  完成: {"type":"result","task_id":"uuid","payload":{"text":"完整回复","status":"ok"}}
"""
from __future__ import annotations

import asyncio
import json
import logging
from threading import Event, Thread
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket

from lingshu_api.dependencies import check_book_owner, check_chapter_owner
from lingshu_api.services.db_bridge import WorkspaceDB, get_workspace_db
from lingshu_api.services.usage_recorder import record_ai_usage
from lingshu_api.ws.connection import ConnectionManager, authenticate_ws, get_ws_manager
from lingshu_api.ws.generation import _create_ai_service, _workspace_db_from_app
from lingshu_api.ws.tasks import get_ws_task_registry

logger = logging.getLogger(__name__)
router = APIRouter()

CHAT_SYSTEM_PROMPT = """#### 定位
- 智能助手名称：灵枢小说创作工作台 AI 对话助手
- 主要任务：结合当前书籍数据，为作者提供剧情讨论、设定问答、人物推演、正文修改建议和创作决策支持。

#### 能力
- 上下文整合：优先读取当前作品、书籍级设定、世界观、人物卡、当前章节大纲和正文。
- 写作协作：可以做剧情推演、结构建议、文本润色、人物关系分析和问题排查。
- 冲突识别：当资料互相矛盾时，指出冲突来源，并以用户当前明确指令为优先。

#### 使用说明
- 回答要直接、自然、便于作者继续操作。
- 需要改写时，给出可复制的片段或清晰修改方案；不要擅自覆盖用户正文。
- 不确定的信息要标注为推断，不要把猜测写成既定事实。
- 用户要求角色代入时，遵守所选人物卡、关系状态和剧情进度。"""

CHARACTER_CHAT_PROMPT_TEMPLATE = """#### 定位
- 当前模式：角色对话
- 你正在代入书中人物：{name}
- 人物定位：{role}

#### 人物资料
{profile}
{self_line}

#### 使用说明
- 使用该角色的第一人称口吻回答作者。
- 只知道人物在当前剧情和设定中合理知道的内容。
- 结合上方作品、章节和人物关系上下文说话。
- 不要跳出角色解释自己是 AI；除非作者明确要求写作建议。
- 资料不足时，可以用角色视角表达迟疑，不要硬编书中没有的事实。"""

_active_chats: dict[str, Event] = {}



@router.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
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

            task_id = str(msg.get("task_id", "") or "")
            if msg.get("type") == "cancel":
                active = _active_chats.get(client_id)
                if active:
                    active.set()
                get_ws_task_registry().cancel_client(client_id)
                await manager.send(client_id, {"type": "result", "task_id": task_id, "payload": {"status": "cancelled"}})
                continue

            if msg.get("type") != "chat":
                await manager.send(client_id, {
                    "type": "error",
                    "task_id": task_id,
                    "payload": {"message": f"未知消息类型: {msg.get('type')}"},
                })
                continue

            payload = msg.get("payload", {}) if isinstance(msg.get("payload"), dict) else {}
            book_id = _to_int(payload.get("book_id"))
            chapter_id = _to_int(payload.get("chapter_id"))
            # 所有权校验（修复 V6 IDOR：之前仅当 book_id 存在时校验，
            # 攻击者只传 chapter_id 可绕过并读取他人章节内容）
            if conn.user and (book_id or chapter_id) and workspace_db:
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
            _active_chats[client_id] = cancel_event
            try:
                get_ws_task_registry().create(
                    client_id,
                    _run_chat(ws.app.state.store, manager, client_id, task_id, payload, cancel_event, workspace_db),
                    name=f"ws-chat:{client_id}:{task_id}",
                )
            except RuntimeError:
                await manager.send(client_id, {
                    "type": "error",
                    "task_id": task_id,
                    "payload": {"message": "并发任务数已达上限，请等待当前任务完成"},
                })

    except Exception:
        pass
    finally:
        active = _active_chats.pop(client_id, None)
        if active:
            active.set()
        await get_ws_task_registry().cancel_client_and_wait(client_id)
        manager.disconnect(client_id)


async def _run_chat(
    store,
    manager,
    client_id: str,
    task_id: str,
    payload: dict[str, Any],
    cancel_event: Event,
    workspace_db: WorkspaceDB | None = None,
) -> None:
    conn = manager.connections.get(client_id)
    user_id = int(conn.user["id"]) if conn and conn.user else None
    ai_service = _create_ai_service("chat", workspace_db=workspace_db, user_id=user_id)
    try:
        await manager.send(client_id, {
            "type": "progress",
            "task_id": task_id,
            "payload": {"stage": "thinking", "percent": 0, "message": "AI 思考中..."},
        })

        messages = _build_chat_messages(payload, workspace_db=workspace_db)
        accumulated = ""
        async for chunk in _stream_chat(ai_service, messages, cancel_event):
            if cancel_event.is_set():
                await manager.send(client_id, {"type": "result", "task_id": task_id, "payload": {"status": "cancelled"}})
                return
            accumulated += chunk
            await manager.send(client_id, {"type": "chunk", "task_id": task_id, "payload": {"text": chunk}})

        await manager.send(client_id, {
            "type": "result",
            "task_id": task_id,
            "payload": {"text": accumulated, "status": "ok"},
        })
        conn = manager.connections.get(client_id)
        user = dict(conn.user) if conn and conn.user else None
        if user:
            input_text = "\n".join(str(item.get("content", "")) for item in messages if isinstance(item, dict))
            record_ai_usage(
                store=store,
                user=user,
                feature="chat",
                ai_service=ai_service,
                fallback_input=input_text,
                fallback_output=accumulated,
            )

    except asyncio.CancelledError:
        cancel_event.set()
        raise
    except Exception as exc:  # noqa: BLE001
        if cancel_event.is_set():
            await manager.send(client_id, {"type": "result", "task_id": task_id, "payload": {"status": "cancelled"}})
        else:
            await manager.send(client_id, {
                "type": "error",
                "task_id": task_id,
                "payload": {"message": "对话失败，请稍后重试"},
            })
    finally:
        if _active_chats.get(client_id) is cancel_event:
            _active_chats.pop(client_id, None)


async def _stream_chat(ai_service, messages: list[dict[str, str]], cancel_event: Event):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    def _worker() -> None:
        try:
            for chunk in ai_service.stream_chat(messages, cancel_event, require_remote=True):
                if cancel_event.is_set():
                    break
                loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
            loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
        except Exception as exc:  # noqa: BLE001
            loop.call_soon_threadsafe(queue.put_nowait, ("error", exc))

    Thread(target=_worker, daemon=True).start()
    while True:
        kind, value = await queue.get()
        if kind == "chunk":
            yield str(value)
        elif kind == "error":
            raise value
        else:
            break


def _build_chat_messages(
    payload: dict[str, Any],
    workspace_db: WorkspaceDB | None = None,
) -> list[dict[str, str]]:
    history = _normalize_history(payload.get("messages", []))
    latest_user_message = _latest_user_message(history)
    context = _build_chat_context_prompt(
        workspace_db or get_workspace_db(),
        book_id=_to_int(payload.get("book_id")),
        chapter_id=_to_int(payload.get("chapter_id")),
        ai_character_id=_to_int(payload.get("ai_character_id")),
        self_character_id=_to_int(payload.get("self_character_id")),
        latest_user_message=latest_user_message,
        current_content=str(payload.get("current_content") or ""),
    ).strip()
    if context:
        return [{"role": "system", "content": context}, *history[-12:]]
    return history[-12:]


def _normalize_history(messages: Any) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    if not isinstance(messages, list):
        return normalized
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user").strip()
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "").strip()
        if content:
            normalized.append({"role": role, "content": content})
    return normalized


def _latest_user_message(messages: list[dict[str, str]]) -> str:
    for item in reversed(messages):
        if item.get("role") == "user":
            return str(item.get("content") or "")
    return ""


def _build_chat_context_prompt(
    db: WorkspaceDB,
    *,
    book_id: int | None = None,
    chapter_id: int | None = None,
    ai_character_id: int | None = None,
    self_character_id: int | None = None,
    latest_user_message: str = "",
    current_content: str = "",
) -> str:
    lines = [CHAT_SYSTEM_PROMPT]
    latest_user_message = str(latest_user_message or "").strip()
    if latest_user_message:
        lines.append(f"【当前用户请求】\n{latest_user_message[:1200]}")

    book = db.get_book(book_id) if book_id else None
    if book:
        lines.append(f"作品名称：{book.get('title', '')}")

    chapter = db.get_chapter(chapter_id) if chapter_id else None
    if chapter:
        volume_id = _to_int(chapter.get("volume_id"))
        if volume_id:
            volume = db.get_volume(volume_id)
            if volume:
                lines.append(f"当前卷：{volume.get('title', '')}")
        lines.append(f"当前章节：{chapter.get('title', '')}")
        outline = str(chapter.get("outline") or "").strip()
        content = str(current_content or chapter.get("content") or "").strip()
        if outline:
            lines.append(f"章节大纲：{outline[:1200]}")
        if content:
            lines.append(f"当前正文节选：{content[:2200]}")

    if book:
        book_id_int = int(book["id"])
        reference_context = _build_reference_context(db, book_id_int)
        if reference_context:
            lines.append(reference_context)
        book_context = _build_book_chat_context(db, book_id_int, max_chars=7000)
        if book_context:
            lines.append(book_context)

    ai_character = _get_character_for_book(db, ai_character_id, book_id)
    self_character = _get_character_for_book(db, self_character_id, book_id)
    if ai_character:
        lines.append(_build_character_chat_prompt(ai_character, self_character))

    if book:
        skills = _build_skill_context(db, int(book["id"]))
        if skills:
            lines.append(skills)

    return "\n\n".join(line for line in lines if str(line).strip())


def _build_book_chat_context(db: WorkspaceDB, book_id: int, max_chars: int = 7000) -> str:
    try:
        export_data = db.db.get_book_export_data(book_id)
    except Exception:  # noqa: BLE001
        return ""
    pieces: list[str] = ["【全书上下文】"]
    book = export_data.get("book") or {}
    outline = str(book.get("outline_text") or "").strip()
    if outline:
        pieces.append(f"书籍全局描述：{outline[:2600]}")

    character_lines: list[str] = []
    for item in export_data.get("characters", [])[:40]:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        role = str(item.get("role") or "").strip() or "未设定"
        profile = str(item.get("profile_text") or "").strip()
        character_lines.append(f"- {name}（{role}）：{profile[:500]}")
    if character_lines:
        pieces.append("人物设定：\n" + "\n".join(character_lines))

    chapter_blocks: list[str] = []
    used = 0
    for chapter in export_data.get("chapters", []):
        title = str(chapter.get("title") or "").strip()
        outline = str(chapter.get("outline") or "").strip()
        summary = str(chapter.get("summary_text") or "").strip()
        content = str(chapter.get("content") or "").strip()
        body = summary or content[:1800]
        block = f"--- {title} ---\n大纲：{outline[:600]}\n正文/摘要：{body[:1800]}"
        if used + len(block) > max_chars:
            break
        chapter_blocks.append(block)
        used += len(block)
    if chapter_blocks:
        pieces.append("全书正文与章节摘要节选：\n" + "\n\n".join(chapter_blocks))
    return "\n\n".join(pieces)


def _build_character_chat_prompt(
    ai_character: dict[str, Any],
    self_character: dict[str, Any] | None = None,
) -> str:
    name = str(ai_character.get("name") or "").strip() or "未命名角色"
    role = str(ai_character.get("role") or "").strip() or "未设定"
    profile = str(ai_character.get("profile_text") or "").strip()
    self_name = str((self_character or {}).get("name") or "").strip()
    self_line = f"正在与你对话的人是「{self_name}」，请以「{name}」的视角和口吻回应。" if self_name else ""
    return CHARACTER_CHAT_PROMPT_TEMPLATE.format(
        name=name,
        role=role,
        profile=profile or "暂无明确设定，请从全书上下文推断但不要编造关键事实。",
        self_name=self_name,
        self_line=self_line,
    )


def _build_reference_context(db: WorkspaceDB, book_id: int) -> str:
    try:
        return str(db.db.build_book_reference_context(book_id, max_chars=3000) or "")
    except Exception:  # noqa: BLE001
        return ""


def _build_skill_context(db: WorkspaceDB, book_id: int) -> str:
    try:
        rows = list(db.db.list_bound_skills_for_book(book_id)) + list(db.db.list_bound_skills_for_global())
    except Exception:  # noqa: BLE001
        return ""
    seen: set[int] = set()
    lines: list[str] = []
    for row in rows:
        skill_id = int(row["id"])
        if skill_id in seen:
            continue
        seen.add(skill_id)
        name = str(row["name"] or "").strip()
        instruction = str(row["instruction_text"] or row["summary"] or "").strip()
        if name and instruction:
            lines.append(f"- {name}：{instruction[:180]}")
        if len(lines) >= 10:
            break
    return "启用 Skills：\n" + "\n".join(lines) if lines else ""


def _get_character_for_book(db: WorkspaceDB, character_id: int | None, book_id: int | None) -> dict[str, Any] | None:
    if not character_id:
        return None
    character = db.get_character(character_id)
    if not character:
        return None
    if book_id and int(character.get("book_id") or 0) != int(book_id):
        return None
    return character


def _to_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
