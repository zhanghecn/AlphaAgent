from __future__ import annotations

import pandas as pd
import pytest

from alphaagent.server.services.low_suction import causal_leader_pullback
from alphaagent.server.services.low_suction.causal_leader_pullback import (
    ALGORITHM_VERSION,
    EXACT_REQUIRED_SUPPORT,
    MINIMUM_REQUIRED_SUPPORT,
    execute_close_trades,
    execute_prepared_close_trades,
    explain_warming_support_relevance_signal,
    prepare_stock_campaigns,
    rank_campaign_leaders,
    replay_stock_campaign,
    replay_stock_campaigns,
    select_cross_regime_support_reclaim_signals,
    select_gold_strong_reclaim_signals,
    select_rotation_next_session_signals,
    select_three_phase_adaptive_signals,
    select_warming_support_relevance_signals,
    summarize_trade_metrics,
)


def test_dynamic_rank_uses_visible_campaign_leadership() -> None:
    rows = pd.DataFrame(
        [
            _rank_row("600001.SSE", 18.0, 3, 11.0, 1.4),
            _rank_row("600002.SSE", 15.0, 4, 10.0, 1.8),
            _rank_row("600003.SSE", 12.0, 2, 9.0, 1.2),
            _rank_row("600004.SSE", 11.0, 5, 10.5, 2.0),
            {
                **_rank_row("600005.SSE", 99.0, 8, 80.0, 5.0),
                "ignited_in_campaign": False,
            },
        ]
    )

    ranked = rank_campaign_leaders(rows)

    top3 = ranked.loc[ranked["dynamic_top3"]].sort_values("dynamic_rank")
    assert top3["vt_symbol"].tolist() == [
        "600001.SSE",
        "600002.SSE",
        "600003.SSE",
    ]
    assert ranked.loc[ranked["vt_symbol"].eq("600005.SSE"), "dynamic_rank"].isna().all()
    assert ranked["rank_feature_cutoff_date"].eq(pd.Timestamp("2026-01-15")).all()


def test_dynamic_rank_rejects_future_or_outcome_columns() -> None:
    rows = pd.DataFrame([_rank_row("600001.SSE", 18.0, 3, 11.0, 1.4)])

    with pytest.raises(ValueError, match="future or outcome"):
        rank_campaign_leaders(rows.assign(future_return_pct=99.0))


def test_first_pullback_waits_for_ma5_weak_to_strong_close() -> None:
    replay = replay_stock_campaign(pd.DataFrame(_first_wave_rows()))

    assert ALGORITHM_VERSION == "causal-leader-pullback-close-v2"
    assert replay.signals["signal_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2025-06-26"
    ]
    signal = replay.signals.iloc[0]
    assert signal["wave_number"] == 1
    assert signal["required_support"] == "ma5"
    assert signal["support_line"] == "ma5"
    assert signal["reference_peak_price"] == pytest.approx(11.0)
    assert bool(signal["dynamic_top3"])


def test_pullback_ledger_explains_when_confirmation_is_not_dynamic_top3() -> None:
    rows = _first_wave_rows()
    rows[4]["dynamic_rank"] = 4
    rows[4]["dynamic_top3"] = False

    replay = replay_stock_campaign(pd.DataFrame(rows))

    confirmation_day = replay.daily_ledger.loc[
        replay.daily_ledger["trade_date"].eq(pd.Timestamp("2025-06-26"))
    ].iloc[0]
    assert replay.signals["signal_date"].tolist() == [pd.Timestamp("2025-06-27")]
    assert confirmation_day["confirmation_status"] == "not_dynamic_top3"
    assert confirmation_day["required_support"] == "ma5"
    assert confirmation_day["latest_support_test_date"] == pd.Timestamp("2025-06-25")


def test_second_pullback_waits_for_ma10_after_a_higher_high() -> None:
    rows = _second_wave_rows()

    replay = replay_stock_campaign(pd.DataFrame(rows))

    assert replay.signals["signal_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2025-06-26",
        "2025-07-03",
    ]
    assert replay.signals["required_support"].tolist() == ["ma5", "ma10"]
    assert replay.signals["wave_number"].tolist() == [1, 2]


