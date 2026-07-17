"""Point-in-time stock main-rise and passive-hold baseline audit."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from collections.abc import Sequence
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .event_neutral_days import load_event_neutral_comparison_inputs
from .event_recognition_falsification import chronological_event_blocks
from .outcome_group_study import load_outcome_group_study_data
from .outcomes import generate_daily_proxy_outcomes
from .research_protocol import default_protocol, fingerprint_frame, protocol_hash

CANDIDATE_COLUMNS = (
    "event_id",
    "context_date",
    "entry_date",
    "planned_exit_date",
    "vt_symbol",
    "sector_id",
    "concept_name",
    "recognition_rank",
    "main_rise",
)
DAILY_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
)
STOCK_DEFINITIONS = (
    "concept_main_rise",
    "stock_above_ma5",
    "stock_trend_order",
    "stock_strong_main_rise",
)
MIN_BASELINE_TRADES = 30
MIN_BASELINE_DAYS = 20
STUDY_EVIDENCE_LEVEL = "event_recognition_stock_main_rise_hold_audit"
PROHIBITED_FEATURE_COLUMNS = frozenset(
    {
        "net_return_pct",
        "gross_return_pct",
        "double_cost_net_return_pct",
        "mfe_pct",
        "mae_pct",
        "exit_price",
        "outcome_group",
    }
)


def build_stock_main_rise_features(
    candidates: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> pd.DataFrame:
    """Attach stock trend features known at each candidate's D-1 close."""

    _reject_future_or_outcome_columns(candidates, daily_bars)
    _require_columns(candidates, CANDIDATE_COLUMNS, "candidate")
    _require_columns(daily_bars, DAILY_COLUMNS, "daily bar")
    if candidates.duplicated(["event_id"]).any():
        raise ValueError("candidate event IDs must be unique")

    calendar = pd.DatetimeIndex(
        pd.to_datetime(list(trading_dates), errors="raise")
    ).normalize()
    calendar = calendar.drop_duplicates().sort_values()
    if calendar.empty:
        raise ValueError("trading dates must not be empty")

    bars = daily_bars.loc[:, list(DAILY_COLUMNS)].copy()
    bars["trade_date"] = pd.to_datetime(
        bars["trade_date"], errors="raise"
    ).dt.normalize()
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("daily bar identities must be unique")
    symbols = set(candidates["vt_symbol"].astype(str))
    bars = bars.loc[bars["vt_symbol"].astype(str).isin(symbols)].copy()
    feature_frames = [
        _build_symbol_features(str(vt_symbol), group, calendar)
        for vt_symbol, group in bars.groupby("vt_symbol", sort=True)
    ]
    stock_features = (
        pd.concat(feature_frames, ignore_index=True)
        if feature_frames
        else _empty_stock_features()
    )

    result = candidates.copy()
    result["context_date"] = pd.to_datetime(
        result["context_date"], errors="raise"
    ).dt.normalize()
    result["entry_date"] = pd.to_datetime(
        result["entry_date"], errors="raise"
    ).dt.normalize()
    result["planned_exit_date"] = pd.to_datetime(
        result["planned_exit_date"], errors="raise"
    ).dt.normalize()
    generated_columns = set(stock_features) - {"vt_symbol", "trade_date"}
    stale_columns = sorted(generated_columns & set(result))
    if stale_columns:
        result = result.drop(columns=stale_columns)
    result = result.merge(
        stock_features,
        left_on=["vt_symbol", "context_date"],
        right_on=["vt_symbol", "trade_date"],
        how="left",
        validate="many_to_one",
    ).drop(columns=["trade_date"])

    numeric_required = (
        "stock_close",
        "ma5",
        "ma10",
        "ma20",
        "ma5_shift_3",
        "ma10_shift_3",
        "ma20_shift_3",
        "return_10d_pct",
        "distance_from_20d_high_pct",
    )
    numeric = result.loc[:, list(numeric_required)].apply(
        pd.to_numeric, errors="coerce"
    )
    result["feature_complete"] = (
        numeric.notna().all(axis=1)
        & np.isfinite(numeric.to_numpy(dtype=float)).all(axis=1)
    )
    result["feature_status"] = np.where(
        result["feature_complete"],
        "complete",
        "incomplete_d1_history",
    )
    concept_main_rise = result["main_rise"].astype(bool)
    result["concept_main_rise"] = concept_main_rise
    result["stock_above_ma5"] = (
        concept_main_rise
        & result["feature_complete"]
        & result["stock_close"].ge(result["ma5"])
    )
    result["stock_trend_order"] = (
        result["stock_above_ma5"]
        & result["ma5"].gt(result["ma10"])
        & result["ma10"].gt(result["ma20"])
    )
    result["stock_strong_main_rise"] = (
        result["stock_trend_order"]
        & result["ma5"].gt(result["ma5_shift_3"])
        & result["ma10"].gt(result["ma10_shift_3"])
        & result["ma20"].gt(result["ma20_shift_3"])
        & result["return_10d_pct"].gt(0)
        & result["distance_from_20d_high_pct"].ge(-5.0)
    )
    result["source_cutoff_date"] = result["context_date"]
    result["evidence_level"] = "event_recognition_stock_main_rise_audit"
    return result.sort_values(
        ["entry_date", "event_id"], kind="stable"
    ).reset_index(drop=True)


