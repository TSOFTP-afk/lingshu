from __future__ import annotations

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
        # 创建测试用户并获取认证 Token
        test_client.post("/api/auth/register", json={
            "username": "testuser",
            "password": "testpass123",
            "email": "test@example.com",
        })
        login_resp = test_client.post("/api/auth/login", json={
            "username": "testuser",
            "password": "testpass123",
        })
        token = login_resp.json().get("access_token", "")
        test_client.headers["Authorization"] = f"Bearer {token}"
        yield test_client

    db_bridge.reset_default_workspace_db()


def test_workspace_settings_analysis_pipeline_mode(client: TestClient) -> None:
    default = client.get("/api/settings/workspace")
    assert default.status_code == 200
    assert default.json()["analysis_pipeline_mode"] == "legacy"

    saved = client.put("/api/settings/workspace", json={"analysis_pipeline_mode": "v3"})
    assert saved.status_code == 200
    assert saved.json()["analysis_pipeline_mode"] == "v3"
    assert client.get("/api/settings/workspace").json()["analysis_pipeline_mode"] == "v3"

    fallback = client.put("/api/settings/workspace", json={"analysis_pipeline_mode": "unknown"})
    assert fallback.status_code == 200
    assert fallback.json()["analysis_pipeline_mode"] == "legacy"


