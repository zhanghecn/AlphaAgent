"""Historical proxy research for first-board sector warmup."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from statistics import mean

from alphaagent.server.services.limit_up.sector_warmup import (
    historical_warmup_proxy,
    historical_warmup_quality_gate,
)

RESEARCH_VERSION = "sector-warmup-research-v2"
INITIAL_CASH = 100_000.0
ROUND_TRIP_COST_PCT = 0.31
HARD_LOSS_PCT = -5.0
FORWARD_START_DATE = date(2026, 7, 13)
QUALITY_GATE_VARIANT = "warmup_quality_gate"
QUALITY_HYPOTHESIS_STATUS = "post_holdout_hypothesis"
MAX_DIAGNOSTIC_TRADES = 50

VARIANT_LABELS = {
    "baseline": "当前首板 Top1",
    "warmup_rank": "预热优先排序",
    "warmup_gate": "预热准入门",
    QUALITY_GATE_VARIANT: "预热质量门（事后假设）",
    "warmup_leader_proxy": "预热 + 昨日龙头代理",
}

DIAGNOSTIC_REASON_LABELS = {
    "warmup_unavailable": "预热字段不完整",
    "warmup_not_confirmed": "前一日行业未确认预热",
    "warmup_score_crowded": "预热分过高，处于拥挤段",
    "prior_industry_sealed_count_missing": "前一日行业封板数缺失",
    "prior_industry_no_sealed_expansion": "前一日行业没有封板扩散",
    "entry_day_failed_to_seal": "入场日最终炸板",
    "stock_amount_not_expanded": "个股前期量能未放大",
    "stock_seal_gene_weak": "半年触板封板率偏弱",
    "industry_seal_breadth_weak": "前一日行业封板宽度偏弱",
    "not_prior_industry_leader": "前一日行业龙头位靠后",
    "ranked_below_selected_warmup_candidate": "同日预热候选排名更低",
    "quality_gate_false_positive": "质量门仍未覆盖的亏损",
}


def build_sector_warmup_research_report(
    rows: Sequence[Mapping[str, object]],
    *,
    start: date | None = None,
    end: date | None = None,
    data_coverage: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Compare frozen first-board ranking against additive warmup proxies."""

    candidates_by_date, funnel = _closed_candidates_by_date(rows, start, end)
    trades_by_variant = _select_variant_trades(candidates_by_date)
    summaries = {
        variant: _summarize_trades(trades)
        for variant, trades in trades_by_variant.items()
    }
    baseline = summaries["baseline"]
    event_dates = sorted(candidates_by_date)
    coverage = dict(data_coverage or {})
    coverage.setdefault("signal_time_feature_linkage_ready", False)
    formal_ready = _formal_data_ready(
        coverage,
        event_dates[0] if event_dates else None,
        event_dates[-1] if event_dates else None,
    )
    comparisons = [
        _comparison(variant, summaries[variant], baseline, formal_ready)
        for variant in VARIANT_LABELS
    ]
    phase_summaries = _phase_summaries(trades_by_variant)
    acceptance = _acceptance(
        summaries["warmup_gate"],
        baseline,
        formal_ready,
        phase_summaries,
    )
    quality_gate_validation = _quality_gate_validation(
        coverage,
        phase_summaries,
    )
    return {
        "status": "ready" if rows else "insufficient_data",
        "research_version": RESEARCH_VERSION,
        "research_status": "formal" if formal_ready else "proxy_only",
        "simulation_eligible": bool(acceptance["passed"]),
        "scope": "first_board",
        "primary_exit": "next_open",
        "initial_cash": INITIAL_CASH,
        "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
        "return_cost_treatment": "already_in_ledger_no_second_deduction",
        "forward_start_date": FORWARD_START_DATE.isoformat(),
        "event_start": event_dates[0] if event_dates else None,
        "event_end": event_dates[-1] if event_dates else None,
        "candidate_funnel": funnel,
        "comparisons": comparisons,
        "phase_summaries": phase_summaries,
        "acceptance": acceptance,
        "quality_gate_validation": quality_gate_validation,
        "diagnostics": _trade_diagnostics(trades_by_variant),
        "data_coverage": coverage,
        "formal_concept_backtest_ready": formal_ready,
        "lane_isolation": {
            "passed": True,
            "affected_lanes": ["first_board"],
            "unchanged_lanes": ["two_to_three", "high_board"],
        },
        "selected_trades": {
            variant: trades[-200:] for variant, trades in trades_by_variant.items()
        },
        "limitations": [
            "当前结果使用信号日前一交易日行业涨幅、宽度和量能代理，不等同盘中概念预热。",
            "历史概念成员快照不足时禁止使用当前成员关系回填过去。",
            "昨日行业龙头排名不是首板信号时刻动态龙头，仅作反例诊断。",
            "预热质量门来自查看旧锁定留出后的假设，旧留出结果只作诊断，不是新样本外证明。",
            "所有预热字段保持 research_only，不改变实时动作和接力板排序。",
        ],
    }


