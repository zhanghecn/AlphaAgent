"""Causal support-day close events and pre-registered rule selection."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd


RULE_EXACT_HOLD = "support_day_exact_hold"
RULE_EXACT_BULLISH = "support_day_exact_bullish_reversal"
RULE_BAND_RECLAIM = "support_day_ma5_then_ma10_band_reclaim"
RULE_IDS = (RULE_EXACT_HOLD, RULE_EXACT_BULLISH, RULE_BAND_RECLAIM)
ROUND_TRIP_COST_PCT = 0.2
DOUBLE_ROUND_TRIP_COST_PCT = 0.4
SUPPORT_TOLERANCE_PCT = 2.0
MIN_PULLBACK_PCT = 5.0
MIN_DEVELOPMENT_TRADES = 100
MIN_DEVELOPMENT_WIN_RATE_PCT = 60.0
MIN_DEVELOPMENT_PROFIT_FACTOR = 1.2
DEVELOPMENT_BLOCKS = frozenset({"block_1", "block_2", "block_3"})
LATE_BLOCKS = frozenset({"block_4", "block_5"})
SUPPORT_DEPTH = {"ma5": 1, "ma10": 2, "ma20": 3}
PROHIBITED_OUTCOME_TOKENS = (
    "future_",
    "outcome",
    "net_return",
    "gross_return",
    "exit_",
    "mfe",
    "mae",
    "profit",
    "d1_",
)


def build_support_day_events(
    leader_paths: pd.DataFrame,
    daily_ledger: pd.DataFrame,
    market_timing: pd.DataFrame,
) -> pd.DataFrame:
    """Build outcome-neutral events whose signal is the support-test close."""

    _reject_outcome_columns(leader_paths)
    _reject_outcome_columns(daily_ledger)
    path_columns = (
        "campaign_id",
        "sector_id",
        "concept_name",
        "vt_symbol",
        "stock_name",
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "daily_return_pct",
        "ma5",
        "ma10",
        "ma20",
        "previous_close",
        "volume_ratio_prior5",
        "close_location",
        "campaign_active",
        "dynamic_rank",
        "dynamic_top3",
        "structure_intact",
        "feature_cutoff_date",
    )
    ledger_columns = (
        "campaign_id",
        "vt_symbol",
        "trade_date",
        "state",
        "wave_number",
        "record_high_price",
        "record_high_date",
        "deepest_tested_support",
        "deepest_tested_depth",
        "required_support",
        "latest_support_test_date",
        "dynamic_top3",
        "structure_intact",
    )
    timing_columns = (
        "source_date",
        "active_direction",
        "danger_state",
        "market_phase",
    )
    _require_columns(leader_paths, path_columns, "leader path")
    _require_columns(daily_ledger, ledger_columns, "campaign daily ledger")
    _require_columns(market_timing, timing_columns, "market timing")

    paths = leader_paths.loc[:, list(path_columns)].copy()
    ledger = daily_ledger.loc[:, list(ledger_columns)].copy()
    paths["trade_date"] = _dates(paths["trade_date"])
    paths["feature_cutoff_date"] = _dates(paths["feature_cutoff_date"])
    ledger["trade_date"] = _dates(ledger["trade_date"])
    ledger["latest_support_test_date"] = _dates(
        ledger["latest_support_test_date"], allow_missing=True
    )
    if not paths["feature_cutoff_date"].eq(paths["trade_date"]).all():
        raise ValueError("leader path cutoff must equal its completed trade date")
    identity = ["campaign_id", "vt_symbol", "trade_date"]
    if paths.duplicated(identity).any() or ledger.duplicated(identity).any():
        raise ValueError("support-day source identities must be unique")

    support_today = (
        ledger["state"].astype(str).eq("pullback")
        & ledger["required_support"].astype(str).isin(("ma5", "ma10"))
        & ledger["latest_support_test_date"].eq(ledger["trade_date"])
        & ledger["dynamic_top3"].fillna(False).astype(bool)
        & ledger["structure_intact"].fillna(False).astype(bool)
    )
    state_columns = [
        column
        for column in ledger_columns
        if column not in {"dynamic_top3", "structure_intact"}
    ]
    events = ledger.loc[support_today, state_columns].merge(
        paths,
        on=identity,
        how="inner",
        validate="one_to_one",
        sort=False,
    )
    if events.empty:
        return _empty_events()

    events = _attach_market_timing(events, market_timing)
    numeric = (
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "daily_return_pct",
        "ma5",
        "ma10",
        "ma20",
        "previous_close",
        "volume_ratio_prior5",
        "close_location",
        "record_high_price",
        "deepest_tested_depth",
        "wave_number",
        "dynamic_rank",
    )
    events[list(numeric)] = events[list(numeric)].apply(
        pd.to_numeric, errors="coerce"
    )
    required_is_ma5 = events["required_support"].astype(str).eq("ma5")
    events["required_support_price"] = np.where(
        required_is_ma5, events["ma5"], events["ma10"]
    )
    events["required_support_depth"] = np.where(required_is_ma5, 1, 2)
    events["support_test_date"] = events["trade_date"]
    events["signal_date"] = events["trade_date"]
    events["feature_cutoff_date"] = events["trade_date"]
    events["peak_drawdown_low_pct"] = (
        events["low_price"] / events["record_high_price"] - 1.0
    ) * 100.0
    events["low_to_required_pct"] = (
        events["low_price"] / events["required_support_price"] - 1.0
    ) * 100.0
    events["close_to_required_pct"] = (
        events["close_price"] / events["required_support_price"] - 1.0
    ) * 100.0
    events["required_line_near"] = events["low_to_required_pct"].abs().le(
        SUPPORT_TOLERANCE_PCT
    )
    events["exact_depth_match"] = events["deepest_tested_depth"].eq(
        events["required_support_depth"]
    )
    events["required_support_held"] = events["close_price"].ge(
        events["required_support_price"]
    )
    later_wave = events["wave_number"].gt(1)
    events["ma5_ma10_band_test"] = (
        later_wave
        & events["low_price"].lt(events["ma5"])
        & events["low_price"].ge(
            events["ma10"] * (1.0 - SUPPORT_TOLERANCE_PCT / 100.0)
        )
    )
    events["ma5_reclaimed"] = events["close_price"].ge(events["ma5"])
    events["bullish_reversal"] = (
        events["close_price"].ge(events["open_price"])
        & events["close_location"].ge(0.5)
    )
    events["limit_up_style_close"] = events["daily_return_pct"].ge(9.5)
    events["signal_id"] = (
        "support-day-v5:"
        + events["campaign_id"].astype(str)
        + ":"
        + events["vt_symbol"].astype(str)
        + ":"
        + events["signal_date"].dt.strftime("%Y-%m-%d")
        + ":wave-"
        + events["wave_number"].astype("Int64").astype(str)
    )
    if events["signal_id"].duplicated().any():
        raise ValueError("support-day signal identities must be unique")
    eligible = (
        events["campaign_active"].fillna(False).astype(bool)
        & events["dynamic_top3"].fillna(False).astype(bool)
        & events["structure_intact"].fillna(False).astype(bool)
        & events["peak_drawdown_low_pct"].le(-MIN_PULLBACK_PCT)
    )
    return (
        events.loc[eligible]
        .sort_values(
            ["signal_date", "campaign_id", "dynamic_rank", "vt_symbol"],
            kind="stable",
        )
        .reset_index(drop=True)
    )


def apply_pre_registered_rules(events: pd.DataFrame) -> pd.DataFrame:
    """Apply the three frozen predicates without outcome or regime optimization."""

    _reject_outcome_columns(events)
    required = (
        "signal_id",
        "wave_number",
        "exact_depth_match",
        "required_line_near",
        "required_support_held",
        "bullish_reversal",
        "ma5_ma10_band_test",
        "ma5_reclaimed",
        "danger_state",
        "close_price",
        "ma20",
        "daily_return_pct",
        "campaign_active",
        "dynamic_top3",
        "structure_intact",
    )
    _require_columns(events, required, "support-day event")
    if events.empty:
        return events.assign(rule_id=pd.Series(dtype=str))

    common = _common_rule_mask(events)
    exact_hold = (
        common
        & events["exact_depth_match"].astype(bool)
        & events["required_line_near"].astype(bool)
        & events["required_support_held"].astype(bool)
    )
    first_wave = events["wave_number"].eq(1)
    later_band = (
        events["wave_number"].gt(1)
        & events["ma5_ma10_band_test"].astype(bool)
        & events["ma5_reclaimed"].astype(bool)
        & events["bullish_reversal"].astype(bool)
    )
    masks = {
        RULE_EXACT_HOLD: exact_hold,
        RULE_EXACT_BULLISH: exact_hold & events["bullish_reversal"].astype(bool),
        RULE_BAND_RECLAIM: common & ((first_wave & exact_hold) | later_band),
    }
    selected = [events.loc[mask].assign(rule_id=rule) for rule, mask in masks.items()]
    return (
        pd.concat(selected, ignore_index=True)
        .sort_values(
            ["signal_date", "rule_id", "dynamic_rank", "signal_id"],
            kind="stable",
        )
        .reset_index(drop=True)
    )


def filter_common_rule_universe(events: pd.DataFrame) -> pd.DataFrame:
    """Keep causal event dates that at least one registered rule may trade."""

    _reject_outcome_columns(events)
    required = (
        "campaign_active",
        "dynamic_top3",
        "structure_intact",
        "danger_state",
        "close_price",
        "ma20",
        "daily_return_pct",
    )
    _require_columns(events, required, "common support-day universe")
    return events.loc[_common_rule_mask(events)].reset_index(drop=True)


def assign_common_time_blocks(
    frame: pd.DataFrame,
    *,
    event_dates: Sequence[object],
) -> pd.DataFrame:
    """Assign one five-block calendar shared by every rule and environment."""

    _require_columns(frame, ("signal_date",), "time-block frame")
    result = frame.copy()
    result["signal_date"] = _dates(result["signal_date"])
    dates = sorted(pd.DatetimeIndex(pd.to_datetime(event_dates)).normalize().unique())
    if not dates:
        result["time_block"] = pd.Series(index=result.index, dtype=str)
        return result
    block_by_date = {
        pd.Timestamp(trade_date): f"block_{min(position * 5 // len(dates) + 1, 5)}"
        for position, trade_date in enumerate(dates)
    }
    result["time_block"] = result["signal_date"].map(block_by_date)
    if result["time_block"].isna().any():
        raise ValueError("rule signal date is outside the common event calendar")
    return result


def execute_d1_close_trades(
    selected_events: pd.DataFrame,
    leader_paths: pd.DataFrame,
    *,
    round_trip_cost_pct: float = ROUND_TRIP_COST_PCT,
) -> pd.DataFrame:
    """Buy the completed event close and sell the next symbol-session close."""

    if round_trip_cost_pct < 0:
        raise ValueError("round-trip cost cannot be negative")
    required = (
        "rule_id",
        "signal_id",
        "campaign_id",
        "vt_symbol",
        "signal_date",
        "close_price",
        "dynamic_rank",
    )
    _require_columns(selected_events, required, "selected support-day event")
    _require_columns(
        leader_paths,
        ("vt_symbol", "trade_date", "close_price"),
        "leader path close calendar",
    )
    if selected_events.empty:
        return pd.DataFrame()
    events = selected_events.copy()
    events["signal_date"] = _dates(events["signal_date"])
    events = (
        events.sort_values(
            ["rule_id", "signal_date", "dynamic_rank", "campaign_id", "signal_id"],
            kind="stable",
        )
        .drop_duplicates(["rule_id", "vt_symbol", "signal_date"], keep="first")
        .reset_index(drop=True)
    )
    bars = _canonical_symbol_closes(leader_paths)
    calendars = {
        str(symbol): group.reset_index(drop=True)
        for symbol, group in bars.groupby("vt_symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for event in events.to_dict("records"):
        symbol = str(event["vt_symbol"])
        calendar = calendars.get(symbol)
        if calendar is None:
            raise ValueError(f"missing close calendar for support event: {symbol}")
        signal_date = pd.Timestamp(event["signal_date"])
        positions = calendar.index[calendar["trade_date"].eq(signal_date)]
        if len(positions) != 1:
            raise ValueError("support event must match one symbol close")
        entry_price = float(event["close_price"])
        next_position = int(positions[0]) + 1
        trade = {
            **event,
            "entry_date": signal_date,
            "entry_price": entry_price,
            "round_trip_cost_pct": round_trip_cost_pct,
        }
        if next_position >= len(calendar):
            trade.update(
                {
                    "d1_date": pd.NaT,
                    "d1_close": None,
                    "d1_net_return_pct": None,
                    "exit_date": pd.NaT,
                    "exit_price": None,
                    "net_return_pct": None,
                }
            )
        else:
            d1 = calendar.iloc[next_position]
            d1_close = float(d1["close_price"])
            d1_net_return = _net_return(
                entry_price, d1_close, round_trip_cost_pct
            )
            trade.update(
                {
                    "d1_date": pd.Timestamp(d1["trade_date"]),
                    "d1_close": d1_close,
                    "d1_net_return_pct": d1_net_return,
                    "exit_date": pd.Timestamp(d1["trade_date"]),
                    "exit_price": d1_close,
                    "net_return_pct": d1_net_return,
                }
            )
        rows.append(trade)
    trades = pd.DataFrame.from_records(rows).sort_values(
        ["entry_date", "rule_id", "dynamic_rank", "signal_id"], kind="stable"
    )
    return _drop_overlapping_same_stock_trades(trades)


def reprice_d1_close_trades(
    trades: pd.DataFrame,
    *,
    round_trip_cost_pct: float,
) -> pd.DataFrame:
    """Apply a different fixed cost to an already executed D+1 ledger."""

    if round_trip_cost_pct < 0:
        raise ValueError("round-trip cost cannot be negative")
    if trades.empty:
        return trades.copy()
    required = (
        "entry_price",
        "d1_close",
        "d1_net_return_pct",
        "exit_date",
        "net_return_pct",
        "round_trip_cost_pct",
    )
    _require_columns(trades, required, "executed D+1 trade")
    result = trades.copy()
    result["round_trip_cost_pct"] = float(round_trip_cost_pct)
    entry_price = pd.to_numeric(result["entry_price"], errors="coerce")
    d1_close = pd.to_numeric(result["d1_close"], errors="coerce")
    closed = result["exit_date"].notna() & d1_close.notna()
    if (entry_price.loc[closed] <= 0).any() or entry_price.loc[closed].isna().any():
        raise ValueError("closed D+1 trades require a positive entry price")
    repriced = (d1_close / entry_price - 1.0) * 100.0 - round_trip_cost_pct
    result.loc[closed, "d1_net_return_pct"] = repriced.loc[closed]
    result.loc[closed, "net_return_pct"] = repriced.loc[closed]
    result.loc[~closed, ["d1_net_return_pct", "net_return_pct"]] = np.nan
    return result


def freeze_development_rule(
    trades: pd.DataFrame,
    double_cost_trades: pd.DataFrame,
    development_cash_results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Freeze one rule from blocks 1-3 without reading late-block outcomes."""

    required = ("rule_id", "time_block", "exit_date", "net_return_pct")
    _require_columns(trades, required, "development trade")
    _require_columns(double_cost_trades, required, "double-cost development trade")
    development = trades.loc[trades["time_block"].isin(DEVELOPMENT_BLOCKS)]
    development_double = double_cost_trades.loc[
        double_cost_trades["time_block"].isin(DEVELOPMENT_BLOCKS)
    ]
    candidates = []
    for rule_id in RULE_IDS:
        rule_trades = development.loc[development["rule_id"].eq(rule_id)]
        rule_double = development_double.loc[
            development_double["rule_id"].eq(rule_id)
        ]
        metrics = summarize_d1_trades(rule_trades)
        double_metrics = summarize_d1_trades(rule_double)
        stable_blocks = sum(
            _development_block_passed(
                rule_trades.loc[rule_trades["time_block"].eq(block)]
            )
            for block in sorted(DEVELOPMENT_BLOCKS)
        )
        compound = _finite_or_none(
            development_cash_results.get(rule_id, {}).get("compound_return_pct")
        )
        passed = bool(
            metrics["closed_trades"] >= MIN_DEVELOPMENT_TRADES
            and float(metrics["win_rate_pct"] or 0.0)
            > MIN_DEVELOPMENT_WIN_RATE_PCT
            and float(metrics["mean_net_return_pct"] or 0.0) > 0.0
            and float(metrics["profit_factor"] or 0.0)
            >= MIN_DEVELOPMENT_PROFIT_FACTOR
            and float(double_metrics["mean_net_return_pct"] or 0.0) > 0.0
            and stable_blocks >= 2
        )
        candidates.append(
            {
                "rule_id": rule_id,
                "development_closed_trades": metrics["closed_trades"],
                "development_win_rate_pct": metrics["win_rate_pct"],
                "development_mean_net_return_pct": metrics[
                    "mean_net_return_pct"
                ],
                "development_profit_factor": metrics["profit_factor"],
                "development_double_cost_mean_pct": double_metrics[
                    "mean_net_return_pct"
                ],
                "development_stable_blocks": stable_blocks,
                "development_cash_compound_pct": compound,
                "nomination_passed": passed,
            }
        )
    eligible = [row for row in candidates if row["nomination_passed"]]
    selected = (
        sorted(
            eligible,
            key=lambda row: (
                -(row["development_cash_compound_pct"] or -math.inf),
                -(row["development_profit_factor"] or -math.inf),
                row["rule_id"],
            ),
        )[0]["rule_id"]
        if eligible
        else None
    )
    return {"selected_rule": selected, "candidate_metrics": candidates}


