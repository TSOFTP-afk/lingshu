from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AppState:
    """集中式应用状态 —— 所有可变状态集中管理，视图通过 Listener 订阅变更"""

    selected_book_id: int | None = None
    selected_book_title: str = ""
    selected_volume_id: int | None = None
    selected_chapter_id: int | None = None
    selected_character_id: int | None = None

    current_tree_iid: str | None = None
    current_node_kind: str = ""

    editor_scope_kind: str | None = None
    editor_scope_id: int | None = None

    editor_content: str = ""
    editor_outline: str = ""
    editor_summary: str = ""
    editor_dirty: bool = False
    editor_save_time: str = ""
    editor_word_count: int = 0

    workspace_mode: str = "empty"

    sidebar_collapsed: bool = False
    sidebar_width: int = 220

    context_panel_visible: bool = False
    context_panel_width: int = 280
    context_panel_tab: str = "overview"

    focus_mode: bool = False
    drawer_kind: str = "details"
    theme_mode: str = "light"

    task_running: bool = False
    task_name: str = ""
    task_detail: str = ""
    task_generated_chars: int = 0

    ai_remote_enabled: bool = False
    ai_api_key: str = ""
    ai_base_url: str = ""
    ai_model: str = ""
    ai_mode_label: str = "本地 Mock"

    active_skills_label: str = "生效 Skills：无"
    bound_skill_count: int = 0

    def _notify(self, listeners: dict[str, list[Callable]], key: str) -> None:
        for cb in listeners.get(key, []):
            try:
                cb(getattr(self, key))
            except Exception:
                logger.exception("State listener failed for key=%s", key)
        for cb in listeners.get("*", []):
            try:
                cb(key, getattr(self, key))
            except Exception:
                logger.exception("Wildcard state listener failed for key=%s", key)

    def _set(self, listeners: dict[str, list[Callable]], key: str, value: Any) -> None:
        if getattr(self, key) == value:
            return
        object.__setattr__(self, key, value)
        self._notify(listeners, key)

    def clear_book_context(self) -> None:
        self.selected_book_id = None
        self.selected_book_title = ""
        self.selected_volume_id = None
        self.selected_chapter_id = None
        self.current_node_kind = ""
        self.workspace_mode = "empty"
        self.editor_scope_kind = None
        self.editor_scope_id = None
        self.active_skills_label = "生效 Skills：无"
        self.bound_skill_count = 0

    def clear_selection(self) -> None:
        self.selected_book_id = None
        self.selected_book_title = ""
        self.selected_volume_id = None
        self.selected_chapter_id = None
        self.current_node_kind = ""
        self.editor_scope_kind = None
        self.editor_scope_id = None
        self.editor_dirty = False


class StateStore:
    """状态存储器 —— 管理 AppState 实例和变更监听器"""

    def __init__(self, state: AppState | None = None):
        self.state = state or AppState()
        self._listeners: dict[str, list[Callable]] = {}

    def get(self, key: str) -> Any:
        return getattr(self.state, key)

    def set(self, key: str, value: Any) -> None:
        self.state._set(self._listeners, key, value)

    def update(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self.state, key):
                self.set(key, value)

    def on_change(self, key: str, callback: Callable) -> None:
        self._listeners.setdefault(key, []).append(callback)

    def off_change(self, key: str, callback: Callable) -> None:
        entries = self._listeners.get(key, [])
        if callback in entries:
            entries.remove(callback)

    def clear_book_context(self) -> None:
        self.state.clear_book_context()
        for key in (
            "selected_book_id",
            "selected_book_title",
            "selected_volume_id",
            "selected_chapter_id",
            "current_node_kind",
            "workspace_mode",
            "editor_scope_kind",
            "editor_scope_id",
            "active_skills_label",
            "bound_skill_count",
        ):
            self.state._notify(self._listeners, key)

    def clear_selection(self) -> None:
        self.state.clear_selection()
        for key in (
            "selected_book_id",
            "selected_book_title",
            "selected_volume_id",
            "selected_chapter_id",
            "current_node_kind",
            "editor_scope_kind",
            "editor_scope_id",
            "editor_dirty",
        ):
            self.state._notify(self._listeners, key)

    def is_chapter_active(self) -> bool:
        return self.state.current_node_kind == "chapter" and self.state.selected_chapter_id is not None

    def is_book_active(self) -> bool:
        return self.state.selected_book_id is not None

    def has_management_scope(self) -> bool:
        return self.state.selected_book_id is not None and self.state.current_node_kind in {"book", "volume", "group"}
