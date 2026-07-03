from __future__ import annotations

import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from novel_app.analysis import AnalysisCardDraft, AnalysisStore
from novel_app.database import Database
from novel_app.db.common import DATABASE_RESET_EPOCH_ID


def test_initialize_creates_analysis_tables() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            tables = {
                row["name"]
                for row in db.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            assert {
                "analysis_runs",
                "analysis_cards",
                "analysis_blocks",
                "analysis_audit_logs",
                "analysis_apply_snapshots",
            }.issubset(tables)
        finally:
            db.close()


def test_analysis_store_run_card_snapshot_and_audit_roundtrip() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("分析测试")
            store = AnalysisStore(db)

            run_id = store.create_run(book_id, status="running", meta={"source": "test"})
            store.update_run_status(run_id, "awaiting_review", summary="生成 1 张草案")
            run = store.get_run(run_id)
            assert run is not None
            assert run["status"] == "awaiting_review"
            assert run["summary"] == "生成 1 张草案"

            card_id = store.create_card(
                book_id,
                run_id,
                AnalysisCardDraft(
                    card_uid="full_payload",
                    card_type="full_payload",
                    payload={"book_outline": "新大纲"},
                    diff={"applyable": True, "changed_paths": ["books.outline_text"]},
                ),
            )
            cards = store.list_cards(run_id)
            assert [int(card["id"]) for card in cards] == [card_id]
            assert cards[0]["card_type"] == "full_payload"

            store.mark_card_applied(card_id, applied_table="analysis_runs", applied_id=run_id)
            applied = store.get_card(card_id)
            assert applied is not None
            assert applied["status"] == "applied"
            assert applied["applied_at"]

            snapshot_id = store.create_snapshot(book_id, run_id, "before", {"book": {"id": book_id}})
            snapshots = db.list_analysis_apply_snapshots(book_id, run_id)
            assert [int(item["id"]) for item in snapshots] == [snapshot_id]

            audit_id = store.create_audit_log(
                book_id,
                run_id=run_id,
                card_id=card_id,
                action="applied",
                target_type="full_payload",
                new_value={"book_outline": "新大纲"},
            )
            logs = db.list_analysis_audit_logs(book_id, run_id)
            assert [int(item["id"]) for item in logs] == [audit_id]
            assert logs[0]["action"] == "applied"
        finally:
            db.close()


def test_analysis_store_blocks_and_evidence_resolution_roundtrip() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("analysis blocks")
            chapter_id = db.create_chapter(book_id, "chapter")
            db.update_chapter(chapter_id, outline="", content="Lin folded the map.")
            store = AnalysisStore(db)
            run_id = store.create_run(book_id, status="running")

            block_ids = store.save_blocks(
                book_id,
                run_id,
                [
                    {
                        "block_uid": "analysis-chapter-1-part-001",
                        "chunk_id": "chunk-0001",
                        "chunk_index": 1,
                        "chapter_ids": [chapter_id],
                        "chapter_refs": [{"id": chapter_id, "title": "chapter"}],
                        "char_start": 0,
                        "char_end": 19,
                        "text": "Lin folded the map.",
                    }
                ],
            )

            rows = store.list_blocks(book_id, run_id=run_id)
            assert [int(row["id"]) for row in rows] == block_ids
            assert rows[0]["block_uid"] == "analysis-chapter-1-part-001"

            resolution = store.resolve_payload_evidence(
                book_id,
                {
                    "characters": [
                        {
                            "name": "Lin",
                            "source_block_uid": "analysis-chapter-1-part-001",
                            "evidence_quote": "folded the map",
                        }
                    ]
                },
                run_id=run_id,
            )
            assert resolution["status"] == "trusted"
            assert resolution["trusted_refs"] == 1
        finally:
            db.close()


def test_old_database_is_preserved_during_v2_schema_initialization() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "novels.db"
        connection = sqlite3.connect(path)
        connection.execute(
            """
            CREATE TABLE books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                outline_text TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute("INSERT INTO books (title, outline_text) VALUES ('Legacy Book', 'old outline')")
        connection.commit()
        connection.close()

        db = Database(path)
        try:
            db.initialize()
            columns = {
                row["name"]
                for row in db.connection.execute("PRAGMA table_info(analysis_cards)").fetchall()
            }
            assert {"book_id", "run_id", "card_uid", "payload_json", "diff_json", "status"}.issubset(columns)
            block_columns = {
                row["name"]
                for row in db.connection.execute("PRAGMA table_info(analysis_blocks)").fetchall()
            }
            assert {"book_id", "run_id", "block_uid", "text", "content_hash"}.issubset(block_columns)
            books = db.list_books()
            assert len(books) == 1
            assert books[0]["title"] == "Legacy Book"
            marker = db.connection.execute(
                "SELECT 1 FROM app_migrations WHERE id = ?",
                (DATABASE_RESET_EPOCH_ID,),
            ).fetchone()
            assert marker is not None
        finally:
            db.close()


def test_database_reset_epoch_prevents_repeated_clear() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "novels.db"
        db = Database(path)
        try:
            db.initialize()
            book_id = db.create_book("新纪元书")
        finally:
            db.close()

        reopened = Database(path)
        try:
            reopened.initialize()
            books = reopened.list_books()
            assert [int(book["id"]) for book in books] == [book_id]
        finally:
            reopened.close()


def test_legacy_data_dirs_are_not_auto_imported_after_v2_reset(monkeypatch) -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        legacy_dir = root / "legacy" / "data"
        legacy_dir.mkdir(parents=True)
        legacy_db = legacy_dir / "novels.db"
        connection = sqlite3.connect(legacy_db)
        connection.execute(
            """
            CREATE TABLE books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                outline_text TEXT NOT NULL DEFAULT ''
            )
            """
        )
        connection.execute("INSERT INTO books (title, outline_text) VALUES ('旧目录书', 'old')")
        connection.commit()
        connection.close()

        monkeypatch.setenv("SIMPLE_AI_NOVEL_LEGACY_DATA_DIRS", str(legacy_dir))
        (root / "current").mkdir()
        db = Database(root / "current" / "novels.db")
        try:
            db.initialize()
            assert db.list_books() == []
            assert db.imported_legacy_data_dirs == []
        finally:
            db.close()
