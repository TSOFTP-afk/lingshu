from __future__ import annotations

import contextlib
import importlib
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "workspace-data"
    monkeypatch.setenv("SIMPLE_AI_NOVEL_DATA_DIR", str(data_dir))
    monkeypatch.delenv("LINGSHU_AI_API_KEY", raising=False)
    monkeypatch.delenv("LINGSHU_AI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

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


def _workspace_db(client: TestClient):
    return client.app.state.workspace_db_provider.get()


def test_reference_import_bind_update_segments_and_unbind(client: TestClient) -> None:
    book = client.post("/api/workspace/books", json={"title": "Reference target"}).json()["item"]
    book_id = int(book["id"])

    response = client.post(
        "/api/workspace/references/import-file",
        data={"book_id": str(book_id), "title": "Ref A", "role": "canon_reference"},
        files={"file": ("ref.md", b"# Part One\n\nReference rhythm sample.", "text/markdown")},
    )
    assert response.status_code == 200
    source_id = int(response.json()["source_id"])
    assert response.json()["stats"]["segment_count"] == 1

    refs = client.get(f"/api/workspace/books/{book_id}/references").json()
    assert len(refs["items"]) == 1
    assert refs["items"][0]["role"] == "canon_reference"
    assert "Reference rhythm sample" in refs["context"]

    segments = client.get(f"/api/workspace/books/{book_id}/references/{source_id}/segments").json()
    assert len(segments["items"]) == 1
    assert "Reference rhythm sample" in segments["items"][0]["content"]

    update = client.patch(
        f"/api/workspace/books/{book_id}/references/{source_id}",
        json={"enabled": False, "role": "avoid_reference", "notes": "disabled"},
    )
    assert update.status_code == 200
    disabled_context = client.get(f"/api/workspace/books/{book_id}/references").json()["context"]
    assert "Reference rhythm sample" not in disabled_context

    unbind = client.delete(f"/api/workspace/books/{book_id}/references/{source_id}")
    assert unbind.status_code == 200
    assert client.get(f"/api/workspace/books/{book_id}/references/{source_id}/segments").status_code == 200
    assert client.get(f"/api/workspace/books/{book_id}/references/{source_id}/segments").json()["items"] == []


def test_reference_global_import_can_bind_existing_source(client: TestClient) -> None:
    book = client.post("/api/workspace/books", json={"title": "Bind target"}).json()["item"]
    book_id = int(book["id"])

    imported = client.post(
        "/api/workspace/references/import-file",
        data={"title": "Global Ref"},
        files={"file": ("global.txt", b"Global reference text.", "text/plain")},
    )
    assert imported.status_code == 200
    source_id = int(imported.json()["source_id"])

    bind = client.post(
        f"/api/workspace/books/{book_id}/references/{source_id}",
        json={"role": "style_reference"},
    )
    assert bind.status_code == 200
    assert bind.json()["stats"]["segment_count"] == 1
    assert "Global reference text" in client.get(f"/api/workspace/books/{book_id}/references").json()["context"]


def test_ai_settings_roundtrip_and_purpose_resolution(client: TestClient, tmp_path, monkeypatch) -> None:
    unauth = client.get("/api/settings/ai", headers={"Authorization": ""})
    assert unauth.status_code == 401
    assert "AI 功能" in unauth.json()["detail"]

    payload = client.get("/api/settings/ai").json()
    assert payload["ok"] is True
    assert "writing" in payload["profiles"]

    payload["profiles"]["writing"].update({
        "remote_enabled": True,
        "provider": "deepseek",
        "api_key": "sk-test-writing",
        "base_url": "https://example.test/v1",
        "model": "model-writing",
        "temperature": 0.2,
        "max_tokens": 1234,
        "thinking_enabled": True,
        "thinking_budget_tokens": 8192,
    })
    saved = client.put("/api/settings/ai", json=payload)
    assert saved.status_code == 200

    loaded = client.get("/api/settings/ai").json()
    assert loaded["profiles"]["writing"]["api_key"] == "***"
    assert loaded["profiles"]["writing"]["api_key_configured"] is True
    assert loaded["profiles"]["writing"]["provider"] == "deepseek"
    assert loaded["profiles"]["writing"]["model"] == "model-writing"
    assert loaded["profiles"]["writing"]["thinking_enabled"] is True
    assert loaded["profiles"]["writing"]["thinking_budget_tokens"] == 8192

    from lingshu_api.services.ai_settings import resolve_ai_profile, settings_path
    data_dir = _workspace_db(client).db.data_dir
    raw_file = json.loads(settings_path(data_dir).read_text(encoding="utf-8"))
    assert "profiles" in raw_file
    assert raw_file["profiles"]["writing"]["api_key"]
    assert raw_file["profiles"]["writing"]["provider"] == "deepseek"
    assert raw_file["profiles"]["writing"]["thinking_enabled"] is True
    assert raw_file["profiles"]["writing"]["thinking_budget_tokens"] == 8192

    profile = resolve_ai_profile(data_dir, "generation")
    assert profile["api_key"] == "sk-test-writing"
    assert profile["provider"] == "deepseek"
    assert profile["model"] == "model-writing"
    extra_body = json.loads(profile["extra_body"])
    assert extra_body["thinking"] == {"type": "enabled", "budget_tokens": 8192}

    monkeypatch.setenv("LINGSHU_AI_API_KEY", "sk-env")
    monkeypatch.setenv("LINGSHU_AI_MODEL", "env-model")
    chat_profile = resolve_ai_profile(data_dir, "chat")
    assert chat_profile["api_key"] == "sk-env"
    assert chat_profile["model"] == "env-model"

    test_profile = {**loaded["profiles"]["writing"], "api_key": "sk-test-writing"}
    test_resp = client.post("/api/settings/ai/test", json={"purpose": "writing", "profile": test_profile})
    assert test_resp.status_code == 200
    assert test_resp.json()["ok"] is True


def test_ai_purposes_includes_writing_probe() -> None:
    from lingshu_api.services.ai_settings import AI_PURPOSES

    assert "writing_probe" in AI_PURPOSES
    assert AI_PURPOSES["writing_probe"]["label"] == "写作探针"
    assert "扫描" in AI_PURPOSES["writing_probe"]["description"]


def test_profile_defaults_contains_probe_fields() -> None:
    from lingshu_api.services.ai_settings import PROFILE_DEFAULTS

    assert PROFILE_DEFAULTS.get("interval_seconds") == 8
    assert PROFILE_DEFAULTS.get("auto_write_threshold") == 0.55
    assert PROFILE_DEFAULTS.get("probe_enabled") is False


def test_writing_probe_settings_roundtrip(client: TestClient) -> None:
    payload = client.get("/api/settings/ai").json()
    assert "writing_probe" in payload["profiles"]
    # 默认值兜底
    assert payload["profiles"]["writing_probe"]["interval_seconds"] == 8
    assert payload["profiles"]["writing_probe"]["auto_write_threshold"] == 0.55
    assert payload["profiles"]["writing_probe"]["probe_enabled"] is False

    payload["profiles"]["writing_probe"].update({
        "probe_enabled": True,
        "interval_seconds": 12,
        "auto_write_threshold": 0.7,
        "remote_enabled": True,
        "api_key": "sk-probe",
        "model": "probe-model",
    })
    saved = client.put("/api/settings/ai", json=payload)
    assert saved.status_code == 200

    loaded = client.get("/api/settings/ai").json()
    probe = loaded["profiles"]["writing_probe"]
    assert probe["probe_enabled"] is True
    assert probe["interval_seconds"] == 12
    assert probe["auto_write_threshold"] == 0.7
    assert probe["api_key_configured"] is True


def test_writing_probe_interval_clamped_to_range(client: TestClient) -> None:
    payload = client.get("/api/settings/ai").json()
    # 越界值应被归一化到 [5, 60]
    payload["profiles"]["writing_probe"].update({
        "interval_seconds": 1,  # 低于下限
        "auto_write_threshold": 2.0,  # 高于上限
    })
    saved = client.put("/api/settings/ai", json=payload).json()
    assert saved["profiles"]["writing_probe"]["interval_seconds"] == 5
    assert saved["profiles"]["writing_probe"]["auto_write_threshold"] == 1.0

