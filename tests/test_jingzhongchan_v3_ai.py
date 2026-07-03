"""真实书籍 V3 AI 模式全链路分析测试：使用《镜中蝉》全书 + DeepSeek AI。

验证 V3 分析管道在 AI 增强模式下的完整运行：
1. 读取《镜中蝉》全文并按章节切分
2. 创建书籍、章节、种子人物
3. 配置 DeepSeek AI provider
4. 运行 V3 全链路分析（AI 增强模式 use_ai=True）
5. 对比 AI 模式 vs 规则引擎模式的产物质量
6. 验证静态属性提取链路
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novel_app.analysis.ai_provider import AIAnalysisProvider
from novel_app.analysis.card_generators_v3 import build_v3_entity_card, _extract_static_attrs_from_facts
from novel_app.analysis.llm_cache import LLMCache
from novel_app.analysis.pipeline_v3 import PIPELINE_V3_VERSION, AnalysisPipelineV3
from novel_app.analysis.state_machine_writeback import writeback_to_state_machine
from novel_app.ai.service import SimpleAIService
from novel_app.database import Database

SAMPLE_NOVEL_PATH = Path(__file__).resolve().parents[1] / "tools" / "sample_novel" / "镜中蝉.txt"

# DeepSeek API 配置（从环境变量或默认值读取）
DEEPSEEK_API_KEY = os.environ.get("LINGSHU_AI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
DEEPSEEK_BASE_URL = os.environ.get("LINGSHU_AI_BASE_URL") or "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = os.environ.get("LINGSHU_AI_MODEL") or "deepseek-chat"

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
    i = 1
    while i < len(parts) - 1:
        title = parts[i].strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if title and content:
            chapters.append((title, content))
        i += 2
    return chapters


def _print_section(title: str, lines: list[str] | None = None) -> None:
    print()
    print("─" * 80)
    print(f"【{title}】")
    print("─" * 80)
    if lines:
        for line in lines:
            print(line)


def _print_static_attrs(label: str, attrs: dict[str, str]) -> None:
    print(f"  {label}:")
    if not attrs:
        print("    (空)")
        return
    for key, value in attrs.items():
        print(f"    {key}: {str(value)[:80]}")


def _create_ai_provider(db: Database) -> AIAnalysisProvider:
    """创建 DeepSeek AI provider。"""
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY 环境变量")
    service = SimpleAIService(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        model=DEEPSEEK_MODEL,
    )
    service.require_remote("V3 AI 增强分析")
    cache = LLMCache(db)
    provider = AIAnalysisProvider(service, cache)
    print(f"  AI provider 已创建: base_url={DEEPSEEK_BASE_URL}, model={DEEPSEEK_MODEL}")
    print(f"  API Key: {DEEPSEEK_API_KEY[:8]}...{DEEPSEEK_API_KEY[-4:]}")
    return provider


def run_jingzhongchan_v3_ai_test():
    """《镜中蝉》全书 V3 AI 模式全链路分析测试。"""
    output_lines: list[str] = []

    def log(msg: str = "") -> None:
        print(msg)
        output_lines.append(msg)

    log("=" * 80)
    log("灵枢 V3 分析管道 — 真实书籍 AI 增强模式测试（《镜中蝉》+ DeepSeek）")
    log("=" * 80)
    log(f"管道版本: {PIPELINE_V3_VERSION}")
    log(f"测试用书: 《镜中蝉》（灵枢范例小说·民国悬疑短篇）")
    log(f"AI 模型: {DEEPSEEK_MODEL} @ {DEEPSEEK_BASE_URL}")

    if not DEEPSEEK_API_KEY:
        log(f"✗ 未配置 API Key，请设置 LINGSHU_AI_API_KEY 环境变量")
        return

    # 读取原文
    if not SAMPLE_NOVEL_PATH.exists():
        log(f"✗ 找不到样本小说: {SAMPLE_NOVEL_PATH}")
        return
    raw_text = SAMPLE_NOVEL_PATH.read_text(encoding="utf-8")
    log(f"原文总字符数: {len(raw_text)}")

    chapters = _split_chapters(raw_text)
    log(f"切分章节数: {len(chapters)}")
    total_chars = sum(len(c) for _, c in chapters)
    log(f"章节正文总字数: {total_chars}")

    if not chapters:
        log("✗ 未切分到章节，终止测试")
        return

    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()

            # Step 1: 创建书籍与章节
            log("")
            log("─" * 80)
            log("【Step 1: 创建书籍与章节】")
            log("─" * 80)
            book_id = db.create_book("镜中蝉（V3 AI测试）")
            log(f"  书籍 id={book_id}")

            chapter_ids = []
            for idx, (title, content) in enumerate(chapters, 1):
                ch_id = db.create_chapter(book_id, title)
                db.update_chapter(ch_id, outline="", content=content)
                chapter_ids.append(ch_id)
                log(f"  第{idx:2d}章: id={ch_id}, 标题={title}, 字数={len(content)}")
            log(f"  总计: {len(chapter_ids)} 章, {total_chars} 字")

            # Step 2: 添加种子人物
            log("")
            log("─" * 80)
            log("【Step 2: 添加种子人物】")
            log("─" * 80)
            char_ids: dict[str, int] = {}
            for name, desc in SEED_CHARACTERS:
                cid = db.create_character(book_id, name)
                char_ids[name] = cid
                log(f"  人物: {name} (id={cid}) — {desc}")

            # Step 3: 创建 AI provider
            log("")
            log("─" * 80)
            log("【Step 3: 创建 DeepSeek AI provider】")
            log("─" * 80)
            ai_provider = _create_ai_provider(db)

            # Step 4: 运行 V3 全链路分析（AI 增强模式）
            log("")
            log("─" * 80)
            log("【Step 4: 运行 V3 全链路分析（AI 增强模式 use_ai=True）】")
            log("─" * 80)
            log(f"  开始时间: {time.strftime('%H:%M:%S')}")
            log(f"  注: AI 模式会调用 DeepSeek API，可能耗时数分钟...")
            t0 = time.time()
            pipeline = AnalysisPipelineV3(db, ai_provider=ai_provider)
            try:
                result = pipeline.start_run(book_id, use_ai=True)
                elapsed = time.time() - t0
                ai_success = True
            except Exception as exc:
                elapsed = time.time() - t0
                ai_success = False
                log(f"  ✗ AI 模式运行失败: {type(exc).__name__}: {exc}")
                log(f"  耗时: {elapsed:.2f} 秒")
                log(f"  尝试回退到规则引擎模式...")
                pipeline_rule = AnalysisPipelineV3(db)
                book_id2 = db.create_book("镜中蝉（V3 回退测试）")
                for idx, (title, content) in enumerate(chapters, 1):
                    ch_id = db.create_chapter(book_id2, title)
                    db.update_chapter(ch_id, outline="", content=content)
                for name, desc in SEED_CHARACTERS:
                    db.create_character(book_id2, name)
                result = pipeline_rule.start_run(book_id2)
                book_id = book_id2
                elapsed = time.time() - t0

            log(f"  耗时: {elapsed:.2f} 秒")
            log("")
            log(f"  运行状态: {result.status}")
            log(f"  Run ID: {result.run_id}")
            log(f"  语义块数: {result.block_count}")
            log(f"  实体提及数: {result.mention_count}")
            log(f"  实体候选数: {result.entity_count}")
            log(f"  原子事实数: {result.fact_count}")
            log(f"  卡片数: {result.card_count}")
            log(f"  记忆事实数: {result.memory_fact_count}")
            log(f"  记忆摘要数: {result.memory_summary_fact_count}")
            log(f"  探针计划数: {result.probe_plan_count}")
            log(f"  探针结果数: {result.probe_result_count}")
            log(f"  不一致探针数: {result.probe_inconsistent_count}")
            log(f"  meta.current_phase: {result.meta.get('current_phase', 'N/A')}")
            log(f"  meta.ai_invoked: {result.meta.get('ai_invoked', 'N/A')}")
            log(f"  meta.ai_stages: {result.meta.get('ai_stages', 'N/A')}")
            log(f"  meta.ai_fallback_stages: {result.meta.get('ai_fallback_stages', 'N/A')}")
            log(f"  meta.ai_call_count: {result.meta.get('ai_call_count', 'N/A')}")
            log(f"  meta.ai_cache_hits: {result.meta.get('ai_cache_hits', 'N/A')}")

            if not ai_success:
                log("")
                log("  ⚠ AI 模式失败，已回退到规则引擎。详见上方错误信息。")

            # Step 5: 语义块统计
            log("")
            log("─" * 80)
            log("【Step 5: 语义分块统计】")
            log("─" * 80)
            blocks = db.list_analysis_blocks(book_id, run_id=result.run_id)
            log(f"  总块数: {len(blocks)}")
            if blocks:
                chapters_with_blocks: dict[int, int] = {}
                for b in blocks:
                    ch_id = dict(b).get("chapter_id", 0)
                    chapters_with_blocks[ch_id] = chapters_with_blocks.get(ch_id, 0) + 1
                log(f"  各章节块数分布: {list(chapters_with_blocks.values())}")
                log("")
                log("  前3个语义块预览:")
                for b in blocks[:3]:
                    row = dict(b)
                    text_preview = str(row.get("text", ""))[:60].replace("\n", " ")
                    log(f"    [{row.get('chunk_id')}] 章节{row.get('chapter_id')} | {text_preview}...")

            # Step 6: 实体候选
            log("")
            log("─" * 80)
            log("【Step 6: 实体候选（共指消解结果）】")
            log("─" * 80)
            entities = db.list_analysis_entities(book_id, run_id=result.run_id)
            log(f"  总实体数: {len(entities)}")
            type_counts: dict[str, int] = {}
            for e in entities:
                et = dict(e).get("entity_type", "unknown")
                type_counts[et] = type_counts.get(et, 0) + 1
            log(f"  类型分布: {type_counts}")
            log("")
            sorted_entities = sorted(entities, key=lambda e: int(dict(e).get("mention_count", 0) or 0), reverse=True)
            log("  前10个实体（按提及数排序）:")
            for e in sorted_entities[:10]:
                row = dict(e)
                aliases = row.get("aliases", "") or ""
                log(f"    [{row.get('entity_uid', '')[:20]}...] "
                    f"type={row.get('entity_type')} "
                    f"name={row.get('canonical_name')} "
                    f"提及数={row.get('mention_count', '?')} "
                    f"别名={aliases[:40]}")

            # Step 7: 原子事实统计
            log("")
            log("─" * 80)
            log("【Step 7: 原子事实统计】")
            log("─" * 80)
            facts = db.list_analysis_facts(book_id, run_id=result.run_id)
            log(f"  总事实数: {len(facts)}")
            fact_type_counts: dict[str, int] = {}
            for f in facts:
                ft = str(dict(f).get("fact_type", "unknown"))
                fact_type_counts[ft] = fact_type_counts.get(ft, 0) + 1
            log(f"  类型分布: {fact_type_counts}")
            log("")
            log("  前5个事实预览:")
            for f in facts[:5]:
                row = dict(f)
                value = row.get("value") or {}
                summary = ""
                if isinstance(value, dict):
                    summary = str(value.get("summary", ""))[:80]
                log(f"    [{row.get('fact_uid', '')[:16]}...] "
                    f"type={row.get('fact_type')} "
                    f"summary={summary}")

            # Step 8: 分析卡片统计与样例
            log("")
            log("─" * 80)
            log("【Step 8: 分析卡片统计与样例】")
            log("─" * 80)
            cards = db.list_analysis_cards(result.run_id)
            log(f"  总卡片数: {len(cards)}")
            card_type_counts: dict[str, int] = {}
            for c in cards:
                ct = dict(c).get("card_type", "unknown")
                card_type_counts[ct] = card_type_counts.get(ct, 0) + 1
            log(f"  类型分布: {card_type_counts}")
            log("")
            log("  前5张卡片 payload 预览:")
            for c in cards[:5]:
                row = dict(c)
                payload_raw = row.get("payload_json", "")
                try:
                    payload = json.loads(payload_raw) if isinstance(payload_raw, str) else (payload_raw or {})
                except (json.JSONDecodeError, TypeError):
                    payload = {}
                wb_fields = payload.get("writeback_fields", {}) if isinstance(payload, dict) else {}
                log(f"    [{row.get('card_uid', '')[:20]}...] "
                    f"type={row.get('card_type')} "
                    f"status={row.get('status')}")
                if wb_fields:
                    for k, v in list(wb_fields.items())[:4]:
                        log(f"      {k}: {str(v)[:60]}")

            # Step 9: 记忆层统计
            log("")
            log("─" * 80)
            log("【Step 9: 记忆层统计】")
            log("─" * 80)
            log(f"  memory_fact_count: {result.memory_fact_count}")
            log(f"  memory_summary_fact_count: {result.memory_summary_fact_count}")
            if facts:
                scope_counts: dict[str, int] = {}
                type_counts_mem: dict[str, int] = {}
                for f in facts:
                    row = dict(f)
                    scope = str(row.get("memory_scope", "unknown"))
                    scope_counts[scope] = scope_counts.get(scope, 0) + 1
                    mtype = str(row.get("memory_type", "unknown"))
                    type_counts_mem[mtype] = type_counts_mem.get(mtype, 0) + 1
                log(f"  memory_scope 分布: {scope_counts}")
                log(f"  memory_type 分布: {type_counts_mem}")

            # Step 10: 探针统计
            log("")
            log("─" * 80)
            log("【Step 10: 探针统计】")
            log("─" * 80)
            log(f"  probe_plan_count: {result.probe_plan_count}")
            log(f"  probe_result_count: {result.probe_result_count}")
            log(f"  probe_inconsistent_count: {result.probe_inconsistent_count}")

            # Step 11: 静态属性提取测试
            log("")
            log("─" * 80)
            log("【Step 11: 静态属性提取测试】")
            log("─" * 80)
            extracted = _extract_static_attrs_from_facts([dict(f) for f in facts])
            log(f"  从全书 facts 提取静态属性:")
            if not extracted:
                log("    (空)")
            else:
                for key, value in extracted.items():
                    log(f"    {key}: {str(value)[:80]}")
            if extracted:
                log("  ✓ facts 中包含静态属性信息")
            else:
                log("  ⚠ facts 未包含外貌/年龄/性别等静态属性关键词")

            # Step 12: build_v3_entity_card 静态属性结构化验证
            log("")
            log("─" * 80)
            log("【Step 12: build_v3_entity_card 静态属性结构化验证】")
            log("─" * 80)
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
                dependency_hash="jingzhongchan-ai-static-attrs-test",
                use_ai=False,
            )
            payload = card.payload if hasattr(card, "payload") else {}
            wb_fields = payload.get("writeback_fields", {}) if isinstance(payload, dict) else {}
            log(f"  build_v3_entity_card 输出:")
            if not wb_fields:
                log("    (空)")
            else:
                for key, value in wb_fields.items():
                    log(f"    {key}: {str(value)[:80]}")
            assert "appearance_keywords" in wb_fields, "writeback_fields 应包含 appearance_keywords"
            assert "identity_occupation" in wb_fields, "writeback_fields 应包含 identity_occupation"
            log("  ✓ build_v3_entity_card 成功结构化提取静态属性")

            # Step 13: writeback_to_state_machine 写入状态机验证
            log("")
            log("─" * 80)
            log("【Step 13: writeback_to_state_machine 写入状态机验证】")
            log("─" * 80)
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
            log(f"  状态机字段:")
            if not sm_static:
                log("    (空)")
            else:
                for key, value in sm_static.items():
                    log(f"    {key}: {str(value)[:80]}")
            assert "黑伞" in sm_static["appearance_keywords"] or "黑布衫" in sm_static["appearance_keywords"], \
                f"appearance_keywords 应含外貌描述，实际: {sm_static['appearance_keywords']}"
            assert "记者" in sm_static["identity_occupation"], \
                f"identity_occupation 应含'记者'，实际: {sm_static['identity_occupation']}"
            log("  ✓ writeback_to_state_machine 成功写入静态属性到状态机")

            # 最终汇总
            log("")
            log("─" * 80)
            log("【测试汇总】")
            log("─" * 80)
            log(f"  书籍: 《镜中蝉》 ({total_chars} 字, {len(chapters)} 章)")
            log(f"  种子人物: {len(SEED_CHARACTERS)} 个")
            log(f"  AI 模式: {'✓ 成功' if ai_success else '✗ 失败（已回退规则引擎）'}")
            log(f"  V3 分析耗时: {elapsed:.2f} 秒")
            log(f"  AI 调用次数: {result.meta.get('ai_call_count', 'N/A')}")
            log(f"  AI 缓存命中: {result.meta.get('ai_cache_hits', 'N/A')}")
            log(f"  AI 阶段: {result.meta.get('ai_stages', 'N/A')}")
            log(f"  AI 回退阶段: {result.meta.get('ai_fallback_stages', 'N/A')}")
            log("")
            log(f"  语义块: {result.block_count}")
            log(f"  实体提及: {result.mention_count}")
            log(f"  实体候选: {result.entity_count}")
            log(f"  原子事实: {result.fact_count}")
            log(f"  分析卡片: {result.card_count}")
            log(f"  记忆事实: {result.memory_fact_count}")
            log(f"  探针计划: {result.probe_plan_count}")
            log(f"  探针结果: {result.probe_result_count}")
            log("")
            if ai_success:
                log("  ✓ V3 AI 增强模式在真实书籍上完整运行")
            else:
                log("  ⚠ V3 AI 模式失败，已回退到规则引擎")
            log("  ✓ build_v3_entity_card 静态属性结构化提取正常")
            log("  ✓ writeback_to_state_machine 状态机写入正常")
            log("")
            log("=" * 80)
            log("《镜中蝉》全书 V3 AI 分析测试 — 完成！")
            log("=" * 80)

            # 保存完整输出到文件
            output_path = Path("ai_test_output.log")
            output_path.write_text("\n".join(output_lines), encoding="utf-8")
            log(f"\n[完整输出已保存至 {output_path.absolute()}]")

        finally:
            db.close()


if __name__ == "__main__":
    run_jingzhongchan_v3_ai_test()
