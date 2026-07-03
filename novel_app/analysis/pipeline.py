# DEPRECATED: 三层金字塔系统，已被 V3 替代
# 新代码应使用 novel_app.analysis.pipeline_v3.AnalysisPipelineV3
# 详见 .trae/specs/ai-v3-replace-three-layer/spec.md
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from typing import Any

from novel_app.analysis.card_builder import AnalysisCardBuilder, BuiltAnalysisCards
from novel_app.analysis.chunker import AnalysisChunker
from novel_app.analysis.entity_resolver import normalize_entity_alias
from novel_app.analysis.mention_extractor import MentionExtractor
from novel_app.analysis.store import AnalysisStore
from novel_app.analysis.utils import chapter_dict as _chapter_dict
from novel_app.analysis.utils import safe_int as _safe_int
from novel_app.database import Database

logger = logging.getLogger(__name__)
PIPELINE_VERSION = "p2_entity_cards_v1"

_DEPRECATED_WARNING_SHOWN = False


@dataclass(frozen=True)
class AnalysisPipelineResult:
    run_id: int
    status: str
    block_count: int
    indexed_block_count: int
    card_count: int
    entity_count: int
    summary: str
    meta: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "block_count": self.block_count,
            "indexed_block_count": self.indexed_block_count,
            "card_count": self.card_count,
            "entity_count": self.entity_count,
            "summary": self.summary,
            "meta": self.meta,
        }


