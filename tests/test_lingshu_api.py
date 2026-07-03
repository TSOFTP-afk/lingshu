from __future__ import annotations

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


def test_public_auth_bookshelf_author_and_workspace_routes(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/password-params").status_code == 404
    assert client.get("/api/books").status_code == 200
    assert client.get("/api/books/99999").status_code == 404
    assert client.get("/api/books/99999/chapters").status_code == 404
    assert client.get("/api/chapters/99999").status_code == 404

    assert client.post("/api/auth/login", json={"username": "ghost_user", "password": "xxx"}).status_code == 401

    username = f"apitest_{uuid.uuid4().hex[:10]}"
    register = client.post(
        "/api/auth/register",
        json={"username": username, "password": "apitest_001", "is_author": 1},
    )
    assert register.status_code == 200
    token = register.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/auth/me", headers=headers).status_code == 200
    assert client.get("/api/auth/devices", headers=headers).status_code == 200
    assert client.post("/api/auth/login", json={"username": username, "password": "apitest_001"}).status_code == 200

    assert client.get("/api/bookshelf", headers=headers).status_code == 200
    assert client.get("/api/bookshelf/shelves", headers=headers).status_code == 200
    assert client.post("/api/bookshelf/shelves", json={"name": "测试分组"}, headers=headers).status_code == 200
    assert client.get("/api/bookshelf/99999", headers=headers).status_code == 404
    assert client.get("/api/cloud/sync/status").status_code == 401
    assert client.get("/api/cloud/sync/status", headers=headers).status_code == 200

    assert client.get("/api/author/books", headers=headers).status_code == 200
    book_resp = client.post("/api/author/books", json={"title": "API测试作品"}, headers=headers)
    assert book_resp.status_code == 200
    book_id = book_resp.json()["item"]["id"]

    assert client.get(f"/api/author/books/{book_id}/chapters", headers=headers).status_code == 200
    chapter_resp = client.post(f"/api/author/books/{book_id}/chapters/next", headers=headers)
    assert chapter_resp.status_code == 200
    chapter_id = chapter_resp.json()["item"].get("chapter_id") or chapter_resp.json()["item"]["id"]
    assert client.get(f"/api/author/books/{book_id}/chapters/{chapter_id}", headers=headers).status_code == 200
    assert client.patch(
        f"/api/author/books/{book_id}/chapters/{chapter_id}",
        json={"title": "更新后标题", "content": "正文内容", "volume_title": "测试卷"},
        headers=headers,
    ).status_code == 200
    assert client.post(f"/api/author/books/{book_id}/chapters/{chapter_id}/publish", headers=headers).status_code == 200
    assert client.delete(f"/api/author/books/{book_id}/chapters/{chapter_id}", headers=headers).status_code == 200
    assert client.patch(f"/api/author/books/{book_id}", json={"summary": "更新简介"}, headers=headers).status_code == 200
    assert client.patch("/api/author/books/99999", json={"summary": "xxx"}, headers=headers).status_code == 404

    assert client.get("/api/workspace/books").status_code == 401
    assert client.get("/api/workspace/health").status_code == 200
