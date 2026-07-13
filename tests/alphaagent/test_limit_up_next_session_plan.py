from __future__ import annotations

from datetime import date, datetime
import json
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up import live_service
from alphaagent.server.services.limit_up import next_session_plan
from alphaagent.market.models import Quote


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _source_snapshot() -> dict[str, object]:
    eligible = {
        "vt_symbol": "600001.SSE",
        "name": "计划候选",
        "sector_name": "机器人",
        "market_dragon_rank": 1,
        "board_level": 2,
        "board_lane": "one_to_two",
        "action": "next_auction",
        "entry_kind": "next_auction",
        "reason": "首板质量通过",
        "lane_favorable_factors": ["sector_core", "prior_board_changed_hands_and_resealed"],
        "setup_tags": ["weak_to_strong_breakout"],
        "buy_condition": "次日竞价硬门通过后执行",
        "sell_condition": "D+1动态退出",
        "cancel_condition": "竞价不符合或市场门关闭",
        "execution_confidence": "proxy_without_l2",
    }
    blocked = {
        **eligible,
        "vt_symbol": "600002.SSE",
        "name": "不入计划",
        "action": "pass",
        "entry_kind": "none",
    }
    return {
        "trade_date": "2026-07-10",
        "source": "akshare.stock_ztb_em",
        "source_updated_at": "2026-07-10T15:05:00+08:00",
        "market_context": {"sealed_count": 35, "failed_count": 8},
        "candidates": [],
        "recommendations": {
            "market_gate": {"passed": True, "reasons": []},
            "lanes": {"now": [], "tail": [], "next_auction": [eligible, blocked]},
        },
        "data_quality": {"status": "ready", "source_errors": []},
    }


def test_build_final_plan_keeps_only_next_auction_research_actions() -> None:
    captured_at = datetime(2026, 7, 10, 19, 5, tzinfo=SHANGHAI)

    result = next_session_plan.build_next_session_plan_snapshot(
        _source_snapshot(),
        source_trade_date=date(2026, 7, 10),
        captured_at=captured_at,
        phase="final",
    )

    assert result["mode"] == "next_session_final"
    assert result["source_trade_date"] == "2026-07-10"
    assert result["target_session"] == "next_trading_session"
    assert result["plan_phase"] == "final"
    assert result["data_quality"]["is_stale"] is False
    rows = result["recommendations"]["lanes"]["next_auction"]
    assert [row["vt_symbol"] for row in rows] == ["600001.SSE"]
    assert rows[0]["action"] == "observe"
    assert rows[0]["research_action"] == "next_auction"
    assert rows[0]["signal_state"] == "observing"
    assert rows[0]["execution_permission"] == "research_only"


def test_plan_keeps_structural_observations_while_auction_checks_are_pending() -> None:
    source = _source_snapshot()
    source["recommendations"]["lanes"]["next_auction"] = []
    source["candidates"] = [
        {
            "vt_symbol": "003020.SZSE",
            "name": "立方制药",
            "state": "resealed",
            "board_level": 2,
            "board_lane": "one_to_two",
            "market_dragon_rank": 29,
            "sector_dragon_rank": 1,
            "lane_decision": "blocked",
            "lane_blockers": [
                "market_failed_rate_high",
                "auction_gap_out_of_range",
                "third_board_setup_unconfirmed",
                "two_to_three_risk_stack",
            ],
            "lane_favorable_factors": [
                "prior_board_changed_hands_and_resealed",
                "prior_low_held_positive",
            ],
            "lane_quality_tier": "B",
            "lane_rank_score": 15.6895,
        },
        {
            "vt_symbol": "600002.SSE",
            "name": "前板证据残缺",
            "state": "sealed",
            "board_level": 2,
            "board_lane": "two_to_three",
            "lane_blockers": ["prior_board_path_incomplete"],
            "lane_rank_score": 80.0,
        },
        {
            "vt_symbol": "600003.SSE",
            "name": "没有涨停基因",
            "state": "sealed",
            "board_level": 1,
            "board_lane": "first_board",
            "lane_blockers": ["limit_up_gene_missing"],
            "lane_rank_score": 90.0,
        },
    ]

    result = next_session_plan.build_next_session_plan_snapshot(
        source,
        source_trade_date=date(2026, 7, 10),
        captured_at=datetime(2026, 7, 10, 19, 5, tzinfo=SHANGHAI),
        phase="final",
    )

    rows = result["recommendations"]["lanes"]["next_auction"]
    assert [row["vt_symbol"] for row in rows] == ["003020.SZSE"]
    assert rows[0]["board_level"] == 3
    assert rows[0]["board_lane"] == "two_to_three"
    assert rows[0]["action"] == "observe"
    assert rows[0]["research_action"] == "next_auction"
    assert rows[0]["strategy_name"] == "二进三竞价观察"


