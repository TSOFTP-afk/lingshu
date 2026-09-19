"""阶段 3.4 验证测试：ai_provider.py 系统提示词外置到 novel_app/analysis/prompts/。

保证要点：
- 每个 prompt 文件可被 load_prompt 加载且非空；
- prompts 目录文件数与 ai_provider.py 中 load_prompt 调用数一致（防遗漏）；
- 关键提示词包含特征锚点子串（内容没搬丢）；
- UTF-8 无 BOM、首行元数据注释被加载器跳过。
"""
from __future__ import annotations

import re
from pathlib import Path

from novel_app.analysis.ai_provider import SYSTEM_PROMPT_MENTION
from novel_app.analysis.prompts import load_prompt

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "novel_app" / "analysis" / "prompts"
PROVIDER_SRC = (Path(__file__).resolve().parents[1] / "novel_app" / "analysis" / "ai_provider.py").read_text(encoding="utf-8")

# 每段提示词的特征锚点子串（外置前原文中存在的关键指令句/JSON 片段）
ANCHORS = {
    "entity_mention_extraction": [
        "称号与本名双向提取",
        '{"mentions": [{"quote_text": "示例人物", "entity_type": "character", "confidence": 0.95}]}',
        "不要提取普通方位词作 location",
    ],
    "entity_coreference_resolution": [
        "简称与全名合并",
        "同一 mention_uid 只能归入一个实体",
        '{"entities": [{"canonical_name": "林青霞"',
    ],
    "atomic_fact_extraction": [
        "subject_entity_uid 必须是已知实体列表中出现过的 entity_uid",
        "foreshadowing：伏笔（暗示后续发展的线索）",
    ],
    "card_content_generation": [
        "内容必须基于给定的事实列表，不得编造原文未提及的信息",
        "v3_book_summary",
    ],
    "memory_importance_scoring": [
        "fact_uid 必须原样回传，不得修改",
        "hot ≥ 0.7，warm 0.4-0.7，cold 0.1-0.4，archive < 0.1",
    ],
    "memory_compression": [
        "压缩目标比（target_ratio）",
        '摘要文本置于 "summary" 字段',
    ],
    "probe_question_generation": [
        "foreshadowing_recovery：伏笔回收探针",
        "expected 应明确，便于一致性比对",
    ],
    "semantic_chunk_adjustment": [
        "候选边界可微调（前后移动若干字符到最近的句号/换行/段落边界）",
        '{"boundaries": [1200, 3500, 6800, 9500]}',
    ],
    "semantic_chunk_boundary_v2": [
        "不要新增或删除边界，只调整现有边界位置",
        "边界左侧 20% + 右侧 20%",
    ],
    "mention_marker_screening": [
        "2字名字需警惕是否为普通词",
        '"verdict": "confirmed"',
    ],
    "suspicious_mention_review": [
        "【标记开始】和【标记结束】",
        '"corrected_quote_text"',
    ],
}


def _prompt_md_files() -> dict[str, Path]:
    return {p.stem: p for p in PROMPTS_DIR.glob("*.md")}


def test_all_prompt_files_load_and_nonempty() -> None:
    files = _prompt_md_files()
    assert files, "prompts 目录下没有 .md 文件"
    for name, path in files.items():
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{name}.md 含 BOM"
        loaded = load_prompt(name)
        assert loaded, f"{name}.md 加载结果为空"
        assert not loaded.startswith("<!--"), f"{name}.md 首行元数据注释未被加载器跳过"


def test_file_count_matches_load_prompt_calls() -> None:
    files = _prompt_md_files()
    called = re.findall(r'load_prompt\("([^"]+)"\)', PROVIDER_SRC)
    assert len(called) == 11, f"ai_provider.py 中 load_prompt 调用数应为 11，实际 {len(called)}"
    assert set(called) == set(files), f"调用与文件不一致：缺失 {set(called) - set(files)}，多余 {set(files) - set(called)}"
    assert len(files) == 11


def test_anchor_substrings_present() -> None:
    assert set(ANCHORS) == set(_prompt_md_files()), "锚点清单与 prompts 文件清单不同步"
    for name, anchors in ANCHORS.items():
        loaded = load_prompt(name)
        for anchor in anchors:
            assert anchor in loaded, f"{name}.md 缺少特征锚点：{anchor!r}"


def test_no_interpolation_templates() -> None:
    """本批次外置的 11 段提示词全部为纯静态文本（原代码为非 f-string 三引号常量，
    无插值），因此无需 format 用例；若未来引入含插值的模板，应在此补充
    format 后产物与期望片段的一致性用例。
    """
    # 静态文本一致性：加载结果与文件原文（跳过首行注释）逐字节一致
    for name, path in _prompt_md_files().items():
        text = path.read_text(encoding="utf-8")
        expected = text.split("\n", 1)[1] if text.startswith("<!--") else text
        assert load_prompt(name) == expected


def test_provider_constants_wired_to_load_prompt() -> None:
    """模块级常量已改由 load_prompt 提供，消费点零改动。"""
    assert load_prompt("entity_mention_extraction") == SYSTEM_PROMPT_MENTION
    for consumed in (
        "SYSTEM_PROMPT_MENTION",
        "SYSTEM_PROMPT_COREFERENCE",
        "SYSTEM_PROMPT_FACT",
        "SYSTEM_PROMPT_CARD_CONTENT",
        "SYSTEM_PROMPT_MEMORY_SCORE",
        "SYSTEM_PROMPT_MEMORY_COMPRESS",
        "SYSTEM_PROMPT_PROBE_QUESTION",
        "SYSTEM_PROMPT_SEMANTIC_CHUNK",
        "SYSTEM_PROMPT_SEMANTIC_CHUNK_V2",
        "SYSTEM_PROMPT_MENTION_SCREEN",
        "SYSTEM_PROMPT_MENTION_REVIEW",
    ):
        assert f"system_prompt={consumed}" in PROVIDER_SRC, f"消费点丢失：{consumed}"
