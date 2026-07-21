from __future__ import annotations

import json

import pandas as pd

from alphaagent.server.services.low_suction import cli, support_quality_study
from alphaagent.server.services.low_suction.support_quality_study import (
    build_support_quality_report,
    evaluate_selected_quality_rule,
)


def test_report_hides_all_late_evidence_without_development_leaf() -> None:
    report = build_support_quality_report(
        coverage={"strict_historical_membership_rows": 0},
        fingerprints={},
        enriched_events=pd.DataFrame(),
        executed_trades=pd.DataFrame(),
        tree_description=_tree_description(),
        leaf_freeze={"selected_leaf": None, "leaf_metrics": []},
        validation=None,
        named_case_audit=[],
    )

    assert report["selected_leaf"] is None
    assert report["block_4"] is None
    assert report["block_5"] is None
    assert report["environment_freeze"] == {}
    assert report["selected_trade_ledger"] == []
    assert report["formal_metrics"] is None
    assert report["research_status"] == "no_development_quality_leaf"


def test_block_four_failure_keeps_block_five_out_of_report() -> None:
    losing_late = _validation_trades(block_5_return=-99.0)
    winning_late = _validation_trades(block_5_return=99.0)

    first_validation = evaluate_selected_quality_rule(
        losing_late,
        pd.DataFrame(),
        coverage={"strict_historical_membership_rows": 0},
    )
    second_validation = evaluate_selected_quality_rule(
        winning_late,
        pd.DataFrame(),
        coverage={"strict_historical_membership_rows": 0},
    )
    first = _selected_report(losing_late, first_validation)
    second = _selected_report(winning_late, second_validation)

    assert first == second
    assert first["block_4"]["passed"] is False
    assert first["block_5"] is None
    assert first["four_slot_cash"] == {}
    assert {row["time_block"] for row in first["selected_trade_ledger"]} == {
        "block_1",
        "block_2",
        "block_3",
        "block_4",
    }


def test_final_proxy_gate_requires_two_material_profitable_environments() -> None:
    trades = _passing_validation_trades()

    validation = evaluate_selected_quality_rule(
        trades,
        _stock_bars_for(trades),
        coverage={
            "strict_historical_membership_rows": 0,
            "preclose_execution_rows": 0,
        },
    )

    assert validation.block_4["passed"] is True
    assert validation.block_5 is not None
    assert validation.block_5["passed"] is True
    assert validation.qualification["historical_proxy_gate_passed"] is True
    assert validation.qualification["formal_strategy"] is False
    assert validation.qualification["formal_metrics"] is None
    assert len(
        validation.qualification["qualified_material_environments"]
    ) == 2
    assert validation.four_slot_cash["compound_return_pct"] > 60.0
    assert validation.four_slot_cash["maximum_drawdown_pct"] >= -10.0


def test_support_quality_cli_runs_database_study_once(monkeypatch, capsys) -> None:
    report = {"policy_version": "test-v6"}
    calls: list[str] = []
    monkeypatch.setattr(
        support_quality_study,
        "run_support_quality_study",
        lambda: calls.append("run") or report,
    )
    monkeypatch.setattr(
        support_quality_study,
        "render_support_quality_json",
        lambda current: f"json:{current['policy_version']}\n",
    )
    monkeypatch.setattr(
        support_quality_study,
        "render_support_quality_markdown",
        lambda current: f"markdown:{current['policy_version']}\n",
    )

    args = cli.build_parser().parse_args(
        ["v6-support-quality-study", "--format", "json"]
    )
    assert args.command == "v6-support-quality-study"
    assert cli.main(["v6-support-quality-study", "--format", "markdown"]) == 0
    assert capsys.readouterr().out == "markdown:test-v6\n"
    assert calls == ["run"]


