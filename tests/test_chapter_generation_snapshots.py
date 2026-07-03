"""章节生成快照回归测试。

覆盖 ChapterGenerationSnapshotMixin 的核心场景：
- create_generation_snapshot 创建快照（含 selected_skills JSON 序列化）
- list_generation_snapshots 按 created_at DESC 排序
- restore_generation_snapshot 多表写入（旧 content 入 chapter_snapshots，新 content 写入 chapters）
- delete_generation_snapshot 删除快照
- restore/get 不存在的快照返回 None
"""
from __future__ import annotations

import json

import pytest

from novel_app.database import Database


@pytest.fixture
def db(tmp_path):
    """创建临时数据库、测试 book 与 chapter。"""
    database = Database(str(tmp_path / "test.db"))
    database.initialize()
    book_id = database.create_book("测试书")
    chapter_id = database.create_chapter(book_id, "测试章节")
    return database, book_id, chapter_id


def test_create_generation_snapshot(db):
    """create_generation_snapshot 应写入快照并返回 id，selected_skills 序列化为 JSON。"""
    database, book_id, chapter_id = db
    snap_id = database.create_generation_snapshot(chapter_id, {
        "mode": "draft",
        "outline": "测试大纲",
        "generated_text": "生成的正文内容",
        "selected_skills": [{"name": "skill1", "category": "cat", "instruction_text": "instr"}],
        "status": "success",
        "task_id": "task-1",
    })
    assert snap_id > 0
    snap = database.get_generation_snapshot(snap_id)
    assert snap is not None
    assert snap["mode"] == "draft"
    assert snap["outline"] == "测试大纲"
    assert snap["generated_text"] == "生成的正文内容"
    assert snap["status"] == "success"
    assert snap["task_id"] == "task-1"
    # selected_skills_json 应是 JSON 字符串
    skills = json.loads(snap["selected_skills_json"])
    assert len(skills) == 1
    assert skills[0]["name"] == "skill1"


def test_create_generation_snapshot_defaults(db):
    """create_generation_snapshot 缺省字段应使用默认值。"""
    database, book_id, chapter_id = db
    snap_id = database.create_generation_snapshot(chapter_id, {
        "mode": "draft",
        "status": "success",
    })
    snap = database.get_generation_snapshot(snap_id)
    assert snap is not None
    assert snap["outline"] == ""
    assert snap["generated_text"] == ""
    assert snap["task_id"] == ""
    # selected_skills 缺省应为空列表 JSON
    assert json.loads(snap["selected_skills_json"]) == []


def test_list_generation_snapshots_desc_order(db):
    """list_generation_snapshots 应按 created_at DESC 排序，最新的在前。"""
    database, book_id, chapter_id = db
    id1 = database.create_generation_snapshot(chapter_id, {"mode": "draft", "status": "success"})
    id2 = database.create_generation_snapshot(chapter_id, {"mode": "continue", "status": "success"})
    items = database.list_generation_snapshots(chapter_id)
    assert len(items) == 2
    # DESC 排序，最新的在前
    assert items[0]["id"] == id2
    assert items[1]["id"] == id1
    # 返回的是 dict
    assert isinstance(items[0], dict)
    assert items[0]["mode"] == "continue"


def test_list_generation_snapshots_empty(db):
    """无快照时应返回空列表。"""
    database, book_id, chapter_id = db
    items = database.list_generation_snapshots(chapter_id)
    assert items == []


def test_list_generation_snapshots_isolated_per_chapter(db):
    """list_generation_snapshots 应按 chapter_id 隔离。"""
    database, book_id, chapter_id = db
    other_chapter_id = database.create_chapter(book_id, "另一章节")
    database.create_generation_snapshot(chapter_id, {"mode": "draft", "status": "success"})
    database.create_generation_snapshot(other_chapter_id, {"mode": "continue", "status": "success"})
    assert len(database.list_generation_snapshots(chapter_id)) == 1
    assert len(database.list_generation_snapshots(other_chapter_id)) == 1


def test_restore_generation_snapshot(db):
    """restore 应把旧 content 存入 chapter_snapshots，新 content 写入 chapters。

    多表写入用 database.transaction() 包裹（方法内不自行 commit）。
    """
    database, book_id, chapter_id = db
    # 先给 chapter 设旧 content（update_chapter 签名：chapter_id, outline, content）
    database.update_chapter(chapter_id, "旧大纲", "旧正文内容")

    # 创建快照
    snap_id = database.create_generation_snapshot(chapter_id, {
        "mode": "draft",
        "generated_text": "新生成的内容",
        "status": "success",
    })

    # 恢复（多表写入用 transaction 包裹）
    with database.transaction():
        result = database.restore_generation_snapshot(snap_id)
    assert result is not None
    assert result["chapter_id"] == chapter_id
    assert result["old_content_length"] == len("旧正文内容")
    assert result["new_content_length"] == len("新生成的内容")

    # 验证 chapter content 已更新为新内容
    chapter = database.get_chapter(chapter_id)
    assert chapter["content"] == "新生成的内容"

    # 验证旧 content 已存入 chapter_snapshots 表（label='generation_restore'）
    rows = database.connection.execute(
        "SELECT * FROM chapter_snapshots WHERE chapter_id = ? AND label = 'generation_restore'",
        (chapter_id,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["content"] == "旧正文内容"
    assert rows[0]["outline"] == "旧大纲"


def test_restore_generation_snapshot_empty_old_content(db):
    """restore 时空旧 content 也应正常工作，old_content_length 为 0。"""
    database, book_id, chapter_id = db
    # chapter 初始 content 为空字符串
    snap_id = database.create_generation_snapshot(chapter_id, {
        "mode": "draft",
        "generated_text": "首次生成内容",
        "status": "success",
    })
    with database.transaction():
        result = database.restore_generation_snapshot(snap_id)
    assert result is not None
    assert result["old_content_length"] == 0
    assert result["new_content_length"] == len("首次生成内容")
    chapter = database.get_chapter(chapter_id)
    assert chapter["content"] == "首次生成内容"


def test_delete_generation_snapshot(db):
    """delete 应删除快照，删除后 get 返回 None。"""
    database, book_id, chapter_id = db
    snap_id = database.create_generation_snapshot(chapter_id, {"mode": "draft", "status": "success"})
    assert database.get_generation_snapshot(snap_id) is not None
    database.delete_generation_snapshot(snap_id)
    assert database.get_generation_snapshot(snap_id) is None


def test_delete_generation_snapshot_idempotent(db):
    """delete 不存在的快照不应报错。"""
    database, book_id, chapter_id = db
    # 不存在的 id，不应抛异常
    database.delete_generation_snapshot(99999)


def test_restore_nonexistent_returns_none(db):
    """restore 不存在的快照应返回 None。"""
    database, book_id, chapter_id = db
    with database.transaction():
        result = database.restore_generation_snapshot(99999)
    assert result is None


def test_get_generation_snapshot_nonexistent_returns_none(db):
    """get 不存在的快照应返回 None。"""
    database, book_id, chapter_id = db
    assert database.get_generation_snapshot(99999) is None
