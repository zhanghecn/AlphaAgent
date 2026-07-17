from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.daily_phase_study import (
    PHASES,
    PHASE_PRECEDENCE,
    build_daily_phase_attribution_metrics,
    build_daily_phase_metrics,
    build_daily_phase_panel,
    build_daily_phase_report,
    build_daily_phase_trade_ledger,
    classify_daily_phase,
    classify_phase_baseline,
    classify_relative_strength,
    classify_volume_ratio,
    evaluate_daily_phase_candidates,
    execute_daily_phase_holds,
    render_daily_phase_json,
)


def _calendar() -> tuple[date, ...]:
    start = date(2025, 1, 2)
    return tuple(start + timedelta(days=index) for index in range(45))


def _candidates() -> pd.DataFrame:
    calendar = _calendar()
    rows = []
    for symbol, stock_name, sector_id in (
        ("600001.SSE", "甲公司", "BK0001"),
        ("000001.SZSE", "乙公司", "BK0001"),
        ("300001.SZSE", "创业板公司", "BK0002"),
    ):
        for offset in (1, 2, 3, 4, 5):
            context_position = 24 + offset
            rows.append(
                {
                    "event_id": len(rows) + 1,
                    "recognition_event_id": 100 + len(rows),
                    "leader_spell_id": f"{sector_id}:cycle-a:{symbol}",
                    "recognition_source_date": calendar[25],
                    "context_date": calendar[context_position],
                    "source_date": calendar[context_position + 1],
                    "entry_date": calendar[context_position + 1],
                    "planned_exit_date": calendar[context_position + 2],
                    "sector_id": sector_id,
                    "concept_name": "测试概念",
                    "cycle_id": "cycle-a",
                    "vt_symbol": symbol,
                    "stock_name": stock_name,
                    "recognition_rank": 1,
                    "cycle_relative_percentile": 0.9,
                    "spell_session_offset": offset,
                    "signal_close": 12.0,
                    "previous_high": 12.2,
                    "ma5": 11.8,
                    "ma10": 11.5,
                    "active_direction": "GOLD",
                    "danger_state": "NORMAL",
                    "market_phase": "warming",
                    "main_rise": True,
                    "is_top3": True,
                    "rank_mode": "event_recognition_proxy",
                    "evidence_level": "event_recognition_neutral_day_falsification",
                }
            )
    return pd.DataFrame(rows)


def _stock_bars() -> pd.DataFrame:
    rows = []
    for symbol, slope in (
        ("600001.SSE", 0.08),
        ("000001.SZSE", 0.05),
        ("300001.SZSE", 0.1),
    ):
        for position, trade_date in enumerate(_calendar()):
            close = 10.0 + position * slope
            rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "open_price": close - 0.03,
                    "high_price": close + 0.12,
                    "low_price": close - 0.12,
                    "close_price": close,
                    "volume": 100_000.0 + position * 1_000.0,
                }
            )
    return pd.DataFrame(rows)


def _concept_bars() -> pd.DataFrame:
    rows = []
    for sector_id, slope in (("BK0001", 0.4), ("BK0002", 0.2)):
        for position, trade_date in enumerate(_calendar()):
            rows.append(
                {
                    "sector_id": sector_id,
                    "trade_date": trade_date,
                    "close_price": 100.0 + position * slope,
                }
            )
    return pd.DataFrame(rows)


def _market_returns() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": _calendar(),
            "market_daily_return": [0.001] * len(_calendar()),
        }
    )


def _phase_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "phase_feature_complete": True,
        "main_rise": True,
        "stock_close": 12.0,
        "ma5": 11.8,
        "ma10": 11.5,
        "ma20": 11.0,
        "stock_daily_return_pct": 1.0,
        "current_near_limit_up": False,
        "previous_near_limit_up": False,
        "consecutive_near_limit_up_days": 0,
        "prior_near_limit_up_days_5d": 0,
        "prior_near_limit_up_days_10d": 0,
        "volume_to_prior_5d_ratio": 1.0,
    }
    values.update(overrides)
    return values


