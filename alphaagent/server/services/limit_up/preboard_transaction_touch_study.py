"""Historical v6 transaction-flow touch-timing counterexample."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import date
import json
from math import isfinite
from statistics import mean

from alphaagent.server.services.limit_up import preboard_competing_risk_study as legacy
from alphaagent.server.services.limit_up import preboard_joint_trigger_study as v3
from alphaagent.server.services.limit_up import preboard_transaction_trigger_study as v4
from alphaagent.server.services.limit_up.preboard_competing_risk_model import (
    ACTION_SCORE_FIELD as LEGACY_ACTION_SCORE_FIELD,
    IDENTITY_TARGET_FIELD,
    attach_competing_risk_targets,
    enrich_same_minute_competition,
)
from alphaagent.server.services.limit_up.preboard_hazard_model import (
    attach_hazard_targets,
)
from alphaagent.server.services.limit_up.preboard_joint_trigger_model import (
    ACTION_SCORE_FIELD as JOINT_ACTION_SCORE_FIELD,
    probability_calibration_report,
)
from alphaagent.server.services.limit_up.preboard_transaction_touch_model import (
    TOUCH_ACTION_SCORE_FIELD,
    TOUCH_ACTION_TARGET_FIELD,
    TOUCH_CONFIRMATION_MINUTES,
    TOUCH_PREPARE_SCORE_FIELD,
    TOUCH_PREPARE_TARGET_FIELD,
    calibrate_touch_threshold,
    select_touch_action_signals,
)
from alphaagent.server.services.limit_up.preboard_transaction_trigger_model import (
    TransactionTriggerModelFit,
    fit_transaction_trigger_model,
    score_transaction_trigger_rows,
    transaction_trigger_feature_vector,
)


STUDY_VERSION = "limit-up-preboard-transaction-touch-v6"
DEFAULT_SESSION_COUNT = 89


def build_transaction_touch_analysis(
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
    """Fit touch-only models and replay a single-complete-minute action policy."""

    identity_labeled = attach_competing_risk_targets(prefix_rows, formal_orders)
    touch_labeled = attach_hazard_targets(
        identity_labeled,
        formal_orders,
        horizons=(3, 5),
    )
    enriched_rows = enrich_same_minute_competition(touch_labeled)
    prepare_model = fit_transaction_trigger_model(
        enriched_rows,
        fit_dates=fit_dates,
        target_field=TOUCH_PREPARE_TARGET_FIELD,
    )
    action_model = fit_transaction_trigger_model(
        enriched_rows,
        fit_dates=fit_dates,
        target_field=TOUCH_ACTION_TARGET_FIELD,
    )
    prepare_rows = score_transaction_trigger_rows(
        enriched_rows,
        prepare_model,
        score_field=TOUCH_PREPARE_SCORE_FIELD,
    )
    action_rows = score_transaction_trigger_rows(
        prepare_rows,
        action_model,
        score_field=TOUCH_ACTION_SCORE_FIELD,
    )
    action_rows = [_alias_touch_score(row) for row in action_rows]
    threshold = calibrate_touch_threshold(
        action_rows,
        calibration_dates=calibration_dates,
    )
    replay_action_threshold = (
        threshold.threshold if threshold.threshold is not None else 1.1
    )
    normal_bundle = build_touch_replay_orders(
        action_rows=action_rows,
        formal_orders=formal_orders,
        action_threshold=replay_action_threshold,
    )
    conservative_bundle = build_touch_replay_orders(
        action_rows=action_rows,
        formal_orders=formal_orders,
        action_threshold=replay_action_threshold,
        conservative_entry=True,
    )

    phases: dict[str, dict[str, object]] = {}
    for phase, allowed_dates in {
        "full": fit_dates | calibration_dates | validation_dates,
        "validation": validation_dates,
    }.items():
        phases[phase] = _touch_phase_report(
            enriched_rows=enriched_rows,
            formal_orders=formal_orders,
            action_signals=normal_bundle["action_signals"],
            action_orders=normal_bundle["combined_orders"],
            conservative_orders=conservative_bundle["combined_orders"],
            bars=bars,
            trade_dates=trade_dates,
            allowed_dates=allowed_dates,
            action_rows=action_rows,
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
                **_touch_phase_report(
                    enriched_rows=enriched_rows,
                    formal_orders=formal_orders,
                    action_signals=normal_bundle["action_signals"],
                    action_orders=normal_bundle["combined_orders"],
                    conservative_orders=conservative_bundle["combined_orders"],
                    bars=bars,
                    trade_dates=trade_dates,
                    allowed_dates=set(block_dates),
                    action_rows=(),
                    action_threshold=threshold.threshold,
                    include_attribution=False,
                ),
            }
        )

    models: dict[str, TransactionTriggerModelFit] = {
        "prepare_touch_5m": prepare_model,
        "action_touch_3m": action_model,
    }
    model_reports = {key: v4._model_report(model) for key, model in models.items()}
    threshold_report = v3._threshold_report(threshold)
    validation_accounts = _mapping(
        _mapping(phases.get("validation")).get("accounts")
    )
    validation = _mapping(phases.get("validation"))
    acceptance = build_touch_acceptance_report(
        validation,
        validation_blocks=validation_blocks,
        models=tuple(models.values()),
        threshold=threshold,
        baseline_parity=baseline_parity,
        v3_reference_parity=v3_reference_parity,
        transaction_coverage=transaction_coverage,
        coverage_contract=coverage_contract,
    )
    oracle = build_reachable_touch_oracle(
        enriched_rows=enriched_rows,
        formal_orders=formal_orders,
        bars=bars,
        trade_dates=trade_dates,
        validation_dates=validation_dates,
    )
    analysis = {
        "dataset": legacy._dataset_report(enriched_rows),
        "models": model_reports,
        "threshold_selection": threshold_report,
        "probability_calibration": {
            "calibration": probability_calibration_report(
                action_rows,
                allowed_dates=calibration_dates,
                score_field=TOUCH_ACTION_SCORE_FIELD,
                target_field=TOUCH_ACTION_TARGET_FIELD,
            ),
            "validation": probability_calibration_report(
                action_rows,
                allowed_dates=validation_dates,
                score_field=TOUCH_ACTION_SCORE_FIELD,
                target_field=TOUCH_ACTION_TARGET_FIELD,
            ),
        },
        "prepare_score_count": len(prepare_rows),
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
            "action_signals": v4._stable_fingerprint(
                _stable_action_rows(normal_bundle["action_signals"])
            ),
            "oracle": v4._stable_fingerprint(oracle),
            "validation_accounts": v4._stable_fingerprint(validation_accounts),
        },
        "acceptance": acceptance,
        "decision": (
            "historical_pass_forward_shadow_only"
            if acceptance["passed"] is True
            else "historical_rejected_no_live_promotion"
        ),
    }
    artifacts = {
        "enriched_rows": enriched_rows,
        "action_rows": action_rows,
        "action_signals": normal_bundle["action_signals"],
        "combined_orders": normal_bundle["combined_orders"],
    }
    return analysis, dict(models), artifacts


def build_touch_acceptance_report(
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
    """Apply the unchanged account gates without accepting oracle inputs."""

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


def build_touch_replay_orders(
    *,
    action_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    action_threshold: float,
    conservative_entry: bool = False,
) -> dict[str, list[dict[str, object]]]:
    action_signals = select_touch_action_signals(
        action_rows,
        threshold=action_threshold,
    )
    early_orders = [
        order
        for signal in action_signals
        if (order := _touch_order(signal, conservative_entry=conservative_entry))
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
        "relay_orders": relay_orders,
        "combined_orders": [*relay_orders, *early_orders],
    }


def build_reachable_touch_oracle(
    *,
    enriched_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    validation_dates: set[date],
) -> dict[str, object]:
    """Measure the execution ceiling using future original-account identities."""

    formal_scope = legacy._orders_on_dates(formal_orders, validation_dates)
    formal_account = legacy.replay_competing_account(formal_scope, bars, trade_dates)
    original_pairs = legacy._filled_first_board_pairs(formal_account)
    latest_by_pair: dict[tuple[str, date], dict[str, object]] = {}
    for raw in enriched_rows:
        row = dict(raw)
        pair = legacy._order_pair(row)
        if (
            pair not in original_pairs
            or legacy._order_date(row) not in validation_dates
            or row.get(TOUCH_ACTION_TARGET_FIELD) is not True
            or row.get("transaction_features") is None
            or row.get("fillable") is not True
        ):
            continue
        previous = latest_by_pair.get(pair)
        if previous is None or str(row.get("signal_at") or "") > str(
            previous.get("signal_at") or ""
        ):
            latest_by_pair[pair] = row
    oracle_orders = [
        order
        for row in latest_by_pair.values()
        if (
            order := _touch_order(
                {
                    **row,
                    TOUCH_ACTION_SCORE_FIELD: 1.0,
                    JOINT_ACTION_SCORE_FIELD: 1.0,
                },
                conservative_entry=False,
            )
        )
        is not None
    ]
    relay_orders = [
        dict(order)
        for order in formal_scope
        if str(order.get("lane") or "") == "two_to_three"
    ]
    combined = [*relay_orders, *oracle_orders]
    account = legacy.replay_competing_account(combined, bars, trade_dates)
    filled_pairs = legacy._filled_first_board_pairs(account)
    return {
        "informational_only": True,
        "acceptance_input": False,
        "original_account_pair_count": len(original_pairs),
        "reachable_prefix_pair_count": len(latest_by_pair),
        "order_pair_count": len(oracle_orders),
        "filled_pair_count": len(filled_pairs),
        "matched_original_pair_count": len(filled_pairs & original_pairs),
        "reachable_original_recall_pct": _percentage(
            len(latest_by_pair), len(original_pairs)
        ),
        "account": legacy._account_metrics(combined, bars, trade_dates),
    }


def _touch_phase_report(
    *,
    enriched_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    action_signals: Sequence[Mapping[str, object]],
    action_orders: Sequence[Mapping[str, object]],
    conservative_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    allowed_dates: set[date],
    action_rows: Sequence[Mapping[str, object]],
    action_threshold: float | None,
    include_attribution: bool = True,
) -> dict[str, object]:
    report = {
        "identity": _touch_identity_report(
            enriched_rows,
            formal_orders,
            action_signals,
            allowed_dates=allowed_dates,
        ),
        "touch_quality": _touch_signal_report(
            action_signals,
            allowed_dates=allowed_dates,
        ),
        "accounts": _touch_phase_accounts(
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
            observation_rows=action_rows,
            scored_rows=action_rows,
            selected_signals=action_signals,
            action_threshold=action_threshold,
            confirmation_minutes=TOUCH_CONFIRMATION_MINUTES,
        )
    return report


def _touch_identity_report(
    rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    signals: Sequence[Mapping[str, object]],
    *,
    allowed_dates: set[date],
) -> dict[str, object]:
    """Use the v6 one-scoreable-minute contract for reachable recall."""

    report = legacy._identity_report(
        rows,
        formal_orders,
        signals,
        allowed_dates=allowed_dates,
    )
    eligible_rows = [
        row
        for row in rows
        if legacy._order_date(row) in allowed_dates
        and transaction_trigger_feature_vector(row) is not None
    ]
    reachable_formal_pairs = {
        legacy._order_pair(row)
        for row in eligible_rows
        if row.get(IDENTITY_TARGET_FIELD) is True
    }
    reachable_horizon_pairs = {
        legacy._order_pair(row)
        for row in eligible_rows
        if row.get(TOUCH_ACTION_TARGET_FIELD) is True
    }
    selected_pairs = {
        legacy._order_pair(row)
        for row in signals
        if legacy._order_date(row) in allowed_dates
    }
    return {
        **report,
        "reachable_formal_pair_count": len(reachable_formal_pairs),
        "reachable_horizon_pair_count": len(reachable_horizon_pairs),
        "reachable_formal_recall_pct": _percentage(
            len(selected_pairs & reachable_formal_pairs),
            len(reachable_formal_pairs),
        ),
        "reachable_horizon_recall_pct": _percentage(
            len(selected_pairs & reachable_horizon_pairs),
            len(reachable_horizon_pairs),
        ),
        "reachable_confirmation_minutes": TOUCH_CONFIRMATION_MINUTES,
    }


def _touch_phase_accounts(
    *,
    formal_orders: Sequence[Mapping[str, object]],
    action_orders: Sequence[Mapping[str, object]],
    conservative_orders: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date],
    allowed_dates: set[date],
) -> dict[str, object]:
    """Replay v6 accounts while retaining the established account field names."""

    formal = legacy._orders_on_dates(formal_orders, allowed_dates)
    action = legacy._orders_on_dates(action_orders, allowed_dates)
    conservative = legacy._orders_on_dates(conservative_orders, allowed_dates)
    relay = [
        order for order in formal if str(order.get("lane") or "") == "two_to_three"
    ]
    early = [
        order
        for order in action
        if str(order.get("algorithm") or "") == "formal_touch_3m_timing_v6"
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


def _touch_signal_report(
    signals: Sequence[Mapping[str, object]],
    *,
    allowed_dates: set[date],
) -> dict[str, object]:
    selected = [
        row for row in signals if legacy._order_date(row) in allowed_dates
    ]
    touched = [
        row for row in selected if row.get(TOUCH_ACTION_TARGET_FIELD) is True
    ]
    returns = [
        value
        for row in selected
        if (value := _number(row.get("net_return_pct"))) is not None
    ]
    return {
        "selection_count": len(selected),
        "touch_true_positive_count": len(touched),
        "touch_precision_pct": _percentage(len(touched), len(selected)),
        "d1_closed_count": len(returns),
        "d1_win_rate_pct": _percentage(
            sum(value > 0 for value in returns), len(returns)
        ),
        "d1_average_return_pct": round(mean(returns), 4) if returns else None,
    }


def _touch_order(
    signal: Mapping[str, object],
    *,
    conservative_entry: bool,
) -> dict[str, object] | None:
    probability = _number(signal.get(TOUCH_ACTION_SCORE_FIELD))
    aliased = {**dict(signal), JOINT_ACTION_SCORE_FIELD: probability}
    order = v3._joint_order(aliased, conservative_entry=conservative_entry)
    if order is None:
        return None
    return {
        **order,
        "algorithm": "formal_touch_3m_timing_v6",
        TOUCH_ACTION_SCORE_FIELD: probability,
        "action_score_kind": TOUCH_ACTION_SCORE_FIELD,
        "confirmation_minutes": TOUCH_CONFIRMATION_MINUTES,
        "candidate_source": "all_3pct_shared_strategy_1m_touch_timing_v6",
    }


def _alias_touch_score(row: Mapping[str, object]) -> dict[str, object]:
    return {
        **dict(row),
        JOINT_ACTION_SCORE_FIELD: row.get(TOUCH_ACTION_SCORE_FIELD),
        LEGACY_ACTION_SCORE_FIELD: row.get(TOUCH_ACTION_SCORE_FIELD),
    }


def evaluate_preboard_transaction_touch(
    *,
    session_count: int = DEFAULT_SESSION_COUNT,
) -> dict[str, object]:
    report = v4._evaluate_preboard_transaction_trigger(
        session_count=session_count,
        study_version=STUDY_VERSION,
        coverage_contract=v4.EXPLICIT_NO_ACTION_V5_COVERAGE,
        candidate_key="v6",
        candidate_analysis_builder=build_transaction_touch_analysis,
        candidate_confirmation_minutes=TOUCH_CONFIRMATION_MINUTES,
        candidate_action_model_key="action_touch_3m",
        candidate_label="v6触板时序模型",
        historical_validation_kind="viewed_development_counterexample",
    )
    if str(report.get("candidate_key") or "") != "v6":
        return report
    result = dict(report)
    incremental = _mapping(result.get("incremental_attribution"))
    if incremental:
        result["incremental_attribution"] = _rename_incremental_v6(incremental)
    limitations = [str(value) for value in result.get("limitations") or []]
    limitations.append(
        "TDX当日逐笔API已确认可用，但当前实时推荐链路尚未接入；时间戳仅到分钟级，"
        "不能复现十秒级拉板或L2委托撤单。"
    )
    result["limitations"] = limitations
    return result


def _stable_action_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[list[object]]:
    return [
        [
            str(row.get("vt_symbol") or ""),
            str(row.get("signal_date") or "")[:10],
            str(row.get("signal_time") or "")[:8],
            _number(row.get(TOUCH_ACTION_SCORE_FIELD)),
            row.get(TOUCH_ACTION_TARGET_FIELD) is True,
            row.get(IDENTITY_TARGET_FIELD) is True,
            row.get("fillable") is True,
        ]
        for row in sorted(
            rows,
            key=lambda value: (
                str(value.get("signal_date") or "")[:10],
                str(value.get("signal_time") or "")[:8],
                str(value.get("vt_symbol") or ""),
            ),
        )
    ]


def _rename_incremental_v6(
    report: Mapping[str, object],
) -> dict[str, object]:
    result = dict(report)
    categories = _mapping(result.get("categories"))
    result["categories"] = {
        str(name).replace("v4", "v6"): value
        for name, value in categories.items()
    }
    if "v4_signal_pair_count" in result:
        result["v6_signal_pair_count"] = result.pop("v4_signal_pair_count")
    return result


def render_preboard_transaction_touch_markdown(
    report: Mapping[str, object],
) -> str:
    markdown = v4.render_transaction_trigger_markdown(report)
    candidate = _mapping(report.get("v6"))
    threshold = _mapping(candidate.get("threshold_selection"))
    threshold_rows = [
        _mapping(row) for row in threshold.get("metrics_by_threshold") or []
    ]
    minimum_count = int(threshold.get("minimum_selection_count") or 0)
    count_qualified = [
        row
        for row in threshold_rows
        if int(row.get("selection_count") or 0) >= minimum_count
    ]
    best_count_qualified = max(
        count_qualified,
        key=lambda row: (
            _number(row.get("touch_precision")) or 0.0,
            int(row.get("touch_true_positive_count") or 0),
        ),
        default={},
    )
    validation = _mapping(_mapping(candidate.get("phases")).get("validation"))
    identity = _mapping(validation.get("identity"))
    touch_quality = _mapping(validation.get("touch_quality"))
    timing_lines = [
        "",
        "## Timing calibration",
        "",
        f"- 状态：`{threshold.get('status')}`；冻结阈值："
        f"`{threshold.get('threshold')}`；动作确认：1个完整分钟。",
    ]
    if best_count_qualified:
        timing_lines.append(
            "- 满足最少样本数的最佳校准点：阈值 "
            f"{best_count_qualified.get('threshold')}，"
            f"{best_count_qualified.get('touch_true_positive_count', 0)}/"
            f"{best_count_qualified.get('selection_count', 0)}，触板精度 "
            f"{_pct((_number(best_count_qualified.get('touch_precision')) or 0) * 100)}。"
        )
    timing_lines.append(
        f"- 验证段 v6 动作 {identity.get('selection_count', 0)}；"
        f"三分钟触板精度 {_pct(touch_quality.get('touch_precision_pct'))}；"
        "阈值失败时组合账户只含未改动二进三，不代表 v6 提前买入收益。"
    )
    timing_lines.append("")
    markdown = markdown.replace(
        "\n## Same-account validation\n",
        "\n".join(timing_lines) + "\n## Same-account validation\n",
        1,
    )
    oracle = _mapping(candidate.get("oracle_ceiling"))
    if not oracle:
        return markdown
    marker = "\n## Decision\n"
    oracle_lines = [
        "",
        "## Reachable oracle ceiling",
        "",
        "- 仅作可达上界，不进入模型、阈值或验收。",
        f"- 原账户 {oracle.get('original_account_pair_count', 0)} 个股票日；"
        f"3分钟可达 {oracle.get('reachable_prefix_pair_count', 0)}；"
        f"oracle账户匹配 {oracle.get('matched_original_pair_count', 0)}。",
        f"- 可达召回：{_pct(oracle.get('reachable_original_recall_pct'))}。",
    ]
    oracle_account = _mapping(oracle.get("account"))
    if oracle_account:
        oracle_lines.append(
            "- Oracle账户仅作上界："
            f"{oracle_account.get('trade_count', 0)} 笔，胜率 "
            f"{_pct(oracle_account.get('win_rate'))}，复利 "
            f"{_signed_pct(oracle_account.get('total_return_pct'))}，回撤 "
            f"{_signed_pct(oracle_account.get('max_drawdown_pct'))}。"
        )
    oracle_lines.append("")
    return markdown.replace(marker, "\n".join(oracle_lines) + marker, 1)


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


def _signed_pct(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:+.2f}%" if parsed is not None else "-"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate touch-timing trigger v6")
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
    report = evaluate_preboard_transaction_touch(session_count=args.sessions)
    markdown = render_preboard_transaction_touch_markdown(report)
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