def summarize_d1_trades(trades: pd.DataFrame) -> dict[str, Any]:
    """Summarize closed D+1 returns without treating censored rows as losses."""

    if trades.empty:
        return _empty_metrics()
    returns = pd.to_numeric(
        trades.loc[trades["exit_date"].notna(), "net_return_pct"], errors="coerce"
    ).dropna()
    if returns.empty:
        return _empty_metrics()
    wins = returns.loc[returns.gt(0.0)]
    losses = returns.loc[returns.lt(0.0)]
    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())
    equity = pd.concat(
        [pd.Series([1.0]), (1.0 + returns / 100.0).cumprod()], ignore_index=True
    )
    drawdown = equity / equity.cummax() - 1.0
    return {
        "closed_trades": int(len(returns)),
        "winning_trades": int(returns.gt(0.0).sum()),
        "win_rate_pct": float(returns.gt(0.0).mean() * 100.0),
        "mean_net_return_pct": float(returns.mean()),
        "median_net_return_pct": float(returns.median()),
        "profit_factor": (
            gross_profit / gross_loss
            if gross_loss > 0
            else math.inf
            if gross_profit > 0
            else None
        ),
        "compound_return_pct": float((equity.iat[-1] - 1.0) * 100.0),
        "maximum_drawdown_pct": float(drawdown.min() * 100.0),
    }


