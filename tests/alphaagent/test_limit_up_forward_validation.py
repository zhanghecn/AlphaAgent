from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from alphaagent.server.main import create_app
from alphaagent.server.services.limit_up.entry_backtest import build_limit_up_entry_backtest
from alphaagent.server.services.limit_up import forward_validation


TRADE_CALENDAR = ["2026-07-09", "2026-07-10", "2026-07-13", "2026-07-14"]


def test_forward_validation_excludes_unverified_snapshots() -> None:
    snapshots = [
        _snapshot(),
        _snapshot(captured_at="2026-07-10T10:06:00+08:00", is_stale=True),
        _snapshot(captured_at="2026-07-10T10:07:00+08:00", mode="historical_proxy"),
        _snapshot(
            trade_date="2026-07-11",
            captured_at="2026-07-11T10:05:00+08:00",
        ),
        _snapshot(captured_at="2026-07-09T10:05:00+08:00"),
        _snapshot(captured_at="2026-07-10T12:05:00+08:00", session_stage="lunch"),
        _snapshot(captured_at="not-a-time"),
        _snapshot(captured_at="2026-07-10T14:55:00+08:00", session_stage="morning"),
        _snapshot(
            trade_date="2026-07-08",
            captured_at="2026-07-08T10:05:00+08:00",
        ),
    ]

    report = forward_validation.build_forward_validation_report(
        _dataset(),
        snapshots,
        trade_calendar=TRADE_CALENDAR,
        entry_mode="sweep",
        exit_mode="next_open",
        current_date=date(2026, 7, 10),
    )

    assert report["mode"] == "saved_actionable_recommendation_forward_validation"
    assert report["validation_version"] == "limit-up-forward-validation-v2"
    assert report["simulation_eligible"] is False
    assert report["coverage"]["raw_snapshot_count"] == 9
    assert report["coverage"]["eligible_snapshot_count"] == 1
    assert report["coverage"]["excluded_snapshot_count"] == 8
    assert report["coverage"]["observed_trade_days"] == 1
    reasons = {
        row["code"]: row["count"]
        for row in report["coverage"]["excluded_by_reason"]
    }
    assert reasons == {
        "captured_date_mismatch": 1,
        "invalid_captured_at": 1,
        "invalid_session_stage": 1,
        "mode_not_live_snapshot": 1,
        "non_trading_day": 2,
        "session_stage_mismatch": 1,
        "stale_snapshot": 1,
    }
    assert report["summary"]["plan_count"] == 1
    assert report["summary"]["closed_trade_count"] == 1
    assert all(order["source_mode"] == "strict_snapshot" for order in report["orders"])


def test_forward_validation_without_eligible_snapshots_is_collecting_not_zero_return() -> None:
    report = forward_validation.build_forward_validation_report(
        {"daily_bars": [], "coverage": {}},
        [_snapshot(mode="historical_proxy")],
        trade_calendar=TRADE_CALENDAR,
        entry_mode="sweep",
        exit_mode="next_open",
        current_date=date(2026, 7, 10),
    )

    assert report["status"] == "collecting"
    assert report["result_status"] == "no_eligible_snapshots"
    assert report["coverage"]["observed_trade_days"] == 0
    assert report["summary"]["plan_count"] == 0
    assert report["summary"]["win_rate"] is None
    assert report["summary"]["average_return_pct"] is None
    assert report["summary"]["total_return_pct"] is None
    assert report["summary"]["max_drawdown_pct"] is None
    assert report["progress"]["process_check"]["progress_pct"] == 0.0
    assert report["progress"]["strategy_review"]["remaining_days"] == 60


def test_current_live_trade_date_can_wait_for_daily_calendar_close() -> None:
    report = forward_validation.build_forward_validation_report(
        {"daily_bars": [], "coverage": {}},
        [_snapshot()],
        trade_calendar=["2026-07-09"],
        entry_mode="sweep",
        exit_mode="next_open",
        current_date=date(2026, 7, 10),
    )

    assert report["coverage"]["eligible_snapshot_count"] == 1
    assert report["status"] == "observing"
    assert report["result_status"] == "awaiting_d1"
    assert report["summary"]["pending_plan_count"] == 1
    assert report["summary"]["total_return_pct"] is None


