"""Causal daily dating of concept-leader ignition, confirmation and endings."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha1
from typing import Any

import numpy as np
import pandas as pd


CAMPAIGN_COLUMNS = (
    "campaign_id",
    "sector_id",
    "concept_name",
    "anchor_date",
    "end_date",
)
RELATION_COLUMNS = (
    "source_date",
    "sector_id",
    "concept_name",
    "vt_symbol",
    "stock_name",
    "limit_times",
)
BAR_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "turnover",
)
STRONG_CLOSE_PCT = 9.5
LEADER_DATE_MODES = (
    "ignition_gain_top3",
    "two_strong_gain_top3",
    "two_strong_gain_top3_early_phase",
)
MIN_CONFIRMATION_GAIN_PCT = 15.0
MAX_CONFIRMATION_LAG_SESSIONS = 3
MAX_EARLY_PHASE_IGNITION_LIMIT_TIMES = 2
LIFECYCLE_HORIZON_SESSIONS = 20
STUDY_VERSION = "daily-leader-spell-date-v1"
RESEARCH_STATUS = "reused_history_incomplete_event_denominator"
CONCEPT_SOURCE = "eastmoney.board_kline"
CAMPAIGN_ANCHOR_MODE = "breakout_relative_turnover"
CAMPAIGN_EXIT_DRAWDOWN_PCT = 5.0
CAMPAIGN_EXIT_CONFIRM_SESSIONS = 3
RESTART_RESET_DRAWDOWN_PCT = 3.0
MIN_RESTART_GAP_SESSIONS = 3
ZHONGJING_SYMBOL = "002579.SZSE"
ZHONGJING_IGNITION_DATE = pd.Timestamp("2026-05-26")
NORMALIZED_EVENT_COLUMNS = (
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


@dataclass(frozen=True)
class DailyLeaderSpellDateInputs:
    concept_bars: pd.DataFrame
    events: pd.DataFrame
    relations: pd.DataFrame
    stock_bars: pd.DataFrame
    coverage: dict[str, Any]
    fingerprints: dict[str, dict[str, Any]]


def build_daily_event_candidate_ledger(
    campaigns: pd.DataFrame,
    relations: pd.DataFrame,
    stock_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Expand exact-reason candidates only from their close-known event date."""

    campaign_frame = _prepare_campaigns(campaigns)
    relation_frame = _prepare_relations(relations)
    bars = _prepare_stock_bars(stock_bars)
    bars_by_symbol = {
        symbol: frame.reset_index(drop=True)
        for symbol, frame in bars.groupby("vt_symbol", sort=False)
    }

    rows: list[dict[str, object]] = []
    for campaign in campaign_frame.to_dict("records"):
        scoped = relation_frame.loc[
            relation_frame["sector_id"].eq(campaign["sector_id"])
            & relation_frame["source_date"].between(
                campaign["anchor_date"], campaign["end_date"]
            )
        ].copy()
        if scoped.empty:
            continue
        first_events = (
            scoped.sort_values(
                ["source_date", "vt_symbol", "limit_times"],
                kind="stable",
            )
            .drop_duplicates("vt_symbol", keep="first")
            .reset_index(drop=True)
        )
        for event in first_events.to_dict("records"):
            features = bars_by_symbol.get(str(event["vt_symbol"]))
            if features is None:
                continue
            rows.extend(_candidate_path_rows(campaign, event, features))

    if not rows:
        return pd.DataFrame()
    ledger = pd.DataFrame.from_records(rows)
    if ledger.duplicated(["leader_spell_id", "trade_date"]).any():
        raise ValueError("leader spell daily identities must be unique")
    ledger = ledger.sort_values(
        ["campaign_id", "trade_date", "cumulative_gain_pct", "vt_symbol"],
        ascending=[True, True, False, True],
        kind="stable",
    ).reset_index(drop=True)
    grouped = ledger.groupby(["campaign_id", "trade_date"], sort=False)
    ledger["causal_gain_rank"] = grouped.cumcount() + 1
    ledger["causal_cohort_size"] = grouped["vt_symbol"].transform("nunique")
    return ledger.sort_values(
        ["trade_date", "campaign_id", "causal_gain_rank", "vt_symbol"],
        kind="stable",
    ).reset_index(drop=True)


def build_restart_aware_concept_impulses(
    concept_features: pd.DataFrame,
    *,
    anchor_mode: str = CAMPAIGN_ANCHOR_MODE,
    reset_drawdown_pct: float = RESTART_RESET_DRAWDOWN_PCT,
    minimum_restart_gap_sessions: int = MIN_RESTART_GAP_SESSIONS,
    exit_drawdown_pct: float = CAMPAIGN_EXIT_DRAWDOWN_PCT,
    exit_confirm_sessions: int = CAMPAIGN_EXIT_CONFIRM_SESSIONS,
) -> pd.DataFrame:
    """Split broad concept campaigns when a reset is followed by a new anchor edge."""

    anchor_column = f"anchor_{anchor_mode}"
    required = (
        "sector_id",
        "concept_name",
        "trade_date",
        "close_price",
        anchor_column,
    )
    _require_columns(concept_features, required, "concept campaign feature")
    if not 0 < reset_drawdown_pct < 100:
        raise ValueError("restart reset drawdown must be between zero and one hundred")
    if minimum_restart_gap_sessions < 1:
        raise ValueError("minimum restart gap must be positive")
    if not 0 < exit_drawdown_pct < 100 or exit_confirm_sessions < 1:
        raise ValueError("terminal exit parameters must be positive")
    frame = concept_features.loc[:, list(required)].copy()
    frame["sector_id"] = frame["sector_id"].astype(str)
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    frame["close_price"] = pd.to_numeric(frame["close_price"], errors="coerce")
    if frame.duplicated(["sector_id", "trade_date"]).any():
        raise ValueError("concept feature identities must be unique")
    if frame["close_price"].isna().any() or frame["close_price"].le(0).any():
        raise ValueError("concept closes must be positive")
    if frame[anchor_column].isna().any():
        raise ValueError("concept anchors cannot be missing")
    frame[anchor_column] = frame[anchor_column].astype(bool)

    records: list[dict[str, object]] = []
    for _, sector_frame in frame.groupby("sector_id", sort=True):
        sector = sector_frame.sort_values("trade_date", kind="stable").reset_index(
            drop=True
        )
        records.extend(
            _scan_restart_aware_impulses(
                sector,
                anchor_column=anchor_column,
                anchor_mode=anchor_mode,
                reset_drawdown_pct=reset_drawdown_pct,
                minimum_restart_gap_sessions=minimum_restart_gap_sessions,
                exit_drawdown_pct=exit_drawdown_pct,
                exit_confirm_sessions=exit_confirm_sessions,
            )
        )
    if not records:
        return pd.DataFrame()
    result = pd.DataFrame.from_records(records)
    if result["campaign_id"].duplicated().any():
        raise ValueError("restart-aware concept impulse identities must be unique")
    return result.sort_values(
        ["anchor_date", "sector_id", "campaign_id"], kind="stable"
    ).reset_index(drop=True)


def build_leader_confirmations(ledger: pd.DataFrame) -> pd.DataFrame:
    """Date leader confirmations using only fields known at each completed close."""

    required = (
        "leader_spell_id",
        "campaign_id",
        "sector_id",
        "concept_name",
        "anchor_date",
        "campaign_end_date",
        "vt_symbol",
        "stock_name",
        "ignition_date",
        "ignition_limit_times",
        "trade_date",
        "sessions_since_ignition",
        "strong_closes_since_ignition",
        "cumulative_gain_pct",
        "causal_gain_rank",
        "causal_cohort_size",
    )
    _require_columns(ledger, required, "daily event candidate ledger")
    if ledger.empty:
        return pd.DataFrame()
    frame = ledger.copy()
    for column in ("ignition_date", "trade_date"):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.normalize()
    if frame.duplicated(["leader_spell_id", "trade_date"]).any():
        raise ValueError("daily event candidate identities must be unique")

    records: list[dict[str, object]] = []
    for _, spell in frame.groupby("leader_spell_id", sort=True):
        ordered = spell.sort_values("trade_date", kind="stable")
        ignition = ordered.loc[ordered["trade_date"].eq(ordered["ignition_date"])]
        if not ignition.empty:
            eligible = ignition.loc[
                ignition["causal_gain_rank"].le(3)
                & ignition["causal_cohort_size"].ge(3)
            ]
            if not eligible.empty:
                records.append(
                    _confirmation_record(
                        eligible.iloc[0],
                        mode="ignition_gain_top3",
                    )
                )

        persistent = ordered.loc[
            ordered["sessions_since_ignition"].between(
                1, MAX_CONFIRMATION_LAG_SESSIONS
            )
            & ordered["strong_closes_since_ignition"].ge(2)
            & ordered["cumulative_gain_pct"].ge(MIN_CONFIRMATION_GAIN_PCT)
            & ordered["causal_gain_rank"].le(3)
            & ordered["causal_cohort_size"].ge(3)
        ]
        if persistent.empty:
            continue
        confirmation = persistent.iloc[0]
        records.append(
            _confirmation_record(
                confirmation,
                mode="two_strong_gain_top3",
            )
        )
        if (
            int(confirmation["ignition_limit_times"])
            <= MAX_EARLY_PHASE_IGNITION_LIMIT_TIMES
        ):
            records.append(
                _confirmation_record(
                    confirmation,
                    mode="two_strong_gain_top3_early_phase",
                )
            )

    if not records:
        return pd.DataFrame()
    result = pd.DataFrame.from_records(records)
    if result.duplicated(["leader_date_mode", "leader_spell_id"]).any():
        raise ValueError("leader confirmation identities must be unique")
    return result.sort_values(
        ["confirmation_date", "leader_date_mode", "campaign_id", "vt_symbol"],
        kind="stable",
    ).reset_index(drop=True)


