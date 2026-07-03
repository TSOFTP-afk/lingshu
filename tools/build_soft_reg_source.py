"""构建软著源代码鉴别材料 — 人类可读版。

从项目核心模块抽取代码，按前 30 页（分析引擎） + 后 30 页（前后端）组织。
输出：带清晰文件分隔、模块说明、行号的纯文本文件。
每页约 50 行，总行数控制在 3000 行左右。
"""
from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = PROJECT_ROOT / "docs" / "软著申请材料" / "01-源代码（前30页+后30页）.txt"
LINES_PER_PAGE = 50
PAGE_COUNT = 60
LINES_BUDGET = PAGE_COUNT * LINES_PER_PAGE

# ── 前 30 页：核心分析引擎 ──
FRONT_FILES = [
    ("novel_app/analysis/__init__.py",           "分析引擎包入口，导出全部公开 API"),
    ("novel_app/analysis/schemas_v3.py",         "V3 数据模型定义（语义块、实体候选、原子事实）"),
    ("novel_app/analysis/semantic_chunker.py",   "L1 语义感知分块器（场景/段落/句子边界识别）"),
    ("novel_app/analysis/mention_extractor.py",  "M2 实体提及抽取（规则+LLM 双通道）"),
    ("novel_app/analysis/coreference.py",        "M3 两级共指消解（同名聚类+称谓链+跨章合并）"),
    ("novel_app/analysis/entity_resolver.py",    "实体解析工具（规范化、稳定UID生成）"),
    ("novel_app/analysis/entity_store.py",       "实体数据存储层（CRUD + 向量索引）"),
    ("novel_app/analysis/entity_identity_resolver.py", "ID 全局身份消解（跨章节称号→本名）"),
    ("novel_app/analysis/fact_extractor.py",     "M4 原子事实抽取（5种类型+置信度）"),
    ("novel_app/analysis/fact_store.py",         "事实数据存储层"),
    ("novel_app/analysis/memory_classifier.py",  "M7 ARS 四维记忆评分与分类"),
    ("novel_app/analysis/memory_window.py",      "记忆滑动窗口管理（短期/长期切换）"),
    ("novel_app/analysis/memory_compressor.py",  "记忆 N:1 压缩流水线"),
    ("novel_app/analysis/card_coordinator.py",   "M5 事件驱动卡片生成协调器"),
    ("novel_app/analysis/card_generators_v3.py", "V3 卡片规则生成器"),
    ("novel_app/analysis/card_post_processor.py","卡片 LLM 后处理（去重/合并/类型修正）"),
    ("novel_app/analysis/evidence.py",           "证据门禁（可信度评估+weak/missing/empty判定）"),
    ("novel_app/analysis/v3_writeback.py",       "V3 写回引擎（Schema Gate+快照+审计）"),
    ("novel_app/analysis/writeback.py",          "V1 写回引擎（兼容保留）"),
    ("novel_app/analysis/writeback_card_generator.py", "写回卡片 LLM 精炼生成层"),
    ("novel_app/analysis/backtrack.py",          "精准回溯引擎（影响范围+增量重算）"),
    ("novel_app/analysis/probe_planner.py",      "M8 探针规划器（四类探针计划生成）"),
    ("novel_app/analysis/probe_executor.py",     "探针执行器（定向原文读取）"),
    ("novel_app/analysis/consistency_checker.py","一致性判定器（LLM+规则双模式）"),
    ("novel_app/analysis/llm_cache.py",          "LLM 调用缓存层"),
    ("novel_app/analysis/ai_provider.py",        "AI 调用统一提供者"),
    ("novel_app/analysis/vector_store.py",       "向量存储抽象层"),
    ("novel_app/analysis/pipeline_v3.py",        "V3 分析流水线主入口"),
    ("novel_app/analysis/pipeline_v3_stages.py", "V3 流水线各阶段实现"),
    ("novel_app/analysis/pipeline_v3_config.py", "V3 流水线配置管理"),
    ("novel_app/analysis/pipeline_v3_incremental.py", "V3 增量分析实现"),
    ("novel_app/analysis/diff_apply.py",         "差异应用与合并策略"),
]

# ── 后 30 页：后端 + 前端关键模块 ──
BACK_FILES = [
    ("lingshu_api/main.py",                  "FastAPI 应用入口（创建配置+启动）"),
    ("lingshu_api/dependencies.py",          "共享依赖注入（认证+store+同步）"),
    ("lingshu_api/routers/auth.py",          "用户认证路由（登录/注册/设备信任）"),
    ("lingshu_api/routers/admin_auth.py",    "管理员独立认证路由"),
    ("lingshu_api/routers/analysis_v3.py",   "V3 分析 REST API"),
    ("lingshu_api/routers/workspace.py",     "工作台核心 CRUD API"),
    ("lingshu_api/services/book_sync.py",    "书籍云端同步服务"),
    ("lingshu_api/ws/chat.py",              "WebSocket 对话助手"),
    ("lingshu_api/ws/tasks.py",             "WebSocket 异步任务管理"),
    ("electron/preload.js",                 "Electron 预加载（安全存储桥接）"),
    ("electron/main.js",                    "Electron 主进程（窗口+后端托管）"),
    ("lingshu-app/src/main.js",             "Vue 应用入口（挂载+插件注册）"),
    ("lingshu-app/src/router.js",           "前端路由配置"),
    ("lingshu-app/src/stores/auth.js",      "前端认证状态管理（Pinia）"),
    ("lingshu-app/src/utils/api.js",        "axios 实例+Token注入+WebSocket构建"),
]

