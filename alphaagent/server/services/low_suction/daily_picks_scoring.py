"""低吸日线候选综合评分（纯函数层）。

只吃 ``build_extended_daily_features`` 的因果特征与可见 K 线历史，
不查库、不看未来收益。研究票规则决定候选是否入池；本模块保留当前
综合分作为排名偏差的诊断基线，不再决定准入。

权重设计来源（全量 811 交易日分桶验证，见任务报告）：
- 趋势族：安静 K 线 + 回踩线别 + 段内距离超额梯度 + 昨日已跌 +
  收盘位置 + 连续小 K 线 + 缩量。
- 超跌族：低点支撑 + 换手率梯度 + 崩盘脱离低点 + 过程结构 +
  收盘反应 + 梯形缩量 + 安静 K 线 + 长期空头。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


SCORE_VERSION = "low-suction-daily-score-v2.6"

SCORE_BANDS: tuple[tuple[float, float, str], ...] = (
    (0.0, 39.999, "0-39"),
    (40.0, 59.999, "40-59"),
    (60.0, 79.999, "60-79"),
    (80.0, 89.999, "80-89"),
    (90.0, 100.0, "90-100"),
)

# 与研究引擎 candle_quiet 同源：小 K 线 = 振幅 <= 5%
QUIET_CANDLE_RANGE_MAX_PCT = 5.0

# 历史评分阈值：只会封顶诊断分，不再决定研究规则候选是否入池。
OVERSOLD_TURNOVER_GATE_MAX_PCT = 8.0
# 历史评分阈值触发时的诊断分上限。
OVERSOLD_GATE_FAILED_SCORE_CAP = 39.0
# P1 路径的缩量地基不能收缩到无交易承接。该下限只影响该研究路径的诊断排序。
STAGED_MA30_ACTIVE_PARTICIPATION_MIN_PCT = 1.5


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
    """趋势回踩候选综合分（0-100），仅用于研究规则命中后的排序诊断。

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
    *,
    pre_cross_rule_matched: bool = False,
    stable_three_ma_wrap_rule_matched: bool = False,
    staged_ma30_convergence_rule_matched: bool = False,
) -> tuple[float, tuple[ScoreComponent, ...]]:
    """超跌反弹候选的诊断排序分（最高 140）。

    研究规则先决定是否入池，本函数只比较已命中规则的候选。换手率≥8%
    会触发评分门禁并封顶 39；其余基础特征按 0.4 折算，再叠加已验证研究
    路径的加分。``vol_ratio`` 是 scanner 从可见历史算出的近 5/10 日均量比。
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
            "ma10_crossed_ma30_within_15d",
        )
    )
    reaction = bool(features.get("support_close_reaction"))
    shrink = str(features.get("volume_shape") or "") == "staircase_shrink"
    long_bear_days = int(features.get("prior_bear_alignment_days") or 0)
    daily_return = _number(features.get("daily_return_pct"))
    next_close_required_return = _number(
        features.get("ma10_ma20_next_close_required_return_pct")
    )
    controlled_pre_cross_drive = bool(
        pre_cross_rule_matched
        and daily_return is not None
        and 1.5 <= daily_return < 5.0
        and next_close_required_return is not None
        and 0 < next_close_required_return < 5.0
    )
    controlled_pre_cross_drive_pts = 10.0 if controlled_pre_cross_drive else 0.0
    ma10_ma30_narrowing = _number(
        features.get("ma10_ma30_gap_narrowing_5d_pct")
    )
    fast_staged_ma30_convergence = bool(
        staged_ma30_convergence_rule_matched
        and ma10_ma30_narrowing is not None
        and ma10_ma30_narrowing >= 5.0
    )
    fast_staged_ma30_convergence_pts = 2.0 if fast_staged_ma30_convergence else 0.0
    staged_ma30_active_participation = bool(
        staged_ma30_convergence_rule_matched
        and turnover is not None
        and STAGED_MA30_ACTIVE_PARTICIPATION_MIN_PCT
        <= turnover
        < OVERSOLD_TURNOVER_GATE_MAX_PCT
    )
    staged_ma30_active_participation_pts = (
        8.0 if staged_ma30_active_participation else 0.0
    )

    gate_passed = turnover is not None and turnover < OVERSOLD_TURNOVER_GATE_MAX_PCT
    turnover_pts = (
        14.0
        if turnover is not None and turnover < 3.0
        else (
            10.0
            if turnover is not None and 3.0 <= turnover < 5.0
            else (
                4.0
                if turnover is not None and 5.0 <= turnover < 8.0
                else 0.0
            )
        )
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
    # 三线包裹好看度仅属于已命中的稳定包裹研究路径。不能让其他
    # 超跌路径因均线窄或缩量而借到这部分权重。
    yang_wrap = bool(features.get("yang_wrap_three_ma"))
    yang_wrap_after_long_bear_cross = yang_wrap and bool(
        features.get("ma10_crossed_ma20_after_long_bear_within_15d")
    )
    m10_cv = _number(features.get("ma10_slope_cv_6d"))
    vol_mono = _number(features.get("vol_monotone_6d"))
    body_excl = _number(features.get("body_max_excl_6d"))
    spread3 = _number(features.get("ma_cluster_spread_pct"))
    tr_pretty = _number(features.get("turnover_rate_pct"))
    hold_premium = _number(features.get("breakout_hold_premium"))
    stable_wrap_base = (
        stable_three_ma_wrap_rule_matched
        and yang_wrap_after_long_bear_cross
        and bool(features.get("yang_wrap_stable_base"))
    )
    wrap_low_distance = _number(features.get("yang_wrap_nearest_ma_low_abs_pct"))
    wrap_volume_end_to_peak = _number(
        features.get("yang_wrap_volume_end_to_peak_ratio_6d")
    )
    # 活跃度（主人"死股偏好"反向纠偏：2~5%换手=有资金承接的活跃真低吸加分，
    # 接近死股的低换手不加分——yang_wrap票里活跃的(传智4.87%)D+5涨43%，温和的(1.6%)只涨2%）
    active_pts = (
        8.0 if tr_pretty is not None and 2.0 <= tr_pretty < 5.0
        else (5.0 if tr_pretty is not None and 5.0 <= tr_pretty < 8.0
              else (4.0 if tr_pretty is not None and 1.5 <= tr_pretty < 2.0 else 0.0))
    )
    # 上穿后守住（主人"涨2次跳水=假突破波折"判据）：
    # 守住(溢价>+3%,真突破平滑)+15，边缘+8，回吐(假突破)0 —— 前12名只有传智守住、其余全回吐
    hold_pts = (
        15.0 if hold_premium is not None and hold_premium > 3.0
        else (8.0 if hold_premium is not None and hold_premium > 1.0 else 0.0)
    )
    pretty_pts = 0.0
    if stable_wrap_base:
        pretty_pts = 40.0 + active_pts + hold_pts
        pretty_pts += (
            max(0.0, (6.0 - abs(spread3)) / 6.0 * 12.0)
            if spread3 is not None
            else 0.0
        )
        pretty_pts += (
            max(0.0, (80.0 - m10_cv) / 80.0 * 8.0)
            if m10_cv is not None
            else 0.0
        )
        pretty_pts += (vol_mono * 8.0) if vol_mono is not None else 0.0
        pretty_pts += (
            max(0.0, (2.5 - body_excl) / 2.5 * 4.0)
            if body_excl is not None
            else 0.0
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
            "yang_wrap_pretty",
            "阳线包裹好看度",
            pretty_pts > 0,
            pretty_pts,
            95.0,
            (
                f"阳线包裹三线★ 平滑{_fmt(m10_cv)} 梯形{_fmt(vol_mono)}"
                if stable_wrap_base
                else (
                    "三线几何包裹但未命中稳定包裹研究路径"
                    if yang_wrap_after_long_bear_cross
                    else (
                        "三线几何包裹但未完成长期空头后 MA10 上穿 MA20"
                        if yang_wrap
                        else f"非稳定三线包裹路径 平滑{_fmt(m10_cv)} 梯形{_fmt(vol_mono)}"
                    )
                )
            ),
        ),
        _component(
            "yang_wrap_stable_base",
            "前期稳定地基",
            stable_wrap_base,
            8.0 if stable_wrap_base else 0.0,
            8.0,
            f"低点距三线 {_fmt(wrap_low_distance)}%，D量/6日峰 {_fmt(wrap_volume_end_to_peak)}",
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
            "MA10 分阶段上穿结构成立" if process else "分阶段上穿结构不成立",
        ),
        _component(
            "staged_ma30_fast_convergence",
            "MA10 向 MA30 快速收敛",
            fast_staged_ma30_convergence,
            fast_staged_ma30_convergence_pts,
            2.0,
            (
                f"5日 MA10-MA30 缩差 {_fmt(ma10_ma30_narrowing)}%（>=5%）"
                if staged_ma30_convergence_rule_matched
                else "非 MA10 向 MA30 分阶段收敛路径"
            ),
        ),
        _component(
            "staged_ma30_active_participation",
            "收缩后活跃承接",
            staged_ma30_active_participation,
            staged_ma30_active_participation_pts,
            8.0,
            (
                f"P1 路径换手 {_fmt(turnover)}%（{STAGED_MA30_ACTIVE_PARTICIPATION_MIN_PCT:g}%~{OVERSOLD_TURNOVER_GATE_MAX_PCT:g}%）"
                if staged_ma30_convergence_rule_matched
                else "非 MA10 向 MA30 分阶段收敛路径"
            ),
        ),
        _component(
            "pre_cross_controlled_drive",
            "预上穿受控启动",
            controlled_pre_cross_drive,
            controlled_pre_cross_drive_pts,
            10.0,
            (
                f"D日 {_fmt(daily_return, signed=True)}%，D+1 需 {_fmt(next_close_required_return, signed=True)}% 使 MA10≥MA20"
                if pre_cross_rule_matched
                else "非 MA10/20 预上穿路径"
            ),
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
    # 稳定地基独立优先，避免把低点远离均线或量未收缩的强行包裹排在研究形态之前。
    base_pts = sum(
        c.points for c in components
        if c.kind == "bonus"
        and c.key not in {
            "yang_wrap_pretty",
            "yang_wrap_stable_base",
            "pre_cross_controlled_drive",
            "staged_ma30_fast_convergence",
            "staged_ma30_active_participation",
        }
    )
    stable_base_pts = 8.0 if stable_wrap_base else 0.0
    raw = (
        base_pts * 0.4
        + pretty_pts
        + stable_base_pts
        + controlled_pre_cross_drive_pts
        + fast_staged_ma30_convergence_pts
        + staged_ma30_active_participation_pts
    )
    if not gate_passed:
        raw = min(raw, OVERSOLD_GATE_FAILED_SCORE_CAP)
    return round(min(140.0, raw), 2), components


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
    max_total: float = 100.0,
) -> float:
    raw = sum(item.points for item in components)
    if gate_failed_cap is not None and any(
        item.kind == "gate" and not item.passed for item in components
    ):
        raw = min(raw, gate_failed_cap)
    return round(min(max_total, raw), 2)


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
