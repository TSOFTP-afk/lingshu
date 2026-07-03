from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from novel_app.analysis.card_coordinator import CardCoordinator
from novel_app.analysis.fact_store import FactStore
from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3
from novel_app.database import Database


def test_card_coordinator_generates_events_cards_dependencies_and_supersedes_changed_cards() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Card Coordinator Book")
            db.create_character(book_id, "Lin Yi")
            chapter_id = db.create_chapter(book_id, "One")
            content = "Lin Yi enters the city.\n\nLin Yi marks a hidden clue."
            db.update_chapter(chapter_id, outline="", content=content)

            result = AnalysisPipelineV3(db).start_run(book_id)
            cards = db.list_analysis_cards(result.run_id)
            events = db.list_analysis_events(book_id, run_id=result.run_id)

            assert result.status == "probes_ready"
            assert result.card_count == len(cards) == 2
            assert {row["card_type"] for row in cards} == {"v3_character", "v3_book_summary"}
            assert all(row["status"] == "draft" for row in cards)
            assert all(row["card_type"] != "full_payload" for row in cards)
            assert len(events) == 2
            assert all(row["status"] == "processed" for row in events)
            for card in cards:
                dependencies = db.list_analysis_card_dependencies(book_id, run_id=result.run_id, card_uid=str(card["card_uid"]))
                dependency_types = {row["dependency_type"] for row in dependencies}
                assert {"entity", "fact", "block"}.issubset(dependency_types)

            second = CardCoordinator(db).run(book_id=book_id, run_id=result.run_id)
            assert second.active_card_count == 2
            assert len(db.list_analysis_cards(result.run_id)) == 2

            facts = FactStore(db).list_facts(book_id, run_id=result.run_id)
            facts.append(
                {
                    **facts[0],
                    "id": 0,
                    "fact_uid": "FACT-extra-card-change",
                    "quote_text": "Lin Yi gains a token.",
                    "value": {"summary": "Lin Yi gains a token.", "subject_name": "Lin Yi"},
                    "confidence": 0.8,
                }
            )
            FactStore(db).replace_facts(book_id, result.run_id, facts)
            changed = CardCoordinator(db).run(book_id=book_id, run_id=result.run_id)
            changed_cards = db.list_analysis_cards(result.run_id)

            assert changed.active_card_count == 2
            assert len(changed_cards) == 4
            assert sum(1 for row in changed_cards if row["status"] == "superseded") == 2
            assert sum(1 for row in changed_cards if row["status"] == "draft") == 2
        finally:
            db.close()
