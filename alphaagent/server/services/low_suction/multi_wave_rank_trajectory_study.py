"""Exploratory daily concept-rank trajectories before a second-wave label."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


STUDY_VERSION = "multi-wave-rank-trajectory-v1"
MEMBERSHIP_EVIDENCE = "current_membership_and_security_proxy"
MIN_DEVELOPMENT_DIRECTIONAL_AUC = 0.60
MIN_VALIDATION_DIRECTIONAL_AUC = 0.55
MIN_STABLE_BLOCKS = 4
MIN_BLOCK_ROWS = 30
RANK_TRAJECTORY_FEATURES = (
    "leader_path_top1_share_pct",
    "leader_path_top3_share_pct",
    "leader_recovery_top3_share_pct",
    "leader_peak_strength_pct",
    "leader_trough_strength_pct",
    "leader_decision_strength_pct",
    "leader_worst_strength_pct",
    "leader_strength_std_pct",
    "leader_peak_to_decision_strength_change_pct_points",
    "leader_trough_to_decision_strength_change_pct_points",
    "leader_top3_streak_to_decision_sessions",
    "leader_decision_gap_to_best_other_pct",
    "leader_decision_gap_to_top3_mean_pct",
    "leader_decision_turnover_strength_pct",
    "leader_path_median_turnover_strength_pct",
    "positive_breadth_trough_to_decision_change_pct_points",
    "strong_breadth_trough_to_decision_change_pct_points",
    "top3_concentration_trough_to_decision_change_pct_points",
)

LABEL_COLUMNS = (
    "episode_id",
    "cohort",
    "vt_symbol",
    "stock_name",
    "sector_id",
    "concept_name",
    "anchor_date",
    "first_peak_date",
    "first_trough_date",
    "decision_date",
    "feature_cutoff_date",
    "second_wave_status",
    "multi_wave_leader",
)


@dataclass(frozen=True)
class RankTrajectoryResult:
    panel: pd.DataFrame
    daily_path: pd.DataFrame
    member_ledger: pd.DataFrame
    exclusions: pd.DataFrame


def run_multi_wave_rank_trajectory_study() -> dict[str, Any]:
    """Run the fixed rank-trajectory diagnosis on resolved wave-2 labels."""

    from .cross_leader_wave_study import (
        build_causal_wave_episodes,
        filter_complete_episode_paths,
        replay_leader_wave_episodes,
    )
    from .multi_wave_leader_identity_study import (
        assign_multi_wave_time_blocks,
        build_multi_wave_identity_labels,
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
    labels = assign_multi_wave_time_blocks(cohort.labels)
    result = build_multi_wave_rank_trajectory(
        labels,
        inputs.memberships,
        inputs.stock_bars,
        trading_dates=inputs.trading_dates,
    )
    classified_panel = attach_rank_trajectory_classes(result.panel)
    result = RankTrajectoryResult(
        panel=classified_panel,
        daily_path=result.daily_path,
        member_ledger=result.member_ledger,
        exclusions=result.exclusions,
    )
    diagnostics = evaluate_rank_trajectory_features(result.panel)
    class_summary = summarize_rank_trajectory_classes(result.panel)
    new_information_coverage = _load_new_information_coverage(
        tuple(sorted(labels["decision_date"].dt.date.unique()))
    )

    fingerprint_frames = {
        "rank_trajectory_panel": (result.panel, ("episode_id",)),
        "rank_trajectory_daily_path": (
            result.daily_path,
            ("episode_id", "trade_date"),
        ),
        "rank_trajectory_member_ledger": (
            result.member_ledger,
            ("episode_id", "trade_date", "member_vt_symbol"),
        ),
    }
    generated_fingerprints = {
        name: fingerprint_frame(frame, identity_columns=identity).as_dict()
        for name, (frame, identity) in fingerprint_frames.items()
    }
    coverage = {
        **inputs.coverage,
        "causal_rank_rows": int(len(causal_ranks)),
        "selected_non_overlapping_episodes": int(len(selected_episodes)),
        "complete_non_overlapping_episodes": int(len(episodes)),
        "incomplete_fixed_path_exclusions": int(len(path_exclusions)),
        "successful_first_waves": int(len(cohort.labels) + len(cohort.censored)),
        "resolved_second_wave_labels": int(len(labels)),
        "right_censored_second_waves": int(len(cohort.censored)),
        "trade_outcome_rows_read": 0,
        "minute_rows_read": 0,
        "timing_rows_read": 0,
    }
    return build_rank_trajectory_report(
        result=result,
        diagnostics=diagnostics,
        class_summary=class_summary,
        new_information_coverage=new_information_coverage,
        coverage=coverage,
        fingerprints={**inputs.fingerprints, **generated_fingerprints},
    )


def build_rank_trajectory_report(
    *,
    result: RankTrajectoryResult,
    diagnostics: pd.DataFrame,
    class_summary: pd.DataFrame,
    new_information_coverage: Mapping[str, Any],
    coverage: Mapping[str, Any],
    fingerprints: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build reused-history rank diagnostics with formal metrics quarantined."""

    candidates = diagnostics.loc[
        diagnostics["candidate_for_new_forward_block"].astype(bool)
    ]
    complete = result.panel.loc[result.panel["feature_complete"].astype(bool)]
    report = {
        "study_version": STUDY_VERSION,
        "research_status": (
            "exploratory_candidate_requires_new_forward_block"
            if not candidates.empty
            else "no_stable_rank_trajectory_feature"
        ),
        "validation_status": "reused_history_not_validation",
        "formal_strategy": False,
        "formal_metrics": {
            "win_rate_pct": None,
            "compounded_return_pct": None,
            "profit_factor": None,
            "maximum_drawdown_pct": None,
        },
        "membership_evidence": MEMBERSHIP_EVIDENCE,
        "trajectory_contract": {
            "start": "causal_top3_episode_anchor",
            "cutoff": "wave_1_first_rebreak_session_close",
            "rank_observations_exclude_anchor_tie": True,
            "member_denominator": "current_proxy_members_with_complete_episode_path",
            "minimum_complete_members": 3,
            "gain_rank_order": [
                "cumulative_gain_desc",
                "turnover_expansion_desc",
                "vt_symbol_asc",
            ],
            "features": list(RANK_TRAJECTORY_FEATURES),
            "trajectory_classes": {
                "persistent_leader": (
                    "path_top3>=80 and recovery_top3>=80 and decision_strength>=80"
                ),
                "lost_leadership": (
                    "decision_strength<50 or recovery_top3<50"
                ),
                "mixed_trajectory": "all_remaining_paths",
            },
        },
        "candidate_gate": {
            "development_blocks": [1, 2, 3],
            "validation_direction_blocks": [4, 5],
            "development_directional_auc_min": MIN_DEVELOPMENT_DIRECTIONAL_AUC,
            "validation_directional_auc_min": MIN_VALIDATION_DIRECTIONAL_AUC,
            "minimum_stable_blocks": MIN_STABLE_BLOCKS,
            "minimum_rows_per_block": MIN_BLOCK_ROWS,
            "candidate_count": int(len(candidates)),
            "candidate_features": candidates["feature"].astype(str).tolist(),
            "promotion": "new_forward_block_only",
        },
        "new_information_coverage": _json_safe(dict(new_information_coverage)),
        "coverage": {
            **dict(coverage),
            "trajectory_panel_rows": int(len(result.panel)),
            "trajectory_feature_complete_rows": int(len(complete)),
            "trajectory_feature_incomplete_rows": int(len(result.panel) - len(complete)),
            "trajectory_episode_exclusions": int(len(result.exclusions)),
            "trajectory_daily_leader_rows": int(len(result.daily_path)),
            "trajectory_member_rows": int(len(result.member_ledger)),
            "trajectory_symbols": int(
                complete["vt_symbol"].nunique() if "vt_symbol" in complete else 0
            ),
            "trajectory_decision_dates": int(
                complete["decision_date"].nunique()
                if "decision_date" in complete
                else 0
            ),
        },
        "feature_diagnostics": _records(diagnostics),
        "trajectory_class_summary": _records(class_summary),
        "representative_cases": _representative_trajectory_cases(result),
        "boundaries": [
            "all five historical blocks were already viewed in the prior identity study",
            "current concept memberships create survivorship bias",
            "local fund flow and membership snapshots overlap zero label dates",
            "free EastMoney historical fund-flow probes expose recent data only and were not imported",
            "trajectory continuation share is not low-suction trade win rate",
            "no wave-2 path, minute bar, timing regime or trade return is a predictor",
        ],
        "fingerprints": _json_safe(dict(fingerprints)),
    }
    return _json_safe(report)


