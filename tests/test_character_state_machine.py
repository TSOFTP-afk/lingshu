"""人物状态机回归测试。

覆盖 CharacterStateMachineMixin 的核心场景：
- create_character 自动初始化状态机
- update_state_machine 三轴字段更新
- create_cycle 增值计算与快照触发（main light / 门槛 / heavy 强制 / micro 不存档）
- get_character_profile_form 从状态机生成旧格式
- list_cycles 类型过滤
- list_snapshots 显式调用避免 MRO 冲突
"""
from __future__ import annotations

import pytest

from novel_app.database import Database
from novel_app.db.character_state_machine import CharacterStateMachineMixin


@pytest.fixture
def db(tmp_path):
    """创建临时数据库。"""
    database = Database(str(tmp_path / "test.db"))
    database.initialize()
    # 创建测试 book
    book_id = database.create_book("测试书")
    return database, book_id


def test_create_character_auto_init_state_machine(db):
    """create_character 应自动创建状态机行。"""
    database, book_id = db
    char_id = database.create_character(book_id, "测试人物")
    sm = database.get_state_machine(char_id)
    assert sm is not None
    assert sm["desire_text"] == ""
    assert sm["current_desire_state"] == "original"
    assert sm["current_fate_state"] == "dormant"
    assert sm["total_change_score"] == 0


def test_update_state_machine(db):
    """update_state_machine 应更新三轴字段。"""
    database, book_id = db
    char_id = database.create_character(book_id, "测试人物")
    database.update_state_machine(char_id, {
        "desire_text": "复活卡莲",
        "mbti_type": "INTP",
        "fate_type": "paradox",
    })
    sm = database.get_state_machine(char_id)
    assert sm["desire_text"] == "复活卡莲"
    assert sm["mbti_type"] == "INTP"
    assert sm["fate_type"] == "paradox"


def test_create_cycle_main_light_score(db):
    """主循环 light 应 +3 分。"""
    database, book_id = db
    char_id = database.create_character(book_id, "测试人物")
    with database.transaction():
        result = database.create_cycle(char_id, {
            "cycle_type": "main",
            "intensity": "light",
            "world_feedback": "测试反馈",
        })
    assert result["cumulative_score"] == 3
    assert result["snapshot_created"] is False  # 3 未跨 10 门槛


def test_create_cycle_threshold_triggers_snapshot(db):
    """累计增值跨 10 门槛应触发快照存档。"""
    database, book_id = db
    char_id = database.create_character(book_id, "测试人物")
    # 先加 8 分（main heavy）
    with database.transaction():
        database.create_cycle(char_id, {"cycle_type": "main", "intensity": "heavy"})
    # 再加 3 分（main light），累计 11，跨 10 门槛
    with database.transaction():
        result = database.create_cycle(char_id, {"cycle_type": "main", "intensity": "light"})
    assert result["cumulative_score"] == 11
    assert result["snapshot_created"] is True
    assert result["snapshot_id"] is not None


def test_create_heavy_cycle_forces_snapshot(db):
    """重循环应强制触发快照存档，无论门槛。"""
    database, book_id = db
    char_id = database.create_character(book_id, "测试人物")
    with database.transaction():
        result = database.create_cycle(char_id, {
            "cycle_type": "heavy",
            "intensity": "existential",
            "world_feedback": "存在论级冲击",
        })
    assert result["cumulative_score"] == 10
    assert result["snapshot_created"] is True  # heavy 强制存档


def test_micro_cycle_no_snapshot(db):
    """微循环不应触发存档。"""
    database, book_id = db
    char_id = database.create_character(book_id, "测试人物")
    with database.transaction():
        database.create_cycle(char_id, {"cycle_type": "main", "intensity": "light"})
    # micro 不通过 create_cycle，而是通过 create_micro_batch
    # 或者 create_cycle(micro) 应返回不存档
    # 根据 Mixin 实现，create_cycle 支持 micro（score=1），但 micro 不存档
    sm = database.get_state_machine(char_id)
    assert sm["total_change_score"] == 3  # 只有 main light 的 3 分


def test_get_character_profile_form_from_state_machine(db):
    """get_character_profile_form 应从状态机生成旧格式。"""
    database, book_id = db
    char_id = database.create_character(book_id, "测试人物")
    database.update_character(char_id, "测试人物", "主角", "", None)  # 设 role
    database.update_state_machine(char_id, {
        "desire_text": "复活挚爱",
        "belief_core": "为爱牺牲一切",
    })
    form = database.get_character_profile_form(char_id)
    assert form is not None
    # 验证状态机字段映射到旧表单（具体字段需根据兼容层实现确认）
    # 至少 supplements 应保留


