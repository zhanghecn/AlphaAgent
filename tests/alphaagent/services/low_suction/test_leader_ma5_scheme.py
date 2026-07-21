from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.leader_ma5_scheme import (
    SCHEME_VERSION,
    select_scheme_candidates,
    summarize_tail_results,
    summarize_tail_segments,
    summarize_structural_results,
    summarize_structural_segments,
)
from alphaagent.server.services.low_suction.leader_ma5_scheme_study import (
    build_leader_ma5_scheme_report,
    build_cutoff_recognition_audit,
    build_causal_structural_cash_trades,
    build_hybrid_feature_diagnostics,
    build_tail_scheme_candidates,
    build_tail_structural_cash_trades,
    execute_tail_scheme,
    load_frozen_scheme_candidates,
    render_leader_ma5_scheme_json,
    render_leader_ma5_scheme_markdown,
)
from alphaagent.server.services.low_suction.tail_feature_study import (
    PROHIBITED_FEATURE_COLUMNS,
    build_tail_feature_panel,
)


def _attribution_ledger() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_id": "signal-a",
                "signal_date": "2025-01-02",
                "entry_date": "2025-01-03",
                "vt_symbol": "600001.SSE",
                "strong_days_ge_9_5pct": 1,
                "time_block": "block_1",
                "net_return_pct": 2.0,
                "exit_date": "2025-01-08",
                "eventually_made_higher_high": True,
                "maximum_adverse_excursion_pct": -1.0,
                "maximum_favorable_excursion_pct": 3.0,
                "active_direction": "GOLD",
                "volume_ratio_prior5": 0.8,
                "stock_ma5_ma10_gap_pct": 6.0,
            },
            {
                "signal_id": "signal-b",
                "signal_date": "2025-01-06",
                "entry_date": "2025-01-07",
                "vt_symbol": "000001.SZSE",
                "strong_days_ge_9_5pct": 0,
                "time_block": "block_2",
                "net_return_pct": 20.0,
                "exit_date": "2025-01-10",
                "eventually_made_higher_high": True,
                "maximum_adverse_excursion_pct": -0.2,
                "maximum_favorable_excursion_pct": 25.0,
                "active_direction": "GOLD",
                "volume_ratio_prior5": 0.2,
                "stock_ma5_ma10_gap_pct": 20.0,
            },
            {
                "signal_id": "signal-c",
                "signal_date": "2025-01-08",
                "entry_date": "2025-01-09",
                "vt_symbol": "600002.SSE",
                "strong_days_ge_9_5pct": 2,
                "time_block": "block_2",
                "net_return_pct": -1.0,
                "exit_date": "2025-01-14",
                "eventually_made_higher_high": False,
                "maximum_adverse_excursion_pct": -5.0,
                "maximum_favorable_excursion_pct": 0.5,
                "active_direction": "SILVER",
                "volume_ratio_prior5": 1.8,
                "stock_ma5_ma10_gap_pct": 2.0,
            },
            {
                "signal_id": "signal-d",
                "signal_date": "2025-01-10",
                "entry_date": "2025-01-13",
                "vt_symbol": "002001.SZSE",
                "strong_days_ge_9_5pct": 1,
                "time_block": "block_5",
                "net_return_pct": 3.0,
                "exit_date": "2025-01-17",
                "eventually_made_higher_high": True,
                "maximum_adverse_excursion_pct": -2.0,
                "maximum_favorable_excursion_pct": 4.0,
                "active_direction": "MISSING",
                "volume_ratio_prior5": 3.0,
                "stock_ma5_ma10_gap_pct": 0.5,
            },
        ]
    )


def test_scheme_selects_only_the_natural_strong_day_gate() -> None:
    selected = select_scheme_candidates(_attribution_ledger())

    assert SCHEME_VERSION == "leader-ma5-recognition-v1"
    assert list(selected["signal_id"]) == ["signal-a", "signal-c", "signal-d"]
    assert selected["strong_days_ge_9_5pct"].ge(1).all()


