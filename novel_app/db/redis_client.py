"""Redis 客户端单例与健康检查 —— hybrid-database-architecture spec Task 4.2 实现。

设计要点：
1. **单例模式**：全局共享一个 Redis 连接池，避免重复创建
2. **优雅降级**：Redis 不可用时返回 None，调用方据此走无缓存路径（不抛异常）
3. **环境变量配置**：REDIS_URL 优先，否则用 REDIS_HOST + REDIS_PORT + REDIS_DB
4. **健康检查**：ping() 方法用于 /api/health 端点显示 Redis 状态
5. **线程安全**：连接池本身线程安全，单例创建用锁保护

使用方式：
    from novel_app.db.redis_client import get_redis_client, is_redis_available
    client = get_redis_client()  # 返回 redis.Redis 或 None
    if client is not None:
        client.set("key", "value", ex=300)
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

# Redis 默认配置（可通过环境变量覆盖）
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 6379
_DEFAULT_DB = 0
_DEFAULT_PASSWORD = ""

# 单例状态
_client_lock = threading.Lock()
_client: Any | None = None  # redis.Redis | None
_client_initialized: bool = False


def _create_client() -> Any | None:
    """创建 Redis 客户端实例。失败时返回 None 并记日志。"""
    try:
        import redis
    except ImportError:
        logger.info("redis 包未安装，缓存功能禁用")
        return None

    # 优先用 REDIS_URL（支持 rediss:// 等完整 URL）
    redis_url = os.environ.get("REDIS_URL", "").strip()
    if redis_url:
        try:
            client = redis.Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                retry_on_timeout=True,
            )
            client.ping()
            logger.info("Redis 客户端已连接（REDIS_URL=%s）", _mask_url(redis_url))
            return client
        except Exception as exc:
            logger.warning("Redis 连接失败（REDIS_URL=%s）: %s", _mask_url(redis_url), exc)
            return None

    # 否则用分离的 host/port/db/password
    host = os.environ.get("REDIS_HOST", _DEFAULT_HOST)
    port = int(os.environ.get("REDIS_PORT", _DEFAULT_PORT))
    db = int(os.environ.get("REDIS_DB", _DEFAULT_DB))
    password = os.environ.get("REDIS_PASSWORD", _DEFAULT_PASSWORD) or None

    try:
        client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry_on_timeout=True,
        )
        client.ping()
        logger.info("Redis 客户端已连接（host=%s port=%d db=%d）", host, port, db)
        return client
    except Exception as exc:
        logger.warning("Redis 连接失败（host=%s port=%d db=%d）: %s", host, port, db, exc)
        return None


def _mask_url(url: str) -> str:
    """遮蔽 URL 中的密码部分，避免日志泄露。"""
    if "://" in url and "@" in url:
        scheme = url.split("://")[0]
        rest = url.split("://", 1)[1]
        if "@" in rest:
            creds, host_part = rest.rsplit("@", 1)
            return f"{scheme}://***@{host_part}"
    return url


def get_redis_client() -> Any | None:
    """获取 Redis 客户端单例。

    首次调用时尝试连接，失败则缓存 None 避免重复尝试。
    Redis 不可用时返回 None，调用方应据此走无缓存路径。

    返回 redis.Redis 实例（已 ping 验证）或 None。
    """
    global _client, _client_initialized
    if _client_initialized:
        return _client
    with _client_lock:
        if _client_initialized:
            return _client
        _client = _create_client()
        _client_initialized = True
        return _client


def is_redis_available() -> bool:
    """检查 Redis 是否可用（已连接且 ping 成功）。"""
    client = get_redis_client()
    if client is None:
        return False
    try:
        client.ping()
        return True
    except Exception:
        return False


def reset_redis_client() -> None:
    """重置单例状态（主要用于测试）。

    下次 get_redis_client() 会重新尝试连接。
    """
    global _client, _client_initialized
    with _client_lock:
        if _client is not None:
            with contextlib.suppress(Exception):
                _client.close()
        _client = None
        _client_initialized = False


def ping_redis() -> dict[str, Any]:
    """健康检查：返回 Redis 连接状态信息（供 /api/health 使用）。

    返回 {"status": "ok"|"down", "latency_ms": float|None}
    """
    client = get_redis_client()
    if client is None:
        return {"status": "down", "latency_ms": None}
    try:
        import time
        start = time.monotonic()
        client.ping()
        latency_ms = (time.monotonic() - start) * 1000
        return {"status": "ok", "latency_ms": round(latency_ms, 2)}
    except Exception as exc:
        logger.warning("Redis ping 失败: %s", exc)
        return {"status": "down", "latency_ms": None, "error": str(exc)}
