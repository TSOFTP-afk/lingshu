"""本地单用户模式（LINGSHU_LOCAL_USER，personal-client P2）回归测试。

覆盖:
  a) /auth/me 无 token → 200 本地用户（免登录直达工作台的数据基础）
  b) require_login 端点（/api/workspace/books）无 token → 200（不再 401）
  c) require_ai_access 端点（/api/settings/ai）无 token → 200（登录/配额直通）
  d) WS 认证无 token → auth_ok（跳过 token 校验与封禁计数）
  e) 开关语义锁：LINGSHU_LOCAL_USER=0 时 /auth/me 无 token → 401
     （对照用例，锁住"显式设 0 恢复多用户行为"的承诺；根 conftest 已
     setdefault 0，存量测试因此全部保持多用户语义）
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lingshu_api.main import create_app

# ── 环境 & 夹具 ───────────────────────────────────────────────────


@pytest.fixture()
def local_env(monkeypatch):
    """开启本地单用户模式（与生产默认一致，显式设 1 防外部 env 干扰）。"""
    monkeypatch.setenv("LINGSHU_LOCAL_USER", "1")
    return monkeypatch


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """临时数据库 + 未携带 Authorization 头的 TestClient。"""
    db_path = tmp_path / "bookstore.db"
    monkeypatch.setenv("SIMPLE_AI_NOVEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BOOKSTORE_DB_PATH", str(db_path))
    from lingshu_api.services.db_bridge import reset_default_workspace_db

    reset_default_workspace_db()
    app = create_app(db_path=db_path)
    with TestClient(app) as test_client:
        yield test_client
    reset_default_workspace_db()


# ── a) /auth/me 无 token → 200 本地用户 ──────────────────────────

def test_auth_me_without_token_returns_local_user(client, local_env):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    user = resp.json()
    assert user["id"] == 1
    assert user["username"] == "local"
    assert user["is_admin"] == 1
    assert user["is_author"] == 1
    assert user["status"] == "active"


# ── b) require_login 端点无 token → 200 ─────────────────────────

def test_require_login_endpoint_without_token_passes(client, local_env):
    resp = client.get("/api/workspace/books")
    assert resp.status_code == 200, "本地模式无 token 应直通（多用户模式为 401）"


# ── c) require_ai_access 端点无 token → 200 ─────────────────────

def test_require_ai_access_endpoint_without_token_passes(client, local_env):
    resp = client.get("/api/settings/ai")
    assert resp.status_code == 200, "本地模式 AI 门禁应直通（免登录且无配额限制）"


# ── d) WS 认证无 token → auth_ok ────────────────────────────────

def test_ws_auth_without_token_passes(client, local_env):
    with client.websocket_connect("/ws/generation") as ws:
        ws.send_json({"type": "auth", "payload": {"token": ""}})
        msg = ws.receive_json()
    assert msg["type"] == "auth_ok", f"本地模式 WS 应免 token 认证通过，实际: {msg}"


# ── e) 开关语义锁：env=0 恢复多用户 401 ──────────────────────────

def test_multi_user_mode_auth_me_without_token_keeps_401(client, monkeypatch):
    monkeypatch.setenv("LINGSHU_LOCAL_USER", "0")
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401, "显式设 LINGSHU_LOCAL_USER=0 必须恢复多用户 401 语义"


def test_multi_user_mode_require_login_without_token_keeps_401(client, monkeypatch):
    monkeypatch.setenv("LINGSHU_LOCAL_USER", "0")
    resp = client.get("/api/workspace/books")
    assert resp.status_code == 401
