from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from novel_app.analysis.writeback_card_generator import (
    WritebackCardGenerationError,
    WritebackCardGenerator,
)
from novel_app.database import Database


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


def _make_db(tmp: str) -> Database:
    db = Database(Path(tmp) / "novels.db")
    db.initialize()
    return db


def _card(target: str, fields: dict, *, facts: list[dict] | None = None) -> dict:
    return {
        "card_uid": f"CARD-{target}",
        "card_type": f"v3_{target}",
        "entity_uid": "ENT-test",
        "payload": {
            "title": "测试卡",
            "name": fields.get("name", ""),
            "entity_type": "character" if target == "character" else "location",
            "summary": "自动摘要",
            "fact_count": len(facts or []),
            "facts": facts or [],
            "writeback_target": target,
            "writeback_fields": fields,
        },
    }


def test_writeback_card_generator_refines_character_and_locks_name() -> None:
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("生成器测试书")
            db.create_character(book_id, "林一")
            fake = FakeAIProvider({
                "name": "错误改名",
                "role": "主角",
                "profile_text": "林一是以冷静判断推进剧情的主角。",
            })
            generator = WritebackCardGenerator(fake)

            result = generator.generate(
                db,
                book_id,
                _card(
                    "character",
                    {"name": "林一", "role": "", "profile_text": "林一。主角。"},
                    facts=[{"fact_type": "event", "quote_text": "林一进入城市", "value": {"summary": "林一进入城市"}}],
                ),
            )

            assert result.fields == {
                "name": "林一",
                "role": "主角",
                "profile_text": "林一是以冷静判断推进剧情的主角。",
            }
            assert result.metadata["used"] is True
            assert fake.calls[0]["stage"] == "writeback_card_generator"
            assert fake.calls[0]["input_payload"]["existing_business_data"]["name"] == "林一"
        finally:
            db.close()


def test_writeback_card_generator_refines_world_entry() -> None:
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("生成器测试书")
            fake = FakeAIProvider({
                "name": "错误地点",
                "category": "location",
                "content_text": "青云宗位于东洲，是故事早期的重要宗门。",
            })
            result = WritebackCardGenerator(fake).generate(
                db,
                book_id,
                _card("world_entry", {"name": "青云宗", "category": "宗门", "content_text": "片段"}),
            )

            assert result.fields["name"] == "青云宗"
            assert result.fields["category"] == "location"
            assert "东洲" in result.fields["content_text"]
        finally:
            db.close()


def test_writeback_card_generator_refines_book() -> None:
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("生成器测试书")
            fake = FakeAIProvider({
                "outline_text": "第一幕：林一进入城市并发现伏笔。",
                "world_text": "世界以宗门和灵力规则为核心。",
            })
            result = WritebackCardGenerator(fake).generate(
                db,
                book_id,
                _card("book", {"outline_text": "林一进入城市", "world_text": ""}),
            )

            assert "第一幕" in result.fields["outline_text"]
            assert "灵力" in result.fields["world_text"]
        finally:
            db.close()


@pytest.mark.parametrize(
    "output",
    [
        [],
        {"name": "林一", "role": "主角"},
        {"writeback_fields": {"name": "林一", "role": "主角"}},
    ],
)
def test_writeback_card_generator_rejects_invalid_character_output(output) -> None:
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("生成器测试书")
            generator = WritebackCardGenerator(FakeAIProvider(output))

            with pytest.raises(WritebackCardGenerationError):
                generator.generate(
                    db,
                    book_id,
                    _card("character", {"name": "林一", "role": "", "profile_text": "原始"}),
                )
        finally:
            db.close()


def test_writeback_card_generator_propagates_ai_failure() -> None:
    with TemporaryDirectory() as tmp:
        db = _make_db(tmp)
        try:
            book_id = db.create_book("生成器测试书")
            generator = WritebackCardGenerator(FakeAIProvider(exc=RuntimeError("boom")))

            with pytest.raises(RuntimeError, match="boom"):
                generator.generate(
                    db,
                    book_id,
                    _card("character", {"name": "林一", "role": "", "profile_text": "原始"}),
                )
        finally:
            db.close()
