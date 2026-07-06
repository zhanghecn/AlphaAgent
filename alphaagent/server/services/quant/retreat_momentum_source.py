"""Hidden retreat momentum source for the unified dragon-pullback strategy."""

from __future__ import annotations

from collections import defaultdict
from copy import copy
from typing import Any

from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.services.quant.factors import SignalScore, clamp_score


RETREAT_MOMENTUM_SOURCE_LANE = "retreat_high_low_switch_momentum"


def append_board_survival_pressure_sources(
    scores: list[SignalScore],
    *,
    visible_bars: dict[str, list[Any]],
    session: Any | None = None,
    stock_meta: dict[str, dict[str, Any]] | None = None,
    sector_names: dict[str, list[str]] | None = None,
    source_cap: int = 2,
) -> list[SignalScore]:
    """Append a narrow D-day-visible pressure right-tail source.

    The source is intentionally hidden under the public dragon-pullback strategy:
    users still see one strategy, while the internal execution pool may include a
    small number of board-survival retreat momentum candidates.
    """

    if not scores or source_cap <= 0:
        return list(scores)
    raw_rank_by_symbol = {
        str(score.vt_symbol): rank
        for rank, score in enumerate(sorted(scores, key=lambda item: (-float(item.total_score or 0), str(item.vt_symbol))), start=1)
    }
    symbols = [str(score.vt_symbol) for score in scores]
    stock_meta = stock_meta if stock_meta is not None else _load_stock_meta(session, symbols)
    sector_names = sector_names if sector_names is not None else _load_sector_names(session, symbols)

    source_scores = [
        source
        for score in scores
        if (
            source := _source_candidate_from_score(
                score,
                stock_meta=stock_meta.get(str(score.vt_symbol), {}),
                sectors=sector_names.get(str(score.vt_symbol), []),
                raw_rank=raw_rank_by_symbol.get(str(score.vt_symbol)),
            )
        )
        is not None
    ]
    if not source_scores:
        return list(scores)

    _attach_board_quality(source_scores, visible_bars=visible_bars, stock_meta=stock_meta, sector_names=sector_names)
    _attach_theme_confirmation(source_scores)
    _attach_cross_section_stats(source_scores)

    selected_sources: list[SignalScore] = []
    existing_symbols = {
        str(score.vt_symbol)
        for score in scores
        if bool(getattr(score, "entry_signal", False)) or bool((getattr(score, "evidence", {}) or {}).get("default_executable_entry_signal"))
    }
    for source in sorted(
        (score for score in source_scores if board_survival_pressure_source_allowed(score)),
        key=lambda score: (
            -(_num((score.evidence or {}).get("retreat_momentum_opportunity_score")) or float(score.total_score or 0.0)),
            _num((score.evidence or {}).get("retreat_momentum_raw_signal_rank")) or 10**9,
            str(score.vt_symbol),
        ),
    ):
        if len(selected_sources) >= source_cap:
            break
        vt_symbol = str(source.vt_symbol)
        if vt_symbol in existing_symbols:
            continue
        selected_sources.append(source)
        existing_symbols.add(vt_symbol)
    return [*scores, *selected_sources]


