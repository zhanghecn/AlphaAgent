"""Read-only low-suction launch quality buckets.

The buckets are visible entry-day diagnostics. They do not imply a buy/sell
decision by themselves.
"""

from __future__ import annotations

from typing import Any


def low_suction_launch_quality_bucket(evidence: dict[str, Any]) -> str:
    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    if setup != "stealth_low_suction" and low_suction_days < 3:
        return "not_low_suction"
    if not evidence.get("low_suction_launch_confirmed"):
        return "unconfirmed_buildup"

    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    repeat_days = _float_or_none(evidence.get("tail_buy_repeat_days")) or 0.0
    pullback_days = _float_or_none(evidence.get("pullback_days")) or 0.0

    if pullback_days >= 12:
        return "late_pullback_launch"
    if repeat_days > 0:
        return "repeated_launch"
    if close_location is not None and 0.55 <= close_location <= 0.72 and volume_ratio is not None and 0.8 <= volume_ratio <= 1.4:
        return "balanced_first_lift"
    if volume_ratio is not None and volume_ratio < 0.75:
        return "thin_volume_launch"
    if close_location is not None and close_location >= 0.78:
        return "high_close_launch"
    return "other_confirmed_launch"


def low_suction_launch_quality_label(bucket: Any) -> str:
    labels = {
        "not_low_suction": "非低吸买点",
        "unconfirmed_buildup": "低吸蓄势未确认",
        "balanced_first_lift": "低吸首个均衡上拉",
        "thin_volume_launch": "低吸启动量能偏弱",
        "high_close_launch": "低吸启动收盘偏高",
        "late_pullback_launch": "低吸启动回踩过久",
        "repeated_launch": "低吸重复启动",
        "other_confirmed_launch": "其他低吸确认",
    }
    return labels.get(str(bucket or ""), str(bucket or "未知"))


def ensure_low_suction_launch_quality(evidence: dict[str, Any]) -> None:
    if evidence.get("low_suction_launch_quality_label"):
        return
    bucket = evidence.get("low_suction_launch_quality_bucket") or low_suction_launch_quality_bucket(evidence)
    evidence["low_suction_launch_quality_bucket"] = bucket
    evidence["low_suction_launch_quality_label"] = low_suction_launch_quality_label(bucket)


def low_suction_dragon_context(evidence: dict[str, Any]) -> dict[str, Any]:
    """Return read-only diagnostics for the low-suction / dragon boundary."""

    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    launch_confirmed = bool(evidence.get("low_suction_launch_confirmed"))
    early_state = str(evidence.get("entry_launch_diagnostic_state") or evidence.get("early_follow_through_state") or "")
    quality_bucket = low_suction_launch_quality_bucket(evidence)
    quality_label = low_suction_launch_quality_label(quality_bucket)
    early_dragon_risk = _is_early_dragon_without_buildup(evidence, setup=setup, low_suction_days=days)

    notes: list[str] = []
    conflict = False
    level = "neutral"

    if setup == "dragon_pullback" and days >= 3:
        if launch_confirmed:
            state, label = "dragon_overlap_low_suction_launch", "龙回头叠加低吸上拉"
            level = "positive"
            notes.append(quality_label)
        else:
            state, label = "dragon_overlap_waiting_low_suction", "龙回头叠加低吸蓄势未启动"
            conflict = True
            level = "warning"
            notes.append("低吸蓄势未出现首个上拉确认")
    elif setup == "dragon_pullback" and early_dragon_risk:
        state, label = "early_dragon_without_buildup", "龙回头偏早缺低吸蓄势"
        conflict = True
        level = "warning"
        notes.append("均线发散且缺少反复低吸承接")
    elif days >= 3 and not launch_confirmed:
        state, label = "low_suction_waiting_launch", "低吸蓄势等待上拉"
        level = "watch"
        notes.append("低吸状态不等于关键买点")
    elif days >= 3 and early_state == "failed_launch":
        state, label = "low_suction_confirmed_failed_follow", "低吸确认后无承接"
        conflict = True
        level = "warning"
        notes.append("首个上拉后买后三日承接失败")
    elif days >= 3 and early_state in {"confirmed_follow_through", "weak_follow_through", "low_suction_followed"}:
        state, label = "low_suction_confirmed_followed", "低吸确认且买后承接"
        level = "positive"
        notes.append(quality_label)
    elif days >= 3 and launch_confirmed:
        state, label = "low_suction_confirmed_launch", "低吸上拉确认"
        level = "positive"
        notes.append(quality_label)
    elif setup == "dragon_pullback":
        state, label = "standard_dragon_pullback", "标准龙回头"
    else:
        state, label = "not_low_suction_dragon", "非低吸龙回头"

    return {
        "low_suction_dragon_state": state,
        "low_suction_dragon_label": label,
        "low_suction_dragon_conflict": conflict,
        "low_suction_dragon_conflict_level": level,
        "low_suction_dragon_notes": _dedupe_notes(notes),
    }


