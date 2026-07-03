from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
from threading import Event

import pytest
from fastapi.testclient import TestClient

from lingshu_api.services.db_bridge import WorkspaceDB
from lingshu_api.ws.chat import _build_chat_context_prompt


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
        # 将 token 也存到 headers 中供 WebSocket 测试使用
        test_client.headers["X-Test-Token"] = token
        yield test_client

    db_bridge.reset_default_workspace_db()


def test_chat_websocket_reports_protocol_errors(client: TestClient) -> None:
    token = client.headers["X-Test-Token"]
    with client.websocket_connect("/ws/chat") as ws:
        # WebSocket 认证
        ws.send_json({"type": "auth", "payload": {"token": token}})
        auth_resp = ws.receive_json()
        assert auth_resp["type"] == "auth_ok"

        ws.send_json({"type": "unknown_test", "task_id": "t1"})
        assert ws.receive_json()["type"] == "error"

        ws.send_text("not valid json{{{")
        assert ws.receive_json()["type"] == "error"


def test_chat_context_includes_persona_and_current_draft(tmp_path) -> None:
    db = WorkspaceDB(tmp_path / "novels.db")
    try:
        book = db.create_book("Test Book")
        book_id = int(book["id"])
        chapter = db.create_chapter(book_id, "Chapter 1")
        chapter_id = int(chapter["id"])
        db.update_chapter(chapter_id, outline="chapter outline", content="saved draft")
        character = db.create_character(book_id, "Lin Yi")
        character_id = int(character["id"])
        db.update_character(character_id, role="protagonist", profile_text="calm gatekeeper")

        context = _build_chat_context_prompt(
            db,
            book_id=book_id,
            chapter_id=chapter_id,
            ai_character_id=character_id,
            latest_user_message="What do you think?",
            current_content="unsaved draft wins",
        )

        assert "Test Book" in context
        assert "Chapter 1" in context
        assert "chapter outline" in context
        assert "unsaved draft wins" in context
        assert "What do you think?" in context
        assert "Lin Yi" in context
        assert "calm gatekeeper" in context
    finally:
        db.close()


@pytest.mark.parametrize("path", ["/ws/generation", "/ws/review"])
def test_business_websockets_accept_connections(client: TestClient, path: str) -> None:
    token = client.headers["X-Test-Token"]
    with client.websocket_connect(path) as ws:
        # WebSocket 认证
        ws.send_json({"type": "auth", "payload": {"token": token}})
        auth_resp = ws.receive_json()
        assert auth_resp["type"] == "auth_ok"


class _CaptureManager:
    def __init__(self) -> None:
        self.messages = []

    async def send(self, client_id: str, message: dict) -> None:
        self.messages.append({"client_id": client_id, **message})


class _FakeAnalysisService:
    def __init__(
        self,
        *,
        source_requests: bool = False,
        model: str = "",
        one_shot_payload: dict | None = None,
    ) -> None:
        self.calls = []
        self.source_requests = source_requests
        self.model = model
        self.base_url = "https://api.example.test/v1"
        self.one_shot_payload = one_shot_payload

    def analyze_book_level1(self, **kwargs):
        self.calls.append(("level1", kwargs))
        return {
            "level": 1,
            "chunk_index": kwargs["chunk_index"],
            "source_facts": [
                {
                    "fact_id": "f1",
                    "chapter_id": kwargs["chapter_ids"][0],
                    "chunk_id": kwargs["chunk_id"],
                    "claim": "Lin Yi enters the city",
                    "evidence_quote": "Lin Yi enters the city",
                }
            ],
        }

    def analyze_book_level2(self, **kwargs):
        self.calls.append(("level2", kwargs))
        return {
            "level": 2,
            "group_index": kwargs["group_index"],
            "merged_events": ["Lin Yi enters the city"],
        }

    def analyze_book_level3_draft(self, **kwargs):
        self.calls.append(("level3", kwargs))
        chapter_id = kwargs["chapters"][0]["id"]
        payload = {
            "_requires_evidence": True,
            "book_outline": "Lin Yi enters the city and opens the main plot.",
            "chapter_updates": [
                {
                    "chapter_id": chapter_id,
                    "outline": "Lin Yi enters the city.",
                    "events": ["Lin Yi enters the city"],
                    "source_block_uid": f"analysis-chapter-{chapter_id}-part-001",
                    "source_quote": "Lin Yi enters the city",
                }
            ],
        }
        if self.source_requests:
            payload["source_requests"] = [
                {
                    "request_id": "review-1",
                    "chapter_id": chapter_id,
                    "source_block_uid": f"analysis-chapter-{chapter_id}-part-001",
                    "target_field": "chapter_updates",
                }
            ]
        return payload

    def analyze_book_level3_finalize(self, **kwargs):
        self.calls.append(("finalize", kwargs))
        draft = dict(kwargs["draft_payload"])
        draft.pop("source_requests", None)
        draft["_meta"] = {"finalized": True}
        draft["book_outline"] = "finalized outline"
        return draft

    def analyze_book_one_shot(self, **kwargs):
        self.calls.append(("one_shot", kwargs))
        if isinstance(self.one_shot_payload, dict):
            return dict(self.one_shot_payload)
        chapter_id = kwargs["chapters"][0]["id"]
        return {
            "_requires_evidence": True,
            "book_outline": "One-shot outline",
            "chapter_updates": [
                {
                    "chapter_id": chapter_id,
                    "outline": "Lin Yi enters the city.",
                    "events": ["Lin Yi enters the city"],
                    "source_block_uid": f"analysis-chapter-{chapter_id}-part-001",
                    "source_quote": "Lin Yi enters the city",
                }
            ],
        }


