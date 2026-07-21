"""Causal daily algorithm for dynamic leaders and main-rise pullbacks."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


ALGORITHM_VERSION = "causal-leader-pullback-close-v2"
CONCEPT_ANCHOR_MODE = "breakout_relative_turnover"
CONCEPT_EXIT_DRAWDOWN_PCT = 5.0
CONCEPT_EXIT_CONFIRM_SESSIONS = 3
IGNITION_RETURN_PCT = 5.0
IGNITION_VOLUME_RATIO = 1.5
PULLBACK_PCT = 5.0
SUPPORT_TOLERANCE_PCT = 2.0
ROUND_TRIP_COST_PCT = 0.2
NON_CONTRACTION_VOLUME_RATIO = 0.8
GOLD_STRONG_RECLAIM_RETURN_PCT = 8.0
GOLD_STRONG_RECLAIM_MAX_PEAK_GAP_PCT = 5.0
GOLD_STRONG_RECLAIM_MAX_SUPPORT_SESSIONS = 2
CROSS_REGIME_POLICY_VERSION = "causal-leader-pullback-cross-regime-v3"
WARMING_SUPPORT_RELEVANCE_POLICY_VERSION = (
    "causal-leader-pullback-warming-support-relevance-v1"
)
ROTATION_NEXT_SESSION_POLICY_VERSION = (
    "causal-leader-pullback-rotation-next-session-v1"
)
THREE_PHASE_ADAPTIVE_POLICY_VERSION = (
    "causal-leader-pullback-three-phase-adaptive-v1"
)
SUPPORT_DEPTH = {"ma5": 1, "ma10": 2, "ma20": 3}
MINIMUM_REQUIRED_SUPPORT = "minimum_required_support"
EXACT_REQUIRED_SUPPORT = "exact_required_support"
SUPPORT_MATCH_MODES = frozenset(
    {MINIMUM_REQUIRED_SUPPORT, EXACT_REQUIRED_SUPPORT}
)
PROHIBITED_RANK_TOKENS = (
    "future_",
    "outcome",
    "net_return",
    "gross_return",
    "exit_",
    "mfe",
    "mae",
    "profit",
)


@dataclass(frozen=True)
class CampaignReplay:
    """Signals, trades and daily states for one stock in one campaign."""

    signals: pd.DataFrame
    trades: pd.DataFrame
    daily_ledger: pd.DataFrame


@dataclass(frozen=True)
class CampaignPreparation:
    """Normalized campaign paths and causal states before trade execution."""

    paths: pd.DataFrame
    signals: pd.DataFrame
    daily_ledger: pd.DataFrame


def rank_campaign_leaders(member_rows: pd.DataFrame) -> pd.DataFrame:
    """Rank each campaign/date using visible leg leadership only."""

    _reject_prohibited_columns(member_rows, PROHIBITED_RANK_TOKENS)
    required = (
        "campaign_id",
        "sector_id",
        "concept_name",
        "trade_date",
        "vt_symbol",
        "stock_name",
        "leg_gain_pct",
        "strong_days_since_ignition",
        "concept_gain_pct",
        "turnover_expansion",
        "ignited_in_campaign",
        "structure_intact",
    )
    _require_columns(member_rows, required, "campaign leader member")
    frame = member_rows.copy()
    frame["trade_date"] = _normalized_dates(frame["trade_date"])
    identity = ["campaign_id", "trade_date", "vt_symbol"]
    if frame.duplicated(identity).any():
        raise ValueError("campaign leader member identities must be unique")

    numeric = (
        "leg_gain_pct",
        "strong_days_since_ignition",
        "concept_gain_pct",
        "turnover_expansion",
    )
    frame[list(numeric)] = frame[list(numeric)].apply(pd.to_numeric, errors="coerce")
    frame["concept_excess_gain_pct"] = frame["leg_gain_pct"] - frame["concept_gain_pct"]
    group = ["campaign_id", "trade_date"]
    frame["member_count"] = frame.groupby(group, sort=False)["vt_symbol"].transform(
        "nunique"
    )
    frame["rankable"] = (
        frame["ignited_in_campaign"].astype(bool)
        & frame["structure_intact"].astype(bool)
        & frame[list(numeric)].notna().all(axis=1)
    )
    frame["rankable_member_count"] = (
        frame["rankable"]
        .groupby([frame["campaign_id"], frame["trade_date"]], sort=False)
        .transform("sum")
    )

    eligible = frame["rankable"] & frame["rankable_member_count"].ge(3)
    ordered = (
        frame.loc[eligible]
        .sort_values(
            [
                "campaign_id",
                "trade_date",
                "leg_gain_pct",
                "strong_days_since_ignition",
                "concept_excess_gain_pct",
                "turnover_expansion",
                "vt_symbol",
            ],
            ascending=[True, True, False, False, False, False, True],
            na_position="last",
            kind="stable",
        )
        .copy()
    )
    frame["dynamic_rank"] = pd.array([pd.NA] * len(frame), dtype="Int64")
    ranks = ordered.groupby(group, sort=False).cumcount().add(1).astype("Int64")
    frame.loc[ordered.index, "dynamic_rank"] = ranks.to_numpy()
    frame["dynamic_top3"] = frame["dynamic_rank"].le(3).fillna(False)
    frame["rank_feature_cutoff_date"] = frame["trade_date"]
    return frame.reset_index(drop=True)


def select_gold_strong_reclaim_signals(signals: pd.DataFrame) -> pd.DataFrame:
    """Select the frozen GOLD/NORMAL strong reclaim entry without outcomes."""

    if signals.empty:
        return signals.copy()
    _reject_prohibited_columns(signals, PROHIBITED_RANK_TOKENS)
    required = (
        "signal_date",
        "market_timing_feature_cutoff_date",
        "signal_daily_return_pct",
        "signal_close",
        "reference_peak_price",
        "support_test_session_gap",
        "active_direction",
        "danger_state",
    )
    _require_columns(signals, required, "gold strong reclaim signal")
    frame = signals.copy()
    frame["signal_date"] = _normalized_dates(frame["signal_date"])
    frame["market_timing_feature_cutoff_date"] = _normalized_dates(
        frame["market_timing_feature_cutoff_date"]
    )
    if not frame["market_timing_feature_cutoff_date"].eq(frame["signal_date"]).all():
        raise ValueError("market timing cutoff must equal signal date")
    numeric_columns = (
        "signal_daily_return_pct",
        "signal_close",
        "reference_peak_price",
        "support_test_session_gap",
    )
    frame[list(numeric_columns)] = frame[list(numeric_columns)].apply(
        pd.to_numeric,
        errors="coerce",
    )
    peak_gap_pct = (frame["signal_close"] / frame["reference_peak_price"] - 1.0) * 100.0
    selected = (
        frame["active_direction"].astype(str).eq("GOLD")
        & frame["danger_state"].astype(str).eq("NORMAL")
        & frame["signal_daily_return_pct"].ge(GOLD_STRONG_RECLAIM_RETURN_PCT)
        & frame["signal_close"].ge(
            frame["reference_peak_price"]
            * (1.0 - GOLD_STRONG_RECLAIM_MAX_PEAK_GAP_PCT / 100.0)
        )
        & frame["support_test_session_gap"].between(
            1,
            GOLD_STRONG_RECLAIM_MAX_SUPPORT_SESSIONS,
        )
        & frame["reference_peak_price"].gt(0.0)
    )
    result = frame.loc[selected].copy()
    result["peak_gap_pct"] = peak_gap_pct.loc[selected]
    return result.reset_index(drop=True)


def select_cross_regime_support_reclaim_signals(
    signals: pd.DataFrame,
) -> pd.DataFrame:
    """Route the frozen strong-reclaim signal by same-day market phase."""

    gold = select_gold_strong_reclaim_signals(signals)
    if gold.empty:
        return gold
    required = ("market_phase", "signal_low", "support_price")
    _require_columns(gold, required, "cross-regime support reclaim signal")
    gold[["signal_low", "support_price"]] = gold[
        ["signal_low", "support_price"]
    ].apply(pd.to_numeric, errors="coerce")
    support_floor = gold["support_price"] * (1.0 - SUPPORT_TOLERANCE_PCT / 100.0)
    phase = gold["market_phase"].astype(str)
    selected = phase.eq("rotation") | (
        phase.eq("warming")
        & gold["support_price"].gt(0.0)
        & gold["signal_low"].ge(support_floor)
    )
    return gold.loc[selected].reset_index(drop=True)


def select_warming_support_relevance_signals(
    signals: pd.DataFrame,
) -> pd.DataFrame:
    """Keep rotation reclaims and warming reclaims whose active support holds."""

    if signals.empty:
        return signals.copy()
    _reject_prohibited_columns(signals, PROHIBITED_RANK_TOKENS)
    gold = select_gold_strong_reclaim_signals(signals)
    if gold.empty:
        return gold
    required = ("market_phase", "signal_low", "support_price")
    _require_columns(gold, required, "warming support relevance signal")
    gold[["signal_low", "support_price"]] = gold[
        ["signal_low", "support_price"]
    ].apply(pd.to_numeric, errors="coerce")
    support_gap_pct = (gold["signal_low"] / gold["support_price"] - 1.0) * 100.0
    phase = gold["market_phase"].astype(str)
    selected = phase.eq("rotation") | (
        phase.eq("warming")
        & gold["support_price"].gt(0.0)
        & gold["signal_low"].ge(gold["support_price"])
        & gold["signal_low"].le(
            gold["support_price"]
            * (1.0 + GOLD_STRONG_RECLAIM_RETURN_PCT / 100.0)
        )
    )
    result = gold.loc[selected].copy()
    result["low_support_gap_pct"] = support_gap_pct.loc[selected]
    return result.reset_index(drop=True)


def select_rotation_next_session_signals(
    signals: pd.DataFrame,
) -> pd.DataFrame:
    """Keep support relevance but require next-session confirmation in rotation."""

    selected = select_warming_support_relevance_signals(signals)
    if selected.empty:
        return selected
    _require_columns(
        selected,
        ("market_phase", "support_test_session_gap"),
        "rotation next-session signal",
    )
    gaps = pd.to_numeric(
        selected["support_test_session_gap"], errors="coerce"
    )
    phase = selected["market_phase"].astype(str)
    keep = phase.ne("rotation") | gaps.eq(1.0)
    return selected.loc[keep].reset_index(drop=True)


def select_three_phase_adaptive_signals(
    signals: pd.DataFrame,
) -> pd.DataFrame:
    """Trade uptrend reclaims and apply stricter support rules as momentum cools."""

    gold = select_gold_strong_reclaim_signals(signals)
    if gold.empty:
        return gold
    _require_columns(
        gold,
        ("market_phase", "signal_low", "support_price", "support_test_session_gap"),
        "three-phase adaptive signal",
    )
    numeric = ("signal_low", "support_price", "support_test_session_gap")
    gold[list(numeric)] = gold[list(numeric)].apply(pd.to_numeric, errors="coerce")
    phase = gold["market_phase"].astype(str)
    support_gap_pct = (gold["signal_low"] / gold["support_price"] - 1.0) * 100.0
    support_relevant = (
        gold["support_price"].gt(0.0)
        & support_gap_pct.between(0.0, GOLD_STRONG_RECLAIM_RETURN_PCT)
    )
    support_holds = gold["support_price"].gt(0.0) & support_gap_pct.ge(0.0)
    selected = (
        (phase.eq("uptrend") & support_holds)
        | (phase.eq("warming") & support_relevant)
        | (
            phase.eq("rotation")
            & gold["support_test_session_gap"].eq(1.0)
        )
    )
    result = gold.loc[selected].copy()
    result["low_support_gap_pct"] = support_gap_pct.loc[selected]
    return result.reset_index(drop=True)


def explain_warming_support_relevance_signal(
    signal: Mapping[str, Any],
) -> str:
    """Return the first causal rejection reason or the eligible decision."""

    frame = pd.DataFrame([dict(signal)])
    _reject_prohibited_columns(frame, PROHIBITED_RANK_TOKENS)
    required = (
        "signal_date",
        "market_timing_feature_cutoff_date",
        "signal_daily_return_pct",
        "signal_close",
        "reference_peak_price",
        "support_test_session_gap",
        "active_direction",
        "danger_state",
        "market_phase",
        "signal_low",
        "support_price",
    )
    _require_columns(frame, required, "warming support relevance signal")
    signal_date = pd.Timestamp(signal["signal_date"]).normalize()
    timing_cutoff = pd.Timestamp(
        signal["market_timing_feature_cutoff_date"]
    ).normalize()
    if timing_cutoff != signal_date:
        raise ValueError("market timing cutoff must equal signal date")

    if str(signal["active_direction"]) != "GOLD":
        return "cash_non_gold_market"
    if str(signal["danger_state"]) != "NORMAL":
        return "cash_danger_market"
    daily_return = _finite_or_none(signal["signal_daily_return_pct"])
    if daily_return is None or daily_return < GOLD_STRONG_RECLAIM_RETURN_PCT:
        return "confirmation_return_below_8pct"
    close = _finite_or_none(signal["signal_close"])
    reference_peak = _finite_or_none(signal["reference_peak_price"])
    if (
        close is None
        or reference_peak is None
        or reference_peak <= 0.0
        or close
        < reference_peak * (1.0 - GOLD_STRONG_RECLAIM_MAX_PEAK_GAP_PCT / 100.0)
    ):
        return "close_too_far_below_visible_peak"
    support_gap = _finite_or_none(signal["support_test_session_gap"])
    if (
        support_gap is None
        or support_gap < 1
        or support_gap > GOLD_STRONG_RECLAIM_MAX_SUPPORT_SESSIONS
    ):
        return "support_confirmation_too_late"

    phase = str(signal["market_phase"])
    if phase == "rotation":
        return "eligible_rotation_strong_reclaim"
    if phase != "warming":
        return "cash_unsupported_market_phase"
    low = _finite_or_none(signal["signal_low"])
    support = _finite_or_none(signal["support_price"])
    if low is None or support is None or support <= 0.0:
        return "warming_support_invalid"
    if low < support:
        return "warming_support_undercut"
    if low > support * (1.0 + GOLD_STRONG_RECLAIM_RETURN_PCT / 100.0):
        return "warming_support_stale"
    return "eligible_warming_support_relevance"


def replay_stock_campaign(
    campaign_path: pd.DataFrame,
    *,
    support_match_mode: str = MINIMUM_REQUIRED_SUPPORT,
) -> CampaignReplay:
    """Replay one ordered stock campaign and execute its close signals."""

    identities = campaign_path.loc[:, ["campaign_id", "vt_symbol"]].drop_duplicates()
    if len(identities) != 1:
        raise ValueError("one replay requires exactly one stock campaign")
    return replay_stock_campaigns(
        campaign_path,
        support_match_mode=support_match_mode,
    )


def replay_stock_campaigns(
    campaign_paths: pd.DataFrame,
    *,
    support_match_mode: str = MINIMUM_REQUIRED_SUPPORT,
) -> CampaignReplay:
    """Prepare once and independently replay many stock campaigns."""

    prepared = prepare_stock_campaigns(
        campaign_paths,
        support_match_mode=support_match_mode,
    )
    trades = execute_prepared_close_trades(prepared.signals, prepared)
    return CampaignReplay(
        signals=prepared.signals,
        trades=trades,
        daily_ledger=prepared.daily_ledger,
    )


def prepare_stock_campaigns(
    campaign_paths: pd.DataFrame,
    *,
    support_match_mode: str = MINIMUM_REQUIRED_SUPPORT,
) -> CampaignPreparation:
    """Build campaign signals and daily states without executing any trades."""

    if support_match_mode not in SUPPORT_MATCH_MODES:
        raise ValueError(f"unsupported support match mode: {support_match_mode}")
    paths = _prepare_campaign_paths(campaign_paths)
    signal_rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    group_columns = ["campaign_id", "vt_symbol"]
    for positions in paths.groupby(group_columns, sort=False).indices.values():
        path = paths.iloc[positions].reset_index(drop=True)
        path_signals, path_daily = _build_campaign_signal_records(
            path,
            support_match_mode=support_match_mode,
        )
        signal_rows.extend(path_signals)
        daily_rows.extend(path_daily)

    signals = pd.DataFrame.from_records(signal_rows, columns=_signal_columns())
    daily = pd.DataFrame.from_records(daily_rows)
    return CampaignPreparation(paths=paths, signals=signals, daily_ledger=daily)


def execute_prepared_close_trades(
    signals: pd.DataFrame,
    prepared: CampaignPreparation,
    *,
    round_trip_cost_pct: float = ROUND_TRIP_COST_PCT,
) -> pd.DataFrame:
    """Execute signals against already normalized campaign paths."""

    if round_trip_cost_pct < 0:
        raise ValueError("round-trip cost cannot be negative")
    if signals.empty:
        return pd.DataFrame(columns=_trade_columns())
    return _execute_prepared_close_trades(
        signals,
        prepared.paths,
        round_trip_cost_pct=round_trip_cost_pct,
    )


def execute_close_trades(
    signals: pd.DataFrame,
    campaign_path: pd.DataFrame,
    *,
    round_trip_cost_pct: float = ROUND_TRIP_COST_PCT,
) -> pd.DataFrame:
    """Apply D-close entry, D+1 loss stop and causal winner exits."""

    if round_trip_cost_pct < 0:
        raise ValueError("round-trip cost cannot be negative")
    if signals.empty:
        return pd.DataFrame(columns=_trade_columns())
    signal_frame = _prepare_signal_frame(signals)
    paths = _prepare_campaign_paths(campaign_path)
    return _execute_prepared_close_trades(
        signal_frame,
        paths,
        round_trip_cost_pct=round_trip_cost_pct,
    )


def _prepare_signal_frame(signals: pd.DataFrame) -> pd.DataFrame:
    required = (
        "signal_id",
        "campaign_id",
        "sector_id",
        "vt_symbol",
        "signal_date",
        "feature_cutoff_date",
        "signal_close",
        "wave_number",
        "support_line",
        "support_depth",
        "support_test_date",
        "reference_peak_price",
        "dynamic_rank",
    )
    _require_columns(signals, required, "leader pullback signal")
    signal_frame = signals.copy()
    for column in ("signal_date", "feature_cutoff_date"):
        signal_frame[column] = _normalized_dates(signal_frame[column])
    if not signal_frame["feature_cutoff_date"].eq(signal_frame["signal_date"]).all():
        raise ValueError("signal feature cutoff must equal signal date")
    if signal_frame["signal_id"].duplicated().any():
        raise ValueError("leader pullback signal IDs must be unique")
    return signal_frame


def _execute_prepared_close_trades(
    signals: pd.DataFrame,
    campaign_paths: pd.DataFrame,
    *,
    round_trip_cost_pct: float = ROUND_TRIP_COST_PCT,
) -> pd.DataFrame:
    if signals.empty:
        return pd.DataFrame(columns=_trade_columns())
    signal_frame = _prepare_signal_frame(signals)
    path_groups = campaign_paths.groupby(
        ["campaign_id", "vt_symbol"], sort=False
    ).indices
    signal_groups = signal_frame.groupby(
        ["campaign_id", "vt_symbol"], sort=False
    ).indices
    rows: list[dict[str, Any]] = []
    for identity, signal_positions in signal_groups.items():
        path_positions = path_groups.get(identity)
        if path_positions is None:
            raise ValueError(f"signal identity has no campaign path: {identity!r}")
        path = campaign_paths.iloc[path_positions].reset_index(drop=True)
        identity_signals = signal_frame.iloc[signal_positions]
        rows.extend(
            _execute_close_trade_records(
                identity_signals,
                path,
                round_trip_cost_pct=round_trip_cost_pct,
            )
        )
    return (
        pd.DataFrame.from_records(rows, columns=_trade_columns())
        .sort_values(["entry_date", "signal_id"], kind="stable")
        .reset_index(drop=True)
    )


def _execute_close_trade_records(
    signal_frame: pd.DataFrame,
    path: pd.DataFrame,
    *,
    round_trip_cost_pct: float,
) -> list[dict[str, Any]]:
    positions = {
        pd.Timestamp(value): index for index, value in enumerate(path["trade_date"])
    }
    rows: list[dict[str, Any]] = []
    occupied_through: pd.Timestamp | None = None
    loss_depth_by_wave: dict[int, int] = {}
    loss_date_by_wave: dict[int, pd.Timestamp] = {}
    completed_waves: set[int] = set()
    for signal in signal_frame.sort_values(
        ["signal_date", "support_depth", "signal_id"], kind="stable"
    ).to_dict("records"):
        entry_date = pd.Timestamp(signal["signal_date"])
        wave_number = int(signal["wave_number"])
        support_depth = int(signal["support_depth"])
        if occupied_through is not None and entry_date <= occupied_through:
            continue
        if wave_number in completed_waves:
            continue
        if support_depth <= loss_depth_by_wave.get(wave_number, 0):
            continue
        prior_loss_date = loss_date_by_wave.get(wave_number)
        if (
            prior_loss_date is not None
            and pd.Timestamp(signal["support_test_date"]) <= prior_loss_date
        ):
            continue
        trade = _execute_signal(
            signal,
            path,
            positions,
            round_trip_cost_pct=round_trip_cost_pct,
        )
        rows.append(trade)
        exit_date = trade.get("exit_date")
        if exit_date is None or pd.isna(exit_date):
            break
        occupied_through = pd.Timestamp(exit_date)
        if trade["exit_reason"] == "d1_loss_stop":
            loss_depth_by_wave[wave_number] = support_depth
            loss_date_by_wave[wave_number] = pd.Timestamp(exit_date)
        else:
            completed_waves.add(wave_number)
    return rows


def summarize_trade_metrics(trades: pd.DataFrame) -> dict[str, Any]:
    """Summarize closed signal returns without hiding censored rows."""

    if trades.empty:
        return _empty_metrics()
    _require_columns(trades, ("exit_date", "net_return_pct"), "trade metric")
    returns = pd.to_numeric(
        trades.loc[trades["exit_date"].notna(), "net_return_pct"], errors="coerce"
    ).dropna()
    if returns.empty:
        result = _empty_metrics()
        result["trades"] = int(len(trades))
        return result
    positive = returns.loc[returns.gt(0.0)]
    negative = returns.loc[returns.lt(0.0)]
    gross_profit = float(positive.sum())
    gross_loss = float(-negative.sum())
    equity = pd.concat(
        [pd.Series([1.0]), (1.0 + returns / 100.0).cumprod()],
        ignore_index=True,
    )
    drawdown = equity / equity.cummax() - 1.0
    return {
        "trades": int(len(trades)),
        "closed_trades": int(len(returns)),
        "positive_trades": int(returns.gt(0.0).sum()),
        "positive_rate_pct": float(returns.gt(0.0).mean() * 100.0),
        "mean_net_return_pct": float(returns.mean()),
        "median_net_return_pct": float(returns.median()),
        "profit_factor": (
            gross_profit / gross_loss
            if gross_loss > 0
            else math.inf
            if gross_profit > 0
            else None
        ),
        "compound_return_pct": float((equity.iloc[-1] - 1.0) * 100.0),
        "maximum_drawdown_pct": float(drawdown.min() * 100.0),
        "d1_loss_stops": int(
            trades.get("exit_reason", pd.Series(dtype=str))
            .astype(str)
            .eq("d1_loss_stop")
            .sum()
        ),
    }


def _build_campaign_signal_records(
    path: pd.DataFrame,
    *,
    support_match_mode: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    campaign_id = str(path["campaign_id"].iat[0])
    vt_symbol = str(path["vt_symbol"].iat[0])
    trade_dates = path["trade_date"].to_numpy()
    high_prices = path["high_price"].to_numpy(dtype=float)
    low_prices = path["low_price"].to_numpy(dtype=float)
    close_prices = path["close_price"].to_numpy(dtype=float)
    daily_returns = path["daily_return_pct"].to_numpy(dtype=float)
    prior_highs = path["prior_high20"].to_numpy(dtype=float)
    volume_ratios = path["volume_ratio_prior5"].to_numpy(dtype=float)
    ma5 = path["ma5"].to_numpy(dtype=float)
    ma10 = path["ma10"].to_numpy(dtype=float)
    ma20 = path["ma20"].to_numpy(dtype=float)
    close_locations = path["close_location"].to_numpy(dtype=float)
    campaign_active = path["campaign_active"].to_numpy()
    dynamic_top3 = path["dynamic_top3"].to_numpy()
    dynamic_ranks = path["dynamic_rank"].to_numpy()
    structure_intact = path["structure_intact"].to_numpy()
    if "leader_leg_start_today" in path:
        leader_leg_start = path["leader_leg_start_today"].to_numpy()
    else:
        leader_leg_start = np.zeros(len(path), dtype=bool)
    support_values = {"ma5": ma5, "ma10": ma10, "ma20": ma20}

    state = "waiting_ignition"
    wave_number = 0
    leg_number = 0
    peak_price: float | None = None
    peak_date: pd.Timestamp | None = None
    deepest_tested_depth = 0
    running_pullback_low: float | None = None
    support_information_version = 0
    emitted_information_version = 0
    latest_support_test_date: pd.Timestamp | None = None
    latest_support_test_position: int | None = None
    rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []

    for position in range(len(path)):
        candidate_line: str | None = None
        required_line: str | None = None
        confirmation_status = "not_in_pullback"
        signal_emitted_today = False
        trade_date = pd.Timestamp(trade_dates[position])
        ignition = bool(leader_leg_start[position]) or bool(
            daily_returns[position] >= IGNITION_RETURN_PCT
            and close_prices[position] > prior_highs[position]
            and volume_ratios[position] >= IGNITION_VOLUME_RATIO
        )
        higher_high = False
        if state in {"waiting_ignition", "terminated"}:
            if ignition and bool(campaign_active[position]):
                state = "advancing"
                wave_number = 1
                leg_number += 1
                peak_price = high_prices[position]
                peak_date = trade_date
                deepest_tested_depth = 0
                running_pullback_low = None
                support_information_version = 0
                emitted_information_version = 0
                latest_support_test_date = None
                latest_support_test_position = None
        elif peak_price is not None and high_prices[position] > peak_price:
            higher_high = state == "pullback"
            if higher_high:
                wave_number += 1
                deepest_tested_depth = 0
                running_pullback_low = None
                support_information_version = 0
                emitted_information_version = 0
                latest_support_test_date = None
                latest_support_test_position = None
            state = "advancing"
            peak_price = high_prices[position]
            peak_date = trade_date

        if state in {"advancing", "pullback"}:
            if not bool(campaign_active[position]) or not bool(
                structure_intact[position]
            ):
                state = "terminated"
            elif (
                peak_price is not None
                and trade_date > pd.Timestamp(peak_date)
                and low_prices[position] <= peak_price * (1.0 - PULLBACK_PCT / 100.0)
            ):
                state = "pullback"

        support = None
        if state == "pullback":
            support = _deepest_support_test_values(
                low_prices[position],
                ma5[position],
                ma10[position],
                ma20[position],
            )
            low_price = low_prices[position]
            new_pullback_low = (
                running_pullback_low is None or low_price < running_pullback_low
            )
            if new_pullback_low:
                running_pullback_low = low_price
            if support is not None:
                observed_depth = SUPPORT_DEPTH[support]
                depth_increased = observed_depth > deepest_tested_depth
                deepest_tested_depth = max(deepest_tested_depth, observed_depth)
            else:
                depth_increased = False
            if new_pullback_low or depth_increased:
                support_information_version += 1
                latest_support_test_date = trade_date
                latest_support_test_position = position
            candidate_line = _support_for_depth(deepest_tested_depth)
            required_line = "ma5" if wave_number == 1 else "ma10"
            required_depth = SUPPORT_DEPTH[required_line]
            confirmation_status = _pullback_confirmation_status(
                required_support_tested=(
                    candidate_line is not None
                    and _support_depth_matches(
                        deepest_tested_depth,
                        required_depth,
                        support_match_mode,
                    )
                ),
                new_support_information=(
                    support_information_version > emitted_information_version
                ),
                after_support_test=(
                    latest_support_test_date is not None
                    and latest_support_test_position is not None
                    and trade_date > latest_support_test_date
                ),
                dynamic_top3=bool(dynamic_top3[position]),
                structure_intact=bool(structure_intact[position]),
                support_held=(
                    candidate_line is not None
                    and close_prices[position]
                    >= support_values[candidate_line][position]
                ),
                price_action_confirmed=(
                    position > 0
                    and (
                        close_prices[position] > close_prices[position - 1]
                        or close_locations[position] >= 0.5
                    )
                ),
            )
            if confirmation_status == "eligible":
                bar = path.iloc[position]
                rows.append(
                    _signal_row(
                        bar,
                        wave_number=wave_number,
                        leg_number=leg_number,
                        required_support=required_line,
                        support_line=candidate_line,
                        support_test_date=latest_support_test_date,
                        support_test_session_gap=(
                            position - latest_support_test_position
                        ),
                        reference_peak_date=peak_date,
                        reference_peak_price=float(peak_price),
                    )
                )
                emitted_information_version = support_information_version
                confirmation_status = "signal_emitted"
                signal_emitted_today = True

        daily_rows.append(
            {
                "campaign_id": campaign_id,
                "vt_symbol": vt_symbol,
                "trade_date": trade_date,
                "state": state,
                "stock_leg_number": leg_number,
                "wave_number": wave_number,
                "record_high_price": peak_price,
                "record_high_date": peak_date,
                "higher_high_today": higher_high,
                "deepest_tested_support": _support_for_depth(deepest_tested_depth),
                "deepest_tested_depth": deepest_tested_depth,
                "required_support": required_line,
                "latest_support_test_date": latest_support_test_date,
                "support_test_session_gap": (
                    position - latest_support_test_position
                    if latest_support_test_position is not None
                    else None
                ),
                "confirmation_status": confirmation_status,
                "signal_emitted_today": signal_emitted_today,
                "dynamic_rank": _optional_int(dynamic_ranks[position]),
                "dynamic_top3": bool(dynamic_top3[position]),
                "structure_intact": bool(structure_intact[position]),
                "feature_cutoff_date": trade_date,
            }
        )
    return rows, daily_rows


def _support_depth_matches(
    deepest_tested_depth: int,
    required_depth: int,
    support_match_mode: str,
) -> bool:
    if support_match_mode == MINIMUM_REQUIRED_SUPPORT:
        return deepest_tested_depth >= required_depth
    if support_match_mode == EXACT_REQUIRED_SUPPORT:
        return deepest_tested_depth == required_depth
    raise ValueError(f"unsupported support match mode: {support_match_mode}")


def _pullback_confirmation_status(
    *,
    required_support_tested: bool,
    new_support_information: bool,
    after_support_test: bool,
    dynamic_top3: bool,
    structure_intact: bool,
    support_held: bool,
    price_action_confirmed: bool,
) -> str:
    gates = (
        ("required_support_not_tested", required_support_tested),
        ("no_new_support_information", new_support_information),
        ("support_test_day", after_support_test),
        ("not_dynamic_top3", dynamic_top3),
        ("structure_not_intact", structure_intact),
        ("support_not_held", support_held),
        ("price_action_not_confirmed", price_action_confirmed),
    )
    return next((status for status, passed in gates if not passed), "eligible")


def _deepest_support_test_values(
    low_price: float,
    ma5: float,
    ma10: float,
    ma20: float,
) -> str | None:
    deepest: str | None = None
    for line, support in (("ma5", ma5), ("ma10", ma10), ("ma20", ma20)):
        if not np.isfinite(support) or support <= 0:
            continue
        lower = support * (1.0 - SUPPORT_TOLERANCE_PCT / 100.0)
        upper = support * (1.0 + SUPPORT_TOLERANCE_PCT / 100.0)
        if lower <= low_price <= upper:
            deepest = line
    return deepest


def _signal_row(
    bar: pd.Series,
    *,
    wave_number: int,
    leg_number: int,
    required_support: str,
    support_line: str,
    support_test_date: pd.Timestamp,
    support_test_session_gap: int,
    reference_peak_date: pd.Timestamp | None,
    reference_peak_price: float,
) -> dict[str, Any]:
    signal_date = pd.Timestamp(bar["trade_date"])
    volume_ratio = _finite_or_none(bar["volume_ratio_prior5"])
    signal_id = (
        f"{ALGORITHM_VERSION}:{bar['campaign_id']}:{bar['vt_symbol']}:"
        f"{signal_date.date().isoformat()}:{support_line}"
    )
    return {
        "signal_id": signal_id,
        "campaign_id": str(bar["campaign_id"]),
        "sector_id": str(bar["sector_id"]),
        "concept_name": str(bar["concept_name"]),
        "vt_symbol": str(bar["vt_symbol"]),
        "stock_name": str(bar["stock_name"]),
        "signal_date": signal_date,
        "feature_cutoff_date": signal_date,
        "stock_leg_number": leg_number,
        "wave_number": wave_number,
        "required_support": required_support,
        "support_line": support_line,
        "support_depth": SUPPORT_DEPTH[support_line],
        "support_test_date": support_test_date,
        "support_test_session_gap": support_test_session_gap,
        "support_price": float(bar[support_line]),
        "signal_close": float(bar["close_price"]),
        "signal_low": float(bar["low_price"]),
        "signal_daily_return_pct": float(bar["daily_return_pct"]),
        "volume_ratio_prior5": volume_ratio,
        "base_confirmation": True,
        "non_contraction_confirmation": bool(
            volume_ratio is not None and volume_ratio >= NON_CONTRACTION_VOLUME_RATIO
        ),
        "reference_peak_date": reference_peak_date,
        "reference_peak_price": reference_peak_price,
        "dynamic_rank": int(bar["dynamic_rank"]),
        "dynamic_top3": bool(bar["dynamic_top3"]),
    }


def _execute_signal(
    signal: Mapping[str, Any],
    path: pd.DataFrame,
    positions: Mapping[pd.Timestamp, int],
    *,
    round_trip_cost_pct: float,
) -> dict[str, Any]:
    entry_date = pd.Timestamp(signal["signal_date"])
    entry_position = positions.get(entry_date)
    if entry_position is None:
        raise ValueError("signal date has no campaign bar")
    entry_price = float(signal["signal_close"])
    d1_position = entry_position + 1
    if d1_position >= len(path):
        return _censored_trade(signal, entry_price)
    d1 = path.iloc[d1_position]
    d1_return = _net_return(entry_price, float(d1["close_price"]), round_trip_cost_pct)
    if d1_return <= 0:
        exit_row = d1
        exit_reason = "d1_loss_stop"
    else:
        exit_row, exit_reason = _first_winner_exit(
            path.iloc[d1_position:],
            reference_peak=float(signal["reference_peak_price"]),
        )
        if exit_row is None:
            return _censored_trade(
                signal,
                entry_price,
                d1_date=pd.Timestamp(d1["trade_date"]),
                d1_close=float(d1["close_price"]),
                d1_net_return_pct=d1_return,
            )
    exit_date = pd.Timestamp(exit_row["trade_date"])
    exit_price = float(exit_row["close_price"])
    observed = path.iloc[entry_position : positions[exit_date] + 1]
    return {
        **_trade_identity(signal),
        "entry_date": entry_date,
        "entry_price": entry_price,
        "d1_date": pd.Timestamp(d1["trade_date"]),
        "d1_close": float(d1["close_price"]),
        "d1_net_return_pct": d1_return,
        "exit_date": exit_date,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "holding_sessions": int(positions[exit_date] - entry_position),
        "net_return_pct": _net_return(entry_price, exit_price, round_trip_cost_pct),
        "mfe_pct": float((observed["high_price"].max() / entry_price - 1.0) * 100.0),
        "mae_pct": float((observed["low_price"].min() / entry_price - 1.0) * 100.0),
        "round_trip_cost_pct": round_trip_cost_pct,
    }


def _first_winner_exit(
    path: pd.DataFrame,
    *,
    reference_peak: float,
) -> tuple[pd.Series | None, str]:
    for _, bar in path.iterrows():
        if float(bar["high_price"]) > reference_peak:
            return bar, "higher_high_confirmed"
        if not bool(bar["structure_intact"]):
            return bar, "structural_break"
        if not bool(bar["campaign_active"]):
            return bar, "concept_campaign_ended"
    return None, "right_censored"


def _censored_trade(
    signal: Mapping[str, Any],
    entry_price: float,
    *,
    d1_date: pd.Timestamp | None = None,
    d1_close: float | None = None,
    d1_net_return_pct: float | None = None,
) -> dict[str, Any]:
    return {
        **_trade_identity(signal),
        "entry_date": pd.Timestamp(signal["signal_date"]),
        "entry_price": entry_price,
        "d1_date": d1_date,
        "d1_close": d1_close,
        "d1_net_return_pct": d1_net_return_pct,
        "exit_date": pd.NaT,
        "exit_price": None,
        "exit_reason": "right_censored",
        "holding_sessions": None,
        "net_return_pct": None,
        "mfe_pct": None,
        "mae_pct": None,
        "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
    }


def _trade_identity(signal: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "signal_id": str(signal["signal_id"]),
        "campaign_id": str(signal["campaign_id"]),
        "sector_id": str(signal["sector_id"]),
        "vt_symbol": str(signal["vt_symbol"]),
        "wave_number": int(signal["wave_number"]),
        "support_line": str(signal["support_line"]),
        "support_depth": int(signal["support_depth"]),
        "support_test_date": pd.Timestamp(signal["support_test_date"]),
        "dynamic_rank": int(signal["dynamic_rank"]),
    }


def _prepare_campaign_paths(frame: pd.DataFrame) -> pd.DataFrame:
    required = (
        "campaign_id",
        "sector_id",
        "concept_name",
        "vt_symbol",
        "stock_name",
        "trade_date",
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
        "campaign_active",
        "dynamic_rank",
        "dynamic_top3",
        "feature_cutoff_date",
    )
    _require_columns(frame, required, "stock campaign path")
    path = frame.copy()
    for column in ("trade_date", "feature_cutoff_date"):
        path[column] = _normalized_dates(path[column])
    if not path["feature_cutoff_date"].eq(path["trade_date"]).all():
        raise ValueError("campaign feature cutoff must equal trade date")
    identity_columns = ["campaign_id", "vt_symbol"]
    date_identity = [*identity_columns, "trade_date"]
    if path.duplicated(date_identity).any():
        raise ValueError("stock campaign dates must be unique per identity")
    numeric = (
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
    path[list(numeric)] = path[list(numeric)].apply(pd.to_numeric, errors="coerce")
    finite_prices = path[["open_price", "high_price", "low_price", "close_price"]]
    if not np.isfinite(finite_prices.to_numpy(dtype=float)).all():
        raise ValueError("campaign OHLC values must be finite")
    path = path.sort_values(
        [*identity_columns, "trade_date"], kind="stable"
    ).reset_index(drop=True)
    below_ma10 = path["close_price"].lt(path["ma10"])
    previous_below_ma10 = below_ma10.groupby(
        [path[column] for column in identity_columns], sort=False
    ).shift(1, fill_value=False)
    path["structure_intact"] = (
        path["close_price"].ge(path["ma20"])
        & ~(below_ma10 & previous_below_ma10 & path["ma5"].le(path["ma10"]))
    ).fillna(False)
    return path


def _support_for_depth(depth: int) -> str | None:
    return next((line for line, value in SUPPORT_DEPTH.items() if value == depth), None)


def _net_return(entry_price: float, exit_price: float, cost_pct: float) -> float:
    return (exit_price / entry_price - 1.0) * 100.0 - cost_pct


def _empty_metrics() -> dict[str, Any]:
    return {
        "trades": 0,
        "closed_trades": 0,
        "positive_trades": 0,
        "positive_rate_pct": None,
        "mean_net_return_pct": None,
        "median_net_return_pct": None,
        "profit_factor": None,
        "compound_return_pct": None,
        "maximum_drawdown_pct": None,
        "d1_loss_stops": 0,
    }


def _signal_columns() -> list[str]:
    return [
        "signal_id",
        "campaign_id",
        "sector_id",
        "concept_name",
        "vt_symbol",
        "stock_name",
        "signal_date",
        "feature_cutoff_date",
        "stock_leg_number",
        "wave_number",
        "required_support",
        "support_line",
        "support_depth",
        "support_test_date",
        "support_test_session_gap",
        "support_price",
        "signal_close",
        "signal_low",
        "signal_daily_return_pct",
        "volume_ratio_prior5",
        "base_confirmation",
        "non_contraction_confirmation",
        "reference_peak_date",
        "reference_peak_price",
        "dynamic_rank",
        "dynamic_top3",
    ]


def _trade_columns() -> list[str]:
    return [
        "signal_id",
        "campaign_id",
        "sector_id",
        "vt_symbol",
        "wave_number",
        "support_line",
        "support_depth",
        "support_test_date",
        "dynamic_rank",
        "entry_date",
        "entry_price",
        "d1_date",
        "d1_close",
        "d1_net_return_pct",
        "exit_date",
        "exit_price",
        "exit_reason",
        "holding_sessions",
        "net_return_pct",
        "mfe_pct",
        "mae_pct",
        "round_trip_cost_pct",
    ]


def _reject_prohibited_columns(
    frame: pd.DataFrame,
    tokens: Sequence[str],
) -> None:
    prohibited = sorted(
        column
        for column in frame
        if any(token in str(column).lower() for token in tokens)
    )
    if prohibited:
        raise ValueError(f"future or outcome columns are prohibited: {prohibited}")


def _normalized_dates(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="raise").dt.normalize()


def _optional_int(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)


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
