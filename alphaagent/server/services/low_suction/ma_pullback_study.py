"""Causal MA5/MA10 pullback-round validation for event-recognized leaders."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .event_neutral_days import EventNeutralInputs, load_event_neutral_comparison_inputs
from .event_recognition_5m_study import build_event_5m_state_panel
from .event_recognition_falsification import chronological_event_blocks
from .event_recognition_minutes import INTERVAL
from .outcome_group_minutes import load_outcome_group_5m_manifest
from .outcome_group_study import classify_volume_ratio, label_outcome_group_trades
from .research_protocol import fingerprint_frame
from .stock_main_rise_audit import build_stock_main_rise_features


ADAPTIVE_ARM = "adaptive_ma5_ma10"
ARM_REFERENCES: dict[str, dict[int, str]] = {
    ADAPTIVE_ARM: {1: "ma5", 2: "ma10"},
    "always_ma5": {1: "ma5", 2: "ma5"},
    "always_ma10": {1: "ma10", 2: "ma10"},
    "reversed_ma10_ma5": {1: "ma10", 2: "ma5"},
}
CONTROL_ARMS = tuple(arm for arm in ARM_REFERENCES if arm != ADAPTIVE_ARM)
ROUND_REFERENCE_CANONICAL_ARMS = {
    ("first", "ma5"): ADAPTIVE_ARM,
    ("first", "ma10"): "always_ma10",
    ("second", "ma5"): "always_ma5",
    ("second", "ma10"): ADAPTIVE_ARM,
}
DEVELOPMENT_BLOCKS = frozenset({1, 2, 3})
VALIDATION_BLOCKS = frozenset({4, 5})
MIN_DEVELOPMENT_TRADES = 30
MIN_DEVELOPMENT_DAYS = 20
MIN_VALIDATION_TRADES = 20
MIN_VALIDATION_DAYS = 15
MIN_HIGH_WIN_RATE_PCT = 55.0
STUDY_EVIDENCE_LEVEL = "historical_event_rank_1_3_ma5_ma10_pullback_validation"

ROUND_REQUIRED_COLUMNS = (
    "event_id",
    "leader_spell_id",
    "recognition_source_date",
    "context_date",
    "entry_date",
    "spell_session_offset",
    "vt_symbol",
    "main_rise",
)
SIGNAL_CONTEXT_COLUMNS = (
    "leader_spell_id",
    "recognition_source_date",
    "context_date",
    "spell_session_offset",
    "stock_close",
    "ma5",
    "ma10",
    "ma20",
    "pullback_round",
    "pullback_round_group",
    "completed_rebound",
    "concept_main_rise",
    "stock_above_ma5",
    "stock_trend_order",
    "stock_strong_main_rise",
    "daily_volume_ratio",
    "daily_volume_class",
)
PROHIBITED_SIGNAL_COLUMNS = frozenset(
    {
        "net_return_pct",
        "double_cost_net_return_pct",
        "gross_return_pct",
        "mfe_pct",
        "mae_pct",
        "exit_price",
        "outcome_group",
    }
)


def build_pullback_round_panel(
    candidates: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> pd.DataFrame:
    """Attach D-1 trend features and the causal current pullback round."""

    _require_columns(candidates, ROUND_REQUIRED_COLUMNS, "pullback candidate")
    features = build_stock_main_rise_features(
        candidates,
        daily_bars,
        trading_dates=trading_dates,
    )
    daily_context = _build_daily_context(
        daily_bars,
        trading_dates=trading_dates,
        symbols=set(features["vt_symbol"].astype(str)),
    )
    panel = features.merge(
        daily_context,
        left_on=["vt_symbol", "context_date"],
        right_on=["vt_symbol", "trade_date"],
        how="left",
        validate="many_to_one",
    ).drop(columns="trade_date")
    panel["recognition_source_date"] = pd.to_datetime(
        panel["recognition_source_date"], errors="raise"
    ).dt.normalize()
    panel["spell_session_offset"] = pd.to_numeric(
        panel["spell_session_offset"], errors="raise"
    ).astype(int)
    if panel["daily_return_pct"].isna().any():
        raise ValueError("every pullback context requires a completed daily return")

    labelled = [
        _label_spell_pullback_rounds(group)
        for _, group in panel.groupby("leader_spell_id", sort=False)
    ]
    result = pd.concat(labelled, ignore_index=True) if labelled else panel.copy()
    result["pullback_round_group"] = np.select(
        [result["pullback_round"].eq(1), result["pullback_round"].eq(2)],
        ["first", "second"],
        default="third_plus",
    )
    result["daily_volume_class"] = result["daily_volume_ratio"].map(
        classify_volume_ratio
    )
    result["evidence_level"] = STUDY_EVIDENCE_LEVEL
    return result.sort_values(
        ["entry_date", "event_id"], kind="stable"
    ).reset_index(drop=True)


def build_ma_pullback_signals(
    pullback_panel: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Extract the first executable touch-and-reclaim for every frozen arm."""

    _reject_signal_leakage(pullback_panel, minute_bars)
    _require_columns(
        pullback_panel,
        ("event_id", *SIGNAL_CONTEXT_COLUMNS),
        "pullback panel",
    )
    eligible_candidates = pullback_panel.loc[
        pullback_panel["concept_main_rise"].astype(bool)
        & pullback_panel["pullback_round"].isin((1, 2))
    ].copy()
    if eligible_candidates.empty:
        return _empty_signals(pullback_panel)

    base = build_event_5m_state_panel(eligible_candidates, minute_bars)
    context = eligible_candidates.loc[
        :, ["event_id", *SIGNAL_CONTEXT_COLUMNS]
    ].copy()
    panel = base.merge(context, on="event_id", how="left", validate="many_to_one")
    panel = panel.sort_values(["event_id", "bar_time"], kind="stable")
    grouped = panel.groupby("event_id", sort=False)
    prior_three_volume = grouped["volume"].transform(
        lambda values: values.shift(1).rolling(3, min_periods=3).mean()
    )
    panel["intraday_volume_ratio"] = panel["volume"] / prior_three_volume.where(
        prior_three_volume.gt(0)
    )
    panel["signal_minutes_from_open"] = (grouped.cumcount() + 1) * 5

    arms = [
        _extract_arm_signals(panel, arm=arm, references=references)
        for arm, references in ARM_REFERENCES.items()
    ]
    nonempty = [frame for frame in arms if not frame.empty]
    if not nonempty:
        return _empty_signals(pullback_panel)
    signals = pd.concat(nonempty, ignore_index=True)
    signals["intraday_volume_class"] = signals["intraday_volume_ratio"].map(
        classify_volume_ratio
    )
    ranks = pd.to_numeric(signals["recognition_rank"], errors="raise").astype(int)
    if not ranks.isin((1, 2, 3)).all():
        raise ValueError("pullback leader ranks must be 1 through 3")
    signals["leader_rank_group"] = np.where(ranks.eq(1), "rank_1", "rank_2_3")
    signals["market_regime"] = (
        signals["active_direction"].astype(str)
        + "/"
        + signals["danger_state"].astype(str)
    )
    signals["evidence_level"] = STUDY_EVIDENCE_LEVEL
    if signals.duplicated(["event_id", "rule_arm"]).any():
        raise ValueError("each event and frozen arm can emit at most one signal")
    return signals.sort_values(
        ["entry_date", "event_id", "rule_arm"], kind="stable"
    ).reset_index(drop=True)


