from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from novel_app.analysis.entity_resolver import normalize_entity_alias, normalize_entity_type
from novel_app.analysis.schemas_v3 import EntityMentionCandidate
from novel_app.database import Database

MENTION_MIN_CONFIDENCE = 0.55

_QUOTE_PATTERNS = (
    ("quoted_title", re.compile(r"《([^》]{2,40})》")),
    ("quoted_name", re.compile(r"[“「『\"]([^”」』\"\n]{2,32})[”」』\"]")),
)
_PUNCTUATION_RE = re.compile(r"[，。！？、；：,.!?;:\n\r\t]")

# 网文对话/动作模式：用于不依赖种子的 character 识别
# 形如"枫鱼道："、"叶芷笑道："、"老者怒道："、"少女冷声道："
_DIALOGUE_VERBS = (
    "道", "说", "笑道", "怒道", "冷道", "喊道", "低声道", "沉声道", "淡淡道",
    "微笑道", "大笑道", "冷笑道", "叹道", "问道", "答道", "接口道", "接道",
    "续道", "说道", "喝道", "嗤笑道", "嘲讽道", "低喝道", "轻声道", "柔声道",
    "厉声道", "正色道", "皱眉道", "疑惑道", "惊讶道", "好奇道", "喃喃道",
    "自语道", "补充道", "解释道", "反问道", "打趣道", "调侃道", "感叹道",
    "冷哼道", "眯眼道", "眯着眼道", "歪头道", "挠头道", "摊手道", "耸肩道",
    # 补充常见"X声道"模式，避免"冷声道"等被拆成名字+动词
    "冷声道", "大声道", "高声道", "急声道", "颤声道", "怒声道", "朗声道",
    "平淡道", "平静道", "冷漠道", "淡然道", "茫然道", "恍惚道", "迟疑道",
    "犹豫道", "无奈道", "苦笑道", "微笑道", "痴笑道", "怪笑道", "狞笑道",
    "点头道", "摇头道", "抱拳道", "拱手道", "合十道", "敛衽道", "施礼道",
)
# 构建对话模式正则：2-4 个汉字后跟对话动词 + 冒号
# 动词按长度降序排列，确保"笑道"在"道"之前匹配；名字用非贪婪 {2,4}? 避免吞掉动词首字
_DIALOGUE_PATTERN = re.compile(
    r"([\u4e00-\u9fff]{2,4}?)(?:" + "|".join(sorted(_DIALOGUE_VERBS, key=len, reverse=True)) + r")[:：]"
)

# 动作模式：形如"枫鱼看着"、"叶芷转身"、"张三走向"
# 需要句子边界前缀 + 名字尾字否定后顾，避免"枫鱼挠了"+"挠头"这类名字过捕
_ACTION_VERBS = (
    "看着", "转身", "走向", "看向", "望向", "跑向", "冲向", "扑向", "退后",
    "上前", "站起", "坐下", "点头", "摇头", "皱眉", "微笑", "冷笑", "叹息",
    "挥手", "抬手", "伸手", "放手", "握拳", "闭眼", "睁眼", "回头", "抬头",
    "低头", "侧头", "歪头", "挠头", "转头", "回身", "偏头", "侧脸",
    "清了清嗓子", "整理了一下", "拍了拍",
    "拉住", "推开", "扶起", "搀扶", "拥抱", "拍了拍",
)
# 名字尾字不能是常见语法助词/副词，否则是误捕（如"枫鱼挠了"以"了"结尾，"叶芷当即"以"即"结尾，"枫鱼只能"以"能"结尾）
_ACTION_NAME_SUFFIX_BLACKLIST = "了着过的地一就也还是在不没把被让给对向往到从和与及或刚即又再便才正已遂乃该本此其某能别"
_ACTION_PATTERN = re.compile(
    r"(?:^|[。！？\n\r“”「『（,，；、\s])([\u4e00-\u9fff]{2,4}?)(?<![" + _ACTION_NAME_SUFFIX_BLACKLIST + r"])(?:" + "|".join(sorted(_ACTION_VERBS, key=len, reverse=True)) + r")"
)

