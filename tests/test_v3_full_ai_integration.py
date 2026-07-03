"""V3 分析链路全环节 AI 接入测试 — Task 7。

覆盖以下环节的 AI 模式、回退与规则回归：
1. AIAnalysisProvider 新增 5 方法（generate_card_content/score_memory_importance/
   compress_memory/generate_probe_questions/semantic_chunk）
2. M5 卡片生成 AI 模式（card_generators_v3.py）
3. M7 记忆分层 AI 模式（memory_classifier.py + memory_compressor.py）
4. M8 探针规划 AI 模式（probe_planner.py）
5. M1 语义分块 AI 模式（semantic_chunker.py）
6. use_ai=False 时的回归测试
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from novel_app.analysis.ai_provider import AIAnalysisProvider
from novel_app.analysis.card_generators_v3 import build_v3_book_card, build_v3_entity_card
from novel_app.analysis.llm_cache import LLMCache
from novel_app.analysis.memory_classifier import MemoryClassifier
from novel_app.analysis.memory_compressor import MemoryCompressor
from novel_app.analysis.probe_planner import ProbePlanner
from novel_app.analysis.semantic_chunker import SemanticChunker
from novel_app.database import Database


# ---------------------------------------------------------------------------
# Database 辅助方法（与 test_ai_provider.py / test_v3_writeback.py 一致）
# LLMCache 依赖 Database.query_one 与 Database.execute，但 Database 类
# 通过 self.connection 访问，这里补齐这些辅助方法。
# ---------------------------------------------------------------------------
def _query_one(self, sql: str, params: tuple = ()):
    cursor = self.connection.execute(sql, params)
    return cursor.fetchone()


def _db_execute(self, sql: str, params: tuple = ()):
    return self.connection.execute(sql, params)


Database.query_one = _query_one
Database.execute = _db_execute


# ---------------------------------------------------------------------------
# Mock AI Service（用于 AIAnalysisProvider 测试）
# ---------------------------------------------------------------------------
class MockAIService:
    """模拟 AI 服务，根据用户/系统提示中的关键词返回预设 JSON 响应。"""

    def __init__(self, responses=None):
        self.responses = responses or {}

    def is_remote_configured(self):
        return True

    def _post_json_chat_completion(self, messages, temperature=None, extra_body=None, *, timeout=None):
        for key, response in self.responses.items():
            if any(key in str(msg.get("content", "")) for msg in messages):
                return {"choices": [{"message": {"content": json.dumps(response, ensure_ascii=False)}}]}
        return {"choices": [{"message": {"content": "{}"}}]}

    def _chat_completion_content(self, result, purpose=""):
        return result["choices"][0]["message"]["content"]

    def _loads_json_payload(self, text):
        return json.loads(text)


class FailingAIService:
    """模拟 AI 服务持续失败。"""

    def is_remote_configured(self):
        return True

    def _post_json_chat_completion(self, *args, **kwargs):
        raise RuntimeError("AI service unavailable")

    def _chat_completion_content(self, *args, **kwargs):
        raise RuntimeError("AI service unavailable")

    def _loads_json_payload(self, text):
        return json.loads(text)


# ---------------------------------------------------------------------------
# Fake AI Providers（用于 M5/M7/M8/M1 模块测试）
# 直接 mock 各模块调用的 ai_provider 方法，不依赖真实 LLM/Database。
# ---------------------------------------------------------------------------
class FakeCardAIProvider:
    """Mock AI provider for card generation."""

    def __init__(self, output=None, exc=None):
        self.output = output
        self.exc = exc
        self.calls = []

    def generate_card_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.output


class FakeMemoryScoreAIProvider:
    """Mock AI provider for memory importance scoring."""

    def __init__(self, output=None, exc=None):
        self.output = output
        self.exc = exc
        self.calls = []

    def score_memory_importance(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.output


class FakeMemoryCompressAIProvider:
    """Mock AI provider for memory compression."""

    def __init__(self, output=None, exc=None):
        self.output = output
        self.exc = exc
        self.calls = []

    def compress_memory(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.output


class FakeProbeAIProvider:
    """Mock AI provider for probe question generation."""

    def __init__(self, output=None, exc=None):
        self.output = output
        self.exc = exc
        self.calls = []

    def generate_probe_questions(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.output


class FakeChunkAIProvider:
    """Mock AI provider for semantic chunking."""

    def __init__(self, output=None, exc=None):
        self.output = output
        self.exc = exc
        self.calls = []

    def semantic_chunk(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.output


# ---------------------------------------------------------------------------
# 测试数据工厂
# ---------------------------------------------------------------------------
def _make_entity(entity_type="character", canonical_name="林一", entity_uid="ENT-P-001"):
    return {
        "entity_uid": entity_uid,
        "entity_type": entity_type,
        "canonical_name": canonical_name,
        "aliases": [],
        "metadata": {"role": "主角"},
    }


def _make_fact(
    fact_uid="FCT-001",
    fact_type="event",
    quote_text="林一进入青云宗",
    summary="林一进入青云宗",
    entity_uid="ENT-P-001",
    chapter_id=1,
):
    return {
        "fact_uid": fact_uid,
        "subject_entity_uid": entity_uid,
        "fact_type": fact_type,
        "quote_text": quote_text,
        "value": {"summary": summary, "subject_name": "林一"},
        "chapter_id": chapter_id,
        "block_uid": f"block-{chapter_id}",
        "confidence": 0.85,
        "status": "candidate",
        "metadata": {},
    }


def _make_classified_fact(
    fact_uid="FCT-001",
    fact_type="event",
    entity_uid="ENT-P-001",
    chapter_id=1,
    memory_type="cache",
    memory_scope="long_term",
):
    """构造已经过 MemoryClassifier 分类的事实，用于 MemoryCompressor 测试。

    可压缩事实需满足：memory_type=cache + memory_scope=long_term + 非 foreshadowing/world_rule/state。
    """
    return {
        "fact_uid": fact_uid,
        "subject_entity_uid": entity_uid,
        "fact_type": fact_type,
        "quote_text": f"事件 {fact_uid}。",
        "value": {"summary": f"事件 {fact_uid}", "subject_name": "林一"},
        "chapter_id": chapter_id,
        "block_uid": f"block-{chapter_id}",
        "confidence": 0.8,
        "status": "candidate",
        "memory_scope": memory_scope,
        "memory_importance": "normal",
        "memory_type": memory_type,
        "importance_score": 0.5,
        "is_foreshadowing": 0,
        "is_compressible": 1,
        "metadata": {},
    }


def _make_probe_fact(
    fact_uid="F-1",
    entity_uid="E-hero",
    fact_type="foreshadowing",
    chapter_id=1,
    quote_text="Lin Yi finds a hidden clue.",
    memory_type="evidence",
):
    return {
        "fact_uid": fact_uid,
        "subject_entity_uid": entity_uid,
        "fact_type": fact_type,
        "value": {"summary": quote_text, "subject_name": entity_uid},
        "quote_text": quote_text,
        "chapter_id": chapter_id,
        "block_uid": f"B-{chapter_id}",
        "confidence": 0.8,
        "memory_scope": "long_term",
        "memory_importance": "high",
        "memory_type": memory_type,
        "importance_score": 0.8,
        "status": "candidate",
        "metadata": {},
    }


@contextmanager
def _ai_provider(ai_service):
    """创建带临时数据库的 AIAnalysisProvider，测试结束自动清理。"""
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            yield AIAnalysisProvider(ai_service, LLMCache(db))
        finally:
            db.close()


# ===================================================================
# 1. AIAnalysisProvider 新方法测试
# ===================================================================

def test_generate_card_content_character():
    """AI 返回 character 卡内容，验证 title/profile_text/role 字段。"""
    ai_response = {
        "title": "林一·青云宗剑修",
        "profile_text": "林一是青云宗内门弟子，主修剑道。",
        "role": "主角",
        "summary": "青云宗剑修弟子，手持诛仙剑的主角。",
    }
    with _ai_provider(MockAIService(responses={"卡片内容": ai_response})) as provider:
        result = provider.generate_card_content(
            card_type="v3_character",
            entity=_make_entity(),
            facts=[_make_fact()],
            context="林一进入青云宗",
            book_id=1,
            run_id=1,
        )

    assert result is not None
    assert result["title"] == "林一·青云宗剑修"
    assert "林一" in result["profile_text"]
    assert result["role"] == "主角"
    assert "青云宗" in result["summary"]


def test_generate_card_content_world():
    """AI 返回 world 卡内容。"""
    ai_response = {
        "title": "青云宗·势力门派",
        "content_text": "青云宗是修仙界的顶级门派之一。",
        "category": "势力",
        "summary": "修仙界顶级门派之一。",
    }
    with _ai_provider(MockAIService(responses={"卡片内容": ai_response})) as provider:
        result = provider.generate_card_content(
            card_type="v3_world",
            entity=_make_entity(entity_type="organization", canonical_name="青云宗", entity_uid="ENT-O-001"),
            facts=[_make_fact(quote_text="青云宗是顶级门派", summary="青云宗是顶级门派")],
            context="青云宗是修仙界门派",
            book_id=1,
            run_id=1,
        )

    assert result is not None
    assert result["title"] == "青云宗·势力门派"
    assert "青云宗" in result["content_text"]
    assert result["category"] == "势力"


def test_generate_card_content_book():
    """AI 返回 book 卡内容。"""
    ai_response = {
        "title": "诛仙·仙侠长篇",
        "outline_text": "故事围绕青云宗弟子林一展开。",
        "world_text": "本作世界观以仙侠修真为底色。",
        "summary": "以林一为主角的仙侠修真长篇。",
    }
    with _ai_provider(MockAIService(responses={"卡片内容": ai_response})) as provider:
        result = provider.generate_card_content(
            card_type="v3_book_summary",
            entity={"entity_uid": "BOOK-1", "entity_type": "book", "canonical_name": "诛仙"},
            facts=[_make_fact()],
            context="林一进入青云宗",
            book_id=1,
            run_id=1,
        )

    assert result is not None
    assert result["title"] == "诛仙·仙侠长篇"
    assert "林一" in result["outline_text"]
    assert "仙侠" in result["world_text"]


def test_generate_card_content_failure():
    """AI 调用失败，返回 None。"""
    with _ai_provider(FailingAIService()) as provider:
        result = provider.generate_card_content(
            card_type="v3_character",
            entity=_make_entity(),
            facts=[_make_fact()],
            context="测试",
            book_id=1,
            run_id=1,
        )

    assert result is None
    assert len(provider.errors) > 0


def test_score_memory_importance_success():
    """AI 返回记忆评分列表。"""
    ai_response = {
        "scores": [
            {"fact_uid": "FCT-001", "memory_level": "hot", "importance_score": 0.85},
            {"fact_uid": "FCT-002", "memory_level": "warm", "importance_score": 0.55},
            {"fact_uid": "FCT-003", "memory_level": "cold", "importance_score": 0.25},
        ]
    }
    facts = [
        _make_fact(fact_uid="FCT-001", quote_text="林一拜师", summary="林一拜师"),
        _make_fact(fact_uid="FCT-002", quote_text="林一休息", summary="林一休息"),
        _make_fact(fact_uid="FCT-003", quote_text="林一吃饭", summary="林一吃饭"),
    ]
    with _ai_provider(MockAIService(responses={"记忆重要性评分": ai_response})) as provider:
        result = provider.score_memory_importance(facts=facts, context="测试", book_id=1, run_id=1)

    assert result is not None
    assert len(result) == 3
    by_uid = {item["fact_uid"]: item for item in result}
    assert by_uid["FCT-001"]["memory_level"] == "hot"
    assert by_uid["FCT-001"]["importance_score"] == 0.85
    assert by_uid["FCT-002"]["memory_level"] == "warm"
    assert by_uid["FCT-003"]["memory_level"] == "cold"


def test_score_memory_importance_failure():
    """AI 失败返回 None。"""
    with _ai_provider(FailingAIService()) as provider:
        result = provider.score_memory_importance(
            facts=[_make_fact()],
            context="测试",
            book_id=1,
            run_id=1,
        )

    assert result is None
    assert len(provider.errors) > 0


def test_compress_memory_success():
    """AI 返回压缩摘要。"""
    ai_response = {"summary": "林一在乌坦城成长，拜药尘为师学习炼药术。"}
    with _ai_provider(MockAIService(responses={"压缩为一段连贯的摘要文本": ai_response})) as provider:
        result = provider.compress_memory(
            facts=[_make_fact(fact_uid="FCT-a"), _make_fact(fact_uid="FCT-b")],
            target_ratio=0.3,
            book_id=1,
            run_id=1,
        )

    assert result is not None
    assert isinstance(result, str)
    assert "林一" in result
    assert "药尘" in result


def test_compress_memory_failure():
    """AI 失败返回 None。"""
    with _ai_provider(FailingAIService()) as provider:
        result = provider.compress_memory(
            facts=[_make_fact()],
            target_ratio=0.3,
            book_id=1,
            run_id=1,
        )

    assert result is None
    assert len(provider.errors) > 0


def test_generate_probe_questions_success():
    """AI 返回探针问题。"""
    ai_response = {
        "question": "林一是否最终学会炼药术？",
        "expected": "是，应回收药尘的师徒承诺。",
    }
    with _ai_provider(MockAIService(responses={"探针问题": ai_response})) as provider:
        result = provider.generate_probe_questions(
            probe_type="foreshadowing_recovery",
            facts=[_make_fact(fact_type="foreshadowing", quote_text="老夫教你炼药术")],
            context="药尘承诺教萧炎炼药术",
            book_id=1,
            run_id=1,
        )

    assert result is not None
    assert "炼药术" in result["question"]
    assert result["expected"]


def test_generate_probe_questions_failure():
    """AI 失败返回 None。"""
    with _ai_provider(FailingAIService()) as provider:
        result = provider.generate_probe_questions(
            probe_type="foreshadowing_recovery",
            facts=[_make_fact()],
            context="测试",
            book_id=1,
            run_id=1,
        )

    assert result is None
    assert len(provider.errors) > 0


def test_semantic_chunk_success():
    """AI 返回边界列表。"""
    text = "第一章。" + ("段落一。" * 200) + "第二章。" + ("段落二。" * 200)
    text_len = len(text)
    ai_response = {"boundaries": [0, text_len // 2, text_len]}
    with _ai_provider(MockAIService(responses={"语义连贯性调整边界": ai_response})) as provider:
        result = provider.semantic_chunk(
            text=text,
            candidate_boundaries=[0, text_len // 2 - 2, text_len],
            book_id=1,
            run_id=1,
        )

    assert result is not None
    assert isinstance(result, list)
    assert all(isinstance(b, int) for b in result)
    # 升序去重
    assert result == sorted(set(result))
    assert 0 in result
    assert text_len in result


def test_semantic_chunk_failure():
    """AI 失败返回 None。"""
    with _ai_provider(FailingAIService()) as provider:
        result = provider.semantic_chunk(
            text="这是一段测试文本。",
            candidate_boundaries=[0, 5],
            book_id=1,
            run_id=1,
        )

    assert result is None
    assert len(provider.errors) > 0


# ===================================================================
# 2. M5 卡片生成 AI 模式测试
# ===================================================================

def test_build_v3_entity_card_ai_character():
    """use_ai=True 时 character 卡用 AI 内容。"""
    ai_output = {
        "title": "林一·主角",
        "profile_text": "AI 生成的角色档案。",
        "role": "主角",
        "summary": "AI 生成的摘要。",
    }
    ai_provider = FakeCardAIProvider(output=ai_output)

    draft = build_v3_entity_card(
        book_id=1,
        run_id=1,
        entity=_make_entity(),
        facts=[_make_fact()],
        card_type="v3_character",
        dependency_hash="dep-hash-001",
        use_ai=True,
        ai_provider=ai_provider,
    )

    assert draft.payload["source_rule"] == "ai_llm_card"
    assert draft.payload["title"] == "林一·主角"
    assert draft.payload["writeback_fields"]["profile_text"] == "AI 生成的角色档案。"
    assert draft.payload["writeback_fields"]["role"] == "主角"
    assert draft.payload["summary"] == "AI 生成的摘要。"
    assert len(ai_provider.calls) == 1
    assert ai_provider.calls[0]["card_type"] == "v3_character"


def test_build_v3_entity_card_ai_world():
    """use_ai=True 时 world 卡用 AI 内容。"""
    ai_output = {
        "title": "青云宗·门派",
        "content_text": "AI 生成的世界设定。",
        "category": "势力",
        "summary": "AI 生成的世界摘要。",
    }
    ai_provider = FakeCardAIProvider(output=ai_output)
    entity = _make_entity(entity_type="organization", canonical_name="青云宗", entity_uid="ENT-O-001")

    draft = build_v3_entity_card(
        book_id=1,
        run_id=1,
        entity=entity,
        facts=[_make_fact()],
        card_type="v3_world",
        dependency_hash="dep-hash-002",
        use_ai=True,
        ai_provider=ai_provider,
    )

    assert draft.payload["source_rule"] == "ai_llm_card"
    assert draft.payload["title"] == "青云宗·门派"
    assert draft.payload["writeback_fields"]["content_text"] == "AI 生成的世界设定。"
    assert draft.payload["writeback_fields"]["category"] == "势力"


def test_build_v3_entity_card_ai_fallback():
    """AI 失败时回退到规则。"""
    ai_provider = FakeCardAIProvider(exc=RuntimeError("AI unavailable"))

    draft = build_v3_entity_card(
        book_id=1,
        run_id=1,
        entity=_make_entity(),
        facts=[_make_fact()],
        card_type="v3_character",
        dependency_hash="dep-hash-003",
        use_ai=True,
        ai_provider=ai_provider,
    )

    # AI 失败时回退到 rule_v1
    assert draft.payload["source_rule"] == "rule_v1"
    # 标题应为规则模式的默认值
    assert "候选卡" in draft.payload["title"]


def test_build_v3_entity_card_rule_mode():
    """use_ai=False 时保持规则模式。"""
    ai_provider = FakeCardAIProvider(output={"title": "不应被使用"})

    draft = build_v3_entity_card(
        book_id=1,
        run_id=1,
        entity=_make_entity(),
        facts=[_make_fact()],
        card_type="v3_character",
        dependency_hash="dep-hash-004",
        use_ai=False,
        ai_provider=ai_provider,
    )

    # use_ai=False 时 source_rule 不在 payload 中
    assert "source_rule" not in draft.payload
    # AI provider 不应被调用
    assert len(ai_provider.calls) == 0
    # 标题应为规则模式的默认值
    assert "候选卡" in draft.payload["title"]


def test_build_v3_book_card_ai():
    """use_ai=True 时 book 卡用 AI 内容。"""
    ai_output = {
        "title": "AI 书籍标题",
        "outline_text": "AI 生成的大纲。",
        "world_text": "AI 生成的世界观。",
        "summary": "AI 生成的书籍摘要。",
    }
    ai_provider = FakeCardAIProvider(output=ai_output)

    draft = build_v3_book_card(
        book_id=1,
        run_id=1,
        facts=[_make_fact()],
        dependency_hash="dep-hash-005",
        use_ai=True,
        ai_provider=ai_provider,
    )

    assert draft.payload["source_rule"] == "ai_llm_card"
    assert draft.payload["title"] == "AI 书籍标题"
    assert draft.payload["writeback_fields"]["outline_text"] == "AI 生成的大纲。"
    assert draft.payload["writeback_fields"]["world_text"] == "AI 生成的世界观。"
    assert draft.payload["summary"] == "AI 生成的书籍摘要。"


def test_build_v3_book_card_ai_fallback():
    """AI 失败时回退。"""
    ai_provider = FakeCardAIProvider(exc=RuntimeError("AI unavailable"))

    draft = build_v3_book_card(
        book_id=1,
        run_id=1,
        facts=[_make_fact()],
        dependency_hash="dep-hash-006",
        use_ai=True,
        ai_provider=ai_provider,
    )

    assert draft.payload["source_rule"] == "rule_v1"
    assert "候选卡" in draft.payload["title"]


def test_build_v3_book_card_rule_mode():
    """use_ai=False 时保持规则模式。"""
    ai_provider = FakeCardAIProvider(output={"title": "不应被使用"})

    draft = build_v3_book_card(
        book_id=1,
        run_id=1,
        facts=[_make_fact()],
        dependency_hash="dep-hash-007",
        use_ai=False,
        ai_provider=ai_provider,
    )

    assert "source_rule" not in draft.payload
    assert len(ai_provider.calls) == 0
    assert "候选卡" in draft.payload["title"]


# ===================================================================
# 3. M7 记忆分层 AI 模式测试
# ===================================================================

def test_memory_classifier_ai_mode():
    """use_ai=True 时用 AI 评分。"""
    ai_scores = [
        {"fact_uid": "FCT-001", "memory_level": "hot", "importance_score": 0.9},
        {"fact_uid": "FCT-002", "memory_level": "cold", "importance_score": 0.2},
    ]
    ai_provider = FakeMemoryScoreAIProvider(output=ai_scores)

    classifier = MemoryClassifier(short_term_chapter_window=2, use_ai=True, ai_provider=ai_provider)
    facts = [
        _make_fact(fact_uid="FCT-001", fact_type="event", chapter_id=1),
        _make_fact(fact_uid="FCT-002", fact_type="event", chapter_id=2),
    ]
    result = classifier.classify_facts(facts)

    assert classifier._last_engine == "ai"
    assert len(ai_provider.calls) == 1
    by_uid = {f["fact_uid"]: f for f in result}
    # hot → high
    assert by_uid["FCT-001"]["memory_importance"] == "high"
    assert by_uid["FCT-001"]["importance_score"] == 0.9
    # cold → low
    assert by_uid["FCT-002"]["memory_importance"] == "low"
    assert by_uid["FCT-002"]["importance_score"] == 0.2


def test_memory_classifier_ai_fallback():
    """AI 失败时回退到 ARS。"""
    ai_provider = FakeMemoryScoreAIProvider(exc=RuntimeError("AI unavailable"))

    classifier = MemoryClassifier(short_term_chapter_window=2, use_ai=True, ai_provider=ai_provider)
    facts = [_make_fact(fact_uid="FCT-001", fact_type="event", chapter_id=1)]
    result = classifier.classify_facts(facts)

    assert classifier._last_engine == "rule"
    assert len(result) == 1
    # 仍然有 memory_importance 字段（来自 ARS）
    assert "memory_importance" in result[0]
    assert "importance_score" in result[0]


def test_memory_classifier_rule_mode():
    """use_ai=False 时保持 ARS。"""
    ai_provider = FakeMemoryScoreAIProvider(
        output=[{"fact_uid": "FCT-001", "memory_level": "hot", "importance_score": 0.99}]
    )

    classifier = MemoryClassifier(short_term_chapter_window=2, use_ai=False, ai_provider=ai_provider)
    facts = [_make_fact(fact_uid="FCT-001", fact_type="event", chapter_id=1)]
    result = classifier.classify_facts(facts)

    assert classifier._last_engine == "rule"
    # AI provider 不应被调用
    assert len(ai_provider.calls) == 0
    # importance_score 应来自 ARS，不是 AI 的 0.99
    assert result[0]["importance_score"] != 0.99


def test_memory_compressor_ai_mode():
    """use_ai=True 时用 AI 压缩。"""
    ai_summary = "AI 生成的压缩摘要。"
    ai_provider = FakeMemoryCompressAIProvider(output=ai_summary)

    compressor = MemoryCompressor(cache_threshold=3, use_ai=True, ai_provider=ai_provider)
    # 构造 4 个可压缩事实（同 entity_uid + fact_type=event + memory_type=cache + long_term）
    facts = [
        _make_classified_fact(fact_uid=f"FCT-{i}", fact_type="event", entity_uid="ENT-P-001", chapter_id=i)
        for i in range(1, 5)
    ]
    result = compressor.compress(facts)

    summaries = [f for f in result if f["fact_type"] == "memory_summary"]
    assert len(summaries) == 1
    assert summaries[0]["quote_text"] == "AI 生成的压缩摘要。"
    assert summaries[0]["metadata"]["compress_engine"] == "ai"
    assert compressor._last_engine == "ai"
    assert len(ai_provider.calls) == 1


def test_memory_compressor_ai_fallback():
    """AI 失败时回退到规则。"""
    ai_provider = FakeMemoryCompressAIProvider(exc=RuntimeError("AI unavailable"))

    compressor = MemoryCompressor(cache_threshold=3, use_ai=True, ai_provider=ai_provider)
    facts = [
        _make_classified_fact(fact_uid=f"FCT-{i}", fact_type="event", entity_uid="ENT-P-001", chapter_id=i)
        for i in range(1, 5)
    ]
    result = compressor.compress(facts)

    summaries = [f for f in result if f["fact_type"] == "memory_summary"]
    assert len(summaries) == 1
    # 规则模式生成的摘要包含 "cached" 关键词
    assert "cached" in summaries[0]["quote_text"]
    assert summaries[0]["metadata"]["compress_engine"] == "rule"
    assert compressor._last_engine == "rule"


def test_memory_compressor_rule_mode():
    """use_ai=False 时保持规则。"""
    ai_provider = FakeMemoryCompressAIProvider(output="不应被使用")

    compressor = MemoryCompressor(cache_threshold=3, use_ai=False, ai_provider=ai_provider)
    facts = [
        _make_classified_fact(fact_uid=f"FCT-{i}", fact_type="event", entity_uid="ENT-P-001", chapter_id=i)
        for i in range(1, 5)
    ]
    result = compressor.compress(facts)

    summaries = [f for f in result if f["fact_type"] == "memory_summary"]
    assert len(summaries) == 1
    assert "cached" in summaries[0]["quote_text"]
    assert summaries[0]["metadata"]["compress_engine"] == "rule"
    assert compressor._last_engine == "rule"
    assert len(ai_provider.calls) == 0


# ===================================================================
# 4. M8 探针规划 AI 模式测试
# ===================================================================

def _make_probe_test_facts():
    """构造覆盖四种探针类型的测试事实。"""
    return [
        _make_probe_fact(fact_uid="F-foreshadow", fact_type="foreshadowing", chapter_id=1,
                         quote_text="Lin Yi finds a hidden clue."),
        _make_probe_fact(fact_uid="F-state", fact_type="state", chapter_id=1,
                         quote_text="Lin Yi is alive."),
        _make_probe_fact(fact_uid="F-rule", fact_type="world_rule", chapter_id=2,
                         quote_text="The gate cannot open without blood.", memory_type="foundation"),
        _make_probe_fact(fact_uid="F-relation", fact_type="relation", chapter_id=2,
                         quote_text="Lin Yi helps Mei."),
    ]


def _make_probe_test_entities():
    return [
        {"entity_uid": "E-hero", "canonical_name": "Lin Yi", "entity_type": "character"},
        {"entity_uid": "E-world", "canonical_name": "Gate Rule", "entity_type": "concept"},
    ]


def test_probe_planner_ai_mode():
    """use_ai=True 时用 AI 生成问题。"""
    ai_output = {
        "question": "AI 生成的探针问题？",
        "expected": "AI 生成的预期答案。",
    }
    ai_provider = FakeProbeAIProvider(output=ai_output)

    planner = ProbePlanner(use_ai=True, ai_provider=ai_provider)
    plans = planner.plan(
        book_id=1,
        run_id=1,
        facts=_make_probe_test_facts(),
        entities=_make_probe_test_entities(),
    )

    assert planner._last_engine == "ai"
    assert len(plans) > 0
    # 至少有一个 plan 使用了 AI 生成的问题
    ai_plans = [p for p in plans if p["plan"]["metadata"]["planner"] == "ai_llm"]
    assert len(ai_plans) > 0
    for plan in ai_plans:
        assert plan["plan"]["question"] == "AI 生成的探针问题？"
        assert plan["plan"]["expected"] == "AI 生成的预期答案。"
    assert len(ai_provider.calls) > 0


def test_probe_planner_ai_fallback():
    """AI 失败时回退到硬编码模板。"""
    ai_provider = FakeProbeAIProvider(exc=RuntimeError("AI unavailable"))

    planner = ProbePlanner(use_ai=True, ai_provider=ai_provider)
    plans = planner.plan(
        book_id=1,
        run_id=1,
        facts=_make_probe_test_facts(),
        entities=_make_probe_test_entities(),
    )

    assert planner._last_engine == "rule_fallback"
    assert len(plans) > 0
    # 所有 plan 都应使用规则模板
    for plan in plans:
        assert plan["plan"]["metadata"]["planner"] == "rules_v1"


def test_probe_planner_rule_mode():
    """use_ai=False 时保持硬编码模板。"""
    ai_provider = FakeProbeAIProvider(
        output={"question": "不应被使用", "expected": "不应被使用"}
    )

    planner = ProbePlanner(use_ai=False, ai_provider=ai_provider)
    plans = planner.plan(
        book_id=1,
        run_id=1,
        facts=_make_probe_test_facts(),
        entities=_make_probe_test_entities(),
    )

    assert planner._last_engine == "rule"
    assert len(plans) > 0
    for plan in plans:
        assert plan["plan"]["metadata"]["planner"] == "rules_v1"
    assert len(ai_provider.calls) == 0


# ===================================================================
# 5. M1 语义分块 AI 模式测试
# ===================================================================

def _make_chunker_chapters():
    """构造足够长的章节内容，确保规则分块会产生多个块。"""
    para1 = "段落一内容。" * 200  # ~1200 字
    para2 = "段落二内容。" * 200  # ~1200 字
    para3 = "段落三内容。" * 200  # ~1200 字
    content = f"{para1}\n\n{para2}\n\n{para3}"
    return [{"id": 1, "title": "第一章", "content": content, "outline": ""}]


def test_semantic_chunker_ai_mode():
    """use_ai=True 时 AI 辅助边界。"""
    chapters = _make_chunker_chapters()
    # 先跑规则分块获取候选边界
    rule_chunker = SemanticChunker(target_chars=1000, max_chars=2000)
    rule_blocks = rule_chunker.chunk_chapters(1, chapters, pipeline_version="test")
    assert len(rule_blocks) >= 2, "规则分块应产生多个块"

    rule_boundaries = sorted({b.char_start for b in rule_blocks} | {rule_blocks[-1].char_end})

    # AI 返回调整后的边界（与规则相同，验证 AI 被调用即可）
    ai_provider = FakeChunkAIProvider(output=rule_boundaries)

    chunker = SemanticChunker(target_chars=1000, max_chars=2000, use_ai=True, ai_provider=ai_provider)
    blocks = chunker.chunk_chapters(1, chapters, pipeline_version="test")

    assert chunker._last_engine == "ai_assisted"
    assert len(blocks) > 0
    assert len(ai_provider.calls) == 1
    # AI 调用时传入的文本应为章节内容
    assert ai_provider.calls[0]["text"] == chapters[0]["content"]
    # candidate_boundaries 应包含 0
    assert 0 in ai_provider.calls[0]["candidate_boundaries"]


def test_semantic_chunker_ai_fallback():
    """AI 失败时回退到规则。"""
    ai_provider = FakeChunkAIProvider(exc=RuntimeError("AI unavailable"))

    chunker = SemanticChunker(target_chars=1000, max_chars=2000, use_ai=True, ai_provider=ai_provider)
    blocks = chunker.chunk_chapters(1, _make_chunker_chapters(), pipeline_version="test")

    assert chunker._last_engine == "rule"
    assert len(blocks) > 0
    # 即使 AI 失败，仍应有分块结果


def test_semantic_chunker_rule_mode():
    """use_ai=False 时保持规则。"""
    ai_provider = FakeChunkAIProvider(output=[0, 100, 200])

    chunker = SemanticChunker(target_chars=1000, max_chars=2000, use_ai=False, ai_provider=ai_provider)
    blocks = chunker.chunk_chapters(1, _make_chunker_chapters(), pipeline_version="test")

    assert chunker._last_engine == "rule"
    assert len(blocks) > 0
    assert len(ai_provider.calls) == 0


# ===================================================================
# 6. use_ai=False 回归测试
# ===================================================================

def test_regression_card_generation_no_ai_when_disabled():
    """use_ai=False 时卡片生成不调用 AI。"""
    ai_provider = FakeCardAIProvider(output={"title": "不应被使用"})

    entity_draft = build_v3_entity_card(
        book_id=1, run_id=1, entity=_make_entity(), facts=[_make_fact()],
        card_type="v3_character", dependency_hash="h1", use_ai=False, ai_provider=ai_provider,
    )
    book_draft = build_v3_book_card(
        book_id=1, run_id=1, facts=[_make_fact()],
        dependency_hash="h2", use_ai=False, ai_provider=ai_provider,
    )

    assert len(ai_provider.calls) == 0
    assert "source_rule" not in entity_draft.payload
    assert "source_rule" not in book_draft.payload


def test_regression_memory_classifier_no_ai_when_disabled():
    """use_ai=False 时记忆分类器不调用 AI。"""
    ai_provider = FakeMemoryScoreAIProvider(
        output=[{"fact_uid": "FCT-1", "memory_level": "hot", "importance_score": 0.99}]
    )

    classifier = MemoryClassifier(short_term_chapter_window=2, use_ai=False, ai_provider=ai_provider)
    result = classifier.classify_facts([_make_fact(fact_uid="FCT-1", chapter_id=1)])

    assert len(ai_provider.calls) == 0
    assert classifier._last_engine == "rule"
    # 确保未被 AI 的 0.99 覆盖
    assert result[0]["importance_score"] != 0.99


def test_regression_memory_compressor_no_ai_when_disabled():
    """use_ai=False 时记忆压缩器不调用 AI。"""
    ai_provider = FakeMemoryCompressAIProvider(output="不应被使用")

    compressor = MemoryCompressor(cache_threshold=3, use_ai=False, ai_provider=ai_provider)
    facts = [
        _make_classified_fact(fact_uid=f"FCT-{i}", fact_type="event", entity_uid="ENT-1", chapter_id=i)
        for i in range(1, 5)
    ]
    result = compressor.compress(facts)

    assert len(ai_provider.calls) == 0
    assert compressor._last_engine == "rule"
    summaries = [f for f in result if f["fact_type"] == "memory_summary"]
    assert len(summaries) == 1
    assert summaries[0]["metadata"]["compress_engine"] == "rule"


def test_regression_probe_planner_no_ai_when_disabled():
    """use_ai=False 时探针规划不调用 AI。"""
    ai_provider = FakeProbeAIProvider(
        output={"question": "不应被使用", "expected": "不应被使用"}
    )

    planner = ProbePlanner(use_ai=False, ai_provider=ai_provider)
    facts = [
        _make_probe_fact(fact_uid="F-1", fact_type="foreshadowing", chapter_id=1,
                         quote_text="clue found"),
    ]
    entities = [{"entity_uid": "E-1", "canonical_name": "X", "entity_type": "character"}]

    plans = planner.plan(book_id=1, run_id=1, facts=facts, entities=entities)

    assert len(ai_provider.calls) == 0
    assert planner._last_engine == "rule"
    for plan in plans:
        assert plan["plan"]["metadata"]["planner"] == "rules_v1"


def test_regression_semantic_chunker_no_ai_when_disabled():
    """use_ai=False 时语义分块不调用 AI。"""
    ai_provider = FakeChunkAIProvider(output=[0, 100])

    chunker = SemanticChunker(target_chars=1000, max_chars=2000, use_ai=False, ai_provider=ai_provider)
    chapters = [{
        "id": 1, "title": "第一章",
        "content": "段落一。" * 200 + "\n\n" + "段落二。" * 200,
        "outline": "",
    }]
    blocks = chunker.chunk_chapters(1, chapters, pipeline_version="test")

    assert len(ai_provider.calls) == 0
    assert chunker._last_engine == "rule"
    assert len(blocks) > 0
