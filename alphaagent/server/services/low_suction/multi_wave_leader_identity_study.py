"""Point-in-time identification of leaders that continue into a second wave."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.tree import DecisionTreeClassifier

from .event_recognition_falsification import chronological_event_blocks


STUDY_VERSION = "multi-wave-leader-identity-v1"
POSITIVE_SECOND_WAVE_STATUS = "continued_to_higher_high"
NEGATIVE_SECOND_WAVE_STATUS = "terminal_failure_observed"
CENSORED_SECOND_WAVE_STATUSES = frozenset(
    ("unresolved_pullback_censored", "open_at_observation_end")
)
SUPPORT_DEPTH = {
    "above_ma5": 0.0,
    "ma5": 1.0,
    "ma10": 2.0,
    "below_ma20": 3.0,
}
MULTI_WAVE_FEATURES = (
    "first_wave_gain_pct",
    "first_wave_pullback_depth_pct",
    "first_wave_recovery_sessions",
    "first_wave_strong_days",
    "first_wave_max_volume_ratio",
    "first_wave_median_volume_ratio",
    "first_trough_volume_ratio",
    "first_trough_support_depth",
    "first_trough_reclaimed_ma5",
    "first_trough_reclaimed_ma10",
    "decision_return_1d_pct",
    "decision_return_5d_pct",
    "decision_return_10d_pct",
    "decision_volume_ratio_prior5",
    "decision_turnover_expansion",
    "decision_distance_ma20_pct",
    "decision_distance_first_peak_pct",
    "stock_gain_since_anchor_pct",
    "concept_gain_since_anchor_pct",
    "stock_excess_since_anchor_pct",
    "concept_return_5d_pct",
    "concept_return_10d_pct",
    "concept_turnover_expansion",
    "member_positive_5d_breadth_pct",
    "member_recent_strong_5d_breadth_pct",
    "member_main_rise_breadth_pct",
    "causal_rank",
    "candidate_pool_size",
)
TREE_MAX_DEPTH = 2
TREE_MIN_SAMPLES_LEAF = 100
TREE_RANDOM_STATE = 0
MIN_DEVELOPMENT_PRECISION_PCT = 60.0
MIN_DEVELOPMENT_LIFT_PCT_POINTS = 5.0
MIN_VALIDATION_ROWS = 100
MIN_VALIDATION_BLOCK_ROWS = 30
MIN_VALIDATION_BLOCK_PRECISION_PCT = 60.0

EPISODE_IDENTITY_COLUMNS = (
    "episode_id",
    "cohort",
    "vt_symbol",
    "stock_name",
    "anchor_date",
    "observation_end",
    "causal_rank",
    "sector_id",
    "concept_name",
    "cycle_id",
)

FIRST_WAVE_COLUMNS = (
    "episode_id",
    "wave_number",
    "wave_start_date",
    "peak_date",
    "peak_price",
    "trough_date",
    "trough_price",
    "pullback_pct",
    "higher_high_date",
    "recovery_sessions",
    "trough_volume_ratio_5d",
    "deepest_tested_support",
    "trough_close_reclaimed_ma5",
    "trough_close_reclaimed_ma10",
    "resolution_status",
)

IMPULSE_COLUMNS = (
    "episode_id",
    "wave_number",
    "impulse_gain_pct",
    "strong_days_ge_9_5pct",
    "max_volume_ratio_prior5",
    "median_volume_ratio_prior5",
)


@dataclass(frozen=True)
class MultiWaveIdentityCohort:
    labels: pd.DataFrame
    censored: pd.DataFrame


@dataclass(frozen=True)
class MultiWaveCondition:
    feature: str
    operator: str
    threshold: float

    def __post_init__(self) -> None:
        if self.feature not in MULTI_WAVE_FEATURES:
            raise ValueError(f"unsupported multi-wave feature: {self.feature}")
        if self.operator not in {"<=", ">"}:
            raise ValueError(f"unsupported multi-wave operator: {self.operator}")


@dataclass(frozen=True)
class MultiWaveRule:
    rule_id: str
    leaf_node: int
    conditions: tuple[MultiWaveCondition, ...]


@dataclass(frozen=True)
class MultiWaveLeafAttempt:
    leaf_node: int
    rule: MultiWaveRule
    rows: int
    positives: int
    precision_pct: float
    recall_pct: float
    precision_lift_pct_points: float
    rejection_reasons: tuple[str, ...]
    selected: bool = False


@dataclass(frozen=True)
class MultiWaveIdentityDiscovery:
    model: DecisionTreeClassifier
    selected_rule: MultiWaveRule | None
    attempts: tuple[MultiWaveLeafAttempt, ...]
    development_rows: int
    development_base_rate_pct: float


def run_multi_wave_leader_identity_study() -> dict[str, Any]:
    """Run the frozen identity study on the existing causal Top3 wave cohort."""

    from .cross_leader_wave_study import (
        build_causal_wave_episodes,
        filter_complete_episode_paths,
        replay_leader_wave_episodes,
    )
    from .research_protocol import fingerprint_frame
    from .true_leader_study import (
        build_emotion_cycle_candidates,
        build_point_in_time_stock_features,
        load_true_leader_study_inputs,
        rank_causal_cycle_leaders,
    )

    inputs = load_true_leader_study_inputs(include_reference_bars=False)
    stock_features = build_point_in_time_stock_features(inputs.stock_bars)
    candidates = build_emotion_cycle_candidates(
        inputs.cycle_starts,
        inputs.memberships,
        stock_features,
    )
    causal_ranks = rank_causal_cycle_leaders(candidates)
    selected_episodes = build_causal_wave_episodes(
        causal_ranks,
        trading_dates=inputs.trading_dates,
    )
    episodes, path_exclusions = filter_complete_episode_paths(
        selected_episodes,
        inputs.stock_bars,
        trading_dates=inputs.trading_dates,
    )
    replay = replay_leader_wave_episodes(episodes, inputs.stock_bars)
    cohort = build_multi_wave_identity_labels(
        episodes,
        replay["waves"],
        replay["impulses"],
    )
    concept_context = _load_identity_concept_bars(
        tuple(sorted(episodes["sector_id"].astype(str).unique())),
        start_date=inputs.trading_dates[0],
        end_date=inputs.trading_dates[-1],
    )
    panel = build_multi_wave_feature_panel(
        cohort.labels,
        causal_ranks,
        inputs.stock_bars,
        concept_context,
        inputs.memberships,
    )
    panel = assign_multi_wave_time_blocks(panel)
    univariate = evaluate_multi_wave_univariate(panel)
    discovery = discover_multi_wave_identity(panel)
    validation = evaluate_multi_wave_identity(panel, discovery)

    generated_frames = {
        "multi_wave_episodes": (episodes, ("episode_id",)),
        "multi_wave_ledger": (
            replay["waves"],
            ("episode_id", "wave_number"),
        ),
        "resolved_second_wave_labels": (
            cohort.labels,
            ("episode_id",),
        ),
        "censored_second_wave_labels": (
            cohort.censored,
            ("episode_id",),
        ),
        "multi_wave_feature_panel": (panel, ("episode_id",)),
        "multi_wave_concept_context": (
            concept_context,
            ("sector_id", "trade_date"),
        ),
    }
    generated_fingerprints = {
        name: fingerprint_frame(frame, identity_columns=identity).as_dict()
        for name, (frame, identity) in generated_frames.items()
    }
    coverage = {
        **inputs.coverage,
        "causal_rank_rows": int(len(causal_ranks)),
        "causal_top3_rows": int(causal_ranks["causal_top3"].astype(bool).sum()),
        "selected_non_overlapping_episodes": int(len(selected_episodes)),
        "complete_non_overlapping_episodes": int(len(episodes)),
        "incomplete_path_exclusions": int(len(path_exclusions)),
        "wave_rows": int(len(replay["waves"])),
        "concept_context_rows": int(len(concept_context)),
        "concept_context_sectors": int(concept_context["sector_id"].nunique()),
        "identity_decision_dates": int(panel["decision_date"].nunique()),
        "trade_outcome_rows_read": 0,
        "minute_rows_read": 0,
        "timing_rows_read": 0,
    }
    return build_multi_wave_identity_report(
        cohort=cohort,
        panel=panel,
        univariate=univariate,
        discovery=discovery,
        validation=validation,
        coverage=coverage,
        fingerprints={**inputs.fingerprints, **generated_fingerprints},
    )


def _load_identity_concept_bars(
    sector_ids: tuple[str, ...],
    *,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    from .concept_index_coverage import CANONICAL_CONCEPT_INDEX_SOURCE

    columns = ["sector_id", "trade_date", "close_price", "turnover"]
    if not sector_ids:
        return pd.DataFrame(columns=columns)
    statement = (
        select(
            schema.sector_daily_bars.c.sector_id,
            schema.sector_daily_bars.c.trade_date,
            schema.sector_daily_bars.c.close_price,
            schema.sector_daily_bars.c.turnover,
        )
        .where(
            schema.sector_daily_bars.c.sector_id.in_(sector_ids),
            schema.sector_daily_bars.c.source == CANONICAL_CONCEPT_INDEX_SOURCE,
            schema.sector_daily_bars.c.trade_date.between(
                start_date - timedelta(days=60),
                end_date,
            ),
        )
        .order_by(
            schema.sector_daily_bars.c.sector_id,
            schema.sector_daily_bars.c.trade_date,
        )
    )
    return pd.read_sql(
        statement,
        get_engine(),
        parse_dates=["trade_date"],
    )


def build_multi_wave_identity_report(
    *,
    cohort: MultiWaveIdentityCohort,
    panel: pd.DataFrame,
    univariate: pd.DataFrame,
    discovery: MultiWaveIdentityDiscovery,
    validation: Mapping[str, Any],
    coverage: Mapping[str, Any],
    fingerprints: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build identity evidence without promoting it to low-suction performance."""

    _require_columns(
        panel,
        ("episode_id", "decision_date", "block", "multi_wave_leader", "feature_complete"),
        "multi-wave feature panel",
    )
    complete = panel.loc[panel["feature_complete"].astype(bool)].copy()
    block_summary = []
    for block in range(1, 6):
        rows = complete.loc[complete["block"].eq(block)]
        target = rows["multi_wave_leader"].astype(bool)
        block_summary.append(
            {
                "block": block,
                "start_date": _date_text(rows["decision_date"].min()),
                "end_date": _date_text(rows["decision_date"].max()),
                "decision_dates": int(rows["decision_date"].nunique()),
                "rows": int(len(rows)),
                "positives": int(target.sum()),
                "base_rate_pct": (
                    float(target.mean() * 100.0) if len(target) else None
                ),
            }
        )
    report = {
        "study_version": STUDY_VERSION,
        "research_status": str(validation["overall_conclusion"]),
        "research_question": (
            "at_first_rebreak_close_can_a_causal_top3_proxy_be_identified_as_a_"
            "resolved_second_wave_continuation"
        ),
        "formal_strategy": False,
        "formal_metrics": {
            "win_rate_pct": None,
            "compounded_return_pct": None,
            "profit_factor": None,
            "maximum_drawdown_pct": None,
        },
        "membership_evidence": "current_membership_and_security_proxy",
        "label_contract": {
            "decision_timestamp": "wave_1_first_higher_high_session_close",
            "positive": POSITIVE_SECOND_WAVE_STATUS,
            "negative": NEGATIVE_SECOND_WAVE_STATUS,
            "censored": sorted(CENSORED_SECOND_WAVE_STATUSES),
            "minimum_pullback_pct": 5.0,
            "episode_horizon_sessions": 40,
        },
        "feature_contract": {
            "cutoff": "decision_date_close_or_earlier",
            "features": list(MULTI_WAVE_FEATURES),
            "current_proxy_member_breadth": True,
            "future_wave_2_predictors": False,
            "trade_outcomes_read": False,
            "minute_bars_read": False,
            "gold_silver_context_read": False,
        },
        "coverage": {
            **dict(coverage),
            "successful_first_waves": int(len(cohort.labels) + len(cohort.censored)),
            "resolved_second_waves": int(len(cohort.labels)),
            "continued_second_waves": int(
                cohort.labels.get("multi_wave_leader", pd.Series(dtype=bool))
                .astype(bool)
                .sum()
            ),
            "terminal_second_waves": int(
                len(cohort.labels)
                - cohort.labels.get("multi_wave_leader", pd.Series(dtype=bool))
                .astype(bool)
                .sum()
            ),
            "censored_second_waves": int(len(cohort.censored)),
            "feature_panel_rows": int(len(panel)),
            "feature_complete_rows": int(len(complete)),
            "feature_incomplete_rows": int(len(panel) - len(complete)),
        },
        "chronological_blocks": block_summary,
        "univariate_diagnostics": _records(univariate),
        "tree_contract": {
            "development_blocks": [1, 2, 3],
            "validation_blocks": [4, 5],
            "max_depth": TREE_MAX_DEPTH,
            "min_samples_leaf": TREE_MIN_SAMPLES_LEAF,
            "random_state": TREE_RANDOM_STATE,
            "development_min_precision_pct_exclusive": (
                MIN_DEVELOPMENT_PRECISION_PCT
            ),
            "development_min_lift_pct_points_inclusive": (
                MIN_DEVELOPMENT_LIFT_PCT_POINTS
            ),
            "validation_min_rows": MIN_VALIDATION_ROWS,
            "validation_min_rows_per_block": MIN_VALIDATION_BLOCK_ROWS,
            "validation_min_precision_per_block_pct_exclusive": (
                MIN_VALIDATION_BLOCK_PRECISION_PCT
            ),
        },
        "development": {
            "rows": discovery.development_rows,
            "base_rate_pct": discovery.development_base_rate_pct,
            "selected_rule": _rule_payload(discovery.selected_rule),
            "leaf_attempts": [
                _attempt_payload(attempt) for attempt in discovery.attempts
            ],
        },
        "identity_validation": _json_safe(dict(validation)),
        "representative_cases": _representative_cases(
            cohort,
            panel,
            discovery.selected_rule,
        ),
        "boundaries": [
            "current concept memberships create survivorship bias",
            "identity precision is not low-suction trade win rate",
            "the 40-session episode horizon censors unresolved second waves",
            "daily close is the decision timestamp; no intraday execution is studied",
            "the old outer holdout is contaminated and is not reused",
        ],
        "fingerprints": _json_safe(dict(fingerprints)),
    }
    return _json_safe(report)


