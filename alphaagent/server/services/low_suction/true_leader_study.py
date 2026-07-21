"""Causal concept-cycle leader identity and retrospective wave validation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .leader_waves import build_leader_wave_ledger


STRONG_DAY_PCT = 5.0
MIN_CONCEPT_RELATIVE_PERCENTILE = 0.80
MIN_COMPLETE_MEMBERS = 3
MAX_COMPLETE_MEMBERS = 300
MIN_RECENT_IGNITED = 3
MIN_RECENT_IGNITED_SHARE = 0.05
TRUTH_HORIZON_SESSIONS = 40
MIN_PROXY_TOP1_EXACT_RATE_PCT = 30.0
MIN_PROXY_TOP3_CAPTURE_RATE_PCT = 60.0
MIN_PROXY_TOP3_OVERLAP_PCT = 50.0
EVIDENCE_LEVEL = "current_membership_and_security_proxy"
PROHIBITED_RANK_TOKENS = (
    "future_",
    "truth_",
    "net_return",
    "gross_return",
    "exit_price",
    "mfe",
    "mae",
    "outcome",
)
REFERENCE_CAMPAIGNS = (
    ("600170.SSE", "上海建工", date(2025, 9, 15)),
    ("002636.SZSE", "金安国纪", date(2026, 1, 15)),
    ("600183.SSE", "生益科技", date(2026, 5, 13)),
)


@dataclass(frozen=True)
class TrueLeaderStudyInputs:
    cycle_starts: pd.DataFrame
    memberships: pd.DataFrame
    stock_bars: pd.DataFrame
    concept_bars: pd.DataFrame
    reference_bars: pd.DataFrame
    reason_relations: pd.DataFrame
    trading_dates: tuple[date, ...]
    coverage: dict[str, Any]
    fingerprints: dict[str, dict[str, Any]]


def build_point_in_time_stock_features(stock_bars: pd.DataFrame) -> pd.DataFrame:
    """Build trailing stock descriptors without shifting future values backward."""

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
    _require_columns(stock_bars, required, "stock bar")
    frame = stock_bars.loc[:, list(required)].copy()
    frame["vt_symbol"] = frame["vt_symbol"].astype(str).str.strip()
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    if frame.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock daily bar identities must be unique")
    numeric_columns = list(required[2:])
    frame[numeric_columns] = frame[numeric_columns].apply(
        pd.to_numeric,
        errors="coerce",
    )
    numeric = frame[numeric_columns].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or (numeric <= 0).any():
        raise ValueError("stock daily bar values must be finite and positive")
    frame = frame.sort_values(
        ["vt_symbol", "trade_date"], kind="stable"
    ).reset_index(drop=True)
    grouped = frame.groupby("vt_symbol", sort=False)
    frame["daily_return_pct"] = (
        grouped["close_price"].pct_change(fill_method=None) * 100.0
    )
    frame["strong_day"] = frame["daily_return_pct"].ge(STRONG_DAY_PCT)
    frame["strong_days_3"] = grouped["strong_day"].transform(
        lambda values: values.rolling(3, min_periods=1).sum()
    )
    frame["strong_days_10"] = grouped["strong_day"].transform(
        lambda values: values.rolling(10, min_periods=1).sum()
    )
    frame["return_10d_pct"] = (
        grouped["close_price"].pct_change(10, fill_method=None) * 100.0
    )
    frame["ma5"] = grouped["close_price"].transform(
        lambda values: values.rolling(5, min_periods=5).mean()
    )
    frame["ma10"] = grouped["close_price"].transform(
        lambda values: values.rolling(10, min_periods=10).mean()
    )
    frame["ma20"] = grouped["close_price"].transform(
        lambda values: values.rolling(20, min_periods=20).mean()
    )
    frame["turnover_median_20d"] = grouped["turnover"].transform(
        lambda values: values.rolling(20, min_periods=20).median()
    )
    frame["prior_high20"] = grouped["high_price"].transform(
        lambda values: values.shift(1).rolling(20, min_periods=20).max()
    )
    frame["distance_from_prior_high_pct"] = (
        frame["close_price"] / frame["prior_high20"] - 1.0
    ) * 100.0

    global_position = pd.Series(
        np.arange(len(frame), dtype=float),
        index=frame.index,
    )
    strong_position = global_position.where(frame["strong_day"])
    earliest = strong_position.groupby(frame["vt_symbol"], sort=False).transform(
        lambda values: values.rolling(10, min_periods=1).min()
    )
    latest = strong_position.groupby(frame["vt_symbol"], sort=False).transform(
        lambda values: values.rolling(10, min_periods=1).max()
    )
    frame["first_strong_sessions_ago_10d"] = global_position - earliest
    frame["last_strong_sessions_ago_10d"] = global_position - latest
    first_dates = np.full(len(frame), np.datetime64("NaT"), dtype="datetime64[ns]")
    valid_earliest = earliest.notna().to_numpy()
    date_values = frame["trade_date"].to_numpy(dtype="datetime64[ns]")
    first_dates[valid_earliest] = date_values[
        earliest.loc[valid_earliest].astype(int).to_numpy()
    ]
    frame["first_strong_date_10d"] = pd.to_datetime(first_dates)

    complete_columns = (
        "return_10d_pct",
        "ma5",
        "ma10",
        "ma20",
        "turnover_median_20d",
        "prior_high20",
    )
    complete_values = frame.loc[:, list(complete_columns)].to_numpy(dtype=float)
    frame["feature_complete"] = np.isfinite(complete_values).all(axis=1)
    frame["feature_status"] = np.where(
        frame["feature_complete"],
        "complete",
        "incomplete_trailing_history",
    )
    return frame.reset_index(drop=True)


def build_emotion_cycle_candidates(
    cycle_starts: pd.DataFrame,
    memberships: pd.DataFrame,
    stock_features: pd.DataFrame,
) -> pd.DataFrame:
    """Return point-in-time candidates for breadth-qualified concept cycles."""

    cycle_columns = (
        "cycle_id",
        "sector_id",
        "concept_name",
        "trade_date",
        "relative_percentile",
        "close_price",
        "concept_return_10d",
    )
    membership_columns = ("sector_id", "vt_symbol", "stock_name")
    feature_columns = (
        "vt_symbol",
        "trade_date",
        "close_price",
        "strong_days_3",
        "strong_days_10",
        "return_10d_pct",
        "ma5",
        "ma10",
        "ma20",
        "turnover_median_20d",
        "distance_from_prior_high_pct",
        "first_strong_sessions_ago_10d",
        "last_strong_sessions_ago_10d",
        "first_strong_date_10d",
        "feature_complete",
        "feature_status",
    )
    _require_columns(cycle_starts, cycle_columns, "cycle start")
    _require_columns(memberships, membership_columns, "membership")
    _require_columns(stock_features, feature_columns, "stock feature")

    cycles = cycle_starts.loc[:, list(cycle_columns)].copy()
    cycles["trade_date"] = pd.to_datetime(
        cycles["trade_date"], errors="raise"
    ).dt.normalize()
    cycles["sector_id"] = cycles["sector_id"].astype(str)
    if cycles["cycle_id"].duplicated().any():
        raise ValueError("cycle start IDs must be unique")
    cycles = cycles.rename(columns={"close_price": "concept_close_price"})

    members = memberships.loc[:, list(membership_columns)].copy()
    members["sector_id"] = members["sector_id"].astype(str)
    members["vt_symbol"] = members["vt_symbol"].astype(str).str.strip()
    members["stock_name"] = members["stock_name"].fillna("").astype(str).str.strip()
    if members.duplicated(["sector_id", "vt_symbol"]).any():
        raise ValueError("current membership identities must be unique")
    members = members.loc[
        members["vt_symbol"].map(_is_main_board_symbol)
        & ~members["stock_name"].map(_is_current_risk_name)
    ].copy()

    features = stock_features.loc[:, list(feature_columns)].copy()
    features["trade_date"] = pd.to_datetime(
        features["trade_date"], errors="raise"
    ).dt.normalize()
    if features.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock feature identities must be unique")
    features = features.rename(columns={"close_price": "stock_close_price"})

    frame = cycles.merge(
        members,
        on="sector_id",
        how="inner",
        validate="many_to_many",
    ).merge(
        features,
        on=["vt_symbol", "trade_date"],
        how="left",
        validate="many_to_one",
    )
    if frame.empty:
        return frame
    frame["feature_complete"] = frame["feature_complete"].fillna(False).astype(bool)
    frame["recently_ignited"] = (
        frame["feature_complete"]
        & pd.to_numeric(frame["strong_days_3"], errors="coerce").gt(0)
    )
    cycle_group = frame.groupby("cycle_id", sort=False)
    frame["complete_member_count"] = cycle_group["feature_complete"].transform("sum")
    frame["recent_ignited_count"] = cycle_group["recently_ignited"].transform("sum")
    frame["recent_ignited_share"] = (
        frame["recent_ignited_count"] / frame["complete_member_count"].replace(0, np.nan)
    )
    qualified_cycle = (
        pd.to_numeric(frame["relative_percentile"], errors="coerce").ge(
            MIN_CONCEPT_RELATIVE_PERCENTILE
        )
        & frame["complete_member_count"].between(
            MIN_COMPLETE_MEMBERS,
            MAX_COMPLETE_MEMBERS,
        )
        & frame["recent_ignited_count"].ge(MIN_RECENT_IGNITED)
        & frame["recent_ignited_share"].ge(MIN_RECENT_IGNITED_SHARE)
    )
    frame = frame.loc[
        qualified_cycle
        & frame["feature_complete"]
        & pd.to_numeric(frame["strong_days_10"], errors="coerce").ge(1)
    ].copy()
    if frame.empty:
        return frame
    eligible_count = frame.groupby("cycle_id", sort=False)["vt_symbol"].transform(
        "nunique"
    )
    frame = frame.loc[eligible_count.ge(3)].copy()
    frame["stock_excess_concept_10d_pct"] = (
        pd.to_numeric(frame["return_10d_pct"], errors="coerce")
        - pd.to_numeric(frame["concept_return_10d"], errors="coerce") * 100.0
    )
    frame["main_rise_alive"] = (
        frame["stock_close_price"].ge(frame["ma5"])
        & frame["ma5"].gt(frame["ma10"])
        & frame["ma10"].gt(frame["ma20"])
    )
    frame["ignition_precedes_concept"] = pd.to_datetime(
        frame["first_strong_date_10d"], errors="coerce"
    ).lt(frame["trade_date"])
    frame["candidate_pool_size"] = frame.groupby("cycle_id", sort=False)[
        "vt_symbol"
    ].transform("nunique")
    frame["feature_cutoff_date"] = frame["trade_date"]
    frame["evidence_level"] = EVIDENCE_LEVEL
    return frame.sort_values(
        ["trade_date", "sector_id", "vt_symbol"], kind="stable"
    ).reset_index(drop=True)


def rank_causal_cycle_leaders(candidates: pd.DataFrame) -> pd.DataFrame:
    """Freeze causal and ten-day-excess baseline ranks for each cycle."""

    leaked = sorted(
        column
        for column in candidates
        if any(token in str(column).lower() for token in PROHIBITED_RANK_TOKENS)
    )
    if leaked:
        raise ValueError(f"future or outcome columns are prohibited: {leaked}")
    required = (
        "cycle_id",
        "trade_date",
        "sector_id",
        "vt_symbol",
        "main_rise_alive",
        "ignition_precedes_concept",
        "first_strong_sessions_ago_10d",
        "strong_days_10",
        "stock_excess_concept_10d_pct",
        "distance_from_prior_high_pct",
        "turnover_median_20d",
        "feature_cutoff_date",
    )
    _require_columns(candidates, required, "leader candidate")
    if candidates.duplicated(["cycle_id", "vt_symbol"]).any():
        raise ValueError("leader candidate identities must be unique")
    pool_sizes = candidates.groupby("cycle_id", sort=False)["vt_symbol"].nunique()
    if pool_sizes.lt(3).any():
        raise ValueError("every leader cycle requires at least three candidates")

    causal = candidates.copy().sort_values(
        [
            "trade_date",
            "cycle_id",
            "main_rise_alive",
            "ignition_precedes_concept",
            "first_strong_sessions_ago_10d",
            "strong_days_10",
            "stock_excess_concept_10d_pct",
            "distance_from_prior_high_pct",
            "turnover_median_20d",
            "vt_symbol",
        ],
        ascending=[True, True, False, False, False, False, False, False, False, True],
        na_position="last",
        kind="stable",
    )
    causal["causal_rank"] = causal.groupby("cycle_id", sort=False).cumcount() + 1
    baseline_order = candidates.sort_values(
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
    baseline_order["baseline_rank"] = (
        baseline_order.groupby("cycle_id", sort=False).cumcount() + 1
    )
    causal = causal.merge(
        baseline_order.loc[:, ["cycle_id", "vt_symbol", "baseline_rank"]],
        on=["cycle_id", "vt_symbol"],
        how="left",
        validate="one_to_one",
    )
    causal["causal_top1"] = causal["causal_rank"].eq(1)
    causal["causal_top3"] = causal["causal_rank"].le(3)
    causal["baseline_top1"] = causal["baseline_rank"].eq(1)
    causal["baseline_top3"] = causal["baseline_rank"].le(3)
    causal["rank_known_at"] = pd.to_datetime(causal["feature_cutoff_date"])
    return causal.sort_values(
        ["trade_date", "cycle_id", "causal_rank"], kind="stable"
    ).reset_index(drop=True)


def build_cycle_leader_truth(
    frozen_ranks: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
    horizon: int = TRUTH_HORIZON_SESSIONS,
) -> pd.DataFrame:
    """Attach retrospective wave and excess-return truth to frozen ranks."""

    if horizon < 1:
        raise ValueError("truth horizon must be positive")
    rank_columns = (
        "cycle_id",
        "sector_id",
        "trade_date",
        "vt_symbol",
        "first_strong_date_10d",
        "causal_rank",
        "causal_top1",
        "causal_top3",
        "baseline_rank",
        "baseline_top1",
        "baseline_top3",
    )
    _require_columns(frozen_ranks, rank_columns, "frozen rank")
    if frozen_ranks.duplicated(["cycle_id", "vt_symbol"]).any():
        raise ValueError("frozen rank identities must be unique")
    stocks = _prepare_truth_stock_bars(stock_bars)
    concepts = _prepare_truth_concept_bars(concept_bars)
    calendar = tuple(sorted(set(pd.to_datetime(tuple(trading_dates)).normalize())))
    positions = {value: index for index, value in enumerate(calendar)}
    stock_groups = {
        str(symbol): group.sort_values("trade_date", kind="stable").reset_index(drop=True)
        for symbol, group in stocks.groupby("vt_symbol", sort=False)
    }
    concept_groups = {
        str(sector_id): group.sort_values("trade_date", kind="stable").reset_index(drop=True)
        for sector_id, group in concepts.groupby("sector_id", sort=False)
    }
    wave_cache: dict[tuple[str, pd.Timestamp, pd.Timestamp], dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for input_order, rank in enumerate(frozen_ranks.to_dict("records")):
        result = dict(rank)
        result["_input_order"] = input_order
        cycle_date = pd.Timestamp(rank["trade_date"]).normalize()
        position = positions.get(cycle_date)
        if position is None or position + horizon >= len(calendar):
            rows.append(_censored_truth(result, horizon, "censored_incomplete_40d"))
            continue
        boundary = calendar[position + horizon]
        stock = stock_groups.get(str(rank["vt_symbol"]))
        concept = concept_groups.get(str(rank["sector_id"]))
        if stock is None or concept is None:
            rows.append(_censored_truth(result, horizon, "censored_missing_future_bars"))
            continue
        required_dates = set(calendar[position : position + horizon + 1])
        stock_index = stock.set_index("trade_date", drop=False)
        concept_index = concept.set_index("trade_date", drop=False)
        if not required_dates.issubset(stock_index.index) or not required_dates.issubset(
            concept_index.index
        ):
            rows.append(_censored_truth(result, horizon, "censored_missing_future_bars"))
            continue
        anchor = pd.Timestamp(rank["first_strong_date_10d"]).normalize()
        if anchor not in stock_index.index or anchor > cycle_date:
            rows.append(_censored_truth(result, horizon, "censored_missing_anchor_bar"))
            continue

        stock_start = float(stock_index.at[cycle_date, "close_price"])
        concept_start = float(concept_index.at[cycle_date, "close_price"])
        stock_anchor = float(stock_index.at[anchor, "close_price"])
        concept_anchor = (
            float(concept_index.at[anchor, "close_price"])
            if anchor in concept_index.index
            else None
        )
        anchor_position = positions.get(anchor)
        stock_20 = float(stock_index.at[calendar[position + min(20, horizon)], "close_price"])
        concept_20 = float(
            concept_index.at[calendar[position + min(20, horizon)], "close_price"]
        )
        stock_40 = float(stock_index.at[boundary, "close_price"])
        concept_40 = float(concept_index.at[boundary, "close_price"])
        excess_path = []
        for future_date in calendar[position + 1 : position + horizon + 1]:
            stock_return = float(stock_index.at[future_date, "close_price"]) / stock_start - 1.0
            concept_return = (
                float(concept_index.at[future_date, "close_price"]) / concept_start - 1.0
            )
            excess_path.append((stock_return - concept_return) * 100.0)
        cache_key = (str(rank["vt_symbol"]), anchor, boundary)
        if cache_key not in wave_cache:
            ledger = build_leader_wave_ledger(
                stock.loc[stock["trade_date"].le(boundary)],
                anchor_date=anchor.date(),
                observation_end=boundary.date(),
            )
            successful = ledger.loc[
                ledger["resolution_status"].eq("continued_to_higher_high")
            ]
            wave_cache[cache_key] = {
                "wave_count": int(ledger["wave_number"].max()),
                "final_resolution_status": str(
                    ledger.iloc[-1]["resolution_status"]
                ),
                "successful_supports": "|".join(
                    successful["deepest_tested_support"].dropna().astype(str)
                ),
                "final_support": (
                    str(ledger.iloc[-1]["deepest_tested_support"])
                    if pd.notna(ledger.iloc[-1]["deepest_tested_support"])
                    else None
                ),
            }
        wave_summary = wave_cache[cache_key]
        result.update(
            {
                "truth_status": "complete",
                "truth_horizon_sessions": horizon,
                "truth_observation_end": boundary,
                "future_wave_count": wave_summary["wave_count"],
                "future_higher_high_confirmations": wave_summary["wave_count"] - 1,
                "future_final_resolution_status": wave_summary[
                    "final_resolution_status"
                ],
                "future_successful_supports": wave_summary["successful_supports"],
                "future_final_support": wave_summary["final_support"],
                "ignition_lead_sessions": (
                    position - anchor_position if anchor_position is not None else None
                ),
                "stock_ignition_to_cycle_return_pct": (
                    stock_start / stock_anchor - 1.0
                )
                * 100.0,
                "concept_ignition_to_cycle_return_pct": (
                    (concept_start / concept_anchor - 1.0) * 100.0
                    if concept_anchor is not None
                    else None
                ),
                "concept_future_5d_return_pct": (
                    float(concept_index.at[calendar[position + 5], "close_price"])
                    / concept_start
                    - 1.0
                )
                * 100.0,
                "future_20d_close_excess_pct": (
                    (stock_20 / stock_start - 1.0)
                    - (concept_20 / concept_start - 1.0)
                )
                * 100.0,
                "future_40d_close_excess_pct": (
                    (stock_40 / stock_start - 1.0)
                    - (concept_40 / concept_start - 1.0)
                )
                * 100.0,
                "future_40d_max_excess_pct": max(excess_path),
            }
        )
        rows.append(result)

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
    qualified_cycles = set(complete["cycle_id"].astype(str))
    identities = pd.MultiIndex.from_frame(result[["cycle_id", "vt_symbol"]])
    mapped = rank_map.reindex(identities)
    result["truth_rank"] = pd.array(mapped.to_numpy(), dtype="Int64")
    result["truth_cycle_qualified"] = result["cycle_id"].astype(str).isin(
        qualified_cycles
    )
    result["truth_top1"] = result["truth_rank"].eq(1).fillna(False)
    result["truth_top3"] = result["truth_rank"].le(3).fillna(False)
    return result.sort_values("_input_order", kind="stable").drop(
        columns=["_input_order"]
    ).reset_index(drop=True)


def assign_true_leader_blocks(
    labels: pd.DataFrame,
    *,
    block_count: int = 5,
) -> pd.DataFrame:
    """Assign every cycle on the same date to one chronological block."""

    _require_columns(
        labels,
        ("cycle_id", "trade_date", "truth_cycle_qualified"),
        "truth label",
    )
    if block_count < 1:
        raise ValueError("block count must be positive")
    result = labels.drop(columns=["block"], errors="ignore").copy()
    result["trade_date"] = pd.to_datetime(
        result["trade_date"], errors="raise"
    ).dt.normalize()
    eligible_dates = tuple(
        sorted(
            result.loc[result["truth_cycle_qualified"].astype(bool), "trade_date"]
            .drop_duplicates()
            .tolist()
        )
    )
    if len(eligible_dates) < block_count:
        raise ValueError("truth labels do not cover every requested block")
    date_to_block: dict[pd.Timestamp, int] = {}
    for block, values in enumerate(
        np.array_split(np.array(eligible_dates, dtype="datetime64[ns]"), block_count),
        start=1,
    ):
        date_to_block.update({pd.Timestamp(value): block for value in values})
    result["block"] = result["trade_date"].map(date_to_block).astype("Int64")
    return result


def evaluate_true_leader_identity(labels: pd.DataFrame) -> pd.DataFrame:
    """Compare causal and baseline identity accuracy on identical cycles."""

    required = (
        "cycle_id",
        "block",
        "truth_status",
        "truth_cycle_qualified",
        "truth_top1",
        "truth_top3",
        "future_wave_count",
        "future_40d_max_excess_pct",
        "causal_top1",
        "causal_top3",
        "baseline_top1",
        "baseline_top3",
    )
    _require_columns(labels, required, "identity label")
    eligible = labels.loc[
        labels["truth_status"].eq("complete")
        & labels["truth_cycle_qualified"].astype(bool)
        & labels["block"].notna()
    ].copy()
    segments: list[tuple[str, pd.DataFrame]] = [("all", eligible)]
    segments.extend(
        (f"block_{block}", eligible.loc[eligible["block"].eq(block)])
        for block in sorted(eligible["block"].dropna().astype(int).unique())
    )
    modes = (
        ("causal_leadership", "causal_top1", "causal_top3"),
        ("ten_day_excess_baseline", "baseline_top1", "baseline_top3"),
    )
    rows = []
    for segment_name, segment in segments:
        for mode, top1_column, top3_column in modes:
            cycle_metrics = []
            for _, cycle in segment.groupby("cycle_id", sort=False):
                truth_top1 = set(cycle.loc[cycle["truth_top1"], "vt_symbol"].astype(str))
                truth_top3 = set(cycle.loc[cycle["truth_top3"], "vt_symbol"].astype(str))
                selected_top1 = set(cycle.loc[cycle[top1_column], "vt_symbol"].astype(str))
                selected_top3 = set(cycle.loc[cycle[top3_column], "vt_symbol"].astype(str))
                cycle_metrics.append(
                    {
                        "top1_exact": selected_top1 == truth_top1,
                        "top3_captures_truth_top1": bool(selected_top3 & truth_top1),
                        "top3_overlap": len(selected_top3 & truth_top3) / 3.0,
                    }
                )
            selected = segment.loc[segment[top3_column]]
            rest = segment.loc[~segment[top3_column]]
            rows.append(
                {
                    "segment": segment_name,
                    "mode": mode,
                    "qualified_cycles": len(cycle_metrics),
                    "top1_exact_rate_pct": _mean_boolean(
                        [row["top1_exact"] for row in cycle_metrics]
                    ),
                    "top3_truth_top1_capture_rate_pct": _mean_boolean(
                        [row["top3_captures_truth_top1"] for row in cycle_metrics]
                    ),
                    "mean_truth_top3_overlap_pct": (
                        float(
                            np.mean([row["top3_overlap"] for row in cycle_metrics])
                            * 100.0
                        )
                        if cycle_metrics
                        else None
                    ),
                    "selected_vs_rest_wave_count_delta": _mean_difference(
                        selected["future_wave_count"],
                        rest["future_wave_count"],
                    ),
                    "selected_vs_rest_max_excess_delta_pct": _mean_difference(
                        selected["future_40d_max_excess_pct"],
                        rest["future_40d_max_excess_pct"],
                    ),
                }
            )
    return pd.DataFrame(rows)


def load_true_leader_study_inputs(
    *,
    include_reference_bars: bool = True,
) -> TrueLeaderStudyInputs:
    """Load broad discovery inputs and quarantined reference-stock history."""

    from sqlalchemy import func, select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine, session_scope

    from .concept_cycles import build_cycle_candidates, load_cycle_research_inputs
    from .contracts import CONCEPT_SECTOR_TYPES
    from .reason_relations import build_normalized_reason_relations
    from .research_protocol import fingerprint_frame

    cycle_inputs = load_cycle_research_inputs()
    cycle_states = build_cycle_candidates(
        cycle_inputs.concept_bars,
        cycle_inputs.market_returns,
    )
    cycle_starts = cycle_states.loc[
        cycle_states["definition"].eq("breakout_trend")
        & cycle_states["in_cycle"].astype(bool)
        & cycle_states["cycle_days"].eq(1),
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
    sector_ids = tuple(sorted(cycle_starts["sector_id"].astype(str).unique()))
    engine = get_engine()
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
                schema.stock_sector_memberships.c.vt_symbol == schema.stocks.c.vt_symbol,
            )
        )
        .where(
            schema.stock_sector_memberships.c.sector_type == "theme",
            schema.stock_sector_memberships.c.sector_id.in_(sector_ids),
        )
        .order_by(
            schema.stock_sector_memberships.c.sector_id,
            schema.stock_sector_memberships.c.vt_symbol,
        )
    )
    memberships = pd.read_sql(membership_statement, engine)
    memberships["stock_name"] = memberships["stock_name"].fillna("")
    eligible_memberships = memberships.loc[
        memberships["vt_symbol"].map(_is_main_board_symbol)
        & ~memberships["stock_name"].map(_is_current_risk_name)
    ].copy()
    symbols = tuple(sorted(eligible_memberships["vt_symbol"].astype(str).unique()))
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
                cycle_inputs.split.discovery_dates[0],
                cycle_inputs.split.discovery_dates[-1],
            ),
        )
        .order_by(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
        )
    )
    stock_bars = pd.read_sql(stock_statement, engine, parse_dates=["trade_date"])
    reference_columns = [
        "vt_symbol",
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "turnover",
        "source",
    ]
    if include_reference_bars:
        reference_symbols = tuple(item[0] for item in REFERENCE_CAMPAIGNS)
        reference_statement = (
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
            .where(schema.stock_daily_bars.c.vt_symbol.in_(reference_symbols))
            .order_by(
                schema.stock_daily_bars.c.vt_symbol,
                schema.stock_daily_bars.c.trade_date,
            )
        )
        reference_bars = pd.read_sql(
            reference_statement,
            engine,
            parse_dates=["trade_date"],
        )
    else:
        reference_bars = pd.DataFrame(columns=reference_columns)
    discovery_end = cycle_inputs.split.discovery_dates[-1]
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
                schema.stock_events.c.event_date <= discovery_end.strftime("%Y%m%d"),
            )
            .order_by(schema.stock_events.c.event_date, schema.stock_events.c.id)
        ).mappings().all()
        concept_rows = session.execute(
            select(schema.sectors.c.id, schema.sectors.c.name)
            .where(schema.sectors.c.type.in_(CONCEPT_SECTOR_TYPES))
            .order_by(schema.sectors.c.id)
        ).all()
        strict_membership_rows = int(
            session.execute(
                select(func.count()).select_from(
                    schema.low_suction_concept_membership_history
                )
            ).scalar_one()
        )
    event_frame = _normalize_reason_event_rows(event_rows)
    concepts = pd.DataFrame(concept_rows, columns=["sector_id", "concept_name"])
    reason_relations = build_normalized_reason_relations(event_frame, concepts)

    fingerprint_inputs = {
        "cycle_starts": (cycle_starts, ("cycle_id",)),
        "current_memberships": (
            eligible_memberships,
            ("sector_id", "vt_symbol"),
        ),
        "discovery_stock_bars": (stock_bars, ("trade_date", "vt_symbol")),
        "discovery_concept_bars": (
            cycle_inputs.concept_bars,
            ("trade_date", "sector_id"),
        ),
        "normalized_reason_relations": (
            reason_relations,
            ("source_date", "sector_id", "vt_symbol"),
        ),
        "reference_stock_bars": (
            reference_bars,
            ("trade_date", "vt_symbol"),
        ),
    }
    fingerprints = {
        name: fingerprint_frame(frame, identity_columns=identity).as_dict()
        for name, (frame, identity) in fingerprint_inputs.items()
    }
    coverage = {
        "discovery_start": cycle_inputs.split.discovery_dates[0].isoformat(),
        "discovery_end": discovery_end.isoformat(),
        "outer_holdout_start": cycle_inputs.split.holdout_dates[0].isoformat(),
        "outer_holdout_end": cycle_inputs.split.holdout_dates[-1].isoformat(),
        "old_holdout_status": "contaminated_not_reusable",
        "concept_cycle_starts": int(len(cycle_starts)),
        "concepts_with_cycles": int(cycle_starts["sector_id"].nunique()),
        "current_membership_rows": int(len(eligible_memberships)),
        "current_membership_symbols": int(
            eligible_memberships["vt_symbol"].nunique()
        ),
        "strict_historical_membership_rows": strict_membership_rows,
        "discovery_stock_bar_rows": int(len(stock_bars)),
        "discovery_stock_symbols": int(stock_bars["vt_symbol"].nunique()),
        "discovery_concept_bar_rows": int(len(cycle_inputs.concept_bars)),
        "reason_event_rows": int(len(event_frame)),
        "reason_event_source_start": (
            event_frame["source_date"].min().date().isoformat()
            if not event_frame.empty
            else None
        ),
        "reason_event_source_end": (
            event_frame["source_date"].max().date().isoformat()
            if not event_frame.empty
            else None
        ),
        "normalized_reason_relations": int(len(reason_relations)),
        "reference_stock_bar_rows": int(len(reference_bars)),
        "reference_start": (
            reference_bars["trade_date"].min().date().isoformat()
            if not reference_bars.empty
            else None
        ),
        "reference_end": (
            reference_bars["trade_date"].max().date().isoformat()
            if not reference_bars.empty
            else None
        ),
    }
    return TrueLeaderStudyInputs(
        cycle_starts=cycle_starts,
        memberships=eligible_memberships,
        stock_bars=stock_bars,
        concept_bars=cycle_inputs.concept_bars,
        reference_bars=reference_bars,
        reason_relations=reason_relations,
        trading_dates=cycle_inputs.split.discovery_dates,
        coverage=coverage,
        fingerprints=fingerprints,
    )


def build_reference_campaign_audit(
    reference_bars: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Audit user-raised stocks without using them for model selection."""

    _require_columns(
        reference_bars,
        (
            "vt_symbol",
            "trade_date",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
        ),
        "reference stock bar",
    )
    frame = reference_bars.copy()
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    rows = []
    for symbol, stock_name, anchor_date in REFERENCE_CAMPAIGNS:
        bars = frame.loc[frame["vt_symbol"].eq(symbol)].copy()
        available_dates = set(bars["trade_date"].dt.date)
        if bars.empty or anchor_date not in available_dates:
            rows.append(
                {
                    "vt_symbol": symbol,
                    "stock_name": stock_name,
                    "anchor_date": anchor_date.isoformat(),
                    "status": "missing_anchor_bar",
                    "used_for_model_selection": False,
                    "evidence_scope": "contaminated_descriptive_reference",
                    "waves": [],
                }
            )
            continue
        ledger = build_leader_wave_ledger(
            bars,
            anchor_date=anchor_date,
            observation_end=bars["trade_date"].max().date(),
        )
        waves = _records(ledger)
        rows.append(
            {
                "vt_symbol": symbol,
                "stock_name": stock_name,
                "anchor_date": anchor_date.isoformat(),
                "observation_end": bars["trade_date"].max().date().isoformat(),
                "status": "complete_descriptive_audit",
                "used_for_model_selection": False,
                "evidence_scope": "contaminated_descriptive_reference",
                "wave_count": int(ledger["wave_number"].max()),
                "confirmed_higher_highs": int(
                    ledger["resolution_status"].eq(
                        "continued_to_higher_high"
                    ).sum()
                ),
                "final_status": str(ledger.iloc[-1]["resolution_status"]),
                "final_record_high": float(ledger.iloc[-1]["peak_price"]),
                "waves": waves,
            }
        )
    return rows


