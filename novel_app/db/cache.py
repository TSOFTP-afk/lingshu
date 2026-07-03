"""Redis 缓存层 —— hybrid-database-architecture spec Task 4.3-4.7 实现。

CacheManager 提供 4 类缓存 + 1 类分布式锁：
1. 书籍树缓存（key=book_tree:{book_id}，TTL=300s，写操作失效）
2. 章节内容缓存（key=chapter:{chapter_id}，TTL=600s，编辑失效）
3. 分析运行状态缓存（key=analysis_run:{run_id}，TTL=60s）
4. 书籍列表缓存（key=book_list:{user_id}，TTL=300s，写操作失效）
5. 分布式锁（SETNX book:{id}:analysis_lock，TTL=3600s）

设计要点：
1. **优雅降级**：Redis 不可用时所有方法返回 None / False / 空，不影响主流程
2. **JSON 序列化**：所有 value 存 JSON 字符串，读出时反序列化
3. **key 前缀**：统一用 lingshu: 前缀，避免与其他应用冲突
4. **批量失效**：写操作后批量删除相关 key（如 rename_book 失效 book_tree + book_list）
5. **锁的幂等性**：acquire_lock 返回 token，release_lock 需匹配 token（用 Lua 脚本保证原子性）

使用方式：
    from novel_app.db.cache import CacheManager
    cache = CacheManager()
    if cache.is_available():
        cached = cache.get_book_tree(book_id)
        if cached is None:
            cached = db.get_book(book_id)
            cache.set_book_tree(book_id, cached)
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Callable, TypeVar

from novel_app.db.redis_client import get_redis_client

logger = logging.getLogger(__name__)

T = TypeVar("T")

# key 前缀与 TTL 配置
_KEY_PREFIX = "lingshu:"
_BOOK_TREE_TTL = 300  # 5 分钟
_CHAPTER_TTL = 600  # 10 分钟
_ANALYSIS_RUN_TTL = 60  # 1 分钟
_BOOK_LIST_TTL = 300  # 5 分钟
_ANALYSIS_LOCK_TTL = 3600  # 1 小时


class CacheManager:
    """Redis 缓存管理器，封装 4 类缓存 + 分布式锁。

    Redis 不可用时所有方法优雅降级（返回 None / False / 空）。
    """

    def __init__(self, prefix: str = _KEY_PREFIX) -> None:
        self._prefix = prefix

    # ------------------------------------------------------------------
    # 基础工具
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Redis 是否可用。"""
        client = get_redis_client()
        return client is not None

    def _client(self) -> Any | None:
        """获取 Redis 客户端（可能为 None）。"""
        return get_redis_client()

    def _key(self, suffix: str) -> str:
        """构造完整 key（加前缀）。"""
        return f"{self._prefix}{suffix}"

    def _serialize(self, value: Any) -> str:
        """序列化 value 为 JSON 字符串。"""
        return json.dumps(value, ensure_ascii=False, default=str)

    def _deserialize(self, value: str | None) -> Any | None:
        """反序列化 JSON 字符串。失败返回 None。"""
        if value is None:
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None

    def _get(self, key: str) -> str | None:
        """安全 GET（Redis 不可用时返回 None）。"""
        client = self._client()
        if client is None:
            return None
        try:
            return client.get(self._key(key))
        except Exception as exc:
            logger.debug("Cache GET 失败 key=%s: %s", key, exc)
            return None

    def _set(self, key: str, value: str, ttl: int) -> bool:
        """安全 SET（带 TTL）。Redis 不可用时返回 False。"""
        client = self._client()
        if client is None:
            return False
        try:
            client.set(self._key(key), value, ex=ttl)
            return True
        except Exception as exc:
            logger.debug("Cache SET 失败 key=%s: %s", key, exc)
            return False

    def _delete(self, *keys: str) -> int:
        """安全 DELETE（批量删除）。返回实际删除数。"""
        client = self._client()
        if client is None or not keys:
            return 0
        try:
            full_keys = [self._key(k) for k in keys]
            return int(client.delete(*full_keys))
        except Exception as exc:
            logger.debug("Cache DELETE 失败 keys=%s: %s", keys, exc)
            return 0

    def _delete_pattern(self, pattern: str) -> int:
        """按 pattern 删除（用 SCAN 避免阻塞）。返回删除数。"""
        client = self._client()
        if client is None:
            return 0
        try:
            full_pattern = self._key(pattern)
            deleted = 0
            # 用 SCAN 分批扫描，避免 KEYS 阻塞
            cursor = 0
            while True:
                cursor, batch = client.scan(cursor=cursor, match=full_pattern, count=100)
                if batch:
                    deleted += int(client.delete(*batch))
                if cursor == 0:
                    break
            return deleted
        except Exception as exc:
            logger.debug("Cache DELETE_PATTERN 失败 pattern=%s: %s", pattern, exc)
            return 0

    # ------------------------------------------------------------------
    # 1. 书籍树缓存（SubTask 4.4）
    # ------------------------------------------------------------------

    def get_book_tree(self, book_id: int) -> dict[str, Any] | None:
        """获取书籍树缓存。"""
        return self._deserialize(self._get(f"book_tree:{book_id}"))

    def set_book_tree(self, book_id: int, tree: dict[str, Any]) -> bool:
        """写入书籍树缓存。"""
        return self._set(f"book_tree:{book_id}", self._serialize(tree), _BOOK_TREE_TTL)

    def invalidate_book_tree(self, book_id: int) -> int:
        """失效书籍树缓存。"""
        return self._delete(f"book_tree:{book_id}")

    # ------------------------------------------------------------------
    # 2. 章节内容缓存（SubTask 4.5）
    # ------------------------------------------------------------------

    def get_chapter(self, chapter_id: int) -> dict[str, Any] | None:
        """获取章节内容缓存。"""
        return self._deserialize(self._get(f"chapter:{chapter_id}"))

    def set_chapter(self, chapter_id: int, chapter: dict[str, Any]) -> bool:
        """写入章节内容缓存。"""
        return self._set(f"chapter:{chapter_id}", self._serialize(chapter), _CHAPTER_TTL)

    def invalidate_chapter(self, chapter_id: int) -> int:
        """失效章节内容缓存。"""
        return self._delete(f"chapter:{chapter_id}")

    def invalidate_chapters_for_book(self, book_id: int) -> int:
        """失效某本书所有章节缓存（章节编辑后调用）。"""
        return self._delete_pattern(f"chapter:*")
        # 注意：chapter payload 里含 book_id，但 key 不含，故需全量扫描
        # 实际章节编辑是单章级别，invalidate_chapter(chapter_id) 即可
        # 此方法仅在 delete_book 等批量场景使用

    # ------------------------------------------------------------------
    # 3. 分析运行状态缓存（SubTask 4.6）
    # ------------------------------------------------------------------

    def get_analysis_run(self, run_id: int) -> dict[str, Any] | None:
        """获取分析运行状态缓存。"""
        return self._deserialize(self._get(f"analysis_run:{run_id}"))

    def set_analysis_run(self, run_id: int, status: dict[str, Any]) -> bool:
        """写入分析运行状态缓存。"""
        return self._set(f"analysis_run:{run_id}", self._serialize(status), _ANALYSIS_RUN_TTL)

    def invalidate_analysis_run(self, run_id: int) -> int:
        """失效分析运行状态缓存。"""
        return self._delete(f"analysis_run:{run_id}")

    # ------------------------------------------------------------------
    # 4. 书籍列表缓存（附加，list_books 高频读）
    # ------------------------------------------------------------------

    def get_book_list(self, user_id: int) -> list[dict[str, Any]] | None:
        """获取书籍列表缓存。"""
        value = self._deserialize(self._get(f"book_list:{user_id}"))
        return value if isinstance(value, list) else None

    def set_book_list(self, user_id: int, books: list[dict[str, Any]]) -> bool:
        """写入书籍列表缓存。"""
        return self._set(f"book_list:{user_id}", self._serialize(books), _BOOK_LIST_TTL)

    def invalidate_book_list(self, user_id: int) -> int:
        """失效书籍列表缓存。"""
        return self._delete(f"book_list:{user_id}")

    def invalidate_all_book_lists(self) -> int:
        """失效所有书籍列表缓存（book_id 未知时用）。"""
        return self._delete_pattern("book_list:*")

    # ------------------------------------------------------------------
    # 5. 分布式锁（SubTask 4.7）
    # ------------------------------------------------------------------

    def acquire_analysis_lock(self, book_id: int, ttl: int = _ANALYSIS_LOCK_TTL) -> str | None:
        """获取书籍分析锁。

        用 SET NX EX 实现，成功返回 token（用于释放时验证）。
        锁已被持有则返回 None。
        """
        client = self._client()
        if client is None:
            # Redis 不可用时返回伪 token，允许无锁运行（单机模式）
            return f"nolock:{uuid.uuid4().hex}"

        token = uuid.uuid4().hex
        key = self._key(f"book:{book_id}:analysis_lock")
        try:
            # SET key value NX EX ttl —— 原子操作
            acquired = client.set(key, token, nx=True, ex=ttl)
            if acquired:
                return token
            return None
        except Exception as exc:
            logger.warning("acquire_analysis_lock 失败 book_id=%d: %s", book_id, exc)
            return f"nolock:{uuid.uuid4().hex}"  # 降级为无锁

    def release_analysis_lock(self, book_id: int, token: str) -> bool:
        """释放书籍分析锁。

        用 Lua 脚本保证原子性：只有 token 匹配才删除。
        """
        # 伪 token（Redis 不可用时的降级）直接返回 True
        if token.startswith("nolock:"):
            return True

        client = self._client()
        if client is None:
            return True

        # Lua 脚本：如果 key 的值等于 token 则删除，否则不操作
        lua_script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        key = self._key(f"book:{book_id}:analysis_lock")
        try:
            result = client.eval(lua_script, 1, key, token)
            return bool(result)
        except Exception as exc:
            logger.warning("release_analysis_lock 失败 book_id=%d: %s", book_id, exc)
            return False

    def is_analysis_locked(self, book_id: int) -> bool:
        """检查书籍是否正在分析中（锁是否被持有）。"""
        client = self._client()
        if client is None:
            return False
        try:
            return bool(client.exists(self._key(f"book:{book_id}:analysis_lock")))
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 高级工具：缓存回源
    # ------------------------------------------------------------------

    def get_or_set(
        self,
        key: str,
        ttl: int,
        loader: Callable[[], T | None],
    ) -> T | None:
        """通用缓存回源模式：先查缓存，未命中则调 loader 加载并回填。

        Redis 不可用时直接调 loader。
        """
        cached = self._deserialize(self._get(key))
        if cached is not None:
            return cached  # type: ignore[return-value]

        value = loader()
        if value is not None:
            self._set(key, self._serialize(value), ttl)
        return value

    # ------------------------------------------------------------------
    # 批量失效（写操作后调用）
    # ------------------------------------------------------------------

    def invalidate_on_book_write(self, book_id: int, *, also_book_list: bool = True) -> None:
        """书籍写操作后失效相关缓存。

        失效：book_tree:{book_id}（+ 可选 book_list:*）
        """
        self._delete(f"book_tree:{book_id}")
        if also_book_list:
            self._delete_pattern("book_list:*")

    def invalidate_on_chapter_write(self, book_id: int, chapter_id: int) -> None:
        """章节写操作后失效相关缓存。

        失效：chapter:{chapter_id} + book_tree:{book_id}
        """
        self._delete(f"chapter:{chapter_id}", f"book_tree:{book_id}")

    def invalidate_on_book_delete(self, book_id: int) -> None:
        """书籍删除后失效所有相关缓存。"""
        self._delete(f"book_tree:{book_id}")
        self._delete_pattern("book_list:*")
        # 章节缓存按 book_id 过滤（payload 含 book_id，但 key 不含）
        # 这里不做全量扫描，章节缓存的 TTL 会让它们自然过期