def build_leader_lifecycles(
    confirmations: pd.DataFrame,
    stock_bars: pd.DataFrame,
    *,
    horizon_sessions: int = LIFECYCLE_HORIZON_SESSIONS,
) -> pd.DataFrame:
    """Attach descriptive peaks and causal two-close MA5 end confirmations."""

    required = (
        "leader_date_mode",
        "leader_spell_id",
        "campaign_id",
        "sector_id",
        "concept_name",
        "vt_symbol",
        "stock_name",
        "ignition_date",
        "confirmation_date",
        "confirmation_known_at",
    )
    _require_columns(confirmations, required, "leader confirmation")
    if horizon_sessions < 1:
        raise ValueError("lifecycle horizon must be positive")
    if confirmations.empty:
        return pd.DataFrame()
    frame = confirmations.copy()
    for column in ("ignition_date", "confirmation_date", "confirmation_known_at"):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.normalize()
    if frame.duplicated(["leader_date_mode", "leader_spell_id"]).any():
        raise ValueError("leader confirmation identities must be unique")
    features = _prepare_stock_bars(stock_bars)
    by_symbol = {
        symbol: group.reset_index(drop=True)
        for symbol, group in features.groupby("vt_symbol", sort=False)
    }
    rows: list[dict[str, object]] = []
    for confirmation in frame.to_dict("records"):
        symbol_bars = by_symbol.get(str(confirmation["vt_symbol"]))
        if symbol_bars is None:
            continue
        lifecycle = _lifecycle_record(
            confirmation,
            symbol_bars,
            horizon_sessions=horizon_sessions,
        )
        if lifecycle is not None:
            rows.append(lifecycle)
    return pd.DataFrame.from_records(rows).sort_values(
        ["confirmation_date", "leader_date_mode", "leader_spell_id"],
        kind="stable",
    ).reset_index(drop=True)


def build_leader_continuation_truth(
    confirmations: pd.DataFrame,
    stock_bars: pd.DataFrame,
    *,
    horizon_sessions: int = LIFECYCLE_HORIZON_SESSIONS,
    pullback_pct: float = 5.0,
) -> pd.DataFrame:
    """Label post-confirmation continuation without feeding it into dating."""

    required = (
        "leader_date_mode",
        "leader_spell_id",
        "campaign_id",
        "sector_id",
        "concept_name",
        "vt_symbol",
        "stock_name",
        "ignition_date",
        "ignition_limit_times",
        "confirmation_date",
        "confirmation_known_at",
        "confirmation_lag_sessions",
    )
    _require_columns(confirmations, required, "leader confirmation")
    if horizon_sessions < 5:
        raise ValueError("continuation horizon must cover at least five sessions")
    if not 0 < pullback_pct < 100:
        raise ValueError("pullback percentage must be between zero and one hundred")
    if confirmations.empty:
        return pd.DataFrame()
    frame = confirmations.copy()
    for column in ("ignition_date", "confirmation_date", "confirmation_known_at"):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.normalize()
    if frame.duplicated(["leader_date_mode", "leader_spell_id"]).any():
        raise ValueError("leader confirmation identities must be unique")
    features = _prepare_stock_bars(stock_bars)
    by_symbol = {
        symbol: group.reset_index(drop=True)
        for symbol, group in features.groupby("vt_symbol", sort=False)
    }
    rows: list[dict[str, object]] = []
    for confirmation in frame.to_dict("records"):
        symbol_bars = by_symbol.get(str(confirmation["vt_symbol"]))
        if symbol_bars is None:
            continue
        truth = _continuation_truth_record(
            confirmation,
            symbol_bars,
            horizon_sessions=horizon_sessions,
            pullback_pct=pullback_pct,
        )
        if truth is not None:
            rows.append(truth)
    return pd.DataFrame.from_records(rows).sort_values(
        ["confirmation_date", "leader_date_mode", "leader_spell_id"],
        kind="stable",
    ).reset_index(drop=True)


def summarize_leader_date_modes(
    truth: pd.DataFrame,
    *,
    block_count: int = 5,
) -> pd.DataFrame:
    """Summarize every mode on pooled and chronological confirmation blocks."""

    required = (
        "leader_date_mode",
        "leader_spell_id",
        "confirmation_date",
        "confirmation_lag_sessions",
        "ignition_limit_times",
        "truth_status",
        "continued_after_pullback",
        "d5_close_return_pct",
        "future_max_return_pct",
        "future_max_drawdown_pct",
    )
    _require_columns(truth, required, "leader continuation truth")
    if block_count < 1:
        raise ValueError("block count must be positive")
    if truth.empty:
        return pd.DataFrame()
    frame = truth.copy()
    frame["confirmation_date"] = pd.to_datetime(
        frame["confirmation_date"], errors="raise"
    ).dt.normalize()
    block_by_date = _chronological_block_map(
        frame["confirmation_date"],
        block_count=block_count,
    )
    frame["time_block"] = frame["confirmation_date"].map(block_by_date)

    rows: list[dict[str, object]] = []
    for mode, mode_frame in frame.groupby("leader_date_mode", sort=True):
        rows.append(
            {
                "leader_date_mode": str(mode),
                "segment": "all",
                **_mode_metrics(mode_frame),
            }
        )
        for block, block_frame in mode_frame.groupby("time_block", sort=True):
            rows.append(
                {
                    "leader_date_mode": str(mode),
                    "segment": str(block),
                    **_mode_metrics(block_frame),
                }
            )
    return pd.DataFrame.from_records(rows).sort_values(
        ["segment", "leader_date_mode"], kind="stable"
    ).reset_index(drop=True)


def summarize_leader_outcome_groups(
    truth: pd.DataFrame,
    *,
    mode: str = "two_strong_gain_top3_early_phase",
) -> pd.DataFrame:
    """Contrast complete continuation winners and failures for one frozen mode."""

    required = (
        "leader_date_mode",
        "leader_spell_id",
        "truth_status",
        "continued_after_pullback",
        "d5_close_return_pct",
        "future_max_return_pct",
        "future_max_drawdown_pct",
        "confirmation_gain_pct",
        "confirmation_cohort_size",
        "confirmation_causal_gain_rank",
    )
    _require_columns(truth, required, "leader continuation truth")
    frame = truth.loc[
        truth["leader_date_mode"].eq(mode) & truth["truth_status"].eq("complete")
    ].copy()
    rows: list[dict[str, object]] = []
    labels = {
        False: "no_pullback_rebreak",
        True: "pullback_then_higher_high",
    }
    for continued, group in frame.groupby("continued_after_pullback", sort=True):
        rows.append(
            {
                "leader_date_mode": mode,
                "outcome_group": labels[bool(continued)],
                "spells": int(len(group)),
                "d5_positive_share_pct": _boolean_rate(
                    group["d5_close_return_pct"].gt(0)
                ),
                "mean_d5_close_return_pct": _mean(group["d5_close_return_pct"]),
                "median_d5_close_return_pct": _median(group["d5_close_return_pct"]),
                "mean_confirmation_gain_pct": _mean(
                    group["confirmation_gain_pct"]
                ),
                "median_confirmation_cohort_size": _median(
                    group["confirmation_cohort_size"]
                ),
                "rank1_share_pct": _boolean_rate(
                    group["confirmation_causal_gain_rank"].eq(1)
                ),
                "mean_future_max_return_pct": _mean(group["future_max_return_pct"]),
                "mean_future_max_drawdown_pct": _mean(
                    group["future_max_drawdown_pct"]
                ),
            }
        )
    return pd.DataFrame.from_records(rows)


