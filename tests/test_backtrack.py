from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3
from novel_app.database import Database


def test_backtrack_task_recomputes_affected_facts_and_cards_without_formal_writeback() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Backtrack Book")
            db.create_character(book_id, "Lin Yi")
            chapter_id = db.create_chapter(book_id, "One")
            db.update_chapter(
                chapter_id,
                outline="",
                content="Lin Yi enters the city.\n\nLin Yi marks a hidden clue.",
            )

            pipeline = AnalysisPipelineV3(db)
            result = pipeline.start_run(book_id)
            entities = db.list_analysis_entities(book_id, run_id=result.run_id)
            entity_uid = next(str(row["entity_uid"]) for row in entities if str(row["canonical_name"]) == "Lin Yi")

            task = pipeline.plan_backtrack_task(
                book_id,
                result.run_id,
                trigger_type="entity_updated",
                target_uid=entity_uid,
                reason="test entity correction",
            )

            assert task["status"] == "pending"
            assert task["impact"]["counts"]["entities"] == 1
            assert task["impact"]["counts"]["facts"] >= 1
            assert task["impact"]["counts"]["cards"] >= 1
            assert task["impact"]["block_uids"]

            backtracked = pipeline.run_backtrack_task(book_id, result.run_id, int(task["id"]))
            refreshed_task = db.get_analysis_backtrack_task(int(task["id"]))
            refreshed_run = db.get_analysis_run(result.run_id)
            cards = db.list_analysis_cards(result.run_id)

            assert backtracked.task["status"] == "completed"
            assert refreshed_task is not None
            assert refreshed_task["status"] == "completed"
            assert refreshed_run is not None
            assert refreshed_run["status"] == "backtrack_ready"
            assert json.loads(str(refreshed_run["meta_json"] or "{}"))["current_phase"] == "M6"
            assert backtracked.fact_count >= 1
            assert all(str(row["card_type"] or "") != "full_payload" for row in cards)
            assert db.list_characters(book_id)[0]["name"] == "Lin Yi"
        finally:
            db.close()
