from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from novel_app.analysis import AnalysisStore
from novel_app.analysis.diff_apply import (
    apply_analysis_cards,
    build_drafts_with_diffs,
    capture_apply_snapshot,
    evidence_writeback_gate,
    split_book_analysis_payload,
)
from novel_app.database import Database
from novel_app.structured_templates import world_form_defaults


def test_split_book_analysis_payload_creates_expected_cards() -> None:
    drafts = split_book_analysis_payload(
        {
            "book_outline": "新的故事方向",
            "world_form": {"fields": {}},
            "character_cards": [{"name": "林一"}],
            "chapter_updates": [{"chapter_id": 1, "events": ["相遇"]}],
            "analysis_unresolved": [{"field": "能力来源"}],
        }
    )

    assert [draft.card_type for draft in drafts] == [
        "full_payload",
        "book_summary",
        "world",
        "characters",
        "chapters",
        "unresolved",
    ]
    assert drafts[-1].status == "blocked"
    assert drafts[-1].diff["applyable"] is False


def test_split_book_analysis_payload_normalizes_card_aliases() -> None:
    drafts = split_book_analysis_payload(
        {
            "book_card": {"primary_parent_tag_id": "奇幻", "book_description": "星门失控"},
            "world_card": {"world_rules_table": "星门需要血脉钥匙。"},
            "character_cards": [{"name": "林一", "role": "主角", "profile_text": "守门人后裔"}],
        }
    )
    cards = {draft.card_type: draft for draft in drafts}

    assert {"full_payload", "book_summary", "world", "characters"} <= set(cards)
    assert cards["book_summary"].payload["book_outline_form"]["fields"]["primary_parent_tag_id"]["value"] == "奇幻"
    assert cards["book_summary"].payload["book_outline_form"]["fields"]["book_description"]["value"] == "星门失控"
    assert cards["world"].payload["world_form"]["fields"]["world_rules_table"]["value"] == "星门需要血脉钥匙。"
    assert cards["characters"].payload["characters"][0]["name"] == "林一"


def test_save_draft_does_not_modify_formal_book_data() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("草案书")
            character_id = db.create_character(book_id, "林一")
            world = world_form_defaults()
            world["fields"]["world_rules_table"]["value"] = "旧规则"
            db.update_book_world_form(book_id, world)
            chapter_id = db.create_chapter(book_id, "第一章")
            event_id = db.create_chapter_event(book_id, chapter_id, "旧事件")

            before_character = dict(db.get_character(character_id))
            before_world = db.get_book_world_form(book_id)
            before_events = [dict(item) for item in db.list_chapter_events(book_id)]

            run_id = db.create_analysis_run(book_id, status="running")
            drafts = build_drafts_with_diffs(
                db,
                book_id,
                {
                    "world_form": {"fields": {"world_rules_table": {"value": "新规则"}}},
                    "character_cards": [{"name": "林一", "role": "主角", "profile_text": "新人物"}],
                    "chapter_updates": [{"chapter_id": chapter_id, "events": ["新事件"]}],
                },
            )
            AnalysisStore(db).save_cards(book_id, run_id, drafts)

            assert dict(db.get_character(character_id)) == before_character
            assert db.get_book_world_form(book_id) == before_world
            assert [dict(item) for item in db.list_chapter_events(book_id)] == before_events
            assert int(db.list_chapter_events(book_id)[0]["id"]) == event_id
        finally:
            db.close()


def test_evidence_writeback_gate_allows_trusted_block_refs_with_unresolved_preview() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("gate book")
            chapter_id = db.create_chapter(book_id, "chapter")
            run_id = db.create_analysis_run(book_id, status="running")
            AnalysisStore(db).save_blocks(
                book_id,
                run_id,
                [
                    {
                        "block_uid": "analysis-chapter-1-part-001",
                        "chunk_id": "chunk-0001",
                        "chunk_index": 1,
                        "chapter_ids": [chapter_id],
                        "text": "Lin folded the map into his sleeve.",
                    }
                ],
            )
            payload = {
                "_requires_evidence": True,
                "book_outline_form": {
                    "fields": {
                        "book_description": {
                            "value": "map mystery",
                            "source_block_uid": "analysis-chapter-1-part-001",
                            "source_quote": "folded the map",
                        }
                    }
                },
                "analysis_unresolved": [{"field": "origin"}],
            }

            drafts = build_drafts_with_diffs(db, book_id, payload, run_id=run_id)
            full_diff = drafts[0].diff

            assert full_diff["applyable"] is True
            assert full_diff["evidence_writeback_gate"]["status"] == "trusted"
            assert drafts[-1].card_type == "unresolved"
            assert drafts[-1].diff["applyable"] is False
        finally:
            db.close()