def board_survival_pressure_source_allowed(score: SignalScore) -> bool:
    evidence = getattr(score, "evidence", {}) or {}
    if not evidence.get("retreat_momentum_board_survival_source"):
        return False
    if str(evidence.get("timing_window") or "") != "after_silver_late":
        return False
    if str(evidence.get("market_phase") or "") != "retreat":
        return False
    if str(evidence.get("retreat_momentum_subtype") or "") != "active_first_pullback_switch":
        return False
    if not bool(evidence.get("retreat_momentum_theme_confirmed")):
        return False
    if not (bool(evidence.get("board_is_limit_up")) or bool(evidence.get("board_near_limit_close"))):
        return False
    if bool(evidence.get("board_failed_limit_up")):
        return False

    source_score = _num(evidence.get("retreat_momentum_opportunity_score")) or float(score.total_score or 0.0)
    raw_rank = _num(evidence.get("retreat_momentum_raw_signal_rank")) or 10**9
    theme_rank = _num(evidence.get("retreat_momentum_theme_source_rank")) or 10**9
    ret5 = _num(evidence.get("return_5d")) or 0.0
    ret20 = _num(evidence.get("return_20d")) or 0.0
    ret60 = _num(evidence.get("return_60d")) or 0.0
    ma20 = _num(evidence.get("ma20_distance_pct")) or 0.0
    near_count = _num(evidence.get("near_limit_up_count_20d")) or 0.0
    volume_ratio = _num(evidence.get("volume_ratio_5d_20d"))
    latest_change = _num(evidence.get("latest_change_pct"))
    close_location = _num(evidence.get("board_close_location_in_range"))
    upper_shadow = _num(evidence.get("board_upper_shadow_pct")) or 0.0
    streak = _num(evidence.get("board_limit_up_streak")) or 0.0
    limit_count_5d = _num(evidence.get("board_limit_up_count_5d")) or 0.0
    promoted = _num(evidence.get("board_theme_promoted_limit_up_count")) or 0.0
    theme_source_count = _num(evidence.get("retreat_momentum_theme_source_count")) or 0.0
    sparse_theme_frontrow = bool(theme_source_count < 2.0 and raw_rank > 160.0)

    return bool(
        source_score >= 91.5
        and raw_rank <= 200.0
        and theme_rank <= 2.0
        and not sparse_theme_frontrow
        and latest_change is not None
        and latest_change >= 9.3
        and 12.0 <= ret5 <= 27.0
        and ret20 <= 45.0
        and ret60 <= 60.0
        and ma20 <= 30.0
        and near_count <= 5.0
        and volume_ratio is not None
        and 0.80 <= volume_ratio <= 2.60
        and (close_location is None or close_location >= 0.86)
        and upper_shadow <= 2.5
        and streak <= 2.0
        and limit_count_5d <= 3.0
        and promoted >= 1.0
        and theme_source_count <= 12.0
    )


def _source_candidate_from_score(
    raw: SignalScore,
    *,
    stock_meta: dict[str, Any],
    sectors: list[str],
    raw_rank: int | None,
) -> SignalScore | None:
    evidence = getattr(raw, "evidence", {}) or {}
    if evidence.get("status") != "ready":
        return None
    if _is_st_name(stock_meta.get("name")):
        return None
    if str(evidence.get("timing_window") or "") != "after_silver_late":
        return None
    if str(evidence.get("market_phase") or "") != "retreat":
        return None
    if float(raw.risk_score or 0.0) < 35.0 or float(raw.liquidity_score or 0.0) < 25.0:
        return None

    subtype = _retreat_momentum_subtype(evidence)
    if subtype is None:
        return None
    score, components = _opportunity_score(raw, subtype=subtype)
    if score < 80.0:
        return None

    source = copy(raw)
    source.total_score = score
    source.entry_signal = True
    source.evidence = {
        **dict(evidence),
        "setup_type": RETREAT_MOMENTUM_SOURCE_LANE,
        "entry_setup": RETREAT_MOMENTUM_SOURCE_LANE,
        "setup_family": RETREAT_MOMENTUM_SOURCE_LANE,
        "entry_family": RETREAT_MOMENTUM_SOURCE_LANE,
        "retreat_momentum_source": True,
        "retreat_momentum_board_survival_source": True,
        "retreat_momentum_subtype": subtype,
        "retreat_momentum_opportunity_score": score,
        "retreat_momentum_score_components": components,
        "retreat_momentum_raw_signal_rank": raw_rank,
        "retreat_momentum_original_setup": evidence.get("entry_setup") or evidence.get("setup_type"),
        "retreat_momentum_original_failed_rules": list(evidence.get("failed_rules") or []),
        "retreat_momentum_sector_names": list(sectors or []),
        "failed_rules": [],
        "raw_entry_signal": True,
        "default_executable_entry_signal": True,
        "executable_entry_signal": True,
        "key_entry_signal": True,
        "action": "BUY",
        "entry_action": "BUY",
        "signal_label": "退潮动量源买点",
        "signal_role": "key_buy",
        "score_notes": list(evidence.get("score_notes") or []) + ["退潮右尾源：板生存确认"],
    }
    return source


