from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from alphaagent.server.services.low_suction import swing_strategy_service as service
from alphaagent.server.services.low_suction import swing_strategy_overview
from alphaagent.server.services.low_suction.swing_strategy_market_data import (
    SwingLiveSnapshot,
)
from alphaagent.server.services.low_suction.swing_strategy_repository import (
    SwingSignalStaticContext,
)
from tests.alphaagent.services.low_suction.test_swing_paper_portfolio import (
    _daily_bars,
    _empty_positions,
    _empty_trades,
    _entry_quotes,
    _open_position,
    _signals,
)
from tests.alphaagent.services.low_suction.test_swing_strategy import _inputs


SHANGHAI = ZoneInfo("Asia/Shanghai")
SIGNAL_NOW = datetime(2026, 7, 20, 14, 50, 20, tzinfo=SHANGHAI)
ENTRY_NOW = datetime(2026, 7, 20, 14, 55, 10, tzinfo=SHANGHAI)
PREVIEW_NOW = datetime(2026, 7, 20, 10, 30, 20, tzinfo=SHANGHAI)


def _context() -> SwingSignalStaticContext:
    inputs = _inputs()
    return SwingSignalStaticContext(
        source_trade_date=inputs.source_trade_date,
        signal_trade_date=inputs.signal_trade_date,
        captured_at=inputs.captured_at,
        leader_rows=inputs.leader_rows,
        leader_history=inputs.leader_history,
        stock_bars=inputs.stock_bars,
        concept_bars=inputs.concept_bars,
        benchmark_bars=inputs.benchmark_bars,
        completed_dates=inputs.completed_dates,
        open_positions=inputs.open_positions,
    )


def test_strategy_overview_auto_refresh_is_limited_to_mutation_windows() -> None:
    expected_by_time = {
        (1, 0): 30_300,
        (9, 24): 60,
        (9, 25): 30,
        (9, 39): 30,
        (9, 40): 2_700,
        (10, 25): 30,
        (10, 40): 2_700,
        (14, 45): 30,
        (15, 4): 30,
        (15, 5): 13_800,
        (18, 55): 300,
        (22, 29): 300,
        (22, 30): 39_300,
    }

    for (hour, minute), expected in expected_by_time.items():
        observed_at = datetime(2026, 7, 21, hour, minute, tzinfo=SHANGHAI)
        assert swing_strategy_overview._auto_refresh_seconds(observed_at) == expected

    weekend = datetime(2026, 7, 19, 14, 50, tzinfo=SHANGHAI)
    assert swing_strategy_overview._auto_refresh_seconds(weekend) == 66_900


def test_strategy_overview_coalesces_repeated_current_reads(monkeypatch) -> None:
    calls = {"runs": 0, "signals": 0, "positions": 0, "trades": 0}

    def empty_frame(name: str) -> pd.DataFrame:
        calls[name] += 1
        return pd.DataFrame()

    monkeypatch.setattr(
        service.repository,
        "load_runs_for_date",
        lambda **_: empty_frame("runs"),
    )
    monkeypatch.setattr(
        service.repository,
        "load_signal_candidates",
        lambda **_: empty_frame("signals"),
    )
    monkeypatch.setattr(
        service.repository,
        "load_positions",
        lambda **_: empty_frame("positions"),
    )
    monkeypatch.setattr(
        service.repository,
        "load_trades",
        lambda **_: empty_frame("trades"),
    )
    swing_strategy_overview._OVERVIEW_CACHE.clear()

    first = service.get_swing_strategy_overview()
    second = service.get_swing_strategy_overview()

    assert calls == {"runs": 1, "signals": 1, "positions": 1, "trades": 1}
    assert first == second
    assert first is not second
    swing_strategy_overview._OVERVIEW_CACHE.clear()


def test_strategy_overview_carries_latest_unfilled_recommendation_until_1030(
    monkeypatch,
) -> None:
    cached = _signals().copy()
    cached["signal_trade_date"] = date(2026, 7, 20)
    monkeypatch.setattr(service.repository, "load_runs_for_date", lambda **_: pd.DataFrame())
    monkeypatch.setattr(service.repository, "load_signal_candidates", lambda **_: pd.DataFrame())
    monkeypatch.setattr(
        service.repository,
        "load_latest_unfilled_recommendations",
        lambda **_: cached,
    )
    monkeypatch.setattr(service.repository, "load_positions", lambda **_: _empty_positions())
    monkeypatch.setattr(service.repository, "load_trades", lambda **_: _empty_trades())

    overview = service.get_swing_strategy_overview(
        now=datetime(2026, 7, 21, 10, 0, tzinfo=SHANGHAI)
    )

    assert overview["recommendations"] == []
    assert len(overview["cached_recommendations"]) == 1
    assert overview["cached_recommendations"][0]["cached"] is True
    assert overview["recommendation_cache"]["source_trade_date"] == "2026-07-20"


