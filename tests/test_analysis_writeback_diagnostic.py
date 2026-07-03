from __future__ import annotations

from pathlib import Path

from novel_app.analysis import AnalysisCardDraft, AnalysisStore
from novel_app.database import Database
from tools.diagnose_analysis_writeback import scan_database


def test_diagnostic_reports_pruned_empty_gate_runs_as_not_recoverable(tmp_path: Path) -> None:
    db = Database(tmp_path / "novels.db")
    try:
        db.initialize()
        book_id = db.create_book("Pruned Book")
        store = AnalysisStore(db)
        run_id = store.create_run(
            book_id,
            status="awaiting_review",
            meta={
                "writeback_gate": {
                    "status": "empty",
                    "reason": "No writeback fields remain after evidence filtering.",
                }
            },
        )
        store.create_card(
            book_id,
            run_id,
            AnalysisCardDraft(
                card_uid="full_payload",
                card_type="full_payload",
                payload={
                    "_requires_evidence": True,
                    "analysis_unresolved": [{"title": "evidence gate pruned fields"}],
                    "_meta": {"evidence_gate_dropped": 5},
                },
                diff={
                    "evidence_writeback_gate": {
                        "status": "empty",
                        "reason": "No writeback fields remain after evidence filtering.",
                    }
                },
            ),
        )
    finally:
        db.close()

    reports = scan_database(tmp_path / "novels.db")

    assert len(reports) == 1
    report = reports[0]
    assert report["run_id"] == run_id
    assert report["book_id"] == book_id
    assert report["evidence_gate_dropped"] == 5
    assert report["has_formal_content"] is False
    assert report["recoverable_from_saved_payload"] is False
    assert "rerun whole-book analysis" in report["advice"]
