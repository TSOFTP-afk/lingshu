"""写作技巧集索引器。

在 WritingTechniqueLoader 之上提供：
- 轻量 JSON 索引（供 API 返回列表用，不含 raw_content）
- 单例缓存（进程级，避免每次请求重新扫描文件系统）
- 与长篇生成 selected_skills 的适配桥接
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from novel_app.writing_techniques.loader import (
    STAGE_SKILL_MAP,
    WritingTechniqueLoader,
)

logger = logging.getLogger(__name__)


class TechniqueIndexer:
    """写作技巧集索引服务（单例，进程级缓存）。"""

    _instance: "TechniqueIndexer | None" = None
    _lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "TechniqueIndexer":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, base_dir: Any = None) -> None:
        if getattr(self, "_initialized", False):
            if base_dir is not None:
                self._loader = WritingTechniqueLoader(base_dir)
                self._loader.load(force=True)
            return
        self._loader = WritingTechniqueLoader(base_dir)
        self._loader.load()
        self._initialized = True

    @classmethod
    def reload(cls, base_dir: Any = None) -> "TechniqueIndexer":
        """重新加载（目录变更后调用）。"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls.__new__(cls)
            cls._instance._loader = WritingTechniqueLoader(base_dir)
            cls._instance._loader.load(force=True)
            cls._instance._initialized = True
        return cls._instance

    @property
    def loader(self) -> WritingTechniqueLoader:
        return self._loader

    # ---------- 索引视图 ----------
    def skill_index(self) -> list[dict[str, Any]]:
        """技能列表轻量索引（不含 raw_content）。"""
        return [
            {
                "skill_id": s.skill_id,
                "name": s.name,
                "one_liner": s.one_liner,
                "category": s.category,
                "trigger_scenarios": s.trigger_scenarios,
                "fit_stages": s.fit_stages,
                "file_path": s.file_path,
                "step_count": len(s.steps),
            }
            for s in self._loader.list_skills()
        ]

    def reference_index(self) -> list[dict[str, Any]]:
        """参考文档列表轻量索引。"""
        return [
            {
                "ref_id": r.ref_id,
                "title": r.title,
                "source": r.source,
                "category": r.category,
                "difficulty": r.difficulty,
                "file_path": r.file_path,
            }
            for r in self._loader.list_references()
        ]

    def stage_index(self) -> list[dict[str, Any]]:
        """写作阶段 → 技能映射索引。"""
        return [
            {"stage": stage, "skill_ids": skill_ids}
            for stage, skill_ids in STAGE_SKILL_MAP.items()
        ]

    def full_index(self) -> dict[str, Any]:
        return {
            "skills": self.skill_index(),
            "references": self.reference_index(),
            "stages": self.stage_index(),
            "available": self._loader.available,
            "base_dir": str(self._loader.base_dir),
        }

    # ---------- 详情 ----------
    def skill_detail(self, skill_id: str) -> dict[str, Any] | None:
        s = self._loader.get_skill(skill_id)
        if not s:
            return None
        return {
            "skill_id": s.skill_id,
            "name": s.name,
            "one_liner": s.one_liner,
            "category": s.category,
            "trigger_scenarios": s.trigger_scenarios,
            "input_requirements": s.input_requirements,
            "steps": s.steps,
            "output_format": s.output_format,
            "quality_checks": s.quality_checks,
            "example": s.example,
            "fit_stages": s.fit_stages,
            "file_path": s.file_path,
            "raw_content": s.raw_content,
        }

    def reference_detail(self, ref_id: str) -> dict[str, Any] | None:
        r = self._loader.get_reference(ref_id)
        if not r:
            return None
        return {
            "ref_id": r.ref_id,
            "title": r.title,
            "source": r.source,
            "category": r.category,
            "difficulty": r.difficulty,
            "file_path": r.file_path,
            "raw_content": r.raw_content,
        }

    # ---------- 检索 ----------
    def search(
        self,
        stage: str | None = None,
        category: str | None = None,
        keyword: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "skill_id": s.skill_id,
                "name": s.name,
                "one_liner": s.one_liner,
                "category": s.category,
                "trigger_scenarios": s.trigger_scenarios,
                "fit_stages": s.fit_stages,
                "file_path": s.file_path,
            }
            for s in self._loader.search(stage=stage, category=category, keyword=keyword)
        ]

    def recommend(self, stage: str) -> list[dict[str, Any]]:
        return [
            {
                "skill_id": s.skill_id,
                "name": s.name,
                "one_liner": s.one_liner,
                "category": s.category,
                "trigger_scenarios": s.trigger_scenarios,
                "file_path": s.file_path,
            }
            for s in self._loader.recommend_by_stage(stage)
        ]

    # ---------- 长篇生成适配 ----------
    def to_selected_skills(self, skill_ids: list[str]) -> list[dict[str, Any]]:
        """把选中的写作技巧 skill_id 列表转换为长篇生成 selected_skills 格式。

        直接可注入 multi_agent_generate_from_outline 的 selected_skills 参数，
        被 _format_skill_block（generation.py:535）消费。
        """
        result: list[dict[str, Any]] = []
        for sid in skill_ids:
            s = self._loader.get_skill(sid)
            if s:
                result.append(s.to_selected_skill())
        return result
