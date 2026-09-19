"""
人物接口 IDOR 回归测试（安全修复 C）。

病灶：characters.py 中写操作使用 `if book_id: check_book_owner(...)`，
book_id 为 0/None（全局人物）时完全跳过归属校验，任何登录用户可篡改全局人物。

修复后语义：
- 全局人物（book_id 缺失/为 0）写操作（资料修改/图片上传/删除/状态机写入）仅管理员可执行，普通用户 403；
- 归属书籍的人物写操作必须通过书籍归属校验，不得被 book_id 分支绕过；
- 读操作维持现状（全局人物对登录用户可读）。
"""
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


def _login_headers(store, username: str, password: str = "testpass123") -> dict[str, str]:
    with contextlib.suppress(Exception):
        store.create_user(username, password)
    token = store.login_user(username, password)
    assert token
    return {"Authorization": f"Bearer {token}"}


def _admin_headers(store, username: str = "admin_user") -> dict[str, str]:
    with contextlib.suppress(Exception):
        store.create_user(username, "adminpass123")
    store.sync_admin_users({username})
    token = store.login_user(username, "adminpass123")
    assert token
    return {"Authorization": f"Bearer {token}"}


def _workspace_db(client: TestClient):
    return client.app.state.workspace_db_provider.get()


def _create_global_character(client: TestClient, name: str = "全局模板人物") -> int:
    """直接经 DB 连接创建全局人物（book_id=0）。

    characters.book_id 有指向 books 的外键（正常写入不可能为 0），
    全局人物只可能来自历史数据/外部导入，故测试中临时关闭 FK 插入。
    """
    db = _workspace_db(client)
    conn = db.db.connection
    if conn.in_transaction:  # PRAGMA foreign_keys 在事务内是 no-op，先落盘
        conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        cursor = conn.execute(
            "INSERT INTO characters (book_id, name, profile_text) VALUES (0, ?, ?)",
            (name, f"{name} 的原始资料"),
        )
        character_id = int(cursor.lastrowid)
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
    assert character_id
    return character_id


def _png_file() -> dict:
    png_header = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    return {"file": ("avatar.png", png_header, "image/png")}


# ================================================================
#  全局人物写操作 — 普通用户 403
# ================================================================


def test_global_character_update_forbidden_for_normal_user(client: TestClient) -> None:
    """普通用户（非管理员）修改全局人物资料 → 403。"""
    character_id = _create_global_character(client)
    other_headers = _login_headers(client.app.state.store, "normal_user_b")
    resp = client.patch(
        f"/api/workspace/characters/{character_id}",
        json={"profile_text": "被篡改的资料"},
        headers=other_headers,
    )
    assert resp.status_code == 403, resp.text
    # 资料未被篡改（GET 返回的字段为顶层结构）
    item = client.get(f"/api/workspace/characters/{character_id}").json()
    assert item["profile_text"] != "被篡改的资料"


def test_global_character_upload_image_forbidden_for_normal_user(client: TestClient) -> None:
    """普通用户为全局人物上传立绘 → 403。"""
    character_id = _create_global_character(client)
    other_headers = _login_headers(client.app.state.store, "normal_user_b")
    resp = client.post(
        f"/api/workspace/characters/{character_id}/image",
        files=_png_file(),
        headers=other_headers,
    )
    assert resp.status_code == 403, resp.text
    char = _workspace_db(client).get_character(character_id)
    assert not char["image_path"]


def test_global_character_delete_forbidden_for_normal_user(client: TestClient) -> None:
    """普通用户删除全局人物 → 403。"""
    character_id = _create_global_character(client)
    other_headers = _login_headers(client.app.state.store, "normal_user_b")
    resp = client.delete(f"/api/workspace/characters/{character_id}", headers=other_headers)
    assert resp.status_code == 403, resp.text
    assert _workspace_db(client).get_character(character_id) is not None


def test_global_character_state_machine_write_forbidden_for_normal_user(client: TestClient) -> None:
    """普通用户写全局人物状态机 → 403。"""
    character_id = _create_global_character(client)
    other_headers = _login_headers(client.app.state.store, "normal_user_b")
    resp = client.patch(
        f"/api/workspace/characters/{character_id}/state-machine",
        json={"desire_text": "被篡改的欲望"},
        headers=other_headers,
    )
    assert resp.status_code == 403, resp.text


# ================================================================
#  全局人物写操作 — 管理员放行
# ================================================================


def test_admin_can_update_global_character(client: TestClient) -> None:
    character_id = _create_global_character(client)
    admin_headers = _admin_headers(client.app.state.store)
    resp = client.patch(
        f"/api/workspace/characters/{character_id}",
        json={"profile_text": "管理员修订的资料"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True


def test_admin_can_upload_and_delete_global_character(client: TestClient) -> None:
    character_id = _create_global_character(client)
    admin_headers = _admin_headers(client.app.state.store)
    resp = client.post(
        f"/api/workspace/characters/{character_id}/image",
        files=_png_file(),
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True

    resp = client.delete(f"/api/workspace/characters/{character_id}", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert _workspace_db(client).get_character(character_id) is None


# ================================================================
#  归属人物写操作 — 归属校验必过（不得被 book_id 分支绕过）
# ================================================================


def test_book_character_write_by_non_owner_forbidden(client: TestClient) -> None:
    """用户 B 修改用户 A 书下的人物 → 403（确认归属校验不可绕过）。"""
    book = client.post("/api/workspace/books", json={"title": "A 的书"})
    assert book.status_code == 200
    book_id = book.json()["item"]["id"]
    char = client.post(f"/api/workspace/books/{book_id}/characters", json={"name": "主角"})
    character_id = char.json()["item"]["id"]

    other_headers = _login_headers(client.app.state.store, "normal_user_b")
    resp = client.patch(
        f"/api/workspace/characters/{character_id}",
        json={"profile_text": "越权修改"},
        headers=other_headers,
    )
    assert resp.status_code == 403, resp.text
    resp = client.delete(f"/api/workspace/characters/{character_id}", headers=other_headers)
    assert resp.status_code == 403, resp.text
    resp = client.post(
        f"/api/workspace/characters/{character_id}/image",
        files=_png_file(),
        headers=other_headers,
    )
    assert resp.status_code == 403, resp.text


def test_book_character_state_machine_write_by_non_owner_forbidden(client: TestClient) -> None:
    book = client.post("/api/workspace/books", json={"title": "A 的书"})
    book_id = book.json()["item"]["id"]
    char = client.post(f"/api/workspace/books/{book_id}/characters", json={"name": "主角"})
    character_id = char.json()["item"]["id"]

    other_headers = _login_headers(client.app.state.store, "normal_user_b")
    resp = client.patch(
        f"/api/workspace/characters/{character_id}/state-machine",
        json={"desire_text": "越权修改"},
        headers=other_headers,
    )
    assert resp.status_code == 403, resp.text


# ================================================================
#  读操作维持现状 — 全局人物对登录用户可读
# ================================================================


def test_global_character_read_open_to_logged_in_users(client: TestClient) -> None:
    character_id = _create_global_character(client)
    other_headers = _login_headers(client.app.state.store, "normal_user_b")
    resp = client.get(f"/api/workspace/characters/{character_id}", headers=other_headers)
    assert resp.status_code == 200, resp.text
    resp = client.get(
        f"/api/workspace/characters/{character_id}/state-machine", headers=other_headers
    )
    assert resp.status_code == 200, resp.text
