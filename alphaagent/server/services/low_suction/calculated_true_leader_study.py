"""Calculated concept-cycle leader identity and independent wave truth."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from .calculated_leader_relationship import (
    MIN_RELATIONSHIP_CORRELATION,
    MIN_RELATIONSHIP_OBSERVATIONS,
    MIN_SAME_DIRECTION_RATE,
    RELATIONSHIP_POOL_SIZE,
    RELATIONSHIP_WINDOW,
    build_calculated_relationship_pool,
    build_calculated_stock_features,
    build_relationship_matrices,
)
from .leader_waves import build_leader_wave_ledger


TRUTH_HORIZON_SESSIONS = 40
MIN_TOP1_EXACT_RATE_PCT = 30.0
MIN_TOP3_CAPTURE_RATE_PCT = 60.0
MIN_TOP3_OVERLAP_PCT = 50.0
PROHIBITED_RANK_TOKENS = (
    "truth_",
    "future_",
    "outcome",
    "entry_price",
    "exit_price",
    "net_return",
    "gross_return",
    "mfe",
    "mae",
)
STUDY_VERSION = "calculated-true-leader-v1"
CAUSAL_RANK_ORDER = (
    "ignition_precedes_concept_desc",
    "strong_days_10_desc",
    "return_acceleration_5d_pct_desc",
    "stock_excess_concept_10d_pct_desc",
    "distance_from_prior_high_pct_desc",
    "volume_ratio_5_20_desc",
    "relationship_consensus_desc",
    "turnover_median_20d_desc",
    "vt_symbol_asc",
)
TRUTH_RANK_ORDER = (
    "future_wave_count_desc",
    "future_40d_max_excess_pct_desc",
    "future_20d_close_excess_pct_desc",
    "vt_symbol_asc",
)


@dataclass(frozen=True)
class CalculatedTrueLeaderInputs:
    cycle_starts: pd.DataFrame
    stock_bars: pd.DataFrame
    concept_bars: pd.DataFrame
    market_returns: pd.DataFrame
    trading_dates: tuple[date, ...]
    coverage: dict[str, Any]
    fingerprints: dict[str, dict[str, Any]]


def load_calculated_true_leader_inputs() -> CalculatedTrueLeaderInputs:
    """Load all-main-board daily prices without membership or event tables."""

    from sqlalchemy import and_, or_, select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    from .concept_cycles import (
        MARKET_BENCHMARK_SYMBOLS,
        build_cycle_candidates,
        build_market_returns,
        load_cycle_research_inputs,
    )
    from .concept_index_coverage import CANONICAL_CONCEPT_INDEX_SOURCE
    from .contracts import CONCEPT_SECTOR_TYPES
    from .research_protocol import fingerprint_frame

    cycle_inputs = load_cycle_research_inputs()
    cycle_states = build_cycle_candidates(
        cycle_inputs.concept_bars,
        cycle_inputs.market_returns,
    )
    cycle_starts = cycle_states.loc[
        cycle_states["definition"].eq("breakout_trend")
        & cycle_states["in_cycle"].astype(bool)
        & cycle_states["cycle_days"].eq(1)
        & cycle_states["relative_percentile"].ge(0.80),
        [
            "cycle_id",
            "sector_id",
            "concept_name",
            "trade_date",
            "relative_percentile",
            "close_price",
            "concept_return_10d",
        ],
    ].copy()
    if cycle_starts.empty or cycle_starts["cycle_id"].duplicated().any():
        raise ValueError("calculated leader cycle starts must be non-empty and unique")

    discovery_start = cycle_inputs.split.discovery_dates[0]
    discovery_end = cycle_inputs.split.discovery_dates[-1]
    reliable_dates = tuple(cycle_inputs.reliable_dates)
    discovery_end_position = reliable_dates.index(discovery_end)
    truth_position = discovery_end_position + TRUTH_HORIZON_SESSIONS
    if truth_position >= len(reliable_dates):
        raise ValueError("reliable calendar has no complete truth horizon")
    truth_end = reliable_dates[truth_position]
    load_start = discovery_start - timedelta(days=120)
    sector_ids = tuple(sorted(cycle_starts["sector_id"].astype(str).unique()))

    main_board_filter = or_(
        and_(
            schema.stocks.c.exchange == "SSE",
            or_(
                schema.stocks.c.symbol.like("600%"),
                schema.stocks.c.symbol.like("601%"),
                schema.stocks.c.symbol.like("603%"),
                schema.stocks.c.symbol.like("605%"),
            ),
        ),
        and_(
            schema.stocks.c.exchange == "SZSE",
            or_(
                schema.stocks.c.symbol.like("000%"),
                schema.stocks.c.symbol.like("001%"),
                schema.stocks.c.symbol.like("002%"),
                schema.stocks.c.symbol.like("003%"),
            ),
        ),
    )
    stock_statement = (
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stocks.c.name.label("stock_name"),
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.volume,
            schema.stock_daily_bars.c.turnover,
            schema.stock_daily_bars.c.source,
        )
        .select_from(
            schema.stock_daily_bars.join(
                schema.stocks,
                schema.stock_daily_bars.c.vt_symbol == schema.stocks.c.vt_symbol,
            )
        )
        .where(
            main_board_filter,
            schema.stock_daily_bars.c.trade_date.between(load_start, truth_end),
        )
        .order_by(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
        )
    )
    concept_statement = (
        select(
            schema.sector_daily_bars.c.sector_id,
            schema.sectors.c.name.label("concept_name"),
            schema.sector_daily_bars.c.trade_date,
            schema.sector_daily_bars.c.open_price,
            schema.sector_daily_bars.c.high_price,
            schema.sector_daily_bars.c.low_price,
            schema.sector_daily_bars.c.close_price,
            schema.sector_daily_bars.c.volume,
            schema.sector_daily_bars.c.turnover,
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
            schema.sector_daily_bars.c.sector_id.in_(sector_ids),
            schema.sector_daily_bars.c.trade_date.between(load_start, truth_end),
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
            schema.stock_daily_bars.c.trade_date.between(load_start, truth_end),
        )
        .order_by(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
        )
    )
    engine = get_engine()
    stock_bars = pd.read_sql(stock_statement, engine, parse_dates=["trade_date"])
    concept_bars = pd.read_sql(concept_statement, engine, parse_dates=["trade_date"])
    benchmark_bars = pd.read_sql(
        benchmark_statement, engine, parse_dates=["trade_date"]
    )
    benchmark_counts = benchmark_bars.groupby("trade_date", sort=True)[
        "vt_symbol"
    ].nunique()
    trading_dates = tuple(
        pd.Timestamp(value).date()
        for value in benchmark_counts.loc[
            benchmark_counts.eq(len(MARKET_BENCHMARK_SYMBOLS))
        ].index
    )
    market_returns = build_market_returns(
        benchmark_bars,
        research_dates=trading_dates,
    )
    fingerprint_inputs = {
        "cycle_starts": (cycle_starts, ("cycle_id",)),
        "all_main_board_stock_bars": (
            stock_bars,
            ("trade_date", "vt_symbol"),
        ),
        "calculated_relation_concept_bars": (
            concept_bars,
            ("trade_date", "sector_id"),
        ),
        "market_benchmark_bars": (
            benchmark_bars,
            ("trade_date", "vt_symbol"),
        ),
    }
    fingerprints = {
        name: fingerprint_frame(frame, identity_columns=identity).as_dict()
        for name, (frame, identity) in fingerprint_inputs.items()
    }
    coverage = {
        "discovery_start": discovery_start.isoformat(),
        "discovery_end": discovery_end.isoformat(),
        "truth_horizon_end": truth_end.isoformat(),
        "load_start": load_start.isoformat(),
        "old_outer_holdout_status": "contaminated_not_reusable",
        "concept_cycle_starts": int(len(cycle_starts)),
        "concepts_with_cycles": int(cycle_starts["sector_id"].nunique()),
        "all_main_board_stock_bar_rows": int(len(stock_bars)),
        "all_main_board_symbols": int(stock_bars["vt_symbol"].nunique()),
        "relationship_concept_bar_rows": int(len(concept_bars)),
        "relationship_concepts": int(concept_bars["sector_id"].nunique()),
        "market_benchmark_bar_rows": int(len(benchmark_bars)),
        "trading_dates": int(len(trading_dates)),
        "membership_rows_read": 0,
        "reason_rows_read": 0,
        "minute_rows_read": 0,
        "outcome_rows_read": 0,
    }
    return CalculatedTrueLeaderInputs(
        cycle_starts=cycle_starts,
        stock_bars=stock_bars,
        concept_bars=concept_bars,
        market_returns=market_returns,
        trading_dates=trading_dates,
        coverage=coverage,
        fingerprints=fingerprints,
    )


def run_calculated_true_leader_study() -> dict[str, Any]:
    """Execute the preregistered calculated-leader study end to end."""

    inputs = load_calculated_true_leader_inputs()
    features = build_calculated_stock_features(inputs.stock_bars)
    cycle_dates = pd.DatetimeIndex(
        pd.to_datetime(inputs.cycle_starts["trade_date"]).unique()
    ).normalize()
    eligible_features = features.loc[
        features["trade_date"].isin(cycle_dates)
        & features["leader_eligible"].astype(bool)
    ].copy()
    matrices = build_relationship_matrices(
        inputs.stock_bars,
        inputs.concept_bars,
        inputs.market_returns,
    )
    causal_pool = build_calculated_relationship_pool(
        inputs.cycle_starts,
        eligible_features,
        matrices,
        direction="causal",
    )
    if causal_pool.empty:
        raise ValueError("calculated causal relationship pool is empty")
    ranks = rank_calculated_leaders(causal_pool)
    realized_pool = build_calculated_relationship_pool(
        inputs.cycle_starts,
        eligible_features,
        matrices,
        direction="realized",
    )
    if realized_pool.empty:
        raise ValueError("calculated realized relationship pool is empty")
    truth = build_realized_leader_truth(
        realized_pool,
        inputs.stock_bars,
        inputs.concept_bars,
        trading_dates=inputs.trading_dates,
    )
    metrics = evaluate_calculated_identity(ranks, truth, block_count=5)
    if metrics.empty:
        raise ValueError("calculated identity evaluation has no qualified cycles")
    coverage = {
        **inputs.coverage,
        "point_in_time_feature_rows": int(len(features)),
        "eligible_cycle_date_stock_rows": int(len(eligible_features)),
        "causal_relationship_rows": int(len(causal_pool)),
        "causal_relationship_cycles": int(causal_pool["cycle_id"].nunique()),
        "realized_relationship_rows": int(len(realized_pool)),
        "realized_relationship_cycles": int(realized_pool["cycle_id"].nunique()),
        "truth_complete_rows": int(truth["truth_status"].eq("complete").sum()),
        "truth_qualified_cycles": int(
            truth.loc[truth["truth_cycle_qualified"], "cycle_id"].nunique()
        ),
    }
    return build_calculated_true_leader_report(
        coverage=coverage,
        fingerprints=inputs.fingerprints,
        ranks=ranks,
        truth=truth,
        metrics=metrics,
    )


def rank_calculated_leaders(causal_pool: pd.DataFrame) -> pd.DataFrame:
    """Freeze one causal Top3 and one excess-return baseline per cycle."""

    prohibited = sorted(
        column
        for column in causal_pool
        if any(token in str(column).lower() for token in PROHIBITED_RANK_TOKENS)
    )
    if prohibited:
        raise ValueError(f"prohibited rank columns: {prohibited}")
    required = (
        "cycle_id",
        "sector_id",
        "concept_name",
        "trade_date",
        "vt_symbol",
        "first_strong_date_10d",
        "strong_days_10",
        "return_10d_pct",
        "return_acceleration_5d_pct",
        "distance_from_prior_high_pct",
        "volume_ratio_5_20",
        "turnover_median_20d",
        "concept_return_10d",
        "relationship_consensus",
        "relationship_known_at",
        "relationship_direction",
    )
    _require_columns(causal_pool, required, "causal relationship pool")
    frame = causal_pool.copy()
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    frame["relationship_known_at"] = pd.to_datetime(
        frame["relationship_known_at"], errors="raise"
    ).dt.normalize()
    frame["first_strong_date_10d"] = pd.to_datetime(
        frame["first_strong_date_10d"], errors="raise"
    ).dt.normalize()
    if frame.duplicated(["cycle_id", "vt_symbol"]).any():
        raise ValueError("causal relationship identities must be unique")
    if not frame["relationship_direction"].eq("causal").all():
        raise ValueError("leader ranks require only causal relationships")
    if frame["relationship_known_at"].gt(frame["trade_date"]).any():
        raise ValueError("causal relationships cannot be known after rank date")
    pool_sizes = frame.groupby("cycle_id", sort=False)["vt_symbol"].nunique()
    if pool_sizes.lt(3).any():
        raise ValueError("every calculated leader cycle requires at least three stocks")

    frame["ignition_precedes_concept"] = frame["first_strong_date_10d"].lt(
        frame["trade_date"]
    )
    frame["stock_excess_concept_10d_pct"] = (
        pd.to_numeric(frame["return_10d_pct"], errors="coerce")
        - pd.to_numeric(frame["concept_return_10d"], errors="coerce") * 100.0
    )
    calculated = frame.sort_values(
        [
            "trade_date",
            "cycle_id",
            "ignition_precedes_concept",
            "strong_days_10",
            "return_acceleration_5d_pct",
            "stock_excess_concept_10d_pct",
            "distance_from_prior_high_pct",
            "volume_ratio_5_20",
            "relationship_consensus",
            "turnover_median_20d",
            "vt_symbol",
        ],
        ascending=[
            True,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            True,
        ],
        na_position="last",
        kind="stable",
    ).copy()
    calculated["calculated_rank"] = (
        calculated.groupby("cycle_id", sort=False).cumcount() + 1
    )
    baseline = frame.sort_values(
        [
            "trade_date",
            "cycle_id",
            "stock_excess_concept_10d_pct",
            "vt_symbol",
        ],
        ascending=[True, True, False, True],
        na_position="last",
        kind="stable",
    ).copy()
    baseline["baseline_rank"] = baseline.groupby(
        "cycle_id", sort=False
    ).cumcount() + 1
    calculated = calculated.merge(
        baseline.loc[:, ["cycle_id", "vt_symbol", "baseline_rank"]],
        on=["cycle_id", "vt_symbol"],
        how="left",
        validate="one_to_one",
    )
    calculated["calculated_top1"] = calculated["calculated_rank"].eq(1)
    calculated["calculated_top3"] = calculated["calculated_rank"].le(3)
    calculated["baseline_top1"] = calculated["baseline_rank"].eq(1)
    calculated["baseline_top3"] = calculated["baseline_rank"].le(3)
    calculated["rank_known_at"] = calculated["relationship_known_at"]
    return calculated.sort_values(
        ["trade_date", "cycle_id", "calculated_rank"], kind="stable"
    ).reset_index(drop=True)


def build_realized_leader_truth(
    realized_pool: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
    horizon: int = TRUTH_HORIZON_SESSIONS,
) -> pd.DataFrame:
    """Rank independent realized relations by multi-wave and concept excess."""

    if horizon < 1:
        raise ValueError("truth horizon must be positive")
    required = (
        "cycle_id",
        "sector_id",
        "concept_name",
        "trade_date",
        "vt_symbol",
        "first_strong_date_10d",
        "relationship_direction",
        "relationship_known_at",
    )
    _require_columns(realized_pool, required, "realized relationship pool")
    pool = realized_pool.copy()
    pool["trade_date"] = pd.to_datetime(pool["trade_date"], errors="raise").dt.normalize()
    pool["first_strong_date_10d"] = pd.to_datetime(
        pool["first_strong_date_10d"], errors="raise"
    ).dt.normalize()
    pool["relationship_known_at"] = pd.to_datetime(
        pool["relationship_known_at"], errors="raise"
    ).dt.normalize()
    if pool.duplicated(["cycle_id", "vt_symbol"]).any():
        raise ValueError("realized relationship identities must be unique")
    if not pool["relationship_direction"].eq("realized").all():
        raise ValueError("truth requires only realized relationships")

    stocks = _prepare_truth_stock_bars(stock_bars)
    concepts = _prepare_truth_concept_bars(concept_bars)
    calendar = tuple(sorted(set(pd.to_datetime(tuple(trading_dates)).normalize())))
    positions = {value: index for index, value in enumerate(calendar)}
    stock_groups = {
        str(symbol): group.sort_values("trade_date", kind="stable").reset_index(
            drop=True
        )
        for symbol, group in stocks.groupby("vt_symbol", sort=False)
    }
    concept_groups = {
        str(sector): group.sort_values("trade_date", kind="stable").reset_index(
            drop=True
        )
        for sector, group in concepts.groupby("sector_id", sort=False)
    }
    rows = [
        _realized_truth_row(
            row,
            stock_groups,
            concept_groups,
            calendar,
            positions,
            horizon=horizon,
        )
        for row in pool.to_dict("records")
    ]
    result = pd.DataFrame(rows)
    result["truth_cycle_qualified"] = False
    result["truth_rank"] = pd.array([pd.NA] * len(result), dtype="Int64")
    complete = result.loc[result["truth_status"].eq("complete")].copy()
    complete_counts = complete.groupby("cycle_id", sort=False)["vt_symbol"].transform(
        "nunique"
    )
    complete = complete.loc[complete_counts.ge(3)].sort_values(
        [
            "cycle_id",
            "future_wave_count",
            "future_40d_max_excess_pct",
            "future_20d_close_excess_pct",
            "vt_symbol",
        ],
        ascending=[True, False, False, False, True],
        kind="stable",
    )
    complete["_truth_rank"] = complete.groupby("cycle_id", sort=False).cumcount() + 1
    rank_map = complete.set_index(["cycle_id", "vt_symbol"])["_truth_rank"]
    identities = pd.MultiIndex.from_frame(result[["cycle_id", "vt_symbol"]])
    result["truth_rank"] = pd.array(
        rank_map.reindex(identities).to_numpy(), dtype="Int64"
    )
    qualified_cycles = set(complete["cycle_id"].astype(str))
    result["truth_cycle_qualified"] = result["cycle_id"].astype(str).isin(
        qualified_cycles
    )
    result["truth_top1"] = result["truth_rank"].eq(1).fillna(False)
    result["truth_top3"] = result["truth_rank"].le(3).fillna(False)
    return result.sort_values(
        ["trade_date", "cycle_id", "truth_rank", "vt_symbol"],
        na_position="last",
        kind="stable",
    ).reset_index(drop=True)


def evaluate_calculated_identity(
    frozen_ranks: pd.DataFrame,
    realized_truth: pd.DataFrame,
    *,
    block_count: int = 5,
) -> pd.DataFrame:
    """Separate relationship-pool and rank misses on identical truth cycles."""

    rank_columns = (
        "cycle_id",
        "trade_date",
        "vt_symbol",
        "calculated_top1",
        "calculated_top3",
        "baseline_top1",
        "baseline_top3",
    )
    truth_columns = (
        "cycle_id",
        "trade_date",
        "vt_symbol",
        "truth_status",
        "truth_top1",
        "truth_top3",
    )
    _require_columns(frozen_ranks, rank_columns, "frozen calculated rank")
    _require_columns(realized_truth, truth_columns, "realized truth")
    if block_count < 1:
        raise ValueError("block count must be positive")
    ranks = frozen_ranks.loc[:, list(rank_columns)].copy()
    truth = realized_truth.loc[:, list(truth_columns)].copy()
    for frame in (ranks, truth):
        frame["trade_date"] = pd.to_datetime(
            frame["trade_date"], errors="raise"
        ).dt.normalize()
    if ranks.duplicated(["cycle_id", "vt_symbol"]).any():
        raise ValueError("frozen rank identities must be unique")
    if truth.duplicated(["cycle_id", "vt_symbol"]).any():
        raise ValueError("truth identities must be unique")
    truth = truth.loc[truth["truth_status"].eq("complete")].copy()
    qualified_cycles = _qualified_identity_cycles(ranks, truth)
    if not qualified_cycles:
        return pd.DataFrame()
    cycle_dates = (
        ranks.loc[ranks["cycle_id"].astype(str).isin(qualified_cycles)]
        .groupby("cycle_id", sort=False)["trade_date"]
        .first()
        .sort_values(kind="stable")
    )
    unique_dates = tuple(sorted(cycle_dates.drop_duplicates().tolist()))
    if len(unique_dates) < block_count:
        raise ValueError("identity cycles do not cover every requested block")
    date_to_block: dict[pd.Timestamp, int] = {}
    for block, values in enumerate(
        np.array_split(np.array(unique_dates, dtype="datetime64[ns]"), block_count),
        start=1,
    ):
        date_to_block.update({pd.Timestamp(value): block for value in values})
    cycle_blocks = {
        str(cycle_id): date_to_block[pd.Timestamp(trade_date)]
        for cycle_id, trade_date in cycle_dates.items()
    }
    segments: list[tuple[str, set[str]]] = [("all", qualified_cycles)]
    segments.extend(
        (
            f"block_{block}",
            {
                cycle_id
                for cycle_id, assigned in cycle_blocks.items()
                if assigned == block
            },
        )
        for block in range(1, block_count + 1)
    )
    modes = (
        ("calculated_leadership", "calculated_top1", "calculated_top3"),
        ("ten_day_excess_baseline", "baseline_top1", "baseline_top3"),
    )
    rows: list[dict[str, object]] = []
    for segment_name, cycle_ids in segments:
        for mode, top1_column, top3_column in modes:
            rows.append(
                _identity_segment_metrics(
                    segment_name,
                    mode,
                    cycle_ids,
                    ranks,
                    truth,
                    top1_column=top1_column,
                    top3_column=top3_column,
                )
            )
    return pd.DataFrame(rows)


def build_calculated_true_leader_report(
    *,
    coverage: Mapping[str, Any],
    fingerprints: Mapping[str, Mapping[str, Any]],
    ranks: pd.DataFrame,
    truth: pd.DataFrame,
    metrics: pd.DataFrame,
) -> dict[str, Any]:
    """Build a report that cannot expose low-suction performance prematurely."""

    decision = _identity_decision(metrics)
    cycle_summaries = _build_cycle_summaries(ranks, truth)
    miss_counts = _miss_attribution_counts(cycle_summaries)
    return {
        "study_version": STUDY_VERSION,
        "overall_conclusion": decision["overall_conclusion"],
        "formal_top3": False,
        "formal_selected_mode": None,
        "formal_low_suction_metrics": None,
        "outcome_data_read": False,
        "minute_data_read": False,
        "timing_data_read": False,
        "membership_rows_read": 0,
        "reason_rows_read": 0,
        "universe": "all_available_sse_szse_main_board_daily_prices",
        "relationship_input": "price_returns_only",
        "relationship_contract": {
            "window_sessions": RELATIONSHIP_WINDOW,
            "minimum_paired_observations": MIN_RELATIONSHIP_OBSERVATIONS,
            "minimum_max_correlation": MIN_RELATIONSHIP_CORRELATION,
            "minimum_same_direction_rate": MIN_SAME_DIRECTION_RATE,
            "pool_size": RELATIONSHIP_POOL_SIZE,
            "residual_market": (
                "equal_weight_CSI300_CSI500_CSI1000_daily_return"
            ),
            "components": [
                "same_session_residual_correlation",
                "stock_leads_concept_one_session_residual_correlation",
                "same_direction_residual_return_rate",
            ],
            "consensus": "unweighted_mean_of_within_cycle_percentile_ranks",
            "alternative_windows_or_weights_tested": 0,
        },
        "stock_eligibility_contract": [
            "SSE_or_SZSE_main_board_symbol",
            "finite_trailing_features",
            "close_gte_ma5_gt_ma10_gt_ma20",
            "ma5_and_ma10_above_three_sessions_ago",
            "at_least_one_five_percent_strong_day_in_last_ten_sessions",
        ],
        "causal_rank_order": list(CAUSAL_RANK_ORDER),
        "baseline_rank_order": [
            "stock_excess_concept_10d_pct_desc",
            "vt_symbol_asc",
        ],
        "truth_rank_order": list(TRUTH_RANK_ORDER),
        "truth_contract": {
            "horizon_sessions": TRUTH_HORIZON_SESSIONS,
            "relationship_window": "D_plus_1_through_D_plus_40",
            "wave_anchor": "point_in_time_first_strong_date_10d",
            "attached_after_causal_rank_freeze": True,
        },
        "coverage": dict(coverage),
        "input_fingerprints": {
            str(name): dict(value) for name, value in fingerprints.items()
        },
        "decision": decision,
        "identity_metrics": _records(metrics),
        "miss_attribution": miss_counts,
        "cycle_summaries": cycle_summaries,
        "causal_rank_rows": int(len(ranks)),
        "realized_truth_rows": int(len(truth)),
        "limitations": [
            "The former outer holdout has already been inspected and is not reusable as untouched evidence.",
            "Historical point-in-time ST and suspension status is incomplete; eligibility uses main-board symbols and observed bars only.",
            "Realized leader truth is a price-calculated proxy, not an exchange-published semantic concept membership label.",
            "No low-suction entry, exit, win rate, return, compounding or drawdown is read until identity gates pass in a newly locked validation set.",
        ],
        "reproduce": (
            "docker compose run --rm --no-deps "
            "-v /root/project/ai/vnpy:/workspace -w /workspace "
            "alphaagent-api python -m "
            "alphaagent.server.services.low_suction.cli "
            "v2-calculated-true-leader-study --format markdown"
        ),
    }


def render_calculated_true_leader_json(report: Mapping[str, Any]) -> str:
    """Render deterministic calculated-leader JSON evidence."""

    return json.dumps(
        _json_safe(report),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_calculated_true_leader_markdown(report: Mapping[str, Any]) -> str:
    """Render the high-signal calculated-leader research report."""

    decision = report["decision"]
    coverage = report["coverage"]
    lines = [
        "# AlphaAgent 行情计算真龙头研究",
        "",
        f"结论：`{report['overall_conclusion']}`。正式 Top3："
        f"`{str(report['formal_top3']).lower()}`；低吸绩效：`null`。",
        "",
        "龙头候选和 Top3 全部由沪深主板股票、概念指数和市场基准的日线计算；"
        "概念成员、涨停原因、分钟线、金银环境和交易结果读取数均为 0。",
        "",
        "## Coverage",
        "",
        f"- 发现段：`{coverage.get('discovery_start')}..{coverage.get('discovery_end')}`；"
        f"真值截止：`{coverage.get('truth_horizon_end')}`。",
        f"- 主板股票：`{coverage.get('all_main_board_symbols')}` 只 / "
        f"`{coverage.get('all_main_board_stock_bar_rows')}` 根日线。",
        f"- 预筛概念周期：`{coverage.get('concept_cycle_starts')}`；"
        f"因果关系周期：`{coverage.get('causal_relationship_cycles')}`；"
        f"完整真值周期：`{coverage.get('truth_qualified_cycles')}`。",
        f"- 因果关系行：`{coverage.get('causal_relationship_rows')}`；"
        f"已实现关系行：`{coverage.get('realized_relationship_rows')}`。",
        "",
        "## Frozen Calculation",
        "",
        f"- 关系：过去 `{RELATIONSHIP_WINDOW}` 个交易日，至少 "
        f"`{MIN_RELATIONSHIP_OBSERVATIONS}` 个配对观测；股票和概念都先减去"
        "沪深300/中证500/中证1000等权日收益。",
        "- 关系共识：同期残差相关、股票领先概念一日相关、残差同向率三项"
        "在同周期内的百分位等权平均；没有搜索其他权重或窗口。",
        "- 个股资格：收盘不低于 MA5，且 MA5 > MA10 > MA20，MA5/MA10"
        "均较三日前上升，近十日至少一次涨幅不低于 5%。",
        "- 未来真值：D+1..D+40 独立重算关系，再按多波次数、最大概念超额、"
        "20 日收盘超额排序；不回流因果排名。",
        "",
        "## Identity Validation",
        "",
        "| Segment | Mode | Cycles | Relation pool captures truth Top1 | Top1 exact | Top3 captures truth Top1 | Top3 overlap |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["identity_metrics"]:
        lines.append(
            f"| `{row['segment']}` | `{row['mode']}` | "
            f"{row['qualified_cycles']} | "
            f"{_format_pct(row['relation_pool_truth_top1_capture_rate_pct'])} | "
            f"{_format_pct(row['top1_exact_rate_pct'])} | "
            f"{_format_pct(row['top3_truth_top1_capture_rate_pct'])} | "
            f"{_format_pct(row['mean_truth_top3_overlap_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- 五块胜数：`{decision['calculated_block_wins']}/5`；"
            f"相对稳定门：`{str(decision['relative_stability_passed']).lower()}`。",
            f"- 绝对身份门：`{str(decision['identity_accuracy_gate_passed']).lower()}`；"
            "要求 Top1 精确率 30%、Top3 捕获 60%、Top3 重合 50%。",
            f"- 归因：关系池漏抓 `{report['miss_attribution']['relationship_pool_miss']}`，"
            f"池内排序漏抓 `{report['miss_attribution']['leader_rank_miss']}`，"
            f"Top3 捕获 `{report['miss_attribution']['captured']}`。",
            "",
            "## Representative Misses",
            "",
            "| Date | Concept | Realized Top1 | Calculated Top3 | Attribution |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    misses = [
        row
        for row in report["cycle_summaries"]
        if row["attribution"] != "captured"
    ][:20]
    for row in misses:
        top3 = ", ".join(
            f"{item['stock_name']} `{item['vt_symbol']}`"
            for item in row["calculated_top3"]
        )
        truth = row["truth_top3"][0]
        lines.append(
            f"| `{row['trade_date']}` | {row['concept_name']} | "
            f"{truth['stock_name']} `{truth['vt_symbol']}` | {top3} | "
            f"`{row['attribution']}` |"
        )
    lines.extend(["", "## Boundary", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(
        [
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


def _build_cycle_summaries(
    ranks: pd.DataFrame,
    truth: pd.DataFrame,
) -> list[dict[str, object]]:
    complete_truth = truth.loc[truth["truth_status"].eq("complete")].copy()
    cycle_ids = _qualified_identity_cycles(ranks, complete_truth)
    rows: list[dict[str, object]] = []
    for cycle_id in sorted(cycle_ids):
        rank_cycle = ranks.loc[ranks["cycle_id"].astype(str).eq(cycle_id)].copy()
        truth_cycle = complete_truth.loc[
            complete_truth["cycle_id"].astype(str).eq(cycle_id)
        ].copy()
        rank_cycle = rank_cycle.sort_values("calculated_rank", kind="stable")
        if "truth_rank" in truth_cycle:
            truth_cycle = truth_cycle.sort_values("truth_rank", kind="stable")
        else:
            truth_cycle = truth_cycle.sort_values(
                ["truth_top1", "vt_symbol"], ascending=[False, True], kind="stable"
            )
        calculated_top3_symbols = set(
            rank_cycle.loc[
                rank_cycle["calculated_top3"].astype(bool), "vt_symbol"
            ].astype(str)
        )
        relationship_pool = set(rank_cycle["vt_symbol"].astype(str))
        truth_top1_symbol = str(
            truth_cycle.loc[truth_cycle["truth_top1"].astype(bool), "vt_symbol"].iloc[0]
        )
        if truth_top1_symbol not in relationship_pool:
            attribution = "relationship_pool_miss"
        elif truth_top1_symbol not in calculated_top3_symbols:
            attribution = "leader_rank_miss"
        else:
            attribution = "captured"
        first = rank_cycle.iloc[0]
        rows.append(
            {
                "cycle_id": cycle_id,
                "sector_id": str(first.get("sector_id", "")),
                "concept_name": str(first.get("concept_name", "")),
                "trade_date": _json_safe(first["trade_date"]),
                "causal_relationship_pool_size": int(len(rank_cycle)),
                "calculated_top3": _ranked_leader_rows(
                    rank_cycle.loc[rank_cycle["calculated_top3"].astype(bool)],
                    "calculated_rank",
                ),
                "baseline_top3": _ranked_leader_rows(
                    rank_cycle.loc[rank_cycle["baseline_top3"].astype(bool)],
                    "baseline_rank",
                ),
                "truth_top3": _truth_leader_rows(
                    truth_cycle.loc[truth_cycle["truth_top3"].astype(bool)]
                ),
                "attribution": attribution,
            }
        )
    return rows


def _ranked_leader_rows(
    frame: pd.DataFrame,
    rank_column: str,
) -> list[dict[str, object]]:
    rows = []
    for row in frame.sort_values(rank_column, kind="stable").to_dict("records"):
        rows.append(
            {
                "rank": int(row[rank_column]),
                "vt_symbol": str(row["vt_symbol"]),
                "stock_name": str(row.get("stock_name") or row["vt_symbol"]),
                "relationship_rank": (
                    int(row["relation_rank"])
                    if row.get("relation_rank") is not None
                    and pd.notna(row.get("relation_rank"))
                    else None
                ),
            }
        )
    return rows


def _truth_leader_rows(frame: pd.DataFrame) -> list[dict[str, object]]:
    if "truth_rank" in frame:
        ordered = frame.sort_values("truth_rank", kind="stable")
    else:
        ordered = frame.sort_values(
            ["truth_top1", "vt_symbol"], ascending=[False, True], kind="stable"
        )
    rows = []
    for fallback_rank, row in enumerate(ordered.to_dict("records"), start=1):
        value = row.get("truth_rank")
        rank = int(value) if value is not None and pd.notna(value) else fallback_rank
        rows.append(
            {
                "rank": rank,
                "vt_symbol": str(row["vt_symbol"]),
                "stock_name": str(row.get("stock_name") or row["vt_symbol"]),
                "future_wave_count": _number_or_none(row.get("future_wave_count")),
                "future_40d_max_excess_pct": _number_or_none(
                    row.get("future_40d_max_excess_pct")
                ),
            }
        )
    return rows


def _miss_attribution_counts(
    cycle_summaries: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    return {
        label: sum(row.get("attribution") == label for row in cycle_summaries)
        for label in ("relationship_pool_miss", "leader_rank_miss", "captured")
    }


def _number_or_none(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _realized_truth_row(
    row: dict[str, object],
    stock_groups: dict[str, pd.DataFrame],
    concept_groups: dict[str, pd.DataFrame],
    calendar: tuple[pd.Timestamp, ...],
    positions: dict[pd.Timestamp, int],
    *,
    horizon: int,
) -> dict[str, object]:
    result = dict(row)
    cycle_date = pd.Timestamp(row["trade_date"]).normalize()
    position = positions.get(cycle_date)
    if position is None or position + horizon >= len(calendar):
        return _censored_truth(result, "censored_incomplete_40d")
    boundary = calendar[position + horizon]
    if pd.Timestamp(row["relationship_known_at"]).normalize() != boundary:
        raise ValueError("realized relationship cutoff must equal truth boundary")
    stock = stock_groups.get(str(row["vt_symbol"]))
    concept = concept_groups.get(str(row["sector_id"]))
    if stock is None or concept is None:
        return _censored_truth(result, "censored_missing_future_bars")
    stock_index = stock.set_index("trade_date", drop=False)
    concept_index = concept.set_index("trade_date", drop=False)
    required_dates = set(calendar[position : position + horizon + 1])
    if not required_dates.issubset(stock_index.index) or not required_dates.issubset(
        concept_index.index
    ):
        return _censored_truth(result, "censored_missing_future_bars")
    anchor = pd.Timestamp(row["first_strong_date_10d"]).normalize()
    if anchor > cycle_date or anchor not in stock_index.index:
        return _censored_truth(result, "censored_missing_anchor_bar")
    observed_stock = stock.loc[stock["trade_date"].le(boundary)]
    if observed_stock.loc[
        observed_stock["trade_date"].between(anchor, boundary), "volume"
    ].le(0).any():
        return _censored_truth(result, "censored_invalid_wave_bars")
    ledger = build_leader_wave_ledger(
        observed_stock,
        anchor_date=anchor.date(),
        observation_end=boundary.date(),
    )
    stock_start = float(stock_index.at[cycle_date, "close_price"])
    concept_start = float(concept_index.at[cycle_date, "close_price"])
    excess_path = []
    for future_date in calendar[position + 1 : position + horizon + 1]:
        stock_return = float(stock_index.at[future_date, "close_price"]) / stock_start - 1.0
        concept_return = (
            float(concept_index.at[future_date, "close_price"]) / concept_start - 1.0
        )
        excess_path.append((stock_return - concept_return) * 100.0)
    midpoint = calendar[position + min(20, horizon)]
    result.update(
        {
            "truth_status": "complete",
            "truth_observation_end": boundary,
            "future_wave_count": int(ledger["wave_number"].max()),
            "future_higher_high_confirmations": int(ledger["wave_number"].max()) - 1,
            "future_final_resolution_status": str(
                ledger.iloc[-1]["resolution_status"]
            ),
            "future_20d_close_excess_pct": (
                (
                    float(stock_index.at[midpoint, "close_price"]) / stock_start
                    - 1.0
                )
                - (
                    float(concept_index.at[midpoint, "close_price"]) / concept_start
                    - 1.0
                )
            )
            * 100.0,
            "future_40d_max_excess_pct": max(excess_path),
        }
    )
    return result


def _censored_truth(
    row: dict[str, object],
    status: str,
) -> dict[str, object]:
    result = dict(row)
    result.update(
        {
            "truth_status": status,
            "truth_observation_end": None,
            "future_wave_count": None,
            "future_higher_high_confirmations": None,
            "future_final_resolution_status": None,
            "future_20d_close_excess_pct": None,
            "future_40d_max_excess_pct": None,
        }
    )
    return result


def _qualified_identity_cycles(
    ranks: pd.DataFrame,
    truth: pd.DataFrame,
) -> set[str]:
    rank_counts = ranks.groupby("cycle_id", sort=False).agg(
        rows=("vt_symbol", "nunique"),
        calculated_top1=("calculated_top1", "sum"),
        calculated_top3=("calculated_top3", "sum"),
        baseline_top1=("baseline_top1", "sum"),
        baseline_top3=("baseline_top3", "sum"),
    )
    truth_counts = truth.groupby("cycle_id", sort=False).agg(
        rows=("vt_symbol", "nunique"),
        truth_top1=("truth_top1", "sum"),
        truth_top3=("truth_top3", "sum"),
    )
    valid_ranks = set(
        rank_counts.loc[
            rank_counts["rows"].ge(3)
            & rank_counts["calculated_top1"].eq(1)
            & rank_counts["calculated_top3"].eq(3)
            & rank_counts["baseline_top1"].eq(1)
            & rank_counts["baseline_top3"].eq(3)
        ].index.astype(str)
    )
    valid_truth = set(
        truth_counts.loc[
            truth_counts["rows"].ge(3)
            & truth_counts["truth_top1"].eq(1)
            & truth_counts["truth_top3"].eq(3)
        ].index.astype(str)
    )
    return valid_ranks & valid_truth


def _identity_segment_metrics(
    segment_name: str,
    mode: str,
    cycle_ids: set[str],
    ranks: pd.DataFrame,
    truth: pd.DataFrame,
    *,
    top1_column: str,
    top3_column: str,
) -> dict[str, object]:
    cycle_metrics: list[dict[str, float | bool]] = []
    for cycle_id in sorted(cycle_ids):
        rank_cycle = ranks.loc[ranks["cycle_id"].astype(str).eq(cycle_id)]
        truth_cycle = truth.loc[truth["cycle_id"].astype(str).eq(cycle_id)]
        relationship_pool = set(rank_cycle["vt_symbol"].astype(str))
        selected_top1 = set(
            rank_cycle.loc[rank_cycle[top1_column].astype(bool), "vt_symbol"].astype(str)
        )
        selected_top3 = set(
            rank_cycle.loc[rank_cycle[top3_column].astype(bool), "vt_symbol"].astype(str)
        )
        truth_top1 = set(
            truth_cycle.loc[truth_cycle["truth_top1"].astype(bool), "vt_symbol"].astype(str)
        )
        truth_top3 = set(
            truth_cycle.loc[truth_cycle["truth_top3"].astype(bool), "vt_symbol"].astype(str)
        )
        cycle_metrics.append(
            {
                "relation_capture": bool(relationship_pool & truth_top1),
                "top1_exact": selected_top1 == truth_top1,
                "top3_capture": bool(selected_top3 & truth_top1),
                "top3_overlap": len(selected_top3 & truth_top3) / 3.0,
            }
        )
    return {
        "segment": segment_name,
        "mode": mode,
        "qualified_cycles": len(cycle_metrics),
        "relation_pool_truth_top1_capture_rate_pct": _boolean_rate(
            [bool(row["relation_capture"]) for row in cycle_metrics]
        ),
        "top1_exact_rate_pct": _boolean_rate(
            [bool(row["top1_exact"]) for row in cycle_metrics]
        ),
        "top3_truth_top1_capture_rate_pct": _boolean_rate(
            [bool(row["top3_capture"]) for row in cycle_metrics]
        ),
        "mean_truth_top3_overlap_pct": (
            float(np.mean([float(row["top3_overlap"]) for row in cycle_metrics]) * 100.0)
            if cycle_metrics
            else None
        ),
    }


def _identity_decision(metrics: pd.DataFrame) -> dict[str, object]:
    required = (
        "segment",
        "mode",
        "top1_exact_rate_pct",
        "top3_truth_top1_capture_rate_pct",
        "mean_truth_top3_overlap_pct",
    )
    _require_columns(metrics, required, "identity metric")
    pooled = metrics.loc[metrics["segment"].eq("all")].set_index("mode")
    if "calculated_leadership" not in pooled.index:
        raise ValueError("calculated pooled identity metric is missing")
    calculated = pooled.loc["calculated_leadership"]
    gate = (
        float(calculated["top1_exact_rate_pct"]) >= MIN_TOP1_EXACT_RATE_PCT
        and float(calculated["top3_truth_top1_capture_rate_pct"])
        >= MIN_TOP3_CAPTURE_RATE_PCT
        and float(calculated["mean_truth_top3_overlap_pct"])
        >= MIN_TOP3_OVERLAP_PCT
    )
    block_winners = []
    for segment in sorted(
        value for value in metrics["segment"].astype(str).unique() if value != "all"
    ):
        block = metrics.loc[metrics["segment"].eq(segment)].set_index("mode")
        calculated_tuple = _metric_tuple(block.loc["calculated_leadership"])
        baseline_tuple = _metric_tuple(block.loc["ten_day_excess_baseline"])
        block_winners.append(
            "calculated_leadership"
            if calculated_tuple > baseline_tuple
            else (
                "ten_day_excess_baseline"
                if baseline_tuple > calculated_tuple
                else "tie"
            )
        )
    calculated_wins = block_winners.count("calculated_leadership")
    relative_stability = calculated_wins >= 3
    if gate and relative_stability:
        conclusion = "calculated_identity_candidate_old_holdout_contaminated"
    elif relative_stability:
        conclusion = "stable_relative_improvement_but_identity_accuracy_insufficient"
    else:
        conclusion = "calculated_relation_or_rank_not_stable"
    return {
        "overall_conclusion": conclusion,
        "identity_accuracy_gate_passed": gate,
        "relative_stability_passed": relative_stability,
        "calculated_block_wins": calculated_wins,
        "required_block_wins": 3,
        "block_winners": block_winners,
        "absolute_identity_gate": {
            "minimum_top1_exact_rate_pct": MIN_TOP1_EXACT_RATE_PCT,
            "minimum_top3_truth_top1_capture_rate_pct": MIN_TOP3_CAPTURE_RATE_PCT,
            "minimum_mean_truth_top3_overlap_pct": MIN_TOP3_OVERLAP_PCT,
        },
    }


def _metric_tuple(row: pd.Series) -> tuple[float, float, float]:
    return (
        float(row["top3_truth_top1_capture_rate_pct"]),
        float(row["top1_exact_rate_pct"]),
        float(row["mean_truth_top3_overlap_pct"]),
    )


def _prepare_truth_stock_bars(frame: pd.DataFrame) -> pd.DataFrame:
    columns = (
        "vt_symbol",
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
    )
    _require_columns(frame, columns, "truth stock bar")
    result = frame.loc[:, list(columns)].copy()
    result["trade_date"] = pd.to_datetime(
        result["trade_date"], errors="raise"
    ).dt.normalize()
    if result.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("truth stock bar identities must be unique")
    return result


def _prepare_truth_concept_bars(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ("sector_id", "trade_date", "close_price")
    _require_columns(frame, columns, "truth concept bar")
    result = frame.loc[:, list(columns)].copy()
    result["trade_date"] = pd.to_datetime(
        result["trade_date"], errors="raise"
    ).dt.normalize()
    if result.duplicated(["sector_id", "trade_date"]).any():
        raise ValueError("truth concept bar identities must be unique")
    return result


def _boolean_rate(values: Sequence[bool]) -> float | None:
    return float(np.mean(values) * 100.0) if values else None


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, np.ndarray)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, date)):
        return pd.Timestamp(value).date().isoformat()
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(float(value)) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _format_pct(value: object) -> str:
    numeric = _number_or_none(value)
    return f"{numeric:.4f}%" if numeric is not None else "null"


def _require_columns(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    label: str,
) -> None:
    missing = sorted(set(columns) - set(frame))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
