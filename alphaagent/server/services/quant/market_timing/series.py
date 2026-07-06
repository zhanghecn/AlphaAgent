"""大盘综合指数序列与补充技术指标(金手指/银手指择时用)。

设计要点
--------
- 用 ``INDEX_WEIGHTS`` 对 7 大指数的「日收益率」加权, 再 cumprod 成综合序列,
  避免不同指数量纲(上证 4000 点 vs 科创50 ~1000)直接加权失真。
- 只保留 7 指数共同覆盖的交易日, 保证每日 prev_close 对齐, 无跨天收益。
- 所有指标函数只用传入序列的「尾部」(≤t), 杜绝未来函数。调用方传 ``closes[:t+1]``。
- MACD/RSI/波动率/量能是 ``market_context`` 未覆盖的补充指标; trend/momentum/
  breadth/risk 直接复用 ``compute_market_contexts`` 的得分(已保证无未来), 见 factors.py。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select

from alphaagent.market.providers import RealMarketDataClient, _china_today, _is_intraday_china
from alphaagent.market.symbols import INDEX_SYMBOLS
from alphaagent.server.services.quant.market_context import INDEX_WEIGHTS


@dataclass(frozen=True)
class CompositeBar:
    """大盘综合指数单日数据。close 为基期 100 起算的累计序列。"""

    trade_date: date
    close: float
    turnover: float
    return_pct: float


def load_composite_series(
    session: Any, schema: Any, start: date, end: date
) -> list[CompositeBar]:
    """加载 7 指数日线, 按日收益率加权成综合序列, 返回按 trade_date 升序。"""
    vt_symbols = [f"{it['symbol']}.{it['exchange']}" for it in INDEX_SYMBOLS]
    table = schema.stock_daily_bars
    rows = session.execute(
        select(table.c.vt_symbol, table.c.trade_date, table.c.close_price, table.c.turnover)
        .where(table.c.vt_symbol.in_(vt_symbols))
        .where(table.c.trade_date >= start)
        .where(table.c.trade_date <= end)
        .order_by(table.c.vt_symbol, table.c.trade_date)
    ).all()

    close_by: dict[str, dict[date, float]] = {}
    turn_by: dict[str, dict[date, float]] = {}
    for vt, d, close, turnover in rows:
        if close is None:
            continue
        sym = str(vt)
        close_by.setdefault(sym, {})[d] = float(close)
        turn_by.setdefault(sym, {})[d] = float(turnover or 0.0)

    weighted_syms = [s for s in INDEX_WEIGHTS if s in close_by]
    if not weighted_syms:
        return []
    date_sets = [set(close_by[s].keys()) for s in weighted_syms]
    common = sorted(set.intersection(*date_sets))

    series: list[CompositeBar] = []
    prev_close: dict[str, float] = {}
    composite = 100.0
    for d in common:
        weighted_ret = 0.0
        weight_sum = 0.0
        weighted_turnover = 0.0
        for sym in weighted_syms:
            w = INDEX_WEIGHTS[sym]
            c = close_by[sym][d]
            weighted_turnover += w * turn_by[sym].get(d, 0.0)
            pc = prev_close.get(sym)
            if pc:
                weighted_ret += w * (c / pc - 1.0)
                weight_sum += w
            prev_close[sym] = c
        ret = (weighted_ret / weight_sum) if weight_sum > 0 else 0.0
        composite = composite * (1.0 + ret)
        series.append(CompositeBar(d, composite, weighted_turnover, ret * 100.0))
    return series


def intraday_today_bar(prev_close: float, prev_turnover: float) -> CompositeBar | None:
    """盘中拉七大指数实时点位, 加权合成今天的 composite bar。

    用 ``change_pct`` 算每个指数的日收益率(等价 (last-prev_close)/prev_close),
    按 INDEX_WEIGHTS 加权, 基于昨日 composite close 累乘得到今天。

    返回 None 的情形(调用方退化为纯昨日 panel):
    - 非交易时段(周末/盘前/盘后)
    - 实时源拉取失败
    - 所有指数 volume=0(节假日/半天/异常停牌)

    注意: 这是「实时预警」用途的近似 bar, 不写 DB; 18:00 eod 同步今天日线后,
    load_composite_series 会读到正式日线, 本函数在 last_date>=today 时不再追加。
    """
    if not _is_intraday_china():
        return None
    try:
        quotes = RealMarketDataClient().get_indices() or []
    except Exception:  # noqa: BLE001  实时源不可用则退回昨日 panel
        return None
    qmap = {q.vt_symbol: q for q in quotes}
    weighted_ret = 0.0
    weight_sum = 0.0
    weighted_turnover = 0.0
    any_volume = False
    for sym, w in INDEX_WEIGHTS.items():
        q = qmap.get(sym)
        if not q or q.last_price is None:
            continue
        if q.change_pct is not None:
            ret = q.change_pct / 100.0
        elif q.previous_close:
            ret = q.last_price / q.previous_close - 1.0
        else:
            continue
        weighted_ret += w * ret
        weight_sum += w
        if q.turnover:
            weighted_turnover += w * q.turnover
        if q.volume and q.volume > 0:
            any_volume = True
    if weight_sum <= 0 or not any_volume:
        return None
    ret = weighted_ret / weight_sum
    today = _china_today()
    close = prev_close * (1.0 + ret)
    turnover = weighted_turnover if weighted_turnover > 0 else prev_turnover
    return CompositeBar(today, close, turnover, ret * 100.0)


# ---------------- 技术指标(纯函数, 只用传入序列 ≤t 尾部) ----------------


def sma(values: list[float], window: int) -> float | None:
    """简单移动平均, 取序列末尾 window 个。"""
    if window <= 0 or len(values) < window:
        return None
    return sum(values[-window:]) / window


def ema_series(values: list[float], window: int) -> list[float]:
    """指数移动平均(整序列), 供 MACD 复用。"""
    if not values:
        return []
    k = 2.0 / (window + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def macd_hist(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> list[float | None]:
    """MACD 柱状图序列(与 closes 等长, 预热段为 None)。histogram = (DIF - DEA) × 2。"""
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < slow:
        return out
    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    dif = [f - s for f, s in zip(ema_fast, ema_slow)]
    # DIF 在 slow-1 之前不可靠, 从该处起对 DIF 尾部再求 EMA 得 DEA
    valid_start = slow - 1
    dea_tail = ema_series(dif[valid_start:], signal)
    dea: list[float | None] = [None] * n
    for i, v in enumerate(dea_tail):
        dea[valid_start + i] = v
    for i in range(n):
        if dea[i] is None:
            continue
        out[i] = (dif[i] - dea[i]) * 2.0
    return out


def rsi(closes: list[float], window: int = 14) -> float | None:
    """RSI(默认14), 取序列末尾 window 个涨跌。"""
    if len(closes) < window + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(-window, 0):
        ch = closes[i] - closes[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    avg_gain = gains / window
    avg_loss = losses / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def period_return_pct(closes: list[float], window: int) -> float | None:
    """window 期累计收益率(%)。"""
    if len(closes) <= window:
        return None
    base = closes[-window - 1]
    if not base:
        return None
    return (closes[-1] / base - 1.0) * 100.0


def volatility_pct(closes: list[float], window: int = 20) -> float | None:
    """日收益率标准差(%)。"""
    if len(closes) < window + 1:
        return None
    rets = [(closes[i] / closes[i - 1] - 1.0) * 100.0 for i in range(-window, 0)]
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / max(len(rets) - 1, 1)
    return var ** 0.5


def volume_ratio(turnovers: list[float], window: int = 20) -> float | None:
    """量比 = 当日成交额 / 前 window 日均成交额。"""
    if len(turnovers) < window + 1:
        return None
    avg = sum(turnovers[-window - 1:-1]) / window
    if avg <= 0:
        return None
    return turnovers[-1] / avg