def summarize_exploratory_continuation_slice(
    truth: pd.DataFrame,
    *,
    mode: str = "two_strong_gain_top3_early_phase",
    block_count: int = 5,
) -> pd.DataFrame:
    """Audit a post-hoc continuation slice without promoting it to a rule."""

    required = (
        "leader_date_mode",
        "leader_spell_id",
        "confirmation_date",
        "confirmation_gain_pct",
        "confirmation_causal_gain_rank",
        "truth_status",
        "continued_after_pullback",
        "d5_close_return_pct",
    )
    _require_columns(truth, required, "leader continuation truth")
    frame = truth.copy()
    frame["confirmation_date"] = pd.to_datetime(
        frame["confirmation_date"], errors="raise"
    ).dt.normalize()
    block_by_date = _chronological_block_map(
        frame["confirmation_date"],
        block_count=block_count,
    )
    frame = frame.loc[
        frame["leader_date_mode"].eq(mode) & frame["truth_status"].eq("complete")
    ].copy()
    frame["time_block"] = frame["confirmation_date"].map(block_by_date)
    frame["in_candidate_slice"] = (
        frame["confirmation_gain_pct"].ge(20.0)
        & frame["confirmation_gain_pct"].lt(25.0)
        & frame["confirmation_causal_gain_rank"].isin((2, 3))
    )

    rows: list[dict[str, object]] = []
    for segment, segment_frame in (
        [("all", frame)]
        + [
            (str(block), block_frame)
            for block, block_frame in frame.groupby("time_block", sort=True)
        ]
    ):
        for in_slice, group in segment_frame.groupby("in_candidate_slice", sort=True):
            rows.append(
                {
                    "leader_date_mode": mode,
                    "segment": segment,
                    "slice": (
                        "gain_20_25_rank_2_3" if bool(in_slice) else "complement"
                    ),
                    "spells": int(len(group)),
                    "continuation_after_pullback_rate_pct": _boolean_rate(
                        group["continued_after_pullback"]
                    ),
                    "d5_positive_share_pct": _boolean_rate(
                        group["d5_close_return_pct"].gt(0)
                    ),
                    "mean_d5_close_return_pct": _mean(group["d5_close_return_pct"]),
                    "median_d5_close_return_pct": _median(
                        group["d5_close_return_pct"]
                    ),
                }
            )
    return pd.DataFrame.from_records(rows)


def load_daily_leader_spell_date_inputs() -> DailyLeaderSpellDateInputs:
    """Load only canonical concept bars, close-known events and stock daily bars."""

    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine, session_scope

    from .calculated_leader_relationship import is_main_board_symbol
    from .contracts import CONCEPT_SECTOR_TYPES
    from .dynamic_concept_campaign_study import (
        filter_exploratory_concept_universe,
    )
    from .event_recognition_falsification import build_exact_reason_relations
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
    raw_concepts = pd.read_sql(
        concept_statement,
        engine,
        parse_dates=["trade_date"],
    )
    concept_bars, universe_audit = filter_exploratory_concept_universe(
        raw_concepts
    )
    if concept_bars.empty:
        raise ValueError("canonical concept history is empty")
    concept_ids = set(concept_bars["sector_id"].astype(str))
    concept_names = (
        concept_bars.loc[:, ["sector_id", "concept_name"]]
        .drop_duplicates()
        .sort_values("sector_id", kind="stable")
        .reset_index(drop=True)
    )

    with session_scope() as session:
        event_rows = session.execute(
            select(
                schema.stock_events.c.id,
                schema.stock_events.c.vt_symbol,
                schema.stock_events.c.event_date,
                schema.stock_events.c.raw,
            )
            .where(schema.stock_events.c.event_type == "limit_pool_zt")
            .order_by(schema.stock_events.c.event_date, schema.stock_events.c.id)
        ).mappings().all()
    events = _normalize_limit_events(event_rows)
    relations = build_exact_reason_relations(events, concept_names)
    relations = relations.loc[
        relations["sector_id"].astype(str).isin(concept_ids)
        & relations["vt_symbol"].map(is_main_board_symbol)
    ].copy()
    relations["limit_times"] = pd.to_numeric(
        relations["limit_times"], errors="coerce"
    )
    missing_limit_times = int(relations["limit_times"].isna().sum())
    relations = relations.loc[
        relations["limit_times"].notna() & relations["limit_times"].ge(1)
    ].copy()
    relations["limit_times"] = relations["limit_times"].astype(int)
    if relations.empty:
        raise ValueError("exact event-to-concept relations are empty")

    symbols = tuple(sorted(relations["vt_symbol"].astype(str).unique()))
    concept_start = pd.Timestamp(concept_bars["trade_date"].min()).date()
    concept_end = pd.Timestamp(concept_bars["trade_date"].max()).date()
    bar_start = concept_start - timedelta(days=60)
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
        )
        .where(
            schema.stock_daily_bars.c.vt_symbol.in_(symbols),
            schema.stock_daily_bars.c.trade_date.between(bar_start, concept_end),
        )
        .order_by(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
        )
    )
    stock_bars = pd.read_sql(
        stock_statement,
        engine,
        parse_dates=["trade_date"],
    )
    if stock_bars.empty:
        raise ValueError("event-related stock daily history is empty")

    fingerprint_frames = {
        "canonical_concept_bars": (
            concept_bars,
            ("sector_id", "trade_date"),
        ),
        "close_known_limit_events": (events, ("event_id",)),
        "exact_event_concept_relations": (
            relations,
            ("source_date", "sector_id", "vt_symbol"),
        ),
        "event_related_stock_bars": (
            stock_bars,
            ("trade_date", "vt_symbol"),
        ),
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
        "limit_event_rows": int(len(events)),
        "event_start": _date_bound(events, "source_date", "min"),
        "event_end": _date_bound(events, "source_date", "max"),
        "exact_relation_rows": int(len(relations)),
        "relation_concepts": int(relations["sector_id"].nunique()),
        "relation_symbols": int(relations["vt_symbol"].nunique()),
        "missing_limit_times_excluded": missing_limit_times,
        "stock_bar_rows": int(len(stock_bars)),
        "stock_symbols": int(stock_bars["vt_symbol"].nunique()),
        "stock_bar_start": _date_bound(stock_bars, "trade_date", "min"),
        "stock_bar_end": _date_bound(stock_bars, "trade_date", "max"),
        "membership_rows_read": 0,
        "minute_rows_read": 0,
        "fund_cycle_rows_read": 0,
        "timing_rows_read": 0,
        "prior_outcome_rows_read": 0,
        **universe_audit,
    }
    return DailyLeaderSpellDateInputs(
        concept_bars=concept_bars,
        events=events,
        relations=relations,
        stock_bars=stock_bars,
        coverage=coverage,
        fingerprints=fingerprints,
    )


