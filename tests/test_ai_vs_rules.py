"""AI 增强 V3 分析管道测试 — 使用 DeepSeek LLM 进行实体/事实提取。

对比纯规则 vs AI 增强的卡片质量。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novel_app.ai.service import SimpleAIService
from novel_app.analysis.ai_provider import AIAnalysisProvider
from novel_app.analysis.llm_cache import LLMCache
from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3
from novel_app.database import Database

# ── DeepSeek 配置 ──
os.environ.setdefault("LINGSHU_AI_API_KEY", "sk-test-placeholder")
os.environ["LINGSHU_AI_BASE_URL"] = "https://api.deepseek.com/v1"
os.environ["LINGSHU_AI_MODEL"] = "deepseek-chat"

# ── 测试小说内容 ──
CHAPTERS = [
    ("第一章 陨落的天才", """
斗之力，三段！
望着测验魔石碑上面闪亮得甚至有些刺眼的五个大字，少年面无表情，唇角有着一抹自嘲...

"萧炎，斗之力，三段！级别：低级！"测验魔石碑之旁，一位中年男子，语气漠然公布。

"三段？嘿嘿，果然不出我所料，这个'天才'这一年又是在原地踏步！"

"哎，这废物真是把家族的脸都给丢光了。"

"要不是族长是他的父亲，这种废物，早就被驱赶出家族了..."

"下一个，萧媚！"

"萧媚，斗之气：七段！级别：高级！"

"啧啧，七段斗之气，真了不起..."

"下一个，萧薰儿！"

"斗之气：九段！级别：高级！"

"薰儿小姐，半年之后，你应该便能凝聚斗气之旋，十四岁成为斗者，你是萧家百年内的第二人！"

"萧炎哥哥。"萧薰儿对着萧炎恭敬弯了弯腰。

"我现在还有资格让你怎么叫么？"萧炎苦涩地道。

"萧炎哥哥，以前你曾经和薰儿说过，要能放下，才能拿起，提放自如，是自在人！"萧薰儿柔声道。

房间中，一个苍老的声音从戒指中响起："小家伙，想知道为什么你的斗之气消失吗？"

"你是谁？"

"老夫药尘，人称药尊者。这三年，你修炼出来的斗之气，全都被老夫给吸收了！"

"什么？！原来是你！"

"小子别急，从今天起，老夫教你炼药术，让你成为这斗气大陆上最强的炼药师！"

"好，我答应你。"
"""),
    ("第二章 斗气大陆", """
翌日清晨，萧炎从修炼中醒来，按照药尘的指导，他昨晚尝试了一套新的修炼功法——焚决。

演武场上，萧宁站在场中央，朗声道："萧炎表弟，要不要来切磋一下？"

萧炎平静看着萧宁："你想打，我便陪你。"

萧宁一拳袭来，萧炎脚步轻移险险避开，一掌正中萧宁胸口。

"这……这怎么可能？"围观的族人一片哗然。

远处阁楼上，萧家族长萧战负手而立，眼中闪过一丝欣慰。

"斗气大陆，强者为尊。乌坦城只是一个小小的起点..."
"""),
    ("第三章 炼药初试", """
萧炎盘坐房间中，面前摆放着紫兰草、凝血花、骨灵果等药材。

"炼药师的基础，便是从这些低级药材开始。"萧炎平静道。

药尘赞许："现在，尝试炼制一枚凝血散。"

萧炎掌心凝聚出淡黄色斗气火焰，小心翼翼投入紫兰草。

半个时辰后，一枚淡红色丹药静静躺在掌心。

"成功了！"

"凝血散，一品丹药，可加速伤口愈合。在乌坦城这种小地方，算是稀罕物了。"

