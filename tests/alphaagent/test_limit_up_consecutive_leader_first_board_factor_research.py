"""Tests for the consecutive-leader first-board factor mining study."""

from __future__ import annotations

import copy

from alphaagent.server.services.limit_up import (
    consecutive_leader_first_board_factor_research as study,
)


def _event(
    vt_symbol: str,
    trade_date: str,
    limit_times: int,
    *,
    first_limit_time: str = "09:30:00",
    is_sealed: bool = True,
    open_times: int = 0,
    seal_amount: float = 1.0e8,
    turnover: float = 5.0e8,
    float_market_cap: float = 5.0e9,
    turnover_rate: float = 5.0,
    industry_name: str = "电子",
    name: str = "示例",
    close_price: float = 11.0,
    change_pct: float = 10.0,
) -> dict:
    return {
        "vt_symbol": vt_symbol,
        "trade_date": trade_date,
        "limit_times": limit_times,
        "is_sealed": is_sealed,
        "first_limit_time": first_limit_time,
        "last_limit_time": first_limit_time,
        "open_times": open_times,
        "seal_amount": seal_amount,
        "turnover": turnover,
        "float_market_cap": float_market_cap,
        "turnover_rate": turnover_rate,
        "industry_name": industry_name,
        "name": name,
        "close_price": close_price,
        "change_pct": change_pct,
    }


def _calendar(*dates: str) -> list[str]:
    return list(dates)


# ── Task 1: extract_first_board_samples ────────────────────────────────


def test_three_board_first_board_is_marked_leader() -> None:
    events = [
        _event("600001.SSE", "2025-07-10", 1),
        _event("600001.SSE", "2025-07-11", 2),
        _event("600001.SSE", "2025-07-12", 3),
    ]
    samples = study.extract_first_board_samples(
        events, _calendar("2025-07-10", "2025-07-11", "2025-07-12"),
        min_consecutive_boards=3,
    )
    assert len(samples) == 1
    sample = samples[0]
    assert sample["trade_date"] == "2025-07-10"
    assert sample["eventual_peak"] == 3
    assert sample["is_leader"] is True
    assert sample["segment_length"] == 3


def test_single_board_is_negative() -> None:
    events = [_event("600001.SSE", "2025-07-10", 1)]
    samples = study.extract_first_board_samples(
        events, _calendar("2025-07-10"), min_consecutive_boards=3
    )
    assert len(samples) == 1
    assert samples[0]["eventual_peak"] == 1
    assert samples[0]["is_leader"] is False


def test_two_board_is_negative_at_threshold_three() -> None:
    events = [
        _event("600001.SSE", "2025-07-10", 1),
        _event("600001.SSE", "2025-07-11", 2),
    ]
    samples = study.extract_first_board_samples(
        events, _calendar("2025-07-10", "2025-07-11"), min_consecutive_boards=3
    )
    assert samples[0]["eventual_peak"] == 2
    assert samples[0]["is_leader"] is False


def test_non_adjacent_trading_day_breaks_segment() -> None:
    # 板3 落在 D4，D2→D4 不相邻（中间 D3 没涨停且不在段内）
    events = [
        _event("600001.SSE", "2025-07-10", 1),
        _event("600001.SSE", "2025-07-11", 2),
        _event("600001.SSE", "2025-07-14", 3),
    ]
    samples = study.extract_first_board_samples(
        events,
        _calendar("2025-07-10", "2025-07-11", "2025-07-13", "2025-07-14"),
        min_consecutive_boards=3,
    )
    assert len(samples) == 1
    # 段被 D2→D4 断开，首板段只到板2
    assert samples[0]["eventual_peak"] == 2
    assert samples[0]["is_leader"] is False