def test_outcomes_and_diagnostics_cannot_change_scheme_identity() -> None:
    baseline = select_scheme_candidates(_attribution_ledger())
    changed = _attribution_ledger().copy(deep=True)
    changed["net_return_pct"] = [-99.0, 99.0, 99.0, -99.0]
    changed["exit_date"] = "2099-01-01"
    changed["eventually_made_higher_high"] = False
    changed["maximum_adverse_excursion_pct"] = -99.0
    changed["maximum_favorable_excursion_pct"] = 99.0
    changed["active_direction"] = ["SILVER", "GOLD", "GOLD", "GOLD"]
    changed["volume_ratio_prior5"] = [99.0, 0.01, 99.0, 99.0]
    changed["stock_ma5_ma10_gap_pct"] = [-10.0, 99.0, -10.0, -10.0]

    repeated = select_scheme_candidates(changed)

    assert list(repeated["signal_id"]) == list(baseline["signal_id"])


def test_duplicate_signal_identity_is_rejected() -> None:
    ledger = _attribution_ledger()
    ledger = pd.concat([ledger, ledger.iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="signal IDs must be unique"):
        select_scheme_candidates(ledger)


def test_structural_summary_uses_closed_outcomes_after_selection() -> None:
    selected = select_scheme_candidates(_attribution_ledger())

    summary = summarize_structural_results(selected)

    assert summary["signals"] == 3
    assert summary["closed_trades"] == 3
    assert summary["descriptive_positive_share_pct"] == pytest.approx(66.6666667)
    assert summary["mean_net_return_pct"] == pytest.approx(4.0 / 3.0)
    assert summary["profit_factor"] == pytest.approx(5.0)


def test_structural_summary_does_not_mutate_input() -> None:
    selected = select_scheme_candidates(_attribution_ledger())
    original = deepcopy(selected.to_dict("records"))

    summarize_structural_results(selected)

    assert selected.to_dict("records") == original


def test_structural_segments_keep_all_five_frozen_blocks() -> None:
    selected = select_scheme_candidates(_attribution_ledger())

    segments = summarize_structural_segments(selected)

    assert tuple(segments) == (
        "all",
        "block_1",
        "block_2",
        "block_3",
        "block_4",
        "block_5",
    )
    assert segments["all"]["closed_trades"] == 3
    assert segments["block_2"]["closed_trades"] == 1
    assert segments["block_3"]["closed_trades"] == 0
    assert segments["block_5"]["mean_net_return_pct"] == pytest.approx(3.0)


TAIL_DATES = tuple(pd.bdate_range("2025-02-03", periods=31).date)
TAIL_SIGNAL_DATE = TAIL_DATES[-3]
TAIL_NEXT_DATE = TAIL_DATES[-2]
TAIL_STRUCTURAL_EXECUTION_DATE = TAIL_DATES[-1]


def _tail_scheme_candidate() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_id": "tail-signal",
                "episode_id": "episode-1",
                "signal_date": TAIL_SIGNAL_DATE,
                "entry_date": TAIL_NEXT_DATE,
                "wave_start_date": TAIL_DATES[-9],
                "pullback_confirmation_date": TAIL_DATES[-4],
                "first_support_approach_date": TAIL_DATES[-4],
                "reference_peak_date": TAIL_DATES[-5],
                "reference_peak_price": 10.6,
                "vt_symbol": "600001.SSE",
                "stock_name": "Test Stock",
                "sector_id": "BK0001",
                "concept_name": "Test Concept",
                "causal_rank": 1,
                "strong_days_ge_9_5pct": 1,
                "active_direction": "GOLD",
                "danger_state": "NORMAL",
                "market_phase": "launch",
                "time_block": "block_4",
                "exit_date": TAIL_NEXT_DATE,
                "net_return_pct": 99.0,
                "eventually_made_higher_high": True,
            }
        ]
    )


