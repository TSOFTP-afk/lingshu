"""《蛊真人》前30节 V3 全链路测试。
"""
from __future__ import annotations

import pytest

import contextlib
import json
import os
import re
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3
from novel_app.analysis.ai_provider import AIAnalysisProvider
from novel_app.analysis.llm_cache import LLMCache
from novel_app.ai.service import SimpleAIService
from novel_app.database import Database

NOVEL_PATH = os.environ.get("LINGSHU_TEST_NOVEL_PATH", "")

pytestmark = [
    pytest.mark.performance,
    pytest.mark.skipif(not NOVEL_PATH, reason="未设置 LINGSHU_TEST_NOVEL_PATH"),
]


@pytest.fixture(autouse=True)
def _deepseek_ai_env(monkeypatch):
    """仅在测试运行时把 AI 环境变量指向 DeepSeek，收集阶段不污染进程环境。"""
    monkeypatch.setenv("LINGSHU_AI_API_KEY", os.environ.get("LINGSHU_AI_API_KEY", "sk-test-placeholder"))
    monkeypatch.setenv("LINGSHU_AI_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("LINGSHU_AI_MODEL", "deepseek-chat")
MAX_CHAPTERS = 30
SECTION_HEAD_RE = re.compile(r"^第[一二三四五六七八九十百千\d]{1,4}[节章].*$", re.MULTILINE)


def _split_sections(text: str, max_count: int) -> list[tuple[str, str]]:
    matches = list(SECTION_HEAD_RE.finditer(text))
    sections = []
    for i in range(min(len(matches), max_count)):
        title = matches[i].group(0).strip()
        start = matches[i].end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        sections.append((title, content))
    return sections


def _create_db(book_name, sections):
    """创建临时数据库并写入章节。"""
    db_path = Path(os.environ.get("TEMP", ".")) / f"lingshu_test_{int(time.time())}.db"
    db = Database(db_path)
    db.initialize()
    book_id = db.create_book(book_name)
    for title, content in sections:
        cid = db.create_chapter(book_id, title)
        db.update_chapter(cid, outline="", content=content)
    return db, book_id


def _cleanup_db(db):
    with contextlib.suppress(Exception):
        db.close()
    db_path = db.db_path
    with contextlib.suppress(Exception):
        os.unlink(db_path)
        os.unlink(db_path + "-wal")
        os.unlink(db_path + "-shm")


def _parse(row) -> dict:
    raw = row["payload_json"]
    if not raw:
        return {}
    try:
        return json.loads(str(raw))
    except Exception:
        return {}


def _print_cards(db, run_id, label):
    cards = db.connection.execute(
        "SELECT card_type, payload_json, entity_uid FROM analysis_cards WHERE run_id=? AND status!='superseded'",
        (run_id,),
    ).fetchall()
    char = [c for c in cards if c["card_type"] == "v3_character"]
    book = [c for c in cards if c["card_type"] == "v3_book_summary"]
    world = [c for c in cards if c["card_type"] == "v3_world"]

    print(f"\n  [{label}]")
    print(f"    人物卡: {len(char)}")
    for c in char[:15]:
        p = _parse(c)
        print(f"      {p.get('name','?'):15s} f={p.get('fact_count',0):3d}  {p.get('summary','')[:60]}")
    if len(char) > 15:
        print(f"      ... {len(char)-15} 张更多")

    print(f"    书籍卡: {len(book)}")
    for c in book:
        p = _parse(c)
        wb = p.get('writeback_fields', {})
        print(f"      f={p.get('fact_count',0)}, outline={wb.get('outline_text','')[:60]}")

    noise = sum(1 for c in world if _parse(c).get("writeback_target") in (None, "", "none"))
    print(f"    世界卡: {len(world)} (噪声: {noise})")
    for c in world[:10]:
        p = _parse(c)
        print(f"      [{p.get('writeback_target','?'):12s}] {p.get('name','?')[:30]:30s} f={p.get('fact_count',0)}")


def main():
    print("=" * 80)
    print("《蛊真人》前30节 V3 全链路测试")
    print("=" * 80)

    # ── Step 1: 读文件 & 分割 ──
    print("\nStep 1: 读文件 & 分割章节")
    t0 = time.time()
    with open(NOVEL_PATH, encoding="utf-8") as f:
        full_text = f.read()
    sections = _split_sections(full_text, MAX_CHAPTERS)
    total_chars = sum(len(c) for _, c in sections)
    print(f"  {len(full_text):,} chars -> {len(sections)} 节, {total_chars:,} 字 ({time.time()-t0:.1f}s)")
    for i, (title, content) in enumerate(sections[:3]):
        print(f"    [{i+1}] {title} ({len(content):,} chars)")

    # ── Step 2: 纯规则引擎 ──
    print("\nStep 2: 纯规则引擎")
    t0 = time.time()
    db_rule, bid = _create_db("蛊真人", sections)
    print(f"  DB: {time.time()-t0:.1f}s")
    t0 = time.time()
    rule_result = AnalysisPipelineV3(db_rule).start_run(bid)
    t_rule = time.time() - t0
    print(f"  分析: {t_rule:.1f}s, B={rule_result.block_count} M={rule_result.mention_count} "
          f"E={rule_result.entity_count} F={rule_result.fact_count} C={rule_result.card_count}")
    _print_cards(db_rule, rule_result.run_id, "纯规则")
    _cleanup_db(db_rule)

    # ── Step 3: AI 增强 ──
    print("\nStep 3: AI 增强 (DeepSeek)")
    t0 = time.time()
    db_ai, bid = _create_db("蛊真人", sections)
    print(f"  DB: {time.time()-t0:.1f}s")

    ai_service = SimpleAIService(
        api_key=os.environ.get("LINGSHU_AI_API_KEY", "sk-test-placeholder"),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
    )
    llm_cache = LLMCache(db_ai)
    ai_provider = AIAnalysisProvider(ai_service, llm_cache)

    print(f"  开始 AI 分析 (~89K字, 约3-8分钟)...")
    t0 = time.time()
    ai_result = AnalysisPipelineV3(db_ai, ai_provider=ai_provider).start_run(bid, use_ai=True)
    t_ai = time.time() - t0
    print(f"  分析: {t_ai:.1f}s, 调用 {ai_result.meta.get('ai_call_count','?')} 次")
    print(f"  B={ai_result.block_count} M={ai_result.mention_count} "
          f"E={ai_result.entity_count} F={ai_result.fact_count} C={ai_result.card_count}")
    if ai_result.meta.get("ai_stages"):
        print(f"  AI: {ai_result.meta['ai_stages']}")
    if ai_result.meta.get("ai_fallback_stages"):
        print(f"  Fallback: {ai_result.meta['ai_fallback_stages']}")
    _print_cards(db_ai, ai_result.run_id, "AI 增强")
    _cleanup_db(db_ai)

    # ── 对比 ──
    print("\n" + "=" * 80)
    print("对比总结")
    print("=" * 80)
    print(f"  《蛊真人》前{len(sections)}节, {total_chars:,} 字符")
    print(f"  规则: M={rule_result.mention_count} E={rule_result.entity_count} "
          f"F={rule_result.fact_count} C={rule_result.card_count}, {t_rule:.1f}s")
    print(f"  AI:   M={ai_result.mention_count} E={ai_result.entity_count} "
          f"F={ai_result.fact_count} C={ai_result.card_count}, {t_ai:.1f}s")


if __name__ == "__main__":
    main()
