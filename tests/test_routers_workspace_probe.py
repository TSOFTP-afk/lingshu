"""写作探针伴随机制 — workspace API 端点测试。"""
from __future__ import annotations

import contextlib
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "probe-data"
    monkeypatch.setenv("SIMPLE_AI_NOVEL_DATA_DIR", str(data_dir))

    db_bridge = importlib.import_module("lingshu_api.services.db_bridge")
    db_bridge.reset_default_workspace_db()

    from lingshu_api.main import create_app

    app = create_app(tmp_path / "bookstore.db")
    with TestClient(app) as test_client:
        store = app.state.store
        with contextlib.suppress(Exception):
            store.create_user("probeuser", "probepass123")
        token = store.login_user("probeuser", "probepass123")
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client

    db_bridge.reset_default_workspace_db()


def _enable_probe(client: TestClient, *, probe_enabled: bool = True) -> None:
    """通过 AI 设置 API 启用写作探针。"""
    payload = client.get("/api/settings/ai").json()
    payload["profiles"]["writing_probe"].update({
        "probe_enabled": probe_enabled,
        "interval_seconds": 8,
        "auto_write_threshold": 0.55,
    })
    resp = client.put("/api/settings/ai", json=payload)
    assert resp.status_code == 200


def _create_book_with_chapter(client: TestClient, *, content: str = "") -> tuple[int, int]:
    """创建书籍 + 章节，可选填充正文，返回 (book_id, chapter_id)。"""
    book_id = client.post("/api/workspace/books", json={"title": "探针测试书"}).json()["item"]["id"]
    chapter_id = client.post(
        f"/api/workspace/books/{book_id}/chapters", json={"title": "第1章"}
    ).json()["item"]["id"]
    if content:
        client.patch(
            f"/api/workspace/chapters/{chapter_id}",
            json={"content": content},
        )
    return book_id, chapter_id


def test_trigger_writing_probe_disabled_returns_403(client: TestClient) -> None:
    """探针未启用时触发扫描应返回 403。"""
    book_id, chapter_id = _create_book_with_chapter(client, content="陆小川说：你好。")
    resp = client.post(f"/api/workspace/books/{book_id}/chapters/{chapter_id}/writing-probe")
    assert resp.status_code == 403


def test_trigger_writing_probe_enabled_returns_drafts(client: TestClient) -> None:
    """探针启用后触发扫描，规则识别新人物应写入草稿。"""
    _enable_probe(client)
    # 使用对话模式触发新人物识别（陆小川不在 characters 表中）
    content = (
        "陆小川推开门，皱眉看向远方。\n"
        "他低声说道：\"你确定要走这条路？\"\n"
        "苏晚晴叹了口气，点点头。\n"
    )
    book_id, chapter_id = _create_book_with_chapter(client, content=content)
    resp = client.post(f"/api/workspace/books/{book_id}/chapters/{chapter_id}/writing-probe")
    assert resp.status_code == 200
    data = resp.json()
    assert "character_drafts" in data
    assert isinstance(data["character_drafts"], list)
    # 至少识别出一个新人物草稿
    assert len(data["character_drafts"]) >= 1


def test_list_writing_probe_drafts_isolated_per_chapter(client: TestClient) -> None:
    """草稿按章节独立展示，不串章。"""
    _enable_probe(client)
    content_a = "方寒抬头望天，喃喃自语。\n"
    content_b = "陈平安走入书院，环顾四周。\n"
    book_id, ch_a = _create_book_with_chapter(client, content=content_a)
    ch_b = client.post(
        f"/api/workspace/books/{book_id}/chapters", json={"title": "第2章"}
    ).json()["item"]["id"]
    client.patch(f"/api/workspace/chapters/{ch_b}", json={"content": content_b})

    client.post(f"/api/workspace/books/{book_id}/chapters/{ch_a}/writing-probe")
    client.post(f"/api/workspace/books/{book_id}/chapters/{ch_b}/writing-probe")

    drafts_a = client.get(
        f"/api/workspace/books/{book_id}/chapters/{ch_a}/writing-probe/drafts"
    ).json()["items"]
    drafts_b = client.get(
        f"/api/workspace/books/{book_id}/chapters/{ch_b}/writing-probe/drafts"
    ).json()["items"]

    # 每章草稿独立，payload 中 chapter_id 应匹配查询章节
    for d in drafts_a:
        assert d["payload"]["chapter_id"] == ch_a
    for d in drafts_b:
        assert d["payload"]["chapter_id"] == ch_b
    # 两章草稿不重叠
    uids_a = {d["card_uid"] for d in drafts_a}
    uids_b = {d["card_uid"] for d in drafts_b}
    assert not (uids_a & uids_b)


def test_list_drafts_includes_run_id(client: TestClient) -> None:
    """草稿条目应包含 run_id 字段。"""
    _enable_probe(client)
    # 使用动作模式（抬头/转身）确保规则识别
    book_id, chapter_id = _create_book_with_chapter(client, content="李寒山抬头望天，转身离开。\n")
    client.post(f"/api/workspace/books/{book_id}/chapters/{chapter_id}/writing-probe")
    drafts = client.get(
        f"/api/workspace/books/{book_id}/chapters/{chapter_id}/writing-probe/drafts"
    ).json()["items"]
    assert drafts
    for d in drafts:
        assert "run_id" in d
        assert isinstance(d["run_id"], int)


