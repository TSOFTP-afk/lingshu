from __future__ import annotations

import json
import warnings
from typing import Any

from novel_app.structured_templates import (
    BOOK_OUTLINE_FORM_SCHEMA,
    PROTAGONIST_TEMPLATE,
    SUPPORTING_CHARACTER_TEMPLATE,
    WORLD_FORM_SCHEMA,
    WORLD_TEMPLATE,
    book_outline_template,
    character_profile_schema_for_role,
)

from .limits import (
    BOOK_ANALYSIS_LEVEL1_MAX_TOKENS,
    BOOK_ANALYSIS_LEVEL2_MAX_TOKENS,
    BOOK_ANALYSIS_LEVEL3_MAX_TOKENS,
    MAX_BOOK_ANALYSIS_INPUT_CHARS,
)


# DEPRECATED: 三层金字塔 AI 分析系统已被 V3 AI 增强模式替代。
# 新代码应使用 novel_app.analysis.pipeline_v3.AnalysisPipelineV3(use_ai=True)。
# 详见 .trae/specs/ai-v3-replace-three-layer/spec.md
class AIBookAnalysisMixin:
    def analyze_book(
        self,
        *,
        book_title: str,
        book_outline: str,
        chapters: list[dict[str, Any]],
        characters: list[dict[str, Any]] | None = None,
        world_entries: list[dict[str, Any]] | None = None,
        require_remote: bool = False,
    ) -> dict[str, Any]:
        """Analyze a whole book and return a normalized analysis payload."""
        if require_remote:
            self.require_remote("全书分析")
        characters = characters or []
        world_entries = world_entries or []
        if self.api_key and self.model:
            try:
                return self._analyze_book_remote(
                    book_title=book_title,
                    book_outline=book_outline,
                    chapters=chapters,
                    characters=characters,
                    world_entries=world_entries,
                )
            except Exception as exc:
                self._remember_remote_error("全书分析", exc)
                if require_remote:
                    raise
        return self._analyze_book_mock(book_title, book_outline, chapters, characters, world_entries)

    def analyze_book_level1(
        self,
        *,
        book_title: str,
        book_outline: str,
        chunk_text: str,
        chunk_index: int,
        total_chunks: int,
        chunk_id: str = "",
        chapter_ids: list[int] | None = None,
        extra_body: dict[str, Any] | None = None,
        require_remote: bool = True,
    ) -> dict[str, Any]:
        """Analyze one source chunk for the first pyramid level."""
        warnings.warn(
            "analyze_book_level1 已废弃，请使用 AnalysisPipelineV3(use_ai=True) 替代。"
            "详见 .trae/specs/ai-v3-replace-three-layer/spec.md",
            DeprecationWarning,
            stacklevel=2,
        )
        if require_remote:
            self.require_remote("全书分析一级")
        if not self.is_remote_configured():
            self.require_remote("全书分析一级")
        try:
            return self._analyze_book_level1_remote(
                book_title=book_title,
                book_outline=book_outline,
                chunk_text=chunk_text,
                chunk_index=chunk_index,
                total_chunks=total_chunks,
                chunk_id=chunk_id,
                chapter_ids=chapter_ids or [],
                extra_body=extra_body,
            )
        except Exception as exc:
            self._remember_remote_error("全书分析一级", exc)
            raise

    def analyze_book_level2(
        self,
        *,
        book_title: str,
        level1_results: list[dict[str, Any]],
        group_index: int,
        total_groups: int,
        extra_body: dict[str, Any] | None = None,
        require_remote: bool = True,
    ) -> dict[str, Any]:
        """Merge level-one chunk analyses into structured summaries."""
        warnings.warn(
            "analyze_book_level2 已废弃，请使用 AnalysisPipelineV3(use_ai=True) 替代。"
            "详见 .trae/specs/ai-v3-replace-three-layer/spec.md",
            DeprecationWarning,
            stacklevel=2,
        )
        if require_remote:
            self.require_remote("全书分析二级")
        if not self.is_remote_configured():
            self.require_remote("全书分析二级")
        try:
            return self._analyze_book_level2_remote(
                book_title=book_title,
                level1_results=level1_results,
                group_index=group_index,
                total_groups=total_groups,
                extra_body=extra_body,
            )
        except Exception as exc:
            self._remember_remote_error("全书分析二级", exc)
            raise

    def analyze_book_level3(
        self,
        *,
        book_title: str,
        book_outline: str,
        level2_results: list[dict[str, Any]],
        chapters: list[dict[str, Any]],
        characters: list[dict[str, Any]] | None = None,
        world_entries: list[dict[str, Any]] | None = None,
        extra_body: dict[str, Any] | None = None,
        require_remote: bool = True,
    ) -> dict[str, Any]:
        """Produce final writable book-analysis outputs."""
        warnings.warn(
            "analyze_book_level3 已废弃，请使用 AnalysisPipelineV3(use_ai=True) 替代。"
            "详见 .trae/specs/ai-v3-replace-three-layer/spec.md",
            DeprecationWarning,
            stacklevel=2,
        )
        if require_remote:
            self.require_remote("全书分析三级")
        if not self.is_remote_configured():
            self.require_remote("全书分析三级")
        try:
            return self._analyze_book_level3_draft_remote(
                book_title=book_title,
                book_outline=book_outline,
                level2_results=level2_results,
                chapters=chapters,
                characters=characters or [],
                world_entries=world_entries or [],
                extra_body=extra_body,
            )
        except Exception as exc:
            self._remember_remote_error("全书分析三级", exc)
            raise

    def analyze_book_level3_draft(
        self,
        *,
        book_title: str,
        book_outline: str,
        level2_results: list[dict[str, Any]],
        chapters: list[dict[str, Any]],
        characters: list[dict[str, Any]] | None = None,
        world_entries: list[dict[str, Any]] | None = None,
        source_index: list[dict[str, Any]] | None = None,
        extra_body: dict[str, Any] | None = None,
        require_remote: bool = True,
    ) -> dict[str, Any]:
        """Draft final book-analysis outputs before evidence gating."""
        warnings.warn(
            "analyze_book_level3_draft 已废弃，请使用 AnalysisPipelineV3(use_ai=True) 替代。"
            "详见 .trae/specs/ai-v3-replace-three-layer/spec.md",
            DeprecationWarning,
            stacklevel=2,
        )
        if require_remote:
            self.require_remote("全书分析三级草案")
        if not self.is_remote_configured():
            self.require_remote("全书分析三级草案")
        try:
            return self._analyze_book_level3_draft_remote(
                book_title=book_title,
                book_outline=book_outline,
                level2_results=level2_results,
                chapters=chapters,
                characters=characters or [],
                world_entries=world_entries or [],
                source_index=source_index or [],
                extra_body=extra_body,
            )
        except Exception as exc:
            self._remember_remote_error("全书分析三级草案", exc)
            raise

    def analyze_book_level3_finalize(
        self,
        *,
        book_title: str,
        book_outline: str,
        level2_results: list[dict[str, Any]],
        draft_payload: dict[str, Any],
        source_context: dict[str, Any],
        chapters: list[dict[str, Any]],
        characters: list[dict[str, Any]] | None = None,
        world_entries: list[dict[str, Any]] | None = None,
        extra_body: dict[str, Any] | None = None,
        require_remote: bool = True,
    ) -> dict[str, Any]:
        """Finalize level-three analysis with source review results."""
        if require_remote:
            self.require_remote("全书分析三级原文复核")
        if not self.is_remote_configured():
            self.require_remote("全书分析三级原文复核")
        try:
            return self._analyze_book_level3_finalize_remote(
                book_title=book_title,
                book_outline=book_outline,
                level2_results=level2_results,
                draft_payload=draft_payload,
                source_context=source_context,
                chapters=chapters,
                characters=characters or [],
                world_entries=world_entries or [],
                extra_body=extra_body,
            )
        except Exception as exc:
            self._remember_remote_error("全书分析三级原文复核", exc)
            raise

    def analyze_book_one_shot(
        self,
        *,
        book_title: str,
        book_outline: str,
        chapters: list[dict[str, Any]],
        source_blocks: list[dict[str, Any]],
        characters: list[dict[str, Any]] | None = None,
        world_entries: list[dict[str, Any]] | None = None,
        extra_body: dict[str, Any] | None = None,
        require_remote: bool = True,
    ) -> dict[str, Any]:
        """Analyze a short-enough whole book in one long-context JSON request."""
        if require_remote:
            self.require_remote("全书一次性分析")
        if not self.is_remote_configured():
            self.require_remote("全书一次性分析")
        try:
            return self._analyze_book_one_shot_remote(
                book_title=book_title,
                book_outline=book_outline,
                chapters=chapters,
                source_blocks=source_blocks,
                characters=characters or [],
                world_entries=world_entries or [],
                extra_body=extra_body,
            )
        except Exception as exc:
            self._remember_remote_error("全书一次性分析", exc)
            raise

    def _analyze_book_level1_remote(
        self,
        *,
        book_title: str,
        book_outline: str,
        chunk_text: str,
        chunk_index: int,
        total_chunks: int,
        chunk_id: str = "",
        chapter_ids: list[int] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        chapter_ids = chapter_ids or []
        evidence_context = (
            "\n\n【证据输出要求】\n"
            f"- 本片段 chunk_id={chunk_id or f'chunk-{chunk_index:04d}'}，覆盖 chapter_ids={json.dumps(chapter_ids, ensure_ascii=False)}。\n"
            "- 所有事实、人物线索、世界观线索、冲突和疑问都要尽量写入 source_facts。\n"
            "- source_facts 每项字段：fact_id、chapter_id、chunk_id、category、subject、claim、evidence_quote、confidence、uncertainty。\n"
            "- evidence_quote 必须是原文短引或极近似短句；没有证据就写入 uncertainty，不要补成事实。\n"
        )
        prompt = (
            "你正在执行三级全书分析的第一级。请直接解读给定原文片段，尽可能保持原文含义，但要精简。\n"
            "只输出 JSON 对象，不要解释，不要写 Markdown。\n"
            "JSON 字段：\n"
            "- level: 固定为 1\n"
            "- chunk_index: 当前片段序号\n"
            "- total_chunks: 片段总数\n"
            "- faithful_digest: 对原文含义的忠实精简解读，保留关键因果、转折和情绪推进\n"
            "- key_events: 关键事件短句数组\n"
            "- character_clues: 数组，每项 name, role_hint, motivation, change\n"
            "- world_clues: 数组，每项 category, content\n"
            "- chapter_updates: 数组，每项 chapter_id, outline, events\n"
            "不要发明原文没有的信息；不确定时写入 uncertainty 字段。\n\n"
            f"书名：{book_title}\n"
            f"已有书籍级设定：{book_outline[:5000]}\n"
            f"当前片段：{chunk_index}/{total_chunks}\n"
            f"片段内容：\n{chunk_text}"
        )
        prompt += evidence_context
        result = self._post_json_chat_completion(
            messages=[
                {"role": "system", "content": "你是中文长篇小说的第一级忠实解读器，只返回指定 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.15,
            extra_body=extra_body,
            min_max_tokens=BOOK_ANALYSIS_LEVEL1_MAX_TOKENS,
        )
        raw_text = self._chat_completion_content(result, "全书分析一级")
        payload = self._extract_json_object_payload(raw_text)
        payload.setdefault("level", 1)
        payload.setdefault("chunk_index", chunk_index)
        payload.setdefault("total_chunks", total_chunks)
        payload.setdefault("chunk_id", chunk_id or f"chunk-{chunk_index:04d}")
        payload.setdefault("chapter_ids", chapter_ids)
        return payload

    def _analyze_book_level2_remote(
        self,
        *,
        book_title: str,
        level1_results: list[dict[str, Any]],
        group_index: int,
        total_groups: int,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prompt = (
            "你正在执行三级全书分析的第二级。请整合若干个第一级解读结果，概括内容、完善逻辑链条，理解故事走向，"
            "为第三级模板输出做准备。\n"
            "只输出 JSON 对象，不要解释，不要写 Markdown。\n"
            "JSON 字段：\n"
            "- level: 固定为 2\n"
            "- group_index: 当前二级分组序号\n"
            "- total_groups: 二级分组总数\n"
            "- story_summary: 本组故事概括\n"
            "- logic_chain: 因果链条短句数组\n"
            "- timeline: 时间线/阶段推进数组\n"
            "- character_arcs: 数组，每项 name, role, goal, conflict, change, final_state\n"
            "- world_model: 数组，每项 category, rule, evidence\n"
            "- chapter_updates: 数组，每项 chapter_id, outline, events\n"
            "- output_hints: 给第三级填写模板时必须保留的要点数组\n"
            "请控制输出体积：story_summary 800 字以内；logic_chain/timeline 各不超过 12 条；"
            "consolidated_facts 不超过 24 条；chapter_updates 不超过 40 条；不要复述第一级全文。\n"
            "JSON 必须严格合法：数组元素、对象字段之间必须有英文逗号；字符串内不要直接换行。\n"
            "请去重、纠错、合并同名人物和同类设定，但不要创造没有依据的新设定。\n\n"
            f"书名：{book_title}\n"
            f"二级分组：{group_index}/{total_groups}\n"
            f"第一级结果：\n{json.dumps(level1_results, ensure_ascii=False)}"
        )
        prompt += (
            "\n\n【证据保真要求】\n"
            "- 保留一级 source_facts 中的 fact_id、chapter_id、chunk_id、evidence_quote，不要把证据来源抹掉。\n"
            "- 输出 consolidated_facts，每项含 fact_ids、chapter_ids、chunk_ids、claim、evidence_quotes、confidence。\n"
            "- 对冲突信息输出 conflicts；对证据不足但三级需要判断的字段输出 coverage_gaps。\n"
            "- 不要用类型常识补全剧情、人物动机或世界观规则。\n"
        )
        result = self._post_json_chat_completion(
            messages=[
                {"role": "system", "content": "你是中文长篇小说的第二级结构整理器，只返回指定 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.15,
            extra_body=extra_body,
            min_max_tokens=BOOK_ANALYSIS_LEVEL2_MAX_TOKENS,
        )
        raw_text = self._chat_completion_content(result, "全书分析二级")
        payload = self._extract_json_object_payload(raw_text)
        payload.setdefault("level", 2)
        payload.setdefault("group_index", group_index)
        payload.setdefault("total_groups", total_groups)
        return payload

    def _analyze_book_level3_draft_remote(
        self,
        *,
        book_title: str,
        book_outline: str,
        level2_results: list[dict[str, Any]],
        chapters: list[dict[str, Any]],
        characters: list[dict[str, Any]],
        world_entries: list[dict[str, Any]],
        source_index: list[dict[str, Any]] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_index = source_index or []
        chapter_refs = [
            {
                "id": item.get("id"),
                "title": item.get("title", ""),
                "outline": item.get("outline", ""),
            }
            for item in chapters
        ]
        prompt = (
            "你正在执行三级全书分析的第三级。请整合全部第二级结果，完全理解故事，并直接负责最终输出。\n"
            "只输出 JSON 对象，不要解释。最终结果将直接覆盖用户现有书籍级、世界观、人物卡和章节分析字段，"
            "所以请按模板谨慎填写，不要输出空壳。\n"
            "JSON 字段：\n"
            "- book_outline: 字符串，可为 Markdown 补充说明\n"
            "- book_outline_form: 对象，格式为 {fields:{working_title/primary_parent_tag_id/book_description/target_readers/reader_age_band/length_band/serial_status/supplemental_settings/work_intro:{value}}, supplements:[{title,content}]}\n"
            "- world_form: 对象，格式为 {fields:{字段ID:{checked/value}}, supplements:[{title,content}]}\n"
            "- characters: 数组，每项 name, role, profile_form 或 profile_data；必要时可附 profile_text\n"
            "- chapter_updates: 数组，每项 chapter_id, outline, events\n"
            "events 是本章关键事件短标签数组。\n"
            "复选框字段必须明确 checked；文本字段必须明确 value。AI 结果会覆盖旧值，所以不要省略已判断出的字段。\n\n"
            "模板骨架：\n"
            f"【书籍级模板】\n{book_outline_template(book_title)[:2600]}\n\n"
            f"【世界观设定模板】\n{WORLD_TEMPLATE[:2200]}\n\n"
            f"【主角设定模板】\n{PROTAGONIST_TEMPLATE[:2200]}\n\n"
            f"【配角设定模板】\n{SUPPORTING_CHARACTER_TEMPLATE[:1800]}\n\n"
            f"书名：{book_title}\n"
            f"当前书籍级设定：{book_outline[:4000]}\n"
            f"现有人物：{json.dumps(characters[:80], ensure_ascii=False)}\n"
            f"现有世界观：{json.dumps(world_entries[:40], ensure_ascii=False)}\n"
            f"章节索引：{json.dumps(chapter_refs, ensure_ascii=False)}\n"
            f"第二级结果：\n{json.dumps(level2_results, ensure_ascii=False)}"
        )
        prompt += (
            "\n\n【第三级草案与回查要求】\n"
            "- 你现在先产出可写回草案，同时审查证据是否足够；不要把猜测写成模板字段。\n"
            "- 所有写入 book_outline_form、world_form、characters.profile_form、chapter_updates 的字段，都尽量附 evidence_refs 或 source_quotes。\n"
            "- For every writeback evidence item, include source_block_uid/block_uid and evidence_quote/source_quote so the app can verify it against analysis_blocks.\n"
            "- 复选框 checked 只有在二级事实或原文证据明确支持时才为 true；无法判断保持 false 或留空。\n"
            "- 如遇存疑、冲突、证据不足、字段难以判断，请输出 source_requests 数组。\n"
            "- source_requests 每项含 request_id、reason、target_field、chapter_id、chunk_id、keywords。\n"
            "- 无证据但需要人工确认的问题写入 analysis_unresolved，不要写入 Truth/RAG 内容字段。\n"
            f"\n【本次可回查原文索引】\n{json.dumps(source_index[:120], ensure_ascii=False)}"
        )
        result = self._post_json_chat_completion(
            messages=[
                {"role": "system", "content": "你是中文长篇小说项目的第三级终审分析器，只返回最终 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=None,
            extra_body=extra_body,
            min_max_tokens=BOOK_ANALYSIS_LEVEL3_MAX_TOKENS,
        )
        raw_text = self._chat_completion_content(result, "全书分析三级草案")
        payload = self._extract_json_object_payload(raw_text)
        return payload

    def _analyze_book_level3_remote(
        self,
        *,
        book_title: str,
        book_outline: str,
        level2_results: list[dict[str, Any]],
        chapters: list[dict[str, Any]],
        characters: list[dict[str, Any]],
        world_entries: list[dict[str, Any]],
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._analyze_book_level3_draft_remote(
            book_title=book_title,
            book_outline=book_outline,
            level2_results=level2_results,
            chapters=chapters,
            characters=characters,
            world_entries=world_entries,
            source_index=[],
            extra_body=extra_body,
        )

    def _analyze_book_level3_finalize_remote(
        self,
        *,
        book_title: str,
        book_outline: str,
        level2_results: list[dict[str, Any]],
        draft_payload: dict[str, Any],
        source_context: dict[str, Any],
        chapters: list[dict[str, Any]],
        characters: list[dict[str, Any]],
        world_entries: list[dict[str, Any]],
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        chapter_refs = [
            {
                "id": item.get("id"),
                "title": item.get("title", ""),
                "outline": item.get("outline", ""),
            }
            for item in chapters
        ]
        prompt = (
            "你是三级全书分析的最终复核器。请根据二级结果、三级草案和本地回查到的原文片段，输出最终可写回 JSON。\n"
            "只返回 JSON 对象，不要解释，不要 Markdown 包裹。\n"
            "必须遵守：\n"
            "- 字段写入只能来自二级事实或 source_context 原文片段；不要用类型常识、网文套路或模板默认值补空。\n"
            "- 草案中没有证据的字段需要删除或留空；无法解决的问题写入 analysis_unresolved。\n"
            "- 复选框 checked 只有在原文/二级事实明确支持时才为 true。\n"
            "- 人物卡重点核实身份、性格、动机、能力、关系线；世界观重点核实规则、时代、势力、地理、危机；书籍级重点核实分区、读者、年龄、篇幅、连载状态、简介和补充设定。\n"
            "- 输出字段仍为 book_outline、book_outline_form、world_form、characters、chapter_updates、analysis_unresolved。\n"
            "- 每个非空 value 或 checked=true 的字段尽量保留 evidence_refs 或 source_quotes。\n\n"
            "- For every retained evidence item, copy the source_context block_uid and exact quote into source_block_uid/block_uid plus evidence_quote/source_quote.\n\n"
            f"书名：{book_title}\n"
            f"当前书籍级设定：{book_outline[:4000]}\n"
            f"现有人物：{json.dumps(characters[:80], ensure_ascii=False)}\n"
            f"现有世界观：{json.dumps(world_entries[:40], ensure_ascii=False)}\n"
            f"章节索引：{json.dumps(chapter_refs, ensure_ascii=False)}\n"
            f"第二级结果：\n{json.dumps(level2_results, ensure_ascii=False)}\n\n"
            f"三级草案：\n{json.dumps(draft_payload, ensure_ascii=False)}\n\n"
            f"回查原文片段：\n{json.dumps(source_context, ensure_ascii=False)}"
        )
        result = self._post_json_chat_completion(
            messages=[
                {"role": "system", "content": "你是中文长篇小说项目的第三级原文复核与模板精填器，只返回最终 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=None,
            extra_body=extra_body,
            min_max_tokens=BOOK_ANALYSIS_LEVEL3_MAX_TOKENS,
        )
        raw_text = self._chat_completion_content(result, "全书分析三级原文复核")
        payload = self._extract_json_object_payload(raw_text)
        return payload

    def _analyze_book_one_shot_remote(
        self,
        *,
        book_title: str,
        book_outline: str,
        chapters: list[dict[str, Any]],
        source_blocks: list[dict[str, Any]],
        characters: list[dict[str, Any]],
        world_entries: list[dict[str, Any]],
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        chapter_refs = [
            {
                "id": item.get("id"),
                "title": item.get("title", ""),
                "outline": item.get("outline", ""),
            }
            for item in chapters
        ]
        source_payload = [
            {
                "block_uid": item.get("block_uid") or item.get("chunk_id") or "",
                "chunk_id": item.get("chunk_id") or "",
                "chunk_index": item.get("chunk_index", 0),
                "chapter_ids": item.get("chapter_ids") if isinstance(item.get("chapter_ids"), list) else [],
                "chapter_refs": item.get("chapter_refs") if isinstance(item.get("chapter_refs"), list) else [],
                "text": str(item.get("text") or ""),
            }
            for item in source_blocks
        ]
        prompt = (
            "你正在执行一次性全书分析。当前模型已被调用方判定具备 1M+ 上下文，"
            "所以本次会提供完整 source_blocks 原文，不允许截断、概括替代或另行召回。\n"
            "只输出一个有效 JSON 对象，不要输出 Markdown 代码块、解释或额外文本。\n"
            "返回 JSON 必须包含这些顶层字段：\n"
            "- _requires_evidence: true\n"
            "- book_outline: 字符串，可为 Markdown 补充说明\n"
            "- book_outline_form: 对象，格式为 {fields:{字段ID:{value/checked}}, supplements:[{title,content}]}\n"
            "- world_form: 对象，格式为 {fields:{字段ID:{value/checked}}, supplements:[{title,content}]}\n"
            "- characters: 数组，每项包含 name, role, profile_form 或 character_profile_form，可附 profile_text\n"
            "- chapter_updates: 数组，每项包含 chapter_id, outline, events\n"
            "- analysis_unresolved: 数组，记录证据不足、冲突或需要用户人工判断的问题\n"
            "所有可写回字段都必须尽量携带 source_block_uid 或 block_uid，以及 evidence_quote 或 source_quote。"
            "证据短引必须来自本次 source_blocks 原文；证据不足时写入 analysis_unresolved，不要编造。\n"
            "checkbox 字段只有原文明确支持时才 checked=true；文本字段无法判断则留空或省略。\n"
            "DeepSeek JSON Output 兼容要求：本提示明确要求 json，且最终只能返回 json object。\n\n"
            "模板和 schema：\n"
            f"【书籍级 Markdown 模板】\n{book_outline_template(book_title)}\n\n"
            f"【书籍级表单 schema】\n{json.dumps(BOOK_OUTLINE_FORM_SCHEMA, ensure_ascii=False)}\n\n"
            f"【世界观 Markdown 模板】\n{WORLD_TEMPLATE}\n\n"
            f"【世界观表单 schema】\n{json.dumps(WORLD_FORM_SCHEMA, ensure_ascii=False)}\n\n"
            f"【主角 Markdown 模板】\n{PROTAGONIST_TEMPLATE}\n\n"
            f"【主角 profile_form schema】\n{json.dumps(character_profile_schema_for_role('protagonist'), ensure_ascii=False)}\n\n"
            f"【配角 Markdown 模板】\n{SUPPORTING_CHARACTER_TEMPLATE}\n\n"
            f"【配角 profile_form schema】\n{json.dumps(character_profile_schema_for_role('supporting'), ensure_ascii=False)}\n\n"
            f"书名：{book_title}\n"
            f"当前书籍级设定：{book_outline}\n"
            f"现有人物：{json.dumps(characters, ensure_ascii=False)}\n"
            f"现有世界观：{json.dumps(world_entries, ensure_ascii=False)}\n"
            f"章节索引：{json.dumps(chapter_refs, ensure_ascii=False)}\n\n"
            f"完整 source_blocks：\n{json.dumps(source_payload, ensure_ascii=False)}\n\n"
            "示例 json 形状："
            "{\"_requires_evidence\":true,\"book_outline_form\":{\"fields\":{}},"
            "\"world_form\":{\"fields\":{}},\"characters\":[{\"name\":\"\",\"role\":\"\","
            "\"profile_form\":{\"fields\":{}},\"source_block_uid\":\"\",\"evidence_quote\":\"\"}],"
            "\"chapter_updates\":[],\"analysis_unresolved\":[]}"
        )
        result = self._post_json_chat_completion(
            messages=[
                {"role": "system", "content": "你是中文长篇小说项目的一次性全书分析器，只返回最终 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=None,
            extra_body=extra_body,
            min_max_tokens=BOOK_ANALYSIS_LEVEL3_MAX_TOKENS,
        )
        _raise_if_chat_completion_truncated(result, "全书一次性分析")
        raw_text = self._chat_completion_content(result, "全书一次性分析")
        payload = self._extract_json_object_payload(raw_text)
        if not payload:
            raise RuntimeError("全书一次性分析返回的 JSON 为空")
        payload.setdefault("_requires_evidence", True)
        return payload

    def _analyze_book_remote(
        self,
        *,
        book_title: str,
        book_outline: str,
        chapters: list[dict[str, Any]],
        characters: list[dict[str, Any]],
        world_entries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        overhead = len(book_title) + len(book_outline) + len(json.dumps(characters[:40], ensure_ascii=False)) + len(json.dumps(world_entries[:40], ensure_ascii=False)) + 3000
        available = max(1000, MAX_BOOK_ANALYSIS_INPUT_CHARS - overhead)
        max_chapters = min(len(chapters), 80)
        per_chapter_limit = max(500, min(2200, available // max(1, max_chapters)))
        chapter_payload = []
        for item in chapters[:max_chapters]:
            chapter_payload.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title", ""),
                    "outline": item.get("outline", ""),
                    "content": str(item.get("content", ""))[:per_chapter_limit],
                }
            )
        prompt = (
            "请分析这部长篇小说项目，只输出 JSON 对象，不要解释。\n"
            "JSON 字段：\n"
            "- book_outline: 字符串，必须是 Markdown，并按照【书籍级模板】补全；用户已填写的字段要作为硬约束保留\n"
            "- book_outline_form: 可选对象，格式为 {fields:{working_title/primary_parent_tag_id/book_description/target_readers/reader_age_band/length_band/serial_status/supplemental_settings/work_intro:{value}}, supplements:[{title,content}]}；只填写高置信度字段\n"
            "- world_form: 可选对象，格式为 {fields:{字段ID:{checked/value}}, supplements:[{title,content}]}；只填写高置信度字段\n"
            "- characters: 数组，每项 name, role, profile_text；profile_text 必须是 Markdown，主角按【主角设定模板】，其他人物按【配角设定模板】补全\n"
            "- world_entries: 兼容字段，可为空；优先使用 world_form 表达世界观\n"
            "- chapter_updates: 数组，每项 chapter_id, outline, events\n"
            "events 是本章关键事件短标签数组。\n\n"
            "模板骨架：\n"
            f"【书籍级模板】\n{book_outline_template(book_title)[:2600]}\n\n"
            f"【世界观设定模板】\n{WORLD_TEMPLATE[:2200]}\n\n"
            f"【主角设定模板】\n{PROTAGONIST_TEMPLATE[:2200]}\n\n"
            f"【配角设定模板】\n{SUPPORTING_CHARACTER_TEMPLATE[:1800]}\n\n"
            f"书名：{book_title}\n"
            f"书籍大纲：{book_outline[:4000]}\n"
            f"现有人物：{json.dumps(characters[:40], ensure_ascii=False)}\n"
            f"现有世界观：{json.dumps(world_entries[:40], ensure_ascii=False)}\n"
            f"章节：{json.dumps(chapter_payload, ensure_ascii=False)}"
        )
        result = self._post_json_chat_completion(
            messages=[
                {"role": "system", "content": "你是中文长篇小说项目分析器，擅长抽取人物、世界观、章节大纲和关键事件，只返回 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.25,
            min_max_tokens=BOOK_ANALYSIS_LEVEL3_MAX_TOKENS,
        )
        raw_text = self._chat_completion_content(result, "全书分析")
        payload = self._extract_json_object_payload(raw_text)
        return payload

    def _analyze_book_mock(
        self,
        book_title: str,
        book_outline: str,
        chapters: list[dict[str, Any]],
        characters: list[dict[str, Any]],
        world_entries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        chapter_updates: list[dict[str, Any]] = []
        outline_lines = [f"全书分析：{book_title or '未命名作品'}"]
        if book_outline.strip():
            outline_lines.append(book_outline.strip()[:600])
        outline_lines.append(f"规模：{len(chapters)} 章")
        for item in chapters[:80]:
            content = str(item.get("content", ""))
            outline = str(item.get("outline", "")).strip()
            if not outline:
                first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
                outline = f"本章围绕「{first_line[:36] or item.get('title', '章节')}」推进。"
            outline_lines.append(f"- {item.get('title', '章节')}：{outline.splitlines()[0][:80]}")
            chapter_updates.append(
                {
                    "chapter_id": item.get("id"),
                    "outline": outline,
                    "events": [str(item.get("title", "章节"))[:24]],
                }
            )
        return {
            "book_outline": "\n".join(outline_lines[:90]),
            "characters": characters,
            "world_entries": world_entries,
            "chapter_updates": chapter_updates,
        }


def _raise_if_chat_completion_truncated(result: dict[str, Any], purpose: str) -> None:
    choices = result.get("choices") if isinstance(result, dict) else None
    if not isinstance(choices, list) or not choices:
        return
    first = choices[0]
    if not isinstance(first, dict):
        return
    finish_reason = str(first.get("finish_reason") or "").strip().lower()
    if finish_reason == "length":
        raise RuntimeError(f"{purpose}失败：AI 返回被 max_tokens 截断")
