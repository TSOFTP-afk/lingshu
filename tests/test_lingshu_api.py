from __future__ import annotations

import contextlib
import importlib
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "workspace-data"
    monkeypatch.setenv("SIMPLE_AI_NOVEL_DATA_DIR", str(data_dir))

    db_bridge = importlib.import_module("lingshu_api.services.db_bridge")
    db_bridge.reset_default_workspace_db()

    from lingshu_api.main import create_app

    app = create_app(tmp_path / "bookstore.db")
    with TestClient(app) as test_client:
        yield test_client

    db_bridge.reset_default_workspace_db()


def _token(client: TestClient, username: str, password: str = "apitest_001") -> str:
    """登录端点已剥离，直接操作 store 数据层获取 token。"""
    store = client.app.state.store
    with contextlib.suppress(Exception):
        store.create_user(username, password, is_author=1)
    token = store.login_user(username, password)
    assert token
    return token


def test_public_auth_bookshelf_author_and_workspace_routes(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/password-params").status_code == 404

    # ── 已剥离的产品线路由（书城/书架/发布/作者端/社区/管理端/登录注册）→ 404 ──
    assert client.get("/api/books").status_code == 404
    assert client.get("/api/books/99999").status_code == 404
    assert client.get("/api/books/99999/chapters").status_code == 404
    assert client.get("/api/chapters/99999").status_code == 404
    assert client.post("/api/auth/login", json={"username": "ghost_user", "password": "xxx"}).status_code == 404
    assert client.post(
        "/api/auth/register", json={"username": "ghost_user", "password": "xxx"}
    ).status_code == 404
    assert client.post("/api/publish/chapter", json={}).status_code == 404
    assert client.get("/api/bookshelf").status_code == 404
    assert client.get("/api/author/books").status_code == 404
    assert client.get("/api/community/cards").status_code == 404
    assert client.get("/api/admin/overview").status_code == 404

    # ── /api/auth/me：多用户模式下无 token → 401，有效 token → 200 ──
    assert client.get("/api/auth/me").status_code == 401
    token = _token(client, f"apitest_{uuid.uuid4().hex[:10]}")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    # ── 云端书籍只读路由保留（upload/download/sync 已随 book_sync 剥离）──
    assert client.get("/api/cloud/sync/status").status_code == 401
    assert client.get("/api/cloud/sync/status", headers=headers).status_code == 200
    assert client.post("/api/cloud/books/1/upload", headers=headers).status_code == 404
    assert client.post("/api/cloud/sync", headers=headers).status_code == 404

    # ── 工作台：多用户模式下无 token → 401 ──
    assert client.get("/api/workspace/books").status_code == 401
    assert client.get("/api/workspace/health").status_code == 200
