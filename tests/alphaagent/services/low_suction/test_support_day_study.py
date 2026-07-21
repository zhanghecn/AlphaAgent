from __future__ import annotations

import json

import pandas as pd

from alphaagent.server.services.low_suction import cli, support_day_study
from alphaagent.server.services.low_suction.support_day_entry import RULE_EXACT_HOLD
from alphaagent.server.services.low_suction.support_day_study import (
    apply_frozen_environment_policy,
    build_development_diagnostics,
    build_support_day_report,
    evaluate_frozen_rule,
    freeze_development_environments,
    render_support_day_markdown,
)


def test_environment_freeze_ignores_profitable_late_blocks() -> None:
    trades = _environment_trades()

    first = freeze_development_environments(trades)
    changed_late = trades.copy()
    late = changed_late["time_block"].isin(("block_4", "block_5"))
    changed_late.loc[late, "net_return_pct"] *= -1
    second = freeze_development_environments(changed_late)

    assert first == second
    assert first["policy_by_environment"] == {
        "GOLD|NORMAL|rotation": "trade",
        "SILVER|NORMAL|warming": "cash",
    }
    selected = apply_frozen_environment_policy(
        trades, first["policy_by_environment"]
    )
    assert set(selected["active_direction"]) == {"GOLD"}


def test_development_diagnostics_never_read_late_outcomes() -> None:
    trades = _environment_trades()

    first = build_development_diagnostics(trades)
    changed_late = trades.copy()
    late = changed_late["time_block"].isin(("block_4", "block_5"))
    changed_late.loc[late, "net_return_pct"] = 99.0
    second = build_development_diagnostics(changed_late)

    assert first == second
    assert first["blocks"] == ["block_1", "block_2", "block_3"]


def test_frozen_rule_win_rate_must_be_strictly_above_sixty() -> None:
    decision = evaluate_frozen_rule(
        _qualification_trades(winners_per_segment=18),
        cash_result=_cash_result(),
        double_cost_cash_result=_double_cost_cash_result(),
        strict_membership_rows=1,
        preclose_execution_rows=120,
    )

    assert decision["historical_proxy_gate_passed"] is False
    assert "win_rate<=60pct" in decision["failed_gates"]


def test_proxy_can_pass_while_formal_strategy_remains_blocked() -> None:
    decision = evaluate_frozen_rule(
        _qualification_trades(winners_per_segment=20),
        cash_result=_cash_result(),
        double_cost_cash_result=_double_cost_cash_result(),
        strict_membership_rows=0,
        preclose_execution_rows=0,
    )

    assert decision["historical_proxy_gate_passed"] is True
    assert decision["formal_strategy"] is False
    assert decision["formal_metrics"] is None
    assert decision["formal_blockers"] == [
        "strict_historical_membership_missing",
        "executable_preclose_price_missing",
    ]


def test_report_hides_late_evaluation_when_no_rule_was_nominated() -> None:
    report = build_support_day_report(
        coverage={"strict_historical_membership_rows": 0},
        fingerprints={},
        events=pd.DataFrame(),
        rule_events=pd.DataFrame(),
        all_d1_trades=pd.DataFrame(),
        rule_freeze={"selected_rule": None, "candidate_metrics": []},
        environment_freeze={},
        selected_d1_trades=pd.DataFrame(),
        selected_double_cost_trades=pd.DataFrame(),
        cash_result={},
        double_cost_cash_result={},
        structural_trades=pd.DataFrame(),
        named_case_audit=[],
    )

    assert report["selected_rule"] is None
    assert report["research_status"] == "no_development_rule_nominated"
    assert report["late_evaluation"] is None
    assert report["formal_strategy"] is False
    assert report["formal_metrics"] is None
    assert report["development_diagnostics"] == {
        "blocks": ["block_1", "block_2", "block_3"],
        "rule_metrics": [],
        "feature_metrics": [],
        "high_win_groups": [],
        "low_win_groups": [],
        "warning": "development attribution only; groups are not executable rules",
    }


def test_report_persists_only_development_trade_rows() -> None:
    trades = _environment_trades()

    first = _no_nominee_report(trades)
    changed_late = trades.copy()
    changed_late.loc[changed_late["time_block"].eq("block_4"), "net_return_pct"] = 99.0
    second = _no_nominee_report(changed_late)

    assert first["development_trade_ledger"] == second["development_trade_ledger"]
    assert len(first["development_trade_ledger"]) == 60
    assert {row["time_block"] for row in first["development_trade_ledger"]} == {
        "block_1",
        "block_2",
        "block_3",
    }


def test_development_diagnostics_include_stable_high_and_low_combinations() -> None:
    diagnostics = build_development_diagnostics(_diagnostic_trades())

    high = next(
        row
        for row in diagnostics["high_win_groups"]
        if row["feature"] == "signal_return_group+dynamic_rank_group"
        and row["group"] == "6_to_9_5|rank_1"
    )
    low = next(
        row
        for row in diagnostics["low_win_groups"]
        if row["feature"] == "signal_return_group+dynamic_rank_group"
        and row["group"] == "0_to_3|rank_3"
    )

    assert high["win_rate_pct"] == 70.0
    assert high["positive_development_blocks"] == 3
    assert low["win_rate_pct"] == 30.0
    assert low["negative_development_blocks"] == 3
    rendered = render_support_day_markdown(_no_nominee_report(_diagnostic_trades()))
    assert "开发期高胜率分组" in rendered
    assert "6_to_9_5|rank_1" in rendered
    assert "开发期低胜率分组" in rendered


