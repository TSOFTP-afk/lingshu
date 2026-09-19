from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

import pytest

from novel_app.analysis.card_coordinator import CardCoordinatorResult
from novel_app.analysis.entity_store import EntityStore
from novel_app.analysis.fact_store import FactStore
from novel_app.analysis.pipeline_v3 import PIPELINE_V3_VERSION, AnalysisPipelineV3, AnalysisPipelineV3Cancelled
from novel_app.analysis.probe_executor import ProbeExecutionResult
from novel_app.analysis.semantic_chunker import SemanticChunker
from novel_app.analysis.store import AnalysisStore
from novel_app.database import Database
from novel_app.db.common import ANALYSIS_V3_FOUNDATION_MIGRATION_ID


def test_semantic_chunker_preserves_chapter_ranges_and_stable_hashes() -> None:
    content = "第一段开场。\n\n第二段推进剧情。角色说话！\n\n***\n\n第三段换场。"
    chapters = [{"id": 7, "title": "第一章", "content": content}]
    chunker = SemanticChunker(target_chars=12, max_chars=24)

    first = chunker.chunk_chapters(1, chapters, pipeline_version=PIPELINE_V3_VERSION)
    second = chunker.chunk_chapters(1, chapters, pipeline_version=PIPELINE_V3_VERSION)

    assert [block.content_hash for block in first] == [block.content_hash for block in second]
    assert [block.structure_hash for block in first] == [block.structure_hash for block in second]
    assert len(first) >= 3
    for block in first:
        assert block.text == content[block.char_start:block.char_end]
        assert block.chapter_id == 7
        assert block.pipeline_version == PIPELINE_V3_VERSION
        assert block.content_hash
        assert block.structure_hash


def test_analysis_pipeline_v3_creates_run_blocks_mentions_facts_cards_without_ai_writeback() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("V3 Book")
            db.create_character(book_id, "Lin Yi")
            chapter_id = db.create_chapter(book_id, "One")
            content = "Lin Yi enters the city.\n\nHe marks a hidden clue."
            db.update_chapter(chapter_id, outline="", content=content)

            result = AnalysisPipelineV3(db, chunker=SemanticChunker(target_chars=20, max_chars=48)).start_run(book_id)
            run = db.get_analysis_run(result.run_id)
            blocks = db.list_analysis_blocks(book_id, run_id=result.run_id)
            mentions = db.list_analysis_entity_mentions(book_id, run_id=result.run_id)
            entities = db.list_analysis_entities(book_id, run_id=result.run_id)
            facts = db.list_analysis_facts(book_id, run_id=result.run_id)
            cards = db.list_analysis_cards(result.run_id)
            events = db.list_analysis_events(book_id, run_id=result.run_id)

            assert result.status == "probes_ready"
            assert run["pipeline_version"] == PIPELINE_V3_VERSION
            assert result.block_count == len(blocks)
            assert result.mention_count == len(mentions) == 1
            assert result.entity_count == len(entities) == 1
            assert result.fact_count == len(facts) == 1
            assert result.card_count == len(cards) == 2
            assert result.probe_plan_count >= 0
            assert result.probe_result_count >= 0
            assert mentions[0]["quote_text"] == "Lin Yi"
            assert mentions[0]["source_rule"] == "formal_character"
            assert mentions[0]["entity_uid"] == entities[0]["entity_uid"]
            assert entities[0]["canonical_name"] == "Lin Yi"
            assert entities[0]["mention_count"] == 1
            assert facts[0]["subject_entity_uid"] == entities[0]["entity_uid"]
            assert facts[0]["quote_text"] in content
            assert facts[0]["confidence"] >= 0.55
            assert facts[0]["memory_scope"] == "short_term"
            assert facts[0]["memory_type"] in {"evidence", "cache", "foundation"}
            assert facts[0]["importance_score"] > 0
            aliases = db.list_analysis_entity_aliases(book_id, result.run_id, str(entities[0]["entity_uid"]))
            versions = db.list_analysis_entity_versions(book_id, result.run_id, str(entities[0]["entity_uid"]))
            assert [row["alias"] for row in aliases] == ["Lin Yi"]
            assert [row["action"] for row in versions] == ["auto_coreference"]
            assert AnalysisPipelineV3(db).run_entity_coreference(book_id, result.run_id) == 1
            rerun_versions = db.list_analysis_entity_versions(book_id, result.run_id, str(entities[0]["entity_uid"]))
            assert [row["version"] for row in rerun_versions] == [1]
            assert AnalysisPipelineV3(db).run_atomic_facts(book_id, result.run_id) == 1
            rerun_facts = db.list_analysis_facts(book_id, run_id=result.run_id)
            assert len(rerun_facts) == 1
            assert {row["card_type"] for row in cards} == {"v3_character", "v3_book_summary"}
            assert all(str(row["card_type"] or "") != "full_payload" for row in cards)
            assert len(events) == result.card_count
            assert AnalysisPipelineV3(db).run_card_events(book_id, result.run_id).active_card_count == 2
            assert len(db.list_analysis_cards(result.run_id)) == 2
            assert all(row["pipeline_version"] == PIPELINE_V3_VERSION for row in blocks)
            assert all(row["structure_hash"] for row in blocks)
            assert all(row["content_hash"] for row in blocks)
            for row in blocks:
                assert str(row["text"]) == content[int(row["char_start"]):int(row["char_end"])]
        finally:
            db.close()


