from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from novel_app.analysis.mention_extractor import MentionExtractor, MentionSeed
from novel_app.database import Database


def test_mention_extractor_uses_formal_seeds_quotes_suffixes_and_stable_uids() -> None:
    content = "林一进入青云宗。他举起《玄铁剑法》，随后获得玄铁剑。"
    block = {
        "block_uid": "analysis-v3-chapter-1-part-0001",
        "chapter_id": 1,
        "char_start": 0,
        "char_end": len(content),
        "text": content,
    }
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Mention Book")
            db.create_character(book_id, "林一")
            db.create_world_entry(book_id, "青云宗", "宗门")

            extractor = MentionExtractor.from_database(db, book_id)
            first = extractor.extract_from_blocks(book_id=book_id, run_id=12, blocks=[block])
            second = extractor.extract_from_blocks(book_id=book_id, run_id=12, blocks=[block])

            assert [item.mention_uid for item in first] == [item.mention_uid for item in second]
            by_quote = {item.quote_text: item for item in first}
            assert by_quote["林一"].source_rule == "formal_character"
            assert by_quote["林一"].entity_type == "character"
            assert by_quote["青云宗"].source_rule == "formal_world_entry"
            assert by_quote["青云宗"].entity_type == "organization"
            assert by_quote["玄铁剑法"].source_rule == "quoted_title"
            assert by_quote["玄铁剑"].source_rule == "suffix_pattern"
            assert by_quote["玄铁剑"].entity_type == "item"
            for mention in first:
                assert content[mention.char_start:mention.char_end] == mention.quote_text
                assert mention.confidence >= 0.55
        finally:
            db.close()


def test_mention_extractor_filters_low_confidence_seeds() -> None:
    content = "低置信实体在这里出现。"
    extractor = MentionExtractor(
        [
            MentionSeed(
                text="低置信实体",
                entity_type="concept",
                source_rule="low_confidence_test",
                confidence=0.5,
                metadata={},
            )
        ]
    )

    mentions = extractor.extract_from_blocks(
        book_id=1,
        run_id=1,
        blocks=[
            {
                "block_uid": "b1",
                "chapter_id": 1,
                "char_start": 0,
                "char_end": len(content),
                "text": content,
            }
        ],
    )

    assert mentions == []


def test_dialogue_pattern_recognizes_characters_without_seeds() -> None:
    """对话模式应不依赖种子识别人物名字，如"枫鱼道："、"叶芷笑道："。"""
    content = "枫鱼道：今日天气不错。叶芷笑道：是啊。张三冷声道：未必。"
    block = {
        "block_uid": "dlg-001",
        "chapter_id": 1,
        "char_start": 0,
        "char_end": len(content),
        "text": content,
    }
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Dialogue Book")
            # 不创建任何 character 种子，验证纯对话模式识别
            extractor = MentionExtractor.from_database(db, book_id)
            mentions = extractor.extract_from_blocks(book_id=book_id, run_id=1, blocks=[block])
            by_quote = {item.quote_text: item for item in mentions}
            # 三个对话动词模式都应识别出 character
            assert "枫鱼" in by_quote
            assert by_quote["枫鱼"].entity_type == "character"
            assert by_quote["枫鱼"].source_rule == "dialogue_pattern"
            assert "叶芷" in by_quote
            assert by_quote["叶芷"].entity_type == "character"
            assert "张三" in by_quote
            assert by_quote["张三"].entity_type == "character"
            # 置信度应为 0.65
            assert by_quote["枫鱼"].confidence == 0.65
            for mention in mentions:
                assert content[mention.char_start:mention.char_end] == mention.quote_text
        finally:
            db.close()


def test_action_pattern_recognizes_characters_without_seeds() -> None:
    """动作模式应不依赖种子识别人物名字，如"枫鱼看着"、"叶芷转身"。"""
    content = "枫鱼看着远方的山峦。叶芷转身离开。张三走向门口。"
    block = {
        "block_uid": "act-001",
        "chapter_id": 1,
        "char_start": 0,
        "char_end": len(content),
        "text": content,
    }
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Action Book")
            extractor = MentionExtractor.from_database(db, book_id)
            mentions = extractor.extract_from_blocks(book_id=book_id, run_id=1, blocks=[block])
            by_quote = {item.quote_text: item for item in mentions}
            assert "枫鱼" in by_quote
            assert by_quote["枫鱼"].source_rule == "action_pattern"
            assert by_quote["枫鱼"].entity_type == "character"
            assert "叶芷" in by_quote
            assert "张三" in by_quote
            # 动作模式置信度 0.6
            assert by_quote["枫鱼"].confidence == 0.6
        finally:
            db.close()


def test_dialogue_pattern_filters_negative_prefixes() -> None:
    """泛称如少年/少女/众人/老者后跟对话动词时不应被识别为人名。"""
    content = "少年道：在下来了。少女笑道：好的。众人道：遵命。老者叹道：罢了。"
    block = {
        "block_uid": "neg-001",
        "chapter_id": 1,
        "char_start": 0,
        "char_end": len(content),
        "text": content,
    }
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Negative Book")
            extractor = MentionExtractor.from_database(db, book_id)
            mentions = extractor.extract_from_blocks(book_id=book_id, run_id=1, blocks=[block])
            by_quote = {item.quote_text: item for item in mentions}
            # 泛称不应出现在结果中
            assert "少年" not in by_quote
            assert "少女" not in by_quote
            assert "众人" not in by_quote
            assert "老者" not in by_quote
        finally:
            db.close()


def test_dialogue_pattern_with_existing_seeds_does_not_duplicate() -> None:
    """种子人物和对话模式同时命中同一名字时不应产生重复 mention。"""
    content = "枫鱼道：出发。"
    block = {
        "block_uid": "dedup-001",
        "chapter_id": 1,
        "char_start": 0,
        "char_end": len(content),
        "text": content,
    }
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("Dedup Book")
            db.create_character(book_id, "枫鱼")  # 种子人物
            extractor = MentionExtractor.from_database(db, book_id)
            mentions = extractor.extract_from_blocks(book_id=book_id, run_id=1, blocks=[block])
            # 种子(formal_character, conf=0.95) 应优先于对话模式(conf=0.65)
            by_rule = {item.source_rule: item for item in mentions}
            assert "formal_character" in by_rule
            # 同一位置同一名字只保留 confidence 最高的
            feng_mentions = [m for m in mentions if m.quote_text == "枫鱼"]
            assert len(feng_mentions) == 1
            assert feng_mentions[0].source_rule == "formal_character"
        finally:
            db.close()
