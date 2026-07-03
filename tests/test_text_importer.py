from __future__ import annotations

from novel_app.text_importer import normalize_paragraph_spacing, parse_long_text


def test_parse_long_text_uses_agent_structure_without_local_heading_rules() -> None:
    raw_text = "\n".join(
        [
            "目录",
            "烟雨篇",
            "起风",
            "雨落在城门上，林一第一次听见远处的钟声。",
            "他沿着河岸向北走，心里记着旧约。",
            "回城",
            "城门在黄昏时打开，旧友带来了新的密信。",
        ]
    )
    structure = [
        {"kind": "volume", "line_number": 2, "title": "第一卷 烟雨篇"},
        {"kind": "chapter", "line_number": 3, "title": "第一章 起风"},
        {"kind": "chapter", "line_number": 6, "title": "第二章 回城"},
    ]

    parsed = parse_long_text(
        "测试书",
        raw_text,
        chapter_structure=structure,
        use_local_headings=False,
    )

    assert [chapter.title for chapter in parsed.chapters] == ["第一章 起风", "第二章 回城"]
    assert [chapter.volume_title for chapter in parsed.chapters] == ["第一卷 烟雨篇", "第一卷 烟雨篇"]
    assert "雨落在城门上" in parsed.chapters[0].content
    assert "城门在黄昏时打开" in parsed.chapters[1].content


def test_parse_long_text_without_agent_structure_does_not_use_local_headings_when_disabled() -> None:
    raw_text = "第一章 风起\n正文一。\n第二章 回城\n正文二。"

    parsed = parse_long_text("测试书", raw_text, chapter_structure=[], use_local_headings=False)

    assert len(parsed.chapters) == 1
    assert parsed.chapters[0].title == "第1章"
    assert "第二章 回城" in parsed.chapters[0].content


def test_detected_structure_preserves_large_prefix_before_first_late_chapter() -> None:
    prefix = "首段正文。" * 70000
    raw_text = prefix + "\n第二章 后续\n后续正文。"
    structure = [{"kind": "chapter", "line_number": 2, "title": "第二章 后续"}]

    parsed = parse_long_text("测试书", raw_text, chapter_structure=structure, use_local_headings=False)

    assert [chapter.title for chapter in parsed.chapters] == ["第1章", "第二章 后续"]
    assert "首段正文" in parsed.chapters[0].content
    assert "后续正文" in parsed.chapters[1].content


def test_detected_structure_does_not_create_prefix_chapter_before_early_heading() -> None:
    raw_text = "目录\n第一章 开端\n正文。" + ("长正文。" * 60000)
    structure = [{"kind": "chapter", "line_number": 2, "title": "第一章 开端"}]

    parsed = parse_long_text("测试书", raw_text, chapter_structure=structure, use_local_headings=False)

    assert [chapter.title for chapter in parsed.chapters] == ["第一章 开端"]
    assert "目录" not in parsed.chapters[0].content


def test_normalize_paragraph_spacing_keeps_one_blank_line_between_text_blocks() -> None:
    assert normalize_paragraph_spacing("alpha\nbeta\n\n\ncharlie") == "alpha\n\nbeta\n\ncharlie"


def test_parse_long_text_normalizes_imported_chapter_paragraph_spacing() -> None:
    parsed = parse_long_text("Imported", "Chapter 1\nalpha\nbeta\n\n\ncharlie")

    assert parsed.chapters
    assert "alpha\n\nbeta\n\ncharlie" in parsed.chapters[0].content
