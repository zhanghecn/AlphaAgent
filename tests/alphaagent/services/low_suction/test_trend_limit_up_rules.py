"""趋势族重构（连板后补涨/弱转强）产品规则回归。

覆盖：连板史特征块边界、B 涨停弱转强的涨停日豁免、A 弱市门、
tier/决胜键与锚点不进推荐。
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

import alphaagent.server.services.low_suction.daily_picks_scanner as scanner
from alphaagent.server.services.low_suction.daily_factor_extended_discovery import (
    LIMIT_UP_PULLBACK_REBOUND_RULE_KEY,
    LIMIT_UP_PULLBACK_WATCHLIST_RULE_KEY,
    LIMIT_UP_WEAK_TO_STRONG_RECLAIM_RULE_KEY,
    RESEARCH_WEAK_TO_STRONG_NO_LIMIT_RULE_KEY,
)
from alphaagent.server.services.low_suction.daily_picks_scanner import (
    _candidate_priority_tier,
)


def _bar(day: date, close: float, *, open_price: float | None = None,
         high: float | None = None, low: float | None = None,
         volume: float = 1_000.0) -> dict[str, object]:
    return {
        "trade_date": day,
        "open_price": open_price if open_price is not None else close * 0.99,
        "close_price": close,
        "high_price": high if high is not None else close * 1.01,
        "low_price": low if low is not None else close * 0.98,
        "volume": volume,
    }


def _limit_up_history(
    *, streak: int = 5, days_since_peak: int = 2, signal_limit_up: bool = False,
) -> list[dict[str, object]]:
    """合成 60+ 根历史：先 40 根横盘，随后 streak 连板（每日 +10%），
    再回落 days_since_peak 天，末根为信号日。"""
    start = date(2025, 1, 1)
    bars: list[dict[str, object]] = []
    day = start
    price = 10.0
    for _ in range(55):
        bars.append(_bar(day, price))
        day += timedelta(days=1)
        price *= 1.001
    for _ in range(streak):
        prev = price
        price = round(prev * 1.10, 2)
        bars.append(_bar(day, price, low=price * 0.995))
        day += timedelta(days=1)
    peak = price
    # 参数语义 = 信号日距段顶的交易日差（dsp）：回落 dsp-1 天后是信号日。
    for _ in range(max(0, days_since_peak - 1)):
        price = round(price * 0.94, 2)
        bars.append(_bar(day, price))
        day += timedelta(days=1)
    if signal_limit_up:
        prev_close = bars[-1]["close_price"]
        limit = round(float(prev_close) * 1.10, 2)
        bars.append(_bar(day, limit, open_price=float(prev_close) * 0.96, low=float(prev_close) * 0.95))
    else:
        prev_close = bars[-1]["close_price"]
        bars.append(_bar(day, round(float(prev_close) * 1.004, 2)))
    assert len(bars) >= 60
    return bars


class TestLimitUpStreakFeatures:
    def test_streak_peak_and_dryness_from_window(self) -> None:
        from alphaagent.server.services.low_suction.daily_factor_extended_discovery import (
            _limit_up_streak_features,
        )

        bars = _limit_up_history(streak=5, days_since_peak=2)
        features = _limit_up_streak_features(bars)

        assert features["limit_up_history_window_sessions"] >= 60
        assert features["limit_up_close_streak_max_60d"] == 5
        assert features["days_since_streak_peak_60d"] == 2
        assert features["limit_up_close_today"] is False
        assert features["close_to_prev_close_pct"] == pytest.approx(0.4, abs=0.2)
        assert features["volume_to_streak_peak_pct"] == pytest.approx(100.0, abs=0.5)
        assert features["volume_to_ma5_ratio"] == pytest.approx(1.0, abs=0.01)

    def test_signal_day_limit_up_starts_new_streak_not_main(self) -> None:
        from alphaagent.server.services.low_suction.daily_factor_extended_discovery import (
            _limit_up_streak_features,
        )

        bars = _limit_up_history(streak=5, days_since_peak=2, signal_limit_up=True)
        features = _limit_up_streak_features(bars)

        # D 日本身涨停：主段仍是之前 5 板段（不含 D 日的新段）。
        assert features["limit_up_close_today"] is True
        assert features["limit_up_close_streak_max_60d"] == 5

    def test_short_window_fails_closed(self) -> None:
        from alphaagent.server.services.low_suction.daily_factor_extended_discovery import (
            _limit_up_streak_features,
        )

        features = _limit_up_streak_features([_bar(date(2025, 1, 1), 10.0)])

        assert features["limit_up_history_window_sessions"] == 1
        assert features["limit_up_close_streak_max_60d"] == 0


def _trend_snapshot(features: dict[str, object], history, signal_date: date):
    return SimpleNamespace(
        symbol="600664.SSE",
        trade_date=signal_date,
        position=len(history) - 1,
        history=history,
        features=features,
        prior_features=None,
        d1_close_return_pct=5.0,
        d1_label_status="available",
    )


def _scan_trend(
    monkeypatch: pytest.MonkeyPatch,
    matched_rules: tuple[str, ...],
    history,
    *,
    regime_map: dict[date, str] | None = None,
    signal_date: date = date(2026, 7, 20),
):
    features = {
        "close_price": history[-1]["close_price"],
        "daily_return_pct": 1.0,
        "turnover_rate_pct": 25.0,
        "candle_range_pct": 8.0,
        "limit_up_close_streak_max_60d": 5,
        "days_since_streak_peak_60d": 1,
        "close_off_low_pct": 9.0,
        "volume_to_streak_peak_pct": 30.0,
        "open_to_prev_close_pct": -4.0,
    }
    snapshot = _trend_snapshot(features, history, signal_date)
    monkeypatch.setattr(
        scanner,
        "_iter_candidate_snapshots",
        lambda *args, **kwargs: iter((snapshot,)),
    )
    monkeypatch.setattr(
        scanner,
        "matching_discovery_rule_keys",
        lambda features, setup_type, *, prior_features=None, rules=None: (
            matched_rules if setup_type == "trend_pullback" else ()
        ),
    )
    return scanner.scan_low_suction_candidates(
        [],
        (signal_date, signal_date + timedelta(days=1)),
        [],
        target_dates={signal_date},
        market_regimes=regime_map,
    )


class TestScannerTrendRules:
    def test_limit_up_close_day_admits_both_limit_paths(self, monkeypatch) -> None:
        """涨停收盘日：B 弱转强与 A 补涨涨停两条涨停路径都放行；观察层仍剔除。"""
        signal_date = date(2026, 7, 20)
        limit_history = _limit_up_history(
            streak=5, days_since_peak=1, signal_limit_up=True
        )

        admitted_b = _scan_trend(
            monkeypatch,
            (LIMIT_UP_WEAK_TO_STRONG_RECLAIM_RULE_KEY,),
            limit_history,
            signal_date=signal_date,
        )
        assert [c.rule_key for c in admitted_b] == [
            LIMIT_UP_WEAK_TO_STRONG_RECLAIM_RULE_KEY
        ]

        admitted_a = _scan_trend(
            monkeypatch,
            (LIMIT_UP_PULLBACK_REBOUND_RULE_KEY,),
            limit_history,
            signal_date=signal_date,
        )
        assert [c.rule_key for c in admitted_a] == [
            LIMIT_UP_PULLBACK_REBOUND_RULE_KEY
        ]

        rejected_watch = _scan_trend(
            monkeypatch,
            (LIMIT_UP_PULLBACK_WATCHLIST_RULE_KEY,),
            limit_history,
            signal_date=signal_date,
        )
        assert rejected_watch == []

    def test_pullback_paths_have_no_regime_gate(self, monkeypatch) -> None:
        """主人定调：命中即放行，不设大盘环境门（强市/弱市都推荐）。"""
        signal_date = date(2026, 7, 20)
        history = _limit_up_history(streak=6, days_since_peak=15)

        for rule_key in (LIMIT_UP_PULLBACK_REBOUND_RULE_KEY,
                         LIMIT_UP_PULLBACK_WATCHLIST_RULE_KEY):
            admitted = _scan_trend(
                monkeypatch, (rule_key,), history,
                regime_map={signal_date: "above_ma20"},
                signal_date=signal_date,
            )
            assert [c.rule_key for c in admitted] == [rule_key]

    def test_research_anchor_is_intraday_prepare_in_product_scan(self) -> None:
        """锚点以「弱转强预备·未封板」身份进产品清单：盘中展示让用户提前
        准备打板；tier 0 + 不占仓位键集，收盘确认版由 service 过滤。"""
        assert RESEARCH_WEAK_TO_STRONG_NO_LIMIT_RULE_KEY in (
            scanner.PRODUCT_TREND_RULE_KEYS
        )
        assert {
            rule.key for rule in scanner.PRODUCT_DISCOVERY_RULES["trend_pullback"]
        } == {
            LIMIT_UP_WEAK_TO_STRONG_RECLAIM_RULE_KEY,
            LIMIT_UP_PULLBACK_REBOUND_RULE_KEY,
            LIMIT_UP_PULLBACK_WATCHLIST_RULE_KEY,
            RESEARCH_WEAK_TO_STRONG_NO_LIMIT_RULE_KEY,
        }
        assert scanner.TREND_WATCHLIST_RULE_KEYS == frozenset(
            {LIMIT_UP_PULLBACK_WATCHLIST_RULE_KEY}
        )
        # 回测/前五组合排除用扩容键集：观察层 + 弱转强预备都不占仓位。
        assert scanner.TREND_NON_POSITION_RULE_KEYS == frozenset(
            {
                LIMIT_UP_PULLBACK_WATCHLIST_RULE_KEY,
                RESEARCH_WEAK_TO_STRONG_NO_LIMIT_RULE_KEY,
            }
        )


class TestTrendTiersAndRanking:
    def _candidate(self, rule_key: str, *, turnover: float):
        from alphaagent.server.services.low_suction.daily_picks_scoring import (
            QuietStreak,
        )

        return scanner.LowSuctionCandidate(
            vt_symbol="600664.SSE",
            trade_date=date(2026, 7, 20),
            setup_type="trend_pullback",
            rule_key=rule_key,
            matched_rule_keys=(rule_key,),
            score=50.0,
            band="40-59",
            streak=QuietStreak(total=0, yin=0, yang=0),
            components=(),
            close_price=5.0,
            daily_return_pct=1.0,
            turnover_rate_pct=turnover,
            candle_range_pct=8.0,
            d1_trade_date=None,
            d1_close_return_pct=None,
        )

    def test_reclaim_takes_p1_5_and_turnover_target_25(self) -> None:
        reclaim = self._candidate(
            LIMIT_UP_WEAK_TO_STRONG_RECLAIM_RULE_KEY, turnover=24.0
        )
        pullback = self._candidate(
            LIMIT_UP_PULLBACK_REBOUND_RULE_KEY, turnover=24.0
        )

        assert _candidate_priority_tier(reclaim) == 20
        assert _candidate_priority_tier(pullback) == 10
        # 趋势 tier20 决胜目标为 25% 换手带心（超跌仍是 3%）。
        assert scanner.candidate_ranking_key(reclaim)[2] == abs(24.0 - 25.0)
        assert scanner.candidate_ranking_key(pullback)[2] == 0.0
