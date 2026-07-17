from __future__ import annotations

from datetime import date

import pytest

from alphaagent.server.services.low_suction.universe import (
    SecurityRecord,
    eligibility_reason,
    is_main_board_symbol,
)


@pytest.mark.parametrize(
    ("symbol", "exchange"),
    [
        ("600000", "SSE"),
        ("601318", "SSE"),
        ("603000", "SSE"),
        ("605001", "SSE"),
        ("000001", "SZSE"),
        ("001979", "SZSE"),
        ("002594", "SZSE"),
        ("003816", "SZSE"),
    ],
)
def test_main_board_prefixes_are_eligible(symbol: str, exchange: str) -> None:
    assert is_main_board_symbol(symbol, exchange) is True


@pytest.mark.parametrize(
    ("symbol", "exchange"),
    [
        ("300750", "SZSE"),
        ("688981", "SSE"),
        ("430047", "BSE"),
        ("830799", "BSE"),
        ("920000", "BSE"),
        ("600000", "SZSE"),
        ("000001", "SSE"),
    ],
)
def test_non_main_board_or_cross_market_codes_are_rejected(
    symbol: str,
    exchange: str,
) -> None:
    assert is_main_board_symbol(symbol, exchange) is False


def _security(**overrides: object) -> SecurityRecord:
    values: dict[str, object] = {
        "vt_symbol": "600000.SSE",
        "symbol": "600000",
        "exchange": "SSE",
        "name": "浦发银行",
        "status": "LISTED",
        "listed_sessions": 1_000,
        "suspended": False,
        "risk_warning": False,
        "delisted": False,
        "evidence_level": "strict",
    }
    values.update(overrides)
    return SecurityRecord(**values)


def test_historical_security_record_is_eligible() -> None:
    assert eligibility_reason(_security(), date(2026, 7, 15)) is None


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"symbol": "300001", "exchange": "SZSE"}, "board_not_supported"),
        ({"name": "*ST测试"}, "risk_warning"),
        ({"status": "ST"}, "risk_warning"),
        ({"risk_warning": True}, "risk_warning"),
        ({"status": "DELISTING"}, "delisting"),
        ({"delisted": True}, "delisted"),
        ({"suspended": True}, "suspended"),
        ({"listed_sessions": 59}, "new_stock"),
        ({"evidence_level": "current_proxy"}, "historical_status_unavailable"),
    ],
)
def test_historical_exclusions_return_auditable_reason(
    override: dict[str, object],
    reason: str,
) -> None:
    assert eligibility_reason(_security(**override), date(2026, 7, 15)) == reason
