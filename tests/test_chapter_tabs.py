from __future__ import annotations

from novel_app.qt.chapter_tabs import ChapterEditorSession, ChapterEditorWidgets, ChapterTabsController


def make_session(chapter_id: int, title: str | None = None) -> ChapterEditorSession:
    return ChapterEditorSession(
        chapter_id=chapter_id,
        book_id=1,
        title=title or f"第 {chapter_id} 章",
        path=f"测试书 / 第 {chapter_id} 章",
        outline_text=f"outline {chapter_id}",
        content_text=f"content {chapter_id}",
        loaded_content_text=f"content {chapter_id}",
    )


def test_open_same_chapter_reuses_existing_session() -> None:
    controller = ChapterTabsController()

    first = controller.open_or_activate(make_session(1, "初始标题"))
    first.content_text = "unsaved content"
    first.dirty = True
    second = controller.open_or_activate(make_session(1, "更新标题"))

    assert first is second
    assert controller.open_order == [1]
    assert second.title == "更新标题"
    assert second.content_text == "unsaved content"
    assert second.dirty is True


def test_switching_tabs_preserves_text_cursor_scroll_and_dirty_state() -> None:
    controller = ChapterTabsController()
    controller.open_or_activate(make_session(1))
    controller.store_active(
        outline_text="edited outline",
        content_text="edited content",
        dirty=True,
        cursor_position=12,
        scroll_position=34,
    )
    controller.open_or_activate(make_session(2))

    restored = controller.activate(1)

    assert restored is not None
    assert restored.outline_text == "edited outline"
    assert restored.content_text == "edited content"
    assert restored.dirty is True
    assert restored.cursor_position == 12
    assert restored.scroll_position == 34
    assert controller.tab_title(1).startswith("● ")


def test_close_active_session_selects_previous_open_tab() -> None:
    controller = ChapterTabsController()
    controller.open_or_activate(make_session(1))
    controller.open_or_activate(make_session(2))
    controller.open_or_activate(make_session(3))

    closed = controller.close(3)

    assert closed is not None
    assert closed.chapter_id == 3
    assert controller.open_order == [1, 2]
    assert controller.active_chapter_id == 2


def test_mark_saved_updates_loaded_content_and_dirty_list() -> None:
    controller = ChapterTabsController()
    controller.open_or_activate(make_session(1))
    controller.store_active(outline_text="outline", content_text="new content", dirty=True)

    assert [session.chapter_id for session in controller.dirty_sessions()] == [1]
    controller.mark_saved(1, outline_text="outline", content_text="new content", summary_text="")

    session = controller.sessions[1]
    assert session.dirty is False
    assert session.loaded_content_text == "new content"
    assert controller.dirty_sessions() == []


def test_session_can_hold_independent_editor_widgets() -> None:
    session = make_session(1)
    outline_editor = object()
    content_editor = object()

    session.editor_widgets = ChapterEditorWidgets(
        outline_editor=outline_editor,
        content_editor=content_editor,
    )

    assert session.editor_widgets.outline_editor is outline_editor
    assert session.editor_widgets.content_editor is content_editor
