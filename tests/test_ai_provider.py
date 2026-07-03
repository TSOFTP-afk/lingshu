from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from novel_app.analysis.ai_provider import AIAnalysisProvider, iter_ai_text_windows
from novel_app.analysis.llm_cache import LLMCache
from novel_app.analysis.schemas_v3 import AtomicFact, EntityMentionCandidate, ResolvedEntityCandidate
from novel_app.database import Database


# LLMCache 依赖 Database.query_one 和 Database.execute，但 Database 类
# 尚未直接定义这些方法（它通过 self.connection 访问），
# 在测试中为 Database 添加这些辅助方法。
def _query_one(self, sql: str, params: tuple = ()):
    cursor = self.connection.execute(sql, params)
    return cursor.fetchone()


def _db_execute(self, sql: str, params: tuple = ()):
    return self.connection.execute(sql, params)


Database.query_one = _query_one
Database.execute = _db_execute


class MockAIService:
    """模拟 AI 服务，返回预设的 JSON 响应。"""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self._call_log = []

    def is_remote_configured(self):
        return True

    def _post_json_chat_completion(self, messages, temperature=None, extra_body=None, *, timeout=None):
        # 根据 messages 内容返回不同的预设响应
        for key, response in self.responses.items():
            if any(key in str(msg.get("content", "")) for msg in messages):
                return {"choices": [{"message": {"content": json.dumps(response, ensure_ascii=False)}}]}
        return {"choices": [{"message": {"content": "{}"}}]}

    def _chat_completion_content(self, result, purpose=""):
        choices = result.get("choices", [])
        if not choices:
            raise RuntimeError("No choices in result")
        return choices[0]["message"]["content"]

    def _loads_json_payload(self, text):
        return json.loads(text)


class RawAIService:
    """Return raw model content strings in order."""

    def __init__(self, contents: list[str]):
        self.contents = list(contents)
        self.remote_call_count = 0

    def is_remote_configured(self):
        return True

    def _post_json_chat_completion(self, messages, temperature=None, extra_body=None, *, timeout=None):
        self.remote_call_count += 1
        index = min(self.remote_call_count - 1, len(self.contents) - 1)
        return {"choices": [{"message": {"content": self.contents[index]}}]}

    def _chat_completion_content(self, result, purpose=""):
        return result["choices"][0]["message"]["content"]

    def _loads_json_payload(self, text):
        return json.loads(text)


def test_ai_provider_extract_mentions_returns_candidates():
    """AI 提及抽取应返回 EntityMentionCandidate 列表。"""
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            ai_response = {
                "mentions": [
                    {"quote_text": "林一", "entity_type": "character", "confidence": 0.9},
                    {"quote_text": "青云宗", "entity_type": "organization", "confidence": 0.85},
                ]
            }
            ai_service = MockAIService(responses={"实体提及": ai_response})
            llm_cache = LLMCache(db)
            provider = AIAnalysisProvider(ai_service, llm_cache)

            blocks = [{
                "block_uid": "analysis-v3-chapter-1-part-0001",
                "chapter_id": 1,
                "char_start": 0,
                "char_end": 20,
                "text": "林一进入青云宗。",
            }]

            mentions = provider.extract_mentions(blocks, book_id=1, run_id=1)

            assert len(mentions) == 2
            assert all(isinstance(m, EntityMentionCandidate) for m in mentions)
            assert mentions[0].quote_text == "林一"
            assert mentions[0].entity_type == "character"
            assert mentions[0].source_rule == "ai_llm"
            assert mentions[1].quote_text == "青云宗"
            assert mentions[1].entity_type == "organization"
        finally:
            db.close()


