"""Structural-exit study for causal main-rise weak-to-strong entries."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from .leader_ma5_cash import simulate_structural_cash_account
from .main_rise_weak_to_strong_study import (
    DIAGNOSTIC_RULE_VERSION,
    REFERENCE_SYMBOLS,
    ROUND_TRIP_COST_PCT,
    WeakToStrongRule,
    _first_rejection_reason,
    candidate_rules,
    load_study_data,
    select_rule_signals,
)


STUDY_VERSION = "main-rise-structural-exit-v1"
ENTRY_EXECUTION_ASSUMPTION = "same_close_research_proxy"
CASH_CAPACITY = 4
STOCK_BAR_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
)
CONCEPT_BAR_COLUMNS = (
    "sector_id",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
)
STRUCTURAL_SIGNAL_COLUMNS = (
    "signal_id",
    "rule_version",
    "trade_date",
    "vt_symbol",
    "stock_name",
    "sector_id",
    "concept_name",
    "close_price",
    "prior_high20",
    "leader_rank",
    "block",
    "pullback_opportunity_ordinal",
    "support_zone",
)


@dataclass(frozen=True)
class StructuralStudyData:
    """Frozen signal inputs and quarantined structural-outcome bars."""

    features: pd.DataFrame
    d1_outcomes: pd.DataFrame
    stock_bars: pd.DataFrame
    concept_bars: pd.DataFrame
    coverage: dict[str, Any]
    fingerprints: dict[str, dict[str, Any]]


def prepare_stock_exit_features(daily_bars: pd.DataFrame) -> pd.DataFrame:
    """Calculate causal stock MA20 values from ordered completed daily bars."""

    frame = _prepare_daily_bars(
        daily_bars,
        identity_column="vt_symbol",
        required_columns=STOCK_BAR_COLUMNS,
    )
    frame["ma20"] = frame.groupby("vt_symbol", sort=False)[
        "close_price"
    ].transform(lambda values: values.rolling(20, min_periods=20).mean())
    return frame


def prepare_concept_exit_features(concept_bars: pd.DataFrame) -> pd.DataFrame:
    """Replay the existing concept structure contract without future fields."""

    frame = _prepare_daily_bars(
        concept_bars,
        identity_column="sector_id",
        required_columns=CONCEPT_BAR_COLUMNS,
    )
    close_group = frame.groupby("sector_id", sort=False)["close_price"]
    frame["ma20"] = close_group.transform(
        lambda values: values.rolling(20, min_periods=20).mean()
    )
    frame["close_lag20"] = close_group.shift(20)
    frame["high20"] = close_group.transform(
        lambda values: values.rolling(20, min_periods=20).max()
    )
    frame["ma20_lag5"] = frame.groupby("sector_id", sort=False)["ma20"].shift(5)
    frame["concept_return20_pct"] = (
        frame["close_price"].div(frame["close_lag20"]).sub(1.0).mul(100.0)
    )
    frame["concept_drawdown20_pct"] = (
        frame["close_price"].div(frame["high20"]).sub(1.0).mul(100.0)
    )
    required = ("ma20", "ma20_lag5", "close_lag20", "high20")
    frame["concept_structure_known"] = frame[list(required)].notna().all(axis=1)
    frame["concept_structure_intact"] = (
        frame["concept_structure_known"]
        & frame["close_price"].ge(frame["ma20"] * 0.98)
        & frame["ma20"].gt(frame["ma20_lag5"])
        & frame["concept_return20_pct"].ge(0.0)
        & frame["concept_drawdown20_pct"].ge(-12.0)
    )
    return frame


def build_structural_exit_trades(
    signals: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
    *,
    round_trip_cost_pct: float = ROUND_TRIP_COST_PCT,
    outcome_end_exclusive: object | None = None,
) -> pd.DataFrame:
    """Apply the frozen higher-high/structure-break exits after D close."""

    if round_trip_cost_pct < 0:
        raise ValueError("round-trip cost cannot be negative")
    _require_columns(signals, STRUCTURAL_SIGNAL_COLUMNS, "structural signal")
    if signals.empty:
        return pd.DataFrame()
    signal_frame = signals.copy()
    signal_frame["trade_date"] = pd.to_datetime(
        signal_frame["trade_date"], errors="raise"
    ).dt.normalize()
    outcome_boundary = _normalize_outcome_boundary(outcome_end_exclusive)
    if outcome_boundary is not None and signal_frame["trade_date"].ge(
        outcome_boundary
    ).any():
        raise ValueError("structural signals must precede the outcome boundary")
    if signal_frame["signal_id"].astype(str).duplicated().any():
        raise ValueError("structural signal IDs must be unique")

    stock_features = prepare_stock_exit_features(stock_bars)
    concept_features = prepare_concept_exit_features(concept_bars)
    stock_paths = {
        str(symbol): group.reset_index(drop=True)
        for symbol, group in stock_features.groupby("vt_symbol", sort=False)
    }
    concept_paths = {
        str(sector_id): group.reset_index(drop=True)
        for sector_id, group in concept_features.groupby("sector_id", sort=False)
    }
    records = []
    for signal in signal_frame.sort_values(
        ["trade_date", "vt_symbol", "signal_id"], kind="stable"
    ).to_dict("records"):
        symbol = str(signal["vt_symbol"])
        sector_id = str(signal["sector_id"])
        stock_path = stock_paths.get(symbol)
        concept_path = concept_paths.get(sector_id)
        if stock_path is None:
            raise ValueError(f"missing stock exit bars for {symbol}")
        if concept_path is None:
            raise ValueError(f"missing concept exit bars for {sector_id}")
        records.append(
            _replay_structural_signal(
                signal,
                stock_path,
                concept_path,
                round_trip_cost_pct=round_trip_cost_pct,
                outcome_end_exclusive=outcome_boundary,
            )
        )
    return pd.DataFrame.from_records(records).sort_values(
        ["trade_date", "leader_rank", "signal_id"], kind="stable"
    ).reset_index(drop=True)


def summarize_structural_returns(trades: pd.DataFrame) -> dict[str, Any]:
    """Summarize closed trades while retaining the right-censored denominator."""

    if trades.empty:
        return _empty_metrics()
    _require_columns(
        trades,
        ("exit_date", "net_return_pct", "holding_sessions"),
        "structural trade",
    )
    returns = pd.to_numeric(
        trades.loc[trades["exit_date"].notna(), "net_return_pct"],
        errors="coerce",
    ).dropna()
    holding = pd.to_numeric(
        trades.loc[trades["exit_date"].notna(), "holding_sessions"],
        errors="coerce",
    ).dropna()
    if returns.empty:
        metrics = _empty_metrics()
        metrics["entries"] = int(len(trades))
        metrics["censored_trades"] = int(len(trades))
        return metrics
    gains = float(returns.loc[returns.gt(0)].sum())
    losses = abs(float(returns.loc[returns.lt(0)].sum()))
    equity = (1.0 + returns / 100.0).cumprod()
    drawdown = (equity / equity.cummax() - 1.0) * 100.0
    return {
        "entries": int(len(trades)),
        "closed_trades": int(len(returns)),
        "censored_trades": int(len(trades) - len(returns)),
        "positive_rate_pct": float(returns.gt(0).mean() * 100.0),
        "mean_return_pct": float(returns.mean()),
        "median_return_pct": float(returns.median()),
        "profit_factor": (
            gains / losses if losses > 0 else (math.inf if gains > 0 else None)
        ),
        "compound_return_pct": float((equity.iloc[-1] - 1.0) * 100.0),
        "maximum_drawdown_pct": float(drawdown.min()),
        "median_holding_sessions": float(holding.median()) if not holding.empty else None,
    }


def evaluate_structural_rule_grid(
    features: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
    *,
    rules: Sequence[WeakToStrongRule] | None = None,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Evaluate only blocks 1..4; block 5 bars are not replayed here."""

    selected_rules = tuple(rules or candidate_rules())
    development_end, validation_end = _selection_outcome_boundaries(features)
    rows = []
    trades_by_rule: dict[str, pd.DataFrame] = {}
    for rule in selected_rules:
        signals = select_rule_signals(features, rule)
        development_trades = build_structural_exit_trades(
            signals.loc[signals["block"].isin((1, 2, 3))].copy(),
            stock_bars,
            concept_bars,
            outcome_end_exclusive=development_end,
        )
        validation_trades = build_structural_exit_trades(
            signals.loc[signals["block"].eq(4)].copy(),
            stock_bars,
            concept_bars,
            outcome_end_exclusive=validation_end,
        )
        visible_records = [
            record
            for frame in (development_trades, validation_trades)
            for record in frame.to_dict("records")
        ]
        trades = (
            pd.DataFrame.from_records(visible_records)
            .sort_values(
                ["trade_date", "leader_rank", "signal_id"], kind="stable"
            )
            .reset_index(drop=True)
            if visible_records
            else pd.DataFrame()
        )
        trades_by_rule[rule.version] = trades
        development = summarize_structural_returns(
            development_trades
        )
        validation = summarize_structural_returns(validation_trades)
        rows.append(
            {
                **asdict(rule),
                **_prefix_metrics("development", development),
                **_prefix_metrics("validation", validation),
                "selection_qualified": _selection_gates_pass(
                    development, validation
                ),
            }
        )
    return pd.DataFrame.from_records(rows), trades_by_rule