def select_sector_warmup_variant_trades(
    rows: Sequence[Mapping[str, object]],
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, list[dict[str, object]]]:
    """Return all frozen variant selections for chronological cash execution."""

    candidates_by_date, _ = _closed_candidates_by_date(rows, start, end)
    return _select_variant_trades(candidates_by_date)


def _closed_candidates_by_date(
    rows: Sequence[Mapping[str, object]],
    start: date | None,
    end: date | None,
) -> tuple[dict[str, list[dict[str, object]]], dict[str, int]]:
    by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    raw_count = 0
    eligible_count = 0
    closed_count = 0
    confirmed_count = 0
    quality_count = 0
    for day in rows:
        trade_date = str(day.get("trade_date") or "")[:10]
        parsed_date = _date_or_none(trade_date)
        if (
            parsed_date is None
            or (start and parsed_date < start)
            or (end and parsed_date > end)
        ):
            continue
        phase = (
            "post_freeze_forward"
            if parsed_date >= FORWARD_START_DATE
            else str(day.get("validation_phase") or "unknown")
        )
        candidates = _first_board_candidates(day)
        raw_count += len(candidates)
        for candidate in candidates:
            if str(candidate.get("decision") or "") != "eligible":
                continue
            eligible_count += 1
            net_return = _outcome_number(candidate, "next_open_return_pct")
            if net_return is None:
                continue
            closed_count += 1
            warmup = historical_warmup_proxy(candidate)
            quality_gate = historical_warmup_quality_gate(candidate)
            if warmup["confirmed"]:
                confirmed_count += 1
            if quality_gate["passed"]:
                quality_count += 1
            by_date[trade_date].append(
                {
                    **_cash_execution_fields(candidate, trade_date),
                    "trade_date": trade_date,
                    "validation_phase": phase,
                    "vt_symbol": str(candidate.get("vt_symbol") or ""),
                    "name": str(
                        candidate.get("name") or candidate.get("vt_symbol") or ""
                    ),
                    "rank_score": _number(candidate.get("rank_score")) or 0.0,
                    "net_return_pct": round(net_return, 6),
                    "sealed": bool(_outcome_value(candidate, "sealed")),
                    "warmup_confirmed": bool(warmup["confirmed"]),
                    "warmup_state": warmup["state"],
                    "warmup_score": warmup["score"],
                    "warmup_quality_passed": bool(quality_gate["passed"]),
                    "warmup_quality_state": quality_gate["state"],
                    "warmup_quality_rejection_reasons": list(
                        quality_gate["rejection_reasons"]
                    ),
                    "prior_industry_change_pct": _candidate_number(
                        candidate,
                        "prior_industry_change_pct",
                    ),
                    "prior_industry_return_5d_pct": _candidate_number(
                        candidate,
                        "prior_industry_return_5d_pct",
                    ),
                    "prior_industry_advancing_rate": _candidate_number(
                        candidate,
                        "prior_industry_advancing_rate",
                    ),
                    "prior_industry_turnover_ratio_5d": _candidate_number(
                        candidate,
                        "prior_industry_turnover_ratio_5d",
                    ),
                    "prior_industry_sealed_count": _candidate_integer(
                        candidate,
                        "prior_industry_sealed_count",
                    ),
                    "prior_industry_sealed_rate": _candidate_number(
                        candidate,
                        "prior_industry_sealed_rate",
                    ),
                    "prior_amount_ratio_5d": _candidate_number(
                        candidate,
                        "prior_amount_ratio_5d",
                    ),
                    "prior_seal_success_rate_126": _candidate_number(
                        candidate,
                        "prior_seal_success_rate_126",
                    ),
                    "prior_industry_leader_rank": _candidate_integer(
                        candidate,
                        "prior_industry_leader_rank",
                    ),
                }
            )
    return dict(by_date), {
        "raw_first_board": raw_count,
        "eligible": eligible_count,
        "closed": closed_count,
        "warmup_confirmed": confirmed_count,
        "warmup_quality_confirmed": quality_count,
    }


