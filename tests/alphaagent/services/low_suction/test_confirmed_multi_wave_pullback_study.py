from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alphaagent.server.services.low_suction.confirmed_multi_wave_pullback_study import (
    ConfirmedPullbackResult,
    build_confirmed_multi_wave_pullback_report,
    build_confirmed_multi_wave_signals,
    build_confirmed_pullback_trades,
    evaluate_confirmed_pullback_candidate,
    render_confirmed_pullback_json,
    render_confirmed_pullback_markdown,
    summarize_confirmed_pullback_trades,
)


def _bar(
    trade_date: pd.Timestamp,
    *,
    close: float,
    high: float | None = None,
    low: float | None = None,
    open_price: float | None = None,
    volume: float = 100.0,
) -> dict[str, object]:
    resolved_open = close if open_price is None else open_price
    return {
        "vt_symbol": "600001.SSE",
        "trade_date": trade_date,
        "open_price": resolved_open,
        "high_price": max(close, resolved_open) + 0.1 if high is None else high,
        "low_price": min(close, resolved_open) - 0.1 if low is None else low,
        "close_price": close,
        "volume": volume,
        "turnover": close * volume,
    }


def _confirmed_wave_fixture() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    dates = pd.bdate_range("2025-01-02", periods=38)
    rows = []
    for index, trade_date in enumerate(dates[:25]):
        close = 10.0 + index * 0.06
        rows.append(_bar(trade_date, close=close))
    rows.extend(
        [
            _bar(dates[25], close=12.0, high=12.2, low=11.6, volume=150.0),
            _bar(dates[26], close=12.6, high=12.8, low=11.9, volume=180.0),
            # This support approach is before a 5% pullback and must be ignored.
            _bar(dates[27], close=12.3, high=12.55, low=12.20, volume=90.0),
            _bar(dates[28], close=12.0, high=12.25, low=12.00, volume=80.0),
            _bar(dates[29], close=12.1, high=12.30, low=11.80, volume=75.0),
            _bar(
                dates[30],
                close=12.9,
                open_price=12.15,
                high=13.05,
                low=12.10,
                volume=130.0,
            ),
        ]
    )
    rows.extend(
        _bar(trade_date, close=12.7 + index * 0.02)
        for index, trade_date in enumerate(dates[31:])
    )
    bars = pd.DataFrame(rows)
    episodes = pd.DataFrame(
        [
            {
                "episode_id": "dynamic:600001.SSE:2025-02-06",
                "cycle_id": "breakout_trend:BK001:2025-02-06",
                "vt_symbol": "600001.SSE",
                "stock_name": "测试龙头",
                "sector_id": "BK001",
                "concept_name": "测试概念",
                "anchor_date": dates[25],
                "observation_end": dates[-1],
                "causal_rank": 1,
                "time_block": "block_1",
            }
        ]
    )
    waves = pd.DataFrame(
        [
            {
                "episode_id": episodes.iloc[0]["episode_id"],
                "wave_number": wave_number,
                "wave_start_date": dates[start_index],
                "observation_end": dates[-1],
            }
            for wave_number, start_index in ((1, 20), (2, 23), (3, 25))
        ]
    )
    concept_states = pd.DataFrame(
        [
            {
                "sector_id": "BK001",
                "trade_date": trade_date,
                "definition": "breakout_trend",
                "in_cycle": True,
                "sustain_qualifies": True,
                "cycle_id": "breakout_trend:BK001:2025-02-06",
            }
            for trade_date in dates
        ]
    )
    return episodes, waves, bars, concept_states


