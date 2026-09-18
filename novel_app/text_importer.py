from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedChapter:
    title: str
    content: str
    outline: str
    volume_title: str | None = None
    chapter_type: str = "正文"
    start_line: int = 0  # 章节在原文中的起始行号（1-based），用于 AI 校验定位


@dataclass(frozen=True)
class ParsedBook:
    title: str
    outline: str
    chapters: list[ParsedChapter]


_CN_NUM = r"\d零〇一二两三四五六七八九十百千万"
_VOLUME_RE = re.compile(
    rf"^\s*第\s*[{_CN_NUM}]+\s*卷(?:\s+\S.*|[：:·、.．\-—_]\s*\S.*)?\s*$",
    re.IGNORECASE,
)
_STRONG_CHAPTER_RE = re.compile(
    rf"^\s*(第\s*[{_CN_NUM}]+\s*[章节回]|章节\s*\d+|Chapter\s+\d+|序章|楔子|尾声|番外)(?:\s+.*|[：:·、.．\-—_].*)?$",
    re.IGNORECASE,
)
_ACT_RE = re.compile(
    rf"^\s*第\s*[{_CN_NUM}]+\s*幕(?:\s+.*|[：:·、.．\-—_].*)?$",
    re.IGNORECASE,
)
_PIPE_SECTION_RE = re.compile(
    rf"^\s*[|｜]\s*[{_CN_NUM}]+\s*[|｜]\s*\S+.*$",
    re.IGNORECASE,
)
_NUMBERED_SECTION_RE = re.compile(
    r"^\s*\d+\s*[.．、]\s*\S+.*$",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"(?<=[。！？!?；;])\s*")
SMART_IMPORT_PREFIX_CHARS = 300_000

# 章节类型推断关键词
_EXTRA_KEYWORDS = re.compile(r"番外|番篇|外传|外篇|特别篇|短篇|Side\s*Story", re.IGNORECASE)
_AUTHOR_KEYWORDS = re.compile(r"作者的话|作者寄语|后记|写在后面|写在最后|结语|感言|致谢|尾声寄语", re.IGNORECASE)


def _infer_chapter_type(title: str) -> str:
    """根据章节标题关键词推断章节类型。"""
    if _AUTHOR_KEYWORDS.search(title):
        return "作者的话"
    if _EXTRA_KEYWORDS.search(title):
        return "番外"
    return "正文"


def parse_long_text(
    book_title: str,
    raw_text: str,
    chapter_structure: list[dict[str, Any]] | None = None,
    use_local_headings: bool = True,
) -> ParsedBook:
    text = _normalize_text(raw_text)
    if not text:
        return ParsedBook(title=book_title.strip() or "未命名导入作品", outline="", chapters=[])

    chapters: list[ParsedChapter]
    explicit_chapter_count = 0
    if chapter_structure:
        chapters = _parse_by_detected_structure(text, chapter_structure)
        explicit_chapter_count = len(chapters)
        if not chapters and not use_local_headings:
            chapters = [ParsedChapter(title="第1章", content=text.strip(), outline="", volume_title=None)]
    elif use_local_headings:
        chapters, explicit_chapter_count = _parse_by_headings(text)
    else:
        chapters = [ParsedChapter(title="第1章", content=text.strip(), outline="", volume_title=None)]
    if explicit_chapter_count == 0:
        chapters = _chunk_implicit_chapters(chapters)

    normalized_chapters = [_normalize_imported_chapter(chapter) for chapter in chapters if chapter.content.strip()]
    return ParsedBook(
        title=book_title.strip() or "未命名导入作品",
        outline=_extract_book_outline(book_title, normalized_chapters),
        chapters=normalized_chapters,
    )


