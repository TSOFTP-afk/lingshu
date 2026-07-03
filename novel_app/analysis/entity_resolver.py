from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from novel_app.analysis.evidence import extract_evidence_refs

CHARACTER_CONTAINERS = (
    "characters",
    "character_cards",
    "character_profiles",
    "character_profile",
    "character_data",
)
WORLD_CONTAINERS = (
    "world_entries",
    "world",
    "worldbuilding",
    "world_elements",
    "locations",
    "organizations",
    "items",
    "concepts",
)
NAME_KEYS = ("name", "title", "label", "character_name", "entity_name", "target_entity")
ALIAS_KEYS = ("alias", "aliases", "aka", "also_known_as", "nicknames", "other_names")
ROLE_KEYS = ("role", "character_role", "position", "category", "type", "kind")
IGNORED_MAP_KEYS = {"fields", "metadata", "_meta", "evidence", "evidence_refs", "source_requests"}

ENTITY_TYPE_PREFIXES = {
    "book": "ENT-B",
    "character": "ENT-P",
    "person": "ENT-P",
    "location": "ENT-L",
    "organization": "ENT-O",
    "item": "ENT-I",
    "concept": "ENT-C",
    "world": "ENT-W",
    "group": "ENT-G",
}

ENTITY_TYPE_ALIASES = {
    "char": "character",
    "character": "character",
    "person": "character",
    "people": "character",
    "role": "character",
    "\u4eba\u7269": "character",
    "\u89d2\u8272": "character",
    "\u4e3b\u89d2": "character",
    "location": "location",
    "place": "location",
    "\u5730\u70b9": "location",
    "\u5730\u540d": "location",
    "\u573a\u6240": "location",
    "organization": "organization",
    "org": "organization",
    "\u7ec4\u7ec7": "organization",
    "\u52bf\u529b": "organization",
    "item": "item",
    "artifact": "item",
    "object": "item",
    "\u7269\u54c1": "item",
    "\u9053\u5177": "item",
    "\u5b9d\u7269": "item",
    "concept": "concept",
    "rule": "concept",
    "\u6982\u5ff5": "concept",
    "\u89c4\u5219": "concept",
    "\u8bbe\u5b9a": "concept",
    "world": "world",
    "worldbuilding": "world",
    "\u4e16\u754c": "world",
    "\u4e16\u754c\u89c2": "world",
}


@dataclass(frozen=True)
class EntityMention:
    mention: str
    entity_type: str
    source_path: str = ""
    aliases: tuple[str, ...] = ()
    role: str = ""
    confidence: float = 0.7
    evidence_refs: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "mention": self.mention,
            "entity_type": self.entity_type,
            "source_path": self.source_path,
            "aliases": list(self.aliases),
            "role": self.role,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class ResolvedEntity:
    entity_uid: str
    entity_type: str
    canonical_name: str
    aliases: tuple[str, ...]
    mentions: tuple[EntityMention, ...]
    confidence: float = 0.7

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity_uid": self.entity_uid,
            "entity_type": self.entity_type,
            "canonical_name": self.canonical_name,
            "aliases": list(self.aliases),
            "mention_count": len(self.mentions),
            "confidence": self.confidence,
            "mentions": [mention.as_dict() for mention in self.mentions],
        }


@dataclass(frozen=True)
class EntityResolutionResult:
    entities: tuple[ResolvedEntity, ...]
    mentions: tuple[EntityMention, ...]
    alias_map: dict[str, str]

    @property
    def entity_count(self) -> int:
        return len(self.entities)

    @property
    def mention_count(self) -> int:
        return len(self.mentions)

    def entity_uid_for(self, name: str, entity_type: str = "") -> str:
        normalized = normalize_entity_alias(name)
        if not normalized:
            return ""
        direct = self.alias_map.get(normalized)
        if direct:
            return direct
        wanted = normalize_entity_type(entity_type, "")
        for entity in self.entities:
            if wanted and entity.entity_type != wanted:
                continue
            if normalized == normalize_entity_alias(entity.canonical_name):
                return entity.entity_uid
        return ""

    def entities_by_type(self, *entity_types: str) -> list[ResolvedEntity]:
        wanted = {normalize_entity_type(item, item) for item in entity_types if str(item).strip()}
        if not wanted:
            return list(self.entities)
        return [entity for entity in self.entities if entity.entity_type in wanted]

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity_count": self.entity_count,
            "mention_count": self.mention_count,
            "entities": [entity.as_dict() for entity in self.entities],
            "alias_map": dict(sorted(self.alias_map.items())),
        }


