"""Tests for the morning-window leader probability study (v2)."""

from __future__ import annotations

import copy

from alphaagent.server.services.limit_up import (
    morning_window_leader_probability_research as study,
)


def _sample(first_limit_time, trade_date, is_leader=False, **factors):
    sample = {
        "first_limit_time": first_limit_time,
        "trade_date": trade_date,
        "is_leader": is_leader,
    }
    sample.update(factors)
    return sample


# ── Task 1: window filter / month group / time split ───────────────────


def test_filter_morning_window_boundaries() -> None:
    samples = [
        _sample("09:25:00", "2025-07-10"),  # 排除（< 09:30）
        _sample("09:30:00", "2025-07-10"),  # 含（左边界）
        _sample("10:30:00", "2025-07-11"),  # 含
        _sample("11:00:00", "2025-07-12"),  # 含（右边界）
        _sample("11:00:01", "2025-07-13"),  # 排除（> 11:00）
        _sample("13:00:00", "2025-07-14"),  # 排除
        _sample(None, "2025-07-15"),  # 排除（无时间）
    ]
    window = study.filter_morning_window(samples)
    assert sorted({s["trade_date"] for s in window}) == [
        "2025-07-10",
        "2025-07-11",
        "2025-07-12",
    ]


def test_filter_morning_window_custom_range() -> None:
    samples = [_sample("09:35:00", "d1"), _sample("10:30:00", "d2")]
    window = study.filter_morning_window(samples, start="09:40:00", end="10:00:00")
    assert window == []


def test_group_by_month() -> None:
    samples = [
        _sample("09:30:00", "2025-07-10"),
        _sample("09:30:00", "2025-07-20"),
        _sample("09:30:00", "2025-08-01"),
    ]
    by_month = study.group_by_month(samples)
    assert set(by_month.keys()) == {"2025-07", "2025-08"}
    assert len(by_month["2025-07"]) == 2
    assert len(by_month["2025-08"]) == 1


def test_time_holdout_split_no_overlap_no_leak() -> None:
    samples = [
        _sample("09:30:00", "2025-07-10"),
        _sample("09:30:00", "2025-08-10"),
        _sample("09:30:00", "2025-09-10"),
        _sample("09:30:00", "2025-10-10"),
    ]
    train, test = study.time_holdout_split(samples, train_months=2)
    assert sorted({s["trade_date"][:7] for s in train}) == ["2025-07", "2025-08"]
    assert sorted({s["trade_date"][:7] for s in test}) == ["2025-09", "2025-10"]
    # 无未来泄漏：test 所有日期严格晚于 train 最大日期
    assert min(s["trade_date"] for s in test) > max(s["trade_date"] for s in train)
    # 不重叠不遗漏
    assert len(train) + len(test) == len(samples)


# ── Task 2: transparent probability scoring ────────────────────────────


def _strong_train(factor_a="momentum", factor_b="noise"):
    """40 样本：factor_a 完美区分（正高负低），factor_b 无区分度。"""

    train = []
    for i in range(20):
        trade_date = f"2025-07-{i + 1:02d}"
        train.append(
            _sample("09:30:00", trade_date, is_leader=True, **{factor_a: 100.0 + i, factor_b: float(i)})
        )
        train.append(
            _sample("09:30:00", trade_date, is_leader=False, **{factor_a: float(i), factor_b: float(i)})
        )
    return train


def test_build_calibration_selects_strong_factors_only() -> None:
    train = _strong_train()
    calibration = study.build_calibration(train, ["momentum", "noise"], draws=50, seed=42)
    assert "momentum" in calibration["factors"]
    assert "noise" not in calibration["factors"]


def test_build_calibration_weights_sum_to_one() -> None:
    train = _strong_train()
    calibration = study.build_calibration(train, ["momentum"], draws=50, seed=42)
    weights = [spec["weight"] for spec in calibration["factors"].values()]
    assert abs(sum(weights) - 1.0) < 1e-6


def test_score_monotone_with_strong_factor() -> None:
    train = _strong_train()
    calibration = study.build_calibration(train, ["momentum"], draws=50, seed=42)
    high = study.score_leader_probability(
        _sample("09:30:00", "d1", momentum=110.0), calibration
    )
    low = study.score_leader_probability(
        _sample("09:30:00", "d1", momentum=5.0), calibration
    )
    assert high is not None and low is not None
    assert high > low
    assert high > 0.5


