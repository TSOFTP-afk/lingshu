"""伏笔管理 API — routers/foreshadows.py 端点测试。"""
from __future__ import annotations

import contextlib
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "foreshadow-data"
    monkeypatch.setenv("SIMPLE_AI_NOVEL_DATA_DIR", str(data_dir))

    db_bridge = importlib.import_module("lingshu_api.services.db_bridge")
    db_bridge.reset_default_workspace_db()

    from lingshu_api.main import create_app

    app = create_app(tmp_path / "bookstore.db")
    with TestClient(app) as test_client:
        store = app.state.store
        with contextlib.suppress(Exception):
            store.create_user("foreshadow_user", "foreshadow_pass123")
        token = store.login_user("foreshadow_user", "foreshadow_pass123")
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client

    db_bridge.reset_default_workspace_db()


def _get_other_user_token(client: TestClient) -> str:
    """在同一 app 内创建第二个用户并返回其登录 token，用于测试 ownership 隔离。"""
    store = client.app.state.store
    with contextlib.suppress(Exception):
        store.create_user("other_user", "other_pass123")
    return store.login_user("other_user", "other_pass123")


def _create_book(client: TestClient, *, title: str = "伏笔测试书") -> int:
    return client.post("/api/workspace/books", json={"title": title}).json()["item"]["id"]


def _create_chapter(client: TestClient, book_id: int, *, title: str = "第一章") -> int:
    return client.post(
        f"/api/workspace/books/{book_id}/chapters", json={"title": title}
    ).json()["item"]["id"]


