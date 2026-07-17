"""金手指/银手指信号触发 v9: 精度优先银手指 + 金手指失效保护。

演进:
- v1/v2: 单日边沿触发, bull/bear 在阈值附近抖动会让 GOLD/SILVER 频繁交替。
- v3: 仓位状态机(FLAT/LONG/SHORT) + 连续确认, 单日噪声被过滤, 信号稀疏稳定。
- v2.4.2(v3 + 次日确认): 候选日 i 触发后, 要求次日 i+1 同向才发; 反向=假突破过滤。
  缺陷: 被否决的候选被静默丢弃 → 用户看到「金手指消失」(语义未来函数)。
- v4: 候选触发即记录事件(标候选日 i), 用 status 字段记确认结果:
    CONFIRMED(次日同向, state 改变) / INVALIDATED(次日反向假突破, state 不变)
    / PENDING(序列末端待确认)。
  事件存在性不依赖未来, 历史完整保留, 不再有「金手指消失」。
- v5: 事件与仓位状态解耦。首次进入金区/银区时记录候选, 连续停留不重复;
  离开后再次进入可重新记录同方向候选。修复长期 SHORT/LONG 吞掉近期同向事件。
- v6: 增加独立 ``REVERSAL_GOLD`` 弱势衰竭 setup。候选只读取 <=i 的
  收盘前缀, 次日上涨且宽基参与度不窄时确认。镜像反转银未通过长历史验证,
  不因形式对称而上线。
- v7: 增加 ``STRUCTURAL_BREAKDOWN_SILVER`` 和独立危险状态。强破位
  当日优先于反转金, 危险状态持续到价格、参与度和空头强度共同修复。
- v8: 停止生成样本外失效的普通 ``BREAKDOWN_SILVER``。银手指只保留
  顶部风险和多类空头结构一致恶化两类 setup, 金手指行为不变。
- v9(本版): 趋势金候选若被次日宽基急跌明确否决, 在失败日生成
  ``GOLD_FAILURE_SILVER``，避免已失效金状态继续无限延续。

无未来函数(关键修复):
- 候选事件属性(trade_date/direction/grade/bull_force)只用 <=i 数据
- status 是 i+1 的合法函数(确认日收盘已知)
- 事件存在性在候选日 i 就确定, 不被未来数据抹除(v2.4.2 缺失这一条)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from alphaagent.server.services.market_timing.factors import MarketTimingFactors
from alphaagent.server.services.market_timing import series as ser

# 进入门槛(比单日触发稍高, 要求明确方向)
GOLD_ENTER = 60.0  # bull_force ≥ 此值且顶部信号弱 → 金手指候选
SILVER_ENTER = 60.0  # bear_force ≥ 此值且多头弱 → 银手指候选
TOP_GUARD = 55.0  # 金手指要求 bear<55(顶部未抬头); 银手指要求 bull<55(多头已退)
MACD_TOP_GUARD = 70.0  # 金手指要求 macd_top<此值(数据驱动: 失败金手指多带 MACD 顶背离)
BREADTH_TOP_GUARD = 65.0  # 金手指要求 breadth_top<此值(广度顶背离时禁发)

# setup 类型只解释信号来源, 不引入仓位语义
SETUP_TREND_GOLD = "TREND_GOLD"
SETUP_REVERSAL_GOLD = "REVERSAL_GOLD"
SETUP_TOP_SILVER = "TOP_SILVER"
SETUP_BREAKDOWN_SILVER = "BREAKDOWN_SILVER"
SETUP_STRUCTURAL_BREAKDOWN_SILVER = "STRUCTURAL_BREAKDOWN_SILVER"
SETUP_GOLD_FAILURE_SILVER = "GOLD_FAILURE_SILVER"

# v9 趋势金失败保护：必须是宽基急跌且多空合力已经反转
GOLD_FAILURE_RETURN_MAX = -2.0
GOLD_FAILURE_UP_RATIO_MAX = 0.25

# v6 反转金固定门槛(六指数 2015-2026 + 七指数共同期验证)
REVERSAL_RSI2_MAX = 20.0
REVERSAL_RETURN_10D_MAX = -2.0
REVERSAL_DRAWDOWN_20D_MAX = -3.0
REVERSAL_RETURN_1D_MIN = -1.0
REVERSAL_RETURN_1D_MAX = 0.5
REVERSAL_CONFIRM_UP_RATIO_MIN = 0.5
REVERSAL_COOLDOWN = 10

# v7 结构性破位和风险修复门槛(标准化分数 + 宽基参与度)
STRUCTURAL_BEAR_MIN = 65.0
STRUCTURAL_BEAR_GAP_MIN = 15.0
STRUCTURAL_BREAKDOWN_MIN = 80.0
STRUCTURAL_MACD_TOP_MIN = 70.0
STRUCTURAL_UP_RATIO_MAX = 0.5
REPAIR_BEAR_MAX = 65.0
REPAIR_UP_RATIO_MIN = 0.5

NORMAL = "NORMAL"
DANGER = "DANGER"

# 候选确认状态
STATUS_PENDING = "PENDING"  # 序列末端, 待次日确认(盘中最新候选)
STATUS_CONFIRMED = "CONFIRMED"  # 次日同向确认
STATUS_INVALIDATED = "INVALIDATED"  # 次日反向(假突破), 事件保留


@dataclass(frozen=True)
class TimingSignal:
    trade_date: date
    direction: str        # GOLD(金手指) / SILVER(银手指)
    status: str           # PENDING / CONFIRMED / INVALIDATED
    grade: str            # STRONG / MEDIUM / WEAK(候选日的强度参考)
    bull_force: float
    bear_force: float
    phase: str
    setup_type: str
    confirm_date: date | None = None  # 确认日(次日 i+1); PENDING 时为 None
    reasons: list[str] = field(default_factory=list)


def build_active_directions(
    trade_dates: list[date],
    events: list[TimingSignal],
) -> list[str]:
    """从确认日起延续最近金银方向，不读取确认日之后的数据。"""
    confirmed_by_date = {
        event.confirm_date: event.direction
        for event in events
        if event.status == STATUS_CONFIRMED and event.confirm_date is not None
    }
    active = "NEUTRAL"
    directions: list[str] = []
    for trade_date in trade_dates:
        confirmed = confirmed_by_date.get(trade_date)
        if confirmed in {"GOLD", "SILVER"}:
            active = confirmed
        directions.append(active)
    return directions


def _grade(direction: str, bull: float, bear: float) -> str:
    """候选日的强度档位(仅参考, 不影响状态逻辑)。"""
    v = bull if direction == "GOLD" else bear
    if v >= 72:
        return "STRONG"
    if v >= 66:
        return "MEDIUM"
    return "WEAK"


def candidate_direction(factor: MarketTimingFactors) -> str | None:
    """返回当日进入候选区的方向；阈值只在这里定义。"""
    gold_ok = (
        factor.bull_force >= GOLD_ENTER
        and factor.bear_force < TOP_GUARD
        and factor.macd_top < MACD_TOP_GUARD
        and factor.breadth_top < BREADTH_TOP_GUARD
    )
    if gold_ok:
        return "GOLD"
    if factor.bear_force >= SILVER_ENTER and factor.bull_force < TOP_GUARD:
        return "SILVER"
    return None


def _reversal_gold_metrics(
    closes: list[float],
    end_index: int | None = None,
) -> dict[str, float] | None:
    """返回指定候选日的弱势衰竭指标，不读取其后的收盘价。"""
    end = len(closes) - 1 if end_index is None else end_index
    if end < 20 or end >= len(closes):
        return None

    current_close = closes[end]
    previous_close = closes[end - 1]
    base_10d = closes[end - 10]
    if previous_close <= 0 or base_10d <= 0:
        return None

    rsi2 = ser.rsi(closes[end - 2 : end + 1], 2)
    if rsi2 is None:
        return None

    return_1d = (current_close / previous_close - 1.0) * 100.0
    return_10d = (current_close / base_10d - 1.0) * 100.0
    high_20d = max(closes[end - 19 : end + 1])
    if high_20d <= 0:
        return None
    drawdown_20d = (current_close / high_20d - 1.0) * 100.0
    return {
        "rsi2": rsi2,
        "return_1d": return_1d,
        "return_10d": return_10d,
        "drawdown_20d": drawdown_20d,
    }


def _matches_reversal_gold(metrics: dict[str, float] | None) -> bool:
    if metrics is None:
        return False
    return (
        metrics["rsi2"] <= REVERSAL_RSI2_MAX
        and metrics["return_10d"] <= REVERSAL_RETURN_10D_MAX
        and metrics["drawdown_20d"] <= REVERSAL_DRAWDOWN_20D_MAX
        and REVERSAL_RETURN_1D_MIN
        <= metrics["return_1d"]
        <= REVERSAL_RETURN_1D_MAX
    )


def is_reversal_gold(
    closes: list[float],
    end_index: int | None = None,
) -> bool:
    """判断指定日是否进入反转金区；默认判断序列末日。"""
    return _matches_reversal_gold(_reversal_gold_metrics(closes, end_index))


def _sma_at(closes: list[float], index: int, window: int) -> float | None:
    """返回指定索引的因果均线，只读取 ``<=index`` 的固定窗口。"""
    if index < window - 1 or index >= len(closes):
        return None
    return sum(closes[index - window + 1 : index + 1]) / window


def is_structural_breakdown(
    factor: MarketTimingFactors,
    closes: list[float],
    index: int,
    up_ratio: float | None,
) -> bool:
    """判断当日是否为结构性破位；参与度缺失时严格不触发。"""
    ma20 = _sma_at(closes, index, 20)
    if ma20 is None or up_ratio is None:
        return False
    breakdown = float(factor.evidence.get("trend_breakdown") or 0.0)
    return (
        factor.bear_force >= STRUCTURAL_BEAR_MIN
        and factor.bear_force - factor.bull_force >= STRUCTURAL_BEAR_GAP_MIN
        and breakdown >= STRUCTURAL_BREAKDOWN_MIN
        and closes[index] < ma20
        and factor.macd_top >= STRUCTURAL_MACD_TOP_MIN
        and up_ratio <= STRUCTURAL_UP_RATIO_MAX
    )


def _is_danger_repaired(
    factor: MarketTimingFactors,
    closes: list[float],
    index: int,
    up_ratio: float | None,
) -> bool:
    ma5 = _sma_at(closes, index, 5)
    return bool(
        ma5 is not None
        and up_ratio is not None
        and closes[index] > ma5
        and up_ratio >= REPAIR_UP_RATIO_MIN
        and factor.bear_force < REPAIR_BEAR_MAX
    )


def build_danger_states(
    factor_seq: list[MarketTimingFactors],
    closes: list[float] | None,
    up_ratios: list[float | None] | None,
) -> list[str]:
    """构建逐日因果危险状态；输入不对齐时关闭该通道。"""
    n = len(factor_seq)
    if (
        closes is None
        or up_ratios is None
        or len(closes) != n
        or len(up_ratios) != n
    ):
        return [NORMAL] * n

    active = False
    states: list[str] = []
    for index, factor in enumerate(factor_seq):
        up_ratio = up_ratios[index]
        if active and _is_danger_repaired(
            factor,
            closes,
            index,
            up_ratio,
        ):
            active = False
        if not active and is_structural_breakdown(
            factor,
            closes,
            index,
            up_ratio,
        ):
            active = True
        states.append(DANGER if active else NORMAL)
    return states


def candidate_setup(
    factor: MarketTimingFactors,
    *,
    reversal_gold: bool = False,
    structural_breakdown: bool = False,
) -> tuple[str | None, str | None]:
    """根据当日因子和已计算的反转状态返回方向及 setup。"""
    if structural_breakdown:
        return "SILVER", SETUP_STRUCTURAL_BREAKDOWN_SILVER
    if reversal_gold:
        return "GOLD", SETUP_REVERSAL_GOLD

    direction = candidate_direction(factor)
    if direction == "GOLD":
        return direction, SETUP_TREND_GOLD
    if direction == "SILVER":
        breakdown = float(factor.evidence.get("trend_breakdown") or 0.0)
        if breakdown >= SILVER_ENTER:
            return None, None
        return direction, SETUP_TOP_SILVER
    return None, None


def is_gold_failure_silver(
    setup_type: str,
    factor: MarketTimingFactors,
    previous_close: float,
    current_close: float,
    up_ratio: float | None,
) -> bool:
    """判断趋势金是否在下一交易日发生可确认的宽基失败。"""
    if (
        setup_type != SETUP_TREND_GOLD
        or previous_close <= 0
        or current_close <= 0
        or up_ratio is None
    ):
        return False
    return_pct = (current_close / previous_close - 1.0) * 100.0
    return (
        return_pct <= GOLD_FAILURE_RETURN_MAX
        and up_ratio <= GOLD_FAILURE_UP_RATIO_MAX
        and factor.bull_force < GOLD_ENTER
        and factor.bear_force >= factor.bull_force
    )


def _evaluate_status(
    target: str,
    setup_type: str,
    index: int,
    closes: list[float] | None,
    up_ratios: list[float | None] | None = None,
) -> tuple[str, int | None]:
    """用次日判定候选状态，返回状态和确认日索引。

    - 无确认模式(closes=None/长度不匹配): 直接 CONFIRMED(兼容旧调用/测试)
    - index 是序列末端: PENDING(待确认)
    - 次日同向(GOLD 涨/SILVER 跌): CONFIRMED
    - 次日反向: INVALIDATED(假突破)
    """
    if closes is None:
        return STATUS_CONFIRMED, None
    confirm_index = index + 1
    if confirm_index >= len(closes):
        return STATUS_PENDING, None
    next_up = closes[confirm_index] > closes[index]
    confirmed = (target == "GOLD" and next_up) or (target == "SILVER" and not next_up)
    if setup_type == SETUP_REVERSAL_GOLD and up_ratios is not None:
        next_up_ratio = up_ratios[confirm_index]
        confirmed = confirmed and (
            next_up_ratio is None
            or next_up_ratio >= REVERSAL_CONFIRM_UP_RATIO_MIN
        )
    return (
        STATUS_CONFIRMED if confirmed else STATUS_INVALIDATED,
        confirm_index,
    )


def _derive_gold_failure_events(
    events: list[TimingSignal],
    factor_seq: list[MarketTimingFactors],
    closes: list[float],
    up_ratios: list[float | None],
    confirmed_through: date | None,
) -> list[TimingSignal]:
    """从趋势金次日失败派生银事件，并让失败银覆盖同日普通候选。"""
    index_by_date = {
        factor.trade_date: index
        for index, factor in enumerate(factor_seq)
    }
    failure_events: list[TimingSignal] = []
    failure_dates: set[date] = set()

    for event in events:
        if event.trade_date in failure_dates:
            continue
        candidate_index = index_by_date.get(event.trade_date)
        if candidate_index is None:
            continue
        failure_index = candidate_index + 1
        if failure_index >= len(factor_seq):
            continue
        factor = factor_seq[failure_index]
        up_ratio = up_ratios[failure_index]
        if not is_gold_failure_silver(
            event.setup_type,
            factor,
            closes[candidate_index],
            closes[failure_index],
            up_ratio,
        ):
            continue

        failure_date = factor.trade_date
        finalized = (
            confirmed_through is None
            or failure_date <= confirmed_through
        )
        status = STATUS_CONFIRMED if finalized else STATUS_PENDING
        return_pct = (
            closes[failure_index] / closes[candidate_index] - 1.0
        ) * 100.0
        failure_events.append(
            TimingSignal(
                trade_date=failure_date,
                direction="SILVER",
                status=status,
                grade=_grade("SILVER", factor.bull_force, factor.bear_force),
                bull_force=factor.bull_force,
                bear_force=factor.bear_force,
                phase=factor.phase,
                setup_type=SETUP_GOLD_FAILURE_SILVER,
                confirm_date=failure_date if finalized else None,
                reasons=[
                    f"failed_gold={event.trade_date}",
                    f"return_1d={return_pct:.1f}%",
                    f"up_ratio={up_ratio:.2f}",
                    f"bull={factor.bull_force:.1f}",
                    f"bear={factor.bear_force:.1f}",
                    status,
                ],
            )
        )
        failure_dates.add(failure_date)

    if not failure_events:
        return events
    retained = [
        event for event in events
        if event.trade_date not in failure_dates
    ]
    return sorted(
        [*retained, *failure_events],
        key=lambda event: event.trade_date,
    )


def detect_events(
    factor_seq: list[MarketTimingFactors],
    closes: list[float] | None = None,
    up_ratios: list[float | None] | None = None,
    confirmed_through: date | None = None,
) -> list[TimingSignal]:
    """检测金银区域进入事件，并记录次日确认状态。

    区域进入规则：
      - 非金区 -> 金区：记录 GOLD 候选
      - 非银区 -> 银区：记录 SILVER 候选
      - 连续停留同一区域：不重复记录
      - 离开后再次进入：允许再次记录同方向候选

    每个候选事件标在【候选日 i】(不是确认日), status 记录次日确认结果:
      - CONFIRMED:   次日 i+1 同向
      - INVALIDATED: 次日 i+1 反向(假突破), 事件保留不被抹除
      - PENDING:     i 是序列末端无次日数据, 待确认

    closes 需与 factor_seq 同长度对齐(同交易日); closes=None 退回无确认模式(兼容旧调用/测试)。
    confirmed_through 用于盘中载荷，只允许截止日及以前的确认正式生效。
    """
    events: list[TimingSignal] = []
    previous_zone: tuple[str, str] | None = None
    previous_reversal_zone = False
    last_reversal_index = -REVERSAL_COOLDOWN
    n = len(factor_seq)
    aligned_closes = closes if closes is not None and len(closes) == n else None
    aligned_up_ratios = (
        up_ratios
        if aligned_closes is not None
        and up_ratios is not None
        and len(up_ratios) == n
        else None
    )
    danger_states = build_danger_states(
        factor_seq,
        aligned_closes,
        aligned_up_ratios,
    )

    for i, f in enumerate(factor_seq):
        structural_breakdown = bool(
            aligned_closes is not None
            and aligned_up_ratios is not None
            and is_structural_breakdown(
                f,
                aligned_closes,
                i,
                aligned_up_ratios[i],
            )
        )
        entered_danger = (
            danger_states[i] == DANGER
            and (i == 0 or danger_states[i - 1] == NORMAL)
        )
        reversal_metrics = (
            _reversal_gold_metrics(aligned_closes, i)
            if aligned_closes is not None
            else None
        )
        reversal_zone = _matches_reversal_gold(reversal_metrics)
        entered_reversal_zone = (
            reversal_zone
            and not structural_breakdown
            and not previous_reversal_zone
        )
        previous_reversal_zone = reversal_zone if not structural_breakdown else False
        use_reversal_setup = (
            entered_reversal_zone
            and i - last_reversal_index >= REVERSAL_COOLDOWN
        )
        direction, setup_type = candidate_setup(
            f,
            reversal_gold=use_reversal_setup,
            structural_breakdown=structural_breakdown,
        )
        if direction is None or setup_type is None:
            previous_zone = None
            continue
        zone = (direction, setup_type)
        if (
            danger_states[i] == DANGER
            and direction == "SILVER"
            and setup_type != SETUP_STRUCTURAL_BREAKDOWN_SILVER
        ):
            previous_zone = zone
            continue
        if (
            setup_type == SETUP_STRUCTURAL_BREAKDOWN_SILVER
            and not entered_danger
        ):
            previous_zone = zone
            continue
        if zone == previous_zone:
            continue
        previous_zone = zone

        if setup_type == SETUP_REVERSAL_GOLD:
            last_reversal_index = i

        if setup_type == SETUP_STRUCTURAL_BREAKDOWN_SILVER:
            confirm_index = i + 1
            if confirm_index >= n:
                status = STATUS_PENDING
                confirm_index = None
            else:
                status = (
                    STATUS_CONFIRMED
                    if danger_states[confirm_index] == DANGER
                    else STATUS_INVALIDATED
                )
        else:
            status, confirm_index = _evaluate_status(
                direction,
                setup_type,
                i,
                aligned_closes,
                aligned_up_ratios,
            )
        if (
            confirm_index is not None
            and confirmed_through is not None
            and factor_seq[confirm_index].trade_date > confirmed_through
        ):
            status = STATUS_PENDING
            confirm_index = None
        status_reason = status if aligned_closes is not None else "区域进入"
        reasons = [
            f"bull={f.bull_force:.1f}",
            f"bear={f.bear_force:.1f}",
            f"phase={f.phase}",
            status_reason,
        ]
        if setup_type == SETUP_REVERSAL_GOLD and reversal_metrics is not None:
            reasons = [
                f"rsi2={reversal_metrics['rsi2']:.1f}",
                f"return_10d={reversal_metrics['return_10d']:.1f}%",
                f"drawdown_20d={reversal_metrics['drawdown_20d']:.1f}%",
                f"return_1d={reversal_metrics['return_1d']:.1f}%",
                status_reason,
            ]
        elif setup_type == SETUP_STRUCTURAL_BREAKDOWN_SILVER:
            reasons = [
                f"bear={f.bear_force:.1f}",
                f"bear_gap={f.bear_force - f.bull_force:.1f}",
                f"trend_breakdown={float(f.evidence.get('trend_breakdown') or 0.0):.1f}",
                f"macd_top={f.macd_top:.1f}",
                f"up_ratio={aligned_up_ratios[i]:.2f}",
                status_reason,
            ]
        events.append(
            TimingSignal(
                trade_date=f.trade_date,
                direction=direction,
                status=status,
                grade=_grade(direction, f.bull_force, f.bear_force),
                bull_force=f.bull_force,
                bear_force=f.bear_force,
                phase=f.phase,
                setup_type=setup_type,
                confirm_date=(
                    factor_seq[confirm_index].trade_date
                    if confirm_index is not None
                    else None
                ),
                reasons=reasons,
            )
        )

    if aligned_closes is not None and aligned_up_ratios is not None:
        return _derive_gold_failure_events(
            events,
            factor_seq,
            aligned_closes,
            aligned_up_ratios,
            confirmed_through,
        )
    return events
