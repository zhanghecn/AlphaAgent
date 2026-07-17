"""大盘择时表现评估的时间对齐守护。"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from alphaagent.server.services.market_timing import backtest as bt
from alphaagent.server.services.market_timing import factors as fac
from alphaagent.server.services.market_timing import panel as mt_panel
from alphaagent.server.services.market_timing import signal as sig
from alphaagent.server.services.market_timing.series import CompositeBar


def _bars(
    closes: list[float],
    up_ratios: list[float | None] | None = None,
) -> list[CompositeBar]:
    start = date(2026, 1, 5)
    return [
        CompositeBar(
            trade_date=start + timedelta(days=index),
            close=close,
            turnover=1_000_000.0,
            return_pct=(
                0.0
                if index == 0
                else (close / closes[index - 1] - 1.0) * 100.0
            ),
            up_ratio=up_ratios[index] if up_ratios is not None else None,
        )
        for index, close in enumerate(closes)
    ]


def _event(
    trade_date: date,
    status: str,
    confirm_date: date | None,
) -> sig.TimingSignal:
    return sig.TimingSignal(
        trade_date=trade_date,
        direction="GOLD",
        status=status,
        grade="WEAK",
        bull_force=70.0,
        bear_force=40.0,
        phase="warming",
        setup_type=sig.SETUP_REVERSAL_GOLD,
        confirm_date=confirm_date,
        reasons=[],
    )


def _silver_event(
    trade_date: date,
    confirm_date: date,
) -> sig.TimingSignal:
    return replace(
        _event(trade_date, sig.STATUS_CONFIRMED, confirm_date),
        direction="SILVER",
        bull_force=40.0,
        bear_force=70.0,
        phase="retreat",
        setup_type=sig.SETUP_TOP_SILVER,
    )


def _factor(
    day: date,
    *,
    bull: float = 70.0,
    bear: float = 40.0,
    mom_5d: float = 1.0,
    above_ma20: bool = True,
    trend_breakdown: float = 28.0,
) -> fac.MarketTimingFactors:
    return fac.MarketTimingFactors(
        trade_date=day,
        phase="warming" if bull > bear else "retreat",
        trend=bull,
        momentum=bull,
        breadth=bull,
        structure=50.0,
        volume=50.0,
        bull_force=bull,
        bear_force=bear,
        close_above_ma20=above_ma20,
        mom_5d=mom_5d,
        mom_20d=1.0,
        macd_top=42.0,
        breadth_top=38.0,
        evidence={"trend_breakdown": trend_breakdown},
    )


def _state_bucket(
    report: dict,
    period: str,
    direction: str,
    horizon: int,
) -> bt.StateBucketStat:
    return next(
        bucket
        for bucket in report["buckets"]
        if bucket.period == period
        and bucket.direction == direction
        and bucket.horizon == horizon
    )


def _recovery_case(
    *,
    candidate_factor: dict[str, float | bool] | None = None,
    confirmation_close: float = 99.0,
    confirmation_up_ratio: float | None = 0.6,
    confirmation_bull: float = 60.0,
    confirmation_bear: float = 50.0,
) -> tuple[list[fac.MarketTimingFactors], list[CompositeBar], sig.TimingSignal]:
    bars = _bars(
        [100.0, 99.0, 98.0, 97.0, 96.0, 98.0, confirmation_close, 100.0],
        [0.1, 0.1, 0.1, 0.1, 0.1, 0.6, confirmation_up_ratio, 0.6],
    )
    factors = [
        _factor(
            bar.trade_date,
            bull=40.0,
            bear=70.0,
            mom_5d=-1.0,
            above_ma20=False,
        )
        for bar in bars
    ]
    factors[5] = _factor(
        bars[5].trade_date,
        **(
            candidate_factor
            or {
                "bull": 60.0,
                "bear": 50.0,
                "mom_5d": 1.0,
                "above_ma20": False,
            }
        ),
    )
    factors[6] = _factor(
        bars[6].trade_date,
        bull=confirmation_bull,
        bear=confirmation_bear,
        mom_5d=1.0,
        above_ma20=True,
    )
    return factors, bars, _silver_event(bars[0].trade_date, bars[1].trade_date)


def test_confirmed_performance_starts_after_confirmation_close() -> None:
    bars = _bars([100.0, 120.0, 120.0, 120.0, 120.0, 120.0, 120.0])
    event = _event(
        trade_date=bars[0].trade_date,
        status=sig.STATUS_CONFIRMED,
        confirm_date=bars[1].trade_date,
    )

    result = bt.evaluate([event], bars)

    confirmed_row = next(row for row in result["rows"] if row["horizon"] == 5)
    assert confirmed_row["candidate_date"] == bars[0].trade_date
    assert confirmed_row["confirm_date"] == bars[1].trade_date
    assert confirmed_row["start_date"] == bars[1].trade_date
    assert confirmed_row["setup_type"] == sig.SETUP_REVERSAL_GOLD
    assert confirmed_row["return"] == pytest.approx(0.0)

    candidate_row = next(
        row for row in result["candidate_rows"] if row["horizon"] == 5
    )
    assert candidate_row["candidate_date"] == bars[0].trade_date
    assert candidate_row["start_date"] == bars[0].trade_date
    assert candidate_row["setup_type"] == sig.SETUP_REVERSAL_GOLD
    assert candidate_row["return"] == pytest.approx(20.0)
    assert result["evaluation_basis"] == {
        "confirmed_start": "confirm_date_close",
        "candidate_start": "candidate_date_close",
        "executable": False,
    }


def test_candidate_performance_keeps_every_candidate_status() -> None:
    bars = _bars([100.0] * 12)
    events = [
        _event(bars[0].trade_date, sig.STATUS_CONFIRMED, bars[1].trade_date),
        _event(bars[2].trade_date, sig.STATUS_INVALIDATED, bars[3].trade_date),
        _event(bars[4].trade_date, sig.STATUS_PENDING, None),
    ]

    result = bt.evaluate(events, bars)

    confirmed_candidates = {row["candidate_date"] for row in result["rows"]}
    all_candidates = {row["candidate_date"] for row in result["candidate_rows"]}
    assert confirmed_candidates == {bars[0].trade_date}
    assert all_candidates == {event.trade_date for event in events}

    five_day_bucket = next(
        bucket
        for bucket in result["candidate_buckets"]
        if bucket.direction == "GOLD"
        and bucket.grade == "WEAK"
        and bucket.horizon == 5
    )
    assert five_day_bucket.count == 3


def test_panel_serializes_both_evaluation_bases() -> None:
    bars = _bars([100.0, 120.0, 120.0, 120.0, 120.0, 120.0, 120.0])
    event = _event(
        trade_date=bars[0].trade_date,
        status=sig.STATUS_CONFIRMED,
        confirm_date=bars[1].trade_date,
    )

    accuracy = mt_panel._build_accuracy(bt.evaluate([event], bars))

    assert accuracy["evaluation_basis"]["confirmed_start"] == "confirm_date_close"
    assert accuracy["candidate_buckets"][0]["direction"] == "GOLD"
    assert accuracy["rows"][0]["start_date"] == bars[1].trade_date.isoformat()
    assert accuracy["rows"][0]["setup_type"] == sig.SETUP_REVERSAL_GOLD
    assert accuracy["candidate_rows"][0]["start_date"] == bars[0].trade_date.isoformat()


def test_direction_state_metrics_cover_gold_drawdown_and_silver_rebound() -> None:
    bars = _bars([100.0, 110.0, 90.0, 95.0, 80.0, 120.0, 110.0])
    directions = [
        "GOLD",
        "SILVER",
        "NEUTRAL",
        "NEUTRAL",
        "NEUTRAL",
        "NEUTRAL",
        "NEUTRAL",
    ]

    report = bt.evaluate_direction_states(
        directions,
        bars,
        split_date=bars[4].trade_date,
    )

    gold_one_day = _state_bucket(report, "ALL", "GOLD", 1)
    assert gold_one_day.hit_rate == 1.0
    assert gold_one_day.avg_return == pytest.approx(10.0)
    assert gold_one_day.avg_adverse_excursion == 0.0
    assert gold_one_day.adverse_3pct_rate == 0.0

    gold_three_day = _state_bucket(report, "ALL", "GOLD", 3)
    assert gold_three_day.hit_rate == 0.0
    assert gold_three_day.avg_return == pytest.approx(-5.0)
    assert gold_three_day.avg_directional_return == pytest.approx(-5.0)
    assert gold_three_day.avg_adverse_excursion == pytest.approx(-10.0)
    assert gold_three_day.adverse_3pct_rate == 1.0

    gold = _state_bucket(report, "ALL", "GOLD", 5)
    assert gold.count == 1
    assert gold.hit_rate == 1.0
    assert gold.avg_return == pytest.approx(20.0)
    assert gold.avg_directional_return == pytest.approx(20.0)
    assert gold.avg_adverse_excursion == pytest.approx(-20.0)
    assert gold.worst_adverse_excursion == pytest.approx(-20.0)
    assert gold.adverse_3pct_rate == 1.0

    silver_one_day = _state_bucket(report, "ALL", "SILVER", 1)
    assert silver_one_day.hit_rate == 1.0
    assert silver_one_day.avg_return == pytest.approx((90.0 / 110.0 - 1.0) * 100.0)
    assert silver_one_day.avg_adverse_excursion == 0.0
    assert silver_one_day.adverse_3pct_rate == 0.0

    silver_three_day = _state_bucket(report, "ALL", "SILVER", 3)
    assert silver_three_day.hit_rate == 1.0
    assert silver_three_day.avg_return == pytest.approx((80.0 / 110.0 - 1.0) * 100.0)
    assert silver_three_day.avg_directional_return == pytest.approx(
        (1.0 - 80.0 / 110.0) * 100.0,
    )
    assert silver_three_day.avg_adverse_excursion == 0.0
    assert silver_three_day.adverse_3pct_rate == 0.0

    silver = _state_bucket(report, "ALL", "SILVER", 5)
    assert silver.count == 1
    assert silver.hit_rate == 0.0
    assert silver.avg_return == pytest.approx(0.0)
    assert silver.avg_directional_return == pytest.approx(0.0)
    assert silver.avg_adverse_excursion == pytest.approx((120.0 / 110.0 - 1.0) * 100.0)
    assert silver.worst_adverse_excursion == silver.avg_adverse_excursion
    assert silver.adverse_3pct_rate == 1.0
    assert report["evaluation_basis"] == {
        "start": "state_date_close",
        "executable": False,
        "overlapping_daily_samples": True,
    }


def test_direction_state_evaluation_handles_empty_and_rejects_misalignment() -> None:
    split_date = date(2025, 7, 1)

    report = bt.evaluate_direction_states([], [], split_date=split_date)

    assert report["buckets"] == []
    assert report["rows"] == []
    assert report["runs"]["latest_direction"] == "NEUTRAL"
    with pytest.raises(ValueError, match="长度必须一致"):
        bt.evaluate_direction_states(["GOLD"], [], split_date=split_date)


def test_direction_state_split_boundary_and_run_statistics() -> None:
    bars = _bars([100.0 + index for index in range(10)])
    directions = [
        "NEUTRAL",
        "GOLD",
        "GOLD",
        "SILVER",
        "SILVER",
        "GOLD",
        "SILVER",
        "SILVER",
        "SILVER",
        "SILVER",
    ]
    split_date = bars[5].trade_date

    report = bt.evaluate_direction_states(directions, bars, split_date=split_date)

    early_gold = _state_bucket(report, "EARLY", "GOLD", 1)
    late_gold = _state_bucket(report, "LATE", "GOLD", 1)
    assert early_gold.count == 2
    assert early_gold.avg_return == pytest.approx(
        ((102.0 / 101.0 - 1.0) + (103.0 / 102.0 - 1.0)) * 50.0,
    )
    assert late_gold.count == 1
    assert late_gold.avg_return == pytest.approx((106.0 / 105.0 - 1.0) * 100.0)
    runs = report["runs"]
    assert runs["coverage_days"] == {"GOLD": 3, "SILVER": 6, "NEUTRAL": 1}
    assert runs["run_count"] == {"GOLD": 2, "SILVER": 2}
    assert runs["avg_run_days"] == {"GOLD": 1.5, "SILVER": 3.0}
    assert runs["short_run_count"] == {"GOLD": 2, "SILVER": 1}
    assert runs["transition_count"] == 3
    assert runs["latest_direction"] == "SILVER"


def test_volatility_hysteresis_switches_on_causal_trend_breakdown() -> None:
    bars = _bars(
        [100.0, 101.0, 100.5, 99.0, 98.0],
        [1.0, 1.0, 1.0, 0.0, 0.0],
    )
    factors = [_factor(bar.trade_date) for bar in bars]
    factors[3] = _factor(
        bars[3].trade_date,
        bull=50.0,
        bear=60.0,
        mom_5d=-1.0,
        above_ma20=False,
        trend_breakdown=70.0,
    )
    gold = _event(bars[0].trade_date, sig.STATUS_CONFIRMED, bars[1].trade_date)

    directions = bt.build_volatility_hysteresis_directions(factors, bars, [gold])

    assert directions == ["NEUTRAL", "GOLD", "GOLD", "SILVER", "SILVER"]


@pytest.mark.parametrize(
    "factor_change,up_ratio",
    [
        ({"bear_force": 49.0}, 0.0),
        ({"mom_5d": 0.0}, 0.0),
        ({}, None),
        ({}, 0.5),
    ],
)
def test_volatility_hysteresis_requires_broad_confirming_weakness(
    factor_change: dict,
    up_ratio: float | None,
) -> None:
    bars = _bars([100.0, 101.0, 100.5, 99.0], [1.0, 1.0, 1.0, up_ratio])
    factors = [_factor(bar.trade_date) for bar in bars]
    failure = _factor(
        bars[-1].trade_date,
        bull=50.0,
        bear=60.0,
        mom_5d=-1.0,
        above_ma20=False,
        trend_breakdown=70.0,
    )
    factors[-1] = replace(failure, **factor_change)
    gold = _event(bars[0].trade_date, sig.STATUS_CONFIRMED, bars[1].trade_date)

    directions = bt.build_volatility_hysteresis_directions(factors, bars, [gold])

    assert directions[-1] == "GOLD"


def test_volatility_hysteresis_shock_is_prefix_stable_and_confirmed_gold_recovers() -> None:
    closes = [100.0 * (1.001 ** index) for index in range(21)]
    closes.extend([closes[-1] * 0.97, closes[-1] * 0.965, closes[-1] * 0.98])
    up_ratios = [1.0] * 21 + [0.0, 0.0, 1.0]
    bars = _bars(closes, up_ratios)
    factors = [_factor(bar.trade_date) for bar in bars]
    shock_index = 21
    factors[shock_index] = _factor(
        bars[shock_index].trade_date,
        bull=50.0,
        bear=60.0,
        mom_5d=-2.0,
    )
    factors[shock_index + 1] = _factor(
        bars[shock_index + 1].trade_date,
        bull=48.0,
        bear=62.0,
        mom_5d=-3.0,
    )
    first_gold = _event(
        bars[0].trade_date,
        sig.STATUS_CONFIRMED,
        bars[1].trade_date,
    )
    recovery_gold = _event(
        bars[-2].trade_date,
        sig.STATUS_CONFIRMED,
        bars[-1].trade_date,
    )

    prefix = bt.build_volatility_hysteresis_directions(
        factors[: shock_index + 1],
        bars[: shock_index + 1],
        [first_gold],
    )
    complete = bt.build_volatility_hysteresis_directions(
        factors,
        bars,
        [first_gold, recovery_gold],
    )
    polluted_bars = bars[:-1] + [replace(bars[-1], close=bars[-1].close * 5.0)]
    polluted_factors = factors[:-1] + [
        replace(factors[-1], bull_force=0.0, bear_force=100.0)
    ]
    polluted = bt.build_volatility_hysteresis_directions(
        polluted_factors,
        polluted_bars,
        [first_gold, recovery_gold],
    )

    assert prefix[-1] == "SILVER"
    assert complete[: shock_index + 1] == prefix
    assert complete[-2] == "SILVER"
    assert complete[-1] == "GOLD"
    assert polluted[:-1] == complete[:-1]


@pytest.mark.parametrize(
    ("variant", "candidate_factor"),
    [
        (
            bt.RECOVERY_R1_REPAIR,
            {
                "bull": 50.0,
                "bear": 60.0,
                "mom_5d": -1.0,
                "above_ma20": False,
            },
        ),
        (
            bt.RECOVERY_R2_BULL_CROSS,
            {
                "bull": 60.0,
                "bear": 50.0,
                "mom_5d": 1.0,
                "above_ma20": False,
            },
        ),
        (
            bt.RECOVERY_R3_MA20,
            {
                "bull": 60.0,
                "bear": 50.0,
                "mom_5d": 1.0,
                "above_ma20": True,
            },
        ),
    ],
)
def test_recovery_gold_variants_confirm_only_after_broad_follow_through(
    variant: str,
    candidate_factor: dict[str, float | bool],
) -> None:
    factors, bars, silver = _recovery_case(candidate_factor=candidate_factor)

    result = bt.build_recovery_gold_state(
        factors,
        bars,
        [silver],
        variant=variant,
    )

    assert len(result["events"]) == 1
    event = result["events"][0]
    assert (event.trade_date, event.confirm_date, event.status) == (
        bars[5].trade_date,
        bars[6].trade_date,
        sig.STATUS_CONFIRMED,
    )
    assert event.setup_type == bt.SETUP_RECOVERY_GOLD
    assert result["directions"][0] == "NEUTRAL"
    assert result["directions"][1:6] == ["SILVER"] * 5
    assert result["directions"][6:] == ["GOLD"] * 2


@pytest.mark.parametrize(
    "case",
    ["down_close", "missing_participation", "bear_still_dominant"],
)
def test_recovery_gold_confirmation_fails_closed(case: str) -> None:
    kwargs: dict[str, object] = {}
    if case == "down_close":
        kwargs["confirmation_close"] = 97.0
    elif case == "missing_participation":
        kwargs["confirmation_up_ratio"] = None
    else:
        kwargs["confirmation_bull"] = 49.0
        kwargs["confirmation_bear"] = 60.0
    factors, bars, silver = _recovery_case(**kwargs)

    result = bt.build_recovery_gold_state(
        factors,
        bars,
        [silver],
        variant=bt.RECOVERY_R2_BULL_CROSS,
    )

    assert len(result["events"]) == 1
    assert result["events"][0].status == sig.STATUS_INVALIDATED
    assert result["directions"][-1] == "SILVER"


def test_recovery_gold_rejects_invalid_inputs() -> None:
    factors, bars, silver = _recovery_case()

    with pytest.raises(ValueError, match="unknown recovery variant"):
        bt.build_recovery_gold_state(factors, bars, [silver], variant="UNKNOWN")
    with pytest.raises(ValueError, match="长度必须一致"):
        bt.build_recovery_gold_state(
            factors[:-1],
            bars,
            [silver],
            variant=bt.RECOVERY_R2_BULL_CROSS,
        )
    misaligned = factors.copy()
    misaligned[-1] = replace(misaligned[-1], trade_date=bars[-2].trade_date)
    with pytest.raises(ValueError, match="日期必须对齐"):
        bt.build_recovery_gold_state(
            misaligned,
            bars,
            [silver],
            variant=bt.RECOVERY_R2_BULL_CROSS,
        )


def test_recovery_gold_emits_once_per_continuous_zone_and_allows_reentry() -> None:
    bars = _bars(
        [100.0, 99.0, 98.0, 97.0, 96.0, 98.0, 98.0, 99.0, 97.0, 99.0, 100.0],
        [0.1, 0.1, 0.1, 0.1, 0.1, 0.6, 0.6, 0.6, 0.1, 0.6, 0.6],
    )
    factors = [
        _factor(
            bar.trade_date,
            bull=40.0,
            bear=70.0,
            mom_5d=-1.0,
            above_ma20=False,
        )
        for bar in bars
    ]
    for index in (5, 6, 7, 9, 10):
        factors[index] = _factor(
            bars[index].trade_date,
            bull=60.0,
            bear=50.0,
            mom_5d=1.0,
            above_ma20=False,
        )
    silver = _silver_event(bars[0].trade_date, bars[1].trade_date)

    result = bt.build_recovery_gold_state(
        factors,
        bars,
        [silver],
        variant=bt.RECOVERY_R2_BULL_CROSS,
    )

    assert [event.trade_date for event in result["events"]] == [
        bars[5].trade_date,
        bars[9].trade_date,
    ]
    assert [event.status for event in result["events"]] == [
        sig.STATUS_INVALIDATED,
        sig.STATUS_CONFIRMED,
    ]


def test_recovery_gold_respects_base_event_priority() -> None:
    factors, bars, first_silver = _recovery_case()
    second_silver = _silver_event(bars[5].trade_date, bars[6].trade_date)

    silver_priority = bt.build_recovery_gold_state(
        factors,
        bars,
        [first_silver, second_silver],
        variant=bt.RECOVERY_R2_BULL_CROSS,
    )

    assert silver_priority["events"][0].status == sig.STATUS_INVALIDATED
    assert silver_priority["directions"][6] == "SILVER"

    base_gold = _event(
        bars[4].trade_date,
        sig.STATUS_CONFIRMED,
        bars[5].trade_date,
    )
    gold_priority = bt.build_recovery_gold_state(
        factors,
        bars,
        [first_silver, base_gold],
        variant=bt.RECOVERY_R2_BULL_CROSS,
    )

    assert gold_priority["events"] == []
    assert gold_priority["directions"][5:] == ["GOLD"] * 3


@pytest.mark.parametrize("starting_direction", ["NEUTRAL", "GOLD"])
def test_recovery_gold_only_triggers_while_silver(starting_direction: str) -> None:
    factors, bars, _ = _recovery_case()
    events = (
        []
        if starting_direction == "NEUTRAL"
        else [
            _event(
                bars[0].trade_date,
                sig.STATUS_CONFIRMED,
                bars[1].trade_date,
            )
        ]
    )

    result = bt.build_recovery_gold_state(
        factors,
        bars,
        events,
        variant=bt.RECOVERY_R2_BULL_CROSS,
    )

    assert result["events"] == []
    assert result["directions"][-1] == starting_direction


def test_recovery_gold_candidate_is_prefix_stable_and_future_safe() -> None:
    factors, bars, silver = _recovery_case()

    prefix = bt.build_recovery_gold_state(
        factors[:6],
        bars[:6],
        [silver],
        variant=bt.RECOVERY_R2_BULL_CROSS,
    )
    complete = bt.build_recovery_gold_state(
        factors,
        bars,
        [silver],
        variant=bt.RECOVERY_R2_BULL_CROSS,
    )
    polluted_factors = factors[:-1] + [
        replace(factors[-1], bull_force=0.0, bear_force=100.0, mom_5d=-99.0)
    ]
    polluted_bars = bars[:-1] + [
        replace(bars[-1], close=bars[-1].close * 5.0, up_ratio=0.0)
    ]
    polluted = bt.build_recovery_gold_state(
        polluted_factors,
        polluted_bars,
        [silver],
        variant=bt.RECOVERY_R2_BULL_CROSS,
    )

    assert len(prefix["events"]) == 1
    assert prefix["events"][0].status == sig.STATUS_PENDING
    assert prefix["events"][0].confirm_date is None
    assert complete["events"][0].trade_date == prefix["events"][0].trade_date
    assert complete["events"][0].status == sig.STATUS_CONFIRMED
    assert complete["directions"][:6] == prefix["directions"]
    assert polluted["events"] == complete["events"]
    assert polluted["directions"][:-1] == complete["directions"][:-1]


def test_recovery_gold_run_evaluation_classifies_outcomes() -> None:
    bars = _bars(
        [
            100.0,
            99.0,
            98.0,
            100.0,
            102.0,
            104.0,
            106.0,
            108.0,
            110.0,
            109.0,
            108.0,
            109.0,
            110.0,
            108.0,
            106.0,
            104.0,
            102.0,
            100.0,
            101.0,
            100.0,
            99.0,
            100.0,
            101.0,
            102.0,
            103.0,
        ]
    )
    base_directions = (
        ["NEUTRAL"]
        + ["SILVER"] * 6
        + ["GOLD"] * 3
        + ["SILVER"] * 8
        + ["GOLD"]
        + ["SILVER"] * 6
    )
    recovery_events = [
        replace(
            _event(
                bars[candidate].trade_date,
                sig.STATUS_CONFIRMED,
                bars[confirm].trade_date,
            ),
            setup_type=bt.SETUP_RECOVERY_GOLD,
        )
        for candidate, confirm in ((2, 3), (11, 12), (21, 22))
    ]

    rows = bt.evaluate_recovery_gold_runs(
        base_directions,
        recovery_events,
        bars,
    )

    assert [row["outcome"] for row in rows] == [
        "IMPROVED",
        "FALSE_RECOVERY",
        "IMMATURE",
    ]
    assert [row["advanced_days"] for row in rows] == [4, 6, 3]
    assert rows[0]["return_5d"] == pytest.approx(10.0)
    assert rows[1]["return_5d"] == pytest.approx((100.0 / 110.0 - 1.0) * 100.0)
    assert rows[2]["return_5d"] is None
    assert rows[2]["open_run"] is True


def test_silver_run_leave_one_out_uses_only_remaining_runs() -> None:
    bars = _bars([100.0 + index for index in range(20)])
    base_directions = (
        ["NEUTRAL"]
        + ["SILVER"] * 3
        + ["GOLD"] * 4
        + ["SILVER"] * 5
        + ["GOLD"] * 7
    )
    candidate_directions = (
        ["NEUTRAL", "SILVER"]
        + ["GOLD"] * 6
        + ["SILVER"] * 2
        + ["GOLD"] * 10
    )

    rows = bt.evaluate_silver_run_leave_one_out(
        base_directions,
        candidate_directions,
        bars,
    )

    assert [
        (row["omitted_start"], row["omitted_end"])
        for row in rows
    ] == [
        (bars[1].trade_date, bars[3].trade_date),
        (bars[8].trade_date, bars[12].trade_date),
    ]
    assert [(row["base_count"], row["candidate_count"]) for row in rows] == [
        (5, 2),
        (3, 1),
    ]
    assert all(row["base_hit_rate"] == 0.0 for row in rows)
    assert all(row["candidate_hit_rate"] == 0.0 for row in rows)
    assert all(row["base_adverse_3pct_rate"] == 1.0 for row in rows)
    assert all(row["candidate_adverse_3pct_rate"] == 1.0 for row in rows)