def test_first_wave_exact_support_rejects_a_pullback_that_reaches_ma10() -> None:
    rows = _first_wave_rows()
    rows[2].update(low_price=10.00, ma5=10.35, ma10=10.02, ma20=9.50)
    rows[3].update(ma10=10.05, ma20=9.55)
    rows[4].update(ma10=10.10, ma20=9.60)

    minimum = replay_stock_campaign(
        pd.DataFrame(rows), support_match_mode=MINIMUM_REQUIRED_SUPPORT
    )
    exact = replay_stock_campaign(
        pd.DataFrame(rows), support_match_mode=EXACT_REQUIRED_SUPPORT
    )

    assert minimum.signals["required_support"].tolist() == ["ma5"]
    assert minimum.signals["support_line"].tolist() == ["ma10"]
    assert exact.signals.empty


def test_later_wave_exact_support_accepts_ma10_but_rejects_ma20() -> None:
    ma10 = replay_stock_campaign(
        pd.DataFrame(_second_wave_rows()),
        support_match_mode=EXACT_REQUIRED_SUPPORT,
    )
    ma20_rows = _second_wave_rows()
    ma20_rows[8].update(low_price=10.10, ma20=10.12)
    ma20_rows[9].update(ma20=10.15)
    ma20 = replay_stock_campaign(
        pd.DataFrame(ma20_rows),
        support_match_mode=EXACT_REQUIRED_SUPPORT,
    )

    assert ma10.signals["required_support"].tolist() == ["ma5", "ma10"]
    assert ma10.signals["support_line"].tolist() == ["ma5", "ma10"]
    assert ma20.signals["support_line"].tolist() == ["ma5"]


def test_replay_rejects_an_unknown_support_match_mode() -> None:
    with pytest.raises(ValueError, match="unsupported support match mode"):
        replay_stock_campaign(
            pd.DataFrame(_first_wave_rows()),
            support_match_mode="future_best_support",
        )


def test_batch_replay_is_identical_to_individual_campaign_replays() -> None:
    first = pd.DataFrame(_first_wave_rows())
    second = first.assign(
        campaign_id="campaign-2",
        sector_id="BK0002",
        concept_name="第二概念",
        vt_symbol="600002.SSE",
        stock_name="第二股份",
    )
    combined = pd.concat([first, second], ignore_index=True)

    batch = replay_stock_campaigns(combined)
    expected_signals = (
        pd.concat(
            [
                replay_stock_campaign(first).signals,
                replay_stock_campaign(second).signals,
            ],
            ignore_index=True,
        )
        .sort_values("signal_id", kind="stable")
        .reset_index(drop=True)
    )
    expected_trades = (
        pd.concat(
            [
                replay_stock_campaign(first).trades,
                replay_stock_campaign(second).trades,
            ],
            ignore_index=True,
        )
        .sort_values("signal_id", kind="stable")
        .reset_index(drop=True)
    )

    pd.testing.assert_frame_equal(
        batch.signals.sort_values("signal_id", kind="stable").reset_index(drop=True),
        expected_signals,
    )
    pd.testing.assert_frame_equal(
        batch.trades.sort_values("signal_id", kind="stable").reset_index(drop=True),
        expected_trades,
    )
    assert batch.daily_ledger.groupby(
        ["campaign_id", "vt_symbol"], sort=False
    ).size().tolist() == [len(first), len(second)]


def test_campaign_preparation_does_not_execute_trades(monkeypatch) -> None:
    def fail_if_executed(*_args, **_kwargs):
        raise AssertionError("campaign preparation must not execute trades")

    monkeypatch.setattr(
        causal_leader_pullback,
        "_execute_prepared_close_trades",
        fail_if_executed,
    )

    prepared = prepare_stock_campaigns(pd.DataFrame(_first_wave_rows()))

    assert prepared.signals["signal_date"].tolist() == [pd.Timestamp("2025-06-26")]
    assert len(prepared.daily_ledger) == len(_first_wave_rows())
    assert prepared.paths["trade_date"].is_monotonic_increasing


def test_campaign_replay_reuses_the_prepared_state() -> None:
    paths = pd.DataFrame(_second_wave_rows())

    prepared = prepare_stock_campaigns(paths)
    replay = replay_stock_campaigns(paths)

    pd.testing.assert_frame_equal(replay.signals, prepared.signals)
    pd.testing.assert_frame_equal(replay.daily_ledger, prepared.daily_ledger)