def test_signals_require_two_confirmed_highs_and_a_causal_pullback() -> None:
    episodes, waves, bars, concept_states = _confirmed_wave_fixture()

    signals = build_confirmed_multi_wave_signals(
        episodes,
        waves,
        bars,
        concept_states,
    )

    assert set(signals["signal_mode"]) == {
        "first_approach",
        "stabilized_reclaim",
    }
    assert signals["wave_number"].eq(3).all()
    assert signals["confirmed_higher_highs_at_wave_start"].eq(2).all()
    assert signals["pullback_confirmation_date"].eq(
        pd.Timestamp(bars.iloc[28]["trade_date"])
    ).all()
    first = signals.loc[signals["signal_mode"].eq("first_approach")].iloc[0]
    stabilized = signals.loc[
        signals["signal_mode"].eq("stabilized_reclaim")
    ].iloc[0]
    assert first["signal_date"] == pd.Timestamp(bars.iloc[28]["trade_date"])
    assert stabilized["signal_date"] == pd.Timestamp(bars.iloc[29]["trade_date"])
    assert stabilized["signal_date"] > first["signal_date"]
    assert stabilized["feature_cutoff_date"] == stabilized["signal_date"]
    assert stabilized["concept_main_rise_intact"]
    assert stabilized["stock_structure_intact"]
    assert stabilized["primary_eligible"]


def test_future_bars_cannot_change_confirmed_pullback_signal() -> None:
    episodes, waves, bars, concept_states = _confirmed_wave_fixture()
    original = build_confirmed_multi_wave_signals(
        episodes,
        waves,
        bars,
        concept_states,
    )
    signal_date = original.loc[
        original["signal_mode"].eq("stabilized_reclaim"), "signal_date"
    ].iloc[0]
    changed_bars = bars.copy()
    future = changed_bars["trade_date"].gt(signal_date)
    changed_bars.loc[future, "close_price"] = 30.0
    changed_bars.loc[future, "open_price"] = 29.0
    changed_bars.loc[future, "high_price"] = 31.0
    changed_bars.loc[future, "low_price"] = 28.0
    changed = build_confirmed_multi_wave_signals(
        episodes,
        waves,
        changed_bars,
        concept_states,
    )

    compared = [
        "episode_id",
        "wave_number",
        "signal_mode",
        "signal_date",
        "pullback_confirmation_date",
        "reference_peak_date",
        "reference_peak_price",
        "support_line",
        "stock_structure_intact",
        "concept_main_rise_intact",
        "primary_eligible",
        "feature_cutoff_date",
    ]
    pd.testing.assert_frame_equal(original[compared], changed[compared])


def test_wave_four_is_diagnostic_but_cannot_enter_the_primary_cohort() -> None:
    episodes, waves, bars, concept_states = _confirmed_wave_fixture()
    waves = waves.loc[waves["wave_number"].eq(3)].assign(wave_number=4)

    signals = build_confirmed_multi_wave_signals(
        episodes,
        waves,
        bars,
        concept_states,
    )

    stabilized = signals.loc[
        signals["signal_mode"].eq("stabilized_reclaim")
    ].iloc[0]
    assert stabilized["confirmed_higher_highs_at_wave_start"] == 3
    assert not stabilized["primary_eligible"]


def test_structural_break_and_missing_concept_state_close_primary_gate() -> None:
    episodes, waves, bars, concept_states = _confirmed_wave_fixture()
    broken = bars.copy()
    break_index = 28
    broken.loc[break_index, "close_price"] = 9.0
    broken.loc[break_index, "open_price"] = 9.1
    broken.loc[break_index, "high_price"] = 9.2
    broken.loc[break_index, "low_price"] = 8.9
    broken.loc[29, "close_price"] = 12.1
    broken.loc[29, "open_price"] = 11.9
    missing_state = concept_states.loc[
        ~concept_states["trade_date"].eq(bars.iloc[29]["trade_date"])
    ]

    structural = build_confirmed_multi_wave_signals(
        episodes,
        waves,
        broken,
        concept_states,
    )
    unavailable = build_confirmed_multi_wave_signals(
        episodes,
        waves,
        bars,
        missing_state,
    )

    structural_signal = structural.loc[
        structural["signal_mode"].eq("stabilized_reclaim")
    ].iloc[0]
    unavailable_signal = unavailable.loc[
        unavailable["signal_mode"].eq("stabilized_reclaim")
    ].iloc[0]
    assert not structural_signal["stock_structure_intact"]
    assert not structural_signal["primary_eligible"]
    assert not unavailable_signal["concept_state_available"]
    assert not unavailable_signal["concept_main_rise_intact"]
    assert not unavailable_signal["primary_eligible"]


