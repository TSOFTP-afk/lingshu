"""人物状态机字段 Schema，供前端动态渲染三轴+价值观+运行态快照表单。

依据《人物状态机·设计规范 v2》。
"""

STATE_MACHINE_SCHEMA = {
    "static_attrs": {
        "title": "静态属性",
        "fields": [
            {"id": "alias", "label": "别名/称号", "type": "text"},
            {"id": "age", "label": "年龄", "type": "text"},
            {"id": "gender", "label": "性别", "type": "text"},
            {"id": "appearance_keywords", "label": "外貌关键词", "type": "text"},
            {"id": "signature_feature", "label": "标志性特征", "type": "text"},
            {"id": "identity_occupation", "label": "身份/职业", "type": "text"},
        ],
    },
    "desire": {
        "title": "轴1：星座——欲望层",
        "fields": [
            {"id": "desire_text", "label": "终极欲望", "type": "multiline"},
            {"id": "desire_origin", "label": "情感引力源", "type": "multiline"},
            {"id": "desire_anchor", "label": "关系锚点", "type": "text"},
            {"id": "desire_extreme", "label": "欲望极端形态", "type": "multiline"},
            {"id": "desire_fear_mirror", "label": "恐惧镜像", "type": "multiline"},
        ],
    },
    "mbti": {
        "title": "轴2：MBTI——认知层",
        "fields": [
            {"id": "mbti_type", "label": "MBTI类型", "type": "text"},
            {"id": "mbti_i_e", "label": "I/E", "type": "select", "options": ["", "I", "E"]},
            {"id": "mbti_n_s", "label": "N/S", "type": "select", "options": ["", "N", "S"]},
            {"id": "mbti_t_f", "label": "T/F", "type": "select", "options": ["", "T", "F"]},
            {"id": "mbti_j_p", "label": "J/P", "type": "select", "options": ["", "J", "P"]},
            {"id": "mbti_strategy", "label": "策略原型", "type": "text"},
            {"id": "mbti_advantage", "label": "认知优势", "type": "multiline"},
            {"id": "mbti_blindspot", "label": "认知盲点", "type": "multiline"},
        ],
    },
    "fate": {
        "title": "轴3：命理——边界层",
        "fields": [
            {"id": "fate_type", "label": "命理类型", "type": "select",
             "options": ["", "paradox", "inertial", "decay"]},
            {"id": "fate_content", "label": "命理内容", "type": "multiline"},
            {"id": "fate_trigger", "label": "触发条件", "type": "multiline"},
            {"id": "fate_target", "label": "反噬方向", "type": "text"},
            {"id": "fate_limit", "label": "反噬极限", "type": "multiline"},
        ],
    },
    "belief": {
        "title": "价值观筛选器",
        "fields": [
            {"id": "belief_core", "label": "根本信条", "type": "multiline"},
            {"id": "belief_origin", "label": "信条来源", "type": "multiline"},
            {"id": "belief_alignment", "label": "一致性", "type": "select",
             "options": ["", "aligned", "partial", "conflict"]},
            {"id": "belief_sacrifice", "label": "可牺牲项", "type": "multiline"},
            {"id": "belief_taboo", "label": "不可触碰项", "type": "multiline"},
        ],
    },
    "snapshot": {
        "title": "运行态快照",
        "fields": [
            {"id": "current_desire_state", "label": "星座现状", "type": "select",
             "options": ["original", "shifted", "reshaped"]},
            {"id": "current_mbti_state", "label": "MBTI现状", "type": "text"},
            {"id": "current_fate_state", "label": "命理状态", "type": "select",
             "options": ["dormant", "active", "fulfilled"]},
            {"id": "current_belief_state", "label": "核心信条状态", "type": "select",
             "options": ["stable", "loosening", "rebuilt"]},
            {"id": "current_friction", "label": "内耗水平", "type": "select",
             "options": ["none", "low", "medium", "high", "resolved"]},
            {"id": "current_dilemma", "label": "当前困境", "type": "multiline"},
        ],
    },
}

# 所有状态机可编辑字段 id 的扁平列表（供 API 校验白名单用）
STATE_MACHINE_FIELD_IDS = [
    f["id"] for section in STATE_MACHINE_SCHEMA.values() for f in section["fields"]
]
