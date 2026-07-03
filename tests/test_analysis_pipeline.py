from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from novel_app.analysis.pipeline import PIPELINE_VERSION, AnalysisPipeline
from novel_app.database import Database


class FakeRetriever:
    def __init__(self) -> None:
        self.indexed: list[dict[str, Any]] = []

    def index_analysis_block(self, **kwargs: Any) -> None:
        self.indexed.append(kwargs)


class FailingRetriever:
    def index_analysis_block(self, **_kwargs: Any) -> None:
        raise RuntimeError("vector store unavailable")


def test_analysis_pipeline_creates_review_run_blocks_cards_and_rag_index() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Pipeline Book")
            chapter_id = db.create_chapter(book_id, "One")
            db.update_chapter(chapter_id, outline="", content="Lin folded the map into his sleeve.")
            retriever = FakeRetriever()
            payload = {
                "_requires_evidence": True,
                "character_cards": [
                    {
                        "name": "Lin",
                        "source_block_uid": f"analysis-chapter-{chapter_id}-part-001",
                        "source_quote": "folded the map",
                    }
                ],
            }

            result = AnalysisPipeline(db, rag_retriever=retriever).create_draft_run(
                book_id,
                payload,
                chapters=[dict(db.get_chapter(chapter_id))],
                meta={"source": "ws_analysis", "task_id": "task-1"},
            )
            run = db.get_analysis_run(result.run_id)
            cards = db.list_analysis_cards(result.run_id)
            blocks = db.list_analysis_blocks(book_id, run_id=result.run_id)
            meta = json.loads(str(run["meta_json"] or "{}"))

            assert result.status == "awaiting_review"
            assert run["pipeline_version"] == PIPELINE_VERSION
            assert result.block_count == 1
            assert result.indexed_block_count == 1
            assert len(retriever.indexed) == 1
            assert blocks[0]["indexed_at"]
            assert {card["card_type"] for card in cards} == {"full_payload", "characters"}
            assert float(next(card for card in cards if card["card_type"] == "characters")["ars_score"]) > 0.8
            assert meta["entity_count"] == 1
            assert meta["source_block_indexed_count"] == 1
            assert meta["source"] == "ws_analysis"
            assert meta["task_id"] == "task-1"
            assert result.meta["source"] == "ws_analysis"
        finally:
            db.close()


def test_analysis_pipeline_records_rag_index_errors_without_failing_draft_creation() -> None:
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Pipeline Error Book")
            chapter_id = db.create_chapter(book_id, "One")
            db.update_chapter(chapter_id, outline="", content="Lin folded the map into his sleeve.")
            payload = {
                "character_cards": [{"name": "Lin"}],
            }

            result = AnalysisPipeline(db, rag_retriever=FailingRetriever()).create_draft_run(
                book_id,
                payload,
                chapters=[dict(db.get_chapter(chapter_id))],
            )
            run = db.get_analysis_run(result.run_id)
            meta = json.loads(str(run["meta_json"] or "{}"))

            assert result.status == "awaiting_review"
            assert result.indexed_block_count == 0
            assert meta["rag_index_error_count"] == 1
            assert "vector store unavailable" in meta["rag_index_errors"][0]
        finally:
            db.close()


def test_v1_pipeline_augments_missing_characters_via_rule_extraction() -> None:
    """V1 pipeline 应通过规则兜底补抽 AI 漏掉的人物。

    场景：AI payload 只返回了"枫鱼"，但原文中"叶芷笑道："和"张三冷声道："
    也表明这两个人物出场。规则兜底应将叶芷和张三注入 payload 的 characters 列表，
    并附带证据原文使其能通过证据门禁。
    """
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Rule Augment Book")
            chapter_id = db.create_chapter(book_id, "第一章")
            content = "枫鱼道：今日天气不错。叶芷笑道：是啊。张三冷声道：未必。"
            db.update_chapter(chapter_id, outline="", content=content)
            # AI 只返回了枫鱼，漏掉了叶芷和张三
            payload = {
                "_requires_evidence": True,
                "characters": [
                    {
                        "name": "枫鱼",
                        "role": "protagonist",
                        "source_block_uid": f"analysis-chapter-{chapter_id}-part-001",
                        "evidence_quote": "枫鱼道：今日天气不错",
                        "profile_text": "主角枫鱼。",
                    }
                ],
            }

            result = AnalysisPipeline(db).create_draft_run(
                book_id,
                payload,
                chapters=[dict(db.get_chapter(chapter_id))],
            )

            # 验证 payload 被原地增强
            names_in_payload = [c["name"] for c in payload["characters"]]
            assert "枫鱼" in names_in_payload
            assert "叶芷" in names_in_payload  # 规则补抽
            assert "张三" in names_in_payload  # 规则补抽

            # 验证规则补抽的人物带证据
            ye_zhi = next(c for c in payload["characters"] if c["name"] == "叶芷")
            assert ye_zhi["source_block_uid"]
            assert "叶芷" in ye_zhi["evidence_quote"]
            assert ye_zhi["profile_text"]

            # 验证审计日志记录了增强
            logs = db.list_analysis_audit_logs(book_id, run_id=result.run_id)
            augment_logs = [log for log in logs if log["action"] == "rule_character_augmentation"]
            assert len(augment_logs) == 1
            import json as _json
            new_value = _json.loads(str(augment_logs[0]["new_value_json"] or "{}"))
            assert new_value["rule_added_character_count"] == 2
        finally:
            db.close()