class AnalysisPipeline:
    def __init__(
        self,
        database: Database,
        *,
        rag_retriever: Any | None = None,
        chunker: AnalysisChunker | None = None,
        store: AnalysisStore | None = None,
        card_builder_cls: type[AnalysisCardBuilder] = AnalysisCardBuilder,
    ) -> None:
        global _DEPRECATED_WARNING_SHOWN
        if not _DEPRECATED_WARNING_SHOWN:
            warnings.warn(
                "AnalysisPipeline (V1) is deprecated, use AnalysisPipelineV3 instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            _DEPRECATED_WARNING_SHOWN = True
        self.database = database
        self.rag_retriever = rag_retriever
        self.chunker = chunker or AnalysisChunker(max_chars=20000)
        self.store = store or AnalysisStore(database)
        self.card_builder_cls = card_builder_cls

    def prepare_source_blocks(self, chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.chunker.chunk_chapters([_chapter_dict(item) for item in chapters])

    def create_draft_run(
        self,
        book_id: int,
        payload: dict[str, Any],
        *,
        chapters: list[dict[str, Any]] | None = None,
        source_blocks: list[dict[str, Any]] | None = None,
        scope_type: str = "book",
        input_hash: str = "",
        meta: dict[str, Any] | None = None,
    ) -> AnalysisPipelineResult:
        base_meta = {"pipeline_version": PIPELINE_VERSION, **(meta or {})}
        run_id = self.store.create_run(
            int(book_id),
            scope_type=scope_type,
            status="running",
            pipeline_version=PIPELINE_VERSION,
            input_hash=input_hash,
            meta=base_meta,
        )
        try:
            blocks = list(source_blocks) if source_blocks is not None else self.prepare_source_blocks(chapters or self._load_book_chapters(book_id))
            block_ids = self.store.save_blocks(int(book_id), run_id, blocks) if blocks else []
            indexed_uids, index_errors = self._index_blocks_for_rag(int(book_id), run_id, blocks)
            if indexed_uids:
                self.store.mark_blocks_indexed(int(book_id), run_id, indexed_uids)

            # 规则兜底：用 MentionExtractor 从原文中补抽 AI 漏掉的人物（对话/动作模式）
            rule_added = self._augment_payload_with_rule_characters(int(book_id), run_id, payload, blocks)
            if rule_added > 0:
                self.store.create_audit_log(
                    int(book_id),
                    run_id=run_id,
                    action="rule_character_augmentation",
                    target_type="analysis_run",
                    target_uid=str(run_id),
                    new_value={"rule_added_character_count": rule_added},
                    reason="rule-based character candidates augmented to AI payload",
                )

            built = self.card_builder_cls(self.database, int(book_id), run_id=run_id).build_result(payload)
            card_ids = self.store.save_cards(int(book_id), run_id, built.drafts)
            summary = f"Generated {len(card_ids)} analysis draft cards from {len(block_ids)} source blocks."
            run_meta = self._run_meta(
                built,
                source_block_count=len(blocks),
                saved_block_count=len(block_ids),
                indexed_block_count=len(indexed_uids),
                index_errors=index_errors,
            )
            run_meta = {**base_meta, **run_meta}
            self.store.create_audit_log(
                int(book_id),
                run_id=run_id,
                action="draft_created",
                target_type="analysis_run",
                target_uid=str(run_id),
                new_value={
                    "card_count": len(card_ids),
                    "block_count": len(block_ids),
                    "entity_count": built.entity_resolution.entity_count,
                },
                reason="analysis pipeline draft created",
            )
            self.store.update_run_status(run_id, "awaiting_review", summary=summary, meta=run_meta)
            return AnalysisPipelineResult(
                run_id=run_id,
                status="awaiting_review",
                block_count=len(block_ids),
                indexed_block_count=len(indexed_uids),
                card_count=len(card_ids),
                entity_count=built.entity_resolution.entity_count,
                summary=summary,
                meta=run_meta,
            )
        except Exception as exc:
            logger.exception("Analysis pipeline failed for book_id=%s run_id=%s", book_id, run_id)
            self.store.update_run_status(
                run_id,
                "failed",
                error_text=str(exc),
                meta={**base_meta, "pipeline_failed": True},
            )
            raise

    def _index_blocks_for_rag(
        self,
        book_id: int,
        run_id: int,
        blocks: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        if self.rag_retriever is None:
            return [], []
        indexed: list[str] = []
        errors: list[str] = []
        for block in blocks:
            block_uid = str(block.get("block_uid") or "").strip()
            if not block_uid:
                continue
            chapter_ids = [_safe_int(item) for item in block.get("chapter_ids", [])]
            chapter_ids = [item for item in chapter_ids if item is not None]
            chapter_id = chapter_ids[0] if chapter_ids else 0
            text = str(block.get("text", "") or "")
            try:
                self.rag_retriever.index_analysis_block(
                    book_id=book_id,
                    block_uid=block_uid,
                    chapter_id=chapter_id,
                    summary=str(block.get("summary") or text[:500]),
                    content_snippet=text[:1200],
                    metadata={
                        "run_id": run_id,
                        "chunk_id": block.get("chunk_id", ""),
                        "chunk_index": block.get("chunk_index", 0),
                        "chapter_ids": chapter_ids,
                        "chapter_refs": block.get("chapter_refs", []),
                        "char_start": block.get("char_start", 0),
                        "char_end": block.get("char_end", 0),
                    },
                )
                indexed.append(block_uid)
            except Exception as exc:
                message = f"{block_uid}: {exc}"
                errors.append(message)
                logger.exception("Failed to index analysis block %s for book_id=%s run_id=%s", block_uid, book_id, run_id)
        return indexed, errors

    def _augment_payload_with_rule_characters(
        self,
        book_id: int,
        run_id: int,
        payload: dict[str, Any],
        source_blocks: list[dict[str, Any]],
    ) -> int:
        """规则兜底：用 MentionExtractor 从原文中补抽 AI 漏掉的人物。

        对话/动作模式识别的 character 不依赖种子，可发现 AI 全书分析遗漏的出场人物。
        为每个规则发现但 AI 未列出的人物，构造带证据的最小 character 条目，注入 payload，
        使其能通过证据门禁（filter_untrusted_book_analysis_payload）并最终写回 characters 表。
        """
        if not source_blocks:
            return 0
        try:
            extractor = MentionExtractor.from_database(self.database, book_id)
            mentions = extractor.extract_from_blocks(
                book_id=book_id, run_id=run_id, blocks=source_blocks,
            )
        except Exception:
            logger.exception("Rule mention extraction failed for book_id=%s run_id=%s", book_id, run_id)
            return 0

        # 只关注 character 类型，按 normalized_text 分组取最高 confidence 的 mention 作为证据
        character_mentions: dict[str, Any] = {}
        for mention in mentions:
            if str(getattr(mention, "entity_type", "") or "") != "character":
                continue
            name = str(getattr(mention, "normalized_text", "") or "").strip()
            if not name:
                continue
            existing = character_mentions.get(name)
            if existing is None or float(getattr(mention, "confidence", 0.0) or 0.0) > float(getattr(existing, "confidence", 0.0) or 0.0):
                character_mentions[name] = mention

        if not character_mentions:
            return 0

        # AI payload 中已有的人物名（normalized），以及 characters 表中已有的人物
        existing_names: set[str] = set()
        if not isinstance(payload.get("characters"), list):
            payload["characters"] = []
        for item in payload["characters"]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("character_name") or "").strip()
            if name:
                existing_names.add(normalize_entity_alias(name))
        try:
            for character in self.database.list_characters(int(book_id)):
                name = str(character["name"] or "").strip()
                if name:
                    existing_names.add(normalize_entity_alias(name))
        except Exception:
            pass

        # block_uid → block text 映射，用于提取证据原文窗口
        block_text_by_uid: dict[str, str] = {}
        for block in source_blocks:
            block_uid = str(block.get("block_uid") or "").strip()
            if block_uid:
                block_text_by_uid[block_uid] = str(block.get("text") or "")

        added = 0
        for name, mention in character_mentions.items():
            if name in existing_names:
                continue
            quote_text = str(getattr(mention, "quote_text", "") or name)
            block_uid = str(getattr(mention, "block_uid", "") or "")
            block_text = block_text_by_uid.get(block_uid, "")
            evidence_quote = self._build_evidence_quote(block_text, quote_text, window=40)
            payload["characters"].append({
                "name": quote_text,
                "role": "supporting",
                "source_block_uid": block_uid,
                "evidence_quote": evidence_quote,
                "profile_text": f"{quote_text}在原文中通过对话/动作模式被识别为出场人物。",
            })
            existing_names.add(name)
            added += 1

        if added > 0:
            logger.info("V1 rule-fallback augmented %d character(s) from dialogue/action patterns (book_id=%s run_id=%s)",
                        added, book_id, run_id)
        return added

    @staticmethod
    def _build_evidence_quote(block_text: str, name: str, *, window: int = 40) -> str:
        """从 block_text 中提取包含 name 的证据短引（±window 字符），确保原文逐字匹配。"""
        if not block_text or not name:
            return name
        idx = block_text.find(name)
        if idx < 0:
            return name
        start = max(0, idx - window)
        end = min(len(block_text), idx + len(name) + window)
        snippet = block_text[start:end]
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(block_text) else ""
        return f"{prefix}{snippet}{suffix}"

    def _run_meta(
        self,
        built: BuiltAnalysisCards,
        *,
        source_block_count: int,
        saved_block_count: int,
        indexed_block_count: int,
        index_errors: list[str],
    ) -> dict[str, Any]:
        entity_resolution = built.entity_resolution.as_dict()
        return {
            "pipeline_version": PIPELINE_VERSION,
            "source_block_count": source_block_count,
            "source_block_saved_count": saved_block_count,
            "source_block_indexed_count": indexed_block_count,
            "rag_index_error_count": len(index_errors),
            "rag_index_errors": index_errors[:5],
            "card_count": len(built.drafts),
            "card_types": [draft.card_type for draft in built.drafts],
            "entity_count": built.entity_resolution.entity_count,
            "entity_mention_count": built.entity_resolution.mention_count,
            "entity_resolution": {
                "entity_count": entity_resolution["entity_count"],
                "mention_count": entity_resolution["mention_count"],
                "entities": [
                    {
                        "entity_uid": item["entity_uid"],
                        "entity_type": item["entity_type"],
                        "canonical_name": item["canonical_name"],
                        "aliases": item["aliases"],
                    }
                    for item in entity_resolution["entities"]
                ],
            },
        }

    def _load_book_chapters(self, book_id: int) -> list[dict[str, Any]]:
        if hasattr(self.database, "get_book_export_data"):
            data = self.database.get_book_export_data(int(book_id))
            chapters = data.get("chapters", []) if isinstance(data, dict) else []
            if isinstance(chapters, list):
                return [_chapter_dict(item) for item in chapters]
        rows = self.database.list_chapters(int(book_id))
        chapters: list[dict[str, Any]] = []
        for row in rows:
            chapter = self.database.get_chapter(int(row["id"]))
            if chapter:
                chapters.append(_chapter_dict(chapter))
        return chapters


def extract_block_facts(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for index, block in enumerate(blocks, start=1):
        text = str(block.get("text", "") or "")
        if not text.strip():
            continue
        block_uid = str(block.get("block_uid") or block.get("chunk_id") or f"analysis-block-{index:04d}").strip()
        chapter_ids = [_safe_int(item) for item in block.get("chapter_ids", [])]
        chapter_ids = [item for item in chapter_ids if item is not None]
        facts.append(
            {
                "fact_uid": f"fact:{block_uid}",
                "block_uid": block_uid,
                "chunk_id": str(block.get("chunk_id") or ""),
                "chapter_ids": chapter_ids,
                "chapter_refs": block.get("chapter_refs", []) if isinstance(block.get("chapter_refs"), list) else [],
                "char_start": _safe_int(block.get("char_start")) or 0,
                "char_end": _safe_int(block.get("char_end")) or len(text),
                "char_count": len(text),
                "summary": str(block.get("summary") or text[:240]).strip(),
                "preview": text[:240],
            }
        )
    return facts
