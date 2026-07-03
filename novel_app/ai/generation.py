from __future__ import annotations

import re
from collections.abc import Iterator
from threading import Event
from typing import Any

from novel_app.prompt_settings import (
    AI_GENERATION_CONTINUE_TASK_PROMPT,
    AI_GENERATION_DRAFT_TASK_PROMPT,
    AI_GENERATION_POLISH_TASK_PROMPT,
    AI_GENERATION_SYSTEM_PROMPT,
    AI_GENERATION_TEMPLATE_PROMPT,
    AI_PROJECT_SKILL_DISTILL_SYSTEM_PROMPT,
    AI_PROJECT_SKILL_DISTILL_TEMPLATE_PROMPT,
    AI_SKILL_DISTILL_SYSTEM_PROMPT,
    AI_SKILL_DISTILL_TEMPLATE_PROMPT,
    AI_SUMMARY_SYSTEM_PROMPT,
    AI_SUMMARY_TEMPLATE_PROMPT,
)
from novel_app.prompt_utils import render_prompt


class AIGenerationMixin:
    def generate_draft(
        self,
        book_title: str,
        chapter_title: str,
        outline: str,
        current_content: str = "",
        summary_text: str = "",
        selected_skills: list[dict[str, Any]] | None = None,
        sourcebook_context: str = "",
    ) -> str:
        """Generate a revised draft for a chapter outline."""
        truth_file = "\n".join(
            [
                f"书名：{book_title or '未命名作品'}",
                f"章节：{chapter_title or '未命名章节'}",
                f"章节大纲：{outline or '暂无大纲'}",
                f"已有正文：{current_content or '暂无正文'}",
                f"设定/摘要：{summary_text or '暂无'}",
                sourcebook_context or "",
            ]
        )
        payload = self.multi_agent_generate_from_outline(
            book_title=book_title,
            chapter_title=chapter_title,
            outline=outline,
            current_content=current_content,
            truth_file=truth_file,
            selected_skills=selected_skills,
            sourcebook_context=sourcebook_context,
        )
        return str(payload.get("revised_content") or "")

    def continue_writing(
        self,
        book_title: str,
        chapter_title: str,
        outline: str,
        current_content: str,
        summary_text: str = "",
        selected_skills: list[dict[str, Any]] | None = None,
        sourcebook_context: str = "",
    ) -> str:
        """Continue an existing chapter from the current text."""
        return self._generate_by_mode(
            mode="continue",
            book_title=book_title,
            chapter_title=chapter_title,
            outline=outline,
            current_content=current_content,
            summary_text=summary_text,
            selected_skills=selected_skills,
            sourcebook_context=sourcebook_context,
        )

    def polish_text(
        self,
        book_title: str,
        chapter_title: str,
        outline: str,
        current_content: str,
        summary_text: str = "",
        selected_skills: list[dict[str, Any]] | None = None,
        sourcebook_context: str = "",
    ) -> str:
        """Polish the current chapter text without changing the public API."""
        return self._generate_by_mode(
            mode="polish",
            book_title=book_title,
            chapter_title=chapter_title,
            outline=outline,
            current_content=current_content,
            summary_text=summary_text,
            selected_skills=selected_skills,
            sourcebook_context=sourcebook_context,
        )

    def stream_generate(
        self,
        mode: str,
        book_title: str,
        chapter_title: str,
        outline: str,
        current_content: str = "",
        summary_text: str = "",
        selected_skills: list[dict[str, Any]] | None = None,
        sourcebook_context: str = "",
        cancel_event: Event | None = None,
        require_remote: bool = False,
    ) -> Iterator[str]:
        """Yield generation output in chunks for UI streaming."""
        selected_skills = selected_skills or []
        if mode == "draft":
            truth_file = "\n".join(
                [
                    f"书名：{book_title or '未命名作品'}",
                    f"章节：{chapter_title or '未命名章节'}",
                    f"章节大纲：{outline or '暂无大纲'}",
                    f"已有正文：{current_content or '暂无正文'}",
                    f"设定/摘要：{summary_text or '暂无'}",
                    sourcebook_context or "",
                ]
            )
            payload = self.multi_agent_generate_from_outline(
                book_title=book_title,
                chapter_title=chapter_title,
                outline=outline,
                current_content=current_content,
                truth_file=truth_file,
                selected_skills=selected_skills,
                sourcebook_context=sourcebook_context,
                require_remote=require_remote,
                cancel_event=cancel_event,
            )
            yield from self._chunk_text(str(payload.get("revised_content") or ""), cancel_event=cancel_event)
            return
        if require_remote:
            self.require_remote("写作生成")
        if self.api_key and self.model:
            try:
                yield from self._generate_remote_stream(
                    mode=mode,
                    book_title=book_title,
                    chapter_title=chapter_title,
                    outline=outline,
                    current_content=current_content,
                    summary_text=summary_text,
                    selected_skills=selected_skills,
                    sourcebook_context=sourcebook_context,
                    cancel_event=cancel_event,
                )
                return
            except Exception as exc:
                self._remember_remote_error("流式生成", exc)
                if require_remote:
                    raise

        yield from self._chunk_text(
            self._generate_mock(
                mode=mode,
                book_title=book_title,
                chapter_title=chapter_title,
                outline=outline,
                current_content=current_content,
                summary_text=summary_text,
                selected_skills=selected_skills,
                sourcebook_context=sourcebook_context,
            ),
            cancel_event=cancel_event,
        )

    def summarize_chapter(
        self,
        book_title: str,
        chapter_title: str,
        outline: str,
        content: str,
        require_remote: bool = False,
    ) -> str:
        """Summarize chapter content for outlines and context stores."""
        cleaned_content = content.strip()
        if not cleaned_content:
            return "当前章节还没有正文，暂时无法生成摘要。"

        self.require_remote("大纲同步")
        try:
            return self._summarize_remote(
                book_title=book_title,
                chapter_title=chapter_title,
                outline=outline,
                content=cleaned_content,
            )
        except Exception as exc:
            self._remember_remote_error("摘要同步", exc)
            raise

    def distill_skills(
        self,
        source_title: str,
        source_text: str,
        require_remote: bool = False,
    ) -> list[dict[str, str]]:
        """Extract reusable writing skills from a reference text."""
        cleaned_text = source_text.strip()
        if not cleaned_text:
            return []

        self.require_remote("Skills 提炼")
        try:
            return self._distill_remote(source_title, cleaned_text)
        except Exception as exc:
            self._remember_remote_error("Skills 提炼", exc)
            raise

    def distill_project_skills(
        self,
        source_title: str,
        source_text: str,
        source_url: str = "",
        license_note: str = "待确认",
        reusable_level: str = "pattern_only",
        require_remote: bool = False,
    ) -> list[dict[str, str]]:
        """Extract reusable skills from project research notes."""
        cleaned_text = source_text.strip()
        if not cleaned_text:
            return []

        self.require_remote("项目 Skills 提炼")
        try:
            return self._distill_project_remote(
                source_title=source_title,
                source_text=cleaned_text,
                source_url=source_url,
                license_note=license_note,
                reusable_level=reusable_level,
            )
        except Exception as exc:
            self._remember_remote_error("项目 Skills 提炼", exc)
            raise

    def _generate_by_mode(
        self,
        mode: str,
        book_title: str,
        chapter_title: str,
        outline: str,
        current_content: str = "",
        summary_text: str = "",
        selected_skills: list[dict[str, Any]] | None = None,
        sourcebook_context: str = "",
    ) -> str:
        selected_skills = selected_skills or []
        if self.api_key and self.model:
            try:
                return self._generate_remote(
                    mode=mode,
                    book_title=book_title,
                    chapter_title=chapter_title,
                    outline=outline,
                    current_content=current_content,
                    summary_text=summary_text,
                    selected_skills=selected_skills,
                    sourcebook_context=sourcebook_context,
                )
            except Exception as exc:
                self._remember_remote_error("生成", exc)

        return self._generate_mock(
            mode=mode,
            book_title=book_title,
            chapter_title=chapter_title,
            outline=outline,
            current_content=current_content,
            summary_text=summary_text,
            selected_skills=selected_skills,
            sourcebook_context=sourcebook_context,
        )

    def _generate_remote(
        self,
        mode: str,
        book_title: str,
        chapter_title: str,
        outline: str,
        current_content: str,
        summary_text: str,
        selected_skills: list[dict[str, Any]],
        sourcebook_context: str,
    ) -> str:
        prompt = self._build_remote_generation_prompt(
            mode=mode,
            book_title=book_title,
            chapter_title=chapter_title,
            outline=outline,
            current_content=current_content,
            summary_text=summary_text,
            skill_block=self._format_skill_block(selected_skills),
            sourcebook_context=sourcebook_context,
        )
        result = self._post_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": self.prompt_text("ai.generation.system", AI_GENERATION_SYSTEM_PROMPT),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        return self._chat_completion_content(result, "章节生成")

    def _generate_remote_stream(
        self,
        mode: str,
        book_title: str,
        chapter_title: str,
        outline: str,
        current_content: str,
        summary_text: str,
        selected_skills: list[dict[str, Any]],
        sourcebook_context: str,
        cancel_event: Event | None = None,
    ) -> Iterator[str]:
        prompt = self._build_remote_generation_prompt(
            mode=mode,
            book_title=book_title,
            chapter_title=chapter_title,
            outline=outline,
            current_content=current_content,
            summary_text=summary_text,
            skill_block=self._format_skill_block(selected_skills),
            sourcebook_context=sourcebook_context,
        )
        for chunk in self._stream_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": self.prompt_text("ai.generation.system", AI_GENERATION_SYSTEM_PROMPT),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            cancel_event=cancel_event,
        ):
            text = self._stream_delta_text(chunk)
            if text:
                yield text

    def _summarize_remote(
        self,
        book_title: str,
        chapter_title: str,
        outline: str,
        content: str,
    ) -> str:
        prompt = render_prompt(
            self.prompt_text("ai.summary.template", AI_SUMMARY_TEMPLATE_PROMPT),
            {
                "book_title": book_title or "未命名作品",
                "chapter_title": chapter_title or "未命名章节",
                "outline": outline or "暂无大纲",
                "content": content[:6000],
            },
        )
        result = self._post_chat_completion(
            messages=[
                {"role": "system", "content": self.prompt_text("ai.summary.system", AI_SUMMARY_SYSTEM_PROMPT)},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
        )
        return self._chat_completion_content(result, "章节摘要")

    def _distill_remote(
        self,
        source_title: str,
        source_text: str,
    ) -> list[dict[str, str]]:
        prompt = render_prompt(
            self.prompt_text("ai.skill_distill.template", AI_SKILL_DISTILL_TEMPLATE_PROMPT),
            {
                "source_title": source_title,
                "source_text": source_text[:6000],
            },
        )
        result = self._post_json_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": self.prompt_text("ai.skill_distill.system", AI_SKILL_DISTILL_SYSTEM_PROMPT),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
        )
        raw_text = self._chat_completion_content(result, "参考文本提炼")
        parsed = self._extract_json_payload(raw_text)

        skill_records: list[dict[str, str]] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            if not all(key in item for key in ("name", "category", "summary", "instruction")):
                continue
            skill_records.append(
                {
                    "name": str(item["name"]).strip(),
                    "category": str(item["category"]).strip(),
                    "summary": str(item["summary"]).strip(),
                    "instruction": str(item["instruction"]).strip(),
                    "use_cases": str(item.get("use_cases", "")).strip(),
                    "risk_note": str(item.get("risk_note", "")).strip(),
                }
            )
        return skill_records

    def _distill_project_remote(
        self,
        *,
        source_title: str,
        source_text: str,
        source_url: str,
        license_note: str,
        reusable_level: str,
    ) -> list[dict[str, str]]:
        prompt = render_prompt(
            self.prompt_text("ai.project_skill_distill.template", AI_PROJECT_SKILL_DISTILL_TEMPLATE_PROMPT),
            {
                "source_title": source_title,
                "source_url": source_url or "未记录",
                "license_note": license_note or "待确认",
                "reusable_level": reusable_level or "pattern_only",
                "source_text": source_text[:7000],
            },
        )
        result = self._post_json_chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": self.prompt_text(
                        "ai.project_skill_distill.system",
                        AI_PROJECT_SKILL_DISTILL_SYSTEM_PROMPT,
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.35,
        )
        raw_text = self._chat_completion_content(result, "项目 Skills 提炼")
        parsed = self._extract_json_payload(raw_text)

        skill_records: list[dict[str, str]] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            if not all(key in item for key in ("name", "category", "summary", "instruction")):
                continue
            skill_records.append(
                {
                    "name": str(item["name"]).strip(),
                    "category": str(item["category"]).strip(),
                    "summary": str(item["summary"]).strip(),
                    "instruction": str(item["instruction"]).strip(),
                    "use_cases": str(item.get("use_cases", "")).strip(),
                    "risk_note": str(item.get("risk_note", "")).strip(),
                }
            )
        return skill_records

    def _chat_mock(self, messages: list[dict[str, str]]) -> str:
        user_messages = [item.get("content", "") for item in messages if item.get("role") == "user"]
        latest = user_messages[-1].strip() if user_messages else "请帮我检查当前章节。"
        return (
            "本地 Mock 对话：我已经收到你的问题。\n\n"
            f"你刚才说：{latest[:300]}\n\n"
            "如果要获得真实的多轮 AI 对话，请在 AI 设置中配置“AI 对话”用途。"
        )

    def _generate_mock(
        self,
        mode: str,
        book_title: str,
        chapter_title: str,
        outline: str,
        current_content: str,
        summary_text: str,
        selected_skills: list[dict[str, Any]],
        sourcebook_context: str,
    ) -> str:
        skill_names = [str(item.get("name", "")).strip() for item in selected_skills if str(item.get("name", "")).strip()]
        skill_hint = "、".join(skill_names[:2]) if skill_names else "场景铺陈"
        outline_hint = outline.strip() or "围绕当前冲突继续推进"
        summary_hint = summary_text.strip() or "前文已经建立了基础悬念"
        context_hint = self._compact_context_hint(sourcebook_context)

        if mode == "continue":
            anchor = current_content.strip()[-60:] if current_content.strip() else "空气里仍残留着尚未说明的异样"
            return "\n\n".join(
                [
                    f"{anchor}之后，新的细节开始显露出来。人物没有立刻做出激烈反应，而是先压住情绪，顺着现场留下的痕迹继续判断局势。",
                    f"这一段续写会沿着“{outline_hint}”往前推，同时保留 {skill_hint} 的节奏，并和 {context_hint} 保持一致。",
                    f"等角色真正意识到问题的严重性时，局面已经悄悄偏离了原来的预期，这也让《{book_title or '未命名作品'}》的《{chapter_title or '未命名章节'}》自然获得下一步推进空间。",
                ]
            )

        if mode == "polish":
            source = current_content.strip() or outline_hint
            trimmed = re.sub(r"\s+", " ", source)[:120]
            return "\n\n".join(
                [
                    f"{trimmed}。这段文字经过润色后，会更强调画面感与停顿，让人物动作、环境变化和情绪波动互相支撑，而不是平铺直叙地并列出现。",
                    f"在表达上，我会尽量保留原有信息，但把句式节奏调整得更顺，让关键细节落在更能被读者感知的位置，同时用 {skill_hint} 的方式增强段落层次，并避免偏离 {context_hint}。",
                    f"这样处理之后，这一段既不会脱离原本的剧情核心，也能和“{summary_hint}”形成更自然的呼应。",
                ]
            )

        return "\n\n".join(
            [
                f"《{book_title or '未命名作品'}》的《{chapter_title or '未命名章节'}》从“{outline_hint}”切入，先用环境和动作建立起稳定的画面，再把人物推到真正需要做决定的位置。",
                f"这一版草稿会吸收 {skill_hint} 的写法，并遵守 {context_hint}，让信息释放更均匀。人物不会直接把答案说出来，而是在观察、试探和短暂迟疑里，让读者先察觉到局势正在变化。",
                f"随着章节推进，前文提到的“{summary_hint}”会得到延展，新的线索被悄悄抛出，为后续续写、润色和摘要提炼保留足够空间。",
            ]
        )

    def _compact_context_hint(self, sourcebook_context: str) -> str:
        cleaned = re.sub(r"\s+", " ", sourcebook_context).strip()
        if not cleaned:
            return "当前书籍既有设定"
        return cleaned[:160]

    def _format_skill_block(self, selected_skills: list[dict[str, Any]]) -> str:
        if not selected_skills:
            return "Skills：无"

        lines = ["Skills："]
        for skill in selected_skills:
            name = skill.get("name") or skill.get("title") or "未命名技巧"
            category = skill.get("category") or skill.get("scope") or "通用"
            instruction = (
                skill.get("instruction_text")
                or skill.get("instruction")
                or skill.get("description")
                or skill.get("summary")
                or ""
            )
            lines.append(f"- {name}（{category}）：{instruction}")
        return "\n".join(lines)

    def _build_remote_generation_prompt(
        self,
        mode: str,
        book_title: str,
        chapter_title: str,
        outline: str,
        current_content: str,
        summary_text: str,
        skill_block: str,
        sourcebook_context: str,
    ) -> str:
        return render_prompt(
            self.prompt_text("ai.generation.template", AI_GENERATION_TEMPLATE_PROMPT),
            {
                "book_title": book_title or "未命名作品",
                "chapter_title": chapter_title or "未命名章节",
                "outline": outline or "暂无大纲",
                "summary_text": summary_text or "暂无摘要",
                "sourcebook_context": sourcebook_context.strip()[:5000] or "暂无 sourcebook 上下文",
                "current_content": current_content or "暂无正文",
                "skill_block": skill_block,
                "task_instruction": self._generation_task_instruction(mode),
            },
        )

    def _generation_task_instruction(self, mode: str) -> str:
        if mode == "continue":
            return self.prompt_text("ai.generation.continue_task", AI_GENERATION_CONTINUE_TASK_PROMPT)
        if mode == "polish":
            return self.prompt_text("ai.generation.polish_task", AI_GENERATION_POLISH_TASK_PROMPT)
        return self.prompt_text("ai.generation.draft_task", AI_GENERATION_DRAFT_TASK_PROMPT)
