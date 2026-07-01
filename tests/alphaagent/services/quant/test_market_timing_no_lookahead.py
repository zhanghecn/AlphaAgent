"""断言 market_timing 模块无未来函数(所有特征只用 ≤t 数据)。

三类守护:
1. 窗口指标(rsi/volatility/volume_ratio): 篡改窗口外的值, 输出不变。
2. 递推指标(macd): 加未来尾巴, 过去位置的值不变。
3. 端到端 pipeline: 篡改后段数据, 前段信号事件完全不变。

任一被破坏(有人误把整序列/未来值塞进特征), 对应断言会挂。
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


# ---- 4. 端到端: 篡改后段, 前段信号事件不变 ----


def test_pipeline_prefix_stable_under_future_pollution():
    closes, turns = _gen_series(80, seed=6)
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(80)]

    def build(seq_c, seq_t):
        out = []
        for i in range(80):
            ctx = _StubCtx(dates[i])
            out.append(fac.compute_factors([ctx], seq_c[: i + 1], seq_t[: i + 1]))
        return out

    factor_full = build(closes, turns)
    events_full = sig.detect_events(factor_full)

    # 篡改后 40 天: 暴跌 + 缩量
    polluted_c = closes[:40] + [closes[39] * (0.9 ** (i - 39)) for i in range(40, 80)]
    polluted_t = turns[:40] + [1e8] * 40
    factor_poll = build(polluted_c, polluted_t)
    events_poll = sig.detect_events(factor_poll)

    split = dates[40]
    early_full = [e for e in events_full if e.trade_date < split]
    early_poll = [e for e in events_poll if e.trade_date < split]
    assert len(early_full) == len(early_poll), "前段事件数量被未来数据改变=未来函数泄露"
    for a, b in zip(early_full, early_poll):
        assert a.trade_date == b.trade_date
        assert a.direction == b.direction
        assert a.grade == b.grade
