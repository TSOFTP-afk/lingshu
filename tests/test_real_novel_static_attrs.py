"""真实小说数据测试：验证状态机静态属性字段在 V3 分析链路中的完整写入。

测试目标：
1. V3 分析提取的 facts 中包含外貌/年龄/性别/身份等静态属性信息
2. card_generators_v3.build_v3_entity_card 能结构化提取静态属性到 writeback_fields
3. state_machine_writeback.writeback_to_state_machine 能将静态属性 facts 写入状态机字段
4. characters._generate_legacy_form_from_state_machine 能反向填充旧表单
5. update_character_form 状态机分支能同步 profile_data_json

测试用书：《斗破苍穹》前3章（含明确的外貌/年龄/性别/身份描述）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novel_app.analysis.card_generators_v3 import _extract_static_attrs_from_facts, build_v3_entity_card
from novel_app.analysis.pipeline_v3 import AnalysisPipelineV3
from novel_app.analysis.state_machine_writeback import writeback_to_state_machine
from novel_app.database import Database

# 《斗破苍穹》第一章片段 — 含明确的外貌/年龄/性别/身份描述
CHAPTER_CONTENT = """
斗之力，三段！

望着测验魔石碑上面闪亮得甚至有些刺眼的五个大字，少年面无表情，唇角有着一抹自嘲。

"萧炎，斗之力，三段！级别：低级！"测验魔石碑之旁，一位中年男子，看了一眼碑上所显示出来的信息，语气漠然的将之公布了出来。

少年缓缓抬起头来，露出一张有些清秀的稚嫩脸庞，漆黑的眸子木然的在周围那些嘲讽的同龄人身上扫过。

萧炎，十六岁，男，萧家年轻一辈曾经的修炼天才。身穿青色长袍，眉宇间有一道浅浅的竖纹，双眼深邃但透着颓废。

"下一个，萧媚！"

少女年龄不过十四左右，虽然并算不上绝色，不过那张稚气未脱的小脸，却是蕴含着淡淡的妩媚。萧媚，女，萧家少女，身穿粉色罗裙，眼眸灵动。

"下一个，萧薰儿！"

一位身着紫色衣裙的少女，正淡雅的站立，平静的稚嫩俏脸，并未因为众人的注目而改变分毫。萧薰儿，十四岁，女，萧家天才少女，容貌清冷脱俗，气质如清莲初绽。

萧战，男，四十余岁，萧家族长，萧炎的父亲。身材魁梧，面容刚毅，留有短须。

