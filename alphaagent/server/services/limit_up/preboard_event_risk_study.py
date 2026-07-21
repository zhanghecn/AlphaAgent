"""Historical v7 market-event and candidate-ranking counterexample."""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
import json
from math import isfinite
from statistics import mean

from sqlalchemy import distinct, func, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.limit_up import preboard_competing_risk_study as legacy
from alphaagent.server.services.limit_up import preboard_joint_trigger_study as v3
from alphaagent.server.services.limit_up import preboard_transaction_touch_study as v6
from alphaagent.server.services.limit_up import preboard_transaction_trigger_study as v4
from alphaagent.server.services.limit_up.preboard_competing_risk_model import (
    ACTION_SCORE_FIELD as LEGACY_ACTION_SCORE_FIELD,
    IDENTITY_TARGET_FIELD,
    attach_competing_risk_targets,
    enrich_same_minute_competition,
)
from alphaagent.server.services.limit_up.preboard_event_risk_model import (
    CANDIDATE_EVENT_FEATURE_NAMES,
    EVENT_CANDIDATE_RANK_FIELD,
    EVENT_FEATURE_VERSION,
    EVENT_MARKET_SCORE_FIELD,
    EVENT_RANK_FEATURE_NAMES,
    EVENT_RANK_SCORE_FIELD,
    MARKET_EVENT_FEATURE_NAMES,
    MAX_DAILY_FIRST_BOARD_ACTIONS,
    TOUCH_TARGET_FIELD,
    EventMarketModelFit,
    EventRankModelFit,
    EventThresholdSelection,
    calibrate_event_risk_threshold,
    enrich_event_risk_features,
    event_market_training_batch,
    fit_event_market_model,
    fit_event_rank_model,
    score_event_risk_rows,
    select_event_risk_signals,
)
from alphaagent.server.services.limit_up.preboard_joint_trigger_model import (
    ACTION_SCORE_FIELD as JOINT_ACTION_SCORE_FIELD,
)


STUDY_VERSION = "limit-up-preboard-event-risk-v7"
DEFAULT_SESSION_COUNT = 89
EVENT_CONFIRMATION_MINUTES = 1
EVENT_ALGORITHM = "formal_touch_event_risk_v7"


