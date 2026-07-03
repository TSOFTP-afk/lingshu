from __future__ import annotations

from pathlib import Path

from novel_app.analysis import AnalysisCardBuilder, AnalysisCardDraft, AnalysisStore
from novel_app.analysis.diff_apply import card_diff, card_payload
from novel_app.analysis.payload_normalizer import has_formal_writeback_content
from novel_app.database import Database


def test_analysis_runs_expose_latest_writeback_ready_contract(tmp_path: Path) -> None:
    db = Database(tmp_path / "novels.db")
    try:
        db.initialize()
        book_id = db.create_book("Analysis Contract Book")
        store = AnalysisStore(db)

        old_run_id = store.create_run(book_id, status="awaiting_review")
        store.create_card(
            book_id,
            old_run_id,
            AnalysisCardDraft(
                card_uid="full_payload",
                card_type="full_payload",
                payload={
                    "_requires_evidence": True,
                    "analysis_unresolved": [{"title": "evidence gate pruned"}],
                    "_meta": {"evidence_gate_dropped": 3},
                },
                diff={"applyable": False, "manual_applyable": False, "evidence_writeback_gate": {"status": "empty"}},
            ),
        )

        ready_run_id = store.create_run(book_id, status="awaiting_review")
        ready_payload = {"book_outline_form": {"fields": {"primary_parent_tag_id": {"value": "xianxia"}}}}
        ready_cards = AnalysisCardBuilder(db, book_id, run_id=ready_run_id).build(ready_payload)
        store.save_cards(book_id, ready_run_id, ready_cards)

        runs = db.list_analysis_runs(book_id, limit=20)
        assert int(runs[0]["id"]) == ready_run_id

        ready_diff = card_diff(db.get_analysis_full_payload_card(ready_run_id))
        old_diff = card_diff(db.get_analysis_full_payload_card(old_run_id))
        assert ready_diff["applyable"] is True
        assert ready_diff["manual_applyable"] is True
        assert old_diff["applyable"] is False
        assert old_diff["manual_applyable"] is False
    finally:
        db.close()


def test_analysis_card_diff_contains_preview_safe_fields(tmp_path: Path) -> None:
    db = Database(tmp_path / "novels.db")
    try:
        db.initialize()
        book_id = db.create_book("Preview Contract Book")
        chapter_id = db.create_chapter(book_id, "Chapter 1")
        payload = {
            "_requires_evidence": True,
            "_meta": {"analysis_pipeline": "three_level_pyramid_v2_source_review"},
            "book_outline_form": {"fields": {"primary_parent_tag_id": {"value": "xianxia"}}},
            "world_form": {"fields": {"world_rules_table": {"value": "spirit tides decide city power"}}},
            "characters": [{"name": "Lin Yi", "role": "protagonist", "profile_text": "calm gatekeeper"}],
            "chapter_updates": [
                {
                    "chapter_id": chapter_id,
                    "outline": "Lin Yi enters the city.",
                    "events": ["Lin Yi enters the city"],
                    "source_quote": "Lin Yi enters the city",
                    "source_block_uid": f"analysis-chapter-{chapter_id}-part-001",
                }
            ],
        }
        run_id = AnalysisStore(db).create_run(book_id, status="awaiting_review")
        card = AnalysisCardBuilder(db, book_id, run_id=run_id).build(payload)[0]

        assert card.card_type == "full_payload"
        assert card.diff["manual_applyable"] is True
        assert "candidate_truth_updates" in card.diff
        assert card.diff["candidate_truth_updates"]
        assert "evidence_writeback_gate" in card.diff
        assert "changed_paths" in card.diff
        assert "_meta" not in card.diff.get("summary", "")
    finally:
        db.close()


def test_weak_evidence_card_requires_user_override(tmp_path: Path) -> None:
    db = Database(tmp_path / "novels.db")
    try:
        db.initialize()
        book_id = db.create_book("Weak Evidence Book")
        run_id = AnalysisStore(db).create_run(book_id, status="awaiting_review")
        payload = {
            "_requires_evidence": True,
            "book_outline_form": {"fields": {"primary_parent_tag_id": {"value": "xianxia"}}},
            "world_form": {"fields": {"world_rules_table": {"value": "mana is taxed"}}},
        }

        full_card = AnalysisCardBuilder(db, book_id, run_id=run_id).build(payload)[0]

        assert full_card.diff["applyable"] is False
        assert full_card.diff["manual_applyable"] is True
        assert full_card.diff["requires_user_override"] is True
        assert full_card.diff["evidence_writeback_gate"]["status"] == "missing"
    finally:
        db.close()


def test_pruned_empty_analysis_card_is_not_formal_writeback_content(tmp_path: Path) -> None:
    db = Database(tmp_path / "novels.db")
    try:
        db.initialize()
        book_id = db.create_book("Pruned Contract Book")
        run_id = AnalysisStore(db).create_run(book_id, status="awaiting_review")
        card_id = AnalysisStore(db).create_card(
            book_id,
            run_id,
            AnalysisCardDraft(
                card_uid="full_payload",
                card_type="full_payload",
                payload={
                    "_requires_evidence": True,
                    "analysis_unresolved": [{"title": "evidence gate pruned"}],
                    "_meta": {"evidence_gate_dropped": 5},
                },
                diff={"applyable": False, "manual_applyable": False, "evidence_writeback_gate": {"status": "empty"}},
            ),
        )
        row = db.get_analysis_card(card_id)

        assert has_formal_writeback_content(card_payload(row)) is False
        diff = card_diff(row)
        assert diff["evidence_writeback_gate"]["status"] == "empty"
        assert diff["applyable"] is False
    finally:
        db.close()