def test_ai_provider_extract_mentions_skips_not_found_quotes():
    """AI 返回的 quote_text 在原文中找不到时应跳过。"""
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            ai_response = {
                "mentions": [
                    {"quote_text": "林一", "entity_type": "character", "confidence": 0.9},
                    {"quote_text": "不存在", "entity_type": "concept", "confidence": 0.8},
                ]
            }
            ai_service = MockAIService(responses={"实体提及": ai_response})
            llm_cache = LLMCache(db)
            provider = AIAnalysisProvider(ai_service, llm_cache)

            blocks = [{
                "block_uid": "analysis-v3-chapter-1-part-0001",
                "chapter_id": 1,
                "char_start": 0,
                "char_end": 5,
                "text": "林一进城。",
            }]

            mentions = provider.extract_mentions(blocks, book_id=1, run_id=1)

            # "不存在" 在 "林一进城。" 中找不到，应被跳过
            assert len(mentions) == 1
            assert mentions[0].quote_text == "林一"
        finally:
            db.close()


def test_ai_provider_extract_mentions_deduplicates_duplicate_quotes():
    """AI 返回重复实体时应去重，避免写入 mention 唯一键冲突。"""
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            ai_response = {
                "mentions": [
                    {"quote_text": "林一", "entity_type": "character", "confidence": 0.7},
                    {"quote_text": "林一", "entity_type": "character", "confidence": 0.9},
                ]
            }
            ai_service = MockAIService(responses={"实体提及": ai_response})
            llm_cache = LLMCache(db)
            provider = AIAnalysisProvider(ai_service, llm_cache)

            blocks = [{
                "block_uid": "analysis-v3-chapter-1-part-0001",
                "chapter_id": 1,
                "char_start": 0,
                "char_end": 5,
                "text": "林一进城。",
            }]

            mentions = provider.extract_mentions(blocks, book_id=1, run_id=1)

            assert len(mentions) == 1
            assert mentions[0].quote_text == "林一"
            assert mentions[0].confidence == 0.9
        finally:
            db.close()


def test_ai_provider_resolve_coreference_returns_entities():
    """AI 共指消解应返回 ResolvedEntityCandidate 列表。"""
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            ai_response = {
                "entities": [
                    {
                        "canonical_name": "林一",
                        "entity_type": "character",
                        "aliases": ["林师兄"],
                        "mention_uids": ["MEN-aaa", "MEN-bbb"],
                        "confidence": 0.9,
                    }
                ]
            }
            ai_service = MockAIService(responses={"共指消解": ai_response})
            llm_cache = LLMCache(db)
            provider = AIAnalysisProvider(ai_service, llm_cache)

            mentions = [
                {"mention_uid": "MEN-aaa", "entity_type": "character", "quote_text": "林一", "normalized_text": "林一", "chapter_id": 1, "block_uid": "b1"},
                {"mention_uid": "MEN-bbb", "entity_type": "character", "quote_text": "林师兄", "normalized_text": "林师兄", "chapter_id": 2, "block_uid": "b2"},
            ]

            entities = provider.resolve_coreference(mentions, book_id=1, run_id=1)

            assert len(entities) == 1
            assert isinstance(entities[0], ResolvedEntityCandidate)
            assert entities[0].canonical_name == "林一"
            assert "林师兄" in entities[0].aliases
            assert entities[0].source_rule == "ai_llm_coreference"
        finally:
            db.close()


def test_ai_provider_extract_facts_returns_facts():
    """AI 事实抽取应返回 AtomicFact 列表。"""
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            ai_response = {
                "facts": [
                    {
                        "subject_entity_uid": "ENT-test",
                        "fact_type": "event",
                        "quote_text": "林一进入青云宗",
                        "block_uid": "analysis-v3-chapter-1-part-0001",
                        "value": {"summary": "林一进入青云宗"},
                        "confidence": 0.85,
                    }
                ]
            }
            ai_service = MockAIService(responses={"原子事实": ai_response})
            llm_cache = LLMCache(db)
            provider = AIAnalysisProvider(ai_service, llm_cache)

            blocks = [{
                "block_uid": "analysis-v3-chapter-1-part-0001",
                "chapter_id": 1,
                "char_start": 0,
                "char_end": 7,
                "text": "林一进入青云宗。",
            }]
            entities = [
                {"entity_uid": "ENT-test", "entity_type": "character", "canonical_name": "林一"},
            ]

            facts = provider.extract_facts(blocks, entities, book_id=1, run_id=1)

            assert len(facts) == 1
            assert isinstance(facts[0], AtomicFact)
            assert facts[0].subject_entity_uid == "ENT-test"
            assert facts[0].fact_type == "event"
            assert facts[0].metadata.get("source_rule") == "ai_llm_fact"
        finally:
            db.close()


