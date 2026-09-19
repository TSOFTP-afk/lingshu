"""AI 分析提供器 — 封装 OpenAI 兼容 API 调用，为 V3 各阶段提供 AI 能力。

当 use_ai=True 时，AIAnalysisProvider 替代 V3 流水线中 M2/M3/M4 阶段的规则提取：
- extract_mentions: 替代 MentionExtractor 的正则规则
- resolve_coreference: 替代 CoreferenceResolver 的规则聚类
- extract_facts: 替代 FactExtractor 的句法模式
- check_consistency: LLM 一致性判定

V3 分析链路全环节 AI 接入扩展方法：
- generate_card_content: 用 LLM 生成卡片（角色/世界/书籍）结构化内容，替代字符串机械拼接
- score_memory_importance: 用 LLM 对原子事实进行记忆重要性评分（hot/warm/cold/archive）
- compress_memory: 用 LLM 生成压缩后的记忆摘要文本
- generate_probe_questions: 用 LLM 根据上下文生成有针对性的探针问题
- semantic_chunk: 用 LLM 辅助语义边界判定，调整规则分块的候选边界

所有调用通过 LLMCache 缓存，命中缓存时跳过远程调用。
AI 调用失败时返回空列表，由调用方（pipeline_v3）回退到规则模式。
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from novel_app.analysis.entity_resolver import normalize_entity_alias, normalize_entity_type, stable_entity_uid
from novel_app.analysis.llm_cache import LLMCache
from novel_app.analysis.prompts import load_prompt
from novel_app.analysis.schemas_v3 import (
    ANALYSIS_V3_SCHEMA_VERSION,
    AtomicFact,
    EntityMentionCandidate,
    ResolvedEntityCandidate,
)
from novel_app.json_utils import (
    balance_json_like_text,
    extract_json_object,
    json_candidate_text,
    loads_json_payload,
    repair_json_like_text,
)

logger = logging.getLogger(__name__)


# V3 各阶段系统提示词已外置到 novel_app/analysis/prompts/，由 load_prompt 读取文件原文（内容与外置前逐字节一致）。
SYSTEM_PROMPT_MENTION = load_prompt("entity_mention_extraction")
SYSTEM_PROMPT_COREFERENCE = load_prompt("entity_coreference_resolution")
SYSTEM_PROMPT_FACT = load_prompt("atomic_fact_extraction")
SYSTEM_PROMPT_CARD_CONTENT = load_prompt("card_content_generation")
SYSTEM_PROMPT_MEMORY_SCORE = load_prompt("memory_importance_scoring")
SYSTEM_PROMPT_MEMORY_COMPRESS = load_prompt("memory_compression")
SYSTEM_PROMPT_PROBE_QUESTION = load_prompt("probe_question_generation")
SYSTEM_PROMPT_SEMANTIC_CHUNK = load_prompt("semantic_chunk_adjustment")
SYSTEM_PROMPT_SEMANTIC_CHUNK_V2 = load_prompt("semantic_chunk_boundary_v2")
SYSTEM_PROMPT_MENTION_SCREEN = load_prompt("mention_marker_screening")
SYSTEM_PROMPT_MENTION_REVIEW = load_prompt("suspicious_mention_review")


FACT_TYPES = {"event", "relation", "state", "foreshadowing", "world_rule"}
CARD_TYPES = {"v3_character", "v3_world", "v3_book_summary"}
CARD_REQUIRED_FIELDS: dict[str, set[str]] = {
    "v3_character": {"title", "profile_text", "role", "summary"},
    "v3_world": {"title", "content_text", "category", "summary"},
    "v3_book_summary": {"title", "outline_text", "world_text", "summary"},
}
MEMORY_LEVELS = {"hot", "warm", "cold", "archive"}
PROBE_TYPES = {"foreshadowing_recovery", "entity_state", "world_rule", "relationship_evolution"}
AI_TEXT_WINDOW_CHARS = 8000
AI_TEXT_WINDOW_OVERLAP = 300
# AI 调用总尝试次数 = 1（首次）+ 3（重试）。可通过环境变量覆盖。
# 重试时按错误类型应用退避：限流(429)指数退避(2/4/8s)，超时线性退避(1/2/3s)，其他 0.5s。
AI_MAX_ATTEMPTS = max(1, int(os.environ.get("LINGSHU_AI_MAX_ATTEMPTS", "4") or 4))
# 限流退避基数（秒），指数退避: base * 2^(retry_index-1) → 2s, 4s, 8s
AI_RATE_LIMIT_BACKOFF_BASE = float(os.environ.get("LINGSHU_AI_RATE_LIMIT_BACKOFF_BASE", "2.0") or 2.0)
# 超时退避基数（秒），线性退避: base * retry_index → 1s, 2s, 3s
AI_TIMEOUT_BACKOFF_BASE = float(os.environ.get("LINGSHU_AI_TIMEOUT_BACKOFF_BASE", "1.0") or 1.0)
# 其他错误退避（秒），固定值
AI_OTHER_BACKOFF = float(os.environ.get("LINGSHU_AI_OTHER_BACKOFF", "0.5") or 0.5)
# 记忆评分分批大小：每批事实数。126 条事实一次性发送会导致 AI 输出超过 max_tokens 截断，
# 分批后每批输出约 30 条评分（~3KB JSON），远低于 16384 token 上限。
# 可通过环境变量调整。
MEMORY_SCORE_BATCH_SIZE = max(5, int(os.environ.get("LINGSHU_AI_MEMORY_SCORE_BATCH_SIZE", "30") or 30))
SENTENCE_BOUNDARIES = "。！？.!?\n"
# 共指消解 AI 调用内部 deadline（秒）。超时后停止剩余批次，返回已收集结果，
# 由调用方 fallback 到规则引擎。设为 300s（小于 pipeline_v3 的 STAGE_TIMEOUT_SECONDS=600），
# 给规则引擎留出足够时间完成。
AI_COREFERENCE_DEADLINE_SECONDS = int(os.environ.get("LINGSHU_ANALYSIS_V3_AI_COREFERENCE_DEADLINE_SECONDS", "300") or 300)
# 共指消解批次动态并发管理（AIMD 拥塞控制 + 慢启动）。
# - 物理上限 500：ThreadPoolExecutor 的 max_workers，与 AI_MAX_WORKERS 对齐
# - 初始 5：保守起步，避免新用户一上来就打爆 API
# - 慢启动阶段（current < slow_start_threshold）：成功时翻倍，快速爬坡
# - 拥塞避免阶段：成功时加性增加（+1），平稳接近上限
# - 限流(429)时乘性减少（×0.5），连接错误时乘性减少（×0.7），普通失败时小幅削减（-1）
# - 乘性减少后重新进入慢启动（类 TCP），并下调 ssthresh 以快速恢复
# 可通过环境变量调整：起始值 LINGSHU_AI_COREFERENCE_CONCURRENCY_INITIAL、
# 上限 LINGSHU_AI_COREFERENCE_CONCURRENCY_MAX
AI_COREFERENCE_CONCURRENCY_MAX = max(1, int(os.environ.get("LINGSHU_AI_COREFERENCE_CONCURRENCY_MAX", "2000") or 2000))
AI_COREFERENCE_CONCURRENCY_INITIAL = max(1, min(
    int(os.environ.get("LINGSHU_AI_COREFERENCE_CONCURRENCY_INITIAL", "64") or 64),
    AI_COREFERENCE_CONCURRENCY_MAX,
))
BURST_SUBMIT_CAP = int(os.environ.get("LINGSHU_AI_BURST_SUBMIT_CAP", "8") or 8)


@dataclass(frozen=True)
class AITextWindow:
    index: int
    start: int
    end: int
    text: str


class AIMDConcurrencyController:
    """AIMD（加性增/乘性减）+ 慢启动动态并发控制器，类 TCP 拥塞控制。

    在传统 AIMD 基础上引入 TCP 慢启动机制，解决高上限（500）下爬坡过慢的问题：
    - 慢启动阶段（current < ssthresh）：成功时翻倍，5→10→20→40… 快速逼近带宽
    - 拥塞避免阶段（current >= ssthresh）：成功时加性增加（+1），平稳接近 maximum
    - 限流(429)：乘性减少（×0.5），ssthresh 下调为 current/2，重新进入慢启动
    - 连接错误（Remote end closed 等）：乘性减少（×0.7），同样重进慢启动
    - 普通失败：小幅削减（-1），不改变阶段

    相比旧版（纯 +1 爬坡，5→500 需 495 次成功），慢启动可在 ~6 次成功内
    从 5 爬到 320，大幅缩短冷启动阶段；乘性减少后的慢启动恢复也更快。

    线程安全：所有调整通过 _lock 保护，可在多线程环境下使用。
    """

    def __init__(
        self,
        *,
        initial: int = AI_COREFERENCE_CONCURRENCY_INITIAL,
        minimum: int = 1,
        maximum: int = AI_COREFERENCE_CONCURRENCY_MAX,
        slow_start_threshold: int | None = None,
    ) -> None:
        self._current = max(minimum, min(initial, maximum))
        self._minimum = minimum
        self._maximum = maximum
        # 慢启动阈值 ssthresh：默认 maximum/8 且不超过 32，低于此值翻倍增长。
        # 失败后下调到 current/2（类 TCP），使恢复过程更平稳。
        if slow_start_threshold is None:
            slow_start_threshold = max(initial, min(maximum // 8, 32))
        self._ssthresh = max(minimum, min(slow_start_threshold, maximum))
        self._in_slow_start = self._current < self._ssthresh
        self._lock = threading.Lock()
        self._success_count = 0
        self._failure_count = 0
        self._rate_limit_count = 0
        self._connection_error_count = 0
        self._peak = self._current
        # 延迟感知统计
        self._latency_samples: deque[float] = deque(maxlen=20)
        self._latency_baseline: float | None = None
        self._latency_degrade_count = 0
        # 退化冷却：上次退化时间，防止同一批样本反复触发退化导致死循环
        self._last_degrade_time: float = 0.0
        self._degrade_cooldown: float = 30.0

    def current(self) -> int:
        """返回当前允许的并发数。"""
        with self._lock:
            return self._current

    def on_success(self) -> int:
        """批次成功后调用：慢启动阶段翻倍，拥塞避免阶段 +1。"""
        with self._lock:
            self._success_count += 1
            if self._current < self._maximum:
                if self._in_slow_start and self._current < self._ssthresh:
                    # 慢启动：翻倍爬坡（5→10→20→40…）
                    self._current = min(self._maximum, self._current * 2)
                    if self._current >= self._ssthresh:
                        # 越过 ssthresh，切换到拥塞避免
                        self._in_slow_start = False
                else:
                    # 拥塞避免：加性增加（+1）
                    self._current = min(self._maximum, self._current + 1)
                if self._current > self._peak:
                    self._peak = self._current
            return self._current

    def on_failure(self, *, rate_limited: bool = False, connection_error: bool = False) -> int:
        """批次失败后调用：按严重程度乘性减少，并重新进入慢启动。

        - 限流(429)：×0.5（大幅削减）
        - 连接错误：×0.7（中度削减，避免持续打爆连接）
        - 普通失败：-1（小幅削减）
        乘性减少后下调 ssthresh=current/2 并重进慢启动，加速后续恢复。
        """
        with self._lock:
            self._failure_count += 1
            if rate_limited:
                self._rate_limit_count += 1
                new_val = max(self._minimum, self._current // 2)
            elif connection_error:
                self._connection_error_count += 1
                new_val = max(self._minimum, int(self._current * 0.7))
            else:
                # 普通失败仅小幅削减，不重进慢启动（避免抖动）
                self._current = max(self._minimum, self._current - 1)
                return self._current
            # 乘性减少：下调 ssthresh 并重进慢启动（类 TCP 快速恢复）
            self._ssthresh = max(self._minimum, new_val // 2)
            self._in_slow_start = True
            self._current = new_val
            return self._current

    def record_latency(self, duration: float) -> None:
        """记录一次成功调用的耗时，用于延迟感知。

        前 10 次采样建立基线（中位值），后续采样用于退化检测。
        """
        with self._lock:
            self._latency_samples.append(duration)
            if self._latency_baseline is None and len(self._latency_samples) >= 10:
                sorted_samples = sorted(self._latency_samples)
                mid = len(sorted_samples) // 2
                if len(sorted_samples) % 2 == 0:
                    self._latency_baseline = (sorted_samples[mid - 1] + sorted_samples[mid]) / 2.0
                else:
                    self._latency_baseline = sorted_samples[mid]

    def check_latency_degrade(self) -> bool:
        """检查延迟是否显著恶化（中位延迟 >= 基线 × 3）。

        仅在基线已建立（>=10 次采样）且当前窗口有足够样本（>=10）时检测。
        退化冷却期内（默认 30s）不重复触发，避免同一批样本反复退化导致死循环。
        阈值 ×3（较 ×2 更宽松），避免 API 自然抖动误判为退化导致并发反复回退。
        """
        with self._lock:
            if self._latency_baseline is None or len(self._latency_samples) < 10:
                return False
            # 冷却期检查：上次退化后需等待 cooldown 秒才再次检测
            now = time.monotonic()
            if self._last_degrade_time > 0 and (now - self._last_degrade_time) < self._degrade_cooldown:
                return False
            sorted_samples = sorted(self._latency_samples)
            mid = len(sorted_samples) // 2
            if len(sorted_samples) % 2 == 0:
                current_median = (sorted_samples[mid - 1] + sorted_samples[mid]) / 2.0
            else:
                current_median = sorted_samples[mid]
            return current_median >= self._latency_baseline * 3.0

    def on_latency_degrade(self) -> int:
        """延迟恶化时调用：×0.7 回退 + 下调 ssthresh + 重进慢启动。

        逻辑与 on_failure(connection_error=True) 一致，但单独计数。
        退化后清空延迟样本并重置基线，让新并发水平下重新建立基线，避免死循环。
        """
        with self._lock:
            self._latency_degrade_count += 1
            new_val = max(self._minimum, int(self._current * 0.7))
            self._ssthresh = max(self._minimum, new_val // 2)
            self._in_slow_start = True
            self._current = new_val
            # 清空样本 + 重置基线 + 设置冷却时间，防止同一批样本反复触发退化
            self._latency_samples.clear()
            self._latency_baseline = None
            self._last_degrade_time = time.monotonic()
            return self._current

    def stats(self) -> dict[str, int]:
        """返回统计信息（用于日志）。"""
        with self._lock:
            return {
                "current": self._current,
                "peak": self._peak,
                "minimum": self._minimum,
                "maximum": self._maximum,
                "ssthresh": self._ssthresh,
                "slow_start": 1 if self._in_slow_start else 0,
                "success": self._success_count,
                "failure": self._failure_count,
                "rate_limited": self._rate_limit_count,
                "connection_error": self._connection_error_count,
                "latency_baseline": self._latency_baseline,
                "latency_median": (sorted(self._latency_samples)[len(self._latency_samples)//2] if self._latency_samples else None),
                "latency_degrade_count": self._latency_degrade_count,
            }


def _is_rate_limit_error(exc: Exception) -> bool:
    """检测异常是否为 API 限流（429）或可视为限流的错误。

    用于 AIMD 控制器决定是否进行乘性减少（×0.5）。
    检测范围：
    - HTTPError 403/429（OpenAI 兼容 API 常见限流状态码）
    - 异常消息中包含 rate limit / quota / too many requests
    - urllib.error.HTTPError 的 code 属性
    """
    # 检查异常对象上的 code 属性（urllib.error.HTTPError）
    code = getattr(exc, "code", None)
    if code in (403, 429):
        return True
    # 检查异常链中是否有 HTTPError
    cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    if cause is not None:
        cause_code = getattr(cause, "code", None)
        if cause_code in (403, 429):
            return True
    # 检查异常消息
    msg = str(exc).lower()
    return any(kw in msg for kw in ("rate limit", "rate_limit", "quota", "too many requests", "429", "403"))


def _is_connection_error(exc: Exception) -> bool:
    """检测异常是否为连接层错误（远端关闭/重置/中断），视为过载信号。

    用于 AIMD 控制器决定是否进行中度乘性减少（×0.7）。
    与限流（×0.5）区分：连接错误通常是服务端在高并发下主动断开，
    削减力度略低于限流但仍需乘性回退，避免持续打爆连接。
    检测范围：
    - ConnectionError 及其子类（RemoteDisconnected / ConnectionResetError 等）
    - 异常链中的连接错误
    - 消息关键词：remote end closed / connection closed / connection reset /
      connection aborted / connection refused / broken pipe /
      chunked encoding / incomplete read
    """
    if isinstance(exc, ConnectionError):
        return True
    cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    if cause is not None and isinstance(cause, ConnectionError):
        return True
    msg = str(exc).lower()
    return any(kw in msg for kw in (
        "remote end closed", "connection closed", "connection reset",
        "connection aborted", "connection refused", "broken pipe",
        "chunked encoding", "incomplete read",
    ))


def iter_ai_text_windows(
    text: str,
    *,
    window_chars: int = AI_TEXT_WINDOW_CHARS,
    overlap: int = AI_TEXT_WINDOW_OVERLAP,
) -> list[AITextWindow]:
    clean_text = str(text or "")
    if not clean_text:
        return []
    size = max(1, int(window_chars))
    safe_overlap = max(0, min(int(overlap), size - 1))
    windows: list[AITextWindow] = []
    cursor = 0
    text_len = len(clean_text)
    while cursor < text_len:
        hard_end = min(text_len, cursor + size)
        end = hard_end
        if hard_end < text_len:
            min_soft_end = cursor + max(1, int(size * 0.6))
            soft_end = -1
            for boundary in SENTENCE_BOUNDARIES:
                pos = clean_text.rfind(boundary, cursor, hard_end)
                if pos >= min_soft_end:
                    soft_end = max(soft_end, pos + len(boundary))
            if soft_end > cursor:
                end = soft_end
        if end <= cursor:
            end = hard_end
        windows.append(AITextWindow(index=len(windows), start=cursor, end=end, text=clean_text[cursor:end]))
        if end >= text_len:
            break
        cursor = max(cursor + 1, end - safe_overlap)
    return windows


class AIAnalysisProvider:
    """封装 OpenAI 兼容 API，为 V3 流水线 M2/M3/M4 阶段提供 AI 提取能力。

    所有远程调用经 LLMCache 缓存；单次调用失败时记录到 self.errors 并跳过，
    不在内部回退到规则模式（由调用方决定回退策略）。
    """

    PROMPT_VERSION = "ai_provider_v1"
    SCHEMA_VERSION = "analysis_v3_m4"

    MENTION_BATCH_SIZE = int(os.environ.get("LINGSHU_ANALYSIS_V3_AI_COREFERENCE_BATCH_SIZE", "25") or 25)
    MEMORY_SCORE_BATCH_SIZE = MEMORY_SCORE_BATCH_SIZE
    TEXT_SLICE_LIMIT = 2000
    AI_TEXT_WINDOW_CHARS = AI_TEXT_WINDOW_CHARS
    AI_TEXT_WINDOW_OVERLAP = AI_TEXT_WINDOW_OVERLAP
    AI_MAX_ATTEMPTS = AI_MAX_ATTEMPTS
    AI_COREFERENCE_DEADLINE_SECONDS = AI_COREFERENCE_DEADLINE_SECONDS
    AI_COREFERENCE_CONCURRENCY_MAX = AI_COREFERENCE_CONCURRENCY_MAX
    AI_COREFERENCE_CONCURRENCY_INITIAL = AI_COREFERENCE_CONCURRENCY_INITIAL

    # 分级超时表：基于输入文本字符数（window.text / context / user_prompt 长度）
    # 按章节长度分级，避免短文本等待过久、长文本超时失败
    # 格式: (文本长度上限, 超时秒数)
    AI_TIMEOUT_TIERS: list[tuple[int, int]] = [
        (2000, 30),       # < 2000 字: 30 秒
        (4000, 60),       # 2000-4000 字: 60 秒
        (8000, 120),      # 4000-8000 字: 120 秒
        (15000, 120),     # 8000-15000 字: 120 秒
        (999999999, 120), # >= 15000 字: 120 秒
    ]

    @classmethod
    def _compute_timeout_for_text(cls, text_len: int) -> int:
        """根据输入文本字符数计算合适的 AI 调用超时秒数。

        分级策略避免短文本等待过久、长文本超时失败。
        """
        for threshold, timeout in cls.AI_TIMEOUT_TIERS:
            if text_len < threshold:
                return timeout
        return cls.AI_TIMEOUT_TIERS[-1][1]

    def __init__(
        self,
        ai_service: Any,
        llm_cache: LLMCache,
        *,
        prompt_version: str | None = None,
        database: Any = None,
    ) -> None:
        self.ai_service = ai_service
        self.llm_cache = llm_cache
        self.prompt_version = prompt_version or self.PROMPT_VERSION
        self.cache_hits = 0
        self.call_count = 0
        self.errors: list[dict[str, Any]] = []
        self._stats_lock = threading.Lock()
        self.retry_count = 0
        self.repaired_json_count = 0
        self.error_type_counts: dict[str, int] = {}
        self._database = database
        self._known_entity_seeds_cache: dict[int, list[str]] = {}

    def _load_known_entity_seeds(self, book_id: int) -> list[str]:
        """从 database 读取已知 character / world_entry 名称作为实体种子。

        每本书只读一次并缓存到 self._known_entity_seeds_cache。
        失败时返回空列表，不抛异常（不阻断主流程）。
        """
        if self._database is None:
            return []
        seeds: list[str] = []
        seen: set[str] = set()
        try:
            for row in self._database.list_characters(book_id):
                name = str(row.get("name") or "").strip() if isinstance(row, dict) else str(getattr(row, "name", "") or "").strip()
                if name and name not in seen:
                    seen.add(name)
                    seeds.append(name)
        except Exception as exc:
            logger.warning("list_characters failed for known entity seeds (book_id=%s): %s", book_id, exc)
        try:
            for row in self._database.list_world_entries(book_id):
                name = str(row.get("name") or "").strip() if isinstance(row, dict) else str(getattr(row, "name", "") or "").strip()
                if name and name not in seen:
                    seen.add(name)
                    seeds.append(name)
        except Exception as exc:
            logger.warning("list_world_entries failed for known entity seeds (book_id=%s): %s", book_id, exc)
        return seeds

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def extract_mentions(
        self,
        blocks: list[dict[str, Any]],
        *,
        book_id: int,
        run_id: int,
        raise_on_error: bool = False,
    ) -> list[EntityMentionCandidate]:
        """对每个语义块单独调用 LLM，抽取实体提及候选。

        AI 返回的 quote_text 通过 text.find 定位绝对字符位置；无法在原文中
        定位的候选会被丢弃。source_rule 标记为 "ai_llm"。

        若构造时传入了 database，则在首次调用时按 book_id 加载已知实体种子
        （character + world_entry 名称），并附加到 user_prompt 以引导 LLM
        优先识别已知实体名称，减少低质量 mention 噪声。
        """
        # 加载已知实体种子（每本书只读一次，缓存到实例属性）
        if book_id not in self._known_entity_seeds_cache:
            try:
                self._known_entity_seeds_cache[book_id] = self._load_known_entity_seeds(book_id)
            except Exception as exc:
                logger.warning("Failed to load known entity seeds (book_id=%s): %s", book_id, exc)
                self._known_entity_seeds_cache[book_id] = []
        known_seeds_hint = ""
        if book_id in self._known_entity_seeds_cache:
            seeds = self._known_entity_seeds_cache[book_id]
            if seeds:
                seeds_text = "、".join(seeds[:50])
                known_seeds_hint = f"\n已知实体（请优先识别这些名称）：{seeds_text}\n"
        results: list[EntityMentionCandidate] = []
        for block in blocks:
            block_uid = str(block.get("block_uid") or "")
            try:
                chapter_id = block.get("chapter_id")
                char_start = int(block.get("char_start") or 0)
                text = str(block.get("text") or "")

                # 从 block 中提取章节标题
                chapter_title = ""
                chapter_refs = block.get("chapter_refs")
                if isinstance(chapter_refs, list) and chapter_refs:
                    chapter_title = str(chapter_refs[0].get("title", ""))

                if not text.strip() or not block_uid:
                    continue
                for window in iter_ai_text_windows(
                    text,
                    window_chars=self.AI_TEXT_WINDOW_CHARS,
                    overlap=self.AI_TEXT_WINDOW_OVERLAP,
                ):
                    input_payload = {
                        "book_id": book_id,
                        "block_uid": block_uid,
                        "window_index": window.index,
                        "window_start": window.start,
                        "window_end": window.end,
                        "text": window.text,
                    }
                    user_prompt = (
                        f"block_uid: {block_uid}\n"
                        f"chapter_id: {chapter_id}\n"
                        f"chapter_title: {chapter_title}\n"
                        f"window_index: {window.index}\n"
                        f"window_start: {window.start}\n"
                        f"window_end: {window.end}\n"
                        f"文本片段：\n{window.text}\n"
                        f"{known_seeds_hint}\n"
                        f"请抽取其中的实体提及。"
                    )
                    output = self._call_llm(
                        stage="ai_mention",
                        input_payload=input_payload,
                        system_prompt=SYSTEM_PROMPT_MENTION,
                        user_prompt=user_prompt,
                        timeout=self._compute_timeout_for_text(len(window.text)),
                    )
                    mentions_data = output.get("mentions")
                    if not isinstance(mentions_data, list):
                        continue
                    for item in mentions_data:
                        candidate = self._parse_mention_item(
                            item,
                            text=window.text,
                            char_start=char_start + window.start,
                            chapter_id=chapter_id,
                            block_uid=block_uid,
                            book_id=book_id,
                            run_id=run_id,
                            metadata={
                                "ai_window_index": window.index,
                                "ai_window_start": window.start,
                                "ai_window_end": window.end,
                                "chapter_title": chapter_title,
                            },
                        )
                        if candidate is not None:
                            results.append(candidate)
            except Exception as exc:
                self._record_error(stage="ai_mention", exc=exc, block_uid=block_uid)
                logger.warning("AI mention extraction failed for block %s: %s", block_uid, exc)
                if raise_on_error:
                    raise
                continue
        return _dedupe_mentions(results)

    def resolve_coreference(
        self,
        mentions: list[dict[str, Any]],
        *,
        book_id: int,
        run_id: int,
    ) -> list[ResolvedEntityCandidate]:
        """调用 LLM 将指代同一实体的提及合并为统一实体。

        mentions 数量较多时分批处理（每批最多 MENTION_BATCH_SIZE 个），
        每批独立调用 LLM。entity_uid 由 stable_entity_uid 生成，
        source_rule 标记为 "ai_llm_coreference"。

        批次通过线程池并发执行，使用 AIMD 动态并发管理：
        - 初始并发 5，慢启动翻倍至 ssthresh 后 +1 加性增加，上限 500
        - 延迟感知：中位延迟 ≥ 基线×2 时 ×0.7 回退；突发提交限制每轮最多 8 个
        - 限流(429)时乘性减少（×0.5），普通失败时小幅削减（-1）
        - 使 50 批 ~25s/批的耗时从 1250s 降至 ~25-100s（视 API 承载能力）
        """
        results: list[ResolvedEntityCandidate] = []
        if not mentions:
            return results

        # 按 entity_type + quote_text 排序，确保同名/子串名的提及落在同一批次
        sorted_mentions = sorted(
            mentions,
            key=lambda m: (
                str(m.get("entity_type") or ""),
                str(m.get("quote_text") or ""),
            ),
        )

        batch_size = self.MENTION_BATCH_SIZE
        deadline_seconds = max(60, int(self.AI_COREFERENCE_DEADLINE_SECONDS))
        max_workers = max(1, int(self.AI_COREFERENCE_CONCURRENCY_MAX))
        start_monotonic = time.monotonic()
        total_batches = (len(sorted_mentions) + batch_size - 1) // batch_size

        # AIMD 动态并发控制器
        controller = AIMDConcurrencyController(
            initial=max(1, int(self.AI_COREFERENCE_CONCURRENCY_INITIAL)),
            minimum=1,
            maximum=max_workers,
        )

        # 预构建所有批次的输入参数（避免在子线程中访问可变状态）
        batch_inputs: list[tuple[int, list[dict[str, Any]], dict[str, Any], str, set[str]]] = []
        for batch_idx in range(0, len(sorted_mentions), batch_size):
            batch = sorted_mentions[batch_idx : batch_idx + batch_size]
            compact = [
                {
                    "mention_uid": str(m.get("mention_uid") or ""),
                    "entity_type": str(m.get("entity_type") or ""),
                    "quote_text": str(m.get("quote_text") or ""),
                    "chapter_id": m.get("chapter_id"),
                    "chapter_title": str(
                        (m.get("metadata") or {}).get("chapter_title", "")
                        or m.get("chapter_title", "")
                    ),
                }
                for m in batch
            ]
            input_payload = {
                "book_id": book_id,
                "mentions_count": len(batch),
                "mentions": compact,
            }
            user_prompt = (
                f"book_id: {book_id}\n"
                f"本批提及数量：{len(batch)}\n"
                f"提及列表（JSON）：\n{json.dumps(compact, ensure_ascii=False)}\n\n"
                f"请将指代同一实体的提及合并，返回实体列表。"
            )
            valid_uids = {str(m.get("mention_uid") or "") for m in batch}
            batch_inputs.append((batch_idx, batch, input_payload, user_prompt, valid_uids))

        def _process_batch(
            batch_idx: int,
            input_payload: dict[str, Any],
            user_prompt: str,
            valid_uids: set[str],
        ) -> tuple[list[ResolvedEntityCandidate], bool, bool, bool]:
            """单个批次的 LLM 调用与解析（线程池工作函数）。

            返回 (candidates, success, rate_limited, connection_error) 用于 AIMD 控制。
            """
            try:
                output = self._call_llm(
                    stage="ai_coreference",
                    input_payload=input_payload,
                    system_prompt=SYSTEM_PROMPT_COREFERENCE,
                    user_prompt=user_prompt,
                    timeout=self._compute_timeout_for_text(len(user_prompt)),
                )
                entities_data = output.get("entities")
                if not isinstance(entities_data, list):
                    return [], True, False, False
                batch_results: list[ResolvedEntityCandidate] = []
                for item in entities_data:
                    candidate = self._parse_entity_item(item, valid_uids, book_id=book_id)
                    if candidate is not None:
                        batch_results.append(candidate)
                return batch_results, True, False, False
            except Exception as exc:
                rate_limited = _is_rate_limit_error(exc)
                connection_error = _is_connection_error(exc)
                self._record_error(stage="ai_coreference", exc=exc, batch_idx=batch_idx)
                logger.warning(
                    "AI coreference failed for batch %s (rate_limited=%s, connection_error=%s): %s",
                    batch_idx, rate_limited, connection_error, exc,
                )
                return [], False, rate_limited, connection_error

        # 使用线程池并发执行批次，物理上限 max_workers，逻辑上限由 controller 动态决定
        pending: set[concurrent.futures.Future] = set()
        submit_times: dict[concurrent.futures.Future, float] = {}
        completed_batches = 0
        deadline_exceeded = False
        last_log_concurrency = controller.current()
        last_log_time = start_monotonic
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            input_iter = iter(batch_inputs)
            # 初始提交 controller.current() 个任务
            initial_submit = min(controller.current(), len(batch_inputs))
            for _ in range(initial_submit):
                batch_idx, _, input_payload, user_prompt, valid_uids = next(input_iter)
                fut = executor.submit(_process_batch, batch_idx, input_payload, user_prompt, valid_uids)
                pending.add(fut)
                submit_times[fut] = time.monotonic()

            while pending:
                # 等待至少一个任务完成
                done, pending = concurrent.futures.wait(
                    pending, timeout=1.0, return_when=concurrent.futures.FIRST_COMPLETED
                )
                for future in done:
                    completed_batches += 1
                    try:
                        batch_results, success, rate_limited, connection_error = future.result()
                        results.extend(batch_results)
                        # AIMD：根据批次结果调整并发上限（三级失败分类）
                        if success:
                            controller.on_success()
                            submit_t = submit_times.pop(future, None)
                            if submit_t is not None:
                                controller.record_latency(time.monotonic() - submit_t)
                        else:
                            controller.on_failure(
                                rate_limited=rate_limited,
                                connection_error=connection_error,
                            )
                            submit_times.pop(future, None)
                    except Exception as exc:
                        controller.on_failure(
                            rate_limited=_is_rate_limit_error(exc),
                            connection_error=_is_connection_error(exc),
                        )
                        submit_times.pop(future, None)
                        logger.warning("AI coreference batch future failed: %s", exc)

                # 周期性日志：每 15s 或并发数变化超过 5 时记录一次
                now = time.monotonic()
                current_concurrency = controller.current()
                if now - last_log_time >= 15.0 or abs(current_concurrency - last_log_concurrency) >= 5:
                    logger.info(
                        "AI coreference progress run_id=%s: completed %d/%d, pending %d, "
                        "concurrency %d (peak %d), elapsed %.1fs",
                        run_id, completed_batches, total_batches, len(pending),
                        current_concurrency, controller.stats()["peak"], now - start_monotonic,
                    )
                    last_log_concurrency = current_concurrency
                    last_log_time = now

                # 延迟退化检查
                if controller.check_latency_degrade():
                    controller.on_latency_degrade()
                    logger.warning("AI coreference latency degraded for run_id=%s, backing off to %d", run_id, controller.current())

                # deadline 检查：超时后停止提交新批次，但等待已提交的完成
                elapsed = now - start_monotonic
                if elapsed >= deadline_seconds and not deadline_exceeded:
                    deadline_exceeded = True
                    logger.warning(
                        "AI coreference deadline exceeded for run_id=%s: elapsed=%.1fs >= %ss, "
                        "stopping new submissions, completed %d/%d batches, %d pending, concurrency %d",
                        run_id, elapsed, deadline_seconds, completed_batches, total_batches,
                        len(pending), controller.current(),
                    )
                    self._record_error(
                        stage="ai_coreference",
                        exc=TimeoutError(f"coreference AI deadline exceeded: {elapsed:.1f}s >= {deadline_seconds}s"),
                    )
                    # 不再提交新批次，但让 pending 中的任务继续完成（它们已在执行中）

                # 若未超时，根据动态并发上限继续提交新批次
                if not deadline_exceeded:
                    current_limit = controller.current()
                    submitted_this_cycle = 0
                    while len(pending) < current_limit and submitted_this_cycle < BURST_SUBMIT_CAP:
                        try:
                            batch_idx, _, input_payload, user_prompt, valid_uids = next(input_iter)
                            fut = executor.submit(_process_batch, batch_idx, input_payload, user_prompt, valid_uids)
                            pending.add(fut)
                            submit_times[fut] = time.monotonic()
                            submitted_this_cycle += 1
                        except StopIteration:
                            break

        stats = controller.stats()
        if deadline_exceeded:
            logger.info(
                "AI coreference finished for run_id=%s: completed %d/%d batches, %d entities (deadline %ss), "
                "AIMD stats: peak=%d, success=%d, failure=%d, rate_limited=%d",
                run_id, completed_batches, total_batches, len(results), deadline_seconds,
                stats["peak"], stats["success"], stats["failure"], stats["rate_limited"],
            )
        else:
            logger.info(
                "AI coreference finished for run_id=%s: completed %d/%d batches, %d entities (%.1fs), "
                "AIMD stats: peak=%d, success=%d, failure=%d, rate_limited=%d",
                run_id, completed_batches, total_batches, len(results), time.monotonic() - start_monotonic,
                stats["peak"], stats["success"], stats["failure"], stats["rate_limited"],
            )
        return _dedupe_entities(results)

    def extract_facts(
        self,
        blocks: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        *,
        book_id: int,
        run_id: int,
        raise_on_error: bool = False,
    ) -> list[AtomicFact]:
        """对每个语义块单独调用 LLM，抽取与已知实体相关的原子事实。

        仅向 AI 传递在 block 文本中出现过的实体。quote_text 通过 text.find
        定位绝对字符位置；subject_entity_uid 必须来自已知实体列表。
        source_rule 标记为 "ai_llm_fact"。
        """
        results: list[AtomicFact] = []
        entity_index = self._build_entity_index(entities)
        for block in blocks:
            block_uid = str(block.get("block_uid") or "")
            try:
                chapter_id = block.get("chapter_id")
                char_start = int(block.get("char_start") or 0)
                text = str(block.get("text") or "")
                if not text.strip() or not block_uid:
                    continue
                for window in iter_ai_text_windows(
                    text,
                    window_chars=self.AI_TEXT_WINDOW_CHARS,
                    overlap=self.AI_TEXT_WINDOW_OVERLAP,
                ):
                    block_entities = self._entities_in_text(entity_index, window.text)
                    if not block_entities:
                        continue
                    input_payload = {
                        "book_id": book_id,
                        "block_uid": block_uid,
                        "window_index": window.index,
                        "window_start": window.start,
                        "window_end": window.end,
                        "text": window.text,
                        "entities": block_entities,
                    }
                    user_prompt = (
                        f"block_uid: {block_uid}\n"
                        f"chapter_id: {chapter_id}\n"
                        f"window_index: {window.index}\n"
                        f"window_start: {window.start}\n"
                        f"window_end: {window.end}\n"
                        f"已知实体（JSON）：\n{json.dumps(block_entities, ensure_ascii=False)}\n\n"
                        f"文本片段：\n{window.text}\n\n"
                        f"请抽取原子事实，subject_entity_uid 必须来自已知实体列表。"
                    )
                    output = self._call_llm(
                        stage="ai_fact",
                        input_payload=input_payload,
                        system_prompt=SYSTEM_PROMPT_FACT,
                        user_prompt=user_prompt,
                        timeout=self._compute_timeout_for_text(len(window.text)),
                    )
                    facts_data = output.get("facts")
                    if not isinstance(facts_data, list):
                        continue
                    valid_entity_uids = {e["entity_uid"] for e in block_entities}
                    for item in facts_data:
                        fact = self._parse_fact_item(
                            item,
                            text=window.text,
                            char_start=char_start + window.start,
                            chapter_id=chapter_id,
                            block_uid=block_uid,
                            valid_entity_uids=valid_entity_uids,
                            book_id=book_id,
                            run_id=run_id,
                            metadata={
                                "ai_window_index": window.index,
                                "ai_window_start": window.start,
                                "ai_window_end": window.end,
                            },
                        )
                        if fact is not None:
                            results.append(fact)
            except Exception as exc:
                self._record_error(stage="ai_fact", exc=exc, block_uid=block_uid)
                logger.warning("AI fact extraction failed for block %s: %s", block_uid, exc)
                if raise_on_error:
                    raise
                continue
        return _dedupe_facts(results)

    # ------------------------------------------------------------------
    # LLM 调用封装
    # ------------------------------------------------------------------

    def _compute_retry_backoff(self, exc: Exception, retry_index: int) -> float:
        """根据错误类型和重试序号计算退避秒数。

        - 限流(429)：指数退避 base * 2^(retry_index-1) → 2s, 4s, 8s
        - 超时：线性退避 base * retry_index → 1s, 2s, 3s
        - 其他：固定 AI_OTHER_BACKOFF（0.5s）
        """
        if _is_rate_limit_error(exc):
            return AI_RATE_LIMIT_BACKOFF_BASE * (2 ** max(0, retry_index - 1))
        error_type = self._classify_error(exc)
        if error_type == "timeout":
            return AI_TIMEOUT_BACKOFF_BASE * retry_index
        return AI_OTHER_BACKOFF

    def _call_llm(
        self,
        *,
        stage: str,
        input_payload: Any,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """调用 LLM，带缓存和错误处理。失败时抛异常。

        线程安全：缓存查询/写入经 ThreadSafeConnection 保护，
        共享计数器（cache_hits/call_count/retry_count/repaired_json_count）
        通过 _stats_lock 保护，支持 resolve_coreference 的并发批次调用。

        重试机制（AI_MAX_ATTEMPTS=4，即首次 + 3 次重试）：
        - 限流(429)：指数退避 2s/4s/8s
        - 超时：线性退避 1s/2s/3s
        - 其他：固定 0.5s

        timeout: 可选超时秒数，覆盖默认的 _request_timeout。
        分级超时由调用方根据输入文本长度传入（见 _compute_timeout_for_text）。
        """
        cached = self.llm_cache.get(
            stage=stage,
            prompt_version=self.prompt_version,
            schema_version=self.SCHEMA_VERSION,
            input_payload=input_payload,
        )
        if cached is not None:
            with self._stats_lock:
                self.cache_hits += 1
            return cached
        if not self.ai_service.is_remote_configured():
            raise RuntimeError("AI 服务未配置远程接口")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        last_error: Exception | None = None
        for attempt in range(1, self.AI_MAX_ATTEMPTS + 1):
            try:
                result = self.ai_service._post_json_chat_completion(messages, temperature=temperature, timeout=timeout)
                content = self.ai_service._chat_completion_content(result, purpose=stage)
                output, repaired = self._loads_json_object(content)
                if repaired:
                    with self._stats_lock:
                        self.repaired_json_count += 1
                self.llm_cache.put(
                    stage=stage,
                    prompt_version=self.prompt_version,
                    schema_version=self.SCHEMA_VERSION,
                    input_payload=input_payload,
                    output=output,
                )
                with self._stats_lock:
                    self.call_count += 1
                return output
            except Exception as exc:
                last_error = exc
                last_error.ai_attempt = attempt
                last_error.ai_error_type = self._classify_error(exc)
                if attempt < self.AI_MAX_ATTEMPTS:
                    retry_index = attempt  # 第 1 次失败后的重试序号为 1
                    backoff = self._compute_retry_backoff(exc, retry_index)
                    is_rate_limited = _is_rate_limit_error(exc)
                    logger.warning(
                        "AI %s 调用失败 (attempt %d/%d, %s), %.1fs 后重试: %s",
                        stage, attempt, self.AI_MAX_ATTEMPTS,
                        "rate_limited" if is_rate_limited else getattr(exc, "ai_error_type", ""),
                        backoff, str(exc)[:200],
                    )
                    with self._stats_lock:
                        self.retry_count += 1
                    time.sleep(backoff)
                    continue
                logger.error(
                    "AI %s 调用最终失败 (attempt %d/%d): %s",
                    stage, attempt, self.AI_MAX_ATTEMPTS, str(exc)[:300],
                )
                raise last_error from exc
        raise RuntimeError("AI call failed without an exception")

    def _loads_json_object(self, content: str) -> tuple[dict[str, Any], bool]:
        try:
            output = self.ai_service._loads_json_payload(content)
            if isinstance(output, dict):
                return output, False
            raise RuntimeError(f"AI 返回非 JSON 对象: {type(output)}")
        except Exception as first_error:
            candidate = json_candidate_text(str(content or ""), "{", "}")
            repaired = repair_json_like_text(candidate)
            balanced = balance_json_like_text(repaired)
            for item in (candidate, repaired, balanced):
                if not item:
                    continue
                try:
                    output = loads_json_payload(item)
                    if isinstance(output, dict):
                        return output, True
                except Exception:
                    continue
            try:
                return extract_json_object(content), True
            except Exception as exc:
                raise first_error from exc

    def _record_error(
        self,
        *,
        stage: str,
        exc: Exception,
        block_uid: str = "",
        batch_idx: int | None = None,
        attempt: int | None = None,
    ) -> None:
        error_type = str(getattr(exc, "ai_error_type", "") or self._classify_error(exc))
        resolved_attempt = attempt if attempt is not None else getattr(exc, "ai_attempt", None)
        block_uid_or_batch = str(block_uid or (batch_idx if batch_idx is not None else ""))
        with self._stats_lock:
            self.error_type_counts[error_type] = self.error_type_counts.get(error_type, 0) + 1
            self.errors.append({
                "stage": stage,
                "block_uid_or_batch": block_uid_or_batch,
                "error_type": error_type,
                "message": str(exc),
                "attempt": resolved_attempt,
                "error": str(exc),
                **({"block_uid": block_uid} if block_uid else {}),
                **({"batch_idx": batch_idx} if batch_idx is not None else {}),
            })

    @staticmethod
    def _classify_error(exc: Exception) -> str:
        message = str(exc).lower()
        name = exc.__class__.__name__
        if "timeout" in message or "timed out" in message:
            return "timeout"
        if "json" in message or "expecting" in message or "decode" in message:
            return "json_parse"
        if "empty" in message or "为空" in message:
            return "empty_response"
        if "configured" in message or "配置" in message:
            return "configuration"
        return name

    def check_consistency(
        self,
        *,
        prompt: str,
        probe_type: str,
        probe_uid: str,
    ) -> str | None:
        """LLM 一致性判定：给定探针证据，返回 JSON 字符串。"""
        try:
            output = self._call_llm(
                stage="ai_consistency_check",
                input_payload={"probe_uid": probe_uid, "probe_type": probe_type},
                system_prompt="你是一个小说一致性检查器，只输出 JSON。",
                user_prompt=prompt,
                temperature=0.1,
                timeout=self._compute_timeout_for_text(len(prompt)),
            )
            return json.dumps(output, ensure_ascii=False)
        except Exception as exc:
            logger.warning("AI consistency check failed for probe %s: %s", probe_uid, exc)
            return None

    def generate_card_content(
        self,
        *,
        card_type: str,
        entity: dict[str, Any],
        facts: list[dict[str, Any]],
        context: str = "",
        book_id: int = 0,
        run_id: int = 0,
    ) -> dict[str, Any] | None:
        """用 LLM 生成卡片的结构化内容，替代字符串机械拼接。

        card_type 三种：v3_character / v3_world / v3_book_summary。
        返回字典字段随 card_type 不同：
        - v3_character: title/profile_text/role/summary
        - v3_world: title/content_text/category/summary
        - v3_book_summary: title/outline_text/world_text/summary

        AI 调用失败时返回 None。
        """
        if card_type not in CARD_TYPES:
            logger.warning("generate_card_content: invalid card_type %s", card_type)
            return None
        entity_uid = ""
        try:
            canonical_name = str(entity.get("canonical_name") or "")
            entity_uid = str(entity.get("entity_uid") or "")
            entity_type = str(entity.get("entity_type") or "")
            metadata = entity.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            compact_entity = {
                "canonical_name": canonical_name,
                "entity_type": entity_type,
                "entity_uid": entity_uid,
                "metadata": metadata,
            }
            compact_facts = [
                {
                    "fact_uid": str(f.get("fact_uid") or ""),
                    "fact_type": str(f.get("fact_type") or ""),
                    "quote_text": str(f.get("quote_text") or ""),
                    "value": (
                        f.get("value")
                        if isinstance(f.get("value"), dict)
                        else {"summary": str(f.get("summary") or "")}
                    ),
                }
                for f in facts
                if isinstance(f, dict)
            ]
            input_payload = {
                "book_id": book_id,
                "card_type": card_type,
                "entity": compact_entity,
                "facts": compact_facts,
                "context": context,
            }
            user_prompt = (
                f"book_id: {book_id}\n"
                f"run_id: {run_id}\n"
                f"card_type: {card_type}\n"
                f"实体信息（JSON）：\n{json.dumps(compact_entity, ensure_ascii=False)}\n\n"
                f"关联事实（JSON）：\n{json.dumps(compact_facts, ensure_ascii=False)}\n\n"
                f"上下文章节摘要：\n{context}\n\n"
                f"请根据以上信息生成 {card_type} 类型的卡片内容，只返回纯 JSON 对象。"
            )
            output = self._call_llm(
                stage="ai_card_content",
                input_payload=input_payload,
                system_prompt=SYSTEM_PROMPT_CARD_CONTENT,
                user_prompt=user_prompt,
                timeout=self._compute_timeout_for_text(len(context) + len(json.dumps(compact_facts, ensure_ascii=False))),
            )
            if not isinstance(output, dict):
                return None
            required = CARD_REQUIRED_FIELDS.get(card_type, set())
            if not required.issubset(output.keys()):
                return None
            return output
        except Exception as exc:
            self._record_error(stage="ai_card_content", exc=exc)
            logger.warning(
                "AI card content generation failed for card_type=%s entity=%s: %s",
                card_type, entity_uid, exc,
            )
            return None

    def score_memory_importance(
        self,
        *,
        facts: list[dict[str, Any]],
        context: str = "",
        book_id: int = 0,
        run_id: int = 0,
    ) -> list[dict[str, Any]] | None:
        """用 LLM 对原子事实进行记忆重要性评分。

        输入：fact 列表（每个含 fact_uid/quote_text/fact_type/value.summary）+ 章节上下文。
        输出：list of {"fact_uid", "memory_level": "hot|warm|cold|archive", "importance_score": 0.0-1.0}。
        AI 调用失败时返回 None。

        分批策略：当事实数量超过 MEMORY_SCORE_BATCH_SIZE（默认 30）时，
        按 fact_type 均匀分组后分批发送给 LLM，避免单次输出超过 max_tokens 截断。
        每批独立调用，结果合并返回；部分批次失败时返回已成功的批次结果。
        """
        if not facts:
            return []
        try:
            compact_facts = [
                {
                    "fact_uid": str(f.get("fact_uid") or ""),
                    "fact_type": str(f.get("fact_type") or ""),
                    "quote_text": str(f.get("quote_text") or ""),
                    "value": (
                        f.get("value")
                        if isinstance(f.get("value"), dict)
                        else {"summary": str(f.get("summary") or "")}
                    ),
                }
                for f in facts
                if isinstance(f, dict)
            ]
            if not compact_facts:
                return []

            # 分批：按 fact_type 分组后轮询分配，保证每批类型分布均衡
            batches = self._split_facts_into_batches(compact_facts, self.MEMORY_SCORE_BATCH_SIZE)
            total_batches = len(batches)
            if total_batches == 1:
                # 单批直接调用（保持原有缓存键）
                return self._score_memory_batch(
                    batches[0], context=context, book_id=book_id, run_id=run_id,
                    batch_idx=0, total_batches=1,
                )

            # 多批并行调用
            logger.info("AI memory score: %d facts split into %d batches (batch_size=%d)",
                        len(compact_facts), total_batches, self.MEMORY_SCORE_BATCH_SIZE)
            all_results: list[dict[str, Any]] = []
            failed_batches = 0
            for idx, batch in enumerate(batches):
                try:
                    batch_results = self._score_memory_batch(
                        batch, context=context, book_id=book_id, run_id=run_id,
                        batch_idx=idx, total_batches=total_batches,
                    )
                    if batch_results:
                        all_results.extend(batch_results)
                    else:
                        failed_batches += 1
                except Exception as batch_exc:
                    failed_batches += 1
                    logger.warning("AI memory score batch %d/%d failed: %s",
                                   idx + 1, total_batches, batch_exc)

            if not all_results and failed_batches == total_batches:
                # 全部批次失败
                return None
            if failed_batches > 0:
                logger.warning("AI memory score: %d/%d batches failed, returning partial results (%d/%d facts scored)",
                               failed_batches, total_batches, len(all_results), len(compact_facts))
            return all_results
        except Exception as exc:
            self._record_error(stage="ai_memory_score", exc=exc)
            logger.warning("AI memory importance scoring failed: %s", exc)
            return None

    @staticmethod
    def _split_facts_into_batches(
        facts: list[dict[str, Any]], batch_size: int,
    ) -> list[list[dict[str, Any]]]:
        """将事实列表按 fact_type 轮询分组，保证每批类型分布均衡。

        例如 event/relation/state 三种类型混合时，避免某批全是 event、某批全是 state。
        """
        if batch_size >= len(facts):
            return [list(facts)]
        # 按 fact_type 分桶
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for f in facts:
            buckets[str(f.get("fact_type") or "event")].append(f)
        # 轮询从各桶取 fact，均匀分散到批次
        sorted_buckets = [buckets[k] for k in sorted(buckets.keys())]
        batches: list[list[dict[str, Any]]] = [[]]
        for bucket in sorted_buckets:
            for fact in bucket:
                if len(batches[-1]) >= batch_size:
                    batches.append([])
                batches[-1].append(fact)
        return [b for b in batches if b]

    def _score_memory_batch(
        self,
        batch_facts: list[dict[str, Any]],
        *,
        context: str,
        book_id: int,
        run_id: int,
        batch_idx: int,
        total_batches: int,
    ) -> list[dict[str, Any]] | None:
        """对单批事实调用 LLM 进行记忆评分。

        batch_idx/total_batches 用于日志和缓存区分，缓存键含批次信息避免跨批命中。
        """
        input_payload = {
            "book_id": book_id,
            "facts_count": len(batch_facts),
            "facts": batch_facts,
            "context": context,
            "batch_idx": batch_idx,
            "total_batches": total_batches,
        }
        user_prompt = (
            f"book_id: {book_id}\n"
            f"run_id: {run_id}\n"
            f"事实数量：{len(batch_facts)}\n"
            f"事实列表（JSON）：\n{json.dumps(batch_facts, ensure_ascii=False)}\n\n"
            f"章节上下文：\n{context}\n\n"
            f"请对每个事实进行记忆重要性评分，必须为每个 fact_uid 都给出评分，只返回纯 JSON 对象。"
        )
        output = self._call_llm(
            stage="ai_memory_score",
            input_payload=input_payload,
            system_prompt=SYSTEM_PROMPT_MEMORY_SCORE,
            user_prompt=user_prompt,
            timeout=self._compute_timeout_for_text(len(context) + len(json.dumps(batch_facts, ensure_ascii=False))),
        )
        scores_data = output.get("scores")
        if not isinstance(scores_data, list):
            return None
        results: list[dict[str, Any]] = []
        valid_uids = {f["fact_uid"] for f in batch_facts if f.get("fact_uid")}
        for item in scores_data:
            if not isinstance(item, dict):
                continue
            fact_uid = str(item.get("fact_uid") or "")
            if not fact_uid or fact_uid not in valid_uids:
                continue
            memory_level = str(item.get("memory_level") or "")
            if memory_level not in MEMORY_LEVELS:
                continue
            try:
                importance_score = float(item.get("importance_score") or 0.0)
            except (TypeError, ValueError):
                importance_score = 0.0
            importance_score = max(0.0, min(1.0, importance_score))
            results.append({
                "fact_uid": fact_uid,
                "memory_level": memory_level,
                "importance_score": importance_score,
            })
        return results

    def compress_memory(
        self,
        *,
        facts: list[dict[str, Any]],
        target_ratio: float = 0.3,
        book_id: int = 0,
        run_id: int = 0,
        timeout: int | None = None,
    ) -> str | None:
        """用 LLM 生成压缩后的记忆摘要文本。

        输入：待压缩的 fact 列表 + 目标压缩比。
        输出：压缩后的摘要文本字符串。AI 调用失败时返回 None。
        timeout: 可选超时秒数，覆盖默认的分级超时。记忆压缩建议传较短超时（如 90s）。
        """
        if not facts:
            return ""
        try:
            compact_facts = [
                {
                    "fact_uid": str(f.get("fact_uid") or ""),
                    "fact_type": str(f.get("fact_type") or ""),
                    "quote_text": str(f.get("quote_text") or ""),
                    "value": (
                        f.get("value")
                        if isinstance(f.get("value"), dict)
                        else {"summary": str(f.get("summary") or "")}
                    ),
                }
                for f in facts
                if isinstance(f, dict)
            ]
            safe_ratio = max(0.05, min(1.0, float(target_ratio)))
            input_payload = {
                "book_id": book_id,
                "facts_count": len(compact_facts),
                "facts": compact_facts,
                "target_ratio": safe_ratio,
            }
            user_prompt = (
                f"book_id: {book_id}\n"
                f"run_id: {run_id}\n"
                f"事实数量：{len(compact_facts)}\n"
                f"目标压缩比 target_ratio: {safe_ratio}\n"
                f"事实列表（JSON）：\n{json.dumps(compact_facts, ensure_ascii=False)}\n\n"
                f"请将以上事实压缩为一段连贯的摘要文本，压缩后字数约为原始事实总字数的 {safe_ratio} 倍，只返回纯 JSON 对象。"
            )
            output = self._call_llm(
                stage="ai_memory_compress",
                input_payload=input_payload,
                system_prompt=SYSTEM_PROMPT_MEMORY_COMPRESS,
                user_prompt=user_prompt,
                timeout=timeout if timeout is not None else self._compute_timeout_for_text(len(json.dumps(compact_facts, ensure_ascii=False))),
            )
            summary = output.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                return None
            return summary
        except Exception as exc:
            self._record_error(stage="ai_memory_compress", exc=exc)
            logger.warning("AI memory compression failed: %s", exc)
            return None

    def generate_probe_questions(
        self,
        *,
        probe_type: str,
        facts: list[dict[str, Any]],
        context: str = "",
        book_id: int = 0,
        run_id: int = 0,
    ) -> dict[str, Any] | None:
        """用 LLM 根据上下文生成有针对性的探针问题。

        probe_type 四种：foreshadowing_recovery / entity_state / world_rule / relationship_evolution。
        输出：{"question": "...", "expected": "..."}。AI 调用失败时返回 None。
        """
        if probe_type not in PROBE_TYPES:
            logger.warning("generate_probe_questions: invalid probe_type %s", probe_type)
            return None
        try:
            compact_facts = [
                {
                    "fact_uid": str(f.get("fact_uid") or ""),
                    "fact_type": str(f.get("fact_type") or ""),
                    "quote_text": str(f.get("quote_text") or ""),
                    "value": (
                        f.get("value")
                        if isinstance(f.get("value"), dict)
                        else {"summary": str(f.get("summary") or "")}
                    ),
                }
                for f in facts
                if isinstance(f, dict)
            ]
            input_payload = {
                "book_id": book_id,
                "probe_type": probe_type,
                "facts_count": len(compact_facts),
                "facts": compact_facts,
                "context": context,
            }
            user_prompt = (
                f"book_id: {book_id}\n"
                f"run_id: {run_id}\n"
                f"probe_type: {probe_type}\n"
                f"事实列表（JSON）：\n{json.dumps(compact_facts, ensure_ascii=False)}\n\n"
                f"章节上下文：\n{context}\n\n"
                f"请根据以上信息生成一个 {probe_type} 类型的探针问题及其预期答案，只返回纯 JSON 对象。"
            )
            output = self._call_llm(
                stage="ai_probe_question",
                input_payload=input_payload,
                system_prompt=SYSTEM_PROMPT_PROBE_QUESTION,
                user_prompt=user_prompt,
                timeout=self._compute_timeout_for_text(len(context) + len(json.dumps(compact_facts, ensure_ascii=False))),
            )
            if not isinstance(output, dict):
                return None
            question = str(output.get("question") or "").strip()
            expected = str(output.get("expected") or "").strip()
            if not question or not expected:
                return None
            return {"question": question, "expected": expected}
        except Exception as exc:
            self._record_error(stage="ai_probe_question", exc=exc)
            logger.warning(
                "AI probe question generation failed for probe_type=%s: %s",
                probe_type, exc,
            )
            return None

    def semantic_chunk(
        self,
        *,
        text: str,
        candidate_boundaries: list[int],
        book_id: int = 0,
        run_id: int = 0,
    ) -> list[int] | None:
        """用 LLM 辅助语义边界判定，调整规则分块的候选边界。

        输入：章节文本 + 规则分块的候选边界位置列表（字符偏移）。
        输出：调整后的语义块边界位置列表。AI 调用失败时返回 None。
        """
        clean_text = str(text or "")
        if not clean_text or not candidate_boundaries:
            return None
        try:
            text_len = len(clean_text)
            safe_boundaries = sorted({
                int(b)
                for b in candidate_boundaries
                if isinstance(b, int) or (isinstance(b, str) and b.lstrip("-").isdigit())
            })
            input_payload = {
                "book_id": book_id,
                "text_length": text_len,
                "text": clean_text,
                "candidate_boundaries": safe_boundaries,
            }
            user_prompt = (
                f"book_id: {book_id}\n"
                f"run_id: {run_id}\n"
                f"文本长度：{text_len}\n"
                f"候选边界（字符偏移列表）：{json.dumps(safe_boundaries, ensure_ascii=False)}\n\n"
                f"章节文本：\n{clean_text}\n\n"
                f"请基于语义连贯性调整边界位置，使每个块在语义上自洽，只返回纯 JSON 对象。"
            )
            output = self._call_llm(
                stage="ai_semantic_chunk",
                input_payload=input_payload,
                system_prompt=SYSTEM_PROMPT_SEMANTIC_CHUNK,
                user_prompt=user_prompt,
                timeout=self._compute_timeout_for_text(len(clean_text)),
            )
            boundaries_data = output.get("boundaries")
            if not isinstance(boundaries_data, list):
                return None
            results: list[int] = []
            for b in boundaries_data:
                try:
                    pos = int(b)
                except (TypeError, ValueError):
                    continue
                if 0 <= pos <= text_len:
                    results.append(pos)
            if not results:
                return None
            # 去重并升序排列
            return sorted(set(results))
        except Exception as exc:
            self._record_error(stage="ai_semantic_chunk", exc=exc)
            logger.warning("AI semantic chunk failed: %s", exc)
            return None

    def semantic_chunk_boundaries(
        self,
        *,
        text_len: int,
        boundary_windows: list[dict[str, Any]],
        book_id: int = 0,
        run_id: int = 0,
    ) -> list[int] | None:
        """基于边界窗口文本优化分块边界位置（V2 边界窗口模式）。

        不发送整章文本，只发送每个边界附近左右各 20% 的文本片段，
        让 AI 判断边界是否需要微调到更好的语义断点。

        输入：text_len 章节总长度 + boundary_windows 每个边界的窗口信息。
        输出：调整后的边界偏移列表（绝对偏移）。AI 调用失败时返回 None。
        """
        if not boundary_windows:
            return None
        try:
            # 计算窗口总文本量（用于超时计算）
            window_text_total = sum(
                len(str(w.get("left_text", ""))) + len(str(w.get("right_text", "")))
                for w in boundary_windows
            )

            # 构造 AI 输入：每个边界的窗口信息
            windows_payload = [
                {
                    "boundary": w["boundary"],
                    "left_context": w["left_text"],
                    "right_context": w["right_text"],
                }
                for w in boundary_windows
            ]
            windows_json = json.dumps(windows_payload, ensure_ascii=False)

            user_prompt = (
                f"章节总长度：{text_len}\n"
                f"边界数量：{len(boundary_windows)}\n\n"
                f"边界窗口（每个边界附带左右上下文片段）：\n{windows_json}\n\n"
                f"请对每个边界判断当前位置是否在语义断点：\n"
                f"- 若已在段落结尾/句号/换行处，保持不变\n"
                f"- 若在句子中间或对话中间，微调到附近最近的语义断点\n"
                f"- 边界偏移是相对于章节开头的绝对字符位置\n"
                f"只返回纯 JSON 对象，格式：{{\"boundaries\": [偏移1, 偏移2, ...]}}"
            )

            output = self._call_llm(
                stage="ai_semantic_chunk",
                input_payload={
                    "book_id": book_id,
                    "text_length": text_len,
                    "boundary_count": len(boundary_windows),
                    "window_text_total": window_text_total,
                },
                system_prompt=SYSTEM_PROMPT_SEMANTIC_CHUNK_V2,
                user_prompt=user_prompt,
                timeout=self._compute_timeout_for_text(window_text_total),
            )

            boundaries_data = output.get("boundaries")
            if not isinstance(boundaries_data, list):
                return None
            results: list[int] = []
            for b in boundaries_data:
                try:
                    pos = int(b)
                except (TypeError, ValueError):
                    continue
                if 0 <= pos <= text_len:
                    results.append(pos)
            if not results:
                return None
            return sorted(set(results))
        except Exception as exc:
            self._record_error(stage="ai_semantic_chunk", exc=exc)
            logger.warning("AI semantic chunk boundaries failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # M2 规则先行 + 标记打包 + 异常二次复查
    # ------------------------------------------------------------------

    def screen_mention_markers(
        self,
        markers: list[dict[str, Any]],
        *,
        book_id: int,
        run_id: int,
        raise_on_error: bool = False,
    ) -> list[dict[str, Any]]:
        """批量审核规则提取的实体候选标记（仅元数据，不含原文）。

        输入：markers 列表，每项含 marker_id/quote_text/entity_type/confidence/
              source_rule/chapter_title/co_occurrence。
        输出：审核结果列表，每项含 marker_id/verdict(confirmed|suspicious|reject)/
              confidence/reason。

        LLM 调用失败时返回空列表（由调用方决定降级策略）。
        """
        if not markers:
            return []
        try:
            markers_json = json.dumps(markers, ensure_ascii=False)
            input_payload = {
                "book_id": book_id,
                "run_id": run_id,
                "marker_count": len(markers),
                "markers": markers,
            }
            user_prompt = (
                f"book_id: {book_id}\n"
                f"标记数量：{len(markers)}\n"
                f"标记列表（JSON）：\n{markers_json}\n\n"
                f"请审核每个标记的可靠性，返回判定结果。"
            )
            output = self._call_llm(
                stage="ai_mention_screen",
                input_payload=input_payload,
                system_prompt=SYSTEM_PROMPT_MENTION_SCREEN,
                user_prompt=user_prompt,
                timeout=self._compute_timeout_for_text(len(user_prompt)),
            )
            results_data = output.get("results")
            if not isinstance(results_data, list):
                return []
            parsed: list[dict[str, Any]] = []
            valid_ids = {str(m.get("marker_id") or "") for m in markers}
            for item in results_data:
                if not isinstance(item, dict):
                    continue
                marker_id = str(item.get("marker_id") or "")
                if marker_id not in valid_ids:
                    continue
                verdict = str(item.get("verdict") or "").strip().lower()
                if verdict not in ("confirmed", "suspicious", "reject"):
                    verdict = "suspicious"
                try:
                    conf = float(item.get("confidence") or 0.5)
                except (TypeError, ValueError):
                    conf = 0.5
                parsed.append({
                    "marker_id": marker_id,
                    "verdict": verdict,
                    "confidence": max(0.0, min(1.0, conf)),
                    "reason": str(item.get("reason") or ""),
                })
            return parsed
        except Exception as exc:
            self._record_error(stage="ai_mention_screen", exc=exc)
            logger.warning("AI mention screen failed: %s", exc)
            if raise_on_error:
                raise
            return []

    def review_suspicious_mention(
        self,
        marker: dict[str, Any],
        context_text: str,
        *,
        book_id: int,
        run_id: int,
        raise_on_error: bool = False,
    ) -> dict[str, Any] | None:
        """对单个可疑标记进行二次复查（携带上下文文本）。

        输入：marker（含 quote_text/entity_type/source_rule/chapter_title）+
              context_text（标记位置前后各约 300 字，标记位置用【标记开始】【标记结束】标注）。
        输出：{verdict, entity_type, confidence, corrected_quote_text} 或 None（调用失败）。
        """
        if not context_text or not marker:
            return None
        try:
            quote_text = str(marker.get("quote_text") or "")
            entity_type = str(marker.get("entity_type") or "")
            source_rule = str(marker.get("source_rule") or "")
            chapter_title = str(marker.get("chapter_title") or "")

            input_payload = {
                "book_id": book_id,
                "run_id": run_id,
                "marker_id": str(marker.get("marker_id") or ""),
                "quote_text": quote_text,
                "entity_type": entity_type,
                "source_rule": source_rule,
                "context_length": len(context_text),
            }
            user_prompt = (
                f"标记元数据：\n"
                f"- quote_text: {quote_text}\n"
                f"- entity_type: {entity_type}\n"
                f"- source_rule: {source_rule}\n"
                f"- chapter_title: {chapter_title}\n\n"
                f"上下文文本（标记位置已标注）：\n{context_text}\n\n"
                f"请判定标记是否为有效实体。"
            )
            output = self._call_llm(
                stage="ai_mention_review",
                input_payload=input_payload,
                system_prompt=SYSTEM_PROMPT_MENTION_REVIEW,
                user_prompt=user_prompt,
                timeout=self._compute_timeout_for_text(len(user_prompt)),
            )
            verdict = str(output.get("verdict") or "").strip().lower()
            if verdict not in ("confirmed", "reject"):
                verdict = "confirmed"
            try:
                conf = float(output.get("confidence") or 0.5)
            except (TypeError, ValueError):
                conf = 0.5
            result_entity_type = str(output.get("entity_type") or entity_type).strip()
            corrected = str(output.get("corrected_quote_text") or "").strip()
            return {
                "marker_id": str(marker.get("marker_id") or ""),
                "verdict": verdict,
                "entity_type": result_entity_type,
                "confidence": max(0.0, min(1.0, conf)),
                "corrected_quote_text": corrected if corrected else quote_text,
            }
        except Exception as exc:
            self._record_error(stage="ai_mention_review", exc=exc)
            logger.warning("AI mention review failed: %s", exc)
            if raise_on_error:
                raise
            return None

    # ------------------------------------------------------------------
    # 解析辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_mention_item(
        item: Any,
        *,
        text: str,
        char_start: int,
        chapter_id: int | None,
        block_uid: str,
        book_id: int,
        run_id: int,
        metadata: dict[str, Any] | None = None,
    ) -> EntityMentionCandidate | None:
        if not isinstance(item, dict):
            return None
        quote_text = str(item.get("quote_text") or "").strip()
        if not quote_text:
            return None
        rel = text.find(quote_text)
        if rel < 0:
            return None
        abs_start = char_start + rel
        abs_end = abs_start + len(quote_text)
        entity_type = normalize_entity_type(item.get("entity_type"), "character")
        normalized_text = normalize_entity_alias(quote_text)
        try:
            confidence = float(item.get("confidence") or 0.5)
        except (TypeError, ValueError):
            confidence = 0.5
        return EntityMentionCandidate.create(
            book_id=book_id,
            run_id=run_id,
            entity_type=entity_type,
            normalized_text=normalized_text,
            quote_text=quote_text,
            chapter_id=chapter_id,
            block_uid=block_uid,
            char_start=abs_start,
            char_end=abs_end,
            confidence=confidence,
            source_rule="ai_llm",
            metadata=metadata,
        )

    @staticmethod
    def _parse_entity_item(
        item: Any,
        valid_uids: set[str],
        *,
        book_id: int,
    ) -> ResolvedEntityCandidate | None:
        if not isinstance(item, dict):
            return None
        canonical_name = str(item.get("canonical_name") or "").strip()
        if not canonical_name:
            return None
        entity_type = normalize_entity_type(item.get("entity_type"), "character")
        aliases_raw = item.get("aliases") or []
        aliases = (
            [str(a).strip() for a in aliases_raw if str(a).strip()]
            if isinstance(aliases_raw, list)
            else []
        )
        mention_uids_raw = item.get("mention_uids") or []
        mention_uids = (
            [
                str(u).strip()
                for u in mention_uids_raw
                if str(u).strip() and str(u).strip() in valid_uids
            ]
            if isinstance(mention_uids_raw, list)
            else []
        )
        if not mention_uids:
            return None
        try:
            confidence = float(item.get("confidence") or 0.7)
        except (TypeError, ValueError):
            confidence = 0.7
        entity_uid = stable_entity_uid(entity_type, canonical_name, book_id=book_id)
        return ResolvedEntityCandidate(
            entity_uid=entity_uid,
            entity_type=entity_type,
            canonical_name=canonical_name,
            aliases=tuple(aliases),
            mention_uids=tuple(mention_uids),
            confidence=confidence,
            status="candidate",
            source_rule="ai_llm_coreference",
            summary="",
            metadata={"schema_version": ANALYSIS_V3_SCHEMA_VERSION},
        )

    @staticmethod
    def _parse_fact_item(
        item: Any,
        *,
        text: str,
        char_start: int,
        chapter_id: int | None,
        block_uid: str,
        valid_entity_uids: set[str],
        book_id: int,
        run_id: int,
        metadata: dict[str, Any] | None = None,
    ) -> AtomicFact | None:
        if not isinstance(item, dict):
            return None
        subject_entity_uid = str(item.get("subject_entity_uid") or "")
        if not subject_entity_uid or subject_entity_uid not in valid_entity_uids:
            return None
        fact_type = str(item.get("fact_type") or "event")
        if fact_type not in FACT_TYPES:
            fact_type = "event"
        quote_text = str(item.get("quote_text") or "").strip()
        if not quote_text:
            return None
        rel = text.find(quote_text)
        if rel < 0:
            return None
        abs_start = char_start + rel
        abs_end = abs_start + len(quote_text)
        value = item.get("value")
        if not isinstance(value, dict):
            value = {"summary": str(item.get("summary") or quote_text)}
        elif "summary" not in value:
            value = {**value, "summary": str(item.get("summary") or quote_text)}
        try:
            confidence = float(item.get("confidence") or 0.6)
        except (TypeError, ValueError):
            confidence = 0.6
        return AtomicFact.create(
            book_id=book_id,
            run_id=run_id,
            subject_entity_uid=subject_entity_uid,
            fact_type=fact_type,
            value=value,
            quote_text=quote_text,
            chapter_id=chapter_id,
            block_uid=block_uid,
            char_start=abs_start,
            char_end=abs_end,
            confidence=confidence,
            source_rule="ai_llm_fact",
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # 实体索引辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _build_entity_index(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        index: list[dict[str, Any]] = []
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            entity_uid = str(entity.get("entity_uid") or "")
            canonical_name = str(entity.get("canonical_name") or "")
            if not entity_uid or not canonical_name:
                continue
            aliases_raw = entity.get("aliases") or []
            aliases = (
                [str(a).strip() for a in aliases_raw if str(a).strip()]
                if isinstance(aliases_raw, list)
                else []
            )
            names = [canonical_name, *aliases]
            index.append(
                {
                    "entity_uid": entity_uid,
                    "entity_type": str(entity.get("entity_type") or ""),
                    "canonical_name": canonical_name,
                    "names": names,
                }
            )
        return index

    @staticmethod
    def _entities_in_text(
        entity_index: list[dict[str, Any]],
        text: str,
    ) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for entry in entity_index:
            for name in entry["names"]:
                if name and name in text:
                    found.append(
                        {
                            "entity_uid": entry["entity_uid"],
                            "entity_type": entry["entity_type"],
                            "canonical_name": entry["canonical_name"],
                            "aliases": entry.get("aliases", []),
                        }
                    )
                    break
        return found


def _dedupe_mentions(candidates: list[EntityMentionCandidate]) -> list[EntityMentionCandidate]:
    by_uid: dict[str, EntityMentionCandidate] = {}
    for candidate in candidates:
        existing = by_uid.get(candidate.mention_uid)
        if existing is None or candidate.confidence > existing.confidence:
            by_uid[candidate.mention_uid] = candidate
    return sorted(by_uid.values(), key=lambda item: (item.chapter_id or 0, item.block_uid, item.char_start, item.char_end, item.mention_uid))


def _dedupe_facts(candidates: list[AtomicFact]) -> list[AtomicFact]:
    by_uid: dict[str, AtomicFact] = {}
    for candidate in candidates:
        existing = by_uid.get(candidate.fact_uid)
        if existing is None or candidate.confidence > existing.confidence:
            by_uid[candidate.fact_uid] = candidate
    return sorted(by_uid.values(), key=lambda item: (item.chapter_id or 0, item.block_uid, item.fact_uid))


def _dedupe_entities(candidates: list[ResolvedEntityCandidate]) -> list[ResolvedEntityCandidate]:
    by_uid: dict[str, ResolvedEntityCandidate] = {}
    for candidate in candidates:
        existing = by_uid.get(candidate.entity_uid)
        if existing is None:
            by_uid[candidate.entity_uid] = candidate
            continue
        aliases = tuple(sorted({*existing.aliases, *candidate.aliases}))
        mention_uids = tuple(sorted({*existing.mention_uids, *candidate.mention_uids}))
        confidence = max(existing.confidence, candidate.confidence)
        preferred = candidate if candidate.confidence >= existing.confidence else existing
        by_uid[candidate.entity_uid] = ResolvedEntityCandidate(
            entity_uid=preferred.entity_uid,
            entity_type=preferred.entity_type,
            canonical_name=preferred.canonical_name,
            aliases=aliases,
            mention_uids=mention_uids,
            confidence=confidence,
            status=preferred.status,
            source_rule=preferred.source_rule,
            summary=preferred.summary,
            metadata={**existing.metadata, **candidate.metadata},
        )

    merged = _cross_batch_merge_entities(list(by_uid.values()))
    return sorted(merged, key=lambda item: (item.entity_type, item.canonical_name, item.entity_uid))


# 跨批次合并的名称相似度阈值（编辑距离比例），低于此值视为相似
_CROSS_BATCH_NAME_SIMILARITY_THRESHOLD = 0.35


def _names_should_merge(name_a: str, name_b: str) -> bool:
    """判断两个名称是否应该合并（子串关系或高相似度）。

    用于跨批次合并——AI coreference 分批处理时，同角色的不同称呼可能落在不同批次，
    产生不同 entity_uid 的相似实体。此函数判断它们是否应合并。
    """
    if not name_a or not name_b:
        return False
    if name_a == name_b:
        return True
    short, long = (name_a, name_b) if len(name_a) <= len(name_b) else (name_b, name_a)
    # 子串关系：短名（>=2 字）是长名的前缀/后缀/子串
    if len(short) >= 2:
        if long.startswith(short) or long.endswith(short):
            return True
        if short in long:
            return True
    # 编辑距离相似度
    try:
        from novel_app.analysis.coreference import _name_similarity
        sim = _name_similarity(name_a, name_b)
        if sim >= (1.0 - _CROSS_BATCH_NAME_SIMILARITY_THRESHOLD):
            return True
    except Exception:
        pass
    return False


def _cross_batch_merge_entities(
    entities: list[ResolvedEntityCandidate],
) -> list[ResolvedEntityCandidate]:
    """跨批次合并：将不同批次返回的、名称相似/子串关系的实体合并。

    AI coreference 按 MENTION_BATCH_SIZE 分批处理，跨批次的同角色不同称呼
    （如 batch1 返回 "张三"，batch2 返回 "张三爷"）会产生不同 entity_uid，
    _dedupe_entities 只按 entity_uid 去重无法合并。此函数补充跨批次合并。
    """
    if len(entities) <= 1:
        return entities

    # 按 entity_type 分组，只在同类型内合并
    by_type: dict[str, list[ResolvedEntityCandidate]] = {}
    for entity in entities:
        by_type.setdefault(str(entity.entity_type or ""), []).append(entity)

    result: list[ResolvedEntityCandidate] = []
    for _entity_type, group in by_type.items():
        if len(group) <= 1:
            result.extend(group)
            continue

        # 收集每个实体的所有名称（canonical + aliases）
        def _all_names(e: ResolvedEntityCandidate) -> set[str]:
            names = {str(e.canonical_name or "")}
            for alias in (e.aliases or ()):
                alias_text = str(alias or "").strip()
                if alias_text:
                    names.add(alias_text)
            names.discard("")
            return names

        # Union-Find 合并
        parent: dict[int, int] = {i: i for i in range(len(group))}

        def _find(x: int) -> int:
            while parent[x] != x:  # noqa: B023 — 闭包仅在同一迭代内定义并调用，parent 不会跨迭代泄漏
                parent[x] = parent[parent[x]]  # noqa: B023 — 闭包仅在同一迭代内定义并调用，parent 不会跨迭代泄漏
                x = parent[x]  # noqa: B023 — 闭包仅在同一迭代内定义并调用，parent 不会跨迭代泄漏
            return x

        def _union(a: int, b: int) -> None:
            ra, rb = _find(a), _find(b)
            if ra != rb:
                parent[ra] = rb  # noqa: B023 — 闭包仅在同一迭代内定义并调用，parent 不会跨迭代泄漏

        names_list = [_all_names(e) for e in group]
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                # 检查两个实体的任意名称对是否应该合并
                should_merge = any(
                    _names_should_merge(ni, nj)
                    for ni in names_list[i]
                    for nj in names_list[j]
                )
                if should_merge:
                    _union(i, j)

        # 按 root 分组并合并
        groups: dict[int, list[int]] = {}
        for i in range(len(group)):
            groups.setdefault(_find(i), []).append(i)

        for indices in groups.values():
            if len(indices) == 1:
                result.append(group[indices[0]])
                continue
            # 合并多个实体：选择置信度最高/mention 最多的作为主实体
            members = [group[i] for i in indices]
            members.sort(
                key=lambda e: (e.confidence, len(e.mention_uids)),
                reverse=True,
            )
            primary = members[0]
            all_aliases: set[str] = set(primary.aliases or ())
            all_mention_uids: set[str] = set(primary.mention_uids)
            all_metadata = dict(primary.metadata or {})
            confidence = primary.confidence
            for member in members[1:]:
                all_aliases.update(member.aliases or ())
                # 被合并实体的 canonical_name 也作为别名保留
                member_canonical = str(member.canonical_name or "").strip()
                if member_canonical and member_canonical != str(primary.canonical_name or ""):
                    all_aliases.add(member_canonical)
                all_mention_uids.update(member.mention_uids)
                if member.confidence > confidence:
                    confidence = member.confidence
                member_meta = member.metadata or {}
                for k, v in member_meta.items():
                    if k not in all_metadata:
                        all_metadata[k] = v
            # canonical_name 不在 aliases 中
            all_aliases.discard(str(primary.canonical_name or ""))
            result.append(
                ResolvedEntityCandidate(
                    entity_uid=primary.entity_uid,
                    entity_type=primary.entity_type,
                    canonical_name=primary.canonical_name,
                    aliases=tuple(sorted(all_aliases)),
                    mention_uids=tuple(sorted(all_mention_uids)),
                    confidence=confidence,
                    status=primary.status,
                    source_rule=primary.source_rule,
                    summary=primary.summary,
                    metadata=all_metadata,
                )
            )
    return result
