"""Membership-proxy daily discovery orchestration and exploratory metrics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .events import (
    MAIN_RISE_CONFIRMED,
    attach_daily_event_metrics,
    build_daily_discovery_events,
    classify_daily_family_tags,
)
from .leader_rank import rank_concept_leaders
from .main_rise import build_main_rise_states
from .outcomes import generate_daily_proxy_outcomes
from .repository import ProxyResearchInputs
from .time_split import chronological_split_labels

SHANGHAI = ZoneInfo("Asia/Shanghai")
RESEARCH_VERSION = "low-suction-membership-proxy-v1"


@dataclass(frozen=True)
class ProxyDiscoveryResult:
    summary: dict[str, Any]
    concept_states: pd.DataFrame
    ranked_rows: pd.DataFrame
    events: pd.DataFrame
    outcomes: pd.DataFrame
    stressed_outcomes: pd.DataFrame


def apply_theme_eligibility_guard(
    ranked: pd.DataFrame,
    eligibility: pd.DataFrame,
    *,
    taxonomy_status: str,
    taxonomy_version: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach one frozen taxonomy and return eligible plus fully audited rows."""

    required_ranked = {"sector_id", "trade_date"}
    required_eligibility = {
        "sector_id",
        "cutoff",
        "eligible",
        "eligibility_class",
        "eligibility_reason",
    }
    missing_ranked = sorted(required_ranked - set(ranked.columns))
    missing_eligibility = sorted(required_eligibility - set(eligibility.columns))
    if missing_ranked or missing_eligibility:
        missing = missing_ranked + missing_eligibility
        raise ValueError(f"missing theme eligibility guard columns: {', '.join(missing)}")
    candidates = ranked.copy()
    candidates["trade_date"] = pd.to_datetime(
        candidates["trade_date"], errors="raise"
    ).dt.normalize()
    decisions = eligibility.copy()
    decisions["cutoff"] = pd.to_datetime(
        decisions["cutoff"], errors="raise"
    ).dt.normalize()
    if decisions.duplicated(["sector_id", "cutoff"]).any():
        raise ValueError("theme eligibility decisions must be unique per sector/cutoff")
    audited = candidates.merge(
        decisions,
        left_on=["sector_id", "trade_date"],
        right_on=["sector_id", "cutoff"],
        how="left",
        validate="many_to_one",
    )
    missing_decision = audited["eligible"].isna()
    audited.loc[missing_decision, "eligible"] = False
    audited.loc[missing_decision, "eligibility_class"] = "ambiguous"
    audited.loc[missing_decision, "eligibility_reason"] = "missing_decision"
    if taxonomy_status != "qualified_taxonomy":
        audited["eligible"] = False
        audited["eligibility_reason"] = taxonomy_status
    audited["eligible"] = audited["eligible"].astype(bool)
    audited["theme_eligibility_version"] = taxonomy_version
    accepted = audited.loc[audited["eligible"]].copy()
    return accepted.reset_index(drop=True), audited.reset_index(drop=True)


def run_membership_proxy_discovery(inputs: ProxyResearchInputs) -> ProxyDiscoveryResult:
    """Run the bounded proxy study while keeping formal metrics unavailable."""

    concept_states = build_main_rise_states(
        inputs.concept_bars,
        trading_dates=inputs.trading_dates,
        evidence_level="membership_proxy",
    )
    stock_features = prepare_stock_features(
        inputs.stock_bars,
        trading_dates=inputs.trading_dates,
    )
    ranked = build_proxy_rank_features(
        concept_states,
        stock_features,
        inputs.memberships,
        signal_dates=inputs.signal_dates,
    )
    product_events = build_daily_discovery_events(ranked)
    product_events["cohort"] = "main_rise_top3"
    comparisons = build_comparison_events(ranked)
    events = pd.concat([product_events, comparisons], ignore_index=True, sort=False)
    events = _attach_timing_and_split(events, inputs.timing_labels)

    outcome_bars = _prepare_outcome_bars(inputs.stock_bars)
    outcomes = generate_daily_proxy_outcomes(
        events,
        outcome_bars,
        trading_dates=inputs.trading_dates,
    )
    stressed = generate_daily_proxy_outcomes(
        events,
        outcome_bars,
        trading_dates=inputs.trading_dates,
        cost_multiplier=2.0,
    )
    summary = summarize_proxy_outcomes(events, outcomes)
    summary.update(
        {
            "research_version": RESEARCH_VERSION,
            "coverage": inputs.coverage,
            "ranked_rows": int(len(ranked)),
            "events": int(len(events)),
            "product_events": int((events["cohort"] == "main_rise_top3").sum()),
            "stressed_closed": int((stressed["status"] == "closed").sum()),
        }
    )
    return ProxyDiscoveryResult(
        summary=summary,
        concept_states=concept_states,
        ranked_rows=ranked,
        events=events,
        outcomes=outcomes,
        stressed_outcomes=stressed,
    )