def test_strategy_overview_does_not_carry_recommendation_after_1030(
    monkeypatch,
) -> None:
    monkeypatch.setattr(service.repository, "load_runs_for_date", lambda **_: pd.DataFrame())
    monkeypatch.setattr(service.repository, "load_signal_candidates", lambda **_: pd.DataFrame())
    monkeypatch.setattr(service.repository, "load_positions", lambda **_: _empty_positions())
    monkeypatch.setattr(service.repository, "load_trades", lambda **_: _empty_trades())

    overview = service.get_swing_strategy_overview(
        now=datetime(2026, 7, 21, 10, 31, tzinfo=SHANGHAI)
    )

    assert overview["cached_recommendations"] == []
    assert overview["recommendation_cache"]["active"] is False

def _live_snapshot(*, stale: bool = False) -> SwingLiveSnapshot:
    inputs = _inputs()
    stock_quotes = inputs.stock_quotes.copy()
    if stale:
        stock_quotes["trade_time"] = SIGNAL_NOW - timedelta(minutes=5)
    return SwingLiveSnapshot(
        stock_quotes=stock_quotes,
        concept_quotes=inputs.concept_quotes,
        benchmark_quotes=inputs.benchmark_quotes,
    )


def _live_snapshot_at(observed_at: datetime) -> SwingLiveSnapshot:
    inputs = _inputs()
    stock_quotes = inputs.stock_quotes.copy()
    stock_quotes["trade_time"] = observed_at
    concept_quotes = inputs.concept_quotes.copy()
    concept_quotes["captured_at"] = observed_at
    benchmark_quotes = inputs.benchmark_quotes.copy()
    benchmark_quotes["trade_time"] = observed_at
    return SwingLiveSnapshot(
        stock_quotes=stock_quotes,
        concept_quotes=concept_quotes,
        benchmark_quotes=benchmark_quotes,
    )


def test_1450_scan_blocks_when_intraday_quote_is_stale(monkeypatch) -> None:
    blocked: dict[str, object] = {}
    monkeypatch.setattr(
        service.repository,
        "load_signal_static_context",
        lambda **kwargs: _context(),
    )
    monkeypatch.setattr(
        service.market_data,
        "collect_signal_market_snapshot",
        lambda *args, **kwargs: _live_snapshot(stale=True),
    )
    monkeypatch.setattr(
        service.repository,
        "save_blocked_run",
        lambda **kwargs: blocked.update(kwargs) or {"status": "blocked"},
    )

    result = service.capture_swing_signals(now=SIGNAL_NOW)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"] == ["intraday_stock_quotes_stale"]
    assert result["recommendations_created"] == 0
    assert result["broker_orders_created"] == 0
    assert blocked["phase"] == "signal_1450"


def test_1450_scan_freezes_ready_recommendations(monkeypatch) -> None:
    saved: dict[str, object] = {}
    monkeypatch.setattr(
        service.repository,
        "load_signal_static_context",
        lambda **kwargs: _context(),
    )
    monkeypatch.setattr(
        service.market_data,
        "collect_signal_market_snapshot",
        lambda *args, **kwargs: _live_snapshot(),
    )
    monkeypatch.setattr(
        service.repository,
        "save_signal_capture",
        lambda capture: saved.update(capture=capture)
        or type("Result", (), {"status": "frozen", "rows_written": 1})(),
    )

    result = service.capture_swing_signals(now=SIGNAL_NOW)

    assert result["status"] == "ready"
    assert result["recommendations_created"] == 1
    assert result["broker_orders_created"] == 0
    assert saved["capture"].candidates[0].feature_cutoff_at.hour == 14
    assert saved["capture"].candidates[0].feature_cutoff_at.minute == 50


