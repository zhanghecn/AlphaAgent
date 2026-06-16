"""Tests for the realtime holdings intelligence: live-price refresh and exit advice.

groups.holdings() is the endpoint the portfolio page actually consumes
(/portfolio/holdings -> groups.holdings), so the live last_price refresh and
the per-position exit advice both live there. These tests pin the in-place
mutation of _apply_live_price without standing up a full database.
"""

from __future__ import annotations

import pytest
from datetime import date, datetime, timezone

from alphaagent.server.services.portfolio import groups


def test_apply_live_price_refreshes_last_price_market_value_and_pnl(monkeypatch) -> None:
    monkeypatch.setattr(groups, "latest_bar_close", lambda session, vt_symbol: 12.0)

    item = {
        "vt_symbol": "600000.SSE",
        "volume": 1000,
        "cost_price": 10.0,
        "last_price": 10.0,  # stale fill price
        "market_value": 10_000.0,
        "floating_pnl": 0.0,
        "floating_pnl_pct": 0.0,
    }

    groups._apply_live_price(item, session=None)

    assert item["last_price"] == 12.0
    assert item["market_value"] == 12_000.0
    assert item["floating_pnl"] == 2_000.0
    assert item["floating_pnl_pct"] == pytest.approx(20.0)


def test_apply_live_price_leaves_stale_price_when_no_bar(monkeypatch) -> None:
    monkeypatch.setattr(groups, "latest_bar_close", lambda session, vt_symbol: None)

    item = {
        "vt_symbol": "600000.SSE",
        "volume": 1000,
        "cost_price": 10.0,
        "last_price": 10.0,
    }

    groups._apply_live_price(item, session=None)

    # No bar -> no refresh, stale fill price preserved (graceful degradation).
    assert item["last_price"] == 10.0
    assert "market_value" not in item or item["market_value"] != 12_000.0


def test_apply_live_price_skips_non_positive_close(monkeypatch) -> None:
    monkeypatch.setattr(groups, "latest_bar_close", lambda session, vt_symbol: 0.0)

    item = {
        "vt_symbol": "600000.SSE",
        "volume": 1000,
        "cost_price": 10.0,
        "last_price": 10.0,
    }

    groups._apply_live_price(item, session=None)

    assert item["last_price"] == 10.0


# --- exit advice (groups._attach_advice) -----------------------------------

def _holding(**overrides) -> dict:
    base = {
        "last_price": 10.5,
        "cost_price": 10.0,
        "stop_loss_price": 9.3,
        "take_profit_price": 11.8,
        "trailing_stop_price": 9.2,
        "created_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return base


def test_attach_advice_stop_loss_when_price_below_stop_line() -> None:
    item = _holding(last_price=9.0)
    groups._attach_advice(item)
    assert item["advice"] == "stop_loss"


def test_attach_advice_take_profit_when_price_above_target() -> None:
    item = _holding(last_price=12.0)
    groups._attach_advice(item)
    assert item["advice"] == "take_profit"


def test_attach_advice_hold_when_no_rule_triggered() -> None:
    item = _holding(last_price=10.5)  # fresh position, no line breached
    groups._attach_advice(item)
    assert item["advice"] == "hold"


def test_attach_advice_time_stop_for_long_held_position() -> None:
    # Held far longer than time_stop_days*2 (default 15*2=30 days).
    item = _holding(created_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
    groups._attach_advice(item)
    assert item["advice"] == "time_stop"


def test_attach_advice_defaults_to_hold_when_price_missing() -> None:
    item = _holding(last_price=None)
    groups._attach_advice(item)
    assert item["advice"] == "hold"