def ensure_low_suction_dragon_context(evidence: dict[str, Any]) -> None:
    if evidence.get("low_suction_dragon_label"):
        return
    evidence.update(low_suction_dragon_context(evidence))


def entry_family_context(evidence: dict[str, Any]) -> dict[str, Any]:
    """Return read-only setup-family diagnostics.

    This deliberately does not change score, action, or failed rules. The goal
    is to separate low-position reclaim semantics from dragon-pullback
    semantics so later factor audits can compare them without changing trades.
    """

    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    low_reclaim_type = _low_position_reclaim_type(evidence)
    dragon_like = _is_dragon_pullback_family(evidence, setup=setup)
    low_reclaim_like = low_reclaim_type != "none"
    notes: list[str] = []

    if low_reclaim_like:
        family = "low_position_reclaim"
        label = "低位承接转强"
        notes.extend(_low_position_reclaim_notes(evidence, low_reclaim_type))
    elif dragon_like:
        family = "dragon_pullback"
        label = "龙回头回踩"
        notes.append("前置强势或龙回头状态成立")
    else:
        family = "unknown"
        label = "未归类"

    conflict = bool(low_reclaim_like and dragon_like)
    if conflict:
        notes.append("同时具备龙回头和低位承接证据，后续审计需分桶比较")

    return {
        "entry_family": family,
        "entry_family_label": label,
        "entry_family_conflict": conflict,
        "entry_family_notes": _dedupe_notes(notes),
        "low_position_reclaim_type": low_reclaim_type,
        "low_position_reclaim_label": low_position_reclaim_label(low_reclaim_type),
        "is_readonly_setup_diagnostic": True,
    }


def ensure_entry_family_context(evidence: dict[str, Any]) -> None:
    if evidence.get("entry_family") and evidence.get("low_position_reclaim_type"):
        return
    evidence.update(entry_family_context(evidence))


def low_position_reclaim_label(kind: Any) -> str:
    labels = {
        "platform_accumulation_launch": "平台低吸首启",
        "ma_support_reclaim": "均线承接上攻",
        "deep_reclaim": "深回踩修复",
        "none": "非低位承接",
    }
    return labels.get(str(kind or ""), str(kind or "未知"))


def low_suction_dragon_context_label(bucket: Any) -> str:
    labels = {
        "dragon_overlap_low_suction_launch": "龙回头叠加低吸上拉",
        "dragon_overlap_waiting_low_suction": "龙回头叠加低吸蓄势未启动",
        "early_dragon_without_buildup": "龙回头偏早缺低吸蓄势",
        "low_suction_waiting_launch": "低吸蓄势等待上拉",
        "low_suction_confirmed_failed_follow": "低吸确认后无承接",
        "low_suction_confirmed_followed": "低吸确认且买后承接",
        "low_suction_confirmed_launch": "低吸上拉确认",
        "standard_dragon_pullback": "标准龙回头",
        "not_low_suction_dragon": "非低吸龙回头",
    }
    return labels.get(str(bucket or ""), str(bucket or "未知"))