def _create_foreshadow(
    client: TestClient,
    book_id: int,
    *,
    description: str = "主角玉佩的微光",
    status: str = "pending",
    priority: str = "medium",
    setup_chapter_id: int | None = None,
    payoff_chapter_id: int | None = None,
    resolution_note: str = "",
) -> dict:
    resp = client.post(
        f"/api/workspace/books/{book_id}/foreshadows",
        json={
            "description": description,
            "status": status,
            "priority": priority,
            "setup_chapter_id": setup_chapter_id,
            "payoff_chapter_id": payoff_chapter_id,
            "resolution_note": resolution_note,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["item"]


# ================================================================
#  GET /foreshadows
# ================================================================

def test_list_foreshadows_empty(client: TestClient) -> None:
    book_id = _create_book(client)
    resp = client.get(f"/api/workspace/books/{book_id}/foreshadows")
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


def test_list_foreshadows_returns_created(client: TestClient) -> None:
    book_id = _create_book(client)
    _create_foreshadow(client, book_id, description="伏笔A")
    _create_foreshadow(client, book_id, description="伏笔B")

    resp = client.get(f"/api/workspace/books/{book_id}/foreshadows")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    descriptions = {it["description"] for it in items}
    assert descriptions == {"伏笔A", "伏笔B"}


def test_list_foreshadows_status_filter(client: TestClient) -> None:
    book_id = _create_book(client)
    _create_foreshadow(client, book_id, description="待回收", status="pending")
    _create_foreshadow(client, book_id, description="已回收", status="resolved")
    _create_foreshadow(client, book_id, description="已废弃", status="abandoned")

    resp = client.get(f"/api/workspace/books/{book_id}/foreshadows?status=resolved")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["description"] == "已回收"
    assert items[0]["status"] == "resolved"


def test_list_foreshadows_includes_chapter_titles(client: TestClient) -> None:
    book_id = _create_book(client)
    setup_ch = _create_chapter(client, book_id, title="埋设章")
    payoff_ch = _create_chapter(client, book_id, title="回收章")
    _create_foreshadow(
        client, book_id,
        description="玉佩之谜",
        setup_chapter_id=setup_ch,
        payoff_chapter_id=payoff_ch,
    )

    items = client.get(f"/api/workspace/books/{book_id}/foreshadows").json()["items"]
    assert len(items) == 1
    assert items[0]["setup_chapter_title"] == "埋设章"
    assert items[0]["payoff_chapter_title"] == "回收章"


# ================================================================
#  POST /foreshadows
# ================================================================

def test_create_foreshadow_returns_item(client: TestClient) -> None:
    book_id = _create_book(client)
    item = _create_foreshadow(
        client, book_id,
        description="主角胸口玉佩的微光",
        status="pending",
        priority="high",
        resolution_note="待第三章揭示",
    )
    assert item["id"] > 0
    assert item["book_id"] == book_id
    assert item["description"] == "主角胸口玉佩的微光"
    assert item["status"] == "pending"
    assert item["priority"] == "high"
    assert item["source"] == "manual"
    assert item["resolution_note"] == "待第三章揭示"
    assert item["fact_uid"] == ""
    assert item["created_at"]
    assert item["updated_at"]


def test_create_foreshadow_rejects_empty_description(client: TestClient) -> None:
    book_id = _create_book(client)
    resp = client.post(
        f"/api/workspace/books/{book_id}/foreshadows",
        json={"description": ""},
    )
    assert resp.status_code == 400
    assert "不能为空" in resp.json()["detail"]


def test_create_foreshadow_rejects_blank_description(client: TestClient) -> None:
    book_id = _create_book(client)
    resp = client.post(
        f"/api/workspace/books/{book_id}/foreshadows",
        json={"description": "   "},
    )
    assert resp.status_code == 400


def test_create_foreshadow_with_chapter_ids(client: TestClient) -> None:
    book_id = _create_book(client)
    setup_ch = _create_chapter(client, book_id, title="第一章")
    payoff_ch = _create_chapter(client, book_id, title="第二章")
    item = _create_foreshadow(
        client, book_id,
        description="玉佩之谜",
        setup_chapter_id=setup_ch,
        payoff_chapter_id=payoff_ch,
    )
    assert item["setup_chapter_id"] == setup_ch
    assert item["payoff_chapter_id"] == payoff_ch


# ================================================================
#  PATCH /foreshadows/{id}
# ================================================================

def test_update_foreshadow_partial_fields(client: TestClient) -> None:
    book_id = _create_book(client)
    item = _create_foreshadow(client, book_id, description="原描述", priority="medium")
    fid = item["id"]

    resp = client.patch(
        f"/api/workspace/foreshadows/{fid}",
        json={"description": "新描述", "status": "resolved", "priority": "high"},
    )
    assert resp.status_code == 200
    updated = resp.json()["item"]
    assert updated["description"] == "新描述"
    assert updated["status"] == "resolved"
    assert updated["priority"] == "high"


def test_update_foreshadow_resolves_with_note(client: TestClient) -> None:
    book_id = _create_book(client)
    item = _create_foreshadow(client, book_id, description="伏笔")
    fid = item["id"]

    resp = client.patch(
        f"/api/workspace/foreshadows/{fid}",
        json={"status": "resolved", "resolution_note": "玉佩乃神物"},
    )
    assert resp.status_code == 200
    updated = resp.json()["item"]
    assert updated["status"] == "resolved"
    assert updated["resolution_note"] == "玉佩乃神物"


def test_update_foreshadow_not_found_returns_404(client: TestClient) -> None:
    resp = client.patch(
        "/api/workspace/foreshadows/999999",
        json={"description": "x"},
    )
    assert resp.status_code == 404
    assert "伏笔不存在" in resp.json()["detail"]


def test_update_foreshadow_rejects_empty_description(client: TestClient) -> None:
    book_id = _create_book(client)
    item = _create_foreshadow(client, book_id, description="原描述")
    fid = item["id"]

    resp = client.patch(
        f"/api/workspace/foreshadows/{fid}",
        json={"description": "  "},
    )
    assert resp.status_code == 400
    assert "不能为空" in resp.json()["detail"]


def test_update_foreshadow_with_chapter_ids(client: TestClient) -> None:
    book_id = _create_book(client)
    setup_ch = _create_chapter(client, book_id, title="埋设章")
    payoff_ch = _create_chapter(client, book_id, title="回收章")
    item = _create_foreshadow(client, book_id, description="伏笔")
    fid = item["id"]

    resp = client.patch(
        f"/api/workspace/foreshadows/{fid}",
        json={"setup_chapter_id": setup_ch, "payoff_chapter_id": payoff_ch},
    )
    assert resp.status_code == 200
    updated = resp.json()["item"]
    assert updated["setup_chapter_id"] == setup_ch
    assert updated["payoff_chapter_id"] == payoff_ch


# ================================================================
#  DELETE /foreshadows/{id}
# ================================================================

def test_delete_foreshadow(client: TestClient) -> None:
    book_id = _create_book(client)
    item = _create_foreshadow(client, book_id, description="待删除")
    fid = item["id"]

    resp = client.delete(f"/api/workspace/foreshadows/{fid}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # 确认已删除
    items = client.get(f"/api/workspace/books/{book_id}/foreshadows").json()["items"]
    assert len(items) == 0


def test_delete_foreshadow_not_found_returns_404(client: TestClient) -> None:
    resp = client.delete("/api/workspace/foreshadows/999999")
    assert resp.status_code == 404


# ================================================================
#  POST /foreshadows/sync
# ================================================================

def test_sync_from_analysis_no_facts_returns_zero(client: TestClient) -> None:
    book_id = _create_book(client)
    resp = client.post(f"/api/workspace/books/{book_id}/foreshadows/sync")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "added": 0}


def test_sync_from_analysis_with_facts(client: TestClient) -> None:
    book_id = _create_book(client)
    # 通过 DB 桥接层插入 analysis_facts
    db_provider = client.app.state.workspace_db_provider
    wdb = db_provider.get()
    run_id = wdb.db.create_analysis_run(book_id, pipeline_version="v3_test")
    wdb.db.replace_analysis_facts(book_id, run_id, [
        {
            "fact_uid": "fact-api-1",
            "subject_entity_uid": "ent-x",
            "fact_type": "foreshadowing",
            "quote_text": "玉佩发光的伏笔",
            "value": {"description": "玉佩乃神物，第三章揭示"},
            "chapter_id": 0,
            "importance_score": 0.8,
            "confidence": 0.9,
            "status": "candidate",
        },
    ])

    resp = client.post(f"/api/workspace/books/{book_id}/foreshadows/sync")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "added": 1}

    items = client.get(f"/api/workspace/books/{book_id}/foreshadows").json()["items"]
    assert len(items) == 1
    assert items[0]["source"] == "auto"
    assert items[0]["fact_uid"] == "fact-api-1"
    assert items[0]["description"] == "玉佩乃神物，第三章揭示"
    assert items[0]["priority"] == "high"  # importance_score=0.8 → high


def test_sync_deduplicates_by_fact_uid(client: TestClient) -> None:
    book_id = _create_book(client)
    db_provider = client.app.state.workspace_db_provider
    wdb = db_provider.get()
    run_id = wdb.db.create_analysis_run(book_id, pipeline_version="v3_test")
    wdb.db.replace_analysis_facts(book_id, run_id, [
        {
            "fact_uid": "fact-dup",
            "subject_entity_uid": "ent-x",
            "fact_type": "foreshadowing",
            "quote_text": "伏笔",
            "value": {},
            "chapter_id": 0,
            "importance_score": 0.5,
            "confidence": 0.8,
            "status": "candidate",
        },
    ])

    # 第一次同步
    resp1 = client.post(f"/api/workspace/books/{book_id}/foreshadows/sync")
    assert resp1.json()["added"] == 1
    # 第二次同步应跳过已存在的 fact_uid
    resp2 = client.post(f"/api/workspace/books/{book_id}/foreshadows/sync")
    assert resp2.json()["added"] == 0

    items = client.get(f"/api/workspace/books/{book_id}/foreshadows").json()["items"]
    assert len(items) == 1


# ================================================================
#  鉴权与 ownership
# ================================================================

def test_list_foreshadows_requires_login(client: TestClient) -> None:
    book_id = _create_book(client)
    saved_auth = client.headers.pop("Authorization", None)
    try:
        resp = client.get(f"/api/workspace/books/{book_id}/foreshadows")
        assert resp.status_code == 401
    finally:
        if saved_auth:
            client.headers["Authorization"] = saved_auth


def test_create_foreshadow_requires_login(client: TestClient) -> None:
    book_id = _create_book(client)
    saved_auth = client.headers.pop("Authorization", None)
    try:
        resp = client.post(
            f"/api/workspace/books/{book_id}/foreshadows",
            json={"description": "x"},
        )
        assert resp.status_code == 401
    finally:
        if saved_auth:
            client.headers["Authorization"] = saved_auth


def test_non_owner_cannot_list_foreshadows(client: TestClient) -> None:
    """非书籍拥有者不应能查看他人书籍的伏笔。"""
    book_id = _create_book(client, title="主人书")
    _create_foreshadow(client, book_id, description="主人的伏笔")

    other_token = _get_other_user_token(client)
    saved = client.headers.pop("Authorization", None)
    try:
        client.headers["Authorization"] = f"Bearer {other_token}"
        resp = client.get(f"/api/workspace/books/{book_id}/foreshadows")
        assert resp.status_code == 403
    finally:
        client.headers["Authorization"] = saved


def test_non_owner_cannot_create_foreshadow(client: TestClient) -> None:
    """非书籍拥有者不应能在他人书籍下新增伏笔。"""
    book_id = _create_book(client, title="主人书")
    other_token = _get_other_user_token(client)
    saved = client.headers.pop("Authorization", None)
    try:
        client.headers["Authorization"] = f"Bearer {other_token}"
        resp = client.post(
            f"/api/workspace/books/{book_id}/foreshadows",
            json={"description": "入侵伏笔"},
        )
        assert resp.status_code == 403
    finally:
        client.headers["Authorization"] = saved


def test_non_owner_cannot_update_foreshadow(client: TestClient) -> None:
    """非书籍拥有者不应能编辑他人书籍的伏笔。"""
    book_id = _create_book(client, title="主人书")
    item = _create_foreshadow(client, book_id, description="原描述")
    other_token = _get_other_user_token(client)
    saved = client.headers.pop("Authorization", None)
    try:
        client.headers["Authorization"] = f"Bearer {other_token}"
        resp = client.patch(
            f"/api/workspace/foreshadows/{item['id']}",
            json={"description": "篡改"},
        )
        assert resp.status_code == 403
    finally:
        client.headers["Authorization"] = saved


def test_non_owner_cannot_delete_foreshadow(client: TestClient) -> None:
    """非书籍拥有者不应能删除他人书籍的伏笔。"""
    book_id = _create_book(client, title="主人书")
    item = _create_foreshadow(client, book_id, description="待保护")
    other_token = _get_other_user_token(client)
    saved = client.headers.pop("Authorization", None)
    try:
        client.headers["Authorization"] = f"Bearer {other_token}"
        resp = client.delete(f"/api/workspace/foreshadows/{item['id']}")
        assert resp.status_code == 403
    finally:
        client.headers["Authorization"] = saved


def test_non_owner_cannot_sync_foreshadows(client: TestClient) -> None:
    """非书籍拥有者不应能触发他人书籍的伏笔同步。"""
    book_id = _create_book(client, title="主人书")
    other_token = _get_other_user_token(client)
    saved = client.headers.pop("Authorization", None)
    try:
        client.headers["Authorization"] = f"Bearer {other_token}"
        resp = client.post(f"/api/workspace/books/{book_id}/foreshadows/sync")
        assert resp.status_code == 403
    finally:
        client.headers["Authorization"] = saved
