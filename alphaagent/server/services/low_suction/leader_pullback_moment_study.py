"""Intraday pullback moments for realized and D-1 dynamic cycle leaders."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .event_recognition_5m_study import build_event_5m_state_panel
from .outcome_group_study import classify_volume_ratio, label_outcome_group_trades
from .research_protocol import fingerprint_frame


MOMENT_RULES = (
    "ma5_touch_hold",
    "ma10_touch_hold",
    "vwap_reclaim",
    "drawdown_1_reversal",
    "drawdown_3_reversal",
)
DEVELOPMENT_BLOCKS = frozenset({1, 2, 3})
VALIDATION_BLOCKS = frozenset({4, 5})
MIN_DEVELOPMENT_TRADES = 30
MIN_DEVELOPMENT_DAYS = 20
MIN_VALIDATION_TRADES = 20
MIN_VALIDATION_DAYS = 15
MIN_HIGH_WIN_RATE_PCT = 55.0
STUDY_EVIDENCE_LEVEL = "event_candidate_cycle_leader_pullback_moment_study"
IDENTITY_COLUMNS = (
    "dynamic_feature_status",
    "dynamic_excess_return_pct",
    "dynamic_near_limit_up_days",
    "dynamic_max_consecutive_near_limit_up_days",
    "dynamic_sessions_since_last_near_limit_up",
    "dynamic_traded_value_20d",
    "dynamic_rank",
    "dynamic_pool_size",
    "dynamic_top3_qualified",
    "dynamic_top1",
    "dynamic_top3",
    "realized_path_status",
    "realized_stock_return_pct",
    "realized_excess_return_pct",
    "realized_near_limit_up_days",
    "realized_max_consecutive_near_limit_up_days",
    "realized_market_rank",
    "realized_return_rank",
    "oracle_market_top1",
    "oracle_market_top3",
    "oracle_return_top1",
    "oracle_return_top3",
)
CANDIDATE_CONTEXT_COLUMNS = (
    "leader_spell_id",
    "stock_name",
    "recognition_source_date",
    "context_date",
    "previous_high",
    "ma5",
    "ma10",
    "cycle_relative_percentile",
    "spell_session_offset",
    "main_rise",
    "is_top3",
    "rank_mode",
    *IDENTITY_COLUMNS,
)


def attach_cycle_leader_identities(
    candidates: pd.DataFrame,
    dynamic_leaders: pd.DataFrame,
    realized_leaders: pd.DataFrame,
) -> pd.DataFrame:
    """Attach causal dynamic and retrospective leader identities explicitly."""

    keys = ("cycle_id", "entry_date", "vt_symbol")
    _require_columns(candidates, keys, "candidate identity")
    _require_columns(
        dynamic_leaders,
        (*keys, "dynamic_rank", "dynamic_pool_size", "dynamic_top3_qualified"),
        "dynamic leader",
    )
    _require_columns(
        realized_leaders,
        (
            "cycle_id",
            "vt_symbol",
            "realized_market_rank",
            "realized_return_rank",
        ),
        "realized leader",
    )
    frame = candidates.copy()
    frame["entry_date"] = pd.to_datetime(frame["entry_date"], errors="raise").dt.normalize()
    dynamic = dynamic_leaders.copy()
    dynamic["entry_date"] = pd.to_datetime(
        dynamic["entry_date"], errors="raise"
    ).dt.normalize()
    dynamic_columns = [
        *keys,
        *[column for column in dynamic.columns if column.startswith("dynamic_")],
    ]
    dynamic_columns = list(dict.fromkeys(dynamic_columns))
    realized_columns = [
        "cycle_id",
        "vt_symbol",
        *[column for column in realized_leaders.columns if column.startswith("realized_")],
    ]
    realized_columns = list(dict.fromkeys(realized_columns))
    result = frame.merge(
        dynamic.loc[:, dynamic_columns],
        on=list(keys),
        how="left",
        validate="many_to_one",
    ).merge(
        realized_leaders.loc[:, realized_columns],
        on=["cycle_id", "vt_symbol"],
        how="left",
        validate="many_to_one",
    )
    for column in ("dynamic_top3_qualified", "dynamic_top1", "dynamic_top3"):
        result[column] = result[column].fillna(False).astype(bool)
    market_rank = pd.to_numeric(result["realized_market_rank"], errors="coerce")
    return_rank = pd.to_numeric(result["realized_return_rank"], errors="coerce")
    result["oracle_market_top1"] = market_rank.eq(1)
    result["oracle_market_top3"] = market_rank.le(3)
    result["oracle_return_top1"] = return_rank.eq(1)
    result["oracle_return_top3"] = return_rank.le(3)
    return result.sort_values(["entry_date", "event_id"], kind="stable").reset_index(
        drop=True
    )


def build_leader_pullback_moments(
    identified_candidates: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Extract the first executable timestamp for every frozen pullback rule."""

    _require_columns(
        identified_candidates,
        ("event_id", *CANDIDATE_CONTEXT_COLUMNS),
        "identified candidate",
    )
    base = build_event_5m_state_panel(identified_candidates, minute_bars)
    context = identified_candidates.loc[
        :, ["event_id", *CANDIDATE_CONTEXT_COLUMNS]
    ].copy()
    panel = base.merge(context, on="event_id", how="left", validate="many_to_one")
    panel = panel.sort_values(["event_id", "bar_time"], kind="stable")
    grouped = panel.groupby("event_id", sort=False)
    panel["session_high"] = grouped["high_price"].cummax()
    panel["drawdown_from_session_high_pct"] = (
        panel["close_price"] / panel["session_high"].where(panel["session_high"].gt(0))
        - 1.0
    ) * 100.0
    prior_volume = grouped["volume"].transform(
        lambda values: values.shift(1).rolling(3, min_periods=3).mean()
    )
    panel["intraday_volume_ratio"] = panel["volume"] / prior_volume.where(
        prior_volume.gt(0)
    )
    panel["signal_minutes_from_open"] = (grouped.cumcount() + 1) * 5
    rule_masks = _moment_rule_masks(panel)
    moments = [
        _extract_first_moment(panel, rule=rule, mask=rule_masks[rule])
        for rule in MOMENT_RULES
    ]
    nonempty = [frame for frame in moments if not frame.empty]
    if not nonempty:
        return _empty_moments(identified_candidates)
    result = pd.concat(nonempty, ignore_index=True)
    result["intraday_volume_class"] = result["intraday_volume_ratio"].map(
        classify_volume_ratio
    )
    result["signal_time_bucket"] = result["signal_minutes_from_open"].map(
        classify_signal_time
    )
    result["drawdown_bucket"] = result["drawdown_from_session_high_pct"].map(
        classify_drawdown
    )
    result["market_regime"] = (
        result["active_direction"].astype(str)
        + "/"
        + result["danger_state"].astype(str)
    )
    if result.duplicated(["event_id", "moment_rule"]).any():
        raise ValueError("each candidate day can emit one moment per frozen rule")
    return result.sort_values(
        ["entry_date", "event_id", "observed_at", "moment_rule"], kind="stable"
    ).reset_index(drop=True)


