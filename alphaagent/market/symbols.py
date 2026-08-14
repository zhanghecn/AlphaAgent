"""A-share symbol and index helpers."""

from __future__ import annotations


INDEX_SYMBOLS: tuple[dict[str, str], ...] = (
    {"symbol": "000001", "exchange": "SSE", "name": "上证指数"},
    {"symbol": "000300", "exchange": "SSE", "name": "沪深300"},
    {"symbol": "000905", "exchange": "SSE", "name": "中证500"},
    {"symbol": "000852", "exchange": "SSE", "name": "中证1000"},
    {"symbol": "399001", "exchange": "SZSE", "name": "深证成指"},
    {"symbol": "399006", "exchange": "SZSE", "name": "创业板指"},
    {"symbol": "000688", "exchange": "SSE", "name": "科创50"},
    {"symbol": "000016", "exchange": "SSE", "name": "上证50"},
    {"symbol": "899050", "exchange": "BSE", "name": "北证50"},
)


def normalize_exchange(symbol: str, exchange: str | None = None) -> str:
    """Infer vn.py-style exchange from an A-share code."""

    lower_symbol = symbol.strip().lower()
    if lower_symbol.startswith("bj"):
        return "BSE"
    if lower_symbol.startswith("sh"):
        return "SSE"
    if lower_symbol.startswith("sz"):
        return "SZSE"

    if exchange:
        upper = exchange.upper()
        if upper in {"SSE", "SH", "SHSE"}:
            return "SSE"
        if upper in {"SZSE", "SZ"}:
            return "SZSE"
        if upper in {"BSE", "BJ"}:
            return "BSE"

    if symbol.startswith(("5", "6")):
        return "SSE"
    if symbol.startswith(("0", "1", "2", "3")):
        return "SZSE"
    if symbol.startswith(("4", "8", "9")):
        return "BSE"
    return "SSE"


def vt_symbol(symbol: str, exchange: str | None = None) -> str:
    """Return vn.py vt_symbol format."""

    return f"{symbol}.{normalize_exchange(symbol, exchange)}"


def tencent_prefix(symbol: str, exchange: str | None = None) -> str:
    """Return Tencent quote symbol prefix."""

    normalized = normalize_exchange(symbol, exchange)
    if normalized == "SSE":
        return f"sh{symbol}"
    if normalized == "BSE":
        return f"bj{symbol}"
    return f"sz{symbol}"


def eastmoney_secid(symbol: str, exchange: str | None = None) -> str:
    """Return Eastmoney secid."""

    normalized = normalize_exchange(symbol, exchange)
    if normalized == "SSE":
        return f"1.{symbol}"
    if normalized == "BSE":
        return f"0.{symbol}"
    return f"0.{symbol}"


def eastmoney_hsf10_code(symbol: str, exchange: str | None = None) -> str:
    """Return Eastmoney HSF10 code, e.g. SH600000."""

    normalized = normalize_exchange(symbol, exchange)
    prefix = "SH" if normalized == "SSE" else "BJ" if normalized == "BSE" else "SZ"
    return f"{prefix}{symbol}"
