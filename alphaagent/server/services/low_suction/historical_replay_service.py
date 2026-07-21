"""Build and query database-derived historical low-suction replay evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .causal_leader_pullback import (
    THREE_PHASE_ADAPTIVE_POLICY_VERSION,
    execute_prepared_close_trades,
    select_three_phase_adaptive_signals,
)
from .causal_leader_pullback_forward import (
    THREE_PHASE_QUALIFICATION_CONTRACT_VERSION,
)
from .causal_leader_pullback_study import (
    _attach_trade_market_timing,
    build_causal_stock_features,
    build_dynamic_leader_paths,
    build_concept_campaign_ledger,
    load_causal_leader_pullback_inputs,
    prepare_dynamic_leader_paths,
    select_non_overlapping_trades,
    simulate_four_slot_cash,
)
from .historical_replay_repository import (
    get_replay_trade,
    list_replay_trades,
    load_latest_replay_run,
    save_replay_run,
)


EVIDENCE_LEVEL = "exploratory_survivorship_proxy"
MEMBERSHIP_MODE = "current_membership_replayed_backward"
REGRESSION_ARTIFACT_SHA256 = (
    "ccfeed5e4254c435d9821fdca96c9670adfc9fa3965b0d53f68da416e1c7a111"
)
PRODUCT_POLICY_VERSION = f"{THREE_PHASE_ADAPTIVE_POLICY_VERSION}-two-slot-v1"
REGRESSION_ARTIFACT = (
    Path(__file__).resolve().parents[4]
    / "memory/06_backtests/low_suction_three_phase_adaptive_diagnostic_20260721.json"
)


@dataclass(frozen=True)
class HistoricalReplayBuild:
    run: dict[str, object]
    trades: pd.DataFrame
    metrics: dict[str, object]


def build_exploratory_three_phase_replay() -> HistoricalReplayBuild:
    """Recompute the exploratory replay from PostgreSQL, never from JSON rows."""

    inputs = load_causal_leader_pullback_inputs()
    stock_features = build_causal_stock_features(inputs.stock_bars)
    _campaigns, campaign_paths = build_concept_campaign_ledger(inputs.concept_bars)
    leaders, _coverage = build_dynamic_leader_paths(
        campaign_paths, inputs.memberships, stock_features
    )
    prepared = prepare_dynamic_leader_paths(leaders, inputs.market_timing)
    signals = select_three_phase_adaptive_signals(prepared.signals)
    executed = execute_prepared_close_trades(signals, prepared.campaigns).assign(
        variant=THREE_PHASE_ADAPTIVE_POLICY_VERSION
    )
    timed = _attach_trade_market_timing(executed, prepared.signals)
    selected = select_non_overlapping_trades(timed)
    ledger = _build_ledger(selected, signals, inputs.memberships)
    cash = simulate_four_slot_cash(selected, stock_features, capacity=2)
    metrics = _metrics(ledger, cash)
    artifact = _load_regression_artifact()
    _verify_regression(metrics, artifact)

    input_fingerprint = _combined_input_fingerprint(inputs.fingerprints)
    run_id = hashlib.sha256(
        f"{PRODUCT_POLICY_VERSION}|{input_fingerprint}".encode("utf-8")
    ).hexdigest()
    run = {
        "run_id": run_id,
        "policy_version": PRODUCT_POLICY_VERSION,
        "qualification_contract_version": THREE_PHASE_QUALIFICATION_CONTRACT_VERSION,
        "evidence_level": EVIDENCE_LEVEL,
        "membership_mode": MEMBERSHIP_MODE,
        "input_fingerprint": input_fingerprint,
        "regression_artifact_sha256": REGRESSION_ARTIFACT_SHA256,
        "trade_count": len(ledger),
        "metrics": metrics,
        "built_at": datetime.now().astimezone(),
        "raw": {
            "database_coverage": inputs.coverage,
            "database_input_fingerprints": inputs.fingerprints,
            "formal_strategy": False,
            "formal_blockers": [
                "historical_point_in_time_membership_missing",
                "natural_forward_qualification_not_met",
            ],
            "regression_artifact_is_input": False,
        },
    }
    return HistoricalReplayBuild(run=run, trades=ledger, metrics=metrics)


def materialize_exploratory_three_phase_replay() -> dict[str, object]:
    """Run the expensive replay explicitly and persist its immutable ledger."""

    build = build_exploratory_three_phase_replay()
    saved = save_replay_run(build.run, build.trades)
    return {**saved, "run": build.run, "metrics": build.metrics}


def get_historical_replay_overview() -> dict[str, object]:
    """Read saved evidence only; this function never launches a replay."""

    latest = load_latest_replay_run()
    strict = load_latest_replay_run(evidence_level="strict_point_in_time")
    return {
        "latest_run": latest,
        "latest_strict_run": strict,
        "formal_strategy": False,
        "exploratory_counts_toward_qualification": False,
        "strict_history_available": strict is not None,
    }


def get_historical_replay_trades(**filters: object) -> dict[str, object]:
    """Read a saved replay page without recomputation."""

    return list_replay_trades(**filters)


def get_historical_replay_trade(*, run_id: str, signal_id: str) -> dict[str, object] | None:
    """Read one saved replay row without recomputation."""

    return get_replay_trade(run_id=run_id, signal_id=signal_id)


def _build_ledger(
    trades: pd.DataFrame,
    signals: pd.DataFrame,
    memberships: pd.DataFrame,
) -> pd.DataFrame:
    if trades.empty:
        raise ValueError("database replay produced no selected trades")
    context_columns = [
        "signal_id",
        "concept_name",
        "support_price",
        "signal_date",
    ]
    missing = [column for column in context_columns if column not in signals]
    if missing:
        raise ValueError(f"selected signals missing ledger context: {missing}")
    context = signals.loc[:, context_columns].drop_duplicates("signal_id")
    frame = trades.merge(
        context,
        on="signal_id",
        how="left",
        validate="one_to_one",
        suffixes=("", "_signal"),
    )
    names = memberships.loc[:, ["vt_symbol", "stock_name"]].drop_duplicates()
    if names["vt_symbol"].duplicated().any():
        names = names.drop_duplicates("vt_symbol", keep="last")
    frame = frame.merge(names, on="vt_symbol", how="left", validate="many_to_one")
    frame["stock_name"] = frame["stock_name"].fillna("")
    frame["signal_date"] = frame["signal_date"].fillna(frame["entry_date"])
    frame["support_test_date"] = pd.to_datetime(
        frame["support_test_date"], errors="raise"
    ).dt.date
    for source, target in (
        ("signal_date", "signal_date"),
        ("entry_date", "_entry_date"),
        ("d1_date", "d1_date"),
        ("exit_date", "exit_date"),
    ):
        frame[target] = pd.to_datetime(frame[source], errors="raise").dt.date
    required = [
        "signal_id",
        "campaign_id",
        "sector_id",
        "concept_name",
        "vt_symbol",
        "stock_name",
        "market_phase",
        "time_block",
        "dynamic_rank",
        "wave_number",
        "support_line",
        "support_price",
        "support_test_date",
        "signal_date",
        "entry_price",
        "d1_date",
        "d1_close",
        "d1_net_return_pct",
        "exit_date",
        "exit_price",
        "exit_reason",
        "holding_sessions",
        "net_return_pct",
    ]
    if frame[required].isna().any().any():
        missing_values = frame[required].columns[frame[required].isna().any()].tolist()
        raise ValueError(f"historical ledger has missing values: {missing_values}")
    result = frame.loc[:, required].copy()
    result["raw"] = frame.apply(
        lambda row: {
            key: value
            for key, value in row.to_dict().items()
            if key not in required and key != "_entry_date"
        },
        axis=1,
    )
    return result.sort_values(["signal_date", "signal_id"], kind="stable").reset_index(
        drop=True
    )


def _metrics(ledger: pd.DataFrame, cash: dict[str, Any]) -> dict[str, object]:
    returns = pd.to_numeric(ledger["net_return_pct"], errors="raise")
    return {
        "trades": int(len(ledger)),
        "positive_rate_pct": float(returns.gt(0).mean() * 100.0),
        "mean_net_return_pct": float(returns.mean()),
        "two_slot_cash": cash,
    }


def _load_regression_artifact() -> dict[str, Any]:
    raw = REGRESSION_ARTIFACT.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != REGRESSION_ARTIFACT_SHA256:
        raise ValueError(f"three-phase regression artifact changed: {digest}")
    report = json.loads(raw.decode("utf-8"))
    if not isinstance(report, dict):
        raise ValueError("three-phase regression artifact must be an object")
    return report


def _verify_regression(metrics: dict[str, object], artifact: dict[str, Any]) -> None:
    expected = artifact["historical_metrics"]
    full = expected["full_history"]
    cash = expected["two_slot_cash"]
    actual_cash = metrics["two_slot_cash"]
    checks = {
        "trades": (metrics["trades"], full["trades"]),
        "positive_rate_pct": (metrics["positive_rate_pct"], full["win_rate_pct"]),
        "mean_net_return_pct": (
            metrics["mean_net_return_pct"],
            full["mean_net_return_pct"],
        ),
        "cash_closed_trades": (actual_cash["closed_trades"], cash["closed_trades"]),
        "cash_compound_return_pct": (
            actual_cash["compound_return_pct"],
            cash["compound_return_pct"],
        ),
    }
    mismatches = [
        name
        for name, (actual, wanted) in checks.items()
        if abs(float(actual) - float(wanted)) > 1e-9
    ]
    if mismatches:
        raise ValueError(
            "database replay no longer matches regression evidence: "
            + ", ".join(mismatches)
        )


def _combined_input_fingerprint(fingerprints: dict[str, object]) -> str:
    encoded = json.dumps(
        fingerprints, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