def _parse_by_detected_structure(text: str, chapter_structure: list[dict[str, Any]]) -> list[ParsedChapter]:
    markers = _normalize_structure_markers(chapter_structure)
    if not any(marker["kind"] == "chapter" for marker in markers):
        return []

    markers_by_line: dict[int, list[dict[str, Any]]] = {}
    for marker in markers:
        markers_by_line.setdefault(int(marker["line_number"]), []).append(marker)

    chapters: list[ParsedChapter] = []
    current_volume: str | None = None
    current_title: str | None = None
    buffer: list[str] = []
    leading_buffer: list[str] = []
    first_chapter_line = min(int(marker["line_number"]) for marker in markers if marker["kind"] == "chapter")
    preserve_large_leading_prefix = _char_offset_before_line(text, first_chapter_line) >= SMART_IMPORT_PREFIX_CHARS
    leading_prefix_flushed = False

    def flush() -> None:
        nonlocal buffer, current_title
        content = "\n".join(buffer).strip()
        if current_title and content:
            chapters.append(ParsedChapter(title=current_title, content=content, outline="", volume_title=current_volume, chapter_type=current_chapter_type))
        buffer = []

    def flush_leading_prefix() -> None:
        nonlocal leading_buffer, leading_prefix_flushed
        if leading_prefix_flushed:
            return
        content = "\n".join(leading_buffer).strip()
        if content:
            chapters.append(ParsedChapter(title=f"第{len(chapters) + 1}章", content=content, outline="", volume_title=current_volume, chapter_type="正文"))
        leading_buffer = []
        leading_prefix_flushed = True

    current_chapter_type: str = "正文"
    for line_number, raw_line in enumerate(text.split("\n"), start=1):
        line_markers = markers_by_line.get(line_number, [])
        volume_markers = [item for item in line_markers if item["kind"] == "volume"]
        chapter_markers = [item for item in line_markers if item["kind"] == "chapter"]
        if volume_markers:
            flush()
            current_volume = str(volume_markers[-1]["title"])
            current_title = None
            continue
        if chapter_markers:
            if current_title:
                flush()
            elif preserve_large_leading_prefix:
                flush_leading_prefix()
            current_title = str(chapter_markers[-1]["title"])
            current_chapter_type = str(chapter_markers[-1].get("chapter_type", "") or _infer_chapter_type(current_title))
            if current_chapter_type not in ("正文", "番外", "作者的话"):
                current_chapter_type = _infer_chapter_type(current_title)
            continue
        if current_title:
            buffer.append(raw_line)
        elif preserve_large_leading_prefix:
            line = _clean_heading_line(raw_line)
            if not leading_buffer and _is_front_matter_noise(line):
                continue
            leading_buffer.append(raw_line)
    flush()
    return chapters


def _char_offset_before_line(text: str, line_number: int) -> int:
    if line_number <= 1:
        return 0
    offset = 0
    for index, line in enumerate(text.split("\n"), start=1):
        if index >= line_number:
            break
        offset += len(line) + 1
    return offset


def _normalize_structure_markers(chapter_structure: list[dict[str, Any]]) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for item in chapter_structure:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "") or "").strip().lower()
        if kind not in {"volume", "chapter"}:
            continue
        try:
            line_number = int(item.get("line_number", item.get("line", 0)) or 0)
        except (TypeError, ValueError):
            continue
        title = str(item.get("title", "") or "").strip()
        if line_number <= 0 or not title:
            continue
        key = (kind, line_number)
        if key in seen:
            continue
        seen.add(key)
        markers.append({"kind": kind, "line_number": line_number, "title": title})
    markers.sort(key=lambda item: (int(item["line_number"]), 0 if item["kind"] == "volume" else 1))
    return markers


def _normalize_text(raw_text: str) -> str:
    text = raw_text.replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def normalize_paragraph_spacing(value: str) -> str:
    """Ensure exactly one blank line between adjacent text paragraphs."""
    lines = str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        output.append(line)
        if index >= len(lines) - 1 or not line.strip():
            index += 1
            continue

        next_text_line_index = index + 1
        while next_text_line_index < len(lines) and not lines[next_text_line_index].strip():
            next_text_line_index += 1
        if next_text_line_index < len(lines) and lines[next_text_line_index].strip():
            output.append("")
            index = next_text_line_index
            continue
        index += 1
    return "\n".join(output).strip()


def _normalize_imported_chapter(chapter: ParsedChapter) -> ParsedChapter:
    content = normalize_paragraph_spacing(chapter.content)
    return ParsedChapter(
        title=chapter.title,
        content=content,
        outline=_extract_chapter_outline(chapter.title, content),
        volume_title=chapter.volume_title,
        chapter_type=chapter.chapter_type,
        start_line=chapter.start_line,
    )


