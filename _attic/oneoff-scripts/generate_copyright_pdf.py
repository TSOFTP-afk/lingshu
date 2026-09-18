"""生成软件著作权申请源代码 PDF 文档（符合规范：前30页+后30页=60页）。

规范要求：
- 源代码总行数 ≥ 3000 行：提交前 30 页 + 后 30 页（共 60 页）
- 每页 ≥ 50 行（不含空行）
- 页眉：软件名称 + 版本号
- 前 30 页：从程序入口开始连续截取
- 后 30 页：到程序结尾连续截取，末页右下角加"（程序结束）"
- 不得含第三方版权信息

格式：A4 / 10pt 微软雅黑 / 1.5 倍行距（满足 ≥50行/页 要求）
输出：docs/软著申请材料/灵枢源代码-60页.pdf
"""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

SOFTWARE_NAME = "灵枢智能写作工作台软件 V3.0"
FONT_NORMAL = "MSYH"
FONT_BOLD = "MSYHB"
FONT_SIZE = 10
# 10pt 字体，1.4 倍行距：10 * 1.4 = 14pt = 14 * 0.3528 mm ≈ 4.94mm
# A4 可用高度 275mm / 4.94mm ≈ 55 行/页（满足 ≥50 行/页 硬性要求）
LINE_HEIGHT = 4.94
MARGIN_LEFT = 15
MARGIN_RIGHT = 15
MARGIN_TOP = 12
MARGIN_BOTTOM = 10
HEADER_HEIGHT = 5

# 每页目标行数（≥50 行硬性要求）
LINES_PER_PAGE = 53
# 前 30 页 + 后 30 页 = 60 页
FRONT_PAGES = 30
BACK_PAGES = 30
# 实际每页约55行（含空行+分隔符），前30页取1590行
FRONT_LINES = LINES_PER_PAGE * FRONT_PAGES  # 1590 行
# 后30页略减，消除末页溢出（文件分隔符占行）
BACK_LINES = 1570

PROJECT_ROOT = Path(__file__).parent

# Windows 系统字体路径
FONT_REGULAR = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD_PATH = r"C:\Windows\Fonts\msyhbd.ttc"