def label_leader_pullback_moments(
    moments: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    trading_dates: tuple[date, ...],
) -> pd.DataFrame:
    """Attach existing normal and double-cost D+1 cash labels."""

    return label_outcome_group_trades(
        moments,
        daily_bars,
        trading_dates=trading_dates,
    )


def build_leader_moment_cohort_trades(trades: pd.DataFrame) -> pd.DataFrame:
    """Expand causal and oracle memberships without mixing their identities."""

    required = (
        "observation_id",
        "event_id",
        "cycle_id",
        "entry_date",
        "block",
        "moment_rule",
        "dynamic_top3_qualified",
        "dynamic_top1",
        "dynamic_top3",
        "oracle_market_top1",
        "oracle_market_top3",
        "oracle_return_top1",
        "oracle_return_top3",
        "signal_time_bucket",
        "drawdown_bucket",
        "intraday_volume_class",
        "market_regime",
        "normal_status",
        "stressed_status",
        "net_return_pct",
        "double_cost_net_return_pct",
    )
    _require_columns(trades, required, "leader pullback trade")
    rows: list[dict[str, Any]] = []
    for record in trades.to_dict("records"):
        _append_moment_memberships(rows, record)
    if not rows:
        result = trades.iloc[0:0].copy()
        result["table_id"] = pd.Series(dtype="object")
        result["cohort_key"] = pd.Series(dtype="object")
        return result
    result = pd.DataFrame(rows)
    if result.duplicated(["observation_id", "table_id", "cohort_key"]).any():
        raise ValueError("leader moment cohort identities must be unique")
    return result.sort_values(
        ["entry_date", "observation_id", "table_id", "cohort_key"],
        kind="stable",
    ).reset_index(drop=True)


