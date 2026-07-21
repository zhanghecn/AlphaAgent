from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from alphaagent.server.services.low_suction import cli
from alphaagent.server.services.low_suction.leader_tenure_study import (
    POLICY_VERSION,
    STUDY_VERSION,
    build_leader_tenure_report,
    evaluate_tenure_confirmations,
    render_leader_tenure_json,
    render_leader_tenure_markdown,
)


def test_development_failure_never_executes_late_blocks() -> None:
    events, returns = _events(development_wins=15, block_4_return=99.0)
    executor, calls = _executor(returns)

    evaluation = evaluate_tenure_confirmations(
        events,
        pd.DataFrame(),
        coverage=_coverage(),
        executor=executor,
        cash_simulator=_positive_cash,
    )

    assert calls == [{"block_1", "block_2", "block_3"}]
    assert evaluation.development_freeze["selected_rule"] is None
    assert evaluation.block_4 is None
    assert evaluation.block_5 is None
    assert set(evaluation.visible_trades["time_block"]) <= {
        "block_1",
        "block_2",
        "block_3",
    }


def test_block_4_failure_never_executes_block_5() -> None:
    events, returns = _events(development_wins=30, block_4_return=-1.0)
    executor, calls = _executor(returns)

    evaluation = evaluate_tenure_confirmations(
        events,
        pd.DataFrame(),
        coverage=_coverage(),
        executor=executor,
        cash_simulator=_positive_cash,
    )

    assert calls == [
        {"block_1", "block_2", "block_3"},
        {"block_4"},
    ]
    assert evaluation.development_freeze["selected_rule"] is not None
    assert evaluation.block_4["passed"] is False
    assert evaluation.block_5 is None
    assert set(evaluation.visible_trades["time_block"]) <= {
        "block_1",
        "block_2",
        "block_3",
        "block_4",
    }


def test_block_5_executes_only_after_block_4_passes() -> None:
    events, returns = _events(
        development_wins=30,
        block_4_return=2.0,
        block_5_return=-1.0,
    )
    executor, calls = _executor(returns)

    evaluation = evaluate_tenure_confirmations(
        events,
        pd.DataFrame(),
        coverage=_coverage(),
        executor=executor,
        cash_simulator=_positive_cash,
    )

    assert calls == [
        {"block_1", "block_2", "block_3"},
        {"block_4"},
        {"block_5"},
    ]
    assert evaluation.block_4["passed"] is True
    assert evaluation.block_5 is not None
    assert evaluation.block_5["passed"] is False
    assert evaluation.qualification["failed_gates"] == ["block_5_failed"]


def test_report_hides_unopened_late_outcomes_and_is_deterministic() -> None:
    events, returns = _events(development_wins=15, block_4_return=987_654.0)
    executor, _ = _executor(returns)
    evaluation = evaluate_tenure_confirmations(
        events,
        pd.DataFrame(),
        coverage=_coverage(),
        executor=executor,
        cash_simulator=_positive_cash,
    )
    report = build_leader_tenure_report(
        coverage=_coverage(),
        fingerprints={},
        block_boundaries=_boundaries(),
        identity_diagnostics={"raw_path_rows": 10, "tenure_path_rows": 10},
        event_counts={"primary_confirmations": len(events)},
        evaluation=evaluation,
        named_case_audit=[],
    )

    rendered = render_leader_tenure_json(report)

    assert report["selected_rule"] is None
    assert report["block_4"] is None
    assert report["block_5"] is None
    assert report["formal_metrics"] is None
    assert "987654" not in rendered
    assert render_leader_tenure_json(json.loads(rendered)) == rendered
    assert "block 5：`未读取`" in render_leader_tenure_markdown(report)


def test_cli_offline_render_does_not_run_database_study(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "validated_output_path", Path)
    report = _minimal_report()
    source = tmp_path / "report.json"
    output = tmp_path / "report.md"
    source.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(
        "alphaagent.server.services.low_suction.leader_tenure_study.run_leader_tenure_study",
        lambda: (_ for _ in ()).throw(AssertionError("database study called")),
    )

    status = cli.main(
        [
            "v8-leader-tenure-study",
            "--format",
            "markdown",
            "--input",
            str(source),
            "--output",
            str(output),
        ]
    )

    assert status == 0
    assert "因果龙头任期 V8" in output.read_text(encoding="utf-8")


