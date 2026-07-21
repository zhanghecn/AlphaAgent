"""First weak-to-strong close after an exact causal support test."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from .support_day_entry import (
    DEVELOPMENT_BLOCKS,
    PROHIBITED_OUTCOME_TOKENS,
    RULE_EXACT_HOLD,
    summarize_d1_trades,
)


RULE_ID = "support_reclaim_first_weak_to_strong"
NON_LIMIT_RETURN_CEILING_PCT = 8.0
MIN_DEVELOPMENT_TRADES = 100
MIN_WIN_RATE_PCT = 60.0
MIN_PROFIT_FACTOR = 1.2
BLOCK_NAMES = tuple(f"block_{number}" for number in range(1, 6))

_EVENT_COLUMNS = (
    "rule_id",
    "signal_id",
    "support_signal_id",
    "campaign_id",
    "sector_id",
    "concept_name",
    "vt_symbol",
    "stock_name",
    "signal_date",
    "feature_cutoff_date",
    "entry_date",
    "entry_price",
    "close_price",
    "open_price",
    "high_price",
    "low_price",
    "previous_close",
    "daily_return_pct",
    "volume_ratio_prior5",
    "close_location",
    "dynamic_rank",
    "dynamic_top3",
    "wave_number",
    "required_support",
    "required_support_depth",
    "support_price",
    "support_test_date",
    "support_day_high",
    "support_day_close",
    "support_dynamic_rank",
    "confirmation_delay_sessions",
    "record_high_price",
    "peak_gap_pct",
    "active_direction",
    "danger_state",
    "market_phase",
    "market_timing_source_date",
    "market_timing_feature_cutoff_date",
)


def build_support_reclaim_confirmations(
    exact_support_events: pd.DataFrame,
    leader_paths: pd.DataFrame,
    daily_ledger: pd.DataFrame,
    market_timing: pd.DataFrame,
) -> pd.DataFrame:
    """Emit the first non-limit reclaim close after each valid support anchor."""

    anchors = _prepare_exact_anchors(exact_support_events)
    daily = _prepare_daily_path(leader_paths, daily_ledger)
    if anchors.empty or daily.empty:
        return _empty_events()

    daily_identities = pd.MultiIndex.from_frame(
        daily.loc[:, ["campaign_id", "vt_symbol", "trade_date"]]
    )
    anchor_identities = pd.MultiIndex.from_frame(
        anchors.loc[:, ["campaign_id", "vt_symbol", "signal_date"]].rename(
            columns={"signal_date": "trade_date"}
        )
    )
    if not anchor_identities.isin(daily_identities).all():
        raise ValueError("exact support anchor is absent from its campaign path")

    anchor_lookup = {
        (str(row["campaign_id"]), str(row["vt_symbol"]), row["signal_date"]): row
        for row in anchors.to_dict("records")
    }
    rows: list[dict[str, Any]] = []
    for identity, group in daily.groupby(["campaign_id", "vt_symbol"], sort=False):
        rows.extend(_confirmation_records(identity, group, anchor_lookup))
    events = pd.DataFrame.from_records(rows, columns=_EVENT_COLUMNS[:-5])
    return _attach_market_timing(events, market_timing)


def freeze_common_block_boundaries(
    event_dates: Sequence[object],
) -> dict[str, pd.Timestamp]:
    """Freeze the five V5 date endpoints before observing V7 confirmations."""

    dates = sorted(pd.DatetimeIndex(pd.to_datetime(event_dates)).normalize().unique())
    if not dates:
        raise ValueError("common event calendar cannot be empty")
    count = len(dates)
    return {
        block: pd.Timestamp(dates[math.ceil(number * count / 5) - 1])
        for number, block in enumerate(BLOCK_NAMES, start=1)
    }


def assign_frozen_time_blocks(
    frame: pd.DataFrame,
    boundaries: Mapping[str, object],
) -> pd.DataFrame:
    """Assign dates to pre-frozen V5 intervals without re-cutting V7 rows."""

    _require_columns(frame, ("signal_date",), "confirmation block frame")
    endpoints = _normalized_boundaries(boundaries)
    result = frame.copy()
    result["signal_date"] = _dates(result["signal_date"])
    result["time_block"] = result["signal_date"].map(
        lambda value: next(
            (
                block
                for block, endpoint in endpoints.items()
                if value <= endpoint
            ),
            "block_5",
        )
    )
    return result


def freeze_development_confirmation_rule(
    trades: pd.DataFrame,
    double_cost_trades: pd.DataFrame,
    development_cash_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Nominate the sole V7 rule using blocks 1-3 only."""

    required = ("rule_id", "signal_id", "time_block", "exit_date", "net_return_pct")
    _require_columns(trades, required, "confirmation trade")
    _require_columns(double_cost_trades, required, "double-cost confirmation trade")
    development = trades.loc[trades["time_block"].isin(DEVELOPMENT_BLOCKS)]
    development_double = double_cost_trades.loc[
        double_cost_trades["time_block"].isin(DEVELOPMENT_BLOCKS)
    ]
    if set(development["signal_id"].astype(str)) != set(
        development_double["signal_id"].astype(str)
    ):
        raise ValueError("development cost ledgers must contain identical signals")
    if not development["rule_id"].astype(str).eq(RULE_ID).all():
        raise ValueError("V7 development ledger contains an unsupported rule")

    metrics = summarize_d1_trades(development)
    double_metrics = summarize_d1_trades(development_double)
    stable_blocks = sum(
        _positive_block(development.loc[development["time_block"].eq(block)])
        for block in sorted(DEVELOPMENT_BLOCKS)
    )
    cash_compound = _finite_or_none(
        development_cash_result.get("compound_return_pct")
    )
    failed = _development_failures(
        metrics,
        double_metrics=double_metrics,
        stable_blocks=stable_blocks,
        cash_compound=cash_compound,
    )
    return {
        "selected_rule": RULE_ID if not failed else None,
        "development_metrics": metrics,
        "development_double_cost_metrics": double_metrics,
        "development_stable_blocks": stable_blocks,
        "development_cash_compound_pct": cash_compound,
        "nomination_passed": not failed,
        "failed_gates": failed,
    }


