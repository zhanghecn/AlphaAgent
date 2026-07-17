"""Discovery-only falsification study for event-recognized low-suction stocks."""

from __future__ import annotations

import bisect
import json
import math
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from alphaagent.server.services.execution import cash_ledger

from .concept_cycles import build_cycle_candidates, load_cycle_research_inputs
from .contracts import CONCEPT_SECTOR_TYPES
from .research_protocol import default_protocol, fingerprint_frame, protocol_hash
from .theme_reference_cohorts import classify_manifest_sector

EVIDENCE_LEVEL = "event_recognition_falsification"
COHORT_LABEL = "recognition_top3_incomplete_denominator"
ENTRY_DEPTHS_PCT = (0.0, 2.0, 4.0, 6.0)
MIN_PRIOR_SESSIONS = 60
EVENT_BLOCK_COUNT = 5
INITIAL_CASH = 100_000.0

COMMISSION_RATE = 0.0003
MINIMUM_COMMISSION = 5.0
STAMP_TAX_RATE = 0.0005
TRANSFER_FEE_RATE = 0.00001
SLIPPAGE_BPS = 10.0
LOT_SIZE = 100

PROHIBITED_OUTCOME_COLUMNS = frozenset(
    {
        "net_return_pct",
        "gross_return_pct",
        "entry_price",
        "exit_price",
        "mfe_pct",
        "mae_pct",
    }
)
EXCLUDED_MANIFEST_CLASSES = frozenset(
    {"mechanical_event", "style_universe", "report_event", "ambiguous"}
)

EVENT_COLUMNS = (
    "event_id",
    "source_date",
    "vt_symbol",
    "stock_name",
    "reason",
    "limit_times",
    "limit_up_suc_rate",
    "fd_amount",
    "float_market_cap",
    "amount",
)
RELATION_COLUMNS = (
    "event_id",
    "source_date",
    "sector_id",
    "concept_name",
    "vt_symbol",
    "stock_name",
    "limit_times",
    "limit_up_suc_rate",
    "fd_amount",
    "float_market_cap",
    "amount",
)
BAR_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
)


@dataclass(frozen=True)
class EventFalsificationInputs:
    candidates: pd.DataFrame
    stock_bars: pd.DataFrame
    trading_dates: tuple[date, ...]
    discovery_start: date
    discovery_end: date
    coverage: dict[str, Any]
    input_fingerprints: dict[str, dict[str, Any]]


def build_exact_reason_relations(
    events: pd.DataFrame,
    concepts: pd.DataFrame,
) -> pd.DataFrame:
    """Map event reasons to concept names without aliases or membership fallback."""

    _require_columns(events, EVENT_COLUMNS, "event")
    _require_columns(concepts, ("sector_id", "concept_name"), "concept")
    frame = events.copy()
    frame["source_date"] = pd.to_datetime(
        frame["source_date"], errors="raise"
    ).dt.date
    frame["reason_token"] = frame["reason"].fillna("").astype(str).str.split(
        "+", regex=False
    )
    frame = frame.explode("reason_token", ignore_index=True)
    frame["reason_token"] = frame["reason_token"].fillna("").str.strip()

    concept_frame = concepts.loc[:, ["sector_id", "concept_name"]].copy()
    concept_frame["sector_id"] = concept_frame["sector_id"].astype(str)
    concept_frame["concept_name"] = concept_frame["concept_name"].astype(str).str.strip()
    if concept_frame.duplicated(["sector_id"]).any():
        raise ValueError("concept sector IDs must be unique")
    if concept_frame.duplicated(["concept_name"]).any():
        raise ValueError("concept names must be unique for exact event matching")

    result = frame.merge(
        concept_frame,
        left_on="reason_token",
        right_on="concept_name",
        how="inner",
        validate="many_to_one",
    )
    result = result.loc[:, list(RELATION_COLUMNS)].drop_duplicates(
        ["source_date", "sector_id", "vt_symbol"], keep="first"
    )
    return result.sort_values(
        ["source_date", "sector_id", "vt_symbol"], kind="stable"
    ).reset_index(drop=True)