def build_event_feature_rows(
    prefix_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Freeze observable event features before attaching any future target."""

    competing = enrich_same_minute_competition(prefix_rows)
    featured = enrich_event_risk_features(competing)
    return attach_competing_risk_targets(featured, formal_orders)


def build_event_risk_analysis(
    prefix_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    *,
    fit_dates: set[date],
    calibration_dates: set[date],
    validation_dates: set[date],
    baseline_parity: Mapping[str, object],
    v3_reference_parity: Mapping[str, object],
    transaction_coverage: Mapping[str, object],
    coverage_contract: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    labeled_rows = build_event_feature_rows(prefix_rows, formal_orders)
    market_model = fit_event_market_model(labeled_rows, fit_dates=fit_dates)
    rank_model = fit_event_rank_model(labeled_rows, fit_dates=fit_dates)
    scored_rows = [
        _alias_event_scores(row)
        for row in score_event_risk_rows(labeled_rows, market_model, rank_model)
    ]
    threshold = calibrate_event_risk_threshold(
        scored_rows,
        calibration_dates=calibration_dates,
    )
    replay_threshold = threshold.threshold if threshold.threshold is not None else 1.1
    normal_bundle = build_event_replay_orders(
        scored_rows=scored_rows,
        formal_orders=formal_orders,
        action_threshold=replay_threshold,
    )
    conservative_bundle = build_event_replay_orders(
        scored_rows=scored_rows,
        formal_orders=formal_orders,
        action_threshold=replay_threshold,
        conservative_entry=True,
    )

    phases: dict[str, dict[str, object]] = {}
    for phase, allowed_dates in {
        "full": fit_dates | calibration_dates | validation_dates,
        "validation": validation_dates,
    }.items():
        phases[phase] = _event_phase_report(
            labeled_rows=labeled_rows,
            formal_orders=formal_orders,
            action_signals=normal_bundle["action_signals"],
            action_orders=normal_bundle["combined_orders"],
            conservative_orders=conservative_bundle["combined_orders"],
            bars=bars,
            trade_dates=trade_dates,
            allowed_dates=allowed_dates,
            scored_rows=scored_rows,
            action_threshold=threshold.threshold,
        )

    validation_blocks: list[dict[str, object]] = []
    for index, block_dates in enumerate(
        legacy._fixed_validation_blocks(validation_dates),
        start=1,
    ):
        validation_blocks.append(
            {
                "block": index,
                "date_range": legacy._date_range(block_dates),
                **_event_phase_report(
                    labeled_rows=labeled_rows,
                    formal_orders=formal_orders,
                    action_signals=normal_bundle["action_signals"],
                    action_orders=normal_bundle["combined_orders"],
                    conservative_orders=conservative_bundle["combined_orders"],
                    bars=bars,
                    trade_dates=trade_dates,
                    allowed_dates=set(block_dates),
                    scored_rows=(),
                    action_threshold=threshold.threshold,
                    include_attribution=False,
                ),
            }
        )

    model_reports = {
        "market_touch_3m": _market_model_report(market_model),
        "candidate_touch_rank": _rank_model_report(rank_model),
    }
    model_reports["event_policy"] = _event_policy_report(model_reports)
    threshold_report = _threshold_report(threshold)
    acceptance = build_event_acceptance_report(
        _mapping(phases.get("validation")),
        validation_blocks=validation_blocks,
        models=(market_model, rank_model),
        threshold=threshold,
        baseline_parity=baseline_parity,
        v3_reference_parity=v3_reference_parity,
        transaction_coverage=transaction_coverage,
        coverage_contract=coverage_contract,
    )
    oracle = v6.build_reachable_touch_oracle(
        enriched_rows=labeled_rows,
        formal_orders=formal_orders,
        bars=bars,
        trade_dates=trade_dates,
        validation_dates=validation_dates,
    )
    ablation = _base_rank_ablation(
        scored_rows,
        calibration_dates=calibration_dates,
        validation_dates=validation_dates,
    )
    validation_accounts = _mapping(
        _mapping(phases.get("validation")).get("accounts")
    )
    analysis = {
        "dataset": legacy._dataset_report(labeled_rows),
        "models": model_reports,
        "threshold_selection": threshold_report,
        "market_event_quality": {
            "fit": _market_event_quality(scored_rows, fit_dates),
            "calibration": _market_event_quality(scored_rows, calibration_dates),
            "validation": _market_event_quality(scored_rows, validation_dates),
        },
        "ranking_quality": {
            "fit": _ranking_quality(scored_rows, fit_dates),
            "calibration": _ranking_quality(scored_rows, calibration_dates),
            "validation": _ranking_quality(scored_rows, validation_dates),
        },
        "base_rank_ablation": ablation,
        "phases": phases,
        "validation_blocks": validation_blocks,
        "signal_counts": {
            "action": len(normal_bundle["action_signals"]),
            "fillable_action": len(normal_bundle["early_orders"]),
        },
        "oracle_ceiling": oracle,
        "deterministic_fingerprints": {
            "models": v4._stable_fingerprint(model_reports),
            "threshold": v4._stable_fingerprint(threshold_report),
            "scored_rows": v4._stable_fingerprint(_stable_scored_rows(scored_rows)),
            "action_signals": v4._stable_fingerprint(
                _stable_action_rows(normal_bundle["action_signals"])
            ),
            "oracle": v4._stable_fingerprint(oracle),
            "validation_accounts": v4._stable_fingerprint(validation_accounts),
        },
        "acceptance": acceptance,
        "decision": (
            "historical_pass_forward_shadow_only"
            if acceptance.get("passed") is True
            else "historical_rejected_no_live_promotion"
        ),
    }
    artifacts = {
        "enriched_rows": labeled_rows,
        "action_rows": scored_rows,
        "action_signals": normal_bundle["action_signals"],
        "combined_orders": normal_bundle["combined_orders"],
    }
    return analysis, {"market": market_model, "rank": rank_model}, artifacts


def build_event_acceptance_report(
    validation: Mapping[str, object],
    *,
    validation_blocks: Sequence[Mapping[str, object]],
    models: Sequence[object],
    threshold: object,
    baseline_parity: Mapping[str, object],
    v3_reference_parity: Mapping[str, object],
    transaction_coverage: Mapping[str, object],
    coverage_contract: str,
) -> dict[str, object]:
    """Apply the unchanged v6 account gates without accepting oracle evidence."""

    return v4.build_transaction_acceptance_report(
        validation,
        validation_blocks=validation_blocks,
        models=models,
        threshold=threshold,
        baseline_parity=baseline_parity,
        v3_reference_parity=v3_reference_parity,
        transaction_coverage=transaction_coverage,
        coverage_contract=coverage_contract,
    )


def build_event_replay_orders(
    *,
    scored_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    action_threshold: float,
    conservative_entry: bool = False,
) -> dict[str, list[dict[str, object]]]:
    action_signals = select_event_risk_signals(
        scored_rows,
        threshold=action_threshold,
    )
    early_orders = [
        order
        for signal in action_signals
        if (order := _event_order(signal, conservative_entry=conservative_entry))
        is not None
    ]
    relay_orders = [
        dict(order)
        for order in formal_orders
        if str(order.get("lane") or "") == "two_to_three"
    ]
    return {
        "action_signals": action_signals,
        "early_orders": early_orders,
        "combined_orders": [*relay_orders, *early_orders],
    }


def _event_phase_report(
    *,
    labeled_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    action_signals: Sequence[Mapping[str, object]],
    action_orders: Sequence[Mapping[str, object]],
    conservative_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    allowed_dates: set[date],
    scored_rows: Sequence[Mapping[str, object]],
    action_threshold: float | None,
    include_attribution: bool = True,
) -> dict[str, object]:
    report = {
        "identity": v6._touch_identity_report(
            labeled_rows,
            formal_orders,
            action_signals,
            allowed_dates=allowed_dates,
        ),
        "touch_quality": v6._touch_signal_report(
            action_signals,
            allowed_dates=allowed_dates,
        ),
        "accounts": _event_phase_accounts(
            formal_orders=formal_orders,
            action_orders=action_orders,
            conservative_orders=conservative_orders,
            bars=bars,
            trade_dates=trade_dates,
            allowed_dates=allowed_dates,
        ),
        "account_identity": legacy._account_identity_report(
            formal_orders=formal_orders,
            action_orders=action_orders,
            bars=bars,
            trade_dates=trade_dates,
            allowed_dates=allowed_dates,
        ),
    }
    if include_attribution:
        report["account_path_attribution"] = legacy.build_account_path_attribution(
            formal_orders=formal_orders,
            action_orders=action_orders,
            bars=bars,
            trade_dates=trade_dates,
            allowed_dates=allowed_dates,
            observation_rows=labeled_rows,
            scored_rows=scored_rows,
            selected_signals=action_signals,
            action_threshold=action_threshold,
            confirmation_minutes=EVENT_CONFIRMATION_MINUTES,
        )
        report["event_selection_attribution"] = _event_selection_attribution(
            formal_orders=formal_orders,
            scored_rows=scored_rows,
            action_signals=action_signals,
            allowed_dates=allowed_dates,
            threshold=action_threshold,
        )
    return report


def _event_phase_accounts(
    *,
    formal_orders: Sequence[Mapping[str, object]],
    action_orders: Sequence[Mapping[str, object]],
    conservative_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    allowed_dates: set[date],
) -> dict[str, object]:
    formal = legacy._orders_on_dates(formal_orders, allowed_dates)
    action = legacy._orders_on_dates(action_orders, allowed_dates)
    conservative = legacy._orders_on_dates(conservative_orders, allowed_dates)
    relay = [
        order for order in formal if str(order.get("lane") or "") == "two_to_three"
    ]
    early = [
        order
        for order in action
        if str(order.get("algorithm") or "") == EVENT_ALGORITHM
    ]
    return {
        "formal_touch": legacy._account_metrics(formal, bars, trade_dates),
        "two_to_three_only": legacy._account_metrics(relay, bars, trade_dates),
        "early_first_board_only": legacy._account_metrics(early, bars, trade_dates),
        "joint_action": legacy._account_metrics(action, bars, trade_dates),
        "joint_action_double_cost": legacy._account_metrics(
            action,
            bars,
            trade_dates,
            cost_multiplier=2.0,
        ),
        "joint_action_conservative": legacy._account_metrics(
            conservative,
            bars,
            trade_dates,
        ),
    }


def _event_order(
    signal: Mapping[str, object],
    *,
    conservative_entry: bool,
) -> dict[str, object] | None:
    market_probability = _number(signal.get(EVENT_MARKET_SCORE_FIELD))
    rank_score = _number(signal.get(EVENT_RANK_SCORE_FIELD))
    aliased = {
        **dict(signal),
        JOINT_ACTION_SCORE_FIELD: market_probability,
    }
    order = v3._joint_order(aliased, conservative_entry=conservative_entry)
    if order is None:
        return None
    return {
        **order,
        "algorithm": EVENT_ALGORITHM,
        EVENT_MARKET_SCORE_FIELD: market_probability,
        EVENT_RANK_SCORE_FIELD: rank_score,
        EVENT_CANDIDATE_RANK_FIELD: signal.get(EVENT_CANDIDATE_RANK_FIELD, 1),
        "event_active_candidate_count": signal.get("event_active_candidate_count"),
        "event_feature_version": signal.get("event_feature_version"),
        "event_feature_cutoff": signal.get("event_feature_cutoff"),
        LEGACY_ACTION_SCORE_FIELD: market_probability,
        "action_score_kind": EVENT_MARKET_SCORE_FIELD,
        "confirmation_minutes": EVENT_CONFIRMATION_MINUTES,
        "candidate_source": "all_3pct_shared_strategy_event_risk_v7",
    }


def _alias_event_scores(row: Mapping[str, object]) -> dict[str, object]:
    probability = row.get(EVENT_MARKET_SCORE_FIELD)
    return {
        **dict(row),
        JOINT_ACTION_SCORE_FIELD: probability,
        LEGACY_ACTION_SCORE_FIELD: probability,
        v6.TOUCH_ACTION_SCORE_FIELD: probability,
    }


def evaluate_preboard_event_risk(
    *,
    session_count: int = DEFAULT_SESSION_COUNT,
) -> dict[str, object]:
    report = v4._evaluate_preboard_transaction_trigger(
        session_count=session_count,
        study_version=STUDY_VERSION,
        coverage_contract=v4.EXPLICIT_NO_ACTION_V5_COVERAGE,
        candidate_key="v7",
        candidate_analysis_builder=build_event_risk_analysis,
        candidate_confirmation_minutes=EVENT_CONFIRMATION_MINUTES,
        candidate_action_model_key="event_policy",
        candidate_label="v7事件竞争风险",
        historical_validation_kind="viewed_development_counterexample",
    )
    result = {**dict(report), "report_title": "首板事件竞争风险 v7 研究"}
    if str(result.get("candidate_key") or "") != "v7":
        return result
    result["incremental_attribution"] = _rename_incremental_v7(
        _mapping(result.get("incremental_attribution"))
    )
    result["point_in_time_context_coverage"] = load_point_in_time_context_coverage()
    limitations = [str(value) for value in result.get("limitations") or []]
    limitations.extend(
        [
            "历史概念强度、板块资金和雷达观察覆盖不足，明确排除在v7模型、阈值和验收之外。",
            "v7历史段已经被此前研究查看；即使历史通过，也只能冻结后累计新的60日只读前向证据。",
        ]
    )
    result["limitations"] = limitations
    return result


def load_point_in_time_context_coverage() -> dict[str, object]:
    concept = schema.limit_up_concept_strength_snapshots
    sector = schema.sector_fund_flow_snapshots
    frame = schema.limit_up_radar_frames
    observation = schema.limit_up_radar_observations
    with session_scope() as session:
        concept_days = session.execute(
            select(func.count(distinct(concept.c.trade_date)))
        ).scalar_one()
        sector_days = session.execute(
            select(func.count(distinct(sector.c.trade_date)))
        ).scalar_one()
        radar_days = session.execute(
            select(func.count(distinct(frame.c.trade_date))).select_from(
                frame.join(observation, observation.c.frame_id == frame.c.id)
            )
        ).scalar_one()
    return {
        "concept_snapshot_trade_days": int(concept_days or 0),
        "sector_fund_flow_snapshot_trade_days": int(sector_days or 0),
        "radar_observation_trade_days": int(radar_days or 0),
        "historical_model_input": False,
        "role": "new_forward_extension_only",
    }


def render_preboard_event_risk_markdown(report: Mapping[str, object]) -> str:
    markdown = v4.render_transaction_trigger_markdown(report)
    candidate = _mapping(report.get("v7"))
    models = _mapping(candidate.get("models"))
    market = _mapping(models.get("market_touch_3m"))
    rank = _mapping(models.get("candidate_touch_rank"))
    threshold = _mapping(candidate.get("threshold_selection"))
    ranking = _mapping(_mapping(candidate.get("ranking_quality")).get("validation"))
    supported_threshold = _best_supported_threshold_metric(threshold)
    validation = _mapping(_mapping(candidate.get("phases")).get("validation"))
    accounts = _mapping(validation.get("accounts"))
    early_account = _mapping(accounts.get("early_first_board_only"))
    joint_account = _mapping(accounts.get("joint_action"))
    event_lines = [
        "",
        "## Event-risk models",
        "",
        f"- 市场三分钟事件模型：`{market.get('status') or '-'}`，训练分钟 "
        f"{market.get('training_row_count', 0)}，指纹 `{market.get('fingerprint') or '-'}`。",
        f"- 候选 LambdaRank：`{rank.get('status') or '-'}`，混合风险集 "
        f"{rank.get('training_group_count', 0)}，指纹 `{rank.get('fingerprint') or '-'}`。",
        f"- 校准状态：`{threshold.get('status') or '-'}`；冻结市场概率阈值 "
        f"`{threshold.get('threshold')}`。",
        _supported_threshold_line(threshold, supported_threshold),
        f"- 验证事件分钟 Top1 命中：{_pct(ranking.get('ranker_top1_hit_pct'))}；"
        f"原 rank Top1：{_pct(ranking.get('base_top1_hit_pct'))}。",
        _first_board_account_line(early_account, joint_account),
        "",
        "",
    ]
    markdown = markdown.replace(
        "\n## Same-account validation\n",
        "\n".join(event_lines) + "## Same-account validation\n",
        1,
    )
    context = _mapping(report.get("point_in_time_context_coverage"))
    context_lines = [
        "",
        "## Point-in-time context boundary",
        "",
        f"- 概念快照 {context.get('concept_snapshot_trade_days', 0)} 日，板块资金快照 "
        f"{context.get('sector_fund_flow_snapshot_trade_days', 0)} 日，3%雷达有效观察 "
        f"{context.get('radar_observation_trade_days', 0)} 日。",
        "- 这些覆盖不足的数据不得进入 v7 历史模型、阈值或验收，只允许冻结后作为新前向扩展层。",
        "",
        "",
    ]
    return markdown.replace(
        "\n## Decision\n",
        "\n".join(context_lines) + "## Decision\n",
        1,
    )


def _market_model_report(model: EventMarketModelFit) -> dict[str, object]:
    return {
        "status": model.status,
        "target_field": model.target_field,
        "feature_version": model.feature_version,
        "features": list(MARKET_EVENT_FEATURE_NAMES),
        "training_row_count": model.training_row_count,
        "training_date_count": model.training_date_count,
        "class_counts": dict(model.class_counts),
        "fit_dates": list(model.fit_dates),
        "scaler_mean_by_feature": dict(model.scaler_mean_by_feature),
        "scaler_scale_by_feature": dict(model.scaler_scale_by_feature),
        "coefficient_by_feature": dict(model.coefficient_by_feature),
        "intercept": model.intercept,
        "fingerprint": model.fingerprint,
    }


def _rank_model_report(model: EventRankModelFit) -> dict[str, object]:
    importance = sorted(
        model.feature_importance_by_name.items(),
        key=lambda item: (-item[1], item[0]),
    )
    return {
        "status": model.status,
        "target_field": TOUCH_TARGET_FIELD,
        "feature_version": model.feature_version,
        "features": list(EVENT_RANK_FEATURE_NAMES),
        "candidate_event_features": list(CANDIDATE_EVENT_FEATURE_NAMES),
        "training_row_count": model.training_row_count,
        "training_group_count": model.training_group_count,
        "class_counts": dict(model.class_counts),
        "fit_dates": list(model.fit_dates),
        "parameters": dict(model.parameters),
        "feature_importance_by_name": dict(model.feature_importance_by_name),
        "importance_top10": [
            {"feature": name, "gain": value}
            for name, value in importance[:10]
        ],
        "fingerprint": model.fingerprint,
    }


def _event_policy_report(models: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    market = _mapping(models.get("market_touch_3m"))
    rank = _mapping(models.get("candidate_touch_rank"))
    ready = market.get("status") == "ready" and rank.get("status") == "ready"
    return {
        "status": "ready" if ready else "model_not_ready",
        "market_model_fingerprint": market.get("fingerprint"),
        "rank_model_fingerprint": rank.get("fingerprint"),
        "fingerprint": v4._stable_fingerprint(
            {
                "market": market.get("fingerprint"),
                "rank": rank.get("fingerprint"),
                "selection": "market_probability_gate_then_minute_rank_top1",
                "confirmation_minutes": EVENT_CONFIRMATION_MINUTES,
                "maximum_daily_first_board_actions": MAX_DAILY_FIRST_BOARD_ACTIONS,
            }
        ),
    }


def _threshold_report(selection: EventThresholdSelection) -> dict[str, object]:
    return {
        "status": selection.status,
        "threshold": selection.threshold,
        "calibration_dates": list(selection.calibration_dates),
        "minimum_selection_count": selection.minimum_selection_count,
        "minimum_precision": selection.minimum_precision,
        "selected_metrics": dict(selection.selected_metrics),
        "metrics_by_threshold": [dict(row) for row in selection.metrics_by_threshold],
    }


def _best_supported_threshold_metric(
    threshold: Mapping[str, object],
) -> dict[str, object]:
    minimum_count = int(_number(threshold.get("minimum_selection_count")) or 0)
    supported = [
        _mapping(row)
        for row in threshold.get("metrics_by_threshold") or []
        if int(_number(_mapping(row).get("selection_count")) or 0) >= minimum_count
    ]
    return max(
        supported,
        key=lambda row: (
            _number(row.get("touch_precision")) or 0.0,
            _number(row.get("reachable_recall")) or 0.0,
            _number(row.get("threshold")) or 0.0,
        ),
        default={},
    )


def _supported_threshold_line(
    threshold: Mapping[str, object],
    metric: Mapping[str, object],
) -> str:
    selected = int(_number(metric.get("selection_count")) or 0)
    true_count = int(_number(metric.get("touch_true_positive_count")) or 0)
    if not selected:
        return "- 校准段没有达到最少选择数的阈值。"
    return (
        f"- 至少 {threshold.get('minimum_selection_count', 0)} 次选择时，最好为阈值 "
        f"{metric.get('threshold')} 的 `{true_count}/{selected}="
        f"{_percentage(true_count, selected):.2f}%`，要求 "
        f"{float(_number(threshold.get('minimum_precision')) or 0.0) * 100:.2f}%。"
    )


def _first_board_account_line(
    early_account: Mapping[str, object],
    joint_account: Mapping[str, object],
) -> str:
    early_trades = int(_number(early_account.get("trade_count")) or 0)
    if early_trades:
        return (
            f"- 验证段提前首板成交 {early_trades} 笔，首板账户复利 "
            f"{v4._signed_pct(early_account.get('total_return_pct'))}。"
        )
    return (
        "- 验证段提前首板成交 0 笔；联合账户复利 "
        f"{v4._signed_pct(joint_account.get('total_return_pct'))} 来自未改动二进三，"
        "不能解释为 v7 收益。"
    )


def _market_event_quality(
    rows: Sequence[Mapping[str, object]],
    allowed_dates: set[date],
) -> dict[str, object]:
    groups: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        if legacy._order_date(row) in allowed_dates:
            groups[_minute_key(row)].append(row)
    labels: list[int] = []
    probabilities: list[float] = []
    for key in sorted(groups):
        group = groups[key]
        probability = next(
            (
                value
                for row in group
                if (value := _number(row.get(EVENT_MARKET_SCORE_FIELD))) is not None
            ),
            None,
        )
        if probability is None:
            continue
        labels.append(int(any(row.get(TOUCH_TARGET_FIELD) is True for row in group)))
        probabilities.append(probability)
    positives = sum(labels)
    return {
        "minute_count": len(labels),
        "positive_event_minute_count": positives,
        "event_rate_pct": _percentage(positives, len(labels)),
        "roc_auc": _roc_auc(labels, probabilities),
        "brier_score": (
            round(mean((probability - label) ** 2 for label, probability in zip(labels, probabilities, strict=True)), 8)
            if labels
            else None
        ),
    }


def _ranking_quality(
    rows: Sequence[Mapping[str, object]],
    allowed_dates: set[date],
) -> dict[str, object]:
    groups: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        if legacy._order_date(row) in allowed_dates:
            groups[_minute_key(row)].append(row)
    event_groups = [
        group
        for _, group in sorted(groups.items())
        if any(row.get(TOUCH_TARGET_FIELD) is True for row in group)
    ]
    ranker_top1 = sum(
        _top_k_hits(group, EVENT_RANK_SCORE_FIELD, 1) for group in event_groups
    )
    ranker_top2 = sum(
        _top_k_hits(group, EVENT_RANK_SCORE_FIELD, 2) for group in event_groups
    )
    base_top1 = sum(_top_k_hits(group, "rank_score", 1) for group in event_groups)
    base_top2 = sum(_top_k_hits(group, "rank_score", 2) for group in event_groups)
    count = len(event_groups)
    return {
        "event_minute_count": count,
        "ranker_top1_hit_count": ranker_top1,
        "ranker_top1_hit_pct": _percentage(ranker_top1, count),
        "ranker_top2_hit_count": ranker_top2,
        "ranker_top2_hit_pct": _percentage(ranker_top2, count),
        "base_top1_hit_count": base_top1,
        "base_top1_hit_pct": _percentage(base_top1, count),
        "base_top2_hit_count": base_top2,
        "base_top2_hit_pct": _percentage(base_top2, count),
    }


def _base_rank_ablation(
    rows: Sequence[Mapping[str, object]],
    *,
    calibration_dates: set[date],
    validation_dates: set[date],
) -> dict[str, object]:
    ablation_rows = [
        {
            **dict(row),
            EVENT_RANK_SCORE_FIELD: _number(row.get("rank_score")) or 0.0,
        }
        for row in rows
    ]
    selection = calibrate_event_risk_threshold(
        ablation_rows,
        calibration_dates=calibration_dates,
    )
    signals = (
        select_event_risk_signals(ablation_rows, threshold=selection.threshold)
        if selection.threshold is not None
        else []
    )
    validation = [
        row for row in signals if legacy._order_date(row) in validation_dates
    ]
    true_count = sum(row.get(TOUCH_TARGET_FIELD) is True for row in validation)
    return {
        "informational_only": True,
        "acceptance_input": False,
        "calibration": _threshold_report(selection),
        "validation_selection_count": len(validation),
        "validation_touch_true_positive_count": true_count,
        "validation_touch_precision_pct": _percentage(true_count, len(validation)),
    }


def _event_selection_attribution(
    *,
    formal_orders: Sequence[Mapping[str, object]],
    scored_rows: Sequence[Mapping[str, object]],
    action_signals: Sequence[Mapping[str, object]],
    allowed_dates: set[date],
    threshold: float | None,
) -> dict[str, object]:
    formal_pairs = {
        legacy._order_pair(order)
        for order in legacy._orders_on_dates(formal_orders, allowed_dates)
        if str(order.get("lane") or "") == "first_board"
    }
    selected_pairs = {
        legacy._order_pair(row)
        for row in action_signals
        if legacy._order_date(row) in allowed_dates
    }
    rows_by_pair: dict[tuple[str, date], list[Mapping[str, object]]] = defaultdict(list)
    for row in scored_rows:
        pair = legacy._order_pair(row)
        if pair in formal_pairs and legacy._order_date(row) in allowed_dates:
            rows_by_pair[pair].append(row)
    reasons: dict[str, int] = defaultdict(int)
    for pair in sorted(formal_pairs - selected_pairs):
        rows = rows_by_pair.get(pair, [])
        if not rows:
            reasons["no_scoreable_event_prefix"] += 1
            continue
        if threshold is None:
            reasons["action_threshold_unavailable"] += 1
            continue
        passing = [
            row
            for row in rows
            if (_number(row.get(EVENT_MARKET_SCORE_FIELD)) or -1.0) >= threshold
        ]
        if not passing:
            reasons["market_probability_below_threshold"] += 1
        elif all(int(row.get(EVENT_CANDIDATE_RANK_FIELD) or 0) > 1 for row in passing):
            reasons["lost_same_minute_candidate_ranking"] += 1
        else:
            reasons["daily_capacity_or_prior_selection"] += 1
    return {
        "formal_pair_count": len(formal_pairs),
        "selected_formal_pair_count": len(formal_pairs & selected_pairs),
        "missed_formal_pair_count": len(formal_pairs - selected_pairs),
        "missed_reason_counts": dict(sorted(reasons.items())),
    }


def _top_k_hits(
    group: Sequence[Mapping[str, object]],
    score_field: str,
    count: int,
) -> bool:
    ordered = sorted(
        group,
        key=lambda row: (
            -(_number(row.get(score_field)) or 0.0),
            str(row.get("vt_symbol") or ""),
        ),
    )
    return any(row.get(TOUCH_TARGET_FIELD) is True for row in ordered[:count])


def _roc_auc(labels: Sequence[int], probabilities: Sequence[float]) -> float | None:
    if len(set(labels)) < 2:
        return None
    from sklearn.metrics import roc_auc_score

    return round(float(roc_auc_score(labels, probabilities)), 8)


def _stable_scored_rows(rows: Sequence[Mapping[str, object]]) -> list[list[object]]:
    return [
        [
            str(row.get("vt_symbol") or ""),
            str(row.get("signal_date") or "")[:10],
            str(row.get("signal_time") or "")[:8],
            _number(row.get(EVENT_MARKET_SCORE_FIELD)),
            _number(row.get(EVENT_RANK_SCORE_FIELD)),
            int(row.get(EVENT_CANDIDATE_RANK_FIELD) or 0),
            row.get(TOUCH_TARGET_FIELD) is True,
        ]
        for row in sorted(rows, key=_row_sort_key)
    ]


def _stable_action_rows(rows: Sequence[Mapping[str, object]]) -> list[list[object]]:
    return [
        [
            str(row.get("vt_symbol") or ""),
            str(row.get("signal_date") or "")[:10],
            str(row.get("signal_time") or "")[:8],
            _number(row.get(EVENT_MARKET_SCORE_FIELD)),
            _number(row.get(EVENT_RANK_SCORE_FIELD)),
            row.get(TOUCH_TARGET_FIELD) is True,
            row.get(IDENTITY_TARGET_FIELD) is True,
            row.get("fillable") is True,
        ]
        for row in sorted(rows, key=_row_sort_key)
    ]


def _rename_incremental_v7(report: Mapping[str, object]) -> dict[str, object]:
    result = dict(report)
    categories = _mapping(result.get("categories"))
    result["categories"] = {
        str(name).replace("v4", "v7"): value for name, value in categories.items()
    }
    if "v4_signal_pair_count" in result:
        result["v7_signal_pair_count"] = result.pop("v4_signal_pair_count")
    return result


def _minute_key(row: Mapping[str, object]) -> tuple[str, str]:
    return (
        str(row.get("signal_date") or row.get("trade_date") or "")[:10],
        str(row.get("signal_time") or "")[:8],
    )


def _row_sort_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    date_text, signal_time = _minute_key(row)
    return date_text, signal_time, str(row.get("vt_symbol") or "")


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100.0, 4) if denominator else None


def _pct(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:.2f}%" if parsed is not None else "-"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate event-risk trigger v7")
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSION_COUNT)
    parser.add_argument(
        "--format",
        choices=("json", "markdown", "both"),
        default="markdown",
    )
    parser.add_argument("--output")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = evaluate_preboard_event_risk(session_count=args.sessions)
    markdown = render_preboard_event_risk_markdown(report)
    json_text = json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    if args.format == "both":
        if not args.output:
            raise ValueError("--output is required when --format=both")
        v4._write_output(f"{args.output}.md", markdown)
        v4._write_output(f"{args.output}.json", json_text)
        return
    content = json_text if args.format == "json" else markdown
    if args.output:
        v4._write_output(args.output, content)
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
