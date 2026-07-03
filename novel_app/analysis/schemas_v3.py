from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

ANALYSIS_V3_SCHEMA_VERSION = "analysis_v3_m4"


def stable_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SemanticBlock:
    book_id: int
    block_uid: str
    chunk_id: str
    chunk_index: int
    chapter_id: int | None
    chapter_title: str
    char_start: int
    char_end: int
    text: str
    content_hash: str
    structure_hash: str
    pipeline_version: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_text_span(
        cls,
        *,
        book_id: int,
        chapter_id: int | None,
        chapter_title: str,
        local_index: int,
        chunk_index: int,
        char_start: int,
        char_end: int,
        text: str,
        pipeline_version: str,
        split_reason: str,
        chapter_content_hash: str = "",
    ) -> SemanticBlock:
        clean_text = str(text or "")
        content_hash = stable_hash(clean_text)
        chapter_label = str(chapter_id) if chapter_id is not None else "orphan"
        block_uid = f"analysis-v3-chapter-{chapter_label}-part-{local_index:04d}"
        chunk_id = f"semantic-{chapter_label}-part-{local_index:04d}"
        structure_hash = stable_hash(
            "|".join(
                [
                    ANALYSIS_V3_SCHEMA_VERSION,
                    str(book_id),
                    chapter_label,
                    str(char_start),
                    str(char_end),
                    str(len(clean_text)),
                    content_hash,
                ]
            )
        )
        return cls(
            book_id=int(book_id),
            block_uid=block_uid,
            chunk_id=chunk_id,
            chunk_index=int(chunk_index),
            chapter_id=chapter_id,
            chapter_title=str(chapter_title or ""),
            char_start=max(0, int(char_start)),
            char_end=max(0, int(char_end)),
            text=clean_text,
            content_hash=content_hash,
            structure_hash=structure_hash,
            pipeline_version=pipeline_version,
            metadata={
                "schema_version": ANALYSIS_V3_SCHEMA_VERSION,
                "split_reason": split_reason,
                "chapter_title": str(chapter_title or ""),
                "text_length": len(clean_text),
                "chapter_content_hash": str(chapter_content_hash or ""),
            },
        )

    def as_analysis_block(self) -> dict[str, Any]:
        chapter_ids = [self.chapter_id] if self.chapter_id is not None else []
        chapter_refs = [
            {"id": self.chapter_id, "title": self.chapter_title}
        ] if self.chapter_id is not None else []
        return {
            "block_uid": self.block_uid,
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "chapter_id": self.chapter_id,
            "chapter_ids": chapter_ids,
            "chapter_refs": chapter_refs,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "text": self.text,
            "summary": self.text[:500],
            "content_hash": self.content_hash,
            "structure_hash": self.structure_hash,
            "pipeline_version": self.pipeline_version,
            "metadata": self.metadata,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "book_id": self.book_id,
            "block_uid": self.block_uid,
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "chapter_id": self.chapter_id,
            "chapter_title": self.chapter_title,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "text": self.text,
            "content_hash": self.content_hash,
            "structure_hash": self.structure_hash,
            "pipeline_version": self.pipeline_version,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EntityMentionCandidate:
    mention_uid: str
    entity_type: str
    normalized_text: str
    quote_text: str
    chapter_id: int | None
    block_uid: str
    char_start: int
    char_end: int
    confidence: float
    status: str = "candidate"
    source_rule: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        book_id: int,
        run_id: int,
        entity_type: str,
        normalized_text: str,
        quote_text: str,
        chapter_id: int | None,
        block_uid: str,
        char_start: int,
        char_end: int,
        confidence: float,
        source_rule: str,
        metadata: dict[str, Any] | None = None,
    ) -> EntityMentionCandidate:
        uid_seed = "|".join(
            [
                str(book_id),
                str(run_id),
                str(block_uid),
                str(chapter_id or ""),
                str(char_start),
                str(char_end),
                str(entity_type or ""),
                str(normalized_text or ""),
                str(source_rule or ""),
            ]
        )
        return cls(
            mention_uid=f"MEN-{stable_hash(uid_seed)[:16]}",
            entity_type=str(entity_type or "unknown"),
            normalized_text=str(normalized_text or ""),
            quote_text=str(quote_text or ""),
            chapter_id=chapter_id,
            block_uid=str(block_uid or ""),
            char_start=max(0, int(char_start)),
            char_end=max(0, int(char_end)),
            confidence=max(0.0, min(1.0, float(confidence or 0.0))),
            status="candidate",
            source_rule=str(source_rule or ""),
            metadata={
                "schema_version": ANALYSIS_V3_SCHEMA_VERSION,
                **(metadata or {}),
            },
        )

    def as_analysis_mention(self) -> dict[str, Any]:
        return {
            "mention_uid": self.mention_uid,
            "entity_type": self.entity_type,
            "normalized_text": self.normalized_text,
            "quote_text": self.quote_text,
            "chapter_id": self.chapter_id,
            "block_uid": self.block_uid,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "confidence": self.confidence,
            "status": self.status,
            "source_rule": self.source_rule,
            "metadata": dict(self.metadata),
        }

    def as_dict(self) -> dict[str, Any]:
        return self.as_analysis_mention()


