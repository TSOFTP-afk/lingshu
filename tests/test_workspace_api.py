from __future__ import annotations

import contextlib
import importlib
import json
from pathlib import Path

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


def _workspace_db(client: TestClient):
    return client.app.state.workspace_db_provider.get()


class _CapturingSyncService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    def silent_collect(self, book_id: int, user_id: int) -> None:
        self.calls.append(("silent_collect", int(book_id), int(user_id)))

    def sync_book_edit(self, book_id: int, user_id: int) -> None:
        self.calls.append(("sync_book_edit", int(book_id), int(user_id)))


def _import_file(content: str, filename: str = "import.txt") -> dict:
    return {"file": (filename, content.encode("utf-8"), "text/plain")}


def test_workspace_books_volumes_chapters_and_outline(client: TestClient) -> None:
    assert client.get("/api/workspace/health").json() == {"ok": True}
    assert client.get("/api/workspace/books").status_code == 200

    book_resp = client.post("/api/workspace/books", json={"title": "API Test Book"})
    assert book_resp.status_code == 200
    book_id = book_resp.json()["item"]["id"]

    assert client.get(f"/api/workspace/books/{book_id}").status_code == 200
    assert client.patch(f"/api/workspace/books/{book_id}", json={"title": "Renamed Book"}).status_code == 200

    volume_resp = client.post(f"/api/workspace/books/{book_id}/volumes", json={"title": "V1"})
    assert volume_resp.status_code == 200
    volume_id = volume_resp.json()["item"]["id"]
    assert client.patch(f"/api/workspace/volumes/{volume_id}", json={"title": "V1-renamed"}).status_code == 200

    chapter_resp = client.post(f"/api/workspace/books/{book_id}/chapters", json={"title": "Ch1"})
    assert chapter_resp.status_code == 200
    chapter_id = chapter_resp.json()["item"]["id"]
    volume_chapter_resp = client.post(f"/api/workspace/volumes/{volume_id}/chapters", json={"title": "VolCh1"})
    assert volume_chapter_resp.status_code == 200
    volume_chapter_id = volume_chapter_resp.json()["item"]["id"]

    assert client.get(f"/api/workspace/chapters/{chapter_id}").status_code == 200
    volume_chapter = client.get(f"/api/workspace/chapters/{volume_chapter_id}").json()
    assert volume_chapter["book_id"] == book_id
    assert volume_chapter["volume_id"] == volume_id
    assert client.patch(
        f"/api/workspace/chapters/{chapter_id}",
        json={"content": "chapter body", "outline": "chapter outline"},
    ).status_code == 200
    assert client.get(f"/api/workspace/books/{book_id}/chapters").status_code == 200
    book_tree = client.get(f"/api/workspace/books/{book_id}").json()
    assert any(volume["title"] == "V1-renamed" and volume["chapters"] for volume in book_tree["volumes"])
    assert any(volume.get("is_virtual") for volume in book_tree["volumes"])

    outline_payload = client.get(f"/api/workspace/books/{book_id}/outline").json()
    assert outline_payload["outline_schema"]
    assert outline_payload["outline_data"]["fields"]
    outline_data = outline_payload["outline_data"]
    target_readers = "\u7537\u9891"
    serial_status = "\u8fde\u8f7d\u4e2d"
    outline_data["fields"]["target_readers"]["value"] = target_readers
    outline_data["fields"]["serial_status"]["value"] = serial_status
    outline_save = client.put(f"/api/workspace/books/{book_id}/outline", json={"outline_data": outline_data})
    assert outline_save.status_code == 200
    assert target_readers in outline_save.json()["outline_text"]
    assert outline_save.json()["outline_data"]["fields"]["target_readers"]["value"] == target_readers

    assert client.get("/api/workspace/books/99999").status_code == 404
    assert client.patch("/api/workspace/chapters/99999", json={}).status_code == 404