legacy_analysis_removed = pytest.mark.skip(
    reason="legacy /ws/analysis pyramid pipeline was removed; use /ws/analysis-v3"
)


@legacy_analysis_removed
def test_analysis_websocket_pipeline_runs_three_levels_and_creates_draft_run(tmp_path, monkeypatch) -> None:
    db = WorkspaceDB(tmp_path / "novels.db")
    try:
        book = db.create_book("Analysis Book")
        book_id = int(book["id"])
        chapter = db.create_chapter(book_id, "Chapter 1")
        chapter_id = int(chapter["id"])
        db.update_chapter(chapter_id, outline="", content="Lin Yi enters the city.")
        db.update_book_world(book_id, "world rule: spirit veins decide power")

        service = _FakeAnalysisService()
        fast_extra = {"temperature": 0.1}
        final_extra = {"temperature": 0.2}
        monkeypatch.setattr("lingshu_api.ws.analysis_ws.get_workspace_db", lambda: db)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws._create_ai_service", lambda purpose: service)
        monkeypatch.setattr(
            "lingshu_api.ws.analysis_ws.load_ai_settings",
            lambda *args, **kwargs: {
                "book_analysis_concurrency": "1",
                "book_analysis_fast_extra_body": fast_extra,
                "book_analysis_final_extra_body": json.dumps(final_extra),
            },
        )
        monkeypatch.setattr("lingshu_api.ws.analysis_ws._create_analysis_retriever", lambda database: None)

        from lingshu_api.ws.analysis_ws import _run_analysis

        manager = _CaptureManager()
        asyncio.run(_run_analysis(manager, "client", "task", book_id, Event()))

        result = next(message for message in manager.messages if message["type"] == "result")
        assert result["payload"]["status"] == "ok"
        assert result["payload"]["run_id"]
        assert result["payload"]["card_count"] >= 2
        assert [call[0] for call in service.calls] == ["level1", "level2", "level3"]
        assert all(message.get("payload", {}).get("stage") != "source_review" for message in manager.messages)

        level1_kwargs = next(kwargs for name, kwargs in service.calls if name == "level1")
        level2_kwargs = next(kwargs for name, kwargs in service.calls if name == "level2")
        level3_kwargs = next(kwargs for name, kwargs in service.calls if name == "level3")
        assert level1_kwargs["extra_body"] == fast_extra
        assert level2_kwargs["extra_body"] == fast_extra
        assert level3_kwargs["extra_body"] == final_extra
        assert "spirit veins" in str(level3_kwargs["world_entries"])

        run = db.db.get_analysis_run(result["payload"]["run_id"])
        assert run is not None
        assert run["status"] == "awaiting_review"
        run_meta = json.loads(str(run["meta_json"] or "{}"))
        assert run_meta["source"] == "ws_analysis"
        assert run_meta["task_id"] == "task"
        assert run_meta["source_review_executed"] is False
        cards = db.db.list_analysis_cards(result["payload"]["run_id"])
        assert {card["card_type"] for card in cards} >= {"full_payload", "book_summary", "chapters"}
    finally:
        db.close()