def test_plan_limits_each_board_lane_to_four_observations() -> None:
    source = _source_snapshot()
    source["recommendations"]["lanes"]["next_auction"] = []
    source["candidates"] = [
        {
            "vt_symbol": f"60000{index}.SSE",
            "name": f"二板候选{index}",
            "state": "sealed",
            "board_level": 2,
            "board_lane": "two_to_three",
            "lane_blockers": ["auction_gap_out_of_range"],
            "lane_rank_score": float(index),
        }
        for index in range(1, 7)
    ]

    result = next_session_plan.build_next_session_plan_snapshot(
        source,
        source_trade_date=date(2026, 7, 10),
        captured_at=datetime(2026, 7, 10, 19, 5, tzinfo=SHANGHAI),
        phase="final",
    )

    rows = result["recommendations"]["lanes"]["next_auction"]
    assert [row["name"] for row in rows] == [
        "二板候选6",
        "二板候选5",
        "二板候选4",
        "二板候选3",
    ]


def test_plan_snapshot_is_json_serializable_before_persistence() -> None:
    source = _source_snapshot()
    source["candidates"] = [{"vt_symbol": "600001.SSE", "as_of_trade_date": date(2026, 7, 10)}]

    result = next_session_plan.build_next_session_plan_snapshot(
        source,
        source_trade_date=date(2026, 7, 10),
        captured_at=datetime(2026, 7, 10, 19, 5, tzinfo=SHANGHAI),
        phase="final",
    )

    encoded = json.loads(json.dumps(result))
    assert encoded["candidates"][0]["as_of_trade_date"] == "2026-07-10"