class EntityResolver:
    def resolve(self, payload: dict[str, Any], *, book_id: int | None = None) -> EntityResolutionResult:
        mentions = tuple(self.extract_mentions(payload))
        entities = self._merge_mentions(mentions, book_id=book_id)
        alias_map: dict[str, str] = {}
        for entity in entities:
            for alias in (entity.canonical_name, *entity.aliases):
                normalized = normalize_entity_alias(alias)
                if normalized:
                    alias_map[normalized] = entity.entity_uid
        return EntityResolutionResult(entities=tuple(entities), mentions=mentions, alias_map=alias_map)

    def extract_mentions(self, payload: dict[str, Any]) -> list[EntityMention]:
        if not isinstance(payload, dict):
            return []
        mentions: list[EntityMention] = []
        for key in CHARACTER_CONTAINERS:
            if key in payload:
                mentions.extend(_mentions_from_container(payload.get(key), key, default_type="character"))
        for key in WORLD_CONTAINERS:
            if key in payload:
                mentions.extend(_mentions_from_container(payload.get(key), key, default_type=_world_type_for_container(key)))
        mentions.extend(_explicit_entity_mentions(payload, ""))
        return _dedupe_mentions(mentions)

    def _merge_mentions(
        self,
        mentions: tuple[EntityMention, ...],
        *,
        book_id: int | None = None,
    ) -> list[ResolvedEntity]:
        alias_to_uid: dict[str, str] = {}
        buckets: dict[str, dict[str, Any]] = {}
        for mention in mentions:
            names = [mention.mention, *mention.aliases]
            normalized_names = [normalize_entity_alias(name) for name in names]
            normalized_names = [name for name in normalized_names if name]
            if not normalized_names:
                continue
            uid = next((alias_to_uid[name] for name in normalized_names if name in alias_to_uid), "")
            if not uid:
                uid = stable_entity_uid(mention.entity_type, mention.mention, book_id=book_id)
            bucket = buckets.setdefault(
                uid,
                {
                    "entity_type": mention.entity_type,
                    "canonical_name": mention.mention,
                    "aliases": set(),
                    "mentions": [],
                    "confidence": [],
                },
            )
            bucket["mentions"].append(mention)
            bucket["confidence"].append(float(mention.confidence or 0.0))
            if len(mention.mention) > len(str(bucket["canonical_name"] or "")):
                bucket["canonical_name"] = mention.mention
            for name in names:
                if str(name).strip():
                    bucket["aliases"].add(str(name).strip())
            for normalized in normalized_names:
                alias_to_uid[normalized] = uid

        entities: list[ResolvedEntity] = []
        for uid, bucket in buckets.items():
            canonical = str(bucket["canonical_name"] or "").strip()
            aliases = sorted(
                str(alias).strip()
                for alias in bucket["aliases"]
                if str(alias).strip() and str(alias).strip() != canonical
            )
            confidences = [float(item) for item in bucket["confidence"] if item is not None]
            confidence = round(sum(confidences) / max(1, len(confidences)), 3)
            entities.append(
                ResolvedEntity(
                    entity_uid=uid,
                    entity_type=str(bucket["entity_type"] or "world"),
                    canonical_name=canonical,
                    aliases=tuple(aliases),
                    mentions=tuple(bucket["mentions"]),
                    confidence=confidence,
                )
            )
        return sorted(entities, key=lambda item: (item.entity_type, item.canonical_name, item.entity_uid))


def resolve_payload_entities(payload: dict[str, Any], *, book_id: int | None = None) -> EntityResolutionResult:
    return EntityResolver().resolve(payload, book_id=book_id)


def stable_entity_uid(entity_type: str, name: str, *, book_id: int | None = None) -> str:
    normalized_type = normalize_entity_type(entity_type, "world")
    normalized_name = normalize_entity_alias(name) or "unnamed"
    digest = hashlib.sha1(f"{normalized_type}:{normalized_name}".encode()).hexdigest()[:10].upper()
    prefix = ENTITY_TYPE_PREFIXES.get(normalized_type, ENTITY_TYPE_PREFIXES["world"])
    uid = f"{prefix}-{digest}"
    if book_id is not None:
        return f"BOOK-{int(book_id)}::{uid}"
    return uid


def normalize_entity_alias(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = re.sub(r"[\s\-_`'\"]+", "", text)
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text, flags=re.UNICODE)
    return text


def normalize_entity_type(value: Any, default: str = "world") -> str:
    raw = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    if not raw:
        return default
    for key, normalized in ENTITY_TYPE_ALIASES.items():
        if key in raw:
            return normalized
    return ENTITY_TYPE_ALIASES.get(raw, raw.replace(" ", "_")) or default


