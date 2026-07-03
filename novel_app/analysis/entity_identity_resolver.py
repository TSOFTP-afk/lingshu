"""全局实体身份消解 — 跨章节识别同一角色的不同称号/身份。

在共指消解 (M3) 之后运行。共指消解只能合并文本相似的 mention（如"张三"+"青云剑尊张三"），
但无法将完全不同的称呼（如"张三"和"青云剑尊"）关联为同一人。

本模块将已消解的角色实体及其事实发送给 LLM，识别跨身份的同一角色。
LLM 利用跨章节的叙事一致性（相同事件、相同关系、继承性角色弧线）来判断。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_IDENTITY = """你是一名专业的小说角色关系分析助手。你的任务是识别小说中哪些不同的名字/称号实际上指向同一个角色。

## 背景
在长篇小说中，同一个角色可能在不同阶段以不同身份出现：
- 角色可能从凡名成长为称号角色（如"张三"→"青云剑尊"）
- 角色可能被不同人以不同称呼提及（本名、称号、职位、尊称）
- 前期出现的"神秘老者"可能是后期揭示身份的"XX尊者"

## 任务
审查以下角色实体列表。每个实体包含：
- 名称、别名
- 出现的章节范围
- 相关的关键事实摘要

找出哪些实体实际上是同一个人，给出合并建议。

## 判断标准
1. **叙事连续性**：实体A的事实 → 实体B的事实有因果关系或时间承接
2. **身份继承**：A获得的身份/称号与B的身份/称号一致
3. **关系网络重叠**：A和B与相同的第三方角色互动
4. **事实中的指代线索**：A的fact中提到了B的名字，或反之

## 输出格式
只返回纯 JSON：
{
  "merges": [
    {
      "keep_entity_uid": "BOOK-1::ENT-P-xxx",
      "keep_name": "张三",
      "merge_entity_uids": ["BOOK-1::ENT-P-yyy"],
      "merge_names": ["青云剑尊"],
      "confidence": 0.9,
      "reason": "张三后来成为青云剑尊，叙事连续"
    }
  ]
}

## 规则
- 只返回纯 JSON，禁止 Markdown 代码块
- 不确定时不要强行合并
- 保留最完整/最常用的实体作为 keep_entity_uid
- 实体数量多时请逐一审查"""


@dataclass
class IdentityResolveResult:
    merge_count: int
    merges: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "merge_count": self.merge_count,
            "merges": self.merges,
        }


class EntityIdentityResolver:
    """全局实体身份消解器。"""

    PROMPT_VERSION = "identity_resolve_v1"
    BATCH_SIZE = 80  # 一批最多处理 80 个角色实体

    def __init__(self, ai_provider: Any, entity_store: Any, fact_store: Any) -> None:
        self.ai_provider = ai_provider
        self.entity_store = entity_store
        self.fact_store = fact_store

    def resolve(
        self,
        *,
        book_id: int,
        run_id: int,
    ) -> IdentityResolveResult:
        """执行全局身份消解，返回合并方案。"""
        entities = self.entity_store.list_entities(int(book_id), run_id=int(run_id), limit=None)
        character_entities = [
            e for e in entities
            if str(e.get("entity_type") or "") == "character"
        ]
        if len(character_entities) < 2:
            return IdentityResolveResult(0)

        # 获取每个角色的关键事实
        all_facts = self.fact_store.list_facts(int(book_id), run_id=int(run_id), limit=None)
        facts_by_entity: dict[str, list[dict[str, Any]]] = {}
        for fact in all_facts:
            uid = str(fact.get("subject_entity_uid") or "")
            if uid:
                facts_by_entity.setdefault(uid, []).append(dict(fact))

        # 构建实体摘要
        entity_summaries = []
        for entity in character_entities:
            entity_uid = str(entity.get("entity_uid") or "")
            entity_facts = facts_by_entity.get(entity_uid, [])
            # 取代表性事实
            top_facts = sorted(
                entity_facts,
                key=lambda f: float(f.get("importance_score") or 0),
                reverse=True,
            )[:8]

            chapters = sorted({
                int(f.get("chapter_id") or 0)
                for f in entity_facts
                if f.get("chapter_id")
            })

            aliases = entity.get("aliases") or []
            if isinstance(aliases, str):
                try:
                    aliases = json.loads(aliases)
                except Exception:
                    aliases = []

            entity_summaries.append({
                "entity_uid": entity_uid,
                "canonical_name": str(entity.get("canonical_name") or ""),
                "aliases": list(aliases) if isinstance(aliases, (list, tuple)) else [],
                "fact_count": len(entity_facts),
                "chapter_range": [min(chapters), max(chapters)] if chapters else [],
                "top_facts": [
                    {
                        "fact_type": str(f.get("fact_type") or ""),
                        "chapter_id": f.get("chapter_id"),
                        "summary": str((f.get("value") or {}).get("summary") or f.get("quote_text") or "")[:150],
                    }
                    for f in top_facts
                ],
            })

        # 分批处理
        all_merges: list[dict[str, Any]] = []
        for batch_start in range(0, len(entity_summaries), self.BATCH_SIZE):
            batch = entity_summaries[batch_start : batch_start + self.BATCH_SIZE]

            input_payload = {
                "book_id": book_id,
                "entity_count": len(batch),
            }
            user_prompt = (
                f"book_id: {book_id}\n"
                f"角色实体数：{len(batch)}\n"
                f"实体摘要（JSON）：\n{json.dumps(batch, ensure_ascii=False)}\n\n"
                f"请识别哪些实体实际上是同一个人。"
            )

            try:
                output = self.ai_provider._call_llm(
                    stage="identity_resolve",
                    input_payload=input_payload,
                    system_prompt=SYSTEM_PROMPT_IDENTITY,
                    user_prompt=user_prompt,
                    temperature=0.15,
                )
            except Exception as exc:
                logger.warning("Identity resolution LLM call failed: %s", exc)
                continue

            merges = output.get("merges") or []
            if isinstance(merges, list):
                all_merges.extend(merges)

        return IdentityResolveResult(
            merge_count=len(all_merges),
            merges=all_merges,
        )

    def apply_merges(
        self,
        book_id: int,
        run_id: int,
        merges: list[dict[str, Any]],
    ) -> int:
        """将 LLM 返回的合并方案写入数据库。返回实际合并的实体数。"""
        applied = 0
        for merge in merges:
            keep_uid = str(merge.get("keep_entity_uid") or "")
            merge_uids = merge.get("merge_entity_uids") or []
            if not keep_uid or not merge_uids:
                continue
            if not isinstance(merge_uids, list):
                continue

            for uid in merge_uids:
                uid_str = str(uid)
                if uid_str == keep_uid:
                    continue
                try:
                    # 合并实体：将 merge_uid 合并到 keep_uid
                    self.entity_store.merge_entities(
                        int(book_id), int(run_id),
                        target_entity_uid=keep_uid,
                        source_entity_uids=[uid_str],
                        actor="identity_resolver",
                    )
                    applied += 1
                    logger.info(
                        "Identity resolved: merged %s (%s) → %s (%s)",
                        uid_str, merge.get("keep_name", "?"),
                        keep_uid, merge.get("merge_names", []),
                    )
                except Exception as exc:
                    logger.warning("Failed to merge entity %s → %s: %s", uid_str, keep_uid, exc)

        return applied
