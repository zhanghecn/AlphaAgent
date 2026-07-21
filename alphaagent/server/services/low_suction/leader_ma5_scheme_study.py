"""Executable study for the frozen leader MA5 recognition scheme."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .confirmed_multi_wave_pullback_study import (
    APPROACH_TOLERANCE_PCT,
    MIN_PULLBACK_PCT,
)
from .leader_ma5_cash import (
    simulate_capacity_comparison,
    simulate_structural_cash_account,
)
from .leader_ma5_scheme import (
    SCHEME_VERSION,
    select_scheme_candidates,
    summarize_structural_segments,
    summarize_tail_segments,
)
from .tail_feature_study import (
    build_tail_feature_panel,
    execute_tail_trades,
)


TAIL_EVIDENCE_LEVEL = "reused_history_leader_ma5_tail_execution"
TAIL_RANK_MODE = "causal_proxy_confirmed_multi_wave"
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
ATTRIBUTION_REPORT_PATH = (
    REPOSITORY_ROOT
    / "memory/06_backtests/low_suction_ma5_case_attribution_study_20260718.json"
)
ATTRIBUTION_REPORT_SHA256 = (
    "bca54e63dfacc47c547589fcd6b202e5f6a0323f388e6c8759e0b0bd1c421e4d"
)
PARENT_REPORT_PATH = (
    REPOSITORY_ROOT
    / "memory/06_backtests/low_suction_confirmed_multi_wave_pullback_study_20260718.json"
)
PARENT_REPORT_SHA256 = (
    "6b503d1c6eaa19f9cc86cac6aeb16641f72df44031b68b1e28151fa639afa42c"
)
EXPECTED_PARENT_MA5_ROWS = 57
EXPECTED_SCHEME_CANDIDATE_ROWS = 35
CASH_EXIT_BUFFER_DAYS = 30
CUTOFF_CHECK_COLUMNS = (
    "cutoff_reclaimed_provisional_ma5",
    "cutoff_not_below_previous_close",
    "cutoff_approached_provisional_ma5",
    "cutoff_pullback_known",
    "cutoff_reference_peak_preexists",
)
CUTOFF_AUDIT_COLUMNS = (
    "signal_id",
    "provisional_ma5_at_1450",
    "prior_close_count",
    *CUTOFF_CHECK_COLUMNS,
    "cutoff_recognition_passed",
)
HYBRID_NUMERIC_DIAGNOSTICS = (
    "volume_ratio_prior5",
    "stock_ma5_ma10_gap_pct",
    "tail_return_from_previous_close_pct",
    "tail_drawdown_from_session_high_pct",
    "tail_vs_vwap_pct",
    "last_15m_volume_ratio",
    "support_break_count",
)
HYBRID_CATEGORICAL_DIAGNOSTICS = ("active_direction", "causal_rank")


def load_frozen_attribution_ledger() -> pd.DataFrame:
    """Load the immutable attribution artifact behind the concrete scheme."""

    _verify_file_sha256(PARENT_REPORT_PATH, PARENT_REPORT_SHA256, "parent report")
    raw = ATTRIBUTION_REPORT_PATH.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != ATTRIBUTION_REPORT_SHA256:
        raise ValueError(f"MA5 attribution report fingerprint changed: {digest}")
    report = json.loads(raw.decode("utf-8"))
    if report.get("study_version") != "ma5-case-attribution-v1":
        raise ValueError("unexpected MA5 attribution study version")
    ledger = pd.DataFrame.from_records(report.get("individual_case_ledger") or [])
    if len(ledger) != EXPECTED_PARENT_MA5_ROWS:
        raise ValueError(
            "frozen MA5 attribution cohort changed: "
            f"expected {EXPECTED_PARENT_MA5_ROWS}, got {len(ledger)}"
        )
    return ledger


def load_frozen_scheme_candidates() -> pd.DataFrame:
    """Select the fixed one-gate candidate cohort from immutable evidence."""

    candidates = select_scheme_candidates(load_frozen_attribution_ledger())
    if len(candidates) != EXPECTED_SCHEME_CANDIDATE_ROWS:
        raise ValueError(
            "frozen leader MA5 scheme cohort changed: "
            f"expected {EXPECTED_SCHEME_CANDIDATE_ROWS}, got {len(candidates)}"
        )
    return candidates


def run_leader_ma5_scheme_study() -> dict[str, Any]:
    """Run the fixed structural and D-tail execution comparison on local evidence."""

    from .leader_ma5_scheme_minutes import (
        build_scheme_5m_manifest,
        build_scheme_minute_pairs,
        load_existing_scheme_minutes,
    )

    attribution = load_frozen_attribution_ledger()
    candidates = select_scheme_candidates(attribution)
    if len(candidates) != EXPECTED_SCHEME_CANDIDATE_ROWS:
        raise ValueError("real leader MA5 scheme candidate count changed")
    daily_bars = _load_scheme_daily_bars(candidates)
    pairs = build_scheme_minute_pairs(candidates)
    minute_bars = load_existing_scheme_minutes(pairs)
    manifest = build_scheme_5m_manifest(pairs, minute_bars)
    complete_ids = _complete_signal_ids(manifest)
    complete_candidates = candidates.loc[
        candidates["signal_id"].astype(str).isin(complete_ids)
    ].copy()
    if complete_candidates.empty:
        features = pd.DataFrame()
        executed = pd.DataFrame()
    else:
        features, executed = execute_tail_scheme(
            complete_candidates,
            daily_bars,
            minute_bars,
        )
    cutoff_pass_ids = (
        set(
            features.loc[
                features["cutoff_recognition_passed"].astype(bool),
                "event_id",
            ].astype(str)
        )
        if not features.empty
        else set()
    )
    tail_ledger = _retain_all_tail_attempts(
        candidates,
        executed,
        complete_ids,
        cutoff_pass_ids,
    )
    structural_cash_trades = build_causal_structural_cash_trades(
        candidates,
        daily_bars,
    )
    cash_comparison = simulate_capacity_comparison(structural_cash_trades, daily_bars)
    tail_structural_trades = build_tail_structural_cash_trades(
        candidates,
        executed,
        daily_bars,
    )
    tail_structural_cash_comparison = simulate_capacity_comparison(
        tail_structural_trades,
        daily_bars,
    )
    tail_structural_capacity4 = simulate_structural_cash_account(
        tail_structural_trades,
        daily_bars,
        capacity=4,
    )
    tail_structural_trade_ledger = pd.DataFrame.from_records(
        tail_structural_capacity4["trade_ledger"]
    )
    hybrid_feature_diagnostics = build_hybrid_feature_diagnostics(
        candidates,
        features,
        tail_structural_trade_ledger,
    )
    fingerprints = _input_fingerprints(
        attribution=attribution,
        candidates=candidates,
        daily_bars=daily_bars,
        minute_manifest=manifest,
        minute_bars=minute_bars,
        features=features,
        tail_ledger=tail_ledger,
        structural_cash_trades=structural_cash_trades,
        tail_structural_trades=tail_structural_trades,
        tail_structural_trade_ledger=tail_structural_trade_ledger,
    )
    return build_leader_ma5_scheme_report(
        attribution_ledger=attribution,
        candidates=candidates,
        minute_manifest=manifest,
        tail_ledger=tail_ledger,
        cash_comparison=cash_comparison,
        tail_structural_cash_comparison=tail_structural_cash_comparison,
        tail_structural_trade_ledger=tail_structural_trade_ledger,
        hybrid_feature_diagnostics=hybrid_feature_diagnostics,
        cutoff_recognition_audit=(
            features.loc[:, list(CUTOFF_AUDIT_COLUMNS)].copy()
            if not features.empty
            else pd.DataFrame(columns=CUTOFF_AUDIT_COLUMNS)
        ),
        input_fingerprints=fingerprints,
    )


def _load_scheme_daily_bars(candidates: pd.DataFrame) -> pd.DataFrame:
    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    symbols = tuple(sorted(candidates["vt_symbol"].astype(str).unique()))
    signal_dates = pd.to_datetime(candidates["signal_date"], errors="raise")
    entry_dates = pd.to_datetime(candidates["entry_date"], errors="raise")
    exit_dates = pd.to_datetime(candidates["exit_date"], errors="coerce").dropna()
    load_start = (signal_dates.min().date() - timedelta(days=120))
    last_required = entry_dates.max()
    if not exit_dates.empty:
        last_required = max(last_required, exit_dates.max())
    load_end = last_required.date() + timedelta(days=CASH_EXIT_BUFFER_DAYS)
    statement = (
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.volume,
            schema.stock_daily_bars.c.turnover,
        )
        .where(
            schema.stock_daily_bars.c.vt_symbol.in_(symbols),
            schema.stock_daily_bars.c.trade_date.between(load_start, load_end),
        )
        .order_by(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
        )
    )
    return pd.read_sql(
        statement,
        get_engine(),
        parse_dates=["trade_date"],
    )


def _complete_signal_ids(manifest: pd.DataFrame) -> set[str]:
    _require_columns(
        manifest,
        ("signal_id", "pair_role", "status"),
        "scheme minute manifest",
    )
    complete = set()
    for signal_id, group in manifest.groupby("signal_id", sort=False):
        roles = set(group["pair_role"].astype(str))
        if (
            roles == {"signal", "next_session"}
            and len(group) == 2
            and group["status"].eq("complete").all()
        ):
            complete.add(str(signal_id))
    return complete


def _retain_all_tail_attempts(
    candidates: pd.DataFrame,
    executed: pd.DataFrame,
    complete_ids: set[str],
    cutoff_pass_ids: set[str],
) -> pd.DataFrame:
    executed_by_id = (
        {
            str(row["event_id"]): row
            for row in executed.to_dict("records")
        }
        if not executed.empty
        else {}
    )
    rows = []
    for candidate in candidates.to_dict("records"):
        signal_id = str(candidate["signal_id"])
        if signal_id in executed_by_id:
            row = dict(executed_by_id[signal_id])
            row["signal_id"] = signal_id
            rows.append(row)
            continue
        if signal_id not in complete_ids:
            reason = "incomplete_d_or_d1_5m"
        elif signal_id not in cutoff_pass_ids:
            reason = "cutoff_recognition_failed"
        else:
            reason = "complete_pair_execution_missing"
        rows.append(
            {
                "event_id": signal_id,
                "signal_id": signal_id,
                "entry_date": pd.Timestamp(candidate["signal_date"]).date(),
                "block": _block_number(candidate["time_block"]),
                "status": "unavailable",
                "reason": reason,
                "net_return_pct": None,
                "double_cost_net_return_pct": None,
            }
        )
    return pd.DataFrame.from_records(rows).sort_values(
        ["entry_date", "event_id"],
        kind="stable",
    ).reset_index(drop=True)


def _input_fingerprints(**frames: pd.DataFrame) -> dict[str, Any]:
    from .research_protocol import fingerprint_frame

    identities = {
        "attribution": ("signal_id",),
        "candidates": ("signal_id",),
        "daily_bars": ("vt_symbol", "trade_date"),
        "minute_manifest": ("event_id",),
        "minute_bars": ("vt_symbol", "bar_time", "interval"),
        "features": ("event_id",),
        "tail_ledger": ("event_id",),
        "structural_cash_trades": ("signal_id",),
        "tail_structural_trades": ("signal_id",),
        "tail_structural_trade_ledger": ("signal_id",),
    }
    fingerprints = {}
    for label, frame in frames.items():
        if frame.empty:
            fingerprints[label] = {
                "algorithm": "sha256",
                "digest": None,
                "rows": 0,
                "columns": [],
            }
            continue
        fingerprints[label] = fingerprint_frame(
            frame,
            identity_columns=identities[label],
        ).as_dict()
    fingerprints["parent_report"] = {
        "algorithm": "sha256",
        "digest": f"sha256:{PARENT_REPORT_SHA256}",
        "rows": EXPECTED_PARENT_MA5_ROWS,
    }
    fingerprints["attribution_report"] = {
        "algorithm": "sha256",
        "digest": f"sha256:{ATTRIBUTION_REPORT_SHA256}",
        "rows": EXPECTED_PARENT_MA5_ROWS,
    }
    return fingerprints


def _verify_file_sha256(path: Path, expected: str, label: str) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        raise ValueError(f"{label} fingerprint changed: {digest}")


def build_leader_ma5_scheme_report(
    *,
    attribution_ledger: pd.DataFrame,
    candidates: pd.DataFrame,
    minute_manifest: pd.DataFrame,
    tail_ledger: pd.DataFrame,
    cash_comparison: dict[str, dict[str, Any]],
    tail_structural_cash_comparison: dict[str, dict[str, Any]],
    tail_structural_trade_ledger: pd.DataFrame,
    hybrid_feature_diagnostics: dict[str, Any],
    cutoff_recognition_audit: pd.DataFrame,
    input_fingerprints: dict[str, Any],
) -> dict[str, Any]:
    """Build one complete reused-history report without promoting formal metrics."""

    _require_columns(minute_manifest, ("status",), "scheme minute manifest")
    _require_columns(tail_ledger, ("event_id", "status"), "scheme tail ledger")
    if tail_ledger["event_id"].duplicated().any():
        raise ValueError("scheme tail event IDs must be unique")
    expected_pairs = len(candidates) * 2
    if len(minute_manifest) != expected_pairs:
        raise ValueError(
            f"scheme minute manifest requires {expected_pairs} exact pairs"
        )
    complete_pairs = int(minute_manifest["status"].eq("complete").sum())
    structural_base = summarize_structural_segments(attribution_ledger)
    structural_scheme = summarize_structural_segments(candidates)
    tail_segments = summarize_tail_segments(tail_ledger)
    tail_pooled = tail_segments["all"]
    _validate_cash_comparison(cash_comparison)
    _validate_cash_comparison(tail_structural_cash_comparison)
    cutoff_summary = _summarize_cutoff_audit(cutoff_recognition_audit)
    hybrid_segments = _summarize_hybrid_segments(
        candidates,
        tail_structural_trade_ledger,
    )
    coverage_complete = complete_pairs == expected_pairs
    status = _research_status(coverage_complete, cutoff_summary)
    primary_exit = (
        "after either the first later daily high above the reference peak or the "
        "second consecutive close below MA20, sell at the next stock-session open"
    )
    return {
        "scheme_version": SCHEME_VERSION,
        "research_status": status,
        "validation_status": "reused_history_not_formal_validation",
        "formal_strategy": False,
        "formal_metrics": None,
        "scheme_contract": {
            "universe": (
                "confirmed wave-3 causal proxy Top3, main-board only, "
                "concept main-rise and stock structure intact"
            ),
            "pullback": (
                "first stabilized MA5 reclaim after a visible 5% pullback "
                "and two confirmed higher highs"
            ),
            "recognition_gate": "strong_days_ge_9_5pct >= 1",
            "feature_cutoff": "D 14:50 completed 5m bar",
            "tail_entry": "D 14:55 5m bar open",
            "holding_style": "multi-session swing; no fixed D+1 exit",
            "primary_exit": primary_exit,
            "structural_comparator_entry": "D+1 official open",
            "structural_cash_exit": primary_exit,
            "structural_comparator_exit": (
                "trigger-day close retained only to reproduce the parent daily study"
            ),
            "portfolio_capacity": 4,
            "position_target": "current equity / 4, 100-share lots, no leverage",
            "portfolio_constraints": (
                "at most one open position per concept; deterministic causal-rank "
                "then signal-id priority"
            ),
            "diagnostic_only": [
                "volume_ratio_prior5",
                "stock_ma5_ma10_gap_pct",
                "active_direction",
                "danger_state",
                "post-entry concept continuation",
            ],
            "cutoff_recognition": (
                "at D 14:50, provisional MA5 from prior four closes plus the "
                "completed 14:50 close is reclaimed; price is not below the prior "
                "close; MA5 approach and 5% pullback are already observable"
            ),
        },
        "coverage": {
            "parent_ma5_rows": int(len(attribution_ledger)),
            "scheme_candidate_rows": int(len(candidates)),
            "minute_required_pairs": expected_pairs,
            "minute_complete_pairs": complete_pairs,
            "minute_missing_or_invalid_pairs": expected_pairs - complete_pairs,
            "tail_ledger_rows": int(len(tail_ledger)),
            "tail_structural_cash_eligible_signals": int(
                tail_structural_cash_comparison["capacity_4"]["signals"]
            ),
            "cutoff_audited_signals": cutoff_summary["audited_signals"],
            "cutoff_passed_signals": cutoff_summary["passed_signals"],
        },
        "structural_base_segments": structural_base,
        "structural_scheme_segments": structural_scheme,
        "structural_cash_comparison": cash_comparison,
        "tail_structural_cash_comparison": tail_structural_cash_comparison,
        "tail_structural_trade_segments": hybrid_segments,
        "hybrid_feature_diagnostics": hybrid_feature_diagnostics,
        "cutoff_recognition_audit": cutoff_summary,
        "tail_execution_segments": tail_segments,
        "execution_decision": {
            "forward_shadow": {
                "status": "frozen_research_candidate_not_production",
                "entry": "D 14:55 open after the completed 14:50 cutoff gate",
                "exit": primary_exit,
                "portfolio_capacity": 4,
                "historical_descriptor": tail_structural_cash_comparison[
                    "capacity_4"
                ],
            },
            "fixed_1035_exit": {
                "status": "not_retained_as_primary_exit",
                "historical_descriptor": tail_pooled,
            },
        },
        "rejected_experiments": {
            "fixed_d1_1035_exit": {
                "status": "rejected_not_current_contract",
                "exit": "D+1 10:35 5m bar open",
                "reason": "fixed next-day exit conflicts with the swing objective",
                "historical_descriptor": tail_pooled,
            }
        },
        "historical_tail_gate": _historical_tail_gate(tail_pooled),
        "individual_case_ledger": _individual_cases(
            candidates,
            tail_ledger,
            tail_structural_trade_ledger,
            cutoff_recognition_audit,
        ),
        "input_fingerprints": input_fingerprints,
        "boundaries": [
            "all five historical blocks were already viewed",
            "current concept memberships remain a survivorship proxy",
            "causal Top3 did not pass the prior absolute historical identity gate",
            "historical concept main-rise state is a completed-daily-bar proxy; live shadow must recalculate it at 14:50",
            "the 9.5 percent recognition threshold is a natural A-share strong-day boundary",
            "volume, MA gap, GOLD/SILVER and future continuation never select candidates",
            "fixed capacities 1/2/3/4 are all reported; reused history does not select one",
            "capacity 4 is frozen now as the forward 25 percent risk cap and must not be retuned on these reused rows",
            "formal win rate, return and compounding remain null",
        ],
        "reproduce": (
            "docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace "
            "-w /workspace alphaagent-api python -m "
            "alphaagent.server.services.low_suction.cli "
            "v2-leader-ma5-scheme-study --format markdown"
        ),
    }


def render_leader_ma5_scheme_json(report: dict[str, Any]) -> str:
    return json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=_json_default,
    ) + "\n"


def render_leader_ma5_scheme_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    contract = report["scheme_contract"]
    lines = [
        "# AlphaAgent Leader MA5 Low-suction Scheme",
        "",
        f"Research status: `{report['research_status']}`.",
        "Formal strategy/metrics: `false/null`.",
        "",
        "## Concrete Contract",
        "",
        f"- Recognition: `{contract['recognition_gate']}`.",
        f"- Pullback: {contract['pullback']}.",
        f"- Feature cutoff: `{contract['feature_cutoff']}`.",
        f"- Entry: `{contract['tail_entry']}`.",
        f"- Holding style: `{contract['holding_style']}`.",
        f"- Primary exit: `{contract['primary_exit']}`.",
        f"- Portfolio: max `{contract['portfolio_capacity']}` positions; "
        f"`{contract['position_target']}`.",
        "",
        "## Coverage",
        "",
        f"- Parent/scheme rows: `{coverage['parent_ma5_rows']}/"
        f"{coverage['scheme_candidate_rows']}`.",
        f"- Minute complete/required pairs: `{coverage['minute_complete_pairs']}/"
        f"{coverage['minute_required_pairs']}`.",
        f"- 14:50 causal stock gate passed/audited: `{coverage['cutoff_passed_signals']}/"
        f"{coverage['cutoff_audited_signals']}`.",
        "",
        "## Non-causal Parent Daily Comparator",
        "",
        *_segment_table(report["structural_scheme_segments"], structural=True),
        "",
        "## Causal D+1-open To Next-open Structural Cash Account",
        "",
        f"- Initial cash: `{_cash_initial(report['structural_cash_comparison']):.2f} CNY`.",
        "- Entry is D+1 open; a daily structural trigger executes at the next stock-session open. All four fixed capacities are shown without choosing a historical return winner.",
        "",
        *_cash_table(report["structural_cash_comparison"]),
        "",
        "## D 14:55 Entry To Structural Exit Cash Account",
        "",
        f"- Executable 14:55 entries: `{coverage['tail_structural_cash_eligible_signals']}/{coverage['scheme_candidate_rows']}`.",
        f"- Initial cash: `{_cash_initial(report['tail_structural_cash_comparison']):.2f} CNY`.",
        "- A prior-peak rebreak or second consecutive close below MA20 triggers an exit at the next stock-session open; unavailable 5-minute entries are not fabricated.",
        "",
        *_cash_table(report["tail_structural_cash_comparison"]),
        "",
        "### Hybrid Trade Stability",
        "",
        *_segment_table(report["tail_structural_trade_segments"], structural=False),
        "",
        "## Hybrid Winner/Loser Diagnostics",
        "",
        "These fields are descriptive only and do not change the frozen candidate set.",
        "",
        *_hybrid_diagnostic_lines(report["hybrid_feature_diagnostics"]),
        "",
        "## Cases",
        "",
        "| Date | Stock | Concept | Block | Parent close | Swing | Status |",
        "| --- | --- | --- | --- | ---: | ---: | --- |",
        *_case_lines(report["individual_case_ledger"]),
        "",
        "## Rejected Experiment: Fixed D+1 Exit",
        "",
        "The D+1 10:35 exit is retained only as rejected evidence and is not part of the current swing contract.",
        "",
        *_segment_table(report["tail_execution_segments"], structural=False),
        "",
        "## Boundaries",
        "",
        *[f"- {value}" for value in report["boundaries"]],
        "",
        "## Reproduce",
        "",
        "```bash",
        report["reproduce"],
        "```",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _research_status(
    coverage_complete: bool,
    cutoff_summary: dict[str, Any],
) -> str:
    if int(cutoff_summary.get("passed_signals") or 0) == 0:
        return "blocked_by_no_causal_cutoff_evidence"
    if not coverage_complete:
        return "forward_shadow_candidate_partial_historical_minute_coverage"
    return "forward_shadow_candidate_ready"


def _historical_tail_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "closed_trades_gte_30": int(metrics.get("closed_trades") or 0) >= 30,
        "win_rate_gt_60_pct": _greater(metrics.get("win_rate_pct"), 60.0),
        "mean_net_return_gt_0": _greater(
            metrics.get("mean_net_return_pct"),
            0.0,
        ),
        "profit_factor_gte_1_2": _greater_equal(
            metrics.get("profit_factor"),
            1.2,
        ),
        "double_cost_mean_gt_0": _greater(
            metrics.get("double_cost_mean_net_return_pct"),
            0.0,
        ),
        "compound_return_gt_60_pct": _greater(
            metrics.get("compound_return_pct"),
            60.0,
        ),
        "maximum_drawdown_gte_minus_10_pct": _greater_equal(
            metrics.get("maximum_drawdown_pct"),
            -10.0,
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "validation_boundary": "reused_history_candidate_gate_only",
    }


def _individual_cases(
    candidates: pd.DataFrame,
    tail_ledger: pd.DataFrame,
    tail_structural_trade_ledger: pd.DataFrame,
    cutoff_audit: pd.DataFrame,
) -> list[dict[str, Any]]:
    tail_by_signal = {
        str(row["event_id"]): row
        for row in tail_ledger.to_dict("records")
    }
    expected = set(candidates["signal_id"].astype(str))
    if set(tail_by_signal) != expected:
        raise ValueError("scheme tail ledger must retain every selected signal")
    cutoff_by_signal = {
        str(row["signal_id"]): row
        for row in cutoff_audit.to_dict("records")
    }
    _require_columns(
        tail_structural_trade_ledger,
        ("signal_id", "status", "reason", "net_return_pct"),
        "tail structural trade ledger",
    )
    hybrid_by_signal = {
        str(row["signal_id"]): row
        for row in tail_structural_trade_ledger.to_dict("records")
    }
    rows = []
    for candidate in candidates.sort_values(
        ["signal_date", "signal_id"],
        kind="stable",
    ).to_dict("records"):
        signal_id = str(candidate["signal_id"])
        tail = tail_by_signal[signal_id]
        hybrid = hybrid_by_signal.get(signal_id, {})
        rows.append(
            {
                "signal_id": signal_id,
                "signal_date": _date_text(candidate.get("signal_date")),
                "vt_symbol": str(candidate.get("vt_symbol") or ""),
                "stock_name": str(candidate.get("stock_name") or ""),
                "sector_id": str(candidate.get("sector_id") or ""),
                "concept_name": str(candidate.get("concept_name") or ""),
                "time_block": str(candidate.get("time_block") or ""),
                "causal_rank": _integer(candidate.get("causal_rank")),
                "strong_days_ge_9_5pct": _integer(
                    candidate.get("strong_days_ge_9_5pct")
                ),
                "volume_ratio_prior5": _number(
                    candidate.get("volume_ratio_prior5")
                ),
                "stock_ma5_ma10_gap_pct": _number(
                    candidate.get("stock_ma5_ma10_gap_pct")
                ),
                "active_direction": str(candidate.get("active_direction") or ""),
                "structural_net_return_pct": _number(
                    candidate.get("net_return_pct")
                ),
                "tail_status": str(tail.get("status") or ""),
                "tail_reason": (
                    str(tail["reason"]) if tail.get("reason") is not None else None
                ),
                "tail_net_return_pct": _number(tail.get("net_return_pct")),
                "tail_double_cost_net_return_pct": _number(
                    tail.get("double_cost_net_return_pct")
                ),
                "hybrid_status": str(hybrid.get("status") or "unavailable"),
                "hybrid_reason": (
                    str(hybrid["reason"])
                    if hybrid.get("reason") is not None
                    else (
                        "incomplete_1455_entry"
                        if signal_id not in hybrid_by_signal
                        else None
                    )
                ),
                "hybrid_net_return_pct": _number(hybrid.get("net_return_pct")),
                "cutoff_recognition_passed": (
                    bool(cutoff_by_signal[signal_id]["cutoff_recognition_passed"])
                    if signal_id in cutoff_by_signal
                    else None
                ),
            }
        )
    return rows


def _summarize_cutoff_audit(audit: pd.DataFrame) -> dict[str, Any]:
    _require_columns(audit, CUTOFF_AUDIT_COLUMNS, "14:50 cutoff audit")
    if audit["signal_id"].astype(str).duplicated().any():
        raise ValueError("14:50 cutoff audit signal IDs must be unique")
    return {
        "audited_signals": int(len(audit)),
        "passed_signals": int(audit["cutoff_recognition_passed"].astype(bool).sum()),
        "failed_signals": int((~audit["cutoff_recognition_passed"].astype(bool)).sum()),
        "check_pass_counts": {
            column: int(audit[column].astype(bool).sum())
            for column in CUTOFF_CHECK_COLUMNS
        },
        "definition": (
            "uses only prior daily closes and completed stock 5-minute bars through "
            "14:50; excludes the 14:55 and 15:00 bars"
        ),
    }


def _summarize_hybrid_segments(
    candidates: pd.DataFrame,
    trade_ledger: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    _require_columns(candidates, ("signal_id", "time_block"), "hybrid segment candidate")
    _require_columns(
        trade_ledger,
        ("signal_id", "status", "net_return_pct"),
        "hybrid segment ledger",
    )
    blocks = candidates.loc[:, ["signal_id", "time_block"]].copy()
    blocks["signal_id"] = blocks["signal_id"].astype(str)
    ledger = trade_ledger.loc[:, ["signal_id", "status", "net_return_pct"]].copy()
    ledger["signal_id"] = ledger["signal_id"].astype(str)
    panel = ledger.merge(blocks, on="signal_id", how="left", validate="one_to_one")
    if panel["time_block"].isna().any():
        raise ValueError("hybrid segment ledger has unknown signal IDs")
    segments = {"all": _summarize_hybrid_returns(panel)}
    for block_number in range(1, 6):
        block = f"block_{block_number}"
        segments[block] = _summarize_hybrid_returns(
            panel.loc[panel["time_block"].eq(block)]
        )
    return segments


def _summarize_hybrid_returns(frame: pd.DataFrame) -> dict[str, Any]:
    returns = pd.to_numeric(frame["net_return_pct"], errors="coerce")
    closed = returns.loc[frame["status"].eq("closed") & returns.notna()]
    losses = abs(float(closed.loc[closed.lt(0)].sum()))
    profit_factor = (
        float(closed.loc[closed.gt(0)].sum()) / losses
        if losses > 0
        else None
    )
    return {
        "signals": int(len(frame)),
        "closed_trades": int(len(closed)),
        "win_rate_pct": float(closed.gt(0).mean() * 100.0) if len(closed) else None,
        "mean_net_return_pct": float(closed.mean()) if len(closed) else None,
        "profit_factor": profit_factor,
        "compound_return_pct": None,
        "maximum_drawdown_pct": None,
    }


def _validate_cash_comparison(
    comparison: dict[str, dict[str, Any]],
) -> None:
    expected = tuple(f"capacity_{capacity}" for capacity in range(1, 5))
    if tuple(comparison) != expected:
        raise ValueError("structural cash comparison must retain capacities 1/2/3/4")
    required = (
        "capacity",
        "initial_cash",
        "final_equity",
        "compound_return_pct",
        "maximum_drawdown_pct",
        "signals",
        "accepted_entries",
        "closed_trades",
        "cash_win_rate_pct",
        "skipped_entries",
        "rejected_entries",
        "unclosed_trades",
        "total_fees",
        "reason_counts",
    )
    initial_cash = None
    for capacity, key in enumerate(expected, start=1):
        metrics = comparison[key]
        missing = [name for name in required if name not in metrics]
        if missing:
            raise ValueError(
                f"missing structural cash capacity metrics: {', '.join(missing)}"
            )
        if int(metrics["capacity"]) != capacity:
            raise ValueError("structural cash capacity key/value mismatch")
        current_initial = float(metrics["initial_cash"])
        if initial_cash is None:
            initial_cash = current_initial
        elif current_initial != initial_cash:
            raise ValueError("structural cash capacities must share initial cash")


def _cash_initial(comparison: dict[str, dict[str, Any]]) -> float:
    _validate_cash_comparison(comparison)
    return float(comparison["capacity_1"]["initial_cash"])


def _cash_table(comparison: dict[str, dict[str, Any]]) -> list[str]:
    _validate_cash_comparison(comparison)
    lines = [
        "| Capacity | Accepted | Skipped | Rejected | Final equity | Compound | Drawdown | Closed | Win | Fees |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for metrics in comparison.values():
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{int(metrics['capacity'])}`",
                    str(int(metrics["accepted_entries"])),
                    str(int(metrics["skipped_entries"])),
                    str(int(metrics["rejected_entries"])),
                    f"{float(metrics['final_equity']):.2f}",
                    _percent(metrics["compound_return_pct"]),
                    _percent(metrics["maximum_drawdown_pct"]),
                    str(int(metrics["closed_trades"])),
                    _percent(metrics["cash_win_rate_pct"]),
                    f"{float(metrics['total_fees']):.2f}",
                ]
            )
            + " |"
        )
    return lines


def _hybrid_diagnostic_lines(diagnostics: dict[str, Any]) -> list[str]:
    lines = [
        f"- Closed/winners/losers: `{diagnostics['closed_trades']}/"
        f"{diagnostics['winning_trades']}/{diagnostics['losing_trades']}`.",
        "",
        "| Numeric feature | Winner mean | Loser mean | Difference |",
        "| --- | ---: | ---: | ---: |",
    ]
    for feature, metrics in diagnostics["numeric"].items():
        lines.append(
            f"| `{feature}` | {_decimal(metrics.get('winner_mean'))} | "
            f"{_decimal(metrics.get('loser_mean'))} | "
            f"{_decimal(metrics.get('winner_minus_loser_mean'))} |"
        )
    lines.extend(
        [
            "",
            "| Active direction | Trades | Win | Mean |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    directions = diagnostics["categorical"].get("active_direction", {})
    for direction, metrics in directions.items():
        lines.append(
            f"| `{direction}` | {metrics['trades']} | "
            f"{_percent(metrics.get('win_rate_pct'))} | "
            f"{_percent(metrics.get('mean_net_return_pct'))} |"
        )
    return lines


def _segment_table(
    segments: dict[str, dict[str, Any]],
    *,
    structural: bool,
) -> list[str]:
    lines = [
        "| Segment | Signals | Closed | Win | Mean | PF | Compound | Drawdown |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for segment, metrics in segments.items():
        win_key = "descriptive_positive_share_pct" if structural else "win_rate_pct"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{segment}`",
                    str(metrics.get("signals", 0)),
                    str(metrics.get("closed_trades", 0)),
                    _percent(metrics.get(win_key)),
                    _percent(metrics.get("mean_net_return_pct")),
                    _decimal(metrics.get("profit_factor")),
                    _percent(metrics.get("compound_return_pct")),
                    _percent(metrics.get("maximum_drawdown_pct")),
                ]
            )
            + " |"
        )
    return lines


def _case_lines(cases: Sequence[dict[str, Any]]) -> list[str]:
    return [
        "| "
        + " | ".join(
            [
                str(case.get("signal_date") or "-"),
                f"{case.get('stock_name') or '-'} `{case.get('vt_symbol') or '-'}`",
                str(case.get("concept_name") or "-"),
                str(case.get("time_block") or "-"),
                _percent(case.get("structural_net_return_pct")),
                _percent(case.get("hybrid_net_return_pct")),
                str(case.get("hybrid_status") or "-"),
            ]
        )
        + " |"
        for case in cases
    ]


def _date_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date().isoformat()


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _greater(value: Any, threshold: float) -> bool:
    number = _number(value)
    return number is not None and number > threshold


def _greater_equal(value: Any, threshold: float) -> bool:
    number = _number(value)
    return number is not None and number >= threshold


def _percent(value: Any) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:.4f}%"


def _decimal(value: Any) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:.4f}"


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return pd.Timestamp(value).isoformat()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def build_tail_scheme_candidates(
    candidates: pd.DataFrame,
    daily_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Map selected MA5 rows to the established outcome-neutral tail schema."""

    required = (
        "signal_id",
        "episode_id",
        "signal_date",
        "entry_date",
        "wave_start_date",
        "vt_symbol",
        "stock_name",
        "sector_id",
        "concept_name",
        "causal_rank",
        "active_direction",
        "danger_state",
        "market_phase",
        "time_block",
    )
    _require_columns(candidates, required, "leader MA5 scheme candidate")
    if candidates["signal_id"].duplicated().any():
        raise ValueError("leader MA5 scheme signal IDs must be unique")
    previous_dates = _previous_trading_dates(daily_bars)
    rows = [
        _tail_candidate_row(candidate, previous_dates)
        for candidate in candidates.to_dict("records")
    ]
    return pd.DataFrame.from_records(rows).sort_values(
        ["entry_date", "event_id"],
        kind="stable",
    ).reset_index(drop=True)