# 否定前缀：这些词后跟对话/动作动词时不是人名
_NEGATIVE_PREFIXES = {
    "然后", "于是", "突然", "忽然", "随即", "随后", "马上", "立刻", "顿时",
    "这时", "那是", "这是", "他们", "她们", "它们", "我们", "你们", "大家",
    "众人", "有人", "那人", "此人", "对方", "一人", "两人", "几人", "众人",
    "少年", "少女", "老者", "中年", "青年", "男子", "女子", "书生", "和尚",
    "道士", "掌柜", "店小二", "管家", "护卫", "侍女", "丫鬟", "下人", "仆人",
    # 常见非人名短语
    "一边", "一下", "一阵", "一些", "一点", "不由", "不能", "不会", "不要",
    "轻轻", "顺便", "两个人", "你们都", "大家都", "大家都别", "只见", "正是", "好像",
    "似乎", "或许", "也许", "应该", "本来", "其实", "毕竟", "而且", "但是",
    # 名字+副词组合（误捕）
    "枫鱼只能", "枫鱼刚", "枫鱼当即", "叶芷当即",
}
_SUFFIX_RE = re.compile(
    r"[\u4e00-\u9fff]{1,12}(?:"
    r"宗门|门派|宗|派|阁|楼|宫|城|国|谷|山|院|司|会|盟|族|军|卫|队|殿|府|塔|"
    r"秘境|洞天|世界|大陆|界|域|"
    r"灵根|境界|体系|规则|功法|剑法|心法|法诀|功|法|诀|"
    r"剑|刀|珠|鼎|镜|令|印|阵|符|丹"
    r")"
)
_TRIM_PREFIXES = (
    "主角获得",
    "主角使用",
    "众人进入",
    "他们进入",
    "她们进入",
    "他进入",
    "她进入",
    "随后获得",
    "随后使用",
    "进入",
    "拜入",
    "加入",
    "来到",
    "来自",
    "前往",
    "抵达",
    "攻打",
    "创建",
    "建立",
    "发现",
    "获得",
    "使用",
    "祭出",
    "修炼",
    "参悟",
)


@dataclass(frozen=True)
class MentionSeed:
    text: str
    entity_type: str
    source_rule: str
    confidence: float
    metadata: dict[str, Any]