def _cash_execution_fields(
    candidate: Mapping[str, object],
    trade_date: str,
) -> dict[str, object]:
    outcome = candidate.get("outcome")
    return {
        "lane": "first_board",
        "entry_date": str(candidate.get("entry_date") or trade_date)[:10],
        "signal_date": str(candidate.get("signal_date") or trade_date)[:10],
        "result_date": candidate.get("result_date"),
        "signal_time": candidate.get("signal_time"),
        "buy_time": candidate.get("buy_time") or candidate.get("signal_time"),
        "signal_kind": candidate.get("signal_kind"),
        "entry_price": candidate.get("entry_price"),
        "limit_price": candidate.get("limit_price"),
        "industry_id": candidate.get("industry_id"),
        "industry_name": candidate.get("industry_name"),
        "outcome": dict(outcome) if isinstance(outcome, Mapping) else {},
    }


def _select_variant_trades(
    candidates_by_date: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, list[dict[str, object]]]:
    selected = {variant: [] for variant in VARIANT_LABELS}
    for trade_date in sorted(candidates_by_date):
        candidates = [dict(candidate) for candidate in candidates_by_date[trade_date]]
        baseline = _best_ranked(candidates)
        if baseline is None:
            continue
        selected["baseline"].append(baseline)
        warmup_ranked = _best_ranked(
            candidates,
            prefer_warmup=True,
        )
        if warmup_ranked is not None:
            selected["warmup_rank"].append(warmup_ranked)
        warmup_candidates = [
            candidate for candidate in candidates if candidate["warmup_confirmed"]
        ]
        warmup_gated = _best_ranked(warmup_candidates)
        if warmup_gated is not None:
            selected["warmup_gate"].append(warmup_gated)
            if warmup_gated["warmup_quality_passed"]:
                selected[QUALITY_GATE_VARIANT].append(warmup_gated)
        leader_candidates = [
            candidate
            for candidate in warmup_candidates
            if _integer(candidate.get("prior_industry_leader_rank")) in {1, 2}
        ]
        leader = _best_ranked(leader_candidates)
        if leader is not None:
            selected["warmup_leader_proxy"].append(leader)
    return selected


def _best_ranked(
    candidates: Sequence[Mapping[str, object]],
    *,
    prefer_warmup: bool = False,
) -> dict[str, object] | None:
    if not candidates:
        return None
    return dict(
        min(
            candidates,
            key=lambda candidate: (
                -int(bool(candidate.get("warmup_confirmed"))) if prefer_warmup else 0,
                -(_number(candidate.get("rank_score")) or 0.0),
                str(candidate.get("vt_symbol") or ""),
            ),
        )
    )


def _summarize_trades(trades: Sequence[Mapping[str, object]]) -> dict[str, object]:
    ordered = sorted(trades, key=lambda trade: str(trade.get("trade_date") or ""))
    returns = [_number(trade.get("net_return_pct")) or 0.0 for trade in ordered]
    equity = INITIAL_CASH
    peak = INITIAL_CASH
    max_drawdown = 0.0
    for return_pct in returns:
        equity *= 1 + return_pct / 100
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, (equity / peak - 1) * 100)
    wins = sum(return_pct > 0 for return_pct in returns)
    hard_losses = sum(return_pct <= HARD_LOSS_PCT for return_pct in returns)
    sealed = sum(bool(trade.get("sealed")) for trade in ordered)
    count = len(returns)
    return {
        "trade_count": count,
        "trade_day_count": len({str(trade.get("trade_date")) for trade in ordered}),
        "win_rate": _percentage(wins, count),
        "average_net_return_pct": round(mean(returns), 4) if returns else None,
        "total_return_pct": round((equity / INITIAL_CASH - 1) * 100, 4),
        "max_drawdown_pct": round(max_drawdown, 4),
        "hard_loss_rate": _percentage(hard_losses, count),
        "seal_rate": _percentage(sealed, count),
        "initial_cash": INITIAL_CASH,
        "final_equity": round(equity, 2),
        "start": str(ordered[0].get("trade_date")) if ordered else None,
        "end": str(ordered[-1].get("trade_date")) if ordered else None,
    }


