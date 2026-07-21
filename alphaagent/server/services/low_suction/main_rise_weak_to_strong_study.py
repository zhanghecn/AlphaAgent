"""Daily main-rise leader divergence-to-strength research."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd


STUDY_VERSION = "main-rise-weak-to-strong-v6"
CONCEPT_SOURCE = "eastmoney.board_kline"
ROUND_TRIP_COST_PCT = 0.2
BASE_MAIN_RISE_RETURN60_PCT = 15.0
BASE_MAIN_RISE_TOP3_DAYS10 = 3
BASE_MAIN_RISE_NEW_HIGH_DAYS20 = 1
DIAGNOSTIC_RULE_VERSION = "wts-r6020-top4-nh2-vol12-opall"
REFERENCE_SYMBOLS = {
    "002636.SZSE": "Jinan Guoji",
    "002384.SZSE": "Dongshan Precision",
    "600487.SSE": "Hengtong Optic-Electric",
}
LEADER_SCORE_WEIGHTS = {
    "gain60_strength": 0.35,
    "gain20_strength": 0.30,
    "gain10_strength": 0.10,
    "turnover_strength": 0.15,
    "turnover_expansion_strength": 0.10,
}
SIGNAL_FEATURE_COLUMNS = (
    "sector_id",
    "concept_name",
    "trade_date",
    "vt_symbol",
    "stock_name",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "turnover",
    "daily_return_pct",
    "prior_daily_return_pct",
    "return5_pct",
    "return10_pct",
    "return20_pct",
    "return60_pct",
    "ma5",
    "ma10",
    "ma20",
    "ma60",
    "ma10_lag5",
    "ma20_lag5",
    "ma60_lag5",
    "prior_high20",
    "prior_high60",
    "pullback_low4",
    "drawdown_from_prior_high_pct",
    "volume_ratio5",
    "turnover5",
    "turnover_expansion",
    "close_location",
    "body_return_pct",
    "strong_days10",
    "concept_daily_return_pct",
    "concept_prior_daily_return_pct",
    "concept_return5_pct",
    "concept_return10_pct",
    "concept_return20_pct",
    "concept_drawdown20_pct",
    "concept_relative_pct",
    "gain60_strength",
    "gain20_strength",
    "gain10_strength",
    "turnover_strength",
    "turnover_expansion_strength",
    "leader_score",
    "leader_rank",
    "prior_leader_rank",
    "member_count",
    "stock_session_index",
    "top3_days5",
    "top3_days10",
    "new_high_days20",
    "concept_campaign_id",
    "candidate_run_id",
    "main_rise_active",
    "main_rise_start_date",
    "main_rise_active_sessions",
    "main_rise_gain_pct",
    "confirmed_restart_count",
    "pullback_opportunity_ordinal",
    "pullback_duration",
    "episode_pullback_low",
    "weak_to_strong_day",
    "pullback_block_reason",
    "concept_restrength",
    "active_direction",
    "danger_state",
    "support_zone",
)
OUTCOME_COLUMNS = (
    "trade_date",
    "vt_symbol",
    "close_d1",
    "close_d3",
    "close_d5",
    "d1_net_return_pct",
    "d3_net_return_pct",
    "d5_net_return_pct",
)
PROHIBITED_SIGNAL_TOKENS = (
    "close_d1",
    "close_d3",
    "close_d5",
    "d1_",
    "d3_",
    "d5_",
    "future_",
    "outcome_",
    "net_return",
    "profit",
)


@dataclass(frozen=True)
class WeakToStrongRule:
    """Preregistered structural rule selected before the final time block."""

    version: str
    minimum_return60_pct: float
    minimum_top3_days10: int
    minimum_new_high_days20: int
    maximum_volume_ratio: float
    maximum_opportunity_ordinal: int | None = None
    minimum_reversal_return_pct: float = 0.5
    minimum_close_location: float = 0.60
    maximum_reversal_return_pct: float = 8.0
    minimum_drawdown_pct: float = -12.0
    maximum_drawdown_pct: float = -1.0
    minimum_volume_ratio: float = 0.25


@dataclass(frozen=True)
class StudyData:
    features: pd.DataFrame
    outcomes: pd.DataFrame
    coverage: dict[str, Any]
    fingerprints: dict[str, dict[str, Any]]


def candidate_rules() -> tuple[WeakToStrongRule, ...]:
    """Return the complete 32-rule structural grid."""

    rows = []
    for return60 in (20.0, 35.0):
        for top3_days10 in (4, 6):
            for new_high_days20 in (2, 3):
                for maximum_volume_ratio in (0.8, 1.2):
                    for maximum_opportunity in (2, None):
                        opportunity = (
                            str(maximum_opportunity)
                            if maximum_opportunity is not None
                            else "all"
                        )
                        rows.append(
                            WeakToStrongRule(
                                version=(
                                    f"wts-r60{int(return60)}-top{top3_days10}-"
                                    f"nh{new_high_days20}-"
                                    f"vol{int(maximum_volume_ratio * 10)}-"
                                    f"op{opportunity}"
                                ),
                                minimum_return60_pct=return60,
                                minimum_top3_days10=top3_days10,
                                minimum_new_high_days20=new_high_days20,
                                maximum_volume_ratio=maximum_volume_ratio,
                                maximum_opportunity_ordinal=maximum_opportunity,
                            )
                        )
    return tuple(rows)


def rank_dynamic_concept_leaders(member_features: pd.DataFrame) -> pd.DataFrame:
    """Calculate daily concept ranks from trailing gain and turnover only."""

    _reject_outcome_columns(member_features)
    required = (
        "sector_id",
        "trade_date",
        "vt_symbol",
        "return60_pct",
        "return20_pct",
        "return10_pct",
        "turnover5",
        "turnover_expansion",
    )
    _require_columns(member_features, required, "dynamic leader member")
    frame = member_features.copy()
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    if frame.duplicated(["sector_id", "trade_date", "vt_symbol"]).any():
        raise ValueError("dynamic leader member identities must be unique")
    group = [frame["sector_id"], frame["trade_date"]]
    strengths = {
        "gain60_strength": "return60_pct",
        "gain20_strength": "return20_pct",
        "gain10_strength": "return10_pct",
        "turnover_strength": "turnover5",
        "turnover_expansion_strength": "turnover_expansion",
    }
    for output, source in strengths.items():
        values = pd.to_numeric(frame[source], errors="coerce")
        frame[output] = values.groupby(group, sort=False).rank(
            method="average", pct=True
        )
    complete = frame[list(strengths)].notna().all(axis=1)
    frame["leader_score"] = np.nan
    frame.loc[complete, "leader_score"] = sum(
        frame.loc[complete, feature] * weight
        for feature, weight in LEADER_SCORE_WEIGHTS.items()
    )
    frame = frame.sort_values(
        ["sector_id", "trade_date", "leader_score", "turnover5", "vt_symbol"],
        ascending=[True, True, False, False, True],
        kind="stable",
        na_position="last",
    )
    frame["leader_rank"] = (
        frame.loc[complete]
        .groupby(["sector_id", "trade_date"], sort=False)
        .cumcount()
        .add(1)
    )
    frame["member_count"] = frame.groupby(
        ["sector_id", "trade_date"], sort=False
    )["vt_symbol"].transform("nunique")
    frame["is_top3"] = frame["leader_rank"].le(3).fillna(False)
    return frame.sort_values(
        ["trade_date", "sector_id", "leader_rank", "vt_symbol"],
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)


def build_main_rise_path_state(paths: pd.DataFrame) -> pd.DataFrame:
    """Replay causal leader paths and number only higher-high-confirmed pullbacks."""

    _reject_outcome_columns(paths)
    required = (
        "sector_id",
        "concept_campaign_id",
        "candidate_run_id",
        "trade_date",
        "vt_symbol",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "daily_return_pct",
        "return60_pct",
        "top3_days10",
        "new_high_days20",
        "ma5",
        "ma10",
        "ma20",
        "ma60",
    )
    _require_columns(paths, required, "main-rise path")
    frame = paths.copy()
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    identity = [
        "sector_id",
        "concept_campaign_id",
        "candidate_run_id",
        "trade_date",
        "vt_symbol",
    ]
    if frame.duplicated(identity).any():
        raise ValueError("main-rise path identities must be unique")
    numeric = (
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "daily_return_pct",
        "return60_pct",
        "top3_days10",
        "new_high_days20",
        "ma5",
        "ma10",
        "ma20",
        "ma60",
    )
    frame[list(numeric)] = frame[list(numeric)].apply(
        pd.to_numeric, errors="coerce"
    )
    frame = _select_primary_stock_paths(frame)
    group_columns = ["vt_symbol", "candidate_run_id"]
    ordered = frame.sort_values([*group_columns, "trade_date"], kind="stable")
    parts = [
        _replay_main_rise_group(group)
        for _, group in ordered.groupby(group_columns, sort=False, dropna=False)
    ]
    result = pd.concat(parts, ignore_index=True) if parts else ordered.copy()
    if {
        "concept_daily_return_pct",
        "concept_prior_daily_return_pct",
    }.issubset(result.columns):
        concept_return = pd.to_numeric(
            result["concept_daily_return_pct"], errors="coerce"
        )
        prior_concept_return = pd.to_numeric(
            result["concept_prior_daily_return_pct"], errors="coerce"
        )
        result["concept_restrength"] = (
            concept_return.gt(0.0) & concept_return.gt(prior_concept_return)
        ).fillna(False)
    else:
        result["concept_restrength"] = False
    result["support_zone"] = [
        classify_support_zone(low, ma5=ma5, ma10=ma10, ma20=ma20)
        if pd.notna(low)
        else "unavailable"
        for low, ma5, ma10, ma20 in zip(
            result["episode_pullback_low"],
            result["ma5"],
            result["ma10"],
            result["ma20"],
            strict=True,
        )
    ]
    sort_columns = ["trade_date", "sector_id"]
    if "leader_rank" in result.columns:
        sort_columns.append("leader_rank")
    sort_columns.append("vt_symbol")
    return result.sort_values(
        sort_columns,
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)


def _select_primary_stock_paths(frame: pd.DataFrame) -> pd.DataFrame:
    ranked = frame.copy()
    defaults = {
        "leader_rank": math.inf,
        "top3_days5": 0,
        "leader_score": -math.inf,
        "concept_relative_pct": -math.inf,
    }
    for column, default in defaults.items():
        if column not in ranked.columns:
            ranked[column] = default
    ranked = ranked.sort_values(
        [
            "vt_symbol",
            "trade_date",
            "leader_rank",
            "top3_days5",
            "leader_score",
            "concept_relative_pct",
            "sector_id",
        ],
        ascending=[True, True, True, False, False, False, True],
        kind="stable",
    ).drop_duplicates(["vt_symbol", "trade_date"], keep="first")
    ranked = ranked.sort_values(["vt_symbol", "trade_date"], kind="stable")
    if "stock_session_index" in ranked.columns:
        session_index = pd.to_numeric(
            ranked["stock_session_index"], errors="coerce"
        )
        gap = session_index.groupby(ranked["vt_symbol"], sort=False).diff().ne(1)
        ranked["candidate_run_id"] = gap.groupby(
            ranked["vt_symbol"], sort=False
        ).cumsum().astype(int)
    return ranked.reset_index(drop=True)


def _replay_main_rise_group(group: pd.DataFrame) -> pd.DataFrame:
    rows = group.sort_values("trade_date", kind="stable").to_dict("records")
    activated = False
    active_sessions = 0
    start_date: pd.Timestamp | None = None
    start_close: float | None = None
    reference_high: float | None = None
    confirmed_restarts = 0
    awaiting_higher_high = False
    in_pullback = False
    blocked_pullback = False
    pullback_ordinal: int | None = None
    pullback_duration = 0
    pullback_low: float | None = None
    previous_close: float | None = None
    records: list[dict[str, Any]] = []

    for row in rows:
        close_price = float(row["close_price"])
        high_price = float(row["high_price"])
        low_price = float(row["low_price"])
        daily_return = float(row["daily_return_pct"])
        qualifies = bool(
            float(row["return60_pct"]) >= BASE_MAIN_RISE_RETURN60_PCT
            and float(row["top3_days10"]) >= BASE_MAIN_RISE_TOP3_DAYS10
            and float(row["new_high_days20"]) >= BASE_MAIN_RISE_NEW_HIGH_DAYS20
        )
        if not activated and qualifies:
            activated = True
            start_date = pd.Timestamp(row["trade_date"])
            start_close = close_price
            reference_high = high_price

        weak_to_strong = False
        block_reason: str | None = None
        row_ordinal: int | None = None
        row_duration = 0
        row_pullback_low: float | None = None
        if activated:
            active_sessions += 1
            if reference_high is None:
                reference_high = high_price
            elif high_price > reference_high:
                if awaiting_higher_high:
                    confirmed_restarts += 1
                    awaiting_higher_high = False
                reference_high = high_price

            if in_pullback:
                pullback_duration += 1
                pullback_low = min(float(pullback_low), low_price)
                row_duration = pullback_duration
                row_pullback_low = pullback_low
                if blocked_pullback:
                    block_reason = "prior_restart_not_confirmed"
                else:
                    row_ordinal = pullback_ordinal
                if (
                    daily_return > 0.0
                    and previous_close is not None
                    and close_price > previous_close
                ):
                    if not blocked_pullback:
                        weak_to_strong = True
                        awaiting_higher_high = True
                    in_pullback = False
                    blocked_pullback = False
                    pullback_ordinal = None
                    pullback_duration = 0
                    pullback_low = None
            elif daily_return < 0.0:
                in_pullback = True
                pullback_duration = 1
                pullback_low = low_price
                row_duration = 1
                row_pullback_low = low_price
                if awaiting_higher_high:
                    blocked_pullback = True
                    block_reason = "prior_restart_not_confirmed"
                else:
                    blocked_pullback = False
                    pullback_ordinal = confirmed_restarts + 1
                    row_ordinal = pullback_ordinal

        row.update(
            {
                "main_rise_active": activated,
                "main_rise_start_date": start_date,
                "main_rise_active_sessions": active_sessions if activated else 0,
                "main_rise_gain_pct": (
                    (close_price / start_close - 1.0) * 100.0
                    if activated and start_close
                    else None
                ),
                "confirmed_restart_count": confirmed_restarts,
                "pullback_opportunity_ordinal": row_ordinal,
                "pullback_duration": row_duration,
                "episode_pullback_low": row_pullback_low,
                "weak_to_strong_day": weak_to_strong,
                "pullback_block_reason": block_reason,
            }
        )
        records.append(row)
        previous_close = close_price
    return pd.DataFrame.from_records(records)


def classify_support_zone(
    pullback_low: float,
    *,
    ma5: float,
    ma10: float,
    ma20: float,
) -> str:
    """Describe the deepest four-session support test with fixed tolerances."""

    values = (pullback_low, ma5, ma10, ma20)
    if not all(math.isfinite(float(value)) and float(value) > 0 for value in values):
        return "unavailable"
    if pullback_low >= ma5 * 0.98:
        return "ma5"
    if pullback_low >= ma10 * 0.97:
        return "ma10"
    if pullback_low >= ma20 * 0.97:
        return "ma20"
    return "below_ma20"


def assign_chronological_blocks(
    features: pd.DataFrame,
    *,
    block_count: int = 5,
) -> pd.DataFrame:
    """Assign blocks from the full broad signal-date denominator."""

    if block_count < 2:
        raise ValueError("at least two chronological blocks are required")
    _require_columns(features, ("trade_date",), "signal feature")
    frame = features.copy()
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    dates = tuple(sorted(frame["trade_date"].dropna().unique()))
    if len(dates) < block_count:
        raise ValueError("signal dates cannot fill every chronological block")
    labels = {
        value: min(block_count, int(index * block_count / len(dates)) + 1)
        for index, value in enumerate(dates)
    }
    frame["block"] = frame["trade_date"].map(labels).astype(int)
    return frame


def select_rule_signals(
    features: pd.DataFrame,
    rule: WeakToStrongRule,
) -> pd.DataFrame:
    """Apply one close-known rule and deduplicate stock/date concept aliases."""

    _reject_outcome_columns(features)
    required = (
        *SIGNAL_FEATURE_COLUMNS,
        "block",
    )
    _require_columns(features, required, "weak-to-strong feature")
    frame = features.copy()
    numeric = (
        "close_price",
        "ma5",
        "ma10",
        "ma20",
        "ma60",
        "episode_pullback_low",
        "daily_return_pct",
        "return20_pct",
        "return60_pct",
        "drawdown_from_prior_high_pct",
        "volume_ratio5",
        "close_location",
        "concept_daily_return_pct",
        "leader_rank",
        "member_count",
        "top3_days10",
        "new_high_days20",
        "main_rise_active_sessions",
        "confirmed_restart_count",
        "pullback_opportunity_ordinal",
        "pullback_duration",
    )
    frame[list(numeric)] = frame[list(numeric)].apply(
        pd.to_numeric, errors="coerce"
    )
    first_support = (
        frame["pullback_opportunity_ordinal"].eq(1)
        & frame["support_zone"].eq("ma5")
        & frame["close_price"].ge(frame["ma5"])
    )
    later_support = (
        frame["pullback_opportunity_ordinal"].ge(2)
        & frame["support_zone"].isin(("ma5", "ma10"))
        & frame["close_price"].ge(frame["ma10"])
    )
    opportunity_allowed = frame["pullback_opportunity_ordinal"].ge(1)
    if rule.maximum_opportunity_ordinal is not None:
        opportunity_allowed &= frame["pullback_opportunity_ordinal"].le(
            rule.maximum_opportunity_ordinal
        )
    selected = frame.loc[
        frame["leader_rank"].le(3)
        & frame["member_count"].ge(5)
        & frame["active_direction"].eq("GOLD")
        & frame["danger_state"].ne("DANGER")
        & frame["main_rise_active"].astype(bool)
        & frame["weak_to_strong_day"].astype(bool)
        & frame["pullback_block_reason"].isna()
        & frame["main_rise_active_sessions"].ge(2)
        & frame["return60_pct"].ge(rule.minimum_return60_pct)
        & frame["top3_days10"].ge(rule.minimum_top3_days10)
        & frame["new_high_days20"].ge(rule.minimum_new_high_days20)
        & frame["drawdown_from_prior_high_pct"].between(
            rule.minimum_drawdown_pct,
            rule.maximum_drawdown_pct,
        )
        & frame["daily_return_pct"].between(
            rule.minimum_reversal_return_pct,
            rule.maximum_reversal_return_pct,
        )
        & frame["close_location"].ge(rule.minimum_close_location)
        & frame["volume_ratio5"].between(
            rule.minimum_volume_ratio,
            rule.maximum_volume_ratio,
        )
        & frame["pullback_duration"].between(2, 5)
        & frame["concept_restrength"].astype(bool)
        & opportunity_allowed
        & (first_support | later_support)
    ].copy()
    selected = selected.sort_values(
        [
            "trade_date",
            "vt_symbol",
            "leader_rank",
            "concept_relative_pct",
            "leader_score",
            "sector_id",
        ],
        ascending=[True, True, True, False, False, True],
        kind="stable",
    ).drop_duplicates(["trade_date", "vt_symbol"], keep="first")
    selected["rule_version"] = rule.version
    selected["signal_id"] = (
        selected["trade_date"].dt.strftime("%Y-%m-%d")
        + ":"
        + selected["vt_symbol"].astype(str)
    )
    if selected["signal_id"].duplicated().any():
        raise ValueError("weak-to-strong signal identities must be unique")
    return selected.reset_index(drop=True)


def attach_close_outcomes(
    signals: pd.DataFrame,
    outcomes: pd.DataFrame,
) -> pd.DataFrame:
    """Attach future closes only after the causal signal frame is frozen."""

    _reject_outcome_columns(signals)
    _require_columns(signals, ("trade_date", "vt_symbol"), "frozen signal")
    _require_columns(outcomes, OUTCOME_COLUMNS, "close outcome")
    right = outcomes.copy()
    right["trade_date"] = pd.to_datetime(
        right["trade_date"], errors="raise"
    ).dt.normalize()
    if right.duplicated(["trade_date", "vt_symbol"]).any():
        raise ValueError("close outcome identities must be unique")
    result = signals.merge(
        right,
        on=["trade_date", "vt_symbol"],
        how="left",
        validate="one_to_one",
    )
    return result


def summarize_returns(
    trades: pd.DataFrame,
    *,
    return_column: str = "d1_net_return_pct",
) -> dict[str, Any]:
    """Calculate transparent overlap-ignored trade metrics."""

    _require_columns(trades, (return_column,), "trade return")
    values = pd.to_numeric(trades[return_column], errors="coerce").dropna()
    if values.empty:
        return _empty_metrics()
    gains = float(values.loc[values.gt(0)].sum())
    losses = abs(float(values.loc[values.lt(0)].sum()))
    equity = (1.0 + values / 100.0).cumprod()
    drawdown = (equity / equity.cummax() - 1.0) * 100.0
    return {
        "closed_trades": int(len(values)),
        "positive_rate_pct": float(values.gt(0).mean() * 100.0),
        "mean_return_pct": float(values.mean()),
        "median_return_pct": float(values.median()),
        "profit_factor": (
            gains / losses if losses > 0 else (math.inf if gains > 0 else None)
        ),
        "compound_return_pct": float((equity.iloc[-1] - 1.0) * 100.0),
        "maximum_drawdown_pct": float(drawdown.min()),
    }


def evaluate_rule_grid(
    features: pd.DataFrame,
    outcomes: pd.DataFrame,
    *,
    rules: Sequence[WeakToStrongRule] | None = None,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Evaluate development and validation only; block 5 remains unread here."""

    selected_rules = tuple(rules or candidate_rules())
    records = []
    signals_by_rule: dict[str, pd.DataFrame] = {}
    for rule in selected_rules:
        signals = select_rule_signals(features, rule)
        signals_by_rule[rule.version] = signals
        trades = attach_close_outcomes(signals, outcomes)
        development = trades.loc[trades["block"].isin((1, 2, 3))]
        validation = trades.loc[trades["block"].eq(4)]
        dev = summarize_returns(development)
        val = summarize_returns(validation)
        qualified = _selection_gates_pass(dev, val)
        records.append(
            {
                **asdict(rule),
                **{f"development_{key}": value for key, value in dev.items()},
                **{f"validation_{key}": value for key, value in val.items()},
                "selection_qualified": qualified,
            }
        )
    return pd.DataFrame.from_records(records), signals_by_rule