def label_ma_pullback_trades(
    signals: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    trading_dates: tuple[date, ...],
) -> pd.DataFrame:
    """Attach existing normal and double-cost D+1 cash outcomes."""

    return label_outcome_group_trades(
        signals,
        daily_bars,
        trading_dates=trading_dates,
    )


def build_ma_pullback_cohort_trades(trades: pd.DataFrame) -> pd.DataFrame:
    """Expand frozen rule and attribution memberships after outcomes exist."""

    required = (
        "observation_id",
        "event_id",
        "entry_date",
        "block",
        "rule_arm",
        "reference_line",
        "pullback_round_group",
        "concept_main_rise",
        "stock_trend_order",
        "stock_strong_main_rise",
        "daily_volume_class",
        "intraday_volume_class",
        "leader_rank_group",
        "market_regime",
        "normal_status",
        "stressed_status",
        "net_return_pct",
        "double_cost_net_return_pct",
    )
    _require_columns(trades, required, "MA pullback trade")
    rows: list[dict[str, Any]] = []
    for record in trades.to_dict("records"):
        _append_cohort_memberships(rows, record)
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    if result.duplicated(["observation_id", "table_id", "cohort_key"]).any():
        raise ValueError("MA pullback cohort identities must be unique")
    return result.sort_values(
        ["entry_date", "observation_id", "table_id", "cohort_key"],
        kind="stable",
    ).reset_index(drop=True)


