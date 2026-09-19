"""会话 token 安全回归测试 — auth_tokens 表只存哈希，不存明文。

背景（抢救方案 1.1 安全修复 A）:
  历史实现把明文 token 与 token_hash 同时写入 auth_tokens 表，
  拖库即泄露全部活跃会话。修复后:
    1. 新登录只写 token_hash（token 列存 NULL）；
    2. 鉴权校验按 token_hash 查表（客户端仍传明文 token，对外 API 兼容）；
    3. 初始化时幂等迁移：回填存量行 token_hash 后清空明文 token 列；
    4. 管理端查询不返回明文 token。
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lingshu_api.main import create_app
from novel_app.bookstore import BookstoreStore
from novel_app.bookstore.models import initialize_database


USERNAME = "token_sec_author"
PASSWORD = "test_pass_123456"


def _sha256(text: str) -> str:
    """与 novel_app.bookstore.security._token_hash 相同的哈希算法。"""
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


@pytest.fixture()
def client_and_store(tmp_path: Path) -> tuple[TestClient, BookstoreStore, Path]:
    db_path = tmp_path / "bookstore.db"
    app = create_app(db_path=db_path)
    store = BookstoreStore(db_path)
    store.create_user(USERNAME, PASSWORD, is_author=1)
    return TestClient(app), store, db_path


def _login(client: TestClient) -> str:
    resp = client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    assert token
    return token


def _auth_tokens_rows(db_path: Path) -> list[sqlite3.Row]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT token, token_hash, user_id, revoked_at, expires_at FROM auth_tokens"
        ).fetchall()


def test_new_login_stores_only_hash(client_and_store) -> None:
    """新登录写入后，token 列不含明文，token_hash 与明文一致。"""
    client, _store, db_path = client_and_store
    token = _login(client)

    rows = _auth_tokens_rows(db_path)
    assert len(rows) == 1
    row = rows[0]
    # token 列必须为空（NULL 或空串），不得泄露明文
    stored_token = row["token"]
    assert stored_token is None or stored_token == "", f"auth_tokens.token 泄露明文: {stored_token!r}"
    # 哈希列正确，且不等于明文
    assert row["token_hash"] == _sha256(token)
    assert row["token_hash"] != token

    # 明文 token 仍可正常通过鉴权接口
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["username"] == USERNAME


def test_auth_still_works_after_multiple_logins(client_and_store) -> None:
    """多次登录产生多条哈希记录，各明文 token 均可鉴权。"""
    client, _store, db_path = client_and_store
    token_one = _login(client)
    token_two = _login(client)
    assert token_one != token_two

    rows = _auth_tokens_rows(db_path)
    assert len(rows) == 2
    for row in rows:
        assert row["token"] is None or row["token"] == ""
        assert len(row["token_hash"]) == 64

    for token in (token_one, token_two):
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200, resp.text


def test_legacy_plaintext_rows_backfilled_and_cleared(client_and_store) -> None:
    """存量明文行经初始化迁移后：回填 token_hash、清空 token 列，旧 token 仍可鉴权。"""
    client, _store, db_path = client_and_store
    legacy_token = "legacy-plaintext-token-abcdef123456"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO auth_tokens (token, token_hash, user_id, expires_at)
            VALUES (?, '', 1, datetime('now', '+7 days'))
            """,
            (legacy_token,),
        )
        connection.commit()

    # 幂等迁移：重跑 schema 初始化
    initialize_database(db_path)

    rows = _auth_tokens_rows(db_path)
    legacy_rows = [row for row in rows if row["token_hash"] == _sha256(legacy_token)]
    assert legacy_rows, "存量行 token_hash 未回填"
    for row in legacy_rows:
        assert row["token"] is None or row["token"] == "", f"迁移后 token 列仍存明文: {row['token']!r}"

    # 旧明文 token 迁移后仍可通过鉴权（按哈希查表）
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {legacy_token}"})
    assert resp.status_code == 200, resp.text


def test_logout_revokes_by_hash(client_and_store) -> None:
    """登出按哈希撤销，明文 token 随即失效。"""
    client, _store, db_path = client_and_store
    token = _login(client)
    resp = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text

    rows = _auth_tokens_rows(db_path)
    assert rows and rows[0]["revoked_at"] is not None

    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_admin_views_do_not_expose_plaintext_token(client_and_store) -> None:
    """管理端 token 列表/用户详情不返回明文 token。"""
    client, store, db_path = client_and_store
    token = _login(client)

    listing = store.admin_list_tokens(page=1, page_size=20)
    assert listing["total"] >= 1
    for item in listing["items"]:
        assert not item.get("token"), f"管理端泄露明文 token: {item.get('token')!r}"
        assert item.get("token_hash")

    detail = store.admin_get_user(1)
    assert detail is not None
    for item in detail["tokens"]:
        assert not item.get("token"), f"用户详情泄露明文 token: {item.get('token')!r}"

    # 管理端按明文 token 撤销仍然有效
    assert store.admin_revoke_token(1, token) is True
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
