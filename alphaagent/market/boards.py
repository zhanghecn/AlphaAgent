"""A-share board classification helpers."""

from __future__ import annotations

from typing import Any

BOARD_LABELS = {
    "main": "主板",
    "chinext": "创业板",
    "star": "科创板",
    "bse": "北交所",
    "index": "指数",
    "unknown": "其他",
}

DEFAULT_QUANT_INCLUDED_BOARDS = ("main",)
ALL_QUANT_BOARDS = ("main", "chinext", "star", "bse")


def board_options() -> list[dict[str, str]]:
    return [{"value": board, "label": board_label(board)} for board in ALL_QUANT_BOARDS]


def stock_board(vt_symbol: Any, exchange: Any = None) -> str:
    text = str(vt_symbol or "").strip().upper()
    symbol = text.split(".", 1)[0]
    exch = str(exchange or (text.split(".", 1)[1] if "." in text else "")).strip().upper()
    if not symbol:
        return "unknown"
    if exch in {"BSE", "BJ"} or symbol.startswith(("8", "4", "920")):
        return "bse"
    if symbol.startswith("688"):
        return "star"
    if symbol.startswith(("300", "301")):
        return "chinext"
    if (symbol.startswith("000") and exch == "SSE") or (symbol.startswith("399") and exch == "SZSE"):
        return "index"
    if exch in {"SSE", "SZSE"} or symbol.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
        return "main"
    return "unknown"


def board_label(board: Any) -> str:
    return BOARD_LABELS.get(str(board or "").strip().lower(), BOARD_LABELS["unknown"])


def stock_board_payload(vt_symbol: Any, exchange: Any = None) -> dict[str, str]:
    board = stock_board(vt_symbol, exchange)
    return {"board": board, "board_label": board_label(board)}


def normalize_included_boards(value: Any, default: tuple[str, ...] = DEFAULT_QUANT_INCLUDED_BOARDS) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        raw_items = [item.strip().lower() for item in value.split(",")]
    else:
        try:
            raw_items = [str(item).strip().lower() for item in value]
        except TypeError:
            raw_items = [str(value).strip().lower()]
    allowed = set(ALL_QUANT_BOARDS)
    items = tuple(dict.fromkeys(item for item in raw_items if item in allowed))
    return items or default


def included_board_labels(boards: Any) -> list[str]:
    return [board_label(board) for board in normalize_included_boards(boards)]
