"""Matched pre-breakout ignition, breadth and later diffusion research."""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha1

import numpy as np
import pandas as pd


RESEARCH_STATUS = "exploratory_not_frozen"
MEMBERSHIP_EVIDENCE_LEVEL = "current_membership_survivorship_proxy"
PREBREAKOUT_LEADS = (10, 5, 3, 1)
DIFFUSION_FUTURE_DAYS = (3, 5, 10)
PREBREAKOUT_FEATURES = (
    "concept_return_1d_pct",
    "concept_return_3d_pct",
    "concept_return_5d_pct",
    "concept_return_10d_pct",
    "relative_gain_5d_percentile",
    "concept_turnover_expansion",
    "same_day_positive_breadth_pct",
    "positive_breadth_5d_pct",
    "breadth_5d_change_pct_points",
    "ignition_share_5d_pct",
    "leader_return_5d_pct",
    "top3_mean_return_5d_pct",
    "top3_turnover_share_pct",
    "top3_mean_turnover_expansion",
    "top3_positive_gain_concentration_pct",
)


def build_breakout_transition_events(
    concept_features: pd.DataFrame,
) -> pd.DataFrame:
    """Build false-to-true 20-session breakout transitions."""

    required = (
        "sector_id",
        "concept_name",
        "trade_date",
        "anchor_breakout_20",
    )
    frame = _normalized_concept_frame(concept_features, required)
    frame["calendar_position"] = frame.groupby("sector_id", sort=False).cumcount()
    previous = frame.groupby("sector_id", sort=False)["anchor_breakout_20"].shift(
        fill_value=False
    )
    events = frame.loc[
        frame["anchor_breakout_20"].astype(bool) & ~previous.astype(bool),
        [
            "sector_id",
            "concept_name",
            "trade_date",
            "calendar_position",
        ],
    ].rename(columns={"trade_date": "breakout_date"})
    events = events.sort_values(["breakout_date", "sector_id"]).reset_index(drop=True)
    events["event_id"] = events.apply(
        lambda row: _identity_hash(
            "breakout",
            row["sector_id"],
            pd.Timestamp(row["breakout_date"]).date().isoformat(),
        ),
        axis=1,
    )
    events["time_block"] = _chronological_blocks(events["breakout_date"], 5)
    return events[
        [
            "event_id",
            "sector_id",
            "concept_name",
            "breakout_date",
            "calendar_position",
            "time_block",
        ]
    ]


def build_prebreakout_observation_pairs(
    events: pd.DataFrame,
    concept_features: pd.DataFrame,
    *,
    leads: Sequence[int] = PREBREAKOUT_LEADS,
    max_events_per_block: int = 250,
) -> pd.DataFrame:
    """Pair each pre-breakout observation with a clean same-concept control."""

    event_required = (
        "event_id",
        "sector_id",
        "concept_name",
        "breakout_date",
        "calendar_position",
        "time_block",
    )
    _require_columns(events, event_required, "breakout event")
    normalized_leads = tuple(sorted(set(int(value) for value in leads), reverse=True))
    if not normalized_leads or any(value <= 0 for value in normalized_leads):
        raise ValueError("prebreakout leads must be positive")
    if max_events_per_block <= 0:
        raise ValueError("max_events_per_block must be positive")

    feature_required = (
        "sector_id",
        "concept_name",
        "trade_date",
        "anchor_breakout_20",
        "return_1d_pct",
        "return_3d_pct",
        "return_5d_pct",
        "return_10d_pct",
        "relative_gain_5d_percentile",
        "turnover_expansion",
    )
    features = _normalized_concept_frame(concept_features, feature_required)
    features["calendar_position"] = features.groupby("sector_id", sort=False).cumcount()
    event_frame = events.copy()
    event_frame["breakout_date"] = pd.to_datetime(
        event_frame["breakout_date"], errors="raise"
    ).dt.normalize()
    event_frame = _eligible_sampled_events(
        event_frame,
        features,
        maximum_lead=max(normalized_leads),
        max_events_per_block=max_events_per_block,
    )
    if event_frame.empty:
        return pd.DataFrame()

    block_boundaries = _block_boundaries(event_frame)
    transition_positions = {
        str(sector_id): group["calendar_position"].astype(int).to_numpy()
        for sector_id, group in events.groupby("sector_id", sort=False)
    }
    feature_groups = {
        str(sector_id): group.reset_index(drop=True)
        for sector_id, group in features.groupby("sector_id", sort=False)
    }
    used_controls: dict[tuple[str, int], set[int]] = {}
    records: list[dict[str, object]] = []
    for event in event_frame.itertuples(index=False):
        sector_id = str(event.sector_id)
        sector = feature_groups[sector_id]
        transitions = transition_positions.get(sector_id, np.array([], dtype=int))
        for lead_days in normalized_leads:
            positive_position = int(event.calendar_position) - lead_days
            control_position = _matched_control_position(
                sector,
                positive_position=positive_position,
                lead_days=lead_days,
                event_block=str(event.time_block),
                block_boundaries=block_boundaries,
                transition_positions=transitions,
                used_positions=used_controls.setdefault((sector_id, lead_days), set()),
            )
            if control_position is None:
                continue
            pair_id = _identity_hash("pair", event.event_id, lead_days)
            for role, position in (
                ("positive", positive_position),
                ("control", control_position),
            ):
                row = sector.iloc[position]
                records.append(
                    _observation_record(
                        row,
                        event=event,
                        pair_id=pair_id,
                        lead_days=lead_days,
                        sample_role=role,
                        transitions=transitions,
                    )
                )
    return pd.DataFrame.from_records(records).sort_values(
        ["lead_days", "pair_id", "sample_role"]
    ).reset_index(drop=True)