def build_ma_pullback_metrics(cohort_trades: pd.DataFrame) -> pd.DataFrame:
    """Summarize frozen cohorts over the chronological diagnostic split."""

    required = (
        "entry_date",
        "block",
        "table_id",
        "cohort_key",
        "normal_status",
        "net_return_pct",
        "double_cost_net_return_pct",
    )
    _require_columns(cohort_trades, required, "MA pullback cohort trade")
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


def evaluate_ma_pullback_hypothesis(metrics: pd.DataFrame) -> dict[str, Any]:
    """Evaluate the adaptive arm against fixed samples and fixed controls."""

    adaptive = _arm_segment_metrics(metrics, ADAPTIVE_ARM)
    development = adaptive.get("development")
    validation = adaptive.get("validation")
    adaptive_status = _time_split_status(development, validation)
    comparisons = []
    adaptive_advantage = development is not None and validation is not None
    for control_arm in CONTROL_ARMS:
        control = _arm_segment_metrics(metrics, control_arm)
        control_validation = control.get("validation")
        beats_control = _beats_control(validation, control_validation)
        adaptive_advantage = adaptive_advantage and beats_control
        comparisons.append(
            {
                "control_arm": control_arm,
                "control_available": control_validation is not None,
                "adaptive_beats_validation_win_and_double_cost": beats_control,
                "adaptive_validation_win_rate_pct": _metric_value(
                    validation, "win_rate_pct"
                ),
                "control_validation_win_rate_pct": _metric_value(
                    control_validation, "win_rate_pct"
                ),
                "adaptive_validation_double_cost_mean_net_return_pct": _metric_value(
                    validation, "double_cost_mean_net_return_pct"
                ),
                "control_validation_double_cost_mean_net_return_pct": _metric_value(
                    control_validation, "double_cost_mean_net_return_pct"
                ),
            }
        )
    if adaptive_status == "high_win_confirmed" and adaptive_advantage:
        conclusion = "historical_adaptive_candidate_found"
    elif adaptive_status == "positive_confirmed" and adaptive_advantage:
        conclusion = "historical_positive_adaptive_candidate_found"
    elif adaptive_status in {"high_win_confirmed", "positive_confirmed"}:
        conclusion = "adaptive_rule_positive_without_control_advantage"
    else:
        conclusion = "ma5_ma10_hypothesis_not_confirmed"
    return {
        "adaptive_arm": ADAPTIVE_ARM,
        "adaptive_status": adaptive_status,
        "adaptive_advantage": bool(adaptive_advantage),
        "overall_conclusion": conclusion,
        "development": _series_record(development),
        "validation": _series_record(validation),
        "control_comparison": comparisons,
    }


def load_ma_pullback_study_data(
    inputs: EventNeutralInputs | None = None,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, Any],
    dict[str, Any],
]:
    """Load complete historical inputs and execute the frozen study once."""

    selected_inputs = inputs or load_event_neutral_comparison_inputs()
    candidates = selected_inputs.candidates.copy()
    if candidates.empty:
        raise ValueError("MA pullback comparison candidates are required")
    minute_bars, manifest = _load_complete_candidate_minutes(candidates)
    pullback_panel = build_pullback_round_panel(
        candidates,
        selected_inputs.stock_bars,
        trading_dates=selected_inputs.trading_dates,
    )
    signals = build_ma_pullback_signals(pullback_panel, minute_bars)
    blocks = chronological_event_blocks(
        tuple(sorted(pd.to_datetime(candidates["entry_date"]).dt.date.unique())),
        block_count=5,
    ).rename(columns={"source_date": "entry_date"})
    signals["entry_date"] = pd.to_datetime(signals["entry_date"]).dt.date
    signals = signals.merge(
        blocks,
        on="entry_date",
        how="left",
        validate="many_to_one",
    )
    trades = label_ma_pullback_trades(
        signals,
        selected_inputs.stock_bars,
        trading_dates=selected_inputs.trading_dates,
    )
    cohort_trades = build_ma_pullback_cohort_trades(trades)
    metrics = build_ma_pullback_metrics(cohort_trades)
    decision = evaluate_ma_pullback_hypothesis(metrics)
    metadata = _build_loader_metadata(
        selected_inputs,
        candidates=candidates,
        pullback_panel=pullback_panel,
        minute_bars=minute_bars,
        manifest=manifest,
        signals=signals,
        trades=trades,
    )
    return pullback_panel, signals, trades, metrics, decision, metadata


