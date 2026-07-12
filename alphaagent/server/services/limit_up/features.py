"""No-lookahead feature construction for limit-up candidates."""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from datetime import date
from statistics import mean
from typing import Mapping, Sequence

from alphaagent.server.services.limit_up.domain import normalize_limit_time, percentile_ranks


def timing_snapshot_as_of(
    signals: Sequence[Mapping[str, object]],
    as_of_date: str | date | None,
) -> dict[str, object]:
    """Return what was knowable about gold/silver signals by ``as_of_date``.

    A signal candidate exists on its candidate date, but its final status is not
    knowable until ``confirm_date``.  This conversion prevents a historical
    INVALIDATED/CONFIRMED label from leaking into the prior trading day.
    """

    cutoff = _date_text(as_of_date)
    if cutoff is None:
        return _empty_timing_snapshot(None)

    visible: list[dict[str, object]] = []
    for raw in signals:
        signal_date = _date_text(raw.get("date") or raw.get("trade_date"))
        if signal_date is None or signal_date > cutoff:
            continue
        confirm_date = _date_text(raw.get("confirm_date"))
        stored_status = str(raw.get("status") or "PENDING").upper()
        if confirm_date is not None and confirm_date > cutoff:
            as_of_status = "PENDING"
        elif confirm_date is None and stored_status in {"CONFIRMED", "INVALIDATED"}:
            as_of_status = stored_status
        else:
            as_of_status = stored_status
        visible.append(
            {
                **dict(raw),
                "date": signal_date,
                "confirm_date": confirm_date,
                "as_of_status": as_of_status,
            }
        )

    visible.sort(key=lambda item: (str(item["date"]), str(item.get("confirm_date") or "")))
    confirmed = [item for item in visible if item["as_of_status"] == "CONFIRMED"]
    latest_candidate = visible[-1] if visible else None
    last_confirmed = confirmed[-1] if confirmed else None
    last_gold = next(
        (item for item in reversed(confirmed) if str(item.get("direction")) == "GOLD"),
        None,
    )
    last_silver = next(
        (item for item in reversed(confirmed) if str(item.get("direction")) == "SILVER"),
        None,
    )
    return {
        "as_of_date": cutoff,
        "last_confirmed_direction": (last_confirmed or {}).get("direction"),
        "last_confirmed_signal": last_confirmed,
        "latest_candidate": latest_candidate,
        "last_gold_date": (last_gold or {}).get("confirm_date") or (last_gold or {}).get("date"),
        "last_silver_date": (last_silver or {}).get("confirm_date") or (last_silver or {}).get("date"),
        "visible_signal_count": len(visible),
    }


def market_snapshot_for_trade(
    trade_date: str | date,
    prior_trade_date: str | date | None,
    sentiment_points: Sequence[Mapping[str, object]],
    timing_signals: Sequence[Mapping[str, object]],
    trading_dates: Sequence[str] | None = None,
) -> dict[str, object]:
    """Build the D-day market context using only the prior close."""

    trade_text = _date_text(trade_date)
    prior_text = _date_text(prior_trade_date)
    sentiment = next(
        (
            dict(point)
            for point in sentiment_points
            if _date_text(point.get("date") or point.get("trade_date")) == prior_text
        ),
        None,
    )
    timing = timing_snapshot_as_of(timing_signals, prior_text)
    calendar = sorted({_date_text(item) for item in trading_dates or [] if _date_text(item)})
    timing["trading_days_since_gold"] = _trading_day_distance(
        calendar,
        _date_text(timing.get("last_gold_date")),
        prior_text,
    )
    timing["trading_days_since_silver"] = _trading_day_distance(
        calendar,
        _date_text(timing.get("last_silver_date")),
        prior_text,
    )
    _attach_timing_freshness(timing)
    return {
        "trade_date": trade_text,
        "sentiment_date": prior_text if sentiment is not None else None,
        "sentiment": sentiment,
        "timing": timing,
        "data_cutoff": "D-1_CLOSE",
        "available_at": "D日开盘前",
    }


def sector_score_index(
    rows: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str], dict[str, object]]:
    result: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        score_date = _date_text(row.get("as_of_date"))
        sector_id = str(row.get("sector_id") or "")
        if score_date and sector_id:
            result[(score_date, sector_id)] = dict(row)
    return result


