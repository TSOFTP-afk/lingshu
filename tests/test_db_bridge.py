from __future__ import annotations

from lingshu_api.services.db_bridge import WorkspaceDB


def test_workspace_db_crud_round_trip(tmp_path) -> None:
    db = WorkspaceDB(tmp_path / "novels.db")
    try:
        new_book = db.create_book("自动化测试书籍")
        book_id = int(new_book["id"])

        book = db.get_book(book_id)
        assert book is not None
        assert "volumes" in book

        renamed = db.rename_book(book_id, "自动化测试-已更名")
        assert renamed is not None
        assert renamed["title"] == "自动化测试-已更名"

        vol = db.create_volume(book_id, "测试卷01")
        chapter = db.create_chapter(book_id, "测试章节01", int(vol["id"]))
        chapter_id = int(chapter["id"])

        assert db.get_chapter(chapter_id)["title"] == "测试章节01"
        updated = db.update_chapter(chapter_id, content="测试正文内容", outline="测试大纲")
        assert updated is not None
        assert updated["content"] == "测试正文内容"
        assert db.get_chapter(chapter_id)["word_count"] == len("测试正文内容")

        db.reorder_volumes(book_id, [int(vol["id"])])
        db.move_chapter(chapter_id, int(vol["id"]), 5)
        db.delete_chapter(chapter_id)
        db.delete_volume(int(vol["id"]))
        db.delete_book(book_id)
        assert db.get_book(book_id) is None
    finally:
        db.close()
