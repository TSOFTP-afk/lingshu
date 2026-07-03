"""V3 分析向量存储：管理 analysis_blocks / entity_mentions / entity_summaries 三个 collection。

蓝图设计：
- analysis_blocks_{book_id}：block 文本摘要、章节、hash
- entity_mentions_{book_id}：mention、上下文、候选实体
- entity_summaries_{book_id}：canonical_name、aliases、summary

用途：
1. 共指消解：mention 上下文向量辅助消歧
2. 探针定位：根据实体摘要向量定位相关 block
3. 记忆检索：短期/长期记忆向量分离检索

实现：基于 HNSWStore（faiss-cpu），替代原 QdrantLocalClient。
- 向量持久化到 SQLite vectors 表（storage_dir/vectors.db）
- 内存 HNSW 索引提供亚秒级近似最近邻搜索
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from novel_app.db.hnsw_store import HNSWStore
from novel_app.rag.embedder import APIEmbedder, FallbackEmbedder

logger = logging.getLogger(__name__)

VECTOR_SIZE = 256


class AnalysisVectorStore:
    """V3 分析专用向量存储，管理三个 collection。"""

    def __init__(
        self,
        storage_dir: str | Path,
        embedder: APIEmbedder | FallbackEmbedder | None = None,
        *,
        db_path: str | Path | None = None,
    ) -> None:
        storage_dir = Path(storage_dir)
        storage_dir.mkdir(parents=True, exist_ok=True)
        # 优先用显式传入的 db_path，否则用 storage_dir/vectors.db
        resolved_db_path = Path(db_path) if db_path else storage_dir / "vectors.db"
        self._client = HNSWStore(resolved_db_path, storage_dir=storage_dir)
        self._embedder = embedder or FallbackEmbedder(dim=VECTOR_SIZE)
        self._vector_size = VECTOR_SIZE

    # ------------------------------------------------------------------
    # Collection 管理
    # ------------------------------------------------------------------

    def _blocks_collection(self, book_id: int) -> str:
        return f"analysis_blocks_{book_id}"

    def _mentions_collection(self, book_id: int) -> str:
        return f"entity_mentions_{book_id}"

    def _summaries_collection(self, book_id: int) -> str:
        return f"entity_summaries_{book_id}"

    def _ensure_collection(self, collection_name: str) -> None:
        if not self._client.collection_exists(collection_name):
            self._client.create_collection(collection_name, self._vector_size)

    # ------------------------------------------------------------------
    # Block 向量索引
    # ------------------------------------------------------------------

    def index_block(
        self,
        book_id: int,
        block_uid: str,
        chapter_id: int,
        text: str,
        content_hash: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """索引一个分析 block。"""
        collection = self._blocks_collection(book_id)
        self._ensure_collection(collection)
        text_to_embed = str(text or "").strip()[:3000]
        if not text_to_embed:
            return
        vector = self._embedder.embed_single(text_to_embed)
        if not vector:
            return
        point_id = f"block:{block_uid}"
        payload = {
            "doc_type": "analysis_block",
            "book_id": book_id,
            "chapter_id": chapter_id,
            "block_uid": block_uid,
            "content_hash": content_hash,
            "text_snippet": text_to_embed[:500],
            **(metadata or {}),
        }
        self._client.upsert(collection, [{"id": point_id, "vector": vector, "payload": payload}])

    def index_blocks_batch(
        self,
        book_id: int,
        blocks: list[dict[str, Any]],
    ) -> int:
        """批量索引 blocks，返回成功索引数量。"""
        if not blocks:
            return 0
        collection = self._blocks_collection(book_id)
        self._ensure_collection(collection)
        texts = [str(b.get("text") or "")[:3000].strip() for b in blocks]
        vectors = self._embedder.embed(texts)
        points: list[dict[str, Any]] = []
        for block, vector, text in zip(blocks, vectors, texts, strict=False):
            if not text or not vector:
                continue
            block_uid = str(block.get("block_uid") or "")
            point_id = f"block:{block_uid}"
            payload = {
                "doc_type": "analysis_block",
                "book_id": book_id,
                "chapter_id": block.get("chapter_id"),
                "block_uid": block_uid,
                "content_hash": str(block.get("content_hash") or ""),
                "text_snippet": text[:500],
            }
            points.append({"id": point_id, "vector": vector, "payload": payload})
        if points:
            self._client.upsert(collection, points)
        return len(points)

    def search_blocks(
        self,
        book_id: int,
        query: str,
        top_k: int = 10,
        chapter_id: int | None = None,
        score_threshold: float = 0.3,
    ) -> list[dict[str, Any]]:
        """搜索与 query 相似的 blocks。"""
        collection = self._blocks_collection(book_id)
        if not self._client.collection_exists(collection):
            return []
        query_vector = self._embedder.embed_single(query)
        if not query_vector:
            return []
        filter_condition = None
        if chapter_id is not None:
            filter_condition = {"chapter_id": chapter_id}
        return self._client.search(
            collection, query_vector, limit=top_k,
            score_threshold=score_threshold,
            filter_condition=filter_condition,
        )

    def remove_blocks_for_chapter(self, book_id: int, chapter_id: int) -> list[int | str]:
        """删除指定章节的 block 向量。"""
        collection = self._blocks_collection(book_id)
        if not self._client.collection_exists(collection):
            return []
        return self._client.delete_by_filter(
            collection,
            {"doc_type": "analysis_block", "book_id": book_id, "chapter_id": chapter_id},
        )

    # ------------------------------------------------------------------
    # Entity Mention 向量索引
    # ------------------------------------------------------------------

    def index_mention(
        self,
        book_id: int,
        mention_uid: str,
        quote_text: str,
        context: str,
        entity_type: str,
        candidate_entity_uid: str = "",
        chapter_id: int | None = None,
        block_uid: str = "",
    ) -> None:
        """索引一个实体提及。"""
        collection = self._mentions_collection(book_id)
        self._ensure_collection(collection)
        text_to_embed = f"{quote_text}\n{context}".strip()[:3000]
        if not text_to_embed:
            return
        vector = self._embedder.embed_single(text_to_embed)
        if not vector:
            return
        point_id = f"mention:{mention_uid}"
        payload = {
            "doc_type": "entity_mention",
            "book_id": book_id,
            "mention_uid": mention_uid,
            "entity_type": entity_type,
            "candidate_entity_uid": candidate_entity_uid,
            "chapter_id": chapter_id,
            "block_uid": block_uid,
            "quote_text": quote_text[:300],
        }
        self._client.upsert(collection, [{"id": point_id, "vector": vector, "payload": payload}])

    def index_mentions_batch(
        self,
        book_id: int,
        mentions: list[dict[str, Any]],
    ) -> int:
        """批量索引 mentions，返回成功索引数量。"""
        if not mentions:
            return 0
        collection = self._mentions_collection(book_id)
        self._ensure_collection(collection)
        texts = []
        for m in mentions:
            quote = str(m.get("quote_text") or "")
            context = str(m.get("context") or "")
            texts.append(f"{quote}\n{context}".strip()[:3000])
        vectors = self._embedder.embed(texts)
        points: list[dict[str, Any]] = []
        for mention, vector, text in zip(mentions, vectors, texts, strict=False):
            if not text or not vector:
                continue
            mention_uid = str(mention.get("mention_uid") or "")
            point_id = f"mention:{mention_uid}"
            payload = {
                "doc_type": "entity_mention",
                "book_id": book_id,
                "mention_uid": mention_uid,
                "entity_type": str(mention.get("entity_type") or ""),
                "candidate_entity_uid": str(mention.get("candidate_entity_uid") or ""),
                "chapter_id": mention.get("chapter_id"),
                "block_uid": str(mention.get("block_uid") or ""),
                "quote_text": str(mention.get("quote_text") or "")[:300],
            }
            points.append({"id": point_id, "vector": vector, "payload": payload})
        if points:
            self._client.upsert(collection, points)
        return len(points)

    def search_similar_mentions(
        self,
        book_id: int,
        query_text: str,
        top_k: int = 10,
        entity_type: str | None = None,
        score_threshold: float = 0.4,
    ) -> list[dict[str, Any]]:
        """搜索与 query_text 语义相似的 mentions（用于共指消解辅助）。"""
        collection = self._mentions_collection(book_id)
        if not self._client.collection_exists(collection):
            return []
        query_vector = self._embedder.embed_single(query_text)
        if not query_vector:
            return []
        filter_condition = None
        if entity_type:
            filter_condition = {"entity_type": entity_type}
        return self._client.search(
            collection, query_vector, limit=top_k,
            score_threshold=score_threshold,
            filter_condition=filter_condition,
        )

    # ------------------------------------------------------------------
    # Entity Summary 向量索引
    # ------------------------------------------------------------------

    def index_entity_summary(
        self,
        book_id: int,
        entity_uid: str,
        canonical_name: str,
        aliases: list[str],
        summary: str,
        entity_type: str = "character",
    ) -> None:
        """索引一个实体摘要。"""
        collection = self._summaries_collection(book_id)
        self._ensure_collection(collection)
        aliases_text = "、".join(aliases) if aliases else ""
        text_to_embed = f"{canonical_name}\n{aliases_text}\n{summary}".strip()[:3000]
        if not text_to_embed:
            return
        vector = self._embedder.embed_single(text_to_embed)
        if not vector:
            return
        point_id = f"entity:{entity_uid}"
        payload = {
            "doc_type": "entity_summary",
            "book_id": book_id,
            "entity_uid": entity_uid,
            "canonical_name": canonical_name,
            "aliases": aliases[:20],
            "entity_type": entity_type,
            "summary": summary[:500],
        }
        self._client.upsert(collection, [{"id": point_id, "vector": vector, "payload": payload}])

    def index_entity_summaries_batch(
        self,
        book_id: int,
        entities: list[dict[str, Any]],
    ) -> int:
        """批量索引实体摘要，返回成功索引数量。"""
        if not entities:
            return 0
        collection = self._summaries_collection(book_id)
        self._ensure_collection(collection)
        texts = []
        for e in entities:
            name = str(e.get("canonical_name") or "")
            aliases = e.get("aliases") or []
            if isinstance(aliases, str):
                aliases = aliases.split(",") if aliases else []
            aliases_text = "、".join(str(a) for a in aliases[:10])
            summary = str(e.get("summary") or "")
            texts.append(f"{name}\n{aliases_text}\n{summary}".strip()[:3000])
        vectors = self._embedder.embed(texts)
        points: list[dict[str, Any]] = []
        for entity, vector, text in zip(entities, vectors, texts, strict=False):
            if not text or not vector:
                continue
            entity_uid = str(entity.get("entity_uid") or "")
            point_id = f"entity:{entity_uid}"
            aliases = entity.get("aliases") or []
            if isinstance(aliases, str):
                aliases = aliases.split(",") if aliases else []
            payload = {
                "doc_type": "entity_summary",
                "book_id": book_id,
                "entity_uid": entity_uid,
                "canonical_name": str(entity.get("canonical_name") or ""),
                "aliases": aliases[:20],
                "entity_type": str(entity.get("entity_type") or ""),
                "summary": str(entity.get("summary") or "")[:500],
            }
            points.append({"id": point_id, "vector": vector, "payload": payload})
        if points:
            self._client.upsert(collection, points)
        return len(points)

    def search_similar_entities(
        self,
        book_id: int,
        query_text: str,
        top_k: int = 10,
        entity_type: str | None = None,
        score_threshold: float = 0.4,
    ) -> list[dict[str, Any]]:
        """搜索与 query_text 语义相似的实体摘要（用于共指消解辅助）。"""
        collection = self._summaries_collection(book_id)
        if not self._client.collection_exists(collection):
            return []
        query_vector = self._embedder.embed_single(query_text)
        if not query_vector:
            return []
        filter_condition = None
        if entity_type:
            filter_condition = {"entity_type": entity_type}
        return self._client.search(
            collection, query_vector, limit=top_k,
            score_threshold=score_threshold,
            filter_condition=filter_condition,
        )

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_stats(self, book_id: int) -> dict[str, int]:
        """返回三个 collection 的点数量。"""
        return {
            "blocks": self._client.count(self._blocks_collection(book_id)),
            "mentions": self._client.count(self._mentions_collection(book_id)),
            "summaries": self._client.count(self._summaries_collection(book_id)),
        }
