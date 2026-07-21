"""Exploratory dynamic concept campaigns and changing leader ranks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha1

import numpy as np
import pandas as pd


RESEARCH_STATUS = "exploratory_not_frozen"
MEMBERSHIP_EVIDENCE_LEVEL = "current_membership_survivorship_proxy"
EXPLORATORY_ANCHOR_MODES = (
    "breakout_20",
    "relative_gain_5d_q80",
    "breakout_relative",
    "breakout_relative_turnover",
)
EXPLORATORY_EXIT_CANDIDATES = (
    (3.0, 1),
    (3.0, 3),
    (5.0, 1),
    (5.0, 3),
    (8.0, 1),
    (8.0, 3),
)
LEADER_MODES = (
    "cumulative_gain",
    "ignition_gain",
    "gain_persistence",
    "gain_persistence_turnover",
)
LEADER_OBSERVATION_DAYS = frozenset((0, 1, 3, 5, 10))
LEADER_DIFFUSION_DAYS = (3, 5, 10)


def build_concept_campaign_features(concept_bars: pd.DataFrame) -> pd.DataFrame:
    """Build trailing concept gain, breakout, strength and turnover features."""

    required = ("sector_id", "trade_date", "close_price", "turnover")
    _require_columns(concept_bars, required, "concept bar")
    frame = concept_bars.copy()
    frame["sector_id"] = frame["sector_id"].astype(str)
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    if "concept_name" not in frame:
        frame["concept_name"] = frame["sector_id"]
    frame["concept_name"] = frame["concept_name"].fillna(frame["sector_id"]).astype(str)
    if frame.duplicated(["sector_id", "trade_date"]).any():
        raise ValueError("concept bar identities must be unique")
    _require_finite_positive(frame["close_price"], "concept close_price")
    _require_finite_non_negative(frame["turnover"], "concept turnover")
    frame = frame.sort_values(["sector_id", "trade_date"]).reset_index(drop=True)

    grouped = frame.groupby("sector_id", sort=False)
    for sessions in (1, 3, 5, 10):
        frame[f"return_{sessions}d_pct"] = (
            grouped["close_price"].pct_change(sessions, fill_method=None) * 100.0
        )
    frame["prior_high_20"] = grouped["close_price"].transform(
        lambda values: values.shift(1).rolling(20, min_periods=20).max()
    )
    frame["relative_gain_5d_percentile"] = frame.groupby(
        "trade_date", sort=False
    )["return_5d_pct"].rank(method="average", pct=True)
    frame["turnover_mean_5"] = grouped["turnover"].transform(
        lambda values: values.rolling(5, min_periods=5).mean()
    )
    frame["turnover_mean_prev20"] = grouped["turnover"].transform(
        lambda values: values.shift(5).rolling(20, min_periods=15).mean()
    )
    frame["turnover_expansion"] = (
        frame["turnover_mean_5"] / frame["turnover_mean_prev20"]
    )

    breakout = frame["close_price"].gt(frame["prior_high_20"])
    relative = frame["return_5d_pct"].gt(0.0) & frame[
        "relative_gain_5d_percentile"
    ].ge(0.80)
    frame["anchor_breakout_20"] = breakout.fillna(False).astype(bool)
    frame["anchor_relative_gain_5d_q80"] = relative.fillna(False).astype(bool)
    frame["anchor_breakout_relative"] = (breakout & relative).fillna(False).astype(bool)
    frame["anchor_breakout_relative_turnover"] = (
        breakout & relative & frame["turnover_expansion"].ge(1.20)
    ).fillna(False).astype(bool)
    return frame


def build_exploratory_campaigns(
    concept_features: pd.DataFrame,
    *,
    anchor_modes: Sequence[str] = EXPLORATORY_ANCHOR_MODES,
    exit_candidates: Sequence[tuple[float, int]] = EXPLORATORY_EXIT_CANDIDATES,
    retained_path_days: frozenset[int] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build one non-overlapping campaign ledger for every candidate definition."""

    modes = tuple(anchor_modes)
    exits = tuple(exit_candidates)
    _validate_campaign_definitions(modes, exits)
    required = (
        "sector_id",
        "concept_name",
        "trade_date",
        "close_price",
        *(f"anchor_{mode}" for mode in modes),
    )
    _require_columns(concept_features, required, "concept feature")
    features = concept_features.copy()
    features["sector_id"] = features["sector_id"].astype(str)
    features["trade_date"] = pd.to_datetime(
        features["trade_date"], errors="raise"
    ).dt.normalize()
    if features.duplicated(["sector_id", "trade_date"]).any():
        raise ValueError("concept feature identities must be unique")
    _require_finite_positive(features["close_price"], "concept close_price")
    features = features.sort_values(["sector_id", "trade_date"])

    campaign_records: list[dict[str, object]] = []
    path_records: list[dict[str, object]] = []
    for _, sector_frame in features.groupby("sector_id", sort=True):
        sector = sector_frame.reset_index(drop=True)
        for mode in modes:
            triggers = sector[f"anchor_{mode}"].astype(bool).to_numpy()
            for drawdown_pct, confirm_sessions in exits:
                campaigns, paths = _scan_campaign_definition(
                    sector,
                    triggers=triggers,
                    anchor_mode=mode,
                    drawdown_pct=float(drawdown_pct),
                    confirm_sessions=int(confirm_sessions),
                )
                campaign_records.extend(campaigns)
                path_records.extend(
                    _retained_campaign_paths(paths, retained_path_days)
                )

    campaigns = pd.DataFrame.from_records(campaign_records)
    paths = pd.DataFrame.from_records(path_records)
    if not campaigns.empty:
        campaigns = campaigns.sort_values(
            [
                "anchor_mode",
                "exit_drawdown_pct",
                "exit_confirm_sessions",
                "anchor_date",
                "sector_id",
            ]
        ).reset_index(drop=True)
    if not paths.empty:
        paths = paths.sort_values(
            ["campaign_id", "trade_date"]
        ).reset_index(drop=True)
    return campaigns, paths