class MentionExtractor:
    def __init__(self, seeds: Iterable[MentionSeed] | None = None, *, min_confidence: float = MENTION_MIN_CONFIDENCE) -> None:
        self.seeds = tuple(seed for seed in (seeds or ()) if normalize_entity_alias(seed.text))
        self.min_confidence = max(0.0, min(1.0, float(min_confidence)))
        self._llm_extractor: LLMentionExtractor | None = None

    def enable_llm(self, llm_extractor: LLMentionExtractor) -> None:
        """启用 LLM 增强抽取。传入 LLMentionExtractor 实例。"""
        self._llm_extractor = llm_extractor

    @classmethod
    def from_database(cls, database: Database, book_id: int, *, min_confidence: float = MENTION_MIN_CONFIDENCE) -> MentionExtractor:
        seeds: list[MentionSeed] = []
        for character in database.list_characters(int(book_id)):
            name = str(character["name"] or "").strip()
            if name:
                seeds.append(
                    MentionSeed(
                        text=name,
                        entity_type="character",
                        source_rule="formal_character",
                        confidence=0.95,
                        metadata={"source_table": "characters", "source_id": int(character["id"])},
                    )
                )
        for entry in database.list_world_entries(int(book_id)):
            entry_id = int(entry.get("id") or 0)
            if entry_id <= 0:
                continue
            name = str(entry.get("name") or "").strip()
            if name:
                seeds.append(
                    MentionSeed(
                        text=name,
                        entity_type=_world_category_type(str(entry.get("category") or "")),
                        source_rule="formal_world_entry",
                        confidence=0.9,
                        metadata={"source_table": "world_entries", "source_id": entry_id},
                    )
                )
        return cls(seeds, min_confidence=min_confidence)

    def extract_from_blocks(
        self,
        *,
        book_id: int,
        run_id: int,
        blocks: Iterable[Any],
    ) -> list[EntityMentionCandidate]:
        by_key: dict[tuple[str, int, int, str, str], EntityMentionCandidate] = {}
        for block in blocks:
            block_data = _block_dict(block)
            text = str(block_data.get("text") or "")
            if not text:
                continue
            for candidate in self._seed_mentions(book_id, run_id, block_data, text):
                self._keep_best(by_key, candidate)
            for candidate in self._quoted_mentions(book_id, run_id, block_data, text):
                self._keep_best(by_key, candidate)
            for candidate in self._suffix_mentions(book_id, run_id, block_data, text):
                self._keep_best(by_key, candidate)
            # 不依赖种子的 character 识别：对话/动作模式
            for candidate in self._dialogue_mentions(book_id, run_id, block_data, text):
                self._keep_best(by_key, candidate)

        # LLM 增强抽取：对规则未覆盖的 block 调用 LLM 补充
        if self._llm_extractor is not None:
            llm_candidates = self._llm_extractor.extract(
                book_id=book_id,
                run_id=run_id,
                blocks=list(blocks),
                existing_candidates=dict(by_key),
            )
            for candidate in llm_candidates:
                self._keep_best(by_key, candidate)

        return sorted(by_key.values(), key=lambda item: (item.chapter_id or 0, item.char_start, item.char_end, item.normalized_text))

    def _seed_mentions(
        self,
        book_id: int,
        run_id: int,
        block: dict[str, Any],
        text: str,
    ) -> Iterable[EntityMentionCandidate]:
        for seed in self.seeds:
            if seed.confidence < self.min_confidence:
                continue
            for match in re.finditer(re.escape(seed.text), text, flags=re.IGNORECASE):
                yield self._candidate(
                    book_id=book_id,
                    run_id=run_id,
                    block=block,
                    text=text,
                    local_start=match.start(),
                    local_end=match.end(),
                    entity_type=seed.entity_type,
                    confidence=seed.confidence,
                    source_rule=seed.source_rule,
                    metadata=seed.metadata,
                )

    def _quoted_mentions(
        self,
        book_id: int,
        run_id: int,
        block: dict[str, Any],
        text: str,
    ) -> Iterable[EntityMentionCandidate]:
        for source_rule, pattern in _QUOTE_PATTERNS:
            for match in pattern.finditer(text):
                value = str(match.group(1) or "").strip()
                if not _looks_like_entity_name(value):
                    continue
                confidence = 0.72 if source_rule == "quoted_title" else 0.62
                if confidence < self.min_confidence:
                    continue
                yield self._candidate(
                    book_id=book_id,
                    run_id=run_id,
                    block=block,
                    text=text,
                    local_start=match.start(1),
                    local_end=match.end(1),
                    entity_type="concept",
                    confidence=confidence,
                    source_rule=source_rule,
                    metadata={},
                )

    def _suffix_mentions(
        self,
        book_id: int,
        run_id: int,
        block: dict[str, Any],
        text: str,
    ) -> Iterable[EntityMentionCandidate]:
        for match in _SUFFIX_RE.finditer(text):
            value, offset = _clean_suffix_value(match.group(0))
            if not _looks_like_entity_name(value):
                continue
            confidence = 0.58
            if confidence < self.min_confidence:
                continue
            local_start = match.start() + offset
            local_end = local_start + len(value)
            yield self._candidate(
                book_id=book_id,
                run_id=run_id,
                block=block,
                text=text,
                local_start=local_start,
                local_end=local_end,
                entity_type=_suffix_type(value),
                confidence=confidence,
                source_rule="suffix_pattern",
                metadata={},
            )

    def _dialogue_mentions(
        self,
        book_id: int,
        run_id: int,
        block: dict[str, Any],
        text: str,
    ) -> Iterable[EntityMentionCandidate]:
        """基于网文对话/动作模式识别 character，不依赖种子。

        匹配形如"枫鱼道："、"叶芷笑道："、"张三看着"的模式。
        这些模式在网文中高频出现，可高效识别人物名字。
        """
        for match in _DIALOGUE_PATTERN.finditer(text):
            name = str(match.group(1) or "").strip()
            if not _looks_like_character_name(name):
                continue
            confidence = 0.65  # 对话模式置信度高于 suffix
            if confidence < self.min_confidence:
                continue
            local_start = match.start(1)
            local_end = match.end(1)
            yield self._candidate(
                book_id=book_id,
                run_id=run_id,
                block=block,
                text=text,
                local_start=local_start,
                local_end=local_end,
                entity_type="character",
                confidence=confidence,
                source_rule="dialogue_pattern",
                metadata={},
            )
        for match in _ACTION_PATTERN.finditer(text):
            name = str(match.group(1) or "").strip()
            if not _looks_like_character_name(name):
                continue
            confidence = 0.6  # 动作模式置信度略低
            if confidence < self.min_confidence:
                continue
            local_start = match.start(1)
            local_end = match.end(1)
            yield self._candidate(
                book_id=book_id,
                run_id=run_id,
                block=block,
                text=text,
                local_start=local_start,
                local_end=local_end,
                entity_type="character",
                confidence=confidence,
                source_rule="action_pattern",
                metadata={},
            )

    def _candidate(
        self,
        *,
        book_id: int,
        run_id: int,
        block: dict[str, Any],
        text: str,
        local_start: int,
        local_end: int,
        entity_type: str,
        confidence: float,
        source_rule: str,
        metadata: dict[str, Any],
    ) -> EntityMentionCandidate:
        quote_text = text[local_start:local_end]
        block_start = _int(block.get("char_start"), 0)
        chapter_id = _int_or_none(block.get("chapter_id"))
        return EntityMentionCandidate.create(
            book_id=book_id,
            run_id=run_id,
            entity_type=normalize_entity_type(entity_type, "concept"),
            normalized_text=normalize_entity_alias(quote_text),
            quote_text=quote_text,
            chapter_id=chapter_id,
            block_uid=str(block.get("block_uid") or ""),
            char_start=block_start + int(local_start),
            char_end=block_start + int(local_end),
            confidence=confidence,
            source_rule=source_rule,
            metadata={
                **metadata,
                "block_local_start": int(local_start),
                "block_local_end": int(local_end),
            },
        )

    @staticmethod
    def _keep_best(
        by_key: dict[tuple[str, int, int, str, str], EntityMentionCandidate],
        candidate: EntityMentionCandidate,
    ) -> None:
        if not candidate.quote_text or candidate.confidence < MENTION_MIN_CONFIDENCE:
            return
        key = (
            candidate.block_uid,
            candidate.char_start,
            candidate.char_end,
            candidate.entity_type,
            candidate.normalized_text,
        )
        existing = by_key.get(key)
        if existing is None or candidate.confidence > existing.confidence:
            by_key[key] = candidate