def test_support_day_cli_runs_database_study_once(monkeypatch, capsys) -> None:
    report = {"policy_version": "test-v5"}
    calls: list[str] = []
    monkeypatch.setattr(
        support_day_study,
        "run_support_day_study",
        lambda: calls.append("run") or report,
    )
    monkeypatch.setattr(
        support_day_study,
        "render_support_day_json",
        lambda current: f"json:{current['policy_version']}\n",
    )
    monkeypatch.setattr(
        support_day_study,
        "render_support_day_markdown",
        lambda current: f"markdown:{current['policy_version']}\n",
    )

    args = cli.build_parser().parse_args(
        ["v5-support-day-study", "--format", "json"]
    )
    assert args.command == "v5-support-day-study"
    assert cli.main(["v5-support-day-study", "--format", "markdown"]) == 0
    assert capsys.readouterr().out == "markdown:test-v5\n"
    assert calls == ["run"]


def test_support_day_cli_renders_saved_json_without_database(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    source = tmp_path / "support-day.json"
    source.write_text(json.dumps({"policy_version": "saved-v5"}), encoding="utf-8")

    def fail_if_database_runs():
        raise AssertionError("offline rendering must not run the database study")

    monkeypatch.setattr(
        support_day_study,
        "run_support_day_study",
        fail_if_database_runs,
    )
    monkeypatch.setattr(
        support_day_study,
        "render_support_day_markdown",
        lambda report: f"offline:{report['policy_version']}\n",
    )

    assert (
        cli.main(
            [
                "v5-support-day-study",
                "--input",
                str(source),
                "--format",
                "markdown",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == "offline:saved-v5\n"


def _environment_trades() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    environments = (
        ("GOLD", "rotation", 7, -20.0),
        ("SILVER", "warming", 4, 20.0),
    )
    position = 0
    for direction, phase, development_winners, late_return in environments:
        for block_number in range(1, 4):
            for attempt in range(10):
                rows.append(
                    _trade_row(
                        position,
                        direction=direction,
                        phase=phase,
                        block=f"block_{block_number}",
                        net_return=2.0 if attempt < development_winners else -1.0,
                    )
                )
                position += 1
        for _ in range(10):
            rows.append(
                _trade_row(
                    position,
                    direction=direction,
                    phase=phase,
                    block="block_4",
                    net_return=late_return,
                )
            )
            position += 1
    return pd.DataFrame(rows)


def _qualification_trades(*, winners_per_segment: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    position = 0
    for direction, phase in (("GOLD", "rotation"), ("SILVER", "warming")):
        for block in ("block_4", "block_5"):
            for attempt in range(30):
                rows.append(
                    _trade_row(
                        position,
                        direction=direction,
                        phase=phase,
                        block=block,
                        net_return=2.0 if attempt < winners_per_segment else -1.0,
                    )
                )
                position += 1
    return pd.DataFrame(rows)


def _trade_row(
    position: int,
    *,
    direction: str,
    phase: str,
    block: str,
    net_return: float,
) -> dict[str, object]:
    entry_date = pd.Timestamp("2025-01-02") + pd.Timedelta(days=position)
    return {
        "rule_id": RULE_EXACT_HOLD,
        "signal_id": f"signal-{position}",
        "vt_symbol": f"{600000 + position % 20:06d}.SSE",
        "entry_date": entry_date,
        "exit_date": entry_date + pd.Timedelta(days=1),
        "net_return_pct": net_return,
        "time_block": block,
        "active_direction": direction,
        "danger_state": "NORMAL",
        "market_phase": phase,
    }


def _cash_result() -> dict[str, float]:
    return {"compound_return_pct": 80.0, "maximum_drawdown_pct": -5.0}


def _double_cost_cash_result() -> dict[str, float]:
    return {"compound_return_pct": 20.0, "maximum_drawdown_pct": -7.0}


def _no_nominee_report(trades: pd.DataFrame) -> dict[str, object]:
    return build_support_day_report(
        coverage={"strict_historical_membership_rows": 0},
        fingerprints={},
        events=pd.DataFrame(),
        rule_events=pd.DataFrame(),
        all_d1_trades=trades,
        rule_freeze={"selected_rule": None, "candidate_metrics": []},
        environment_freeze={},
        selected_d1_trades=pd.DataFrame(),
        selected_double_cost_trades=pd.DataFrame(),
        cash_result={},
        double_cost_cash_result={},
        structural_trades=pd.DataFrame(),
        named_case_audit=[],
    )


def _diagnostic_trades() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    position = 0
    for block_number in range(1, 4):
        for attempt in range(10):
            high = _trade_row(
                position,
                direction="GOLD",
                phase="rotation",
                block=f"block_{block_number}",
                net_return=2.0 if attempt < 7 else -1.0,
            )
            high.update(
                daily_return_pct=7.0,
                dynamic_rank=1,
                wave_number=1,
                required_support="ma5",
                volume_ratio_prior5=1.6,
                close_location=0.8,
            )
            rows.append(high)
            position += 1
        for attempt in range(10):
            low = _trade_row(
                position,
                direction="SILVER",
                phase="warming",
                block=f"block_{block_number}",
                net_return=1.0 if attempt < 3 else -2.0,
            )
            low.update(
                daily_return_pct=1.0,
                dynamic_rank=3,
                wave_number=2,
                required_support="ma10",
                volume_ratio_prior5=0.6,
                close_location=0.4,
            )
            rows.append(low)
            position += 1
    return pd.DataFrame(rows)