def render_rank_trajectory_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def render_rank_trajectory_markdown(report: Mapping[str, Any]) -> str:
    coverage = _mapping(report.get("coverage"))
    candidate_gate = _mapping(report.get("candidate_gate"))
    new_information = _mapping(report.get("new_information_coverage"))
    lines = [
        "# AlphaAgent 第一浪概念内动态排名轨迹研究",
        "",
        f"研究状态：`{report.get('research_status')}`；验证边界："
        f"`{report.get('validation_status')}`。",
        "正式低吸胜率、收益、复利：`null`。以下只描述已查看历史中的身份轨迹。",
        "",
        "## Coverage",
        "",
        f"- 已决第二浪标签：`{coverage.get('resolved_second_wave_labels', 0)}`；轨迹面板 "
        f"`{coverage.get('trajectory_panel_rows', 0)}`，完整特征 "
        f"`{coverage.get('trajectory_feature_complete_rows', 0)}`。",
        f"- 轨迹剔除：`{coverage.get('trajectory_episode_exclusions', 0)}`；每日龙头行 "
        f"`{coverage.get('trajectory_daily_leader_rows', 0)}`，成员日行 "
        f"`{coverage.get('trajectory_member_rows', 0)}`。",
        f"- 候选特征：`{candidate_gate.get('candidate_count', 0)}`；只能进入新的前向块。",
        "",
        "## 新信息覆盖",
        "",
        "| 数据 | 日期数 | 范围 | 标签重合日 | 是否读取 |",
        "| --- | ---: | --- | ---: | --- |",
        _coverage_line("个股资金流", "stock_fund_flow", new_information),
        _coverage_line("板块资金流", "sector_fund_flow", new_information),
        _coverage_line("成员快照", "membership_snapshot", new_information),
        _coverage_line("板块资金快照", "sector_fund_flow_snapshot", new_information),
        "",
        "这些数据与 2023-2025 决策日重合为 0，因此没有硬拼到历史特征。",
        "",
        "## 单特征轨迹",
        "",
        "方向只由 block 1-3 决定；所有时间块都已被历史研究查看过。",
        "",
        "| 特征 | 方向 | 开发 AUC | B1 | B2 | B3 | B4 | B5 | 稳定块 | 状态 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    diagnostics = sorted(
        (_mapping(row) for row in _sequence(report.get("feature_diagnostics"))),
        key=lambda row: -float(row.get("development_directional_auc") or 0.0),
    )
    for row in diagnostics:
        lines.append(
            f"| `{row.get('feature')}` | `{row.get('direction')}` | "
            f"{_number(row.get('development_directional_auc'))} | "
            f"{_number(row.get('block_1_directional_auc'))} | "
            f"{_number(row.get('block_2_directional_auc'))} | "
            f"{_number(row.get('block_3_directional_auc'))} | "
            f"{_number(row.get('block_4_directional_auc'))} | "
            f"{_number(row.get('block_5_directional_auc'))} | "
            f"{row.get('stable_blocks', 0)} | `{row.get('status')}` |"
        )
    lines.extend(
        [
            "",
            "## 冻结轨迹分类",
            "",
            "| Scope | 轨迹 | 样本 | 续浪 | 续浪比例 |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for row in _sequence(report.get("trajectory_class_summary")):
        item = _mapping(row)
        lines.append(
            f"| `{item.get('scope')}` | `{item.get('trajectory_class')}` | "
            f"{item.get('rows', 0)} | {item.get('positives', 0)} | "
            f"{_pct(item.get('continuation_share_pct'))} |"
        )
    lines.extend(_representative_case_lines(report))
    lines.extend(
        [
            "",
            "## 边界",
            "",
            *[f"- {item}" for item in _sequence(report.get("boundaries"))],
            "",
            "## Reproduce",
            "",
            "```bash",
            "docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-multi-wave-rank-trajectory-study --format markdown",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def classify_rank_trajectory(
    *,
    path_top3_share_pct: float,
    recovery_top3_share_pct: float,
    decision_strength_pct: float,
) -> str:
    """Apply the predeclared persistence/loss classes without fitting thresholds."""

    persistent = (
        path_top3_share_pct >= 80.0
        and recovery_top3_share_pct >= 80.0
        and decision_strength_pct >= 80.0
    )
    if persistent:
        return "persistent_leader"
    if decision_strength_pct < 50.0 or recovery_top3_share_pct < 50.0:
        return "lost_leadership"
    return "mixed_trajectory"


def attach_rank_trajectory_classes(panel: pd.DataFrame) -> pd.DataFrame:
    """Attach one mutually exclusive descriptive trajectory class."""

    columns = (
        "leader_path_top3_share_pct",
        "leader_recovery_top3_share_pct",
        "leader_decision_strength_pct",
    )
    _require_columns(panel, columns, "rank trajectory class")
    result = panel.copy()
    persistent = (
        pd.to_numeric(result[columns[0]], errors="coerce").ge(80.0)
        & pd.to_numeric(result[columns[1]], errors="coerce").ge(80.0)
        & pd.to_numeric(result[columns[2]], errors="coerce").ge(80.0)
    )
    lost = (
        pd.to_numeric(result[columns[2]], errors="coerce").lt(50.0)
        | pd.to_numeric(result[columns[1]], errors="coerce").lt(50.0)
    )
    result["trajectory_class"] = np.select(
        [persistent, lost],
        ["persistent_leader", "lost_leadership"],
        default="mixed_trajectory",
    )
    return result


def evaluate_rank_trajectory_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Freeze feature direction on blocks 1-3 and diagnose all five blocks."""

    _require_diagnostic_panel(panel)
    complete = panel.loc[panel["feature_complete"].astype(bool)].copy()
    development = complete.loc[complete["block"].isin((1, 2, 3))]
    if development["multi_wave_leader"].nunique() != 2:
        raise ValueError("trajectory development requires both label classes")
    records = []
    for feature in RANK_TRAJECTORY_FEATURES:
        development_values = pd.to_numeric(
            development[feature], errors="raise"
        ).to_numpy(dtype=float)
        development_target = development["multi_wave_leader"].astype(bool).to_numpy()
        raw_auc = _roc_auc(development_target, development_values)
        direction = "higher" if raw_auc is None or raw_auc >= 0.5 else "lower"
        record: dict[str, object] = {
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
        sufficient_blocks = 0
        stable_blocks = 0
        for block in range(1, 6):
            block_frame = complete.loc[complete["block"].eq(block)]
            block_values = pd.to_numeric(
                block_frame[feature], errors="raise"
            ).to_numpy(dtype=float)
            block_target = block_frame["multi_wave_leader"].astype(bool).to_numpy()
            auc = _directional_auc(block_target, block_values, direction)
            rows = int(len(block_frame))
            sufficient = bool(
                rows >= MIN_BLOCK_ROWS and len(np.unique(block_target)) == 2
            )
            sufficient_blocks += int(sufficient)
            stable_blocks += int(
                sufficient and auc is not None and auc >= MIN_VALIDATION_DIRECTIONAL_AUC
            )
            record[f"block_{block}_rows"] = rows
            record[f"block_{block}_directional_auc"] = auc
        development_auc = record["development_directional_auc"]
        block_4_auc = record["block_4_directional_auc"]
        block_5_auc = record["block_5_directional_auc"]
        candidate = bool(
            development_auc is not None
            and float(development_auc) >= MIN_DEVELOPMENT_DIRECTIONAL_AUC
            and block_4_auc is not None
            and float(block_4_auc) >= MIN_VALIDATION_DIRECTIONAL_AUC
            and block_5_auc is not None
            and float(block_5_auc) >= MIN_VALIDATION_DIRECTIONAL_AUC
            and stable_blocks >= MIN_STABLE_BLOCKS
            and sufficient_blocks == 5
        )
        record["stable_blocks"] = stable_blocks
        record["sufficient_blocks"] = sufficient_blocks
        record["candidate_for_new_forward_block"] = candidate
        record["status"] = (
            "candidate_for_new_forward_block"
            if candidate
            else "exploratory_not_selected"
        )
        records.append(record)
    return pd.DataFrame.from_records(records)


def summarize_rank_trajectory_classes(panel: pd.DataFrame) -> pd.DataFrame:
    """Describe continuation labels by frozen class pooled and per block."""

    _require_columns(
        panel,
        (
            "episode_id",
            "decision_date",
            "block",
            "multi_wave_leader",
            "feature_complete",
            "trajectory_class",
        ),
        "rank trajectory class panel",
    )
    complete = panel.loc[panel["feature_complete"].astype(bool)].copy()
    rows = []
    scopes: list[tuple[str, pd.DataFrame]] = [("pooled", complete)]
    scopes.extend(
        (f"block_{block}", complete.loc[complete["block"].eq(block)])
        for block in range(1, 6)
    )
    for scope, scoped in scopes:
        for trajectory_class, group in scoped.groupby("trajectory_class", sort=True):
            target = group["multi_wave_leader"].astype(bool)
            rows.append(
                {
                    "scope": scope,
                    "trajectory_class": str(trajectory_class),
                    "rows": int(len(group)),
                    "decision_dates": int(group["decision_date"].nunique()),
                    "positives": int(target.sum()),
                    "continuation_share_pct": float(target.mean() * 100.0),
                }
            )
    return pd.DataFrame.from_records(rows)


def build_multi_wave_rank_trajectory(
    labels: pd.DataFrame,
    memberships: pd.DataFrame,
    stock_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> RankTrajectoryResult:
    """Calculate wave-1 daily member ranks using one fixed complete denominator."""

    label_frame = _prepare_labels(labels)
    members = _prepare_memberships(memberships)
    stock_features = _prepare_stock_features(stock_bars)
    date_grid = _build_episode_date_grid(label_frame, trading_dates)
    expanded = _expand_episode_members(date_grid, members, stock_features)
    complete_members = _complete_path_members(expanded, date_grid)
    eligible, exclusions = _eligible_episodes(label_frame, complete_members)
    if eligible.empty:
        return RankTrajectoryResult(
            panel=_empty_panel(),
            daily_path=pd.DataFrame(),
            member_ledger=pd.DataFrame(),
            exclusions=exclusions,
        )
    ledger = _build_member_rank_ledger(expanded, complete_members, eligible)
    daily_path = _build_leader_daily_path(ledger)
    panel = _aggregate_rank_trajectory(eligible, daily_path)
    return RankTrajectoryResult(
        panel=panel,
        daily_path=daily_path,
        member_ledger=ledger,
        exclusions=exclusions,
    )


def _prepare_labels(labels: pd.DataFrame) -> pd.DataFrame:
    _require_columns(labels, LABEL_COLUMNS, "multi-wave identity label")
    frame = labels.copy()
    if frame["episode_id"].duplicated().any():
        raise ValueError("multi-wave label episode IDs must be unique")
    for column in (
        "anchor_date",
        "first_peak_date",
        "first_trough_date",
        "decision_date",
        "feature_cutoff_date",
    ):
        frame[column] = pd.to_datetime(frame[column], errors="raise").dt.normalize()
    if not frame["feature_cutoff_date"].eq(frame["decision_date"]).all():
        raise ValueError("feature cutoff must equal the first-rebreak decision date")
    ordered = (
        frame["anchor_date"].le(frame["first_peak_date"])
        & frame["first_peak_date"].lt(frame["first_trough_date"])
        & frame["first_trough_date"].lt(frame["decision_date"])
    )
    if not ordered.all():
        raise ValueError("wave-1 trajectory dates must be strictly ordered")
    return frame.sort_values(["decision_date", "episode_id"], kind="stable").reset_index(
        drop=True
    )


def _prepare_memberships(memberships: pd.DataFrame) -> pd.DataFrame:
    columns = ("sector_id", "vt_symbol")
    _require_columns(memberships, columns, "current concept membership")
    frame = memberships.loc[:, list(columns)].copy()
    frame["sector_id"] = frame["sector_id"].astype(str)
    frame["vt_symbol"] = frame["vt_symbol"].astype(str)
    if frame.duplicated(list(columns)).any():
        raise ValueError("current concept membership identities must be unique")
    return frame.rename(columns={"vt_symbol": "member_vt_symbol"})


def _prepare_stock_features(stock_bars: pd.DataFrame) -> pd.DataFrame:
    columns = ("vt_symbol", "trade_date", "close_price", "turnover")
    _require_columns(stock_bars, columns, "stock daily bar")
    frame = stock_bars.loc[:, list(columns)].copy()
    frame["vt_symbol"] = frame["vt_symbol"].astype(str)
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    if frame.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock daily bar identities must be unique")
    frame[["close_price", "turnover"]] = frame[
        ["close_price", "turnover"]
    ].apply(pd.to_numeric, errors="raise")
    values = frame[["close_price", "turnover"]].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("stock close and turnover must be finite")
    if frame["close_price"].le(0).any() or frame["turnover"].lt(0).any():
        raise ValueError("stock closes must be positive and turnover non-negative")
    frame = frame.sort_values(["vt_symbol", "trade_date"], kind="stable").reset_index(
        drop=True
    )
    grouped = frame.groupby("vt_symbol", sort=False)
    turnover_mean_5 = grouped["turnover"].transform(
        lambda series: series.rolling(5, min_periods=5).mean()
    )
    turnover_previous_20 = grouped["turnover"].transform(
        lambda series: series.shift(5).rolling(20, min_periods=15).mean()
    )
    frame["turnover_expansion"] = turnover_mean_5 / turnover_previous_20.replace(
        0.0, np.nan
    )
    return frame.rename(columns={"vt_symbol": "member_vt_symbol"})


def _build_episode_date_grid(
    labels: pd.DataFrame,
    trading_dates: Sequence[date],
) -> pd.DataFrame:
    calendar = pd.DatetimeIndex(pd.to_datetime(tuple(trading_dates))).normalize()
    calendar = calendar.drop_duplicates().sort_values()
    positions = {trade_date: index for index, trade_date in enumerate(calendar)}
    rows = []
    for label in labels.to_dict("records"):
        anchor = pd.Timestamp(label["anchor_date"])
        decision = pd.Timestamp(label["decision_date"])
        peak = pd.Timestamp(label["first_peak_date"])
        trough = pd.Timestamp(label["first_trough_date"])
        if any(value not in positions for value in (anchor, peak, trough, decision)):
            raise ValueError("trajectory boundary is absent from the reliable calendar")
        if positions[anchor] >= positions[decision]:
            raise ValueError("trajectory decision must follow its anchor")
        for trade_date in calendar[positions[anchor] : positions[decision] + 1]:
            rows.append(
                {
                    "episode_id": str(label["episode_id"]),
                    "sector_id": str(label["sector_id"]),
                    "leader_vt_symbol": str(label["vt_symbol"]),
                    "anchor_date": anchor,
                    "first_peak_date": peak,
                    "first_trough_date": trough,
                    "decision_date": decision,
                    "trade_date": pd.Timestamp(trade_date),
                    "trajectory_phase": _trajectory_phase(
                        pd.Timestamp(trade_date), peak, trough
                    ),
                    "rank_observation": bool(pd.Timestamp(trade_date) > anchor),
                    "peak_date_row": bool(pd.Timestamp(trade_date) == peak),
                    "trough_date_row": bool(pd.Timestamp(trade_date) == trough),
                    "decision_date_row": bool(pd.Timestamp(trade_date) == decision),
                }
            )
    return pd.DataFrame.from_records(rows)


def _trajectory_phase(
    trade_date: pd.Timestamp,
    peak_date: pd.Timestamp,
    trough_date: pd.Timestamp,
) -> str:
    if trade_date <= peak_date:
        return "impulse"
    if trade_date <= trough_date:
        return "pullback"
    return "recovery"


def _expand_episode_members(
    date_grid: pd.DataFrame,
    memberships: pd.DataFrame,
    stock_features: pd.DataFrame,
) -> pd.DataFrame:
    expanded = date_grid.merge(
        memberships,
        on="sector_id",
        how="inner",
        validate="many_to_many",
    ).merge(
        stock_features,
        on=["member_vt_symbol", "trade_date"],
        how="left",
        validate="many_to_one",
    )
    return expanded.sort_values(
        ["episode_id", "member_vt_symbol", "trade_date"], kind="stable"
    ).reset_index(drop=True)


def _complete_path_members(
    expanded: pd.DataFrame,
    date_grid: pd.DataFrame,
) -> pd.DataFrame:
    expected = date_grid.groupby("episode_id", sort=False)["trade_date"].nunique()
    counts = (
        expanded.loc[expanded["close_price"].notna()]
        .groupby(["episode_id", "member_vt_symbol"], sort=False)["trade_date"]
        .nunique()
        .rename("observed_sessions")
        .reset_index()
    )
    counts["expected_sessions"] = counts["episode_id"].map(expected)
    return counts.loc[
        counts["observed_sessions"].eq(counts["expected_sessions"]),
        ["episode_id", "member_vt_symbol"],
    ].reset_index(drop=True)


def _eligible_episodes(
    labels: pd.DataFrame,
    complete_members: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    member_count = complete_members.groupby("episode_id", sort=False)[
        "member_vt_symbol"
    ].nunique()
    complete_pairs = set(
        complete_members[["episode_id", "member_vt_symbol"]].itertuples(
            index=False, name=None
        )
    )
    retained = []
    exclusions = []
    for index, label in labels.iterrows():
        episode_id = str(label["episode_id"])
        count = int(member_count.get(episode_id, 0))
        leader_complete = (episode_id, str(label["vt_symbol"])) in complete_pairs
        if count >= 3 and leader_complete:
            retained.append(index)
            continue
        exclusions.append(
            {
                "episode_id": episode_id,
                "vt_symbol": str(label["vt_symbol"]),
                "decision_date": pd.Timestamp(label["decision_date"]),
                "complete_member_count": count,
                "exclusion_reason": (
                    "leader_path_incomplete"
                    if not leader_complete
                    else "fewer_than_three_complete_members"
                ),
            }
        )
    exclusion_columns = (
        "episode_id",
        "vt_symbol",
        "decision_date",
        "complete_member_count",
        "exclusion_reason",
    )
    return labels.loc[retained].reset_index(drop=True), pd.DataFrame.from_records(
        exclusions,
        columns=list(exclusion_columns),
    )


def _build_member_rank_ledger(
    expanded: pd.DataFrame,
    complete_members: pd.DataFrame,
    eligible: pd.DataFrame,
) -> pd.DataFrame:
    retained_ids = set(eligible["episode_id"].astype(str))
    ledger = expanded.loc[expanded["episode_id"].isin(retained_ids)].merge(
        complete_members,
        on=["episode_id", "member_vt_symbol"],
        how="inner",
        validate="many_to_one",
    )
    anchor_close = ledger.loc[ledger["trade_date"].eq(ledger["anchor_date"]), [
        "episode_id",
        "member_vt_symbol",
        "close_price",
    ]].rename(columns={"close_price": "anchor_close_price"})
    ledger = ledger.merge(
        anchor_close,
        on=["episode_id", "member_vt_symbol"],
        how="left",
        validate="many_to_one",
    )
    ledger["cumulative_gain_pct"] = (
        ledger["close_price"] / ledger["anchor_close_price"] - 1.0
    ) * 100.0
    ledger = _attach_gain_ranks(ledger)
    ledger = _attach_turnover_ranks(ledger)
    return _attach_daily_group_metrics(ledger)


def _attach_gain_ranks(ledger: pd.DataFrame) -> pd.DataFrame:
    result = ledger.sort_values(
        [
            "episode_id",
            "trade_date",
            "cumulative_gain_pct",
            "turnover_expansion",
            "member_vt_symbol",
        ],
        ascending=[True, True, False, False, True],
        na_position="last",
        kind="stable",
    ).copy()
    group_columns = ["episode_id", "trade_date"]
    result["gain_rank"] = result.groupby(group_columns, sort=False).cumcount() + 1
    result["member_count"] = result.groupby(group_columns, sort=False)[
        "member_vt_symbol"
    ].transform("nunique")
    result["rank_strength_pct"] = (
        (result["member_count"] - result["gain_rank"])
        / (result["member_count"] - 1)
        * 100.0
    )
    result["gain_top1"] = result["gain_rank"].eq(1)
    result["gain_top3"] = result["gain_rank"].le(3)
    return result


def _attach_turnover_ranks(ledger: pd.DataFrame) -> pd.DataFrame:
    identity = ["episode_id", "trade_date", "member_vt_symbol"]
    ranks = ledger.sort_values(
        [
            "episode_id",
            "trade_date",
            "turnover_expansion",
            "cumulative_gain_pct",
            "member_vt_symbol",
        ],
        ascending=[True, True, False, False, True],
        na_position="last",
        kind="stable",
    ).copy()
    ranks["turnover_rank"] = ranks.groupby(
        ["episode_id", "trade_date"], sort=False
    ).cumcount() + 1
    ranks["turnover_strength_pct"] = (
        (ranks["member_count"] - ranks["turnover_rank"])
        / (ranks["member_count"] - 1)
        * 100.0
    )
    return ledger.merge(
        ranks.loc[:, [*identity, "turnover_rank", "turnover_strength_pct"]],
        on=identity,
        how="left",
        validate="one_to_one",
    )


def _attach_daily_group_metrics(ledger: pd.DataFrame) -> pd.DataFrame:
    result = ledger.copy()
    group_columns = ["episode_id", "trade_date"]
    result["positive_gain"] = result["cumulative_gain_pct"].clip(lower=0.0)
    result["top3_positive_gain"] = result["positive_gain"].where(
        result["gain_top3"], 0.0
    )
    result["other_gain"] = result["cumulative_gain_pct"].where(
        result["member_vt_symbol"].ne(result["leader_vt_symbol"])
    )
    result["best_other_gain_pct"] = result.groupby(group_columns, sort=False)[
        "other_gain"
    ].transform("max")
    top3_mean = (
        result.loc[result["gain_top3"]]
        .groupby(group_columns, sort=False)["cumulative_gain_pct"]
        .mean()
        .rename("top3_mean_gain_pct")
        .reset_index()
    )
    result = result.merge(
        top3_mean,
        on=group_columns,
        how="left",
        validate="many_to_one",
    )
    metrics = result.groupby(group_columns, sort=False).agg(
        positive_breadth_pct=("cumulative_gain_pct", _positive_pct),
        strong_breadth_pct=("cumulative_gain_pct", _strong_pct),
        positive_gain_sum=("positive_gain", "sum"),
        top3_positive_gain_sum=("top3_positive_gain", "sum"),
    ).reset_index()
    metrics["top3_positive_gain_concentration_pct"] = np.where(
        metrics["positive_gain_sum"].gt(0),
        metrics["top3_positive_gain_sum"] / metrics["positive_gain_sum"] * 100.0,
        0.0,
    )
    return result.merge(
        metrics.loc[
            :,
            [
                *group_columns,
                "positive_breadth_pct",
                "strong_breadth_pct",
                "top3_positive_gain_concentration_pct",
            ],
        ],
        on=group_columns,
        how="left",
        validate="many_to_one",
    ).sort_values(
        ["episode_id", "trade_date", "gain_rank"], kind="stable"
    ).reset_index(drop=True)


def _positive_pct(values: pd.Series) -> float:
    return float(values.gt(0.0).mean() * 100.0)


def _strong_pct(values: pd.Series) -> float:
    return float(values.ge(5.0).mean() * 100.0)


def _build_leader_daily_path(ledger: pd.DataFrame) -> pd.DataFrame:
    return ledger.loc[
        ledger["member_vt_symbol"].eq(ledger["leader_vt_symbol"])
    ].sort_values(["episode_id", "trade_date"], kind="stable").reset_index(drop=True)


def _aggregate_rank_trajectory(
    labels: pd.DataFrame,
    daily_path: pd.DataFrame,
) -> pd.DataFrame:
    records = []
    for episode_id, path in daily_path.groupby("episode_id", sort=False):
        ordered = path.sort_values("trade_date", kind="stable")
        observed = ordered.loc[ordered["rank_observation"]]
        recovery = observed.loc[observed["trajectory_phase"].eq("recovery")]
        peak = _single_path_row(ordered, "peak_date_row")
        trough = _single_path_row(ordered, "trough_date_row")
        decision = _single_path_row(ordered, "decision_date_row")
        records.append(
            {
                "episode_id": str(episode_id),
                "trajectory_member_count": int(decision["member_count"]),
                "trajectory_observation_sessions": int(len(observed)),
                "leader_path_top1_share_pct": _boolean_pct(observed["gain_top1"]),
                "leader_path_top3_share_pct": _boolean_pct(observed["gain_top3"]),
                "leader_recovery_top3_share_pct": _boolean_pct(recovery["gain_top3"]),
                "leader_peak_strength_pct": float(peak["rank_strength_pct"]),
                "leader_trough_strength_pct": float(trough["rank_strength_pct"]),
                "leader_decision_strength_pct": float(decision["rank_strength_pct"]),
                "leader_worst_strength_pct": float(observed["rank_strength_pct"].min()),
                "leader_strength_std_pct": float(
                    observed["rank_strength_pct"].std(ddof=0)
                ),
                "leader_peak_to_decision_strength_change_pct_points": float(
                    decision["rank_strength_pct"] - peak["rank_strength_pct"]
                ),
                "leader_trough_to_decision_strength_change_pct_points": float(
                    decision["rank_strength_pct"] - trough["rank_strength_pct"]
                ),
                "leader_top3_streak_to_decision_sessions": float(
                    _trailing_true_count(observed["gain_top3"])
                ),
                "leader_decision_gap_to_best_other_pct": float(
                    decision["cumulative_gain_pct"] - decision["best_other_gain_pct"]
                ),
                "leader_decision_gap_to_top3_mean_pct": float(
                    decision["cumulative_gain_pct"] - decision["top3_mean_gain_pct"]
                ),
                "leader_decision_turnover_strength_pct": float(
                    decision["turnover_strength_pct"]
                ),
                "leader_path_median_turnover_strength_pct": float(
                    observed["turnover_strength_pct"].median()
                ),
                "positive_breadth_trough_to_decision_change_pct_points": float(
                    decision["positive_breadth_pct"] - trough["positive_breadth_pct"]
                ),
                "strong_breadth_trough_to_decision_change_pct_points": float(
                    decision["strong_breadth_pct"] - trough["strong_breadth_pct"]
                ),
                "top3_concentration_trough_to_decision_change_pct_points": float(
                    decision["top3_positive_gain_concentration_pct"]
                    - trough["top3_positive_gain_concentration_pct"]
                ),
            }
        )
    features = pd.DataFrame.from_records(records)
    panel = labels.merge(features, on="episode_id", how="inner", validate="one_to_one")
    numeric = panel.loc[:, list(RANK_TRAJECTORY_FEATURES)].apply(
        pd.to_numeric, errors="coerce"
    )
    panel.loc[:, list(RANK_TRAJECTORY_FEATURES)] = numeric
    finite = np.isfinite(numeric.to_numpy(dtype=float))
    panel["feature_complete"] = finite.all(axis=1)
    panel["feature_exclusion_reason"] = [
        None
        if complete
        else "missing:" + ",".join(
            feature
            for feature, available in zip(RANK_TRAJECTORY_FEATURES, row, strict=True)
            if not available
        )
        for complete, row in zip(panel["feature_complete"], finite, strict=True)
    ]
    panel["feature_cutoff_date"] = panel["decision_date"]
    return panel.sort_values(["decision_date", "episode_id"], kind="stable").reset_index(
        drop=True
    )


def _single_path_row(path: pd.DataFrame, marker: str) -> pd.Series:
    matches = path.loc[path[marker].astype(bool)]
    if len(matches) != 1:
        raise ValueError(f"trajectory path requires one {marker}")
    return matches.iloc[0]


def _trailing_true_count(values: pd.Series) -> int:
    count = 0
    for value in reversed(values.astype(bool).tolist()):
        if not value:
            break
        count += 1
    return count


def _boolean_pct(values: pd.Series) -> float:
    return float(values.astype(bool).mean() * 100.0) if len(values) else 0.0


def _empty_panel() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            *LABEL_COLUMNS,
            *RANK_TRAJECTORY_FEATURES,
            "feature_complete",
            "feature_exclusion_reason",
        ]
    )


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
        raise ValueError("trajectory AUC values must be finite")
    return float(roc_auc_score(target, values))


def _require_diagnostic_panel(panel: pd.DataFrame) -> None:
    _require_columns(
        panel,
        (
            "episode_id",
            "decision_date",
            "block",
            "multi_wave_leader",
            "feature_complete",
            *RANK_TRAJECTORY_FEATURES,
        ),
        "rank trajectory diagnostic panel",
    )
    if panel["episode_id"].duplicated().any():
        raise ValueError("trajectory diagnostic episode IDs must be unique")
    blocks = set(pd.to_numeric(panel["block"], errors="raise").unique())
    if not blocks.issubset({1, 2, 3, 4, 5}):
        raise ValueError("trajectory diagnostic blocks must be between one and five")


def _require_columns(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    label: str,
) -> None:
    missing = sorted(set(columns) - set(frame))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")


def _load_new_information_coverage(
    label_dates: tuple[date, ...],
) -> dict[str, Any]:
    from sqlalchemy import func, select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    label_date_strings = tuple(value.isoformat() for value in label_dates)
    datasets = (
        (
            "stock_fund_flow",
            schema.stock_fund_flows,
            schema.stock_fund_flows.c.trade_date,
            label_date_strings,
        ),
        (
            "sector_fund_flow",
            schema.sector_fund_flows,
            schema.sector_fund_flows.c.trade_date,
            label_date_strings,
        ),
        (
            "membership_snapshot",
            schema.stock_sector_membership_snapshots,
            schema.stock_sector_membership_snapshots.c.snapshot_date,
            label_dates,
        ),
        (
            "sector_fund_flow_snapshot",
            schema.sector_fund_flow_snapshots,
            schema.sector_fund_flow_snapshots.c.trade_date,
            label_dates,
        ),
    )
    coverage: dict[str, Any] = {
        "free_historical_flow_probe": "recent_only_and_rate_limited_not_imported",
        "flow_rows_used_as_features": 0,
        "membership_snapshot_rows_used_as_features": 0,
    }
    with get_engine().connect() as connection:
        for prefix, table, date_column, overlap_values in datasets:
            row = connection.execute(
                select(
                    func.count(),
                    func.count(func.distinct(date_column)),
                    func.min(date_column),
                    func.max(date_column),
                ).select_from(table)
            ).one()
            overlap_dates = int(
                connection.execute(
                    select(func.count(func.distinct(date_column)))
                    .select_from(table)
                    .where(date_column.in_(overlap_values))
                ).scalar_one()
            )
            coverage.update(
                {
                    f"{prefix}_rows": int(row[0] or 0),
                    f"{prefix}_dates": int(row[1] or 0),
                    f"{prefix}_start": _date_text(row[2]),
                    f"{prefix}_end": _date_text(row[3]),
                    f"{prefix}_label_overlap_dates": overlap_dates,
                }
            )
    return coverage


def _representative_trajectory_cases(
    result: RankTrajectoryResult,
) -> dict[str, list[dict[str, Any]]]:
    if result.panel.empty or "trajectory_class" not in result.panel:
        return {
            "persistent_continued": [],
            "persistent_terminal": [],
            "lost_leadership": [],
        }
    complete = result.panel.loc[result.panel["feature_complete"].astype(bool)]
    persistent = complete.loc[
        complete["trajectory_class"].eq("persistent_leader")
    ]
    return {
        "persistent_continued": _case_records(
            persistent.loc[persistent["multi_wave_leader"].astype(bool)]
        ),
        "persistent_terminal": _case_records(
            persistent.loc[~persistent["multi_wave_leader"].astype(bool)]
        ),
        "lost_leadership": _case_records(
            complete.loc[complete["trajectory_class"].eq("lost_leadership")]
        ),
    }


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
        "multi_wave_leader",
        "trajectory_class",
        "trajectory_member_count",
        "trajectory_observation_sessions",
        "leader_path_top1_share_pct",
        "leader_path_top3_share_pct",
        "leader_recovery_top3_share_pct",
        "leader_decision_strength_pct",
        "leader_top3_streak_to_decision_sessions",
        "leader_decision_gap_to_best_other_pct",
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


def _representative_case_lines(report: Mapping[str, Any]) -> list[str]:
    cases = _mapping(report.get("representative_cases"))
    lines = [
        "",
        "## 个股轨迹例子",
        "",
        "| 类型 | 股票 | 概念 | 决策日 | 全程 Top3 | 恢复 Top3 | 决策强度 | 连续 Top3 | 领先第二名 |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    groups = (
        ("持续/续浪", "persistent_continued"),
        ("持续/终止", "persistent_terminal"),
        ("丢失地位", "lost_leadership"),
    )
    for label, key in groups:
        for row in _sequence(cases.get(key)):
            item = _mapping(row)
            lines.append(
                f"| {label} | {item.get('stock_name')} `{item.get('vt_symbol')}` | "
                f"{item.get('concept_name')} | {item.get('decision_date')} | "
                f"{_pct(item.get('leader_path_top3_share_pct'))} | "
                f"{_pct(item.get('leader_recovery_top3_share_pct'))} | "
                f"{_pct(item.get('leader_decision_strength_pct'))} | "
                f"{_number(item.get('leader_top3_streak_to_decision_sessions'))} | "
                f"{_pct(item.get('leader_decision_gap_to_best_other_pct'))} |"
            )
    return lines


def _coverage_line(
    label: str,
    prefix: str,
    coverage: Mapping[str, Any],
) -> str:
    start = coverage.get(f"{prefix}_start")
    end = coverage.get(f"{prefix}_end")
    return (
        f"| {label} | {coverage.get(f'{prefix}_dates', 0)} | {start}..{end} | "
        f"{coverage.get(f'{prefix}_label_overlap_dates', 0)} | `False` |"
    )


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _date_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    try:
        return pd.Timestamp(value).date().isoformat()
    except (TypeError, ValueError):
        return str(value)


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