def choose_rule(grid: pd.DataFrame) -> WeakToStrongRule | None:
    """Select by block-4 mean after all development and validation gates pass."""

    _require_columns(
        grid,
        (
            "version",
            "selection_qualified",
            "validation_mean_return_pct",
            "validation_profit_factor",
            "development_mean_return_pct",
        ),
        "rule grid",
    )
    qualified = grid.loc[grid["selection_qualified"].astype(bool)].copy()
    if qualified.empty:
        return None
    selected = qualified.sort_values(
        [
            "validation_mean_return_pct",
            "validation_profit_factor",
            "development_mean_return_pct",
            "version",
        ],
        ascending=[False, False, False, True],
        kind="stable",
    ).iloc[0]
    values = {
        field: selected[field]
        for field in WeakToStrongRule.__dataclass_fields__
    }
    maximum_opportunity = values["maximum_opportunity_ordinal"]
    values["maximum_opportunity_ordinal"] = (
        None if pd.isna(maximum_opportunity) else int(maximum_opportunity)
    )
    values["minimum_top3_days10"] = int(values["minimum_top3_days10"])
    values["minimum_new_high_days20"] = int(values["minimum_new_high_days20"])
    return WeakToStrongRule(**values)


def final_rule_metrics(trades: pd.DataFrame) -> pd.DataFrame:
    """Report the frozen rule pooled and by the five original blocks."""

    rows = [{"segment": "all", **summarize_returns(trades)}]
    for block in range(1, 6):
        rows.append(
            {
                "segment": f"block_{block}",
                **summarize_returns(trades.loc[trades["block"].eq(block)]),
            }
        )
    for horizon in (3, 5):
        rows.append(
            {
                "segment": f"all_d{horizon}",
                **summarize_returns(
                    trades,
                    return_column=f"d{horizon}_net_return_pct",
                ),
            }
        )
    return pd.DataFrame.from_records(rows)


