"""一接二 +9% 入场价格口径；本模块不依赖研究与数据库代码。"""
from __future__ import annotations

import math


def limit_10pct(prev_close: float) -> float:
    """主板涨停价：不复权昨收乘 1.10 后四舍五入到分。"""
    return round(prev_close * 1.10 + 1e-9, 2)


def trigger_9pct(prev_close: float) -> float:
    """严格高于昨收 +9% 的第一个可报价（最小价位 0.01 元）。"""
    return round(math.floor(prev_close * 109 + 1e-7) / 100 + 0.01, 2)


def open9_entry(open_price: float, high_price: float, prev_close: float) -> float | None:
    """开盘非涨停时，盘中首次严格突破 +9% 的假定成交价。"""
    if not all(math.isfinite(price) for price in (open_price, high_price, prev_close)):
        return None
    if prev_close <= 0:
        return None
    if open_price >= limit_10pct(prev_close) - 1e-9:
        return None
    trigger = trigger_9pct(prev_close)
    if high_price + 1e-9 < trigger:
        return None
    return round(max(open_price, trigger), 2)