def _parse_by_headings(text: str) -> tuple[list[ParsedChapter], int]:
    chapters: list[ParsedChapter] = []
    current_volume: str | None = None
    current_title: str | None = None
    current_start_line: int = 0
    buffer: list[str] = []
    explicit_chapter_count = 0
    strong_count, act_count, pipe_section_count, numbered_section_count = _count_heading_candidates(text)
    allow_pipe_sections = pipe_section_count >= 2
    allow_numbered_sections = strong_count < 2 and numbered_section_count >= 2
    use_acts_as_volumes = act_count >= 2 and (allow_pipe_sections or strong_count >= 2 or numbered_section_count >= 2)

    def flush() -> None:
        nonlocal buffer, current_title, current_start_line
        content = "\n".join(buffer).strip()
        if content:
            title = current_title or f"第{len(chapters) + 1}章"
            chapter_type = _infer_chapter_type(title) if current_title else "正文"
            chapters.append(ParsedChapter(
                title=title, content=content, outline="",
                volume_title=current_volume, chapter_type=chapter_type,
                start_line=current_start_line,
            ))
        buffer = []

    for line_index, raw_line in enumerate(text.split("\n"), start=1):
        line = _clean_heading_line(raw_line)
        if not chapters and not buffer and _is_front_matter_noise(line):
            current_title = None
            continue
        if line and len(line) <= 80 and _VOLUME_RE.match(line):
            flush()
            current_volume = line
            current_title = None
            continue
        if line and len(line) <= 100 and use_acts_as_volumes and _ACT_RE.match(line):
            flush()
            current_volume = line
            current_title = None
            continue
        if line and len(line) <= 100 and _is_chapter_heading(
            line,
            allow_pipe_sections,
            allow_numbered_sections,
            use_acts_as_volumes,
        ):
            flush()
            current_title = line
            current_start_line = line_index
            explicit_chapter_count += 1
            continue
        buffer.append(raw_line)
    flush()

    if not chapters and text.strip():
        chapters.append(ParsedChapter(title="第1章", content=text.strip(), outline="", volume_title=None))
    return chapters, explicit_chapter_count


def _clean_heading_line(raw_line: str) -> str:
    line = raw_line.strip().strip("\ufeff")
    line = re.sub(r"^\s*[#>*\-=—_＿~～·•\s]+", "", line)
    line = re.sub(r"[\-=—_＿~～·•\s]+$", "", line)
    return line.strip()


def _is_front_matter_noise(line: str) -> bool:
    compact = re.sub(r"\s+", "", line or "")
    return compact in {"目录", "作品目录", "章节目录", "正文", "正文开始", "内容简介"}


def _is_chapter_heading(
    line: str,
    allow_pipe_sections: bool,
    allow_numbered_sections: bool,
    use_acts_as_volumes: bool,
) -> bool:
    if not use_acts_as_volumes and _ACT_RE.match(line):
        return True
    if _STRONG_CHAPTER_RE.match(line):
        return True
    if allow_pipe_sections and _PIPE_SECTION_RE.match(line):
        return True
    return allow_numbered_sections and bool(_NUMBERED_SECTION_RE.match(line))


def _count_heading_candidates(text: str) -> tuple[int, int, int, int]:
    strong_count = 0
    act_count = 0
    pipe_section_count = 0
    numbered_section_count = 0
    for raw_line in text.split("\n"):
        line = _clean_heading_line(raw_line)
        if not line or len(line) > 100 or _VOLUME_RE.match(line):
            continue
        if _ACT_RE.match(line):
            act_count += 1
        elif _STRONG_CHAPTER_RE.match(line):
            strong_count += 1
        elif _PIPE_SECTION_RE.match(line):
            pipe_section_count += 1
        elif _NUMBERED_SECTION_RE.match(line):
            numbered_section_count += 1
    return strong_count, act_count, pipe_section_count, numbered_section_count


def _chunk_implicit_chapters(chapters: list[ParsedChapter]) -> list[ParsedChapter]:
    chunked: list[ParsedChapter] = []
    for chapter in chapters:
        chunks = _split_into_chunks(chapter.content)
        if len(chunks) == 1:
            title = chapter.title if chapter.title != "第1章" or chapter.volume_title is None else f"{chapter.volume_title} 第1章"
            chunked.append(ParsedChapter(title=title, content=chunks[0], outline="", volume_title=chapter.volume_title, chapter_type=chapter.chapter_type, start_line=chapter.start_line))
            continue
        for index, chunk in enumerate(chunks, start=1):
            title = f"第{len(chunked) + 1}章"
            if chapter.volume_title:
                title = f"{chapter.volume_title} 第{index}章"
            chunked.append(ParsedChapter(title=title, content=chunk, outline="", volume_title=chapter.volume_title, chapter_type=chapter.chapter_type, start_line=chapter.start_line))
    return chunked


def _split_into_chunks(text: str, target_size: int = 4500, hard_size: int = 6800) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", text) if part.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for paragraph in paragraphs:
        if len(paragraph) > hard_size:
            if current:
                chunks.append("\n\n".join(current).strip())
                current = []
                current_size = 0
            chunks.extend(_split_large_paragraph(paragraph, target_size))
            continue
        if current and current_size + len(paragraph) > target_size:
            chunks.append("\n\n".join(current).strip())
            current = [paragraph]
            current_size = len(paragraph)
        else:
            current.append(paragraph)
            current_size += len(paragraph)
    if current:
        chunks.append("\n\n".join(current).strip())
    return [chunk for chunk in chunks if chunk.strip()]


