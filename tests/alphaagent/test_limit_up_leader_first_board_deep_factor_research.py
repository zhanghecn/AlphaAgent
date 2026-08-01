"""Tests for the deep first-board factor mining study (v2)."""

from __future__ import annotations

from alphaagent.server.services.limit_up import (
    leader_first_board_deep_factor_research as deep,
)


def _bar(
    vt_symbol: str,
    trade_date: str,
    close: float,
    *,
    open_: float | None = None,
    high: float | None = None,
    low: float | None = None,
    turnover: float = 1.0e8,
    turnover_rate: float = 5.0,
    change_pct: float = 0.0,
) -> dict:
    return {
        "vt_symbol": vt_symbol,
        "trade_date": trade_date,
        "open_price": open_ if open_ is not None else close,
        "close_price": close,
        "high_price": high if high is not None else close,
        "low_price": low if low is not None else close,
        "volume": 1.0e6,
        "turnover": turnover,
        "turnover_rate": turnover_rate,
        "change_pct": change_pct,
    }


def _event(
    vt_symbol: str,
    trade_date: str,
    limit_times: int,
    *,
    first_limit_time: str = "09:30:00",
    is_sealed: bool = True,
    name: str = "示例",
    close_price: float = 11.0,
) -> dict:
    return {
        "vt_symbol": vt_symbol,
        "trade_date": trade_date,
        "limit_times": limit_times,
        "is_sealed": is_sealed,
        "first_limit_time": first_limit_time,
        "last_limit_time": first_limit_time,
        "open_times": 0,
        "seal_amount": 1.0e8,
        "turnover": 5.0e8,
        "float_market_cap": 5.0e9,
        "turnover_rate": 5.0,
        "name": name,
        "close_price": close_price,
        "change_pct": 10.0,
    }


# ── 板型 / ST ──────────────────────────────────────────────────────────


def test_board_type_classification() -> None:
    assert deep._board_type("600001.SSE") == "main"
    assert deep._board_type("000001.SZSE") == "main"
    assert deep._board_type("300001.SZSE") == "chinext"
    assert deep._board_type("688001.SSE") == "star"
    assert deep._board_type("830001.BJSE") == "other"
    assert deep._is_st_name("ST示例") is True
    assert deep._is_st_name("示例") is False


# ── 前 3 天之前（D-10..D-4）─────────────────────────────────────────────


def test_mid_window_features() -> None:
    # 11 根历史 bar：D-11=8.0，D-10..D-4 收 8.0→9.0，D-3..D-1 收 9.0→9.0（平）
    closes = [8.0, 8.1, 8.3, 8.5, 8.7, 8.8, 8.9, 9.0, 9.0, 9.0, 9.0]
    bars = [
        _bar("600001.SSE", f"2025-07-{day:02d}", close, turnover=1.0e8 * (index + 1))
        for index, (day, close) in enumerate(zip(range(1, 12), closes))
    ]
    features = deep._mid_window_features(bars)
    # w7 = D-10..D-4 = index 1..7（收 8.1..9.0）；基 = bars[-11] = 8.0
    assert abs(features["prior_4_10d_return_pct"] - (9.0 / 8.0 - 1) * 100) < 0.01
    assert features["prior_10d_amplitude_pct"] is not None
    # w3 = index 8..10（量 9,10,11），w7 = index 1..7（量 2..8）→ 10/5 = 2.0
    assert abs(features["turnover_ratio_3d_vs_prev7d"] - 2.0) < 0.01


def test_mid_window_features_insufficient_history() -> None:
    bars = [_bar("600001.SSE", f"2025-07-{day:02d}", 10.0) for day in range(1, 6)]
    features = deep._mid_window_features(bars)
    assert features["prior_4_10d_return_pct"] is None
    assert features["turnover_ratio_3d_vs_prev7d"] is None


# ── 近半年 ─────────────────────────────────────────────────────────────


def test_long_window_features() -> None:
    # 127 根：index 0 是基价 8.0（return_126d 用）；126 窗口 = index 1..126
    # 窗口内低点 8.0 在 index 5（位置 4），高点 12.0 在 index 100（位置 99），末收 10.0
    bars = []
    for index in range(127):
        close = 8.0 if index == 0 else 10.0
        high = 12.0 if index == 100 else 10.5
        low = 8.0 if index == 5 else 9.5
        bars.append(_bar("600001.SSE", f"2025-01-{index + 1:03d}", close, high=high, low=low))
    features = deep._long_window_features(bars)
    assert abs(features["return_126d_pct"] - (10.0 / 8.0 - 1) * 100) < 0.01
    assert abs(features["position_126d"] - (10.0 - 8.0) / (12.0 - 8.0)) < 0.001
    assert abs(features["drawdown_from_126d_high_pct"] - (10.0 / 12.0 - 1) * 100) < 0.01
    assert abs(features["rebound_from_126d_low_pct"] - (10.0 / 8.0 - 1) * 100) < 0.01
    assert abs(features["amplitude_126d_pct"] - (12.0 - 8.0) / 8.0 * 100) < 0.01
    assert features["days_since_126d_high"] == 125 - 99
    assert features["days_since_126d_low"] == 125 - 4


