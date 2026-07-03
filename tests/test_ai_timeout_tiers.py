"""AI 分级超时计算单元测试。

验证 _compute_timeout_for_text 根据输入文本字符数返回正确的超时秒数，
确保短文本等待过久、长文本超时失败的问题得到解决。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from novel_app.analysis.ai_provider import AIAnalysisProvider


def test_short_text_returns_30s():
    """< 2000 字应返回 30 秒超时。"""
    assert AIAnalysisProvider._compute_timeout_for_text(0) == 30
    assert AIAnalysisProvider._compute_timeout_for_text(500) == 30
    assert AIAnalysisProvider._compute_timeout_for_text(1999) == 30


def test_medium_text_returns_60s():
    """2000-4000 字应返回 60 秒超时。"""
    assert AIAnalysisProvider._compute_timeout_for_text(2000) == 60
    assert AIAnalysisProvider._compute_timeout_for_text(3000) == 60
    assert AIAnalysisProvider._compute_timeout_for_text(3999) == 60


def test_long_text_returns_120s():
    """4000-8000 字应返回 120 秒超时。"""
    assert AIAnalysisProvider._compute_timeout_for_text(4000) == 120
    assert AIAnalysisProvider._compute_timeout_for_text(6000) == 120
    assert AIAnalysisProvider._compute_timeout_for_text(7999) == 120


def test_very_long_text_returns_180s():
    """8000-15000 字应返回 180 秒超时。"""
    assert AIAnalysisProvider._compute_timeout_for_text(8000) == 180
    assert AIAnalysisProvider._compute_timeout_for_text(10000) == 180
    assert AIAnalysisProvider._compute_timeout_for_text(14999) == 180


def test_huge_text_returns_300s():
    """>= 15000 字应返回 300 秒超时。"""
    assert AIAnalysisProvider._compute_timeout_for_text(15000) == 300
    assert AIAnalysisProvider._compute_timeout_for_text(30000) == 300
    assert AIAnalysisProvider._compute_timeout_for_text(1000000) == 300


def test_timeout_tiers_monotonically_increasing():
    """超时值应随文本长度单调递增。"""
    thresholds = [0, 1999, 2000, 3999, 4000, 7999, 8000, 14999, 15000, 50000]
    timeouts = [AIAnalysisProvider._compute_timeout_for_text(t) for t in thresholds]
    for i in range(1, len(timeouts)):
        assert timeouts[i] >= timeouts[i - 1], \
            f"超时非单调递增: text_len={thresholds[i]} timeout={timeouts[i]} < prev={timeouts[i-1]}"


if __name__ == "__main__":
    test_short_text_returns_30s()
    test_medium_text_returns_60s()
    test_long_text_returns_120s()
    test_very_long_text_returns_180s()
    test_huge_text_returns_300s()
    test_timeout_tiers_monotonically_increasing()
    print("✓ 全部 6 个分级超时单元测试通过")