def _attach_market_timing(
    events: pd.DataFrame,
    market_timing: pd.DataFrame,
) -> pd.DataFrame:
    timing = market_timing.loc[
        :, ["source_date", "active_direction", "danger_state", "market_phase"]
    ].copy()
    timing["source_date"] = _dates(timing["source_date"])
    if timing["source_date"].duplicated().any():
        raise ValueError("market timing dates must be unique")
    timing = timing.rename(columns={"source_date": "trade_date"})
    result = events.merge(
        timing, on="trade_date", how="left", validate="many_to_one", sort=False
    )
    for column in ("active_direction", "danger_state", "market_phase"):
        result[column] = result[column].fillna("UNKNOWN").astype(str)
    result["market_timing_feature_cutoff_date"] = result["trade_date"]
    return result


def _canonical_symbol_closes(leader_paths: pd.DataFrame) -> pd.DataFrame:
    bars = leader_paths.loc[:, ["vt_symbol", "trade_date", "close_price"]].copy()
    bars["vt_symbol"] = bars["vt_symbol"].astype(str)
    bars["trade_date"] = _dates(bars["trade_date"])
    bars["close_price"] = pd.to_numeric(bars["close_price"], errors="raise")
    conflicts = bars.groupby(["vt_symbol", "trade_date"], sort=False)[
        "close_price"
    ].nunique()
    if conflicts.gt(1).any():
        raise ValueError("leader paths disagree on a symbol daily close")
    return (
        bars.drop_duplicates(["vt_symbol", "trade_date"], keep="first")
        .sort_values(["vt_symbol", "trade_date"], kind="stable")
        .reset_index(drop=True)
    )


