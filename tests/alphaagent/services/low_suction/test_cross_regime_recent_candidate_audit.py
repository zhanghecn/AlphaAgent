from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.cross_regime_recent_candidate_audit import (
    AUDIT_VERSION,
    RecentCausalReplay,
    archive_recent_candidate_audit,
    build_cross_regime_recent_candidate_audit,
    render_recent_candidate_audit_markdown,
)
from alphaagent.server.services.low_suction.forward_ma5_pullback import (
    FORWARD_MA5_CONTRACT_VERSION,
    ForwardMa5Capture,
)
from alphaagent.server.services.low_suction.cli import build_parser
from tests.alphaagent.services.low_suction.test_causal_leader_pullback_forward_repository import (
    ATTEMPTED_AT,
    SIGNAL_DATE,
    SOURCE_DATE,
    _complete_capture,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
AUDIT_EVALUATED_AT = datetime(2026, 7, 22, 19, 0, tzinfo=SHANGHAI)


def _audit_capture() -> ForwardMa5Capture:
    capture = _complete_capture()
    signal = {
        "signal_id": "signal-1",
        "campaign_id": "campaign-1",
        "sector_id": "BK_TEST",
        "concept_name": "测试概念",
        "vt_symbol": "000001.SZSE",
        "stock_name": "测试龙头",
        "signal_date": SIGNAL_DATE.isoformat(),
        "signal_close": 10.0,
        "signal_low": 9.9,
        "support_price": 9.8,
        "reference_peak_price": 10.5,
        "dynamic_rank": 1,
        "dynamic_top3": True,
        "wave_number": 1,
        "support_line": "ma5",
        "active_direction": "GOLD",
        "danger_state": "NORMAL",
        "market_phase": "rotation",
    }
    row = replace(
        capture.rows[0],
        vt_symbol="000001.SZSE",
        stock_name="测试龙头",
        sector_id="BK_TEST",
        sector_name="测试概念",
        rank=1,
        current_wave_number=1,
        support_line="ma5",
        support_price=9.8,
        line_distance_low_pct=(9.9 / 9.8 - 1.0) * 100.0,
        line_distance_close_pct=(10.0 / 9.8 - 1.0) * 100.0,
        decision_reason="eligible_rotation_strong_reclaim",
        raw={"signal": signal},
    )
    scope = replace(
        capture.scopes[0],
        raw={
            "signal_funnel": {
                "base_confirmation": 2,
                "gold_strong_reclaim": 1,
                "v3_cross_regime_support_reclaim": 1,
                "warming_support_relevance": 1,
            }
        },
    )
    return replace(capture, rows=(row,), scopes=(scope,))


def _replay() -> RecentCausalReplay:
    bars = pd.DataFrame(
        [
            {
                "vt_symbol": "000001.SZSE",
                "trade_date": SIGNAL_DATE,
                "close_price": 10.0,
            },
            {
                "vt_symbol": "000001.SZSE",
                "trade_date": date(2026, 7, 22),
                "close_price": 10.5,
            },
        ]
    )
    outcomes = pd.DataFrame(
        [
            {
                "vt_symbol": "000001.SZSE",
                "signal_trade_date": SIGNAL_DATE,
                "status": "closed",
                "terminal": True,
                "exit_date": date(2026, 7, 22),
                "exit_reason": "higher_high_confirmed",
                "net_return_pct": 4.8,
            }
        ]
    )
    return RecentCausalReplay(
        source_trade_date=SOURCE_DATE,
        signal_trade_date=SIGNAL_DATE,
        capture=_audit_capture(),
        observed_stock_bars=bars,
        outcomes=outcomes,
    )


def _legacy_candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "contract_version": FORWARD_MA5_CONTRACT_VERSION,
                "signal_trade_date": date(2026, 7, 17),
                "identity_mode": "cumulative_gain",
                "vt_symbol": "000001.SZSE",
                "signal_eligible": False,
            },
            {
                "contract_version": FORWARD_MA5_CONTRACT_VERSION,
                "signal_trade_date": date(2026, 7, 20),
                "identity_mode": "gain_persistence",
                "vt_symbol": "600001.SSE",
                "signal_eligible": True,
            },
        ]
    )