def test_score_skips_missing_factor() -> None:
    train = _strong_train(factor_a="alpha", factor_b="beta")
    calibration = study.build_calibration(train, ["alpha", "beta"], draws=50, seed=42)
    # 若 beta 因无区分度被排除，只剩 alpha；样本只有 alpha 仍可打分
    sample = _sample("09:30:00", "d1", alpha=110.0)
    score = study.score_leader_probability(sample, calibration)
    assert score is not None


def test_calibration_not_changed_by_test_outcome() -> None:
    train = _strong_train()
    calibration = study.build_calibration(train, ["momentum"], draws=50, seed=42)
    snapshot = copy.deepcopy(calibration)
    mutated_test = _sample("09:30:00", "2026-07-01", is_leader=False, momentum=110.0)
    study.score_leader_probability(mutated_test, calibration)
    assert calibration == snapshot


# ── Task 3: holdout evaluation & monthly stability ─────────────────────


def test_evaluate_score_locked_when_strong() -> None:
    train = _strong_train()
    calibration = study.build_calibration(train, ["momentum"], draws=50, seed=42)
    test = []
    for i in range(20):
        test.append(
            _sample("09:30:00", f"2026-07-{i + 1:02d}", is_leader=True, momentum=100.0 + i)
        )
        test.append(
            _sample("09:30:00", f"2026-07-{i + 1:02d}", is_leader=False, momentum=float(i))
        )
    result = study.evaluate_score(test, calibration, draws=50, seed=42)
    assert result["locked"] is True
    assert result["auc"] is not None and result["auc"] > 0.58
    assert result["top20_positive_rate"] > result["baseline_rate"]


def test_evaluate_score_baseline_rate_correct() -> None:
    train = _strong_train()
    calibration = study.build_calibration(train, ["momentum"], draws=50, seed=42)
    test = [
        _sample("09:30:00", "2026-07-01", is_leader=True, momentum=110.0),
        _sample("09:30:00", "2026-07-02", is_leader=True, momentum=105.0),
        _sample("09:30:00", "2026-07-03", is_leader=False, momentum=5.0),
        _sample("09:30:00", "2026-07-04", is_leader=False, momentum=2.0),
    ]
    result = study.evaluate_score(test, calibration, draws=50, seed=42)
    assert result["sample_count"] == 4
    assert result["positive_count"] == 2
    assert result["baseline_rate"] == 0.5


def test_monthly_stability_marks_direction_flip() -> None:
    month_higher = [
        *(_sample("09:30:00", f"d{i}", is_leader=True, x=100.0 + i) for i in range(20)),
        *(_sample("09:30:00", f"d{i}", is_leader=False, x=float(i)) for i in range(20)),
    ]
    month_lower = [
        *(_sample("09:30:00", f"d{i}", is_leader=True, x=float(i)) for i in range(20)),
        *(_sample("09:30:00", f"d{i}", is_leader=False, x=100.0 + i) for i in range(20)),
    ]
    stability = study.monthly_factor_stability(
        {"2025-07": month_higher, "2025-08": month_lower}, ["x"], draws=50, seed=42
    )
    assert stability["x"]["unstable"] is True
    assert set(stability["x"]["directions"]) == {"higher", "lower"}


def test_monthly_stability_consistent_direction() -> None:
    month = [
        *(_sample("09:30:00", f"d{i}", is_leader=True, x=100.0 + i) for i in range(20)),
        *(_sample("09:30:00", f"d{i}", is_leader=False, x=float(i)) for i in range(20)),
    ]
    stability = study.monthly_factor_stability(
        {"2025-07": month, "2025-08": month}, ["x"], draws=50, seed=42
    )
    assert stability["x"]["unstable"] is False


# ── Task 4: report orchestration & rendering ───────────────────────────