def _prepare_exact_anchors(frame: pd.DataFrame) -> pd.DataFrame:
    _reject_outcome_columns(frame, "exact support anchor")
    required = (
        "rule_id",
        "signal_id",
        "campaign_id",
        "sector_id",
        "concept_name",
        "vt_symbol",
        "stock_name",
        "signal_date",
        "support_test_date",
        "feature_cutoff_date",
        "high_price",
        "close_price",
        "required_support",
        "required_support_depth",
        "required_support_price",
        "wave_number",
        "record_high_price",
        "dynamic_rank",
    )
    _require_columns(frame, required, "exact support anchor")
    anchors = frame.loc[frame["rule_id"].astype(str).eq(RULE_EXACT_HOLD)].copy()
    for column in ("signal_date", "support_test_date", "feature_cutoff_date"):
        anchors[column] = _dates(anchors[column])
    if not anchors["signal_date"].equals(anchors["support_test_date"]):
        raise ValueError("exact support anchor must occur on its support-test date")
    if not anchors["signal_date"].equals(anchors["feature_cutoff_date"]):
        raise ValueError("exact support anchor cutoff must equal its signal date")
    identity = ["campaign_id", "vt_symbol", "signal_date"]
    if anchors.duplicated(identity).any():
        raise ValueError("exact support anchor identities must be unique")
    return anchors.sort_values([*identity, "signal_id"], kind="stable").reset_index(
        drop=True
    )


def _prepare_daily_path(
    leader_paths: pd.DataFrame,
    daily_ledger: pd.DataFrame,
) -> pd.DataFrame:
    _reject_outcome_columns(leader_paths, "leader path")
    _reject_outcome_columns(daily_ledger, "campaign daily ledger")
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
        "previous_close",
        "daily_return_pct",
        "ma5",
        "ma10",
        "ma20",
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
        "deepest_tested_depth",
        "required_support",
        "latest_support_test_date",
    )
    _require_columns(leader_paths, path_columns, "leader path")
    _require_columns(daily_ledger, ledger_columns, "campaign daily ledger")
    paths = leader_paths.loc[:, list(path_columns)].copy()
    ledger = daily_ledger.loc[:, list(ledger_columns)].copy()
    paths["trade_date"] = _dates(paths["trade_date"])
    paths["feature_cutoff_date"] = _dates(paths["feature_cutoff_date"])
    ledger["trade_date"] = _dates(ledger["trade_date"])
    ledger["latest_support_test_date"] = _dates(
        ledger["latest_support_test_date"], allow_missing=True
    )
    if not paths["feature_cutoff_date"].equals(paths["trade_date"]):
        raise ValueError("leader path cutoff must equal its completed trade date")
    identity = ["campaign_id", "vt_symbol", "trade_date"]
    if paths.duplicated(identity).any() or ledger.duplicated(identity).any():
        raise ValueError("confirmation path identities must be unique")
    daily = paths.merge(
        ledger,
        on=identity,
        how="inner",
        validate="one_to_one",
        sort=False,
    )
    numeric = (
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "previous_close",
        "daily_return_pct",
        "volume_ratio_prior5",
        "close_location",
        "dynamic_rank",
        "wave_number",
        "record_high_price",
        "deepest_tested_depth",
    )
    daily[list(numeric)] = daily[list(numeric)].apply(pd.to_numeric, errors="coerce")
    return daily.sort_values(
        ["campaign_id", "vt_symbol", "trade_date"], kind="stable"
    ).reset_index(drop=True)