def test_analysis_v3_run_routes_create_blocks_and_do_not_pollute_legacy_runs(client: TestClient) -> None:
    assert client.post("/api/workspace/books/999999/analysis-v3/runs", json={}).status_code == 404

    book_id = client.post("/api/workspace/books", json={"title": "V3 API Book"}).json()["item"]["id"]
    empty = client.post(f"/api/workspace/books/{book_id}/analysis-v3/runs", json={})
    assert empty.status_code == 400

    client.post(f"/api/workspace/books/{book_id}/characters", json={"name": "林一"})
    chapter_id = client.post(f"/api/workspace/books/{book_id}/chapters", json={"title": "Chapter 1"}).json()["item"]["id"]
    client.patch(
        f"/api/workspace/chapters/{chapter_id}",
        json={"content": "林一进入城市。\n\n第二段留下《星火伏笔》。"},
    )

    created = client.post(f"/api/workspace/books/{book_id}/analysis-v3/runs", json={"execute_l1": True})
    assert created.status_code == 200
    body = created.json()
    run_id = body["run_id"]
    assert body["status"] == "probes_ready"
    assert body["block_count"] >= 1
    assert body["mention_count"] >= 2
    assert body["entity_count"] >= 2
    assert body["fact_count"] >= 2
    assert body["memory_fact_count"] >= 2
    assert body["card_count"] >= 3
    assert body["probe_plan_count"] >= 1
    assert body["probe_result_count"] >= 1
    assert body["item"]["pipeline_version"].startswith("analysis_v3")

    listed = client.get(f"/api/workspace/books/{book_id}/analysis-v3/runs")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == run_id

    detail = client.get(f"/api/workspace/analysis-v3/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["item"]["block_count"] == body["block_count"]
    assert detail.json()["item"]["mention_count"] == body["mention_count"]
    assert detail.json()["item"]["entity_count"] == body["entity_count"]
    assert detail.json()["item"]["fact_count"] == body["fact_count"]
    assert detail.json()["item"]["card_count"] == body["card_count"]
    assert detail.json()["item"]["probe_result_count"] == body["probe_result_count"]

    blocks = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/blocks")
    assert blocks.status_code == 200
    items = blocks.json()["items"]
    assert len(items) == body["block_count"]
    assert items[0]["chapter_id"] == chapter_id
    assert items[0]["content_hash"]
    assert items[0]["structure_hash"]
    assert "进入城市" in "".join(item["snippet"] for item in items)

    mentions = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/mentions")
    assert mentions.status_code == 200
    mention_items = mentions.json()["items"]
    assert len(mention_items) == body["mention_count"]
    assert {"林一", "星火伏笔"}.issubset({item["quote_text"] for item in mention_items})
    assert all(item["block_uid"] for item in mention_items)
    assert all(item["entity_uid"] for item in mention_items)
    limited_mentions = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/mentions?limit=1")
    assert limited_mentions.status_code == 200
    assert len(limited_mentions.json()["items"]) == 1

    entities = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/entities")
    assert entities.status_code == 200
    entity_items = entities.json()["items"]
    assert len(entity_items) == body["entity_count"]
    assert {"林一", "星火伏笔"}.issubset({item["canonical_name"] for item in entity_items})
    assert all(item["mention_count"] >= 1 for item in entity_items)

    facts = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/facts")
    assert facts.status_code == 200
    fact_items = facts.json()["items"]
    assert len(fact_items) == body["fact_count"]
    assert any("进入城市" in item["quote_text"] for item in fact_items)
    assert any(item["fact_type"] == "foreshadowing" for item in fact_items)
    assert all(item["subject_entity_uid"] for item in fact_items)
    assert all(item["confidence"] >= 0.55 for item in fact_items)
    assert all(item["memory_scope"] for item in fact_items)
    assert all(item["memory_type"] for item in fact_items)
    limited_facts = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/facts?limit=1")
    assert limited_facts.status_code == 200
    assert len(limited_facts.json()["items"]) == 1

    memory = client.post(f"/api/workspace/analysis-v3/runs/{run_id}/steps/memory_layer")
    assert memory.status_code == 200
    assert memory.json()["classified_fact_count"] >= 2
    assert memory.json()["run"]["status"] == "memory_ready"

    probes = client.post(f"/api/workspace/analysis-v3/runs/{run_id}/steps/probes")
    assert probes.status_code == 200
    assert probes.json()["run"]["status"] == "probes_ready"
    assert probes.json()["probe_plan_count"] >= 1
    assert probes.json()["probe_result_count"] >= 1

    probe_plans = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/probes/plans")
    assert probe_plans.status_code == 200
    assert len(probe_plans.json()["items"]) == probes.json()["probe_plan_count"]
    assert all(item["plan"]["source_evidence"] for item in probe_plans.json()["items"])

    probe_results = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/probes/results")
    assert probe_results.status_code == 200
    assert len(probe_results.json()["items"]) == probes.json()["probe_result_count"]
    assert all("source_evidence" in item["result"] for item in probe_results.json()["items"])
    assert all("target_evidence" in item["result"] for item in probe_results.json()["items"])

    cards = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/cards")
    assert cards.status_code == 200
    card_items = cards.json()["items"]
    assert len(card_items) == body["card_count"]
    assert {"v3_character", "v3_world", "v3_book_summary"}.issubset({item["card_type"] for item in card_items})
    assert all(item["card_type"] != "full_payload" for item in card_items)
    assert all(item["dependencies"] for item in card_items)

    events = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/events")
    assert events.status_code == 200
    event_items = events.json()["items"]
    assert len(event_items) == body["card_count"]
    assert all(item["status"] == "processed" for item in event_items)

    rerun = client.post(f"/api/workspace/analysis-v3/runs/{run_id}/steps/entity_mentions")
    assert rerun.status_code == 200
    assert rerun.json()["mention_count"] == body["mention_count"]
    after_rerun = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/mentions").json()["items"]
    assert len(after_rerun) == body["mention_count"]

    coref = client.post(f"/api/workspace/analysis-v3/runs/{run_id}/steps/entity_coreference")
    assert coref.status_code == 200
    assert coref.json()["entity_count"] == body["entity_count"]

    fact_rerun = client.post(f"/api/workspace/analysis-v3/runs/{run_id}/steps/atomic_facts")
    assert fact_rerun.status_code == 200
    assert fact_rerun.json()["fact_count"] == body["fact_count"]

    card_rerun = client.post(f"/api/workspace/analysis-v3/runs/{run_id}/steps/card_events")
    assert card_rerun.status_code == 200
    assert card_rerun.json()["active_card_count"] == body["card_count"]
    after_card_rerun = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/cards").json()["items"]
    assert len(after_card_rerun) == body["card_count"]

    entity_uid = entity_items[0]["entity_uid"]
    patched = client.patch(
        f"/api/workspace/analysis-v3/runs/{run_id}/entities/{entity_uid}",
        json={
            "canonical_name": "修订实体",
            "status": "reviewed",
            "aliases": ["旧名", "修订实体"],
        },
    )
    assert patched.status_code == 200
    assert patched.json()["item"]["canonical_name"] == "修订实体"
    assert patched.json()["item"]["status"] == "reviewed"
    assert "旧名" in patched.json()["item"]["aliases"]
    assert patched.json()["backtrack_task"]["status"] == "pending"
    assert patched.json()["backtrack_task"]["impact"]["counts"]["cards"] >= 1

    versions = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/entities/{entity_uid}/versions")
    assert versions.status_code == 200
    assert [item["action"] for item in versions.json()["items"]] == ["auto_coreference", "manual_update"]

    backtrack_tasks = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/backtrack/tasks")
    assert backtrack_tasks.status_code == 200
    task = backtrack_tasks.json()["items"][0]
    assert task["target_uid"] == entity_uid
    assert task["impact"]["block_uids"]

    manual_task_response = client.post(
        f"/api/workspace/analysis-v3/runs/{run_id}/backtrack/tasks",
        json={
            "trigger_type": "manual",
            "target_uid": entity_uid,
            "reason": "test cancel",
        },
    )
    assert manual_task_response.status_code == 200
    manual_task = manual_task_response.json()["item"]
    cancelled = client.post(f"/api/workspace/analysis-v3/runs/{run_id}/backtrack/tasks/{manual_task['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["item"]["status"] == "cancelled"

    executed = client.post(f"/api/workspace/analysis-v3/runs/{run_id}/backtrack/tasks/{task['id']}/execute")
    assert executed.status_code == 200
    assert executed.json()["task"]["status"] == "completed"
    assert executed.json()["run"]["status"] == "backtrack_ready"
    assert executed.json()["run"]["meta"]["current_phase"] == "M6"
    assert executed.json()["card_result"]["active_card_count"] >= body["card_count"]

    recancel = client.post(f"/api/workspace/analysis-v3/runs/{run_id}/backtrack/tasks/{task['id']}/cancel")
    assert recancel.status_code == 409

    review_before_merge = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/review")
    assert review_before_merge.status_code == 200
    assert review_before_merge.json()["item"]["formal_writeback_allowed"] is False
    assert review_before_merge.json()["item"]["writeback_mode"] == "blocked"

    refreshed_entities = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/entities").json()["items"]
    merge_target_uid = entity_uid
    merge_source_uid = next(item["entity_uid"] for item in refreshed_entities if item["entity_uid"] != merge_target_uid)
    merged = client.post(
        f"/api/workspace/analysis-v3/runs/{run_id}/entities/merge",
        json={
            "target_entity_uid": merge_target_uid,
            "source_entity_uids": [merge_source_uid],
            "canonical_name": "Merged Entity",
            "aliases": ["Merged Entity", "Old Entity"],
        },
    )
    assert merged.status_code == 200
    assert merged.json()["item"]["entity_uid"] == merge_target_uid
    assert merged.json()["item"]["status"] == "reviewed"
    assert "manual_merge" in [item["action"] for item in merged.json()["versions"]]
    assert merged.json()["backtrack_task"]["trigger_type"] == "entity_merged"

    after_merge_entities = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/entities").json()["items"]
    assert next(item for item in after_merge_entities if item["entity_uid"] == merge_source_uid)["status"] == "merged"
    after_merge_mentions = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/mentions").json()["items"]
    split_mention_uid = next(item["mention_uid"] for item in after_merge_mentions if item["entity_uid"] == merge_target_uid)

    bad_split = client.post(
        f"/api/workspace/analysis-v3/runs/{run_id}/entities/{merge_target_uid}/split",
        json={"canonical_name": "Split Entity"},
    )
    assert bad_split.status_code == 400

    split = client.post(
        f"/api/workspace/analysis-v3/runs/{run_id}/entities/{merge_target_uid}/split",
        json={
            "canonical_name": "Split Entity",
            "aliases": ["Split Alias"],
            "mention_uids": [split_mention_uid],
        },
    )
    assert split.status_code == 200
    assert split.json()["item"]["entity_uid"] != merge_target_uid
    assert split.json()["item"]["status"] == "reviewed"
    assert split.json()["backtrack_task"]["trigger_type"] == "entity_split"
    assert split.json()["versions"][0]["action"] == "manual_split"

    rolled_back = client.post(
        f"/api/workspace/analysis-v3/runs/{run_id}/entities/{merge_target_uid}/versions/2/rollback",
        json={"reason": "test rollback"},
    )
    assert rolled_back.status_code == 200
    assert rolled_back.json()["item"]["canonical_name"] == "修订实体"
    assert "manual_rollback" in [item["action"] for item in rolled_back.json()["versions"]]
    assert rolled_back.json()["backtrack_task"]["trigger_type"] == "entity_rollback"

    review_after_changes = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/review")
    assert review_after_changes.status_code == 200
    assert review_after_changes.json()["item"]["pending_backtrack_count"] >= 1
    assert "pending_backtrack_tasks" in review_after_changes.json()["item"]["blockers"]

    legacy_runs = client.get(f"/api/workspace/books/{book_id}/analysis/runs")
    assert legacy_runs.status_code == 200
    assert legacy_runs.json()["items"] == []


def test_analysis_v3_card_writeback_allows_empty_body_and_creates_snapshot(client: TestClient, monkeypatch) -> None:
    import lingshu_api.routers.analysis_v3 as analysis_v3_router
    import lingshu_api.routers.analysis_v3_cards as analysis_v3_cards_router
    from novel_app.analysis import AnalysisCardDraft, AnalysisStore
    from novel_app.analysis.pipeline_v3 import PIPELINE_V3_VERSION
    from novel_app.analysis.writeback_card_generator import WritebackCardGenerationResult

    class FakeWritebackGenerator:
        def __init__(self) -> None:
            self.calls = []

        def generate(self, database, book_id, card, *, payload=None):
            self.calls.append((database, book_id, card, payload))
            payload = payload or {}
            fields = dict(payload.get("writeback_fields") or {})
            fields["profile_text"] = f"Refined: {fields.get('profile_text', '')}".strip()
            return WritebackCardGenerationResult(
                target=str(payload.get("writeback_target") or ""),
                fields=fields,
                metadata={
                    "used": True,
                    "source": "test",
                    "original_writeback_fields": dict(payload.get("writeback_fields") or {}),
                },
            )

    fake_generator = FakeWritebackGenerator()
    # 同时 patch analysis_v3 与 analysis_v3_cards 两个模块的引用（前者 re-export，后者实际调用）
    monkeypatch.setattr(analysis_v3_router, "_create_writeback_card_generator", lambda db, *, user_id=None: fake_generator)
    monkeypatch.setattr(analysis_v3_cards_router, "_create_writeback_card_generator", lambda db, *, user_id=None: fake_generator)

    book_id = client.post("/api/workspace/books", json={"title": "V3 Writeback API Book"}).json()["item"]["id"]
    db = client.app.state.workspace_db_provider.get()
    store = AnalysisStore(db.db)
    # 注入 ai_invoked 元数据，触发 use_writeback_generator=True 分支
    run_id = store.create_run(book_id, status="probes_ready", pipeline_version=PIPELINE_V3_VERSION, meta={"ai_invoked": True, "ai_stages": ["cards"]})
    card_uid = "CARD-api-writeback-character"
    store.create_card(
        book_id,
        run_id,
        AnalysisCardDraft(
            card_uid=card_uid,
            card_type="v3_character",
            payload={
                "writeback_target": "character",
                "writeback_fields": {
                    "name": "Api Writeback Character",
                    "role": "supporting",
                    "profile_text": "Created from V3 API writeback.",
                },
            },
            diff={"applyable": True},
            status="draft",
        ),
    )

    written = client.post(f"/api/workspace/analysis-v3/runs/{run_id}/cards/{card_uid}/writeback")
    assert written.status_code == 200
    body = written.json()
    assert body["applied_table"] == "characters"
    assert body["applied_id"] is not None
    assert body["writeback_generation_used"] is True
    assert any(str(row["name"] or "") == "Api Writeback Character" for row in db.db.list_characters(book_id))

    snapshots = db.db.list_analysis_apply_snapshots(book_id, run_id)
    assert snapshots
    assert card_uid in str(snapshots[0]["label"] or "")
    assert "writeback_generation" in str(snapshots[0]["snapshot_json"] or "")
    assert fake_generator.calls

    repeated = client.post(f"/api/workspace/analysis-v3/runs/{run_id}/cards/{card_uid}/writeback")
    assert repeated.status_code == 409

    legacy_card_uid = "CARD-api-apply-character"
    store.create_card(
        book_id,
        run_id,
        AnalysisCardDraft(
            card_uid=legacy_card_uid,
            card_type="v3_character",
            payload={
                "writeback_target": "character",
                "writeback_fields": {
                    "name": "Api Apply Character",
                    "role": "supporting",
                    "profile_text": "Created from V3 legacy apply endpoint.",
                },
            },
            diff={"applyable": True},
            status="draft",
        ),
    )
    legacy_written = client.post(f"/api/workspace/analysis-v3/runs/{run_id}/cards/{legacy_card_uid}/apply")
    assert legacy_written.status_code == 200
    assert legacy_written.json()["writeback_generation_used"] is True
    legacy_repeated = client.post(f"/api/workspace/analysis-v3/runs/{run_id}/cards/{legacy_card_uid}/apply")
    assert legacy_repeated.status_code == 409

    batch_card_uid = "CARD-api-batch-character"
    store.create_card(
        book_id,
        run_id,
        AnalysisCardDraft(
            card_uid=batch_card_uid,
            card_type="v3_character",
            payload={
                "writeback_target": "character",
                "writeback_fields": {
                    "name": "Api Batch Character",
                    "role": "supporting",
                    "profile_text": "Created from V3 batch writeback.",
                },
            },
            diff={"applyable": True},
            status="draft",
        ),
    )
    batch_written = client.post(f"/api/workspace/analysis-v3/runs/{run_id}/writeback")
    assert batch_written.status_code == 200
    batch_item = next(item for item in batch_written.json()["results"] if item["card_uid"] == batch_card_uid)
    assert batch_item["success"] is True
    assert batch_item["writeback_generation_used"] is True


def test_analysis_v3_card_writeback_requires_ai_generator(client: TestClient, monkeypatch) -> None:
    from fastapi import HTTPException

    import lingshu_api.routers.analysis_v3 as analysis_v3_router
    import lingshu_api.routers.analysis_v3_cards as analysis_v3_cards_router
    from novel_app.analysis import AnalysisCardDraft, AnalysisStore
    from novel_app.analysis.pipeline_v3 import PIPELINE_V3_VERSION

    def unavailable(_db, *, user_id=None):
        raise HTTPException(status_code=503, detail="fake generator unavailable")

    monkeypatch.setattr(analysis_v3_router, "_create_writeback_card_generator", unavailable)
    monkeypatch.setattr(analysis_v3_cards_router, "_create_writeback_card_generator", unavailable)

    book_id = client.post("/api/workspace/books", json={"title": "V3 Writeback Requires AI"}).json()["item"]["id"]
    db = client.app.state.workspace_db_provider.get()
    store = AnalysisStore(db.db)
    # 注入 ai_invoked 元数据，触发 use_writeback_generator=True 分支
    run_id = store.create_run(book_id, status="probes_ready", pipeline_version=PIPELINE_V3_VERSION, meta={"ai_invoked": True, "ai_stages": ["cards"]})
    card_uid = "CARD-api-writeback-requires-ai"
    store.create_card(
        book_id,
        run_id,
        AnalysisCardDraft(
            card_uid=card_uid,
            card_type="v3_character",
            payload={
                "writeback_target": "character",
                "writeback_fields": {
                    "name": "Needs AI Character",
                    "role": "supporting",
                    "profile_text": "Raw profile.",
                },
            },
            diff={"applyable": True},
            status="draft",
        ),
    )

    written = client.post(f"/api/workspace/analysis-v3/runs/{run_id}/cards/{card_uid}/writeback")
    assert written.status_code == 503
    card = db.db.connection.execute(
        "SELECT * FROM analysis_cards WHERE run_id = ? AND card_uid = ?",
        (run_id, card_uid),
    ).fetchone()
    assert str(card["status"]) == "draft"
    assert all(str(row["name"] or "") != "Needs AI Character" for row in db.db.list_characters(book_id))
    assert db.db.list_analysis_apply_snapshots(book_id, run_id) == []


def test_review_gate_single_card_not_hard_blocked_by_run_level_issues(client: TestClient) -> None:
    """单卡写回门禁不应被 run 级 pending_backtrack/probe_manual_review 硬阻塞。

    回归：此前 pending_backtrack_tasks 与 probe_manual_review 在单卡场景仍作为硬阻塞，
    且 failed 回溯（终态）会永久阻塞写回。
    """
    import os
    import sqlite3
    from pathlib import Path

    book_id = client.post("/api/workspace/books", json={"title": "Gate Book"}).json()["item"]["id"]
    chapter_id = client.post(f"/api/workspace/books/{book_id}/chapters", json={"title": "C1"}).json()["item"]["id"]
    client.patch(
        f"/api/workspace/chapters/{chapter_id}",
        json={"content": "林一进入城市。\n\n第二段留下《星火伏笔》。"},
    )
    created = client.post(f"/api/workspace/books/{book_id}/analysis-v3/runs", json={"execute_l1": True})
    assert created.status_code == 200
    run_id = created.json()["run_id"]
    assert created.json()["probe_result_count"] >= 1

    # 直接注入阻塞项：pending / failed 回溯任务，并将探针结果置为 manual_review
    db_path = Path(os.environ["SIMPLE_AI_NOVEL_DATA_DIR"]) / "novels.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO analysis_backtrack_tasks (book_id, run_id, task_uid, trigger_type, target_uid, impact_json, status, priority) "
            "VALUES (?, ?, 'BT-pending', 'manual', 'ENT-x', '{}', 'pending', 50)",
            (book_id, run_id),
        )
        conn.execute(
            "INSERT INTO analysis_backtrack_tasks (book_id, run_id, task_uid, trigger_type, target_uid, impact_json, status, priority) "
            "VALUES (?, ?, 'BT-failed', 'manual', 'ENT-x', '{}', 'failed', 50)",
            (book_id, run_id),
        )
        conn.execute(
            "UPDATE analysis_probe_results SET status = 'manual_review' WHERE run_id = ?",
            (run_id,),
        )
        conn.commit()
    finally:
        conn.close()

    # 批量门禁：仍应被 pending_backtrack_tasks / probe_manual_review 硬阻塞
    batch_review = client.get(f"/api/workspace/analysis-v3/runs/{run_id}/review").json()["item"]
    assert batch_review["formal_writeback_allowed"] is False
    assert "pending_backtrack_tasks" in batch_review["blockers"]
    assert "probe_manual_review" in batch_review["blockers"]
    assert "failed_backtrack_tasks" in batch_review["soft_blockers"]
    assert batch_review["failed_backtrack_count"] >= 1

    # 单卡门禁：run 级问题降级为软阻塞，不应硬拦
    single_review = client.get(
        f"/api/workspace/analysis-v3/runs/{run_id}/review?for_single_card=true"
    ).json()["item"]
    assert single_review["formal_writeback_allowed"] is True
    assert single_review["blockers"] == []
    assert "pending_backtrack_tasks" in single_review["soft_blockers"]
    assert "probe_manual_review" in single_review["soft_blockers"]
    assert "failed_backtrack_tasks" in single_review["soft_blockers"]