def build_leader_moment_metrics(cohort_trades: pd.DataFrame) -> pd.DataFrame:
    """Summarize causal and oracle cohorts over fixed time segments."""

    _require_columns(
        cohort_trades,
        (
            "entry_date",
            "block",
            "table_id",
            "cohort_key",
            "normal_status",
            "net_return_pct",
            "double_cost_net_return_pct",
        ),
        "leader moment cohort trade",
    )
    if cohort_trades.empty:
        return _empty_metrics()
    frame = cohort_trades.copy()
    frame["entry_date"] = pd.to_datetime(
        frame["entry_date"], errors="raise"
    ).dt.date
    rows = []
    for (table_id, cohort_key), cohort in frame.groupby(
        ["table_id", "cohort_key"], sort=True
    ):
        for segment, blocks in _metric_segments():
            rows.append(
                {
                    "table_id": str(table_id),
                    "cohort_key": str(cohort_key),
                    "segment": segment,
                    **_summarize_rows(cohort.loc[cohort["block"].isin(blocks)]),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["table_id", "cohort_key", "segment"], kind="stable"
    ).reset_index(drop=True)


def evaluate_causal_leader_moments(metrics: pd.DataFrame) -> dict[str, Any]:
    """Evaluate only D-1 dynamic identity cohorts against fixed gates."""

    if metrics.empty:
        return {
            "overall_conclusion": "no_causal_leader_moments",
            "causal_evaluated_cohorts": 0,
            "causal_adequately_sampled_cohorts": 0,
            "causal_stable_positive_cohorts": 0,
            "causal_high_win_cohorts": 0,
            "cohort_evaluation": [],
        }
    causal = metrics.loc[metrics["table_id"].eq("causal_rule_x_identity")]
    rows = []
    for cohort_key, group in causal.groupby("cohort_key", sort=True):
        indexed = group.set_index("segment")
        development = indexed.loc["development"]
        validation = indexed.loc["validation"]
        development_sample = _passes_sample(
            development,
            minimum_trades=MIN_DEVELOPMENT_TRADES,
            minimum_days=MIN_DEVELOPMENT_DAYS,
        )
        validation_sample = _passes_sample(
            validation,
            minimum_trades=MIN_VALIDATION_TRADES,
            minimum_days=MIN_VALIDATION_DAYS,
        )
        stable_positive = (
            development_sample
            and validation_sample
            and _positive_metric(development)
            and _positive_metric(validation)
        )
        high_win = stable_positive and (
            float(development["win_rate_pct"]) >= MIN_HIGH_WIN_RATE_PCT
            and float(validation["win_rate_pct"]) >= MIN_HIGH_WIN_RATE_PCT
        )
        if not development_sample:
            status = "development_insufficient"
        elif not _positive_metric(development):
            status = "not_development_candidate"
        elif not validation_sample:
            status = "validation_insufficient"
        elif not _positive_metric(validation):
            status = "validation_failed"
        elif high_win:
            status = "historical_high_win_confirmed"
        else:
            status = "historical_positive_low_win"
        rows.append(
            {
                "cohort_key": str(cohort_key),
                "status": status,
                "adequately_sampled": bool(development_sample and validation_sample),
                "stable_positive": bool(stable_positive),
                "high_win": bool(high_win),
                **_prefixed_metric(development, "development"),
                **_prefixed_metric(validation, "validation"),
            }
        )
    high_win_count = sum(bool(row["high_win"]) for row in rows)
    stable_count = sum(bool(row["stable_positive"]) for row in rows)
    adequately_sampled_count = sum(bool(row["adequately_sampled"]) for row in rows)
    if high_win_count:
        conclusion = "causal_high_win_moment_found_in_reused_history"
    elif stable_count:
        conclusion = "causal_positive_low_win_moment_found_in_reused_history"
    else:
        conclusion = "no_stable_causal_leader_pullback_moment"
    return {
        "overall_conclusion": conclusion,
        "causal_evaluated_cohorts": len(rows),
        "causal_adequately_sampled_cohorts": adequately_sampled_count,
        "causal_stable_positive_cohorts": stable_count,
        "causal_high_win_cohorts": high_win_count,
        "cohort_evaluation": rows,
    }


def load_cycle_leader_pullback_study_data() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, Any],
    dict[str, Any],
]:
    """Build all period identities, moments, outcomes and metrics from local data."""

    from .concept_cycles import build_cycle_candidates, load_cycle_research_inputs
    from .cycle_leader_study import (
        build_cycle_leader_summary,
        build_dynamic_cycle_leaders,
        build_observed_cycle_periods,
        build_realized_cycle_leaders,
    )
    from .event_neutral_days import load_event_neutral_inputs
    from .event_neutral_minutes import load_complete_event_neutral_5m_bars
    from .event_recognition_falsification import (
        chronological_event_blocks,
        load_event_falsification_inputs,
    )
    from .individual_leader_study import build_spell_identities

    event_inputs = load_event_falsification_inputs()
    cycle_inputs = load_cycle_research_inputs()
    if cycle_inputs.split.discovery_dates[-1] != event_inputs.discovery_end:
        raise ValueError("event and cycle discovery boundaries must match")
    cycle_states = build_cycle_candidates(
        cycle_inputs.concept_bars,
        cycle_inputs.market_returns,
    )
    spells = build_spell_identities(event_inputs.candidates)
    periods = build_observed_cycle_periods(cycle_states, spells)
    realized = build_realized_cycle_leaders(
        periods,
        spells,
        event_inputs.stock_bars,
        cycle_inputs.concept_bars,
    )

    neutral_inputs = load_event_neutral_inputs()
    candidates = neutral_inputs.candidates.copy()
    targets = candidates.loc[
        :, ["cycle_id", "sector_id", "entry_date", "context_date"]
    ].drop_duplicates(["cycle_id", "entry_date"])
    dynamic = build_dynamic_cycle_leaders(
        periods,
        spells,
        targets,
        neutral_inputs.stock_bars,
        cycle_inputs.concept_bars,
    )
    period_summary = build_cycle_leader_summary(periods, realized, dynamic)
    identified = attach_cycle_leader_identities(candidates, dynamic, realized)
    minute_bars = load_complete_event_neutral_5m_bars(candidates)
    moments = build_leader_pullback_moments(identified, minute_bars)
    blocks = chronological_event_blocks(
        tuple(sorted(pd.to_datetime(candidates["entry_date"]).dt.date.unique())),
        block_count=5,
    ).rename(columns={"source_date": "entry_date"})
    moments["entry_date"] = pd.to_datetime(moments["entry_date"]).dt.date
    moments = moments.merge(
        blocks,
        on="entry_date",
        how="left",
        validate="many_to_one",
    )
    trades = label_leader_pullback_moments(
        moments,
        neutral_inputs.stock_bars,
        trading_dates=neutral_inputs.trading_dates,
    )
    cohorts = build_leader_moment_cohort_trades(trades)
    metrics = build_leader_moment_metrics(cohorts)
    evaluation = evaluate_causal_leader_moments(metrics)
    metadata = _build_study_metadata(
        event_inputs=event_inputs,
        cycle_inputs=cycle_inputs,
        neutral_inputs=neutral_inputs,
        periods=periods,
        realized=realized,
        dynamic=dynamic,
        candidates=candidates,
        minute_bars=minute_bars,
        moments=moments,
        trades=trades,
    )
    return period_summary, trades, metrics, evaluation, metadata


