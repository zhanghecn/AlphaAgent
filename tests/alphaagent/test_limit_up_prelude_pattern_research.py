"""前奏形态因子研究测试：形态判定边界、量能口径锁、无未来函数、报告编排。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

import alphaagent.server.services.limit_up.leader_first_board_prelude_pattern_research as research
from alphaagent.server.services.limit_up.leader_first_board_deep_factor_research import (
    _mid_window_features,
)
from alphaagent.server.services.limit_up.leader_first_board_prelude_pattern_research import (
    _june_july_check,
    _pattern_hit_rates,
    _prelude_pattern_features,
    _volume_shift_by_pattern,
    attach_prelude_features,
)


def _bars(
    changes: list[float | None],
    turnovers: list[float | None] | None = None,
    *,
    start: str = "2026-06-01",
) -> list[dict[str, object]]:
    """按 change_pct 序列合成日线（trade_date 递增，窗口之前的值不影响形态）。"""

    bars: list[dict[str, object]] = []
    for index, change in enumerate(changes):
        day = date.fromisoformat(start) + timedelta(days=index)
        bars.append(
            {
                "vt_symbol": "600001.SSE",
                "trade_date": day.isoformat(),
                "close_price": 10.0,
                "change_pct": change,
                "turnover": turnovers[index] if turnovers else 100.0,
            }
        )
    return bars


# ── 形态 streak 判定 ─────────────────────────────────────────────────────


def test_small_yang_streak_three_days() -> None:
    features = _prelude_pattern_features(_bars([1.0, 2.0, 2.5]))
    assert features["prelude_small_yang_streak"] == 3
    assert features["prelude_small_yin_streak"] == 0
    assert features["prelude_pattern"] == "small_yang"


def test_small_yang_streak_two_days_with_big_yang_before() -> None:
    # D-3 大阳 5% 不参与计数，但 D-2/D-1 两根小阳已满足 streak=2
    features = _prelude_pattern_features(_bars([5.0, 2.0, 2.0]))
    assert features["prelude_small_yang_streak"] == 2
    assert features["prelude_pattern"] == "small_yang"


def test_big_yang_at_d1_breaks_yang_streak() -> None:
    # D-1 是大阳 3.01% → 从 D-1 起数立即打断
    features = _prelude_pattern_features(_bars([2.0, 2.0, 3.01]))
    assert features["prelude_small_yang_streak"] == 0
    assert features["prelude_pattern"] == "none"


def test_boundary_change_pct_exactly_three_counts() -> None:
    features = _prelude_pattern_features(_bars([3.0, 3.0]))
    assert features["prelude_small_yang_streak"] == 2
    assert features["prelude_pattern"] == "small_yang"


def test_zero_change_breaks_both_patterns() -> None:
    features = _prelude_pattern_features(_bars([2.0, 2.0, 0.0]))
    assert features["prelude_small_yang_streak"] == 0
    assert features["prelude_small_yin_streak"] == 0
    assert features["prelude_pattern"] == "none"


def test_zero_change_before_streak_does_not_break() -> None:
    # D-3 平盘（0），D-2/D-1 小阳 → streak=2 成立
    features = _prelude_pattern_features(_bars([0.0, 2.0, 2.0]))
    assert features["prelude_small_yang_streak"] == 2
    assert features["prelude_pattern"] == "small_yang"


def test_none_change_breaks_streak() -> None:
    features = _prelude_pattern_features(_bars([None, 2.0, 2.0]))
    assert features["prelude_small_yang_streak"] == 2  # D-3 缺失不影响 D-2/D-1
    features = _prelude_pattern_features(_bars([2.0, None, 2.0]))
    assert features["prelude_small_yang_streak"] == 1  # D-2 缺失打断
    assert features["prelude_pattern"] == "none"


def test_small_yin_streak_and_boundary() -> None:
    features = _prelude_pattern_features(_bars([-1.0, -2.0, -2.5]))
    assert features["prelude_small_yin_streak"] == 3
    assert features["prelude_pattern"] == "small_yin"
    boundary = _prelude_pattern_features(_bars([-3.0, -3.0]))
    assert boundary["prelude_small_yin_streak"] == 2
    assert boundary["prelude_pattern"] == "small_yin"
    broken = _prelude_pattern_features(_bars([-2.0, -3.01]))
    assert broken["prelude_small_yin_streak"] == 0
    assert broken["prelude_pattern"] == "none"


def test_yang_and_yin_are_mutually_exclusive() -> None:
    # D-1 是小阴 → 小阳 streak 立即为 0；D-2 小阳打断小阴 streak
    features = _prelude_pattern_features(_bars([2.0, 2.0, -1.0]))
    assert features["prelude_small_yang_streak"] == 0
    assert features["prelude_small_yin_streak"] == 1
    assert features["prelude_pattern"] == "none"


def test_custom_max_change_pct() -> None:
    # 2% 档：+2.5% 算大阳打断；4% 档：+3.5% 仍算小阳
    assert _prelude_pattern_features(_bars([2.5, 2.5]), max_change_pct=2.0)[
        "prelude_small_yang_streak"
    ] == 0
    assert _prelude_pattern_features(_bars([3.5, 3.5]), max_change_pct=4.0)[
        "prelude_pattern"
    ] == "small_yang"


# ── 量能特征 ─────────────────────────────────────────────────────────────


def test_vol_cv_hand_computed() -> None:
    changes = [1.0] * 10
    turnovers = [100.0] * 6 + [200.0] + [50.0, 50.0, 50.0]
    features = _prelude_pattern_features(_bars(changes, turnovers))
    # calm = turnovers[-10:-3] = [100×6, 200]，mean=800/7，pstdev/mean ≈ 0.3062
    assert features["prelude_vol_cv_7d"] == pytest.approx(0.3062, abs=1e-4)


def test_vol_cv_requires_five_valid_values() -> None:
    changes = [1.0] * 10
    turnovers: list[float | None] = [100.0, None, 100.0, None, 100.0, None, 100.0, 100.0, 50.0, 50.0]
    features = _prelude_pattern_features(_bars(changes, turnovers))
    # calm 窗口 7 根里只有 4 个有效值（<5）→ cv=None
    assert features["prelude_vol_cv_7d"] is None


def test_volume_features_none_when_history_short() -> None:
    features = _prelude_pattern_features(_bars([1.0] * 9))
    assert features["prelude_vol_cv_7d"] is None
    assert features["prelude_vol_shift_ratio"] is None


def test_vol_shift_ratio_matches_turnover_ratio_3d_vs_prev7d() -> None:
    """口径锁：prelude_vol_shift_ratio 与既有 turnover_ratio_3d_vs_prev7d 必须相等。"""

    turnovers = [float(100 + index * 7) for index in range(12)]
    bars = _bars([1.0] * 12, turnovers)
    prelude = _prelude_pattern_features(bars)
    mid = _mid_window_features(bars)
    assert prelude["prelude_vol_shift_ratio"] == mid["turnover_ratio_3d_vs_prev7d"]


def test_features_ignore_bars_outside_window() -> None:
    """无未来函数/窗口外无关：改动 D-11 及之前的 bar 不影响任何特征。"""

    changes = [0.5] * 5 + [1.0] * 10
    turnovers = [float(80 + index) for index in range(15)]
    base = _prelude_pattern_features(_bars(changes, turnovers))
    poisoned_changes = [9.9] * 5 + [1.0] * 10
    poisoned_turnovers: list[float | None] = [None] * 5 + turnovers[5:]
    poisoned = _prelude_pattern_features(_bars(poisoned_changes, poisoned_turnovers))
    assert base == poisoned


# ── attach_prelude_features ──────────────────────────────────────────────


def test_attach_prelude_features_uses_bars_before_event_day() -> None:
    changes = [1.0, 2.0, 2.0, 2.0, 9.9]  # D 日 9.9% 涨停；前奏 D-3..D-1 三根小阳
    bars = _bars(changes)
    sample = {"vt_symbol": "600001.SSE", "trade_date": bars[-1]["trade_date"]}
    attached = attach_prelude_features([sample], bars)
    assert attached[0]["prelude_small_yang_streak"] == 3
    assert attached[0]["prelude_pattern"] == "small_yang"


def test_attach_prelude_features_unknown_symbol_keeps_defaults() -> None:
    sample = {"vt_symbol": "600999.SSE", "trade_date": "2026-06-05"}
    attached = attach_prelude_features([sample], _bars([1.0, 2.0]))
    assert attached[0]["prelude_pattern"] == "none"
    assert attached[0]["prelude_vol_cv_7d"] is None


# ── 分析块 ───────────────────────────────────────────────────────────────


def _sample(
    pattern: str,
    leader: bool,
    *,
    month: str = "2026-06",
    shift: float | None = 1.2,
    cv: float | None = 0.3,
    return_20d: float | None = 5.0,
) -> dict[str, object]:
    return {
        "vt_symbol": "600001.SSE",
        "trade_date": f"{month}-15",
        "is_leader": leader,
        "prelude_pattern": pattern,
        "prelude_small_yang_streak": 2 if pattern == "small_yang" else 0,
        "prelude_small_yin_streak": 2 if pattern == "small_yin" else 0,
        "prelude_vol_shift_ratio": shift,
        "prelude_vol_cv_7d": cv,
        "return_20d_pct": return_20d,
        "d1_open_return_pct": 2.0 if leader else -1.0,
    }


def test_pattern_hit_rates() -> None:
    samples = [
        _sample("small_yang", True),
        _sample("small_yang", True),
        _sample("small_yin", True),
        _sample("none", True),
        _sample("small_yang", False),
        _sample("none", False),
        _sample("none", False),
        _sample("none", False),
    ]
    rows = {row["pattern"]: row for row in _pattern_hit_rates(samples)}
    assert rows["small_yang"]["leader_hit_rate"] == 0.5  # 2/4
    assert rows["small_yang"]["non_leader_hit_rate"] == 0.25  # 1/4
    assert rows["small_yang"]["rate_ratio"] == 2.0
    assert rows["any"]["leader_hit_rate"] == 0.75  # 3/4
    assert rows["any"]["non_leader_hit_rate"] == 0.25


def test_volume_shift_by_pattern_direction() -> None:
    samples = [
        *[_sample("small_yang", True, shift=1.3) for _ in range(25)],
        *[_sample("small_yin", True, shift=0.7) for _ in range(25)],
    ]
    result = _volume_shift_by_pattern(samples)
    yang = result["by_pattern"]["small_yang"]
    yin = result["by_pattern"]["small_yin"]
    assert yang["prob_expand"] == 1.0
    assert yin["prob_shrink"] == 1.0
    test = result["yang_vs_yin_mannwhitney"]
    assert test["p_value"] is not None and test["p_value"] < 0.01


def test_volume_shift_mannwhitney_skips_small_samples() -> None:
    samples = [_sample("small_yang", True), _sample("small_yin", True)]
    result = _volume_shift_by_pattern(samples)
    assert result["yang_vs_yin_mannwhitney"]["p_value"] is None


def test_june_july_check_flags_flip() -> None:
    monthly = [
        {
            "factor_key": "x",
            "months": [
                {"month": "2026-06", "direction": "positive", "auc": 0.6},
                {"month": "2026-07", "direction": "negative", "auc": 0.4},
            ],
        }
    ]
    rows = _june_july_check(monthly)
    assert rows[0]["flipped"] is True
    skipped = [
        {
            "factor_key": "y",
            "months": [
                {"month": "2026-06", "direction": "skip", "auc": None},
                {"month": "2026-07", "direction": "positive", "auc": 0.6},
            ],
        }
    ]
    assert _june_july_check(skipped)[0]["flipped"] is False


# ── 报告编排（monkeypatch 样本管线，合成 factor_samples）─────────────────────


def test_build_report_orchestration(monkeypatch: pytest.MonkeyPatch) -> None:
    samples: list[dict[str, object]] = []
    for index in range(40):
        leader = index % 2 == 0
        pattern = ("small_yang" if index % 3 == 0 else "small_yin") if leader else "none"
        samples.append(
            _sample(
                pattern,
                leader,
                month="2026-06" if index < 20 else "2026-07",
                shift=1.0 + index * 0.01,
                cv=0.2 + index * 0.005,
                return_20d=float(index % 15),
            )
        )

    monkeypatch.setattr(
        research,
        "build_factor_samples",
        lambda *args, **kwargs: ([], samples),
    )
    monkeypatch.setattr(
        research,
        "attach_prelude_features",
        lambda factor_samples, daily_bars, **kwargs: [dict(s) for s in factor_samples],
    )
    report = research.build_prelude_pattern_report(
        [], [], [], [], [], min_consecutive_boards=2, board_gap_mode="wave"
    )
    assert report["status"] == "ok"
    assert report["first_board_count"] == 40
    assert report["label_balance"]["positive"] == 20
    assert len(report["hit_rates"]) == 3
    assert len(report["numeric_factors"]) == 4
    assert len(report["monthly_stability"]) == 4
    assert len(report["june_july_check"]) == 4
    combos = {row["combo"] for row in report["combos"]}
    assert combos == {
        "__baseline__",
        "prelude_any",
        "prelude_a_calm",
        "prelude_b_calm",
        "prelude_a_calm_expand",
        "prelude_b_calm_shrink",
        "prelude_any_low_position",
    }
    baseline = next(row for row in report["combos"] if row["combo"] == "__baseline__")
    assert baseline["leader_rate"] == 0.5
    assert report["pattern_outcomes"]["categories"]
    assert report["volume_shift_by_pattern"]["by_pattern"]
    assert report["notes"]
