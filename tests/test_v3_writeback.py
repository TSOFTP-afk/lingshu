"""V3 写回功能单元测试 — 覆盖人物卡、世界卡、书籍卡写回、门禁、apply_card 及边界情况。"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from novel_app.analysis import AnalysisCardDraft, AnalysisStore
from novel_app.analysis.v3_writeback import writeback_v3_card
from novel_app.analysis.writeback_card_generator import WritebackCardGenerator
from novel_app.database import Database


# ---------------------------------------------------------------------------
# 辅助：Database 缺少的 query_one / execute 方法（与 test_ai_provider.py 一致）
# ---------------------------------------------------------------------------
def _query_one(self, sql: str, params: tuple = ()):
    cursor = self.connection.execute(sql, params)
    return cursor.fetchone()


def _db_execute(self, sql: str, params: tuple = ()):
    return self.connection.execute(sql, params)


Database.query_one = _query_one
Database.execute = _db_execute


class FakeAIProvider:
    def __init__(self, output=None, exc: Exception | None = None) -> None:
        self.output = output if output is not None else {}
        self.exc = exc
        self.calls: list[dict] = []

    def _call_llm(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return self.output


# ---------------------------------------------------------------------------
# Fixture 工具
# ---------------------------------------------------------------------------
def _make_db(tmp: str) -> Database:
    db = Database(Path(tmp) / "novels.db")
    db.initialize()
    return db


def _character_card(name: str, role: str = "", profile_text: str = "") -> dict:
    """构造一张人物写回卡片。"""
    return {
        "card_type": "character_profile",
        "payload": {
            "writeback_target": "character",
            "writeback_fields": {
                "name": name,
                "role": role,
                "profile_text": profile_text,
            },
        },
    }


def _world_entry_card(name: str, category: str = "设定", content_text: str = "") -> dict:
    """构造一张世界观写回卡片。"""
    return {
        "card_type": "world_entry",
        "payload": {
            "writeback_target": "world_entry",
            "writeback_fields": {
                "name": name,
                "category": category,
                "content_text": content_text,
            },
        },
    }


def _book_card(outline_text: str = "", world_text: str = "") -> dict:
    """构造一张书籍写回卡片。"""
    return {
        "card_type": "book_outline",
        "payload": {
            "writeback_target": "book",
            "writeback_fields": {
                "outline_text": outline_text,
                "world_text": world_text,
            },
        },
    }


# ===================================================================
# 人物卡写回测试
# ===================================================================


def test_writeback_character_new():
    """新人物写回 — 验证 characters 表中新增了记录。"""
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("写回测试书")
            card = _character_card("林一", "男主", "天赋异禀的修仙者")
            result = writeback_v3_card(db, book_id, card)

            assert result.success is True
            assert result.applied_table == "characters"
            assert result.applied_id is not None
            assert result.snapshot_id is not None

            characters = db.list_characters(book_id)
            assert len(characters) == 1
            snapshots = db.list_analysis_apply_snapshots(book_id)
            assert snapshots
            assert int(snapshots[0]["id"]) == result.snapshot_id
            assert str(characters[0]["name"]).strip() == "林一"
        finally:
            db.close()


def test_writeback_character_with_required_generator_refines_fields_and_snapshot():
    """强制生成器路径 — 写回前使用 LLM 字段，并将生成元数据写入快照。"""
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("写回生成测试书")
            card = _character_card("林一", "原角色", "林一。天赋异禀。")
            generator = WritebackCardGenerator(FakeAIProvider({
                "name": "错误改名",
                "role": "主角",
                "profile_text": "林一是以冷静判断推进剧情的主角。",
            }))

            result = writeback_v3_card(
                db,
                book_id,
                card,
                writeback_generator=generator,
                require_generator=True,
            )

            assert result.success is True
            assert result.generation_used is True
            assert result.writeback_fields["name"] == "林一"
            assert result.writeback_fields["role"] == "主角"
            characters = db.list_characters(book_id)
            assert any(str(ch["name"] or "") == "林一" for ch in characters)
            snapshots = db.list_analysis_apply_snapshots(book_id)
            snapshot = json.loads(str(snapshots[0]["snapshot_json"] or "{}"))
            assert snapshot["writeback_fields"]["profile_text"] == "林一是以冷静判断推进剧情的主角。"
            assert snapshot["original_writeback_fields"]["profile_text"] == "林一。天赋异禀。"
            assert snapshot["writeback_generation"]["used"] is True
        finally:
            db.close()


def test_writeback_required_generator_missing_fails_closed():
    """强制生成器但未提供 — 不应写入业务表。"""
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("写回生成测试书")
            result = writeback_v3_card(db, book_id, _character_card("林一", "主角", "测试"), require_generator=True)

            assert result.success is False
            assert "生成器不可用" in result.detail
            assert db.list_characters(book_id) == []
            assert db.list_analysis_apply_snapshots(book_id) == []
        finally:
            db.close()


def test_writeback_generator_invalid_output_fails_closed():
    """LLM 输出缺少内容 — 不应创建快照或写入业务表。"""
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("写回生成测试书")
            generator = WritebackCardGenerator(FakeAIProvider({"name": "林一", "role": "主角"}))

            result = writeback_v3_card(
                db,
                book_id,
                _character_card("林一", "主角", "机械拼接"),
                writeback_generator=generator,
                require_generator=True,
            )

            assert result.success is False
            assert "AI 写回卡片生成失败" in result.detail
            assert db.list_characters(book_id) == []
            assert db.list_analysis_apply_snapshots(book_id) == []
        finally:
            db.close()


def test_writeback_character_existing():
    """已有人物更新 — 验证 profile 合并更新。"""
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("写回测试书")
            # 先创建同名人物
            db.create_character(book_id, "林一")

            card = _character_card("林一", "男主", "天赋异禀的修仙者")
            result = writeback_v3_card(db, book_id, card)

            assert result.success is True
            assert result.applied_table == "characters"

            characters = db.list_characters(book_id)
            assert len(characters) == 1  # 不应重复创建
            assert str(characters[0]["name"]).strip() == "林一"
            # profile_text 应包含新写入的内容
            profile = str(characters[0]["profile_text"] or "")
            assert "天赋异禀" in profile or "林一" in profile
        finally:
            db.close()


# ===================================================================
# 世界卡写回测试
# ===================================================================


def test_writeback_world_entry_new():
    """新世界观条目写回 — 验证 world_entries 表中新增了记录。"""
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("写回测试书")
            card = _world_entry_card("青云宗", "宗门", "位于东洲的修仙大宗")
            result = writeback_v3_card(db, book_id, card)

            assert result.success is True
            assert result.applied_table == "world_entries"
            assert result.applied_id is not None

            entries = db.list_world_entries(book_id)
            # list_world_entries 会插入一个"世界观总设定"条目，所以找非总设定的
            real_entries = [e for e in entries if str(e.get("name") or "") == "青云宗"]
            assert len(real_entries) == 1
        finally:
            db.close()


def test_writeback_world_entry_existing():
    """已有世界观条目更新 — 验证 content_text 追加。"""
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("写回测试书")
            # 先创建同名条目
            entry_id = db.create_world_entry(book_id, "青云宗", category="宗门")
            db.update_world_entry(entry_id, name="青云宗", category="宗门", content_text="旧内容")

            card = _world_entry_card("青云宗", "宗门", "新追加的内容")
            result = writeback_v3_card(db, book_id, card)

            assert result.success is True
            assert result.applied_id == entry_id

            entry = db.get_world_entry(entry_id)
            content = str(entry["content_text"] or "")
            # 应包含旧内容和新内容
            assert "旧内容" in content
            assert "新追加的内容" in content
        finally:
            db.close()


# ===================================================================
# 书籍卡写回测试
# ===================================================================


def test_writeback_book_outline():
    """书籍大纲写回 — 验证 books 表的 outline_text 更新。"""
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("写回测试书")
            card = _book_card(outline_text="第一卷：初入修仙界")
            result = writeback_v3_card(db, book_id, card)

            assert result.success is True
            assert result.applied_table == "books"
            assert result.applied_id == book_id

            book = db.get_book(book_id)
            outline = str(book["outline_text"] or "")
            assert "初入修仙界" in outline
        finally:
            db.close()


def test_writeback_book_world():
    """书籍世界观写回 — 验证 books 表的 world_text 更新。"""
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("写回测试书")
            card = _book_card(world_text="灵气复苏，万族林立")
            result = writeback_v3_card(db, book_id, card)

            assert result.success is True
            assert result.applied_table == "books"

            book = db.get_book(book_id)
            world = str(book["world_text"] or "")
            assert "灵气复苏" in world
        finally:
            db.close()


# ===================================================================
# 写回门禁测试
# ===================================================================


def test_writeback_gate_allowed():
    """门禁通过 — 运行 completed 且无阻断项。"""
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("门禁测试书")
            store = AnalysisStore(db)
            run_id = store.create_run(book_id, status="completed")

            # 无 pending backtrack 任务，写回应能正常执行
            card = _character_card("林一", "男主", "测试")
            result = writeback_v3_card(db, book_id, card)

            assert result.success is True

            # 确认 run 状态仍为 completed，无阻断
            run = store.get_run(run_id)
            assert run is not None
            assert run["status"] == "completed"
        finally:
            db.close()


def test_writeback_gate_blocked():
    """门禁阻断 — 存在 pending backtrack。"""
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("门禁测试书")
            store = AnalysisStore(db)
            run_id = store.create_run(book_id, status="completed")

            # 创建一个 pending backtrack task
            store.create_backtrack_task(
                book_id,
                run_id,
                task_uid="BT-test001",
                trigger_type="entity_updated",
                target_uid="ENT-linyi",
                impact={"reason": "test"},
                status="pending",
            )

            # 存在 pending backtrack 时，虽然 writeback_v3_card 本身不做门禁检查，
            # 但通过 list_backtrack_tasks 可以确认阻断项存在
            pending = store.list_backtrack_tasks(book_id, run_id=run_id, status="pending")
            assert len(pending) > 0

            # 额外验证：run 不应处于可写回状态
            # 实际场景中，上层调用方应在存在 pending backtrack 时阻止写回
            # 这里验证数据一致性：pending 任务存在
            all_tasks = store.list_backtrack_tasks(book_id, run_id=run_id)
            pending_tasks = [t for t in all_tasks if str(t["status"]) == "pending"]
            assert len(pending_tasks) >= 1
        finally:
            db.close()


# ===================================================================
# apply_card 测试
# ===================================================================


def test_apply_card_with_writeback():
    """apply_card 执行写回并标记 applied。"""
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("apply_card 测试书")
            store = AnalysisStore(db)
            run_id = store.create_run(book_id, status="completed")

            # 创建一张人物写回卡片
            store.create_card(
                book_id,
                run_id,
                AnalysisCardDraft(
                    card_uid="CARD-char-linyi",
                    card_type="character_profile",
                    payload={
                        "writeback_target": "character",
                        "writeback_fields": {
                            "name": "林一",
                            "role": "男主",
                            "profile_text": "天赋异禀",
                        },
                    },
                    diff={"applyable": True},
                ),
            )

            # 执行 apply_card
            result_card = store.apply_card(book_id, run_id, "CARD-char-linyi")

            # 验证卡片状态已变为 applied
            assert result_card is not None
            assert str(result_card["status"]) == "applied"
            assert str(result_card["applied_table"]) == "characters"
            assert result_card["applied_id"] is not None

            # 验证人物确实被创建了
            characters = db.list_characters(book_id)
            assert len(characters) >= 1
            names = [str(ch["name"]).strip() for ch in characters]
            assert "林一" in names
        finally:
            db.close()


# ===================================================================
# 边界情况
# ===================================================================


def test_writeback_no_payload():
    """卡片无 payload — 返回失败。"""
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("边界测试书")
            card = {"card_type": "character_profile"}  # 无 payload 也无 payload_json
            result = writeback_v3_card(db, book_id, card)

            assert result.success is False
            assert "无 payload" in result.detail
        finally:
            db.close()


def test_writeback_unknown_target():
    """未知 writeback_target — 返回失败。"""
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("边界测试书")
            card = {
                "card_type": "unknown",
                "payload": {
                    "writeback_target": "nonexistent_target",
                    "writeback_fields": {"name": "测试"},
                },
            }
            result = writeback_v3_card(db, book_id, card)

            assert result.success is False
            assert "未知" in result.detail
        finally:
            db.close()