def test_threshold_change_flips_label() -> None:
    events = [
        _event("600001.SSE", "2025-07-10", 1),
        _event("600001.SSE", "2025-07-11", 2),
        _event("600001.SSE", "2025-07-12", 3),
    ]
    cal = _calendar("2025-07-10", "2025-07-11", "2025-07-12")
    assert (
        study.extract_first_board_samples(events, cal, min_consecutive_boards=3)[0][
            "is_leader"
        ]
        is True
    )
    assert (
        study.extract_first_board_samples(events, cal, min_consecutive_boards=4)[0][
            "is_leader"
        ]
        is False
    )


def test_multiple_segments_per_symbol() -> None:
    events = [
        _event("600001.SSE", "2025-07-10", 1),
        _event("600001.SSE", "2025-07-11", 2),
        _event("600001.SSE", "2025-07-21", 1),  # 新一段首板
        _event("600001.SSE", "2025-07-22", 2),
    ]
    samples = study.extract_first_board_samples(
        events,
        _calendar(
            "2025-07-10", "2025-07-11", "2025-07-21", "2025-07-22"
        ),
        min_consecutive_boards=3,
    )
    assert len(samples) == 2
    assert {s["trade_date"] for s in samples} == {"2025-07-10", "2025-07-21"}
    assert all(s["eventual_peak"] == 2 for s in samples)


def test_failed_board_events_are_ignored() -> None:
    events = [
        _event("600001.SSE", "2025-07-10", 1, is_sealed=True),
        _event("600001.SSE", "2025-07-11", 2, is_sealed=False),  # 炸板，不算
    ]
    samples = study.extract_first_board_samples(
        events, _calendar("2025-07-10", "2025-07-11"), min_consecutive_boards=3
    )
    assert len(samples) == 1
    assert samples[0]["eventual_peak"] == 1
    assert samples[0]["is_leader"] is False


def test_segment_missing_first_board_is_skipped() -> None:
    # 段从板2开始（首板数据缺失），无首板样本
    events = [
        _event("600001.SSE", "2025-07-10", 2),
        _event("600001.SSE", "2025-07-11", 3),
    ]
    samples = study.extract_first_board_samples(
        events, _calendar("2025-07-10", "2025-07-11"), min_consecutive_boards=3
    )
    assert samples == []


def test_eventual_peak_label_does_not_leak_across_segments() -> None:
    # 两段独立；篡改段B的峰值，段A的首板样本不变
    base = [
        _event("600001.SSE", "2025-07-10", 1),
        _event("600001.SSE", "2025-07-11", 2),
        _event("600002.SSE", "2025-07-10", 1),
        _event("600002.SSE", "2025-07-11", 2),
        _event("600002.SSE", "2025-07-12", 3),
        _event("600002.SSE", "2025-07-13", 4),
    ]
    cal = _calendar("2025-07-10", "2025-07-11", "2025-07-12", "2025-07-13")
    original = study.extract_first_board_samples(base, cal, min_consecutive_boards=3)
    mutated_input = copy.deepcopy(base)
    # 删掉 600002 的板4，让其峰值从4变3（同段，删除不影响 600001 段）
    mutated_input = [e for e in mutated_input if e["trade_date"] != "2025-07-13"]
    mutated = study.extract_first_board_samples(
        mutated_input, cal, min_consecutive_boards=3
    )
    original_a = next(s for s in original if s["vt_symbol"] == "600001.SSE")
    mutated_a = next(s for s in mutated if s["vt_symbol"] == "600001.SSE")
    assert original_a["eventual_peak"] == mutated_a["eventual_peak"]
    assert original_a["is_leader"] == mutated_a["is_leader"]


# ── Task 2: factor extraction ──────────────────────────────────────────


