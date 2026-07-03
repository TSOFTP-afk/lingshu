"""实体共指消解 — 章内同名聚类 + 跨章合并 + 称谓链消解。

Phase 1: 同名/规范化同名聚类（原有逻辑）
Phase 2: 称谓链消解（师父→他、师姐→她等代词/称谓关联）
Phase 3: 跨章合并（名称相似 + 别名显式 + 时间线不冲突）
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from novel_app.analysis.entity_resolver import normalize_entity_alias, normalize_entity_type, stable_entity_uid
from novel_app.analysis.schemas_v3 import ANALYSIS_V3_SCHEMA_VERSION, ResolvedEntityCandidate

# ---------------------------------------------------------------------------
# 称谓链规则：代词/称谓 → 可能指向的实体类型
# ---------------------------------------------------------------------------
_APPELLATION_PATTERNS: list[tuple[str, str, float]] = [
    # (称谓关键词, 推断的实体类型, 置信度加成)
    ("师父", "character", 0.15),
    ("师傅", "character", 0.15),
    ("师尊", "character", 0.15),
    ("师叔", "character", 0.12),
    ("师伯", "character", 0.12),
    ("师姐", "character", 0.12),
    ("师妹", "character", 0.12),
    ("师兄", "character", 0.12),
    ("师弟", "character", 0.12),
    ("道友", "character", 0.08),
    ("前辈", "character", 0.08),
    ("晚辈", "character", 0.08),
    ("掌门", "character", 0.10),
    ("长老", "character", 0.10),
    ("阁主", "character", 0.10),
    ("城主", "character", 0.10),
    ("族长", "character", 0.10),
    ("父亲", "character", 0.15),
    ("母亲", "character", 0.15),
    ("兄长", "character", 0.12),
    ("姐姐", "character", 0.12),
    ("弟弟", "character", 0.12),
    ("妹妹", "character", 0.12),
    ("爷爷", "character", 0.15),
    ("奶奶", "character", 0.15),
]

# 名称相似度阈值：编辑距离 / max(len_a, len_b) < 此值视为相似
_NAME_SIMILARITY_THRESHOLD = 0.45
_VECTOR_BUCKET_LIMIT = int(os.environ.get("LINGSHU_ANALYSIS_V3_COREFERENCE_VECTOR_BUCKET_LIMIT", "600") or 600)
_PAIR_CHECK_LIMIT = int(os.environ.get("LINGSHU_ANALYSIS_V3_COREFERENCE_PAIR_LIMIT", "350000") or 350000)
_TIME_LIMIT_SECONDS = int(os.environ.get("LINGSHU_ANALYSIS_V3_COREFERENCE_TIMEOUT_SECONDS", "540") or 540)

logger = logging.getLogger(__name__)


class CoreferenceResolver:
    def __init__(self, vector_store: Any | None = None) -> None:
        self._vector_store = vector_store

    def resolve_mentions(
        self,
        *,
        book_id: int,
        mentions: Iterable[dict[str, Any]],
    ) -> list[ResolvedEntityCandidate]:
        mention_list = list(mentions)

        # Phase 1: 同名/规范化同名聚类
        buckets = self._phase1_same_name_clustering(book_id, mention_list)

        # Phase 2: 称谓链消解 — 将称谓型 mention 关联到最近的同名实体
        self._phase2_appellation_linking(buckets, mention_list)

        # Phase 3: 跨章合并 — 名称相似 + 别名显式 + 时间线不冲突
        buckets = self._phase3_cross_chapter_merge(buckets, book_id)

        # 构建最终实体列表
        entities: list[ResolvedEntityCandidate] = []
        for (entity_type, normalized), bucket in buckets.items():
            quotes = [str(item.get("quote_text") or "").strip() for item in bucket if str(item.get("quote_text") or "").strip()]
            if not quotes:
                continue
            canonical = self._canonical_name(quotes)
            aliases = tuple(sorted({quote for quote in quotes if quote != canonical}))
            confidences = [float(item.get("confidence") or 0.0) for item in bucket]
            confidence = round(sum(confidences) / max(1, len(confidences)), 3)
            mention_uids = tuple(str(item.get("mention_uid") or "") for item in bucket if str(item.get("mention_uid") or "").strip())
            source_rule = self._source_rule(bucket)
            entity_uid = stable_entity_uid(entity_type, canonical or normalized, book_id=book_id)
            chapter_ids = sorted({
                int(item.get("chapter_id") or 0)
                for item in bucket
                if _int_or_none(item.get("chapter_id")) is not None
            })
            entities.append(
                ResolvedEntityCandidate(
                    entity_uid=entity_uid,
                    entity_type=entity_type,
                    canonical_name=canonical,
                    aliases=aliases,
                    mention_uids=mention_uids,
                    confidence=confidence,
                    status="candidate",
                    source_rule=source_rule,
                    metadata={
                        "schema_version": ANALYSIS_V3_SCHEMA_VERSION,
                        "normalized_text": normalized,
                        "mention_count": len(mention_uids),
                        "chapter_ids": chapter_ids,
                        "source_rules": sorted({str(item.get("source_rule") or "") for item in bucket if str(item.get("source_rule") or "").strip()}),
                    },
                )
            )
        return sorted(entities, key=lambda item: (item.entity_type, item.canonical_name, item.entity_uid))

    # ------------------------------------------------------------------
    # Phase 1: 同名/规范化同名聚类
    # ------------------------------------------------------------------

    def _phase1_same_name_clustering(
        self,
        book_id: int,
        mentions: list[dict[str, Any]],
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for mention in mentions:
            entity_type = normalize_entity_type(mention.get("entity_type"), "concept")
            normalized = normalize_entity_alias(mention.get("normalized_text") or mention.get("quote_text"))
            if not normalized:
                continue
            buckets[(entity_type, normalized)].append(dict(mention))
        return buckets

    # ------------------------------------------------------------------
    # Phase 2: 称谓链消解
    # ------------------------------------------------------------------

    def _phase2_appellation_linking(
        self,
        buckets: dict[tuple[str, str], list[dict[str, Any]]],
        mentions: list[dict[str, Any]],
    ) -> None:
        """将称谓型 mention（如"师父"、"他"）关联到最近的同名实体候选。

        策略：对每个称谓 mention，在同一章节内查找最近的、类型匹配的实体候选，
        将该 mention 合并到对应 bucket 中。
        """
        appellation_mentions = self._collect_appellation_mentions(mentions)
        if not appellation_mentions:
            return

        # 构建 chapter → 按位置排序的 mention 列表
        chapter_mentions: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for mention in mentions:
            chapter_id = _int_or_none(mention.get("chapter_id"))
            if chapter_id is not None:
                chapter_mentions[chapter_id].append(dict(mention))

        # 为每个 bucket 记录出现位置，方便查找最近实体
        bucket_positions: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
        for key, bucket in buckets.items():
            for item in bucket:
                chapter_id = _int_or_none(item.get("chapter_id"))
                char_start = int(item.get("char_start") or 0)
                if chapter_id is not None:
                    bucket_positions[key].append((chapter_id, char_start))

        for appellation in appellation_mentions:
            chapter_id = _int_or_none(appellation.get("chapter_id"))
            if chapter_id is None:
                continue
            char_start = int(appellation.get("char_start") or 0)
            appellation_type = str(appellation.get("entity_type") or "character")
            best_key: tuple[str, str] | None = None
            best_distance = float("inf")

            for key, positions in bucket_positions.items():
                key_type = key[0]
                if key_type != appellation_type:
                    continue
                for pos_chapter, pos_char in positions:
                    if pos_chapter != chapter_id:
                        continue
                    distance = abs(pos_char - char_start)
                    if distance < best_distance:
                        best_distance = distance
                        best_key = key

            if best_key is not None and best_distance < 500:
                buckets[best_key].append(appellation)

    def _collect_appellation_mentions(self, mentions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """收集称谓型 mention（quote_text 匹配称谓模式的）。"""
        result: list[dict[str, Any]] = []
        for mention in mentions:
            quote = str(mention.get("quote_text") or "").strip()
            if not quote:
                continue
            for pattern_text, _entity_type, _ in _APPELLATION_PATTERNS:
                if quote == pattern_text or quote.endswith(pattern_text):
                    result.append(dict(mention))
                    break
        return result

    # ------------------------------------------------------------------
    # Phase 3: 跨章合并
    # ------------------------------------------------------------------

    def _phase3_cross_chapter_merge(
        self,
        buckets: dict[tuple[str, str], list[dict[str, Any]]],
        book_id: int,
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        """合并跨章的同实体候选。

        合并条件（全部满足）：
        1. 同一 entity_type
        2. 名称相似度超过阈值（编辑距离），或一方是另一方的别名/子串
        3. 时间线不冲突（两个候选的 chapter_ids 不重叠，或重叠但 quote_text 不矛盾）
        """
        keys = list(buckets.keys())
        merged: set[tuple[str, str]] = set()
        merges: list[tuple[tuple[str, str], tuple[str, str]]] = []
        allow_vector = self._vector_store is not None and len(keys) <= _VECTOR_BUCKET_LIMIT
        pair_checks = 0
        started_at = time.monotonic()
        timed_out = False
        if self._vector_store is not None and not allow_vector:
            logger.info(
                "Skip vector-assisted coreference merge: bucket_count=%s limit=%s book_id=%s",
                len(keys),
                _VECTOR_BUCKET_LIMIT,
                book_id,
            )

        for i, key_a in enumerate(keys):
            if key_a in merged:
                continue
            for j in range(i + 1, len(keys)):
                pair_checks += 1
                if pair_checks > _PAIR_CHECK_LIMIT:
                    logger.warning(
                        "Stop coreference cross-chapter merge after %s pair checks: bucket_count=%s book_id=%s",
                        pair_checks,
                        len(keys),
                        book_id,
                    )
                    break
                if _TIME_LIMIT_SECONDS > 0 and pair_checks % 1000 == 0 and time.monotonic() - started_at > _TIME_LIMIT_SECONDS:
                    timed_out = True
                    logger.warning(
                        "Stop coreference cross-chapter merge after %.1fs: bucket_count=%s book_id=%s pair_checks=%s",
                        time.monotonic() - started_at,
                        len(keys),
                        book_id,
                        pair_checks,
                    )
                    break
                key_b = keys[j]
                if key_b in merged:
                    continue
                if key_a[0] != key_b[0]:
                    continue
                if self._should_merge_buckets(buckets[key_a], buckets[key_b], allow_vector=allow_vector):
                    merges.append((key_a, key_b))
                    merged.add(key_b)
            if timed_out or pair_checks > _PAIR_CHECK_LIMIT:
                break

        # 执行合并
        for key_a, key_b in merges:
            buckets[key_a].extend(buckets.pop(key_b, []))

        return buckets

    def _should_merge_buckets(
        self,
        bucket_a: list[dict[str, Any]],
        bucket_b: list[dict[str, Any]],
        *,
        allow_vector: bool = True,
    ) -> bool:
        """判断两个 bucket 是否应该合并。"""
        names_a = {str(item.get("quote_text") or "").strip() for item in bucket_a}
        names_b = {str(item.get("quote_text") or "").strip() for item in bucket_b}

        # 条件 1: 别名显式 — 一方的 quote 是另一方的子串或别名
        for name_a in names_a:
            for name_b in names_b:
                if not name_a or not name_b:
                    continue
                if name_a == name_b:
                    return True
                short, long = (name_a, name_b) if len(name_a) < len(name_b) else (name_b, name_a)
                if len(short) >= 2 and (long.startswith(short) or long.endswith(short) or short in long):
                    return True

        # 条件 2: 名称相似度
        for name_a in names_a:
            for name_b in names_b:
                if not name_a or not name_b:
                    continue
                if _name_similarity(name_a, name_b) >= (1.0 - _NAME_SIMILARITY_THRESHOLD):
                    return True

        # 条件 3: 向量相似度辅助 — 如果两个 bucket 的上下文向量高度相似，也合并
        if allow_vector and self._vector_store is not None:
            try:
                vector_score = self._vector_similarity_score(bucket_a, bucket_b)
                if vector_score >= 0.75:
                    return True
            except Exception:
                pass

        return False

    def _vector_similarity_score(
        self,
        bucket_a: list[dict[str, Any]],
        bucket_b: list[dict[str, Any]],
    ) -> float:
        """利用向量存储计算两个 bucket 的上下文相似度。"""
        if not self._vector_store:
            return 0.0
        # 取每个 bucket 的第一个 mention 的 quote_text 作为查询
        quote_a = str(bucket_a[0].get("quote_text") or "").strip() if bucket_a else ""
        quote_b = str(bucket_b[0].get("quote_text") or "").strip() if bucket_b else ""
        if not quote_a or not quote_b:
            return 0.0
        book_id = int(bucket_a[0].get("book_id") or 0)
        if not book_id:
            return 0.0
        # 用 quote_a 搜索 entity_summaries，看是否命中 bucket_b 的实体
        results_a = self._vector_store.search_similar_entities(book_id, quote_a, top_k=3, score_threshold=0.5)
        results_b = self._vector_store.search_similar_entities(book_id, quote_b, top_k=3, score_threshold=0.5)
        # 如果两者的搜索结果有重叠（命中同一实体），说明上下文相似
        uids_a = {r.get("payload", {}).get("entity_uid") for r in results_a}
        uids_b = {r.get("payload", {}).get("entity_uid") for r in results_b}
        overlap = uids_a & uids_b
        if overlap:
            # 取重叠实体的最高分数
            max_score = 0.0
            for r in results_a + results_b:
                if r.get("payload", {}).get("entity_uid") in overlap:
                    max_score = max(max_score, r.get("score", 0.0))
            return min(1.0, max_score)
        return 0.0

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _canonical_name(quotes: list[str]) -> str:
        counts: dict[str, int] = defaultdict(int)
        for quote in quotes:
            counts[quote] += 1
        return sorted(counts, key=lambda item: (-counts[item], -len(item), item))[0]

    @staticmethod
    def _source_rule(mentions: list[dict[str, Any]]) -> str:
        counts: dict[str, int] = defaultdict(int)
        for mention in mentions:
            source_rule = str(mention.get("source_rule") or "auto_coreference")
            counts[source_rule] += 1
        return sorted(counts, key=lambda item: (-counts[item], item))[0] if counts else "auto_coreference"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _name_similarity(a: str, b: str) -> float:
    """计算两个名称的相似度（0~1），基于编辑距离。"""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    dist = _edit_distance(a, b)
    max_len = max(len(a), len(b))
    return 1.0 - (dist / max_len)


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein 编辑距离。"""
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    prev = list(range(m + 1))
    curr = [0] * (m + 1)
    for i in range(1, n + 1):
        curr[0] = i
        for j in range(1, m + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev, curr = curr, prev
    return prev[m]


def _int_or_none(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None
