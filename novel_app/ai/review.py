from __future__ import annotations

import json
import re
from threading import Event
from typing import Any

from novel_app.prompt_settings import (
    AI_REVIEW_GENERATE_SYSTEM_PROMPT,
    AI_REVIEW_GENERATE_TEMPLATE_PROMPT,
    AI_REVIEW_RELATIONSHIP_SYSTEM_PROMPT,
    AI_REVIEW_RELATIONSHIP_TEMPLATE_PROMPT,
    AI_REVIEW_REVIEW_SYSTEM_PROMPT,
    AI_REVIEW_REVIEW_TEMPLATE_PROMPT,
)
from novel_app.prompt_utils import render_prompt


class AIReviewMixin:
    def extract_character_relationships(
        self,
        *,
        book_title: str,
        characters: list[dict[str, Any]],
        chapters: list[dict[str, Any]],
        require_remote: bool = False,
        cancel_event: Event | None = None,
    ) -> list[dict[str, str]]:
        """Infer relationship records from characters and chapters."""
        if require_remote:
            self.require_remote("人物关系分析")
        if cancel_event and cancel_event.is_set():
            raise RuntimeError("任务已取消")
        normalized_characters = self._relationship_named_characters(characters)
        if len(normalized_characters) < 2:
            return []
        if not self.is_remote_configured():
            if require_remote:
                self.require_remote("人物关系分析")
            return self._extract_relationships_mock(
                book_title=book_title,
                characters=normalized_characters,
                chapters=chapters,
            )
        try:
            payload = self._extract_relationships_remote(
                book_title=book_title,
                characters=normalized_characters,
                chapters=chapters,
            )
            if cancel_event and cancel_event.is_set():
                raise RuntimeError("任务已取消")
            return self._normalize_relationship_payload(payload, normalized_characters)
        except Exception as exc:
            self._remember_remote_error("人物关系分析", exc)
            if require_remote:
                raise
            return self._extract_relationships_mock(
                book_title=book_title,
                characters=normalized_characters,
                chapters=chapters,
            )

    def multi_agent_review(
        self,
        *,
        book_title: str,
        chapter_title: str,
        outline: str,
        content: str,
        truth_file: str,
        selected_skills: list[dict[str, Any]] | None = None,
        require_remote: bool = False,
        cancel_event: Event | None = None,
        template_content: str = "",
    ) -> dict[str, Any]:
        """Review chapter content and return normalized findings."""
        if require_remote:
            self.require_remote("长篇校验")
        if cancel_event and cancel_event.is_set():
            raise RuntimeError("任务已取消")
        selected_skills = selected_skills or []
        if self.api_key and self.model:
            try:
                payload = self._multi_agent_review_remote(
                    book_title=book_title,
                    chapter_title=chapter_title,
                    outline=outline,
                    content=content,
                    truth_file=truth_file,
                    selected_skills=selected_skills,
                    template_content=template_content,
                )
                if cancel_event and cancel_event.is_set():
                    raise RuntimeError("任务已取消")
                return self._normalize_review_payload(payload, content, outline)
            except Exception as exc:
                self._remember_remote_error("长篇校验", exc)
                if require_remote:
                    raise
        return self._multi_agent_review_mock(book_title, chapter_title, outline, content, truth_file, selected_skills, template_content)

    def multi_agent_generate_from_outline(
        self,
        *,
        book_title: str,
        chapter_title: str,
        outline: str,
        current_content: str,
        truth_file: str,
        selected_skills: list[dict[str, Any]] | None = None,
        sourcebook_context: str = "",
        require_remote: bool = False,
        cancel_event: Event | None = None,
        template_content: str = "",
        previous_chapters: list[dict[str, Any]] | None = None,
        style_voices_block: str = "",
    ) -> dict[str, Any]:
        """Run the generation pipeline and return a normalized payload."""
        if require_remote:
            self.require_remote("长篇生成")
        if cancel_event and cancel_event.is_set():
            raise RuntimeError("任务已取消")
        selected_skills = selected_skills or []
        previous_chapters = previous_chapters or []
        if self.api_key and self.model:
            try:
                payload = self._multi_agent_generate_remote(
                    book_title=book_title,
                    chapter_title=chapter_title,
                    outline=outline,
                    current_content=current_content,
                    truth_file=truth_file,
                    selected_skills=selected_skills,
                    sourcebook_context=sourcebook_context,
                    template_content=template_content,
                    previous_chapters=previous_chapters,
                    style_voices_block=style_voices_block,
                )
                if cancel_event and cancel_event.is_set():
                    raise RuntimeError("任务已取消")
                return self._normalize_review_payload(payload, current_content, outline)
            except Exception as exc:
                self._remember_remote_error("长篇生成", exc)
                if require_remote:
                    raise
        return self._multi_agent_generate_mock(
            book_title=book_title,
            chapter_title=chapter_title,
            outline=outline,
            current_content=current_content,
            truth_file=truth_file,
            selected_skills=selected_skills,
            sourcebook_context=sourcebook_context,
            template_content=template_content,
            previous_chapters=previous_chapters,
        )

    def multi_agent_graph_generate(
        self,
        *,
        book_title: str,
        chapter_title: str,
        outline: str,
        current_content: str,
        truth_file: str,
        selected_skills: list[dict[str, Any]] | None = None,
        sourcebook_context: str = "",
        require_remote: bool = False,
        cancel_event: Event | None = None,
        template_content: str = "",
        style_voices_block: str = "",
    ) -> dict[str, Any]:
        """Run graph-based generation with shared agent state."""
        from novel_app.agents import AgentGraph, AgentState
        if require_remote:
            self.require_remote("多 Agent 图编排生成")
        if cancel_event and cancel_event.is_set():
            raise RuntimeError("任务已取消")
        graph = AgentGraph(
            self._post_chat_completion,
            post_json_chat=self._post_json_chat_completion,
            model_router=getattr(self, '_model_router', None),
            prompt_overrides=self.get_prompt_overrides(),
        )
        state = AgentState(
            book_title=book_title,
            chapter_title=chapter_title,
            outline=outline,
            current_content=current_content,
            truth_file=truth_file,
            sourcebook_context=sourcebook_context,
            template_content=template_content,
            style_voices_block=style_voices_block,
            selected_skills=selected_skills or [],
            _cancel_event=cancel_event,
        )
        state.plan = ""
        state.draft = current_content
        state = graph.run_generation(state)
        result = state.to_result()
        return self._normalize_review_payload(result, current_content, outline)

    def multi_agent_graph_review(
        self,
        *,
        book_title: str,
        chapter_title: str,
        outline: str,
        content: str,
        truth_file: str,
        selected_skills: list[dict[str, Any]] | None = None,
        require_remote: bool = False,
        cancel_event: Event | None = None,
        template_content: str = "",
    ) -> dict[str, Any]:
        """Run graph-based review with shared agent state."""
        from novel_app.agents import AgentGraph, AgentState
        if require_remote:
            self.require_remote("多 Agent 图编排审查")
        if cancel_event and cancel_event.is_set():
            raise RuntimeError("任务已取消")
        graph = AgentGraph(
            self._post_chat_completion,
            post_json_chat=self._post_json_chat_completion,
            model_router=getattr(self, '_model_router', None),
            prompt_overrides=self.get_prompt_overrides(),
        )
        state = AgentState(
            book_title=book_title,
            chapter_title=chapter_title,
            outline=outline,
            current_content=content,
            truth_file=truth_file,
            template_content=template_content,
            selected_skills=selected_skills or [],
            _cancel_event=cancel_event,
        )
        state = graph.run_review(state)
        result = state.to_result()
        return self._normalize_review_payload(result, content, outline)

    def _multi_agent_generate_remote(
        self,
        *,
        book_title: str,
        chapter_title: str,
        outline: str,
        current_content: str,
        truth_file: str,
        selected_skills: list[dict[str, Any]],
        sourcebook_context: str,
        template_content: str = "",
        previous_chapters: list[dict[str, Any]] | None = None,
        style_voices_block: str = "",
    ) -> dict[str, Any]:
        prev_chapters = previous_chapters or []
        prev_blocks: list[str] = []
        for i, ch in enumerate(prev_chapters, start=1):
            prev_blocks.append(
                f"=== 前序章节{i}：{ch.get('title', '未知')} ===\n"
                f"正文节选：{str(ch.get('content', ''))[:1500]}"
            )
        prev_context_block = ""
        if prev_blocks:
            prev_context_block = "\n\n前序章节正文参考（请保持语言风格和叙事节奏一致）：\n" + "\n\n".join(prev_blocks) + "\n"
        style_block = ""
        if style_voices_block.strip():
            style_block = f"\n\n{style_voices_block.strip()}\n\n请严格按照以上风格特征、人物设定和角色声音生成正文；生成后必须检查人物动机、台词和关系是否 OOC。\n"
        prompt = render_prompt(
            self.prompt_text("ai.review.generate_template", AI_REVIEW_GENERATE_TEMPLATE_PROMPT),
            {
                "book_title": book_title or "未命名作品",
                "chapter_title": chapter_title or "未命名章节",
                "outline": outline or "暂无大纲",
                "current_content": current_content[:9000] or "空",
                "skill_block": self._format_skill_block(selected_skills),
                "sourcebook_context": sourcebook_context[:4000],
                "template_content": template_content[:3000],
                "prev_context_block": prev_context_block,
                "style_block": style_block,
                "truth_file": truth_file[:9000],
            },
        )
        result = self._post_json_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": self.prompt_text("ai.review.generate_system", AI_REVIEW_GENERATE_SYSTEM_PROMPT),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.65,
        )
        raw_text = self._chat_completion_content(result, "长篇生成")
        return self._extract_json_object_payload(raw_text)

    def _multi_agent_generate_mock(
        self,
        *,
        book_title: str,
        chapter_title: str,
        outline: str,
        current_content: str,
        truth_file: str,
        selected_skills: list[dict[str, Any]],
        sourcebook_context: str,
        template_content: str = "",
        previous_chapters: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        outline_text = outline.strip() or "本章需要推进核心冲突，呈现人物选择，并留下下一章钩子。"
        base = current_content.strip()
        if base:
            content = re.sub(r"\n{3,}", "\n\n", base)
            content = f"{content}\n\n【多智能体修订】本章已根据大纲完成结构复核，建议继续补强人物动机、场景目标和结尾钩子。"
        else:
            content = (
                f"{chapter_title or '本章'}\n\n"
                f"{outline_text}\n\n"
                "夜色像一层缓慢落下的幕布，把所有未说出口的话都压进沉默里。主角站在门前，意识到这一章真正要解决的并不是眼前的阻碍，而是自己一直回避的选择。\n\n"
                "他先确认目标，再审视代价。每一个动作都被环境放大：脚步声、风声、远处若有若无的呼喊，都在提醒他，故事已经不能再停在原地。\n\n"
                "冲突随之逼近。对手并没有立刻现身，却通过留下的痕迹改变了局面。主角必须在保守退让和冒险推进之间做出判断，而这个判断也会改变人物关系与后续剧情。\n\n"
                "最终，他选择向前。这个决定暂时解决了眼前问题，却也打开了更深的疑问：真正的危险并不在门后，而在所有人都以为已经确定的设定之中。"
            )
        prev_ctx_note = f"（已参考 {len(previous_chapters or [])} 个前序章节）" if (previous_chapters and len(previous_chapters) > 0) else ""
        payload = {
            "summary": f"《{book_title or '未命名作品'}》/{chapter_title or '当前章节'} 已完成本地长篇生成兜底{prev_ctx_note}。",
            "overall_score": 64,
            "final_verdict": "approve",
            "findings": [
                {
                    "agent": "ooc_auditor",
                    "severity": "low",
                    "category": "人物代入",
                    "location_hint": "全章",
                    "quote": outline_text[:120],
                    "issue": "本地 Mock 已加入人物代入与 OOC 检查占位，但无法替代远程模型的细粒度角色判断。",
                    "suggestion": "接入远程长篇生成用途模型后，可获得更稳定的人物口吻、动机和关系一致性检查。",
                }
            ],
            "revised_content": content,
            "revised_outline": outline_text,
            "template_comparison": "本地 Mock 已读取对照模板上下文；真实远程模型会进一步比较节奏、对白密度和描写比例。" if template_content.strip() else "",
            "risk_notes": "本地 Mock 只提供结构兜底，不代表真实长篇生成质量。",
        }
        return self._normalize_review_payload(payload, current_content, outline)

    def _multi_agent_review_remote(
        self,
        *,
        book_title: str,
        chapter_title: str,
        outline: str,
        content: str,
        truth_file: str,
        selected_skills: list[dict[str, Any]],
        template_content: str = "",
    ) -> dict[str, Any]:
        prompt = render_prompt(
            self.prompt_text("ai.review.review_template", AI_REVIEW_REVIEW_TEMPLATE_PROMPT),
            {
                "book_title": book_title or "未命名作品",
                "chapter_title": chapter_title or "未命名章节",
                "outline": outline or "暂无大纲",
                "skill_block": self._format_skill_block(selected_skills),
                "template_content": template_content[:3000],
                "truth_file": truth_file[:9000],
                "content": content[:16000],
            },
        )
        result = self._post_json_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": self.prompt_text("ai.review.review_system", AI_REVIEW_REVIEW_SYSTEM_PROMPT),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.25,
        )
        raw_text = self._chat_completion_content(result, "长篇审查")
        return self._extract_json_object_payload(raw_text)

    def _multi_agent_review_mock(
        self,
        book_title: str,
        chapter_title: str,
        outline: str,
        content: str,
        truth_file: str,
        selected_skills: list[dict[str, Any]],
        template_content: str = "",
    ) -> dict[str, Any]:
        cleaned = content.strip()
        if cleaned:
            revised = re.sub(r"\n{3,}", "\n\n", cleaned)
        else:
            revised = f"{chapter_title or '本章'}围绕既定大纲展开，先补足场景目标，再推进人物选择。"
        if revised == cleaned and len(revised) >= 80:
            revised = f"{revised}\n\n【校验修订】本段已按长篇校验流程完成一次保守整理，建议作者继续检查人物动机与前后设定。"
        elif revised == cleaned:
            revised = f"{revised}\n\n【审查修订】建议继续补充场景、冲突和人物反应。".strip()
        findings = [
            {
                "agent": "plot_auditor",
                "severity": "medium" if len(cleaned) < 800 else "low",
                "category": "剧情推进",
                "location_hint": "全章",
                "quote": cleaned[:80],
                "issue": "本地审查提示：当前章节仍需要确认冲突推进是否足够清晰。",
                "suggestion": "检查每个场景是否有目标、阻力和结果，必要时补一两句人物反应。",
            },
            {
                "agent": "continuity_auditor",
                "severity": "low",
                "category": "连续性",
                "location_hint": "Truth File",
                "quote": "",
                "issue": "已按当前人物、世界观和大纲做一致性兜底检查。",
                "suggestion": "如果后续接入远程审查模型，可获得更细的矛盾定位。",
            },
        ]
        payload = {
            "summary": f"《{book_title or '未命名作品'}》/{chapter_title or '当前章节'} 已完成本地长篇校验兜底。",
            "overall_score": 72 if len(cleaned) >= 800 else 58,
            "final_verdict": "approve",
            "findings": findings,
            "revised_content": revised,
            "revised_outline": outline.strip() or "本章需围绕当前冲突推进，并保持人物动机、设定和节奏一致。",
            "template_comparison": "本地 Mock 已读取对照模板；建议远程审查时重点比较叙事节奏、对白密度和段落长度。" if template_content.strip() else "",
            "risk_notes": "本地 Mock 只做结构兜底，不代表真实模型审查质量。",
        }
        return self._normalize_review_payload(payload, content, outline)

    def _normalize_review_payload(self, payload: dict[str, Any], fallback_content: str, fallback_outline: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Review payload must be a JSON object.")
        findings: list[dict[str, str]] = []
        raw_findings = payload.get("findings", [])
        if isinstance(raw_findings, list):
            for item in raw_findings[:40]:
                if not isinstance(item, dict):
                    continue
                severity = str(item.get("severity", "low")).strip().lower()
                if severity not in {"high", "medium", "low"}:
                    severity = "low"
                issue = str(item.get("issue") or item.get("issue_text") or "").strip()
                suggestion = str(item.get("suggestion") or item.get("suggestion_text") or "").strip()
                if not issue and not suggestion:
                    continue
                findings.append(
                    {
                        "agent": str(item.get("agent", "")).strip()[:80],
                        "severity": severity,
                        "category": str(item.get("category", "")).strip()[:80],
                        "location_hint": str(item.get("location_hint", "")).strip()[:160],
                        "quote": str(item.get("quote") or item.get("quote_text") or "").strip()[:600],
                        "issue": issue[:1000],
                        "suggestion": suggestion[:1000],
                    }
                )
        verdict_raw = payload.get("final_verdict", payload.get("verdict", "reject"))
        if isinstance(verdict_raw, bool):
            final_verdict = "approve" if verdict_raw else "reject"
        else:
            verdict_text = str(verdict_raw).strip().lower()
            final_verdict = "approve" if verdict_text in {"approve", "approved", "pass", "passed", "ok", "true"} else "reject"
        revised_content = str(payload.get("revised_content") or payload.get("content") or "").strip()
        revised_outline = str(payload.get("revised_outline") or payload.get("outline") or "").strip()
        if not revised_content:
            final_verdict = "reject"
            revised_content = fallback_content
            findings.insert(
                0,
                {
                    "agent": "safety_gate",
                    "severity": "high",
                    "category": "安全护栏",
                    "location_hint": "revised_content",
                    "quote": "",
                    "issue": "模型返回的修订正文为空，已阻止自动覆盖。",
                    "suggestion": "请重新校验，或在生成记录中人工比对后再决定是否手动应用。",
                },
            )
        fallback_length = len(fallback_content.strip())
        if final_verdict == "approve" and fallback_length >= 200 and len(revised_content.strip()) < int(fallback_length * 0.4):
            final_verdict = "reject"
            findings.insert(
                0,
                {
                    "agent": "safety_gate",
                    "severity": "high",
                    "category": "安全护栏",
                    "location_hint": "revised_content",
                    "quote": "",
                    "issue": "模型返回的修订正文长度异常缩短，已阻止自动覆盖。",
                    "suggestion": "请重新校验或手动比对生成记录中的草稿后再决定是否应用。",
                },
            )
        findings = findings[:40]
        if not revised_outline:
            revised_outline = fallback_outline
        risk_notes = payload.get("risk_notes", "")
        if isinstance(risk_notes, list):
            risk_notes = "\n".join(str(item).strip() for item in risk_notes if str(item).strip())
        template_comparison = payload.get("template_comparison", "")
        if isinstance(template_comparison, list):
            template_comparison = "\n".join(str(item).strip() for item in template_comparison if str(item).strip())
        return {
            "summary": str(payload.get("summary", "")).strip(),
            "overall_score": self._coerce_probability(payload.get("overall_score", 0)),
            "final_verdict": final_verdict,
            "findings": findings,
            "revised_content": revised_content,
            "revised_outline": revised_outline,
            "template_comparison": str(template_comparison).strip()[:3000],
            "risk_notes": str(risk_notes).strip(),
        }

    def _relationship_named_characters(self, characters: list[dict[str, Any]]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in characters:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "").strip()
            if not name:
                continue
            key = re.sub(r"\s+", "", name).casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(
                {
                    "name": name[:60],
                    "role": str(item.get("role", "") or "").strip()[:80],
                    "profile_text": str(item.get("profile_text", "") or item.get("profile", "") or "").strip()[:400],
                }
            )
        return normalized

    def _extract_relationships_mock(
        self,
        *,
        book_title: str,
        characters: list[dict[str, str]],
        chapters: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        names = [str(item.get("name", "") or "").strip() for item in characters if str(item.get("name", "") or "").strip()]
        relationships: list[dict[str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()
        type_keywords = [
            ("敌", "敌对"),
            ("仇", "敌对"),
            ("盟", "同盟"),
            ("合作", "合作"),
            ("朋友", "同伴"),
            ("同伴", "同伴"),
            ("师", "师徒"),
            ("父", "亲属"),
            ("母", "亲属"),
            ("兄", "亲属"),
            ("妹", "亲属"),
            ("爱", "情感"),
        ]
        for chapter in chapters:
            content = str(chapter.get("content", "") or "")
            title = str(chapter.get("title", "") or "章节")
            paragraphs = [part for part in re.split(r"\n\s*\n+|[。！？!?；;]", content) if part.strip()]
            for paragraph in paragraphs:
                mentioned = [name for name in names if name and name in paragraph]
                if len(mentioned) < 2:
                    continue
                relation_type = "关联"
                for keyword, label in type_keywords:
                    if keyword in paragraph:
                        relation_type = label
                        break
                for index, source in enumerate(mentioned):
                    for target in mentioned[index + 1:]:
                        pair = tuple(sorted((source, target)))
                        if pair in seen_pairs:
                            continue
                        seen_pairs.add(pair)
                        relationships.append(
                            {
                                "source_name": source,
                                "target_name": target,
                                "relationship_type": relation_type,
                                "description": f"本地分析：两人在《{title}》同段落出现。",
                            }
                        )
                        if len(relationships) >= 80:
                            return relationships
        return relationships

    def _extract_relationships_remote(
        self,
        *,
        book_title: str,
        characters: list[dict[str, str]],
        chapters: list[dict[str, Any]],
    ) -> dict[str, Any]:
        chapter_payload = []
        for item in chapters[:100]:
            chapter_payload.append(
                {
                    "title": str(item.get("title", "") or "")[:80],
                    "outline": str(item.get("outline", "") or "")[:800],
                    "content": str(item.get("content", "") or "")[:2400],
                }
            )
        prompt = render_prompt(
            self.prompt_text("ai.review.relationship_template", AI_REVIEW_RELATIONSHIP_TEMPLATE_PROMPT),
            {
                "book_title": book_title or "未命名作品",
                "characters": json.dumps(characters[:60], ensure_ascii=False),
                "chapters": json.dumps(chapter_payload, ensure_ascii=False),
            },
        )
        result = self._post_json_chat_completion(
            messages=[
                {"role": "system", "content": self.prompt_text("ai.review.relationship_system", AI_REVIEW_RELATIONSHIP_SYSTEM_PROMPT)},
                {"role": "user", "content": prompt},
            ],
            temperature=0.18,
        )
        raw_text = self._chat_completion_content(result, "人物关系分析")
        return self._extract_json_object_payload(raw_text)

    def _normalize_relationship_payload(
        self,
        payload: dict[str, Any],
        characters: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        if not isinstance(payload, dict):
            return []
        allowed: dict[str, str] = {}
        for item in characters:
            name = str(item.get("name", "") or "").strip()
            if name:
                allowed[self._relationship_name_key(name)] = name
        raw_relationships = payload.get("relationships", [])
        if not isinstance(raw_relationships, list):
            return []
        relationships: list[dict[str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for item in raw_relationships[:120]:
            if not isinstance(item, dict):
                continue
            source = allowed.get(self._relationship_name_key(item.get("source_name") or item.get("source") or ""))
            target = allowed.get(self._relationship_name_key(item.get("target_name") or item.get("target") or ""))
            if not source or not target or source == target:
                continue
            pair = tuple(sorted((source, target)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            relationship_type = str(
                item.get("relationship_type") or item.get("type") or item.get("relation") or "关联"
            ).strip()
            description = str(item.get("description") or item.get("evidence") or "").strip()
            relationships.append(
                {
                    "source_name": source,
                    "target_name": target,
                    "relationship_type": (relationship_type or "关联")[:24],
                    "description": description[:160],
                }
            )
        return relationships

    @staticmethod
    def _relationship_name_key(value: Any) -> str:
        text = str(value or "").strip()
        text = re.sub(r"[（(].*?[）)]", "", text)
        text = re.sub(r"\s+", "", text)
        return text.casefold()
