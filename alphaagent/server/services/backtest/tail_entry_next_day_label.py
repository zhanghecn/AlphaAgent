"""Tail-entry next-day labels for candidate quality research."""

from __future__ import annotations

from datetime import date
from typing import Any

from alphaagent.server.services.quant.factors import Bar


def build_tail_entry_next_day_label(
    *,
    signal_date: date,
    bars: list[Bar],
    vt_symbol: str = "",
    name: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Label a D close entry by D+1 close outcome and D+2/D+3 hold value."""

    sorted_bars = sorted(bars, key=lambda bar: bar.trade_date)
    signal_index = next((index for index, bar in enumerate(sorted_bars) if bar.trade_date == signal_date), None)
    if signal_index is None:
        return _missing_label("no_signal_bar", signal_date=signal_date)

    signal_bar = sorted_bars[signal_index]
    entry_price = _positive_float(signal_bar.close_price)
    if entry_price is None:
        return _missing_label("invalid_tail_entry_price", signal_date=signal_date, signal_bar=signal_bar)

    d1_index = next(
        (index for index in range(signal_index + 1, len(sorted_bars)) if sorted_bars[index].trade_date > signal_date),
        None,
    )
    if d1_index is None:
        return _missing_label("no_execute_bar", signal_date=signal_date, signal_bar=signal_bar, entry_price=entry_price)

    d1_bar = sorted_bars[d1_index]
    d2_bar = sorted_bars[d1_index + 1] if d1_index + 1 < len(sorted_bars) else None
    d3_bar = sorted_bars[d1_index + 2] if d1_index + 2 < len(sorted_bars) else None
    hold_window = [bar for bar in (d2_bar, d3_bar) if bar is not None]

    d1_open_return = _pct_return(float(d1_bar.open_price), entry_price)
    d1_high_runup = _pct_return(float(d1_bar.high_price), entry_price)
    d1_low_drawdown = _pct_return(float(d1_bar.low_price), entry_price)
    d1_close_return = _pct_return(float(d1_bar.close_price), entry_price)
    d1_success = bool(d1_close_return is not None and d1_close_return > 0)
    d1_quality_success = bool(
        d1_success
        and d1_high_runup is not None
        and d1_high_runup >= 1.5
        and d1_low_drawdown is not None
        and d1_low_drawdown > -3.0
    )

    limit_threshold = limit_up_close_threshold_pct(vt_symbol=vt_symbol, name=name, evidence=evidence)
    near_limit_threshold = near_limit_up_threshold_pct(vt_symbol=vt_symbol, name=name, evidence=evidence)
    d1_near_limit_up = bool(d1_high_runup is not None and d1_high_runup >= near_limit_threshold)
    d1_limit_up = bool(
        d1_high_runup is not None
        and d1_close_return is not None
        and d1_high_runup >= near_limit_threshold
        and d1_close_return >= near_limit_threshold
    )
    d1_big_drop = bool(
        (d1_close_return is not None and d1_close_return <= -5.0)
        or (d1_low_drawdown is not None and d1_low_drawdown <= -7.0)
    )

    d2_close_return = _pct_return(float(d2_bar.close_price), entry_price) if d2_bar is not None else None
    d3_close_return = _pct_return(float(d3_bar.close_price), entry_price) if d3_bar is not None else None
    d2_d3_best_runup = _pct_return(max(float(bar.high_price) for bar in hold_window), entry_price) if hold_window else None
    d2_d3_best_close_return = _pct_return(max(float(bar.close_price) for bar in hold_window), entry_price) if hold_window else None
    d2_d3_low_drawdown = _pct_return(min(float(bar.low_price) for bar in hold_window), entry_price) if hold_window else None
    hold_to_d3_worthwhile = _hold_to_d3_worthwhile(
        d1_success=d1_success,
        d1_close_price=float(d1_bar.close_price),
        entry_price=entry_price,
        hold_window=hold_window,
    )
    take_profit_next_day = _take_profit_next_day(
        d1_success=d1_success,
        d1_close_return=d1_close_return,
        d2_d3_best_close_return=d2_d3_best_close_return,
        d2_d3_low_drawdown=d2_d3_low_drawdown,
        hold_to_d3_worthwhile=hold_to_d3_worthwhile,
    )

    return {
        "status": "ready",
        "label_model": "tail_entry_next_day",
        "entry_model": "signal_day_close",
        "entry_selection": "daily_candidate",
        "tail_entry_date": signal_bar.trade_date.isoformat(),
        "tail_entry_price": round(entry_price, 4),
        "d1_trade_date": d1_bar.trade_date.isoformat(),
        "d1_open_price": round(float(d1_bar.open_price), 4),
        "d1_high_price": round(float(d1_bar.high_price), 4),
        "d1_low_price": round(float(d1_bar.low_price), 4),
        "d1_close_price": round(float(d1_bar.close_price), 4),
        "d1_open_return_pct": d1_open_return,
        "d1_high_runup_pct": d1_high_runup,
        "d1_low_drawdown_pct": d1_low_drawdown,
        "d1_close_return_pct": d1_close_return,
        "d1_success": d1_success,
        "d1_quality_success": d1_quality_success,
        "d1_near_limit_up": d1_near_limit_up,
        "d1_limit_up": d1_limit_up,
        "d1_limit_threshold_pct": limit_threshold,
        "d1_near_limit_threshold_pct": near_limit_threshold,
        "d1_big_drop": d1_big_drop,
        "d1_low_open": bool(d1_open_return is not None and d1_open_return <= -2.0),
        "d1_low_close": bool(d1_close_return is not None and d1_close_return <= -3.0),
        "d2_trade_date": d2_bar.trade_date.isoformat() if d2_bar is not None else None,
        "d2_close_return_pct": d2_close_return,
        "d3_trade_date": d3_bar.trade_date.isoformat() if d3_bar is not None else None,
        "d3_close_return_pct": d3_close_return,
        "d2_d3_best_runup_pct": d2_d3_best_runup,
        "d2_d3_best_close_return_pct": d2_d3_best_close_return,
        "d2_d3_low_drawdown_pct": d2_d3_low_drawdown,
        "hold_to_d3_worthwhile": hold_to_d3_worthwhile,
        "take_profit_next_day": take_profit_next_day,
        "uses_future_for_label_only": True,
        "not_used_for_signal_score": True,
    }


def limit_up_close_threshold_pct(*, vt_symbol: str = "", name: str | None = None, evidence: dict[str, Any] | None = None) -> float:
    if _is_st_stock(name=name, evidence=evidence):
        return 5.0
    if _is_bse_stock(vt_symbol):
        return 30.0
    if _is_chinext_or_star_stock(vt_symbol):
        return 20.0
    return 10.0


def near_limit_up_threshold_pct(*, vt_symbol: str = "", name: str | None = None, evidence: dict[str, Any] | None = None) -> float:
    if _is_st_stock(name=name, evidence=evidence):
        return 4.5
    if _is_bse_stock(vt_symbol):
        return 29.0
    if _is_chinext_or_star_stock(vt_symbol):
        return 19.0
    return 9.3


def _hold_to_d3_worthwhile(
    *,
    d1_success: bool,
    d1_close_price: float,
    entry_price: float,
    hold_window: list[Bar],
) -> bool | None:
    if not d1_success or not hold_window:
        return None
    best_follow_high = max(float(bar.high_price) for bar in hold_window)
    worst_follow_low = min(float(bar.low_price) for bar in hold_window)
    return best_follow_high > d1_close_price and worst_follow_low >= entry_price


def _take_profit_next_day(
    *,
    d1_success: bool,
    d1_close_return: float | None,
    d2_d3_best_close_return: float | None,
    d2_d3_low_drawdown: float | None,
    hold_to_d3_worthwhile: bool | None,
) -> bool | None:
    if not d1_success or hold_to_d3_worthwhile is None:
        return None
    if hold_to_d3_worthwhile:
        return False
    if d2_d3_low_drawdown is not None and d2_d3_low_drawdown < 0:
        return True
    if d1_close_return is not None and d2_d3_best_close_return is not None:
        return d2_d3_best_close_return < d1_close_return
    return True


def _missing_label(
    status: str,
    *,
    signal_date: date,
    signal_bar: Bar | None = None,
    entry_price: float | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "label_model": "tail_entry_next_day",
        "entry_model": "signal_day_close",
        "entry_selection": "daily_candidate",
        "tail_entry_date": signal_bar.trade_date.isoformat() if signal_bar is not None else None,
        "tail_entry_price": round(entry_price, 4) if entry_price is not None else None,
        "d1_trade_date": None,
        "d1_close_return_pct": None,
        "d1_success": None,
        "d1_quality_success": None,
        "uses_future_for_label_only": True,
        "not_used_for_signal_score": True,
    }


def _pct_return(price: float, base: float) -> float | None:
    if base <= 0:
        return None
    return round((price / base - 1.0) * 100.0, 4)


def _positive_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric > 0 else None


def _is_st_stock(*, name: str | None, evidence: dict[str, Any] | None) -> bool:
    if evidence and bool(evidence.get("is_st") or evidence.get("st_stock")):
        return True
    return "ST" in str(name or "").upper()


def _is_bse_stock(vt_symbol: str) -> bool:
    symbol = str(vt_symbol or "").upper()
    code = symbol.split(".", 1)[0]
    return symbol.endswith((".BSE", ".BJ")) or (symbol.endswith(".SSE") is False and code.startswith(("8", "4")))


def _is_chinext_or_star_stock(vt_symbol: str) -> bool:
    symbol = str(vt_symbol or "").upper()
    code = symbol.split(".", 1)[0]
    return code.startswith(("300", "301", "688", "689"))
