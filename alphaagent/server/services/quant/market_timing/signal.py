"""金手指/银手指信号触发 v4: 仓位状态机 + 候选/确认两状态。

演进:
- v1/v2: 单日边沿触发, bull/bear 在阈值附近抖动会让 GOLD/SILVER 频繁交替。
- v3: 仓位状态机(FLAT/LONG/SHORT) + 连续确认, 单日噪声被过滤, 信号稀疏稳定。
- v2.4.2(v3 + 次日确认): 候选日 i 触发后, 要求次日 i+1 同向才发; 反向=假突破过滤。
  缺陷: 被否决的候选被静默丢弃 → 用户看到「金手指消失」(语义未来函数)。
- v4(本版): 候选触发即记录事件(标候选日 i), 用 status 字段记确认结果:
    CONFIRMED(次日同向, state 改变) / INVALIDATED(次日反向假突破, state 不变)
    / PENDING(序列末端待确认)。
  事件存在性不依赖未来, 历史完整保留, 不再有「金手指消失」。

无未来函数(关键修复):
- 候选事件属性(trade_date/direction/grade/bull_force)只用 <=i 数据
- status 是 i+1 的合法函数(确认日收盘已知)
- 事件存在性在候选日 i 就确定, 不被未来数据抹除(v2.4.2 缺失这一条)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from alphaagent.server.services.quant.market_timing.factors import MarketTimingFactors

# 进入门槛(比单日触发稍高, 要求明确方向)
GOLD_ENTER = 60.0  # bull_force ≥ 此值且顶部信号弱 → 金手指候选
SILVER_ENTER = 60.0  # bear_force ≥ 此值且多头弱 → 银手指候选
CONFIRM_DAYS = 1  # 连续确认天数(状态保持已防交替; 1天=更灵敏, 样本更多)
TOP_GUARD = 55.0  # 金手指要求 bear<55(顶部未抬头); 银手指要求 bull<55(多头已退)
MACD_TOP_GUARD = 70.0  # 金手指要求 macd_top<此值(数据驱动: 失败金手指多带 MACD 顶背离)
BREADTH_TOP_GUARD = 65.0  # 金手指要求 breadth_top<此值(广度顶背离时禁发)

# 候选确认状态
STATUS_PENDING = "PENDING"  # 序列末端, 待次日确认(盘中最新候选)
STATUS_CONFIRMED = "CONFIRMED"  # 次日同向确认, state 改变
STATUS_INVALIDATED = "INVALIDATED"  # 次日反向(假突破), state 不变, 事件保留


@dataclass(frozen=True)
class TimingSignal:
    trade_date: date
    direction: str        # GOLD(金手指/进场) / SILVER(银手指/离场防守)
    status: str           # PENDING / CONFIRMED / INVALIDATED
    grade: str            # STRONG / MEDIUM / WEAK(候选日的强度参考)
    bull_force: float
    bear_force: float
    phase: str
    confirm_date: date | None = None  # 确认日(次日 i+1); PENDING 时为 None
    reasons: list[str] = field(default_factory=list)


def _grade(direction: str, bull: float, bear: float) -> str:
    """候选日的强度档位(仅参考, 不影响状态逻辑)。"""
    v = bull if direction == "GOLD" else bear
    if v >= 72:
        return "STRONG"
    if v >= 66:
        return "MEDIUM"
    return "WEAK"


def _evaluate_status(
    target: str, i: int, n: int, closes: list[float] | None, use_confirm: bool
) -> tuple[str, int | None]:
    """用次日 i+1 判定候选 i 的确认状态。返回 (status, 确认日 index)。

    - 无确认模式(closes=None/长度不匹配): 直接 CONFIRMED(兼容旧调用/测试)
    - i 是序列末端(无 i+1): PENDING(待确认)
    - 次日同向(GOLD 涨/SILVER 跌): CONFIRMED
    - 次日反向: INVALIDATED(假突破)
    """
    if not use_confirm:
        return STATUS_CONFIRMED, None
    if i + 1 >= n:
        return STATUS_PENDING, None
    next_up = closes[i + 1] > closes[i]
    confirmed = (target == "GOLD" and next_up) or (target == "SILVER" and not next_up)
    return (STATUS_CONFIRMED if confirmed else STATUS_INVALIDATED), i + 1


def detect_events(
    factor_seq: list[MarketTimingFactors],
    closes: list[float] | None = None,
) -> list[TimingSignal]:
    """仓位状态机 + 候选/确认两状态。

    状态流转(只在 CONFIRMED 时切换):
        FLAT ──金手指确认──▶ LONG ──银手指确认──▶ SHORT ──金手指确认──▶ LONG …
    INVALIDATED/PENDING 不改 state(候选未生效, 不影响后续判定)。

    每个候选事件标在【候选日 i】(不是确认日), status 记录次日确认结果:
      - CONFIRMED:   次日 i+1 同向, state 改变
      - INVALIDATED: 次日 i+1 反向(假突破), state 不变, 事件保留不被抹除
      - PENDING:     i 是序列末端无次日数据, 待确认, state 不变

    closes 需与 factor_seq 同长度对齐(同交易日); closes=None 退回无确认模式(兼容旧调用/测试)。
    """
    events: list[TimingSignal] = []
    state = "FLAT"
    pending: str | None = None
    streak = 0
    n = len(factor_seq)
    use_confirm = closes is not None and len(closes) == n

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
            status, ci = _evaluate_status(target, i, n, closes, use_confirm)
            events.append(
                TimingSignal(
                    trade_date=f.trade_date,
                    direction=target,
                    status=status,
                    grade=_grade(target, f.bull_force, f.bear_force),
                    bull_force=f.bull_force,
                    bear_force=f.bear_force,
                    phase=f.phase,
                    confirm_date=factor_seq[ci].trade_date if ci is not None else None,
                    reasons=[
                        f"bull={f.bull_force:.1f}",
                        f"bear={f.bear_force:.1f}",
                        f"phase={f.phase}",
                        status if use_confirm else f"确认{streak}天",
                    ],
                )
            )
            if status == STATUS_CONFIRMED:
                state = "LONG" if target == "GOLD" else "SHORT"
            pending = None
            streak = 0

    return events