def run_daily_leader_spell_date_study() -> dict[str, Any]:
    """Run the daily leader-date study and require the Zhongjing audit case."""

    from .dynamic_concept_campaign import (
        build_concept_campaign_features,
        build_exploratory_campaigns,
    )
    from .research_protocol import fingerprint_frame

    inputs = load_daily_leader_spell_date_inputs()
    concept_features = build_concept_campaign_features(inputs.concept_bars)
    campaigns = build_restart_aware_concept_impulses(concept_features)
    if campaigns.empty:
        raise ValueError("restart-aware concept impulse ledger is empty")
    pcb_features = concept_features.loc[
        concept_features["concept_name"].eq("PCB")
    ].copy()
    legacy_pcb_campaigns, _ = build_exploratory_campaigns(
        pcb_features,
        anchor_modes=(CAMPAIGN_ANCHOR_MODE,),
        exit_candidates=((CAMPAIGN_EXIT_DRAWDOWN_PCT, CAMPAIGN_EXIT_CONFIRM_SESSIONS),),
        retained_path_days=frozenset(),
    )
    if legacy_pcb_campaigns.empty:
        raise ValueError("legacy PCB campaign audit ledger is empty")
    campaign_contract = campaigns.loc[
        :,
        [
            "campaign_id",
            "sector_id",
            "concept_name",
            "anchor_date",
            "end_date",
        ],
    ].copy()
    candidate_ledger = build_daily_event_candidate_ledger(
        campaign_contract,
        inputs.relations,
        inputs.stock_bars,
    )
    if candidate_ledger.empty:
        raise ValueError("daily event candidate ledger is empty")
    confirmations = build_leader_confirmations(candidate_ledger)
    if confirmations.empty:
        raise ValueError("leader confirmation ledger is empty")
    lifecycles = build_leader_lifecycles(confirmations, inputs.stock_bars)
    truth = build_leader_continuation_truth(confirmations, inputs.stock_bars)
    if lifecycles.empty or truth.empty:
        raise ValueError("leader lifecycle or truth ledger is empty")
    metrics = summarize_leader_date_modes(truth, block_count=5)
    outcome_groups = summarize_leader_outcome_groups(truth)
    exploratory_slice = summarize_exploratory_continuation_slice(
        truth,
        block_count=5,
    )
    lifecycle_columns = [
        "leader_date_mode",
        "leader_spell_id",
        "realized_peak_date",
        "realized_peak_close",
        "first_end_warning_date",
        "end_warning_date",
        "end_confirmation_date",
        "end_confirmation_known_at",
        "lifecycle_status",
        "observation_end",
        "observation_sessions",
    ]
    spell_ledger = truth.merge(
        lifecycles.loc[:, lifecycle_columns],
        on=["leader_date_mode", "leader_spell_id"],
        how="left",
        validate="one_to_one",
    )
    zhongjing = spell_ledger.loc[
        spell_ledger["vt_symbol"].eq(ZHONGJING_SYMBOL)
        & spell_ledger["ignition_date"].eq(ZHONGJING_IGNITION_DATE)
    ].copy()
    if zhongjing.empty:
        raise ValueError("Zhongjing 2026 leader spell was not detected")
    preferred_case = zhongjing.loc[
        zhongjing["leader_date_mode"].eq(
            "two_strong_gain_top3_early_phase"
        )
    ]
    if len(preferred_case) != 1:
        raise ValueError("Zhongjing early-phase confirmation is not unique")
    case_row = preferred_case.iloc[0]
    zhongjing_path = _build_zhongjing_daily_path(
        case_row,
        candidate_ledger,
        inputs.relations,
        inputs.stock_bars,
    )
    concept_restart_audit = _build_concept_restart_audit(
        case_row,
        campaigns,
        legacy_pcb_campaigns,
    )
    _require_zhongjing_historical_case(
        case_row,
        zhongjing_path,
        concept_restart_audit,
    )
    coverage = {
        **inputs.coverage,
        "fixed_concept_campaigns": int(len(campaign_contract)),
        "restart_aware_concept_impulses": int(len(campaign_contract)),
        "legacy_pcb_campaigns_audited": int(len(legacy_pcb_campaigns)),
        "campaigns_with_event_candidates": int(
            candidate_ledger["campaign_id"].nunique()
        ),
        "daily_candidate_rows": int(len(candidate_ledger)),
        "candidate_spells": int(candidate_ledger["leader_spell_id"].nunique()),
        "confirmation_rows": int(len(confirmations)),
        "confirmed_spells": int(confirmations["leader_spell_id"].nunique()),
        "complete_truth_rows": int(truth["truth_status"].eq("complete").sum()),
    }
    fingerprints = {
        **inputs.fingerprints,
        "restart_aware_concept_impulses": fingerprint_frame(
            campaigns,
            identity_columns=("campaign_id",),
        ).as_dict(),
        "legacy_pcb_campaign_audit": fingerprint_frame(
            legacy_pcb_campaigns,
            identity_columns=("campaign_id",),
        ).as_dict(),
        "leader_confirmations": fingerprint_frame(
            confirmations,
            identity_columns=("leader_date_mode", "leader_spell_id"),
        ).as_dict(),
        "leader_spell_truth": fingerprint_frame(
            truth,
            identity_columns=("leader_date_mode", "leader_spell_id"),
        ).as_dict(),
    }
    return build_daily_leader_spell_date_report(
        coverage=coverage,
        fingerprints=fingerprints,
        metrics=metrics,
        outcome_groups=outcome_groups,
        exploratory_slice=exploratory_slice,
        spell_ledger=spell_ledger,
        zhongjing=zhongjing,
        zhongjing_path=zhongjing_path,
        concept_restart_audit=concept_restart_audit,
    )


def build_daily_leader_spell_date_report(
    *,
    coverage: Mapping[str, Any],
    fingerprints: Mapping[str, Any],
    metrics: pd.DataFrame,
    outcome_groups: pd.DataFrame,
    exploratory_slice: pd.DataFrame,
    spell_ledger: pd.DataFrame,
    zhongjing: pd.DataFrame,
    zhongjing_path: pd.DataFrame,
    concept_restart_audit: pd.DataFrame,
) -> dict[str, Any]:
    """Build deterministic research evidence with formal outputs disabled."""

    return {
        "study_version": STUDY_VERSION,
        "research_status": RESEARCH_STATUS,
        "formal_top3": False,
        "formal_metrics": None,
        "formal_strategy": False,
        "contract": {
            "campaign_anchor_mode": CAMPAIGN_ANCHOR_MODE,
            "restart_reset_drawdown_pct": RESTART_RESET_DRAWDOWN_PCT,
            "minimum_restart_gap_sessions": MIN_RESTART_GAP_SESSIONS,
            "campaign_exit_drawdown_pct": CAMPAIGN_EXIT_DRAWDOWN_PCT,
            "campaign_exit_confirm_sessions": CAMPAIGN_EXIT_CONFIRM_SESSIONS,
            "candidate_relation": "close_known_exact_plus_delimited_limit_reason",
            "candidate_membership": "expands_from_first_observed_event_only",
            "confirmation_modes": list(LEADER_DATE_MODES),
            "strong_close_pct": STRONG_CLOSE_PCT,
            "minimum_confirmation_gain_pct": MIN_CONFIRMATION_GAIN_PCT,
            "maximum_confirmation_lag_sessions": MAX_CONFIRMATION_LAG_SESSIONS,
            "truth_horizon_sessions": LIFECYCLE_HORIZON_SESSIONS,
            "truth_pullback_pct": CAMPAIGN_EXIT_DRAWDOWN_PCT,
            "exploratory_continuation_slice": (
                "confirmation_gain_20_to_25_pct_and_causal_rank_2_or_3"
            ),
            "exploratory_slice_is_frozen": False,
            "entry_or_trade_rule": None,
        },
        "coverage": dict(coverage),
        "mode_metrics": _records(metrics),
        "outcome_group_profiles": _records(outcome_groups),
        "exploratory_continuation_slice": _records(exploratory_slice),
        "leader_spell_ledger": _records(spell_ledger),
        "zhongjing_case": _records(zhongjing),
        "zhongjing_daily_path": _records(zhongjing_path),
        "concept_restart_audit": _records(concept_restart_audit),
        "input_fingerprints": dict(fingerprints),
        "findings_boundary": [
            "Zhongjing 2026 was user-inspected before this study",
            "exact limit-up reason relations are an incomplete non-random denominator",
            "historical point-in-time memberships were not read",
            "realized peak and continuation truth never enter confirmation ranking",
            "no API, UI, paper portfolio or live strategy was changed",
        ],
        "reproduce": (
            "python -m alphaagent.server.services.low_suction.cli "
            "v2-daily-leader-spell-date-study --format markdown"
        ),
    }