def _bar(
    vt_symbol: str,
    trade_date: str,
    *,
    open_price: float,
    close_price: float,
    high_price: float | None = None,
    low_price: float | None = None,
    volume: float = 1.0e6,
    turnover: float = 1.0e8,
    turnover_rate: float = 3.0,
    change_pct: float | None = None,
) -> dict:
    return {
        "vt_symbol": vt_symbol,
        "trade_date": trade_date,
        "open_price": open_price,
        "close_price": close_price,
        "high_price": high_price if high_price is not None else close_price,
        "low_price": low_price if low_price is not None else close_price,
        "volume": volume,
        "turnover": turnover,
        "turnover_rate": turnover_rate,
        "change_pct": change_pct,
    }


def _calendar_from(start: str, n: int) -> list[str]:
    from datetime import date, timedelta

    base = date.fromisoformat(start)
    return [(base + timedelta(days=i)).isoformat() for i in range(n)]


def test_first_limit_time_bucket_and_early_seal() -> None:
    sample = _event("600001.SSE", "2025-07-10", 1, first_limit_time="09:30:00")
    factors = study.extract_factor_vector(
        sample, symbol_bars=[], d_bar=None, prior_limits={}
    )
    assert factors["first_limit_time_bucket"] == "morning_0930_1000"
    assert factors["is_early_seal"] is True
    assert factors["first_limit_hour"] == 9


def test_late_seal_is_not_early() -> None:
    sample = _event("600001.SSE", "2025-07-10", 1, first_limit_time="13:45:00")
    factors = study.extract_factor_vector(
        sample, symbol_bars=[], d_bar=None, prior_limits={}
    )
    assert factors["is_early_seal"] is False
    assert factors["first_limit_time_bucket"] == "afternoon_1300_1400"


def test_prior_3d_shape_calculation() -> None:
    bars = [
        _bar("600001.SSE", "2025-07-07", open_price=10.0, close_price=10.5, high_price=10.6, low_price=9.9, change_pct=5.0),
        _bar("600001.SSE", "2025-07-08", open_price=10.5, close_price=10.0, high_price=10.7, low_price=9.8, change_pct=-4.76),
        _bar("600001.SSE", "2025-07-09", open_price=10.0, close_price=10.8, high_price=11.0, low_price=9.9, change_pct=8.0),
        _bar("600001.SSE", "2025-07-10", open_price=10.8, close_price=11.0, high_price=11.0, low_price=10.8, change_pct=10.0),
    ]
    shape = study._prior_3d_shape(bars, "2025-07-10")
    assert shape["prior_3d_cum_return_pct"] == round((10.8 / 10.5 - 1) * 100, 4)
    assert shape["prior_3d_max_change_pct"] == 8.0
    assert shape["prior_3d_up_days"] == 2
    assert shape["prior_day_change_pct"] == 8.0


def test_one_word_board_detection() -> None:
    sample = _event("600001.SSE", "2025-07-10", 1, seal_amount=2.0e8, turnover=3.0e8)
    d_bar = _bar(
        "600001.SSE", "2025-07-10",
        open_price=11.0, close_price=11.0, high_price=11.0, low_price=11.0,
    )
    seal = study._seal_quality(sample, d_bar)
    assert seal["is_one_word_board"] is True
    assert seal["seal_to_turnover_ratio"] == round(2.0e8 / 3.0e8, 4)
    assert seal["open_times"] == 0


def test_normal_board_not_one_word() -> None:
    sample = _event("600001.SSE", "2025-07-10", 1, open_times=2)
    d_bar = _bar(
        "600001.SSE", "2025-07-10",
        open_price=10.5, close_price=11.0, high_price=11.0, low_price=10.4,
    )
    seal = study._seal_quality(sample, d_bar)
    assert seal["is_one_word_board"] is False
    assert seal["open_times"] == 2


