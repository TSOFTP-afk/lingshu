from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from novel_app.analysis import build_analysis_card_drafts, extract_block_facts, verify_analysis_card_evidence
from novel_app.analysis.card_builder import AnalysisCardBuilder
from novel_app.analysis.store import AnalysisStore
from novel_app.database import Database


def test_card_builder_adds_entity_uid_ars_and_truth_preview_without_writing_formal_data() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Builder Book")
            chapter_id = db.create_chapter(book_id, "One")
            run_id = db.create_analysis_run(book_id, status="running")
            AnalysisStore(db).save_blocks(
                book_id,
                run_id,
                [
                    {
                        "block_uid": f"analysis-chapter-{chapter_id}-part-001",
                        "chunk_id": "chunk-0001",
                        "chunk_index": 1,
                        "chapter_ids": [chapter_id],
                        "text": "Lin folded the map into his sleeve.",
                    }
                ],
            )

            payload = {
                "_requires_evidence": True,
                "book_outline": "A map mystery.",
                "character_cards": [
                    {
                        "name": "Lin",
                        "aliases": ["Mapkeeper"],
                        "profile_text": "keeps the hidden map",
                        "source_block_uid": f"analysis-chapter-{chapter_id}-part-001",
                        "source_quote": "folded the map",
                    }
                ],
            }

            built = AnalysisCardBuilder(db, book_id, run_id=run_id).build_result(payload)
            cards = {draft.card_type: draft for draft in built.drafts}

            assert built.entity_resolution.entity_count == 1
            assert cards["characters"].entity_uid.startswith(f"BOOK-{book_id}::ENT-P-")
            assert cards["characters"].ars_score > 0.8
            assert cards["characters"].diff["evidence_writeback_gate"]["status"] == "trusted"
            assert cards["characters"].diff["candidate_truth_updates"][0]["target"] == "characters"
            assert db.list_characters(book_id) == []
        finally:
            db.close()


def test_card_builder_scores_missing_evidence_lower_than_trusted_evidence() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Score Book")
            chapter_id = db.create_chapter(book_id, "One")
            run_id = db.create_analysis_run(book_id, status="running")
            AnalysisStore(db).save_blocks(
                book_id,
                run_id,
                [
                    {
                        "block_uid": f"analysis-chapter-{chapter_id}-part-001",
                        "chapter_ids": [chapter_id],
                        "text": "Lin folded the map into his sleeve.",
                    }
                ],
            )

            trusted = AnalysisCardBuilder(db, book_id, run_id=run_id).build(
                {
                    "_requires_evidence": True,
                    "character_cards": [
                        {
                            "name": "Lin",
                            "source_block_uid": f"analysis-chapter-{chapter_id}-part-001",
                            "source_quote": "folded the map",
                        }
                    ],
                }
            )
            missing = AnalysisCardBuilder(db, book_id, run_id=run_id).build(
                {
                    "_requires_evidence": True,
                    "character_cards": [
                        {
                            "name": "Lin",
                            "source_block_uid": "missing-block",
                            "source_quote": "folded the map",
                        }
                    ],
                }
            )

            trusted_character = next(draft for draft in trusted if draft.card_type == "characters")
            missing_character = next(draft for draft in missing if draft.card_type == "characters")
            assert trusted_character.ars_score > missing_character.ars_score
            assert missing_character.diff["applyable"] is False
        finally:
            db.close()


def test_p1_p2_public_analysis_helpers_extract_build_and_verify() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Helper Book")
            chapter_id = db.create_chapter(book_id, "One")
            run_id = db.create_analysis_run(book_id, status="running")
            blocks = [
                {
                    "block_uid": f"analysis-chapter-{chapter_id}-part-001",
                    "chunk_id": "chunk-0001",
                    "chapter_ids": [chapter_id],
                    "text": "Lin folded the map into his sleeve.",
                }
            ]
            AnalysisStore(db).save_blocks(book_id, run_id, blocks)
            payload = {
                "_requires_evidence": True,
                "character_cards": [
                    {
                        "name": "Lin",
                        "source_block_uid": f"analysis-chapter-{chapter_id}-part-001",
                        "source_quote": "folded the map",
                    }
                ],
            }

            facts = extract_block_facts(blocks)
            drafts = build_analysis_card_drafts(db, book_id, payload, run_id=run_id)
            gate = verify_analysis_card_evidence(db, book_id, payload, run_id=run_id)

            assert facts[0]["fact_uid"] == f"fact:analysis-chapter-{chapter_id}-part-001"
            assert {draft.card_type for draft in drafts} == {"full_payload", "characters"}
            assert gate["status"] == "trusted"
            assert gate["applyable"] is True
        finally:
            db.close()