def render_daily_leader_spell_date_json(report: Mapping[str, Any]) -> str:
    """Render stable machine-readable leader-date evidence."""

    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def render_daily_leader_spell_date_markdown(report: Mapping[str, Any]) -> str:
    """Render concise mode metrics and the auditable Zhongjing daily path."""

    coverage = report.get("coverage") or {}
    lines = [
        "# AlphaAgent Daily Leader Spell Date Study",
        "",
        f"Research status: `{report.get('research_status')}`.",
        "Formal Top3/metrics/strategy: `false/null/false`.",
        "",
        "## Coverage",
        "",
        (
            f"- Fixed concept campaigns/event candidate campaigns: "
            f"`{coverage.get('fixed_concept_campaigns', 0)}/"
            f"{coverage.get('campaigns_with_event_candidates', 0)}`."
        ),
        (
            f"- Candidate spells/confirmation rows/complete truth: "
            f"`{coverage.get('candidate_spells', 0)}/"
            f"{coverage.get('confirmation_rows', 0)}/"
            f"{coverage.get('complete_truth_rows', 0)}`."
        ),
        (
            f"- Membership/minute/fund-cycle/prior-outcome rows read: "
            f"`{coverage.get('membership_rows_read', 0)}/"
            f"{coverage.get('minute_rows_read', 0)}/"
            f"{coverage.get('fund_cycle_rows_read', 0)}/"
            f"{coverage.get('prior_outcome_rows_read', 0)}`."
        ),
        "",
    ]
    restart_audit = list(report.get("concept_restart_audit") or [])
    if restart_audit:
        audit = restart_audit[0]
        lines.extend(
            [
                "## Concept Restart Audit",
                "",
                (
                    "- Legacy PCB campaign: "
                    f"`{_date_text(audit.get('legacy_anchor_date'))}` to "
                    f"`{_date_text(audit.get('legacy_end_date'))}`."
                ),
                (
                    "- Restart-aware PCB impulse: "
                    f"`{_date_text(audit.get('restart_aware_anchor_date'))}` to "
                    f"`{_date_text(audit.get('restart_aware_end_date'))}`."
                ),
                "- Split rule: a 3% reset followed by a new anchor rising edge.",
                "",
            ]
        )
    lines.extend(
        [
            "## Mode Comparison",
            "",
            "| Mode | Segment | Spells | Complete | Pullback then higher high | D+5 positive | Mean D+5 | Median D+5 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.get("mode_metrics") or []:
        lines.append(
            f"| {row.get('leader_date_mode')} | {row.get('segment')} | "
            f"{row.get('spells', 0)} | {row.get('complete_truth_rows', 0)} | "
            f"{_percent(row.get('continuation_after_pullback_rate_pct'))} | "
            f"{_percent(row.get('d5_positive_share_pct'))} | "
            f"{_percent(row.get('mean_d5_close_return_pct'))} | "
            f"{_percent(row.get('median_d5_close_return_pct'))} |"
        )
    lines.extend(
        [
            "",
            "## Continuation Winners And Failures",
            "",
            "| Outcome group | Spells | D+5 positive | Mean D+5 | Confirmation gain | Rank1 share | Future max | Future drawdown |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.get("outcome_group_profiles") or []:
        lines.append(
            f"| {row.get('outcome_group')} | {row.get('spells', 0)} | "
            f"{_percent(row.get('d5_positive_share_pct'))} | "
            f"{_percent(row.get('mean_d5_close_return_pct'))} | "
            f"{_percent(row.get('mean_confirmation_gain_pct'))} | "
            f"{_percent(row.get('rank1_share_pct'))} | "
            f"{_percent(row.get('mean_future_max_return_pct'))} | "
            f"{_percent(row.get('mean_future_max_drawdown_pct'))} |"
        )
    lines.extend(
        [
            "",
            "## Post-hoc Continuation Slice",
            "",
            "This same-history slice is not frozen and is not an entry rule.",
            "",
            "| Segment | Slice | Spells | Pullback then higher high | D+5 positive | Mean D+5 | Median D+5 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.get("exploratory_continuation_slice") or []:
        lines.append(
            f"| {row.get('segment')} | {row.get('slice')} | "
            f"{row.get('spells', 0)} | "
            f"{_percent(row.get('continuation_after_pullback_rate_pct'))} | "
            f"{_percent(row.get('d5_positive_share_pct'))} | "
            f"{_percent(row.get('mean_d5_close_return_pct'))} | "
            f"{_percent(row.get('median_d5_close_return_pct'))} |"
        )
    lines.extend(
        [
            "",
            "## Zhongjing Electronics 2026",
            "",
            "| Mode | Concept anchor | Ignition | Confirmation | Rank | Peak | Warning | End confirmed | Continued after pullback |",
            "| --- | --- | --- | --- | ---: | --- | --- | --- | --- |",
        ]
    )
    for row in report.get("zhongjing_case") or []:
        lines.append(
            f"| {row.get('leader_date_mode')} | {_date_text(row.get('anchor_date'))} | "
            f"{_date_text(row.get('ignition_date'))} | "
            f"{_date_text(row.get('confirmation_date'))} | "
            f"{row.get('confirmation_causal_gain_rank', '')} | "
            f"{_date_text(row.get('realized_peak_date'))} | "
            f"{_date_text(row.get('first_end_warning_date'))} | "
            f"{_date_text(row.get('end_confirmation_date'))} | "
            f"{row.get('continued_after_pullback')} |"
        )
    lines.extend(
        [
            "",
            "### Daily Path",
            "",
            "| Date | Close | Return | MA5 | MA10 | Event boards | Causal rank | Role |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in report.get("zhongjing_daily_path") or []:
        lines.append(
            f"| {_date_text(row.get('trade_date'))} | "
            f"{_number(row.get('close_price'))} | "
            f"{_percent(row.get('daily_return_pct'))} | "
            f"{_number(row.get('ma5'))} | {_number(row.get('ma10'))} | "
            f"{_integer(row.get('event_limit_times'))} | "
            f"{_integer(row.get('causal_gain_rank'))} | "
            f"{row.get('role') or ''} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Peak date is descriptive; it was not known on that date.",
            "- End confirmation requires two consecutive completed closes below MA5.",
            "- The 20%-25% gain and rank 2/3 slice was discovered on this same history and requires forward validation.",
            "- Exact event reasons do not contain every concept member, so formal Top3 remains disabled.",
            "- No minute data, fund cycle, current membership, or prior low-suction outcome was read.",
            "",
            "## Reproduce",
            "",
            "```bash",
            str(report.get("reproduce") or ""),
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def _confirmation_record(
    row: pd.Series,
    *,
    mode: str,
) -> dict[str, object]:
    if mode not in LEADER_DATE_MODES:
        raise ValueError(f"unknown leader date mode: {mode}")
    confirmation_date = pd.Timestamp(row["trade_date"])
    return {
        "leader_date_mode": mode,
        "leader_spell_id": str(row["leader_spell_id"]),
        "campaign_id": str(row["campaign_id"]),
        "sector_id": str(row["sector_id"]),
        "concept_name": str(row["concept_name"]),
        "anchor_date": pd.Timestamp(row["anchor_date"]),
        "campaign_end_date": pd.Timestamp(row["campaign_end_date"]),
        "vt_symbol": str(row["vt_symbol"]),
        "stock_name": str(row["stock_name"]),
        "ignition_date": pd.Timestamp(row["ignition_date"]),
        "ignition_limit_times": int(row["ignition_limit_times"]),
        "confirmation_date": confirmation_date,
        "confirmation_known_at": confirmation_date,
        "confirmation_lag_sessions": int(row["sessions_since_ignition"]),
        "confirmation_strong_closes": int(row["strong_closes_since_ignition"]),
        "confirmation_gain_pct": float(row["cumulative_gain_pct"]),
        "confirmation_causal_gain_rank": int(row["causal_gain_rank"]),
        "confirmation_cohort_size": int(row["causal_cohort_size"]),
        "feature_cutoff_date": confirmation_date,
    }


def _continuation_truth_record(
    confirmation: dict[str, object],
    features: pd.DataFrame,
    *,
    horizon_sessions: int,
    pullback_pct: float,
) -> dict[str, object] | None:
    confirmation_date = pd.Timestamp(confirmation["confirmation_date"])
    path = features.loc[features["trade_date"].ge(confirmation_date)].head(
        horizon_sessions + 1
    )
    if path.empty or path.iloc[0]["trade_date"] != confirmation_date:
        return None
    complete = len(path) >= horizon_sessions + 1
    entry_close = float(path.iloc[0]["close_price"])
    entry_high = float(path.iloc[0]["high_price"])
    d5_return = (
        (float(path.iloc[5]["close_price"]) / entry_close - 1.0) * 100.0
        if len(path) > 5
        else np.nan
    )
    future = path.iloc[1:]
    future_max_return = (
        (float(future["high_price"].max()) / entry_close - 1.0) * 100.0
        if not future.empty
        else np.nan
    )
    running_high = path["close_price"].cummax()
    drawdowns = (path["close_price"] / running_high - 1.0) * 100.0
    later_higher = future.loc[future["high_price"].gt(entry_high)]
    pullback_date, recovery_date = _pullback_recovery_dates(
        path,
        pullback_pct=pullback_pct,
    )
    return {
        **confirmation,
        "truth_status": "complete" if complete else "censored_incomplete_horizon",
        "truth_horizon_sessions": horizon_sessions,
        "truth_observation_end": pd.Timestamp(path.iloc[-1]["trade_date"]),
        "d5_close_return_pct": float(d5_return),
        "future_max_return_pct": float(future_max_return),
        "future_max_drawdown_pct": float(drawdowns.min()),
        "later_higher_high": bool(not later_higher.empty),
        "first_later_higher_high_date": (
            pd.Timestamp(later_higher.iloc[0]["trade_date"])
            if not later_higher.empty
            else pd.NaT
        ),
        "pullback_date": pullback_date,
        "recovery_higher_high_date": recovery_date,
        "continued_after_pullback": bool(pd.notna(recovery_date)),
    }


def _pullback_recovery_dates(
    path: pd.DataFrame,
    *,
    pullback_pct: float,
) -> tuple[pd.Timestamp | pd.NaT, pd.Timestamp | pd.NaT]:
    records = path.reset_index(drop=True)
    if len(records) < 3:
        return pd.NaT, pd.NaT
    running_peak = float(records.iloc[0]["high_price"])
    for position in range(1, len(records)):
        row = records.iloc[position]
        if float(row["low_price"]) <= running_peak * (1.0 - pullback_pct / 100.0):
            later = records.iloc[position + 1 :]
            recovered = later.loc[later["high_price"].gt(running_peak)]
            return (
                pd.Timestamp(row["trade_date"]),
                (
                    pd.Timestamp(recovered.iloc[0]["trade_date"])
                    if not recovered.empty
                    else pd.NaT
                ),
            )
        running_peak = max(running_peak, float(row["high_price"]))
    return pd.NaT, pd.NaT


def _mode_metrics(frame: pd.DataFrame) -> dict[str, object]:
    complete = frame.loc[frame["truth_status"].eq("complete")].copy()
    d5 = pd.to_numeric(complete["d5_close_return_pct"], errors="coerce").dropna()
    continuation = complete["continued_after_pullback"].astype(bool)
    future_max = pd.to_numeric(
        complete["future_max_return_pct"], errors="coerce"
    ).dropna()
    future_drawdown = pd.to_numeric(
        complete["future_max_drawdown_pct"], errors="coerce"
    ).dropna()
    return {
        "spells": int(frame["leader_spell_id"].nunique()),
        "complete_truth_rows": int(len(complete)),
        "censored_truth_rows": int(len(frame) - len(complete)),
        "continuation_after_pullback_rate_pct": _boolean_rate(continuation),
        "d5_positive_share_pct": _boolean_rate(d5.gt(0)),
        "mean_d5_close_return_pct": _mean(d5),
        "median_d5_close_return_pct": _median(d5),
        "mean_future_max_return_pct": _mean(future_max),
        "mean_future_max_drawdown_pct": _mean(future_drawdown),
        "median_confirmation_lag_sessions": _median(
            pd.to_numeric(frame["confirmation_lag_sessions"], errors="coerce")
        ),
        "early_ignition_share_pct": _boolean_rate(
            pd.to_numeric(frame["ignition_limit_times"], errors="coerce").le(
                MAX_EARLY_PHASE_IGNITION_LIMIT_TIMES
            )
        ),
    }


def _chronological_block_map(
    confirmation_dates: pd.Series,
    *,
    block_count: int,
) -> dict[pd.Timestamp, str]:
    if block_count < 1:
        raise ValueError("block count must be positive")
    dates = tuple(sorted(pd.to_datetime(confirmation_dates).unique()))
    if len(dates) < block_count:
        raise ValueError("confirmation dates must cover every requested block")
    result: dict[pd.Timestamp, str] = {}
    for index, values in enumerate(
        np.array_split(np.array(dates, dtype="datetime64[ns]"), block_count),
        start=1,
    ):
        for value in values:
            result[pd.Timestamp(value)] = f"block_{index}"
    return result


def _boolean_rate(values: pd.Series) -> float | None:
    if values.empty:
        return None
    return float(values.astype(bool).mean() * 100.0)


def _mean(values: pd.Series) -> float | None:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    return float(clean.mean()) if not clean.empty else None


def _median(values: pd.Series) -> float | None:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    return float(clean.median()) if not clean.empty else None


def _normalize_limit_events(rows: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for row in rows:
        raw = dict(row.get("raw") or {})
        reason = str(raw.get("涨停原因") or raw.get("reason_type") or "").strip()
        if not reason:
            continue
        source_date = pd.to_datetime(
            str(row.get("event_date"))[:8],
            format="%Y%m%d",
            errors="raise",
        ).date()
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
    return pd.DataFrame.from_records(records, columns=list(NORMALIZED_EVENT_COLUMNS))


def _build_concept_restart_audit(
    case: pd.Series,
    restart_campaigns: pd.DataFrame,
    legacy_campaigns: pd.DataFrame,
) -> pd.DataFrame:
    campaign_id = str(case["campaign_id"])
    ignition_date = pd.Timestamp(case["ignition_date"])
    restarted = restart_campaigns.loc[
        restart_campaigns["campaign_id"].astype(str).eq(campaign_id)
    ]
    legacy = legacy_campaigns.loc[
        legacy_campaigns["sector_id"].astype(str).eq(str(case["sector_id"]))
        & pd.to_datetime(legacy_campaigns["anchor_date"]).le(ignition_date)
        & pd.to_datetime(legacy_campaigns["end_date"]).ge(ignition_date)
    ]
    if len(restarted) != 1 or len(legacy) != 1:
        raise ValueError("Zhongjing concept restart audit is not unique")
    restarted_row = restarted.iloc[0]
    legacy_row = legacy.iloc[0]
    return pd.DataFrame.from_records(
        [
            {
                "sector_id": str(case["sector_id"]),
                "concept_name": str(case["concept_name"]),
                "target_ignition_date": ignition_date,
                "legacy_anchor_date": pd.Timestamp(legacy_row["anchor_date"]),
                "legacy_end_date": pd.Timestamp(legacy_row["end_date"]),
                "restart_aware_anchor_date": pd.Timestamp(
                    restarted_row["anchor_date"]
                ),
                "restart_aware_end_date": pd.Timestamp(restarted_row["end_date"]),
                "restart_aware_end_known_at": pd.Timestamp(
                    restarted_row["end_known_at"]
                ),
                "legacy_merged_target_into_old_campaign": True,
                "restart_reason": "three_pct_reset_then_new_anchor_edge",
            }
        ]
    )


def _require_zhongjing_historical_case(
    case: pd.Series,
    daily_path: pd.DataFrame,
    concept_restart_audit: pd.DataFrame,
) -> None:
    expected_dates = {
        "anchor_date": "2026-05-25",
        "ignition_date": "2026-05-26",
        "confirmation_date": "2026-05-27",
        "realized_peak_date": "2026-06-02",
        "first_end_warning_date": "2026-06-05",
        "end_confirmation_date": "2026-06-08",
    }
    for field, expected in expected_dates.items():
        if pd.Timestamp(case[field]) != pd.Timestamp(expected):
            raise ValueError(f"Zhongjing {field} historical assertion failed")
    if not np.isclose(float(case["realized_peak_close"]), 20.76):
        raise ValueError("Zhongjing realized peak close historical assertion failed")

    dated_path = daily_path.set_index("trade_date")
    ignition = dated_path.loc[pd.Timestamp("2026-05-26")]
    confirmation = dated_path.loc[pd.Timestamp("2026-05-27")]
    if int(ignition["event_limit_times"]) != 1 or int(
        ignition["causal_gain_rank"]
    ) != 2:
        raise ValueError("Zhongjing ignition board/rank historical assertion failed")
    if int(confirmation["event_limit_times"]) != 2 or int(
        confirmation["causal_gain_rank"]
    ) != 1:
        raise ValueError("Zhongjing confirmation board/rank historical assertion failed")

    audit = concept_restart_audit.iloc[0]
    if pd.Timestamp(audit["legacy_anchor_date"]) != pd.Timestamp("2026-04-13"):
        raise ValueError("legacy PCB anchor historical assertion failed")
    if pd.Timestamp(audit["restart_aware_anchor_date"]) != pd.Timestamp(
        "2026-05-25"
    ):
        raise ValueError("restart-aware PCB anchor historical assertion failed")


def _build_zhongjing_daily_path(
    case: pd.Series,
    candidate_ledger: pd.DataFrame,
    relations: pd.DataFrame,
    stock_bars: pd.DataFrame,
) -> pd.DataFrame:
    features = _prepare_stock_bars(stock_bars)
    spell_id = str(case["leader_spell_id"])
    spell_path = candidate_ledger.loc[
        candidate_ledger["leader_spell_id"].eq(spell_id),
        [
            "trade_date",
            "causal_gain_rank",
            "causal_cohort_size",
            "cumulative_gain_pct",
        ],
    ].copy()
    if spell_path.empty:
        raise ValueError("Zhongjing candidate path is empty")
    event_path = relations.loc[
        relations["vt_symbol"].eq(ZHONGJING_SYMBOL)
        & relations["sector_id"].eq(str(case["sector_id"])),
        ["source_date", "limit_times"],
    ].copy()
    event_path["source_date"] = pd.to_datetime(
        event_path["source_date"], errors="raise"
    ).dt.normalize()
    event_path = (
        event_path.sort_values("limit_times", ascending=False, kind="stable")
        .drop_duplicates("source_date")
        .rename(
            columns={
                "source_date": "trade_date",
                "limit_times": "event_limit_times",
            }
        )
    )
    start = pd.Timestamp(case["anchor_date"])
    prior = features.loc[
        features["vt_symbol"].eq(ZHONGJING_SYMBOL)
        & features["trade_date"].lt(start),
        "trade_date",
    ]
    if not prior.empty:
        start = pd.Timestamp(prior.max())
    end_value = case.get("end_confirmation_date")
    end = (
        pd.Timestamp(end_value)
        if pd.notna(end_value)
        else pd.Timestamp(case["truth_observation_end"])
    )
    path = features.loc[
        features["vt_symbol"].eq(ZHONGJING_SYMBOL)
        & features["trade_date"].between(start, end)
    ].copy()
    path = path.merge(
        spell_path,
        on="trade_date",
        how="left",
        validate="one_to_one",
    ).merge(
        event_path,
        on="trade_date",
        how="left",
        validate="one_to_one",
    )
    roles: dict[pd.Timestamp, list[str]] = {}
    role_fields = (
        ("anchor_date", "concept_campaign_anchor"),
        ("ignition_date", "leader_ignition"),
        ("confirmation_date", "leader_confirmation"),
        ("pullback_date", "five_pct_pullback"),
        ("recovery_higher_high_date", "higher_high_recovery"),
        ("realized_peak_date", "realized_peak_not_known_same_day"),
        ("first_end_warning_date", "first_close_below_ma5_warning"),
        ("end_confirmation_date", "second_close_below_ma5_end_confirmation"),
    )
    for field, label in role_fields:
        value = case.get(field)
        if pd.notna(value):
            roles.setdefault(pd.Timestamp(value), []).append(label)
    path["role"] = path["trade_date"].map(
        lambda value: ";".join(roles.get(pd.Timestamp(value), []))
    )
    return path.loc[
        :,
        [
            "trade_date",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "daily_return_pct",
            "ma5",
            "ma10",
            "ma20",
            "event_limit_times",
            "causal_gain_rank",
            "causal_cohort_size",
            "cumulative_gain_pct",
            "role",
        ],
    ].reset_index(drop=True)


def _date_bound(frame: pd.DataFrame, column: str, mode: str) -> str | None:
    if frame.empty:
        return None
    values = pd.to_datetime(frame[column], errors="raise")
    value = values.min() if mode == "min" else values.max()
    return pd.Timestamp(value).date().isoformat()


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return [
        _json_safe(record)
        for record in frame.to_dict("records")
    ]


def _json_safe(value: Any) -> Any:
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, date)):
        return pd.Timestamp(value).date().isoformat()
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    return value


def _percent(value: Any) -> str:
    safe = _json_safe(value)
    return "-" if safe is None else f"{float(safe):.4f}%"


def _number(value: Any) -> str:
    safe = _json_safe(value)
    return "-" if safe is None else f"{float(safe):.4f}"


def _integer(value: Any) -> str:
    safe = _json_safe(value)
    return "-" if safe is None else str(int(safe))


def _date_text(value: Any) -> str:
    safe = _json_safe(value)
    return "-" if safe is None else str(safe)


def _lifecycle_record(
    confirmation: dict[str, object],
    features: pd.DataFrame,
    *,
    horizon_sessions: int,
) -> dict[str, object] | None:
    confirmation_date = pd.Timestamp(confirmation["confirmation_date"])
    available = features.loc[features["trade_date"].ge(confirmation_date)].head(
        horizon_sessions + 1
    )
    if available.empty or available.iloc[0]["trade_date"] != confirmation_date:
        return None

    first_warning: pd.Timestamp | pd.NaT = pd.NaT
    active_warning: pd.Timestamp | pd.NaT = pd.NaT
    end_warning: pd.Timestamp | pd.NaT = pd.NaT
    end_confirmation: pd.Timestamp | pd.NaT = pd.NaT
    consecutive_below = 0
    for row in available.iloc[1:].itertuples(index=False):
        below_ma5 = pd.notna(row.ma5) and float(row.close_price) < float(row.ma5)
        if below_ma5:
            if consecutive_below == 0:
                active_warning = pd.Timestamp(row.trade_date)
                if pd.isna(first_warning):
                    first_warning = active_warning
            consecutive_below += 1
            if consecutive_below >= 2:
                end_warning = active_warning
                end_confirmation = pd.Timestamp(row.trade_date)
                break
        else:
            consecutive_below = 0
            active_warning = pd.NaT

    observed = available
    if pd.notna(end_confirmation):
        observed = available.loc[
            available["trade_date"].le(end_confirmation)
        ]
    peak_index = observed["close_price"].idxmax()
    peak = observed.loc[peak_index]
    complete_horizon = len(available) >= horizon_sessions + 1
    if pd.notna(end_confirmation):
        status = "end_confirmed"
    elif complete_horizon:
        status = "horizon_complete_no_end"
    else:
        status = "censored_incomplete_horizon"
    return {
        **confirmation,
        "realized_peak_date": pd.Timestamp(peak["trade_date"]),
        "realized_peak_close": float(peak["close_price"]),
        "first_end_warning_date": first_warning,
        "end_warning_date": end_warning,
        "end_confirmation_date": end_confirmation,
        "end_confirmation_known_at": end_confirmation,
        "lifecycle_status": status,
        "observation_end": pd.Timestamp(available.iloc[-1]["trade_date"]),
        "observation_sessions": int(len(available)),
    }


def _scan_restart_aware_impulses(
    sector: pd.DataFrame,
    *,
    anchor_column: str,
    anchor_mode: str,
    reset_drawdown_pct: float,
    minimum_restart_gap_sessions: int,
    exit_drawdown_pct: float,
    exit_confirm_sessions: int,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    active: dict[str, object] | None = None
    previous_anchor = False

    for position, row in sector.iterrows():
        anchor = bool(row[anchor_column])
        anchor_edge = anchor and not previous_anchor
        if active is None:
            if anchor_edge:
                active = _start_restart_aware_impulse(
                    row,
                    position=position,
                    anchor_mode=anchor_mode,
                    reset_drawdown_pct=reset_drawdown_pct,
                    minimum_restart_gap_sessions=minimum_restart_gap_sessions,
                    exit_drawdown_pct=exit_drawdown_pct,
                    exit_confirm_sessions=exit_confirm_sessions,
                )
                _advance_restart_aware_impulse(active, row, position=position)
            previous_anchor = anchor
            continue

        sessions_since_anchor = position - int(active["anchor_position"])
        should_restart = (
            anchor_edge
            and bool(active["reset_observed"])
            and sessions_since_anchor >= minimum_restart_gap_sessions
        )
        if should_restart:
            records.append(
                _restart_aware_impulse_record(
                    active,
                    sector,
                    end_position=position - 1,
                    end_reason="next_impulse_restart",
                    end_known_at=pd.Timestamp(row["trade_date"]),
                )
            )
            active = _start_restart_aware_impulse(
                row,
                position=position,
                anchor_mode=anchor_mode,
                reset_drawdown_pct=reset_drawdown_pct,
                minimum_restart_gap_sessions=minimum_restart_gap_sessions,
                exit_drawdown_pct=exit_drawdown_pct,
                exit_confirm_sessions=exit_confirm_sessions,
            )
            _advance_restart_aware_impulse(active, row, position=position)
            previous_anchor = anchor
            continue

        _advance_restart_aware_impulse(active, row, position=position)
        if int(active["below_exit_count"]) >= exit_confirm_sessions:
            records.append(
                _restart_aware_impulse_record(
                    active,
                    sector,
                    end_position=position,
                    end_reason="confirmed_running_peak_drawdown",
                    end_known_at=pd.Timestamp(row["trade_date"]),
                )
            )
            active = None
        previous_anchor = anchor

    if active is not None:
        records.append(
            _restart_aware_impulse_record(
                active,
                sector,
                end_position=len(sector) - 1,
                end_reason="right_censored",
                end_known_at=pd.Timestamp(sector.iloc[-1]["trade_date"]),
            )
        )
    return records


def _start_restart_aware_impulse(
    row: pd.Series,
    *,
    position: int,
    anchor_mode: str,
    reset_drawdown_pct: float,
    minimum_restart_gap_sessions: int,
    exit_drawdown_pct: float,
    exit_confirm_sessions: int,
) -> dict[str, object]:
    anchor_date = pd.Timestamp(row["trade_date"]).normalize()
    sector_id = str(row["sector_id"])
    campaign_key = (
        f"restart-aware|{anchor_mode}|{reset_drawdown_pct:.1f}|"
        f"{minimum_restart_gap_sessions}|{exit_drawdown_pct:.1f}|"
        f"{exit_confirm_sessions}|{sector_id}|{anchor_date.date().isoformat()}"
    )
    return {
        "campaign_id": sha1(campaign_key.encode("utf-8")).hexdigest(),
        "anchor_mode": anchor_mode,
        "reset_drawdown_pct": reset_drawdown_pct,
        "minimum_restart_gap_sessions": minimum_restart_gap_sessions,
        "exit_drawdown_pct": exit_drawdown_pct,
        "exit_confirm_sessions": exit_confirm_sessions,
        "sector_id": sector_id,
        "concept_name": str(row["concept_name"]),
        "anchor_date": anchor_date,
        "anchor_price": float(row["close_price"]),
        "anchor_position": position,
        "peak_price": float(row["close_price"]),
        "peak_position": position,
        "peak_date": anchor_date,
        "reset_observed": False,
        "first_reset_date": pd.NaT,
        "below_exit_count": 0,
    }


def _advance_restart_aware_impulse(
    active: dict[str, object],
    row: pd.Series,
    *,
    position: int,
) -> None:
    close_price = float(row["close_price"])
    trade_date = pd.Timestamp(row["trade_date"]).normalize()
    if close_price > float(active["peak_price"]):
        active["peak_price"] = close_price
        active["peak_position"] = position
        active["peak_date"] = trade_date

    drawdown_pct = (close_price / float(active["peak_price"]) - 1.0) * 100.0
    if drawdown_pct <= -float(active["reset_drawdown_pct"]):
        if not bool(active["reset_observed"]):
            active["first_reset_date"] = trade_date
        active["reset_observed"] = True
    if drawdown_pct <= -float(active["exit_drawdown_pct"]):
        active["below_exit_count"] = int(active["below_exit_count"]) + 1
    else:
        active["below_exit_count"] = 0


def _restart_aware_impulse_record(
    active: Mapping[str, object],
    sector: pd.DataFrame,
    *,
    end_position: int,
    end_reason: str,
    end_known_at: pd.Timestamp,
) -> dict[str, object]:
    terminal = sector.iloc[end_position]
    anchor_price = float(active["anchor_price"])
    peak_price = float(active["peak_price"])
    terminal_price = float(terminal["close_price"])
    return {
        "campaign_id": active["campaign_id"],
        "anchor_mode": active["anchor_mode"],
        "reset_drawdown_pct": active["reset_drawdown_pct"],
        "minimum_restart_gap_sessions": active["minimum_restart_gap_sessions"],
        "exit_drawdown_pct": active["exit_drawdown_pct"],
        "exit_confirm_sessions": active["exit_confirm_sessions"],
        "sector_id": active["sector_id"],
        "concept_name": active["concept_name"],
        "anchor_date": active["anchor_date"],
        "anchor_price": anchor_price,
        "end_date": pd.Timestamp(terminal["trade_date"]).normalize(),
        "end_known_at": end_known_at.normalize(),
        "end_reason": end_reason,
        "right_censored": end_reason == "right_censored",
        "campaign_days": end_position - int(active["anchor_position"]) + 1,
        "running_high_price": peak_price,
        "running_high_date": active["peak_date"],
        "peak_gain_pct": (peak_price / anchor_price - 1.0) * 100.0,
        "terminal_gain_pct": (terminal_price / anchor_price - 1.0) * 100.0,
        "days_to_peak": int(active["peak_position"])
        - int(active["anchor_position"]),
        "reset_observed": bool(active["reset_observed"]),
        "first_reset_date": active["first_reset_date"],
    }


def _candidate_path_rows(
    campaign: dict[str, object],
    event: dict[str, object],
    features: pd.DataFrame,
) -> list[dict[str, object]]:
    anchor_date = pd.Timestamp(campaign["anchor_date"])
    ignition_date = pd.Timestamp(event["source_date"])
    end_date = pd.Timestamp(campaign["end_date"])
    prior = features.loc[features["trade_date"].lt(anchor_date)]
    if prior.empty:
        return []
    anchor_base_date = pd.Timestamp(prior.iloc[-1]["trade_date"])
    anchor_base_close = float(prior.iloc[-1]["close_price"])
    path = features.loc[
        features["trade_date"].between(ignition_date, end_date)
    ].copy()
    if path.empty or not path.iloc[0]["trade_date"] == ignition_date:
        return []
    path["strong_close"] = path["daily_return_pct"].ge(STRONG_CLOSE_PCT)
    path["strong_closes_since_ignition"] = path["strong_close"].cumsum()
    path["sessions_since_ignition"] = np.arange(len(path), dtype=int)
    path["cumulative_gain_pct"] = (
        path["close_price"] / anchor_base_close - 1.0
    ) * 100.0
    path["running_high_price"] = path["high_price"].cummax()
    leader_spell_id = f"{campaign['campaign_id']}:{event['vt_symbol']}"
    result: list[dict[str, object]] = []
    for row in path.to_dict("records"):
        result.append(
            {
                "leader_spell_id": leader_spell_id,
                "campaign_id": str(campaign["campaign_id"]),
                "sector_id": str(campaign["sector_id"]),
                "concept_name": str(campaign["concept_name"]),
                "anchor_date": anchor_date,
                "campaign_end_date": end_date,
                "anchor_base_date": anchor_base_date,
                "anchor_base_close": anchor_base_close,
                "ignition_date": ignition_date,
                "ignition_limit_times": int(event["limit_times"]),
                "vt_symbol": str(event["vt_symbol"]),
                "stock_name": str(event["stock_name"]),
                **row,
                "feature_cutoff_date": pd.Timestamp(row["trade_date"]),
            }
        )
    return result


def _prepare_campaigns(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, CAMPAIGN_COLUMNS, "concept campaign")
    result = frame.loc[:, list(CAMPAIGN_COLUMNS)].copy()
    result["campaign_id"] = result["campaign_id"].astype(str)
    result["sector_id"] = result["sector_id"].astype(str)
    for column in ("anchor_date", "end_date"):
        result[column] = pd.to_datetime(result[column], errors="raise").dt.normalize()
    if result["campaign_id"].duplicated().any():
        raise ValueError("concept campaign identities must be unique")
    if result["end_date"].lt(result["anchor_date"]).any():
        raise ValueError("concept campaign end cannot precede its anchor")
    return result.sort_values(["anchor_date", "campaign_id"], kind="stable")


def _prepare_relations(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, RELATION_COLUMNS, "event concept relation")
    result = frame.loc[:, list(RELATION_COLUMNS)].copy()
    result["source_date"] = pd.to_datetime(
        result["source_date"], errors="raise"
    ).dt.normalize()
    for column in ("sector_id", "vt_symbol"):
        result[column] = result[column].astype(str)
    result["limit_times"] = pd.to_numeric(
        result["limit_times"], errors="raise"
    ).astype(int)
    if result.duplicated(["source_date", "sector_id", "vt_symbol"]).any():
        raise ValueError("event concept relation identities must be unique")
    return result.sort_values(
        ["source_date", "sector_id", "vt_symbol"], kind="stable"
    )


def _prepare_stock_bars(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, BAR_COLUMNS, "stock daily bar")
    result = frame.loc[:, list(BAR_COLUMNS)].copy()
    result["vt_symbol"] = result["vt_symbol"].astype(str)
    result["trade_date"] = pd.to_datetime(
        result["trade_date"], errors="raise"
    ).dt.normalize()
    if result.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock daily bar identities must be unique")
    numeric_columns = [
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "turnover",
    ]
    result[numeric_columns] = result[numeric_columns].apply(
        pd.to_numeric, errors="coerce"
    )
    values = result[numeric_columns].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("stock daily values must be finite")
    if (result[["open_price", "high_price", "low_price", "close_price"]] <= 0).any().any():
        raise ValueError("stock prices must be positive")
    if (result[["volume", "turnover"]] < 0).any().any():
        raise ValueError("stock volume and turnover cannot be negative")
    result = result.sort_values(["vt_symbol", "trade_date"], kind="stable")
    grouped = result.groupby("vt_symbol", sort=False)
    result["daily_return_pct"] = (
        grouped["close_price"].pct_change(fill_method=None) * 100.0
    )
    for window in (5, 10, 20):
        result[f"ma{window}"] = grouped["close_price"].transform(
            lambda values, size=window: values.rolling(size, min_periods=size).mean()
        )
    return result.reset_index(drop=True)


def _require_columns(
    frame: pd.DataFrame,
    columns: Iterable[str],
    label: str,
) -> None:
    missing = sorted(set(columns) - set(frame))
    if missing:
        raise ValueError(f"{label} missing columns: {', '.join(missing)}")