def test_prior_limit_counts_window() -> None:
    cal = _calendar_from("2025-01-01", 40)  # day_number 0..39
    all_events = [
        _event("600001.SSE", cal[0], 1),    # 远：126 内、20 外
        _event("600001.SSE", cal[25], 1),   # 近：20 内
        _event("600001.SSE", cal[28], 1),   # 首板 D
        _event("600001.SSE", cal[29], 2),   # 连板
    ]
    samples = study.extract_first_board_samples(all_events, cal, min_consecutive_boards=3)
    counts = study.compute_prior_limit_counts(samples, all_events, cal)
    key = ("600001.SSE", cal[28])
    assert counts[key]["prior_limit_count_126"] == 2
    assert counts[key]["prior_limit_count_20"] == 1
    assert counts[key]["days_since_prior_limit"] == 3


def test_extract_factor_vector_carries_label() -> None:
    sample = _event("600001.SSE", "2025-07-10", 1, first_limit_time="09:35:00")
    sample["is_leader"] = True
    sample["eventual_peak"] = 4
    factors = study.extract_factor_vector(
        sample, symbol_bars=[], d_bar=None, prior_limits={"prior_limit_count_126": 3}
    )
    assert factors["is_leader"] is True
    assert factors["eventual_peak"] == 4
    assert factors["prior_limit_count_126"] == 3
    assert factors["float_market_cap"] == 5.0e9


# ── Task 3: factor comparison statistics ───────────────────────────────


def _factor_sample(is_leader: bool, trade_date: str, **factors) -> dict:
    return {"is_leader": is_leader, "trade_date": trade_date, **factors}


def test_auc_perfect_separation() -> None:
    samples = [
        *(_factor_sample(True, f"d{i:02d}", score=100.0 + i) for i in range(20)),
        *(_factor_sample(False, f"d{i:02d}", score=float(i)) for i in range(20)),
    ]
    result = study.compare_numeric_factor(samples, "score")
    assert result["auc"] is not None
    assert result["auc"] > 0.99
    assert result["direction"] == "higher"


def test_auc_no_separation() -> None:
    samples = [
        _factor_sample(i % 2 == 0, f"d{i:02d}", score=float(i)) for i in range(40)
    ]
    result = study.compare_numeric_factor(samples, "score")
    assert result["auc"] is not None
    assert abs(result["auc"] - 0.5) < 0.15


def test_auc_none_when_one_side_empty() -> None:
    samples = [_factor_sample(True, "d01", score=1.0)]
    result = study.compare_numeric_factor(samples, "score")
    assert result["auc"] is None
    assert result["positive_count"] == 1
    assert result["negative_count"] == 0


def test_quintile_buckets_monotone_for_signal_factor() -> None:
    samples = [
        _factor_sample(i >= 40, f"d{i:02d}", score=float(i)) for i in range(50)
    ]
    result = study.compare_numeric_factor(samples, "score")
    rates = result["quintile_positive_rates"]
    assert len(rates) == 5
    assert rates[-1]["positive_rate"] > rates[0]["positive_rate"]


def test_bootstrap_ci_excludes_zero_for_strong_factor() -> None:
    samples = []
    for i in range(30):
        samples.append(_factor_sample(True, f"d{i:02d}", score=10.0))
        samples.append(_factor_sample(False, f"d{i:02d}", score=5.0))
    result = study.compare_numeric_factor(samples, "score", draws=200, seed=42)
    assert result["mean_delta"] == 5.0
    assert result["mean_delta_lower_95"] > 0


def test_categorical_factor_positive_rates() -> None:
    samples = [
        _factor_sample(True, "d01", bucket="morning_0930_1000"),
        _factor_sample(True, "d01", bucket="morning_0930_1000"),
        _factor_sample(False, "d02", bucket="afternoon_1400_1500"),
        _factor_sample(True, "d02", bucket="afternoon_1400_1500"),
    ]
    result = study.compare_categorical_factor(samples, "bucket")
    by_cat = {c["category"]: c for c in result["categories"]}
    assert by_cat["morning_0930_1000"]["positive_rate"] == 1.0
    assert by_cat["afternoon_1400_1500"]["positive_rate"] == 0.5