def test_cli_online_render_runs_database_study_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli, "validated_output_path", Path)
    calls = 0
    report = _minimal_report()

    def run_study() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return report

    monkeypatch.setattr(
        "alphaagent.server.services.low_suction.leader_tenure_study.run_leader_tenure_study",
        run_study,
    )
    output = tmp_path / "report.json"

    status = cli.main(
        [
            "v8-leader-tenure-study",
            "--format",
            "json",
            "--output",
            str(output),
        ]
    )

    assert status == 0
    assert calls == 1
    assert json.loads(output.read_text(encoding="utf-8")) == report


def _events(
    *,
    development_wins: int,
    block_4_return: float,
    block_5_return: float = 2.0,
) -> tuple[pd.DataFrame, dict[str, float]]:
    rows: list[dict[str, object]] = []
    returns: dict[str, float] = {}
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
        signal_id = f"signal-{position}"
        rows.append(
            {
                "rule_id": "support_reclaim_first_weak_to_strong",
                "signal_id": signal_id,
                "campaign_id": f"campaign-{position}",
                "sector_id": f"BK{position % 20:04d}",
                "concept_name": f"概念{position % 20}",
                "vt_symbol": f"600{position:03d}.SSE",
                "stock_name": f"样本{position}",
                "signal_date": pd.Timestamp("2024-01-02")
                + pd.offsets.BDay(position),
                "close_price": 10.0,
                "dynamic_rank": position % 3 + 1,
                "confirmation_delay_sessions": 1,
                "required_support": "ma5",
                "daily_return_pct": 2.0,
                "volume_ratio_prior5": 1.0,
                "time_block": block,
                "active_direction": "GOLD",
                "danger_state": "NORMAL",
                "market_phase": "rotation",
            }
        )
        returns[signal_id] = value
    return pd.DataFrame(rows), returns


def _executor(returns: dict[str, float]):
    calls: list[set[str]] = []

    def execute(events: pd.DataFrame, _bars: pd.DataFrame) -> pd.DataFrame:
        calls.append(set(events["time_block"].astype(str)))
        rows = []
        for event in events.to_dict("records"):
            value = returns[str(event["signal_id"])]
            entry_date = pd.Timestamp(event["signal_date"])
            d1_close = 10.0 * (1.0 + (value + 0.2) / 100.0)
            rows.append(
                {
                    **event,
                    "entry_date": entry_date,
                    "entry_price": 10.0,
                    "d1_date": entry_date + pd.offsets.BDay(1),
                    "d1_close": d1_close,
                    "d1_net_return_pct": value,
                    "exit_date": entry_date + pd.offsets.BDay(1),
                    "exit_price": d1_close,
                    "net_return_pct": value,
                    "round_trip_cost_pct": 0.2,
                }
            )
        return pd.DataFrame(rows)

    return execute, calls


def _positive_cash(_trades: pd.DataFrame, _bars: pd.DataFrame) -> dict[str, object]:
    return {
        "compound_return_pct": 25.0,
        "maximum_drawdown_pct": -5.0,
    }


def _coverage() -> dict[str, int]:
    return {
        "strict_historical_membership_rows": 0,
        "preclose_execution_rows": 0,
    }


def _boundaries() -> dict[str, pd.Timestamp]:
    return {
        f"block_{index}": pd.Timestamp("2024-01-01")
        + pd.offsets.BDay(index * 40)
        for index in range(1, 6)
    }


def _minimal_report() -> dict[str, object]:
    return {
        "study_version": STUDY_VERSION,
        "policy_version": POLICY_VERSION,
        "research_status": "no_development_tenure_rule",
        "formal_strategy": False,
        "formal_metrics": None,
        "selected_rule": None,
        "coverage": {},
        "contract": {},
        "identity_diagnostics": {},
        "event_counts": {},
        "development_freeze": {},
        "environment_freeze": {},
        "block_4": None,
        "block_5": None,
        "qualification": {"failed_gates": []},
        "named_case_audit": [],
        "boundaries": [],
        "reproduce": "offline",
    }