def test_analysis_pipeline_v3_handles_ten_chapter_sample() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Ten Chapter V3 Book")
            for index in range(1, 11):
                chapter_id = db.create_chapter(book_id, f"Chapter {index}")
                db.update_chapter(
                    chapter_id,
                    outline="",
                    content=f"Chapter {index} opening scene.\n\nChapter {index} clue and consequence.",
                )

            result = AnalysisPipelineV3(db).start_run(book_id)
            blocks = db.list_analysis_blocks(book_id, run_id=result.run_id)

            assert result.status == "probes_ready"
            assert result.block_count >= 10
            assert len(blocks) == result.block_count
            assert result.meta["source_chapter_count"] == 10
            assert "fact_count" in result.meta
            assert "card_count" in result.meta
            assert result.meta["current_phase"] == "Done"
            assert "memory_fact_count" in result.meta
            assert "probe_result_count" in result.meta
        finally:
            db.close()


def test_analysis_v3_internal_reads_do_not_truncate_large_candidates() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("large candidate book")
            chapter_id = db.create_chapter(book_id, "large chapter")
            db.update_chapter(chapter_id, outline="", content="large synthetic content")
            run_id = AnalysisStore(db).create_run(book_id, status="facts_ready", pipeline_version=PIPELINE_V3_VERSION)
            mention_count = 6001
            fact_count = 10001
            entity_count = 1001

            db.replace_analysis_entity_mentions(
                book_id,
                run_id,
                [
                    {
                        "mention_uid": f"MEN-{index}",
                        "entity_uid": "",
                        "entity_type": "character",
                        "normalized_text": f"name-{index}",
                        "quote_text": f"Name {index}",
                        "chapter_id": chapter_id,
                        "block_uid": "block-large",
                        "char_start": index,
                        "char_end": index + 6,
                        "confidence": 0.8,
                        "source_rule": "test",
                    }
                    for index in range(mention_count)
                ],
            )
            db.replace_analysis_entities(
                book_id,
                run_id,
                [
                    {
                        "entity_uid": f"ENT-{index}",
                        "entity_type": "character",
                        "canonical_name": f"Name {index}",
                        "aliases": [],
                        "mention_uids": [f"MEN-{index}"] if index < mention_count else [],
                        "confidence": 0.8,
                        "source_rule": "test",
                    }
                    for index in range(entity_count)
                ],
            )
            db.replace_analysis_facts(
                book_id,
                run_id,
                [
                    {
                        "fact_uid": f"FACT-{index}",
                        "subject_entity_uid": f"ENT-{index % entity_count}",
                        "fact_type": "event",
                        "value": {"summary": f"Fact {index}"},
                        "quote_text": f"Fact quote {index}",
                        "chapter_id": chapter_id,
                        "block_uid": "block-large",
                        "confidence": 0.8,
                    }
                    for index in range(fact_count)
                ],
            )

            entity_store = EntityStore(db)
            fact_store = FactStore(db)
            assert len(entity_store.list_mentions(book_id, run_id=run_id)) == 1000
            assert len(entity_store.list_mentions(book_id, run_id=run_id, limit=None)) == mention_count
            assert len(fact_store.list_facts(book_id, run_id=run_id)) == 1000
            assert len(fact_store.list_facts(book_id, run_id=run_id, limit=None)) == fact_count

            class RecordingMemoryClassifier:
                def __init__(self):
                    self.seen_count = 0
                    self.window_builder = self
                    # V3 AI 集成后 run_memory_layer 会访问这些属性，需补齐 mock
                    self.use_ai = False
                    self.ai_provider = None
                    self._last_engine = "rule"
                def classify_facts(self, facts):
                    self.seen_count = len(facts)
                    return facts
                def migrate_expired_short_term(self, facts):
                    return facts

            class PassthroughCompressor:
                def __init__(self):
                    # V3 AI 集成后 run_memory_layer 会访问这些属性，需补齐 mock
                    self.use_ai = False
                    self.ai_provider = None
                    self._last_engine = "rule"
                def compress(self, facts):
                    return facts

            class RecordingCardCoordinator:
                def __init__(self):
                    self.fact_count = 0
                    self.entity_count = 0
                def run(self, *, book_id: int, run_id: int, target_entity_uids=None, use_ai: bool = False, ai_provider=None):
                    self.fact_count = len(FactStore(db).list_facts(book_id, run_id=run_id, limit=None))
                    self.entity_count = len(EntityStore(db).list_entities(book_id, run_id=run_id, limit=None))
                    return CardCoordinatorResult(event_count=0, card_count=0, active_card_count=0, dependency_count=0)

            class RecordingProbePlanner:
                def __init__(self):
                    self.fact_count = 0
                    self.entity_count = 0
                    self._last_engine = "rule"
                def plan(self, *, book_id: int, run_id: int, facts, entities, use_ai: bool = False, ai_provider=None):
                    self.fact_count = len(facts)
                    self.entity_count = len(entities)
                    return []

            class RecordingProbeExecutor:
                def __init__(self):
                    self.fact_count = 0
                def execute(self, *, book_id: int, run_id: int, plans=None, facts=None):
                    self.fact_count = len(facts or [])
                    return ProbeExecutionResult(0, 0, 0, 0, 0)

            pipeline = AnalysisPipelineV3(db)
            memory_classifier = RecordingMemoryClassifier()
            card_coordinator = RecordingCardCoordinator()
            probe_planner = RecordingProbePlanner()
            probe_executor = RecordingProbeExecutor()
            pipeline.memory_classifier = memory_classifier
            pipeline.memory_compressor = PassthroughCompressor()
            pipeline.card_coordinator = card_coordinator
            pipeline.probe_planner = probe_planner
            pipeline.probe_executor = probe_executor

            pipeline.run_memory_layer(book_id, run_id, update_run=False)
            pipeline.run_card_events(book_id, run_id, update_run=False)
            pipeline.run_probe_plans(book_id, run_id, update_run=False)

            assert memory_classifier.seen_count == fact_count
            assert card_coordinator.fact_count == fact_count
            assert card_coordinator.entity_count == entity_count
            assert probe_planner.fact_count == fact_count
            assert probe_planner.entity_count == entity_count
            assert probe_executor.fact_count == fact_count
        finally:
            db.close()