萧炎眼中闪过一抹坚定："总有一天，我会炼制出九品丹药，成为这大陆上最强的炼药师！"
"""),
]


def _build_book(db: Database) -> int:
    book_id = db.create_book("斗破苍穹")
    for title, content in CHAPTERS:
        ch_id = db.create_chapter(book_id, title)
        db.update_chapter(ch_id, outline="", content=content)
    for name in ["萧炎", "萧薰儿", "萧媚", "药尘", "萧战", "萧宁"]:
        db.create_character(book_id, name)
    return book_id


def _print_entities(db, book_id, run_id, label):
    entities = db.connection.execute(
        """SELECT entity_uid, entity_type, canonical_name, confidence,
                  json_extract(metadata_json, '$.mention_count') as mention_count
           FROM analysis_entities WHERE book_id=? AND run_id=?
           ORDER BY entity_type, mention_count DESC""",
        (book_id, run_id),
    ).fetchall()
    print(f"\n  [{label}] 实体候选 ({len(entities)} 个):")
    for e in entities[:15]:
        mc = e["mention_count"] or "?"
        print(f"    [{e['entity_type'][:10]:10s}] {e['canonical_name'][:25]:25s} "
              f"提及{mc} 置信度{e['confidence']}")


def _print_cards(db, run_id, label):
    cards = db.connection.execute(
        "SELECT card_uid, card_type, entity_uid, status, payload_json FROM analysis_cards WHERE run_id=?",
        (run_id,),
    ).fetchall()

    char_cards = [c for c in cards if c["card_type"] == "v3_character"]
    book_cards = [c for c in cards if c["card_type"] == "v3_book_summary"]
    world_cards = [c for c in cards if c["card_type"] == "v3_world"]

    print(f"\n  [{label}] 卡片统计:")
    print(f"    人物卡: {len(char_cards)} 张")
    for c in char_cards:
        p = _parse_payload(c)
        fs = p.get("facts", [])
        name = p.get("name", "?")
        print(f"      - {name}: {len(fs)} 条事实, summary={str(p.get('summary',''))[:60]}")

    print(f"    书籍卡: {len(book_cards)} 张")
    for c in book_cards:
        p = _parse_payload(c)
        print(f"      - fact_count={p.get('fact_count',0)}, "
              f"outline={str(p.get('writeback_fields',{}).get('outline_text',''))[:50]}")

    print(f"    世界卡: {len(world_cards)} 张")
    # 显示前8张世界卡的可读名称
    for c in world_cards[:8]:
        p = _parse_payload(c)
        name = p.get("name", "?")
        wb = p.get("writeback_target", "?")
        fs = p.get("facts", [])
        print(f"      - [{wb}] {name[:30]}: {len(fs)} 条事实")

    # 质量问题统计
    noise_count = sum(1 for c in world_cards
                      if _parse_payload(c).get("writeback_target") in (None, "", "none"))
    print(f"    噪声世界卡(writeback_target=none): {noise_count}/{len(world_cards)}")


def _parse_payload(row) -> dict:
    raw = row["payload_json"]
    if not raw:
        return {}
    try:
        return json.loads(str(raw))
    except Exception:
        return {}


def main():
    print("=" * 80)
    print("灵枢 V3 — AI 增强分析 (DeepSeek) vs 规则引擎 对比测试")
    print("=" * 80)

    # ═══════════════════════════════════════════════════════════════════
    # Phase 1: 纯规则分析（基准）
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "─" * 80)
    print("Phase 1: 纯规则引擎分析 (Baseline)")
    print("─" * 80)

    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = _build_book(db)
            print(f"  创建书籍: id={book_id}, 3章, 6个人物种子")

            t0 = time.time()
            rule_result = AnalysisPipelineV3(db).start_run(book_id)
            t_rule = time.time() - t0
            print(f"  规则引擎耗时: {t_rule:.1f}s")
            print(f"  Blocks={rule_result.block_count} Mentions={rule_result.mention_count} "
                  f"Entities={rule_result.entity_count} Facts={rule_result.fact_count} "
                  f"Cards={rule_result.card_count}")

            _print_entities(db, book_id, rule_result.run_id, "规则引擎")
            _print_cards(db, rule_result.run_id, "规则引擎")

        finally:
            db.close()

    # ═══════════════════════════════════════════════════════════════════
    # Phase 2: AI 增强分析
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "─" * 80)
    print("Phase 2: AI 增强分析 (DeepSeek)")
    print("─" * 80)

    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = _build_book(db)
            print(f"  创建书籍: id={book_id}, 3章, 6个人物种子")

            # 创建 AI Provider
            ai_service = SimpleAIService(
                api_key=os.environ.get("LINGSHU_AI_API_KEY", "sk-test-placeholder"),
                base_url="https://api.deepseek.com/v1",
                model="deepseek-chat",
            )
            if not ai_service.is_remote_configured():
                print("  ❌ AI 服务未配置! 请检查 API Key/Base URL/Model")
                return

            print(f"  AI 模式: {ai_service.get_mode_label()}")
            llm_cache = LLMCache(db)
            ai_provider = AIAnalysisProvider(ai_service, llm_cache)

            t0 = time.time()
            ai_result = AnalysisPipelineV3(db, ai_provider=ai_provider).start_run(
                book_id, use_ai=True
            )
            t_ai = time.time() - t0
            print(f"  AI 增强耗时: {t_ai:.1f}s")
            print(f"  Blocks={ai_result.block_count} Mentions={ai_result.mention_count} "
                  f"Entities={ai_result.entity_count} Facts={ai_result.fact_count} "
                  f"Cards={ai_result.card_count}")

            if ai_result.meta.get("ai_stages"):
                print(f"  AI 成功阶段: {ai_result.meta['ai_stages']}")
            if ai_result.meta.get("ai_fallback_stages"):
                print(f"  AI 降级阶段: {ai_result.meta['ai_fallback_stages']}")
            if ai_result.meta.get("ai_cache_hits"):
                print(f"  AI 缓存命中: {ai_result.meta['ai_cache_hits']}")
            if ai_result.meta.get("ai_call_count"):
                print(f"  AI 调用次数: {ai_result.meta['ai_call_count']}")

            _print_entities(db, book_id, ai_result.run_id, "AI 增强")
            _print_cards(db, ai_result.run_id, "AI 增强")

        finally:
            db.close()

    # ═══════════════════════════════════════════════════════════════════
    # 总结对比
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("对比总结")
    print("=" * 80)
    print(f"  规则引擎: {rule_result.mention_count} mentions, {rule_result.entity_count} entities, "
          f"{rule_result.fact_count} facts, {rule_result.card_count} cards, "
          f"耗时 {t_rule:.1f}s")
    print(f"  AI 增强: {ai_result.mention_count} mentions, {ai_result.entity_count} entities, "
          f"{ai_result.fact_count} facts, {ai_result.card_count} cards, "
          f"耗时 {t_ai:.1f}s")


if __name__ == "__main__":
    main()