def test_apply_summary_writes_to_chapter(client: TestClient) -> None:
    """概要写回应更新 chapters.summary_text 并标记草稿 applied。"""
    _enable_probe(client)
    book_id, chapter_id = _create_book_with_chapter(client, content="主角在山洞中修行。")
    summary_text = "本章描述主角在山洞中悟道的过程。"
    resp = client.post(
        f"/api/workspace/chapters/{chapter_id}/apply-summary",
        json={"summary_text": summary_text},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    # 校验章节概要已更新
    chapter = client.get(f"/api/workspace/chapters/{chapter_id}").json()
    assert chapter["summary_text"] == summary_text


def test_apply_summary_rejects_empty_text(client: TestClient) -> None:
    """空概要应返回 400。"""
    _enable_probe(client)
    _, chapter_id = _create_book_with_chapter(client, content="...")
    resp = client.post(
        f"/api/workspace/chapters/{chapter_id}/apply-summary",
        json={"summary_text": "   "},
    )
    assert resp.status_code == 400


def test_appearing_characters_filters_by_chapter(client: TestClient) -> None:
    """appearing-characters 端点返回当前章节出现的现有人物（按 appear_count 降序）。"""
    # 不依赖 probe_enabled
    book_id, chapter_id = _create_book_with_chapter(client)
    # 创建两个现有人物
    db_provider = client.app.state.workspace_db_provider
    wdb = db_provider.get()
    char_a_id = wdb.db.create_character(book_id, "林青锋")
    char_b_id = wdb.db.create_character(book_id, "陈玄")
    # 林青锋多次出现，陈玄只出现一次
    content = (
        "林青锋踏入大厅，环顾四周。\n"
        "林青锋低声说道：\"这里有什么？\"\n"
        "陈玄点了点头。"
    )
    client.patch(f"/api/workspace/chapters/{chapter_id}", json={"content": content})

    resp = client.get(
        f"/api/workspace/books/{book_id}/chapters/{chapter_id}/appearing-characters"
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    # 林青锋应排在前面（出现次数更多）
    names = [it["name"] for it in items]
    assert names[0] == "林青锋"
    assert names[1] == "陈玄"
    assert items[0]["appear_count"] >= 2
    assert items[1]["appear_count"] >= 1


def test_appearing_characters_excludes_non_appearing(client: TestClient) -> None:
    """不出现在章节中的现有人物不应返回。"""
    book_id, chapter_id = _create_book_with_chapter(client)
    db_provider = client.app.state.workspace_db_provider
    wdb = db_provider.get()
    wdb.db.create_character(book_id, "出场人物A")
    wdb.db.create_character(book_id, "未出场人物B")
    content = "出场人物A挥剑前行。"
    client.patch(f"/api/workspace/chapters/{chapter_id}", json={"content": content})

    resp = client.get(
        f"/api/workspace/books/{book_id}/chapters/{chapter_id}/appearing-characters"
    )
    items = resp.json()["items"]
    names = [it["name"] for it in items]
    assert "出场人物A" in names
    assert "未出场人物B" not in names


def test_writeback_all_applies_character_drafts(client: TestClient) -> None:
    """writeback-all 应将人物草稿写回 characters 表并标记 applied。"""
    _enable_probe(client)
    # 使用对话模式（喝道）+ 动作模式（皱眉/转身）确保规则识别
    content = "夏侯惇皱眉转身，喝道：\"杀！\"\n"
    book_id, chapter_id = _create_book_with_chapter(client, content=content)

    trigger = client.post(f"/api/workspace/books/{book_id}/chapters/{chapter_id}/writing-probe")
    assert trigger.status_code == 200
    drafts_before = trigger.json()["character_drafts"]
    assert drafts_before  # 确认有草稿

    wb_resp = client.post(
        f"/api/workspace/books/{book_id}/chapters/{chapter_id}/writing-probe/writeback-all"
    )
    assert wb_resp.status_code == 200
    wb_data = wb_resp.json()
    assert wb_data["ok"] is True
    assert wb_data["success"] >= 1

    # characters 表应有对应人物
    db_provider = client.app.state.workspace_db_provider
    wdb = db_provider.get()
    chars = wdb.db.list_characters(book_id)
    char_names = [str(c["name"]) for c in chars]
    assert any("夏侯惇" in n for n in char_names)

    # 草稿状态应为 applied
    drafts_after = client.get(
        f"/api/workspace/books/{book_id}/chapters/{chapter_id}/writing-probe/drafts"
    ).json()["items"]
    char_drafts = [d for d in drafts_after if d["card_type"] == "writing_probe_character"]
    assert char_drafts
    for d in char_drafts:
        assert d["status"] == "applied"


def test_trigger_probe_requires_login(client: TestClient) -> None:
    """未登录触发探针应返回 401。"""
    book_id, chapter_id = _create_book_with_chapter(client, content="x")
    # 清掉 Authorization
    saved_auth = client.headers.pop("Authorization", None)
    try:
        resp = client.post(f"/api/workspace/books/{book_id}/chapters/{chapter_id}/writing-probe")
        assert resp.status_code == 401
    finally:
        if saved_auth:
            client.headers["Authorization"] = saved_auth


def test_trigger_probe_nonexistent_book_returns_404(client: TestClient) -> None:
    """触发不存在书籍的探针应返回 404。"""
    _enable_probe(client)
    resp = client.post("/api/workspace/books/999999/chapters/1/writing-probe")
    assert resp.status_code == 404