def test_prepared_trade_execution_does_not_prepare_paths_again(monkeypatch) -> None:
    prepared = prepare_stock_campaigns(pd.DataFrame(_first_wave_rows()))

    def fail_if_prepared_again(*_args, **_kwargs):
        raise AssertionError("prepared paths must be reused")

    monkeypatch.setattr(
        causal_leader_pullback,
        "_prepare_campaign_paths",
        fail_if_prepared_again,
    )

    trades = execute_prepared_close_trades(prepared.signals, prepared)

    assert trades["signal_id"].tolist() == prepared.signals["signal_id"].tolist()


def test_d1_loss_exit_only_allows_a_deeper_same_wave_reentry() -> None:
    rows = [
        _bar("2026-01-15", 9.80, 10.20, 9.75, 10.10, ignition=True),
        _bar("2026-01-16", 10.10, 10.50, 10.00, 10.40),
        _bar("2026-01-19", 10.20, 10.25, 9.90, 10.00, ma5=9.95, ma10=9.65),
        _bar("2026-01-20", 10.00, 10.20, 9.90, 10.15, ma5=10.00, ma10=9.70),
        _bar("2026-01-21", 10.10, 10.15, 9.70, 9.90, ma5=9.98, ma10=9.72),
        _bar("2026-01-22", 9.88, 10.02, 9.76, 9.95, ma5=9.96, ma10=9.74),
        _bar("2026-01-23", 9.75, 9.90, 9.50, 9.70, ma5=9.90, ma10=9.55),
        _bar("2026-01-26", 9.72, 10.05, 9.55, 9.98, ma5=9.86, ma10=9.58),
        _bar("2026-01-27", 9.98, 10.20, 9.90, 10.10, ma5=9.88, ma10=9.62),
        _bar("2026-01-28", 10.15, 10.60, 10.10, 10.50, ma5=10.00, ma10=9.70),
    ]
    replay = replay_stock_campaign(pd.DataFrame(rows))

    assert replay.signals["support_line"].tolist() == ["ma5", "ma10", "ma10"]
    assert replay.signals["support_depth"].tolist() == [1, 2, 2]
    assert replay.signals["support_test_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-01-19",
        "2026-01-21",
        "2026-01-23",
    ]
    assert replay.trades["entry_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-01-20",
        "2026-01-26",
    ]
    assert replay.trades.iloc[0]["exit_reason"] == "d1_loss_stop"
    assert replay.trades.iloc[0]["net_return_pct"] < 0
    assert replay.trades.iloc[1]["exit_reason"] == "higher_high_confirmed"


def test_non_contraction_is_a_declared_filter_not_a_different_signal_rule() -> None:
    replay = replay_stock_campaign(pd.DataFrame(_first_wave_rows()))
    signal = replay.signals.iloc[0]

    assert signal["base_confirmation"]
    assert not signal["non_contraction_confirmation"]
    assert signal["volume_ratio_prior5"] == pytest.approx(0.7)


def test_gold_strong_reclaim_requires_all_causal_entry_boundaries() -> None:
    signal = (
        replay_stock_campaign(pd.DataFrame(_first_wave_rows())).signals.iloc[[0]].copy()
    )
    signal["signal_daily_return_pct"] = 8.0
    signal["signal_close"] = 95.0
    signal["reference_peak_price"] = 100.0
    signal["support_test_session_gap"] = 2
    signal["active_direction"] = "GOLD"
    signal["danger_state"] = "NORMAL"
    signal["market_timing_feature_cutoff_date"] = signal["signal_date"]

    selected = select_gold_strong_reclaim_signals(signal)

    assert selected["signal_id"].tolist() == signal["signal_id"].tolist()
    rejected = (
        signal.assign(signal_daily_return_pct=7.99),
        signal.assign(signal_close=94.99),
        signal.assign(support_test_session_gap=3),
        signal.assign(active_direction="SILVER"),
        signal.assign(danger_state="DANGER"),
    )
    assert all(select_gold_strong_reclaim_signals(rows).empty for rows in rejected)