def _common_rule_mask(events: pd.DataFrame) -> pd.Series:
    return (
        events["campaign_active"].astype(bool)
        & events["dynamic_top3"].astype(bool)
        & events["structure_intact"].astype(bool)
        & events["danger_state"].astype(str).eq("NORMAL")
        & events["close_price"].gt(events["ma20"])
        & events["daily_return_pct"].lt(9.5)
    )


def _drop_overlapping_same_stock_trades(trades: pd.DataFrame) -> pd.DataFrame:
    retained: list[int] = []
    identities = ["rule_id", "vt_symbol"]
    for _, group in trades.groupby(identities, sort=False):
        occupied_through: pd.Timestamp | None = None
        for index, trade in group.sort_values("entry_date", kind="stable").iterrows():
            entry_date = pd.Timestamp(trade["entry_date"])
            if occupied_through is not None and entry_date <= occupied_through:
                continue
            retained.append(index)
            occupied_through = (
                pd.Timestamp.max.normalize()
                if pd.isna(trade["exit_date"])
                else pd.Timestamp(trade["exit_date"])
            )
    return (
        trades.loc[retained]
        .sort_values(
            ["entry_date", "rule_id", "dynamic_rank", "signal_id"], kind="stable"
        )
        .reset_index(drop=True)
    )


