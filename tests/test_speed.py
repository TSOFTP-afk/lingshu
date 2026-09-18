"""快速测试：AI 增强分析 — 并发 20，窗口 6000 字。"""
from __future__ import annotations

import pytest

import contextlib, json, os, re, sys, time
from pathlib import Path

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


def main():
    print("《蛊真人》前30节 — AI增强 (并发20, 窗口6K)")
    print("=" * 60)

    # 读文件 & 分割
    t0 = time.time()
    with open(NOVEL_PATH, encoding="utf-8") as f:
        full_text = f.read()
    matches = list(SECTION_HEAD_RE.finditer(full_text))
    sections = []
    for i in range(min(MAX_CHAPTERS, len(matches))):
        title = matches[i].group(0).strip()
        start = matches[i].end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        content = full_text[start:end].strip()
        sections.append((title, content))
    total_chars = sum(len(c) for _, c in sections)
    print(f"  文件: {len(full_text):,}字 → 前{len(sections)}节 {total_chars:,}字 ({time.time()-t0:.1f}s)")

    # 写入 DB（用项目 data 目录，避免 TEMP 慢）
    t0 = time.time()
    db_path = Path(__file__).resolve().parents[1] / "data" / "test_gu.db"
    db = Database(db_path)
    db.initialize()
    book_id = db.create_book("蛊真人")
    for title, content in sections:
        cid = db.create_chapter(book_id, title)
        db.update_chapter(cid, outline="", content=content)
    print(f"  DB 写入: {time.time()-t0:.1f}s")

    # AI 分析
    ai_service = SimpleAIService(
        api_key=os.environ.get("LINGSHU_AI_API_KEY", "sk-test-placeholder"),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
    )
    llm_cache = LLMCache(db)
    ai_provider = AIAnalysisProvider(ai_service, llm_cache)

    print(f"  开始分析...")
    t0 = time.time()
    result = AnalysisPipelineV3(db, ai_provider=ai_provider).start_run(book_id, use_ai=True)
    elapsed = time.time() - t0

    # 结果
    cards = db.connection.execute(
        "SELECT card_type, COUNT(*) as cnt FROM analysis_cards WHERE run_id=? AND status!='superseded' GROUP BY card_type",
        (result.run_id,),
    ).fetchall()

    print(f"\n  耗时: {elapsed:.1f}s | 调用: {result.meta.get('ai_call_count','?')} 次")
    print(f"  Blocks={result.block_count} Mentions={result.mention_count} "
          f"Entities={result.entity_count} Facts={result.fact_count} Cards={result.card_count}")
    if result.meta.get("ai_stages"):
        print(f"  AI 阶段: {result.meta['ai_stages']}")
    if result.meta.get("ai_fallback_stages"):
        print(f"  降级: {result.meta['ai_fallback_stages']}")

    print(f"\n  卡片分布:")
    for row in cards:
        print(f"    {row['card_type']}: {row['cnt']} 张")

    # 人物卡 top 10
    top_chars = db.connection.execute(
        """SELECT json_extract(payload_json, '$.name') as name, json_extract(payload_json, '$.fact_count') as fc
           FROM analysis_cards WHERE run_id=? AND card_type='v3_character' AND status!='superseded'
           ORDER BY CAST(fc AS INTEGER) DESC LIMIT 10""",
        (result.run_id,),
    ).fetchall()
    print(f"\n  Top 10 人物卡:")
    for r in top_chars:
        print(f"    {r['name']:15s} {r['fc']} 条事实")

    db.close()
    with contextlib.suppress(Exception):
        os.unlink(str(db_path))
        os.unlink(str(db_path) + "-wal")
        os.unlink(str(db_path) + "-shm")


if __name__ == "__main__":
    main()
