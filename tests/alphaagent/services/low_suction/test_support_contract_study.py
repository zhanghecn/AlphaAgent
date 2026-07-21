from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from alphaagent.server.services.low_suction import cli, support_contract_study
from alphaagent.server.services.low_suction.causal_leader_pullback import (
    EXACT_REQUIRED_SUPPORT,
    MINIMUM_REQUIRED_SUPPORT,
)
from alphaagent.server.services.low_suction.support_contract_study import (
    DEEP_RECLAIM_VARIANT,
    EXACT_SUPPORT_VARIANT,
    build_support_named_case_audit,
    build_support_contract_report,
    evaluate_support_contract,
    render_support_contract_markdown,
    replay_support_contracts,
)


def test_support_contracts_run_two_independent_state_machines(monkeypatch) -> None:
    calls: list[str] = []

    def replay(_paths, _timing, *, support_match_mode: str):
        calls.append(support_match_mode)
        return SimpleNamespace(
            signals=pd.DataFrame({"signal_id": [support_match_mode]}),
            trades=pd.DataFrame(),
            waves=pd.DataFrame(),
            exclusions=pd.DataFrame(),
            daily_ledger=pd.DataFrame(),
        )

    monkeypatch.setattr(
        support_contract_study,
        "replay_dynamic_leader_paths",
        replay,
    )

    replays = replay_support_contracts(pd.DataFrame(), pd.DataFrame())

    assert calls == [MINIMUM_REQUIRED_SUPPORT, EXACT_REQUIRED_SUPPORT]
    assert set(replays) == {DEEP_RECLAIM_VARIANT, EXACT_SUPPORT_VARIANT}
    assert (
        replays[DEEP_RECLAIM_VARIANT].signals["signal_id"].tolist()
        == [MINIMUM_REQUIRED_SUPPORT]
    )
    assert (
        replays[EXACT_SUPPORT_VARIANT].signals["signal_id"].tolist()
        == [EXACT_REQUIRED_SUPPORT]
    )


def test_support_contract_report_keeps_historical_and_formal_gates_separate() -> None:
    trades = pd.concat(
        [
            _trades(DEEP_RECLAIM_VARIANT, winners_per_block=13),
            _trades(EXACT_SUPPORT_VARIANT, winners_per_block=13),
        ],
        ignore_index=True,
    )
    report = build_support_contract_report(
        coverage={"strict_historical_membership_rows": 0},
        fingerprints={"stock_bars": {"digest": "sha256:test", "rows": 100}},
        selected_signals=_signals(),
        selected_trades=trades,
        cash_results={
            DEEP_RECLAIM_VARIANT: _cash_result(),
            EXACT_SUPPORT_VARIANT: _cash_result(),
        },
        named_case_audit=[
            {
                "variant": EXACT_SUPPORT_VARIANT,
                "vt_symbol": "002636.SZSE",
                "stock_name": "金安国纪",
                "first_top3_date": "2026-01-15",
                "last_top3_date": "2026-06-30",
                "waves": 3,
                "signals": 2,
                "executed_trades": 2,
                "wave_rows": [],
                "trade_rows": [],
            }
        ],
    )

    assert report["policy_version"] == "causal-leader-pullback-support-contract-v4"
    assert report["formal_strategy"] is False
    assert report["formal_metrics"] is None
    assert "minimum" in report["contract"]["variants"][DEEP_RECLAIM_VARIANT]
    assert "exact" in report["contract"]["variants"][EXACT_SUPPORT_VARIANT]
    for variant in (DEEP_RECLAIM_VARIANT, EXACT_SUPPORT_VARIANT):
        decision = report["qualification"][variant]
        assert decision["historical_proxy_gate_passed"] is True
        assert "strict_historical_membership_missing" in decision["formal_blockers"]
        assert "same_close_execution_is_research_proxy" in decision["formal_blockers"]
    assert report["named_case_audit"][0]["stock_name"] == "金安国纪"
    assert "参考个股波段" in render_support_contract_markdown(report)


