"""Return-independent concept main-rise cycle research for low suction V2."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd

from .research_protocol import (
    DataFingerprint,
    ProtocolSplit,
    ResearchProtocol,
    build_protocol_split,
    default_protocol,
    fingerprint_frame,
    protocol_hash,
)

MARKET_BENCHMARK_SYMBOLS = (
    "000300.SSE",
    "000905.SSE",
    "000852.SSE",
)
FROZEN_MAIN_RISE_DEFINITION = "breakout_trend"
OUTCOME_COLUMNS = frozenset(
    {
        "net_return_pct",
        "net_log_return",
        "mfe_pct",
        "mae_pct",
        "entry_price",
        "exit_price",
    }
)


class CycleDefinition(StrEnum):
    TREND_ORDER = "trend_order"
    BREAKOUT_TREND = "breakout_trend"
    RELATIVE_TREND = "relative_trend"


@dataclass(frozen=True)
class CycleSelectionResult:
    status: str
    selected_definition: str | None
    fold_winners: tuple[str | None, ...]
    win_counts: tuple[tuple[str, int], ...]
    fold_metrics: pd.DataFrame
    discovery_metrics: pd.DataFrame


@dataclass(frozen=True)
class CycleResearchInputs:
    concept_bars: pd.DataFrame
    market_returns: pd.DataFrame
    split: ProtocolSplit
    reliable_dates: tuple[date, ...]
    input_fingerprint: str
    component_fingerprints: tuple[tuple[str, DataFingerprint], ...]


def build_market_returns(
    benchmark_bars: pd.DataFrame,
    *,
    research_dates: Sequence[date],
) -> pd.DataFrame:
    required = {"trade_date", "vt_symbol", "close_price"}
    missing = sorted(required - set(benchmark_bars))
    if missing:
        raise ValueError(f"missing market benchmark columns: {', '.join(missing)}")

    frame = benchmark_bars.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    frame["vt_symbol"] = frame["vt_symbol"].astype(str)
    frame["close_price"] = pd.to_numeric(frame["close_price"], errors="raise")
    if frame.duplicated(["trade_date", "vt_symbol"]).any():
        raise ValueError("market benchmark identity must be unique")
    if frame["close_price"].isna().any() or (frame["close_price"] <= 0).any():
        raise ValueError("market benchmark closes must be positive")

    required_symbols = set(MARKET_BENCHMARK_SYMBOLS)
    missing_symbols = sorted(required_symbols - set(frame["vt_symbol"]))
    if missing_symbols:
        raise ValueError(f"missing market benchmark symbols: {', '.join(missing_symbols)}")
    pivot = (
        frame.loc[frame["vt_symbol"].isin(required_symbols)]
        .pivot(index="trade_date", columns="vt_symbol", values="close_price")
        .sort_index()
        .loc[:, list(MARKET_BENCHMARK_SYMBOLS)]
    )
    research_index = pd.DatetimeIndex(pd.to_datetime(tuple(research_dates))).normalize()
    missing_dates = research_index.difference(pivot.dropna().index)
    if len(missing_dates):
        raise ValueError("market benchmarks do not cover every research date")

    daily_return = pivot.pct_change(fill_method=None).mean(axis=1, skipna=False)
    market_return_10d = (1.0 + daily_return).rolling(10, min_periods=10).apply(
        np.prod,
        raw=True,
    ) - 1.0
    return pd.DataFrame(
        {
            "trade_date": pivot.index,
            "market_daily_return": daily_return.to_numpy(),
            "market_return_10d": market_return_10d.to_numpy(),
            "research_date_valid": pivot.index.isin(research_index),
        }
    ).reset_index(drop=True)


def load_cycle_research_calendar(
    *,
    as_of_date: date | None = None,
) -> tuple[date, ...]:
    """Load dates with complete canonical concepts and all frozen benchmarks."""

    from sqlalchemy import func, select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import session_scope
    from alphaagent.server.services.completed_session import completed_daily_bar_cutoff

    from .concept_index_coverage import (
        CANONICAL_CONCEPT_INDEX_SOURCE,
        build_dynamic_concept_coverage,
    )
    from .contracts import CONCEPT_SECTOR_TYPES

    completed_cutoff = completed_daily_bar_cutoff()
    cutoff = min(as_of_date, completed_cutoff) if as_of_date else completed_cutoff
    with session_scope() as session:
        count_rows = session.execute(
            select(
                schema.sector_daily_bars.c.trade_date,
                func.count(func.distinct(schema.sector_daily_bars.c.sector_id)),
            )
            .select_from(
                schema.sector_daily_bars.join(
                    schema.sectors,
                    schema.sector_daily_bars.c.sector_id == schema.sectors.c.id,
                )
            )
            .where(
                schema.sectors.c.type.in_(CONCEPT_SECTOR_TYPES),
                schema.sector_daily_bars.c.source == CANONICAL_CONCEPT_INDEX_SOURCE,
                schema.sector_daily_bars.c.trade_date <= cutoff,
            )
            .group_by(schema.sector_daily_bars.c.trade_date)
            .order_by(schema.sector_daily_bars.c.trade_date)
        ).all()
        bound_rows = session.execute(
            select(
                schema.sector_daily_bars.c.sector_id,
                func.min(schema.sector_daily_bars.c.trade_date),
                func.max(schema.sector_daily_bars.c.trade_date),
            )
            .select_from(
                schema.sector_daily_bars.join(
                    schema.sectors,
                    schema.sector_daily_bars.c.sector_id == schema.sectors.c.id,
                )
            )
            .where(
                schema.sectors.c.type.in_(CONCEPT_SECTOR_TYPES),
                schema.sector_daily_bars.c.source == CANONICAL_CONCEPT_INDEX_SOURCE,
                schema.sector_daily_bars.c.trade_date <= cutoff,
            )
            .group_by(schema.sector_daily_bars.c.sector_id)
            .order_by(schema.sector_daily_bars.c.sector_id)
        ).all()
        benchmark_rows = session.execute(
            select(
                schema.stock_daily_bars.c.trade_date,
                func.count(func.distinct(schema.stock_daily_bars.c.vt_symbol)),
            )
            .where(
                schema.stock_daily_bars.c.vt_symbol.in_(MARKET_BENCHMARK_SYMBOLS),
                schema.stock_daily_bars.c.trade_date <= cutoff,
            )
            .group_by(schema.stock_daily_bars.c.trade_date)
            .order_by(schema.stock_daily_bars.c.trade_date)
        ).all()

    dynamic_coverage = build_dynamic_concept_coverage(
        trading_dates=tuple(row[0] for row in count_rows),
        count_rows=tuple((row[0], int(row[1] or 0)) for row in count_rows),
        bounds=tuple((str(row[0]), row[1], row[2]) for row in bound_rows),
    )
    benchmark_dates = {
        row[0]
        for row in benchmark_rows
        if int(row[1] or 0) == len(MARKET_BENCHMARK_SYMBOLS)
    }
    return tuple(
        row.trade_date
        for row in dynamic_coverage
        if row.qualifies and row.trade_date in benchmark_dates
    )


def load_cycle_research_inputs(
    protocol: ResearchProtocol | None = None,
    *,
    as_of_date: date | None = None,
) -> CycleResearchInputs:
    """Read discovery values only; outer holdout prices never enter this process."""

    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    from .concept_index_coverage import CANONICAL_CONCEPT_INDEX_SOURCE
    from .contracts import CONCEPT_SECTOR_TYPES

    selected_protocol = protocol or default_protocol()
    reliable_dates = load_cycle_research_calendar(as_of_date=as_of_date)
    split = build_protocol_split(reliable_dates, selected_protocol)
    discovery_dates = split.discovery_dates

    concept_statement = (
        select(
            schema.sector_daily_bars.c.sector_id,
            schema.sectors.c.name.label("concept_name"),
            schema.sector_daily_bars.c.trade_date,
            schema.sector_daily_bars.c.close_price,
            schema.sector_daily_bars.c.source,
        )
        .select_from(
            schema.sector_daily_bars.join(
                schema.sectors,
                schema.sector_daily_bars.c.sector_id == schema.sectors.c.id,
            )
        )
        .where(
            schema.sectors.c.type.in_(CONCEPT_SECTOR_TYPES),
            schema.sector_daily_bars.c.source == CANONICAL_CONCEPT_INDEX_SOURCE,
            schema.sector_daily_bars.c.trade_date.in_(discovery_dates),
        )
        .order_by(
            schema.sector_daily_bars.c.sector_id,
            schema.sector_daily_bars.c.trade_date,
        )
    )
    benchmark_statement = (
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.source,
        )
        .where(
            schema.stock_daily_bars.c.vt_symbol.in_(MARKET_BENCHMARK_SYMBOLS),
            schema.stock_daily_bars.c.trade_date.in_(discovery_dates),
        )
        .order_by(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
        )
    )
    engine = get_engine()
    concept_bars = pd.read_sql(
        concept_statement,
        engine,
        parse_dates=["trade_date"],
    )
    benchmark_bars = pd.read_sql(
        benchmark_statement,
        engine,
        parse_dates=["trade_date"],
    )
    if concept_bars.empty:
        raise ValueError("no canonical concept bars in the V2 discovery window")

    market_returns = build_market_returns(
        benchmark_bars,
        research_dates=discovery_dates,
    )
    concept_fingerprint = fingerprint_frame(
        concept_bars,
        identity_columns=("trade_date", "sector_id"),
    )
    benchmark_fingerprint = fingerprint_frame(
        benchmark_bars,
        identity_columns=("trade_date", "vt_symbol"),
    )
    components = (
        ("canonical_concept_bars", concept_fingerprint),
        ("market_benchmark_bars", benchmark_fingerprint),
    )
    fingerprint_payload = {
        "protocol_hash": protocol_hash(selected_protocol),
        "discovery_start": discovery_dates[0].isoformat(),
        "discovery_end": discovery_dates[-1].isoformat(),
        "components": {
            name: fingerprint.digest for name, fingerprint in components
        },
    }
    combined_digest = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return CycleResearchInputs(
        concept_bars=concept_bars,
        market_returns=market_returns,
        split=split,
        reliable_dates=reliable_dates,
        input_fingerprint=f"sha256:{combined_digest}",
        component_fingerprints=components,
    )


def build_cycle_candidates(
    concept_bars: pd.DataFrame,
    market_returns: pd.DataFrame,
) -> pd.DataFrame:
    prohibited = OUTCOME_COLUMNS & set(concept_bars)
    if prohibited:
        raise ValueError(f"outcome columns are not allowed: {sorted(prohibited)}")

    frame = _prepare_concept_bars(concept_bars, market_returns)
    indicator_group = frame.groupby(
        ["sector_id", "history_segment"],
        sort=False,
        observed=True,
    )
    frame["ma10"] = indicator_group["close_price"].transform(
        lambda values: values.rolling(10, min_periods=10).mean()
    )
    frame["ma20"] = indicator_group["close_price"].transform(
        lambda values: values.rolling(20, min_periods=20).mean()
    )
    frame["ma10_shift_5"] = indicator_group["ma10"].shift(5)
    frame["ma20_shift_5"] = indicator_group["ma20"].shift(5)
    frame["high20"] = indicator_group["close_price"].transform(
        lambda values: values.rolling(20, min_periods=20).max()
    )
    frame["concept_return_10d"] = indicator_group["close_price"].pct_change(
        10,
        fill_method=None,
    )
    frame["relative_10d"] = (
        frame["concept_return_10d"] - frame["market_return_10d"]
    )
    frame["relative_percentile"] = frame.groupby(
        "trade_date",
        sort=False,
        observed=True,
    )["relative_10d"].rank(method="average", pct=True)

    trend_order = (
        (frame["close_price"] > frame["ma10"])
        & (frame["ma10"] > frame["ma20"])
        & (frame["ma10"] > frame["ma10_shift_5"])
        & (frame["ma20"] > frame["ma20_shift_5"])
        & frame["research_date_valid"]
    ).fillna(False)
    definitions = {
        CycleDefinition.TREND_ORDER: trend_order,
        CycleDefinition.BREAKOUT_TREND: (
            trend_order & (frame["close_price"] >= frame["high20"])
        ).fillna(False),
        CycleDefinition.RELATIVE_TREND: (
            trend_order & (frame["relative_percentile"] >= 0.80)
        ).fillna(False),
    }
    candidates = []
    for definition, qualifies in definitions.items():
        candidate = frame.assign(
            definition=definition.value,
            qualifies=qualifies.astype(bool),
            entry_qualifies=qualifies.astype(bool),
            sustain_qualifies=trend_order.astype(bool),
        )
        candidates.append(apply_three_day_hysteresis(candidate))
    return (
        pd.concat(candidates, ignore_index=True)
        .sort_values(["definition", "sector_id", "trade_date"], kind="stable")
        .reset_index(drop=True)
    )


def apply_three_day_hysteresis(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"sector_id", "trade_date", "definition", "qualifies"}
    missing = sorted(required - set(frame))
    if missing:
        raise ValueError(f"missing cycle columns: {', '.join(missing)}")

    result = frame.copy()
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.normalize()
    if "history_segment" not in result:
        result["history_segment"] = 0
    identity = ["definition", "sector_id", "history_segment", "trade_date"]
    if result.duplicated(identity).any():
        raise ValueError("cycle qualification identity must be unique")
    result = result.sort_values(identity, kind="stable").reset_index(drop=True)
    entry_qualifies = result.get("entry_qualifies", result["qualifies"]).astype(bool)
    sustain_qualifies = result.get("sustain_qualifies", result["qualifies"]).astype(bool)
    if (entry_qualifies & ~sustain_qualifies).any():
        raise ValueError("cycle entry must also satisfy the common sustain condition")

    row_count = len(result)
    in_cycle = np.zeros(row_count, dtype=bool)
    miss_count = np.zeros(row_count, dtype=np.int64)
    cycle_id: list[str | None] = [None] * row_count
    cycle_start: list[pd.Timestamp | None] = [None] * row_count
    cycle_days: list[int | None] = [None] * row_count
    cycle_ended = np.zeros(row_count, dtype=bool)
    ended_cycle_id: list[str | None] = [None] * row_count
    completed_cycle_days: list[int | None] = [None] * row_count
    completed_qualifying_days: list[int | None] = [None] * row_count
    false_start = pd.array([pd.NA] * row_count, dtype="boolean")

    group_columns = ["definition", "sector_id", "history_segment"]
    for _, group in result.groupby(group_columns, sort=False, observed=True):
        active = False
        active_cycle_id: str | None = None
        active_start: pd.Timestamp | None = None
        active_days = 0
        qualifying_days = 0
        misses = 0

        for row_index in group.index:
            enters = bool(entry_qualifies.at[row_index])
            sustains = bool(sustain_qualifies.at[row_index])
            if not active and not enters:
                continue
            if not active:
                active = True
                active_start = result.at[row_index, "trade_date"]
                active_cycle_id = _cycle_id(result.loc[row_index], active_start)
                active_days = 1
                qualifying_days = 1
                misses = 0
            elif sustains:
                active_days += 1
                qualifying_days += 1
                misses = 0
            else:
                misses += 1
                if misses >= 3:
                    cycle_ended[row_index] = True
                    miss_count[row_index] = misses
                    ended_cycle_id[row_index] = active_cycle_id
                    completed_cycle_days[row_index] = active_days
                    completed_qualifying_days[row_index] = qualifying_days
                    false_start[row_index] = qualifying_days < 3
                    active = False
                    active_cycle_id = None
                    active_start = None
                    active_days = 0
                    qualifying_days = 0
                    misses = 0
                    continue
                active_days += 1

            in_cycle[row_index] = True
            miss_count[row_index] = misses
            cycle_id[row_index] = active_cycle_id
            cycle_start[row_index] = active_start
            cycle_days[row_index] = active_days

    result["in_cycle"] = in_cycle
    result["miss_count"] = miss_count
    result["cycle_id"] = pd.Series(cycle_id, dtype="string")
    result["cycle_start"] = pd.to_datetime(cycle_start)
    result["cycle_days"] = pd.array(cycle_days, dtype="Int64")
    result["cycle_ended"] = cycle_ended
    result["ended_cycle_id"] = pd.Series(ended_cycle_id, dtype="string")
    result["completed_cycle_days"] = pd.array(completed_cycle_days, dtype="Int64")
    result["completed_qualifying_days"] = pd.array(
        completed_qualifying_days,
        dtype="Int64",
    )
    result["false_start"] = false_start
    return result


def evaluate_cycle_definitions(
    candidates: pd.DataFrame,
    *,
    evaluation_dates: Sequence[date],
) -> pd.DataFrame:
    required = {
        "definition",
        "sector_id",
        "trade_date",
        "in_cycle",
        "cycle_id",
        "cycle_ended",
        "completed_cycle_days",
        "false_start",
    }
    missing = sorted(required - set(candidates))
    if missing:
        raise ValueError(f"missing cycle evaluation columns: {', '.join(missing)}")

    frame = candidates.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    if "calendar_position" not in frame:
        positions = {
            trade_date: index
            for index, trade_date in enumerate(sorted(frame["trade_date"].unique()))
        }
        frame["calendar_position"] = frame["trade_date"].map(positions)
    identity = ["definition", "sector_id", "calendar_position"]
    if frame.duplicated(identity).any():
        raise ValueError("cycle evaluation identity must be unique")

    allowed_dates = pd.DatetimeIndex(pd.to_datetime(tuple(evaluation_dates))).normalize()
    evaluation_mask = frame["trade_date"].isin(allowed_dates)
    active_states = frame.loc[evaluation_mask & frame["in_cycle"]].copy()
    starts = active_states.loc[active_states["cycle_days"].eq(1)].copy()
    started_cycle_ids = set(starts["cycle_id"].dropna().astype(str))
    ended = frame.loc[
        evaluation_mask
        & frame["cycle_ended"]
        & frame["ended_cycle_id"].astype("string").isin(started_cycle_ids)
    ].copy()
    definitions = tuple(sorted(frame["definition"].dropna().astype(str).unique()))

    persistence = {
        horizon: _persistence_rows(frame, starts, allowed_dates, horizon=horizon)
        for horizon in (1, 3)
    }
    rows = []
    for definition in definitions:
        definition_active = active_states.loc[active_states["definition"] == definition]
        definition_starts = starts.loc[starts["definition"] == definition]
        definition_ended = ended.loc[ended["definition"] == definition]
        next_day = persistence[1].loc[persistence[1]["definition"] == definition]
        three_day = persistence[3].loc[persistence[3]["definition"] == definition]
        monthly = three_day.assign(
            month=three_day["trade_date"].dt.to_period("M").astype(str)
        ).groupby("month", observed=True)["persists"].mean()
        rows.append(
            {
                "definition": definition,
                "events": int(definition_starts["cycle_id"].nunique()),
                "active_state_days": int(len(definition_active)),
                "eligible_next_day_states": int(next_day["persists"].notna().sum()),
                "eligible_three_day_states": int(three_day["persists"].notna().sum()),
                "next_day_persistence_rate": _mean_or_nan(next_day["persists"]),
                "three_day_persistence_rate": _mean_or_nan(three_day["persists"]),
                "completed_cycles": int(len(definition_ended)),
                "false_start_rate": _mean_or_nan(
                    definition_ended["false_start"].astype("Float64")
                ),
                "median_cycle_days": _median_or_nan(
                    definition_ended["completed_cycle_days"]
                ),
                "evaluation_months": int(monthly.notna().sum()),
                "monthly_three_day_persistence_std": (
                    float(monthly.std(ddof=0)) if monthly.notna().any() else np.nan
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("definition", kind="stable").reset_index(drop=True)


def choose_stable_cycle_definition(
    fold_winners: Sequence[str | CycleDefinition | None],
    *,
    minimum_wins: int = 3,
) -> CycleDefinition | None:
    if minimum_wins < 1:
        raise ValueError("minimum_wins must be positive")
    counts = Counter(str(winner) for winner in fold_winners if winner is not None)
    eligible = [
        definition
        for definition, count in counts.items()
        if count >= minimum_wins
    ]
    if len(eligible) != 1:
        return None
    return CycleDefinition(eligible[0])


def select_cycle_definition(
    candidates: pd.DataFrame,
    split: ProtocolSplit,
) -> CycleSelectionResult:
    candidate_dates = set(pd.to_datetime(candidates["trade_date"]).dt.date)
    if candidate_dates & set(split.holdout_dates):
        raise ValueError("locked holdout values must not be loaded during cycle selection")

    fold_frames = []
    fold_winners: list[str | None] = []
    for fold_number, fold in enumerate(split.rolling_folds, start=1):
        metrics = evaluate_cycle_definitions(
            candidates,
            evaluation_dates=fold.validation_dates,
        )
        winner = _winning_definition(metrics)
        fold_winners.append(winner)
        fold_frames.append(
            metrics.assign(
                fold=fold_number,
                fold_winner=metrics["definition"].eq(winner),
            )
        )

    selected = choose_stable_cycle_definition(fold_winners)
    counts = Counter(winner for winner in fold_winners if winner is not None)
    return CycleSelectionResult(
        status=(
            "selected_main_rise_definition"
            if selected is not None
            else "no_stable_main_rise_definition"
        ),
        selected_definition=selected.value if selected is not None else None,
        fold_winners=tuple(fold_winners),
        win_counts=tuple(sorted((str(key), value) for key, value in counts.items())),
        fold_metrics=pd.concat(fold_frames, ignore_index=True),
        discovery_metrics=evaluate_cycle_definitions(
            candidates,
            evaluation_dates=split.discovery_dates,
        ),
    )


def run_current_cycle_study(
    protocol: ResearchProtocol | None = None,
    *,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    selected_protocol = protocol or default_protocol()
    inputs = load_cycle_research_inputs(
        selected_protocol,
        as_of_date=as_of_date,
    )
    candidates = build_cycle_candidates(inputs.concept_bars, inputs.market_returns)
    selection = select_cycle_definition(candidates, inputs.split)
    return build_cycle_study_report(inputs, selection, selected_protocol)


def build_cycle_study_report(
    inputs: CycleResearchInputs,
    selection: CycleSelectionResult,
    protocol: ResearchProtocol,
) -> dict[str, Any]:
    split = inputs.split
    return {
        "protocol_version": protocol.version,
        "protocol_hash": protocol_hash(protocol),
        "overall_conclusion": "blocked_by_data_quality",
        "formal_metrics": None,
        "cycle_stage": "completed",
        "cycle_selection_status": selection.status,
        "selected_definition": selection.selected_definition,
        "stock_trade_outcomes_read": False,
        "holdout_price_values_read": False,
        "selection_criterion": [
            "three_day_persistence_rate_desc",
            "false_start_rate_asc",
            "median_cycle_days_desc",
            "definition_name_asc",
            "winner_requires_at_least_three_of_five_folds",
        ],
        "false_start_definition": (
            "completed cycle with fewer than three common trend-sustain days"
        ),
        "cycle_contract": {
            "version": protocol.cycle_contract_version,
            "trend_order": "enter when the common trend condition first becomes true",
            "breakout_trend": "enter when trend order and a 20-day closing high are both true",
            "relative_trend": "enter when trend order and same-day top-20% concept strength are both true",
            "common_sustain": "trend_order",
            "common_exit": "third consecutive day without trend_order; effective that day",
            "persistence_unit": "one observation per concept cycle start",
        },
        "market_benchmark": {
            "symbols": list(MARKET_BENCHMARK_SYMBOLS),
            "method": "daily_equal_weight_rebalanced_composite",
            "note": (
                "relative_trend ranks concepts cross-sectionally, so subtracting the "
                "same market return does not change their percentile order"
            ),
        },
        "date_split": {
            "reliable_dates": len(inputs.reliable_dates),
            "reliable_start": inputs.reliable_dates[0].isoformat(),
            "reliable_end": inputs.reliable_dates[-1].isoformat(),
            "discovery_dates": len(split.discovery_dates),
            "discovery_start": split.discovery_dates[0].isoformat(),
            "discovery_end": split.discovery_dates[-1].isoformat(),
            "holdout_dates": len(split.holdout_dates),
            "holdout_start": split.holdout_dates[0].isoformat(),
            "holdout_end": split.holdout_dates[-1].isoformat(),
        },
        "input_rows": {
            "canonical_concept_bars": int(len(inputs.concept_bars)),
            "concepts": int(inputs.concept_bars["sector_id"].nunique()),
            "market_benchmark_bars": int(
                len(inputs.market_returns) * len(MARKET_BENCHMARK_SYMBOLS)
            ),
        },
        "input_fingerprint": inputs.input_fingerprint,
        "component_fingerprints": {
            name: fingerprint.as_dict()
            for name, fingerprint in inputs.component_fingerprints
        },
        "fold_winners": [
            {"fold": index, "definition": winner}
            for index, winner in enumerate(selection.fold_winners, start=1)
        ],
        "fold_win_counts": dict(selection.win_counts),
        "discovery_definition_metrics": _metric_records(
            selection.discovery_metrics
        ),
        "fold_definition_metrics": _metric_records(selection.fold_metrics),
        "next_stage": "strict_point_in_time_top3_identity_research",
        "next_stage_blockers": [
            "historical_concept_membership",
            "historical_security_status",
        ],
        "reproduce": (
            "docker compose exec -T alphaagent-api python -m "
            "alphaagent.server.services.low_suction.cli v2-cycle-study "
            "--format markdown"
        ),
    }


def render_cycle_study_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_cycle_study_markdown(report: dict[str, Any]) -> str:
    split = report["date_split"]
    lines = [
        "# AlphaAgent 低吸 V2 主升周期研究",
        "",
        f"协议：`{report['protocol_version']}`  ",
        f"周期阶段：`{report['cycle_selection_status']}`  ",
        f"冻结定义：`{report['selected_definition'] or '-'}`  ",
        "整体结论：`blocked_by_data_quality`，正式交易绩效：`null`",
        "",
        "本阶段只读取概念指数和宽基指数，不读取股票交易收益、低吸结果或锁定留出价格。",
        "三种方案只比较进入条件；进入后统一由 `trend_order` 续期，连续失效 3 日退出。",
        "持续率每个概念周期起点只计一次；假启动是共同趋势续期不足 3 日。",
        "次日持续率因三日退出迟滞机械性为 100%，只作审计，不参与排序。",
        "",
        "## Data Split",
        "",
        f"- 可靠日期：`{split['reliable_dates']}`，"
        f"`{split['reliable_start']}..{split['reliable_end']}`。",
        f"- 发现段：`{split['discovery_dates']}`，"
        f"`{split['discovery_start']}..{split['discovery_end']}`。",
        f"- 锁定留出：`{split['holdout_dates']}`，"
        f"`{split['holdout_start']}..{split['holdout_end']}`；只记录日期边界，未读取价格。",
        f"- 输入指纹：`{report['input_fingerprint']}`。",
        "",
        "## Discovery Metrics",
        "",
        "| Definition | Cycles | Active states | Next-day persistence | 3-day persistence | False starts | Median cycle days | Monthly stability std |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for metric in report["discovery_definition_metrics"]:
        lines.append(
            f"| `{metric['definition']}` | {metric['events']} | "
            f"{metric['active_state_days']} | "
            f"{_format_rate(metric['next_day_persistence_rate'])} | "
            f"{_format_rate(metric['three_day_persistence_rate'])} | "
            f"{_format_rate(metric['false_start_rate'])} | "
            f"{_format_number(metric['median_cycle_days'])} | "
            f"{_format_rate(metric['monthly_three_day_persistence_std'])} |"
        )

    lines.extend(
        [
            "",
            "## Rolling Selection",
            "",
            "| Fold | Winner |",
            "| ---: | --- |",
        ]
    )
    for item in report["fold_winners"]:
        lines.append(f"| {item['fold']} | `{item['definition'] or '-'}` |")
    win_counts = ", ".join(
        f"`{definition}`={count}"
        for definition, count in sorted(report["fold_win_counts"].items())
    )
    lines.extend(
        [
            "",
            f"折胜次数：{win_counts or '无'}。",
            "",
            "排序只使用周期起点的三日持续率、假启动率和周期长度；未使用任何个股低吸收益。",
            "",
            "## Boundary",
            "",
            "主升定义冻结后，下一阶段才是点时 Top3 身份研究。当前仍缺三年严格历史概念成员",
            "和历史证券状态，因此不能计算低吸胜率、复利、利润因子或最大回撤。",
            "",
            "## Reproduce",
            "",
            "```bash",
            str(report["reproduce"]),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _prepare_concept_bars(
    concept_bars: pd.DataFrame,
    market_returns: pd.DataFrame,
) -> pd.DataFrame:
    required_bars = {"sector_id", "trade_date", "close_price"}
    missing_bars = sorted(required_bars - set(concept_bars))
    if missing_bars:
        raise ValueError(f"missing concept bar columns: {', '.join(missing_bars)}")
    required_market = {"trade_date", "market_return_10d"}
    missing_market = sorted(required_market - set(market_returns))
    if missing_market:
        raise ValueError(f"missing market return columns: {', '.join(missing_market)}")

    market = market_returns.copy()
    market["trade_date"] = pd.to_datetime(market["trade_date"], errors="raise").dt.normalize()
    if market.duplicated("trade_date").any():
        raise ValueError("market return dates must be unique")
    market = market.sort_values("trade_date", kind="stable").reset_index(drop=True)
    market["calendar_position"] = np.arange(len(market), dtype=np.int64)
    if "research_date_valid" not in market:
        market["research_date_valid"] = True

    frame = concept_bars.copy()
    frame["sector_id"] = frame["sector_id"].astype(str)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    frame["close_price"] = pd.to_numeric(frame["close_price"], errors="raise")
    if frame.duplicated(["sector_id", "trade_date"]).any():
        raise ValueError("concept bar identity must be unique")
    if frame["close_price"].isna().any() or (frame["close_price"] <= 0).any():
        raise ValueError("concept close prices must be positive")

    market_columns = [
        "trade_date",
        "calendar_position",
        "market_return_10d",
        "research_date_valid",
    ]
    frame = frame.merge(
        market[market_columns],
        on="trade_date",
        how="left",
        validate="many_to_one",
    )
    if frame["calendar_position"].isna().any():
        raise ValueError("every concept bar date must exist in the market calendar")
    frame = frame.sort_values(["sector_id", "trade_date"], kind="stable").reset_index(drop=True)
    calendar_step = frame.groupby("sector_id", sort=False)["calendar_position"].diff()
    frame["calendar_gap"] = calendar_step.gt(1).fillna(False)
    frame["history_segment"] = (
        frame.groupby("sector_id", sort=False)["calendar_gap"].cumsum().astype(int)
    )
    frame["calendar_position"] = frame["calendar_position"].astype(int)
    frame["research_date_valid"] = frame["research_date_valid"].fillna(False).astype(bool)
    return frame


def _cycle_id(row: pd.Series, cycle_start: pd.Timestamp) -> str:
    return ":".join(
        (
            str(row["definition"]),
            str(row["sector_id"]),
            cycle_start.date().isoformat(),
        )
    )


def _persistence_rows(
    frame: pd.DataFrame,
    active: pd.DataFrame,
    allowed_dates: pd.DatetimeIndex,
    *,
    horizon: int,
) -> pd.DataFrame:
    future = frame.loc[
        frame["trade_date"].isin(allowed_dates),
        ["definition", "sector_id", "calendar_position", "in_cycle"],
    ].copy()
    future["calendar_position"] -= horizon
    future = future.rename(columns={"in_cycle": "persists"})
    columns = ["definition", "sector_id", "calendar_position"]
    return active.merge(future, on=columns, how="left", validate="one_to_one")


def _winning_definition(metrics: pd.DataFrame) -> str | None:
    eligible = metrics.dropna(subset=["three_day_persistence_rate"]).copy()
    if eligible.empty:
        return None
    ranked = eligible.sort_values(
        [
            "three_day_persistence_rate",
            "false_start_rate",
            "median_cycle_days",
            "definition",
        ],
        ascending=[False, True, False, True],
        na_position="last",
        kind="stable",
    )
    return str(ranked.iloc[0]["definition"])


def _mean_or_nan(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.mean()) if not numeric.empty else np.nan


def _median_or_nan(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.median()) if not numeric.empty else np.nan


def _metric_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _json_value(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (float, np.floating)) and np.isnan(value):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    return value


def _format_rate(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.2f}%"


def _format_number(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"