def test_gold_strong_reclaim_rejects_late_market_timing_context() -> None:
    signal = (
        replay_stock_campaign(pd.DataFrame(_first_wave_rows())).signals.iloc[[0]].copy()
    )
    signal["support_test_session_gap"] = 1
    signal["active_direction"] = "GOLD"
    signal["danger_state"] = "NORMAL"
    signal["market_timing_feature_cutoff_date"] = pd.Timestamp("2025-06-27")

    with pytest.raises(ValueError, match="market timing cutoff"):
        select_gold_strong_reclaim_signals(signal)


def test_cross_regime_support_reclaim_routes_only_rotation_and_warming() -> None:
    signal = (
        replay_stock_campaign(pd.DataFrame(_first_wave_rows())).signals.iloc[[0]].copy()
    )
    signal["signal_daily_return_pct"] = 8.0
    signal["signal_close"] = 95.0
    signal["reference_peak_price"] = 100.0
    signal["support_test_session_gap"] = 2
    signal["support_price"] = 10.0
    signal["active_direction"] = "GOLD"
    signal["danger_state"] = "NORMAL"
    signal["market_timing_feature_cutoff_date"] = signal["signal_date"]

    rows = pd.concat(
        [
            signal.assign(
                signal_id="rotation-broke-support",
                market_phase="rotation",
                signal_low=9.50,
            ),
            signal.assign(
                signal_id="warming-held-tolerance",
                market_phase="warming",
                signal_low=9.80,
            ),
            signal.assign(
                signal_id="warming-broke-tolerance",
                market_phase="warming",
                signal_low=9.79,
            ),
            signal.assign(
                signal_id="uptrend-insufficient-sample",
                market_phase="uptrend",
                signal_low=10.00,
            ),
            signal.assign(
                signal_id="retreat-cash",
                market_phase="retreat",
                signal_low=10.00,
            ),
        ],
        ignore_index=True,
    )

    selected = select_cross_regime_support_reclaim_signals(rows)

    assert selected["signal_id"].tolist() == [
        "rotation-broke-support",
        "warming-held-tolerance",
    ]


def test_cross_regime_support_reclaim_rejects_outcome_columns() -> None:
    signal = (
        replay_stock_campaign(pd.DataFrame(_first_wave_rows())).signals.iloc[[0]].copy()
    )
    signal["market_phase"] = "rotation"
    signal["active_direction"] = "GOLD"
    signal["danger_state"] = "NORMAL"
    signal["market_timing_feature_cutoff_date"] = signal["signal_date"]

    with pytest.raises(ValueError, match="future or outcome"):
        select_cross_regime_support_reclaim_signals(
            signal.assign(net_return_pct=99.0)
        )


def test_warming_support_relevance_selects_rotation_and_exact_warming_hold() -> None:
    signal = _support_relevance_signal()
    rows = pd.concat(
        [
            signal.assign(
                signal_id="rotation",
                market_phase="rotation",
                signal_low=8.0,
            ),
            signal.assign(
                signal_id="warming-support",
                market_phase="warming",
                signal_low=10.0,
            ),
            signal.assign(
                signal_id="warming-upper-bound",
                market_phase="warming",
                signal_low=10.8,
            ),
            signal.assign(
                signal_id="warming-undercut",
                market_phase="warming",
                signal_low=9.99,
            ),
            signal.assign(
                signal_id="warming-stale",
                market_phase="warming",
                signal_low=10.81,
            ),
        ],
        ignore_index=True,
    )

    selected = select_warming_support_relevance_signals(rows)

    assert selected["signal_id"].tolist() == [
        "rotation",
        "warming-support",
        "warming-upper-bound",
    ]
    assert selected.loc[
        selected["signal_id"].eq("warming-upper-bound"), "low_support_gap_pct"
    ].iat[0] == pytest.approx(8.0)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"active_direction": "SILVER"}, "cash_non_gold_market"),
        ({"danger_state": "DANGER"}, "cash_danger_market"),
        ({"signal_daily_return_pct": 7.99}, "confirmation_return_below_8pct"),
        ({"signal_close": 94.99}, "close_too_far_below_visible_peak"),
        ({"support_test_session_gap": 3}, "support_confirmation_too_late"),
        ({"market_phase": "retreat"}, "cash_unsupported_market_phase"),
        ({"signal_low": 9.99}, "warming_support_undercut"),
        ({"signal_low": 10.81}, "warming_support_stale"),
        ({"market_phase": "rotation"}, "eligible_rotation_strong_reclaim"),
        ({"signal_low": 10.5}, "eligible_warming_support_relevance"),
    ],
)
def test_warming_support_relevance_explains_first_causal_decision(
    changes: dict[str, object],
    expected: str,
) -> None:
    row = _support_relevance_signal().iloc[0].to_dict()
    row.update(changes)

    assert explain_warming_support_relevance_signal(row) == expected