def _retained_campaign_paths(
    paths: Sequence[dict[str, object]],
    retained_path_days: frozenset[int] | None,
) -> list[dict[str, object]]:
    if retained_path_days is None:
        return list(paths)
    if any(day < 0 for day in retained_path_days):
        raise ValueError("retained path days must be non-negative")
    return [
        row
        for row in paths
        if int(row["campaign_day"]) in retained_path_days
        or bool(row["is_endpoint"])
    ]


def evaluate_exploratory_campaigns(
    campaigns: pd.DataFrame,
    campaign_path: pd.DataFrame,
    *,
    block_count: int = 5,
) -> pd.DataFrame:
    """Describe every start/exit candidate pooled and by chronological block."""

    del campaign_path
    required = (
        "campaign_id",
        "anchor_mode",
        "exit_drawdown_pct",
        "exit_confirm_sessions",
        "anchor_date",
        "right_censored",
        "campaign_days",
        "peak_gain_pct",
        "terminal_gain_pct",
        "days_to_peak",
        "reached_5pct",
        "reached_10pct",
        "higher_high_within_10_after_end",
        "post_end_further_drawdown_pct",
    )
    _require_columns(campaigns, required, "campaign")
    if block_count <= 0:
        raise ValueError("block_count must be positive")
    frame = campaigns.copy()
    frame["anchor_date"] = pd.to_datetime(
        frame["anchor_date"], errors="raise"
    ).dt.normalize()
    frame["time_block"] = _chronological_blocks(frame["anchor_date"], block_count)

    dimensions = [
        "anchor_mode",
        "exit_drawdown_pct",
        "exit_confirm_sessions",
    ]
    records: list[dict[str, object]] = []
    for keys, candidate in frame.groupby(dimensions, sort=True):
        base = dict(zip(dimensions, keys, strict=True))
        records.append({**base, "scope": "pooled", **_campaign_metrics(candidate)})
        for block, block_frame in candidate.groupby("time_block", sort=True):
            records.append(
                {**base, "scope": str(block), **_campaign_metrics(block_frame)}
            )
    return pd.DataFrame.from_records(records)


def campaign_candidate_diagnostics(
    metrics: pd.DataFrame,
) -> list[dict[str, object]]:
    """Label unstable and Pareto-dominated definitions without freezing one."""

    required = (
        "anchor_mode",
        "exit_drawdown_pct",
        "exit_confirm_sessions",
        "scope",
        "campaigns",
        "reach_5pct_rate",
        "median_peak_gain_pct",
        "higher_high_within_10_after_end_rate",
    )
    _require_columns(metrics, required, "campaign metric")
    pooled = metrics.loc[metrics["scope"].eq("pooled")].copy()
    blocks = metrics.loc[metrics["scope"].str.startswith("block_")].copy()
    identity = ["anchor_mode", "exit_drawdown_pct", "exit_confirm_sessions"]
    block_reach_medians = blocks.groupby(
        ["scope", "exit_drawdown_pct", "exit_confirm_sessions"],
        sort=False,
    )["reach_5pct_rate"].median()
    records: list[dict[str, object]] = []
    for _, row in pooled.iterrows():
        candidate_mask = np.logical_and.reduce(
            [blocks[column].eq(row[column]) for column in identity]
        )
        candidate_blocks = blocks.loc[candidate_mask]
        dominated = _is_dominated_candidate(row, pooled)
        candidate_thresholds = pd.MultiIndex.from_frame(
            candidate_blocks[
                ["scope", "exit_drawdown_pct", "exit_confirm_sessions"]
            ]
        ).map(block_reach_medians)
        stable_blocks = int(
            (
                candidate_blocks["reach_5pct_rate"].to_numpy()
                >= candidate_thresholds.to_numpy()
            ).sum()
        )
        records.append(
            {
                **{column: _json_scalar(row[column]) for column in identity},
                "campaigns": int(row["campaigns"]),
                "pareto_dominated": dominated,
                "blocks_at_or_above_median_reach": stable_blocks,
                "block_count": int(candidate_blocks["scope"].nunique()),
                "status": (
                    "candidate_for_future_validation"
                    if not dominated and stable_blocks >= 3 and row["campaigns"] >= 100
                    else "exploratory_not_selected"
                ),
            }
        )
    return records