def build_prebreakout_stock_features(stock_bars: pd.DataFrame) -> pd.DataFrame:
    """Build trailing returns, ignition counts and turnover expansion."""

    required = ("vt_symbol", "trade_date", "close_price", "turnover")
    _require_columns(stock_bars, required, "stock bar")
    frame = stock_bars.copy()
    frame["vt_symbol"] = frame["vt_symbol"].astype(str)
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    frame = frame.loc[frame["vt_symbol"].map(_is_main_board_symbol)].copy()
    if frame.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock bar identities must be unique")
    _require_finite_positive(frame["close_price"], "stock close_price")
    _require_finite_non_negative(frame["turnover"], "stock turnover")
    frame = frame.sort_values(["vt_symbol", "trade_date"]).reset_index(drop=True)
    grouped = frame.groupby("vt_symbol", sort=False)
    frame["return_1d_pct"] = (
        grouped["close_price"].pct_change(1, fill_method=None) * 100.0
    )
    frame["return_5d_pct"] = (
        grouped["close_price"].pct_change(5, fill_method=None) * 100.0
    )
    frame["return_previous_5d_pct"] = grouped["close_price"].transform(
        lambda values: (values.shift(5) / values.shift(10) - 1.0) * 100.0
    )
    strong_day = frame["return_1d_pct"].ge(5.0).astype(float)
    frame["strong_day_count_5"] = strong_day.groupby(frame["vt_symbol"]).transform(
        lambda values: values.rolling(5, min_periods=5).sum()
    )
    frame["turnover_mean_5"] = grouped["turnover"].transform(
        lambda values: values.rolling(5, min_periods=5).mean()
    )
    frame["turnover_mean_previous_20"] = grouped["turnover"].transform(
        lambda values: values.shift(5).rolling(20, min_periods=15).mean()
    )
    frame["turnover_expansion"] = (
        frame["turnover_mean_5"] / frame["turnover_mean_previous_20"]
    )
    return frame


