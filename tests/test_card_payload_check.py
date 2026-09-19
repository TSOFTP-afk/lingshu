"""检查 V3 卡片生成的 payload 内容是否正确。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3
from novel_app.database import Database

# 使用上次测试相同的《斗破苍穹》内容
CHAPTER_1_TITLE = "第一章 陨落的天才"
CHAPTER_1_CONTENT = """
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
"""

CHAPTER_2_TITLE = "第二章 斗气大陆"
CHAPTER_2_CONTENT = """
翌日清晨，萧炎从修炼中醒来，按照药尘的指导，他昨晚尝试了一套新的修炼功法——焚决。

演武场上，萧宁站在场中央，朗声道："萧炎表弟，要不要来切磋一下？"

萧炎平静看着萧宁："你想打，我便陪你。"

萧宁一拳袭来，萧炎脚步轻移险险避开，一掌正中萧宁胸口。

"这……这怎么可能？"围观的族人一片哗然。

远处阁楼上，萧家族长萧战负手而立，眼中闪过一丝欣慰。

"斗气大陆，强者为尊。乌坦城只是一个小小的起点..."
"""

CHAPTER_3_TITLE = "第三章 炼药初试"
CHAPTER_3_CONTENT = """
萧炎盘坐房间中，面前摆放着紫兰草、凝血花、骨灵果等药材。

"炼药师的基础，便是从这些低级药材开始。"萧炎平静道。

药尘赞许："现在，尝试炼制一枚凝血散。"

萧炎掌心凝聚出淡黄色斗气火焰，小心翼翼投入紫兰草。

半个时辰后，一枚淡红色丹药静静躺在掌心。

"成功了！"

"凝血散，一品丹药，可加速伤口愈合。在乌坦城这种小地方，算是稀罕物了。"

萧炎眼中闪过一抹坚定："总有一天，我会炼制出九品丹药，成为这大陆上最强的炼药师！"
"""


def main():
    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()
            book_id = db.create_book("斗破苍穹")

            # 添加章节
            for title, content in [
                (CHAPTER_1_TITLE, CHAPTER_1_CONTENT),
                (CHAPTER_2_TITLE, CHAPTER_2_CONTENT),
                (CHAPTER_3_TITLE, CHAPTER_3_CONTENT),
            ]:
                ch_id = db.create_chapter(book_id, title)
                db.update_chapter(ch_id, outline="", content=content)

            # 添加人物卡种子
            for name in ["萧炎", "萧薰儿", "萧媚", "药尘", "萧战", "萧宁"]:
                db.create_character(book_id, name)

            # 运行全链路分析
            pipeline = AnalysisPipelineV3(db)
            result = pipeline.start_run(book_id)
            print(f"分析完成: {result.status}")
            print(f"  Blocks={result.block_count} Mentions={result.mention_count} "
                  f"Entities={result.entity_count} Facts={result.fact_count} Cards={result.card_count}\n")

            # ================================================================
            # 直接查询数据库获取卡片 payload
            # ================================================================
            cards = db.connection.execute(
                """
                SELECT card_uid, card_type, entity_uid, status, ars_score,
                       payload_json, diff_json
                FROM analysis_cards
                WHERE run_id = ?
                ORDER BY
                    CASE card_type
                        WHEN 'v3_character' THEN 1
                        WHEN 'v3_book_summary' THEN 2
                        WHEN 'v3_world' THEN 3
                        ELSE 9
                    END
                """,
                (result.run_id,),
            ).fetchall()

            # 同时查实体信息
            entities = {
                e["entity_uid"]: dict(e)
                for e in db.list_analysis_entities(book_id, run_id=result.run_id)
            }

            print("=" * 80)
            print("人物卡 (v3_character)")
            print("=" * 80)
            char_cards = [row for row in cards if row["card_type"] == "v3_character"]
            for row in char_cards:
                _print_card(row, entities)

            print("\n" + "=" * 80)
            print("书籍卡 (v3_book_summary)")
            print("=" * 80)
            book_cards = [row for row in cards if row["card_type"] == "v3_book_summary"]
            for row in book_cards:
                _print_card(row, entities)

            print("\n" + "=" * 80)
            print("世界卡 (v3_world) — 仅展示前 5 张")
            print("=" * 80)
            world_cards = [row for row in cards if row["card_type"] == "v3_world"]
            for row in world_cards[:5]:
                _print_card(row, entities)
            if len(world_cards) > 5:
                print(f"\n... 还有 {len(world_cards) - 5} 张 v3_world 卡未展示")

            # 汇总统计
            print("\n" + "=" * 80)
            print("卡片质量汇总")
            print("=" * 80)
            for card_type, type_name in [
                ("v3_character", "人物卡"), ("v3_book_summary", "书籍卡"), ("v3_world", "世界卡")
            ]:
                type_cards = [row for row in cards if row["card_type"] == card_type]
                has_payload = sum(1 for c in type_cards if c["payload_json"] and str(c["payload_json"]).strip() not in ("", "{}"))
                has_facts = sum(1 for c in type_cards if _count_facts_in_card(c) > 0)
                has_writeback = sum(1 for c in type_cards if _parse_payload(c).get("writeback_target") not in (None, "", "none"))
                print(f"  {type_name} ({len(type_cards)} 张): "
                      f"有payload={has_payload}, 含facts={has_facts}, 可写回={has_writeback}")

        finally:
            db.close()


def _print_card(row, entities):
    entity_uid = row["entity_uid"]
    payload = _parse_payload(row)
    entity = entities.get(entity_uid, {})
    entity_name = entity.get("canonical_name", "?")
    entity_type = entity.get("entity_type", "?")

    facts_list = payload.get("facts", [])
    summary = payload.get("summary", "")
    wb_target = payload.get("writeback_target", "?")
    wb_fields = payload.get("writeback_fields", {})

    print(f"\n  卡片: {row['card_uid'][:24]}...")
    print(f"  关联实体: {entity_name} (类型={entity_type}, UID={entity_uid[:30]}...)")
    print(f"  卡片类型: {row['card_type']}")
    print(f"  状态: {row['status']} | ARS评分: {row['ars_score']}")
    print(f"  写回目标: {wb_target}")
    if wb_fields:
        for k, v in wb_fields.items():
            v_str = str(v)[:100]
            print(f"    writeback_fields.{k}: {v_str}")

    if summary:
        print(f"  摘要: {summary[:150]}")
    else:
        print("  ⚠ 摘要为空!")

    print(f"  关联事实数: {len(facts_list)}")

    # 展示前 3 条事实
    for i, fact in enumerate(facts_list[:3], 1):
        fact_type = fact.get("fact_type", "?")
        fact_text = str(fact.get("summary") or fact.get("quote_text", ""))[:100]
        print(f"    [{i}] [{fact_type}] {fact_text}")

    if len(facts_list) > 3:
        print(f"    ... 还有 {len(facts_list) - 3} 条事实")


def _parse_payload(row) -> dict:
    raw = row["payload_json"]
    if not raw:
        return {}
    try:
        return json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return {}


def _count_facts_in_card(row) -> int:
    payload = _parse_payload(row)
    facts = payload.get("facts", [])
    return len(facts) if isinstance(facts, list) else 0


if __name__ == "__main__":
    main()