def test_warming_support_relevance_rejects_outcome_columns() -> None:
    signal = _support_relevance_signal().assign(net_return_pct=99.0)

    with pytest.raises(ValueError, match="future or outcome"):
        select_warming_support_relevance_signals(signal)

    with pytest.raises(ValueError, match="future or outcome"):
        explain_warming_support_relevance_signal(signal.iloc[0].to_dict())


def test_rotation_next_session_selector_changes_only_delayed_rotation() -> None:
    signal = _support_relevance_signal()
    rows = pd.concat(
        [
            signal.assign(
                signal_id="rotation-next",
                market_phase="rotation",
                support_test_session_gap=1,
            ),
            signal.assign(
                signal_id="rotation-delayed",
                market_phase="rotation",
                support_test_session_gap=2,
            ),
            signal.assign(
                signal_id="warming-delayed",
                market_phase="warming",
                support_test_session_gap=2,
            ),
        ],
        ignore_index=True,
    )

    selected = select_rotation_next_session_signals(rows)

    assert selected["signal_id"].tolist() == [
        "rotation-next",
        "warming-delayed",
    ]


def test_rotation_next_session_selector_rejects_outcome_columns() -> None:
    signal = _support_relevance_signal().assign(net_return_pct=99.0)

    with pytest.raises(ValueError, match="future or outcome"):
        select_rotation_next_session_signals(signal)


def test_three_phase_adaptive_routes_uptrend_warming_rotation_and_retreat() -> None:
    signal = _support_relevance_signal()
    rows = pd.concat(
        [
            signal.assign(signal_id="uptrend", market_phase="uptrend"),
            signal.assign(
                signal_id="uptrend-undercut",
                market_phase="uptrend",
                signal_low=9.99,
            ),
            signal.assign(signal_id="warming", market_phase="warming"),
            signal.assign(
                signal_id="rotation-next",
                market_phase="rotation",
                support_test_session_gap=1,
            ),
            signal.assign(
                signal_id="rotation-delayed",
                market_phase="rotation",
                support_test_session_gap=2,
            ),
            signal.assign(signal_id="retreat", market_phase="retreat"),
        ],
        ignore_index=True,
    )

    selected = select_three_phase_adaptive_signals(rows)

    assert selected["signal_id"].tolist() == [
        "uptrend",
        "warming",
        "rotation-next",
    ]


def test_three_phase_adaptive_rejects_outcome_columns() -> None:
    signal = _support_relevance_signal().assign(net_return_pct=99.0)

    with pytest.raises(ValueError, match="future or outcome"):
        select_three_phase_adaptive_signals(signal)


def test_trade_metrics_include_profit_factor_compound_and_drawdown() -> None:
    trades = pd.DataFrame(
        {
            "net_return_pct": [10.0, -5.0, 4.0],
            "exit_date": pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-04"]),
        }
    )

    metrics = summarize_trade_metrics(trades)

    assert metrics["closed_trades"] == 3
    assert metrics["positive_rate_pct"] == pytest.approx(200 / 3)
    assert metrics["profit_factor"] == pytest.approx(2.8)
    assert metrics["compound_return_pct"] == pytest.approx(8.68)
    assert metrics["maximum_drawdown_pct"] == pytest.approx(-5.0)


def test_execute_close_trades_rejects_signal_after_feature_cutoff() -> None:
    path = pd.DataFrame(_first_wave_rows())
    replay = replay_stock_campaign(path)
    signals = replay.signals.copy()
    signals.loc[:, "feature_cutoff_date"] = pd.Timestamp("2025-06-25")

    with pytest.raises(ValueError, match="feature cutoff"):
        execute_close_trades(signals, path)


