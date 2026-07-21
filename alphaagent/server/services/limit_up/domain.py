"""Pure rules for limit-up event ranking and proxy execution."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from decimal import Decimal, ROUND_HALF_UP
from math import prod
from statistics import mean, median

from alphaagent.server.services.a_share_universe import (
    is_eligible_main_board as is_eligible_main_board,
)

FILL_SCENARIOS = {"conservative", "optimistic"}
FAST_BOARD_CUTOFF = "09:31:00"
EVENT_CLOSE_ABS_TOLERANCE = 0.02
EVENT_CLOSE_RELATIVE_TOLERANCE = 0.001
EVENT_CHANGE_TOLERANCE_PCT = 0.6

D1_OUTCOME_LABELS = {
    "awaiting_d1_bar": "待 D+1",
    "entry_price_missing": "买入价缺失",
    "continuation_limit_up": "D+1 连板",
    "next_limit_up_after_failed_board": "D+1 涨停（前日炸板）",
    "close_premium": "D+1 收盘溢价",
    "high_open_dump": "高开冲高回落",
    "rush_and_fall": "冲高回落",
    "direct_breakdown": "低开闷杀",
    "low_open_weak": "低开走弱",
    "intraday_premium_lost": "曾有溢价未守住",
    "no_premium": "D+1 无溢价",
}


def normalize_limit_time(value: object) -> str | None:
    """Normalize provider time values to HH:MM:SS."""

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    digits = "".join(character for character in text if character.isdigit())
    if not digits:
        return None
    digits = digits.zfill(6)[-6:]
    return f"{digits[:2]}:{digits[2:4]}:{digits[4:]}"


def event_fill_status(event: Mapping[str, object], scenario: str) -> str:
    """Classify a touch-time order fill proxy.

    An open count proves that the board opened after a touch, but it does not
    prove that a later reseal occurred.  Reseal evidence is classified
    separately by :func:`reseal_observation_status`.
    """

    if scenario not in FILL_SCENARIOS:
        raise ValueError(f"Unsupported fill scenario: {scenario}")
    first_limit_time = normalize_limit_time(event.get("first_limit_time"))
    open_times = _int_value(event.get("open_times"))
    if first_limit_time and first_limit_time <= FAST_BOARD_CUTOFF and open_times == 0:
        return "unfilled_fast_board"
    if scenario == "conservative" and open_times <= 0:
        return "unfilled_queue_unknown"
    if scenario == "conservative":
        return "filled_first_open_proxy"
    return "filled_non_fast_proxy"


def reseal_observation_status(event: Mapping[str, object]) -> str:
    """Describe whether the daily event record can prove a later reseal."""

    open_times = _int_value(event.get("open_times"))
    if open_times <= 0:
        return "no_reseal_observed"
    first_limit_time = normalize_limit_time(event.get("first_limit_time"))
    last_limit_time = normalize_limit_time(event.get("last_limit_time"))
    if first_limit_time and last_limit_time and last_limit_time > first_limit_time:
        return "reseal_observed_queue_unknown"
    return "reseal_path_unverifiable"


def event_matches_daily_bar(
    event: Mapping[str, object],
    daily_bar: Mapping[str, object],
) -> bool:
    """Reject a limit-up snapshot when its final price conflicts with daily bars."""

    event_close = _optional_float(event.get("close_price"))
    daily_close = _optional_float(daily_bar.get("close_price"))
    if event_close is not None and daily_close is not None:
        close_tolerance = max(
            EVENT_CLOSE_ABS_TOLERANCE,
            abs(daily_close) * EVENT_CLOSE_RELATIVE_TOLERANCE,
        )
        if abs(event_close - daily_close) > close_tolerance:
            return False

    event_change = _optional_float(event.get("change_pct"))
    daily_change = _optional_float(daily_bar.get("change_pct"))
    return (
        event_change is None
        or daily_change is None
        or abs(event_change - daily_change) <= EVENT_CHANGE_TOLERANCE_PCT
    )


def main_board_limit_price(previous_close: float) -> float:
    """Calculate a 10cm limit price using half-up cent rounding."""

    price = Decimal(str(previous_close)) * Decimal("1.10")
    return float(price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def analyze_d1_outcome(
    signal_bar: Mapping[str, object] | None,
    next_bar: Mapping[str, object] | None,
    *,
    entry_price: float | None,
    total_cost_rate: float = 0.0,
    signal_was_sealed: bool | None = None,
) -> dict[str, object]:
    """Classify the next trading day from a limit-up buyer's perspective.

    This is a price-path label, not a causal claim.  It deliberately keeps the
    classification independent of end-of-day seal fields so it can be used for
    both historical review and proxy-backtest outcome attribution.
    """

    if entry_price is None or entry_price <= 0:
        return _d1_outcome("entry_price_missing")
    if next_bar is None:
        return _d1_outcome("awaiting_d1_bar")

    open_price = _optional_float(next_bar.get("open_price"))
    high_price = _optional_float(next_bar.get("high_price"))
    low_price = _optional_float(next_bar.get("low_price"))
    close_price = _optional_float(next_bar.get("close_price"))
    returns = {
        "open_return_pct": _gross_return_pct(entry_price, open_price),
        "high_return_pct": _gross_return_pct(entry_price, high_price),
        "low_return_pct": _gross_return_pct(entry_price, low_price),
        "close_return_pct": _gross_return_pct(entry_price, close_price),
        "open_net_return_pct": _net_return_pct(entry_price, open_price, total_cost_rate),
        "close_net_return_pct": _net_return_pct(entry_price, close_price, total_cost_rate),
    }
    signal_close = _optional_float((signal_bar or {}).get("close_price"))
    next_limit_price = main_board_limit_price(signal_close) if signal_close else None
    is_continuation = bool(
        close_price
        and next_limit_price
        and close_price >= next_limit_price - max(0.02, next_limit_price * 0.001)
    )
    open_return = returns["open_return_pct"]
    high_return = returns["high_return_pct"]
    close_return = returns["close_return_pct"]

    if is_continuation:
        outcome_code = (
            "continuation_limit_up"
            if signal_was_sealed is not False
            else "next_limit_up_after_failed_board"
        )
    elif _at_most(open_return, -3.0) and _at_most(close_return, -3.0):
        outcome_code = "direct_breakdown"
    elif _above(open_return, 0.0) and _at_least(high_return, 3.0) and _at_most(close_return, 0.0):
        outcome_code = "high_open_dump"
    elif _at_least(high_return, 3.0) and _at_most(close_return, 0.0):
        outcome_code = "rush_and_fall"
    elif _above(close_return, 0.0):
        outcome_code = "close_premium"
    elif _above(high_return, 0.0):
        outcome_code = "intraday_premium_lost"
    elif _at_most(open_return, 0.0) and _at_most(close_return, 0.0):
        outcome_code = "low_open_weak"
    else:
        outcome_code = "no_premium"

    return {
        **_d1_outcome(outcome_code),
        "next_limit_price": next_limit_price,
        "next_open_price": open_price,
        "next_high_price": high_price,
        "next_low_price": low_price,
        "next_close_price": close_price,
        **returns,
    }


def percentile_ranks(values: Mapping[str, float | None]) -> dict[str, float]:
    """Return ascending 0..1 percentile ranks, with missing values at zero."""

    available = [(key, float(value)) for key, value in values.items() if value is not None]
    if not available:
        return {key: 0.0 for key in values}
    sorted_values = sorted({value for _, value in available})
    denominator = max(len(sorted_values) - 1, 1)
    rank_by_value = {
        value: (index / denominator if len(sorted_values) > 1 else 1.0)
        for index, value in enumerate(sorted_values)
    }
    return {
        key: rank_by_value.get(float(value), 0.0) if value is not None else 0.0
        for key, value in values.items()
    }


def rank_dragon_candidates(
    events: list[dict[str, object]],
    *,
    limit: int = 5,
) -> list[dict[str, object]]:
    """Keep each sector's top two candidates, then return the market TopN."""

    by_sector: dict[str, list[dict[str, object]]] = defaultdict(list)
    for event in events:
        sector_id = str(event.get("sector_id") or "")
        if sector_id:
            by_sector[sector_id].append(dict(event))

    front_rows: list[dict[str, object]] = []
    for sector_events in by_sector.values():
        ordered = sorted(sector_events, key=_dragon_sort_key)
        for sector_rank, event in enumerate(ordered[:2], start=1):
            event["sector_dragon_rank"] = sector_rank
            front_rows.append(event)

    market_rows = sorted(front_rows, key=_dragon_sort_key)[: max(int(limit), 0)]
    for market_rank, event in enumerate(market_rows, start=1):
        event["market_dragon_rank"] = market_rank
    return market_rows


