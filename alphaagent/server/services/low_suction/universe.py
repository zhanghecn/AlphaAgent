"""Point-in-time main-board eligibility for low-suction research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

SSE_MAIN_BOARD_PREFIXES = ("600", "601", "603", "605")
SZSE_MAIN_BOARD_PREFIXES = ("000", "001", "002", "003")
MIN_LISTED_SESSIONS = 60


@dataclass(frozen=True)
class SecurityRecord:
    """Security state known at one historical research cutoff."""

    vt_symbol: str
    symbol: str
    exchange: str
    name: str
    status: str
    listed_sessions: int
    suspended: bool
    risk_warning: bool
    delisted: bool
    evidence_level: str


def is_main_board_symbol(symbol: str, exchange: str) -> bool:
    """Return whether a code belongs to the supported SSE/SZSE 10% boards."""

    normalized_symbol = str(symbol).strip()
    normalized_exchange = str(exchange).strip().upper()
    if normalized_exchange == "SSE":
        return normalized_symbol.startswith(SSE_MAIN_BOARD_PREFIXES)
    if normalized_exchange == "SZSE":
        return normalized_symbol.startswith(SZSE_MAIN_BOARD_PREFIXES)
    return False


def eligibility_reason(
    security: SecurityRecord,
    trade_date: date,
) -> str | None:
    """Return an exclusion reason, or None when the security is eligible."""

    del trade_date  # The caller supplies the record already valid on this date.
    if not is_main_board_symbol(security.symbol, security.exchange):
        return "board_not_supported"
    if security.evidence_level != "strict":
        return "historical_status_unavailable"

    status = security.status.strip().upper()
    name = security.name.strip().upper()
    if security.delisted or status == "DELISTED":
        return "delisted"
    if status in {"DELISTING", "TERMINATING"} or "退" in security.name:
        return "delisting"
    if security.risk_warning or status in {"ST", "*ST", "RISK_WARNING"}:
        return "risk_warning"
    if name.startswith("ST") or name.startswith("*ST"):
        return "risk_warning"
    if security.suspended or status == "SUSPENDED":
        return "suspended"
    if security.listed_sessions < MIN_LISTED_SESSIONS:
        return "new_stock"
    return None
