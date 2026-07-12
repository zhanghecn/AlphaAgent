"""Research-plan rules for the limit-up desk.

The plan is intentionally conditional: it selects a candidate from pre-trade
evidence, then requires a first reseal before the conservative fill proxy can
execute.  Final open counts and seal results never participate in selection.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from alphaagent.server.services.limit_up.features import promotion_rate_for_board


def build_daily_research_plan(
    candidates: Sequence[Mapping[str, object]],
    market_context: Mapping[str, object] | None,
) -> dict[str, object]:
    context = market_context or {}
    sentiment = context.get("sentiment")
    sentiment = sentiment if isinstance(sentiment, Mapping) else {}
    timing = context.get("timing")
    timing = timing if isinstance(timing, Mapping) else {}
    policy = _phase_policy(sentiment)
    if timing.get("active_direction") == "SILVER" and policy["max_plans"] > 1:
        policy = {
            **policy,
            "max_plans": 1,
            "risk_budget_pct": 25,
            "reason": f"{policy['reason']}；银手指后限制为一只",
        }

    eligible = sorted(
        (
            dict(candidate)
            for candidate in candidates
            if (
                candidate.get("decision") == "eligible"
                or (
                    candidate.get("decision_reason") == "fast_board_wait_reseal"
                    and float(candidate.get("dragon_score") or 0.0) >= 65
                )
            )
            and _candidate_gate_passed(candidate)
            and int(candidate.get("signal_board_level") or 1) <= 2
            and int(candidate.get("sector_dragon_rank") or 99) <= 2
        ),
        key=lambda item: (
            -float(item.get("dragon_score") or 0.0),
            int(item.get("market_dragon_rank") or 99),
            str(item.get("vt_symbol") or ""),
        ),
    )
    plans = eligible[: int(policy["max_plans"])]
    if not plans and int(policy["max_plans"]) > 0:
        policy = {
            **policy,
            "reason": "当前没有同时通过主线、情绪、板位和前排约束的候选",
        }
    return {
        **policy,
        "plans": plans,
        "rejected_count": max(len(candidates) - len(plans), 0),
        "entry_trigger": "first_reseal",
        "entry_trigger_label": "首次开板后的回封确认",
        "direct_board_allowed": False,
        "selection_cutoff": "D_FIRST_TOUCH",
        "verification_status": "blocked_by_missing_reseal_queue_data",
        "verification_reason": "日终事件只能证明触板和最终状态，不能验证首次回封时的队列成交",
        "board_lanes": build_board_lane_context(context),
    }


def build_board_lane_context(
    market_context: Mapping[str, object] | None,
) -> list[dict[str, object]]:
    context = market_context or {}
    sentiment = context.get("sentiment")
    sentiment = sentiment if isinstance(sentiment, Mapping) else {}
    phase = str(sentiment.get("phase") or "unknown")
    ladder = sentiment.get("promotion_ladder")
    ladder = ladder if isinstance(ladder, Mapping) else {}
    definitions = (
        (1, "first_board", "首板", "首板封板率"),
        (2, "one_to_two", "一进二", "一进二晋级率"),
        (3, "two_to_three", "二进三", "二进三晋级率"),
        (4, "three_plus", "三板以上", "高位晋级率"),
    )
    rows: list[dict[str, object]] = []
    for board_level, key, label, metric_label in definitions:
        metric = ladder.get(key)
        metric = metric if isinstance(metric, Mapping) else {}
        rate = promotion_rate_for_board(sentiment, board_level)
        action, action_label, reason = _lane_action(phase, board_level, rate)
        rows.append(
            {
                "board_level": board_level,
                "lane": key,
                "label": label,
                "metric_label": metric_label,
                "base_count": int(metric.get("base_count") or 0),
                "success_count": int(metric.get("promoted_count") or 0),
                "success_rate": rate,
                "action": action,
                "action_label": action_label,
                "reason": reason,
            }
        )
    return rows


def _candidate_gate_passed(candidate: Mapping[str, object]) -> bool:
    explicit = candidate.get("pretrade_gate_passed")
    if explicit is not None:
        return bool(explicit)
    return candidate.get("decision") == "eligible"


def _lane_action(
    phase: str,
    board_level: int,
    success_rate: float | None,
) -> tuple[str, str, str]:
    if phase in {"ice", "ebb", "unknown"}:
        return "blocked", "禁打", "冰点、退潮或情绪数据不足"
    if board_level >= 4:
        return "watch", "只观察", "高位需要盘口队列、监管和容量证据"
    if board_level == 3:
        if phase == "mainrise" and success_rate is not None and success_rate >= 0.25:
            return "reduced", "减半研究", "仅主升且二进三环境不弱时观察核心"
        return "blocked", "禁打", "二进三默认不进入无L2执行池"
    if success_rate is not None and success_rate < 0.12:
        return "blocked", "禁打", "对应板型历史成功率低于12%"
    if phase in {"divergence", "climax"}:
        return "conditional", "只等回封", "分歧或高潮只接受主线前排的可验证回封"
    if phase == "repair":
        return "trial", "小仓试错", "修复期只做低板主线前排"
    return "allowed", "可研究", "主升环境允许低板主线前排"


def _phase_policy(sentiment: Mapping[str, object]) -> dict[str, object]:
    phase = str(sentiment.get("phase") or "unknown")
    score = _number(sentiment.get("score"))
    promotion = _number(sentiment.get("promotion_rate"))
    failed = _number(sentiment.get("failed_limit_up_rate"))
    if phase in {"ice", "ebb"}:
        label = "冰点空仓" if phase == "ice" else "退潮空仓"
        return _policy("empty", label, f"{label}，不生成回封计划", 0, 0)
    if phase == "repair":
        strong_repair = (
            score is not None
            and score >= 60
            and promotion is not None
            and promotion >= 0.25
            and (failed is None or failed <= 0.35)
        )
        if strong_repair:
            return _policy("normal", "修复扩散", "修复强度和晋级率同步改善", 2, 50)
        return _policy("trial", "修复试错", "修复期只保留一只主线低板", 1, 25)
    if phase == "divergence":
        return _policy("reduced", "分歧收缩", "分歧期只留一只核心并等待回封", 1, 25)
    if phase == "climax":
        return _policy("reduced", "高潮降仓", "高潮期防次日兑现，只留一只核心", 1, 25)
    if phase in {"mainrise", "uptrend"}:
        return _policy("normal", "主升参与", "主升期最多两只主线前排", 2, 50)
    return _policy("empty", "数据不足", "缺少 D-1 情绪快照，不生成计划", 0, 0)


def _policy(
    action: str,
    label: str,
    reason: str,
    max_plans: int,
    risk_budget_pct: int,
) -> dict[str, object]:
    return {
        "action": action,
        "action_label": label,
        "reason": reason,
        "max_plans": max_plans,
        "risk_budget_pct": risk_budget_pct,
    }


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
