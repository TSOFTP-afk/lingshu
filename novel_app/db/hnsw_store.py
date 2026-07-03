"""HNSW 向量存储 —— hybrid-database-architecture spec Task 2 实现。

用 faiss-cpu 的 IndexHNSWFlat 替代 QdrantLocalClient，提供：
- 内存 HNSW 索引（近似最近邻搜索，亚秒级延迟）
- SQLite `vectors` 表持久化（重启后可从 SQLite 重建索引）
- API 兼容 QdrantLocalClient（create_collection/upsert/search/delete/count 等）

设计要点：
1. **延迟重建策略**：faiss HNSW 不支持 remove_ids，故 upsert/delete 仅写 SQLite +
   标记 `_dirty`，search 时若 dirty 则从 SQLite 全量重建索引。批量 upsert 后首次
   search 承担重建成本，后续 search 直接走内存索引。
2. **ID 映射**：faiss label 用 SQLite vectors.id（int64 自增），point_id（int|str）
   存 TEXT，通过 `_label_to_point_id` / `_point_id_to_label` 双向映射。
3. **cosine 相似度**：向量入库前归一化，用 METRIC_INNER_PRODUCT 搜索，返回的
   distance 即 cosine 相似度（越大越相似，与 QdrantLocalClient 语义一致）。
4. **filter_condition**：faiss 不支持原生过滤，采用过采样策略——search limit*10
   个结果后在 Python 层按 payload 过滤。
5. **懒加载**：collection 第一次访问时才从 SQLite 加载，避免启动时全量加载。

spec 原写 hnswlib，因 Python 3.13 + Windows 无预编译 wheel 改用 faiss-cpu，
算法等价（HNSW），性能相当，且有预编译 wheel 便于 EXE 打包。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

import faiss
import numpy as np

logger = logging.getLogger(__name__)

# HNSW 参数
_DEFAULT_M = 32  # 每个节点的连接数（内存与精度权衡，32 适合中等规模）
_DEFAULT_EF_CONSTRUCTION = 40  # 构建时的 ef（越大精度越高但构建越慢）
_DEFAULT_EF_SEARCH = 64  # 搜索时的 ef（越大精度越高但搜索越慢）
_OVERSAMPLE_FACTOR = 10  # filter_condition 时的过采样倍数


class HNSWStore:
    """基于 faiss-cpu 的 HNSW 向量存储，API 兼容 QdrantLocalClient。

    持久化到 SQLite `vectors` 表（由 schema.py 的 _apply_hnsw_vectors_migration 创建）。
    内存索引按 collection 懒加载，upsert/delete 标记 dirty，search 时按需重建。
    """

    def __init__(
        self,
        db_path: Path | str,
        *,
        storage_dir: Path | str | None = None,
        m: int = _DEFAULT_M,
        ef_construction: int = _DEFAULT_EF_CONSTRUCTION,
        ef_search: int = _DEFAULT_EF_SEARCH,
    ) -> None:
        self._db_path = Path(db_path)
        self._storage_dir = Path(storage_dir) if storage_dir else self._db_path.parent / "hnsw_data"
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._m = m
        self._ef_construction = ef_construction
        self._ef_search = ef_search

        self._lock = threading.RLock()
        # 按 collection 组织的内存状态
        # _collections[name] = {
        #     "faiss_index": faiss.IndexIDMap2,
        #     "base_index": faiss.IndexHNSWFlat,  # 用于调参
        #     "dim": int,
        #     "label_to_point_id": dict[int, str],
        #     "point_id_to_label": dict[str, int],
        #     "payloads": dict[str, dict],
        #     "loaded": bool,
        #     "dirty": bool,
        # }
        self._collections: dict[str, dict[str, Any]] = {}
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """确保 vectors 表存在（支持独立 db 文件或复用 novels.db）。

        schema 与 schema.py 的 _apply_hnsw_vectors_migration 一致，
        此处用 CREATE TABLE IF NOT EXISTS 保证幂等。
        """
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS vectors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection TEXT NOT NULL,
                    point_id TEXT NOT NULL,
                    vector_blob BLOB NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    dim INTEGER NOT NULL DEFAULT 0,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(collection, point_id)
                );
                CREATE INDEX IF NOT EXISTS idx_vectors_collection
                    ON vectors(collection);
                CREATE INDEX IF NOT EXISTS idx_vectors_collection_point
                    ON vectors(collection, point_id);
                """
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # SQLite 连接（每次操作新建短连接，避免跨线程问题）
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    # ------------------------------------------------------------------
    # Collection 管理
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_collection_name(collection_name: str) -> str:
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in collection_name)

    def _ensure_collection_loaded(self, collection_name: str) -> dict[str, Any]:
        """确保 collection 的内存状态已加载（懒加载）。"""
        safe_name = self._safe_collection_name(collection_name)
        with self._lock:
            state = self._collections.get(safe_name)
            if state is None:
                state = {
                    "faiss_index": None,
                    "base_index": None,
                    "dim": 0,
                    "label_to_point_id": {},
                    "point_id_to_label": {},
                    "payloads": {},
                    "loaded": False,
                    "dirty": False,
                }
                self._collections[safe_name] = state
            if not state["loaded"]:
                self._load_collection_from_sqlite(safe_name, state)
                state["loaded"] = True
                state["dirty"] = False
            return state

    def _load_collection_from_sqlite(self, safe_name: str, state: dict[str, Any]) -> None:
        """从 SQLite vectors 表加载 collection 数据并重建 faiss 索引。"""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id, point_id, vector_blob, payload_json, dim FROM vectors WHERE collection = ?",
                (safe_name,),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return

        dim = int(rows[0]["dim"]) if rows[0]["dim"] else 0
        if dim <= 0:
            # 从 vector_blob 推断 dim
            blob = rows[0]["vector_blob"]
            dim = len(blob) // 4  # float32 = 4 bytes

        state["dim"] = dim
        index, base = self._create_faiss_index(dim)
        state["faiss_index"] = index
        state["base_index"] = base

        vectors: list[np.ndarray] = []
        labels: list[int] = []
        for row in rows:
            label = int(row["id"])
            point_id = str(row["point_id"])
            try:
                vec = np.frombuffer(row["vector_blob"], dtype=np.float32)
            except ValueError:
                logger.warning("HNSWStore: 跳过 collection=%s point_id=%s 的损坏向量", safe_name, point_id)
                continue
            if len(vec) != dim:
                logger.warning(
                    "HNSWStore: 跳过 dim 不匹配的向量 collection=%s point_id=%s expected=%d got=%d",
                    safe_name, point_id, dim, len(vec),
                )
                continue
            state["label_to_point_id"][label] = point_id
            state["point_id_to_label"][point_id] = label
            try:
                state["payloads"][point_id] = json.loads(row["payload_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                state["payloads"][point_id] = {}
            vectors.append(vec)
            labels.append(label)

        if vectors:
            matrix = np.vstack(vectors).astype(np.float32, copy=False)
            label_array = np.array(labels, dtype=np.int64)
            index.add_with_ids(matrix, label_array)
        logger.info("HNSWStore: 加载 collection=%s 向量数=%d dim=%d", safe_name, len(vectors), dim)

    def _create_faiss_index(self, dim: int) -> tuple[faiss.IndexIDMap2, faiss.IndexHNSWFlat]:
        """创建新的 faiss HNSW 索引（用 IDMap2 包装支持自定义 id）。"""
        base = faiss.IndexHNSWFlat(dim, self._m, faiss.METRIC_INNER_PRODUCT)
        base.hnsw.efConstruction = self._ef_construction
        base.hnsw.efSearch = self._ef_search
        index = faiss.IndexIDMap2(base)
        return index, base

    def create_collection(self, collection_name: str, vector_size: int, distance: str = "Cosine") -> bool:
        """创建 collection（幂等，已存在返回 False）。

        实际上 HNSWStore 的 collection 是逻辑概念，无需预创建。
        此方法仅为 API 兼容，记录 dim 信息。
        """
        safe_name = self._safe_collection_name(collection_name)
        with self._lock:
            state = self._collections.get(safe_name)
            if state is not None and state["loaded"]:
                return False
            # 检查 SQLite 是否已有数据
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT dim FROM vectors WHERE collection = ? LIMIT 1",
                    (safe_name,),
                ).fetchone()
            finally:
                conn.close()
            if row:
                # SQLite 已有数据，懒加载时会自动加载
                return False
            # 创建空状态
            self._collections[safe_name] = {
                "faiss_index": None,
                "base_index": None,
                "dim": int(vector_size),
                "label_to_point_id": {},
                "point_id_to_label": {},
                "payloads": {},
                "loaded": True,
                "dirty": False,
            }
            return True

    def collection_exists(self, collection_name: str) -> bool:
        """检查 collection 是否存在（有数据或已创建）。"""
        safe_name = self._safe_collection_name(collection_name)
        with self._lock:
            state = self._collections.get(safe_name)
            if state is not None and state["loaded"] and (state["payloads"] or state["faiss_index"] is not None):
                return True
            # 检查 SQLite
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT 1 FROM vectors WHERE collection = ? LIMIT 1",
                    (safe_name,),
                ).fetchone()
            finally:
                conn.close()
            return row is not None

    def get_collection_info(self, collection_name: str) -> dict[str, Any] | None:
        """返回 collection 元信息（vector_size, distance, count）。"""
        safe_name = self._safe_collection_name(collection_name)
        with self._lock:
            state = self._ensure_collection_loaded(safe_name)
            if not state["payloads"] and state["dim"] == 0:
                return None
            return {
                "vector_size": state["dim"],
                "distance": "Cosine",
                "points_count": len(state["payloads"]),
            }

    # ------------------------------------------------------------------
    # 向量写入
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_vector(vec: list[float]) -> np.ndarray:
        """归一化向量（cosine 相似度要求）。"""
        arr = np.asarray(vec, dtype=np.float32)
        norm = float(np.linalg.norm(arr))
        if norm > 0:
            arr = arr / norm
        return arr.astype(np.float32, copy=False)

    def upsert(self, collection_name: str, points: list[dict[str, Any]]) -> None:
        """批量 upsert 向量。

        每个 point: {"id": int|str, "vector": list[float], "payload": dict}
        策略：写 SQLite（INSERT OR REPLACE）+ 标记 dirty。
        search 时若 dirty 则全量重建 faiss 索引。
        """
        if not points:
            return
        safe_name = self._safe_collection_name(collection_name)
        with self._lock:
            state = self._ensure_collection_loaded(safe_name)
            dim = state["dim"]
            conn = self._connect()
            try:
                for point in points:
                    point_id = str(point["id"])
                    vec = point.get("vector", [])
                    if not vec:
                        continue
                    if dim == 0:
                        dim = len(vec)
                        state["dim"] = dim
                    elif len(vec) != dim:
                        logger.warning(
                            "HNSWStore: 跳过 dim 不匹配的向量 collection=%s point_id=%s expected=%d got=%d",
                            safe_name, point_id, dim, len(vec),
                        )
                        continue
                    vec_arr = self._normalize_vector(vec)
                    payload = point.get("payload", {}) or {}
                    payload_json = json.dumps(payload, ensure_ascii=False)
                    conn.execute(
                        """
                        INSERT INTO vectors (collection, point_id, vector_blob, payload_json, dim, updated_at)
                        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(collection, point_id) DO UPDATE SET
                            vector_blob = excluded.vector_blob,
                            payload_json = excluded.payload_json,
                            dim = excluded.dim,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (safe_name, point_id, vec_arr.tobytes(), payload_json, dim),
                    )
                    # 同步更新内存映射（不更新 faiss 索引，标记 dirty）
                    state["payloads"][point_id] = payload
                conn.commit()
            finally:
                conn.close()
            state["dirty"] = True

    # ------------------------------------------------------------------
    # 向量删除
    # ------------------------------------------------------------------

    def delete(self, collection_name: str, point_ids: list[int | str]) -> None:
        """按 point_id 删除向量。"""
        if not point_ids:
            return
        safe_name = self._safe_collection_name(collection_name)
        with self._lock:
            state = self._ensure_collection_loaded(safe_name)
            conn = self._connect()
            try:
                for pid in point_ids:
                    pid_str = str(pid)
                    conn.execute(
                        "DELETE FROM vectors WHERE collection = ? AND point_id = ?",
                        (safe_name, pid_str),
                    )
                    state["payloads"].pop(pid_str, None)
                conn.commit()
            finally:
                conn.close()
            state["dirty"] = True

    def delete_by_filter(self, collection_name: str, filter_condition: dict[str, Any]) -> list[int | str]:
        """按 payload 过滤条件删除向量，返回被删除的 point_id 列表。"""
        if not filter_condition:
            return []
        safe_name = self._safe_collection_name(collection_name)
        with self._lock:
            state = self._ensure_collection_loaded(safe_name)
            deleted_ids: list[str] = []
            for point_id, payload in list(state["payloads"].items()):
                if self._match_filter(payload, filter_condition):
                    deleted_ids.append(point_id)
            if deleted_ids:
                conn = self._connect()
                try:
                    conn.executemany(
                        "DELETE FROM vectors WHERE collection = ? AND point_id = ?",
                        [(safe_name, pid) for pid in deleted_ids],
                    )
                    conn.commit()
                finally:
                    conn.close()
                for pid in deleted_ids:
                    state["payloads"].pop(pid, None)
                state["dirty"] = True
            return deleted_ids

    # ------------------------------------------------------------------
    # 向量搜索
    # ------------------------------------------------------------------

    def _rebuild_if_dirty(self, safe_name: str, state: dict[str, Any]) -> None:
        """如果 collection 标记为 dirty，从 SQLite 全量重建 faiss 索引。"""
        if not state["dirty"]:
            return
        state["faiss_index"] = None
        state["base_index"] = None
        state["label_to_point_id"] = {}
        state["point_id_to_label"] = {}
        state["loaded"] = False
        state["dirty"] = False
        self._load_collection_from_sqlite(safe_name, state)
        state["loaded"] = True

    def search(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int = 10,
        score_threshold: float | None = None,
        filter_condition: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """搜索与 query_vector 最相似的向量。

        返回 [{"id", "score", "payload"}]，score 为 cosine 相似度（越大越相似）。
        """
        safe_name = self._safe_collection_name(collection_name)
        with self._lock:
            state = self._ensure_collection_loaded(safe_name)
            if state["faiss_index"] is None and not state["payloads"]:
                return []
            self._rebuild_if_dirty(safe_name, state)
            index = state["faiss_index"]
            if index is None or index.ntotal == 0:
                return []

            query_arr = self._normalize_vector(query_vector).reshape(1, -1)
            # filter_condition 需要过采样
            search_k = limit * _OVERSAMPLE_FACTOR if filter_condition else limit
            search_k = min(search_k, index.ntotal)
            if search_k <= 0:
                return []

            distances, labels = index.search(query_arr, search_k)
            results: list[dict[str, Any]] = []
            for score, label in zip(distances[0], labels[0], strict=False):
                if label < 0:  # faiss 返回 -1 表示不足
                    continue
                point_id = state["label_to_point_id"].get(int(label))
                if point_id is None:
                    continue
                payload = state["payloads"].get(point_id, {})
                if score_threshold is not None and float(score) < score_threshold:
                    continue
                if filter_condition and not self._match_filter(payload, filter_condition):
                    continue
                # 还原 point_id 的原始类型（int 或 str）
                original_id = self._restore_point_id_type(point_id)
                results.append({"id": original_id, "score": float(score), "payload": payload})
                if len(results) >= limit:
                    break
            return results

    @staticmethod
    def _restore_point_id_type(point_id: str) -> int | str:
        """尝试将 point_id 还原为 int（如果原始是 int）。"""
        try:
            int_val = int(point_id)
            # 确保转换是可逆的（避免 "01" → 1 的信息丢失）
            if str(int_val) == point_id:
                return int_val
        except ValueError:
            pass
        return point_id

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def count(self, collection_name: str) -> int:
        """返回 collection 中的向量数。"""
        safe_name = self._safe_collection_name(collection_name)
        with self._lock:
            state = self._ensure_collection_loaded(safe_name)
            return len(state["payloads"])

    # ------------------------------------------------------------------
    # 过滤匹配（与 QdrantLocalClient._match_filter 语义一致）
    # ------------------------------------------------------------------

    @staticmethod
    def _match_filter(payload: dict[str, Any], condition: dict[str, Any]) -> bool:
        for key, value in condition.items():
            if key not in payload:
                return False
            if isinstance(value, dict):
                if not HNSWStore._match_filter(payload[key], value):
                    return False
            elif payload[key] != value:
                return False
        return True

    # ------------------------------------------------------------------
    # 维护
    # ------------------------------------------------------------------

    def flush(self, collection_name: str | None = None) -> None:
        """手动触发索引重建（清除 dirty 标记）。

        如果指定 collection_name，只重建该 collection；否则重建所有 dirty 的 collection。
        """
        with self._lock:
            names = [self._safe_collection_name(collection_name)] if collection_name else list(self._collections.keys())
            for name in names:
                state = self._collections.get(name)
                if state and state["dirty"]:
                    self._rebuild_if_dirty(name, state)

    def close(self) -> None:
        """释放内存索引。"""
        with self._lock:
            self._collections.clear()