def test_rank_factors_orders_by_effect_strength() -> None:
    samples = []
    for i in range(20):
        samples.append(
            _factor_sample(True, f"d{i:02d}", strong=10.0, weak=float(i))
        )
        samples.append(
            _factor_sample(False, f"d{i:02d}", strong=1.0, weak=float(i))
        )
    ranking = study.rank_factors(samples, ["strong", "weak"], draws=100, seed=42)
    assert ranking[0]["factor_key"] == "strong"
    assert ranking[0]["effect_strength"] > ranking[1]["effect_strength"]


# ── Task 4: report orchestration & rendering ───────────────────────────


def _series_bars(symbol: str, dates: list[str], base: float = 10.0) -> list[dict]:
    bars: list[dict] = []
    price = base
    for trade_date in dates:
        close = round(price * 1.01, 2)
        bars.append(
            _bar(
                symbol,
                trade_date,
                open_price=price,
                close_price=close,
                high_price=round(close * 1.005, 2),
                low_price=round(price * 0.995, 2),
                change_pct=1.0,
                turnover=2.0e8,
            )
        )
        price = close
    return bars


def test_build_factor_report_structure() -> None:
    cal = _calendar_from("2025-06-01", 15)
    events = [
        _event("600001.SSE", cal[7], 1),
        _event("600001.SSE", cal[8], 2),
        _event("600001.SSE", cal[9], 3),
        _event("600002.SSE", cal[7], 1),
    ]
    bars = _series_bars("600001.SSE", cal[0:10]) + _series_bars("600002.SSE", cal[0:10])
    report = study.build_factor_report(events, bars, cal, min_consecutive_boards=3)
    assert report["execution_valid"] is False
    assert report["study_version"] == study.STUDY_VERSION
    assert report["label_balance"]["positive"] == 1
    assert report["label_balance"]["negative"] == 1
    assert isinstance(report["numeric_factor_ranking"], list)
    assert report["numeric_factor_ranking"]
    assert "first_limit_time_bucket" in report["categorical_factors"]


def test_render_markdown_contains_required_sections() -> None:
    cal = _calendar_from("2025-06-01", 15)
    events = [
        _event("600001.SSE", cal[7], 1),
        _event("600001.SSE", cal[8], 2),
        _event("600001.SSE", cal[9], 3),
        _event("600002.SSE", cal[7], 1),
    ]
    bars = _series_bars("600001.SSE", cal[0:10]) + _series_bars("600002.SSE", cal[0:10])
    report = study.build_factor_report(events, bars, cal, min_consecutive_boards=3)
    markdown = study.render_markdown(report)
    assert "## Boundary" in markdown
    assert "## Sample Balance" in markdown
    assert "## Numeric Factor Ranking" in markdown
    assert "## Decision" in markdown
    assert "## Evidence Boundary" in markdown


def test_build_factor_report_label_is_not_a_tradable_factor() -> None:
    # eventual_peak / is_leader 不在 numeric factor keys 里（防 lookahead）
    assert "eventual_peak" not in study.NUMERIC_FACTOR_KEYS
    assert "is_leader" not in study.NUMERIC_FACTOR_KEYS


def test_positive_rate_rendered_as_percentage() -> None:
    report = {
        "status": "ok",
        "study_version": "x",
        "min_consecutive_boards": 3,
        "first_board_count": 2,
        "label_balance": {"positive": 1, "negative": 19, "positive_rate": 0.05},
        "numeric_factor_ranking": [],
        "categorical_factors": {
            "first_limit_time_bucket": {
                "categories": [
                    {
                        "category": "auction_open",
                        "total": 5,
                        "positive_count": 1,
                        "positive_rate": 0.2,
                    }
                ]
            }
        },
    }
    markdown = study.render_markdown(report)
    assert "5.00%" in markdown  # 0.05 -> 5.00%
    assert "20.00%" in markdown  # 0.2 -> 20.00%
    assert "0.05%" not in markdown  # 不应把小数比例当百分比
