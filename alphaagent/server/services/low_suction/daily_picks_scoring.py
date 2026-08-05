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


SCORE_VERSION = "low-suction-daily-score-v1"

SCORE_BANDS: tuple[tuple[float, float, str], ...] = (
    (0.0, 39.999, "0-39"),
    (40.0, 59.999, "40-59"),
    (60.0, 79.999, "60-79"),
    (80.0, 89.999, "80-89"),
    (90.0, 100.0, "90-100"),
)

# 与研究引擎 candle_quiet 同源：小 K 线 = 振幅 <= 5%
QUIET_CANDLE_RANGE_MAX_PCT = 5.0


@dataclass(frozen=True)
class ScoreComponent:
    """One weighted factor condition in the composite score."""

    key: str
    label: str
    passed: bool
    points: float
    max_points: float
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "passed": self.passed,
            "points": self.points,
            "max_points": self.max_points,
            "detail": self.detail,
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
    """趋势回踩候选综合分（0-100）。前置：v4 规则已硬过滤双否决。"""

    candle_range = _number(features.get("candle_range_pct"))
    candle_quiet = bool(features.get("candle_quiet"))
    ma5_touch = bool(features.get("ma5_low_touch"))
    ma10_touch = bool(features.get("ma10_low_touch"))
    dist_excess = _number(features.get("trend_dist_excess_pct"))
    prior_return = _number(features.get("prior_daily_return_pct"))
    close_to_ma5 = _number(features.get("close_to_ma5_pct"))
    last_shrank = bool(features.get("last_volume_shrank"))

    components = (
        _component(
            "candle_quiet",
            "安静小K线",
            candle_quiet,
            20.0 if candle_quiet else 0.0,
            20.0,
            f"振幅 {_fmt(candle_range)}%（≤5% 为小K线）",
        ),
        _component(
            "touch_line",
            "回踩均线",
            ma5_touch or ma10_touch,
            15.0 if ma5_touch else (8.0 if ma10_touch else 0.0),
            15.0,
            (
                "低点回踩 MA5"
                if ma5_touch
                else ("低点回踩 MA10" if ma10_touch else "未回踩 MA5/MA10")
            ),
        ),
        _component(
            "dist_excess",
            "趋势老嫩",
            dist_excess is not None and dist_excess < 2.0,
            (
                20.0
                if dist_excess is not None and dist_excess < 0
                else (12.0 if dist_excess is not None and dist_excess < 1.0 else 6.0)
            ),
            20.0,
            (
                f"M5-M10 距离较本段回踩中位 {_fmt(dist_excess, signed=True)}pct"
                if dist_excess is not None
                else "本段无回踩参照"
            ),
        ),
        _component(
            "prior_day_down",
            "昨日已跌",
            prior_return is not None and prior_return <= 0,
            (
                10.0
                if prior_return is not None and prior_return <= 0
                else (5.0 if prior_return is not None and prior_return <= 1.0 else 0.0)
            ),
            10.0,
            f"昨日涨跌 {_fmt(prior_return, signed=True)}%",
        ),
        _component(
            "close_position",
            "收盘位置",
            close_to_ma5 is not None and close_to_ma5 <= 0,
            (
                10.0
                if close_to_ma5 is not None and close_to_ma5 <= 0
                else (5.0 if close_to_ma5 is not None and close_to_ma5 <= 1.0 else 0.0)
            ),
            10.0,
            f"收盘距 MA5 {_fmt(close_to_ma5, signed=True)}%",
        ),
        _component(
            "quiet_streak",
            "连续小K线",
            streak.total >= 2,
            (
                20.0
                if streak.total >= 4
                else (12.0 if streak.total >= 3 else (6.0 if streak.total >= 2 else 0.0))
            ),
            20.0,
            streak.label,
        ),
        _component(
            "volume_shrink",
            "缩量",
            last_shrank,
            5.0 if last_shrank else 0.0,
            5.0,
            "当日成交量低于前日" if last_shrank else "当日未缩量",
        ),
    )
    return _total(components), components


def score_oversold_candidate(
    features: Mapping[str, object],
    streak: QuietStreak,
) -> tuple[float, tuple[ScoreComponent, ...]]:
    """超跌反弹候选综合分（0-100）。前置：oversold_process_eligible。"""

    low_support = bool(features.get("oversold_low_support"))
    turnover = _number(features.get("turnover_rate_pct"))
    tight = bool(features.get("capitulation_rebound_tight"))
    broad = bool(features.get("capitulation_rebound_broad"))
    close_off_low = _number(features.get("close_off_low_pct"))
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
    candle_quiet = bool(features.get("candle_quiet"))
    candle_range = _number(features.get("candle_range_pct"))
    long_bear = bool(features.get("long_bear_alignment"))

    components = (
        _component(
            "low_support",
            "低点获均线支撑",
            low_support,
            20.0 if low_support else 0.0,
            20.0,
            "D 日低点在 MA10/20/30 获实际支撑" if low_support else "低点未获均线支撑",
        ),
        _component(
            "turnover",
            "换手率门禁",
            turnover is not None and turnover < 8.0,
            (
                20.0
                if turnover is not None and turnover < 3.0
                else (
                    12.0
                    if turnover is not None and turnover < 5.0
                    else (6.0 if turnover is not None and turnover < 8.0 else 0.0)
                )
            ),
            20.0,
            f"换手率 {_fmt(turnover)}%（<3% 最优 / <8% 门禁）",
        ),
        _component(
            "capitulation",
            "崩盘脱离低点",
            tight or broad,
            15.0 if tight else (8.0 if broad else 0.0),
            15.0,
            (
                f"收盘脱离低点 {_fmt(close_off_low)}%（0.3~1.5% 为紧凑反弹）"
                if close_off_low is not None
                else "无崩盘反弹形态"
            ),
        ),
        _component(
            "process_structure",
            "上穿过程结构",
            process,
            15.0 if process else 0.0,
            15.0,
            "MA10 分阶段上穿/联合上攻结构成立" if process else "分阶段上穿结构不成立",
        ),
        _component(
            "close_reaction",
            "收盘支撑反应",
            reaction,
            10.0 if reaction else 0.0,
            10.0,
            "收盘守住支撑有反应" if reaction else "收盘无支撑反应",
        ),
        _component(
            "volume_shape",
            "量能形态",
            shrink,
            10.0 if shrink else 0.0,
            10.0,
            "梯形缩量" if shrink else "非梯形缩量",
        ),
        _component(
            "candle_quiet",
            "安静小K线",
            candle_quiet,
            5.0 if candle_quiet else 0.0,
            5.0,
            f"振幅 {_fmt(candle_range)}%",
        ),
        _component(
            "quiet_streak",
            "连续小K线",
            streak.total >= 2,
            5.0 if streak.total >= 2 else 0.0,
            5.0,
            streak.label,
        ),
    )
    return _total(components), components


def _component(
    key: str,
    label: str,
    passed: bool,
    points: float,
    max_points: float,
    detail: str,
) -> ScoreComponent:
    return ScoreComponent(
        key=key,
        label=label,
        passed=passed,
        points=round(points, 2),
        max_points=max_points,
        detail=detail,
    )


def _total(components: Sequence[ScoreComponent]) -> float:
    return round(min(100.0, sum(item.points for item in components)), 2)


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