def _tail_daily_bars() -> pd.DataFrame:
    rows = []
    for index, trade_date in enumerate(TAIL_DATES):
        close = 9.5 + index * 0.02
        if trade_date == TAIL_SIGNAL_DATE:
            close = 10.2
        elif trade_date == TAIL_NEXT_DATE:
            close = 10.4
        rows.append(
            {
                "vt_symbol": "600001.SSE",
                "trade_date": trade_date,
                "open_price": close - 0.05,
                "high_price": close + 0.2,
                "low_price": close - 0.2,
                "close_price": close,
                "volume": 1_000_000.0 + index * 1_000.0,
                "turnover": close * (1_000_000.0 + index * 1_000.0),
            }
        )
    return pd.DataFrame(rows)


def _tail_five_minute_times(trade_date: date) -> tuple[datetime, ...]:
    values = []
    for start in ("09:35", "13:05"):
        current = datetime.combine(
            trade_date,
            datetime.strptime(start, "%H:%M").time(),
        )
        values.extend(current + timedelta(minutes=5 * index) for index in range(24))
    return tuple(values)


def _tail_minute_bars() -> pd.DataFrame:
    rows = []
    for trade_date in (TAIL_SIGNAL_DATE, TAIL_NEXT_DATE):
        for index, bar_time in enumerate(_tail_five_minute_times(trade_date)):
            open_price = 10.1 if trade_date == TAIL_SIGNAL_DATE else 10.4
            if trade_date == TAIL_SIGNAL_DATE and bar_time.strftime("%H:%M") == "14:55":
                open_price = 10.2
            if trade_date == TAIL_NEXT_DATE and bar_time.strftime("%H:%M") == "10:35":
                open_price = 10.5
            close_price = open_price + 0.01
            volume = 100_000.0 + index * 100.0
            rows.append(
                {
                    "vt_symbol": "600001.SSE",
                    "trade_date": trade_date,
                    "bar_time": bar_time,
                    "interval": "5m",
                    "open_price": open_price,
                    "high_price": close_price + 0.02,
                    "low_price": open_price - 0.02,
                    "close_price": close_price,
                    "volume": volume,
                    "turnover": close_price * volume,
                    "source": "tdx_public_hq",
                }
            )
    return pd.DataFrame(rows)


def test_tail_candidate_mapping_uses_previous_session_without_outcomes() -> None:
    mapped = build_tail_scheme_candidates(
        _tail_scheme_candidate(),
        _tail_daily_bars(),
    )

    assert len(mapped) == 1
    assert mapped.loc[0, "context_date"] == TAIL_DATES[-4]
    assert mapped.loc[0, "entry_date"] == TAIL_SIGNAL_DATE
    assert mapped.loc[0, "planned_exit_date"] == TAIL_NEXT_DATE
    assert mapped.loc[0, "recognition_source_date"] == TAIL_DATES[-9]
    assert mapped.loc[0, "spell_session_offset"] == 3
    assert PROHIBITED_FEATURE_COLUMNS.isdisjoint(mapped.columns)
    assert "eventually_made_higher_high" not in mapped


def test_tail_execution_reuses_1455_and_next_1035_cash_contract() -> None:
    features, ledger = execute_tail_scheme(
        _tail_scheme_candidate(),
        _tail_daily_bars(),
        _tail_minute_bars(),
    )

    assert len(features) == 1
    assert features.loc[0, "feature_cutoff_time"] == "14:50"
    assert bool(features.loc[0, "cutoff_recognition_passed"]) is True
    assert ledger.loc[0, "status"] == "closed"
    assert pd.Timestamp(ledger.loc[0, "entry_time"]).strftime("%H:%M") == "14:55"
    assert pd.Timestamp(ledger.loc[0, "exit_time"]).strftime("%H:%M") == "10:35"
    assert ledger.loc[0, "entry_price_raw"] == pytest.approx(10.2)
    assert ledger.loc[0, "exit_price_raw"] == pytest.approx(10.5)
    assert ledger.loc[0, "double_cost_net_return_pct"] < ledger.loc[
        0, "net_return_pct"
    ]