def prior_stock_features(
    bars: Sequence[Mapping[str, object]],
    trade_date: str,
    *,
    assume_sorted: bool = False,
) -> dict[str, float | str | None]:
    ordered = bars if assume_sorted else sorted(
        bars,
        key=lambda row: str(row.get("trade_date") or ""),
    )
    index = _sorted_bar_index(ordered, trade_date)
    if index is None or index <= 0:
        return _empty_prior_stock_features()
    prior = ordered[index - 1]
    history = ordered[max(0, index - 6) : index - 1]
    history_turnover = [_number(row.get("turnover")) for row in history]
    usable_turnover = [value for value in history_turnover if value is not None and value > 0]
    prior_turnover = _number(prior.get("turnover"))
    average_turnover = mean(usable_turnover) if usable_turnover else None
    close_now = _number(prior.get("close_price"))
    close_base = _number(ordered[max(0, index - 6)].get("close_price")) if index >= 2 else None
    return {
        "prior_trade_date": _date_text(prior.get("trade_date")),
        "prior_turnover": prior_turnover,
        "prior_turnover_rate": _number(prior.get("turnover_rate")),
        "prior_turnover_ratio_5d": _ratio(prior_turnover, average_turnover),
        "prior_return_5d_pct": (
            round((close_now / close_base - 1) * 100, 4)
            if close_now is not None and close_base
            else None
        ),
        "prior_change_pct": _number(prior.get("change_pct")),
    }


def close_stock_features(
    bars: Sequence[Mapping[str, object]],
    trade_date: str,
    *,
    assume_sorted: bool = False,
) -> dict[str, float | None]:
    ordered = bars if assume_sorted else sorted(
        bars,
        key=lambda row: str(row.get("trade_date") or ""),
    )
    index = _sorted_bar_index(ordered, trade_date)
    if index is None:
        return {"d_turnover_ratio_5d": None, "d_turnover": None, "d_turnover_rate": None}
    current = ordered[index]
    history = ordered[max(0, index - 5) : index]
    turnovers = [_number(row.get("turnover")) for row in history]
    usable = [value for value in turnovers if value is not None and value > 0]
    current_turnover = _number(current.get("turnover"))
    return {
        "d_turnover_ratio_5d": _ratio(current_turnover, mean(usable) if usable else None),
        "d_turnover": current_turnover,
        "d_turnover_rate": _number(current.get("turnover_rate")),
    }


def _sorted_bar_index(
    bars: Sequence[Mapping[str, object]],
    trade_date: str,
) -> int | None:
    index = bisect_left(
        bars,
        trade_date,
        key=lambda row: _date_text(row.get("trade_date")) or "",
    )
    if index >= len(bars) or _date_text(bars[index].get("trade_date")) != trade_date:
        return None
    return index