def test_recent_audit_separates_legacy_shadow_from_causal_replay() -> None:
    report = build_cross_regime_recent_candidate_audit(
        legacy_scopes=pd.DataFrame(),
        legacy_candidates=_legacy_candidates(),
        legacy_outcomes=pd.DataFrame(),
        causal_replays=(_replay(),),
        as_of_date=date(2026, 7, 22),
        evaluated_at=AUDIT_EVALUATED_AT,
    )

    assert report["audit_version"] == AUDIT_VERSION
    assert report["legacy_shadow"] == {
        "contract_version": FORWARD_MA5_CONTRACT_VERSION,
        "forward_sample": True,
        "scope_rows": 0,
        "candidate_rows": 2,
        "signal_rows": 1,
        "outcome_rows": 0,
        "signal_trade_dates": ["2026-07-17", "2026-07-20"],
        "identity_modes": ["cumulative_gain", "gain_persistence"],
        "formal_metrics": None,
    }
    causal = report["causal_replay"]
    assert causal["forward_sample"] is False
    assert causal["candidate_rows"] == 1
    assert causal["signal_rows"] == 1
    assert causal["signal_funnel"] == {
        "base_confirmation": 2,
        "gold_strong_reclaim": 1,
        "v3_cross_regime_support_reclaim": 1,
        "warming_support_relevance": 1,
    }
    assert causal["rejection_reason_counts"] == {
        "eligible_rotation_strong_reclaim": 1
    }
    assert causal["replay_dates"] == [
        {
            "source_trade_date": "2026-07-20",
            "signal_trade_date": "2026-07-21",
            "scope_status": "frozen",
            "scope_complete": True,
            "active_concept_count": 1,
            "prior_top3_count": 1,
            "candidate_rows": 1,
            "signal_rows": 1,
        }
    ]
    assert len(causal["individual_cases"]) == 1
    case = causal["individual_cases"][0]
    assert case["vt_symbol"] == "000001.SZSE"
    assert case["market_phase"] == "rotation"
    assert case["support_line"] == "ma5"
    assert case["gates"]["dynamic_top3"] is True
    assert case["gates"]["support_relevance"] is True
    assert case["d1_outcome_observable"] is True
    assert case["d1_net_return_pct"] == pytest.approx(4.8)
    assert case["structural_outcome_observable"] is True
    assert causal["formal_metrics"] is None


def test_each_causal_candidate_must_appear_exactly_once() -> None:
    replay = _replay()
    duplicate = replace(replay, capture=replace(replay.capture, rows=replay.capture.rows * 2))

    with pytest.raises(ValueError, match="candidate identity must be unique"):
        build_cross_regime_recent_candidate_audit(
            legacy_scopes=pd.DataFrame(),
            legacy_candidates=pd.DataFrame(),
            legacy_outcomes=pd.DataFrame(),
            causal_replays=(duplicate,),
            as_of_date=date(2026, 7, 22),
            evaluated_at=AUDIT_EVALUATED_AT,
        )


def test_markdown_states_that_causal_replay_is_not_forward_evidence() -> None:
    report = build_cross_regime_recent_candidate_audit(
        legacy_scopes=pd.DataFrame(),
        legacy_candidates=_legacy_candidates(),
        legacy_outcomes=pd.DataFrame(),
        causal_replays=(_replay(),),
        as_of_date=date(2026, 7, 22),
        evaluated_at=AUDIT_EVALUATED_AT,
    )

    rendered = render_recent_candidate_audit_markdown(report)

    assert "旧 MA5 前向影子" in rendered
    assert "因果点时回放" in rendered
    assert "forward_sample=false" in rendered
    assert "正式胜率和复利：`null`" in rendered
    assert "活跃概念" in rendered
    assert "2026-07-20 | 2026-07-21 | `frozen` | 1 | 1 | 1 | 1" in rendered


def test_archive_is_idempotent_but_refuses_different_bytes(tmp_path) -> None:
    report = build_cross_regime_recent_candidate_audit(
        legacy_scopes=pd.DataFrame(),
        legacy_candidates=_legacy_candidates(),
        legacy_outcomes=pd.DataFrame(),
        causal_replays=(_replay(),),
        as_of_date=date(2026, 7, 22),
        evaluated_at=AUDIT_EVALUATED_AT,
    )
    output = tmp_path / "recent-audit.json"

    first = archive_recent_candidate_audit(report, output)
    second = archive_recent_candidate_audit(report, output)

    assert first == second
    assert output.exists()
    assert output.with_suffix(".md").exists()
    changed = {**report, "as_of_date": "2026-07-23"}
    with pytest.raises(FileExistsError, match="different content"):
        archive_recent_candidate_audit(changed, output)


def test_audit_rejects_an_as_of_date_after_its_execution_clock() -> None:
    with pytest.raises(ValueError, match="cannot precede as_of_date"):
        build_cross_regime_recent_candidate_audit(
            legacy_scopes=pd.DataFrame(),
            legacy_candidates=pd.DataFrame(),
            legacy_outcomes=pd.DataFrame(),
            causal_replays=(),
            as_of_date=date(2026, 7, 22),
            evaluated_at=ATTEMPTED_AT,
        )


def test_cli_registers_cross_regime_forward_and_recent_audit_commands() -> None:
    run = build_parser().parse_args(
        ["v4-cross-regime-forward-run", "--as-of-date", "2026-07-21"]
    )
    report = build_parser().parse_args(
        ["v4-cross-regime-forward-report", "--format", "json"]
    )
    audit = build_parser().parse_args(
        [
            "v4-cross-regime-recent-audit",
            "--as-of-date",
            "2026-07-20",
            "--output",
            "memory/06_backtests/recent.json",
        ]
    )

    assert run.command == "v4-cross-regime-forward-run"
    assert run.as_of_date == date(2026, 7, 21)
    assert report.command == "v4-cross-regime-forward-report"
    assert report.format == "json"
    assert audit.command == "v4-cross-regime-recent-audit"
    assert audit.as_of_date == date(2026, 7, 20)
