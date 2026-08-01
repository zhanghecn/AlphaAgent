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


# ── Phase 2：潜力分 v2 + 封板质量 + 尾盘降权 + 温度指示 ────────────────


def _rich_signal(vt_symbol, **factors):
    base = {
        "vt_symbol": vt_symbol,
        "board_lane": "first_board",
        "change_pct": 5.0,
        "distance_to_limit_pct": 3.0,
        "concept_leader_rank": 2,
        "seal_amount": 1.0e8,
    }
    base.update(factors)
    return base


def test_potential_score_ranks_whitelist_factors_first() -> None:
    # A 涨幅低但白名单因子全面更强 → 潜力分优先排前
    snapshot = _snapshot([
        _rich_signal("A", change_pct=4.0, concept_max_return_20d=12.0,
                     volume_ratio_5_60=2.5, drawdown_from_126d_high_pct=-5.0,
                     position_126d=0.9, prior_return_20d_pct=18.0,
                     prior_return_5d_pct=6.0),
        _rich_signal("B", change_pct=9.0, concept_max_return_20d=-3.0,
                     volume_ratio_5_60=0.8, drawdown_from_126d_high_pct=-35.0,
                     position_126d=0.1, prior_return_20d_pct=-12.0,
                     prior_return_5d_pct=-4.0),
    ])
    result = service.select_first_board_leaders(snapshot)
    leaders = result["leaders"]
    assert leaders[0]["vt_symbol"] == "A"
    assert leaders[0]["potential_score"] > leaders[1]["potential_score"]
    assert leaders[0]["factor_percentiles"]["concept_max_return_20d"] == 1.0


def test_potential_score_missing_factors_redistribute_weights() -> None:
    # 只有部分因子有值 → 权重按可用重分配，不因缺字段归零
    snapshot = _snapshot([
        _rich_signal("A", concept_max_return_20d=10.0),
        _rich_signal("B", concept_max_return_20d=5.0),
    ])
    result = service.select_first_board_leaders(snapshot)
    a = result["leaders"][0]
    assert a["vt_symbol"] == "A"
    assert a["potential_score"] == 1.0  # 唯一可用因子分位 1 → 满分
    assert set(a["factor_percentiles"]) == {"concept_max_return_20d"}


def test_seal_quality_boost_and_retention_warning() -> None:
    snapshot = _snapshot([
        _rich_signal("A", concept_max_return_20d=8.0,
                     seal_to_turnover_ratio=1.5, seal_amount_retention_ratio=1.1),
        _rich_signal("B", concept_max_return_20d=8.0,
                     seal_to_turnover_ratio=0.1, seal_amount_retention_ratio=0.5),
    ])
    result = service.select_first_board_leaders(snapshot)
    leaders = {leader["vt_symbol"]: leader for leader in result["leaders"]}
    assert leaders["A"]["potential_score"] > leaders["B"]["potential_score"]
    assert leaders["B"]["seal_weakening"] is True
    assert leaders["A"]["seal_weakening"] is False


def test_late_seal_downweights_score() -> None:
    snapshot = _snapshot([
        _rich_signal("A", concept_max_return_20d=10.0, first_limit_time="09:45:00"),
        _rich_signal("B", concept_max_return_20d=10.0, first_limit_time="14:35:00"),
    ])
    result = service.select_first_board_leaders(snapshot)
    leaders = {leader["vt_symbol"]: leader for leader in result["leaders"]}
    assert leaders["B"]["late_seal"] is True
    assert leaders["A"]["late_seal"] is False
    assert leaders["A"]["potential_score"] > leaders["B"]["potential_score"]


def test_market_temperature_levels(monkeypatch) -> None:
    monkeypatch.setattr(service, "_load_market_temperature", lambda today: {
        "trade_date": today.isoformat(), "available": True,
        "lag1_trade_date": "2026-07-29", "lag1_first_board_count": 25, "level": "cold",
    })
    service._temperature_cache["at"] = None  # 清缓存
    result = service.select_first_board_leaders(_snapshot([]))
    temp = result["market_temperature"]
    assert temp["available"] is True
    assert temp["level"] == "cold"
    assert temp["lag1_first_board_count"] == 25
    # 分档边界
    assert service.TEMP_COLD_MAX == 32 and service.TEMP_HOT_MIN == 69