def test_trades_enter_next_open_and_exit_on_first_higher_high() -> None:
    episodes, waves, bars, concept_states = _confirmed_wave_fixture()
    signals = build_confirmed_multi_wave_signals(
        episodes,
        waves,
        bars,
        concept_states,
    )

    trades, exclusions = build_confirmed_pullback_trades(signals, bars)

    assert exclusions.empty
    trade = trades.loc[trades["signal_mode"].eq("stabilized_reclaim")].iloc[0]
    assert trade["entry_date"] > trade["signal_date"]
    assert trade["entry_price"] == pytest.approx(12.15)
    assert trade["entry_proxy"] == "next_session_open_after_close_signal"
    assert trade["executable_exit_reason"] == "higher_high_confirmed"
    assert trade["exit_date"] == trade["entry_date"]
    assert trade["net_return_pct"] == pytest.approx(
        (12.9 / 12.15 - 1.0) * 100.0 - 0.2
    )


def test_entry_gap_at_or_above_peak_is_explicitly_rejected() -> None:
    episodes, waves, bars, concept_states = _confirmed_wave_fixture()
    signals = build_confirmed_multi_wave_signals(
        episodes,
        waves,
        bars,
        concept_states,
    )
    gapped = bars.copy()
    entry_index = 30
    gapped.loc[entry_index, "open_price"] = 12.8
    gapped.loc[entry_index, "high_price"] = 13.0
    gapped.loc[entry_index, "low_price"] = 12.7
    gapped.loc[entry_index, "close_price"] = 12.9

    trades, exclusions = build_confirmed_pullback_trades(signals, gapped)

    assert trades["signal_mode"].tolist() == ["first_approach"]
    assert exclusions["signal_mode"].tolist() == ["stabilized_reclaim"]
    assert set(exclusions["exclusion_reason"]) == {"opportunity_gone_at_entry"}


def test_two_close_ma20_exit_keeps_later_higher_high_as_false_exit_evidence() -> None:
    episodes, waves, bars, concept_states = _confirmed_wave_fixture()
    signals = build_confirmed_multi_wave_signals(
        episodes,
        waves,
        bars,
        concept_states,
    )
    changed = bars.copy()
    changed.loc[30, ["open_price", "high_price", "low_price", "close_price"]] = [
        12.15,
        12.20,
        10.40,
        10.50,
    ]
    changed.loc[31, ["open_price", "high_price", "low_price", "close_price"]] = [
        10.50,
        10.60,
        10.30,
        10.40,
    ]
    changed.loc[33, ["open_price", "high_price", "low_price", "close_price"]] = [
        12.40,
        13.10,
        12.30,
        13.00,
    ]

    trades, exclusions = build_confirmed_pullback_trades(signals, changed)

    assert exclusions.empty
    trade = trades.loc[trades["signal_mode"].eq("stabilized_reclaim")].iloc[0]
    assert trade["executable_exit_reason"] == "two_closes_below_ma20"
    assert trade["exit_date"] == pd.Timestamp(changed.iloc[31]["trade_date"])
    assert trade["eventually_made_higher_high"]
    assert trade["defensive_exit_preceded_later_higher_high"]