def test_preliminary_plan_uses_same_day_pool_confirmed_after_close(monkeypatch) -> None:
    requested_dates: list[str] = []

    class Adapter:
        def limit_up_pools(self, trade_key: str) -> dict[str, object]:
            requested_dates.append(trade_key)
            return {"trade_date": trade_key, "pools": {}}

    monkeypatch.setattr(next_session_plan, "load_latest_daily_trade_date", lambda _date=None: date(2026, 7, 10))
    monkeypatch.setattr(next_session_plan, "load_latest_next_session_plan", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(next_session_plan, "_source_snapshot_from_pools", lambda *_args: _source_snapshot())
    monkeypatch.setattr(next_session_plan, "save_snapshot", lambda snapshot: snapshot)

    result = next_session_plan.refresh_next_session_plan(
        "preliminary",
        captured_at=datetime(2026, 7, 13, 15, 5, tzinfo=SHANGHAI),
        adapter=Adapter(),
    )

    assert requested_dates == ["20260713"]
    assert result["source_trade_date"] == "2026-07-13"


def test_refresh_rebuilds_a_saved_empty_plan(monkeypatch) -> None:
    requested_dates: list[str] = []

    class Adapter:
        def limit_up_pools(self, trade_key: str) -> dict[str, object]:
            requested_dates.append(trade_key)
            return {"trade_date": trade_key, "pools": {}}

    empty = next_session_plan.build_next_session_plan_snapshot(
        {
            **_source_snapshot(),
            "recommendations": {
                "market_gate": {"passed": True, "reasons": []},
                "lanes": {"now": [], "tail": [], "next_auction": []},
            },
        },
        source_trade_date=date(2026, 7, 10),
        captured_at=datetime(2026, 7, 10, 15, 5, tzinfo=SHANGHAI),
        phase="preliminary",
    )
    monkeypatch.setattr(next_session_plan, "load_latest_next_session_plan", lambda *_args, **_kwargs: empty)
    monkeypatch.setattr(next_session_plan, "_source_snapshot_from_pools", lambda *_args: _source_snapshot())
    monkeypatch.setattr(next_session_plan, "save_snapshot", lambda snapshot: snapshot)

    result = next_session_plan.refresh_next_session_plan(
        "preliminary",
        source_trade_date=date(2026, 7, 10),
        captured_at=datetime(2026, 7, 10, 15, 10, tzinfo=SHANGHAI),
        adapter=Adapter(),
    )

    assert requested_dates == ["20260710"]
    assert result["status"] == "ready"


def test_weekend_live_read_prefers_saved_final_plan(monkeypatch) -> None:
    plan = next_session_plan.build_next_session_plan_snapshot(
        _source_snapshot(),
        source_trade_date=date(2026, 7, 10),
        captured_at=datetime(2026, 7, 10, 19, 5, tzinfo=SHANGHAI),
        phase="final",
    )
    monkeypatch.setattr(next_session_plan, "get_latest_next_session_plan", lambda: plan)
    monkeypatch.setattr(
        live_service,
        "load_latest_daily_trade_date",
        lambda _date: date(2026, 7, 10),
    )
    monkeypatch.setattr(
        live_service,
        "load_latest_snapshot",
        lambda **_kwargs: None,
    )

    result = live_service.get_latest_live_snapshot(
        datetime(2026, 7, 11, 20, 0, tzinfo=SHANGHAI)
    )

    assert result["mode"] == "next_session_final"
    assert result["trade_date"] == "2026-07-10"
    assert result["source_trade_date"] == "2026-07-10"
    assert result["data_quality"]["is_stale"] is False
    assert result["recommendations"]["lanes"]["next_auction"][0]["action"] == "observe"


def test_plan_read_does_not_refresh_or_persist(monkeypatch) -> None:
    plan = next_session_plan.build_next_session_plan_snapshot(
        _source_snapshot(),
        source_trade_date=date(2026, 7, 10),
        captured_at=datetime(2026, 7, 10, 19, 5, tzinfo=SHANGHAI),
        phase="final",
    )
    calls: list[str] = []
    monkeypatch.setattr(next_session_plan, "get_latest_next_session_plan", lambda: plan)
    monkeypatch.setattr(
        live_service,
        "refresh_live_snapshot",
        lambda *_args, **_kwargs: calls.append("refresh") or {},
    )
    monkeypatch.setattr(
        live_service,
        "save_snapshot",
        lambda *_args, **_kwargs: calls.append("save") or {},
    )

    result = live_service.get_latest_live_snapshot(
        datetime(2026, 7, 12, 21, 0, tzinfo=SHANGHAI)
    )

    assert result["mode"] == "next_session_final"
    assert calls == []


def test_live_payload_fetch_adds_targeted_plan_quotes() -> None:
    class Adapter:
        requested: list[dict[str, str]] = []

        def list_stocks(self, **_kwargs):
            return {
                "trade_date": "20260713",
                "items": [],
                "source": "ranking",
                "updated_at": "2026-07-13T09:18:00+08:00",
            }

        def limit_up_pools(self, _trade_key):
            return {
                "trade_date": "20260713",
                "pools": {},
                "source": "pools",
                "updated_at": "2026-07-13T09:18:00+08:00",
            }

        def get_quotes(self, symbols):
            self.requested = list(symbols)
            return [
                Quote(
                    symbol="600001",
                    exchange="SSE",
                    vt_symbol="600001.SSE",
                    name="计划股",
                    last_price=11.3,
                    change=0.3,
                    change_pct=2.73,
                    open_price=11.25,
                    high_price=11.3,
                    low_price=11.2,
                    previous_close=11.0,
                    volume=1000,
                    turnover=10_000_000,
                    market_cap=None,
                    pe=None,
                    pb=None,
                    turnover_rate=1.2,
                    industry="机器人",
                    area=None,
                    trade_time="20260713091800",
                    source="tencent.qt.gtimg",
                )
            ]

    adapter = Adapter()
    quotes, _pools, errors = live_service._fetch_live_payloads(
        adapter,
        datetime(2026, 7, 13, 9, 18, tzinfo=SHANGHAI),
        planned_symbols=["600001.SSE"],
    )

    assert adapter.requested == [{"symbol": "600001", "exchange": "SSE"}]
    assert [row["vt_symbol"] for row in quotes["items"]] == ["600001.SSE"]
    assert errors == []