def run_ma_pullback_study() -> dict[str, Any]:
    """Run and render the frozen historical MA pullback study."""

    return build_ma_pullback_report(*load_ma_pullback_study_data())


def build_ma_pullback_report(
    pullback_panel: pd.DataFrame,
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    metrics: pd.DataFrame,
    decision: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Build decision-bearing evidence while keeping production claims closed."""

    primary_trades = trades.loc[
        trades["rule_arm"].eq(ADAPTIVE_ARM)
        & trades["stock_trend_order"].astype(bool)
    ].copy()
    closed_primary = primary_trades.loc[primary_trades["normal_status"].eq("closed")]
    best = closed_primary.sort_values("net_return_pct", ascending=False).head(20)
    worst = closed_primary.sort_values("net_return_pct", ascending=True).head(20)
    relevant_segments = ("all", "development", "validation")
    report_metrics = metrics.loc[metrics["segment"].isin(relevant_segments)]
    coverage = dict(metadata.get("coverage", {}))
    coverage.setdefault("pullback_panel_rows", int(len(pullback_panel)))
    coverage.setdefault("signals", int(len(signals)))
    coverage.setdefault("trades", int(len(trades)))
    return {
        "evidence_level": STUDY_EVIDENCE_LEVEL,
        "overall_conclusion": str(decision["overall_conclusion"]),
        "formal_metrics": None,
        "formal_rule_selected": False,
        "strict_historical_top3_claim": False,
        "historical_validation_values_read": True,
        "outer_holdout_price_values_read": False,
        "late_segment_is_unseen_validation": False,
        "frozen_contract": {
            "identity": "historical_event_recognition_rank_1_3_proxy",
            "primary_universe": "D-1 concept_main_rise and stock_trend_order",
            "round_definition": (
                "completed negative daily-return runs separated by at least one "
                "completed positive-return rebound"
            ),
            "feature_cutoff": "D-1 official close plus completed 5m signal bar",
            "entry": (
                "completed 5m low touches D-1 reference and close reclaims it; "
                "buy next 5m open"
            ),
            "exit": "first sellable D+1 official close with T+1 and costs",
            "arms": {
                arm: {
                    "first": references[1],
                    "second": references[2],
                }
                for arm, references in ARM_REFERENCES.items()
            },
            "development_blocks": sorted(DEVELOPMENT_BLOCKS),
            "validation_blocks": sorted(VALIDATION_BLOCKS),
        },
        "decision": _json_safe(dict(decision)),
        "coverage": coverage,
        "arm_metrics": _records(
            report_metrics.loc[report_metrics["table_id"].eq("arm_comparison")]
        ),
        "round_metrics": _records(
            report_metrics.loc[report_metrics["table_id"].eq("round_comparison")]
        ),
        "round_reference_metrics": _records(
            report_metrics.loc[
                report_metrics["table_id"].eq("round_reference_comparison")
            ]
        ),
        "primary_block_metrics": _records(
            metrics.loc[
                metrics["table_id"].eq("arm_comparison")
                & metrics["cohort_key"].eq(ADAPTIVE_ARM)
                & metrics["segment"].str.startswith("block_")
            ]
        ),
        "main_rise_sensitivity": _records(
            report_metrics.loc[
                report_metrics["table_id"].eq("main_rise_sensitivity")
            ]
        ),
        "attribution_metrics": _records(
            report_metrics.loc[
                report_metrics["table_id"].str.startswith("round_x_")
            ]
        ),
        "best_20_primary_trades": _records(best),
        "worst_20_primary_trades": _records(worst),
        "input_fingerprints": dict(metadata.get("input_fingerprints", {})),
        "limitations": [
            "historical identity is event-recognition Rank1-3, not strict point-in-time concept-member Top3",
            "blocks 4-5 were visible in earlier low-suction reports and are not an untouched outer holdout",
            "daily equal-weight compounding is comparative rather than a production cash portfolio",
            "volume, rank and GOLD/SILVER tables are attribution only and cannot select the rule",
            "an intraday dip that closes positive is not a completed negative daily-return round",
        ],
    }


def render_ma_pullback_json(report: Mapping[str, Any]) -> str:
    """Render deterministic machine-readable evidence."""

    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def render_ma_pullback_markdown(report: Mapping[str, Any]) -> str:
    """Render the decision-bearing MA pullback evidence in Chinese."""

    decision = report["decision"]
    coverage = report["coverage"]
    lines = [
        "# AlphaAgent MA5/MA10 回调低吸验证",
        "",
        f"结论：`{report['overall_conclusion']}`  ",
        f"自适应状态/对照优势：`{decision['adaptive_status']}/"
        f"{decision['adaptive_advantage']}`  ",
        "身份：历史事件 Rank1-3 代理，不是严格历史概念全成员 Top3  ",
        "主升：D-1 概念仍在主升，且个股 `收盘 >= MA5 > MA10 > MA20`  ",
        "第一轮回调看 D-1 MA5；完成反弹后的第二轮回调看 D-1 MA10  ",
        "触发：完成的 5 分钟 bar 触及并收回均线，下一根 5 分钟开盘买入，D+1 收盘卖出  ",
        f"候选/分钟/信号/交易：`{coverage.get('comparison_candidates', 0)}/"
        f"{coverage.get('minute_rows', 0)}/{coverage.get('signals', 0)}/"
        f"{coverage.get('trades', 0)}`",
        "",
        "## 四种冻结规则对照",
        "",
        "| Rule | Segment | Trades | Days | Win | Mean | PF | 2x mean | Compound | Drawdown |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(_metric_markdown_rows(report["arm_metrics"]))
    lines.extend(
        [
            "",
            "## 第一轮与第二轮",
            "",
            "| Round | Segment | Trades | Days | Win | Mean | PF | 2x mean | Compound | Drawdown |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(_metric_markdown_rows(report["round_metrics"]))
    lines.extend(
        [
            "",
            "## 同一轮次的均线直接对照",
            "",
            "| Round/reference | Segment | Trades | Days | Win | Mean | PF | 2x mean | Compound | Drawdown |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(_metric_markdown_rows(report["round_reference_metrics"]))
    lines.extend(
        [
            "",
            "## 自适应规则五个时间块",
            "",
            "| Rule | Segment | Trades | Days | Win | Mean | PF | 2x mean | Compound | Drawdown |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(_metric_markdown_rows(report["primary_block_metrics"]))
    lines.extend(
        [
            "",
            "## 主升口径敏感性",
            "",
            "| Universe | Segment | Trades | Days | Win | Mean | PF | 2x mean | Compound | Drawdown |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(_metric_markdown_rows(report["main_rise_sensitivity"]))
    lines.extend(
        [
            "",
            "## 金银、量能与龙位归因",
            "",
            "这些表只解释结果，不增加筛选条件，也不参与四种规则臂的选择。",
            "",
            "| Dimension | Round/value | Segment | Trades | Days | Win | Mean | 2x mean |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    attribution = list(report["attribution_metrics"])
    if not attribution:
        lines.append("| - | - | - | - | - | - | - | - |")
    for row in attribution:
        lines.append(
            f"| `{row['table_id']}` | `{row['cohort_key']}` | `{row['segment']}` | "
            f"{row['closed_trades']} | {row['source_days']} | "
            f"{_pct(row['win_rate_pct'])} | {_pct(row['mean_net_return_pct'])} | "
            f"{_pct(row['double_cost_mean_net_return_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## 研究边界",
            "",
            "本报告立即检验历史因果规则，但 blocks 4-5 已在旧研究中出现，不是未读外层留出。"
            "严格历史 Top3、正式策略胜率和生产规则继续关闭。",
            "",
        ]
    )
    return "\n".join(lines)


def _build_daily_context(
    daily_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
    symbols: set[str],
) -> pd.DataFrame:
    _require_columns(
        daily_bars,
        ("vt_symbol", "trade_date", "close_price", "volume"),
        "daily context bar",
    )
    calendar = pd.DatetimeIndex(pd.to_datetime(list(trading_dates))).normalize()
    calendar = calendar.drop_duplicates().sort_values()
    bars = daily_bars.loc[daily_bars["vt_symbol"].astype(str).isin(symbols)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.normalize()
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("daily context bar identities must be unique")
    frames = [
        _build_symbol_daily_context(str(symbol), group, calendar)
        for symbol, group in bars.groupby("vt_symbol", sort=True)
    ]
    return pd.concat(frames, ignore_index=True)


def _build_symbol_daily_context(
    vt_symbol: str,
    bars: pd.DataFrame,
    calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    frame = bars.set_index("trade_date").reindex(calendar)
    close = pd.to_numeric(frame["close_price"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    prior_volume = volume.shift(1).rolling(5, min_periods=5).mean()
    return pd.DataFrame(
        {
            "vt_symbol": vt_symbol,
            "trade_date": calendar,
            "daily_return_pct": close.pct_change(fill_method=None) * 100.0,
            "daily_volume_ratio": volume / prior_volume.where(prior_volume.gt(0)),
        }
    )


def _label_spell_pullback_rounds(group: pd.DataFrame) -> pd.DataFrame:
    ordered = group.sort_values(
        ["spell_session_offset", "context_date"], kind="stable"
    ).copy()
    current_round = 0
    decline_active = False
    completed_rebound = False
    round_values: list[int] = []
    rebound_values: list[bool] = []
    for row in ordered.itertuples(index=False):
        context_date = pd.Timestamp(row.context_date).normalize()
        recognition_date = pd.Timestamp(row.recognition_source_date).normalize()
        if context_date > recognition_date:
            daily_return = float(row.daily_return_pct)
            if daily_return < 0:
                if not decline_active and (current_round == 0 or completed_rebound):
                    current_round += 1
                decline_active = True
                completed_rebound = False
            elif daily_return > 0 and current_round > 0:
                decline_active = False
                completed_rebound = True
        if decline_active:
            candidate_round = max(current_round, 1)
        elif current_round == 0:
            candidate_round = 1
        elif completed_rebound:
            candidate_round = current_round + 1
        else:
            candidate_round = current_round
        round_values.append(candidate_round)
        rebound_values.append(completed_rebound)
    ordered["pullback_round"] = round_values
    ordered["completed_rebound"] = rebound_values
    return ordered


def _extract_arm_signals(
    panel: pd.DataFrame,
    *,
    arm: str,
    references: Mapping[int, str],
) -> pd.DataFrame:
    frame = panel.copy()
    frame["reference_line"] = frame["pullback_round"].map(references)
    frame["reference_value"] = np.where(
        frame["reference_line"].eq("ma5"), frame["ma5"], frame["ma10"]
    )
    reference = pd.to_numeric(frame["reference_value"], errors="coerce")
    eligible = (
        reference.gt(0)
        & pd.to_numeric(frame["low_price"], errors="coerce").le(reference)
        & pd.to_numeric(frame["close_price"], errors="coerce").ge(reference)
        & frame["next_bar_time"].notna()
        & pd.to_numeric(frame["next_bar_open"], errors="coerce").gt(0)
    )
    selected = frame.loc[eligible].drop_duplicates("event_id", keep="first").copy()
    if selected.empty:
        return selected
    selected["rule_arm"] = arm
    selected["observed_at"] = pd.to_datetime(selected["bar_time"], errors="raise")
    selected["entry_time"] = pd.to_datetime(
        selected["next_bar_time"], errors="raise"
    )
    selected["entry_price_raw"] = pd.to_numeric(
        selected["next_bar_open"], errors="raise"
    )
    selected["signal_distance_to_reference_pct"] = (
        selected["close_price"] / selected["reference_value"] - 1.0
    ) * 100.0
    selected["signal_touch_depth_pct"] = (
        selected["low_price"] / selected["reference_value"] - 1.0
    ) * 100.0
    selected["observation_id"] = (
        selected["event_id"].astype(str)
        + ":"
        + selected["rule_arm"]
        + ":"
        + selected["observed_at"].dt.strftime("%Y-%m-%dT%H:%M:%S")
    )
    return selected


def _append_cohort_memberships(
    rows: list[dict[str, Any]],
    record: dict[str, Any],
) -> None:
    if bool(record["stock_trend_order"]):
        _append_membership(rows, record, "arm_comparison", str(record["rule_arm"]))
        round_reference = (
            str(record["pullback_round_group"]),
            str(record["reference_line"]),
        )
        if ROUND_REFERENCE_CANONICAL_ARMS.get(round_reference) == record["rule_arm"]:
            _append_membership(
                rows,
                record,
                "round_reference_comparison",
                "|".join(round_reference),
            )
    if record["rule_arm"] != ADAPTIVE_ARM:
        return
    for universe in (
        "concept_main_rise",
        "stock_trend_order",
        "stock_strong_main_rise",
    ):
        if bool(record[universe]):
            _append_membership(rows, record, "main_rise_sensitivity", universe)
    if not bool(record["stock_trend_order"]):
        return
    round_group = str(record["pullback_round_group"])
    _append_membership(rows, record, "round_comparison", round_group)
    for dimension in (
        "daily_volume_class",
        "intraday_volume_class",
        "leader_rank_group",
        "market_regime",
    ):
        _append_membership(
            rows,
            record,
            f"round_x_{dimension}",
            f"{round_group}|{record[dimension]}",
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


def _arm_segment_metrics(
    metrics: pd.DataFrame,
    arm: str,
) -> dict[str, pd.Series]:
    if metrics.empty:
        return {}
    rows = metrics.loc[
        metrics["table_id"].eq("arm_comparison")
        & metrics["cohort_key"].eq(arm)
    ]
    return {str(row["segment"]): row for _, row in rows.iterrows()}


def _time_split_status(
    development: pd.Series | None,
    validation: pd.Series | None,
) -> str:
    if not _passes_sample(
        development,
        minimum_trades=MIN_DEVELOPMENT_TRADES,
        minimum_days=MIN_DEVELOPMENT_DAYS,
    ):
        return "development_insufficient"
    if not _positive_metric(development):
        return "not_development_candidate"
    if not _passes_sample(
        validation,
        minimum_trades=MIN_VALIDATION_TRADES,
        minimum_days=MIN_VALIDATION_DAYS,
    ):
        return "validation_insufficient"
    if not _positive_metric(validation):
        return "validation_failed"
    if (
        float(development["win_rate_pct"]) >= MIN_HIGH_WIN_RATE_PCT
        and float(validation["win_rate_pct"]) >= MIN_HIGH_WIN_RATE_PCT
    ):
        return "high_win_confirmed"
    return "positive_confirmed"


def _passes_sample(
    metric: pd.Series | None,
    *,
    minimum_trades: int,
    minimum_days: int,
) -> bool:
    return metric is not None and (
        int(metric["closed_trades"]) >= minimum_trades
        and int(metric["source_days"]) >= minimum_days
    )


def _positive_metric(metric: pd.Series | None) -> bool:
    if metric is None:
        return False
    values = (
        metric["mean_net_return_pct"],
        metric["double_cost_mean_net_return_pct"],
        metric["profit_factor"],
    )
    if any(value is None or pd.isna(value) for value in values):
        return False
    return float(values[0]) > 0 and float(values[1]) > 0 and float(values[2]) > 1


def _beats_control(
    adaptive: pd.Series | None,
    control: pd.Series | None,
) -> bool:
    if adaptive is None or control is None:
        return False
    fields = ("win_rate_pct", "double_cost_mean_net_return_pct")
    values = [adaptive[field] for field in fields] + [control[field] for field in fields]
    if any(value is None or pd.isna(value) for value in values):
        return False
    return all(float(adaptive[field]) > float(control[field]) for field in fields)


def _metric_value(metric: pd.Series | None, column: str) -> float | None:
    if metric is None:
        return None
    return _finite_float(metric.get(column), allow_infinite=True)


def _series_record(metric: pd.Series | None) -> dict[str, Any] | None:
    return None if metric is None else _json_safe(metric.to_dict())


def _load_complete_candidate_minutes(
    candidates: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    manifest = load_outcome_group_5m_manifest(candidates)
    if manifest["status"].ne("complete").any():
        raise ValueError("MA pullback 5m manifest must be complete before study")
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
    if len(minute_bars) != len(candidates) * 48:
        raise ValueError("MA pullback minute rows must equal candidate days times 48")
    return minute_bars, manifest


def _filter_candidate_pairs(
    candidates: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    pairs = candidates.loc[:, ["vt_symbol", "entry_date"]].copy()
    pairs["trade_date"] = pd.to_datetime(pairs.pop("entry_date")).dt.date
    pairs = pairs.drop_duplicates()
    bars = minute_bars.copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"]).dt.date
    return bars.merge(
        pairs,
        on=["vt_symbol", "trade_date"],
        how="inner",
        validate="many_to_one",
    ).sort_values(["vt_symbol", "trade_date", "bar_time"], kind="stable").reset_index(
        drop=True
    )


def _build_loader_metadata(
    inputs: EventNeutralInputs,
    *,
    candidates: pd.DataFrame,
    pullback_panel: pd.DataFrame,
    minute_bars: pd.DataFrame,
    manifest: pd.DataFrame,
    signals: pd.DataFrame,
    trades: pd.DataFrame,
) -> dict[str, Any]:
    round_counts = pullback_panel["pullback_round_group"].value_counts()
    arm_counts = signals["rule_arm"].value_counts()
    status_counts = trades["normal_status"].value_counts(dropna=False)
    coverage = {
        **inputs.coverage,
        "comparison_candidates": int(len(candidates)),
        "concept_main_rise_candidates": int(
            pullback_panel["concept_main_rise"].astype(bool).sum()
        ),
        "stock_trend_order_candidates": int(
            pullback_panel["stock_trend_order"].astype(bool).sum()
        ),
        "stock_strong_main_rise_candidates": int(
            pullback_panel["stock_strong_main_rise"].astype(bool).sum()
        ),
        "first_round_candidates": int(round_counts.get("first", 0)),
        "second_round_candidates": int(round_counts.get("second", 0)),
        "third_plus_round_candidates": int(round_counts.get("third_plus", 0)),
        "manifest_pairs": int(len(manifest)),
        "complete_pairs": int(manifest["status"].eq("complete").sum()),
        "minute_rows": int(len(minute_bars)),
        "signals": int(len(signals)),
        "trades": int(len(trades)),
        "signals_by_arm": {str(key): int(value) for key, value in arm_counts.items()},
        "normal_status_counts": {
            str(key): int(value) for key, value in status_counts.items()
        },
        "holdout_price_values_read": False,
        "current_membership_rows_read": 0,
        "strict_historical_top3_rows_read": 0,
    }
    fingerprints = {
        **inputs.input_fingerprints,
        "ma_pullback_candidates": fingerprint_frame(
            candidates, identity_columns=("event_id",)
        ).as_dict(),
        "ma_pullback_round_panel": fingerprint_frame(
            pullback_panel, identity_columns=("event_id",)
        ).as_dict(),
        "ma_pullback_minutes": fingerprint_frame(
            minute_bars, identity_columns=("vt_symbol", "bar_time", "interval")
        ).as_dict(),
        "ma_pullback_signals": fingerprint_frame(
            signals, identity_columns=("observation_id",)
        ).as_dict(),
        "ma_pullback_outcomes": fingerprint_frame(
            trades, identity_columns=("observation_id",)
        ).as_dict(),
    }
    return {
        "coverage": coverage,
        "input_fingerprints": fingerprints,
        "discovery_start": inputs.discovery_start,
        "discovery_end": inputs.discovery_end,
    }


def _empty_signals(panel: pd.DataFrame) -> pd.DataFrame:
    columns = [
        *panel.columns,
        "rule_arm",
        "reference_line",
        "reference_value",
        "observed_at",
        "entry_time",
        "entry_price_raw",
        "intraday_volume_ratio",
        "intraday_volume_class",
        "signal_minutes_from_open",
        "signal_distance_to_reference_pct",
        "signal_touch_depth_pct",
        "observation_id",
        "leader_rank_group",
        "market_regime",
    ]
    return pd.DataFrame(columns=list(dict.fromkeys(columns)))


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


def _reject_signal_leakage(*frames: pd.DataFrame) -> None:
    prohibited = set().union(
        *(PROHIBITED_SIGNAL_COLUMNS & set(frame.columns) for frame in frames)
    )
    prohibited.update(
        column
        for frame in frames
        for column in frame.columns
        if str(column).startswith("future_")
    )
    if prohibited:
        raise ValueError(f"future or outcome signal columns are prohibited: {sorted(prohibited)}")


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


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
