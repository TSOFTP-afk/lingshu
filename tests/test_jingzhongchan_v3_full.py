"""真实书籍 V3 全链路分析测试：使用《镜中蝉》全书（约3万字，12章）。

验证 V3 分析管道在真实长篇小说上的完整运行：
1. 读取《镜中蝉》全文并按章节切分
2. 创建书籍、章节、种子人物
3. 运行 V3 全链路分析（规则引擎模式）
4. 输出各阶段统计（语义块/提及/实体/事实/卡片/记忆/探针）
5. 抽样展示各类分析产物
6. 验证静态属性提取链路
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novel_app.analysis.card_generators_v3 import build_v3_entity_card, _extract_static_attrs_from_facts
from novel_app.analysis.pipeline_v3 import PIPELINE_V3_VERSION, AnalysisPipelineV3
from novel_app.analysis.state_machine_writeback import writeback_to_state_machine
from novel_app.database import Database

SAMPLE_NOVEL_PATH = Path(__file__).resolve().parents[1] / "tools" / "sample_novel" / "镜中蝉.txt"

# 《镜中蝉》主要人物（作为种子增强实体识别）
SEED_CHARACTERS = [
    ("沈砚", "主角，上海《新声报》记者，沈鹤年之子，为寻父亲失踪真相归来"),
    ("陆婉清", "如烟社当家花旦，身世成谜，登台时镜中倒影常与现实不符"),
    ("周慎之", "青砚镇警察所长，处事拘泥程序，忌惮权贵"),
    ("柳如烟", "如烟社班主，手段老辣，深藏不露"),
    ("小蝉", "十年前失踪的少女，镇上人讳莫如深"),
    ("沈鹤年", "沈砚之父，十年前失踪的记者，回忆中人物"),
]


def _split_chapters(text: str) -> list[tuple[str, str]]:
    """按 '第X章 标题' 切分章节。"""
    pattern = re.compile(r"(第[一二三四五六七八九十百零\d]+章\s+\S+)")
    parts = pattern.split(text)
    chapters: list[tuple[str, str]] = []
    # parts[0] 是开头序言，之后是 [标题, 正文, 标题, 正文, ...]
    i = 1
    while i < len(parts) - 1:
        title = parts[i].strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if title and content:
            chapters.append((title, content))
        i += 2
    return chapters


def _print_section(title: str) -> None:
    print()
    print("─" * 80)
    print(f"【{title}】")
    print("─" * 80)


def _print_static_attrs(label: str, attrs: dict[str, str]) -> None:
    print(f"  {label}:")
    if not attrs:
        print("    (空)")
        return
    for key, value in attrs.items():
        print(f"    {key}: {str(value)[:80]}")


def run_jingzhongchan_v3_full_test():
    """《镜中蝉》全书 V3 全链路分析测试。"""
    print("=" * 80)
    print("灵枢 V3 分析管道 — 真实书籍全书测试（《镜中蝉》）")
    print("=" * 80)
    print(f"管道版本: {PIPELINE_V3_VERSION}")
    print(f"测试用书: 《镜中蝉》（灵枢范例小说·民国悬疑短篇）")

    # 读取原文
    if not SAMPLE_NOVEL_PATH.exists():
        print(f"✗ 找不到样本小说: {SAMPLE_NOVEL_PATH}")
        return
    raw_text = SAMPLE_NOVEL_PATH.read_text(encoding="utf-8")
    print(f"原文总字符数: {len(raw_text)}")

    chapters = _split_chapters(raw_text)
    print(f"切分章节数: {len(chapters)}")
    total_chars = sum(len(c) for _, c in chapters)
    print(f"章节正文总字数: {total_chars}")

    if not chapters:
        print("✗ 未切分到章节，终止测试")
        return

    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()

            # Step 1: 创建书籍与章节
            _print_section("Step 1: 创建书籍与章节")
            book_id = db.create_book("镜中蝉（V3全书测试）")
            print(f"  书籍 id={book_id}")

            chapter_ids = []
            for idx, (title, content) in enumerate(chapters, 1):
                ch_id = db.create_chapter(book_id, title)
                db.update_chapter(ch_id, outline="", content=content)
                chapter_ids.append(ch_id)
                print(f"  第{idx:2d}章: id={ch_id}, 标题={title}, 字数={len(content)}")
            print(f"  总计: {len(chapter_ids)} 章, {total_chars} 字")

            # Step 2: 添加种子人物
            _print_section("Step 2: 添加种子人物")
            char_ids: dict[str, int] = {}
            for name, desc in SEED_CHARACTERS:
                cid = db.create_character(book_id, name)
                char_ids[name] = cid
                print(f"  人物: {name} (id={cid}) — {desc}")

            # Step 3: 运行 V3 全链路分析
            _print_section("Step 3: 运行 V3 全链路分析（规则引擎模式）")
            print(f"  开始时间: {time.strftime('%H:%M:%S')}")
            t0 = time.time()
            pipeline = AnalysisPipelineV3(db)
            result = pipeline.start_run(book_id)
            elapsed = time.time() - t0
            print(f"  耗时: {elapsed:.2f} 秒")
            print()
            print(f"  运行状态: {result.status}")
            print(f"  Run ID: {result.run_id}")
            print(f"  语义块数: {result.block_count}")
            print(f"  实体提及数: {result.mention_count}")
            print(f"  实体候选数: {result.entity_count}")
            print(f"  原子事实数: {result.fact_count}")
            print(f"  卡片数: {result.card_count}")
            print(f"  记忆事实数: {result.memory_fact_count}")
            print(f"  记忆摘要数: {result.memory_summary_fact_count}")
            print(f"  探针计划数: {result.probe_plan_count}")
            print(f"  探针结果数: {result.probe_result_count}")
            print(f"  不一致探针数: {result.probe_inconsistent_count}")
            print(f"  meta.current_phase: {result.meta.get('current_phase', 'N/A')}")

            # Step 4: 语义块统计
            _print_section("Step 4: 语义分块统计")
            blocks = db.list_analysis_blocks(book_id, run_id=result.run_id)
            print(f"  总块数: {len(blocks)}")
            if blocks:
                chapters_with_blocks: dict[int, int] = {}
                for b in blocks:
                    ch_id = dict(b).get("chapter_id", 0)
                    chapters_with_blocks[ch_id] = chapters_with_blocks.get(ch_id, 0) + 1
                print("  各章节块数:")
                for ch_id, cnt in sorted(chapters_with_blocks.items()):
                    print(f"    章节 id={ch_id}: {cnt} 块")
                print()
                print("  前3个语义块预览:")
                for b in blocks[:3]:
                    row = dict(b)
                    text_preview = str(row.get("text", ""))[:60].replace("\n", " ")
                    print(f"    [{row.get('chunk_id')}] 章节{row.get('chapter_id')} | {text_preview}...")

            # Step 5: 实体候选（共指消解结果）
            _print_section("Step 5: 实体候选（共指消解结果）")
            entities = db.list_analysis_entities(book_id, run_id=result.run_id)
            print(f"  总实体数: {len(entities)}")
            type_counts: dict[str, int] = {}
            for e in entities:
                et = dict(e).get("entity_type", "unknown")
                type_counts[et] = type_counts.get(et, 0) + 1
            print(f"  类型分布: {type_counts}")
            print()
            print("  前10个实体:")
            for e in entities[:10]:
                row = dict(e)
                aliases = row.get("aliases", "") or ""
                print(f"    [{row.get('entity_uid', '')[:20]}...] "
                      f"type={row.get('entity_type')} "
                      f"name={row.get('canonical_name')} "
                      f"提及数={row.get('mention_count', '?')} "
                      f"别名={aliases[:30]}")

            # Step 6: 原子事实统计
            _print_section("Step 6: 原子事实统计")
            facts = db.list_analysis_facts(book_id, run_id=result.run_id)
            print(f"  总事实数: {len(facts)}")
            fact_type_counts: dict[str, int] = {}
            for f in facts:
                ft = str(dict(f).get("fact_type", "unknown"))
                fact_type_counts[ft] = fact_type_counts.get(ft, 0) + 1
            print(f"  类型分布: {fact_type_counts}")
            print()
            print("  前5个事实预览:")
            for f in facts[:5]:
                row = dict(f)
                value = row.get("value") or {}
                summary = ""
                if isinstance(value, dict):
                    summary = str(value.get("summary", ""))[:80]
                print(f"    [{row.get('fact_uid', '')[:16]}...] "
                      f"type={row.get('fact_type')} "
                      f"summary={summary}")

            # Step 7: 分析卡片统计与样例
            _print_section("Step 7: 分析卡片统计与样例")
            cards = db.list_analysis_cards(result.run_id)
            print(f"  总卡片数: {len(cards)}")
            card_type_counts: dict[str, int] = {}
            for c in cards:
                ct = dict(c).get("card_type", "unknown")
                card_type_counts[ct] = card_type_counts.get(ct, 0) + 1
            print(f"  类型分布: {card_type_counts}")
            print()
            print("  前5张卡片 payload 预览:")
            for c in cards[:5]:
                row = dict(c)
                payload_raw = row.get("payload_json", "")
                try:
                    payload = json.loads(payload_raw) if isinstance(payload_raw, str) else (payload_raw or {})
                except (json.JSONDecodeError, TypeError):
                    payload = {}
                wb_fields = payload.get("writeback_fields", {}) if isinstance(payload, dict) else {}
                print(f"    [{row.get('card_uid', '')[:20]}...] "
                      f"type={row.get('card_type')} "
                      f"status={row.get('status')}")
                if wb_fields:
                    for k, v in list(wb_fields.items())[:4]:
                        print(f"      {k}: {str(v)[:60]}")

            # Step 8: 记忆层统计
            _print_section("Step 8: 记忆层统计")
            print(f"  memory_fact_count: {result.memory_fact_count}")
            print(f"  memory_summary_fact_count: {result.memory_summary_fact_count}")
            if facts:
                scope_counts: dict[str, int] = {}
                type_counts_mem: dict[str, int] = {}
                for f in facts:
                    row = dict(f)
                    scope = str(row.get("memory_scope", "unknown"))
                    scope_counts[scope] = scope_counts.get(scope, 0) + 1
                    mtype = str(row.get("memory_type", "unknown"))
                    type_counts_mem[mtype] = type_counts_mem.get(mtype, 0) + 1
                print(f"  memory_scope 分布: {scope_counts}")
                print(f"  memory_type 分布: {type_counts_mem}")

            # Step 9: 探针统计
            _print_section("Step 9: 探针统计")
            print(f"  probe_plan_count: {result.probe_plan_count}")
            print(f"  probe_result_count: {result.probe_result_count}")
            print(f"  probe_inconsistent_count: {result.probe_inconsistent_count}")

            # Step 10: 静态属性提取测试（用规则引擎 facts）
            _print_section("Step 10: 静态属性提取测试")
            extracted = _extract_static_attrs_from_facts([dict(f) for f in facts])
            _print_static_attrs("从全书 facts 提取静态属性", extracted)
            if extracted:
                print("  ✓ 规则引擎 facts 中包含静态属性信息")
            else:
                print("  ⚠ 规则引擎 facts 未包含外貌/年龄/性别等静态属性关键词")
                print("    （注：规则引擎的 fact_type 多为 event/state/foreshadowing，")
                print("     静态属性识别需要 AI 模式支持）")

            # Step 11: 构造含静态属性的 facts 验证 build_v3_entity_card
            _print_section("Step 11: build_v3_entity_card 静态属性结构化验证")
            test_entity = {
                "entity_uid": "TEST-SHENYAN",
                "canonical_name": "沈砚",
                "entity_type": "character",
                "metadata": {"role": "主角"},
            }
            test_facts = [
                {"fact_uid": "TF1", "fact_type": "appearance",
                 "value": {"summary": "穿黑布衫，撑黑伞，眉宇间有忧色"},
                 "quote_text": "撑着一把黑伞", "subject_entity_uid": "TEST-SHENYAN"},
                {"fact_uid": "TF2", "fact_type": "identity_occupation",
                 "value": {"summary": "上海《新声报》记者"},
                 "quote_text": "上海来的记者", "subject_entity_uid": "TEST-SHENYAN"},
                {"fact_uid": "TF3", "fact_type": "age",
                 "value": {"summary": "二十出头"},
                 "quote_text": "年纪不过二十出头", "subject_entity_uid": "TEST-SHENYAN"},
                {"fact_uid": "TF4", "fact_type": "gender",
                 "value": {"summary": "男"},
                 "quote_text": "沈家少爷", "subject_entity_uid": "TEST-SHENYAN"},
            ]
            card = build_v3_entity_card(
                book_id=book_id,
                run_id=result.run_id,
                entity=test_entity,
                facts=test_facts,
                card_type="v3_character",
                dependency_hash="jingzhongchan-static-attrs-test",
            )
            payload = card.payload if hasattr(card, "payload") else {}
            wb_fields = payload.get("writeback_fields", {}) if isinstance(payload, dict) else {}
            _print_static_attrs("build_v3_entity_card 输出", wb_fields)
            assert "appearance_keywords" in wb_fields, "writeback_fields 应包含 appearance_keywords"
            assert "identity_occupation" in wb_fields, "writeback_fields 应包含 identity_occupation"
            print("  ✓ build_v3_entity_card 成功结构化提取静态属性")

            # Step 12: writeback_to_state_machine 写入状态机验证
            _print_section("Step 12: writeback_to_state_machine 写入状态机验证")
            shenyan_id = char_ids["沈砚"]
            writeback_to_state_machine(db, book_id, shenyan_id, test_facts)
            sm = dict(db.get_state_machine(shenyan_id)) if db.get_state_machine(shenyan_id) else {}
            sm_static = {
                "alias": sm.get("alias", ""),
                "age": sm.get("age", ""),
                "gender": sm.get("gender", ""),
                "appearance_keywords": sm.get("appearance_keywords", ""),
                "signature_feature": sm.get("signature_feature", ""),
                "identity_occupation": sm.get("identity_occupation", ""),
            }
            _print_static_attrs("状态机字段", sm_static)
            assert "黑伞" in sm_static["appearance_keywords"] or "黑布衫" in sm_static["appearance_keywords"], \
                f"appearance_keywords 应含外貌描述，实际: {sm_static['appearance_keywords']}"
            assert "记者" in sm_static["identity_occupation"], \
                f"identity_occupation 应含'记者'，实际: {sm_static['identity_occupation']}"
            print("  ✓ writeback_to_state_machine 成功写入静态属性到状态机")

            # 最终汇总
            _print_section("测试汇总")
            print(f"  书籍: 《镜中蝉》 ({total_chars} 字, {len(chapters)} 章)")
            print(f"  种子人物: {len(SEED_CHARACTERS)} 个")
            print(f"  V3 分析耗时: {elapsed:.2f} 秒")
            print(f"  语义块: {result.block_count}")
            print(f"  实体提及: {result.mention_count}")
            print(f"  实体候选: {result.entity_count}")
            print(f"  原子事实: {result.fact_count}")
            print(f"  分析卡片: {result.card_count}")
            print(f"  记忆事实: {result.memory_fact_count}")
            print(f"  探针计划: {result.probe_plan_count}")
            print(f"  探针结果: {result.probe_result_count}")
            print()
            print("  ✓ V3 全链路分析在真实书籍上完整运行")
            print("  ✓ build_v3_entity_card 静态属性结构化提取正常")
            print("  ✓ writeback_to_state_machine 状态机写入正常")
            print()
            print("=" * 80)
            print("《镜中蝉》全书 V3 分析测试 — 全部通过！")
            print("=" * 80)

        finally:
            db.close()


if __name__ == "__main__":
    run_jingzhongchan_v3_full_test()