def test_workspace_import_refresh_payload_and_cloud_sync(client: TestClient) -> None:
    from lingshu_api.dependencies import set_sync_service

    app = client.app
    original_sync_service = app.state.sync_service
    sync_service = _CapturingSyncService()
    set_sync_service(app, sync_service)
    try:
        imported = client.post(
            "/api/workspace/import-file",
            params={"skip_volumes": "true"},
            files=_import_file("第一章 初见\n林一抵达镜湖。\n\n第二章 风起\n旧案浮出水面。"),
        )

        assert imported.status_code == 200
        data = imported.json()
        book_id = int(data["book_id"])
        assert data["item"]["id"] == book_id
        assert data["item"]["title"] == "import"
        assert data["first_chapter_id"]
        assert data["stats"]["chapter_count"] >= 1
        assert [call[0] for call in sync_service.calls] == ["silent_collect", "sync_book_edit"]
        assert {call[1] for call in sync_service.calls} == {book_id}

        listed = client.get("/api/workspace/books")
        assert listed.status_code == 200
        assert any(int(item["id"]) == book_id for item in listed.json()["items"])

        sync_service.calls.clear()
        appended = client.post(
            f"/api/workspace/books/{book_id}/import-file",
            params={"skip_volumes": "true"},
            files=_import_file("第三章 再会\n新的线索出现。", filename="append.txt"),
        )

        assert appended.status_code == 200
        appended_data = appended.json()
        assert int(appended_data["book_id"]) == book_id
        assert appended_data["item"]["id"] == book_id
        assert [call[0] for call in sync_service.calls] == ["silent_collect", "sync_book_edit"]
        assert {call[1] for call in sync_service.calls} == {book_id}

        refreshed = client.get(f"/api/workspace/books/{book_id}")
        assert refreshed.status_code == 200
        chapters = [
            chapter
            for volume in refreshed.json()["volumes"]
            for chapter in (volume.get("chapters") or [])
        ]
        assert len(chapters) >= 2
    finally:
        set_sync_service(app, original_sync_service)

def test_workspace_private_routes_require_login_and_owner(client: TestClient) -> None:
    from novel_app.analysis.pipeline import AnalysisPipeline

    book_id = client.post("/api/workspace/books", json={"title": "Private Owner Book"}).json()["item"]["id"]
    chapter_id = client.post(f"/api/workspace/books/{book_id}/chapters", json={"title": "Private Chapter"}).json()["item"]["id"]
    client.patch(
        f"/api/workspace/chapters/{chapter_id}",
        json={"content": "private body", "outline": "private outline"},
    )
    assert client.post(f"/api/workspace/chapters/{chapter_id}/snapshot", json={"label": "baseline"}).status_code == 200

    db = _workspace_db(client)
    run_result = AnalysisPipeline(db.db).create_draft_run(
        book_id,
        {
            "_requires_evidence": False,
            "book_outline": "private outline",
            "chapter_updates": [
                {"chapter_id": chapter_id, "outline": "private outline", "events": ["private event"]}
            ],
        },
        chapters=[db.get_chapter(chapter_id)],
    )
    owner_cards = client.get(f"/api/workspace/analysis/runs/{run_result.run_id}/cards")
    assert owner_cards.status_code == 200
    card_id = owner_cards.json()["items"][0]["id"]

    unauth = {"Authorization": ""}
    private_gets = [
        ("/api/workspace/books", None),
        (f"/api/workspace/books/{book_id}", None),
        (f"/api/workspace/books/{book_id}/chapters", None),
        (f"/api/workspace/books/{book_id}/search", {"q": "private"}),
        (f"/api/workspace/chapters/{chapter_id}", None),
        (f"/api/workspace/books/{book_id}/outline", None),
        (f"/api/workspace/chapters/{chapter_id}/snapshots", None),
        (f"/api/workspace/books/{book_id}/analysis/runs", None),
        (f"/api/workspace/analysis/runs/{run_result.run_id}/cards", None),
    ]
    for path, params in private_gets:
        response = client.get(path, params=params or {}, headers=unauth)
        assert response.status_code == 401, f"{path}: {response.text}"

    other_headers = _login_headers(client.app.state.store, "other_workspace_user")
    other_books = client.get("/api/workspace/books", headers=other_headers)
    assert other_books.status_code == 200
    assert all(item["id"] != book_id for item in other_books.json()["items"])

    for path, params in private_gets[1:]:
        response = client.get(path, params=params or {}, headers=other_headers)
        assert response.status_code == 403, f"{path}: {response.text}"

    assert client.post(
        f"/api/workspace/chapters/{chapter_id}/ai-probability",
        json={"content": "private body"},
        headers=other_headers,
    ).status_code == 403
    unauth_ai = client.post(
        f"/api/workspace/chapters/{chapter_id}/ai-probability",
        json={"content": "private body"},
        headers=unauth,
    )
    assert unauth_ai.status_code == 401
    assert "AI 功能" in unauth_ai.json()["detail"]
    assert client.post(
        f"/api/workspace/chapters/{chapter_id}/polish-selection",
        json={"text": "private body"},
        headers=other_headers,
    ).status_code == 403
    assert client.post(f"/api/workspace/analysis/cards/{card_id}/reject", headers=other_headers).status_code == 403

    assert client.get(f"/api/workspace/books/{book_id}").status_code == 200
    assert client.get(f"/api/workspace/chapters/{chapter_id}").json()["content"] == "private body"