def select_dynamic_leader_campaign_path(
    campaigns: pd.DataFrame,
    campaign_path: pd.DataFrame,
    *,
    max_episodes_per_mode: int = 250,
) -> pd.DataFrame:
    """Select an evenly spaced, outcome-neutral leader-study episode sample."""

    if max_episodes_per_mode <= 0:
        raise ValueError("max_episodes_per_mode must be positive")
    _require_columns(
        campaigns,
        ("campaign_id", "anchor_mode", "sector_id", "anchor_date", "campaign_days"),
        "campaign",
    )
    _require_columns(campaign_path, ("campaign_id", "trade_date", "campaign_day"), "campaign path")
    eligible = campaigns.loc[campaigns["campaign_days"].ge(11)].copy()
    eligible["episode_key"] = _episode_keys(eligible)
    eligible = eligible.sort_values(["anchor_mode", "anchor_date", "sector_id"])
    eligible = eligible.drop_duplicates(["anchor_mode", "episode_key"])

    selected_ids: list[str] = []
    for _, mode_frame in eligible.groupby("anchor_mode", sort=True):
        positions = _evenly_spaced_positions(len(mode_frame), max_episodes_per_mode)
        selected_ids.extend(mode_frame.iloc[positions]["campaign_id"].astype(str))
    selected = campaign_path.loc[
        campaign_path["campaign_id"].astype(str).isin(selected_ids)
    ].copy()
    return selected.sort_values(["campaign_id", "trade_date"]).reset_index(drop=True)


