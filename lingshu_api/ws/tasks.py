"""WebSocket background task registry."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable
from typing import Any

logger = logging.getLogger("lingshu.ws.tasks")


class ClientTaskRegistry:
    """Track background asyncio tasks by WebSocket client id."""

    MAX_TASKS_PER_CLIENT = 5

    def __init__(self) -> None:
        self._tasks: dict[str, set[asyncio.Task[Any]]] = defaultdict(set)

    def create(
        self,
        client_id: str,
        coro: Awaitable[Any],
        *,
        name: str | None = None,
    ) -> asyncio.Task[Any]:
        if len(self._tasks.get(client_id, set())) >= self.MAX_TASKS_PER_CLIENT:
            raise RuntimeError(f"客户端 {client_id} 的并发任务数已达上限 ({self.MAX_TASKS_PER_CLIENT})")
        task = asyncio.create_task(coro, name=name)
        self.track(client_id, task)
        return task

    def track(self, client_id: str, task: asyncio.Task[Any]) -> None:
        if len(self._tasks.get(client_id, set())) >= self.MAX_TASKS_PER_CLIENT:
            raise RuntimeError(f"客户端 {client_id} 的并发任务数已达上限 ({self.MAX_TASKS_PER_CLIENT})")
        self._tasks[client_id].add(task)
        task.add_done_callback(lambda done: self._discard(client_id, done))

    def cancel_client(self, client_id: str) -> None:
        tasks = self._pop_client(client_id)
        for task in tasks:
            if not task.done():
                task.cancel()

    async def cancel_client_and_wait(self, client_id: str) -> None:
        tasks = self._pop_client(client_id)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def active_count(self, client_id: str | None = None) -> int:
        if client_id is not None:
            return len(self._tasks.get(client_id, set()))
        return sum(len(tasks) for tasks in self._tasks.values())

    def _pop_client(self, client_id: str) -> set[asyncio.Task[Any]]:
        return self._tasks.pop(client_id, set())

    def _discard(self, client_id: str, task: asyncio.Task[Any]) -> None:
        tasks = self._tasks.get(client_id)
        if tasks is not None:
            tasks.discard(task)
            if not tasks:
                self._tasks.pop(client_id, None)
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.error(
                "WS background task failed: client_id=%s",
                client_id,
                exc_info=(type(exc), exc, exc.__traceback__),
            )


_registry = ClientTaskRegistry()


def get_ws_task_registry() -> ClientTaskRegistry:
    return _registry