def _candidate_trade_frame(*, passing: bool) -> pd.DataFrame:
    rows = []
    for block_number in range(1, 6):
        for row_index in range(40):
            positive = row_index < (28 if passing else 20)
            rows.append(
                {
                    "episode_id": f"episode-{block_number}-{row_index}",
                    "vt_symbol": f"600{block_number:03d}.SSE",
                    "stock_name": f"股票-{block_number}",
                    "concept_name": f"概念-{block_number}",
                    "signal_mode": "stabilized_reclaim",
                    "signal_date": pd.Timestamp("2025-01-01"),
                    "time_block": f"block_{block_number}",
                    "primary_eligible": True,
                    "concept_main_rise_intact": True,
                    "stock_structure_intact": True,
                    "xuguang_climax_candidate": False,
                    "wave_number": 3,
                    "entry_date": pd.Timestamp("2025-01-02"),
                    "entry_price": 10.0,
                    "exit_date": pd.Timestamp("2025-01-02"),
                    "net_return_pct": 2.0 if positive else -1.0,
                    "maximum_adverse_excursion_pct": -0.5,
                    "eventually_made_higher_high": positive,
                    "defensive_exit_preceded_later_higher_high": False,
                    "support_line": "ma10",
                    "volume_class_prior5": "normal",
                    "wave_bucket": "wave_3",
                    "executable_exit_reason": "higher_high_confirmed",
                }
            )
    return pd.DataFrame(rows)


def test_candidate_gate_requires_return_quality_and_block_stability() -> None:
    passing = evaluate_confirmed_pullback_candidate(_candidate_trade_frame(passing=True))
    failing = evaluate_confirmed_pullback_candidate(
        _candidate_trade_frame(passing=False)
    )

    assert passing["candidate_for_new_forward_block"]
    assert passing["stable_blocks"] == 5
    assert not failing["candidate_for_new_forward_block"]


def test_summary_keeps_censored_rows_out_of_return_denominators() -> None:
    trades = _candidate_trade_frame(passing=True).iloc[:3].copy()
    trades.loc[trades.index[-1], ["exit_date", "net_return_pct"]] = [pd.NaT, np.nan]

    summary = summarize_confirmed_pullback_trades(trades, "signal_mode")

    assert summary.iloc[0]["entries"] == 3
    assert summary.iloc[0]["closed_entries"] == 2
    assert summary.iloc[0]["censored_entries"] == 1


def test_report_quarantines_reused_proxy_results_from_formal_metrics() -> None:
    trades = _candidate_trade_frame(passing=True)
    wave_four = trades.iloc[[0]].assign(
        episode_id="wave-four-diagnostic",
        wave_number=4,
        primary_eligible=False,
    )
    trades = pd.concat([trades, wave_four], ignore_index=True)
    result = ConfirmedPullbackResult(
        signals=trades.assign(signal_date=pd.Timestamp("2025-01-01")),
        trades=trades,
        exclusions=pd.DataFrame(),
    )
    report = build_confirmed_multi_wave_pullback_report(
        result=result,
        coverage={"strict_historical_membership_rows": 0},
        fingerprints={},
    )

    assert report["validation_status"] == "reused_history_not_validation"
    assert report["membership_evidence"] == (
        "current_membership_and_security_proxy"
    )
    assert report["formal_metrics"] == {
        "win_rate_pct": None,
        "average_net_return_pct": None,
        "compounded_return_pct": None,
        "profit_factor": None,
        "maximum_drawdown_pct": None,
    }
    assert report["candidate_gate"]["candidate_for_new_forward_block"]
    assert report["candidate_gate"]["pooled"]["entries"] == 200
    assert report["primary_funnel_summary"][-1]["entries"] == 200
    assert len(report["primary_support_block_summary"]) == 5
    assert {
        row["time_block"] for row in report["primary_support_block_summary"]
    } == {f"block_{number}" for number in range(1, 6)}
    rendered_json = render_confirmed_pullback_json(report)
    rendered_markdown = render_confirmed_pullback_markdown(report)
    assert render_confirmed_pullback_json(report) == rendered_json
    assert "正式 Top3、低吸胜率、收益、复利：`null`" in rendered_markdown