def run_cycle_leader_pullback_study() -> dict[str, Any]:
    """Run the frozen cycle-leader pullback study."""

    return build_cycle_leader_pullback_report(
        *load_cycle_leader_pullback_study_data()
    )


def build_cycle_leader_pullback_report(
    period_summary: pd.DataFrame,
    trades: pd.DataFrame,
    metrics: pd.DataFrame,
    evaluation: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Build exhaustive period evidence with causal and oracle tables separated."""

    report_segments = ("all", "development", "validation")
    selected_metrics = metrics.loc[metrics["segment"].isin(report_segments)]
    causal = selected_metrics.loc[
        selected_metrics["table_id"].eq("causal_rule_x_identity")
    ]
    oracle = selected_metrics.loc[
        selected_metrics["table_id"].eq("oracle_rule_x_identity")
    ]
    attribution = selected_metrics.loc[
        selected_metrics["table_id"].str.startswith("causal_rule_x_")
        & selected_metrics["table_id"].ne("causal_rule_x_identity")
    ]
    moment_columns = [
        column
        for column in (
            "observation_id",
            "event_id",
            "cycle_id",
            "sector_id",
            "concept_name",
            "vt_symbol",
            "stock_name",
            "entry_date",
            "moment_rule",
            "observed_at",
            "entry_time",
            "entry_price_raw",
            "drawdown_from_session_high_pct",
            "signal_time_bucket",
            "drawdown_bucket",
            "intraday_volume_class",
            "market_regime",
            "dynamic_rank",
            "dynamic_pool_size",
            "dynamic_top3_qualified",
            "dynamic_top1",
            "dynamic_top3",
            "realized_market_rank",
            "realized_return_rank",
            "normal_status",
            "net_return_pct",
            "double_cost_net_return_pct",
        )
        if column in trades
    ]
    coverage = dict(metadata.get("coverage", {}))
    coverage.setdefault("observed_periods", int(len(period_summary)))
    coverage.setdefault("pullback_moments", int(len(trades)))
    return {
        "evidence_level": STUDY_EVIDENCE_LEVEL,
        "overall_conclusion": str(evaluation["overall_conclusion"]),
        "formal_metrics": None,
        "formal_rule_selected": False,
        "strict_historical_top3_claim": False,
        "historical_validation_values_read": True,
        "outer_holdout_price_values_read": False,
        "late_segment_is_unseen_validation": False,
        "frozen_contract": {
            "period": "breakout_trend concept cycle",
            "candidate_pool": "event_candidate_pool",
            "oracle_identity": "completed-period market and return Top1/Top3 labels",
            "causal_identity": "D-1 dynamic Top1/Top3",
            "dynamic_minimum_pool": 3,
            "moment_rules": list(MOMENT_RULES),
            "entry": "first completed 5m moment per rule; next 5m open",
            "exit": "first sellable D+1 official close with normal and double costs",
            "development_blocks": sorted(DEVELOPMENT_BLOCKS),
            "validation_blocks": sorted(VALIDATION_BLOCKS),
        },
        "coverage": coverage,
        "causal_evaluation": _json_safe(dict(evaluation)),
        "period_leaders": _records(period_summary),
        "causal_metrics": _records(causal),
        "oracle_metrics": _records(oracle),
        "causal_attribution_metrics": _records(attribution),
        "individual_moments": _records(trades.loc[:, moment_columns]),
        "input_fingerprints": dict(metadata.get("input_fingerprints", {})),
        "limitations": [
            "period candidates are event-recognized stocks, not the complete historical concept membership",
            "realized leader ranks use the completed period and are descriptive oracle labels only",
            "dynamic ranks are causal but only cover stocks already recognized by D-1",
            "minute paths cover S+1..S+5 event-neutral days rather than every session in each full cycle",
            "blocks 4-5 were visible in earlier studies and are not an untouched outer holdout",
        ],
    }


def render_cycle_leader_pullback_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def render_cycle_leader_pullback_markdown(report: Mapping[str, Any]) -> str:
    coverage = report["coverage"]
    evaluation = report["causal_evaluation"]
    lines = [
        "# AlphaAgent 各阶段龙头回调时刻研究",
        "",
        f"结论：`{report['overall_conclusion']}`  ",
        "事后阶段龙头：完整周期市场辨识度/收益 Top3，只用于解释  ",
        "D-1 动态龙头：当时已识别候选中的 Top1/Top3，只有该身份进入因果统计  ",
        f"周期/三只以上周期/分钟/回调时刻：`{coverage.get('observed_periods', 0)}/"
        f"{coverage.get('periods_with_three_candidates', 0)}/"
        f"{coverage.get('minute_rows', 0)}/{coverage.get('pullback_moments', 0)}`  ",
        f"因果规则组/充分样本组/稳定正期望/高胜率：`{evaluation['causal_evaluated_cohorts']}/"
        f"{evaluation['causal_adequately_sampled_cohorts']}/"
        f"{evaluation['causal_stable_positive_cohorts']}/"
        f"{evaluation['causal_high_win_cohorts']}`",
        "",
        "## D-1 动态龙头回调结果",
        "",
        "| Identity/rule | Segment | Trades | Days | Win | Mean | PF | 2x mean | Compound | Drawdown |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(_metric_markdown_rows(report["causal_metrics"]))
    lines.extend(
        [
            "",
            "## 事后阶段龙头描述（不可交易）",
            "",
            "| Identity/rule | Segment | Trades | Days | Win | Mean | PF | 2x mean | Compound | Drawdown |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(_metric_markdown_rows(report["oracle_metrics"]))
    lines.extend(
        [
            "",
            "## 全部概念主升周期龙头",
            "",
            "| Start | End | Concept | Status | Candidates | 事后辨识度 Top3 | 事后收益 Top3 | Dynamic sessions/qualified | Oracle Top1 in dynamic Top3 |",
            "| --- | --- | --- | --- | ---: | --- | --- | ---: | ---: |",
        ]
    )
    for row in report["period_leaders"]:
        lines.append(
            f"| {row['period_start']} | {row['period_end']} | {row['concept_name']} "
            f"(`{row['sector_id']}`) | `{row['period_status']}` | {row['candidate_count']} | "
            f"{_table_text(row['realized_market_top3'])} | "
            f"{_table_text(row['realized_return_top3'])} | "
            f"{row['dynamic_sessions']}/{row['qualified_dynamic_sessions']} | "
            f"{_pct(row['realized_market_top1_dynamic_top3_retention_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "本报告把事后龙头和当时可识别龙头分开。历史完整概念成员缺失，因此这里是"
            "事件候选池内的全周期清单，不是严格全成员 Top3；任何 oracle 高收益都不能生成订单。",
            "",
        ]
    )
    return "\n".join(lines)


def classify_signal_time(value: Any) -> str:
    try:
        minutes = float(value)
    except (TypeError, ValueError):
        return "missing"
    if not np.isfinite(minutes) or minutes <= 0:
        return "missing"
    if minutes <= 30:
        return "opening_30"
    if minutes <= 120:
        return "morning_31_120"
    return "afternoon_121_plus"


def classify_drawdown(value: Any) -> str:
    try:
        drawdown = float(value)
    except (TypeError, ValueError):
        return "missing"
    if not np.isfinite(drawdown) or drawdown > 0:
        return "missing"
    depth = abs(drawdown)
    if depth < 1:
        return "shallow_0_1"
    if depth < 3:
        return "moderate_1_3"
    if depth < 5:
        return "deep_3_5"
    return "very_deep_5_plus"


def _append_moment_memberships(
    rows: list[dict[str, Any]],
    record: dict[str, Any],
) -> None:
    rule = str(record["moment_rule"])
    if bool(record["dynamic_top3_qualified"]):
        if bool(record["dynamic_top1"]):
            _append_membership(
                rows,
                record,
                "causal_rule_x_identity",
                f"dynamic_top1|{rule}",
            )
        if bool(record["dynamic_top3"]):
            _append_membership(
                rows,
                record,
                "causal_rule_x_identity",
                f"dynamic_top3|{rule}",
            )
            for dimension in (
                "signal_time_bucket",
                "drawdown_bucket",
                "intraday_volume_class",
                "market_regime",
            ):
                _append_membership(
                    rows,
                    record,
                    f"causal_rule_x_{dimension}",
                    f"dynamic_top3|{rule}|{record[dimension]}",
                )
    for flag in (
        "oracle_market_top1",
        "oracle_market_top3",
        "oracle_return_top1",
        "oracle_return_top3",
    ):
        if bool(record[flag]):
            _append_membership(
                rows,
                record,
                "oracle_rule_x_identity",
                f"{flag}|{rule}",
            )


def _append_membership(
    rows: list[dict[str, Any]],
    record: Mapping[str, Any],
    table_id: str,
    cohort_key: str,
) -> None:
    rows.append({**record, "table_id": table_id, "cohort_key": cohort_key})


def _metric_segments() -> tuple[tuple[str, frozenset[int]], ...]:
    return (
        ("all", frozenset({1, 2, 3, 4, 5})),
        ("development", DEVELOPMENT_BLOCKS),
        ("validation", VALIDATION_BLOCKS),
        *((f"block_{block}", frozenset({block})) for block in range(1, 6)),
    )


def _summarize_rows(rows: pd.DataFrame) -> dict[str, Any]:
    closed = rows.loc[rows["normal_status"].eq("closed")].copy()
    returns = pd.to_numeric(closed["net_return_pct"], errors="coerce").dropna()
    stressed = pd.to_numeric(
        closed.loc[returns.index, "double_cost_net_return_pct"], errors="coerce"
    ).dropna()
    compound, drawdown = _daily_compounding(closed.loc[returns.index])
    return {
        "signals": int(len(rows)),
        "closed_trades": int(len(returns)),
        "source_days": int(closed.loc[returns.index, "entry_date"].nunique()),
        "win_rate_pct": _win_rate(returns),
        "mean_net_return_pct": _mean(returns),
        "median_net_return_pct": _median(returns),
        "profit_factor": _profit_factor(returns),
        "double_cost_mean_net_return_pct": _mean(stressed),
        "compound_return_pct": compound,
        "maximum_drawdown_pct": drawdown,
    }


def _daily_compounding(rows: pd.DataFrame) -> tuple[float | None, float | None]:
    if rows.empty:
        return None, None
    frame = rows.copy()
    frame["net_return_pct"] = pd.to_numeric(frame["net_return_pct"], errors="coerce")
    daily = frame.dropna(subset=["net_return_pct"]).groupby(
        "entry_date", sort=True
    )["net_return_pct"].mean()
    if daily.empty:
        return None, None
    equity = (1.0 + daily / 100.0).cumprod()
    running_peak = equity.cummax().clip(lower=1.0)
    drawdown = equity / running_peak - 1.0
    return float((equity.iloc[-1] - 1.0) * 100.0), float(drawdown.min() * 100.0)


def _passes_sample(
    metric: pd.Series,
    *,
    minimum_trades: int,
    minimum_days: int,
) -> bool:
    return (
        int(metric["closed_trades"]) >= minimum_trades
        and int(metric["source_days"]) >= minimum_days
    )


def _positive_metric(metric: pd.Series) -> bool:
    values = (
        metric["mean_net_return_pct"],
        metric["double_cost_mean_net_return_pct"],
        metric["profit_factor"],
    )
    if any(value is None or pd.isna(value) for value in values):
        return False
    return float(values[0]) > 0 and float(values[1]) > 0 and float(values[2]) > 1


def _prefixed_metric(metric: pd.Series, prefix: str) -> dict[str, Any]:
    return {
        f"{prefix}_{column}": _json_safe(metric[column])
        for column in (
            "closed_trades",
            "source_days",
            "win_rate_pct",
            "mean_net_return_pct",
            "profit_factor",
            "double_cost_mean_net_return_pct",
            "compound_return_pct",
            "maximum_drawdown_pct",
        )
    }


def _build_study_metadata(
    *,
    event_inputs: Any,
    cycle_inputs: Any,
    neutral_inputs: Any,
    periods: pd.DataFrame,
    realized: pd.DataFrame,
    dynamic: pd.DataFrame,
    candidates: pd.DataFrame,
    minute_bars: pd.DataFrame,
    moments: pd.DataFrame,
    trades: pd.DataFrame,
) -> dict[str, Any]:
    qualified_dynamic = dynamic.loc[dynamic["dynamic_top3_qualified"].astype(bool)]
    moment_counts = moments["moment_rule"].value_counts().sort_index()
    status_counts = trades["normal_status"].value_counts(dropna=False).sort_index()
    cycle_fingerprints = {
        name: value.as_dict() for name, value in cycle_inputs.component_fingerprints
    }
    fingerprints = {
        **dict(event_inputs.input_fingerprints),
        **dict(neutral_inputs.input_fingerprints),
        **cycle_fingerprints,
        "cycle_leader_periods": fingerprint_frame(
            periods, identity_columns=("cycle_id",)
        ).as_dict(),
        "cycle_leader_realized": fingerprint_frame(
            realized, identity_columns=("cycle_id", "vt_symbol")
        ).as_dict(),
        "cycle_leader_dynamic": fingerprint_frame(
            dynamic, identity_columns=("cycle_id", "entry_date", "vt_symbol")
        ).as_dict(),
        "cycle_leader_minutes": fingerprint_frame(
            minute_bars, identity_columns=("vt_symbol", "bar_time", "interval")
        ).as_dict(),
        "cycle_leader_moments": fingerprint_frame(
            moments, identity_columns=("observation_id",)
        ).as_dict(),
        "cycle_leader_moment_outcomes": fingerprint_frame(
            trades, identity_columns=("observation_id",)
        ).as_dict(),
    }
    coverage = {
        **dict(event_inputs.coverage),
        "observed_periods": int(len(periods)),
        "completed_periods": int(periods["period_status"].eq("completed").sum()),
        "censored_periods": int(
            periods["period_status"].eq("censored_at_discovery_end").sum()
        ),
        "periods_with_three_candidates": int(periods["candidate_count"].ge(3).sum()),
        "period_candidate_spells": int(len(realized)),
        "event_neutral_candidates": int(len(candidates)),
        "dynamic_leader_rows": int(len(dynamic)),
        "dynamic_sessions": int(dynamic[["cycle_id", "entry_date"]].drop_duplicates().shape[0]),
        "qualified_dynamic_sessions": int(
            qualified_dynamic[["cycle_id", "entry_date"]].drop_duplicates().shape[0]
        ),
        "minute_rows": int(len(minute_bars)),
        "pullback_moments": int(len(moments)),
        "moment_counts": {str(key): int(value) for key, value in moment_counts.items()},
        "qualified_dynamic_top1_moments": int(moments["dynamic_top1"].astype(bool).sum()),
        "qualified_dynamic_top3_moments": int(moments["dynamic_top3"].astype(bool).sum()),
        "oracle_market_top1_moments": int(
            moments["oracle_market_top1"].astype(bool).sum()
        ),
        "normal_status_counts": {
            str(key): int(value) for key, value in status_counts.items()
        },
        "strict_historical_membership_rows_read": 0,
        "outer_holdout_price_values_read": False,
        "current_membership_rows_read": 0,
    }
    return {
        "coverage": coverage,
        "input_fingerprints": fingerprints,
        "discovery_start": event_inputs.discovery_start,
        "discovery_end": event_inputs.discovery_end,
    }


def _empty_metrics() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "table_id",
            "cohort_key",
            "segment",
            "signals",
            "closed_trades",
            "source_days",
            "win_rate_pct",
            "mean_net_return_pct",
            "median_net_return_pct",
            "profit_factor",
            "double_cost_mean_net_return_pct",
            "compound_return_pct",
            "maximum_drawdown_pct",
        ]
    )


def _metric_markdown_rows(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    if not rows:
        return ["| - | - | - | - | - | - | - | - | - | - |"]
    return [
        f"| `{row['cohort_key']}` | `{row['segment']}` | {row['closed_trades']} | "
        f"{row['source_days']} | {_pct(row['win_rate_pct'])} | "
        f"{_pct(row['mean_net_return_pct'])} | {_number(row['profit_factor'])} | "
        f"{_pct(row['double_cost_mean_net_return_pct'])} | "
        f"{_pct(row['compound_return_pct'])} | {_pct(row['maximum_drawdown_pct'])} |"
        for row in rows
    ]


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [_json_safe(record) for record in frame.to_dict("records")]


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _win_rate(values: pd.Series) -> float | None:
    return float(values.gt(0).mean() * 100.0) if len(values) else None


def _mean(values: pd.Series) -> float | None:
    return float(values.mean()) if len(values) else None


def _median(values: pd.Series) -> float | None:
    return float(values.median()) if len(values) else None


def _profit_factor(values: pd.Series) -> float | None:
    if values.empty:
        return None
    gains = float(values.loc[values.gt(0)].sum())
    losses = abs(float(values.loc[values.lt(0)].sum()))
    if losses == 0:
        return math.inf if gains > 0 else None
    return gains / losses


def _finite_float(value: Any, *, allow_infinite: bool = False) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or (math.isinf(numeric) and not allow_infinite):
        return None
    return numeric


def _pct(value: Any) -> str:
    numeric = _finite_float(value)
    return "-" if numeric is None else f"{numeric:.4f}%"


def _number(value: Any) -> str:
    numeric = _finite_float(value, allow_infinite=True)
    if numeric is None:
        return "-"
    return "inf" if math.isinf(numeric) else f"{numeric:.4f}"


def _table_text(value: Any) -> str:
    return str(value or "-").replace("|", "/")


def _moment_rule_masks(panel: pd.DataFrame) -> dict[str, pd.Series]:
    ma5 = pd.to_numeric(panel["ma5"], errors="coerce")
    ma10 = pd.to_numeric(panel["ma10"], errors="coerce")
    reversal = (
        panel["close_price"].gt(panel["previous_bar_close"])
        & panel["previous_bar_close"].le(panel["two_bars_ago_close"])
    )
    executable = (
        panel["next_bar_time"].notna()
        & pd.to_numeric(panel["next_bar_open"], errors="coerce").gt(0)
    )
    return {
        "ma5_touch_hold": executable
        & ma5.gt(0)
        & panel["low_price"].le(ma5)
        & panel["close_price"].ge(ma5),
        "ma10_touch_hold": executable
        & ma10.gt(0)
        & panel["low_price"].le(ma10)
        & panel["close_price"].ge(ma10),
        "vwap_reclaim": executable & panel["vwap_reclaim"].astype(bool),
        "drawdown_1_reversal": executable
        & reversal
        & panel["drawdown_from_session_high_pct"].le(-1.0),
        "drawdown_3_reversal": executable
        & reversal
        & panel["drawdown_from_session_high_pct"].le(-3.0),
    }


def _extract_first_moment(
    panel: pd.DataFrame,
    *,
    rule: str,
    mask: pd.Series,
) -> pd.DataFrame:
    selected = panel.loc[mask].drop_duplicates("event_id", keep="first").copy()
    if selected.empty:
        return selected
    selected["moment_rule"] = rule
    selected["observed_at"] = pd.to_datetime(selected["bar_time"], errors="raise")
    selected["entry_time"] = pd.to_datetime(
        selected["next_bar_time"], errors="raise"
    )
    selected["entry_price_raw"] = pd.to_numeric(
        selected["next_bar_open"], errors="raise"
    )
    selected["observation_id"] = (
        selected["event_id"].astype(str)
        + ":"
        + selected["moment_rule"]
        + ":"
        + selected["observed_at"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    )
    return selected


def _empty_moments(candidates: pd.DataFrame) -> pd.DataFrame:
    columns = [
        *candidates.columns,
        "moment_rule",
        "observed_at",
        "entry_time",
        "entry_price_raw",
        "observation_id",
        "session_high",
        "drawdown_from_session_high_pct",
        "intraday_volume_ratio",
        "intraday_volume_class",
        "signal_minutes_from_open",
        "signal_time_bucket",
        "drawdown_bucket",
        "market_regime",
    ]
    return pd.DataFrame(columns=list(dict.fromkeys(columns)))


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