def test_tail_structural_cash_trade_reuses_filled_1455_entry() -> None:
    _, ledger = execute_tail_scheme(
        _tail_scheme_candidate(),
        _tail_daily_bars(),
        _tail_minute_bars(),
    )

    trades = build_tail_structural_cash_trades(
        _tail_scheme_candidate(),
        ledger,
        _tail_daily_bars(),
    )

    assert len(trades) == 1
    assert trades.loc[0, "entry_date"] == TAIL_SIGNAL_DATE
    assert trades.loc[0, "exit_date"] == TAIL_STRUCTURAL_EXECUTION_DATE
    assert trades.loc[0, "exit_price_mode"] == "open"
    assert trades.loc[0, "entry_price_raw_override"] == pytest.approx(10.2)


def test_tail_structural_cash_trade_rejects_entry_at_reference_peak() -> None:
    candidate = _tail_scheme_candidate()
    candidate.loc[0, "reference_peak_price"] = 10.2
    _, ledger = execute_tail_scheme(
        candidate,
        _tail_daily_bars(),
        _tail_minute_bars(),
    )

    trades = build_tail_structural_cash_trades(
        candidate,
        ledger,
        _tail_daily_bars(),
    )

    assert trades.empty


def test_daily_structural_cash_trade_executes_session_after_trigger() -> None:
    trades = build_causal_structural_cash_trades(
        _tail_scheme_candidate(),
        _tail_daily_bars(),
    )

    assert trades.loc[0, "entry_date"] == TAIL_NEXT_DATE
    assert trades.loc[0, "structural_trigger_date"] == TAIL_NEXT_DATE
    assert trades.loc[0, "exit_date"] == TAIL_STRUCTURAL_EXECUTION_DATE
    assert trades.loc[0, "exit_price_mode"] == "open"


def test_cutoff_audit_recomputes_provisional_ma5_before_entry() -> None:
    mapped = build_tail_scheme_candidates(
        _tail_scheme_candidate(),
        _tail_daily_bars(),
    )
    features = build_tail_feature_panel(
        mapped,
        _tail_daily_bars(),
        _tail_minute_bars(),
    )
    audit = build_cutoff_recognition_audit(
        _tail_scheme_candidate(),
        features,
        _tail_daily_bars(),
    )
    weakened = features.copy()
    weakened.loc[0, "tail_close_price"] = weakened.loc[0, "context_close_price"] - 1.0
    failed = build_cutoff_recognition_audit(
        _tail_scheme_candidate(),
        weakened,
        _tail_daily_bars(),
    )

    assert audit.loc[0, "prior_close_count"] == 4
    assert bool(audit.loc[0, "cutoff_reclaimed_provisional_ma5"]) is True
    assert bool(audit.loc[0, "cutoff_not_below_previous_close"]) is True
    assert bool(audit.loc[0, "cutoff_pullback_known"]) is True
    assert bool(audit.loc[0, "cutoff_recognition_passed"]) is True
    assert bool(failed.loc[0, "cutoff_recognition_passed"]) is False


