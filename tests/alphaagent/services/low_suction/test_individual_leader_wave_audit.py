from __future__ import annotations

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.individual_leader_wave_audit import (
    LeaderCampaignCase,
    _validate_campaign_cases,
    build_individual_leader_wave_report,
    build_case_hypothesis_replays,
    build_support_candidate_ledger,
    execute_d1_loss_exit_trades,
    find_price_volume_ignitions,
    render_individual_leader_wave_markdown,
)
from alphaagent.server.services.low_suction.cli import build_parser


def test_red_close_can_stabilize_after_a_confirmed_ma5_pullback() -> None:
    features = pd.DataFrame(
        [
            _bar("2026-01-05", 10.00, 10.20, 9.90, 10.10),
            _bar("2026-01-06", 10.00, 10.00, 9.40, 9.60),
            _bar("2026-01-07", 9.54, 9.55, 9.45, 9.51),
            _bar("2026-01-08", 9.80, 10.30, 9.75, 10.20),
        ]
    )
    waves = pd.DataFrame(
        [
            _wave(
                peak_date="2026-01-05",
                peak_price=10.20,
                higher_high_date="2026-01-08",
            )
        ]
    )

    candidates = build_support_candidate_ledger(features, waves)

    assert candidates["signal_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-01-07"
    ]
    candidate = candidates.iloc[0]
    assert candidate["support_line"] == "ma5"
    assert not bool(candidate["signal_close_not_below_previous"])
    assert candidate["close_location"] > 0.50


def test_d1_loss_exits_and_reentry_requires_new_pullback_information() -> None:
    features = pd.DataFrame(
        [
            _bar("2026-01-05", 10.00, 10.20, 9.90, 10.10),
            _bar("2026-01-06", 9.80, 9.90, 9.40, 9.70),
            _bar("2026-01-07", 9.70, 9.80, 9.50, 9.60),
            _bar("2026-01-08", 9.50, 9.60, 9.10, 9.30),
            _bar("2026-01-09", 9.20, 9.70, 9.00, 9.60),
            _bar("2026-01-12", 9.70, 10.00, 9.60, 9.90),
            _bar("2026-01-13", 10.10, 10.40, 10.00, 10.30),
        ]
    )
    candidates = pd.DataFrame(
        [
            _candidate("2026-01-06", 9.70, 9.40, 1),
            _candidate("2026-01-07", 9.60, 9.40, 1),
            _candidate("2026-01-09", 9.60, 9.00, 2),
        ]
    )
    candidates["signal_date"] = pd.to_datetime(candidates["signal_date"])
    waves = pd.DataFrame(
        [
            _wave(
                peak_date="2026-01-05",
                peak_price=10.20,
                higher_high_date="2026-01-13",
            )
        ]
    )

    trades = execute_d1_loss_exit_trades(candidates, features, waves)

    assert trades["entry_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-01-06",
        "2026-01-09",
    ]
    first, second = trades.iloc[0], trades.iloc[1]
    assert first["exit_reason"] == "d1_loss_stop"
    assert first["net_return_pct"] == pytest.approx(-1.230927835, rel=1e-6)
    assert first["loss_cause"] == "entry_too_early"
    assert second["exit_reason"] == "higher_high_confirmed"
    assert second["net_return_pct"] == pytest.approx(7.091666667, rel=1e-6)


def test_structure_recovery_can_create_a_later_entry_in_the_same_wave() -> None:
    first = _bar("2026-01-05", 10.00, 10.20, 9.90, 10.10)
    broken = _bar("2026-01-06", 8.70, 8.90, 8.40, 8.60)
    broken["structural_break"] = True
    recovered = _bar("2026-01-07", 9.70, 9.90, 9.70, 9.80)
    features = pd.DataFrame(
        [first, broken, recovered, _bar("2026-01-08", 10.10, 10.40, 10.00, 10.30)]
    )
    waves = pd.DataFrame(
        [
            _wave(
                peak_date="2026-01-05",
                peak_price=10.20,
                higher_high_date="2026-01-08",
            )
        ]
    )

    candidates = build_support_candidate_ledger(features, waves)

    assert candidates["signal_date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-01-07"
    ]
    assert bool(candidates.iloc[0]["structure_reclaimed_today"])


