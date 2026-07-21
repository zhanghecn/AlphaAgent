from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from alphaagent.server.services.low_suction import cli
from alphaagent.server.services.low_suction.support_reclaim_confirmation import RULE_ID
from alphaagent.server.services.low_suction.support_reclaim_confirmation_study import (
    build_development_diagnostics,
    build_support_reclaim_confirmation_report,
    evaluate_selected_confirmation_rule,
    render_support_reclaim_confirmation_json,
    render_support_reclaim_confirmation_markdown,
)


def test_no_development_nomination_hides_every_late_result() -> None:
    trades = _study_trades(development_wins=20, block_4_return=20.0)
    freeze = {
        "selected_rule": None,
        "development_metrics": {"closed_trades": 120, "win_rate_pct": 20.0},
        "development_double_cost_metrics": {},
        "development_stable_blocks": 0,
        "development_cash_compound_pct": -20.0,
        "nomination_passed": False,
        "failed_gates": ["development_win_rate<=60pct"],
    }

    report = build_support_reclaim_confirmation_report(
        coverage=_coverage(),
        fingerprints={},
        block_boundaries=_boundaries(),
        exact_support_events=pd.DataFrame(),
        confirmation_events=pd.DataFrame(),
        executed_trades=trades,
        development_freeze=freeze,
        validation=None,
        named_case_audit=[],
    )

    assert report["research_status"] == "no_development_confirmation_rule"
    assert report["selected_rule"] is None
    assert report["block_4"] is None
    assert report["block_5"] is None
    assert report["selected_trade_ledger"] == []
    assert report["formal_metrics"] is None
    assert {row["time_block"] for row in report["development_trade_ledger"]} <= {
        "block_1",
        "block_2",
        "block_3",
    }


def test_block_4_failure_keeps_block_5_hidden() -> None:
    trades = _study_trades(development_wins=26, block_4_return=-1.0)
    validation = evaluate_selected_confirmation_rule(
        trades,
        pd.DataFrame(),
        coverage=_coverage(),
    )
    freeze = {
        "selected_rule": RULE_ID,
        "development_metrics": {"closed_trades": 120, "win_rate_pct": 65.0},
        "development_double_cost_metrics": {},
        "development_stable_blocks": 3,
        "development_cash_compound_pct": 25.0,
        "nomination_passed": True,
        "failed_gates": [],
    }

    report = build_support_reclaim_confirmation_report(
        coverage=_coverage(),
        fingerprints={},
        block_boundaries=_boundaries(),
        exact_support_events=pd.DataFrame(),
        confirmation_events=pd.DataFrame(),
        executed_trades=trades,
        development_freeze=freeze,
        validation=validation,
        named_case_audit=[],
    )

    assert report["research_status"] == "block_4_failed"
    assert report["block_4"]["passed"] is False
    assert report["block_5"] is None
    assert {row["time_block"] for row in report["selected_trade_ledger"]} <= {
        "block_1",
        "block_2",
        "block_3",
        "block_4",
    }


def test_environment_freeze_cannot_read_late_block_state_or_returns() -> None:
    trades = _study_trades(development_wins=26, block_4_return=-1.0)
    first = evaluate_selected_confirmation_rule(
        trades,
        pd.DataFrame(),
        coverage=_coverage(),
    )
    polluted = trades.copy()
    late = polluted["time_block"].isin(("block_4", "block_5"))
    polluted.loc[late, "active_direction"] = "SILVER"
    polluted.loc[late, "market_phase"] = "retreat"
    polluted.loc[late, "net_return_pct"] = -99.0

    second = evaluate_selected_confirmation_rule(
        polluted,
        pd.DataFrame(),
        coverage=_coverage(),
    )

    assert first.environment_freeze == second.environment_freeze


def test_block_5_is_evaluated_only_after_block_4_passes() -> None:
    trades = _study_trades(
        development_wins=26,
        block_4_return=2.0,
        block_5_return=-1.0,
    )

    validation = evaluate_selected_confirmation_rule(
        trades,
        pd.DataFrame(),
        coverage=_coverage(),
    )

    assert validation.block_4["passed"] is True
    assert validation.block_5 is not None
    assert validation.block_5["passed"] is False
    assert validation.late_validation_passed is False
    assert validation.qualification["failed_gates"] == ["block_5_failed"]


