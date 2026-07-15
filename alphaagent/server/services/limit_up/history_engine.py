"""Point-in-time daily replay engine for main-board limit-up entry routes."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from typing import Mapping, Sequence

import pandas as pd

from alphaagent.server.services.limit_up import scheduled_execution
from alphaagent.server.services.limit_up.dynamic_exit import attach_replay_exit_decisions
from alphaagent.server.services.limit_up.lane_features import (
    attach_limit_gene_features,
    first_reseal_time,
    path_prefix_features,
    price_path_to_return_path,
)
from alphaagent.server.services.limit_up.lane_repository import (
    EventIndex,
    FinancialIndex,
    financial_risk_as_of,
    financial_snapshot_as_of,
)
from alphaagent.server.services.limit_up.lane_research import (
    BOARD_LANES,
    select_daily_lane_portfolio,
)
from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION

ENTRY_MODES = ("auction", "sweep", "tail", "next_auction")
ROUND_TRIP_COST_RATE = 0.0031
MAIN_BOARD_DAILY_LIMIT_THRESHOLD = 9.2
MAX_REGULAR_DAILY_MOVE = 11.5


@dataclass(frozen=True)
class AnalogStats:
    sample_count: int
    effective_sample_count: int
    smoothed_win_rate: float | None
    average_return_pct: float | None
    hard_loss_rate: float | None
    touch_rate: float | None
    seal_rate: float | None
    seal_after_touch_rate: float | None
    confidence: str


@dataclass
class _Accumulator:
    sample_count: int = 0
    return_count: int = 0
    win_count: int = 0
    hard_loss_count: int = 0
    touch_count: int = 0
    seal_count: int = 0
    return_sum: float = 0.0

    def add(self, candidate: Mapping[str, object]) -> None:
        outcome = candidate.get("outcome")
        outcome = outcome if isinstance(outcome, Mapping) else {}
        self.sample_count += 1
        self.touch_count += int(bool(outcome.get("touched")))
        self.seal_count += int(bool(outcome.get("sealed")))
        if not _candidate_filled(candidate):
            return
        value = _number(outcome.get("next_open_return_pct"))
        if value is None:
            return
        self.return_count += 1
        self.return_sum += value
        self.win_count += int(value > 0)
        self.hard_loss_count += int(value <= -5)


def build_daily_feature_frame(
    rows: Sequence[Mapping[str, object]] | pd.DataFrame,
) -> pd.DataFrame:
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame([dict(row) for row in rows])
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    numeric_columns = (
        "open_price",
        "close_price",
        "high_price",
        "low_price",
        "volume",
        "turnover",
        "turnover_rate",
        "change_pct",
    )
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame.get(column), errors="coerce")
    frame = frame.dropna(subset=["vt_symbol", "trade_date", "open_price", "close_price"]).sort_values(
        ["vt_symbol", "trade_date"],
        kind="stable",
    )
    grouped = frame.groupby("vt_symbol", sort=False)
    frame["prev_trade_date"] = grouped["trade_date"].shift(1)
    frame["prev_close"] = grouped["close_price"].shift(1)
    missing_change = frame["change_pct"].isna() & frame["prev_close"].gt(0)
    frame.loc[missing_change, "change_pct"] = (
        frame.loc[missing_change, "close_price"] / frame.loc[missing_change, "prev_close"] - 1
    ) * 100

    global_dates = sorted(frame["trade_date"].dropna().unique())
    prior_global = {global_dates[index]: global_dates[index - 1] for index in range(1, len(global_dates))}
    next_global = {global_dates[index]: global_dates[index + 1] for index in range(len(global_dates) - 1)}
    frame["expected_prev_trade_date"] = frame["trade_date"].map(prior_global)
    frame["adjacent_prev"] = frame["prev_trade_date"].eq(frame["expected_prev_trade_date"])

    frame["high_change_pct"] = (frame["high_price"] / frame["prev_close"] - 1) * 100
    frame["sealed"] = frame["change_pct"].between(
        MAIN_BOARD_DAILY_LIMIT_THRESHOLD,
        MAX_REGULAR_DAILY_MOVE,
    )
    frame["touched"] = frame["high_change_pct"].between(
        MAIN_BOARD_DAILY_LIMIT_THRESHOLD,
        MAX_REGULAR_DAILY_MOVE,
    )
    run_break = (~frame["sealed"]) | (~frame["adjacent_prev"])
    run_id = run_break.groupby(frame["vt_symbol"], sort=False).cumsum()
    frame["current_streak"] = (
        frame["sealed"].astype(int).groupby([frame["vt_symbol"], run_id], sort=False).cumsum()
    )
    prior_streak = frame.groupby("vt_symbol", sort=False)["current_streak"].shift(1).fillna(0)
    frame["prior_streak"] = prior_streak.where(frame["adjacent_prev"], 0).astype(int)
    frame["prior_break_streak"] = (
        frame.groupby("vt_symbol", sort=False)["prior_streak"].shift(1).fillna(0).astype(int)
    )
    frame["board_level"] = frame["prior_streak"] + 1

    grouped = frame.groupby("vt_symbol", sort=False)
    frame["prior_change_pct"] = grouped["change_pct"].shift(1)
    prior_open = grouped["open_price"].shift(1)
    prior_high = grouped["high_price"].shift(1)
    prior_low = grouped["low_price"].shift(1)
    prior_previous_close = grouped["close_price"].shift(2)
    frame["prior_open_gap_pct"] = (prior_open / prior_previous_close - 1) * 100
    frame["prior_low_change_pct"] = (prior_low / prior_previous_close - 1) * 100
    frame["prior_amplitude_pct"] = (prior_high / prior_low - 1) * 100
    frame["prior_turnover_rate"] = grouped["turnover_rate"].shift(1)
    frame["prior_return_5d_pct"] = (grouped["close_price"].shift(1) / grouped["close_price"].shift(6) - 1) * 100
    frame["prior_return_20d_pct"] = (grouped["close_price"].shift(1) / grouped["close_price"].shift(21) - 1) * 100
    prior_turnover = grouped["turnover"].shift(1)
    prior_amount_base = grouped["turnover"].transform(
        lambda series: series.shift(2).rolling(5, min_periods=3).mean()
    )
    frame["prior_amount_ratio_5d"] = prior_turnover / prior_amount_base
    if "industry_name" not in frame:
        if "industry" in frame:
            frame["industry_name"] = frame["industry"]
        else:
            frame["industry_name"] = "未分类"
    elif "industry" in frame:
        frame["industry_name"] = frame["industry_name"].fillna(frame["industry"])
    frame["industry_name"] = frame["industry_name"].fillna("未分类")
    if "industry_id" not in frame:
        frame["industry_id"] = frame["industry_name"]
    frame["industry_id"] = frame["industry_id"].fillna("UNCLASSIFIED").astype(str)
    frame = _attach_prior_industry_features(frame, next_global)

    leadership_groups = frame.groupby(["trade_date", "industry_id"], sort=False, observed=True)
    return_rank = leadership_groups["prior_return_5d_pct"].rank(pct=True).fillna(0.5)
    change_rank = leadership_groups["prior_change_pct"].rank(pct=True).fillna(0.5)
    amount_rank = leadership_groups["prior_amount_ratio_5d"].rank(pct=True).fillna(0.5)
    frame["prior_industry_leadership_score"] = (
        return_rank * 45 + change_rank * 25 + amount_rank * 30
    )
    leadership_groups = frame.groupby(["trade_date", "industry_id"], sort=False, observed=True)
    frame["prior_industry_leader_rank"] = leadership_groups[
        "prior_industry_leadership_score"
    ].rank(method="min", ascending=False)
    frame["prior_industry_stock_count"] = leadership_groups["vt_symbol"].transform("count")
    frame["auction_gap_pct"] = (frame["open_price"] / frame["prev_close"] - 1) * 100
    frame["limit_price"] = frame["prev_close"].map(_limit_price)

    frame = frame.sort_values(["vt_symbol", "trade_date"], kind="stable")
    grouped = frame.groupby("vt_symbol", sort=False)
    frame["next_trade_date"] = grouped["trade_date"].shift(-1)
    frame["next_open_price"] = grouped["open_price"].shift(-1)
    frame["next_close_price"] = grouped["close_price"].shift(-1)
    frame["expected_next_trade_date"] = frame["trade_date"].map(next_global)
    adjacent_next = frame["next_trade_date"].eq(frame["expected_next_trade_date"])
    frame.loc[~adjacent_next, ["next_trade_date", "next_open_price", "next_close_price"]] = pd.NA

    frame["market_first_board"] = (frame["prior_streak"].eq(0) & frame["sealed"]).astype(int)
    frame["market_one_board_base"] = frame["prior_streak"].eq(1).astype(int)
    frame["market_one_to_two"] = (frame["prior_streak"].eq(1) & frame["sealed"]).astype(int)
    frame["market_two_board_base"] = frame["prior_streak"].eq(2).astype(int)
    frame["market_two_to_three"] = (frame["prior_streak"].eq(2) & frame["sealed"]).astype(int)
    market = frame.groupby("trade_date", sort=True).agg(
        advancing_rate=("change_pct", lambda values: float((values > 0).mean())),
        sealed_count=("sealed", "sum"),
        touched_count=("touched", "sum"),
        max_board=("current_streak", "max"),
        first_board_count=("market_first_board", "sum"),
        one_board_base=("market_one_board_base", "sum"),
        one_to_two_count=("market_one_to_two", "sum"),
        two_board_base=("market_two_board_base", "sum"),
        two_to_three_count=("market_two_to_three", "sum"),
    )
    market["failed_count"] = market["touched_count"] - market["sealed_count"]
    market["failed_rate"] = market["failed_count"] / market["touched_count"].replace(0, pd.NA)
    market["one_to_two_rate"] = market["one_to_two_count"] / market["one_board_base"].replace(0, pd.NA)
    market["two_to_three_rate"] = market["two_to_three_count"] / market["two_board_base"].replace(0, pd.NA)
    market_by_date = market.to_dict("index")
    prior_market = frame["expected_prev_trade_date"].map(market_by_date)
    frame["prior_market_advancing_rate"] = prior_market.map(
        lambda item: _mapping_number(item, "advancing_rate")
    )
    frame["prior_market_sealed_count"] = prior_market.map(
        lambda item: _mapping_number(item, "sealed_count")
    )
    frame["prior_market_failed_rate"] = prior_market.map(
        lambda item: _mapping_number(item, "failed_rate")
    )
    frame["prior_market_max_board"] = prior_market.map(
        lambda item: _mapping_number(item, "max_board")
    )
    frame["prior_market_first_board_count"] = prior_market.map(
        lambda item: _mapping_number(item, "first_board_count")
    )
    frame["prior_market_one_to_two_rate"] = prior_market.map(
        lambda item: _mapping_number(item, "one_to_two_rate")
    )
    frame["prior_market_two_to_three_rate"] = prior_market.map(
        lambda item: _mapping_number(item, "two_to_three_rate")
    )
    frame["prior_market_phase"] = frame["prior_market_advancing_rate"].map(_market_phase)
    return attach_limit_gene_features(frame).reset_index(drop=True)


def _attach_prior_industry_features(
    frame: pd.DataFrame,
    next_global: Mapping[object, object],
) -> pd.DataFrame:
    industry_daily = (
        frame.groupby(["trade_date", "industry_id", "industry_name"], sort=True, observed=True)
        .agg(
            industry_stock_count=("vt_symbol", "count"),
            industry_change_pct=("change_pct", "mean"),
            industry_advancing_rate=("change_pct", lambda values: float((values > 0).mean())),
            industry_turnover=("turnover", "sum"),
            industry_sealed_count=("sealed", "sum"),
        )
        .reset_index()
        .sort_values(["industry_id", "trade_date"], kind="stable")
    )
    grouped = industry_daily.groupby("industry_id", sort=False, observed=True)
    turnover_base = grouped["industry_turnover"].transform(
        lambda series: series.shift(1).rolling(5, min_periods=3).mean()
    )
    industry_daily["industry_turnover_ratio_5d"] = industry_daily["industry_turnover"] / turnover_base
    industry_daily["industry_return_5d_pct"] = grouped["industry_change_pct"].transform(
        lambda series: series.rolling(5, min_periods=3).sum()
    )
    industry_daily["industry_sealed_rate"] = (
        industry_daily["industry_sealed_count"]
        / industry_daily["industry_stock_count"].replace(0, pd.NA)
    )
    date_groups = industry_daily.groupby("trade_date", sort=False, observed=True)
    momentum_rank = date_groups["industry_return_5d_pct"].rank(pct=True).fillna(0.5)
    breadth_rank = date_groups["industry_advancing_rate"].rank(pct=True).fillna(0.5)
    turnover_rank = date_groups["industry_turnover_ratio_5d"].rank(pct=True).fillna(0.5)
    sealed_rank = date_groups["industry_sealed_rate"].rank(pct=True).fillna(0.5)
    industry_daily["industry_heat_score"] = (
        momentum_rank * 35 + breadth_rank * 25 + turnover_rank * 20 + sealed_rank * 20
    )
    industry_daily["industry_heat_rank"] = date_groups["industry_heat_score"].rank(
        method="min",
        ascending=False,
    )
    industry_daily["industry_count"] = date_groups["industry_id"].transform("count")
    industry_daily["trade_date"] = industry_daily["trade_date"].map(next_global)
    prior = industry_daily.dropna(subset=["trade_date"]).rename(
        columns={
            "industry_change_pct": "prior_industry_change_pct",
            "industry_advancing_rate": "prior_industry_advancing_rate",
            "industry_turnover_ratio_5d": "prior_industry_turnover_ratio_5d",
            "industry_return_5d_pct": "prior_industry_return_5d_pct",
            "industry_sealed_count": "prior_industry_sealed_count",
            "industry_sealed_rate": "prior_industry_sealed_rate",
            "industry_heat_score": "prior_industry_heat_score",
            "industry_heat_rank": "prior_industry_heat_rank",
            "industry_count": "prior_industry_count",
        }
    )
    columns = [
        "trade_date",
        "industry_id",
        "prior_industry_change_pct",
        "prior_industry_advancing_rate",
        "prior_industry_turnover_ratio_5d",
        "prior_industry_return_5d_pct",
        "prior_industry_sealed_count",
        "prior_industry_sealed_rate",
        "prior_industry_heat_score",
        "prior_industry_heat_rank",
        "prior_industry_count",
    ]
    return frame.merge(
        prior[columns],
        on=["trade_date", "industry_id"],
        how="left",
        sort=False,
    )


def route_candidates_for_date(
    frame: pd.DataFrame,
    trade_date: date,
    *,
    total_cost_rate: float = ROUND_TRIP_COST_RATE,
) -> dict[str, list[dict[str, object]]]:
    if frame.empty:
        return {mode: [] for mode in ENTRY_MODES}
    timestamp = pd.Timestamp(trade_date)
    day = frame[frame["trade_date"].eq(timestamp)]
    return _route_candidates_from_day(
        day,
        total_cost_rate=total_cost_rate,
    )


def _route_candidates_from_day(
    day: pd.DataFrame,
    *,
    total_cost_rate: float,
) -> dict[str, list[dict[str, object]]]:
    if day.empty:
        return {mode: [] for mode in ENTRY_MODES}
    valid = day[
        day["prev_close"].gt(0)
        & day["open_price"].gt(0)
        & day["auction_gap_pct"].between(1.0, 7.0)
    ]
    first_board = valid[valid["prior_streak"].eq(0)]
    next_board = valid[valid["prior_streak"].isin((1, 2))]
    auction = [
        _candidate_payload(row, "auction", 1, total_cost_rate=total_cost_rate)
        for _, row in first_board.iterrows()
    ]
    sweep = [
        _candidate_payload(row, "sweep", 1, total_cost_rate=total_cost_rate)
        for _, row in first_board.iterrows()
    ]
    tail = [
        _candidate_payload(row, "tail", 1, total_cost_rate=total_cost_rate)
        for _, row in first_board.iterrows()
    ]
    next_auction = [
        _candidate_payload(
            row,
            "next_auction",
            int(row["prior_streak"]) + 1,
            total_cost_rate=total_cost_rate,
        )
        for _, row in next_board.iterrows()
    ]
    return {
        "auction": auction,
        "sweep": sweep,
        "tail": tail,
        "next_auction": next_auction,
    }


def build_history_replays(
    rows: Sequence[Mapping[str, object]] | pd.DataFrame,
    *,
    commission_rate: float = 0.0003,
    stamp_tax_rate: float = 0.0005,
    slippage_bps: float = 10.0,
    warmup_days: int = 120,
    holdout_days: int = 120,
    min_analogs: int = 60,
    top_n: int = 5,
    reliable_start: date | None = None,
    reliable_end: date | None = None,
    event_evidence: EventIndex | None = None,
    financial_index: FinancialIndex | None = None,
) -> list[dict[str, object]]:
    total_cost_rate = commission_rate * 2 + stamp_tax_rate + slippage_bps * 2 / 10_000
    frame = rows.copy() if isinstance(rows, pd.DataFrame) and "prev_close" in rows.columns else build_daily_feature_frame(rows)
    if frame.empty:
        return []
    dates = [item.date() for item in sorted(frame["trade_date"].dropna().unique())]
    if reliable_start is not None:
        dates = [item for item in dates if item >= reliable_start]
    if reliable_end is not None:
        dates = [item for item in dates if item <= reliable_end]
    accumulators: dict[tuple[object, ...], _Accumulator] = defaultdict(_Accumulator)
    pending: dict[str, list[dict[str, object]]] = defaultdict(list)
    replays: list[dict[str, object]] = []
    holdout_start = max(len(dates) - max(holdout_days, 0), max(warmup_days, 0))
    day_groups = frame.groupby("trade_date", sort=False)

    event_evidence = event_evidence or {}
    financial_index = financial_index or {}
    for index, current_date in enumerate(dates):
        current_text = current_date.isoformat()
        if index < warmup_days:
            phase = "warmup"
        elif holdout_days > 0 and index >= holdout_start:
            phase = "locked_holdout"
        else:
            phase = "expanding_oos"

        matured_dates = [key for key in pending if key < current_text]
        update_analogs = phase != "locked_holdout" or index == holdout_start
        for matured_date in sorted(matured_dates):
            for sample in pending.pop(matured_date):
                if update_analogs:
                    _add_analog_sample(accumulators, sample)

        day_frame = day_groups.get_group(pd.Timestamp(current_date))
        raw_lanes = _route_candidates_from_day(
            day_frame,
            total_cost_rate=total_cost_rate,
        )
        selected_lanes: dict[str, list[dict[str, object]]] = {}
        candidate_counts: dict[str, int] = {}
        for entry_mode in ENTRY_MODES:
            raw_candidates = raw_lanes[entry_mode]
            candidate_counts[entry_mode] = len(raw_candidates)
            ranked: list[dict[str, object]] = []
            for candidate in raw_candidates:
                analog = _resolve_analog(accumulators, candidate, min_analogs=min_analogs)
                enriched = {
                    **candidate,
                    "analog": asdict(analog),
                    "score": _candidate_score(candidate, analog),
                    "validation_phase": phase,
                    "favorable_factors": _favorable_factors(candidate, analog),
                    "risk_factors": _risk_factors(candidate, analog),
                }
                enriched["action"] = _history_action(enriched, phase, min_analogs=min_analogs)
                ranked.append(enriched)
            ranked.sort(
                key=lambda item: (
                    float(item.get("score") or -1e9),
                    str(item.get("vt_symbol") or ""),
                ),
                reverse=True,
            )
            selected_lanes[entry_mode] = [
                {**candidate, "rank": rank}
                for rank, candidate in enumerate(ranked[:top_n], start=1)
            ]

        market_context = _day_market_context_from_day(day_frame)
        board_candidates = _board_lane_candidates_from_day(
            day_frame,
            current_date,
            event_evidence=event_evidence,
            financial_index=financial_index,
            total_cost_rate=total_cost_rate,
        )
        lane_portfolio = select_daily_lane_portfolio(board_candidates)
        board_lanes = {
            lane: [
                {**candidate, "validation_phase": phase}
                for candidate in lane_portfolio["lanes"][lane]
            ]
            for lane in BOARD_LANES
        }
        board_candidate_pool = {
            lane: [
                {**candidate, "validation_phase": phase}
                for candidate in lane_portfolio["candidate_pool"][lane]
            ]
            for lane in BOARD_LANES
        }
        selected_keys = {
            (str(candidate.get("lane") or ""), str(candidate.get("vt_symbol") or ""))
            for candidate in lane_portfolio["selected"]
        }
        selected_candidates = [
            candidate
            for lane in BOARD_LANES
            for candidate in board_lanes[lane]
            if (lane, str(candidate.get("vt_symbol") or "")) in selected_keys
        ]
        day_path_count = sum(
            bool(candidate.get("path_prefix")) for candidate in board_candidates
        )
        replays.append(
            {
                "trade_date": current_text,
                "strategy_version": HISTORY_STRATEGY_VERSION,
                "source_mode": "daily_point_in_time",
                "validation_phase": phase,
                "known_at": f"{current_text}T09:25:00+08:00",
                "market_context": market_context,
                "candidate_counts": candidate_counts,
                "lanes": selected_lanes,
                "board_candidate_counts": {
                    lane: sum(
                        str(candidate.get("lane") or "") == lane
                        for candidate in board_candidates
                    )
                    for lane in BOARD_LANES
                },
                "board_lanes": board_lanes,
                "board_candidate_pool": board_candidate_pool,
                "lane_portfolio": {
                    **lane_portfolio,
                    "lanes": board_lanes,
                    "candidate_pool": board_candidate_pool,
                    "selected": selected_candidates,
                },
                "data_quality": {
                    "feature_cutoff": "D_OPEN_AND_D_MINUS_1_CLOSE",
                    "history_membership_mode": "current_universe_survivorship_risk",
                    "industry_membership_mode": "current_mid_level_industry_proxy",
                    "industry_membership_survivorship_risk": True,
                    "has_tick": False,
                    "has_l2": False,
                    "strict_point_in_time_numeric_features": True,
                    "strict_point_in_time_membership": False,
                    "intraday_path_candidate_count": day_path_count,
                    "intraday_path_mode": (
                        "three_minute_prefix" if day_path_count else "unavailable"
                    ),
                    "financial_asof_enforced": True,
                },
            }
        )

        for candidates in raw_lanes.values():
            for candidate in candidates:
                result_date = str(candidate.get("result_date") or "")
                if result_date:
                    pending[result_date].append(candidate)
    return attach_replay_exit_decisions(replays)


def build_analog_index(
    replays: Sequence[Mapping[str, object]],
    *,
    result_before: date,
) -> dict[tuple[object, ...], _Accumulator]:
    """Index only outcomes that were fully known before a new signal date."""

    accumulators: dict[tuple[object, ...], _Accumulator] = defaultdict(_Accumulator)
    cutoff = result_before.isoformat()
    for replay in replays:
        lanes = replay.get("lanes")
        lanes = lanes if isinstance(lanes, Mapping) else {}
        for rows in lanes.values():
            if not isinstance(rows, list):
                continue
            for raw_candidate in rows:
                if not isinstance(raw_candidate, Mapping):
                    continue
                result_date = _date_text(raw_candidate.get("result_date"))
                if result_date is None or result_date >= cutoff:
                    continue
                _add_analog_sample(accumulators, raw_candidate)
    return dict(accumulators)


def resolve_analog(
    accumulators: Mapping[tuple[object, ...], _Accumulator],
    candidate: Mapping[str, object],
    *,
    min_analogs: int = 60,
) -> dict[str, object]:
    """Resolve the same hierarchical analog evidence used by historical replay."""

    return asdict(_resolve_analog(accumulators, candidate, min_analogs=min_analogs))


def _add_analog_sample(
    accumulators: dict[tuple[object, ...], _Accumulator],
    candidate: Mapping[str, object],
) -> None:
    for key in _analog_keys(candidate):
        accumulators[key].add(candidate)


def _resolve_analog(
    accumulators: Mapping[tuple[object, ...], _Accumulator],
    candidate: Mapping[str, object],
    *,
    min_analogs: int,
) -> AnalogStats:
    keys = _analog_keys(candidate)
    available = [(key, accumulators.get(key)) for key in keys]
    available = [(key, value) for key, value in available if value is not None]
    chosen = next(
        (value for _, value in available if value.return_count >= min_analogs),
        None,
    )
    if chosen is None and available:
        chosen = max((value for _, value in available), key=lambda item: item.return_count)
    baseline = accumulators.get(keys[-2]) or accumulators.get(keys[-1])
    if chosen is None or chosen.return_count <= 0:
        return AnalogStats(0, 0, None, None, None, None, None, None, "insufficient")
    baseline = baseline if baseline is not None and baseline.return_count > 0 else chosen
    prior_strength = min(40, baseline.return_count)
    base_win = baseline.win_count / baseline.return_count
    base_return = baseline.return_sum / baseline.return_count
    base_hard_loss = baseline.hard_loss_count / baseline.return_count
    denominator = chosen.return_count + prior_strength
    win_rate = (chosen.win_count + base_win * prior_strength) / denominator * 100
    average_return = (chosen.return_sum + base_return * prior_strength) / denominator
    hard_loss_rate = (chosen.hard_loss_count + base_hard_loss * prior_strength) / denominator * 100
    if chosen.return_count >= 300:
        confidence = "high"
    elif chosen.return_count >= 120:
        confidence = "medium"
    elif chosen.return_count >= min_analogs:
        confidence = "low"
    else:
        confidence = "insufficient"
    return AnalogStats(
        sample_count=chosen.sample_count,
        effective_sample_count=chosen.return_count,
        smoothed_win_rate=round(win_rate, 4),
        average_return_pct=round(average_return, 4),
        hard_loss_rate=round(hard_loss_rate, 4),
        touch_rate=round(chosen.touch_count / chosen.sample_count * 100, 4) if chosen.sample_count else None,
        seal_rate=round(chosen.seal_count / chosen.sample_count * 100, 4) if chosen.sample_count else None,
        seal_after_touch_rate=(
            round(chosen.seal_count / chosen.touch_count * 100, 4)
            if chosen.touch_count
            else None
        ),
        confidence=confidence,
    )


def _analog_keys(candidate: Mapping[str, object]) -> list[tuple[object, ...]]:
    known = candidate.get("known_at_signal")
    known = known if isinstance(known, Mapping) else {}
    entry_mode = str(candidate.get("entry_mode") or "")
    target_board = int(candidate.get("target_board") or 1)
    gap = _gap_bucket(known.get("auction_gap_pct"))
    prior_return = _prior_return_bucket(known.get("prior_change_pct"))
    turnover = _turnover_bucket(known.get("prior_turnover_rate"))
    amount = _amount_bucket(known.get("prior_amount_ratio_5d"))
    phase = str(known.get("prior_market_phase") or "unknown")
    return [
        (entry_mode, target_board, gap, prior_return, turnover, amount, phase),
        (entry_mode, target_board, gap, amount, phase),
        (entry_mode, target_board, gap, phase),
        (entry_mode, target_board, phase),
        (entry_mode, target_board, gap),
        (entry_mode, target_board),
        (entry_mode,),
    ]


def _candidate_score(candidate: Mapping[str, object], analog: AnalogStats) -> float:
    known = candidate.get("known_at_signal")
    known = known if isinstance(known, Mapping) else {}
    average_return = analog.average_return_pct if analog.average_return_pct is not None else -4.0
    win_rate = analog.smoothed_win_rate if analog.smoothed_win_rate is not None else 25.0
    hard_loss = analog.hard_loss_rate if analog.hard_loss_rate is not None else 50.0
    gap = _number(known.get("auction_gap_pct")) or 0.0
    prior_change = _number(known.get("prior_change_pct")) or 0.0
    score = average_return * 12 + (win_rate - 50) * 0.2 - hard_loss * 0.12
    score += max(0.0, 4.0 - abs(gap - 4.0))
    score += min(max(prior_change, -5.0), 8.0) * 0.08
    phase = str(known.get("prior_market_phase") or "unknown")
    score += {"broad_rise": 8.0, "repair": -1.0, "mixed": -5.0, "retreat": -8.0}.get(
        phase,
        -3.0,
    )
    if int(candidate.get("target_board") or 1) >= 3:
        score -= 6.0
    return round(score, 4)


def _history_action(
    candidate: Mapping[str, object],
    phase: str,
    *,
    min_analogs: int,
) -> str:
    if phase == "warmup":
        return "observe_warmup"
    analog = candidate.get("analog")
    analog = analog if isinstance(analog, Mapping) else {}
    effective = int(analog.get("effective_sample_count") or 0)
    average = _number(analog.get("average_return_pct"))
    win_rate = _number(analog.get("smoothed_win_rate"))
    hard_loss = _number(analog.get("hard_loss_rate"))
    seal_after_touch = _number(analog.get("seal_after_touch_rate"))
    known = candidate.get("known_at_signal")
    known = known if isinstance(known, Mapping) else {}
    phase_allowed = str(known.get("prior_market_phase") or "unknown") == "broad_rise"
    failed_rate = _number(known.get("prior_market_failed_rate"))
    market_allowed = phase_allowed and (failed_rate is None or failed_rate <= 0.5)
    entry_mode = str(candidate.get("entry_mode") or "")
    if entry_mode == "auction":
        eligible = _analog_gate(
            effective,
            average,
            win_rate,
            hard_loss,
            minimum_samples=max(min_analogs, 180),
            minimum_average=0.8,
            minimum_win_rate=52,
            maximum_hard_loss=15,
        ) and market_allowed
        return "auction_buy" if eligible else "watch_first_board"
    if entry_mode == "sweep":
        eligible = _analog_gate(
            effective,
            average,
            win_rate,
            hard_loss,
            minimum_samples=max(min_analogs, 120),
            minimum_average=1.0,
            minimum_win_rate=55,
            maximum_hard_loss=18,
        ) and market_allowed and seal_after_touch is not None and seal_after_touch >= 50
        return "wait_sweep" if eligible else "pass"
    if entry_mode == "tail":
        eligible = _analog_gate(
            effective,
            average,
            win_rate,
            hard_loss,
            minimum_samples=max(min_analogs, 120),
            minimum_average=1.0,
            minimum_win_rate=58,
            maximum_hard_loss=8,
        ) and market_allowed
        return "wait_tail" if eligible else "pass"

    target_board = int(candidate.get("target_board") or 1)
    gap = _number(known.get("auction_gap_pct"))
    amount_ratio = _number(known.get("prior_amount_ratio_5d"))
    promotion_rate = _number(known.get("prior_market_one_to_two_rate"))
    route_allowed = (
        target_board == 2
        and gap is not None
        and 3 <= gap <= 6
        and amount_ratio is not None
        and 1.2 <= amount_ratio <= 3
        and (promotion_rate is None or promotion_rate <= 0.4)
    )
    eligible = _analog_gate(
        effective,
        average,
        win_rate,
        hard_loss,
        minimum_samples=max(min_analogs, 180),
        minimum_average=1.0,
        minimum_win_rate=50,
        maximum_hard_loss=20,
    ) and market_allowed and route_allowed
    return "next_auction" if eligible else "pass"


def _analog_gate(
    effective: int,
    average: float | None,
    win_rate: float | None,
    hard_loss: float | None,
    *,
    minimum_samples: int,
    minimum_average: float,
    minimum_win_rate: float,
    maximum_hard_loss: float,
) -> bool:
    return (
        effective >= minimum_samples
        and average is not None
        and average >= minimum_average
        and win_rate is not None
        and win_rate >= minimum_win_rate
        and hard_loss is not None
        and hard_loss <= maximum_hard_loss
    )


def _favorable_factors(candidate: Mapping[str, object], analog: AnalogStats) -> list[str]:
    factors: list[str] = []
    if analog.average_return_pct is not None and analog.average_return_pct > 0:
        factors.append("历史相似样本净收益为正")
    if analog.smoothed_win_rate is not None and analog.smoothed_win_rate >= 50:
        factors.append("历史相似样本胜率不低于50%")
    if analog.hard_loss_rate is not None and analog.hard_loss_rate <= 15:
        factors.append("历史相似样本硬亏损率较低")
    known = candidate.get("known_at_signal")
    known = known if isinstance(known, Mapping) else {}
    if known.get("prior_market_phase") == "broad_rise":
        factors.append("D-1市场处于普涨阶段")
    return factors


def _risk_factors(candidate: Mapping[str, object], analog: AnalogStats) -> list[str]:
    factors: list[str] = []
    if analog.confidence == "insufficient":
        factors.append("历史相似样本不足")
    if analog.average_return_pct is not None and analog.average_return_pct <= 0:
        factors.append("历史相似样本净收益不为正")
    if analog.hard_loss_rate is not None and analog.hard_loss_rate > 25:
        factors.append("历史相似样本硬亏损率过高")
    known = candidate.get("known_at_signal")
    known = known if isinstance(known, Mapping) else {}
    phase = str(known.get("prior_market_phase") or "unknown")
    if phase != "broad_rise":
        factors.append(f"D-1市场并非普涨阶段（{phase}）")
    if int(candidate.get("target_board") or 1) >= 3:
        factors.append("二进三训练区没有稳定正优势")
    return factors


def _candidate_filled(candidate: Mapping[str, object]) -> bool:
    outcome = candidate.get("outcome")
    outcome = outcome if isinstance(outcome, Mapping) else {}
    entry_mode = str(candidate.get("entry_mode") or "")
    if entry_mode == "sweep":
        return bool(outcome.get("touched"))
    if entry_mode == "tail":
        return bool(outcome.get("sealed"))
    return True


def _day_market_context(frame: pd.DataFrame, trade_date: date) -> dict[str, object]:
    day = frame[frame["trade_date"].eq(pd.Timestamp(trade_date))]
    return _day_market_context_from_day(day)


def _day_market_context_from_day(day: pd.DataFrame) -> dict[str, object]:
    if day.empty:
        return {}
    first = day.iloc[0]
    return {
        "data_cutoff": "D_MINUS_1_CLOSE",
        "phase": str(first.get("prior_market_phase") or "unknown"),
        "advancing_rate": _rounded(first.get("prior_market_advancing_rate")),
        "sealed_count": _integer_or_none(first.get("prior_market_sealed_count")),
        "failed_rate": _rounded(first.get("prior_market_failed_rate")),
        "max_board": _integer_or_none(first.get("prior_market_max_board")),
        "first_board_count": _integer_or_none(first.get("prior_market_first_board_count")),
        "one_to_two_rate": _rounded(first.get("prior_market_one_to_two_rate")),
        "two_to_three_rate": _rounded(first.get("prior_market_two_to_three_rate")),
    }


def _gap_bucket(value: object) -> str:
    number = _number(value)
    if number is None:
        return "missing"
    if number < 2:
        return "1_2"
    if number < 5:
        return "2_5"
    return "5_7"


def _prior_return_bucket(value: object) -> str:
    number = _number(value)
    if number is None:
        return "missing"
    if number < 0:
        return "negative"
    if number < 3:
        return "0_3"
    if number < 7:
        return "3_7"
    return "7_plus"


def _turnover_bucket(value: object) -> str:
    number = _number(value)
    if number is None:
        return "missing"
    if number < 3:
        return "under_3"
    if number < 7:
        return "3_7"
    if number < 15:
        return "7_15"
    if number < 25:
        return "15_25"
    return "25_plus"


def _amount_bucket(value: object) -> str:
    number = _number(value)
    if number is None:
        return "missing"
    if number < 0.8:
        return "under_0_8"
    if number < 1.2:
        return "0_8_1_2"
    if number < 2:
        return "1_2_2"
    return "2_plus"


def _candidate_payload(
    row: pd.Series,
    entry_mode: str,
    target_board: int,
    *,
    total_cost_rate: float,
) -> dict[str, object]:
    signal_date = _date_text(row.get("trade_date"))
    prior_date = _date_text(row.get("prev_trade_date"))
    result_date = _date_text(row.get("next_trade_date"))
    open_price = _number(row.get("open_price"))
    limit_price = _number(row.get("limit_price"))
    entry_price = open_price if entry_mode in {"auction", "next_auction"} else limit_price
    next_open = _number(row.get("next_open_price"))
    next_close = _number(row.get("next_close_price"))
    known_at_signal = {
        "data_cutoff": "D_OPEN_AND_D_MINUS_1_CLOSE",
        "auction_gap_pct": _rounded(row.get("auction_gap_pct")),
        "prior_change_pct": _rounded(row.get("prior_change_pct")),
        "prior_open_gap_pct": _rounded(row.get("prior_open_gap_pct")),
        "prior_low_change_pct": _rounded(row.get("prior_low_change_pct")),
        "prior_amplitude_pct": _rounded(row.get("prior_amplitude_pct")),
        "prior_return_5d_pct": _rounded(row.get("prior_return_5d_pct")),
        "prior_return_20d_pct": _rounded(row.get("prior_return_20d_pct")),
        "prior_turnover_rate": _rounded(row.get("prior_turnover_rate")),
        "prior_amount_ratio_5d": _rounded(row.get("prior_amount_ratio_5d")),
        "prior_industry_id": str(row.get("industry_id") or "UNCLASSIFIED"),
        "prior_industry_name": str(row.get("industry_name") or "未分类"),
        "prior_industry_change_pct": _rounded(row.get("prior_industry_change_pct")),
        "prior_industry_return_5d_pct": _rounded(row.get("prior_industry_return_5d_pct")),
        "prior_industry_advancing_rate": _rounded(row.get("prior_industry_advancing_rate")),
        "prior_industry_turnover_ratio_5d": _rounded(row.get("prior_industry_turnover_ratio_5d")),
        "prior_industry_sealed_count": _integer_or_none(row.get("prior_industry_sealed_count")),
        "prior_industry_sealed_rate": _rounded(row.get("prior_industry_sealed_rate")),
        "prior_industry_heat_score": _rounded(row.get("prior_industry_heat_score")),
        "prior_industry_heat_rank": _integer_or_none(row.get("prior_industry_heat_rank")),
        "prior_industry_count": _integer_or_none(row.get("prior_industry_count")),
        "prior_industry_leadership_score": _rounded(row.get("prior_industry_leadership_score")),
        "prior_industry_leader_rank": _integer_or_none(row.get("prior_industry_leader_rank")),
        "prior_industry_stock_count": _integer_or_none(row.get("prior_industry_stock_count")),
        "prior_market_phase": str(row.get("prior_market_phase") or "unknown"),
        "prior_market_advancing_rate": _rounded(row.get("prior_market_advancing_rate")),
        "prior_market_sealed_count": _integer_or_none(row.get("prior_market_sealed_count")),
        "prior_market_failed_rate": _rounded(row.get("prior_market_failed_rate")),
        "prior_market_max_board": _integer_or_none(row.get("prior_market_max_board")),
        "prior_market_first_board_count": _integer_or_none(row.get("prior_market_first_board_count")),
        "prior_market_one_to_two_rate": _rounded(row.get("prior_market_one_to_two_rate")),
        "prior_market_two_to_three_rate": _rounded(row.get("prior_market_two_to_three_rate")),
    }
    outcome = {
        "touched": bool(row.get("touched")),
        "sealed": bool(row.get("sealed")),
        "entry_day_close_price": _number(row.get("close_price")),
        "next_open_price": next_open,
        "next_close_price": next_close,
        "next_open_return_pct": _net_return(entry_price, next_open, total_cost_rate),
        "next_close_return_pct": _net_return(entry_price, next_close, total_cost_rate),
    }
    if entry_mode == "auction":
        action = "auction_buy"
        confidence = "daily_open_proxy"
    elif entry_mode == "next_auction":
        action = "next_auction"
        confidence = "daily_open_proxy"
    elif entry_mode == "sweep":
        action = "watch_first_board"
        confidence = "daily_touch_proxy_without_queue"
    else:
        action = "wait_tail"
        confidence = "daily_close_proxy_unverifiable"
    return {
        "vt_symbol": str(row.get("vt_symbol") or ""),
        "name": str(row.get("name") or ""),
        "industry_id": str(row.get("industry_id") or "UNCLASSIFIED"),
        "industry_name": str(row.get("industry_name") or row.get("industry") or "未分类"),
        "entry_mode": entry_mode,
        "action": action,
        "signal_date": signal_date,
        "plan_date": prior_date if entry_mode == "next_auction" else signal_date,
        "entry_date": signal_date,
        "result_date": result_date,
        "target_board": target_board,
        "prior_streak": int(row.get("prior_streak") or 0),
        "entry_price": entry_price,
        "limit_price": limit_price,
        "known_at_signal": known_at_signal,
        "outcome": outcome,
        "execution_confidence": confidence,
        "source_mode": "daily_point_in_time",
    }


def _board_lane_candidates_for_date(
    frame: pd.DataFrame,
    trade_date: date,
    *,
    event_evidence: EventIndex,
    financial_index: FinancialIndex,
    total_cost_rate: float,
) -> list[dict[str, object]]:
    timestamp = pd.Timestamp(trade_date)
    day = frame[frame["trade_date"].eq(timestamp)]
    return _board_lane_candidates_from_day(
        day,
        trade_date,
        event_evidence=event_evidence,
        financial_index=financial_index,
        total_cost_rate=total_cost_rate,
    )


def _board_lane_candidates_from_day(
    day: pd.DataFrame,
    trade_date: date,
    *,
    event_evidence: EventIndex,
    financial_index: FinancialIndex,
    total_cost_rate: float,
) -> list[dict[str, object]]:
    if day.empty:
        return []
    usable = day[
        day["prev_close"].gt(0)
        & day["open_price"].gt(0)
    ]
    rows_by_symbol = {
        str(row.get("vt_symbol") or ""): row
        for _, row in usable.iterrows()
    }
    candidates: list[dict[str, object]] = []

    for (symbol, event_date), event in event_evidence.items():
        if event_date != trade_date:
            continue
        row = rows_by_symbol.get(symbol)
        if row is None or int(row.get("prior_streak") or 0) != 0:
            continue
        first_time = str(event.get("first_limit_time") or "")
        if not first_time:
            continue
        path = _event_intraday_path(event, previous_close=row.get("prev_close"))
        reseal_time = first_reseal_time(path) if path else None
        if first_time < "10:00:00" and reseal_time:
            signal_time = reseal_time
            signal_kind = "reseal"
        else:
            signal_time = first_time
            signal_kind = "first_touch"
        prefix = path_prefix_features(path, signal_time) if path else None
        base = _candidate_payload(
            row,
            "sweep",
            1,
            total_cost_rate=total_cost_rate,
        )
        candidates.append(
            _lane_candidate_payload(
                row,
                base,
                signal_time=signal_time,
                signal_kind=signal_kind,
                path_prefix=prefix,
                current_event=event,
                prior_event=None,
                financial_index=financial_index,
                trade_date=trade_date,
            )
        )

    auction_rows = usable[
        usable["auction_gap_pct"].between(1.0, 7.0)
        & (
            usable["prior_streak"].ge(1)
            | usable["prior_limit_count_5"].ge(1)
        )
    ]
    for _, row in auction_rows.iterrows():
        prior_streak = int(row.get("prior_streak") or 0)
        recent_limits = int(row.get("prior_limit_count_5") or 0)
        target_board = max(prior_streak + 1, recent_limits + 1, 2)
        if target_board == 2:
            continue
        symbol = str(row.get("vt_symbol") or "")
        current_event = event_evidence.get((symbol, trade_date))
        current_path = (
            _event_intraday_path(current_event, previous_close=row.get("prev_close"))
            if current_event
            else []
        )
        trigger = (
            scheduled_execution.resolve_relay_entry_trigger(
                current_event.get("first_limit_time"),
                current_path,
            )
            if current_event
            else {
                "status": "event_missing",
                "signal_time": None,
                "signal_kind": None,
                "reason": "current_day_limit_event_missing",
            }
        )
        trigger_time = str(trigger.get("signal_time") or "")
        path_prefix = (
            path_prefix_features(current_path, trigger_time)
            if current_path and trigger_time
            else None
        )
        base = _candidate_payload(
            row,
            "next_auction",
            target_board,
            total_cost_rate=total_cost_rate,
        )
        prior_date_text = _date_text(row.get("prev_trade_date"))
        prior_event = (
            event_evidence.get(
                (symbol, date.fromisoformat(prior_date_text))
            )
            if prior_date_text
            else None
        )
        candidate = _lane_candidate_payload(
            row,
            base,
            signal_time=trigger_time or "09:25:00",
            signal_kind=str(trigger.get("signal_kind") or "relay_watch"),
            path_prefix=path_prefix,
            current_event=current_event,
            prior_event=prior_event,
            financial_index=financial_index,
            trade_date=trade_date,
        )
        candidates.append(
            _with_relay_trigger(
                candidate,
                trigger,
                total_cost_rate=total_cost_rate,
            )
        )
    return candidates


def _event_intraday_path(
    event: Mapping[str, object],
    *,
    previous_close: object,
) -> list[object]:
    preview = event.get("time_preview")
    if isinstance(preview, Sequence) and not isinstance(preview, (str, bytes)):
        values = list(preview)
        if any(value is not None for value in values):
            return values
    prices = event.get("minute_price_path")
    if not isinstance(prices, Sequence) or isinstance(prices, (str, bytes)):
        return []
    return price_path_to_return_path(prices, previous_close=previous_close)


def _with_relay_trigger(
    candidate: Mapping[str, object],
    trigger: Mapping[str, object],
    *,
    total_cost_rate: float,
) -> dict[str, object]:
    result = dict(candidate)
    status = str(trigger.get("status") or "missing_first_touch")
    ready = status == "ready"
    signal_time = str(trigger.get("signal_time") or "") or None
    signal_kind = str(trigger.get("signal_kind") or "") or None
    limit_price = _number(candidate.get("limit_price"))
    outcome = candidate.get("outcome")
    outcome = dict(outcome) if isinstance(outcome, Mapping) else {}
    entry_price = limit_price if ready else None
    outcome.update(
        {
            "next_open_return_pct": _net_return(
                entry_price,
                _number(outcome.get("next_open_price")),
                total_cost_rate,
            ),
            "next_close_return_pct": _net_return(
                entry_price,
                _number(outcome.get("next_close_price")),
                total_cost_rate,
            ),
        }
    )
    result.update(
        {
            "qualification_time": "09:25:00",
            "qualification_kind": "auction",
            "relay_trigger_status": status,
            "relay_trigger_reason": trigger.get("reason"),
            "signal_time": signal_time,
            "buy_time": signal_time,
            "signal_kind": signal_kind,
            "entry_mode": "sweep" if ready else "relay_watch",
            "entry_price": entry_price,
            "outcome": outcome,
            "data_cutoff": "D_INTRADAY_TRIGGER_AND_D_MINUS_1_EVIDENCE",
            "execution_confidence": (
                "three_minute_path_without_queue" if ready else "not_executable"
            ),
            "source_mode": (
                str(candidate.get("source_mode") or "intraday_path_prefix")
                if ready
                else "relay_trigger_unavailable"
            ),
        }
    )
    return result


def _lane_candidate_payload(
    row: pd.Series,
    base: Mapping[str, object],
    *,
    signal_time: str,
    signal_kind: str,
    path_prefix: Mapping[str, object] | None,
    current_event: Mapping[str, object] | None,
    prior_event: Mapping[str, object] | None,
    financial_index: FinancialIndex,
    trade_date: date,
) -> dict[str, object]:
    known = base.get("known_at_signal")
    known = known if isinstance(known, Mapping) else {}
    symbol = str(base.get("vt_symbol") or "")
    prior_board = _prior_board_payload(prior_event)
    financial_snapshot = financial_snapshot_as_of(financial_index, symbol, trade_date)
    source_mode = (
        "intraday_path_prefix"
        if path_prefix
        else "event_time_proxy_without_path"
        if current_event
        else "daily_auction_point_in_time"
    )
    return {
        **dict(base),
        **dict(known),
        "industry_id": str(row.get("industry_id") or "UNCLASSIFIED"),
        "industry_name": str(row.get("industry_name") or "未分类"),
        "signal_time": signal_time,
        "signal_kind": signal_kind,
        "buy_time": "09:30:00" if signal_kind == "auction" else signal_time,
        "sell_time_next_open": "09:30:00",
        "sell_time_next_close": "15:00:00",
        "prior_limit_count_126": int(row.get("prior_limit_count_126") or 0),
        "prior_touch_count_126": int(row.get("prior_touch_count_126") or 0),
        "prior_limit_count_5": int(row.get("prior_limit_count_5") or 0),
        "prior_limit_count_10": int(row.get("prior_limit_count_10") or 0),
        "prior_break_streak": int(row.get("prior_break_streak") or 0),
        "prior_seal_success_rate_126": _rounded(
            row.get("prior_seal_success_rate_126")
        ),
        "trade_days_since_prior_limit": _integer_or_none(
            row.get("trade_days_since_prior_limit")
        ),
        "pullback_from_prior_limit_pct": _rounded(
            row.get("pullback_from_prior_limit_pct")
        ),
        "prior_position_120": _rounded(row.get("prior_position_120")),
        "recent_structure_board_count": int(
            row.get("recent_structure_board_count") or 1
        ),
        "path_prefix": dict(path_prefix) if path_prefix else None,
        "event_evidence": _current_event_evidence(current_event),
        "prior_board": prior_board,
        "financial_risk": financial_risk_as_of(
            financial_index,
            symbol,
            trade_date,
        ),
        "financial_snapshot": financial_snapshot,
        "has_l2": False,
        "execution_confidence": (
            "three_minute_path_without_queue"
            if path_prefix
            else "event_time_without_queue"
            if current_event
            else "daily_open_proxy"
        ),
        "source_mode": source_mode,
    }


def _current_event_evidence(
    event: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if not event:
        return None
    return {
        "first_limit_time": event.get("first_limit_time"),
        "historical_seal_rate": event.get("historical_seal_rate"),
        "limit_up_shape": event.get("limit_up_shape"),
        "limit_up_reason": event.get("limit_up_reason"),
        "path_source": event.get("path_source"),
        "source_updated_at": event.get("source_updated_at"),
    }


def _prior_board_payload(
    event: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if not event:
        return None
    path = event.get("time_preview")
    path = path if isinstance(path, Sequence) and not isinstance(path, (str, bytes)) else []
    path_summary = path_prefix_features(path, "14:57:00") if path else None
    return {
        "is_sealed": event.get("is_sealed"),
        "first_limit_time": event.get("first_limit_time"),
        "last_limit_time": event.get("last_limit_time"),
        "open_times": event.get("open_times"),
        "seal_amount": event.get("seal_amount"),
        "turnover_rate": event.get("turnover_rate"),
        "seal_to_turnover_ratio": event.get("seal_to_turnover_ratio"),
        "historical_seal_rate": event.get("historical_seal_rate"),
        "limit_up_shape": event.get("limit_up_shape"),
        "path_summary": path_summary,
        "source": event.get("status_source"),
    }


def _limit_price(previous_close: object) -> float | None:
    value = _number(previous_close)
    return round(value * 1.1 + 1e-8, 2) if value and value > 0 else None


def _net_return(
    entry_price: float | None,
    exit_price: float | None,
    total_cost_rate: float,
) -> float | None:
    if not entry_price or exit_price is None:
        return None
    return round(((exit_price / entry_price - 1) - total_cost_rate) * 100, 4)


def _mapping_number(value: object, key: str) -> float | None:
    if not isinstance(value, Mapping):
        return None
    return _number(value.get(key))


def _market_phase(value: object) -> str:
    number = _number(value)
    if number is None:
        return "unknown"
    if number < 0.35:
        return "retreat"
    if number < 0.50:
        return "mixed"
    if number < 0.65:
        return "repair"
    return "broad_rise"


def _date_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value)[:10]


def _number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rounded(value: object, digits: int = 4) -> float | None:
    number = _number(value)
    return round(number, digits) if number is not None else None


def _integer_or_none(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None