def final_gates(metrics: pd.DataFrame) -> tuple[bool, list[str]]:
    """Apply the repository's strict historical qualification gates."""

    frame = metrics.set_index("segment", drop=False)
    failures = []
    all_row = _metric_row(frame, "all")
    block4 = _metric_row(frame, "block_4")
    block5 = _metric_row(frame, "block_5")
    checks = (
        (all_row.get("closed_trades", 0) >= 100, "pooled_trades_below_100"),
        (block4.get("closed_trades", 0) >= 30, "block4_trades_below_30"),
        (block5.get("closed_trades", 0) >= 30, "block5_trades_below_30"),
        (
            _finite_or_zero(all_row.get("positive_rate_pct")) > 60.0,
            "pooled_win_rate_not_above_60",
        ),
        (_finite_or_zero(all_row.get("mean_return_pct")) > 0.0, "pooled_mean_not_positive"),
        (_finite_or_zero(all_row.get("profit_factor")) >= 1.20, "pooled_pf_below_1_20"),
        (
            _finite_or_zero(all_row.get("compound_return_pct")) > 60.0,
            "pooled_compound_not_above_60",
        ),
        (
            _finite_or_zero(block4.get("positive_rate_pct")) > 60.0,
            "block4_win_rate_not_above_60",
        ),
        (_finite_or_zero(block4.get("mean_return_pct")) > 0.0, "block4_mean_not_positive"),
        (_finite_or_zero(block4.get("profit_factor")) > 1.0, "block4_pf_not_above_1"),
        (
            _finite_or_zero(block4.get("compound_return_pct")) > 0.0,
            "block4_compound_not_positive",
        ),
        (
            _finite_or_zero(block5.get("positive_rate_pct")) > 60.0,
            "block5_win_rate_not_above_60",
        ),
        (_finite_or_zero(block5.get("mean_return_pct")) > 0.0, "block5_mean_not_positive"),
        (_finite_or_zero(block5.get("profit_factor")) > 1.0, "block5_pf_not_above_1"),
        (
            _finite_or_zero(block5.get("compound_return_pct")) > 0.0,
            "block5_compound_not_positive",
        ),
        (
            _finite_or(all_row.get("maximum_drawdown_pct"), -100.0) >= -10.0,
            "overlap_ignored_drawdown_below_minus_10",
        ),
    )
    failures.extend(reason for passed, reason in checks if not passed)
    return not failures, failures