HEADER = """══════════════════════════════════════════════════════════════
  灵枢智能写作工作台软件 V3.0  源代码
══════════════════════════════════════════════════════════════

  申请人：________（填写真实姓名）
  软件全称：灵枢智能写作工作台软件
  软件简称：灵枢 LingShu
  版本号：V3.0

  本文档为软件著作权登记源代码鉴别材料，共 60 页。
  前 30 页：核心分析引擎（novel_app/analysis/）
  后 30 页：后端服务 + 前端框架 + 桌面壳

  所有代码为项目自研，已剔除第三方库与缓存目录。
══════════════════════════════════════════════════════════════


"""

SEP = "\n" + "─" * 72 + "\n"
THIN_SEP = "\n" + "· " * 30 + "\n"


def read_clean_lines(filepath: Path) -> list[str]:
    """读取文件，移除 shebang 和编码声明，返回干净代码行。"""
    if not filepath.exists():
        return []
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return []

    # 跳过开头的 shebang / encoding 声明
    clean: list[str] = []
    skip_prefixes = ("#!/", "# -*- coding")
    for i, line in enumerate(lines):
        if i == 0 and any(line.startswith(p) for p in skip_prefixes):
            continue
        clean.append(line)
    return clean


def strip_trailing_blanks(lines: list[str]) -> list[str]:
    """去掉末尾连续空行。"""
    while lines and lines[-1].strip() == "":
        lines.pop()
    return lines


def concat_section(file_list: list[tuple[str, str]], label: str, max_lines: int, silent: bool = False) -> list[str]:
    """拼接文件列表为一个 section。

    每个文件格式:
      ── 分隔线 ──
      # 文件路径
      # 功能说明
      ── 分隔线 ──
      <代码>
    """
    result: list[str] = []
    section_start = len(result)

    for rel_path, description in file_list:
        filepath = PROJECT_ROOT / rel_path
        code_lines = read_clean_lines(filepath)
        if not code_lines:
            if not silent:
                print(f"  ✗ 跳过（不存在）: {rel_path}")
            continue

        code_lines = strip_trailing_blanks(code_lines)

        # 构建文件头块（无行号）
        file_header = [
            SEP,
            f"  📄 {rel_path}\n",
            f"  📝 {description}\n",
            SEP,
        ]

        # 带行号的代码体
        code_body = []
        for i, line in enumerate(code_lines, 1):
            # 保留原始格式（制表符/空格），只去掉行尾换行再统一加
            stripped = line.rstrip("\n\r")
            # 截断过长的行（120 字符以内）
            if len(stripped) > 120:
                stripped = stripped[:117] + "..."
            code_body.append(f"{i:>5d} │ {stripped}\n")

        file_block = file_header + code_body
        block_len = len(file_block)

        if len(result) + block_len > max_lines:
            remaining = max_lines - len(result) - len(file_header)
            if remaining < 5:
                break
            result.extend(file_header)
            result.extend(code_body[:remaining])
            break

        result.extend(file_block)
        if not silent:
            print(f"  ✓ {rel_path}  ({len(code_lines)} 行)")

    total = len(result)
    pages = total // LINES_PER_PAGE
    print(f"  → {label}: {total} 行 (~{pages} 页)")
    return result


def main():
    half = LINES_BUDGET // 2  # 每半约 1500 行
    output: list[str] = [HEADER]

    print(f"{'='*60}")
    print(f"  前 30 页：核心分析引擎（目标 ≤ {half} 行）")
    print(f"{'='*60}")
    front = concat_section(FRONT_FILES, "前 30 页", half)
    output.extend(front)
    front_total = len(output)
    print()

    print(f"{'='*60}")
    print(f"  后 30 页：前后端服务层（目标 ≤ {LINES_BUDGET} 行）")
    print(f"{'='*60}")
    back = concat_section(BACK_FILES, "后 30 页", LINES_BUDGET - front_total)
    output.extend(back)

    total = len(output)
    est_pages = total // LINES_PER_PAGE + 1
    front_pages = front_total // LINES_PER_PAGE
    back_pages = (total - front_total) // LINES_PER_PAGE

    print()
    print(f"{'='*60}")
    print(f"  总计: {total} 行 | ~{est_pages} 页")
    print(f"  前 30 页实际 ~{front_pages} 页 | 后 30 页实际 ~{back_pages} 页")
    print(f"{'='*60}")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.writelines(output)

    print(f"\n  ✓ 输出: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