def build_dynamic_leader_ledger(
    campaign_path: pd.DataFrame,
    memberships: pd.DataFrame,
    stock_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate causal member ranks on key campaign observations and endpoints."""

    path_required = (
        "campaign_id",
        "anchor_mode",
        "sector_id",
        "concept_name",
        "anchor_date",
        "trade_date",
        "campaign_day",
        "cumulative_gain_pct",
        "is_endpoint",
    )
    membership_required = (
        "sector_id",
        "vt_symbol",
        "stock_name",
        "evidence_level",
    )
    bar_required = ("vt_symbol", "trade_date", "close_price", "turnover")
    _require_columns(campaign_path, path_required, "campaign path")
    _require_columns(memberships, membership_required, "membership")
    _require_columns(stock_bars, bar_required, "stock bar")
    if campaign_path.empty:
        return pd.DataFrame()

    observations = _prepare_leader_observations(campaign_path)
    members = _prepare_memberships(memberships)
    bars = _prepare_stock_bars(stock_bars)
    expanded = observations.merge(members, on="sector_id", how="inner", validate="many_to_many")
    stock_observations = bars[
        [
            "vt_symbol",
            "trade_date",
            "close_price",
            "turnover",
            "turnover_expansion",
        ]
    ].rename(
        columns={
            "close_price": "stock_close_price",
            "turnover": "stock_turnover",
        }
    )
    expanded = expanded.merge(
        stock_observations,
        on=["vt_symbol", "trade_date"],
        how="inner",
        validate="many_to_one",
    )
    anchor_closes = bars[["vt_symbol", "trade_date", "previous_close"]].rename(
        columns={"trade_date": "anchor_date", "previous_close": "anchor_close"}
    )
    expanded = expanded.merge(
        anchor_closes,
        on=["vt_symbol", "anchor_date"],
        how="inner",
        validate="many_to_one",
    )
    expanded = expanded.loc[expanded["anchor_close"].gt(0)].copy()
    expanded["member_cumulative_gain_pct"] = (
        expanded["stock_close_price"] / expanded["anchor_close"] - 1.0
    ) * 100.0
    expanded["stock_excess_concept_pct"] = (
        expanded["member_cumulative_gain_pct"] - expanded["cumulative_gain_pct"]
    )
    totals = expanded.groupby(["episode_id", "trade_date"], sort=False)[
        "stock_turnover"
    ].transform("sum")
    expanded["member_turnover_share"] = expanded[
        "stock_turnover"
    ] / totals.where(totals.gt(0))
    expanded = expanded.sort_values(
        ["episode_id", "vt_symbol", "trade_date"]
    ).reset_index(drop=True)
    expanded = _add_ignition_features(expanded)
    return _rank_dynamic_leaders(expanded)


def build_realized_campaign_leader_proxy(
    dynamic_ledger: pd.DataFrame,
) -> pd.DataFrame:
    """Build descriptive endpoint ranks after causal ledgers are complete."""

    required = (
        "episode_id",
        "anchor_mode",
        "sector_id",
        "anchor_date",
        "trade_date",
        "vt_symbol",
        "stock_excess_concept_pct",
        "member_cumulative_gain_pct",
        "cumulative_gain_top3",
    )
    _require_columns(dynamic_ledger, required, "dynamic leader ledger")
    frame = dynamic_ledger.copy().sort_values(
        ["episode_id", "vt_symbol", "trade_date"]
    )
    previous_high = frame.groupby(["episode_id", "vt_symbol"], sort=False)[
        "member_cumulative_gain_pct"
    ].transform(lambda values: values.shift(1).cummax())
    frame["sets_observed_record_high"] = previous_high.isna() | frame[
        "member_cumulative_gain_pct"
    ].gt(previous_high)
    grouped = frame.groupby(["episode_id", "vt_symbol"], sort=True)
    summary = grouped.agg(
        anchor_mode=("anchor_mode", "first"),
        sector_id=("sector_id", "first"),
        anchor_date=("anchor_date", "first"),
        realized_top3_observations=("cumulative_gain_top3", "sum"),
        repeated_record_highs=("sets_observed_record_high", "sum"),
        maximum_concept_excess_pct=("stock_excess_concept_pct", "max"),
        terminal_concept_excess_pct=("stock_excess_concept_pct", "last"),
    ).reset_index()
    summary = summary.sort_values(
        [
            "episode_id",
            "repeated_record_highs",
            "maximum_concept_excess_pct",
            "terminal_concept_excess_pct",
            "vt_symbol",
        ],
        ascending=[True, False, False, False, True],
    )
    summary["realized_rank"] = summary.groupby("episode_id", sort=False).cumcount() + 1
    summary["realized_top3"] = summary["realized_rank"].le(3)
    return summary.reset_index(drop=True)


def evaluate_dynamic_leader_modes(
    dynamic_ledger: pd.DataFrame,
    realized_proxy: pd.DataFrame,
    *,
    block_count: int = 5,
) -> pd.DataFrame:
    """Compare dynamic Top3 identity on common episodes and date blocks."""

    if block_count <= 0:
        raise ValueError("block_count must be positive")
    required = (
        "episode_id",
        "anchor_mode",
        "anchor_date",
        "campaign_day",
        "vt_symbol",
        *(f"{mode}_rank" for mode in LEADER_MODES),
    )
    _require_columns(dynamic_ledger, required, "dynamic leader ledger")
    _require_columns(
        realized_proxy,
        ("episode_id", "vt_symbol", "realized_rank", "realized_top3"),
        "realized leader proxy",
    )
    frame = dynamic_ledger.copy()
    frame["campaign_day_bucket"] = frame["campaign_day"].map(_leader_day_bucket)
    frame["time_block"] = _chronological_blocks(frame["anchor_date"], block_count)
    truth = realized_proxy[["episode_id", "vt_symbol", "realized_rank", "realized_top3"]]
    frame = frame.merge(
        truth,
        on=["episode_id", "vt_symbol"],
        how="inner",
        validate="many_to_one",
    )
    records: list[dict[str, object]] = []
    scopes = ["pooled", *sorted(frame["time_block"].dropna().unique())]
    for anchor_mode, mode_frame in frame.groupby("anchor_mode", sort=True):
        for day_bucket, day_frame in mode_frame.groupby(
            "campaign_day_bucket", sort=True
        ):
            for scope in scopes:
                scoped = (
                    day_frame
                    if scope == "pooled"
                    else day_frame.loc[day_frame["time_block"].eq(scope)]
                )
                if scoped.empty:
                    continue
                complete_ids = _complete_identity_episodes(scoped)
                common = scoped.loc[scoped["episode_id"].isin(complete_ids)]
                for leader_mode in LEADER_MODES:
                    records.append(
                        {
                            "anchor_mode": anchor_mode,
                            "campaign_day_bucket": day_bucket,
                            "scope": scope,
                            "leader_mode": leader_mode,
                            **_leader_identity_metrics(common, leader_mode),
                        }
                    )
    return pd.DataFrame.from_records(records)


def evaluate_leader_diffusion(
    dynamic_ledger: pd.DataFrame,
    *,
    block_count: int = 5,
    future_days: Sequence[int] = LEADER_DIFFUSION_DAYS,
) -> pd.DataFrame:
    """Measure whether a D leader precedes later gains among other members."""

    required = (
        "episode_id",
        "anchor_mode",
        "anchor_date",
        "trade_date",
        "campaign_day",
        "vt_symbol",
        "member_cumulative_gain_pct",
        *(f"{mode}_rank" for mode in LEADER_MODES),
    )
    _require_columns(dynamic_ledger, required, "dynamic leader ledger")
    if block_count <= 0:
        raise ValueError("block_count must be positive")
    horizons = tuple(sorted(set(int(day) for day in future_days)))
    if not horizons or any(day <= 0 for day in horizons):
        raise ValueError("future diffusion days must be positive")

    frame = dynamic_ledger.copy()
    frame["anchor_date"] = pd.to_datetime(
        frame["anchor_date"], errors="raise"
    ).dt.normalize()
    frame["time_block"] = _chronological_blocks(frame["anchor_date"], block_count)
    records: list[dict[str, object]] = []
    for anchor_mode, anchor_frame in frame.groupby("anchor_mode", sort=True):
        base = anchor_frame.loc[anchor_frame["campaign_day"].eq(0)]
        for future_day in horizons:
            future = anchor_frame.loc[anchor_frame["campaign_day"].eq(future_day)]
            for leader_mode in LEADER_MODES:
                episodes = _leader_diffusion_episode_rows(
                    base,
                    future,
                    leader_mode=leader_mode,
                )
                if episodes.empty:
                    continue
                scopes = ["pooled", *sorted(episodes["time_block"].unique())]
                for scope in scopes:
                    scoped = (
                        episodes
                        if scope == "pooled"
                        else episodes.loc[episodes["time_block"].eq(scope)]
                    )
                    records.append(
                        {
                            "anchor_mode": anchor_mode,
                            "future_day": future_day,
                            "scope": scope,
                            "leader_mode": leader_mode,
                            **_leader_diffusion_metrics(scoped),
                        }
                    )
    return pd.DataFrame.from_records(records)


def _leader_diffusion_episode_rows(
    base: pd.DataFrame,
    future: pd.DataFrame,
    *,
    leader_mode: str,
) -> pd.DataFrame:
    rank_column = f"{leader_mode}_rank"
    rows: list[dict[str, object]] = []
    common_episodes = sorted(
        set(base["episode_id"].astype(str))
        & set(future["episode_id"].astype(str))
    )
    for episode_id in common_episodes:
        base_episode = base.loc[base["episode_id"].astype(str).eq(episode_id)]
        future_episode = future.loc[
            future["episode_id"].astype(str).eq(episode_id)
        ]
        leader_rows = base_episode.loc[base_episode[rank_column].eq(1)]
        if len(leader_rows) != 1:
            continue
        common_symbols = set(base_episode["vt_symbol"].astype(str)) & set(
            future_episode["vt_symbol"].astype(str)
        )
        leader_symbol = str(leader_rows.iloc[0]["vt_symbol"])
        follower_symbols = common_symbols - {leader_symbol}
        if len(follower_symbols) < 2 or leader_symbol not in common_symbols:
            continue
        base_followers = base_episode.loc[
            base_episode["vt_symbol"].astype(str).isin(follower_symbols)
        ].set_index("vt_symbol")["member_cumulative_gain_pct"]
        future_followers = future_episode.loc[
            future_episode["vt_symbol"].astype(str).isin(follower_symbols)
        ].set_index("vt_symbol")["member_cumulative_gain_pct"]
        follower_deltas = future_followers - base_followers
        future_leader = future_episode.loc[
            future_episode["vt_symbol"].astype(str).eq(leader_symbol)
        ]
        if len(future_leader) != 1:
            continue
        rows.append(
            {
                "episode_id": episode_id,
                "time_block": str(base_episode.iloc[0]["time_block"]),
                "leader_gain_pct": float(
                    leader_rows.iloc[0]["member_cumulative_gain_pct"]
                ),
                "follower_gain_delta_pct": float(follower_deltas.median()),
                "positive_breadth_delta_pct_points": float(
                    (
                        future_followers.gt(0).mean()
                        - base_followers.gt(0).mean()
                    )
                    * 100.0
                ),
                "leader_retained_top1": bool(
                    future_leader.iloc[0][rank_column] == 1
                ),
                "leader_retained_top3": bool(
                    future_leader.iloc[0][rank_column] <= 3
                ),
            }
        )
    return pd.DataFrame.from_records(rows)


def _leader_diffusion_metrics(frame: pd.DataFrame) -> dict[str, object]:
    return {
        "qualified_campaigns": int(len(frame)),
        "median_leader_gain_at_anchor_pct": _median(frame["leader_gain_pct"]),
        "median_follower_gain_delta_pct": _median(
            frame["follower_gain_delta_pct"]
        ),
        "median_positive_breadth_delta_pct_points": _median(
            frame["positive_breadth_delta_pct_points"]
        ),
        "leader_retained_top1_rate_pct": _boolean_rate(
            frame["leader_retained_top1"]
        ),
        "leader_retained_top3_rate_pct": _boolean_rate(
            frame["leader_retained_top3"]
        ),
        "leader_gain_follower_delta_spearman": _spearman(
            frame["leader_gain_pct"], frame["follower_gain_delta_pct"]
        ),
    }


def _scan_campaign_definition(
    sector: pd.DataFrame,
    *,
    triggers: np.ndarray,
    anchor_mode: str,
    drawdown_pct: float,
    confirm_sessions: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    campaigns: list[dict[str, object]] = []
    paths: list[dict[str, object]] = []
    active: dict[str, object] | None = None
    active_paths: list[dict[str, object]] = []

    for position, row in sector.iterrows():
        if active is None:
            if not bool(triggers[position]):
                continue
            active = _new_active_campaign(
                row,
                position=position,
                anchor_mode=anchor_mode,
                drawdown_pct=drawdown_pct,
                confirm_sessions=confirm_sessions,
            )
            active_paths = []
        path_row = _update_active_campaign(active, row, position=position)
        active_paths.append(path_row)
        if int(active["below_count"]) < confirm_sessions:
            continue
        campaign, finalized_paths = _finalize_campaign(
            active,
            active_paths,
            sector,
            end_position=position,
            right_censored=False,
        )
        campaigns.append(campaign)
        paths.extend(finalized_paths)
        active = None
        active_paths = []

    if active is not None:
        end_position = len(sector) - 1
        campaign, finalized_paths = _finalize_campaign(
            active,
            active_paths,
            sector,
            end_position=end_position,
            right_censored=True,
        )
        campaigns.append(campaign)
        paths.extend(finalized_paths)
    return campaigns, paths


def _new_active_campaign(
    row: pd.Series,
    *,
    position: int,
    anchor_mode: str,
    drawdown_pct: float,
    confirm_sessions: int,
) -> dict[str, object]:
    anchor_date = pd.Timestamp(row["trade_date"]).normalize()
    sector_id = str(row["sector_id"])
    campaign_key = (
        f"{anchor_mode}|{drawdown_pct:.1f}|{confirm_sessions}|"
        f"{sector_id}|{anchor_date.date().isoformat()}"
    )
    return {
        "campaign_id": sha1(campaign_key.encode("utf-8")).hexdigest(),
        "anchor_mode": anchor_mode,
        "exit_drawdown_pct": drawdown_pct,
        "exit_confirm_sessions": confirm_sessions,
        "sector_id": sector_id,
        "concept_name": str(row["concept_name"]),
        "anchor_date": anchor_date,
        "anchor_price": float(row["close_price"]),
        "anchor_position": position,
        "peak_price": float(row["close_price"]),
        "peak_position": position,
        "peak_date": anchor_date,
        "below_count": 0,
    }


def _update_active_campaign(
    active: dict[str, object],
    row: pd.Series,
    *,
    position: int,
) -> dict[str, object]:
    close_price = float(row["close_price"])
    if close_price > float(active["peak_price"]):
        active["peak_price"] = close_price
        active["peak_position"] = position
        active["peak_date"] = pd.Timestamp(row["trade_date"]).normalize()
    drawdown_pct = (close_price / float(active["peak_price"]) - 1.0) * 100.0
    if drawdown_pct <= -float(active["exit_drawdown_pct"]):
        active["below_count"] = int(active["below_count"]) + 1
    else:
        active["below_count"] = 0
    anchor_price = float(active["anchor_price"])
    return {
        "campaign_id": active["campaign_id"],
        "anchor_mode": active["anchor_mode"],
        "exit_drawdown_pct": active["exit_drawdown_pct"],
        "exit_confirm_sessions": active["exit_confirm_sessions"],
        "sector_id": active["sector_id"],
        "concept_name": active["concept_name"],
        "anchor_date": active["anchor_date"],
        "trade_date": pd.Timestamp(row["trade_date"]).normalize(),
        "campaign_day": position - int(active["anchor_position"]),
        "close_price": close_price,
        "cumulative_gain_pct": (close_price / anchor_price - 1.0) * 100.0,
        "running_high_price": float(active["peak_price"]),
        "running_high_gain_pct": (
            float(active["peak_price"]) / anchor_price - 1.0
        )
        * 100.0,
        "drawdown_from_high_pct": drawdown_pct,
        "is_endpoint": False,
    }


def _finalize_campaign(
    active: Mapping[str, object],
    active_paths: list[dict[str, object]],
    sector: pd.DataFrame,
    *,
    end_position: int,
    right_censored: bool,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    active_paths[-1]["is_endpoint"] = True
    terminal = active_paths[-1]
    post_end = _post_end_observation(
        sector,
        end_position=end_position,
        peak_price=float(active["peak_price"]),
        end_price=float(terminal["close_price"]),
        right_censored=right_censored,
    )
    campaign = {
        "campaign_id": active["campaign_id"],
        "anchor_mode": active["anchor_mode"],
        "exit_drawdown_pct": active["exit_drawdown_pct"],
        "exit_confirm_sessions": active["exit_confirm_sessions"],
        "sector_id": active["sector_id"],
        "concept_name": active["concept_name"],
        "anchor_date": active["anchor_date"],
        "anchor_price": active["anchor_price"],
        "end_date": terminal["trade_date"],
        "end_reason": (
            "right_censored"
            if right_censored
            else "confirmed_running_peak_drawdown"
        ),
        "right_censored": right_censored,
        "campaign_days": len(active_paths),
        "running_high_price": active["peak_price"],
        "running_high_date": active["peak_date"],
        "peak_gain_pct": active_paths[-1]["running_high_gain_pct"],
        "terminal_gain_pct": terminal["cumulative_gain_pct"],
        "days_to_peak": int(active["peak_position"]) - int(active["anchor_position"]),
        "reached_5pct": float(active_paths[-1]["running_high_gain_pct"]) >= 5.0,
        "reached_10pct": float(active_paths[-1]["running_high_gain_pct"]) >= 10.0,
        **post_end,
    }
    return campaign, active_paths


def _post_end_observation(
    sector: pd.DataFrame,
    *,
    end_position: int,
    peak_price: float,
    end_price: float,
    right_censored: bool,
) -> dict[str, object]:
    future = sector.iloc[end_position + 1 : end_position + 11]
    if right_censored or len(future) < 10:
        return {
            "higher_high_within_10_after_end": None,
            "post_end_further_drawdown_pct": None,
        }
    future_closes = future["close_price"].astype(float)
    return {
        "higher_high_within_10_after_end": bool(future_closes.max() > peak_price),
        "post_end_further_drawdown_pct": float(
            (future_closes.min() / end_price - 1.0) * 100.0
        ),
    }


def _campaign_metrics(frame: pd.DataFrame) -> dict[str, object]:
    completed = frame.loc[~frame["right_censored"].astype(bool)]
    return {
        "campaigns": int(len(frame)),
        "completed_campaigns": int(len(completed)),
        "right_censored_campaigns": int(frame["right_censored"].astype(bool).sum()),
        "median_campaign_days": _median(frame["campaign_days"]),
        "median_peak_gain_pct": _median(frame["peak_gain_pct"]),
        "p75_peak_gain_pct": _quantile(frame["peak_gain_pct"], 0.75),
        "median_terminal_gain_pct": _median(frame["terminal_gain_pct"]),
        "reach_5pct_rate": _boolean_rate(frame["reached_5pct"]),
        "reach_10pct_rate": _boolean_rate(frame["reached_10pct"]),
        "median_days_to_peak": _median(frame["days_to_peak"]),
        "higher_high_within_10_after_end_rate": _boolean_rate(
            frame["higher_high_within_10_after_end"]
        ),
        "median_post_end_further_drawdown_pct": _median(
            frame["post_end_further_drawdown_pct"]
        ),
    }


def _prepare_leader_observations(campaign_path: pd.DataFrame) -> pd.DataFrame:
    observations = campaign_path.copy()
    for column in ("anchor_date", "trade_date"):
        observations[column] = pd.to_datetime(
            observations[column], errors="raise"
        ).dt.normalize()
    observations = observations.loc[
        observations["campaign_day"].isin(LEADER_OBSERVATION_DAYS)
        | observations["is_endpoint"].astype(bool)
    ].copy()
    observations["episode_id"] = _episode_keys(observations)
    identity = ["episode_id", "trade_date"]
    consistency = observations.groupby(identity, sort=False).agg(
        concept_gain_values=("cumulative_gain_pct", "nunique"),
        campaign_day_values=("campaign_day", "nunique"),
    )
    if consistency[["concept_gain_values", "campaign_day_values"]].gt(1).any().any():
        raise ValueError("duplicate campaign observations disagree")
    return observations.sort_values(identity).drop_duplicates(identity).reset_index(
        drop=True
    )


def _prepare_memberships(memberships: pd.DataFrame) -> pd.DataFrame:
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


def _prepare_stock_bars(stock_bars: pd.DataFrame) -> pd.DataFrame:
    bars = stock_bars.copy()
    bars["vt_symbol"] = bars["vt_symbol"].astype(str)
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.normalize()
    bars = bars.loc[bars["vt_symbol"].map(_is_main_board_symbol)].copy()
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock bar identities must be unique")
    _require_finite_positive(bars["close_price"], "stock close_price")
    _require_finite_non_negative(bars["turnover"], "stock turnover")
    bars = bars.sort_values(["vt_symbol", "trade_date"]).reset_index(drop=True)
    grouped = bars.groupby("vt_symbol", sort=False)
    bars["previous_close"] = grouped["close_price"].shift(1)
    turnover_5 = grouped["turnover"].transform(
        lambda values: values.rolling(5, min_periods=5).mean()
    )
    turnover_prev20 = grouped["turnover"].transform(
        lambda values: values.shift(5).rolling(20, min_periods=15).mean()
    )
    bars["turnover_expansion"] = turnover_5 / turnover_prev20
    return bars


def _add_ignition_features(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    ignition_dates = result["trade_date"].where(
        result["member_cumulative_gain_pct"].ge(5.0)
    )
    result["first_observed_ignition_date"] = ignition_dates.groupby(
        [result["episode_id"], result["vt_symbol"]]
    ).transform("min")
    anchor_dates = pd.to_datetime(result["anchor_date"])
    result["first_observed_ignition_day"] = (
        result["first_observed_ignition_date"] - anchor_dates
    ).dt.days
    return result


def _rank_dynamic_leaders(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.sort_values(
        ["episode_id", "trade_date", "vt_symbol"]
    ).reset_index(drop=True)
    group_columns = ["episode_id", "trade_date"]
    result = _rank_mode(
        result,
        mode="cumulative_gain",
        order=("member_cumulative_gain_pct", "vt_symbol"),
        ascending=(False, True),
    )
    result["cumulative_gain_rank"] = result["cumulative_gain_rank"].astype(int)
    result["cumulative_gain_top3"] = result["cumulative_gain_rank"].le(3)
    result["top3_observations_so_far"] = (
        result.sort_values(["episode_id", "vt_symbol", "trade_date"])
        .groupby(["episode_id", "vt_symbol"], sort=False)["cumulative_gain_top3"]
        .cumsum()
        .reindex(result.index)
        .astype(int)
    )
    result["ignition_sort_missing"] = result["first_observed_ignition_date"].isna()
    result = _rank_mode(
        result,
        mode="ignition_gain",
        order=(
            "ignition_sort_missing",
            "first_observed_ignition_date",
            "member_cumulative_gain_pct",
            "vt_symbol",
        ),
        ascending=(True, True, False, True),
    )
    result = _rank_mode(
        result,
        mode="gain_persistence",
        order=(
            "top3_observations_so_far",
            "member_cumulative_gain_pct",
            "vt_symbol",
        ),
        ascending=(False, False, True),
    )
    percentile_columns = []
    for source in (
        "member_cumulative_gain_pct",
        "top3_observations_so_far",
        "turnover_expansion",
    ):
        column = f"{source}_percentile"
        result[column] = result.groupby(group_columns, sort=False)[source].rank(
            method="average", pct=True, na_option="bottom"
        )
        percentile_columns.append(column)
    result["gain_persistence_turnover_score"] = result[percentile_columns].mean(
        axis=1
    )
    result = _rank_mode(
        result,
        mode="gain_persistence_turnover",
        order=(
            "gain_persistence_turnover_score",
            "member_cumulative_gain_pct",
            "vt_symbol",
        ),
        ascending=(False, False, True),
    )
    for mode in LEADER_MODES:
        result[f"{mode}_top3"] = result[f"{mode}_rank"].le(3)
    return result.sort_values(
        ["episode_id", "trade_date", "cumulative_gain_rank"]
    ).reset_index(drop=True)


def _rank_mode(
    frame: pd.DataFrame,
    *,
    mode: str,
    order: Sequence[str],
    ascending: Sequence[bool],
) -> pd.DataFrame:
    identity = ["episode_id", "trade_date"]
    ranked = frame.sort_values([*identity, *order], ascending=[True, True, *ascending])
    ranked[f"{mode}_rank"] = ranked.groupby(identity, sort=False).cumcount() + 1
    return ranked.sort_index()


def _complete_identity_episodes(frame: pd.DataFrame) -> set[str]:
    counts = frame.groupby("episode_id", sort=False).agg(
        candidates=("vt_symbol", "nunique"),
        truth_top1=("realized_rank", lambda values: int(values.eq(1).sum())),
        truth_top3=("realized_top3", "sum"),
    )
    return set(
        counts.loc[
            counts["candidates"].ge(3)
            & counts["truth_top1"].eq(1)
            & counts["truth_top3"].ge(3)
        ].index.astype(str)
    )


def _leader_identity_metrics(
    frame: pd.DataFrame,
    leader_mode: str,
) -> dict[str, object]:
    rank_column = f"{leader_mode}_rank"
    episode_rows: list[dict[str, float]] = []
    for _, episode in frame.groupby("episode_id", sort=False):
        predicted_top1 = set(episode.loc[episode[rank_column].eq(1), "vt_symbol"])
        predicted_top3 = set(episode.loc[episode[rank_column].le(3), "vt_symbol"])
        truth_top1 = set(episode.loc[episode["realized_rank"].eq(1), "vt_symbol"])
        truth_top3 = set(episode.loc[episode["realized_top3"].astype(bool), "vt_symbol"])
        episode_rows.append(
            {
                "top1_exact": float(predicted_top1 == truth_top1),
                "top3_capture": float(bool(predicted_top3 & truth_top1)),
                "top3_overlap": len(predicted_top3 & truth_top3) / 3.0,
            }
        )
    return {
        "qualified_campaigns": len(episode_rows),
        "top1_exact_rate_pct": _mean_metric(episode_rows, "top1_exact"),
        "top3_capture_realized_top1_rate_pct": _mean_metric(
            episode_rows, "top3_capture"
        ),
        "mean_realized_top3_overlap_pct": _mean_metric(
            episode_rows, "top3_overlap"
        ),
    }


def _validate_campaign_definitions(
    modes: Sequence[str], exits: Sequence[tuple[float, int]]
) -> None:
    unknown = sorted(set(modes) - set(EXPLORATORY_ANCHOR_MODES))
    if unknown:
        raise ValueError(f"unknown anchor modes: {unknown}")
    if not modes or not exits:
        raise ValueError("anchor modes and exit candidates must be non-empty")
    for drawdown_pct, confirm_sessions in exits:
        if not np.isfinite(drawdown_pct) or drawdown_pct <= 0:
            raise ValueError("exit drawdown must be positive")
        if confirm_sessions <= 0:
            raise ValueError("exit confirmation sessions must be positive")


def _is_dominated_candidate(row: pd.Series, pooled: pd.DataFrame) -> bool:
    comparable = pooled.loc[
        pooled.index.to_series().ne(row.name)
        & pooled["exit_drawdown_pct"].eq(row["exit_drawdown_pct"])
        & pooled["exit_confirm_sessions"].eq(row["exit_confirm_sessions"])
    ]
    return bool(
        (
            comparable["reach_5pct_rate"].ge(row["reach_5pct_rate"])
            & comparable["median_peak_gain_pct"].ge(row["median_peak_gain_pct"])
            & comparable["higher_high_within_10_after_end_rate"].le(
                row["higher_high_within_10_after_end_rate"]
            )
            & (
                comparable["reach_5pct_rate"].gt(row["reach_5pct_rate"])
                | comparable["median_peak_gain_pct"].gt(row["median_peak_gain_pct"])
                | comparable["higher_high_within_10_after_end_rate"].lt(
                    row["higher_high_within_10_after_end_rate"]
                )
            )
        ).any()
    )


def _chronological_blocks(dates: pd.Series, block_count: int) -> pd.Series:
    normalized = pd.to_datetime(dates, errors="raise").dt.normalize()
    unique_dates = np.array(sorted(normalized.unique()))
    if not len(unique_dates):
        return pd.Series(pd.NA, index=dates.index, dtype="string")
    actual_blocks = min(block_count, len(unique_dates))
    labels: dict[pd.Timestamp, str] = {}
    for index, date_block in enumerate(np.array_split(unique_dates, actual_blocks), start=1):
        for value in date_block:
            labels[pd.Timestamp(value)] = f"block_{index}"
    return normalized.map(labels).astype("string")


def _episode_keys(frame: pd.DataFrame) -> pd.Series:
    anchor_dates = pd.to_datetime(frame["anchor_date"], errors="raise").dt.strftime(
        "%Y-%m-%d"
    )
    raw = (
        frame["anchor_mode"].astype(str)
        + "|"
        + frame["sector_id"].astype(str)
        + "|"
        + anchor_dates
    )
    return raw.map(lambda value: sha1(value.encode("utf-8")).hexdigest())


def _evenly_spaced_positions(row_count: int, limit: int) -> np.ndarray:
    if row_count <= limit:
        return np.arange(row_count, dtype=int)
    return np.unique(np.linspace(0, row_count - 1, num=limit, dtype=int))


def _leader_day_bucket(value: object) -> str:
    day = int(value)
    return f"D+{day}" if day else "D"


def _is_main_board_symbol(vt_symbol: object) -> bool:
    value = str(vt_symbol)
    if value.endswith(".SSE"):
        return value[:6].startswith(("600", "601", "603", "605"))
    if value.endswith(".SZSE"):
        return value[:6].startswith(("000", "001", "002", "003"))
    return False


def _boolean_rate(values: pd.Series) -> float | None:
    usable = values.dropna()
    if usable.empty:
        return None
    return float(usable.astype(bool).mean() * 100.0)


def _median(values: pd.Series) -> float | None:
    usable = pd.to_numeric(values, errors="coerce").dropna()
    return float(usable.median()) if not usable.empty else None


def _quantile(values: pd.Series, quantile: float) -> float | None:
    usable = pd.to_numeric(values, errors="coerce").dropna()
    return float(usable.quantile(quantile)) if not usable.empty else None


def _mean_metric(records: Sequence[Mapping[str, float]], key: str) -> float | None:
    if not records:
        return None
    return float(np.mean([record[key] for record in records]) * 100.0)


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


def _json_scalar(value: object) -> object:
    return value.item() if isinstance(value, np.generic) else value


def _require_columns(
    frame: pd.DataFrame, columns: Sequence[str], label: str
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