def _retreat_momentum_subtype(evidence: dict[str, Any]) -> str | None:
    failed = {str(item) for item in evidence.get("failed_rules") or []}
    strong_leg = _num(evidence.get("strong_leg_score")) or 0.0
    ret5 = _num(evidence.get("return_5d"))
    ret20 = _num(evidence.get("return_20d"))
    ret60 = _num(evidence.get("return_60d"))
    latest_change = _num(evidence.get("latest_change_pct"))
    ma5 = _num(evidence.get("ma5_distance_pct"))
    ma10 = _num(evidence.get("ma10_distance_pct"))
    ma20 = _num(evidence.get("ma20_distance_pct"))
    drawdown = _num(evidence.get("drawdown_from_pivot_pct"))
    pullback_days = _num(evidence.get("pullback_days")) or 0.0
    volume_ratio = _num(evidence.get("volume_ratio_5d_20d"))
    near_limit_count = _num(evidence.get("near_limit_up_count_20d")) or 0.0
    large_bull_count = _num(evidence.get("large_bull_count_20d")) or 0.0
    active_source = bool(evidence.get("recent_limit_up_20d")) or near_limit_count >= 1.0 or large_bull_count >= 1.0
    if volume_ratio is not None and not (0.45 <= volume_ratio <= 3.20):
        return None
    if latest_change is not None and latest_change <= -8.0:
        return None
    if "distribution_risk" in failed:
        return None
    if not (
        active_source
        and strong_leg >= 78.0
        and pullback_days <= 2.0
        and drawdown is not None
        and -10.5 <= drawdown <= 0.5
        and ma5 is not None
        and ma5 >= -2.5
        and ma10 is not None
        and ma10 >= -1.0
        and ma20 is not None
        and ma20 <= 35.0
        and ("pullback_too_short" in failed or "support_acceptance" in failed or "overheat" in failed)
        and (ret5 is None or ret5 <= 35.0)
        and (ret20 is None or ret20 <= 65.0)
        and (ret60 is None or ret60 <= 130.0)
    ):
        return None
    return "active_first_pullback_switch"


def _opportunity_score(raw: SignalScore, *, subtype: str) -> tuple[float, dict[str, float]]:
    evidence = getattr(raw, "evidence", {}) or {}
    strong_leg = _num(evidence.get("strong_leg_score")) or 0.0
    latest_change = _num(evidence.get("latest_change_pct")) or 0.0
    ret5 = _num(evidence.get("return_5d")) or 0.0
    ret20 = _num(evidence.get("return_20d")) or 0.0
    ret60 = _num(evidence.get("return_60d")) or 0.0
    ma20 = _num(evidence.get("ma20_distance_pct")) or 0.0
    volume_ratio = _num(evidence.get("volume_ratio_5d_20d")) or 1.0
    near_limit_count = _num(evidence.get("near_limit_up_count_20d")) or 0.0
    large_bull_count = _num(evidence.get("large_bull_count_20d")) or 0.0
    components = {
        "base": 68.0,
        "subtype": 3.8 if subtype == "active_first_pullback_switch" else 0.0,
        "strong_leg": min(max((strong_leg - 55.0) * 0.10, 0.0), 5.0),
        "latest_change": min(max(latest_change, 0.0) * 0.42, 4.2),
        "recent_return": min(max(ret5, 0.0) * 0.12, 3.2),
        "active_source": min(near_limit_count * 1.0 + large_bull_count * 0.45, 4.0),
        "retreat_phase": 2.6,
        "liquidity": min(float(raw.liquidity_score or 0.0) * 0.035, 2.8),
        "risk": min(float(raw.risk_score or 0.0) * 0.020, 1.8),
    }
    penalty = 0.0
    if ret20 > 45.0:
        penalty += min((ret20 - 45.0) * 0.12, 4.5)
    if ret60 > 90.0:
        penalty += min((ret60 - 90.0) * 0.05, 3.5)
    if ma20 > 32.0:
        penalty += min((ma20 - 32.0) * 0.18, 5.5)
    if volume_ratio > 2.6:
        penalty += min((volume_ratio - 2.6) * 2.0, 2.5)
    components["stretch_penalty"] = -round(penalty, 4)
    score = round(clamp_score(sum(components.values())), 4)
    return score, {key: round(value, 4) for key, value in components.items()}


