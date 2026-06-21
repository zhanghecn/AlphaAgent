"""Read-only single-symbol market line and unified marker review helpers."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from alphaagent.server.services.quant import market_context


def bull_bear_line_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Build a compact market line point from signal-day visible evidence."""

    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    payload = evidence.get("market_context") if isinstance(evidence.get("market_context"), dict) else {}
    if not payload:
        payload = {
            "regime": evidence.get("dynamic_market_regime"),
            "label": evidence.get("dynamic_market_label"),
            "market_score": evidence.get("market_score"),
            "breadth_score": evidence.get("market_breadth_score") or evidence.get("breadth_score"),
            "market_warning_level": evidence.get("market_warning_level"),
            "recovery_state": evidence.get("recovery_state"),
            "fund_flow_state": evidence.get("fund_flow_state"),
            "theme_strength": evidence.get("theme_strength"),
        }
    phase = market_context.classify_trading_market_phase(payload)
    score = _market_line_score(payload, phase)
    return {
        "trade_date": row.get("trade_date"),
        "state": _market_line_state(phase["phase"]),
        "phase": phase["phase"],
        "label": _market_line_label(phase["phase"]),
        "score": score,
        "level": _market_line_level(score),
        "color_role": _market_line_color_role(phase["phase"]),
        "notes": phase.get("notes") or [],
        "not_used_for_signal_score": True,
    }


def build_unified_signal_review(rows: list[dict[str, Any]], *, cluster_days: int = 14) -> dict[str, Any]:
    """Collapse dense signal rows into buy/rejected/sell markers and stats.

    The function processes rows in chronological order. It never chooses a row
    based on future returns; sell stats are calculated only after a visible buy.
    """

    ordered = sorted((dict(row) for row in rows), key=_row_sort_key)
    markers: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    cluster: list[dict[str, Any]] = []
    cluster_start: date | None = None
    open_buy: dict[str, Any] | None = None
    open_max_high: float | None = None
    open_max_drawdown_pct = 0.0
    max_cluster_days = max(int(cluster_days), 0)

    def flush_cluster() -> None:
        nonlocal cluster, cluster_start, open_buy, open_max_high, open_max_drawdown_pct
        if not cluster:
            return
        buy = _latest_visible_launch(cluster)
        markers.append(_buy_marker(buy, cluster))
        open_buy = buy
        open_max_high = _row_high(buy) or _row_close(buy)
        open_max_drawdown_pct = 0.0
        cluster = []
        cluster_start = None

    for row in ordered:
        row_date = _row_date(row)
        if _is_buy_row(row):
            if cluster_start is None:
                cluster_start = row_date
            if row_date and cluster_start and (row_date - cluster_start).days > max_cluster_days:
                flush_cluster()
                cluster_start = row_date
            cluster.append(row)
            continue

        if _is_rejected_buy_row(row):
            flush_cluster()
            markers.append(_rejected_marker(row))
            continue

        if open_buy:
            visible_prices = [value for value in [open_max_high, _row_high(row), _row_close(row)] if value is not None]
            open_max_high = max(visible_prices) if visible_prices else open_max_high
            drawdown = _drawdown_from_buy(open_buy, row)
            if drawdown is not None:
                open_max_drawdown_pct = min(open_max_drawdown_pct, drawdown)

        if _is_sell_row(row):
            flush_cluster()
            if open_buy:
                segment = _closed_segment(open_buy, row, open_max_drawdown_pct)
                segments.append(segment)
                markers.append(_sell_marker(row, segment))
                open_buy = None
                open_max_high = None
                open_max_drawdown_pct = 0.0
            else:
                markers.append(_sell_marker(row, None))
            continue

        if cluster and _breaks_buy_cluster(row):
            flush_cluster()

    flush_cluster()
    return {
        "markers": markers,
        "segments": segments,
        "summary": _segment_summary(segments),
        "method": "按日期顺序聚合买入簇；卖出只和上一笔聚合买入配对；不使用未来数据挑买点。",
        "not_used_for_signal_score": True,
    }


def attach_symbol_review(rows: list[dict[str, Any]]) -> dict[str, Any]:
    market_line = [bull_bear_line_from_row(row) for row in rows]
    review = build_unified_signal_review(rows)
    return {
        "market_line": market_line,
        "unified_review": review,
    }


def _market_line_score(payload: dict[str, Any], phase: dict[str, Any]) -> float:
    tide_score = _safe_float(phase.get("tide_score"))
    if tide_score is not None:
        return round(max(0.0, min(100.0, tide_score)), 2)
    score = _safe_float(payload.get("market_score"))
    if score is not None:
        return round(max(0.0, min(100.0, score)), 2)
    fallback = {"uptrend": 78.0, "warming": 62.0, "rotation": 50.0, "retreat": 24.0}
    return fallback.get(str(phase.get("phase") or ""), 50.0)


def _market_line_state(phase: str) -> str:
    return {
        "uptrend": "bull",
        "warming": "warming",
        "rotation": "range",
        "retreat": "bear",
    }.get(str(phase or ""), "unknown")


def _market_line_label(phase: str) -> str:
    return {
        "uptrend": "主升",
        "warming": "回暖",
        "rotation": "震荡",
        "retreat": "退潮",
    }.get(str(phase or ""), "未知")


def _market_line_color_role(phase: str) -> str:
    return {
        "uptrend": "rise",
        "warming": "recover",
        "rotation": "neutral",
        "retreat": "fall",
    }.get(str(phase or ""), "neutral")