@legacy_analysis_removed
def test_analysis_websocket_uses_one_shot_for_short_book_and_1m_model(tmp_path, monkeypatch) -> None:
    db = WorkspaceDB(tmp_path / "novels.db")
    try:
        book = db.create_book("One Shot Book")
        book_id = int(book["id"])
        chapter = db.create_chapter(book_id, "Chapter 1")
        chapter_id = int(chapter["id"])
        db.update_chapter(chapter_id, outline="", content="Lin Yi enters the city.")

        service = _FakeAnalysisService(model="openai/gpt-4.1")
        monkeypatch.setattr("lingshu_api.ws.analysis_ws.get_workspace_db", lambda: db)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws._create_ai_service", lambda purpose: service)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws.load_ai_settings", lambda *args, **kwargs: {})
        monkeypatch.setattr("lingshu_api.ws.analysis_ws._create_analysis_retriever", lambda database: None)

        from lingshu_api.ws.analysis_ws import _run_analysis

        manager = _CaptureManager()
        asyncio.run(_run_analysis(manager, "client", "task", book_id, Event(), analysis_mode="one_shot"))

        result = next(message for message in manager.messages if message["type"] == "result")
        assert result["payload"]["status"] == "ok"
        assert [call[0] for call in service.calls] == ["one_shot"]
        assert any(message.get("payload", {}).get("stage") == "full_book" for message in manager.messages)

        one_shot_kwargs = service.calls[0][1]
        assert "Lin Yi enters the city." in one_shot_kwargs["source_blocks"][0]["text"]

        run = db.db.get_analysis_run(result["payload"]["run_id"])
        run_meta = json.loads(str(run["meta_json"] or "{}"))
        assert run_meta["analysis_mode"] == "one_shot"
        assert run_meta["one_shot_used"] is True
        assert run_meta["matched_context_model"] == "gpt-4.1"
        assert run_meta["context_tokens"] >= 1_000_000
        assert run_meta["book_char_count"] == len("LinYientersthecity.")
    finally:
        db.close()


@legacy_analysis_removed
def test_analysis_websocket_keeps_pyramid_for_non_1m_model(tmp_path, monkeypatch) -> None:
    db = WorkspaceDB(tmp_path / "novels.db")
    try:
        book = db.create_book("Pyramid Book")
        book_id = int(book["id"])
        chapter = db.create_chapter(book_id, "Chapter 1")
        db.update_chapter(int(chapter["id"]), outline="", content="Lin Yi enters the city.")

        service = _FakeAnalysisService(model="deepseek-chat")
        monkeypatch.setattr("lingshu_api.ws.analysis_ws.get_workspace_db", lambda: db)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws._create_ai_service", lambda purpose: service)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws.load_ai_settings", lambda *args, **kwargs: {})
        monkeypatch.setattr("lingshu_api.ws.analysis_ws._create_analysis_retriever", lambda database: None)

        from lingshu_api.ws.analysis_ws import _run_analysis

        manager = _CaptureManager()
        asyncio.run(_run_analysis(manager, "client", "task", book_id, Event()))

        assert [call[0] for call in service.calls] == ["level1", "level2", "level3"]
        assert all(message.get("payload", {}).get("stage") != "full_book" for message in manager.messages)
    finally:
        db.close()


@legacy_analysis_removed
def test_analysis_websocket_pyramid_mode_ignores_one_shot_capable_model(tmp_path, monkeypatch) -> None:
    db = WorkspaceDB(tmp_path / "novels.db")
    try:
        book = db.create_book("Pyramid Switch Book")
        book_id = int(book["id"])
        chapter = db.create_chapter(book_id, "Chapter 1")
        db.update_chapter(int(chapter["id"]), outline="", content="Lin Yi enters the city.")

        service = _FakeAnalysisService(model="gpt-4.1")
        monkeypatch.setattr("lingshu_api.ws.analysis_ws.get_workspace_db", lambda: db)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws._create_ai_service", lambda purpose: service)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws.load_ai_settings", lambda *args, **kwargs: {})
        monkeypatch.setattr("lingshu_api.ws.analysis_ws._create_analysis_retriever", lambda database: None)

        from lingshu_api.ws.analysis_ws import _run_analysis

        manager = _CaptureManager()
        asyncio.run(_run_analysis(manager, "client", "task", book_id, Event(), analysis_mode="pyramid"))

        assert [call[0] for call in service.calls] == ["level1", "level2", "level3"]
        assert all(message.get("payload", {}).get("stage") != "full_book" for message in manager.messages)
    finally:
        db.close()


@legacy_analysis_removed
def test_analysis_websocket_one_shot_rejects_unsupported_model(tmp_path, monkeypatch) -> None:
    db = WorkspaceDB(tmp_path / "novels.db")
    try:
        book = db.create_book("Non Long Context Book")
        book_id = int(book["id"])
        chapter = db.create_chapter(book_id, "Chapter 1")
        db.update_chapter(int(chapter["id"]), outline="", content="Lin Yi enters the city.")

        service = _FakeAnalysisService(model="deepseek-chat")
        monkeypatch.setattr("lingshu_api.ws.analysis_ws.get_workspace_db", lambda: db)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws._create_ai_service", lambda purpose: service)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws.load_ai_settings", lambda *args, **kwargs: {})
        monkeypatch.setattr("lingshu_api.ws.analysis_ws._create_analysis_retriever", lambda database: None)

        from lingshu_api.ws.analysis_ws import _run_analysis

        manager = _CaptureManager()
        asyncio.run(_run_analysis(manager, "client", "task", book_id, Event(), analysis_mode="one_shot"))

        error = next(message for message in manager.messages if message["type"] == "error")
        assert "1M+ 上下文模型" in error["payload"]["message"]
        assert service.calls == []
    finally:
        db.close()


