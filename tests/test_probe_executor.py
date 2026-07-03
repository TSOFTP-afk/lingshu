from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from novel_app.analysis.fact_store import FactStore
from novel_app.analysis.probe_executor import ProbeExecutor
from novel_app.analysis.probe_planner import ProbePlanner
from novel_app.analysis.store import AnalysisStore
from novel_app.database import Database


def test_probe_executor_persists_results_and_creates_backtrack_for_inconsistency() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Probe Book")
            run_id = AnalysisStore(db).create_run(book_id, pipeline_version="analysis_v3_test")
            facts = [
                _fact("F-rule", "E-world", None, "The gate cannot open without blood."),
                _fact("F-rule-conflict", "E-world", None, "The gate can open without blood."),
            ]
            FactStore(db).replace_facts(book_id, run_id, facts)
            stored_facts = FactStore(db).list_facts(book_id, run_id=run_id)
            plans = ProbePlanner().plan(
                book_id=book_id,
                run_id=run_id,
                facts=stored_facts,
                entities=[{"entity_uid": "E-world", "canonical_name": "Gate Rule", "entity_type": "concept"}],
            )
            world_plans = [plan for plan in plans if plan["probe_type"] == "world_rule"]
            AnalysisStore(db).replace_probe_plans(book_id, run_id, world_plans)

            result = ProbeExecutor(db).execute(book_id=book_id, run_id=run_id, plans=world_plans, facts=stored_facts)
            stored_results = AnalysisStore(db).list_probe_results(book_id, run_id=run_id)
            tasks = AnalysisStore(db).list_backtrack_tasks(book_id, run_id=run_id)

            assert result.result_count == 1
            assert result.inconsistent_count == 1
            assert result.backtrack_task_count == 1
            assert stored_results[0]["consistency"] == "inconsistent"
            assert stored_results[0]["result"]["source_evidence"]
            assert stored_results[0]["result"]["target_evidence"]
            assert stored_results[0]["result"]["formal_writeback"] is False
            assert tasks[0]["trigger_type"] == "probe_inconsistent"
            assert tasks[0]["target_uid"] == "E-world"
            impact = json.loads(str(tasks[0]["impact_json"] or "{}"))
            assert impact["counts"]["facts"] >= 1
        finally:
            db.close()


def _fact(fact_uid: str, entity_uid: str, chapter_id: int | None, quote_text: str) -> dict:
    return {
        "fact_uid": fact_uid,
        "subject_entity_uid": entity_uid,
        "fact_type": "world_rule",
        "value": {"summary": quote_text, "subject_name": "Gate Rule"},
        "quote_text": quote_text,
        "chapter_id": chapter_id,
        "block_uid": f"B-{fact_uid}",
        "confidence": 0.86,
        "memory_scope": "long_term",
        "memory_importance": "high",
        "memory_type": "foundation",
        "importance_score": 0.9,
        "status": "candidate",
        "metadata": {},
    }