def test_analysis_pipeline_v3_cancel_event_marks_run_cancelled() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Cancelled V3 Book")
            chapter_id = db.create_chapter(book_id, "One")
            db.update_chapter(chapter_id, outline="", content="Alice opens the gate.")
            cancel_event = Event()

            def progress_callback(stage: str, percent: int, message: str) -> None:
                if stage == "l1_semantic_blocks" and percent >= 10:
                    cancel_event.set()

            with pytest.raises(AnalysisPipelineV3Cancelled):
                AnalysisPipelineV3(db).start_run(
                    book_id,
                    progress_callback=progress_callback,
                    cancel_event=cancel_event,
                )

            runs = db.list_analysis_runs(book_id)
            assert runs
            assert runs[0]["status"] == "cancelled"
        finally:
            db.close()


def test_analysis_v3_foundation_migration_is_repeatable() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "novels.db"
        db = Database(path)
        try:
            db.initialize()
            db.initialize()
            block_columns = {
                row["name"]
                for row in db.connection.execute("PRAGMA table_info(analysis_blocks)").fetchall()
            }
            assert {"structure_hash", "pipeline_version"}.issubset(block_columns)
            mention_columns = {
                row["name"]
                for row in db.connection.execute("PRAGMA table_info(analysis_entity_mentions)").fetchall()
            }
            assert {"mention_uid", "quote_text", "source_rule"}.issubset(mention_columns)
            entity_columns = {
                row["name"]
                for row in db.connection.execute("PRAGMA table_info(analysis_entities)").fetchall()
            }
            assert {"entity_uid", "canonical_name", "source_rule"}.issubset(entity_columns)
            fact_columns = {
                row["name"]
                for row in db.connection.execute("PRAGMA table_info(analysis_facts)").fetchall()
            }
            assert {"fact_uid", "subject_entity_uid", "quote_text", "memory_scope"}.issubset(fact_columns)
            tables = {
                row["name"]
                for row in db.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'analysis_%'"
                ).fetchall()
            }
            assert {
                "analysis_entities",
                "analysis_entity_aliases",
                "analysis_entity_mentions",
                "analysis_entity_versions",
                "analysis_events",
                "analysis_card_dependencies",
                "analysis_facts",
                "analysis_probe_plans",
                "analysis_probe_results",
                "analysis_llm_cache",
            }.issubset(tables)
            marker = db.connection.execute(
                "SELECT 1 FROM app_migrations WHERE id = ?",
                (ANALYSIS_V3_FOUNDATION_MIGRATION_ID,),
            ).fetchone()
            assert marker is not None
        finally:
            db.close()


