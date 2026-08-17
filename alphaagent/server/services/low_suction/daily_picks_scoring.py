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


SCORE_VERSION = "low-suction-daily-score-v3.4"

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
# 上穿前价格先行（X/Y）路径的攻击强度投票：每条市场验证轴 +2，满 4 票 +8。
ATTACK_VOTE_POINTS_EACH = 2.0
ATTACK_VOTE_MAX_COUNT = 4
# 三线包裹链（W/Z）路径附加分（2026-08 校准升级，桶证据见节点注释）：
# W 安静包裹：信号日振幅 <3% 满 4 / 3~4% 得 2——包裹日振幅是强单调轴
# （半年池内 <4% 桶 80.8%/+1.00 vs 4~6% 桶 50.0% vs ≥6% 桶 0%）；分值
# 刻意低于 Z 链式（两日结构多一层时间确认），避免单日消息形态压过
# 弱市攻击（X）主榜。
# Z 链式确认 +6（两日链式结构池内 69.0%/+0.86，与 X 同档）+
# 缩量确认 +2（确认日 5/10 均量比 <0.9 桶 71.4%/+1.49 vs >1.1 桶 60%/+0.37）。
THREE_MA_WRAP_QUIET_FULL_RANGE_MAX_PCT = 3.0
THREE_MA_WRAP_QUIET_RANGE_MAX_PCT = 4.0
THREE_MA_WRAP_QUIET_FULL_POINTS = 4.0
THREE_MA_WRAP_QUIET_PART_POINTS = 2.0
POST_WRAP_CHAIN_POINTS = 6.0
POST_WRAP_SHRINK_CONFIRM_POINTS = 2.0
POST_WRAP_SHRINK_CONFIRM_VOL_RATIO_MAX = 0.9
# 趋势族重构（2026-08 连板后补涨/弱转强）评分常量：底盘分量满 100 ×0.4 + 路径
# 组件 ≤30 直加 = 满值约 70，与超跌族同量纲（SCORE_BANDS 两族共用语义不变）。
# 底盘不设换手硬门禁 —— 妖股连板票 20-38% 换手是常态（旧版无 gate 理由延续）。
TREND_STREAK_POINTS = (16.0, 22.0, 18.0)  # 4-6 / 7-9 / >=10（7-9 桶 54%/+0.73）
TREND_TIMING_POINTS = (18.0, 13.0, 11.0, 7.0, 13.0)  # dsp<=4/5-9/10-17/18-24/25-30
TREND_CLOSE_CONTROL_POINTS = (20.0, 15.0, 9.0, 4.0)  # close_off_low >=8/4-8/2-4/<2
TREND_VOLUME_DRYNESS_POINTS = (22.0, 16.0, 9.0, 4.0)  # vol_vs_peak <=10/10-20/20-40/>40
TREND_TURNOVER_POINTS = (18.0, 13.0, 8.0, 3.0)  # >=20/8-20/3-8/<3
# B 涨停弱转强路径组件（拉起幅度轴 = B 池核心排序证据）
TREND_RECLAIM_OPEN_DEPTH_POINTS = (10.0, 6.0)  # open_chg <=-3 / <=0
TREND_RECLAIM_MAGNITUDE_POINTS = (12.0, 8.0, 4.0)  # close_off_low >=12/8/4
TREND_RECLAIM_STREAK_PREMIUM_POINTS = 8.0  # streak >=7
# A 补涨涨停路径组件（2026-08-17 涨停确认制定稿的桶证据：平开 0~2 最从容
# 64.6-72%；换手 10~20 甜点 63.5% vs >=20 崩 45.3%；量能恢复段峰 30~60 健康
# 63.5% vs >60 过热 52.9%）
TREND_PULLBACK_FLAT_OPEN_POINTS = (10.0, 7.0, 4.0)  # open 0-1 / 1-2 / 2-3
TREND_PULLBACK_TURNOVER_SWEET_POINTS = (12.0, 8.0)  # 10~20 / <10
TREND_PULLBACK_VOLUME_RECOVERY_POINTS = (8.0, 4.0)  # 段峰 30~60 / >60


