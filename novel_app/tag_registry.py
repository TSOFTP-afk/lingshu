from __future__ import annotations

from typing import Any

from novel_app.tag_registry_data import ALL_PARENT_TAG_ID, CHILD_TAG_ROWS

BOOK_TAG_REGISTRY_VERSION = "book_tag_registry_v2"

PARENT_TAGS: list[dict[str, str]] = [
    {"id": "xuanhuan", "name": "玄幻", "description": "东方幻想、修炼体系、异世大陆等大类。"},
    {"id": "qihuan", "name": "奇幻", "description": "西式幻想、魔法、史诗冒险等大类。"},
    {"id": "wuxia", "name": "武侠", "description": "江湖、门派、侠义与武学冲突。"},
    {"id": "xianxia", "name": "仙侠", "description": "修仙、宗门、飞升与仙道体系。"},
    {"id": "dushi", "name": "都市", "description": "现代城市生活、职场、异能与商业。"},
    {"id": "xianshi", "name": "现实", "description": "现实题材、时代生活与社会议题。"},
    {"id": "lishi", "name": "历史", "description": "历史背景、架空王朝与权谋战争。"},
    {"id": "junshi", "name": "军事", "description": "军旅、战争、战术与组织对抗。"},
    {"id": "youxi", "name": "游戏", "description": "网游、电竞、游戏系统与副本机制。"},
    {"id": "tiyu", "name": "体育", "description": "竞技体育、训练成长与赛事叙事。"},
    {"id": "kehuan", "name": "科幻", "description": "未来科技、星际、赛博与硬科幻设定。"},
    {"id": "xuanyi_lingyi", "name": "悬疑灵异", "description": "案件、谜团、怪谈与灵异元素。"},
    {"id": "qingxiaoshuo", "name": "轻小说", "description": "轻小说结构、青春、校园与二次元表达。"},
    {"id": "zhutian_wuxian", "name": "诸天无限", "description": "多世界穿梭、无限流与副本世界。"},
    {"id": "yanqing", "name": "言情", "description": "情感关系、恋爱推进与人物羁绊。"},
    {"id": "dongman_youxi_yansheng", "name": "动漫/游戏衍生", "description": "基于动漫或游戏剧情世界观的衍生创作。"},
    {"id": "erciyuan_tongren", "name": "二次元/同人", "description": "二次元风格、同人创作与跨作品元素。"},
    {"id": "moshi", "name": "末世", "description": "灾变、生存、秩序崩坏与重建。"},
    {"id": "wenyu", "name": "文娱", "description": "娱乐圈、创作、影视音乐与文化产业。"},
]

PARENT_TAG_BY_ID = {item["id"]: item for item in PARENT_TAGS}
PARENT_TAG_BY_NAME = {item["name"]: item for item in PARENT_TAGS}
PARENT_TAG_ALIASES = {
    "二次元": "erciyuan_tongren",
    "二次元/二次元": "erciyuan_tongren",
    "动漫游戏衍生": "dongman_youxi_yansheng",
    "动漫/游戏衍生": "dongman_youxi_yansheng",
    "现代": "dushi",
    "全部": ALL_PARENT_TAG_ID,
}

LEGACY_CHILD_TAG_ALIASES = {
    "fanrenliu": "凡人流",
}


def _parent_name(parent_id: str) -> str:
    if parent_id == ALL_PARENT_TAG_ID:
        return "全部"
    parent = PARENT_TAG_BY_ID.get(parent_id)
    return str(parent.get("name") if parent else parent_id).strip()


def _child_from_row(tag_id: str, name: str, parent_ids: tuple[str, ...], description: str) -> dict[str, Any]:
    normalized_parent_ids = [parent_id for parent_id in parent_ids if parent_id == ALL_PARENT_TAG_ID or parent_id in PARENT_TAG_BY_ID]
    return {
        "id": str(tag_id).strip(),
        "name": str(name).strip(),
        "parent_ids": normalized_parent_ids,
        "parent_names": [_parent_name(parent_id) for parent_id in normalized_parent_ids],
        "description": str(description).strip(),
    }


