"""金手指/银手指信号触发 v3: 仓位状态机 + 连续确认 + 滞回。

v1/v2 用单日边沿触发, bull/bear 在阈值附近抖动会让 GOLD/SILVER 频繁交替,
违背「银手指=空仓等待, 金手指=重新进场」的仓位语义。v3 改为状态机:

- 维护仓位状态 ``LONG``(多头持仓) / ``SHORT``(防守空仓) / ``FLAT``(初始)。
- 进入多头后保持, 直到「银手指条件连续 CONFIRM_DAYS 天满足」才切防守。
- 进入防守后保持, 直到「金手指条件连续 CONFIRM_DAYS 天满足」才切多头。
- 切换需连续确认 → 单日噪声被过滤, 信号稀疏稳定, 不会频繁交替。
- 事件 = 状态切换点(金手指=进场日, 银手指=离场日), 带当时强度档位。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from alphaagent.server.services.quant.market_timing.factors import MarketTimingFactors

# 进入门槛(比 v2 单日触发稍高, 要求明确方向)
GOLD_ENTER = 60.0  # bull_force ≥ 此值且顶部信号弱 → 金手指候选
SILVER_ENTER = 60.0  # bear_force ≥ 此值且多头弱 → 银手指候选
CONFIRM_DAYS = 1  # 连续确认天数(状态保持已防交替; 1天=更灵敏, 样本更多)
TOP_GUARD = 55.0  # 金手指要求 bear<55(顶部未抬头); 银手指要求 bull<55(多头已退)
MACD_TOP_GUARD = 70.0  # 金手指要求 macd_top<此值(数据驱动: 失败金手指 3/4 有 MACD 顶背离 macd_top=80)
BREADTH_TOP_GUARD = 65.0  # 金手指要求 breadth_top<此值(广度顶背离时禁发: 失败样本 breadth_top=68)


@dataclass(frozen=True)
class TimingSignal:
    trade_date: date
    direction: str        # GOLD(金手指/进场) / SILVER(银手指/离场防守)
    grade: str            # STRONG / MEDIUM / WEAK(切换时的强度参考)
    bull_force: float
    bear_force: float
    phase: str
    reasons: list[str] = field(default_factory=list)


def _grade(direction: str, bull: float, bear: float) -> str:
    """切换时的强度档位(仅参考, 不影响状态逻辑)。"""
    v = bull if direction == "GOLD" else bear
    if v >= 72:
        return "STRONG"
    if v >= 66:
        return "MEDIUM"
    return "WEAK"


def detect_events(factor_seq: list[MarketTimingFactors]) -> list[TimingSignal]:
    """仓位状态机: 状态切换点 = 信号事件。

    状态流转:
        FLAT ──金手指确认──▶ LONG ──银手指确认──▶ SHORT ──金手指确认──▶ LONG …
    进入任一状态后保持, 直到达成反向确认。同方向不会重复发事件。
    """
    events: list[TimingSignal] = []
    state = "FLAT"          # FLAT / LONG / SHORT
    pending: str | None = None  # 待确认的方向
    streak = 0

    for f in factor_seq:
        bull = f.bull_force
        bear = f.bear_force

        # 金手指过滤(数据驱动, 失败样本分析: 失败金手指 3/4 命中 MACD 顶背离):
        #   - bear < TOP_GUARD: 顶部合力未抬头
        #   - macd_top < MACD_TOP_GUARD: 排除 MACD 顶背离时的假金手指
        gold_ok = (
            bull >= GOLD_ENTER
            and bear < TOP_GUARD
            and f.macd_top < MACD_TOP_GUARD
            and f.breadth_top < BREADTH_TOP_GUARD
        )
        silver_ok = bear >= SILVER_ENTER and bull < TOP_GUARD

        # 当前状态下, 是否能朝某方向切换(同方向不重复)
        target: str | None = None
        if state != "LONG" and gold_ok:
            target = "GOLD"
        elif state != "SHORT" and silver_ok:
            target = "SILVER"

        # 连续确认计数
        if target == pending:
            streak += 1
        else:
            pending = target
            streak = 1 if target else 0

        # 确认期满 → 切换状态, 记事件
        if target and streak >= CONFIRM_DAYS:
            events.append(
                TimingSignal(
                    trade_date=f.trade_date,
                    direction=target,
                    grade=_grade(target, bull, bear),
                    bull_force=bull,
                    bear_force=bear,
                    phase=f.phase,
                    reasons=[
                        f"bull={bull:.1f}",
                        f"bear={bear:.1f}",
                        f"phase={f.phase}",
                        f"确认{streak}天",
                    ],
                )
            )
            state = "LONG" if target == "GOLD" else "SHORT"
            pending = None
            streak = 0

    return events
