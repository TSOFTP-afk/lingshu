"""桌面端发布令牌流程回归测试（针对 lingshu_api.main 活应用）。

背景（阶段2 减法）:
  旧 test_bookstore_api.py 测的是未挂载的平行书城应用（已归档至 _attic/legacy-tests/），
  已随该死代码归档至 _attic/legacy-tests/。此处以最小用例保住活路由
  POST /api/publish/chapter 的令牌校验行为（X-Publish-Token 走环境变量）。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lingshu_api.main import create_app

PUBLISH_TOKEN = "test-publish-token"


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(db_path=tmp_path / "bookstore.db"))


def _payload(**overrides):
    data = {
        "source_app": "lingshu-desktop",
        "source_book_id": 12,
        "source_volume_id": 3,
        "source_chapter_id": 45,
        "book_title": "镜湖试读",
        "volume_title": "第一卷",
        "chapter_title": "第一章 风起",
        "sort_order": 1,
        "outline": "主角抵达镜湖。",
        "summary_text": "镜湖边的第一场冲突。",
        "content": "风从湖面吹来，少年第一次看见城墙后的光。",
        "ai_probability": 12,
        "ai_probability_level": "low",
        "updated_at": "2026-06-02 12:00:00",
    }
    data.update(overrides)
    return data


def _publish(client: TestClient, token: str | None = PUBLISH_TOKEN) -> dict:
    headers = {"X-Publish-Token": token} if token is not None else {}
    return client.post("/api/publish/chapter", json=_payload(), headers=headers)


def test_publish_with_valid_token_creates_book(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSTORE_PUBLISH_TOKEN", PUBLISH_TOKEN)
    resp = _publish(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["book_id"] == 1 and body["chapter_id"] == 1
    books = client.get("/api/books").json()["items"]
    assert len(books) == 1 and books[0]["title"] == "镜湖试读"


def test_publish_rejects_wrong_token(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSTORE_PUBLISH_TOKEN", PUBLISH_TOKEN)
    assert _publish(client, token="wrong-token").status_code == 401


def test_publish_without_configured_token_returns_503(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BOOKSTORE_PUBLISH_TOKEN", raising=False)
    assert _publish(client).status_code == 503