def test_named_case_audit_is_built_independently_for_each_variant(monkeypatch) -> None:
    calls: list[list[str]] = []

    def audit(_paths, signals, _trades, _waves, _daily):
        calls.append(signals["signal_id"].tolist())
        return [{"vt_symbol": "002636.SZSE", "stock_name": "金安国纪"}]

    monkeypatch.setattr(support_contract_study, "build_named_case_audit", audit)
    replays = {
        variant: SimpleNamespace(waves=pd.DataFrame(), daily_ledger=pd.DataFrame())
        for variant in (DEEP_RECLAIM_VARIANT, EXACT_SUPPORT_VARIANT)
    }
    signals = pd.DataFrame(
        [
            {"variant": DEEP_RECLAIM_VARIANT, "signal_id": "deep"},
            {"variant": EXACT_SUPPORT_VARIANT, "signal_id": "exact"},
        ]
    )
    trades = signals.copy()

    result = build_support_named_case_audit(
        pd.DataFrame(),
        replays,
        signals,
        trades,
    )

    assert calls == [["deep"], ["exact"]]
    assert [item["variant"] for item in result] == [
        DEEP_RECLAIM_VARIANT,
        EXACT_SUPPORT_VARIANT,
    ]


def test_support_contract_win_rate_must_be_strictly_above_sixty() -> None:
    decision = evaluate_support_contract(
        DEEP_RECLAIM_VARIANT,
        _trades(DEEP_RECLAIM_VARIANT, winners_per_block=12),
        _cash_result(),
        strict_membership_rows=1,
    )

    assert decision["historical_proxy_gate_passed"] is False
    assert "win_rate<=60pct" in decision["failed_gates"]


def test_support_contract_cli_runs_once_and_renders_selected_format(
    monkeypatch,
    capsys,
) -> None:
    report = {"policy_version": "test-v4"}
    calls: list[str] = []
    monkeypatch.setattr(
        support_contract_study,
        "run_support_contract_study",
        lambda: calls.append("run") or report,
    )
    monkeypatch.setattr(
        support_contract_study,
        "render_support_contract_json",
        lambda current: f"json:{current['policy_version']}\n",
    )
    monkeypatch.setattr(
        support_contract_study,
        "render_support_contract_markdown",
        lambda current: f"markdown:{current['policy_version']}\n",
    )

    args = cli.build_parser().parse_args(
        ["v4-support-contract-study", "--format", "json"]
    )
    assert args.command == "v4-support-contract-study"
    assert cli.main(["v4-support-contract-study", "--format", "markdown"]) == 0
    assert capsys.readouterr().out == "markdown:test-v4\n"
    assert calls == ["run"]


def _signals() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "variant": DEEP_RECLAIM_VARIANT,
                "signal_id": "deep-1",
                "signal_date": pd.Timestamp("2026-01-05"),
                "required_support": "ma5",
                "support_line": "ma10",
            },
            {
                "variant": EXACT_SUPPORT_VARIANT,
                "signal_id": "exact-1",
                "signal_date": pd.Timestamp("2026-01-05"),
                "required_support": "ma5",
                "support_line": "ma5",
            },
        ]
    )


def _trades(variant: str, *, winners_per_block: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    start = pd.Timestamp("2024-01-02")
    for block in range(1, 6):
        for position in range(20):
            entry_date = start + pd.Timedelta(days=(block - 1) * 30 + position)
            rows.append(
                {
                    "variant": variant,
                    "signal_id": f"{variant}-{block}-{position}",
                    "vt_symbol": f"600{block:03d}.SSE",
                    "sector_id": f"BK{block:04d}",
                    "entry_date": entry_date,
                    "exit_date": entry_date + pd.Timedelta(days=1),
                    "time_block": f"block_{block}",
                    "market_phase": (
                        "rotation" if (position + block) % 2 == 0 else "warming"
                    ),
                    "support_line": "ma5" if block == 1 else "ma10",
                    "required_support": "ma5" if block == 1 else "ma10",
                    "net_return_pct": 2.0 if position < winners_per_block else -1.0,
                    "exit_reason": "higher_high_confirmed",
                }
            )
    return pd.DataFrame(rows)


def _cash_result() -> dict[str, object]:
    return {
        "initial_cash": 100_000.0,
        "final_equity": 170_000.0,
        "compound_return_pct": 70.0,
        "maximum_drawdown_pct": -5.0,
        "accepted_entries": 100,
        "closed_trades": 100,
    }
