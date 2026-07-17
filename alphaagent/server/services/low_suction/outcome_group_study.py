"""D+1 winner/loser grouping for one frozen intraday pullback anchor."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .event_neutral_outcomes import label_event_neutral_outcomes
from .event_neutral_days import EventNeutralInputs, load_event_neutral_comparison_inputs
from .event_recognition_falsification import chronological_event_blocks
from .event_recognition_5m_study import build_event_5m_state_panel
from .event_recognition_minutes import INTERVAL
from .outcome_group_minutes import load_outcome_group_5m_manifest
from .research_protocol import default_protocol, fingerprint_frame, protocol_hash

VOLUME_CLASSES = ("contraction", "normal", "expansion", "explosion")
MIN_COHORT_TRADES = 30
MIN_COHORT_DAYS = 20
HIGH_WIN_RATE_PCT = 60.0
LOW_WIN_RATE_PCT = 45.0
STUDY_EVIDENCE_LEVEL = "event_recognition_outcome_group_d1_falsification"

COMPARISON_COLUMNS = (
    "event_id",
    "context_date",
    "main_rise",
    "spell_session_offset",
)
DAILY_VOLUME_COLUMNS = ("vt_symbol", "trade_date", "volume")
PROHIBITED_FEATURE_COLUMNS = frozenset(
    {
        "net_return_pct",
        "gross_return_pct",
        "double_cost_net_return_pct",
        "mfe_pct",
        "mae_pct",
        "exit_price",
        "exit_price_raw",
        "outcome_group",
        "session_final_low",
        "session_final_high",
    }
)

COHORT_SPECS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("daily_volume", ("daily_volume_class",)),
    ("intraday_volume", ("intraday_volume_class",)),
    ("leader_rank", ("leader_rank_group",)),
    ("main_rise", ("main_rise_group",)),
    ("market_regime", ("market_regime",)),
    ("spell_offset", ("spell_session_offset",)),
    (
        "daily_x_intraday_volume",
        ("daily_volume_class", "intraday_volume_class"),
    ),
    (
        "intraday_volume_x_rank",
        ("intraday_volume_class", "leader_rank_group"),
    ),
    (
        "intraday_volume_x_main_rise",
        ("intraday_volume_class", "main_rise_group"),
    ),
    (
        "intraday_volume_x_market",
        ("intraday_volume_class", "market_regime"),
    ),
    (
        "main_rise_x_rank_x_market",
        ("main_rise_group", "leader_rank_group", "market_regime"),
    ),
)


def classify_volume_ratio(value: Any) -> str:
    """Map a point-in-time volume ratio to the frozen four-level taxonomy."""

    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return "missing"
    if not math.isfinite(ratio) or ratio < 0:
        return "missing"
    if ratio < 0.8:
        return "contraction"
    if ratio < 1.5:
        return "normal"
    if ratio < 2.5:
        return "expansion"
    return "explosion"


def build_outcome_group_signals(
    candidates: pd.DataFrame,
    minute_bars: pd.DataFrame,
    daily_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Select the first executable 5m close at or below the D-1 close."""

    _reject_future_or_outcome_columns(candidates, minute_bars, daily_bars)
    _require_columns(candidates, COMPARISON_COLUMNS, "comparison candidate")
    if candidates.duplicated(["event_id"]).any():
        raise ValueError("comparison candidate event IDs must be unique")

    panel = build_event_5m_state_panel(candidates, minute_bars)
    context = candidates.loc[:, list(COMPARISON_COLUMNS)].copy()
    context["context_date"] = pd.to_datetime(
        context["context_date"], errors="raise"
    ).dt.date
    panel = panel.merge(context, on="event_id", how="left", validate="many_to_one")
    panel = panel.sort_values(["event_id", "bar_time"], kind="stable")
    group = panel.groupby("event_id", sort=False)
    prior_three_volume = group["volume"].transform(
        lambda values: values.shift(1).rolling(3, min_periods=3).mean()
    )
    panel["intraday_volume_ratio"] = panel["volume"] / prior_three_volume.where(
        prior_three_volume.gt(0)
    )
    panel["signal_minutes_from_open"] = (group.cumcount() + 1) * 5
    panel["distance_to_previous_close_pct"] = (
        panel["close_price"] / panel["signal_close"].where(panel["signal_close"].gt(0))
        - 1.0
    ) * 100.0
    ratio = pd.to_numeric(panel["intraday_volume_ratio"], errors="coerce")
    eligible = (
        panel["close_price"].le(panel["signal_close"])
        & panel["next_bar_time"].notna()
        & pd.to_numeric(panel["next_bar_open"], errors="coerce").gt(0)
        & ratio.notna()
        & np.isfinite(ratio.to_numpy(dtype=float))
    )
    signals = (
        panel.loc[eligible]
        .drop_duplicates("event_id", keep="first")
        .sort_values(["entry_date", "event_id"], kind="stable")
        .reset_index(drop=True)
    )

    daily_context = _build_daily_volume_context(daily_bars)
    signals = signals.merge(
        daily_context,
        on=["vt_symbol", "context_date"],
        how="left",
        validate="many_to_one",
    )
    signals["observed_at"] = pd.to_datetime(signals["bar_time"], errors="raise")
    signals["entry_time"] = pd.to_datetime(
        signals["next_bar_time"], errors="raise"
    )
    signals["entry_price_raw"] = pd.to_numeric(
        signals["next_bar_open"], errors="raise"
    )
    signals["observation_id"] = (
        signals["event_id"].astype(str)
        + ":"
        + signals["observed_at"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    )
    signals["intraday_volume_class"] = signals["intraday_volume_ratio"].map(
        classify_volume_ratio
    )
    signals["daily_volume_class"] = signals["daily_volume_ratio"].map(
        classify_volume_ratio
    )
    ranks = pd.to_numeric(signals["recognition_rank"], errors="raise").astype(int)
    if not ranks.isin((1, 2, 3)).all():
        raise ValueError("comparison leader ranks must be 1 through 3")
    signals["leader_rank_group"] = np.where(ranks.eq(1), "rank_1", "rank_2_3")
    signals["main_rise_group"] = np.where(
        signals["main_rise"].astype(bool),
        "main_rise",
        "non_main_rise",
    )
    signals["market_regime"] = (
        signals["active_direction"].astype(str)
        + "/"
        + signals["danger_state"].astype(str)
    )
    return signals.sort_values(
        ["entry_date", "event_id", "observed_at"], kind="stable"
    ).reset_index(drop=True)


def label_outcome_group_trades(
    signals: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    trading_dates: tuple[date, ...],
) -> pd.DataFrame:
    """Attach normal and double-cost D+1 labels after signal construction."""

    if signals.empty:
        result = signals.copy()
        for column in (
            "normal_status",
            "normal_reason",
            "stressed_status",
            "stressed_reason",
            "net_return_pct",
            "double_cost_net_return_pct",
            "outcome_group",
        ):
            result[column] = pd.Series(dtype="object")
        return result
    normal = label_event_neutral_outcomes(
        signals,
        daily_bars,
        trading_dates=trading_dates,
    )
    stressed = label_event_neutral_outcomes(
        signals,
        daily_bars,
        trading_dates=trading_dates,
        cost_multiplier=2.0,
    )
    normal_columns = normal.loc[
        :,
        [
            "observation_id",
            "status",
            "reason",
            "actual_exit_date",
            "entry_price",
            "exit_price_raw",
            "exit_price",
            "total_fees",
            "net_return_pct",
        ],
    ].rename(columns={"status": "normal_status", "reason": "normal_reason"})
    stressed_columns = stressed.loc[
        :, ["observation_id", "status", "reason", "net_return_pct"]
    ].rename(
        columns={
            "status": "stressed_status",
            "reason": "stressed_reason",
            "net_return_pct": "double_cost_net_return_pct",
        }
    )
    trades = signals.merge(
        normal_columns,
        on="observation_id",
        how="left",
        validate="one_to_one",
    ).merge(
        stressed_columns,
        on="observation_id",
        how="left",
        validate="one_to_one",
    )
    closed = trades["normal_status"].eq("closed")
    returns = pd.to_numeric(trades["net_return_pct"], errors="coerce")
    trades["outcome_group"] = np.select(
        [closed & returns.gt(0), closed & returns.le(0)],
        ["winner", "loser"],
        default="not_closed",
    )
    return trades.sort_values(
        ["entry_date", "event_id", "observed_at"], kind="stable"
    ).reset_index(drop=True)


def classify_development_cohort(metrics: Mapping[str, Any]) -> str:
    """Classify a development cohort with fixed sample and performance gates."""

    if (
        int(metrics.get("closed_trades") or 0) < MIN_COHORT_TRADES
        or int(metrics.get("source_days") or 0) < MIN_COHORT_DAYS
    ):
        return "neutral"
    win_rate = _finite_value(metrics.get("win_rate_pct"))
    mean_return = _finite_value(metrics.get("mean_net_return_pct"))
    profit_factor = _finite_value(metrics.get("profit_factor"), allow_infinite=True)
    stressed_mean = _finite_value(
        metrics.get("double_cost_mean_net_return_pct")
    )
    if (
        win_rate is not None
        and win_rate > HIGH_WIN_RATE_PCT
        and mean_return is not None
        and mean_return > 0
        and profit_factor is not None
        and profit_factor > 1
        and stressed_mean is not None
        and stressed_mean > 0
    ):
        return "high_candidate"
    if (
        win_rate is not None
        and win_rate < LOW_WIN_RATE_PCT
        and mean_return is not None
        and mean_return < 0
        and profit_factor is not None
        and profit_factor < 1
    ):
        return "low_candidate"
    return "neutral"


def build_outcome_cohort_metrics(trades: pd.DataFrame) -> pd.DataFrame:
    """Measure every pre-registered cohort on development and validation."""

    required = {
        "block",
        "entry_date",
        "normal_status",
        "stressed_status",
        "net_return_pct",
        "double_cost_net_return_pct",
    }
    required.update(column for _, columns in COHORT_SPECS for column in columns)
    _require_columns(trades, tuple(sorted(required)), "outcome trade")
    records: list[dict[str, Any]] = []
    segments = (("development", (1, 2, 3)), ("validation", (4, 5)))
    for table_id, dimensions in COHORT_SPECS:
        identities = (
            trades.loc[:, list(dimensions)]
            .drop_duplicates()
            .sort_values(list(dimensions), kind="stable", na_position="last")
        )
        for identity in identities.to_dict("records"):
            cohort_key = _cohort_key(dimensions, identity)
            identity_mask = pd.Series(True, index=trades.index, dtype=bool)
            for dimension in dimensions:
                value = identity[dimension]
                if pd.isna(value):
                    identity_mask &= trades[dimension].isna()
                else:
                    identity_mask &= trades[dimension].eq(value)
            for segment, blocks in segments:
                rows = trades.loc[identity_mask & trades["block"].isin(blocks)]
                records.append(
                    {
                        "table_id": table_id,
                        "cohort_key": cohort_key,
                        "cohort_values": {
                            key: _json_scalar(value)
                            for key, value in identity.items()
                        },
                        "segment": segment,
                        **_summarize_trade_rows(rows),
                    }
                )
    metrics = pd.DataFrame(records)
    if metrics.empty:
        return metrics
    development_classes: dict[tuple[str, str], str] = {}
    validation_statuses: dict[tuple[str, str], str] = {}
    for (table_id, cohort_key), rows in metrics.groupby(
        ["table_id", "cohort_key"], sort=True
    ):
        development = rows.loc[rows["segment"].eq("development")].iloc[0]
        validation = rows.loc[rows["segment"].eq("validation")].iloc[0]
        development_class = classify_development_cohort(development)
        development_classes[(str(table_id), str(cohort_key))] = development_class
        validation_statuses[(str(table_id), str(cohort_key))] = (
            _validation_status(development_class, validation)
        )
    keys = list(zip(metrics["table_id"], metrics["cohort_key"], strict=True))
    metrics["development_class"] = [development_classes[key] for key in keys]
    metrics["validation_status"] = [validation_statuses[key] for key in keys]
    return metrics.sort_values(
        ["table_id", "cohort_key", "segment"], kind="stable"
    ).reset_index(drop=True)


def build_winner_loser_profiles(trades: pd.DataFrame) -> pd.DataFrame:
    """Describe pre-entry feature differences after outcomes are known."""

    required = (
        "outcome_group",
        "entry_date",
        "daily_volume_ratio",
        "intraday_volume_ratio",
        "leader_rank_group",
        "main_rise_group",
        "market_regime",
        "danger_state",
        "signal_minutes_from_open",
        "distance_to_previous_close_pct",
    )
    _require_columns(trades, required, "profile trade")
    rows = []
    closed = trades.loc[trades["outcome_group"].isin(("winner", "loser"))]
    for outcome_group, group in closed.groupby("outcome_group", sort=True):
        rows.append(
            {
                "outcome_group": str(outcome_group),
                "closed_trades": int(len(group)),
                "source_days": int(pd.to_datetime(group["entry_date"]).dt.date.nunique()),
                "median_daily_volume_ratio": _median_numeric(
                    group["daily_volume_ratio"]
                ),
                "median_intraday_volume_ratio": _median_numeric(
                    group["intraday_volume_ratio"]
                ),
                "rank_1_share_pct": _share(group["leader_rank_group"].eq("rank_1")),
                "main_rise_share_pct": _share(
                    group["main_rise_group"].eq("main_rise")
                ),
                "gold_normal_share_pct": _share(
                    group["market_regime"].eq("GOLD/NORMAL")
                ),
                "silver_normal_share_pct": _share(
                    group["market_regime"].eq("SILVER/NORMAL")
                ),
                "danger_share_pct": _share(group["danger_state"].ne("NORMAL")),
                "median_signal_minutes_from_open": _median_numeric(
                    group["signal_minutes_from_open"]
                ),
                "median_distance_to_previous_close_pct": _median_numeric(
                    group["distance_to_previous_close_pct"]
                ),
            }
        )
    return pd.DataFrame(rows)


def load_outcome_group_study_data(
    inputs: EventNeutralInputs | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load exact comparison candidates, complete 5m bars, signals and labels."""

    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    selected_inputs = inputs or load_event_neutral_comparison_inputs()
    candidates = selected_inputs.candidates.copy()
    if candidates.empty:
        raise ValueError("outcome-group comparison candidates are required")
    manifest = load_outcome_group_5m_manifest(candidates)
    incomplete = manifest.loc[manifest["status"].ne("complete")]
    if not incomplete.empty:
        raise ValueError("outcome-group 5m manifest must be complete before study")

    symbols = tuple(sorted(candidates["vt_symbol"].astype(str).unique()))
    dates = tuple(sorted(pd.to_datetime(candidates["entry_date"]).dt.date.unique()))
    statement = (
        select(
            schema.stock_minute_bars.c.vt_symbol,
            schema.stock_minute_bars.c.trade_date,
            schema.stock_minute_bars.c.bar_time,
            schema.stock_minute_bars.c.interval,
            schema.stock_minute_bars.c.open_price,
            schema.stock_minute_bars.c.high_price,
            schema.stock_minute_bars.c.low_price,
            schema.stock_minute_bars.c.close_price,
            schema.stock_minute_bars.c.volume,
            schema.stock_minute_bars.c.turnover,
            schema.stock_minute_bars.c.source,
        )
        .where(
            schema.stock_minute_bars.c.vt_symbol.in_(symbols),
            schema.stock_minute_bars.c.trade_date.between(dates[0], dates[-1]),
            schema.stock_minute_bars.c.interval == INTERVAL,
        )
        .order_by(
            schema.stock_minute_bars.c.vt_symbol,
            schema.stock_minute_bars.c.trade_date,
            schema.stock_minute_bars.c.bar_time,
        )
    )
    loaded = pd.read_sql(statement, get_engine(), parse_dates=["bar_time"])
    minute_bars = _filter_candidate_pairs(candidates, loaded)
    expected_rows = len(candidates) * 48
    if len(minute_bars) != expected_rows:
        raise ValueError("outcome-group minute rows must equal candidate days times 48")

    signals = build_outcome_group_signals(
        candidates,
        minute_bars,
        selected_inputs.stock_bars,
    )
    blocks = chronological_event_blocks(dates, block_count=5).rename(
        columns={"source_date": "entry_date"}
    )
    signals["entry_date"] = pd.to_datetime(signals["entry_date"]).dt.date
    signals = signals.merge(
        blocks,
        on="entry_date",
        how="left",
        validate="many_to_one",
    )
    trades = label_outcome_group_trades(
        signals,
        selected_inputs.stock_bars,
        trading_dates=selected_inputs.trading_dates,
    )
    normal_statuses = trades["normal_status"].value_counts(dropna=False)
    stressed_statuses = trades["stressed_status"].value_counts(dropna=False)
    main_rise_counts = candidates["main_rise"].astype(bool).value_counts()
    main_rise_signal_counts = signals["main_rise"].astype(bool).value_counts()
    outcome_counts = trades["outcome_group"].value_counts(dropna=False)
    actual_exit_dates = pd.to_datetime(
        trades["actual_exit_date"], errors="coerce"
    ).dt.date
    planned_exit_dates = pd.to_datetime(
        trades["planned_exit_date"], errors="coerce"
    ).dt.date
    signal_minute_counts = signals["signal_minutes_from_open"].value_counts().sort_index()
    fingerprints = {
        **selected_inputs.input_fingerprints,
        "outcome_group_minutes": fingerprint_frame(
            minute_bars,
            identity_columns=("vt_symbol", "bar_time", "interval"),
        ).as_dict(),
        "outcome_group_signals": fingerprint_frame(
            signals.loc[
                :,
                [
                    "observation_id",
                    "event_id",
                    "entry_date",
                    "observed_at",
                    "entry_time",
                    "daily_volume_ratio",
                    "intraday_volume_ratio",
                    "leader_rank_group",
                    "main_rise_group",
                    "market_regime",
                    "block",
                ],
            ],
            identity_columns=("observation_id",),
        ).as_dict(),
        "outcome_group_labels": fingerprint_frame(
            trades.loc[
                :,
                [
                    "observation_id",
                    "normal_status",
                    "normal_reason",
                    "net_return_pct",
                    "stressed_status",
                    "stressed_reason",
                    "double_cost_net_return_pct",
                    "outcome_group",
                ],
            ],
            identity_columns=("observation_id",),
        ).as_dict(),
    }
    coverage = {
        **selected_inputs.coverage,
        "comparison_candidates": int(len(candidates)),
        "main_rise_candidates": int(main_rise_counts.get(True, 0)),
        "non_main_rise_candidates": int(main_rise_counts.get(False, 0)),
        "manifest_pairs": int(len(manifest)),
        "complete_pairs": int(manifest["status"].eq("complete").sum()),
        "minute_rows": int(len(minute_bars)),
        "entry_signals": int(len(signals)),
        "no_pullback_signal": int(len(candidates) - len(signals)),
        "main_rise_signals": int(main_rise_signal_counts.get(True, 0)),
        "non_main_rise_signals": int(main_rise_signal_counts.get(False, 0)),
        "winner_count": int(outcome_counts.get("winner", 0)),
        "loser_count": int(outcome_counts.get("loser", 0)),
        "planned_d1_exit_count": int(actual_exit_dates.eq(planned_exit_dates).sum()),
        "delayed_sellable_exit_count": int(actual_exit_dates.gt(planned_exit_dates).sum()),
        "first_eligible_0950_signal_count": int(
            signals["signal_minutes_from_open"].eq(20).sum()
        ),
        "signal_minutes_from_open_counts": {
            str(int(key)): int(value) for key, value in signal_minute_counts.items()
        },
        "missing_daily_volume_class": int(
            signals["daily_volume_class"].eq("missing").sum()
        ),
        "normal_status_counts": {
            str(key): int(value) for key, value in normal_statuses.items()
        },
        "double_cost_status_counts": {
            str(key): int(value) for key, value in stressed_statuses.items()
        },
        "candidate_date_start": min(dates).isoformat(),
        "candidate_date_end": max(dates).isoformat(),
        "holdout_price_values_read": False,
        "current_membership_rows_read": 0,
    }
    metadata = {
        "coverage": coverage,
        "input_fingerprints": fingerprints,
        "discovery_start": selected_inputs.discovery_start,
        "discovery_end": selected_inputs.discovery_end,
    }
    return candidates, signals, trades, metadata


def build_outcome_group_report(
    candidates: pd.DataFrame,
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the complete machine report without selecting a trading rule."""

    protocol = default_protocol()
    cohort_metrics = build_outcome_cohort_metrics(trades)
    profile_frames = []
    for segment, blocks in (
        ("all", (1, 2, 3, 4, 5)),
        ("development", (1, 2, 3)),
        ("validation", (4, 5)),
    ):
        profile = build_winner_loser_profiles(trades.loc[trades["block"].isin(blocks)])
        if not profile.empty:
            profile.insert(0, "segment", segment)
            profile_frames.append(profile)
    profiles = (
        pd.concat(profile_frames, ignore_index=True)
        if profile_frames
        else pd.DataFrame()
    )
    overall_rows = []
    for segment, blocks in (
        ("all", (1, 2, 3, 4, 5)),
        ("development", (1, 2, 3)),
        ("validation", (4, 5)),
        ("block_1", (1,)),
        ("block_2", (2,)),
        ("block_3", (3,)),
        ("block_4", (4,)),
        ("block_5", (5,)),
    ):
        overall_rows.append(
            {
                "segment": segment,
                **_summarize_trade_rows(trades.loc[trades["block"].isin(blocks)]),
            }
        )
    overall = pd.DataFrame(overall_rows)
    development = cohort_metrics.loc[cohort_metrics["segment"].eq("development")]
    high_candidates = development.loc[
        development["development_class"].eq("high_candidate")
    ]
    low_candidates = development.loc[
        development["development_class"].eq("low_candidate")
    ]
    confirmed_high = development.loc[
        development["validation_status"].eq("high_confirmed")
    ]
    confirmed_low = development.loc[
        development["validation_status"].eq("low_confirmed")
    ]
    if not confirmed_high.empty and not confirmed_low.empty:
        conclusion = "confirmed_high_and_low_cohorts"
    elif not high_candidates.empty or not low_candidates.empty:
        conclusion = "descriptive_groups_not_stable"
    else:
        conclusion = "no_usable_group_separation"
    coverage = dict(metadata.get("coverage", {}))
    coverage.setdefault("comparison_candidates", int(len(candidates)))
    coverage.setdefault("entry_signals", int(len(signals)))
    return {
        "protocol_version": protocol.version,
        "protocol_hash": protocol_hash(protocol),
        "evidence_level": STUDY_EVIDENCE_LEVEL,
        "overall_conclusion": conclusion,
        "formal_metrics": None,
        "formal_rule_selected": False,
        "holdout_price_values_read": False,
        "current_membership_rows_read": 0,
        "limit_up_strategy_rows_read": 0,
        "frozen_contract": {
            "universe": "earliest event-recognition leader spell S+1..S+5",
            "evidence_scope": "proxy_not_strict_historical_top3",
            "main_rise_known_at": "D-1 close",
            "entry_signal": "first eligible 5m close <= D-1 close",
            "entry_fill": "next 5m open",
            "maximum_trades_per_stock_day": 1,
            "exit": "D+1 first sellable close",
            "cost_multipliers": [1.0, 2.0],
            "volume_thresholds": {
                "contraction": "<0.8",
                "normal": "[0.8,1.5)",
                "expansion": "[1.5,2.5)",
                "explosion": ">=2.5",
            },
            "development_blocks": [1, 2, 3],
            "validation_blocks": [4, 5],
            "high_gate": {
                "closed_trades": f">={MIN_COHORT_TRADES}",
                "source_days": f">={MIN_COHORT_DAYS}",
                "win_rate_pct": f">{HIGH_WIN_RATE_PCT}",
                "mean_net_return_pct": ">0",
                "profit_factor": ">1",
                "double_cost_mean_net_return_pct": ">0",
            },
            "low_gate": {
                "closed_trades": f">={MIN_COHORT_TRADES}",
                "source_days": f">={MIN_COHORT_DAYS}",
                "win_rate_pct": f"<{LOW_WIN_RATE_PCT}",
                "mean_net_return_pct": "<0",
                "profit_factor": "<1",
            },
            "outer_holdout_read": False,
        },
        "coverage": coverage,
        "input_fingerprints": dict(metadata.get("input_fingerprints", {})),
        "overall_metrics": _records(overall),
        "winner_loser_profiles": _records(profiles),
        "cohort_metrics": _records(cohort_metrics),
        "development_high_candidates": _cohort_ids(high_candidates),
        "development_low_candidates": _cohort_ids(low_candidates),
        "confirmed_high_cohorts": _cohort_ids(confirmed_high),
        "confirmed_low_cohorts": _cohort_ids(confirmed_low),
        "decision": {
            "entry_rule_selected": False,
            "cohort_filter_selected": False,
            "strict_top3_claim": False,
            "next_gate": "interpret_group_separation_without_rule_selection",
        },
    }


def run_outcome_group_study() -> dict[str, Any]:
    candidates, signals, trades, metadata = load_outcome_group_study_data()
    return build_outcome_group_report(candidates, signals, trades, metadata)


def render_outcome_group_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def render_outcome_group_markdown(report: Mapping[str, Any]) -> str:
    coverage = report["coverage"]
    lines = [
        "# Low-suction D+1 Winner/Loser Group Study",
        "",
        f"- Conclusion: `{report['overall_conclusion']}`",
        f"- Evidence: `{report['evidence_level']}` (proxy, not strict historical Top3)",
        "- Formal metrics/rule: `null/false`",
        "- Outer holdout/current members/limit-up strategy rows read: `0/0/0`",
        f"- Candidates: `{coverage.get('comparison_candidates', 0)}` "
        f"(main rise `{coverage.get('main_rise_candidates', 0)}`, "
        f"control `{coverage.get('non_main_rise_candidates', 0)}`)",
        f"- Entry signals/no-pullback: `{coverage.get('entry_signals', 0)}/"
        f"{coverage.get('no_pullback_signal', 0)}`",
        "",
        "## Overall D+1 Results",
        "",
        "| Segment | Signals | Closed | Days | Win | Mean | Median | PF | 2x mean |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["overall_metrics"]:
        lines.append(
            f"| `{row['segment']}` | {row['signals']} | {row['closed_trades']} | "
            f"{row['source_days']} | {_pct(row['win_rate_pct'])} | "
            f"{_pct(row['mean_net_return_pct'])} | "
            f"{_pct(row['median_net_return_pct'])} | "
            f"{_number(row['profit_factor'])} | "
            f"{_pct(row['double_cost_mean_net_return_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## Winner/Loser Profiles",
            "",
            "| Segment | Outcome | Trades | Daily volume median | 5m volume median | Rank1 | Main rise | Gold normal | Silver normal |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["winner_loser_profiles"]:
        lines.append(
            f"| `{row['segment']}` | `{row['outcome_group']}` | "
            f"{row['closed_trades']} | {_number(row['median_daily_volume_ratio'])} | "
            f"{_number(row['median_intraday_volume_ratio'])} | "
            f"{_pct(row['rank_1_share_pct'])} | {_pct(row['main_rise_share_pct'])} | "
            f"{_pct(row['gold_normal_share_pct'])} | "
            f"{_pct(row['silver_normal_share_pct'])} |"
        )
    for table_id, title in (
        ("daily_volume", "D-1 Daily Volume"),
        ("intraday_volume", "Signal 5m Volume"),
        ("leader_rank", "Leader Rank"),
        ("main_rise", "Main-rise Status"),
        ("market_regime", "GOLD/SILVER Regime"),
    ):
        lines.extend(_render_cohort_table(report["cohort_metrics"], table_id, title))
    lines.extend(
        [
            "",
            "## Classification",
            "",
            f"- Development high candidates: `{len(report['development_high_candidates'])}`",
            f"- Development low candidates: `{len(report['development_low_candidates'])}`",
            f"- Confirmed high cohorts: `{len(report['confirmed_high_cohorts'])}`",
            f"- Confirmed low cohorts: `{len(report['confirmed_low_cohorts'])}`",
            "- Outcome labels are descriptive only and are never entry features.",
            "- No cohort is promoted to a buy rule in this study.",
            "",
        ]
    )
    return "\n".join(lines)


def _build_daily_volume_context(daily_bars: pd.DataFrame) -> pd.DataFrame:
    _require_columns(daily_bars, DAILY_VOLUME_COLUMNS, "daily volume")
    bars = daily_bars.loc[:, list(DAILY_VOLUME_COLUMNS)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.date
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("daily volume identities must be unique")
    bars["volume"] = pd.to_numeric(bars["volume"], errors="coerce")
    bars = bars.sort_values(["vt_symbol", "trade_date"], kind="stable")
    prior_five = bars.groupby("vt_symbol", sort=False)["volume"].transform(
        lambda values: values.shift(1).rolling(5, min_periods=5).mean()
    )
    bars["daily_volume_ratio"] = bars["volume"] / prior_five.where(prior_five.gt(0))
    return bars.loc[:, ["vt_symbol", "trade_date", "daily_volume_ratio"]].rename(
        columns={"trade_date": "context_date"}
    )


def _filter_candidate_pairs(
    candidates: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    pairs = candidates.loc[:, ["vt_symbol", "entry_date"]].copy()
    pairs["entry_date"] = pd.to_datetime(pairs["entry_date"], errors="raise").dt.date
    pairs = pairs.drop_duplicates().rename(columns={"entry_date": "trade_date"})
    bars = minute_bars.copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.date
    return (
        bars.merge(
            pairs,
            on=["vt_symbol", "trade_date"],
            how="inner",
            validate="many_to_one",
        )
        .sort_values(["vt_symbol", "bar_time"], kind="stable")
        .reset_index(drop=True)
    )


def _summarize_trade_rows(rows: pd.DataFrame) -> dict[str, Any]:
    closed = rows.loc[
        rows["normal_status"].eq("closed") & rows["stressed_status"].eq("closed")
    ]
    normal = pd.to_numeric(closed["net_return_pct"], errors="coerce").dropna()
    stressed = pd.to_numeric(
        closed["double_cost_net_return_pct"], errors="coerce"
    ).dropna()
    return {
        "signals": int(len(rows)),
        "closed_trades": int(len(normal)),
        "source_days": int(pd.to_datetime(closed["entry_date"]).dt.date.nunique()),
        "win_rate_pct": _win_rate(normal),
        "mean_net_return_pct": _mean(normal),
        "median_net_return_pct": _median(normal),
        "profit_factor": _profit_factor(normal),
        "tail_5pct": _quantile(normal, 0.05),
        "double_cost_win_rate_pct": _win_rate(stressed),
        "double_cost_mean_net_return_pct": _mean(stressed),
    }


def _validation_status(
    development_class: str,
    validation_metrics: Mapping[str, Any],
) -> str:
    validation_class = classify_development_cohort(validation_metrics)
    if development_class == "high_candidate":
        return (
            "high_confirmed"
            if validation_class == "high_candidate"
            else "high_not_confirmed"
        )
    if development_class == "low_candidate":
        return (
            "low_confirmed"
            if validation_class == "low_candidate"
            else "low_not_confirmed"
        )
    return "not_applicable"


def _cohort_key(dimensions: tuple[str, ...], identity: Mapping[str, Any]) -> str:
    return "|".join(
        f"{dimension}={_json_scalar(identity[dimension])}" for dimension in dimensions
    )


def _cohort_ids(frame: pd.DataFrame) -> list[dict[str, str]]:
    if frame.empty:
        return []
    return [
        {"table_id": str(row.table_id), "cohort_key": str(row.cohort_key)}
        for row in frame.itertuples(index=False)
    ]


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _json_safe(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (date, pd.Timestamp)):
        return pd.Timestamp(value).isoformat()
    return value


def _render_cohort_table(
    records: list[dict[str, Any]],
    table_id: str,
    title: str,
) -> list[str]:
    rows = [row for row in records if row["table_id"] == table_id]
    lines = [
        "",
        f"## {title}",
        "",
        "| Cohort | Segment | Closed | Days | Win | Mean | PF | 2x mean | Dev class | Validation |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['cohort_key']}` | `{row['segment']}` | "
            f"{row['closed_trades']} | {row['source_days']} | "
            f"{_pct(row['win_rate_pct'])} | {_pct(row['mean_net_return_pct'])} | "
            f"{_number(row['profit_factor'])} | "
            f"{_pct(row['double_cost_mean_net_return_pct'])} | "
            f"`{row['development_class']}` | `{row['validation_status']}` |"
        )
    return lines


def _reject_future_or_outcome_columns(*frames: pd.DataFrame) -> None:
    prohibited = set().union(
        *(PROHIBITED_FEATURE_COLUMNS & set(frame) for frame in frames)
    )
    prohibited.update(
        column
        for frame in frames
        for column in frame
        if str(column).startswith("future_")
    )
    if prohibited:
        raise ValueError(
            f"future or outcome columns are prohibited from entry features: {sorted(prohibited)}"
        )


def _profit_factor(values: pd.Series) -> float | None:
    if values.empty:
        return None
    gains = float(values.loc[values > 0].sum())
    losses = abs(float(values.loc[values < 0].sum()))
    if losses == 0:
        return math.inf if gains > 0 else None
    return gains / losses


def _win_rate(values: pd.Series) -> float | None:
    return float(values.gt(0).mean() * 100.0) if len(values) else None


def _mean(values: pd.Series) -> float | None:
    return float(values.mean()) if len(values) else None


def _median(values: pd.Series) -> float | None:
    return float(values.median()) if len(values) else None


def _quantile(values: pd.Series, value: float) -> float | None:
    return float(values.quantile(value)) if len(values) else None


def _median_numeric(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.median()) if len(numeric) else None


def _share(mask: pd.Series) -> float | None:
    return float(mask.mean() * 100.0) if len(mask) else None


def _finite_value(value: Any, *, allow_infinite: bool = False) -> float | None:
    if value is None or value is pd.NA:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or (math.isinf(result) and not allow_infinite):
        return None
    return result


def _json_scalar(value: Any) -> Any:
    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _pct(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}%"


def _number(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}"


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
