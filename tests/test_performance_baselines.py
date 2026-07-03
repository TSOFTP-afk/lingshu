from __future__ import annotations

import tempfile

import pytest

from novel_app.rag.retriever import ChapterRetriever
from novel_app.text_importer import parse_long_text


@pytest.mark.performance
def test_rag_search_handles_hundreds_of_local_chapters_quickly() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        retriever = ChapterRetriever(tmp)
        for index in range(240):
            retriever.index_chapter(
                1,
                index + 1,
                f"第{index + 1}章",
                f"主角调查线索 {index % 11} 并推进真相。",
                content_snippet="线索与冲突" * 20,
            )

        results = retriever.search(1, "调查真相", top_k=8)

    assert results
    assert len(results) <= 8


@pytest.mark.performance
def test_long_text_import_parser_handles_large_chapter_sets() -> None:
    text = "\n".join(
        f"第{index}章 测试章节\n" + ("正文内容。" * 80)
        for index in range(1, 181)
    )

    parsed = parse_long_text("性能测试", text)

    assert parsed.title == "性能测试"
    assert len(parsed.chapters) >= 150
