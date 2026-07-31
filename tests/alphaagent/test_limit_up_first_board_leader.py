"""Tests for the first-board leader live view (v4)."""

from __future__ import annotations

from alphaagent.server.services.limit_up import first_board_leader_service as service


def _signal(vt_symbol, board_lane, change_pct, distance_to_limit_pct, concept_leader_rank, seal_amount=1.0e8):
    return {
        "vt_symbol": vt_symbol,
        "board_lane": board_lane,
        "change_pct": change_pct,
        "distance_to_limit_pct": distance_to_limit_pct,
        "concept_leader_rank": concept_leader_rank,
        "seal_amount": seal_amount,
    }


def _snapshot(now_signals):
    return {
        "trade_date": "2026-07-30",
        "captured_at": "2026-07-30T10:00:00+08:00",
        "session_stage": "morning",
        "mode": "live_snapshot",
        "data_quality": {"is_stale": False},
        "recommendations": {"lanes": {"now": now_signals, "tail": [], "next_auction": []}},
    }


def test_filters_to_first_board_only() -> None:
    snapshot = _snapshot([
        _signal("A", "first_board", 9.5, 0.5, 1),
        _signal("B", "two_to_three", 10.0, 0.0, 1),  # 非首板，排除
        _signal("C", "high_board", 10.0, 0.0, 1),  # 非首板，排除
    ])
    result = service.select_first_board_leaders(snapshot)
    leaders = result["leaders"]
    assert [leader["vt_symbol"] for leader in leaders] == ["A"]


def test_orders_by_realtime_strength() -> None:
    # 强度：涨幅高 > 距板近 > 概念龙前 > 封单大
    snapshot = _snapshot([
        _signal("A", "first_board", 5.0, 5.0, 3),  # 涨幅低，垫底
        _signal("B", "first_board", 9.5, 0.5, 1),  # 涨幅高+概念龙1，第一
        _signal("C", "first_board", 9.5, 0.5, 2),  # 同涨幅同距板，概念龙2 次之
    ])
    result = service.select_first_board_leaders(snapshot)
    assert [leader["vt_symbol"] for leader in result["leaders"]] == ["B", "C", "A"]


def test_caps_at_leader_limit() -> None:
    signals = [
        _signal(f"S{i:02d}", "first_board", 9.0 - i * 0.1, 1.0, i)
        for i in range(25)
    ]
    result = service.select_first_board_leaders(_snapshot(signals))
    assert len(result["leaders"]) == 20


def test_empty_snapshot_returns_empty_leaders() -> None:
    result = service.select_first_board_leaders(None)
    assert result["leaders"] == []
    assert result["trade_date"] is None


def test_preserves_snapshot_meta() -> None:
    snapshot = _snapshot([_signal("A", "first_board", 9.5, 0.5, 1)])
    result = service.select_first_board_leaders(snapshot)
    assert result["trade_date"] == "2026-07-30"
    assert result["session_stage"] == "morning"
    assert result["mode"] == "live_snapshot"
    assert result["data_quality"] == {"is_stale": False}
