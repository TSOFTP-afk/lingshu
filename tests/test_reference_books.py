from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from novel_app.database import Database
from novel_app.reference_books import (
    read_reference_text_file,
    reference_source_path,
    split_reference_text_into_segments,
)
from novel_app.truth import TruthManager


def test_initialize_creates_book_reference_tables() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()

            tables = {
                str(row["name"])
                for row in db.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }

            assert "book_reference_sources" in tables
            assert "book_reference_segments" in tables
        finally:
            db.close()


def test_split_reference_text_into_segments_uses_headings_and_summaries() -> None:
    text = """# 第一章 风格样本

舰长在舰桥上用轻快吐槽推进节奏。

# 第二章 设定样本

核心设定需要被当作参考资料，而不是正式事实。
"""

    segments = split_reference_text_into_segments(text, max_chars=400)

    assert [segment["segment_index"] for segment in segments] == [1, 2]
    assert segments[0]["title"] == "第一章 风格样本"
    assert "轻快吐槽" in segments[0]["summary"]
    assert segments[1]["title"] == "第二章 设定样本"


def test_reference_source_path_resolves_relative_paths_inside_data_dir() -> None:
    data_dir = Path("data-root")
    assert reference_source_path({"source_path": "references/imported_books/a.txt"}, data_dir) == data_dir / "references/imported_books/a.txt"


def test_read_reference_text_file_reads_utf8_text() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "reference.md"
        path.write_text("# 参考\n\n文本内容", encoding="utf-8")

        assert "文本内容" in read_reference_text_file(path)


def test_bind_reference_source_to_book_reuses_binding_and_updates_role() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("参考书目标")
            source_id = db.create_reference_source("参考 A", "ref-a.txt", rights_note="user_imported")

            first_id = db.bind_reference_source_to_book(book_id, source_id, role="style_reference", notes="old")
            second_id = db.bind_reference_source_to_book(book_id, source_id, role="canon_reference", notes="new")
            bindings = db.list_book_reference_sources(book_id)

            assert first_id == second_id
            assert len(bindings) == 1
            assert bindings[0]["source_title"] == "参考 A"
            assert bindings[0]["role"] == "canon_reference"
            assert bindings[0]["notes"] == "new"
            assert int(bindings[0]["enabled"]) == 1
        finally:
            db.close()


def test_create_and_list_book_reference_segments_replace_old_segments() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("分段书")
            source_id = db.create_reference_source("参考 B", "ref-b.txt")
            db.bind_reference_source_to_book(book_id, source_id)

            db.create_book_reference_segments(
                book_id,
                source_id,
                [
                    {"segment_index": 1, "title": "旧段", "content": "旧内容"},
                    {"segment_index": 2, "title": "旧段二", "content": "旧内容二"},
                ],
            )
            db.create_book_reference_segments(
                book_id,
                source_id,
                [{"segment_index": 1, "title": "新段", "content": "新内容", "summary": "新摘要"}],
            )
            segments = db.list_book_reference_segments(book_id, source_id)

            assert len(segments) == 1
            assert segments[0]["title"] == "新段"
            assert segments[0]["summary"] == "新摘要"
            assert segments[0]["content_hash"]
        finally:
            db.close()


def test_reference_book_segments_are_scoped_to_book() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_a = db.create_book("书 A")
            book_b = db.create_book("书 B")
            source_id = db.create_reference_source("共享参考", "shared-ref.txt")
            db.bind_reference_source_to_book(book_a, source_id)
            db.bind_reference_source_to_book(book_b, source_id)
            db.create_book_reference_segments(book_a, source_id, [{"content": "只属于 A"}])
            db.create_book_reference_segments(book_b, source_id, [{"content": "只属于 B"}])

            context_a = db.build_book_reference_context(book_a)
            context_b = db.build_book_reference_context(book_b)

            assert "只属于 A" in context_a
            assert "只属于 B" not in context_a
            assert "只属于 B" in context_b
            assert "只属于 A" not in context_b
        finally:
            db.close()


def test_sourcebook_context_includes_only_enabled_book_references() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("上下文书")
            enabled_source = db.create_reference_source("启用参考", "enabled.txt")
            disabled_source = db.create_reference_source("停用参考", "disabled.txt")
            db.bind_reference_source_to_book(book_id, enabled_source, role="style_reference")
            db.bind_reference_source_to_book(book_id, disabled_source, role="avoid_reference")
            db.update_book_reference_binding(book_id, disabled_source, enabled=False)
            db.create_book_reference_segments(
                book_id,
                enabled_source,
                [{"title": "第一段", "content": "启用参考的节奏样本", "summary": "节奏轻快"}],
            )
            db.create_book_reference_segments(
                book_id,
                disabled_source,
                [{"title": "第一段", "content": "停用参考不应出现"}],
            )

            context = db.build_book_reference_context(book_id)

            assert "【参考书基础数据】" in context
            assert "[文风参考]《启用参考》第一段：节奏轻快" in context
            assert "停用参考不应出现" not in context
        finally:
            db.close()


def test_unbind_reference_book_removes_binding_and_segments() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("解绑书")
            source_id = db.create_reference_source("待解绑参考", "unbind.txt")
            db.bind_reference_source_to_book(book_id, source_id)
            db.create_book_reference_segments(book_id, source_id, [{"content": "解绑后应消失"}])

            db.unbind_reference_source_from_book(book_id, source_id)

            assert db.list_book_reference_sources(book_id, enabled_only=False) == []
            assert db.list_book_reference_segments(book_id, source_id) == []
            assert db.build_book_reference_context(book_id) == ""
        finally:
            db.close()


def test_book_reference_rag_never_enters_truth_file() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Truth 隔离书")
            db.create_chapter(book_id, "第一章")
            source_id = db.create_reference_source("Truth 外参考", "truth-outside.txt")
            db.bind_reference_source_to_book(book_id, source_id)
            db.create_book_reference_segments(
                book_id,
                source_id,
                [{"content": "REFERENCE_ONLY_TEXT_SHOULD_NOT_ENTER_TRUTH"}],
            )

            truth = TruthManager(Path(tmp) / "truth-data", db)
            files = truth.build_all(book_id)
            combined = "\n".join(files.values())

            assert "REFERENCE_ONLY_TEXT_SHOULD_NOT_ENTER_TRUTH" not in combined
            assert "参考书基础数据" not in combined
        finally:
            db.close()
