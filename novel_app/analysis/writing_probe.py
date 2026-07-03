"""写作探针伴随服务。

章节写作时后台静默扫描，将人物与概要以草稿形式保存到 analysis_cards 表。
- 草稿 card_type: writing_probe_character / writing_probe_summary
- 复用 MentionExtractor 规则引擎发现人物（含对话/动作模式，不依赖种子）
- 复用 book 维度伴随 run（每书一个长期 run，status='probe_companion'）
- 概要写回通过 update_chapter_summary（不走 V3 writeback）
- 人物写回通过 V3 writeback 机制（由 API 层调用）
"""
from __future__ import annotations

import json
import logging
from typing import Any

from novel_app.analysis.entity_resolver import normalize_entity_alias
from novel_app.analysis.mention_extractor import MentionExtractor
from novel_app.analysis.models import AnalysisCardDraft
from novel_app.analysis.store import AnalysisStore
from novel_app.database import Database

_logger = logging.getLogger(__name__)

PROBE_PIPELINE_VERSION = "writing_probe_v1"
PROBE_RUN_STATUS = "probe_companion"


class WritingProbeService:
    """写作探针服务：扫描章节生成草稿，管理伴随 run。"""

    def __init__(
        self,
        database: Database,
        *,
        probe_enabled: bool = True,
        ai_available: bool = False,
        interval_seconds: int = 8,
        auto_write_threshold: float = 0.55,
        user_id: int | None = None,
    ) -> None:
        self.database = database
        self.store = AnalysisStore(database)
        self.probe_enabled = probe_enabled
        self.ai_available = ai_available
        self.interval_seconds = interval_seconds
        self.auto_write_threshold = auto_write_threshold
        self.user_id = user_id

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def scan_chapter(self, book_id: int, chapter_id: int) -> dict[str, Any]:
        """扫描章节，生成草稿写入 analysis_cards，返回新增草稿列表。"""
        chapter = self.database.get_chapter(int(chapter_id))
        if not chapter:
            return {"character_drafts": [], "summary_draft": None, "error": "chapter not found"}

        text = str(chapter["content"] or "")
        if not text.strip():
            return {"character_drafts": [], "summary_draft": None}

        book_id_int = int(book_id)
        chapter_id_int = int(chapter_id)
        run_id = self._ensure_companion_run(book_id_int)

        # 用 MentionExtractor 扫描人物（复用规则引擎，含对话/动作模式）
        extractor = MentionExtractor.from_database(self.database, book_id_int)
        blocks = [{
            "block_uid": f"chapter-{chapter_id_int}",
            "text": text,
            "chapter_id": chapter_id_int,
            "char_start": 0,
            "char_end": len(text),
        }]
        mentions = extractor.extract_from_blocks(
            book_id=book_id_int, run_id=run_id, blocks=blocks
        )

        # 过滤已有 characters，只保留新人物草稿
        existing_names = {
            normalize_entity_alias(str(c["name"] or ""))
            for c in self.database.list_characters(book_id_int)
            if str(c["name"] or "").strip()
        }

        character_drafts: list[dict[str, Any]] = []
        seen_new: set[str] = set()
        for mention in mentions:
            if mention.entity_type != "character":
                continue
            # 跳过已有人物的种子命中（formal_character），只保留规则新发现的
            if mention.source_rule == "formal_character":
                continue
            normalized = normalize_entity_alias(mention.normalized_text)
            if not normalized or normalized in existing_names or normalized in seen_new:
                continue
            if mention.confidence < self.auto_write_threshold:
                continue
            draft = self._upsert_character_draft(
                book_id_int, run_id, chapter_id_int, chapter, mention
            )
            character_drafts.append(draft)
            seen_new.add(normalized)

        # AI 生成章节概要（AI 不可用时跳过）
        summary_draft = None
        if self.ai_available:
            summary_text = self._generate_summary(book_id_int, chapter_id_int, text)
            if summary_text:
                summary_draft = self._upsert_summary_draft(
                    book_id_int, run_id, chapter_id_int, chapter, summary_text, len(text)
                )

        # 审计日志
        self.store.create_audit_log(
            book_id_int,
            run_id=run_id,
            action="writing_probe_scan",
            target_type="chapter",
            target_uid=str(chapter_id_int),
            new_value={
                "character_draft_count": len(character_drafts),
                "summary_draft": bool(summary_draft),
                "word_count": len(text),
            },
            reason="writing probe companion scan",
        )

        return {"character_drafts": character_drafts, "summary_draft": summary_draft}

    def list_chapter_drafts(self, book_id: int, chapter_id: int) -> list[dict[str, Any]]:
        """列出指定章节的所有探针草稿。"""
        rows = self.store.list_cards_by_chapter(int(book_id), int(chapter_id))
        result: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(str(row["payload_json"] or "{}"))
            result.append({
                "id": int(row["id"]),
                "run_id": int(row["run_id"]),
                "card_uid": str(row["card_uid"] or ""),
                "card_type": str(row["card_type"] or ""),
                "status": str(row["status"] or ""),
                "payload": payload,
                "created_at": str(row["created_at"] or ""),
                "updated_at": str(row["updated_at"] or ""),
            })
        return result

    def apply_summary(
        self,
        book_id: int,
        chapter_id: int,
        summary_text: str,
        *,
        actor: str = "user",
    ) -> dict[str, Any]:
        """将概要草稿写回 chapters.summary_text。"""
        chapter = self.database.get_chapter(int(chapter_id))
        if not chapter:
            return {"ok": False, "error": "chapter not found"}
        old_summary = str(chapter["summary_text"] or "")
        self.database.update_chapter_summary(int(chapter_id), summary_text)
        # 标记概要草稿为 applied
        run_id = self._ensure_companion_run(int(book_id))
        card_uid = f"probe-summary-{chapter_id}"
        self.database.connection.execute(
            "UPDATE analysis_cards SET status = 'applied', applied_at = CURRENT_TIMESTAMP, "
            "applied_table = 'chapters', applied_id = ? WHERE run_id = ? AND card_uid = ?",
            (int(chapter_id), run_id, card_uid),
        )
        self.database.connection.commit()
        self.store.create_audit_log(
            int(book_id),
            run_id=run_id,
            action="writing_probe_summary_apply",
            target_type="chapter",
            target_uid=str(chapter_id),
            old_value={"summary_text": old_summary[:200]},
            new_value={"summary_text": summary_text[:200]},
            reason="writing probe summary applied by user",
            actor=actor,
        )
        return {"ok": True, "chapter_id": int(chapter_id)}

    def find_appearing_characters(self, book_id: int, chapter_id: int) -> list[dict[str, Any]]:
        """用现有人物作为种子，匹配当前章节出场人物（用于 CharactersTab 章节过滤）。"""
        chapter = self.database.get_chapter(int(chapter_id))
        if not chapter:
            return []
        text = str(chapter["content"] or "")
        if not text.strip():
            return []
        book_id_int = int(book_id)
        chapter_id_int = int(chapter_id)
        run_id = self._ensure_companion_run(book_id_int)
        extractor = MentionExtractor.from_database(self.database, book_id_int)
        blocks = [{
            "block_uid": f"chapter-{chapter_id_int}",
            "text": text,
            "chapter_id": chapter_id_int,
            "char_start": 0,
            "char_end": len(text),
        }]
        mentions = extractor.extract_from_blocks(
            book_id=book_id_int, run_id=run_id, blocks=blocks
        )
        # 只保留 formal_character 种子命中（即现有人物在章节出现）
        character_map: dict[str, dict[str, Any]] = {}
        for ch in self.database.list_characters(book_id_int):
            normalized = normalize_entity_alias(str(ch["name"] or ""))
            if not normalized:
                continue
            character_map[normalized] = {
                "character_id": int(ch["id"]),
                "name": str(ch["name"] or ""),
                "role": str(ch["role"] or ""),
                "profile_text": str(ch["profile_text"] or ""),
                "appear_count": 0,
                "max_confidence": 0.0,
            }
        for mention in mentions:
            if mention.entity_type != "character" or mention.source_rule != "formal_character":
                continue
            normalized = normalize_entity_alias(mention.normalized_text)
            if normalized not in character_map:
                continue
            character_map[normalized]["appear_count"] += 1
            character_map[normalized]["max_confidence"] = max(
                character_map[normalized]["max_confidence"], float(mention.confidence)
            )
        result = [v for v in character_map.values() if v["appear_count"] > 0]
        result.sort(key=lambda x: x["appear_count"], reverse=True)
        return result

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _ensure_companion_run(self, book_id: int) -> int:
        """获取或创建 book 维度的探针伴随 run。"""
        rows = self.database.connection.execute(
            "SELECT id FROM analysis_runs WHERE book_id = ? AND status = ? AND pipeline_version = ? "
            "ORDER BY id DESC LIMIT 1",
            (book_id, PROBE_RUN_STATUS, PROBE_PIPELINE_VERSION),
        ).fetchall()
        if rows:
            return int(rows[0]["id"])
        return self.store.create_run(
            book_id,
            scope_type="book",
            status=PROBE_RUN_STATUS,
            pipeline_version=PROBE_PIPELINE_VERSION,
            meta={"companion": True},
            summary="writing probe companion run",
        )

    def _upsert_character_draft(
        self,
        book_id: int,
        run_id: int,
        chapter_id: int,
        chapter: Any,
        mention: Any,
    ) -> dict[str, Any]:
        name = str(getattr(mention, "quote_text", "") or getattr(mention, "normalized_text", ""))
        normalized = normalize_entity_alias(name)
        card_uid = f"probe-char-{chapter_id}-{normalized}"
        source_rule = str(getattr(mention, "source_rule", "") or "")
        confidence = float(getattr(mention, "confidence", 0.0) or 0.0)
        evidence_quote = str(getattr(mention, "quote_text", "") or name)
        payload = {
            "card_type": "writing_probe_character",
            "writeback_target": "character",
            "writeback_fields": {
                "name": name,
                "role": "supporting",
                "profile_text": f"{name}在本章通过{source_rule}被识别为出场人物。",
            },
            "evidence_quote": evidence_quote,
            "source_rule": source_rule,
            "confidence": confidence,
            "chapter_id": chapter_id,
            "chapter_title": str(chapter["title"] or ""),
        }
        self.store.upsert_card_by_uid(
            book_id,
            run_id,
            AnalysisCardDraft(
                card_uid=card_uid,
                card_type="writing_probe_character",
                payload=payload,
                diff={},
                status="draft",
                entity_uid=f"character:{normalized}",
                ars_score=0.0,
            ),
        )
        return payload

    def _upsert_summary_draft(
        self,
        book_id: int,
        run_id: int,
        chapter_id: int,
        chapter: Any,
        summary_text: str,
        word_count: int,
    ) -> dict[str, Any]:
        card_uid = f"probe-summary-{chapter_id}"
        payload = {
            "card_type": "writing_probe_summary",
            "writeback_target": "chapter_summary",
            "writeback_fields": {"summary_text": summary_text},
            "chapter_id": chapter_id,
            "chapter_title": str(chapter["title"] or ""),
            "word_count": word_count,
        }
        self.store.upsert_card_by_uid(
            book_id,
            run_id,
            AnalysisCardDraft(
                card_uid=card_uid,
                card_type="writing_probe_summary",
                payload=payload,
                diff={},
                status="draft",
                entity_uid=f"chapter:{chapter_id}",
                ars_score=0.0,
            ),
        )
        return payload

    def _generate_summary(self, book_id: int, chapter_id: int, text: str) -> str:
        """调用 AI 生成章节概要。AI 不可用或失败时返回空字符串。"""
        if not self.ai_available:
            return ""
        try:
            from lingshu_api.services.ai_settings import resolve_ai_profile
            from novel_app.ai.book_analysis import _call_ai_summary
            data_dir = getattr(self.database, "data_dir", None)
            if not data_dir:
                return ""
            profile = resolve_ai_profile(data_dir, "writing_probe", user_id=self.user_id)
            return _call_ai_summary(profile, text)
        except Exception as e:
            _logger.warning("writing probe summary generation failed: %s", e)
            return ""
