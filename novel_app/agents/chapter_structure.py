from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from novel_app.json_utils import extract_json_object

SMART_IMPORT_ANALYSIS_CHUNK_CHARS = 100_000
SMART_IMPORT_BOUNDARY_CONTEXT_CHARS = 9_000
SEGMENT_TARGET_CHARS = SMART_IMPORT_ANALYSIS_CHUNK_CHARS


class ChapterStructureAgent:
    """Detect volume/chapter heading lines for smart import."""

    def __init__(self, post_chat: Callable[..., dict[str, Any]]) -> None:
        self._post_chat = post_chat

    def detect(self, text: str) -> list[dict[str, Any]]:
        structures: list[Any] = []
        for segment_text, line_offset in self._iter_detection_segments(text):
            for catalog in self._build_line_catalog_batches(segment_text):
                for item in self._detect_batch(catalog):
                    if isinstance(item, dict):
                        adjusted = dict(item)
                        try:
                            raw_line_number = adjusted.get("line_number", adjusted.get("line", 0))
                            adjusted["line_number"] = int(raw_line_number or 0) + line_offset
                        except (TypeError, ValueError):
                            adjusted["line_number"] = 0
                        structures.append(adjusted)
                    else:
                        structures.append(item)
        return self._normalize_items(structures)

    @classmethod
    def _iter_detection_segments(
        cls,
        text: str,
        max_chars: int = SMART_IMPORT_ANALYSIS_CHUNK_CHARS,
        boundary_context_chars: int = SMART_IMPORT_BOUNDARY_CONTEXT_CHARS,
    ) -> list[tuple[str, int]]:
        segments = cls._iter_analysis_segments(text, max_chars=max_chars)
        segments.extend(
            cls._iter_boundary_probe_segments(
                text,
                max_chars=max_chars,
                context_chars=boundary_context_chars,
            )
        )
        seen: set[tuple[str, int]] = set()
        unique: list[tuple[str, int]] = []
        for segment, offset in segments:
            key = (segment, offset)
            if key in seen:
                continue
            seen.add(key)
            unique.append((segment, offset))
        return unique

    @staticmethod
    def _iter_analysis_segments(
        text: str,
        max_chars: int = SMART_IMPORT_ANALYSIS_CHUNK_CHARS,
    ) -> list[tuple[str, int]]:
        normalized = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
        if len(normalized) <= max_chars:
            return [(normalized, 0)] if normalized.strip() else []
        segments: list[tuple[str, int]] = []
        current: list[str] = []
        current_chars = 0
        start_line_number = 1
        for line_number, line in enumerate(normalized.split("\n"), start=1):
            line_size = len(line) + 1
            if len(line) > max_chars:
                if current:
                    segments.append(("\n".join(current), start_line_number - 1))
                    current = []
                    current_chars = 0
                chunks = [line[start : start + max_chars] for start in range(0, len(line), max_chars)]
                if len(chunks) > 1 and 0 < len(chunks[-1]) <= 120:
                    borrow = 121 - len(chunks[-1])
                    if len(chunks[-2]) - borrow > 120:
                        chunks[-1] = chunks[-2][-borrow:] + chunks[-1]
                        chunks[-2] = chunks[-2][:-borrow]
                for chunk in chunks:
                    if chunk.strip():
                        segments.append((chunk, line_number - 1))
                start_line_number = line_number + 1
                continue
            if current and current_chars + line_size > max_chars:
                segments.append(("\n".join(current), start_line_number - 1))
                current = []
                current_chars = 0
                start_line_number = line_number
            if not current:
                start_line_number = line_number
            current.append(line)
            current_chars += line_size
        if current:
            segments.append(("\n".join(current), start_line_number - 1))
        return [(segment, offset) for segment, offset in segments if segment.strip()]

    @staticmethod
    def _iter_boundary_probe_segments(
        text: str,
        max_chars: int = SMART_IMPORT_ANALYSIS_CHUNK_CHARS,
        context_chars: int = SMART_IMPORT_BOUNDARY_CONTEXT_CHARS,
    ) -> list[tuple[str, int]]:
        normalized = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
        if len(normalized) <= max_chars or context_chars <= 0:
            return []
        probes: list[tuple[str, int]] = []
        seen_windows: set[tuple[int, int]] = set()
        for boundary in range(max_chars, len(normalized), max_chars):
            start_hint = max(0, boundary - context_chars)
            end_hint = min(len(normalized), boundary + context_chars)
            start = normalized.rfind("\n", 0, start_hint) + 1
            end_newline = normalized.find("\n", end_hint)
            end = len(normalized) if end_newline < 0 else end_newline
            if end - start > max_chars:
                start = start_hint
                end = end_hint
                if end - start > max_chars:
                    half = max_chars // 2
                    start = max(0, boundary - half)
                    end = min(len(normalized), start + max_chars)
            if end <= start:
                continue
            if not ChapterStructureAgent._window_has_catalog_lines_on_both_sides(
                normalized,
                start,
                end,
                boundary,
            ):
                continue
            key = (start, end)
            if key in seen_windows:
                continue
            segment = normalized[start:end]
            if not segment.strip():
                continue
            seen_windows.add(key)
            probes.append((segment, normalized.count("\n", 0, start)))
        return probes

    @staticmethod
    def _window_has_catalog_lines_on_both_sides(text: str, start: int, end: int, boundary: int) -> bool:
        def has_catalog_line(part: str) -> bool:
            for raw_line in part.split("\n"):
                line = re.sub(r"\s+", " ", raw_line.strip())
                if 0 < len(line) <= 120:
                    return True
            return False

        return has_catalog_line(text[start:boundary]) and has_catalog_line(text[boundary:end])

    def _detect_batch(self, catalog: str) -> list[Any]:
        valid_line_numbers = {
            int(match.group(1))
            for match in re.finditer(r"(?m)^(\d+):\s+", catalog)
        }
        prompt = (
            "请从下面的中文长篇小说文本行目录中识别真实卷/章结构。\n"
            "只返回 JSON，不要解释。JSON 格式：\n"
            "{\"structure\":[{\"kind\":\"volume|chapter\",\"line_number\":1,\"title\":\"标题\",\"chapter_type\":\"正文|番外|作者的话\"}]}\n"
            "规则：\n"
            "- line_number 必须使用行目录左侧的原始行号，且为 1-based。\n"
            "- volume 表示卷/部/篇/集标题，例如“第一卷”“第2卷”。volume 的 chapter_type 固定为“正文”。\n"
            "- chapter 表示章节标题，例如“第一章”“第12章”“序章”“番外”。\n"
            "- chapter_type 分类规则：\n"
            "  - “番外”：标题含“番外”“番篇”“外传”“外篇”“特别篇”“短篇”“Side Story”等关键词\n"
            "  - “作者的话”：标题含“作者的话”“作者寄语”“后记”“写在后面”“写在最后”“结语”“感言”“致谢”等关键词\n"
            "  - “正文”：其他所有章节（含序章、楔子、尾声等叙事章节）\n"
            "- 只标记独立成行的结构标题，不要把正文句子、目录说明、人物设定项当章节。\n"
            "- 如果没有可靠章节结构，返回 {\"structure\":[]}。\n\n"
            f"行目录：\n{catalog}"
        )
        result = self._post_chat(
            messages=[
                {
                    "role": "system",
                    "content": "你是长篇小说导入结构识别智能体，只负责找卷/章标题行并返回 JSON。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.05,
        )
        raw = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        payload = extract_json_object(raw)
        items = payload.get("structure", [])
        if not isinstance(items, list):
            return []
        filtered: list[Any] = []
        for item in items:
            if not isinstance(item, dict):
                filtered.append(item)
                continue
            try:
                line_number = int(item.get("line_number", item.get("line", 0)) or 0)
            except (TypeError, ValueError):
                continue
            if line_number in valid_line_numbers:
                filtered.append(item)
        return filtered

    @staticmethod
    def _build_line_catalog_batches(
        text: str,
        max_lines: int = 2200,
        max_chars: int = 48000,
        max_batches: int = 12,
    ) -> list[str]:
        lines = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        batches: list[str] = []
        current: list[str] = []
        total_chars = 0
        for line_number, raw_line in enumerate(lines, start=1):
            line = re.sub(r"\s+", " ", raw_line.strip())
            if not line:
                continue
            if len(line) > 120:
                continue
            entry = f"{line_number}: {line}"
            if current and (total_chars + len(entry) + 1 > max_chars or len(current) >= max_lines):
                batches.append("\n".join(current))
                if len(batches) >= max_batches:
                    return batches
                current = []
                total_chars = 0
            current.append(entry)
            total_chars += len(entry) + 1
        if current and len(batches) < max_batches:
            batches.append("\n".join(current))
        return batches

    @staticmethod
    def _build_line_catalog(text: str, max_lines: int = 2200, max_chars: int = 48000) -> str:
        batches = ChapterStructureAgent._build_line_catalog_batches(
            text,
            max_lines=max_lines,
            max_chars=max_chars,
            max_batches=1,
        )
        return batches[0] if batches else ""

    @staticmethod
    def _normalize_items(items: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "") or "").strip().lower()
            if kind not in {"volume", "chapter"}:
                continue
            try:
                line_number = int(item.get("line_number", item.get("line", 0)) or 0)
            except (TypeError, ValueError):
                continue
            if line_number <= 0:
                continue
            title = str(item.get("title", "") or "").strip()
            if not title:
                continue
            key = (kind, line_number)
            if key in seen:
                continue
            seen.add(key)
            normalized_item = {"kind": kind, "line_number": line_number, "title": title[:120]}
            if "chapter_type" in item:
                chapter_type = str(item.get("chapter_type", "") or "").strip()
                if chapter_type in ("正文", "番外", "作者的话"):
                    normalized_item["chapter_type"] = chapter_type
            normalized.append(normalized_item)
        normalized.sort(key=lambda item: (int(item["line_number"]), 0 if item["kind"] == "volume" else 1))
        return normalized

    @staticmethod
    def _segment_text(
        text: str,
        target_chars: int = SEGMENT_TARGET_CHARS,
    ) -> list[tuple[str, int]]:
        """将文本按约 target_chars 字符在自然段落边界处弹性分段。

        返回列表，每项为 (segment_text, line_offset)，line_offset 为该段在原文中的起始行号偏移。
        """
        normalized = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
        if len(normalized) <= target_chars:
            return [(normalized, 0)] if normalized.strip() else []

        lines = normalized.split("\n")
        segments: list[tuple[str, int]] = []
        current_lines: list[str] = []
        current_chars = 0
        start_line = 0

        for i, line in enumerate(lines):
            line_size = len(line) + 1
            # 当累计字符超过目标大小，且当前行为空行或短行（可能是标题行）时切分
            if current_chars + line_size > target_chars and current_lines:
                # 寻找最近的空行或短行作为切分点
                split_index = len(current_lines)
                for j in range(len(current_lines) - 1, max(0, len(current_lines) - 50), -1):
                    stripped = current_lines[j].strip()
                    if not stripped or (len(stripped) <= 100 and stripped):
                        split_index = j + 1
                        break

                segment_lines = current_lines[:split_index]
                segment_text = "\n".join(segment_lines)
                if segment_text.strip():
                    segments.append((segment_text, start_line))

                remaining_lines = current_lines[split_index:]
                current_lines = remaining_lines + [line]
                current_chars = sum(len(current_line) + 1 for current_line in current_lines)
                start_line = start_line + split_index
            else:
                if not current_lines:
                    start_line = i
                current_lines.append(line)
                current_chars += line_size

        if current_lines:
            segment_text = "\n".join(current_lines)
            if segment_text.strip():
                segments.append((segment_text, start_line))

        return segments

    @staticmethod
    def _merge_segment_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """合并多段检测结果，处理行号偏移和边界去重。"""
        if not items:
            return []
        # Sort by line_number
        sorted_items = sorted(items, key=lambda x: (int(x.get("line_number", 0)), 0 if x.get("kind") == "volume" else 1))
        # Deduplicate: same kind + same title + close line numbers (within 5 lines)
        seen: set[tuple[str, str]] = set()
        merged: list[dict[str, Any]] = []
        for item in sorted_items:
            kind = str(item.get("kind", ""))
            title = str(item.get("title", ""))
            key = (kind, title)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged

    def review_catalog(
        self,
        catalog_summary: str,
        total_chapters: int,
    ) -> list[dict[str, Any]]:
        """校验正则解析得到的目录是否合理，返回可疑章节区间。

        :param catalog_summary: ``build_catalog_summary`` 生成的目录摘要
        :param total_chapters: 章节总数
        :return: ``[{"start_chapter": int, "end_chapter": int, "reason": str}, ...]``

        AI 只负责指出可疑的章节序号区间，不负责重新解析。
        """
        prompt = (
            "你是长篇小说导入结构校验智能体。下面是正则解析得到的小说目录摘要，\n"
            "格式为：序号|字数|卷|类型|标题\n\n"
            f"全书共 {total_chapters} 章。请检查目录是否存在以下问题：\n"
            "- 某些章节字数异常（过短如<200字，可能是误切分；或异常长>10000字，可能是漏切分）\n"
            "- 标题看起来不像章节标题（是正文句子被误识别为标题）\n"
            "- 章节序号不连续或标题重复\n"
            "- 缺少章节（一大段文本没有切分）\n\n"
            "只返回 JSON，不要解释。JSON 格式：\n"
            '{"issues":[{"start_chapter":85,"end_chapter":90,"reason":"第85-90章字数仅100-300字，可能被误切分"}, ...]}\n\n'
            "规则：\n"
            "- start_chapter 和 end_chapter 使用目录摘要中的序号（1-based, 含两端）\n"
            "- end_chapter >= start_chapter\n"
            "- 把连续的异常章节合并为一个区间\n"
            "- 只报告真正可疑的区域，不要把正常的章节标为问题\n"
            '- 如果目录看起来正常，返回 {"issues":[]}\n'
            "- 最多报告 10 个问题区域\n\n"
            f"目录摘要：\n{catalog_summary}"
        )
        result = self._post_chat(
            messages=[
                {
                    "role": "system",
                    "content": "你是小说导入结构校验智能体，只负责检查目录问题并返回 JSON。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.05,
        )
        raw = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        payload = extract_json_object(raw)
        issues = payload.get("issues", [])
        if not isinstance(issues, list):
            return []
        # 过滤有效项
        valid: list[dict[str, Any]] = []
        for item in issues[:10]:
            if not isinstance(item, dict):
                continue
            try:
                start_chapter = int(item.get("start_chapter", 0) or 0)
                end_chapter = int(item.get("end_chapter", start_chapter) or start_chapter)
            except (TypeError, ValueError):
                continue
            if start_chapter <= 0:
                continue
            if end_chapter < start_chapter:
                end_chapter = start_chapter
            valid.append({
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
                "reason": str(item.get("reason", "") or "")[:200],
            })
        return valid
