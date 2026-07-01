"""大盘择时因子打分 v2(金手指/银手指)。

v1 教训: 银手指用「镜像 bull_force 低」在单边牛市完全失效(0% 胜率)。
v2 改为双独立合力分:
- ``bull_force``: 多头合力(趋势/动量/广度/波动结构/量能), 金手指弱档 v1 已验证 79% 胜率。
- ``bear_force``: 顶部空头合力, 用真正的「顶部结构」因子独立打分, 不再镜像:
  广度顶背离 / MACD 顶背离 / 放量滞涨 / 趋势破位。

无未来函数: ``compute_factors`` 接收截止当日(含)的切片:
- ``ctx_window``: 升序的 MarketContext 列表(用于广度趋势/顶背离, 需近 N 天)。
- ``closes``/``turnovers``: 截止当日的综合序列切片。
未来收益(t+1..t+20)绝不进入特征, 仅由 backtest 模块用作评估标签。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from alphaagent.server.services.quant.market_timing import series as ser

# 族权重(广度与趋势/动量并列最高, 因广度对 A 股顶底区分度最强)
W_TREND = 0.25
W_MOMENTUM = 0.25
W_BREADTH = 0.25
W_STRUCTURE = 0.15
W_VOLUME = 0.10

# bear_force 顶部因子权重
WB_BREADTH_TOP = 0.30   # 广度顶背离(A 股最可靠顶部信号)
WB_MACD_TOP = 0.25
WB_VOL_PRICE = 0.20     # 放量滞涨
WB_BREAKDOWN = 0.25     # 趋势破位


def clamp(v: float | None) -> float:
    if v is None or not math.isfinite(float(v)):
        return 0.0
    return round(max(0.0, min(100.0, float(v))), 4)


@dataclass(frozen=True)
class MarketTimingFactors:
    trade_date: date
    phase: str
    trend: float
    momentum: float
    breadth: float
    structure: float
    volume: float
    bull_force: float
    bear_force: float
    close_above_ma20: bool
    mom_5d: float | None
    mom_20d: float | None
    macd_top: float
    breadth_top: float
    evidence: dict[str, Any] = field(default_factory=dict)


# ---------------- 多头因子族 ----------------


def _macd_bull_score(hist_now: float | None, hist_prev: float | None) -> float:
    if hist_now is None:
        return 50.0
    score = 50.0 + max(min(hist_now * 60.0, 35.0), -35.0)
    if hist_prev is not None and hist_now > hist_prev:
        score += 8.0
    return clamp(score)


def _rsi_bull_score(rsi_v: float | None) -> float:
    return clamp(rsi_v) if rsi_v is not None else 50.0


def _structure_bull_score(
    vol_now: float | None,
    vol_avg: float | None,
    drawdown_60d: float | None,
    closes: list[float],
) -> float:
    """v2: 波动结构多头分。低波动 + 波动收敛 + 连阳 + 回撤可控。
    去掉 v1 的 ``100-risk``(牛市里 risk 也常偏高, 会拉低合力分, 致中强档触发不了)。"""
    base = 50.0
    if vol_now is not None:
        # vol_pct 为日收益率标准差(%), 牛市约 0.8~1.5。低波=稳步上行=多头
        base = clamp(72.0 - vol_now * 14.0)  # vol=0.8→61, vol=1.2→55, vol=2.0→44
    if vol_now is not None and vol_avg is not None and vol_now < vol_avg:
        base += 8.0  # 波动收敛=蓄势
    if len(closes) >= 3 and closes[-1] > closes[-2] > closes[-3]:
        base += 7.0  # 三连阳
    if drawdown_60d is not None and drawdown_60d > -5.0:
        base += 5.0  # 距 60 日高点回撤可控
    return clamp(base)


def _volume_bull_score(vr: float | None, closes: list[float]) -> float:
    if vr is None:
        return 50.0
    base = 50.0 + max(min((vr - 1.0) * 30.0, 30.0), -20.0)
    if len(closes) >= 2 and closes[-1] > closes[-2] and vr > 1.0:
        base += 10.0
    return clamp(base)


# ---------------- 顶部空头因子(独立, 不镜像 bull) ----------------


def _breadth_top_divergence(ctx_window: list[Any], closes: list[float]) -> float:
    """广度顶背离: 价格近 20 日上行, 但市场广度(站上 MA20 个股比)从高位回落。
    A 股顶部最可靠信号: 指数虚涨、强势股减少。返回 0-100, 越大越空。"""
    if len(ctx_window) < 6 or len(closes) < 21:
        return 50.0
    breadth_now = ctx_window[-1].breadth_score
    breadth_5d_ago = ctx_window[-6].breadth_score
    price_up_20d = closes[-1] > closes[-21]
    if breadth_now < breadth_5d_ago - 5.0:
        # 广度 5 日内下降 >5 点
        return 82.0 if price_up_20d else 60.0  # 价格涨+广度回落=经典顶背离
    if breadth_now < 35.0:
        return 68.0  # 广度本身已很弱(指数靠少数权重撑)
    return 38.0


def _macd_top_divergence(closes: list[float]) -> float:
    """MACD 顶背离: 近 20 日价格创新高, 但 MACD 柱峰值低于前 20 日峰值。"""
    if len(closes) < 40:
        return 50.0
    hist = ser.macd_hist(closes)
    recent_hist = [h for h in hist[-20:] if h is not None]
    prev_hist = [h for h in hist[-40:-20] if h is not None]
    if not recent_hist or not prev_hist:
        return 50.0
    price_peak_recent = max(closes[-20:])
    price_peak_prev = max(closes[-40:-20])
    hist_peak_recent = max(recent_hist)
    hist_peak_prev = max(prev_hist)
    if price_peak_recent > price_peak_prev and hist_peak_recent < hist_peak_prev * 0.9:
        return 80.0  # 价格新高、MACD 柱走低=顶背离
    if price_peak_recent > price_peak_prev and hist_peak_recent < hist_peak_prev:
        return 62.0
    return 42.0


def _volume_price_divergence(turnovers: list[float], closes: list[float]) -> float:
    """放量滞涨: 近 5 日均量显著放大, 但价格 5 日涨幅极小甚至下跌(量价背离)。"""
    if len(turnovers) < 25 or len(closes) < 6:
        return 50.0
    recent_vol = sum(turnovers[-5:]) / 5
    avg_vol = sum(turnovers[-21:-1]) / 20
    if avg_vol <= 0:
        return 50.0
    vol_ratio = recent_vol / avg_vol
    price_chg_5d = (closes[-1] / closes[-6] - 1.0) * 100.0
    if vol_ratio > 1.2 and price_chg_5d < 1.0:
        return 76.0
    if vol_ratio > 1.1 and price_chg_5d < 0.0:
        return 64.0
    return 38.0


def _trend_breakdown(closes: list[float]) -> float:
    """趋势破位: 跌破 MA20 + MA5<MA20 + (可选)跌破 MA60 + 连阴。"""
    if len(closes) < 25:
        return 50.0
    ma5 = ser.sma(closes, 5)
    ma20 = ser.sma(closes, 20)
    ma60 = ser.sma(closes, 60) if len(closes) >= 60 else None
    close = closes[-1]
    score = 28.0
    if ma20 and close < ma20:
        score += 25.0
    if ma5 and ma20 and ma5 < ma20:
        score += 20.0
    if ma60 and close < ma60:
        score += 15.0
    if len(closes) >= 3 and closes[-1] < closes[-2] < closes[-3]:
        score += 10.0
    return clamp(score)


def _phase_of(ctx: Any) -> str:
    from alphaagent.server.services.quant.market_context import classify_trading_market_phase

    payload = ctx.to_dict() if hasattr(ctx, "to_dict") else dict(ctx)
    return str(classify_trading_market_phase(payload).get("phase") or "unknown")


def compute_factors(
    ctx_window: list[Any],
    closes: list[float],
    turnovers: list[float],
) -> MarketTimingFactors:
    """计算单日因子(v2)。

    Args:
        ctx_window: 截止当日(含)升序的 ``MarketContext`` 列表(需 ≥6 天以算广度趋势)。
        closes / turnovers: 截止当日(含)的综合序列切片。
    """
    if not ctx_window:
        raise ValueError("ctx_window 不能为空")
    ctx = ctx_window[-1]

    # ---- 多头合力 bull_force ----
    trend = clamp(ctx.trend_score)
    hist_series = ser.macd_hist(closes)
    hist_now = hist_series[-1] if hist_series else None
    hist_prev = hist_series[-2] if len(hist_series) >= 2 else None
    macd_score = _macd_bull_score(hist_now, hist_prev)
    rsi_v = ser.rsi(closes)
    momentum = clamp(0.5 * ctx.momentum_score + 0.25 * macd_score + 0.25 * _rsi_bull_score(rsi_v))
    breadth = clamp(ctx.breadth_score)
    vol_now = ser.volatility_pct(closes)
    # 近 20 日波动均值(不含今天)用于"波动收敛"判断
    vol_avg = ser.volatility_pct(closes[:-1]) if len(closes) > 21 else None
    structure = _structure_bull_score(vol_now, vol_avg, ctx.drawdown_60d_pct, closes)
    vr = ser.volume_ratio(turnovers)
    volume_score = _volume_bull_score(vr, closes)

    # 趋势顺势 + 多周期动量(供 signal 做顺势/共振过滤)
    ma20 = ser.sma(closes, 20)
    close_above_ma20 = bool(ma20 is not None and closes[-1] > ma20)
    mom_5d = ser.period_return_pct(closes, 5)
    mom_20d = ser.period_return_pct(closes, 20)
    bull_force = clamp(
        W_TREND * trend
        + W_MOMENTUM * momentum
        + W_BREADTH * breadth
        + W_STRUCTURE * structure
        + W_VOLUME * volume_score
    )

    # ---- 顶部空头合力 bear_force(独立) ----
    bd = _breadth_top_divergence(ctx_window, closes)
    md = _macd_top_divergence(closes)
    vpd = _volume_price_divergence(turnovers, closes)
    tbd = _trend_breakdown(closes)
    bear_force = clamp(
        WB_BREADTH_TOP * bd + WB_MACD_TOP * md + WB_VOL_PRICE * vpd + WB_BREAKDOWN * tbd
    )

    return MarketTimingFactors(
        trade_date=ctx.trade_date,
        phase=_phase_of(ctx),
        trend=trend,
        momentum=momentum,
        breadth=breadth,
        structure=structure,
        volume=volume_score,
        bull_force=bull_force,
        bear_force=bear_force,
        close_above_ma20=close_above_ma20,
        mom_5d=mom_5d,
        mom_20d=mom_20d,
        macd_top=md,
        breadth_top=bd,
        evidence={
            "macd_hist": hist_now,
            "rsi": rsi_v,
            "vol_pct": vol_now,
            "volume_ratio": vr,
            "market_score": ctx.market_score,
            "risk_score": ctx.risk_score,
            "vol_price_div": vpd,
            "trend_breakdown": tbd,
            "regime": ctx.regime,
        },
    )