def _comparison(
    variant: str,
    summary: Mapping[str, object],
    baseline: Mapping[str, object],
    formal_data_ready: bool,
) -> dict[str, object]:
    result = {
        "variant": variant,
        "label": VARIANT_LABELS[variant],
        "formal": formal_data_ready
        and variant not in {"warmup_leader_proxy", QUALITY_GATE_VARIANT},
        **dict(summary),
    }
    if variant == QUALITY_GATE_VARIANT:
        result.update(
            {
                "hypothesis_status": QUALITY_HYPOTHESIS_STATUS,
                "execution_effect": "none_research_only",
            }
        )
    if variant == "baseline":
        result["delta"] = None
        return result
    result["delta"] = {
        "trade_count": int(summary["trade_count"]) - int(baseline["trade_count"]),
        "win_rate": _difference(summary.get("win_rate"), baseline.get("win_rate")),
        "average_net_return_pct": _difference(
            summary.get("average_net_return_pct"),
            baseline.get("average_net_return_pct"),
        ),
        "total_return_pct": _difference(
            summary.get("total_return_pct"),
            baseline.get("total_return_pct"),
        ),
        "max_drawdown_pct": _difference(
            summary.get("max_drawdown_pct"),
            baseline.get("max_drawdown_pct"),
        ),
    }
    return result


def _phase_summaries(
    trades_by_variant: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, list[dict[str, object]]]:
    phases = ("warmup", "expanding_oos", "locked_holdout", "post_freeze_forward")
    return {
        phase: [
            {
                "variant": variant,
                "label": VARIANT_LABELS[variant],
                **_summarize_trades(
                    [
                        trade
                        for trade in trades
                        if str(trade.get("validation_phase") or "") == phase
                    ]
                ),
            }
            for variant, trades in trades_by_variant.items()
        ]
        for phase in phases
    }


def _acceptance(
    treatment: Mapping[str, object],
    baseline: Mapping[str, object],
    formal_data_ready: bool,
    phase_summaries: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, object]:
    expanding_treatment, expanding_baseline = _phase_variant_pair(
        phase_summaries,
        "expanding_oos",
    )
    holdout_treatment, holdout_baseline = _phase_variant_pair(
        phase_summaries,
        "locked_holdout",
    )
    forward_treatment, forward_baseline = _phase_variant_pair(
        phase_summaries,
        "post_freeze_forward",
    )
    checks = [
        _check(
            "formal_data",
            formal_data_ready,
            "点时概念数据覆盖回测区间且已关联信号时刻",
        ),
        _check(
            "sample_count", int(treatment["trade_count"]) >= 100, "正式样本不少于100笔"
        ),
        _check(
            "seal_rate",
            _improvement(treatment.get("seal_rate"), baseline.get("seal_rate")) >= 5,
            "封板率相对基线提高至少5个百分点",
        ),
        _check(
            "win_rate",
            _improvement(treatment.get("win_rate"), baseline.get("win_rate")) >= 5,
            "D+1净胜率相对基线提高至少5个百分点",
        ),
        _check(
            "average_return",
            (_number(treatment.get("average_net_return_pct")) or -999) > 0
            and _improvement(
                treatment.get("average_net_return_pct"),
                baseline.get("average_net_return_pct"),
            )
            >= 0.25,
            "平均净收益为正且相对提高至少0.25个百分点",
        ),
        _check(
            "hard_loss_rate",
            _not_worse(
                treatment.get("hard_loss_rate"),
                baseline.get("hard_loss_rate"),
            ),
            "硬亏损率不高于基线",
        ),
        _check(
            "drawdown",
            (_number(treatment.get("max_drawdown_pct")) or -999)
            >= (_number(baseline.get("max_drawdown_pct")) or -999),
            "最大回撤不差于基线",
        ),
        _check(
            "final_equity",
            (_number(treatment.get("final_equity")) or 0)
            > (_number(baseline.get("final_equity")) or 0),
            "10万元期末资金高于基线",
        ),
        _check(
            "trade_retention",
            int(treatment["trade_count"]) >= int(baseline["trade_count"]) * 0.30,
            "保留交易数不少于基线30%",
        ),
        _check(
            "expanding_oos_direction",
            _phase_direction_consistent(expanding_treatment, expanding_baseline),
            "滚动样本外方向优于基线",
        ),
        _check(
            "locked_holdout_direction",
            _phase_direction_consistent(holdout_treatment, holdout_baseline),
            "锁定留出方向优于基线",
        ),
        _check(
            "post_freeze_forward_count",
            int(forward_treatment.get("trade_count") or 0) >= 30,
            "规则冻结后前向闭合不少于30笔",
        ),
        _check(
            "post_freeze_forward_direction",
            _phase_direction_consistent(forward_treatment, forward_baseline),
            "规则冻结后前向方向优于基线",
        ),
    ]
    return {
        "passed": all(bool(check["passed"]) for check in checks),
        "evaluated_variant": "warmup_gate",
        "checks": checks,
    }