def test_later_snapshot_cannot_rewrite_first_intraday_buy_action() -> None:
    snapshots = [
        _snapshot(trigger_price=11.0),
        _snapshot(captured_at="2026-07-10T10:20:00+08:00", trigger_price=11.2),
    ]

    report = forward_validation.build_forward_validation_report(
        _dataset(),
        snapshots,
        trade_calendar=TRADE_CALENDAR,
        entry_mode="sweep",
        exit_mode="next_open",
        current_date=date(2026, 7, 10),
    )

    assert len(report["orders"]) == 1
    assert report["orders"][0]["snapshot_at"] == "2026-07-10T10:05:00+08:00"
    assert report["trades"][0]["entry_price"] == 11.0


def test_forward_validation_does_not_execute_research_only_action() -> None:
    snapshot = _snapshot(
        action="pass",
        research_action="buy_now",
        actionable=False,
    )

    report = forward_validation.build_forward_validation_report(
        _dataset(),
        [snapshot],
        trade_calendar=TRADE_CALENDAR,
        entry_mode="sweep",
        exit_mode="next_open",
        current_date=date(2026, 7, 10),
    )

    assert report["orders"] == []
    assert report["trades"] == []
    assert report["summary"]["plan_count"] == 0
    assert report["summary"]["win_rate"] is None


def test_forward_validation_does_not_execute_lane_buy_missing_from_formal_list() -> None:
    snapshot = _snapshot(action="buy_now", actionable=False)

    report = forward_validation.build_forward_validation_report(
        _dataset(),
        [snapshot],
        trade_calendar=TRADE_CALENDAR,
        entry_mode="sweep",
        exit_mode="next_close",
        current_date=date(2026, 7, 10),
    )

    assert report["orders"] == []
    assert report["trades"] == []


def test_forward_validation_executes_saved_formal_recommendation() -> None:
    report = forward_validation.build_forward_validation_report(
        _dataset(),
        [_snapshot()],
        trade_calendar=TRADE_CALENDAR,
        entry_mode="sweep",
        exit_mode="next_close",
        current_date=date(2026, 7, 10),
    )

    assert len(report["orders"]) == 1
    assert report["orders"][0]["fill_evidence"] == (
        "saved_actionable_recommendation_proxy"
    )
    assert len(report["trades"]) == 1


def test_regular_entry_backtest_does_not_treat_research_action_as_execution() -> None:
    snapshot = _snapshot(action="pass", research_action="buy_now")

    report = build_limit_up_entry_backtest(
        _dataset(),
        [snapshot],
        entry_mode="sweep",
        exit_mode="next_open",
        historical_proxy_candidates=[],
    )

    assert report["orders"] == []
    assert report["trades"] == []


def test_next_auction_uses_only_the_last_valid_plan_for_each_day() -> None:
    morning = _snapshot(
        symbol="600001.SSE",
        name="早盘计划",
        lane="next_auction",
        action="next_auction",
        entry_kind="next_auction",
    )
    tail = _snapshot(
        symbol="600002.SSE",
        name="尾盘计划",
        lane="next_auction",
        action="next_auction",
        entry_kind="next_auction",
        captured_at="2026-07-10T14:55:00+08:00",
        session_stage="tail",
    )

    report = forward_validation.build_forward_validation_report(
        _dataset(symbols=("600001.SSE", "600002.SSE")),
        [morning, tail],
        trade_calendar=TRADE_CALENDAR,
        entry_mode="next_auction",
        exit_mode="next_open",
        current_date=date(2026, 7, 10),
    )

    assert [order["vt_symbol"] for order in report["orders"]] == ["600002.SSE"]
    assert report["orders"][0]["snapshot_at"] == "2026-07-10T14:55:00+08:00"


def test_next_close_is_the_first_trading_day_after_the_actual_entry() -> None:
    report = forward_validation.build_forward_validation_report(
        _dataset(),
        [_snapshot()],
        trade_calendar=TRADE_CALENDAR,
        entry_mode="sweep",
        exit_mode="next_close",
        current_date=date(2026, 7, 10),
    )

    trade = report["trades"][0]
    assert trade["entry_date"] == "2026-07-10"
    assert trade["exit_date"] == "2026-07-13"
    assert trade["exit_price"] == 11.8