def test_hourly_preview_publishes_alert_without_opening_positions(monkeypatch) -> None:
    saved: dict[str, object] = {}
    monkeypatch.setattr(
        service.repository,
        "load_signal_static_context",
        lambda **kwargs: replace(_context(), captured_at=PREVIEW_NOW),
    )
    monkeypatch.setattr(
        service.market_data,
        "collect_signal_market_snapshot",
        lambda *args, **kwargs: _live_snapshot_at(PREVIEW_NOW),
    )
    monkeypatch.setattr(
        service.repository,
        "save_signal_preview",
        lambda capture: saved.update(capture=capture)
        or type("Result", (), {"status": "preview_replaced", "rows_written": 1})(),
    )

    result = service.capture_swing_preview(now=PREVIEW_NOW)

    assert result["status"] == "preview_ready"
    assert result["recommendations_created"] == 1
    assert result["positions_opened"] == 0
    assert result["broker_orders_created"] == 0
    assert saved["capture"].feature_cutoff_at == PREVIEW_NOW


def test_1455_fill_only_uses_quote_after_frozen_signal(monkeypatch) -> None:
    saved: dict[str, object] = {}
    monkeypatch.setattr(
        service.repository,
        "load_run",
        lambda **kwargs: {"complete": True},
    )
    monkeypatch.setattr(
        service.repository,
        "load_recommended_signals",
        lambda **kwargs: _signals(),
    )
    monkeypatch.setattr(
        service.repository,
        "load_positions",
        lambda **kwargs: _empty_positions(),
    )
    monkeypatch.setattr(
        service.repository,
        "load_trades",
        lambda **kwargs: _empty_trades(),
    )
    monkeypatch.setattr(
        service.market_data,
        "collect_stock_quotes",
        lambda *args, **kwargs: _entry_quotes(),
    )
    monkeypatch.setattr(
        service.repository,
        "save_entry_decisions",
        lambda **kwargs: saved.update(kwargs)
        or {"status": "complete", "positions_opened": 1},
    )

    result = service.fill_swing_entries(now=ENTRY_NOW)

    assert result["status"] == "complete"
    assert result["positions_opened"] == 1
    assert result["broker_orders_created"] == 0
    assert saved["decisions"][0].quote_time > _signals().iloc[0]["captured_at"]


def test_eod_trigger_waits_for_a_later_open_fill(monkeypatch) -> None:
    saved: dict[str, object] = {}
    monkeypatch.setattr(
        service.repository,
        "load_positions",
        lambda **kwargs: _open_position(),
    )
    monkeypatch.setattr(
        service.repository,
        "load_position_daily_bars",
        lambda *args, **kwargs: _daily_bars(),
    )
    monkeypatch.setattr(
        service.repository,
        "save_exit_triggers",
        lambda **kwargs: saved.update(kwargs)
        or {"status": "complete", "triggers_created": 1},
    )

    result = service.settle_swing_positions(
        as_of_date=date(2026, 7, 20),
        now=datetime(2026, 7, 20, 19, 10, tzinfo=SHANGHAI),
    )

    assert result["status"] == "complete"
    assert result["triggers_created"] == 1
    assert saved["decisions"][0].exit_price is None
    assert saved["marks"] == {"signal-1": 14.4}
    assert result["positions_closed"] == 0
    assert result["broker_orders_created"] == 0


def test_eod_settlement_uses_the_latest_reliable_daily_session(monkeypatch) -> None:
    loaded: dict[str, object] = {}
    monkeypatch.setattr(
        service.repository,
        "latest_complete_daily_date",
        lambda **_: date(2026, 7, 17),
        raising=False,
    )
    monkeypatch.setattr(
        service.repository,
        "load_positions",
        lambda **_: _empty_positions(),
    )
    monkeypatch.setattr(
        service.repository,
        "load_position_daily_bars",
        lambda *args, **kwargs: loaded.update(kwargs) or pd.DataFrame(),
    )
    monkeypatch.setattr(
        service.repository,
        "save_exit_triggers",
        lambda **kwargs: loaded.update(kwargs) or {"status": "complete"},
    )

    result = service.settle_swing_positions(
        now=datetime(2026, 7, 20, 19, 10, tzinfo=SHANGHAI),
    )

    assert result["trade_date"] == "2026-07-17"
    assert loaded["as_of_date"] == date(2026, 7, 17)


