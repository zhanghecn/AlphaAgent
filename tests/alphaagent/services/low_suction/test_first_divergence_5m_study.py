from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.event_recognition_5m_study import (
    FROZEN_RULES,
)
from alphaagent.server.services.low_suction.first_divergence_5m_study import (
    STUDY_EVIDENCE_LEVEL,
    build_first_divergence_5m_report,
    build_first_divergence_transitions,
)


def _candidate() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": 1,
                "source_date": date(2025, 7, 3),
                "entry_date": date(2025, 7, 4),
                "planned_exit_date": date(2025, 7, 7),
                "sector_id": "BK0963",
                "concept_name": "商业航天",
                "cycle_id": "cycle-1",
                "vt_symbol": "600001.SSE",
                "recognition_rank": 1,
                "signal_close": 10.0,
                "active_direction": "SILVER",
                "danger_state": "NORMAL",
                "market_phase": "recovery",
            }
        ]
    )


def _minute_bars() -> pd.DataFrame:
    morning = [
        datetime(2025, 7, 4, 9, 35) + timedelta(minutes=5 * index)
        for index in range(24)
    ]
    afternoon = [
        datetime(2025, 7, 4, 13, 5) + timedelta(minutes=5 * index)
        for index in range(24)
    ]
    times = [*morning, *afternoon]
    closes = [9.9, 9.7, 10.05, 10.1, 10.2, *([9.9] * 43)]
    opens = [10.0, 9.9, 9.7, 10.05, 10.1, *closes[5:]]
    return pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": date(2025, 7, 4),
                "bar_time": bar_time,
                "interval": "5m",
                "open_price": open_price,
                "high_price": max(open_price, close_price) + 0.02,
                "low_price": min(open_price, close_price) - 0.02,
                "close_price": close_price,
                "volume": 1_000.0,
                "turnover": close_price * 1_000.0,
                "source": "tdx_public_hq",
            }
            for bar_time, open_price, close_price in zip(
                times,
                opens,
                closes,
                strict=True,
            )
        ]
    )


def test_transitions_reuse_all_frozen_rules_with_new_evidence_level() -> None:
    transitions = build_first_divergence_transitions(
        _candidate(),
        _minute_bars(),
    )

    assert set(transitions["rule"]) == set(FROZEN_RULES)
    assert transitions["evidence_level"].eq(STUDY_EVIDENCE_LEVEL).all()


def test_report_keeps_formal_and_holdout_metrics_locked() -> None:
    report = build_first_divergence_5m_report(
        coverage={"candidate_pairs": 333, "complete_pairs": 333},
        rule_metrics=pd.DataFrame(),
        block_metrics=pd.DataFrame(),
        regime_metrics=pd.DataFrame(),
        minute_fingerprint="sha256:test",
    )

    assert report["formal_metrics"] is None
    assert report["formal_rule_selected"] is False
    assert report["holdout_price_values_read"] is False
    assert report["overall_conclusion"] == "no_first_divergence_5m_edge"


def test_study_cli_exposes_no_tunable_research_parameters() -> None:
    args = build_parser().parse_args(
        ["v2-first-divergence-5m-study", "--format", "json"]
    )

    assert args.command == "v2-first-divergence-5m-study"
    for parameter in ("horizon", "rules", "threshold", "exit", "start", "end"):
        assert not hasattr(args, parameter)
