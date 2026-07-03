"""伏笔相关 DB 层测试 — CRUD + sync 逻辑。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from novel_app.analysis.foreshadow_sync import sync_foreshadows_from_facts
from novel_app.database import Database


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "t.db")
    database.initialize()
    return database


def _make_fact(
    *,
    fact_uid: str,
    fact_type: str = "foreshadowing",
    quote_text: str = "伏笔原文",
    value: dict | None = None,
    chapter_id: int | None = None,
    importance_score: float = 0.5,
    subject_entity_uid: str = "ent-foo",
) -> dict:
    return {
        "fact_uid": fact_uid,
        "subject_entity_uid": subject_entity_uid,
        "fact_type": fact_type,
        "quote_text": quote_text,
        "value": value or {},
        "chapter_id": chapter_id or 0,
        "block_uid": "block-1",
        "confidence": 0.8,
        "importance_score": importance_score,
        "status": "candidate",
    }


# ================================================================
#  CRUD
# ================================================================

def test_create_and_get_foreshadow_returns_row(db: Database) -> None:
    book_id = db.create_book("测试书")
    fid = db.create_foreshadow(book_id, "主角胸口玉佩的微光")
    assert isinstance(fid, int)
    row = db.get_foreshadow(fid)
    assert row is not None
    assert int(row["book_id"]) == book_id
    assert str(row["description"]) == "主角胸口玉佩的微光"
    assert str(row["status"]) == "pending"
    assert str(row["priority"]) == "medium"
    assert str(row["source"]) == "manual"
    assert str(row["fact_uid"]) == ""


def test_create_foreshadow_invalid_values_fallback_to_defaults(db: Database) -> None:
    book_id = db.create_book("测试书")
    fid = db.create_foreshadow(
        book_id, "描述",
        status="invalid_status",
        priority="invalid_priority",
        source="invalid_source",
    )
    row = db.get_foreshadow(fid)
    assert str(row["status"]) == "pending"
    assert str(row["priority"]) == "medium"
    assert str(row["source"]) == "manual"


def test_get_foreshadow_returns_none_when_absent(db: Database) -> None:
    assert db.get_foreshadow(999999) is None


def test_list_foreshadows_returns_all_unfiltered(db: Database) -> None:
    book_id = db.create_book("测试书")
    db.create_foreshadow(book_id, "伏笔A")
    db.create_foreshadow(book_id, "伏笔B")
    other_book = db.create_book("另一本书")
    db.create_foreshadow(other_book, "其他书伏笔")
    rows = db.list_foreshadows(book_id)
    assert len(rows) == 2
    # 按 created_at DESC 排序，最后创建的在前
    descriptions = [str(r["description"]) for r in rows]
    assert "伏笔A" in descriptions
    assert "伏笔B" in descriptions
    assert "其他书伏笔" not in descriptions


def test_list_foreshadows_status_filter(db: Database) -> None:
    book_id = db.create_book("测试书")
    pending_id = db.create_foreshadow(book_id, "待回收", status="pending")
    resolved_id = db.create_foreshadow(book_id, "已回收", status="resolved")
    db.create_foreshadow(book_id, "已废弃", status="abandoned")

    pending_rows = db.list_foreshadows(book_id, status="pending")
    assert {int(r["id"]) for r in pending_rows} == {pending_id}

    resolved_rows = db.list_foreshadows(book_id, status="resolved")
    assert {int(r["id"]) for r in resolved_rows} == {resolved_id}


def test_list_foreshadows_invalid_status_falls_back_to_all(db: Database) -> None:
    book_id = db.create_book("测试书")
    db.create_foreshadow(book_id, "伏笔1")
    db.create_foreshadow(book_id, "伏笔2")
    # 非法状态值应被忽略，返回全部
    rows = db.list_foreshadows(book_id, status="bogus")
    assert len(rows) == 2


def test_list_foreshadows_includes_chapter_titles(db: Database) -> None:
    book_id = db.create_book("测试书")
    setup_ch = db.create_chapter(book_id, "埋设章")
    payoff_ch = db.create_chapter(book_id, "回收章")
    fid = db.create_foreshadow(
        book_id, "玉佩之谜",
        setup_chapter_id=setup_ch,
        payoff_chapter_id=payoff_ch,
    )
    rows = db.list_foreshadows(book_id)
    assert len(rows) == 1
    row = rows[0]
    assert int(row["id"]) == fid
    assert str(row["setup_chapter_title"]) == "埋设章"
    assert str(row["payoff_chapter_title"]) == "回收章"


def test_list_foreshadows_chapter_title_null_when_unset(db: Database) -> None:
    book_id = db.create_book("测试书")
    db.create_foreshadow(book_id, "无章节伏笔")
    rows = db.list_foreshadows(book_id)
    assert len(rows) == 1
    assert rows[0]["setup_chapter_title"] is None
    assert rows[0]["payoff_chapter_title"] is None


def test_update_foreshadow_whitelisted_fields(db: Database) -> None:
    book_id = db.create_book("测试书")
    setup_ch = db.create_chapter(book_id, "第一章")
    payoff_ch = db.create_chapter(book_id, "第二章")
    fid = db.create_foreshadow(book_id, "原描述")

    updated = db.update_foreshadow(
        fid,
        description="更新后的描述",
        status="resolved",
        priority="high",
        setup_chapter_id=setup_ch,
        payoff_chapter_id=payoff_ch,
        resolution_note="玉佩乃神物",
    )
    assert updated is not None
    assert str(updated["description"]) == "更新后的描述"
    assert str(updated["status"]) == "resolved"
    assert str(updated["priority"]) == "high"
    assert int(updated["setup_chapter_id"]) == setup_ch
    assert int(updated["payoff_chapter_id"]) == payoff_ch
    assert str(updated["resolution_note"]) == "玉佩乃神物"


def test_update_foreshadow_ignores_non_whitelisted_fields(db: Database) -> None:
    book_id = db.create_book("测试书")
    fid = db.create_foreshadow(book_id, "原描述", source="manual", fact_uid="uid-1")
    # 尝试修改 source / fact_uid / book_id（均不在白名单中）
    updated = db.update_foreshadow(
        fid,
        source="auto",
        fact_uid="uid-2",
        book_id=999999,
    )
    assert updated is not None
    assert str(updated["source"]) == "manual"
    assert str(updated["fact_uid"]) == "uid-1"
    assert int(updated["book_id"]) == book_id


def test_update_foreshadow_invalid_status_and_priority_ignored(db: Database) -> None:
    book_id = db.create_book("测试书")
    fid = db.create_foreshadow(book_id, "描述", status="pending", priority="medium")
    updated = db.update_foreshadow(
        fid,
        status="bogus",
        priority="bogus",
        description="新描述",  # 合法字段确保有更新
    )
    assert updated is not None
    assert str(updated["status"]) == "pending"  # 非法值未生效
    assert str(updated["priority"]) == "medium"  # 非法值未生效
    assert str(updated["description"]) == "新描述"


def test_update_foreshadow_no_valid_fields_returns_current_row(db: Database) -> None:
    book_id = db.create_book("测试书")
    fid = db.create_foreshadow(book_id, "原描述")
    row = db.update_foreshadow(fid, unknown_field="x")
    assert row is not None
    assert str(row["description"]) == "原描述"


def test_update_foreshadow_updates_updated_at(db: Database) -> None:
    book_id = db.create_book("测试书")
    fid = db.create_foreshadow(book_id, "描述")
    before = db.get_foreshadow(fid)
    # updated_at 精度为秒，等 1.1 秒确保时间戳变化
    import time
    time.sleep(1.1)
    db.update_foreshadow(fid, description="新描述")
    after = db.get_foreshadow(fid)
    assert str(after["updated_at"]) >= str(before["updated_at"])
    assert str(after["updated_at"]) != str(before["updated_at"])


def test_delete_foreshadow_returns_true_and_removes(db: Database) -> None:
    book_id = db.create_book("测试书")
    fid = db.create_foreshadow(book_id, "待删除")
    assert db.delete_foreshadow(fid) is True
    assert db.get_foreshadow(fid) is None


def test_delete_foreshadow_returns_false_when_absent(db: Database) -> None:
    assert db.delete_foreshadow(999999) is False


def test_find_foreshadow_by_fact_uid(db: Database) -> None:
    book_id = db.create_book("测试书")
    fid = db.create_foreshadow(book_id, "描述", fact_uid="fact-abc")
    found = db.find_foreshadow_by_fact_uid(book_id, "fact-abc")
    assert found is not None
    assert int(found["id"]) == fid


def test_find_foreshadow_by_fact_uid_returns_none_when_empty(db: Database) -> None:
    book_id = db.create_book("测试书")
    db.create_foreshadow(book_id, "描述", fact_uid="")
    assert db.find_foreshadow_by_fact_uid(book_id, "") is None


def test_find_foreshadow_by_fact_uid_isolated_per_book(db: Database) -> None:
    book_a = db.create_book("书A")
    book_b = db.create_book("书B")
    db.create_foreshadow(book_a, "描述", fact_uid="shared-uid")
    # 在 book_b 中查找同一 fact_uid 应返回 None
    assert db.find_foreshadow_by_fact_uid(book_b, "shared-uid") is None


# ================================================================
#  sync_foreshadows_from_facts
# ================================================================

def test_sync_creates_foreshadows_from_foreshadowing_facts(db: Database) -> None:
    book_id = db.create_book("测试书")
    run_id = db.create_analysis_run(book_id, pipeline_version="v3_test")
    db.replace_analysis_facts(book_id, run_id, [
        _make_fact(fact_uid="f-1", quote_text="玉佩发光", importance_score=0.8),
        _make_fact(fact_uid="f-2", quote_text="老人预言", importance_score=0.5),
    ])

    added = sync_foreshadows_from_facts(db, book_id, run_id=run_id)
    assert added == 2
    rows = db.list_foreshadows(book_id)
    assert len(rows) == 2
    sources = {str(r["source"]) for r in rows}
    assert sources == {"auto"}
    statuses = {str(r["status"]) for r in rows}
    assert statuses == {"pending"}


def test_sync_ignores_non_foreshadowing_facts(db: Database) -> None:
    book_id = db.create_book("测试书")
    run_id = db.create_analysis_run(book_id, pipeline_version="v3_test")
    db.replace_analysis_facts(book_id, run_id, [
        _make_fact(fact_uid="f-1", fact_type="foreshadowing", quote_text="伏笔"),
        _make_fact(fact_uid="f-2", fact_type="event", quote_text="事件"),
        _make_fact(fact_uid="f-3", fact_type="relationship", quote_text="关系"),
    ])

    added = sync_foreshadows_from_facts(db, book_id, run_id=run_id)
    assert added == 1
    rows = db.list_foreshadows(book_id)
    assert len(rows) == 1
    assert str(rows[0]["fact_uid"]) == "f-1"


def test_sync_deduplicates_by_fact_uid(db: Database) -> None:
    book_id = db.create_book("测试书")
    run_id = db.create_analysis_run(book_id, pipeline_version="v3_test")
    db.replace_analysis_facts(book_id, run_id, [
        _make_fact(fact_uid="dup-uid", quote_text="伏笔A"),
    ])

    # 第一次同步新增 1 条
    assert sync_foreshadows_from_facts(db, book_id, run_id=run_id) == 1
    # 第二次同步应跳过已存在的 fact_uid
    assert sync_foreshadows_from_facts(db, book_id, run_id=run_id) == 0
    assert len(db.list_foreshadows(book_id)) == 1


def test_sync_prefers_value_json_description(db: Database) -> None:
    book_id = db.create_book("测试书")
    run_id = db.create_analysis_run(book_id, pipeline_version="v3_test")
    db.replace_analysis_facts(book_id, run_id, [
        _make_fact(
            fact_uid="f-1",
            quote_text="原文引用",
            value={"description": "结构化描述", "extra": "x"},
        ),
    ])

    sync_foreshadows_from_facts(db, book_id, run_id=run_id)
    rows = db.list_foreshadows(book_id)
    assert len(rows) == 1
    assert str(rows[0]["description"]) == "结构化描述"


def test_sync_falls_back_to_quote_text_when_no_value_description(db: Database) -> None:
    book_id = db.create_book("测试书")
    run_id = db.create_analysis_run(book_id, pipeline_version="v3_test")
    db.replace_analysis_facts(book_id, run_id, [
        _make_fact(
            fact_uid="f-1",
            quote_text="引用文本",
            value={"other": "no description field"},
        ),
    ])

    sync_foreshadows_from_facts(db, book_id, run_id=run_id)
    rows = db.list_foreshadows(book_id)
    assert len(rows) == 1
    assert str(rows[0]["description"]) == "引用文本"


def test_sync_infers_priority_from_importance_score(db: Database) -> None:
    book_id = db.create_book("测试书")
    run_id = db.create_analysis_run(book_id, pipeline_version="v3_test")
    db.replace_analysis_facts(book_id, run_id, [
        _make_fact(fact_uid="f-high", quote_text="高", importance_score=0.9),
        _make_fact(fact_uid="f-mid", quote_text="中", importance_score=0.5),
        _make_fact(fact_uid="f-low", quote_text="低", importance_score=0.2),
    ])

    sync_foreshadows_from_facts(db, book_id, run_id=run_id)
    by_uid = {str(r["fact_uid"]): str(r["priority"]) for r in db.list_foreshadows(book_id)}
    assert by_uid["f-high"] == "high"
    assert by_uid["f-mid"] == "medium"
    assert by_uid["f-low"] == "low"


def test_sync_sets_setup_chapter_id_from_fact(db: Database) -> None:
    book_id = db.create_book("测试书")
    chapter_id = db.create_chapter(book_id, "第一章")
    run_id = db.create_analysis_run(book_id, pipeline_version="v3_test")
    db.replace_analysis_facts(book_id, run_id, [
        _make_fact(fact_uid="f-1", quote_text="伏笔", chapter_id=chapter_id),
    ])

    sync_foreshadows_from_facts(db, book_id, run_id=run_id)
    rows = db.list_foreshadows(book_id)
    assert len(rows) == 1
    assert int(rows[0]["setup_chapter_id"]) == chapter_id


def test_sync_returns_zero_when_no_facts(db: Database) -> None:
    book_id = db.create_book("测试书")
    assert sync_foreshadows_from_facts(db, book_id) == 0
    assert len(db.list_foreshadows(book_id)) == 0


def test_sync_skips_fact_with_empty_description(db: Database) -> None:
    """事实的 value_json 无描述且 quote_text 为空时应被跳过。

    通过直接 SQL 插入绕过 _insert_analysis_facts 的非空校验，
    以验证 sync_foreshadows_from_facts 的空描述过滤逻辑。
    """
    book_id = db.create_book("测试书")
    run_id = db.create_analysis_run(book_id, pipeline_version="v3_test")
    # 正常插入一条有效事实
    db.replace_analysis_facts(book_id, run_id, [
        _make_fact(fact_uid="f-valid", quote_text="有效伏笔"),
    ])
    # 直接 SQL 插入一条描述为空的事实（绕过非空校验）
    db.connection.execute(
        """
        INSERT INTO analysis_facts (
            book_id, run_id, fact_uid, subject_entity_uid, fact_type,
            value_json, quote_text, chapter_id, block_uid, confidence,
            memory_scope, memory_importance, memory_type, importance_score,
            status, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            book_id, run_id, "f-empty", "ent-foo", "foreshadowing",
            "{}", "", None, "block-1", 0.5,
            "short_term", "normal", "evidence", 0.5,
            "candidate", "{}",
        ),
    )
    db.connection.commit()

    added = sync_foreshadows_from_facts(db, book_id, run_id=run_id)
    assert added == 1
    rows = db.list_foreshadows(book_id)
    assert len(rows) == 1
    assert str(rows[0]["fact_uid"]) == "f-valid"


def test_sync_without_run_id_uses_latest_facts(db: Database) -> None:
    book_id = db.create_book("测试书")
    run1 = db.create_analysis_run(book_id, pipeline_version="v3_test", status="applied")
    db.replace_analysis_facts(book_id, run1, [
        _make_fact(fact_uid="f-r1", quote_text="旧 run 伏笔"),
    ])
    run2 = db.create_analysis_run(book_id, pipeline_version="v3_test")
    db.replace_analysis_facts(book_id, run2, [
        _make_fact(fact_uid="f-r2", quote_text="新 run 伏笔"),
    ])

    # 不指定 run_id 应聚合所有 facts（list_analysis_facts 不限 run_id）
    added = sync_foreshadows_from_facts(db, book_id)
    assert added == 2
    uids = {str(r["fact_uid"]) for r in db.list_foreshadows(book_id)}
    assert uids == {"f-r1", "f-r2"}