def test_long_window_features_short_history_returns_none() -> None:
    bars = [_bar("600001.SSE", f"2025-07-{day:02d}", 10.0) for day in range(1, 30)]
    features = deep._long_window_features(bars)
    assert features["position_126d"] is None
    assert features["return_20d_pct"] is not None  # 20 日特征仍可用
    assert features["return_126d_pct"] is None


# ── 板块共振 ───────────────────────────────────────────────────────────


def test_sector_context_counts_and_earliest() -> None:
    events = [
        _event("600001.SSE", "2025-07-10", 1, first_limit_time="09:35:00"),
        _event("600002.SSE", "2025-07-10", 1, first_limit_time="10:05:00"),
        _event("600003.SSE", "2025-07-10", 1, is_sealed=False),
    ]
    memberships = [
        {"vt_symbol": "600001.SSE", "sector_id": "BK1", "sector_type": "concept"},
        {"vt_symbol": "600002.SSE", "sector_id": "BK1", "sector_type": "concept"},
        {"vt_symbol": "600003.SSE", "sector_id": "BK1", "sector_type": "concept"},
    ]
    sector_bars = [
        {"sector_id": "BK1", "trade_date": f"2025-07-{day:02d}", "close_price": 100.0 + day, "change_pct": 1.0}
        for day in range(1, 11)
    ]
    ctx = deep.build_sector_context(events, memberships, sector_bars)
    # 炸板（未封）不计入涨停家数
    assert ctx.sector_limit_count[("2025-07-10", "BK1")] == 2
    assert ctx.sector_earliest_time[("2025-07-10", "BK1")] == "09:35:00"
    features = deep._sector_features("600001.SSE", "2025-07-10", "09:35:00", ctx)
    assert features["concept_max_limit_up_d"] == 2
    assert features["concept_earliest_seal"] == 1.0
    assert features["concept_max_change_d"] == 1.0
    assert features["concept_best_rank_pct"] == 1.0  # 只有一个板块
    follower = deep._sector_features("600002.SSE", "2025-07-10", "10:05:00", ctx)
    assert follower["concept_earliest_seal"] == 0.0


def test_sector_features_without_membership() -> None:
    ctx = deep.build_sector_context([], [], [])
    features = deep._sector_features("600001.SSE", "2025-07-10", "09:35:00", ctx)
    assert features["concept_count"] == 0
    assert features["concept_max_limit_up_d"] is None
    assert features["industry_max_change_d"] is None


def test_sector_momentum_uses_days_before_d() -> None:
    # 板块 7 连阳后 D 日大跌：D 日的前 5 日动量仍应显著为正（不含 D 日）
    sector_bars = []
    for index in range(8):
        change = 2.0 if index < 7 else -5.0
        sector_bars.append(
            {
                "sector_id": "BK1",
                "trade_date": f"2025-07-{index + 1:02d}",
                "close_price": 100.0 * (1.02 ** index) if index < 7 else 100.0,
                "change_pct": change,
            }
        )
    ctx = deep.build_sector_context([], [], sector_bars)
    momentum = ctx.sector_return_prev[("BK1", "2025-07-08")]
    assert momentum["r5"] > 5.0  # D-1..D-5 的连阳涨幅，不含 D 日 -5%


# ── D+1 标签 ───────────────────────────────────────────────────────────


def test_d1_labels_next_calendar_day() -> None:
    bars = [
        _bar("600001.SSE", "2025-07-10", 11.0),
        _bar("600001.SSE", "2025-07-11", 11.5, open_=11.2, high=11.8),
    ]
    calendar = ["2025-07-10", "2025-07-11"]
    day_number = {value: index for index, value in enumerate(calendar)}
    labels = deep._d1_labels(bars, 0, calendar, day_number)
    assert abs(labels["d1_open_return_pct"] - (11.2 / 11.0 - 1) * 100) < 0.01
    assert abs(labels["d1_close_return_pct"] - (11.5 / 11.0 - 1) * 100) < 0.01
    assert abs(labels["d1_high_return_pct"] - (11.8 / 11.0 - 1) * 100) < 0.01


def test_d1_labels_skip_when_next_day_missing() -> None:
    # 停牌：D+1 交易日没有 bar → 标签为 None（不跨天取值）
    bars = [
        _bar("600001.SSE", "2025-07-10", 11.0),
        _bar("600001.SSE", "2025-07-14", 11.5),
    ]
    calendar = ["2025-07-10", "2025-07-11", "2025-07-14"]
    day_number = {value: index for index, value in enumerate(calendar)}
    labels = deep._d1_labels(bars, 0, calendar, day_number)
    assert labels["d1_open_return_pct"] is None


# ── 时间段交叉 ─────────────────────────────────────────────────────────


