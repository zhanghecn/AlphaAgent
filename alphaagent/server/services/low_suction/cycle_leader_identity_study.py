"""Return-independent identity comparison for observed cycle leader candidates."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .leader_identity import (
    LeaderIdentityMode,
    choose_stable_leader_identity,
    rank_prevalidated_leader_identities,
)


STRONG_EVENT_THRESHOLD_PCT = 5.0
STRONG_EVENT_FUTURE_SESSIONS = 5
NO_STRONG_EVENT_SCORE = STRONG_EVENT_FUTURE_SESSIONS + 1
MIN_MODE_POOL = 3
DEVELOPMENT_BLOCKS = frozenset({1, 2, 3})
VALIDATION_BLOCKS = frozenset({4, 5})
MIN_BLOCK_RETENTION_OBSERVATIONS = 100
MIN_BLOCK_STRONG_EVENT_OBSERVATIONS = 50
BASELINE_IDENTITY_MODE = LeaderIdentityMode.MARKET_RECOGNITION.value
STUDY_EVIDENCE_LEVEL = "event_candidate_cycle_leader_identity_comparison"

DYNAMIC_IDENTITY_COLUMNS = (
    "cycle_id",
    "sector_id",
    "entry_date",
    "context_date",
    "feature_cutoff_date",
    "leader_spell_id",
    "recognition_source_date",
    "vt_symbol",
    "stock_name",
    "identity_feature_status",
    "identity_cycle_relative_return",
    "identity_strong_day_count_cycle",
    "identity_sessions_since_strong",
    "identity_turnover_median_20d",
    "identity_capacity_passed",
)
PROHIBITED_RANK_COLUMNS = frozenset(
    {
        "net_return_pct",
        "gross_return_pct",
        "double_cost_net_return_pct",
        "entry_price",
        "exit_price",
        "mfe_pct",
        "mae_pct",
    }
)
PROHIBITED_RANK_PREFIXES = (
    "realized_",
    "future_",
    "outcome_",
    "exit_",
    "d1_",
    "d3_",
    "d5_",
)


def build_cycle_identity_mode_ranks(
    dynamic_candidates: pd.DataFrame,
) -> pd.DataFrame:
    """Rank the same D-1 event-candidate pool under all frozen identity modes."""

    _reject_rank_outcomes(dynamic_candidates)
    _require_columns(dynamic_candidates, DYNAMIC_IDENTITY_COLUMNS, "dynamic identity")
    source = dynamic_candidates.loc[:, list(DYNAMIC_IDENTITY_COLUMNS)].copy()
    for column in (
        "entry_date",
        "context_date",
        "feature_cutoff_date",
        "recognition_source_date",
    ):
        source[column] = pd.to_datetime(source[column], errors="raise").dt.normalize()
    if source.duplicated(["cycle_id", "entry_date", "vt_symbol"]).any():
        raise ValueError("dynamic identity candidates must be unique")
    cycle_counts = source.groupby(["entry_date", "sector_id"], sort=False)[
        "cycle_id"
    ].nunique()
    if cycle_counts.gt(1).any():
        raise ValueError("one sector session cannot contain multiple active cycles")
    if source["feature_cutoff_date"].ge(source["entry_date"]).any():
        raise ValueError("identity features must be frozen before entry date")
    if source["recognition_source_date"].gt(source["context_date"]).any():
        raise ValueError("candidate recognition must be known by D-1")

    features = source.rename(
        columns={
            "identity_cycle_relative_return": "cycle_relative_return",
            "identity_strong_day_count_cycle": "strong_day_count_cycle",
            "identity_sessions_since_strong": "sessions_since_strong",
            "identity_turnover_median_20d": "turnover_median_20d",
            "identity_capacity_passed": "capacity_passed",
        }
    )
    features["excluded_reason"] = np.where(
        features["identity_feature_status"].eq("complete"),
        None,
        "incomplete_identity_features",
    )
    ranks = [
        rank_prevalidated_leader_identities(
            features,
            mode=mode,
            session_column="entry_date",
        )
        for mode in LeaderIdentityMode
    ]
    result = pd.concat(ranks, ignore_index=True)
    group_columns = ["identity_mode", "cycle_id", "entry_date"]
    result["mode_pool_size"] = result.groupby(group_columns, sort=False)[
        "rank_eligible"
    ].transform("sum").astype(int)
    result["mode_top3_qualified"] = result["mode_pool_size"].ge(MIN_MODE_POOL)
    result["mode_top1"] = (
        result["mode_top3_qualified"] & result["rank"].eq(1).fillna(False)
    )
    result["mode_top3"] = (
        result["mode_top3_qualified"] & result["rank"].le(3).fillna(False)
    )
    return result.sort_values(
        ["entry_date", "sector_id", "identity_mode", "rank", "vt_symbol"],
        na_position="last",
        kind="stable",
    ).reset_index(drop=True)


def build_cycle_identity_labels(
    ranks: pd.DataFrame,
    stock_bars: pd.DataFrame,
    realized_leaders: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> pd.DataFrame:
    """Attach return-independent future identity labels after D-1 ranking."""

    _require_columns(
        ranks,
        (
            "cycle_id",
            "entry_date",
            "identity_mode",
            "vt_symbol",
            "mode_top3",
        ),
        "cycle identity rank",
    )
    _require_columns(stock_bars, ("vt_symbol", "trade_date", "close_price"), "stock bar")
    _require_columns(
        realized_leaders,
        ("cycle_id", "vt_symbol", "realized_market_rank", "realized_return_rank"),
        "realized leader",
    )
    calendar = _prepare_calendar(trading_dates)
    positions = {trade_date: index for index, trade_date in enumerate(calendar)}
    result = ranks.copy()
    result["entry_date"] = pd.to_datetime(result["entry_date"], errors="raise").dt.date
    if result.duplicated(
        ["identity_mode", "cycle_id", "entry_date", "vt_symbol"]
    ).any():
        raise ValueError("cycle identity rank rows must be unique")

    top3_groups = {
        (str(mode), str(cycle_id), entry_date): set(group["vt_symbol"].astype(str))
        for (mode, cycle_id, entry_date), group in result.loc[
            result["mode_top3"].astype(bool)
        ].groupby(["identity_mode", "cycle_id", "entry_date"], sort=False)
    }
    changes = _daily_change_lookup(stock_bars)
    retention: list[float] = []
    strong_lead: list[float] = []
    for row in result.itertuples(index=False):
        if not bool(row.mode_top3):
            retention.append(np.nan)
            strong_lead.append(np.nan)
            continue
        position = positions.get(row.entry_date)
        next_date = (
            calendar[position + 1]
            if position is not None and position + 1 < len(calendar)
            else None
        )
        next_top3 = top3_groups.get(
            (str(row.identity_mode), str(row.cycle_id), next_date)
        )
        retention.append(
            np.nan if next_top3 is None else float(str(row.vt_symbol) in next_top3)
        )
        strong_lead.append(
            _strong_event_lead(
                str(row.vt_symbol),
                position,
                calendar=calendar,
                changes=changes,
            )
        )
    result["retained_top3_next_session"] = retention
    result["strong_event_lead_sessions"] = strong_lead

    realized = realized_leaders.loc[
        :,
        ["cycle_id", "vt_symbol", "realized_market_rank", "realized_return_rank"],
    ].copy()
    if realized.duplicated(["cycle_id", "vt_symbol"]).any():
        raise ValueError("realized leader rows must be unique")
    result = result.merge(
        realized,
        on=["cycle_id", "vt_symbol"],
        how="left",
        validate="many_to_one",
    )
    result["realized_market_top1"] = result["realized_market_rank"].eq(1)
    result["realized_return_top1"] = result["realized_return_rank"].eq(1)
    return result.sort_values(
        ["entry_date", "sector_id", "identity_mode", "rank", "vt_symbol"],
        na_position="last",
        kind="stable",
    ).reset_index(drop=True)


def build_cycle_identity_metrics(labels: pd.DataFrame) -> pd.DataFrame:
    """Summarize retention, strong-event lead, capacity and oracle coverage."""

    _require_columns(
        labels,
        (
            "cycle_id",
            "entry_date",
            "identity_mode",
            "mode_top3",
            "retained_top3_next_session",
            "strong_event_lead_sessions",
            "capacity_passed",
            "realized_market_top1",
            "realized_return_top1",
            "block",
        ),
        "cycle identity label",
    )
    frame = labels.copy()
    frame["entry_date"] = pd.to_datetime(frame["entry_date"], errors="raise").dt.date
    frame["block"] = pd.to_numeric(frame["block"], errors="raise").astype(int)
    if not frame["block"].isin(range(1, 6)).all():
        raise ValueError("cycle identity blocks must be 1..5")

    rows = []
    for mode in LeaderIdentityMode:
        mode_rows = frame.loc[frame["identity_mode"].eq(mode.value)]
        for segment, blocks in _metric_segments():
            rows.append(
                {
                    "identity_mode": mode.value,
                    "segment": segment,
                    **_summarize_identity_rows(
                        mode_rows.loc[mode_rows["block"].isin(blocks)]
                    ),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["identity_mode", "segment"], kind="stable"
    ).reset_index(drop=True)


def evaluate_cycle_identity_modes(metrics: pd.DataFrame) -> dict[str, Any]:
    """Select a stable proxy mode without reading low-suction returns."""

    _require_columns(
        metrics,
        (
            "identity_mode",
            "segment",
            "eligible_retention_observations",
            "next_session_top3_retention",
            "strong_event_lead_observations",
            "strong_event_lead_sessions",
            "capacity_pass_rate",
        ),
        "cycle identity metric",
    )
    fold_winners: list[str | None] = []
    fold_rows: list[dict[str, Any]] = []
    for block in range(1, 6):
        block_metrics = metrics.loc[metrics["segment"].eq(f"block_{block}")]
        by_mode = {
            str(row.identity_mode): row
            for row in block_metrics.itertuples(index=False)
        }
        eligible = (
            set(by_mode) == {mode.value for mode in LeaderIdentityMode}
            and all(_block_sample_sufficient(row) for row in by_mode.values())
        )
        if not eligible:
            winner = None
            status = "insufficient_sample"
        else:
            winner = min(by_mode.values(), key=_identity_winner_key).identity_mode
            winner = str(winner)
            status = "winner_selected"
        fold_winners.append(winner)
        fold_rows.append(
            {"block": block, "identity_mode": winner, "status": status}
        )

    selected = choose_stable_leader_identity(fold_winners, minimum_wins=3)
    selected_mode = selected.value if selected is not None else None
    counts = Counter(winner for winner in fold_winners if winner is not None)
    development_better: bool | None = None
    validation_better: bool | None = None
    comparison: dict[str, Any] | None = None
    if selected_mode is not None:
        development_better, development_comparison = _compare_mode_to_baseline(
            metrics,
            selected_mode=selected_mode,
            segment="development",
        )
        validation_better, validation_comparison = _compare_mode_to_baseline(
            metrics,
            selected_mode=selected_mode,
            segment="validation",
        )
        comparison = {
            "development": development_comparison,
            "validation": validation_comparison,
        }

    improved = bool(
        selected_mode is not None
        and selected_mode != BASELINE_IDENTITY_MODE
        and development_better
        and validation_better
    )
    if selected_mode is None:
        conclusion = "no_stable_proxy_identity"
    elif selected_mode == BASELINE_IDENTITY_MODE:
        conclusion = "market_recognition_proxy_confirmed"
    elif improved:
        conclusion = "improved_proxy_identity_found"
    else:
        conclusion = "stable_proxy_identity_not_consistently_better"
    return {
        "overall_conclusion": conclusion,
        "baseline_identity_mode": BASELINE_IDENTITY_MODE,
        "proxy_selected_mode": selected_mode,
        "improved_proxy_mode": selected_mode if improved else None,
        "formal_selected_mode": None,
        "fold_winners": fold_rows,
        "fold_win_counts": dict(sorted(counts.items())),
        "development_better_than_baseline": development_better,
        "validation_better_than_baseline": validation_better,
        "candidate_vs_baseline": comparison,
        "pullback_retest_allowed": improved,
        "low_suction_outcomes_read": False,
    }


def build_selected_mode_dynamic_identity(
    ranks: pd.DataFrame,
    selected_mode: str,
) -> pd.DataFrame:
    """Adapt one improved mode to the frozen pullback identity columns."""

    mode = LeaderIdentityMode(selected_mode).value
    _require_columns(
        ranks,
        (
            "cycle_id",
            "entry_date",
            "vt_symbol",
            "identity_mode",
            "rank",
            "mode_pool_size",
            "mode_top3_qualified",
            "mode_top1",
            "mode_top3",
        ),
        "cycle identity rank",
    )
    selected = ranks.loc[ranks["identity_mode"].eq(mode)].copy()
    if selected.empty:
        raise ValueError(f"selected identity mode has no rows: {mode}")
    if selected.duplicated(["cycle_id", "entry_date", "vt_symbol"]).any():
        raise ValueError("selected mode rank identities must be unique")
    selected = selected.rename(
        columns={
            "rank": "dynamic_rank",
            "mode_pool_size": "dynamic_pool_size",
            "mode_top3_qualified": "dynamic_top3_qualified",
            "mode_top1": "dynamic_top1",
            "mode_top3": "dynamic_top3",
        }
    )
    return selected.sort_values(
        ["entry_date", "sector_id", "dynamic_rank", "vt_symbol"],
        na_position="last",
        kind="stable",
    ).reset_index(drop=True)


def execute_identity_gated_pullback(
    evaluation: Mapping[str, Any],
    runner: Callable[[str], Mapping[str, Any]],
) -> dict[str, Any]:
    """Call the pullback runner only after the frozen identity improvement gate."""

    if not bool(evaluation.get("pullback_retest_allowed")):
        return {
            "status": "not_run_identity_gate_failed",
            "selected_mode": None,
            "low_suction_outcomes_read": False,
            "report": None,
        }
    selected_mode = str(evaluation.get("improved_proxy_mode") or "").strip()
    if not selected_mode:
        raise ValueError("an improved proxy mode is required to run pullback outcomes")
    report = dict(runner(selected_mode))
    return {
        "status": "completed_reused_history_diagnostic",
        "selected_mode": selected_mode,
        "low_suction_outcomes_read": True,
        "report": report,
    }


def load_cycle_leader_identity_study_data() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    """Build identity evidence before conditionally loading pullback outcomes."""

    from .concept_cycles import build_cycle_candidates, load_cycle_research_inputs
    from .cycle_leader_study import (
        build_dynamic_cycle_leaders,
        build_observed_cycle_periods,
        build_realized_cycle_leaders,
    )
    from .event_neutral_days import load_event_neutral_inputs
    from .event_recognition_falsification import (
        chronological_event_blocks,
        load_event_falsification_inputs,
    )
    from .individual_leader_study import build_spell_identities
    from .research_protocol import fingerprint_frame

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
    ranks = build_cycle_identity_mode_ranks(dynamic)
    labels = build_cycle_identity_labels(
        ranks,
        neutral_inputs.stock_bars,
        realized,
        trading_dates=neutral_inputs.trading_dates,
    )
    blocks = chronological_event_blocks(
        tuple(sorted(pd.to_datetime(candidates["entry_date"]).dt.date.unique())),
        block_count=5,
    ).rename(columns={"source_date": "entry_date"})
    labels = labels.merge(
        blocks,
        on="entry_date",
        how="left",
        validate="many_to_one",
    )
    metrics = build_cycle_identity_metrics(labels)
    evaluation = evaluate_cycle_identity_modes(metrics)

    def pullback_runner(selected_mode: str) -> Mapping[str, Any]:
        return _run_selected_identity_pullback(
            ranks,
            candidates,
            realized,
            neutral_inputs.stock_bars,
            trading_dates=neutral_inputs.trading_dates,
            blocks=blocks,
            selected_mode=selected_mode,
        )

    pullback = execute_identity_gated_pullback(evaluation, pullback_runner)
    metadata = {
        "coverage": _identity_coverage(
            periods=periods,
            dynamic=dynamic,
            labels=labels,
            pullback=pullback,
        ),
        "input_fingerprints": {
            **dict(event_inputs.input_fingerprints),
            **dict(neutral_inputs.input_fingerprints),
            **{
                name: value.as_dict()
                for name, value in cycle_inputs.component_fingerprints
            },
            "cycle_identity_dynamic_features": fingerprint_frame(
                dynamic,
                identity_columns=("cycle_id", "entry_date", "vt_symbol"),
            ).as_dict(),
            "cycle_identity_mode_ranks": fingerprint_frame(
                ranks,
                identity_columns=(
                    "identity_mode",
                    "cycle_id",
                    "entry_date",
                    "vt_symbol",
                ),
            ).as_dict(),
            "cycle_identity_labels": fingerprint_frame(
                labels,
                identity_columns=(
                    "identity_mode",
                    "cycle_id",
                    "entry_date",
                    "vt_symbol",
                ),
            ).as_dict(),
        },
        "discovery_start": event_inputs.discovery_start,
        "discovery_end": event_inputs.discovery_end,
    }
    return labels, metrics, evaluation, pullback, metadata


def run_cycle_leader_identity_study() -> dict[str, Any]:
    """Run the frozen cycle-leader identity comparison study."""

    return build_cycle_leader_identity_report(
        *load_cycle_leader_identity_study_data()
    )


def build_cycle_leader_identity_report(
    labels: pd.DataFrame,
    metrics: pd.DataFrame,
    evaluation: Mapping[str, Any],
    pullback: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Build exhaustive proxy identity evidence with formal claims closed."""

    coverage = dict(metadata.get("coverage", {}))
    coverage.setdefault("identity_rows", int(len(labels)))
    return {
        "evidence_level": STUDY_EVIDENCE_LEVEL,
        "candidate_pool": "event_candidate_pool_proxy",
        "overall_conclusion": str(evaluation["overall_conclusion"]),
        "proxy_selected_mode": evaluation.get("proxy_selected_mode"),
        "formal_selected_mode": None,
        "formal_metrics": None,
        "strict_historical_top3_claim": False,
        "low_suction_outcomes_read": bool(
            pullback.get("low_suction_outcomes_read")
        ),
        "outer_holdout_price_values_read": False,
        "late_segment_is_unseen_validation": False,
        "frozen_contract": {
            "feature_cutoff": "D-1 completed daily bars",
            "identity_modes": [mode.value for mode in LeaderIdentityMode],
            "strong_event": "first >=5% daily return on D..D+5; 6=no event",
            "selection": "retention desc, strong lead asc, capacity desc; unique 3/5 winner",
            "improvement_gate": (
                "non-baseline winner must beat market recognition in blocks 1-3 "
                "and blocks 4-5"
            ),
            "pullback_retest": "only after identity improvement; frozen five moments",
        },
        "coverage": coverage,
        "identity_evaluation": _json_safe(dict(evaluation)),
        "identity_metrics": _records(metrics),
        "mode_top3_overlap": build_cycle_identity_mode_overlap(labels),
        "identity_ledger": _records(labels),
        "pullback_retest": _json_safe(dict(pullback)),
        "input_fingerprints": _json_safe(
            dict(metadata.get("input_fingerprints", {}))
        ),
        "discovery_start": _json_safe(metadata.get("discovery_start")),
        "discovery_end": _json_safe(metadata.get("discovery_end")),
        "limitations": [
            "historical complete concept membership and strict security state are unavailable",
            "event-recognized candidates are not a complete concept-member denominator",
            "completed-period leader coverage is descriptive and cannot select an identity mode",
            "blocks 4-5 were visible in prior studies and are not an untouched outer holdout",
            "a proxy-selected mode cannot become a formal or production Top3 identity",
        ],
    }