def test_evidence_writeback_gate_blocks_missing_or_mismatched_block_refs() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("gate book")
            chapter_id = db.create_chapter(book_id, "chapter")
            run_id = db.create_analysis_run(book_id, status="running")
            AnalysisStore(db).save_blocks(
                book_id,
                run_id,
                [
                    {
                        "block_uid": "analysis-chapter-1-part-001",
                        "chapter_ids": [chapter_id],
                        "text": "Lin folded the map into his sleeve.",
                    }
                ],
            )

            missing = evidence_writeback_gate(
                db,
                book_id,
                {"book_outline_form": {"fields": {"genre": {"value": "x", "source_block_uid": "missing", "source_quote": "folded"}}}},
                run_id=run_id,
                requires_evidence=True,
            )
            mismatched = evidence_writeback_gate(
                db,
                book_id,
                {"book_outline_form": {"fields": {"genre": {"value": "x", "source_block_uid": "analysis-chapter-1-part-001", "source_quote": "not in block"}}}},
                run_id=run_id,
                requires_evidence=True,
            )

            assert missing["applyable"] is False
            assert missing["status"] == "missing"
            assert mismatched["applyable"] is False
            assert mismatched["status"] == "weak"
        finally:
            db.close()


def test_weak_evidence_payload_keeps_visible_formal_draft_cards() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("weak draft")
            chapter_id = db.create_chapter(book_id, "chapter")
            run_id = db.create_analysis_run(book_id, status="running")

            drafts = build_drafts_with_diffs(
                db,
                book_id,
                {
                    "_requires_evidence": True,
                    "book_outline_form": {"fields": {"primary_parent_tag_id": {"value": "仙侠"}}},
                    "world_form": {"fields": {"world_rules_table": {"value": "蛊虫决定力量上限。"}}},
                    "characters": [{"name": "方源", "role": "主角", "profile_text": "冷静果断。"}],
                    "chapter_updates": [{"chapter_id": chapter_id, "outline": "方源重生。", "events": ["方源重生"]}],
                },
                run_id=run_id,
            )

            cards = {draft.card_type: draft for draft in drafts}
            assert {"full_payload", "book_summary", "world", "characters", "chapters"} <= set(cards)
            assert cards["full_payload"].diff["applyable"] is False
            assert cards["full_payload"].diff["manual_applyable"] is True
            assert cards["full_payload"].diff["requires_user_override"] is True
            assert cards["full_payload"].diff["evidence_writeback_gate"]["status"] == "missing"
        finally:
            db.close()


def test_capture_apply_snapshot_contains_book_level_state() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("快照书")
            char_id = db.create_character(book_id, "林一")
            chapter_id = db.create_chapter(book_id, "第一章")
            db.update_chapter(chapter_id, outline="旧大纲", content="正文", summary_text="旧摘要")
            event_id = db.create_chapter_event(book_id, chapter_id, "旧事件")

            snapshot = capture_apply_snapshot(db, book_id)

            assert snapshot["book"]["id"] == book_id
            assert snapshot["characters"][0]["id"] == char_id
            assert snapshot["chapter_events"][0]["id"] == event_id
            assert snapshot["chapters"][0]["outline"] == "旧大纲"
            assert snapshot["chapters"][0]["summary_text"] == "旧摘要"
        finally:
            db.close()