def test_workspace_exact_search_returns_chapter_locations(client: TestClient) -> None:
    book_id = client.post("/api/workspace/books", json={"title": "Search Book"}).json()["item"]["id"]
    chapter_id = client.post(f"/api/workspace/books/{book_id}/chapters", json={"title": "Chapter Search"}).json()["item"]["id"]
    client.patch(
        f"/api/workspace/chapters/{chapter_id}",
        json={"content": "first paragraph\n\nTarget term appears here.\n\nfinal target term"},
    )

    response = client.get(f"/api/workspace/books/{book_id}/search", params={"q": "Target term"})

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    assert items[0]["chapter_id"] == chapter_id
    assert items[0]["field"] == "content"
    assert items[0]["line"] == 3
    assert "Target term appears here" in items[0]["context"]


def test_workspace_analysis_runs_cards_reject_apply_and_refresh_artifacts(client: TestClient) -> None:
    from novel_app.analysis.pipeline import AnalysisPipeline
    from novel_app.rag.retriever import ChapterRetriever

    book_id = client.post("/api/workspace/books", json={"title": "Analysis API Book"}).json()["item"]["id"]
    chapter_id = client.post(f"/api/workspace/books/{book_id}/chapters", json={"title": "Chapter 1"}).json()["item"]["id"]
    client.patch(f"/api/workspace/chapters/{chapter_id}", json={"content": "Lin Yi enters the city."})

    db = _workspace_db(client)
    retriever = ChapterRetriever(storage_dir=str(db.db.data_dir / "rag_index"))
    run_result = AnalysisPipeline(db.db, rag_retriever=retriever).create_draft_run(
        book_id,
        {
            "_requires_evidence": False,
            "book_outline": "Lin Yi enters the city and opens the main plot.",
            "chapter_updates": [
                {"chapter_id": chapter_id, "outline": "Lin Yi enters the city.", "events": ["Lin Yi enters the city"]}
            ],
        },
        chapters=[db.get_chapter(chapter_id)],
    )

    runs_resp = client.get(f"/api/workspace/books/{book_id}/analysis/runs")
    assert runs_resp.status_code == 200
    assert runs_resp.json()["items"][0]["id"] == run_result.run_id
    assert runs_resp.json()["items"][0]["card_count"] >= 2

    cards_resp = client.get(f"/api/workspace/analysis/runs/{run_result.run_id}/cards")
    assert cards_resp.status_code == 200
    cards = cards_resp.json()["items"]
    assert {card["card_type"] for card in cards} >= {"full_payload", "book_summary", "chapters"}
    reject_id = next(card["id"] for card in cards if card["card_type"] == "book_summary")

    reject_resp = client.post(f"/api/workspace/analysis/cards/{reject_id}/reject")
    assert reject_resp.status_code == 200
    assert reject_resp.json()["item"]["status"] == "rejected"

    apply_resp = client.post(f"/api/workspace/analysis/runs/{run_result.run_id}/apply")
    assert apply_resp.status_code == 200
    apply_data = apply_resp.json()
    assert apply_data["ok"] is True
    assert apply_data["weak_evidence_override"] is False
    assert apply_data["updated_chapter_ids"] == [chapter_id]
    assert apply_data["snapshot_id"]
    assert apply_data["applied_cards"] >= 1
    assert apply_data["audit_log_ids"]
    assert "current_state.md" in apply_data["writeback_artifacts"]["truth_files"]
    assert {"book_design", "truth_snapshot", f"chapter:{chapter_id}"}.issubset(
        set(apply_data["writeback_artifacts"]["rag_indexed"])
    )

    assert db.db.list_analysis_apply_snapshots(book_id, run_result.run_id)
    assert db.db.list_analysis_audit_logs(book_id, run_result.run_id)
    assert client.get(f"/api/workspace/chapters/{chapter_id}").json()["outline"] == "Lin Yi enters the city."

    truth_path = Path(db.db.data_dir) / str(book_id) / "current_state.md"
    assert truth_path.exists()
    assert "Analysis API Book" in truth_path.read_text(encoding="utf-8")

    doc_types = _rag_doc_types(db.db.data_dir, book_id)
    assert {"analysis_block", "book_design", "truth_snapshot", "chapter"}.issubset(doc_types)


