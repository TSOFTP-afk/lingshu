"""卡片后处理层 — 使用 LLM 对生成的卡片进行去重、合并和质量审核。

在 V3 管道的 M5 (卡片生成) 之后运行。
将已生成的所有卡片摘要发送给 LLM，LLM 返回：
- 应合并的卡片对（含合并后的 canonical_name）
- 应删除的噪声卡片
- 可选：修正后的 summary
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_CARD_POST = """你是一名专业的小说设定审核助手。你的任务是审查一批自动生成的小说角色卡和世界观卡，识别问题并进行修正。

## 任务
审查以下卡片列表，找出以下问题并给出修正方案：

### 1. 重复/近似卡片合并
- 同一角色可能有多个卡片（如"方源"和"古月方源"、"赤城"和"古月赤城"）
- 判断标准：名称互为子串、事实高度重叠、属于同一实体类型
- 合并时：canonical_name 用最完整的名称，合并所有 facts

### 2. 称号/尊称/代称合并（重要！）
- 以下类型的卡片很可能指向某个具体人物，应尝试合并：
  * 尊称：仙尊、魔尊、尊者、大人、阁下
  * 职位：族长、家老、长老、掌门、首领
  * 关系称谓：舅父、舅母、师父、师叔
  * 代称：老者、中年人、少年、少女、黑袍人
- 判断方法：
  * 查看两张卡片的 facts 是否涉及相同的事件、相同的地点、相同的对话
  * 查看 summary 中的人名、动作、上下文是否有交集
  * 如果 fact 中反复出现某个具体人名（如"方源"），则该称号卡应合并到那个人名下
- 合并时：canonical_name 用该角色的真实姓名（如果有），否则保留最有辨识度的称呼

### 3. 噪声卡片删除
- 以下类型的卡片应删除：
  * 非命名实体的通用词汇（如"成功"、"远处"、"一阵"）
  * 句子片段被误识别为实体（如"早就被驱赶出"、"让你成为"）
  * 过于模糊的指代且无法确定指向（如"他"、"那个少年"等代词类）
  * entity_type 为 character 但事实全是 concept/event 相关的内容
  * 事实数 < 2 且 fact_count 远小于同类卡片平均值

### 4. 实体类型修正
- 部分卡片类型可能标注错误（如"酒虫"应该从 character 改为 item 或 concept）
- "魂兽"、"蛊虫"等非人类实体不应是 character
- 如果发现类型错误，给出修正后的 entity_type

## 输出格式
只返回纯 JSON 对象：
{
  "merges": [
    {
      "keep_card_uid": "CARD-V3-xxx",
      "merge_card_uids": ["CARD-V3-yyy"],
      "canonical_name": "古月方源",
      "reason": "简称与全名合并"
    }
  ],
  "deletes": [
    {
      "card_uid": "CARD-V3-zzz",
      "reason": "非命名实体的通用词汇"
    }
  ],
  "type_fixes": [
    {
      "card_uid": "CARD-V3-www",
      "new_entity_type": "item",
      "reason": "酒虫是物品而非人物"
    }
  ]
}

## 规则
- 只返回纯 JSON，禁止 Markdown 代码块
- 称号合并时，优先合并到 fact_count 最多且有真实姓名的角色
- 不太确定时宁可保留，不要误删
- 卡片数量多时请逐一审查，不要遗漏
- merge 时 keep_card_uid 必须是合并组中 fact_count 最多的那张卡"""


@dataclass
class CardPostResult:
    """卡片后处理结果。"""
    merge_count: int
    delete_count: int
    type_fix_count: int
    merges: list[dict[str, Any]] = field(default_factory=list)
    deletes: list[dict[str, Any]] = field(default_factory=list)
    type_fixes: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "merge_count": self.merge_count,
            "delete_count": self.delete_count,
            "type_fix_count": self.type_fix_count,
            "merges": self.merges,
            "deletes": self.deletes,
            "type_fixes": self.type_fixes,
        }


class CardPostProcessor:
    """使用 LLM 对卡片进行后处理去重合并。"""

    PROMPT_VERSION = "card_post_v1"

    def __init__(self, ai_provider: Any) -> None:
        self.ai_provider = ai_provider

    def process(
        self,
        *,
        book_id: int,
        run_id: int,
        cards: list[dict[str, Any]],
    ) -> CardPostResult:
        """对卡片列表进行 LLM 后处理，返回合并/删除/修正方案。"""
        if not cards:
            return CardPostResult(0, 0, 0)

        # 构建精简的卡片摘要供 LLM 审查
        compact_cards = self._build_compact_cards(cards)

        input_payload = {
            "book_id": book_id,
            "card_count": len(cards),
            "cards": compact_cards,
        }

        user_prompt = (
            f"book_id: {book_id}\n"
            f"卡片总数：{len(cards)}\n"
            f"卡片摘要（JSON）：\n{json.dumps(compact_cards, ensure_ascii=False)}\n\n"
            f"请审查这些卡片，找出需要合并、删除或修正类型的项。"
        )

        try:
            output = self.ai_provider._call_llm(
                stage="card_post_process",
                input_payload=input_payload,
                system_prompt=SYSTEM_PROMPT_CARD_POST,
                user_prompt=user_prompt,
                temperature=0.15,
            )
        except Exception as exc:
            logger.warning("Card post-processing LLM call failed: %s", exc)
            return CardPostResult(0, 0, 0)

        merges = output.get("merges") or []
        deletes = output.get("deletes") or []
        type_fixes = output.get("type_fixes") or []

        if not isinstance(merges, list):
            merges = []
        if not isinstance(deletes, list):
            deletes = []
        if not isinstance(type_fixes, list):
            type_fixes = []

        return CardPostResult(
            merge_count=len(merges),
            delete_count=len(deletes),
            type_fix_count=len(type_fixes),
            merges=merges,
            deletes=deletes,
            type_fixes=type_fixes,
        )

    @staticmethod
    def _build_compact_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """构建精简的卡片摘要列表供 LLM 审查。"""
        compact: list[dict[str, Any]] = []
        for card in cards:
            payload = card.get("payload") if isinstance(card.get("payload"), dict) else {}
            if not payload:
                # 尝试从 payload_json 解析
                raw = card.get("payload_json")
                if raw:
                    try:
                        payload = json.loads(str(raw)) if isinstance(raw, str) else dict(raw)
                    except Exception:
                        payload = {}

            compact.append({
                "card_uid": str(card.get("card_uid") or ""),
                "card_type": str(card.get("card_type") or ""),
                "entity_uid": str(card.get("entity_uid") or ""),
                "canonical_name": str(payload.get("name") or payload.get("title") or "?"),
                "entity_type": str(payload.get("entity_type") or card.get("entity_type") or "?"),
                "fact_count": int(payload.get("fact_count") or 0),
                "summary": str(payload.get("summary") or "")[:200],
                "writeback_target": str(payload.get("writeback_target") or ""),
            })
        return compact