def prepare_stock_features(
    bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> pd.DataFrame:
    """Compute daily stock features using only the current and earlier sessions."""

    required = {
        "vt_symbol",
        "trade_date",
        "open_price",
        "close_price",
        "high_price",
        "low_price",
        "volume",
        "turnover",
    }
    missing = sorted(required - set(bars.columns))
    if missing:
        raise ValueError(f"missing stock bar columns: {', '.join(missing)}")
    if bars.empty:
        return pd.DataFrame()

    source = bars.copy()
    source["trade_date"] = pd.to_datetime(source["trade_date"], errors="raise").dt.normalize()
    if source.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock vt_symbol/trade_date rows must be unique")
    calendar = pd.DatetimeIndex(pd.to_datetime(list(trading_dates), errors="raise"))
    calendar = calendar.normalize().drop_duplicates().sort_values()
    frames = [
        _stock_feature_frame(str(vt_symbol), group, calendar)
        for vt_symbol, group in source.groupby("vt_symbol", sort=True)
    ]
    return pd.concat(frames, ignore_index=True).sort_values(
        ["trade_date", "vt_symbol"],
        kind="stable",
        ignore_index=True,
    )


def build_proxy_rank_features(
    concept_states: pd.DataFrame,
    stock_features: pd.DataFrame,
    memberships: pd.DataFrame,
    *,
    signal_dates: Sequence[date],
) -> pd.DataFrame:
    """Rank current members by D-close features, retaining only ranks 1-10."""

    required_memberships = {"sector_id", "concept_name", "vt_symbol"}
    missing = sorted(required_memberships - set(memberships.columns))
    if missing:
        raise ValueError(f"missing membership columns: {', '.join(missing)}")
    dates = {pd.Timestamp(value).normalize() for value in signal_dates}
    states = concept_states.loc[
        concept_states["trade_date"].isin(dates)
        & (concept_states["state"] != "UNKNOWN")
    ].copy()
    states["concept_strength_score"] = states.groupby("trade_date")[
        "return_5d_pct"
    ].rank(method="average", pct=True) * 100.0

    ranked_dates: list[pd.DataFrame] = []
    membership_columns = ["sector_id", "concept_name", "vt_symbol"]
    membership_frame = memberships[membership_columns].drop_duplicates()
    for trade_date in sorted(dates):
        day_states = states.loc[states["trade_date"] == trade_date]
        day_stocks = stock_features.loc[stock_features["trade_date"] == trade_date]
        if day_states.empty or day_stocks.empty:
            continue
        pairs = membership_frame.merge(
            day_states,
            on="sector_id",
            how="inner",
            suffixes=("", "_state"),
        ).merge(day_stocks, on="vt_symbol", how="inner", suffixes=("_concept", ""))
        if pairs.empty:
            continue
        pairs = _rank_columns(pairs, trade_date)
        ranked = rank_concept_leaders(pairs, membership_mode="current_proxy")
        ranked_dates.append(ranked.loc[ranked["rank"].fillna(999) <= 10].copy())
    if not ranked_dates:
        return pd.DataFrame()
    return pd.concat(ranked_dates, ignore_index=True).sort_values(
        ["trade_date", "sector_id", "rank", "vt_symbol"],
        kind="stable",
        ignore_index=True,
    )


def build_comparison_events(ranked: pd.DataFrame) -> pd.DataFrame:
    """Build rank and non-main-rise falsification events from the same features."""

    if ranked.empty:
        return pd.DataFrame()
    frame = ranked.copy()
    main_rank_control = (frame["state"] == MAIN_RISE_CONFIRMED) & frame["rank"].between(4, 10)
    non_main_control = (frame["state"] == "NOT_MAIN_RISE") & frame["rank"].le(3)
    frame = frame.loc[main_rank_control | non_main_control].copy()
    frame["cohort"] = np.where(
        main_rank_control.loc[frame.index],
        "main_rise_rank_4_10",
        "non_main_rise_top3",
    )
    frame = attach_daily_event_metrics(frame)
    frame["family_tags"] = frame.apply(classify_daily_family_tags, axis=1)
    frame = frame.loc[frame["family_tags"].map(bool)].copy()
    if frame.empty:
        return frame
    frame["comparison_cycle"] = frame["rise_cycle_id"].fillna(
        frame["sector_id"].astype(str)
        + ":"
        + frame["trade_date"].dt.to_period("M").astype(str)
    )
    frame = frame.sort_values(
        ["cohort", "vt_symbol", "comparison_cycle", "trade_date", "rank"],
        kind="stable",
    ).drop_duplicates(["cohort", "vt_symbol", "comparison_cycle"], keep="first")
    frame["related_concepts"] = frame["sector_id"].map(lambda value: (str(value),))
    frame["event_id"] = frame.apply(
        lambda row: (
            f"low-suction-control-v1:{row['cohort']}:"
            f"{row['trade_date'].date().isoformat()}:{row['vt_symbol']}:{row['sector_id']}"
        ),
        axis=1,
    )
    frame["signal_at"] = frame["cutoff"]
    frame["observation_cutoff"] = "daily_close"
    frame["earliest_entry"] = "next_session_open"
    return frame.reset_index(drop=True)


def summarize_proxy_outcomes(
    events: pd.DataFrame,
    outcomes: pd.DataFrame,
) -> dict[str, Any]:
    """Return exploratory matrices while keeping formal metrics explicitly null."""

    event_columns = [
        "event_id",
        "vt_symbol",
        "trade_date",
        "sector_id",
        "family_tags",
        "cohort",
        "active_direction",
        "danger_state",
        "time_split",
    ]
    merged = outcomes.merge(events[event_columns], on="event_id", how="left")
    merged = merged.explode("family_tags").rename(columns={"family_tags": "family"})
    group_columns = [
        "cohort",
        "family",
        "exit_key",
        "active_direction",
        "danger_state",
        "time_split",
    ]
    matrix = []
    for keys, group in merged.groupby(group_columns, dropna=False, sort=True):
        closed = group.loc[group["status"] == "closed", "net_return_pct"].dropna()
        positive = closed.loc[closed > 0].sum()
        negative = abs(closed.loc[closed < 0].sum())
        row = dict(zip(group_columns, keys, strict=True))
        row.update(
            {
                "evidence_level": "membership_proxy",
                "events": int(group["event_id"].nunique()),
                "closed": int(len(closed)),
                "win_rate_pct": round(float((closed > 0).mean() * 100.0), 4)
                if len(closed)
                else None,
                "mean_return_pct": round(float(closed.mean()), 4) if len(closed) else None,
                "median_return_pct": round(float(closed.median()), 4)
                if len(closed)
                else None,
                "profit_factor": round(float(positive / negative), 4)
                if negative > 0
                else None,
            }
        )
        matrix.append(row)
    return {
        "status": "exploratory_membership_proxy",
        "formal_metrics": None,
        "events": int(events["event_id"].nunique()),
        "closed_outcomes": int((outcomes["status"] == "closed").sum()),
        "matrix": matrix,
    }


def _stock_feature_frame(
    vt_symbol: str,
    group: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    frame = group.set_index("trade_date").reindex(calendar)
    frame.index.name = "trade_date"
    frame["vt_symbol"] = vt_symbol
    frame["has_bar"] = frame["close_price"].notna()
    close = pd.to_numeric(frame["close_price"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    turnover = pd.to_numeric(frame["turnover"], errors="coerce")
    frame["previous_close"] = close.shift(1)
    frame["return_1d_pct"] = (close / close.shift(1) - 1.0) * 100.0
    for sessions in (5, 10, 20):
        frame[f"return_{sessions}d_pct"] = (
            close / close.shift(sessions) - 1.0
        ) * 100.0
    change_pct = pd.to_numeric(frame.get("change_pct"), errors="coerce")
    change_pct = change_pct.fillna(frame["return_1d_pct"])
    strong = change_pct >= 5.0
    limit_up = change_pct >= 9.5
    frame["limit_up_count_20d"] = limit_up.rolling(20, min_periods=20).sum()
    frame["strong_day_count_20d"] = strong.rolling(20, min_periods=20).sum()
    frame["sessions_since_strong"] = _sessions_since_true(strong)
    rolling_high = close.rolling(20, min_periods=20).max()
    frame["max_drawdown_20d_pct"] = (close / rolling_high - 1.0) * 100.0
    frame["sessions_since_peak"] = close.rolling(20, min_periods=20).apply(
        lambda values: float(len(values) - 1 - int(np.argmax(values))),
        raw=True,
    )
    frame["drawdown_from_peak_pct"] = frame["max_drawdown_20d_pct"]
    frame["ma5"] = close.rolling(5, min_periods=5).mean()
    frame["ma10"] = close.rolling(10, min_periods=10).mean()
    above_ma10 = close >= frame["ma10"]
    frame["ma10_hold_ratio"] = above_ma10.rolling(10, min_periods=10).mean()
    frame["turnover"] = turnover
    frame["turnover_median_20d"] = turnover.rolling(20, min_periods=20).median()
    frame["turnover_nonzero_ratio"] = turnover.gt(0).rolling(20, min_periods=20).mean()
    average_volume = volume.rolling(5, min_periods=5).mean()
    frame["volume_ratio_5d"] = volume.div(average_volume.where(average_volume != 0))
    frame["prior_strong_day"] = strong.shift(1, fill_value=False)
    return frame.loc[frame["has_bar"]].reset_index().drop(columns=["has_bar"])


def _sessions_since_true(values: pd.Series) -> pd.Series:
    positions = pd.Series(np.arange(len(values), dtype=float), index=values.index)
    last_true = positions.where(values.fillna(False)).ffill()
    return positions - last_true


def _rank_columns(pairs: pd.DataFrame, trade_date: pd.Timestamp) -> pd.DataFrame:
    frame = pairs.copy()
    frame["trade_date"] = trade_date
    local_cutoff = pd.Timestamp(trade_date).replace(hour=15, tzinfo=SHANGHAI)
    frame["cutoff"] = local_cutoff
    frame["feature_cutoff"] = local_cutoff
    for sessions in (5, 10, 20):
        frame[f"relative_strength_{sessions}d"] = (
            frame[f"return_{sessions}d_pct"] - frame[f"return_{sessions}d_pct_concept"]
        )
    concept_change = (
        frame["change_pct_concept"].fillna(0.0)
        if "change_pct_concept" in frame
        else pd.Series(0.0, index=frame.index)
    )
    frame["divergence_relative_return"] = frame["return_1d_pct"] - concept_change
    frame["concept_correlation_20d"] = 0.5
    frame["launch_lead_sessions"] = (
        frame["state_age"] - frame["sessions_since_strong"]
    )
    relative_columns = [
        "relative_strength_5d",
        "relative_strength_10d",
        "relative_strength_20d",
    ]
    frame["intraday_lead_ratio"] = frame[relative_columns].gt(0).mean(axis=1)
    frame["evidence_level"] = "membership_proxy"
    return frame


def _attach_timing_and_split(
    events: pd.DataFrame,
    timing_labels: pd.DataFrame,
) -> pd.DataFrame:
    if events.empty:
        return events
    result = events.copy()
    result["trade_date"] = (
        pd.to_datetime(result["trade_date"], errors="raise")
        .dt.normalize()
        .astype("datetime64[ns]")
    )
    if timing_labels.empty:
        result["active_direction"] = "UNKNOWN"
        result["zone_direction"] = "UNKNOWN"
        result["danger_state"] = "UNKNOWN"
        result["market_phase"] = "UNKNOWN"
    else:
        normalized_labels = timing_labels.copy()
        normalized_labels["trade_date"] = (
            pd.to_datetime(normalized_labels["trade_date"], errors="raise")
            .dt.normalize()
            .astype("datetime64[ns]")
        )
        result = result.merge(normalized_labels, on="trade_date", how="left")
        for column in (
            "active_direction",
            "zone_direction",
            "danger_state",
            "market_phase",
        ):
            result[column] = result[column].fillna("UNKNOWN")
    if result["trade_date"].nunique() >= 3:
        result = chronological_split_labels(result)
    else:
        result["time_split"] = "insufficient_dates"
    return result


def _prepare_outcome_bars(stock_bars: pd.DataFrame) -> pd.DataFrame:
    bars = stock_bars.copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.normalize()
    bars = bars.sort_values(["vt_symbol", "trade_date"], kind="stable")
    previous_close = bars.groupby("vt_symbol", sort=False)["close_price"].shift(1)
    bars["limit_up_price"] = previous_close * 1.10
    bars["limit_down_price"] = previous_close * 0.90
    bars["suspended"] = pd.to_numeric(bars["volume"], errors="coerce").fillna(0).le(0)
    return bars
