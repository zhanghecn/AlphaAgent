"""低吸日线候选扫描器：把研究票的因果规则变成候选清单。

实时推荐与历史回测共用同一套扫描逻辑，差别只在数据窗口与是否带 D+1 标签。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from alphaagent.server.services.low_suction.daily_factor_extended_discovery import (
    DISCOVERY_RULES,
    FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
    STAGED_MA10_SUPPORT_RULE_KEY,
    _iter_candidate_snapshots,
    build_pre_attack_base_process_features,
    is_mature_first_leg_two_ma_wrap_qualified,
    matching_discovery_rule_keys,
)
from alphaagent.server.services.low_suction.daily_factor_research import (
    is_main_board_limit_up_touched,
)
from alphaagent.server.services.low_suction.daily_picks_scoring import (
    QuietStreak,
    ScoreComponent,
    quiet_candle_streak,
    score_band,
    score_oversold_candidate,
    score_trend_candidate,
)


SETUP_TYPE_LABELS = {
    "trend_pullback": "上升趋势低吸",
    "oversold_rebound": "超跌反弹低吸",
}
P1_5_TURNOVER_TARGET_PCT = 3.0
PRODUCT_OVERSOLD_RULE_KEYS = frozenset(
    {
        FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
        STAGED_MA10_SUPPORT_RULE_KEY,
    }
)
PRODUCT_DISCOVERY_RULES = {
    "oversold_rebound": tuple(
        rule
        for rule in DISCOVERY_RULES["oversold_rebound"]
        if rule.key in PRODUCT_OVERSOLD_RULE_KEYS
    ),
    # 趋势族尚未收敛，保持当前产品行为，后续单独研究。
    "trend_pullback": DISCOVERY_RULES["trend_pullback"],
}

RULE_LABELS = {
    rule.key: rule.description
    for rules in PRODUCT_DISCOVERY_RULES.values()
    for rule in rules
}


@dataclass(frozen=True)
class LowSuctionCandidate:
    """One scored low-suction candidate for a single trade date."""

    vt_symbol: str
    trade_date: date
    setup_type: str
    rule_key: str
    matched_rule_keys: tuple[str, ...]
    score: float
    band: str
    streak: QuietStreak
    components: tuple[ScoreComponent, ...]
    close_price: float | None
    daily_return_pct: float | None
    turnover_rate_pct: float | None
    candle_range_pct: float | None
    d1_trade_date: date | None
    d1_close_return_pct: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "vt_symbol": self.vt_symbol,
            "symbol": self.vt_symbol.split(".")[0],
            "trade_date": self.trade_date.isoformat(),
            "setup_type": self.setup_type,
            "setup_label": SETUP_TYPE_LABELS[self.setup_type],
            "rule_key": self.rule_key,
            "rule_label": RULE_LABELS.get(self.rule_key, self.rule_key),
            "matched_rule_keys": list(self.matched_rule_keys),
            "score": self.score,
            "band": self.band,
            "streak": {
                "total": self.streak.total,
                "yin": self.streak.yin,
                "yang": self.streak.yang,
                "label": self.streak.label,
            },
            "components": [item.as_dict() for item in self.components],
            "close_price": self.close_price,
            "daily_return_pct": self.daily_return_pct,
            "turnover_rate_pct": self.turnover_rate_pct,
            "candle_range_pct": self.candle_range_pct,
            "d1_trade_date": self.d1_trade_date.isoformat() if self.d1_trade_date else None,
            "d1_close_return_pct": self.d1_close_return_pct,
        }


def scan_low_suction_candidates(
    bars,
    calendar: Sequence[date],
    security_status: Sequence[Mapping[str, object]],
    *,
    target_dates: set[date] | None = None,
) -> list[LowSuctionCandidate]:
    """Scan source-rule candidates and attach the current diagnostic score.

    ``target_dates`` 为 None 时扫描全窗口（回测）；传入单日集合即实时/补扫。

    产品超跌池只放行两条跨窗口已验证路径：成熟首段两线攻击（P1.5）与
    分段 MA10 支撑（P1）。其余攻击锚点仍留在研究层，不会仅因形态相似
    进入实时推荐或回测仓位。
    """

    candidates: list[LowSuctionCandidate] = []
    snapshots = _iter_candidate_snapshots(
        bars,
        calendar,
        security_status,
        require_rule_match=True,
        rule_manifest=PRODUCT_DISCOVERY_RULES,
        target_dates=target_dates,
    )
    calendar_tuple = tuple(calendar)
    calendar_positions = {value: index for index, value in enumerate(calendar_tuple)}
    for snapshot in snapshots:
        if target_dates is not None and snapshot.trade_date not in target_dates:
            continue
        if _signal_day_limit_up_closed(snapshot.history, snapshot.position):
            continue
        features = snapshot.features
        prior_features = snapshot.prior_features
        trend_rules = matching_discovery_rule_keys(
            features,
            "trend_pullback",
            prior_features=prior_features,
            rules=PRODUCT_DISCOVERY_RULES["trend_pullback"],
        )
        matched_oversold_rules = matching_discovery_rule_keys(
            features,
            "oversold_rebound",
            prior_features=prior_features,
            rules=PRODUCT_DISCOVERY_RULES["oversold_rebound"],
        )
        oversold_rules = tuple(
            rule_key
            for rule_key in matched_oversold_rules
            if rule_key == STAGED_MA10_SUPPORT_RULE_KEY
        )
        if FIRST_LEG_TWO_MA_WRAP_RULE_KEY in matched_oversold_rules:
            base_features = build_pre_attack_base_process_features(
                snapshot.history[: snapshot.position + 1],
                include_d_minus_one=True,
            )
            first_leg_features = {**features, **base_features}
            if is_mature_first_leg_two_ma_wrap_qualified(first_leg_features):
                features = first_leg_features
                # P1.5 必须写在首位：同日同时命中 P1 时，rule_key 仍应反映
                # 经过完整底盘资格门的更高优先级路径。
                oversold_rules = (
                    FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
                    *oversold_rules,
                )
        if not trend_rules and not oversold_rules:
            continue
        streak = quiet_candle_streak(snapshot.history[: snapshot.position + 1])
        close_price = _number(features.get("close_price"))
        daily_return = _number(features.get("daily_return_pct"))
        turnover = _number(features.get("turnover_rate_pct"))
        candle_range = _number(features.get("candle_range_pct"))
        d1_return = snapshot.d1_close_return_pct
        calendar_position = calendar_positions.get(snapshot.trade_date)
        d1_date = (
            calendar_tuple[calendar_position + 1]
            if calendar_position is not None
            and calendar_position + 1 < len(calendar_tuple)
            and snapshot.d1_label_status == "available"
            else None
        )
        if trend_rules:
            score, components = score_trend_candidate(features, streak)
            candidates.append(
                LowSuctionCandidate(
                    vt_symbol=snapshot.symbol,
                    trade_date=snapshot.trade_date,
                    setup_type="trend_pullback",
                    rule_key=trend_rules[0],
                    matched_rule_keys=trend_rules,
                    score=score,
                    band=score_band(score),
                    streak=streak,
                    components=components,
                    close_price=close_price,
                    daily_return_pct=daily_return,
                    turnover_rate_pct=turnover,
                    candle_range_pct=candle_range,
                    d1_trade_date=d1_date,
                    d1_close_return_pct=d1_return,
                )
            )
        if oversold_rules:
            history_vols = [_number(h.get("volume")) for h in snapshot.history[: snapshot.position + 1]]
            history_vols = [v for v in history_vols if v is not None]
            if len(history_vols) >= 10:
                vol_ratio = sum(history_vols[-5:]) / 5 / (sum(history_vols[-10:]) / 10)
            else:
                vol_ratio = None
            score, components = score_oversold_candidate(
                features,
                streak,
                vol_ratio=vol_ratio,
                staged_ma30_convergence_rule_matched=(
                    STAGED_MA10_SUPPORT_RULE_KEY in oversold_rules
                ),
            )
            candidates.append(
                LowSuctionCandidate(
                    vt_symbol=snapshot.symbol,
                    trade_date=snapshot.trade_date,
                    setup_type="oversold_rebound",
                    rule_key=oversold_rules[0],
                    matched_rule_keys=oversold_rules,
                    score=score,
                    band=score_band(score),
                    streak=streak,
                    components=components,
                    close_price=close_price,
                    daily_return_pct=daily_return,
                    turnover_rate_pct=turnover,
                    candle_range_pct=candle_range,
                    d1_trade_date=d1_date,
                    d1_close_return_pct=d1_return,
                )
            )
    candidates.sort(key=lambda item: (item.trade_date, *candidate_ranking_key(item)))
    return candidates


def candidate_ranking_key(
    item: LowSuctionCandidate,
) -> tuple[int, float, float, int, float, str]:
    """Stable product ranking shared by live recommendations and backtests.

    超跌候选只包含已验证路径：成熟首段两线攻击（P1.5）优先于分段
    MA10 支撑（P1）。P1.5 内先比较综合诊断分；换手率距 3% 的接近度只
    用于同分决胜，避免一个单项覆盖均线、位置、K 线与量能的共同判断。
    """

    tier = _candidate_priority_tier(item)
    turnover_distance = 0.0
    if tier == 20:
        turnover_distance = (
            abs(item.turnover_rate_pct - P1_5_TURNOVER_TARGET_PCT)
            if item.turnover_rate_pct is not None
            else 99.0
        )
    return (
        -tier,
        -item.score,
        turnover_distance,
        -item.streak.total,
        item.turnover_rate_pct if item.turnover_rate_pct is not None else 99.0,
        item.vt_symbol,
    )


def _candidate_priority_tier(item: LowSuctionCandidate) -> int:
    if item.setup_type != "oversold_rebound":
        return 0
    matched = set(item.matched_rule_keys)
    if FIRST_LEG_TWO_MA_WRAP_RULE_KEY in matched:
        return 20
    if STAGED_MA10_SUPPORT_RULE_KEY in matched:
        return 10
    return 0


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _signal_day_limit_up_closed(
    history: Sequence[Mapping[str, object]],
    position: int,
) -> bool:
    """Exclude a main-board signal bar that closed at its upper price limit."""

    if position < 1 or position >= len(history):
        return False
    prior_close = _number(history[position - 1].get("close_price"))
    close_price = _number(history[position].get("close_price"))
    return bool(
        prior_close is not None
        and close_price is not None
        and is_main_board_limit_up_touched(prior_close, close_price)
    )