def execute_stock_main_rise_hold(
    features: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Buy D open from D-1 evidence and retain only the D+1 close outcome."""

    _require_columns(
        features,
        ("event_id", "vt_symbol", "context_date", "evidence_level"),
        "stock main-rise feature",
    )
    events = features.loc[
        :, ["event_id", "vt_symbol", "context_date", "evidence_level"]
    ].rename(columns={"context_date": "trade_date"})
    events["event_id"] = events["event_id"].astype(str)
    bars = _prepare_hold_bars(daily_bars)
    normal = generate_daily_proxy_outcomes(
        events,
        bars,
        trading_dates=trading_dates,
    )
    stressed = generate_daily_proxy_outcomes(
        events,
        bars,
        trading_dates=trading_dates,
        cost_multiplier=2.0,
    )
    return (
        _select_d1_outcomes(normal),
        _select_d1_outcomes(stressed),
    )


def classify_hold_baseline(metrics: Mapping[str, Any]) -> str:
    """Apply fixed sample, positive and high-win gates to one metric row."""

    if (
        int(metrics.get("closed_trades") or 0) < MIN_BASELINE_TRADES
        or int(metrics.get("source_days") or 0) < MIN_BASELINE_DAYS
    ):
        return "insufficient_sample"
    win_rate = _numeric_value(metrics.get("win_rate_pct"))
    mean_return = _numeric_value(metrics.get("mean_net_return_pct"))
    profit_factor = _numeric_value(
        metrics.get("profit_factor"), allow_infinite=True
    )
    stressed_mean = _numeric_value(
        metrics.get("double_cost_mean_net_return_pct")
    )
    positive = (
        win_rate is not None
        and win_rate > 50.0
        and mean_return is not None
        and mean_return > 0
        and profit_factor is not None
        and profit_factor > 1
        and stressed_mean is not None
        and stressed_mean > 0
    )
    if positive and win_rate > 60.0:
        return "high_win_baseline"
    if positive:
        return "positive_baseline"
    return "not_positive_baseline"


def build_hold_baseline_metrics(
    features: pd.DataFrame,
    normal_outcomes: pd.DataFrame,
    stressed_outcomes: pd.DataFrame,
) -> pd.DataFrame:
    """Summarize every fixed stock definition on identical time segments."""

    _require_columns(
        features,
        ("event_id", "entry_date", "block", *STOCK_DEFINITIONS),
        "stock main-rise metric feature",
    )
    required_outcome = ("event_id", "status", "net_return_pct")
    _require_columns(normal_outcomes, required_outcome, "normal hold outcome")
    _require_columns(stressed_outcomes, required_outcome, "stressed hold outcome")
    if normal_outcomes.duplicated(["event_id"]).any() or stressed_outcomes.duplicated(
        ["event_id"]
    ).any():
        raise ValueError("hold outcome event IDs must be unique")

    frame = features.copy()
    frame["event_id"] = frame["event_id"].astype(str)
    normal = normal_outcomes.loc[:, list(required_outcome)].rename(
        columns={"status": "normal_status"}
    )
    stressed = stressed_outcomes.loc[:, list(required_outcome)].rename(
        columns={
            "status": "stressed_status",
            "net_return_pct": "double_cost_net_return_pct",
        }
    )
    frame = frame.merge(
        normal,
        on="event_id",
        how="left",
        validate="one_to_one",
    ).merge(
        stressed,
        on="event_id",
        how="left",
        validate="one_to_one",
    )
    segments = (
        ("all", (1, 2, 3, 4, 5)),
        ("development", (1, 2, 3)),
        ("validation", (4, 5)),
        ("block_1", (1,)),
        ("block_2", (2,)),
        ("block_3", (3,)),
        ("block_4", (4,)),
        ("block_5", (5,)),
    )
    rows = []
    for definition in STOCK_DEFINITIONS:
        eligible = frame.loc[frame[definition].astype(bool)]
        for segment, blocks in segments:
            metrics = _summarize_returns(eligible.loc[eligible["block"].isin(blocks)])
            rows.append(
                {
                    "definition": definition,
                    "segment": segment,
                    **metrics,
                    "baseline_label": classify_hold_baseline(metrics),
                }
            )
    result = pd.DataFrame(rows)
    stable: dict[str, bool] = {}
    positive_labels = {"positive_baseline", "high_win_baseline"}
    for definition, group in result.groupby("definition", sort=True):
        development_label = group.loc[
            group["segment"].eq("development"), "baseline_label"
        ].item()
        validation_label = group.loc[
            group["segment"].eq("validation"), "baseline_label"
        ].item()
        stable[str(definition)] = (
            development_label in positive_labels
            and validation_label in positive_labels
        )
    result["stable_positive_baseline"] = result["definition"].map(stable)
    return result.sort_values(
        ["definition", "segment"], kind="stable"
    ).reset_index(drop=True)


def attach_signal_ma_zones(
    trades: pd.DataFrame,
    features: pd.DataFrame,
) -> pd.DataFrame:
    """Attach D-1 MA location to each already-frozen intraday signal."""

    _require_columns(trades, ("event_id", "close_price"), "low-suction trade")
    feature_columns = (
        "event_id",
        "ma5",
        "ma10",
        "ma20",
        *STOCK_DEFINITIONS,
    )
    _require_columns(features, feature_columns, "stock main-rise attribution")
    if features.duplicated(["event_id"]).any():
        raise ValueError("stock main-rise attribution event IDs must be unique")
    overlap = (set(feature_columns) - {"event_id"}) & set(trades)
    if overlap:
        raise ValueError(f"trade already contains MA attribution columns: {sorted(overlap)}")

    result = trades.copy()
    result["event_id"] = result["event_id"].astype(str)
    feature_frame = features.loc[:, list(feature_columns)].copy()
    feature_frame["event_id"] = feature_frame["event_id"].astype(str)
    result = result.merge(
        feature_frame,
        on="event_id",
        how="left",
        validate="one_to_one",
    )
    signal_close = pd.to_numeric(result["close_price"], errors="coerce")
    ma5 = pd.to_numeric(result["ma5"], errors="coerce")
    ma10 = pd.to_numeric(result["ma10"], errors="coerce")
    ma20 = pd.to_numeric(result["ma20"], errors="coerce")
    result["signal_above_ma5"] = signal_close.ge(ma5) & ma5.notna()
    result["signal_above_ma10"] = signal_close.ge(ma10) & ma10.notna()
    result["signal_above_ma20"] = signal_close.ge(ma20) & ma20.notna()
    ordered = ma5.gt(ma10) & ma10.gt(ma20)
    result["signal_ma_zone"] = np.select(
        [
            ordered & signal_close.ge(ma5),
            ordered & signal_close.ge(ma10),
            ordered & signal_close.ge(ma20),
            ordered & signal_close.lt(ma20),
        ],
        ["above_ma5", "ma5_to_ma10", "ma10_to_ma20", "below_ma20"],
        default="unordered_mas",
    )
    return result


def build_signal_ma_zone_metrics(attributed_trades: pd.DataFrame) -> pd.DataFrame:
    """Summarize old low-suction outcomes by frozen MA zones and definitions."""

    _require_columns(
        attributed_trades,
        (
            "entry_date",
            "block",
            "normal_status",
            "stressed_status",
            "net_return_pct",
            "double_cost_net_return_pct",
            "signal_ma_zone",
            *STOCK_DEFINITIONS,
        ),
        "MA-attributed low-suction trade",
    )
    segments = (
        ("all", (1, 2, 3, 4, 5)),
        ("development", (1, 2, 3)),
        ("validation", (4, 5)),
        ("block_1", (1,)),
        ("block_2", (2,)),
        ("block_3", (3,)),
        ("block_4", (4,)),
        ("block_5", (5,)),
    )
    cohorts: list[tuple[str, str, pd.Series]] = []
    for zone in sorted(attributed_trades["signal_ma_zone"].astype(str).unique()):
        cohorts.append(
            (
                "signal_ma_zone",
                zone,
                attributed_trades["signal_ma_zone"].astype(str).eq(zone),
            )
        )
    for definition in STOCK_DEFINITIONS:
        cohorts.append(
            (
                "d1_stock_definition",
                definition,
                attributed_trades[definition].astype(bool),
            )
        )
    rows = []
    for table_id, cohort_key, mask in cohorts:
        cohort = attributed_trades.loc[mask]
        for segment, blocks in segments:
            rows.append(
                {
                    "table_id": table_id,
                    "cohort_key": cohort_key,
                    "segment": segment,
                    **_summarize_returns(cohort.loc[cohort["block"].isin(blocks)]),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["table_id", "cohort_key", "segment"], kind="stable"
    ).reset_index(drop=True)


def load_stock_main_rise_audit_data(
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load the frozen proxy candidates and both causal audit surfaces."""

    inputs = load_event_neutral_comparison_inputs()
    candidates, _, trades, outcome_metadata = load_outcome_group_study_data(inputs)
    features = build_stock_main_rise_features(
        candidates,
        inputs.stock_bars,
        trading_dates=inputs.trading_dates,
    )
    entry_dates = tuple(sorted(pd.to_datetime(features["entry_date"]).dt.date.unique()))
    blocks = chronological_event_blocks(entry_dates, block_count=5).rename(
        columns={"source_date": "entry_date"}
    )
    features["entry_date"] = pd.to_datetime(features["entry_date"]).dt.date
    features = features.merge(
        blocks,
        on="entry_date",
        how="left",
        validate="many_to_one",
    )
    normal, stressed = execute_stock_main_rise_hold(
        features,
        inputs.stock_bars,
        trading_dates=inputs.trading_dates,
    )
    hold_metrics = build_hold_baseline_metrics(features, normal, stressed)
    attributed = attach_signal_ma_zones(trades, features)
    signal_metrics = build_signal_ma_zone_metrics(attributed)

    definition_counts = {
        definition: int(features[definition].astype(bool).sum())
        for definition in STOCK_DEFINITIONS
    }
    zone_counts = attributed["signal_ma_zone"].value_counts().sort_index()
    normal_status_counts = normal["status"].value_counts(dropna=False).sort_index()
    stressed_status_counts = stressed["status"].value_counts(dropna=False).sort_index()
    normal_rejection_reasons = (
        normal.loc[normal["status"].ne("closed"), "reason"]
        .fillna("unknown")
        .value_counts()
        .sort_index()
    )
    coverage = {
        **dict(outcome_metadata.get("coverage", {})),
        "candidate_count": int(len(features)),
        "feature_complete_count": int(features["feature_complete"].sum()),
        "feature_incomplete_count": int((~features["feature_complete"]).sum()),
        "definition_counts": definition_counts,
        "hold_normal_status_counts": {
            str(key): int(value) for key, value in normal_status_counts.items()
        },
        "hold_double_cost_status_counts": {
            str(key): int(value) for key, value in stressed_status_counts.items()
        },
        "hold_rejection_reason_counts": {
            str(key): int(value) for key, value in normal_rejection_reasons.items()
        },
        "low_suction_signal_count": int(len(attributed)),
        "signal_above_ma5_count": int(attributed["signal_above_ma5"].sum()),
        "signal_above_ma10_count": int(attributed["signal_above_ma10"].sum()),
        "signal_above_ma20_count": int(attributed["signal_above_ma20"].sum()),
        "signal_ma_zone_counts": {
            str(key): int(value) for key, value in zone_counts.items()
        },
        "holdout_price_values_read": False,
        "current_membership_rows_read": 0,
        "limit_up_strategy_rows_read": 0,
    }
    fingerprints = {
        **dict(outcome_metadata.get("input_fingerprints", {})),
        "stock_main_rise_features": fingerprint_frame(
            features.loc[
                :,
                [
                    "event_id",
                    "context_date",
                    "entry_date",
                    "stock_close",
                    "ma5",
                    "ma10",
                    "ma20",
                    "ma5_shift_3",
                    "ma10_shift_3",
                    "ma20_shift_3",
                    "return_10d_pct",
                    "distance_from_20d_high_pct",
                    *STOCK_DEFINITIONS,
                    "block",
                ],
            ],
            identity_columns=("event_id",),
        ).as_dict(),
        "stock_main_rise_hold_normal": fingerprint_frame(
            normal.loc[:, ["event_id", "status", "reason", "net_return_pct"]],
            identity_columns=("event_id",),
        ).as_dict(),
        "stock_main_rise_hold_stressed": fingerprint_frame(
            stressed.loc[:, ["event_id", "status", "reason", "net_return_pct"]],
            identity_columns=("event_id",),
        ).as_dict(),
        "stock_main_rise_signal_zones": fingerprint_frame(
            attributed.loc[
                :,
                [
                    "event_id",
                    "signal_ma_zone",
                    "signal_above_ma5",
                    "signal_above_ma10",
                    "signal_above_ma20",
                ],
            ],
            identity_columns=("event_id",),
        ).as_dict(),
    }
    metadata = {
        "coverage": coverage,
        "input_fingerprints": fingerprints,
        "discovery_start": inputs.discovery_start,
        "discovery_end": inputs.discovery_end,
    }
    return features, hold_metrics, attributed, signal_metrics, metadata


def build_stock_main_rise_report(
    features: pd.DataFrame,
    hold_metrics: pd.DataFrame,
    attributed_trades: pd.DataFrame,
    signal_metrics: pd.DataFrame,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a bounded audit report without selecting a production definition."""

    _require_columns(
        features,
        ("feature_complete", *STOCK_DEFINITIONS),
        "stock main-rise report feature",
    )
    _require_columns(
        hold_metrics,
        ("definition", "segment", "baseline_label", "stable_positive_baseline"),
        "hold baseline report metric",
    )
    protocol = default_protocol()
    stable_definitions = sorted(
        hold_metrics.loc[
            hold_metrics["stable_positive_baseline"].astype(bool), "definition"
        ].astype(str).unique()
    )
    stable_stock_definitions = [
        definition
        for definition in stable_definitions
        if definition != "concept_main_rise"
    ]
    if stable_stock_definitions:
        conclusion = "stock_main_rise_baseline_confirmed"
    elif "concept_main_rise" in stable_definitions:
        conclusion = "concept_only_not_stock_main_rise"
    else:
        conclusion = "no_stock_main_rise_baseline_in_proxy"
    prevalence = [
        {
            "definition": definition,
            "candidate_count": int(features[definition].astype(bool).sum()),
            "candidate_share_pct": float(features[definition].astype(bool).mean() * 100.0),
        }
        for definition in STOCK_DEFINITIONS
    ]
    signal_count = len(attributed_trades)
    coverage = dict(metadata.get("coverage", {}))
    coverage.setdefault("candidate_count", int(len(features)))
    coverage.setdefault("low_suction_signal_count", int(signal_count))
    return {
        "protocol_version": protocol.version,
        "protocol_hash": protocol_hash(protocol),
        "evidence_level": STUDY_EVIDENCE_LEVEL,
        "overall_conclusion": conclusion,
        "formal_metrics": None,
        "selected_stock_main_rise_definition": None,
        "formal_rule_selected": False,
        "holdout_price_values_read": False,
        "current_membership_rows_read": 0,
        "limit_up_strategy_rows_read": 0,
        "frozen_contract": {
            "feature_cutoff": "D-1 close",
            "hold_entry": "D open",
            "hold_exit": "D+1 close",
            "cost_multipliers": [1.0, 2.0],
            "definitions": list(STOCK_DEFINITIONS),
            "ma_periods": [5, 10, 20],
            "slope_lookback_sessions": 3,
            "strong_main_rise_max_distance_from_20d_high_pct": -5.0,
            "development_blocks": [1, 2, 3],
            "validation_blocks": [4, 5],
            "outer_holdout_read": False,
            "pre_breakout_track_included": False,
        },
        "coverage": coverage,
        "input_fingerprints": dict(metadata.get("input_fingerprints", {})),
        "definition_prevalence": prevalence,
        "hold_baseline_metrics": _records(hold_metrics),
        "low_suction_signal_ma_metrics": _records(signal_metrics),
        "stable_positive_definitions": stable_definitions,
        "stable_stock_definitions": stable_stock_definitions,
        "signal_ma_position": {
            "signal_count": int(signal_count),
            "above_ma5_count": int(attributed_trades["signal_above_ma5"].sum()),
            "above_ma10_count": int(attributed_trades["signal_above_ma10"].sum()),
            "above_ma20_count": int(attributed_trades["signal_above_ma20"].sum()),
            "above_ma5_share_pct": _share(attributed_trades["signal_above_ma5"]),
            "above_ma10_share_pct": _share(attributed_trades["signal_above_ma10"]),
            "above_ma20_share_pct": _share(attributed_trades["signal_above_ma20"]),
        },
        "decision": {
            "definition_selected": False,
            "new_pullback_entry_tested": False,
            "pre_breakout_track_tested": False,
            "strict_top3_claim": False,
        },
    }


def run_stock_main_rise_audit() -> dict[str, Any]:
    features, hold_metrics, attributed, signal_metrics, metadata = (
        load_stock_main_rise_audit_data()
    )
    return build_stock_main_rise_report(
        features,
        hold_metrics,
        attributed,
        signal_metrics,
        metadata,
    )


def render_stock_main_rise_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def render_stock_main_rise_markdown(report: Mapping[str, Any]) -> str:
    position = report["signal_ma_position"]
    lines = [
        "# Low-suction Stock Main-rise Baseline Audit",
        "",
        f"- Conclusion: `{report['overall_conclusion']}`",
        f"- Evidence: `{report['evidence_level']}` (proxy, not strict historical Top3)",
        "- Formal metrics/selected definition: `null/null`",
        "- Outer holdout/current members/limit-up strategy rows read: `0/0/0`",
        f"- Candidate/low-suction signals: `{report['coverage'].get('candidate_count', 0)}/"
        f"{position['signal_count']}`",
        f"- Signals above MA5/MA10/MA20: `{position['above_ma5_count']}/"
        f"{position['above_ma10_count']}/{position['above_ma20_count']}`",
        "",
        "## Definition Prevalence",
        "",
        "| Definition | Candidates | Share |",
        "| --- | ---: | ---: |",
    ]
    for row in report["definition_prevalence"]:
        lines.append(
            f"| `{row['definition']}` | {row['candidate_count']} | "
            f"{_pct(row['candidate_share_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## D-open To D+1-close Hold Baseline",
            "",
            "| Definition | Segment | Closed | Days | Win | Mean | PF | 2x mean | Label | Stable |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in report["hold_baseline_metrics"]:
        if row["segment"] not in {"all", "development", "validation"}:
            continue
        lines.append(
            f"| `{row['definition']}` | `{row['segment']}` | {row['closed_trades']} | "
            f"{row['source_days']} | {_pct(row['win_rate_pct'])} | "
            f"{_pct(row['mean_net_return_pct'])} | {_number(row['profit_factor'])} | "
            f"{_pct(row['double_cost_mean_net_return_pct'])} | "
            f"`{row['baseline_label']}` | "
            f"`{str(row['stable_positive_baseline']).lower()}` |"
        )
    lines.extend(
        [
            "",
            "## Existing Low-suction Entry MA Zones",
            "",
            "| Table | Cohort | Segment | Closed | Days | Win | Mean | PF | 2x mean |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["low_suction_signal_ma_metrics"]:
        if row["segment"] not in {"all", "development", "validation"}:
            continue
        lines.append(
            f"| `{row['table_id']}` | `{row['cohort_key']}` | `{row['segment']}` | "
            f"{row['closed_trades']} | {row['source_days']} | "
            f"{_pct(row['win_rate_pct'])} | {_pct(row['mean_net_return_pct'])} | "
            f"{_number(row['profit_factor'])} | "
            f"{_pct(row['double_cost_mean_net_return_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "本报告只审计代理候选的个股主升基准和旧买点均线位置，不选择正式主升定义，",
            "不测试新低吸触发，也不包含提前埋伏轨道。严格 Top3、正式绩效和外层留出保持关闭。",
            "",
        ]
    )
    return "\n".join(lines)


def _build_symbol_features(
    vt_symbol: str,
    group: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    frame = group.set_index("trade_date").reindex(calendar)
    frame.index.name = "trade_date"
    frame["vt_symbol"] = vt_symbol
    close = pd.to_numeric(frame["close_price"], errors="coerce")
    frame["stock_close"] = close
    for sessions in (5, 10, 20):
        frame[f"ma{sessions}"] = close.rolling(
            sessions, min_periods=sessions
        ).mean()
        frame[f"return_{sessions}d_pct"] = (
            close / close.shift(sessions) - 1.0
        ) * 100.0
    for sessions in (5, 10, 20):
        frame[f"ma{sessions}_shift_3"] = frame[f"ma{sessions}"].shift(3)
    rolling_high = close.rolling(20, min_periods=20).max()
    frame["high_20d"] = rolling_high
    frame["distance_from_20d_high_pct"] = (
        close / rolling_high.where(rolling_high.gt(0)) - 1.0
    ) * 100.0
    return frame.reset_index().loc[:, list(_empty_stock_features().columns)]


def _prepare_hold_bars(daily_bars: pd.DataFrame) -> pd.DataFrame:
    _require_columns(daily_bars, DAILY_COLUMNS, "hold daily bar")
    bars = daily_bars.loc[:, list(DAILY_COLUMNS)].copy()
    bars["trade_date"] = pd.to_datetime(
        bars["trade_date"], errors="raise"
    ).dt.normalize()
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("hold daily bar identities must be unique")
    bars = bars.sort_values(["vt_symbol", "trade_date"], kind="stable")
    previous_close = bars.groupby("vt_symbol", sort=False)["close_price"].shift(1)
    bars["limit_up_price"] = previous_close * 1.10
    bars["limit_down_price"] = previous_close * 0.90
    bars["suspended"] = pd.to_numeric(
        bars["volume"], errors="coerce"
    ).fillna(0).le(0)
    return bars


def _select_d1_outcomes(outcomes: pd.DataFrame) -> pd.DataFrame:
    return outcomes.loc[outcomes["exit_key"].eq("entry_plus_1_close")].sort_values(
        ["signal_date", "event_id"], kind="stable"
    ).reset_index(drop=True)


def _summarize_returns(frame: pd.DataFrame) -> dict[str, Any]:
    closed = frame.loc[
        frame["normal_status"].eq("closed")
        & frame["stressed_status"].eq("closed")
    ]
    normal = pd.to_numeric(closed["net_return_pct"], errors="coerce").dropna()
    stressed = pd.to_numeric(
        closed["double_cost_net_return_pct"], errors="coerce"
    ).dropna()
    return {
        "signals": int(len(frame)),
        "closed_trades": int(len(normal)),
        "source_days": int(
            pd.to_datetime(closed["entry_date"], errors="coerce").dt.date.nunique()
        ),
        "win_rate_pct": _win_rate(normal),
        "mean_net_return_pct": _mean(normal),
        "median_net_return_pct": _median(normal),
        "profit_factor": _profit_factor(normal),
        "tail_5pct": _quantile(normal, 0.05),
        "double_cost_win_rate_pct": _win_rate(stressed),
        "double_cost_mean_net_return_pct": _mean(stressed),
    }


def _empty_stock_features() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "vt_symbol",
            "trade_date",
            "stock_close",
            "ma5",
            "ma10",
            "ma20",
            "ma5_shift_3",
            "ma10_shift_3",
            "ma20_shift_3",
            "return_5d_pct",
            "return_10d_pct",
            "return_20d_pct",
            "high_20d",
            "distance_from_20d_high_pct",
        ]
    )


def _reject_future_or_outcome_columns(*frames: pd.DataFrame) -> None:
    prohibited = set().union(
        *(PROHIBITED_FEATURE_COLUMNS & set(frame) for frame in frames)
    )
    prohibited.update(
        column
        for frame in frames
        for column in frame
        if str(column).startswith(("future_", "outcome_"))
    )
    if prohibited:
        raise ValueError(
            f"future or outcome columns are prohibited from stock main-rise features: {sorted(prohibited)}"
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


def _numeric_value(value: Any, *, allow_infinite: bool = False) -> float | None:
    if value is None or value is pd.NA:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or (math.isinf(result) and not allow_infinite):
        return None
    return result


def _share(values: pd.Series) -> float | None:
    return float(values.astype(bool).mean() * 100.0) if len(values) else None


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


def _pct(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}%"


def _number(value: Any) -> str:
    return "-" if value is None else f"{float(value):.4f}"


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
