from __future__ import annotations

import contextlib
import importlib

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
        # 创建测试用户并获取认证 Token（直接操作 store 绕过限流）
        store = app.state.store
        with contextlib.suppress(Exception):
            store.create_user("testuser", "testpass123")
        token = store.login_user("testuser", "testpass123")
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client

    db_bridge.reset_default_workspace_db()


def test_phase2_workspace_drawer_routes(client: TestClient) -> None:
    book_resp = client.post("/api/workspace/books", json={"title": "阶段2测试书"})
    assert book_resp.status_code == 200
    book_id = book_resp.json()["item"]["id"]

    assert client.get(f"/api/workspace/books/{book_id}/characters").status_code == 200
    char_resp = client.post(f"/api/workspace/books/{book_id}/characters", json={"name": "测试人物A"})
    assert char_resp.status_code == 200
    char_id = char_resp.json()["item"]["id"]
    char_detail = client.get(f"/api/workspace/characters/{char_id}")
    assert char_detail.status_code == 200
    assert char_detail.json()["profile_schema"]
    profile_data = char_detail.json()["profile_data"]
    profile_data["fields"]["function_partner"]["checked"] = True
    assert client.patch(
        f"/api/workspace/characters/{char_id}",
        json={"name": "测试人物A-改", "role": "搭档", "profile_data": profile_data},
    ).status_code == 200
    updated_char = client.get(f"/api/workspace/characters/{char_id}").json()
    assert updated_char["profile_data"]["fields"]["function_partner"]["checked"] is True
    assert "[x] 搭档/战友" in updated_char["profile_text"]

    world_payload = client.get(f"/api/workspace/books/{book_id}/world")
    assert world_payload.status_code == 200
    assert world_payload.json()["world_schema"]
    world_data = world_payload.json()["world_data"]
    world_data["fields"]["shape_otherworld"]["checked"] = True
    world_data["fields"]["crisis_ai"]["checked"] = True
    world_save = client.put(
        f"/api/workspace/books/{book_id}/world",
        json={"world_data": world_data},
    )
    assert world_save.status_code == 200
    assert "[x] 异世界" in world_save.json()["world_text"]
    assert world_save.json()["world_data"]["fields"]["crisis_ai"]["checked"] is True

    assert client.get(f"/api/workspace/books/{book_id}/skills").status_code == 200
    assert client.get("/api/workspace/skills").status_code == 200
    assert client.get(f"/api/workspace/books/{book_id}/references").status_code == 200
    assert client.get("/api/workspace/references").status_code == 200
    assert client.get("/api/workspace/books/99999/characters").status_code == 404
    assert client.delete(f"/api/workspace/characters/{char_id}").status_code == 200

    routes = client.get("/openapi.json").json()["paths"]
    assert len([path for path in routes if "workspace" in path]) >= 28