def build_prebreakout_member_features(
    observations: pd.DataFrame,
    memberships: pd.DataFrame,
    stock_features: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aggregate causal member ignition, breadth, leader and turnover features."""

    observation_required = (
        "pair_id",
        "event_id",
        "sector_id",
        "lead_days",
        "sample_role",
        "observation_date",
        "time_block",
    )
    membership_required = (
        "sector_id",
        "vt_symbol",
        "stock_name",
        "evidence_level",
    )
    stock_required = (
        "vt_symbol",
        "trade_date",
        "close_price",
        "return_1d_pct",
        "return_5d_pct",
        "return_previous_5d_pct",
        "strong_day_count_5",
        "turnover",
        "turnover_expansion",
    )
    _require_columns(observations, observation_required, "observation")
    members = _validated_memberships(memberships, membership_required)
    _require_columns(stock_features, stock_required, "stock feature")
    stocks = stock_features.copy()
    stocks["trade_date"] = pd.to_datetime(
        stocks["trade_date"], errors="raise"
    ).dt.normalize()
    if stocks.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock feature identities must be unique")

    observation_frame = observations.copy()
    observation_frame["observation_date"] = pd.to_datetime(
        observation_frame["observation_date"], errors="raise"
    ).dt.normalize()
    expanded = observation_frame.merge(
        members,
        on="sector_id",
        how="inner",
        validate="many_to_many",
    ).merge(
        stocks[list(stock_required)],
        left_on=["vt_symbol", "observation_date"],
        right_on=["vt_symbol", "trade_date"],
        how="inner",
        validate="many_to_one",
    )
    expanded = expanded.dropna(
        subset=[
            "return_1d_pct",
            "return_5d_pct",
            "return_previous_5d_pct",
            "strong_day_count_5",
            "turnover",
            "turnover_expansion",
        ]
    ).copy()
    group_columns = ["pair_id", "sample_role"]
    expanded = expanded.sort_values(
        [*group_columns, "return_5d_pct", "vt_symbol"],
        ascending=[True, True, False, True],
    )
    expanded["early_rank"] = expanded.groupby(group_columns, sort=False).cumcount() + 1
    expanded["early_leader"] = expanded["early_rank"].eq(1)
    expanded["early_return_5d_pct"] = expanded["return_5d_pct"]
    expanded["is_top3"] = expanded["early_rank"].le(3)
    expanded["positive_gain_5d"] = expanded["return_5d_pct"].clip(lower=0.0)

    counts = expanded.groupby(group_columns, sort=False)["vt_symbol"].transform(
        "nunique"
    )
    expanded = expanded.loc[counts.ge(3)].copy()
    aggregates = _aggregate_member_features(expanded, group_columns)
    identity_columns = [
        column
        for column in observations.columns
        if column not in aggregates.columns or column in group_columns
    ]
    observation_identity = observations[identity_columns].drop_duplicates(group_columns)
    panel = observation_identity.merge(
        aggregates,
        on=group_columns,
        how="inner",
        validate="one_to_one",
    )
    ledger_columns = [
        "pair_id",
        "sample_role",
        "event_id",
        "sector_id",
        "lead_days",
        "time_block",
        "observation_date",
        "vt_symbol",
        "stock_name",
        "close_price",
        "early_return_5d_pct",
        "early_rank",
        "early_leader",
    ]
    return (
        panel.sort_values(["lead_days", "pair_id", "sample_role"]).reset_index(
            drop=True
        ),
        expanded[ledger_columns]
        .sort_values(["lead_days", "pair_id", "sample_role", "early_rank"])
        .reset_index(drop=True),
    )


def evaluate_prebreakout_features(
    panel: pd.DataFrame,
    *,
    block_count: int = 5,
) -> pd.DataFrame:
    """Compare positive/control features pooled and in chronological blocks."""

    required = (
        "pair_id",
        "lead_days",
        "sample_role",
        "time_block",
        *PREBREAKOUT_FEATURES,
    )
    _require_columns(panel, required, "prebreakout feature panel")
    if block_count <= 0:
        raise ValueError("block_count must be positive")
    records: list[dict[str, object]] = []
    for lead_days, lead_frame in panel.groupby("lead_days", sort=True):
        scopes = ["pooled", *sorted(lead_frame["time_block"].dropna().unique())]
        for scope in scopes:
            scoped = (
                lead_frame
                if scope == "pooled"
                else lead_frame.loc[lead_frame["time_block"].eq(scope)]
            )
            for feature in PREBREAKOUT_FEATURES:
                records.append(
                    {
                        "lead_days": int(lead_days),
                        "feature": feature,
                        "scope": str(scope),
                        **_paired_feature_metrics(scoped, feature),
                    }
                )
    return pd.DataFrame.from_records(records)


def prebreakout_feature_diagnostics(
    metrics: pd.DataFrame,
) -> list[dict[str, object]]:
    """Apply the preregistered AUC and five-block stability label."""

    required = ("lead_days", "feature", "scope", "pairs", "rank_auc")
    _require_columns(metrics, required, "prebreakout feature metric")
    records: list[dict[str, object]] = []
    for (lead_days, feature), group in metrics.groupby(
        ["lead_days", "feature"], sort=True
    ):
        pooled = group.loc[group["scope"].eq("pooled")]
        blocks = group.loc[group["scope"].str.startswith("block_")]
        if len(pooled) != 1:
            continue
        pooled_auc = _number_or_none(pooled.iloc[0]["rank_auc"])
        stable_blocks = int(
            (
                pd.to_numeric(blocks["rank_auc"], errors="coerce").ge(0.55)
                & pd.to_numeric(blocks["pairs"], errors="coerce").ge(30)
            ).sum()
        )
        all_blocks_sufficient = bool(
            blocks["scope"].nunique() == 5
            and pd.to_numeric(blocks["pairs"], errors="coerce").ge(30).all()
        )
        qualified = bool(
            pooled_auc is not None
            and pooled_auc >= 0.60
            and stable_blocks >= 4
            and all_blocks_sufficient
        )
        records.append(
            {
                "lead_days": int(lead_days),
                "feature": str(feature),
                "pooled_pairs": int(pooled.iloc[0]["pairs"]),
                "pooled_rank_auc": pooled_auc,
                "stable_blocks": stable_blocks,
                "all_blocks_sufficient": all_blocks_sufficient,
                "status": (
                    "candidate_for_forward_validation"
                    if qualified
                    else "exploratory_not_selected"
                ),
            }
        )
    return records


def build_prebreakout_diffusion_outcomes(
    observations: pd.DataFrame,
    early_member_ledger: pd.DataFrame,
    memberships: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_calendar: pd.DataFrame,
    *,
    future_days: Sequence[int] = DIFFUSION_FUTURE_DAYS,
) -> pd.DataFrame:
    """Observe the frozen E leader and followers over equal future windows."""

    observation_required = (
        "pair_id",
        "sector_id",
        "lead_days",
        "sample_role",
        "observation_date",
        "observation_position",
        "time_block",
    )
    ledger_required = (
        "pair_id",
        "sample_role",
        "sector_id",
        "lead_days",
        "time_block",
        "observation_date",
        "vt_symbol",
        "early_return_5d_pct",
        "early_rank",
        "early_leader",
    )
    _require_columns(observations, observation_required, "observation")
    _require_columns(early_member_ledger, ledger_required, "early member ledger")
    _validated_memberships(
        memberships,
        ("sector_id", "vt_symbol", "stock_name", "evidence_level"),
    )
    _require_columns(
        stock_bars,
        ("vt_symbol", "trade_date", "close_price"),
        "stock bar",
    )
    horizons = tuple(sorted(set(int(value) for value in future_days)))
    if not horizons or any(value <= 0 for value in horizons):
        raise ValueError("future diffusion days must be positive")

    calendar = _prepared_calendar(concept_calendar)
    observation_frame = observations.copy()
    observation_frame["observation_date"] = pd.to_datetime(
        observation_frame["observation_date"], errors="raise"
    ).dt.normalize()
    ledger = early_member_ledger.copy()
    ledger["observation_date"] = pd.to_datetime(
        ledger["observation_date"], errors="raise"
    ).dt.normalize()
    bars = stock_bars[["vt_symbol", "trade_date", "close_price"]].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.normalize()
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock bar identities must be unique")

    outcome_frames: list[pd.DataFrame] = []
    for horizon in horizons:
        context = observation_frame[list(observation_required)].copy()
        context["future_days"] = horizon
        context["outcome_position"] = (
            context["observation_position"] + context["lead_days"] + horizon
        )
        context = context.merge(
            calendar.rename(
                columns={
                    "calendar_position": "outcome_position",
                    "trade_date": "outcome_date",
                }
            ),
            on=["sector_id", "outcome_position"],
            how="inner",
            validate="many_to_one",
        )
        expanded = context.merge(
            ledger,
            on=[
                "pair_id",
                "sample_role",
                "sector_id",
                "lead_days",
                "time_block",
                "observation_date",
            ],
            how="inner",
            validate="one_to_many",
        )
        expanded = expanded.merge(
            bars.rename(
                columns={
                    "trade_date": "observation_date",
                    "close_price": "observation_close",
                }
            ),
            on=["vt_symbol", "observation_date"],
            how="inner",
            validate="many_to_one",
        ).merge(
            bars.rename(
                columns={
                    "trade_date": "outcome_date",
                    "close_price": "outcome_close",
                }
            ),
            on=["vt_symbol", "outcome_date"],
            how="inner",
            validate="many_to_one",
        )
        expanded["future_return_pct"] = (
            expanded["outcome_close"] / expanded["observation_close"] - 1.0
        ) * 100.0
        outcome_frames.append(_aggregate_diffusion_outcomes(expanded))
    if not outcome_frames:
        return pd.DataFrame()
    return pd.concat(outcome_frames, ignore_index=True).sort_values(
        ["lead_days", "future_days", "pair_id", "sample_role"]
    ).reset_index(drop=True)


def evaluate_prebreakout_diffusion(
    outcomes: pd.DataFrame,
    *,
    block_count: int = 5,
) -> pd.DataFrame:
    """Compare matched positive/control follower diffusion and leader retention."""

    required = (
        "pair_id",
        "lead_days",
        "future_days",
        "sample_role",
        "time_block",
        "early_leader_return_5d_pct",
        "early_leader_retained_top1",
        "early_leader_retained_top3",
        "follower_median_return_pct",
        "follower_positive_breadth_pct",
    )
    _require_columns(outcomes, required, "prebreakout diffusion outcome")
    if block_count <= 0:
        raise ValueError("block_count must be positive")
    records: list[dict[str, object]] = []
    for (lead_days, future_days), group in outcomes.groupby(
        ["lead_days", "future_days"], sort=True
    ):
        scopes = ["pooled", *sorted(group["time_block"].dropna().unique())]
        for scope in scopes:
            scoped = group if scope == "pooled" else group.loc[group["time_block"].eq(scope)]
            records.append(
                {
                    "lead_days": int(lead_days),
                    "future_days": int(future_days),
                    "scope": str(scope),
                    **_diffusion_metrics(scoped),
                }
            )
    return pd.DataFrame.from_records(records)


def _normalized_concept_frame(
    frame: pd.DataFrame,
    required: Sequence[str],
) -> pd.DataFrame:
    _require_columns(frame, required, "concept feature")
    result = frame.copy()
    result["sector_id"] = result["sector_id"].astype(str)
    result["trade_date"] = pd.to_datetime(
        result["trade_date"], errors="raise"
    ).dt.normalize()
    if result.duplicated(["sector_id", "trade_date"]).any():
        raise ValueError("concept feature identities must be unique")
    return result.sort_values(["sector_id", "trade_date"]).reset_index(drop=True)


def _eligible_sampled_events(
    events: pd.DataFrame,
    features: pd.DataFrame,
    *,
    maximum_lead: int,
    max_events_per_block: int,
) -> pd.DataFrame:
    calendar_sizes = features.groupby("sector_id", sort=False).size().to_dict()
    eligible = events.loc[
        events.apply(
            lambda row: int(row["calendar_position"]) >= maximum_lead
            and int(row["calendar_position"]) + 10
            < int(calendar_sizes.get(str(row["sector_id"]), 0)),
            axis=1,
        )
    ].copy()
    selected: list[pd.DataFrame] = []
    for _, block in eligible.sort_values(["breakout_date", "sector_id"]).groupby(
        "time_block", sort=True
    ):
        positions = _evenly_spaced_positions(len(block), max_events_per_block)
        selected.append(block.iloc[positions])
    return pd.concat(selected, ignore_index=True) if selected else eligible.iloc[0:0]


def _matched_control_position(
    sector: pd.DataFrame,
    *,
    positive_position: int,
    lead_days: int,
    event_block: str,
    block_boundaries: Sequence[pd.Timestamp],
    transition_positions: np.ndarray,
    used_positions: set[int],
) -> int | None:
    candidates: list[tuple[int, pd.Timestamp, int]] = []
    for position, row in sector.iterrows():
        if position < 25 or position + lead_days + 10 >= len(sector):
            continue
        if position in used_positions:
            continue
        if _block_for_date(pd.Timestamp(row["trade_date"]), block_boundaries) != event_block:
            continue
        nearest = _nearest_transition_distance(position, transition_positions)
        if nearest <= 10:
            continue
        candidates.append(
            (abs(position - positive_position), pd.Timestamp(row["trade_date"]), position)
        )
    if not candidates:
        return None
    position = min(candidates)[2]
    used_positions.add(position)
    return int(position)


def _observation_record(
    row: pd.Series,
    *,
    event: object,
    pair_id: str,
    lead_days: int,
    sample_role: str,
    transitions: np.ndarray,
) -> dict[str, object]:
    return {
        "pair_id": pair_id,
        "event_id": event.event_id,
        "sector_id": str(event.sector_id),
        "concept_name": str(event.concept_name),
        "breakout_date": pd.Timestamp(event.breakout_date).normalize(),
        "lead_days": lead_days,
        "sample_role": sample_role,
        "observation_date": pd.Timestamp(row["trade_date"]).normalize(),
        "observation_position": int(row["calendar_position"]),
        "time_block": str(event.time_block),
        "nearest_breakout_distance": _nearest_transition_distance(
            int(row["calendar_position"]), transitions
        ),
        "concept_return_1d_pct": row["return_1d_pct"],
        "concept_return_3d_pct": row["return_3d_pct"],
        "concept_return_5d_pct": row["return_5d_pct"],
        "concept_return_10d_pct": row["return_10d_pct"],
        "relative_gain_5d_percentile": row["relative_gain_5d_percentile"],
        "concept_turnover_expansion": row["turnover_expansion"],
    }


def _aggregate_member_features(
    expanded: pd.DataFrame,
    group_columns: Sequence[str],
) -> pd.DataFrame:
    expanded["same_day_positive"] = expanded["return_1d_pct"].gt(0)
    expanded["positive_5d"] = expanded["return_5d_pct"].gt(0)
    expanded["positive_previous_5d"] = expanded["return_previous_5d_pct"].gt(0)
    expanded["ignited_5d"] = expanded["strong_day_count_5"].gt(0)
    base = expanded.groupby(list(group_columns), sort=False).agg(
        member_count=("vt_symbol", "nunique"),
        same_day_positive_breadth_pct=("same_day_positive", "mean"),
        positive_breadth_5d_pct=("positive_5d", "mean"),
        previous_positive_breadth_5d_pct=("positive_previous_5d", "mean"),
        ignition_share_5d_pct=("ignited_5d", "mean"),
        leader_return_5d_pct=("return_5d_pct", "max"),
        total_turnover=("turnover", "sum"),
        total_positive_gain_5d=("positive_gain_5d", "sum"),
    )
    top3 = expanded.loc[expanded["is_top3"]].groupby(list(group_columns), sort=False).agg(
        early_leader_symbol=("vt_symbol", "first"),
        top3_mean_return_5d_pct=("return_5d_pct", "mean"),
        top3_turnover=("turnover", "sum"),
        top3_mean_turnover_expansion=("turnover_expansion", "mean"),
        top3_positive_gain_5d=("positive_gain_5d", "sum"),
    )
    result = base.join(top3, how="inner").reset_index()
    for column in (
        "same_day_positive_breadth_pct",
        "positive_breadth_5d_pct",
        "previous_positive_breadth_5d_pct",
        "ignition_share_5d_pct",
    ):
        result[column] *= 100.0
    result["breadth_5d_change_pct_points"] = (
        result["positive_breadth_5d_pct"]
        - result["previous_positive_breadth_5d_pct"]
    )
    result["top3_turnover_share_pct"] = (
        result["top3_turnover"] / result["total_turnover"].where(result["total_turnover"].gt(0))
    ) * 100.0
    result["top3_positive_gain_concentration_pct"] = (
        result["top3_positive_gain_5d"]
        / result["total_positive_gain_5d"].where(result["total_positive_gain_5d"].gt(0))
    ) * 100.0
    return result.drop(
        columns=[
            "total_turnover",
            "total_positive_gain_5d",
            "top3_turnover",
            "top3_positive_gain_5d",
        ]
    )


def _paired_feature_metrics(frame: pd.DataFrame, feature: str) -> dict[str, object]:
    pairs = _paired_values(frame, feature)
    if pairs.empty:
        return _empty_feature_metrics()
    positive = pairs["positive"].astype(float)
    control = pairs["control"].astype(float)
    differences = positive - control
    direction = positive.gt(control).astype(float) + positive.eq(control).astype(float) * 0.5
    return {
        "pairs": int(len(pairs)),
        "positive_median": float(positive.median()),
        "control_median": float(control.median()),
        "median_paired_difference": float(differences.median()),
        "matched_positive_higher_rate_pct": float(direction.mean() * 100.0),
        "rank_auc": _rank_auc(positive, control),
    }


def _aggregate_diffusion_outcomes(expanded: pd.DataFrame) -> pd.DataFrame:
    group_columns = ["pair_id", "sample_role", "lead_days", "future_days"]
    counts = expanded.groupby(group_columns, sort=False)["vt_symbol"].transform("nunique")
    frame = expanded.loc[counts.ge(3)].copy()
    frame = frame.sort_values(
        [*group_columns, "future_return_pct", "vt_symbol"],
        ascending=[True, True, True, True, False, True],
    )
    frame["future_rank"] = frame.groupby(group_columns, sort=False).cumcount() + 1
    leaders = frame.loc[frame["early_leader"]].copy()
    leaders["early_leader_retained_top1"] = leaders["future_rank"].eq(1)
    leaders["early_leader_retained_top3"] = leaders["future_rank"].le(3)
    leader_summary = leaders.groupby(group_columns, sort=False).agg(
        sector_id=("sector_id", "first"),
        time_block=("time_block", "first"),
        early_leader_symbol=("vt_symbol", "first"),
        early_leader_return_5d_pct=("early_return_5d_pct", "first"),
        early_leader_retained_top1=("early_leader_retained_top1", "first"),
        early_leader_retained_top3=("early_leader_retained_top3", "first"),
    )
    followers = frame.loc[~frame["early_leader"]].copy()
    followers["follower_positive"] = followers["future_return_pct"].gt(0)
    follower_summary = followers.groupby(group_columns, sort=False).agg(
        follower_count=("vt_symbol", "nunique"),
        follower_median_return_pct=("future_return_pct", "median"),
        follower_positive_breadth_pct=("follower_positive", "mean"),
    )
    result = leader_summary.join(follower_summary, how="inner").reset_index()
    result["follower_positive_breadth_pct"] *= 100.0
    return result


def _diffusion_metrics(frame: pd.DataFrame) -> dict[str, object]:
    follower_pairs = _paired_values(frame, "follower_median_return_pct")
    breadth_pairs = _paired_values(frame, "follower_positive_breadth_pct")
    complete_ids = set(follower_pairs.index) & set(breadth_pairs.index)
    follower_pairs = follower_pairs.loc[sorted(complete_ids)]
    breadth_pairs = breadth_pairs.loc[sorted(complete_ids)]
    positive = frame.loc[
        frame["sample_role"].eq("positive") & frame["pair_id"].isin(complete_ids)
    ]
    control = frame.loc[
        frame["sample_role"].eq("control") & frame["pair_id"].isin(complete_ids)
    ]
    return {
        "pairs": len(complete_ids),
        "positive_follower_median_return_pct": _median(
            follower_pairs.get("positive", pd.Series(dtype=float))
        ),
        "control_follower_median_return_pct": _median(
            follower_pairs.get("control", pd.Series(dtype=float))
        ),
        "median_follower_return_difference_pct": _median(
            follower_pairs.get("positive", pd.Series(dtype=float))
            - follower_pairs.get("control", pd.Series(dtype=float))
        ),
        "positive_follower_breadth_pct": _median(
            breadth_pairs.get("positive", pd.Series(dtype=float))
        ),
        "control_follower_breadth_pct": _median(
            breadth_pairs.get("control", pd.Series(dtype=float))
        ),
        "median_follower_breadth_difference_pct_points": _median(
            breadth_pairs.get("positive", pd.Series(dtype=float))
            - breadth_pairs.get("control", pd.Series(dtype=float))
        ),
        "positive_leader_retained_top1_rate_pct": _boolean_rate(
            positive["early_leader_retained_top1"]
        ),
        "control_leader_retained_top1_rate_pct": _boolean_rate(
            control["early_leader_retained_top1"]
        ),
        "positive_leader_retained_top3_rate_pct": _boolean_rate(
            positive["early_leader_retained_top3"]
        ),
        "control_leader_retained_top3_rate_pct": _boolean_rate(
            control["early_leader_retained_top3"]
        ),
        "positive_leader_gain_follower_return_spearman": _spearman(
            positive["early_leader_return_5d_pct"],
            positive["follower_median_return_pct"],
        ),
    }


def _paired_values(frame: pd.DataFrame, value_column: str) -> pd.DataFrame:
    working = frame[["pair_id", "sample_role", value_column]].dropna()
    if working.duplicated(["pair_id", "sample_role"]).any():
        raise ValueError("paired observation identities must be unique")
    pivot = working.pivot(index="pair_id", columns="sample_role", values=value_column)
    required_roles = [role for role in ("positive", "control") if role in pivot]
    if len(required_roles) < 2:
        return pd.DataFrame(columns=["positive", "control"])
    return pivot.dropna(subset=["positive", "control"])


def _rank_auc(positive: pd.Series, control: pd.Series) -> float | None:
    if positive.empty or control.empty:
        return None
    combined = pd.concat(
        [
            pd.DataFrame({"value": positive.to_numpy(), "positive": True}),
            pd.DataFrame({"value": control.to_numpy(), "positive": False}),
        ],
        ignore_index=True,
    )
    ranks = combined["value"].rank(method="average")
    positive_count = int(combined["positive"].sum())
    control_count = len(combined) - positive_count
    rank_sum = float(ranks.loc[combined["positive"]].sum())
    return float(
        (rank_sum - positive_count * (positive_count + 1) / 2)
        / (positive_count * control_count)
    )


def _validated_memberships(
    memberships: pd.DataFrame,
    required: Sequence[str],
) -> pd.DataFrame:
    _require_columns(memberships, required, "membership")
    members = memberships.copy()
    if not members["evidence_level"].eq(MEMBERSHIP_EVIDENCE_LEVEL).all():
        raise ValueError(
            "membership evidence_level must be current_membership_survivorship_proxy"
        )
    members["sector_id"] = members["sector_id"].astype(str)
    members["vt_symbol"] = members["vt_symbol"].astype(str)
    members = members.loc[members["vt_symbol"].map(_is_main_board_symbol)].copy()
    if members.duplicated(["sector_id", "vt_symbol"]).any():
        raise ValueError("membership identities must be unique")
    return members


def _prepared_calendar(concept_calendar: pd.DataFrame) -> pd.DataFrame:
    _require_columns(concept_calendar, ("sector_id", "trade_date"), "concept calendar")
    calendar = concept_calendar[["sector_id", "trade_date"]].copy()
    calendar["sector_id"] = calendar["sector_id"].astype(str)
    calendar["trade_date"] = pd.to_datetime(
        calendar["trade_date"], errors="raise"
    ).dt.normalize()
    if calendar.duplicated(["sector_id", "trade_date"]).any():
        raise ValueError("concept calendar identities must be unique")
    calendar = calendar.sort_values(["sector_id", "trade_date"]).reset_index(drop=True)
    calendar["calendar_position"] = calendar.groupby("sector_id", sort=False).cumcount()
    return calendar


def _nearest_transition_distance(position: int, transitions: np.ndarray) -> int:
    if not len(transitions):
        return 1_000_000
    return int(np.min(np.abs(transitions.astype(int) - int(position))))


def _block_boundaries(events: pd.DataFrame) -> tuple[pd.Timestamp, ...]:
    maxima = (
        events.groupby("time_block", sort=True)["breakout_date"]
        .max()
        .sort_index()
    )
    return tuple(pd.Timestamp(value).normalize() for value in maxima)


def _block_for_date(
    trade_date: pd.Timestamp,
    boundaries: Sequence[pd.Timestamp],
) -> str:
    position = int(np.searchsorted(np.array(boundaries, dtype="datetime64[ns]"), trade_date.to_datetime64()))
    return f"block_{min(position + 1, len(boundaries))}"


def _chronological_blocks(dates: pd.Series, block_count: int) -> pd.Series:
    normalized = pd.to_datetime(dates, errors="raise").dt.normalize()
    unique_dates = np.array(sorted(normalized.unique()))
    if not len(unique_dates):
        return pd.Series(pd.NA, index=dates.index, dtype="string")
    labels: dict[pd.Timestamp, str] = {}
    for index, block in enumerate(
        np.array_split(unique_dates, min(block_count, len(unique_dates))), start=1
    ):
        for value in block:
            labels[pd.Timestamp(value)] = f"block_{index}"
    return normalized.map(labels).astype("string")


def _evenly_spaced_positions(row_count: int, limit: int) -> np.ndarray:
    if row_count <= limit:
        return np.arange(row_count, dtype=int)
    return np.unique(np.linspace(0, row_count - 1, num=limit, dtype=int))


def _identity_hash(*parts: object) -> str:
    value = "|".join(str(part) for part in parts)
    return sha1(value.encode("utf-8")).hexdigest()


def _is_main_board_symbol(vt_symbol: object) -> bool:
    value = str(vt_symbol)
    if value.endswith(".SSE"):
        return value[:6].startswith(("600", "601", "603", "605"))
    if value.endswith(".SZSE"):
        return value[:6].startswith(("000", "001", "002", "003"))
    return False


def _empty_feature_metrics() -> dict[str, object]:
    return {
        "pairs": 0,
        "positive_median": None,
        "control_median": None,
        "median_paired_difference": None,
        "matched_positive_higher_rate_pct": None,
        "rank_auc": None,
    }


def _median(values: pd.Series) -> float | None:
    usable = pd.to_numeric(values, errors="coerce").dropna()
    return float(usable.median()) if not usable.empty else None


def _boolean_rate(values: pd.Series) -> float | None:
    usable = values.dropna()
    return float(usable.astype(bool).mean() * 100.0) if not usable.empty else None


def _spearman(left: pd.Series, right: pd.Series) -> float | None:
    pairs = pd.concat([left, right], axis=1).dropna()
    if (
        len(pairs) < 3
        or pairs.iloc[:, 0].nunique() < 2
        or pairs.iloc[:, 1].nunique() < 2
    ):
        return None
    value = pairs.iloc[:, 0].corr(pairs.iloc[:, 1], method="spearman")
    return float(value) if pd.notna(value) else None


def _number_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = sorted(set(columns) - set(frame))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")


def _require_finite_positive(values: pd.Series, label: str) -> None:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or not np.isfinite(numeric).all() or numeric.le(0).any():
        raise ValueError(f"{label} must be finite and positive")


def _require_finite_non_negative(values: pd.Series, label: str) -> None:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or not np.isfinite(numeric).all() or numeric.lt(0).any():
        raise ValueError(f"{label} must be finite and non-negative")
