"""WritingProbeService 单元测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from novel_app.analysis.writing_probe import WritingProbeService
from novel_app.database import Database


def _set_chapter_content(database: Database, chapter_id: int, content: str) -> None:
    database.connection.execute(
        "UPDATE chapters SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (content, chapter_id),
    )
    database.connection.commit()


@pytest.fixture()
def service_with_book(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    db.initialize()
    book_id = db.create_book("测试书")
    service = WritingProbeService(db, probe_enabled=True, ai_available=False)
    yield db, service, book_id
    # Windows 下显式释放连接，避免文件锁
    try:
        db.connection.close()
    except Exception:
        pass


def test_scan_chapter_discovers_new_characters_via_rule(service_with_book) -> None:
    db, service, book_id = service_with_book
    chapter_id = db.create_chapter(book_id, "第一章")
    _set_chapter_content(db, chapter_id, "叶芷笑道：「你好。」\n张三冷声道：「走。」")
    db.create_character(book_id, "叶芷")  # 已有人物

    result = service.scan_chapter(book_id, chapter_id)
    new_names = [d["writeback_fields"]["name"] for d in result["character_drafts"]]
    assert "张三" in new_names
    assert "叶芷" not in new_names  # 已有人物不进草稿


def test_scan_chapter_skips_existing_characters(service_with_book) -> None:
    db, service, book_id = service_with_book
    chapter_id = db.create_chapter(book_id, "第一章")
    _set_chapter_content(db, chapter_id, "枫鱼道：你好。\n叶芷道：再见。")
    db.create_character(book_id, "枫鱼")
    db.create_character(book_id, "叶芷")

    result = service.scan_chapter(book_id, chapter_id)
    # 两个都是已有人物，不应有任何草稿
    assert result["character_drafts"] == []


def test_scan_chapter_creates_companion_run_once(service_with_book) -> None:
    db, service, book_id = service_with_book
    ch1 = db.create_chapter(book_id, "第一章")
    _set_chapter_content(db, ch1, "张三道：你好")
    ch2 = db.create_chapter(book_id, "第二章")
    _set_chapter_content(db, ch2, "李四道：再见")

    service.scan_chapter(book_id, ch1)
    run_id_1 = service._ensure_companion_run(book_id)
    service.scan_chapter(book_id, ch2)
    run_id_2 = service._ensure_companion_run(book_id)
    assert run_id_1 == run_id_2  # 同一本书复用同一个伴随 run


def test_find_appearing_characters_counts_and_sorts(service_with_book) -> None:
    db, service, book_id = service_with_book
    chapter_id = db.create_chapter(book_id, "第一章")
    # 枫鱼出现3次，叶芷出现1次
    _set_chapter_content(
        db,
        chapter_id,
        "枫鱼道：...\n枫鱼转身。\n枫鱼看着叶芷。\n叶芷道：...",
    )
    db.create_character(book_id, "枫鱼")
    db.create_character(book_id, "叶芷")

    result = service.find_appearing_characters(book_id, chapter_id)
    assert len(result) == 2
    assert result[0]["name"] == "枫鱼"
    assert result[0]["appear_count"] >= 2
    assert result[1]["name"] == "叶芷"


def test_find_appearing_characters_excludes_non_appearing(service_with_book) -> None:
    db, service, book_id = service_with_book
    chapter_id = db.create_chapter(book_id, "第一章")
    _set_chapter_content(db, chapter_id, "枫鱼道：你好")
    db.create_character(book_id, "枫鱼")
    db.create_character(book_id, "叶芷")  # 不出现

    result = service.find_appearing_characters(book_id, chapter_id)
    assert len(result) == 1
    assert result[0]["name"] == "枫鱼"


def test_list_chapter_drafts_returns_only_target_chapter(service_with_book) -> None:
    db, service, book_id = service_with_book
    ch1 = db.create_chapter(book_id, "第一章")
    _set_chapter_content(db, ch1, "张三道：你好")
    ch2 = db.create_chapter(book_id, "第二章")
    _set_chapter_content(db, ch2, "李四道：再见")

    service.scan_chapter(book_id, ch1)
    service.scan_chapter(book_id, ch2)
    drafts1 = service.list_chapter_drafts(book_id, ch1)
    drafts2 = service.list_chapter_drafts(book_id, ch2)
    assert all(d["payload"]["chapter_id"] == ch1 for d in drafts1)
    assert all(d["payload"]["chapter_id"] == ch2 for d in drafts2)
    assert len(drafts1) >= 1
    assert len(drafts2) >= 1


def test_list_chapter_drafts_includes_run_id(service_with_book) -> None:
    db, service, book_id = service_with_book
    chapter_id = db.create_chapter(book_id, "第一章")
    _set_chapter_content(db, chapter_id, "张三道：你好")
    service.scan_chapter(book_id, chapter_id)

    drafts = service.list_chapter_drafts(book_id, chapter_id)
    assert drafts
    expected_run_id = service._ensure_companion_run(book_id)
    for draft in drafts:
        assert draft["run_id"] == expected_run_id


def test_apply_summary_updates_chapter_summary_text(service_with_book) -> None:
    db, service, book_id = service_with_book
    chapter_id = db.create_chapter(book_id, "第一章")
    _set_chapter_content(db, chapter_id, "正文内容")
    # 先 upsert 一条概要草稿
    run_id = service._ensure_companion_run(book_id)
    service._upsert_summary_draft(
        book_id, run_id, chapter_id, db.get_chapter(chapter_id), "本章讲述了...", 4
    )

    result = service.apply_summary(book_id, chapter_id, "本章讲述了...")
    assert result["ok"] is True
    chapter = db.get_chapter(chapter_id)
    assert chapter["summary_text"] == "本章讲述了..."

    # 草稿应标记 applied
    drafts = service.list_chapter_drafts(book_id, chapter_id)
    summary_drafts = [d for d in drafts if d["card_type"] == "writing_probe_summary"]
    assert summary_drafts
    assert summary_drafts[0]["status"] == "applied"


def test_scan_chapter_writes_audit_log(service_with_book) -> None:
    db, service, book_id = service_with_book
    chapter_id = db.create_chapter(book_id, "第一章")
    _set_chapter_content(db, chapter_id, "张三道：你好")
    service.scan_chapter(book_id, chapter_id)

    run_id = service._ensure_companion_run(book_id)
    rows = db.connection.execute(
        "SELECT * FROM analysis_audit_logs WHERE run_id = ? AND action = 'writing_probe_scan'",
        (run_id,),
    ).fetchall()
    assert len(rows) == 1


def test_scan_chapter_empty_content_returns_empty(service_with_book) -> None:
    db, service, book_id = service_with_book
    chapter_id = db.create_chapter(book_id, "第一章")
    _set_chapter_content(db, chapter_id, "")
    result = service.scan_chapter(book_id, chapter_id)
    assert result["character_drafts"] == []
    assert result["summary_draft"] is None


def test_scan_chapter_nonexistent_chapter_returns_error(service_with_book) -> None:
    db, service, book_id = service_with_book
    result = service.scan_chapter(book_id, 99999)
    assert "error" in result