def _execution_panel() -> pd.DataFrame:
    context_date = _calendar()[25]
    return pd.DataFrame(
        [
            {
                "event_id": "phase-a",
                "leader_spell_id": "BK0001:cycle-a:600001.SSE",
                "recognition_source_date": context_date,
                "context_date": context_date,
                "entry_date": _calendar()[26],
                "planned_exit_date": _calendar()[27],
                "vt_symbol": "600001.SSE",
                "stock_name": "甲公司",
                "sector_id": "BK0001",
                "concept_name": "测试概念",
                "phase": "trend_continuation",
                "volume_class": "normal",
                "relative_strength_state": "improving_positive",
                "market_regime": "GOLD/NORMAL",
                "block": 1,
                "evidence_level": "event_recognition_daily_phase_hold_study",
            }
        ]
    )


def _metric_trades() -> pd.DataFrame:
    rows = []
    start = date(2025, 1, 1)
    for index in range(50):
        block = index // 10 + 1
        winning = index % 3 != 0
        normal_return = 1.2 if winning else -0.8
        rows.append(
            {
                "event_id": f"trade-{index}",
                "leader_spell_id": f"spell-{index // 2}",
                "phase": "divergence_restart",
                "entry_date": start + timedelta(days=index),
                "vt_symbol": f"600{index % 10:03d}.SSE",
                "sector_id": f"BK{index % 8:04d}",
                "concept_name": f"概念{index % 8}",
                "block": block,
                "normal_status": "closed",
                "stressed_status": "closed",
                "net_return_pct": normal_return,
                "double_cost_net_return_pct": normal_return - 0.2,
                "volume_class": ("contraction" if index % 2 else "normal"),
                "relative_strength_state": (
                    "improving_positive" if index % 2 else "non_positive"
                ),
                "market_regime": "GOLD/NORMAL" if block <= 3 else "SILVER/NORMAL",
            }
        )
    return pd.DataFrame(rows)


def test_daily_phase_panel_is_causal_main_board_and_bounded() -> None:
    candidates = _candidates()
    one_context = candidates.loc[
        candidates["spell_session_offset"].eq(1)
        & candidates["vt_symbol"].eq("600001.SSE")
    ]
    baseline = build_daily_phase_panel(
        one_context,
        _stock_bars(),
        _concept_bars(),
        _market_returns(),
        trading_dates=_calendar(),
    )
    stock_bars = _stock_bars()
    cutoff = one_context.iloc[0]["context_date"]
    stock_bars.loc[
        pd.to_datetime(stock_bars["trade_date"]).dt.date > cutoff,
        ["open_price", "high_price", "low_price", "close_price", "volume"],
    ] = [999.0, 999.0, 0.1, 999.0, 999_999.0]
    changed = build_daily_phase_panel(
        one_context,
        stock_bars,
        _concept_bars(),
        _market_returns(),
        trading_dates=_calendar(),
    )

    pd.testing.assert_frame_equal(baseline, changed)

    full = build_daily_phase_panel(
        candidates,
        _stock_bars(),
        _concept_bars(),
        _market_returns(),
        trading_dates=_calendar(),
    )
    assert full["spell_session_offset"].between(1, 4).all()
    assert full["event_id"].is_unique
    assert not full["vt_symbol"].str.startswith(("300", "301", "688", "689")).any()
    assert set(full["phase"]).issubset(PHASES)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (_phase_values(phase_feature_complete=False), "unclassified"),
        (
            _phase_values(
                main_rise=False,
                current_near_limit_up=True,
                consecutive_near_limit_up_days=3,
            ),
            "decay",
        ),
        (
            _phase_values(
                current_near_limit_up=True,
                consecutive_near_limit_up_days=3,
            ),
            "climax_risk",
        ),
        (
            _phase_values(
                current_near_limit_up=True,
                previous_near_limit_up=True,
                consecutive_near_limit_up_days=2,
                prior_near_limit_up_days_10d=1,
            ),
            "continuous_acceleration",
        ),
        (
            _phase_values(
                current_near_limit_up=True,
                consecutive_near_limit_up_days=1,
                prior_near_limit_up_days_10d=1,
            ),
            "divergence_restart",
        ),
        (
            _phase_values(
                current_near_limit_up=True,
                consecutive_near_limit_up_days=1,
                prior_near_limit_up_days_10d=0,
            ),
            "first_launch",
        ),
        (
            _phase_values(
                stock_daily_return_pct=-1.0,
                prior_near_limit_up_days_5d=1,
                volume_to_prior_5d_ratio=0.79,
            ),
            "healthy_pullback",
        ),
        (_phase_values(), "trend_continuation"),
        (_phase_values(stock_close=11.4), "decay"),
    ],
)
def test_daily_phase_precedence(values: dict[str, object], expected: str) -> None:
    phase, reason = classify_daily_phase(values)

    assert phase == expected
    assert reason


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        (0.7999, "contraction"),
        (0.8, "normal"),
        (1.4999, "normal"),
        (1.5, "expansion"),
        (2.4999, "expansion"),
        (2.5, "explosion"),
        (None, "missing"),
    ],
)
def test_daily_volume_boundaries_are_frozen(ratio: object, expected: str) -> None:
    assert classify_volume_ratio(ratio) == expected


