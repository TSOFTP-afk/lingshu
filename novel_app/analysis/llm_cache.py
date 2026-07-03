"""LLM 阶段缓存 — 读写 analysis_llm_cache 表。

每个 V3 分析阶段（mention、coreference、fact、card、memory、probe）
独立维护 prompt_version / schema_version / input_hash，命中缓存时直接返回
已保存的 output_json，跳过远程调用。
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from novel_app.database import Database

logger = logging.getLogger(__name__)


class LLMCache:
    """对 analysis_llm_cache 表的读写封装。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def get(
        self,
        *,
        stage: str,
        prompt_version: str,
        schema_version: str,
        input_payload: Any,
    ) -> dict[str, Any] | None:
        """查询缓存，命中时返回 output_json，否则返回 None。"""
        cache_key = self._cache_key(stage, prompt_version, schema_version, input_payload)
        input_hash = self._input_hash(input_payload)
        cursor = self.database.connection.execute(
            "SELECT output_json FROM analysis_llm_cache WHERE cache_key = ? AND input_hash = ?",
            (cache_key, input_hash),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        raw = str(row["output_json"] or "{}")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("LLM cache entry %s has invalid JSON, ignoring", cache_key)
            return None
        if not isinstance(value, dict):
            return None
        logger.debug("LLM cache hit: stage=%s key=%s", stage, cache_key[:24])
        return value

    def put(
        self,
        *,
        stage: str,
        prompt_version: str,
        schema_version: str,
        input_payload: Any,
        output: dict[str, Any],
    ) -> str:
        """写入缓存，返回 cache_key。"""
        cache_key = self._cache_key(stage, prompt_version, schema_version, input_payload)
        input_hash = self._input_hash(input_payload)
        output_json = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
        self.database.connection.execute(
            """
            INSERT OR REPLACE INTO analysis_llm_cache
                (cache_key, stage, prompt_version, schema_version, input_hash, output_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (cache_key, stage, prompt_version, schema_version, input_hash, output_json),
        )
        logger.debug("LLM cache write: stage=%s key=%s", stage, cache_key[:24])
        return cache_key

    def invalidate_stage(self, stage: str) -> int:
        """清除某个阶段的所有缓存，返回删除行数。"""
        cursor = self.database.connection.execute(
            "DELETE FROM analysis_llm_cache WHERE stage = ?",
            (stage,),
        )
        return cursor.rowcount

    def invalidate_book(self, book_id: int) -> int:
        """清除与某本书相关的缓存（按 stage 前缀匹配），返回删除行数。"""
        cursor = self.database.connection.execute(
            "DELETE FROM analysis_llm_cache WHERE stage LIKE ?",
            (f"%book_{book_id}%",),
        )
        return cursor.rowcount

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(stage: str, prompt_version: str, schema_version: str, input_payload: Any) -> str:
        seed = json.dumps(
            {"stage": stage, "pv": prompt_version, "sv": schema_version, "input": input_payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        return f"LLMCACHE-{stage}-{digest[:32]}"

    @staticmethod
    def _input_hash(input_payload: Any) -> str:
        raw = json.dumps(input_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
