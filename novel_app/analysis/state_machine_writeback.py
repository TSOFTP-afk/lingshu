"""V3 分析卡片写回到人物状态机。

将分析 facts 映射到状态机三轴字段（星座/MBTI/命理）或循环日志，
替代直接写入旧表单 supplements。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# fact_type 关键词 → 状态机字段映射规则
# 高置信度映射：fact_type 含关键词 → 写入对应三轴字段
_FACT_TO_AXIS_MAP: list[dict[str, Any]] = [
    # 静态属性映射（优先匹配，避免落入 low_confidence_feedback）
    {
        "keywords": ["alias", "别名", "称号", "绰号"],
        "fields": ["alias"],
        "axis": "static_attrs",
    },
    {
        "keywords": ["age", "年龄", "岁数"],
        "fields": ["age"],
        "axis": "static_attrs",
    },
    {
        "keywords": ["gender", "性别", "男女"],
        "fields": ["gender"],
        "axis": "static_attrs",
    },
    {
        "keywords": ["appearance", "外貌", "形象", "外形", "容貌"],
        "fields": ["appearance_keywords"],
        "axis": "static_attrs",
    },
    {
        "keywords": ["signature_feature", "标志", "特征", "伤疤", "纹身", "饰品", "口癖"],
        "fields": ["signature_feature"],
        "axis": "static_attrs",
    },
    {
        "keywords": ["identity", "身份", "职业", "职务", "职位"],
        "fields": ["identity_occupation"],
        "axis": "static_attrs",
    },
    {
        "keywords": ["motivation", "desire", "欲望", "执念", "目标"],
        "fields": ["desire_text", "desire_origin"],
        "axis": "desire",
    },
    {
        "keywords": ["fear", "恐惧", "害怕"],
        "fields": ["desire_fear_mirror"],
        "axis": "desire",
    },
    {
        "keywords": ["cognition", "strategy", "认知", "策略", "行动模式"],
        "fields": ["mbti_strategy", "mbti_advantage"],
        "axis": "mbti",
    },
    {
        "keywords": ["blindspot", "盲点", "忽略"],
        "fields": ["mbti_blindspot"],
        "axis": "mbti",
    },
    {
        "keywords": ["limitation", "fate", "命理", "约束", "悖论", "代价"],
        "fields": ["fate_content", "fate_trigger"],
        "axis": "fate",
    },
    {
        "keywords": ["belief", "信条", "底线", "道德"],
        "fields": ["belief_core", "belief_taboo"],
        "axis": "belief",
    },
]


def writeback_to_state_machine(
    database, book_id: int, character_id: int, facts: list[dict]
) -> dict:
    """将分析 facts 映射到状态机字段并创建循环日志。

    映射规则：
    - 高置信度 fact（fact_type 含已知关键词）→ 写入对应三轴字段
    - 低置信度 fact → 进入循环日志的 world_feedback/action_taken，不改三轴
    - 保守策略：不覆盖用户已填的非空字段（仅填充空字段）

    返回 dict: {
        "axis_updates": {field: old_value},  # 实际更新的字段
        "cycle_id": int | None,
        "cumulative_score": int,
        "snapshot_created": bool,
    }
    """
    if not facts:
        return {"axis_updates": {}, "cycle_id": None, "cumulative_score": 0,
                "snapshot_created": False}

    # 1. 读取当前状态机
    sm = database.get_state_machine(character_id)
    if sm is None:
        logger.warning("状态机不存在 character_id=%s，跳过写回", character_id)
        return {"axis_updates": {}, "cycle_id": None, "cumulative_score": 0,
                "snapshot_created": False}

    sm_dict = dict(sm)
    axis_updates: dict[str, str] = {}
    low_confidence_feedback: list[str] = []

    # 2. 遍历 facts，分类映射
    for fact in facts:
        fact_type = str(fact.get("fact_type") or fact.get("type") or "").lower()
        # V3 facts 的 value 字段为 dict 结构（含 summary/quote_text 等），需提取 summary 纯文本
        raw_value = fact.get("content") or fact.get("text") or fact.get("value")
        if isinstance(raw_value, dict):
            raw_value = raw_value.get("summary") or raw_value.get("text") or ""
        fact_content = str(raw_value or "").strip()
        if not fact_content:
            continue

        matched = False
        for rule in _FACT_TO_AXIS_MAP:
            if any(kw in fact_type for kw in rule["keywords"]):
                # 高置信度：尝试写入对应字段（保守：仅填空字段）
                for field_id in rule["fields"]:
                    current_val = str(sm_dict.get(field_id, "") or "").strip()
                    if not current_val:
                        axis_updates[field_id] = fact_content
                        sm_dict[field_id] = fact_content  # 更新内存副本
                matched = True
                break

        if not matched:
            # 低置信度：进入循环日志 feedback
            low_confidence_feedback.append(fact_content)

    # 3. 更新状态机三轴字段（如果有）
    if axis_updates:
        database.update_state_machine(character_id, axis_updates)

    # 4. 创建主循环日志（+3, light）
    cycle_data = {
        "cycle_type": "main",
        "intensity": "light",
        "triggered_desire": sm_dict.get("desire_text", ""),
        "belief_filtered_strategy": sm_dict.get("mbti_strategy", ""),
        "action_taken": "V3 分析写回",
        "world_feedback": "；".join(low_confidence_feedback) if low_confidence_feedback else "V3 分析补充",
        "feedback_intensity": "light",
        "mbti_change": sm_dict.get("mbti_strategy", ""),
        "star_state": sm_dict.get("current_desire_state", "original"),
        "fate_state": sm_dict.get("current_fate_state", "dormant"),
        "internal_friction": sm_dict.get("current_friction", "none"),
    }

    cycle_result = database.create_cycle(character_id, cycle_data)

    return {
        "axis_updates": axis_updates,
        "cycle_id": cycle_result.get("cycle_id"),
        "cumulative_score": cycle_result.get("cumulative_score", 0),
        "snapshot_created": cycle_result.get("snapshot_created", False),
    }
