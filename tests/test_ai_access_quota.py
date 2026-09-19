"""AI 门禁回归测试 — 安全修复 B。

覆盖:
  a) require_ai_access 每日 token 预算（LINGSHU_DAILY_AI_TOKEN_LIMIT，默认 200000）→ 超限 429
  b) require_ai_access 每用户并发上限（LINGSHU_AI_CONCURRENCY_PER_USER，默认 3）→ 超限 429，请求结束必须释放
  c) 服务端 AI Key 回退注入改为 opt-in（LINGSHU_ALLOW_SERVER_KEY_FALLBACK=1 才启用，默认关闭）
  d) Linux/无 keyring 环境禁止明文落库：无 LINGSHU_MASTER_KEY 时抛明确异常；有 master key 时 Fernet 加密
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from lingshu_api import dependencies
from lingshu_api.main import create_app
from lingshu_api.services.ai_settings import (
    load_ai_settings,
    resolve_ai_profile,
    save_ai_settings,
)
from novel_app.bookstore import BookstoreStore
from novel_app.secure_storage import protect_secret, unprotect_secret

# ── 环境 & 夹具 ───────────────────────────────────────────────────

_AI_ENV_VARS = (
    "LINGSHU_AI_API_KEY",
    "OPENAI_API_KEY",
    "LINGSHU_AI_BASE_URL",
    "OPENAI_BASE_URL",
    "LINGSHU_AI_MODEL",
    "OPENAI_MODEL",
    "LINGSHU_ALLOW_SERVER_KEY_FALLBACK",
    "LINGSHU_MASTER_KEY",
    "LINGSHU_DAILY_AI_TOKEN_LIMIT",
    "LINGSHU_AI_CONCURRENCY_PER_USER",
)


@pytest.fixture()
def ai_env(monkeypatch):
    """清空 AI 门禁相关环境变量，返回 monkeypatch 供用例自行设置。"""
    for var in _AI_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


@pytest.fixture(autouse=True)
def _clean_concurrency_slots():
    """每条用例前后清空进程内并发计数，避免互相污染。"""
    with dependencies._ai_concurrency_lock:
        dependencies._ai_concurrency.clear()
    yield
    with dependencies._ai_concurrency_lock:
        dependencies._ai_concurrency.clear()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """临时数据库 + 已登录用户的 TestClient。"""
    db_path = tmp_path / "bookstore.db"
    monkeypatch.setenv("SIMPLE_AI_NOVEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BOOKSTORE_DB_PATH", str(db_path))
    from lingshu_api.services.db_bridge import reset_default_workspace_db

    reset_default_workspace_db()
    app = create_app(db_path=db_path)
    with TestClient(app) as test_client:
        store = app.state.store
        with contextlib.suppress(Exception):
            store.create_user("quota_user", "test_pass_123456")
        token = store.login_user("quota_user", "test_pass_123456")
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client, store, token
    reset_default_workspace_db()


def _user_id(store: BookstoreStore, token: str) -> int:
    user = store.get_user_by_token(token)
    assert user, "测试用户 token 应有效"
    return int(user["id"])


# ── a) 每日 token 预算 ────────────────────────────────────────────

def test_daily_budget_blocks_when_exceeded(client, ai_env):
    test_client, store, token = client
    ai_env.setenv("LINGSHU_DAILY_AI_TOKEN_LIMIT", "1000")
    user_id = _user_id(store, token)
    store.record_user_ai_usage(user_id=user_id, feature="chat", total_tokens=1000)

    resp = test_client.get("/api/settings/ai")
    assert resp.status_code == 429
    body = resp.json()
    assert "detail" in body, "429 响应应与项目现有错误格式一致（{\"detail\": ...}）"
    assert str(body["detail"]).strip(), "detail 不应为空"


def test_daily_budget_allows_under_limit(client, ai_env):
    test_client, store, token = client
    ai_env.setenv("LINGSHU_DAILY_AI_TOKEN_LIMIT", "1000")
    user_id = _user_id(store, token)
    store.record_user_ai_usage(user_id=user_id, feature="chat", total_tokens=500)

    resp = test_client.get("/api/settings/ai")
    assert resp.status_code == 200


def test_daily_budget_default_is_200k(ai_env):
    ai_env.setenv("LINGSHU_DAILY_AI_TOKEN_LIMIT", "")
    assert dependencies._ai_daily_token_limit() == 200000
    ai_env.delenv("LINGSHU_DAILY_AI_TOKEN_LIMIT", raising=False)
    assert dependencies._ai_daily_token_limit() == 200000
    ai_env.setenv("LINGSHU_DAILY_AI_TOKEN_LIMIT", "500")
    assert dependencies._ai_daily_token_limit() == 500


# ── b) 每用户并发上限 ─────────────────────────────────────────────

def test_concurrency_limit_blocks_and_releases(ai_env):
    ai_env.setenv("LINGSHU_AI_CONCURRENCY_PER_USER", "2")
    dependencies._acquire_ai_slot(42)
    dependencies._acquire_ai_slot(42)
    with pytest.raises(HTTPException) as exc_info:
        dependencies._acquire_ai_slot(42)
    assert exc_info.value.status_code == 429
    # 其他用户不受影响
    dependencies._acquire_ai_slot(43)
    # 释放后可再次获取
    dependencies._release_ai_slot(42)
    dependencies._acquire_ai_slot(42)


def test_concurrency_slot_released_after_request(client, ai_env):
    test_client, store, token = client
    ai_env.setenv("LINGSHU_AI_CONCURRENCY_PER_USER", "1")
    user_id = _user_id(store, token)

    resp = test_client.get("/api/settings/ai")
    assert resp.status_code == 200
    # yield 依赖结束后必须释放并发槽位
    assert user_id not in dependencies._ai_concurrency


# ── c) 服务端 Key 回退 opt-in ─────────────────────────────────────

def test_server_key_fallback_disabled_by_default(client, ai_env):
    test_client, store, token = client
    ai_env.setenv("LINGSHU_AI_API_KEY", "sk-server-secret-key")
    ai_env.setenv("LINGSHU_AI_MODEL", "server-model")
    user_id = _user_id(store, token)

    profile = resolve_ai_profile(Path(os.environ["SIMPLE_AI_NOVEL_DATA_DIR"]), "writing", user_id=user_id)
    assert profile["api_key"] != "sk-server-secret-key", "默认不得静默注入服务端 Key"
    assert "sk-server-secret-key" not in json.dumps(profile, ensure_ascii=False), "服务端 Key 不得泄漏到 profile"

    # 用户启用远程但未配 Key → 明确报错并引导去 AI 设置里配 Key
    payload = test_client.get("/api/settings/ai").json()
    payload["profiles"]["writing"]["remote_enabled"] = True
    saved = test_client.put("/api/settings/ai", json=payload)
    assert saved.status_code == 200
    test_resp = test_client.post("/api/settings/ai/test", json={"purpose": "writing"})
    assert test_resp.status_code == 200
    body = test_resp.json()
    assert body["ok"] is False
    assert "AI 设置" in body["message"], f"应引导用户去 AI 设置配 Key，实际: {body['message']}"
    assert "sk-server-secret-key" not in body["message"]


def test_server_key_fallback_opt_in(client, ai_env):
    test_client, store, token = client
    ai_env.setenv("LINGSHU_AI_API_KEY", "sk-server-secret-key")
    ai_env.setenv("LINGSHU_AI_MODEL", "server-model")
    ai_env.setenv("LINGSHU_ALLOW_SERVER_KEY_FALLBACK", "1")
    user_id = _user_id(store, token)

    profile = resolve_ai_profile(Path(os.environ["SIMPLE_AI_NOVEL_DATA_DIR"]), "writing", user_id=user_id)
    assert profile["api_key"] == "sk-server-secret-key"
    assert profile["remote_enabled"] is True
    assert profile["model"] == "server-model"


# ── d) 禁止明文 Key 落库 ──────────────────────────────────────────

@pytest.fixture()
def posix_no_keyring(monkeypatch):
    """模拟 Linux/无 keyring 环境。"""
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr("novel_app.secure_storage._store_keyring_secret", lambda secret: "")


def test_protect_secret_rejects_plaintext_without_master_key(ai_env, posix_no_keyring):
    with pytest.raises(RuntimeError) as exc_info:
        protect_secret("sk-my-plain-api-key")
    message = str(exc_info.value)
    assert "LINGSHU_MASTER_KEY" in message, "异常信息应指明如何配置 LINGSHU_MASTER_KEY"
    assert "sk-my-plain-api-key" not in message


def test_fernet_roundtrip_with_master_key(ai_env, posix_no_keyring):
    ai_env.setenv("LINGSHU_MASTER_KEY", "unit-test-master-key")
    sealed = protect_secret("sk-my-plain-api-key")
    assert sealed.startswith("fernet:")
    assert "sk-my-plain-api-key" not in sealed
    assert unprotect_secret(sealed) == "sk-my-plain-api-key"


def test_saved_profile_not_plaintext_in_db(tmp_path, ai_env, posix_no_keyring, monkeypatch):
    ai_env.setenv("LINGSHU_MASTER_KEY", "unit-test-master-key")
    db_path = tmp_path / "bookstore.db"
    monkeypatch.setenv("BOOKSTORE_DB_PATH", str(db_path))
    monkeypatch.setenv("SIMPLE_AI_NOVEL_DATA_DIR", str(tmp_path))
    BookstoreStore(db_path)  # 初始化表结构

    save_ai_settings(
        tmp_path,
        {"profiles": {"writing": {"remote_enabled": True, "api_key": "sk-user-plain-key", "model": "m"}}},
        user_id=1,
    )

    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            "SELECT profile_json FROM user_ai_settings WHERE user_id = 1 AND purpose = 'writing'"
        ).fetchall()
    assert rows, "profile 应已写入 user_ai_settings"
    raw = rows[0][0]
    assert "sk-user-plain-key" not in raw, "API Key 不得明文写入数据库"
    assert "fernet:" in raw

    loaded = load_ai_settings(tmp_path, reveal_secrets=True, user_id=1)
    assert loaded["profiles"]["writing"]["api_key"] == "sk-user-plain-key"