def _development_block_passed(trades: pd.DataFrame) -> bool:
    metrics = summarize_d1_trades(trades)
    return bool(
        metrics["closed_trades"] > 0
        and float(metrics["win_rate_pct"] or 0.0) > MIN_DEVELOPMENT_WIN_RATE_PCT
        and float(metrics["mean_net_return_pct"] or 0.0) > 0.0
    )


def _net_return(entry_price: float, exit_price: float, cost_pct: float) -> float:
    return (exit_price / entry_price - 1.0) * 100.0 - cost_pct


def _empty_metrics() -> dict[str, Any]:
    return {
        "closed_trades": 0,
        "winning_trades": 0,
        "win_rate_pct": None,
        "mean_net_return_pct": None,
        "median_net_return_pct": None,
        "profit_factor": None,
        "compound_return_pct": None,
        "maximum_drawdown_pct": None,
    }


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "signal_id",
            "signal_date",
            "support_test_date",
            "feature_cutoff_date",
            "rule_id",
        ]
    ).drop(columns="rule_id")


def _reject_outcome_columns(frame: pd.DataFrame) -> None:
    prohibited = sorted(
        str(column)
        for column in frame
        if any(token in str(column).lower() for token in PROHIBITED_OUTCOME_TOKENS)
    )
    if prohibited:
        raise ValueError(f"outcome columns are prohibited: {prohibited}")


def _dates(values: pd.Series, *, allow_missing: bool = False) -> pd.Series:
    dates = pd.to_datetime(values, errors="coerce" if allow_missing else "raise")
    return dates.dt.normalize()


def _finite_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