def test_final_gate_requires_and_accepts_two_material_environments() -> None:
    trades = _study_trades(
        development_wins=26,
        block_4_return=2.0,
        block_5_return=2.0,
        split_environments=True,
    )

    validation = evaluate_selected_confirmation_rule(
        trades,
        _stock_bars(trades),
        coverage={
            "strict_historical_membership_rows": 1,
            "preclose_execution_rows": len(trades),
        },
    )

    assert validation.block_4["passed"] is True
    assert validation.block_5 is not None
    assert validation.block_5["passed"] is True
    assert validation.four_slot_cash["compound_return_pct"] > 60.0
    assert validation.qualification["qualified_material_environments"] == [
        "GOLD|NORMAL|rotation",
        "SILVER|NORMAL|rotation",
    ]
    assert validation.qualification["historical_proxy_gate_passed"] is True
    assert validation.qualification["formal_strategy"] is True


def test_development_diagnostics_never_include_late_blocks() -> None:
    trades = _study_trades(development_wins=26, block_4_return=99.0)

    diagnostics = build_development_diagnostics(trades)

    assert diagnostics["visible_blocks"] == ["block_1", "block_2", "block_3"]
    assert diagnostics["closed_trades"] == 120
    assert {row["dimension"] for row in diagnostics["groups"]} == {
        "support_line",
        "confirmation_delay",
        "signal_return",
        "volume_ratio",
        "dynamic_rank",
    }


def test_renderers_are_deterministic() -> None:
    report = build_support_reclaim_confirmation_report(
        coverage=_coverage(),
        fingerprints={},
        block_boundaries=_boundaries(),
        exact_support_events=pd.DataFrame(),
        confirmation_events=pd.DataFrame(),
        executed_trades=_study_trades(development_wins=20, block_4_return=20.0),
        development_freeze={
            "selected_rule": None,
            "development_metrics": {},
            "development_double_cost_metrics": {},
            "development_stable_blocks": 0,
            "development_cash_compound_pct": -1.0,
            "nomination_passed": False,
            "failed_gates": ["development_win_rate<=60pct"],
        },
        validation=None,
        named_case_audit=[],
    )

    rendered = render_support_reclaim_confirmation_json(report)

    assert json.loads(rendered)["policy_version"] == (
        "causal-leader-support-reclaim-confirmation-v7"
    )
    assert render_support_reclaim_confirmation_json(json.loads(rendered)) == rendered
    assert "block 5：`未读取`" in render_support_reclaim_confirmation_markdown(report)


def test_named_case_cannot_leak_hidden_block_5_trade_returns() -> None:
    trades = _study_trades(development_wins=20, block_4_return=20.0)
    hidden_return = 987_654.0
    report = build_support_reclaim_confirmation_report(
        coverage=_coverage(),
        fingerprints={},
        block_boundaries=_boundaries(),
        exact_support_events=pd.DataFrame(),
        confirmation_events=pd.DataFrame(),
        executed_trades=trades,
        development_freeze={
            "selected_rule": None,
            "development_metrics": {},
            "development_double_cost_metrics": {},
            "development_stable_blocks": 0,
            "development_cash_compound_pct": -1.0,
            "nomination_passed": False,
            "failed_gates": ["development_win_rate<=60pct"],
        },
        validation=None,
        named_case_audit=[
            {
                "vt_symbol": "600000.SSE",
                "stock_name": "测试龙头",
                "signals": 1,
                "executed_trades": 1,
                "signal_rows": [{"net_return_pct": hidden_return}],
                "trade_rows": [{"net_return_pct": hidden_return}],
            }
        ],
    )

    named_case = report["named_case_audit"][0]
    assert named_case["signal_rows"] == []
    assert named_case["trade_rows"] == []
    assert named_case["executed_trades"] == 0
    assert str(hidden_return) not in json.dumps(report, ensure_ascii=False)