def test_workspace_analysis_apply_allows_confirmed_weak_evidence(client: TestClient) -> None:
    from novel_app.analysis.pipeline import AnalysisPipeline

    book_id = client.post("/api/workspace/books", json={"title": "Weak Evidence API Book"}).json()["item"]["id"]
    db = _workspace_db(client)
    run_result = AnalysisPipeline(db.db).create_draft_run(
        book_id,
        {
            "_requires_evidence": True,
            "book_outline_form": {"fields": {"primary_parent_tag_id": {"value": "xianxia"}}},
        },
    )

    blocked = client.post(f"/api/workspace/analysis/runs/{run_result.run_id}/apply")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["requires_user_override"] is True

    confirmed = client.post(
        f"/api/workspace/analysis/runs/{run_result.run_id}/apply",
        json={"allow_weak_evidence": True},
    )
    assert confirmed.status_code == 200
    data = confirmed.json()
    assert data["ok"] is True
    assert data["weak_evidence_override"] is True
    assert data["applied_cards"] >= 1
    assert "current_state.md" in data["writeback_artifacts"]["truth_files"]

    run = db.db.get_analysis_run(run_result.run_id)
    run_meta = json.loads(str(run["meta_json"] or "{}"))
    assert run["status"] == "applied"
    assert run_meta["weak_evidence_override"] is True


def _rag_doc_types(data_dir: Path, book_id: int) -> set[str]:
    points_path = Path(data_dir) / "rag_index" / f"book_{book_id}" / "points.json"
    points = json.loads(points_path.read_text(encoding="utf-8"))
    return {str(point.get("payload", {}).get("doc_type") or "") for point in points}


def test_workspace_create_volume_returns_real_sort_order(client: TestClient) -> None:
    """回归测试：create_volume 返回的 sort_order 必须来自数据库实际值，而非硬编码 0。

    覆盖 P0 修复：db_bridge.create_volume 之前手工构造返回值 sort_order=0，
    与底层 library.create_volume 计算的递增 sort_order 不一致。
    """
    book_id = client.post("/api/workspace/books", json={"title": "Sort Order Test Book"}).json()["item"]["id"]

    first = client.post(f"/api/workspace/books/{book_id}/volumes", json={"title": "V1"}).json()["item"]
    second = client.post(f"/api/workspace/books/{book_id}/volumes", json={"title": "V2"}).json()["item"]
    third = client.post(f"/api/workspace/books/{book_id}/volumes", json={"title": "V3"}).json()["item"]

    assert first["sort_order"] == 1, f"首卷 sort_order 应为 1，实际为 {first['sort_order']}"
    assert second["sort_order"] == 2, f"第二卷 sort_order 应为 2，实际为 {second['sort_order']}"
    assert third["sort_order"] == 3, f"第三卷 sort_order 应为 3，实际为 {third['sort_order']}"

    # 返回的 item 必须包含完整字段（id, book_id, title, sort_order）
    for vol in (first, second, third):
        assert vol["id"]
        assert vol["book_id"] == book_id
        assert vol["title"]


def test_workspace_chapter_create_schema_only_accepts_title(client: TestClient) -> None:
    """回归测试：ChapterCreate schema 仅接受 title，content/outline/sort_order 应被拒绝或忽略。

    覆盖 P1 修复：删除 schema 中被后端静默忽略的字段，避免 API 使用者误判。
    """
    book_id = client.post("/api/workspace/books", json={"title": "Chapter Schema Test Book"}).json()["item"]["id"]

    # 仅传 title 应成功
    resp = client.post(f"/api/workspace/books/{book_id}/chapters", json={"title": "Only Title"})
    assert resp.status_code == 200
    chapter = resp.json()["item"]
    assert chapter["title"] == "Only Title"
    # 新建章节正文/大纲应为空，而非来自请求体
    assert chapter.get("content", "") == ""
    assert chapter.get("outline", "") == ""

    # 多传未知字段应被 Pydantic 忽略（默认 extra=ignore）而非报错
    extra_resp = client.post(
        f"/api/workspace/books/{book_id}/chapters",
        json={"title": "With Extra", "content": "should be ignored", "outline": "ignored", "sort_order": 99},
    )
    assert extra_resp.status_code == 200
    extra_chapter = extra_resp.json()["item"]
    assert extra_chapter["title"] == "With Extra"
    assert extra_chapter.get("content", "") == ""
    assert extra_chapter.get("outline", "") == ""
