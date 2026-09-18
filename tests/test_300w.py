"""300万字长篇测试 — AI增强 (并发300, 窗口20K)。"""
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
TARGET_CHARS = 3_000_000
SECTION_HEAD_RE = re.compile(r"^第[一二三四五六七八九十百千\d]{1,4}[节章].*$", re.MULTILINE)


def main():
    print("=" * 60)
    print(f"《蛊真人》300万字测试 (并发300, 窗口20K)")
    print("=" * 60)

    t0 = time.time()
    with open(NOVEL_PATH, encoding="utf-8") as f:
        full_text = f.read()
    matches = list(SECTION_HEAD_RE.finditer(full_text))
    print(f"  文件: {len(full_text):,}字 | 共 {len(matches)} 节 ({time.time()-t0:.1f}s)")

    sections = []
    total = 0
    for i in range(len(matches)):
        title = matches[i].group(0).strip()
        start = matches[i].end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        content = full_text[start:end].strip()
        sections.append((title, content))
        total += len(content)
        if total >= TARGET_CHARS:
            break
    print(f"  截取: 前{len(sections)}节, {total:,}字 ({time.time()-t0:.1f}s)")

    t0 = time.time()
    db_path = Path(__file__).resolve().parents[1] / "data" / "test_300w.db"
    db = Database(db_path)
    db.initialize()
    book_id = db.create_book("蛊真人")
    for title, content in sections:
        cid = db.create_chapter(book_id, title)
        db.update_chapter(cid, outline="", content=content)
    print(f"  DB写入: {len(sections)}章, {time.time()-t0:.1f}s")

    ai_service = SimpleAIService(
        api_key=os.environ.get("LINGSHU_AI_API_KEY", "sk-test-placeholder"),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
    )
    llm_cache = LLMCache(db)
    ai_provider = AIAnalysisProvider(ai_service, llm_cache)

    print(f"  开始分析 ({len(sections)}章, {total:,}字)...")
    t0 = time.time()
    result = AnalysisPipelineV3(db, ai_provider=ai_provider).start_run(book_id, use_ai=True)
    elapsed = time.time() - t0

    cards = db.connection.execute(
        "SELECT card_type, COUNT(*) as cnt FROM analysis_cards WHERE run_id=? AND status!='superseded' GROUP BY card_type",
        (result.run_id,),
    ).fetchall()

    print(f"\n  ═══ 结果 ═══")
    print(f"  耗时: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print(f"  速度: {total/elapsed:,.0f} 字/秒")
    print(f"  API调用: {result.meta.get('ai_call_count','?')} 次")
    print(f"  Blocks={result.block_count}  Mentions={result.mention_count}  "
          f"Entities={result.entity_count}  Facts={result.fact_count}  Cards={result.card_count}")
    if result.meta.get("card_post_merges"):
        print(f"  后处理: 合并{result.meta['card_post_merges']} "
              f"删除{result.meta.get('card_post_deletes',0)}")

    print(f"\n  卡片分布:")
    for row in cards:
        print(f"    {row['card_type']}: {row['cnt']}")

    noise = db.connection.execute(
        """SELECT COUNT(*) as cnt FROM analysis_cards
           WHERE run_id=? AND card_type='v3_world' AND status!='superseded'
           AND (json_extract(payload_json, '$.writeback_target') IS NULL
                OR json_extract(payload_json, '$.writeback_target') = ''
                OR json_extract(payload_json, '$.writeback_target') = 'none')""",
        (result.run_id,),
    ).fetchone()
    world_count = next((r['cnt'] for r in cards if r['card_type'] == 'v3_world'), 0)
    if world_count:
        print(f"  世界卡噪声: {noise['cnt']}/{world_count} ({noise['cnt']/world_count*100:.0f}%)")

    top = db.connection.execute(
        """SELECT json_extract(payload_json, '$.name') as name, json_extract(payload_json, '$.fact_count') as fc
           FROM analysis_cards WHERE run_id=? AND card_type='v3_character' AND status!='superseded'
           ORDER BY CAST(fc AS INTEGER) DESC LIMIT 20""",
        (result.run_id,),
    ).fetchall()
    print(f"\n  Top 20 人物:")
    for r in top:
        print(f"    {r['name']:20s} {r['fc']} 条")

    db.close()
    with contextlib.suppress(Exception):
        os.unlink(str(db_path))
        os.unlink(str(db_path) + "-wal")
        os.unlink(str(db_path) + "-shm")


if __name__ == "__main__":
    main()