def test_positive_d1_exits_at_a_causal_break_before_a_later_higher_high() -> None:
    features = pd.DataFrame(
        [
            _bar("2026-01-05", 10.00, 10.20, 9.90, 10.10),
            _bar("2026-01-06", 9.60, 9.80, 9.40, 9.70),
            _bar("2026-01-07", 9.80, 10.00, 9.70, 9.90),
            {
                **_bar("2026-01-08", 9.40, 9.50, 9.20, 9.30),
                "structural_break": True,
            },
            _bar("2026-01-09", 10.10, 10.40, 10.00, 10.30),
        ]
    )
    candidates = pd.DataFrame([_candidate("2026-01-06", 9.70, 9.40, 1)])
    candidates["signal_date"] = pd.to_datetime(candidates["signal_date"])
    waves = pd.DataFrame(
        [
            _wave(
                peak_date="2026-01-05",
                peak_price=10.20,
                higher_high_date="2026-01-09",
            )
        ]
    )

    trades = execute_d1_loss_exit_trades(candidates, features, waves)

    trade = trades.iloc[0]
    assert trade["d1_net_return_pct"] > 0
    assert trade["exit_date"] == pd.Timestamp("2026-01-08")
    assert trade["exit_reason"] == "structural_break"
    assert bool(trade["later_higher_high_after_exit"])
    assert trade["loss_cause"] == "entry_too_early"


def test_terminal_exit_cannot_precede_a_recovery_entry() -> None:
    features = pd.DataFrame(
        [
            _bar("2026-01-05", 10.00, 10.20, 9.90, 10.10),
            {
                **_bar("2026-01-06", 9.00, 9.20, 8.80, 9.00),
                "structural_break": True,
            },
            _bar("2026-01-07", 9.50, 9.80, 9.40, 9.70),
            _bar("2026-01-08", 9.70, 10.00, 9.60, 9.90),
            {
                **_bar("2026-01-09", 9.20, 9.30, 9.00, 9.10),
                "structural_break": True,
            },
        ]
    )
    candidates = pd.DataFrame([_candidate("2026-01-07", 9.70, 8.80, 2)])
    candidates["signal_date"] = pd.to_datetime(candidates["signal_date"])
    wave = _wave(
        peak_date="2026-01-05",
        peak_price=10.20,
        higher_high_date="2026-01-09",
    )
    wave.update(
        {
            "higher_high_date": pd.NaT,
            "structural_break_date": pd.Timestamp("2026-01-06"),
            "resolution_status": "terminal_failure_observed",
            "observation_end": pd.Timestamp("2026-01-09"),
        }
    )

    trades = execute_d1_loss_exit_trades(
        candidates,
        features,
        pd.DataFrame([wave]),
    )

    trade = trades.iloc[0]
    assert trade["exit_date"] == pd.Timestamp("2026-01-09")
    assert trade["holding_sessions"] == 2


def test_case_hypothesis_filters_candidates_before_replaying() -> None:
    features = pd.DataFrame(
        [
            _bar("2026-01-05", 10.00, 10.20, 9.90, 10.10),
            _bar("2026-01-06", 9.60, 9.80, 9.40, 9.60),
            _bar("2026-01-07", 9.70, 9.90, 9.60, 9.80),
            _bar("2026-01-08", 9.60, 9.90, 9.50, 9.70),
            _bar("2026-01-09", 9.80, 10.10, 9.70, 9.90),
            _bar("2026-01-12", 10.10, 10.40, 10.00, 10.30),
        ]
    )
    candidates = pd.DataFrame(
        [
            {
                **_candidate("2026-01-06", 9.60, 9.40, 1),
                "signal_daily_return_pct": -1.0,
                "signal_volume_ratio_prior5": 0.5,
            },
            {
                **_candidate("2026-01-08", 9.70, 9.40, 1),
                "signal_daily_return_pct": 1.0,
                "signal_volume_ratio_prior5": 1.0,
            },
        ]
    )
    candidates["signal_date"] = pd.to_datetime(candidates["signal_date"])
    waves = pd.DataFrame(
        [
            _wave(
                peak_date="2026-01-05",
                peak_price=10.20,
                higher_high_date="2026-01-12",
            )
        ]
    )

    replays = build_case_hypothesis_replays(candidates, features, waves)

    assert replays["base_support_confirmation"]["entry_date"].tolist() == [
        pd.Timestamp("2026-01-06")
    ]
    assert replays["up_close_non_contraction"]["entry_date"].tolist() == [
        pd.Timestamp("2026-01-08")
    ]


def test_price_volume_ignition_does_not_require_preexisting_ma_alignment() -> None:
    features = pd.DataFrame(
        [
            {
                **_bar("2026-01-15", 9.80, 10.90, 9.75, 10.80),
                "daily_return_pct": 10.0,
                "prior_high20": 10.20,
                "volume_ratio_prior5": 2.0,
                "trend_aligned": False,
            }
        ]
    )

    ignitions = find_price_volume_ignitions(features)

    assert len(ignitions) == 1
    assert ignitions.iloc[0]["trade_date"] == pd.Timestamp("2026-01-15")


