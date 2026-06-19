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
    bucket = low_suction_launch_quality_bucket(evidence)
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