def test_non_trading_day_does_not_create_a_signal(monkeypatch) -> None:
    called = {"repository": False}
    monkeypatch.setattr(
        service.repository,
        "load_signal_static_context",
        lambda **kwargs: called.update(repository=True),
    )

    result = service.capture_swing_signals(
        now=datetime(2026, 7, 19, 14, 50, tzinfo=SHANGHAI)
    )

    assert result["status"] == "market_closed"
    assert result["recommendations_created"] == 0
    assert called["repository"] is False


def test_strategy_overview_uses_only_forward_paper_account_rows(monkeypatch) -> None:
    closed_entry_at = datetime(2026, 7, 16, 14, 55, tzinfo=SHANGHAI)
    open_entry_at = datetime(2026, 7, 17, 14, 55, tzinfo=SHANGHAI)
    positions = pd.DataFrame(
        [
            {
                "signal_id": "closed-signal",
                "strategy_version": "low-suction-swing-paper-v1",
                "vt_symbol": "600001.SSE",
                "stock_name": "已平仓龙头",
                "sector_id": "BK0001",
                "sector_name": "概念一",
                "status": "closed",
                "entry_trade_date": date(2026, 7, 16),
                "entry_at": closed_entry_at,
                "entry_price": 10.0,
                "volume": 1_000,
                "buy_fee": 5.0,
                "buy_cash_delta": -10_000.0,
                "last_mark_date": date(2026, 7, 17),
                "last_mark_price": 11.0,
            },
            {
                "signal_id": "open-signal",
                "strategy_version": "low-suction-swing-paper-v1",
                "vt_symbol": "600002.SSE",
                "stock_name": "持仓龙头",
                "sector_id": "BK0002",
                "sector_name": "概念二",
                "status": "open",
                "entry_trade_date": date(2026, 7, 17),
                "entry_at": open_entry_at,
                "entry_price": 20.0,
                "volume": 1_000,
                "buy_fee": 5.0,
                "buy_cash_delta": -20_000.0,
                "last_mark_date": date(2026, 7, 17),
                "last_mark_price": 21.0,
            },
        ]
    )
    trades = pd.DataFrame(
        [
            {
                "signal_id": "closed-signal",
                "strategy_version": "low-suction-swing-paper-v1",
                "vt_symbol": "600001.SSE",
                "stock_name": "已平仓龙头",
                "sector_id": "BK0001",
                "sector_name": "概念一",
                "entry_trade_date": date(2026, 7, 16),
                "entry_at": closed_entry_at,
                "entry_price": 10.0,
                "volume": 1_000,
                "entry_amount": 10_000.0,
                "buy_fee": 5.0,
                "buy_cash_delta": -10_000.0,
                "exit_trigger_date": date(2026, 7, 16),
                "exit_trigger_reason": "reference_peak_rebreak",
                "exit_trade_date": date(2026, 7, 17),
                "exit_at": datetime(2026, 7, 17, 9, 31, tzinfo=SHANGHAI),
                "exit_price": 11.0,
                "exit_amount": 11_000.0,
                "sell_fee": 5.0,
                "sell_cash_delta": 11_000.0,
                "total_fees": 10.0,
                "net_pnl": 1_000.0,
                "net_return_pct": 10.0,
                "exit_deferred_sessions": 0,
                "evidence_level": "strict_intraday_forward_paper",
            }
        ]
    )
    monkeypatch.setattr(service.repository, "load_runs_for_date", lambda **_: pd.DataFrame())
    monkeypatch.setattr(service.repository, "load_signal_candidates", lambda **_: pd.DataFrame())
    monkeypatch.setattr(service.repository, "load_positions", lambda **_: positions)
    monkeypatch.setattr(service.repository, "load_trades", lambda **_: trades)

    overview = service.get_swing_strategy_overview(
        now=datetime(2026, 7, 19, 10, 0, tzinfo=SHANGHAI)
    )

    assert overview["session"]["status"] == "market_closed"
    assert overview["execution_mode"] == "paper"
    assert overview["broker_orders_enabled"] is False
    assert overview["forward_performance"]["closed_trades"] == 1
    assert overview["forward_performance"]["win_rate_pct"] == 100.0
    assert overview["forward_performance"]["cash"] == 81_000.0
    assert overview["forward_performance"]["market_value"] == 21_000.0
    assert overview["forward_performance"]["equity"] == 102_000.0
    assert overview["forward_performance"]["compound_return_pct"] == 2.0
    assert overview["evidence_boundary"]["historical_metrics_in_forward"] is False
