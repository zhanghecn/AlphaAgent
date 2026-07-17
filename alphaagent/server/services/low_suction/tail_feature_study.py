"""D-tail support-feature study for event-recognized main-rise leader spells."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import numpy as np
import pandas as pd

from alphaagent.server.services.execution import cash_ledger

from .event_recognition_falsification import chronological_event_blocks


INTERVAL = "5m"
FEATURE_CUTOFF = time(14, 50)
ENTRY_TIME = time(14, 55)
EXIT_OBSERVATION_TIME = time(10, 30)
EXIT_TIME = time(10, 35)
OBSERVATION_OFFSETS = frozenset({1, 2, 3, 4})
INITIAL_CASH = 100_000.0
COMMISSION_RATE = 0.0003
MINIMUM_COMMISSION = 5.0
STAMP_TAX_RATE = 0.0005
TRANSFER_FEE_RATE = 0.00001
SLIPPAGE_BPS = 10.0
LOT_SIZE = 100
STUDY_EVIDENCE_LEVEL = "event_proxy_tail_low_suction_feature_discovery"

MIN_DEVELOPMENT_TRADES = 30
MIN_DEVELOPMENT_DAYS = 20
MIN_VALIDATION_TRADES = 20
MIN_VALIDATION_DAYS = 15
HIGH_WIN_RATE_PCT = 55.0

TAIL_NUMERIC_FEATURES = (
    "context_distance_to_ma5_pct",
    "context_distance_to_ma10_pct",
    "context_distance_to_ma20_pct",
    "context_distance_from_20d_high_pct",
    "tail_return_from_previous_close_pct",
    "tail_drawdown_from_session_high_pct",
    "tail_range_position_pct",
    "tail_vs_open_pct",
    "tail_vs_vwap_pct",
    "tail_vs_ma5_pct",
    "tail_vs_ma10_pct",
    "tail_vs_ma20_pct",
    "afternoon_low_vs_morning_low_pct",
    "last_15m_return_pct",
    "last_15m_volume_ratio",
)

CATEGORICAL_FEATURES = (
    "support_zone",
    "morning_support_state",
    "support_break_count",
    "tail_return_bucket",
    "tail_drawdown_bucket",
    "tail_range_bucket",
    "late_momentum_bucket",
    "late_volume_bucket",
    "recognition_rank_bucket",
    "spell_offset_bucket",
    "market_regime",
    "tail_above_vwap",
    "tail_above_ma5",
    "tail_above_ma10",
    "tail_above_ma20",
)

CANDIDATE_COLUMNS = (
    "event_id",
    "leader_spell_id",
    "recognition_source_date",
    "context_date",
    "entry_date",
    "planned_exit_date",
    "sector_id",
    "concept_name",
    "cycle_id",
    "vt_symbol",
    "stock_name",
    "recognition_rank",
    "cycle_relative_percentile",
    "spell_session_offset",
    "active_direction",
    "danger_state",
    "market_phase",
    "main_rise",
    "is_top3",
    "rank_mode",
    "evidence_level",
)

DAILY_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "turnover",
)

MINUTE_COLUMNS = (
    "vt_symbol",
    "trade_date",
    "bar_time",
    "interval",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "turnover",
    "source",
)

PROHIBITED_FEATURE_COLUMNS = frozenset(
    {
        "status",
        "reason",
        "entry_time",
        "exit_time",
        "entry_price",
        "entry_price_raw",
        "exit_price",
        "exit_price_raw",
        "gross_return_pct",
        "net_return_pct",
        "double_cost_net_return_pct",
        "tail_success",
        "outcome_group",
    }
)


def build_tail_feature_panel(
    candidates: pd.DataFrame,
    daily_bars: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Freeze D-tail features at the completed 14:50 five-minute bar."""

    _reject_outcome_columns(candidates, daily_bars, minute_bars)
    _require_columns(candidates, CANDIDATE_COLUMNS, "tail candidate")
    candidate_frame = candidates.copy()
    for column in (
        "recognition_source_date",
        "context_date",
        "entry_date",
        "planned_exit_date",
    ):
        candidate_frame[column] = pd.to_datetime(
            candidate_frame[column], errors="raise"
        ).dt.date
    if candidate_frame["event_id"].duplicated().any():
        raise ValueError("tail candidate event IDs must be unique")
    if candidate_frame.duplicated(["vt_symbol", "entry_date"]).any():
        raise ValueError("tail candidate stock/date pairs must be unique")
    if not candidate_frame["spell_session_offset"].isin(OBSERVATION_OFFSETS).all():
        raise ValueError("tail candidates must use frozen S+1..S+4 offsets")

    support = _build_daily_support(daily_bars)
    minutes = _prepare_minutes(minute_bars)
    decision_bars = minutes.loc[
        minutes["bar_time"].dt.time.le(FEATURE_CUTOFF)
    ].copy()
    feature_times = set(_expected_close_times(end=FEATURE_CUTOFF))
    rows: list[dict[str, Any]] = []
    for candidate in candidate_frame.to_dict("records"):
        symbol = str(candidate["vt_symbol"])
        entry_date = candidate["entry_date"]
        day = decision_bars.loc[
            decision_bars["vt_symbol"].eq(symbol)
            & decision_bars["trade_date"].eq(entry_date)
        ].copy()
        day_times = set(day["bar_time"].dt.time)
        if day_times != feature_times or len(day) != len(feature_times):
            raise ValueError("every tail feature day requires complete bars through 14:50")
        context = support.get((symbol, candidate["context_date"]))
        if context is None:
            raise ValueError("tail candidate is missing D-1 daily support")
        rows.append(_tail_feature_row(candidate, context, day))

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    if "block" not in result:
        blocks = chronological_event_blocks(
            tuple(sorted(result["entry_date"].unique())),
            block_count=5,
        ).rename(columns={"source_date": "entry_date"})
        result = result.merge(blocks, on="entry_date", how="left", validate="many_to_one")
    result["evidence_level"] = STUDY_EVIDENCE_LEVEL
    return result.sort_values(["entry_date", "event_id"], kind="stable").reset_index(
        drop=True
    )