@dataclass(frozen=True)
class ScoreComponent:
    """One weighted factor condition in the composite score."""

    key: str
    label: str
    passed: bool
    points: float
    max_points: float
    detail: str
    kind: str = "bonus"  # gate（硬门禁）/ bonus（梯度）/ priority（层级下限）

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
    *,
    weak_to_strong_reclaim_rule_matched: bool = False,
    limit_up_pullback_rule_matched: bool = False,
) -> tuple[float, tuple[ScoreComponent, ...]]:
    """趋势族（连板后补涨/弱转强）候选诊断排序分。

    公共底盘因子（满 100 ×0.4 = 40）+ 路径组件因子（命中才加，≤30 直加）
    = 满值约 70，与超跌族同量纲。底盘为连板妖股回落语境的通用梯度（连板
    高度 / 距顶甜点 / 收盘控制 / 量能枯竭 / 换手承接）；B 涨停弱转强组件
    吃低开深度与拉板力度，A 补涨涨停组件吃平开直接性、换手甜点与量能恢复
    度。无换手硬门禁 —— 妖股 20-38% 换手是常态。
    """

    streak_max = int(features.get("limit_up_close_streak_max_60d") or 0)
    days_since_peak = features.get("days_since_streak_peak_60d")
    days_since_peak = int(days_since_peak) if days_since_peak is not None else None
    close_off_low = _number(features.get("close_off_low_pct"))
    vol_vs_peak = _number(features.get("volume_to_streak_peak_pct"))
    turnover = _number(features.get("turnover_rate_pct"))
    open_chg = _number(features.get("open_to_prev_close_pct"))

    streak_pts = (
        TREND_STREAK_POINTS[1] if 7 <= streak_max <= 9
        else (TREND_STREAK_POINTS[2] if streak_max >= 10
              else (TREND_STREAK_POINTS[0] if streak_max >= 4 else 0.0))
    )
    if days_since_peak is None:
        timing_pts = 0.0
        timing_detail = "无连板段顶参照"
    elif days_since_peak <= 4:
        timing_pts = TREND_TIMING_POINTS[0]
    elif days_since_peak <= 9:
        timing_pts = TREND_TIMING_POINTS[1]
    elif days_since_peak <= 17:
        timing_pts = TREND_TIMING_POINTS[2]
    elif days_since_peak <= 24:
        timing_pts = TREND_TIMING_POINTS[3]
    else:
        timing_pts = TREND_TIMING_POINTS[4]
    if close_off_low is None:
        control_pts = 0.0
    elif close_off_low >= 8:
        control_pts = TREND_CLOSE_CONTROL_POINTS[0]
    elif close_off_low >= 4:
        control_pts = TREND_CLOSE_CONTROL_POINTS[1]
    elif close_off_low >= 2:
        control_pts = TREND_CLOSE_CONTROL_POINTS[2]
    else:
        control_pts = TREND_CLOSE_CONTROL_POINTS[3]
    if vol_vs_peak is None:
        dry_pts = 0.0
    elif vol_vs_peak <= 10:
        dry_pts = TREND_VOLUME_DRYNESS_POINTS[0]
    elif vol_vs_peak <= 20:
        dry_pts = TREND_VOLUME_DRYNESS_POINTS[1]
    elif vol_vs_peak <= 40:
        dry_pts = TREND_VOLUME_DRYNESS_POINTS[2]
    else:
        dry_pts = TREND_VOLUME_DRYNESS_POINTS[3]
    if turnover is None:
        turnover_pts = 0.0
    elif turnover >= 20:
        turnover_pts = TREND_TURNOVER_POINTS[0]
    elif turnover >= 8:
        turnover_pts = TREND_TURNOVER_POINTS[1]
    elif turnover >= 3:
        turnover_pts = TREND_TURNOVER_POINTS[2]
    else:
        turnover_pts = TREND_TURNOVER_POINTS[3]

    # B 涨停弱转强路径组件
    reclaim_open_pts = 0.0
    if weak_to_strong_reclaim_rule_matched and open_chg is not None:
        reclaim_open_pts = (
            TREND_RECLAIM_OPEN_DEPTH_POINTS[0]
            if open_chg <= -3
            else (TREND_RECLAIM_OPEN_DEPTH_POINTS[1] if open_chg <= 0 else 0.0)
        )
    reclaim_magnitude_pts = 0.0
    if weak_to_strong_reclaim_rule_matched and close_off_low is not None:
        reclaim_magnitude_pts = (
            TREND_RECLAIM_MAGNITUDE_POINTS[0]
            if close_off_low >= 12
            else (TREND_RECLAIM_MAGNITUDE_POINTS[1] if close_off_low >= 8
                  else (TREND_RECLAIM_MAGNITUDE_POINTS[2] if close_off_low >= 4 else 0.0))
        )
    reclaim_streak_pts = (
        TREND_RECLAIM_STREAK_PREMIUM_POINTS
        if weak_to_strong_reclaim_rule_matched and streak_max >= 7
        else 0.0
    )

    # A 补涨涨停路径组件
    pullback_flat_pts = 0.0
    if limit_up_pullback_rule_matched and open_chg is not None:
        if open_chg < 1.0:
            pullback_flat_pts = TREND_PULLBACK_FLAT_OPEN_POINTS[0]
        elif open_chg < 2.0:
            pullback_flat_pts = TREND_PULLBACK_FLAT_OPEN_POINTS[1]
        else:
            pullback_flat_pts = TREND_PULLBACK_FLAT_OPEN_POINTS[2]
    pullback_turnover_pts = (
        TREND_PULLBACK_TURNOVER_SWEET_POINTS[0]
        if limit_up_pullback_rule_matched
        and turnover is not None
        and 10.0 <= turnover < 20.0
        else (TREND_PULLBACK_TURNOVER_SWEET_POINTS[1]
              if limit_up_pullback_rule_matched and turnover is not None
              else 0.0)
    )
    pullback_recovery_pts = (
        TREND_PULLBACK_VOLUME_RECOVERY_POINTS[0]
        if limit_up_pullback_rule_matched
        and vol_vs_peak is not None
        and 30.0 < vol_vs_peak <= 60.0
        else (TREND_PULLBACK_VOLUME_RECOVERY_POINTS[1]
              if limit_up_pullback_rule_matched
              and vol_vs_peak is not None
              and vol_vs_peak > 60.0
              else 0.0)
    )

    base_components = (
        _component(
            "limit_up_streak_strength",
            "连板高度",
            streak_pts > 0,
            streak_pts,
            max(TREND_STREAK_POINTS),
            f"主段 {streak_max} 连板（7-9 满22）",
        ),
        _component(
            "pullback_timing",
            "距顶甜点",
            timing_pts > 0,
            timing_pts,
            max(TREND_TIMING_POINTS),
            (
                f"段顶后 {days_since_peak} 个交易日"
                if days_since_peak is not None
                else "无连板段顶参照"
            ),
        ),
        _component(
            "close_control",
            "收盘控制",
            control_pts > 0,
            control_pts,
            max(TREND_CLOSE_CONTROL_POINTS),
            f"收盘脱离低点 {_fmt(close_off_low, signed=True)}pct",
        ),
        _component(
            "volume_dryness",
            "量能枯竭",
            dry_pts > 0,
            dry_pts,
            max(TREND_VOLUME_DRYNESS_POINTS),
            (
                f"量能为主段峰值 {_fmt(vol_vs_peak)}%（≤10% 满22）"
                if vol_vs_peak is not None
                else "无主段峰值量参照"
            ),
        ),
        _component(
            "turnover_activity",
            "换手承接",
            turnover_pts > 0,
            turnover_pts,
            max(TREND_TURNOVER_POINTS),
            f"换手 {_fmt(turnover)}%（≥20% 满18）",
        ),
        _component(
            "reclaim_open_depth",
            "低开深度",
            reclaim_open_pts > 0,
            reclaim_open_pts,
            TREND_RECLAIM_OPEN_DEPTH_POINTS[0],
            (
                f"B 路径开盘 {_fmt(open_chg, signed=True)}%"
                if weak_to_strong_reclaim_rule_matched
                else "非涨停弱转强路径"
            ),
        ),
        _component(
            "reclaim_magnitude",
            "拉板力度",
            reclaim_magnitude_pts > 0,
            reclaim_magnitude_pts,
            TREND_RECLAIM_MAGNITUDE_POINTS[0],
            (
                f"B 路径收盘脱离低点 {_fmt(close_off_low, signed=True)}pct"
                if weak_to_strong_reclaim_rule_matched
                else "非涨停弱转强路径"
            ),
        ),
        _component(
            "reclaim_streak_premium",
            "高连板加成",
            reclaim_streak_pts > 0,
            reclaim_streak_pts,
            TREND_RECLAIM_STREAK_PREMIUM_POINTS,
            (
                f"B 路径主段 {streak_max} 连板"
                if weak_to_strong_reclaim_rule_matched
                else "非涨停弱转强路径"
            ),
        ),
        _component(
            "pullback_flat_open_direct",
            "平开直接性",
            pullback_flat_pts > 0,
            pullback_flat_pts,
            TREND_PULLBACK_FLAT_OPEN_POINTS[0],
            (
                f"A 路径开盘 {_fmt(open_chg, signed=True)}%（0~1% 从容平开满10）"
                if limit_up_pullback_rule_matched
                else "非补涨涨停路径"
            ),
        ),
        _component(
            "pullback_turnover_sweet",
            "换手甜点",
            pullback_turnover_pts > 0,
            pullback_turnover_pts,
            TREND_PULLBACK_TURNOVER_SWEET_POINTS[0],
            (
                f"A 路径换手 {_fmt(turnover)}%（10~20% 甜点满12）"
                if limit_up_pullback_rule_matched
                else "非补涨涨停路径"
            ),
        ),
        _component(
            "pullback_volume_recovery",
            "量能恢复",
            pullback_recovery_pts > 0,
            pullback_recovery_pts,
            TREND_PULLBACK_VOLUME_RECOVERY_POINTS[0],
            (
                f"A 路径量能为主段峰值 {_fmt(vol_vs_peak)}%（30~60% 健康恢复满8）"
                if limit_up_pullback_rule_matched
                else "非补涨涨停路径"
            ),
        ),
    )
    base_pts = sum(
        c.points
        for c in base_components
        if c.key
        in {
            "limit_up_streak_strength",
            "pullback_timing",
            "close_control",
            "volume_dryness",
            "turnover_activity",
        }
    )
    raw = (
        base_pts * 0.4
        + reclaim_open_pts
        + reclaim_magnitude_pts
        + reclaim_streak_pts
        + pullback_flat_pts
        + pullback_turnover_pts
        + pullback_recovery_pts
    )
    return round(min(100.0, raw), 2), base_components