def test_incremental_run_reuses_unchanged_chapters() -> None:
    """增量分析：未变更章节的 blocks/mentions/facts 被复用，仅处理新增章节。"""
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Incremental Book")
            db.create_character(book_id, "Alice")
            ch1_id = db.create_chapter(book_id, "Chapter 1")
            db.update_chapter(ch1_id, outline="", content="Alice walks into the forest.\n\nShe finds a hidden cave.")
            ch2_id = db.create_chapter(book_id, "Chapter 2")
            db.update_chapter(ch2_id, outline="", content="Alice discovers an ancient sword.\n\nThe sword glows faintly.")

            # 首次全量分析
            pipeline = AnalysisPipelineV3(db)
            first_result = pipeline.start_run(book_id)
            assert first_result.status == "probes_ready"
            first_run_id = first_result.run_id
            first_blocks = db.list_analysis_blocks(book_id, run_id=first_run_id)
            first_mentions = db.list_analysis_entity_mentions(book_id, run_id=first_run_id)
            first_facts = db.list_analysis_facts(book_id, run_id=first_run_id)

            # 新增第三章
            ch3_id = db.create_chapter(book_id, "Chapter 3")
            db.update_chapter(ch3_id, outline="", content="Alice meets the guardian.\n\nThe guardian warns her.")

            # 增量分析
            inc_result = pipeline.start_incremental_run(book_id)
            assert inc_result.status == "probes_ready"
            assert inc_result.meta.get("incremental") is True
            assert inc_result.meta.get("base_run_id") == first_run_id
            assert inc_result.meta.get("chapters_added", 0) >= 1
            assert inc_result.meta.get("chapters_unchanged", 0) >= 2

            inc_blocks = db.list_analysis_blocks(book_id, run_id=inc_result.run_id)
            inc_mentions = db.list_analysis_entity_mentions(book_id, run_id=inc_result.run_id)
            inc_facts = db.list_analysis_facts(book_id, run_id=inc_result.run_id)

            # 新 run 应该有更多 blocks/mentions/facts
            assert len(inc_blocks) >= len(first_blocks)
            assert len(inc_mentions) >= len(first_mentions)
            assert len(inc_facts) >= len(first_facts)

            # 审计日志应记录增量分析
            audit = db.connection.execute(
                "SELECT action FROM analysis_audit_logs WHERE run_id = ? AND action = ?",
                (inc_result.run_id, "analysis_v3_incremental_run_completed"),
            ).fetchone()
            assert audit is not None
        finally:
            db.close()


def test_incremental_run_falls_back_to_full_without_base() -> None:
    """增量分析：没有 base run 时自动降级为全量分析。"""
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("No Base Book")
            ch_id = db.create_chapter(book_id, "Chapter 1")
            db.update_chapter(ch_id, outline="", content="A lone wanderer appears.")

            pipeline = AnalysisPipelineV3(db)
            result = pipeline.start_incremental_run(book_id)
            assert result.status == "probes_ready"
            # 没有 base run 时，incremental 不在 meta 中（因为走了 start_run）
            assert result.block_count >= 1
        finally:
            db.close()


def test_incremental_run_no_changes_returns_base() -> None:
    """增量分析：章节无变化时返回 base run 结果。"""
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("No Change Book")
            db.create_character(book_id, "Bob")
            ch_id = db.create_chapter(book_id, "Chapter 1")
            db.update_chapter(ch_id, outline="", content="Bob stands guard.")

            pipeline = AnalysisPipelineV3(db)
            first = pipeline.start_run(book_id)

            # 不修改任何章节，再次增量分析
            inc = pipeline.start_incremental_run(book_id)
            assert inc.meta.get("incremental") is True
            assert inc.meta.get("chapters_changed") == 0
            # 应返回 base run 的 ID（无变化不创建新 run）
            assert inc.run_id == first.run_id
        finally:
            db.close()