def execute_tail_trades(
    features: pd.DataFrame,
    daily_bars: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Enter at D 14:55 open and exit at D+1 10:35 open under fixed costs."""

    _require_columns(
        features,
        (
            "event_id",
            "entry_date",
            "planned_exit_date",
            "vt_symbol",
            "context_close_price",
            *TAIL_NUMERIC_FEATURES,
        ),
        "tail feature",
    )
    frame = features.copy()
    for column in ("entry_date", "planned_exit_date"):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.date
    if frame["event_id"].duplicated().any():
        raise ValueError("tail feature event IDs must be unique")
    minutes = _prepare_minutes(minute_bars)
    minute_index = {
        (str(row.vt_symbol), row.trade_date, pd.Timestamp(row.bar_time).time()): row
        for row in minutes.itertuples(index=False)
    }
    daily = _prepare_daily_bars(daily_bars)
    daily_close = {
        (str(row.vt_symbol), row.trade_date): float(row.close_price)
        for row in daily.itertuples(index=False)
    }
    rows = [
        _execute_tail_trade(
            feature,
            minute_index=minute_index,
            daily_close=daily_close,
        )
        for feature in frame.to_dict("records")
    ]
    return pd.DataFrame(rows).sort_values(
        ["entry_date", "event_id"], kind="stable"
    ).reset_index(drop=True)


def build_numeric_success_failure_profiles(ledger: pd.DataFrame) -> pd.DataFrame:
    """Compare frozen continuous features without choosing thresholds."""

    _require_columns(
        ledger,
        ("status", "outcome_group", "entry_date", *TAIL_NUMERIC_FEATURES),
        "tail trade ledger",
    )
    closed = ledger.loc[
        ledger["status"].eq("closed")
        & ledger["outcome_group"].isin(("success", "failure"))
    ].copy()
    rows = []
    for feature in TAIL_NUMERIC_FEATURES:
        for outcome_group in ("success", "failure"):
            group = closed.loc[closed["outcome_group"].eq(outcome_group)]
            values = pd.to_numeric(group[feature], errors="coerce").dropna()
            rows.append(
                {
                    "feature": feature,
                    "outcome_group": outcome_group,
                    "rows": int(len(values)),
                    "source_days": int(
                        pd.to_datetime(group.loc[values.index, "entry_date"])
                        .dt.date.nunique()
                    )
                    if len(values)
                    else 0,
                    "mean": float(values.mean()) if len(values) else None,
                    "median": float(values.median()) if len(values) else None,
                    "q25": float(values.quantile(0.25)) if len(values) else None,
                    "q75": float(values.quantile(0.75)) if len(values) else None,
                }
            )
    return pd.DataFrame(rows)


def build_categorical_feature_metrics(ledger: pd.DataFrame) -> pd.DataFrame:
    """Summarize every frozen state over all/development/validation/blocks."""

    _require_columns(
        ledger,
        (
            "entry_date",
            "block",
            "status",
            "net_return_pct",
            "double_cost_net_return_pct",
            *CATEGORICAL_FEATURES,
        ),
        "tail trade ledger",
    )
    rows = []
    for segment, blocks in _metric_segments():
        segment_rows = ledger.loc[ledger["block"].isin(blocks)]
        rows.append(
            {
                "table_id": "baseline",
                "cohort_key": "all",
                "segment": segment,
                **_summarize_trade_rows(segment_rows),
            }
        )
        for feature in CATEGORICAL_FEATURES:
            values = segment_rows[feature].map(_cohort_text)
            for cohort_key in sorted(values.unique()):
                rows.append(
                    {
                        "table_id": feature,
                        "cohort_key": cohort_key,
                        "segment": segment,
                        **_summarize_trade_rows(
                            segment_rows.loc[values.eq(cohort_key)]
                        ),
                    }
                )
    return pd.DataFrame(rows).sort_values(
        ["table_id", "cohort_key", "segment"], kind="stable"
    ).reset_index(drop=True)


def evaluate_single_feature_groups(metrics: pd.DataFrame) -> dict[str, Any]:
    """Confirm only pre-bucketed single groups across both reused-history segments."""

    _require_columns(
        metrics,
        (
            "table_id",
            "cohort_key",
            "segment",
            "closed_trades",
            "source_days",
            "win_rate_pct",
            "mean_net_return_pct",
            "double_cost_mean_net_return_pct",
        ),
        "tail feature metric",
    )
    baselines = metrics.loc[metrics["table_id"].eq("baseline")].set_index("segment")
    rows = []
    groups = metrics.loc[metrics["table_id"].ne("baseline")]
    for (table_id, cohort_key), group in groups.groupby(
        ["table_id", "cohort_key"], sort=True
    ):
        indexed = group.set_index("segment")
        development = _segment_metric(indexed, "development")
        validation = _segment_metric(indexed, "validation")
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
        development_better = _beats_baseline(
            development, baselines.loc["development"]
        )
        validation_better = _beats_baseline(
            validation, baselines.loc["validation"]
        )
        stressed_positive = _positive_number(
            development["double_cost_mean_net_return_pct"]
        ) and _positive_number(validation["double_cost_mean_net_return_pct"])
        stable = bool(
            development_sample
            and validation_sample
            and development_better
            and validation_better
            and stressed_positive
        )
        high_win = bool(
            stable
            and float(development["win_rate_pct"]) > HIGH_WIN_RATE_PCT
            and float(validation["win_rate_pct"]) > HIGH_WIN_RATE_PCT
        )
        if not development_sample:
            status = "development_insufficient"
        elif not validation_sample:
            status = "validation_insufficient"
        elif not development_better or not validation_better:
            status = "not_better_than_segment_baseline"
        elif not stressed_positive:
            status = "double_cost_not_positive"
        elif high_win:
            status = "high_win_stable_positive"
        else:
            status = "stable_positive_low_win"
        rows.append(
            {
                "table_id": str(table_id),
                "cohort_key": str(cohort_key),
                "status": status,
                "stable_positive": stable,
                "high_win": high_win,
                **_prefixed_metric(development, "development"),
                **_prefixed_metric(validation, "validation"),
            }
        )
    stable_count = sum(bool(row["stable_positive"]) for row in rows)
    high_win_count = sum(bool(row["high_win"]) for row in rows)
    if high_win_count:
        conclusion = "tail_feature_high_win_group_found_in_reused_history"
    elif stable_count:
        conclusion = "tail_feature_stable_positive_group_found_in_reused_history"
    else:
        conclusion = "no_stable_tail_feature_group"
    return {
        "overall_conclusion": conclusion,
        "combined_rule_selected": False,
        "evaluated_groups": len(rows),
        "stable_positive_groups": stable_count,
        "high_win_groups": high_win_count,
        "group_evaluation": rows,
    }


def build_tail_feature_report(
    features: pd.DataFrame,
    ledger: pd.DataFrame,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Preserve coverage, profiles, all feature groups and winner/loser cases."""

    numeric_profiles = build_numeric_success_failure_profiles(ledger)
    metrics = build_categorical_feature_metrics(ledger)
    evaluation = evaluate_single_feature_groups(metrics)
    closed = ledger.loc[ledger["status"].eq("closed")].copy()
    closed["net_return_pct"] = pd.to_numeric(
        closed["net_return_pct"], errors="coerce"
    )
    winners = closed.loc[closed["net_return_pct"].gt(0)]
    failures = closed.loc[closed["net_return_pct"].le(0)]
    baseline = metrics.loc[metrics["table_id"].eq("baseline")]
    return {
        "study_track": "tail_low_suction_feature_discovery",
        "evidence_level": STUDY_EVIDENCE_LEVEL,
        "overall_conclusion": evaluation["overall_conclusion"],
        "formal_rule_selected": False,
        "formal_metrics": None,
        "strict_historical_top3_claim": False,
        "trade_outcomes_read": True,
        "outer_holdout_price_values_read": False,
        "entry_contract": {
            "feature_cutoff": "D 14:50 close",
            "entry": "D 14:55 bar open",
            "requested_exit": "D+1 10:30",
            "exit": "D+1 10:35 bar open",
            "exit_interpretation": "first executable 5m proxy after 10:30",
            "cost_multipliers": [1.0, 2.0],
        },
        "coverage": _json_safe(dict(metadata.get("coverage", {}))),
        "baseline_metrics": _records(baseline),
        "numeric_profiles": _records(numeric_profiles),
        "categorical_feature_metrics": _records(metrics),
        "feature_evaluation": _json_safe(evaluation),
        "largest_winners": _case_records(
            winners.sort_values(
                "net_return_pct", ascending=False, kind="stable"
            ).head(20)
        ),
        "largest_failures": _case_records(
            failures.sort_values(
                "net_return_pct", ascending=True, kind="stable"
            ).head(20)
        ),
        "feature_rows": int(len(features)),
        "input_fingerprints": _json_safe(
            dict(metadata.get("input_fingerprints", {}))
        ),
        "discovery_start": _json_safe(metadata.get("discovery_start")),
        "discovery_end": _json_safe(metadata.get("discovery_end")),
        "limitations": [
            "leader identity is an event-recognition proxy rather than strict historical membership Top3",
            "blocks 4-5 are reused history and not an untouched outer holdout",
            "14:55 and 10:35 bar opens are five-minute execution proxies without order-book evidence",
            "single-feature groups are descriptive and no combined production rule is selected",
            "historical security status remains reconstructed from current names",
        ],
    }


def render_tail_feature_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def render_tail_feature_markdown(report: Mapping[str, Any]) -> str:
    coverage = report.get("coverage", {})
    cohort_contract = report.get("cohort_contract", {})
    is_gold = (
        isinstance(cohort_contract, Mapping)
        and cohort_contract.get("active_direction") == "GOLD"
    )
    title = (
        "# AlphaAgent 金手指龙头尾盘低吸特征研究"
        if is_gold
        else "# AlphaAgent 龙头尾盘低吸特征研究"
    )
    lines = [
        title,
        "",
        f"结论：`{report['overall_conclusion']}`  ",
        "正式规则/绩效：`null/null`  ",
        "成交：D 14:50 完成观察，14:55 bar 开盘买；D+1 10:30 后首个可执行代理为 10:35 bar 开盘卖。",
    ]
    if is_gold:
        lines.append(
            "固定母样本：`active_direction=GOLD`，状态在 `D-1 close` 已知；"
            "SILVER 不进入分钟特征、交易账本或结果分组。"
        )
    lines.extend(
        [
            "",
            "## 覆盖",
            "",
            f"候选/完整双日路径/特征：`{coverage.get('candidate_rows', 0)}/"
            f"{coverage.get('complete_pairs', 0)}/{report.get('feature_rows', 0)}`  ",
            f"股票/日期：`{coverage.get('symbols', 0)}/{coverage.get('dates', 0)}`  ",
            f"闭合/成功/失败：`{coverage.get('closed_trades', 0)}/"
            f"{coverage.get('successful_trades', 0)}/"
            f"{coverage.get('failed_trades', 0)}`  ",
            f"拒绝/未闭合：`{coverage.get('status_counts', {}).get('rejected', 0)}/"
            f"{coverage.get('status_counts', {}).get('unclosed', 0)}`",
        ]
    )
    if is_gold:
        direction_counts = coverage.get("parent_direction_candidate_counts", {})
        lines.extend(
            [
                f"筛选前候选/金手指候选：`{coverage.get('parent_candidate_rows', 0)}/"
                f"{coverage.get('candidate_rows', 0)}`  ",
                "方向候选数：`"
                + ", ".join(
                    f"{direction}={count}"
                    for direction, count in sorted(direction_counts.items())
                )
                + "`  ",
                f"金手指候选占比：`{_pct(coverage.get('cohort_candidate_share_pct'))}`",
                "",
                "### 原始时间块覆盖",
                "",
                "| Block | Feature rows | Dates |",
                "| --- | ---: | ---: |",
            ]
        )
        block_rows = coverage.get("block_feature_rows", {})
        block_dates = coverage.get("block_dates", {})
        for block in range(1, 6):
            key = f"block_{block}"
            lines.append(
                f"| `{key}` | {block_rows.get(key, 0)} | {block_dates.get(key, 0)} |"
            )
        if int(block_rows.get("block_5", 0)) == 0:
            lines.extend(
                [
                    "",
                    "警示：金手指在原 `block_5` 没有候选，"
                    "validation 实际只来自 `block_4`，不构成两个后段时间块确认。",
                ]
            )
    lines.extend(
        [
            "",
            "### 未成交与未闭合原因",
            "",
            "| Reason | Count |",
            "| --- | ---: |",
        ]
    )
    reason_counts = coverage.get("reason_counts", {})
    lines.extend(
        [
            f"| `{reason}` | {count} |"
            for reason, count in sorted(reason_counts.items())
        ]
        or ["| `none` | 0 |"]
    )
    lines.extend(
        [
            "",
            "## 总体结果",
            "",
            "| Segment | Closed | Days | Win | Mean | Median | PF | 2x mean | Compound | Drawdown |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["baseline_metrics"]:
        lines.append(_metric_markdown_row(row))
    lines.extend(
        [
            "",
            "复利为同日全部闭合信号等权后的历史诊断曲线，不是正式现金账户绩效。",
            "",
            "## 支撑位置",
            "",
            "| Feature | State | Segment | Closed | Days | Win | Mean | 2x mean |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    support_tables = {"support_zone", "morning_support_state", "support_break_count"}
    for row in report["categorical_feature_metrics"]:
        if row["table_id"] in support_tables and row["segment"] in {
            "all",
            "development",
            "validation",
        }:
            lines.append(
                f"| `{row['table_id']}` | `{row['cohort_key']}` | "
                f"`{row['segment']}` | {row['closed_trades']} | {row['source_days']} | "
                f"{_pct(row['win_rate_pct'])} | {_pct(row['mean_net_return_pct'])} | "
                f"{_pct(row['double_cost_mean_net_return_pct'])} |"
            )
    lines.extend(
        [
            "",
            "## 单特征跨段确认",
            "",
            "| Feature | State | Status | Dev N/Win/Mean/2x | Val N/Win/Mean/2x |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in report["feature_evaluation"]["group_evaluation"]:
        lines.append(
            f"| `{row['table_id']}` | `{row['cohort_key']}` | `{row['status']}` | "
            f"{row['development_closed_trades']}/{_pct(row['development_win_rate_pct'])}/"
            f"{_pct(row['development_mean_net_return_pct'])}/"
            f"{_pct(row['development_double_cost_mean_net_return_pct'])} | "
            f"{row['validation_closed_trades']}/{_pct(row['validation_win_rate_pct'])}/"
            f"{_pct(row['validation_mean_net_return_pct'])}/"
            f"{_pct(row['validation_double_cost_mean_net_return_pct'])} |"
        )
    lines.extend(_numeric_profile_markdown(report["numeric_profiles"]))
    lines.extend(_case_markdown("成功案例", report["largest_winners"]))
    lines.extend(_case_markdown("失败案例", report["largest_failures"]))
    lines.extend(_fingerprint_markdown(report.get("input_fingerprints", {})))
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "本报告先保留全部成功与失败案例，再比较事前特征。事件认可 Top3 不是严格历史成员 Top3，后两块也是复用历史；任何局部高胜率都不能直接成为正式规则。",
            "",
        ]
    )
    return "\n".join(lines)


def load_tail_feature_study_data(
    *,
    active_direction: str | None = None,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    dict[str, Any],
]:
    """Load S+1..S+4 candidates and exact D/D+1 5m pairs inside discovery."""

    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    from .event_neutral_days import load_event_neutral_inputs
    from .research_protocol import fingerprint_frame

    inputs = load_event_neutral_inputs()
    parent_candidates = inputs.candidates.loc[
        inputs.candidates["spell_session_offset"].isin(OBSERVATION_OFFSETS)
    ].copy()
    if active_direction is not None:
        parent_candidates = _attach_original_tail_blocks(parent_candidates)
    direction_counts = (
        parent_candidates["active_direction"].astype(str).value_counts()
    )
    candidates = parent_candidates
    if active_direction is not None:
        candidates = parent_candidates.loc[
            parent_candidates["active_direction"].eq(active_direction)
        ].copy()
    for column in ("entry_date", "planned_exit_date"):
        candidates[column] = pd.to_datetime(candidates[column], errors="raise").dt.date
    if candidates.empty:
        cohort = active_direction or "all directions"
        raise ValueError(f"no S+1..S+4 tail candidates for {cohort} inside discovery")
    symbols = tuple(sorted(candidates["vt_symbol"].astype(str).unique()))
    start = min(candidates["entry_date"].min(), candidates["planned_exit_date"].min())
    end = max(candidates["entry_date"].max(), candidates["planned_exit_date"].max())
    if end > inputs.discovery_end:
        raise ValueError("tail minute request crossed the discovery boundary")
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
            schema.stock_minute_bars.c.trade_date.between(start, end),
            schema.stock_minute_bars.c.interval == INTERVAL,
        )
        .order_by(
            schema.stock_minute_bars.c.vt_symbol,
            schema.stock_minute_bars.c.trade_date,
            schema.stock_minute_bars.c.bar_time,
        )
    )
    loaded = pd.read_sql(statement, get_engine(), parse_dates=["bar_time"])
    loaded = _prepare_minutes(loaded)
    if loaded["trade_date"].max() > inputs.discovery_end:
        raise ValueError("loaded minute values crossed the discovery boundary")
    complete_pairs = _complete_minute_pairs(loaded)
    complete_mask = [
        (str(row.vt_symbol), row.entry_date) in complete_pairs
        and (str(row.vt_symbol), row.planned_exit_date) in complete_pairs
        for row in candidates.itertuples(index=False)
    ]
    selected = candidates.loc[complete_mask].copy()
    if selected.empty:
        raise ValueError("no candidates have complete D and D+1 five-minute paths")
    required_pairs = {
        (str(row.vt_symbol), day)
        for row in selected.itertuples(index=False)
        for day in (row.entry_date, row.planned_exit_date)
    }
    pair_index = pd.MultiIndex.from_frame(loaded[["vt_symbol", "trade_date"]])
    minute_bars = loaded.loc[pair_index.isin(required_pairs)].copy()
    daily_bars = inputs.stock_bars.copy()
    daily_dates = pd.to_datetime(daily_bars["trade_date"], errors="raise").dt.date
    if daily_dates.max() > inputs.discovery_end:
        raise ValueError("loaded daily values crossed the discovery boundary")
    features = build_tail_feature_panel(selected, daily_bars, minute_bars)
    ledger = execute_tail_trades(features, daily_bars, minute_bars)
    block_feature_rows = features["block"].value_counts()
    block_dates = features.groupby("block", sort=True)["entry_date"].nunique()
    coverage = {
        "candidate_rows": int(len(candidates)),
        "complete_pairs": int(len(selected)),
        "incomplete_pairs": int(len(candidates) - len(selected)),
        "coverage_pct": float(len(selected) / len(candidates) * 100.0),
        "symbols": int(selected["vt_symbol"].nunique()),
        "dates": int(selected["entry_date"].nunique()),
        "minute_rows": int(len(minute_bars)),
        **_execution_coverage(ledger),
        "offsets": [1, 2, 3, 4],
        "feature_cutoff": "14:50",
        "entry_time": "14:55",
        "exit_time": "10:35",
        "strict_historical_membership_rows_read": 0,
        "outer_holdout_price_values_read": False,
    }
    if active_direction is not None:
        coverage.update(
            {
                "cohort_active_direction": active_direction,
                "cohort_known_at": "D-1 close",
                "parent_candidate_rows": int(len(parent_candidates)),
                "parent_direction_candidate_counts": {
                    str(key): int(value)
                    for key, value in direction_counts.sort_index().items()
                },
                "cohort_candidate_share_pct": float(
                    len(candidates) / len(parent_candidates) * 100.0
                ),
                "block_feature_rows": {
                    f"block_{block}": int(block_feature_rows.get(block, 0))
                    for block in range(1, 6)
                },
                "block_dates": {
                    f"block_{block}": int(block_dates.get(block, 0))
                    for block in range(1, 6)
                },
            }
        )
    fingerprints = {
        "tail_candidates": fingerprint_frame(
            selected, identity_columns=("entry_date", "vt_symbol")
        ).as_dict(),
        "tail_minutes": fingerprint_frame(
            minute_bars,
            identity_columns=("vt_symbol", "bar_time", "interval"),
        ).as_dict(),
        "tail_features": fingerprint_frame(
            features, identity_columns=("event_id",)
        ).as_dict(),
        "tail_trade_ledger": fingerprint_frame(
            ledger, identity_columns=("event_id",)
        ).as_dict(),
    }
    if active_direction is not None:
        fingerprints["parent_tail_candidates"] = fingerprint_frame(
            parent_candidates,
            identity_columns=("entry_date", "vt_symbol"),
        ).as_dict()
    metadata = {
        "coverage": coverage,
        "input_fingerprints": fingerprints,
        "discovery_start": inputs.discovery_start,
        "discovery_end": inputs.discovery_end,
    }
    return features, ledger, metadata


def run_tail_feature_study() -> dict[str, Any]:
    return build_tail_feature_report(*load_tail_feature_study_data())


def _tail_feature_row(
    candidate: dict[str, Any],
    context: Mapping[str, float],
    day: pd.DataFrame,
) -> dict[str, Any]:
    day = day.sort_values("bar_time", kind="stable")
    tail = day.iloc[-1]
    morning = day.loc[day["bar_time"].dt.time.le(time(11, 30))]
    afternoon = day.loc[day["bar_time"].dt.time.ge(time(13, 5))]
    morning_low = float(morning["low_price"].min())
    afternoon_low = float(afternoon["low_price"].min())
    tail_close = float(tail["close_price"])
    session_high = float(day["high_price"].max())
    session_low = float(day["low_price"].min())
    day_open = float(day.iloc[0]["open_price"])
    cumulative_volume = float(day["volume"].sum())
    vwap = float(day["turnover"].sum() / cumulative_volume)
    previous_close = float(context["context_close_price"])
    ma5 = float(context["context_ma5"])
    ma10 = float(context["context_ma10"])
    ma20 = float(context["context_ma20"])
    broke_morning_low = afternoon_low < morning_low
    reclaimed_morning_low = broke_morning_low and tail_close >= morning_low
    if not broke_morning_low:
        morning_state = "held"
    elif reclaimed_morning_low:
        morning_state = "false_break_reclaimed"
    else:
        morning_state = "broken_unrecovered"
    tail_above_vwap = tail_close >= vwap
    tail_above_ma5 = tail_close >= ma5
    tail_above_ma10 = tail_close >= ma10
    tail_above_ma20 = tail_close >= ma20
    support_zone = _support_zone(
        tail_close,
        vwap=vwap,
        ma5=ma5,
        ma10=ma10,
        ma20=ma20,
    )
    support_break_count = sum(
        (
            not tail_above_vwap,
            not tail_above_ma5,
            not tail_above_ma10,
            not tail_above_ma20,
            morning_state == "broken_unrecovered",
        )
    )
    last_15m_return = _pct_change(tail_close, float(day.iloc[-4]["close_price"]))
    prior_afternoon = afternoon.iloc[:-3]
    last_volume = float(afternoon.iloc[-3:]["volume"].mean())
    prior_volume = float(prior_afternoon["volume"].mean())
    last_volume_ratio = last_volume / prior_volume if prior_volume > 0 else float("nan")
    range_width = session_high - session_low
    range_position = (
        (tail_close - session_low) / range_width * 100.0 if range_width > 0 else 50.0
    )
    tail_return = _pct_change(tail_close, previous_close)
    drawdown = _pct_change(tail_close, session_high)
    row = {
        **candidate,
        **context,
        "feature_cutoff_at": pd.Timestamp(tail["bar_time"]),
        "feature_cutoff_time": FEATURE_CUTOFF.strftime("%H:%M"),
        "tail_close_price": tail_close,
        "tail_vwap": vwap,
        "morning_low": morning_low,
        "afternoon_low": afternoon_low,
        "session_high_through_1450": session_high,
        "session_low_through_1450": session_low,
        "context_distance_to_ma5_pct": _pct_change(previous_close, ma5),
        "context_distance_to_ma10_pct": _pct_change(previous_close, ma10),
        "context_distance_to_ma20_pct": _pct_change(previous_close, ma20),
        "context_distance_from_20d_high_pct": _pct_change(
            previous_close, float(context["context_high20"])
        ),
        "tail_return_from_previous_close_pct": tail_return,
        "tail_drawdown_from_session_high_pct": drawdown,
        "tail_range_position_pct": range_position,
        "tail_vs_open_pct": _pct_change(tail_close, day_open),
        "tail_vs_vwap_pct": _pct_change(tail_close, vwap),
        "tail_vs_ma5_pct": _pct_change(tail_close, ma5),
        "tail_vs_ma10_pct": _pct_change(tail_close, ma10),
        "tail_vs_ma20_pct": _pct_change(tail_close, ma20),
        "afternoon_low_vs_morning_low_pct": _pct_change(
            afternoon_low, morning_low
        ),
        "last_15m_return_pct": last_15m_return,
        "last_15m_volume_ratio": last_volume_ratio,
        "tail_above_vwap": tail_above_vwap,
        "tail_above_ma5": tail_above_ma5,
        "tail_above_ma10": tail_above_ma10,
        "tail_above_ma20": tail_above_ma20,
        "afternoon_broke_morning_low": broke_morning_low,
        "tail_reclaimed_morning_low": reclaimed_morning_low,
        "morning_support_state": morning_state,
        "support_zone": support_zone,
        "support_break_count": int(support_break_count),
        "tail_return_bucket": _tail_return_bucket(tail_return),
        "tail_drawdown_bucket": _drawdown_bucket(drawdown),
        "tail_range_bucket": _range_bucket(range_position),
        "late_momentum_bucket": _momentum_bucket(last_15m_return),
        "late_volume_bucket": _volume_bucket(last_volume_ratio),
        "recognition_rank_bucket": (
            "rank1" if int(candidate["recognition_rank"]) == 1 else "rank2_3"
        ),
        "spell_offset_bucket": f"S+{int(candidate['spell_session_offset'])}",
        "market_regime": (
            f"{candidate['active_direction']}/{candidate['danger_state']}"
        ),
    }
    numeric = pd.Series({key: row[key] for key in TAIL_NUMERIC_FEATURES}, dtype=float)
    if numeric.isna().any() or not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("tail numeric features must be complete finite values")
    return row


def _build_daily_support(frame: pd.DataFrame) -> dict[tuple[str, date], dict[str, float]]:
    bars = _prepare_daily_bars(frame)
    grouped = bars.groupby("vt_symbol", sort=False)
    for sessions in (5, 10, 20):
        bars[f"ma{sessions}"] = grouped["close_price"].transform(
            lambda values, window=sessions: values.rolling(
                window, min_periods=window
            ).mean()
        )
    bars["high20"] = grouped["close_price"].transform(
        lambda values: values.rolling(20, min_periods=20).max()
    )
    result = {}
    for row in bars.itertuples(index=False):
        values = (row.close_price, row.ma5, row.ma10, row.ma20, row.high20)
        if any(pd.isna(value) or float(value) <= 0 for value in values):
            continue
        result[(str(row.vt_symbol), row.trade_date)] = {
            "context_close_price": float(row.close_price),
            "context_ma5": float(row.ma5),
            "context_ma10": float(row.ma10),
            "context_ma20": float(row.ma20),
            "context_high20": float(row.high20),
        }
    return result


def _prepare_daily_bars(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, DAILY_COLUMNS, "tail daily bar")
    bars = frame.loc[:, list(DAILY_COLUMNS)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.date
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("tail daily bar identities must be unique")
    for column in DAILY_COLUMNS[2:]:
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    return bars.sort_values(["vt_symbol", "trade_date"], kind="stable").reset_index(
        drop=True
    )


def _prepare_minutes(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, MINUTE_COLUMNS, "tail minute bar")
    bars = frame.loc[:, list(MINUTE_COLUMNS)].copy()
    bars = bars.loc[bars["interval"].eq(INTERVAL)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.date
    bars["bar_time"] = pd.to_datetime(bars["bar_time"], errors="raise")
    if bars.duplicated(["vt_symbol", "bar_time", "interval"]).any():
        raise ValueError("tail minute bar identities must be unique")
    for column in ("open_price", "high_price", "low_price", "close_price", "volume", "turnover"):
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    if bars[["open_price", "high_price", "low_price", "close_price", "volume", "turnover"]].isna().any().any():
        raise ValueError("tail minute OHLCV values must be numeric")
    return bars.sort_values(["vt_symbol", "bar_time"], kind="stable").reset_index(
        drop=True
    )


def _execute_tail_trade(
    feature: dict[str, Any],
    *,
    minute_index: Mapping[tuple[str, date, time], Any],
    daily_close: Mapping[tuple[str, date], float],
) -> dict[str, Any]:
    base = dict(feature)
    symbol = str(feature["vt_symbol"])
    entry_date = feature["entry_date"]
    exit_date = feature["planned_exit_date"]
    entry_bar = minute_index.get((symbol, entry_date, ENTRY_TIME))
    exit_bar = minute_index.get((symbol, exit_date, EXIT_TIME))
    base.update(
        {
            "status": None,
            "reason": None,
            "entry_time": None,
            "exit_time": None,
            "entry_price_raw": None,
            "entry_price": None,
            "exit_price_raw": None,
            "exit_price": None,
            "gross_return_pct": None,
            "net_return_pct": None,
            "double_cost_net_return_pct": None,
            "tail_success": None,
            "outcome_group": "unavailable",
        }
    )
    if entry_bar is None:
        return _finish_status(base, "rejected", "missing_1455_entry_bar")
    entry_open = float(entry_bar.open_price)
    if entry_open <= 0 or float(entry_bar.volume) <= 0:
        return _finish_status(base, "rejected", "invalid_1455_entry_bar")
    previous_close = float(feature["context_close_price"])
    limit_up = _limit_price(previous_close, 1.10)
    if entry_open >= limit_up:
        return _finish_status(
            base,
            "rejected",
            "entry_limit_up_queue_unknown_without_l2",
        )
    base["entry_time"] = pd.Timestamp(entry_bar.bar_time)
    base["entry_price_raw"] = entry_open
    if exit_bar is None:
        return _finish_status(base, "unclosed", "missing_1035_exit_bar")
    exit_open = float(exit_bar.open_price)
    if exit_open <= 0 or float(exit_bar.volume) <= 0:
        return _finish_status(base, "unclosed", "invalid_1035_exit_bar")
    d_close = daily_close.get((symbol, entry_date))
    if d_close is None or d_close <= 0:
        return _finish_status(base, "unclosed", "missing_d_close_for_exit_limit")
    limit_down = _limit_price(d_close, 0.90)
    if exit_open <= limit_down:
        return _finish_status(
            base,
            "unclosed",
            "exit_limit_down_queue_unknown_without_l2",
        )
    normal = _cash_return(
        entry_open,
        exit_open,
        limit_up=limit_up,
        limit_down=limit_down,
        cost_multiplier=1.0,
    )
    stressed = _cash_return(
        entry_open,
        exit_open,
        limit_up=limit_up,
        limit_down=limit_down,
        cost_multiplier=2.0,
    )
    if normal is None or stressed is None:
        return _finish_status(base, "rejected", "insufficient_cash")
    base.update(
        {
            "status": "closed",
            "reason": None,
            "exit_time": pd.Timestamp(exit_bar.bar_time),
            "entry_price": normal[0],
            "exit_price_raw": exit_open,
            "exit_price": normal[1],
            "gross_return_pct": _pct_change(exit_open, entry_open),
            "net_return_pct": normal[2],
            "double_cost_net_return_pct": stressed[2],
            "tail_success": normal[2] > 0,
            "outcome_group": "success" if normal[2] > 0 else "failure",
        }
    )
    return base


def _cash_return(
    entry_price: float,
    exit_price: float,
    *,
    limit_up: float,
    limit_down: float,
    cost_multiplier: float,
) -> tuple[float, float, float] | None:
    buy = cash_ledger.calculate_buy_execution(
        raw_price=entry_price,
        cash=INITIAL_CASH,
        target_cash=INITIAL_CASH,
        commission_rate=COMMISSION_RATE * cost_multiplier,
        slippage_bps=SLIPPAGE_BPS * cost_multiplier,
        lot_size=LOT_SIZE,
        minimum_commission=MINIMUM_COMMISSION * cost_multiplier,
        transfer_fee_rate=TRANSFER_FEE_RATE * cost_multiplier,
        max_price=limit_up,
    )
    if buy.volume <= 0:
        return None
    sell = cash_ledger.calculate_sell_execution(
        raw_price=exit_price,
        volume=buy.volume,
        cost_price=buy.price,
        commission_rate=COMMISSION_RATE * cost_multiplier,
        stamp_tax_rate=STAMP_TAX_RATE * cost_multiplier,
        slippage_bps=SLIPPAGE_BPS * cost_multiplier,
        minimum_commission=MINIMUM_COMMISSION * cost_multiplier,
        transfer_fee_rate=TRANSFER_FEE_RATE * cost_multiplier,
        min_price=limit_down,
    )
    final_cash = buy.cash_after + sell.cash_delta
    return buy.price, sell.price, (final_cash / INITIAL_CASH - 1.0) * 100.0


def _finish_status(base: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    base["status"] = status
    base["reason"] = reason
    return base


def _execution_coverage(ledger: pd.DataFrame) -> dict[str, Any]:
    _require_columns(
        ledger,
        ("status", "reason", "tail_success"),
        "tail trade ledger",
    )
    closed = ledger["status"].eq("closed")
    successes = closed & ledger["tail_success"].eq(True)
    failures = closed & ledger["tail_success"].eq(False)
    status_counts = ledger["status"].fillna("unknown").astype(str).value_counts()
    reason_counts = (
        ledger.loc[ledger["reason"].notna(), "reason"]
        .astype(str)
        .value_counts()
    )
    return {
        "closed_trades": int(closed.sum()),
        "successful_trades": int(successes.sum()),
        "failed_trades": int(failures.sum()),
        "status_counts": {
            str(key): int(value)
            for key, value in status_counts.sort_index().items()
        },
        "reason_counts": {
            str(key): int(value)
            for key, value in reason_counts.sort_index().items()
        },
    }


def _complete_minute_pairs(frame: pd.DataFrame) -> set[tuple[str, date]]:
    expected = set(_expected_close_times())
    complete = set()
    for (symbol, trade_date), group in frame.groupby(
        ["vt_symbol", "trade_date"], sort=False
    ):
        times = set(group["bar_time"].dt.time)
        if len(group) == len(expected) and times == expected:
            complete.add((str(symbol), trade_date))
    return complete


def _attach_original_tail_blocks(frame: pd.DataFrame) -> pd.DataFrame:
    """Freeze block IDs on the parent dates before applying a cohort filter."""

    if "entry_date" not in frame:
        raise ValueError("tail parent candidates require entry_date for block assignment")
    result = frame.copy()
    result["entry_date"] = pd.to_datetime(
        result["entry_date"], errors="raise"
    ).dt.date
    if "block" in result:
        if result["block"].isna().any():
            raise ValueError("tail parent candidate block IDs cannot be null")
        return result
    blocks = chronological_event_blocks(
        tuple(sorted(result["entry_date"].unique())),
        block_count=5,
    ).rename(columns={"source_date": "entry_date"})
    return result.merge(blocks, on="entry_date", how="left", validate="many_to_one")


def _expected_close_times(*, end: time = time(15, 0)) -> tuple[time, ...]:
    values = []
    for start, count in ((time(9, 35), 24), (time(13, 5), 24)):
        current = datetime.combine(date(2000, 1, 1), start)
        values.extend((current + timedelta(minutes=5 * index)).time() for index in range(count))
    return tuple(value for value in values if value <= end)


def _support_zone(
    price: float,
    *,
    vwap: float,
    ma5: float,
    ma10: float,
    ma20: float,
) -> str:
    if price < ma20:
        return "below_ma20"
    if price < ma10:
        return "ma10_to_ma20"
    if price < ma5:
        return "ma5_to_ma10"
    if price < vwap:
        return "below_vwap_above_ma5"
    return "above_vwap_and_ma5"


def _tail_return_bucket(value: float) -> str:
    if value < 0:
        return "below_0"
    if value < 3:
        return "0_to_3"
    if value < 5:
        return "3_to_5"
    if value < 7:
        return "5_to_7"
    return "7_plus"


def _drawdown_bucket(value: float) -> str:
    if value >= -1:
        return "within_1"
    if value >= -3:
        return "1_to_3"
    if value >= -5:
        return "3_to_5"
    return "below_5"


def _range_bucket(value: float) -> str:
    if value < 20:
        return "bottom_20"
    if value < 50:
        return "20_to_50"
    if value < 80:
        return "50_to_80"
    return "top_20"


def _momentum_bucket(value: float) -> str:
    if value < -0.3:
        return "falling"
    if value <= 0.3:
        return "flat"
    return "rising"


def _volume_bucket(value: float) -> str:
    if value < 0.7:
        return "contraction"
    if value <= 1.3:
        return "normal"
    return "expansion"


def _limit_price(previous_close: float, multiplier: float) -> float:
    value = Decimal(str(previous_close)) * Decimal(str(multiplier))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _metric_segments() -> tuple[tuple[str, frozenset[int]], ...]:
    return (
        ("all", frozenset(range(1, 6))),
        ("development", frozenset({1, 2, 3})),
        ("validation", frozenset({4, 5})),
        *((f"block_{block}", frozenset({block})) for block in range(1, 6)),
    )


def _summarize_trade_rows(rows: pd.DataFrame) -> dict[str, Any]:
    closed = rows.loc[rows["status"].eq("closed")].copy()
    normal = pd.to_numeric(closed["net_return_pct"], errors="coerce").dropna()
    stressed = pd.to_numeric(
        closed.loc[normal.index, "double_cost_net_return_pct"], errors="coerce"
    ).dropna()
    compound, drawdown = _daily_compounding(closed.loc[normal.index])
    return {
        "signals": int(len(rows)),
        "closed_trades": int(len(normal)),
        "source_days": int(
            pd.to_datetime(closed.loc[normal.index, "entry_date"]).dt.date.nunique()
        )
        if len(normal)
        else 0,
        "win_rate_pct": float(normal.gt(0).mean() * 100.0) if len(normal) else None,
        "mean_net_return_pct": float(normal.mean()) if len(normal) else None,
        "median_net_return_pct": float(normal.median()) if len(normal) else None,
        "profit_factor": _profit_factor(normal),
        "double_cost_mean_net_return_pct": float(stressed.mean()) if len(stressed) else None,
        "compound_return_pct": compound,
        "maximum_drawdown_pct": drawdown,
    }


def _daily_compounding(rows: pd.DataFrame) -> tuple[float | None, float | None]:
    if rows.empty:
        return None, None
    daily = (
        rows.assign(
            net_return_pct=pd.to_numeric(rows["net_return_pct"], errors="coerce")
        )
        .dropna(subset=["net_return_pct"])
        .groupby("entry_date", sort=True)["net_return_pct"]
        .mean()
    )
    if daily.empty:
        return None, None
    equity = (1.0 + daily / 100.0).cumprod()
    drawdown = equity / equity.cummax().clip(lower=1.0) - 1.0
    return float((equity.iloc[-1] - 1.0) * 100.0), float(drawdown.min() * 100.0)


def _profit_factor(values: pd.Series) -> float | None:
    if values.empty:
        return None
    gains = float(values.loc[values.gt(0)].sum())
    losses = abs(float(values.loc[values.lt(0)].sum()))
    if losses == 0:
        return math.inf if gains > 0 else None
    return gains / losses


def _passes_sample(metric: pd.Series, *, minimum_trades: int, minimum_days: int) -> bool:
    return int(metric["closed_trades"]) >= minimum_trades and int(metric["source_days"]) >= minimum_days


def _beats_baseline(metric: pd.Series, baseline: pd.Series) -> bool:
    values = (
        metric["win_rate_pct"],
        metric["mean_net_return_pct"],
        baseline["win_rate_pct"],
        baseline["mean_net_return_pct"],
    )
    if any(value is None or pd.isna(value) for value in values):
        return False
    return float(values[0]) > float(values[2]) and float(values[1]) > float(values[3])


def _positive_number(value: Any) -> bool:
    return value is not None and not pd.isna(value) and float(value) > 0


def _prefixed_metric(metric: pd.Series, prefix: str) -> dict[str, Any]:
    return {
        f"{prefix}_{column}": _json_safe(metric[column])
        for column in (
            "closed_trades",
            "source_days",
            "win_rate_pct",
            "mean_net_return_pct",
            "double_cost_mean_net_return_pct",
        )
    }


def _segment_metric(indexed: pd.DataFrame, segment: str) -> pd.Series:
    if segment in indexed.index:
        return indexed.loc[segment]
    return pd.Series(
        {
            "closed_trades": 0,
            "source_days": 0,
            "win_rate_pct": None,
            "mean_net_return_pct": None,
            "double_cost_mean_net_return_pct": None,
        }
    )


def _case_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    columns = [
        column
        for column in (
            "event_id",
            "entry_date",
            "vt_symbol",
            "stock_name",
            "concept_name",
            "recognition_rank",
            "spell_session_offset",
            "market_regime",
            "support_zone",
            "morning_support_state",
            "support_break_count",
            "tail_return_from_previous_close_pct",
            "tail_drawdown_from_session_high_pct",
            "tail_range_position_pct",
            "entry_price_raw",
            "exit_price_raw",
            "net_return_pct",
            "double_cost_net_return_pct",
        )
        if column in frame
    ]
    return _records(frame.loc[:, columns])


def _numeric_profile_markdown(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    lines = [
        "",
        "## 成功与失败连续特征",
        "",
        "| Feature | Group | N | Median | Q25 | Q75 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['feature']}` | `{row['outcome_group']}` | {row['rows']} | "
            f"{_number(row['median'])} | {_number(row['q25'])} | {_number(row['q75'])} |"
        )
    return lines


def _case_markdown(title: str, rows: Sequence[Mapping[str, Any]]) -> list[str]:
    lines = [
        "",
        f"## {title}",
        "",
        "| Date | Stock | Concept | Rank/Offset | Support | Morning | Tail return | Drawdown | Entry | Exit | Net | 2x |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('entry_date')} | {row.get('stock_name')} ({row.get('vt_symbol')}) | "
            f"{row.get('concept_name')} | {row.get('recognition_rank')}/S+{row.get('spell_session_offset')} | "
            f"`{row.get('support_zone')}` | `{row.get('morning_support_state')}` | "
            f"{_pct(row.get('tail_return_from_previous_close_pct'))} | "
            f"{_pct(row.get('tail_drawdown_from_session_high_pct'))} | "
            f"{_number(row.get('entry_price_raw'))} | {_number(row.get('exit_price_raw'))} | "
            f"{_pct(row.get('net_return_pct'))} | {_pct(row.get('double_cost_net_return_pct'))} |"
        )
    return lines


def _fingerprint_markdown(
    fingerprints: Mapping[str, Any],
) -> list[str]:
    lines = [
        "",
        "## 输入指纹",
        "",
        "| Input | Rows | Columns | Digest |",
        "| --- | ---: | ---: | --- |",
    ]
    for name, fingerprint in sorted(fingerprints.items()):
        if not isinstance(fingerprint, Mapping):
            continue
        columns = fingerprint.get("columns", ())
        column_count = (
            len(columns)
            if isinstance(columns, Sequence) and not isinstance(columns, str)
            else 0
        )
        lines.append(
            f"| `{name}` | {fingerprint.get('rows', 0)} | {column_count} | "
            f"`{fingerprint.get('digest', '-')}` |"
        )
    return lines


def _metric_markdown_row(row: Mapping[str, Any]) -> str:
    return (
        f"| `{row['segment']}` | {row['closed_trades']} | {row['source_days']} | "
        f"{_pct(row['win_rate_pct'])} | {_pct(row['mean_net_return_pct'])} | "
        f"{_pct(row['median_net_return_pct'])} | {_number(row['profit_factor'])} | "
        f"{_pct(row['double_cost_mean_net_return_pct'])} | "
        f"{_pct(row['compound_return_pct'])} | {_pct(row['maximum_drawdown_pct'])} |"
    )


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [_json_safe(record) for record in frame.to_dict("records")]


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    try:
        return None if bool(pd.isna(value)) else value
    except (TypeError, ValueError):
        return value


def _pct_change(value: float, base: float) -> float:
    if base <= 0:
        raise ValueError("percentage-change base must be positive")
    return (value / base - 1.0) * 100.0


def _cohort_text(value: Any) -> str:
    if isinstance(value, (bool, np.bool_)):
        return "true" if bool(value) else "false"
    return str(value)


def _pct(value: Any) -> str:
    number = _optional_number(value)
    return "-" if number is None else f"{number:.4f}%"


def _number(value: Any) -> str:
    number = _optional_number(value, allow_infinite=True)
    if number is None:
        return "-"
    return "inf" if math.isinf(number) else f"{number:.4f}"


def _optional_number(value: Any, *, allow_infinite: bool = False) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    if math.isnan(number) or (math.isinf(number) and not allow_infinite):
        return None
    return number


def _reject_outcome_columns(*frames: pd.DataFrame) -> None:
    prohibited = sorted(
        {
            str(column)
            for frame in frames
            for column in frame.columns
            if str(column) in PROHIBITED_FEATURE_COLUMNS
            or str(column).startswith(("future_", "outcome_"))
        }
    )
    if prohibited:
        raise ValueError(f"tail feature inputs contain outcome columns: {prohibited}")


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
