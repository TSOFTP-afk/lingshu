from __future__ import annotations

from novel_app.structured_templates import (
    book_outline_form_to_markdown,
    merge_book_outline_form,
    normalize_book_outline_form,
)
from novel_app.tag_registry import (
    ALL_PARENT_TAG_ID,
    CHILD_TAGS,
    PARENT_TAGS,
    book_tag_profile_to_truth_lines,
    list_child_tags,
    normalize_book_tag_profile,
    search_book_tags,
)


def test_embedded_parent_tags_include_book_template_categories() -> None:
    parent_names = {tag["name"] for tag in PARENT_TAGS}

    assert len(PARENT_TAGS) == 19
    assert {"玄幻", "都市", "动漫/游戏衍生", "二次元/同人", "文娱"}.issubset(parent_names)
    assert "穿越" not in parent_names


def test_embedded_child_tags_include_relationship_mapping() -> None:
    child_names = {tag["name"] for tag in CHILD_TAGS}
    dushi_child_names = {tag["name"] for tag in list_child_tags("dushi")}

    assert len(CHILD_TAGS) == 271
    assert {"神豪", "系统流", "凡人流", "两界穿梭"}.issubset(child_names)
    assert "神豪" in dushi_child_names
    assert "系统流" in dushi_child_names
    assert next(tag for tag in CHILD_TAGS if tag["name"] == "系统流")["parent_ids"] == [ALL_PARENT_TAG_ID]


def test_chuanyue_remains_child_tag_not_parent_tag() -> None:
    chuanyue_child_names = {tag["name"] for tag in list_child_tags("chuanyue")}

    assert all(tag["id"] != "chuanyue" for tag in PARENT_TAGS)
    assert "穿越" in chuanyue_child_names
    assert "重生" in chuanyue_child_names


def test_book_tag_search_respects_parent_and_all_parent_children() -> None:
    results = search_book_tags("神豪", parent_id="都市")

    assert results[0]["type"] == "child"
    assert results[0]["name"] == "神豪"
    assert results[0]["parent_ids"] == ["dushi"]

    all_parent_results = search_book_tags("系统流", parent_id="都市")
    assert all_parent_results[0]["name"] == "系统流"
    assert all_parent_results[0]["parent_ids"] == [ALL_PARENT_TAG_ID]


def test_book_outline_form_preserves_normalized_tag_profile() -> None:
    data = normalize_book_outline_form(
        {
            "tag_profile": {
                "primary_parent_tag_id": "xuanhuan",
                "selected_child_tags": [{"id": "fanrenliu", "name": "凡人流"}],
                "custom_tags": [{"name": "失败越强", "description": "失败推动升级"}],
            }
        },
        "测试书",
    )

    profile = data["tag_profile"]

    assert profile["primary_parent_tag_id"] == "xuanhuan"
    assert data["fields"]["primary_parent_tag_id"]["value"] == "xuanhuan"
    assert profile["selected_parent_tags"][0]["name"] == "玄幻"
    assert profile["selected_child_tags"][0]["id"] == "凡人流"
    assert profile["selected_child_tags"][0]["name"] == "凡人流"
    assert profile["selected_child_tags"][0]["parent_ids"] == [ALL_PARENT_TAG_ID]
    assert profile["custom_tags"][0]["source"] == "user_custom"


def test_book_outline_supplements_are_numbered_when_title_is_empty() -> None:
    data = normalize_book_outline_form(
        {
            "supplements": [
                {"content": "第一条额外设定"},
                {"title": "补充设定 2", "content": "第二条额外设定"},
            ]
        },
        "测试书",
    )

    assert data["supplements"][0]["title"] == "补充设定 1"
    assert data["supplements"][1]["title"] == "补充设定 2"
    rendered = book_outline_form_to_markdown(data, "测试书")
    assert "## 补充设定 1" in rendered
    assert "第一条额外设定" in rendered
    assert "## 补充设定 2" in rendered
    assert "第二条额外设定" in rendered


def test_book_outline_legacy_supplemental_settings_moves_to_supplements() -> None:
    data = normalize_book_outline_form(
        {"fields": {"supplemental_settings": {"value": "旧字段里的补充设定"}}},
        "测试书",
    )

    assert data["fields"]["supplemental_settings"]["value"] == ""
    assert data["supplements"] == [{"title": "补充设定 1", "content": "旧字段里的补充设定"}]


def test_merge_book_outline_form_does_not_clear_existing_tags_with_empty_incoming() -> None:
    base = normalize_book_outline_form(
        {"tag_profile": {"selected_parent_tag_ids": ["xuanhuan"]}},
        "测试书",
    )
    merged = merge_book_outline_form(base, {"fields": {}}, "测试书")

    assert merged["tag_profile"]["selected_parent_tag_ids"] == ["xuanhuan"]
    assert merged["tag_profile"]["selected_parent_tags"][0]["name"] == "玄幻"


def test_book_tag_profile_truth_lines_are_empty_without_confirmed_selection() -> None:
    assert book_tag_profile_to_truth_lines(normalize_book_tag_profile({})) == []


def test_book_tag_profile_truth_lines_mark_custom_source() -> None:
    lines = book_tag_profile_to_truth_lines(
        {
            "selected_parent_tag_ids": ["xuanhuan"],
            "custom_tags": [{"name": "崩坏主B", "parent_name": "二次元/同人"}],
        }
    )
    rendered = "\n".join(lines)

    assert "书籍标签画像" in rendered
    assert "玄幻" in rendered
    assert "source=user_custom" in rendered
    assert "崩坏主B" in rendered


def test_custom_tag_is_not_written_to_embedded_registry() -> None:
    profile = normalize_book_tag_profile(
        {
            "selected_child_tag_ids": ["不存在的内嵌标签"],
            "custom_tags": [{"name": "失败越强", "description": "用户自定义"}],
        }
    )

    assert all(tag["name"] != "失败越强" for tag in CHILD_TAGS)
    assert profile["selected_child_tags"][0]["name"] == "不存在的内嵌标签"
    assert profile["custom_tags"][0]["source"] == "user_custom"