def test_report_keeps_case_metrics_descriptive() -> None:
    report = build_individual_leader_wave_report(
        campaign_summaries=pd.DataFrame(
            [
                {
                    "campaign_id": "case-a",
                    "stock_name": "案例股",
                    "vt_symbol": "000001.SZSE",
                    "campaign_start": pd.Timestamp("2026-01-05"),
                    "campaign_end": pd.Timestamp("2026-01-13"),
                    "wave_count": 1,
                    "continued_wave_count": 1,
                    "terminal_wave_count": 0,
                    "campaign_gain_pct": 20.0,
                }
            ]
        ),
        ignition_ledger=pd.DataFrame(),
        daily_ledger=pd.DataFrame(),
        wave_ledger=pd.DataFrame(),
        support_candidates=pd.DataFrame(),
        trades=pd.DataFrame(),
        fingerprints={},
    )

    assert report["formal_strategy"] is False
    assert report["formal_metrics"] is None
    assert report["coverage"]["campaigns"] == 1


def test_markdown_renders_missing_dates_as_dash_instead_of_nat() -> None:
    report = build_individual_leader_wave_report(
        campaign_summaries=pd.DataFrame(),
        ignition_ledger=pd.DataFrame(),
        daily_ledger=pd.DataFrame(),
        wave_ledger=pd.DataFrame(
            [
                {
                    "stock_name": "案例股",
                    "campaign_id": "case-a",
                    "vt_symbol": "000001.SZSE",
                    "wave_number": 1,
                    "peak_date": pd.Timestamp("2026-01-05"),
                    "peak_price": 10.0,
                    "pullback_confirmation_date": pd.Timestamp("2026-01-06"),
                    "trough_date": pd.Timestamp("2026-01-07"),
                    "trough_price": 9.0,
                    "deepest_tested_support": "ma5",
                    "higher_high_date": pd.NaT,
                    "first_structural_break_in_pullback": pd.NaT,
                    "resolution_status": "unresolved_pullback_censored",
                }
            ]
        ),
        support_candidates=pd.DataFrame(),
        trades=pd.DataFrame(),
        fingerprints={},
    )

    rendered = render_individual_leader_wave_markdown(report)

    assert "NaT" not in rendered
    assert "| - | - | `unresolved_pullback_censored` |" in rendered


def test_campaign_cases_reject_non_main_board_symbols() -> None:
    case = LeaderCampaignCase(
        campaign_id="invalid-board",
        vt_symbol="300001.SZSE",
        stock_name="案例股",
        load_start=pd.Timestamp("2025-01-01").date(),
        campaign_start=pd.Timestamp("2025-03-01").date(),
        campaign_end=pd.Timestamp("2025-04-01").date(),
        evidence_end=pd.Timestamp("2025-05-01").date(),
        anchor_basis="test",
    )

    with pytest.raises(ValueError, match="eligible main-board"):
        _validate_campaign_cases((case,))


def test_cli_registers_individual_leader_wave_audit() -> None:
    args = build_parser().parse_args(
        ["v2-individual-leader-wave-audit", "--format", "json"]
    )

    assert args.command == "v2-individual-leader-wave-audit"
    assert args.format == "json"


def _bar(
    trade_date: str,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
) -> dict[str, object]:
    return {
        "vt_symbol": "000001.SZSE",
        "trade_date": pd.Timestamp(trade_date),
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "close_price": close_price,
        "volume": 100.0,
        "daily_return_pct": 0.0,
        "ma5": 9.50,
        "ma10": 9.00,
        "ma20": 8.50,
        "volume_ratio_prior5": 1.0,
        "structural_break": False,
    }


def _wave(
    *,
    peak_date: str,
    peak_price: float,
    higher_high_date: str,
) -> dict[str, object]:
    return {
        "campaign_id": "case-a",
        "vt_symbol": "000001.SZSE",
        "wave_number": 1,
        "wave_start_date": pd.Timestamp(peak_date),
        "peak_date": pd.Timestamp(peak_date),
        "peak_price": peak_price,
        "higher_high_date": pd.Timestamp(higher_high_date),
        "structural_break_date": pd.NaT,
        "resolution_status": "continued_to_higher_high",
        "observation_end": pd.Timestamp(higher_high_date),
    }


def _candidate(
    signal_date: str,
    signal_close: float,
    running_pullback_low: float,
    support_depth: int,
) -> dict[str, object]:
    return {
        "campaign_id": "case-a",
        "vt_symbol": "000001.SZSE",
        "wave_number": 1,
        "signal_date": signal_date,
        "signal_close": signal_close,
        "support_line": "ma5" if support_depth == 1 else "ma10",
        "support_depth": support_depth,
        "running_pullback_low": running_pullback_low,
        "reference_peak_price": 10.20,
    }
