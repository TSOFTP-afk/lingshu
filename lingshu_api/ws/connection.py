"""
WebSocket 基础设施 — 连接管理、Ping/Pong 保活、消息路由。

提供统一的 WebSocket 端点注册机制，各业务模块（生成/审查/分析/对话）
通过 register_ws_handler() 注册各自的处理器。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("lingshu.ws")

PING_INTERVAL_SEC = 25
PING_TIMEOUT_SEC = 10
PONG_TIMEOUT_SEC = 120  # 超过此时间未收到 pong 则视为僵尸连接（V3 分析期间可能延迟回复）

# 消息处理器类型
MessageHandler = Callable[[dict[str, Any], WebSocket, str], Awaitable[None]]


class Connection:
    """单个 WebSocket 连接封装。"""

    def __init__(self, ws: WebSocket, client_id: str | None = None) -> None:
        self.ws = ws
        self.client_id = client_id or str(uuid.uuid4())[:8]
        self.last_pong: float = asyncio.get_event_loop().time()
        self.is_alive = True
        self.user: dict[str, Any] | None = None
        self.analysis_active: bool = False  # V3 分析进行中时放宽 pong 超时


class ConnectionManager:
    """WebSocket 连接管理器 — 单例。"""

    MAX_WS_MESSAGE_SIZE = 1_000_000  # 1MB
    MAX_CONNECTS_PER_IP_PER_MINUTE = int(os.environ.get("WS_MAX_CONNECTS_PER_IP_PER_MINUTE", "120"))

    def __init__(self) -> None:
        self.connections: dict[str, Connection] = {}
        self._handlers: dict[str, MessageHandler] = {}
        self.max_connections: int = int(os.environ.get("MAX_WS_CONNECTIONS", "1000"))
        self._ip_bans: dict[str, float] = {}  # ip_address -> ban_expiry_timestamp
        self._ip_failures: dict[str, int] = {}  # ip_address -> failure_count
        self._ip_connect_times: dict[str, list[float]] = {}  # ip_address -> [timestamps]

    def register_handler(self, msg_type: str, handler: MessageHandler) -> None:
        """注册消息类型处理器。"""
        self._handlers[msg_type] = handler

    def _get_client_ip(self, ws: WebSocket) -> str:
        """Extract client IP from WebSocket connection."""
        forwarded_for = ws.headers.get("x-forwarded-for")
        if forwarded_for:
            first_ip = forwarded_for.split(",", 1)[0].strip()
            if first_ip:
                return first_ip
        real_ip = ws.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        client = ws.client
        if client:
            return client[0]
        return "unknown"

    def is_ip_banned(self, ip: str) -> bool:
        """Check if an IP address is currently banned."""
        import time
        expiry = self._ip_bans.get(ip)
        if expiry is None:
            return False
        if time.time() > expiry:
            del self._ip_bans[ip]
            self._ip_failures.pop(ip, None)
            return False
        return True

    def record_auth_failure(self, ip: str) -> int:
        """Record an authentication failure for an IP. Returns total failure count."""
        import time
        count = self._ip_failures.get(ip, 0) + 1
        self._ip_failures[ip] = count
        ban_threshold = int(os.environ.get("WS_AUTH_FAILURE_BAN_THRESHOLD", "0"))
        if ban_threshold > 0 and count >= ban_threshold:
            ban_seconds = int(os.environ.get("WS_AUTH_FAILURE_BAN_SECONDS", "900"))
            self._ip_bans[ip] = time.time() + ban_seconds
        return count

    def clear_auth_failures(self, ip: str) -> None:
        """Clear authentication failures for an IP after successful auth."""
        self._ip_failures.pop(ip, None)

    def _check_ip_connect_rate(self, ip: str) -> bool:
        """检查 IP 连接频率是否超限。返回 True 表示允许连接。"""
        now = time.time()
        timestamps = self._ip_connect_times.get(ip, [])
        # 清理超过 60 秒的记录
        cutoff = now - 60.0
        timestamps = [t for t in timestamps if t > cutoff]
        if len(timestamps) >= self.MAX_CONNECTS_PER_IP_PER_MINUTE:
            self._ip_connect_times[ip] = timestamps
            return False
        timestamps.append(now)
        self._ip_connect_times[ip] = timestamps
        return True

    async def connect(self, ws: WebSocket, client_id: str | None = None) -> Connection:
        """接受 WebSocket 连接并注册。"""
        # Check IP ban first
        ip = self._get_client_ip(ws)
        if self.is_ip_banned(ip):
            await ws.accept()
            await ws.close(code=4003, reason="IP已被临时封禁")
            conn = Connection(ws, client_id)
            conn.is_alive = False
            return conn
        # Check IP connect rate limit
        if not self._check_ip_connect_rate(ip):
            await ws.accept()
            await ws.send_json({"type": "error", "payload": {"message": "连接过于频繁，请稍后重试"}})
            await ws.close(code=4004, reason="连接频率超限")
            conn = Connection(ws, client_id)
            conn.is_alive = False
            return conn
        if len(self.connections) >= self.max_connections:
            await ws.accept()
            await ws.send_json({"type": "error", "payload": {"message": "连接数已达上限，请稍后重试"}})
            await ws.close(code=1013, reason="连接数已达上限")
            conn = Connection(ws, client_id)
            conn.is_alive = False
            return conn
        await ws.accept()
        conn = Connection(ws, client_id)
        self.connections[conn.client_id] = conn
        logger.info("WS 连接: %s (共 %d 个)", conn.client_id, len(self.connections))
        return conn

    def disconnect(self, client_id: str) -> None:
        """移除连接。"""
        self.connections.pop(client_id, None)
        logger.info("WS 断开: %s (剩余 %d 个)", client_id, len(self.connections))

    async def send(self, client_id: str, message: dict[str, Any]) -> bool:
        """向指定客户端发送 JSON 消息。"""
        conn = self.connections.get(client_id)
        if not conn or not conn.is_alive:
            return False
        try:
            await conn.ws.send_json(message)
            return True
        except Exception:
            conn.is_alive = False
            return False

    async def broadcast(self, message: dict[str, Any]) -> None:
        """向所有客户端广播消息。"""
        for conn in list(self.connections.values()):
            if conn.is_alive:
                try:
                    await conn.ws.send_json(message)
                except Exception:
                    conn.is_alive = False

    async def dispatch(self, raw: dict[str, Any], ws: WebSocket, client_id: str) -> None:
        """将消息分发给已注册的处理器。"""
        msg_type = raw.get("type", "")
        handler = self._handlers.get(msg_type)
        if handler:
            await handler(raw, ws, client_id)
        else:
            await self.send(client_id, {
                "type": "error",
                "task_id": raw.get("task_id", ""),
                "payload": {"message": f"未知消息类型: {msg_type}"},
            })

    async def ping_loop(self) -> None:
        """全局心跳循环 — 在后台任务中运行。"""
        while True:
            await asyncio.sleep(PING_INTERVAL_SEC)
            now = asyncio.get_event_loop().time()
            dead: list[str] = []
            for cid, conn in list(self.connections.items()):
                if not conn.is_alive:
                    dead.append(cid)
                    continue
                # V3 分析进行中时使用 10 分钟超时，避免 AI 长调用被误判僵尸
                effective_timeout = 600 if conn.analysis_active else PONG_TIMEOUT_SEC
                if now - conn.last_pong > effective_timeout:
                    logger.warning("WS 僵尸连接: %s (pong 超时 %.0fs, analysis_active=%s)", cid, now - conn.last_pong, conn.analysis_active)
                    conn.is_alive = False
                    dead.append(cid)
                    continue
                try:
                    await conn.ws.send_json({"type": "ping"})
                except Exception:
                    conn.is_alive = False
                    dead.append(cid)
            for cid in dead:
                self.disconnect(cid)


# 全局单例
_manager: ConnectionManager | None = None


def get_ws_manager() -> ConnectionManager:
    """获取全局 WebSocket 连接管理器。"""
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager


async def authenticate_ws(
    ws: WebSocket,
    client_id: str | None = None,
    *,
    error_type: str = "error",
) -> Connection | None:
    """
    通用 WebSocket 认证协程。

    接受连接并完成认证，返回已认证的 Connection 对象。
    认证失败时返回 None（已发送错误消息并断开连接）。

    使用方式（在 FastAPI 路由中）:
        conn = await authenticate_ws(ws)
        if conn is None:
            return
    """
    manager = get_ws_manager()
    ip = manager._get_client_ip(ws)
    conn = await manager.connect(ws, client_id)

    if not conn.is_alive:
        return None

    try:
        auth_text = await ws.receive_text()
        if len(auth_text) > ConnectionManager.MAX_WS_MESSAGE_SIZE:
            await manager.send(conn.client_id, {"type": error_type, "payload": {"message": "消息大小超过限制"}})
            with contextlib.suppress(Exception):
                await ws.close(code=1009, reason="消息过大")
            return None
        try:
            auth_msg = json.loads(auth_text)
        except json.JSONDecodeError:
            await manager.send(conn.client_id, {"type": error_type, "payload": {"message": "无效的 JSON 格式"}})
            manager.disconnect(conn.client_id)
            manager.record_auth_failure(ip)
            if manager.is_ip_banned(ip):
                with contextlib.suppress(Exception):
                    await ws.close(code=4001, reason="认证失败次数过多，IP已被临时封禁")
                return None
            return None

        if auth_msg.get("type") != "auth":
            await manager.send(conn.client_id, {"type": error_type, "payload": {"message": "请先认证"}})
            manager.disconnect(conn.client_id)
            manager.record_auth_failure(ip)
            if manager.is_ip_banned(ip):
                with contextlib.suppress(Exception):
                    await ws.close(code=4001, reason="认证失败次数过多，IP已被临时封禁")
                return None
            return None

        token = str(auth_msg.get("payload", {}).get("token", ""))
        if not token:
            await manager.send(conn.client_id, {"type": error_type, "payload": {"message": "缺少认证令牌"}})
            manager.disconnect(conn.client_id)
            manager.record_auth_failure(ip)
            if manager.is_ip_banned(ip):
                with contextlib.suppress(Exception):
                    await ws.close(code=4001, reason="认证失败次数过多，IP已被临时封禁")
                return None
            return None

        try:
            user = await asyncio.to_thread(ws.app.state.store.get_user_by_token, token)
        except Exception:
            user = None

        if not user:
            await manager.send(conn.client_id, {"type": error_type, "payload": {"message": "认证失败"}})
            manager.disconnect(conn.client_id)
            manager.record_auth_failure(ip)
            if manager.is_ip_banned(ip):
                with contextlib.suppress(Exception):
                    await ws.close(code=4001, reason="认证失败次数过多，IP已被临时封禁")
                return None
            return None

        conn.user = dict(user)
        manager.clear_auth_failures(ip)
        await manager.send(conn.client_id, {"type": "auth_ok", "payload": {"username": user.get("username", "")}})
        return conn
    except Exception:
        manager.disconnect(conn.client_id)
        return None


async def handle_ws_connection(ws: WebSocket, client_id: str | None = None) -> None:
    """
    通用 WebSocket 连接处理协程（含认证）。

    使用方式（在 FastAPI 路由中）:
        @router.websocket("/ws/generation")
        async def ws_generation(ws: WebSocket):
            await handle_ws_connection(ws)
    """
    conn = await authenticate_ws(ws, client_id)
    if conn is None:
        return

    manager = get_ws_manager()
    try:
        # 正常消息循环
        while True:
            raw_text = await ws.receive_text()
            if len(raw_text) > ConnectionManager.MAX_WS_MESSAGE_SIZE:
                await manager.send(conn.client_id, {"type": "error", "payload": {"message": "消息大小超过限制"}})
                await ws.close(code=1009, reason="消息过大")
                break
            try:
                message = json.loads(raw_text)
            except json.JSONDecodeError:
                await manager.send(conn.client_id, {"type": "error", "payload": {"message": "无效的 JSON 格式"}})
                continue
            # 处理 pong 响应，更新 last_pong 时间
            if message.get("type") == "pong":
                conn.last_pong = asyncio.get_event_loop().time()
                continue
            await manager.dispatch(message, ws, conn.client_id)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WS 异常: %s", conn.client_id)
    finally:
        manager.disconnect(conn.client_id)


def ws_message(
    msg_type: str = "result",
    task_id: str = "",
    **payload: Any,
) -> dict[str, Any]:
    """构建标准 WebSocket 消息。"""
    return {"type": msg_type, "task_id": task_id, "payload": payload}