@pytest.mark.parametrize(
    ("excess", "change", "expected"),
    [
        (1.0, 0.1, "improving_positive"),
        (1.0, 0.0, "positive_not_improving"),
        (0.0, 1.0, "non_positive"),
        (-0.1, 1.0, "non_positive"),
        (None, 1.0, "missing"),
    ],
)
def test_relative_strength_boundaries_are_frozen(
    excess: object,
    change: object,
    expected: str,
) -> None:
    assert classify_relative_strength(excess, change) == expected


def test_daily_phase_hold_uses_next_open_and_following_close() -> None:
    normal, stressed = execute_daily_phase_holds(
        _execution_panel(),
        _stock_bars(),
        trading_dates=_calendar(),
    )

    assert normal.iloc[0]["entry_date"] == pd.Timestamp(_calendar()[26])
    assert normal.iloc[0]["exit_date"] == pd.Timestamp(_calendar()[27])
    assert stressed.iloc[0]["net_return_pct"] < normal.iloc[0]["net_return_pct"]

    ledger = build_daily_phase_trade_ledger(
        _execution_panel(), normal, stressed
    )
    assert ledger.iloc[0]["stock_name"] == "甲公司"
    assert ledger.iloc[0]["normal_status"] == "closed"
    assert ledger.iloc[0]["double_cost_net_return_pct"] < ledger.iloc[0]["net_return_pct"]


def test_daily_phase_hold_rejects_limit_up_open() -> None:
    bars = _stock_bars()
    previous_close = bars.loc[
        bars["vt_symbol"].eq("600001.SSE")
        & pd.to_datetime(bars["trade_date"]).dt.date.eq(_calendar()[25]),
        "close_price",
    ].item()
    entry_mask = bars["vt_symbol"].eq("600001.SSE") & pd.to_datetime(
        bars["trade_date"]
    ).dt.date.eq(_calendar()[26])
    bars.loc[entry_mask, "open_price"] = previous_close * 1.10

    normal, _ = execute_daily_phase_holds(
        _execution_panel(),
        bars,
        trading_dates=_calendar(),
    )

    assert normal.iloc[0]["status"] == "rejected"
    assert normal.iloc[0]["reason"] == "entry_at_limit_up"


