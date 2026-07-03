from __future__ import annotations

from typing import Any


def chapter_dict(value: Any) -> dict[str, Any]:
    """将章节数据统一转换为 dict。

    兼容两种输入：
    - dict 对象：直接返回副本
    - 具有 id/title/outline/content 属性的对象（如 sqlite3.Row）：提取字段
    - None 或无法转换的值：返回空 dict
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    try:
        return {
            "id": value["id"],
            "title": value["title"],
            "outline": value["outline"],
            "content": value["content"],
        }
    except Exception:
        try:
            return dict(value)
        except Exception:
            return {}


def safe_int(value: Any) -> int | None:
    """安全地将值转换为 int，失败返回 None。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
