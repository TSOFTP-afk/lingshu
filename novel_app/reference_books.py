from __future__ import annotations

import re
from pathlib import Path
from typing import Any

BOOK_REFERENCE_ROLES: tuple[tuple[str, str], ...] = (
    ("style_reference", "文风参考"),
    ("canon_reference", "设定参考"),
    ("structure_reference", "结构参考"),
    ("avoid_reference", "规避参考"),
)


def split_reference_text_into_segments(text: str, max_chars: int = 1800) -> list[dict[str, Any]]:
    """Split a reference book into stable, book-scoped segments."""
    max_chars = max(400, int(max_chars or 1800))
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    raw_segments: list[tuple[str, str]] = []
    current_title = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        content = "\n".join(current_lines).strip()
        if content:
            raw_segments.extend(_split_oversized_reference_segment(current_title, content, max_chars))
        current_title = ""
        current_lines = []

    for line in normalized.split("\n"):
        stripped = line.strip()
        if _is_reference_heading(stripped):
            if current_lines:
                flush()
            current_title = _clean_reference_heading(stripped)
            current_lines = [stripped]
            continue
        current_lines.append(line)
        if stripped == "" and len("\n".join(current_lines)) >= max_chars:
            flush()
    flush()

    if not raw_segments:
        raw_segments = [("", normalized)]

    segments: list[dict[str, Any]] = []
    for index, (title, content) in enumerate(raw_segments, start=1):
        cleaned = content.strip()
        if not cleaned:
            continue
        segments.append(
            {
                "segment_index": index,
                "title": title or f"第 {index} 段",
                "summary": _reference_summary(cleaned),
                "content": cleaned,
                "metadata": {"source": "reference_books"},
            }
        )
    return segments


def reference_source_path(source: dict[str, Any], data_dir: Path) -> Path:
    raw = str(source.get("source_path") or "").strip()
    path = Path(raw)
    if path.is_absolute():
        return path
    return Path(data_dir) / path


def read_reference_text_file(path: Path) -> str:
    if path.suffix.lower() == ".docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("当前环境未安装 python-docx，无法读取 docx 参考书。") from exc
        document = Document(str(path))
        return "\n\n".join(paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip())
    return path.read_text(encoding="utf-8", errors="ignore")


def role_label(role: str) -> str:
    labels = dict(BOOK_REFERENCE_ROLES)
    return labels.get(str(role or "").strip(), str(role or "参考书").strip() or "参考书")


def _is_reference_heading(text: str) -> bool:
    if not text:
        return False
    return bool(
        re.match(r"^#{1,6}\s+\S+", text)
        or re.match(r"^第[0-9一二三四五六七八九十百千万]+[章节卷回部篇].*", text)
        or re.match(r"^(chapter|part|volume)\s+\d+.*", text, re.IGNORECASE)
    )


def _clean_reference_heading(text: str) -> str:
    return re.sub(r"^#{1,6}\s*", "", text).strip()


def _split_oversized_reference_segment(title: str, content: str, max_chars: int) -> list[tuple[str, str]]:
    if len(content) <= max_chars:
        return [(title, content)]
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
    if len(paragraphs) <= 1:
        return [(title, content[i : i + max_chars]) for i in range(0, len(content), max_chars)]
    chunks: list[tuple[str, str]] = []
    current: list[str] = []
    for paragraph in paragraphs:
        candidate = "\n\n".join([*current, paragraph]).strip()
        if current and len(candidate) > max_chars:
            chunks.append((title, "\n\n".join(current).strip()))
            current = [paragraph]
        else:
            current.append(paragraph)
    if current:
        chunks.append((title, "\n\n".join(current).strip()))
    return chunks


def _reference_summary(content: str, limit: int = 220) -> str:
    cleaned = re.sub(r"\s+", " ", content).strip()
    return cleaned[:limit]
