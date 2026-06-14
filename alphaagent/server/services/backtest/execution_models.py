"""Execution price models for AlphaAgent portfolio backtests."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol

from alphaagent.market.boards import stock_board
from alphaagent.server.services.quant.factors import Bar


SUPPORTED_BACKTEST_MINUTE_INTERVALS = {"1m"}
SUPPORTED_EXECUTION_MODELS = {"tail_close_hybrid", "strict_1430", "legacy_next_open"}


class BacktestParamsLike(Protocol):
    execution_model: str
    intraday_entry: bool
    minute_entry_required: bool
    minute_interval: str
    tail_entry_start: str
    tail_entry_end: str
    tail_entry_ma5_tolerance_pct: float


class MinuteBarLike(Protocol):
    bar_time: datetime
    trade_date: date
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float | None
    turnover: float | None


def normalize_execution_model(value: Any) -> str:
    model = str(value or "strict_1430").strip().lower()
    aliases = {
        "hybrid": "tail_close_hybrid",
        "tail": "tail_close_hybrid",
        "tail_close": "tail_close_hybrid",
        "strict": "strict_1430",
        "strict_minute": "strict_1430",
        "strict_tail": "strict_1430",
        "next_open": "legacy_next_open",
        "daily_next_open": "legacy_next_open",
        "legacy": "legacy_next_open",
    }
    model = aliases.get(model, model)
    if model not in SUPPORTED_EXECUTION_MODELS:
        supported = ", ".join(sorted(SUPPORTED_EXECUTION_MODELS))
        raise ValueError(f"Unsupported execution model: {model}; supported: {supported}")
    return model


def normalize_backtest_minute_interval(value: Any) -> str:
    interval = str(value or "1m").strip().lower()
    aliases = {
        "1": "1m",
        "1min": "1m",
        "1分钟": "1m",
    }
    interval = aliases.get(interval, interval)
    if interval not in SUPPORTED_BACKTEST_MINUTE_INTERVALS:
        supported = ", ".join(sorted(SUPPORTED_BACKTEST_MINUTE_INTERVALS))
        raise ValueError(f"Unsupported backtest minute interval: {interval}; supported: {supported}")
    return interval


def resolve_buy_fill(
    order: dict[str, Any],
    current_day: date,
    daily_bar: Bar,
    bar_index: dict[str, dict[date, Bar]],
    minute_index: dict[str, dict[date, list[MinuteBarLike]]],
    params: BacktestParamsLike,
) -> dict[str, Any]:
    if params.execution_model == "tail_close_hybrid":
        return _resolve_tail_hybrid_buy_fill(order, current_day, daily_bar, bar_index, minute_index, params)
    if params.execution_model == "strict_1430":
        return _resolve_strict_1430_buy_fill(order, current_day, daily_bar, bar_index, minute_index, params)
    return _resolve_legacy_next_open_buy_fill(order, current_day, daily_bar, bar_index, minute_index, params)


def resolve_tail_sell_fill(
    vt_symbol: str,
    position: Any,
    current_day: date,
    daily_bar: Bar,
    minute_index: dict[str, dict[date, list[MinuteBarLike]]],
    params: BacktestParamsLike,
    reason: str,
    signal_date: date | None = None,
) -> dict[str, Any]:
    minute_bars = minute_index.get(vt_symbol, {}).get(current_day, [])
    signal_day = signal_date or current_day
    base = {
        "status": "filled",
        "execution_model": params.execution_model,
        "signal_date": signal_day.isoformat(),
        "execute_date": current_day.isoformat(),
        "entry_date": position.entry_date.isoformat(),
        "reason": reason,
        "minute_bar_count": len(minute_bars),
        "window": f"{params.tail_entry_start}-{params.tail_entry_end}",
        "minute_interval": params.minute_interval,
    }
    if _is_limit_down_tail(vt_symbol, daily_bar):
        return {
            **base,
            "status": "rejected",
            "price": None,
            "mode": "limit_down_tail_blocked",
            "reason": "limit_down_tail_blocked",
            "price_source": None,
            "proxy_used": False,
        }
    trigger = _exact_tail_bar(minute_bars, params)
    if trigger:
        return {
            **base,
            "price": trigger.close_price,
            "mode": "minute_1430_sell",
            "bar_time": trigger.bar_time.isoformat(sep=" "),
            "price_source": "stock_minute_bars.close_price",
            "proxy_used": False,
        }
    if params.execution_model == "strict_1430" and current_day >= date.today():
        # 今天缺 14:30 快照才拒单并提示；历史 strict_1430 走下方日线收盘代理卖出
        return {
            **base,
            "status": "rejected",
            "price": None,
            "mode": "today_pending_1430_snapshot_sell",
            "reason": "today_pending_1430_snapshot",
            "next_action": "今日 14:30 后分钟数据将自动补齐，届时重跑获取真实卖出价。",
            "price_source": None,
            "proxy_used": False,
        }
    return {
        **base,
        "price": daily_bar.close_price,
        "mode": "daily_close_proxy_sell",
        "price_source": "stock_daily_bars.close_price",
        "proxy_used": True,
    }


def _resolve_legacy_next_open_buy_fill(
    order: dict[str, Any],
    current_day: date,
    daily_bar: Bar,
    bar_index: dict[str, dict[date, Bar]],
    minute_index: dict[str, dict[date, list[MinuteBarLike]]],
    params: BacktestParamsLike,
) -> dict[str, Any]:
    vt_symbol = str(order["vt_symbol"])
    if not params.intraday_entry:
        return {
            "status": "filled",
            "price": daily_bar.open_price,
            "execution_model": params.execution_model,
            "mode": "daily_next_open",
            "signal_date": _iso_date(order.get("signal_date")),
            "execute_date": current_day.isoformat(),
            "price_source": "stock_daily_bars.open_price",
            "proxy_used": False,
        }

    reference_date = _as_date(order.get("signal_date")) or _previous_trade_date(bar_index.get(vt_symbol, {}), current_day)
    ma5 = _ma5_for_entry_day(bar_index.get(vt_symbol, {}), reference_date) if reference_date else None
    minute_bars = minute_index.get(vt_symbol, {}).get(current_day, [])
    trigger = _tail_entry_trigger(minute_bars, ma5, params)
    if trigger:
        return {
            "status": "filled",
            "price": trigger.close_price,
            "execution_model": params.execution_model,
            "mode": "minute_tail_ma5",
            "bar_time": trigger.bar_time.isoformat(sep=" "),
            "signal_date": reference_date.isoformat() if reference_date else None,
            "execute_date": current_day.isoformat(),
            "price_source": "stock_minute_bars.close_price",
            "proxy_used": False,
            "reference_date": reference_date.isoformat() if reference_date else None,
            "ma5": ma5,
            "ma5_distance_pct": _pct_distance(trigger.close_price, ma5),
            "window": f"{params.tail_entry_start}-{params.tail_entry_end}",
            "minute_interval": params.minute_interval,
        }
    if params.minute_entry_required:
        return {
            "status": "rejected",
            "price": None,
            "reason": "tail_entry_not_triggered",
            "execution_model": params.execution_model,
            "mode": "minute_tail_ma5_required",
            "signal_date": reference_date.isoformat() if reference_date else None,
            "execute_date": current_day.isoformat(),
            "price_source": None,
            "proxy_used": False,
            "minute_bar_count": len(minute_bars),
            "reference_date": reference_date.isoformat() if reference_date else None,
            "ma5": ma5,
            "window": f"{params.tail_entry_start}-{params.tail_entry_end}",
            "minute_interval": params.minute_interval,
        }
    return {
        "status": "filled",
        "price": daily_bar.open_price,
        "execution_model": params.execution_model,
        "mode": "daily_next_open_fallback",
        "fallback_reason": "minute_tail_entry_unavailable_or_not_triggered",
        "signal_date": reference_date.isoformat() if reference_date else None,
        "execute_date": current_day.isoformat(),
        "price_source": "stock_daily_bars.open_price",
        "proxy_used": True,
        "minute_bar_count": len(minute_bars),
        "reference_date": reference_date.isoformat() if reference_date else None,
        "ma5": ma5,
        "window": f"{params.tail_entry_start}-{params.tail_entry_end}",
        "minute_interval": params.minute_interval,
    }


def _resolve_tail_hybrid_buy_fill(
    order: dict[str, Any],
    current_day: date,
    daily_bar: Bar,
    bar_index: dict[str, dict[date, Bar]],
    minute_index: dict[str, dict[date, list[MinuteBarLike]]],
    params: BacktestParamsLike,
) -> dict[str, Any]:
    vt_symbol = str(order["vt_symbol"])
    if _is_limit_up_tail(vt_symbol, daily_bar):
        return _tail_reject_payload("limit_up_tail_unfilled", order, current_day, daily_bar, bar_index, minute_index, params)
    reference_date = _as_date(order.get("signal_date")) or _previous_trade_date(bar_index.get(vt_symbol, {}), current_day)
    ma5 = _ma5_for_entry_day(bar_index.get(vt_symbol, {}), reference_date) if reference_date else None
    minute_bars = minute_index.get(vt_symbol, {}).get(current_day, [])
    trigger = _exact_tail_bar(minute_bars, params)
    if trigger:
        return _tail_buy_payload(
            mode="minute_1430",
            price=trigger.close_price,
            order=order,
            current_day=current_day,
            reference_date=reference_date,
            ma5=ma5,
            params=params,
            minute_bars=minute_bars,
            minute_bar=trigger,
            price_source="stock_minute_bars.close_price",
            proxy_used=False,
        )
    return _tail_buy_payload(
        mode="daily_close_proxy",
        price=daily_bar.close_price,
        order=order,
        current_day=current_day,
        reference_date=reference_date,
        ma5=ma5,
        params=params,
        minute_bars=minute_bars,
        minute_bar=None,
        price_source="stock_daily_bars.close_price",
        proxy_used=True,
    )


def _resolve_strict_1430_buy_fill(
    order: dict[str, Any],
    current_day: date,
    daily_bar: Bar,
    bar_index: dict[str, dict[date, Bar]],
    minute_index: dict[str, dict[date, list[MinuteBarLike]]],
    params: BacktestParamsLike,
) -> dict[str, Any]:
    vt_symbol = str(order["vt_symbol"])
    if _is_limit_up_tail(vt_symbol, daily_bar):
        return _tail_reject_payload("limit_up_tail_unfilled", order, current_day, daily_bar, bar_index, minute_index, params)
    reference_date = _as_date(order.get("signal_date")) or _previous_trade_date(bar_index.get(vt_symbol, {}), current_day)
    ma5 = _ma5_for_entry_day(bar_index.get(vt_symbol, {}), reference_date) if reference_date else None
    minute_bars = minute_index.get(vt_symbol, {}).get(current_day, [])
    trigger = _exact_tail_bar(minute_bars, params)
    if trigger:
        return _tail_buy_payload(
            mode="minute_1430",
            price=trigger.close_price,
            order=order,
            current_day=current_day,
            reference_date=reference_date,
            ma5=ma5,
            params=params,
            minute_bars=minute_bars,
            minute_bar=trigger,
            price_source="stock_minute_bars.close_price",
            proxy_used=False,
        )
    # 无 14:30 快照：按日期分流，解决历史日期无意义拒单
    if current_day < date.today():
        # 历史日期缺分钟数据属正常，用执行日日线收盘代理成交（信号确认后的可观测价）
        return _tail_buy_payload(
            mode="daily_close_proxy",
            price=daily_bar.close_price,
            order=order,
            current_day=current_day,
            reference_date=reference_date,
            ma5=ma5,
            params=params,
            minute_bars=minute_bars,
            minute_bar=None,
            price_source="stock_daily_bars.close_price",
            proxy_used=True,
        )
    # 今天缺 14:30 快照：盘中未到或数据未同步，明确提示而非无意义拒单
    payload = _tail_reject_payload(
        "missing_1430_snapshot", order, current_day, daily_bar, bar_index, minute_index, params
    )
    payload["mode"] = "today_pending_1430_snapshot"
    payload["next_action"] = "今日 14:30 后分钟数据将自动补齐，届时重跑可获取真实成交价；历史日期已用日线收盘代理成交。"
    return payload


def _tail_buy_payload(
    *,
    mode: str,
    price: float,
    order: dict[str, Any],
    current_day: date,
    reference_date: date | None,
    ma5: float | None,
    params: BacktestParamsLike,
    minute_bars: list[MinuteBarLike],
    minute_bar: MinuteBarLike | None,
    price_source: str,
    proxy_used: bool,
) -> dict[str, Any]:
    distance = _pct_distance(price, ma5)
    if ma5 is not None and distance is not None and abs(distance) > params.tail_entry_ma5_tolerance_pct:
        return {
            **_tail_base_payload(order, current_day, reference_date, ma5, params, minute_bars),
            "status": "rejected",
            "price": price,
            "reason": "tail_entry_not_triggered",
            "mode": "strict_1430_required" if params.execution_model == "strict_1430" else mode,
            "ma5_distance_pct": distance,
            "price_source": price_source,
            "proxy_used": proxy_used,
        }
    return {
        **_tail_base_payload(order, current_day, reference_date, ma5, params, minute_bars),
        "status": "filled",
        "price": price,
        "mode": mode,
        "bar_time": minute_bar.bar_time.isoformat(sep=" ") if minute_bar else None,
        "ma5_distance_pct": distance,
        "price_source": price_source,
        "proxy_used": proxy_used,
    }


def _tail_reject_payload(
    reason: str,
    order: dict[str, Any],
    current_day: date,
    daily_bar: Bar,
    bar_index: dict[str, dict[date, Bar]],
    minute_index: dict[str, dict[date, list[MinuteBarLike]]],
    params: BacktestParamsLike,
) -> dict[str, Any]:
    vt_symbol = str(order["vt_symbol"])
    reference_date = _as_date(order.get("signal_date")) or _previous_trade_date(bar_index.get(vt_symbol, {}), current_day)
    ma5 = _ma5_for_entry_day(bar_index.get(vt_symbol, {}), reference_date) if reference_date else None
    minute_bars = minute_index.get(vt_symbol, {}).get(current_day, [])
    return {
        **_tail_base_payload(order, current_day, reference_date, ma5, params, minute_bars),
        "status": "rejected",
        "price": None if reason != "tail_entry_not_triggered" else daily_bar.close_price,
        "reason": reason,
        "mode": "strict_1430_required" if params.execution_model == "strict_1430" else reason,
        "price_source": None,
        "proxy_used": False,
    }


def _tail_base_payload(
    order: dict[str, Any],
    current_day: date,
    reference_date: date | None,
    ma5: float | None,
    params: BacktestParamsLike,
    minute_bars: list[MinuteBarLike],
) -> dict[str, Any]:
    return {
        "execution_model": params.execution_model,
        "signal_date": _iso_date(order.get("signal_date")) or (reference_date.isoformat() if reference_date else None),
        "execute_date": current_day.isoformat(),
        "reference_date": reference_date.isoformat() if reference_date else None,
        "ma5": ma5,
        "minute_bar_count": len(minute_bars),
        "window": f"{params.tail_entry_start}-{params.tail_entry_end}",
        "minute_interval": params.minute_interval,
    }


def _exact_tail_bar(minute_bars: list[MinuteBarLike], params: BacktestParamsLike) -> MinuteBarLike | None:
    target = _parse_hhmm(params.tail_entry_start)
    for bar in sorted(minute_bars, key=lambda item: item.bar_time):
        if bar.bar_time.time().hour == target.hour and bar.bar_time.time().minute == target.minute:
            return bar
    return None


def _tail_entry_trigger(
    minute_bars: list[MinuteBarLike],
    ma5: float | None,
    params: BacktestParamsLike,
) -> MinuteBarLike | None:
    if ma5 is None or ma5 <= 0:
        return None
    start = _parse_hhmm(params.tail_entry_start)
    end = _parse_hhmm(params.tail_entry_end)
    for bar in sorted(minute_bars, key=lambda item: item.bar_time):
        hhmm = bar.bar_time.time()
        if hhmm < start or hhmm > end:
            continue
        distance = _pct_distance(bar.close_price, ma5)
        if distance is not None and abs(distance) <= params.tail_entry_ma5_tolerance_pct:
            return bar
    return None


def _ma5_for_entry_day(symbol_bars: dict[date, Bar], reference_date: date | None) -> float | None:
    if reference_date is None:
        return None
    closes = [bar.close_price for day, bar in sorted(symbol_bars.items()) if day <= reference_date]
    if len(closes) < 5:
        return None
    return sum(closes[-5:]) / 5


def _previous_trade_date(symbol_bars: dict[date, Bar], current_day: date) -> date | None:
    previous = [day for day in symbol_bars if day < current_day]
    return max(previous) if previous else None


def _parse_hhmm(value: str):
    return datetime.strptime(value, "%H:%M").time()


def _pct_distance(value: float | None, reference: float | None) -> float | None:
    if value is None or reference in (None, 0):
        return None
    return (float(value) / float(reference) - 1) * 100


def _is_limit_up_tail(vt_symbol: str, bar: Bar) -> bool:
    threshold = _daily_limit_threshold(vt_symbol)
    return bool(bar.change_pct is not None and bar.change_pct >= threshold)


def _is_limit_down_tail(vt_symbol: str, bar: Bar) -> bool:
    threshold = _daily_limit_threshold(vt_symbol)
    return bool(bar.change_pct is not None and bar.change_pct <= -threshold)


def _daily_limit_threshold(vt_symbol: str) -> float:
    board = stock_board(vt_symbol)
    if board == "bse":
        return 29.8
    if board in {"star", "chinext"}:
        return 19.8
    return 9.8


def _iso_date(value: Any) -> str | None:
    parsed = _as_date(value)
    return parsed.isoformat() if parsed else None


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