def _confirmation_records(
    identity: tuple[object, object],
    group: pd.DataFrame,
    anchor_lookup: Mapping[tuple[str, str, pd.Timestamp], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    campaign_id, vt_symbol = map(str, identity)
    active_anchor: Mapping[str, Any] | None = None
    anchor_position: int | None = None
    completed_waves: set[int] = set()
    records: list[dict[str, Any]] = []
    ordered = group.reset_index(drop=True)
    for position, bar in ordered.iterrows():
        trade_date = pd.Timestamp(bar["trade_date"])
        anchor = anchor_lookup.get((campaign_id, vt_symbol, trade_date))
        if anchor is not None:
            active_anchor = anchor
            anchor_position = position
            continue
        if active_anchor is None or anchor_position is None:
            continue
        wave_number = int(active_anchor["wave_number"])
        if wave_number in completed_waves:
            continue
        if _anchor_invalid(bar, active_anchor):
            active_anchor = None
            anchor_position = None
            continue
        if not _weak_to_strong_confirmed(bar, active_anchor):
            continue
        records.append(
            _confirmation_event(
                bar,
                active_anchor,
                confirmation_delay_sessions=position - anchor_position,
            )
        )
        completed_waves.add(wave_number)
        active_anchor = None
        anchor_position = None
    return records


def _anchor_invalid(bar: pd.Series, anchor: Mapping[str, Any]) -> bool:
    return bool(
        int(bar["wave_number"]) != int(anchor["wave_number"])
        or str(bar["state"]) != "pullback"
        or not bool(bar["campaign_active"])
        or not bool(bar["dynamic_top3"])
        or not bool(bar["structure_intact"])
        or int(bar["deepest_tested_depth"])
        != int(anchor["required_support_depth"])
        or str(bar["required_support"]) != str(anchor["required_support"])
    )


def _weak_to_strong_confirmed(
    bar: pd.Series,
    anchor: Mapping[str, Any],
) -> bool:
    return bool(
        float(bar["close_price"]) > float(anchor["high_price"])
        and float(bar["close_price"]) > float(bar["previous_close"])
        and float(bar["close_price"]) < float(bar["record_high_price"])
        and float(bar["daily_return_pct"]) < NON_LIMIT_RETURN_CEILING_PCT
    )


def _confirmation_event(
    bar: pd.Series,
    anchor: Mapping[str, Any],
    *,
    confirmation_delay_sessions: int,
) -> dict[str, Any]:
    signal_date = pd.Timestamp(bar["trade_date"])
    close_price = float(bar["close_price"])
    record_high = float(bar["record_high_price"])
    return {
        "rule_id": RULE_ID,
        "signal_id": (
            f"support-reclaim-v7:{bar['campaign_id']}:{bar['vt_symbol']}:"
            f"{signal_date.date().isoformat()}:wave-{int(bar['wave_number'])}"
        ),
        "support_signal_id": str(anchor["signal_id"]),
        "campaign_id": str(bar["campaign_id"]),
        "sector_id": str(bar["sector_id"]),
        "concept_name": str(bar["concept_name"]),
        "vt_symbol": str(bar["vt_symbol"]),
        "stock_name": str(bar["stock_name"]),
        "signal_date": signal_date,
        "feature_cutoff_date": signal_date,
        "entry_date": signal_date,
        "entry_price": close_price,
        "close_price": close_price,
        "open_price": float(bar["open_price"]),
        "high_price": float(bar["high_price"]),
        "low_price": float(bar["low_price"]),
        "previous_close": float(bar["previous_close"]),
        "daily_return_pct": float(bar["daily_return_pct"]),
        "volume_ratio_prior5": _finite_or_none(bar["volume_ratio_prior5"]),
        "close_location": _finite_or_none(bar["close_location"]),
        "dynamic_rank": int(bar["dynamic_rank"]),
        "dynamic_top3": True,
        "wave_number": int(bar["wave_number"]),
        "required_support": str(anchor["required_support"]),
        "required_support_depth": int(anchor["required_support_depth"]),
        "support_price": float(anchor["required_support_price"]),
        "support_test_date": pd.Timestamp(anchor["signal_date"]),
        "support_day_high": float(anchor["high_price"]),
        "support_day_close": float(anchor["close_price"]),
        "support_dynamic_rank": int(anchor["dynamic_rank"]),
        "confirmation_delay_sessions": int(confirmation_delay_sessions),
        "record_high_price": record_high,
        "peak_gap_pct": float((close_price / record_high - 1.0) * 100.0),
    }


def _attach_market_timing(
    events: pd.DataFrame,
    market_timing: pd.DataFrame,
) -> pd.DataFrame:
    timing_columns = (
        "source_date",
        "active_direction",
        "danger_state",
        "market_phase",
    )
    _require_columns(market_timing, timing_columns, "market timing")
    timing = market_timing.loc[:, list(timing_columns)].copy()
    timing["source_date"] = _dates(timing["source_date"])
    if timing["source_date"].duplicated().any():
        raise ValueError("market timing dates must be unique")
    timing["market_timing_source_date"] = timing["source_date"]
    timing = timing.rename(columns={"source_date": "signal_date"})
    if events.empty:
        return _empty_events()
    result = events.merge(
        timing,
        on="signal_date",
        how="left",
        validate="many_to_one",
        sort=False,
    )
    for column in timing_columns[1:]:
        result[column] = result[column].fillna("UNKNOWN").astype(str)
    result["market_timing_feature_cutoff_date"] = result["signal_date"]
    return result.loc[:, list(_EVENT_COLUMNS)].sort_values(
        ["signal_date", "campaign_id", "dynamic_rank", "vt_symbol"],
        kind="stable",
    ).reset_index(drop=True)


def _normalized_boundaries(
    boundaries: Mapping[str, object],
) -> dict[str, pd.Timestamp]:
    if set(boundaries) != set(BLOCK_NAMES):
        raise ValueError("frozen block boundaries must contain block_1 through block_5")
    normalized = {
        block: pd.Timestamp(boundaries[block]).normalize() for block in BLOCK_NAMES
    }
    if list(normalized.values()) != sorted(normalized.values()):
        raise ValueError("frozen block boundaries must be chronological")
    return normalized


def _development_failures(
    metrics: Mapping[str, Any],
    *,
    double_metrics: Mapping[str, Any],
    stable_blocks: int,
    cash_compound: float | None,
) -> list[str]:
    failed = []
    if int(metrics["closed_trades"]) < MIN_DEVELOPMENT_TRADES:
        failed.append("development_closed_trades<100")
    if float(metrics["win_rate_pct"] or 0.0) <= MIN_WIN_RATE_PCT:
        failed.append("development_win_rate<=60pct")
    if float(metrics["mean_net_return_pct"] or 0.0) <= 0.0:
        failed.append("development_mean_return<=0")
    if float(metrics["profit_factor"] or 0.0) < MIN_PROFIT_FACTOR:
        failed.append("development_profit_factor<1.2")
    if float(double_metrics["mean_net_return_pct"] or 0.0) <= 0.0:
        failed.append("development_double_cost_mean<=0")
    if stable_blocks < 2:
        failed.append("development_stable_blocks<2")
    if cash_compound is None or cash_compound <= 0.0:
        failed.append("development_cash_compound<=0")
    return failed


def _positive_block(trades: pd.DataFrame) -> bool:
    metrics = summarize_d1_trades(trades)
    return bool(
        int(metrics["closed_trades"]) > 0
        and float(metrics["win_rate_pct"] or 0.0) > MIN_WIN_RATE_PCT
        and float(metrics["mean_net_return_pct"] or 0.0) > 0.0
    )


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(columns=_EVENT_COLUMNS)


def _reject_outcome_columns(frame: pd.DataFrame, label: str) -> None:
    prohibited = sorted(
        str(column)
        for column in frame
        if any(token in str(column).lower() for token in PROHIBITED_OUTCOME_TOKENS)
    )
    if prohibited:
        raise ValueError(f"{label} contains outcome columns: {prohibited}")


def _dates(values: pd.Series, *, allow_missing: bool = False) -> pd.Series:
    result = pd.to_datetime(values, errors="coerce" if allow_missing else "raise")
    return result.dt.normalize()


def _finite_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _require_columns(
    frame: pd.DataFrame,
    required: Sequence[str],
    label: str,
) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing columns: {missing}")
