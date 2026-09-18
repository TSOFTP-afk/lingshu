from __future__ import annotations

import re
from typing import Any

from novel_app.prompt_settings import (
    AI_TEXT_ANALYSIS_AI_PROB_SYSTEM_PROMPT,
    AI_TEXT_ANALYSIS_AI_PROB_TEMPLATE_PROMPT,
    AI_TEXT_ANALYSIS_CLASSIFY_SYSTEM_PROMPT,
    AI_TEXT_ANALYSIS_CROSS_CHAPTER_SYSTEM_PROMPT,
    AI_TEXT_ANALYSIS_CROSS_CHAPTER_TEMPLATE_PROMPT,
    AI_TEXT_ANALYSIS_STYLE_SYSTEM_PROMPT,
    AI_TEXT_ANALYSIS_STYLE_TEMPLATE_PROMPT,
    AI_TEXT_ANALYSIS_TYPO_SYSTEM_PROMPT,
    AI_TEXT_ANALYSIS_TYPO_TEMPLATE_PROMPT,
    AI_TEXT_ANALYSIS_VOICE_SYSTEM_PROMPT,
    AI_TEXT_ANALYSIS_VOICE_TEMPLATE_PROMPT,
)
from novel_app.prompt_utils import render_prompt


class AITextAnalysisMixin:
    def analyze_document(self, text: str, require_remote: bool = False) -> str:
        """分析文档类型,返回 body/outline/character/world"""
        cleaned = text.strip()[:3000]
        if not cleaned:
            return "body"

        self.require_remote("智能导入分类")
        try:
            return self._analyze_remote(cleaned)
        except Exception as exc:
            self._remember_remote_error("文档分类", exc)
            raise

    def detect_chapter_structure(self, text: str, require_remote: bool = False) -> list[dict[str, Any]]:
        """Detect chapter boundaries from imported text."""
        cleaned = text.strip()
        if not cleaned:
            return []

        self.require_remote("章节结构识别")
        try:
            from novel_app.agents import ChapterStructureAgent

            agent = ChapterStructureAgent(self._post_json_chat_completion)
            return agent.detect(cleaned)
        except Exception as exc:
            self._remember_remote_error("章节结构识别", exc)
            raise

    def review_import_catalog(
        self,
        catalog_summary: str,
        total_chapters: int,
    ) -> list[dict[str, Any]]:
        """校验正则解析的目录摘要，返回可疑行号区间。

        用于三阶段智能导入的第二阶段：正则解析后让 AI 检查目录是否合理。
        """
        if not catalog_summary.strip():
            return []
        self.require_remote("导入目录校验")
        try:
            from novel_app.agents import ChapterStructureAgent

            agent = ChapterStructureAgent(self._post_json_chat_completion)
            return agent.review_catalog(catalog_summary, total_chapters)
        except Exception as exc:
            self._remember_remote_error("导入目录校验", exc)
            raise

    def detect_ai_probability(self, text: str) -> tuple[int, str]:
        """Estimate whether text looks AI-generated."""
        cleaned = text.strip()
        if not cleaned:
            return 0, "none"
        if len(cleaned) < 200:
            return 0, "none"
        self.require_remote("AI 概率检测")
        prompt = render_prompt(
            self.prompt_text("ai.text_analysis.ai_prob_template", AI_TEXT_ANALYSIS_AI_PROB_TEMPLATE_PROMPT),
            {
                "content": cleaned[:8000],
            },
        )
        result = self._post_json_chat_completion(
            messages=[
                {"role": "system", "content": self.prompt_text("ai.text_analysis.ai_prob_system", AI_TEXT_ANALYSIS_AI_PROB_SYSTEM_PROMPT)},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
        )
        raw_text = self._chat_completion_content(result, "AI 概率检测")
        payload = self._extract_json_object_payload(raw_text)
        probability = self._coerce_probability(payload.get("probability", 0))
        level = str(payload.get("level", "none")).strip().lower()
        return self._normalize_ai_probability(probability, level)

    def detect_chinese_typos(
        self,
        text: str,
        *,
        require_remote: bool = False,
    ) -> list[dict[str, Any]]:
        """Find probable Chinese typos and correction suggestions."""
        content = str(text or "")
        prompt_content = content.strip()
        if not prompt_content:
            return []
        if require_remote:
            self.require_remote("AI 纠错检测")
        if not self.is_remote_configured():
            return []
        prompt = render_prompt(
            self.prompt_text("ai.text_analysis.typo_template", AI_TEXT_ANALYSIS_TYPO_TEMPLATE_PROMPT),
            {
                "content": prompt_content[:8000],
            },
        )
        result = self._post_json_chat_completion(
            messages=[
                {"role": "system", "content": self.prompt_text("ai.text_analysis.typo_system", AI_TEXT_ANALYSIS_TYPO_SYSTEM_PROMPT)},
                {"role": "user", "content": prompt},
            ],
            temperature=0.05,
        )
        raw_text = self._chat_completion_content(result, "AI 纠错检测")
        try:
            payload = self._extract_json_payload(raw_text)
        except Exception as exc:
            if require_remote:
                raise RuntimeError("AI 纠错返回格式无效：未收到 JSON 数组。") from exc
            return []
        findings: list[dict[str, Any]] = []
        occupied_starts: set[int] = set()
        for item in payload[:80]:
            if not isinstance(item, dict):
                continue
            wrong = str(item.get("wrong", "") or "").strip()
            suggestion = str(item.get("suggestion", "") or "").strip()
            if not wrong or not suggestion or wrong == suggestion:
                continue
            start = content.find(wrong)
            while start in occupied_starts and start >= 0:
                start = content.find(wrong, start + len(wrong))
            if start < 0:
                continue
            occupied_starts.add(start)
            try:
                confidence = float(item.get("confidence", 0.75) or 0.75)
            except (TypeError, ValueError):
                confidence = 0.75
            findings.append(
                {
                    "start": start,
                    "end": start + len(wrong),
                    "wrong": wrong,
                    "suggestion": suggestion,
                    "severity": "medium" if confidence >= 0.8 else "low",
                    "dimension": "错别字(AI)",
                    "rule": "ai_typo_detection",
                    "confidence": max(0.0, min(1.0, confidence)),
                }
            )
        findings.sort(key=lambda item: int(item["start"]))
        return findings

    @staticmethod
    def _coerce_probability(value: Any) -> int:
        if isinstance(value, (int, float)):
            return max(0, min(100, int(round(value))))
        match = re.search(r"\d{1,3}", str(value))
        if not match:
            return 0
        return max(0, min(100, int(match.group(0))))

    @staticmethod
    def _level_from_probability(probability: int) -> str:
        if probability >= 92:
            return "certain"
        if probability >= 68:
            return "high"
        if probability >= 42:
            return "medium"
        if probability >= 18:
            return "low"
        return "none"

    def _normalize_ai_probability(self, probability: int, level: str) -> tuple[int, str]:
        probability = max(0, min(100, int(probability)))
        level = str(level).strip().lower()
        derived = self._level_from_probability(probability)
        if level not in {"certain", "high", "medium", "low", "none"}:
            return probability, derived
        if level == "certain" and probability >= 92:
            return 100, "certain"
        if level != derived:
            return probability, derived
        return probability, level

    def cross_chapter_check(
        self,
        *,
        current_chapter_title: str,
        current_chapter_content: str,
        previous_chapters: list[dict[str, Any]],
        truth_file: str,
        require_remote: bool = False,
        cancel_event: Any = None,
    ) -> dict[str, Any]:
        """Check adjacent chapters for continuity problems."""
        if require_remote:
            self.require_remote("跨章节一致性检查")
        if cancel_event and cancel_event.is_set():
            raise RuntimeError("任务已取消")
        if len(previous_chapters) == 0:
            return {"cross_findings": [], "cross_summary": ""}
        if not (self.api_key and self.model):
            return self._cross_chapter_check_mock(
                current_chapter_title=current_chapter_title,
                current_chapter_content=current_chapter_content,
                previous_chapters=previous_chapters,
                truth_file=truth_file,
            )
        try:
            payload = self._cross_chapter_check_remote(
                current_chapter_title=current_chapter_title,
                current_chapter_content=current_chapter_content,
                previous_chapters=previous_chapters,
                truth_file=truth_file,
            )
            if cancel_event and cancel_event.is_set():
                raise RuntimeError("任务已取消")
            return self._normalize_cross_chapter_payload(payload)
        except Exception as exc:
            self._remember_remote_error("跨章节一致性检查", exc)
            if require_remote:
                raise
        return self._cross_chapter_check_mock(
            current_chapter_title=current_chapter_title,
            current_chapter_content=current_chapter_content,
            previous_chapters=previous_chapters,
            truth_file=truth_file,
        )

    def _cross_chapter_check_remote(
        self,
        *,
        current_chapter_title: str,
        current_chapter_content: str,
        previous_chapters: list[dict[str, Any]],
        truth_file: str,
    ) -> dict[str, Any]:
        prev_blocks: list[str] = []
        for i, ch in enumerate(previous_chapters, start=1):
            prev_blocks.append(
                f"=== 前序章节{i}：{ch.get('title', '未知')} ===\n"
                f"正文：{str(ch.get('content', ''))[:2500]}"
            )
        prompt = render_prompt(
            self.prompt_text("ai.text_analysis.cross_chapter_template", AI_TEXT_ANALYSIS_CROSS_CHAPTER_TEMPLATE_PROMPT),
            {
                "current_chapter_title": current_chapter_title or "未知",
                "current_chapter_content": current_chapter_content[:5000],
                "prev_count": str(len(previous_chapters)),
                "prev_blocks": "\n\n".join(prev_blocks),
                "truth_file": truth_file[:6000],
            },
        )
        result = self._post_json_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": self.prompt_text("ai.text_analysis.cross_chapter_system", AI_TEXT_ANALYSIS_CROSS_CHAPTER_SYSTEM_PROMPT),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.25,
        )
        raw_text = self._chat_completion_content(result, "跨章节一致性审查")
        return self._extract_json_object_payload(raw_text)

    def _cross_chapter_check_mock(
        self,
        *,
        current_chapter_title: str,
        current_chapter_content: str,
        previous_chapters: list[dict[str, Any]],
        truth_file: str,
    ) -> dict[str, Any]:
        return {
            "cross_findings": [],
            "cross_summary": f"本地 Mock：已参考 {len(previous_chapters)} 个前序章节，未检测到明显不一致。",
        }

    def _normalize_cross_chapter_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        findings: list[dict[str, str]] = []
        raw_findings = payload.get("cross_findings", [])
        if isinstance(raw_findings, list):
            for item in raw_findings[:30]:
                if not isinstance(item, dict):
                    continue
                dimension = str(item.get("dimension", "")).strip()
                if dimension not in {"character", "world", "fact"}:
                    continue
                severity = str(item.get("severity", "medium")).strip().lower()
                if severity not in {"high", "medium", "low"}:
                    severity = "medium"
                issue = str(item.get("issue", "")).strip()
                if not issue:
                    continue
                findings.append({
                    "agent": "cross_chapter_auditor",
                    "severity": severity,
                    "category": f"跨章节-{dimension}",
                    "location_hint": str(item.get("conflict_with", "")).strip()[:80],
                    "quote": "",
                    "issue": issue[:800],
                    "suggestion": str(item.get("suggestion", "")).strip()[:800],
                    "dimension": dimension,
                    "conflict_with": str(item.get("conflict_with", "")).strip()[:80],
                    "is_cross_chapter": True,
                })
        return {
            "cross_findings": findings,
            "cross_summary": str(payload.get("cross_summary", "")).strip()[:500],
        }

    def extract_style_profile(
        self,
        *,
        sample_texts: list[str],
        require_remote: bool = False,
    ) -> dict[str, Any]:
        """Extract a compact style profile from chapter samples."""
        if require_remote:
            self.require_remote("风格特征提取")
        if not sample_texts:
            return {"style_profile": ""}
        combined = "\n\n---\n\n".join(t[:3000] for t in sample_texts if t.strip())
        if not combined.strip():
            return {"style_profile": ""}
        self.require_remote("风格特征提取")
        try:
            payload = self._extract_style_profile_remote(combined)
            return payload
        except Exception as exc:
            self._remember_remote_error("风格特征提取", exc)
            raise

    def _extract_style_profile_remote(self, combined_text: str) -> dict[str, Any]:
        prompt = render_prompt(
            self.prompt_text("ai.text_analysis.style_template", AI_TEXT_ANALYSIS_STYLE_TEMPLATE_PROMPT),
            {
                "combined_text": combined_text[:8000],
            },
        )
        result = self._post_json_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": self.prompt_text("ai.text_analysis.style_system", AI_TEXT_ANALYSIS_STYLE_SYSTEM_PROMPT),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.15,
        )
        raw_text = self._chat_completion_content(result, "风格分析")
        payload = self._extract_json_object_payload(raw_text)
        profile_parts = []
        fields = [
            ("narrative_perspective", "叙事视角"),
            ("dialogue_density", "对话密度"),
            ("description_ratio", "描写占比"),
            ("avg_paragraph_length", "段落长度"),
            ("tone", "基调"),
            ("vocabulary_level", "词汇风格"),
            ("pacing", "节奏"),
        ]
        for key, label in fields:
            val = str(payload.get(key, "")).strip()
            if val:
                profile_parts.append(f"{label}：{val}")
        notes = str(payload.get("style_notes", "")).strip()
        if notes:
            profile_parts.append(f"要点：{notes}")
        return {"style_profile": "；".join(profile_parts) if profile_parts else ""}

    def extract_character_voices(
        self,
        *,
        chapters: list[dict[str, Any]],
        character_names: list[str] | None = None,
        require_remote: bool = False,
    ) -> dict[str, Any]:
        """Extract character voice notes from prior chapters."""
        if require_remote:
            self.require_remote("角色声音提取")
        if not chapters:
            return {"character_voices": []}
        self.require_remote("角色声音提取")
        try:
            payload = self._extract_character_voices_remote(chapters, character_names)
            return payload
        except Exception as exc:
            self._remember_remote_error("角色声音提取", exc)
            raise

    def _extract_character_voices_remote(
        self,
        chapters: list[dict[str, Any]],
        character_names: list[str] | None,
    ) -> dict[str, Any]:
        chapter_blocks: list[str] = []
        for ch in chapters[:5]:
            title = str(ch.get("title", "未知"))
            content = str(ch.get("content", ""))[:2000]
            chapter_blocks.append(f"=== {title} ===\n{content}")
        combined = "\n\n".join(chapter_blocks)
        names_hint = ""
        if character_names:
            names_hint = f"\n重点关注角色：{'、'.join(character_names[:10])}"
        prompt = render_prompt(
            self.prompt_text("ai.text_analysis.voice_template", AI_TEXT_ANALYSIS_VOICE_TEMPLATE_PROMPT),
            {
                "combined_text": combined[:8000],
                "names_hint": names_hint,
            },
        )
        result = self._post_json_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": self.prompt_text("ai.text_analysis.voice_system", AI_TEXT_ANALYSIS_VOICE_SYSTEM_PROMPT),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.15,
        )
        raw_text = self._chat_completion_content(result, "角色声音分析")
        payload = self._extract_json_object_payload(raw_text)
        voices = payload.get("character_voices", [])
        if not isinstance(voices, list):
            voices = []
        valid_voices = []
        for v in voices[:8]:
            if not isinstance(v, dict):
                continue
            name = str(v.get("name", "")).strip()
            if not name:
                continue
            valid_voices.append({
                "name": name,
                "speech_style": str(v.get("speech_style", "未明确")).strip()[:40],
                "catchwords": str(v.get("catchwords", "")).strip()[:100],
                "personality_hint": str(v.get("personality_hint", "")).strip()[:40],
            })
        return {"character_voices": valid_voices}

    def format_style_and_voices_block(
        self,
        style_profile: str,
        character_voices: list[dict[str, Any]],
    ) -> str:
        """Format style and voice notes for generation prompts."""
        parts: list[str] = []
        if style_profile.strip():
            parts.append(f"【写作风格特征】{style_profile.strip()}")
        if character_voices:
            voice_lines = []
            for v in character_voices[:8]:
                name = str(v.get("name", ""))
                style = str(v.get("speech_style", ""))
                catchwords = str(v.get("catchwords", ""))
                hint = str(v.get("personality_hint", ""))
                line = f"- {name}：说话风格「{style}」"
                if catchwords:
                    line += f"，口头禅「{catchwords}」"
                if hint:
                    line += f"，{hint}"
                voice_lines.append(line)
            parts.append("【角色声音卡片】\n" + "\n".join(voice_lines))
        return "\n\n".join(parts) if parts else ""

    def _analyze_remote(self, text: str) -> str:
        messages = [
            {
                "role": "system",
                "content": self.prompt_text("ai.text_analysis.classify_system", AI_TEXT_ANALYSIS_CLASSIFY_SYSTEM_PROMPT),
            },
            {"role": "user", "content": text},
        ]
        result = self._post_chat_completion(messages, temperature=0.1)
        choices = result.get("choices", [])
        if choices:
            msg = choices[0].get("message", {}).get("content", "")
            result_clean = msg.strip().lower()
            for label in ("body", "outline", "character", "world"):
                if label in result_clean:
                    return label
        return "body"
