"""写作探针相关 DB 层测试。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_app.database import Database


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "t.db")
    database.initialize()
    return database


def _set_chapter_content(database: Database, chapter_id: int, content: str) -> None:
    database.connection.execute(
        "UPDATE chapters SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (content, chapter_id),
    )
    database.connection.commit()


def test_list_analysis_cards_by_chapter_filters_via_json(db: Database) -> None:
    book_id = db.create_book("测试书")
    run_id = db.create_analysis_run(book_id, pipeline_version="writing_probe_v1", status="probe_companion")
    db.create_analysis_card(
        book_id, run_id, "probe-char-100-foo", "writing_probe_character",
        {"chapter_id": 100, "writeback_fields": {"name": "foo"}}, status="draft",
    )
    db.create_analysis_card(
        book_id, run_id, "probe-char-101-bar", "writing_probe_character",
        {"chapter_id": 101, "writeback_fields": {"name": "bar"}}, status="draft",
    )
    rows = db.list_analysis_cards_by_chapter(book_id, 100)
    assert len(rows) == 1
    assert rows[0]["card_uid"] == "probe-char-100-foo"


def test_list_analysis_cards_by_chapter_with_card_type_filter(db: Database) -> None:
    book_id = db.create_book("测试书")
    run_id = db.create_analysis_run(book_id, pipeline_version="writing_probe_v1", status="probe_companion")
    db.create_analysis_card(
        book_id, run_id, "probe-char-100-foo", "writing_probe_character",
        {"chapter_id": 100, "writeback_fields": {"name": "foo"}}, status="draft",
    )
    db.create_analysis_card(
        book_id, run_id, "probe-summary-100", "writing_probe_summary",
        {"chapter_id": 100, "writeback_fields": {"summary_text": "..."}}, status="draft",
    )
    chars = db.list_analysis_cards_by_chapter(book_id, 100, card_type="writing_probe_character")
    summaries = db.list_analysis_cards_by_chapter(book_id, 100, card_type="writing_probe_summary")
    assert len(chars) == 1
    assert len(summaries) == 1
    assert chars[0]["card_type"] == "writing_probe_character"
    assert summaries[0]["card_type"] == "writing_probe_summary"


def test_upsert_analysis_card_by_uid_replaces_existing(db: Database) -> None:
    book_id = db.create_book("测试书")
    run_id = db.create_analysis_run(book_id, pipeline_version="writing_probe_v1", status="probe_companion")
    db.upsert_analysis_card_by_uid(
        book_id, run_id, "probe-char-100-foo", "writing_probe_character",
        {"chapter_id": 100, "confidence": 0.6, "writeback_fields": {"name": "foo"}}, status="draft",
    )
    db.upsert_analysis_card_by_uid(
        book_id, run_id, "probe-char-100-foo", "writing_probe_character",
        {"chapter_id": 100, "confidence": 0.7, "writeback_fields": {"name": "foo"}}, status="draft",
    )
    rows = db.list_analysis_cards_by_chapter(book_id, 100, card_type="writing_probe_character")
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"])
    assert payload["confidence"] == 0.7


def test_upsert_analysis_card_by_uid_inserts_when_absent(db: Database) -> None:
    book_id = db.create_book("测试书")
    run_id = db.create_analysis_run(book_id, pipeline_version="writing_probe_v1", status="probe_companion")
    db.upsert_analysis_card_by_uid(
        book_id, run_id, "probe-char-100-new", "writing_probe_character",
        {"chapter_id": 100, "writeback_fields": {"name": "new"}}, status="draft",
    )
    rows = db.list_analysis_cards_by_chapter(book_id, 100)
    assert len(rows) == 1
    assert rows[0]["card_uid"] == "probe-char-100-new"


def test_update_chapter_summary_persists_text(db: Database) -> None:
    book_id = db.create_book("测试书")
    chapter_id = db.create_chapter(book_id, "第一章")
    _set_chapter_content(db, chapter_id, "正文内容")
    db.update_chapter_summary(chapter_id, "本章讲述了...")
    chapter = db.get_chapter(chapter_id)
    assert chapter["summary_text"] == "本章讲述了..."
