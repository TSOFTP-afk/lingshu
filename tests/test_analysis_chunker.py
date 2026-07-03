from __future__ import annotations

from novel_app.analysis.chunker import AnalysisChunker


def test_chunker_keeps_normal_paragraphs_intact() -> None:
    first = "alpha " * 40
    second = "beta " * 40
    chunks = AnalysisChunker(max_chars=360).chunk_chapters(
        [{"id": 7, "title": "Chapter 7", "outline": "outline", "content": f"{first}\n\n{second}"}]
    )

    assert len(chunks) == 2
    assert chunks[0]["chapter_ids"] == [7]
    assert chunks[0]["block_uid"] == "analysis-chapter-7-part-001"
    assert first.strip() in chunks[0]["text"]
    assert second.strip() in chunks[1]["text"]
    assert second.strip() not in chunks[0]["text"]


def test_chunker_hard_splits_oversized_paragraphs_without_losing_text() -> None:
    content = "x" * 500
    chunks = AnalysisChunker(max_chars=180).chunk_chapters(
        [{"id": 3, "title": "Long", "outline": "", "content": content}]
    )

    assert len(chunks) > 1
    assert all(len(chunk["text"]) <= 180 for chunk in chunks)
    joined_body = "".join(chunk["text"].split("content:\n", 1)[-1].replace("\n\n", "") for chunk in chunks)
    assert joined_body == content
