"""Full-history proxy study for the causal leader pullback algorithm."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from alphaagent.server.services.a_share_universe import is_eligible_main_board

from .causal_leader_pullback import (
    ALGORITHM_VERSION,
    CampaignPreparation,
    CONCEPT_ANCHOR_MODE,
    CONCEPT_EXIT_CONFIRM_SESSIONS,
    CONCEPT_EXIT_DRAWDOWN_PCT,
    CROSS_REGIME_POLICY_VERSION,
    IGNITION_RETURN_PCT,
    IGNITION_VOLUME_RATIO,
    MINIMUM_REQUIRED_SUPPORT,
    NON_CONTRACTION_VOLUME_RATIO,
    ROUND_TRIP_COST_PCT,
    SUPPORT_TOLERANCE_PCT,
    execute_prepared_close_trades,
    prepare_stock_campaigns,
    rank_campaign_leaders,
    select_cross_regime_support_reclaim_signals,
    select_gold_strong_reclaim_signals,
    summarize_trade_metrics,
)
from .dynamic_concept_campaign import (
    MEMBERSHIP_EVIDENCE_LEVEL,
    build_concept_campaign_features,
    build_exploratory_campaigns,
)
from .contracts import CONCEPT_SECTOR_TYPES


STUDY_VERSION = "causal-leader-pullback-study-v4"
CONCEPT_SOURCE = "eastmoney.board_kline"
GOLD_STRONG_RECLAIM_VARIANT = "gold_strong_reclaim_confirmation"
CROSS_REGIME_SUPPORT_RECLAIM_VARIANT = (
    "cross_regime_support_reclaim_confirmation"
)
VARIANTS = (
    "base_confirmation",
    "non_contraction_confirmation",
    GOLD_STRONG_RECLAIM_VARIANT,
    CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
)
MIN_STOCK_SESSIONS = 60
PRECAMPAIGN_IGNITION_SESSIONS = 10
TIME_BLOCK_COUNT = 5
MIN_CLOSED_TRADES = 100
MIN_BLOCK_TRADES = 30
MIN_CROSS_REGIME_BLOCK_TRADES = 15
MIN_STABLE_TIME_BLOCKS = 3
MIN_QUALIFIED_MARKET_PHASES = 2
MIN_MARKET_PHASE_TRADES = 30
MIN_WIN_RATE_PCT = 60.0
MIN_PROFIT_FACTOR = 1.20
MIN_CASH_COMPOUND_PCT = 60.0
MIN_CASH_DRAWDOWN_PCT = -10.0
REFERENCE_SYMBOLS = {
    "002384.SZSE": "东山精密",
    "002636.SZSE": "金安国纪",
    "600487.SSE": "亨通光电",
}
STOCK_PATH_FEATURE_COLUMNS = (
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "turnover",
    "daily_return_pct",
    "ma5",
    "ma10",
    "ma20",
    "prior_high20",
    "volume_ratio_prior5",
    "turnover_expansion",
    "close_location",
    "stock_session_index",
    "previous_close",
    "strong_day",
    "ignition",
    "last_ignition_session_index",
    "sessions_since_ignition",
    "last_ignition_date",
    "ignition_base_close",
    "last_ignition_base_close",
    "structure_intact",
    "feature_complete",
)


@dataclass(frozen=True)
class CausalLeaderPullbackInputs:
    concept_bars: pd.DataFrame
    memberships: pd.DataFrame
    stock_bars: pd.DataFrame
    market_timing: pd.DataFrame
    coverage: dict[str, Any]
    fingerprints: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class ReplayResult:
    signals: pd.DataFrame
    trades: pd.DataFrame
    waves: pd.DataFrame
    exclusions: pd.DataFrame
    daily_ledger: pd.DataFrame


@dataclass(frozen=True)
class DynamicLeaderPreparation:
    """Replayable paths and causal states before any trade variant runs."""

    campaigns: CampaignPreparation
    signals: pd.DataFrame
    waves: pd.DataFrame
    exclusions: pd.DataFrame


def load_causal_leader_pullback_inputs() -> CausalLeaderPullbackInputs:
    """Load canonical concept history, current members and main-board OHLCV."""

    from sqlalchemy import func, select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    from .dynamic_concept_campaign_study import filter_exploratory_concept_universe
    from .event_recognition_falsification import load_timing_context
    from .research_protocol import fingerprint_frame

    engine = get_engine()
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
            schema.sector_daily_bars.c.source == CONCEPT_SOURCE,
        )
        .order_by(
            schema.sector_daily_bars.c.sector_id,
            schema.sector_daily_bars.c.trade_date,
        )
    )
    raw_concepts = pd.read_sql(concept_statement, engine, parse_dates=["trade_date"])
    concept_bars, universe_audit = filter_exploratory_concept_universe(raw_concepts)
    if concept_bars.empty:
        raise ValueError("canonical concept bars are empty")
    concept_start = pd.Timestamp(concept_bars["trade_date"].min()).date()
    concept_end = pd.Timestamp(concept_bars["trade_date"].max()).date()
    sector_ids = tuple(sorted(concept_bars["sector_id"].astype(str).unique()))

    membership_statement = (
        select(
            schema.stock_sector_memberships.c.sector_id,
            schema.stock_sector_memberships.c.vt_symbol,
            schema.stocks.c.name.label("stock_name"),
            schema.stock_sector_memberships.c.source,
        )
        .select_from(
            schema.stock_sector_memberships.join(
                schema.stocks,
                schema.stock_sector_memberships.c.vt_symbol
                == schema.stocks.c.vt_symbol,
            )
        )
        .where(
            schema.stock_sector_memberships.c.sector_type.in_(CONCEPT_SECTOR_TYPES),
            schema.stock_sector_memberships.c.sector_id.in_(sector_ids),
        )
        .order_by(
            schema.stock_sector_memberships.c.sector_id,
            schema.stock_sector_memberships.c.vt_symbol,
        )
    )
    memberships = pd.read_sql(membership_statement, engine)
    memberships["stock_name"] = memberships["stock_name"].fillna("").astype(str)
    memberships = memberships.loc[
        [
            is_eligible_main_board(symbol, name)
            for symbol, name in zip(
                memberships["vt_symbol"], memberships["stock_name"], strict=True
            )
        ]
    ].drop_duplicates(["sector_id", "vt_symbol"], keep="last")
    memberships["evidence_level"] = MEMBERSHIP_EVIDENCE_LEVEL
    if memberships.empty:
        raise ValueError("eligible current concept memberships are empty")
    symbols = tuple(sorted(memberships["vt_symbol"].astype(str).unique()))

    stock_statement = (
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.volume,
            schema.stock_daily_bars.c.turnover,
            schema.stock_daily_bars.c.source,
        )
        .where(
            schema.stock_daily_bars.c.vt_symbol.in_(symbols),
            schema.stock_daily_bars.c.trade_date.between(
                concept_start - timedelta(days=180), concept_end
            ),
        )
        .order_by(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
        )
    )
    stock_bars = pd.read_sql(stock_statement, engine, parse_dates=["trade_date"])
    if stock_bars.empty:
        raise ValueError("eligible main-board stock bars are empty")
    if stock_bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock daily bar identities must be unique")

    market_timing = load_timing_context()
    _require_columns(
        market_timing,
        ("source_date", "active_direction", "danger_state", "market_phase"),
        "market timing context",
    )
    market_timing = market_timing.copy()
    market_timing["source_date"] = pd.to_datetime(
        market_timing["source_date"], errors="raise"
    ).dt.normalize()
    if market_timing["source_date"].duplicated().any():
        raise ValueError("market timing dates must be unique")

    with engine.connect() as connection:
        strict_membership_rows = int(
            connection.execute(
                select(func.count()).select_from(
                    schema.low_suction_concept_membership_history
                )
            ).scalar_one()
        )
        snapshot_dates = int(
            connection.execute(
                select(
                    func.count(
                        func.distinct(
                            schema.stock_sector_membership_snapshots.c.snapshot_date
                        )
                    )
                )
            ).scalar_one()
        )
    if strict_membership_rows:
        raise ValueError(
            "strict historical memberships exist; survivorship proxy must not mix with them"
        )

    fingerprint_frames = {
        "canonical_concept_bars": (concept_bars, ("sector_id", "trade_date")),
        "current_membership_survivorship_proxy": (
            memberships,
            ("sector_id", "vt_symbol"),
        ),
        "main_board_stock_bars": (stock_bars, ("vt_symbol", "trade_date")),
        "market_timing_context": (market_timing, ("source_date",)),
    }
    fingerprints = {
        name: fingerprint_frame(frame, identity_columns=identity).as_dict()
        for name, (frame, identity) in fingerprint_frames.items()
    }
    coverage = {
        "raw_concept_bar_rows": int(len(raw_concepts)),
        "concept_bar_rows": int(len(concept_bars)),
        "concepts": int(concept_bars["sector_id"].nunique()),
        "concept_start": concept_start.isoformat(),
        "concept_end": concept_end.isoformat(),
        "current_membership_rows": int(len(memberships)),
        "current_membership_symbols": int(memberships["vt_symbol"].nunique()),
        "strict_historical_membership_rows": strict_membership_rows,
        "membership_snapshot_dates": snapshot_dates,
        "stock_bar_rows": int(len(stock_bars)),
        "stock_symbols": int(stock_bars["vt_symbol"].nunique()),
        "minute_rows_read": 0,
        "fund_flow_rows_read": 0,
        "market_timing_rows_read": int(len(market_timing)),
        "market_timing_start": _date_or_none(market_timing["source_date"].min()),
        "market_timing_end": _date_or_none(market_timing["source_date"].max()),
        "old_low_suction_outcome_rows_read": 0,
        **universe_audit,
    }
    return CausalLeaderPullbackInputs(
        concept_bars=concept_bars,
        memberships=memberships.reset_index(drop=True),
        stock_bars=stock_bars,
        market_timing=market_timing.reset_index(drop=True),
        coverage=coverage,
        fingerprints=fingerprints,
    )


def build_causal_stock_features(stock_bars: pd.DataFrame) -> pd.DataFrame:
    """Build all trailing price, volume, ignition and structure fields once."""

    required = (
        "vt_symbol",
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "turnover",
    )
    _require_columns(stock_bars, required, "stock daily bar")
    frame = stock_bars.loc[:, list(required)].copy()
    frame["vt_symbol"] = frame["vt_symbol"].astype(str)
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    if frame.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock daily bar identities must be unique")
    numeric = list(required[2:])
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(frame[numeric].to_numpy(dtype=float)).all():
        raise ValueError("stock daily values must be finite")
    frame = frame.sort_values(["vt_symbol", "trade_date"], kind="stable").reset_index(
        drop=True
    )
    grouped = frame.groupby("vt_symbol", sort=False)
    frame["stock_session_index"] = grouped.cumcount()
    frame["previous_close"] = grouped["close_price"].shift(1)
    frame["daily_return_pct"] = (
        frame["close_price"] / frame["previous_close"] - 1.0
    ) * 100.0
    for window in (5, 10, 20):
        frame[f"ma{window}"] = _rolling_by_symbol(
            frame["close_price"],
            frame["vt_symbol"],
            window=window,
            min_periods=window,
            aggregation="mean",
        )
    frame["prior_high20"] = _rolling_by_symbol(
        grouped["high_price"].shift(1),
        frame["vt_symbol"],
        window=20,
        min_periods=20,
        aggregation="max",
    )
    prior_volume = _rolling_by_symbol(
        grouped["volume"].shift(1),
        frame["vt_symbol"],
        window=5,
        min_periods=5,
        aggregation="median",
    )
    frame["volume_ratio_prior5"] = frame["volume"] / prior_volume.replace(0.0, np.nan)
    turnover5 = _rolling_by_symbol(
        frame["turnover"],
        frame["vt_symbol"],
        window=5,
        min_periods=5,
        aggregation="mean",
    )
    turnover20 = _rolling_by_symbol(
        grouped["turnover"].shift(5),
        frame["vt_symbol"],
        window=20,
        min_periods=15,
        aggregation="mean",
    )
    frame["turnover_expansion"] = turnover5 / turnover20.replace(0.0, np.nan)
    spread = (frame["high_price"] - frame["low_price"]).replace(0.0, np.nan)
    frame["close_location"] = (
        (frame["close_price"] - frame["low_price"]) / spread
    ).fillna(0.5)
    frame["strong_day"] = frame["daily_return_pct"].ge(IGNITION_RETURN_PCT)
    frame["ignition"] = (
        frame["strong_day"]
        & frame["close_price"].gt(frame["prior_high20"])
        & frame["volume_ratio_prior5"].ge(IGNITION_VOLUME_RATIO)
    ).fillna(False)
    ignition_position = frame["stock_session_index"].where(frame["ignition"])
    frame["last_ignition_session_index"] = ignition_position.groupby(
        frame["vt_symbol"], sort=False
    ).ffill()
    frame["sessions_since_ignition"] = (
        frame["stock_session_index"] - frame["last_ignition_session_index"]
    )
    ignition_date = frame["trade_date"].where(frame["ignition"])
    frame["last_ignition_date"] = ignition_date.groupby(
        frame["vt_symbol"], sort=False
    ).ffill()
    ignition_base = frame["previous_close"].where(frame["ignition"])
    frame["ignition_base_close"] = ignition_base
    frame["last_ignition_base_close"] = ignition_base.groupby(
        frame["vt_symbol"], sort=False
    ).ffill()
    below_ma10 = frame["close_price"].lt(frame["ma10"])
    frame["structure_intact"] = (
        frame["close_price"].ge(frame["ma20"])
        & ~(
            below_ma10
            & below_ma10.groupby(frame["vt_symbol"], sort=False).shift(
                1, fill_value=False
            )
            & frame["ma5"].le(frame["ma10"])
        )
        & frame["stock_session_index"].ge(MIN_STOCK_SESSIONS)
    ).fillna(False)
    feature_columns = (
        "ma5",
        "ma10",
        "ma20",
        "prior_high20",
        "volume_ratio_prior5",
        "turnover_expansion",
    )
    frame["feature_complete"] = frame[list(feature_columns)].notna().all(axis=1)
    frame["feature_cutoff_date"] = frame["trade_date"]
    return frame


def _rolling_by_symbol(
    values: pd.Series,
    symbols: pd.Series,
    *,
    window: int,
    min_periods: int,
    aggregation: str,
) -> pd.Series:
    rolled = values.groupby(symbols, sort=False).rolling(
        window,
        min_periods=min_periods,
    )
    result = rolled.aggregate(aggregation).reset_index(level=0, drop=True)
    return result.reindex(values.index)


def build_concept_campaign_ledger(
    concept_bars: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the one frozen price/turnover campaign definition."""

    features = build_concept_campaign_features(concept_bars)
    campaigns, paths = build_exploratory_campaigns(
        features,
        anchor_modes=(CONCEPT_ANCHOR_MODE,),
        exit_candidates=((CONCEPT_EXIT_DRAWDOWN_PCT, CONCEPT_EXIT_CONFIRM_SESSIONS),),
        retained_path_days=None,
    )
    if campaigns.empty or paths.empty:
        raise ValueError("frozen concept campaign definition produced no paths")
    right_censored_ids = set(
        campaigns.loc[
            campaigns["right_censored"].astype(bool),
            "campaign_id",
        ].astype(str)
    )
    paths["campaign_active"] = ~paths["is_endpoint"].astype(bool) | paths[
        "campaign_id"
    ].astype(str).isin(right_censored_ids)
    paths["feature_cutoff_date"] = paths["trade_date"]
    return campaigns, paths


