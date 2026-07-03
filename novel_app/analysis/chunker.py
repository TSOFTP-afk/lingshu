from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AnalysisChunk:
    chunk_id: str
    chunk_index: int
    block_uid: str
    text: str
    chapter_ids: list[int]
    chapter_refs: list[dict[str, Any]]
    char_start: int
    char_end: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "block_uid": self.block_uid,
            "text": self.text,
            "chapter_ids": self.chapter_ids,
            "chapter_refs": self.chapter_refs,
            "char_start": self.char_start,
            "char_end": self.char_end,
        }


class AnalysisChunker:
    def __init__(self, *, max_chars: int = 20000) -> None:
        self.max_chars = max(1, int(max_chars))

    def chunk_chapters(self, chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
        chunks: list[AnalysisChunk] = []
        cursor = 0
        for chapter in chapters:
            for text, chapter_ids, chapter_refs, local_index in self._chapter_texts(chapter):
                if not text.strip():
                    continue
                chunk_index = len(chunks) + 1
                block_uid = self._block_uid(chapter_refs, local_index)
                start = cursor
                end = start + len(text)
                chunks.append(
                    AnalysisChunk(
                        chunk_id=f"chunk-{chunk_index:04d}",
                        chunk_index=chunk_index,
                        block_uid=block_uid,
                        text=text,
                        chapter_ids=chapter_ids,
                        chapter_refs=chapter_refs,
                        char_start=start,
                        char_end=end,
                    )
                )
                cursor = end + 2
        return [chunk.as_dict() for chunk in chunks]

    def _chapter_texts(self, chapter: dict[str, Any]) -> list[tuple[str, list[int], list[dict[str, Any]], int]]:
        chapter_id = self._int_or_none(chapter.get("id"))
        title = str(chapter.get("title", "") or "")
        outline = str(chapter.get("outline", "") or "")
        content = str(chapter.get("content", "") or "")
        header = self._chapter_header(chapter_id, title, outline)
        chapter_ids = [chapter_id] if chapter_id is not None else []
        chapter_refs = [{"id": chapter_id, "title": title}] if chapter_id is not None else []
        paragraphs = self._paragraphs(content) or [""]
        available = max(1, self.max_chars - len(header))
        chunks: list[tuple[str, list[int], list[dict[str, Any]], int]] = []
        current_parts: list[str] = []
        local_index = 1

        def current_text() -> str:
            body = "\n\n".join(part for part in current_parts if part)
            return f"{header}{body}".strip()

        def flush() -> None:
            nonlocal local_index, current_parts
            text = current_text()
            if text:
                chunks.append((text, chapter_ids, chapter_refs, local_index))
                local_index += 1
            current_parts = []

        for paragraph in paragraphs:
            pieces = self._split_long_paragraph(paragraph, available)
            for piece in pieces:
                candidate_parts = current_parts + ([piece] if piece else [])
                candidate_body = "\n\n".join(part for part in candidate_parts if part)
                candidate_len = len(f"{header}{candidate_body}".strip())
                if current_parts and candidate_len > self.max_chars:
                    flush()
                current_parts.append(piece)
        flush()
        return chunks

    @staticmethod
    def _chapter_header(chapter_id: int | None, title: str, outline: str) -> str:
        chapter_label = "" if chapter_id is None else str(chapter_id)
        return (
            f"[chapter_id={chapter_label}]\n"
            f"title: {title}\n"
            f"outline: {outline}\n"
            "content:\n"
        )

    @staticmethod
    def _paragraphs(content: str) -> list[str]:
        normalized = str(content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return []
        return [part.strip() for part in re.split(r"\n\s*\n+", normalized) if part.strip()]

    @staticmethod
    def _split_long_paragraph(paragraph: str, limit: int) -> list[str]:
        text = str(paragraph or "").strip()
        if len(text) <= limit:
            return [text]
        pieces: list[str] = []
        while text:
            if len(text) <= limit:
                pieces.append(text)
                break
            cut = max(
                text.rfind("\n", 0, limit),
                text.rfind("。", 0, limit),
                text.rfind("！", 0, limit),
                text.rfind("？", 0, limit),
                text.rfind(".", 0, limit),
                text.rfind("!", 0, limit),
                text.rfind("?", 0, limit),
            )
            if cut < max(1, limit // 2):
                cut = limit
            else:
                cut += 1
            pieces.append(text[:cut].strip())
            text = text[cut:].strip()
        return [piece for piece in pieces if piece]

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _block_uid(chapter_refs: list[dict[str, Any]], local_index: int) -> str:
        if chapter_refs:
            return f"analysis-chapter-{chapter_refs[0]['id']}-part-{local_index:03d}"
        return f"analysis-orphan-part-{local_index:03d}"