def _quality_gate_validation(
    data_coverage: Mapping[str, object],
    phase_summaries: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, object]:
    forward_quality, forward_baseline = _phase_variant_pair(
        phase_summaries,
        "post_freeze_forward",
        QUALITY_GATE_VARIANT,
    )
    formal_data_ready = _forward_quality_data_ready(
        data_coverage,
        forward_quality.get("end"),
    )
    average_return = _number(forward_quality.get("average_net_return_pct"))
    total_return = _number(forward_quality.get("total_return_pct"))
    checks = [
        _check(
            "formal_data",
            formal_data_ready,
            "点时概念数据覆盖回测区间且已关联信号时刻",
        ),
        _check(
            "post_freeze_forward_count",
            int(forward_quality.get("trade_count") or 0) >= 30,
            "2026-07-13后前向闭合不少于30笔",
        ),
        _check(
            "post_freeze_positive_average",
            average_return is not None and average_return > 0,
            "冻结后前向平均净收益为正",
        ),
        _check(
            "post_freeze_positive_compound",
            total_return is not None and total_return > 0,
            "冻结后前向复利为正",
        ),
        _check(
            "post_freeze_win_rate",
            _not_worse(
                forward_quality.get("win_rate"),
                forward_baseline.get("win_rate"),
                higher=True,
            ),
            "冻结后前向胜率不低于同期基线",
        ),
        _check(
            "post_freeze_hard_loss_rate",
            _not_worse(
                forward_quality.get("hard_loss_rate"),
                forward_baseline.get("hard_loss_rate"),
            ),
            "冻结后前向硬亏损率不高于同期基线",
        ),
    ]
    return {
        "status": QUALITY_HYPOTHESIS_STATUS,
        "passed": all(bool(check["passed"]) for check in checks),
        "promotion_eligible": False,
        "manual_review_required": True,
        "evaluated_variant": QUALITY_GATE_VARIANT,
        "execution_effect": "none_research_only",
        "rule_freeze_date": FORWARD_START_DATE.isoformat(),
        "minimum_forward_trades": 30,
        "forward_trade_count": int(forward_quality.get("trade_count") or 0),
        "old_holdout_evidence_role": "diagnostic_only",
        "checks": checks,
    }


def _trade_diagnostics(
    trades_by_variant: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, object]:
    warmup_holdout = _phase_trades(trades_by_variant, "warmup_gate", "locked_holdout")
    baseline_holdout = _phase_trades(trades_by_variant, "baseline", "locked_holdout")
    warmup_keys = {_trade_key(trade) for trade in warmup_holdout}
    losses = [
        _diagnostic_trade(trade, _loss_reason_codes(trade))
        for trade in warmup_holdout
        if (_number(trade.get("net_return_pct")) or 0.0) < 0
    ]
    missed_winners = [
        _diagnostic_trade(trade, _missed_winner_reason_codes(trade))
        for trade in baseline_holdout
        if (_trade_key(trade) not in warmup_keys)
        and ((_number(trade.get("net_return_pct")) or 0.0) > 0)
    ]
    missed_winners.sort(
        key=lambda trade: (
            -(_number(trade.get("net_return_pct")) or 0.0),
            str(trade.get("trade_date") or ""),
            str(trade.get("vt_symbol") or ""),
        )
    )
    return {
        "phase": "locked_holdout",
        "source_variant": "warmup_gate",
        "old_holdout_evidence_role": "diagnostic_only",
        "locked_holdout_loss_count": len(losses),
        "locked_holdout_missed_winner_count": len(missed_winners),
        "locked_holdout_losses": losses[:MAX_DIAGNOSTIC_TRADES],
        "locked_holdout_missed_winners": missed_winners[:MAX_DIAGNOSTIC_TRADES],
    }


