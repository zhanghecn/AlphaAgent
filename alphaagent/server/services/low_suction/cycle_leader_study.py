"""Cycle-level realized and point-in-time leader identity ledgers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd


PERIOD_COLUMNS = (
    "sector_id",
    "concept_name",
    "cycle_id",
    "period_start",
    "period_end",
    "active_sessions",
    "candidate_count",
    "period_status",
    "candidate_pool",
)
SPELL_COLUMNS = (
    "leader_spell_id",
    "recognition_source_date",
    "sector_id",
    "concept_name",
    "cycle_id",
    "vt_symbol",
    "stock_name",
)
STOCK_BAR_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "close_price",
    "volume",
)
CONCEPT_BAR_COLUMNS = ("sector_id", "trade_date", "close_price")
REALIZED_PREFIX = "realized_"
NEAR_LIMIT_UP_PCT = 9.5
MIN_DYNAMIC_POOL = 3
IDENTITY_STRONG_DAY_PCT = 5.0
IDENTITY_CAPACITY_MIN_MEDIAN_VALUE = 100_000_000.0
IDENTITY_NO_STRONG_SESSION_SENTINEL = 10_000


def build_observed_cycle_periods(
    cycle_states: pd.DataFrame,
    candidate_spells: pd.DataFrame,
) -> pd.DataFrame:
    """Return every candidate-bearing breakout-trend period."""

    _require_columns(
        cycle_states,
        (
            "definition",
            "sector_id",
            "trade_date",
            "in_cycle",
            "cycle_id",
            "cycle_ended",
            "ended_cycle_id",
        ),
        "cycle state",
    )
    spells = _prepare_spells(candidate_spells)
    states = cycle_states.copy()
    states["trade_date"] = pd.to_datetime(
        states["trade_date"], errors="raise"
    ).dt.normalize()
    states["sector_id"] = states["sector_id"].astype(str)
    observed_ids = set(spells["cycle_id"])
    active = states.loc[
        states["definition"].eq("breakout_trend")
        & states["in_cycle"].astype(bool)
        & states["cycle_id"].astype("string").isin(observed_ids)
    ].copy()
    if active.duplicated(["sector_id", "cycle_id", "trade_date"]).any():
        raise ValueError("active cycle period identities must be unique")
    missing_cycles = observed_ids - set(active["cycle_id"].astype(str))
    if missing_cycles:
        raise ValueError(f"candidate cycles missing from cycle states: {sorted(missing_cycles)}")

    periods = (
        active.groupby(["sector_id", "cycle_id"], sort=True, as_index=False)
        .agg(
            period_start=("trade_date", "min"),
            period_end=("trade_date", "max"),
            active_sessions=("trade_date", "nunique"),
        )
    )
    spell_summary = (
        spells.groupby(["sector_id", "cycle_id"], sort=True, as_index=False)
        .agg(
            concept_name=("concept_name", "first"),
            candidate_count=("vt_symbol", "nunique"),
        )
    )
    periods = periods.merge(
        spell_summary,
        on=["sector_id", "cycle_id"],
        how="left",
        validate="one_to_one",
    )
    ended_ids = set(
        states.loc[
            states["definition"].eq("breakout_trend")
            & states["cycle_ended"].astype(bool),
            "ended_cycle_id",
        ]
        .dropna()
        .astype(str)
    )
    periods["period_status"] = np.where(
        periods["cycle_id"].astype(str).isin(ended_ids),
        "completed",
        "censored_at_discovery_end",
    )
    periods["candidate_pool"] = "event_candidate_pool"
    return periods.loc[:, list(PERIOD_COLUMNS)].sort_values(
        ["period_start", "sector_id", "cycle_id"], kind="stable"
    ).reset_index(drop=True)


def build_realized_cycle_leaders(
    periods: pd.DataFrame,
    candidate_spells: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Attach retrospective market-recognition and return ranks."""

    _require_columns(periods, PERIOD_COLUMNS, "observed period")
    spells = _prepare_spells(candidate_spells)
    stocks = _prepare_stock_bars(stock_bars)
    concepts = _prepare_concept_bars(concept_bars)
    stock_groups = {
        str(symbol): group.sort_values("trade_date", kind="stable")
        for symbol, group in stocks.groupby("vt_symbol", sort=False)
    }
    concept_groups = {
        str(sector_id): group.sort_values("trade_date", kind="stable")
        for sector_id, group in concepts.groupby("sector_id", sort=False)
    }
    period_index = periods.set_index("cycle_id", drop=False)
    rows = [
        _realized_candidate_row(
            spell,
            period_index.loc[str(spell["cycle_id"])],
            stock_groups.get(str(spell["vt_symbol"]), pd.DataFrame()),
            concept_groups.get(str(spell["sector_id"]), pd.DataFrame()),
        )
        for spell in spells.to_dict("records")
    ]
    result = pd.DataFrame(rows)
    result = _assign_realized_ranks(result)
    return result.sort_values(
        ["period_start", "sector_id", "realized_market_rank", "vt_symbol"],
        kind="stable",
    ).reset_index(drop=True)


