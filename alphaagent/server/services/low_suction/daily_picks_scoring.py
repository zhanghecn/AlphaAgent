"""低吸日线候选综合评分（纯函数层）。

只吃 ``build_extended_daily_features`` 的因果特征与可见 K 线历史，
不查库、不看未来收益。分数用于实时推荐排序与回测分桶。

权重设计来源（全量 811 交易日分桶验证，见任务报告）：
- 趋势族：安静 K 线 + 回踩线别 + 段内距离超额梯度 + 昨日已跌 +
  收盘位置 + 连续小 K 线 + 缩量。双否决（首阴追高/趋势过伸）已由
  v4 规则硬过滤，分数只做梯度不再重复否决。
- 超跌族：低点支撑 + 换手率梯度 + 崩盘脱离低点 + 过程结构 +
  收盘反应 + 梯形缩量 + 安静 K 线 + 长期空头。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


SCORE_VERSION = "low-suction-daily-score-v2"

SCORE_BANDS: tuple[tuple[float, float, str], ...] = (
    (0.0, 39.999, "0-39"),
    (40.0, 59.999, "40-59"),
    (60.0, 79.999, "60-79"),
    (80.0, 89.999, "80-89"),
    (90.0, 100.0, "90-100"),
)

# 与研究引擎 candle_quiet 同源：小 K 线 = 振幅 <= 5%
QUIET_CANDLE_RANGE_MAX_PCT = 5.0

# 超跌族换手率硬门禁（≥8% = 高换手派发，统计剧毒）。趋势族不用此门禁（妖股高换手常见）。
OVERSOLD_TURNOVER_GATE_MAX_PCT = 8.0
# 超跌族 gate 失败时综合分硬上限（强制定入 0-39 band）。
OVERSOLD_GATE_FAILED_SCORE_CAP = 39.0


@dataclass(frozen=True)
class ScoreComponent:
    """One weighted factor condition in the composite score."""

    key: str
    label: str
    passed: bool
    points: float
    max_points: float
    detail: str
    kind: str = "bonus"  # "gate"（硬门禁，失败封顶）/ "bonus"（梯度加分）

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "passed": self.passed,
            "points": self.points,
            "max_points": self.max_points,
            "detail": self.detail,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class QuietStreak:
    """连续小 K 线计数（含 D 日，混合颜色）。"""

    total: int
    yin: int
    yang: int

    @property
    def label(self) -> str:
        if self.total <= 0:
            return "无连续小K线"
        parts: list[str] = []
        if self.yin:
            parts.append(f"{self.yin}小阴")
        if self.yang:
            parts.append(f"{self.yang}小阳")
        return f"连续{self.total}根小K线（{'+'.join(parts)}）"


def quiet_candle_streak(
    history: Sequence[Mapping[str, object]],
) -> QuietStreak:
    """Count consecutive quiet candles (range<=5%) ending at the last bar."""

    total = 0
    yin = 0
    yang = 0
    rows = list(history[-13:])
    # 先正向算出每行振幅（前收取前一行收盘），再反向数连续小 K 线
    ranges: list[float | None] = []
    for index, row in enumerate(rows):
        high_price = _number(row.get("high_price"))
        low_price = _number(row.get("low_price"))
        prev_close = (
            _number(rows[index - 1].get("close_price")) if index > 0 else None
        )
        if high_price is None or low_price is None or not prev_close:
            ranges.append(None)
            continue
        ranges.append((high_price - low_price) / prev_close * 100)
    for row, range_pct in zip(reversed(rows), reversed(ranges)):
        if range_pct is None or range_pct > QUIET_CANDLE_RANGE_MAX_PCT:
            break
        open_price = _number(row.get("open_price"))
        close_price = _number(row.get("close_price"))
        if open_price is None or close_price is None:
            break
        total += 1
        if close_price >= open_price:
            yang += 1
        else:
            yin += 1
    return QuietStreak(total=total, yin=yin, yang=yang)


def score_band(score: float) -> str:
    for lower, upper, label in SCORE_BANDS:
        if lower <= score <= upper:
            return label
    return SCORE_BANDS[-1][2] if score >= 100 else SCORE_BANDS[0][2]


def score_trend_candidate(
    features: Mapping[str, object],
    streak: QuietStreak,
) -> tuple[float, tuple[ScoreComponent, ...]]:
    """趋势回踩候选综合分（0-100）。前置：v4 规则已硬过滤双否决。

    9 个 bonus 分量（无 gate —— 妖股高换手/高振幅常见，任何 gate 都误伤研究票）。
    核心创新：振幅分量按「转势(MA60>MA30) vs 成熟」语境切换梯度 —— 转势票反弹初期
    中等振幅(5-8%)是唯一正收益口袋(+0.018%)，成熟票则需极安静(<3%)。权重源自全量分桶。
    """

    candle_range = _number(features.get("candle_range_pct"))
    ma60 = _number(features.get("ma60"))
    ma30 = _number(features.get("ma30"))
    in_transition = ma60 is not None and ma30 is not None and ma60 > ma30
    bull_days = int(features.get("bull_alignment_days") or 0)
    ma5_touch = bool(features.get("ma5_low_touch"))
    ma10_touch = bool(features.get("ma10_low_touch"))
    turnover = _number(features.get("turnover_rate_pct"))
    dist_excess = _number(features.get("trend_dist_excess_pct"))
    prior_return = _number(features.get("prior_daily_return_pct"))
    close_to_ma5 = _number(features.get("close_to_ma5_pct"))
    last_shrank = bool(features.get("last_volume_shrank"))

    # 语境调节振幅分量（max 22）：[<3%, 3-5%, 5-8%, ≥8%]
    amp_table_mature = (22.0, 14.0, 4.0, 0.0)
    amp_table_transition = (14.0, 20.0, 22.0, 6.0)
    if candle_range is None:
        amp_pts, amp_bucket = 0.0, -1
    elif candle_range < 3.0:
        amp_pts, amp_bucket = (amp_table_transition[0] if in_transition else amp_table_mature[0]), 0
    elif candle_range < 5.0:
        amp_pts, amp_bucket = (amp_table_transition[1] if in_transition else amp_table_mature[1]), 1
    elif candle_range < 8.0:
        amp_pts, amp_bucket = (amp_table_transition[2] if in_transition else amp_table_mature[2]), 2
    else:
        amp_pts, amp_bucket = (amp_table_transition[3] if in_transition else amp_table_mature[3]), 3
    ctx_label = "转势(MA60>MA30)" if in_transition else "成熟(MA60≤MA30)"

    turnover_pts = (
        12.0 if turnover is not None and turnover < 3.0
        else (8.0 if turnover is not None and turnover < 5.0
              else (4.0 if turnover is not None and turnover < 8.0 else 1.0))
    )
    age_pts = (
        14.0 if 6 <= bull_days <= 10
        else (10.0 if 3 <= bull_days <= 5
              else (7.0 if 1 <= bull_days <= 2
                    else (5.0 if 11 <= bull_days <= 20 else (4.0 if bull_days >= 21 else 0.0))))
    )
    dist_pts = (
        5.0 if dist_excess is not None and dist_excess < 0
        else (3.0 if dist_excess is not None and dist_excess < 1.0
              else (1.0 if dist_excess is not None and dist_excess < 2.0 else 0.0))
    )
    streak_pts = (
        14.0 if streak.total >= 5
        else (11.0 if streak.total >= 4
              else (8.0 if streak.total >= 3 else (5.0 if streak.total >= 2 else 0.0)))
    )

    components = (
        _component(
            "candle_quiet_context",
            "振幅安静度(语境)",
            amp_pts > 0,
            amp_pts,
            22.0,
            f"{ctx_label} 振幅 {_fmt(candle_range)}%（{amp_pts:.0f}/22）",
        ),
        _component(
            "trend_age",
            "趋势年龄",
            age_pts > 0,
            age_pts,
            14.0,
            f"多头排列 {bull_days} 日（6-10 满14）",
        ),
        _component(
            "touch_line",
            "回踩均线",
            ma5_touch or ma10_touch,
            14.0 if ma5_touch else (9.0 if ma10_touch else 0.0),
            14.0,
            "低点回踩 MA5" if ma5_touch else ("低点回踩 MA10" if ma10_touch else "未回踩 MA5/MA10"),
        ),
        _component(
            "turnover_gradient",
            "换手率梯度",
            turnover_pts > 0,
            turnover_pts,
            12.0,
            f"换手 {_fmt(turnover)}%（<3% 满12）",
        ),
        _component(
            "quiet_streak",
            "连续小K线",
            streak_pts > 0,
            streak_pts,
            14.0,
            streak.label,
        ),
        _component(
            "prior_day_down",
            "昨日已跌",
            prior_return is not None and prior_return <= 0,
            (
                8.0 if prior_return is not None and prior_return <= 0
                else (4.0 if prior_return is not None and prior_return <= 1.0 else 0.0)
            ),
            8.0,
            f"昨日涨跌 {_fmt(prior_return, signed=True)}%",
        ),
        _component(
            "close_position",
            "收盘位置",
            close_to_ma5 is not None and close_to_ma5 <= 0,
            (
                8.0 if close_to_ma5 is not None and close_to_ma5 <= 0
                else (4.0 if close_to_ma5 is not None and close_to_ma5 <= 1.0 else 0.0)
            ),
            8.0,
            f"收盘距 MA5 {_fmt(close_to_ma5, signed=True)}%",
        ),
        _component(
            "dist_excess",
            "趋势老嫩",
            dist_pts > 0,
            dist_pts,
            5.0,
            (
                f"M5-M10 距离较本段回踩中位 {_fmt(dist_excess, signed=True)}pct"
                if dist_excess is not None
                else "本段无回踩参照"
            ),
        ),
        _component(
            "volume_shrink",
            "缩量",
            last_shrank,
            3.0 if last_shrank else 0.0,
            3.0,
            "当日成交量低于前日" if last_shrank else "当日未缩量",
        ),
    )
    return _total(components), components


def score_oversold_candidate(
    features: Mapping[str, object],
    streak: QuietStreak,
    vol_ratio: float | None = None,
) -> tuple[float, tuple[ScoreComponent, ...]]:
    """超跌反弹候选综合分（0-100）。前置：oversold_process_eligible。

    换手率≥8% 为硬门禁（gate，失败总分封顶 39）；其余 10 个 bonus 分量梯度加分。
    权重源自全量分桶：高换手=派发；量能趋势单调（骤缩+0.065%→骤放-0.301%）。
    vol_ratio = 近5日均量/近10日均量，由 scanner 从 history 算好传入。
    """

    turnover = _number(features.get("turnover_rate_pct"))
    candle_range = _number(features.get("candle_range_pct"))
    close_off_low = _number(features.get("close_off_low_pct"))
    low_support = bool(features.get("oversold_low_support"))
    tight = bool(features.get("capitulation_rebound_tight"))
    broad = bool(features.get("capitulation_rebound_broad"))
    process = any(
        bool(features.get(field))
        for field in (
            "staged_m10_first",
            "m10_dual_cross_before_m20_m30",
            "m5_m10_joint_attack_ready",
            "ma10_crossed_ma30_within_15d",
        )
    )
    reaction = bool(features.get("support_close_reaction"))
    shrink = str(features.get("volume_shape") or "") == "staircase_shrink"
    long_bear_days = int(features.get("prior_bear_alignment_days") or 0)

    gate_passed = turnover is not None and turnover < OVERSOLD_TURNOVER_GATE_MAX_PCT
    turnover_pts = (
        14.0 if turnover is not None and turnover < 3.0
        else (10.0 if turnover is not None and turnover < 5.0
              else (4.0 if turnover is not None and turnover < 8.0 else 0.0))
    )
    amp_pts = (
        12.0 if candle_range is not None and candle_range < 3.0
        else (8.0 if candle_range is not None and candle_range < 5.0
              else (2.0 if candle_range is not None and candle_range < 8.0 else 0.0))
    )
    long_bear_pts = (
        10.0 if long_bear_days >= 20
        else (8.0 if long_bear_days >= 10
              else (4.0 if long_bear_days >= 5 else 0.0))
    )
    vol_trend_pts = (
        10.0 if vol_ratio is not None and vol_ratio < 0.8
        else (8.0 if vol_ratio is not None and vol_ratio < 1.0
              else (4.0 if vol_ratio is not None and vol_ratio < 1.1
                    else (2.0 if vol_ratio is not None and vol_ratio < 1.3 else 0.0)))
    )

    components = (
        _component(
            "turnover_gate",
            "换手率门禁",
            gate_passed,
            0.0,
            0.0,
            (
                f"换手 {_fmt(turnover)}%（≥{OVERSOLD_TURNOVER_GATE_MAX_PCT:g}% 门禁失败，封顶{OVERSOLD_GATE_FAILED_SCORE_CAP:g}）"
                if not gate_passed
                else f"换手 {_fmt(turnover)}%（<{OVERSOLD_TURNOVER_GATE_MAX_PCT:g}% 通过）"
            ),
            kind="gate",
        ),
        _component(
            "turnover_gradient",
            "换手率梯度",
            turnover_pts > 0,
            turnover_pts,
            14.0,
            f"换手 {_fmt(turnover)}%（<3% 满14）",
        ),
        _component(
            "candle_quiet",
            "振幅安静度",
            amp_pts > 0,
            amp_pts,
            12.0,
            f"振幅 {_fmt(candle_range)}%（<3% 满12）",
        ),
        _component(
            "low_support",
            "低点获均线支撑",
            low_support,
            16.0 if low_support else 0.0,
            16.0,
            "D 日低点在 MA10/20/30 获实际支撑" if low_support else "低点未获均线支撑",
        ),
        _component(
            "long_bear_duration",
            "空头持续时长",
            long_bear_pts > 0,
            long_bear_pts,
            10.0,
            f"前期空头排列 {long_bear_days} 日（≥20 满10）",
        ),
        _component(
            "process_structure",
            "上穿过程结构",
            process,
            12.0 if process else 0.0,
            12.0,
            "MA10 分阶段上穿/联合上攻结构成立" if process else "分阶段上穿结构不成立",
        ),
        _component(
            "capitulation",
            "崩盘脱离低点",
            tight or broad,
            10.0 if tight else (6.0 if broad else 0.0),
            10.0,
            (
                f"收盘脱离低点 {_fmt(close_off_low)}%（0.3~1.5% 为紧凑反弹）"
                if close_off_low is not None
                else "无崩盘反弹形态"
            ),
        ),
        _component(
            "close_reaction",
            "收盘支撑反应",
            reaction,
            8.0 if reaction else 0.0,
            8.0,
            "收盘守住支撑有反应" if reaction else "收盘无支撑反应",
        ),
        _component(
            "volume_shape",
            "量能形态",
            shrink,
            5.0 if shrink else 0.0,
            5.0,
            "梯形缩量" if shrink else "非梯形缩量",
        ),
        _component(
            "quiet_streak",
            "连续小K线",
            streak.total >= 2,
            3.0 if streak.total >= 2 else 0.0,
            3.0,
            streak.label,
        ),
        _component(
            "vol_trend",
            "量能趋势",
            vol_trend_pts > 0,
            vol_trend_pts,
            10.0,
            (
                f"5/10日均量比 {_fmt(vol_ratio)}（<0.8 骤缩满10）"
                if vol_ratio is not None
                else "量能趋势数据不足"
            ),
        ),
    )
    return _total(components, gate_failed_cap=OVERSOLD_GATE_FAILED_SCORE_CAP), components


def _component(
    key: str,
    label: str,
    passed: bool,
    points: float,
    max_points: float,
    detail: str,
    *,
    kind: str = "bonus",
) -> ScoreComponent:
    return ScoreComponent(
        key=key,
        label=label,
        passed=passed,
        points=round(points, 2),
        max_points=max_points,
        detail=detail,
        kind=kind,
    )


def _total(
    components: Sequence[ScoreComponent],
    *,
    gate_failed_cap: float | None = None,
) -> float:
    raw = sum(item.points for item in components)
    if gate_failed_cap is not None and any(
        item.kind == "gate" and not item.passed for item in components
    ):
        raw = min(raw, gate_failed_cap)
    return round(min(100.0, raw), 2)


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _fmt(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "--"
    return f"{value:+.2f}" if signed else f"{value:.2f}"