def _phase_trades(
    trades_by_variant: Mapping[str, Sequence[Mapping[str, object]]],
    variant: str,
    phase: str,
) -> list[Mapping[str, object]]:
    return [
        trade
        for trade in trades_by_variant.get(variant, ())
        if str(trade.get("validation_phase") or "") == phase
    ]


def _trade_key(trade: Mapping[str, object]) -> tuple[str, str]:
    return (
        str(trade.get("trade_date") or ""),
        str(trade.get("vt_symbol") or ""),
    )


def _loss_reason_codes(trade: Mapping[str, object]) -> list[str]:
    reasons = list(trade.get("warmup_quality_rejection_reasons") or [])
    if not bool(trade.get("sealed")):
        reasons.append("entry_day_failed_to_seal")
    amount_ratio = _number(trade.get("prior_amount_ratio_5d"))
    if amount_ratio is not None and amount_ratio < 1:
        reasons.append("stock_amount_not_expanded")
    seal_gene = _number(trade.get("prior_seal_success_rate_126"))
    if seal_gene is not None and seal_gene < 0.5:
        reasons.append("stock_seal_gene_weak")
    industry_seal_rate = _number(trade.get("prior_industry_sealed_rate"))
    if industry_seal_rate is not None and industry_seal_rate < 0.05:
        reasons.append("industry_seal_breadth_weak")
    leader_rank = _integer(trade.get("prior_industry_leader_rank"))
    if leader_rank is not None and leader_rank > 5:
        reasons.append("not_prior_industry_leader")
    if not reasons:
        reasons.append("quality_gate_false_positive")
    return list(dict.fromkeys(reasons))


def _missed_winner_reason_codes(trade: Mapping[str, object]) -> list[str]:
    if not bool(trade.get("warmup_confirmed")):
        return ["warmup_not_confirmed"]
    return ["ranked_below_selected_warmup_candidate"]


def _diagnostic_trade(
    trade: Mapping[str, object],
    reason_codes: Sequence[str],
) -> dict[str, object]:
    labels = [DIAGNOSTIC_REASON_LABELS.get(code, code) for code in reason_codes]
    feature_keys = (
        "trade_date",
        "validation_phase",
        "vt_symbol",
        "name",
        "net_return_pct",
        "sealed",
        "warmup_confirmed",
        "warmup_state",
        "warmup_score",
        "warmup_quality_passed",
        "prior_industry_change_pct",
        "prior_industry_return_5d_pct",
        "prior_industry_advancing_rate",
        "prior_industry_turnover_ratio_5d",
        "prior_industry_sealed_count",
        "prior_industry_sealed_rate",
        "prior_amount_ratio_5d",
        "prior_seal_success_rate_126",
        "prior_industry_leader_rank",
    )
    return {
        **{key: trade.get(key) for key in feature_keys},
        "reason_codes": list(reason_codes),
        "reason_labels": labels,
        "explanation": "、".join(labels),
    }