@dataclass(frozen=True)
class ResolvedEntityCandidate:
    entity_uid: str
    entity_type: str
    canonical_name: str
    aliases: tuple[str, ...]
    mention_uids: tuple[str, ...]
    confidence: float
    status: str = "candidate"
    source_rule: str = "auto_coreference"
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_analysis_entity(self) -> dict[str, Any]:
        return {
            "entity_uid": self.entity_uid,
            "entity_type": self.entity_type,
            "canonical_name": self.canonical_name,
            "aliases": list(self.aliases),
            "mention_uids": list(self.mention_uids),
            "confidence": self.confidence,
            "status": self.status,
            "source_rule": self.source_rule,
            "summary": self.summary,
            "metadata": dict(self.metadata),
        }

    def as_dict(self) -> dict[str, Any]:
        return self.as_analysis_entity()


@dataclass(frozen=True)
class AtomicFact:
    fact_uid: str
    subject_entity_uid: str
    fact_type: str
    value: dict[str, Any]
    quote_text: str
    chapter_id: int | None
    block_uid: str
    confidence: float
    memory_scope: str = "short_term"
    memory_importance: str = "normal"
    memory_type: str = "evidence"
    importance_score: float = 0.0
    status: str = "candidate"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        book_id: int,
        run_id: int,
        subject_entity_uid: str,
        fact_type: str,
        value: dict[str, Any],
        quote_text: str,
        chapter_id: int | None,
        block_uid: str,
        char_start: int,
        char_end: int,
        confidence: float,
        source_rule: str,
        metadata: dict[str, Any] | None = None,
    ) -> AtomicFact:
        uid_seed = "|".join(
            [
                str(book_id),
                str(run_id),
                str(subject_entity_uid or ""),
                str(fact_type or ""),
                str(block_uid or ""),
                str(chapter_id or ""),
                str(char_start),
                str(char_end),
                stable_hash(quote_text),
            ]
        )
        bounded_confidence = max(0.0, min(1.0, float(confidence or 0.0)))
        return cls(
            fact_uid=f"FACT-{stable_hash(uid_seed)[:16]}",
            subject_entity_uid=str(subject_entity_uid or ""),
            fact_type=str(fact_type or "event"),
            value=dict(value or {}),
            quote_text=str(quote_text or ""),
            chapter_id=chapter_id,
            block_uid=str(block_uid or ""),
            confidence=bounded_confidence,
            memory_scope="short_term",
            memory_importance="normal",
            memory_type="evidence",
            importance_score=bounded_confidence,
            status="candidate",
            metadata={
                "schema_version": ANALYSIS_V3_SCHEMA_VERSION,
                "source_rule": str(source_rule or ""),
                "char_start": max(0, int(char_start)),
                "char_end": max(0, int(char_end)),
                **(metadata or {}),
            },
        )

    def as_analysis_fact(self) -> dict[str, Any]:
        return {
            "fact_uid": self.fact_uid,
            "subject_entity_uid": self.subject_entity_uid,
            "fact_type": self.fact_type,
            "value": dict(self.value),
            "quote_text": self.quote_text,
            "chapter_id": self.chapter_id,
            "block_uid": self.block_uid,
            "confidence": self.confidence,
            "memory_scope": self.memory_scope,
            "memory_importance": self.memory_importance,
            "memory_type": self.memory_type,
            "importance_score": self.importance_score,
            "status": self.status,
            "metadata": dict(self.metadata),
        }

    def as_dict(self) -> dict[str, Any]:
        return self.as_analysis_fact()