def test_apply_analysis_cards_writes_full_payload_to_formal_data() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("apply draft")
            chapter_id = db.create_chapter(book_id, "chapter")
            db.update_chapter(chapter_id, outline="old outline", content="body", summary_text="")
            run_id = db.create_analysis_run(book_id, status="awaiting_review")
            payload = {
                "book_outline_form": {"fields": {"primary_parent_tag_id": {"value": "xianxia"}}},
                "world_form": {"fields": {"world_rules_table": {"value": "spirit stones set the price"}}},
                "characters": [{"name": "Lin", "role": "Protagonist", "profile_form": {"fields": {"personality_main": {"value": "steady"}}}}],
                "chapter_updates": [{"chapter_id": chapter_id, "outline": "Lin enters town.", "events": ["Lin enters town"]}],
            }
            drafts = build_drafts_with_diffs(db, book_id, payload, run_id=run_id)
            card_ids = AnalysisStore(db).save_cards(book_id, run_id, drafts)

            result = apply_analysis_cards(db, book_id, run_id, card_ids)

            assert result.applied_cards == len(card_ids)
            assert result.snapshot_id is not None
            assert db.get_book_outline_form(book_id)["fields"]["primary_parent_tag_id"]["value"] == "xianxia"
            assert db.get_book_world_form(book_id)["fields"]["world_rules_table"]["value"] == "spirit stones set the price"
            character = db.list_characters(book_id)[0]
            assert character["name"] == "Lin"
            assert db.get_character_profile_form(int(character["id"]))["fields"]["personality_main"]["value"] == "steady"
            assert db.get_chapter(chapter_id)["outline"] == "Lin enters town."
            assert [event["label"] for event in db.list_chapter_events(book_id, chapter_id)] == ["Lin enters town"]
            assert db.get_analysis_run(run_id)["status"] == "applied"
        finally:
            db.close()


def test_apply_analysis_cards_ignores_chapter_ai_probability_fields() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("apply draft")
            chapter_id = db.create_chapter(book_id, "chapter")
            db.update_chapter(chapter_id, outline="old outline", content="body", summary_text="")
            db.update_chapter_ai_probability(chapter_id, 88, "high")
            run_id = db.create_analysis_run(book_id, status="awaiting_review")
            payload = {
                "chapter_updates": [
                    {
                        "chapter_id": chapter_id,
                        "outline": "Lin enters town.",
                        "ai_probability": 7,
                        "ai_probability_level": "low",
                        "events": ["Lin enters town"],
                    }
                ],
            }
            drafts = build_drafts_with_diffs(db, book_id, payload, run_id=run_id)
            card_ids = AnalysisStore(db).save_cards(book_id, run_id, drafts)

            result = apply_analysis_cards(db, book_id, run_id, card_ids)

            chapter = db.get_chapter(chapter_id)
            assert result.applied_cards == len(card_ids)
            assert chapter["outline"] == "Lin enters town."
            assert chapter["ai_probability"] == 88
            assert chapter["ai_probability_level"] == "high"
        finally:
            db.close()


def test_apply_analysis_cards_does_not_half_writeback_split_card_only() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("split only")
            run_id = db.create_analysis_run(book_id, status="awaiting_review")
            original_world = db.get_book_world_form(book_id)
            drafts = build_drafts_with_diffs(
                db,
                book_id,
                {"world_form": {"fields": {"world_rules_table": {"value": "new rule"}}}},
                run_id=run_id,
            )
            card_ids = AnalysisStore(db).save_cards(book_id, run_id, drafts)
            world_card_id = next(
                card_id
                for card_id in card_ids
                if str(db.get_analysis_card(card_id)["card_type"]) == "world"
            )

            result = apply_analysis_cards(db, book_id, run_id, [world_card_id])

            assert result.applied_cards == 0
            assert result.snapshot_id is None
            assert db.get_book_world_form(book_id) == original_world
            assert str(db.get_analysis_card(world_card_id)["status"]) == "draft"
        finally:
            db.close()


def test_apply_analysis_cards_requires_override_for_weak_evidence() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("weak apply")
            run_id = db.create_analysis_run(book_id, status="awaiting_review")
            payload = {
                "_requires_evidence": True,
                "book_outline_form": {"fields": {"primary_parent_tag_id": {"value": "qihuan"}}},
            }
            drafts = build_drafts_with_diffs(db, book_id, payload, run_id=run_id)
            card_ids = AnalysisStore(db).save_cards(book_id, run_id, drafts)
            full_card_id = int(db.get_analysis_full_payload_card(run_id)["id"])

            blocked = apply_analysis_cards(db, book_id, run_id, [full_card_id])

            assert blocked.applied_cards == 0
            assert blocked.snapshot_id is None
            assert db.get_book_outline_form(book_id)["fields"]["primary_parent_tag_id"]["value"] == ""
            assert str(db.get_analysis_card(full_card_id)["status"]) == "draft"

            applied = apply_analysis_cards(db, book_id, run_id, card_ids, allow_weak_evidence=True)

            assert applied.applied_cards == len(card_ids)
            assert db.get_book_outline_form(book_id)["fields"]["primary_parent_tag_id"]["value"] == "qihuan"
            assert db.get_analysis_run(run_id)["status"] == "applied"
        finally:
            db.close()