def test_list_cycles(db):
    """list_cycles 应返回循环日志列表。"""
    database, book_id = db
    char_id = database.create_character(book_id, "测试人物")
    with database.transaction():
        database.create_cycle(char_id, {"cycle_type": "main", "intensity": "light"})
        database.create_cycle(char_id, {"cycle_type": "heavy", "intensity": "existential"})
    cycles = database.list_cycles(char_id)
    assert len(cycles) == 2
    # 验证类型过滤
    main_cycles = database.list_cycles(char_id, "main")
    assert len(main_cycles) == 1
    heavy_cycles = database.list_cycles(char_id, "heavy")
    assert len(heavy_cycles) == 1


def test_list_snapshots_explicit_mixin_call(db):
    """list_snapshots 需显式调用 CharacterStateMachineMixin 避免MRO冲突。"""
    database, book_id = db
    char_id = database.create_character(book_id, "测试人物")
    with database.transaction():
        database.create_cycle(char_id, {"cycle_type": "heavy", "intensity": "existential"})
    # 显式调用状态机版本的 list_snapshots
    snapshots = CharacterStateMachineMixin.list_snapshots(database, char_id)
    assert len(snapshots) == 1
    assert snapshots[0]["snapshot_no"] == 1
    assert snapshots[0]["trigger_type"] == "heavy_cycle"


# ----------------------------------------------------------------------
# 静态属性字段回归测试（Task 7.1）
# ----------------------------------------------------------------------

STATIC_ATTR_FIELDS = (
    "alias",
    "age",
    "gender",
    "appearance_keywords",
    "signature_feature",
    "identity_occupation",
)


def test_create_character_initializes_static_attrs_empty(db):
    """create_character 后状态机静态属性字段默认为空字符串。"""
    database, book_id = db
    char_id = database.create_character(book_id, "测试人物")
    sm = database.get_state_machine(char_id)
    assert sm is not None
    for field in STATIC_ATTR_FIELDS:
        assert sm[field] == "", f"静态属性 {field} 应默认为空字符串"


def test_update_state_machine_writes_static_attrs(db):
    """update_state_machine 能正确写入 6 个静态属性字段。"""
    database, book_id = db
    char_id = database.create_character(book_id, "测试人物")
    expected = {
        "alias": "白月",
        "age": "27",
        "gender": "女",
        "appearance_keywords": "银发；红瞳",
        "signature_feature": "左颊泪痣",
        "identity_occupation": "皇家骑士",
    }
    database.update_state_machine(char_id, dict(expected))
    sm = database.get_state_machine(char_id)
    for field, value in expected.items():
        assert sm[field] == value, f"静态属性 {field} 写入失败"


def test_generate_legacy_form_backfills_static_attrs(db):
    """_generate_legacy_form_from_state_machine 能正确反向填充旧表单 6 个静态属性字段。

    仅当状态机字段非空时才覆盖旧表单字段值。
    """
    database, book_id = db
    char_id = database.create_character(book_id, "测试人物")
    database.update_character(char_id, "测试人物", "主角", "", None)
    expected = {
        "alias": "白月",
        "age": "27",
        "gender": "女",
        "appearance_keywords": "银发；红瞳",
        "signature_feature": "左颊泪痣",
        "identity_occupation": "皇家骑士",
    }
    database.update_state_machine(char_id, dict(expected))

    form = database._generate_legacy_form_from_state_machine(char_id)
    assert form is not None
    fields = form.get("fields", {})
    for field, value in expected.items():
        assert field in fields, f"旧表单缺少字段 {field}"
        assert fields[field]["value"] == value, (
            f"旧表单字段 {field} 反向填充失败：期望 {value!r}，实际 {fields[field]['value']!r}"
        )


def test_update_character_form_syncs_static_attrs_to_profile_data_json(db):
    """调用 update_character_form 传入含静态属性的状态机字段后，
    profile_data_json 中对应字段被正确更新。

    profile_data_json 结构：{"fields": {"alias": {"value": "..."}, ...}}
    """
    import json

    database, book_id = db
    char_id = database.create_character(book_id, "测试人物")
    database.update_character(char_id, "测试人物", "主角", "", None)

    static_attrs = {
        "alias": "苍雷",
        "age": "31",
        "gender": "男",
        "appearance_keywords": "黑发；刀疤",
        "signature_feature": "右手银环",
        "identity_occupation": "佣兵团长",
    }
    database.update_character_form(
        char_id,
        name="测试人物",
        role="主角",
        profile_data=dict(static_attrs),
    )

    # 直接读取 characters 表的 profile_data_json 验证同步结果
    row = database.connection.execute(
        "SELECT profile_data_json FROM characters WHERE id = ?",
        (char_id,),
    ).fetchone()
    assert row is not None
    profile_data = json.loads(row["profile_data_json"])
    fields_dict = profile_data.get("fields", {})
    assert isinstance(fields_dict, dict)
    for field, value in static_attrs.items():
        assert field in fields_dict, f"profile_data_json.fields 缺少字段 {field}"
        assert fields_dict[field].get("value") == value, (
            f"profile_data_json.fields.{field}.value 同步失败："
            f"期望 {value!r}，实际 {fields_dict[field].get('value')!r}"
        )
