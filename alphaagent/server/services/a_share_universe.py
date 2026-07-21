"""Shared A-share universe rules that are independent of research strategy."""

from __future__ import annotations


def is_eligible_main_board(vt_symbol: str, name: str) -> bool:
    """Return whether a symbol belongs to the non-ST SSE/SZSE main board."""

    code, _, exchange = str(vt_symbol or "").upper().partition(".")
    normalized_name = str(name or "").upper().replace("*", "")
    if (
        "ST" in normalized_name
        or "退" in normalized_name
        or normalized_name.startswith(("S", "N", "C"))
        or exchange not in {"SSE", "SZSE"}
    ):
        return False
    if exchange == "SSE":
        return code.startswith(("600", "601", "603", "605"))
    return code.startswith(("000", "001", "002", "003"))