def build_recognition_candidates(
    relations: pd.DataFrame,
    cycle_states: pd.DataFrame,
    stock_bars: pd.DataFrame,
    trading_dates: tuple[date, ...],
) -> pd.DataFrame:
    """Build incomplete-denominator recognition Top3 candidates known after close."""

    _require_columns(relations, RELATION_COLUMNS, "event relation")
    _require_columns(
        cycle_states,
        (
            "trade_date",
            "sector_id",
            "definition",
            "in_cycle",
            "cycle_id",
            "relative_percentile",
        ),
        "cycle state",
    )
    _require_columns(stock_bars, BAR_COLUMNS, "stock bar")
    prohibited = PROHIBITED_OUTCOME_COLUMNS & set(cycle_states)
    if prohibited:
        raise ValueError(f"outcomes are prohibited from recognition ranking: {sorted(prohibited)}")

    calendar = _normalized_calendar(trading_dates)
    if not calendar:
        return _empty_candidates()
    states = cycle_states.copy()
    states["source_date"] = pd.to_datetime(
        states["trade_date"], errors="raise"
    ).dt.date
    states = states.loc[
        states["definition"].eq("breakout_trend") & states["in_cycle"].astype(bool),
        ["source_date", "sector_id", "cycle_id", "relative_percentile"],
    ]
    if states.duplicated(["source_date", "sector_id"]).any():
        raise ValueError("active cycle state identity must be unique")

    bars = _prepare_bars(stock_bars)
    bars["prior_sessions"] = bars.groupby("vt_symbol", sort=False).cumcount()
    source_bars = bars.loc[
        :,
        ["vt_symbol", "trade_date", "close_price", "prior_sessions"],
    ].rename(
        columns={"trade_date": "source_date", "close_price": "signal_close"}
    )

    frame = relations.copy()
    frame["source_date"] = pd.to_datetime(
        frame["source_date"], errors="raise"
    ).dt.date
    frame = frame.merge(
        states,
        on=["source_date", "sector_id"],
        how="inner",
        validate="many_to_one",
    ).merge(
        source_bars,
        on=["source_date", "vt_symbol"],
        how="inner",
        validate="many_to_one",
    )
    if frame.empty:
        return _empty_candidates()

    frame = frame.loc[
        frame["vt_symbol"].map(_is_main_board_symbol)
        & ~frame["stock_name"].map(_is_excluded_event_name)
        & frame["prior_sessions"].ge(MIN_PRIOR_SESSIONS)
    ].copy()
    eligible_count = frame.groupby(
        ["source_date", "sector_id"], sort=False
    )["vt_symbol"].transform("nunique")
    frame = frame.loc[eligible_count.ge(3)].copy()
    if frame.empty:
        return _empty_candidates()

    numeric_columns = (
        "limit_times",
        "limit_up_suc_rate",
        "fd_amount",
        "float_market_cap",
        "amount",
        "relative_percentile",
    )
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    valid_market_cap = frame["float_market_cap"].where(
        frame["float_market_cap"].gt(0)
    )
    frame["seal_strength"] = frame["fd_amount"] / valid_market_cap
    order_columns = [
        "source_date",
        "sector_id",
        "limit_times",
        "limit_up_suc_rate",
        "seal_strength",
        "amount",
        "vt_symbol",
    ]
    frame = frame.sort_values(
        order_columns,
        ascending=[True, True, False, False, False, False, True],
        na_position="last",
        kind="stable",
    )
    frame["recognition_rank"] = (
        frame.groupby(["source_date", "sector_id"], sort=False).cumcount() + 1
    )
    frame = frame.loc[frame["recognition_rank"].le(3)].copy()

    frame = frame.sort_values(
        [
            "source_date",
            "vt_symbol",
            "relative_percentile",
            "recognition_rank",
            "sector_id",
        ],
        ascending=[True, True, False, True, True],
        na_position="last",
        kind="stable",
    ).drop_duplicates(["source_date", "vt_symbol"], keep="first")
    next_dates = _next_session_map(calendar)
    frame["entry_date"] = frame["source_date"].map(next_dates)
    frame["planned_exit_date"] = frame["entry_date"].map(next_dates)
    frame = frame.loc[frame["planned_exit_date"].notna()].copy()
    frame["evidence_level"] = EVIDENCE_LEVEL

    result_columns = list(_empty_candidates().columns)
    return frame.loc[:, result_columns].sort_values(
        ["source_date", "sector_id", "recognition_rank", "vt_symbol"],
        kind="stable",
    ).reset_index(drop=True)


def execute_frozen_limit_grid(
    candidates: pd.DataFrame,
    stock_bars: pd.DataFrame,
    *,
    trading_dates: tuple[date, ...],
    cost_multiplier: float = 1.0,
    initial_cash: float = INITIAL_CASH,
) -> pd.DataFrame:
    """Execute frozen pre-open limit orders and a D+1 sellable-close exit."""

    _require_columns(
        candidates,
        (
            "event_id",
            "source_date",
            "entry_date",
            "sector_id",
            "concept_name",
            "cycle_id",
            "vt_symbol",
            "recognition_rank",
            "signal_close",
            "evidence_level",
        ),
        "candidate",
    )
    _require_columns(stock_bars, BAR_COLUMNS, "stock bar")
    if cost_multiplier <= 0 or initial_cash <= 0:
        raise ValueError("cost multiplier and initial cash must be positive")
    if candidates.empty:
        return _empty_outcomes()

    calendar = _normalized_calendar(trading_dates)
    bars = _prepare_bars(stock_bars)
    bars["previous_close"] = bars.groupby("vt_symbol", sort=False)[
        "close_price"
    ].shift(1)
    bar_index = {
        (str(row.vt_symbol), row.trade_date): row
        for row in bars.itertuples(index=False)
    }
    rows: list[dict[str, Any]] = []
    ordered_candidates = candidates.sort_values(
        ["source_date", "sector_id", "recognition_rank", "vt_symbol"],
        kind="stable",
    )
    for candidate in ordered_candidates.to_dict("records"):
        for depth in ENTRY_DEPTHS_PCT:
            rows.append(
                _execute_candidate_depth(
                    candidate,
                    depth=depth,
                    calendar=calendar,
                    bar_index=bar_index,
                    cost_multiplier=cost_multiplier,
                    initial_cash=initial_cash,
                )
            )
    return pd.DataFrame(rows, columns=_empty_outcomes().columns)