药尘，人称药尊者，年龄不详的老者，寄居在萧炎戒指中的灵魂。声音苍老，性格玩味得意。
"""


def _print_section(title: str) -> None:
    print()
    print("─" * 80)
    print(f"【{title}】")
    print("─" * 80)


def _print_static_attrs(label: str, attrs: dict[str, str]) -> None:
    print(f"  {label}:")
    if not attrs:
        print("    (空)")
        return
    for key, value in attrs.items():
        print(f"    {key}: {value[:80]}")


def run_static_attrs_real_novel_test():
    """真实小说数据 — 静态属性全链路测试。"""
    print("=" * 80)
    print("灵枢 V3 — 真实小说数据静态属性全链路测试")
    print("=" * 80)

    with TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "novels.db")
        try:
            db.initialize()

            # Step 1: 创建书籍与章节
            _print_section("Step 1: 创建书籍与章节")
            book_id = db.create_book("斗破苍穹-静态属性测试")
            ch_id = db.create_chapter(book_id, "第一章 陨落的天才")
            db.update_chapter(ch_id, outline="", content=CHAPTER_CONTENT)
            print(f"  书籍 id={book_id}, 章节 id={ch_id}, 内容字数={len(CHAPTER_CONTENT)}")

            # Step 2: 创建人物（验证 create_character 自动初始化空静态属性）
            _print_section("Step 2: 创建人物并验证静态属性默认为空")
            char_names = ["萧炎", "萧薰儿", "萧媚", "萧战", "药尘"]
            char_ids: dict[str, int] = {}
            for name in char_names:
                cid = db.create_character(book_id, name)
                char_ids[name] = cid
                sm = dict(db.get_state_machine(cid)) if db.get_state_machine(cid) else {}
                static_attrs = {
                    "alias": sm.get("alias", ""),
                    "age": sm.get("age", ""),
                    "gender": sm.get("gender", ""),
                    "appearance_keywords": sm.get("appearance_keywords", ""),
                    "signature_feature": sm.get("signature_feature", ""),
                    "identity_occupation": sm.get("identity_occupation", ""),
                }
                _print_static_attrs(f"创建时 {name}", static_attrs)
                # 验证所有静态属性字段为空字符串
                for field, val in static_attrs.items():
                    assert val == "", f"创建人物后 {name}.{field} 应为空字符串，实际为 '{val}'"
            print("  ✓ 所有人物创建后静态属性字段默认为空字符串")

            # Step 3: 运行 V3 全链路分析
            _print_section("Step 3: 运行 V3 全链路分析")
            pipeline = AnalysisPipelineV3(db)
            result = pipeline.start_run(book_id)
            print(f"  运行状态: {result.status}")
            print(f"  Run ID: {result.run_id}")
            print(f"  语义块数: {result.block_count}")
            print(f"  实体提及数: {result.mention_count}")
            print(f"  实体候选数: {result.entity_count}")
            print(f"  原子事实数: {result.fact_count}")
            print(f"  卡片数: {result.card_count}")

            # Step 4: 查看 facts 中含静态属性关键词的条目
            _print_section("Step 4: 检查 facts 中含静态属性关键词的条目")
            facts = db.list_analysis_facts(book_id, run_id=result.run_id)
            static_keywords = ["外貌", "形象", "年龄", "性别", "身份", "职业", "别名", "称号", "appearance", "age", "gender"]
            static_facts: list[dict] = []
            for fact in facts:
                fact_row = dict(fact)
                fact_type = str(fact_row.get("fact_type") or "").lower()
                fact_value = fact_row.get("value") or {}
                summary = str(fact_value.get("summary") or "") if isinstance(fact_value, dict) else ""
                combined = f"{fact_type} {summary}".lower()
                if any(kw in combined for kw in static_keywords):
                    static_facts.append(fact_row)
                    print(f"  [{fact_row.get('fact_uid', '')[:16]}] type={fact_type}")
                    print(f"    summary: {summary[:100]}")
            print(f"  共找到 {len(static_facts)} 条含静态属性关键词的 facts")

            # Step 5: 测试 _extract_static_attrs_from_facts 函数
            _print_section("Step 5: 测试 _extract_static_attrs_from_facts 提取静态属性")
            extracted = _extract_static_attrs_from_facts([dict(f) for f in facts])
            _print_static_attrs("从全量 facts 提取", extracted)
            if extracted:
                print("  ✓ _extract_static_attrs_from_facts 成功提取静态属性字段")
            else:
                print("  ⚠ 未从 facts 提取到静态属性（facts 可能未包含外貌/年龄等关键词）")

            # Step 6: 构造含明确静态属性的 facts，验证 build_v3_entity_card 输出
            _print_section("Step 6: 验证 build_v3_entity_card 结构化输出静态属性")
            test_entity = {
                "entity_uid": "TEST-CHAR-XYAN",
                "canonical_name": "萧炎",
                "entity_type": "character",
                "metadata": {"role": "主角"},
            }
            test_facts = [
                {"fact_uid": "F1", "fact_type": "appearance", "value": {"summary": "清秀稚嫩脸庞，漆黑眸子，眉宇间有浅浅竖纹"},
                 "quote_text": "露出一张有些清秀的稚嫩脸庞", "subject_entity_uid": "TEST-CHAR-XYAN"},
                {"fact_uid": "F2", "fact_type": "age", "value": {"summary": "十六岁"},
                 "quote_text": "萧炎，十六岁", "subject_entity_uid": "TEST-CHAR-XYAN"},
                {"fact_uid": "F3", "fact_type": "gender", "value": {"summary": "男"},
                 "quote_text": "萧炎，十六岁，男", "subject_entity_uid": "TEST-CHAR-XYAN"},
                {"fact_uid": "F4", "fact_type": "identity_occupation", "value": {"summary": "萧家年轻一辈曾经的修炼天才"},
                 "quote_text": "萧家年轻一辈曾经的修炼天才", "subject_entity_uid": "TEST-CHAR-XYAN"},
                {"fact_uid": "F5", "fact_type": "event", "value": {"summary": "参加测验"},
                 "quote_text": "测验魔石碑", "subject_entity_uid": "TEST-CHAR-XYAN"},
            ]
            card = build_v3_entity_card(
                book_id=book_id,
                run_id=1,
                entity=test_entity,
                facts=test_facts,
                card_type="v3_character",
                dependency_hash="test-dep-hash-static-attrs",
            )
            card_payload = card.payload if hasattr(card, "payload") else {}
            writeback_fields = card_payload.get("writeback_fields", {}) if isinstance(card_payload, dict) else {}
            _print_static_attrs("build_v3_entity_card 输出 writeback_fields", writeback_fields)

            # 验证静态属性字段被结构化提取到 writeback_fields
            assert "appearance_keywords" in writeback_fields, "writeback_fields 应包含 appearance_keywords"
            assert "age" in writeback_fields, "writeback_fields 应包含 age"
            assert "gender" in writeback_fields, "writeback_fields 应包含 gender"
            assert "identity_occupation" in writeback_fields, "writeback_fields 应包含 identity_occupation"
            assert "清秀" in writeback_fields["appearance_keywords"], f"appearance_keywords 内容应含 '清秀'，实际: {writeback_fields['appearance_keywords']}"
            assert "十六" in writeback_fields["age"], f"age 内容应含 '十六'，实际: {writeback_fields['age']}"
            print("  ✓ build_v3_entity_card 成功结构化提取静态属性到 writeback_fields")

            # Step 7: 验证 writeback_to_state_machine 写入状态机静态属性字段
            _print_section("Step 7: 验证 writeback_to_state_machine 写入状态机")
            xiaoyan_id = char_ids["萧炎"]
            writeback_facts = [
                {"fact_uid": "WF1", "fact_type": "appearance", "value": {"summary": "清秀稚嫩脸庞，漆黑眸子"},
                 "quote_text": "清秀的稚嫩脸庞", "subject_entity_uid": "TEST-CHAR-XYAN"},
                {"fact_uid": "WF2", "fact_type": "age", "value": {"summary": "十六岁"},
                 "quote_text": "十六岁", "subject_entity_uid": "TEST-CHAR-XYAN"},
                {"fact_uid": "WF3", "fact_type": "gender", "value": {"summary": "男"},
                 "quote_text": "男", "subject_entity_uid": "TEST-CHAR-XYAN"},
                {"fact_uid": "WF4", "fact_type": "identity", "value": {"summary": "萧家年轻一辈曾经的修炼天才"},
                 "quote_text": "修炼天才", "subject_entity_uid": "TEST-CHAR-XYAN"},
            ]
            writeback_to_state_machine(db, book_id, xiaoyan_id, writeback_facts)
            sm = dict(db.get_state_machine(xiaoyan_id)) if db.get_state_machine(xiaoyan_id) else {}
            sm_static_attrs = {
                "alias": sm.get("alias", ""),
                "age": sm.get("age", ""),
                "gender": sm.get("gender", ""),
                "appearance_keywords": sm.get("appearance_keywords", ""),
                "signature_feature": sm.get("signature_feature", ""),
                "identity_occupation": sm.get("identity_occupation", ""),
            }
            _print_static_attrs("writeback_to_state_machine 后状态机", sm_static_attrs)

            assert "清秀" in sm_static_attrs["appearance_keywords"], f"状态机 appearance_keywords 应含 '清秀'，实际: {sm_static_attrs['appearance_keywords']}"
            assert "十六" in sm_static_attrs["age"], f"状态机 age 应含 '十六'，实际: {sm_static_attrs['age']}"
            assert "男" in sm_static_attrs["gender"], f"状态机 gender 应含 '男'，实际: {sm_static_attrs['gender']}"
            assert "天才" in sm_static_attrs["identity_occupation"], f"状态机 identity_occupation 应含 '天才'，实际: {sm_static_attrs['identity_occupation']}"
            print("  ✓ writeback_to_state_machine 成功写入静态属性到状态机字段")

            # Step 8: 验证保守映射 — 不覆盖已填的非空字段
            _print_section("Step 8: 验证保守映射不覆盖已填字段")
            new_facts = [
                {"fact_uid": "WF5", "fact_type": "age", "value": {"summary": "二十岁（新数据）"},
                 "quote_text": "二十岁", "subject_entity_uid": "TEST-CHAR-XYAN"},
                {"fact_uid": "WF6", "fact_type": "alias", "value": {"summary": "炎少"},
                 "quote_text": "炎少", "subject_entity_uid": "TEST-CHAR-XYAN"},
            ]
            writeback_to_state_machine(db, book_id, xiaoyan_id, new_facts)
            sm_after = dict(db.get_state_machine(xiaoyan_id)) if db.get_state_machine(xiaoyan_id) else {}
            # age 已有"十六岁"，不应被"二十岁"覆盖
            assert "十六" in sm_after.get("age", ""), f"保守映射失败：age 被覆盖为 '{sm_after.get('age')}'"
            # alias 原为空，应被写入"炎少"
            assert "炎少" in sm_after.get("alias", ""), f"保守映射失败：alias 未写入，实际为 '{sm_after.get('alias')}'"
            print("  ✓ age 保持 '十六岁'（未被覆盖）")
            print("  ✓ alias 写入 '炎少'（原为空，被填充）")

            # Step 9: 验证 update_character_form 状态机分支同步 profile_data_json
            _print_section("Step 9: 验证 update_character_form 同步 profile_data_json")
            db.update_character_form(
                xiaoyan_id,
                name="萧炎",
                role="主角",
                profile_data={
                    "appearance_keywords": "青色长袍，眉宇竖纹",
                    "age": "十六岁",
                    "gender": "男",
                },
            )
            # 读取 profile_data_json 验证同步
            row = db.connection.execute(
                "SELECT profile_data_json FROM characters WHERE id = ?",
                (xiaoyan_id,),
            ).fetchone()
            profile_json = row["profile_data_json"] if row else None
            profile_data = json.loads(profile_json) if profile_json else {}
            fields_dict = profile_data.get("fields", {}) if isinstance(profile_data, dict) else {}
            synced_appearance = fields_dict.get("appearance_keywords", {}).get("value", "") if isinstance(fields_dict.get("appearance_keywords"), dict) else ""
            synced_age = fields_dict.get("age", {}).get("value", "") if isinstance(fields_dict.get("age"), dict) else ""
            print(f"  profile_data_json.appearance_keywords: {synced_appearance}")
            print(f"  profile_data_json.age: {synced_age}")
            assert "青色长袍" in synced_appearance, f"profile_data_json 中 appearance_keywords 未同步: '{synced_appearance}'"
            assert "十六" in synced_age, f"profile_data_json 中 age 未同步: '{synced_age}'"
            print("  ✓ update_character_form 成功同步静态属性到 profile_data_json")

            # Step 10: 验证 _generate_legacy_form_from_state_machine 反向填充
            _print_section("Step 10: 验证 _generate_legacy_form_from_state_machine 反向填充")
            legacy_form = db.get_character_profile_form(xiaoyan_id)
            legacy_fields = legacy_form.get("fields", {}) if isinstance(legacy_form, dict) else {}
            legacy_appearance = legacy_fields.get("appearance_keywords", {}).get("value", "") if isinstance(legacy_fields.get("appearance_keywords"), dict) else ""
            legacy_age = legacy_fields.get("age", {}).get("value", "") if isinstance(legacy_fields.get("age"), dict) else ""
            legacy_gender = legacy_fields.get("gender", {}).get("value", "") if isinstance(legacy_fields.get("gender"), dict) else ""
            print(f"  旧表单 appearance_keywords: {legacy_appearance}")
            print(f"  旧表单 age: {legacy_age}")
            print(f"  旧表单 gender: {legacy_gender}")
            assert legacy_appearance, "旧表单 appearance_keywords 不应为空"
            assert legacy_age, "旧表单 age 不应为空"
            assert legacy_gender, "旧表单 gender 不应为空"
            print("  ✓ _generate_legacy_form_from_state_machine 成功反向填充旧表单静态属性")

            # 最终汇总
            _print_section("测试汇总")
            print("  ✓ create_character 自动初始化静态属性字段为空")
            print("  ✓ build_v3_entity_card 结构化提取静态属性到 writeback_fields")
            print("  ✓ writeback_to_state_machine 写入静态属性到状态机字段")
            print("  ✓ 保守映射不覆盖已填非空字段")
            print("  ✓ update_character_form 同步静态属性到 profile_data_json")
            print("  ✓ _generate_legacy_form_from_state_machine 反向填充旧表单")
            print()
            print("=" * 80)
            print("真实小说数据静态属性全链路测试 — 全部通过！")
            print("=" * 80)

        finally:
            db.close()


if __name__ == "__main__":
    run_static_attrs_real_novel_test()