def choose_structural_rule(grid: pd.DataFrame) -> WeakToStrongRule | None:
    """Choose one nominated rule without consulting any block-5 value."""

    required = (
        "version",
        "selection_qualified",
        "validation_positive_rate_pct",
        "validation_mean_return_pct",
        "validation_profit_factor",
        "development_mean_return_pct",
    )
    _require_columns(grid, required, "structural rule grid")
    qualified = grid.loc[grid["selection_qualified"].astype(bool)].copy()
    if qualified.empty:
        return None
    selected = qualified.sort_values(
        [
            "validation_positive_rate_pct",
            "validation_mean_return_pct",
            "validation_profit_factor",
            "development_mean_return_pct",
            "version",
        ],
        ascending=[False, False, False, False, True],
        kind="stable",
    ).iloc[0]
    values = {
        field: selected[field]
        for field in WeakToStrongRule.__dataclass_fields__
    }
    maximum_opportunity = values["maximum_opportunity_ordinal"]
    values["maximum_opportunity_ordinal"] = (
        None if pd.isna(maximum_opportunity) else int(maximum_opportunity)
    )
    values["minimum_top3_days10"] = int(values["minimum_top3_days10"])
    values["minimum_new_high_days20"] = int(values["minimum_new_high_days20"])
    return WeakToStrongRule(**values)


def final_structural_metrics(trades: pd.DataFrame) -> pd.DataFrame:
    """Calculate pooled and five-block metrics for the nominated rule only."""

    rows = [{"segment": "all", **summarize_structural_returns(trades)}]
    for block in range(1, 6):
        rows.append(
            {
                "segment": f"block_{block}",
                **summarize_structural_returns(
                    trades.loc[trades["block"].eq(block)]
                ),
            }
        )
    return pd.DataFrame.from_records(rows)


def build_structural_cash_inputs(trades: pd.DataFrame) -> pd.DataFrame:
    """Convert only closed same-close proxy trades to the shared cash contract."""

    required = (
        "signal_id",
        "vt_symbol",
        "sector_id",
        "trade_date",
        "exit_date",
        "leader_rank",
        "entry_price",
    )
    _require_columns(trades, required, "structural cash trade")
    closed = trades.loc[trades["exit_date"].notna()].copy()
    if closed.empty:
        return pd.DataFrame(
            columns=[
                "signal_id",
                "vt_symbol",
                "sector_id",
                "entry_date",
                "exit_date",
                "causal_rank",
                "entry_price_raw_override",
                "exit_price_mode",
            ]
        )
    if closed["signal_id"].astype(str).duplicated().any():
        raise ValueError("structural cash signal IDs must be unique")
    result = pd.DataFrame(
        {
            "signal_id": closed["signal_id"].astype(str),
            "vt_symbol": closed["vt_symbol"].astype(str),
            "sector_id": closed["sector_id"].astype(str),
            "entry_date": pd.to_datetime(
                closed["trade_date"], errors="raise"
            ).dt.date,
            "exit_date": pd.to_datetime(
                closed["exit_date"], errors="raise"
            ).dt.date,
            "causal_rank": pd.to_numeric(
                closed["leader_rank"], errors="raise"
            ).astype(int),
            "entry_price_raw_override": pd.to_numeric(
                closed["entry_price"], errors="raise"
            ),
            "exit_price_mode": "close",
        }
    )
    return result.sort_values(
        ["entry_date", "causal_rank", "signal_id"], kind="stable"
    ).reset_index(drop=True)