def _mentions_from_container(value: Any, path: str, *, default_type: str) -> list[EntityMention]:
    mentions: list[EntityMention] = []
    if isinstance(value, list):
        for index, item in enumerate(value):
            mentions.extend(_mentions_from_node(item, f"{path}[{index}]", default_type=default_type))
        return mentions
    if isinstance(value, dict):
        own = _mention_from_mapping(value, path, default_type=default_type)
        if own:
            mentions.append(own)
            return mentions
        for key, item in value.items():
            if str(key) in IGNORED_MAP_KEYS:
                continue
            child_path = f"{path}.{key}"
            if isinstance(item, dict):
                mentions.extend(_mentions_from_node(item, child_path, default_type=default_type, fallback_name=str(key)))
            elif isinstance(item, list):
                mentions.extend(_mentions_from_container(item, child_path, default_type=default_type))
            elif isinstance(item, str) and item.strip() and len(str(key).strip()) <= 40:
                mentions.append(
                    EntityMention(
                        mention=str(key).strip(),
                        entity_type=default_type,
                        source_path=child_path,
                        confidence=0.55,
                    )
                )
        return mentions
    if isinstance(value, str) and value.strip():
        return [
            EntityMention(
                mention=value.strip(),
                entity_type=default_type,
                source_path=path,
                confidence=0.5,
            )
        ]
    return mentions


def _mentions_from_node(
    value: Any,
    path: str,
    *,
    default_type: str,
    fallback_name: str = "",
) -> list[EntityMention]:
    if isinstance(value, dict):
        mention = _mention_from_mapping(value, path, default_type=default_type, fallback_name=fallback_name)
        if mention:
            return [mention]
        return _mentions_from_container(value, path, default_type=default_type)
    if isinstance(value, str) and value.strip():
        return [
            EntityMention(
                mention=value.strip(),
                entity_type=default_type,
                source_path=path,
                confidence=0.5,
            )
        ]
    return []


def _mention_from_mapping(
    value: dict[str, Any],
    path: str,
    *,
    default_type: str,
    fallback_name: str = "",
) -> EntityMention | None:
    name = _first_text(value, NAME_KEYS) or (fallback_name.strip() if fallback_name.strip() not in IGNORED_MAP_KEYS else "")
    if not name:
        return None
    aliases = tuple(alias for alias in _aliases_from_mapping(value) if normalize_entity_alias(alias) != normalize_entity_alias(name))
    role = _first_text(value, ROLE_KEYS)
    entity_type = normalize_entity_type(value.get("entity_type") or value.get("type") or value.get("category"), default_type)
    evidence_refs = tuple(ref.as_dict() for ref in extract_evidence_refs(value))
    confidence = 0.82 if _first_text(value, NAME_KEYS) else 0.62
    return EntityMention(
        mention=name,
        entity_type=entity_type,
        source_path=path,
        aliases=aliases,
        role=role,
        confidence=confidence,
        evidence_refs=evidence_refs,
    )


def _explicit_entity_mentions(value: Any, path: str) -> list[EntityMention]:
    mentions: list[EntityMention] = []
    if isinstance(value, list):
        for index, item in enumerate(value):
            mentions.extend(_explicit_entity_mentions(item, f"{path}[{index}]" if path else f"[{index}]"))
        return mentions
    if not isinstance(value, dict):
        return mentions
    if value.get("entity_name") or value.get("target_entity"):
        mention = _mention_from_mapping(value, path, default_type=normalize_entity_type(value.get("entity_type"), "world"))
        if mention:
            mentions.append(mention)
    for key, item in value.items():
        if key in CHARACTER_CONTAINERS or key in WORLD_CONTAINERS:
            continue
        child_path = f"{path}.{key}" if path else str(key)
        mentions.extend(_explicit_entity_mentions(item, child_path))
    return mentions


def _dedupe_mentions(mentions: list[EntityMention]) -> list[EntityMention]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[EntityMention] = []
    for mention in mentions:
        key = (mention.entity_type, normalize_entity_alias(mention.mention), mention.source_path)
        if not key[1] or key in seen:
            continue
        seen.add(key)
        deduped.append(mention)
    return deduped


def _aliases_from_mapping(value: dict[str, Any]) -> tuple[str, ...]:
    aliases: list[str] = []
    for key in ALIAS_KEYS:
        item = value.get(key)
        if isinstance(item, list):
            aliases.extend(str(part).strip() for part in item if str(part).strip())
        elif isinstance(item, str) and item.strip():
            aliases.extend(part.strip() for part in re.split(r"[,;/\u3001\uff0c]+", item) if part.strip())
    return tuple(dict.fromkeys(aliases))


def _first_text(value: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
        if isinstance(item, (int, float)) and str(item).strip():
            return str(item).strip()
    return ""


def _world_type_for_container(key: str) -> str:
    mapping = {
        "locations": "location",
        "organizations": "organization",
        "items": "item",
        "concepts": "concept",
    }
    return mapping.get(key, "world")