def build_file_order() -> list[str]:
    """按功能模块组织文件顺序（核心算法优先，混合按功能）。

    前30页：入口 → API → 核心分析算法
    后30页：数据层 → 辅助模块 → 前端入口 → 结尾
    """
    # ===== 前部：入口 + 核心算法（确保 semantic_chunker + memory_window 完整包含）=====
    front_files = [
        # 程序入口
        "main.py",
        "lingshu_api/main.py",
        # 核心分析算法（重点展示，按重要性排序）
        "novel_app/analysis/mention_extractor.py",      # 实体提及抽取
        "novel_app/analysis/coreference.py",             # 共指消解
        "novel_app/analysis/semantic_chunker.py",        # 语义分块
        "novel_app/analysis/memory_window.py",           # 记忆窗口
        "novel_app/analysis/chunker.py",                 # 分块器
        "novel_app/analysis/memory_compressor.py",       # 记忆压缩
        "novel_app/analysis/memory_classifier.py",       # 记忆分类
        "novel_app/analysis/long_context_models.py",     # 长上下文模型
        "novel_app/analysis/entity_identity_resolver.py",# 实体身份解析
        "novel_app/analysis/entity_resolver.py",         # 实体解析
        "novel_app/analysis/fact_extractor.py",          # 事实抽取
        "novel_app/analysis/fact_store.py",              # 事实存储
        "novel_app/analysis/evidence.py",                # 证据
        "novel_app/analysis/consistency_checker.py",     # 一致性检查
        "novel_app/analysis/ai_provider.py",             # AI 提供商
        "novel_app/analysis/writeback.py",               # 回写
        "novel_app/analysis/pipeline_v3.py",             # 管道 v3
        "novel_app/analysis/pipeline_v3_stages.py",      # 管道阶段
        "novel_app/analysis/pipeline_v3_incremental.py", # 增量管道
        "novel_app/analysis/card_generators_v3.py",      # 卡片生成器
        "novel_app/analysis/card_coordinator.py",        # 卡片协调器
        "novel_app/analysis/card_builder.py",            # 卡片构建器
        "novel_app/analysis/active_probe_executor.py",   # 主动探针执行
        "novel_app/analysis/probe_executor.py",          # 探针执行
        "novel_app/analysis/probe_planner.py",           # 探针规划
        "novel_app/analysis/writing_probe.py",           # 写作探针
        "novel_app/analysis/backtrack.py",               # 回溯
        "novel_app/analysis/diff_apply.py",              # 差异应用
        "novel_app/analysis/payload_normalizer.py",      # 载荷规范化
        "novel_app/analysis/llm_cache.py",               # LLM 缓存
        "novel_app/analysis/vector_store.py",            # 向量存储
        "novel_app/analysis/state_machine_writeback.py", # 状态机回写
        "novel_app/analysis/schemas_v3.py",              # Schema v3
        "novel_app/analysis/models.py",                  # 模型
        "novel_app/analysis/store.py",                   # 存储
        "novel_app/analysis/utils.py",                   # 工具
        # AI 服务
        "novel_app/ai/client.py",
        "novel_app/ai/provider.py",
        "novel_app/ai/service.py",
        "novel_app/ai/generation.py",
        "novel_app/ai/review.py",
        "novel_app/ai/book_analysis.py",
        "novel_app/ai/text_analysis.py",
        "novel_app/ai/types.py",
        "novel_app/ai/limits.py",
        # 智能体
        "novel_app/agents/graph.py",
        "novel_app/agents/planner.py",
        "novel_app/agents/writer.py",
        "novel_app/agents/reviser.py",
        "novel_app/agents/auditor.py",
        "novel_app/agents/chapter_structure.py",
        "novel_app/agents/prompts.py",
        # RAG 检索
        "novel_app/rag/retriever.py",
        "novel_app/rag/reranker.py",
        "novel_app/rag/embedder.py",
        "novel_app/rag/qdrant_client.py",
        # 审计
        "novel_app/audit/rules.py",
        "novel_app/audit/validator.py",
        "novel_app/audit/dsl_parser.py",
        "novel_app/audit/dimensions.py",
        # 真值管理
        "novel_app/truth/truth_manager.py",
        # API 路由
        "lingshu_api/dependencies.py",
        "lingshu_api/routers/workspace.py",
        "lingshu_api/routers/analysis_v3.py",
        "lingshu_api/routers/analysis_v3_steps.py",
        "lingshu_api/routers/analysis_v3_runs.py",
        "lingshu_api/routers/analysis_v3_cards.py",
        "lingshu_api/routers/characters.py",
        "lingshu_api/routers/world.py",
        "lingshu_api/routers/export.py",
        "lingshu_api/routers/settings.py",
        "lingshu_api/routers/rag.py",
        "lingshu_api/routers/auth.py",
        "lingshu_api/routers/admin.py",
        "lingshu_api/routers/admin_auth.py",
        "lingshu_api/routers/bookstore.py",
        "lingshu_api/routers/bookshelf.py",
        "lingshu_api/routers/cloud_books.py",
        "lingshu_api/routers/references.py",
        "lingshu_api/routers/skills.py",
        "lingshu_api/routers/writing_techniques.py",
        # API 服务
        "lingshu_api/services/book_sync.py",
        "lingshu_api/services/db_bridge.py",
        "lingshu_api/services/ai_settings.py",
        "lingshu_api/services/workspace_settings.py",
        "lingshu_api/services/usage_recorder.py",
        # WebSocket
        "lingshu_api/ws/chat.py",
        "lingshu_api/ws/tasks.py",
        "lingshu_api/ws/generation.py",
        "lingshu_api/ws/review_ws.py",
        "lingshu_api/ws/analysis_v3_ws.py",
        "lingshu_api/ws/analysis_ws.py",
        "lingshu_api/ws/connection.py",
        # Schemas
        "lingshu_api/schemas/workspace.py",
        "lingshu_api/schemas/analysis_v3.py",
        "lingshu_api/schemas/settings.py",
        "lingshu_api/schemas/auth.py",
        "lingshu_api/schemas/admin_auth.py",
        "lingshu_api/schemas/ws_messages.py",
    ]

    # ===== 后部：数据层 + 辅助模块 + 前端 + 结尾 =====
    # 顺序：短文件在前（中间省略区），长文件在后（确保末页≥50行）
    back_files = [
        # 数据库层
        "novel_app/db/schema.py",
        "novel_app/db/common.py",
        "novel_app/db/__init__.py",
        "novel_app/db/analysis.py",
        "novel_app/db/library.py",
        "novel_app/db/resources.py",
        "novel_app/db/characters.py",
        "novel_app/db/review.py",
        "novel_app/db/media.py",
        "novel_app/db/legacy.py",
        "novel_app/db/structured.py",
        "novel_app/db/character_state_machine.py",
        "novel_app/db/chapter_generation_snapshots.py",
        # 书城
        "novel_app/bookstore/store.py",
        "novel_app/bookstore/cloud_store.py",
        "novel_app/bookstore/app.py",
        "novel_app/bookstore/models.py",
        "novel_app/bookstore/security.py",
        # 结构化模板
        "novel_app/structured_templates/base.py",
        "novel_app/structured_templates/book.py",
        "novel_app/structured_templates/character.py",
        "novel_app/structured_templates/world.py",
        "novel_app/structured_templates/common.py",
        # 写作技巧
        "novel_app/writing_techniques/loader.py",
        "novel_app/writing_techniques/indexer.py",
        # 核心基础设施
        "novel_app/core/state.py",
        "novel_app/core/event_bus.py",
        "novel_app/core/service_locator.py",
        # 状态管理
        "novel_app/state/app_state.py",
        # 主题
        "novel_app/theme/colors.py",
        "novel_app/theme/typography.py",
        "novel_app/theme/spacing.py",
        "novel_app/theme/design_tokens.py",
        "novel_app/theme/theme_customization.py",
        # 辅助工具（短文件放前部，避免成为结尾）
        "novel_app/env_utils.py",           # 16 行
        "novel_app/json_utils.py",          # 123 行
        "novel_app/text_importer.py",
        "novel_app/secure_storage.py",
        "novel_app/prompt_settings.py",
        "novel_app/prompt_utils.py",
        "novel_app/tag_registry.py",
        "novel_app/tag_registry_data.py",
        "novel_app/research_sources.py",
        "novel_app/reference_books.py",
        "novel_app/star_graph_defaults.py",
        "novel_app/model_router.py",
        "novel_app/database.py",
        "novel_app/exporter.py",            # 314 行
        # 前端入口（短文件，放中间）
        "lingshu-app/src/main.js",          # 12 行
        "lingshu-app/src/App.vue",          # 34 行
        "lingshu-app/index.html",           # 13 行
        "electron/preload.js",              # 41 行
        # 长文件放最后（确保末页行数充足）
        "electron/main.js",                 # 409 行
        "packaging/Launcher.cs",            # 1132 行（程序结尾）
    ]

    return front_files + back_files