def _low_position_reclaim_type(evidence: dict[str, Any]) -> str:
    if _has_distribution_or_break_risk(evidence):
        return "none"
    if not _is_low_or_mid_low_position(evidence):
        return "none"

    days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    ma30_distance = _float_or_none(evidence.get("ma30_distance_pct"))
    launch_confirmed = bool(evidence.get("low_suction_launch_confirmed"))
    ma_converged = convergence is not None and convergence <= 6.5
    volume_controlled = volume_ratio is not None and 0.45 <= volume_ratio <= 1.55
    close_strong = close_location is not None and close_location >= 0.55
    lift_ok = latest_change is not None and 0.6 <= latest_change <= 6.5
    support_ok = ma20_distance is not None and ma20_distance >= -3.2

    if days >= 3 and ma_converged and volume_controlled and support_ok and (launch_confirmed or (close_strong and lift_ok)):
        return "platform_accumulation_launch"

    near_or_reclaimed_ma = any(
        distance is not None and -3.5 <= distance <= 4.8
        for distance in (
            _float_or_none(evidence.get("ma5_distance_pct")),
            _float_or_none(evidence.get("ma10_distance_pct")),
            ma20_distance,
            ma30_distance,
        )
    )
    if days >= 2 and near_or_reclaimed_ma and close_strong and support_ok and volume_controlled:
        return "ma_support_reclaim"

    drawdown = _float_or_none(evidence.get("drawdown_from_pivot_pct"))
    max_drawdown_60d = _float_or_none(evidence.get("max_drawdown_60d"))
    if (
        near_or_reclaimed_ma
        and close_strong
        and lift_ok
        and support_ok
        and max_drawdown_60d is not None
        and max_drawdown_60d <= -15.0
        and (drawdown is None or drawdown >= -22.0)
    ):
        return "deep_reclaim"

    return "none"


def _is_dragon_pullback_family(evidence: dict[str, Any], *, setup: str) -> bool:
    if setup == "dragon_pullback":
        return True
    if str(evidence.get("dragon_state") or "") == "TAIL_BUY_READY":
        return True
    return_20d = _float_or_none(evidence.get("return_20d"))
    return_60d = _float_or_none(evidence.get("return_60d"))
    near_limit_count = _float_or_none(evidence.get("near_limit_up_count_20d")) or 0.0
    large_bull_count = _float_or_none(evidence.get("large_bull_count_20d")) or 0.0
    strong_leg_score = _float_or_none(evidence.get("strong_leg_score"))
    return bool(
        (return_20d is not None and return_20d >= 18.0)
        or (return_60d is not None and return_60d >= 30.0)
        or near_limit_count >= 1
        or large_bull_count >= 1
        or (strong_leg_score is not None and strong_leg_score >= 72.0)
    )


def _is_low_or_mid_low_position(evidence: dict[str, Any]) -> bool:
    return_20d = _float_or_none(evidence.get("return_20d"))
    return_60d = _float_or_none(evidence.get("return_60d"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    high_sideways_days = _float_or_none(evidence.get("high_level_sideways_days")) or 0.0
    if high_sideways_days >= 12:
        return False
    if return_60d is not None and return_60d >= 45.0:
        return False
    if return_20d is not None and return_20d >= 22.0:
        return False
    if ma20_distance is not None and ma20_distance >= 14.0:
        return False
    return True


def _has_distribution_or_break_risk(evidence: dict[str, Any]) -> bool:
    if bool(evidence.get("high_level_sideways_distribution_risk")):
        return True
    risk_flags = {str(flag) for flag in evidence.get("risk_flags") or []}
    failed_rules = {str(rule) for rule in evidence.get("failed_rules") or []}
    hard_risks = {
        "distribution_risk",
        "high_level_sideways_distribution_risk",
        "volume_stall_risk",
        "key_support_break_risk",
        "ma20_broken",
        "pullback_too_deep",
    }
    if risk_flags & hard_risks or failed_rules & hard_risks:
        return True
    return bool(evidence.get("volume_stall_risk") or evidence.get("key_support_break_risk"))


def _low_position_reclaim_notes(evidence: dict[str, Any], kind: str) -> list[str]:
    notes: list[str] = []
    convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    if convergence is not None and convergence <= 6.5:
        notes.append("低位均线收敛")
    if days >= 3:
        notes.append(f"低吸承接 {int(days)} 天")
    if bool(evidence.get("low_suction_launch_confirmed")):
        notes.append("首个上拉确认")
    if kind == "ma_support_reclaim":
        notes.append("低位均线承接上攻")
    elif kind == "deep_reclaim":
        notes.append("深回踩后修复")
    return notes


def _is_early_dragon_without_buildup(evidence: dict[str, Any], *, setup: str, low_suction_days: float) -> bool:
    if setup != "dragon_pullback":
        return False
    if bool(evidence.get("early_dragon_pullback_risk")):
        return True
    if low_suction_days > 0:
        return False
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    return bool(
        ma_convergence is not None
        and ma_convergence >= 18.0
        and latest_change is not None
        and latest_change >= 1.0
        and close_location is not None
        and close_location >= 0.55
    )


def _dedupe_notes(notes: list[str]) -> list[str]:
    result = []
    seen = set()
    for note in notes:
        text = str(note or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