def build_dynamic_leader_paths(
    campaign_paths: pd.DataFrame,
    memberships: pd.DataFrame,
    stock_features: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Rank one concept at a time and retain complete paths of any daily Top3."""

    required_paths = (
        "campaign_id",
        "sector_id",
        "concept_name",
        "anchor_date",
        "trade_date",
        "campaign_day",
        "cumulative_gain_pct",
        "campaign_active",
    )
    _require_columns(campaign_paths, required_paths, "concept campaign path")
    _require_columns(
        memberships, ("sector_id", "vt_symbol", "stock_name"), "membership"
    )
    campaign_frame = campaign_paths.copy()
    campaign_frame["sector_id"] = campaign_frame["sector_id"].astype(str)
    campaign_frame = campaign_frame.rename(
        columns={"close_price": "concept_close_price"}
    )
    for column in ("anchor_date", "trade_date"):
        campaign_frame[column] = pd.to_datetime(
            campaign_frame[column], errors="raise"
        ).dt.normalize()
    member_frame = memberships.loc[:, ["sector_id", "vt_symbol", "stock_name"]].copy()
    member_frame["sector_id"] = member_frame["sector_id"].astype(str)
    feature_lookup = _build_stock_feature_lookup(stock_features)
    retained_parts: list[pd.DataFrame] = []
    expanded_rows = 0
    rankable_rows = 0
    top3_rows = 0
    retained_identities = 0

    for sector_id, sector_paths in campaign_frame.groupby("sector_id", sort=True):
        sector_members = member_frame.loc[member_frame["sector_id"].eq(str(sector_id))]
        if len(sector_members) < 3:
            continue
        expanded = _expand_sector_campaign_members(
            sector_paths,
            sector_members,
            feature_lookup,
        )
        if expanded.empty:
            continue
        expanded_rows += len(expanded)
        expanded = _attach_campaign_leg_features(expanded)
        rank_inputs = expanded.drop(
            columns=["exit_drawdown_pct", "exit_confirm_sessions"],
            errors="ignore",
        )
        ranked = rank_campaign_leaders(rank_inputs)
        rankable_rows += int(ranked["rankable"].sum())
        top3_rows += int(ranked["dynamic_top3"].sum())
        top3_ids = ranked.loc[
            ranked["dynamic_top3"], ["campaign_id", "vt_symbol"]
        ].drop_duplicates()
        retained_identities += len(top3_ids)
        if top3_ids.empty:
            continue
        ranked_identities = pd.MultiIndex.from_frame(
            ranked.loc[:, ["campaign_id", "vt_symbol"]]
        )
        retained_id_index = pd.MultiIndex.from_frame(top3_ids)
        retained = ranked.loc[ranked_identities.isin(retained_id_index)].copy()
        retained["feature_cutoff_date"] = retained["trade_date"]
        retained_parts.append(retained)

    if not retained_parts:
        return pd.DataFrame(), {
            "expanded_member_date_rows": expanded_rows,
            "rankable_member_date_rows": rankable_rows,
            "dynamic_top3_rows": top3_rows,
            "retained_stock_campaigns": retained_identities,
        }
    result = (
        pd.concat(retained_parts, ignore_index=True)
        .sort_values(
            ["trade_date", "campaign_id", "dynamic_rank", "vt_symbol"],
            na_position="last",
            kind="stable",
        )
        .reset_index(drop=True)
    )
    return result, {
        "expanded_member_date_rows": int(expanded_rows),
        "rankable_member_date_rows": int(rankable_rows),
        "dynamic_top3_rows": int(top3_rows),
        "retained_stock_campaigns": int(retained_identities),
    }


def _build_stock_feature_lookup(stock_features: pd.DataFrame) -> pd.DataFrame:
    identity_columns = ["vt_symbol", "trade_date"]
    required = [*identity_columns, *STOCK_PATH_FEATURE_COLUMNS]
    _require_columns(stock_features, required, "stock feature lookup")
    if stock_features.duplicated(identity_columns).any():
        raise ValueError("stock feature lookup identities must be unique")
    return stock_features.loc[:, required].set_index(identity_columns)


def _expand_sector_campaign_members(
    sector_paths: pd.DataFrame,
    sector_members: pd.DataFrame,
    feature_lookup: pd.DataFrame,
) -> pd.DataFrame:
    paths = sector_paths.reset_index(drop=True)
    members = sector_members.loc[:, ["vt_symbol", "stock_name"]].reset_index(drop=True)
    if paths.empty or members.empty:
        return pd.DataFrame()
    path_positions = np.repeat(np.arange(len(paths)), len(members))
    member_positions = np.tile(np.arange(len(members)), len(paths))
    expanded_paths = paths.iloc[path_positions].reset_index(drop=True)
    expanded_members = members.iloc[member_positions].reset_index(drop=True)
    lookup_index = pd.MultiIndex.from_arrays(
        [
            expanded_members["vt_symbol"].to_numpy(),
            expanded_paths["trade_date"].to_numpy(),
        ],
        names=["vt_symbol", "trade_date"],
    )
    expanded_features = feature_lookup.reindex(lookup_index).reset_index(drop=True)
    return pd.concat(
        [expanded_paths, expanded_members, expanded_features],
        axis=1,
        copy=False,
    )


def _attach_campaign_leg_features(expanded: pd.DataFrame) -> pd.DataFrame:
    frame = expanded.sort_values(
        ["campaign_id", "vt_symbol", "trade_date"], kind="stable"
    ).copy()
    group_columns = [frame["campaign_id"], frame["vt_symbol"]]
    pre_campaign_ignition = frame["campaign_day"].eq(0) & pd.to_numeric(
        frame["sessions_since_ignition"], errors="coerce"
    ).between(0, PRECAMPAIGN_IGNITION_SESSIONS)
    current_ignition = frame["ignition"].fillna(False).astype(bool)
    candidate = pre_campaign_ignition | current_ignition
    candidate_ordinal = (
        candidate.astype(int).groupby(group_columns, sort=False).cumsum()
    )
    first_candidate = candidate & candidate_ordinal.eq(1)
    candidate_base = frame["ignition_base_close"].where(current_ignition)
    candidate_base = candidate_base.where(
        ~pre_campaign_ignition, frame["last_ignition_base_close"]
    )
    candidate_date = frame["trade_date"].where(current_ignition)
    candidate_date = candidate_date.where(
        ~pre_campaign_ignition, frame["last_ignition_date"]
    )
    first_base = candidate_base.where(first_candidate)
    first_date = candidate_date.where(first_candidate)
    frame["leader_leg_base_close"] = first_base.groupby(
        group_columns, sort=False
    ).ffill()
    frame["leader_ignition_date"] = first_date.groupby(
        group_columns, sort=False
    ).ffill()
    frame["leader_leg_start_today"] = first_candidate.fillna(False)
    frame["ignited_in_campaign"] = frame["leader_leg_base_close"].notna()
    frame["leg_gain_pct"] = (
        frame["close_price"] / frame["leader_leg_base_close"] - 1.0
    ) * 100.0
    visible_strong = frame["strong_day"].fillna(False) & frame["ignited_in_campaign"]
    frame["strong_days_since_ignition"] = (
        visible_strong.astype(int).groupby(group_columns, sort=False).cumsum()
    )
    frame["concept_gain_pct"] = pd.to_numeric(
        frame["cumulative_gain_pct"], errors="coerce"
    )
    frame["structure_intact"] = frame["structure_intact"].fillna(False) & frame[
        "feature_complete"
    ].fillna(False)
    frame["ignited_in_campaign"] &= (
        frame["stock_session_index"].fillna(-1).ge(MIN_STOCK_SESSIONS)
    )
    return frame


def attach_signal_market_timing(
    signals: pd.DataFrame,
    market_timing: pd.DataFrame,
) -> pd.DataFrame:
    """Attach only the market state published for the completed signal date."""

    _require_columns(signals, ("signal_date",), "leader pullback signal")
    timing_columns = (
        "source_date",
        "active_direction",
        "danger_state",
        "market_phase",
    )
    _require_columns(market_timing, timing_columns, "market timing context")
    stale_columns = set(timing_columns[1:]) & set(signals.columns)
    if stale_columns:
        raise ValueError(
            f"signals already contain market timing: {sorted(stale_columns)}"
        )

    result = signals.copy()
    result["signal_date"] = pd.to_datetime(
        result["signal_date"], errors="raise"
    ).dt.normalize()
    timing = market_timing.loc[:, list(timing_columns)].copy()
    timing["source_date"] = pd.to_datetime(
        timing["source_date"], errors="raise"
    ).dt.normalize()
    if timing["source_date"].duplicated().any():
        raise ValueError("market timing dates must be unique")
    timing["market_timing_source_date"] = timing["source_date"]
    timing = timing.rename(columns={"source_date": "signal_date"})
    result = result.merge(
        timing,
        on="signal_date",
        how="left",
        validate="many_to_one",
        sort=False,
    )
    available = result["market_timing_source_date"].notna()
    for column in timing_columns[1:]:
        result[column] = result[column].fillna("UNKNOWN").astype(str)
    result["market_timing_evidence"] = np.where(available, "available", "missing")
    result["market_timing_feature_cutoff_date"] = result["signal_date"]
    result["market_regime"] = result["active_direction"] + "/" + result["danger_state"]
    return result


def replay_dynamic_leader_paths(
    leader_paths: pd.DataFrame,
    market_timing: pd.DataFrame,
    *,
    support_match_mode: str = MINIMUM_REQUIRED_SUPPORT,
) -> ReplayResult:
    """Replay every retained stock campaign without fixed future windows."""

    prepared = prepare_dynamic_leader_paths(
        leader_paths,
        market_timing,
        support_match_mode=support_match_mode,
    )
    signals = prepared.signals
    campaigns = prepared.campaigns
    trade_parts: list[pd.DataFrame] = []
    if not signals.empty:
        trade_parts.append(
            execute_prepared_close_trades(signals, campaigns).assign(
                variant="base_confirmation"
            )
        )
        non_contraction = signals.loc[
            signals["non_contraction_confirmation"].astype(bool)
        ]
        trade_parts.append(
            execute_prepared_close_trades(non_contraction, campaigns).assign(
                variant="non_contraction_confirmation"
            )
        )
        gold_signals = select_gold_strong_reclaim_signals(signals)
        signals[GOLD_STRONG_RECLAIM_VARIANT] = signals["signal_id"].isin(
            gold_signals["signal_id"]
        )
        trade_parts.append(
            execute_prepared_close_trades(gold_signals, campaigns).assign(
                variant=GOLD_STRONG_RECLAIM_VARIANT
            )
        )
        cross_regime_signals = select_cross_regime_support_reclaim_signals(signals)
        signals[CROSS_REGIME_SUPPORT_RECLAIM_VARIANT] = signals["signal_id"].isin(
            cross_regime_signals["signal_id"]
        )
        trade_parts.append(
            execute_prepared_close_trades(cross_regime_signals, campaigns).assign(
                variant=CROSS_REGIME_SUPPORT_RECLAIM_VARIANT
            )
        )
    trades = _attach_trade_market_timing(_concat(trade_parts), signals)
    return ReplayResult(
        signals=signals,
        trades=trades,
        waves=prepared.waves,
        exclusions=prepared.exclusions,
        daily_ledger=campaigns.daily_ledger,
    )


def prepare_dynamic_leader_paths(
    leader_paths: pd.DataFrame,
    market_timing: pd.DataFrame,
    *,
    support_match_mode: str = MINIMUM_REQUIRED_SUPPORT,
) -> DynamicLeaderPreparation:
    """Build replayable dynamic-leader states without executing trade variants."""

    if leader_paths.empty:
        return _empty_dynamic_leader_preparation()
    replay_paths, exclusions = _select_replayable_leader_paths(leader_paths)
    if replay_paths.empty:
        return DynamicLeaderPreparation(
            campaigns=CampaignPreparation(
                paths=pd.DataFrame(),
                signals=pd.DataFrame(),
                daily_ledger=pd.DataFrame(),
            ),
            signals=pd.DataFrame(),
            waves=pd.DataFrame(),
            exclusions=exclusions,
        )
    campaigns = prepare_stock_campaigns(
        replay_paths,
        support_match_mode=support_match_mode,
    )
    signals = attach_signal_market_timing(campaigns.signals, market_timing)
    waves = _summarize_replay_waves(
        campaigns.daily_ledger,
        replay_paths=campaigns.paths,
        signals=signals,
    )
    return DynamicLeaderPreparation(
        campaigns=campaigns,
        signals=signals,
        waves=waves,
        exclusions=exclusions,
    )


def _select_replayable_leader_paths(
    leader_paths: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required_complete = (
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "turnover",
        "daily_return_pct",
        "ma5",
        "ma10",
        "ma20",
        "prior_high20",
        "volume_ratio_prior5",
        "close_location",
    )
    identity_columns = ["campaign_id", "vt_symbol"]
    ordered = leader_paths.sort_values(
        [*identity_columns, "trade_date"], kind="stable"
    ).reset_index(drop=True)
    complete_rows = ordered[list(required_complete)].notna().all(axis=1)
    groups = [ordered[column] for column in identity_columns]
    complete_paths = complete_rows.groupby(groups, sort=False).transform("all")
    path_sizes = ordered.groupby(identity_columns, sort=False)["trade_date"].transform(
        "size"
    )
    valid_paths = complete_paths & path_sizes.ge(2)
    exclusions = _build_replay_exclusions(
        ordered,
        complete_rows=complete_rows,
        valid_paths=valid_paths,
    )
    replay_paths = ordered.loc[valid_paths].reset_index(drop=True)
    return replay_paths, exclusions


def _empty_dynamic_leader_preparation() -> DynamicLeaderPreparation:
    empty = pd.DataFrame()
    return DynamicLeaderPreparation(
        campaigns=CampaignPreparation(
            paths=empty.copy(),
            signals=empty.copy(),
            daily_ledger=empty.copy(),
        ),
        signals=empty.copy(),
        waves=empty.copy(),
        exclusions=empty.copy(),
    )


def _attach_trade_market_timing(
    trades: pd.DataFrame,
    signals: pd.DataFrame,
) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    context_columns = [
        "signal_id",
        "active_direction",
        "danger_state",
        "market_phase",
        "market_regime",
        "market_timing_evidence",
        "market_timing_feature_cutoff_date",
    ]
    _require_columns(signals, context_columns, "timed leader pullback signal")
    context = signals.loc[:, context_columns]
    if context["signal_id"].duplicated().any():
        raise ValueError("signal market timing identities must be unique")
    return trades.merge(
        context,
        on="signal_id",
        how="left",
        validate="many_to_one",
        sort=False,
    )


def _build_replay_exclusions(
    paths: pd.DataFrame,
    *,
    complete_rows: pd.Series,
    valid_paths: pd.Series,
) -> pd.DataFrame:
    invalid = paths.loc[~valid_paths, ["campaign_id", "vt_symbol"]].drop_duplicates()
    if invalid.empty:
        return pd.DataFrame(
            columns=["campaign_id", "vt_symbol", "path_rows", "missing_rows", "reason"]
        )
    audit = (
        paths.assign(_complete=complete_rows)
        .groupby(["campaign_id", "vt_symbol"], sort=False)
        .agg(path_rows=("trade_date", "size"), complete_rows=("_complete", "sum"))
    )
    audit["missing_rows"] = audit["path_rows"] - audit["complete_rows"]
    result = invalid.merge(
        audit.reset_index(),
        on=["campaign_id", "vt_symbol"],
        how="left",
        validate="one_to_one",
    )
    result["reason"] = "incomplete_stock_campaign_path"
    return result.loc[
        :, ["campaign_id", "vt_symbol", "path_rows", "missing_rows", "reason"]
    ]


def _summarize_replay_waves(
    daily: pd.DataFrame,
    *,
    replay_paths: pd.DataFrame,
    signals: pd.DataFrame,
) -> pd.DataFrame:
    active = daily.loc[daily["wave_number"].gt(0)].copy()
    if active.empty:
        return pd.DataFrame()
    group_columns = ["campaign_id", "vt_symbol", "wave_number"]
    active["record_high_price"] = pd.to_numeric(
        active["record_high_price"], errors="coerce"
    )
    active["deepest_tested_depth"] = pd.to_numeric(
        active["deepest_tested_depth"], errors="coerce"
    )
    waves = active.groupby(group_columns, sort=False, as_index=False).agg(
        wave_start_date=("trade_date", "min"),
        wave_end_date=("trade_date", "max"),
        record_high_price=("record_high_price", "max"),
        higher_high_confirmed=("higher_high_today", "any"),
        deepest_tested_depth=("deepest_tested_depth", "max"),
        terminal_state=("state", "last"),
    )
    metadata = replay_paths.loc[
        :, ["campaign_id", "vt_symbol", "sector_id", "concept_name"]
    ].drop_duplicates()
    if metadata.duplicated(["campaign_id", "vt_symbol"]).any():
        raise ValueError("stock campaign metadata must be unique")
    waves = waves.merge(
        metadata,
        on=["campaign_id", "vt_symbol"],
        how="left",
        validate="many_to_one",
    )
    if signals.empty:
        waves["signal_count"] = 0
    else:
        counts = (
            signals.groupby(group_columns, sort=False).size().rename("signal_count")
        )
        waves = waves.merge(
            counts.reset_index(),
            on=group_columns,
            how="left",
            validate="one_to_one",
        )
        waves["signal_count"] = waves["signal_count"].fillna(0).astype(int)
    waves["deepest_tested_support"] = waves["deepest_tested_depth"].map(
        {1: "ma5", 2: "ma10", 3: "ma20"}
    )
    waves["wave_number"] = waves["wave_number"].astype(int)
    waves["higher_high_confirmed"] = waves["higher_high_confirmed"].astype(bool)
    return (
        waves.loc[
            :,
            [
                "campaign_id",
                "sector_id",
                "concept_name",
                "vt_symbol",
                "wave_number",
                "wave_start_date",
                "wave_end_date",
                "record_high_price",
                "higher_high_confirmed",
                "deepest_tested_support",
                "signal_count",
                "terminal_state",
            ],
        ]
        .sort_values(group_columns, kind="stable")
        .reset_index(drop=True)
    )


def select_non_overlapping_trades(trades: pd.DataFrame) -> pd.DataFrame:
    """Resolve duplicate concept identities and overlapping same-stock positions."""

    if trades.empty:
        return trades.copy()
    frame = trades.copy()
    for column in ("entry_date", "exit_date"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.normalize()
    frame = frame.sort_values(
        ["variant", "entry_date", "dynamic_rank", "signal_id"], kind="stable"
    ).drop_duplicates(["variant", "vt_symbol", "entry_date"], keep="first")
    retained = []
    for _, group in frame.groupby(["variant", "vt_symbol"], sort=False):
        occupied_through: pd.Timestamp | None = None
        for index, trade in group.sort_values("entry_date", kind="stable").iterrows():
            entry_date = pd.Timestamp(trade["entry_date"])
            if occupied_through is not None and entry_date <= occupied_through:
                continue
            retained.append(index)
            exit_date = trade["exit_date"]
            occupied_through = (
                pd.Timestamp.max.normalize()
                if pd.isna(exit_date)
                else pd.Timestamp(exit_date)
            )
    selected = frame.loc[retained].copy()
    return assign_trade_time_blocks(selected)


def assign_trade_time_blocks(trades: pd.DataFrame) -> pd.DataFrame:
    result = trades.copy()
    if result.empty:
        result["time_block"] = pd.Series(dtype=str)
        return result
    _require_columns(result, ("variant", "entry_date"), "trade time block")
    entry_dates = pd.to_datetime(result["entry_date"], errors="raise").dt.normalize()
    block_labels = pd.Series(index=result.index, dtype=str)
    for positions in result.groupby("variant", sort=False).indices.values():
        variant_dates = entry_dates.iloc[positions]
        block_labels.iloc[positions] = variant_dates.map(
            _build_time_block_map(variant_dates)
        )
    result["time_block"] = block_labels
    return result.sort_values(
        ["entry_date", "variant", "dynamic_rank", "signal_id"], kind="stable"
    ).reset_index(drop=True)


def _build_time_block_map(entry_dates: pd.Series) -> dict[pd.Timestamp, str]:
    dates = sorted(entry_dates.unique())
    return {
        pd.Timestamp(trade_date): (
            f"block_{min(position * TIME_BLOCK_COUNT // len(dates) + 1, TIME_BLOCK_COUNT)}"
        )
        for position, trade_date in enumerate(dates)
    }


def simulate_four_slot_cash(
    trades: pd.DataFrame,
    stock_bars: pd.DataFrame,
    *,
    initial_cash: float = 100_000.0,
    capacity: int = 4,
) -> dict[str, Any]:
    """Simulate a no-leverage close-price account with one slot per concept."""

    closed = trades.loc[
        trades.get("exit_date", pd.Series(dtype="datetime64[ns]")).notna()
        & trades.get("net_return_pct", pd.Series(dtype=float)).notna()
    ].copy()
    if closed.empty:
        return _empty_cash_result(initial_cash, capacity)
    for column in ("entry_date", "exit_date"):
        closed[column] = pd.to_datetime(closed[column], errors="raise").dt.normalize()
    bars = stock_bars.loc[
        stock_bars["vt_symbol"]
        .astype(str)
        .isin(closed["vt_symbol"].astype(str).unique()),
        ["vt_symbol", "trade_date", "close_price"],
    ].copy()
    bars["trade_date"] = pd.to_datetime(
        bars["trade_date"], errors="raise"
    ).dt.normalize()
    close_by_symbol = {
        str(symbol): group.set_index("trade_date")["close_price"].astype(float)
        for symbol, group in bars.groupby("vt_symbol", sort=False)
    }
    calendar = sorted(
        bars.loc[
            bars["trade_date"].between(
                closed["entry_date"].min(), closed["exit_date"].max()
            ),
            "trade_date",
        ].unique()
    )
    entries = {
        pd.Timestamp(trade_date): group.sort_values(
            ["dynamic_rank", "signal_id"], kind="stable"
        )
        for trade_date, group in closed.groupby("entry_date", sort=True)
    }
    cash = float(initial_cash)
    positions: dict[str, dict[str, Any]] = {}
    accepted: list[dict[str, Any]] = []
    skip_reasons: dict[str, int] = {}
    equity_curve = [float(initial_cash)]

    for raw_date in calendar:
        trade_date = pd.Timestamp(raw_date)
        due = sorted(
            signal_id
            for signal_id, position in positions.items()
            if pd.Timestamp(position["exit_date"]) <= trade_date
        )
        for signal_id in due:
            position = positions.pop(signal_id)
            cash += float(position["allocation"]) * (
                1.0 + float(position["net_return_pct"]) / 100.0
            )
            accepted.append(position)
        equity = cash + sum(
            _marked_position_value(position, close_by_symbol, trade_date)
            for position in positions.values()
        )
        target = equity / capacity
        for trade in entries.get(trade_date, pd.DataFrame()).to_dict("records"):
            reason = _cash_entry_rejection(trade, positions, capacity, cash, target)
            if reason is not None:
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                continue
            allocation = min(target, cash)
            cash -= allocation
            positions[str(trade["signal_id"])] = {
                **trade,
                "allocation": allocation,
            }
        equity_curve.append(
            cash
            + sum(
                _marked_position_value(position, close_by_symbol, trade_date)
                for position in positions.values()
            )
        )
    final_equity = float(equity_curve[-1])
    equity = pd.Series(equity_curve, dtype=float)
    drawdown = equity / equity.cummax() - 1.0
    wins = sum(float(row["net_return_pct"]) > 0 for row in accepted)
    return {
        "initial_cash": float(initial_cash),
        "capacity": capacity,
        "final_equity": final_equity,
        "compound_return_pct": (final_equity / initial_cash - 1.0) * 100.0,
        "maximum_drawdown_pct": float(drawdown.min() * 100.0),
        "signals": int(len(closed)),
        "accepted_entries": int(len(accepted) + len(positions)),
        "closed_trades": int(len(accepted)),
        "winning_trades": int(wins),
        "cash_win_rate_pct": wins / len(accepted) * 100.0 if accepted else None,
        "open_positions": int(len(positions)),
        "skip_reasons": dict(sorted(skip_reasons.items())),
    }


def _cash_entry_rejection(
    trade: Mapping[str, Any],
    positions: Mapping[str, Mapping[str, Any]],
    capacity: int,
    cash: float,
    target: float,
) -> str | None:
    if len(positions) >= capacity:
        return "capacity_full"
    if any(
        str(position["sector_id"]) == str(trade["sector_id"])
        for position in positions.values()
    ):
        return "same_concept_position"
    if any(
        str(position["vt_symbol"]) == str(trade["vt_symbol"])
        for position in positions.values()
    ):
        return "same_stock_position"
    if cash <= 0 or target <= 0:
        return "insufficient_cash"
    return None


def _marked_position_value(
    position: Mapping[str, Any],
    close_by_symbol: Mapping[str, pd.Series],
    trade_date: pd.Timestamp,
) -> float:
    series = close_by_symbol.get(str(position["vt_symbol"]))
    if series is None:
        return float(position["allocation"])
    available = series.loc[series.index <= trade_date]
    if available.empty:
        return float(position["allocation"])
    return (
        float(position["allocation"])
        * float(available.iloc[-1])
        / float(position["entry_price"])
    )


def build_leader_spell_ledger(leader_paths: pd.DataFrame) -> pd.DataFrame:
    if leader_paths.empty:
        return pd.DataFrame()
    top3 = leader_paths.loc[leader_paths["dynamic_top3"].astype(bool)].copy()
    if top3.empty:
        return pd.DataFrame()
    top3 = top3.sort_values(["campaign_id", "vt_symbol", "campaign_day"], kind="stable")
    group = [top3["campaign_id"], top3["vt_symbol"]]
    top3["spell_number"] = (
        top3["campaign_day"]
        .groupby(group, sort=False)
        .diff()
        .ne(1)
        .groupby(group, sort=False)
        .cumsum()
    )
    return (
        top3.groupby(
            [
                "campaign_id",
                "sector_id",
                "concept_name",
                "vt_symbol",
                "stock_name",
                "spell_number",
            ],
            sort=False,
        )
        .agg(
            spell_start=("trade_date", "min"),
            spell_end=("trade_date", "max"),
            top3_days=("trade_date", "nunique"),
            best_rank=("dynamic_rank", "min"),
            start_leg_gain_pct=("leg_gain_pct", "first"),
            end_leg_gain_pct=("leg_gain_pct", "last"),
            maximum_leg_gain_pct=("leg_gain_pct", "max"),
        )
        .reset_index()
        .sort_values(["spell_start", "campaign_id", "best_rank"], kind="stable")
        .reset_index(drop=True)
    )


def build_named_case_audit(
    leader_paths: pd.DataFrame,
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    waves: pd.DataFrame,
    daily_ledger: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows = []
    for symbol, name in REFERENCE_SYMBOLS.items():
        paths = leader_paths.loc[
            leader_paths.get("vt_symbol", pd.Series(dtype=str)).eq(symbol)
        ]
        case_signals = signals.loc[
            signals.get("vt_symbol", pd.Series(dtype=str)).eq(symbol)
        ]
        case_trades = trades.loc[
            trades.get("vt_symbol", pd.Series(dtype=str)).eq(symbol)
        ]
        case_waves = waves.loc[waves.get("vt_symbol", pd.Series(dtype=str)).eq(symbol)]
        case_daily = daily_ledger.loc[
            daily_ledger.get("vt_symbol", pd.Series(dtype=str)).eq(symbol)
        ]
        if "confirmation_status" in case_daily:
            pullback_confirmations = case_daily.loc[
                case_daily["confirmation_status"].astype(str).ne("not_in_pullback")
            ]
            status_counts = {
                str(status): int(count)
                for status, count in pullback_confirmations["confirmation_status"]
                .value_counts(sort=False)
                .items()
            }
        else:
            pullback_confirmations = pd.DataFrame()
            status_counts = {}
        rows.append(
            {
                "vt_symbol": symbol,
                "stock_name": name,
                "leader_detected": bool(
                    not paths.empty and paths["dynamic_top3"].astype(bool).any()
                ),
                "first_top3_date": _date_or_none(
                    paths.loc[paths["dynamic_top3"].astype(bool), "trade_date"].min()
                    if not paths.empty
                    else None
                ),
                "last_top3_date": _date_or_none(
                    paths.loc[paths["dynamic_top3"].astype(bool), "trade_date"].max()
                    if not paths.empty
                    else None
                ),
                "campaigns": int(paths["campaign_id"].nunique())
                if not paths.empty
                else 0,
                "waves": int(len(case_waves)),
                "signals": int(len(case_signals)),
                "executed_trades": int(len(case_trades)),
                "confirmation_status_counts": status_counts,
                "pullback_confirmation_rows": _records(pullback_confirmations),
                "wave_rows": _records(case_waves),
                "signal_rows": _records(case_signals),
                "trade_rows": _records(case_trades),
            }
        )
    return rows


def build_causal_leader_pullback_report(
    *,
    coverage: Mapping[str, Any],
    fingerprints: Mapping[str, Mapping[str, Any]],
    campaigns: pd.DataFrame,
    leader_paths: pd.DataFrame,
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    leader_spells: pd.DataFrame,
    waves: pd.DataFrame,
    case_audit: Sequence[Mapping[str, Any]],
    cash_results: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a complete proxy result while keeping formal metrics null."""

    overall_metrics = [
        {
            "variant": variant,
            **summarize_trade_metrics(_variant_trades(trades, variant)),
        }
        for variant in VARIANTS
    ]
    time_block_metrics = [
        {
            "variant": variant,
            "time_block": f"block_{block}",
            **summarize_trade_metrics(
                _variant_trades(trades, variant, block=f"block_{block}")
            ),
        }
        for variant in VARIANTS
        for block in range(1, TIME_BLOCK_COUNT + 1)
    ]
    market_phase_metrics = _group_metrics(trades, "market_phase")
    decisions = [
        _variant_decision(
            variant,
            overall_metrics,
            time_block_metrics,
            market_phase_metrics,
            cash_results.get(variant, {}),
            strict_membership_rows=int(
                coverage.get("strict_historical_membership_rows") or 0
            ),
        )
        for variant in VARIANTS
    ]
    return _json_safe(
        {
            "study_version": STUDY_VERSION,
            "algorithm_version": ALGORITHM_VERSION,
            "policy_version": CROSS_REGIME_POLICY_VERSION,
            "research_status": "historical_proxy_cross_regime_evaluated",
            "formal_strategy": False,
            "formal_metrics": None,
            "contract": {
                "universe": "eligible SSE/SZSE main board; no ChiNext/STAR/BSE/ST",
                "concept_campaign": (
                    "20d breakout + 5d relative top20% + turnover expansion>=1.2; "
                    "end after three closes at least 5% below running peak"
                ),
                "leader_rank": (
                    "complete current-member denominator; ignition leg gain, strong-day "
                    "count, concept excess, turnover expansion; lexicographic Top3"
                ),
                "stock_ignition": "return>=5%, close>prior20 high, volume>=1.5x",
                "wave": "record high -> visible 5% pullback -> later higher high",
                "first_pullback": "test MA5, then wait for a later confirming close",
                "later_pullback": "test MA10, then wait for a later confirming close",
                "confirmation": "hold tested line and close above prior close or upper-half",
                "entry": "D completed close research proxy",
                "d1_exit": "D+1 close when cost-adjusted return is <=0",
                "winner_exit": "first higher high, structural break, or concept end close",
                "same_wave_reentry": (
                    "support must be deeper and its test date must follow the prior loss exit"
                ),
                "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
                "variants": {
                    "base_confirmation": "all causal confirmations",
                    "non_contraction_confirmation": (
                        f"same confirmations with volume_ratio_prior5>={NON_CONTRACTION_VOLUME_RATIO}"
                    ),
                    GOLD_STRONG_RECLAIM_VARIANT: (
                        "GOLD/NORMAL only; confirmation return>=8%, close within 5% "
                        "of the visible peak, one or two sessions after the support test"
                    ),
                    CROSS_REGIME_SUPPORT_RECLAIM_VARIANT: (
                        "GOLD/NORMAL rotation uses strong reclaim; warming additionally "
                        f"requires confirmation low no more than {SUPPORT_TOLERANCE_PCT:g}% "
                        "below the tested support"
                    ),
                },
                "market_policy": {
                    "GOLD/NORMAL+rotation": CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
                    "GOLD/NORMAL+warming": (
                        f"{CROSS_REGIME_SUPPORT_RECLAIM_VARIANT}+support_floor"
                    ),
                    "GOLD/NORMAL+uptrend": "cash_insufficient_sample",
                    "GOLD/NORMAL+retreat": "cash",
                    "SILVER/NORMAL": "cash",
                    "NEUTRAL/NORMAL": "cash",
                    "GOLD/DANGER": "cash",
                    "SILVER/DANGER": "cash",
                    "UNKNOWN": "cash",
                },
            },
            "data_quality": {
                "membership_evidence": MEMBERSHIP_EVIDENCE_LEVEL,
                "strict_historical_membership": False,
                "known_bias": (
                    "current 2026 membership is replayed backward; historical additions, "
                    "deletions and historical ST status are incomplete"
                ),
                "same_close_execution": "research proxy, not guaranteed executable fill",
                "minutes_used": False,
                "fund_flow_used": False,
                "gold_silver_used_for_selection": True,
                "market_timing_alignment": "source_date equals completed signal_date",
                "old_low_suction_outcomes_used": False,
            },
            "coverage": {
                **dict(coverage),
                "concept_campaigns": int(len(campaigns)),
                "leader_path_rows": int(len(leader_paths)),
                "leader_stock_campaigns": _nunique_pairs(
                    leader_paths, ("campaign_id", "vt_symbol")
                ),
                "candidate_signals": int(len(signals)),
                "selected_trade_rows": int(len(trades)),
                "leader_spells": int(len(leader_spells)),
                "wave_rows": int(len(waves)),
                "market_timing_available_signals": int(
                    signals.get("market_timing_evidence", pd.Series(dtype=str))
                    .eq("available")
                    .sum()
                ),
            },
            "decisions": decisions,
            "overall_metrics": overall_metrics,
            "time_block_metrics": time_block_metrics,
            "cash_results": dict(cash_results),
            "signal_funnel": {
                "base_confirmations": int(len(signals)),
                "non_contraction_confirmations": int(
                    signals.get("non_contraction_confirmation", pd.Series(dtype=bool))
                    .astype(bool)
                    .sum()
                ),
                "base_selected_trades": int(
                    len(_variant_trades(trades, "base_confirmation"))
                ),
                "non_contraction_selected_trades": int(
                    len(_variant_trades(trades, "non_contraction_confirmation"))
                ),
                "gold_strong_reclaim_confirmations": int(
                    signals.get(GOLD_STRONG_RECLAIM_VARIANT, pd.Series(dtype=bool))
                    .astype(bool)
                    .sum()
                ),
                "gold_strong_reclaim_selected_trades": int(
                    len(_variant_trades(trades, GOLD_STRONG_RECLAIM_VARIANT))
                ),
                "cross_regime_support_reclaim_confirmations": int(
                    signals.get(
                        CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
                        pd.Series(dtype=bool),
                    )
                    .astype(bool)
                    .sum()
                ),
                "cross_regime_support_reclaim_selected_trades": int(
                    len(
                        _variant_trades(
                            trades,
                            CROSS_REGIME_SUPPORT_RECLAIM_VARIANT,
                        )
                    )
                ),
            },
            "support_metrics": _group_metrics(trades, "support_line"),
            "wave_metrics": _group_metrics(trades, "wave_number"),
            "rank_metrics": _group_metrics(trades, "dynamic_rank"),
            "exit_metrics": _group_metrics(trades, "exit_reason"),
            "market_regime_metrics": _group_metrics(trades, "market_regime"),
            "market_phase_metrics": market_phase_metrics,
            "named_case_audit": list(case_audit),
            "representative_winners": _representative_trades(trades, largest=True),
            "representative_losses": _representative_trades(trades, largest=False),
            "leader_spell_ledger": _records(leader_spells),
            "wave_ledger": _records(waves),
            "candidate_signal_ledger": _records(signals),
            "trade_ledger": _records(trades),
            "fingerprints": dict(fingerprints),
            "boundaries": [
                "Every signal uses only fields known at its completed D close.",
                "Current memberships provide a broad denominator but are not point-in-time history.",
                "Five blocks measure chronological stability; prior research makes them reused history, not a new holdout.",
                "GOLD/NORMAL rotation trades strong reclaim; warming also requires the confirmation low to hold the tested support tolerance.",
                "Uptrend remains cash because its material sample is insufficient; retreat, SILVER, NEUTRAL, DANGER and UNKNOWN remain cash states.",
                "Minute bars and fund flow do not select or remove a candidate in this run.",
                "Formal metrics remain null until strict membership and forward evidence gates pass.",
            ],
            "reproduce": (
                "legacy CLI retired; use the daily-factor-* commands for current "
                "low-suction research"
            ),
        }
    )


def run_causal_leader_pullback_study() -> dict[str, Any]:
    """Run the complete daily algorithm from raw database inputs."""

    from .research_protocol import fingerprint_frame

    inputs = load_causal_leader_pullback_inputs()
    coverage = dict(inputs.coverage)
    fingerprints = dict(inputs.fingerprints)
    concept_bars = inputs.concept_bars
    memberships = inputs.memberships
    market_timing = inputs.market_timing
    stock_features = build_causal_stock_features(inputs.stock_bars)
    del inputs

    campaigns, campaign_paths = build_concept_campaign_ledger(concept_bars)
    leader_paths, rank_coverage = build_dynamic_leader_paths(
        campaign_paths, memberships, stock_features
    )
    replay = replay_dynamic_leader_paths(leader_paths, market_timing)
    selected_trades = select_non_overlapping_trades(replay.trades)
    cash_results = {
        variant: simulate_four_slot_cash(
            _variant_trades(selected_trades, variant), stock_features
        )
        for variant in VARIANTS
    }
    spells = build_leader_spell_ledger(leader_paths)
    case_audit = build_named_case_audit(
        leader_paths,
        replay.signals,
        selected_trades,
        replay.waves,
        replay.daily_ledger,
    )
    coverage.update(rank_coverage)
    coverage.update(
        {
            "replayed_stock_campaigns": _nunique_pairs(
                leader_paths, ("campaign_id", "vt_symbol")
            ),
            "incomplete_replay_paths": int(len(replay.exclusions)),
        }
    )
    generated = {
        "concept_campaigns": fingerprint_frame(
            campaigns, identity_columns=("campaign_id",)
        ).as_dict(),
        "dynamic_leader_paths": fingerprint_frame(
            leader_paths.loc[
                :,
                [
                    "campaign_id",
                    "trade_date",
                    "vt_symbol",
                    "dynamic_rank",
                    "dynamic_top3",
                    "leg_gain_pct",
                ],
            ],
            identity_columns=("campaign_id", "trade_date", "vt_symbol"),
        ).as_dict(),
        "pullback_signals": fingerprint_frame(
            replay.signals, identity_columns=("signal_id",)
        ).as_dict(),
        "selected_trades": fingerprint_frame(
            selected_trades,
            identity_columns=("variant", "signal_id"),
        ).as_dict(),
    }
    return build_causal_leader_pullback_report(
        coverage=coverage,
        fingerprints={**fingerprints, **generated},
        campaigns=campaigns,
        leader_paths=leader_paths,
        signals=replay.signals,
        trades=selected_trades,
        leader_spells=spells,
        waves=replay.waves,
        case_audit=case_audit,
        cash_results=cash_results,
    )


def render_causal_leader_pullback_json(report: Mapping[str, Any]) -> str:
    return (
        json.dumps(
            _json_safe(dict(report)), ensure_ascii=False, indent=2, sort_keys=True
        )
        + "\n"
    )


def render_causal_leader_pullback_markdown(report: Mapping[str, Any]) -> str:
    coverage = _mapping(report.get("coverage"))
    decisions = _sequence(report.get("decisions"))
    lines = [
        "# AlphaAgent 动态龙头主升低吸算法",
        "",
        f"算法：`{report.get('policy_version') or report.get('algorithm_version')}`；状态：`{report.get('research_status')}`；正式策略：`false`。",
        "",
        "## 最终算法",
        "",
        "1. 概念指数以 20 日突破、相对强度和成交额扩张点火，连续三日从峰值回撤 5% 后结束。",
        "2. 在完整当前成员分母中，按点火以来涨幅、强势日、概念超额和成交额扩张逐日计算 Top3。",
        "3. 个股必须先出现涨幅至少 5%、收盘越前 20 日高点、成交量至少 1.5 倍的点火。",
        "4. 第一轮回调先测试 MA5；创新高后的第二轮及以后先测试 MA10；测试日不能直接买。",
        "5. 测试后的完成日线守住支撑，且收盘高于前收或位于日内上半区，D 收盘作为低吸代理。",
        "6. GOLD/NORMAL 的 rotation 使用强收复；warming 还要求确认日最低价不跌破已测试支撑的 2% 容差下沿。",
        "7. uptrend 样本不足，retreat、SILVER、任意 DANGER 和 UNKNOWN 当前空仓。",
        "8. D+1 扣 0.2% 成本后不盈利直接收盘退出；盈利则持有到越前高、结构破坏或概念结束。",
        "9. 同一浪止损后，只有更深支撑且支撑测试日晚于止损日才允许再入。",
        "",
        "## Coverage",
        "",
        f"- 概念 `{coverage.get('concepts', 0)}`；campaign `{coverage.get('concept_campaigns', 0)}`；"
        f"当前成员关系 `{coverage.get('current_membership_rows', 0)}`；主板日线 `{coverage.get('stock_bar_rows', 0)}`。",
        f"- 展开成员日 `{coverage.get('expanded_member_date_rows', 0)}`；动态 Top3 日 `{coverage.get('dynamic_top3_rows', 0)}`；"
        f"逐股 campaign `{coverage.get('replayed_stock_campaigns', 0)}`；波段 `{coverage.get('wave_rows', 0)}`。",
        f"- 行情状态 `{coverage.get('market_timing_rows_read', 0)}` 日；信号同日命中 "
        f"`{coverage.get('market_timing_available_signals', 0)}`；分钟线、资金流和旧低吸结果读取均为 0。",
        "",
        "## Environment Policy",
        "",
        "| Environment | Action |",
        "| --- | --- |",
        f"| `GOLD/NORMAL + rotation` | `{CROSS_REGIME_SUPPORT_RECLAIM_VARIANT}` |",
        f"| `GOLD/NORMAL + warming` | `{CROSS_REGIME_SUPPORT_RECLAIM_VARIANT} + support_floor` |",
        "| `GOLD/NORMAL + uptrend` | `cash_insufficient_sample` |",
        "| `GOLD/NORMAL + retreat` | `cash` |",
        "| `SILVER/NORMAL` | `cash` |",
        "| `NEUTRAL/NORMAL` | `cash` |",
        "| `GOLD/DANGER` | `cash` |",
        "| `SILVER/DANGER` | `cash` |",
        "| `UNKNOWN` | `cash` |",
        "",
        "## Overall",
        "",
        "| Variant | Closed | Win rate | Mean | PF | Signal compound | Max DD | Cash compound | Cash DD |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        *_overall_metric_lines(report),
        "",
        "## Five Time Blocks",
        "",
        "| Variant | Block | Closed | Win rate | Mean | PF | Compound | Max DD |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        *_block_metric_lines(report),
        "",
        "## Decision",
        "",
        *[
            f"- `{item.get('variant')}`：历史代理门="
            f"`{str(item.get('historical_proxy_gate_passed')).lower()}`；正式状态="
            f"`{item.get('status')}`；失败门："
            f"`{', '.join(item.get('failed_gates') or []) or 'none'}`。"
            for item in decisions
        ],
        "",
        "## Named Cases",
        "",
        *_case_lines(report.get("named_case_audit")),
        "",
        "## Data Boundary",
        "",
        "本轮 Top3 分母比旧涨停原因候选更完整，但仍是当前成员幸存者代理，不是历史点时成员。",
        "因此历史指标可以评价算法形状，不能升级为正式可交易胜率；正式指标继续为 `null`。",
        "",
        "## Reproduce",
        "",
        "```bash",
        str(report.get("reproduce") or ""),
        "```",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _variant_decision(
    variant: str,
    overall_metrics: Sequence[Mapping[str, Any]],
    block_metrics: Sequence[Mapping[str, Any]],
    market_phase_metrics: Sequence[Mapping[str, Any]],
    cash: Mapping[str, Any],
    *,
    strict_membership_rows: int,
) -> dict[str, Any]:
    overall = next(
        (row for row in overall_metrics if row.get("variant") == variant), {}
    )
    blocks = [row for row in block_metrics if row.get("variant") == variant]
    failed = []
    if int(overall.get("closed_trades") or 0) < MIN_CLOSED_TRADES:
        failed.append("closed_trades<100")
    if float(overall.get("positive_rate_pct") or 0.0) <= MIN_WIN_RATE_PCT:
        failed.append("win_rate<=60pct")
    if float(overall.get("mean_net_return_pct") or 0.0) <= 0:
        failed.append("mean_return<=0")
    if float(overall.get("profit_factor") or 0.0) < MIN_PROFIT_FACTOR:
        failed.append("profit_factor<1.2")
    minimum_block_trades = (
        MIN_CROSS_REGIME_BLOCK_TRADES
        if variant == CROSS_REGIME_SUPPORT_RECLAIM_VARIANT
        else MIN_BLOCK_TRADES
    )
    stable_blocks = sum(
        int(row.get("closed_trades") or 0) >= minimum_block_trades
        and float(row.get("positive_rate_pct") or 0.0) > MIN_WIN_RATE_PCT
        and float(row.get("mean_net_return_pct") or 0.0) > 0.0
        for row in blocks
    )
    if stable_blocks < MIN_STABLE_TIME_BLOCKS:
        failed.append("stable_time_blocks<3")
    if float(cash.get("compound_return_pct") or 0.0) <= MIN_CASH_COMPOUND_PCT:
        failed.append("cash_compound<=60pct")
    cash_drawdown = _finite_or_none(cash.get("maximum_drawdown_pct"))
    if (cash_drawdown if cash_drawdown is not None else -100.0) < MIN_CASH_DRAWDOWN_PCT:
        failed.append("cash_drawdown<-10pct")
    qualified_market_phases = sorted(
        str(row.get("group"))
        for row in market_phase_metrics
        if row.get("variant") == variant
        and int(row.get("closed_trades") or 0) >= MIN_MARKET_PHASE_TRADES
        and float(row.get("positive_rate_pct") or 0.0) > MIN_WIN_RATE_PCT
        and float(row.get("compound_return_pct") or 0.0) > 0.0
    )
    if (
        variant == CROSS_REGIME_SUPPORT_RECLAIM_VARIANT
        and len(qualified_market_phases) < MIN_QUALIFIED_MARKET_PHASES
    ):
        failed.append("qualified_market_phases<2")
    if strict_membership_rows == 0:
        failed.append("strict_historical_membership_missing")
    return {
        "variant": variant,
        "status": "not_qualified" if failed else "qualified",
        "historical_proxy_gate_passed": not any(
            gate for gate in failed if gate != "strict_historical_membership_missing"
        ),
        "stable_time_blocks": int(stable_blocks),
        "qualified_market_phases": qualified_market_phases,
        "failed_gates": failed,
    }


def _variant_trades(
    trades: pd.DataFrame,
    variant: str,
    *,
    block: str | None = None,
) -> pd.DataFrame:
    if trades.empty or "variant" not in trades:
        return pd.DataFrame()
    selected = trades.loc[trades["variant"].eq(variant)]
    if block is not None:
        if "time_block" not in selected:
            return pd.DataFrame()
        selected = selected.loc[selected["time_block"].eq(block)]
    return selected.copy()


def _group_metrics(trades: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    if trades.empty or column not in trades:
        return []
    rows = []
    for (variant, value), group in trades.groupby(
        ["variant", column], sort=True, dropna=False
    ):
        rows.append(
            {
                "variant": str(variant),
                "group": _json_safe(value),
                **summarize_trade_metrics(group),
            }
        )
    return rows


def _representative_trades(
    trades: pd.DataFrame,
    *,
    largest: bool,
    limit: int = 20,
) -> list[dict[str, Any]]:
    if trades.empty or "net_return_pct" not in trades:
        return []
    closed = trades.loc[trades["net_return_pct"].notna()].copy()
    tie_breakers = [
        column for column in ("entry_date", "signal_id") if column in closed
    ]
    return _records(
        closed.sort_values(
            ["net_return_pct", *tie_breakers],
            ascending=[not largest, *([True] * len(tie_breakers))],
            kind="stable",
        ).head(limit)
    )


def _overall_metric_lines(report: Mapping[str, Any]) -> list[str]:
    cash = _mapping(report.get("cash_results"))
    lines = []
    for raw in _sequence(report.get("overall_metrics")):
        row = _mapping(raw)
        cash_row = _mapping(cash.get(str(row.get("variant"))))
        lines.append(
            f"| {row.get('variant')} | {row.get('closed_trades', 0)} | "
            f"{_pct(row.get('positive_rate_pct'))} | {_pct(row.get('mean_net_return_pct'))} | "
            f"{_number(row.get('profit_factor'))} | {_pct(row.get('compound_return_pct'))} | "
            f"{_pct(row.get('maximum_drawdown_pct'))} | {_pct(cash_row.get('compound_return_pct'))} | "
            f"{_pct(cash_row.get('maximum_drawdown_pct'))} |"
        )
    return lines


def _block_metric_lines(report: Mapping[str, Any]) -> list[str]:
    return [
        f"| {row.get('variant')} | {row.get('time_block')} | {row.get('closed_trades', 0)} | "
        f"{_pct(row.get('positive_rate_pct'))} | {_pct(row.get('mean_net_return_pct'))} | "
        f"{_number(row.get('profit_factor'))} | {_pct(row.get('compound_return_pct'))} | "
        f"{_pct(row.get('maximum_drawdown_pct'))} |"
        for row in map(_mapping, _sequence(report.get("time_block_metrics")))
    ]


def _case_lines(raw: object) -> list[str]:
    rows = _sequence(raw)
    if not rows:
        return ["- 无命名案例。"]
    lines = []
    for row in map(_mapping, rows):
        status_counts = _mapping(row.get("confirmation_status_counts"))
        status_text = ", ".join(
            f"{status}={count}" for status, count in status_counts.items()
        )
        status_suffix = f"；回调确认状态：`{status_text}`" if status_text else ""
        lines.append(
            f"- `{row.get('vt_symbol')}` {row.get('stock_name')}：龙头="
            f"`{str(row.get('leader_detected')).lower()}`，campaign `{row.get('campaigns', 0)}`，"
            f"波段 `{row.get('waves', 0)}`，信号 `{row.get('signals', 0)}`，"
            f"执行 `{row.get('executed_trades', 0)}`{status_suffix}。"
        )
    return lines


def _empty_cash_result(initial_cash: float, capacity: int) -> dict[str, Any]:
    return {
        "initial_cash": float(initial_cash),
        "capacity": capacity,
        "final_equity": float(initial_cash),
        "compound_return_pct": 0.0,
        "maximum_drawdown_pct": 0.0,
        "signals": 0,
        "accepted_entries": 0,
        "closed_trades": 0,
        "winning_trades": 0,
        "cash_win_rate_pct": None,
        "open_positions": 0,
        "skip_reasons": {},
    }


def _deepest_support(depths: pd.Series) -> str | None:
    numeric = pd.to_numeric(depths, errors="coerce").dropna()
    if numeric.empty or numeric.max() <= 0:
        return None
    return {1: "ma5", 2: "ma10", 3: "ma20"}.get(int(numeric.max()))


def _nunique_pairs(frame: pd.DataFrame, columns: Sequence[str]) -> int:
    if frame.empty or any(column not in frame for column in columns):
        return 0
    return int(frame.loc[:, list(columns)].drop_duplicates().shape[0])


def _date_or_none(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date().isoformat()


def _concat(parts: Sequence[pd.DataFrame]) -> pd.DataFrame:
    nonempty = [part for part in parts if not part.empty]
    return pd.concat(nonempty, ignore_index=True) if nonempty else pd.DataFrame()


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return [_json_safe(row) for row in frame.to_dict("records")]


def _json_safe(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp,)):
        return value.date().isoformat()
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _pct(value: object) -> str:
    number = _finite_or_none(value)
    return "-" if number is None else f"{number:.4f}%"


def _number(value: object) -> str:
    number = _finite_or_none(value)
    return "-" if number is None else f"{number:.4f}"


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