def _phase_variant_pair(
    phase_summaries: Mapping[str, Sequence[Mapping[str, object]]],
    phase: str,
    variant: str = "warmup_gate",
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    rows = phase_summaries.get(phase) or []
    by_variant = {str(row.get("variant") or ""): row for row in rows}
    return by_variant.get(variant, {}), by_variant.get("baseline", {})


def _phase_direction_consistent(
    treatment: Mapping[str, object],
    baseline: Mapping[str, object],
) -> bool:
    if (
        int(treatment.get("trade_count") or 0) <= 0
        or int(baseline.get("trade_count") or 0) <= 0
    ):
        return False
    return bool(
        _improvement(
            treatment.get("average_net_return_pct"),
            baseline.get("average_net_return_pct"),
        )
        > 0
        and _improvement(
            treatment.get("total_return_pct"),
            baseline.get("total_return_pct"),
        )
        > 0
        and _not_worse(treatment.get("win_rate"), baseline.get("win_rate"), higher=True)
        and _not_worse(
            treatment.get("hard_loss_rate"),
            baseline.get("hard_loss_rate"),
        )
        and _not_worse(
            treatment.get("max_drawdown_pct"),
            baseline.get("max_drawdown_pct"),
            higher=True,
        )
    )


def _not_worse(current: object, baseline: object, *, higher: bool = False) -> bool:
    current_number = _number(current)
    baseline_number = _number(baseline)
    if current_number is None or baseline_number is None:
        return False
    return (
        current_number >= baseline_number
        if higher
        else current_number <= baseline_number
    )


def _formal_data_ready(
    coverage: Mapping[str, object],
    event_start: str | None,
    event_end: str | None,
) -> bool:
    return (
        coverage.get("signal_time_feature_linkage_ready") is True
        and event_start is not None
        and event_end is not None
        and (_integer(coverage.get("membership_snapshot_days")) or 0) >= 500
        and (_integer(coverage.get("concept_daily_bar_days")) or 0) >= 500
        and (_integer(coverage.get("intraday_fund_snapshot_days")) or 0) >= 60
        and _coverage_contains(coverage, "membership_snapshot", event_start, event_end)
        and _coverage_contains(coverage, "concept_daily_bar", event_start, event_end)
        and _coverage_contains(
            coverage, "intraday_fund_snapshot", event_start, event_end
        )
    )


def _forward_quality_data_ready(
    coverage: Mapping[str, object],
    forward_end: object,
) -> bool:
    parsed_end = _date_or_none(forward_end)
    if parsed_end is None or parsed_end < FORWARD_START_DATE:
        return False
    required_start = FORWARD_START_DATE.isoformat()
    required_end = parsed_end.isoformat()
    return (
        coverage.get("signal_time_feature_linkage_ready") is True
        and (_integer(coverage.get("membership_snapshot_days")) or 0) >= 500
        and (_integer(coverage.get("concept_daily_bar_days")) or 0) >= 500
        and (_integer(coverage.get("intraday_fund_snapshot_days")) or 0) >= 60
        and _coverage_contains(
            coverage,
            "membership_snapshot",
            required_start,
            required_end,
        )
        and _coverage_contains(
            coverage,
            "concept_daily_bar",
            required_start,
            required_end,
        )
        and _coverage_contains(
            coverage,
            "intraday_fund_snapshot",
            required_start,
            required_end,
        )
    )


def _coverage_contains(
    coverage: Mapping[str, object],
    prefix: str,
    event_start: str,
    event_end: str,
) -> bool:
    coverage_start = _date_or_none(coverage.get(f"{prefix}_start"))
    coverage_end = _date_or_none(coverage.get(f"{prefix}_end"))
    required_start = _date_or_none(event_start)
    required_end = _date_or_none(event_end)
    return bool(
        coverage_start
        and coverage_end
        and required_start
        and required_end
        and coverage_start <= required_start
        and coverage_end >= required_end
    )


def _first_board_candidates(day: Mapping[str, object]) -> list[dict[str, object]]:
    pool = day.get("board_candidate_pool")
    if not isinstance(pool, Mapping):
        portfolio = day.get("lane_portfolio")
        portfolio = portfolio if isinstance(portfolio, Mapping) else {}
        pool = portfolio.get("candidate_pool")
    pool = pool if isinstance(pool, Mapping) else {}
    candidates = pool.get("first_board")
    candidates = candidates if isinstance(candidates, list) else []
    return [
        dict(candidate) for candidate in candidates if isinstance(candidate, Mapping)
    ]


def _outcome_value(candidate: Mapping[str, object], key: str) -> object:
    outcome = candidate.get("outcome")
    return outcome.get(key) if isinstance(outcome, Mapping) else None


def _outcome_number(candidate: Mapping[str, object], key: str) -> float | None:
    return _number(_outcome_value(candidate, key))


def _candidate_integer(candidate: Mapping[str, object], key: str) -> int | None:
    direct = _integer(candidate.get(key))
    if direct is not None:
        return direct
    known = candidate.get("known_at_signal")
    return _integer(known.get(key)) if isinstance(known, Mapping) else None


def _candidate_number(candidate: Mapping[str, object], key: str) -> float | None:
    direct = _number(candidate.get(key))
    if direct is not None:
        return direct
    known = candidate.get("known_at_signal")
    return _number(known.get(key)) if isinstance(known, Mapping) else None


def _check(code: str, passed: bool, label: str) -> dict[str, object]:
    return {"code": code, "passed": bool(passed), "label": label}


def _improvement(current: object, baseline: object) -> float:
    current_number = _number(current)
    baseline_number = _number(baseline)
    if current_number is None or baseline_number is None:
        return float("-inf")
    return current_number - baseline_number


def _difference(current: object, baseline: object) -> float | None:
    value = _improvement(current, baseline)
    return round(value, 4) if value != float("-inf") else None


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator else None


def _date_or_none(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _integer(value: object) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