def _event(
    vt_symbol,
    trade_date,
    limit_times,
    *,
    first_limit_time="09:30:00",
    is_sealed=True,
    open_times=0,
    seal_amount=1.0e8,
    turnover=5.0e8,
    float_market_cap=5.0e9,
    turnover_rate=5.0,
    name="示例",
    close_price=11.0,
    change_pct=10.0,
):
    return {
        "vt_symbol": vt_symbol,
        "trade_date": trade_date,
        "limit_times": limit_times,
        "is_sealed": is_sealed,
        "first_limit_time": first_limit_time,
        "open_times": open_times,
        "seal_amount": seal_amount,
        "turnover": turnover,
        "float_market_cap": float_market_cap,
        "turnover_rate": turnover_rate,
        "name": name,
        "close_price": close_price,
        "change_pct": change_pct,
    }


def _bar(vt_symbol, trade_date, *, open_price, close_price, high_price=None, low_price=None, turnover=2.0e8, change_pct=1.0):
    return {
        "vt_symbol": vt_symbol,
        "trade_date": trade_date,
        "open_price": open_price,
        "close_price": close_price,
        "high_price": high_price if high_price is not None else close_price,
        "low_price": low_price if low_price is not None else close_price,
        "turnover": turnover,
        "turnover_rate": 3.0,
        "change_pct": change_pct,
    }


def _series_bars(symbol, dates, base=10.0):
    bars = []
    price = base
    for trade_date in dates:
        close = round(price * 1.01, 2)
        bars.append(
            _bar(symbol, trade_date, open_price=price, close_price=close, high_price=round(close * 1.005, 2), low_price=round(price * 0.995, 2))
        )
        price = close
    return bars


def _calendar_from(start, n):
    from datetime import date, timedelta

    base = date.fromisoformat(start)
    return [(base + timedelta(days=i)).isoformat() for i in range(n)]


def test_group_a_excludes_seal_time_factors() -> None:
    # 封板时刻质量因子不进封板前评分（A 组）
    assert "prior_return_5d_pct" in study.GROUP_A_FACTORS
    assert "first_limit_hour" not in study.GROUP_A_FACTORS
    assert "open_times" not in study.GROUP_A_FACTORS
    assert "seal_to_turnover_ratio" not in study.GROUP_A_FACTORS


def test_build_probability_report_structure() -> None:
    cal = _calendar_from("2025-06-01", 60)
    events = [
        # 月1 (2025-06)：龙 + 夭折
        _event("600001.SSE", cal[7], 1),
        _event("600001.SSE", cal[8], 2),
        _event("600001.SSE", cal[9], 3),
        _event("600002.SSE", cal[7], 1),
        # 月2 (2025-07)：龙 + 夭折
        _event("600003.SSE", cal[37], 1),
        _event("600003.SSE", cal[38], 2),
        _event("600003.SSE", cal[39], 3),
        _event("600004.SSE", cal[37], 1),
    ]
    bars = (
        _series_bars("600001.SSE", cal[0:40])
        + _series_bars("600002.SSE", cal[0:40])
        + _series_bars("600003.SSE", cal[0:40])
        + _series_bars("600004.SSE", cal[0:40])
    )
    report = study.build_probability_report(
        events, bars, cal, min_consecutive_boards=3, train_months=1, draws=50, seed=42
    )
    assert report["execution_valid"] is False
    assert report["study_version"] == study.STUDY_VERSION
    assert report["coverage"]["morning_window_count"] == 4
    assert isinstance(report["locked_factors"], list)
    assert "holdout_eval" in report
    assert "calibration" in report
    assert "monthly_stability" in report


def test_render_markdown_contains_required_sections() -> None:
    cal = _calendar_from("2025-06-01", 60)
    events = [
        _event("600001.SSE", cal[7], 1),
        _event("600001.SSE", cal[8], 2),
        _event("600001.SSE", cal[9], 3),
        _event("600002.SSE", cal[7], 1),
        _event("600003.SSE", cal[37], 1),
        _event("600003.SSE", cal[38], 2),
        _event("600003.SSE", cal[39], 3),
    ]
    bars = (
        _series_bars("600001.SSE", cal[0:40])
        + _series_bars("600002.SSE", cal[0:40])
        + _series_bars("600003.SSE", cal[0:40])
    )
    report = study.build_probability_report(
        events, bars, cal, min_consecutive_boards=3, train_months=1, draws=50, seed=42
    )
    markdown = study.render_markdown(report)
    assert "## Boundary" in markdown
    assert "## Holdout Validation" in markdown
    assert "## Monthly Stability" in markdown
    assert "## Decision" in markdown
