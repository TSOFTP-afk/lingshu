"""网文写作技巧集加载器。

解析 SKILL-*.md 结构化技能文件与参考知识库 md 文件，构建内存索引。
支持从任意指定目录加载（默认从环境变量 WRITING_TECHNIQUES_DIR 或项目 data 目录读取）。
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# 写作阶段 → 推荐技能 ID 映射（源自 README.md「快速使用路线」表）
STAGE_SKILL_MAP: dict[str, list[str]] = {
    "新书立项": ["SKILL-001", "SKILL-005", "SKILL-009", "SKILL-011"],
    "单章写作": ["SKILL-002", "SKILL-004", "SKILL-006", "SKILL-007", "SKILL-012"],
    "爽点设计": ["SKILL-003", "SKILL-013", "SKILL-014", "SKILL-015", "SKILL-016",
                "SKILL-017", "SKILL-018", "SKILL-019", "SKILL-020"],
    "中期维护": ["SKILL-011", "SKILL-022", "SKILL-023", "SKILL-024"],
    "改稿去味": ["SKILL-010", "SKILL-004", "SKILL-006"],
    "发布变现": [],
}

# 技能 ID → 类别（源自 README 技能表）
SKILL_CATEGORY_MAP: dict[str, str] = {
    "SKILL-001": "开篇", "SKILL-002": "钩子", "SKILL-003": "爽点",
    "SKILL-004": "文笔", "SKILL-005": "人物", "SKILL-006": "对话",
    "SKILL-007": "场景", "SKILL-008": "战斗", "SKILL-009": "布局",
    "SKILL-010": "改写", "SKILL-011": "布局", "SKILL-012": "节奏",
    "SKILL-013": "爽点", "SKILL-014": "爽点", "SKILL-015": "爽点",
    "SKILL-016": "爽点", "SKILL-017": "爽点", "SKILL-018": "爽点",
    "SKILL-019": "爽点", "SKILL-020": "爽点",
    "SKILL-022": "场面调度", "SKILL-023": "结构布局",
    "SKILL-024": "情感节奏", "SKILL-026": "心理共鸣",
}

# 参考知识库目录 → 中文类别名
REFERENCE_CATEGORY_MAP: dict[str, str] = {
    "01-情节构建": "情节构建", "02-人物塑造": "人物塑造",
    "03-世界观设定": "世界观设定", "04-对话写作": "对话写作",
    "05-节奏控制": "节奏控制", "06-开篇与结尾": "开篇与结尾",
    "07-文笔与修辞": "文笔与修辞", "08-情感渲染": "情感渲染",
    "09-悬念与反转": "悬念与反转", "10-风格流派": "风格流派",
    "11-创作心态与习惯": "创作心态与习惯", "12-商业与发布": "商业与发布",
}


@dataclass
class TechniqueSkill:
    """可执行技能（SKILL-*.md 解析结果）。"""
    skill_id: str            # SKILL-001
    name: str                # 技能名称（H1 标题）
    one_liner: str           # 一句话描述（## 技能名称 下一行）
    category: str            # 类别
    trigger_scenarios: list[str]      # 触发场景
    input_requirements: list[dict]    # 输入要求（参数表）
    steps: list[dict]                # 执行步骤
    output_format: str               # 输出格式
    quality_checks: list[str]        # 质量检验
    example: str                     # 完整示例（原文）
    raw_content: str                 # 完整 md 原文
    file_path: str                   # 相对路径
    fit_stages: list[str] = field(default_factory=list)  # 适用的写作阶段

    def to_selected_skill(self) -> dict[str, Any]:
        """转换为长篇生成 selected_skills 期望的 dict 格式。

        适配 _format_skill_block（generation.py:535）消费的字段：
        name / category / instruction_text。
        """
        instruction_parts: list[str] = []
        if self.trigger_scenarios:
            instruction_parts.append("触发场景：" + "；".join(self.trigger_scenarios[:3]))
        if self.steps:
            step_lines = [
                f"  {s.get('title', '步骤' + s.get('index', ''))}: {s.get('operation', '')}"
                for s in self.steps[:5]
            ]
            instruction_parts.append("执行步骤：\n" + "\n".join(step_lines))
        if self.output_format:
            instruction_parts.append(f"输出格式：{self.output_format[:200]}")
        if self.quality_checks:
            instruction_parts.append("质量检验：" + "；".join(self.quality_checks[:4]))
        return {
            "name": self.name,
            "category": f"写作技巧/{self.category}",
            "instruction_text": "\n".join(instruction_parts),
            "skill_id": self.skill_id,
            "source": "writing_techniques",
        }


@dataclass
class ReferenceDoc:
    """参考知识库文档。"""
    ref_id: str             # PLOT-001
    title: str              # 标题（从文件名解析）
    source: str             # 来源
    category: str           # 类别
    file_path: str          # 相对路径
    raw_content: str        # 完整 md 原文
    difficulty: str = ""    # 难度（入门/进阶/高级）


class WritingTechniqueLoader:
    """从文件系统加载网文写作技巧集并构建索引。"""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        if base_dir is None:
            # 优先级：显式参数 > WRITING_TECHNIQUES_DIR > SIMPLE_AI_NOVEL_DATA_DIR/writing_techniques > 项目 data/writing_techniques
            env_dir = os.environ.get("WRITING_TECHNIQUES_DIR", "").strip()
            if env_dir:
                base_dir = Path(env_dir)
            else:
                data_root = os.environ.get("SIMPLE_AI_NOVEL_DATA_DIR", "").strip()
                if data_root:
                    base_dir = Path(data_root) / "writing_techniques"
                else:
                    base_dir = Path(__file__).resolve().parents[1] / "data" / "writing_techniques"
        self.base_dir = Path(base_dir)
        self._skills: dict[str, TechniqueSkill] = {}
        self._references: dict[str, ReferenceDoc] = {}
        self._loaded = False

    @property
    def available(self) -> bool:
        return self.base_dir.is_dir()

    def load(self, force: bool = False) -> None:
        if self._loaded and not force:
            return
        self._skills.clear()
        self._references.clear()
        if not self.available:
            logger.warning("写作技巧集目录不存在: %s", self.base_dir)
            self._loaded = True
            return
        self._load_skills()
        self._load_references()
        # 反向填充 fit_stages
        for stage, skill_ids in STAGE_SKILL_MAP.items():
            for sid in skill_ids:
                if sid in self._skills:
                    self._skills[sid].fit_stages.append(stage)
        self._loaded = True
        logger.info(
            "写作技巧集加载完成: %d 个技能, %d 篇参考文档 (来源: %s)",
            len(self._skills), len(self._references), self.base_dir,
        )

    # ---------- 技能加载 ----------
    def _load_skills(self) -> None:
        skills_dir = self.base_dir / "skills"
        if not skills_dir.is_dir():
            return
        for md_file in sorted(skills_dir.glob("SKILL-*.md")):
            try:
                skill = self._parse_skill_file(md_file)
                if skill:
                    self._skills[skill.skill_id] = skill
            except Exception as exc:  # noqa: BLE001
                logger.error("解析技能文件失败 %s: %s", md_file.name, exc)

    def _parse_skill_file(self, md_file: Path) -> TechniqueSkill | None:
        raw = md_file.read_text(encoding="utf-8")
        # skill_id 从文件名提取
        m = re.match(r"(SKILL-\d+)", md_file.name)
        if not m:
            return None
        skill_id = m.group(1)
        # H1 标题作为 name
        h1_match = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
        name = h1_match.group(1).strip() if h1_match else md_file.stem
        # 一句话描述：## 技能名称 下一行
        one_liner = self._extract_section_body(raw, "技能名称")
        # 触发场景
        trigger_scenarios = self._extract_list_items(raw, "触发场景")
        # 输入要求（表格行）
        input_requirements = self._extract_table_rows(raw, "输入要求")
        # 执行步骤
        steps = self._extract_steps(raw)
        # 输出格式
        output_format = self._extract_section_body(raw, "输出格式")
        # 质量检验
        quality_checks = self._extract_list_items(raw, "质量检验")
        # 完整示例（整个 section）
        example = self._extract_full_section(raw, "完整示例")
        category = SKILL_CATEGORY_MAP.get(skill_id, "其他")
        return TechniqueSkill(
            skill_id=skill_id,
            name=name,
            one_liner=one_liner,
            category=category,
            trigger_scenarios=trigger_scenarios,
            input_requirements=input_requirements,
            steps=steps,
            output_format=output_format,
            quality_checks=quality_checks,
            example=example,
            raw_content=raw,
            file_path=str(md_file.relative_to(self.base_dir)).replace("\\", "/"),
        )

    # ---------- 参考文档加载 ----------
    def _load_references(self) -> None:
        for category_dir_name, category_cn in REFERENCE_CATEGORY_MAP.items():
            category_dir = self.base_dir / category_dir_name
            if not category_dir.is_dir():
                continue
            for md_file in sorted(category_dir.rglob("*.md")):
                try:
                    ref = self._parse_reference_file(md_file, category_cn)
                    if ref:
                        self._references[ref.ref_id] = ref
                except Exception as exc:  # noqa: BLE001
                    logger.error("解析参考文档失败 %s: %s", md_file.name, exc)

    def _parse_reference_file(self, md_file: Path, category: str) -> ReferenceDoc | None:
        raw = md_file.read_text(encoding="utf-8")
        rel_path = str(md_file.relative_to(self.base_dir)).replace("\\", "/")
        # 从文件名解析 ref_id, title, source
        # 格式: PLOT-001-三幕式故事结构-网文俱乐部.md
        stem = md_file.stem
        m = re.match(r"([A-Z]+-\d+)-(.+)-([^-\s]+(?:\s[^-\s]+)*)$", stem)
        if m:
            ref_id, title, source = m.group(1), m.group(2), m.group(3)
        else:
            m2 = re.match(r"([A-Z]+-\d+)-(.+)$", stem)
            if m2:
                ref_id, title, source = m2.group(1), m2.group(2), ""
            else:
                return None
        # 难度从内容中提取
        difficulty = ""
        diff_match = re.search(r"难度[:：]\s*(入门|进阶|高级)", raw)
        if diff_match:
            difficulty = diff_match.group(1)
        return ReferenceDoc(
            ref_id=ref_id,
            title=title,
            source=source,
            category=category,
            file_path=rel_path,
            raw_content=raw,
            difficulty=difficulty,
        )

    # ---------- 公共查询 ----------
    def list_skills(self) -> list[TechniqueSkill]:
        self.load()
        return sorted(self._skills.values(), key=lambda s: s.skill_id)

    def get_skill(self, skill_id: str) -> TechniqueSkill | None:
        self.load()
        return self._skills.get(skill_id)

    def list_references(self) -> list[ReferenceDoc]:
        self.load()
        return sorted(self._references.values(), key=lambda r: r.ref_id)

    def get_reference(self, ref_id: str) -> ReferenceDoc | None:
        self.load()
        return self._references.get(ref_id)

    def recommend_by_stage(self, stage: str) -> list[TechniqueSkill]:
        """按写作阶段推荐技能组合。"""
        self.load()
        skill_ids = STAGE_SKILL_MAP.get(stage, [])
        return [self._skills[sid] for sid in skill_ids if sid in self._skills]

    def search(
        self,
        stage: str | None = None,
        category: str | None = None,
        keyword: str | None = None,
    ) -> list[TechniqueSkill]:
        self.load()
        results = self.list_skills()
        if stage:
            results = [s for s in results if stage in s.fit_stages]
        if category:
            results = [s for s in results if category in s.category]
        if keyword:
            kw = keyword.lower()
            results = [
                s for s in results
                if kw in s.name.lower()
                or kw in s.one_liner.lower()
                or kw in s.raw_content.lower()
                or any(kw in sc.lower() for sc in s.trigger_scenarios)
            ]
        return results

    def stages(self) -> list[str]:
        return list(STAGE_SKILL_MAP.keys())

    # ---------- Markdown 解析工具 ----------
    @staticmethod
    def _extract_section_body(raw: str, section_title: str) -> str:
        """提取 ## {section_title} 到下一个 ## 或文件末尾的正文（去除子标题）。"""
        pattern = rf"##\s+{re.escape(section_title)}\s*\n(.*?)(?=\n##\s+|\Z)"
        m = re.search(pattern, raw, re.DOTALL)
        if not m:
            return ""
        body = m.group(1).strip()
        # 去除子标题行
        body = re.sub(r"^###\s+.*$", "", body, flags=re.MULTILINE).strip()
        return body

    @staticmethod
    def _extract_full_section(raw: str, section_title: str) -> str:
        """提取 ## {section_title} 整个 section（含子标题），到下一个同级 ## 或末尾。"""
        pattern = rf"(##\s+{re.escape(section_title)}\s*\n.*?)(?=\n##\s+|\Z)"
        m = re.search(pattern, raw, re.DOTALL)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _extract_list_items(raw: str, section_title: str) -> list[str]:
        body = WritingTechniqueLoader._extract_section_body(raw, section_title)
        items: list[str] = []
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("- ") or line.startswith("* "):
                items.append(line[2:].strip())
            elif line.startswith("- [ ]") or line.startswith("- [x]"):
                items.append(line[5:].strip())
        return items

    @staticmethod
    def _extract_table_rows(raw: str, section_title: str) -> list[dict]:
        body = WritingTechniqueLoader._extract_section_body(raw, section_title)
        rows: list[dict] = []
        lines = [ln for ln in body.splitlines() if ln.strip()]
        if len(lines) < 2:
            return rows
        # 第一行表头
        headers = [h.strip() for h in lines[0].strip("|").split("|")]
        for line in lines[1:]:
            line = line.strip()
            if not line.startswith("|"):
                continue
            # 跳过分隔行
            if re.match(r"^\|[\s\-:|]+\|$", line):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) == len(headers):
                rows.append(dict(zip(headers, cells, strict=False)))
        return rows

    @staticmethod
    def _extract_steps(raw: str) -> list[dict]:
        """提取 ### 步骤N 子节。"""
        steps: list[dict] = []
        # 匹配所有 ### 步骤X：标题
        pattern = r"###\s+(步骤\d+[：:].*?)\n(.*?)(?=\n###\s+|\n##\s+|\Z)"
        for m in re.finditer(pattern, raw, re.DOTALL):
            title = m.group(1).strip()
            body = m.group(2).strip()
            operation = ""
            op_match = re.search(r"\*\*操作\*\*[：:]\s*(.+?)(?=\n\*\*|\Z)", body, re.DOTALL)
            if op_match:
                operation = op_match.group(1).strip()
            points = ""
            pt_match = re.search(r"\*\*要点\*\*[：:]\s*(.+?)(?=\n\*\*|\Z)", body, re.DOTALL)
            if pt_match:
                points = pt_match.group(1).strip()
            idx_match = re.search(r"步骤(\d+)", title)
            steps.append({
                "index": idx_match.group(1) if idx_match else "",
                "title": title,
                "operation": operation,
                "points": points,
            })
        return steps
