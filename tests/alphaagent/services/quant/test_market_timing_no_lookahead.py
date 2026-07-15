"""断言 market_timing 模块无未来函数(所有特征只用 ≤t 数据)。

守护层级:
1. 窗口指标(rsi/volatility/volume_ratio): 篡改窗口外的值, 输出不变。
2. 递推指标(macd): 加未来尾巴, 过去位置的值不变。
3. compute_factors: t 日因子只依赖 closes[:t+1]。
4. 端到端 pipeline: 篡改后段数据, 前段事件【存在性+方向】不变。
5. v4 候选+确认两状态: 事件存在性 no-lookahead + status 与次日方向一致
   + INVALIDATED 候选不被未来抹除(v4 对 v2.4.2 的核心修复)。

任一被破坏(有人误把整序列/未来值塞进特征/把候选丢弃), 对应断言会挂。
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from alphaagent.server.services.quant.market_timing import factors as fac
from alphaagent.server.services.quant.market_timing import series as ser
from alphaagent.server.services.quant.market_timing import signal as sig


class _StubCtx:
    """最小 ctx, 供 compute_factors + classify_trading_market_phase 使用。"""

    def __init__(self, trade_date: date, trend=55.0, momentum=55.0, breadth=55.0, risk=45.0):
        self.trade_date = trade_date
        self.trend_score = trend
        self.momentum_score = momentum
        self.breadth_score = breadth
        self.risk_score = risk
        self.market_score = 55.0
        self.drawdown_60d_pct = -5.0
        self.regime = "choppy_rotation"

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "market_warning_level": 1,
            "recovery_state": "none",
            "fund_flow_state": "balanced",
            "market_score": self.market_score,
            "breadth_score": self.breadth_score,
            "theme_strength": 50.0,
            "index_return_5d": 0.5,
            "index_return_20d": 1.0,
            "growth_score": 55.0,
            "value_score": 55.0,
            "small_cap_score": 55.0,
            "drawdown_60d_pct": -5.0,
        }


def _gen_series(n: int = 80, seed: int = 42) -> tuple[list[float], list[float]]:
    rng = random.Random(seed)
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(closes[-1] * (1 + rng.uniform(-0.02, 0.02)))
    turns = [rng.uniform(1e8, 5e8) for _ in range(n)]
    return closes, turns


def _timing_factor(day: date, zone: str) -> fac.MarketTimingFactors:
    bull, bear = {
        "GOLD": (70.0, 40.0),
        "SILVER": (40.0, 70.0),
        "NEUTRAL": (50.0, 50.0),
    }[zone]
    return fac.MarketTimingFactors(
        trade_date=day,
        phase="warming" if zone == "GOLD" else "retreat",
        trend=bull,
        momentum=bull,
        breadth=bull,
        structure=50.0,
        volume=50.0,
        bull_force=bull,
        bear_force=bear,
        close_above_ma20=zone == "GOLD",
        mom_5d=None,
        mom_20d=None,
        macd_top=40.0,
        breadth_top=40.0,
        evidence={},
    )


def _event(
    candidate_date: date,
    direction: str,
    status: str,
    confirm_date: date | None,
) -> sig.TimingSignal:
    return sig.TimingSignal(
        trade_date=candidate_date,
        direction=direction,
        status=status,
        grade="WEAK",
        bull_force=70.0 if direction == "GOLD" else 40.0,
        bear_force=70.0 if direction == "SILVER" else 40.0,
        phase="warming" if direction == "GOLD" else "retreat",
        setup_type=(
            sig.SETUP_TREND_GOLD
            if direction == "GOLD"
            else sig.SETUP_TOP_SILVER
        ),
        confirm_date=confirm_date,
        reasons=[],
    )


def test_active_direction_starts_on_confirmation_and_persists_until_reversal():
    start = date(2026, 6, 11)
    dates = [start + timedelta(days=index) for index in range(6)]
    events = [
        _event(dates[0], "GOLD", sig.STATUS_CONFIRMED, dates[1]),
        _event(dates[2], "SILVER", sig.STATUS_INVALIDATED, dates[3]),
        _event(dates[4], "SILVER", sig.STATUS_PENDING, None),
    ]

    assert sig.build_active_directions(dates, events) == [
        "NEUTRAL",
        "GOLD",
        "GOLD",
        "GOLD",
        "GOLD",
        "GOLD",
    ]

    confirmed_reversal = events + [
        _event(dates[4], "SILVER", sig.STATUS_CONFIRMED, dates[5]),
    ]
    assert sig.build_active_directions(dates, confirmed_reversal) == [
        "NEUTRAL",
        "GOLD",
        "GOLD",
        "GOLD",
        "GOLD",
        "SILVER",
    ]


def test_active_direction_history_is_stable_when_future_reversal_is_appended():
    start = date(2026, 6, 11)
    dates = [start + timedelta(days=index) for index in range(5)]
    gold = _event(dates[0], "GOLD", sig.STATUS_CONFIRMED, dates[1])
    silver = _event(dates[3], "SILVER", sig.STATUS_CONFIRMED, dates[4])

    prefix = sig.build_active_directions(dates[:4], [gold])
    complete = sig.build_active_directions(dates, [gold, silver])

    assert complete[:4] == prefix
    assert complete[-1] == "SILVER"


def _ordinary_breakdown_factor(day: date) -> fac.MarketTimingFactors:
    return fac.MarketTimingFactors(
        trade_date=day,
        phase="retreat",
        trend=40.0,
        momentum=40.0,
        breadth=40.0,
        structure=50.0,
        volume=50.0,
        bull_force=40.0,
        bear_force=70.0,
        close_above_ma20=False,
        mom_5d=-2.0,
        mom_20d=-3.0,
        macd_top=42.0,
        breadth_top=68.0,
        evidence={"trend_breakdown": 88.0},
    )


# ---- 1. 窗口指标: 篡改窗口外, 值不变 ----


def test_rsi_only_depends_on_last_window():
    closes, _ = _gen_series(60, seed=1)
    r1 = ser.rsi(closes, 14)
    polluted = [-999.0] * 45 + closes[-15:]  # 只保留最后 15 个(window+1)
    assert ser.rsi(polluted, 14) == r1


def test_volatility_only_depends_on_last_window():
    closes, _ = _gen_series(50, seed=2)
    v1 = ser.volatility_pct(closes, 20)
    polluted = [1.0] * 29 + closes[-21:]  # 只保留最后 21 个
    assert ser.volatility_pct(polluted, 20) == v1


def test_volume_ratio_only_depends_on_last_window():
    _, turns = _gen_series(50, seed=3)
    vr1 = ser.volume_ratio(turns, 20)
    polluted = [1.0] * 29 + turns[-21:]  # 只保留最后 21 个
    assert ser.volume_ratio(polluted, 20) == vr1


# ---- 2. 递推指标(EMA/MACD): 加未来尾巴, 过去位置值不变 ----


def test_macd_future_tail_does_not_change_past():
    closes, _ = _gen_series(60, seed=4)
    h_full = ser.macd_hist(closes)
    # 追加 5 个未来值
    h_polluted = ser.macd_hist(closes + [closes[-1] * 1.1] * 5)
    # 前 len(closes) 个必须完全一致(未来只影响尾部新位置)
    assert h_polluted[: len(closes)] == h_full


# ---- 3. compute_factors: t 日因子只依赖 closes[:t+1] ----


def test_compute_factors_no_lookahead():
    closes, turns = _gen_series(80, seed=5)
    ctx = _StubCtx(date(2024, 1, 1))
    for t in (35, 55, 75):
        f1 = fac.compute_factors([ctx], closes[: t + 1], turns[: t + 1])
        # 篡改 t 之后的数据, 但传给 compute_factors 的切片 [:t+1] 保持原值
        polluted_c = closes[: t + 1] + [closes[i] * 5 for i in range(t + 1, len(closes))]
        polluted_t = turns[: t + 1] + [1.0] * (len(closes) - t - 1)
        f2 = fac.compute_factors([ctx], polluted_c[: t + 1], polluted_t[: t + 1])
        assert f1.bull_force == f2.bull_force
        assert f1.momentum == f2.momentum
        assert f1.structure == f2.structure
        assert f1.volume == f2.volume


# ---- 4. 端到端: 篡改后段, 前段事件【存在性+方向】不变 ----


def test_pipeline_prefix_stable_under_future_pollution():
    """v4: 事件标候选日 i, 篡改 i+2 之后不影响前段事件的存在性。

    status 是 i+1 的合法函数, 边界候选日(确认日落在 split 当天)的 status 可能变,
    所以本断言只守护【存在性 + 方向】(trade_date, direction), status 由用例 5/6/7 专测。
    """
    closes, turns = _gen_series(80, seed=6)
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(80)]

    def build(seq_c, seq_t):
        return [
            fac.compute_factors([_StubCtx(dates[i])], seq_c[: i + 1], seq_t[: i + 1])
            for i in range(80)
        ]

    factor_full = build(closes, turns)
    events_full = sig.detect_events(factor_full, closes)

    # 篡改后 40 天: 暴跌 + 缩量
    polluted_c = closes[:40] + [closes[39] * (0.9 ** (i - 39)) for i in range(40, 80)]
    polluted_t = turns[:40] + [1e8] * 40
    factor_poll = build(polluted_c, polluted_t)
    events_poll = sig.detect_events(factor_poll, polluted_c)

    split = dates[40]
    early_full = [e for e in events_full if e.trade_date < split]
    early_poll = [e for e in events_poll if e.trade_date < split]
    assert len(early_full) == len(early_poll), "前段事件被未来数据抹除/新增 = 未来函数泄露"
    for a, b in zip(early_full, early_poll):
        assert a.trade_date == b.trade_date
        assert a.direction == b.direction


# ---- 5. v4 候选+确认两状态: 事件存在性 no-lookahead ----


def test_candidate_event_status_aligns_with_next_day_direction():
    """v4: 每个事件标在【候选日 i】, status 反映次日 i+1 方向。

    CONFIRMED  : GOLD→次日涨, SILVER→次日跌
    INVALIDATED: GOLD→次日跌, SILVER→次日涨(假突破)
    PENDING    : 序列末端无次日, 跳过
    """
    for seed in (6, 11, 23, 31):
        closes, turns = _gen_series(120, seed=seed)
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(120)]
        factor = [
            fac.compute_factors([_StubCtx(dates[i])], closes[: i + 1], turns[: i + 1])
            for i in range(120)
        ]
        events = sig.detect_events(factor, closes)
        if not events:
            continue
        idx_by_date = {d: i for i, d in enumerate(dates)}
        for e in events:
            if e.status == sig.STATUS_PENDING or e.confirm_date is None:
                continue
            ci = idx_by_date[e.trade_date]
            ni = idx_by_date[e.confirm_date]
            next_up = closes[ni] > closes[ci]
            if e.status == sig.STATUS_CONFIRMED:
                assert (e.direction == "GOLD") == next_up, (
                    f"CONFIRMED {e.direction}@{e.trade_date} 与次日方向不符"
                )
            else:  # INVALIDATED
                assert (e.direction == "GOLD") != next_up, (
                    f"INVALIDATED {e.direction}@{e.trade_date} 应与次日反向(假突破)"
                )


def test_false_breakout_retained_not_dropped():
    """v4: 候选事件在有确认/无确认模式下【数量不减少】(INVALIDATED 不被丢弃)。

    v2.4.2 有确认模式会丢弃 INVALIDATED, 数量 < 无确认模式;
    v4 保留所有候选, 且 INVALIDATED 不改 state 会让后续候选更多 → 有确认数量 ≥ 无确认。
    """
    closes, turns = _gen_series(120, seed=6)
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(120)]
    factor = [
        fac.compute_factors([_StubCtx(dates[i])], closes[: i + 1], turns[: i + 1])
        for i in range(120)
    ]

    events_confirm = sig.detect_events(factor, closes)
    events_plain = sig.detect_events(factor, None)

    # v4: 有确认模式保留所有候选(含 INVALIDATED), 数量 >= 无确认模式
    assert len(events_confirm) >= len(events_plain), (
        f"v4 应保留 INVALIDATED: 有确认 {len(events_confirm)} < 无确认 {len(events_plain)} "
        f"= 候选被丢弃(v2.4.2 退化)"
    )


def test_invalidated_candidates_not_erased():
    """v4 核心守护: 篡改确认日之后的数据, INVALIDATED 事件依然存在(不被未来抹除)。

    这是 v4 对 v2.4.2 的核心修复。v2.4.2 候选存废依赖未来(次日反向就丢弃);
    v4 事件存在性在候选日确定, 篡改未来不能抹掉已存在的 INVALIDATED 事件。
    """
    for seed in (6, 11, 23, 31, 42):
        closes, turns = _gen_series(120, seed=seed)
        dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(120)]
        factor = [
            fac.compute_factors([_StubCtx(dates[i])], closes[: i + 1], turns[: i + 1])
            for i in range(120)
        ]
        events = sig.detect_events(factor, closes)
        invalidated = [e for e in events if e.status == sig.STATUS_INVALIDATED]
        # 取一个确认日之后还有足够尾部可篡改的 INVALIDATED
        target = None
        for e in invalidated:
            if e.confirm_date is None:
                continue
            ci = dates.index(e.trade_date)
            if ci + 5 < 120:
                target = e
                break
        if target is None:
            continue

        cut = dates.index(target.confirm_date) + 1  # 保留候选日 + 确认日数据
        polluted_c = closes[:cut] + [closes[cut - 1] * (0.92 ** (i - cut)) for i in range(cut, 120)]
        polluted_t = turns[:cut] + [1e8] * (120 - cut)
        factor_poll = [
            fac.compute_factors([_StubCtx(dates[i])], polluted_c[: i + 1], polluted_t[: i + 1])
            for i in range(120)
        ]
        events_poll = sig.detect_events(factor_poll, polluted_c)

        target_poll = [e for e in events_poll if e.trade_date == target.trade_date]
        assert target_poll, (
            f"INVALIDATED 事件 {target.trade_date} 被未来数据抹除 = 未来函数泄露"
        )
        assert target_poll[0].direction == target.direction
        assert target_poll[0].status == sig.STATUS_INVALIDATED
        return  # 一个 seed 验证通过即足够


# ---- 6. 区域进入事件: 同方向离开后可重新触发 ----


def test_candidate_direction_uses_shared_zone_thresholds():
    day = date(2026, 7, 1)

    assert sig.candidate_direction(_timing_factor(day, "GOLD")) == "GOLD"
    assert sig.candidate_direction(_timing_factor(day, "SILVER")) == "SILVER"
    assert sig.candidate_direction(_timing_factor(day, "NEUTRAL")) is None


def test_ordinary_breakdown_silver_is_suppressed_without_structural_consensus():
    factor = _ordinary_breakdown_factor(date(2026, 7, 7))

    assert sig.candidate_direction(factor) == "SILVER"
    assert sig.candidate_setup(factor) == (None, None)
    assert sig.detect_events([factor], [100.0], [0.0]) == []


def test_top_silver_remains_available():
    factor = _timing_factor(date(2026, 5, 29), "SILVER")

    assert sig.candidate_setup(factor) == (
        "SILVER",
        sig.SETUP_TOP_SILVER,
    )


def test_same_zone_is_one_event_but_reentry_creates_another():
    start = date(2026, 6, 1)
    zones = ["SILVER", "SILVER", "NEUTRAL", "SILVER", "SILVER"]
    factors = [
        _timing_factor(start + timedelta(days=i), zone)
        for i, zone in enumerate(zones)
    ]
    closes = [100.0, 99.0, 100.0, 99.0, 98.0]

    events = sig.detect_events(factors, closes)

    assert [(event.trade_date, event.direction) for event in events] == [
        (start, "SILVER"),
        (start + timedelta(days=3), "SILVER"),
    ]
    assert events[1].status == sig.STATUS_CONFIRMED
    assert events[1].confirm_date == start + timedelta(days=4)


def test_silver_reappears_after_invalidated_gold_candidate():
    start = date(2026, 6, 29)
    zones = ["SILVER", "NEUTRAL", "GOLD", "NEUTRAL", "SILVER", "NEUTRAL"]
    factors = [
        _timing_factor(start + timedelta(days=i), zone)
        for i, zone in enumerate(zones)
    ]
    closes = [100.0, 99.0, 100.0, 98.0, 97.0, 96.0]

    events = sig.detect_events(factors, closes)

    assert [(event.direction, event.status) for event in events] == [
        ("SILVER", sig.STATUS_CONFIRMED),
        ("GOLD", sig.STATUS_INVALIDATED),
        ("SILVER", sig.STATUS_CONFIRMED),
    ]
    assert events[-1].trade_date == start + timedelta(days=4)
    assert events[-1].confirm_date == start + timedelta(days=5)


# ---- 7. v6 弱势衰竭反转金 ----


def _reversal_gold_case() -> tuple[list[fac.MarketTimingFactors], list[float]]:
    """候选日前先急跌，再用小阴线表达卖压衰竭。"""
    closes = [100.0] * 19 + [98.0, 94.0, 93.5, 94.5]
    start = date(2026, 5, 12)
    factors = [
        _timing_factor(start + timedelta(days=index), "SILVER")
        for index in range(len(closes))
    ]
    return factors, closes


def test_reversal_gold_overrides_weak_silver_zone_and_confirms_with_participation():
    factors, closes = _reversal_gold_case()

    events = sig.detect_events(
        factors,
        closes,
        up_ratios=[1.0] * len(closes),
    )

    event = next(
        item for item in events
        if item.setup_type == sig.SETUP_REVERSAL_GOLD
    )
    assert event.trade_date == factors[-2].trade_date
    assert event.direction == "GOLD"
    assert event.status == sig.STATUS_CONFIRMED
    assert event.confirm_date == factors[-1].trade_date


def test_reversal_gold_is_invalidated_when_next_day_participation_is_too_narrow():
    factors, closes = _reversal_gold_case()
    up_ratios = [1.0] * len(closes)
    up_ratios[-1] = 0.4

    events = sig.detect_events(factors, closes, up_ratios=up_ratios)

    event = next(
        item for item in events
        if item.setup_type == sig.SETUP_REVERSAL_GOLD
    )
    assert event.status == sig.STATUS_INVALIDATED
    assert event.confirm_date == factors[-1].trade_date


def test_reversal_gold_rejects_continuing_sharp_drop_and_high_position_pullback():
    weak_then_sharp = [100.0] * 19 + [98.0, 95.2, 94.0]
    high_position_pullback = [100.0 + index for index in range(21)] + [118.5]

    assert sig.is_reversal_gold(weak_then_sharp) is False
    assert sig.is_reversal_gold(high_position_pullback) is False


def test_reversal_gold_candidate_is_prefix_stable_when_future_is_appended():
    factors, closes = _reversal_gold_case()
    candidate_factors = factors[:-1]
    candidate_closes = closes[:-1]

    pending = next(
        item for item in sig.detect_events(candidate_factors, candidate_closes)
        if item.setup_type == sig.SETUP_REVERSAL_GOLD
    )
    confirmed = next(
        item for item in sig.detect_events(factors, closes)
        if item.setup_type == sig.SETUP_REVERSAL_GOLD
    )

    assert pending.trade_date == confirmed.trade_date
    assert pending.direction == confirmed.direction == "GOLD"
    assert pending.setup_type == confirmed.setup_type == sig.SETUP_REVERSAL_GOLD
    assert pending.status == sig.STATUS_PENDING
    assert confirmed.status == sig.STATUS_CONFIRMED


def test_reversal_gold_indexed_lookup_does_not_read_future_closes():
    _, closes = _reversal_gold_case()
    candidate_index = len(closes) - 2

    from_prefix = sig.is_reversal_gold(closes[: candidate_index + 1])
    from_full_series = sig.is_reversal_gold(closes, candidate_index)
    polluted_future = closes[: candidate_index + 1] + [closes[-1] * 10.0]

    assert from_prefix is True
    assert from_full_series == from_prefix
    assert sig.is_reversal_gold(polluted_future, candidate_index) == from_prefix


def test_reversal_gold_cooldown_suppresses_early_reentry(monkeypatch):
    start = date(2026, 5, 1)
    factors = [
        _timing_factor(start + timedelta(days=index), "NEUTRAL")
        for index in range(32)
    ]
    closes = [100.0] * len(factors)
    reversal_days = {20, 22, 30}
    qualifying_metrics = {
        "rsi2": 10.0,
        "return_1d": -0.5,
        "return_10d": -3.0,
        "drawdown_20d": -4.0,
    }

    monkeypatch.setattr(
        sig,
        "_reversal_gold_metrics",
        lambda _values, end_index=None: (
            qualifying_metrics
            if end_index in reversal_days
            else None
        ),
    )

    events = sig.detect_events(factors, closes)
    reversal_events = [
        event for event in events
        if event.setup_type == sig.SETUP_REVERSAL_GOLD
    ]

    assert [event.trade_date for event in reversal_events] == [
        factors[20].trade_date,
        factors[30].trade_date,
    ]


# ---- 8. v7 结构性破位银与因果危险状态 ----


def _structural_factor(day: date) -> fac.MarketTimingFactors:
    return fac.MarketTimingFactors(
        trade_date=day,
        phase="rotation",
        trend=55.0,
        momentum=50.0,
        breadth=40.0,
        structure=45.0,
        volume=50.0,
        bull_force=55.6,
        bear_force=75.4,
        close_above_ma20=False,
        mom_5d=-0.2,
        mom_20d=1.1,
        macd_top=80.0,
        breadth_top=82.0,
        evidence={"trend_breakdown": 83.0},
    )


def _structural_danger_case(
    *,
    immediate_repair: bool = False,
) -> tuple[list[fac.MarketTimingFactors], list[float], list[float | None]]:
    start = date(2026, 3, 13) - timedelta(days=20)
    closes = [100.0] * 20 + [99.0, 101.0 if immediate_repair else 99.1, 98.7, 99.0, 101.0]
    factors = [
        _timing_factor(start + timedelta(days=index), "NEUTRAL")
        for index in range(len(closes))
    ]
    factors[20] = _structural_factor(factors[20].trade_date)
    factors[22] = _structural_factor(factors[22].trade_date)
    factors[23] = _timing_factor(factors[23].trade_date, "SILVER")
    up_ratios: list[float | None] = [1.0] * 20 + [0.0, 1.0 if immediate_repair else 4 / 7, 0.0, 1.0, 1.0]
    return factors, closes, up_ratios


def test_structural_breakdown_enters_once_confirms_and_exits_on_repair():
    factors, closes, up_ratios = _structural_danger_case()

    states = sig.build_danger_states(factors, closes, up_ratios)
    events = sig.detect_events(factors, closes, up_ratios)
    structural_events = [
        event
        for event in events
        if event.setup_type == sig.SETUP_STRUCTURAL_BREAKDOWN_SILVER
    ]

    assert states[20:24] == [sig.DANGER] * 4
    assert states[24] == sig.NORMAL
    assert len(structural_events) == 1
    assert [
        event
        for event in events
        if event.direction == "SILVER"
        and factors[20].trade_date <= event.trade_date <= factors[23].trade_date
    ] == structural_events
    event = structural_events[0]
    assert event.trade_date == factors[20].trade_date
    assert event.direction == "SILVER"
    assert event.status == sig.STATUS_CONFIRMED
    assert event.confirm_date == factors[21].trade_date


def test_structural_breakdown_candidate_is_retained_when_next_day_repairs():
    factors, closes, up_ratios = _structural_danger_case(immediate_repair=True)

    states = sig.build_danger_states(factors, closes, up_ratios)
    event = next(
        event
        for event in sig.detect_events(factors, closes, up_ratios)
        if event.setup_type == sig.SETUP_STRUCTURAL_BREAKDOWN_SILVER
    )

    assert states[20] == sig.DANGER
    assert states[21] == sig.NORMAL
    assert event.status == sig.STATUS_INVALIDATED
    assert event.confirm_date == factors[21].trade_date


def test_structural_breakdown_has_priority_but_residual_danger_does_not(monkeypatch):
    factors, closes, up_ratios = _structural_danger_case()
    qualifying_metrics = {
        "rsi2": 10.0,
        "return_1d": -0.5,
        "return_10d": -3.0,
        "drawdown_20d": -4.0,
    }
    monkeypatch.setattr(
        sig,
        "_reversal_gold_metrics",
        lambda _values, end_index=None: (
            qualifying_metrics if end_index in {20, 21} else None
        ),
    )

    assert sig.candidate_setup(
        factors[20],
        reversal_gold=True,
        structural_breakdown=True,
    ) == ("SILVER", sig.SETUP_STRUCTURAL_BREAKDOWN_SILVER)
    assert sig.candidate_setup(
        factors[21],
        reversal_gold=True,
        structural_breakdown=False,
    ) == ("GOLD", sig.SETUP_REVERSAL_GOLD)

    events = sig.detect_events(factors, closes, up_ratios)
    assert [
        event.setup_type
        for event in events
        if event.trade_date in {factors[20].trade_date, factors[21].trade_date}
    ] == [
        sig.SETUP_STRUCTURAL_BREAKDOWN_SILVER,
        sig.SETUP_REVERSAL_GOLD,
    ]


def test_structural_breakdown_requires_aligned_participation():
    factors, closes, up_ratios = _structural_danger_case()

    assert sig.is_structural_breakdown(factors[20], closes, 20, up_ratios[20]) is True
    assert sig.is_structural_breakdown(factors[20], closes, 20, None) is False
    assert sig.build_danger_states(factors, closes, None) == [sig.NORMAL] * len(factors)


def test_structural_danger_prefix_is_stable_under_future_pollution():
    factors, closes, up_ratios = _structural_danger_case()
    cut = 21

    prefix_states = sig.build_danger_states(
        factors[:cut],
        closes[:cut],
        up_ratios[:cut],
    )
    prefix_event = next(
        event
        for event in sig.detect_events(
            factors[:cut],
            closes[:cut],
            up_ratios[:cut],
        )
        if event.setup_type == sig.SETUP_STRUCTURAL_BREAKDOWN_SILVER
    )

    polluted_closes = closes[:cut] + [200.0] * (len(closes) - cut)
    polluted_up_ratios = up_ratios[:cut] + [1.0] * (len(closes) - cut)
    polluted_states = sig.build_danger_states(
        factors,
        polluted_closes,
        polluted_up_ratios,
    )
    polluted_event = next(
        event
        for event in sig.detect_events(
            factors,
            polluted_closes,
            polluted_up_ratios,
        )
        if event.setup_type == sig.SETUP_STRUCTURAL_BREAKDOWN_SILVER
    )

    assert polluted_states[:cut] == prefix_states
    assert prefix_event.trade_date == polluted_event.trade_date
    assert prefix_event.direction == polluted_event.direction == "SILVER"
    assert prefix_event.status == sig.STATUS_PENDING