def build_cycle_identity_mode_overlap(
    labels: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Return pairwise Top3 Jaccard overlap across shared qualified sessions."""

    _require_columns(
        labels,
        ("identity_mode", "cycle_id", "entry_date", "vt_symbol", "mode_top3"),
        "cycle identity overlap",
    )
    top3 = labels.loc[labels["mode_top3"].astype(bool)].copy()
    modes = tuple(mode.value for mode in LeaderIdentityMode)
    rows = []
    for left_index, left_mode in enumerate(modes):
        for right_mode in modes[left_index + 1 :]:
            left = _identity_top3_groups(top3, left_mode)
            right = _identity_top3_groups(top3, right_mode)
            shared = sorted(set(left) & set(right), key=str)
            overlaps = [
                len(left[key] & right[key]) / len(left[key] | right[key])
                for key in shared
            ]
            rows.append(
                {
                    "left_mode": left_mode,
                    "right_mode": right_mode,
                    "shared_concept_sessions": len(shared),
                    "mean_top3_jaccard": (
                        float(np.mean(overlaps)) if overlaps else None
                    ),
                }
            )
    return rows


def render_cycle_leader_identity_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def render_cycle_leader_identity_markdown(report: Mapping[str, Any]) -> str:
    coverage = report["coverage"]
    evaluation = report["identity_evaluation"]
    lines = [
        "# AlphaAgent D-1 周期龙头身份比较",
        "",
        f"结论：`{report['overall_conclusion']}`  ",
        "候选池：`event_candidate_pool_proxy`，不是历史完整概念成员  ",
        f"代理选择：`{evaluation.get('proxy_selected_mode') or 'null'}`  ",
        "正式选择：`null`  ",
        f"周期/动态候选行/身份账本行：`{coverage.get('observed_periods', 0)}/"
        f"{coverage.get('dynamic_candidate_rows', 0)}/"
        f"{coverage.get('identity_rows', 0)}`  ",
        f"是否读取低吸收益：`{str(report['low_suction_outcomes_read']).lower()}`",
        "",
        "## 身份指标",
        "",
        "| Mode | Segment | Sessions | Top3 | Ret N | Retention | Strong N | Lead | Hit <=5 | Capacity | Market Top1 | Return Top1 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["identity_metrics"]:
        lines.append(
            f"| `{row['identity_mode']}` | `{row['segment']}` | "
            f"{row['qualified_concept_sessions']} | {row['top3_observations']} | "
            f"{row['eligible_retention_observations']} | "
            f"{_ratio(row['next_session_top3_retention'])} | "
            f"{row['strong_event_lead_observations']} | "
            f"{_number(row['strong_event_lead_sessions'])} | "
            f"{_ratio(row['strong_event_within_five_rate'])} | "
            f"{_ratio(row['capacity_pass_rate'])} | "
            f"{_ratio(row['realized_market_top1_coverage'])} | "
            f"{_ratio(row['realized_return_top1_coverage'])} |"
        )
    lines.extend(
        [
            "",
            "## 五块身份赢家",
            "",
            "| Block | Winner | Status |",
            "| ---: | --- | --- |",
        ]
    )
    for row in evaluation["fold_winners"]:
        lines.append(
            f"| {row['block']} | `{row.get('identity_mode') or 'null'}` | "
            f"`{row['status']}` |"
        )
    lines.extend(
        [
            "",
            "## 模式重合",
            "",
            "| Left | Right | Shared sessions | Mean Jaccard |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for row in report["mode_top3_overlap"]:
        lines.append(
            f"| `{row['left_mode']}` | `{row['right_mode']}` | "
            f"{row['shared_concept_sessions']} | {_ratio(row['mean_top3_jaccard'])} |"
        )
    pullback = report["pullback_retest"]
    lines.extend(
        [
            "",
            "## 回调复验门",
            "",
            f"状态：`{pullback['status']}`  ",
            f"身份：`{pullback.get('selected_mode') or 'null'}`  ",
            f"读取低吸收益：`{str(pullback['low_suction_outcomes_read']).lower()}`",
            "",
            "## 边界",
            "",
            "本报告只比较事件候选池内的 D-1 身份，不是严格全成员 Top3。事后阶段龙头只用于覆盖诊断；代理模式不能成为正式策略身份。",
            "",
        ]
    )
    return "\n".join(lines)


def _run_selected_identity_pullback(
    ranks: pd.DataFrame,
    candidates: pd.DataFrame,
    realized: pd.DataFrame,
    stock_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
    blocks: pd.DataFrame,
    selected_mode: str,
) -> dict[str, Any]:
    from .event_neutral_minutes import load_complete_event_neutral_5m_bars
    from .leader_pullback_moment_study import (
        attach_cycle_leader_identities,
        build_leader_moment_cohort_trades,
        build_leader_moment_metrics,
        build_leader_pullback_moments,
        evaluate_causal_leader_moments,
        label_leader_pullback_moments,
    )

    dynamic = build_selected_mode_dynamic_identity(ranks, selected_mode)
    identified = attach_cycle_leader_identities(candidates, dynamic, realized)
    minute_bars = load_complete_event_neutral_5m_bars(candidates)
    moments = build_leader_pullback_moments(identified, minute_bars)
    moments["entry_date"] = pd.to_datetime(moments["entry_date"]).dt.date
    moments = moments.merge(
        blocks,
        on="entry_date",
        how="left",
        validate="many_to_one",
    )
    trades = label_leader_pullback_moments(
        moments,
        stock_bars,
        trading_dates=trading_dates,
    )
    cohorts = build_leader_moment_cohort_trades(trades)
    metrics = build_leader_moment_metrics(cohorts)
    evaluation = evaluate_causal_leader_moments(metrics)
    causal = metrics.loc[
        metrics["table_id"].eq("causal_rule_x_identity")
        & metrics["segment"].isin(("all", "development", "validation"))
    ]
    return {
        "identity_mode": selected_mode,
        "coverage": {
            "minute_rows": int(len(minute_bars)),
            "pullback_moments": int(len(moments)),
            "closed_trades": int(trades["normal_status"].eq("closed").sum()),
        },
        "causal_evaluation": _json_safe(evaluation),
        "causal_metrics": _records(causal),
        "formal_metrics": None,
        "late_segment_is_unseen_validation": False,
    }


def _identity_coverage(
    *,
    periods: pd.DataFrame,
    dynamic: pd.DataFrame,
    labels: pd.DataFrame,
    pullback: Mapping[str, Any],
) -> dict[str, Any]:
    qualified = labels.loc[labels["mode_top3"].astype(bool)]
    qualified_by_mode = {
        mode.value: int(
            qualified.loc[qualified["identity_mode"].eq(mode.value), [
                "cycle_id",
                "entry_date",
            ]]
            .drop_duplicates()
            .shape[0]
        )
        for mode in LeaderIdentityMode
    }
    return {
        "observed_periods": int(len(periods)),
        "completed_periods": int(periods["period_status"].eq("completed").sum()),
        "censored_periods": int(
            periods["period_status"].eq("censored_at_discovery_end").sum()
        ),
        "dynamic_candidate_rows": int(len(dynamic)),
        "complete_identity_feature_rows": int(
            dynamic["identity_feature_status"].eq("complete").sum()
        ),
        "identity_rows": int(len(labels)),
        "identity_sessions": int(
            labels[["cycle_id", "entry_date"]].drop_duplicates().shape[0]
        ),
        "qualified_identity_sessions_by_mode": qualified_by_mode,
        "complete_strong_event_top3_labels": int(
            pd.to_numeric(
                qualified["strong_event_lead_sessions"], errors="coerce"
            ).notna().sum()
        ),
        "strict_historical_membership_rows_read": 0,
        "current_membership_rows_read": 0,
        "low_suction_outcomes_read": bool(
            pullback.get("low_suction_outcomes_read")
        ),
    }


def _identity_top3_groups(
    top3: pd.DataFrame,
    mode: str,
) -> dict[tuple[str, Any], set[str]]:
    selected = top3.loc[top3["identity_mode"].eq(mode)]
    return {
        (str(cycle_id), entry_date): set(group["vt_symbol"].astype(str))
        for (cycle_id, entry_date), group in selected.groupby(
            ["cycle_id", "entry_date"], sort=False
        )
    }


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [_json_safe(row) for row in frame.to_dict("records")]


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if value is None or value is pd.NA:
        return None
    try:
        return None if bool(pd.isna(value)) else value
    except (TypeError, ValueError):
        return value


def _ratio(value: Any) -> str:
    number = _optional_number(value)
    return "-" if number is None else f"{number * 100.0:.4f}%"


def _number(value: Any) -> str:
    number = _optional_number(value)
    return "-" if number is None else f"{number:.4f}"


def _optional_number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if np.isfinite(number) else None


def _summarize_identity_rows(rows: pd.DataFrame) -> dict[str, Any]:
    top3 = rows.loc[rows["mode_top3"].astype(bool)].copy()
    retention = pd.to_numeric(
        top3["retained_top3_next_session"], errors="coerce"
    ).dropna()
    strong_lead = pd.to_numeric(
        top3["strong_event_lead_sessions"], errors="coerce"
    ).dropna()
    capacity = top3["capacity_passed"].astype(float)
    return {
        "qualified_concept_sessions": int(
            top3[["cycle_id", "entry_date"]].drop_duplicates().shape[0]
        ),
        "top3_observations": int(len(top3)),
        "eligible_retention_observations": int(len(retention)),
        "next_session_top3_retention": _mean_or_none(retention),
        "strong_event_lead_observations": int(len(strong_lead)),
        "strong_event_lead_sessions": _median_or_none(strong_lead),
        "strong_event_within_five_rate": _mean_or_none(
            strong_lead.le(STRONG_EVENT_FUTURE_SESSIONS).astype(float)
        ),
        "capacity_pass_rate": _mean_or_none(capacity),
        "realized_market_top1_coverage": _session_flag_coverage(
            top3, "realized_market_top1"
        ),
        "realized_return_top1_coverage": _session_flag_coverage(
            top3, "realized_return_top1"
        ),
    }


def _session_flag_coverage(rows: pd.DataFrame, column: str) -> float | None:
    if rows.empty:
        return None
    values = rows.groupby(["cycle_id", "entry_date"], sort=False)[column].any()
    return float(values.astype(float).mean()) if not values.empty else None


def _metric_segments() -> tuple[tuple[str, frozenset[int]], ...]:
    return (
        ("all", frozenset(range(1, 6))),
        ("development", DEVELOPMENT_BLOCKS),
        ("validation", VALIDATION_BLOCKS),
        *((f"block_{block}", frozenset({block})) for block in range(1, 6)),
    )


def _block_sample_sufficient(metric: Any) -> bool:
    return (
        int(metric.eligible_retention_observations)
        >= MIN_BLOCK_RETENTION_OBSERVATIONS
        and int(metric.strong_event_lead_observations)
        >= MIN_BLOCK_STRONG_EVENT_OBSERVATIONS
    )


def _identity_winner_key(metric: Any) -> tuple[float, float, float, str]:
    return (
        -_required_metric(metric.next_session_top3_retention),
        _required_metric(metric.strong_event_lead_sessions),
        -_required_metric(metric.capacity_pass_rate),
        str(metric.identity_mode),
    )


def _compare_mode_to_baseline(
    metrics: pd.DataFrame,
    *,
    selected_mode: str,
    segment: str,
) -> tuple[bool, dict[str, Any]]:
    selected = _metric_row(metrics, selected_mode, segment)
    baseline = _metric_row(metrics, BASELINE_IDENTITY_MODE, segment)
    better = _lexicographically_better(selected, baseline)
    return better, {
        "segment": segment,
        "selected_mode": selected_mode,
        "better": better,
        "retention_delta": _metric_delta(
            selected, baseline, "next_session_top3_retention"
        ),
        "strong_event_lead_delta": _metric_delta(
            selected, baseline, "strong_event_lead_sessions"
        ),
        "capacity_delta": _metric_delta(selected, baseline, "capacity_pass_rate"),
    }


def _metric_row(metrics: pd.DataFrame, mode: str, segment: str) -> pd.Series:
    rows = metrics.loc[
        metrics["identity_mode"].eq(mode) & metrics["segment"].eq(segment)
    ]
    if len(rows) != 1:
        raise ValueError(f"identity metric row must be unique: {mode}/{segment}")
    return rows.iloc[0]


def _lexicographically_better(selected: pd.Series, baseline: pd.Series) -> bool:
    comparisons = (
        ("next_session_top3_retention", 1.0),
        ("strong_event_lead_sessions", -1.0),
        ("capacity_pass_rate", 1.0),
    )
    for column, direction in comparisons:
        left = _required_metric(selected[column])
        right = _required_metric(baseline[column])
        if np.isclose(left, right, rtol=0.0, atol=1e-12):
            continue
        return bool((left - right) * direction > 0)
    return False


def _metric_delta(selected: pd.Series, baseline: pd.Series, column: str) -> float:
    return _required_metric(selected[column]) - _required_metric(baseline[column])


def _required_metric(value: Any) -> float:
    if value is None or pd.isna(value):
        raise ValueError("identity selection metric cannot be null")
    number = float(value)
    if not np.isfinite(number):
        raise ValueError("identity selection metric must be finite")
    return number


def _mean_or_none(values: pd.Series) -> float | None:
    return float(values.mean()) if len(values) else None


def _median_or_none(values: pd.Series) -> float | None:
    return float(values.median()) if len(values) else None


def _daily_change_lookup(stock_bars: pd.DataFrame) -> dict[tuple[str, date], float]:
    bars = stock_bars.loc[:, ["vt_symbol", "trade_date", "close_price"]].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"], errors="raise").dt.date
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock bar identities must be unique")
    bars["close_price"] = pd.to_numeric(bars["close_price"], errors="coerce")
    bars = bars.sort_values(["vt_symbol", "trade_date"], kind="stable")
    bars["change_pct"] = bars.groupby("vt_symbol", sort=False)["close_price"].pct_change(
        fill_method=None
    ) * 100.0
    return {
        (str(row.vt_symbol), row.trade_date): float(row.change_pct)
        for row in bars.itertuples(index=False)
        if pd.notna(row.change_pct) and np.isfinite(float(row.change_pct))
    }


def _strong_event_lead(
    vt_symbol: str,
    position: int | None,
    *,
    calendar: tuple[date, ...],
    changes: dict[tuple[str, date], float],
) -> float:
    if position is None or position + STRONG_EVENT_FUTURE_SESSIONS >= len(calendar):
        return np.nan
    horizon = calendar[position : position + STRONG_EVENT_FUTURE_SESSIONS + 1]
    values = [changes.get((vt_symbol, trade_date)) for trade_date in horizon]
    if any(value is None for value in values):
        return np.nan
    for offset, value in enumerate(values):
        if float(value) >= STRONG_EVENT_THRESHOLD_PCT:
            return float(offset)
    return float(NO_STRONG_EVENT_SCORE)


def _prepare_calendar(values: Sequence[date]) -> tuple[date, ...]:
    calendar = tuple(sorted(set(pd.to_datetime(tuple(values), errors="raise").date)))
    if not calendar:
        raise ValueError("identity label calendar cannot be empty")
    return calendar


def _reject_rank_outcomes(frame: pd.DataFrame) -> None:
    prohibited = sorted(
        str(column)
        for column in frame.columns
        if str(column) in PROHIBITED_RANK_COLUMNS
        or str(column).lower().startswith(PROHIBITED_RANK_PREFIXES)
    )
    if prohibited:
        raise ValueError(f"prohibited identity rank columns: {prohibited}")


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
