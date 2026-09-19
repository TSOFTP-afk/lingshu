"""
WebSocket 认证失败封禁回归测试（安全修复 C）。

病灶：ConnectionManager.record_auth_failure 的封禁阈值
`WS_AUTH_FAILURE_BAN_THRESHOLD` 默认为 0（不封禁），token 可对 /ws/* 无限试错。

修复后语义：
- 默认阈值为 5：连续失败 5 次后 IP 被封禁（默认 900 秒）；
- 保留环境变量覆盖（沿用现有 env 名 WS_AUTH_FAILURE_BAN_THRESHOLD / WS_AUTH_FAILURE_BAN_SECONDS）；
- 成功认证后失败计数重置（clear_auth_failures）；
- 封禁窗口过期后自动解封且计数清零。
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "workspace-data"
    monkeypatch.setenv("SIMPLE_AI_NOVEL_DATA_DIR", str(data_dir))

    db_bridge = importlib.import_module("lingshu_api.services.db_bridge")
    db_bridge.reset_default_workspace_db()

    from lingshu_api.main import create_app

    app = create_app(tmp_path / "bookstore.db")
    with TestClient(app) as test_client:
        store = app.state.store
        token = store.login_user("testuser", "testpass123")
        if not token:
            store.create_user("testuser", "testpass123")
            token = store.login_user("testuser", "testpass123")
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client

    db_bridge.reset_default_workspace_db()


@pytest.fixture()
def manager():
    """独立的 ConnectionManager 实例（避免污染全局单例状态）。"""
    from lingshu_api.ws.connection import ConnectionManager

    return ConnectionManager()


def test_ban_threshold_default_is_5(monkeypatch) -> None:
    """默认（env 未设置时）连续失败 5 次触发封禁。"""
    monkeypatch.delenv("WS_AUTH_FAILURE_BAN_THRESHOLD", raising=False)
    from lingshu_api.ws.connection import ConnectionManager

    mgr = ConnectionManager()
    count = 0
    for _ in range(4):
        count = mgr.record_auth_failure("1.2.3.4")
        assert not mgr.is_ip_banned("1.2.3.4"), "未达阈值不应封禁"
    assert count == 4
    mgr.record_auth_failure("1.2.3.4")
    assert mgr.is_ip_banned("1.2.3.4"), "第 5 次失败应触发封禁"


def test_five_failures_then_banned_by_default(client: TestClient, monkeypatch) -> None:
    """端到端：默认阈值下连续 5 次认证失败，第 6 次连接被封禁拒绝。"""
    monkeypatch.delenv("WS_AUTH_FAILURE_BAN_THRESHOLD", raising=False)
    from lingshu_api.ws import connection as ws_connection

    manager = ws_connection.get_ws_manager()
    manager._ip_bans.clear()
    manager._ip_failures.clear()
    try:
        for _ in range(5):
            with client.websocket_connect("/ws/chat") as ws:
                ws.send_json({"type": "auth", "payload": {"token": "bad-token"}})
                resp = ws.receive_json()
                assert resp["type"] == "error", resp
        # 第 6 次连接应在 connect 阶段即被以 4003 拒绝
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/chat") as ws:
            ws.receive_json()
    finally:
        manager._ip_bans.clear()
        manager._ip_failures.clear()
        manager._ip_connect_times.clear()


def test_clear_auth_failures_on_success(manager) -> None:
    """成功认证后失败计数重置（clear_auth_failures）。"""
    for _ in range(3):
        manager.record_auth_failure("10.0.0.1")
    assert not manager.is_ip_banned("10.0.0.1")
    manager.clear_auth_failures("10.0.0.1")
    assert manager._ip_failures.get("10.0.0.1") is None
    # 重置后需要重新累计到阈值才会封禁
    for _ in range(4):
        manager.record_auth_failure("10.0.0.1")
    assert not manager.is_ip_banned("10.0.0.1")
    manager.record_auth_failure("10.0.0.1")
    assert manager.is_ip_banned("10.0.0.1")


def test_env_override_threshold(monkeypatch) -> None:
    """env 覆盖阈值：WS_AUTH_FAILURE_BAN_THRESHOLD=2 时第 2 次失败即封禁。"""
    monkeypatch.setenv("WS_AUTH_FAILURE_BAN_THRESHOLD", "2")
    from lingshu_api.ws.connection import ConnectionManager

    mgr = ConnectionManager()
    mgr.record_auth_failure("10.0.0.2")
    assert not mgr.is_ip_banned("10.0.0.2")
    mgr.record_auth_failure("10.0.0.2")
    assert mgr.is_ip_banned("10.0.0.2")


def test_env_override_ban_seconds(monkeypatch) -> None:
    """WS_AUTH_FAILURE_BAN_SECONDS 覆盖封禁时长。"""
    monkeypatch.setenv("WS_AUTH_FAILURE_BAN_THRESHOLD", "1")
    monkeypatch.setenv("WS_AUTH_FAILURE_BAN_SECONDS", "1")
    from lingshu_api.ws.connection import ConnectionManager

    mgr = ConnectionManager()
    mgr.record_auth_failure("10.0.0.3")
    assert mgr.is_ip_banned("10.0.0.3")
    # 窗口过期后自动解封且计数清零
    import time

    remaining = mgr._ip_bans["10.0.0.3"] - time.time()
    assert 0 < remaining <= 2, f"封禁窗口应约为 1 秒，实际剩余 {remaining}"
    mgr._ip_bans["10.0.0.3"] = 0.0  # 模拟时间流逝
    assert not mgr.is_ip_banned("10.0.0.3")
    assert mgr._ip_failures.get("10.0.0.3") is None