def load_study_data() -> StudyData:
    """Load the SQL-ranked broad GOLD panel and quarantine future outcomes."""

    from sqlalchemy import select, text

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine, session_scope

    from .contracts import CONCEPT_SECTOR_TYPES
    from .dynamic_concept_campaign_study import filter_exploratory_concept_universe
    from .event_recognition_falsification import build_exact_reason_relations
    from .research_protocol import fingerprint_frame

    engine = get_engine()
    with session_scope() as session:
        sector_rows = session.execute(
            select(schema.sectors.c.id, schema.sectors.c.name).where(
                schema.sectors.c.type.in_(CONCEPT_SECTOR_TYPES)
            )
        ).all()
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
    concepts = pd.DataFrame.from_records(
        sector_rows, columns=["sector_id", "concept_name"]
    )
    filtered_concepts, universe_audit = filter_exploratory_concept_universe(
        concepts
    )
    events = _normalize_event_rows(event_rows)
    relations = build_exact_reason_relations(events, filtered_concepts)
    eligible_ids = tuple(sorted(relations["sector_id"].astype(str).unique()))
    if not eligible_ids:
        raise ValueError("no narrative concepts have exact historical reason evidence")
    raw = pd.read_sql(
        text(_BROAD_LEADER_QUERY),
        engine,
        params={"sector_ids": list(eligible_ids)},
        parse_dates=["trade_date"],
    )
    if raw.empty:
        raise ValueError("broad GOLD dynamic leader panel is empty")
    _require_columns(raw, OUTCOME_COLUMNS[2:], "SQL outcome panel")
    path_inputs = raw.drop(columns=list(OUTCOME_COLUMNS[2:]), errors="raise")
    state = build_main_rise_path_state(path_inputs)
    _require_columns(state, SIGNAL_FEATURE_COLUMNS, "causal main-rise panel")
    features = assign_chronological_blocks(state.loc[:, list(SIGNAL_FEATURE_COLUMNS)])
    outcomes = raw.loc[:, list(OUTCOME_COLUMNS)].drop_duplicates(
        ["trade_date", "vt_symbol"], keep="first"
    )
    fingerprints = {
        "eligible_reason_relations": fingerprint_frame(
            relations,
            identity_columns=("source_date", "sector_id", "vt_symbol"),
        ).as_dict(),
        "broad_gold_leader_features": fingerprint_frame(
            features,
            identity_columns=("trade_date", "sector_id", "vt_symbol"),
        ).as_dict(),
        "close_outcomes": fingerprint_frame(
            outcomes,
            identity_columns=("trade_date", "vt_symbol"),
        ).as_dict(),
    }
    coverage = {
        **universe_audit,
        "raw_limit_event_rows": int(len(events)),
        "exact_reason_relation_rows": int(len(relations)),
        "eligible_concepts": int(len(eligible_ids)),
        "broad_feature_rows": int(len(features)),
        "broad_stock_dates": int(
            features[["trade_date", "vt_symbol"]].drop_duplicates().shape[0]
        ),
        "broad_symbols": int(features["vt_symbol"].nunique()),
        "broad_dates": int(features["trade_date"].nunique()),
        "feature_start": features["trade_date"].min().date().isoformat(),
        "feature_end": features["trade_date"].max().date().isoformat(),
        "membership_mode": "current_proxy",
        "timing_mode": "D_minus_1_close_GOLD",
        "minute_rows_read": 0,
        "fund_flow_rows_read": 0,
    }
    return StudyData(features, outcomes, coverage, fingerprints)


def run_main_rise_weak_to_strong_study() -> dict[str, Any]:
    """Run selection, final-block evaluation, case audit, and reporting."""

    data = load_study_data()
    grid, signals_by_rule = evaluate_rule_grid(data.features, data.outcomes)
    selected = choose_rule(grid)
    if selected is None:
        diagnostics = _build_failure_diagnostics(
            signals_by_rule,
            data.outcomes,
        )
        return build_report(
            coverage=data.coverage,
            fingerprints=data.fingerprints,
            grid=grid,
            selected_rule=None,
            trades=pd.DataFrame(),
            metrics=pd.DataFrame(),
            qualified=False,
            failed_gates=["no_rule_passed_development_and_block4_selection_gates"],
            cases=_case_audit(data.features, data.outcomes, None),
            outcome_profiles=pd.DataFrame(),
            failure_diagnostics=diagnostics,
        )
    signals = signals_by_rule[selected.version]
    trades = attach_close_outcomes(signals, data.outcomes).sort_values(
        ["trade_date", "vt_symbol"], kind="stable"
    )
    metrics = final_rule_metrics(trades)
    qualified, failed_gates = final_gates(metrics)
    return build_report(
        coverage=data.coverage,
        fingerprints=data.fingerprints,
        grid=grid,
        selected_rule=selected,
        trades=trades,
        metrics=metrics,
        qualified=qualified,
        failed_gates=failed_gates,
        cases=_case_audit(data.features, data.outcomes, selected),
        outcome_profiles=_outcome_profiles(trades),
        failure_diagnostics={},
    )