def test_tail_summary_keeps_nonfills_and_calculates_cash_metrics() -> None:
    ledger = pd.DataFrame(
        [
            {
                "event_id": "a",
                "entry_date": date(2025, 1, 2),
                "block": 1,
                "status": "closed",
                "net_return_pct": 2.0,
                "double_cost_net_return_pct": 1.7,
            },
            {
                "event_id": "b",
                "entry_date": date(2025, 1, 2),
                "block": 1,
                "status": "closed",
                "net_return_pct": -1.0,
                "double_cost_net_return_pct": -1.3,
            },
            {
                "event_id": "c",
                "entry_date": date(2025, 1, 3),
                "block": 5,
                "status": "closed",
                "net_return_pct": 3.0,
                "double_cost_net_return_pct": 2.7,
            },
            {
                "event_id": "d",
                "entry_date": date(2025, 1, 6),
                "block": 5,
                "status": "unavailable",
                "net_return_pct": None,
                "double_cost_net_return_pct": None,
            },
        ]
    )

    summary = summarize_tail_results(ledger)
    segments = summarize_tail_segments(ledger)

    assert summary["signals"] == 4
    assert summary["closed_trades"] == 3
    assert summary["unavailable_or_unclosed"] == 1
    assert summary["win_rate_pct"] == pytest.approx(66.6666667)
    assert summary["mean_net_return_pct"] == pytest.approx(4.0 / 3.0)
    assert summary["double_cost_mean_net_return_pct"] == pytest.approx(3.1 / 3.0)
    assert summary["profit_factor"] == pytest.approx(5.0)
    assert summary["compound_return_pct"] == pytest.approx(3.515)
    assert summary["maximum_drawdown_pct"] == pytest.approx(0.0)
    assert segments["block_1"]["closed_trades"] == 2
    assert segments["block_3"]["closed_trades"] == 0
    assert segments["block_5"]["signals"] == 2


def test_hybrid_diagnostics_compare_winners_and_losers_without_filtering() -> None:
    candidates = pd.DataFrame(
        {
            "signal_id": ["a", "b"],
            "volume_ratio_prior5": [1.2, 0.6],
            "stock_ma5_ma10_gap_pct": [4.0, 8.0],
            "active_direction": ["GOLD", "SILVER"],
            "causal_rank": [1, 2],
        }
    )
    features = pd.DataFrame(
        {
            "signal_id": ["a", "b"],
            "tail_return_from_previous_close_pct": [1.0, 0.2],
            "tail_drawdown_from_session_high_pct": [-1.0, -4.0],
            "tail_vs_vwap_pct": [0.5, -0.8],
            "last_15m_volume_ratio": [1.1, 0.7],
            "support_break_count": [0, 2],
        }
    )
    ledger = pd.DataFrame(
        {
            "signal_id": ["a", "b"],
            "status": ["closed", "closed"],
            "net_return_pct": [5.0, -3.0],
        }
    )

    diagnostics = build_hybrid_feature_diagnostics(candidates, features, ledger)

    assert diagnostics["closed_trades"] == 2
    assert diagnostics["winning_trades"] == 1
    assert diagnostics["losing_trades"] == 1
    assert diagnostics["numeric"]["volume_ratio_prior5"]["winner_mean"] == 1.2
    assert diagnostics["numeric"]["volume_ratio_prior5"]["loser_mean"] == 0.6
    assert diagnostics["categorical"]["active_direction"]["GOLD"]["win_rate_pct"] == 100.0
    assert diagnostics["categorical"]["active_direction"]["SILVER"]["win_rate_pct"] == 0.0


def _report_tail_ledger() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": "signal-a",
                "signal_id": "signal-a",
                "entry_date": date(2025, 1, 2),
                "block": 1,
                "status": "closed",
                "reason": None,
                "net_return_pct": 2.0,
                "double_cost_net_return_pct": 1.7,
            },
            {
                "event_id": "signal-c",
                "signal_id": "signal-c",
                "entry_date": date(2025, 1, 8),
                "block": 2,
                "status": "closed",
                "reason": None,
                "net_return_pct": -1.0,
                "double_cost_net_return_pct": -1.3,
            },
            {
                "event_id": "signal-d",
                "signal_id": "signal-d",
                "entry_date": date(2025, 1, 10),
                "block": 5,
                "status": "unavailable",
                "reason": "incomplete_d_or_d1_5m",
                "net_return_pct": None,
                "double_cost_net_return_pct": None,
            },
        ]
    )


def _report_manifest(*, complete: int) -> pd.DataFrame:
    rows = []
    for index in range(6):
        rows.append(
            {
                "event_id": f"pair-{index}",
                "source_date": date(2025, 1, 2),
                "entry_date": date(2025, 1, 2 + index),
                "vt_symbol": "600001.SSE",
                "pair_role": "signal" if index % 2 == 0 else "next_session",
                "status": "complete" if index < complete else "missing",
            }
        )
    return pd.DataFrame(rows)