def test_support_quality_cli_renders_saved_json_without_database(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    source = tmp_path / "support-quality.json"
    source.write_text(json.dumps({"policy_version": "saved-v6"}), encoding="utf-8")

    def fail_if_database_runs():
        raise AssertionError("offline rendering must not run the database study")

    monkeypatch.setattr(
        support_quality_study,
        "run_support_quality_study",
        fail_if_database_runs,
    )
    monkeypatch.setattr(
        support_quality_study,
        "render_support_quality_markdown",
        lambda report: f"offline:{report['policy_version']}\n",
    )

    assert (
        cli.main(
            [
                "v6-support-quality-study",
                "--input",
                str(source),
                "--format",
                "markdown",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == "offline:saved-v6\n"


def _selected_report(
    trades: pd.DataFrame,
    validation: support_quality_study.QualityValidation,
) -> dict[str, object]:
    return build_support_quality_report(
        coverage={"strict_historical_membership_rows": 0},
        fingerprints={},
        enriched_events=pd.DataFrame(),
        executed_trades=trades,
        tree_description=_tree_description(),
        leaf_freeze={
            "selected_leaf": {
                "rule_id": "support_quality_leaf_2",
                "leaf_node": 2,
                "conditions": [
                    {
                        "feature": "leg_gain_pct",
                        "operator": ">",
                        "threshold": 10.0,
                    }
                ],
            },
            "leaf_metrics": [],
        },
        validation=validation,
        named_case_audit=[],
    )


def _tree_description() -> dict[str, object]:
    return {
        "tree_contract": {
            "max_depth": 2,
            "min_samples_leaf": 100,
            "random_state": 0,
        },
        "features": ["leg_gain_pct"],
        "development_rows": 120,
        "incomplete_feature_rows": 0,
        "leaves": [],
        "model_fingerprint": "sha256:test",
    }


def _validation_trades(*, block_5_return: float) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    position = 0
    for block_number in range(1, 4):
        for attempt in range(40):
            rows.append(
                _trade_row(
                    position,
                    block=f"block_{block_number}",
                    net_return=2.0 if attempt < 28 else -1.0,
                )
            )
            position += 1
    for _attempt in range(30):
        rows.append(
            _trade_row(position, block="block_4", net_return=-1.0)
        )
        position += 1
    for _attempt in range(30):
        rows.append(
            _trade_row(
                position,
                block="block_5",
                net_return=block_5_return,
            )
        )
        position += 1
    return pd.DataFrame.from_records(rows)


def _passing_validation_trades() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    position = 0
    environments = (
        ("GOLD", "rotation", "BK0001"),
        ("SILVER", "warming", "BK0002"),
    )
    for block_number in range(1, 6):
        for direction, phase, sector_id in environments:
            for attempt in range(30):
                row = _trade_row(
                    position,
                    block=f"block_{block_number}",
                    net_return=2.0 if attempt < 21 else -1.0,
                )
                row.update(
                    active_direction=direction,
                    market_phase=phase,
                    sector_id=sector_id,
                    vt_symbol=f"{600000 + position:06d}.SSE",
                )
                rows.append(row)
                position += 1
    return pd.DataFrame.from_records(rows)


def _stock_bars_for(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
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
    return pd.DataFrame.from_records(rows)


def _trade_row(
    position: int,
    *,
    block: str,
    net_return: float,
) -> dict[str, object]:
    entry_date = pd.Timestamp("2024-01-02") + pd.Timedelta(days=position)
    return {
        "rule_id": "support_day_exact_hold",
        "signal_id": f"quality-{position:04d}",
        "campaign_id": 1,
        "sector_id": "BK0001",
        "concept_name": "测试概念",
        "vt_symbol": f"{600000 + position % 20:06d}.SSE",
        "stock_name": f"测试股票{position % 20}",
        "signal_date": entry_date,
        "entry_date": entry_date,
        "exit_date": entry_date + pd.Timedelta(days=1),
        "entry_price": 10.0,
        "d1_close": 10.0 * (1.0 + (net_return + 0.2) / 100.0),
        "d1_net_return_pct": net_return,
        "net_return_pct": net_return,
        "round_trip_cost_pct": 0.2,
        "time_block": block,
        "dynamic_rank": 1,
        "active_direction": "GOLD",
        "danger_state": "NORMAL",
        "market_phase": "rotation",
    }