def final_structural_gates(
    metrics: pd.DataFrame,
    cash_result: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    """Apply the predeclared signal and four-position cash gates."""

    frame = metrics.set_index("segment", drop=False)
    pooled = _metric_row(frame, "all")
    block4 = _metric_row(frame, "block_4")
    block5 = _metric_row(frame, "block_5")
    checks = (
        (int(pooled.get("closed_trades") or 0) >= 100, "pooled_closed_trades_below_100"),
        (int(block4.get("closed_trades") or 0) >= 30, "block4_closed_trades_below_30"),
        (int(block5.get("closed_trades") or 0) >= 30, "block5_closed_trades_below_30"),
        (_finite_or_zero(pooled.get("positive_rate_pct")) > 60.0, "pooled_win_rate_not_above_60"),
        (_finite_or_zero(block4.get("positive_rate_pct")) > 60.0, "block4_win_rate_not_above_60"),
        (_finite_or_zero(block5.get("positive_rate_pct")) > 60.0, "block5_win_rate_not_above_60"),
        (_finite_or_zero(pooled.get("mean_return_pct")) > 0.0, "pooled_mean_not_positive"),
        (_finite_or_zero(pooled.get("profit_factor")) >= 1.20, "pooled_pf_below_1_20"),
        (_finite_or_zero(block4.get("mean_return_pct")) > 0.0, "block4_mean_not_positive"),
        (_finite_or_zero(block4.get("profit_factor")) > 1.0, "block4_pf_not_above_1"),
        (_finite_or_zero(block5.get("mean_return_pct")) > 0.0, "block5_mean_not_positive"),
        (_finite_or_zero(block5.get("profit_factor")) > 1.0, "block5_pf_not_above_1"),
        (int(cash_result.get("closed_trades") or 0) >= 60, "cash_closed_trades_below_60"),
        (_finite_or_zero(cash_result.get("cash_win_rate_pct")) > 60.0, "cash_win_rate_not_above_60"),
        (_finite_or_zero(cash_result.get("compound_return_pct")) > 60.0, "cash_compound_not_above_60"),
        (_finite_or(cash_result.get("maximum_drawdown_pct"), -100.0) >= -10.0, "cash_drawdown_below_minus_10"),
        (_finite_or(cash_result.get("minimum_cash"), -1.0) >= 0.0, "cash_became_negative"),
    )
    failures = [reason for passed, reason in checks if not passed]
    return not failures, failures


def load_main_rise_structural_study_data() -> StructuralStudyData:
    """Load only bars needed by the broadest frozen structural cohort."""

    from sqlalchemy import text

    from alphaagent.server.db.session import get_engine

    from .research_protocol import fingerprint_frame

    base = load_study_data()
    broad_rule = next(
        rule for rule in candidate_rules() if rule.version == DIAGNOSTIC_RULE_VERSION
    )
    broad_signals = select_rule_signals(base.features, broad_rule)
    if broad_signals.empty:
        raise ValueError("broad structural signal denominator is empty")
    symbols = tuple(sorted(broad_signals["vt_symbol"].astype(str).unique()))
    sector_ids = tuple(sorted(broad_signals["sector_id"].astype(str).unique()))
    first_date = pd.Timestamp(base.coverage["feature_start"]).date()
    last_date = pd.Timestamp(base.coverage["feature_end"]).date()
    warmup_start = first_date - timedelta(days=60)
    engine = get_engine()
    stock_bars = pd.read_sql(
        text(_STOCK_BARS_QUERY),
        engine,
        params={
            "symbols": list(symbols),
            "start_date": warmup_start,
            "end_date": last_date,
        },
        parse_dates=["trade_date"],
    )
    concept_bars = pd.read_sql(
        text(_CONCEPT_BARS_QUERY),
        engine,
        params={
            "sector_ids": list(sector_ids),
            "start_date": warmup_start,
            "end_date": last_date,
        },
        parse_dates=["trade_date"],
    )
    if stock_bars.empty or concept_bars.empty:
        raise ValueError("structural outcome bars are incomplete")
    development_end, validation_end = _selection_outcome_boundaries(base.features)
    block_date_ranges = {
        str(int(block)): {
            "start": pd.Timestamp(group["trade_date"].min()).date().isoformat(),
            "end": pd.Timestamp(group["trade_date"].max()).date().isoformat(),
        }
        for block, group in base.features.groupby("block", sort=True)
    }
    fingerprints = {
        **base.fingerprints,
        "structural_stock_bars": fingerprint_frame(
            stock_bars,
            identity_columns=("vt_symbol", "trade_date"),
        ).as_dict(),
        "structural_concept_bars": fingerprint_frame(
            concept_bars,
            identity_columns=("sector_id", "trade_date"),
        ).as_dict(),
    }
    coverage = {
        **base.coverage,
        "broad_structural_signal_rows": int(len(broad_signals)),
        "structural_symbols": int(len(symbols)),
        "structural_sectors": int(len(sector_ids)),
        "stock_bar_rows": int(len(stock_bars)),
        "concept_bar_rows": int(len(concept_bars)),
        "structural_bar_start": warmup_start.isoformat(),
        "structural_bar_end": last_date.isoformat(),
        "block_date_ranges": block_date_ranges,
        "development_outcome_end_exclusive": development_end.date().isoformat(),
        "validation_outcome_end_exclusive": validation_end.date().isoformat(),
        "minute_rows_read": 0,
        "fund_flow_rows_read": 0,
    }
    return StructuralStudyData(
        features=base.features,
        d1_outcomes=base.outcomes,
        stock_bars=stock_bars,
        concept_bars=concept_bars,
        coverage=coverage,
        fingerprints=fingerprints,
    )


def run_main_rise_structural_exit_study() -> dict[str, Any]:
    """Nominate on blocks 1..4, then evaluate structural block 5 once."""

    data = load_main_rise_structural_study_data()
    grid, selection_trades = evaluate_structural_rule_grid(
        data.features,
        data.stock_bars,
        data.concept_bars,
    )
    diagnostic_rule = next(
        rule for rule in candidate_rules()
        if rule.version == DIAGNOSTIC_RULE_VERSION
    )
    selected = choose_structural_rule(grid)
    if selected is None:
        diagnostic = selection_trades[DIAGNOSTIC_RULE_VERSION]
        diagnostic = _attach_d1_diagnostics(diagnostic, data.d1_outcomes)
        return build_structural_exit_report(
            coverage=data.coverage,
            fingerprints=data.fingerprints,
            grid=grid,
            selected_rule=None,
            trades=pd.DataFrame(),
            metrics=pd.DataFrame(),
            cash_result={},
            qualified=False,
            failed_gates=["no_rule_passed_structural_nomination_gates"],
            reference_cases=build_reference_cases(
                diagnostic,
                data.features,
                diagnostic_rule,
                maximum_feature_block=4,
            ),
            d1_diagnostics=_d1_diagnostics(diagnostic),
        )

    signals = select_rule_signals(data.features, selected)
    trades = build_structural_exit_trades(
        signals,
        data.stock_bars,
        data.concept_bars,
    )
    trades = _attach_d1_diagnostics(trades, data.d1_outcomes)
    metrics = final_structural_metrics(trades)
    cash_inputs = build_structural_cash_inputs(trades)
    cash_result = simulate_structural_cash_account(
        cash_inputs,
        data.stock_bars,
        capacity=CASH_CAPACITY,
    )
    qualified, failed_gates = final_structural_gates(metrics, cash_result)
    return build_structural_exit_report(
        coverage=data.coverage,
        fingerprints=data.fingerprints,
        grid=grid,
        selected_rule=selected,
        trades=trades,
        metrics=metrics,
        cash_result=cash_result,
        qualified=qualified,
        failed_gates=failed_gates,
        reference_cases=build_reference_cases(
            trades,
            data.features,
            selected,
            maximum_feature_block=5,
        ),
        d1_diagnostics=_d1_diagnostics(trades),
    )


def build_structural_exit_report(
    *,
    coverage: Mapping[str, Any],
    fingerprints: Mapping[str, Any],
    grid: pd.DataFrame,
    selected_rule: WeakToStrongRule | None,
    trades: pd.DataFrame,
    metrics: pd.DataFrame,
    cash_result: Mapping[str, Any],
    qualified: bool,
    failed_gates: Sequence[str],
    reference_cases: pd.DataFrame,
    d1_diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a complete non-production structural-exit evidence report."""

    research_status = (
        "historical_structural_candidate_passed_reused_history_gates"
        if qualified
        else (
            "selected_structural_rule_failed_final_gates"
            if selected_rule is not None
            else "no_structural_rule_cleared_nomination_gates"
        )
    )
    exit_reasons = Counter(
        str(value)
        for value in trades.get("exit_reason", pd.Series(dtype=object)).dropna()
    )
    cash_public = {
        key: value
        for key, value in dict(cash_result).items()
        if key not in {"trade_ledger", "equity_curve"}
    }
    return _json_safe(
        {
            "study_version": STUDY_VERSION,
            "research_status": research_status,
            "historical_gates_passed": bool(qualified),
            "production_ready": False,
            "formal_metrics": None,
            "selected_rule": asdict(selected_rule) if selected_rule else None,
            "block5_evaluated": selected_rule is not None,
            "failed_gates": list(failed_gates),
            "contract": {
                "universe": "main_board_non_ST_current_membership_proxy",
                "market_state": "D_minus_1_close_GOLD",
                "entry": "D_completed_close",
                "entry_execution_assumption": ENTRY_EXECUTION_ASSUMPTION,
                "exit_execution_assumption": ENTRY_EXECUTION_ASSUMPTION,
                "reference_peak": "D_known_prior_high20",
                "target_exit": "first_D_plus_n_high_above_reference_peak_then_that_close",
                "stock_defense": "second_consecutive_close_below_stock_ma20",
                "concept_defense": (
                    "first_entry_concept_structure_break_then_first_available_stock_close"
                ),
                "maximum_holding": None,
                "end_of_data_fallback": None,
                "d1_role": "diagnostic_only",
                "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
                "cash_capacity": CASH_CAPACITY,
                "minute_bars_used": False,
                "fund_flow_used": False,
                "candidate_rules": len(candidate_rules()),
                "selection_blocks": [1, 2, 3, 4],
                "selection_outcome_windows": {
                    "development_blocks_1_3": "strictly_before_block_4_start",
                    "validation_block_4": "strictly_before_block_5_start",
                },
                "final_reused_history_block": 5,
            },
            "coverage": dict(coverage),
            "rule_grid": _records(grid),
            "metrics": _records(metrics),
            "cash_performance": cash_public,
            "cash_status_counts": dict(cash_result.get("status_counts") or {}),
            "cash_reason_counts": dict(cash_result.get("reason_counts") or {}),
            "exit_reason_counts": dict(sorted(exit_reasons.items())),
            "d1_diagnostics": dict(d1_diagnostics),
            "reference_cases": _records(reference_cases),
            "trades": _records(trades),
            "fingerprints": dict(fingerprints),
            "boundaries": [
                "entry rules and thresholds are unchanged from the D+1 v6 study",
                "all five historical blocks have prior research exposure",
                "D-close confirmation and D-close entry pricing are not executable fills",
                "each structural exit is confirmed by that completed bar and priced at the same close",
                "current concept memberships retain survivorship and point-in-time bias",
                "block 5 is read only after blocks 1..4 nominate one structural rule",
                "a historical pass still requires a new strict forward block",
                "no API, frontend, paper portfolio, or live strategy is changed",
            ],
            "reproduce": (
                "python -m alphaagent.server.services.low_suction.cli "
                "v2-main-rise-structural-exit-study --format markdown"
            ),
        }
    )


def render_main_rise_structural_exit_json(report: Mapping[str, Any]) -> str:
    """Render deterministic structural-exit JSON."""

    return json.dumps(
        _json_safe(dict(report)), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"


def render_main_rise_structural_exit_markdown(report: Mapping[str, Any]) -> str:
    """Render the contract, selection, holdout, cash, and case evidence."""

    coverage = _mapping(report.get("coverage"))
    selected = _mapping(report.get("selected_rule"))
    cash = _mapping(report.get("cash_performance"))
    lines = [
        "# AlphaAgent Main-Rise Structural-Exit Low-Suction Study",
        "",
        f"Research status: `{report.get('research_status')}`.",
        f"Historical gates passed: `{str(bool(report.get('historical_gates_passed'))).lower()}`; production ready: `false`.",
        "",
        "## Contract",
        "",
        "- Entry: D completed close after the unchanged dynamic Top3 weak-to-strong signal.",
        "- Target: first later high above D-known prior high20, sold at that close.",
        "- Defense: second stock close below MA20 or first entry-concept structure break, sold at the first available stock close.",
        "- Entry and exit both use completed-close research prices; neither is an executable same-close fill.",
        "- D+1 is diagnostic only; no minute bars, fund flow, maximum holding, or data-end price fallback.",
        "",
        "## Coverage",
        "",
        f"- Range: `{coverage.get('feature_start')}` to `{coverage.get('feature_end')}`.",
        f"- Features: `{coverage.get('broad_feature_rows', 0)}`; structural stock/concept bars: `{coverage.get('stock_bar_rows', 0)}/{coverage.get('concept_bar_rows', 0)}`.",
        f"- Membership: `{coverage.get('membership_mode')}`; minute/fund rows: `{coverage.get('minute_rows_read', 0)}/{coverage.get('fund_flow_rows_read', 0)}`.",
        f"- Nomination outcome cutoffs: development `< {coverage.get('development_outcome_end_exclusive')}`; validation `< {coverage.get('validation_outcome_end_exclusive')}`.",
        "",
        "## Nomination",
        "",
    ]
    if selected:
        lines.append(f"- Selected from blocks 1..4: `{selected.get('version')}`.")
        lines.append(
            f"- Reused-history block 5 evaluated: `{str(bool(report.get('block5_evaluated'))).lower()}`."
        )
    else:
        lines.append("- No rule passed the blocks 1..4 structural nomination gates; block 5 was not evaluated.")
    failed = list(report.get("failed_gates") or [])
    if failed:
        lines.append("- Failed gates: " + ", ".join(f"`{item}`" for item in failed) + ".")
    lines.extend(
        [
            "",
            "## 32-Rule Nomination Grid",
            "",
            "| Rule | Qualified | Dev Closed | Dev Censored | Dev Positive | Dev Mean | Dev PF | Val Closed | Val Censored | Val Positive | Val Mean | Val PF |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.get("rule_grid") or []:
        lines.append(
            f"| `{row.get('version')}` | `{str(bool(row.get('selection_qualified'))).lower()}` | "
            f"{row.get('development_closed_trades', 0)} | {row.get('development_censored_trades', 0)} | "
            f"{_percent(row.get('development_positive_rate_pct'))} | {_percent(row.get('development_mean_return_pct'))} | "
            f"{_number(row.get('development_profit_factor'))} | {row.get('validation_closed_trades', 0)} | "
            f"{row.get('validation_censored_trades', 0)} | {_percent(row.get('validation_positive_rate_pct'))} | "
            f"{_percent(row.get('validation_mean_return_pct'))} | {_number(row.get('validation_profit_factor'))} |"
        )
    lines.extend(
        [
            "",
            "## Structural Trade Metrics",
            "",
            "| Segment | Entries | Closed | Censored | Positive | Mean | PF | Compound | Drawdown | Hold |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.get("metrics") or []:
        lines.append(
            f"| `{row.get('segment')}` | {row.get('entries', 0)} | {row.get('closed_trades', 0)} | "
            f"{row.get('censored_trades', 0)} | {_percent(row.get('positive_rate_pct'))} | "
            f"{_percent(row.get('mean_return_pct'))} | {_number(row.get('profit_factor'))} | "
            f"{_percent(row.get('compound_return_pct'))} | {_percent(row.get('maximum_drawdown_pct'))} | "
            f"{_number(row.get('median_holding_sessions'))} |"
        )
    lines.extend(["", "## Four-Position Cash", ""])
    if cash:
        lines.extend(
            [
                f"- Closed/winning: `{cash.get('closed_trades', 0)}/{cash.get('winning_trades', 0)}`; win `{_percent(cash.get('cash_win_rate_pct'))}`.",
                f"- Final equity: `{_number(cash.get('final_equity'))}`; compound `{_percent(cash.get('compound_return_pct'))}`; drawdown `{_percent(cash.get('maximum_drawdown_pct'))}`.",
                f"- Accepted/skipped/rejected/unclosed: `{cash.get('accepted_entries', 0)}/{cash.get('skipped_entries', 0)}/{cash.get('rejected_entries', 0)}/{cash.get('unclosed_trades', 0)}`.",
            ]
        )
    else:
        lines.append("- No nominated rule, so no block-5 cash account was constructed.")
    d1 = _mapping(report.get("d1_diagnostics"))
    lines.extend(
        [
            "",
            "## D+1 Diagnostic",
            "",
            f"- Closed D+1 rows: `{d1.get('closed_d1_rows', 0)}`; D+1 positive: `{_percent(d1.get('d1_positive_rate_pct'))}`.",
            f"- D+1 non-positive but structural exit positive: `{d1.get('d1_non_positive_structural_positive', 0)}`.",
            f"- D+1 positive but structural exit non-positive: `{d1.get('d1_positive_structural_non_positive', 0)}`.",
            "",
            "## Reference Cases",
            "",
            "| Date | Stock | Concept | Status | Rank | Opportunity | Support | D+1 | Exit | Reason | Net |",
            "| --- | --- | --- | --- | ---: | ---: | --- | ---: | --- | --- | ---: |",
        ]
    )
    for row in report.get("reference_cases") or []:
        reason = row.get("rejection_reason") or row.get("exit_reason")
        lines.append(
            f"| {_date_text(row.get('trade_date'))} | {row.get('stock_name')} `{row.get('vt_symbol')}` | "
            f"{row.get('concept_name')} | `{row.get('case_status')}` | {row.get('leader_rank')} | {row.get('pullback_opportunity_ordinal')} | "
            f"{row.get('support_zone')} | {_percent(row.get('d1_net_return_pct'))} | "
            f"{_date_text(row.get('exit_date'))} | {reason} | {_percent(row.get('net_return_pct'))} |"
        )
    lines.extend(
        [
            "",
            "## Input Fingerprints",
            "",
            "| Input | Rows | Digest |",
            "| --- | ---: | --- |",
        ]
    )
    for name, value in sorted(_mapping(report.get("fingerprints")).items()):
        fingerprint = _mapping(value)
        lines.append(
            f"| `{name}` | {fingerprint.get('rows', 0)} | `{fingerprint.get('digest')}` |"
        )
    lines.extend(["", "## Boundaries", ""])
    lines.extend(f"- {item}" for item in report.get("boundaries") or [])
    lines.extend(
        [
            "",
            "## Reproduce",
            "",
            "```bash",
            str(report.get("reproduce") or ""),
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def _replay_structural_signal(
    signal: Mapping[str, Any],
    stock_path: pd.DataFrame,
    concept_path: pd.DataFrame,
    *,
    round_trip_cost_pct: float,
    outcome_end_exclusive: pd.Timestamp | None,
) -> dict[str, Any]:
    signal_date = pd.Timestamp(signal["trade_date"])
    entry_price = float(signal["close_price"])
    reference_high = float(signal["prior_high20"])
    if not math.isfinite(entry_price) or entry_price <= 0:
        raise ValueError(f"invalid structural entry price: {signal['signal_id']}")
    if not math.isfinite(reference_high) or reference_high <= entry_price:
        raise ValueError(
            f"structural entry must remain below prior high20: {signal['signal_id']}"
        )
    stock_is_visible = stock_path["trade_date"].gt(signal_date)
    concept_is_visible = concept_path["trade_date"].gt(signal_date)
    if outcome_end_exclusive is not None:
        stock_is_visible &= stock_path["trade_date"].lt(outcome_end_exclusive)
        concept_is_visible &= concept_path["trade_date"].lt(outcome_end_exclusive)
    after_signal = stock_path.loc[stock_is_visible].reset_index(drop=True)
    target = _first_row(after_signal.loc[after_signal["high_price"].gt(reference_high)])
    below_ma20 = after_signal["close_price"].lt(after_signal["ma20"]).fillna(False)
    second_below = below_ma20 & below_ma20.shift(1, fill_value=False)
    stock_defense = _first_row(after_signal.loc[second_below])
    concept_after = concept_path.loc[
        concept_is_visible & concept_path["concept_structure_known"].astype(bool)
    ]
    concept_break = _first_row(
        concept_after.loc[~concept_after["concept_structure_intact"].astype(bool)]
    )
    concept_execution = None
    if concept_break is not None:
        concept_execution = _first_row(
            after_signal.loc[
                after_signal["trade_date"].ge(concept_break["trade_date"])
            ]
        )
    exit_row, exit_reason = _choose_exit(
        target=target,
        stock_defense=stock_defense,
        concept_execution=concept_execution,
    )
    record = dict(signal)
    record.update(
        {
            "entry_date": signal_date,
            "entry_price": entry_price,
            "entry_execution_assumption": ENTRY_EXECUTION_ASSUMPTION,
            "entry_reference_high": reference_high,
            "higher_high_date": _row_date(target),
            "stock_defense_date": _row_date(stock_defense),
            "concept_break_date": _row_date(concept_break),
            "concept_execution_date": _row_date(concept_execution),
            "outcome_end_exclusive": (
                pd.NaT
                if outcome_end_exclusive is None
                else outcome_end_exclusive
            ),
            "exit_reason": (
                "split_boundary_censored"
                if exit_row is None and outcome_end_exclusive is not None
                else exit_reason
            ),
            **_structural_path_metrics(
                after_signal,
                entry_price=entry_price,
                exit_row=exit_row,
                round_trip_cost_pct=round_trip_cost_pct,
            ),
            "round_trip_cost_pct": round_trip_cost_pct,
        }
    )
    return record


def _selection_outcome_boundaries(
    features: pd.DataFrame,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the first unseen date after development and validation."""

    _require_columns(features, ("trade_date", "block"), "selection feature")
    dates = pd.to_datetime(features["trade_date"], errors="raise").dt.normalize()
    blocks = pd.to_numeric(features["block"], errors="raise")
    development_end = dates.loc[blocks.eq(4)].min()
    validation_end = dates.loc[blocks.eq(5)].min()
    if pd.isna(development_end) or pd.isna(validation_end):
        raise ValueError("selection features must include blocks 4 and 5")
    if development_end >= validation_end:
        raise ValueError("chronological block boundaries are not increasing")
    return pd.Timestamp(development_end), pd.Timestamp(validation_end)


def _normalize_outcome_boundary(value: object | None) -> pd.Timestamp | None:
    if value is None:
        return None
    boundary = pd.Timestamp(value)
    if pd.isna(boundary):
        raise ValueError("outcome boundary cannot be missing")
    if boundary.tzinfo is not None:
        boundary = boundary.tz_localize(None)
    return boundary.normalize()


def _choose_exit(
    *,
    target: pd.Series | None,
    stock_defense: pd.Series | None,
    concept_execution: pd.Series | None,
) -> tuple[pd.Series | None, str]:
    candidates = []
    if target is not None:
        candidates.append((pd.Timestamp(target["trade_date"]), 0, target, "higher_high_confirmed"))
    if stock_defense is not None:
        candidates.append((pd.Timestamp(stock_defense["trade_date"]), 1, stock_defense, "two_closes_below_ma20"))
    if concept_execution is not None:
        candidates.append((pd.Timestamp(concept_execution["trade_date"]), 2, concept_execution, "concept_structure_broken"))
    if not candidates:
        return None, "right_censored"
    _, _, row, reason = min(candidates, key=lambda item: (item[0], item[1]))
    return row, reason


def _structural_path_metrics(
    after_signal: pd.DataFrame,
    *,
    entry_price: float,
    exit_row: pd.Series | None,
    round_trip_cost_pct: float,
) -> dict[str, Any]:
    if exit_row is None:
        return {
            "exit_date": pd.NaT,
            "exit_price": None,
            "holding_sessions": None,
            "gross_return_pct": None,
            "net_return_pct": None,
            "maximum_adverse_excursion_pct": None,
            "maximum_favorable_excursion_pct": None,
        }
    exit_date = pd.Timestamp(exit_row["trade_date"])
    observed = after_signal.loc[after_signal["trade_date"].le(exit_date)]
    exit_price = float(exit_row["close_price"])
    gross_return = (exit_price / entry_price - 1.0) * 100.0
    holding_sessions = int(after_signal.index[after_signal["trade_date"].eq(exit_date)][0]) + 1
    return {
        "exit_date": exit_date,
        "exit_price": exit_price,
        "holding_sessions": holding_sessions,
        "gross_return_pct": gross_return,
        "net_return_pct": gross_return - round_trip_cost_pct,
        "maximum_adverse_excursion_pct": min(
            0.0,
            (float(observed["low_price"].min()) / entry_price - 1.0) * 100.0,
        ),
        "maximum_favorable_excursion_pct": max(
            0.0,
            (float(observed["high_price"].max()) / entry_price - 1.0) * 100.0,
        ),
    }


def _prepare_daily_bars(
    daily_bars: pd.DataFrame,
    *,
    identity_column: str,
    required_columns: Sequence[str],
) -> pd.DataFrame:
    _require_columns(daily_bars, required_columns, f"{identity_column} daily bar")
    frame = daily_bars.loc[:, list(required_columns)].copy()
    frame[identity_column] = frame[identity_column].astype(str)
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    numeric = ("open_price", "high_price", "low_price", "close_price")
    frame[list(numeric)] = frame[list(numeric)].apply(pd.to_numeric, errors="raise")
    if frame.duplicated([identity_column, "trade_date"]).any():
        raise ValueError(f"{identity_column} daily bar identities must be unique")
    if frame[list(numeric)].le(0).any().any():
        raise ValueError(f"{identity_column} daily prices must be positive")
    return frame.sort_values(
        [identity_column, "trade_date"], kind="stable"
    ).reset_index(drop=True)


def _selection_gates_pass(
    development: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> bool:
    return bool(
        int(development.get("closed_trades") or 0) >= 60
        and int(validation.get("closed_trades") or 0) >= 20
        and _finite_or_zero(development.get("positive_rate_pct")) > 50.0
        and _finite_or_zero(validation.get("positive_rate_pct")) > 50.0
        and _finite_or_zero(development.get("mean_return_pct")) > 0.0
        and _finite_or_zero(validation.get("mean_return_pct")) > 0.0
        and _finite_or_zero(development.get("profit_factor")) > 1.0
        and _finite_or_zero(validation.get("profit_factor")) > 1.0
    )


def _attach_d1_diagnostics(
    trades: pd.DataFrame,
    outcomes: pd.DataFrame,
) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    required = ("trade_date", "vt_symbol", "d1_net_return_pct")
    _require_columns(outcomes, required, "D+1 diagnostic outcome")
    right = outcomes.loc[:, list(required)].copy()
    right["trade_date"] = pd.to_datetime(
        right["trade_date"], errors="raise"
    ).dt.normalize()
    right = right.drop_duplicates(["trade_date", "vt_symbol"], keep="first")
    return trades.merge(
        right,
        on=["trade_date", "vt_symbol"],
        how="left",
        validate="one_to_one",
    )


def _d1_diagnostics(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty or "d1_net_return_pct" not in trades:
        return {
            "closed_d1_rows": 0,
            "d1_positive_rate_pct": None,
            "d1_mean_return_pct": None,
            "d1_non_positive_structural_positive": 0,
            "d1_positive_structural_non_positive": 0,
        }
    complete = trades.loc[
        trades["d1_net_return_pct"].notna() & trades["net_return_pct"].notna()
    ].copy()
    if complete.empty:
        return {
            "closed_d1_rows": 0,
            "d1_positive_rate_pct": None,
            "d1_mean_return_pct": None,
            "d1_non_positive_structural_positive": 0,
            "d1_positive_structural_non_positive": 0,
        }
    d1 = pd.to_numeric(complete["d1_net_return_pct"], errors="raise")
    structural = pd.to_numeric(complete["net_return_pct"], errors="raise")
    return {
        "closed_d1_rows": int(len(complete)),
        "d1_positive_rate_pct": float(d1.gt(0).mean() * 100.0),
        "d1_mean_return_pct": float(d1.mean()),
        "d1_non_positive_structural_positive": int((d1.le(0) & structural.gt(0)).sum()),
        "d1_positive_structural_non_positive": int((d1.gt(0) & structural.le(0)).sum()),
    }


def build_reference_cases(
    trades: pd.DataFrame,
    features: pd.DataFrame,
    rule: WeakToStrongRule,
    *,
    maximum_feature_block: int,
) -> pd.DataFrame:
    """Keep named structural trades plus one causal rejection for a missing name."""

    cases = (
        trades.loc[trades["vt_symbol"].isin(REFERENCE_SYMBOLS)].copy()
        if not trades.empty
        else pd.DataFrame()
    )
    if not cases.empty:
        cases["case_status"] = "structural_signal"
        cases["rejection_reason"] = None
    columns = [
        "trade_date",
        "block",
        "vt_symbol",
        "stock_name",
        "sector_id",
        "concept_name",
        "leader_rank",
        "pullback_opportunity_ordinal",
        "support_zone",
        "case_status",
        "rejection_reason",
        "entry_price",
        "entry_reference_high",
        "d1_net_return_pct",
        "higher_high_date",
        "stock_defense_date",
        "concept_break_date",
        "exit_date",
        "exit_reason",
        "holding_sessions",
        "net_return_pct",
        "maximum_adverse_excursion_pct",
        "maximum_favorable_excursion_pct",
    ]
    records = cases.loc[
        :, [column for column in columns if column in cases]
    ].to_dict("records")
    present_symbols = {str(record["vt_symbol"]) for record in records}
    missing_symbols = set(REFERENCE_SYMBOLS) - present_symbols
    if missing_symbols:
        _require_columns(
            features,
            (
                "trade_date",
                "block",
                "vt_symbol",
                "weak_to_strong_day",
                "pullback_block_reason",
                "leader_rank",
                "return60_pct",
            ),
            "reference feature",
        )
        candidates = features.loc[
            features["vt_symbol"].isin(missing_symbols)
            & pd.to_numeric(features["block"], errors="coerce").le(
                maximum_feature_block
            )
        ].copy()
        if not candidates.empty:
            candidates["_interesting"] = (
                candidates["weak_to_strong_day"].astype(bool)
                | candidates["pullback_block_reason"].notna()
            )
            candidates = (
                candidates.sort_values(
                    [
                        "vt_symbol",
                        "_interesting",
                        "leader_rank",
                        "return60_pct",
                        "trade_date",
                    ],
                    ascending=[True, False, True, False, False],
                    kind="stable",
                )
                .drop_duplicates("vt_symbol", keep="first")
            )
            for _, row in candidates.iterrows():
                records.append(
                    {
                        "trade_date": row["trade_date"],
                        "block": row["block"],
                        "vt_symbol": row["vt_symbol"],
                        "stock_name": row["stock_name"],
                        "sector_id": row["sector_id"],
                        "concept_name": row["concept_name"],
                        "leader_rank": row["leader_rank"],
                        "pullback_opportunity_ordinal": row[
                            "pullback_opportunity_ordinal"
                        ],
                        "support_zone": row["support_zone"],
                        "case_status": "rejected_reference_case",
                        "rejection_reason": _first_rejection_reason(row, rule),
                        "entry_price": None,
                        "entry_reference_high": row["prior_high20"],
                        "d1_net_return_pct": None,
                        "higher_high_date": pd.NaT,
                        "stock_defense_date": pd.NaT,
                        "concept_break_date": pd.NaT,
                        "exit_date": pd.NaT,
                        "exit_reason": "not_selected",
                        "holding_sessions": None,
                        "net_return_pct": None,
                        "maximum_adverse_excursion_pct": None,
                        "maximum_favorable_excursion_pct": None,
                    }
                )
    if not records:
        return pd.DataFrame()
    return pd.DataFrame.from_records(records).sort_values(
        ["trade_date", "vt_symbol"], kind="stable"
    ).reset_index(drop=True)


def _empty_metrics() -> dict[str, Any]:
    return {
        "entries": 0,
        "closed_trades": 0,
        "censored_trades": 0,
        "positive_rate_pct": None,
        "mean_return_pct": None,
        "median_return_pct": None,
        "profit_factor": None,
        "compound_return_pct": None,
        "maximum_drawdown_pct": None,
        "median_holding_sessions": None,
    }


def _prefix_metrics(prefix: str, metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {f"{prefix}_{key}": value for key, value in metrics.items()}


def _metric_row(frame: pd.DataFrame, segment: str) -> dict[str, Any]:
    if segment not in frame.index:
        return {}
    row = frame.loc[segment]
    if isinstance(row, pd.DataFrame):
        raise ValueError(f"duplicate structural metric segment: {segment}")
    return row.to_dict()


def _first_row(frame: pd.DataFrame) -> pd.Series | None:
    return None if frame.empty else frame.iloc[0]


def _row_date(row: pd.Series | None) -> pd.Timestamp | pd.NaT:
    return pd.NaT if row is None else pd.Timestamp(row["trade_date"])


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing columns: {missing}")


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return [_json_safe(row) for row in frame.to_dict("records")]


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if value is pd.NaT:
        return None
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if pd.isna(value) if not isinstance(value, (str, bytes, bool)) else False:
        return None
    return value


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _finite_or_zero(value: Any) -> float:
    return _finite_or(value, 0.0)


def _finite_or(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:.4f}" if math.isfinite(number) else "-"


def _percent(value: Any) -> str:
    number = _number(value)
    return "-" if number == "-" else f"{number}%"


def _date_text(value: Any) -> str:
    if value is None or value is pd.NaT:
        return "-"
    try:
        return pd.Timestamp(value).date().isoformat()
    except (TypeError, ValueError):
        return "-"


_STOCK_BARS_QUERY = r"""
WITH wanted AS (
    SELECT unnest(CAST(:symbols AS varchar[])) AS vt_symbol
)
SELECT
    b.vt_symbol, b.trade_date, b.open_price, b.high_price,
    b.low_price, b.close_price
FROM stock_daily_bars b
JOIN wanted w ON w.vt_symbol = b.vt_symbol
WHERE b.trade_date BETWEEN :start_date AND :end_date
ORDER BY b.vt_symbol, b.trade_date
"""


_CONCEPT_BARS_QUERY = r"""
WITH wanted AS (
    SELECT unnest(CAST(:sector_ids AS varchar[])) AS sector_id
)
SELECT
    b.sector_id, b.trade_date, b.open_price, b.high_price,
    b.low_price, b.close_price
FROM sector_daily_bars b
JOIN wanted w ON w.sector_id = b.sector_id
WHERE b.source = 'eastmoney.board_kline'
AND b.trade_date BETWEEN :start_date AND :end_date
ORDER BY b.sector_id, b.trade_date
"""
