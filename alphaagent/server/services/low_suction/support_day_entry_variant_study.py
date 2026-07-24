"""Support-day entry variant study: enter at the pullback touch close, not the reclaim close.

现行策略在「分歧转强日」收盘入场（91% 贴近涨停、成交不保证）；
本变体在「回踩支撑当天」收盘入场（下跌日、流动性充裕），用 MA 跌破止损替代
转强确认过滤器，回答"真低吸是否优于确认后追涨"。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .causal_leader_pullback import ROUND_TRIP_COST_PCT, SUPPORT_DEPTH
from .leader_pullback_opportunity_funnel_study import build_support_touch_opportunities


STUDY_VERSION = "support-day-entry-variant-v1"
SUPPORT_DAY_ENTRY_VARIANT = "support_day_entry"
TRADABLE_PHASES = frozenset({"uptrend", "warming", "rotation"})

_SIGNAL_COLUMNS = (
    "signal_id",
    "campaign_id",
    "sector_id",
    "concept_name",
    "vt_symbol",
    "stock_name",
    "signal_date",
    "entry_price",
    "wave_number",
    "support_line",
    "support_depth",
    "support_price",
    "reference_peak_price",
    "dynamic_rank",
    "market_phase",
)


def build_support_day_entry_signals(
    opportunities: pd.DataFrame,
    market_timing: pd.DataFrame,
) -> pd.DataFrame:
    """Filter the full support-touch universe into causal touch-day entry signals."""

    required = (
        "opportunity_id",
        "campaign_id",
        "sector_id",
        "concept_name",
        "vt_symbol",
        "stock_name",
        "entry_date",
        "entry_price",
        "wave_number",
        "support_line",
        "ma5",
        "ma10",
        "prior_high20",
        "dynamic_rank",
    )
    _require_columns(opportunities, required, "support touch opportunity")
    _require_columns(
        market_timing,
        ("source_date", "active_direction", "danger_state", "market_phase"),
        "market timing context",
    )
    frame = opportunities.loc[:, list(required)].copy()
    frame["entry_date"] = pd.to_datetime(frame["entry_date"], errors="raise").dt.normalize()
    timing = market_timing.copy()
    timing["source_date"] = pd.to_datetime(timing["source_date"], errors="raise").dt.normalize()
    frame = frame.merge(
        timing.rename(columns={"source_date": "entry_date"}),
        on="entry_date",
        how="left",
        validate="many_to_one",
        sort=False,
    )
    selected = (
        frame["active_direction"].astype(str).eq("GOLD")
        & frame["danger_state"].astype(str).eq("NORMAL")
        & frame["market_phase"].astype(str).isin(TRADABLE_PHASES)
    )
    frame = frame.loc[selected].copy()
    frame["support_price"] = np.where(
        frame["support_line"].eq("ma5"), frame["ma5"], frame["ma10"]
    ).astype(float)
    frame["support_depth"] = frame["support_line"].map(SUPPORT_DEPTH).astype(int)
    frame = frame.loc[frame["support_price"].gt(0.0)]
    frame = frame.loc[pd.to_numeric(frame["prior_high20"], errors="coerce").gt(0.0)]
    frame = frame.rename(columns={"opportunity_id": "signal_id", "prior_high20": "reference_peak_price"})
    frame = frame.rename(columns={"entry_date": "signal_date"})
    result = frame.loc[:, list(_SIGNAL_COLUMNS)].sort_values(
        ["signal_date", "dynamic_rank", "signal_id"], kind="stable"
    )
    if result["signal_id"].duplicated().any():
        raise ValueError("support-day entry signal identities must be unique")
    return result.reset_index(drop=True)


def execute_support_day_entry_trades(
    signals: pd.DataFrame,
    campaign_paths: pd.DataFrame,
    *,
    round_trip_cost_pct: float = ROUND_TRIP_COST_PCT,
) -> pd.DataFrame:
    """Walk each signal forward: MA-break stop first, then the causal winner exits."""

    if signals.empty:
        return pd.DataFrame()
    path_required = (
        "campaign_id",
        "vt_symbol",
        "trade_date",
        "high_price",
        "low_price",
        "close_price",
        "campaign_active",
        "structure_intact",
    )
    _require_columns(signals, set(_SIGNAL_COLUMNS), "support-day entry signal")
    _require_columns(campaign_paths, path_required, "campaign path")
    paths = campaign_paths.loc[:, list(path_required)].copy()
    paths["trade_date"] = pd.to_datetime(paths["trade_date"], errors="raise").dt.normalize()
    paths = paths.sort_values(["campaign_id", "vt_symbol", "trade_date"], kind="stable")
    path_groups = paths.groupby(["campaign_id", "vt_symbol"], sort=False).indices

    rows: list[dict[str, Any]] = []
    for signal in signals.to_dict("records"):
        identity = (signal["campaign_id"], signal["vt_symbol"])
        positions = path_groups.get(identity)
        if positions is None:
            raise ValueError(f"signal identity has no campaign path: {identity!r}")
        path = paths.iloc[positions].reset_index(drop=True)
        rows.append(_execute_support_day_signal(signal, path, round_trip_cost_pct))
    return (
        pd.DataFrame.from_records(rows)
        .sort_values(["entry_date", "signal_id"], kind="stable")
        .reset_index(drop=True)
    )


def _execute_support_day_signal(
    signal: Mapping[str, Any],
    path: pd.DataFrame,
    round_trip_cost_pct: float,
) -> dict[str, Any]:
    entry_date = pd.Timestamp(signal["signal_date"])
    entry_positions = path.index[path["trade_date"].eq(entry_date)]
    if len(entry_positions) == 0:
        raise ValueError(f"signal date has no campaign bar: {entry_date}")
    entry_position = int(entry_positions[0])
    entry_price = float(signal["entry_price"])
    support_price = float(signal["support_price"])
    reference_peak = float(signal["reference_peak_price"])

    d1_position = entry_position + 1
    d1 = path.iloc[d1_position] if d1_position < len(path) else None
    d1_net_return_pct = (
        _net_return(entry_price, float(d1["close_price"]), round_trip_cost_pct)
        if d1 is not None
        else None
    )

    exit_row: pd.Series | None = None
    exit_reason = "right_censored"
    for position in range(entry_position + 1, len(path)):
        bar = path.iloc[position]
        # 止损优先于同 bar 止盈:收盘跌破支撑线先走,不赌回抽
        if float(bar["close_price"]) < support_price:
            exit_row, exit_reason = bar, "support_broken"
            break
        if float(bar["high_price"]) > reference_peak:
            exit_row, exit_reason = bar, "higher_high_confirmed"
            break
        if not bool(bar["structure_intact"]):
            exit_row, exit_reason = bar, "structural_break"
            break
        if not bool(bar["campaign_active"]):
            exit_row, exit_reason = bar, "concept_campaign_ended"
            break

    if exit_row is None:
        exit_date: pd.Timestamp = pd.NaT
        exit_price: float | None = None
        net_return_pct: float | None = None
        holding_sessions: int | None = None
        observed = path.iloc[entry_position:]
    else:
        exit_date = pd.Timestamp(exit_row["trade_date"])
        exit_price = float(exit_row["close_price"])
        net_return_pct = _net_return(entry_price, exit_price, round_trip_cost_pct)
        exit_position = int(path.index[path["trade_date"].eq(exit_date)][0])
        holding_sessions = exit_position - entry_position
        observed = path.iloc[entry_position : exit_position + 1]

    return {
        "signal_id": str(signal["signal_id"]),
        "campaign_id": str(signal["campaign_id"]),
        "sector_id": str(signal["sector_id"]),
        "concept_name": str(signal["concept_name"]),
        "vt_symbol": str(signal["vt_symbol"]),
        "stock_name": str(signal["stock_name"]),
        "wave_number": int(signal["wave_number"]),
        "support_line": str(signal["support_line"]),
        "support_depth": int(signal["support_depth"]),
        "support_test_date": entry_date,
        "support_price": support_price,
        "reference_peak_price": reference_peak,
        "dynamic_rank": int(signal["dynamic_rank"]),
        "market_phase": str(signal["market_phase"]),
        "variant": SUPPORT_DAY_ENTRY_VARIANT,
        "entry_date": entry_date,
        "entry_price": entry_price,
        "d1_date": pd.Timestamp(d1["trade_date"]) if d1 is not None else None,
        "d1_close": float(d1["close_price"]) if d1 is not None else None,
        "d1_net_return_pct": d1_net_return_pct,
        "exit_date": exit_date,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "holding_sessions": holding_sessions,
        "net_return_pct": net_return_pct,
        "mfe_pct": float((observed["high_price"].max() / entry_price - 1.0) * 100.0),
        "mae_pct": float((observed["low_price"].min() / entry_price - 1.0) * 100.0),
        "round_trip_cost_pct": round_trip_cost_pct,
    }


def run_support_day_entry_variant_study(
    *,
    start: date = date(2024, 8, 1),
    end: date | None = None,
) -> dict[str, Any]:
    """Run the touch-day variant and the official reclaim-day rule on identical inputs."""

    from .causal_leader_pullback import (
        execute_prepared_close_trades,
        select_three_phase_adaptive_signals,
        summarize_trade_metrics,
    )
    from .causal_leader_pullback_study import (
        build_causal_stock_features,
        build_concept_campaign_ledger,
        build_dynamic_leader_paths,
        load_causal_leader_pullback_inputs,
        prepare_dynamic_leader_paths,
        select_non_overlapping_trades,
        simulate_four_slot_cash,
    )
    from .cross_regime_validation import (
        DEVELOPMENT_BLOCKS,
        VALIDATION_BLOCKS,
        _return_metrics,
        _wilson_lower_bound,
    )

    inputs = load_causal_leader_pullback_inputs()
    features = build_causal_stock_features(inputs.stock_bars)
    _, campaign_paths = build_concept_campaign_ledger(inputs.concept_bars)
    leader_paths, coverage = build_dynamic_leader_paths(
        campaign_paths, inputs.memberships, features
    )
    prepared = prepare_dynamic_leader_paths(leader_paths, inputs.market_timing)
    paths = prepared.campaigns.paths

    # 变体:回踩日入场
    opportunities = build_support_touch_opportunities(
        prepared.campaigns.daily_ledger, leader_paths, features
    )
    end_date = pd.Timestamp(end or opportunities["entry_date"].max()).normalize()
    opportunities = opportunities.loc[
        opportunities["entry_date"].between(pd.Timestamp(start), end_date)
    ].reset_index(drop=True)
    if "prior_high20" not in opportunities.columns:
        peak_lookup = leader_paths.loc[:, ["campaign_id", "vt_symbol", "trade_date", "prior_high20"]].copy()
        peak_lookup["trade_date"] = pd.to_datetime(peak_lookup["trade_date"], errors="raise").dt.normalize()
        opportunities = opportunities.merge(
            peak_lookup.rename(columns={"trade_date": "entry_date"}),
            on=["campaign_id", "vt_symbol", "entry_date"],
            how="left",
            validate="one_to_one",
            sort=False,
        )
    variant_signals = build_support_day_entry_signals(opportunities, inputs.market_timing)
    variant_trades = execute_support_day_entry_trades(variant_signals, paths)
    variant_selected = select_non_overlapping_trades(variant_trades)
    # 预登记因果切分(非参数调优):入场日收盘是否守在支撑线上 + 第一波 vs 后续波段
    variant_selected = variant_selected.assign(
        touch_close_holds_support=variant_selected["entry_price"]
        >= variant_selected["support_price"],
        first_wave=variant_selected["wave_number"] == 1,
    )

    # 对照:现行转强日入场(同一 pipeline 同一输入)
    official_signals = select_three_phase_adaptive_signals(prepared.signals)
    official_trades = execute_prepared_close_trades(official_signals, prepared.campaigns).assign(
        variant="three_phase_adaptive"
    )
    official_selected = select_non_overlapping_trades(official_trades)
    phase_lookup = prepared.signals.loc[:, ["signal_id", "market_phase"]].drop_duplicates("signal_id")
    official_selected = official_selected.merge(phase_lookup, on="signal_id", how="left")

    report: dict[str, Any] = {
        "study_version": STUDY_VERSION,
        "period": {"start": str(start), "end": end_date.date().isoformat()},
        "coverage": coverage,
        "parent_opportunities": int(len(opportunities)),
        "variant": _variant_report(
            variant_signals, variant_selected, inputs.stock_bars,
            development_blocks=DEVELOPMENT_BLOCKS, validation_blocks=VALIDATION_BLOCKS,
            return_metrics=_return_metrics, wilson=_wilson_lower_bound,
        ),
        "official": _variant_report(
            official_signals, official_selected, inputs.stock_bars,
            development_blocks=DEVELOPMENT_BLOCKS, validation_blocks=VALIDATION_BLOCKS,
            return_metrics=_return_metrics, wilson=_wilson_lower_bound,
        ),
        "exit_reason_breakdown": {
            "variant": variant_selected["exit_reason"].value_counts().sort_index().to_dict(),
            "official": official_selected["exit_reason"].value_counts().sort_index().to_dict(),
        },
        "pre_registered_cuts": {
            "touch_close_holds_support": _cut_report(variant_selected, "touch_close_holds_support", return_metrics=_return_metrics),
            "first_wave": _cut_report(variant_selected, "first_wave", return_metrics=_return_metrics),
        },
        "boundaries": [
            "Current concept memberships are replayed backward and create survivorship bias.",
            "Touch-day entries use the same completed-close proxy; touch days are down days "
            "with normal liquidity so the fill assumption is far less strained than reclaim days.",
            "Variant thresholds reuse the frozen official ones (MA5/MA10, GOLD/NORMAL, phase "
            "gates); no parameter was tuned on this history.",
        ],
    }
    report["variant"]["quality"] = summarize_trade_metrics(variant_selected)
    report["official"]["quality"] = summarize_trade_metrics(official_selected)
    return report


def _variant_report(
    signals: pd.DataFrame,
    selected: pd.DataFrame,
    stock_bars: pd.DataFrame,
    *,
    development_blocks: tuple[str, ...],
    validation_blocks: tuple[str, ...],
    return_metrics: Any,
    wilson: Any,
) -> dict[str, Any]:
    from .causal_leader_pullback_study import simulate_four_slot_cash

    closed = selected.loc[selected["exit_date"].notna()].copy()
    rows = closed.to_dict("records")
    development = [row for row in rows if row.get("time_block") in development_blocks]
    validation = [row for row in rows if row.get("time_block") in validation_blocks]
    full = return_metrics(rows)
    dev = return_metrics(development)
    val = return_metrics(validation)
    phases = {}
    for phase in ("uptrend", "warming", "rotation"):
        phase_rows = [row for row in rows if row.get("market_phase") == phase]
        phases[phase] = return_metrics(phase_rows)
    return {
        "signals": int(len(signals)),
        "trades": int(len(closed)),
        "win_rate_pct": full["win_rate_pct"],
        "mean_net_return_pct": full["mean_net_return_pct"],
        "profit_factor": full["profit_factor"],
        "wilson_95_lower_pct": wilson(full["winning_trades"], full["closed_trades"]),
        "development": {"trades": dev["closed_trades"], "win_rate_pct": dev["win_rate_pct"], "mean_net_return_pct": dev["mean_net_return_pct"]},
        "validation": {"trades": val["closed_trades"], "win_rate_pct": val["win_rate_pct"], "mean_net_return_pct": val["mean_net_return_pct"]},
        "market_phases": phases,
        "two_slot_cash": simulate_four_slot_cash(selected, stock_bars, capacity=2),
    }


def _cut_report(selected: pd.DataFrame, flag: str, *, return_metrics: Any) -> dict[str, Any]:
    closed = selected.loc[selected["exit_date"].notna()]
    result: dict[str, Any] = {}
    for value, label in ((True, "yes"), (False, "no")):
        rows = closed.loc[closed[flag].eq(value)].to_dict("records")
        metrics = return_metrics(rows)
        result[label] = {
            "trades": metrics["closed_trades"],
            "win_rate_pct": metrics["win_rate_pct"],
            "mean_net_return_pct": metrics["mean_net_return_pct"],
            "profit_factor": metrics["profit_factor"],
        }
    return result


def _net_return(entry_price: float, exit_price: float, cost_pct: float) -> float:
    return round((exit_price / entry_price - 1.0) * 100.0 - cost_pct, 4)


def _require_columns(frame: pd.DataFrame, required: set[str] | tuple[str, ...], label: str) -> None:
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"{label} missing columns: {sorted(missing)}")