def _block_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    result = dict(value)
    if "chapter_id" not in result:
        chapter_ids = result.get("chapter_ids")
        if isinstance(chapter_ids, list) and chapter_ids:
            result["chapter_id"] = chapter_ids[0]
    return result


def _world_category_type(category: str) -> str:
    text = str(category or "")
    if any(key in text for key in ("人物", "角色")):
        return "character"
    if any(key in text for key in ("势力", "组织", "宗门", "门派", "家族")):
        return "organization"
    if any(key in text for key in ("地点", "地理", "城市", "秘境", "地图")):
        return "location"
    if any(key in text for key in ("物品", "法宝", "道具", "装备")):
        return "item"
    return "concept"


def _suffix_type(value: str) -> str:
    if value.endswith(("宗门", "门派", "宗", "派", "阁", "楼", "宫", "院", "司", "会", "盟", "族", "军", "卫", "队")):
        return "organization"
    if value.endswith(("城", "国", "谷", "山", "殿", "府", "塔", "秘境", "洞天", "世界", "大陆", "界", "域")):
        return "location"
    if value.endswith(("剑", "刀", "珠", "鼎", "镜", "令", "印", "阵", "符", "丹")):
        return "item"
    return "concept"


def _clean_suffix_value(value: str) -> tuple[str, int]:
    clean = str(value or "").strip()
    offset = 0
    changed = True
    while changed:
        changed = False
        for prefix in _TRIM_PREFIXES:
            if clean.startswith(prefix) and len(clean) > len(prefix) + 1:
                clean = clean[len(prefix):]
                offset += len(prefix)
                changed = True
                break
    return clean, offset


def _looks_like_entity_name(value: str) -> bool:
    text = str(value or "").strip()
    if len(text) < 2 or len(text) > 40:
        return False
    if _PUNCTUATION_RE.search(text):
        return False
    if normalize_entity_alias(text) in {"他说", "她说", "他们说", "这一切", "不知道", "为什么"}:
        return False
    return bool(normalize_entity_alias(text))


def _looks_like_character_name(value: str) -> bool:
    """对话/动作模式提取的候选名校验，比 _looks_like_entity_name 更严格。

    过滤泛称（少年/少女/老者等）、否定前缀、过短/过长名字。
    """
    text = str(value or "").strip()
    if len(text) < 2 or len(text) > 4:
        return False
    if _PUNCTUATION_RE.search(text):
        return False
    normalized = normalize_entity_alias(text)
    if not normalized:
        return False
    # 过滤泛称和否定前缀
    if normalized in _NEGATIVE_PREFIXES:
        return False
    if normalized in {"他说", "她说", "他们说", "这一切", "不知道", "为什么"}:
        return False
    # 过滤纯方位词/时间词
    if normalized in {"前面", "后面", "左边", "右边", "上面", "下面", "今天", "明天", "昨天"}:
        return False
    return True


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class LLMentionExtractor:
    """LLM 增强实体提及抽取的抽象基类。

    子类需要实现 `extract()` 方法，调用 LLM 对文本块进行提及抽取，
    返回 EntityMentionCandidate 列表。LLM 抽取结果只进候选池，
    不直接写入正式层。

    使用方式：
        extractor = MentionExtractor.from_database(db, book_id)
        extractor.enable_llm(MyLLMentionExtractor(ai_service, llm_cache))
        mentions = extractor.extract_from_blocks(...)
    """

    def extract(
        self,
        *,
        book_id: int,
        run_id: int,
        blocks: list[Any],
        existing_candidates: dict[tuple[str, int, int, str, str], EntityMentionCandidate],
    ) -> list[EntityMentionCandidate]:
        """调用 LLM 对 blocks 进行提及抽取，返回新的候选列表。

        默认实现返回空列表（不调用 LLM）。子类应重写此方法。
        """
        return []