def _rank_row(
    symbol: str,
    leg_gain_pct: float,
    strong_days: int,
    concept_gain_pct: float,
    turnover_expansion: float,
) -> dict[str, object]:
    return {
        "campaign_id": "campaign-1",
        "sector_id": "BK0001",
        "concept_name": "测试概念",
        "trade_date": "2026-01-15",
        "vt_symbol": symbol,
        "stock_name": symbol,
        "leg_gain_pct": leg_gain_pct,
        "strong_days_since_ignition": strong_days,
        "concept_gain_pct": concept_gain_pct,
        "turnover_expansion": turnover_expansion,
        "ignited_in_campaign": True,
        "structure_intact": True,
    }


def _support_relevance_signal() -> pd.DataFrame:
    signal = (
        replay_stock_campaign(pd.DataFrame(_first_wave_rows())).signals.iloc[[0]].copy()
    )
    signal["signal_daily_return_pct"] = 8.0
    signal["signal_close"] = 95.0
    signal["reference_peak_price"] = 100.0
    signal["support_test_session_gap"] = 2
    signal["support_price"] = 10.0
    signal["signal_low"] = 10.5
    signal["active_direction"] = "GOLD"
    signal["danger_state"] = "NORMAL"
    signal["market_phase"] = "warming"
    signal["market_timing_feature_cutoff_date"] = signal["signal_date"]
    return signal


def _first_wave_rows() -> list[dict[str, object]]:
    return [
        _bar("2025-06-20", 9.80, 10.20, 9.75, 10.10, ignition=True),
        _bar("2025-06-23", 10.10, 11.00, 10.05, 10.80),
        _bar("2025-06-24", 10.70, 10.75, 10.30, 10.40, ma5=10.34, close_location=0.22),
        _bar("2025-06-25", 10.38, 10.48, 10.28, 10.35, ma5=10.33, close_location=0.35),
        _bar(
            "2025-06-26",
            10.36,
            10.65,
            10.30,
            10.60,
            ma5=10.35,
            close_location=0.86,
            volume_ratio=0.7,
        ),
        _bar("2025-06-27", 10.62, 10.90, 10.55, 10.80, ma5=10.45),
        _bar("2025-06-30", 10.85, 11.20, 10.80, 11.10, ma5=10.65),
    ]


def _second_wave_rows() -> list[dict[str, object]]:
    rows = _first_wave_rows()
    rows.extend(
        [
            _bar("2025-07-01", 11.05, 11.10, 10.75, 10.85, ma5=10.90, ma10=10.45),
            _bar("2025-07-02", 10.75, 10.80, 10.45, 10.60, ma5=10.78, ma10=10.43),
            _bar("2025-07-03", 10.62, 10.92, 10.55, 10.85, ma5=10.74, ma10=10.44),
            _bar("2025-07-04", 10.90, 11.10, 10.80, 11.00, ma5=10.78, ma10=10.48),
            _bar("2025-07-07", 11.05, 11.35, 10.98, 11.25, ma5=10.92, ma10=10.55),
        ]
    )
    return rows


def _bar(
    trade_date: str,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    *,
    ma5: float = 9.90,
    ma10: float = 9.60,
    ma20: float = 9.20,
    close_location: float = 0.75,
    volume_ratio: float = 1.0,
    ignition: bool = False,
) -> dict[str, object]:
    previous_close = open_price
    daily_return = (close_price / previous_close - 1.0) * 100.0
    return {
        "campaign_id": "campaign-1",
        "sector_id": "BK0001",
        "concept_name": "测试概念",
        "vt_symbol": "600001.SSE",
        "stock_name": "测试股份",
        "trade_date": trade_date,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "close_price": close_price,
        "volume": 1_000_000.0,
        "turnover": 10_000_000.0,
        "daily_return_pct": 6.0 if ignition else daily_return,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "prior_high20": 9.60 if ignition else high_price + 1.0,
        "volume_ratio_prior5": 2.0 if ignition else volume_ratio,
        "close_location": close_location,
        "campaign_active": True,
        "dynamic_rank": 1,
        "dynamic_top3": True,
        "feature_cutoff_date": trade_date,
    }