def score_oversold_candidate(
    features: Mapping[str, object],
    streak: QuietStreak,
    vol_ratio: float | None = None,
    *,
    staged_ma30_convergence_rule_matched: bool = False,
    attack_vote_count: int = 0,
    three_ma_wrap_rule_matched: bool = False,
    post_wrap_confirmation_rule_matched: bool = False,
) -> tuple[float, tuple[ScoreComponent, ...]]:
    """超跌反弹候选的诊断排序分。

    研究规则先决定是否入池，本函数只比较已命中规则的候选。换手率≥8%
    会触发评分门禁并封顶 39；其余基础特征按 0.4 折算。P1 的“向 MA30
    收敛”和“活跃承接”是已验证的同路径加分；X/Y 上穿前价格先行路径的
    “攻击强度投票”按票直加（每票 2 分，满 4 票 8 分）；三线包裹链
    （W/Z）按“安静包裹 / 链式+缩量确认”直加。``vol_ratio``
    是 scanner 从可见历史算出的近 5/10 日均量比。
    """

    turnover = _number(features.get("turnover_rate_pct"))
    candle_range = _number(features.get("candle_range_pct"))
    close_off_low = _number(features.get("close_off_low_pct"))
    low_support = bool(features.get("oversold_low_support"))
    tight = bool(features.get("capitulation_rebound_tight"))
    broad = bool(features.get("capitulation_rebound_broad"))
    process = bool(features.get("staged_m10_first"))
    reaction = bool(features.get("support_close_reaction"))
    shrink = str(features.get("volume_shape") or "") == "staircase_shrink"
    long_bear_days = int(features.get("prior_bear_alignment_days") or 0)
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
    attack_votes = max(0, min(ATTACK_VOTE_MAX_COUNT, int(attack_vote_count)))
    attack_vote_pts = attack_votes * ATTACK_VOTE_POINTS_EACH
    wrap_quiet_pts = 0.0
    if three_ma_wrap_rule_matched and candle_range is not None:
        if candle_range < THREE_MA_WRAP_QUIET_FULL_RANGE_MAX_PCT:
            wrap_quiet_pts = THREE_MA_WRAP_QUIET_FULL_POINTS
        elif candle_range < THREE_MA_WRAP_QUIET_RANGE_MAX_PCT:
            wrap_quiet_pts = THREE_MA_WRAP_QUIET_PART_POINTS
    post_wrap_chain_pts = (
        POST_WRAP_CHAIN_POINTS if post_wrap_confirmation_rule_matched else 0.0
    )
    post_wrap_shrink_confirm = bool(
        post_wrap_confirmation_rule_matched
        and vol_ratio is not None
        and vol_ratio < POST_WRAP_SHRINK_CONFIRM_VOL_RATIO_MAX
    )
    post_wrap_shrink_confirm_pts = (
        POST_WRAP_SHRINK_CONFIRM_POINTS if post_wrap_shrink_confirm else 0.0
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
    base_components = (
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
            "P1 的 MA10 分阶段上穿结构成立"
            if process
            else "非 P1 的 MA10 分阶段上穿结构",
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
            "attack_votes",
            "攻击强度投票",
            attack_votes > 0,
            attack_vote_pts,
            ATTACK_VOTE_POINTS_EACH * ATTACK_VOTE_MAX_COUNT,
            (
                f"X/Y 路径 {attack_votes}/4 票（gap 快收/放量/MA10 加速/宽开口，每票+2）"
                if attack_vote_count
                else "非上穿前价格先行路径"
            ),
        ),
        _component(
            "wrap_quiet_package",
            "安静包裹",
            wrap_quiet_pts > 0,
            wrap_quiet_pts,
            THREE_MA_WRAP_QUIET_FULL_POINTS,
            (
                f"W 路径振幅 {_fmt(candle_range)}%（<3% 满6，3~4% 得4）"
                if three_ma_wrap_rule_matched
                else "非三线包裹路径"
            ),
        ),
        _component(
            "post_wrap_chain_confirm",
            "链式+缩量确认",
            post_wrap_chain_pts + post_wrap_shrink_confirm_pts > 0,
            post_wrap_chain_pts + post_wrap_shrink_confirm_pts,
            POST_WRAP_CHAIN_POINTS + POST_WRAP_SHRINK_CONFIRM_POINTS,
            (
                f"Z 路径链式确认 +{POST_WRAP_CHAIN_POINTS:g}"
                + (
                    f"，均量比 {_fmt(vol_ratio)}<0.9 缩量确认 +{POST_WRAP_SHRINK_CONFIRM_POINTS:g}"
                    if post_wrap_shrink_confirm
                    else "，确认日未缩量"
                )
                if post_wrap_confirmation_rule_matched
                else "非上沿确认路径"
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
    base_pts = sum(
        c.points for c in base_components
        if c.kind == "bonus"
        and c.key not in {
            "staged_ma30_fast_convergence",
            "staged_ma30_active_participation",
            "attack_votes",
            "wrap_quiet_package",
            "post_wrap_chain_confirm",
        }
    )
    raw = (
        base_pts * 0.4
        + fast_staged_ma30_convergence_pts
        + staged_ma30_active_participation_pts
        + attack_vote_pts
        + wrap_quiet_pts
        + post_wrap_chain_pts
        + post_wrap_shrink_confirm_pts
    )
    if not gate_passed:
        raw = min(raw, OVERSOLD_GATE_FAILED_SCORE_CAP)
    return round(min(100.0, raw), 2), base_components


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