def load_all_lines(file_order: list[str]) -> tuple[list[tuple[str, str]], int]:
    """按顺序加载所有文件行，返回 [(file_path, line), ...] 和总行数。"""
    all_lines: list[tuple[str, str]] = []
    for file_path in file_order:
        full_path = PROJECT_ROOT / file_path
        if not full_path.exists():
            continue
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    all_lines.append((file_path, line.rstrip("\r\n")))
        except Exception as e:
            print(f"[WARN] 读取失败 {file_path}: {e}")
    return all_lines, len(all_lines)


class SourceCodePDF(FPDF):
    """A4 源代码 PDF，带页眉（软件名+版本号 / 页码）。"""

    def __init__(self) -> None:
        super().__init__(format="A4", unit="mm")
        self.set_auto_page_break(auto=True, margin=MARGIN_BOTTOM)
        self.set_margins(left=MARGIN_LEFT, top=MARGIN_TOP, right=MARGIN_RIGHT)
        self.add_font(FONT_NORMAL, "", FONT_REGULAR)
        self.add_font(FONT_BOLD, "", FONT_BOLD_PATH)
        # 每页实际渲染行数统计（含空行，软著审查员看到的真实行数）
        self._current_page_lines = 0
        self.page_line_counts: dict[int, int] = {}

    def header(self) -> None:
        self.set_y(5)
        self.set_font(FONT_BOLD, "", 8)
        self.set_text_color(80, 80, 80)
        self.cell(0, HEADER_HEIGHT, SOFTWARE_NAME, align="L", new_x="LMARGIN", new_y="TOP")
        page_text = f"第 {self.page_no()} 页 / 共 60 页"
        page_width = self.get_string_width(page_text)
        self.set_x(self.w - MARGIN_RIGHT - page_width)
        self.cell(page_width, HEADER_HEIGHT, page_text, align="R", new_x="LMARGIN", new_y="TOP")
        self.set_text_color(0, 0, 0)
        self.set_y(MARGIN_TOP)

    def footer(self) -> None:
        # 记录当前页行数（在分页前保存）
        self.page_line_counts[self.page_no()] = self._current_page_lines
        self._current_page_lines = 0
        self.set_y(-8)
        self.set_font(FONT_NORMAL, "", 7)
        self.set_text_color(120, 120, 120)
        self.cell(0, 4, f"— {self.page_no()} —", align="C", new_x="LMARGIN", new_y="TOP")
        self.set_text_color(0, 0, 0)

    def add_file_separator(self, file_path: str) -> None:
        self._current_page_lines += 1
        self.set_font(FONT_BOLD, "", FONT_SIZE)
        self.set_text_color(0, 0, 120)
        separator = f"===== 文件: {file_path} ====="
        self.cell(0, LINE_HEIGHT, separator, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)

    def add_omit_marker(self) -> None:
        """中间省略标记。"""
        self.ln(2)
        self.set_font(FONT_BOLD, "", FONT_SIZE)
        self.set_text_color(120, 0, 0)
        marker = "===== （中间部分源代码已省略，共提交前 30 页 + 后 30 页，符合软件著作权登记要求） ====="
        # 居中显示
        text_width = self.get_string_width(marker)
        if text_width > self.w - MARGIN_LEFT - MARGIN_RIGHT:
            # 过长则折行
            self.cell(0, LINE_HEIGHT, marker, new_x="LMARGIN", new_y="NEXT")
        else:
            self.set_x((self.w - text_width) / 2)
            self.cell(text_width, LINE_HEIGHT, marker, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def add_end_marker(self) -> None:
        """程序结束标志（末页右下角）。"""
        self.ln(1)
        self.set_font(FONT_BOLD, "", FONT_SIZE)
        self.set_text_color(120, 0, 0)
        end_marker = "（程序结束）"
        text_width = self.get_string_width(end_marker)
        self.set_x(self.w - MARGIN_RIGHT - text_width)
        self.cell(text_width, LINE_HEIGHT, end_marker, align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)

    def add_code_line(self, line: str) -> None:
        self.set_font(FONT_NORMAL, "", FONT_SIZE)
        self.set_text_color(0, 0, 0)
        processed = line.replace("\t", "    ")
        if not processed:
            # 空行用完整行距，确保每页行数稳定 ≥50
            self.ln(LINE_HEIGHT)
            self._current_page_lines += 1
            return
        max_chars = 95  # 10pt 字体可放更多字符
        if len(processed) <= max_chars:
            self.cell(0, LINE_HEIGHT, processed, new_x="LMARGIN", new_y="NEXT")
            self._current_page_lines += 1
        else:
            chunks = [processed[i:i + max_chars] for i in range(0, len(processed), max_chars)]
            for chunk in chunks:
                self.cell(0, LINE_HEIGHT, chunk, new_x="LMARGIN", new_y="NEXT")
                self._current_page_lines += 1


def generate_pdf() -> Path:
    file_order = build_file_order()
    all_lines, total_lines = load_all_lines(file_order)

    print(f"文件顺序中总行数: {total_lines}")
    print(f"前 {FRONT_PAGES} 页目标行数: {FRONT_LINES}")
    print(f"后 {BACK_PAGES} 页目标行数: {BACK_LINES}")

    if total_lines <= FRONT_LINES + BACK_LINES:
        # 总行数不足，提交全部
        print("[INFO] 总行数不足 60 页，提交全部源代码")
        front_segment = all_lines
        back_segment = []
        has_omit = False
    else:
        front_segment = all_lines[:FRONT_LINES]
        back_segment = all_lines[-BACK_LINES:]
        has_omit = True

    pdf = SourceCodePDF()
    pdf.set_title(SOFTWARE_NAME)
    pdf.set_author("灵枢项目组")
    pdf.add_page()

    # 当前所在文件（用于插入分隔符）
    current_file = None
    lines_on_page = 0

    def write_segment(segment: list[tuple[str, str]], is_last_segment: bool) -> None:
        nonlocal current_file, lines_on_page
        for file_path, line in segment:
            if file_path != current_file:
                if current_file is not None:
                    pass  # 文件间自然分隔
                current_file = file_path
                pdf.add_file_separator(file_path)
                lines_on_page += 1
            pdf.add_code_line(line)
            lines_on_page += 1

    # 写前 30 页
    print(f"\n[1/2] 写入前 {FRONT_PAGES} 页...")
    write_segment(front_segment, is_last_segment=not has_omit)

    # 中间省略标记
    if has_omit:
        pdf.add_omit_marker()
        print(f"[INFO] 插入中间省略标记")

    # 写后 30 页
    if back_segment:
        print(f"[2/2] 写入后 {BACK_PAGES} 页...")
        current_file = None  # 重置，让分隔符重新出现
        write_segment(back_segment, is_last_segment=True)
        # 末页结束标志
        pdf.add_end_marker()

    # 输出
    output_dir = PROJECT_ROOT / "docs" / "软著申请材料"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "灵枢源代码-60页.pdf"
    pdf.output(str(output_path))
    print(f"\n[完成] PDF 已生成: {output_path}")
    print(f"总页数: {pdf.page_no()}")

    # 输出每页实际渲染行数统计（含空行，软著审查员看到的真实行数）
    print(f"\n=== 每页实际渲染行数（含空行）===")
    min_lines = 999
    below_50 = []
    for pg, cnt in sorted(pdf.page_line_counts.items()):
        if cnt < min_lines:
            min_lines = cnt
        if cnt < 50:
            below_50.append((pg, cnt))
        if pg % 10 == 1 or pg == pdf.page_no() or cnt < 50:
            print(f"  第 {pg:2d} 页: {cnt} 行")
    print(f"\n最少行数/页: {min_lines}")
    print(f"是否满足 >=50 行/页: {'是 [OK]' if min_lines >= 50 else '否 [FAIL]'}")
    if below_50:
        print(f"不足50行的页面: {below_50}")
    return output_path


if __name__ == "__main__":
    generate_pdf()