def _attach_board_quality(
    source_scores: list[SignalScore],
    *,
    visible_bars: dict[str, list[Any]],
    stock_meta: dict[str, dict[str, Any]],
    sector_names: dict[str, list[str]],
) -> None:
    board_state_by_symbol = {
        vt_symbol: _board_state(bars, vt_symbol=vt_symbol, stock_name=(stock_meta.get(vt_symbol) or {}).get("name"))
        for vt_symbol, bars in visible_bars.items()
        if bars
    }
    theme_state = _theme_board_state(board_state_by_symbol, sector_names)
    for score in source_scores:
        evidence = dict(score.evidence or {})
        themes = _meaningful_sectors(evidence.get("retreat_momentum_sector_names"))
        matched = _best_theme_state(themes, theme_state)
        score.evidence = {**evidence, **(board_state_by_symbol.get(str(score.vt_symbol)) or {}), **matched}


def _board_state(bars: list[Any], *, vt_symbol: str, stock_name: Any) -> dict[str, Any]:
    threshold = _limit_threshold_pct(vt_symbol, stock_name)
    states: list[dict[str, Any]] = []
    previous_close: float | None = None
    for bar in bars:
        close = _num(getattr(bar, "close_price", None))
        high = _num(getattr(bar, "high_price", None))
        low = _num(getattr(bar, "low_price", None))
        open_price = _num(getattr(bar, "open_price", None))
        change = _num(getattr(bar, "change_pct", None))
        if change is None and previous_close and close:
            change = (close / previous_close - 1.0) * 100.0
        high_change = (high / previous_close - 1.0) * 100.0 if previous_close and high else None
        close_location = (close - low) / (high - low) if close is not None and high is not None and low is not None and high > low else None
        upper_shadow = max(high - max(open_price, close), 0.0) / close * 100.0 if close and high and open_price is not None else None
        states.append(
            {
                "change": change,
                "high_change": high_change,
                "is_limit_up": bool(change is not None and change >= threshold),
                "touched_limit_up": bool(high_change is not None and high_change >= threshold),
                "near_limit_close": bool(change is not None and change >= threshold - 0.7),
                "close_location": close_location,
                "upper_shadow": upper_shadow,
            }
        )
        if close is not None:
            previous_close = close
    latest = states[-1] if states else {}
    previous = states[-2] if len(states) >= 2 else {}
    streak = 0
    for state in reversed(states):
        if not state.get("is_limit_up"):
            break
        streak += 1
    recent_5 = states[-5:]
    failed_latest = bool(latest.get("touched_limit_up") and not latest.get("is_limit_up"))
    return {
        "board_limit_threshold_pct": threshold,
        "board_change_pct": _round(latest.get("change")),
        "board_high_change_pct": _round(latest.get("high_change")),
        "board_is_limit_up": bool(latest.get("is_limit_up")),
        "board_touched_limit_up": bool(latest.get("touched_limit_up")),
        "board_near_limit_close": bool(latest.get("near_limit_close")),
        "board_failed_limit_up": failed_latest,
        "board_previous_is_limit_up": bool(previous.get("is_limit_up")),
        "board_close_location_in_range": _round(latest.get("close_location")),
        "board_upper_shadow_pct": _round(latest.get("upper_shadow")),
        "board_limit_up_streak": streak,
        "board_limit_up_count_5d": sum(1 for state in recent_5 if state.get("is_limit_up")),
        "board_failed_limit_up_count_5d": sum(1 for state in recent_5 if state.get("touched_limit_up") and not state.get("is_limit_up")),
    }