def _market_line_level(score: float) -> int:
    if score >= 72:
        return 3
    if score >= 56:
        return 2
    if score >= 42:
        return 1
    return 0


def _is_buy_row(row: dict[str, Any]) -> bool:
    return bool(row.get("executable_entry_signal")) and _score(row) >= 75


def _is_rejected_buy_row(row: dict[str, Any]) -> bool:
    if str(row.get("action") or "").upper() != "WATCH":
        return False
    return bool(row.get("entry_signal") or row.get("raw_entry_signal")) and bool(row.get("failed_rules") or [])


def _is_sell_row(row: dict[str, Any]) -> bool:
    return str(row.get("side") or "").upper() == "SELL" or str(row.get("display_kind") or "") == "sell"


def _breaks_buy_cluster(row: dict[str, Any]) -> bool:
    return bool(str(row.get("action") or "").strip()) and not _is_buy_row(row)


def _latest_visible_launch(rows: list[dict[str, Any]]) -> dict[str, Any]:
    key_rows = [row for row in rows if bool(row.get("key_entry_signal")) or str(row.get("signal_role") or "") == "key_buy"]
    candidates = key_rows or rows
    return max(candidates, key=lambda row: (_row_date(row) or date.min, _score(row)))


def _buy_marker(row: dict[str, Any], cluster: list[dict[str, Any]]) -> dict[str, Any]:
    dates = [_date_text(item) for item in cluster if _date_text(item)]
    return {
        "kind": "buy",
        "label": "买入",
        "trade_date": _date_text(row),
        "price": _row_close(row),
        "score": _score(row),
        "cluster_size": len(cluster),
        "cluster_start_date": dates[0] if dates else None,
        "cluster_end_date": dates[-1] if dates else None,
        "raw": row,
    }


def _rejected_marker(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "rejected_buy",
        "label": "拒买",
        "trade_date": _date_text(row),
        "price": _row_close(row),
        "score": _score(row),
        "failed_rules": row.get("failed_rules") or [],
        "raw": row,
    }


def _sell_marker(row: dict[str, Any], segment: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "kind": "sell",
        "label": "卖出",
        "trade_date": _date_text(row),
        "price": _row_close(row),
        "return_pct": (segment or {}).get("return_pct"),
        "max_drawdown_pct": (segment or {}).get("max_drawdown_pct"),
        "raw": row,
    }


def _closed_segment(buy: dict[str, Any], sell: dict[str, Any], max_drawdown_pct: float) -> dict[str, Any]:
    buy_price = _row_close(buy)
    sell_price = _row_close(sell)
    return_pct = (sell_price / buy_price - 1) * 100 if buy_price and sell_price else None
    return {
        "entry_date": _date_text(buy),
        "exit_date": _date_text(sell),
        "entry_price": buy_price,
        "exit_price": sell_price,
        "return_pct": return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "win": return_pct is not None and return_pct > 0,
    }


def _segment_summary(segments: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [value for row in segments if (value := _safe_float(row.get("return_pct"))) is not None]
    if not returns:
        return {
            "trade_count": 0,
            "win_count": 0,
            "win_rate_pct": None,
            "compound_return_pct": None,
            "average_return_pct": None,
            "max_drawdown_pct": None,
        }
    compound = 1.0
    for value in returns:
        compound *= 1 + value / 100
    drawdowns = [_safe_float(row.get("max_drawdown_pct")) for row in segments]
    drawdown_values = [value for value in drawdowns if value is not None]
    wins = [value for value in returns if value > 0]
    return {
        "trade_count": len(returns),
        "win_count": len(wins),
        "win_rate_pct": len(wins) / len(returns) * 100,
        "compound_return_pct": (compound - 1) * 100,
        "average_return_pct": sum(returns) / len(returns),
        "max_drawdown_pct": min(drawdown_values) if drawdown_values else None,
    }


def _drawdown_from_buy(buy: dict[str, Any], row: dict[str, Any]) -> float | None:
    buy_price = _row_close(buy)
    low = _row_low(row) or _row_close(row)
    if not buy_price or low is None:
        return None
    return (low / buy_price - 1) * 100


def _row_sort_key(row: dict[str, Any]) -> tuple[date, str]:
    return (_row_date(row) or date.min, str(row.get("vt_symbol") or ""))


def _row_date(row: dict[str, Any]) -> date | None:
    for key in ("trade_date", "signal_date", "time", "execute_date"):
        value = row.get(key)
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str) and value:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                continue
    return None


def _date_text(row: dict[str, Any]) -> str | None:
    value = row.get("trade_date") or row.get("signal_date") or row.get("time") or row.get("execute_date")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)[:10] if value else None


def _row_close(row: dict[str, Any]) -> float | None:
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    return _first_float(row.get("close"), row.get("price"), evidence.get("close"), evidence.get("close_price"), evidence.get("latest_close"))


def _row_high(row: dict[str, Any]) -> float | None:
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    return _first_float(row.get("high"), evidence.get("high"), evidence.get("high_price"))


def _row_low(row: dict[str, Any]) -> float | None:
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    return _first_float(row.get("low"), evidence.get("low"), evidence.get("low_price"))


def _score(row: dict[str, Any]) -> float:
    return _safe_float(row.get("total_score")) or _safe_float(row.get("score")) or 0.0


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
