"""端到端集成测试 — 测试小说自动写入 + V3 分析 + 写回验证

测试步骤：
1. 创建临时数据库
2. 写入测试小说（book + chapters + characters + world_entries）
3. 启动 V3 分析流水线（use_ai=False，规则模式）
4. 验证分析产出（blocks/mentions/entities/facts/cards 非空）
5. 验证写回门禁（卡片 payload 包含 writeback_target 和 writeback_fields）
6. 执行批量写回
7. 验证人物卡写回（characters 表更新）
8. 验证世界卡写回（world_entries 表更新）
9. 验证书籍卡写回（books 表 outline/world 更新）
10. 验证卡片状态（applied + applied_table + applied_id）
11. 清理测试数据
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from novel_app.analysis.pipeline_v3 import PIPELINE_V3_VERSION, AnalysisPipelineV3
from novel_app.analysis.semantic_chunker import SemanticChunker
from novel_app.analysis.store import AnalysisStore
from novel_app.analysis.v3_writeback import WritebackResult
from novel_app.database import Database
from tests.fixtures.test_novel import get_test_novel


def _setup_database(tmp: str) -> Database:
    """创建并初始化临时数据库。"""
    db = Database(Path(tmp) / "novels.db")
    db.initialize()
    return db


def _write_test_novel(db: Database) -> int:
    """将测试小说写入数据库，返回 book_id。"""
    novel = get_test_novel()
    book_id = db.create_book(novel["title"])

    # 写入章节
    for chapter_data in novel["chapters"]:
        chapter_id = db.create_chapter(book_id, chapter_data["title"])
        db.update_chapter(chapter_id, outline="", content=chapter_data["content"])

    # 写入初始人物
    for char_data in novel["characters"]:
        db.create_character(book_id, char_data["name"])

    # 写入初始世界观条目
    for world_data in novel["world_entries"]:
        entry_id = db.create_world_entry(book_id, world_data["name"], category=world_data["category"])
        db.update_world_entry(entry_id, name=world_data["name"], category=world_data["category"], content_text=world_data["content_text"])

    return book_id


def test_e2e_v3_analysis_and_writeback() -> None:
    """端到端测试：写入测试小说 → V3 分析 → 写回验证。"""
    with TemporaryDirectory() as tmp:
        db = _setup_database(tmp)
        try:
            # ── 步骤 1-2: 写入测试小说 ──
            book_id = _write_test_novel(db)
            novel = get_test_novel()

            # 验证写入
            book = db.get_book(book_id)
            assert book is not None
            assert book["title"] == novel["title"]
            chapters = db.list_chapters(book_id)
            assert len(chapters) == len(novel["chapters"])
            characters = db.list_characters(book_id)
            assert len(characters) == len(novel["characters"])
            # list_world_entries 会额外包含一条"世界观总设定"
            world_entries = db.list_world_entries(book_id)
            world_names = {str(e["name"]) for e in world_entries}
            for we in novel["world_entries"]:
                assert we["name"] in world_names

            # ── 步骤 3: 启动 V3 分析流水线 ──
            chunker = SemanticChunker(target_chars=200, max_chars=500)
            pipeline = AnalysisPipelineV3(db, chunker=chunker)
            result = pipeline.start_run(book_id, use_ai=False)

            # ── 步骤 4: 验证分析产出 ──
            assert result.status == "probes_ready"
            assert result.run_id > 0
            assert result.block_count > 0, f"语义块数量应为正数，实际: {result.block_count}"
            assert result.mention_count > 0, f"实体提及数量应为正数，实际: {result.mention_count}"
            assert result.entity_count > 0, f"实体数量应为正数，实际: {result.entity_count}"
            assert result.fact_count > 0, f"事实数量应为正数，实际: {result.fact_count}"
            assert result.card_count > 0, f"卡片数量应为正数，实际: {result.card_count}"

            # 验证数据库中的分析产出
            blocks = db.list_analysis_blocks(book_id, run_id=result.run_id)
            assert len(blocks) == result.block_count

            mentions = db.list_analysis_entity_mentions(book_id, run_id=result.run_id)
            assert len(mentions) == result.mention_count

            entities = db.list_analysis_entities(book_id, run_id=result.run_id)
            assert len(entities) == result.entity_count

            facts = db.list_analysis_facts(book_id, run_id=result.run_id)
            assert len(facts) == result.fact_count

            cards = db.list_analysis_cards(result.run_id)
            assert len(cards) == result.card_count

            # 验证流水线版本
            run = db.get_analysis_run(result.run_id)
            assert run is not None
            assert run["pipeline_version"] == PIPELINE_V3_VERSION

            # ── 步骤 5: 验证写回门禁 ──
            # V3 卡片应包含 writeback_target 和 writeback_fields
            store = AnalysisStore(db)
            cards_with_writeback = []
            for card in cards:
                payload_json = str(card["payload_json"] or "{}")
                payload = json.loads(payload_json)
                writeback_target = str(payload.get("writeback_target") or "")
                writeback_fields = payload.get("writeback_fields")
                if writeback_target and isinstance(writeback_fields, dict):
                    cards_with_writeback.append({
                        "card": dict(card),
                        "writeback_target": writeback_target,
                        "writeback_fields": writeback_fields,
                    })

            assert len(cards_with_writeback) > 0, "至少应有一张卡片包含 writeback_target"

            # 验证卡片类型覆盖
            writeback_targets = {item["writeback_target"] for item in cards_with_writeback}
            assert "character" in writeback_targets, "应包含人物卡（writeback_target=character）"

            # ── 步骤 6: 执行批量写回 ──
            applied_results: list[WritebackResult] = []
            for item in cards_with_writeback:
                card_uid = str(item["card"]["card_uid"])
                # store.apply_card 内部会调用 writeback_v3_card 并标记卡片状态
                applied_card = store.apply_card(book_id, result.run_id, card_uid)
                if applied_card and str(applied_card["status"]) == "applied":
                    applied_results.append(WritebackResult(True, str(applied_card["applied_table"]), applied_card["applied_id"]))

            # 至少有一张卡片写回成功
            success_count = sum(1 for r in applied_results if r.success)
            assert success_count > 0, f"至少应有一张卡片写回成功，实际成功: {success_count}/{len(applied_results)}"

            # ── 步骤 7: 验证人物卡写回 ──
            character_cards = [item for item in cards_with_writeback if item["writeback_target"] == "character"]
            if character_cards:
                updated_characters = db.list_characters(book_id)
                char_names = {str(ch["name"]) for ch in updated_characters}
                # 初始人物 + 写回创建的新人物都应存在
                for cc in character_cards:
                    name = str(cc["writeback_fields"].get("name") or "").strip()
                    if name:
                        assert name in char_names, f"人物 '{name}' 应在 characters 表中"

            # ── 步骤 8: 验证世界卡写回 ──
            world_cards = [item for item in cards_with_writeback if item["writeback_target"] == "world_entry"]
            if world_cards:
                updated_entries = db.list_world_entries(book_id)
                entry_names = {str(e["name"]) for e in updated_entries}
                for wc in world_cards:
                    name = str(wc["writeback_fields"].get("name") or "").strip()
                    if name:
                        assert name in entry_names, f"世界观条目 '{name}' 应在 world_entries 表中"

            # ── 步骤 9: 验证书籍卡写回 ──
            book_cards = [item for item in cards_with_writeback if item["writeback_target"] == "book"]
            if book_cards:
                updated_book = db.get_book(book_id)
                assert updated_book is not None
                # 书籍卡写回会更新 outline_text 或 world_text
                for bc in book_cards:
                    outline_text = str(bc["writeback_fields"].get("outline_text") or "").strip()
                    world_text = str(bc["writeback_fields"].get("world_text") or "").strip()
                    if outline_text:
                        assert str(updated_book["outline_text"] or "").strip(), "书籍 outline_text 应非空"
                    if world_text:
                        assert str(updated_book["world_text"] or "").strip(), "书籍 world_text 应非空"

            # ── 步骤 10: 验证卡片状态 ──
            # 重新读取卡片，验证已写回的卡片状态
            refreshed_cards = db.list_analysis_cards(result.run_id)
            applied_cards = [c for c in refreshed_cards if str(c["status"]) == "applied"]
            assert len(applied_cards) > 0, "至少应有一张卡片状态为 applied"

            for card in applied_cards:
                assert str(card["applied_table"] or "").strip(), f"卡片 {card['card_uid']} 的 applied_table 应非空"
                assert card["applied_id"] is not None, f"卡片 {card['card_uid']} 的 applied_id 应非空"
                assert card["applied_at"] is not None, f"卡片 {card['card_uid']} 的 applied_at 应非空"

            # 验证 applied_table 的值是合法的业务表名
            valid_tables = {"characters", "world_entries", "books"}
            for card in applied_cards:
                assert str(card["applied_table"]) in valid_tables, (
                    f"卡片 {card['card_uid']} 的 applied_table='{card['applied_table']}' 不在合法表名集合中"
                )

        finally:
            db.close()


def test_e2e_v3_writeback_character_profile_updated() -> None:
    """端到端测试：验证人物卡写回后 profile_text 被更新。"""
    with TemporaryDirectory() as tmp:
        db = _setup_database(tmp)
        try:
            book_id = _write_test_novel(db)

            # 记录写回前的人物 profile
            characters_before = {str(ch["name"]): str(ch["profile_data_json"] or "") for ch in db.list_characters(book_id)}

            # 运行 V3 分析
            chunker = SemanticChunker(target_chars=200, max_chars=500)
            pipeline = AnalysisPipelineV3(db, chunker=chunker)
            result = pipeline.start_run(book_id, use_ai=False)

            store = AnalysisStore(db)
            cards = db.list_analysis_cards(result.run_id)

            # 执行人物卡写回
            for card in cards:
                payload_json = str(card["payload_json"] or "{}")
                payload = json.loads(payload_json)
                if str(payload.get("writeback_target") or "") == "character":
                    card_uid = str(card["card_uid"])
                    store.apply_card(book_id, result.run_id, card_uid)

            # 验证人物 profile 被更新
            characters_after = {str(ch["name"]): str(ch["profile_data_json"] or "") for ch in db.list_characters(book_id)}

            # 至少有一个初始人物的 profile_data_json 发生了变化（添加了 supplements）
            profile_changed = False
            for name in characters_before:
                before = characters_before[name].strip()
                after = characters_after.get(name, "").strip()
                if after and after != before:
                    profile_changed = True
                    break
            assert profile_changed, "至少应有一个初始人物的 profile_data_json 在写回后被更新"

        finally:
            db.close()


def test_e2e_v3_writeback_idempotent() -> None:
    """端到端测试：验证重复写回不会产生重复数据。"""
    with TemporaryDirectory() as tmp:
        db = _setup_database(tmp)
        try:
            book_id = _write_test_novel(db)

            # 运行 V3 分析
            chunker = SemanticChunker(target_chars=200, max_chars=500)
            pipeline = AnalysisPipelineV3(db, chunker=chunker)
            result = pipeline.start_run(book_id, use_ai=False)

            cards = db.list_analysis_cards(result.run_id)

            # 第一次写回
            store = AnalysisStore(db)
            for card in cards:
                payload_json = str(card["payload_json"] or "{}")
                payload = json.loads(payload_json)
                if str(payload.get("writeback_target") or "") == "character":
                    card_uid = str(card["card_uid"])
                    store.apply_card(book_id, result.run_id, card_uid)

            characters_after_first = db.list_characters(book_id)
            char_count_first = len(characters_after_first)

            # 第二次写回（相同卡片）
            for card in cards:
                payload_json = str(card["payload_json"] or "{}")
                payload = json.loads(payload_json)
                if str(payload.get("writeback_target") or "") == "character":
                    card_uid = str(card["card_uid"])
                    store.apply_card(book_id, result.run_id, card_uid)

            characters_after_second = db.list_characters(book_id)
            char_count_second = len(characters_after_second)

            # 人物数量不应增加（写回应更新而非重复创建）
            assert char_count_second == char_count_first, (
                f"重复写回不应增加人物数量: 第一次={char_count_first}, 第二次={char_count_second}"
            )

        finally:
            db.close()


def test_e2e_v3_pipeline_meta_and_audit() -> None:
    """端到端测试：验证 V3 分析流水线的 meta 信息和审计日志。"""
    with TemporaryDirectory() as tmp:
        db = _setup_database(tmp)
        try:
            book_id = _write_test_novel(db)

            chunker = SemanticChunker(target_chars=200, max_chars=500)
            pipeline = AnalysisPipelineV3(db, chunker=chunker)
            result = pipeline.start_run(book_id, use_ai=False)

            # 验证 meta 信息
            assert result.meta["pipeline_family"] == "analysis_v3"
            assert result.meta["current_phase"] == "M8"
            assert "source_chapter_count" in result.meta
            assert result.meta["source_chapter_count"] == len(get_test_novel()["chapters"])
            assert "fact_count" in result.meta
            assert "card_count" in result.meta
            assert "memory_fact_count" in result.meta
            assert "probe_result_count" in result.meta

            # 验证审计日志
            audit_logs = db.list_analysis_audit_logs(book_id, result.run_id)
            assert len(audit_logs) > 0, "应产生审计日志"

            audit_actions = {str(log["action"]) for log in audit_logs}
            assert "analysis_v3_l1_blocks_created" in audit_actions, "应包含语义块创建日志"
            assert "analysis_v3_mentions_created" in audit_actions, "应包含提及创建日志"
            assert "analysis_v3_entities_resolved" in audit_actions, "应包含实体消解日志"
            assert "analysis_v3_facts_created" in audit_actions, "应包含事实创建日志"
            assert "analysis_v3_cards_created" in audit_actions, "应包含卡片创建日志"

        finally:
            db.close()