def _theme_board_state(
    board_state_by_symbol: dict[str, dict[str, Any]],
    sector_names: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for vt_symbol, state in board_state_by_symbol.items():
        for theme in _meaningful_sectors(sector_names.get(vt_symbol, [])):
            grouped[theme].append(state)
    result: dict[str, dict[str, Any]] = {}
    for theme, states in grouped.items():
        changes = [_num(state.get("board_change_pct")) for state in states]
        changes = [value for value in changes if value is not None]
        limit_up = sum(1 for state in states if state.get("board_is_limit_up"))
        failed = sum(1 for state in states if state.get("board_failed_limit_up"))
        touched = sum(1 for state in states if state.get("board_touched_limit_up"))
        previous_limit = sum(1 for state in states if state.get("board_previous_is_limit_up"))
        promoted = sum(1 for state in states if state.get("board_previous_is_limit_up") and state.get("board_is_limit_up"))
        first = sum(1 for state in states if state.get("board_is_limit_up") and not state.get("board_previous_is_limit_up"))
        result[theme] = {
            "board_theme_name": theme,
            "board_theme_member_count": len(states),
            "board_theme_avg_change_pct": _round(sum(changes) / len(changes)) if changes else None,
            "board_theme_limit_up_count": limit_up,
            "board_theme_touched_limit_up_count": touched,
            "board_theme_failed_limit_up_count": failed,
            "board_theme_previous_limit_up_count": previous_limit,
            "board_theme_promoted_limit_up_count": promoted,
            "board_theme_first_limit_up_count": first,
            "board_theme_limit_up_ratio_pct": _round(limit_up / len(states) * 100.0) if states else 0.0,
            "board_theme_failed_to_limit_ratio": _round(failed / max(limit_up, 1)),
        }
    return result


def _best_theme_state(themes: list[str], states: dict[str, dict[str, Any]]) -> dict[str, Any]:
    candidates = [states[theme] for theme in themes if theme in states]
    if not candidates:
        return {}
    return dict(
        sorted(
            candidates,
            key=lambda state: (
                -int(state.get("board_theme_limit_up_count") or 0),
                -int(state.get("board_theme_promoted_limit_up_count") or 0),
                float(state.get("board_theme_failed_to_limit_ratio") or 0.0),
                str(state.get("board_theme_name") or ""),
            ),
        )[0]
    )


def _attach_theme_confirmation(source_scores: list[SignalScore]) -> None:
    sector_counts: dict[str, int] = defaultdict(int)
    for score in source_scores:
        for sector in _meaningful_sectors((score.evidence or {}).get("retreat_momentum_sector_names")):
            sector_counts[sector] += 1
    for score in source_scores:
        evidence = dict(score.evidence or {})
        sectors = _meaningful_sectors(evidence.get("retreat_momentum_sector_names"))
        best = sorted(
            ((sector, sector_counts.get(sector, 0)) for sector in sectors if 3 <= sector_counts.get(sector, 0) <= 35),
            key=lambda item: (-item[1], item[0]),
        )
        score.evidence = {
            **evidence,
            "retreat_momentum_theme_confirmed": bool(best),
            "retreat_momentum_theme_name": best[0][0] if best else None,
            "retreat_momentum_theme_count": best[0][1] if best else 0,
        }
        if best:
            boosted = min(float(score.total_score or 0.0) + min(best[0][1] * 0.35, 2.8), 100.0)
            score.total_score = round(boosted, 4)
            score.evidence["retreat_momentum_opportunity_score"] = round(boosted, 4)


def _attach_cross_section_stats(source_scores: list[SignalScore]) -> None:
    by_theme: dict[str, list[SignalScore]] = defaultdict(list)
    for score in source_scores:
        theme = str((score.evidence or {}).get("retreat_momentum_theme_name") or "")
        if theme:
            by_theme[theme].append(score)
    for theme_scores in by_theme.values():
        ordered = sorted(theme_scores, key=lambda score: (-float(score.total_score or 0.0), str(score.vt_symbol)))
        count = len(ordered)
        for rank, score in enumerate(ordered, start=1):
            score.evidence = {
                **dict(score.evidence or {}),
                "retreat_momentum_theme_source_rank": rank,
                "retreat_momentum_theme_source_count": count,
            }


def _meaningful_sectors(raw: Any) -> list[str]:
    values = raw if isinstance(raw, list) else []
    result: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if "(theme)" not in text:
            continue
        name = text.split("(", 1)[0].strip()
        if name and not _is_generic_sector_name(name) and name not in result:
            result.append(name)
    return result[:8]


def _is_generic_sector_name(name: str) -> bool:
    return any(
        part in name
        for part in (
            "融资融券",
            "融券",
            "沪股通",
            "深股通",
            "富时罗素",
            "标准普尔",
            "机构重仓",
            "基金重仓",
            "QFII重仓",
            "中盘股",
            "小盘股",
            "小盘成长",
            "大盘股",
            "低价股",
            "百元股",
            "破发股",
            "破净股",
            "破增发价",
            "深成",
            "MSCI",
            "央国企改革",
            "西部大开发",
            "一带一路",
            "长江三角",
            "深圳特区",
            "AH股",
            "AB股",
            "参股保险",
            "中证",
            "上证",
            "昨日",
            "新能源",
            "最近多板",
            "趋势股",
            "次新股",
            "专精特新",
            "贬值受益",
            "北交所概念",
            "创投",
            "PPP模式",
            "2025年报",
            "2026一季报",
            "转债标的",
        )
    )


def _load_stock_meta(session: Any | None, symbols: list[str]) -> dict[str, dict[str, Any]]:
    if session is None or not hasattr(session, "execute") or not symbols:
        return {}
    rows = session.execute(select(schema.stocks).where(schema.stocks.c.vt_symbol.in_(symbols))).mappings().all()
    return {str(row["vt_symbol"]): dict(row) for row in rows}


def _load_sector_names(session: Any | None, symbols: list[str]) -> dict[str, list[str]]:
    if session is None or not hasattr(session, "execute") or not symbols:
        return {}
    rows = session.execute(
        select(
            schema.stock_sector_memberships.c.vt_symbol,
            schema.stock_sector_memberships.c.sector_name,
            schema.stock_sector_memberships.c.sector_type,
        )
        .where(schema.stock_sector_memberships.c.vt_symbol.in_(symbols))
        .order_by(schema.stock_sector_memberships.c.vt_symbol, schema.stock_sector_memberships.c.rank.nullslast())
    ).mappings().all()
    result: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        label = f"{row['sector_name']}({row['sector_type']})" if row.get("sector_type") else str(row["sector_name"])
        result[str(row["vt_symbol"])].append(label)
    return dict(result)


def _limit_threshold_pct(vt_symbol: str, stock_name: Any) -> float:
    symbol = str(vt_symbol or "").upper()
    if _is_st_name(stock_name):
        return 4.5
    if symbol.startswith(("8", "4", "920")) or symbol.endswith(".BSE") or symbol.endswith(".BJSE"):
        return 29.0
    if symbol.startswith(("30", "68")):
        return 19.0
    return 9.5


def _num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: Any, digits: int = 4) -> float | None:
    number = _num(value)
    return round(number, digits) if number is not None else None


def _is_st_name(name: Any) -> bool:
    return "ST" in str(name or "").upper()