def build_cutoff_recognition_audit(
    candidates: pd.DataFrame,
    features: pd.DataFrame,
    daily_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Re-evaluate the daily reclaim with only information complete at 14:50."""

    candidate_columns = (
        "signal_id",
        "pullback_confirmation_date",
        "reference_peak_date",
        "reference_peak_price",
    )
    feature_columns = (
        "signal_id",
        "vt_symbol",
        "entry_date",
        "tail_close_price",
        "session_low_through_1450",
        "context_close_price",
    )
    _require_columns(candidates, candidate_columns, "cutoff recognition candidate")
    _require_columns(features, feature_columns, "cutoff recognition feature")
    _require_columns(
        daily_bars,
        ("vt_symbol", "trade_date", "close_price"),
        "cutoff recognition daily bar",
    )
    candidate_frame = candidates.loc[:, list(candidate_columns)].copy()
    candidate_frame["signal_id"] = candidate_frame["signal_id"].astype(str)
    if candidate_frame["signal_id"].duplicated().any():
        raise ValueError("cutoff recognition candidate signal IDs must be unique")
    feature_frame = features.loc[:, list(feature_columns)].copy()
    feature_frame["signal_id"] = feature_frame["signal_id"].astype(str)
    if feature_frame["signal_id"].duplicated().any():
        raise ValueError("cutoff recognition feature signal IDs must be unique")
    merged = feature_frame.merge(
        candidate_frame,
        on="signal_id",
        how="left",
        validate="one_to_one",
    )
    if merged["reference_peak_price"].isna().any():
        raise ValueError("cutoff recognition feature has unknown candidate identity")

    bars = daily_bars.loc[:, ["vt_symbol", "trade_date", "close_price"]].copy()
    bars["vt_symbol"] = bars["vt_symbol"].astype(str)
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise")
    bars["close_price"] = pd.to_numeric(bars["close_price"], errors="raise")
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("cutoff recognition daily bar identities must be unique")

    rows = [_cutoff_audit_row(row, bars) for row in merged.to_dict("records")]
    return pd.DataFrame.from_records(rows, columns=CUTOFF_AUDIT_COLUMNS).sort_values(
        "signal_id",
        kind="stable",
    ).reset_index(drop=True)


def _cutoff_audit_row(
    row: dict[str, Any],
    daily_bars: pd.DataFrame,
) -> dict[str, Any]:
    entry_date = pd.Timestamp(row["entry_date"]).normalize()
    symbol = str(row["vt_symbol"])
    prior = daily_bars.loc[
        daily_bars["vt_symbol"].eq(symbol)
        & daily_bars["trade_date"].lt(entry_date)
    ].sort_values("trade_date", kind="stable").tail(4)
    if len(prior) != 4:
        raise ValueError(f"cutoff recognition needs four prior closes for {symbol}")
    tail_close = float(row["tail_close_price"])
    session_low = float(row["session_low_through_1450"])
    previous_close = float(row["context_close_price"])
    provisional_ma5 = (float(prior["close_price"].sum()) + tail_close) / 5.0
    reference_peak_date = pd.Timestamp(row["reference_peak_date"]).normalize()
    reference_peak = float(row["reference_peak_price"])
    confirmation_date = pd.Timestamp(row["pullback_confirmation_date"]).normalize()
    peak_preexists = reference_peak_date < entry_date
    pullback_known = confirmation_date < entry_date or (
        peak_preexists
        and session_low <= reference_peak * (1.0 - MIN_PULLBACK_PCT / 100.0)
    )
    approach_known = session_low <= provisional_ma5 * (
        1.0 + APPROACH_TOLERANCE_PCT / 100.0
    )
    checks = {
        "cutoff_reclaimed_provisional_ma5": tail_close >= provisional_ma5,
        "cutoff_not_below_previous_close": tail_close >= previous_close,
        "cutoff_approached_provisional_ma5": approach_known,
        "cutoff_pullback_known": pullback_known,
        "cutoff_reference_peak_preexists": peak_preexists,
    }
    return {
        "signal_id": str(row["signal_id"]),
        "provisional_ma5_at_1450": provisional_ma5,
        "prior_close_count": len(prior),
        **checks,
        "cutoff_recognition_passed": all(checks.values()),
    }


def build_causal_structural_cash_trades(
    candidates: pd.DataFrame,
    daily_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Shift each close-confirmed structural trigger to the next stock open."""

    candidate_columns = (
        "signal_id",
        "vt_symbol",
        "sector_id",
        "signal_date",
        "entry_date",
        "exit_date",
        "causal_rank",
        "reference_peak_price",
    )
    _require_columns(candidates, candidate_columns, "causal structural candidate")
    _require_columns(
        daily_bars,
        ("vt_symbol", "trade_date"),
        "causal structural daily bar",
    )
    if candidates["signal_id"].astype(str).duplicated().any():
        raise ValueError("causal structural candidate signal IDs must be unique")

    candidate_frame = candidates.loc[:, list(candidate_columns)].copy()
    candidate_frame["signal_id"] = candidate_frame["signal_id"].astype(str)
    candidate_frame["structural_trigger_date"] = pd.to_datetime(
        candidate_frame.pop("exit_date"),
        errors="raise",
    ).dt.date
    bars = daily_bars.loc[:, ["vt_symbol", "trade_date"]].copy()
    bars["vt_symbol"] = bars["vt_symbol"].astype(str)
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.date
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("causal structural daily bar identities must be unique")
    calendars = {
        str(symbol): tuple(sorted(group["trade_date"].unique()))
        for symbol, group in bars.groupby("vt_symbol", sort=False)
    }
    exit_dates = []
    for row in candidate_frame.itertuples(index=False):
        later = [
            trade_date
            for trade_date in calendars.get(str(row.vt_symbol), ())
            if trade_date > row.structural_trigger_date
        ]
        if not later:
            raise ValueError(
                "missing next-session structural exit for "
                f"{row.vt_symbol} after {row.structural_trigger_date}"
            )
        exit_dates.append(later[0])
    candidate_frame["exit_date"] = exit_dates
    candidate_frame["exit_price_mode"] = "open"
    return candidate_frame.sort_values(
        ["entry_date", "causal_rank", "signal_id"],
        kind="stable",
    ).reset_index(drop=True)


def build_tail_structural_cash_trades(
    candidates: pd.DataFrame,
    tail_execution: pd.DataFrame,
    daily_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Combine filled D 14:55 entries with causal next-open structural exits."""

    execution_columns = ("event_id", "entry_time", "entry_price_raw")
    _require_columns(tail_execution, execution_columns, "tail execution ledger")
    if tail_execution["event_id"].astype(str).duplicated().any():
        raise ValueError("tail execution event IDs must be unique")
    candidate_frame = build_causal_structural_cash_trades(candidates, daily_bars)
    execution_frame = tail_execution.loc[:, list(execution_columns)].copy()
    execution_frame["signal_id"] = execution_frame.pop("event_id").astype(str)
    filled = execution_frame.loc[
        execution_frame["entry_time"].notna()
        & pd.to_numeric(
            execution_frame["entry_price_raw"],
            errors="coerce",
        ).notna()
    ].copy()
    unknown = set(filled["signal_id"]) - set(candidate_frame["signal_id"])
    if unknown:
        raise ValueError("tail execution contains unknown filled signal IDs")
    merged = candidate_frame.merge(
        filled.loc[:, ["signal_id", "entry_price_raw"]],
        on="signal_id",
        how="inner",
        validate="one_to_one",
    )
    merged = merged.loc[
        pd.to_numeric(merged["entry_price_raw"], errors="raise").lt(
            pd.to_numeric(merged["reference_peak_price"], errors="raise")
        )
    ].copy()
    merged["entry_date"] = pd.to_datetime(
        merged["signal_date"],
        errors="raise",
    ).dt.date
    merged = merged.rename(
        columns={"entry_price_raw": "entry_price_raw_override"}
    )
    return merged.sort_values(
        ["entry_date", "causal_rank", "signal_id"],
        kind="stable",
    ).reset_index(drop=True)


def build_hybrid_feature_diagnostics(
    candidates: pd.DataFrame,
    features: pd.DataFrame,
    trade_ledger: pd.DataFrame,
) -> dict[str, Any]:
    """Compare observed hybrid winners and losers without changing selection."""

    candidate_columns = (
        "signal_id",
        "volume_ratio_prior5",
        "stock_ma5_ma10_gap_pct",
        *HYBRID_CATEGORICAL_DIAGNOSTICS,
    )
    feature_columns = (
        "signal_id",
        *HYBRID_NUMERIC_DIAGNOSTICS[2:],
    )
    ledger_columns = ("signal_id", "status", "net_return_pct")
    _require_columns(candidates, candidate_columns, "hybrid diagnostic candidate")
    _require_columns(features, feature_columns, "hybrid diagnostic feature")
    _require_columns(trade_ledger, ledger_columns, "hybrid diagnostic ledger")
    candidate_frame = candidates.loc[:, list(candidate_columns)].copy()
    feature_frame = features.loc[:, list(feature_columns)].copy()
    ledger_frame = trade_ledger.loc[:, list(ledger_columns)].copy()
    for frame, label in (
        (candidate_frame, "candidate"),
        (feature_frame, "feature"),
        (ledger_frame, "ledger"),
    ):
        frame["signal_id"] = frame["signal_id"].astype(str)
        if frame["signal_id"].duplicated().any():
            raise ValueError(f"hybrid diagnostic {label} signal IDs must be unique")
    ledger_frame["net_return_pct"] = pd.to_numeric(
        ledger_frame["net_return_pct"],
        errors="coerce",
    )
    closed = ledger_frame.loc[
        ledger_frame["status"].eq("closed")
        & ledger_frame["net_return_pct"].notna()
    ].copy()
    panel = (
        closed.merge(candidate_frame, on="signal_id", validate="one_to_one")
        .merge(feature_frame, on="signal_id", validate="one_to_one")
        .sort_values("signal_id", kind="stable")
        .reset_index(drop=True)
    )
    panel["winner"] = panel["net_return_pct"].gt(0)
    numeric = {
        column: _winner_loser_numeric(panel, column)
        for column in HYBRID_NUMERIC_DIAGNOSTICS
    }
    categorical = {
        column: _categorical_outcome_diagnostic(panel, column)
        for column in HYBRID_CATEGORICAL_DIAGNOSTICS
    }
    return {
        "closed_trades": int(len(panel)),
        "winning_trades": int(panel["winner"].sum()),
        "losing_trades": int((~panel["winner"]).sum()),
        "numeric": numeric,
        "categorical": categorical,
        "selection_effect": "diagnostic_only",
    }


def _winner_loser_numeric(panel: pd.DataFrame, column: str) -> dict[str, Any]:
    values = pd.to_numeric(panel[column], errors="coerce")
    winners = values.loc[panel["winner"] & values.notna()]
    losers = values.loc[~panel["winner"] & values.notna()]
    winner_mean = float(winners.mean()) if len(winners) else None
    loser_mean = float(losers.mean()) if len(losers) else None
    return {
        "winner_count": int(len(winners)),
        "loser_count": int(len(losers)),
        "winner_mean": winner_mean,
        "loser_mean": loser_mean,
        "winner_median": float(winners.median()) if len(winners) else None,
        "loser_median": float(losers.median()) if len(losers) else None,
        "winner_minus_loser_mean": (
            winner_mean - loser_mean
            if winner_mean is not None and loser_mean is not None
            else None
        ),
    }


def _categorical_outcome_diagnostic(
    panel: pd.DataFrame,
    column: str,
) -> dict[str, dict[str, Any]]:
    groups = {}
    for value, group in panel.groupby(column, dropna=False, sort=True):
        returns = pd.to_numeric(group["net_return_pct"], errors="raise")
        key = "UNKNOWN" if pd.isna(value) else str(value)
        groups[key] = {
            "trades": int(len(group)),
            "win_rate_pct": float(returns.gt(0).mean() * 100.0),
            "mean_net_return_pct": float(returns.mean()),
        }
    return groups


def execute_tail_scheme(
    candidates: pd.DataFrame,
    daily_bars: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build D 14:50 features and execute D 14:55 to D+1 10:35 trades."""

    mapped = build_tail_scheme_candidates(candidates, daily_bars)
    features = build_tail_feature_panel(mapped, daily_bars, minute_bars)
    cutoff_audit = build_cutoff_recognition_audit(
        candidates,
        features,
        daily_bars,
    )
    features = features.merge(
        cutoff_audit,
        on="signal_id",
        how="left",
        validate="one_to_one",
    )
    eligible = features.loc[features["cutoff_recognition_passed"].astype(bool)].copy()
    ledger = execute_tail_trades(eligible, daily_bars, minute_bars)
    return features, ledger


def _tail_candidate_row(
    candidate: dict[str, Any],
    previous_dates: dict[tuple[str, pd.Timestamp], pd.Timestamp],
) -> dict[str, Any]:
    signal_date = pd.Timestamp(candidate["signal_date"]).normalize()
    symbol = str(candidate["vt_symbol"])
    context_date = previous_dates.get((symbol, signal_date))
    if context_date is None:
        raise ValueError(f"missing previous stock session for {symbol} on {signal_date.date()}")
    causal_rank = int(candidate["causal_rank"])
    if causal_rank not in (1, 2, 3):
        raise ValueError("leader MA5 causal rank must be within Top3")
    return {
        "event_id": str(candidate["signal_id"]),
        "signal_id": str(candidate["signal_id"]),
        "leader_spell_id": str(candidate["episode_id"]),
        "recognition_source_date": pd.Timestamp(
            candidate["wave_start_date"]
        ).date(),
        "context_date": context_date.date(),
        "entry_date": signal_date.date(),
        "planned_exit_date": pd.Timestamp(candidate["entry_date"]).date(),
        "sector_id": str(candidate["sector_id"]),
        "concept_name": str(candidate["concept_name"]),
        "cycle_id": str(candidate["episode_id"]),
        "vt_symbol": symbol,
        "stock_name": str(candidate["stock_name"]),
        "recognition_rank": causal_rank,
        "cycle_relative_percentile": (4.0 - causal_rank) / 3.0,
        "spell_session_offset": 3,
        "active_direction": str(candidate["active_direction"]),
        "danger_state": str(candidate["danger_state"]),
        "market_phase": str(candidate["market_phase"]),
        "main_rise": True,
        "is_top3": True,
        "rank_mode": TAIL_RANK_MODE,
        "evidence_level": TAIL_EVIDENCE_LEVEL,
        "block": _block_number(candidate["time_block"]),
    }


def _previous_trading_dates(
    daily_bars: pd.DataFrame,
) -> dict[tuple[str, pd.Timestamp], pd.Timestamp]:
    _require_columns(daily_bars, ("vt_symbol", "trade_date"), "stock daily bar")
    frame = daily_bars.loc[:, ["vt_symbol", "trade_date"]].copy()
    frame["vt_symbol"] = frame["vt_symbol"].astype(str)
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"],
        errors="raise",
    ).dt.normalize()
    if frame.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock daily bar identities must be unique")
    result: dict[tuple[str, pd.Timestamp], pd.Timestamp] = {}
    for symbol, group in frame.groupby("vt_symbol", sort=False):
        dates = group["trade_date"].sort_values(kind="stable").tolist()
        result.update(
            {
                (str(symbol), pd.Timestamp(current)): pd.Timestamp(previous)
                for previous, current in zip(dates[:-1], dates[1:], strict=True)
            }
        )
    return result


def _block_number(value: Any) -> int:
    text = str(value)
    if not text.startswith("block_"):
        raise ValueError(f"invalid leader MA5 time block: {text}")
    number = int(text.removeprefix("block_"))
    if number not in range(1, 6):
        raise ValueError(f"invalid leader MA5 time block: {text}")
    return number


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