def chronological_event_blocks(
    source_dates: tuple[date, ...] | list[date],
    *,
    block_count: int = EVENT_BLOCK_COUNT,
) -> pd.DataFrame:
    """Split available event dates into deterministic non-overlapping time blocks."""

    dates = tuple(sorted(set(pd.to_datetime(source_dates, errors="raise").date)))
    if block_count < 1:
        raise ValueError("block_count must be positive")
    if len(dates) < block_count:
        raise ValueError("event dates must cover every requested block")
    rows = []
    for block, values in enumerate(np.array_split(np.array(dates, dtype=object), block_count), 1):
        rows.extend(
            {"source_date": value, "block": block}
            for value in values.tolist()
        )
    return pd.DataFrame(rows).sort_values("source_date", kind="stable").reset_index(drop=True)


def summarize_falsification_outcomes(
    outcomes: pd.DataFrame,
    stressed_outcomes: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return full-depth and chronological-block metrics without selecting a rule."""

    if outcomes.empty:
        return pd.DataFrame(), pd.DataFrame()
    event_dates = tuple(sorted(set(pd.to_datetime(outcomes["source_date"]).dt.date)))
    blocks = chronological_event_blocks(event_dates)
    normal = outcomes.copy()
    stressed = stressed_outcomes.copy()
    normal["source_date"] = pd.to_datetime(normal["source_date"]).dt.date
    stressed["source_date"] = pd.to_datetime(stressed["source_date"]).dt.date
    normal = normal.merge(blocks, on="source_date", how="left", validate="many_to_one")
    stressed = stressed.merge(blocks, on="source_date", how="left", validate="many_to_one")

    block_rows = []
    for (depth, block), group in normal.groupby(
        ["entry_depth_pct", "block"], sort=True
    ):
        closed = group.loc[group["status"].eq("closed")]
        returns = pd.to_numeric(closed["net_return_pct"], errors="coerce").dropna()
        block_rows.append(
            {
                "entry_depth_pct": float(depth),
                "block": int(block),
                "source_days": int(group["source_date"].nunique()),
                "closed_trades": int(len(returns)),
                "win_rate_pct": _win_rate_pct(returns),
                "mean_net_return_pct": _mean(returns),
                "profit_factor": _profit_factor(returns),
                "positive_block": bool(
                    len(returns)
                    and float(returns.mean()) > 0
                    and (_profit_factor(returns) or 0) > 1
                ),
            }
        )
    block_metrics = pd.DataFrame(block_rows)

    depth_rows = []
    for depth, group in normal.groupby("entry_depth_pct", sort=True):
        closed = group.loc[group["status"].eq("closed")].copy()
        returns = pd.to_numeric(closed["net_return_pct"], errors="coerce").dropna()
        stressed_group = stressed.loc[
            stressed["entry_depth_pct"].eq(depth)
            & stressed["status"].eq("closed")
        ]
        stressed_returns = pd.to_numeric(
            stressed_group["net_return_pct"], errors="coerce"
        ).dropna()
        positive_blocks = int(
            block_metrics.loc[
                block_metrics["entry_depth_pct"].eq(float(depth)),
                "positive_block",
            ].sum()
        )
        closed_count = int(len(returns))
        depth_rows.append(
            {
                "entry_depth_pct": float(depth),
                "candidate_orders": int(len(group)),
                "filled_orders": int(group["status"].isin({"closed", "unclosed"}).sum()),
                "closed_trades": closed_count,
                "fill_rate_pct": (
                    float(closed_count / len(group) * 100.0) if len(group) else None
                ),
                "win_rate_pct": _win_rate_pct(returns),
                "mean_net_return_pct": _mean(returns),
                "median_net_return_pct": _median(returns),
                "profit_factor": _profit_factor(returns),
                "tail_5pct": _quantile(returns, 0.05),
                "maximum_episode_loss_pct": (
                    float(returns.min()) if len(returns) else None
                ),
                "positive_blocks": positive_blocks,
                "double_cost_mean_net_return_pct": _mean(stressed_returns),
                "maximum_month_trade_share": _maximum_group_share(
                    closed, pd.to_datetime(closed["source_date"]).dt.to_period("M")
                ),
                "maximum_concept_trade_share": _maximum_group_share(
                    closed, closed["sector_id"]
                ),
                "qualified_for_strict_retest": bool(
                    closed_count >= 100
                    and positive_blocks >= 4
                    and len(stressed_returns)
                    and float(stressed_returns.mean()) > 0
                ),
            }
        )
    return pd.DataFrame(depth_rows), block_metrics


def summarize_regime_diagnostics(
    outcomes: pd.DataFrame,
    stressed_outcomes: pd.DataFrame,
) -> pd.DataFrame:
    """Describe every pre-existing market context without selecting a policy."""

    required = ("entry_depth_pct", "source_date", "status", "net_return_pct")
    _require_columns(outcomes, required, "outcome")
    _require_columns(stressed_outcomes, required, "stressed outcome")
    normal = outcomes.copy()
    stressed = stressed_outcomes.copy()
    for frame in (normal, stressed):
        if "active_direction" not in frame:
            frame["active_direction"] = "UNKNOWN"
        if "danger_state" not in frame:
            frame["danger_state"] = "UNKNOWN"
        frame["active_direction"] = frame["active_direction"].fillna("UNKNOWN")
        frame["danger_state"] = frame["danger_state"].fillna("UNKNOWN")
        frame["regime_key"] = (
            frame["active_direction"].astype(str)
            + "/"
            + frame["danger_state"].astype(str)
        )
    event_dates = tuple(sorted(set(pd.to_datetime(normal["source_date"]).dt.date)))
    blocks = chronological_event_blocks(
        event_dates,
        block_count=min(EVENT_BLOCK_COUNT, len(event_dates)),
    )
    normal["source_date"] = pd.to_datetime(normal["source_date"]).dt.date
    stressed["source_date"] = pd.to_datetime(stressed["source_date"]).dt.date
    normal = normal.merge(blocks, on="source_date", how="left", validate="many_to_one")
    stressed = stressed.merge(blocks, on="source_date", how="left", validate="many_to_one")

    rows = []
    for (depth, regime_key), group in normal.groupby(
        ["entry_depth_pct", "regime_key"], sort=True
    ):
        closed = group.loc[group["status"].eq("closed")]
        returns = pd.to_numeric(closed["net_return_pct"], errors="coerce").dropna()
        stressed_returns = pd.to_numeric(
            stressed.loc[
                stressed["entry_depth_pct"].eq(depth)
                & stressed["regime_key"].eq(regime_key)
                & stressed["status"].eq("closed"),
                "net_return_pct",
            ],
            errors="coerce",
        ).dropna()
        observed_blocks = 0
        positive_blocks = 0
        for _, block_group in group.groupby("block", sort=True):
            block_returns = pd.to_numeric(
                block_group.loc[
                    block_group["status"].eq("closed"), "net_return_pct"
                ],
                errors="coerce",
            ).dropna()
            if block_returns.empty:
                continue
            observed_blocks += 1
            if (
                float(block_returns.mean()) > 0
                and (_profit_factor(block_returns) or 0) > 1
            ):
                positive_blocks += 1
        source_days = int(group["source_date"].nunique())
        rows.append(
            {
                "entry_depth_pct": float(depth),
                "regime_key": str(regime_key),
                "source_days": source_days,
                "candidate_orders": int(len(group)),
                "closed_trades": int(len(returns)),
                "win_rate_pct": _win_rate_pct(returns),
                "mean_net_return_pct": _mean(returns),
                "profit_factor": _profit_factor(returns),
                "double_cost_mean_net_return_pct": _mean(stressed_returns),
                "sample_at_least_30": bool(len(returns) >= 30),
                "material_days_at_least_20": bool(source_days >= 20),
                "observed_time_blocks": observed_blocks,
                "positive_time_blocks": positive_blocks,
            }
        )
    return pd.DataFrame(rows)


def evaluate_retest_gate(depth_metrics: pd.DataFrame) -> dict[str, Any]:
    """Classify direction quality while explicitly refusing formal rule selection."""

    _require_columns(
        depth_metrics,
        (
            "entry_depth_pct",
            "closed_trades",
            "positive_blocks",
            "double_cost_mean_net_return_pct",
        ),
        "depth metric",
    )
    if depth_metrics.empty:
        return {
            "status": "no_event_recognition_edge",
            "qualifying_depths_pct": [],
            "formal_rule_selected": False,
        }
    qualified = depth_metrics.loc[
        depth_metrics["closed_trades"].ge(100)
        & depth_metrics["positive_blocks"].ge(4)
        & pd.to_numeric(
            depth_metrics["double_cost_mean_net_return_pct"], errors="coerce"
        ).gt(0)
    ]
    if not qualified.empty:
        status = "worth_strict_retest"
    else:
        direction = depth_metrics.loc[depth_metrics["closed_trades"].ge(100)].copy()
        if {"mean_net_return_pct", "profit_factor"} <= set(direction):
            direction = direction.loc[
                pd.to_numeric(direction["mean_net_return_pct"], errors="coerce").gt(0)
                & pd.to_numeric(direction["profit_factor"], errors="coerce").gt(1)
                & pd.to_numeric(
                    direction["double_cost_mean_net_return_pct"], errors="coerce"
                ).gt(0)
            ]
        status = (
            "event_recognition_direction_only"
            if not direction.empty
            else "no_event_recognition_edge"
        )
    return {
        "status": status,
        "qualifying_depths_pct": sorted(
            float(value) for value in qualified["entry_depth_pct"].tolist()
        ),
        "formal_rule_selected": False,
    }


def load_event_falsification_inputs() -> EventFalsificationInputs:
    """Load event-available discovery values without touching outer holdout prices."""

    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine, session_scope

    cycle_inputs = load_cycle_research_inputs()
    cycle_states = build_cycle_candidates(
        cycle_inputs.concept_bars,
        cycle_inputs.market_returns,
    )
    discovery_start = cycle_inputs.split.discovery_dates[0]
    discovery_end = cycle_inputs.split.discovery_dates[-1]
    event_date_end = discovery_end.strftime("%Y%m%d")

    with session_scope() as session:
        event_rows = session.execute(
            select(
                schema.stock_events.c.id,
                schema.stock_events.c.vt_symbol,
                schema.stock_events.c.event_date,
                schema.stock_events.c.raw,
            )
            .where(
                schema.stock_events.c.event_type == "limit_pool_zt",
                schema.stock_events.c.event_date <= event_date_end,
            )
            .order_by(schema.stock_events.c.event_date, schema.stock_events.c.id)
        ).mappings().all()
        concept_rows = session.execute(
            select(schema.sectors.c.id, schema.sectors.c.name)
            .where(schema.sectors.c.type.in_(CONCEPT_SECTOR_TYPES))
            .order_by(schema.sectors.c.id)
        ).all()

    events = _normalize_database_events(event_rows, discovery_end=discovery_end)
    concepts = pd.DataFrame(concept_rows, columns=["sector_id", "concept_name"])
    concepts["manifest_class"] = concepts["sector_id"].map(classify_manifest_sector)
    concepts = concepts.loc[
        ~concepts["manifest_class"].isin(EXCLUDED_MANIFEST_CLASSES)
    ].copy()
    relations = build_exact_reason_relations(events, concepts)
    symbols = tuple(sorted(relations["vt_symbol"].astype(str).unique()))

    reliable_dates = cycle_inputs.reliable_dates
    first_event_date = min(relations["source_date"]) if not relations.empty else discovery_end
    first_position = bisect.bisect_left(reliable_dates, first_event_date)
    bar_start = reliable_dates[max(0, first_position - 100)]
    bar_statement = (
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
            schema.stock_daily_bars.c.trade_date.between(bar_start, discovery_end),
        )
        .order_by(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
        )
    )
    stock_bars = pd.read_sql(
        bar_statement,
        get_engine(),
        parse_dates=["trade_date"],
    )
    candidates = build_recognition_candidates(
        relations,
        cycle_states,
        stock_bars,
        reliable_dates,
    )
    timing_context = load_timing_context()
    timing_context = timing_context.loc[
        timing_context["source_date"].le(discovery_end)
    ].copy()
    candidates = candidates.merge(
        timing_context,
        on="source_date",
        how="left",
        validate="many_to_one",
    )
    for column in ("active_direction", "danger_state", "market_phase"):
        candidates[column] = candidates[column].fillna("UNKNOWN")
    event_dates = int(events["source_date"].nunique()) if not events.empty else 0
    relation_concept_days = int(
        relations[["source_date", "sector_id"]].drop_duplicates().shape[0]
    )
    candidate_concept_days = int(
        candidates[["source_date", "sector_id"]].drop_duplicates().shape[0]
    )
    coverage = {
        "event_rows_with_reason": int(len(events)),
        "event_dates": event_dates,
        "event_start": min(events["source_date"]).isoformat() if event_dates else None,
        "event_end": max(events["source_date"]).isoformat() if event_dates else None,
        "exact_reason_relations": int(len(relations)),
        "matched_concepts": int(relations["sector_id"].nunique()),
        "relation_concept_days": relation_concept_days,
        "eligible_recognition_concept_days": candidate_concept_days,
        "recognition_candidates": int(len(candidates)),
        "candidate_symbols": int(candidates["vt_symbol"].nunique()),
        "stock_bar_rows": int(len(stock_bars)),
        "stock_bar_start": bar_start.isoformat(),
        "stock_bar_end": discovery_end.isoformat(),
        "current_membership_rows_read": 0,
    }
    fingerprints = {
        "event_relations": fingerprint_frame(
            relations,
            identity_columns=("source_date", "sector_id", "vt_symbol"),
        ).as_dict(),
        "recognition_candidates": fingerprint_frame(
            candidates,
            identity_columns=("source_date", "vt_symbol"),
        ).as_dict(),
        "stock_bars": fingerprint_frame(
            stock_bars,
            identity_columns=("trade_date", "vt_symbol"),
        ).as_dict(),
    }
    return EventFalsificationInputs(
        candidates=candidates,
        stock_bars=stock_bars,
        trading_dates=tuple(
            value for value in reliable_dates if value <= discovery_end
        ),
        discovery_start=discovery_start,
        discovery_end=discovery_end,
        coverage=coverage,
        input_fingerprints=fingerprints,
    )


def run_event_recognition_falsification() -> dict[str, Any]:
    inputs = load_event_falsification_inputs()
    outcomes = execute_frozen_limit_grid(
        inputs.candidates,
        inputs.stock_bars,
        trading_dates=inputs.trading_dates,
    )
    stressed = execute_frozen_limit_grid(
        inputs.candidates,
        inputs.stock_bars,
        trading_dates=inputs.trading_dates,
        cost_multiplier=2.0,
    )
    depth_metrics, block_metrics = summarize_falsification_outcomes(
        outcomes,
        stressed,
    )
    regime_metrics = summarize_regime_diagnostics(outcomes, stressed)
    return build_event_falsification_report(
        coverage=inputs.coverage,
        depth_metrics=depth_metrics,
        block_metrics=block_metrics,
        regime_metrics=regime_metrics,
        discovery_start=inputs.discovery_start,
        discovery_end=inputs.discovery_end,
        input_fingerprints=inputs.input_fingerprints,
    )


def build_event_falsification_report(
    *,
    coverage: dict[str, Any],
    depth_metrics: pd.DataFrame,
    block_metrics: pd.DataFrame,
    regime_metrics: pd.DataFrame | None = None,
    discovery_start: date,
    discovery_end: date,
    input_fingerprints: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    decision = evaluate_retest_gate(depth_metrics)
    protocol = default_protocol()
    return {
        "protocol_version": protocol.version,
        "protocol_hash": protocol_hash(protocol),
        "evidence_level": EVIDENCE_LEVEL,
        "cohort_label": COHORT_LABEL,
        "overall_conclusion": decision["status"],
        "formal_metrics": None,
        "formal_rule_selected": False,
        "holdout_price_values_read": False,
        "current_membership_rows_read": 0,
        "date_split": {
            "discovery_start": discovery_start.isoformat(),
            "discovery_end": discovery_end.isoformat(),
            "event_available_dates": int(coverage.get("event_dates") or 0),
            "event_blocks": EVENT_BLOCK_COUNT,
        },
        "frozen_contract": {
            "main_rise": "breakout_trend active at source-date close",
            "relation": "exact plus-delimited reason token equals concept name",
            "candidate_minimum": 3,
            "rank_order": [
                "limit_times_desc",
                "limit_up_suc_rate_desc",
                "seal_strength_desc",
                "amount_desc",
                "vt_symbol_asc",
            ],
            "entry_depths_pct": list(ENTRY_DEPTHS_PCT),
            "entry": "next-session pre-open limit order anchored to source close",
            "exit": "entry-plus-one first sellable close",
            "cost_multiplier": [1.0, 2.0],
        },
        "coverage": coverage,
        "depth_metrics": _records(depth_metrics),
        "block_metrics": _records(block_metrics),
        "regime_diagnostics": _records(
            regime_metrics if regime_metrics is not None else pd.DataFrame()
        ),
        "decision": decision,
        "input_fingerprints": input_fingerprints,
        "limitations": [
            "event reasons are an incomplete, non-random subset of concept members",
            "recognition rank is not strict membership Top3",
            "daily low proves a pre-open limit order was marketable but does not reconstruct queue priority",
            "historical security status remains reconstructed rather than strict",
            "outer holdout and formal cash compounding remain locked",
        ],
        "next_stage": "strict_point_in_time_top3_retest",
    }


def render_event_falsification_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_event_falsification_markdown(report: dict[str, Any]) -> str:
    split = report["date_split"]
    coverage = report["coverage"]
    lines = [
        "# AlphaAgent 低吸事件认可开发段反证",
        "",
        f"协议：`{report['protocol_version']}`  ",
        f"证据：`{report['evidence_level']}`  ",
        f"结论：`{report['overall_conclusion']}`  ",
        "正式绩效：`null`；外层留出价格读取：`false`",
        "",
        "## Scope",
        "",
        f"- 发现段：`{split['discovery_start']}..{split['discovery_end']}`。",
        f"- 事件可用日：`{split['event_available_dates']}`，固定时间块：`{split['event_blocks']}`。",
        f"- 有原因事件：`{coverage.get('event_rows_with_reason', 0)}`；精确关系："
        f"`{coverage.get('exact_reason_relations', 0)}`。",
        f"- 合格认可概念日：`{coverage.get('eligible_recognition_concept_days', 0)}`；"
        f"候选：`{coverage.get('recognition_candidates', 0)}`。",
        "- 当前成员读取：`0`；该 cohort 不是完整成员 Top3。",
        "",
        "## Depth Metrics",
        "",
        "| Discount | Orders | Closed | Fill | Win | Mean | Median | PF | Tail 5% | Positive blocks | Double-cost mean | Strict retest |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for metric in report["depth_metrics"]:
        lines.append(
            f"| {metric['entry_depth_pct']:.0f}% | {metric['candidate_orders']} | "
            f"{metric['closed_trades']} | {_pct(metric['fill_rate_pct'])} | "
            f"{_pct(metric['win_rate_pct'])} | {_pct(metric['mean_net_return_pct'])} | "
            f"{_pct(metric['median_net_return_pct'])} | {_number(metric['profit_factor'])} | "
            f"{_pct(metric['tail_5pct'])} | {metric['positive_blocks']}/5 | "
            f"{_pct(metric['double_cost_mean_net_return_pct'])} | "
            f"{'yes' if metric['qualified_for_strict_retest'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Market Context Diagnostic",
            "",
            "| Discount | Context | Days | Closed | Win | Mean | PF | Double-cost mean | Positive blocks | 20d/30n |",
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for metric in report["regime_diagnostics"]:
        lines.append(
            f"| {metric['entry_depth_pct']:.0f}% | `{metric['regime_key']}` | "
            f"{metric['source_days']} | {metric['closed_trades']} | "
            f"{_pct(metric['win_rate_pct'])} | {_pct(metric['mean_net_return_pct'])} | "
            f"{_number(metric['profit_factor'])} | "
            f"{_pct(metric['double_cost_mean_net_return_pct'])} | "
            f"{metric['positive_time_blocks']}/{metric['observed_time_blocks']} | "
            f"{'yes' if metric['material_days_at_least_20'] and metric['sample_at_least_30'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "本报告只能否定或提名严格复测方向。事件原因不是完整概念成员，认可排名不是正式",
            "Top3；没有读取外层留出，也没有计算 10 万元正式现金复利或选择生产规则。",
            "",
        ]
    )
    return "\n".join(lines)


def _execute_candidate_depth(
    candidate: dict[str, Any],
    *,
    depth: float,
    calendar: tuple[date, ...],
    bar_index: dict[tuple[str, date], Any],
    cost_multiplier: float,
    initial_cash: float,
) -> dict[str, Any]:
    entry_date = _as_date(candidate["entry_date"])
    source_date = _as_date(candidate["source_date"])
    symbol = str(candidate["vt_symbol"])
    base = {
        "event_id": int(candidate["event_id"]),
        "source_date": source_date,
        "entry_date": entry_date,
        "planned_exit_date": _next_date(calendar, entry_date),
        "actual_exit_date": None,
        "sector_id": str(candidate["sector_id"]),
        "concept_name": str(candidate["concept_name"]),
        "cycle_id": str(candidate["cycle_id"]),
        "vt_symbol": symbol,
        "recognition_rank": int(candidate["recognition_rank"]),
        "entry_depth_pct": float(depth),
        "limit_order_price": None,
        "entry_price_raw": None,
        "entry_price": None,
        "exit_price_raw": None,
        "exit_price": None,
        "volume": 0,
        "buy_fee": None,
        "sell_fee": None,
        "total_fees": None,
        "net_return_pct": None,
        "status": None,
        "reason": None,
        "cost_multiplier": float(cost_multiplier),
        "active_direction": str(candidate.get("active_direction") or "UNKNOWN"),
        "danger_state": str(candidate.get("danger_state") or "UNKNOWN"),
        "market_phase": str(candidate.get("market_phase") or "UNKNOWN"),
        "evidence_level": EVIDENCE_LEVEL,
    }
    signal_close = float(candidate["signal_close"])
    limit_order = signal_close * (1.0 - depth / 100.0)
    base["limit_order_price"] = limit_order
    entry_bar = bar_index.get((symbol, entry_date))
    if entry_bar is None or float(entry_bar.volume or 0) <= 0:
        base.update(status="rejected", reason="entry_bar_unavailable")
        return base
    entry_open = float(entry_bar.open_price)
    entry_low = float(entry_bar.low_price)
    if entry_open <= limit_order:
        raw_entry = entry_open
    elif entry_low <= limit_order:
        raw_entry = limit_order
    else:
        base.update(status="not_filled", reason="limit_not_touched")
        return base

    buy = cash_ledger.calculate_buy_execution(
        raw_price=raw_entry,
        cash=initial_cash,
        target_cash=initial_cash,
        commission_rate=COMMISSION_RATE * cost_multiplier,
        slippage_bps=SLIPPAGE_BPS * cost_multiplier,
        lot_size=LOT_SIZE,
        minimum_commission=MINIMUM_COMMISSION * cost_multiplier,
        transfer_fee_rate=TRANSFER_FEE_RATE * cost_multiplier,
        max_price=limit_order,
    )
    if buy.volume <= 0:
        base.update(status="rejected", reason="insufficient_cash")
        return base
    base.update(
        entry_price_raw=raw_entry,
        entry_price=buy.price,
        volume=buy.volume,
        buy_fee=buy.fee,
    )

    planned_exit = base["planned_exit_date"]
    if planned_exit is None:
        base.update(status="unclosed", reason="missing_exit_session")
        return base
    exit_bar = None
    actual_exit = None
    exit_position = bisect.bisect_left(calendar, planned_exit)
    for candidate_exit in calendar[exit_position:]:
        row = bar_index.get((symbol, candidate_exit))
        if row is None or float(row.volume or 0) <= 0:
            continue
        previous_close = float(row.previous_close) if pd.notna(row.previous_close) else None
        if previous_close and _is_one_price_limit_down(row, previous_close):
            continue
        exit_bar = row
        actual_exit = candidate_exit
        break
    if exit_bar is None or actual_exit is None:
        base.update(status="unclosed", reason="no_sellable_exit_in_discovery")
        return base

    sell = cash_ledger.calculate_sell_execution(
        raw_price=float(exit_bar.close_price),
        volume=buy.volume,
        cost_price=buy.price,
        commission_rate=COMMISSION_RATE * cost_multiplier,
        stamp_tax_rate=STAMP_TAX_RATE * cost_multiplier,
        slippage_bps=SLIPPAGE_BPS * cost_multiplier,
        minimum_commission=MINIMUM_COMMISSION * cost_multiplier,
        transfer_fee_rate=TRANSFER_FEE_RATE * cost_multiplier,
    )
    final_cash = buy.cash_after + sell.cash_delta
    base.update(
        actual_exit_date=actual_exit,
        exit_price_raw=float(exit_bar.close_price),
        exit_price=sell.price,
        sell_fee=sell.fee,
        total_fees=buy.fee + sell.fee,
        net_return_pct=(final_cash / initial_cash - 1.0) * 100.0,
        status="closed",
        reason=None,
    )
    return base


def _normalize_database_events(
    rows: list[Any],
    *,
    discovery_end: date,
) -> pd.DataFrame:
    records = []
    for row in rows:
        raw = dict(row["raw"] or {})
        reason = str(raw.get("涨停原因") or raw.get("reason_type") or "").strip()
        if not reason:
            continue
        source_date = pd.to_datetime(str(row["event_date"])[:8], format="%Y%m%d").date()
        if source_date > discovery_end:
            raise ValueError("event query crossed the discovery boundary")
        records.append(
            {
                "event_id": int(row["id"]),
                "source_date": source_date,
                "vt_symbol": str(row["vt_symbol"]),
                "stock_name": str(raw.get("名称") or raw.get("name") or ""),
                "reason": reason,
                "limit_times": raw.get("连板数", raw.get("limit_times")),
                "limit_up_suc_rate": raw.get(
                    "近一年封板率", raw.get("limit_up_suc_rate")
                ),
                "fd_amount": raw.get("封板资金", raw.get("fd_amount")),
                "float_market_cap": raw.get("流通市值"),
                "amount": raw.get("成交额", raw.get("amount")),
            }
        )
    return pd.DataFrame(records, columns=EVENT_COLUMNS)


def load_timing_context() -> pd.DataFrame:
    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import session_scope

    with session_scope() as session:
        panel = session.execute(
            select(schema.market_timing_panel.c.panel)
            .order_by(schema.market_timing_panel.c.computed_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    rows = []
    for item in (panel or {}).get("timing_series") or []:
        rows.append(
            {
                "source_date": pd.Timestamp(item.get("date")).date(),
                "active_direction": str(item.get("active_direction") or "UNKNOWN"),
                "danger_state": str(item.get("danger_state") or "UNKNOWN"),
                "market_phase": str(item.get("phase") or "UNKNOWN"),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "source_date",
            "active_direction",
            "danger_state",
            "market_phase",
        ],
    )


def _prepare_bars(stock_bars: pd.DataFrame) -> pd.DataFrame:
    bars = stock_bars.copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.date
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock bar identity must be unique")
    for column in ("open_price", "high_price", "low_price", "close_price", "volume"):
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    return bars.sort_values(["vt_symbol", "trade_date"], kind="stable").reset_index(
        drop=True
    )


def _normalized_calendar(values: tuple[date, ...] | list[date]) -> tuple[date, ...]:
    return tuple(sorted(set(pd.to_datetime(values, errors="raise").date)))


def _next_session_map(calendar: tuple[date, ...]) -> dict[date, date | None]:
    return {
        value: calendar[index + 1] if index + 1 < len(calendar) else None
        for index, value in enumerate(calendar)
    }


def _next_date(calendar: tuple[date, ...], value: date) -> date | None:
    position = bisect.bisect_right(calendar, value)
    return calendar[position] if position < len(calendar) else None


def _as_date(value: Any) -> date:
    return pd.Timestamp(value).date()


def _is_main_board_symbol(vt_symbol: Any) -> bool:
    text = str(vt_symbol).upper()
    symbol, _, exchange = text.partition(".")
    if exchange == "SSE":
        return symbol.startswith(("600", "601", "603", "605"))
    if exchange == "SZSE":
        return symbol.startswith(("000", "001", "002", "003"))
    return False


def _is_excluded_event_name(value: Any) -> bool:
    text = str(value or "").strip().upper()
    return "ST" in text or "退市" in text or text.startswith("退")


def _is_one_price_limit_down(row: Any, previous_close: float) -> bool:
    limit_down = previous_close * 0.90
    tolerance = max(0.01, limit_down * 0.0015)
    return (
        float(row.high_price) <= limit_down + tolerance
        and float(row.close_price) <= limit_down + tolerance
    )


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")


def _profit_factor(values: pd.Series) -> float | None:
    if values.empty:
        return None
    gains = float(values.loc[values > 0].sum())
    losses = abs(float(values.loc[values < 0].sum()))
    if losses == 0:
        return None if gains == 0 else math.inf
    return gains / losses


def _win_rate_pct(values: pd.Series) -> float | None:
    return float(values.gt(0).mean() * 100.0) if len(values) else None


def _mean(values: pd.Series) -> float | None:
    return float(values.mean()) if len(values) else None


def _median(values: pd.Series) -> float | None:
    return float(values.median()) if len(values) else None


def _quantile(values: pd.Series, quantile: float) -> float | None:
    return float(values.quantile(quantile)) if len(values) else None


def _maximum_group_share(frame: pd.DataFrame, labels: pd.Series) -> float | None:
    if frame.empty:
        return None
    return float(labels.value_counts(dropna=False).max() / len(frame))


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records = []
    for row in frame.to_dict("records"):
        records.append({key: _json_value(value) for key, value in row.items()})
    return records


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (pd.Timestamp, date)):
        return pd.Timestamp(value).date().isoformat()
    return value


def _pct(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}%"


def _number(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}"


def _empty_candidates() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_id",
            "source_date",
            "entry_date",
            "planned_exit_date",
            "sector_id",
            "concept_name",
            "cycle_id",
            "vt_symbol",
            "stock_name",
            "recognition_rank",
            "relative_percentile",
            "limit_times",
            "limit_up_suc_rate",
            "seal_strength",
            "amount",
            "signal_close",
            "prior_sessions",
            "evidence_level",
        ]
    )


def _empty_outcomes() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_id",
            "source_date",
            "entry_date",
            "planned_exit_date",
            "actual_exit_date",
            "sector_id",
            "concept_name",
            "cycle_id",
            "vt_symbol",
            "recognition_rank",
            "entry_depth_pct",
            "limit_order_price",
            "entry_price_raw",
            "entry_price",
            "exit_price_raw",
            "exit_price",
            "volume",
            "buy_fee",
            "sell_fee",
            "total_fees",
            "net_return_pct",
            "status",
            "reason",
            "cost_multiplier",
            "active_direction",
            "danger_state",
            "market_phase",
            "evidence_level",
        ]
    )
