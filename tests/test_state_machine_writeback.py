"""V3 状态机写回回归测试。

覆盖 writeback_to_state_machine 的核心场景：
- motivation 类 fact 映射到 desire_text
- 低置信度 fact 进入循环日志 world_feedback，不改三轴
- 保守映射：不覆盖用户已填的非空字段
- 写回应创建主循环日志（main light +3）
"""
from __future__ import annotations

import pytest

from novel_app.analysis.state_machine_writeback import writeback_to_state_machine
from novel_app.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    database.initialize()
    book_id = database.create_book("测试书")
    return database, book_id


def test_writeback_motivation_to_desire(db):
    """motivation 类型的 fact 应映射到 desire_text。"""
    database, book_id = db
    char_id = database.create_character(book_id, "奥托")
    with database.transaction():
        result = writeback_to_state_machine(database, book_id, char_id, [
            {"fact_type": "motivation", "content": "复活卡莲"},
        ])
    sm = database.get_state_machine(char_id)
    assert sm["desire_text"] == "复活卡莲"
    assert result["cycle_id"] is not None
    assert result["cumulative_score"] == 3  # main light +3


def test_writeback_low_confidence_to_cycle_log(db):
    """低置信度 fact 应进入循环日志 world_feedback，不改三轴。"""
    database, book_id = db
    char_id = database.create_character(book_id, "测试人物")
    with database.transaction():
        result = writeback_to_state_machine(database, book_id, char_id, [
            {"fact_type": "unknown_type", "content": "某条未知分析信息"},
        ])
    sm = database.get_state_machine(char_id)
    assert sm["desire_text"] == ""  # 三轴未被修改
    # 循环日志应包含该 fact
    cycles = database.list_cycles(char_id)
    assert len(cycles) >= 1
    assert "某条未知分析信息" in cycles[0]["world_feedback"]


def test_writeback_conservative_no_overwrite(db):
    """保守映射：不覆盖用户已填的非空字段。"""
    database, book_id = db
    char_id = database.create_character(book_id, "测试人物")
    database.update_state_machine(char_id, {"desire_text": "用户已填的欲望"})
    with database.transaction():
        writeback_to_state_machine(database, book_id, char_id, [
            {"fact_type": "motivation", "content": "分析提取的欲望"},
        ])
    sm = database.get_state_machine(char_id)
    assert sm["desire_text"] == "用户已填的欲望"  # 未被覆盖


def test_writeback_creates_cycle_log(db):
    """写回应创建主循环日志。"""
    database, book_id = db
    char_id = database.create_character(book_id, "测试人物")
    with database.transaction():
        result = writeback_to_state_machine(database, book_id, char_id, [
            {"fact_type": "strategy", "content": "以最小代价换取最大确定性"},
        ])
    cycles = database.list_cycles(char_id)
    assert len(cycles) >= 1
    assert cycles[0]["cycle_type"] == "main"
    assert cycles[0]["change_score"] == 3


# ----------------------------------------------------------------------
# 静态属性写回回归测试（Task 7.2）
# ----------------------------------------------------------------------

def test_writeback_appearance_fact_to_state_machine(db):
    """V3 写回含 appearance fact 时正确写入 appearance_keywords 字段。"""
    database, book_id = db
    char_id = database.create_character(book_id, "白月")
    with database.transaction():
        writeback_to_state_machine(database, book_id, char_id, [
            {"fact_type": "appearance", "content": "银发红瞳，身形单薄"},
        ])
    sm = database.get_state_machine(char_id)
    assert sm["appearance_keywords"] == "银发红瞳，身形单薄"
    # 其他静态属性字段不应被改动
    assert sm["alias"] == ""
    assert sm["age"] == ""
    assert sm["gender"] == ""
    assert sm["signature_feature"] == ""
    assert sm["identity_occupation"] == ""


def test_writeback_age_gender_alias_identity_facts(db):
    """V3 写回含 age/gender/alias/identity 的 facts 时正确映射到对应字段。"""
    database, book_id = db
    char_id = database.create_character(book_id, "苍雷")
    facts = [
        {"fact_type": "alias", "content": "苍雷剑圣"},
        {"fact_type": "age", "content": "31"},
        {"fact_type": "gender", "content": "男"},
        {"fact_type": "identity_occupation", "content": "佣兵团长"},
    ]
    with database.transaction():
        writeback_to_state_machine(database, book_id, char_id, facts)
    sm = database.get_state_machine(char_id)
    assert sm["alias"] == "苍雷剑圣"
    assert sm["age"] == "31"
    assert sm["gender"] == "男"
    assert sm["identity_occupation"] == "佣兵团长"


def test_writeback_does_not_overwrite_filled_static_attrs(db):
    """保守映射：不覆盖用户已填的非空静态属性字段。"""
    database, book_id = db
    char_id = database.create_character(book_id, "白月")
    # 预填部分静态属性字段（模拟用户已填）
    database.update_state_machine(char_id, {
        "alias": "用户已填别名",
        "age": "用户已填年龄",
    })
    facts = [
        {"fact_type": "alias", "content": "分析提取的别名"},
        {"fact_type": "age", "content": "27"},
        {"fact_type": "gender", "content": "女"},  # 空字段，应被填充
    ]
    with database.transaction():
        writeback_to_state_machine(database, book_id, char_id, facts)
    sm = database.get_state_machine(char_id)
    # 已填字段应保留原值，不被覆盖
    assert sm["alias"] == "用户已填别名"
    assert sm["age"] == "用户已填年龄"
    # 空字段应被新值填充
    assert sm["gender"] == "女"