def _split_large_paragraph(paragraph: str, target_size: int) -> list[str]:
    sentences = [item.strip() for item in _SENTENCE_RE.split(paragraph) if item.strip()]
    if len(sentences) <= 1:
        return [paragraph[index : index + target_size].strip() for index in range(0, len(paragraph), target_size)]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for sentence in sentences:
        if current and size + len(sentence) > target_size:
            chunks.append("".join(current).strip())
            current = [sentence]
            size = len(sentence)
        else:
            current.append(sentence)
            size += len(sentence)
    if current:
        chunks.append("".join(current).strip())
    return chunks


def _extract_chapter_outline(title: str, content: str) -> str:
    sentences = _pick_sentences(content, limit=4)
    if not sentences:
        sentences = [content.strip()[:160]]
    lines = [f"自动提炼大纲：{title}", f"字数：{len(content.strip())}"]
    for sentence in sentences:
        lines.append(f"- {sentence[:180]}")
    return "\n".join(lines)


def _extract_book_outline(book_title: str, chapters: list[ParsedChapter]) -> str:
    volume_titles = []
    seen = set()
    for chapter in chapters:
        if chapter.volume_title and chapter.volume_title not in seen:
            volume_titles.append(chapter.volume_title)
            seen.add(chapter.volume_title)
    total_chars = sum(len(chapter.content.strip()) for chapter in chapters)
    lines = [
        f"自动导入总纲：{book_title.strip() or '未命名导入作品'}",
        f"规模：{len(volume_titles)} 卷 / {len(chapters)} 章 / {total_chars} 字",
    ]
    if volume_titles:
        lines.append("卷结构：")
        for title in volume_titles[:20]:
            lines.append(f"- {title}")
    lines.append("章节结构：")
    for chapter in chapters[:40]:
        prefix = f"{chapter.volume_title} / " if chapter.volume_title else ""
        lines.append(f"- {prefix}{chapter.title}")
    if len(chapters) > 40:
        lines.append(f"- ... 另有 {len(chapters) - 40} 章")
    return "\n".join(lines)


def _pick_sentences(content: str, limit: int) -> list[str]:
    compact = re.sub(r"\s+", " ", content).strip()
    sentences = [item.strip() for item in _SENTENCE_RE.split(compact) if len(item.strip()) >= 8]
    picked: list[str] = []
    if sentences:
        picked.append(sentences[0])
    if len(sentences) >= 3:
        picked.append(sentences[len(sentences) // 2])
    if len(sentences) >= 2:
        picked.append(sentences[-1])
    for sentence in sentences:
        if len(picked) >= limit:
            break
        if sentence not in picked:
            picked.append(sentence)
    return picked[:limit]


# ================================================================
#  三阶段智能导入辅助：目录摘要 / 局部重检合并
# ================================================================

def build_catalog_summary(chapters: list[ParsedChapter], max_chars: int = 30000) -> str:
    """生成目录摘要文本，供 AI 校验。

    每行格式: ``序号|字数|卷|类型|标题``
    - 序号从 1 开始
    - 字数为正文字符数（去首尾空白）

    超过 max_chars 时按章节截断（保留前面的章节）。
    """
    lines: list[str] = []
    total_chars = 0
    for index, chapter in enumerate(chapters, start=1):
        char_count = len(chapter.content.strip())
        volume = chapter.volume_title or ""
        line = f"{index}|{char_count}字|{volume}|{chapter.chapter_type}|{chapter.title}"
        # 预估 +1 换行
        if total_chars + len(line) + 1 > max_chars:
            lines.append(f"...（另有 {len(chapters) - index + 1} 章未列出）")
            break
        lines.append(line)
        total_chars += len(line) + 1
    return "\n".join(lines)


def merge_reparsed_chapters(
    original: list[ParsedChapter],
    reparsed: list[ParsedChapter],
    replace_start_index: int,
    replace_end_index: int,
) -> list[ParsedChapter]:
    """将局部重检的章节合并回原始章节列表（按章节序号替换）。

    :param original: 正则解析的完整章节列表
    :param reparsed: AI 对问题区域重新解析得到的章节
    :param replace_start_index: 要替换的起始章节序号（1-based, 含）
    :param replace_end_index: 要替换的结束章节序号（1-based, 含）
    :return: 合并后的章节列表
    """
    if not reparsed:
        return original
    # 0-based 索引
    s = max(0, replace_start_index - 1)
    e = min(len(original), replace_end_index)
    return original[:s] + list(reparsed) + original[e:]