CHILD_TAGS = [_child_from_row(tag_id, name, parent_ids, description) for tag_id, name, parent_ids, description in CHILD_TAG_ROWS]
CHILD_TAG_BY_ID = {item["id"]: item for item in CHILD_TAGS}
CHILD_TAG_BY_NAME = {item["name"]: item for item in CHILD_TAGS}


def list_parent_tags() -> list[dict[str, str]]:
    return [dict(item) for item in PARENT_TAGS]


def list_child_tags(parent_id: str | None = None) -> list[dict[str, Any]]:
    resolved_parent_id = resolve_parent_tag_id(parent_id) if parent_id else ""
    children: list[dict[str, Any]] = []
    for child in CHILD_TAGS:
        child_parent_ids = list(child.get("parent_ids") or [])
        if resolved_parent_id:
            if resolved_parent_id == ALL_PARENT_TAG_ID:
                if ALL_PARENT_TAG_ID not in child_parent_ids:
                    continue
            elif ALL_PARENT_TAG_ID not in child_parent_ids and resolved_parent_id not in child_parent_ids:
                continue
        children.append(dict(child))
    return children


def search_book_tags(query: str, parent_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    try:
        max_results = max(0, int(limit))
    except (TypeError, ValueError):
        max_results = 20
    if max_results <= 0:
        return []

    normalized_query = str(query or "").strip().casefold()
    resolved_parent_id = resolve_parent_tag_id(parent_id) if parent_id else ""
    candidates: list[tuple[int, int, dict[str, Any]]] = []

    for index, parent in enumerate(PARENT_TAGS):
        if resolved_parent_id and parent["id"] != resolved_parent_id:
            continue
        item: dict[str, Any] = {"type": "parent", **parent}
        score = _tag_search_score(item, normalized_query)
        if score > 0:
            candidates.append((score, index, item))

    child_offset = len(PARENT_TAGS)
    for index, child in enumerate(list_child_tags(resolved_parent_id or None)):
        item = {"type": "child", **child}
        score = _tag_search_score(item, normalized_query)
        if score > 0:
            candidates.append((score, child_offset + index, item))

    candidates.sort(key=lambda row: (-row[0], row[1]))
    return [dict(item, score=score) for score, _, item in candidates[:max_results]]


def resolve_parent_tag_id(value: Any) -> str:
    text = _tag_id_or_name(value)
    if not text:
        return ""
    if text in PARENT_TAG_BY_ID or text == ALL_PARENT_TAG_ID:
        return text
    registry = PARENT_TAG_BY_NAME.get(text)
    if registry:
        return registry["id"]
    alias = PARENT_TAG_ALIASES.get(text)
    if alias:
        return alias
    return text


def resolve_child_tag(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        tag_id = str(value.get("id") or "").strip()
        name = str(value.get("name") or "").strip()
        return _child_registry_match(tag_id) or _child_registry_match(name)
    return _child_registry_match(_tag_id_or_name(value))


def normalize_book_tag_profile(profile: Any) -> dict[str, Any]:
    if not isinstance(profile, dict):
        profile = {}

    selected_parent_ids = _string_list(profile.get("selected_parent_tag_ids"))
    primary = _tag_id_or_name(profile.get("primary_parent_tag_id") or profile.get("primary_parent_tag"))
    if primary:
        selected_parent_ids.insert(0, primary)
    selected_parent_ids.extend(_string_list(profile.get("secondary_parent_tag_ids")))
    parent_entries = _normalize_parent_entries(profile.get("selected_parent_tags"))
    for entry in parent_entries:
        selected_parent_ids.append(str(entry.get("id") or entry.get("name") or ""))
    selected_parent_ids = _dedupe([resolve_parent_tag_id(tag_id) for tag_id in selected_parent_ids])
    parent_entries = _merge_parent_entries(selected_parent_ids, parent_entries)

    selected_child_ids = _dedupe([_canonical_child_tag_id(tag_id) for tag_id in _string_list(profile.get("selected_child_tag_ids"))])
    child_entries = _normalize_child_entries(profile.get("selected_child_tags"))
    for entry in child_entries:
        child_id = str(entry.get("id") or entry.get("name") or "").strip()
        if child_id:
            selected_child_ids.append(_canonical_child_tag_id(child_id))
    selected_child_ids = _dedupe(selected_child_ids)
    child_entries = _merge_child_entries(selected_child_ids, child_entries)

    return {
        "version": str(profile.get("version") or BOOK_TAG_REGISTRY_VERSION),
        "primary_parent_tag_id": selected_parent_ids[0] if selected_parent_ids else "",
        "selected_parent_tag_ids": selected_parent_ids,
        "selected_parent_tags": parent_entries,
        "selected_child_tag_ids": selected_child_ids,
        "selected_child_tags": child_entries,
        "custom_tags": _normalize_custom_tags(profile.get("custom_tags")),
        "tag_notes": str(profile.get("tag_notes") or profile.get("notes") or "").strip(),
        "activated_at": str(profile.get("activated_at") or "").strip(),
    }


def book_tag_profile_has_selection(profile: dict[str, Any]) -> bool:
    normalized = normalize_book_tag_profile(profile)
    return bool(
        normalized["selected_parent_tags"]
        or normalized["selected_child_tags"]
        or normalized["custom_tags"]
        or normalized["tag_notes"]
    )


def book_tag_profile_to_truth_lines(profile: dict[str, Any]) -> list[str]:
    normalized = normalize_book_tag_profile(profile)
    if not book_tag_profile_has_selection(normalized):
        return []

    lines = ["## 书籍标签画像"]
    parent_names = [str(item.get("name") or item.get("id") or "").strip() for item in normalized["selected_parent_tags"]]
    child_names = [str(item.get("name") or item.get("id") or "").strip() for item in normalized["selected_child_tags"]]
    if parent_names:
        lines.append(f"- 已选父标签：{', '.join(_dedupe(parent_names))}")
    if child_names:
        lines.append(f"- 已选子标签：{', '.join(_dedupe(child_names))}")
    for custom in normalized["custom_tags"]:
        name = str(custom.get("name") or "").strip()
        if not name:
            continue
        details = ["source=user_custom"]
        parent_name = str(custom.get("parent_name") or "").strip()
        if parent_name:
            details.append(f"父标签={parent_name}")
        description = str(custom.get("description") or "").strip()
        suffix = f"：{description}" if description else ""
        lines.append(f"- 自定义标签：{name} ({'; '.join(details)}){suffix}")
    notes = str(normalized.get("tag_notes") or "").strip()
    if notes:
        lines.append(f"- 标签备注：{notes}")
    lines.append("")
    return lines


def _tag_id_or_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("id") or value.get("name") or "").strip()
    return str(value or "").strip()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            text = _tag_id_or_name(item)
            if text:
                result.append(text)
        return result
    text = _tag_id_or_name(value)
    return [text] if text else []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _normalize_parent_entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            tag_id = str(item.get("id") or item.get("name") or "").strip()
            name = str(item.get("name") or "").strip()
            description = str(item.get("description") or "").strip()
        else:
            tag_id = str(item or "").strip()
            name = ""
            description = ""
        if not tag_id and not name:
            continue
        resolved_id = resolve_parent_tag_id(tag_id) or resolve_parent_tag_id(name)
        registry = PARENT_TAG_BY_ID.get(resolved_id)
        entries.append(
            {
                "id": str(registry.get("id") if registry else resolved_id or tag_id).strip(),
                "name": str(registry.get("name") if registry else (name or tag_id)).strip(),
                "description": str(registry.get("description") if registry else description).strip(),
            }
        )
    return _dedupe_entries(entries)


def _merge_parent_entries(tag_ids: list[str], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for item in entries:
        for key in {str(item.get("id") or "").strip(), str(item.get("name") or "").strip(), resolve_parent_tag_id(item)}:
            if key:
                by_key[key] = item
    merged: list[dict[str, Any]] = []
    for tag_id in tag_ids:
        resolved_id = resolve_parent_tag_id(tag_id)
        registry = PARENT_TAG_BY_ID.get(resolved_id)
        entry = by_key.get(tag_id) or by_key.get(resolved_id)
        if registry:
            merged.append(dict(registry))
        elif entry:
            merged.append(dict(entry))
        else:
            merged.append({"id": resolved_id or tag_id, "name": tag_id, "description": ""})
    return _dedupe_entries(merged)


def _normalize_child_entries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("id") or "").strip()
            tag_id = str(item.get("id") or name).strip()
            parent_ids = _string_list(item.get("parent_ids"))
            description = str(item.get("description") or "").strip()
        else:
            name = str(item or "").strip()
            tag_id = name
            parent_ids = []
            description = ""
        registry = resolve_child_tag({"id": tag_id, "name": name})
        if registry:
            entries.append(_copy_child_tag(registry))
            continue
        if not name and not tag_id:
            continue
        normalized_parent_ids = _canonical_parent_ids(parent_ids)
        entries.append(
            {
                "id": tag_id,
                "name": name or tag_id,
                "parent_ids": normalized_parent_ids,
                "parent_names": [_parent_name(parent_id) for parent_id in normalized_parent_ids],
                "description": description,
            }
        )
    return _dedupe_entries(entries)


def _merge_child_entries(tag_ids: list[str], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for item in entries:
        for key in {str(item.get("id") or "").strip(), str(item.get("name") or "").strip(), _canonical_child_tag_id(item)}:
            if key:
                by_key[key] = item
    merged: list[dict[str, Any]] = []
    for tag_id in tag_ids:
        resolved_id = _canonical_child_tag_id(tag_id)
        registry = resolve_child_tag(resolved_id)
        entry = by_key.get(tag_id) or by_key.get(resolved_id)
        if registry:
            merged.append(_copy_child_tag(registry))
        elif entry:
            merged.append(dict(entry))
        else:
            merged.append({"id": resolved_id or tag_id, "name": tag_id, "parent_ids": [], "parent_names": [], "description": ""})
    return _dedupe_entries(merged)


def _normalize_custom_tags(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    tags: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            description = str(item.get("description") or item.get("note") or "").strip()
            parent_name = str(item.get("parent_name") or item.get("parent") or "").strip()
        else:
            name = str(item or "").strip()
            description = ""
            parent_name = ""
        if not name:
            continue
        tags.append(
            {
                "name": name,
                "description": description,
                "parent_name": parent_name,
                "source": "user_custom",
            }
        )
    return tags


def _tag_search_score(item: dict[str, Any], normalized_query: str) -> int:
    if not normalized_query:
        return 1
    tag_id = str(item.get("id") or "").casefold()
    name = str(item.get("name") or "").casefold()
    description = str(item.get("description") or "").casefold()
    parent_names = " ".join(str(name) for name in item.get("parent_names") or []).casefold()

    if normalized_query in (name, tag_id):
        return 100
    if name.startswith(normalized_query) or tag_id.startswith(normalized_query):
        return 80
    if normalized_query in name or normalized_query in tag_id:
        return 70
    if parent_names and normalized_query in parent_names:
        return 50
    if description and normalized_query in description:
        return 30
    return 0


def _child_registry_match(value: Any) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if not text:
        return None
    aliased = LEGACY_CHILD_TAG_ALIASES.get(text, text)
    return CHILD_TAG_BY_ID.get(aliased) or CHILD_TAG_BY_NAME.get(aliased)


def _canonical_child_tag_id(value: Any) -> str:
    text = _tag_id_or_name(value)
    if not text:
        return ""
    registry = resolve_child_tag(value)
    return str(registry.get("id") if registry else text).strip()


def _canonical_parent_ids(values: list[str]) -> list[str]:
    parent_ids: list[str] = []
    for value in values:
        parent_id = resolve_parent_tag_id(value)
        if parent_id:
            parent_ids.append(parent_id)
    return _dedupe(parent_ids)


def _copy_child_tag(tag: dict[str, Any]) -> dict[str, Any]:
    parent_ids = [str(parent_id).strip() for parent_id in tag.get("parent_ids") or [] if str(parent_id).strip()]
    parent_names = list(tag.get("parent_names") or [_parent_name(parent_id) for parent_id in parent_ids])
    return {
        "id": str(tag.get("id") or tag.get("name") or "").strip(),
        "name": str(tag.get("name") or tag.get("id") or "").strip(),
        "parent_ids": parent_ids,
        "parent_names": parent_names,
        "description": str(tag.get("description") or "").strip(),
    }


def _dedupe_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for entry in entries:
        key = str(entry.get("id") or entry.get("name") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return result