def test_ai_provider_returns_empty_on_failure():
    """AI 调用失败时应返回空列表。"""
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()

            class FailingAIService:
                def is_remote_configured(self):
                    return True
                def _post_json_chat_completion(self, *args, **kwargs):
                    raise RuntimeError("API error")
                def _chat_completion_content(self, *args, **kwargs):
                    raise RuntimeError("API error")
                def _loads_json_payload(self, text):
                    return json.loads(text)

            llm_cache = LLMCache(db)
            provider = AIAnalysisProvider(FailingAIService(), llm_cache)

            blocks = [{
                "block_uid": "b1",
                "chapter_id": 1,
                "char_start": 0,
                "char_end": 5,
                "text": "测试文本。",
            }]

            mentions = provider.extract_mentions(blocks, book_id=1, run_id=1)
            assert mentions == []
            assert len(provider.errors) > 0
        finally:
            db.close()


def test_ai_provider_repairs_trailing_comma_json():
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            raw = 'prefix {"mentions":[{"quote_text":"Lin Yi","entity_type":"character","confidence":0.9,},],} suffix'
            provider = AIAnalysisProvider(RawAIService([raw]), LLMCache(db))
            blocks = [{
                "block_uid": "b1",
                "chapter_id": 1,
                "char_start": 10,
                "char_end": 30,
                "text": "Lin Yi enters town.",
            }]

            mentions = provider.extract_mentions(blocks, book_id=1, run_id=1)

            assert len(mentions) == 1
            assert mentions[0].quote_text == "Lin Yi"
            assert mentions[0].char_start == 10
            assert provider.repaired_json_count == 1
            assert provider.errors == []
        finally:
            db.close()


def test_ai_provider_retries_then_succeeds_without_recording_error():
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            service = RawAIService([
                "not json",
                '{"mentions":[{"quote_text":"Lin Yi","entity_type":"character","confidence":0.8}]}',
            ])
            provider = AIAnalysisProvider(service, LLMCache(db))
            blocks = [{
                "block_uid": "b1",
                "chapter_id": 1,
                "char_start": 0,
                "char_end": 20,
                "text": "Lin Yi enters town.",
            }]

            mentions = provider.extract_mentions(blocks, book_id=1, run_id=1)

            assert len(mentions) == 1
            assert service.remote_call_count == 2
            assert provider.retry_count == 1
            assert provider.errors == []
        finally:
            db.close()


def test_ai_provider_records_structured_error_for_timeout():
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()

            class TimeoutAIService:
                def is_remote_configured(self):
                    return True
                def _post_json_chat_completion(self, *args, **kwargs):
                    raise TimeoutError("request timed out")
                def _chat_completion_content(self, result, purpose=""):
                    return ""
                def _loads_json_payload(self, text):
                    return json.loads(text)

            provider = AIAnalysisProvider(TimeoutAIService(), LLMCache(db))
            blocks = [{
                "block_uid": "b-timeout",
                "chapter_id": 1,
                "char_start": 0,
                "char_end": 20,
                "text": "Lin Yi enters town.",
            }]

            mentions = provider.extract_mentions(blocks, book_id=1, run_id=1)

            assert mentions == []
            assert provider.retry_count == 1
            assert provider.errors
            assert provider.errors[0]["stage"] == "ai_mention"
            assert provider.errors[0]["block_uid_or_batch"] == "b-timeout"
            assert provider.errors[0]["error_type"] == "timeout"
            assert provider.errors[0]["attempt"] == 2
        finally:
            db.close()


