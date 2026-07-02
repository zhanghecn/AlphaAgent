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


def detect_events(
    factor_seq: list[MarketTimingFactors],
    closes: list[float] | None = None,
) -> list[TimingSignal]:
    """仓位状态机 + 次日确认。

    状态流转:
        FLAT ──金手指确认──▶ LONG ──银手指确认──▶ SHORT ──金手指确认──▶ LONG …
    进入任一状态后保持, 直到达成反向确认。同方向不会重复发事件。

    次日确认(closes 可用时; 数据驱动: 金手指次日涨组 20日 100% vs 次日跌 33%):
      - 金手指要求 closes[i+1] > closes[i](次日继续涨); 银手指要求次日继续跌。
      - 次日同向 → 在确认日(次日 i+1)发出"已笃定"信号; 次日反向 → 过滤(假突破)。
      - 最新一天无次日数据 → 不发(待确认); closes=None → 退回无确认(兼容旧调用/测试)。
    closes 需与 factor_seq 同长度对齐(同交易日)。
    """
    events: list[TimingSignal] = []
    state = "FLAT"
    pending: str | None = None
    streak = 0
    use_confirm = closes is not None and len(closes) == len(factor_seq)

    for i, f in enumerate(factor_seq):
        bull = f.bull_force
        bear = f.bear_force

        gold_ok = (
            bull >= GOLD_ENTER
            and bear < TOP_GUARD
            and f.macd_top < MACD_TOP_GUARD
            and f.breadth_top < BREADTH_TOP_GUARD
        )
        silver_ok = bear >= SILVER_ENTER and bull < TOP_GUARD

        target: str | None = None
        if state != "LONG" and gold_ok:
            target = "GOLD"
        elif state != "SHORT" and silver_ok:
            target = "SILVER"

        if target == pending:
            streak += 1
        else:
            pending = target
            streak = 1 if target else 0

        if target and streak >= CONFIRM_DAYS:
            # 次日同向确认(数据驱动: 金手指 75%→100%)
            if use_confirm:
                if i + 1 >= len(factor_seq):
                    continue  # 最新一天无次日数据, 待确认不发
                next_up = closes[i + 1] > closes[i]
                if (target == "GOLD" and not next_up) or (target == "SILVER" and next_up):
                    continue  # 次日反向 = 假突破, 过滤
                cf = factor_seq[i + 1]  # 确认日的 factor, 信号记在确认日
            else:
                cf = f
            events.append(
                TimingSignal(
                    trade_date=cf.trade_date,
                    direction=target,
                    grade=_grade(target, cf.bull_force, cf.bear_force),
                    bull_force=cf.bull_force,
                    bear_force=cf.bear_force,
                    phase=cf.phase,
                    reasons=[
                        f"bull={cf.bull_force:.1f}",
                        f"bear={cf.bear_force:.1f}",
                        f"phase={cf.phase}",
                        "次日确认" if use_confirm else f"确认{streak}天",
                    ],
                )
            )
            state = "LONG" if target == "GOLD" else "SHORT"
            pending = None
            streak = 0

    return events
