from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from alphaagent.server.api import first_board
from alphaagent.server.main import create_app
from alphaagent.server.services.first_board import live_service


def _pool_item(
    symbol: str,
    name: str,
    *,
    limit_up_count: int = 1,
    limit_amount: float = 30.0,
    turnover: float = 100.0,
    first_limit_time: str = "09:35:00",
    open_times: int = 0,
) -> dict[str, object]:
    exchange = "SSE" if symbol.startswith("6") else "SZSE"
    return {
        "vt_symbol": f"{symbol}.{exchange}",
        "name": name,
        "close_price": 10.0,
        "limit_up_price": 10.0,
        "change_pct": 10.0,
        "limit_up_count": limit_up_count,
        "limit_amount": limit_amount,
        "turnover_rate": 8.0,
        "volume_ratio": 2.0,
        "first_limit_time": first_limit_time,
        "last_limit_time": "14:55:00",
        "raw": {"成交额": turnover, "开板次数": open_times},
    }


def test_live_first_board_filters_universe_and_uses_only_live_strength_order() -> None:
    payload = {
        "trade_date": "20260812",
        "updated_at": "2026-08-12T10:01:00+08:00",
        "source": "akshare.stock_ztb_em",
        "pools": {
            "zt": {
                "total": 7,
                "items": [
                    _pool_item(
                        "600001",
                        "首板甲",
                        limit_amount=30,
                        turnover=100,
                        first_limit_time="09:40:00",
                        open_times=2,
                    ),
                    _pool_item(
                        "000002",
                        "首板乙",
                        limit_amount=20,
                        turnover=100,
                        first_limit_time="09:32:00",
                        open_times=1,
                    ),
                    _pool_item("600003", "*ST 首板"),
                    _pool_item("300004", "创业板首板"),
                    _pool_item("600005", "二板", limit_up_count=2),
                    _pool_item("002006", "首板丙", limit_amount=20, turnover=100),
                    _pool_item("600007", "首板丁", limit_amount=10, turnover=100),
                ],
            }
        },
    }

    result = live_service.build_live_first_board_payload(
        payload,
        now=datetime.fromisoformat("2026-08-12T10:02:00+08:00"),
    )

    assert result["trade_date"] == "2026-08-12"
    assert result["data_quality"] == {
        "status": "ready",
        "is_stale": False,
        "pool_total": 7,
        "first_board_total": 4,
    }
    assert [item["vt_symbol"] for item in result["leaders"]] == [
        "600001.SSE",
        "000002.SZSE",
        "002006.SZSE",
        "600007.SSE",
    ]
    first = result["leaders"][0]
    assert first["rank"] == 1
    assert first["seal_to_turnover_ratio"] == 0.3
    assert first["first_limit_time"] == "09:40:00"
    assert first["open_times"] == 2


def test_live_first_board_reports_an_unavailable_pool_without_database_fallback() -> None:
    result = live_service.build_live_first_board_payload(
        {"pools": {"zt": {"status": "unavailable", "items": []}}},
        now=datetime.fromisoformat("2026-08-12T10:02:00+08:00"),
    )

    assert result["status"] == "unavailable"
    assert result["leaders"] == []
    assert result["data_quality"]["is_stale"] is True


def test_first_board_live_api_exposes_only_the_real_time_snapshot(monkeypatch) -> None:
    expected = {
        "status": "ok",
        "trade_date": "2026-08-12",
        "leaders": [{"rank": 1, "vt_symbol": "600001.SSE"}],
    }
    monkeypatch.setattr(first_board, "get_live_first_board", lambda: expected)

    response = TestClient(create_app()).get("/api/first-board/live")

    assert response.status_code == 200
    assert response.json()["data"] == expected
