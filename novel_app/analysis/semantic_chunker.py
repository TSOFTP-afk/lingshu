from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from novel_app.analysis.schemas_v3 import SemanticBlock, stable_hash

logger = logging.getLogger(__name__)

SEMANTIC_CHUNKER_VERSION = "semantic_chunker_v1"

# M1 语义分块 AI 边界调整的并发上限
# 默认 6：DeepSeek API 并发友好值；可通过环境变量覆盖
CHUNK_AI_MAX_WORKERS = int(os.environ.get("LINGSHU_CHUNK_AI_MAX_WORKERS", "6") or 6)


@dataclass(frozen=True)
class TextSpan:
    start: int
    end: int
    text: str
    reason: str


class SemanticChunker:
    def __init__(
        self,
        *,
        target_chars: int = 6000,
        max_chars: int = 8000,
        min_sentence_cut_chars: int = 1200,
        overlap_sentences: int = 1,
        use_ai: bool = False,
        ai_provider: Any = None,
    ) -> None:
        self.target_chars = max(1, int(target_chars))
        self.max_chars = max(self.target_chars, int(max_chars))
        self.min_sentence_cut_chars = max(200, int(min_sentence_cut_chars))
        self.overlap_sentences = max(0, int(overlap_sentences))
        self.use_ai = bool(use_ai)
        self.ai_provider = ai_provider
        # 记录实际使用的引擎："ai_assisted" / "rule"
        self._last_engine: str = "rule"

    def chunk_chapters(
        self,
        book_id: int,
        chapters: list[dict[str, Any]],
        *,
        pipeline_version: str,
        use_ai: bool = False,
        ai_provider: Any = None,
    ) -> list[SemanticBlock]:
        # 优先使用方法参数，fallback 到实例属性
        effective_use_ai = use_ai or self.use_ai
        effective_ai_provider = ai_provider if ai_provider is not None else self.ai_provider
        self._last_engine = "rule"

        # 第一步：所有章节快速跑规则分块（纯本地，毫秒级）
        # 同时收集需要 AI 调整的章节任务
        chapter_tasks: list[tuple[int, dict[str, Any], str, list[TextSpan], str]] = []
        # 结构：(原始章节索引, chapter, content, rule_spans, chapter_content_hash)
        for chapter in chapters:
            chapter_id = self._int_or_none(chapter.get("id"))
            title = str(chapter.get("title") or "")
            content = str(chapter.get("content") or "")
            if not content.strip():
                continue
            chapter_content_hash = stable_hash(content)
            rule_spans = self._chapter_spans(content)
            chapter_tasks.append((len(chapter_tasks), chapter, content, rule_spans, chapter_content_hash))

        if not chapter_tasks:
            return []

        # 第二步：并发执行 AI 边界调整（仅 AI 模式）
        # 按 chapter 原始索引存储调整后的 spans，保持章节顺序
        adjusted_spans: dict[int, list[TextSpan]] = {}
        if effective_use_ai and effective_ai_provider is not None:
            worker_count = max(1, min(len(chapter_tasks), CHUNK_AI_MAX_WORKERS))
            logger.info(
                "M1 语义分块 AI 边界调整: %d 章节, %d 并发 worker",
                len(chapter_tasks), worker_count,
            )

            def _adjust_one(task_tuple: tuple[int, dict[str, Any], str, list[TextSpan], str]) -> tuple[int, list[TextSpan]]:
                idx, _chapter, chap_content, chap_rule_spans, _hash = task_tuple
                try:
                    ai_spans = self._ai_adjust_spans(
                        content=chap_content,
                        rule_spans=chap_rule_spans,
                        ai_provider=effective_ai_provider,
                        book_id=book_id,
                    )
                    if ai_spans:
                        return idx, ai_spans
                    return idx, chap_rule_spans  # AI 失败回退规则
                except Exception as exc:
                    logger.warning("M1 AI 边界调整失败 chapter_idx=%d: %s", idx, exc)
                    return idx, chap_rule_spans  # 异常回退规则

            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="chunk-ai") as executor:
                futures = [executor.submit(_adjust_one, task) for task in chapter_tasks]
                for future in as_completed(futures):
                    idx, spans = future.result()
                    adjusted_spans[idx] = spans
                    if any(s.reason == "ai_adjusted" for s in spans):
                        self._last_engine = "ai_assisted"
        else:
            # 非模式：直接用规则分块
            for idx, _chap, _content, chap_rule_spans, _hash in chapter_tasks:
                adjusted_spans[idx] = chap_rule_spans

        # 第三步：按章节顺序构建 SemanticBlock（chunk_index 全局递增）
        blocks: list[SemanticBlock] = []
        for idx, chapter, _content, _rule_spans, chapter_content_hash in chapter_tasks:
            chapter_id = self._int_or_none(chapter.get("id"))
            title = str(chapter.get("title") or "")
            spans = adjusted_spans.get(idx, _rule_spans)
            local_index = 1
            for span in spans:
                block = SemanticBlock.from_text_span(
                    book_id=book_id,
                    chapter_id=chapter_id,
                    chapter_title=title,
                    local_index=local_index,
                    chunk_index=len(blocks) + 1,
                    char_start=span.start,
                    char_end=span.end,
                    text=span.text,
                    pipeline_version=pipeline_version,
                    split_reason=span.reason,
                    chapter_content_hash=chapter_content_hash,
                )
                blocks.append(block)
                local_index += 1

        # 句子级重叠窗口：为每个 block 添加前一个 block 末尾的 overlap_sentences 个句子
        if self.overlap_sentences > 0 and len(blocks) > 1:
            blocks = self._apply_overlap_window(blocks)

        return blocks

    def _ai_adjust_spans(
        self,
        *,
        content: str,
        rule_spans: list[TextSpan],
        ai_provider: Any,
        book_id: int,
    ) -> list[TextSpan]:
        """调用 AI 微调规则分块的边界。

        AI 仅调整边界位置，不改变分块的基本结构。失败或返回无效结果时返回空列表，
        由调用方回退到规则分块结果。
        """
        if not rule_spans or not ai_provider:
            return []
        try:
            candidate_boundaries = [span.start for span in rule_spans]
            if 0 not in candidate_boundaries:
                candidate_boundaries.insert(0, 0)

            ai_boundaries = ai_provider.semantic_chunk(
                text=content,
                candidate_boundaries=candidate_boundaries,
                book_id=book_id,
                run_id=0,
            )
            if not ai_boundaries:
                return []

            text_len = len(content)
            safe_boundaries = sorted({
                int(b) for b in ai_boundaries if 0 <= int(b) <= text_len
            })
            if 0 not in safe_boundaries:
                safe_boundaries.insert(0, 0)
            if text_len not in safe_boundaries:
                safe_boundaries.append(text_len)

            # 边界数量太少则视为无效
            if len(safe_boundaries) < 2:
                return []

            spans: list[TextSpan] = []
            for i in range(len(safe_boundaries) - 1):
                start = safe_boundaries[i]
                end = safe_boundaries[i + 1]
                if end - start > self.max_chars:
                    # 超长块用规则切分，避免破坏后续流程
                    spans.extend(self._split_long_span(content, start, end))
                else:
                    spans.extend(self._finalize_span(content, start, end, "ai_adjusted"))

            if not spans:
                return []
            return spans
        except Exception:
            # AI 调用失败时回退到规则分块，不中断流水线
            return []

    def _chapter_spans(self, content: str) -> list[TextSpan]:
        source = str(content or "")
        scene_spans = self._scene_spans(source)
        blocks: list[TextSpan] = []
        for scene in scene_spans:
            pieces = self._paragraph_spans(source, scene.start, scene.end)
            if not pieces:
                continue
            current: list[TextSpan] = []

            def flush(reason: str) -> None:
                nonlocal current
                if not current:
                    return
                start = current[0].start
                end = current[-1].end
                blocks.extend(self._finalize_span(source, start, end, reason))
                current = []

            for piece in pieces:
                if len(piece.text) > self.max_chars:
                    flush("paragraph_boundary")
                    blocks.extend(self._split_long_span(source, piece.start, piece.end))
                    continue
                candidate_len = piece.end - current[0].start if current else len(piece.text)
                if current and candidate_len > self.target_chars:
                    flush("paragraph_boundary")
                current.append(piece)
            flush("scene_boundary" if scene.reason == "scene_separator" else "paragraph_boundary")
        return blocks

    def _scene_spans(self, text: str) -> list[TextSpan]:
        separators = list(re.finditer(r"(?m)^\s*(?:[-*_=\u2014]{3,}|#{3,}|第[一二三四五六七八九十百千万\d]+幕)\s*$", text))
        if not separators:
            return self._finalize_span(text, 0, len(text), "chapter")

        spans: list[TextSpan] = []
        cursor = 0
        for match in separators:
            spans.extend(self._finalize_span(text, cursor, match.start(), "scene_separator"))
            cursor = match.end()
        spans.extend(self._finalize_span(text, cursor, len(text), "scene_separator"))
        return spans

    def _paragraph_spans(self, text: str, start: int, end: int) -> list[TextSpan]:
        segment = text[start:end]
        spans: list[TextSpan] = []
        for match in re.finditer(r"\S(?:.*?)(?=(?:\r?\n\s*\r?\n)|\Z)", segment, flags=re.DOTALL):
            span_start = start + match.start()
            span_end = start + match.end()
            spans.extend(self._finalize_span(text, span_start, span_end, "paragraph"))
        return spans

    def _split_long_span(self, text: str, start: int, end: int) -> list[TextSpan]:
        spans: list[TextSpan] = []
        cursor = start
        while cursor < end:
            remaining = end - cursor
            if remaining <= self.max_chars:
                spans.extend(self._finalize_span(text, cursor, end, "sentence_boundary"))
                break
            cut = self._sentence_cut(text, cursor, min(end, cursor + self.max_chars))
            if cut <= cursor:
                cut = min(end, cursor + self.max_chars)
                reason = "hard_limit"
            else:
                reason = "sentence_boundary"
            spans.extend(self._finalize_span(text, cursor, cut, reason))
            cursor = cut
        return spans

    def _sentence_cut(self, text: str, start: int, hard_end: int) -> int:
        window = text[start:hard_end]
        cut = -1
        for mark in ("。", "！", "？", ".", "!", "?", "\n"):
            cut = max(cut, window.rfind(mark))
        if cut < self.min_sentence_cut_chars:
            return -1
        return start + cut + 1

    @staticmethod
    def _finalize_span(text: str, start: int, end: int, reason: str) -> list[TextSpan]:
        start = max(0, int(start))
        end = max(start, int(end))
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start >= end:
            return []
        return [TextSpan(start=start, end=end, text=text[start:end], reason=reason)]

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _apply_overlap_window(self, blocks: list[SemanticBlock]) -> list[SemanticBlock]:
        """为每个 block 添加前一个 block 末尾的 overlap_sentences 个句子作为重叠上下文。

        重叠文本存储在 block.metadata["overlap_prefix"] 中，
        不修改 block 的 char_start/char_end/content_hash，以保持幂等性。
        """
        result: list[SemanticBlock] = [blocks[0]]
        for i in range(1, len(blocks)):
            prev_text = str(blocks[i - 1].text or "")
            overlap_text = self._extract_trailing_sentences(prev_text, self.overlap_sentences)
            if overlap_text:
                new_metadata = dict(blocks[i].metadata or {})
                new_metadata["overlap_prefix"] = overlap_text
                new_metadata["overlap_source_block_uid"] = blocks[i - 1].block_uid
                new_block = SemanticBlock(
                    book_id=blocks[i].book_id,
                    block_uid=blocks[i].block_uid,
                    chunk_id=blocks[i].chunk_id,
                    chunk_index=blocks[i].chunk_index,
                    chapter_id=blocks[i].chapter_id,
                    chapter_title=blocks[i].chapter_title,
                    char_start=blocks[i].char_start,
                    char_end=blocks[i].char_end,
                    text=blocks[i].text,
                    content_hash=blocks[i].content_hash,
                    structure_hash=blocks[i].structure_hash,
                    pipeline_version=blocks[i].pipeline_version,
                    metadata=new_metadata,
                )
                result.append(new_block)
            else:
                result.append(blocks[i])
        return result

    @staticmethod
    def _extract_trailing_sentences(text: str, count: int) -> str:
        """从文本末尾提取最后 count 个句子。"""
        if not text or count <= 0:
            return ""
        # 按中文/英文句号、感叹号、问号分句
        sentences = re.split(r"(?<=[。！？.!?])", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return ""
        trailing = sentences[-count:]
        return "".join(trailing)