def build_dynamic_cycle_leaders(
    periods: pd.DataFrame,
    candidate_spells: pd.DataFrame,
    target_sessions: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Rank recognized event candidates using bars through D-1 only."""

    _reject_realized_columns(candidate_spells, target_sessions)
    _require_columns(periods, PERIOD_COLUMNS, "observed period")
    _require_columns(
        target_sessions,
        ("cycle_id", "sector_id", "entry_date", "context_date"),
        "target session",
    )
    spells = _prepare_spells(candidate_spells)
    targets = _prepare_targets(target_sessions)
    stocks = _prepare_stock_bars(stock_bars)
    concepts = _prepare_concept_bars(concept_bars)
    stock_groups = {
        str(symbol): group.sort_values("trade_date", kind="stable")
        for symbol, group in stocks.groupby("vt_symbol", sort=False)
    }
    concept_groups = {
        str(sector_id): group.sort_values("trade_date", kind="stable")
        for sector_id, group in concepts.groupby("sector_id", sort=False)
    }
    spell_groups = {
        str(cycle_id): group
        for cycle_id, group in spells.groupby("cycle_id", sort=False)
    }
    period_index = periods.set_index("cycle_id", drop=False)
    rows: list[dict[str, Any]] = []
    for target in targets.to_dict("records"):
        cycle_id = str(target["cycle_id"])
        if cycle_id not in period_index.index:
            raise ValueError(f"target cycle is not observed: {cycle_id}")
        available = spell_groups.get(cycle_id, pd.DataFrame())
        available = available.loc[
            available["recognition_source_date"].le(target["context_date"])
        ]
        period = period_index.loc[cycle_id]
        target_rows = [
            _dynamic_candidate_row(
                spell,
                target,
                period,
                stock_groups.get(str(spell["vt_symbol"]), pd.DataFrame()),
                concept_groups.get(str(spell["sector_id"]), pd.DataFrame()),
            )
            for spell in available.to_dict("records")
        ]
        rows.extend(_rank_dynamic_rows(target_rows))
    if not rows:
        return _empty_dynamic_leaders()
    return pd.DataFrame(rows).sort_values(
        ["entry_date", "sector_id", "dynamic_rank", "vt_symbol"], kind="stable"
    ).reset_index(drop=True)


def build_cycle_leader_summary(
    periods: pd.DataFrame,
    realized_leaders: pd.DataFrame,
    dynamic_leaders: pd.DataFrame,
) -> pd.DataFrame:
    """Summarize both leader views without dropping uncovered periods."""

    _require_columns(periods, PERIOD_COLUMNS, "period summary")
    _require_columns(
        realized_leaders,
        (
            "cycle_id",
            "vt_symbol",
            "stock_name",
            "realized_market_rank",
            "realized_return_rank",
        ),
        "realized leader",
    )
    rows = []
    realized_groups = {
        str(cycle_id): group
        for cycle_id, group in realized_leaders.groupby("cycle_id", sort=False)
    }
    dynamic_groups = (
        {
            str(cycle_id): group
            for cycle_id, group in dynamic_leaders.groupby("cycle_id", sort=False)
        }
        if not dynamic_leaders.empty
        else {}
    )
    for period in periods.to_dict("records"):
        cycle_id = str(period["cycle_id"])
        realized = realized_groups.get(cycle_id, pd.DataFrame())
        dynamic = dynamic_groups.get(cycle_id, pd.DataFrame())
        rows.append(
            {
                **period,
                "realized_market_top3": _format_top3(
                    realized, "realized_market_rank"
                ),
                "realized_return_top3": _format_top3(
                    realized, "realized_return_rank"
                ),
                **_dynamic_period_summary(realized, dynamic),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["period_start", "sector_id", "cycle_id"], kind="stable"
    ).reset_index(drop=True)


def _realized_candidate_row(
    spell: dict[str, Any],
    period: pd.Series,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
) -> dict[str, Any]:
    start = pd.Timestamp(period["period_start"])
    end = pd.Timestamp(period["period_end"])
    stock_path = stock_bars.loc[stock_bars["trade_date"].between(start, end)].copy()
    concept_path = concept_bars.loc[
        concept_bars["trade_date"].between(start, end)
    ].copy()
    stock_return = _path_return(stock_path)
    concept_return = _path_return(concept_path)
    coverage_complete = (
        stock_path["trade_date"].nunique() == int(period["active_sessions"])
        and concept_path["trade_date"].nunique() == int(period["active_sessions"])
    )
    strong = stock_path["daily_return_pct"].ge(NEAR_LIMIT_UP_PCT)
    return {
        **spell,
        "period_start": start,
        "period_end": end,
        "period_status": str(period["period_status"]),
        "realized_path_status": "complete" if coverage_complete else "incomplete_bars",
        "realized_stock_return_pct": stock_return,
        "realized_concept_return_pct": concept_return,
        "realized_excess_return_pct": _difference(stock_return, concept_return),
        "realized_near_limit_up_days": int(strong.sum()),
        "realized_max_consecutive_near_limit_up_days": _max_consecutive_true(strong),
    }


def _assign_realized_ranks(frame: pd.DataFrame) -> pd.DataFrame:
    market_order = frame.sort_values(
        [
            "cycle_id",
            "realized_max_consecutive_near_limit_up_days",
            "realized_near_limit_up_days",
            "realized_excess_return_pct",
            "vt_symbol",
        ],
        ascending=[True, False, False, False, True],
        na_position="last",
        kind="stable",
    ).copy()
    market_order["realized_market_rank"] = (
        market_order.groupby("cycle_id", sort=False).cumcount() + 1
    )
    return_order = frame.sort_values(
        [
            "cycle_id",
            "realized_excess_return_pct",
            "realized_stock_return_pct",
            "realized_near_limit_up_days",
            "vt_symbol",
        ],
        ascending=[True, False, False, False, True],
        na_position="last",
        kind="stable",
    ).copy()
    return_order["realized_return_rank"] = (
        return_order.groupby("cycle_id", sort=False).cumcount() + 1
    )
    ranks = market_order.loc[
        :, ["cycle_id", "vt_symbol", "realized_market_rank"]
    ].merge(
        return_order.loc[:, ["cycle_id", "vt_symbol", "realized_return_rank"]],
        on=["cycle_id", "vt_symbol"],
        validate="one_to_one",
    )
    return frame.merge(
        ranks,
        on=["cycle_id", "vt_symbol"],
        how="left",
        validate="one_to_one",
    )


def _dynamic_candidate_row(
    spell: dict[str, Any],
    target: dict[str, Any],
    period: pd.Series,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
) -> dict[str, Any]:
    start = pd.Timestamp(period["period_start"])
    cutoff = pd.Timestamp(target["context_date"])
    stock_path = stock_bars.loc[stock_bars["trade_date"].between(start, cutoff)].copy()
    concept_path = concept_bars.loc[
        concept_bars["trade_date"].between(start, cutoff)
    ].copy()
    stock_return = _path_return(stock_path)
    concept_return = _path_return(concept_path)
    strong = stock_path["daily_return_pct"].ge(NEAR_LIMIT_UP_PCT)
    complete = not stock_path.empty and not concept_path.empty
    trailing_value = stock_bars.loc[stock_bars["trade_date"].le(cutoff)].tail(20)[
        "traded_value_proxy"
    ].mean()
    identity_features = _build_identity_features(
        stock_bars,
        concept_bars,
        start=start,
        cutoff=cutoff,
    )
    return {
        "cycle_id": str(target["cycle_id"]),
        "sector_id": str(target["sector_id"]),
        "entry_date": pd.Timestamp(target["entry_date"]),
        "context_date": cutoff,
        "feature_cutoff_date": cutoff,
        "leader_spell_id": str(spell["leader_spell_id"]),
        "recognition_source_date": pd.Timestamp(spell["recognition_source_date"]),
        "vt_symbol": str(spell["vt_symbol"]),
        "stock_name": str(spell["stock_name"]),
        "dynamic_feature_status": "complete" if complete else "incomplete_bars",
        "dynamic_stock_return_pct": stock_return,
        "dynamic_concept_return_pct": concept_return,
        "dynamic_excess_return_pct": _difference(stock_return, concept_return),
        "dynamic_near_limit_up_days": int(strong.sum()),
        "dynamic_max_consecutive_near_limit_up_days": _max_consecutive_true(strong),
        "dynamic_sessions_since_last_near_limit_up": _sessions_since_last_true(strong),
        "dynamic_traded_value_20d": _finite_or_none(trailing_value),
        **identity_features,
    }


def _rank_dynamic_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    frame = pd.DataFrame(rows)
    complete = frame["dynamic_feature_status"].eq("complete")
    ranked = frame.loc[complete].sort_values(
        [
            "dynamic_max_consecutive_near_limit_up_days",
            "dynamic_near_limit_up_days",
            "dynamic_excess_return_pct",
            "dynamic_traded_value_20d",
            "vt_symbol",
        ],
        ascending=[False, False, False, False, True],
        na_position="last",
        kind="stable",
    ).copy()
    ranked["dynamic_rank"] = np.arange(1, len(ranked) + 1)
    pool_size = len(ranked)
    qualified = pool_size >= MIN_DYNAMIC_POOL
    ranked["dynamic_pool_size"] = pool_size
    ranked["dynamic_top3_qualified"] = qualified
    ranked["dynamic_top1"] = qualified & ranked["dynamic_rank"].eq(1)
    ranked["dynamic_top3"] = qualified & ranked["dynamic_rank"].le(3)
    incomplete = frame.loc[~complete].copy()
    if not incomplete.empty:
        incomplete["dynamic_rank"] = pd.NA
        incomplete["dynamic_pool_size"] = pool_size
        incomplete["dynamic_top3_qualified"] = False
        incomplete["dynamic_top1"] = False
        incomplete["dynamic_top3"] = False
        ranked = pd.concat([ranked, incomplete], ignore_index=True)
    return ranked.to_dict("records")


def _dynamic_period_summary(
    realized: pd.DataFrame,
    dynamic: pd.DataFrame,
) -> dict[str, Any]:
    if dynamic.empty:
        return {
            "dynamic_sessions": 0,
            "qualified_dynamic_sessions": 0,
            "distinct_dynamic_top1": 0,
            "realized_market_top1_dynamic_top3_retention_pct": None,
        }
    dynamic_sessions = int(dynamic["entry_date"].nunique())
    qualified_dates = set(
        dynamic.loc[dynamic["dynamic_top3_qualified"].astype(bool), "entry_date"]
    )
    top1_symbols = dynamic.loc[dynamic["dynamic_top1"].astype(bool), "vt_symbol"].nunique()
    oracle = realized.loc[realized["realized_market_rank"].eq(1), "vt_symbol"]
    if not qualified_dates or oracle.empty:
        retention = None
    else:
        oracle_symbol = str(oracle.iloc[0])
        retained_dates = set(
            dynamic.loc[
                dynamic["entry_date"].isin(qualified_dates)
                & dynamic["vt_symbol"].eq(oracle_symbol)
                & dynamic["dynamic_top3"].astype(bool),
                "entry_date",
            ]
        )
        retention = len(retained_dates) / len(qualified_dates) * 100.0
    return {
        "dynamic_sessions": dynamic_sessions,
        "qualified_dynamic_sessions": len(qualified_dates),
        "distinct_dynamic_top1": int(top1_symbols),
        "realized_market_top1_dynamic_top3_retention_pct": retention,
    }


def _prepare_spells(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, SPELL_COLUMNS, "candidate spell")
    result = frame.loc[:, list(SPELL_COLUMNS)].copy()
    result["recognition_source_date"] = pd.to_datetime(
        result["recognition_source_date"], errors="raise"
    ).dt.normalize()
    for column in ("sector_id", "concept_name", "cycle_id", "vt_symbol", "stock_name"):
        result[column] = result[column].astype(str).str.strip()
    if result.duplicated(["cycle_id", "vt_symbol"]).any():
        raise ValueError("candidate spells must be unique by cycle and stock")
    return result.sort_values(
        ["recognition_source_date", "cycle_id", "vt_symbol"], kind="stable"
    ).reset_index(drop=True)


def _prepare_targets(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.loc[
        :, ["cycle_id", "sector_id", "entry_date", "context_date"]
    ].copy()
    for column in ("entry_date", "context_date"):
        result[column] = pd.to_datetime(result[column], errors="raise").dt.normalize()
    if result.duplicated(["cycle_id", "entry_date"]).any():
        raise ValueError("target sessions must be unique by cycle and entry date")
    if result["context_date"].ge(result["entry_date"]).any():
        raise ValueError("dynamic leader context must be before entry date")
    return result.sort_values(["entry_date", "sector_id", "cycle_id"], kind="stable")


def _prepare_stock_bars(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, STOCK_BAR_COLUMNS, "stock bar")
    columns = [*STOCK_BAR_COLUMNS]
    if "turnover" in frame:
        columns.append("turnover")
    bars = frame.loc[:, columns].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.normalize()
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock bar identities must be unique")
    for column in ("close_price", "volume"):
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    if "turnover" in bars:
        bars["turnover"] = pd.to_numeric(bars["turnover"], errors="coerce")
    bars = bars.sort_values(["vt_symbol", "trade_date"], kind="stable")
    bars["daily_return_pct"] = bars.groupby("vt_symbol", sort=False)[
        "close_price"
    ].pct_change(fill_method=None) * 100.0
    bars["traded_value_proxy"] = bars["close_price"] * bars["volume"]
    return bars.reset_index(drop=True)


def _build_identity_features(
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
    *,
    start: pd.Timestamp,
    cutoff: pd.Timestamp,
) -> dict[str, Any]:
    empty = {
        "identity_feature_status": "incomplete_bars",
        "identity_cycle_relative_return": None,
        "identity_strong_day_count_cycle": None,
        "identity_sessions_since_strong": None,
        "identity_turnover_median_20d": None,
        "identity_capacity_passed": False,
    }
    if "turnover" not in stock_bars:
        return empty

    known_stock = stock_bars.loc[stock_bars["trade_date"].le(cutoff)].copy()
    known_concept = concept_bars.loc[concept_bars["trade_date"].le(cutoff)].copy()
    stock_anchor = _last_positive_close(known_stock.loc[known_stock["trade_date"].lt(start)])
    concept_anchor = _last_positive_close(
        known_concept.loc[known_concept["trade_date"].lt(start)]
    )
    stock_close = _exact_positive_close(known_stock, cutoff)
    concept_close = _exact_positive_close(known_concept, cutoff)
    trailing_turnover = pd.to_numeric(
        known_stock.tail(20)["turnover"], errors="coerce"
    )
    turnover_complete = (
        len(trailing_turnover) == 20
        and trailing_turnover.notna().all()
        and np.isfinite(trailing_turnover.to_numpy(dtype=float)).all()
        and trailing_turnover.gt(0).all()
    )
    if (
        stock_anchor is None
        or concept_anchor is None
        or stock_close is None
        or concept_close is None
        or not turnover_complete
    ):
        return empty

    cycle_stock = known_stock.loc[known_stock["trade_date"].ge(start)]
    strong_cycle = cycle_stock["daily_return_pct"].ge(IDENTITY_STRONG_DAY_PCT)
    all_strong = known_stock["daily_return_pct"].ge(IDENTITY_STRONG_DAY_PCT)
    turnover_median = float(trailing_turnover.median())
    return {
        "identity_feature_status": "complete",
        "identity_cycle_relative_return": float(
            (stock_close / stock_anchor - concept_close / concept_anchor) * 100.0
        ),
        "identity_strong_day_count_cycle": int(strong_cycle.sum()),
        "identity_sessions_since_strong": _identity_sessions_since_strong(all_strong),
        "identity_turnover_median_20d": turnover_median,
        "identity_capacity_passed": bool(
            turnover_median >= IDENTITY_CAPACITY_MIN_MEDIAN_VALUE
        ),
    }


def _last_positive_close(frame: pd.DataFrame) -> float | None:
    values = pd.to_numeric(frame.get("close_price"), errors="coerce").dropna()
    return _positive_or_none(values.iloc[-1]) if not values.empty else None


def _exact_positive_close(frame: pd.DataFrame, trade_date: pd.Timestamp) -> float | None:
    rows = frame.loc[frame["trade_date"].eq(trade_date), "close_price"]
    return _positive_or_none(rows.iloc[0]) if len(rows) == 1 else None


def _positive_or_none(value: Any) -> float | None:
    number = _finite_or_none(value)
    return number if number is not None and number > 0 else None


def _identity_sessions_since_strong(values: pd.Series) -> int:
    mask = values.fillna(False).astype(bool).to_numpy()
    positions = np.flatnonzero(mask)
    if len(positions) == 0:
        return IDENTITY_NO_STRONG_SESSION_SENTINEL
    return int(len(mask) - 1 - positions[-1])


def _prepare_concept_bars(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, CONCEPT_BAR_COLUMNS, "concept bar")
    bars = frame.loc[:, list(CONCEPT_BAR_COLUMNS)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.normalize()
    bars["close_price"] = pd.to_numeric(bars["close_price"], errors="coerce")
    if bars.duplicated(["sector_id", "trade_date"]).any():
        raise ValueError("concept bar identities must be unique")
    return bars.sort_values(["sector_id", "trade_date"], kind="stable").reset_index(
        drop=True
    )


def _path_return(path: pd.DataFrame) -> float | None:
    values = pd.to_numeric(path.get("close_price"), errors="coerce").dropna()
    if len(values) < 1 or values.iloc[0] <= 0:
        return None
    return float((values.iloc[-1] / values.iloc[0] - 1.0) * 100.0)


def _difference(left: float | None, right: float | None) -> float | None:
    return None if left is None or right is None else left - right


def _max_consecutive_true(values: pd.Series) -> int:
    maximum = 0
    current = 0
    for value in values.fillna(False).astype(bool):
        current = current + 1 if value else 0
        maximum = max(maximum, current)
    return maximum


def _sessions_since_last_true(values: pd.Series) -> int:
    mask = values.fillna(False).astype(bool).to_numpy()
    positions = np.flatnonzero(mask)
    return len(mask) if len(positions) == 0 else int(len(mask) - 1 - positions[-1])


def _format_top3(frame: pd.DataFrame, rank_column: str) -> str:
    if frame.empty:
        return ""
    selected = frame.loc[frame[rank_column].le(3)].sort_values(
        rank_column, kind="stable"
    )
    return " | ".join(
        f"{row.stock_name} ({row.vt_symbol})"
        for row in selected.itertuples(index=False)
    )


def _finite_or_none(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _reject_realized_columns(*frames: pd.DataFrame) -> None:
    prohibited = sorted(
        {
            str(column)
            for frame in frames
            for column in frame.columns
            if str(column).startswith(REALIZED_PREFIX)
        }
    )
    if prohibited:
        raise ValueError(f"realized outcome columns are prohibited from dynamic rank: {prohibited}")


def _empty_dynamic_leaders() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "cycle_id",
            "sector_id",
            "entry_date",
            "context_date",
            "feature_cutoff_date",
            "leader_spell_id",
            "recognition_source_date",
            "vt_symbol",
            "stock_name",
            "dynamic_feature_status",
            "dynamic_stock_return_pct",
            "dynamic_concept_return_pct",
            "dynamic_excess_return_pct",
            "dynamic_near_limit_up_days",
            "dynamic_max_consecutive_near_limit_up_days",
            "dynamic_sessions_since_last_near_limit_up",
            "dynamic_traded_value_20d",
            "identity_feature_status",
            "identity_cycle_relative_return",
            "identity_strong_day_count_cycle",
            "identity_sessions_since_strong",
            "identity_turnover_median_20d",
            "identity_capacity_passed",
            "dynamic_rank",
            "dynamic_pool_size",
            "dynamic_top3_qualified",
            "dynamic_top1",
            "dynamic_top3",
        ]
    )


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