@legacy_analysis_removed
def test_analysis_websocket_one_shot_rejects_book_over_limit(tmp_path, monkeypatch) -> None:
    db = WorkspaceDB(tmp_path / "novels.db")
    try:
        book = db.create_book("Large Book")
        book_id = int(book["id"])
        chapter = db.create_chapter(book_id, "Chapter 1")
        db.update_chapter(int(chapter["id"]), outline="", content="A" * 40)

        service = _FakeAnalysisService(model="gpt-4.1")
        monkeypatch.setattr("lingshu_api.ws.analysis_ws.ONE_SHOT_BOOK_CHAR_LIMIT", 20)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws.get_workspace_db", lambda: db)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws._create_ai_service", lambda purpose: service)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws.load_ai_settings", lambda *args, **kwargs: {})
        monkeypatch.setattr("lingshu_api.ws.analysis_ws._create_analysis_retriever", lambda database: None)

        from lingshu_api.ws.analysis_ws import _run_analysis

        manager = _CaptureManager()
        asyncio.run(_run_analysis(manager, "client", "task", book_id, Event(), analysis_mode="one_shot"))

        error = next(message for message in manager.messages if message["type"] == "error")
        assert "少于" in error["payload"]["message"]
        assert service.calls == []
    finally:
        db.close()


@legacy_analysis_removed
def test_analysis_websocket_one_shot_reports_error_when_payload_is_empty(tmp_path, monkeypatch) -> None:
    db = WorkspaceDB(tmp_path / "novels.db")
    try:
        book = db.create_book("Fallback Book")
        book_id = int(book["id"])
        chapter = db.create_chapter(book_id, "Chapter 1")
        db.update_chapter(int(chapter["id"]), outline="", content="Lin Yi enters the city.")

        service = _FakeAnalysisService(model="gpt-4.1", one_shot_payload={"ok": True})
        monkeypatch.setattr("lingshu_api.ws.analysis_ws.get_workspace_db", lambda: db)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws._create_ai_service", lambda purpose: service)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws.load_ai_settings", lambda *args, **kwargs: {})
        monkeypatch.setattr("lingshu_api.ws.analysis_ws._create_analysis_retriever", lambda database: None)

        from lingshu_api.ws.analysis_ws import _run_analysis

        manager = _CaptureManager()
        asyncio.run(_run_analysis(manager, "client", "task", book_id, Event(), analysis_mode="one_shot"))

        error = next(message for message in manager.messages if message["type"] == "error")
        assert "一次性读完分析失败" in error["payload"]["message"]
        assert [call[0] for call in service.calls] == ["one_shot"]
    finally:
        db.close()


@legacy_analysis_removed
def test_analysis_websocket_pipeline_finalizes_when_source_review_requested(tmp_path, monkeypatch) -> None:
    db = WorkspaceDB(tmp_path / "novels.db")
    try:
        book = db.create_book("Source Review Book")
        book_id = int(book["id"])
        chapter = db.create_chapter(book_id, "Chapter 1")
        chapter_id = int(chapter["id"])
        db.update_chapter(chapter_id, outline="", content="Lin Yi enters the city.")

        service = _FakeAnalysisService(source_requests=True)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws.get_workspace_db", lambda: db)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws._create_ai_service", lambda purpose: service)
        monkeypatch.setattr("lingshu_api.ws.analysis_ws.load_ai_settings", lambda *args, **kwargs: {})
        monkeypatch.setattr("lingshu_api.ws.analysis_ws._create_analysis_retriever", lambda database: None)

        from lingshu_api.ws.analysis_ws import _run_analysis

        manager = _CaptureManager()
        asyncio.run(_run_analysis(manager, "client", "task", book_id, Event()))

        result = next(message for message in manager.messages if message["type"] == "result")
        assert result["payload"]["status"] == "ok"
        assert [call[0] for call in service.calls] == ["level1", "level2", "level3", "finalize"]
        assert any(message.get("payload", {}).get("stage") == "source_review" for message in manager.messages)

        finalize_kwargs = next(kwargs for name, kwargs in service.calls if name == "finalize")
        assert finalize_kwargs["extra_body"] is None
        assert finalize_kwargs["source_context"]["requests"][0]["request_id"] == "review-1"
        assert finalize_kwargs["source_context"]["blocks"][0]["block_uid"] == f"analysis-chapter-{chapter_id}-part-001"

        run = db.db.get_analysis_run(result["payload"]["run_id"])
        run_meta = json.loads(str(run["meta_json"] or "{}"))
        assert run_meta["source_review_executed"] is True
        assert run_meta["source_review_request_count"] == 1
    finally:
        db.close()