def render_multi_wave_identity_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def render_multi_wave_identity_markdown(report: Mapping[str, Any]) -> str:
    coverage = _mapping(report.get("coverage"))
    development = _mapping(report.get("development"))
    validation = _mapping(report.get("identity_validation"))
    lines = [
        "# AlphaAgent 第一浪后多浪真龙头点时识别研究",
        "",
        f"研究状态：`{report.get('research_status')}`。",
        "正式低吸胜率、收益、复利：`null`。本报告只评价身份识别，未读取交易收益。",
        "",
        "## 样本口径",
        "",
        f"- 第一浪已重新创新高：`{coverage.get('successful_first_waves', 0)}`。",
        f"- 第二浪已决：`{coverage.get('resolved_second_waves', 0)}`；继续创新高 "
        f"`{coverage.get('continued_second_waves', 0)}`，终止 "
        f"`{coverage.get('terminal_second_waves', 0)}`。",
        f"- 第二浪右端未决并剔除：`{coverage.get('censored_second_waves', 0)}`。",
        f"- 点时特征完整：`{coverage.get('feature_complete_rows', 0)}`；不完整 "
        f"`{coverage.get('feature_incomplete_rows', 0)}`。",
        "- 决策时点固定为第一浪回调后首次重新越过前峰的当日收盘。",
        "",
        "## 时间块",
        "",
        "| Block | 日期 | 决策日 | 样本 | 续浪 | 基准比例 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in _sequence(report.get("chronological_blocks")):
        item = _mapping(row)
        lines.append(
            f"| {item.get('block')} | {item.get('start_date')}..{item.get('end_date')} | "
            f"{item.get('decision_dates', 0)} | {item.get('rows', 0)} | "
            f"{item.get('positives', 0)} | {_pct(item.get('base_rate_pct'))} |"
        )
    lines.extend(
        [
            "",
            "## 单变量方向",
            "",
            "方向只由 block 1-3 决定，block 4-5 不允许反转方向。",
            "",
            "| 特征 | 方向 | 开发 AUC | Block 4 AUC | Block 5 AUC | 两块同向 |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    diagnostics = sorted(
        (_mapping(row) for row in _sequence(report.get("univariate_diagnostics"))),
        key=lambda row: -float(row.get("development_directional_auc") or 0.0),
    )
    for row in diagnostics:
        lines.append(
            f"| `{row.get('feature')}` | `{row.get('direction')}` | "
            f"{_number(row.get('development_directional_auc'))} | "
            f"{_number(row.get('block_4_directional_auc'))} | "
            f"{_number(row.get('block_5_directional_auc'))} | "
            f"`{row.get('same_direction_in_both_validation_blocks')}` |"
        )
    selected_rule = development.get("selected_rule")
    lines.extend(
        [
            "",
            "## 冻结树",
            "",
            f"- 开发样本：`{development.get('rows', 0)}`；基准续浪比例 "
            f"`{_pct(development.get('base_rate_pct'))}`。",
            f"- 冻结叶：`{_rule_text(selected_rule)}`。",
            "",
            "| Leaf | 条件 | 样本 | 精度 | 召回 | 提升 | 状态 |",
            "| ---: | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in _sequence(development.get("leaf_attempts")):
        item = _mapping(row)
        lines.append(
            f"| {item.get('leaf_node')} | {_rule_text(item.get('rule'))} | "
            f"{item.get('rows', 0)} | {_pct(item.get('precision_pct'))} | "
            f"{_pct(item.get('recall_pct'))} | "
            f"{_pct(item.get('precision_lift_pct_points'))} | "
            f"`{'selected' if item.get('selected') else ','.join(item.get('rejection_reasons') or []) or 'eligible'}` |"
        )
    selected_validation = _mapping(validation.get("selected_validation"))
    lines.extend(
        [
            "",
            "## 验证结果",
            "",
            f"- 结论：`{validation.get('overall_conclusion')}`；身份门 "
            f"`{validation.get('identity_gate_passed')}`。",
            f"- 冻结叶验证样本：`{selected_validation.get('rows', 0)}`；精度 "
            f"`{_pct(selected_validation.get('precision_pct'))}`；召回 "
            f"`{_pct(selected_validation.get('recall_pct'))}`。",
            f"- 整树验证 AUC：`{_number(validation.get('validation_model_auc'))}`。",
            f"- 失败门：`{', '.join(validation.get('failed_gates') or []) or 'none'}`。",
            "",
            "| Block | 叶样本 | 精度 | 召回 | 整树 AUC |",
            "| ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in _sequence(validation.get("validation_blocks")):
        item = _mapping(row)
        lines.append(
            f"| {item.get('block')} | {item.get('rows', 0)} | "
            f"{_pct(item.get('precision_pct'))} | {_pct(item.get('recall_pct'))} | "
            f"{_number(item.get('model_auc'))} |"
        )
    cases = _mapping(report.get("representative_cases"))
    lines.extend(
        [
            "",
            "## 验证个股例子",
            "",
            "以下股票都满足同一冻结叶；真阳性和假阳性同时存在，不能事后追加条件。",
            "",
            "| 类型 | 股票 | 概念 | 决策日 | 强势宽度 | 概念 5 日 | 第一浪涨幅 | 回撤 | 支撑深度 |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    case_groups = (
        ("续浪", "selected_validation_true_positive"),
        ("终止", "selected_validation_false_positive"),
    )
    for label, key in case_groups:
        for row in _sequence(cases.get(key)):
            item = _mapping(row)
            lines.append(
                f"| {label} | {item.get('stock_name')} `{item.get('vt_symbol')}` | "
                f"{item.get('concept_name')} | {item.get('decision_date')} | "
                f"{_pct(item.get('member_recent_strong_5d_breadth_pct'))} | "
                f"{_pct(item.get('concept_return_5d_pct'))} | "
                f"{_pct(item.get('first_wave_gain_pct'))} | "
                f"{_pct(item.get('first_wave_pullback_depth_pct'))} | "
                f"{_number(item.get('first_trough_support_depth'))} |"
            )
    lines.extend(
        [
            "",
            "## 边界",
            "",
            *[f"- {value}" for value in _sequence(report.get("boundaries"))],
            "",
            "## Reproduce",
            "",
            "```bash",
            "docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-multi-wave-leader-identity-study --format markdown",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def assign_multi_wave_time_blocks(panel: pd.DataFrame) -> pd.DataFrame:
    """Assign five chronological blocks without splitting one decision date."""

    _require_columns(panel, ("episode_id", "decision_date"), "identity panel")
    result = panel.drop(columns="block", errors="ignore").copy()
    result["decision_date"] = pd.to_datetime(
        result["decision_date"], errors="raise"
    ).dt.normalize()
    blocks = chronological_event_blocks(
        tuple(sorted(result["decision_date"].dt.date.unique())),
        block_count=5,
    ).rename(columns={"source_date": "decision_date"})
    blocks["decision_date"] = pd.to_datetime(blocks["decision_date"]).dt.normalize()
    return result.merge(
        blocks,
        on="decision_date",
        how="left",
        validate="many_to_one",
    ).sort_values(["decision_date", "episode_id"], kind="stable").reset_index(drop=True)


def evaluate_multi_wave_univariate(panel: pd.DataFrame) -> pd.DataFrame:
    """Freeze feature direction on blocks 1-3 and carry it into blocks 4-5."""

    _require_model_panel(panel)
    complete = panel.loc[panel["feature_complete"].astype(bool)].copy()
    development = complete.loc[complete["block"].isin((1, 2, 3))]
    if development["multi_wave_leader"].nunique() != 2:
        raise ValueError("univariate development requires both identity classes")
    rows: list[dict[str, Any]] = []
    for feature in MULTI_WAVE_FEATURES:
        development_values = pd.to_numeric(
            development[feature], errors="raise"
        ).to_numpy(dtype=float)
        development_target = development["multi_wave_leader"].astype(bool).to_numpy()
        raw_auc = _roc_auc(development_target, development_values)
        direction = "higher" if raw_auc is None or raw_auc >= 0.5 else "lower"
        row: dict[str, Any] = {
            "feature": feature,
            "direction": direction,
            "development_rows": int(len(development)),
            "development_raw_auc": raw_auc,
            "development_directional_auc": _directional_auc(
                development_target,
                development_values,
                direction,
            ),
        }
        for block in (4, 5):
            block_frame = complete.loc[complete["block"].eq(block)]
            block_values = pd.to_numeric(
                block_frame[feature], errors="raise"
            ).to_numpy(dtype=float)
            block_target = block_frame["multi_wave_leader"].astype(bool).to_numpy()
            row[f"block_{block}_rows"] = int(len(block_frame))
            row[f"block_{block}_directional_auc"] = _directional_auc(
                block_target,
                block_values,
                direction,
            )
        validation_aucs = (
            row["block_4_directional_auc"],
            row["block_5_directional_auc"],
        )
        row["same_direction_in_both_validation_blocks"] = bool(
            all(value is not None and value > 0.5 for value in validation_aucs)
        )
        rows.append(row)
    return pd.DataFrame.from_records(rows)


def discover_multi_wave_identity(panel: pd.DataFrame) -> MultiWaveIdentityDiscovery:
    """Fit one depth-2 tree on development blocks and freeze at most one leaf."""

    _require_model_panel(panel)
    development = panel.loc[
        panel["feature_complete"].astype(bool) & panel["block"].isin((1, 2, 3))
    ].copy()
    if len(development) < TREE_MIN_SAMPLES_LEAF * 2:
        raise ValueError("multi-wave development sample is too small for the frozen tree")
    features = development.loc[:, list(MULTI_WAVE_FEATURES)].apply(
        pd.to_numeric, errors="raise"
    )
    if not np.isfinite(features.to_numpy(dtype=float)).all():
        raise ValueError("multi-wave development features must be finite")
    target = development["multi_wave_leader"].astype(bool)
    if target.nunique() != 2:
        raise ValueError("multi-wave development requires both identity classes")
    model = DecisionTreeClassifier(
        max_depth=TREE_MAX_DEPTH,
        min_samples_leaf=TREE_MIN_SAMPLES_LEAF,
        random_state=TREE_RANDOM_STATE,
    )
    model.fit(features, target)
    leaf_nodes = model.apply(features)
    base_rate_pct = float(target.mean() * 100.0)
    attempts = []
    for leaf_node, conditions in _leaf_paths(model):
        mask = leaf_nodes == leaf_node
        leaf_target = target.loc[mask]
        precision_pct = float(leaf_target.mean() * 100.0)
        recall_pct = float(leaf_target.sum() / target.sum() * 100.0)
        lift = precision_pct - base_rate_pct
        reasons = []
        if precision_pct <= MIN_DEVELOPMENT_PRECISION_PCT:
            reasons.append("precision_not_strictly_above_60pct")
        if lift < MIN_DEVELOPMENT_LIFT_PCT_POINTS:
            reasons.append("precision_lift_below_5pct_points")
        rule = MultiWaveRule(
            rule_id=f"multi_wave_leaf_{leaf_node}",
            leaf_node=leaf_node,
            conditions=conditions,
        )
        attempts.append(
            MultiWaveLeafAttempt(
                leaf_node=leaf_node,
                rule=rule,
                rows=int(mask.sum()),
                positives=int(leaf_target.sum()),
                precision_pct=precision_pct,
                recall_pct=recall_pct,
                precision_lift_pct_points=lift,
                rejection_reasons=tuple(reasons),
            )
        )
    candidates = sorted(
        (attempt for attempt in attempts if not attempt.rejection_reasons),
        key=lambda attempt: (
            -attempt.precision_pct,
            -attempt.rows,
            attempt.leaf_node,
        ),
    )
    selected_leaf = candidates[0].leaf_node if candidates else None
    frozen_attempts = tuple(
        replace(attempt, selected=attempt.leaf_node == selected_leaf)
        for attempt in sorted(attempts, key=lambda attempt: attempt.leaf_node)
    )
    selected_rule = next(
        (attempt.rule for attempt in frozen_attempts if attempt.selected),
        None,
    )
    return MultiWaveIdentityDiscovery(
        model=model,
        selected_rule=selected_rule,
        attempts=frozen_attempts,
        development_rows=int(len(development)),
        development_base_rate_pct=base_rate_pct,
    )


def apply_multi_wave_rule(
    panel: pd.DataFrame,
    rule: MultiWaveRule,
) -> pd.Series:
    """Apply a frozen tree path using feature columns only."""

    _require_columns(panel, MULTI_WAVE_FEATURES, "multi-wave rule feature")
    selected = pd.Series(True, index=panel.index, dtype=bool)
    for condition in rule.conditions:
        values = pd.to_numeric(panel[condition.feature], errors="coerce")
        selected &= (
            values.le(condition.threshold)
            if condition.operator == "<="
            else values.gt(condition.threshold)
        )
    return selected.fillna(False).astype(bool)


def evaluate_multi_wave_identity(
    panel: pd.DataFrame,
    discovery: MultiWaveIdentityDiscovery,
) -> dict[str, Any]:
    """Evaluate the frozen development leaf once on blocks 4 and 5."""

    _require_model_panel(panel)
    validation = panel.loc[
        panel["feature_complete"].astype(bool) & panel["block"].isin((4, 5))
    ].copy()
    if discovery.selected_rule is None:
        return {
            "overall_conclusion": "no_development_candidate",
            "identity_gate_passed": False,
            "failed_gates": ["no_selected_development_leaf"],
            "selected_validation": _identity_metrics(
                validation.iloc[0:0], validation
            ),
            "validation_model_auc": _model_auc(discovery.model, validation),
            "validation_blocks": [
                {
                    "block": block,
                    **_identity_metrics(
                        validation.iloc[0:0], validation.loc[validation["block"].eq(block)]
                    ),
                    "model_auc": _model_auc(
                        discovery.model,
                        validation.loc[validation["block"].eq(block)],
                    ),
                }
                for block in (4, 5)
            ],
            "trade_outcomes_read": False,
        }
    selected_mask = apply_multi_wave_rule(validation, discovery.selected_rule)
    selected = validation.loc[selected_mask]
    overall = _identity_metrics(selected, validation)
    block_rows = []
    failed = []
    if int(overall["rows"]) < MIN_VALIDATION_ROWS:
        failed.append("fewer_than_100_validation_rows")
    for block in (4, 5):
        universe = validation.loc[validation["block"].eq(block)]
        block_selected = selected.loc[selected["block"].eq(block)]
        metrics = _identity_metrics(block_selected, universe)
        block_rows.append(
            {
                "block": block,
                **metrics,
                "model_auc": _model_auc(discovery.model, universe),
            }
        )
        if int(metrics["rows"]) < MIN_VALIDATION_BLOCK_ROWS:
            failed.append(f"block_{block}_fewer_than_30_rows")
        precision = metrics["precision_pct"]
        if precision is None or precision <= MIN_VALIDATION_BLOCK_PRECISION_PCT:
            failed.append(f"block_{block}_precision_not_strictly_above_60pct")
    return {
        "overall_conclusion": (
            "validated_multi_wave_identity_edge" if not failed else "validation_failed"
        ),
        "identity_gate_passed": not failed,
        "failed_gates": failed,
        "selected_validation": overall,
        "validation_model_auc": _model_auc(discovery.model, validation),
        "validation_blocks": block_rows,
        "trade_outcomes_read": False,
    }


def build_multi_wave_feature_panel(
    labels: pd.DataFrame,
    causal_ranks: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
    memberships: pd.DataFrame,
) -> pd.DataFrame:
    """Attach only decision-date and trailing context to resolved identity labels."""

    label_columns = (
        *EPISODE_IDENTITY_COLUMNS,
        "decision_date",
        "feature_cutoff_date",
        "first_peak_price",
        "first_wave_gain_pct",
        "first_wave_pullback_depth_pct",
        "first_wave_recovery_sessions",
        "first_wave_strong_days",
        "first_wave_max_volume_ratio",
        "first_wave_median_volume_ratio",
        "first_trough_volume_ratio",
        "first_trough_support",
        "first_trough_reclaimed_ma5",
        "first_trough_reclaimed_ma10",
        "second_wave_status",
        "multi_wave_leader",
        "label_status",
        "label_resolution_date",
    )
    _require_columns(labels, label_columns, "multi-wave identity label")
    if labels["episode_id"].duplicated().any():
        raise ValueError("multi-wave label episode IDs must be unique")
    panel = labels.copy()
    for column in (
        "anchor_date",
        "decision_date",
        "feature_cutoff_date",
        "label_resolution_date",
    ):
        panel[column] = pd.to_datetime(panel[column], errors="raise").dt.normalize()
    if not panel["feature_cutoff_date"].eq(panel["decision_date"]).all():
        raise ValueError("label feature cutoff must equal its decision date")

    stock_context = _build_stock_context(stock_bars)
    concept_context = _build_concept_context(concept_bars)
    panel = _attach_stock_context(panel, stock_context)
    panel = _attach_concept_context(panel, concept_context)
    panel = _attach_rank_context(panel, causal_ranks)
    breadth = _build_member_breadth(panel, memberships, stock_context)
    panel = panel.merge(
        breadth,
        on=["sector_id", "decision_date"],
        how="left",
        validate="many_to_one",
    )

    panel["first_trough_support_depth"] = panel["first_trough_support"].map(
        SUPPORT_DEPTH
    )
    for column in (
        "first_trough_reclaimed_ma5",
        "first_trough_reclaimed_ma10",
    ):
        panel[column] = panel[column].astype("boolean").astype(float)
    panel["decision_distance_first_peak_pct"] = (
        panel["decision_close_price"] / panel["first_peak_price"] - 1.0
    ) * 100.0
    panel["decision_distance_ma20_pct"] = (
        panel["decision_close_price"] / panel["decision_ma20"] - 1.0
    ) * 100.0
    panel["stock_gain_since_anchor_pct"] = (
        panel["decision_close_price"] / panel["anchor_stock_close_price"] - 1.0
    ) * 100.0
    panel["concept_gain_since_anchor_pct"] = (
        panel["decision_concept_close_price"]
        / panel["anchor_concept_close_price"]
        - 1.0
    ) * 100.0
    panel["stock_excess_since_anchor_pct"] = (
        panel["stock_gain_since_anchor_pct"]
        - panel["concept_gain_since_anchor_pct"]
    )
    panel["feature_cutoff_date"] = panel["decision_date"]

    numeric_features = panel.loc[:, list(MULTI_WAVE_FEATURES)].apply(
        pd.to_numeric,
        errors="coerce",
    )
    panel.loc[:, list(MULTI_WAVE_FEATURES)] = numeric_features
    finite = np.isfinite(numeric_features.to_numpy(dtype=float))
    panel["feature_complete"] = finite.all(axis=1)
    panel["feature_exclusion_reason"] = [
        None
        if complete
        else "missing:" + ",".join(
            feature
            for feature, available in zip(MULTI_WAVE_FEATURES, row, strict=True)
            if not available
        )
        for complete, row in zip(panel["feature_complete"], finite, strict=True)
    ]
    return panel.sort_values(
        ["decision_date", "episode_id"], kind="stable"
    ).reset_index(drop=True)


def _build_stock_context(stock_bars: pd.DataFrame) -> pd.DataFrame:
    columns = (
        "vt_symbol",
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "turnover",
    )
    _require_columns(stock_bars, columns, "stock daily bar")
    frame = stock_bars.loc[:, list(columns)].copy()
    frame["vt_symbol"] = frame["vt_symbol"].astype(str)
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    if frame.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock daily bar identities must be unique")
    numeric_columns = list(columns[2:])
    frame[numeric_columns] = frame[numeric_columns].apply(
        pd.to_numeric, errors="raise"
    )
    values = frame[numeric_columns].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("stock OHLCV and turnover values must be finite and positive")
    invalid_range = (
        frame["high_price"].lt(frame[["open_price", "close_price"]].max(axis=1))
        | frame["high_price"].lt(frame["low_price"])
        | frame["low_price"].gt(frame[["open_price", "close_price"]].min(axis=1))
    )
    if invalid_range.any():
        raise ValueError("stock daily OHLC ranges are inconsistent")
    frame = frame.sort_values(["vt_symbol", "trade_date"], kind="stable").reset_index(
        drop=True
    )
    grouped = frame.groupby("vt_symbol", sort=False)
    for sessions in (1, 5, 10):
        frame[f"return_{sessions}d_pct"] = (
            grouped["close_price"].pct_change(sessions, fill_method=None) * 100.0
        )
    for sessions in (5, 10, 20):
        frame[f"ma{sessions}"] = grouped["close_price"].transform(
            lambda values, window=sessions: values.rolling(
                window, min_periods=window
            ).mean()
        )
    frame["prior_volume_median_5d"] = grouped["volume"].transform(
        lambda values: values.shift(1).rolling(5, min_periods=5).median()
    )
    frame["volume_ratio_prior5"] = (
        frame["volume"] / frame["prior_volume_median_5d"].replace(0.0, np.nan)
    )
    turnover_mean_5 = grouped["turnover"].transform(
        lambda values: values.rolling(5, min_periods=5).mean()
    )
    turnover_previous_20 = grouped["turnover"].transform(
        lambda values: values.shift(5).rolling(20, min_periods=15).mean()
    )
    frame["turnover_expansion"] = turnover_mean_5 / turnover_previous_20.replace(
        0.0, np.nan
    )
    strong_day = frame["return_1d_pct"].ge(5.0).astype(float)
    frame["recent_strong_5d"] = strong_day.groupby(frame["vt_symbol"]).transform(
        lambda values: values.rolling(5, min_periods=5).max()
    )
    frame["main_rise_alive"] = (
        frame["close_price"].ge(frame["ma5"])
        & frame["ma5"].gt(frame["ma10"])
        & frame["ma10"].gt(frame["ma20"])
    )
    frame["member_feature_complete"] = frame[
        ["return_5d_pct", "recent_strong_5d", "ma5", "ma10", "ma20"]
    ].notna().all(axis=1)
    return frame


def _build_concept_context(concept_bars: pd.DataFrame) -> pd.DataFrame:
    columns = ("sector_id", "trade_date", "close_price", "turnover")
    _require_columns(concept_bars, columns, "concept daily bar")
    frame = concept_bars.loc[:, list(columns)].copy()
    frame["sector_id"] = frame["sector_id"].astype(str)
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    if frame.duplicated(["sector_id", "trade_date"]).any():
        raise ValueError("concept daily bar identities must be unique")
    frame[["close_price", "turnover"]] = frame[
        ["close_price", "turnover"]
    ].apply(pd.to_numeric, errors="raise")
    values = frame[["close_price", "turnover"]].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("concept close and turnover must be finite")
    if frame["close_price"].le(0).any() or frame["turnover"].lt(0).any():
        raise ValueError("concept closes must be positive and turnover non-negative")
    frame = frame.sort_values(["sector_id", "trade_date"], kind="stable").reset_index(
        drop=True
    )
    grouped = frame.groupby("sector_id", sort=False)
    for sessions in (5, 10):
        frame[f"return_{sessions}d_pct"] = (
            grouped["close_price"].pct_change(sessions, fill_method=None) * 100.0
        )
    turnover_mean_5 = grouped["turnover"].transform(
        lambda values: values.rolling(5, min_periods=5).mean()
    )
    turnover_previous_20 = grouped["turnover"].transform(
        lambda values: values.shift(5).rolling(20, min_periods=15).mean()
    )
    frame["turnover_expansion"] = turnover_mean_5 / turnover_previous_20.replace(
        0.0, np.nan
    )
    return frame


def _attach_stock_context(
    panel: pd.DataFrame,
    stock_context: pd.DataFrame,
) -> pd.DataFrame:
    decision = stock_context.loc[
        :,
        [
            "vt_symbol",
            "trade_date",
            "close_price",
            "return_1d_pct",
            "return_5d_pct",
            "return_10d_pct",
            "volume_ratio_prior5",
            "turnover_expansion",
            "ma20",
        ],
    ].rename(
        columns={
            "trade_date": "decision_date",
            "close_price": "decision_close_price",
            "return_1d_pct": "decision_return_1d_pct",
            "return_5d_pct": "decision_return_5d_pct",
            "return_10d_pct": "decision_return_10d_pct",
            "volume_ratio_prior5": "decision_volume_ratio_prior5",
            "turnover_expansion": "decision_turnover_expansion",
            "ma20": "decision_ma20",
        }
    )
    anchor = stock_context.loc[
        :, ["vt_symbol", "trade_date", "close_price"]
    ].rename(
        columns={
            "trade_date": "anchor_date",
            "close_price": "anchor_stock_close_price",
        }
    )
    return panel.merge(
        decision,
        on=["vt_symbol", "decision_date"],
        how="left",
        validate="one_to_one",
    ).merge(
        anchor,
        on=["vt_symbol", "anchor_date"],
        how="left",
        validate="one_to_one",
    )


def _attach_concept_context(
    panel: pd.DataFrame,
    concept_context: pd.DataFrame,
) -> pd.DataFrame:
    decision = concept_context.loc[
        :,
        [
            "sector_id",
            "trade_date",
            "close_price",
            "return_5d_pct",
            "return_10d_pct",
            "turnover_expansion",
        ],
    ].rename(
        columns={
            "trade_date": "decision_date",
            "close_price": "decision_concept_close_price",
            "return_5d_pct": "concept_return_5d_pct",
            "return_10d_pct": "concept_return_10d_pct",
            "turnover_expansion": "concept_turnover_expansion",
        }
    )
    anchor = concept_context.loc[
        :, ["sector_id", "trade_date", "close_price"]
    ].rename(
        columns={
            "trade_date": "anchor_date",
            "close_price": "anchor_concept_close_price",
        }
    )
    return panel.merge(
        decision,
        on=["sector_id", "decision_date"],
        how="left",
        validate="many_to_one",
    ).merge(
        anchor,
        on=["sector_id", "anchor_date"],
        how="left",
        validate="many_to_one",
    )


def _attach_rank_context(
    panel: pd.DataFrame,
    causal_ranks: pd.DataFrame,
) -> pd.DataFrame:
    columns = (
        "cycle_id",
        "vt_symbol",
        "trade_date",
        "feature_cutoff_date",
        "causal_rank",
        "candidate_pool_size",
    )
    _require_columns(causal_ranks, columns, "causal leader rank")
    ranks = causal_ranks.loc[:, list(columns)].copy()
    for column in ("trade_date", "feature_cutoff_date"):
        ranks[column] = pd.to_datetime(ranks[column], errors="raise").dt.normalize()
    if not ranks["trade_date"].eq(ranks["feature_cutoff_date"]).all():
        raise ValueError("causal rank cutoff must equal its trade date")
    if ranks.duplicated(["cycle_id", "vt_symbol"]).any():
        raise ValueError("causal leader rank identities must be unique")
    context = ranks.rename(
        columns={
            "trade_date": "rank_anchor_date",
            "feature_cutoff_date": "rank_feature_cutoff_date",
            "causal_rank": "rank_causal_rank",
        }
    )
    result = panel.merge(
        context,
        on=["cycle_id", "vt_symbol"],
        how="left",
        validate="one_to_one",
    )
    mismatch = (
        result["rank_anchor_date"].notna()
        & ~result["rank_anchor_date"].eq(result["anchor_date"])
    )
    if mismatch.any():
        raise ValueError("episode anchor disagrees with its causal rank date")
    episode_rank = pd.to_numeric(result["causal_rank"], errors="coerce")
    rank_value = pd.to_numeric(result.pop("rank_causal_rank"), errors="coerce")
    if (episode_rank.notna() & rank_value.notna() & ~episode_rank.eq(rank_value)).any():
        raise ValueError("episode causal rank disagrees with frozen rank context")
    result["causal_rank"] = rank_value
    return result


def _build_member_breadth(
    panel: pd.DataFrame,
    memberships: pd.DataFrame,
    stock_context: pd.DataFrame,
) -> pd.DataFrame:
    columns = ("sector_id", "vt_symbol")
    _require_columns(memberships, columns, "current concept membership")
    members = memberships.loc[:, list(columns)].copy()
    members["sector_id"] = members["sector_id"].astype(str)
    members["vt_symbol"] = members["vt_symbol"].astype(str)
    if members.duplicated(list(columns)).any():
        raise ValueError("current concept membership identities must be unique")
    contexts = panel.loc[:, ["sector_id", "decision_date"]].drop_duplicates()
    expanded = contexts.merge(
        members,
        on="sector_id",
        how="left",
        validate="many_to_many",
    ).merge(
        stock_context.loc[
            :,
            [
                "vt_symbol",
                "trade_date",
                "return_5d_pct",
                "recent_strong_5d",
                "main_rise_alive",
                "member_feature_complete",
            ],
        ],
        left_on=["vt_symbol", "decision_date"],
        right_on=["vt_symbol", "trade_date"],
        how="left",
        validate="many_to_one",
    )
    complete = expanded.loc[expanded["member_feature_complete"].fillna(False)].copy()
    if complete.empty:
        return pd.DataFrame(
            columns=[
                "sector_id",
                "decision_date",
                "breadth_member_count",
                "member_positive_5d_breadth_pct",
                "member_recent_strong_5d_breadth_pct",
                "member_main_rise_breadth_pct",
            ]
        )
    complete["positive_5d"] = complete["return_5d_pct"].gt(0)
    grouped = complete.groupby(["sector_id", "decision_date"], sort=False)
    return grouped.agg(
        breadth_member_count=("vt_symbol", "nunique"),
        member_positive_5d_breadth_pct=("positive_5d", _boolean_pct),
        member_recent_strong_5d_breadth_pct=("recent_strong_5d", _boolean_pct),
        member_main_rise_breadth_pct=("main_rise_alive", _boolean_pct),
    ).reset_index()


def _boolean_pct(values: pd.Series) -> float:
    return float(values.astype(bool).mean() * 100.0)


def _leaf_paths(
    model: DecisionTreeClassifier,
) -> list[tuple[int, tuple[MultiWaveCondition, ...]]]:
    tree = model.tree_
    feature_names = [str(value) for value in model.feature_names_in_]
    paths: list[tuple[int, tuple[MultiWaveCondition, ...]]] = []

    def visit(node: int, conditions: tuple[MultiWaveCondition, ...]) -> None:
        left = int(tree.children_left[node])
        right = int(tree.children_right[node])
        if left == right:
            paths.append((node, conditions))
            return
        feature = feature_names[int(tree.feature[node])]
        threshold = float(tree.threshold[node])
        visit(left, (*conditions, MultiWaveCondition(feature, "<=", threshold)))
        visit(right, (*conditions, MultiWaveCondition(feature, ">", threshold)))

    visit(0, ())
    return sorted(paths, key=lambda item: item[0])


def _identity_metrics(
    selected: pd.DataFrame,
    universe: pd.DataFrame,
) -> dict[str, int | float | None]:
    selected_target = selected.get(
        "multi_wave_leader", pd.Series(dtype=bool)
    ).astype(bool)
    universe_target = universe.get(
        "multi_wave_leader", pd.Series(dtype=bool)
    ).astype(bool)
    positives = int(selected_target.sum())
    universe_positives = int(universe_target.sum())
    return {
        "rows": int(len(selected)),
        "positives": positives,
        "universe_rows": int(len(universe)),
        "universe_positives": universe_positives,
        "precision_pct": (
            float(positives / len(selected) * 100.0) if len(selected) else None
        ),
        "recall_pct": (
            float(positives / universe_positives * 100.0)
            if universe_positives
            else None
        ),
        "universe_base_rate_pct": (
            float(universe_positives / len(universe) * 100.0)
            if len(universe)
            else None
        ),
    }


def _model_auc(
    model: DecisionTreeClassifier,
    frame: pd.DataFrame,
) -> float | None:
    if frame.empty:
        return None
    target = frame["multi_wave_leader"].astype(bool).to_numpy()
    features = frame.loc[:, list(MULTI_WAVE_FEATURES)].apply(
        pd.to_numeric, errors="raise"
    )
    classes = list(model.classes_)
    if True not in classes:
        return None
    probability = model.predict_proba(features)[:, classes.index(True)]
    return _roc_auc(target, probability)


def _directional_auc(
    target: np.ndarray,
    values: np.ndarray,
    direction: str,
) -> float | None:
    directed = values if direction == "higher" else -values
    return _roc_auc(target, directed)


def _roc_auc(target: np.ndarray, values: np.ndarray) -> float | None:
    if not len(target) or len(np.unique(target)) != 2:
        return None
    if not np.isfinite(values).all():
        raise ValueError("AUC values must be finite")
    return float(roc_auc_score(target, values))


def _require_model_panel(panel: pd.DataFrame) -> None:
    _require_columns(
        panel,
        (
            "episode_id",
            "decision_date",
            "block",
            "multi_wave_leader",
            "feature_complete",
            *MULTI_WAVE_FEATURES,
        ),
        "multi-wave model panel",
    )
    if panel["episode_id"].duplicated().any():
        raise ValueError("multi-wave model episode IDs must be unique")
    if not set(pd.to_numeric(panel["block"], errors="raise").unique()).issubset(
        {1, 2, 3, 4, 5}
    ):
        raise ValueError("multi-wave model blocks must be between one and five")


def _rule_payload(rule: MultiWaveRule | None) -> dict[str, Any] | None:
    return _json_safe(asdict(rule)) if rule is not None else None


def _attempt_payload(attempt: MultiWaveLeafAttempt) -> dict[str, Any]:
    return _json_safe(asdict(attempt))


def _representative_cases(
    cohort: MultiWaveIdentityCohort,
    panel: pd.DataFrame,
    rule: MultiWaveRule | None,
) -> dict[str, list[dict[str, Any]]]:
    complete = panel.loc[panel["feature_complete"].astype(bool)].copy()
    result = {
        "continued": _case_records(
            complete.loc[complete["multi_wave_leader"].astype(bool)]
        ),
        "terminal": _case_records(
            complete.loc[~complete["multi_wave_leader"].astype(bool)]
        ),
        "censored": _case_records(cohort.censored),
        "selected_validation_true_positive": [],
        "selected_validation_false_positive": [],
    }
    if rule is None or complete.empty:
        return result
    validation = complete.loc[complete["block"].isin((4, 5))].copy()
    selected = validation.loc[apply_multi_wave_rule(validation, rule)]
    result["selected_validation_true_positive"] = _case_records(
        selected.loc[selected["multi_wave_leader"].astype(bool)]
    )
    result["selected_validation_false_positive"] = _case_records(
        selected.loc[~selected["multi_wave_leader"].astype(bool)]
    )
    return result


def _case_records(frame: pd.DataFrame, limit: int = 5) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    preferred = (
        "episode_id",
        "vt_symbol",
        "stock_name",
        "sector_id",
        "concept_name",
        "anchor_date",
        "decision_date",
        "block",
        "second_wave_status",
        "multi_wave_leader",
        "first_wave_gain_pct",
        "first_wave_pullback_depth_pct",
        "first_wave_recovery_sessions",
        "first_trough_support_depth",
        "decision_return_5d_pct",
        "concept_return_5d_pct",
        "stock_excess_since_anchor_pct",
        "member_recent_strong_5d_breadth_pct",
        "member_main_rise_breadth_pct",
        "causal_rank",
        "candidate_pool_size",
    )
    columns = [column for column in preferred if column in frame]
    sort_columns = [
        column for column in ("decision_date", "episode_id") if column in frame
    ]
    ordered = frame.sort_values(sort_columns, kind="stable") if sort_columns else frame
    if len(ordered) > limit:
        positions = np.linspace(0, len(ordered) - 1, num=limit, dtype=int)
        ordered = ordered.iloc[positions]
    return _records(ordered.loc[:, columns])


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _rule_text(value: object) -> str:
    rule = _mapping(value)
    if not rule:
        return "none"
    conditions = []
    for raw in _sequence(rule.get("conditions")):
        condition = _mapping(raw)
        conditions.append(
            f"{condition.get('feature')} {condition.get('operator')} "
            f"{_number(condition.get('threshold'))}"
        )
    return " and ".join(conditions) if conditions else "all development rows"


def _date_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date().isoformat()


def _pct(value: object) -> str:
    numeric = _finite_or_none(value)
    return "null" if numeric is None else f"{numeric:.4f}%"


def _number(value: object) -> str:
    numeric = _finite_or_none(value)
    return "null" if numeric is None else f"{numeric:.4f}"


def _finite_or_none(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, date)):
        return pd.Timestamp(value).date().isoformat()
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(float(value)) else None
    try:
        return None if pd.isna(value) else value
    except (TypeError, ValueError):
        return value


def build_multi_wave_identity_labels(
    episodes: pd.DataFrame,
    waves: pd.DataFrame,
    impulses: pd.DataFrame,
) -> MultiWaveIdentityCohort:
    """Label resolved wave 2 only after wave 1 has confirmed a higher high."""

    _require_columns(episodes, EPISODE_IDENTITY_COLUMNS, "leader episode")
    _require_columns(waves, FIRST_WAVE_COLUMNS, "leader wave")
    _require_columns(impulses, IMPULSE_COLUMNS, "leader wave impulse")
    if episodes["episode_id"].duplicated().any():
        raise ValueError("leader episode IDs must be unique")
    if waves.duplicated(["episode_id", "wave_number"]).any():
        raise ValueError("leader wave identities must be unique")
    if impulses.duplicated(["episode_id", "wave_number"]).any():
        raise ValueError("leader impulse identities must be unique")

    first = waves.loc[
        waves["wave_number"].eq(1)
        & waves["resolution_status"].eq(POSITIVE_SECOND_WAVE_STATUS),
        list(FIRST_WAVE_COLUMNS),
    ].copy()
    if first.empty:
        empty = _empty_label_frame()
        return MultiWaveIdentityCohort(empty, empty.copy())
    first["higher_high_date"] = pd.to_datetime(
        first["higher_high_date"], errors="raise"
    ).dt.normalize()
    if first["higher_high_date"].isna().any():
        raise ValueError("continued first waves require a higher-high decision date")

    first_impulses = impulses.loc[
        impulses["wave_number"].eq(1),
        list(IMPULSE_COLUMNS),
    ].drop(columns="wave_number")
    first = first.merge(
        first_impulses,
        on="episode_id",
        how="left",
        validate="one_to_one",
    )
    impulse_features = list(IMPULSE_COLUMNS[2:])
    if first[impulse_features].isna().any().any():
        raise ValueError("continued first waves require complete impulse descriptors")

    second = waves.loc[
        waves["wave_number"].eq(2),
        [
            "episode_id",
            "resolution_status",
            "higher_high_date",
            "structural_break_date",
        ],
    ].rename(
        columns={
            "resolution_status": "second_wave_status",
            "higher_high_date": "second_higher_high_date",
            "structural_break_date": "second_structural_break_date",
        }
    )
    decision = first.merge(
        episodes.loc[:, list(EPISODE_IDENTITY_COLUMNS)],
        on="episode_id",
        how="inner",
        validate="one_to_one",
    ).merge(second, on="episode_id", how="left", validate="one_to_one")
    if decision["second_wave_status"].isna().any():
        raise ValueError("continued first waves require an observed second wave row")
    unexpected = sorted(
        set(decision["second_wave_status"].astype(str))
        - {
            POSITIVE_SECOND_WAVE_STATUS,
            NEGATIVE_SECOND_WAVE_STATUS,
            *CENSORED_SECOND_WAVE_STATUSES,
        }
    )
    if unexpected:
        raise ValueError(f"unsupported second-wave statuses: {', '.join(unexpected)}")

    result = _normalize_decision_columns(decision)
    resolved = result["second_wave_status"].isin(
        (POSITIVE_SECOND_WAVE_STATUS, NEGATIVE_SECOND_WAVE_STATUS)
    )
    labels = result.loc[resolved].copy()
    labels["multi_wave_leader"] = labels["second_wave_status"].eq(
        POSITIVE_SECOND_WAVE_STATUS
    )
    labels["label_status"] = np.where(
        labels["multi_wave_leader"],
        "second_wave_continued",
        "second_wave_terminal",
    )
    labels["label_resolution_date"] = pd.to_datetime(
        labels["second_higher_high_date"].where(
            labels["multi_wave_leader"],
            labels["second_structural_break_date"],
        ),
        errors="coerce",
    ).dt.normalize()
    if labels["label_resolution_date"].isna().any():
        raise ValueError("resolved second waves require an observable resolution date")
    if labels["label_resolution_date"].lt(labels["decision_date"]).any():
        raise ValueError("second-wave resolution cannot precede the decision date")

    censored = result.loc[~resolved].copy()
    censored["multi_wave_leader"] = pd.Series(
        pd.array([pd.NA] * len(censored), dtype="boolean"),
        index=censored.index,
    )
    censored["label_status"] = "right_censored_second_wave"
    censored["label_resolution_date"] = pd.NaT
    return MultiWaveIdentityCohort(
        labels.sort_values(["decision_date", "episode_id"], kind="stable").reset_index(
            drop=True
        ),
        censored.sort_values(
            ["decision_date", "episode_id"], kind="stable"
        ).reset_index(drop=True),
    )


def _normalize_decision_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    date_columns = (
        "anchor_date",
        "observation_end",
        "wave_start_date",
        "peak_date",
        "trough_date",
        "higher_high_date",
        "second_higher_high_date",
        "second_structural_break_date",
    )
    for column in date_columns:
        result[column] = pd.to_datetime(result[column], errors="coerce").dt.normalize()
    result = result.rename(
        columns={
            "wave_start_date": "first_wave_start_date",
            "peak_date": "first_peak_date",
            "peak_price": "first_peak_price",
            "trough_date": "first_trough_date",
            "trough_price": "first_trough_price",
            "recovery_sessions": "first_wave_recovery_sessions",
            "trough_volume_ratio_5d": "first_trough_volume_ratio",
            "deepest_tested_support": "first_trough_support",
            "trough_close_reclaimed_ma5": "first_trough_reclaimed_ma5",
            "trough_close_reclaimed_ma10": "first_trough_reclaimed_ma10",
            "impulse_gain_pct": "first_wave_gain_pct",
            "strong_days_ge_9_5pct": "first_wave_strong_days",
            "max_volume_ratio_prior5": "first_wave_max_volume_ratio",
            "median_volume_ratio_prior5": "first_wave_median_volume_ratio",
        }
    )
    result["first_wave_pullback_depth_pct"] = -pd.to_numeric(
        result.pop("pullback_pct"), errors="raise"
    )
    result["decision_date"] = result.pop("higher_high_date")
    result["feature_cutoff_date"] = result["decision_date"]
    result = result.drop(columns=["wave_number", "resolution_status"])
    return result


def _empty_label_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            *EPISODE_IDENTITY_COLUMNS,
            "decision_date",
            "feature_cutoff_date",
            "second_wave_status",
            "multi_wave_leader",
            "label_status",
            "label_resolution_date",
        ]
    )


def _require_columns(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    label: str,
) -> None:
    missing = sorted(set(columns) - set(frame))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