def test_ai_provider_splits_long_block_and_restores_coordinates():
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()

            class WindowAIService:
                def __init__(self):
                    self.remote_call_count = 0
                def is_remote_configured(self):
                    return True
                def _post_json_chat_completion(self, messages, temperature=None, extra_body=None):
                    self.remote_call_count += 1
                    prompt = "\n".join(str(msg.get("content", "")) for msg in messages)
                    if "window_index: 0" in prompt:
                        payload = {"mentions": [{"quote_text": "Lin Yi", "entity_type": "character", "confidence": 0.9}]}
                    else:
                        payload = {"mentions": [{"quote_text": "Azure Sect", "entity_type": "organization", "confidence": 0.85}]}
                    return {"choices": [{"message": {"content": json.dumps(payload)}}]}
                def _chat_completion_content(self, result, purpose=""):
                    return result["choices"][0]["message"]["content"]
                def _loads_json_payload(self, text):
                    return json.loads(text)

            text = "Lin Yi" + ("x" * 2100) + "Azure Sect opened the gate."
            provider = AIAnalysisProvider(WindowAIService(), LLMCache(db))
            blocks = [{
                "block_uid": "b-long",
                "chapter_id": 1,
                "char_start": 100,
                "char_end": 100 + len(text),
                "text": text,
            }]

            windows = iter_ai_text_windows(text)
            covered = sum(window.end - window.start for window in windows) - sum(
                max(0, windows[index - 1].end - window.start)
                for index, window in enumerate(windows)
                if index > 0
            )
            mentions = provider.extract_mentions(blocks, book_id=1, run_id=1)

            assert covered / len(text) >= 0.95
            assert len(windows) >= 2
            assert len(mentions) == 2
            azure = [mention for mention in mentions if mention.quote_text == "Azure Sect"][0]
            assert azure.char_start == 100 + text.index("Azure Sect")
            assert azure.metadata["ai_window_index"] > 0
            assert provider.call_count >= 2
        finally:
            db.close()


def test_ai_provider_extract_facts_uses_windows_and_restores_coordinates():
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()

            class WindowFactAIService:
                def __init__(self):
                    self.remote_call_count = 0
                def is_remote_configured(self):
                    return True
                def _post_json_chat_completion(self, messages, temperature=None, extra_body=None):
                    self.remote_call_count += 1
                    prompt = "\n".join(str(msg.get("content", "")) for msg in messages)
                    if "Azure Sect" in prompt:
                        payload = {
                            "facts": [{
                                "subject_entity_uid": "ENT-azure",
                                "fact_type": "event",
                                "quote_text": "Azure Sect opened the gate",
                                "value": {"summary": "Azure Sect opened the gate"},
                                "confidence": 0.8,
                            }]
                        }
                    else:
                        payload = {"facts": []}
                    return {"choices": [{"message": {"content": json.dumps(payload)}}]}
                def _chat_completion_content(self, result, purpose=""):
                    return result["choices"][0]["message"]["content"]
                def _loads_json_payload(self, text):
                    return json.loads(text)

            text = "Lin Yi" + ("x" * 2100) + "Azure Sect opened the gate."
            provider = AIAnalysisProvider(WindowFactAIService(), LLMCache(db))
            blocks = [{
                "block_uid": "b-long-fact",
                "chapter_id": 1,
                "char_start": 200,
                "char_end": 200 + len(text),
                "text": text,
            }]
            entities = [{"entity_uid": "ENT-azure", "entity_type": "organization", "canonical_name": "Azure Sect"}]

            facts = provider.extract_facts(blocks, entities, book_id=1, run_id=1)

            assert len(facts) == 1
            assert facts[0].metadata["char_start"] == 200 + text.index("Azure Sect opened the gate")
            assert facts[0].metadata["ai_window_index"] > 0
            assert provider.call_count >= 1
        finally:
            db.close()


