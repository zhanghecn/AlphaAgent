"""低吸日线候选扫描器：把研究引擎的因果特征与 v3/v4 规则变成候选清单。

实时推荐与历史回测共用同一套扫描逻辑，差别只在数据窗口与是否带 D+1 标签。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from alphaagent.server.services.low_suction.daily_factor_extended_discovery import (
    _iter_candidate_snapshots,
    matching_discovery_rule_keys,
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

RULE_LABELS = {
    "v4_trend_quiet_pullback": "安静小K线回踩",
    "v4_trend_authentic_pullback": "真实回踩（非首阴追高）",
    "v3_oversold_staged_low_support_turnover_low": "分阶段上穿+低点支撑+低换手(<3%)",
    "v3_oversold_staged_low_support_turnover_gate": "分阶段上穿+低点支撑+换手门禁(<8%)",
    "v3_oversold_capitulation_rebound_tight": "崩盘紧凑反弹(换手<3%+脱离低点0.3~1.5%)",
    "v3_oversold_capitulation_rebound_broad": "崩盘宽幅反弹(换手<5%+脱离低点)",
}

# 同族多规则命中时的展示优先级（越靠前值越硬）
_TREND_RULE_PRIORITY = ("v4_trend_quiet_pullback", "v4_trend_authentic_pullback")
_OVERSOLD_RULE_PRIORITY = (
    "v3_oversold_capitulation_rebound_tight",
    "v3_oversold_staged_low_support_turnover_low",
    "v3_oversold_capitulation_rebound_broad",
    "v3_oversold_staged_low_support_turnover_gate",
)


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
    """Scan candidate snapshots and score the ones matching v3/v4 rules.

    ``target_dates`` 为 None 时扫描全窗口（回测）；传入单日集合即实时/补扫。
    """

    candidates: list[LowSuctionCandidate] = []
    snapshots = _iter_candidate_snapshots(
        bars,
        calendar,
        security_status,
        require_rule_match=True,
    )
    calendar_tuple = tuple(calendar)
    calendar_positions = {value: index for index, value in enumerate(calendar_tuple)}
    for snapshot in snapshots:
        if target_dates is not None and snapshot.trade_date not in target_dates:
            continue
        features = snapshot.features
        trend_rules = tuple(
            key
            for key in _TREND_RULE_PRIORITY
            if key in matching_discovery_rule_keys(features, "trend_pullback")
        )
        oversold_rules = tuple(
            key
            for key in _OVERSOLD_RULE_PRIORITY
            if key in matching_discovery_rule_keys(features, "oversold_rebound")
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
            if features.get("trend_bull_alignment"):
                continue  # 多头排列(MA10>MA20>MA30)成立 = 已是趋势族，不再作超跌反弹（超跌是空头→多头过渡期）
            history_vols = [_number(h.get("volume")) for h in snapshot.history[: snapshot.position + 1]]
            history_vols = [v for v in history_vols if v is not None]
            if len(history_vols) >= 10:
                vol_ratio = sum(history_vols[-5:]) / 5 / (sum(history_vols[-10:]) / 10)
            else:
                vol_ratio = None
            score, components = score_oversold_candidate(features, streak, vol_ratio=vol_ratio)
            if any(component.kind == "gate" and not component.passed for component in components):
                continue  # 超跌族换手门禁失败（≥8% 派发），不进候选清单
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
    candidates.sort(key=lambda item: (item.trade_date, -item.score, item.vt_symbol))
    return candidates


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
