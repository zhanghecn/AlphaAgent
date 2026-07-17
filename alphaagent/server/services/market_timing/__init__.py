"""大盘择时金手指/银手指信号模块。

复用 ``market_context`` 的市场得分，补充 MACD/RSI/量能等技术因子，
组成多头合力分 ``bull_force``，按阶段+分级触发金手指(看多)/银手指(看空)。

子模块:
- ``series``   7 指数加权综合序列 + 技术指标(无未来函数)
- ``factors``  5 族因子打分 → bull_force
- ``signal``   阶段适配 + 分级阈值 + 边沿触发
- ``backtest`` 多周期胜率 + bootstrap CI + 基准对比
"""

from alphaagent.server.services.market_timing.factors import (
    MarketTimingFactors,
    compute_factors,
)
from alphaagent.server.services.market_timing.series import (
    CompositeBar,
    load_composite_series,
)
from alphaagent.server.services.market_timing.signal import (
    TimingSignal,
    detect_events,
)
from alphaagent.server.services.market_timing.backtest import evaluate

__all__ = [
    "MarketTimingFactors",
    "compute_factors",
    "CompositeBar",
    "load_composite_series",
    "TimingSignal",
    "detect_events",
    "evaluate",
]