def _report_cash_comparison() -> dict[str, dict[str, object]]:
    return {
        f"capacity_{capacity}": {
            "capacity": capacity,
            "initial_cash": 100_000.0,
            "final_equity": 100_000.0 + capacity * 1_000.0,
            "compound_return_pct": float(capacity),
            "maximum_drawdown_pct": -float(capacity),
            "signals": 3,
            "accepted_entries": capacity,
            "closed_trades": capacity,
            "cash_win_rate_pct": 50.0,
            "skipped_entries": 3 - min(capacity, 3),
            "rejected_entries": 0,
            "unclosed_trades": 0,
            "total_fees": float(capacity * 10),
            "reason_counts": {},
        }
        for capacity in range(1, 5)
    }


def _report_hybrid_ledger() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "signal_id": ["signal-a", "signal-c"],
            "status": ["closed", "closed"],
            "reason": [None, None],
            "net_return_pct": [4.0, -2.0],
        }
    )


def _report_hybrid_diagnostics() -> dict[str, object]:
    return {
        "closed_trades": 2,
        "winning_trades": 1,
        "losing_trades": 1,
        "numeric": {
            "volume_ratio_prior5": {
                "winner_mean": 1.2,
                "loser_mean": 0.6,
                "winner_median": 1.2,
                "loser_median": 0.6,
                "winner_minus_loser_mean": 0.6,
            }
        },
        "categorical": {
            "active_direction": {
                "GOLD": {"trades": 1, "win_rate_pct": 100.0, "mean_net_return_pct": 4.0},
                "SILVER": {"trades": 1, "win_rate_pct": 0.0, "mean_net_return_pct": -2.0},
            }
        },
        "selection_effect": "diagnostic_only",
    }


def _report_cutoff_audit() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "signal_id": ["signal-a", "signal-c"],
            "provisional_ma5_at_1450": [10.0, 11.0],
            "prior_close_count": [4, 4],
            "cutoff_reclaimed_provisional_ma5": [True, True],
            "cutoff_not_below_previous_close": [True, True],
            "cutoff_approached_provisional_ma5": [True, True],
            "cutoff_pullback_known": [True, True],
            "cutoff_reference_peak_preexists": [True, True],
            "cutoff_recognition_passed": [True, True],
        }
    )