def test_ai_provider_cache_hit_skips_remote_call():
    """缓存命中时应跳过远程调用。"""
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()

            call_count = 0

            class CountingAIService:
                def is_remote_configured(self):
                    return True
                def _post_json_chat_completion(self, *args, **kwargs):
                    nonlocal call_count
                    call_count += 1
                    return {"choices": [{"message": {"content": json.dumps({"mentions": []})}}]}
                def _chat_completion_content(self, result, purpose=""):
                    return result["choices"][0]["message"]["content"]
                def _loads_json_payload(self, text):
                    return json.loads(text)

            llm_cache = LLMCache(db)
            ai_service = CountingAIService()
            provider = AIAnalysisProvider(ai_service, llm_cache)

            blocks = [{
                "block_uid": "b1",
                "chapter_id": 1,
                "char_start": 0,
                "char_end": 5,
                "text": "测试。",
            }]

            # 第一次调用：远程
            provider.extract_mentions(blocks, book_id=1, run_id=1)
            first_call_count = call_count

            # 第二次调用：应命中缓存
            provider2 = AIAnalysisProvider(ai_service, llm_cache)
            provider2.extract_mentions(blocks, book_id=1, run_id=1)

            assert provider2.cache_hits > 0
            assert call_count == first_call_count  # 没有新增远程调用
        finally:
            db.close()


def test_pipeline_v3_use_ai_false_behaves_same_as_before():
    """use_ai=False 时行为应与修改前完全一致。"""
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("V3 No AI Book")
            db.create_character(book_id, "Lin Yi")
            chapter_id = db.create_chapter(book_id, "One")
            content = "Lin Yi enters the city.\n\nHe marks a hidden clue."
            db.update_chapter(chapter_id, outline="", content=content)

            from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3
            from novel_app.analysis.semantic_chunker import SemanticChunker

            result = AnalysisPipelineV3(
                db,
                chunker=SemanticChunker(target_chars=20, max_chars=48)
            ).start_run(book_id, use_ai=False)

            assert result.status == "probes_ready"
            assert result.mention_count >= 1
            assert result.entity_count >= 1
            assert result.fact_count >= 1
            # meta 中 ai_invoked 应为 False
            run = db.get_analysis_run(result.run_id)
            meta = json.loads(str(run["meta_json"] or "{}"))
            assert not meta.get("ai_invoked")
        finally:
            db.close()


def test_pipeline_v3_use_ai_true_with_failing_provider_falls_back():
    """use_ai=True 但 AI provider 失败时应回退到规则模式。"""
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("V3 AI Fallback Book")
            db.create_character(book_id, "Lin Yi")
            chapter_id = db.create_chapter(book_id, "One")
            content = "Lin Yi enters the city.\n\nHe marks a hidden clue."
            db.update_chapter(chapter_id, outline="", content=content)

            from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3
            from novel_app.analysis.semantic_chunker import SemanticChunker

            class FailingAIService:
                def is_remote_configured(self):
                    return True
                def _post_json_chat_completion(self, *args, **kwargs):
                    raise RuntimeError("API unavailable")
                def _chat_completion_content(self, *args, **kwargs):
                    raise RuntimeError("API unavailable")
                def _loads_json_payload(self, text):
                    return json.loads(text)

            llm_cache = LLMCache(db)
            ai_provider = AIAnalysisProvider(FailingAIService(), llm_cache)

            result = AnalysisPipelineV3(
                db,
                chunker=SemanticChunker(target_chars=20, max_chars=48),
                ai_provider=ai_provider,
            ).start_run(book_id, use_ai=True)

            # 应回退到规则模式，结果与 use_ai=False 一致
            assert result.status == "probes_ready"
            assert result.mention_count >= 1
            assert result.entity_count >= 1
            assert result.fact_count >= 1
        finally:
            db.close()
