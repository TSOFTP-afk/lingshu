from __future__ import annotations

import hashlib
import hmac
import importlib
import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

import bcrypt
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    data_dir = tmp_path / "workspace-data"
    monkeypatch.setenv("SIMPLE_AI_NOVEL_DATA_DIR", str(data_dir))

    db_bridge = importlib.import_module("lingshu_api.services.db_bridge")
    db_bridge.reset_default_workspace_db()

    from lingshu_api.main import create_app

    db_path = tmp_path / "bookstore.db"
    app = create_app(db_path)
    with TestClient(app) as test_client:
        yield test_client, db_path

    db_bridge.reset_default_workspace_db()


def _insert_admin(db_path: Path, username: str = "admin", password: str = os.environ.get("TEST_ADMIN_PASSWORD", "strong-pass")) -> None:
    from lingshu_api.routers.admin_auth import _ensure_admin_tables

    _ensure_admin_tables(db_path)
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO admin_users (username, password_hash, display_name, role, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?)
            """,
            (username, password_hash, "Admin User", "superadmin", now, now),
        )
        connection.commit()


def _insert_admin_key(db_path: Path, key_id: str = "ak_test", secret: str = os.environ.get("TEST_ADMIN_HMAC_SECRET", "test-secret")) -> None:
    with sqlite3.connect(db_path) as connection:
        admin_id = connection.execute("SELECT id FROM admin_users WHERE username = 'admin'").fetchone()[0]
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        fingerprint = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]
        connection.execute(
            """
            INSERT INTO admin_keys (key_id, admin_user_id, secret_encrypted, key_fingerprint, status, issued_at)
            VALUES (?, ?, ?, ?, 'active', ?)
            """,
            (key_id, int(admin_id), secret, fingerprint, now),
        )
        connection.commit()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _signature(secret: str, timestamp: str, method: str, path: str) -> str:
    message = f"{timestamp}\n{method.upper()}\n{path}"
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def _signed_headers(secret: str, key_id: str, method: str, path: str, token: str | None = None) -> dict[str, str]:
    timestamp = str(int(time.time() * 1000))
    headers = {
        "X-Client-KeyId": key_id,
        "X-Client-Ts": timestamp,
        "X-Client-Sig": _signature(secret, timestamp, method, path),
    }
    if token:
        headers.update(_auth(token))
    return headers


def _signed_login_payload(secret: str, key_id: str, username: str = "admin", password: str = os.environ.get("TEST_ADMIN_PASSWORD", "strong-pass")) -> dict[str, str]:
    timestamp = str(int(time.time() * 1000))
    return {
        "username": username,
        "password": password,
        "key_id": key_id,
        "timestamp": timestamp,
        "hmac_signature": _signature(secret, timestamp, "POST", "/api/admin/auth/login"),
    }


def test_admin_auth_returns_503_when_hmac_key_is_missing(app_client) -> None:
    client, db_path = app_client
    _insert_admin(db_path)

    login = client.post("/api/admin/auth/login", json={"username": "admin", "password": "strong-pass"})
    assert login.status_code == 503
    assert client.get("/api/admin/auth/me").status_code == 503


def test_admin_auth_login_me_logout_and_admin_routes(app_client) -> None:
    client, db_path = app_client
    key_id = "ak_test"
    secret = "test-secret"
    _insert_admin(db_path)
    _insert_admin_key(db_path, key_id=key_id, secret=secret)

    assert client.get("/api/admin/auth/me").status_code == 403
    assert client.get("/api/admin/overview").status_code == 403

    login = client.post("/api/admin/auth/login", json=_signed_login_payload(secret, key_id))
    assert login.status_code == 200
    body = login.json()
    token = body["access_token"]
    assert body["admin"]["username"] == "admin"
    assert body["admin"]["role"] == "superadmin"

    assert client.get(
        "/api/admin/auth/me",
        headers=_signed_headers(secret, key_id, "GET", "/api/admin/auth/me", token=token),
    ).json()["username"] == "admin"
    assert client.get(
        "/api/admin/overview",
        headers=_signed_headers(secret, key_id, "GET", "/api/admin/overview", token=token),
    ).status_code == 200

    assert client.post(
        "/api/admin/auth/logout",
        headers=_signed_headers(secret, key_id, "POST", "/api/admin/auth/logout", token=token),
    ).json() == {"ok": True}
    assert client.get(
        "/api/admin/auth/me",
        headers=_signed_headers(secret, key_id, "GET", "/api/admin/auth/me", token=token),
    ).status_code == 401
    assert client.get(
        "/api/admin/overview",
        headers=_signed_headers(secret, key_id, "GET", "/api/admin/overview", token=token),
    ).status_code == 401


def test_admin_auth_requires_hmac_when_admin_key_is_configured(app_client) -> None:
    client, db_path = app_client
    key_id = "ak_test"
    secret = "test-secret"
    _insert_admin(db_path)
    _insert_admin_key(db_path, key_id=key_id, secret=secret)

    unsigned = client.post("/api/admin/auth/login", json={"username": "admin", "password": "strong-pass"})
    assert unsigned.status_code == 403

    bad_ts = str(int(time.time() * 1000))
    bad = client.post(
        "/api/admin/auth/login",
        json={
            "username": "admin",
            "password": "strong-pass",
            "key_id": key_id,
            "timestamp": bad_ts,
            "hmac_signature": _signature(secret, bad_ts, "POST", "/api/admin/wrong-path"),
        },
    )
    assert bad.status_code == 403

    login_ts = str(int(time.time() * 1000))
    login = client.post(
        "/api/admin/auth/login",
        json={
            "username": "admin",
            "password": "strong-pass",
            "key_id": key_id,
            "timestamp": login_ts,
            "hmac_signature": _signature(secret, login_ts, "POST", "/api/admin/auth/login"),
        },
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    assert client.get("/api/admin/overview", headers=_auth(token)).status_code == 403
    assert client.get(
        "/api/admin/overview",
        headers=_signed_headers(secret, key_id, "GET", "/api/admin/overview", token=token),
    ).status_code == 200


def test_regular_user_token_cannot_access_independent_admin_routes(app_client) -> None:
    client, db_path = app_client
    key_id = "ak_test"
    secret = "test-secret"
    _insert_admin(db_path)
    _insert_admin_key(db_path, key_id=key_id, secret=secret)

    register = client.post(
        "/api/auth/register",
        json={"username": "plain_user", "password": "plain-pass1", "is_author": 1},
    )
    assert register.status_code == 200
    token = register.json()["access_token"]

    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 200
    assert client.get(
        "/api/admin/auth/me",
        headers=_signed_headers(secret, key_id, "GET", "/api/admin/auth/me", token=token),
    ).status_code == 401
    assert client.get(
        "/api/admin/overview",
        headers=_signed_headers(secret, key_id, "GET", "/api/admin/overview", token=token),
    ).status_code == 401


def test_admin_actions_write_audit_rows_with_independent_admin_name(app_client) -> None:
    client, db_path = app_client
    key_id = "ak_test"
    secret = "test-secret"
    _insert_admin(db_path)
    _insert_admin_key(db_path, key_id=key_id, secret=secret)

    target = client.post(
        "/api/auth/register",
        json={"username": "target_user", "password": "target-pass1", "is_author": 1},
    ).json()["user"]

    token = client.post("/api/admin/auth/login", json=_signed_login_payload(secret, key_id)).json()["access_token"]

    update_path = f"/api/admin/users/{target['id']}"
    update = client.patch(
        update_path,
        json={"status": "disabled"},
        headers=_signed_headers(secret, key_id, "PATCH", update_path, token=token),
    )
    assert update.status_code == 200

    audits = client.get(
        "/api/admin/audit-logs",
        headers=_signed_headers(secret, key_id, "GET", "/api/admin/audit-logs", token=token),
    ).json()["items"]
    assert audits
    assert audits[0]["admin_username"] == "admin"
    assert audits[0]["action"] == "update"


def test_admin_auth_normalizes_legacy_audit_table(app_client) -> None:
    client, db_path = app_client
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP TABLE admin_audit_logs")
        connection.execute(
            """
            CREATE TABLE admin_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL DEFAULT '',
                detail_json TEXT NOT NULL DEFAULT '{}',
                ip_address TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (admin_user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        connection.commit()
        connection.execute("PRAGMA foreign_keys = ON")

    key_id = "ak_test"
    secret = "test-secret"
    _insert_admin(db_path)
    _insert_admin_key(db_path, key_id=key_id, secret=secret)
    response = client.post("/api/admin/auth/login", json=_signed_login_payload(secret, key_id))
    assert response.status_code == 200

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(admin_audit_logs)").fetchall()}
        foreign_keys = connection.execute("PRAGMA foreign_key_list(admin_audit_logs)").fetchall()
    assert {"object_type", "object_id", "detail"}.issubset(columns)
    assert not any(row[2] == "users" for row in foreign_keys)