def test_report_keeps_concrete_contract_and_formal_nulls() -> None:
    attribution = _attribution_ledger()
    candidates = select_scheme_candidates(attribution)
    report = build_leader_ma5_scheme_report(
        attribution_ledger=attribution,
        candidates=candidates,
        minute_manifest=_report_manifest(complete=6),
        tail_ledger=_report_tail_ledger(),
        cash_comparison=_report_cash_comparison(),
        tail_structural_cash_comparison=_report_cash_comparison(),
        tail_structural_trade_ledger=_report_hybrid_ledger(),
        hybrid_feature_diagnostics=_report_hybrid_diagnostics(),
        cutoff_recognition_audit=_report_cutoff_audit(),
        input_fingerprints={"test": {"digest": "sha256:test"}},
    )

    payload = render_leader_ma5_scheme_json(report)
    markdown = render_leader_ma5_scheme_markdown(report)

    assert report["scheme_version"] == "leader-ma5-recognition-v1"
    assert report["scheme_contract"]["recognition_gate"] == (
        "strong_days_ge_9_5pct >= 1"
    )
    assert report["scheme_contract"]["portfolio_capacity"] == 4
    assert report["scheme_contract"]["holding_style"] == (
        "multi-session swing; no fixed D+1 exit"
    )
    assert "fixed_1035_test_exit" not in report["scheme_contract"]
    assert report["execution_decision"]["forward_shadow"]["status"] == (
        "frozen_research_candidate_not_production"
    )
    assert report["rejected_experiments"]["fixed_d1_1035_exit"]["status"] == (
        "rejected_not_current_contract"
    )
    assert report["coverage"]["parent_ma5_rows"] == 4
    assert report["coverage"]["scheme_candidate_rows"] == 3
    assert report["coverage"]["minute_complete_pairs"] == 6
    assert report["formal_metrics"] is None
    assert report["formal_strategy"] is False
    assert tuple(report["structural_cash_comparison"]) == (
        "capacity_1",
        "capacity_2",
        "capacity_3",
        "capacity_4",
    )
    assert tuple(report["tail_structural_cash_comparison"]) == (
        "capacity_1",
        "capacity_2",
        "capacity_3",
        "capacity_4",
    )
    assert report["cutoff_recognition_audit"]["audited_signals"] == 2
    assert report["cutoff_recognition_audit"]["passed_signals"] == 2
    assert report["hybrid_feature_diagnostics"]["selection_effect"] == (
        "diagnostic_only"
    )
    assert len(report["individual_case_ledger"]) == 3
    assert '"formal_metrics": null' in payload
    assert "D 14:55" in markdown
    assert "Tested fixed exit" not in markdown
    assert "Rejected Experiment: Fixed D+1 Exit" in markdown
    assert "D+1 10:35" in markdown
    assert "Primary exit: `after either the first later daily high above the reference peak or the second consecutive close below MA20, sell at the next stock-session open`" in markdown
    assert "Initial cash: `100000.00 CNY`" in markdown
    assert "| `1` | 1 | 2 | 0 | 101000.00 | 1.0000% | -1.0000%" in markdown
    assert "D 14:55 Entry To Structural Exit Cash Account" in markdown
    assert "Parent/scheme rows: `4/3`" in markdown
    assert "Parent/scheme rows: `57/35`" not in markdown


def test_report_retains_forward_candidate_with_partial_old_minute_coverage() -> None:
    attribution = _attribution_ledger()
    candidates = select_scheme_candidates(attribution)

    report = build_leader_ma5_scheme_report(
        attribution_ledger=attribution,
        candidates=candidates,
        minute_manifest=_report_manifest(complete=5),
        tail_ledger=_report_tail_ledger(),
        cash_comparison=_report_cash_comparison(),
        tail_structural_cash_comparison=_report_cash_comparison(),
        tail_structural_trade_ledger=_report_hybrid_ledger(),
        hybrid_feature_diagnostics=_report_hybrid_diagnostics(),
        cutoff_recognition_audit=_report_cutoff_audit(),
        input_fingerprints={},
    )

    assert report["research_status"] == (
        "forward_shadow_candidate_partial_historical_minute_coverage"
    )
    assert report["formal_metrics"] is None


def test_real_frozen_scheme_candidate_count_and_gate() -> None:
    candidates = load_frozen_scheme_candidates()

    assert len(candidates) == 35
    assert candidates["strong_days_ge_9_5pct"].ge(1).all()


def test_cli_exposes_fixed_scheme_manifest_backfill_and_study() -> None:
    parser = build_parser()

    manifest = parser.parse_args(
        ["v2-leader-ma5-scheme-5m-manifest", "--format", "markdown"]
    )
    backfill = parser.parse_args(
        ["v2-leader-ma5-scheme-5m-backfill", "--dry-run", "--max-gaps", "70"]
    )
    study = parser.parse_args(
        ["v2-leader-ma5-scheme-study", "--format", "json"]
    )

    assert manifest.command == "v2-leader-ma5-scheme-5m-manifest"
    assert manifest.format == "markdown"
    assert backfill.command == "v2-leader-ma5-scheme-5m-backfill"
    assert backfill.dry_run is True
    assert backfill.write is False
    assert backfill.max_gaps == 70
    assert study.command == "v2-leader-ma5-scheme-study"
    assert study.format == "json"


def test_cli_scheme_study_has_no_threshold_switches() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            ["v2-leader-ma5-scheme-study", "--strong-days", "2"]
        )

    with pytest.raises(SystemExit):
        parser.parse_args(["v2-leader-ma5-scheme-5m-backfill"])