def test_time_bucket_cross() -> None:
    events = [
        _event("600001.SSE", "2025-07-10", 1, first_limit_time="09:26:00"),
        _event("600001.SSE", "2025-07-11", 2, first_limit_time="09:31:00"),
        _event("600001.SSE", "2025-07-12", 3, first_limit_time="09:31:00"),
        _event("600002.SSE", "2025-07-10", 1, first_limit_time="14:30:00", is_sealed=False),
    ]
    calendar = ["2025-07-09", "2025-07-10", "2025-07-11", "2025-07-12"]
    daily_bars = []
    for symbol, base in (("600001.SSE", 10.0), ("600002.SSE", 20.0)):
        for index, trade_date in enumerate(calendar):
            daily_bars.append(
                _bar(symbol, trade_date, base + index, open_=base + index - 0.1, high=base + index + 0.5)
            )
    report = deep.build_deep_factor_report(
        events, daily_bars, calendar, [], [], min_consecutive_boards=3, draws=10, seed=1
    )
    cross = {row["bucket_key"]: row for row in report["time_bucket_cross"]}
    auction = cross["auction_open"]
    assert auction["touch_count"] == 1
    assert auction["seal_rate"] == 1.0
    assert auction["first_board_count"] == 1
    assert auction["leader_count"] == 1
    tail = cross["afternoon_1400_1500"]
    assert tail["touch_count"] == 1
    assert tail["sealed_count"] == 0  # 炸板未封 → 封板率 0
    assert tail["first_board_count"] == 0  # 未封板不进入首板样本


# ── 集成：报告端到端 ───────────────────────────────────────────────────


def test_deep_report_end_to_end() -> None:
    calendar = [f"2025-07-{day:02d}" for day in range(1, 16)]
    events = [
        _event("600001.SSE", "2025-07-10", 1, first_limit_time="09:35:00"),
        _event("600001.SSE", "2025-07-11", 2, first_limit_time="09:31:00"),
        _event("600001.SSE", "2025-07-12", 3, first_limit_time="09:31:00"),
        _event("600002.SSE", "2025-07-10", 1, first_limit_time="13:30:00", name="普通股"),
    ]
    daily_bars = []
    for symbol in ("600001.SSE", "600002.SSE"):
        for index, trade_date in enumerate(calendar):
            daily_bars.append(
                _bar(symbol, trade_date, 10.0 + index * 0.1, turnover=1.0e8)
            )
    memberships = [
        {"vt_symbol": "600001.SSE", "sector_id": "BK1", "sector_type": "concept"},
    ]
    sector_bars = [
        {"sector_id": "BK1", "trade_date": trade_date, "close_price": 100.0, "change_pct": 0.5}
        for trade_date in calendar
    ]
    report = deep.build_deep_factor_report(
        events, daily_bars, calendar, memberships, sector_bars,
        min_consecutive_boards=3, draws=10, seed=1,
    )
    assert report["status"] == "ok"
    assert report["first_board_count"] == 2
    assert report["label_balance"]["positive"] == 1
    factor_keys = {item["factor_key"] for item in report["numeric_factor_ranking"]}
    assert "position_126d" in factor_keys
    assert "concept_max_limit_up_d" in factor_keys
    assert "prior_4_10d_return_pct" in factor_keys
    # 板块归属只在 600001 上 → 600002 的板块因子为空但被统计为缺失
    concept = next(
        item for item in report["numeric_factor_ranking"]
        if item["factor_key"] == "concept_max_limit_up_d"
    )
    assert concept["sample_count"] == 1
    # 市场情绪温度：当天 2 只封板、2 个首板
    market = next(
        item for item in report["numeric_factor_ranking"]
        if item["factor_key"] == "market_sealed_count_d"
    )
    assert market["positive_mean"] == 2
    assert market["negative_mean"] == 2
    # 组合评估：首行恒为全样本基线
    assert report["combos"][0]["combo"] == "__baseline__"
    assert report["combos"][0]["total"] == 2


def test_combo_evaluation_against_baseline() -> None:
    samples = [
        {
            "drawdown_from_126d_high_pct": -5.0,
            "is_early_seal": True,
            "board_type": "main",
            "concept_max_limit_up_d": 10.0,
            "concept_max_return_20d": 8.0,
            "float_market_cap": 5.0e9,
            "turnover_ratio_3d_vs_prev7d": 1.5,
            "is_leader": True,
            "d1_open_return_pct": 3.0,
        },
        {
            "drawdown_from_126d_high_pct": -50.0,
            "is_early_seal": False,
            "board_type": "chinext",
            "concept_max_limit_up_d": 80.0,
            "concept_max_return_20d": -3.0,
            "float_market_cap": 5.0e10,
            "turnover_ratio_3d_vs_prev7d": 0.8,
            "is_leader": False,
            "d1_open_return_pct": -2.0,
        },
    ]
    rows = {row["combo"]: row for row in deep.evaluate_combos(samples)}
    assert rows["__baseline__"]["total"] == 2
    assert rows["near_high_main"]["total"] == 1
    assert rows["near_high_main"]["leader_rate"] == 1.0
    assert rows["full_setup"]["total"] == 1
    assert rows["cold_sector_warm"]["leader_count"] == 1