def test_incremental_run_uses_chapter_hash_for_scene_split_no_changes() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Scene Split Incremental Book")
            db.create_character(book_id, "Alice")
            ch_id = db.create_chapter(book_id, "Chapter 1")
            content = "Alice opens the gate.\n\n***\n\nAlice finds the second sign."
            db.update_chapter(ch_id, outline="", content=content)

            pipeline = AnalysisPipelineV3(db, chunker=SemanticChunker(target_chars=20, max_chars=48))
            first = pipeline.start_run(book_id)
            blocks = db.list_analysis_blocks(book_id, run_id=first.run_id)
            assert len(blocks) >= 2
            metadata = [json.loads(str(row["metadata_json"] or "{}")) for row in blocks]
            assert all(item.get("chapter_content_hash") for item in metadata)

            inc = pipeline.start_incremental_run(book_id)
            assert inc.meta.get("incremental") is True
            assert inc.meta.get("chapters_changed") == 0
            assert inc.run_id == first.run_id
        finally:
            db.close()


def test_v3_merge_rule_and_ai_mentions_preserves_rule_only_characters() -> None:
    """V3 M2 合并策略：规则发现的 character 候选不应被 AI 结果覆盖丢失。

    场景：AI 抽取了"枫鱼"的 mention，规则引擎通过对话模式额外发现了"叶芷"和"张三"。
    合并后应包含全部三个人物，且同位置取 confidence 更高者。
    """
    from novel_app.analysis.pipeline_v3_stages import PipelineV3StagesMixin
    from novel_app.analysis.schemas_v3 import EntityMentionCandidate

    def make_mention(name: str, block_uid: str, char_start: int, confidence: float, source_rule: str) -> EntityMentionCandidate:
        return EntityMentionCandidate.create(
            book_id=1, run_id=1, entity_type="character", normalized_text=name,
            quote_text=name, chapter_id=1, block_uid=block_uid,
            char_start=char_start, char_end=char_start + len(name),
            confidence=confidence, source_rule=source_rule, metadata={},
        )

    # AI 结果：只有枫鱼
    ai_mentions = [
        make_mention("枫鱼", "block-001", 0, 0.85, "ai_extract"),
    ]
    # 规则结果：枫鱼（同位置）+ 叶芷 + 张三（AI 漏抽）
    rule_mentions = [
        make_mention("枫鱼", "block-001", 0, 0.65, "dialogue_pattern"),
        make_mention("叶芷", "block-001", 20, 0.65, "dialogue_pattern"),
        make_mention("张三", "block-001", 40, 0.6, "action_pattern"),
    ]

    merged = PipelineV3StagesMixin._merge_rule_and_ai_mentions(rule_mentions, ai_mentions)

    names = {m.normalized_text for m in merged}
    assert "枫鱼" in names
    assert "叶芷" in names  # 规则独有，不应丢失
    assert "张三" in names  # 规则独有，不应丢失
    # 同位置取 confidence 更高者（AI 0.85 > 规则 0.65）
    feng_yu = next(m for m in merged if m.normalized_text == "枫鱼")
    assert feng_yu.confidence == 0.85
    assert feng_yu.source_rule == "ai_extract"
    # 规则独有候选保留原 confidence
    ye_zhi = next(m for m in merged if m.normalized_text == "叶芷")
    assert ye_zhi.confidence == 0.65
    assert ye_zhi.source_rule == "dialogue_pattern"


def test_v3_m2_rule_first_extracts_dialogue_characters_without_seeds() -> None:
    """V3 M2 规则先行：无种子时也应通过对话模式识别 character 并写入 mention 表。"""
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("V3 Rule-First Book")
            chapter_id = db.create_chapter(book_id, "第一章")
            content = "枫鱼道：出发。叶芷笑道：好的。张三冷声道：哼。"
            db.update_chapter(chapter_id, outline="", content=content)

            pipeline = AnalysisPipelineV3(db, chunker=SemanticChunker(target_chars=100, max_chars=200))
            result = pipeline.start_run(book_id)
            mentions = db.list_analysis_entity_mentions(book_id, run_id=result.run_id)

            quote_texts = {m["quote_text"] for m in mentions}
            # 对话模式识别的 character 都应进入 mention 表
            assert "枫鱼" in quote_texts
            assert "叶芷" in quote_texts
            assert "张三" in quote_texts

            # 验证有 dialogue_pattern 来源的 character mention
            character_mentions = [m for m in mentions if m["entity_type"] == "character"]
            dialogue_mentions = [m for m in character_mentions if m["source_rule"] == "dialogue_pattern"]
            assert len(dialogue_mentions) >= 2  # 至少叶芷和张三通过对话模式识别
        finally:
            db.close()
