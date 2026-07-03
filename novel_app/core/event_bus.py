from __future__ import annotations

import logging
from collections.abc import Callable
from threading import RLock
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    """事件总线 - 提供统一的事件管理机制，减少组件之间的直接依赖"""

    def __init__(self):
        self._listeners: dict[str, list[Callable]] = {}
        self._lock = RLock()

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """订阅事件

        Args:
            event_type: 事件类型
            callback: 回调函数
        """
        with self._lock:
            if event_type not in self._listeners:
                self._listeners[event_type] = []
            if callback not in self._listeners[event_type]:
                self._listeners[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """取消订阅事件

        Args:
            event_type: 事件类型
            callback: 回调函数
        """
        with self._lock:
            if event_type in self._listeners and callback in self._listeners[event_type]:
                self._listeners[event_type].remove(callback)

    def publish(self, event_type: str, *args: Any, **kwargs: Any) -> None:
        """发布事件

        Args:
            event_type: 事件类型
            *args: 位置参数
            **kwargs: 关键字参数
        """
        with self._lock:
            callbacks = list(self._listeners.get(event_type, []))
        for callback in callbacks:
            try:
                callback(*args, **kwargs)
            except Exception:
                logger.exception("Event listener failed for event_type=%s", event_type)

    def clear(self, event_type: str | None = None) -> None:
        """清除事件监听器

        Args:
            event_type: 事件类型，如果为None则清除所有事件监听器
        """
        with self._lock:
            if event_type:
                if event_type in self._listeners:
                    del self._listeners[event_type]
            else:
                self._listeners.clear()

    def get_listeners(self, event_type: str) -> list[Callable]:
        """获取指定事件类型的所有监听器

        Args:
            event_type: 事件类型

        Returns:
            监听器列表
        """
        with self._lock:
            return list(self._listeners.get(event_type, []))

    def has_listeners(self, event_type: str) -> bool:
        """检查指定事件类型是否有监听器

        Args:
            event_type: 事件类型

        Returns:
            是否有监听器
        """
        with self._lock:
            return event_type in self._listeners and len(self._listeners[event_type]) > 0


# 全局事件总线实例
_event_bus = EventBus()


def get_event_bus() -> EventBus:
    """获取全局事件总线实例

    Returns:
        事件总线实例
    """
    return _event_bus


def subscribe(event_type: str, callback: Callable) -> None:
    """订阅事件（全局）

    Args:
        event_type: 事件类型
        callback: 回调函数
    """
    _event_bus.subscribe(event_type, callback)


def unsubscribe(event_type: str, callback: Callable) -> None:
    """取消订阅事件（全局）

    Args:
        event_type: 事件类型
        callback: 回调函数
    """
    _event_bus.unsubscribe(event_type, callback)


def publish(event_type: str, *args: Any, **kwargs: Any) -> None:
    """发布事件（全局）

    Args:
        event_type: 事件类型
        *args: 位置参数
        **kwargs: 关键字参数
    """
    _event_bus.publish(event_type, *args, **kwargs)