def test_cli_offline_render_does_not_run_database_study(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "validated_output_path", Path)
    report = {
        "study_version": "low-suction-support-reclaim-confirmation-study-v1",
        "policy_version": "causal-leader-support-reclaim-confirmation-v7",
        "research_status": "no_development_confirmation_rule",
        "formal_strategy": False,
        "selected_rule": None,
        "development_freeze": {},
        "block_4": None,
        "block_5": None,
        "qualification": {"failed_gates": []},
        "coverage": {},
        "contract": {},
        "development_diagnostics": {"groups": []},
        "named_case_audit": [],
        "boundaries": [],
        "reproduce": "offline",
    }
    source = tmp_path / "report.json"
    output = tmp_path / "report.md"
    source.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(
        "alphaagent.server.services.low_suction.support_reclaim_confirmation_study.run_support_reclaim_confirmation_study",
        lambda: (_ for _ in ()).throw(AssertionError("database study called")),
    )

    status = cli.main(
        [
            "v7-support-reclaim-confirmation-study",
            "--format",
            "markdown",
            "--input",
            str(source),
            "--output",
            str(output),
        ]
    )

    assert status == 0
    assert "支撑后首次弱转强 V7" in output.read_text(encoding="utf-8")


def test_cli_online_render_runs_database_study_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "validated_output_path", Path)
    calls = 0
    report = {
        "study_version": "low-suction-support-reclaim-confirmation-study-v1",
        "policy_version": "causal-leader-support-reclaim-confirmation-v7",
        "research_status": "no_development_confirmation_rule",
    }

    def run_study() -> dict[str, str]:
        nonlocal calls
        calls += 1
        return report

    monkeypatch.setattr(
        "alphaagent.server.services.low_suction.support_reclaim_confirmation_study.run_support_reclaim_confirmation_study",
        run_study,
    )
    output = tmp_path / "report.json"

    status = cli.main(
        [
            "v7-support-reclaim-confirmation-study",
            "--format",
            "json",
            "--output",
            str(output),
        ]
    )

    assert status == 0
    assert calls == 1
    assert json.loads(output.read_text(encoding="utf-8")) == report


def _study_trades(
    *,
    development_wins: int,
    block_4_return: float,
    block_5_return: float = 2.0,
    split_environments: bool = False,
) -> pd.DataFrame:
    rows = []
    for position in range(180):
        within_block = position % 40
        if position < 120:
            block = f"block_{position // 40 + 1}"
            value = 2.0 if within_block < development_wins else -1.0
        elif position < 150:
            block = "block_4"
            value = block_4_return
        else:
            block = "block_5"
            value = block_5_return
        entry_date = pd.Timestamp("2024-01-02") + pd.offsets.BDay(position)
        d1_close = 10.0 * (1.0 + (value + 0.2) / 100.0)
        rows.append(
            {
                "rule_id": RULE_ID,
                "signal_id": f"signal-{position}",
                "campaign_id": f"campaign-{position}",
                "sector_id": f"BK{position % 20:04d}",
                "concept_name": f"概念{position % 20}",
                "vt_symbol": f"600{position:03d}.SSE",
                "stock_name": f"样本{position}",
                "signal_date": entry_date,
                "entry_date": entry_date,
                "exit_date": entry_date + pd.offsets.BDay(1),
                "entry_price": 10.0,
                "d1_close": d1_close,
                "d1_net_return_pct": value,
                "net_return_pct": value,
                "round_trip_cost_pct": 0.2,
                "time_block": block,
                "active_direction": (
                    "GOLD"
                    if not split_environments or position % 2 == 0
                    else "SILVER"
                ),
                "danger_state": "NORMAL",
                "market_phase": "rotation",
                "required_support": "ma5" if position % 2 == 0 else "ma10",
                "confirmation_delay_sessions": position % 3 + 1,
                "daily_return_pct": 1.0 + position % 6,
                "volume_ratio_prior5": (0.6, 1.0, 1.8)[position % 3],
                "dynamic_rank": position % 3 + 1,
            }
        )
    return pd.DataFrame(rows)


def _stock_bars(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for trade in trades.to_dict("records"):
        rows.extend(
            [
                {
                    "vt_symbol": trade["vt_symbol"],
                    "trade_date": trade["entry_date"],
                    "close_price": trade["entry_price"],
                },
                {
                    "vt_symbol": trade["vt_symbol"],
                    "trade_date": trade["exit_date"],
                    "close_price": trade["d1_close"],
                },
            ]
        )
    return pd.DataFrame(rows)


def _coverage() -> dict[str, int]:
    return {
        "strict_historical_membership_rows": 0,
        "preclose_execution_rows": 0,
    }


def _boundaries() -> dict[str, pd.Timestamp]:
    dates = pd.to_datetime(
        ["2024-04-01", "2024-08-01", "2024-12-01", "2025-04-01", "2025-08-01"]
    )
    return {f"block_{index}": date for index, date in enumerate(dates, start=1)}