def run_true_leader_wave_study() -> dict[str, Any]:
    """Run broad causal identity validation and quarantined case inspection."""

    inputs = load_true_leader_study_inputs()
    features = build_point_in_time_stock_features(inputs.stock_bars)
    candidates = build_emotion_cycle_candidates(
        inputs.cycle_starts,
        inputs.memberships,
        features,
    )
    ranks = rank_causal_cycle_leaders(candidates)
    labels = build_cycle_leader_truth(
        ranks,
        inputs.stock_bars,
        inputs.concept_bars,
        trading_dates=inputs.trading_dates,
    )
    blocked = assign_true_leader_blocks(labels, block_count=5)
    metrics = evaluate_true_leader_identity(blocked)
    references = build_reference_campaign_audit(inputs.reference_bars)
    return build_true_leader_report(
        inputs,
        candidates=candidates,
        labels=blocked,
        metrics=metrics,
        reference_cases=references,
    )


def build_true_leader_report(
    inputs: TrueLeaderStudyInputs,
    *,
    candidates: pd.DataFrame,
    labels: pd.DataFrame,
    metrics: pd.DataFrame,
    reference_cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build one deterministic machine report for the identity-only stage."""

    cycle_summaries = _build_cycle_summaries(labels)
    comparison = _evaluate_mode_comparison(metrics)
    relation_counts = (
        inputs.reason_relations["relation_method"].value_counts().sort_index().to_dict()
        if not inputs.reason_relations.empty
        else {}
    )
    reference_symbols = {item[0] for item in REFERENCE_CAMPAIGNS}
    relation_examples = inputs.reason_relations.loc[
        inputs.reason_relations["vt_symbol"].isin(reference_symbols)
    ].copy()
    support_distribution = _build_support_distribution(labels)
    return {
        "study_version": "true-leader-wave-identification-v1",
        "overall_conclusion": comparison["status"],
        "formal_metrics": None,
        "formal_selected_mode": None,
        "strict_top3_claim": False,
        "low_suction_rule_selected": False,
        "old_holdout_status": "contaminated_not_reusable",
        "broad_validation_scope": "discovery_only_current_membership_proxy",
        "reference_scope": "contaminated_descriptive_reference",
        "hot_money_abstraction": [
            "early stock ignition before concept breakout",
            "repeat market recognition and stock-versus-concept strength",
            "divergence is resolved only by a later higher record high",
            "second and third waves are confirmed states, never imagined in advance",
            "structural failure is retained as a counterexample",
        ],
        "person_named_formula_status": "unsupported_by_verified_first_party_evidence",
        "causal_rank_order": [
            "main_rise_alive_desc",
            "ignition_precedes_concept_desc",
            "first_strong_sessions_ago_10d_desc",
            "strong_days_10_desc",
            "stock_excess_concept_10d_pct_desc",
            "distance_from_prior_high_pct_desc",
            "turnover_median_20d_desc",
            "vt_symbol_asc",
        ],
        "emotion_cycle_gate": {
            "minimum_relative_percentile": MIN_CONCEPT_RELATIVE_PERCENTILE,
            "complete_member_range": [MIN_COMPLETE_MEMBERS, MAX_COMPLETE_MEMBERS],
            "minimum_recent_ignited_stocks": MIN_RECENT_IGNITED,
            "minimum_recent_ignited_share": MIN_RECENT_IGNITED_SHARE,
            "strong_day_pct": STRONG_DAY_PCT,
        },
        "truth_contract": {
            "horizon_sessions": TRUTH_HORIZON_SESSIONS,
            "minimum_pullback_pct": 5.0,
            "ordered_sequence": "record_peak -> later_pullback -> later_higher_high",
            "same_day_sequence_allowed": False,
            "truth_rank_order": [
                "future_wave_count_desc",
                "future_40d_max_excess_pct_desc",
                "future_20d_close_excess_pct_desc",
                "vt_symbol_asc",
            ],
        },
        "coverage": {
            **inputs.coverage,
            "qualified_emotion_cycles": int(candidates["cycle_id"].nunique()),
            "causal_candidate_rows": int(len(candidates)),
            "causal_candidate_symbols": int(candidates["vt_symbol"].nunique()),
            "truth_qualified_cycles": int(
                labels.loc[labels["truth_cycle_qualified"], "cycle_id"].nunique()
            ),
            "truth_complete_rows": int(labels["truth_status"].eq("complete").sum()),
        },
        "reason_relation_audit": {
            "method_counts": {str(key): int(value) for key, value in relation_counts.items()},
            "reference_stock_examples": _records(relation_examples),
            "semantic_aliases_invented": False,
            "note": "覆铜板 is not automatically translated to PCB",
        },
        "mode_comparison": comparison,
        "identity_metrics": _records(metrics),
        "wave_support_distribution": support_distribution,
        "lead_response_metrics": _build_lead_response_metrics(labels),
        "cycle_summaries": cycle_summaries,
        "mismatch_cycles": [
            item for item in cycle_summaries if not item["causal_top3_captured_truth_top1"]
        ][:100],
        "reference_campaigns": reference_cases,
        "fingerprints": inputs.fingerprints,
        "limitations": [
            "historical concept membership rows are absent; current membership is a survivorship proxy",
            "historical ST, suspension and delisting status is incomplete",
            "daily bars cannot order same-session high and low",
            "the prior outer holdout has been inspected and cannot be reused",
            "identity validation does not establish a low-suction entry or trading return",
        ],
        "next_stage": (
            "inspect_causal_identity_mismatches_and_collect_point_in_time_membership"
            if comparison["status"]
            != "identity_proxy_accuracy_gate_passed_but_not_strict"
            else "freeze_proxy_for_new_forward_identity_validation"
        ),
        "reproduce": (
            "docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace "
            "-w /workspace alphaagent-api python -m "
            "alphaagent.server.services.low_suction.cli "
            "v2-true-leader-wave-study --format markdown"
        ),
    }


def render_true_leader_study_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_true_leader_study_markdown(report: Mapping[str, Any]) -> str:
    coverage = report["coverage"]
    comparison = report["mode_comparison"]
    lines = [
        "# AlphaAgent 真龙头与多波主升识别研究",
        "",
        f"结论：`{report['overall_conclusion']}`。正式 Top3：`false`；正式绩效：`null`。",
        "",
        "本研究先识别龙头，不研究买点。广泛验证只使用发现段；2026 三只个股是已经看过的",
        "描述性案例，不参与特征选择或样本外主张。波次必须满足不同交易日上的",
        "`记录高点 -> 至少 5% 回调 -> 更高记录高点`。",
        "",
        "## Coverage",
        "",
        f"- 发现段：`{coverage['discovery_start']}..{coverage['discovery_end']}`。",
        f"- 原始概念周期起点：`{coverage['concept_cycle_starts']}`；情绪周期："
        f"`{coverage['qualified_emotion_cycles']}`；完整真值周期："
        f"`{coverage['truth_qualified_cycles']}`。",
        f"- 因果候选：`{coverage['causal_candidate_rows']}` 行 / "
        f"`{coverage['causal_candidate_symbols']}` 股。",
        f"- 当前成员代理：`{coverage['current_membership_rows']}` 行；严格历史成员："
        f"`{coverage['strict_historical_membership_rows']}` 行。",
        "",
        "## Identity Validation",
        "",
        "| Segment | Mode | Cycles | Top1 exact | Top3 captures truth Top1 | Top3 overlap | Wave delta vs rest | Max excess delta |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["identity_metrics"]:
        lines.append(
            f"| `{row['segment']}` | `{row['mode']}` | {row['qualified_cycles']} | "
            f"{_pct(row['top1_exact_rate_pct'])} | "
            f"{_pct(row['top3_truth_top1_capture_rate_pct'])} | "
            f"{_pct(row['mean_truth_top3_overlap_pct'])} | "
            f"{_number(row['selected_vs_rest_wave_count_delta'])} | "
            f"{_number(row['selected_vs_rest_max_excess_delta_pct'])} |"
        )
    lines.extend(
        [
            "",
            f"五块胜负：因果模式 `{comparison['causal_block_wins']}`，基线 "
            f"`{comparison['baseline_block_wins']}`，平局 `{comparison['tied_blocks']}`。",
            f"相对改善：`{str(comparison['stable_relative_improvement']).lower()}`；"
            f"绝对准确率门：`{str(comparison['identity_accuracy_gate_passed']).lower()}`。",
            "",
            "## Stock Leads, Concept Follows",
            "",
            "| Cohort | Rows | Pre-cycle ignition | Median lead sessions | Stock return to cycle | Concept response to cycle | Concept next 5d |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["lead_response_metrics"]:
        lines.append(
            f"| `{row['cohort']}` | {row['rows']} | "
            f"{_pct(row['precycle_ignition_share_pct'])} | "
            f"{_number(row['median_ignition_lead_sessions'])} | "
            f"{_pct(row['mean_stock_ignition_to_cycle_return_pct'])} | "
            f"{_pct(row['mean_concept_ignition_to_cycle_return_pct'])} | "
            f"{_pct(row['mean_concept_future_5d_return_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## Reference Campaigns",
            "",
            "| Stock | Anchor | Waves | Confirmed higher highs | Final high | Final state |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for item in report["reference_campaigns"]:
        lines.append(
            f"| {item['stock_name']} `{item['vt_symbol']}` | `{item['anchor_date']}` | "
            f"{item.get('wave_count', '-')} | {item.get('confirmed_higher_highs', '-')} | "
            f"{_number(item.get('final_record_high'))} | `{item.get('final_status', item['status'])}` |"
        )
        for wave in item.get("waves", []):
            lines.append(
                f"| ↳ 第 {wave['wave_number']} 波 | 峰 `{wave['peak_date']}` | "
                f"{_number(wave['peak_price'])} | 回调 `{wave.get('trough_date') or '-'}` | "
                f"支撑 `{wave.get('deepest_tested_support') or '-'}` | "
                f"`{wave['resolution_status']}` |"
            )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "当前成员表不是历史点时成分，旧留出也已被查看，所以本报告只能比较身份代理，",
            "不能给出正式 Top3、低吸胜率、收益或复利。上海建工的未创新高路径被保留为",
            "终止反例；金安国纪和生益科技的多波路径只用于检查状态机是否理解真实个股。",
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


def _normalize_reason_event_rows(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    records = []
    for row in rows:
        raw = dict(row["raw"] or {})
        reason = str(raw.get("涨停原因") or raw.get("reason_type") or "").strip()
        if not reason:
            continue
        records.append(
            {
                "event_id": int(row["id"]),
                "source_date": pd.to_datetime(
                    str(row["event_date"])[:8],
                    format="%Y%m%d",
                    errors="raise",
                ),
                "vt_symbol": str(row["vt_symbol"]),
                "stock_name": str(raw.get("名称") or raw.get("name") or ""),
                "reason": reason,
            }
        )
    return pd.DataFrame(
        records,
        columns=["event_id", "source_date", "vt_symbol", "stock_name", "reason"],
    )


def _build_cycle_summaries(labels: pd.DataFrame) -> list[dict[str, Any]]:
    eligible = labels.loc[
        labels["truth_status"].eq("complete")
        & labels["truth_cycle_qualified"].astype(bool)
    ].copy()
    rows = []
    for cycle_id, cycle in eligible.groupby("cycle_id", sort=False):
        cycle = cycle.sort_values("causal_rank", kind="stable")
        causal = cycle.loc[cycle["causal_top3"]].sort_values(
            "causal_rank", kind="stable"
        )
        truth = cycle.loc[cycle["truth_top3"]].sort_values(
            "truth_rank", kind="stable"
        )
        truth_top1 = set(cycle.loc[cycle["truth_top1"], "vt_symbol"].astype(str))
        causal_symbols = set(causal["vt_symbol"].astype(str))
        rows.append(
            {
                "cycle_id": str(cycle_id),
                "trade_date": pd.Timestamp(cycle.iloc[0]["trade_date"])
                .date()
                .isoformat(),
                "sector_id": str(cycle.iloc[0]["sector_id"]),
                "concept_name": str(cycle.iloc[0].get("concept_name") or ""),
                "candidate_count": int(cycle["vt_symbol"].nunique()),
                "causal_top3": _leader_rows(causal, "causal_rank"),
                "truth_top3": _leader_rows(truth, "truth_rank"),
                "causal_top3_captured_truth_top1": bool(
                    causal_symbols & truth_top1
                ),
            }
        )
    return sorted(rows, key=lambda row: (row["trade_date"], row["sector_id"]))


def _leader_rows(frame: pd.DataFrame, rank_column: str) -> list[dict[str, Any]]:
    return [
        {
            "rank": int(row[rank_column]),
            "vt_symbol": str(row["vt_symbol"]),
            "stock_name": str(row.get("stock_name") or ""),
            "first_strong_date_10d": _json_safe(row.get("first_strong_date_10d")),
            "future_wave_count": _json_safe(row.get("future_wave_count")),
            "future_40d_max_excess_pct": _json_safe(
                row.get("future_40d_max_excess_pct")
            ),
        }
        for row in frame.to_dict("records")
    ]


def _evaluate_mode_comparison(metrics: pd.DataFrame) -> dict[str, Any]:
    causal_wins = 0
    baseline_wins = 0
    tied = 0
    block_results = []
    for segment in sorted(
        value for value in metrics["segment"].astype(str).unique() if value != "all"
    ):
        block = metrics.loc[metrics["segment"].eq(segment)].set_index("mode")
        causal = _metric_tuple(block.loc["causal_leadership"])
        baseline = _metric_tuple(block.loc["ten_day_excess_baseline"])
        if causal > baseline:
            winner = "causal_leadership"
            causal_wins += 1
        elif baseline > causal:
            winner = "ten_day_excess_baseline"
            baseline_wins += 1
        else:
            winner = None
            tied += 1
        block_results.append({"segment": segment, "winner": winner})
    pooled = metrics.loc[metrics["segment"].eq("all")].set_index("mode")
    causal_row = pooled.loc["causal_leadership"]
    pooled_causal = _metric_tuple(causal_row)
    pooled_baseline = _metric_tuple(pooled.loc["ten_day_excess_baseline"])
    stable_relative_improvement = causal_wins >= 3 and pooled_causal > pooled_baseline
    accuracy_gate_passed = (
        _finite_or_negative_infinity(causal_row.get("top1_exact_rate_pct"))
        >= MIN_PROXY_TOP1_EXACT_RATE_PCT
        and _finite_or_negative_infinity(
            causal_row.get("top3_truth_top1_capture_rate_pct")
        )
        >= MIN_PROXY_TOP3_CAPTURE_RATE_PCT
        and _finite_or_negative_infinity(
            causal_row.get("mean_truth_top3_overlap_pct")
        )
        >= MIN_PROXY_TOP3_OVERLAP_PCT
    )
    if stable_relative_improvement and accuracy_gate_passed:
        status = "identity_proxy_accuracy_gate_passed_but_not_strict"
    elif stable_relative_improvement:
        status = "stable_relative_improvement_but_identity_accuracy_insufficient"
    else:
        status = "no_stable_causal_identity_improvement"
    return {
        "status": status,
        "causal_block_wins": causal_wins,
        "baseline_block_wins": baseline_wins,
        "tied_blocks": tied,
        "block_results": block_results,
        "pooled_causal_better": pooled_causal > pooled_baseline,
        "stable_relative_improvement": stable_relative_improvement,
        "identity_accuracy_gate_passed": accuracy_gate_passed,
        "identity_accuracy_gate": {
            "minimum_top1_exact_rate_pct": MIN_PROXY_TOP1_EXACT_RATE_PCT,
            "minimum_top3_truth_top1_capture_rate_pct": MIN_PROXY_TOP3_CAPTURE_RATE_PCT,
            "minimum_mean_truth_top3_overlap_pct": MIN_PROXY_TOP3_OVERLAP_PCT,
        },
        "formal_selected_mode": None,
    }


def _metric_tuple(row: pd.Series) -> tuple[float, ...]:
    return tuple(
        _finite_or_negative_infinity(row.get(column))
        for column in (
            "top3_truth_top1_capture_rate_pct",
            "top1_exact_rate_pct",
            "mean_truth_top3_overlap_pct",
            "selected_vs_rest_wave_count_delta",
            "selected_vs_rest_max_excess_delta_pct",
        )
    )


def _build_support_distribution(labels: pd.DataFrame) -> dict[str, Any]:
    leaders = labels.loc[
        labels["truth_status"].eq("complete") & labels["truth_top3"]
    ].copy()
    successful_supports: list[str] = []
    for value in leaders["future_successful_supports"].dropna().astype(str):
        successful_supports.extend(item for item in value.split("|") if item)
    terminal = leaders.loc[
        leaders["future_final_resolution_status"].eq("terminal_failure_observed")
    ]
    return {
        "truth_top3_rows": int(len(leaders)),
        "successful_pullback_supports": {
            str(key): int(value)
            for key, value in pd.Series(successful_supports, dtype="string")
            .value_counts()
            .sort_index()
            .items()
        },
        "final_resolution_status": {
            str(key): int(value)
            for key, value in leaders["future_final_resolution_status"]
            .fillna("missing")
            .value_counts()
            .sort_index()
            .items()
        },
        "terminal_final_supports": {
            str(key): int(value)
            for key, value in terminal["future_final_support"]
            .fillna("missing")
            .value_counts()
            .sort_index()
            .items()
        },
    }


def _build_lead_response_metrics(labels: pd.DataFrame) -> list[dict[str, Any]]:
    complete = labels.loc[
        labels["truth_status"].eq("complete")
        & labels["truth_cycle_qualified"].astype(bool)
    ].copy()
    cohorts = (
        ("truth_top1", complete.loc[complete["truth_top1"]]),
        ("truth_top3", complete.loc[complete["truth_top3"]]),
        ("other_candidates", complete.loc[~complete["truth_top3"]]),
    )
    rows = []
    for cohort, frame in cohorts:
        lead_sessions = pd.to_numeric(
            frame["ignition_lead_sessions"], errors="coerce"
        ).dropna()
        rows.append(
            {
                "cohort": cohort,
                "rows": int(len(frame)),
                "precycle_ignition_share_pct": (
                    float(lead_sessions.gt(0).mean() * 100.0)
                    if not lead_sessions.empty
                    else None
                ),
                "median_ignition_lead_sessions": (
                    float(lead_sessions.median()) if not lead_sessions.empty else None
                ),
                "mean_stock_ignition_to_cycle_return_pct": _series_mean(
                    frame["stock_ignition_to_cycle_return_pct"]
                ),
                "mean_concept_ignition_to_cycle_return_pct": _series_mean(
                    frame["concept_ignition_to_cycle_return_pct"]
                ),
                "mean_concept_future_5d_return_pct": _series_mean(
                    frame["concept_future_5d_return_pct"]
                ),
            }
        )
    return rows


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _json_safe(value: Any) -> Any:
    if value is None or value is pd.NA or pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, date)):
        return pd.Timestamp(value).date().isoformat()
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(float(value)) else None
    return value


def _finite_or_negative_infinity(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float("-inf")
    return numeric if np.isfinite(numeric) else float("-inf")


def _pct(value: Any) -> str:
    numeric = _finite_or_negative_infinity(value)
    return "-" if not np.isfinite(numeric) else f"{numeric:.4f}%"


def _number(value: Any) -> str:
    numeric = _finite_or_negative_infinity(value)
    return "-" if not np.isfinite(numeric) else f"{numeric:.4f}"


def _series_mean(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.mean()) if not numeric.empty else None


def _prepare_truth_stock_bars(frame: pd.DataFrame) -> pd.DataFrame:
    required = (
        "vt_symbol",
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
    )
    _require_columns(frame, required, "truth stock bar")
    bars = frame.loc[:, list(required)].copy()
    bars["vt_symbol"] = bars["vt_symbol"].astype(str)
    bars["trade_date"] = pd.to_datetime(
        bars["trade_date"], errors="raise"
    ).dt.normalize()
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("truth stock bar identities must be unique")
    return bars


def _prepare_truth_concept_bars(frame: pd.DataFrame) -> pd.DataFrame:
    required = ("sector_id", "trade_date", "close_price")
    _require_columns(frame, required, "truth concept bar")
    bars = frame.loc[:, list(required)].copy()
    bars["sector_id"] = bars["sector_id"].astype(str)
    bars["trade_date"] = pd.to_datetime(
        bars["trade_date"], errors="raise"
    ).dt.normalize()
    if bars.duplicated(["sector_id", "trade_date"]).any():
        raise ValueError("truth concept bar identities must be unique")
    return bars


def _censored_truth(
    row: dict[str, Any],
    horizon: int,
    status: str,
) -> dict[str, Any]:
    row.update(
        {
            "truth_status": status,
            "truth_horizon_sessions": horizon,
            "truth_observation_end": None,
            "future_wave_count": None,
            "future_higher_high_confirmations": None,
            "future_final_resolution_status": None,
            "future_successful_supports": None,
            "future_final_support": None,
            "ignition_lead_sessions": None,
            "stock_ignition_to_cycle_return_pct": None,
            "concept_ignition_to_cycle_return_pct": None,
            "concept_future_5d_return_pct": None,
            "future_20d_close_excess_pct": None,
            "future_40d_close_excess_pct": None,
            "future_40d_max_excess_pct": None,
        }
    )
    return row


def _is_main_board_symbol(value: object) -> bool:
    symbol = str(value).strip().upper()
    return (
        symbol.endswith(".SSE")
        and symbol.startswith("60")
        or symbol.endswith(".SZSE")
        and symbol.startswith(("000", "001", "002", "003"))
    )


def _is_current_risk_name(value: object) -> bool:
    name = str(value or "").strip().upper()
    return name.startswith(("ST", "*ST")) or "退" in name


def _mean_boolean(values: Sequence[bool]) -> float | None:
    return float(np.mean(values) * 100.0) if values else None


def _mean_difference(first: pd.Series, second: pd.Series) -> float | None:
    left = pd.to_numeric(first, errors="coerce").dropna()
    right = pd.to_numeric(second, errors="coerce").dropna()
    if left.empty or right.empty:
        return None
    return float(left.mean() - right.mean())


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = sorted(set(columns) - set(frame))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