def intraday_observation_features(
    candidates: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    """Describe the ladder visible when the latest candidates first touch limit."""

    sector_counts = Counter(str(item.get("sector_id") or "") for item in candidates)
    level_counts = Counter(int(item.get("signal_board_level") or 1) for item in candidates)
    ordered = sorted(
        candidates,
        key=lambda item: (
            normalize_limit_time(item.get("first_limit_time")) or "99:99:99",
            str(item.get("vt_symbol") or ""),
        ),
    )
    order_by_symbol = {
        str(item.get("vt_symbol") or ""): index
        for index, item in enumerate(ordered, start=1)
    }
    total = len(candidates)
    max_level = max(level_counts, default=0)
    result: dict[str, dict[str, object]] = {}
    for item in candidates:
        symbol = str(item.get("vt_symbol") or "")
        sector_id = str(item.get("sector_id") or "")
        sector_count = sector_counts.get(sector_id, 0)
        result[symbol] = {
            "observed_touch_count": total,
            "market_touch_order": order_by_symbol.get(symbol),
            "observed_sector_touch_count": sector_count,
            "observed_sector_touch_share": round(sector_count / total, 4) if total else None,
            "observed_sector_count": len([key for key in sector_counts if key]),
            "observed_max_board_level": max_level,
            "observed_board_ladder": {
                _board_level_key(level): count
                for level, count in sorted(level_counts.items())
            },
            "available_at": "D日首次触板时",
        }
    return result


def score_pretrade_candidates(
    candidates: Sequence[Mapping[str, object]],
    sector_flow_map: Mapping[str, Mapping[str, object]],
    sector_scores: Mapping[str, Mapping[str, object]],
    market_snapshot: Mapping[str, object],
) -> list[dict[str, object]]:
    """Score candidates exclusively from D-1 and first-touch observable fields."""

    copied = [dict(item) for item in candidates]
    sector_heat_values = {
        str(item.get("vt_symbol") or ""): _number(
            sector_scores.get(str(item.get("sector_id") or ""), {}).get("heat_score")
        )
        for item in copied
    }
    sector_flow_values = {
        str(item.get("vt_symbol") or ""): _number(
            sector_flow_map.get(str(item.get("sector_id") or ""), {}).get("main_net_inflow")
        )
        for item in copied
    }
    liquidity_values = {
        str(item.get("vt_symbol") or ""): _number(
            (item.get("prior_stock") or {}).get("prior_turnover")
            if isinstance(item.get("prior_stock"), Mapping)
            else None
        )
        for item in copied
    }
    stock_flow_values = {
        str(item.get("vt_symbol") or ""): _number(
            (item.get("prior_stock_flow") or {}).get("main_net_inflow")
            if isinstance(item.get("prior_stock_flow"), Mapping)
            else None
        )
        for item in copied
    }
    heat_ranks = percentile_ranks(sector_heat_values)
    flow_ranks = percentile_ranks(sector_flow_values)
    liquidity_ranks = percentile_ranks(liquidity_values)
    stock_flow_ranks = percentile_ranks(stock_flow_values)
    sentiment = market_snapshot.get("sentiment")
    sentiment = sentiment if isinstance(sentiment, Mapping) else {}
    timing = market_snapshot.get("timing")
    timing = timing if isinstance(timing, Mapping) else {}
    phase_quality = _phase_quality(str(sentiment.get("phase") or ""))
    timing_quality = _timing_quality(timing)

    for item in copied:
        symbol = str(item.get("vt_symbol") or "")
        sector_id = str(item.get("sector_id") or "")
        sector_score = dict(sector_scores.get(sector_id, {}))
        prior_stock = item.get("prior_stock")
        prior_stock = prior_stock if isinstance(prior_stock, Mapping) else {}
        intraday = item.get("intraday")
        intraday = intraday if isinstance(intraday, Mapping) else {}
        prior_stock_flow = item.get("prior_stock_flow")
        prior_stock_flow = prior_stock_flow if isinstance(prior_stock_flow, Mapping) else {}
        board_level = int(item.get("signal_board_level") or 1)
        heat_score = _number(sector_score.get("heat_score"))
        trend_state = str(sector_score.get("trend_state") or "")
        sector_flow = sector_flow_map.get(sector_id, {})
        sector_flow_amount = _number(sector_flow.get("main_net_inflow"))
        sector_flow_ratio = _number(sector_flow.get("main_net_inflow_ratio"))
        stock_flow_amount = _number(prior_stock_flow.get("main_net_inflow"))
        stock_flow_ratio = _number(prior_stock_flow.get("main_net_inflow_ratio"))
        target_promotion_rate = promotion_rate_for_board(sentiment, board_level)
        prior_turnover_ratio = _number(prior_stock.get("prior_turnover_ratio_5d"))
        sector_heat_quality = _sector_heat_quality(heat_score, trend_state)
        sector_flow_quality = _fund_flow_quality(
            sector_flow_amount,
            sector_flow_ratio,
            flow_ranks[symbol],
        )
        stock_flow_quality = _fund_flow_quality(
            stock_flow_amount,
            stock_flow_ratio,
            stock_flow_ranks[symbol],
        )
        components = {
            "sector_heat": round(20 * (0.8 * sector_heat_quality + 0.2 * heat_ranks[symbol]), 4),
            "prior_sector_flow": round(12 * sector_flow_quality, 4),
            "market_phase": round(12 * phase_quality, 4),
            "gold_silver": round(8 * timing_quality, 4),
            "board_position": round(10 * _position_quality(board_level), 4),
            "board_success": round(10 * _promotion_quality(target_promotion_rate), 4),
            "sector_expansion": round(10 * _expansion_quality(intraday), 4),
            "prior_stock_flow": round(8 * stock_flow_quality, 4),
            "prior_turnover": round(5 * _relative_turnover_quality(prior_turnover_ratio), 4),
            "prior_liquidity": round(2 * liquidity_ranks[symbol], 4),
            "first_touch": round(3 * _first_touch_quality(item.get("first_limit_time")), 4),
        }
        gates = _pretrade_gates(
            phase=str(sentiment.get("phase") or ""),
            board_level=board_level,
            heat_score=heat_score,
            trend_state=trend_state,
            sector_flow_amount=sector_flow_amount,
            sector_flow_ratio=sector_flow_ratio,
            sector_touch_count=int(intraday.get("observed_sector_touch_count") or 0),
        )
        item["dragon_score"] = round(sum(components.values()), 4)
        item["score_components"] = components
        item["pretrade_gates"] = gates
        item["pretrade_gate_passed"] = all(row["status"] == "pass" for row in gates)
        item["market_context"] = dict(market_snapshot)
        item["prior_sector_score"] = sector_score or None
        item["prior_sector_heat_score"] = heat_score
        item["prior_sector_trend_state"] = sector_score.get("trend_state")
        item["prior_sector_main_net_inflow"] = sector_flow_amount
        item["prior_sector_main_net_inflow_ratio"] = sector_flow_ratio
        item["prior_stock_main_net_inflow"] = stock_flow_amount
        item["prior_stock_main_net_inflow_ratio"] = stock_flow_ratio
        item["target_board_promotion_rate"] = target_promotion_rate
        item["sector_heat_percentile"] = round(heat_ranks[symbol], 4)
        item["sector_flow_percentile"] = round(flow_ranks[symbol], 4)
        item["prior_stock_flow_percentile"] = round(stock_flow_ranks[symbol], 4)
        item["prior_liquidity_percentile"] = round(liquidity_ranks[symbol], 4)
        item["pretrade_data_confidence"] = _pretrade_data_confidence(
            heat_score,
            sector_flow_amount,
            target_promotion_rate,
            _number(prior_stock.get("prior_turnover")),
            stock_flow_amount,
        )
        item["pretrade_feature_stage"] = "D-1_CLOSE_AND_D_FIRST_TOUCH"
    return copied


def promotion_rate_for_board(
    sentiment: Mapping[str, object] | None,
    board_level: int,
) -> float | None:
    if not sentiment:
        return None
    ladder = sentiment.get("promotion_ladder")
    if not isinstance(ladder, Mapping):
        return None
    key = {
        1: "first_board",
        2: "one_to_two",
        3: "two_to_three",
    }.get(board_level, "three_plus")
    row = ladder.get(key)
    return _number(row.get("rate")) if isinstance(row, Mapping) else None


def _phase_quality(phase: str) -> float:
    return {
        "mainrise": 1.0,
        "uptrend": 1.0,
        "repair": 0.85,
        "divergence": 0.55,
        "climax": 0.40,
        "ice": 0.20,
        "ebb": 0.15,
    }.get(phase, 0.30)


def _timing_quality(timing: Mapping[str, object]) -> float:
    latest = timing.get("latest_candidate")
    if isinstance(latest, Mapping) and latest.get("as_of_status") == "PENDING":
        return 0.70 if latest.get("direction") == "GOLD" else 0.25
    state = str(timing.get("signal_state") or "")
    if state == "GOLD_ACTIVE":
        return 0.90
    if state == "SILVER_ACTIVE":
        return 0.20
    if state == "GOLD_FADING":
        return 0.70
    if state == "SILVER_FADING":
        return 0.35
    return 0.50


def _position_quality(level: int) -> float:
    if level == 1:
        return 0.80
    if level == 2:
        return 1.00
    if level == 3:
        return 0.75
    return 0.50


def _expansion_quality(intraday: Mapping[str, object]) -> float:
    count = int(intraday.get("observed_sector_touch_count") or 0)
    if count >= 3:
        return 1.0
    if count == 2:
        return 0.70
    if count == 1:
        return 0.35
    return 0.0


def _first_touch_quality(value: object) -> float:
    text = normalize_limit_time(value)
    if text is None:
        return 0.0
    if text <= "09:31:00":
        return 0.45
    if text <= "10:00:00":
        return 1.0
    if text <= "11:30:00":
        return 0.85
    if text <= "14:00:00":
        return 0.65
    return 0.35


def _trading_day_distance(calendar: Sequence[str], start: str | None, end: str | None) -> int | None:
    if start is None or end is None:
        return None
    calendar_distance = None
    if calendar and start in calendar and end in calendar:
        calendar_distance = max(calendar.index(end) - calendar.index(start), 0)
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError:
        return calendar_distance
    weekday_distance = sum(
        1
        for offset in range(1, max((end_date - start_date).days, 0) + 1)
        if date.fromordinal(start_date.toordinal() + offset).weekday() < 5
    )
    return max(calendar_distance or 0, weekday_distance)


def _attach_timing_freshness(timing: dict[str, object]) -> None:
    direction = str(timing.get("last_confirmed_direction") or "")
    age_key = "trading_days_since_gold" if direction == "GOLD" else "trading_days_since_silver"
    age = _integer(timing.get(age_key)) if direction in {"GOLD", "SILVER"} else None
    timing["signal_age_trade_days"] = age
    timing["active_direction"] = direction if age is not None and age <= 5 else None
    if direction not in {"GOLD", "SILVER"} or age is None:
        timing["signal_state"] = "NONE"
    elif age <= 5:
        timing["signal_state"] = f"{direction}_ACTIVE"
    elif age <= 10:
        timing["signal_state"] = f"{direction}_FADING"
    else:
        timing["signal_state"] = "STALE"


def _sector_heat_quality(heat_score: float | None, trend_state: str) -> float:
    if heat_score is None:
        return 0.0
    heat_quality = min(max((heat_score - 40.0) / 40.0, 0.0), 1.0)
    trend_quality = {
        "MAINLINE_UP": 1.0,
        "FAST_UP": 0.9,
        "ROTATION": 0.65,
        "FADING": 0.25,
        "WEAK": 0.0,
    }.get(trend_state, 0.2)
    return 0.75 * heat_quality + 0.25 * trend_quality


def _fund_flow_quality(
    amount: float | None,
    ratio: float | None,
    percentile: float,
) -> float:
    if amount is None and ratio is None:
        return 0.20
    amount_quality = 1.0 if amount is not None and amount > 0 else 0.0
    ratio_quality = 1.0 if ratio is not None and ratio > 0 else 0.0
    absolute_quality = (amount_quality + ratio_quality) / 2
    return min(max(0.8 * absolute_quality + 0.2 * percentile, 0.0), 1.0)


def _promotion_quality(rate: float | None) -> float:
    if rate is None:
        return 0.30
    return min(max(rate / 0.40, 0.0), 1.0)


def _relative_turnover_quality(ratio: float | None) -> float:
    if ratio is None:
        return 0.20
    if 0.70 <= ratio <= 1.30:
        return 1.0
    if 0.50 <= ratio < 0.70 or 1.30 < ratio <= 1.80:
        return 0.65
    if ratio < 0.35 or ratio > 2.50:
        return 0.10
    return 0.35


def _pretrade_gates(
    *,
    phase: str,
    board_level: int,
    heat_score: float | None,
    trend_state: str,
    sector_flow_amount: float | None,
    sector_flow_ratio: float | None,
    sector_touch_count: int,
) -> list[dict[str, object]]:
    market_allowed = phase not in {"ice", "ebb", ""}
    sector_hot = bool(
        heat_score is not None
        and heat_score >= 60
        and trend_state in {"MAINLINE_UP", "FAST_UP", "ROTATION"}
    )
    positive_flow = bool(
        (sector_flow_amount is not None and sector_flow_amount > 0)
        or (sector_flow_ratio is not None and sector_flow_ratio > 0)
    )
    sector_confirmed = sector_touch_count >= 2 or bool(
        heat_score is not None and heat_score >= 75 and positive_flow
    )
    return [
        _gate("market_phase", "情绪准入", market_allowed, phase or "缺失"),
        _gate(
            "sector_hot",
            "热门板块",
            sector_hot,
            f"热度{heat_score:.1f}/{trend_state}" if heat_score is not None else "热度缺失",
        ),
        _gate("sector_flow", "板块资金", positive_flow, _flow_detail(sector_flow_amount, sector_flow_ratio)),
        _gate("sector_confirmation", "板块共振", sector_confirmed, f"触板{sector_touch_count}只"),
        _gate("board_level", "板位约束", board_level <= 2, f"{board_level}板"),
    ]


def _gate(code: str, label: str, passed: bool, detail: str) -> dict[str, object]:
    return {"code": code, "label": label, "status": "pass" if passed else "fail", "detail": detail}


def _flow_detail(amount: float | None, ratio: float | None) -> str:
    if amount is not None:
        return f"{amount / 100_000_000:+.2f}亿"
    if ratio is not None:
        return f"{ratio:+.2f}%"
    return "资金缺失"


def _pretrade_data_confidence(*values: float | None) -> float:
    return round(sum(value is not None for value in values) / len(values), 4)


def _integer(value: object) -> int | None:
    try:
        return int(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _empty_timing_snapshot(as_of_date: str | None) -> dict[str, object]:
    return {
        "as_of_date": as_of_date,
        "last_confirmed_direction": None,
        "last_confirmed_signal": None,
        "latest_candidate": None,
        "last_gold_date": None,
        "last_silver_date": None,
        "visible_signal_count": 0,
    }


def _empty_prior_stock_features() -> dict[str, float | str | None]:
    return {
        "prior_trade_date": None,
        "prior_turnover": None,
        "prior_turnover_rate": None,
        "prior_turnover_ratio_5d": None,
        "prior_return_5d_pct": None,
        "prior_change_pct": None,
    }


def _board_level_key(level: int) -> str:
    return {1: "first_board", 2: "one_to_two", 3: "two_to_three"}.get(level, "three_plus")


def _date_text(value: object) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10] if len(text) >= 10 else None


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    return round(numerator / denominator, 4) if numerator is not None and denominator else None