def build_report(
    *,
    coverage: Mapping[str, Any],
    fingerprints: Mapping[str, Any],
    grid: pd.DataFrame,
    selected_rule: WeakToStrongRule | None,
    trades: pd.DataFrame,
    metrics: pd.DataFrame,
    qualified: bool,
    failed_gates: Sequence[str],
    cases: pd.DataFrame,
    outcome_profiles: pd.DataFrame,
    failure_diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build complete evidence; a research rule is not a live fill contract."""

    return _json_safe(
        {
            "study_version": STUDY_VERSION,
            "research_status": (
                "frozen_rule_passed_reused_history_gates"
                if qualified
                else "no_rule_cleared_all_gates"
            ),
            "research_rule_frozen": selected_rule is not None,
            "historical_gates_passed": qualified,
            "production_ready": False,
            "formal_metrics": None,
            "failed_gates": list(failed_gates),
            "contract": {
                "universe": "main_board_non_ST_current_membership_proxy",
                "concept_denominator": "concept_names_seen_in_exact_limit_reasons",
                "concept_state": (
                    "close>=ma20; ma10>ma20; both rising; 20d gain>=3%; "
                    "within 8% of 20d high; relative 10d percentile>=60%"
                ),
                "stock_main_rise_state": (
                    "close>=ma20; ma20>ma60; both rising; trailing Top3 persistence; "
                    "prior 60d-high advances; causal restart sequence"
                ),
                "leader_rank": {
                    "scope": "each concept and completed close",
                    "top_n": 3,
                    "weights": LEADER_SCORE_WEIGHTS,
                },
                "market_state_known_at": "D-1 close",
                "market_state": "GOLD",
                "entry": "D completed close research proxy",
                "primary_exit": "D+1 completed close",
                "sensitivity_exits": ["D+3 completed close", "D+5 completed close"],
                "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
                "candidate_rules": len(candidate_rules()),
                "selection_blocks": [1, 2, 3, 4],
                "final_evaluation_block": 5,
            },
            "selected_rule": asdict(selected_rule) if selected_rule else None,
            "coverage": dict(coverage),
            "metrics": _records(metrics),
            "rule_grid": _records(grid),
            "outcome_profiles": _records(outcome_profiles),
            "failure_diagnostics": dict(failure_diagnostics or {}),
            "reference_cases": _records(cases),
            "trades": _records(trades),
            "fingerprints": dict(fingerprints),
            "boundaries": [
                "all five dates blocks come from history that has been examined in earlier research",
                "current concept memberships create survivorship and historical-membership bias",
                "D-close entry is a research proxy and is not an executable post-close fill",
                "compound return and drawdown ignore overlapping simultaneous signals",
                "the frozen rule requires a new forward block before live or paper promotion",
            ],
            "reproduce": (
                "python -m alphaagent.server.services.low_suction.cli "
                "v2-main-rise-weak-to-strong-study --format markdown"
            ),
        }
    )


def render_main_rise_weak_to_strong_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)), ensure_ascii=False, indent=2, sort_keys=True
    )


def render_main_rise_weak_to_strong_markdown(report: Mapping[str, Any]) -> str:
    """Render the decision, block evidence, cases, and exact failed gates."""

    coverage = _mapping(report.get("coverage"))
    rule = _mapping(report.get("selected_rule"))
    lines = [
        "# AlphaAgent Main-Rise Weak-To-Strong Low-Suction Study",
        "",
        f"Research status: `{report.get('research_status')}`.",
        f"Historical gates passed: `{str(bool(report.get('historical_gates_passed'))).lower()}`; production ready: `false`.",
        "",
        "## Coverage",
        "",
        f"- Eligible concepts: `{coverage.get('eligible_concepts', 0)}`; broad feature rows: `{coverage.get('broad_feature_rows', 0)}`.",
        f"- Stock/date rows: `{coverage.get('broad_stock_dates', 0)}`; symbols: `{coverage.get('broad_symbols', 0)}`; dates: `{coverage.get('broad_dates', 0)}`.",
        f"- Range: `{coverage.get('feature_start')}` to `{coverage.get('feature_end')}`; membership: `{coverage.get('membership_mode')}`.",
        "",
        "## Frozen Rule",
        "",
    ]
    if rule:
        lines.extend(
            [
                f"- Version: `{rule.get('version')}`.",
                f"- Reversal return: `{_number(rule.get('minimum_reversal_return_pct'))}%` to `{_number(rule.get('maximum_reversal_return_pct'))}%`.",
                f"- 60-day gain minimum: `{_number(rule.get('minimum_return60_pct'))}%`; Top3 days in 10 minimum: `{rule.get('minimum_top3_days10')}`.",
                f"- Prior 60-day-high advances in 20 sessions minimum: `{rule.get('minimum_new_high_days20')}`; volume ratio maximum: `{_number(rule.get('maximum_volume_ratio'))}`.",
                f"- Maximum opportunity ordinal: `{rule.get('maximum_opportunity_ordinal') or 'all confirmed'}`. Opportunity 1 must hold/reclaim MA5; later opportunities require a prior higher high and must hold/reclaim MA5 or MA10.",
            ]
        )
    else:
        lines.append("- No candidate passed the development and block-4 gates.")
    failed = list(report.get("failed_gates") or [])
    if failed:
        lines.extend(["", "Failed gates: " + ", ".join(f"`{item}`" for item in failed) + "."])
    lines.extend(
        [
            "",
            "## D+1 Evidence",
            "",
            "| Segment | N | Positive | Mean | Median | PF | Compound | Drawdown |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report.get("metrics") or []:
        if str(row.get("segment", "")).startswith("all_d"):
            continue
        lines.append(
            f"| `{row.get('segment')}` | {row.get('closed_trades', 0)} | "
            f"{_percent(row.get('positive_rate_pct'))} | {_percent(row.get('mean_return_pct'))} | "
            f"{_percent(row.get('median_return_pct'))} | {_number(row.get('profit_factor'))} | "
            f"{_percent(row.get('compound_return_pct'))} | {_percent(row.get('maximum_drawdown_pct'))} |"
        )
    diagnostics = _mapping(report.get("failure_diagnostics"))
    if diagnostics:
        lines.extend(
            [
                "",
                "## Failure Diagnostics",
                "",
                f"Denominator rule: `{diagnostics.get('denominator_rule_version')}`; holdout block evaluated: `{str(bool(diagnostics.get('holdout_block_evaluated'))).lower()}`.",
                "",
                "| Grouping | Group | N | Positive | Mean | PF |",
                "| --- | --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for key, label in (
            ("by_block", "block"),
            ("by_opportunity", "opportunity"),
            ("by_support", "support"),
        ):
            for row in diagnostics.get(key) or []:
                lines.append(
                    f"| {label} | `{row.get('group')}` | {row.get('closed_trades', 0)} | "
                    f"{_percent(row.get('positive_rate_pct'))} | "
                    f"{_percent(row.get('mean_return_pct'))} | "
                    f"{_number(row.get('profit_factor'))} |"
                )
    lines.extend(
        [
            "",
            "## Reference Cases",
            "",
            "| Date | Stock | Concept | Rank | Support | D return | D+1 | Selected | Reason |",
            "| --- | --- | --- | ---: | --- | ---: | ---: | --- | --- |",
        ]
    )
    for row in report.get("reference_cases") or []:
        lines.append(
            f"| {_date_text(row.get('trade_date'))} | {row.get('stock_name')} `{row.get('vt_symbol')}` | "
            f"{row.get('concept_name')} | {row.get('leader_rank')} | {row.get('support_zone')} | "
            f"{_percent(row.get('daily_return_pct'))} | {_percent(row.get('d1_net_return_pct'))} | "
            f"{row.get('selected')} | {row.get('rejection_reason') or ''} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            *[f"- {item}" for item in report.get("boundaries") or []],
            "",
            "## Reproduce",
            "",
            "```bash",
            str(report.get("reproduce") or ""),
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def _normalize_event_rows(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    records = []
    for row in rows:
        raw = dict(row.get("raw") or {})
        reason = str(raw.get("涨停原因") or raw.get("reason_type") or "").strip()
        if not reason:
            continue
        records.append(
            {
                "event_id": int(row["id"]),
                "source_date": pd.to_datetime(
                    str(row["event_date"])[:8], format="%Y%m%d"
                ).date(),
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
    return pd.DataFrame.from_records(
        records,
        columns=[
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
        ],
    )


def _selection_gates_pass(
    development: Mapping[str, Any], validation: Mapping[str, Any]
) -> bool:
    return bool(
        int(development.get("closed_trades") or 0) >= 60
        and int(validation.get("closed_trades") or 0) >= 30
        and float(development.get("positive_rate_pct") or 0.0) > 55.0
        and float(validation.get("positive_rate_pct") or 0.0) > 55.0
        and float(development.get("mean_return_pct") or 0.0) > 0.0
        and float(validation.get("mean_return_pct") or 0.0) > 0.0
        and float(development.get("profit_factor") or 0.0) > 1.0
        and float(validation.get("profit_factor") or 0.0) > 1.0
        and float(development.get("compound_return_pct") or 0.0) > 0.0
        and float(validation.get("compound_return_pct") or 0.0) > 0.0
    )


def _case_audit(
    features: pd.DataFrame,
    outcomes: pd.DataFrame,
    rule: WeakToStrongRule | None,
) -> pd.DataFrame:
    cases = features.loc[features["vt_symbol"].isin(REFERENCE_SYMBOLS)].copy()
    if cases.empty:
        return pd.DataFrame()
    selected_ids: set[tuple[pd.Timestamp, str]] = set()
    if rule is not None:
        selected = select_rule_signals(features, rule)
        selected_ids = set(
            selected[["trade_date", "vt_symbol"]].itertuples(index=False, name=None)
        )
    cases = cases.sort_values(
        [
            "trade_date",
            "vt_symbol",
            "weak_to_strong_day",
            "leader_rank",
            "concept_relative_pct",
        ],
        ascending=[True, True, False, True, False],
        kind="stable",
    ).drop_duplicates(["trade_date", "vt_symbol"], keep="first")
    interesting = cases["weak_to_strong_day"].astype(bool) | cases[
        "pullback_block_reason"
    ].notna()
    selected_cases = cases.loc[interesting].copy()
    missing_symbols = set(REFERENCE_SYMBOLS) - set(selected_cases["vt_symbol"])
    if missing_symbols:
        fallback = (
            cases.loc[cases["vt_symbol"].isin(missing_symbols)]
            .sort_values(
                ["vt_symbol", "leader_rank", "trade_date"],
                ascending=[True, True, False],
                kind="stable",
            )
            .drop_duplicates("vt_symbol", keep="first")
        )
        selected_cases = pd.concat([selected_cases, fallback], ignore_index=True)
    cases = selected_cases.sort_values(
        ["trade_date", "vt_symbol"], kind="stable"
    ).reset_index(drop=True)
    cases["selected"] = [
        (pd.Timestamp(row.trade_date), str(row.vt_symbol)) in selected_ids
        for row in cases.itertuples(index=False)
    ]
    cases["rejection_reason"] = [
        None if selected else _first_rejection_reason(row, rule)
        for selected, (_, row) in zip(
            cases["selected"], cases.iterrows(), strict=True
        )
    ]
    columns = [
        "trade_date",
        "vt_symbol",
        "stock_name",
        "sector_id",
        "concept_name",
        "leader_rank",
        "support_zone",
        "daily_return_pct",
        "prior_daily_return_pct",
        "return20_pct",
        "return60_pct",
        "top3_days10",
        "new_high_days20",
        "confirmed_restart_count",
        "pullback_opportunity_ordinal",
        "pullback_duration",
        "drawdown_from_prior_high_pct",
        "concept_daily_return_pct",
        "concept_return20_pct",
        "volume_ratio5",
        "selected",
        "rejection_reason",
    ]
    frozen = cases.loc[:, columns].reset_index(drop=True)
    return attach_close_outcomes(frozen, outcomes)


def _first_rejection_reason(
    row: pd.Series, rule: WeakToStrongRule | None
) -> str:
    diagnostic_rule = rule or WeakToStrongRule(
        version="diagnostic-broadest",
        minimum_return60_pct=20.0,
        minimum_top3_days10=4,
        minimum_new_high_days20=2,
        maximum_volume_ratio=1.2,
    )
    if float(row["member_count"]) < 5:
        return "concept_members_below_5"
    if float(row["leader_rank"]) > 3:
        return "outside_dynamic_top3"
    if str(row["active_direction"]) != "GOLD":
        return "market_not_gold_at_d_minus_1"
    if str(row["danger_state"]) == "DANGER":
        return "market_danger_state"
    if not bool(row["main_rise_active"]):
        return "stock_main_rise_not_active"
    block_reason = row.get("pullback_block_reason")
    if pd.notna(block_reason) and str(block_reason):
        return str(block_reason)
    if not bool(row["weak_to_strong_day"]):
        return "not_divergence_to_strength_close"
    opportunity = int(row["pullback_opportunity_ordinal"])
    if (
        diagnostic_rule.maximum_opportunity_ordinal is not None
        and opportunity > diagnostic_rule.maximum_opportunity_ordinal
    ):
        return "opportunity_above_frozen_limit"
    if float(row["return60_pct"]) < diagnostic_rule.minimum_return60_pct:
        return "stock_60d_gain_too_low"
    if float(row["top3_days10"]) < diagnostic_rule.minimum_top3_days10:
        return "top3_persistence_too_low"
    if float(row["new_high_days20"]) < diagnostic_rule.minimum_new_high_days20:
        return "prior_high_advance_count_too_low"
    support_zone = str(row["support_zone"])
    if opportunity == 1 and support_zone != "ma5":
        return "first_pullback_did_not_hold_ma5"
    if opportunity >= 2 and support_zone not in {"ma5", "ma10"}:
        return "later_pullback_broke_ma10"
    support_price = float(row["ma5"] if opportunity == 1 else row["ma10"])
    if float(row["close_price"]) < support_price:
        return "confirmation_close_below_required_support"
    if not diagnostic_rule.minimum_drawdown_pct <= float(
        row["drawdown_from_prior_high_pct"]
    ) <= diagnostic_rule.maximum_drawdown_pct:
        return "pullback_depth_outside_range"
    if not diagnostic_rule.minimum_reversal_return_pct <= float(
        row["daily_return_pct"]
    ) <= diagnostic_rule.maximum_reversal_return_pct:
        return "reversal_return_outside_range"
    if float(row["close_location"]) < diagnostic_rule.minimum_close_location:
        return "close_location_too_low"
    if not diagnostic_rule.minimum_volume_ratio <= float(
        row["volume_ratio5"]
    ) <= diagnostic_rule.maximum_volume_ratio:
        return "volume_ratio_outside_range"
    if not bool(row["concept_restrength"]):
        return "concept_not_restrengthening"
    return "no_frozen_rule" if rule is None else "duplicate_weaker_concept_alias"


def _outcome_profiles(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    complete = trades.loc[trades["d1_net_return_pct"].notna()].copy()
    complete["outcome_group"] = np.where(
        complete["d1_net_return_pct"].gt(0), "positive", "non_positive"
    )
    features = (
        "daily_return_pct",
        "prior_daily_return_pct",
        "return20_pct",
        "return60_pct",
        "top3_days10",
        "new_high_days20",
        "main_rise_active_sessions",
        "main_rise_gain_pct",
        "confirmed_restart_count",
        "pullback_opportunity_ordinal",
        "drawdown_from_prior_high_pct",
        "volume_ratio5",
        "close_location",
        "concept_daily_return_pct",
        "concept_return20_pct",
        "leader_score",
        "leader_rank",
    )
    rows = []
    for outcome_group, group in complete.groupby("outcome_group", sort=True):
        row: dict[str, Any] = {
            "outcome_group": str(outcome_group),
            "trades": int(len(group)),
        }
        for feature in features:
            row[f"mean_{feature}"] = float(
                pd.to_numeric(group[feature], errors="coerce").mean()
            )
        rows.append(row)
    return pd.DataFrame.from_records(rows)


def _build_failure_diagnostics(
    signals_by_rule: Mapping[str, pd.DataFrame],
    outcomes: pd.DataFrame,
) -> dict[str, Any]:
    signals = signals_by_rule.get(DIAGNOSTIC_RULE_VERSION)
    if signals is None:
        raise ValueError("diagnostic denominator rule is missing")
    trades = attach_close_outcomes(signals, outcomes)
    seen = trades.loc[
        trades["block"].le(4) & trades["d1_net_return_pct"].notna()
    ].copy()
    validation = seen.loc[seen["block"].eq(4)].copy()
    return _json_safe(
        {
            "denominator_rule_version": DIAGNOSTIC_RULE_VERSION,
            "holdout_block_evaluated": False,
            "by_block": _group_return_diagnostics(seen, "block"),
            "by_opportunity": _group_return_diagnostics(
                seen, "pullback_opportunity_ordinal"
            ),
            "by_support": _group_return_diagnostics(seen, "support_zone"),
            "block4_outcome_profiles": _records(
                _outcome_profiles(validation)
            ),
        }
    )


def _group_return_diagnostics(
    trades: pd.DataFrame,
    column: str,
) -> list[dict[str, Any]]:
    rows = []
    for value, group in trades.groupby(column, sort=True, dropna=False):
        rows.append(
            {
                "group": _json_safe(value),
                **summarize_returns(group),
            }
        )
    return rows


def _reject_outcome_columns(frame: pd.DataFrame) -> None:
    prohibited = sorted(
        column
        for column in frame
        if any(token in str(column).lower() for token in PROHIBITED_SIGNAL_TOKENS)
    )
    if prohibited:
        raise ValueError(f"outcome columns are prohibited from signals: {prohibited}")


def _empty_metrics() -> dict[str, Any]:
    return {
        "closed_trades": 0,
        "positive_rate_pct": None,
        "mean_return_pct": None,
        "median_return_pct": None,
        "profit_factor": None,
        "compound_return_pct": 0.0,
        "maximum_drawdown_pct": 0.0,
    }


def _metric_row(frame: pd.DataFrame, segment: str) -> dict[str, Any]:
    if segment not in frame.index:
        return {}
    row = frame.loc[segment]
    if isinstance(row, pd.DataFrame):
        raise ValueError("metric segments must be unique")
    return row.to_dict()


def _require_columns(
    frame: pd.DataFrame, columns: Sequence[str], label: str
) -> None:
    missing = sorted(set(columns) - set(frame))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is None or pd.isna(value):
        return None
    return value


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{numeric:.4f}" if math.isfinite(numeric) else "-"


def _finite_or(value: Any, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _finite_or_zero(value: Any) -> float:
    return _finite_or(value, 0.0)


def _percent(value: Any) -> str:
    number = _number(value)
    return "-" if number == "-" else f"{number}%"


def _date_text(value: Any) -> str:
    try:
        return pd.Timestamp(value).date().isoformat()
    except (TypeError, ValueError):
        return "-"


_BROAD_LEADER_QUERY = r"""
WITH eligible AS (
    SELECT unnest(CAST(:sector_ids AS varchar[])) AS sector_id
), members AS (
    SELECT DISTINCT m.sector_id, m.vt_symbol, s.name AS stock_name
    FROM stock_sector_memberships m
    JOIN eligible e ON e.sector_id = m.sector_id
    JOIN stocks s ON s.vt_symbol = m.vt_symbol
    WHERE (
        (s.exchange = 'SSE' AND (
            s.symbol LIKE '600%' OR s.symbol LIKE '601%'
            OR s.symbol LIKE '603%' OR s.symbol LIKE '605%'
        ))
        OR (s.exchange = 'SZSE' AND (
            s.symbol LIKE '000%' OR s.symbol LIKE '001%'
            OR s.symbol LIKE '002%' OR s.symbol LIKE '003%'
        ))
    )
    AND s.name NOT ILIKE '%ST%'
    AND s.name NOT LIKE '%退市%'
    AND s.name NOT LIKE '退%'
), symbols AS (
    SELECT DISTINCT vt_symbol FROM members
), stock_window AS (
    SELECT
        b.vt_symbol, b.trade_date, b.open_price, b.high_price,
        b.low_price, b.close_price, b.volume, b.turnover,
        row_number() OVER w AS stock_session_index,
        lag(b.close_price, 1) OVER w AS prev_close,
        lag(b.close_price, 5) OVER w AS close_5,
        lag(b.close_price, 10) OVER w AS close_10,
        lag(b.close_price, 20) OVER w AS close_20,
        lag(b.close_price, 60) OVER w AS close_60,
        lead(b.close_price, 1) OVER w AS close_d1,
        lead(b.close_price, 3) OVER w AS close_d3,
        lead(b.close_price, 5) OVER w AS close_d5,
        avg(b.close_price) OVER (
            PARTITION BY b.vt_symbol ORDER BY b.trade_date
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ) AS ma5,
        avg(b.close_price) OVER (
            PARTITION BY b.vt_symbol ORDER BY b.trade_date
            ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
        ) AS ma10,
        avg(b.close_price) OVER (
            PARTITION BY b.vt_symbol ORDER BY b.trade_date
            ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
        ) AS ma20,
        avg(b.close_price) OVER (
            PARTITION BY b.vt_symbol ORDER BY b.trade_date
            ROWS BETWEEN 59 PRECEDING AND CURRENT ROW
        ) AS ma60,
        max(b.high_price) OVER (
            PARTITION BY b.vt_symbol ORDER BY b.trade_date
            ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS prior_high20,
        max(b.high_price) OVER (
            PARTITION BY b.vt_symbol ORDER BY b.trade_date
            ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
        ) AS prior_high60,
        min(b.low_price) OVER (
            PARTITION BY b.vt_symbol ORDER BY b.trade_date
            ROWS BETWEEN 3 PRECEDING AND CURRENT ROW
        ) AS pullback_low4,
        avg(b.volume) OVER (
            PARTITION BY b.vt_symbol ORDER BY b.trade_date
            ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
        ) AS prior_volume5,
        avg(b.turnover) OVER (
            PARTITION BY b.vt_symbol ORDER BY b.trade_date
            ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ) AS turnover5,
        avg(b.turnover) OVER (
            PARTITION BY b.vt_symbol ORDER BY b.trade_date
            ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
        ) AS turnover20
    FROM stock_daily_bars b
    JOIN symbols s ON s.vt_symbol = b.vt_symbol
    WHERE b.trade_date BETWEEN DATE '2024-03-01' AND DATE '2026-07-17'
    WINDOW w AS (PARTITION BY b.vt_symbol ORDER BY b.trade_date)
), stock_returns AS (
    SELECT *,
        (close_price / NULLIF(prev_close, 0) - 1) * 100 AS daily_return_pct,
        (close_price / NULLIF(close_5, 0) - 1) * 100 AS return5_pct,
        (close_price / NULLIF(close_10, 0) - 1) * 100 AS return10_pct,
        (close_price / NULLIF(close_20, 0) - 1) * 100 AS return20_pct,
        (close_price / NULLIF(close_60, 0) - 1) * 100 AS return60_pct,
        (close_price / NULLIF(prior_high20, 0) - 1) * 100
            AS drawdown_from_prior_high_pct,
        volume / NULLIF(prior_volume5, 0) AS volume_ratio5,
        turnover5 / NULLIF(turnover20, 0) AS turnover_expansion,
        (close_price - low_price) / NULLIF(high_price - low_price, 0)
            AS close_location,
        (close_price / NULLIF(open_price, 0) - 1) * 100 AS body_return_pct
    FROM stock_window
), stock_features AS (
    SELECT *,
        lag(daily_return_pct, 1) OVER w AS prior_daily_return_pct,
        lag(ma10, 5) OVER w AS ma10_lag5,
        lag(ma20, 5) OVER w AS ma20_lag5,
        lag(ma60, 5) OVER w AS ma60_lag5,
        sum(CASE WHEN daily_return_pct >= 5 THEN 1 ELSE 0 END) OVER (
            PARTITION BY vt_symbol ORDER BY trade_date
            ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
        ) AS strong_days10,
        sum(CASE WHEN high_price > prior_high60 THEN 1 ELSE 0 END) OVER (
            PARTITION BY vt_symbol ORDER BY trade_date
            ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
        ) AS new_high_days20
    FROM stock_returns
    WINDOW w AS (PARTITION BY vt_symbol ORDER BY trade_date)
), concept_window AS (
    SELECT
        b.sector_id, s.name AS concept_name, b.trade_date,
        b.close_price, b.turnover,
        lag(b.close_price, 1) OVER w AS prev_close,
        lag(b.close_price, 5) OVER w AS close_5,
        lag(b.close_price, 10) OVER w AS close_10,
        lag(b.close_price, 20) OVER w AS close_20,
        avg(b.close_price) OVER (
            PARTITION BY b.sector_id ORDER BY b.trade_date
            ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
        ) AS ma10,
        avg(b.close_price) OVER (
            PARTITION BY b.sector_id ORDER BY b.trade_date
            ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
        ) AS ma20,
        max(b.close_price) OVER (
            PARTITION BY b.sector_id ORDER BY b.trade_date
            ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
        ) AS high20
    FROM sector_daily_bars b
    JOIN eligible e ON e.sector_id = b.sector_id
    JOIN sectors s ON s.id = b.sector_id
    WHERE b.source = 'eastmoney.board_kline'
    AND b.trade_date BETWEEN DATE '2024-03-01' AND DATE '2026-07-17'
    WINDOW w AS (PARTITION BY b.sector_id ORDER BY b.trade_date)
), concept_returns AS (
    SELECT *,
        (close_price / NULLIF(prev_close, 0) - 1) * 100
            AS concept_daily_return_pct,
        (close_price / NULLIF(close_5, 0) - 1) * 100
            AS concept_return5_pct,
        (close_price / NULLIF(close_10, 0) - 1) * 100
            AS concept_return10_pct,
        (close_price / NULLIF(close_20, 0) - 1) * 100
            AS concept_return20_pct,
        (close_price / NULLIF(high20, 0) - 1) * 100
            AS concept_drawdown20_pct
    FROM concept_window
), concept_features AS (
    SELECT *,
        lag(concept_daily_return_pct, 1) OVER w
            AS concept_prior_daily_return_pct,
        lag(ma10, 5) OVER w AS concept_ma10_lag5,
        lag(ma20, 5) OVER w AS concept_ma20_lag5,
        percent_rank() OVER (
            PARTITION BY trade_date ORDER BY concept_return10_pct
        ) AS concept_relative_pct
    FROM concept_returns
    WINDOW w AS (PARTITION BY sector_id ORDER BY trade_date)
), concept_flags AS (
    SELECT *,
        CASE WHEN trade_date >= DATE '2024-05-28'
            AND close_price >= ma20
            AND ma10 > ma20
            AND ma10 > concept_ma10_lag5
            AND ma20 > concept_ma20_lag5
            AND concept_return20_pct >= 3
            AND concept_drawdown20_pct >= -8
            AND concept_relative_pct >= 0.60
        THEN true ELSE false END AS concept_ignition,
        CASE WHEN trade_date >= DATE '2024-05-28'
            AND close_price >= ma20 * 0.98
            AND ma20 > concept_ma20_lag5
            AND concept_return20_pct >= 0
            AND concept_drawdown20_pct >= -12
        THEN true ELSE false END AS concept_structure_intact
    FROM concept_features
), concept_structure_transitions AS (
    SELECT *,
        lag(concept_structure_intact, 1, false) OVER (
            PARTITION BY sector_id ORDER BY trade_date
        ) AS prior_concept_structure_intact
    FROM concept_flags
), concept_structure_runs AS (
    SELECT *,
        sum(CASE
            WHEN concept_structure_intact
                AND NOT prior_concept_structure_intact
            THEN 1 ELSE 0 END
        ) OVER (
            PARTITION BY sector_id ORDER BY trade_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS concept_structure_run_id
    FROM concept_structure_transitions
), concept_activated AS (
    SELECT *,
        max(CASE WHEN concept_ignition THEN 1 ELSE 0 END) OVER (
            PARTITION BY sector_id, concept_structure_run_id
            ORDER BY trade_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS concept_was_activated
    FROM concept_structure_runs
), concept_active AS (
    SELECT *,
        true AS concept_main_rise_active,
        sector_id || ':' || concept_structure_run_id::text
            AS concept_campaign_id
    FROM concept_activated
    WHERE concept_structure_intact
    AND concept_was_activated = 1
), member_strengths AS (
    SELECT
        m.sector_id, c.concept_name, m.stock_name, s.*,
        c.concept_daily_return_pct, c.concept_prior_daily_return_pct,
        c.concept_return5_pct, c.concept_return10_pct,
        c.concept_return20_pct, c.concept_drawdown20_pct,
        c.concept_relative_pct, c.concept_campaign_id,
        percent_rank() OVER (
            PARTITION BY m.sector_id, s.trade_date ORDER BY s.return60_pct
        ) AS gain60_strength,
        percent_rank() OVER (
            PARTITION BY m.sector_id, s.trade_date ORDER BY s.return20_pct
        ) AS gain20_strength,
        percent_rank() OVER (
            PARTITION BY m.sector_id, s.trade_date ORDER BY s.return10_pct
        ) AS gain10_strength,
        percent_rank() OVER (
            PARTITION BY m.sector_id, s.trade_date ORDER BY s.turnover5
        ) AS turnover_strength,
        percent_rank() OVER (
            PARTITION BY m.sector_id, s.trade_date
            ORDER BY s.turnover_expansion
        ) AS turnover_expansion_strength
    FROM members m
    JOIN concept_active c ON c.sector_id = m.sector_id
    JOIN stock_features s
        ON s.vt_symbol = m.vt_symbol AND s.trade_date = c.trade_date
    WHERE s.return20_pct IS NOT NULL
    AND s.return10_pct IS NOT NULL
    AND s.return60_pct IS NOT NULL
    AND s.ma60 IS NOT NULL
    AND s.turnover5 IS NOT NULL
    AND s.turnover_expansion IS NOT NULL
), scored AS (
    SELECT *,
        0.35 * gain60_strength
        + 0.30 * gain20_strength
        + 0.10 * gain10_strength
        + 0.15 * turnover_strength
        + 0.10 * turnover_expansion_strength AS leader_score
    FROM member_strengths
), ranked AS (
    SELECT *,
        row_number() OVER (
            PARTITION BY sector_id, trade_date
            ORDER BY leader_score DESC, turnover5 DESC, vt_symbol
        ) AS leader_rank,
        count(*) OVER (PARTITION BY sector_id, trade_date) AS member_count
    FROM scored
), rank_path AS (
    SELECT *,
        lag(leader_rank, 1) OVER (
            PARTITION BY sector_id, concept_campaign_id, vt_symbol
            ORDER BY trade_date
        ) AS prior_leader_rank,
        sum(CASE WHEN leader_rank <= 3 THEN 1 ELSE 0 END) OVER (
            PARTITION BY sector_id, concept_campaign_id, vt_symbol
            ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
        ) AS top3_days5,
        sum(CASE WHEN leader_rank <= 3 THEN 1 ELSE 0 END) OVER (
            PARTITION BY sector_id, concept_campaign_id, vt_symbol
            ORDER BY trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
        ) AS top3_days10
    FROM ranked
), candidate_flags AS (
    SELECT *,
        CASE WHEN close_price >= ma20
            AND ma20 > ma60
            AND ma20 > ma20_lag5
            AND ma60 > ma60_lag5
            AND top3_days5 >= 2
        THEN true ELSE false END AS candidate_intact
    FROM rank_path
), candidate_transitions AS (
    SELECT *,
        lag(candidate_intact, 1, false) OVER (
            PARTITION BY sector_id, concept_campaign_id, vt_symbol
            ORDER BY trade_date
        ) AS prior_candidate_intact
    FROM candidate_flags
), candidate_runs AS (
    SELECT *,
        sum(CASE
            WHEN candidate_intact AND NOT prior_candidate_intact
            THEN 1 ELSE 0 END
        ) OVER (
            PARTITION BY sector_id, concept_campaign_id, vt_symbol
            ORDER BY trade_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS candidate_run_id
    FROM candidate_transitions
), latest_timing AS (
    SELECT panel FROM market_timing_panel ORDER BY computed_at DESC LIMIT 1
), timing AS (
    SELECT
        (item ->> 'date')::date AS context_date,
        lead((item ->> 'date')::date) OVER (
            ORDER BY (item ->> 'date')::date
        ) AS signal_date,
        item ->> 'active_direction' AS active_direction,
        item ->> 'danger_state' AS danger_state
    FROM latest_timing
    CROSS JOIN LATERAL jsonb_array_elements(panel -> 'timing_series') item
), broad AS (
    SELECT
        r.*,
        t.active_direction,
        t.danger_state,
        (r.close_d1 / NULLIF(r.close_price, 0) - 1) * 100 - 0.2
            AS d1_net_return_pct,
        (r.close_d3 / NULLIF(r.close_price, 0) - 1) * 100 - 0.2
            AS d3_net_return_pct,
        (r.close_d5 / NULLIF(r.close_price, 0) - 1) * 100 - 0.2
            AS d5_net_return_pct
    FROM candidate_runs r
    LEFT JOIN timing t ON t.signal_date = r.trade_date
    WHERE r.candidate_intact
    AND r.member_count >= 5
    AND r.trade_date >= DATE '2024-07-16'
)
SELECT * FROM broad
ORDER BY trade_date, vt_symbol, leader_rank, sector_id
"""