def summarize_proxy_trades(trades: list[dict[str, object]]) -> dict[str, object]:
    """Summarize closed percentage returns without portfolio-size assumptions."""

    returns = [
        float(item["return_pct"])
        for item in trades
        if item.get("return_pct") is not None
    ]
    if not returns:
        return {
            "trade_count": 0,
            "win_count": 0,
            "win_rate": None,
            "average_return_pct": None,
            "median_return_pct": None,
            "total_return_pct": 0.0,
            "profit_factor": None,
        }

    gains = sum(value for value in returns if value > 0)
    losses = abs(sum(value for value in returns if value < 0))
    compounded = (prod(1 + value / 100 for value in returns) - 1) * 100
    win_count = sum(1 for value in returns if value > 0)
    return {
        "trade_count": len(returns),
        "win_count": win_count,
        "win_rate": round(win_count / len(returns) * 100, 4),
        "average_return_pct": round(mean(returns), 4),
        "median_return_pct": round(median(returns), 4),
        "total_return_pct": round(compounded, 4),
        "profit_factor": round(gains / losses, 4) if losses else None,
    }


def _dragon_sort_key(event: Mapping[str, object]) -> tuple[float, str]:
    score = _float_value(event.get("dragon_score"))
    return (-score, str(event.get("vt_symbol") or ""))


def _float_value(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _d1_outcome(code: str) -> dict[str, object]:
    return {
        "outcome_code": code,
        "outcome_label": D1_OUTCOME_LABELS[code],
        "is_continuation_limit_up": code == "continuation_limit_up",
    }


def _gross_return_pct(entry_price: float, price: float | None) -> float | None:
    if price is None:
        return None
    return round((price / entry_price - 1) * 100, 4)


def _net_return_pct(entry_price: float, price: float | None, total_cost_rate: float) -> float | None:
    gross = _gross_return_pct(entry_price, price)
    return round(gross - total_cost_rate * 100, 4) if gross is not None else None


def _at_most(value: float | None, threshold: float) -> bool:
    return value is not None and value <= threshold


def _at_least(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def _above(value: float | None, threshold: float) -> bool:
    return value is not None and value > threshold


def _int_value(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0