def test_phase_baseline_gate_is_strict_and_cost_aware() -> None:
    passing = {
        "closed_trades": 30,
        "source_days": 20,
        "win_rate_pct": 60.0001,
        "mean_net_return_pct": 0.1,
        "profit_factor": 1.01,
        "double_cost_mean_net_return_pct": 0.01,
    }

    assert classify_phase_baseline(passing) == "high_win_candidate"
    assert classify_phase_baseline({**passing, "win_rate_pct": 60.0}) == "positive_candidate"
    assert classify_phase_baseline(
        {**passing, "double_cost_mean_net_return_pct": 0.0}
    ) == "not_positive_candidate"
    assert classify_phase_baseline({**passing, "closed_trades": 29}) == "insufficient_sample"


def test_phase_metrics_are_stable_under_input_shuffle() -> None:
    trades = _metric_trades()
    baseline = build_daily_phase_metrics(trades)
    shuffled = build_daily_phase_metrics(trades.sample(frac=1, random_state=7))

    pd.testing.assert_frame_equal(baseline, shuffled)
    assert set(baseline["segment"]) == {
        "all",
        "early_1_3",
        "late_4_5",
        "block_1",
        "block_2",
        "block_3",
        "block_4",
        "block_5",
    }

    attribution = build_daily_phase_attribution_metrics(trades)
    assert set(attribution["dimension"]) == {
        "volume_class",
        "relative_strength_state",
        "market_regime",
    }


def test_phase_candidate_requires_both_segments_blocks_and_concentration() -> None:
    rows = []
    for segment in (
        "all",
        "early_1_3",
        "late_4_5",
        "block_1",
        "block_2",
        "block_3",
        "block_4",
        "block_5",
    ):
        rows.append(
            {
                "phase": "divergence_restart",
                "segment": segment,
                "mean_net_return_pct": 0.5,
                "profit_factor": 1.5,
                "baseline_label": "high_win_candidate",
                "maximum_stock_positive_profit_share_pct": 19.0,
                "maximum_concept_positive_profit_share_pct": 19.0,
                "maximum_month_positive_profit_share_pct": 19.0,
            }
        )
    metrics = pd.DataFrame(rows)

    evaluated = evaluate_daily_phase_candidates(metrics)

    assert bool(evaluated.iloc[0]["stable_high_win_candidate"])
    assert evaluated.iloc[0]["positive_blocks"] == 5

    concentrated = metrics.copy()
    concentrated.loc[concentrated["segment"].eq("all"), "maximum_stock_positive_profit_share_pct"] = 20.0001
    rejected = evaluate_daily_phase_candidates(concentrated)
    assert not bool(rejected.iloc[0]["stable_high_win_candidate"])


def test_daily_phase_report_keeps_real_trades_and_closes_formal_surfaces() -> None:
    trades = _metric_trades()
    metrics = build_daily_phase_metrics(trades)
    attribution = build_daily_phase_attribution_metrics(trades)
    candidates = evaluate_daily_phase_candidates(metrics)
    report = build_daily_phase_report(
        pd.DataFrame(
            {
                "phase": trades["phase"],
                "vt_symbol": trades["vt_symbol"],
                "event_id": trades["event_id"],
            }
        ),
        trades,
        metrics,
        attribution,
        candidates,
        {},
    )

    assert report["formal_metrics"] is None
    assert report["formal_rule_selected"] is False
    assert report["strict_top3_claim"] is False
    assert report["individual_phase_trades"][0]["vt_symbol"].startswith("600")
    assert "individual_phase_trades" in render_daily_phase_json(report)
    assert PHASE_PRECEDENCE[:3] == (
        "incomplete_history",
        "decay",
        "climax_risk",
    )
    report["best_20_trades"] = [{"actual_exit_date": pd.NaT}]
    assert '"actual_exit_date": null' in render_daily_phase_json(report)


def test_cli_registers_frozen_daily_phase_study() -> None:
    args = build_parser().parse_args(["v2-daily-phase-study"])

    assert args.command == "v2-daily-phase-study"
    assert args.format == "markdown"
    assert set(vars(args)) == {"command", "format", "output"}