def test_forward_validation_service_loads_only_saved_live_version(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_snapshots(start, end, *, strategy_version=None):
        captured.update(start=start, end=end, strategy_version=strategy_version)
        return [_snapshot()]

    monkeypatch.setattr(forward_validation, "load_snapshots_between", fake_snapshots)
    monkeypatch.setattr(forward_validation, "list_daily_trade_dates", lambda: TRADE_CALENDAR)
    monkeypatch.setattr(
        forward_validation,
        "load_daily_bars_for_symbols",
        lambda symbols, start, end: _dataset(symbols=tuple(symbols))["daily_bars"],
    )

    report = forward_validation.get_forward_validation(
        date(2026, 7, 10),
        date(2026, 7, 10),
        current_date=date(2026, 7, 10),
    )

    assert captured == {
        "start": date(2026, 7, 10),
        "end": date(2026, 7, 10),
        "strategy_version": "limit-up-live-v15",
    }
    assert report["coverage"]["eligible_snapshot_count"] == 1


def test_forward_validation_api_uses_frozen_execution_contract(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    captured: dict[str, object] = {}

    def fake_forward(start, end):
        captured.update(start=start, end=end)
        return {
            "status": "collecting",
            "mode": "saved_actionable_recommendation_forward_validation",
        }

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(limit_up, "get_limit_up_forward_validation", fake_forward)

    response = TestClient(create_app()).get(
        "/api/limit-up/forward-validation",
        params={
            "start": "2026-07-01",
            "end": "2026-07-10",
            "entry_mode": "sweep",
            "exit_mode": "next_close",
        },
    )

    assert response.status_code == 200
    assert str(captured["start"]) == "2026-07-01"
    assert str(captured["end"]) == "2026-07-10"


def test_forward_validation_api_rejects_non_formal_execution_contract() -> None:
    response = TestClient(create_app()).get(
        "/api/limit-up/forward-validation",
        params={"entry_mode": "auction", "exit_mode": "next_open"},
    )

    assert response.status_code == 422


def test_forward_validation_api_rejects_invalid_range() -> None:
    response = TestClient(create_app()).get(
        "/api/limit-up/forward-validation",
        params={"start": "2026-07-10", "end": "2026-07-01"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_DATE_RANGE"


def test_forward_validation_api_requires_database(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: False)

    response = TestClient(create_app()).get("/api/limit-up/forward-validation")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


def test_forward_validation_api_returns_structured_service_error(monkeypatch) -> None:
    from alphaagent.server.api import limit_up

    monkeypatch.setattr(limit_up, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        limit_up,
        "get_limit_up_forward_validation",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("broken")),
    )

    response = TestClient(create_app()).get("/api/limit-up/forward-validation")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "LIMIT_UP_RESEARCH_ERROR"
    assert response.json()["error"]["detail"]["reason"] == "RuntimeError"


def _snapshot(
    *,
    trade_date: str = "2026-07-10",
    captured_at: str = "2026-07-10T10:05:00+08:00",
    session_stage: str = "morning",
    mode: str = "live_snapshot",
    is_stale: bool = False,
    symbol: str = "600001.SSE",
    name: str = "严格信号",
    lane: str = "now",
    action: str = "buy_now",
    research_action: str | None = None,
    actionable: bool = True,
    entry_kind: str = "sweep",
    trigger_price: float = 11.0,
) -> dict[str, object]:
    signal = {
        "vt_symbol": symbol,
        "name": name,
        "sector_id": "BK1",
        "sector_name": "机器人",
        "market_dragon_rank": 1,
        "sector_dragon_rank": 1,
        "board_level": 1,
        "state": "resealed",
        "open_times": 1,
        "trigger_price": trigger_price,
        "action": action,
        "entry_kind": entry_kind,
        "execution_confidence": "proxy_without_l2",
    }
    if research_action is not None:
        signal["research_action"] = research_action
    lanes: dict[str, list[dict[str, object]]] = {
        "now": [],
        "tail": [],
        "next_auction": [],
    }
    lanes[lane] = [signal]
    return {
        "trade_date": trade_date,
        "captured_at": captured_at,
        "session_stage": session_stage,
        "strategy_version": "limit-up-live-v2",
        "mode": mode,
        "candidates": [signal],
        "recommendations": {
            "lanes": lanes,
            "actionable_recommendations": [signal] if actionable else [],
        },
        "data_quality": {"status": "ready", "is_stale": is_stale},
    }


def _dataset(
    *,
    symbols: tuple[str, ...] = ("600001.SSE",),
) -> dict[str, object]:
    prices = {
        "2026-07-09": (9.8, 10.0),
        "2026-07-10": (10.2, 11.0),
        "2026-07-13": (11.55, 11.8),
        "2026-07-14": (12.0, 12.1),
    }
    bars = [
        {
            "vt_symbol": symbol,
            "trade_date": trade_date,
            "open_price": open_price,
            "close_price": close_price,
            "high_price": max(open_price, close_price),
            "low_price": min(open_price, close_price),
        }
        for symbol in symbols
        for trade_date, (open_price, close_price) in prices.items()
    ]
    return {
        "events": [],
        "daily_bars": bars,
        "trade_calendar": TRADE_CALENDAR,
        "coverage": {},
    }
