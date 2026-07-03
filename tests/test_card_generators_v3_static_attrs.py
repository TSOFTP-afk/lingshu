"""build_v3_entity_card 静态属性提取回归测试（Task 7.3）。

覆盖 card_generators_v3.build_v3_entity_card 在不同 facts 输入下的行为：
- facts 含静态属性关键词 → writeback_fields 包含对应静态属性字段
- facts 不含静态属性 → 保持原有 name/role/profile_text 三字段行为
"""
from __future__ import annotations

from novel_app.analysis.card_generators_v3 import build_v3_entity_card


def _make_character_entity(
    *,
    entity_uid: str = "CHAR-1",
    canonical_name: str = "白月",
    role: str = "主角",
) -> dict:
    """构造一个 character 类型的 entity 输入。"""
    return {
        "entity_uid": entity_uid,
        "entity_type": "character",
        "canonical_name": canonical_name,
        "metadata": {"role": role},
    }


def _make_fact(
    fact_type: str,
    summary: str,
    *,
    fact_uid: str = "FACT-1",
    quote_text: str = "",
    confidence: float = 0.8,
) -> dict:
    """构造一个 fact 输入。"""
    return {
        "fact_uid": fact_uid,
        "fact_type": fact_type,
        "quote_text": quote_text or summary,
        "value": {"summary": summary, "subject_name": "白月"},
        "confidence": confidence,
    }


def test_build_v3_entity_card_includes_static_attrs_when_facts_present():
    """facts 含静态属性关键词时 build_v3_entity_card 的 writeback_fields 包含对应字段。"""
    entity = _make_character_entity()
    facts = [
        _make_fact("alias", "白月", fact_uid="FACT-alias"),
        _make_fact("age", "27", fact_uid="FACT-age"),
        _make_fact("gender", "女", fact_uid="FACT-gender"),
        _make_fact("appearance", "银发红瞳", fact_uid="FACT-appearance"),
        _make_fact("signature_feature", "左颊泪痣", fact_uid="FACT-feature"),
        _make_fact("identity_occupation", "皇家骑士", fact_uid="FACT-identity"),
    ]
    draft = build_v3_entity_card(
        book_id=1,
        run_id=1,
        entity=entity,
        facts=facts,
        card_type="v3_character",
        dependency_hash="dep-hash-static",
    )
    writeback_fields = draft.payload["writeback_fields"]
    # 基础三字段始终存在
    assert writeback_fields["name"] == "白月"
    assert writeback_fields["role"] == "主角"
    assert "profile_text" in writeback_fields
    # 6 个静态属性字段应被填充
    assert writeback_fields["alias"] == "白月"
    assert writeback_fields["age"] == "27"
    assert writeback_fields["gender"] == "女"
    assert writeback_fields["appearance_keywords"] == "银发红瞳"
    assert writeback_fields["signature_feature"] == "左颊泪痣"
    assert writeback_fields["identity_occupation"] == "皇家骑士"


def test_build_v3_entity_card_keeps_only_basic_fields_when_no_static_attrs():
    """facts 不含静态属性时保持原有 name/role/profile_text 三字段行为。"""
    entity = _make_character_entity()
    facts = [
        _make_fact("motivation", "复活挚爱", fact_uid="FACT-motiv"),
        _make_fact("strategy", "以智取胜", fact_uid="FACT-strat"),
    ]
    draft = build_v3_entity_card(
        book_id=1,
        run_id=1,
        entity=entity,
        facts=facts,
        card_type="v3_character",
        dependency_hash="dep-hash-basic",
    )
    writeback_fields = draft.payload["writeback_fields"]
    # 仅含基础三字段
    assert set(writeback_fields.keys()) == {"name", "role", "profile_text"}
    assert writeback_fields["name"] == "白月"
    assert writeback_fields["role"] == "主角"
    assert "profile_text" in writeback_fields
    # 静态属性字段不应出现
    for static_field in (
        "alias",
        "age",
        "gender",
        "appearance_keywords",
        "signature_feature",
        "identity_occupation",
    ):
        assert static_field not in writeback_fields, (
            f"无静态属性 facts 时不应出现字段 {static_field}"
        )
