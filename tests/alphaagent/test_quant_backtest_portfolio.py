from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from alphaagent.server.main import create_app
from alphaagent.server.db import schema
from alphaagent.server.services.quant.factors import (
    Bar,
    SignalScore,
    DRAGON_PULLBACK_STRATEGY_ID,
    score_breakout_confirmation,
    score_dragon_pullback,
    score_limit_up_after_pullback,
    score_stock,
    score_trend_acceleration,
)


def _bars(days: int = 80) -> list[Bar]:
    start = date(2025, 1, 1)
    result: list[Bar] = []
    price = 10.0
    for index in range(days):
        if index < 60:
            price *= 1.004
        else:
            price *= 1.0
        result.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=price * 0.99,
                high_price=price * 1.02,
                low_price=price * 0.98,
                close_price=price,
                volume=1_000_000 if index < 60 else 600_000,
                turnover=120_000_000,
                change_pct=0.2,
            )
        )
    return result


def _bars_from_closes_for_strategy_lane(closes: list[float], *, start: date) -> list[Bar]:
    bars: list[Bar] = []
    previous = closes[0]
    for index, close in enumerate(closes):
        change_pct = (close / previous - 1) * 100 if index else 0.0
        bars.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=previous,
                high_price=max(previous, close) * 1.02,
                low_price=min(previous, close) * 0.98,
                close_price=close,
                volume=1_000_000 if index < len(closes) - 1 else 1_100_000,
                turnover=close * 100_000_000,
                change_pct=change_pct,
            )
        )
        previous = close
    return bars


def test_mainline_pullback_score_generates_entry_candidate() -> None:
    bars = _bars()

    score = score_stock(
        "600000.SSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-6.0,
        sector_score=78.0,
        financial_score=66.0,
    )

    assert score.evidence["status"] == "ready"
    assert score.total_score > 0
    assert score.relative_strength_score > 50
    assert score.evidence["selection_rule"] == "daily_close_visible_signal"
    assert score.evidence["entry_setup"] == "ma5_pullback"


def test_quant_strategy_registry_dispatches_default_strategy() -> None:
    from alphaagent.server.services.quant.strategy_registry import (
        get_strategy,
        list_internal_strategies,
        list_strategies,
        score_strategy,
    )

    bars = _bars()
    default_strategy = get_strategy(None)
    strategy = get_strategy("mainline_leader_pullback")
    score = score_strategy("mainline_leader_pullback", "600000.SSE", bars, bars[-1].trade_date)

    assert default_strategy is not None
    assert default_strategy.id == "mainline_dragon_pullback"
    assert strategy is not None
    assert strategy.version == "0.1.1"
    assert default_strategy.version == "0.1.66"
    assert [item["id"] for item in list_strategies()] == ["mainline_dragon_pullback"]
    assert "mainline_leader_pullback" in {item["id"] for item in list_internal_strategies()}
    assert score.signal_type == "mainline_leader_pullback"
    assert score.evidence["entry_setup"] == "ma5_pullback"


def test_dragon_pullback_weekly_bars_use_calendar_weeks_not_window_offset() -> None:
    from alphaagent.server.services.quant.strategies.dragon_pullback import _weekly_bars

    bars = [
        Bar(date(2026, 1, 2), 10.0, 10.5, 9.8, 10.2, 1000, 10000),
        Bar(date(2026, 1, 5), 10.2, 10.8, 10.0, 10.6, 1100, 11000),
        Bar(date(2026, 1, 6), 10.6, 11.2, 10.5, 11.0, 1200, 12000),
        Bar(date(2026, 1, 7), 11.0, 11.4, 10.7, 10.9, 1300, 13000),
        Bar(date(2026, 1, 8), 10.9, 11.1, 10.4, 10.6, 1400, 14000),
        Bar(date(2026, 1, 9), 10.6, 10.9, 10.1, 10.3, 1500, 15000),
        Bar(date(2026, 1, 12), 10.3, 10.7, 10.0, 10.5, 1600, 16000),
    ]

    full_weeks = _weekly_bars(bars)
    trimmed_weeks = _weekly_bars(bars[1:])

    assert [bar.trade_date for bar in full_weeks[1:]] == [bar.trade_date for bar in trimmed_weeks]
    assert [(bar.high_price, bar.low_price, bar.close_price) for bar in full_weeks[1:]] == [
        (bar.high_price, bar.low_price, bar.close_price) for bar in trimmed_weeks
    ]


def test_breakout_confirmation_score_generates_entry_candidate() -> None:
    start = date(2025, 1, 1)
    bars: list[Bar] = []
    price = 10.0
    for index in range(85):
        if index < 65:
            price = 10 + index * 0.03
        elif index < 82:
            price = 12.0 + (index % 4) * 0.05
        else:
            price = 12.8 + (index - 82) * 0.25
        bars.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=price * 0.99,
                high_price=price * 1.01,
                low_price=price * 0.98,
                close_price=price,
                volume=2_000_000 if index >= 82 else 1_000_000,
                turnover=300_000_000,
                change_pct=2.0,
            )
        )

    score = score_breakout_confirmation("002636.SZSE", bars, bars[-1].trade_date)

    assert score.signal_type == "breakout_confirmation"
    assert score.evidence["status"] == "ready"
    assert score.evidence["entry_setup"] == "breakout_confirmation"
    assert score.entry_signal is True
    assert score.total_score >= 70


def test_limit_up_after_pullback_score_generates_entry_candidate() -> None:
    start = date(2025, 1, 1)
    bars: list[Bar] = []
    price = 10.0
    for index in range(85):
        if index < 60:
            change_pct = 0.6
        elif index == 78:
            change_pct = 10.0
        elif index in {79, 80, 81, 82}:
            change_pct = -1.2
        elif index == 83:
            change_pct = 0.4
        else:
            change_pct = 0.3
        price *= 1 + change_pct / 100
        bars.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=price * 0.99,
                high_price=price * 1.02,
                low_price=price * 0.98,
                close_price=price,
                volume=1_500_000,
                turnover=350_000_000,
                change_pct=change_pct,
            )
        )

    score = score_limit_up_after_pullback(
        "002636.SZSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-5.0,
        sector_score=80.0,
        financial_score=70.0,
        fund_flow_score=90.0,
        hot_rank_score=80.0,
        lhb_score=75.0,
    )

    assert score.signal_type == "limit_up_after_pullback"
    assert score.evidence["status"] == "ready"
    assert score.evidence["entry_setup"] == "limit_up_after_pullback"
    assert score.evidence["limit_up_count_20d"] == 1
    assert 2 <= score.evidence["days_since_limit_up"] <= 12
    assert score.entry_signal is True
    assert score.total_score >= 76


def test_trend_acceleration_score_generates_entry_candidate() -> None:
    start = date(2025, 1, 1)
    bars: list[Bar] = []
    price = 10.0
    for index in range(85):
        if index < 25:
            change_pct = 0.1
        elif index < 60:
            change_pct = 0.35
        elif index < 80:
            change_pct = 0.75
        else:
            change_pct = 1.8
        price *= 1 + change_pct / 100
        bars.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=price * 0.99,
                high_price=price * 1.015,
                low_price=price * 0.985,
                close_price=price,
                volume=1_700_000 if index >= 75 else 1_000_000,
                turnover=420_000_000,
                change_pct=change_pct,
            )
        )

    score = score_trend_acceleration(
        "002636.SZSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-2.0,
        sector_score=82.0,
        financial_score=70.0,
        fund_flow_score=85.0,
        hot_rank_score=80.0,
        lhb_score=70.0,
    )

    assert score.signal_type == "trend_acceleration"
    assert score.evidence["status"] == "ready"
    assert score.evidence["entry_setup"] == "trend_acceleration"
    assert score.evidence["return_20d"] >= 12.0
    assert 1.05 <= score.evidence["volume_ratio_5d_20d"] <= 2.80
    assert score.entry_signal is True
    assert score.total_score >= 73


def test_trend_acceleration_rejects_non_positive_change_pct() -> None:
    """门控：进场当日须收涨（change_pct>0），过滤"当日下跌的追高假加速"。

    数据驱动（2026-06-25）：真趋势进场当日 median +1.39，追高假加速 median -0.87。
    其余 trend 条件均满足，唯独进场当日 change_pct=0 → 门控拦截 entry_signal。
    """
    start = date(2025, 1, 1)
    bars: list[Bar] = []
    price = 10.0
    for index in range(85):
        if index < 84:
            change_pct = 0.1 if index < 25 else (0.35 if index < 60 else (0.75 if index < 80 else 1.8))
        else:
            change_pct = 0.0  # 进场当日平收（未涨）
        price *= 1 + change_pct / 100
        bars.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=price * 0.99,
                high_price=price * 1.015,
                low_price=price * 0.985,
                close_price=price,
                volume=1_700_000 if index >= 75 else 1_000_000,
                turnover=420_000_000,
                change_pct=change_pct,
            )
        )

    score = score_trend_acceleration(
        "002636.SZSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-2.0,
        sector_score=82.0,
        financial_score=70.0,
        fund_flow_score=85.0,
        hot_rank_score=80.0,
        lhb_score=70.0,
    )

    # 进场当日未收涨（change_pct=0），门控拦截
    assert score.entry_signal is False
    assert score.evidence["status"] == "ready"
    assert score.evidence["latest_change_pct"] == 0.0


def test_trend_acceleration_does_not_use_future_bars() -> None:
    """无未来函数：信号只用 <= trade_date 的 bar，传入未来 bar 不影响信号。

    visible_bars 已用 bar.trade_date <= trade_date 过滤，即使传入未来 bar（trade_date 之后）
    信号也必须与只用截断序列完全一致。
    """
    start = date(2025, 1, 1)
    bars: list[Bar] = []
    price = 10.0
    for index in range(90):  # 90 天，后 5 天作为"未来"
        change_pct = 0.1 if index < 25 else (0.35 if index < 60 else (0.75 if index < 80 else 1.8))
        price *= 1 + change_pct / 100
        bars.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=price * 0.99,
                high_price=price * 1.015,
                low_price=price * 0.985,
                close_price=price,
                volume=1_700_000 if index >= 75 else 1_000_000,
                turnover=420_000_000,
                change_pct=change_pct,
            )
        )

    signal_date = bars[84].trade_date  # 第 85 天作为信号日
    common = dict(
        index_return_20d=-2.0,
        sector_score=82.0,
        financial_score=70.0,
        fund_flow_score=85.0,
        hot_rank_score=80.0,
        lhb_score=70.0,
    )
    # 传入含未来 bar 的完整序列 vs 只含 <= signal_date 的截断序列，信号必须一致
    score_with_future = score_trend_acceleration("002636.SZSE", bars, signal_date, **common)
    score_no_future = score_trend_acceleration("002636.SZSE", bars[:85], signal_date, **common)

    assert score_with_future.entry_signal == score_no_future.entry_signal
    assert score_with_future.total_score == score_no_future.total_score
    assert score_with_future.evidence["return_5d"] == score_no_future.evidence["return_5d"]
    assert score_with_future.evidence["latest_change_pct"] == score_no_future.evidence["latest_change_pct"]


def test_dragon_pullback_score_accepts_ma10_support_reclaim() -> None:
    start = date(2026, 1, 1)
    closes = [20 + index * 0.12 for index in range(74)]
    closes.extend([27.5, 29.8, 32.0, 34.2, 36.4, 34.0, 32.8, 32.5, 33.0, 34.2])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 0.99,
            high_price=close * 1.025,
            low_price=close * 0.975,
            close_price=close,
            volume=1_800_000 if index < 74 else 1_050_000,
            turnover=520_000_000,
            change_pct=2.0 if index < 74 else 1.8,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback(
        "002428.SZSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-2.0,
        sector_score=82.0,
        financial_score=65.0,
        fund_flow_score=70.0,
        hot_rank_score=70.0,
        lhb_score=65.0,
    )

    assert score.signal_type == DRAGON_PULLBACK_STRATEGY_ID
    assert score.evidence["status"] == "ready"
    assert score.evidence["entry_setup"] == "dragon_pullback"
    assert score.evidence["dragon_state"] == "TAIL_BUY_READY"
    assert score.evidence["support_type"] in {"ma5_reclaim", "ma10_support"}
    assert score.entry_signal is True
    assert score.total_score >= 72


def test_dragon_pullback_score_rejects_stale_bars_on_signal_date() -> None:
    bars = _bars(90)
    signal_date = bars[-1].trade_date + timedelta(days=1)

    score = score_dragon_pullback("600000.SSE", bars, signal_date)

    assert score.entry_signal is False
    assert score.evidence == {
        "status": "missing_trade_date_bar",
        "trade_date": signal_date.isoformat(),
        "latest_bar_date": bars[-1].trade_date.isoformat(),
    }


def test_dragon_pullback_repeated_tail_buy_ready_builds_low_suction_score() -> None:
    start = date(2026, 1, 1)
    closes = [20 + index * 0.12 for index in range(74)]
    closes.extend([25.0, 27.0, 29.0, 31.0, 33.0, 31.5, 30.8, 30.6, 30.9, 31.3, 31.2])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 0.99,
            high_price=close * 1.025,
            low_price=close * 0.975,
            close_price=close,
            volume=1_800_000 if index < 74 else 1_050_000,
            turnover=520_000_000,
            change_pct=2.0 if index < 74 else 1.8,
        )
        for index, close in enumerate(closes)
    ]

    first_ready = score_dragon_pullback(
        "002428.SZSE",
        bars[:-2],
        bars[-3].trade_date,
        index_return_20d=-2.0,
        sector_score=82.0,
        financial_score=65.0,
        fund_flow_score=70.0,
        hot_rank_score=70.0,
        lhb_score=65.0,
    )
    repeated_ready = score_dragon_pullback(
        "002428.SZSE",
        bars[:-1],
        bars[-2].trade_date,
        index_return_20d=-2.0,
        sector_score=82.0,
        financial_score=65.0,
        fund_flow_score=70.0,
        hot_rank_score=70.0,
        lhb_score=65.0,
    )

    assert first_ready.evidence["dragon_state"] == "TAIL_BUY_READY"
    assert first_ready.evidence["fresh_tail_buy"] is True
    assert first_ready.entry_signal is True
    assert repeated_ready.evidence["dragon_state"] == "LOW_SUCTION_BUILDUP"
    assert "repeat_tail_buy_setup" not in repeated_ready.evidence["failed_rules"]
    assert repeated_ready.evidence["low_suction_days"] > first_ready.evidence["low_suction_days"]
    assert repeated_ready.evidence["low_suction_buildup_score"] >= 35
    assert repeated_ready.evidence["score_notes"]
    assert repeated_ready.entry_signal is False


def test_recommendation_sort_keeps_buy_first_then_low_suction_watch() -> None:
    from alphaagent.server.services.quant import screening

    trade_date = date(2026, 6, 12)
    normal_watch = SignalScore(
        vt_symbol="600001.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=97.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "dragon_state": "SUPPORT_ACCEPTED",
            "low_suction_days": 0,
            "ma_convergence_pct": 30.0,
            "low_suction_buildup_score": 60.0,
        },
    )
    low_suction_watch = SignalScore(
        vt_symbol="600002.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=74.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "dragon_state": "LOW_SUCTION_BUILDUP",
            "low_suction_days": 4,
            "ma_convergence_pct": 3.5,
            "low_suction_buildup_score": 100.0,
        },
    )
    buy = SignalScore(
        vt_symbol="600003.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=80.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "dragon_state": "TAIL_BUY_READY",
            "low_suction_days": 0,
            "ma_convergence_pct": 20.0,
            "low_suction_buildup_score": 60.0,
        },
    )

    sorted_items = sorted([normal_watch, low_suction_watch, buy], key=lambda item: screening._recommendation_sort_key(item, 76.0))

    assert [item.vt_symbol for item in sorted_items] == ["600003.SSE", "600002.SSE", "600001.SSE"]


def test_recommendation_sort_keeps_buy_score_before_low_suction_shape() -> None:
    from alphaagent.server.services.quant import screening

    trade_date = date(2026, 6, 12)
    low_suction_buy = SignalScore(
        vt_symbol="600010.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=80.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "dragon_state": "LOW_SUCTION_BUILDUP",
            "low_suction_days": 6,
            "ma_convergence_pct": 2.0,
            "low_suction_buildup_score": 100.0,
        },
    )
    tail_buy = SignalScore(
        vt_symbol="600011.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "dragon_state": "TAIL_BUY_READY",
            "low_suction_days": 0,
            "ma_convergence_pct": 12.0,
            "low_suction_buildup_score": 70.0,
        },
    )

    sorted_items = sorted([low_suction_buy, tail_buy], key=lambda item: screening._recommendation_sort_key(item, 76.0))

    assert [item.vt_symbol for item in sorted_items] == ["600011.SSE", "600010.SSE"]


def test_recommendation_action_requires_executable_entry_score() -> None:
    from alphaagent.server.services.quant import screening_payloads

    weak_buy = SignalScore(
        vt_symbol="600004.SSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=73.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "dragon_state": "LOW_SUCTION_BUILDUP",
            "failed_rules": [],
            "close_price": 10.0,
        },
    )

    row = screening_payloads.recommendation_to_db(
        1,
        weak_buy,
        None,
        DRAGON_PULLBACK_STRATEGY_ID,
        "0.1.8",
        min_entry_score=76.0,
    )

    assert row["action"] == "WATCH"
    assert row["reason"]["failed_rules"] == ["total_score"]


def test_recommendation_action_allows_unconfirmed_low_suction_by_default() -> None:
    from alphaagent.server.services.quant import screening_payloads

    low_suction_buildup = SignalScore(
        vt_symbol="002384.SZSE",
        trade_date=date(2026, 6, 11),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=88.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "setup_type": "stealth_low_suction",
            "entry_setup": "stealth_low_suction",
            "dragon_state": "LOW_SUCTION_BUILDUP",
            "failed_rules": ["reclaim_confirmation"],
            "low_suction_days": 4,
            "low_suction_buildup_score": 100.0,
            "stealth_low_suction_score": 98.0,
            "ma_convergence_pct": 1.95,
            "ma20_distance_pct": -2.69,
            "volume_ratio_5d_20d": 0.86,
            "low_suction_launch_confirmed": False,
            "close_price": 10.0,
        },
    )
    low_suction_launch = SignalScore(
        vt_symbol="002384.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=88.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            **low_suction_buildup.evidence,
            "low_suction_launch_confirmed": True,
            "close_location_in_range": 0.72,
        },
    )

    buildup_row = screening_payloads.recommendation_to_db(
        1,
        low_suction_buildup,
        None,
        DRAGON_PULLBACK_STRATEGY_ID,
        "0.1.23",
        min_entry_score=76.0,
    )
    launch_row = screening_payloads.recommendation_to_db(
        2,
        low_suction_launch,
        None,
        DRAGON_PULLBACK_STRATEGY_ID,
        "0.1.23",
        min_entry_score=76.0,
    )

    assert buildup_row["action"] == "BUY"
    assert buildup_row["reason"]["failed_rules"] == []
    assert buildup_row["reason"]["signal_label"] == "低吸蓄势买点"
    assert launch_row["action"] == "BUY"
    assert launch_row["reason"]["failed_rules"] == []
    assert launch_row["reason"]["signal_label"] == "低吸启动买点"


def test_recommendation_action_can_require_low_suction_launch_confirmation() -> None:
    from alphaagent.server.services.quant import screening_payloads

    low_suction_buildup = SignalScore(
        vt_symbol="002384.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=95.81,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "setup_type": "stealth_low_suction",
            "entry_setup": "stealth_low_suction",
            "dragon_state": "TAIL_BUY_READY",
            "failed_rules": [],
            "low_suction_days": 4,
            "low_suction_buildup_score": 100.0,
            "stealth_low_suction_score": 100.0,
            "ma_convergence_pct": 1.75,
            "ma20_distance_pct": 0.0,
            "volume_ratio_5d_20d": 0.83,
            "low_suction_launch_confirmed": False,
            "close_price": 217.55,
        },
    )

    failed_rules = screening_payloads.failed_entry_rules(
        low_suction_buildup,
        76.0,
        include_low_suction_launch_gate=True,
    )

    assert failed_rules == ["low_suction_launch_unconfirmed"]


def test_symbol_signal_row_marks_support_divergence_as_research_only() -> None:
    from alphaagent.server.services.quant import screening_payloads

    support_divergence = SignalScore(
        vt_symbol="003004.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.27,
        liquidity_score=80.0,
        risk_score=62.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "failed_rules": ["reclaim_confirmation"],
            "support_divergence_entry_profile": "high_level_support_divergence",
            "support_divergence_entry_observation_only": True,
            "default_executable_entry_signal": False,
            "raw_entry_signal": False,
            "signal_label": "支撑分歧低吸买点",
            "close_price": 32.1,
        },
    )

    row = screening_payloads.symbol_signal_row(support_divergence, min_entry_score=76.0)

    assert row["action"] == "WATCH"
    assert row["executable_entry_signal"] is False
    assert row["research_entry_signal"] is True
    assert row["signal_label"] == "支撑分歧低吸买点"
    assert row["signal_role"] == "research_buy"


def test_symbol_signal_row_marks_strong_trend_ma_pullback_as_research_only() -> None:
    from alphaagent.server.services.quant import screening_payloads

    ma_pullback = SignalScore(
        vt_symbol="003004.SZSE",
        trade_date=date(2026, 5, 25),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=78.49,
        liquidity_score=80.0,
        risk_score=62.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "failed_rules": ["pullback_too_short"],
            "strong_trend_ma_pullback_entry_profile": "strong_trend_intraday_ma_pullback",
            "strong_trend_ma_pullback_entry_observation_only": True,
            "default_executable_entry_signal": False,
            "raw_entry_signal": False,
            "signal_label": "强趋势均线回踩研究买点",
        },
    )

    row = screening_payloads.symbol_signal_row(ma_pullback, min_entry_score=76.0)

    assert row["action"] == "WATCH"
    assert row["executable_entry_signal"] is False
    assert row["research_entry_signal"] is True
    assert row["signal_label"] == "强趋势均线回踩研究买点"
    assert row["signal_role"] == "research_buy"


def test_symbol_signal_row_marks_default_clean_watch_entry_as_buy() -> None:
    from alphaagent.server.services.quant import screening_payloads

    clean_entry = SignalScore(
        vt_symbol="003004.SZSE",
        trade_date=date(2026, 4, 30),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=64.6,
        liquidity_score=15.0,
        risk_score=62.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "failed_rules": ["liquidity_score", "strong_leg"],
            "default_clean_watch_entry_profile": "clean_low_liquidity_accumulation",
            "default_executable_entry_signal": True,
            "raw_entry_signal": False,
            "signal_label": "低流动性承接低吸买点",
            "close_price": 19.2,
        },
    )

    row = screening_payloads.symbol_signal_row(clean_entry, min_entry_score=76.0)

    assert row["action"] == "BUY"
    assert row["executable_entry_signal"] is True
    assert row["research_entry_signal"] is False
    assert row["key_entry_signal"] is True
    assert row["entry_threshold_reason"] == "default_clean_watch_entry"
    assert row["signal_label"] == "低流动性承接低吸买点"


def test_screening_recommendation_buy_action_uses_normalized_entry_payload() -> None:
    from alphaagent.server.services.quant import screening

    clean_entry = SignalScore(
        vt_symbol="003004.SZSE",
        trade_date=date(2026, 4, 30),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=64.6,
        liquidity_score=15.0,
        risk_score=62.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "default_clean_watch_entry_profile": "clean_low_liquidity_accumulation",
            "default_executable_entry_signal": True,
            "raw_entry_signal": False,
            "signal_label": "低流动性承接低吸买点",
        },
    )

    assert screening._recommendation_buy_action(clean_entry, min_entry_score=76.0) is True


def test_screening_default_entry_fields_promote_clean_watch_before_recommendation_selection() -> None:
    from alphaagent.server.services.quant import screening

    clean_entry = SignalScore(
        vt_symbol="003004.SZSE",
        trade_date=date(2026, 4, 30),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=62.4,
        liquidity_score=15.0,
        risk_score=62.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "entry_setup": "support_accepted",
            "setup_type": "support_accepted",
            "dragon_state": "SUPPORT_ACCEPTED",
            "failed_rules": ["liquidity_score", "strong_leg", "pullback_too_short"],
            "low_suction_days": 3,
            "ma5_distance_pct": 0.4,
            "ma10_distance_pct": 1.0,
            "ma_convergence_pct": 4.0,
            "close_location_in_range": 0.54,
            "volume_ratio_5d_20d": 0.88,
            "return_60d": 18.0,
        },
    )

    adjusted = screening._with_default_screening_entry_fields(
        clean_entry,
        DRAGON_PULLBACK_STRATEGY_ID,
        min_entry_score=76.0,
    )

    assert adjusted.evidence["default_clean_watch_entry_profile"] == "clean_low_liquidity_accumulation"
    assert adjusted.evidence["default_executable_entry_signal"] is True
    assert adjusted.evidence["candidate_quality_adjustment"] > 0
    assert screening._recommendation_buy_action(adjusted, min_entry_score=76.0) is True


def test_recommendation_reason_preserves_readable_low_suction_stage_and_market_summary() -> None:
    from alphaagent.server.services.quant import screening_payloads

    low_suction_launch = SignalScore(
        vt_symbol="002384.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=88.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "setup_type": "stealth_low_suction",
            "entry_setup": "stealth_low_suction",
            "dragon_state": "LOW_SUCTION_BUILDUP",
            "failed_rules": [],
            "low_suction_days": 5,
            "low_suction_launch_confirmed": True,
            "low_suction_stage": "balanced_first_lift",
            "low_suction_stage_label": "低吸首个均衡上拉",
            "low_suction_launch_quality_bucket": "balanced_first_lift",
            "low_suction_launch_quality_label": "低吸首个均衡上拉",
            "market_context_summary": {
                "state": "risk_off",
                "label": "大盘向下/资金防守",
                "severity": "warning",
                "notes": ["强风险", "连续流出"],
            },
            "dynamic_market_regime": "weak_defensive",
            "dynamic_market_label": "弱势防守",
            "market_warning_level": 3,
            "market_warning_label": "强风险",
            "fund_flow_state": "continuous_outflow",
            "fund_flow_label": "连续流出",
            "fund_flow_score": 35.0,
            "fund_flow_streak_days": 4,
            "fund_flow_source": "sector_fund_flows",
            "close_price": 10.0,
        },
    )

    row = screening_payloads.recommendation_to_db(
        1,
        low_suction_launch,
        None,
        DRAGON_PULLBACK_STRATEGY_ID,
        "0.1.23",
        min_entry_score=76.0,
    )

    assert row["action"] == "BUY"
    assert row["reason"]["low_suction_stage_label"] == "低吸首个均衡上拉"
    assert row["reason"]["low_suction_launch_quality_label"] == "低吸首个均衡上拉"
    assert row["reason"]["market_context_summary"]["label"] == "大盘向下/资金防守"
    assert row["reason"]["market_context_summary"]["fund_flow_marker"]["level"] == 3
    assert row["reason"]["market_context_summary"]["fund_flow_marker"]["note"] == "连续流出 4 天"


def test_recommendation_reason_normalizes_low_suction_launch_quality_for_old_evidence() -> None:
    from alphaagent.server.services.quant import screening_payloads

    low_suction_launch = SignalScore(
        vt_symbol="002384.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=88.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "setup_type": "stealth_low_suction",
            "entry_setup": "stealth_low_suction",
            "dragon_state": "LOW_SUCTION_BUILDUP",
            "failed_rules": [],
            "low_suction_days": 5,
            "low_suction_launch_confirmed": True,
            "close_location_in_range": 0.66,
            "volume_ratio_5d_20d": 1.05,
            "tail_buy_repeat_days": 0,
            "pullback_days": 5,
            "close_price": 10.0,
        },
    )

    row = screening_payloads.recommendation_to_db(
        1,
        low_suction_launch,
        None,
        DRAGON_PULLBACK_STRATEGY_ID,
        "0.1.23",
        min_entry_score=76.0,
    )

    assert row["reason"]["low_suction_stage_label"] == "低吸首个均衡上拉"
    assert row["reason"]["low_suction_launch_quality_bucket"] == "balanced_first_lift"
    assert row["reason"]["low_suction_launch_quality_label"] == "低吸首个均衡上拉"
    assert row["reason"]["low_suction_dragon_state"] == "low_suction_confirmed_launch"
    assert row["reason"]["low_suction_dragon_label"] == "低吸上拉确认"
    assert row["reason"]["low_suction_dragon_conflict"] is False


def test_market_context_summary_prefers_market_flow_over_stock_flow_for_old_evidence() -> None:
    from alphaagent.server.services.quant import screening_payloads

    evidence = screening_payloads.normalize_quant_evidence(
        {
            "fund_flow_score": 90.0,
            "market_context": {
                "regime": "weak_defensive",
                "label": "弱势防守",
                "market_warning_level": 3,
                "market_warning_label": "强风险",
                "fund_flow_state": "continuous_outflow",
                "fund_flow_label": "连续流出",
                "fund_flow_score": 35.0,
                "fund_flow_streak_days": 4,
                "fund_flow_source": "sector_fund_flows",
                "recovery_state": "none",
                "recovery_label": "未回暖",
            },
        }
    )

    marker = evidence["market_context_summary"]["fund_flow_marker"]
    assert marker["score"] == 35.0
    assert marker["level"] == 3


def test_recommendation_reason_marks_early_dragon_without_low_suction_context() -> None:
    from alphaagent.server.services.quant import screening_payloads

    early_dragon = SignalScore(
        vt_symbol="601179.SSE",
        trade_date=date(2026, 2, 3),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=96.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "setup_type": "dragon_pullback",
            "entry_setup": "dragon_pullback",
            "failed_rules": [],
            "low_suction_days": 0,
            "low_suction_launch_confirmed": False,
            "early_dragon_pullback_risk": True,
            "ma_convergence_pct": 19.0,
            "latest_change_pct": 2.0,
            "close_location_in_range": 0.7,
            "close_price": 10.0,
        },
    )

    row = screening_payloads.recommendation_to_db(
        1,
        early_dragon,
        None,
        DRAGON_PULLBACK_STRATEGY_ID,
        "0.1.23",
        min_entry_score=76.0,
    )

    assert row["action"] == "BUY"
    assert row["reason"]["low_suction_dragon_state"] == "early_dragon_without_buildup"
    assert row["reason"]["low_suction_dragon_label"] == "龙回头偏早缺低吸蓄势"
    assert row["reason"]["low_suction_dragon_conflict"] is True
    assert row["reason"]["low_suction_dragon_conflict_level"] == "warning"


def test_recommendation_reason_normalizes_low_position_reclaim_context_for_old_evidence() -> None:
    from alphaagent.server.services.quant import screening_payloads

    evidence = screening_payloads.normalize_quant_evidence(
        {
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "low_suction_days": 5,
            "low_suction_launch_confirmed": True,
            "return_20d": 3.0,
            "return_60d": 9.0,
            "max_drawdown_60d": -9.0,
            "ma_convergence_pct": 3.8,
            "ma5_distance_pct": 1.2,
            "ma10_distance_pct": 1.8,
            "ma20_distance_pct": 2.0,
            "ma20_vs_ma30_pct": 0.8,
            "volume_ratio_5d_20d": 1.05,
            "close_location_in_range": 0.68,
            "latest_change_pct": 3.2,
            "high_level_sideways_distribution_risk": False,
            "volume_stall_risk": False,
            "key_support_break_risk": False,
        }
    )

    assert evidence["entry_family"] == "low_position_reclaim"
    assert evidence["entry_family_label"] == "低位承接转强"
    assert evidence["low_position_reclaim_type"] == "platform_accumulation_launch"
    assert evidence["low_position_reclaim_label"] == "平台低吸首启"
    assert evidence["is_readonly_setup_diagnostic"] is True
    assert "低位均线收敛" in evidence["entry_family_notes"]


def test_recommendation_reason_keeps_dragon_family_separate_from_low_position_context() -> None:
    from alphaagent.server.services.quant import screening_payloads

    evidence = screening_payloads.normalize_quant_evidence(
        {
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_type": "dragon_pullback",
            "dragon_state": "TAIL_BUY_READY",
            "return_20d": 28.0,
            "return_60d": 42.0,
            "near_limit_up_count_20d": 1,
            "low_suction_days": 0,
            "ma_convergence_pct": 12.0,
            "ma5_distance_pct": 0.8,
            "ma10_distance_pct": 1.6,
            "ma20_distance_pct": 4.0,
            "volume_ratio_5d_20d": 0.9,
            "close_location_in_range": 0.65,
            "latest_change_pct": 2.4,
        }
    )

    assert evidence["entry_family"] == "dragon_pullback"
    assert evidence["entry_family_label"] == "龙回头回踩"
    assert evidence["low_position_reclaim_type"] == "none"
    assert evidence["entry_family_conflict"] is False


def test_recommendation_reason_rejects_high_level_sideways_as_low_position_reclaim() -> None:
    from alphaagent.server.services.quant import screening_payloads

    evidence = screening_payloads.normalize_quant_evidence(
        {
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "low_suction_days": 6,
            "low_suction_launch_confirmed": True,
            "return_20d": 4.0,
            "return_60d": 55.0,
            "max_drawdown_60d": -8.0,
            "ma_convergence_pct": 4.0,
            "ma5_distance_pct": 1.0,
            "ma10_distance_pct": 1.3,
            "ma20_distance_pct": 2.0,
            "volume_ratio_5d_20d": 1.1,
            "close_location_in_range": 0.66,
            "latest_change_pct": 3.0,
            "high_level_sideways_distribution_risk": True,
        }
    )

    assert evidence["entry_family"] != "low_position_reclaim"
    assert evidence["low_position_reclaim_type"] == "none"
    assert evidence["entry_family_label"] != "低位承接转强"


def test_factor_candidate_feature_row_extracts_readonly_setup_context() -> None:
    from alphaagent.server.services.backtest.factor_audit import candidate_feature_row

    row = candidate_feature_row(
        {
            "trade_date": date(2026, 5, 11),
            "vt_symbol": "603439.SSE",
            "rank": 4,
            "action": "BUY",
            "total_score": 88.25,
            "reason": {
                "status": "ready",
                "entry_setup": "stealth_low_suction",
                "setup_type": "stealth_low_suction",
                "raw_entry_signal": True,
                "executable_entry_signal": True,
                "action": "BUY",
                "low_suction_days": 5,
                "low_suction_launch_confirmed": True,
                "return_20d": 3.0,
                "return_60d": 9.0,
                "ma_convergence_pct": 4.2,
                "ma5_distance_pct": 0.7,
                "ma10_distance_pct": 1.2,
                "ma20_distance_pct": 1.8,
                "ma30_distance_pct": 2.1,
                "support_price": 27.5,
                "ma10": 27.8,
                "ma20": 27.2,
                "volume_ratio_5d_20d": 1.05,
                "turnover_percentile_60d": 0.62,
                "close_location_in_range": 0.68,
                "latest_change_pct": 3.0,
                "dynamic_market_regime": "false_bull",
                "market_warning_level": "warning",
                "fund_flow_state": "outflow",
                "fund_flow_source": "stock_fund_flows_partial",
            },
        },
        stock={"name": "三力制药", "exchange": "SSE", "industry": "医药"},
    )

    assert row["setup_primary"] == "low_position_reclaim"
    assert row["entry_family_label"] == "低位承接转强"
    assert row["low_position_reclaim_type"] == "platform_accumulation_launch"
    assert row["low_position_reclaim_label"] == "平台低吸首启"
    assert row["rank_bucket"] == "top_10"
    assert row["ma_convergence_pct"] == 4.2
    assert row["dynamic_market_regime"] == "false_bull"
    assert row["reason"]["entry_setup"] == "stealth_low_suction"
    assert row["reason"]["support_price"] == 27.5
    assert row["reason"]["ma10"] == 27.8
    assert row["reason"]["ma20"] == 27.2
    assert row["name"] == "三力制药"
    assert row["industry"] == "医药"
    assert row["as_of_date"] == "2026-05-11"
    assert row["feature_window_end"] == "2026-05-11"
    assert row["uses_future_for_label_only"] is False
    assert row["not_used_for_signal_score"] is True


def test_factor_candidate_feature_row_marks_persisted_action_mismatch() -> None:
    from alphaagent.server.services.backtest.factor_audit import candidate_feature_row

    row = candidate_feature_row(
        {
            "trade_date": date(2026, 3, 13),
            "vt_symbol": "002240.SZSE",
            "rank": 4,
            "action": "BUY",
            "reason": {
                "status": "ready",
                "action": "WATCH",
                "raw_entry_signal": True,
                "executable_entry_signal": False,
                "entry_setup": "stealth_low_suction",
                "low_suction_days": 3,
            },
        }
    )

    assert row["persisted_action"] == "BUY"
    assert row["entry_action"] == "WATCH"
    assert row["action_mismatch_resolved"] is True
    assert row["not_used_for_signal_score"] is True


def test_factor_candidate_feature_rows_adds_stock_metadata_by_symbol() -> None:
    from alphaagent.server.services.backtest.factor_audit import candidate_feature_rows

    rows = candidate_feature_rows(
        [
            {
                "trade_date": date(2026, 5, 11),
                "vt_symbol": "603439.SSE",
                "rank": 21,
                "action": "WATCH",
                "reason": {
                    "status": "ready",
                    "entry_setup": "dragon_pullback",
                    "setup_type": "dragon_pullback",
                    "dragon_state": "TAIL_BUY_READY",
                    "return_20d": 28.0,
                    "return_60d": 42.0,
                },
            }
        ],
        {"603439.SSE": {"name": "三力制药", "exchange": "SSE"}},
    )

    assert rows[0]["setup_primary"] == "dragon_pullback"
    assert rows[0]["rank_bucket"] == "top_100"
    assert rows[0]["name"] == "三力制药"


def test_backtest_factor_candidates_api_passes_filters(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_factor_candidates(backtest_id: int, vt_symbol: str | None = None, limit: int = 500):
        captured.update({"backtest_id": backtest_id, "vt_symbol": vt_symbol, "limit": limit})
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "items": [{"vt_symbol": vt_symbol, "setup_primary": "low_position_reclaim"}],
        }

    monkeypatch.setattr(backtests, "backtest_factor_candidates", fake_factor_candidates)
    client = TestClient(create_app())

    response = client.get("/api/backtests/203/factor-candidates?vt_symbol=603439.SSE&limit=200")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["backtest_id"] == 203
    assert payload["items"][0]["setup_primary"] == "low_position_reclaim"
    assert captured == {"backtest_id": 203, "vt_symbol": "603439.SSE", "limit": 200}


def test_fixed_horizon_outcome_uses_next_open_and_marks_audit_only() -> None:
    from alphaagent.server.services.backtest.factor_audit import fixed_horizon_outcome_row

    bars = [
        Bar(date(2026, 5, 8), 10.0, 10.5, 9.8, 10.2, 1_000_000, 100_000_000, 1.0),
        Bar(date(2026, 5, 11), 10.0, 10.8, 9.7, 10.5, 1_000_000, 100_000_000, 3.0),
        Bar(date(2026, 5, 12), 10.6, 11.2, 10.4, 11.0, 1_000_000, 100_000_000, 4.8),
        Bar(date(2026, 5, 13), 11.1, 11.5, 10.9, 11.4, 1_000_000, 100_000_000, 3.6),
        Bar(date(2026, 5, 14), 11.4, 12.0, 11.2, 11.8, 1_000_000, 100_000_000, 3.5),
        Bar(date(2026, 5, 15), 11.8, 12.3, 11.6, 12.1, 1_000_000, 100_000_000, 2.5),
        Bar(date(2026, 5, 18), 12.0, 12.6, 11.7, 12.5, 1_000_000, 100_000_000, 3.3),
    ]

    row = fixed_horizon_outcome_row(signal_date=date(2026, 5, 8), bars=bars, horizons=(3, 5))

    assert row["status"] == "ready"
    assert row["execute_date"] == date(2026, 5, 11)
    assert row["execute_open_price"] == 10.0
    assert row["return_3d"] == 18.0
    assert row["return_5d"] == 25.0
    assert row["mfe_5d"] == 26.0
    assert row["mae_5d"] == -3.0
    assert row["hit_profit_5_pct"] is True
    assert row["hit_profit_8_pct"] is True
    assert row["hit_loss_3_pct"] is True
    assert row["first_hit"] == "loss"
    assert row["uses_future_for_label_only"] is True
    assert row["not_used_for_signal_score"] is True


def test_fixed_horizon_outcome_reports_missing_execute_bar() -> None:
    from alphaagent.server.services.backtest.factor_audit import fixed_horizon_outcome_row

    bars = [Bar(date(2026, 5, 8), 10.0, 10.5, 9.8, 10.2, 1_000_000, 100_000_000, 1.0)]

    row = fixed_horizon_outcome_row(signal_date=date(2026, 5, 8), bars=bars, horizons=(3,))

    assert row["status"] == "no_execute_bar"
    assert row["execute_date"] is None
    assert row["uses_future_for_label_only"] is True
    assert row["not_used_for_signal_score"] is True


def test_current_strategy_trade_outcome_map_pairs_trades_by_signal_date() -> None:
    from alphaagent.server.services.backtest.factor_audit import current_strategy_trade_outcome_map

    trades = [
        {
            "id": 1,
            "trade_date": date(2026, 5, 12),
            "vt_symbol": "603439.SSE",
            "side": "BUY",
            "price": 10.0,
            "reason": "entry_signal",
            "raw": {"execution": {"signal_date": "2026-05-11"}},
        },
        {
            "id": 2,
            "trade_date": date(2026, 5, 20),
            "vt_symbol": "603439.SSE",
            "side": "SELL",
            "price": 11.2,
            "reason": "trend_trailing_stop",
            "raw": {"signal_date": "2026-05-19"},
        },
    ]

    result = current_strategy_trade_outcome_map(trades)

    outcome = result[("603439.SSE", date(2026, 5, 11))]
    assert outcome["current_strategy_entry_date"] == date(2026, 5, 12)
    assert outcome["current_strategy_exit_date"] == date(2026, 5, 20)
    assert outcome["current_strategy_return_pct"] == 12.0
    assert outcome["current_strategy_exit_reason"] == "trend_trailing_stop"


def test_current_strategy_trade_outcome_map_falls_back_to_prior_candidate_date() -> None:
    from alphaagent.server.services.backtest.factor_audit import current_strategy_trade_outcome_map

    trades = [
        {
            "id": 1,
            "trade_date": date(2026, 5, 12),
            "vt_symbol": "603439.SSE",
            "side": "BUY",
            "price": 10.0,
            "reason": "entry_signal",
            "raw": {},
        },
        {
            "id": 2,
            "trade_date": date(2026, 5, 18),
            "vt_symbol": "603439.SSE",
            "side": "SELL",
            "price": 9.5,
            "reason": "support_stop",
            "raw": {},
        },
    ]

    result = current_strategy_trade_outcome_map(
        trades,
        candidate_signal_dates_by_symbol={"603439.SSE": [date(2026, 5, 8), date(2026, 5, 11)]},
    )

    outcome = result[("603439.SSE", date(2026, 5, 11))]
    assert outcome["current_strategy_entry_date"] == date(2026, 5, 12)
    assert outcome["current_strategy_exit_reason"] == "support_stop"
    assert outcome["current_strategy_return_pct"] == -5.0


def test_factor_audit_bucket_helpers_classify_core_ranges() -> None:
    from alphaagent.server.services.backtest import factor_audit

    assert factor_audit.rank_bucket(1) == "top_10"
    assert factor_audit.rank_bucket(17) == "top_20"
    assert factor_audit.rank_bucket(75) == "top_100"
    assert factor_audit.rank_bucket(101) == "outside_top_100"
    assert factor_audit.ma_convergence_bucket(4.2) == "3-6"
    assert factor_audit.low_suction_days_bucket(4) == "3-5"
    assert factor_audit.volume_bucket(0.7) == "shrinking"
    assert factor_audit.volume_bucket(1.3) == "normal"
    assert factor_audit.volume_bucket(2.2) == "double_volume"
    assert factor_audit.close_location_bucket(0.68) == "middle"
    assert factor_audit.market_regime_bucket("false_bull") == "false_bull"
    assert factor_audit.fund_flow_bucket("panic_outflow") == "panic_outflow"


def test_factor_audit_summary_groups_candidate_outcomes() -> None:
    from alphaagent.server.services.backtest.factor_audit import factor_audit_summary

    rows = [
        {
            "setup_primary": "low_position_reclaim",
            "rank_bucket": "top_10",
            "ma_convergence_pct": 4.2,
            "low_suction_days": 4,
            "volume_ratio_5d_20d": 1.2,
            "close_location_in_range": 0.66,
            "dynamic_market_regime": "false_bull",
            "fund_flow_state": "outflow",
            "outcome": {
                "return_20d": 8.0,
                "mfe_20d": 12.0,
                "mae_20d": -2.0,
                "failed_launch": False,
                "support_stop_like": False,
            },
        },
        {
            "setup_primary": "low_position_reclaim",
            "rank_bucket": "top_10",
            "ma_convergence_pct": 8.0,
            "low_suction_days": 8,
            "volume_ratio_5d_20d": 0.6,
            "close_location_in_range": 0.35,
            "dynamic_market_regime": "false_bull",
            "fund_flow_state": "outflow",
            "outcome": {
                "return_20d": -4.0,
                "mfe_20d": 3.0,
                "mae_20d": -6.0,
                "failed_launch": True,
                "support_stop_like": True,
            },
        },
    ]

    summary = factor_audit_summary(rows)

    assert summary["summary"]["sample_count"] == 2
    assert summary["by_setup"][0]["bucket"] == "low_position_reclaim"
    assert summary["by_setup"][0]["sample_count"] == 2
    assert summary["by_setup"][0]["win_rate"] == 50.0
    assert summary["by_setup"][0]["average_return"] == 2.0
    assert summary["by_rank_bucket"][0]["bucket"] == "top_10"
    assert summary["by_market_regime"][0]["bucket"] == "false_bull"
    assert summary["by_factor_bucket"]["ma_convergence"][0]["sample_count"] == 1
    assert "launch_quality" in summary["by_factor_bucket"]
    assert "by_low_position_reclaim_type" in summary


def test_factor_audit_summary_can_exclude_strong_market_rows() -> None:
    from alphaagent.server.services.backtest.factor_audit import factor_audit_summary

    rows = [
        {"dynamic_market_regime": "strong_broad", "rank_bucket": "top_10", "outcome": {"return_20d": 10.0}},
        {"dynamic_market_regime": "false_bull", "rank_bucket": "top_10", "outcome": {"return_20d": -2.0}},
    ]

    summary = factor_audit_summary(rows, exclude_strong_market=True)

    assert summary["coverage"]["candidate_count"] == 1
    assert summary["coverage"]["excluded_strong_market_count"] == 1
    assert summary["summary"]["average_return"] == -2.0


def test_factor_audit_summary_outputs_interaction_opportunity_cost() -> None:
    from alphaagent.server.services.backtest.factor_audit import factor_audit_summary

    rows = [
        {
            "entry_family": "low_position_reclaim",
            "rank": 3,
            "rank_bucket": "top_10",
            "dynamic_market_regime": "false_bull",
            "low_suction_days": 4,
            "first_effective_lift": True,
            "low_suction_launch_quality_bucket": "balanced_first_lift",
            "risk_penalty": 2.0,
            "market_warning_level": 3,
            "low_position_reclaim_type": "ma10_reclaim",
            "ma10_distance_pct": 0.8,
            "outcome": {
                "return_20d": 12.0,
                "mfe_20d": 18.0,
                "mae_20d": -2.0,
                "failed_launch": False,
                "support_stop_like": False,
            },
        },
        {
            "entry_family": "dragon_pullback",
            "rank": 12,
            "rank_bucket": "top_20",
            "dynamic_market_regime": "strong_broad",
            "low_suction_days": 0,
            "first_effective_lift": False,
            "risk_penalty": 9.0,
            "market_warning_level": 0,
            "low_position_reclaim_type": "none",
            "outcome": {
                "return_20d": -5.0,
                "mfe_20d": 2.0,
                "mae_20d": -7.0,
                "failed_launch": True,
                "support_stop_like": True,
            },
        },
    ]

    summary = factor_audit_summary(rows)
    interactions = summary["factor_interaction_opportunity_cost"]

    assert interactions["not_used_for_signal_score"] is True
    assert interactions["entry_family_rank"][0]["factor_group"] == "entry_family+rank_bucket"
    assert interactions["low_suction_days_first_lift"]
    assert interactions["risk_market_warning"]
    assert interactions["opportunity_cost"]["removed_winner_count"] == 1
    assert interactions["opportunity_cost"]["avoided_loser_count"] == 1


def test_candidate_execution_attribution_summarizes_top20_missed_quality() -> None:
    from alphaagent.server.services.backtest.factor_audit import candidate_execution_attribution_summary

    result = candidate_execution_attribution_summary(
        [
            {
                "trade_date": "2026-04-01",
                "vt_symbol": "002384.SZSE",
                "name": "东山精密",
                "entry_action": "BUY",
                "rank": 3,
                "total_score": 97.5,
                "entry_family": "low_position_reclaim",
                "outcome": {
                    "execute_date": "2026-04-02",
                    "return_20d": 18.0,
                    "mfe_20d": 30.0,
                    "mae_20d": -2.0,
                    "uses_future_for_label_only": True,
                },
            },
            {
                "trade_date": "2026-04-01",
                "vt_symbol": "600000.SSE",
                "name": "样本",
                "entry_action": "BUY",
                "rank": 9,
                "total_score": 91.0,
                "entry_family": "dragon_pullback",
                "outcome": {
                    "execute_date": "2026-04-02",
                    "return_20d": -6.0,
                    "mfe_20d": 2.0,
                    "mae_20d": -8.0,
                    "uses_future_for_label_only": True,
                },
            },
            {
                "trade_date": "2026-04-01",
                "vt_symbol": "600001.SSE",
                "entry_action": "BUY",
                "rank": 28,
                "outcome": {"return_20d": 50.0},
            },
        ],
        signal_events=[
            {
                "trade_date": "2026-04-02",
                "signal_date": "2026-04-01",
                "vt_symbol": "600000.SSE",
                "side": "BUY",
            }
        ],
        trades=[
            {
                "trade_date": "2026-04-02",
                "vt_symbol": "600000.SSE",
                "side": "BUY",
                "price": 10.0,
                "raw": {"execution": {"signal_date": "2026-04-01"}},
            }
        ],
        max_execution_rank=20,
    )

    assert result["candidate_count"] == 2
    assert result["filled_count"] == 1
    assert result["missed_count"] == 1
    assert result["top20_missed_quality"]["missed_positive_20d_count"] == 1
    assert result["top20_missed_quality"]["missed_avg_return_20d"] == 18.0
    missed = [row for row in result["items"] if row["vt_symbol"] == "002384.SZSE"][0]
    assert missed["not_filled_reason"] == "candidate_not_planned"
    assert missed["uses_future_for_label_only"] is True
    assert missed["not_used_for_signal_score"] is True


def test_candidate_execution_attribution_reports_unfilled_candidate_quality() -> None:
    from alphaagent.server.services.backtest.factor_audit import candidate_execution_attribution_summary

    result = candidate_execution_attribution_summary(
        [
            {
                "trade_date": "2026-04-01",
                "vt_symbol": "002384.SZSE",
                "name": "东山精密",
                "entry_action": "BUY",
                "rank": 3,
                "total_score": 99.0,
                "entry_family": "low_position_reclaim",
                "outcome": {
                    "execute_date": "2026-04-02",
                    "return_20d": 18.0,
                    "mfe_20d": 30.0,
                    "mae_20d": -2.0,
                    "uses_future_for_label_only": True,
                },
            }
        ],
        signal_events=[],
        orders=[],
        trades=[],
        cache_coverage={"candidate_count": 100, "signal_count": 0},
        max_execution_rank=20,
    )

    row = result["items"][0]
    assert row["signal_date"] == "2026-04-01"
    assert row["vt_symbol"] == "002384.SZSE"
    assert row["rank"] == 3
    assert row["score"] == 99.0
    assert row["missed_return_20d"] == 18.0
    assert row["not_filled_reason"] == "candidate_not_planned"
    assert row["not_used_for_signal_score"] is True


def test_candidate_execution_attribution_summarizes_all_unfilled_top20_candidates() -> None:
    from alphaagent.server.services.backtest.factor_audit import candidate_execution_attribution_summary

    result = candidate_execution_attribution_summary(
        [
            {
                "trade_date": "2026-04-01",
                "vt_symbol": "002384.SZSE",
                "entry_action": "BUY",
                "rank": 3,
                "total_score": 99.0,
                "outcome": {
                    "execute_date": "2026-04-02",
                    "return_20d": 12.0,
                    "mfe_20d": 18.0,
                    "mae_20d": -2.0,
                    "uses_future_for_label_only": True,
                },
            },
            {
                "trade_date": "2026-04-01",
                "vt_symbol": "605255.SSE",
                "entry_action": "BUY",
                "rank": 4,
                "total_score": 96.0,
                "outcome": {
                    "execute_date": "2026-04-02",
                    "return_20d": 30.0,
                    "uses_future_for_label_only": True,
                },
            },
            {
                "trade_date": "2026-04-01",
                "vt_symbol": "600000.SSE",
                "entry_action": "BUY",
                "rank": 5,
                "total_score": 91.0,
                "outcome": {
                    "execute_date": "2026-04-02",
                    "return_20d": -4.0,
                    "uses_future_for_label_only": True,
                },
            },
        ],
        signal_events=[
            {
                "trade_date": "2026-04-02",
                "signal_date": "2026-04-01",
                "vt_symbol": "600000.SSE",
                "side": "BUY",
            }
        ],
        trades=[
            {
                "trade_date": "2026-04-02",
                "vt_symbol": "600000.SSE",
                "side": "BUY",
                "price": 10.0,
                "raw": {"execution": {"signal_date": "2026-04-01"}},
            }
        ],
        cache_coverage={"candidate_count": 100, "signal_count": 1},
        max_execution_rank=20,
    )

    assert result["filled_count"] == 1
    assert result["missed_count"] == 2
    assert result["top20_missed_quality"]["missed_count"] == 2
    assert result["top20_missed_quality"]["missed_positive_20d_count"] == 2
    by_reason = {row["not_filled_reason"]: row for row in result["by_not_filled_reason"]}
    assert by_reason["candidate_not_planned"]["sample_count"] == 2


def test_candidate_not_planned_subreason_separates_plan_gaps() -> None:
    from alphaagent.server.services.backtest.factor_audit import (
        candidate_execution_attribution_summary,
        classify_candidate_plan_gap,
    )

    theoretical_gap = classify_candidate_plan_gap(
        {
            "rank": 3,
            "entry_action": "BUY",
            "candidate_trade_date": "2026-04-01",
            "vt_symbol": "002384.SZSE",
            "theoretical_position": {"is_holding": True, "entry_date": "2026-03-28"},
        },
        signal_events=[],
        orders=[],
        cache_coverage={"candidate_count": 100, "signal_count": 0},
    )

    assert theoretical_gap["subreason"] == "already_theoretical_holding"
    assert theoretical_gap["not_used_for_signal_score"] is True

    sparse_gap = classify_candidate_plan_gap(
        {
            "rank": 5,
            "entry_action": "BUY",
            "candidate_trade_date": "2026-05-11",
            "vt_symbol": "603439.SSE",
        },
        signal_events=[],
        orders=[],
        cache_coverage={"candidate_count": 8, "signal_count": 0},
    )

    assert sparse_gap["subreason"] == "candidate_cache_sparse_or_missing"

    inferred_holding_gap = classify_candidate_plan_gap(
        {
            "rank": 1,
            "entry_action": "BUY",
            "trade_date": "2025-08-07",
            "vt_symbol": "605255.SSE",
        },
        signal_events=[
            {
                "id": 1,
                "signal_date": "2025-08-06",
                "trade_date": "2025-08-07",
                "vt_symbol": "605255.SSE",
                "side": "BUY",
                "raw": {"status": "filled"},
            }
        ],
        orders=[],
        cache_coverage={"candidate_count": 100, "signal_count": 1},
    )

    assert inferred_holding_gap["subreason"] == "already_theoretical_holding"
    assert "2025-08-07" in str(inferred_holding_gap["label"])

    summary = candidate_execution_attribution_summary(
        [
            {
                "trade_date": "2026-04-01",
                "vt_symbol": "002384.SZSE",
                "entry_action": "BUY",
                "rank": 3,
                "total_score": 97.5,
                "theoretical_position": {"is_holding": True, "entry_date": "2026-03-28"},
                "outcome": {"return_20d": 18.0, "uses_future_for_label_only": True},
            }
        ],
        signal_events=[],
        orders=[],
        trades=[],
        cache_coverage={"candidate_count": 100, "signal_count": 0},
        max_execution_rank=20,
    )

    missed = summary["items"][0]
    assert missed["not_filled_reason"] == "candidate_not_planned"
    assert missed["not_filled_subreason"] == "already_theoretical_holding"
    assert missed["not_filled_label"] == "候选存在，但理论计划层已持有同股或没有重复写 BUY"
    assert summary["by_not_filled_subreason"][0]["not_filled_subreason"] == "already_theoretical_holding"


def test_backtest_factor_audit_api_passes_top_limit(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_factor_audit(backtest_id: int, top_limit: int = 100, exclude_strong_market: bool = False):
        captured.update({"backtest_id": backtest_id, "top_limit": top_limit, "exclude_strong_market": exclude_strong_market})
        return {"status": "ready", "backtest_id": backtest_id, "summary": {"sample_count": 3}}

    monkeypatch.setattr(backtests, "backtest_factor_audit", fake_factor_audit)
    client = TestClient(create_app())

    response = client.get("/api/backtests/203/factor-audit?top_limit=50&exclude_strong_market=true")

    assert response.status_code == 200
    assert response.json()["data"]["summary"]["sample_count"] == 3
    assert captured == {"backtest_id": 203, "top_limit": 50, "exclude_strong_market": True}


def test_factor_audit_cache_rows_preserve_audit_only_flags() -> None:
    from alphaagent.server.services.backtest import engine

    item = {
        "trade_date": date(2026, 5, 11),
        "vt_symbol": "603439.SSE",
        "rank": 8,
        "entry_family": "low_position_reclaim",
        "uses_future_for_label_only": False,
        "not_used_for_signal_score": True,
        "outcome": {
            "signal_date": date(2026, 5, 11),
            "execute_date": date(2026, 5, 12),
            "uses_future_for_label_only": True,
            "not_used_for_signal_score": True,
        },
    }

    snapshot = engine._factor_snapshot_values(203, item)
    outcome = engine._factor_outcome_values(203, item)

    assert snapshot["payload"]["not_used_for_signal_score"] is True
    assert snapshot["payload"]["uses_future_for_label_only"] is False
    assert "outcome" not in snapshot["payload"]
    assert outcome["payload"]["uses_future_for_label_only"] is True
    assert outcome["payload"]["not_used_for_signal_score"] is True
    assert outcome["payload"]["execute_date"] == "2026-05-12"
    assert snapshot["payload"]["factor_cache_schema_version"] == engine.FACTOR_AUDIT_CACHE_SCHEMA_VERSION


def test_signal_event_candidate_rows_use_signal_date_and_execution_rank() -> None:
    from alphaagent.server.services.backtest import engine

    rows = [
        {
            "id": 3,
            "trade_date": date(2026, 4, 9),
            "signal_date": date(2026, 4, 8),
            "execute_date": date(2026, 4, 9),
            "vt_symbol": "002384.SZSE",
            "side": "BUY",
            "score": 91.2,
            "raw": {
                "evidence": {
                    "entry_family": "low_position_reclaim",
                    "entry_setup": "stealth_low_suction",
                    "low_suction_days": 5,
                    "low_suction_launch_confirmed": True,
                },
                "candidate_execution": {
                    "execution_candidate_rank": 7,
                    "raw_signal_rank": 12,
                },
            },
        },
        {
            "id": 1,
            "trade_date": date(2026, 4, 9),
            "signal_date": date(2026, 4, 8),
            "execute_date": date(2026, 4, 9),
            "vt_symbol": "600000.SSE",
            "side": "SELL",
            "score": None,
            "raw": {"reason": "support_stop"},
        },
        {
            "id": 2,
            "trade_date": date(2026, 4, 9),
            "signal_date": date(2026, 4, 8),
            "execute_date": date(2026, 4, 9),
            "vt_symbol": "603439.SSE",
            "side": "BUY",
            "score": 92.5,
            "raw": {
                "evidence": {
                    "entry_family": "dragon_pullback",
                    "entry_setup": "dragon_pullback",
                    "low_suction_days": 0,
                },
                "candidate_execution": {
                    "execution_candidate_rank": 3,
                    "raw_signal_rank": 4,
                },
            },
        },
    ]

    candidates = engine._signal_event_candidate_rows(rows, row_limit=2)

    assert [row["vt_symbol"] for row in candidates] == ["603439.SSE", "002384.SZSE"]
    assert candidates[0]["trade_date"] == date(2026, 4, 8)
    assert candidates[0]["execute_date"] == date(2026, 4, 9)
    assert candidates[0]["rank"] == 3
    assert candidates[0]["action"] == "BUY"
    assert candidates[0]["source"] == "backtest_signal_events"
    assert candidates[0]["reason"]["entry_family"] == "dragon_pullback"
    assert candidates[1]["rank"] == 7


def test_signal_event_candidate_rows_fall_back_to_raw_rank_and_evidence_score() -> None:
    from alphaagent.server.services.backtest import engine

    rows = [
        {
            "id": 1,
            "trade_date": date(2026, 5, 12),
            "signal_date": date(2026, 5, 11),
            "execute_date": date(2026, 5, 12),
            "vt_symbol": "603439.SSE",
            "side": "BUY",
            "score": None,
            "raw": {
                "evidence": {
                    "entry_total_score": 88.6,
                    "entry_family": "low_position_reclaim",
                    "entry_setup": "stealth_low_suction",
                },
                "candidate_execution": {"raw_signal_rank": 18},
            },
        }
    ]

    candidates = engine._signal_event_candidate_rows(rows, row_limit=10)

    assert len(candidates) == 1
    assert candidates[0]["rank"] == 18
    assert candidates[0]["total_score"] == 88.6


def test_factor_cache_falls_back_to_backtest_signal_events_when_candidate_runs_missing(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    captured = {}

    class FakeResult:
        def __init__(self, rows=None):
            self._rows = rows or []

        def mappings(self):
            return self

        def all(self):
            return self._rows

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if "FROM quant_recommendations" in text or "FROM quant_stock_signals" in text:
                return FakeResult([])
            if "FROM backtest_signal_events" in text:
                return FakeResult(
                    [
                        {
                            "id": 1,
                            "trade_date": date(2026, 5, 12),
                            "signal_date": date(2026, 5, 11),
                            "execute_date": date(2026, 5, 12),
                            "vt_symbol": "603439.SSE",
                            "side": "BUY",
                            "score": 88.6,
                            "raw": {
                                "evidence": {"entry_setup": "dragon_pullback"},
                                "candidate_execution": {"execution_candidate_rank": 9},
                            },
                        }
                    ]
                )
            raise AssertionError(text)

    monkeypatch.setattr(engine.screening_loaders, "screen_runs_between", lambda *args, **kwargs: {})

    def fake_items(session, run, candidate_rows):
        captured["candidate_rows"] = candidate_rows
        return [{"trade_date": candidate_rows[0]["trade_date"], "vt_symbol": candidate_rows[0]["vt_symbol"], "rank": candidate_rows[0]["rank"]}]

    monkeypatch.setattr(engine, "_factor_cache_items_from_candidate_rows", fake_items)

    items, coverage = engine._build_factor_cache_items(
        FakeSession(),
        {
            "id": 203,
            "strategy_id": "mainline_dragon_pullback",
            "strategy_version": "0.1.23",
            "start_date": date(2026, 5, 1),
            "end_date": date(2026, 5, 31),
            "params": {"max_symbols": 500, "included_boards": ["main"]},
        },
        row_limit=20,
    )

    assert coverage["candidate_source"] == "backtest_signal_events"
    assert coverage["used_signal_fallback_count"] == 1
    assert items[0]["vt_symbol"] == "603439.SSE"
    assert captured["candidate_rows"][0]["rank"] == 9


def test_factor_cache_preserves_existing_snapshots_when_rebuild_has_no_items(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    calls: list[object] = []

    class FakeResult:
        def __init__(self, row=None):
            self._row = row

        def mappings(self):
            return self

        def first(self):
            return self._row

    class FakeSession:
        def execute(self, statement, *args, **kwargs):
            del args, kwargs
            calls.append(statement)
            text = str(statement)
            if "FROM backtest_runs" in text:
                return FakeResult(
                    {
                        "id": 381,
                        "strategy_id": "mainline_dragon_pullback",
                        "strategy_version": "0.1.24",
                        "start_date": date(2026, 1, 1),
                        "end_date": date(2026, 6, 18),
                        "params": {"max_symbols": 500, "included_boards": ["main"]},
                    }
                )
            raise AssertionError(text)

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(engine, "is_database_configured", lambda: True)
    monkeypatch.setattr(engine, "_ensure_backtest_schema", lambda: None)
    monkeypatch.setattr(engine, "session_scope", fake_session_scope)
    monkeypatch.setattr(engine, "_complete_factor_cache_count", lambda session, backtest_id: 0)
    monkeypatch.setattr(engine, "_valid_factor_cache_count", lambda session, backtest_id: 12)
    monkeypatch.setattr(engine, "_lock_factor_cache_build", lambda session, backtest_id: None)
    monkeypatch.setattr(engine, "_factor_snapshot_count", lambda session, backtest_id: 12)
    monkeypatch.setattr(
        engine,
        "_build_factor_cache_items",
        lambda session, run, row_limit: ([], {"candidate_source": "backtest_signal_events", "candidate_count": 0, "signal_count": 0}),
    )
    monkeypatch.setattr(engine, "_factor_cache_coverage", lambda session, backtest_id: {"snapshot_count": 12})

    result = engine.ensure_factor_audit_cache(381, limit=20000)

    assert result["status"] == "ready"
    assert result["cache"] == "existing_snapshots_preserved"
    assert result["coverage"]["candidate_source"] == "existing_backtest_factor_snapshots"
    assert result["coverage"]["rebuild_candidate_source"] == "backtest_signal_events"
    assert not any("DELETE FROM backtest_factor_snapshots" in str(call) for call in calls)
    assert not any("DELETE FROM backtest_factor_outcomes" in str(call) for call in calls)


def test_strategy_timeline_rows_merge_candidate_plan_order_trade() -> None:
    from alphaagent.server.services.backtest.factor_audit import strategy_timeline_rows

    rows = strategy_timeline_rows(
        vt_symbol="603439.SSE",
        recommendations=[
            {
                "trade_date": date(2026, 6, 17),
                "vt_symbol": "603439.SSE",
                "rank": 8,
                "action": "BUY",
                "total_score": 92.5,
                "reason": {"entry_family_label": "低位承接转强", "low_suction_days": 4},
            }
        ],
        signal_events=[
            {
                "trade_date": date(2026, 6, 18),
                "signal_date": date(2026, 6, 17),
                "execute_date": date(2026, 6, 18),
                "vt_symbol": "603439.SSE",
                "side": "BUY",
                "score": 92.5,
                "reason": "entry_signal",
                "raw": {"candidate_execution": {"execution_candidate_selected": True}},
            }
        ],
        orders=[
            {
                "trade_date": date(2026, 6, 18),
                "vt_symbol": "603439.SSE",
                "side": "BUY",
                "status": "rejected",
                "reason": "position_slot_unavailable",
                "price": 18.8,
            }
        ],
        trades=[
            {
                "trade_date": date(2026, 6, 24),
                "vt_symbol": "603439.SSE",
                "side": "SELL",
                "price": 20.1,
                "reason": "trend_trailing_stop",
                "pnl": 6.5,
            }
        ],
    )

    candidate_row = next(row for row in rows if row["date"] == "2026-06-17")
    execute_row = next(row for row in rows if row["date"] == "2026-06-18")
    sell_row = next(row for row in rows if row["date"] == "2026-06-24")
    assert candidate_row["candidate"]["action"] == "BUY"
    assert candidate_row["candidate"]["rank"] == 8
    assert execute_row["execution"]["status"] == "planned_not_ordered"
    assert execute_row["execution"]["reason_code"] == "position_slot_unavailable"
    assert sell_row["sell"]["reason"] == "trend_trailing_stop"


def test_strategy_timeline_rows_collapses_low_suction_buildup_cluster() -> None:
    from alphaagent.server.services.backtest.factor_audit import strategy_timeline_rows

    rows = strategy_timeline_rows(
        vt_symbol="002384.SZSE",
        recommendations=[
            {
                "trade_date": date(2026, 3, 27),
                "vt_symbol": "002384.SZSE",
                "rank": 12,
                "action": "WATCH",
                "total_score": 72.0,
                "reason": {
                    "action": "WATCH",
                    "entry_family": "low_position_reclaim",
                    "entry_setup": "stealth_low_suction",
                    "entry_family_label": "低位承接转强",
                    "low_suction_days": 3,
                    "low_suction_launch_confirmed": False,
                },
            },
            {
                "trade_date": date(2026, 3, 30),
                "vt_symbol": "002384.SZSE",
                "rank": 9,
                "action": "WATCH",
                "total_score": 75.0,
                "reason": {
                    "action": "WATCH",
                    "entry_family": "low_position_reclaim",
                    "entry_setup": "stealth_low_suction",
                    "entry_family_label": "低位承接转强",
                    "low_suction_days": 4,
                    "low_suction_launch_confirmed": False,
                },
            },
            {
                "trade_date": date(2026, 4, 1),
                "vt_symbol": "002384.SZSE",
                "rank": 4,
                "action": "BUY",
                "total_score": 88.0,
                "reason": {
                    "action": "BUY",
                    "entry_family": "low_position_reclaim",
                    "entry_setup": "stealth_low_suction",
                    "entry_family_label": "低位承接转强",
                    "low_suction_days": 5,
                    "low_suction_launch_confirmed": True,
                    "low_suction_launch_quality_bucket": "balanced_first_lift",
                },
            },
        ],
        signal_events=[],
        orders=[],
        trades=[],
    )

    assert len(rows) == 2
    assert rows[0]["cluster"]["type"] == "buildup_cluster"
    assert rows[0]["cluster"]["cluster_start_date"] == "2026-03-27"
    assert rows[0]["cluster"]["cluster_end_date"] == "2026-03-30"
    assert rows[0]["display_markers"] == ["BUY_REJECTED"]
    assert rows[1]["date"] == "2026-04-01"
    assert rows[1]["display_markers"] == ["BUY_SIGNAL"]


def test_strategy_lifecycle_segments_links_buildup_to_first_lift() -> None:
    from alphaagent.server.services.backtest.factor_audit import strategy_lifecycle_segments, strategy_timeline_rows

    rows = strategy_timeline_rows(
        vt_symbol="002384.SZSE",
        recommendations=[
            {
                "trade_date": date(2026, 4, 1),
                "vt_symbol": "002384.SZSE",
                "action": "WATCH",
                "rank": 4,
                "total_score": 91.0,
                "reason": {
                    "action": "WATCH",
                    "entry_setup": "stealth_low_suction",
                    "entry_family": "low_position_reclaim",
                    "low_suction_days": 4,
                    "low_suction_launch_confirmed": False,
                },
            },
            {
                "trade_date": date(2026, 4, 2),
                "vt_symbol": "002384.SZSE",
                "action": "WATCH",
                "rank": 3,
                "total_score": 92.0,
                "reason": {
                    "action": "WATCH",
                    "entry_setup": "stealth_low_suction",
                    "entry_family": "low_position_reclaim",
                    "low_suction_days": 5,
                    "low_suction_launch_confirmed": False,
                },
            },
            {
                "trade_date": date(2026, 4, 8),
                "vt_symbol": "002384.SZSE",
                "action": "BUY",
                "rank": 1,
                "total_score": 98.0,
                "reason": {
                    "action": "BUY",
                    "entry_setup": "stealth_low_suction",
                    "entry_family": "low_position_reclaim",
                    "low_suction_days": 6,
                    "low_suction_launch_confirmed": True,
                    "low_suction_launch_quality_bucket": "balanced_first_lift",
                },
            },
        ],
        signal_events=[],
        orders=[],
        trades=[],
    )

    segments = strategy_lifecycle_segments(rows)

    assert segments == [
        {
            "vt_symbol": "002384.SZSE",
            "cluster_start_date": "2026-04-01",
            "cluster_end_date": "2026-04-02",
            "key_signal_date": "2026-04-08",
            "cluster_type": "low_suction_buildup",
            "buildup_days": 2,
            "support_hold_days": None,
            "first_effective_lift": True,
            "launch_confirmed": True,
            "launch_quality_bucket": "balanced_first_lift",
            "key_signal_rank": 1,
            "key_signal_score": 98.0,
            "key_signal_action": "BUY",
        }
    ]


def test_backtest_strategy_timeline_api_passes_symbol(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_strategy_timeline(backtest_id: int, vt_symbol: str):
        captured.update({"backtest_id": backtest_id, "vt_symbol": vt_symbol})
        return {"status": "ready", "backtest_id": backtest_id, "vt_symbol": vt_symbol, "items": []}

    monkeypatch.setattr(backtests, "backtest_strategy_timeline", fake_strategy_timeline)
    client = TestClient(create_app())

    response = client.get("/api/backtests/203/strategy-timeline?vt_symbol=603439.SSE")

    assert response.status_code == 200
    assert response.json()["data"]["vt_symbol"] == "603439.SSE"
    assert captured == {"backtest_id": 203, "vt_symbol": "603439.SSE"}


def test_backtest_experiment_can_require_low_suction_launch_confirmation() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    low_suction_buy = SignalScore(
        vt_symbol="002384.SZSE",
        trade_date=date(2026, 6, 11),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=88.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "setup_type": "stealth_low_suction",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 5,
            "low_suction_launch_confirmed": False,
        },
    )

    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0)
    strict_launch_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        require_low_suction_launch_confirmation=True,
    )

    assert scoring.is_buy_candidate(low_suction_buy, default_params) is True
    assert scoring.is_buy_candidate(low_suction_buy, strict_launch_params) is False
    low_suction_buy.evidence["low_suction_launch_confirmed"] = True
    assert scoring.is_buy_candidate(low_suction_buy, strict_launch_params) is True


def test_backtest_experiment_can_exclude_repeated_dragon_pullback() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    repeated_dragon = SignalScore(
        vt_symbol="002119.SZSE",
        trade_date=date(2026, 2, 5),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=97.0,
        liquidity_score=100.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "setup_type": "dragon_pullback",
            "entry_setup": "dragon_pullback",
            "failed_rules": [],
            "fresh_tail_buy": False,
            "tail_buy_repeat_days": 1,
        },
    )
    fresh_dragon = SignalScore(
        vt_symbol="002119.SZSE",
        trade_date=date(2026, 2, 4),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=94.0,
        liquidity_score=100.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "setup_type": "dragon_pullback",
            "entry_setup": "dragon_pullback",
            "failed_rules": [],
            "fresh_tail_buy": True,
            "tail_buy_repeat_days": 0,
        },
    )

    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0)
    experiment_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        exclude_repeated_dragon_pullback=True,
    )

    assert scoring.is_buy_candidate(repeated_dragon, default_params) is True
    assert scoring.is_buy_candidate(repeated_dragon, experiment_params) is False
    assert scoring.is_buy_candidate(fresh_dragon, experiment_params) is True


def test_backtest_experiment_entry_launch_quality_adjusts_candidate_ranking() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    good_launch = SignalScore(
        vt_symbol="GOOD.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 5,
            "pullback_days": 5,
            "close_location_in_range": 0.64,
            "volume_ratio_5d_20d": 1.35,
            "ma_convergence_pct": 6.2,
            "latest_change_pct": 1.8,
            "ma5_distance_pct": 1.1,
            "low_suction_launch_confirmed": True,
        },
    )
    weak_launch = SignalScore(
        vt_symbol="WEAK.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 6,
            "pullback_days": 13,
            "close_location_in_range": 0.42,
            "volume_ratio_5d_20d": 0.62,
            "ma_convergence_pct": 4.2,
            "latest_change_pct": -0.2,
            "ma5_distance_pct": -0.4,
            "low_suction_launch_confirmed": True,
        },
    )

    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0)
    experiment_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        enable_entry_launch_quality_score=True,
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        default_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [weak_launch, good_launch],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        experiment_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [weak_launch, good_launch],
    )

    assert [row.vt_symbol for row in default_rows] == ["WEAK.SZSE", "GOOD.SZSE"]
    assert [row.vt_symbol for row in experiment_rows] == ["GOOD.SZSE", "WEAK.SZSE"]
    assert experiment_rows[0].evidence["entry_launch_quality_adjustment"] > 0
    assert experiment_rows[1].evidence["entry_launch_quality_adjustment"] < 0
    assert "entry_launch_quality_adjustment" not in good_launch.evidence


def test_backtest_experiment_entry_launch_risk_penalty_only_downgrades_risky_candidates() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    normal_launch = SignalScore(
        vt_symbol="NORMAL.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 4,
            "pullback_days": 6,
            "close_location_in_range": 0.64,
            "volume_ratio_5d_20d": 1.2,
            "low_suction_launch_confirmed": True,
        },
    )
    risky_launch = SignalScore(
        vt_symbol="RISKY.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 6,
            "pullback_days": 13,
            "close_location_in_range": 0.42,
            "volume_ratio_5d_20d": 0.62,
            "low_suction_launch_confirmed": True,
        },
    )

    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0)
    experiment_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        enable_entry_launch_risk_penalty=True,
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        default_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [risky_launch, normal_launch],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        experiment_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [risky_launch, normal_launch],
    )

    assert [row.vt_symbol for row in default_rows] == ["RISKY.SZSE", "NORMAL.SZSE"]
    assert [row.vt_symbol for row in experiment_rows] == ["NORMAL.SZSE", "RISKY.SZSE"]
    assert "entry_launch_risk_penalty_adjustment" not in experiment_rows[0].evidence
    assert experiment_rows[1].evidence["entry_launch_risk_penalty_adjustment"] < 0
    assert "entry_launch_risk_penalty_adjustment" not in normal_launch.evidence


def test_backtest_experiment_candidate_tail_risk_penalty_filters_extreme_bad_top20_bucket() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    risky_high_close = SignalScore(
        vt_symbol="RISKY.SZSE",
        trade_date=date(2026, 5, 18),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=94.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "dynamic_market_regime": "choppy_rotation",
            "low_suction_launch_quality_bucket": "high_close_launch",
            "close_location_in_range": 0.92,
            "volume_ratio_5d_20d": 1.05,
            "ma_convergence_pct": 7.4,
        },
    )
    clean_momentum = SignalScore(
        vt_symbol="CLEAN.SZSE",
        trade_date=date(2026, 5, 18),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "dynamic_market_regime": "choppy_rotation",
            "low_suction_launch_quality_bucket": "not_low_suction",
            "close_location_in_range": 0.58,
            "volume_ratio_5d_20d": 1.15,
            "ma_convergence_pct": 11.0,
            "recent_limit_up_20d": True,
            "large_bull_count_20d": 4,
        },
    )

    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0)
    experiment_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        enable_candidate_tail_risk_penalty=True,
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 5, 18),
        default_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [risky_high_close, clean_momentum],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 5, 18),
        experiment_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [risky_high_close, clean_momentum],
    )

    assert [row.vt_symbol for row in default_rows] == ["RISKY.SZSE", "CLEAN.SZSE"]
    assert [row.vt_symbol for row in experiment_rows] == ["CLEAN.SZSE"]
    assert scoring._is_candidate_tail_risk_blocked(risky_high_close.evidence) is True
    assert "candidate_tail_risk_adjustment" not in risky_high_close.evidence


def test_backtest_experiment_candidate_tail_risk_penalty_demotes_moderate_bad_top20_bucket() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    moderate_risk = SignalScore(
        vt_symbol="MODERATE.SZSE",
        trade_date=date(2026, 5, 18),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=94.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "dynamic_market_regime": "strong_broad",
            "low_suction_launch_quality_bucket": "high_close_launch",
            "close_location_in_range": 0.79,
            "volume_ratio_5d_20d": 1.05,
            "ma_convergence_pct": 7.4,
        },
    )
    clean_momentum = SignalScore(
        vt_symbol="CLEAN.SZSE",
        trade_date=date(2026, 5, 18),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "dynamic_market_regime": "strong_broad",
            "low_suction_launch_quality_bucket": "not_low_suction",
            "close_location_in_range": 0.58,
            "volume_ratio_5d_20d": 1.15,
            "ma_convergence_pct": 11.0,
            "recent_limit_up_20d": True,
            "large_bull_count_20d": 4,
        },
    )

    experiment_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        enable_candidate_tail_risk_penalty=True,
    )

    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 5, 18),
        experiment_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [moderate_risk, clean_momentum],
    )

    assert [row.vt_symbol for row in experiment_rows] == ["CLEAN.SZSE", "MODERATE.SZSE"]
    assert scoring._is_candidate_tail_risk_blocked(moderate_risk.evidence) is False
    assert experiment_rows[1].evidence["candidate_tail_risk_adjustment"] < 0
    assert "candidate_tail_risk_adjustment" not in moderate_risk.evidence


def test_backtest_experiment_mainline_momentum_lane_promotes_active_winner_profile() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    active_mainline = SignalScore(
        vt_symbol="MAIN.SZSE",
        trade_date=date(2026, 5, 22),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=84.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "dynamic_market_regime": "choppy_rotation",
            "recent_limit_up_20d": True,
            "large_bull_count_20d": 4,
            "near_limit_up_count_20d": 2,
            "close_location_in_range": 0.62,
            "volume_ratio_5d_20d": 1.25,
            "ma_convergence_pct": 11.0,
            "latest_change_pct": 4.8,
        },
    )
    ordinary_candidate = SignalScore(
        vt_symbol="PLAIN.SZSE",
        trade_date=date(2026, 5, 22),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=86.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "dynamic_market_regime": "choppy_rotation",
        },
    )

    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0)
    experiment_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        enable_mainline_momentum_lane=True,
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 5, 22),
        default_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [ordinary_candidate, active_mainline],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 5, 22),
        experiment_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [ordinary_candidate, active_mainline],
    )

    assert [row.vt_symbol for row in default_rows] == ["PLAIN.SZSE"]
    assert [row.vt_symbol for row in experiment_rows] == ["MAIN.SZSE", "PLAIN.SZSE"]
    assert experiment_rows[0].evidence["mainline_momentum_lane_adjustment"] > 0
    assert "mainline_momentum_lane_adjustment" not in active_mainline.evidence


def test_backtest_experiment_mainline_momentum_risk_control_demotes_overextended_candidate() -> None:
    from alphaagent.server.services.backtest import scoring

    overextended = {
        "entry_setup": "dragon_pullback",
        "setup_family": "dragon_pullback",
        "mainline_momentum_lane_adjustment": 2.4,
        "recent_limit_up_20d": True,
        "large_bull_count_20d": 4,
        "near_limit_up_count_20d": 2,
        "close_location_in_range": 0.93,
        "ma_convergence_pct": 20.5,
        "ma5_distance_pct": 6.2,
        "volume_ratio_5d_20d": 1.45,
        "latest_change_pct": 6.8,
        "dynamic_market_regime": "false_bull",
        "market_warning_level": 3,
        "low_suction_launch_quality_bucket": "high_close_launch",
    }

    decision = scoring.mainline_momentum_risk_control_adjustment(overextended)

    assert decision["adjustment"] <= -5.0
    assert decision["profile"] == "mainline_momentum_risk_control"
    assert any("收盘过高" in note for note in decision["notes"])
    assert any("偏离5日线" in note for note in decision["notes"])


def test_backtest_experiment_mainline_momentum_risk_control_keeps_asymmetric_pullback() -> None:
    from alphaagent.server.services.backtest import scoring

    asymmetric_pullback = {
        "entry_setup": "dragon_pullback",
        "setup_family": "dragon_pullback",
        "mainline_momentum_lane_adjustment": 2.1,
        "recent_limit_up_20d": True,
        "large_bull_count_20d": 4,
        "near_limit_up_count_20d": 1,
        "close_location_in_range": 0.48,
        "ma_convergence_pct": 10.5,
        "ma5_distance_pct": 1.2,
        "volume_ratio_5d_20d": 1.2,
        "latest_change_pct": 2.8,
        "dynamic_market_regime": "choppy_rotation",
        "market_warning_level": 1,
        "low_suction_launch_quality_bucket": "not_low_suction",
    }

    decision = scoring.mainline_momentum_risk_control_adjustment(asymmetric_pullback)

    assert decision["adjustment"] > 0
    assert any("低位/中低位" in note for note in decision["notes"])


def test_backtest_experiment_mainline_momentum_risk_control_default_off() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    overextended = SignalScore(
        vt_symbol="HOT.SZSE",
        trade_date=date(2026, 6, 3),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "mainline_momentum_lane_adjustment": 2.4,
            "recent_limit_up_20d": True,
            "large_bull_count_20d": 4,
            "close_location_in_range": 0.93,
            "ma_convergence_pct": 20.5,
            "ma5_distance_pct": 6.2,
            "dynamic_market_regime": "false_bull",
            "market_warning_level": 3,
            "low_suction_launch_quality_bucket": "high_close_launch",
        },
    )
    plain = SignalScore(
        vt_symbol="PLAIN.SZSE",
        trade_date=date(2026, 6, 3),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=88.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
        },
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 3),
        BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0),
        score_candidates_for_day=lambda *_args, **_kwargs: [overextended, plain],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 3),
        BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            strict_entry=True,
            min_entry_score=76.0,
            enable_mainline_momentum_risk_control=True,
        ),
        score_candidates_for_day=lambda *_args, **_kwargs: [overextended, plain],
    )

    assert [row.vt_symbol for row in default_rows] == ["PLAIN.SZSE", "HOT.SZSE"]
    assert default_rows[1].evidence["candidate_quality_adjustment"] < 0
    assert [row.vt_symbol for row in experiment_rows] == ["PLAIN.SZSE", "HOT.SZSE"]
    assert "mainline_momentum_risk_control_adjustment" not in overextended.evidence


def test_backtest_experiment_mainline_momentum_hard_filter_blocks_extreme_tail_risk() -> None:
    from alphaagent.server.services.backtest import scoring

    overextended = {
        "entry_setup": "dragon_pullback",
        "setup_family": "dragon_pullback",
        "mainline_momentum_lane_adjustment": 2.4,
        "recent_limit_up_20d": True,
        "large_bull_count_20d": 4,
        "close_location_in_range": 0.93,
        "ma_convergence_pct": 20.5,
        "ma5_distance_pct": 6.2,
        "low_suction_launch_quality_bucket": "high_close_launch",
    }

    assert scoring.mainline_momentum_hard_filter_reason(overextended) == "ma5_overextended_wide_ma"


def test_backtest_experiment_mainline_momentum_hard_filter_blocks_false_bull_extreme_ma() -> None:
    from alphaagent.server.services.backtest import scoring

    false_bull_extreme_ma = {
        "entry_setup": "dragon_pullback",
        "setup_family": "dragon_pullback",
        "mainline_momentum_lane_adjustment": 2.1,
        "recent_limit_up_20d": True,
        "large_bull_count_20d": 4,
        "close_location_in_range": 0.68,
        "ma_convergence_pct": 23.5,
        "ma5_distance_pct": 2.4,
        "dynamic_market_regime": "false_bull",
        "market_warning_level": 2,
        "low_suction_launch_quality_bucket": "not_low_suction",
    }

    assert scoring.mainline_momentum_hard_filter_reason(false_bull_extreme_ma) == "false_bull_extreme_ma"


def test_backtest_experiment_mainline_momentum_hard_filter_blocks_risk_day_extreme_ma5_distance() -> None:
    from alphaagent.server.services.backtest import scoring

    risk_day_far_ma5 = {
        "entry_setup": "dragon_pullback",
        "setup_family": "dragon_pullback",
        "mainline_momentum_lane_adjustment": 2.1,
        "recent_limit_up_20d": True,
        "large_bull_count_20d": 3,
        "close_location_in_range": 0.52,
        "ma_convergence_pct": 10.2,
        "ma5_distance_pct": 9.3,
        "dynamic_market_regime": "choppy_rotation",
        "market_warning_level": 3,
        "low_suction_launch_quality_bucket": "not_low_suction",
    }

    assert scoring.mainline_momentum_hard_filter_reason(risk_day_far_ma5) == "risk_day_extreme_ma5_distance"


def test_backtest_experiment_mainline_momentum_hard_filter_keeps_low_pullback_buildup() -> None:
    from alphaagent.server.services.backtest import scoring

    low_pullback = {
        "entry_setup": "dragon_pullback",
        "setup_family": "dragon_pullback",
        "mainline_momentum_lane_adjustment": 2.1,
        "recent_limit_up_20d": True,
        "large_bull_count_20d": 4,
        "close_location_in_range": 0.46,
        "ma_convergence_pct": 11.0,
        "ma5_distance_pct": 1.4,
        "volume_ratio_5d_20d": 1.2,
        "low_suction_days": 5,
        "low_suction_launch_quality_bucket": "not_low_suction",
    }

    assert scoring.mainline_momentum_hard_filter_reason(low_pullback) is None


def test_backtest_experiment_mainline_momentum_hard_filter_default_off() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    overextended = SignalScore(
        vt_symbol="HOT.SZSE",
        trade_date=date(2026, 6, 3),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "mainline_momentum_lane_adjustment": 2.4,
            "recent_limit_up_20d": True,
            "large_bull_count_20d": 4,
            "close_location_in_range": 0.93,
            "ma_convergence_pct": 20.5,
            "ma5_distance_pct": 6.2,
            "low_suction_launch_quality_bucket": "high_close_launch",
        },
    )
    plain = SignalScore(
        vt_symbol="PLAIN.SZSE",
        trade_date=date(2026, 6, 3),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=88.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
        },
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 3),
        BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0),
        score_candidates_for_day=lambda *_args, **_kwargs: [overextended, plain],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 3),
        BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            strict_entry=True,
            min_entry_score=76.0,
            enable_mainline_momentum_hard_filter=True,
        ),
        score_candidates_for_day=lambda *_args, **_kwargs: [overextended, plain],
    )

    assert [row.vt_symbol for row in default_rows] == ["HOT.SZSE", "PLAIN.SZSE"]
    assert [row.vt_symbol for row in experiment_rows] == ["PLAIN.SZSE"]
    assert "mainline_momentum_hard_filter_reason" not in overextended.evidence


def test_backtest_experiment_weekly_top_fractal_relief_promotes_supported_strong_dragon() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    supported_dragon = SignalScore(
        vt_symbol="STRONG.SZSE",
        trade_date=date(2026, 6, 15),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.2,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "weekly_top_fractal_risk": True,
            "risk_flags": ["weekly_top_fractal_risk"],
            "risk_penalty": 4.0,
            "support_type": "ma5_reclaim",
            "ma5_distance_pct": -0.9,
            "ma10_distance_pct": -1.0,
            "ma_convergence_pct": 12.0,
            "latest_change_pct": 6.2,
            "return_20d": 40.0,
            "return_60d": 41.0,
            "close_location_in_range": 0.72,
            "volume_ratio_5d_20d": 1.1,
            "dynamic_market_regime": "choppy_rotation",
            "market_warning_level": 2,
        },
    )
    ordinary_candidate = SignalScore(
        vt_symbol="PLAIN.SZSE",
        trade_date=date(2026, 6, 15),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.5,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
        },
    )

    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0)
    experiment_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        enable_weekly_top_fractal_relief=True,
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 15),
        default_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [ordinary_candidate, supported_dragon],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 15),
        experiment_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [ordinary_candidate, supported_dragon],
    )

    assert [row.vt_symbol for row in default_rows] == ["PLAIN.SZSE", "STRONG.SZSE"]
    assert [row.vt_symbol for row in experiment_rows] == ["STRONG.SZSE", "PLAIN.SZSE"]
    assert experiment_rows[0].evidence["weekly_top_fractal_relief_adjustment"] > 0
    assert "weekly_top_fractal_relief_adjustment" not in supported_dragon.evidence


def test_backtest_experiment_weekly_top_fractal_relief_keeps_weak_low_suction_risk() -> None:
    from alphaagent.server.services.backtest import scoring

    weak_low_suction = {
        "weekly_top_fractal_risk": True,
        "risk_flags": ["weekly_top_fractal_risk"],
        "entry_setup": "stealth_low_suction",
        "setup_family": "low_suction_buildup",
        "low_suction_launch_quality_bucket": "unconfirmed_buildup",
        "ma_convergence_pct": 8.0,
        "return_20d": 30.0,
        "return_60d": 35.0,
    }

    decision = scoring.weekly_top_fractal_relief_adjustment(weak_low_suction)

    assert decision["adjustment"] == 0.0
    assert decision["profile"] == "keep_non_dragon_weekly_risk"


def test_backtest_experiment_low_suction_buildup_quality_lane_promotes_clean_buildup() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    clean_buildup = SignalScore(
        vt_symbol="LOW.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "setup_family": "low_suction_buildup",
            "failed_rules": [],
            "low_suction_days": 4,
            "low_suction_launch_quality_bucket": "unconfirmed_buildup",
            "low_suction_launch_confirmed": False,
            "ma_convergence_pct": 1.8,
            "ma5_distance_pct": 0.9,
            "ma10_distance_pct": 0.5,
            "ma20_distance_pct": 0.0,
            "volume_ratio_5d_20d": 0.83,
            "close_location_in_range": 0.28,
            "latest_change_pct": 3.1,
        },
    )
    ordinary_candidate = SignalScore(
        vt_symbol="PLAIN.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=93.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
        },
    )

    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0)
    experiment_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        enable_low_suction_buildup_quality_lane=True,
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 12),
        default_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [ordinary_candidate, clean_buildup],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 12),
        experiment_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [ordinary_candidate, clean_buildup],
    )

    assert [row.vt_symbol for row in default_rows] == ["PLAIN.SZSE", "LOW.SZSE"]
    assert [row.vt_symbol for row in experiment_rows] == ["PLAIN.SZSE", "LOW.SZSE"]
    assert experiment_rows[1].total_score > clean_buildup.total_score
    assert experiment_rows[1].evidence["low_suction_buildup_quality_adjustment"] > 1.0
    assert "low_suction_buildup_quality_adjustment" not in clean_buildup.evidence


def test_backtest_experiment_low_suction_buildup_quality_lane_treats_launch_as_extra_bonus() -> None:
    from alphaagent.server.services.backtest import scoring

    buildup = {
        "entry_setup": "stealth_low_suction",
        "setup_family": "low_suction_buildup",
        "low_suction_days": 4,
        "low_suction_launch_quality_bucket": "unconfirmed_buildup",
        "low_suction_launch_confirmed": False,
        "ma_convergence_pct": 2.2,
        "ma5_distance_pct": 0.8,
        "ma10_distance_pct": 0.6,
        "ma20_distance_pct": 0.2,
        "volume_ratio_5d_20d": 0.9,
        "close_location_in_range": 0.35,
        "latest_change_pct": 2.8,
    }
    confirmed = dict(
        buildup,
        low_suction_launch_quality_bucket="balanced_first_lift",
        low_suction_launch_confirmed=True,
    )

    buildup_decision = scoring.low_suction_buildup_quality_lane_adjustment(buildup)
    confirmed_decision = scoring.low_suction_buildup_quality_lane_adjustment(confirmed)

    assert buildup_decision["adjustment"] > 0
    assert confirmed_decision["adjustment"] > buildup_decision["adjustment"]
    assert any("未确认蓄势：不扣分" in note for note in buildup_decision["notes"])


def test_backtest_experiment_low_suction_buildup_quality_lane_relieves_weekly_risk_only_for_clean_buildup() -> None:
    from alphaagent.server.services.backtest import scoring

    clean_weekly_risk = {
        "entry_setup": "stealth_low_suction",
        "setup_family": "low_suction_buildup",
        "low_suction_days": 4,
        "low_suction_launch_quality_bucket": "unconfirmed_buildup",
        "weekly_top_fractal_risk": True,
        "risk_flags": ["weekly_top_fractal_risk"],
        "risk_penalty": 4.0,
        "ma_convergence_pct": 1.8,
        "ma5_distance_pct": 0.9,
        "ma10_distance_pct": 0.5,
        "ma20_distance_pct": 0.0,
        "volume_ratio_5d_20d": 0.83,
        "close_location_in_range": 0.28,
        "latest_change_pct": 3.1,
    }
    weak_weekly_risk = dict(clean_weekly_risk, ma_convergence_pct=7.0)

    clean_decision = scoring.low_suction_buildup_quality_lane_adjustment(clean_weekly_risk)
    weak_decision = scoring.low_suction_buildup_quality_lane_adjustment(weak_weekly_risk)

    assert clean_decision["adjustment"] > 1.0
    assert any("周线顶分型减免" in note for note in clean_decision["notes"])
    assert weak_decision["adjustment"] == 0.0
    assert weak_decision["profile"] == "loose_moving_averages"


def test_backtest_experiment_surge_quality_lane_promotes_active_lower_mid_pullback() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    active_pullback = SignalScore(
        vt_symbol="ACTIVE.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.2,
        liquidity_score=82.0,
        risk_score=78.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "recent_limit_up_20d": True,
            "large_bull_count_20d": 4,
            "low_suction_launch_quality_bucket": "not_low_suction",
            "close_location_in_range": 0.52,
            "ma_convergence_pct": 11.6,
            "ma5_distance_pct": 1.1,
            "volume_ratio_5d_20d": 1.24,
            "market_warning_level": 0,
        },
    )
    ordinary_candidate = SignalScore(
        vt_symbol="PLAIN.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=93.0,
        liquidity_score=82.0,
        risk_score=78.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "low_suction_launch_quality_bucket": "not_low_suction",
            "close_location_in_range": 0.62,
            "volume_ratio_5d_20d": 1.0,
        },
    )

    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0)
    experiment_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        enable_surge_quality_lane=True,
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 12),
        default_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [ordinary_candidate, active_pullback],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 12),
        experiment_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [ordinary_candidate, active_pullback],
    )

    assert [row.vt_symbol for row in default_rows] == ["PLAIN.SZSE", "ACTIVE.SZSE"]
    assert [row.vt_symbol for row in experiment_rows] == ["ACTIVE.SZSE", "PLAIN.SZSE"]
    assert experiment_rows[0].evidence["surge_quality_lane_adjustment"] > 0
    assert "surge_quality_lane_adjustment" not in active_pullback.evidence


def test_backtest_experiment_surge_quality_lane_demotes_high_close_weak_launch() -> None:
    from alphaagent.server.services.backtest import scoring

    weak_high_close = {
        "entry_setup": "dragon_pullback",
        "setup_family": "dragon_pullback",
        "low_suction_launch_quality_bucket": "high_close_launch",
        "recent_limit_up_20d": False,
        "large_bull_count_20d": 1,
        "close_location_in_range": 0.94,
        "ma_convergence_pct": 16.0,
        "ma5_distance_pct": 5.1,
        "volume_ratio_5d_20d": 1.05,
        "market_warning_level": 3,
    }

    decision = scoring.surge_quality_lane_adjustment(weak_high_close)

    assert decision["adjustment"] < -3.0
    assert decision["profile"] == "surge_quality"
    assert any("高位启动叠加风险" in note for note in decision["notes"])


def test_backtest_experiment_surge_quality_lane_demotes_stale_low_suction_without_activation() -> None:
    from alphaagent.server.services.backtest import scoring

    stale_buildup = {
        "entry_setup": "stealth_low_suction",
        "setup_family": "low_suction_buildup",
        "low_suction_days": 8,
        "low_suction_launch_quality_bucket": "unconfirmed_buildup",
        "recent_limit_up_20d": False,
        "large_bull_count_20d": 0,
        "close_location_in_range": 0.44,
        "ma_convergence_pct": 7.2,
        "volume_ratio_5d_20d": 0.82,
        "market_warning_level": 2,
    }

    decision = scoring.surge_quality_lane_adjustment(stale_buildup)

    assert decision["adjustment"] < 0
    assert any("低吸蓄势超过6天" in note for note in decision["notes"])


def test_backtest_experiment_selective_setup_quality_promotes_active_lower_mid_acceptance() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    active_lower_mid = SignalScore(
        vt_symbol="ACTIVE.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.8,
        liquidity_score=82.0,
        risk_score=78.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "recent_limit_up_20d": True,
            "large_bull_count_20d": 4,
            "near_limit_up_count_20d": 2,
            "low_suction_launch_quality_bucket": "not_low_suction",
            "close_location_in_range": 0.52,
            "ma_convergence_pct": 11.6,
            "ma5_distance_pct": 1.1,
            "volume_ratio_5d_20d": 1.24,
            "market_warning_level": 1,
        },
    )
    ordinary_candidate = SignalScore(
        vt_symbol="PLAIN.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=93.0,
        liquidity_score=82.0,
        risk_score=78.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "low_suction_launch_quality_bucket": "not_low_suction",
            "close_location_in_range": 0.64,
        },
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 12),
        BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0),
        score_candidates_for_day=lambda *_args, **_kwargs: [ordinary_candidate, active_lower_mid],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 12),
        BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            strict_entry=True,
            min_entry_score=76.0,
            enable_selective_setup_quality_lane=True,
        ),
        score_candidates_for_day=lambda *_args, **_kwargs: [ordinary_candidate, active_lower_mid],
    )

    assert [row.vt_symbol for row in default_rows] == ["PLAIN.SZSE", "ACTIVE.SZSE"]
    assert [row.vt_symbol for row in experiment_rows] == ["ACTIVE.SZSE", "PLAIN.SZSE"]
    assert experiment_rows[0].evidence["selective_setup_quality_adjustment"] > 0
    assert "selective_setup_quality_adjustment" not in active_lower_mid.evidence


def test_backtest_experiment_support_divergence_entry_lane_promotes_mature_low_suction() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    mature_low_suction = SignalScore(
        vt_symbol="003004.SZSE",
        trade_date=date(2026, 4, 30),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=77.8449,
        liquidity_score=15.0,
        risk_score=61.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "entry_setup": "support_accepted",
            "dragon_state": "SUPPORT_ACCEPTED",
            "failed_rules": ["strong_leg", "liquidity_score"],
            "support_type": "ma5_reclaim",
            "low_suction_days": 4,
            "low_suction_buildup_score": 100.0,
            "stealth_low_suction_score": 100.0,
            "low_suction_launch_confirmed": True,
            "ma_convergence_pct": 5.1,
        },
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 30),
        BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0),
        score_candidates_for_day=lambda *_args, **_kwargs: [mature_low_suction],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 30),
        BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            strict_entry=True,
            min_entry_score=76.0,
            enable_support_divergence_entry_lane=True,
        ),
        score_candidates_for_day=lambda *_args, **_kwargs: [mature_low_suction],
    )

    assert default_rows == []
    assert [row.vt_symbol for row in experiment_rows] == ["003004.SZSE"]
    assert experiment_rows[0].evidence["support_divergence_entry_profile"] == "mature_low_suction_launch"
    assert experiment_rows[0].evidence["executable_entry_signal"] is True
    assert experiment_rows[0].evidence["support_divergence_entry_observation_only"] is True


def test_backtest_experiment_support_divergence_entry_lane_promotes_high_level_support() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    support_divergence = SignalScore(
        vt_symbol="003004.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.1248,
        liquidity_score=80.0,
        risk_score=62.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "entry_setup": "support_accepted",
            "dragon_state": "SUPPORT_ACCEPTED",
            "failed_rules": ["reclaim_confirmation"],
            "support_type": "ma10_support",
            "strong_leg_score": 100.0,
            "pullback_days": 8,
            "ma_convergence_pct": 24.8,
            "latest_change_pct": -0.47,
        },
    )

    rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 12),
        BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            strict_entry=True,
            min_entry_score=76.0,
            enable_support_divergence_entry_lane=True,
        ),
        score_candidates_for_day=lambda *_args, **_kwargs: [support_divergence],
    )

    assert [row.vt_symbol for row in rows] == ["003004.SZSE"]
    assert rows[0].evidence["support_divergence_entry_profile"] == "high_level_support_divergence"
    assert rows[0].evidence["signal_label"] == "支撑分歧低吸买点"
    assert rows[0].evidence["support_divergence_entry_observation_only"] is True


def test_backtest_experiment_support_divergence_entry_lane_marks_raw_failed_rule_as_observation_only() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    raw_support_divergence = SignalScore(
        vt_symbol="605090.SSE",
        trade_date=date(2026, 1, 8),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=98.61,
        liquidity_score=80.0,
        risk_score=62.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "support_accepted",
            "dragon_state": "SUPPORT_ACCEPTED",
            "failed_rules": ["reclaim_confirmation"],
            "support_type": "ma10_support",
            "strong_leg_score": 100.0,
            "pullback_days": 6,
            "ma_convergence_pct": 18.8,
            "latest_change_pct": 1.2,
        },
    )

    rows = scoring.score_day(
        None,
        {},
        date(2026, 1, 8),
        BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            strict_entry=True,
            min_entry_score=76.0,
            enable_support_divergence_entry_lane=True,
        ),
        score_candidates_for_day=lambda *_args, **_kwargs: [raw_support_divergence],
    )

    assert [row.vt_symbol for row in rows] == ["605090.SSE"]
    assert rows[0].evidence["raw_entry_signal"] is True
    assert rows[0].evidence["default_executable_entry_signal"] is False
    assert rows[0].evidence["support_divergence_entry_observation_only"] is True


def test_backtest_experiment_support_divergence_entry_lane_rejects_false_bull_wide_ma() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    weak_support_divergence = SignalScore(
        vt_symbol="601969.SSE",
        trade_date=date(2025, 11, 20),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.0,
        liquidity_score=80.0,
        risk_score=62.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "entry_setup": "support_accepted",
            "dragon_state": "SUPPORT_ACCEPTED",
            "failed_rules": ["ma_convergence_too_wide_without_low_suction"],
            "support_type": "ma5_reclaim",
            "strong_leg_score": 100.0,
            "pullback_days": 5,
            "ma_convergence_pct": 25.45,
            "latest_change_pct": 5.08,
            "close_location_in_range": 0.80,
            "market_warning_level": 2,
            "dynamic_market_regime": "false_bull",
        },
    )

    rows = scoring.score_day(
        None,
        {},
        date(2025, 11, 20),
        BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            strict_entry=True,
            min_entry_score=76.0,
            enable_support_divergence_entry_lane=True,
        ),
        score_candidates_for_day=lambda *_args, **_kwargs: [weak_support_divergence],
    )

    assert rows == []


def test_backtest_experiment_support_divergence_entry_lane_keeps_003004_wide_ma_reclaim() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    support_divergence = SignalScore(
        vt_symbol="003004.SZSE",
        trade_date=date(2026, 6, 15),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=95.6243,
        liquidity_score=80.0,
        risk_score=62.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "entry_setup": "support_accepted",
            "dragon_state": "SUPPORT_ACCEPTED",
            "failed_rules": ["ma_convergence_too_wide_without_low_suction"],
            "support_type": "ma5_reclaim",
            "strong_leg_score": 100.0,
            "pullback_days": 9,
            "ma_convergence_pct": 22.31,
            "latest_change_pct": 2.52,
            "close_location_in_range": 0.8466,
            "market_warning_level": 2,
            "dynamic_market_regime": "narrow_theme_bull",
        },
    )

    rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 15),
        BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            strict_entry=True,
            min_entry_score=76.0,
            enable_support_divergence_entry_lane=True,
        ),
        score_candidates_for_day=lambda *_args, **_kwargs: [support_divergence],
    )

    assert [row.vt_symbol for row in rows] == ["003004.SZSE"]
    assert rows[0].evidence["support_divergence_entry_profile"] == "high_level_support_divergence"


def test_backtest_experiment_strong_trend_ma_pullback_marks_003004_ma5_touch_research_only() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    ma_pullback = SignalScore(
        vt_symbol="003004.SZSE",
        trade_date=date(2026, 5, 25),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=78.49,
        liquidity_score=80.0,
        risk_score=62.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "entry_setup": "pullback_observe",
            "setup_type": "pullback_observe",
            "dragon_state": "PULLBACK_OBSERVE",
            "support_type": "none",
            "failed_rules": ["pullback_too_short"],
            "strong_leg_score": 95.0,
            "pullback_days": 1,
            "latest_change_pct": -0.0803,
            "close_location_in_range": 0.8101,
            "volume_ratio_5d_20d": 2.3395,
            "ma5_distance_pct": 5.7104,
            "ma10_distance_pct": 14.2385,
            "ma20_distance_pct": 29.2367,
            "ma_convergence_pct": 26.9454,
            "ma5_slope_pct": 4.7534,
            "ma5_vs_ma10_pct": 8.0674,
            "return_20d": 53.4855,
            "return_60d": 88.2709,
            "recent_limit_up_20d": True,
            "large_bull_count_20d": 2,
            "near_limit_up_count_20d": 2,
            "weekly_top_fractal_risk": True,
            "risk_penalty": 4.0,
            "dynamic_market_regime": "false_bull",
            "market_warning_level": 2,
        },
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 5, 25),
        BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0),
        score_candidates_for_day=lambda *_args, **_kwargs: [ma_pullback],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 5, 25),
        BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            strict_entry=True,
            min_entry_score=76.0,
            enable_strong_trend_ma_pullback_entry_lane=True,
        ),
        score_candidates_for_day=lambda *_args, **_kwargs: [ma_pullback],
    )

    assert default_rows == []
    assert [row.vt_symbol for row in experiment_rows] == ["003004.SZSE"]
    assert experiment_rows[0].evidence["strong_trend_ma_pullback_entry_profile"] == "strong_trend_intraday_ma_pullback"
    assert experiment_rows[0].evidence["strong_trend_ma_pullback_entry_observation_only"] is True
    assert experiment_rows[0].evidence["signal_label"] == "强趋势均线回踩研究买点"


def test_backtest_experiment_strong_trend_ma_pullback_rejects_distribution_day() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    distribution_day = SignalScore(
        vt_symbol="003004.SZSE",
        trade_date=date(2026, 6, 4),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=45.6773,
        liquidity_score=80.0,
        risk_score=62.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "entry_setup": "distribution_risk",
            "setup_type": "distribution_risk",
            "dragon_state": "DISTRIBUTION_RISK",
            "support_type": "none",
            "failed_rules": [
                "total_score",
                "distribution_risk",
                "support_acceptance",
                "reclaim_confirmation",
                "pullback_too_short",
            ],
            "strong_leg_score": 95.0,
            "pullback_days": 2,
            "latest_change_pct": -4.7914,
            "volume_ratio_5d_20d": 1.4252,
            "ma10_distance_pct": 4.1702,
            "ma_convergence_pct": 37.4613,
            "return_20d": 76.6398,
            "recent_limit_up_20d": True,
            "risk_penalty": 35.0,
        },
    )

    rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 4),
        BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            strict_entry=True,
            min_entry_score=76.0,
            enable_strong_trend_ma_pullback_entry_lane=True,
        ),
        score_candidates_for_day=lambda *_args, **_kwargs: [distribution_day],
    )

    assert rows == []


def test_backtest_experiment_selective_setup_quality_demotes_extreme_high_active_candidate() -> None:
    from alphaagent.server.services.backtest import scoring

    extreme_high_active = {
        "entry_setup": "dragon_pullback",
        "setup_family": "dragon_pullback",
        "recent_limit_up_20d": True,
        "large_bull_count_20d": 4,
        "near_limit_up_count_20d": 1,
        "low_suction_launch_quality_bucket": "not_low_suction",
        "close_location_in_range": 0.94,
        "ma_convergence_pct": 8.4,
        "ma5_distance_pct": 2.4,
        "volume_ratio_5d_20d": 1.1,
        "market_warning_level": 2,
    }

    decision = scoring.selective_setup_quality_lane_adjustment(extreme_high_active)

    assert decision["profile"] == "selective_setup_quality"
    assert decision["adjustment"] <= -3.0
    assert any("收盘极高" in note for note in decision["notes"])


def test_backtest_experiment_selective_setup_quality_demotes_stale_quiet_buildup() -> None:
    from alphaagent.server.services.backtest import scoring

    stale_quiet = {
        "entry_setup": "stealth_low_suction",
        "setup_family": "low_suction_buildup",
        "low_suction_days": 8,
        "low_suction_launch_quality_bucket": "unconfirmed_buildup",
        "recent_limit_up_20d": False,
        "large_bull_count_20d": 0,
        "close_location_in_range": 0.48,
        "ma_convergence_pct": 2.4,
        "ma5_distance_pct": 0.8,
        "volume_ratio_5d_20d": 0.84,
        "market_warning_level": 2,
    }

    decision = scoring.selective_setup_quality_lane_adjustment(stale_quiet)

    assert decision["adjustment"] <= -3.0
    assert any("低吸蓄势过久" in note for note in decision["notes"])
    assert any("均线过紧" in note for note in decision["notes"])


def test_backtest_experiment_top20_day_quality_gate_promotes_good_day_active_low_mid() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    active_acceptance = SignalScore(
        vt_symbol="ACTIVE.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.8,
        liquidity_score=82.0,
        risk_score=78.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "recent_limit_up_20d": True,
            "large_bull_count_20d": 4,
            "near_limit_up_count_20d": 1,
            "low_suction_launch_quality_bucket": "not_low_suction",
            "close_location_in_range": 0.48,
            "ma_convergence_pct": 10.0,
            "ma5_distance_pct": 1.2,
            "volume_ratio_5d_20d": 1.1,
        },
    )
    ordinary_candidate = SignalScore(
        vt_symbol="PLAIN.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=93.0,
        liquidity_score=82.0,
        risk_score=78.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "low_suction_launch_quality_bucket": "not_low_suction",
            "close_location_in_range": 0.54,
            "ma_convergence_pct": 7.0,
            "ma5_distance_pct": 1.0,
        },
    )
    day_fillers = [
        SignalScore(
            vt_symbol=f"GOOD{index:02d}.SZSE",
            trade_date=date(2026, 6, 12),
            signal_type=DRAGON_PULLBACK_STRATEGY_ID,
            total_score=90.0 - index * 0.1,
            liquidity_score=82.0,
            risk_score=78.0,
            entry_signal=True,
            evidence={
                "status": "ready",
                "entry_setup": "dragon_pullback",
                "setup_family": "dragon_pullback",
                "failed_rules": [],
                "recent_limit_up_20d": True,
                "large_bull_count_20d": 4,
                "low_suction_launch_quality_bucket": "not_low_suction",
                "close_location_in_range": 0.48,
                "ma_convergence_pct": 10.0,
                "ma5_distance_pct": 1.2,
                "volume_ratio_5d_20d": 1.1,
            },
        )
        for index in range(12)
    ]

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 12),
        BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0),
        score_candidates_for_day=lambda *_args, **_kwargs: [ordinary_candidate, active_acceptance, *day_fillers],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 12),
        BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            strict_entry=True,
            min_entry_score=76.0,
            enable_top20_day_quality_gate=True,
        ),
        score_candidates_for_day=lambda *_args, **_kwargs: [ordinary_candidate, active_acceptance, *day_fillers],
    )

    assert [row.vt_symbol for row in default_rows[:2]] == ["PLAIN.SZSE", "ACTIVE.SZSE"]
    assert [row.vt_symbol for row in experiment_rows[:2]] == ["ACTIVE.SZSE", "PLAIN.SZSE"]
    assert experiment_rows[0].evidence["top20_day_quality_adjustment"] > 0
    assert experiment_rows[0].evidence["top20_day_quality_day_profile"]["profile"] == "strong_top20_day"
    assert "top20_day_quality_adjustment" not in active_acceptance.evidence


def test_backtest_experiment_top20_day_quality_gate_demotes_bad_day_high_weak_launch() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    weak_high = SignalScore(
        vt_symbol="WEAK.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=94.0,
        liquidity_score=82.0,
        risk_score=78.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "recent_limit_up_20d": True,
            "large_bull_count_20d": 4,
            "low_suction_launch_quality_bucket": "high_close_launch",
            "close_location_in_range": 0.92,
            "ma_convergence_pct": 9.0,
            "ma5_distance_pct": 4.2,
            "volume_ratio_5d_20d": 1.1,
        },
    )
    protected_low_mid = SignalScore(
        vt_symbol="PROTECT.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.7,
        liquidity_score=82.0,
        risk_score=78.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "failed_rules": [],
            "recent_limit_up_20d": True,
            "large_bull_count_20d": 4,
            "low_suction_launch_quality_bucket": "not_low_suction",
            "close_location_in_range": 0.48,
            "ma_convergence_pct": 10.0,
            "ma5_distance_pct": 1.2,
            "volume_ratio_5d_20d": 1.1,
        },
    )
    weak_fillers = [
        SignalScore(
            vt_symbol=f"WEAK{index:02d}.SZSE",
            trade_date=date(2026, 6, 12),
            signal_type=DRAGON_PULLBACK_STRATEGY_ID,
            total_score=93.0 - index * 0.1,
            liquidity_score=82.0,
            risk_score=78.0,
            entry_signal=True,
            evidence={
                "status": "ready",
                "entry_setup": "dragon_pullback",
                "setup_family": "dragon_pullback",
                "failed_rules": [],
                "recent_limit_up_20d": True,
                "large_bull_count_20d": 4,
                "low_suction_launch_quality_bucket": "high_close_launch",
                "close_location_in_range": 0.90,
                "ma_convergence_pct": 8.0,
                "ma5_distance_pct": 4.0,
                "volume_ratio_5d_20d": 1.1,
            },
        )
        for index in range(10)
    ]

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 12),
        BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0),
        score_candidates_for_day=lambda *_args, **_kwargs: [weak_high, protected_low_mid, *weak_fillers],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 6, 12),
        BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            strict_entry=True,
            min_entry_score=76.0,
            enable_top20_day_quality_gate=True,
        ),
        score_candidates_for_day=lambda *_args, **_kwargs: [weak_high, protected_low_mid, *weak_fillers],
    )

    assert default_rows[0].vt_symbol == "WEAK.SZSE"
    assert experiment_rows[0].vt_symbol == "PROTECT.SZSE"
    weak_row = next(row for row in experiment_rows if row.vt_symbol == "WEAK.SZSE")
    assert weak_row.evidence["top20_day_quality_adjustment"] < 0
    assert weak_row.evidence["top20_day_quality_day_profile"]["profile"] == "weak_top20_day"


def test_backtest_experiment_pure_loss_weak_bucket_penalty_demotes_high_close_thin_launch() -> None:
    from alphaagent.server.services.backtest import scoring

    weak_bucket = {
        "low_suction_launch_quality_bucket": "thin_volume_launch",
        "close_location_in_range": 0.91,
        "volume_ratio_5d_20d": 0.72,
        "ma_convergence_pct": 4.2,
        "low_suction_days": 4,
        "market_warning_level": 2,
        "recent_limit_up_20d": False,
        "large_bull_count_20d": 0,
    }

    decision = scoring.pure_loss_weak_bucket_penalty(weak_bucket)

    assert decision["profile"] == "pure_loss_weak_bucket"
    assert decision["adjustment"] <= -4.0
    assert any("高位薄量启动" in note for note in decision["notes"])


def test_backtest_experiment_pure_loss_weak_bucket_penalty_relieves_active_low_acceptance() -> None:
    from alphaagent.server.services.backtest import scoring

    active_low_acceptance = {
        "low_suction_launch_quality_bucket": "unconfirmed_buildup",
        "close_location_in_range": 0.32,
        "volume_ratio_5d_20d": 1.1,
        "ma_convergence_pct": 4.8,
        "low_suction_days": 4,
        "recent_limit_up_20d": True,
        "large_bull_count_20d": 3,
    }

    decision = scoring.pure_loss_weak_bucket_penalty(active_low_acceptance)

    assert decision["adjustment"] == 0
    assert decision["profile"] == "neutral"


def test_backtest_experiment_low_suction_market_risk_penalty_downgrades_weak_market_launches() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    resilient_launch = SignalScore(
        vt_symbol="RESILIENT.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 4,
            "pullback_days": 6,
            "close_location_in_range": 0.64,
            "volume_ratio_5d_20d": 1.2,
            "low_suction_launch_confirmed": True,
            "dynamic_market_regime": "choppy_rotation",
            "recovery_state": "warming_confirmed",
            "market_breadth_score": 55,
            "market_warning_level": 0,
        },
    )
    weak_market_launch = SignalScore(
        vt_symbol="WEAKMARKET.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 6,
            "pullback_days": 13,
            "close_location_in_range": 0.72,
            "volume_ratio_5d_20d": 0.62,
            "low_suction_launch_confirmed": True,
            "dynamic_market_regime": "weak_defensive",
            "recovery_state": "none",
            "market_breadth_score": 32,
            "market_warning_level": 3,
        },
    )

    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0)
    experiment_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        enable_low_suction_market_risk_penalty=True,
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        default_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [weak_market_launch, resilient_launch],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        experiment_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [weak_market_launch, resilient_launch],
    )

    assert [row.vt_symbol for row in default_rows] == ["WEAKMARKET.SZSE", "RESILIENT.SZSE"]
    assert [row.vt_symbol for row in experiment_rows] == ["RESILIENT.SZSE", "WEAKMARKET.SZSE"]
    assert "low_suction_market_risk_penalty_adjustment" not in experiment_rows[0].evidence
    assert experiment_rows[1].evidence["low_suction_market_risk_penalty_adjustment"] < 0
    assert "low_suction_market_risk_penalty_adjustment" not in resilient_launch.evidence


def test_backtest_experiment_low_suction_market_risk_penalty_ignores_unconfirmed_low_suction() -> None:
    from alphaagent.server.services.backtest import scoring

    evidence = {
        "status": "ready",
        "entry_setup": "stealth_low_suction",
        "low_suction_launch_confirmed": False,
        "pullback_days": 13,
        "close_location_in_range": 0.72,
        "volume_ratio_5d_20d": 0.62,
        "dynamic_market_regime": "weak_defensive",
        "recovery_state": "none",
        "market_breadth_score": 32,
        "market_warning_level": 3,
    }

    assert scoring.low_suction_market_risk_penalty_adjustment(evidence) == 0


def test_low_suction_first_lift_bonus_only_rewards_clean_confirmed_lift() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    clean_lift = SignalScore(
        vt_symbol="CLEAN.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.5,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 5,
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "balanced_first_lift",
            "close_location_in_range": 0.62,
            "volume_ratio_5d_20d": 1.02,
            "ma_convergence_pct": 4.2,
            "latest_change_pct": 2.1,
            "ma5_distance_pct": 1.2,
            "ma10_distance_pct": 1.8,
            "return_60d": 28.0,
        },
    )
    plain_dragon = SignalScore(
        vt_symbol="DRAGON.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "failed_rules": [],
            "low_suction_days": 0,
        },
    )
    hot_lift = SignalScore(
        vt_symbol="HOT.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            **clean_lift.evidence,
            "close_location_in_range": 0.86,
            "low_suction_launch_quality_bucket": "high_close_launch",
        },
    )

    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0)
    experiment_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        enable_low_suction_first_lift_bonus=True,
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        default_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [hot_lift, plain_dragon, clean_lift],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        experiment_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [hot_lift, plain_dragon, clean_lift],
    )

    assert [row.vt_symbol for row in default_rows] == ["CLEAN.SZSE", "HOT.SZSE", "DRAGON.SZSE"]
    assert default_rows[0].evidence["candidate_quality_adjustment"] > 0
    assert default_rows[1].evidence["candidate_quality_adjustment"] < 0
    assert "成熟低吸无涨停高位确认不足降权" in default_rows[1].evidence["candidate_quality_notes"]
    assert [row.vt_symbol for row in experiment_rows] == ["CLEAN.SZSE", "HOT.SZSE", "DRAGON.SZSE"]
    assert experiment_rows[0].evidence["low_suction_first_lift_bonus_adjustment"] > 0
    assert "low_suction_first_lift_bonus_adjustment" not in experiment_rows[2].evidence
    assert "low_suction_first_lift_bonus_adjustment" not in experiment_rows[1].evidence
    assert "low_suction_first_lift_bonus_adjustment" not in clean_lift.evidence


def test_low_suction_lifecycle_ranking_prefers_clean_lift_without_rewarding_buildup() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    clean_lift = SignalScore(
        vt_symbol="CLEAN.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 6,
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "balanced_first_lift",
            "ma_convergence_pct": 2.4,
            "volume_ratio_5d_20d": 0.82,
            "close_location_in_range": 0.64,
            "ma5_distance_pct": 0.8,
        },
    )
    hot_lift = SignalScore(
        vt_symbol="HOT.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 5,
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "high_close_launch",
            "ma_convergence_pct": 7.2,
            "volume_ratio_5d_20d": 1.10,
            "close_location_in_range": 0.86,
            "ma5_distance_pct": 3.6,
        },
    )
    waiting_buildup = SignalScore(
        vt_symbol="WAIT.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=89.5,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            **clean_lift.evidence,
            "low_suction_launch_confirmed": False,
            "low_suction_launch_quality_bucket": "unconfirmed_buildup",
            "close_location_in_range": 0.50,
        },
    )

    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0)
    experiment_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        enable_low_suction_lifecycle_ranking=True,
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        default_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [hot_lift, clean_lift, waiting_buildup],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        experiment_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [hot_lift, clean_lift, waiting_buildup],
    )

    assert [row.vt_symbol for row in default_rows] == ["CLEAN.SZSE", "HOT.SZSE", "WAIT.SZSE"]
    assert default_rows[1].evidence["candidate_quality_adjustment"] < 0
    assert "成熟低吸无涨停高位确认不足降权" in default_rows[1].evidence["candidate_quality_notes"]
    assert [row.vt_symbol for row in experiment_rows] == ["CLEAN.SZSE", "WAIT.SZSE", "HOT.SZSE"]
    assert experiment_rows[0].evidence["low_suction_lifecycle_adjustment"] > 0
    assert "low_suction_lifecycle_adjustment" not in experiment_rows[1].evidence
    assert experiment_rows[2].evidence["low_suction_lifecycle_adjustment"] < 0
    assert "low_suction_lifecycle_adjustment" not in clean_lift.evidence


def test_backtest_experiment_market_adaptive_setup_weighting_rotates_by_market_profile() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    weak_low_suction = SignalScore(
        vt_symbol="LOW.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 5,
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "balanced_first_lift",
            "recent_limit_up_20d": True,
            "dynamic_market_regime": "weak_defensive",
            "market_warning_level": 3,
            "recovery_state": "none",
            "market_breadth_score": 32,
        },
    )
    weak_dragon = SignalScore(
        vt_symbol="DRAGON.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "failed_rules": [],
            "fresh_tail_buy": True,
            "tail_buy_repeat_days": 0,
            "low_suction_days": 0,
            "dynamic_market_regime": "weak_defensive",
            "market_warning_level": 3,
            "recovery_state": "none",
            "market_breadth_score": 32,
        },
    )
    strong_low_suction = SignalScore(
        vt_symbol="LOW.SZSE",
        trade_date=date(2026, 4, 2),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            **weak_low_suction.evidence,
            "dynamic_market_regime": "narrow_theme_bull",
            "market_warning_level": 0,
            "recovery_state": "warming_confirmed",
            "market_breadth_score": 60,
        },
    )
    strong_dragon = SignalScore(
        vt_symbol="DRAGON.SZSE",
        trade_date=date(2026, 4, 2),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            **weak_dragon.evidence,
            "dynamic_market_regime": "narrow_theme_bull",
            "market_warning_level": 0,
            "recovery_state": "warming_confirmed",
            "market_breadth_score": 60,
        },
    )

    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0)
    experiment_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        enable_market_adaptive_setup_weighting=True,
    )

    weak_default_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        default_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [weak_dragon, weak_low_suction],
    )
    weak_experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        experiment_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [weak_dragon, weak_low_suction],
    )
    strong_default_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 2),
        default_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [strong_low_suction, strong_dragon],
    )
    strong_experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 2),
        experiment_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [strong_low_suction, strong_dragon],
    )

    assert [row.vt_symbol for row in weak_default_rows] == ["DRAGON.SZSE", "LOW.SZSE"]
    assert [row.vt_symbol for row in weak_experiment_rows] == ["LOW.SZSE", "DRAGON.SZSE"]
    assert weak_experiment_rows[0].evidence["market_adaptive_setup_profile"] == "weak_defensive"
    assert weak_experiment_rows[0].evidence["market_adaptive_setup_adjustment"] > 0
    assert weak_experiment_rows[1].evidence["market_adaptive_setup_adjustment"] < 0
    assert [row.vt_symbol for row in strong_default_rows] == ["LOW.SZSE", "DRAGON.SZSE"]
    assert [row.vt_symbol for row in strong_experiment_rows] == ["DRAGON.SZSE", "LOW.SZSE"]
    assert strong_experiment_rows[0].evidence["market_adaptive_setup_profile"] == "mainline_active"
    assert "market_adaptive_setup_adjustment" not in weak_low_suction.evidence


def test_low_suction_false_launch_watch_gate_only_blocks_weak_unrecovered_lift() -> None:
    from alphaagent.server.services.backtest.scoring import classify_low_suction_false_launch_watch

    blocked = classify_low_suction_false_launch_watch(
        low_suction_days=4,
        launch_quality_bucket="weak_volume_launch",
        close_location_in_range=0.42,
        volume_ratio_5d_20d=0.76,
        market_warning_level=2,
        market_recovery_level=1,
        recent_limit_up_20d=False,
        theme_alignment="unknown",
    )
    allowed = classify_low_suction_false_launch_watch(
        low_suction_days=4,
        launch_quality_bucket="high_close_launch",
        close_location_in_range=0.82,
        volume_ratio_5d_20d=1.35,
        market_warning_level=1,
        market_recovery_level=2,
        recent_limit_up_20d=True,
        theme_alignment="aligned",
    )

    assert blocked["watch_only"] is True
    assert blocked["reason"] == "low_suction_false_launch_watch"
    assert allowed["watch_only"] is False


def test_low_suction_false_launch_watch_gate_removes_only_weak_market_launch() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    weak_launch = SignalScore(
        vt_symbol="600352.SSE",
        trade_date=date(2026, 3, 11),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 4,
            "low_suction_launch_quality_bucket": "weak_volume_launch",
            "low_suction_launch_confirmed": True,
            "close_location_in_range": 0.42,
            "volume_ratio_5d_20d": 0.76,
            "market_warning_level": 2,
            "market_recovery_level": 1,
            "stock_theme_alignment": "unknown",
        },
    )
    strong_launch = SignalScore(
        vt_symbol="002384.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 5,
            "low_suction_launch_quality_bucket": "balanced_first_lift",
            "low_suction_launch_confirmed": True,
            "close_location_in_range": 0.66,
            "volume_ratio_5d_20d": 1.18,
            "market_warning_level": 1,
            "market_recovery_level": 2,
            "stock_theme_alignment": "aligned",
            "recent_limit_up_20d": True,
        },
    )

    params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        enable_low_suction_false_launch_watch_gate=True,
    )
    rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        params,
        score_candidates_for_day=lambda *_args, **_kwargs: [weak_launch, strong_launch],
    )

    assert [row.vt_symbol for row in rows] == ["002384.SZSE"]


def test_backtest_experiment_can_require_balanced_low_suction_launch_quality() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    balanced_launch = SignalScore(
        vt_symbol="BALANCED.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 5,
            "pullback_days": 6,
            "close_location_in_range": 0.64,
            "volume_ratio_5d_20d": 1.05,
            "low_suction_launch_confirmed": True,
        },
    )
    unconfirmed_buildup = SignalScore(
        vt_symbol="WAITING.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=94.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 6,
            "pullback_days": 8,
            "close_location_in_range": 0.62,
            "volume_ratio_5d_20d": 0.9,
            "low_suction_launch_confirmed": False,
        },
    )
    late_launch = SignalScore(
        vt_symbol="LATE.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 6,
            "pullback_days": 13,
            "close_location_in_range": 0.64,
            "volume_ratio_5d_20d": 0.9,
            "low_suction_launch_confirmed": True,
        },
    )
    dragon_low_suction_unconfirmed = SignalScore(
        vt_symbol="DRAGON_WAITING.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "failed_rules": [],
            "low_suction_days": 4,
            "pullback_days": 8,
            "close_location_in_range": 0.62,
            "volume_ratio_5d_20d": 0.9,
            "low_suction_launch_confirmed": False,
        },
    )
    dragon_buy = SignalScore(
        vt_symbol="DRAGON.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=93.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={"status": "ready", "entry_setup": "dragon_pullback", "failed_rules": []},
    )

    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0)
    experiment_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        require_balanced_low_suction_launch_quality=True,
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        default_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [
            unconfirmed_buildup,
            dragon_buy,
            late_launch,
            dragon_low_suction_unconfirmed,
            balanced_launch,
        ],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        experiment_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [
            unconfirmed_buildup,
            dragon_buy,
            late_launch,
            dragon_low_suction_unconfirmed,
            balanced_launch,
        ],
    )

    assert [row.vt_symbol for row in default_rows] == [
        "DRAGON.SZSE",
        "WAITING.SZSE",
        "LATE.SZSE",
        "BALANCED.SZSE",
        "DRAGON_WAITING.SZSE",
    ]
    assert default_rows[1].evidence["candidate_quality_adjustment"] < 0
    assert default_rows[-1].evidence["candidate_quality_adjustment"] < 0
    assert [row.vt_symbol for row in experiment_rows] == ["DRAGON.SZSE", "BALANCED.SZSE"]


def test_backtest_experiment_can_require_low_suction_launch_for_low_suction_context() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    waiting_low_suction = SignalScore(
        vt_symbol="WAITING.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=94.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 6,
            "low_suction_launch_confirmed": False,
        },
    )
    dragon_overlap_waiting = SignalScore(
        vt_symbol="DRAGON_WAITING.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=93.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "failed_rules": [],
            "low_suction_days": 3,
            "low_suction_launch_confirmed": False,
        },
    )
    confirmed_low_suction = SignalScore(
        vt_symbol="CONFIRMED.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 5,
            "low_suction_launch_confirmed": True,
        },
    )
    normal_dragon = SignalScore(
        vt_symbol="DRAGON.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "failed_rules": [],
            "low_suction_days": 0,
            "low_suction_launch_confirmed": False,
        },
    )

    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, strict_entry=True, min_entry_score=76.0)
    experiment_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        strict_entry=True,
        min_entry_score=76.0,
        require_low_suction_launch_for_low_suction_context=True,
    )

    default_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        default_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [
            waiting_low_suction,
            dragon_overlap_waiting,
            confirmed_low_suction,
            normal_dragon,
        ],
    )
    experiment_rows = scoring.score_day(
        None,
        {},
        date(2026, 4, 1),
        experiment_params,
        score_candidates_for_day=lambda *_args, **_kwargs: [
            waiting_low_suction,
            dragon_overlap_waiting,
            confirmed_low_suction,
            normal_dragon,
        ],
    )

    assert [row.vt_symbol for row in default_rows] == ["WAITING.SZSE", "CONFIRMED.SZSE", "DRAGON_WAITING.SZSE", "DRAGON.SZSE"]
    assert default_rows[0].evidence["candidate_quality_adjustment"] < 0
    assert default_rows[2].evidence["candidate_quality_adjustment"] < 0
    assert [row.vt_symbol for row in experiment_rows] == ["CONFIRMED.SZSE", "DRAGON.SZSE"]


def test_stealth_low_suction_uses_setup_specific_entry_threshold() -> None:
    from alphaagent.server.services.quant import screening_payloads

    low_suction_buy = SignalScore(
        vt_symbol="002208.SZSE",
        trade_date=date(2025, 9, 24),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=74.8,
        liquidity_score=60.0,
        risk_score=63.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "setup_type": "stealth_low_suction",
            "entry_setup": "stealth_low_suction",
            "dragon_state": "LOW_SUCTION_BUILDUP",
            "failed_rules": [],
            "low_suction_days": 5,
            "low_suction_buildup_score": 100.0,
            "stealth_low_suction_score": 99.0,
            "ma_convergence_pct": 2.26,
            "volume_ratio_5d_20d": 1.42,
            "ma20_distance_pct": 1.49,
            "low_suction_launch_confirmed": True,
            "close_price": 6.86,
        },
    )

    row = screening_payloads.symbol_signal_row(low_suction_buy, min_entry_score=76.0)

    assert row["action"] == "BUY"
    assert row["failed_rules"] == []
    assert row["effective_min_entry_score"] == 74.5
    assert row["entry_threshold_reason"] == "stealth_low_suction"


def test_stealth_low_suction_threshold_requires_strict_structure() -> None:
    from alphaagent.server.services.quant import screening_payloads

    weak_low_suction = SignalScore(
        vt_symbol="002208.SZSE",
        trade_date=date(2025, 9, 24),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=74.8,
        liquidity_score=60.0,
        risk_score=63.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "setup_type": "stealth_low_suction",
            "entry_setup": "stealth_low_suction",
            "dragon_state": "LOW_SUCTION_BUILDUP",
            "failed_rules": [],
            "low_suction_days": 3,
            "low_suction_buildup_score": 100.0,
            "stealth_low_suction_score": 99.0,
            "ma_convergence_pct": 2.26,
            "volume_ratio_5d_20d": 1.42,
            "ma20_distance_pct": 1.49,
        },
    )
    risky_low_suction = SignalScore(
        vt_symbol="002208.SZSE",
        trade_date=date(2025, 9, 24),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=74.8,
        liquidity_score=60.0,
        risk_score=63.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "setup_type": "stealth_low_suction",
            "entry_setup": "stealth_low_suction",
            "dragon_state": "LOW_SUCTION_BUILDUP",
            "failed_rules": ["ma20_broken"],
            "low_suction_days": 5,
            "low_suction_buildup_score": 100.0,
            "stealth_low_suction_score": 99.0,
            "ma_convergence_pct": 2.26,
            "volume_ratio_5d_20d": 1.42,
            "ma20_distance_pct": -6.0,
        },
    )

    weak_row = screening_payloads.symbol_signal_row(weak_low_suction, min_entry_score=76.0)
    risky_row = screening_payloads.symbol_signal_row(risky_low_suction, min_entry_score=76.0)

    assert weak_row["action"] == "WATCH"
    assert weak_row["failed_rules"] == ["total_score"]
    assert weak_row["effective_min_entry_score"] == 76.0
    assert risky_row["action"] == "WATCH"
    assert "total_score" in risky_row["failed_rules"]
    assert "ma20_broken" in risky_row["failed_rules"]
    assert "low_suction_launch_unconfirmed" not in risky_row["failed_rules"]


def test_symbol_signal_row_marks_low_suction_launch_as_key_entry_only() -> None:
    from alphaagent.server.services.quant import screening_payloads

    buildup = SignalScore(
        vt_symbol="002384.SZSE",
        trade_date=date(2026, 3, 31),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=74.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "setup_type": "stealth_low_suction",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 4,
            "low_suction_launch_confirmed": False,
        },
    )
    launch = SignalScore(
        vt_symbol="002384.SZSE",
        trade_date=date(2026, 4, 1),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=78.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "setup_type": "stealth_low_suction",
            "entry_setup": "stealth_low_suction",
            "failed_rules": [],
            "low_suction_days": 5,
            "low_suction_buildup_score": 100.0,
            "stealth_low_suction_score": 96.0,
            "ma_convergence_pct": 3.0,
            "volume_ratio_5d_20d": 1.1,
            "ma20_distance_pct": 1.0,
            "low_suction_launch_confirmed": True,
        },
    )

    buildup_row = screening_payloads.symbol_signal_row(buildup, min_entry_score=76.0)
    launch_row = screening_payloads.symbol_signal_row(launch, min_entry_score=76.0)

    assert buildup_row["signal_label"] == "低吸蓄势观察"
    assert buildup_row["signal_role"] == "watch"
    assert buildup_row["key_entry_signal"] is False
    assert launch_row["action"] == "BUY"
    assert launch_row["signal_label"] == "低吸启动买点"
    assert launch_row["signal_role"] == "key_buy"
    assert launch_row["key_entry_signal"] is True


def test_symbol_signal_row_marks_raw_entry_with_failed_rules_as_watch() -> None:
    from alphaagent.server.services.quant import screening_payloads

    weak_buy = SignalScore(
        vt_symbol="600004.SSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=73.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "dragon_state": "LOW_SUCTION_BUILDUP",
            "failed_rules": [],
        },
    )

    row = screening_payloads.symbol_signal_row(weak_buy, min_entry_score=76.0)

    assert row["entry_signal"] is True
    assert row["raw_entry_signal"] is True
    assert row["executable_entry_signal"] is False
    assert row["action"] == "WATCH"
    assert row["failed_rules"] == ["total_score"]


def test_candidate_signal_display_keeps_highest_score_buy_per_cluster() -> None:
    from alphaagent.server.services.quant.symbol_diagnostics import display_candidate_markers

    rows = [
        {"trade_date": date(2026, 5, 12), "action": "BUY", "total_score": 76.0, "signal_label": "低吸蓄势观察"},
        {"trade_date": date(2026, 5, 14), "action": "BUY", "total_score": 84.0, "signal_label": "低吸启动买点"},
        {"trade_date": date(2026, 5, 15), "action": "BUY", "total_score": 81.0, "signal_label": "龙回头买点"},
        {"trade_date": date(2026, 5, 20), "action": "WATCH", "total_score": 90.0, "failed_rules": ["ma20_broken"]},
    ]

    markers = display_candidate_markers(rows, cluster_days=3)

    assert [item["trade_date"] for item in markers] == [date(2026, 5, 14), date(2026, 5, 20)]
    assert markers[0]["display_kind"] == "buy"
    assert markers[0]["cluster_size"] == 3
    assert markers[1]["display_kind"] == "rejected_buy"


def test_candidate_signal_display_waits_for_low_suction_launch_marker() -> None:
    from alphaagent.server.services.quant.symbol_diagnostics import display_candidate_markers

    rows = [
        {
            "trade_date": date(2026, 3, 27),
            "action": "BUY",
            "total_score": 76.0,
            "key_entry_signal": False,
            "signal_role": "watch",
            "evidence": {
                "setup_type": "stealth_low_suction",
                "low_suction_days": 3,
                "low_suction_launch_confirmed": False,
            },
        },
        {
            "trade_date": date(2026, 4, 1),
            "action": "BUY",
            "total_score": 82.0,
            "key_entry_signal": False,
            "signal_role": "watch",
            "evidence": {
                "setup_type": "stealth_low_suction",
                "low_suction_days": 5,
                "low_suction_launch_confirmed": False,
            },
        },
        {
            "trade_date": date(2026, 4, 8),
            "action": "BUY",
            "total_score": 80.0,
            "key_entry_signal": True,
            "signal_role": "key_buy",
            "evidence": {
                "setup_type": "stealth_low_suction",
                "low_suction_days": 6,
                "low_suction_launch_confirmed": True,
            },
        },
    ]

    markers = display_candidate_markers(rows)

    assert [item["trade_date"] for item in markers] == [date(2026, 4, 8)]
    assert markers[0]["cluster_start_date"] == "2026-03-27"
    assert markers[0]["cluster_end_date"] == "2026-04-08"
    assert markers[0]["cluster_size"] == 3


def test_candidate_signal_display_includes_low_suction_context_before_launch() -> None:
    from alphaagent.server.services.quant.symbol_diagnostics import display_candidate_markers

    rows = [
        {
            "trade_date": date(2026, 3, 31),
            "action": "WATCH",
            "total_score": 76.26,
            "entry_signal": False,
            "raw_entry_signal": False,
            "key_entry_signal": False,
            "signal_role": "watch",
            "failed_rules": ["reclaim_confirmation"],
            "evidence": {
                "setup_type": "support_accepted",
                "low_suction_days": 3,
                "low_suction_launch_confirmed": False,
                "failed_rules": ["reclaim_confirmation"],
            },
        },
        {
            "trade_date": date(2026, 4, 1),
            "action": "BUY",
            "total_score": 90.89,
            "key_entry_signal": True,
            "signal_role": "key_buy",
            "evidence": {
                "setup_type": "stealth_low_suction",
                "low_suction_days": 4,
                "low_suction_launch_confirmed": True,
            },
        },
    ]

    markers = display_candidate_markers(rows)

    assert [item["trade_date"] for item in markers] == [date(2026, 4, 1)]
    assert markers[0]["cluster_size"] == 2
    assert markers[0]["cluster_start_date"] == "2026-03-31"


def test_candidate_signal_display_drops_low_suction_buildup_without_launch() -> None:
    from alphaagent.server.services.quant.symbol_diagnostics import display_candidate_markers

    rows = [
        {
            "trade_date": date(2026, 3, 27),
            "action": "BUY",
            "total_score": 76.0,
            "key_entry_signal": False,
            "signal_role": "watch",
            "evidence": {
                "setup_type": "stealth_low_suction",
                "low_suction_days": 3,
                "low_suction_launch_confirmed": False,
            },
        },
        {
            "trade_date": date(2026, 4, 1),
            "action": "BUY",
            "total_score": 82.0,
            "key_entry_signal": False,
            "signal_role": "watch",
            "evidence": {
                "setup_type": "stealth_low_suction",
                "low_suction_days": 5,
                "low_suction_launch_confirmed": False,
            },
        },
    ]

    assert display_candidate_markers(rows) == []


def test_candidate_signal_display_drops_pure_observation_watch_rows() -> None:
    from alphaagent.server.services.quant.symbol_diagnostics import display_candidate_markers

    rows = [
        {
            "trade_date": date(2026, 5, 12),
            "action": "WATCH",
            "total_score": 88.0,
            "raw_entry_signal": False,
            "failed_rules": [],
            "signal_label": "低吸蓄势观察",
        },
        {
            "trade_date": date(2026, 5, 13),
            "action": "WATCH",
            "total_score": 73.0,
            "raw_entry_signal": True,
            "failed_rules": ["total_score"],
            "signal_label": "观察",
        },
    ]

    markers = display_candidate_markers(rows, cluster_days=3)

    assert [item["trade_date"] for item in markers] == [date(2026, 5, 13)]
    assert markers[0]["display_kind"] == "rejected_buy"


def test_candidate_signal_display_excludes_support_divergence_research_from_buy_and_rejected() -> None:
    from alphaagent.server.services.quant.symbol_diagnostics import display_candidate_markers

    rows = [
        {
            "trade_date": date(2026, 6, 12),
            "action": "WATCH",
            "total_score": 90.27,
            "raw_entry_signal": False,
            "executable_entry_signal": False,
            "research_entry_signal": True,
            "failed_rules": ["reclaim_confirmation"],
            "signal_label": "支撑分歧低吸买点",
            "evidence": {
                "support_divergence_entry_profile": "high_level_support_divergence",
                "support_divergence_entry_observation_only": True,
            },
        },
    ]

    assert display_candidate_markers(rows) == []


def test_candidate_signal_display_excludes_strong_trend_ma_pullback_research_from_buy_and_rejected() -> None:
    from alphaagent.server.services.quant.symbol_diagnostics import display_candidate_markers

    rows = [
        {
            "trade_date": date(2026, 5, 25),
            "action": "WATCH",
            "total_score": 78.49,
            "raw_entry_signal": False,
            "executable_entry_signal": False,
            "research_entry_signal": True,
            "failed_rules": ["pullback_too_short"],
            "signal_label": "强趋势均线回踩研究买点",
            "evidence": {
                "strong_trend_ma_pullback_entry_profile": "strong_trend_intraday_ma_pullback",
                "strong_trend_ma_pullback_entry_observation_only": True,
            },
        },
    ]

    assert display_candidate_markers(rows) == []


def test_symbol_signal_payload_counts_only_executable_buy() -> None:
    from alphaagent.server.services.quant import symbol_quant_state

    rows = [
        {
            "trade_date": "2026-06-12",
            "vt_symbol": "600004.SSE",
            "total_score": 73.0,
            "entry_signal": True,
            "executable_entry_signal": False,
            "action": "WATCH",
        },
        {
            "trade_date": "2026-06-11",
            "vt_symbol": "002384.SZSE",
            "total_score": 88.0,
            "entry_signal": True,
            "executable_entry_signal": True,
            "action": "BUY",
        },
    ]

    payload = symbol_quant_state._signal_payload(rows)

    assert payload["status"] == "buy_signal"
    assert payload["entry_signal_count"] == 1
    assert payload["latest"]["action"] == "WATCH"
    assert payload["latest_entry_signal"]["action"] == "BUY"


def test_backtest_persisted_signal_row_restores_executable_entry_only() -> None:
    from alphaagent.server.services.backtest import engine

    score = engine._signal_score_from_row(
        {
            "trade_date": date(2026, 6, 12),
            "vt_symbol": "600004.SSE",
            "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
            "strategy_version": "0.1.8",
            "signal_type": DRAGON_PULLBACK_STRATEGY_ID,
            "total_score": 80.0,
            "relative_strength_score": 70.0,
            "washout_score": 70.0,
            "trend_quality_score": 70.0,
            "sector_mainline_score": 70.0,
            "financial_improvement_score": 70.0,
            "liquidity_score": 80.0,
            "risk_score": 80.0,
            "entry_signal": True,
            "risk_level": "LOW",
            "evidence": {"status": "ready", "failed_rules": ["strong_leg"]},
        },
        min_entry_score=76.0,
    )

    assert score.entry_signal is False


def test_dragon_pullback_rejects_too_early_pullback_before_low_suction_window() -> None:
    start = date(2026, 1, 1)
    closes = [20 + index * 0.12 for index in range(74)]
    closes.extend([29.0, 31.9, 35.1, 38.6, 42.1, 39.4])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 0.99,
            high_price=close * 1.025,
            low_price=close * 0.975,
            close_price=close,
            volume=1_800_000 if index < 74 else 1_050_000,
            turnover=520_000_000,
            change_pct=2.0 if index < 74 else -1.0,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback(
        "002428.SZSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-2.0,
        sector_score=82.0,
        financial_score=65.0,
        fund_flow_score=70.0,
        hot_rank_score=70.0,
        lhb_score=65.0,
    )

    assert score.evidence["pullback_days"] < 3
    assert "pullback_too_short" in score.evidence["failed_rules"]
    assert score.entry_signal is False


def test_dragon_pullback_allows_wide_ma_pullback_when_close_is_not_chasing() -> None:
    start = date(2026, 1, 1)
    closes = [18 + index * 0.10 for index in range(70)]
    closes.extend([55.0, 60.0, 67.0, 74.0, 82.0, 76.0, 72.0, 69.0, 66.0, 67.4])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 0.99,
            high_price=close * 1.025,
            low_price=close * 0.98,
            close_price=close,
            volume=1_500_000 if index < 70 else 900_000,
            turnover=480_000_000,
            change_pct=2.2 if index < 70 else 2.1,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback(
        "605389.SSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-1.0,
        sector_score=50.0,
        financial_score=50.0,
        fund_flow_score=50.0,
        hot_rank_score=50.0,
        lhb_score=50.0,
    )

    assert score.evidence["ma_convergence_pct"] > 16
    assert score.evidence["low_suction_days"] < 2
    assert score.evidence["close_location_in_range"] < 0.70
    assert "ma_convergence_too_wide_without_low_suction" not in score.evidence["failed_rules"]


def test_dragon_pullback_rejects_hot_wide_ma_without_low_suction_near_ma20() -> None:
    start = date(2026, 1, 1)
    closes = [22 + index * 0.08 for index in range(70)]
    closes.extend([40.0, 44.0, 49.0, 56.0, 63.0, 60.0, 57.0, 55.0, 53.5, 54.8])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 0.99,
            high_price=close * (1.025 if index < len(closes) - 1 else 1.002),
            low_price=close * 0.98,
            close_price=close,
            volume=1_500_000 if index < 70 else 900_000,
            turnover=480_000_000,
            change_pct=2.0 if index < 70 else 2.4,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback(
        "605389.SSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-1.0,
        sector_score=50.0,
        financial_score=50.0,
        fund_flow_score=50.0,
        hot_rank_score=50.0,
        lhb_score=50.0,
    )

    assert score.evidence["ma_convergence_pct"] > 14
    assert score.evidence["return_20d"] >= 25
    assert score.evidence["low_suction_days"] < 2
    assert "ma_convergence_too_wide_without_low_suction" in score.evidence["failed_rules"]
    assert score.entry_signal is False


def test_dragon_pullback_exposes_repeated_stretched_dragon_without_low_suction_risk() -> None:
    start = date(2026, 1, 1)
    closes = [18 + index * 0.05 for index in range(70)]
    closes.extend([24.0, 27.0, 30.0, 33.0, 36.0, 39.0, 42.0, 38.0, 36.0, 35.0, 35.8, 36.8])
    changes = []
    for index in range(len(closes)):
        if index < 70:
            changes.append(0.4)
        elif index <= 76:
            changes.append(9.8)
        elif index < 80:
            changes.append(-3.0)
        elif index == 80:
            changes.append(2.8)
        else:
            changes.append(2.2)
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * (0.985 if index >= 80 else 0.99),
            high_price=close * (1.012 if index >= 80 else 1.025),
            low_price=close * (0.975 if index >= 80 else 0.98),
            close_price=close,
            volume=1_500_000 if index < 70 else 900_000,
            turnover=480_000_000,
            change_pct=changes[index],
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback(
        "002119.SZSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-1.0,
        sector_score=85.0,
        financial_score=60.0,
        fund_flow_score=80.0,
        hot_rank_score=80.0,
        lhb_score=70.0,
    )

    assert score.evidence["return_20d"] >= 40
    assert score.evidence["ma_convergence_pct"] >= 18
    assert score.evidence["low_suction_days"] == 0
    assert score.evidence["near_limit_up_count_20d"] >= 3
    assert score.evidence["fresh_tail_buy"] is False
    assert score.evidence["tail_buy_repeat_days"] >= 1
    assert score.evidence["entry_setup"] == "dragon_pullback"
    assert score.evidence["low_suction_launch_confirmed"] is False
    assert score.evidence["early_dragon_pullback_risk"] is True
    assert "early_dragon_pullback_risk" not in score.evidence["failed_rules"]


def test_dragon_pullback_does_not_hard_reject_tail_reversal_experiment() -> None:
    start = date(2026, 1, 1)
    closes = [16 + index * 0.09 for index in range(70)]
    closes.extend([34.0, 38.0, 42.5, 48.0, 54.0, 50.0, 47.0, 44.0, 42.5, 43.2])
    bars: list[Bar] = []
    for index, close in enumerate(closes):
        is_last = index == len(closes) - 1
        bars.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=close * (1.04 if is_last else 0.99),
                high_price=close * (1.105 if is_last else 1.025),
                low_price=close * (0.99 if is_last else 0.98),
                close_price=close,
                volume=2_200_000 if is_last else 1_200_000,
                turnover=680_000_000,
                change_pct=1.8 if is_last else 2.0,
            )
        )

    score = score_dragon_pullback(
        "002384.SZSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-1.0,
        sector_score=80.0,
        financial_score=60.0,
    )

    assert score.evidence["ma_convergence_pct"] >= 14
    assert score.evidence["return_20d"] >= 35
    assert score.evidence["low_suction_days"] < 2
    assert score.evidence["close_location_in_range"] <= 0.35
    assert "tail_reversal_risk" not in score.evidence["failed_rules"]


def test_dragon_pullback_preserves_low_suction_buildup() -> None:
    start = date(2026, 1, 1)
    closes = [22 + index * 0.04 for index in range(50)]
    closes.extend([28 + index * 0.06 for index in range(20)])
    closes.extend([30.0, 30.2, 30.1, 30.3, 30.2, 30.25, 30.3, 30.35, 30.4, 30.45])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 0.992,
            high_price=close * 1.018,
            low_price=close * 0.982,
            close_price=close,
            volume=1_500_000 if index < 70 else 900_000,
            turnover=520_000_000,
            change_pct=0.8,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback(
        "002384.SZSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-1.0,
        sector_score=80.0,
        financial_score=60.0,
    )

    assert score.evidence["low_suction_days"] >= 2
    assert "tail_reversal_risk" not in score.evidence["failed_rules"]


def test_dragon_pullback_detects_stealth_low_suction_as_separate_setup() -> None:
    start = date(2026, 1, 1)
    closes = [18 + index * 0.035 for index in range(70)]
    closes.extend([20.15, 20.32, 20.18, 20.42, 20.35, 20.55, 20.48, 20.62, 20.70, 20.82])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 0.995,
            high_price=close * 1.018,
            low_price=close * 0.982,
            close_price=close,
            volume=1_400_000 if index < 70 else 850_000,
            turnover=420_000_000,
            change_pct=0.6 if index < 70 else 0.8,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback(
        "002747.SZSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-1.0,
        sector_score=50.0,
        financial_score=50.0,
        fund_flow_score=50.0,
        hot_rank_score=50.0,
        lhb_score=50.0,
    )

    assert score.entry_signal is True
    assert score.evidence["setup_type"] == "stealth_low_suction"
    assert score.evidence["entry_setup"] == "stealth_low_suction"
    assert score.evidence["low_suction_days"] >= 4
    assert score.evidence["stealth_low_suction_score"] >= 78
    assert "fresh_stealth_low_suction" in score.evidence
    assert "strong_leg" not in score.evidence["failed_rules"]
    assert "pullback_too_late" not in score.evidence["failed_rules"]


def test_dragon_pullback_routes_bottom_reclaim_inside_default_strategy() -> None:
    closes = [55 + index * 0.02 for index in range(60)]
    closes.extend([56, 55, 54, 53, 52, 51, 50, 49, 48, 47, 46, 45, 44, 43.5, 43, 42.5, 42, 41.8, 41.6, 41.5])
    closes.extend([41.8, 42.2, 42.6, 43.0, 43.4])
    bars = _bars_from_closes_for_strategy_lane(closes, start=date(2026, 1, 1))

    score = score_dragon_pullback(
        "002407.SZSE",
        bars,
        bars[-1].trade_date,
        sector_score=70.0,
        financial_score=60.0,
        fund_flow_score=60.0,
        hot_rank_score=60.0,
        lhb_score=60.0,
    )

    assert score.entry_signal is True
    assert score.evidence["entry_setup"] == "oversold_rebound_start"
    assert score.evidence["rebound_subtype"] == "bottom_reclaim"
    assert score.evidence["bottom_reclaim"] is True
    assert score.evidence["selected_score_lane"] == "oversold_rebound_start"
    assert score.evidence["setup_scores"]["oversold_rebound"] > score.evidence["setup_scores"]["dragon_pullback"]
    assert score.evidence["setup_scores"]["oversold_rebound"] > score.evidence["setup_scores"]["stealth_low_suction"]
    assert score.evidence["failed_rules"] == []


def test_dragon_pullback_routes_secondary_breakout_confirm_inside_default_strategy() -> None:
    closes = [48 + index * 0.01 for index in range(60)]
    closes.extend([48, 47, 46, 45, 44, 43, 42, 41, 40, 39, 38, 37.5, 37, 36.7, 36.4, 36.2, 36.0])
    closes.extend([36.4, 36.2, 36.6, 37.2, 36.8, 37.4, 39.4])
    bars = _bars_from_closes_for_strategy_lane(closes, start=date(2026, 1, 1))

    score = score_dragon_pullback(
        "603260.SSE",
        bars,
        bars[-1].trade_date,
        sector_score=70.0,
        financial_score=60.0,
        fund_flow_score=60.0,
        hot_rank_score=60.0,
        lhb_score=60.0,
    )

    assert score.entry_signal is True
    assert score.evidence["entry_setup"] == "oversold_rebound_start"
    assert score.evidence["rebound_subtype"] == "secondary_breakout_confirm"
    assert score.evidence["secondary_breakout_confirm"] is True
    assert score.evidence["bottom_reclaim"] is False
    assert score.evidence["selected_score_lane"] == "oversold_rebound_start"
    assert score.evidence["setup_scores"]["oversold_rebound"] > score.evidence["setup_scores"]["dragon_pullback"]
    assert score.evidence["failed_rules"] == []


def test_dragon_pullback_routes_deep_cycle_secondary_breakout_when_20d_drawdown_is_shallow() -> None:
    start = date(2026, 1, 1)
    closes = [55.0 - index * 0.14 for index in range(70)]
    closes.extend(
        [
            44.4,
            43.9,
            43.2,
            42.6,
            41.8,
            41.0,
            40.2,
            39.6,
            39.0,
            38.4,
            37.8,
            37.2,
            36.7,
            36.2,
            35.8,
            35.5,
            36.3,
            37.2,
            35.7,
            39.3,
        ]
    )
    bars: list[Bar] = []
    previous = closes[0]
    for index, close in enumerate(closes):
        change_pct = (close / previous - 1) * 100 if index else 0.0
        bars.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=close,
                high_price=close,
                low_price=close * 0.985,
                close_price=close,
                volume=1_100_000 if index >= len(closes) - 5 else 1_000_000,
                turnover=close * 100_000_000,
                change_pct=change_pct,
            )
        )
        previous = close

    score = score_dragon_pullback(
        "603260.SSE",
        bars,
        bars[-1].trade_date,
        sector_score=70.0,
        financial_score=60.0,
        fund_flow_score=60.0,
        hot_rank_score=60.0,
        lhb_score=60.0,
    )

    assert score.entry_signal is True
    assert score.evidence["entry_setup"] == "oversold_rebound_start"
    assert score.evidence["rebound_subtype"] == "secondary_breakout_confirm"
    assert score.evidence["secondary_breakout_confirm"] is True
    assert score.evidence["deep_cycle_secondary_breakout_reversal"] is True
    assert -12.0 < score.evidence["drawdown_from_20d_high_pct"] <= -10.5
    assert score.evidence["max_drawdown_60d"] <= -24.0
    assert score.evidence["return_20d"] <= -8.0
    assert score.evidence["return_60d"] <= -12.0
    assert score.evidence["failed_rules"] == []


def test_dragon_pullback_routes_deep_low_absorption_reversal_inside_default_strategy() -> None:
    closes = [50 + index * 0.01 for index in range(60)]
    closes.extend([50, 49, 48, 47, 46, 45, 44, 43, 42, 41, 40, 39, 38, 37.5, 37, 36.5, 36, 35.5, 35, 32.5])
    bars = _bars_from_closes_for_strategy_lane(closes, start=date(2026, 1, 1))

    score = score_dragon_pullback(
        "688711.SSE",
        bars,
        bars[-1].trade_date,
        sector_score=60.0,
        financial_score=55.0,
        fund_flow_score=55.0,
        hot_rank_score=55.0,
        lhb_score=55.0,
    )

    assert score.entry_signal is True
    assert score.evidence["entry_setup"] == "oversold_rebound_start"
    assert score.evidence["rebound_subtype"] == "deep_low_absorption_reversal"
    assert score.evidence["deep_low_absorption_reversal"] is True
    assert score.evidence["selected_score_lane"] == "oversold_rebound_start"
    assert score.evidence["latest_change_pct"] <= -5.0
    assert score.evidence["close_location_in_range"] <= 0.25
    assert score.evidence["near_limit_up_count_20d"] == 0
    assert 0.5 <= score.evidence["latest_volume_ratio_20d"] <= 1.8
    assert score.evidence["failed_rules"] == []


def test_stealth_low_suction_accumulates_before_first_lift_with_ma5_below_ma10() -> None:
    start = date(2026, 1, 1)
    closes = [50 + index * 0.18 for index in range(70)]
    closes.extend([64.0, 68.0, 72.0, 76.0, 82.0, 77.0, 73.0, 70.5, 69.0, 68.5])
    closes.extend([69.5, 69.0, 68.7, 68.2, 67.9, 67.6, 67.8, 67.7, 68.1, 69.4])
    bars: list[Bar] = []
    for index, close in enumerate(closes):
        is_lift = index == len(closes) - 1
        bars.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=close * (0.99 if is_lift else 0.995),
                high_price=close * (1.005 if is_lift else 1.012),
                low_price=close * (0.985 if is_lift else 0.982),
                close_price=close,
                volume=1_600_000 if index < 70 else (650_000 if not is_lift else 820_000),
                turnover=520_000_000,
                change_pct=2.4 if is_lift else (-0.4 if index >= 72 else 1.2),
            )
        )

    setup_day = score_dragon_pullback(
        "002384.SZSE",
        bars[:-1],
        bars[-2].trade_date,
        index_return_20d=-1.0,
        sector_score=80.0,
        financial_score=60.0,
    )
    lift_day = score_dragon_pullback(
        "002384.SZSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-1.0,
        sector_score=80.0,
        financial_score=60.0,
    )

    assert setup_day.evidence["ma5_vs_ma10_pct"] < 0
    assert setup_day.entry_signal is True
    assert setup_day.evidence["low_suction_days"] >= 4
    assert setup_day.evidence["low_suction_launch_confirmed"] is False
    assert setup_day.evidence["low_suction_launch_bonus"] == 0.0
    assert "weak_rebound_ma5_below_ma10" not in setup_day.evidence["failed_rules"]
    assert lift_day.entry_signal is True
    assert lift_day.evidence["setup_type"] == "stealth_low_suction"
    assert lift_day.evidence["low_suction_days"] >= setup_day.evidence["low_suction_days"]
    assert lift_day.evidence["low_suction_launch_confirmed"] is True
    assert 1.2 <= lift_day.evidence["low_suction_launch_bonus"] <= 1.6
    assert lift_day.total_score > lift_day.evidence["setup_scores"]["stealth_low_suction"]
    assert any(row["name"] == "低吸启动确认" for row in lift_day.evidence["score_breakdown"])
    assert setup_day.evidence["low_suction_stage"] in {"buildup_waiting_lift", "mature_buildup_waiting_lift"}
    assert "等待上拉" in setup_day.evidence["low_suction_stage_label"]
    assert setup_day.evidence["low_suction_launch_quality_bucket"] == "unconfirmed_buildup"
    assert lift_day.evidence["low_suction_stage"] in {"balanced_first_lift", "confirmed_lift", "late_confirmed_lift"}
    assert "低吸" in lift_day.evidence["low_suction_stage_label"]
    assert lift_day.evidence["low_suction_launch_quality_label"] in {"低吸首个均衡上拉", "其他低吸确认", "低吸启动回踩过久"}
    assert "pullback_too_late" not in lift_day.evidence["failed_rules"]


def test_low_suction_strong_launch_counts_as_small_bonus_buy() -> None:
    from alphaagent.server.services.quant.strategies import dragon_pullback

    features = dragon_pullback.DragonFeatures(
        latest=Bar(
            trade_date=date(2026, 6, 15),
            open_price=222.47,
            high_price=239.31,
            low_price=215.39,
            close_price=239.31,
            volume=853_771,
            turnover=19_726_067_200,
            change_pct=10.0,
        ),
        closes=[210.99, 217.55, 239.31],
        highs=[221.68, 226.8, 239.31],
        lows=[205.01, 214.0, 215.39],
        volumes=[654_865, 795_949, 853_771],
        turnovers=[13_984_152_000, 17_464_684_000, 19_726_067_200],
        return_5d=11.0,
        return_20d=22.0,
        return_60d=45.0,
        max_drawdown_60d=-16.0,
        ma5=220.9,
        ma10=221.1,
        ma20=219.0,
        ma30=218.5,
        ma60=200.0,
        ma5_prev=217.0,
        ma10_prev=217.2,
        ma5_distance_pct=8.33,
        ma10_distance_pct=8.20,
        ma20_distance_pct=9.30,
        ma5_vs_ma10_pct=-0.09,
        ma10_vs_ma20_pct=0.96,
        ma20_vs_ma30_pct=0.23,
        ma_convergence_pct=2.54,
        low_suction_days=4,
        support_hold_days=6,
        ma5_slope_pct=1.80,
        volume5=993_000,
        volume20=1_155_000,
        volume_ratio=0.86,
        turnover20=18_000_000_000,
        turnover_percentile_60d=0.62,
        pivot_high_20d=239.31,
        pivot_high_index_from_end=0,
        drawdown_from_pivot_pct=0.0,
        pullback_days=4,
        close_location_in_range=1.0,
        upper_shadow_pct=0.0,
        lower_shadow_pct=3.0,
        body_pct=7.5,
        large_bull_count_20d=2,
        near_limit_up_count_20d=1,
        consecutive_bull_closes=1,
        upward_gap_in_leg=False,
        persistent_volume_expansion=False,
        latest_change_pct=10.0,
        weekly_top_fractal_risk=False,
        spiky_churn_risk=False,
        volume_stall_risk=False,
        high_position_volume_stall_risk=False,
        key_support_break_risk=False,
        illiquid_forgotten_risk=False,
        high_level_sideways_days=0,
        high_level_sideways_distribution_risk=False,
    )

    failed_rules = dragon_pullback._failed_rules(
        features,
        strong_leg=80.0,
        pullback=82.0,
        support=56.0,
        reclaim=93.0,
        risk_flags=[],
        liquidity=80.0,
        risk=80.0,
    )
    setup_type = dragon_pullback._setup_type(
        features,
        "PULLBACK_OBSERVE",
        failed_rules,
        low_suction=100.0,
        stealth_low_suction=100.0,
    )
    display_failed_rules = dragon_pullback._display_failed_rules(
        failed_rules,
        executable_low_suction=True,
        setup_type=setup_type,
    )

    assert failed_rules == ["support_acceptance", "overheat"]
    assert setup_type == "stealth_low_suction"
    assert display_failed_rules == []
    assert dragon_pullback._is_low_suction_launch_confirmed(features, low_suction_days=4) is True
    assert dragon_pullback._low_suction_launch_bonus(features, setup_type=setup_type, low_suction_days=4) == 1.2


def test_stealth_low_suction_persistence_rules_do_not_reject_dragon_specific_failures() -> None:
    from alphaagent.server.services.quant import screening_payloads

    low_suction_buy = SignalScore(
        vt_symbol="002208.SZSE",
        trade_date=date(2026, 4, 29),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=78.0,
        liquidity_score=80.0,
        risk_score=80.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "setup_type": "stealth_low_suction",
            "dragon_state": "LOW_SUCTION_BUILDUP",
            "failed_rules": ["strong_leg", "pullback_too_short"],
            "low_suction_days": 4,
            "low_suction_buildup_score": 100.0,
            "stealth_low_suction_score": 94.0,
            "ma_convergence_pct": 3.45,
            "ma20_distance_pct": 3.0,
            "low_suction_launch_confirmed": True,
            "close_price": 12.98,
        },
    )

    row = screening_payloads.recommendation_to_db(
        1,
        low_suction_buy,
        None,
        DRAGON_PULLBACK_STRATEGY_ID,
        "0.1.9",
        min_entry_score=76.0,
    )

    assert row["action"] == "BUY"
    assert row["reason"]["failed_rules"] == []


def test_dragon_pullback_allows_stealth_low_suction_confirmation_volume() -> None:
    start = date(2026, 1, 1)
    closes = [16 + index * 0.025 for index in range(70)]
    closes.extend([17.62, 17.55, 17.48, 17.58, 17.50, 17.42, 17.35, 17.28, 17.66, 17.82])
    bars: list[Bar] = []
    for index, close in enumerate(closes):
        is_last = index == len(closes) - 1
        bars.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=close * (0.985 if is_last else 0.995),
                high_price=close * (1.01 if is_last else 1.015),
                low_price=close * (0.985 if is_last else 0.982),
                close_price=close,
                volume=2_200_000 if is_last else (1_200_000 if index < 60 else 700_000),
                turnover=380_000_000,
                change_pct=5.7 if is_last else (-0.4 if index >= 70 else 0.4),
            )
        )

    score = score_dragon_pullback(
        "002208.SZSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-1.0,
        sector_score=50.0,
        financial_score=50.0,
    )

    assert score.entry_signal is True
    assert score.evidence["setup_type"] == "stealth_low_suction"
    assert score.evidence["volume_ratio_5d_20d"] > 1.25


def test_dragon_pullback_marks_low_suction_limit_up_start_factors() -> None:
    start = date(2026, 1, 1)
    closes = [10.0 + index * 0.03 for index in range(80)]
    closes.extend([12.0, 13.2, 13.6, 14.1, 14.7, 15.2, 14.9, 15.0, 15.2, 15.5])
    bars: list[Bar] = []
    for index, close in enumerate(closes):
        is_gap = index == 81
        is_limit = index == 81
        is_volume_expansion = 81 <= index <= 85
        previous_close = closes[index - 1] if index > 0 else close
        open_price = previous_close * 1.035 if is_gap else close * 0.995
        change_pct = 10.0 if is_limit else 1.6 if 62 <= index <= 65 else 0.2
        bars.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=open_price,
                high_price=max(open_price, close) * 1.02,
                low_price=min(open_price, close) * 0.98,
                close_price=close,
                volume=3_000_000 if is_volume_expansion else 1_000_000,
                turnover=900_000_000 if is_volume_expansion else 250_000_000,
                change_pct=change_pct,
            )
        )

    score = score_dragon_pullback("002384.SZSE", bars, bars[-1].trade_date, index_return_20d=-3.0, sector_score=70.0)

    assert score.evidence["sector_mainline_score"] == 70.0
    assert score.evidence["recent_limit_up_20d"] is True
    assert score.evidence["consecutive_bull_closes"] >= 4
    assert score.evidence["upward_gap_in_leg"] is True
    assert score.evidence["persistent_volume_expansion"] is True
    assert score.evidence["limit_up_start_factor_count"] >= 3
    assert score.evidence["weak_index_strength_confirmation"] is True


def test_low_suction_limit_up_start_requires_persistent_not_single_volume_spike() -> None:
    start = date(2026, 1, 1)
    closes = [10.0 + index * 0.02 for index in range(80)]
    closes.extend([12.0, 12.2, 12.1, 12.3, 12.2, 12.4, 12.3, 12.5])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 0.995,
            high_price=close * 1.02,
            low_price=close * 0.98,
            close_price=close,
            volume=4_000_000 if index == 82 else 1_000_000,
            turnover=800_000_000 if index == 82 else 220_000_000,
            change_pct=0.8,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback("002208.SZSE", bars, bars[-1].trade_date, index_return_20d=-2.0, sector_score=60.0)

    assert score.evidence["persistent_volume_expansion"] is False
    assert score.evidence["limit_up_start_factor_count"] < 3


def test_stealth_low_suction_keeps_hard_risk_failures_as_watch() -> None:
    from alphaagent.server.services.quant import screening_payloads

    risky_low_suction = SignalScore(
        vt_symbol="002208.SZSE",
        trade_date=date(2026, 6, 16),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=78.0,
        liquidity_score=80.0,
        risk_score=20.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "setup_type": "stealth_low_suction",
            "dragon_state": "LOW_SUCTION_BUILDUP",
            "failed_rules": ["strong_leg", "ma20_broken"],
            "low_suction_days": 4,
            "low_suction_buildup_score": 100.0,
            "stealth_low_suction_score": 90.0,
            "ma_convergence_pct": 3.0,
            "ma20_distance_pct": -8.0,
        },
    )

    row = screening_payloads.recommendation_to_db(
        1,
        risky_low_suction,
        None,
        DRAGON_PULLBACK_STRATEGY_ID,
        "0.1.9",
        min_entry_score=76.0,
    )

    assert row["action"] == "WATCH"
    assert "ma20_broken" in row["reason"]["failed_rules"]
    assert "risk_score" in row["reason"]["failed_rules"]


def test_dragon_pullback_rejects_weak_rebound_with_ma5_below_ma10() -> None:
    start = date(2026, 1, 1)
    closes = [10 + index * 0.08 for index in range(70)]
    closes.extend([17.0, 18.8, 20.5, 22.6, 24.5, 22.1, 20.3, 18.5, 17.6, 17.8, 17.9, 18.0])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 0.99,
            high_price=close * 1.02,
            low_price=close * 0.98,
            close_price=close,
            volume=1_600_000 if index < 70 else 900_000,
            turnover=450_000_000,
            change_pct=-0.4 if index >= 70 else 1.5,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback(
        "002208.SZSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-1.0,
        sector_score=70.0,
        financial_score=55.0,
    )

    assert score.evidence["status"] == "ready"
    assert score.evidence["dragon_state"] in {"INVALIDATED", "PULLBACK_OBSERVE"}
    assert "weak_rebound_ma5_below_ma10" in score.evidence["failed_rules"]
    assert score.entry_signal is False


def test_dragon_pullback_rejects_high_level_distribution_risk() -> None:
    start = date(2026, 1, 1)
    closes = [15 + index * 0.10 for index in range(70)]
    closes.extend([25.0, 27.5, 30.2, 33.0, 36.3, 39.8, 43.7, 48.1, 52.9, 49.0])
    bars: list[Bar] = []
    for index, close in enumerate(closes):
        is_last = index == len(closes) - 1
        bars.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=close * (1.08 if is_last else 0.99),
                high_price=close * (1.15 if is_last else 1.025),
                low_price=close * (0.97 if is_last else 0.98),
                close_price=close,
                volume=4_800_000 if is_last else 1_400_000,
                turnover=1_600_000_000 if is_last else 420_000_000,
                change_pct=-7.4 if is_last else 3.0,
            )
        )

    score = score_dragon_pullback(
        "002208.SZSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-1.0,
        sector_score=85.0,
        financial_score=60.0,
    )

    assert score.evidence["status"] == "ready"
    assert score.evidence["dragon_state"] == "DISTRIBUTION_RISK"
    assert "distribution_risk" in score.evidence["failed_rules"]
    assert score.entry_signal is False


def test_dragon_pullback_rejects_high_volume_limit_down_distribution() -> None:
    start = date(2026, 1, 1)
    closes = [10 + index * 0.08 for index in range(70)]
    closes.extend([16.0, 17.6, 19.3, 21.2, 23.3, 25.6, 28.2, 31.0, 34.1, 30.7])
    bars: list[Bar] = []
    for index, close in enumerate(closes):
        is_last = index == len(closes) - 1
        bars.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=close * (1.08 if is_last else 0.99),
                high_price=close * (1.10 if is_last else 1.025),
                low_price=close if is_last else close * 0.98,
                close_price=close,
                volume=5_000_000 if is_last else 1_400_000,
                turnover=1_800_000_000 if is_last else 420_000_000,
                change_pct=-10.0 if is_last else 3.0,
            )
        )

    score = score_dragon_pullback(
        "002208.SZSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-1.0,
        sector_score=85.0,
        financial_score=60.0,
    )

    assert score.evidence["dragon_state"] == "DISTRIBUTION_RISK"
    assert "distribution_risk" in score.evidence["failed_rules"]
    assert score.entry_signal is False


def test_dragon_pullback_marks_top_fractal_and_volume_stall_risks() -> None:
    start = date(2026, 1, 1)
    closes = [10 + index * 0.06 for index in range(70)]
    closes.extend([16.0, 17.2, 18.4, 19.6, 20.6, 20.2, 19.9, 19.7, 19.5, 19.4])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 0.995,
            high_price=close * (1.06 if 70 <= index <= 73 else 1.0 if index >= 74 else 1.02),
            low_price=close * 0.985,
            close_price=close,
            volume=4_000_000 if index >= 75 else 1_000_000,
            turnover=1_200_000_000 if index >= 75 else 300_000_000,
            change_pct=0.1 if index >= 75 else 1.2,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback("002119.SZSE", bars, bars[-1].trade_date, index_return_20d=-1.0, sector_score=75.0)

    assert score.evidence["weekly_top_fractal_risk"] is True
    assert score.evidence["volume_stall_risk"] is True
    assert "weekly_top_fractal_risk" in score.evidence["risk_flags"]


def test_dragon_pullback_marks_spiky_self_play_risk() -> None:
    start = date(2026, 1, 1)
    bars: list[Bar] = []
    close = 10.0
    for index in range(88):
        change_pct = 5.5 if index % 2 == 0 else -4.8
        close *= 1 + change_pct / 100
        bars.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=close * 0.99,
                high_price=close * 1.11,
                low_price=close * 0.90,
                close_price=close,
                volume=2_000_000,
                turnover=500_000_000,
                change_pct=change_pct,
            )
        )

    score = score_dragon_pullback("002119.SZSE", bars, bars[-1].trade_date, index_return_20d=0.0, sector_score=65.0)

    assert score.evidence["spiky_churn_risk"] is True
    assert "spiky_churn_risk" in score.evidence["risk_flags"]


def test_dragon_pullback_marks_illiquid_and_ma_break_risks() -> None:
    start = date(2026, 1, 1)
    closes = [10 + index * 0.03 for index in range(70)]
    closes.extend([12.0, 11.8, 11.6, 11.4, 11.2, 10.8, 10.5, 10.2, 9.9, 9.6])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 1.005,
            high_price=close * 1.015,
            low_price=close * 0.985,
            close_price=close,
            volume=60_000 if index >= 75 else 1_200_000,
            turnover=8_000_000 if index >= 75 else 260_000_000,
            change_pct=-2.8 if index >= 75 else 0.3,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback("002208.SZSE", bars, bars[-1].trade_date, index_return_20d=-3.0, sector_score=45.0)

    assert score.evidence["illiquid_forgotten_risk"] is True
    assert score.evidence["key_support_break_risk"] is True
    assert "key_support_break_risk" in score.evidence["failed_rules"]


def test_dragon_pullback_marks_high_level_long_sideways_distribution_risk() -> None:
    start = date(2026, 1, 1)
    closes = [10 + index * 0.08 for index in range(60)]
    closes.extend([16.8, 17.2, 16.9, 17.1, 16.7, 17.0, 16.8, 16.9, 17.1, 16.8])
    closes.extend([16.9, 17.0, 16.7, 16.8, 16.9, 16.6, 16.8, 16.7, 16.6, 16.5])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 0.997,
            high_price=close * 1.025,
            low_price=close * 0.975,
            close_price=close,
            volume=2_800_000 if index >= 60 else 1_200_000,
            turnover=900_000_000 if index >= 60 else 300_000_000,
            change_pct=0.0 if index >= 60 else 1.0,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback("603226.SSE", bars, bars[-1].trade_date, index_return_20d=0.0, sector_score=60.0)

    assert score.evidence["high_level_sideways_days"] >= 18
    assert score.evidence["high_level_sideways_distribution_risk"] is True
    assert "high_level_sideways_distribution_risk" in score.evidence["risk_flags"]


def test_dragon_pullback_does_not_mark_short_dragon_retest_as_long_sideways_distribution() -> None:
    start = date(2026, 1, 1)
    closes = [10 + index * 0.08 for index in range(72)]
    closes.extend([18.5, 19.4, 20.3, 19.2, 18.7, 18.9, 19.1, 19.6])
    bars = [
        Bar(
            trade_date=start + timedelta(days=index),
            open_price=close * 0.995,
            high_price=close * 1.03,
            low_price=close * 0.975,
            close_price=close,
            volume=1_600_000 if index >= 70 else 1_200_000,
            turnover=500_000_000 if index >= 70 else 300_000_000,
            change_pct=1.2 if index >= 76 else -0.5 if index >= 73 else 2.0,
        )
        for index, close in enumerate(closes)
    ]

    score = score_dragon_pullback("002428.SZSE", bars, bars[-1].trade_date, index_return_20d=-1.0, sector_score=75.0)

    assert score.evidence.get("high_level_sideways_days", 0) < 15
    assert score.evidence["high_level_sideways_distribution_risk"] is False


def test_quant_strategy_registry_returns_rule_metadata() -> None:
    from alphaagent.server.services.quant.strategy_registry import list_internal_strategies

    strategies = {item["id"]: item for item in list_internal_strategies()}

    assert strategies["mainline_leader_pullback"]["default_min_entry_score"] == 68.0
    assert strategies["mainline_leader_pullback"]["failed_rule_labels"]["ma5_distance"] == "不在MA5低吸区"
    assert strategies["mainline_leader_pullback"]["primary_metric_keys"] == ["ma5_distance_pct"]
    assert strategies["mainline_leader_pullback"]["evidence_labels"]["ma5_distance_pct"] == "MA5距离"
    assert strategies["breakout_confirmation"]["default_min_entry_score"] == 70.0
    assert strategies["breakout_confirmation"]["failed_rule_labels"]["breakout_distance"] == "未接近60日高点"
    assert strategies["breakout_confirmation"]["primary_metric_keys"] == ["close_to_prior_high_pct", "volume_ratio_5d_20d"]
    assert strategies["breakout_confirmation"]["evidence_labels"]["close_to_prior_high_pct"] == "距60日高点"
    assert strategies["limit_up_after_pullback"]["default_min_entry_score"] == 72.0
    assert strategies["limit_up_after_pullback"]["failed_rule_labels"]["limit_up_presence"] == "近20日无涨停"
    assert strategies["limit_up_after_pullback"]["primary_metric_keys"] == ["days_since_limit_up", "ma5_distance_pct"]
    assert strategies["limit_up_after_pullback"]["evidence_labels"]["days_since_limit_up"] == "距涨停天数"
    assert strategies["trend_acceleration"]["default_min_entry_score"] == 73.0
    assert strategies["trend_acceleration"]["failed_rule_labels"]["overheat"] == "短期过热"
    assert strategies["trend_acceleration"]["primary_metric_keys"] == ["return_20d", "volume_ratio_5d_20d"]
    assert strategies["trend_acceleration"]["evidence_labels"]["return_20d"] == "20日涨跌"
    assert strategies["mainline_dragon_pullback"]["default_min_entry_score"] == 76.0
    assert strategies["mainline_dragon_pullback"]["failed_rule_labels"]["distribution_risk"] == "高位派发风险"
    assert strategies["mainline_dragon_pullback"]["failed_rule_labels"]["ma_convergence_too_wide_without_low_suction"] == "均线发散且缺少低吸蓄势"
    assert strategies["mainline_dragon_pullback"]["primary_metric_keys"] == ["dragon_state", "low_suction_days", "ma_convergence_pct"]
    assert strategies["mainline_dragon_pullback"]["evidence_labels"]["low_suction_days"] == "低吸蓄势天数"


def test_symbol_signal_rule_payload_is_strategy_specific() -> None:
    from alphaagent.server.services.quant import screening

    pullback = screening._strategy_rule_payload("mainline_leader_pullback", 68.0)
    breakout = screening._strategy_rule_payload("breakout_confirmation", 70.0)
    limit_up = screening._strategy_rule_payload("limit_up_after_pullback", 72.0)
    acceleration = screening._strategy_rule_payload("trend_acceleration", 73.0)
    dragon = screening._strategy_rule_payload("mainline_dragon_pullback", 72.0)

    assert pullback["ma5_distance_pct"] == "[-1.5, 2.0]"
    assert "ma5_distance_pct" not in breakout
    assert breakout["close_to_prior_high_pct"] == ">= -1.0"
    assert breakout["volume_ratio_5d_20d"] == ">= 1.10"
    assert limit_up["limit_up_count_20d"] == ">= 1"
    assert limit_up["days_since_limit_up"] == "[2, 12]"
    assert limit_up["ma20_distance_pct"] == ">= -2.0"
    assert acceleration["return_20d"] == ">= 12.0"
    assert acceleration["ma_alignment"] == "MA5 > MA20 > MA60"
    assert acceleration["volume_ratio_5d_20d"] == "[1.05, 2.80]"
    assert dragon["pullback_days"] == "[3, 12]"
    assert dragon["support_type"] == "MA5/MA10/MA20 support + reclaim"
    assert dragon["distribution_risk"] == "reject"


def test_dragon_pullback_exit_holds_after_fixed_take_profit_line() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, take_profit_pct=0.18)
    position = Position(
        vt_symbol="002428.SZSE",
        name="云南锗业",
        volume=100,
        cost_price=100.0,
        entry_date=date(2026, 4, 1),
        highest_price=121.0,
        reason={"ma10": 108.0, "ma20": 96.0, "support_price": 104.0},
    )
    bar = Bar(
        trade_date=date(2026, 4, 10),
        open_price=117.0,
        high_price=121.0,
        low_price=116.0,
        close_price=119.0,
        volume=1_000_000,
        turnover=500_000_000,
        change_pct=1.2,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) is None


def test_dragon_pullback_exit_sells_on_trend_break_after_profit() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="600487.SSE",
        name="亨通光电",
        volume=100,
        cost_price=100.0,
        entry_date=date(2026, 4, 1),
        highest_price=122.0,
        reason={"ma10": 118.0, "ma20": 100.0, "support_price": 105.0},
    )
    bar = Bar(
        trade_date=date(2026, 4, 18),
        open_price=112.0,
        high_price=114.0,
        low_price=110.0,
        close_price=111.0,
        volume=1_000_000,
        turnover=500_000_000,
        change_pct=-4.5,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) == "trend_break"


def test_dragon_pullback_exit_protects_large_floating_profit() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="001258.SZSE",
        name="立新能源",
        volume=100,
        cost_price=9.52,
        entry_date=date(2026, 3, 18),
        highest_price=12.33,
        reason={"ma10": 9.15, "ma20": 8.47, "support_price": 9.61},
    )
    bar = Bar(
        trade_date=date(2026, 3, 27),
        open_price=10.90,
        high_price=10.96,
        low_price=10.30,
        close_price=10.43,
        volume=1_000_000,
        turnover=600_000_000,
        change_pct=-3.87,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) == "profit_protection_stop"


def test_dragon_pullback_default_stop_loss_0p08_survives_seven_pct_drawdown() -> None:
    """stop_loss_pct 默认 0.08（2026-06-24 CPCV 验证 PBO=0.33 稳健）。

    跌幅 -7.5%（落在 0.07 线 93.0 与 0.08 线 92.0 之间）：默认 0.08 扛住不止损，
    0.07 会触发 support_stop。背景：0.07 在波动市误杀 55%（止损后5日回升），0.08 让被
    -7%~-8% 震出的交易扛住回升，全样本 return +16.6pp 且样本外 PBO=0.33 不过拟合。
    """
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params_default = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    assert params_default.stop_loss_pct == 0.08
    params_legacy = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, stop_loss_pct=0.07)

    # close 92.5 = 成本 -7.5%，落在 0.07 线(93.0) 与 0.08 线(92.0) 之间。
    # support_price=95 -> support×0.965=91.75（不触发）；ma20=95 -> ma20×0.97=92.15（close 92.5 不触发 trend_break）。
    position = Position(
        vt_symbol="002384.SZSE",
        name="东山精密",
        volume=100,
        cost_price=100.0,
        entry_date=date(2026, 6, 1),
        highest_price=100.0,
        reason={"ma10": 96.0, "ma20": 95.0, "support_price": 95.0},
    )
    bar = Bar(
        trade_date=date(2026, 6, 10),
        open_price=93.0,
        high_price=94.0,
        low_price=92.0,
        close_price=92.5,
        volume=1_000_000,
        turnover=500_000_000,
        change_pct=-7.5,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params_default) is None
    assert sell_reason_for_position(position, bar, bar.trade_date, params_legacy) == "support_stop"


def test_dragon_pullback_default_protects_mid_profit_giveback() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    position = Position(
        vt_symbol="002443.SZSE",
        name="金洲管道",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 5, 14),
        highest_price=11.2,
        reason={"entry_setup": "dragon_pullback", "ma10": 10.6, "ma20": 10.1, "support_price": 10.0},
    )
    bar = Bar(
        trade_date=date(2026, 5, 28),
        open_price=10.3,
        high_price=10.35,
        low_price=10.2,
        close_price=10.30,
        volume=1_000_000,
        turnover=200_000_000,
        change_pct=-2.0,
    )
    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    experiment_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, enable_mid_profit_giveback_stop=True)

    assert sell_reason_for_position(position, bar, bar.trade_date, default_params) == "profit_protection_stop"
    assert sell_reason_for_position(position, bar, bar.trade_date, experiment_params) == "mid_profit_giveback_stop"
    assert sell_reason_for_position(position, bar, bar.trade_date, default_params, current_buy_signal=True) is None
    assert sell_reason_for_position(position, bar, bar.trade_date, experiment_params, current_buy_signal=True) is None


def test_dragon_pullback_default_sells_guarded_highclose_giveback() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="605117.SSE",
        name="德业股份",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 4, 23),
        highest_price=11.4,
        reason={
            "entry_setup": "dragon_pullback",
            "close_location_in_range": 0.88,
            "low_suction_launch_quality_bucket": "repeated_launch",
            "recent_limit_up_20d": True,
            "large_bull_count_20d": 1,
            "ma10": 10.4,
            "ma20": 9.9,
            "support_price": 9.8,
        },
        visible_holding_bars=4,
    )
    bar = Bar(
        trade_date=date(2026, 4, 29),
        open_price=10.35,
        high_price=10.40,
        low_price=10.20,
        close_price=10.30,
        volume=1_000_000,
        turnover=200_000_000,
        change_pct=-2.0,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) == "guarded_highclose_giveback_stop"
    assert sell_reason_for_position(position, bar, bar.trade_date, params, current_buy_signal=True) is None


def test_dragon_pullback_guarded_highclose_giveback_protects_ma10_continuation() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import guarded_highclose_giveback_stop_applies, sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="603876.SSE",
        name="鼎胜新材",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 3, 9),
        highest_price=11.4,
        reason={
            "entry_setup": "dragon_pullback",
            "close_location_in_range": 0.86,
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 1,
            "large_bull_count_20d": 1,
            "support_type": "ma10_support",
            "strong_leg_score": 97.0,
            "pullback_days": 5,
            "ma5_vs_ma10_pct": -0.3,
            "ma10_distance_pct": 1.1,
            "volume_ratio_5d_20d": 0.82,
            "ma10": 10.1,
            "ma20": 9.8,
            "support_price": 9.7,
        },
        visible_holding_bars=4,
    )
    bar = Bar(
        trade_date=date(2026, 3, 13),
        open_price=10.35,
        high_price=10.40,
        low_price=10.20,
        close_price=10.30,
        volume=1_000_000,
        turnover=200_000_000,
        change_pct=-2.0,
    )

    high_gain = position.highest_price / position.cost_price - 1
    gain = bar.close_price / position.cost_price - 1
    drawdown_from_high = bar.close_price / position.highest_price - 1

    assert (
        guarded_highclose_giveback_stop_applies(
            position,
            bar,
            gain,
            high_gain,
            drawdown_from_high,
            hold_soft_exit=False,
            current_buy_signal=False,
        )
        is False
    )
    assert sell_reason_for_position(position, bar, bar.trade_date, params) == "profit_protection_stop"


def test_dragon_pullback_experiment_can_tighten_mfe8_giveback_stop() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    position = Position(
        vt_symbol="000725.SZSE",
        name="京东方A",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 4, 22),
        highest_price=10.9,
        reason={"entry_setup": "dragon_pullback", "ma10": 10.4, "ma20": 10.0, "support_price": 9.9},
    )
    bar = Bar(
        trade_date=date(2026, 4, 29),
        open_price=10.12,
        high_price=10.18,
        low_price=10.05,
        close_price=10.10,
        volume=1_000_000,
        turnover=200_000_000,
        change_pct=-1.4,
    )
    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    mfe8_params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        enable_mid_profit_giveback_stop=True,
        mid_profit_giveback_min_high_gain_pct=0.08,
        mid_profit_giveback_max_current_gain_pct=0.02,
        mid_profit_giveback_drawdown_pct=0.05,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, default_params) is None
    assert sell_reason_for_position(position, bar, bar.trade_date, mfe8_params) == "mid_profit_giveback_stop"


def test_dragon_pullback_trend_trailing_buffer_delays_default_stop() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    position = Position(
        vt_symbol="603439.SSE",
        name="贵州三力",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 5, 11),
        highest_price=14.5,
        reason={"ma10": 11.0, "ma20": 10.0, "support_price": 9.8},
    )
    bar = Bar(
        trade_date=date(2026, 5, 25),
        open_price=13.1,
        high_price=13.2,
        low_price=12.9,
        close_price=13.0,
        volume=1_000_000,
        turnover=200_000_000,
        change_pct=-2.0,
    )
    default_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    buffered_params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, trend_trailing_dd_buffer_pct=0.04)

    assert sell_reason_for_position(position, bar, bar.trade_date, default_params) == "trend_trailing_stop"
    assert sell_reason_for_position(position, bar, bar.trade_date, buffered_params) is None


def test_mid_profit_giveback_experiment_does_not_force_sell_stealth_low_suction() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, enable_mid_profit_giveback_stop=True)
    position = Position(
        vt_symbol="002384.SZSE",
        name="东山精密",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 4, 1),
        highest_price=11.2,
        reason={
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 5,
            "low_suction_launch_confirmed": True,
            "ma10": 10.6,
            "ma20": 10.1,
            "support_price": 10.0,
        },
    )
    bar = Bar(
        trade_date=date(2026, 4, 10),
        open_price=10.3,
        high_price=10.35,
        low_price=10.2,
        close_price=10.30,
        volume=1_000_000,
        turnover=200_000_000,
        change_pct=-2.0,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) is None


def test_default_profit_protection_sells_unconfirmed_giveback_but_keeps_confirmed_low_suction() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    bar = Bar(
        trade_date=date(2026, 4, 10),
        open_price=10.3,
        high_price=10.35,
        low_price=10.2,
        close_price=10.30,
        volume=1_000_000,
        turnover=200_000_000,
        change_pct=-2.0,
    )
    unconfirmed = Position(
        vt_symbol="002384.SZSE",
        name="东山精密",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 4, 1),
        highest_price=11.2,
        reason={"ma10": 10.6, "ma20": 10.1, "support_price": 10.0},
    )
    confirmed_low_suction = Position(
        vt_symbol="002384.SZSE",
        name="东山精密",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 4, 1),
        highest_price=11.2,
        reason={
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 5,
            "low_suction_launch_confirmed": True,
            "ma10": 10.6,
            "ma20": 10.1,
            "support_price": 10.0,
        },
    )

    assert sell_reason_for_position(unconfirmed, bar, bar.trade_date, params) == "profit_protection_stop"
    assert sell_reason_for_position(confirmed_low_suction, bar, bar.trade_date, params) is None


def test_contextual_peak_giveback_requires_visible_profit_and_no_current_buy_signal() -> None:
    from alphaagent.server.services.backtest.simulation import should_trigger_contextual_peak_giveback_stop

    decision = should_trigger_contextual_peak_giveback_stop(
        highest_return_pct=0.13,
        current_return_pct=0.02,
        holding_days=12,
        has_current_buy_or_hold_signal=False,
        market_warning_level=2,
        support_reclaim_failed=True,
        distribution_risk=True,
    )

    assert decision["trigger"] is True
    assert decision["reason"] == "contextual_peak_giveback_stop"

    protected = should_trigger_contextual_peak_giveback_stop(
        highest_return_pct=0.20,
        current_return_pct=0.10,
        holding_days=12,
        has_current_buy_or_hold_signal=True,
        market_warning_level=1,
        support_reclaim_failed=False,
        distribution_risk=False,
    )

    assert protected["trigger"] is False


def test_contextual_peak_giveback_experiment_sells_visible_profit_giveback() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, enable_contextual_peak_giveback_stop=True)
    position = Position(
        vt_symbol="002443.SZSE",
        name="众业达",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 5, 14),
        highest_price=11.3,
        reason={
            "entry_setup": "dragon_pullback",
            "ma10": 10.55,
            "ma20": 10.25,
            "support_price": 10.4,
            "volume_stall_risk": True,
        },
    )
    bar = Bar(
        trade_date=date(2026, 5, 28),
        open_price=10.2,
        high_price=10.3,
        low_price=10.0,
        close_price=10.2,
        volume=1_000_000,
        turnover=200_000_000,
        change_pct=-2.0,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) == "contextual_peak_giveback_stop"
    assert sell_reason_for_position(position, bar, bar.trade_date, params, current_buy_signal=True) is None


def test_contextual_support_reclaim_delay_only_delays_rebound_prone_support_stop() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import should_delay_contextual_support_reclaim

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, enable_contextual_support_reclaim_delay=True)
    position = Position(
        vt_symbol="002384.SZSE",
        name="东山精密",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 4, 1),
        highest_price=10.8,
        reason={
            "support_price": 10.2,
            "ma10": 10.1,
            "ma20": 9.9,
            "market_warning_level": 1,
            "dynamic_market_regime": "choppy_rotation",
        },
    )
    bar = Bar(
        trade_date=date(2026, 4, 10),
        open_price=9.85,
        high_price=10.35,
        low_price=9.75,
        close_price=9.82,
        volume=1_000_000,
        turnover=220_000_000,
        change_pct=-4.0,
    )

    delay = should_delay_contextual_support_reclaim(
        exit_reason="support_stop",
        position=position,
        bar=bar,
        params=params,
    )

    assert delay["delay"] is True
    assert delay["not_used_for_signal_score"] is True


def test_failed_launch_exit_experiment_is_default_off() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="600352.SSE",
        name="浙江龙盛",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 3, 12),
        highest_price=10.15,
        reason={
            "entry_setup": "stealth_low_suction",
            "support_price": 9.85,
            "ma10": 9.95,
            "ma20": 9.88,
        },
        visible_holding_bars=3,
    )
    bar = Bar(
        trade_date=date(2026, 3, 16),
        open_price=9.75,
        high_price=9.82,
        low_price=9.55,
        close_price=9.70,
        volume=1_000_000,
        turnover=300_000_000,
        change_pct=-2.8,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) is None


def test_failed_launch_exit_experiment_sells_after_three_visible_hold_bars() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, enable_failed_launch_exit_stop=True)
    position = Position(
        vt_symbol="600352.SSE",
        name="浙江龙盛",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 3, 12),
        highest_price=10.15,
        reason={
            "entry_setup": "stealth_low_suction",
            "support_price": 9.85,
            "ma10": 9.95,
            "ma20": 9.88,
        },
        visible_holding_bars=3,
    )
    bar = Bar(
        trade_date=date(2026, 3, 16),
        open_price=9.75,
        high_price=9.82,
        low_price=9.55,
        close_price=9.70,
        volume=1_000_000,
        turnover=300_000_000,
        change_pct=-2.8,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) == "failed_launch_exit_stop"


def test_failed_launch_exit_experiment_waits_for_current_buy_signal() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, enable_failed_launch_exit_stop=True)
    position = Position(
        vt_symbol="601179.SSE",
        name="中国西电",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 2, 24),
        highest_price=10.12,
        reason={
            "entry_setup": "dragon_pullback",
            "support_price": 9.9,
            "ma10": 9.95,
            "ma20": 9.85,
        },
        visible_holding_bars=3,
    )
    bar = Bar(
        trade_date=date(2026, 2, 27),
        open_price=9.78,
        high_price=9.86,
        low_price=9.65,
        close_price=9.72,
        volume=1_000_000,
        turnover=300_000_000,
        change_pct=-2.2,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params, current_buy_signal=True) is None


def test_contextual_failed_launch_exit_respects_current_buy_signal() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        enable_contextual_failed_launch_exit_stop=True,
    )
    position = Position(
        vt_symbol="601179.SSE",
        name="中国西电",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 2, 24),
        highest_price=10.12,
        reason={
            "entry_setup": "dragon_pullback",
            "support_price": 9.9,
            "ma10": 9.95,
            "ma20": 9.85,
            "entry_total_score": 82.0,
        },
        visible_holding_bars=3,
    )
    bar = Bar(
        trade_date=date(2026, 2, 27),
        open_price=9.78,
        high_price=9.86,
        low_price=9.65,
        close_price=9.72,
        volume=1_000_000,
        turnover=300_000_000,
        change_pct=-2.2,
    )

    assert (
        sell_reason_for_position(
            position,
            bar,
            bar.trade_date,
            params,
            current_buy_signal=True,
        )
        is None
    )


def test_dynamic_failed_launch_default_requires_verified_family_timing() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    no_timing_position = Position(
        vt_symbol="600352.SSE",
        name="浙江龙盛",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 6, 9),
        highest_price=10.08,
        lowest_price=9.72,
        reason={
            "entry_setup": "stealth_low_suction",
            "support_price": 9.90,
            "ma10": 9.92,
            "ma20": 9.86,
            "entry_total_score": 88.0,
        },
        visible_holding_bars=3,
    )
    silver_retreat_position = Position(
        vt_symbol="603040.SSE",
        name="新坐标",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 6, 9),
        highest_price=10.08,
        lowest_price=9.72,
        reason={
            "entry_setup": "stealth_low_suction",
            "setup_family": "low_suction_buildup",
            "timing_window": "after_silver_6_20",
            "market_phase": "retreat",
            "support_price": 9.90,
            "ma10": 9.92,
            "ma20": 9.86,
            "entry_total_score": 88.0,
        },
        visible_holding_bars=3,
    )
    bar = Bar(
        trade_date=date(2026, 6, 12),
        open_price=9.78,
        high_price=9.84,
        low_price=9.62,
        close_price=9.66,
        volume=1_000_000,
        turnover=300_000_000,
        change_pct=-2.4,
    )

    assert sell_reason_for_position(no_timing_position, bar, bar.trade_date, params) is None
    assert sell_reason_for_position(silver_retreat_position, bar, bar.trade_date, params) == "dynamic_failed_launch_exit_stop"


def test_dynamic_failed_launch_default_blocks_false_warming_family_timing() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="001207.SZSE",
        name="联科科技",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 3, 31),
        highest_price=10.08,
        lowest_price=9.72,
        reason={
            "entry_setup": "stealth_low_suction",
            "setup_family": "low_suction_first_lift",
            "timing_window": "after_silver_6_20",
            "market_phase": "warming",
            "low_suction_launch_confirmed": True,
            "support_price": 9.90,
            "ma10": 9.92,
            "ma20": 9.86,
            "entry_total_score": 88.0,
        },
        visible_holding_bars=3,
    )
    bar = Bar(
        trade_date=date(2026, 4, 3),
        open_price=9.78,
        high_price=9.84,
        low_price=9.62,
        close_price=9.66,
        volume=1_000_000,
        turnover=300_000_000,
        change_pct=-2.4,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) is None


def test_dynamic_failed_launch_exit_sells_visible_failed_launch_before_support_stop() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, enable_dynamic_failed_launch_exit_stop=True)
    position = Position(
        vt_symbol="600352.SSE",
        name="浙江龙盛",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 3, 12),
        highest_price=10.08,
        lowest_price=9.72,
        reason={
            "entry_setup": "stealth_low_suction",
            "support_price": 9.90,
            "ma10": 9.92,
            "ma20": 9.86,
            "entry_total_score": 88.0,
        },
        visible_holding_bars=3,
    )
    bar = Bar(
        trade_date=date(2026, 3, 16),
        open_price=9.78,
        high_price=9.84,
        low_price=9.62,
        close_price=9.66,
        volume=1_000_000,
        turnover=300_000_000,
        change_pct=-2.4,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) == "dynamic_failed_launch_exit_stop"


def test_dynamic_failed_launch_exit_respects_current_buy_signal_and_opened_space() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, enable_dynamic_failed_launch_exit_stop=True)
    position = Position(
        vt_symbol="601179.SSE",
        name="中国西电",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 2, 24),
        highest_price=10.35,
        lowest_price=9.75,
        reason={
            "entry_setup": "dragon_pullback",
            "support_price": 9.90,
            "ma10": 9.95,
            "ma20": 9.86,
            "entry_total_score": 91.0,
        },
        visible_holding_bars=3,
    )
    bar = Bar(
        trade_date=date(2026, 2, 27),
        open_price=9.76,
        high_price=9.88,
        low_price=9.64,
        close_price=9.70,
        volume=1_000_000,
        turnover=300_000_000,
        change_pct=-2.3,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params, current_buy_signal=True) is None
    assert sell_reason_for_position(position, bar, bar.trade_date, params, current_buy_signal=False) is None


def test_low_suction_confirmed_branch_exit_is_default_off() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="600522.SSE",
        name="中天科技",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 1, 13),
        highest_price=10.1,
        lowest_price=9.15,
        reason={"execution": {"mode": "low_suction_trigger_day_confirmed_next_open"}},
        visible_holding_bars=3,
    )
    bar = Bar(
        trade_date=date(2026, 1, 16),
        open_price=9.4,
        high_price=9.55,
        low_price=9.15,
        close_price=9.6,
        volume=1_000_000,
        turnover=200_000_000,
        change_pct=-3.0,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) is None


def test_low_suction_confirmed_branch_exit_sells_strict_failed_follow() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, enable_low_suction_confirmed_branch_exit=True)
    position = Position(
        vt_symbol="600352.SSE",
        name="浙江龙盛",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 3, 12),
        highest_price=10.1,
        lowest_price=9.15,
        reason={"execution": {"mode": "low_suction_trigger_day_confirmed_next_open"}},
        visible_holding_bars=3,
    )
    bar = Bar(
        trade_date=date(2026, 3, 16),
        open_price=9.4,
        high_price=9.55,
        low_price=9.15,
        close_price=9.6,
        volume=1_000_000,
        turnover=200_000_000,
        change_pct=-3.0,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) == "low_suction_failed_follow_branch_stop"
    assert position.low_suction_confirmed_branch == "failed_follow"
    assert position.low_suction_confirmed_branch_raw["low_return_pct"] <= -8.0


def test_low_suction_confirmed_branch_exit_does_not_misclassify_moderate_shakeout() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, enable_low_suction_confirmed_branch_exit=True)
    position = Position(
        vt_symbol="600522.SSE",
        name="中天科技",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 1, 13),
        highest_price=10.1,
        lowest_price=9.43,
        reason={"execution": {"mode": "low_suction_trigger_day_confirmed_next_open"}},
        visible_holding_bars=3,
    )
    bar = Bar(
        trade_date=date(2026, 1, 16),
        open_price=9.6,
        high_price=9.8,
        low_price=9.43,
        close_price=9.56,
        volume=1_000_000,
        turnover=200_000_000,
        change_pct=-2.0,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) is None
    assert position.low_suction_confirmed_branch is None


def test_low_suction_confirmed_branch_exit_holds_opened_space_until_giveback() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, enable_low_suction_confirmed_branch_exit=True, time_stop_days=3)
    position = Position(
        vt_symbol="002384.SZSE",
        name="东山精密",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 4, 8),
        highest_price=10.8,
        lowest_price=9.7,
        reason={"execution": {"mode": "low_suction_trigger_day_confirmed_next_open"}},
        visible_holding_bars=5,
    )
    hold_bar = Bar(
        trade_date=date(2026, 4, 14),
        open_price=10.35,
        high_price=10.7,
        low_price=10.1,
        close_price=10.35,
        volume=1_000_000,
        turnover=200_000_000,
        change_pct=0.5,
    )
    giveback_bar = Bar(
        trade_date=date(2026, 4, 15),
        open_price=10.0,
        high_price=10.1,
        low_price=9.9,
        close_price=10.0,
        volume=1_100_000,
        turnover=220_000_000,
        change_pct=-3.4,
    )

    assert sell_reason_for_position(position, hold_bar, hold_bar.trade_date, params) is None
    assert position.low_suction_confirmed_branch == "opened_space"
    position.visible_holding_bars = 6
    assert sell_reason_for_position(position, giveback_bar, giveback_bar.trade_date, params) == "low_suction_opened_space_giveback_stop"


def test_dragon_pullback_exit_holds_capacity_trend_until_trailing_break() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="600487.SSE",
        name="亨通光电",
        volume=100,
        cost_price=50.0,
        entry_date=date(2026, 1, 10),
        highest_price=72.0,
        reason={"ma10": 66.0, "ma20": 60.0, "support_price": 52.0},
    )
    bar = Bar(
        trade_date=date(2026, 2, 20),
        open_price=67.0,
        high_price=69.0,
        low_price=65.8,
        close_price=66.5,
        volume=1_000_000,
        turnover=800_000_000,
        change_pct=-1.2,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) is None


def test_dragon_pullback_exit_tightens_stop_for_fragile_structure() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="001258.SZSE",
        name="立新能源",
        volume=100,
        cost_price=10.41,
        entry_date=date(2026, 5, 25),
        highest_price=10.70,
        reason={"ma10": 9.92, "ma20": 9.50, "support_price": 10.05, "max_drawdown_60d": -28.58},
    )
    bar = Bar(
        trade_date=date(2026, 6, 2),
        open_price=9.95,
        high_price=10.05,
        low_price=9.72,
        close_price=9.86,
        volume=1_000_000,
        turnover=600_000_000,
        change_pct=-3.1,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) == "fragile_structure_stop"


def test_dragon_pullback_exit_does_not_tighten_fragile_stop_after_profit_buffer() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="002208.SZSE",
        name="合肥城建",
        volume=100,
        cost_price=11.40,
        entry_date=date(2025, 12, 25),
        highest_price=13.30,
        reason={"ma10": 10.90, "ma20": 10.50, "support_price": 11.05, "max_drawdown_60d": -34.11},
    )
    bar = Bar(
        trade_date=date(2026, 1, 8),
        open_price=12.00,
        high_price=12.18,
        low_price=11.72,
        close_price=11.90,
        volume=1_000_000,
        turnover=600_000_000,
        change_pct=-2.5,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) is None


def test_dragon_pullback_exit_holds_low_base_accumulation() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, time_stop_days=10)
    position = Position(
        vt_symbol="002208.SZSE",
        name="合肥城建",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 4, 1),
        highest_price=10.6,
        reason={
            "entry_setup": "stealth_low_suction",
            "low_base_days": 45,
            "price_location_60d_pct": 28.0,
            "base_volatility_20d_pct": 5.0,
            "ma10": 9.95,
            "ma20": 9.75,
            "support_price": 9.7,
        },
    )
    bar = Bar(
        trade_date=date(2026, 4, 28),
        open_price=10.15,
        high_price=10.25,
        low_price=9.88,
        close_price=10.05,
        volume=900_000,
        turnover=250_000_000,
        change_pct=0.3,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) is None


def test_dragon_pullback_exit_holds_ma_support_pullback_with_volume_confirmation() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="600487.SSE",
        name="亨通光电",
        volume=100,
        cost_price=50.0,
        entry_date=date(2026, 1, 10),
        highest_price=64.0,
        reason={
            "ma10": 58.0,
            "ma20": 55.0,
            "support_price": 55.0,
            "volume_ratio_5d_20d": 1.18,
            "latest_change_pct": 0.8,
            "price_volume_sync": True,
        },
    )
    bar = Bar(
        trade_date=date(2026, 2, 8),
        open_price=57.2,
        high_price=58.8,
        low_price=55.4,
        close_price=58.1,
        volume=1_500_000,
        turnover=900_000_000,
        change_pct=0.8,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params, current_buy_signal=True) is None


def test_dragon_pullback_exit_requires_confirmed_breakdown_not_single_noise() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="002208.SZSE",
        name="合肥城建",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 4, 20),
        highest_price=10.4,
        reason={
            "ma10": 9.9,
            "ma20": 9.6,
            "support_price": 9.8,
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 5,
            "low_suction_launch_confirmed": True,
        },
    )
    bar = Bar(
        trade_date=date(2026, 4, 22),
        open_price=9.86,
        high_price=10.05,
        low_price=9.70,
        close_price=9.77,
        volume=1_000_000,
        turnover=300_000_000,
        change_pct=-2.1,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) is None


def test_stealth_low_suction_exit_waits_when_entry_day_only_small_noise() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="002208.SZSE",
        name="合肥城建",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 4, 20),
        highest_price=10.25,
        reason={
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 5,
            "low_suction_launch_confirmed": True,
            "support_price": 9.8,
            "ma20": 9.6,
        },
    )
    bar = Bar(
        trade_date=date(2026, 4, 20),
        open_price=10.0,
        high_price=10.25,
        low_price=9.78,
        close_price=9.82,
        volume=1_000_000,
        turnover=300_000_000,
        change_pct=-1.8,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) is None


def test_dragon_pullback_exit_stops_fragile_entry_after_clean_support_failure() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams, Position
    from alphaagent.server.services.backtest.simulation import sell_reason_for_position

    params = BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID)
    position = Position(
        vt_symbol="001258.SZSE",
        name="立新能源",
        volume=100,
        cost_price=10.0,
        entry_date=date(2026, 5, 25),
        highest_price=10.2,
        reason={
            "ma10": 9.8,
            "ma20": 9.4,
            "support_price": 9.9,
            "max_drawdown_60d": -30.0,
            "entry_setup": "dragon_pullback",
        },
    )
    bar = Bar(
        trade_date=date(2026, 5, 30),
        open_price=9.65,
        high_price=9.75,
        low_price=9.38,
        close_price=9.45,
        volume=1_000_000,
        turnover=300_000_000,
        change_pct=-4.0,
    )

    assert sell_reason_for_position(position, bar, bar.trade_date, params) == "fragile_structure_stop"


def test_dragon_pullback_buy_fill_uses_support_reference_price() -> None:
    from alphaagent.server.services.backtest.execution_models import resolve_buy_fill
    from alphaagent.server.services.backtest.schemas import BacktestParams

    signal_date = date(2026, 4, 29)
    execute_date = date(2026, 4, 30)
    symbol = "002428.SZSE"
    signal_bar = Bar(
        trade_date=signal_date,
        open_price=68.0,
        high_price=70.5,
        low_price=67.8,
        close_price=69.2,
        volume=1_000_000,
        turnover=500_000_000,
        change_pct=-0.7,
    )
    execute_bar = Bar(
        trade_date=execute_date,
        open_price=69.5,
        high_price=71.2,
        low_price=68.9,
        close_price=70.1,
        volume=1_000_000,
        turnover=500_000_000,
        change_pct=1.3,
    )
    params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        execution_model="strict_1430",
        tail_entry_ma5_tolerance_pct=1.5,
    )
    order = {
        "vt_symbol": symbol,
        "signal_date": signal_date,
        "reason": {
            "entry_setup": "dragon_pullback",
            "support_type": "ma10_support",
            "support_price": 69.5,
            "ma5": 73.0,
            "ma10": 69.5,
        },
    }

    fill = resolve_buy_fill(
        order,
        execute_date,
        execute_bar,
        {symbol: {signal_date: signal_bar, execute_date: execute_bar}},
        {},
        params,
    )

    assert fill["status"] == "filled"
    assert fill["mode"] == "daily_close_proxy"
    assert fill["ma5"] == 69.5
    assert abs(fill["ma5_distance_pct"]) <= 1.5


def test_symbol_strategy_comparison_aggregates_registered_strategies(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    monkeypatch.setattr(
        screening,
        "list_available_strategies",
        lambda: {
            "status": "ready",
            "items": [
                {"id": "mainline_leader_pullback", "version": "0.1.1", "name": "低吸", "default_min_entry_score": 68.0},
                {"id": "breakout_confirmation", "version": "0.1.0", "name": "突破", "default_min_entry_score": 70.0},
            ],
        },
    )

    def fake_history(vt_symbol, *, strategy_id, start, end, min_entry_score, limit):
        return {
            "status": "ready",
            "vt_symbol": vt_symbol,
            "name": "金安国纪",
            "board": "main",
            "board_label": "主板",
            "strategy_id": strategy_id,
            "strategy_version": "0.1.x",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "scored_date_count": 9 if strategy_id == "mainline_leader_pullback" else 6,
            "entry_signal_count": 2 if strategy_id == "mainline_leader_pullback" else 1,
            "watch_count": 7 if strategy_id == "mainline_leader_pullback" else 5,
            "entry_signals": [{"trade_date": "2026-01-02", "entry_signal": True}],
            "best_total_score": {"trade_date": "2026-01-03", "total_score": 80},
            "best_entry_fit": {"trade_date": "2026-01-02", "total_score": 78},
            "recent": [{"trade_date": "2026-01-04", "entry_signal": False}],
            "financial_coverage": {"usable_report_count": 3},
            "rule": {"min_entry_score": min_entry_score},
        }

    monkeypatch.setattr(screening, "symbol_signal_history", fake_history)

    result = screening.symbol_strategy_comparison(
        "002636.SZSE",
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        limit=5,
    )

    assert result["status"] == "ready"
    assert result["vt_symbol"] == "002636.SZSE"
    assert result["name"] == "金安国纪"
    assert result["financial_coverage"]["usable_report_count"] == 3
    assert [item["strategy_id"] for item in result["items"]] == ["mainline_leader_pullback", "breakout_confirmation"]
    assert result["items"][0]["scored_date_count"] == 9
    assert result["items"][0]["entry_signal_count"] == 2
    assert result["items"][0]["watch_count"] == 7
    assert result["items"][1]["rule"]["min_entry_score"] == 70.0


def test_symbol_strategy_comparison_api_passes_date_range(monkeypatch) -> None:
    from alphaagent.server.api import quant

    captured = {}

    def fake_comparison(vt_symbol, *, start, end, limit):
        captured.update({"vt_symbol": vt_symbol, "start": start, "end": end, "limit": limit})
        return {"status": "ready", "vt_symbol": vt_symbol, "items": []}

    monkeypatch.setattr(quant.screening, "symbol_strategy_comparison", fake_comparison)

    client = TestClient(create_app())
    response = client.get("/api/quant/symbols/002636.SZSE/strategy-comparison?start=2025-10-14&end=2026-06-13&limit=7")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ready"
    assert captured == {
        "vt_symbol": "002636.SZSE",
        "start": date(2025, 10, 14),
        "end": date(2026, 6, 13),
        "limit": 7,
    }


def test_symbol_diagnostics_summarizes_entry_signal_without_trade(monkeypatch) -> None:
    from alphaagent.server.services.quant import symbol_diagnostics

    def fake_comparison(vt_symbol, *, start, end, limit):
        return {
            "status": "ready",
            "vt_symbol": vt_symbol,
            "name": "金安国纪",
            "board": "main",
            "board_label": "主板",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "items": [
                {
                    "strategy_id": "mainline_leader_pullback",
                    "strategy_name": "低吸",
                    "entry_signal_count": 1,
                    "watch_count": 3,
                    "entry_signals": [{"trade_date": "2026-02-09", "entry_signal": True}],
                    "best_entry_fit": {"trade_date": "2026-02-09", "total_score": 84.4},
                },
                {
                    "strategy_id": "limit_up_after_pullback",
                    "strategy_name": "涨停后回踩",
                    "entry_signal_count": 2,
                    "watch_count": 4,
                    "entry_signals": [{"trade_date": "2026-04-30", "entry_signal": True}],
                    "best_entry_fit": {"trade_date": "2026-04-30", "total_score": 85.8},
                }
            ],
            "financial_coverage": {"usable_report_count": 20},
        }

    def fake_symbol_detail(backtest_id, vt_symbol):
        return {
            "status": "empty",
            "backtest_id": backtest_id,
            "vt_symbol": vt_symbol,
            "orders": [],
            "trades": [],
            "positions": [],
        }

    monkeypatch.setattr(symbol_diagnostics.screening, "symbol_strategy_comparison", fake_comparison)
    monkeypatch.setattr(symbol_diagnostics.backtest_engine, "backtest_symbol_detail", fake_symbol_detail)

    result = symbol_diagnostics.symbol_diagnostics_report(
        "002636.SZSE",
        start=date(2026, 2, 2),
        end=date(2026, 6, 13),
        backtest_id=62,
    )

    assert result["status"] == "ready"
    assert result["name"] == "金安国纪"
    assert result["summary"]["has_entry_signal"] is True
    assert result["summary"]["entry_signal_count"] == 3
    assert result["summary"]["best_signal_date"] == "2026-02-09"
    assert result["summary"]["strategy_signal_counts"] == [
        {
            "strategy_id": "mainline_leader_pullback",
            "strategy_name": "低吸",
            "entry_signal_count": 1,
            "watch_count": 3,
            "best_signal_date": "2026-02-09",
            "best_entry_score": 84.4,
        },
        {
            "strategy_id": "limit_up_after_pullback",
            "strategy_name": "涨停后回踩",
            "entry_signal_count": 2,
            "watch_count": 4,
            "best_signal_date": "2026-04-30",
            "best_entry_score": 85.8,
        },
    ]
    assert result["summary"]["has_trade"] is False
    assert result["summary"]["status"] == "needs_signal_date"
    assert result["summary"]["not_traded_context"]["needs_signal_date"] is True
    assert "选择 BUY 信号日" in result["summary"]["next_action"]


def test_symbol_diagnostics_prioritizes_rejected_order_reason(monkeypatch) -> None:
    from alphaagent.server.services.quant import symbol_diagnostics

    def fake_comparison(vt_symbol, *, start, end, limit):
        del start, end, limit
        return {
            "status": "ready",
            "vt_symbol": vt_symbol,
            "name": "金安国纪",
            "items": [
                {
                    "strategy_id": "mainline_leader_pullback",
                    "entry_signal_count": 1,
                    "entry_signals": [{"trade_date": "2026-02-09", "entry_signal": True}],
                }
            ],
        }

    def fake_symbol_detail(backtest_id, vt_symbol):
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "vt_symbol": vt_symbol,
            "orders": [{"status": "rejected", "reason": "position_slot_unavailable", "reason_label": "未形成组合成交"}],
            "trades": [],
            "positions": [],
        }

    def fake_candidate_trace(backtest_id, vt_symbol, signal_date):
        del backtest_id, vt_symbol, signal_date
        return {
            "status": "rejected",
            "action": "BUY",
            "rank": 2,
            "total_score": 84.4645,
            "planned_execute_date": "2026-02-10",
            "linked_order_reason": "insufficient_cash",
            "linked_order_reason_label": "现金不足",
            "summary": "真实组合订单被拒绝：insufficient_cash。",
            "orders": [{"status": "rejected", "reason": "insufficient_cash", "reason_label": "现金不足"}],
            "trades": [],
            "equity": {
                "cash": 12_000.0,
                "market_value": 988_000.0,
                "total_equity": 1_000_000.0,
                "position_count": 8,
            },
        }

    monkeypatch.setattr(symbol_diagnostics.screening, "symbol_strategy_comparison", fake_comparison)
    monkeypatch.setattr(symbol_diagnostics.backtest_engine, "backtest_symbol_detail", fake_symbol_detail)
    monkeypatch.setattr(symbol_diagnostics.backtest_engine, "backtest_candidate_trace", fake_candidate_trace)

    result = symbol_diagnostics.symbol_diagnostics_report(
        "002636.SZSE",
        start=date(2026, 2, 2),
        end=date(2026, 6, 13),
        backtest_id=62,
        signal_date=date(2026, 2, 9),
    )

    summary = result["summary"]
    assert summary["status"] == "rejected"
    assert summary["main_reason"] == "insufficient_cash"
    assert summary["main_reason_label"] == "现金不足"
    assert summary["main_reason_source"] == "linked_order"
    assert summary["candidate_action"] == "BUY"
    assert summary["candidate_rank"] == 2
    assert summary["candidate_score"] == 84.4645
    assert summary["planned_execute_date"] == "2026-02-10"
    assert summary["signal_day_cash"] == 12_000.0
    assert summary["signal_day_market_value"] == 988_000.0
    assert summary["signal_day_total_equity"] == 1_000_000.0
    assert summary["signal_day_position_count"] == 8
    assert summary["not_traded_context"]["candidate_action"] == "BUY"
    assert summary["not_traded_context"]["planned_execute_date"] == "2026-02-10"
    assert summary["diagnostic_checks"][0] == {"label": "单股BUY信号", "status": "pass"}
    assert {"label": "真实买入成交", "status": "fail"} in summary["diagnostic_checks"]
    assert "候选独立买卖质量" in summary["next_action"]


def test_symbol_diagnostics_api_passes_backtest_and_signal_date(monkeypatch) -> None:
    from alphaagent.server.api import quant

    captured = {}

    def fake_diagnostics(vt_symbol, *, start, end, backtest_id, signal_date, limit):
        captured.update(
            {
                "vt_symbol": vt_symbol,
                "start": start,
                "end": end,
                "backtest_id": backtest_id,
                "signal_date": signal_date,
                "limit": limit,
            }
        )
        return {
            "status": "ready",
            "vt_symbol": vt_symbol,
            "summary": {"status": "rejected"},
            "strategy_comparison": {"items": []},
        }

    monkeypatch.setattr(quant, "symbol_diagnostics_report", fake_diagnostics)

    client = TestClient(create_app())
    response = client.get(
        "/api/quant/symbols/002636.SZSE/diagnostics"
        "?start=2026-02-02&end=2026-06-13&backtest_id=62&signal_date=2026-02-09&limit=5"
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ready"
    assert captured == {
        "vt_symbol": "002636.SZSE",
        "start": date(2026, 2, 2),
        "end": date(2026, 6, 13),
        "backtest_id": 62,
        "signal_date": date(2026, 2, 9),
        "limit": 5,
    }


def test_backtest_strategy_comparison_runs_selected_strategies(monkeypatch) -> None:
    from alphaagent.server.services.backtest import strategy_comparison
    from alphaagent.server.services.backtest.schemas import BacktestParams

    monkeypatch.setattr(
        strategy_comparison,
        "list_internal_strategies",
        lambda: [
            {"id": "mainline_leader_pullback", "version": "0.1.1", "name": "低吸"},
            {"id": "breakout_confirmation", "version": "0.1.0", "name": "突破"},
        ],
    )

    def fake_run(params):
        if params.strategy == "mainline_leader_pullback":
            return {
                "status": "ready",
                "strategy_version": "0.1.1",
                "metrics": {
                    "final_equity": 950000,
                    "total_return_pct": -5.0,
                    "max_drawdown_pct": -9.0,
                    "minute_1430_count": 1,
                    "daily_close_proxy_count": 0,
                },
                "trades": [{"side": "BUY"}, {"side": "SELL"}],
                "orders": [{"status": "rejected", "reason": "tail_entry_not_triggered", "raw": {"execution_model": "strict_1430"}}],
                "signal_events": [{"side": "BUY"}],
            }
        return {
            "status": "ready",
            "strategy_version": "0.1.0",
            "metrics": {
                "final_equity": 1020000,
                "total_return_pct": 2.0,
                "max_drawdown_pct": -1.0,
                "minute_1430_count": 2,
                "daily_close_proxy_count": 0,
            },
            "trades": [{"side": "BUY"}, {"side": "BUY"}, {"side": "SELL"}],
            "orders": [],
            "signal_events": [{"side": "BUY"}, {"side": "BUY"}],
        }

    result = strategy_comparison.compare_strategies(
        BacktestParams(start=date(2026, 2, 2), max_symbols=80, persist=True),
        strategies=["mainline_leader_pullback", "breakout_confirmation"],
        run_backtest=fake_run,
    )

    assert result["status"] == "ready"
    assert result["params"]["persist"] is False
    assert [row["strategy_id"] for row in result["rows"]] == ["mainline_leader_pullback", "breakout_confirmation"]
    assert result["rows"][0]["buy_signal_count"] == 1
    assert result["rows"][0]["strict_1430_rejected_count"] == 1
    assert result["rows"][0]["quality_status"] == "strict_condition_rejections"
    assert result["rows"][1]["minute_1430_ratio"] == 100.0
    assert result["rows"][1]["quality_status"] == "complete_strict"
    assert result["summary"]["best_strategy_id"] == "breakout_confirmation"
    assert result["summary"]["best_verifiable_strategy_id"] == "breakout_confirmation"


def test_backtest_strategy_comparison_adds_readonly_market_phase_summary(monkeypatch) -> None:
    from alphaagent.server.services.backtest import strategy_comparison
    from alphaagent.server.services.backtest.schemas import BacktestParams

    monkeypatch.setattr(
        strategy_comparison,
        "list_internal_strategies",
        lambda: [
            {"id": "dragon", "version": "0.1.0", "name": "龙回头"},
        ],
    )

    def fake_run(_params):
        return {
            "status": "ready",
            "strategy_version": "0.1.0",
            "metrics": {
                "final_equity": 1_000_000,
                "total_return_pct": 0.0,
                "max_drawdown_pct": -3.0,
                "minute_1430_count": 0,
                "daily_close_proxy_count": 0,
            },
            "trades": [
                {
                    "trade_date": "2026-01-02",
                    "vt_symbol": "A.SSE",
                    "side": "BUY",
                    "price": 10.0,
                    "amount": 10_000.0,
                    "raw": {
                        "dynamic_market_regime": "narrow_theme_bull",
                        "market_warning_level": 1,
                        "market_score": 68.0,
                        "theme_strength": 80.0,
                    },
                },
                {
                    "trade_date": "2026-01-06",
                    "vt_symbol": "A.SSE",
                    "side": "SELL",
                    "price": 11.0,
                    "amount": 11_000.0,
                    "pnl": 1_000.0,
                    "reason": "trend_trailing_stop",
                },
                {
                    "trade_date": "2026-02-02",
                    "vt_symbol": "B.SSE",
                    "side": "BUY",
                    "price": 10.0,
                    "amount": 10_000.0,
                    "raw": {
                        "dynamic_market_regime": "weak_defensive",
                        "market_warning_level": 3,
                        "recovery_state": "none",
                        "fund_flow_state": "continuous_outflow",
                    },
                },
                {
                    "trade_date": "2026-02-05",
                    "vt_symbol": "B.SSE",
                    "side": "SELL",
                    "price": 9.5,
                    "amount": 9_500.0,
                    "pnl": -500.0,
                    "reason": "support_stop",
                },
            ],
            "orders": [],
            "signal_events": [{"side": "BUY"}],
        }

    result = strategy_comparison.compare_strategies(
        BacktestParams(start=date(2026, 1, 1), max_symbols=80),
        strategies=["dragon"],
        run_backtest=fake_run,
    )

    row = result["rows"][0]
    summary = row["phase_summary"]
    buckets = {item["phase"]: item for item in summary["by_phase"]}

    assert summary["status"] == "ready"
    assert summary["not_used_for_signal_score"] is True
    assert summary["trade_count"] == 2
    assert buckets["uptrend"]["label"] == "主升"
    assert buckets["uptrend"]["win_rate_pct"] == 100.0
    assert buckets["uptrend"]["avg_return_pct"] == 10.0
    assert buckets["retreat"]["label"] == "退潮"
    assert buckets["retreat"]["win_rate_pct"] == 0.0
    assert buckets["retreat"]["support_stop_count"] == 1
    assert row["phase_rank_hint"]["best_phase"] == "uptrend"


def test_backtest_strategy_comparison_uses_external_market_context_when_trade_raw_is_empty(monkeypatch) -> None:
    from alphaagent.server.services.backtest import strategy_comparison
    from alphaagent.server.services.backtest.schemas import BacktestParams

    monkeypatch.setattr(
        strategy_comparison,
        "list_internal_strategies",
        lambda: [{"id": "pullback", "version": "0.1.0", "name": "低吸"}],
    )

    def fake_run(_params):
        return {
            "status": "ready",
            "metrics": {
                "final_equity": 1_000_000,
                "total_return_pct": 0.0,
                "max_drawdown_pct": -1.0,
                "minute_1430_count": 0,
                "daily_close_proxy_count": 0,
            },
            "trades": [
                {"trade_date": date(2026, 3, 2), "vt_symbol": "A.SSE", "side": "BUY", "price": 10.0, "amount": 10_000.0},
                {"trade_date": date(2026, 3, 6), "vt_symbol": "A.SSE", "side": "SELL", "price": 10.3, "amount": 10_300.0, "pnl": 300.0},
            ],
            "orders": [],
            "signal_events": [],
        }

    captured_dates = []

    def fake_load_market_contexts(trade_dates):
        captured_dates.extend(trade_dates)
        return {
            date(2026, 3, 2): {
                "regime": "weak_rebound",
                "market_warning_level": 2,
                "recovery_state": "warming_confirmed",
                "market_score": 58.0,
            }
        }

    result = strategy_comparison.compare_strategies(
        BacktestParams(start=date(2026, 3, 1), max_symbols=80),
        strategies=["pullback"],
        run_backtest=fake_run,
        load_market_contexts=fake_load_market_contexts,
    )

    buckets = {item["phase"]: item for item in result["rows"][0]["phase_summary"]["by_phase"]}
    assert captured_dates == [date(2026, 3, 2)]
    assert buckets["warming"]["label"] == "回暖"
    assert buckets["warming"]["avg_return_pct"] == 3.0


def test_backtest_strategy_comparison_adds_candidate_topn_phase_summary(monkeypatch) -> None:
    from alphaagent.server.services.backtest import strategy_comparison
    from alphaagent.server.services.backtest.schemas import BacktestParams

    monkeypatch.setattr(
        strategy_comparison,
        "list_internal_strategies",
        lambda: [{"id": "dragon", "version": "0.1.0", "name": "龙回头"}],
    )

    def fake_run(_params):
        return {
            "status": "ready",
            "strategy_version": "0.1.0",
            "metrics": {
                "final_equity": 1_000_000,
                "total_return_pct": 0.0,
                "max_drawdown_pct": -1.0,
                "minute_1430_count": 0,
                "daily_close_proxy_count": 0,
            },
            "trades": [],
            "orders": [],
            "signal_events": [
                {
                    "trade_date": date(2026, 3, 3),
                    "signal_date": date(2026, 3, 2),
                    "execute_date": date(2026, 3, 3),
                    "vt_symbol": "A.SSE",
                    "side": "BUY",
                    "price": 10.0,
                    "score": 92.0,
                    "raw": {
                        "status": "filled",
                        "evidence": {
                            "entry_setup": "stealth_low_suction",
                            "dynamic_market_regime": "weak_rebound",
                            "market_warning_level": 2,
                            "recovery_state": "warming_confirmed",
                        },
                        "candidate_execution": {
                            "raw_signal_rank": 1,
                            "execution_candidate_rank": 1,
                            "execution_candidate_selected": True,
                        },
                    },
                },
                {
                    "trade_date": date(2026, 3, 3),
                    "signal_date": date(2026, 3, 2),
                    "execute_date": date(2026, 3, 3),
                    "vt_symbol": "B.SSE",
                    "side": "BUY",
                    "price": 20.0,
                    "score": 91.0,
                    "raw": {
                        "status": "filled",
                        "evidence": {
                            "entry_setup": "dragon_pullback",
                            "dynamic_market_regime": "weak_defensive",
                            "market_warning_level": 3,
                            "recovery_state": "none",
                        },
                        "candidate_execution": {
                            "raw_signal_rank": 2,
                            "execution_candidate_rank": None,
                            "execution_candidate_selected": False,
                        },
                    },
                },
                {
                    "trade_date": date(2026, 3, 6),
                    "signal_date": date(2026, 3, 5),
                    "execute_date": date(2026, 3, 6),
                    "vt_symbol": "A.SSE",
                    "side": "SELL",
                    "price": 11.0,
                    "reason": "trend_trailing_stop",
                    "raw": {"status": "filled", "reason": "trend_trailing_stop"},
                },
                {
                    "trade_date": date(2026, 3, 7),
                    "signal_date": date(2026, 3, 6),
                    "execute_date": date(2026, 3, 7),
                    "vt_symbol": "B.SSE",
                    "side": "SELL",
                    "price": 18.0,
                    "reason": "support_stop",
                    "raw": {"status": "filled", "reason": "support_stop"},
                },
            ],
        }

    result = strategy_comparison.compare_strategies(
        BacktestParams(start=date(2026, 3, 1), max_symbols=80, candidate_limit=1),
        strategies=["dragon"],
        run_backtest=fake_run,
    )

    summary = result["rows"][0]["candidate_phase_summary"]
    buckets = {item["phase"]: item for item in summary["by_phase"]}

    assert summary["status"] == "ready"
    assert summary["top_limit"] == 1
    assert summary["signal_count"] == 1
    assert summary["evaluated_count"] == 1
    assert summary["best_phase"] == "warming"
    assert buckets["warming"]["label"] == "回暖"
    assert buckets["warming"]["signal_count"] == 1
    assert buckets["warming"]["win_rate_pct"] == 100.0
    assert round(buckets["warming"]["avg_return_pct"], 4) == 10.0
    assert "retreat" not in buckets


def test_backtest_strategy_comparison_treats_zero_return_as_valid(monkeypatch) -> None:
    from alphaagent.server.services.backtest import strategy_comparison
    from alphaagent.server.services.backtest.schemas import BacktestParams

    monkeypatch.setattr(
        strategy_comparison,
        "list_internal_strategies",
        lambda: [
            {"id": "mainline_leader_pullback", "version": "0.1.1", "name": "低吸"},
            {"id": "breakout_confirmation", "version": "0.1.0", "name": "突破"},
        ],
    )

    def fake_run(params):
        returns = {
            "mainline_leader_pullback": -5.0819,
            "breakout_confirmation": 0.0,
        }
        return {
            "status": "ready",
            "strategy_version": "0.1.0",
            "metrics": {
                "final_equity": 1_000_000,
                "total_return_pct": returns[params.strategy],
                "max_drawdown_pct": 0.0,
                "minute_1430_count": 0,
                "daily_close_proxy_count": 0,
            },
            "trades": [],
            "orders": [],
            "signal_events": [{"side": "BUY"}],
        }

    result = strategy_comparison.compare_strategies(
        BacktestParams(start=date(2026, 2, 2), max_symbols=80, persist=True),
        strategies=["mainline_leader_pullback", "breakout_confirmation"],
        run_backtest=fake_run,
    )

    assert result["summary"]["best_strategy_id"] == "breakout_confirmation"
    assert result["summary"]["best_total_return_pct"] == 0.0
    assert result["summary"]["best_verifiable_strategy_id"] is None
    assert result["rows"][1]["quality_status"] == "no_fills"
    assert "不能验证收益" in result["rows"][1]["quality_warning"]


def test_backtest_strategy_comparison_treats_strict_condition_rejections_as_verifiable(monkeypatch) -> None:
    from alphaagent.server.services.backtest import strategy_comparison
    from alphaagent.server.services.backtest.schemas import BacktestParams

    monkeypatch.setattr(
        strategy_comparison,
        "list_internal_strategies",
        lambda: [
            {"id": "pullback", "version": "0.1.1", "name": "低吸"},
            {"id": "breakout", "version": "0.1.0", "name": "突破"},
        ],
    )

    def fake_run(params):
        if params.strategy == "pullback":
            return {
                "status": "ready",
                "metrics": {
                    "final_equity": 950000,
                    "total_return_pct": -5.0,
                    "max_drawdown_pct": -9.0,
                    "minute_1430_count": 21,
                    "daily_close_proxy_count": 0,
                },
                "trades": [{"side": "BUY"}],
                "orders": [{"status": "rejected", "reason": "tail_entry_not_triggered", "raw": {"execution_model": "strict_1430"}}],
                "signal_events": [{"side": "BUY"}],
            }
        return {
            "status": "ready",
            "metrics": {
                "final_equity": 1_000_000,
                "total_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "minute_1430_count": 0,
                "daily_close_proxy_count": 0,
            },
            "trades": [],
            "orders": [{"status": "rejected", "reason": "missing_1430_snapshot", "raw": {"execution_model": "strict_1430", "reason": "missing_1430_snapshot"}}],
            "signal_events": [{"side": "BUY"}],
        }

    result = strategy_comparison.compare_strategies(
        BacktestParams(start=date(2026, 2, 2), max_symbols=80),
        strategies=["pullback", "breakout"],
        run_backtest=fake_run,
    )

    assert result["summary"]["best_strategy_id"] == "breakout"
    assert result["summary"]["best_verifiable_strategy_id"] == "pullback"
    assert result["rows"][0]["quality_status"] == "strict_condition_rejections"
    assert result["rows"][1]["quality_status"] == "missing_snapshots"


def test_backtest_strategy_comparison_marks_missing_snapshots_and_proxy_quality(monkeypatch) -> None:
    from alphaagent.server.services.backtest import strategy_comparison
    from alphaagent.server.services.backtest.schemas import BacktestParams

    monkeypatch.setattr(
        strategy_comparison,
        "list_internal_strategies",
        lambda: [
            {"id": "missing", "version": "0.1.0", "name": "缺快照"},
            {"id": "proxy", "version": "0.1.0", "name": "收盘代理"},
        ],
    )

    def fake_run(params):
        if params.strategy == "missing":
            return {
                "status": "ready",
                "metrics": {
                    "final_equity": 1_000_000,
                    "total_return_pct": 0.0,
                    "max_drawdown_pct": 0.0,
                    "minute_1430_count": 0,
                    "daily_close_proxy_count": 0,
                },
                "trades": [],
                "orders": [
                    {
                        "status": "rejected",
                        "reason": "missing_1430_snapshot",
                        "raw": {"execution_model": "strict_1430", "reason": "missing_1430_snapshot"},
                    }
                ],
                "signal_events": [{"side": "BUY"}],
            }
        return {
            "status": "ready",
            "metrics": {
                "final_equity": 1_001_000,
                "total_return_pct": 0.1,
                "max_drawdown_pct": -0.1,
                "minute_1430_count": 0,
                "daily_close_proxy_count": 1,
            },
            "trades": [{"side": "BUY"}],
            "orders": [],
            "signal_events": [{"side": "BUY"}],
        }

    result = strategy_comparison.compare_strategies(
        BacktestParams(start=date(2026, 2, 2), max_symbols=80),
        strategies=["missing", "proxy"],
        run_backtest=fake_run,
    )

    assert result["rows"][0]["quality_status"] == "missing_snapshots"
    assert result["rows"][0]["minute_gap_rejected_count"] == 1
    assert result["rows"][1]["quality_status"] == "uses_daily_close_proxy"
    assert result["summary"]["complete_strict_count"] == 0


def test_backtest_scoring_skips_symbols_without_bar_on_signal_date() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    signal_date = date(2026, 6, 12)
    stale_date = date(2026, 6, 11)
    scored_symbols: list[str] = []

    def fake_score_candidates_for_day(session, bars_by_symbol, trade_date, params, score_context):
        del session, params, score_context
        results = []
        for vt_symbol in bars_by_symbol:
            scored_symbols.append(vt_symbol)
            results.append(
                SignalScore(
                    vt_symbol=vt_symbol,
                    trade_date=trade_date,
                    total_score=80.0,
                    liquidity_score=80.0,
                    risk_score=80.0,
                    entry_signal=True,
                    evidence={"status": "ready"},
                )
            )
        return results

    fresh_bar = Bar(signal_date, 10.0, 10.5, 9.8, 10.2, volume=1_000_000, turnover=200_000_000)
    stale_bar = Bar(stale_date, 20.0, 20.5, 19.8, 20.2, volume=1_000_000, turnover=200_000_000)

    candidates = scoring.score_day(
        None,
        {"600000.SSE": [fresh_bar], "000001.SZSE": [stale_bar]},
        signal_date,
        BacktestParams(strict_entry=True),
        score_candidates_for_day=fake_score_candidates_for_day,
    )

    assert scored_symbols == ["600000.SSE"]
    assert [candidate.vt_symbol for candidate in candidates] == ["600000.SSE"]


def test_run_backtest_returns_signal_events_for_strategy_comparison(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    trading_days = [date(2026, 1, 1) + timedelta(days=index) for index in range(85)]
    bars_by_symbol = {"600000.SSE": _bars(85)}

    class FakeSession:
        def execute(self, statement):
            del statement
            raise AssertionError("unexpected execute")

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(engine, "is_database_configured", lambda: True)
    monkeypatch.setattr(engine, "_ensure_backtest_schema", lambda: None)
    monkeypatch.setattr(engine, "session_scope", fake_session_scope)
    monkeypatch.setattr(engine, "_load_symbol_universe", lambda session, max_symbols, symbols, included_boards: ["600000.SSE"])
    captured = {}

    def fake_load_all_bars(session, vt_symbols, start, end):
        captured["load_start"] = start
        captured["load_end"] = end
        return bars_by_symbol

    monkeypatch.setattr(engine, "_load_all_bars", fake_load_all_bars)
    monkeypatch.setattr(engine, "_trading_days", lambda bars, start, end: trading_days)
    monkeypatch.setattr(engine, "_load_stock_meta", lambda session, vt_symbols: {"600000.SSE": {"name": "浦发银行"}})
    monkeypatch.setattr(engine, "_load_score_context", lambda session, vt_symbols: engine.ScoreContext())
    monkeypatch.setattr(engine, "_load_score_cache_from_persisted_signals", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        engine,
        "_simulate",
        lambda session, params, bars_by_symbol_arg, trading_days_arg, stock_meta, score_cache=None, score_context=None: {
            "metrics": {"final_equity": 100000, "total_return_pct": 0},
            "equity": [],
            "trades": [],
            "orders": [],
            "signal_events": [{"side": "BUY", "vt_symbol": "600000.SSE"}],
        },
    )

    result = engine.run_backtest(engine.BacktestParams(start=trading_days[0], end=trading_days[-1], persist=False, max_symbols=1))

    assert result["status"] == "ready"
    assert result["signal_events"] == [{"side": "BUY", "vt_symbol": "600000.SSE"}]
    assert captured["load_start"] < trading_days[0]
    assert captured["load_end"] == trading_days[-1]


def test_candidate_snapshot_rows_keep_daily_candidate_rank_and_execution_context() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.backtest.schemas import BacktestParams

    scores = [
        SignalScore(
            vt_symbol="600001.SSE",
            trade_date=date(2026, 1, 2),
            total_score=90,
            entry_signal=True,
            evidence={"entry_setup": "dragon_pullback", "action": "BUY"},
        ),
        SignalScore(
            vt_symbol="600002.SSE",
            trade_date=date(2026, 1, 2),
            total_score=89,
            entry_signal=True,
            evidence={"entry_setup": "stealth_low_suction", "low_suction_days": 6, "action": "BUY"},
        ),
    ]

    rows = engine._candidate_snapshot_rows(
        date(2026, 1, 2),
        scores,
        BacktestParams(candidate_limit=1),
    )

    assert [row["vt_symbol"] for row in rows] == ["600001.SSE", "600002.SSE"]
    assert [row["rank"] for row in rows] == [1, 2]
    payloads = [row["payload"] for row in rows]
    assert payloads[0]["source"] == "backtest_daily_candidates"
    assert payloads[0]["factor_cache_complete"] is True
    assert payloads[0]["raw_signal_rank"] == 1
    assert payloads[0]["execution_candidate_rank"] == 1
    assert payloads[1]["raw_signal_rank"] == 2
    assert payloads[1]["execution_candidate_rank"] is None


def test_run_backtest_does_not_reuse_signal_cache_by_default(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    trading_days = [date(2026, 1, 1) + timedelta(days=index) for index in range(85)]
    bars_by_symbol = {"600000.SSE": _bars(85)}

    class FakeSession:
        def execute(self, statement):
            del statement
            raise AssertionError("unexpected execute")

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(engine, "is_database_configured", lambda: True)
    monkeypatch.setattr(engine, "_ensure_backtest_schema", lambda: None)
    monkeypatch.setattr(engine, "session_scope", fake_session_scope)
    monkeypatch.setattr(engine, "_load_symbol_universe", lambda session, max_symbols, symbols, included_boards: ["600000.SSE"])
    monkeypatch.setattr(engine, "_load_all_bars", lambda session, vt_symbols, start, end: bars_by_symbol)
    monkeypatch.setattr(engine, "_trading_days", lambda bars, start, end: trading_days)
    monkeypatch.setattr(engine, "_load_stock_meta", lambda session, vt_symbols: {"600000.SSE": {"name": "浦发银行"}})
    monkeypatch.setattr(engine, "_load_score_context", lambda session, vt_symbols: engine.ScoreContext())

    def fail_if_cache_loaded(*args, **kwargs):
        del args, kwargs
        raise AssertionError("portfolio backtest must not silently reuse persisted signal cache")

    def fake_simulate(session, params, bars_by_symbol_arg, trading_days_arg, stock_meta, score_cache=None, score_context=None):
        del session, params, bars_by_symbol_arg, trading_days_arg, stock_meta, score_context
        assert score_cache is None
        return {"metrics": {}, "equity": [], "trades": [], "orders": [], "signal_events": []}

    monkeypatch.setattr(engine, "_load_score_cache_from_persisted_signals", fail_if_cache_loaded)
    monkeypatch.setattr(engine, "_simulate", fake_simulate)

    result = engine.run_backtest(engine.BacktestParams(start=trading_days[0], end=trading_days[-1], persist=False, max_symbols=1))

    assert result["status"] == "ready"
    assert result["assumptions"]["signal_cache_reuse"] == "disabled_current_code_recompute"


def test_run_backtest_reuses_signal_cache_only_when_explicit(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    trading_days = [date(2026, 1, 1) + timedelta(days=index) for index in range(85)]
    bars_by_symbol = {"600000.SSE": _bars(85)}
    cache = {trading_days[0]: [SignalScore(vt_symbol="600000.SSE", trade_date=trading_days[0])]}
    calls = {"cache_loads": 0}

    class FakeSession:
        def execute(self, statement):
            del statement
            raise AssertionError("unexpected execute")

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(engine, "is_database_configured", lambda: True)
    monkeypatch.setattr(engine, "_ensure_backtest_schema", lambda: None)
    monkeypatch.setattr(engine, "session_scope", fake_session_scope)
    monkeypatch.setattr(engine, "_load_symbol_universe", lambda session, max_symbols, symbols, included_boards: ["600000.SSE"])
    monkeypatch.setattr(engine, "_load_all_bars", lambda session, vt_symbols, start, end: bars_by_symbol)
    monkeypatch.setattr(engine, "_trading_days", lambda bars, start, end: trading_days)
    monkeypatch.setattr(engine, "_load_stock_meta", lambda session, vt_symbols: {"600000.SSE": {"name": "浦发银行"}})
    monkeypatch.setattr(engine, "_load_score_context", lambda session, vt_symbols: engine.ScoreContext())

    def fake_load_cache(*args, **kwargs):
        del args, kwargs
        calls["cache_loads"] += 1
        return cache

    def fake_simulate(session, params, bars_by_symbol_arg, trading_days_arg, stock_meta, score_cache=None, score_context=None):
        del session, params, bars_by_symbol_arg, trading_days_arg, stock_meta, score_context
        assert score_cache is cache
        return {"metrics": {}, "equity": [], "trades": [], "orders": [], "signal_events": []}

    monkeypatch.setattr(engine, "_load_score_cache_from_persisted_signals", fake_load_cache)
    monkeypatch.setattr(engine, "_simulate", fake_simulate)

    result = engine.run_backtest(
        engine.BacktestParams(
            start=trading_days[0],
            end=trading_days[-1],
            persist=False,
            max_symbols=1,
            reuse_signal_cache=True,
        )
    )

    assert result["status"] == "ready"
    assert result["assumptions"]["signal_cache_reuse"] == "enabled"
    assert calls["cache_loads"] == 1


def test_strategy_comparison_api_passes_params_and_strategies(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_comparison(params, strategies=None):
        captured.update({"params": params, "strategies": strategies})
        return {"status": "ready", "rows": [], "summary": {}}

    monkeypatch.setattr(backtests, "backtest_strategy_comparison", fake_comparison)

    client = TestClient(create_app())
    response = client.post(
        "/api/backtests/strategy-comparison",
        json={
            "start": "2026-02-02",
            "end": "2026-06-13",
            "max_symbols": 80,
            "execution_model": "strict_1430",
            "strategies": ["mainline_leader_pullback", "breakout_confirmation"],
            "persist": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ready"
    assert captured["params"].start == date(2026, 2, 2)
    assert captured["params"].end == date(2026, 6, 13)
    assert captured["params"].max_symbols == 80
    assert captured["params"].execution_model == "strict_1430"
    assert captured["params"].persist is False
    assert captured["strategies"] == ["mainline_leader_pullback", "breakout_confirmation"]


def test_quant_screening_rejects_unknown_strategy_without_database_check(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)

    result = screening.screen_stocks(strategy_id="unknown_strategy")

    assert result["status"] == "unsupported_strategy"
    assert result["strategy_id"] == "unknown_strategy"
    assert result["recommendations"] == []


def test_quant_api_mapping_normalizes_legacy_execution_labels() -> None:
    from alphaagent.server.services.quant import screening

    row = screening._mapping_to_api(
        {
            "vt_symbol": "600000.SSE",
            "reason": {"entry_rule": "daily_close_signal_next_open_execution"},
            "risk_control": {
                "execution": "D close signal; D+1 tail-window minute fill when available, otherwise next-open simulation fallback"
            },
        }
    )

    assert row["reason"]["selection_rule"] == "daily_close_visible_signal"
    assert row["reason"]["entry_setup"] == "ma5_pullback"
    assert "entry_rule" not in row["reason"]
    assert row["risk_control"]["execution"] == "daily close observable signal; execution model selected by backtest"


def test_quant_recommendation_api_resolves_legacy_buy_action_from_reason() -> None:
    from alphaagent.server.services.quant import screening_payloads

    row = screening_payloads.recommendation_row_to_api(
        {
            "trade_date": date(2026, 3, 13),
            "vt_symbol": "002240.SZSE",
            "stock_name": "盛新锂能",
            "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
            "strategy_version": "0.1.23",
            "rank": 1,
            "action": "BUY",
            "total_score": 99.5902,
            "reason": {
                "status": "ready",
                "setup_type": "stealth_low_suction",
                "entry_setup": "stealth_low_suction",
                "dragon_state": "LOW_SUCTION_BUILDUP",
                "low_suction_days": 6,
                "low_suction_launch_confirmed": False,
                "failed_rules": [],
            },
        }
    )

    assert row["action"] == "BUY"
    assert "persisted_action" not in row
    assert "action_mismatch_resolved" not in row
    assert row["failed_rules"] == []
    assert row["reason"]["signal_label"] == "低吸蓄势买点"


def test_mainline_pullback_score_uses_smart_money_proxy_inputs() -> None:
    bars = _bars()

    neutral = score_stock("600000.SSE", bars, bars[-1].trade_date)
    boosted = score_stock(
        "600000.SSE",
        bars,
        bars[-1].trade_date,
        fund_flow_score=90,
        hot_rank_score=80,
        lhb_score=70,
    )

    assert boosted.total_score > neutral.total_score
    assert boosted.evidence["smart_money_proxy_score"] == 83.0
    assert "not proof of main-force intent" in boosted.evidence["smart_money_note"]


def test_mainline_pullback_liquidity_estimates_a_share_volume_lots() -> None:
    bars = _bars()
    bars = [
        Bar(
            trade_date=bar.trade_date,
            open_price=bar.open_price,
            high_price=bar.high_price,
            low_price=bar.low_price,
            close_price=100.0,
            volume=1_000_000,
            turnover=None,
            change_pct=bar.change_pct,
        )
        for bar in bars
    ]

    score = score_stock("600000.SSE", bars, bars[-1].trade_date)

    assert score.evidence["turnover_estimated_from_volume"] is True
    assert score.evidence["turnover20"] == 10_000_000_000
    assert score.liquidity_score == 100.0


def test_quant_smart_money_loaders_score_observable_tables() -> None:
    from alphaagent.server.services.quant import screening

    trade_date = date(2026, 1, 20)

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def mappings(self):
            return self

        def all(self):
            return self._rows

    class FakeSession:
        def __init__(self, rows):
            self.rows = rows

        def execute(self, statement):
            del statement
            return FakeResult(self.rows)

    fund_scores = screening._load_fund_flow_scores(
        FakeSession(
            [
                {
                    "vt_symbol": "600000.SSE",
                    "trade_date": "2026-01-20",
                    "main_net_inflow": 80_000_000,
                    "main_net_inflow_ratio": 6.0,
                    "super_large_net_inflow": 40_000_000,
                    "large_net_inflow": 30_000_000,
                }
            ]
        ),
        ["600000.SSE"],
        trade_date,
    )
    hot_scores = screening._load_hot_rank_scores(
        FakeSession([{"vt_symbol": "600000.SSE", "rank_time": "2026-01-20T10:00:00", "rank": 5, "rank_change": -2}]),
        ["600000.SSE"],
        trade_date,
    )
    lhb_scores = screening._load_lhb_scores(
        FakeSession(
            [
                {
                    "vt_symbol": "600000.SSE",
                    "trade_date": "2026-01-19",
                    "net_amount": 60_000_000,
                    "buy_amount": 120_000_000,
                    "sell_amount": 60_000_000,
                }
            ]
        ),
        ["600000.SSE"],
        trade_date,
    )

    assert fund_scores["600000.SSE"] > 70
    assert hot_scores["600000.SSE"] > 90
    assert lhb_scores["600000.SSE"] > 70


def test_screen_stocks_skips_symbols_without_current_trade_date_bar(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    trade_date = date(2026, 6, 16)
    scored_symbols: list[str] = []

    class FakeSession:
        pass

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    def fake_score_strategy(strategy_id, vt_symbol, bars, as_of, **kwargs):
        del strategy_id, bars, as_of, kwargs
        scored_symbols.append(vt_symbol)
        return SignalScore(
            vt_symbol=vt_symbol,
            trade_date=trade_date,
            total_score=80.0,
            liquidity_score=80.0,
            risk_score=80.0,
            entry_signal=True,
            evidence={"status": "ready"},
        )

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_trade_date", lambda session: trade_date)
    monkeypatch.setattr(screening, "_latest_complete_trade_date", lambda session: trade_date)
    monkeypatch.setattr(screening, "_daily_symbol_count", lambda session, target: 4064)
    monkeypatch.setattr(screening, "_load_stock_universe", lambda session, max_symbols, boards: [
        {"vt_symbol": "600000.SSE", "exchange": "SSE", "name": "浦发银行"},
        {"vt_symbol": "000001.SZSE", "exchange": "SZSE", "name": "平安银行"},
    ])
    monkeypatch.setattr(screening, "_load_bars", lambda session, symbols, as_of, lookback_days: {
        "600000.SSE": [Bar(trade_date, 10.0, 10.4, 9.8, 10.2, volume=1_000_000, turnover=200_000_000)],
        "000001.SZSE": [Bar(date(2026, 6, 15), 20.0, 20.4, 19.8, 20.2, volume=1_000_000, turnover=200_000_000)],
    })
    monkeypatch.setattr(screening, "_load_index_return_20d", lambda session, as_of: None)
    monkeypatch.setattr(screening, "_load_sector_scores", lambda session, symbols, as_of: {})
    monkeypatch.setattr(screening, "_load_financial_scores", lambda session, symbols, as_of: {})
    monkeypatch.setattr(screening, "_load_fund_flow_scores", lambda session, symbols, as_of: {})
    monkeypatch.setattr(screening, "_load_hot_rank_scores", lambda session, symbols, as_of: {})
    monkeypatch.setattr(screening, "_load_lhb_scores", lambda session, symbols, as_of: {})
    monkeypatch.setattr(screening, "score_strategy", fake_score_strategy)

    result = screening.screen_stocks(trade_date, max_symbols=2, included_boards=["main"])

    assert scored_symbols == ["600000.SSE"]
    assert result["total"] == 1
    assert result["recommendation_count"] == 1


def test_screen_stocks_rejects_incomplete_daily_date_without_scoring(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    trade_date = date(2026, 7, 7)
    latest_complete = date(2026, 7, 6)
    scored = {"called": False}

    class FakeSession:
        pass

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    def fail_score(*args, **kwargs):
        del args, kwargs
        scored["called"] = True
        raise AssertionError("incomplete daily date must not be scored")

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_trade_date", lambda session: trade_date)
    monkeypatch.setattr(screening, "_latest_complete_trade_date", lambda session: latest_complete)
    monkeypatch.setattr(screening, "_daily_symbol_count", lambda session, target: 1446 if target == trade_date else 5524)
    monkeypatch.setattr(screening, "score_strategy", fail_score)

    result = screening.screen_stocks(trade_date, persist=True, included_boards=["main"])

    assert result["status"] == "incomplete_daily_data"
    assert result["trade_date"] == "2026-07-07"
    assert result["latest_complete_trade_date"] == "2026-07-06"
    assert result["trade_date_daily_symbol_count"] == 1446
    assert result["min_complete_daily_symbol_count"] == 3000
    assert result["run_id"] is None
    assert result["items"] == []
    assert result["recommendations"] == []
    assert scored["called"] is False


def test_latest_screen_run_defaults_to_latest_complete_daily_date(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    captured: dict[str, object] = {}

    class FakeSession:
        pass

    def fake_latest_screen_run(session, strategy_id, strategy_version, trade_date=None, **kwargs):
        del session
        captured.update(
            {
                "strategy_id": strategy_id,
                "strategy_version": strategy_version,
                "trade_date": trade_date,
                "max_trade_date": kwargs.get("max_trade_date"),
            }
        )
        return {"id": 9, "trade_date": date(2026, 7, 6)}

    monkeypatch.setattr(screening, "_latest_complete_trade_date", lambda session: date(2026, 7, 6))
    monkeypatch.setattr(screening.screening_loaders, "latest_screen_run", fake_latest_screen_run)

    run = screening._latest_screen_run(FakeSession(), screening.STRATEGY_ID)

    assert run["id"] == 9
    assert captured["trade_date"] is None
    assert captured["max_trade_date"] == date(2026, 7, 6)


def test_screen_tail_preview_uses_intraday_temp_bar_without_persisting(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    today = date(2026, 6, 18)
    base_date = date(2026, 6, 17)
    persisted = {"called": False}
    scored_bars: list[Bar] = []

    class FakeSession:
        pass

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    base_bars = [
        Bar(base_date - timedelta(days=90 - index), 10.0, 10.3, 9.9, 10.0 + index * 0.02, volume=1_000_000, turnover=100_000_000)
        for index in range(90)
    ]
    base_bars[-1] = Bar(base_date, 11.0, 11.3, 10.8, 11.0, volume=1_000_000, turnover=110_000_000)
    intraday_bar = Bar(today, 11.0, 11.6, 10.9, 11.5, volume=500_000, turnover=60_000_000, change_pct=4.5)

    def fake_score_strategy(strategy_id, vt_symbol, bars, as_of, **kwargs):
        del strategy_id, kwargs
        scored_bars[:] = bars
        return SignalScore(
            vt_symbol=vt_symbol,
            trade_date=as_of,
            total_score=82.0,
            liquidity_score=80.0,
            risk_score=80.0,
            entry_signal=True,
            evidence={"status": "ready", "entry_setup": "stealth_low_suction"},
        )

    def fail_persist(*args, **kwargs):
        del args, kwargs
        persisted["called"] = True
        raise AssertionError("tail preview must not persist")

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_trade_date", lambda session: today)
    monkeypatch.setattr(screening, "_latest_complete_trade_date", lambda session: base_date)
    monkeypatch.setattr(screening, "_latest_tail_intraday_trade_date", lambda session, base_daily_date: today)
    monkeypatch.setattr(screening, "_tail_intraday_date_available", lambda session, trade_date: trade_date == today)
    monkeypatch.setattr(screening, "_daily_symbol_count", lambda session, trade_date: 265 if trade_date == today else 4064)
    monkeypatch.setattr(screening, "_latest_snapshot_updated_at", lambda session: datetime(2026, 6, 18, 14, 1))
    monkeypatch.setattr(screening, "_latest_snapshot_trade_time", lambda session: "14:01:00")
    monkeypatch.setattr(screening, "_load_stock_universe", lambda session, max_symbols, boards: [
        {"vt_symbol": "002384.SZSE", "exchange": "SZSE", "name": "东山精密", "last_price": 11.5, "turnover": 60_000_000, "change_pct": 4.5},
    ])
    monkeypatch.setattr(screening, "_load_bars", lambda session, symbols, as_of, lookback_days: {"002384.SZSE": base_bars})
    monkeypatch.setattr(screening, "_load_intraday_temp_bars", lambda session, symbols, as_of: {"002384.SZSE": intraday_bar})
    monkeypatch.setattr(screening, "_load_index_return_20d", lambda session, as_of: None)
    monkeypatch.setattr(screening, "_load_sector_scores", lambda session, symbols, as_of: {})
    monkeypatch.setattr(screening, "_load_financial_scores", lambda session, symbols, as_of: {})
    monkeypatch.setattr(screening, "_load_fund_flow_scores", lambda session, symbols, as_of: {})
    monkeypatch.setattr(screening, "_load_hot_rank_scores", lambda session, symbols, as_of: {})
    monkeypatch.setattr(screening, "_load_lhb_scores", lambda session, symbols, as_of: {})
    monkeypatch.setattr(screening, "score_strategy", fake_score_strategy)
    monkeypatch.setattr(screening, "_persist_screen_run", fail_persist)

    result = screening.screen_tail_preview(max_symbols=1, recommendation_limit=100, included_boards=["main"])

    assert result["status"] == "ready"
    assert result["trade_date"] == "2026-06-18"
    assert result["base_daily_date"] == "2026-06-17"
    assert result["latest_daily_date"] == "2026-06-18"
    assert result["trade_date_daily_symbol_count"] == 265
    assert result["run_id"] is None
    assert result["data_source"] == "intraday_snapshot_temp_bar"
    assert result["temporary_bar"] is True
    assert result["intraday_bar_count"] == 1
    assert result["recommendation_count"] == 1
    assert result["recommendations"][0]["reason"]["temporary_bar"] is True
    assert result["recommendations"][0]["reason"]["bar_mode"] == "minute_aggregate"
    assert scored_bars[-1].trade_date == today
    assert persisted["called"] is False


def test_screen_tail_preview_waits_when_only_snapshot_updated(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    base_date = date(2026, 6, 18)

    class FakeSession:
        pass

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    def fail_load_stock_universe(*args, **kwargs):
        del args, kwargs
        raise AssertionError("must not score without real intraday date")

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_trade_date", lambda session: base_date)
    monkeypatch.setattr(screening, "_latest_complete_trade_date", lambda session: base_date)
    monkeypatch.setattr(screening, "_latest_tail_intraday_trade_date", lambda session, base_daily_date: None)
    monkeypatch.setattr(screening, "_latest_snapshot_updated_at", lambda session: datetime(2026, 6, 19, 14, 1))
    monkeypatch.setattr(screening, "_latest_snapshot_trade_time", lambda session: "15:00:00")
    monkeypatch.setattr(screening, "_load_stock_universe", fail_load_stock_universe)

    result = screening.screen_tail_preview(max_symbols=1, recommendation_limit=100, included_boards=["main"])

    assert result["status"] == "waiting_for_intraday_data"
    assert result["trade_date"] is None
    assert result["base_daily_date"] == "2026-06-18"
    assert result["latest_daily_date"] == "2026-06-18"
    assert result["snapshot_updated_at"] == "2026-06-19T14:01:00"
    assert result["recommendations"] == []


def test_get_tail_preview_prefers_today_cache(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    cached_payload = {
        "status": "ready",
        "trade_date": "2026-06-18",
        "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
        "strategy_version": "0.1.23",
        "items": [{"vt_symbol": "A"}, {"vt_symbol": "B"}],
        "recommendations": [{"vt_symbol": "A"}, {"vt_symbol": "B"}],
        "latest_intraday_date": "2026-06-18",
        "intraday_bar_count": 1,
        "recommendation_count": 2,
        "total": 2,
    }
    calls = {"screen": 0}

    monkeypatch.setattr(screening, "_tail_preview_default_trade_date", lambda: date(2026, 6, 18))
    monkeypatch.setattr(screening, "latest_tail_preview_cache", lambda trade_date, strategy_id: cached_payload)

    def fail_screen(*args, **kwargs):
        calls["screen"] += 1
        raise AssertionError("cache hit should not recompute")

    monkeypatch.setattr(screening, "screen_tail_preview", fail_screen)

    result = screening.get_tail_preview(recommendation_limit=1)

    assert result["trade_date"] == "2026-06-18"
    assert len(result["recommendations"]) == 1
    assert calls["screen"] == 0


def test_get_tail_preview_refresh_recomputes(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    calls = {"screen": 0}
    monkeypatch.setattr(screening, "_tail_preview_default_trade_date", lambda: date(2026, 6, 18))
    monkeypatch.setattr(screening, "latest_tail_preview_cache", lambda trade_date, strategy_id: {"trade_date": "2026-06-18"})

    def fake_screen(trade_date, **kwargs):
        calls["screen"] += 1
        return {
            "status": "ready",
            "trade_date": trade_date.isoformat(),
            "recommendations": [],
            "items": [],
        }

    monkeypatch.setattr(screening, "screen_tail_preview", fake_screen)

    result = screening.get_tail_preview(refresh=True)

    assert result["trade_date"] == "2026-06-18"
    assert calls["screen"] == 1


def test_get_tail_preview_ignores_cache_without_intraday_evidence(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    calls = {"screen": 0}
    stale_cache = {
        "status": "ready",
        "trade_date": "2026-06-19",
        "base_daily_date": "2026-06-18",
        "items": [{"vt_symbol": "600000.SSE"}],
        "recommendations": [{"vt_symbol": "600000.SSE"}],
        "recommendation_count": 1,
        "total": 1,
    }

    monkeypatch.setattr(screening, "_tail_preview_default_trade_date", lambda: date(2026, 6, 19))
    monkeypatch.setattr(screening, "latest_tail_preview_cache", lambda trade_date, strategy_id: stale_cache)

    def fake_screen(trade_date, **kwargs):
        del kwargs
        calls["screen"] += 1
        return {
            "status": "waiting_for_intraday_data",
            "trade_date": trade_date.isoformat(),
            "items": [],
            "recommendations": [],
        }

    monkeypatch.setattr(screening, "screen_tail_preview", fake_screen)

    result = screening.get_tail_preview()

    assert result["status"] == "unavailable"
    assert result["recommendations"] == []
    assert calls["screen"] == 0


def test_generate_tail_preview_cache_persists_preview_payload(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    executed: list[object] = []

    class FakeSession:
        def execute(self, statement):
            executed.append(statement)

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        screening,
        "screen_tail_preview",
        lambda *args, **kwargs: {
            "status": "ready",
            "trade_date": "2026-06-18",
            "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
            "strategy_version": "0.1.23",
            "base_daily_date": "2026-06-17",
            "latest_daily_date": "2026-06-18",
            "latest_intraday_date": "2026-06-18",
            "intraday_bar_count": 1,
            "recommendation_count": 3,
            "total": 21,
            "items": [],
            "recommendations": [],
        },
    )

    result = screening.generate_tail_preview_cache(
        date(2026, 6, 18),
        strategy_id=DRAGON_PULLBACK_STRATEGY_ID,
        source_schedule_id="tail_quant_1430",
    )

    assert result["cache"]["status"] == "cached"
    assert result["cache"]["source_schedule_id"] == "tail_quant_1430"
    assert len(executed) == 1
    compiled = executed[0].compile()
    params = compiled.params
    assert params["trade_date"] == date(2026, 6, 18)
    assert params["recommendation_count"] == 3
    assert params["total"] == 21
    assert params["source_schedule_id"] == "tail_quant_1430"


def test_stock_fund_flow_upsert_skips_unknown_symbols(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    inserted: list[dict[str, object]] = []

    class FakeScalarResult:
        def scalars(self):
            return self

        def all(self):
            return ["600000.SSE"]

    class FakeSelectResult:
        def first(self):
            return None

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if text.startswith("SELECT stocks.vt_symbol"):
                return FakeScalarResult()
            if text.startswith("INSERT INTO stock_fund_flows"):
                inserted.append(dict(statement.compile().params))
                return None
            return FakeSelectResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(data_sync, "session_scope", fake_session_scope)

    written = data_sync._upsert_stock_fund_flow_items(
        [
            {"vt_symbol": "600000.SSE", "main_net_inflow": 100_000_000, "main_net_inflow_pct": 6.0},
            {"vt_symbol": "000032.SZSE", "main_net_inflow": 200_000_000, "main_net_inflow_pct": 8.0},
        ],
        "即时",
    )

    assert written == 1
    assert inserted[0]["vt_symbol"] == "600000.SSE"


def test_sector_fund_flow_upsert_creates_sector_metadata(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    inserted_sectors: list[dict[str, object]] = []
    inserted_flows: list[dict[str, object]] = []

    class FakeSelectResult:
        def first(self):
            return None

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            params = dict(statement.compile().params)
            if text.startswith("INSERT INTO sectors"):
                inserted_sectors.append(params)
            elif text.startswith("INSERT INTO sector_fund_flows"):
                inserted_flows.append(params)
            return FakeSelectResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(data_sync, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        data_sync.market_snapshot_repository,
        "save_sector_fund_flow_snapshots",
        lambda items, **kwargs: len(items),
    )

    written = data_sync._upsert_sector_fund_flows(
        [
            {
                "code": "BK1234",
                "name": "半导体",
                "trade_date": "2026-06-18",
                "change_pct": 2.4,
                "main_net_inflow": 2_000_000_000,
                "main_net_inflow_pct": 6.0,
                "rank": 1,
                "source": "eastmoney.sector_fund_flow_rank",
            }
        ],
        "即时",
        "concept",
    )

    assert written == 1
    assert inserted_sectors[0]["id"] == "BK1234"
    assert inserted_sectors[0]["name"] == "半导体"
    assert inserted_flows[0]["sector_id"] == "BK1234"
    assert inserted_flows[0]["trade_date"] == "2026-06-18"
    assert inserted_flows[0]["main_net_inflow"] == 2_000_000_000
    assert inserted_flows[0]["source"] == "eastmoney.sector_fund_flow_rank"


def test_stock_hot_rank_upsert_skips_unknown_symbols(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    inserted: list[dict[str, object]] = []

    class FakeScalarResult:
        def scalars(self):
            return self

        def all(self):
            return ["600000.SSE"]

    class FakeSelectResult:
        def first(self):
            return None

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if text.startswith("SELECT stocks.vt_symbol"):
                return FakeScalarResult()
            if text.startswith("INSERT INTO stock_hot_ranks"):
                inserted.append(dict(statement.compile().params))
                return None
            return FakeSelectResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(data_sync, "session_scope", fake_session_scope)

    written = data_sync._upsert_stock_hot_ranks(
        [
            {"vt_symbol": "600000.SSE", "rank": 1},
            {"vt_symbol": "300666.SZSE", "rank": 2},
        ]
    )

    assert written == 1
    assert inserted[0]["vt_symbol"] == "600000.SSE"


def test_stock_minute_bar_upsert_parses_intraday_time(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    inserted: list[dict[str, object]] = []

    class FakeScalarResult:
        def scalar(self):
            return "600000.SSE"

    class FakeSelectResult:
        def first(self):
            return None

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if text.startswith("SELECT stocks.vt_symbol"):
                return FakeScalarResult()
            if text.startswith("INSERT INTO stock_minute_bars"):
                inserted.append(dict(statement.compile().params))
                return None
            return FakeSelectResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(data_sync, "session_scope", fake_session_scope)

    written = data_sync._upsert_minute_bars(
        "600000",
        "SSE",
        [
            {
                "trade_date": "2026-06-11 14:30:00",
                "open": 10.0,
                "high": 10.2,
                "low": 9.99,
                "close": 10.05,
                "volume": 1200,
            }
        ],
        "1m",
        "test",
    )

    assert written == 1
    assert inserted[0]["vt_symbol"] == "600000.SSE"
    assert inserted[0]["trade_date"].isoformat() == "2026-06-11"
    assert inserted[0]["bar_time"].strftime("%H:%M:%S") == "14:30:00"


def test_stock_minute_sync_job_is_registered() -> None:
    from alphaagent.server.services import data_sync

    job_ids = {job.id for job in data_sync.DEFAULT_JOBS}

    assert "sync_stock_minute_bars" in job_ids
    assert data_sync.JOB_RUNNERS["sync_stock_minute_bars"] == "_run_sync_stock_minute_bars"


def test_seed_default_registry_updates_existing_minute_job(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    captured_updates: list[dict[str, object]] = []

    class FakeResult:
        inserted_primary_key = [1]

        def first(self):
            return object()

    class FakeSession:
        def execute(self, statement):
            statement_text = str(statement)
            if "UPDATE sync_job_definitions" in statement_text:
                params = statement.compile().params
                if params.get("id_1") == "sync_stock_minute_bars":
                    captured_updates.append(params)
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(data_sync, "session_scope", fake_session_scope)

    data_sync.seed_default_registry()

    minute_update = captured_updates[-1]
    assert minute_update["description"] == "同步最近分钟线，或按严格回测缺口补执行日 14:30 尾盘快照。"
    assert minute_update["default_params"]["mode"] == "recent"


def test_stock_minute_sync_accepts_symbols_and_date_range(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    seen_calls: list[dict[str, object]] = []
    written: list[tuple[str, str, str]] = []

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"symbol": "600000", "exchange": "SSE", "vt_symbol": "600000.SSE"}]

    class FakeSession:
        def execute(self, statement):
            assert "stocks.vt_symbol IN" in str(statement)
            return FakeResult()

    class FakeAdapter:
        def stock_bars(self, symbol, exchange, limit, interval, start_date=None, end_date=None):
            seen_calls.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "limit": limit,
                    "interval": interval,
                    "start_date": start_date,
                    "end_date": end_date,
                }
            )
            return {"source": "fake", "items": [{"trade_date": "2026-06-11 14:30:00", "open": 10, "high": 10.2, "low": 9.9, "close": 10.1}]}

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(data_sync, "session_scope", fake_session_scope)
    monkeypatch.setattr(data_sync, "_upsert_minute_bars", lambda symbol, exchange, items, interval, source: written.append((symbol, exchange, interval)) or len(items))

    runner = data_sync.DataSyncRunner()
    runner.adapter = FakeAdapter()
    result = runner._run_sync_stock_minute_bars(
        {
            "symbols": "600000.SSE",
            "start_date": "2026-06-01",
            "end_date": "2026-06-11",
            "stock_limit": 10,
            "limit": 1200,
            "interval": "1m",
            "only_missing": False,
            "incremental": False,
        }
    )

    assert result["mode"] == "recent"
    assert result["provider"] == "akshare"
    assert result["interval"] == "1m"
    assert result["rows_read"] == 1
    assert result["rows_written"] == 1
    assert seen_calls[0]["start_date"].isoformat() == "2026-06-01"
    assert seen_calls[0]["end_date"].isoformat() == "2026-06-11"
    assert seen_calls[0]["limit"] == 1200
    assert written == [("600000", "SSE", "1m")]


def test_stock_minute_sync_gap_mode_uses_backtest_gap_csv(monkeypatch) -> None:
    from alphaagent.server.services import data_sync
    from alphaagent.server.services.data_providers import tdx_minute_import
    from alphaagent.server.services.backtest import engine

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        engine,
        "backtest_minute_gap_csv",
        lambda backtest_id: {
            "status": "ready",
            "content": "trade_date,vt_symbol\n2026-06-11,600000.SSE\n",
            "gap_count": 1,
        },
    )

    def fake_import(**kwargs):
        captured.update(kwargs)
        return {
            "status": "ready",
            "rows_read": 2,
            "rows_written": 2,
            "audit_after": {"status": "ready", "covered_count": 1, "missing_count": 0},
        }

    monkeypatch.setattr(tdx_minute_import, "import_tdx_minute_bars_for_gaps", fake_import)

    result = data_sync.DataSyncRunner()._run_sync_stock_minute_bars(
        {
            "mode": "backtest_gaps",
            "provider": "tdx",
            "backtest_id": 42,
            "interval": "1m",
            "dry_run": True,
            "max_gaps": 20,
            "tail_entry_start": "14:30",
        }
    )

    assert captured["gap_csv_text"].startswith("trade_date,vt_symbol")
    assert captured["gap_file_path"] == ""
    assert captured["interval"] == "1m"
    assert captured["tail_entry_start"] == "14:30"
    assert captured["tail_entry_end"] == "14:30"
    assert captured["dry_run"] is True
    assert captured["max_gaps"] == 20
    assert result["mode"] == "backtest_gaps"
    assert result["provider"] == "tdx"
    assert result["gap_source"] == "backtest_id=42"
    assert result["rows_read"] == 2
    assert result["rows_written"] == 2


def test_stock_minute_sync_gap_mode_forces_1m_tail_snapshot(monkeypatch) -> None:
    from alphaagent.server.services import data_sync
    from alphaagent.server.services.data_providers import tdx_minute_import

    captured: dict[str, object] = {}

    def fake_import(**kwargs):
        captured.update(kwargs)
        return {"status": "ready", "rows_read": 10, "rows_written": 10}

    monkeypatch.setattr(tdx_minute_import, "import_tdx_minute_bars_for_gaps", fake_import)

    result = data_sync.DataSyncRunner()._run_sync_stock_minute_bars(
        {
            "mode": "backtest_gaps",
            "provider": "tdx",
            "gap_csv_text": "trade_date,vt_symbol\n2026-06-11,600000.SSE\n",
            "interval": "1m",
            "dry_run": False,
        }
    )

    assert captured["interval"] == "1m"
    assert result["interval"] == "1m"
    assert result["fetch_interval"] == "1m"
    assert result["base_rows_written"] == 10
    assert result["aggregate_rows_written"] == 0
    assert result["rows_written"] == 10


def test_stock_minute_sync_gap_mode_uses_akshare_provider(monkeypatch) -> None:
    from alphaagent.server.services import data_sync
    from alphaagent.server.services.data_providers import akshare_minute_import

    captured: dict[str, object] = {}

    def fake_import(**kwargs):
        captured.update(kwargs)
        return {"status": "ready", "rows_read": 1, "rows_written": 0, "audit_after": {"status": "ready"}}

    monkeypatch.setattr(akshare_minute_import, "import_akshare_minute_bars_for_gaps", fake_import)

    result = data_sync.DataSyncRunner()._run_sync_stock_minute_bars(
        {
            "mode": "backtest_gaps",
            "provider": "akshare",
            "gap_csv_text": "trade_date,vt_symbol\n2026-06-12,600000.SSE\n",
            "interval": "1m",
            "dry_run": True,
            "tail_entry_start": "14:30",
            "tail_entry_end": "14:30",
        }
    )

    assert captured["interval"] == "1m"
    assert captured["tail_entry_start"] == "14:30"
    assert captured["tail_entry_end"] == "14:30"
    assert result["provider"] == "akshare"
    assert result["interval"] == "1m"
    assert result["rows_read"] == 1


def test_import_stock_minute_bars_csv_groups_and_upserts(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    calls: list[tuple[str, str, list[dict[str, object]], str, str]] = []

    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)
    monkeypatch.setattr(data_sync, "ensure_sync_schema", lambda: None)

    def fake_upsert(symbol, exchange, items, interval, source):
        calls.append((symbol, exchange, items, interval, source))
        return len(items)

    monkeypatch.setattr(data_sync, "_upsert_minute_bars", fake_upsert)

    result = data_sync.import_stock_minute_bars_csv(
        "\ufeffvt_symbol,bar_time,open,high,low,close,volume,turnover\n"
        "600000.SSE,2026-01-08 14:30:00,10,10.2,9.9,10.1,1200,12120\n"
        "000001.SZSE,2026-01-08 14:30:00,20,20.2,19.9,20.1,2200,44220\n",
        interval="1m",
        source="unit_test",
    )

    assert result["status"] == "ready"
    assert result["rows_read"] == 2
    assert result["rows_written"] == 2
    assert result["symbol_count"] == 2
    assert calls[0][0:2] == ("600000", "SSE")
    assert calls[0][2][0]["close"] == 10.1
    assert calls[0][3:] == ("1m", "unit_test")


def test_import_stock_minute_bars_rejects_obsolete_10m_interval(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)

    try:
        data_sync.import_stock_minute_bars_csv(
            "vt_symbol,bar_time,open,high,low,close\n"
            "600000.SSE,2026-01-08 14:30:00,10,10.2,9.9,10.1\n",
            interval="10m",
        )
    except data_sync.DataSyncError as exc:
        assert "Unsupported minute interval: 10m" in str(exc)
    else:
        raise AssertionError("expected DataSyncError")


def test_backtest_params_rejects_non_1m_minute_interval() -> None:
    from alphaagent.server.services.backtest import engine

    try:
        engine.BacktestParams(minute_interval="5m")
    except ValueError as exc:
        assert "Unsupported backtest minute interval: 5m" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_backtest_execution_model_empty_default_is_daily_next_open() -> None:
    from alphaagent.server.services.backtest import engine, execution_models

    assert execution_models.normalize_execution_model(None) == "legacy_next_open"
    assert engine._normalize_execution_model(None) == "legacy_next_open"
    assert engine.BacktestParams().execution_model == "legacy_next_open"
    assert engine.BacktestParams().intraday_entry is False


def test_backtest_ledger_calculates_buy_execution_with_slippage_commission_and_lot() -> None:
    from alphaagent.server.services.backtest import ledger

    result = ledger.calculate_buy_execution(
        raw_price=10.0,
        cash=100_000,
        target_cash=50_000,
        commission_rate=0.0003,
        slippage_bps=10,
    )

    assert round(result.price, 4) == 10.01
    assert result.volume == 4_900
    assert round(result.amount, 4) == 49_049.0
    assert round(result.fee, 4) == 14.7147
    assert round(result.cash_delta, 4) == -49_063.7147
    assert round(result.cash_after, 4) == 50_936.2853


def test_backtest_ledger_reduces_buy_volume_when_fee_exceeds_cash() -> None:
    from alphaagent.server.services.backtest import ledger

    result = ledger.calculate_buy_execution(
        raw_price=10.0,
        cash=10_000,
        target_cash=10_000,
        commission_rate=0.0003,
        slippage_bps=0,
    )

    assert result.price == 10.0
    assert result.volume == 900
    assert result.amount == 9_000.0
    assert result.fee == 2.6999999999999997
    assert round(result.cash_after, 4) == 997.3


def test_backtest_ledger_rejects_buy_below_one_lot() -> None:
    from alphaagent.server.services.backtest import ledger

    result = ledger.calculate_buy_execution(
        raw_price=10.0,
        cash=999,
        target_cash=999,
        commission_rate=0.0003,
        slippage_bps=0,
    )

    assert result.price == 10.0
    assert result.volume == 0
    assert result.amount == 0.0
    assert result.fee == 0.0
    assert result.cash_delta == 0.0
    assert result.cash_after == 999


def test_backtest_ledger_calculates_sell_execution_with_slippage_stamp_tax_and_pnl() -> None:
    from alphaagent.server.services.backtest import ledger

    result = ledger.calculate_sell_execution(
        raw_price=12.0,
        volume=1_000,
        cost_price=10.01,
        commission_rate=0.0003,
        stamp_tax_rate=0.0005,
        slippage_bps=10,
    )

    assert result.price == 11.988
    assert result.volume == 1_000
    assert result.amount == 11_988.0
    assert round(result.fee, 4) == 9.5904
    assert round(result.pnl, 4) == 1_968.4096
    assert result.cash_delta == 11_978.4096


def test_import_stock_minute_bars_file_uses_allowed_path(monkeypatch, tmp_path) -> None:
    from alphaagent.server.services import data_sync

    import_dir = tmp_path / "data" / "imports"
    import_dir.mkdir(parents=True)
    csv_path = import_dir / "minute.csv"
    csv_path.write_text(
        "vt_symbol,bar_time,open,high,low,close,volume,turnover\n"
        "600000.SSE,2026-01-08 14:30:00,10,10.2,9.9,10.1,1200,12120\n",
        encoding="utf-8",
    )

    calls = []
    monkeypatch.setattr(data_sync, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_sync, "ALLOWED_IMPORT_DIRS", (import_dir,))
    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)
    monkeypatch.setattr(data_sync, "ensure_sync_schema", lambda: None)
    monkeypatch.setattr(data_sync, "_upsert_minute_bars", lambda symbol, exchange, items, interval, source: calls.append((symbol, exchange, source)) or len(items))

    result = data_sync.import_stock_minute_bars_file("data/imports/minute.csv", interval="1m", source="file_test")

    assert result["status"] == "ready"
    assert result["rows_written"] == 1
    assert result["file_path"] == "data/imports/minute.csv"
    assert calls == [("600000", "SSE", "file_test")]


def test_import_stock_minute_bars_file_flushes_large_csv(monkeypatch, tmp_path) -> None:
    from alphaagent.server.services import data_sync

    import_dir = tmp_path / "data" / "imports"
    import_dir.mkdir(parents=True)
    csv_path = import_dir / "minute_large.csv"
    rows = ["vt_symbol,bar_time,open,high,low,close,volume,turnover"]
    for index in range(2001):
        rows.append(f"600000.SSE,2026-01-08 14:{index % 60:02d}:00,10,10.2,9.9,10.1,1200,12120")
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    batch_sizes = []
    monkeypatch.setattr(data_sync, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_sync, "ALLOWED_IMPORT_DIRS", (import_dir,))
    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)
    monkeypatch.setattr(data_sync, "ensure_sync_schema", lambda: None)

    def fake_upsert(symbol, exchange, items, interval, source):
        del symbol, exchange, interval, source
        batch_sizes.append(len(items))
        return len(items)

    monkeypatch.setattr(data_sync, "_upsert_minute_bars", fake_upsert)

    result = data_sync.import_stock_minute_bars_file("data/imports/minute_large.csv", interval="1m")

    assert result["rows_read"] == 2001
    assert result["rows_written"] == 2001
    assert batch_sizes == [2000, 1]


def test_import_file_rejects_paths_outside_allowed_dirs(monkeypatch, tmp_path) -> None:
    from alphaagent.server.services import data_sync

    outside = tmp_path / "outside.csv"
    outside.write_text("vt_symbol,bar_time,open,high,low,close\n", encoding="utf-8")
    import_dir = tmp_path / "data" / "imports"

    monkeypatch.setattr(data_sync, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_sync, "ALLOWED_IMPORT_DIRS", (import_dir,))
    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)

    try:
        data_sync.import_stock_minute_bars_file(str(outside))
    except data_sync.DataSyncError as exc:
        assert "must be under" in str(exc)
    else:
        raise AssertionError("expected DataSyncError")


def test_import_file_rejects_empty_path(monkeypatch, tmp_path) -> None:
    from alphaagent.server.services import data_sync

    monkeypatch.setattr(data_sync, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_sync, "ALLOWED_IMPORT_DIRS", (tmp_path / "data" / "imports",))
    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)

    try:
        data_sync.import_stock_minute_bars_file(" ")
    except data_sync.DataSyncError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("expected DataSyncError")


def test_import_minute_bars_api_template_and_dry_run(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)

    client = TestClient(create_app())
    template = client.get("/api/data-sync/imports/minute-bars/template.csv")
    assert template.status_code == 200
    assert template.headers["content-type"].startswith("text/csv")
    assert "vt_symbol,bar_time" in template.text

    response = client.post(
        "/api/data-sync/imports/minute-bars",
        json={
            "dry_run": True,
            "csv_text": "vt_symbol,bar_time,open,high,low,close\n600000.SSE,2026-01-08 14:30:00,10,10.2,9.9,10.1\n",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["rows_read"] == 1
    assert response.json()["data"]["dry_run"] is True


def test_import_minute_bars_api_accepts_file_path(monkeypatch) -> None:
    from alphaagent.server.api import data_sync as api

    captured = {}

    def fake_import_file(file_path, interval, source, dry_run):
        captured.update({"file_path": file_path, "interval": interval, "source": source, "dry_run": dry_run})
        return {"status": "ready", "rows_read": 1, "rows_written": 0, "rows_skipped": 0, "file_path": file_path}

    monkeypatch.setattr(api.service, "import_stock_minute_bars_file", fake_import_file)

    client = TestClient(create_app())
    response = client.post(
        "/api/data-sync/imports/minute-bars",
        json={"file_path": "data/imports/minute.csv", "interval": "1m", "source": "file_test", "dry_run": True},
    )

    assert response.status_code == 200
    assert captured == {"file_path": "data/imports/minute.csv", "interval": "1m", "source": "file_test", "dry_run": True}
    assert response.json()["data"]["file_path"] == "data/imports/minute.csv"


def test_audit_minute_gap_csv_reports_missing_and_covered(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        data_sync,
        "_minute_gap_coverage_counts",
        lambda items, interval, start, end: {("600000.SSE", date(2026, 1, 8)): 2},
    )

    result = data_sync.audit_minute_gap_csv(
        "\ufefftrade_date,vt_symbol,reference_date,window,ma5,minute_bar_count,missing_reason\n"
        "2026-01-08,600000.SSE,2026-01-07,14:30-14:30,10.1,0,no_tail_window_minute_bars\n"
        "2026-01-08,000001.SZSE,2026-01-07,14:30-14:30,20.1,0,no_tail_window_minute_bars\n",
        interval="1m",
        tail_entry_start="14:30",
        tail_entry_end="14:30",
    )

    assert result["status"] == "incomplete"
    assert result["gap_count"] == 2
    assert result["covered_count"] == 1
    assert result["missing_count"] == 1
    assert result["coverage_pct"] == 50.0
    assert result["missing_examples"][0]["vt_symbol"] == "000001.SZSE"
    assert result["next_action"].startswith("import historical 1m bars")


def test_audit_minute_gap_file_uses_allowed_path(monkeypatch, tmp_path) -> None:
    from alphaagent.server.services import data_sync

    import_dir = tmp_path / "memory" / "06_backtests"
    import_dir.mkdir(parents=True)
    csv_path = import_dir / "gap.csv"
    csv_path.write_text("trade_date,vt_symbol\n2026-01-08,600000.SSE\n", encoding="utf-8")

    monkeypatch.setattr(data_sync, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_sync, "ALLOWED_IMPORT_DIRS", (import_dir,))
    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)
    monkeypatch.setattr(data_sync, "_minute_gap_coverage_counts", lambda items, interval, start, end: {})

    result = data_sync.audit_minute_gap_file("memory/06_backtests/gap.csv")

    assert result["status"] == "incomplete"
    assert result["gap_count"] == 1
    assert result["file_path"] == "memory/06_backtests/gap.csv"


def test_minute_gap_import_template_uses_gap_rows() -> None:
    from alphaagent.server.services import data_sync

    content = data_sync.minute_gap_import_template(
        "trade_date,vt_symbol,reference_date,window,ma5\n"
        "2026-01-08,600000.SSE,2026-01-07,14:30-14:30,10.1\n",
    )

    assert "vt_symbol,bar_time,open,high,low,close,volume,turnover" in content
    assert "600000.SSE,2026-01-08 14:30:00" in content


def test_minute_gap_audit_api(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)
    monkeypatch.setattr(data_sync, "_minute_gap_coverage_counts", lambda items, interval, start, end: {})

    client = TestClient(create_app())
    response = client.post(
        "/api/data-sync/imports/minute-bars/audit-gaps",
        json={
            "gap_csv_text": "trade_date,vt_symbol\n2026-01-08,600000.SSE\n",
            "interval": "1m",
            "tail_entry_start": "14:30",
            "tail_entry_end": "14:30",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "incomplete"
    assert response.json()["data"]["missing_count"] == 1


def test_minute_gap_audit_api_accepts_file_path(monkeypatch) -> None:
    from alphaagent.server.api import data_sync as api

    captured = {}

    def fake_audit_file(file_path, interval, tail_entry_start, tail_entry_end, min_tail_bars):
        captured.update(
            {
                "file_path": file_path,
                "interval": interval,
                "tail_entry_start": tail_entry_start,
                "tail_entry_end": tail_entry_end,
                "min_tail_bars": min_tail_bars,
            }
        )
        return {"status": "ready", "gap_count": 1, "covered_count": 1, "missing_count": 0, "file_path": file_path}

    monkeypatch.setattr(api.service, "audit_minute_gap_file", fake_audit_file)

    client = TestClient(create_app())
    response = client.post(
        "/api/data-sync/imports/minute-bars/audit-gaps",
        json={"file_path": "memory/06_backtests/gap.csv", "tail_entry_start": "14:30", "tail_entry_end": "14:30"},
    )

    assert response.status_code == 200
    assert captured["file_path"] == "memory/06_backtests/gap.csv"
    assert response.json()["data"]["status"] == "ready"


def test_minute_gap_audit_api_accepts_backtest_id(monkeypatch) -> None:
    from alphaagent.server.api import data_sync as api

    def fake_requirements(params):
        assert params["backtest_id"] == 42
        return {
            "items": [{"vt_symbol": "600000.SSE", "trade_date": date(2026, 1, 8), "reference_date": None, "ma5": None, "window": "14:30-14:30"}],
            "rows_read": 1,
            "rows_skipped": 0,
            "errors": [],
            "gap_source": "backtest_id=42",
        }

    monkeypatch.setattr(api.service, "minute_gap_requirements_from_params", fake_requirements)
    monkeypatch.setattr(api.service, "_minute_gap_coverage_counts", lambda items, interval, start, end: {})

    client = TestClient(create_app())
    response = client.post(
        "/api/data-sync/imports/minute-bars/audit-gaps",
        json={"backtest_id": 42, "tail_entry_start": "14:30", "tail_entry_end": "14:30"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "incomplete"
    assert response.json()["data"]["missing_count"] == 1


def test_quant_schema_tables_are_registered() -> None:
    table_names = set(schema.metadata.tables)

    assert "quant_stock_signals" in table_names
    assert "backtest_signal_events" in table_names
    assert "backtest_runs" in table_names
    assert "strategy_replay_runs" in table_names
    assert "strategy_replay_attempts" in table_names
    assert "stock_minute_bars" in table_names
    assert "portfolio_groups" in table_names
    assert "simulation_positions" in table_names


def test_new_api_returns_unavailable_when_database_off(monkeypatch) -> None:
    from alphaagent.server.db import session as db_session
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.portfolio import groups
    from alphaagent.server.services.quant import screening
    from alphaagent.server.services.simulation import account

    monkeypatch.setattr(db_session, "is_database_configured", lambda: False)
    monkeypatch.setattr(screening, "is_database_configured", lambda: False)
    monkeypatch.setattr(engine, "is_database_configured", lambda: False)
    monkeypatch.setattr(groups, "is_database_configured", lambda: False)
    monkeypatch.setattr(account, "is_database_configured", lambda: False)
    from alphaagent.server.services.quant import strategy_replay

    monkeypatch.setattr(strategy_replay, "is_database_configured", lambda: False)

    client = TestClient(create_app())

    assert client.get("/api/quant/trading-dates").json()["data"]["status"] == "unavailable"
    assert client.get("/api/quant/recommendations").json()["data"]["status"] == "unavailable"
    assert client.get("/api/quant/symbols/600000.SSE/replay/latest").json()["data"]["status"] == "unavailable"
    assert client.get("/api/backtests").json()["data"]["status"] == "unavailable"
    assert client.get("/api/portfolio/groups").json()["data"]["status"] == "unavailable"
    assert client.get("/api/simulation/accounts").json()["data"]["status"] == "unavailable"


def test_quant_recommendations_api_defaults_to_top_20(monkeypatch) -> None:
    from alphaagent.server.api import quant

    captured: dict[str, object] = {}

    def fake_list_recommendations(trade_date=None, strategy_id="", limit=0):
        captured.update({"trade_date": trade_date, "strategy_id": strategy_id, "limit": limit})
        return {"status": "ready", "items": []}

    monkeypatch.setattr(quant.screening, "list_recommendations", fake_list_recommendations)

    client = TestClient(create_app())
    response = client.get("/api/quant/recommendations?strategy=mainline_dragon_pullback")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ready"
    assert captured["strategy_id"] == "mainline_dragon_pullback"
    assert captured["limit"] == 20


def test_quant_tail_preview_api_passes_preview_payload(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    captured: dict[str, object] = {}

    def fake_get_tail_preview(trade_date=None, **kwargs):
        captured.update({"trade_date": trade_date, **kwargs})
        return {
            "status": "ready",
            "trade_date": trade_date.isoformat(),
            "run_id": None,
            "preview_mode": "tail_intraday",
            "data_source": "intraday_snapshot_temp_bar",
            "temporary_bar": True,
            "recommendations": [],
            "items": [],
            "total": 0,
            "recommendation_count": 0,
        }

    monkeypatch.setattr(screening, "get_tail_preview", fake_get_tail_preview)

    client = TestClient(create_app())
    response = client.get(
        "/api/quant/tail-preview?trade_date=2026-06-18&strategy=mainline_dragon_pullback&limit=100&max_symbols=3000"
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert data["status"] == "ready"
    assert data["trade_date"] == "2026-06-18"
    assert data["run_id"] is None
    assert captured["trade_date"] == date(2026, 6, 18)
    assert captured["strategy_id"] == "mainline_dragon_pullback"
    assert captured["recommendation_limit"] == 100
    assert captured["max_symbols"] == 3000


def test_quant_screen_range_api_passes_range_payload(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    captured: dict[str, object] = {}

    def fake_screen_stocks_range(start=None, end=None, **kwargs):
        captured.update({"start": start, "end": end, **kwargs})
        return {
            "status": "ready",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "trade_date": end.isoformat(),
            "total_dates": 2,
            "succeeded_count": 2,
            "recommendation_count": 3,
            "range_recommendation_count": 7,
            "runs": [],
            "items": [],
            "recommendations": [],
        }

    monkeypatch.setattr(screening, "screen_stocks_range", fake_screen_stocks_range)

    client = TestClient(create_app())
    response = client.post(
        "/api/quant/screen-runs/range",
        json={
            "start": "2026-06-10",
            "end": "2026-06-12",
            "max_symbols": 120,
            "recommendation_limit": 20,
            "min_recommendation_score": 60,
            "persist": True,
            "auto_portfolio": True,
            "included_boards": ["main", "chinext"],
        },
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert data["status"] == "ready"
    assert data["total_dates"] == 2
    assert captured["start"] == date(2026, 6, 10)
    assert captured["end"] == date(2026, 6, 12)
    assert captured["max_symbols"] == 120
    assert captured["included_boards"] == ["main", "chinext"]


def test_quant_research_run_api_starts_background_workflow(monkeypatch) -> None:
    from alphaagent.server.api import quant

    captured: dict[str, object] = {}

    def fake_start_research_run(**kwargs):
        captured.update(kwargs)
        return {
            "id": "job-1",
            "status": "running",
            "strategy_id": kwargs["strategy_id"],
            "stage": "screening",
            "message": "正在补齐候选交易日",
            "progress_current": 1,
            "progress_total": 3,
            "progress_pct": 28,
            "screen_run": None,
            "backtest_id": None,
        }

    monkeypatch.setattr(quant.research_jobs, "start_research_run", fake_start_research_run)

    client = TestClient(create_app())
    response = client.post(
        "/api/quant/research-runs",
        json={
            "start": "2025-03-26",
            "end": "2026-06-15",
            "strategy": "mainline_dragon_pullback",
            "max_symbols": 5000,
            "recommendation_limit": 20,
            "min_recommendation_score": 60,
            "min_entry_score": 76,
            "persist": True,
            "auto_portfolio": True,
            "included_boards": ["main"],
            "initial_cash": 1_000_000,
            "max_positions": 10,
            "candidate_limit": 10,
            "max_position_pct": 0.1,
            "strict_entry": True,
            "execution_model": "legacy_next_open",
        },
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert data["id"] == "job-1"
    assert data["status"] == "running"
    assert captured["start"] == date(2025, 3, 26)
    assert captured["end"] == date(2026, 6, 15)
    assert captured["strategy_id"] == "mainline_dragon_pullback"
    assert "initial_cash" not in captured
    assert "max_positions" not in captured
    assert "max_position_pct" not in captured
    assert captured["recommendation_limit"] == 20
    assert captured["candidate_limit"] == 10
    assert captured["execution_model"] == "legacy_next_open"
    assert captured["included_boards"] == ["main"]
    assert captured["force_refresh"] is False


def test_quant_research_run_api_reads_latest_and_detail(monkeypatch) -> None:
    from alphaagent.server.api import quant

    latest = {"id": "job-2", "status": "succeeded", "backtest_id": 116}
    captured: dict[str, object] = {}

    def fake_get_latest_research_run():
        return latest

    def fake_get_research_run(run_id):
        captured["run_id"] = run_id
        return {"id": run_id, "status": "failed", "message": "boom"}

    monkeypatch.setattr(quant.research_jobs, "get_latest_research_run", fake_get_latest_research_run)
    monkeypatch.setattr(quant.research_jobs, "get_research_run", fake_get_research_run)

    client = TestClient(create_app())
    latest_response = client.get("/api/quant/research-runs/latest")
    detail_response = client.get("/api/quant/research-runs/job-3")

    assert latest_response.status_code == 200
    assert latest_response.json()["data"] == latest
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["id"] == "job-3"
    assert detail_response.json()["data"]["status"] == "failed"
    assert captured["run_id"] == "job-3"


def test_quant_research_job_uses_candidate_quality_as_primary_result(monkeypatch) -> None:
    from alphaagent.server.services.quant import research_jobs

    captured: dict[str, object] = {}
    run_id = "job-candidate-quality"
    params = {
        "strategy": DRAGON_PULLBACK_STRATEGY_ID,
        "max_symbols": 5000,
        "recommendation_limit": 100,
        "min_recommendation_score": 60.0,
        "min_entry_score": 76.0,
        "persist": True,
        "auto_portfolio": True,
        "included_boards": ["main"],
        "candidate_limit": 20,
        "strict_entry": True,
        "execution_model": "legacy_next_open",
        "force_refresh": False,
    }

    def fake_screen_range(**kwargs):
        captured["screen_kwargs"] = kwargs
        return {
            "status": "ready",
            "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
            "strategy_version": "0.test",
            "start_date": "2026-01-02",
            "end_date": "2026-01-31",
            "replay_run": {"status": "ready"},
            "replay_run_id": 7,
        }

    def fake_candidate_quality(**kwargs):
        captured["candidate_quality_kwargs"] = kwargs
        return {
            "status": "ready",
            "start_date": "2026-01-02",
            "end_date": "2026-01-31",
            "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
            "strategy_version": "0.test",
            "rank_limit": 20,
            "sample_limit": 500,
            "entry_selection": "daily_candidate",
            "summary": {"evaluated_count": 3, "win_rate": 66.6667, "average_return_pct": 4.2},
            "coverage": {"candidate_source": "quant_recommendations"},
            "by_rank_limit": [{"rank_limit": 5, "win_rate": 80.0}],
            "by_setup_family_rank_limit": [{"setup_family": "bottom_reclaim", "rank_limit": 20, "win_rate": 70.0}],
            "by_timing_window_rank_limit": [{"timing_window": "silver_pressure_zone", "rank_limit": 20, "win_rate": 60.0}],
            "by_month_rank_limit": [{"month": "2026-01", "rank_limit": 20, "win_rate": 55.0}],
            "yearly": [{"year": 2026, "win_rate": 66.6667}],
            "daily_summaries": [{"trade_date": "2026-01-02", "win_rate": 66.6667}],
            "worst_samples": [{"vt_symbol": "000001.SZSE", "return_pct": -3.0}],
            "best_samples": [{"vt_symbol": "000002.SZSE", "return_pct": 5.0}],
        }

    def fail_run_backtest(*args, **kwargs):
        del args, kwargs
        raise AssertionError("quant research must finish on candidate quality; portfolio diagnostics is not the primary result")

    monkeypatch.setattr(research_jobs.screening, "screen_stocks_range", fake_screen_range)
    monkeypatch.setattr(research_jobs, "candidate_trade_quality_report_from_quant_recommendations", fake_candidate_quality)
    monkeypatch.setattr(research_jobs, "run_backtest", fail_run_backtest, raising=False)
    with research_jobs._JOB_LOCK:
        research_jobs._JOBS[run_id] = {
            "id": run_id,
            "status": "running",
            "params": dict(params),
            "backtest": None,
            "backtest_id": None,
        }

    research_jobs._run_research_job(run_id, date(2026, 1, 2), date(2026, 1, 31), params)
    result = research_jobs.get_research_run(run_id)

    assert result["status"] == "succeeded"
    assert result["candidate_trade_quality"]["summary"]["average_return_pct"] == 4.2
    assert result["candidate_trade_quality"]["by_rank_limit"][0]["rank_limit"] == 5
    assert result["candidate_trade_quality"]["by_setup_family_rank_limit"][0]["setup_family"] == "bottom_reclaim"
    assert result["candidate_trade_quality"]["by_timing_window_rank_limit"][0]["timing_window"] == "silver_pressure_zone"
    assert result["candidate_trade_quality"]["by_month_rank_limit"][0]["month"] == "2026-01"
    assert result["candidate_trade_quality"]["yearly"][0]["year"] == 2026
    assert result["candidate_trade_quality"]["daily_summaries"][0]["trade_date"] == "2026-01-02"
    assert result["candidate_trade_quality"]["worst_samples"][0]["vt_symbol"] == "000001.SZSE"
    assert result["candidate_trade_quality"]["best_samples"][0]["vt_symbol"] == "000002.SZSE"
    assert captured["candidate_quality_kwargs"]["rank_limit"] == 20
    assert captured["candidate_quality_kwargs"]["strategy_version"] == "0.test"
    assert result["backtest"] is None
    assert result["backtest_id"] is None


def test_backtest_service_bootstraps_schema_without_api_startup(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    calls: list[object] = []

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return []

    class FakeSession:
        def execute(self, statement):
            calls.append(statement)
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(engine, "is_database_configured", lambda: True)
    monkeypatch.setattr(engine, "get_engine", lambda: "fake-engine")
    monkeypatch.setattr(engine.schema, "create_schema", lambda db_engine: calls.append(("create_schema", db_engine)))
    monkeypatch.setattr(engine.schema, "_SCHEMA_READY", False)
    monkeypatch.setattr(engine, "session_scope", fake_session_scope)

    result = engine.list_backtests()

    assert result == {"status": "ready", "items": []}
    assert calls[0] == ("create_schema", "fake-engine")


def test_backtest_list_filters_portfolio_and_symbol_runs(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    class FakeRunRows:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "id": 2,
                    "strategy_id": "mainline_leader_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2026, 1, 1),
                    "end_date": date(2026, 6, 12),
                    "status": "succeeded",
                    "initial_cash": 100_000,
                    "final_equity": 101_000,
                    "params": {"symbols": ["600000.SSE"]},
                    "metrics": {},
                },
                {
                    "id": 1,
                    "strategy_id": "mainline_leader_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2026, 1, 1),
                    "end_date": date(2026, 6, 12),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 990_000,
                    "params": {"symbols": []},
                    "metrics": {},
                },
            ]

    class FakeSession:
        def execute(self, statement):
            del statement
            return FakeRunRows()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(engine, "is_database_configured", lambda: True)
    monkeypatch.setattr(engine, "_ensure_backtest_schema", lambda: None)
    monkeypatch.setattr(engine, "session_scope", fake_session_scope)

    portfolio = engine.list_backtests(run_type="portfolio")
    symbol = engine.list_backtests(run_type="symbol")

    assert [item["id"] for item in portfolio["items"]] == [1]
    assert portfolio["items"][0]["run_type"] == "portfolio"
    assert [item["id"] for item in symbol["items"]] == [2]
    assert symbol["items"][0]["run_type"] == "symbol"


def test_backtest_list_fetches_extra_rows_before_run_type_filter(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    captured_limits: list[int] = []

    class FakeRunRows:
        def mappings(self):
            return self

        def all(self):
            rows = []
            for index in range(220, 20, -1):
                rows.append(
                    {
                        "id": index,
                        "strategy_id": "mainline_leader_pullback",
                        "strategy_version": "0.1.1",
                        "start_date": date(2026, 1, 1),
                        "end_date": date(2026, 6, 12),
                        "status": "succeeded",
                        "initial_cash": 100_000,
                        "final_equity": 101_000,
                        "params": {"symbols": [f"{index:06d}.SSE"]},
                        "metrics": {},
                    }
                )
            rows.append(
                {
                    "id": 20,
                    "strategy_id": "mainline_leader_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2026, 1, 1),
                    "end_date": date(2026, 6, 12),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 990_000,
                    "params": {"symbols": []},
                    "metrics": {},
                }
            )
            return rows

    class FakeSession:
        def execute(self, statement):
            captured_limits.append(statement._limit_clause.value)
            return FakeRunRows()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(engine, "is_database_configured", lambda: True)
    monkeypatch.setattr(engine, "_ensure_backtest_schema", lambda: None)
    monkeypatch.setattr(engine, "session_scope", fake_session_scope)

    result = engine.list_backtests(limit=20, run_type="portfolio")

    assert captured_limits == [200]
    assert [item["id"] for item in result["items"]] == [20]


def test_backtest_list_filters_by_strategy_id(monkeypatch) -> None:
    from sqlalchemy.sql import visitors

    from alphaagent.server.services.backtest import engine

    captured_statements = []

    class FakeRunRows:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "id": 112,
                    "strategy_id": "mainline_dragon_pullback",
                    "strategy_version": "0.1.0",
                    "start_date": date(2025, 10, 14),
                    "end_date": date(2026, 2, 4),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 1_116_204,
                    "params": {"symbols": []},
                    "metrics": {},
                }
            ]

    class FakeSession:
        def execute(self, statement):
            captured_statements.append(statement)
            return FakeRunRows()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(engine, "is_database_configured", lambda: True)
    monkeypatch.setattr(engine, "_ensure_backtest_schema", lambda: None)
    monkeypatch.setattr(engine, "session_scope", fake_session_scope)

    result = engine.list_backtests(limit=50, run_type="portfolio", strategy_id="mainline_dragon_pullback")

    bind_values = [
        element.value
        for element in visitors.iterate(captured_statements[0])
        if hasattr(element, "value")
    ]
    assert "mainline_dragon_pullback" in bind_values
    assert [item["strategy_id"] for item in result["items"]] == ["mainline_dragon_pullback"]


def test_backtest_list_filters_current_strategy_version_when_strategy_requested(monkeypatch) -> None:
    from sqlalchemy.sql import visitors

    from alphaagent.server.services.backtest import engine

    captured_statements = []

    class FakeRunRows:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "id": 119,
                    "strategy_id": "mainline_dragon_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2025, 3, 26),
                    "end_date": date(2026, 6, 16),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 1_116_204,
                    "params": {"symbols": []},
                    "metrics": {},
                }
            ]

    class FakeSession:
        def execute(self, statement):
            captured_statements.append(statement)
            return FakeRunRows()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(engine, "is_database_configured", lambda: True)
    monkeypatch.setattr(engine, "_ensure_backtest_schema", lambda: None)
    monkeypatch.setattr(engine, "session_scope", fake_session_scope)

    result = engine.list_backtests(limit=50, run_type="portfolio", strategy_id="mainline_dragon_pullback")

    bind_values = [
        element.value
        for element in visitors.iterate(captured_statements[0])
        if hasattr(element, "value")
    ]
    strategy = engine.get_strategy("mainline_dragon_pullback")
    assert strategy is not None
    assert "mainline_dragon_pullback" in bind_values
    assert strategy.version in bind_values
    assert [item["strategy_version"] for item in result["items"]] == ["0.1.8"]


def test_product_baseline_prefers_complete_current_policy_over_longer_drift_run() -> None:
    from alphaagent.server.services.backtest.baseline_policy import select_product_baselines

    rows = [
        {
            "id": 213,
            "run_type": "portfolio",
            "strategy_id": "mainline_dragon_pullback",
            "strategy_version": "0.1.23",
            "start_date": "2024-05-28",
            "end_date": "2026-06-18",
            "params": {
                "execution_model": "legacy_next_open",
                "candidate_limit": 20,
                "max_positions": 10,
                "baseline_policy": "long_unconfirmed",
            },
        },
        {
            "id": 203,
            "run_type": "portfolio",
            "strategy_id": "mainline_dragon_pullback",
            "strategy_version": "0.1.23",
            "start_date": "2025-03-26",
            "end_date": "2026-06-18",
            "params": {
                "execution_model": "legacy_next_open",
                "candidate_limit": 20,
                "max_positions": 10,
                "baseline_policy": "current_product",
            },
        },
        {
            "id": 208,
            "run_type": "portfolio",
            "strategy_id": "mainline_dragon_pullback",
            "strategy_version": "0.1.23",
            "start_date": "2025-03-26",
            "end_date": "2026-06-18",
            "params": {
                "execution_model": "legacy_next_open",
                "candidate_limit": 20,
                "max_positions": 10,
                "require_low_suction_launch_for_low_suction_context": True,
            },
        },
    ]

    selected = select_product_baselines(rows)

    assert [row["id"] for row in selected] == [203]
    assert selected[0]["baseline_reason"] == "current_product_policy"
    assert selected[0]["baseline_warning"] is None


def test_product_baseline_uses_common_start_when_no_explicit_policy() -> None:
    from alphaagent.server.services.backtest.baseline_policy import select_product_baselines

    rows = [
        {
            "id": 213,
            "run_type": "portfolio",
            "start_date": "2024-05-28",
            "end_date": "2026-06-18",
            "params": {"symbols": [], "execution_model": "legacy_next_open", "candidate_limit": 20, "max_positions": 10},
        },
        {
            "id": 203,
            "run_type": "portfolio",
            "start_date": "2025-03-26",
            "end_date": "2026-06-18",
            "params": {"symbols": []},
        },
        {
            "id": 194,
            "run_type": "portfolio",
            "start_date": "2025-03-26",
            "end_date": "2026-06-18",
            "params": {"symbols": []},
        },
    ]

    selected = select_product_baselines(rows)

    assert [row["id"] for row in selected] == [203, 194]
    assert {row["baseline_reason"] for row in selected} == {"implicit_common_start_date"}
    assert all(row["baseline_warning"] for row in selected)


def test_product_baseline_keeps_historical_high_return_until_no_cache_improves_metrics() -> None:
    from alphaagent.server.services.backtest.baseline_policy import select_product_baselines

    rows = [
        {
            "id": 275,
            "run_type": "portfolio",
            "start_date": "2025-03-26",
            "end_date": "2026-06-18",
            "params": {
                "symbols": [],
                "execution_model": "legacy_next_open",
                "candidate_limit": 20,
                "max_positions": 10,
                "reuse_signal_cache": False,
            },
            "metrics": {"total_return_pct": 48.80, "win_rate": 0.2976},
        },
        {
            "id": 274,
            "run_type": "portfolio",
            "start_date": "2025-03-26",
            "end_date": "2026-06-18",
            "params": {
                "symbols": [],
                "execution_model": "legacy_next_open",
                "candidate_limit": 20,
                "max_positions": 10,
            },
            "metrics": {"total_return_pct": 45.17, "win_rate": 0.2967},
        },
        {
            "id": 203,
            "run_type": "portfolio",
            "start_date": "2025-03-26",
            "end_date": "2026-06-18",
            "params": {"symbols": []},
            "metrics": {"total_return_pct": 82.99, "win_rate": 0.3224},
        },
        {
            "id": 194,
            "run_type": "portfolio",
            "start_date": "2025-03-26",
            "end_date": "2026-06-18",
            "params": {"symbols": []},
            "metrics": {"total_return_pct": 82.99, "win_rate": 0.3224},
        },
        {
            "id": 213,
            "run_type": "portfolio",
            "start_date": "2024-05-28",
            "end_date": "2026-06-18",
            "params": {
                "symbols": [],
                "execution_model": "legacy_next_open",
                "candidate_limit": 20,
                "max_positions": 10,
            },
        },
    ]

    selected = select_product_baselines(rows)

    assert [row["id"] for row in selected] == [203, 194]
    assert {row["baseline_reason"] for row in selected} == {"historical_high_return_policy"}
    assert all("未同时提升收益率和胜率" in row["baseline_warning"] for row in selected)


def test_product_baseline_promotes_no_cache_run_only_when_return_and_win_rate_improve() -> None:
    from alphaagent.server.services.backtest.baseline_policy import select_product_baselines

    rows = [
        {
            "id": 276,
            "run_type": "portfolio",
            "start_date": "2025-03-26",
            "end_date": "2026-06-18",
            "params": {
                "symbols": [],
                "execution_model": "legacy_next_open",
                "candidate_limit": 20,
                "max_positions": 10,
                "reuse_signal_cache": False,
            },
            "metrics": {"total_return_pct": 90.0, "win_rate": 0.35},
        },
        {
            "id": 203,
            "run_type": "portfolio",
            "start_date": "2025-03-26",
            "end_date": "2026-06-18",
            "params": {"symbols": []},
            "metrics": {"total_return_pct": 82.99, "win_rate": 0.3224},
        },
        {
            "id": 194,
            "run_type": "portfolio",
            "start_date": "2025-03-26",
            "end_date": "2026-06-18",
            "params": {"symbols": []},
            "metrics": {"total_return_pct": 82.99, "win_rate": 0.3224},
        },
    ]

    selected = select_product_baselines(rows)

    assert [row["id"] for row in selected] == [276]
    assert selected[0]["baseline_reason"] == "improved_return_win_rate_policy"
    assert selected[0]["baseline_warning"] is None


def test_next_experiment_switches_default_off_and_excluded_from_baseline() -> None:
    from alphaagent.server.services.backtest.baseline_policy import is_product_baseline_params
    from alphaagent.server.services.backtest.schemas import BacktestParams

    params = BacktestParams()

    switches = [
        "enable_contextual_support_reclaim_delay",
        "enable_contextual_peak_giveback_stop",
        "enable_low_suction_false_launch_watch_gate",
        "enable_market_adaptive_setup_weighting",
        "enable_low_suction_first_lift_bonus",
        "enable_low_suction_lifecycle_ranking",
        "enable_low_suction_buildup_quality_lane",
        "enable_candidate_tail_risk_penalty",
        "enable_mainline_momentum_lane",
        "enable_mainline_momentum_risk_control",
        "enable_mainline_momentum_hard_filter",
        "enable_surge_quality_lane",
        "enable_top20_day_quality_gate",
        "enable_weekly_top_fractal_relief",
        "enable_pure_loss_weak_bucket_penalty",
        "enable_support_divergence_entry_lane",
        "enable_strong_trend_ma_pullback_entry_lane",
        "enable_high_risk_d2_follow_through_entry",
        "enable_dynamic_failed_launch_exit_stop",
    ]
    for switch in switches:
        assert getattr(params, switch) is False
        assert is_product_baseline_params({switch: False}) is True
        assert is_product_baseline_params({switch: True}) is False


def test_exclude_from_product_baseline_round_trips_through_backtest_params() -> None:
    from alphaagent.server.api.backtests import _params_from_payload
    from alphaagent.server.services.backtest.engine import _params_to_json
    from alphaagent.server.services.backtest.baseline_policy import is_product_baseline_params

    params = _params_from_payload({"exclude_from_product_baseline": True})
    payload = _params_to_json(params)

    assert params.exclude_from_product_baseline is True
    assert payload["exclude_from_product_baseline"] is True
    assert is_product_baseline_params(payload) is False


def test_reuse_signal_cache_is_explicit_and_excluded_from_baseline() -> None:
    from alphaagent.server.api.backtests import _params_from_payload
    from alphaagent.server.services.backtest.engine import _params_from_run, _params_to_json
    from alphaagent.server.services.backtest.baseline_policy import is_product_baseline_params
    from alphaagent.server.services.quant.strategy_replay import _params_to_json as replay_params_to_json

    default_params = _params_from_payload({})
    params = _params_from_payload({"reuse_signal_cache": True})
    payload = _params_to_json(params)
    replay_payload = replay_params_to_json(params)
    reloaded = _params_from_run({"params": payload, "strategy_id": DRAGON_PULLBACK_STRATEGY_ID})

    assert default_params.reuse_signal_cache is False
    assert params.reuse_signal_cache is True
    assert payload["reuse_signal_cache"] is True
    assert replay_payload["reuse_signal_cache"] is True
    assert reloaded.reuse_signal_cache is True
    assert is_product_baseline_params(payload) is False


def test_market_adaptive_setup_weighting_round_trips_and_excludes_baseline() -> None:
    from alphaagent.server.api.backtests import _params_from_payload
    from alphaagent.server.services.backtest.engine import _params_from_run, _params_to_json
    from alphaagent.server.services.backtest.baseline_policy import is_product_baseline_params
    from alphaagent.server.services.quant.strategy_replay import _params_to_json as replay_params_to_json

    params = _params_from_payload({"enable_market_adaptive_setup_weighting": True})
    payload = _params_to_json(params)
    replay_payload = replay_params_to_json(params)
    reloaded = _params_from_run({"params": payload, "strategy_id": DRAGON_PULLBACK_STRATEGY_ID})

    assert params.enable_market_adaptive_setup_weighting is True
    assert payload["enable_market_adaptive_setup_weighting"] is True
    assert replay_payload["enable_market_adaptive_setup_weighting"] is True
    assert reloaded.enable_market_adaptive_setup_weighting is True
    assert is_product_baseline_params(payload) is False


def test_low_suction_first_lift_bonus_round_trips_and_excludes_baseline() -> None:
    from alphaagent.server.api.backtests import _params_from_payload
    from alphaagent.server.services.backtest.engine import _params_from_run, _params_to_json
    from alphaagent.server.services.backtest.baseline_policy import is_product_baseline_params
    from alphaagent.server.services.quant.strategy_replay import _params_to_json as replay_params_to_json

    params = _params_from_payload({"enable_low_suction_first_lift_bonus": True})
    payload = _params_to_json(params)
    replay_payload = replay_params_to_json(params)
    reloaded = _params_from_run({"params": payload, "strategy_id": DRAGON_PULLBACK_STRATEGY_ID})

    assert params.enable_low_suction_first_lift_bonus is True
    assert payload["enable_low_suction_first_lift_bonus"] is True
    assert replay_payload["enable_low_suction_first_lift_bonus"] is True
    assert reloaded.enable_low_suction_first_lift_bonus is True
    assert is_product_baseline_params(payload) is False


def test_low_suction_lifecycle_ranking_round_trips_and_excludes_baseline() -> None:
    from alphaagent.server.api.backtests import _params_from_payload
    from alphaagent.server.services.backtest.engine import _params_from_run, _params_to_json
    from alphaagent.server.services.backtest.baseline_policy import is_product_baseline_params
    from alphaagent.server.services.quant.strategy_replay import _params_to_json as replay_params_to_json

    params = _params_from_payload({"enable_low_suction_lifecycle_ranking": True})
    payload = _params_to_json(params)
    replay_payload = replay_params_to_json(params)
    reloaded = _params_from_run({"params": payload, "strategy_id": DRAGON_PULLBACK_STRATEGY_ID})

    assert params.enable_low_suction_lifecycle_ranking is True
    assert payload["enable_low_suction_lifecycle_ranking"] is True
    assert replay_payload["enable_low_suction_lifecycle_ranking"] is True
    assert reloaded.enable_low_suction_lifecycle_ranking is True
    assert is_product_baseline_params(payload) is False


def test_candidate_tail_risk_and_mainline_momentum_round_trip_and_exclude_baseline() -> None:
    from alphaagent.server.api.backtests import _params_from_payload
    from alphaagent.server.services.backtest.engine import _params_from_run, _params_to_json
    from alphaagent.server.services.backtest.baseline_policy import is_product_baseline_params
    from alphaagent.server.services.quant.strategy_replay import _params_to_json as replay_params_to_json

    params = _params_from_payload(
        {
            "enable_candidate_tail_risk_penalty": True,
            "enable_mainline_momentum_lane": True,
            "enable_mainline_momentum_risk_control": True,
            "enable_mainline_momentum_hard_filter": True,
            "enable_surge_quality_lane": True,
            "enable_top20_day_quality_gate": True,
            "enable_weekly_top_fractal_relief": True,
            "enable_low_suction_buildup_quality_lane": True,
            "enable_pure_loss_weak_bucket_penalty": True,
            "enable_support_divergence_entry_lane": True,
            "enable_strong_trend_ma_pullback_entry_lane": True,
            "enable_high_risk_d2_follow_through_entry": True,
        }
    )
    payload = _params_to_json(params)
    replay_payload = replay_params_to_json(params)
    reloaded = _params_from_run({"params": payload, "strategy_id": DRAGON_PULLBACK_STRATEGY_ID})

    assert params.enable_candidate_tail_risk_penalty is True
    assert params.enable_mainline_momentum_lane is True
    assert params.enable_mainline_momentum_risk_control is True
    assert params.enable_mainline_momentum_hard_filter is True
    assert params.enable_surge_quality_lane is True
    assert params.enable_top20_day_quality_gate is True
    assert params.enable_weekly_top_fractal_relief is True
    assert params.enable_low_suction_buildup_quality_lane is True
    assert params.enable_pure_loss_weak_bucket_penalty is True
    assert params.enable_support_divergence_entry_lane is True
    assert params.enable_strong_trend_ma_pullback_entry_lane is True
    assert params.enable_high_risk_d2_follow_through_entry is True
    assert payload["enable_candidate_tail_risk_penalty"] is True
    assert payload["enable_mainline_momentum_lane"] is True
    assert payload["enable_mainline_momentum_risk_control"] is True
    assert payload["enable_mainline_momentum_hard_filter"] is True
    assert payload["enable_surge_quality_lane"] is True
    assert payload["enable_top20_day_quality_gate"] is True
    assert payload["enable_weekly_top_fractal_relief"] is True
    assert payload["enable_low_suction_buildup_quality_lane"] is True
    assert payload["enable_pure_loss_weak_bucket_penalty"] is True
    assert payload["enable_support_divergence_entry_lane"] is True
    assert payload["enable_strong_trend_ma_pullback_entry_lane"] is True
    assert payload["enable_high_risk_d2_follow_through_entry"] is True
    assert replay_payload["enable_candidate_tail_risk_penalty"] is True
    assert replay_payload["enable_mainline_momentum_lane"] is True
    assert replay_payload["enable_mainline_momentum_risk_control"] is True
    assert replay_payload["enable_mainline_momentum_hard_filter"] is True
    assert replay_payload["enable_surge_quality_lane"] is True
    assert replay_payload["enable_top20_day_quality_gate"] is True
    assert replay_payload["enable_weekly_top_fractal_relief"] is True
    assert replay_payload["enable_low_suction_buildup_quality_lane"] is True
    assert replay_payload["enable_pure_loss_weak_bucket_penalty"] is True
    assert replay_payload["enable_support_divergence_entry_lane"] is True
    assert replay_payload["enable_strong_trend_ma_pullback_entry_lane"] is True
    assert replay_payload["enable_high_risk_d2_follow_through_entry"] is True
    assert reloaded.enable_candidate_tail_risk_penalty is True
    assert reloaded.enable_mainline_momentum_lane is True
    assert reloaded.enable_mainline_momentum_risk_control is True
    assert reloaded.enable_mainline_momentum_hard_filter is True
    assert reloaded.enable_surge_quality_lane is True
    assert reloaded.enable_top20_day_quality_gate is True
    assert reloaded.enable_weekly_top_fractal_relief is True
    assert reloaded.enable_low_suction_buildup_quality_lane is True
    assert reloaded.enable_pure_loss_weak_bucket_penalty is True
    assert reloaded.enable_support_divergence_entry_lane is True
    assert reloaded.enable_strong_trend_ma_pullback_entry_lane is True
    assert reloaded.enable_high_risk_d2_follow_through_entry is True
    assert is_product_baseline_params(payload) is False


def test_backtest_list_baseline_only_hides_short_range_experiments(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    class FakeRunRows:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "id": 161,
                    "strategy_id": "mainline_dragon_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2025, 3, 26),
                    "end_date": date(2026, 6, 16),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 1_700_000,
                    "params": {"symbols": [], "enable_contextual_failed_launch_exit_stop": True},
                    "metrics": {},
                },
                {
                    "id": 160,
                    "strategy_id": "mainline_dragon_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2025, 3, 26),
                    "end_date": date(2026, 6, 16),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 1_804_100,
                    "params": {"symbols": [], "exclude_from_product_baseline": True},
                    "metrics": {},
                },
                {
                    "id": 159,
                    "strategy_id": "mainline_dragon_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2025, 3, 26),
                    "end_date": date(2026, 6, 16),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 1_700_000,
                    "params": {"symbols": [], "enable_failed_launch_exit_stop": True},
                    "metrics": {},
                },
                {
                    "id": 1581,
                    "strategy_id": "mainline_dragon_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2025, 3, 26),
                    "end_date": date(2026, 6, 16),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 1_700_000,
                    "params": {"symbols": [], "require_balanced_low_suction_launch_quality": True},
                    "metrics": {},
                },
                {
                    "id": 1580,
                    "strategy_id": "mainline_dragon_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2025, 3, 26),
                    "end_date": date(2026, 6, 16),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 1_700_000,
                    "params": {"symbols": [], "require_low_suction_launch_for_low_suction_context": True},
                    "metrics": {},
                },
                {
                    "id": 158,
                    "strategy_id": "mainline_dragon_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2025, 3, 26),
                    "end_date": date(2026, 6, 16),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 1_700_000,
                    "params": {"symbols": [], "enable_entry_launch_risk_penalty": True},
                    "metrics": {},
                },
                {
                    "id": 157,
                    "strategy_id": "mainline_dragon_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2025, 3, 26),
                    "end_date": date(2026, 6, 16),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 1_700_000,
                    "params": {"symbols": [], "enable_low_suction_market_risk_penalty": True},
                    "metrics": {},
                },
                {
                    "id": 156,
                    "strategy_id": "mainline_dragon_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2025, 3, 26),
                    "end_date": date(2026, 6, 16),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 1_700_000,
                    "params": {"symbols": [], "enable_entry_launch_quality_score": True},
                    "metrics": {},
                },
                {
                    "id": 155,
                    "strategy_id": "mainline_dragon_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2025, 3, 26),
                    "end_date": date(2026, 6, 16),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 1_641_100,
                    "params": {"symbols": [], "mid_profit_giveback_drawdown_pct": 0.05},
                    "metrics": {},
                },
                {
                    "id": 154,
                    "strategy_id": "mainline_dragon_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2025, 3, 26),
                    "end_date": date(2026, 6, 16),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 1_641_100,
                    "params": {"symbols": [], "enable_mid_profit_giveback_stop": True},
                    "metrics": {},
                },
                {
                    "id": 154,
                    "strategy_id": "mainline_dragon_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2025, 8, 6),
                    "end_date": date(2026, 6, 16),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 1_514_100,
                    "params": {"symbols": []},
                    "metrics": {},
                },
                {
                    "id": 153,
                    "strategy_id": "mainline_dragon_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2025, 8, 6),
                    "end_date": date(2026, 6, 16),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 1_514_100,
                    "params": {"symbols": []},
                    "metrics": {},
                },
                {
                    "id": 149,
                    "strategy_id": "mainline_dragon_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2025, 3, 26),
                    "end_date": date(2026, 6, 16),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 1_618_700,
                    "params": {"symbols": []},
                    "metrics": {},
                },
                {
                    "id": 147,
                    "strategy_id": "mainline_dragon_pullback",
                    "strategy_version": "0.1.8",
                    "start_date": date(2025, 3, 26),
                    "end_date": date(2026, 6, 16),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 1_592_700,
                    "params": {"symbols": []},
                    "metrics": {},
                },
            ]

    class FakeSession:
        def execute(self, statement):
            del statement
            return FakeRunRows()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(engine, "is_database_configured", lambda: True)
    monkeypatch.setattr(engine, "_ensure_backtest_schema", lambda: None)
    monkeypatch.setattr(engine, "session_scope", fake_session_scope)

    result = engine.list_backtests(
        limit=50,
        run_type="portfolio",
        strategy_id="mainline_dragon_pullback",
        baseline_only=True,
    )

    assert [item["id"] for item in result["items"]] == [149, 147]

    default_run_type_result = engine.list_backtests(
        limit=50,
        strategy_id="mainline_dragon_pullback",
        baseline_only=True,
    )

    assert [item["id"] for item in default_run_type_result["items"]] == [149, 147]


def test_quant_recommendation_marks_buy_only_for_entry_signal() -> None:
    from alphaagent.server.services.quant import screening

    buy_score = SignalScore(
        vt_symbol="600000.SSE",
        trade_date=date(2026, 1, 2),
        total_score=72,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "ma5_distance_pct": 0.0},
    )
    watch_score = SignalScore(
        vt_symbol="000001.SZSE",
        trade_date=date(2026, 1, 2),
        total_score=72,
        entry_signal=False,
        evidence={"status": "ready", "ma5_distance_pct": 0.0},
    )

    assert screening._recommendation_to_db(1, buy_score, None, "mainline_leader_pullback", min_entry_score=72)["action"] == "BUY"
    assert screening._recommendation_to_db(2, watch_score, None, "mainline_leader_pullback", min_entry_score=72)["action"] == "WATCH"


def test_quant_recommendation_uses_strategy_entry_threshold_for_failed_rules() -> None:
    from alphaagent.server.services.quant import screening

    breakout_watch = SignalScore(
        vt_symbol="002636.SZSE",
        trade_date=date(2026, 1, 2),
        total_score=69,
        signal_type="breakout_confirmation",
        entry_signal=False,
        liquidity_score=80,
        risk_score=80,
        trend_quality_score=80,
        evidence={
            "status": "ready",
            "close_to_prior_high_pct": 0.2,
            "volume_ratio_5d_20d": 1.4,
        },
    )

    result = screening._recommendation_to_db(1, breakout_watch, None, "breakout_confirmation")

    assert result["action"] == "WATCH"
    assert result["reason"]["failed_rules"] == ["total_score"]


def test_quant_recommendation_uses_limit_up_pullback_failed_rules() -> None:
    from alphaagent.server.services.quant import screening

    limit_up_watch = SignalScore(
        vt_symbol="002636.SZSE",
        trade_date=date(2026, 1, 2),
        total_score=74,
        signal_type="limit_up_after_pullback",
        entry_signal=False,
        liquidity_score=80,
        risk_score=80,
        trend_quality_score=80,
        evidence={
            "status": "ready",
            "limit_up_count_20d": 1,
            "days_since_limit_up": 20,
            "ma5_distance_pct": 0.8,
            "ma20_distance_pct": 2.0,
        },
    )

    result = screening._recommendation_to_db(1, limit_up_watch, None, "limit_up_after_pullback")

    assert result["action"] == "WATCH"
    assert result["reason"]["failed_rules"] == ["limit_up_recency"]


def test_stock_board_classification_is_display_only_identity() -> None:
    from alphaagent.market.boards import normalize_included_boards, stock_board, stock_board_payload

    assert stock_board("600000.SSE") == "main"
    assert stock_board("000001.SZSE") == "main"
    assert stock_board("300750.SZSE") == "chinext"
    assert stock_board("688981.SSE") == "star"
    assert stock_board("920001.BSE") == "bse"
    assert stock_board_payload("300750.SZSE")["board_label"] == "创业板"
    assert normalize_included_boards(None) == ("main",)
    assert normalize_included_boards("main,chinext,main") == ("main", "chinext")


def test_quant_universe_defaults_to_main_board_only() -> None:
    from alphaagent.server.services.quant import screening

    rows = [
        {"vt_symbol": "300750.SZSE", "exchange": "SZSE", "turnover": 300, "market_cap": 300},
        {"vt_symbol": "000001.SZSE", "exchange": "SZSE", "turnover": 200, "market_cap": 200},
        {"vt_symbol": "000078.SZSE", "exchange": "SZSE", "name": "ST海王", "turnover": 150, "market_cap": 150},
        {"vt_symbol": "001001.SZSE", "exchange": "SZSE", "name": "N新股", "turnover": 140, "market_cap": 140},
        {"vt_symbol": "001002.SZSE", "exchange": "SZSE", "name": "C新股", "turnover": 130, "market_cap": 130},
        {"vt_symbol": "600000.SSE", "exchange": "SSE", "turnover": 100, "market_cap": 100},
        {"vt_symbol": "688981.SSE", "exchange": "SSE", "turnover": 100, "market_cap": 100},
        {"vt_symbol": "920001.BSE", "exchange": "BSE", "turnover": 50, "market_cap": 50},
    ]

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return rows

    class FakeSession:
        def execute(self, statement):
            del statement
            return FakeResult()

    default_symbols = [row["vt_symbol"] for row in screening._load_stock_universe(FakeSession(), 1, ("main",))]
    all_symbols = [row["vt_symbol"] for row in screening._load_stock_universe(FakeSession(), 10, ("main", "chinext", "star", "bse"))]

    assert "300750.SZSE" not in default_symbols
    assert "688981.SSE" not in default_symbols
    assert "920001.BSE" not in default_symbols
    assert default_symbols == ["000001.SZSE"]
    assert "300750.SZSE" in all_symbols
    assert "000078.SZSE" not in all_symbols
    assert "001001.SZSE" not in all_symbols
    assert "001002.SZSE" not in all_symbols
    assert "688981.SSE" in all_symbols
    assert "920001.BSE" in all_symbols


def test_backtest_universe_filters_boards_only_for_generated_pool() -> None:
    from alphaagent.server.services.backtest import engine

    class FakeAllResult:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if "stocks.vt_symbol IN" in text:
                return FakeAllResult([("300750.SZSE",)])
            return FakeAllResult(
                [
                    ("000001.SZSE", "SZSE", 300.0, 300.0),
                    ("300750.SZSE", "SZSE", 500.0, 500.0),
                    ("600000.SSE", "SSE", 100.0, 100.0),
                    ("688981.SSE", "SSE", 400.0, 400.0),
                ]
            )

    generated = engine._load_symbol_universe(FakeSession(), 1, None, ("main",))
    requested = engine._load_symbol_universe(FakeSession(), 10, ["300750.SZSE"], ("main",))

    assert generated == ["000001.SZSE"]
    assert requested == ["300750.SZSE"]


def test_candidate_trace_universe_context_uses_liquidity_order() -> None:
    from alphaagent.server.services.backtest import queries
    from alphaagent.server.db import schema

    rows = [
        {
            "vt_symbol": "600000.SSE",
            "name": "浦发银行",
            "exchange": "SSE",
            "turnover": 500.0,
            "market_cap": 500.0,
        },
        {
            "vt_symbol": "000001.SZSE",
            "name": "平安银行",
            "exchange": "SZSE",
            "turnover": 100.0,
            "market_cap": 100.0,
        },
    ]

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return rows

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            assert "coalesce(stocks.turnover" in text
            assert "coalesce(stocks.market_cap" in text
            assert " DESC" in text
            return FakeResult()

    def board_payload(vt_symbol, stock):
        del vt_symbol, stock
        return {"board": "main"}

    result = queries._universe_context(
        FakeSession(),
        schema,
        "600000.SSE",
        {"max_symbols": 1, "included_boards": ["main"]},
        board_payload,
    )

    assert result["target_universe_rank"] == 1
    assert result["target_in_universe"] is True


def test_backtest_score_cache_requires_matching_screen_boards() -> None:
    from alphaagent.server.services.backtest import engine

    class FakeRows:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class FakeSession:
        def __init__(self):
            self.executed: list[str] = []

        def execute(self, statement):
            self.executed.append(str(statement))
            return FakeRows(
                [
                    {
                        "id": 9,
                        "trade_date": date(2026, 1, 2),
                        "params": {"included_boards": ["chinext"], "max_symbols": 5000},
                    }
                ]
            )

    session = FakeSession()
    params = engine.BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        start=date(2026, 1, 2),
        end=date(2026, 1, 3),
        included_boards=("main",),
        persist=True,
    )

    result = engine._load_score_cache_from_persisted_signals(
        session,
        params,
        "0.1.8",
        ["600000.SSE"],
        [date(2026, 1, 2), date(2026, 1, 3)],
    )

    assert result is None
    assert len(session.executed) == 1


def test_backtest_score_cache_loads_matching_screen_run_by_run_id() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.quant import screening_payloads

    class FakeRows:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class FakeSession:
        def __init__(self):
            self.executed: list[str] = []

        def execute(self, statement):
            text = str(statement)
            self.executed.append(text)
            if "FROM quant_signal_runs" in text:
                return FakeRows(
                    [
                            {
                                "id": 42,
                                "trade_date": date(2026, 1, 2),
                                "params": {
                                    "included_boards": ["main"],
                                    "max_symbols": 5000,
                                    "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                                },
                            }
                        ]
                    )
            assert "quant_stock_signals.run_id IN" in text
            return FakeRows(
                [
                    {
                        "run_id": 42,
                        "trade_date": date(2026, 1, 2),
                        "vt_symbol": f"600{index:03d}.SSE",
                        "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
                        "strategy_version": "0.1.8",
                        "signal_type": DRAGON_PULLBACK_STRATEGY_ID,
                        "total_score": 82,
                        "relative_strength_score": 70,
                        "washout_score": 75,
                        "trend_quality_score": 80,
                        "sector_mainline_score": 60,
                        "financial_improvement_score": 55,
                        "liquidity_score": 85,
                        "risk_score": 72,
                        "entry_signal": True,
                        "risk_level": "LOW",
                        "evidence": {"status": "ready"},
                    }
                    for index in range(50)
                ]
            )

    params = engine.BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        start=date(2026, 1, 2),
        end=date(2026, 1, 3),
        max_symbols=5000,
        included_boards=("main",),
        persist=True,
    )

    result = engine._load_score_cache_from_persisted_signals(
        FakeSession(),
        params,
        "0.1.8",
        [f"600{index:03d}.SSE" for index in range(50)],
        [date(2026, 1, 2), date(2026, 1, 3)],
    )

    assert result is not None
    assert len(result[date(2026, 1, 2)]) == 50


def test_backtest_score_cache_can_be_reused_for_non_persisted_backtest() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.quant import screening_payloads

    class FakeRows:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class FakeSession:
        def execute(self, statement):
            if "FROM quant_signal_runs" in str(statement):
                return FakeRows(
                    [
                        {
                            "id": 42,
                            "trade_date": date(2026, 1, 2),
                            "params": {
                                "included_boards": ["main"],
                                "max_symbols": 5000,
                                "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                            },
                        }
                    ]
                )
            return FakeRows(
                [
                    {
                        "run_id": 42,
                        "trade_date": date(2026, 1, 2),
                        "vt_symbol": f"600{index:03d}.SSE",
                        "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
                        "strategy_version": "0.1.23",
                        "signal_type": DRAGON_PULLBACK_STRATEGY_ID,
                        "total_score": 80,
                        "relative_strength_score": 70,
                        "washout_score": 75,
                        "trend_quality_score": 80,
                        "sector_mainline_score": 60,
                        "financial_improvement_score": 55,
                        "liquidity_score": 85,
                        "risk_score": 72,
                        "entry_signal": True,
                        "risk_level": "LOW",
                        "evidence": {"status": "ready"},
                    }
                    for index in range(50)
                ]
            )

    params = engine.BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        start=date(2026, 1, 2),
        end=date(2026, 1, 3),
        max_symbols=5000,
        included_boards=("main",),
        persist=False,
    )

    result = engine._load_score_cache_from_persisted_signals(
        FakeSession(),
        params,
        "0.1.23",
        [f"600{index:03d}.SSE" for index in range(50)],
        [date(2026, 1, 2), date(2026, 1, 3)],
    )

    assert result is not None
    assert len(result[date(2026, 1, 2)]) == 50


def test_backtest_score_cache_drops_sparse_stale_signal_rows() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.quant import screening_payloads

    class FakeRows:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class FakeSession:
        def execute(self, statement):
            if "FROM quant_signal_runs" in str(statement):
                return FakeRows(
                    [
                        {
                            "id": 42,
                            "trade_date": date(2025, 8, 6),
                            "params": {
                                "included_boards": ["main"],
                                "max_symbols": 5000,
                                "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                            },
                        }
                    ]
                )
            return FakeRows(
                [
                    {
                        "run_id": 42,
                        "trade_date": date(2025, 8, 6),
                        "vt_symbol": "600000.SSE",
                        "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
                        "strategy_version": "0.1.23",
                        "signal_type": DRAGON_PULLBACK_STRATEGY_ID,
                        "total_score": 80,
                        "relative_strength_score": 70,
                        "washout_score": 75,
                        "trend_quality_score": 80,
                        "sector_mainline_score": 60,
                        "financial_improvement_score": 55,
                        "liquidity_score": 85,
                        "risk_score": 72,
                        "entry_signal": True,
                        "risk_level": "LOW",
                        "evidence": {"status": "ready"},
                    }
                ]
            )

    params = engine.BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        start=date(2025, 8, 6),
        end=date(2025, 8, 7),
        max_symbols=5000,
        included_boards=("main",),
        persist=False,
    )

    result = engine._load_score_cache_from_persisted_signals(
        FakeSession(),
        params,
        "0.1.23",
        [f"600{index:03d}.SSE" for index in range(50)],
        [date(2025, 8, 6), date(2025, 8, 7)],
        bars_by_symbol={
            f"600{index:03d}.SSE": [
                Bar(
                    trade_date=date(2025, 8, 6),
                    open_price=10,
                    high_price=10.5,
                    low_price=9.8,
                    close_price=10.2,
                )
            ]
            for index in range(50)
        },
    )

    assert result is None


def test_backtest_score_cache_keeps_sparse_rows_when_daily_coverage_is_sparse() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.quant import screening_payloads

    class FakeRows:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class FakeSession:
        def execute(self, statement):
            if "FROM quant_signal_runs" in str(statement):
                return FakeRows(
                    [
                        {
                            "id": 42,
                            "trade_date": date(2025, 3, 26),
                            "params": {
                                "included_boards": ["main"],
                                "max_symbols": 5000,
                                "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                            },
                        }
                    ]
                )
            return FakeRows(
                [
                    {
                        "run_id": 42,
                        "trade_date": date(2025, 3, 26),
                        "vt_symbol": "600000.SSE",
                        "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
                        "strategy_version": "0.1.23",
                        "signal_type": DRAGON_PULLBACK_STRATEGY_ID,
                        "total_score": 80,
                        "relative_strength_score": 70,
                        "washout_score": 75,
                        "trend_quality_score": 80,
                        "sector_mainline_score": 60,
                        "financial_improvement_score": 55,
                        "liquidity_score": 85,
                        "risk_score": 72,
                        "entry_signal": True,
                        "risk_level": "LOW",
                        "evidence": {"status": "ready"},
                    }
                ]
            )

    params = engine.BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        start=date(2025, 3, 26),
        end=date(2025, 3, 27),
        max_symbols=5000,
        included_boards=("main",),
        persist=False,
    )

    result = engine._load_score_cache_from_persisted_signals(
        FakeSession(),
        params,
        "0.1.23",
        ["600000.SSE"],
        [date(2025, 3, 26), date(2025, 3, 27)],
        bars_by_symbol={
            "600000.SSE": [
                Bar(
                    trade_date=date(2025, 3, 26),
                    open_price=10,
                    high_price=10.5,
                    low_price=9.8,
                    close_price=10.2,
                )
            ]
        },
    )

    assert result is not None
    assert len(result[date(2025, 3, 26)]) == 1


def test_backtest_score_cache_reuses_complete_dates_and_skips_sparse_dates() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.quant import screening_payloads

    complete_day = date(2026, 1, 2)
    sparse_day = date(2026, 1, 3)
    execute_day = date(2026, 1, 4)

    class FakeRows:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class FakeSession:
        def execute(self, statement):
            if "FROM quant_signal_runs" in str(statement):
                return FakeRows(
                    [
                        {
                            "id": 42,
                            "trade_date": complete_day,
                            "params": {
                                "included_boards": ["main"],
                                "max_symbols": 5000,
                                "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                            },
                        },
                        {
                            "id": 43,
                            "trade_date": sparse_day,
                            "params": {
                                "included_boards": ["main"],
                                "max_symbols": 5000,
                                "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                            },
                        },
                    ]
                )
            return FakeRows(
                [
                    {
                        "run_id": 42,
                        "trade_date": complete_day,
                        "vt_symbol": f"600{index:03d}.SSE",
                        "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
                        "strategy_version": "0.1.23",
                        "signal_type": DRAGON_PULLBACK_STRATEGY_ID,
                        "total_score": 80,
                        "relative_strength_score": 70,
                        "washout_score": 75,
                        "trend_quality_score": 80,
                        "sector_mainline_score": 60,
                        "financial_improvement_score": 55,
                        "liquidity_score": 85,
                        "risk_score": 72,
                        "entry_signal": True,
                        "risk_level": "LOW",
                        "evidence": {"status": "ready"},
                    }
                    for index in range(50)
                ]
                + [
                    {
                        "run_id": 43,
                        "trade_date": sparse_day,
                        "vt_symbol": "601000.SSE",
                        "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
                        "strategy_version": "0.1.23",
                        "signal_type": DRAGON_PULLBACK_STRATEGY_ID,
                        "total_score": 80,
                        "relative_strength_score": 70,
                        "washout_score": 75,
                        "trend_quality_score": 80,
                        "sector_mainline_score": 60,
                        "financial_improvement_score": 55,
                        "liquidity_score": 85,
                        "risk_score": 72,
                        "entry_signal": True,
                        "risk_level": "LOW",
                        "evidence": {"status": "ready"},
                    }
                ]
            )

    params = engine.BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        start=complete_day,
        end=execute_day,
        max_symbols=5000,
        included_boards=("main",),
        persist=False,
    )

    result = engine._load_score_cache_from_persisted_signals(
        FakeSession(),
        params,
        "0.1.23",
        [f"600{index:03d}.SSE" for index in range(50)] + ["601000.SSE"],
        [complete_day, sparse_day, execute_day],
    )

    assert result is not None
    assert len(result[complete_day]) == 50
    assert sparse_day not in result


def test_backtest_score_cache_backfills_market_context_for_low_suction_experiment(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.quant import screening_payloads

    class FakeRows:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class FakeContext:
        def to_dict(self):
            return {
                "regime": "weak_defensive",
                "label": "弱势防守",
                "market_score": 38,
                "breadth_score": 32,
                "risk_score": 68,
                "fund_flow_state": "unknown",
                "fund_flow_label": "资金未知",
                "fund_flow_score": None,
                "fund_flow_streak_days": 0,
                "fund_flow_source": None,
                "market_warning_level": 3,
                "market_warning_label": "强风险",
                "recovery_state": "none",
                "recovery_label": "未回暖",
                "source": "unit_test",
            }

    class FakeSession:
        def execute(self, statement):
            if "FROM quant_signal_runs" in str(statement):
                return FakeRows(
                    [
                        {
                            "id": 42,
                            "trade_date": date(2026, 3, 12),
                            "params": {
                                "included_boards": ["main"],
                                "max_symbols": 5000,
                                "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                            },
                        }
                    ]
                )
            return FakeRows(
                [
                    {
                        "run_id": 42,
                        "trade_date": date(2026, 3, 12),
                        "vt_symbol": "600352.SSE" if index == 0 else f"600{index:03d}.SSE",
                        "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
                        "strategy_version": "0.1.23",
                        "signal_type": DRAGON_PULLBACK_STRATEGY_ID,
                        "total_score": 82,
                        "relative_strength_score": 70,
                        "washout_score": 75,
                        "trend_quality_score": 80,
                        "sector_mainline_score": 60,
                        "financial_improvement_score": 55,
                        "liquidity_score": 85,
                        "risk_score": 72,
                        "entry_signal": True,
                        "risk_level": "LOW",
                        "evidence": {
                            "status": "ready",
                            "entry_setup": "stealth_low_suction",
                            "low_suction_launch_confirmed": True,
                            "pullback_days": 13,
                            "close_location_in_range": 0.72,
                            "volume_ratio_5d_20d": 0.62,
                        },
                    }
                    for index in range(50)
                ]
            )

    monkeypatch.setattr(
        engine.market_context,
        "compute_market_contexts",
        lambda _session, _schema, dates: {date(2026, 3, 12): FakeContext()},
    )
    params = engine.BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        start=date(2026, 3, 12),
        end=date(2026, 3, 13),
        max_symbols=5000,
        included_boards=("main",),
        persist=True,
        enable_low_suction_market_risk_penalty=True,
    )

    result = engine._load_score_cache_from_persisted_signals(
        FakeSession(),
        params,
        "0.1.23",
        ["600352.SSE", *[f"600{index:03d}.SSE" for index in range(1, 50)]],
        [date(2026, 3, 12), date(2026, 3, 13)],
    )

    score = result[date(2026, 3, 12)][0]
    assert score.evidence["dynamic_market_regime"] == "weak_defensive"
    assert score.evidence["market_breadth_score"] == 32
    assert score.evidence["recovery_state"] == "none"


def test_backtest_score_cache_backfills_market_context_for_candidate_quality_experiments(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.quant import screening_payloads

    class FakeRows:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class FakeContext:
        def to_dict(self):
            return {
                "regime": "false_bull",
                "label": "假强势",
                "market_score": 58,
                "breadth_score": 36,
                "risk_score": 64,
                "fund_flow_state": "panic_outflow",
                "fund_flow_label": "恐慌流出",
                "fund_flow_score": 18,
                "fund_flow_streak_days": 3,
                "fund_flow_source": "unit_test",
                "market_warning_level": 3,
                "market_warning_label": "风险偏高",
                "recovery_state": "none",
                "recovery_label": "未回暖",
                "source": "unit_test",
            }

    class FakeSession:
        def execute(self, statement):
            if "FROM quant_signal_runs" in str(statement):
                return FakeRows(
                    [
                        {
                            "id": 43,
                            "trade_date": date(2026, 5, 13),
                            "params": {
                                "included_boards": ["main"],
                                "max_symbols": 5000,
                                "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                            },
                        }
                    ]
                )
            return FakeRows(
                [
                    {
                        "run_id": 43,
                        "trade_date": date(2026, 5, 13),
                        "vt_symbol": f"600{index:03d}.SSE",
                        "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
                        "strategy_version": "0.1.23",
                        "signal_type": DRAGON_PULLBACK_STRATEGY_ID,
                        "total_score": 88,
                        "relative_strength_score": 82,
                        "washout_score": 75,
                        "trend_quality_score": 80,
                        "sector_mainline_score": 60,
                        "financial_improvement_score": 55,
                        "liquidity_score": 85,
                        "risk_score": 72,
                        "entry_signal": True,
                        "risk_level": "LOW",
                        "evidence": {
                            "status": "ready",
                            "entry_setup": "dragon_pullback",
                            "low_suction_launch_quality_bucket": "high_close_launch",
                            "close_location_in_range": 0.91,
                            "volume_ratio_5d_20d": 1.1,
                        },
                    }
                    for index in range(50)
                ]
            )

    monkeypatch.setattr(
        engine.market_context,
        "compute_market_contexts",
        lambda _session, _schema, dates: {date(2026, 5, 13): FakeContext()},
    )
    market_context_experiment_flags = [
        "enable_candidate_tail_risk_penalty",
        "enable_mainline_momentum_lane",
        "enable_surge_quality_lane",
        "enable_top20_day_quality_gate",
        "enable_weekly_top_fractal_relief",
        "enable_low_suction_buildup_quality_lane",
        "enable_pure_loss_weak_bucket_penalty",
        "enable_low_suction_false_launch_watch_gate",
        "enable_market_adaptive_setup_weighting",
    ]

    for flag in market_context_experiment_flags:
        params = engine.BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            start=date(2026, 5, 13),
            end=date(2026, 5, 14),
            max_symbols=5000,
            included_boards=("main",),
            persist=True,
            **{flag: True},
        )

        result = engine._load_score_cache_from_persisted_signals(
            FakeSession(),
            params,
            "0.1.23",
            [f"600{index:03d}.SSE" for index in range(50)],
            [date(2026, 5, 13), date(2026, 5, 14)],
        )

        score = result[date(2026, 5, 13)][0]
        assert score.evidence["dynamic_market_regime"] == "false_bull", flag
        assert score.evidence["market_warning_level"] == 3, flag
        assert score.evidence["recovery_state"] == "none", flag


def test_backtest_score_cache_backfills_read_only_early_dragon_risk() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.quant import screening_payloads

    class FakeRows:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class FakeSession:
        def execute(self, statement):
            if "FROM quant_signal_runs" in str(statement):
                return FakeRows(
                    [
                        {
                            "id": 42,
                            "trade_date": date(2026, 2, 2),
                            "params": {
                                "included_boards": ["main"],
                                "max_symbols": 5000,
                                "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                            },
                        }
                    ]
                )
            return FakeRows(
                [
                    {
                        "run_id": 42,
                        "trade_date": date(2026, 2, 2),
                        "vt_symbol": "601179.SSE" if index == 0 else f"600{index:03d}.SSE",
                        "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
                        "strategy_version": "0.1.23",
                        "signal_type": DRAGON_PULLBACK_STRATEGY_ID,
                        "total_score": 96.1786 if index == 0 else 80,
                        "relative_strength_score": 100 if index == 0 else 70,
                        "washout_score": 100 if index == 0 else 75,
                        "trend_quality_score": 100 if index == 0 else 80,
                        "sector_mainline_score": 50,
                        "financial_improvement_score": 70,
                        "liquidity_score": 100,
                        "risk_score": 80,
                        "entry_signal": True,
                        "risk_level": "LOW",
                        "evidence": {
                            "status": "ready",
                            "entry_setup": "dragon_pullback",
                            "setup_type": "dragon_pullback",
                            "low_suction_days": 0,
                            "ma_convergence_pct": 22.91,
                            "latest_change_pct": 7.58,
                            "close_location_in_range": 0.62,
                            "failed_rules": [],
                            "score_notes": ["状态 TAIL_BUY_READY"],
                        }
                        if index == 0
                        else {"status": "ready"},
                    }
                    for index in range(50)
                ]
            )

    params = engine.BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        start=date(2026, 2, 2),
        end=date(2026, 2, 3),
        max_symbols=5000,
        included_boards=("main",),
        persist=True,
    )

    result = engine._load_score_cache_from_persisted_signals(
        FakeSession(),
        params,
        "0.1.23",
        ["601179.SSE", *[f"600{index:03d}.SSE" for index in range(1, 50)]],
        [date(2026, 2, 2), date(2026, 2, 3)],
    )

    score = result[date(2026, 2, 2)][0]
    assert score.entry_signal is True
    assert score.evidence["early_dragon_pullback_risk"] is True
    assert "经典龙回头偏早：均线发散且缺少低吸蓄势" in score.evidence["score_notes"]


def test_backtest_score_cache_prefilters_stealth_low_suction_threshold() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.quant import screening_payloads

    class FakeRows:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class FakeSession:
        def __init__(self):
            self.compiled_params: list[dict[str, object]] = []

        def execute(self, statement):
            text = str(statement)
            self.compiled_params.append(dict(statement.compile().params))
            if "FROM quant_signal_runs" in text:
                return FakeRows(
                    [
                            {
                                "id": 42,
                                "trade_date": date(2026, 1, 2),
                                "params": {
                                    "included_boards": ["main"],
                                    "max_symbols": 5000,
                                    "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                                },
                            }
                        ]
                    )
            return FakeRows([])

    session = FakeSession()
    params = engine.BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        start=date(2026, 1, 2),
        end=date(2026, 1, 3),
        min_entry_score=76.0,
        max_symbols=5000,
        included_boards=("main",),
        persist=True,
    )

    engine._load_score_cache_from_persisted_signals(
        session,
        params,
        "0.1.14",
        ["002208.SZSE"],
        [date(2026, 1, 2), date(2026, 1, 3)],
    )

    assert any(value == 74.5 for value in session.compiled_params[1].values())


def test_persist_screen_run_clears_same_day_outputs_before_insert() -> None:
    from alphaagent.server.services.quant import screening

    calls: list[str] = []

    class FakeReturning:
        def scalar_one(self):
            return 7

    class FakeScalar:
        def scalar_one_or_none(self):
            return None

    class FakeSession:
        def execute(self, statement, params=None):
            text = str(statement)
            if text.startswith("INSERT INTO quant_signal_runs"):
                return FakeReturning()
            if text.startswith("DELETE FROM quant_recommendations"):
                calls.append("delete_recommendations")
                return FakeScalar()
            if text.startswith("DELETE FROM quant_stock_signals"):
                calls.append("delete_signals")
                return FakeScalar()
            if text.startswith("INSERT INTO quant_stock_signals"):
                calls.append("insert_signal")
                return FakeScalar()
            if text.startswith("INSERT INTO quant_recommendations"):
                calls.append("insert_recommendation")
                return FakeScalar()
            return FakeScalar()

    score = SignalScore(
        vt_symbol="600000.SSE",
        trade_date=date(2026, 1, 2),
        total_score=72,
        entry_signal=True,
        evidence={"status": "ready"},
    )

    run_id = screening._persist_screen_run(FakeSession(), date(2026, 1, 2), [score], [score], "mainline_leader_pullback", ("main",))

    assert run_id == 7
    assert calls == ["delete_recommendations", "delete_signals", "insert_signal", "insert_recommendation"]


def test_persist_screen_run_dedupes_same_symbol_scores_before_insert() -> None:
    from alphaagent.server.services.quant import screening

    inserted_run: dict[str, object] = {}
    inserted_signal_rows: list[dict[str, object]] = []
    inserted_recommendation_rows: list[dict[str, object]] = []

    class FakeReturning:
        def scalar_one(self):
            return 7

    class FakeScalar:
        def scalar_one_or_none(self):
            return None

    class FakeSession:
        def execute(self, statement, params=None):
            text = str(statement)
            if text.startswith("INSERT INTO quant_signal_runs"):
                inserted_run.update(dict(statement.compile().params))
                return FakeReturning()
            if text.startswith("INSERT INTO quant_stock_signals"):
                inserted_signal_rows.extend(params or [])
                return FakeScalar()
            if text.startswith("INSERT INTO quant_recommendations"):
                inserted_recommendation_rows.extend(params or [])
                return FakeScalar()
            return FakeScalar()

    first = SignalScore(
        vt_symbol="600000.SSE",
        trade_date=date(2026, 4, 9),
        total_score=95,
        entry_signal=True,
        evidence={"status": "ready"},
    )
    duplicate = SignalScore(
        vt_symbol="600000.SSE",
        trade_date=date(2026, 4, 9),
        total_score=90,
        entry_signal=True,
        evidence={"status": "ready", "candidate_source": "duplicate_lane"},
    )
    other = SignalScore(
        vt_symbol="600001.SSE",
        trade_date=date(2026, 4, 9),
        total_score=88,
        entry_signal=False,
        evidence={"status": "ready"},
    )

    run_id = screening._persist_screen_run(
        FakeSession(),
        date(2026, 4, 9),
        [first, duplicate, other],
        [first, duplicate],
        "mainline_leader_pullback",
        ("main",),
    )

    assert run_id == 7
    assert inserted_run["candidate_count"] == 2
    assert inserted_run["recommendation_count"] == 1
    assert [row["vt_symbol"] for row in inserted_signal_rows] == ["600000.SSE", "600001.SSE"]
    assert [row["vt_symbol"] for row in inserted_recommendation_rows] == ["600000.SSE"]


def test_persist_screen_run_counts_only_executable_buy_signals() -> None:
    from alphaagent.server.services.quant import screening

    inserted_run: dict[str, object] = {}

    class FakeReturning:
        def scalar_one(self):
            return 7

    class FakeScalar:
        def scalar_one_or_none(self):
            return None

    class FakeSession:
        def execute(self, statement, params=None):
            text = str(statement)
            if text.startswith("INSERT INTO quant_signal_runs"):
                inserted_run.update(dict(statement.compile().params))
                return FakeReturning()
            return FakeScalar()

    raw_watch = SignalScore(
        vt_symbol="600004.SSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=80,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "failed_rules": ["strong_leg"]},
    )
    executable_buy = SignalScore(
        vt_symbol="002384.SZSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=93,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "failed_rules": []},
    )

    screening._persist_screen_run(
        FakeSession(),
        date(2026, 6, 12),
        [raw_watch, executable_buy],
        [raw_watch, executable_buy],
        DRAGON_PULLBACK_STRATEGY_ID,
        strategy_version="0.1.8",
        included_boards=("main",),
    )

    assert inserted_run["signal_count"] == 1


def test_sync_quant_candidate_group_reason_uses_executable_action() -> None:
    import json

    from alphaagent.server.services.quant import screening_persistence

    inserted_reason: dict[str, object] = {}

    class FakeScalarNone:
        def scalar_one_or_none(self):
            return None

    class FakeScalarGroup:
        def scalar_one(self):
            return 9

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if text.startswith("SELECT portfolio_groups.id"):
                return FakeScalarNone()
            if text.startswith("INSERT INTO portfolio_groups"):
                return FakeScalarGroup()
            if text.startswith("DELETE FROM portfolio_group_items"):
                return FakeScalarNone()
            if text.startswith("SELECT portfolio_group_items.vt_symbol"):
                return FakeScalarNone()
            if text.startswith("INSERT INTO portfolio_group_items"):
                inserted_reason.update(json.loads(statement.compile().params["reason"]))
                return FakeScalarGroup()
            return FakeScalarGroup()

    raw_watch = SignalScore(
        vt_symbol="600004.SSE",
        trade_date=date(2026, 6, 12),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=80,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        risk_level="MEDIUM",
        evidence={"status": "ready", "failed_rules": ["strong_leg"]},
    )

    result = screening_persistence.sync_quant_candidate_group(
        FakeSession(),
        [raw_watch],
        {"600004.SSE": {"name": "测试股"}},
        DRAGON_PULLBACK_STRATEGY_ID,
        "0.1.8",
    )

    assert result["synced"] == 1
    assert inserted_reason["raw_entry_signal"] is True
    assert inserted_reason["executable_entry_signal"] is False
    assert inserted_reason["entry_signal"] is False
    assert inserted_reason["action"] == "WATCH"
    assert inserted_reason["failed_rules"] == ["strong_leg"]


def test_recommendations_use_latest_screen_run_id_when_latest_run_has_no_items(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening
    from alphaagent.server.services.quant import screening_payloads

    executed: list[str] = []

    class FakeRows:
        def __init__(self, rows=None):
            self.rows = rows or []

        def mappings(self):
            return self

        def first(self):
            return self.rows[0] if self.rows else None

        def all(self):
            return self.rows

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            executed.append(text)
            if "FROM quant_signal_runs" in text:
                return FakeRows([
                    {
                        "id": 8,
                        "trade_date": date(2026, 1, 3),
                        "strategy_id": "mainline_leader_pullback",
                        "strategy_version": "0.1.1",
                        "params": {
                            "included_boards": ["main"],
                            "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                        },
                    }
                ])
            return FakeRows()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_complete_trade_date", lambda session: date(2026, 1, 3))

    result = screening.list_recommendations()

    assert result["status"] == "empty"
    assert result["trade_date"] == "2026-01-03"
    assert result["run_id"] == 8
    assert result["items"] == []
    assert any("quant_signal_runs.strategy_version = :strategy_version_1" in statement for statement in executed)
    assert any("quant_signal_runs.status = :status_1" in statement for statement in executed)
    assert any("quant_recommendations.run_id = :run_id_1" in statement for statement in executed)


def test_recommendations_use_latest_screen_run_id_not_same_day_old_versions(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening
    from alphaagent.server.services.quant import screening_payloads

    executed: list[str] = []

    class FakeRows:
        def __init__(self, rows=None):
            self.rows = rows or []

        def mappings(self):
            return self

        def first(self):
            return self.rows[0] if self.rows else None

        def all(self):
            return self.rows

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            executed.append(text)
            if "FROM quant_signal_runs" in text:
                return FakeRows([
                    {
                        "id": 6,
                        "trade_date": date(2026, 6, 11),
                        "strategy_id": "mainline_leader_pullback",
                        "strategy_version": "0.1.1",
                        "params": {
                            "included_boards": ["main"],
                            "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                        },
                    }
                ])
            return FakeRows([])

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_complete_trade_date", lambda session: date(2026, 6, 11))

    result = screening.list_recommendations()

    assert result["run_id"] == 6
    assert result["strategy_version"] == "0.1.1"
    assert result["included_boards"] == ["main"]
    assert result["trade_date"] == "2026-06-11"
    assert any("quant_signal_runs.strategy_version = :strategy_version_1" in statement for statement in executed)
    assert any("quant_signal_runs.status = :status_1" in statement for statement in executed)
    assert any("quant_recommendations.run_id = :run_id_1" in statement for statement in executed)
    assert not any(
        "quant_recommendations.trade_date = :trade_date_1" in statement
        and "quant_recommendations.run_id = :run_id_1" not in statement
        for statement in executed
    )


def test_signals_use_latest_screen_run_id_not_same_day_old_versions(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening, screening_payloads

    executed: list[str] = []

    class FakeRows:
        def __init__(self, rows=None):
            self.rows = rows or []

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            executed.append(text)
            if "FROM quant_signal_runs" in text:
                return FakeRows(
                    [
                        {
                            "id": 6,
                            "trade_date": date(2026, 6, 11),
                            "strategy_id": "mainline_leader_pullback",
                            "strategy_version": "0.1.1",
                            "params": {
                                "included_boards": ["main"],
                                "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                            },
                        }
                    ]
                )
            assert "quant_stock_signals.run_id = :run_id_1" in text
            return FakeRows(
                [
                    {
                        "id": 1,
                        "run_id": 6,
                        "trade_date": date(2026, 6, 11),
                        "vt_symbol": "003004.SZSE",
                        "strategy_id": "mainline_leader_pullback",
                        "strategy_version": "0.1.1",
                        "signal_type": "mainline_leader_pullback",
                        "total_score": 91.0,
                        "relative_strength_score": 80.0,
                        "washout_score": 70.0,
                        "trend_quality_score": 75.0,
                        "sector_mainline_score": 60.0,
                        "financial_improvement_score": 50.0,
                        "liquidity_score": 80.0,
                        "risk_score": 80.0,
                        "entry_signal": True,
                        "risk_level": "LOW",
                        "evidence": {"status": "ready"},
                    }
                ]
            )

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_complete_trade_date", lambda session: date(2026, 6, 11))

    result = screening.list_signals()

    assert result["run_id"] == 6
    assert result["items"][0]["run_id"] == 6
    assert any("quant_stock_signals.run_id = :run_id_1" in statement for statement in executed)
    assert not any(
        "quant_stock_signals.trade_date = :trade_date_1" in statement
        and "quant_stock_signals.run_id = :run_id_1" not in statement
        for statement in executed
    )


def test_latest_screen_run_skips_stale_signal_evidence_schema() -> None:
    from alphaagent.server.services.quant import screening_loaders, screening_payloads

    class FakeRows:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "id": 8,
                    "trade_date": date(2026, 6, 18),
                    "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
                    "strategy_version": "0.1.23",
                    "params": {"included_boards": ["main"]},
                },
                {
                    "id": 9,
                    "trade_date": date(2026, 6, 17),
                    "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
                    "strategy_version": "0.1.23",
                    "params": {
                        "included_boards": ["main"],
                        "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                    },
                },
            ]

    class FakeSession:
        def execute(self, statement):
            assert "LIMIT :param_1" in str(statement)
            return FakeRows()

    run = screening_loaders.latest_screen_run(
        FakeSession(),
        DRAGON_PULLBACK_STRATEGY_ID,
        "0.1.23",
        signal_evidence_schema_version=screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
    )

    assert run["id"] == 9


def test_screen_runs_by_date_picks_latest_matching_run_id() -> None:
    from alphaagent.server.services.quant import screening_loaders, screening_payloads

    class FakeRows:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "id": 12,
                    "trade_date": date(2026, 6, 12),
                    "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
                    "strategy_version": "0.1.23",
                    "status": "succeeded",
                    "params": {
                        "included_boards": ["chinext"],
                        "max_symbols": 5000,
                        "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                    },
                },
                {
                    "id": 11,
                    "trade_date": date(2026, 6, 12),
                    "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
                    "strategy_version": "0.1.23",
                    "status": "succeeded",
                    "params": {
                        "included_boards": ["main"],
                        "max_symbols": 5000,
                        "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                    },
                },
                {
                    "id": 10,
                    "trade_date": date(2026, 6, 12),
                    "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
                    "strategy_version": "0.1.23",
                    "status": "succeeded",
                    "params": {
                        "included_boards": ["main"],
                        "max_symbols": 3000,
                        "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                    },
                },
            ]

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            assert "FROM quant_signal_runs" in text
            assert "quant_signal_runs.trade_date IN" in text
            return FakeRows()

    runs = screening_loaders.screen_runs_by_date(
        FakeSession(),
        DRAGON_PULLBACK_STRATEGY_ID,
        "0.1.23",
        [date(2026, 6, 12)],
        signal_evidence_schema_version=screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
        max_symbols=5000,
        included_boards=("main",),
    )

    assert runs[date(2026, 6, 12)]["id"] == 11


def test_recommendations_do_not_fallback_to_stale_signal_evidence_schema(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    executed: list[str] = []

    class FakeRows:
        def __init__(self, rows=None):
            self.rows = rows or []

        def mappings(self):
            return self

        def all(self):
            return self.rows

        def scalar(self):
            return date(2026, 6, 18)

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            executed.append(text)
            return FakeRows([])

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_daily_symbol_count", lambda session, target: 4064)

    result = screening.list_recommendations(trade_date=date(2026, 6, 18))

    assert result["status"] == "empty"
    assert result["run_id"] is None
    assert result["items"] == []
    assert "刷新候选" in result["message"]
    assert not any("FROM quant_recommendations" in statement for statement in executed)


def test_recommendations_reject_explicit_incomplete_daily_date(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    trade_date = date(2026, 7, 7)

    class FakeSession:
        pass

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_daily_symbol_count", lambda session, target: 1687 if target == trade_date else 5524)
    monkeypatch.setattr(screening, "_latest_trade_date", lambda session: trade_date)
    monkeypatch.setattr(screening, "_latest_complete_trade_date", lambda session: date(2026, 7, 6))

    result = screening.list_recommendations(trade_date=trade_date)

    assert result["status"] == "incomplete_daily_data"
    assert result["trade_date"] == "2026-07-07"
    assert result["latest_complete_trade_date"] == "2026-07-06"
    assert result["items"] == []
    assert result["recommendations"] == []
    assert "14:30" in result["message"]


def test_latest_trade_plan_uses_latest_screen_run_id(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening, screening_payloads

    executed: list[str] = []

    class FakeRows:
        def __init__(self, rows=None):
            self.rows = rows or []

        def mappings(self):
            return self

        def all(self):
            return self.rows

        def first(self):
            return self.rows[0] if self.rows else None

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            executed.append(text)
            if "FROM quant_signal_runs" in text:
                return FakeRows(
                    [
                        {
                            "id": 88,
                            "trade_date": date(2026, 6, 18),
                            "strategy_id": "mainline_leader_pullback",
                            "strategy_version": "0.1.1",
                            "status": "succeeded",
                            "params": {
                                "included_boards": ["main"],
                                "max_symbols": 5000,
                                "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                            },
                        }
                    ]
                )
            assert "quant_recommendations.run_id = :run_id_1" in text
            return FakeRows(
                [
                    {
                        "id": 1,
                        "run_id": 88,
                        "trade_date": date(2026, 6, 18),
                        "vt_symbol": "003004.SZSE",
                        "strategy_id": "mainline_leader_pullback",
                        "strategy_version": "0.1.1",
                        "rank": 3,
                        "action": "BUY",
                        "horizon": "SWING",
                        "confidence": 0.8,
                        "total_score": 90,
                        "reason": {},
                        "risk_control": {"trade_plan": {"entry_price": 32.1}},
                        "status": "active",
                        "stock_name": "声迅股份",
                    }
                ]
            )

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_complete_trade_date", lambda session: date(2026, 6, 18))

    result = screening.latest_trade_plan("003004.SZSE")

    assert result["status"] == "ready"
    assert result["trade_plan"]["entry_price"] == 32.1
    assert not any(
        "quant_recommendations.vt_symbol = :vt_symbol_1" in statement
        and "quant_recommendations.run_id = :run_id_1" not in statement
        for statement in executed
    )


def test_list_screen_runs_returns_recent_runs(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    class FakeRows:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "id": 9,
                    "strategy_id": "mainline_leader_pullback",
                    "strategy_version": "0.1.1",
                    "trade_date": date(2026, 6, 12),
                    "status": "succeeded",
                    "params": {"included_boards": ["main"]},
                    "candidate_count": 300,
                    "signal_count": 12,
                    "recommendation_count": 20,
                    }
                ]

    class FakeActionRows:
        def mappings(self):
            return self

        def all(self):
            return [
                {"run_id": 9, "action": "BUY", "count": 7},
                {"run_id": 9, "action": "WATCH", "count": 13},
            ]

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if "FROM quant_signal_runs" in text:
                return FakeRows()
            assert "FROM quant_recommendations" in text
            return FakeActionRows()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_complete_trade_date", lambda session: date(2026, 6, 12))

    result = screening.list_screen_runs()

    assert result["status"] == "ready"
    assert result["items"][0]["trade_date"] == "2026-06-12"
    assert result["items"][0]["recommendation_count"] == 20
    assert result["items"][0]["buy_recommendation_count"] == 7
    assert result["items"][0]["watch_recommendation_count"] == 13


def test_list_trading_dates_returns_local_daily_bar_dates(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    class FakeRows:
        def mappings(self):
            return self

        def all(self):
            return [
                {"trade_date": date(2026, 6, 12), "symbol_count": 2},
                {"trade_date": date(2026, 6, 11), "symbol_count": 1},
            ]

    class FakeScalar:
        def __init__(self, value):
            self.value = value

        def scalar(self):
            return self.value

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if "min(stock_daily_bars.trade_date)" in text:
                return FakeScalar(date(2026, 6, 11))
            if "max(stock_daily_bars.trade_date)" in text:
                return FakeScalar(date(2026, 6, 12))
            assert "FROM stock_daily_bars" in text
            assert "GROUP BY stock_daily_bars.trade_date" in text
            assert "ORDER BY stock_daily_bars.trade_date DESC" in text
            return FakeRows()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_complete_trade_date", lambda session: date(2026, 6, 12))

    result = screening.list_trading_dates(limit=20)

    assert result["status"] == "ready"
    assert result["latest_trade_date"] == "2026-06-12"
    assert result["earliest_trade_date"] == "2026-06-11"
    assert result["returned_count"] == 2
    assert result["items"] == [
        {
            "trade_date": "2026-06-12",
            "symbol_count": 2,
            "is_complete": False,
            "min_complete_daily_symbol_count": 3000,
        },
        {
            "trade_date": "2026-06-11",
            "symbol_count": 1,
            "is_complete": False,
            "min_complete_daily_symbol_count": 3000,
        },
    ]


def test_screen_stocks_range_creates_replay_from_persisted_signals(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening
    from alphaagent.server.services.quant import strategy_replay

    calls: list[dict[str, object]] = []

    class FakeSession:
        pass

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_trade_date", lambda session: date(2026, 1, 3))
    monkeypatch.setattr(screening, "_earliest_trade_date", lambda session: date(2026, 1, 2))
    monkeypatch.setattr(screening, "_trading_dates_between", lambda session, start, end: [date(2026, 1, 2), date(2026, 1, 3)])
    monkeypatch.setattr(screening, "_screen_runs_by_date", lambda session, strategy_id, strategy_version, trade_dates, **kwargs: {})
    monkeypatch.setattr(
        screening,
        "screen_stocks",
        lambda trade_date, **kwargs: {
            "status": "ready",
            "strategy_id": "mainline_leader_pullback",
            "strategy_version": "0.1.1",
            "trade_date": trade_date.isoformat(),
            "run_id": 100 if trade_date == date(2026, 1, 2) else 101,
            "total": 1,
            "recommendation_count": 1,
            "included_boards": ["main"],
            "items": [],
            "recommendations": [],
        },
    )

    def fake_create_replay_run(**kwargs):
        calls.append(kwargs)
        return {"status": "ready", "replay_run_id": 77}

    monkeypatch.setattr(strategy_replay, "create_replay_run", fake_create_replay_run)

    result = screening.screen_stocks_range(
        date(2026, 1, 2),
        date(2026, 1, 3),
        persist=True,
        included_boards=["main"],
    )

    assert result["replay_run_id"] == 77
    assert result["replay_run"]["status"] == "ready"
    assert calls[0]["start"] == date(2026, 1, 2)
    assert calls[0]["end"] == date(2026, 1, 3)
    assert calls[0]["strategy_id"] == "mainline_dragon_pullback"
    assert calls[0]["execution_model"] == "legacy_next_open"


def test_screen_stocks_range_rejects_explicit_incomplete_daily_date(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    trade_date = date(2026, 7, 7)

    class FakeSession:
        pass

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_trading_dates_between", lambda session, start, end: [])
    monkeypatch.setattr(screening, "_daily_symbol_count", lambda session, target: 1687 if target == trade_date else 5524)
    monkeypatch.setattr(screening, "_latest_trade_date", lambda session: trade_date)
    monkeypatch.setattr(screening, "_latest_complete_trade_date", lambda session: date(2026, 7, 6))
    monkeypatch.setattr(screening, "_screen_runs_by_date", lambda session, strategy_id, strategy_version, trade_dates, **kwargs: {})

    result = screening.screen_stocks_range(
        start=trade_date,
        end=trade_date,
        persist=True,
        included_boards=["main"],
    )

    assert result["status"] == "incomplete_daily_data"
    assert result["trade_date"] == "2026-07-07"
    assert result["latest_complete_trade_date"] == "2026-07-06"
    assert result["total_dates"] == 0
    assert result["runs"] == []


def test_screen_stocks_range_keeps_candidates_when_replay_fails(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening
    from alphaagent.server.services.quant import strategy_replay

    class FakeSession:
        pass

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_trade_date", lambda session: date(2026, 1, 3))
    monkeypatch.setattr(screening, "_earliest_trade_date", lambda session: date(2026, 1, 2))
    monkeypatch.setattr(screening, "_trading_dates_between", lambda session, start, end: [date(2026, 1, 2)])
    monkeypatch.setattr(screening, "_screen_runs_by_date", lambda session, strategy_id, strategy_version, trade_dates, **kwargs: {})
    monkeypatch.setattr(
        screening,
        "screen_stocks",
        lambda trade_date, **kwargs: {
            "status": "ready",
            "strategy_id": "mainline_leader_pullback",
            "strategy_version": "0.1.1",
            "trade_date": trade_date.isoformat(),
            "run_id": 100,
            "total": 1,
            "recommendation_count": 1,
            "included_boards": ["main"],
            "items": [],
            "recommendations": [],
        },
    )
    monkeypatch.setattr(strategy_replay, "create_replay_run", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    result = screening.screen_stocks_range(
        date(2026, 1, 2),
        date(2026, 1, 3),
        persist=True,
        included_boards=["main"],
    )

    assert result["status"] == "ready"
    assert result["succeeded_count"] == 1
    assert result["replay_run_id"] is None
    assert result["replay_run"] == {"status": "failed", "message": "boom"}


def test_screen_stocks_range_uses_local_trading_dates_and_syncs_latest_only(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    calls: list[tuple[date, bool]] = []

    class FakeRows:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class FakeScalar:
        def scalar(self):
            return date(2026, 6, 12)

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if "max(stock_daily_bars.trade_date)" in text:
                return FakeScalar()
            assert "FROM stock_daily_bars" in text
            assert "GROUP BY stock_daily_bars.trade_date" in text
            assert "ORDER BY stock_daily_bars.trade_date" in text
            return FakeRows([(date(2026, 6, 10),), (date(2026, 6, 11),), (date(2026, 6, 12),)])

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    def fake_screen_stocks(trade_date, **kwargs):
        calls.append((trade_date, kwargs["auto_portfolio"]))
        return {
            "status": "ready",
            "trade_date": trade_date.isoformat(),
            "run_id": len(calls),
            "total": 100 + len(calls),
            "recommendation_count": len(calls),
            "included_boards": kwargs["included_boards"],
            "items": [{"trade_date": trade_date.isoformat()}],
            "recommendations": [{"trade_date": trade_date.isoformat()}],
            "portfolio_sync": {"synced": 1} if kwargs["auto_portfolio"] else None,
        }

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_screen_runs_by_date", lambda session, strategy_id, strategy_version, trade_dates, **kwargs: {})
    monkeypatch.setattr(screening, "screen_stocks", fake_screen_stocks)

    result = screening.screen_stocks_range(start=date(2026, 6, 10), included_boards=["main"])

    assert calls == [
        (date(2026, 6, 12), True),
        (date(2026, 6, 11), False),
        (date(2026, 6, 10), False),
    ]
    assert result["status"] == "ready"
    assert result["start_date"] == "2026-06-10"
    assert result["end_date"] == "2026-06-12"
    assert result["trade_date"] == "2026-06-12"
    assert result["total_dates"] == 3
    assert result["succeeded_count"] == 3
    assert result["range_recommendation_count"] == 6
    assert result["recommendation_count"] == 1
    assert result["portfolio_sync"] == {"synced": 1}
    assert [item["trade_date"] for item in result["runs"]] == ["2026-06-10", "2026-06-11", "2026-06-12"]


def test_screen_stocks_range_skips_existing_persisted_dates(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening
    from alphaagent.server.services.quant import screening_payloads

    generated_dates: list[date] = []
    synced_run_ids: list[int] = []

    class FakeSession:
        pass

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    existing_run = {
        "id": 44,
        "trade_date": date(2026, 6, 10),
        "candidate_count": 123,
        "recommendation_count": 7,
        "status": "succeeded",
        "params": {
            "included_boards": ["main"],
            "max_symbols": 5000,
            "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
        },
    }

    def fake_screen_stocks(trade_date, **kwargs):
        generated_dates.append(trade_date)
        return {
            "status": "ready",
            "trade_date": trade_date.isoformat(),
            "run_id": 55,
            "total": 99,
            "recommendation_count": 5,
            "included_boards": kwargs["included_boards"],
            "items": [],
            "recommendations": [],
            "portfolio_sync": {"synced": 5},
        }

    def fake_sync_existing(run_id, strategy_id, strategy_version):
        synced_run_ids.append(run_id)
        return {"synced": 7}

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_trade_date", lambda session: date(2026, 6, 11))
    monkeypatch.setattr(screening, "_earliest_trade_date", lambda session: date(2026, 6, 10))
    monkeypatch.setattr(screening, "_trading_dates_between", lambda session, start, end: [date(2026, 6, 10), date(2026, 6, 11)])
    monkeypatch.setattr(
        screening,
        "_screen_runs_by_date",
        lambda session, strategy_id, strategy_version, trade_dates, **kwargs: {date(2026, 6, 10): existing_run},
    )
    monkeypatch.setattr(screening, "screen_stocks", fake_screen_stocks)
    monkeypatch.setattr(screening, "_sync_existing_recommendations_to_portfolio", fake_sync_existing)

    result = screening.screen_stocks_range(
        start=date(2026, 6, 10),
        end=date(2026, 6, 11),
        persist=True,
        included_boards=["main"],
    )

    assert generated_dates == [date(2026, 6, 11)]
    assert synced_run_ids == []
    assert result["generated_count"] == 1
    assert result["skipped_existing_count"] == 1
    assert result["range_recommendation_count"] == 12
    assert result["runs"] == [
        {
            "trade_date": "2026-06-10",
            "status": "ready",
            "run_id": 44,
            "candidate_count": 123,
            "recommendation_count": 7,
            "skipped_existing": True,
            "force_refreshed": False,
        },
        {
            "trade_date": "2026-06-11",
            "status": "ready",
            "run_id": 55,
            "candidate_count": 99,
            "recommendation_count": 5,
            "skipped_existing": False,
            "force_refreshed": False,
        },
    ]


def test_screen_run_match_requires_current_signal_evidence_schema() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.quant import screening, screening_payloads

    current_params = {
        "included_boards": ["main"],
        "max_symbols": 5000,
        "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
    }
    stale_params = {
        "included_boards": ["main"],
        "max_symbols": 5000,
    }
    backtest_params = engine.BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, max_symbols=5000, included_boards=("main",))

    assert screening._screen_run_matches_params({"params": current_params}, max_symbols=5000, included_boards=("main",))
    assert not screening._screen_run_matches_params({"params": stale_params}, max_symbols=5000, included_boards=("main",))
    assert engine._screen_run_matches_backtest_params({"params": current_params}, backtest_params)
    assert not engine._screen_run_matches_backtest_params({"params": stale_params}, backtest_params)


def test_screen_stocks_range_force_refresh_regenerates_existing_persisted_dates(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening
    from alphaagent.server.services.quant import screening_payloads

    generated_dates: list[date] = []

    class FakeSession:
        pass

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    existing_run = {
        "id": 44,
        "trade_date": date(2026, 6, 10),
        "candidate_count": 123,
        "recommendation_count": 7,
        "status": "succeeded",
        "params": {
            "included_boards": ["main"],
            "max_symbols": 5000,
            "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
        },
    }

    def fake_screen_stocks(trade_date, **kwargs):
        generated_dates.append(trade_date)
        return {
            "status": "ready",
            "trade_date": trade_date.isoformat(),
            "run_id": 80 if trade_date == date(2026, 6, 10) else 81,
            "total": 88,
            "recommendation_count": 6,
            "included_boards": kwargs["included_boards"],
            "items": [],
            "recommendations": [],
        }

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_trade_date", lambda session: date(2026, 6, 11))
    monkeypatch.setattr(screening, "_earliest_trade_date", lambda session: date(2026, 6, 10))
    monkeypatch.setattr(screening, "_trading_dates_between", lambda session, start, end: [date(2026, 6, 10), date(2026, 6, 11)])
    monkeypatch.setattr(
        screening,
        "_screen_runs_by_date",
        lambda session, strategy_id, strategy_version, trade_dates, **kwargs: {date(2026, 6, 10): existing_run},
    )
    monkeypatch.setattr(screening, "screen_stocks", fake_screen_stocks)

    result = screening.screen_stocks_range(
        start=date(2026, 6, 10),
        end=date(2026, 6, 11),
        persist=True,
        included_boards=["main"],
        force_refresh=True,
    )

    assert generated_dates == [date(2026, 6, 11), date(2026, 6, 10)]
    assert result["generated_count"] == 2
    assert result["skipped_existing_count"] == 0
    assert result["force_refreshed_count"] == 1
    assert result["force_refresh"] is True
    assert result["runs"][0] == {
        "trade_date": "2026-06-10",
        "status": "ready",
        "run_id": 80,
        "candidate_count": 88,
        "recommendation_count": 6,
        "skipped_existing": False,
        "force_refreshed": True,
    }


def test_screen_stocks_range_skips_existing_empty_dates(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening
    from alphaagent.server.services.quant import screening_payloads

    generated_dates: list[date] = []

    class FakeSession:
        pass

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    empty_run = {
        "id": 70,
        "trade_date": date(2026, 6, 10),
        "candidate_count": 0,
        "recommendation_count": 0,
        "status": "empty",
        "params": {
            "included_boards": ["main"],
            "max_symbols": 5000,
            "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
        },
    }

    def fake_screen_stocks(trade_date, **kwargs):
        generated_dates.append(trade_date)
        return {
            "status": "ready",
            "trade_date": trade_date.isoformat(),
            "run_id": 71,
            "total": 8,
            "recommendation_count": 2,
            "included_boards": kwargs["included_boards"],
            "items": [],
            "recommendations": [],
        }

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_trade_date", lambda session: date(2026, 6, 11))
    monkeypatch.setattr(screening, "_earliest_trade_date", lambda session: date(2026, 6, 10))
    monkeypatch.setattr(screening, "_trading_dates_between", lambda session, start, end: [date(2026, 6, 10), date(2026, 6, 11)])
    monkeypatch.setattr(
        screening,
        "_screen_runs_by_date",
        lambda session, strategy_id, strategy_version, trade_dates, **kwargs: {date(2026, 6, 10): empty_run},
    )
    monkeypatch.setattr(screening, "screen_stocks", fake_screen_stocks)

    result = screening.screen_stocks_range(
        start=date(2026, 6, 10),
        end=date(2026, 6, 11),
        persist=True,
        included_boards=["main"],
    )

    assert generated_dates == [date(2026, 6, 11)]
    assert result["processed_count"] == 2
    assert result["succeeded_count"] == 1
    assert result["generated_count"] == 1
    assert result["skipped_existing_count"] == 1
    assert result["runs"][0] == {
        "trade_date": "2026-06-10",
        "status": "empty",
        "run_id": 70,
        "candidate_count": 0,
        "recommendation_count": 0,
        "skipped_existing": True,
        "force_refreshed": False,
    }


def test_screen_stocks_range_reports_progress_for_each_trading_date(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    progress_events: list[dict[str, object]] = []

    class FakeSession:
        pass

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    def fake_screen_stocks(trade_date, **kwargs):
        return {
            "status": "ready",
            "trade_date": trade_date.isoformat(),
            "run_id": int(trade_date.strftime("%d")),
            "total": 10,
            "recommendation_count": 1,
            "included_boards": kwargs["included_boards"],
            "items": [],
            "recommendations": [],
        }

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_trade_date", lambda session: date(2026, 6, 12))
    monkeypatch.setattr(screening, "_earliest_trade_date", lambda session: date(2026, 6, 10))
    monkeypatch.setattr(
        screening,
        "_trading_dates_between",
        lambda session, start, end: [date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12)],
    )
    monkeypatch.setattr(screening, "_screen_runs_by_date", lambda session, strategy_id, strategy_version, trade_dates, **kwargs: {})
    monkeypatch.setattr(screening, "screen_stocks", fake_screen_stocks)

    result = screening.screen_stocks_range(
        start=date(2026, 6, 10),
        end=date(2026, 6, 12),
        included_boards=["main"],
        progress=progress_events.append,
    )

    assert result["status"] == "ready"
    assert [event["trade_date"] for event in progress_events] == ["2026-06-12", "2026-06-11", "2026-06-10"]
    assert [event["progress_current"] for event in progress_events] == [1, 2, 3]
    assert {event["progress_total"] for event in progress_events} == {3}
    assert all(event["status"] == "ready" for event in progress_events)


def test_screen_stocks_range_processes_latest_dates_first_but_returns_ascending(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    generated_dates: list[date] = []
    progress_events: list[dict[str, object]] = []

    class FakeSession:
        pass

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    def fake_screen_stocks(trade_date, **kwargs):
        generated_dates.append(trade_date)
        return {
            "status": "ready",
            "trade_date": trade_date.isoformat(),
            "run_id": int(trade_date.strftime("%d")),
            "total": 10,
            "recommendation_count": 1,
            "included_boards": kwargs["included_boards"],
            "items": [{"trade_date": trade_date.isoformat()}],
            "recommendations": [{"trade_date": trade_date.isoformat()}],
            "portfolio_sync": {"synced": 1} if kwargs["auto_portfolio"] else None,
        }

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "_latest_trade_date", lambda session: date(2026, 6, 12))
    monkeypatch.setattr(screening, "_earliest_trade_date", lambda session: date(2026, 6, 10))
    monkeypatch.setattr(
        screening,
        "_trading_dates_between",
        lambda session, start, end: [date(2026, 6, 10), date(2026, 6, 11), date(2026, 6, 12)],
    )
    monkeypatch.setattr(screening, "_screen_runs_by_date", lambda session, strategy_id, strategy_version, trade_dates, **kwargs: {})
    monkeypatch.setattr(screening, "screen_stocks", fake_screen_stocks)

    result = screening.screen_stocks_range(
        start=date(2026, 6, 10),
        end=date(2026, 6, 12),
        included_boards=["main"],
        progress=progress_events.append,
    )

    assert generated_dates == [date(2026, 6, 12), date(2026, 6, 11), date(2026, 6, 10)]
    assert [event["trade_date"] for event in progress_events] == ["2026-06-12", "2026-06-11", "2026-06-10"]
    assert [event["progress_current"] for event in progress_events] == [1, 2, 3]
    assert [item["trade_date"] for item in result["runs"]] == ["2026-06-10", "2026-06-11", "2026-06-12"]
    assert result["trade_date"] == "2026-06-12"
    assert result["portfolio_sync"] == {"synced": 1}


def test_backtest_metric_rows_are_report_ready() -> None:
    from alphaagent.server.services.backtest import engine

    rows = engine._metric_rows(
        {
            "initial_cash": 1_000_000,
            "final_equity": 1_063_272.4,
            "total_return_pct": 6.3272,
            "win_rate": 0.6,
        }
    )

    assert rows == [
        {"key": "initial_cash", "label": "初始资金", "value": 1_000_000},
        {"key": "final_equity", "label": "期末权益", "value": 1_063_272.4},
        {"key": "total_return_pct", "label": "总收益率", "value": 6.3272},
        {"key": "win_rate", "label": "胜率", "value": 0.6},
    ]


def test_backtest_tail_entry_uses_minute_bar_near_visible_ma5() -> None:
    from datetime import datetime

    from alphaagent.server.services.backtest import engine

    dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(6)]
    symbol_bars = {
        dates[index]: engine.Bar(
            trade_date=dates[index],
            open_price=10 + index * 0.1,
            high_price=10.5 + index * 0.1,
            low_price=9.8 + index * 0.1,
            close_price=10 + index * 0.1,
        )
        for index in range(5)
    }
    execute_day = dates[5]
    daily_bar = engine.Bar(
        trade_date=execute_day,
        open_price=10.9,
        high_price=11.0,
        low_price=10.1,
        close_price=10.3,
    )
    bar_index = {"600000.SSE": {**symbol_bars, execute_day: daily_bar}}
    minute_index = {
        "600000.SSE": {
            execute_day: [
                engine.MinuteBar(
                    bar_time=datetime(2026, 1, 6, 14, 30),
                    trade_date=execute_day,
                    open_price=10.18,
                    high_price=10.22,
                    low_price=10.16,
                    close_price=10.2,
                )
            ]
        }
    }

    fill = engine._resolve_buy_fill(
        {"vt_symbol": "600000.SSE", "signal_date": dates[4]},
        execute_day,
        daily_bar,
        bar_index,
        minute_index,
        engine.BacktestParams(execution_model="tail_close_hybrid"),
    )

    assert fill["status"] == "filled"
    assert fill["mode"] == "minute_1430"
    assert fill["price"] == 10.2
    assert fill["reference_date"] == dates[4].isoformat()


def test_backtest_can_reject_when_minute_tail_entry_is_required() -> None:
    from alphaagent.server.services.backtest import engine

    execute_day = date(2026, 1, 6)
    daily_bar = engine.Bar(
        trade_date=execute_day,
        open_price=10.9,
        high_price=11.0,
        low_price=10.1,
        close_price=10.3,
    )
    bar_index = {
        "600000.SSE": {
            date(2026, 1, 1) + timedelta(days=index): engine.Bar(
                trade_date=date(2026, 1, 1) + timedelta(days=index),
                open_price=10,
                high_price=10,
                low_price=10,
                close_price=10,
            )
            for index in range(5)
        }
    }
    params = engine.BacktestParams(execution_model="strict_1430")

    fill = engine._resolve_buy_fill(
        {"vt_symbol": "600000.SSE", "signal_date": date(2026, 1, 5)},
        execute_day,
        daily_bar,
        bar_index,
        {},
        params,
    )

    # 历史日期缺 14:30 快照不再无意义拒单：改走日线收盘代理；代理价偏离 MA5 超容差时按策略拒单
    assert fill["status"] == "rejected"
    assert fill["reason"] == "tail_entry_not_triggered"
    assert fill["mode"] == "strict_1430_required"


def test_backtest_strict_1430_uses_daily_close_proxy_for_past_date_when_snapshot_missing() -> None:
    from alphaagent.server.services.backtest import engine

    execute_day = date(2026, 1, 6)
    daily_bar = engine.Bar(
        trade_date=execute_day,
        open_price=10.0,
        high_price=10.1,
        low_price=9.9,
        close_price=10.0,  # 与 MA5(=10) 距离 0%，在容差内
    )
    bar_index = {
        "600000.SSE": {
            date(2026, 1, 1) + timedelta(days=index): engine.Bar(
                trade_date=date(2026, 1, 1) + timedelta(days=index),
                open_price=10,
                high_price=10,
                low_price=10,
                close_price=10,
            )
            for index in range(5)
        }
    }
    params = engine.BacktestParams(execution_model="strict_1430")

    fill = engine._resolve_buy_fill(
        {"vt_symbol": "600000.SSE", "signal_date": date(2026, 1, 5)},
        execute_day,
        daily_bar,
        bar_index,
        {},  # 无分钟数据
        params,
    )

    # 历史日期缺 14:30 快照：用日线收盘代理成交，不再拒单
    assert fill["status"] == "filled"
    assert fill["mode"] == "daily_close_proxy"
    assert fill["price"] == 10.0
    assert fill["proxy_used"] is True


def test_backtest_strict_1430_rejects_today_pending_snapshot_with_hint() -> None:
    from alphaagent.server.services.backtest import engine

    today = date.today()
    signal_day = today - timedelta(days=1)
    daily_bar = engine.Bar(
        trade_date=today,
        open_price=10.0,
        high_price=10.1,
        low_price=9.9,
        close_price=10.0,
    )
    bar_index = {
        "600000.SSE": {
            signal_day - timedelta(days=4) + timedelta(days=index): engine.Bar(
                trade_date=signal_day - timedelta(days=4) + timedelta(days=index),
                open_price=10,
                high_price=10,
                low_price=10,
                close_price=10,
            )
            for index in range(5)
        }
    }
    params = engine.BacktestParams(execution_model="strict_1430")

    fill = engine._resolve_buy_fill(
        {"vt_symbol": "600000.SSE", "signal_date": signal_day},
        today,
        daily_bar,
        bar_index,
        {},  # 今日尚无 14:30 分钟快照
        params,
    )

    # 今天缺 14:30 快照：拒单并给出补齐提示，而非无意义拒单
    assert fill["status"] == "rejected"
    assert fill["reason"] == "missing_1430_snapshot"
    assert fill["mode"] == "today_pending_1430_snapshot"
    assert "14:30" in fill["next_action"]


def test_backtest_strict_1430_rejects_tail_condition_when_snapshot_present() -> None:
    from alphaagent.server.services.backtest import engine

    signal_day = date(2026, 1, 5)
    execute_day = date(2026, 1, 6)
    daily_bar = engine.Bar(
        trade_date=execute_day,
        open_price=10,
        high_price=12,
        low_price=9,
        close_price=12,
    )
    bar_index = {
        "600000.SSE": {
            signal_day - timedelta(days=4) + timedelta(days=index): engine.Bar(
                trade_date=signal_day - timedelta(days=4) + timedelta(days=index),
                open_price=10,
                high_price=10,
                low_price=10,
                close_price=10,
            )
            for index in range(5)
        }
    }
    minute_index = {
        "600000.SSE": {
            execute_day: [
                engine.MinuteBar(
                    bar_time=datetime(2026, 1, 6, 14, 30),
                    trade_date=execute_day,
                    open_price=12,
                    high_price=12,
                    low_price=12,
                    close_price=12,
                )
            ]
        }
    }
    params = engine.BacktestParams(execution_model="strict_1430")

    fill = engine._resolve_buy_fill(
        {"vt_symbol": "600000.SSE", "signal_date": signal_day},
        execute_day,
        daily_bar,
        bar_index,
        minute_index,
        params,
    )

    assert fill["status"] == "rejected"
    assert fill["reason"] == "tail_entry_not_triggered"
    assert fill["price_source"] == "stock_minute_bars.close_price"
    assert round(fill["ma5_distance_pct"], 6) == 20.0


def test_backtest_reason_label_keeps_new_and_legacy_execution_rejections() -> None:
    from alphaagent.server.services.backtest import engine

    assert engine.backtest_reason_label("limit_up_open_blocked") == "开盘涨停买不到"
    assert engine.backtest_reason_label("limit_down_open_blocked") == "开盘跌停卖不出"
    assert engine.backtest_reason_label("no_execute_bar") == "缺少执行日K线"
    assert engine.backtest_reason_label("limit_up_or_no_bar") == "涨停或缺少执行日K线"


def test_backtest_tail_hybrid_uses_daily_close_proxy_when_minute_missing() -> None:
    from alphaagent.server.services.backtest import engine

    signal_day = date(2026, 1, 5)
    execute_day = date(2026, 1, 6)
    bar_index = {
        "600000.SSE": {
            signal_day - timedelta(days=4) + timedelta(days=index): engine.Bar(
                trade_date=signal_day - timedelta(days=4) + timedelta(days=index),
                open_price=10,
                high_price=10,
                low_price=10,
                close_price=10,
            )
            for index in range(5)
        }
    }
    daily_bar = engine.Bar(execute_day, open_price=11, high_price=11.2, low_price=9.8, close_price=10.05)
    bar_index["600000.SSE"][execute_day] = daily_bar

    fill = engine._resolve_buy_fill(
        {"vt_symbol": "600000.SSE", "signal_date": signal_day},
        execute_day,
        daily_bar,
        bar_index,
        {},
        engine.BacktestParams(execution_model="tail_close_hybrid"),
    )

    assert fill["status"] == "filled"
    assert fill["mode"] == "daily_close_proxy"
    assert fill["price"] == 10.05
    assert fill["proxy_used"] is True


def test_strategy_replay_uses_persisted_signals_and_records_buy_signal_rejection() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams
    from alphaagent.server.services.quant import strategy_replay

    signal_date = date(2025, 12, 30)
    execute_date = date(2025, 12, 31)
    symbol = "002536.SZSE"
    signals = [
        {
            "id": 1,
            "run_id": 11,
            "trade_date": signal_date,
            "vt_symbol": symbol,
            "strategy_id": "mainline_leader_pullback",
            "strategy_version": "0.1.1",
            "signal_type": "mainline_leader_pullback",
            "total_score": 80.0,
            "risk_score": 60.0,
            "liquidity_score": 70.0,
            "entry_signal": True,
            "evidence": {"status": "ready", "ma5": 10.0, "ma5_distance_pct": 0.0},
        }
    ]
    bars_by_symbol = {
        symbol: [
            Bar(signal_date, 10.0, 10.2, 9.9, 10.0, change_pct=0.2),
            Bar(execute_date, 11.0, 11.0, 11.0, 11.0, change_pct=10.0),
        ]
    }
    params = BacktestParams(
        strategy="mainline_leader_pullback",
        start=signal_date,
        end=execute_date,
        min_entry_score=68,
        strict_entry=True,
        execution_model="strict_1430",
        minute_entry_required=False,
    )

    attempts = strategy_replay._replay_attempts(
        signals,
        bars_by_symbol,
        [signal_date, execute_date],
        {symbol: {"name": "飞龙股份"}},
        {},
        params,
    )
    api_attempts = [strategy_replay._mapping_to_api(dict(item)) for item in attempts]
    events = strategy_replay._events_from_attempts(api_attempts)

    assert len(attempts) == 1
    assert attempts[0]["signal_run_id"] == 11
    assert attempts[0]["execution_status"] == "rejected"
    assert attempts[0]["reject_reason"] == "limit_up_open_blocked"
    assert attempts[0]["raw"]["mode"] == "limit_up_open_blocked"
    assert [event["status"] for event in events] == ["signal", "rejected"]


def test_strategy_replay_passes_entry_evidence_to_exit_rules() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams
    from alphaagent.server.services.quant import strategy_replay

    signal_date = date(2025, 12, 4)
    entry_date = date(2025, 12, 5)
    stop_signal_date = date(2025, 12, 11)
    stop_execute_date = date(2025, 12, 12)
    symbol = "002208.SZSE"
    signals = [
        {
            "id": 1,
            "run_id": 11,
            "trade_date": signal_date,
            "vt_symbol": symbol,
            "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
            "strategy_version": "0.1.8",
            "signal_type": DRAGON_PULLBACK_STRATEGY_ID,
            "total_score": 84.0,
            "risk_score": 80.0,
            "liquidity_score": 80.0,
            "entry_signal": True,
            "evidence": {
                "status": "ready",
                "failed_rules": [],
                "support_price": 11.98,
                "max_drawdown_60d": -30.7,
            },
        }
    ]
    bars_by_symbol = {
        symbol: [
            Bar(signal_date, 11.3, 12.49, 11.05, 12.1, change_pct=5.2),
            Bar(entry_date, 12.0, 12.16, 11.55, 11.64, change_pct=-3.8),
            Bar(stop_signal_date, 11.8, 11.93, 11.31, 11.34, change_pct=-4.5),
            Bar(stop_execute_date, 11.35, 11.76, 11.24, 11.63, change_pct=2.6),
        ]
    }
    params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        start=signal_date,
        end=stop_execute_date,
        min_entry_score=76,
        strict_entry=True,
        execution_model="legacy_next_open",
    )

    attempts = strategy_replay._replay_attempts(
        signals,
        bars_by_symbol,
        [signal_date, entry_date, stop_signal_date, stop_execute_date],
        {symbol: {"name": "合肥城建"}},
        {},
        params,
    )

    sell_attempts = [item for item in attempts if item["side"] == "SELL"]
    assert len(sell_attempts) == 1
    assert sell_attempts[0]["signal_date"] == stop_signal_date
    assert sell_attempts[0]["execute_date"] == stop_execute_date
    assert sell_attempts[0]["raw"]["reason"] == "fragile_structure_stop"


def test_strategy_replay_ignores_raw_entry_signal_with_failed_rules() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams
    from alphaagent.server.services.quant import strategy_replay

    signal_date = date(2026, 6, 12)
    execute_date = date(2026, 6, 15)
    symbol = "600004.SSE"
    signals = [
        {
            "id": 1,
            "run_id": 11,
            "trade_date": signal_date,
            "vt_symbol": symbol,
            "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
            "strategy_version": "0.1.8",
            "signal_type": DRAGON_PULLBACK_STRATEGY_ID,
            "total_score": 80.0,
            "risk_score": 80.0,
            "liquidity_score": 80.0,
            "entry_signal": True,
            "evidence": {"status": "ready", "failed_rules": ["strong_leg"]},
        }
    ]
    bars_by_symbol = {
        symbol: [
            Bar(signal_date, 10.0, 10.2, 9.9, 10.0, change_pct=0.2),
            Bar(execute_date, 10.1, 10.3, 9.9, 10.2, change_pct=2.0),
        ]
    }
    params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        start=signal_date,
        end=execute_date,
        min_entry_score=76,
        strict_entry=True,
        execution_model="legacy_next_open",
    )

    attempts = strategy_replay._replay_attempts(
        signals,
        bars_by_symbol,
        [signal_date, execute_date],
        {symbol: {"name": "测试股"}},
        {},
        params,
    )

    assert attempts == []


def test_strategy_replay_load_signal_rows_uses_latest_screen_run_ids() -> None:
    from alphaagent.server.services.backtest.schemas import BacktestParams
    from alphaagent.server.services.quant import screening_payloads, strategy_replay

    executed: list[str] = []

    class FakeRows:
        def __init__(self, rows):
            self.rows = rows

        def mappings(self):
            return self

        def all(self):
            return self.rows

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            executed.append(text)
            if "FROM quant_signal_runs" in text:
                return FakeRows(
                    [
                        {
                            "id": 42,
                            "trade_date": date(2026, 1, 2),
                            "status": "succeeded",
                            "params": {
                                "included_boards": ["main"],
                                "max_symbols": 5000,
                                "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                            },
                        },
                        {
                            "id": 41,
                            "trade_date": date(2026, 1, 2),
                            "status": "succeeded",
                            "params": {
                                "included_boards": ["main"],
                                "max_symbols": 5000,
                                "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                            },
                        },
                    ]
                )
            assert "quant_stock_signals.run_id IN" in text
            return FakeRows(
                [
                    {
                        "id": 1,
                        "run_id": 42,
                        "trade_date": date(2026, 1, 2),
                        "vt_symbol": "600000.SSE",
                        "strategy_id": DRAGON_PULLBACK_STRATEGY_ID,
                        "strategy_version": "0.1.23",
                        "signal_type": DRAGON_PULLBACK_STRATEGY_ID,
                        "total_score": 82.0,
                        "relative_strength_score": 70.0,
                        "washout_score": 70.0,
                        "trend_quality_score": 70.0,
                        "sector_mainline_score": 60.0,
                        "financial_improvement_score": 60.0,
                        "liquidity_score": 80.0,
                        "risk_score": 80.0,
                        "entry_signal": True,
                        "risk_level": "LOW",
                        "evidence": {"status": "ready"},
                    }
                ]
            )

    params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        start=date(2026, 1, 2),
        end=date(2026, 1, 3),
        max_symbols=5000,
        included_boards=("main",),
        min_entry_score=76,
    )

    rows = strategy_replay._load_signal_rows(
        FakeSession(),
        DRAGON_PULLBACK_STRATEGY_ID,
        "0.1.23",
        date(2026, 1, 2),
        date(2026, 1, 3),
        params,
    )

    assert [row["run_id"] for row in rows] == [42]
    assert not any(
        "quant_stock_signals.trade_date >=" in statement
        or "quant_stock_signals.trade_date <=" in statement
        for statement in executed
        if "FROM quant_stock_signals" in statement
    )


def test_latest_symbol_replay_prefers_recent_run_containing_symbol(monkeypatch) -> None:
    from alphaagent.server.services.quant import strategy_replay

    calls: list[tuple[int, str]] = []

    class FakeScalar:
        def scalar_one_or_none(self):
            return 88

    class FakeRows:
        def mappings(self):
            return self

        def first(self):
            raise AssertionError("latest run fallback should not be queried when symbol run exists")

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if "JOIN strategy_replay_attempts" in text:
                return FakeScalar()
            return FakeRows()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(strategy_replay, "is_database_configured", lambda: True)
    monkeypatch.setattr(strategy_replay, "_ensure_schema", lambda: None)
    monkeypatch.setattr(strategy_replay, "session_scope", fake_session_scope)

    def fake_symbol_replay(run_id: int, vt_symbol: str):
        calls.append((run_id, vt_symbol))
        return {"status": "ready", "replay_run_id": run_id, "vt_symbol": vt_symbol}

    monkeypatch.setattr(strategy_replay, "symbol_replay", fake_symbol_replay)

    result = strategy_replay.latest_symbol_replay("002536.SZSE")

    assert result["replay_run_id"] == 88
    assert calls == [(88, "002536.SZSE")]


def test_latest_symbol_quant_state_ties_signal_candidate_to_latest_global_replay(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening_payloads, symbol_quant_state

    symbol = "002536.SZSE"
    signal_date = date(2025, 12, 30)

    class FakeResult:
        def __init__(self, rows=None, first=None):
            self._rows = rows or []
            self._first = first

        def mappings(self):
            return self

        def first(self):
            return self._first

        def all(self):
            return self._rows

        def scalar_one_or_none(self):
            return self._first

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if "FROM stocks" in text and "quant_recommendations" not in text:
                return FakeResult(first={"vt_symbol": symbol, "name": "飞龙股份", "exchange": "SZSE"})
            if "FROM stock_daily_bars" in text:
                return FakeResult(first=date(2026, 1, 5))
            if "FROM strategy_replay_runs" in text:
                return FakeResult(
                    first={
                        "id": 99,
                        "strategy_id": "mainline_leader_pullback",
                        "strategy_version": "0.1.1",
                        "start_date": signal_date,
                        "end_date": date(2026, 1, 5),
                        "status": "ready",
                        "params": {"included_boards": ["main"], "max_symbols": 5000},
                        "metrics": {"attempt_count": 0},
                        "message": None,
                    }
                )
            if "FROM quant_signal_runs" in text:
                if "quant_signal_runs.trade_date >=" in text:
                    return FakeResult(
                        rows=[
                            {
                                "id": 11,
                                "trade_date": signal_date,
                                "status": "succeeded",
                                "params": {
                                    "included_boards": ["main"],
                                    "max_symbols": 5000,
                                    "signal_evidence_schema_version": screening_payloads.SIGNAL_EVIDENCE_SCHEMA_VERSION,
                                },
                            }
                        ]
                    )
                return FakeResult(first=None)
            if "FROM quant_stock_signals" in text:
                return FakeResult(
                    rows=[
                        {
                            "id": 1,
                            "run_id": 11,
                            "trade_date": signal_date,
                            "vt_symbol": symbol,
                            "strategy_id": "mainline_leader_pullback",
                            "strategy_version": "0.1.1",
                            "signal_type": "mainline_leader_pullback",
                            "total_score": 82.0,
                            "relative_strength_score": 80.0,
                            "washout_score": 75.0,
                            "trend_quality_score": 70.0,
                            "sector_mainline_score": 76.0,
                            "financial_improvement_score": 65.0,
                            "liquidity_score": 78.0,
                            "risk_score": 72.0,
                            "entry_signal": True,
                            "risk_level": "LOW",
                            "evidence": {"status": "ready", "close_price": 29.7, "ma5_distance_pct": 0.4},
                            "source": "test",
                        }
                    ]
                )
            if "FROM quant_recommendations" in text:
                return FakeResult(
                    first={
                        "id": 7,
                        "run_id": 11,
                        "trade_date": signal_date,
                        "vt_symbol": symbol,
                        "strategy_id": "mainline_leader_pullback",
                        "strategy_version": "0.1.1",
                        "rank": 3,
                        "action": "BUY",
                        "horizon": "SWING",
                        "confidence": 0.82,
                        "total_score": 82.0,
                        "reason": {"status": "ready"},
                        "risk_control": {"trade_plan": {"entry_price": 29.7, "entry_date": signal_date.isoformat()}},
                        "status": "active",
                        "expires_at": date(2026, 1, 6),
                        "stock_name": "飞龙股份",
                    }
                )
            if "FROM strategy_replay_attempts" in text:
                return FakeResult(rows=[])
            raise AssertionError(text)

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(symbol_quant_state, "is_database_configured", lambda: True)
    monkeypatch.setattr(symbol_quant_state, "_ensure_schema", lambda: None)
    monkeypatch.setattr(symbol_quant_state, "session_scope", fake_session_scope)

    result = symbol_quant_state.latest_symbol_quant_state(symbol)

    assert result["process"]["source"] == "replay"
    assert result["process"]["replay_run_id"] == 99
    assert result["process"]["start_date"] == "2025-12-30"
    assert result["process"]["latest_available_trade_date"] == "2026-01-05"
    assert result["process"]["is_stale"] is False
    assert result["signal"]["entry_signal_count"] == 1
    assert result["candidate"]["status"] == "candidate"
    assert result["candidate"]["trade_plan"]["entry_price"] == 29.7
    assert result["replay"]["status"] == "no_attempts"
    assert result["state"]["code"] == "candidate_no_execution"
    assert "最近量化过程 2025-12-30 至 2026-01-05" in result["message"]


def test_latest_symbol_quant_state_prefers_newer_screen_over_stale_replay(monkeypatch) -> None:
    from alphaagent.server.services.quant import symbol_quant_state

    symbol = "603629.SSE"
    latest_screen_date = date(2026, 3, 30)

    class FakeResult:
        def __init__(self, rows=None, first=None):
            self._rows = rows or []
            self._first = first

        def mappings(self):
            return self

        def first(self):
            return self._first

        def all(self):
            return self._rows

        def scalar_one_or_none(self):
            return self._first

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if "FROM stocks" in text and "quant_recommendations" not in text:
                return FakeResult(first={"vt_symbol": symbol, "name": "利通电子", "exchange": "SSE"})
            if "FROM stock_daily_bars" in text:
                return FakeResult(first=date(2026, 6, 15))
            if "FROM strategy_replay_runs" in text:
                return FakeResult(
                    first={
                        "id": 2,
                        "strategy_id": "mainline_dragon_pullback",
                        "strategy_version": "0.1.0",
                        "start_date": date(2025, 12, 30),
                        "end_date": date(2026, 2, 2),
                        "status": "ready",
                        "params": {"included_boards": ["main"]},
                        "metrics": {},
                        "message": None,
                    }
                )
            if "FROM quant_signal_runs" in text:
                if "quant_signal_runs.trade_date >=" in text:
                    return FakeResult(rows=[])
                return FakeResult(
                    first={
                        "id": 1685,
                        "strategy_id": "mainline_dragon_pullback",
                        "strategy_version": "0.1.0",
                        "trade_date": latest_screen_date,
                        "status": "succeeded",
                        "candidate_count": 3200,
                        "signal_count": 28,
                        "recommendation_count": 10,
                        "params": {"included_boards": ["main"]},
                        "message": None,
                    }
                )
            if "FROM quant_stock_signals" in text:
                return FakeResult(
                    rows=[
                        {
                            "id": 12,
                            "run_id": 1685,
                            "trade_date": latest_screen_date,
                            "vt_symbol": symbol,
                            "strategy_id": "mainline_dragon_pullback",
                            "strategy_version": "0.1.0",
                            "signal_type": "mainline_dragon_pullback",
                            "total_score": 91.5,
                            "relative_strength_score": 82.0,
                            "washout_score": 88.0,
                            "trend_quality_score": 90.0,
                            "sector_mainline_score": 76.0,
                            "financial_improvement_score": 65.0,
                            "liquidity_score": 78.0,
                            "risk_score": 72.0,
                            "entry_signal": True,
                            "risk_level": "LOW",
                            "evidence": {"status": "ready", "close_price": 18.2},
                            "source": "test",
                        }
                    ]
                )
            if "FROM quant_recommendations" in text:
                return FakeResult(
                    first={
                        "id": 77,
                        "run_id": 1685,
                        "trade_date": latest_screen_date,
                        "vt_symbol": symbol,
                        "strategy_id": "mainline_dragon_pullback",
                        "strategy_version": "0.1.0",
                        "rank": 1,
                        "action": "BUY",
                        "horizon": "SWING",
                        "confidence": 0.9,
                        "total_score": 91.5,
                        "reason": {"status": "ready"},
                        "risk_control": {"trade_plan": {"entry_price": 18.2, "entry_date": latest_screen_date.isoformat()}},
                        "status": "active",
                        "expires_at": date(2026, 3, 31),
                        "stock_name": "利通电子",
                    }
                )
            raise AssertionError(text)

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(symbol_quant_state, "is_database_configured", lambda: True)
    monkeypatch.setattr(symbol_quant_state, "_ensure_schema", lambda: None)
    monkeypatch.setattr(symbol_quant_state, "session_scope", fake_session_scope)

    result = symbol_quant_state.latest_symbol_quant_state(symbol)

    assert result["process"]["source"] == "screen"
    assert result["process"]["screen_run_id"] == 1685
    assert result["process"]["end_date"] == "2026-03-30"
    assert result["process"]["latest_available_trade_date"] == "2026-06-15"
    assert result["process"]["is_stale"] is True
    assert result["replay"]["status"] == "not_generated"
    assert result["state"]["code"] == "candidate_replay_not_generated"


def test_default_backtest_does_not_buy_watch_candidate() -> None:
    from alphaagent.server.services.backtest import engine

    day1 = date(2026, 1, 1)
    day2 = date(2026, 1, 2)
    symbol = "600000.SSE"
    bars_by_symbol = {
        symbol: [
            engine.Bar(day1, 10.0, 10.1, 9.9, 10.0, volume=1_000_000, turnover=120_000_000),
            engine.Bar(day2, 10.0, 10.2, 9.8, 10.0, volume=1_000_000, turnover=120_000_000),
        ]
    }
    watch_score = SignalScore(
        vt_symbol=symbol,
        trade_date=day1,
        total_score=80,
        liquidity_score=80,
        risk_score=80,
        entry_signal=False,
        evidence={"status": "ready"},
    )
    params = engine.BacktestParams(
        start=day1,
        initial_cash=100_000,
        max_positions=1,
        max_position_pct=1.0,
        commission_rate=0.0,
        stamp_tax_rate=0.0,
        slippage_bps=0.0,
        min_entry_score=68,
        strict_entry=True,
    )

    result = engine._simulate(
        session=None,
        params=params,
        bars_by_symbol=bars_by_symbol,
        trading_days=[day1, day2],
        stock_meta={symbol: {"name": "浦发银行"}},
        score_cache={day1: [watch_score]},
        minute_index={},
    )

    assert result["trades"] == []
    assert result["orders"] == []
    assert result["equity"][-1]["cash"] == 100_000
    assert result["equity"][-1]["position_count"] == 0


def test_backtest_marks_missing_position_bar_with_last_visible_price() -> None:
    from alphaagent.server.services.backtest import engine

    day1 = date(2026, 1, 1)
    day2 = date(2026, 1, 2)
    day3 = date(2026, 1, 3)
    symbol = "600000.SSE"
    bars_by_symbol = {
        symbol: [
            engine.Bar(day1, 10.0, 10.2, 9.9, 10.0, volume=1_000_000, turnover=120_000_000),
            engine.Bar(day2, 10.0, 12.0, 9.9, 12.0, volume=1_000_000, turnover=120_000_000),
        ],
        "000001.SSE": [
            engine.Bar(day1, 20.0, 20.1, 19.9, 20.0, volume=1_000_000, turnover=120_000_000),
            engine.Bar(day2, 20.0, 20.1, 19.9, 20.0, volume=1_000_000, turnover=120_000_000),
            engine.Bar(day3, 20.0, 20.1, 19.9, 20.0, volume=1_000_000, turnover=120_000_000),
        ],
    }
    buy_score = SignalScore(
        vt_symbol=symbol,
        trade_date=day1,
        total_score=80,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready"},
    )
    params = engine.BacktestParams(
        start=day1,
        initial_cash=100_000,
        max_positions=1,
        max_position_pct=1.0,
        commission_rate=0.0,
        stamp_tax_rate=0.0,
        slippage_bps=0.0,
        min_entry_score=68,
        strict_entry=True,
    )

    result = engine._simulate(
        session=None,
        params=params,
        bars_by_symbol=bars_by_symbol,
        trading_days=[day1, day2, day3],
        stock_meta={symbol: {"name": "浦发银行"}},
        score_cache={day1: [buy_score], day2: []},
        minute_index={},
    )

    assert result["equity"][-1]["total_equity"] == 120_000
    assert result["positions"][-1]["trade_date"] == "2026-01-03"
    assert result["positions"][-1]["close_price"] == 12.0
    assert result["positions"][-1]["floating_pnl_pct"] == 20.0


def test_backtest_scoring_buy_candidate_policy_matches_strict_entry_flag() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.backtest import scoring

    day = date(2026, 1, 1)
    watch_score = SignalScore(
        vt_symbol="600000.SSE",
        trade_date=day,
        total_score=80,
        liquidity_score=80,
        risk_score=80,
        entry_signal=False,
        evidence={"status": "ready"},
    )
    buy_score = SignalScore(
        vt_symbol="000001.SZSE",
        trade_date=day,
        total_score=80,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready"},
    )

    assert scoring.is_buy_candidate(buy_score, engine.BacktestParams(strict_entry=True))
    assert not scoring.is_buy_candidate(watch_score, engine.BacktestParams(strict_entry=True))
    assert scoring.is_buy_candidate(watch_score, engine.BacktestParams(strict_entry=False))


def test_backtest_strict_entry_accepts_stealth_low_suction_threshold() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.backtest import scoring

    score = SignalScore(
        vt_symbol="002208.SZSE",
        trade_date=date(2025, 9, 24),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=74.8,
        liquidity_score=60.0,
        risk_score=63.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "setup_type": "stealth_low_suction",
            "entry_setup": "stealth_low_suction",
            "dragon_state": "LOW_SUCTION_BUILDUP",
            "failed_rules": [],
            "low_suction_days": 5,
            "low_suction_buildup_score": 100.0,
            "stealth_low_suction_score": 99.0,
            "ma_convergence_pct": 2.26,
            "volume_ratio_5d_20d": 1.42,
            "ma20_distance_pct": 1.49,
            "low_suction_launch_confirmed": True,
        },
    )

    assert scoring.is_buy_candidate(
        score,
        engine.BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            min_entry_score=76.0,
            strict_entry=True,
        ),
    )


def test_backtest_strict_entry_accepts_clean_low_liquidity_ma_support_watch() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.backtest import scoring

    score = SignalScore(
        vt_symbol="003004.SZSE",
        trade_date=date(2026, 4, 30),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=62.4,
        liquidity_score=15.0,
        risk_score=62.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "entry_setup": "support_accepted",
            "setup_type": "support_accepted",
            "dragon_state": "SUPPORT_ACCEPTED",
            "failed_rules": ["liquidity_score", "strong_leg", "pullback_too_short"],
            "low_suction_days": 4,
            "low_suction_launch_confirmed": True,
            "first_effective_lift": True,
            "ma5_distance_pct": 0.6,
            "ma10_distance_pct": 1.2,
            "ma_convergence_pct": 4.8,
            "ma5_slope_pct": 0.1,
            "close_location_in_range": 0.58,
            "volume_ratio_5d_20d": 0.92,
            "return_60d": 18.0,
        },
    )

    params = engine.BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        min_entry_score=76.0,
        strict_entry=True,
    )

    assert scoring.is_buy_candidate(score, params) is True

    rows = scoring.score_day(
        None,
        {"003004.SZSE": []},
        score.trade_date,
        params,
        score_cache={score.trade_date: [score]},
    )

    assert rows[0].evidence["default_clean_watch_entry_profile"] == "clean_low_liquidity_first_lift"
    assert rows[0].evidence["default_executable_entry_signal"] is True
    assert rows[0].evidence["signal_label"] == "低流动性低吸首启买点"


def test_backtest_strict_entry_keeps_active_support_divergence_as_research_only() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.backtest import scoring

    score = SignalScore(
        vt_symbol="002484.SZSE",
        trade_date=date(2026, 4, 24),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.2,
        liquidity_score=80.0,
        risk_score=66.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "entry_setup": "support_accepted",
            "setup_type": "support_accepted",
            "dragon_state": "SUPPORT_ACCEPTED",
            "support_type": "ma10_support",
            "failed_rules": ["reclaim_confirmation"],
            "strong_leg_score": 92.0,
            "pullback_days": 4,
            "low_suction_days": 1,
            "recent_limit_up_20d": True,
            "large_bull_count_20d": 1,
            "ma5_distance_pct": 1.4,
            "ma10_distance_pct": -0.4,
            "ma_convergence_pct": 16.0,
            "close_location_in_range": 0.52,
            "volume_ratio_5d_20d": 0.98,
            "latest_change_pct": -1.2,
            "return_60d": 34.0,
        },
    )
    params = engine.BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        min_entry_score=76.0,
        strict_entry=True,
    )

    assert scoring.is_buy_candidate(score, params) is False

    rows = scoring.score_day(
        None,
        {"002484.SZSE": []},
        score.trade_date,
        params,
        score_cache={score.trade_date: [score]},
    )

    assert rows == []


def test_backtest_strict_entry_rejects_hot_unconfirmed_after_big_run_watch() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.backtest import scoring

    score = SignalScore(
        vt_symbol="605117.SSE",
        trade_date=date(2026, 5, 18),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.0,
        liquidity_score=80.0,
        risk_score=66.0,
        entry_signal=False,
        evidence={
            "status": "ready",
            "entry_setup": "support_accepted",
            "setup_type": "support_accepted",
            "dragon_state": "SUPPORT_ACCEPTED",
            "support_type": "ma5_reclaim",
            "failed_rules": ["reclaim_confirmation"],
            "strong_leg_score": 94.0,
            "pullback_days": 4,
            "low_suction_days": 5,
            "low_suction_launch_confirmed": False,
            "recent_limit_up_20d": True,
            "large_bull_count_20d": 3,
            "ma5_distance_pct": 2.0,
            "ma10_distance_pct": 3.0,
            "ma_convergence_pct": 10.0,
            "close_location_in_range": 0.66,
            "volume_ratio_5d_20d": 1.1,
            "return_60d": 68.0,
        },
    )

    assert scoring.is_buy_candidate(
        score,
        engine.BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            min_entry_score=76.0,
            strict_entry=True,
        ),
    ) is False


def test_setup_family_filter_keeps_only_requested_family() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.backtest import scoring

    day = date(2026, 4, 1)
    low_suction_score = SignalScore(
        vt_symbol="002384.SZSE",
        trade_date=day,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 4,
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "balanced_first_lift",
        },
    )
    dragon_score = SignalScore(
        vt_symbol="603083.SSE",
        trade_date=day,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "low_suction_days": 0,
            "dragon_state": "TAIL_BUY_READY",
        },
    )

    candidates = scoring.score_day(
        session=None,
        bars_by_symbol={},
        trade_date=day,
        params=engine.BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            strict_entry=True,
            setup_family_filter="low_suction_first_lift",
        ),
        score_cache={day: [low_suction_score, dragon_score]},
    )

    assert [item.vt_symbol for item in candidates] == ["002384.SZSE"]
    assert candidates[0].evidence["setup_family"] == "low_suction_first_lift"


def test_phase_aware_selector_treats_low_suction_buildup_as_watch_only() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.backtest import scoring

    day = date(2026, 5, 29)
    buildup_score = SignalScore(
        vt_symbol="002534.SZSE",
        trade_date=day,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 5,
            "low_suction_launch_confirmed": False,
            "regime": "weak_defensive",
            "market_warning_level": 3,
            "recovery_state": "none",
        },
    )

    candidates = scoring.score_day(
        session=None,
        bars_by_symbol={},
        trade_date=day,
        params=engine.BacktestParams(
            strategy=DRAGON_PULLBACK_STRATEGY_ID,
            strict_entry=True,
            enable_phase_aware_setup_selector=True,
        ),
        score_cache={day: [buildup_score]},
    )

    assert candidates == []
    decision = scoring.phase_aware_setup_selector_decision(
        {
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 5,
            "low_suction_launch_confirmed": False,
            "regime": "weak_defensive",
            "market_warning_level": 3,
            "recovery_state": "none",
        }
    )
    assert decision["allowed"] is False
    assert decision["setup_family"] == "low_suction_buildup"
    assert decision["phase"] == "retreat"


def test_phase_strategy_experiment_params_excluded_from_product_baseline() -> None:
    from alphaagent.server.services.backtest.baseline_policy import is_product_baseline_params

    assert not is_product_baseline_params({"setup_family_filter": "dragon_pullback"})
    assert not is_product_baseline_params({"enable_phase_aware_setup_selector": True})
    assert not is_product_baseline_params({"enable_low_suction_pullback_entry": True})


def test_low_suction_pullback_entry_params_round_trip_and_exclude_baseline() -> None:
    from alphaagent.server.api.backtests import _params_from_payload
    from alphaagent.server.services.backtest.engine import _params_from_run, _params_to_json
    from alphaagent.server.services.backtest.baseline_policy import is_product_baseline_params
    from alphaagent.server.services.quant.strategy_replay import _params_to_json as replay_params_to_json

    params = _params_from_payload(
        {
            "enable_low_suction_pullback_entry": True,
            "low_suction_pullback_entry_max_wait_days": 4,
            "low_suction_pullback_entry_buffer_pct": 0.02,
            "low_suction_pullback_entry_reserve_slot": False,
            "enable_low_suction_trigger_day_confirmation": True,
            "enable_low_suction_confirmed_branch_exit": True,
            "low_suction_failed_follow_d3_low_pct": -7.5,
            "low_suction_failed_follow_d3_high_pct": 2.5,
            "low_suction_failed_follow_d3_close_pct": -2.8,
            "low_suction_opened_space_d5_high_pct": 6.5,
            "low_suction_opened_space_d5_low_pct": -4.5,
        }
    )
    payload = _params_to_json(params)
    replay_payload = replay_params_to_json(params)
    reloaded = _params_from_run({"params": payload, "strategy_id": DRAGON_PULLBACK_STRATEGY_ID})

    assert params.enable_low_suction_pullback_entry is True
    assert params.low_suction_pullback_entry_max_wait_days == 4
    assert params.low_suction_pullback_entry_buffer_pct == 0.02
    assert params.low_suction_pullback_entry_reserve_slot is False
    assert params.enable_low_suction_trigger_day_confirmation is True
    assert params.enable_low_suction_confirmed_branch_exit is True
    assert params.low_suction_failed_follow_d3_low_pct == -7.5
    assert params.low_suction_failed_follow_d3_high_pct == 2.5
    assert params.low_suction_failed_follow_d3_close_pct == -2.8
    assert params.low_suction_opened_space_d5_high_pct == 6.5
    assert params.low_suction_opened_space_d5_low_pct == -4.5
    assert payload["enable_low_suction_pullback_entry"] is True
    assert payload["low_suction_pullback_entry_reserve_slot"] is False
    assert payload["enable_low_suction_trigger_day_confirmation"] is True
    assert payload["enable_low_suction_confirmed_branch_exit"] is True
    assert replay_payload["enable_low_suction_pullback_entry"] is True
    assert replay_payload["low_suction_pullback_entry_reserve_slot"] is False
    assert replay_payload["enable_low_suction_trigger_day_confirmation"] is True
    assert replay_payload["enable_low_suction_confirmed_branch_exit"] is True
    assert reloaded.enable_low_suction_pullback_entry is True
    assert reloaded.low_suction_pullback_entry_max_wait_days == 4
    assert reloaded.low_suction_pullback_entry_buffer_pct == 0.02
    assert reloaded.low_suction_pullback_entry_reserve_slot is False
    assert reloaded.enable_low_suction_trigger_day_confirmation is True
    assert reloaded.enable_low_suction_confirmed_branch_exit is True
    assert reloaded.low_suction_failed_follow_d3_low_pct == -7.5
    assert reloaded.low_suction_failed_follow_d3_high_pct == 2.5
    assert reloaded.low_suction_failed_follow_d3_close_pct == -2.8
    assert reloaded.low_suction_opened_space_d5_high_pct == 6.5
    assert reloaded.low_suction_opened_space_d5_low_pct == -4.5
    assert is_product_baseline_params(payload) is False


def test_low_suction_pullback_entry_plan_only_targets_clean_first_lift() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.backtest import simulation

    signal_day = date(2026, 4, 1)
    execute_day = date(2026, 4, 2)
    params = engine.BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        enable_low_suction_pullback_entry=True,
        low_suction_pullback_entry_buffer_pct=0.01,
    )
    clean_reason = {
        "entry_setup": "stealth_low_suction",
        "low_suction_days": 4,
        "low_suction_launch_confirmed": True,
        "low_suction_launch_quality_bucket": "balanced_first_lift",
        "ma10": 10.0,
    }
    high_close_reason = {
        **clean_reason,
        "low_suction_launch_quality_bucket": "high_close_launch",
    }

    clean_plan = simulation.low_suction_pullback_entry_plan(clean_reason, signal_day, execute_day, params)
    high_close_plan = simulation.low_suction_pullback_entry_plan(high_close_reason, signal_day, execute_day, params)

    assert clean_plan is not None
    assert clean_plan["entry_execution_mode"] == "low_suction_pullback_entry"
    assert clean_plan["pullback_entry_target"] == 10.1
    assert clean_plan["pullback_entry_source"] == "ma10"
    assert high_close_plan is None


def test_low_suction_pullback_entry_waits_then_fills_on_ma10_touch() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.backtest import simulation

    signal_day = date(2026, 4, 1)
    d1 = date(2026, 4, 2)
    d2 = date(2026, 4, 3)
    params = engine.BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        enable_low_suction_pullback_entry=True,
        low_suction_pullback_entry_max_wait_days=3,
        low_suction_pullback_entry_buffer_pct=0.01,
    )
    score = SignalScore(
        "002384.SZSE",
        signal_day,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 4,
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "balanced_first_lift",
            "ma10": 10.0,
        },
    )
    plan = simulation.entry_plan_for_candidate(score, signal_day, d1, None, params)

    wait = simulation.low_suction_pullback_entry_decision(plan, d1, engine.Bar(d1, 10.5, 10.8, 10.3, 10.6))
    fill = simulation.low_suction_pullback_entry_decision(plan, d2, engine.Bar(d2, 10.4, 10.6, 10.05, 10.2))

    assert wait["status"] == "waiting"
    assert wait["wait_count"] == 1
    assert fill["status"] == "filled"
    assert fill["price"] == 10.1
    assert fill["price_source"] == "stock_daily_bars.low_touch_limit_proxy"
    assert fill["proxy_used"] is True
    assert fill["wait_count"] == 2


def test_low_suction_pullback_entry_expires_without_buy_when_target_not_touched() -> None:
    from alphaagent.server.services.backtest import engine

    d0 = date(2026, 4, 1)
    d1 = date(2026, 4, 2)
    d2 = date(2026, 4, 3)
    symbol = "002384.SZSE"
    bars_by_symbol = {
        symbol: [
            engine.Bar(d0, 10.8, 11.0, 10.6, 10.8, volume=1_000_000, turnover=120_000_000),
            engine.Bar(d1, 10.9, 11.1, 10.6, 11.0, volume=1_000_000, turnover=120_000_000),
            engine.Bar(d2, 11.0, 11.2, 10.7, 11.1, volume=1_000_000, turnover=120_000_000),
        ],
    }
    score = SignalScore(
        symbol,
        d0,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 4,
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "balanced_first_lift",
            "ma10": 10.0,
        },
    )
    params = engine.BacktestParams(
        start=d0,
        initial_cash=100_000,
        max_positions=1,
        max_position_pct=1.0,
        commission_rate=0.0,
        stamp_tax_rate=0.0,
        slippage_bps=0.0,
        min_entry_score=76,
        strict_entry=True,
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        enable_low_suction_pullback_entry=True,
        low_suction_pullback_entry_max_wait_days=2,
    )

    result = engine._simulate(
        session=None,
        params=params,
        bars_by_symbol=bars_by_symbol,
        trading_days=[d0, d1, d2],
        stock_meta={symbol: {"name": "东山精密"}},
        score_cache={d0: [score]},
        minute_index={},
    )

    assert result["trades"] == []
    rejected = [order for order in result["orders"] if order["status"] == "rejected"]
    assert rejected[-1]["reason"] == "low_suction_pullback_entry_expired"
    assert rejected[-1]["raw"]["reason"] == "pullback_target_not_touched"


def test_low_suction_pullback_entry_can_wait_without_reserving_slot() -> None:
    from alphaagent.server.services.backtest import engine

    d0 = date(2026, 4, 1)
    d1 = date(2026, 4, 2)
    d2 = date(2026, 4, 3)
    low_symbol = "002384.SZSE"
    dragon_symbol = "603629.SSE"
    bars_by_symbol = {
        low_symbol: [
            engine.Bar(d0, 10.8, 11.0, 10.6, 10.8, volume=1_000_000, turnover=120_000_000),
            engine.Bar(d1, 10.9, 11.1, 10.6, 11.0, volume=1_000_000, turnover=120_000_000),
            engine.Bar(d2, 10.5, 10.7, 10.05, 10.2, volume=1_000_000, turnover=120_000_000),
        ],
        dragon_symbol: [
            engine.Bar(d0, 20.0, 20.5, 19.8, 20.2, volume=1_000_000, turnover=120_000_000),
            engine.Bar(d1, 20.2, 20.8, 20.0, 20.5, volume=1_000_000, turnover=120_000_000),
            engine.Bar(d2, 20.5, 21.0, 20.2, 20.8, volume=1_000_000, turnover=120_000_000),
        ],
    }
    low_score = SignalScore(
        low_symbol,
        d0,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=99,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 4,
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "balanced_first_lift",
            "ma10": 10.0,
        },
    )
    dragon_score = SignalScore(
        dragon_symbol,
        d0,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=98,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "entry_setup": "dragon_pullback", "dragon_state": "TAIL_BUY_READY"},
    )
    params = engine.BacktestParams(
        start=d0,
        initial_cash=100_000,
        max_positions=2,
        max_position_pct=0.5,
        commission_rate=0.0,
        stamp_tax_rate=0.0,
        slippage_bps=0.0,
        min_entry_score=76,
        strict_entry=True,
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        enable_low_suction_pullback_entry=True,
        low_suction_pullback_entry_reserve_slot=False,
        low_suction_pullback_entry_max_wait_days=3,
    )

    result = engine._simulate(
        session=None,
        params=params,
        bars_by_symbol=bars_by_symbol,
        trading_days=[d0, d1, d2],
        stock_meta={low_symbol: {"name": "东山精密"}, dragon_symbol: {"name": "三维股份"}},
        score_cache={d0: [low_score, dragon_score]},
        minute_index={},
    )

    buys = [trade for trade in result["trades"] if trade["side"] == "BUY"]
    assert [trade["vt_symbol"] for trade in buys] == [dragon_symbol, low_symbol]
    assert buys[0]["trade_date"] == d1.isoformat()
    assert buys[0]["raw"]["execution"]["mode"] == "daily_next_open"
    assert buys[1]["trade_date"] == d2.isoformat()
    assert buys[1]["raw"]["execution"]["mode"] == "low_suction_pullback_entry"


def test_low_suction_trigger_day_confirmation_executes_next_open() -> None:
    from alphaagent.server.services.backtest import engine

    d0 = date(2026, 4, 1)
    d1 = date(2026, 4, 2)
    d2 = date(2026, 4, 3)
    symbol = "002384.SZSE"
    bars_by_symbol = {
        symbol: [
            engine.Bar(d0, 10.8, 11.0, 10.6, 10.8, volume=1_000_000, turnover=120_000_000),
            engine.Bar(d1, 10.0, 10.6, 9.95, 10.3, volume=1_100_000, turnover=120_000_000),
            engine.Bar(d2, 10.4, 10.8, 10.3, 10.7, volume=1_200_000, turnover=120_000_000),
        ],
    }
    score = SignalScore(
        symbol,
        d0,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 4,
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "balanced_first_lift",
            "ma10": 10.0,
            "volume5": 1_000_000,
        },
    )
    params = engine.BacktestParams(
        start=d0,
        initial_cash=100_000,
        max_positions=1,
        max_position_pct=1.0,
        commission_rate=0.0,
        stamp_tax_rate=0.0,
        slippage_bps=0.0,
        min_entry_score=76,
        strict_entry=True,
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        enable_low_suction_pullback_entry=True,
        low_suction_pullback_entry_reserve_slot=False,
        enable_low_suction_trigger_day_confirmation=True,
        low_suction_pullback_entry_max_wait_days=3,
    )

    result = engine._simulate(
        session=None,
        params=params,
        bars_by_symbol=bars_by_symbol,
        trading_days=[d0, d1, d2],
        stock_meta={symbol: {"name": "东山精密"}},
        score_cache={d0: [score]},
        minute_index={},
    )

    buys = [trade for trade in result["trades"] if trade["side"] == "BUY"]
    assert len(buys) == 1
    assert buys[0]["trade_date"] == d2.isoformat()
    assert buys[0]["price"] == 10.4
    execution = buys[0]["raw"]["execution"]
    assert execution["mode"] == "low_suction_trigger_day_confirmed_next_open"
    assert execution["trigger_day_confirmation"]["trigger_date"] == d1.isoformat()
    assert execution["trigger_day_confirmation"]["confirmed"] is True


def test_low_suction_trigger_day_confirmation_rejects_weak_trigger_day() -> None:
    from alphaagent.server.services.backtest import engine

    d0 = date(2026, 4, 1)
    d1 = date(2026, 4, 2)
    d2 = date(2026, 4, 3)
    symbol = "002384.SZSE"
    bars_by_symbol = {
        symbol: [
            engine.Bar(d0, 10.8, 11.0, 10.6, 10.8, volume=1_000_000, turnover=120_000_000),
            engine.Bar(d1, 10.0, 10.3, 9.95, 10.05, volume=700_000, turnover=120_000_000),
            engine.Bar(d2, 10.4, 10.8, 10.3, 10.7, volume=1_200_000, turnover=120_000_000),
        ],
    }
    score = SignalScore(
        symbol,
        d0,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 4,
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "balanced_first_lift",
            "ma10": 10.0,
            "volume5": 1_000_000,
        },
    )
    params = engine.BacktestParams(
        start=d0,
        initial_cash=100_000,
        max_positions=1,
        max_position_pct=1.0,
        commission_rate=0.0,
        stamp_tax_rate=0.0,
        slippage_bps=0.0,
        min_entry_score=76,
        strict_entry=True,
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        enable_low_suction_pullback_entry=True,
        low_suction_pullback_entry_reserve_slot=False,
        enable_low_suction_trigger_day_confirmation=True,
        low_suction_pullback_entry_max_wait_days=3,
    )

    result = engine._simulate(
        session=None,
        params=params,
        bars_by_symbol=bars_by_symbol,
        trading_days=[d0, d1, d2],
        stock_meta={symbol: {"name": "东山精密"}},
        score_cache={d0: [score]},
        minute_index={},
    )

    assert result["trades"] == []
    rejected = [order for order in result["orders"] if order["status"] == "rejected"]
    assert rejected[-1]["reason"] == "low_suction_trigger_day_confirmation_failed"
    assert rejected[-1]["raw"]["trigger_volume_ge_signal_volume5"] is False


def test_support_stop_reentry_signal_requires_visible_ma5_reclaim_shape() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.backtest import simulation

    start = date(2026, 5, 1)
    closes = [10.0] * 20 + [9.8, 9.6, 9.4, 9.2, 9.5]
    bars = [
        engine.Bar(
            start + timedelta(days=index),
            close * 0.995,
            close * 1.01,
            close * 0.97,
            close,
            volume=1_000_000,
            turnover=100_000_000,
            change_pct=0.2,
        )
        for index, close in enumerate(closes)
    ]
    watch = {
        "support_stop_execute_date": bars[-2].trade_date,
        "checked_days": 0,
    }

    signal = simulation.support_stop_reentry_signal(
        bars,
        bars[-1].trade_date,
        watch,
        engine.BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID),
    )

    assert signal["status"] == "matched"
    assert signal["reason"] == "visible_ma5_reclaim_normal_volume"
    assert signal["reentry_reclaimed_ma5"] is True
    assert 0.55 <= signal["reentry_close_location"] <= 1.0
    assert 0.80 <= signal["reentry_volume_ratio_5d_20d"] <= 1.15


def test_support_stop_reentry_signal_rejects_overheated_volume() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.backtest import simulation

    start = date(2026, 5, 1)
    closes = [10.0] * 20 + [9.8, 9.6, 9.4, 9.2, 9.5]
    bars = []
    for index, close in enumerate(closes):
        volume = 2_500_000 if index >= len(closes) - 5 else 1_000_000
        bars.append(
            engine.Bar(
                start + timedelta(days=index),
                close * 0.995,
                close * 1.01,
                close * 0.97,
                close,
                volume=volume,
                turnover=100_000_000,
                change_pct=0.2,
            )
        )
    watch = {
        "support_stop_execute_date": bars[-2].trade_date,
        "checked_days": 0,
    }

    signal = simulation.support_stop_reentry_signal(
        bars,
        bars[-1].trade_date,
        watch,
        engine.BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID),
    )

    assert signal["status"] == "waiting"
    assert signal["reason"] == "volume_ratio_out_of_range"
    assert signal["reentry_volume_ratio_5d_20d"] > 1.15


def test_support_stop_reentry_after_support_stop_generates_candidate_snapshot_without_real_buy() -> None:
    from alphaagent.server.services.backtest import engine

    symbol = "002208.SZSE"
    start = date(2026, 5, 1)
    trading_days = [start + timedelta(days=index) for index in range(27)]
    bars = []
    for index, day in enumerate(trading_days):
        if index == 0:
            close = 10.0
        elif index == 1:
            close = 10.0
        elif index == 23:
            close = 8.8
        elif index == 24:
            close = 8.8
        elif index == 25:
            close = 9.1
        elif index == 26:
            close = 9.2
        else:
            close = 9.4
        bars.append(
            engine.Bar(
                trade_date=day,
                open_price=close,
                high_price=close * 1.01,
                low_price=close * 0.97,
                close_price=close,
                volume=1_000_000,
                turnover=100_000_000,
                change_pct=0.2,
            )
        )
    candidate = SignalScore(
        vt_symbol=symbol,
        trade_date=trading_days[0],
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "support_price": 9.5,
            "ma10": 9.5,
        },
    )
    params = engine.BacktestParams(
        start=trading_days[0],
        end=trading_days[-1],
        initial_cash=100_000,
        max_positions=1,
        max_position_pct=1.0,
        commission_rate=0.0,
        stamp_tax_rate=0.0,
        slippage_bps=0.0,
        stop_loss_pct=0.5,
        time_stop_days=999,
        min_entry_score=76,
        strict_entry=True,
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        execution_model="legacy_next_open",
    )

    result = engine._simulate(
        None,
        params,
        {symbol: bars},
        trading_days,
        {symbol: {"name": "测试股"}},
        score_cache={trading_days[0]: [candidate]},
        minute_index={},
        score_context=engine.ScoreContext(),
    )

    sells = [trade for trade in result["trades"] if trade["side"] == "SELL"]
    buys = [trade for trade in result["trades"] if trade["side"] == "BUY"]
    snapshots = [
        row
        for row in result["candidate_snapshots"]
        if (row.get("payload") or {}).get("candidate_source") == "support_stop_reentry"
    ]

    assert sells[0]["reason"] == "support_stop"
    assert len(buys) == 1
    assert not any((trade.get("raw") or {}).get("candidate_source") == "support_stop_reentry" for trade in buys)
    assert not any((event.get("raw") or {}).get("candidate_source") == "support_stop_reentry" for event in result["signal_events"])
    assert len(snapshots) == 1
    payload = snapshots[0]["payload"]
    assert snapshots[0]["rank"] == 1001
    assert payload["action"] == "BUY"
    assert payload["candidate_execution"]["execution_candidate_rank"] == 1
    assert payload["candidate_execution"]["execution_candidate_selected"] is True
    assert payload["reason"]["entry_execution_mode"] == "support_stop_ma5_reentry_next_open"


def test_support_stop_reentry_snapshot_is_excluded_from_main_candidate_quality_scope() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.backtest.factor_audit import build_daily_candidate_clusters

    payload = {
        "trade_date": date(2026, 5, 26),
        "vt_symbol": "002208.SZSE",
        "rank": 1001,
        "action": "BUY",
        "total_score": 88.0,
        "reason": {"entry_setup": "support_stop_reentry", "support_stop_reentry": True},
        "candidate_source": "support_stop_reentry",
        "candidate_execution": {
            "execution_lane": "support_stop_reentry",
            "raw_signal_rank": 1001,
            "execution_candidate_rank": 1,
            "execution_candidate_selected": True,
            "execution_candidate_limit": 20,
        },
    }

    clusters = build_daily_candidate_clusters([payload])
    in_scope = engine._candidate_quality_cluster_in_scope(
        clusters[0].entry_row,
        20,
        {"params": {"candidate_limit": 20}},
    )

    assert len(clusters) == 1
    assert in_scope is False
    assert clusters[0].entry_row["rank"] == 1001
    assert clusters[0].entry_row["candidate_execution"]["execution_candidate_rank"] == 1


def test_loose_research_mode_can_buy_watch_candidate_explicitly() -> None:
    from alphaagent.server.services.backtest import engine

    day1 = date(2026, 1, 1)
    day2 = date(2026, 1, 2)
    symbol = "600000.SSE"
    bars_by_symbol = {
        symbol: [
            engine.Bar(day1, 10.0, 10.1, 9.9, 10.0, volume=1_000_000, turnover=120_000_000),
            engine.Bar(day2, 10.0, 10.2, 9.8, 10.0, volume=1_000_000, turnover=120_000_000),
        ]
    }
    watch_score = SignalScore(
        vt_symbol=symbol,
        trade_date=day1,
        total_score=80,
        liquidity_score=80,
        risk_score=80,
        entry_signal=False,
        evidence={"status": "ready"},
    )
    params = engine.BacktestParams(
        start=day1,
        initial_cash=100_000,
        max_positions=1,
        max_position_pct=1.0,
        commission_rate=0.0,
        stamp_tax_rate=0.0,
        slippage_bps=0.0,
        min_entry_score=68,
        strict_entry=False,
        execution_model="tail_close_hybrid",
    )

    result = engine._simulate(
        session=None,
        params=params,
        bars_by_symbol=bars_by_symbol,
        trading_days=[day1, day2],
        stock_meta={symbol: {"name": "浦发银行"}},
        score_cache={day1: [watch_score]},
        minute_index={},
    )

    assert len(result["trades"]) == 1
    assert result["trades"][0]["side"] == "BUY"
    assert result["trades"][0]["vt_symbol"] == symbol


def test_signal_events_use_independent_symbol_state_machine() -> None:
    from alphaagent.server.services.backtest import engine

    symbol = "600000.SSE"
    signal_day = date(2026, 1, 5)
    execute_day = date(2026, 1, 6)
    sell_day = date(2026, 1, 10)
    bar_index = {
        symbol: {
            signal_day: engine.Bar(signal_day, 10, 10.5, 9.8, 10.0),
            execute_day: engine.Bar(execute_day, 10, 10.5, 9.8, 10.05),
            sell_day + timedelta(days=1): engine.Bar(sell_day + timedelta(days=1), 8.6, 8.9, 8.4, 8.5),
        }
    }
    today_bars = {
        symbol: engine.Bar(sell_day, 8.8, 9.0, 8.6, 8.7),
    }
    score = SignalScore(
        vt_symbol=symbol,
        trade_date=signal_day,
        signal_type="mainline_leader_pullback",
        total_score=80,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "ma5_distance_pct": 0.0},
    )
    params = engine.BacktestParams(
        strategy="mainline_leader_pullback",
        stop_loss_pct=0.07,
        execution_model="tail_close_hybrid",
    )
    positions: dict[str, engine.Position] = {}

    buys = engine._signal_events_for_day(signal_day, execute_day, [score], positions, {}, bar_index, {}, {symbol: {"name": "浦发银行"}}, params)
    duplicate = engine._signal_events_for_day(signal_day + timedelta(days=1), sell_day, [score], positions, {}, bar_index, {}, {}, params)
    sells = engine._signal_events_for_day(sell_day, sell_day + timedelta(days=1), [], positions, today_bars, bar_index, {}, {}, params)

    assert [row["side"] for row in buys] == ["BUY"]
    assert buys[0]["price"] == 10.05
    assert buys[0]["raw"]["mode"] == "daily_close_proxy"
    assert duplicate == []
    assert [row["side"] for row in sells] == ["SELL"]
    assert sells[0]["reason"] == "stop_loss"
    assert sells[0]["trade_date"] == sell_day + timedelta(days=1)
    assert sells[0]["execute_date"] == sell_day + timedelta(days=1)
    assert sells[0]["raw"]["signal_date"] == sell_day.isoformat()
    assert sells[0]["price"] == 8.5
    assert sells[0]["raw"]["mode"] == "daily_close_proxy_sell"


def test_signal_events_keep_rejected_theoretical_buy_for_audit() -> None:
    from alphaagent.server.services.backtest import engine

    symbol = "600000.SSE"
    signal_day = date(2026, 1, 5)
    execute_day = date(2026, 1, 6)
    bar_index = {
        symbol: {
            signal_day - timedelta(days=4) + timedelta(days=index): engine.Bar(
                trade_date=signal_day - timedelta(days=4) + timedelta(days=index),
                open_price=10,
                high_price=10,
                low_price=10,
                close_price=10,
            )
            for index in range(5)
        }
    }
    bar_index[symbol][execute_day] = engine.Bar(
        trade_date=execute_day,
        open_price=11,
        high_price=11,
        low_price=10.8,
        close_price=11,
    )
    score = SignalScore(
        vt_symbol=symbol,
        trade_date=signal_day,
        total_score=80,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready"},
    )
    params = engine.BacktestParams(execution_model="strict_1430")
    positions: dict[str, engine.Position] = {}

    events = engine._signal_events_for_day(
        signal_day,
        execute_day,
        [score],
        positions,
        {},
        bar_index,
        {},
        {symbol: {"name": "浦发银行"}},
        params,
    )

    assert len(events) == 1
    assert events[0]["side"] == "BUY"
    assert events[0]["price"] is None
    assert events[0]["reason"] == "entry_signal"
    # 历史日期缺 14:30 快照走日线收盘代理；代理价偏离 MA5 超容差按策略拒单，事件保留审计
    assert events[0]["raw"]["status"] == "rejected"
    assert events[0]["raw"]["reason"] == "tail_entry_not_triggered"
    assert events[0]["raw"]["mode"] == "strict_1430_required"
    assert positions == {}


def test_signal_events_skip_buy_candidate_outside_execution_pool() -> None:
    from alphaagent.server.services.backtest import engine

    signal_day = date(2026, 1, 5)
    execute_day = date(2026, 1, 6)
    selected_symbol = "600000.SSE"
    skipped_symbol = "003004.SZSE"
    bar_index = {
        selected_symbol: {
            signal_day: engine.Bar(signal_day, 10, 10.5, 9.8, 10.2),
            execute_day: engine.Bar(execute_day, 10.1, 10.6, 10.0, 10.5),
        },
        skipped_symbol: {
            signal_day: engine.Bar(signal_day, 32, 33, 31, 32.4),
            execute_day: engine.Bar(execute_day, 32.5, 33.2, 32.1, 33.0),
        },
    }
    selected = SignalScore(
        vt_symbol=selected_symbol,
        trade_date=signal_day,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=95,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "entry_setup": "dragon_pullback"},
    )
    skipped = SignalScore(
        vt_symbol=skipped_symbol,
        trade_date=signal_day,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=70,
        liquidity_score=15,
        risk_score=80,
        entry_signal=False,
        evidence={
            "status": "ready",
            "entry_setup": "support_accepted",
            "default_clean_watch_entry_profile": "clean_low_liquidity_accumulation",
            "default_executable_entry_signal": True,
            "executable_entry_signal": True,
            "failed_rules": ["liquidity_score", "strong_leg"],
        },
    )
    params = engine.BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        candidate_limit=1,
        strict_entry=True,
    )
    positions: dict[str, engine.Position] = {}

    events = engine._signal_events_for_day(
        signal_day,
        execute_day,
        [selected, skipped],
        positions,
        {},
        bar_index,
        {},
        {
            selected_symbol: {"name": "浦发银行"},
            skipped_symbol: {"name": "声迅股份"},
        },
        params,
    )

    assert [event["vt_symbol"] for event in events] == [selected_symbol]
    assert skipped_symbol not in positions
    assert events[0]["raw"]["candidate_execution"]["execution_candidate_selected"] is True


def test_signal_events_skip_research_only_buy_markers() -> None:
    from alphaagent.server.services.backtest import engine

    symbol = "003004.SZSE"
    signal_day = date(2026, 5, 25)
    execute_day = date(2026, 5, 26)
    bar_index = {
        symbol: {
            signal_day: engine.Bar(signal_day, 50, 51, 47.2, 49.76),
            execute_day: engine.Bar(execute_day, 50, 51, 49, 50),
        }
    }
    score = SignalScore(
        vt_symbol=symbol,
        trade_date=signal_day,
        total_score=78.49,
        liquidity_score=80,
        risk_score=80,
        entry_signal=False,
        evidence={
            "status": "ready",
            "strong_trend_ma_pullback_entry_profile": "strong_trend_intraday_ma_pullback",
            "strong_trend_ma_pullback_entry_observation_only": True,
            "default_executable_entry_signal": False,
            "raw_entry_signal": False,
        },
    )
    params = engine.BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        enable_strong_trend_ma_pullback_entry_lane=True,
    )
    positions: dict[str, engine.Position] = {}

    events = engine._signal_events_for_day(
        signal_day,
        execute_day,
        [score],
        positions,
        {},
        bar_index,
        {},
        {symbol: {"name": "声迅股份"}},
        params,
    )

    assert events == []
    assert positions == {}


def test_backtest_simulation_records_deterministic_cash_position_and_slot_rejection() -> None:
    from alphaagent.server.services.backtest import engine

    day1 = date(2026, 1, 1)
    day2 = date(2026, 1, 2)
    symbol_a = "600000.SSE"
    symbol_b = "000001.SZSE"
    bars_by_symbol = {
        symbol_a: [
            engine.Bar(day1, 10.0, 10.2, 9.8, 10.0, volume=1_000_000, turnover=120_000_000),
            engine.Bar(day2, 10.0, 10.4, 9.9, 10.2, volume=1_000_000, turnover=120_000_000),
        ],
        symbol_b: [
            engine.Bar(day1, 20.0, 20.3, 19.8, 20.0, volume=1_000_000, turnover=120_000_000),
            engine.Bar(day2, 22.0, 22.0, 21.8, 22.0, volume=1_000_000, turnover=120_000_000, change_pct=10.0),
        ],
    }
    score_cache = {
        day1: [
            SignalScore(symbol_a, day1, total_score=80, liquidity_score=80, risk_score=80, entry_signal=True, evidence={"status": "ready"}),
            SignalScore(symbol_b, day1, total_score=79, liquidity_score=80, risk_score=80, entry_signal=True, evidence={"status": "ready"}),
        ],
    }
    minute_index = {
        symbol_a: {
            day2: [
                engine.MinuteBar(
                    bar_time=datetime(2026, 1, 2, 14, 30),
                    trade_date=day2,
                    open_price=10.0,
                    high_price=10.1,
                    low_price=9.9,
                    close_price=10.0,
                )
            ]
        }
    }
    params = engine.BacktestParams(
        start=day1,
        initial_cash=100_000,
        max_positions=2,
        max_position_pct=0.5,
        commission_rate=0.0,
        stamp_tax_rate=0.0,
        slippage_bps=0.0,
        min_entry_score=68,
        strict_entry=True,
    )

    result = engine._simulate(
        session=None,
        params=params,
        bars_by_symbol=bars_by_symbol,
        trading_days=[day1, day2],
        stock_meta={symbol_a: {"name": "浦发银行"}, symbol_b: {"name": "平安银行"}},
        score_cache=score_cache,
        minute_index=minute_index,
    )

    trades = result["trades"]
    orders = result["orders"]
    equity_tail = result["equity"][-1]
    positions = result["positions"]

    assert len(trades) == 1
    assert trades[0]["vt_symbol"] == symbol_a
    assert trades[0]["side"] == "BUY"
    assert trades[0]["price"] == 10.0
    assert trades[0]["volume"] == 5_000
    assert trades[0]["amount"] == 50_000.0
    assert equity_tail["cash"] == 50_000.0
    assert equity_tail["market_value"] == 51_000.0
    assert equity_tail["total_equity"] == 101_000.0
    assert positions[-1]["vt_symbol"] == symbol_a
    assert positions[-1]["market_value"] == 51_000.0
    rejected = [order for order in orders if order["status"] == "rejected"]
    assert rejected[0]["vt_symbol"] == symbol_b
    assert rejected[0]["reason"] == "limit_up_open_blocked"
    assert rejected[0]["raw"]["mode"] == "limit_up_open_blocked"


def test_dragon_pullback_execution_pool_does_not_reserve_lane_for_fresh_stealth_low_suction() -> None:
    from alphaagent.server.services.backtest import engine, simulation

    trade_date = date(2026, 4, 14)
    primary = [
        SignalScore(
            vt_symbol=f"600{index:03d}.SSE",
            trade_date=trade_date,
            total_score=95 - index,
            liquidity_score=80,
            risk_score=80,
            entry_signal=True,
            evidence={"status": "ready", "dragon_state": "TAIL_BUY_READY", "fresh_tail_buy": True},
        )
        for index in range(20)
    ]
    filler = [
        SignalScore(
            vt_symbol=f"601{index:03d}.SSE",
            trade_date=trade_date,
            total_score=78,
            liquidity_score=80,
            risk_score=80,
            entry_signal=True,
            evidence={"status": "ready", "dragon_state": "TAIL_BUY_READY", "fresh_tail_buy": True},
        )
        for index in range(30)
    ]
    stealth = SignalScore(
        vt_symbol="002747.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=70.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "low_suction_days": 4,
            "low_suction_buildup_score": 100.0,
            "stealth_low_suction_score": 100.0,
            "ma_convergence_pct": 3.2,
            "volume_ratio_5d_20d": 1.0,
            "ma20_distance_pct": 1.0,
            "failed_rules": [],
            "risk_flags": [],
            "fresh_stealth_low_suction": True,
            "latest_change_pct": 1.36,
            "ma5_distance_pct": 1.95,
            "ma10_distance_pct": 3.77,
            "ma20_distance_pct": 2.78,
            "ma_convergence_pct": 3.63,
            "volume_ratio_5d_20d": 1.10,
        },
    )
    params = engine.BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, candidate_limit=20)

    pool = simulation.execution_candidate_pool([*primary, *filler, stealth], params)

    assert len(pool) == 20
    assert "002747.SZSE" not in {item.vt_symbol for item in pool}


def test_dragon_pullback_execution_pool_does_not_reward_mature_low_suction_with_generic_bonus() -> None:
    from alphaagent.server.services.backtest import engine, simulation

    trade_date = date(2026, 4, 14)
    dragon = SignalScore(
        vt_symbol="600001.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=95,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "dragon_state": "TAIL_BUY_READY", "fresh_tail_buy": True},
    )
    fresh = SignalScore(
        vt_symbol="600367.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=84.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "low_suction_days": 3,
            "low_suction_buildup_score": 100.0,
            "stealth_low_suction_score": 100.0,
            "fresh_stealth_low_suction": True,
            "latest_change_pct": 3.0,
            "ma5_distance_pct": 2.2,
            "ma10_distance_pct": 1.1,
            "ma20_distance_pct": -0.8,
            "ma_convergence_pct": 3.1,
            "volume_ratio_5d_20d": 0.6,
            "failed_rules": [],
            "risk_flags": [],
        },
    )
    stale = SignalScore(
        vt_symbol="002747.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=82.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "low_suction_days": 7,
            "low_suction_buildup_score": 100.0,
            "stealth_low_suction_score": 100.0,
            "fresh_stealth_low_suction": False,
            "latest_change_pct": 2.2,
            "ma5_distance_pct": 1.2,
            "ma10_distance_pct": 1.4,
            "ma20_distance_pct": 1.0,
            "ma_convergence_pct": 2.0,
            "volume_ratio_5d_20d": 0.9,
            "ma5_slope_pct": 0.35,
            "ma5_vs_ma10_pct": 0.8,
            "close_location_in_range": 0.68,
            "strong_leg_score": 72.0,
            "return_20d": 8.0,
            "failed_rules": [],
            "risk_flags": [],
        },
    )
    params = engine.BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, candidate_limit=3)

    pool = simulation.execution_candidate_pool([dragon, stale, fresh], params)

    assert [item.vt_symbol for item in pool] == ["600001.SSE", "600367.SSE", "002747.SZSE"]


def test_backtest_execution_pool_excludes_support_divergence_research_entry() -> None:
    from alphaagent.server.services.backtest import engine, simulation

    trade_date = date(2026, 6, 12)
    normal = SignalScore(
        vt_symbol="600001.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=88.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "dragon_state": "TAIL_BUY_READY"},
    )
    support_divergence = SignalScore(
        vt_symbol="003004.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=96.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=False,
        evidence={
            "status": "ready",
            "support_divergence_entry_profile": "high_level_support_divergence",
            "raw_entry_signal": False,
            "default_executable_entry_signal": False,
            "support_divergence_entry_observation_only": True,
            "entry_setup": "support_accepted",
        },
    )
    params = engine.BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, candidate_limit=2)

    pool = simulation.execution_candidate_pool([support_divergence, normal], params)

    assert [item.vt_symbol for item in pool] == ["600001.SSE"]


def test_backtest_execution_pool_excludes_strong_trend_ma_pullback_research_entry() -> None:
    from alphaagent.server.services.backtest import engine, simulation

    trade_date = date(2026, 5, 25)
    normal = SignalScore(
        vt_symbol="600001.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=88.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "dragon_state": "TAIL_BUY_READY"},
    )
    ma_pullback = SignalScore(
        vt_symbol="003004.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=96.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=False,
        evidence={
            "status": "ready",
            "strong_trend_ma_pullback_entry_profile": "strong_trend_intraday_ma_pullback",
            "raw_entry_signal": False,
            "default_executable_entry_signal": False,
            "strong_trend_ma_pullback_entry_observation_only": True,
            "entry_setup": "pullback_observe",
        },
    )
    params = engine.BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, candidate_limit=2)

    pool = simulation.execution_candidate_pool([ma_pullback, normal], params)

    assert [item.vt_symbol for item in pool] == ["600001.SSE"]


def test_backtest_execution_pool_keeps_profile_candidate_when_raw_entry_signal_exists() -> None:
    from alphaagent.server.services.backtest import engine, simulation

    trade_date = date(2026, 6, 17)
    raw_buy_with_profile = SignalScore(
        vt_symbol="003004.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=96.1,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "support_divergence_entry_profile": "high_level_support_divergence",
            "raw_entry_signal": True,
            "default_executable_entry_signal": True,
            "support_divergence_entry_observation_only": False,
            "entry_setup": "support_accepted",
        },
    )
    params = engine.BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, candidate_limit=2)

    pool = simulation.execution_candidate_pool([raw_buy_with_profile], params)

    assert [item.vt_symbol for item in pool] == ["003004.SZSE"]


def test_backtest_execution_pool_keeps_default_clean_watch_entry() -> None:
    from alphaagent.server.services.backtest import engine, simulation

    trade_date = date(2026, 4, 30)
    clean_watch = SignalScore(
        vt_symbol="003004.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=64.6,
        liquidity_score=15,
        risk_score=80,
        entry_signal=False,
        evidence={
            "status": "ready",
            "default_clean_watch_entry_profile": "clean_low_liquidity_accumulation",
            "raw_entry_signal": False,
            "default_executable_entry_signal": True,
            "executable_entry_signal": True,
            "key_entry_signal": True,
            "signal_label": "低流动性承接低吸买点",
            "entry_setup": "support_accepted",
            "low_suction_days": 3,
        },
    )
    normal = SignalScore(
        vt_symbol="600001.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=70.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "entry_setup": "dragon_pullback"},
    )
    params = engine.BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, candidate_limit=2)

    pool = simulation.execution_candidate_pool([normal, clean_watch], params)

    assert [item.vt_symbol for item in pool] == ["003004.SZSE", "600001.SSE"]


def test_backtest_execution_pool_excludes_raw_signal_if_only_support_divergence_makes_it_executable() -> None:
    from alphaagent.server.services.backtest import engine, simulation

    trade_date = date(2026, 1, 8)
    support_divergence = SignalScore(
        vt_symbol="605090.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=98.61,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "support_divergence_entry_profile": "high_level_support_divergence",
            "raw_entry_signal": True,
            "default_executable_entry_signal": False,
            "support_divergence_entry_observation_only": True,
            "entry_setup": "support_accepted",
        },
    )
    params = engine.BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID, candidate_limit=2)

    pool = simulation.execution_candidate_pool([support_divergence], params)

    assert pool == []


def test_generic_stealth_low_suction_opportunity_bonus_is_removed() -> None:
    from alphaagent.server.services.quant import candidate_lanes

    trade_date = date(2026, 4, 14)
    mature = SignalScore(
        vt_symbol="002747.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=82.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "low_suction_days": 7,
            "latest_change_pct": 2.2,
            "ma5_distance_pct": 1.2,
            "ma10_distance_pct": 1.4,
            "ma20_distance_pct": 1.0,
            "ma_convergence_pct": 2.0,
            "volume_ratio_5d_20d": 0.9,
            "ma5_slope_pct": 0.35,
            "ma5_vs_ma10_pct": 0.8,
            "close_location_in_range": 0.68,
            "strong_leg_score": 72.0,
            "return_20d": 8.0,
            "failed_rules": [],
            "risk_flags": [],
        },
    )

    opportunity_score = candidate_lanes.dragon_pullback_opportunity_score(mature)

    assert not hasattr(candidate_lanes, "stealth_low_suction_opportunity_bonus")
    assert mature.total_score == 82.0
    assert opportunity_score == mature.total_score


def test_execution_pool_no_longer_reranks_by_volume_preparation() -> None:
    from alphaagent.server.services.quant import candidate_lanes

    trade_date = date(2026, 6, 12)
    weak_preparation = SignalScore(
        vt_symbol="WEAK.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "volume_ratio_5d_20d": 1.8,
            "large_bull_count_20d": 3,
            "recent_limit_up_20d": False,
        },
    )
    prepared_active = SignalScore(
        vt_symbol="GOOD.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=88.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "volume_ratio_5d_20d": 0.95,
            "large_bull_count_20d": 1,
            "recent_limit_up_20d": True,
        },
    )

    assert candidate_lanes.select_dragon_pullback_execution_pool(
        [weak_preparation, prepared_active],
        1,
        DRAGON_PULLBACK_STRATEGY_ID,
    ) == [weak_preparation]
    assert weak_preparation.total_score == 92.0
    assert prepared_active.total_score == 88.0


def test_execution_pool_keeps_active_washout_reclaim_inside_wide_ma_filter() -> None:
    from alphaagent.server.services.quant import candidate_lanes

    trade_date = date(2026, 3, 18)
    active_reclaim = SignalScore(
        vt_symbol="603629.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=100.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "support_type": "ma5_reclaim",
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 4,
            "latest_change_pct": 6.43,
            "return_5d": -2.01,
            "return_20d": 19.16,
            "ma_convergence_pct": 14.09,
            "ma20_distance_pct": 5.28,
            "drawdown_from_pivot_pct": -6.23,
            "volume_ratio_5d_20d": 0.85,
            "close_location_in_range": 0.94,
        },
    )
    stale_reclaim = SignalScore(
        vt_symbol="603115.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=99.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "support_type": "ma5_reclaim",
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 4,
            "latest_change_pct": 1.21,
            "return_5d": 11.72,
            "return_20d": 43.49,
            "ma_convergence_pct": 17.07,
            "ma20_distance_pct": 12.68,
            "drawdown_from_pivot_pct": -3.45,
            "volume_ratio_5d_20d": 0.94,
            "close_location_in_range": 0.88,
        },
    )

    assert candidate_lanes.active_washout_reclaim_confirmation(active_reclaim) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(active_reclaim) is None
    assert candidate_lanes.active_washout_reclaim_confirmation(stale_reclaim) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(stale_reclaim) == "wide_ma_no_low_suction_high_close_volume_decay"


def test_execution_pool_keeps_healthy_quiet_low_suction_on_score_without_generic_bonus() -> None:
    from alphaagent.server.services.quant import candidate_lanes

    trade_date = date(2026, 1, 7)
    quiet_low_suction = SignalScore(
        vt_symbol="000338.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=85.5,
        liquidity_score=100,
        risk_score=68,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "low_suction_days": 6,
            "latest_change_pct": 0.906,
            "ma5_distance_pct": 1.898,
            "ma10_distance_pct": 1.904,
            "ma_convergence_pct": 0.593,
            "close_location_in_range": 0.692,
            "return_20d": 2.179,
            "return_60d": 24.79,
            "volume_ratio_5d_20d": 1.029,
            "large_bull_count_20d": 0,
            "recent_limit_up_20d": False,
        },
    )

    assert not hasattr(candidate_lanes, "stealth_low_suction_opportunity_bonus")
    assert candidate_lanes.dragon_pullback_opportunity_score(quiet_low_suction) == quiet_low_suction.total_score


def test_execution_pool_promotes_bottom_reclaim_only_with_positive_timing_bonus() -> None:
    from alphaagent.server.services.quant import candidate_lanes

    trade_date = date(2026, 3, 19)
    bottom_reclaim = SignalScore(
        vt_symbol="BOTTOM.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=82.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "oversold_rebound_start",
            "setup_family": "oversold_rebound_start",
            "rebound_subtype": "bottom_reclaim",
            "bottom_reclaim": True,
            "timing_window": "after_silver_6_20",
            "market_phase": "retreat",
            "close_location_in_range": 0.45,
            "volume_ratio_5d_20d": 0.9,
        },
    )
    plain_higher_score = SignalScore(
        vt_symbol="PLAIN.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=86.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "entry_setup": "dragon_pullback"},
    )

    pool = candidate_lanes.select_dragon_pullback_execution_pool(
        [plain_higher_score, bottom_reclaim],
        1,
        DRAGON_PULLBACK_STRATEGY_ID,
    )
    context = candidate_lanes.execution_pool_context(
        [plain_higher_score, bottom_reclaim],
        1,
        DRAGON_PULLBACK_STRATEGY_ID,
    )

    assert pool == [bottom_reclaim]
    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(bottom_reclaim) == 4.55
    assert context["BOTTOM.SZSE"]["execution_timing_opportunity_bonus"] == 4.55
    assert context["BOTTOM.SZSE"]["execution_opportunity_score"] == 86.55
    assert context["BOTTOM.SZSE"]["execution_candidate_selected"] is True


def test_execution_pool_does_not_penalize_weak_timing_window() -> None:
    from alphaagent.server.services.quant import candidate_lanes

    trade_date = date(2026, 3, 19)
    warming_bottom_reclaim = SignalScore(
        vt_symbol="WARM.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=82.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "oversold_rebound_start",
            "setup_family": "oversold_rebound_start",
            "rebound_subtype": "bottom_reclaim",
            "bottom_reclaim": True,
            "timing_window": "after_silver_6_20",
            "market_phase": "warming",
            "close_location_in_range": 0.45,
            "volume_ratio_5d_20d": 0.9,
        },
    )

    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(warming_bottom_reclaim) == 0.0
    assert candidate_lanes.dragon_pullback_opportunity_score(warming_bottom_reclaim) == warming_bottom_reclaim.total_score


def test_execution_pool_rewards_confirmed_bottom_reclaim_repair() -> None:
    from alphaagent.server.services.quant import candidate_lanes

    trade_date = date(2026, 6, 9)
    confirmed = SignalScore(
        vt_symbol="REPAIR.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=82.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "oversold_rebound_start",
            "setup_family": "oversold_rebound_start",
            "rebound_subtype": "bottom_reclaim",
            "bottom_reclaim": True,
            "timing_window": "after_silver_6_20",
            "market_phase": "retreat",
            "bottom_ma_repair_strength_score": 78.0,
            "bottom_ma_repair_strength_bucket": "strong_repair",
            "bottom_ma_repair_stage": "ma10_reclaim",
            "close_location_in_range": 0.45,
            "volume_ratio_5d_20d": 0.9,
        },
    )

    reasons = candidate_lanes.dragon_pullback_timing_opportunity_reasons(confirmed)

    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(confirmed) == 5.45
    assert any(reason["key"] == "bottom_reclaim_confirmed_repair" for reason in reasons)


def test_execution_pool_promotes_gold_short_window_oversold_repair() -> None:
    from alphaagent.server.services.quant import candidate_lanes

    trade_date = date(2026, 7, 2)
    gold_repair = SignalScore(
        vt_symbol="GOLDREPAIR.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=82.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "oversold_rebound_start",
            "setup_family": "oversold_rebound_start",
            "rebound_subtype": "bottom_reclaim",
            "bottom_reclaim": True,
            "timing_window": "after_gold_0_5",
            "market_phase": "retreat",
            "bottom_ma_repair_strength_score": 78.0,
            "bottom_ma_repair_strength_bucket": "strong_repair",
            "bottom_ma_repair_stage": "ma10_reclaim",
            "close_location_in_range": 0.45,
            "volume_ratio_5d_20d": 0.9,
        },
    )
    plain_higher_score = SignalScore(
        vt_symbol="PLAIN.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=86.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "entry_setup": "dragon_pullback"},
    )

    pool = candidate_lanes.select_dragon_pullback_execution_pool(
        [plain_higher_score, gold_repair],
        1,
        DRAGON_PULLBACK_STRATEGY_ID,
    )
    reasons = candidate_lanes.dragon_pullback_timing_opportunity_reasons(gold_repair)
    keys = {reason["key"] for reason in reasons}

    assert pool == [gold_repair]
    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(gold_repair) == 5.45
    assert "oversold_gold_0_5_retreat_repair" in keys
    assert "bottom_reclaim_gold_confirmed_repair" in keys


def test_execution_pool_rewards_active_right_tail_source_context() -> None:
    from alphaagent.server.services.quant import candidate_lanes

    trade_date = date(2026, 3, 25)
    right_tail = SignalScore(
        vt_symbol="RIGHT.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=88.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_low_suction_overlap",
            "setup_family": "dragon_low_suction_overlap",
            "timing_window": "after_silver_late",
            "market_phase": "retreat",
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 1,
            "large_bull_count_20d": 1,
            "close_location_in_range": 0.61,
            "volume_ratio_5d_20d": 0.86,
        },
    )

    reasons = candidate_lanes.dragon_pullback_timing_opportunity_reasons(right_tail)
    keys = {reason["key"] for reason in reasons}

    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(right_tail) == 3.95
    assert "right_tail_active_source_context" in keys
    assert "right_tail_timing_context" in keys
    assert "right_tail_controlled_volume" in keys


def test_screening_attaches_visible_market_timing_context_to_evidence() -> None:
    from alphaagent.server.services.quant import screening

    score = SignalScore(
        vt_symbol="600001.SSE",
        trade_date=date(2026, 3, 19),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=82.0,
        entry_signal=True,
        evidence={"status": "ready", "entry_setup": "oversold_rebound_start"},
    )

    screening._attach_market_timing_context(
        score,
        {
            "nearest_timing_direction": "SILVER",
            "nearest_timing_grade": "MEDIUM",
            "nearest_timing_date": "2026-03-12",
            "nearest_timing_days": 5,
            "timing_window": "after_silver_0_5",
            "market_phase": "retreat",
            "bull_force": 42.0,
            "bear_force": 68.0,
        },
    )

    assert score.evidence["nearest_timing_direction"] == "SILVER"
    assert score.evidence["timing_window"] == "after_silver_0_5"
    assert score.evidence["market_phase"] == "retreat"
    assert score.evidence["bear_force"] == 68.0


def test_execution_pool_drops_stale_active_weak_decay_pullback_without_refill() -> None:
    from alphaagent.server.services.quant import candidate_lanes

    trade_date = date(2026, 3, 9)
    weak = SignalScore(
        vt_symbol="002208.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=98.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "low_suction_days": 6,
            "low_suction_launch_confirmed": False,
            "first_effective_lift": False,
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 1,
            "pullback_days": 9,
            "close_location_in_range": 0.65,
            "volume_ratio_5d_20d": 0.98,
        },
    )
    protected_low_close = SignalScore(
        vt_symbol="000021.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=97.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "low_suction_days": 6,
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 1,
            "pullback_days": 9,
            "close_location_in_range": 0.18,
            "volume_ratio_5d_20d": 0.98,
        },
    )
    strength_decay = SignalScore(
        vt_symbol="002756.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=96.5,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "low_suction_days": 6,
            "low_suction_launch_confirmed": False,
            "first_effective_lift": False,
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 1,
            "pullback_days": 4,
            "strong_leg_score": 100,
            "close_location_in_range": 0.58,
            "volume_ratio_5d_20d": 0.89,
        },
    )
    old_low_suction_decay = SignalScore(
        vt_symbol="605117.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=95.5,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "low_suction_days": 5,
            "strong_leg_score": 98,
            "volume_ratio_5d_20d": 1.0,
        },
    )
    crowded_large_bull_stretch = SignalScore(
        vt_symbol="600522.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=95.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "large_bull_count_20d": 3,
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 0,
            "ma20_distance_pct": 8.2,
        },
    )
    crowded_large_bull_high_close = SignalScore(
        vt_symbol="002851.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=94.8,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "large_bull_count_20d": 3,
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 0,
            "close_location_in_range": 0.89,
            "ma20_distance_pct": 3.2,
        },
    )
    old_ma10_no_limit_normal_volume = SignalScore(
        vt_symbol="002230.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=94.5,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "low_suction_days": 5,
            "support_type": "ma10_support",
            "pullback_days": 9,
            "strong_leg_score": 80,
            "ma10_distance_pct": 2.8,
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 0,
            "volume_ratio_5d_20d": 0.95,
        },
    )
    protected_low_volume_ma10 = SignalScore(
        vt_symbol="002131.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=94.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "low_suction_days": 5,
            "support_type": "ma10_support",
            "pullback_days": 9,
            "strong_leg_score": 80,
            "ma10_distance_pct": 2.8,
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 0,
            "volume_ratio_5d_20d": 0.64,
        },
    )
    old_ma10_ma5_stretch_decay = SignalScore(
        vt_symbol="002624.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=93.8,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 5,
            "support_type": "ma10_support",
            "pullback_days": 12,
            "strong_leg_score": 84,
            "ma5_distance_pct": 3.8,
            "ma10_distance_pct": 2.3,
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 1,
            "close_location_in_range": 0.65,
            "volume_ratio_5d_20d": 0.7,
        },
    )
    protected_old_ma10_ma5_not_stretched = SignalScore(
        vt_symbol="002916.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=93.6,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 5,
            "support_type": "ma10_support",
            "pullback_days": 12,
            "strong_leg_score": 84,
            "ma5_distance_pct": 3.2,
            "ma10_distance_pct": 2.3,
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 1,
            "close_location_in_range": 0.65,
            "volume_ratio_5d_20d": 0.7,
        },
    )
    strong_long_pullback_far_from_ma10 = SignalScore(
        vt_symbol="002354.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=93.5,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "strong_leg_score": 100,
            "pullback_days": 9,
            "ma10_distance_pct": 5.6,
        },
    )
    protected_strong_long_pullback_near_ma10 = SignalScore(
        vt_symbol="600026.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=93.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "strong_leg_score": 100,
            "pullback_days": 9,
            "ma10_distance_pct": 4.2,
        },
    )
    core_active_strong_shrink_ma10_upper = SignalScore(
        vt_symbol="002831.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.8,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 1,
            "large_bull_count_20d": 2,
            "strong_leg_score": 98,
            "support_type": "ma10_support",
            "pullback_days": 6,
            "support_hold_days": 6,
            "drawdown_from_pivot_pct": -7.5,
            "ma5_distance_pct": 1.6,
            "ma10_distance_pct": 3.4,
            "ma20_distance_pct": 6.8,
            "close_location_in_range": 0.55,
            "volume_ratio_5d_20d": 0.74,
        },
    )
    protected_core_active_strong_tight_ma10 = SignalScore(
        vt_symbol="002384.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.7,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 1,
            "large_bull_count_20d": 2,
            "strong_leg_score": 98,
            "support_type": "ma10_support",
            "pullback_days": 6,
            "support_hold_days": 6,
            "drawdown_from_pivot_pct": -7.5,
            "ma5_distance_pct": 1.6,
            "ma10_distance_pct": 2.2,
            "ma20_distance_pct": 6.8,
            "close_location_in_range": 0.55,
            "volume_ratio_5d_20d": 0.74,
        },
    )
    protected_core_active_strong_heavier_volume = SignalScore(
        vt_symbol="600176.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.6,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 1,
            "large_bull_count_20d": 2,
            "strong_leg_score": 98,
            "support_type": "ma10_support",
            "pullback_days": 6,
            "support_hold_days": 6,
            "drawdown_from_pivot_pct": -7.5,
            "ma5_distance_pct": 1.6,
            "ma10_distance_pct": 3.4,
            "ma20_distance_pct": 6.8,
            "close_location_in_range": 0.55,
            "volume_ratio_5d_20d": 0.96,
        },
    )
    core_active_ma10_flat_mid_high_turnover = SignalScore(
        vt_symbol="002536.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.55,
        liquidity_score=100,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 1,
            "large_bull_count_20d": 2,
            "strong_leg_score": 84,
            "support_type": "ma10_support",
            "pullback_days": 6,
            "support_hold_days": 5,
            "drawdown_from_pivot_pct": -8.5,
            "ma5_distance_pct": 0.4,
            "ma10_distance_pct": 1.2,
            "ma20_distance_pct": 4.2,
            "ma_convergence_pct": 7.0,
            "latest_change_pct": 1.2,
            "close_location_in_range": 0.66,
            "volume_ratio_5d_20d": 0.96,
            "turnover20": 1_200_000_000,
        },
    )
    wide_ma10_high_turnover_normal_volume = SignalScore(
        vt_symbol="600188.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.5,
        liquidity_score=100,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "support_type": "ma10_support",
            "ma_convergence_pct": 16.0,
            "low_suction_days": 0,
            "close_location_in_range": 0.66,
            "ma5_distance_pct": -2.0,
            "volume_ratio_5d_20d": 1.02,
            "turnover20": 1_200_000_000,
        },
    )
    wide_ma_no_low_high_close_normal_volume = SignalScore(
        vt_symbol="000878.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.3,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "ma_convergence_pct": 17.3,
            "low_suction_days": 0,
            "close_location_in_range": 0.85,
            "volume_ratio_5d_20d": 1.22,
            "ma5_distance_pct": -6.0,
            "ma10_distance_pct": -0.8,
        },
    )
    protected_low_turnover_wide_ma10 = SignalScore(
        vt_symbol="603163.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=92.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "support_type": "ma10_support",
            "ma_convergence_pct": 16.0,
            "low_suction_days": 0,
            "close_location_in_range": 0.66,
            "ma5_distance_pct": -2.0,
            "volume_ratio_5d_20d": 1.02,
            "turnover20": 600_000_000,
        },
    )
    protected_heavy_volume_wide_ma10 = SignalScore(
        vt_symbol="002192.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.5,
        liquidity_score=100,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "support_type": "ma10_support",
            "ma_convergence_pct": 16.0,
            "low_suction_days": 0,
            "close_location_in_range": 0.66,
            "ma5_distance_pct": -2.0,
            "volume_ratio_5d_20d": 1.55,
            "turnover20": 1_200_000_000,
        },
    )
    protected_wide_high_close_heavy_volume_washout = SignalScore(
        vt_symbol="000815.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.4,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "ma_convergence_pct": 17.3,
            "low_suction_days": 0,
            "close_location_in_range": 0.85,
            "volume_ratio_5d_20d": 1.49,
            "ma5_distance_pct": -5.5,
            "ma10_distance_pct": 1.8,
        },
    )
    overheated_ma5_reclaim_far_ma10 = SignalScore(
        vt_symbol="605376.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.2,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "support_type": "ma5_reclaim",
            "low_suction_days": 0,
            "pullback_days": 3,
            "strong_leg_score": 100,
            "ma10_distance_pct": 8.2,
            "return_20d": 63.0,
        },
    )
    protected_far_ma10_not_extreme_return = SignalScore(
        vt_symbol="603256.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=91.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "support_type": "ma5_reclaim",
            "low_suction_days": 0,
            "pullback_days": 3,
            "strong_leg_score": 100,
            "ma10_distance_pct": 8.2,
            "return_20d": 50.0,
        },
    )
    protected_large_bull_with_recent_limit = SignalScore(
        vt_symbol="603688.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.9,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "large_bull_count_20d": 3,
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 1,
            "close_location_in_range": 0.90,
            "ma20_distance_pct": 3.2,
        },
    )
    protected_large_bull_controlled_close = SignalScore(
        vt_symbol="603689.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.8,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "large_bull_count_20d": 3,
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 0,
            "close_location_in_range": 0.74,
            "ma20_distance_pct": 3.2,
        },
    )
    core_active_short_pullback_strong_lift = SignalScore(
        vt_symbol="002025.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.75,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 1,
            "large_bull_count_20d": 2,
            "strong_leg_score": 100,
            "support_type": "ma5_reclaim",
            "pullback_days": 4,
            "support_hold_days": 4,
            "drawdown_from_pivot_pct": -8.0,
            "ma5_distance_pct": 0.63,
            "ma10_distance_pct": -0.69,
            "ma20_distance_pct": 6.3,
            "latest_change_pct": 4.36,
            "close_location_in_range": 0.66,
            "volume_ratio_5d_20d": 1.15,
        },
    )
    protected_low_suction_first_lift = SignalScore(
        vt_symbol="003004.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.7,
        liquidity_score=15,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 4,
            "low_suction_launch_confirmed": True,
            "first_effective_lift": True,
            "strong_leg_score": 72,
            "ma5_distance_pct": 2.68,
            "ma10_distance_pct": 2.56,
            "ma20_distance_pct": 4.2,
            "latest_change_pct": 3.0,
            "close_location_in_range": 0.72,
            "volume_ratio_5d_20d": 0.75,
        },
    )
    protected_long_washout_right_tail = SignalScore(
        vt_symbol="600869.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.6,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 1,
            "large_bull_count_20d": 2,
            "strong_leg_score": 100,
            "support_type": "ma5_reclaim",
            "low_suction_days": 1,
            "pullback_days": 10,
            "support_hold_days": 4,
            "drawdown_from_pivot_pct": -8.0,
            "ma5_distance_pct": 0.76,
            "ma10_distance_pct": -0.72,
            "ma20_distance_pct": 4.34,
            "latest_change_pct": 2.27,
            "close_location_in_range": 0.37,
            "volume_ratio_5d_20d": 0.96,
        },
    )
    refill = SignalScore(
        vt_symbol="600001.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=80.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "entry_setup": "dragon_pullback"},
    )

    pool = candidate_lanes.select_dragon_pullback_execution_pool(
        [
            weak,
            protected_low_close,
            strength_decay,
            old_low_suction_decay,
            crowded_large_bull_stretch,
            crowded_large_bull_high_close,
            old_ma10_no_limit_normal_volume,
            protected_low_volume_ma10,
            old_ma10_ma5_stretch_decay,
            protected_old_ma10_ma5_not_stretched,
            strong_long_pullback_far_from_ma10,
            protected_strong_long_pullback_near_ma10,
            core_active_strong_shrink_ma10_upper,
            protected_core_active_strong_tight_ma10,
            protected_core_active_strong_heavier_volume,
            core_active_ma10_flat_mid_high_turnover,
            wide_ma10_high_turnover_normal_volume,
            wide_ma_no_low_high_close_normal_volume,
            protected_low_turnover_wide_ma10,
            protected_heavy_volume_wide_ma10,
            protected_wide_high_close_heavy_volume_washout,
            overheated_ma5_reclaim_far_ma10,
            protected_far_ma10_not_extreme_return,
            protected_large_bull_with_recent_limit,
            protected_large_bull_controlled_close,
            core_active_short_pullback_strong_lift,
            protected_low_suction_first_lift,
            protected_long_washout_right_tail,
            refill,
        ],
        28,
        DRAGON_PULLBACK_STRATEGY_ID,
    )
    context = candidate_lanes.execution_pool_context(
        [
            weak,
            protected_low_close,
            strength_decay,
            old_low_suction_decay,
            crowded_large_bull_stretch,
            crowded_large_bull_high_close,
            old_ma10_no_limit_normal_volume,
            protected_low_volume_ma10,
            old_ma10_ma5_stretch_decay,
            protected_old_ma10_ma5_not_stretched,
            strong_long_pullback_far_from_ma10,
            protected_strong_long_pullback_near_ma10,
            core_active_strong_shrink_ma10_upper,
            protected_core_active_strong_tight_ma10,
            protected_core_active_strong_heavier_volume,
            core_active_ma10_flat_mid_high_turnover,
            wide_ma10_high_turnover_normal_volume,
            wide_ma_no_low_high_close_normal_volume,
            protected_low_turnover_wide_ma10,
            protected_heavy_volume_wide_ma10,
            protected_wide_high_close_heavy_volume_washout,
            overheated_ma5_reclaim_far_ma10,
            protected_far_ma10_not_extreme_return,
            protected_large_bull_with_recent_limit,
            protected_large_bull_controlled_close,
            core_active_short_pullback_strong_lift,
            protected_low_suction_first_lift,
            protected_long_washout_right_tail,
            refill,
        ],
        28,
        DRAGON_PULLBACK_STRATEGY_ID,
    )

    assert [item.vt_symbol for item in pool] == [
        "000021.SZSE",
        "002131.SZSE",
        "002916.SZSE",
        "600026.SSE",
        "002384.SZSE",
        "600176.SSE",
        "002536.SZSE",
        "603163.SSE",
        "002192.SZSE",
        "000815.SZSE",
        "603256.SSE",
        "603688.SSE",
        "603689.SSE",
        "003004.SZSE",
        "600869.SSE",
    ]
    assert context["002208.SZSE"]["execution_candidate_selected"] is False
    assert context["002208.SZSE"]["execution_quality_filtered"] is True
    assert context["002208.SZSE"]["execution_quality_filter_reason"] == "stale_active_weak_decay_pullback"
    assert context["002756.SZSE"]["execution_candidate_selected"] is False
    assert context["002756.SZSE"]["execution_quality_filtered"] is True
    assert context["002756.SZSE"]["execution_quality_filter_reason"] == "stale_active_weak_decay_pullback"
    assert context["605117.SSE"]["execution_candidate_selected"] is False
    assert context["605117.SSE"]["execution_quality_filtered"] is True
    assert context["605117.SSE"]["execution_quality_filter_reason"] == "old_low_suction_strong_leg_normal_volume"
    assert context["600522.SSE"]["execution_candidate_selected"] is False
    assert context["600522.SSE"]["execution_quality_filtered"] is True
    assert context["600522.SSE"]["execution_quality_filter_reason"] == "large_bull_no_limit_ma20_stretch"
    assert context["002851.SZSE"]["execution_candidate_selected"] is False
    assert context["002851.SZSE"]["execution_quality_filtered"] is True
    assert context["002851.SZSE"]["execution_quality_filter_reason"] == "crowded_large_bull_no_limit_high_close_decay"
    assert context["002230.SZSE"]["execution_candidate_selected"] is False
    assert context["002230.SZSE"]["execution_quality_filtered"] is True
    assert context["002230.SZSE"]["execution_quality_filter_reason"] == "old_ma10_support_no_limit_normal_volume_decay"
    assert context["002624.SZSE"]["execution_candidate_selected"] is False
    assert context["002624.SZSE"]["execution_quality_filtered"] is True
    assert context["002624.SZSE"]["execution_quality_filter_reason"] == "old_ma10_support_ma5_stretch_decay"
    assert context["002354.SZSE"]["execution_candidate_selected"] is False
    assert context["002354.SZSE"]["execution_quality_filtered"] is True
    assert context["002354.SZSE"]["execution_quality_filter_reason"] == "strong_leg_long_pullback_ma10_far_decay"
    assert context["002831.SZSE"]["execution_candidate_selected"] is False
    assert context["002831.SZSE"]["execution_quality_filtered"] is True
    assert context["002831.SZSE"]["execution_quality_filter_reason"] == "core_active_strong_leg_shrink_ma10_upper_decay"
    assert context["002536.SZSE"]["execution_candidate_selected"] is True
    assert context["002536.SZSE"]["execution_quality_filtered"] is False
    assert context["600188.SSE"]["execution_candidate_selected"] is False
    assert context["600188.SSE"]["execution_quality_filtered"] is True
    assert context["600188.SSE"]["execution_quality_filter_reason"] == "wide_ma10_high_turnover_normal_volume_decay"
    assert context["000878.SZSE"]["execution_candidate_selected"] is False
    assert context["000878.SZSE"]["execution_quality_filtered"] is True
    assert context["000878.SZSE"]["execution_quality_filter_reason"] == "wide_ma_no_low_suction_high_close_volume_decay"
    assert context["605376.SSE"]["execution_candidate_selected"] is False
    assert context["605376.SSE"]["execution_quality_filtered"] is True
    assert context["605376.SSE"]["execution_quality_filter_reason"] == "overheated_ma5_reclaim_ma10_far_decay"
    assert context["002025.SZSE"]["execution_candidate_selected"] is False
    assert context["002025.SZSE"]["execution_quality_filtered"] is True
    assert context["002025.SZSE"]["execution_quality_filter_reason"] == "core_active_short_pullback_strong_leg_lift_decay"
    assert context["000021.SZSE"]["execution_candidate_selected"] is True
    assert context["002131.SZSE"]["execution_candidate_selected"] is True
    assert context["002131.SZSE"]["execution_quality_filtered"] is False
    assert context["002916.SZSE"]["execution_candidate_selected"] is True
    assert context["603688.SSE"]["execution_candidate_selected"] is True
    assert context["603688.SSE"]["execution_quality_filtered"] is False
    assert context["603689.SSE"]["execution_candidate_selected"] is True
    assert context["603689.SSE"]["execution_quality_filtered"] is False
    assert context["002916.SZSE"]["execution_quality_filtered"] is False
    assert context["600026.SSE"]["execution_candidate_selected"] is True
    assert context["600026.SSE"]["execution_quality_filtered"] is False
    assert context["002384.SZSE"]["execution_candidate_selected"] is True
    assert context["002384.SZSE"]["execution_quality_filtered"] is False
    assert context["600176.SSE"]["execution_candidate_selected"] is True
    assert context["600176.SSE"]["execution_quality_filtered"] is False
    assert context["603163.SSE"]["execution_candidate_selected"] is True
    assert context["603163.SSE"]["execution_quality_filtered"] is False
    assert context["002192.SZSE"]["execution_candidate_selected"] is True
    assert context["002192.SZSE"]["execution_quality_filtered"] is False
    assert context["000815.SZSE"]["execution_candidate_selected"] is True
    assert context["000815.SZSE"]["execution_quality_filtered"] is False
    assert context["603256.SSE"]["execution_candidate_selected"] is True
    assert context["603256.SSE"]["execution_quality_filtered"] is False
    assert context["003004.SZSE"]["execution_candidate_selected"] is True
    assert context["003004.SZSE"]["execution_quality_filtered"] is False
    assert context["600869.SSE"]["execution_candidate_selected"] is True
    assert context["600869.SSE"]["execution_quality_filtered"] is False
    assert context["600001.SSE"]["execution_candidate_selected"] is False


def test_default_candidate_quality_score_rewards_mature_active_low_suction() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    trade_date = date(2026, 2, 4)
    weaker_right_tail = SignalScore(
        vt_symbol="001896.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=96.2,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 4,
            "low_suction_launch_confirmed": True,
            "ma5_distance_pct": 1.6,
            "ma10_distance_pct": 2.1,
            "ma_convergence_pct": 4.0,
            "volume_ratio_5d_20d": 0.9,
            "recent_limit_up_20d": True,
            "large_bull_count_20d": 1,
            "market_warning_level": 1,
            "ma5_slope_pct": 0.2,
            "latest_change_pct": 2.0,
            "close_location_in_range": 0.62,
        },
    )
    higher_plain = SignalScore(
        vt_symbol="600001.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=97.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "entry_setup": "dragon_pullback"},
    )

    rows = scoring.score_day(
        None,
        {"001896.SZSE": [], "600001.SSE": []},
        trade_date,
        BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID),
        score_cache={trade_date: [higher_plain, weaker_right_tail]},
    )

    assert [row.vt_symbol for row in rows] == ["001896.SZSE", "600001.SSE"]
    assert rows[0].evidence["candidate_quality_adjustment"] == 2.55
    assert rows[0].evidence["candidate_quality_notes"] == [
        "成熟低吸首启加分",
        "近期活跃右尾来源加分",
        "活跃且可交易低中位轻加分",
    ]


def test_default_candidate_quality_score_penalizes_overextended_non_right_tail() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    trade_date = date(2026, 5, 12)
    overextended = SignalScore(
        vt_symbol="600002.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=97.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "ma5_distance_pct": 7.2,
            "volume_stall_risk": True,
            "market_warning_level": 3,
            "close_location_in_range": 0.76,
            "ma5_slope_pct": -0.1,
            "large_bull_count_20d": 0,
        },
    )
    stable = SignalScore(
        vt_symbol="600003.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=94.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "entry_setup": "dragon_pullback"},
    )

    rows = scoring.score_day(
        None,
        {"600002.SSE": [], "600003.SSE": []},
        trade_date,
        BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID),
        score_cache={trade_date: [overextended, stable]},
    )

    assert [row.vt_symbol for row in rows] == ["600003.SSE", "600002.SSE"]
    assert rows[1].evidence["candidate_quality_adjustment"] == -4.0
    assert "偏离5日线过远降权" in rows[1].evidence["candidate_quality_notes"]
    assert "放量滞涨降权" in rows[1].evidence["candidate_quality_notes"]


def test_default_candidate_quality_score_penalizes_high_close_false_low_suction_launch() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    trade_date = date(2026, 5, 18)
    high_close_false_launch = SignalScore(
        vt_symbol="605117.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=94.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 3,
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "high_close_launch",
            "ma5_distance_pct": 2.3,
            "ma10_distance_pct": 2.4,
            "ma_convergence_pct": 7.9,
            "volume_ratio_5d_20d": 0.92,
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 0,
            "large_bull_count_20d": 1,
            "market_warning_level": 1,
            "ma5_slope_pct": 0.2,
            "latest_change_pct": 4.5,
            "close_location_in_range": 0.95,
        },
    )
    stable_low_mid_launch = SignalScore(
        vt_symbol="600003.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=94.5,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "entry_setup": "dragon_pullback"},
    )

    rows = scoring.score_day(
        None,
        {"605117.SSE": [], "600003.SSE": []},
        trade_date,
        BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID),
        score_cache={trade_date: [high_close_false_launch, stable_low_mid_launch]},
    )

    assert [row.vt_symbol for row in rows] == ["600003.SSE", "605117.SSE"]
    assert rows[1].evidence["candidate_quality_adjustment"] == 0.1
    assert "无涨停来源高位启动降权" in rows[1].evidence["candidate_quality_notes"]
    assert "成熟低吸无涨停高位确认不足降权" in rows[1].evidence["candidate_quality_notes"]


def test_default_candidate_quality_score_adds_stale_active_weak_decay_pullback_penalty() -> None:
    from alphaagent.server.services.backtest import scoring
    from alphaagent.server.services.backtest.schemas import BacktestParams

    trade_date = date(2026, 3, 9)
    stale_active_long_pullback = SignalScore(
        vt_symbol="002208.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=94.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "low_suction_days": 6,
            "low_suction_launch_confirmed": False,
            "first_effective_lift": False,
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 1,
            "large_bull_count_20d": 1,
            "pullback_days": 9,
            "close_location_in_range": 0.65,
            "volume_ratio_5d_20d": 0.98,
            "ma5_distance_pct": 3.8,
            "ma10_distance_pct": 2.4,
            "ma5_slope_pct": 0.2,
            "latest_change_pct": 1.5,
            "market_warning_level": 1,
        },
    )
    protected_low_close = SignalScore(
        vt_symbol="000021.SZSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=93.0,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "low_suction_days": 6,
            "low_suction_launch_confirmed": False,
            "first_effective_lift": False,
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 1,
            "large_bull_count_20d": 1,
            "pullback_days": 9,
            "close_location_in_range": 0.18,
            "volume_ratio_5d_20d": 0.98,
            "ma5_distance_pct": 1.0,
            "ma10_distance_pct": 1.3,
            "ma5_slope_pct": 0.2,
            "latest_change_pct": 1.5,
            "market_warning_level": 1,
        },
    )

    rows = scoring.score_day(
        None,
        {"002208.SZSE": [], "000021.SZSE": []},
        trade_date,
        BacktestParams(strategy=DRAGON_PULLBACK_STRATEGY_ID),
        score_cache={trade_date: [stale_active_long_pullback, protected_low_close]},
    )
    by_symbol = {row.vt_symbol: row for row in rows}

    assert by_symbol["002208.SZSE"].evidence["candidate_quality_adjustment"] == -2.0
    assert "活跃陈旧弱量强势衰减无首启追加降权" in by_symbol["002208.SZSE"].evidence["candidate_quality_notes"]
    assert by_symbol["000021.SZSE"].evidence["candidate_quality_adjustment"] == -0.9
    assert "活跃陈旧弱量强势衰减无首启追加降权" not in by_symbol["000021.SZSE"].evidence["candidate_quality_notes"]


def test_candidate_entry_reason_records_execution_lane_context() -> None:
    from alphaagent.server.services.backtest import simulation

    trade_date = date(2026, 2, 11)
    candidate = SignalScore(
        vt_symbol="600367.SSE",
        trade_date=trade_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=82.0283,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
        },
    )

    reason = simulation.candidate_entry_reason(
        candidate,
        {
            "execution_lane": "stealth_low_suction",
            "raw_signal_rank": 238,
            "execution_opportunity_score": 88.25,
            "execution_opportunity_bonus": 6.25,
            "execution_candidate_rank": 7,
            "execution_candidate_selected": True,
            "execution_candidate_limit": 20,
        },
    )

    assert reason["candidate_execution"]["execution_lane"] == "stealth_low_suction"
    assert reason["candidate_execution"]["execution_opportunity_score"] == 88.25
    assert reason["candidate_execution"]["execution_opportunity_bonus"] == 6.25
    assert reason["candidate_execution"]["execution_candidate_rank"] == 7


def test_backtest_buy_order_raw_keeps_entry_evidence() -> None:
    from alphaagent.server.services.backtest import engine

    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)
    symbol = "601179.SSE"
    bars_by_symbol = {
        symbol: [
            engine.Bar(d0, 10.0, 10.6, 9.8, 10.4, volume=1000),
            engine.Bar(d1, 10.5, 11.0, 10.2, 10.8, volume=1200),
        ]
    }
    candidate = SignalScore(
        vt_symbol=symbol,
        trade_date=d0,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=96.1786,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "dragon_pullback",
            "setup_type": "dragon_pullback",
            "ma_convergence_pct": 22.91,
            "latest_change_pct": 7.58,
            "close_location_in_range": 0.62,
            "early_dragon_pullback_risk": True,
            "failed_rules": [],
        },
    )
    params = engine.BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        start=d0,
        end=d1,
        initial_cash=100_000,
        max_positions=1,
        max_position_pct=1.0,
        commission_rate=0.0,
        stamp_tax_rate=0.0,
        slippage_bps=0.0,
        execution_model="legacy_next_open",
        intraday_entry=False,
    )

    run = engine._simulate(
        None,
        params,
        bars_by_symbol,
        [d0, d1],
        {symbol: {"name": "中国西电"}},
        score_cache={d0: [candidate]},
        minute_index={},
        score_context=engine.ScoreContext(),
    )

    buy_order = next(order for order in run["orders"] if order["side"] == "BUY")
    assert buy_order["raw"]["mode"] == "daily_next_open"
    assert buy_order["raw"]["entry_setup"] == "dragon_pullback"
    assert buy_order["raw"]["ma_convergence_pct"] == 22.91
    assert buy_order["raw"]["early_dragon_pullback_risk"] is True


def test_candidate_trace_summary_explains_filled_candidate() -> None:
    from alphaagent.server.services.backtest import engine

    signal_date = date(2026, 1, 5)
    execute_date = date(2026, 1, 6)
    result = engine._candidate_trace_summary(
        backtest_id=7,
        vt_symbol="600000.SSE",
        signal_date=signal_date,
        run={"strategy_id": "mainline_leader_pullback", "strategy_version": "0.1.1", "params": {"max_positions": 8}},
        recommendation={
            "trade_date": signal_date,
            "vt_symbol": "600000.SSE",
            "action": "BUY",
            "rank": 3,
            "total_score": 72.5,
            "reason": {"failed_rules": []},
        },
        signal_rows=[
            {
                "trade_date": execute_date,
                "signal_date": signal_date,
                "execute_date": execute_date,
                "vt_symbol": "600000.SSE",
                "side": "BUY",
                "price": 10.1,
                "score": 72.5,
                "reason": "entry_signal",
                "raw": {"status": "filled", "mode": "daily_close_proxy"},
            }
        ],
        order_rows=[
            {
                "id": 9,
                "trade_date": execute_date,
                "vt_symbol": "600000.SSE",
                "side": "BUY",
                "price": 10.1,
                "volume": 1000,
                "status": "filled",
                "reason": "entry_signal",
                "raw": {"mode": "daily_close_proxy"},
            }
        ],
        trade_rows=[
            {
                "id": 10,
                "trade_date": execute_date,
                "vt_symbol": "600000.SSE",
                "side": "BUY",
                "price": 10.1,
                "volume": 1000,
                "amount": 10_100,
                "fee": 3.03,
                "pnl": None,
                "reason": "entry_signal",
                "raw": {"mode": "daily_close_proxy"},
            }
        ],
        equity_row={"trade_date": execute_date, "cash": 989_897, "market_value": 10_100, "total_equity": 999_997, "position_count": 1},
        position_rows=[],
        stock_names={"600000.SSE": {"name": "浦发银行", "exchange": "SSE"}},
    )

    assert result["status"] == "filled"
    assert result["action"] == "BUY"
    assert result["planned_execute_date"] == "2026-01-06"
    assert result["linked_order_status"] == "filled"
    assert result["summary"] == "组合执行链路已按该信号日下单并成交。"
    assert result["equity"]["cash"] == 989_897
    assert result["trades"][0]["amount"] == 10_100


def test_candidate_trace_summary_uses_real_trade_without_signal_event() -> None:
    from alphaagent.server.services.backtest import engine

    signal_date = date(2026, 6, 12)
    execute_date = date(2026, 6, 15)
    result = engine._candidate_trace_summary(
        backtest_id=130,
        vt_symbol="002384.SZSE",
        signal_date=signal_date,
        run={"strategy_id": "mainline_dragon_pullback", "strategy_version": "0.1.8", "params": {"candidate_limit": 10}},
        recommendation=None,
        signal_rows=[],
        order_rows=[
            {
                "id": 18280,
                "trade_date": execute_date,
                "vt_symbol": "002384.SZSE",
                "side": "BUY",
                "price": 222.69,
                "volume": 400,
                "status": "filled",
                "reason": "entry_signal",
                "raw": {"signal_date": "2026-06-12", "execute_date": "2026-06-15"},
            }
        ],
        trade_rows=[
            {
                "id": 9149,
                "trade_date": execute_date,
                "vt_symbol": "002384.SZSE",
                "side": "BUY",
                "price": 222.69,
                "volume": 400,
                "amount": 89_076.0,
                "fee": 26.7,
                "pnl": None,
                "reason": "entry_signal",
                "raw": {"execution": {"signal_date": "2026-06-12", "execute_date": "2026-06-15"}},
            }
        ],
        equity_row={"trade_date": execute_date, "cash": 400_000, "market_value": 95_000, "total_equity": 1_500_000, "position_count": 10},
        position_rows=[],
        stock_names={"002384.SZSE": {"name": "东山精密", "exchange": "SZSE"}},
    )

    assert result["status"] == "filled"
    assert result["summary"] == "组合执行链路已按该信号日下单并成交。"
    assert result["planned_execute_date"] == "2026-06-15"
    assert result["linked_order_status"] == "filled"
    assert result["trades"][0]["vt_symbol"] == "002384.SZSE"


def test_candidate_trace_summary_explains_planned_signal_without_combined_fill() -> None:
    from alphaagent.server.services.backtest import engine

    signal_date = date(2026, 4, 14)
    execute_date = date(2026, 4, 15)
    result = engine._candidate_trace_summary(
        backtest_id=156,
        vt_symbol="002747.SZSE",
        signal_date=signal_date,
        run={"strategy_id": "mainline_dragon_pullback", "strategy_version": "0.1.9", "params": {"candidate_limit": 20, "max_positions": 10}},
        recommendation=None,
        signal_rows=[
            {
                "trade_date": execute_date,
                "signal_date": signal_date,
                "execute_date": execute_date,
                "vt_symbol": "002747.SZSE",
                "side": "BUY",
                "price": 21.12,
                "score": 79.4975,
                "reason": "entry_signal",
                "raw": {"status": "filled", "evidence": {"setup_type": "stealth_low_suction"}},
            }
        ],
        order_rows=[],
        trade_rows=[],
        equity_row={"trade_date": execute_date, "cash": 233_595.64, "market_value": 1_041_429.0, "total_equity": 1_275_024.64, "position_count": 10},
        position_rows=[],
        stock_names={"002747.SZSE": {"name": "埃斯顿", "exchange": "SZSE"}},
        not_planned_context={
            "target_signal_rank": 12,
            "target_signal_score": 79.4975,
            "target_signal_setup": "stealth_low_suction",
            "target_exceeds_candidate_limit": False,
            "candidate_limit": 20,
            "max_positions": 10,
            "signal_date_plan_count": 157,
            "signal_date_buy_plan_count": 157,
        },
    )

    assert result["status"] == "planned_not_ordered"
    assert result["not_planned_context"]["target_signal_rank"] == 12
    assert result["not_planned_context"]["target_signal_setup"] == "stealth_low_suction"
    assert "没有形成组合成交" in result["summary"]
    assert "候选独立买卖报告" in result["summary"]


def test_candidate_trace_summary_explains_planned_signal_outside_execution_limit() -> None:
    from alphaagent.server.services.backtest import engine

    signal_date = date(2026, 4, 28)
    execute_date = date(2026, 4, 29)
    result = engine._candidate_trace_summary(
        backtest_id=156,
        vt_symbol="002208.SZSE",
        signal_date=signal_date,
        run={"strategy_id": "mainline_dragon_pullback", "strategy_version": "0.1.9", "params": {"candidate_limit": 20, "max_positions": 10}},
        recommendation=None,
        signal_rows=[
            {
                "trade_date": execute_date,
                "signal_date": signal_date,
                "execute_date": execute_date,
                "vt_symbol": "002208.SZSE",
                "side": "BUY",
                "price": 12.66,
                "score": 77.3411,
                "reason": "entry_signal",
                "raw": {"status": "filled", "evidence": {"setup_type": "stealth_low_suction"}},
            }
        ],
        order_rows=[],
        trade_rows=[],
        equity_row={"trade_date": execute_date, "cash": 224_294.29, "market_value": 1_196_016.0, "total_equity": 1_420_310.29, "position_count": 8},
        position_rows=[],
        stock_names={"002208.SZSE": {"name": "合肥城建", "exchange": "SZSE"}},
        not_planned_context={
            "target_signal_rank": 31,
            "target_signal_score": 77.3411,
            "target_signal_setup": "stealth_low_suction",
            "target_exceeds_candidate_limit": True,
            "candidate_limit": 20,
            "max_positions": 10,
        },
    )

    assert result["status"] == "planned_not_ordered"
    assert result["not_planned_context"]["target_exceeds_candidate_limit"] is True
    assert "排名第 31" in result["summary"]
    assert "执行前 20 名" in result["summary"]


def test_candidate_trace_summary_explains_lane_execution_limit() -> None:
    from alphaagent.server.services.backtest import engine

    signal_date = date(2026, 4, 15)
    execute_date = date(2026, 4, 16)
    result = engine._candidate_trace_summary(
        backtest_id=200,
        vt_symbol="002747.SZSE",
        signal_date=signal_date,
        run={"strategy_id": "mainline_dragon_pullback", "strategy_version": "0.1.18", "params": {"candidate_limit": 20, "max_positions": 10}},
        recommendation=None,
        signal_rows=[
            {
                "trade_date": execute_date,
                "signal_date": signal_date,
                "execute_date": execute_date,
                "vt_symbol": "002747.SZSE",
                "side": "BUY",
                "price": 20.72,
                "score": 76.8804,
                "reason": "entry_signal",
                "raw": {
                    "status": "filled",
                    "evidence": {"setup_type": "stealth_low_suction"},
                    "candidate_execution": {
                        "execution_lane": "stealth_low_suction",
                        "raw_signal_rank": 455,
                        "execution_candidate_rank": None,
                        "execution_candidate_selected": False,
                        "execution_candidate_limit": 20,
                    },
                },
            }
        ],
        order_rows=[],
        trade_rows=[],
        equity_row={"trade_date": execute_date, "position_count": 7},
        position_rows=[],
        stock_names={"002747.SZSE": {"name": "埃斯顿", "exchange": "SZSE"}},
        not_planned_context={
            "target_signal_rank": 455,
            "target_signal_score": 76.8804,
            "target_signal_setup": "stealth_low_suction",
            "target_execution_lane": "stealth_low_suction",
            "target_raw_signal_rank": 455,
            "target_execution_candidate_rank": None,
            "target_execution_candidate_selected": False,
            "target_exceeds_candidate_limit": True,
            "candidate_limit": 20,
            "max_positions": 10,
        },
    )

    assert result["status"] == "planned_not_ordered"
    assert "低吸洗盘通道" in result["summary"]
    assert "执行前 20 名" in result["summary"]


def test_candidate_trace_summary_explains_lane_selected_but_unfilled() -> None:
    from alphaagent.server.services.backtest import engine

    signal_date = date(2026, 4, 28)
    execute_date = date(2026, 4, 29)
    result = engine._candidate_trace_summary(
        backtest_id=165,
        vt_symbol="002208.SZSE",
        signal_date=signal_date,
        run={"strategy_id": "mainline_dragon_pullback", "strategy_version": "0.1.18", "params": {"candidate_limit": 20, "max_positions": 10}},
        recommendation=None,
        signal_rows=[
            {
                "trade_date": execute_date,
                "signal_date": signal_date,
                "execute_date": execute_date,
                "vt_symbol": "002208.SZSE",
                "side": "BUY",
                "price": 12.79,
                "score": 77.3411,
                "reason": "entry_signal",
                "raw": {
                    "status": "filled",
                    "evidence": {"setup_type": "stealth_low_suction"},
                    "candidate_execution": {
                        "execution_lane": "stealth_low_suction",
                        "raw_signal_rank": 293,
                        "execution_candidate_rank": 8,
                        "execution_candidate_selected": True,
                        "execution_candidate_limit": 20,
                    },
                },
            }
        ],
        order_rows=[],
        trade_rows=[],
        equity_row={"trade_date": execute_date, "position_count": 10},
        position_rows=[],
        stock_names={"002208.SZSE": {"name": "合肥城建", "exchange": "SZSE"}},
        not_planned_context={
            "target_signal_rank": 48,
            "target_signal_score": 77.3411,
            "target_signal_setup": "stealth_low_suction",
            "target_execution_lane": "stealth_low_suction",
            "target_raw_signal_rank": 293,
            "target_execution_candidate_rank": 8,
            "target_execution_candidate_selected": True,
            "target_exceeds_candidate_limit": False,
            "candidate_limit": 20,
            "max_positions": 10,
        },
    )

    assert result["status"] == "planned_not_ordered"
    assert "执行池第 8 名" in result["summary"]
    assert "没有形成组合成交" in result["summary"]
    assert "超过组合执行前" not in result["summary"]


def test_candidate_trace_summary_explains_watch_not_bought() -> None:
    from alphaagent.server.services.backtest import engine

    result = engine._candidate_trace_summary(
        backtest_id=7,
        vt_symbol="600000.SSE",
        signal_date=date(2026, 1, 5),
        run={"strategy_id": "mainline_leader_pullback", "strategy_version": "0.1.1", "params": {"strict_entry": True}},
        recommendation={
            "trade_date": date(2026, 1, 5),
            "vt_symbol": "600000.SSE",
            "action": "WATCH",
            "rank": 12,
            "total_score": 66.0,
            "reason": {"failed_rules": ["ma5_distance"]},
        },
        signal_rows=[],
        order_rows=[],
        trade_rows=[],
        equity_row=None,
        position_rows=[],
        stock_names={"600000.SSE": {"name": "浦发银行", "exchange": "SSE"}},
    )

    assert result["status"] == "watch_not_bought"
    assert result["linked_order_status"] == "not_ordered"
    assert result["summary"] == "候选是 WATCH，默认组合执行不会买入观察股。"


def test_candidate_trace_summary_does_not_link_orders_without_signal_plan() -> None:
    from alphaagent.server.services.backtest import engine

    signal_date = date(2026, 1, 5)
    result = engine._candidate_trace_summary(
        backtest_id=7,
        vt_symbol="600000.SSE",
        signal_date=signal_date,
        run={"strategy_id": "mainline_leader_pullback", "strategy_version": "0.1.1", "params": {}},
        recommendation={
            "trade_date": signal_date,
            "vt_symbol": "600000.SSE",
            "action": "BUY",
            "rank": 1,
            "total_score": 88.0,
            "reason": {"failed_rules": []},
        },
        signal_rows=[],
        order_rows=[],
        trade_rows=[],
        equity_row={"trade_date": signal_date, "cash": 1_000_000, "market_value": 0, "total_equity": 1_000_000, "position_count": 0},
        position_rows=[],
        stock_names={"600000.SSE": {"name": "浦发银行", "exchange": "SSE"}},
        not_planned_context={
            "likely_reason": "before_first_signal_date",
            "likely_reason_label": "信号日早于该回测首个可复盘信号日 2026-03-31",
            "first_signal_date": "2026-03-31",
            "signal_date_plan_count": 0,
            "target_universe_rank": 3,
            "max_symbols": 80,
        },
    )

    assert result["status"] == "candidate_not_planned"
    assert result["linked_order_status"] == "not_ordered"
    assert result["planned_execute_date"] is None
    assert "首个可复盘信号日 2026-03-31" in result["summary"]
    assert result["not_planned_context"]["likely_reason"] == "before_first_signal_date"


def test_candidate_trace_summary_explains_candidate_skipped_by_theoretical_holding_state() -> None:
    from alphaagent.server.services.backtest import engine

    signal_date = date(2026, 6, 9)
    result = engine._candidate_trace_summary(
        backtest_id=194,
        vt_symbol="002384.SZSE",
        signal_date=signal_date,
        run={"strategy_id": "mainline_dragon_pullback", "strategy_version": "0.1.23", "params": {"candidate_limit": 20}},
        recommendation={
            "trade_date": signal_date,
            "vt_symbol": "002384.SZSE",
            "action": "BUY",
            "rank": 1,
            "total_score": 99.0425,
            "reason": {"entry_setup": "stealth_low_suction", "failed_rules": []},
        },
        signal_rows=[],
        order_rows=[],
        trade_rows=[],
        equity_row={"trade_date": signal_date, "cash": 655_356.47, "market_value": 1_098_993, "total_equity": 1_754_349.47, "position_count": 10},
        position_rows=[],
        stock_names={"002384.SZSE": {"name": "东山精密", "exchange": "SZSE"}},
        not_planned_context={
            "likely_reason": "not_in_same_day_plan",
            "likely_reason_label": "该股票不在该信号日理论计划中",
            "recommendation_rank": 1,
            "recommendation_action": "BUY",
            "recommendation_score": 99.0425,
            "target_theoretical_held_on_signal_date": True,
            "target_theoretical_entry_date": "2026-06-04",
            "target_real_held_on_signal_date": False,
            "candidate_limit": 20,
            "max_positions": 10,
        },
    )

    assert result["status"] == "candidate_not_planned"
    assert "理论信号标记层自 2026-06-04 起已持有该股" in result["summary"]
    assert "真实组合当日未持有" in result["summary"]


def test_candidate_trace_summary_explains_signal_snapshot_without_candidate_plan() -> None:
    from alphaagent.server.services.backtest import engine

    signal_date = date(2026, 4, 16)
    result = engine._candidate_trace_summary(
        backtest_id=203,
        vt_symbol="002747.SZSE",
        signal_date=signal_date,
        run={"strategy_id": "mainline_dragon_pullback", "strategy_version": "0.1.23", "params": {"candidate_limit": 20}},
        recommendation=None,
        signal_rows=[],
        order_rows=[],
        trade_rows=[],
        equity_row={"trade_date": signal_date, "cash": 540_000, "market_value": 1_100_000, "total_equity": 1_640_000, "position_count": 9},
        position_rows=[],
        stock_names={"002747.SZSE": {"name": "埃斯顿", "exchange": "SZSE"}},
        not_planned_context={
            "likely_reason": "not_in_persisted_candidates",
            "likely_reason_label": "未进入该日落库候选",
            "signal_snapshot": {
                "source": "dynamic_score",
                "trade_date": "2026-04-16",
                "vt_symbol": "002747.SZSE",
                "total_score": 79.5,
                "executable_entry_signal": True,
                "action": "BUY",
                "signal_label": "低吸启动买点",
                "entry_setup": "stealth_low_suction",
                "low_suction_days": 4,
            },
        },
    )

    assert result["status"] == "signal_snapshot_not_persisted"
    assert "只读逐日评分显示该日存在低吸启动买点" in result["summary"]
    assert "候选/理论计划链路没有对应记录" in result["summary"]
    assert result["not_planned_context"]["signal_snapshot"]["action"] == "BUY"


def test_candidate_trace_summary_prioritizes_theoretical_holding_over_signal_snapshot() -> None:
    from alphaagent.server.services.backtest import engine

    signal_date = date(2026, 4, 16)
    result = engine._candidate_trace_summary(
        backtest_id=203,
        vt_symbol="002747.SZSE",
        signal_date=signal_date,
        run={"strategy_id": "mainline_dragon_pullback", "strategy_version": "0.1.23", "params": {"candidate_limit": 20}},
        recommendation=None,
        signal_rows=[],
        order_rows=[],
        trade_rows=[],
        equity_row={"trade_date": signal_date, "position_count": 10},
        position_rows=[],
        stock_names={"002747.SZSE": {"name": "埃斯顿", "exchange": "SZSE"}},
        not_planned_context={
            "likely_reason": "not_in_persisted_candidates",
            "target_theoretical_held_on_signal_date": True,
            "target_theoretical_entry_date": "2026-04-14",
            "target_real_held_on_signal_date": False,
            "signal_snapshot": {
                "source": "quant_stock_signals",
                "trade_date": "2026-04-16",
                "vt_symbol": "002747.SZSE",
                "total_score": 76.6356,
                "executable_entry_signal": True,
                "action": "BUY",
                "signal_label": "低吸启动买点",
            },
        },
    )

    assert result["status"] == "candidate_not_planned"
    assert "信号快照显示该日存在 BUY" in result["summary"]
    assert "理论信号标记层自 2026-04-14 起已持有该股" in result["summary"]
    assert "真实组合当日未持有" in result["summary"]


def test_candidate_trace_summary_explains_untriggered_theoretical_signal() -> None:
    from alphaagent.server.services.backtest import engine

    signal_date = date(2026, 6, 3)
    execute_date = date(2026, 6, 4)
    result = engine._candidate_trace_summary(
        backtest_id=59,
        vt_symbol="002636.SZSE",
        signal_date=signal_date,
        run={"strategy_id": "mainline_leader_pullback", "strategy_version": "0.1.1", "params": {}},
        recommendation=None,
        signal_rows=[
            {
                "trade_date": execute_date,
                "signal_date": signal_date,
                "execute_date": execute_date,
                "vt_symbol": "002636.SZSE",
                "side": "BUY",
                "price": None,
                "score": 79.46,
                "reason": "entry_signal",
                "plan_status": "not_triggered",
                "plan_status_label": "理论未触发",
                "raw": {"status": "rejected", "reason": "tail_entry_not_triggered"},
            }
        ],
        order_rows=[],
        trade_rows=[],
        equity_row={"trade_date": execute_date, "cash": 1_000_000, "market_value": 0, "total_equity": 1_000_000, "position_count": 0},
        position_rows=[],
        stock_names={"002636.SZSE": {"name": "金安国纪", "exchange": "SZSE"}},
    )

    assert result["status"] == "not_triggered"
    assert result["plan_status"] == "not_triggered"
    assert result["linked_order_status"] == "not_ordered"
    assert "执行日 14:30 价格没有满足尾盘入场条件" in result["summary"]
    assert [item for item in result["diagnostics"] if item["id"] == "real_order"][0]["status"] == "info"


def test_signal_amount_preview_uses_equal_capital_budget(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    def fake_events(*args, **kwargs):
        del args, kwargs
        return {
            "status": "ready",
            "backtest_id": 5,
            "items": [
                {"trade_date": "2026-01-02", "vt_symbol": "600000.SSE", "side": "BUY", "price": 10.0},
                {"trade_date": "2026-01-10", "vt_symbol": "600000.SSE", "side": "SELL", "price": 12.0},
            ],
        }

    monkeypatch.setattr(engine, "backtest_signal_events", fake_events)

    result = engine.backtest_signal_amount_preview(5, capital=1_000_000, max_positions=8)

    assert result["per_trade_budget"] == 125_000
    assert result["items"][1]["preview_volume"] == 12_500
    assert result["items"][1]["preview_amount"] == 125_000
    assert result["items"][0]["preview_volume"] == 12_500
    assert result["items"][0]["preview_pnl"] == 25_000


def test_signal_amount_preview_filters_after_pairing_trades(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    def fake_events(*args, **kwargs):
        del args, kwargs
        return {
            "status": "ready",
            "backtest_id": 5,
            "items": [
                {"trade_date": "2026-01-02", "vt_symbol": "600000.SSE", "side": "BUY", "price": 10.0},
                {"trade_date": "2026-06-10", "vt_symbol": "600000.SSE", "side": "SELL", "price": 12.0},
            ],
        }

    monkeypatch.setattr(engine, "backtest_signal_events", fake_events)

    result = engine.backtest_signal_amount_preview(
        5,
        capital=1_000_000,
        max_positions=8,
        start=date(2026, 6, 1),
        side="SELL",
    )

    assert len(result["items"]) == 1
    assert result["items"][0]["side"] == "SELL"
    assert result["items"][0]["preview_volume"] == 12_500
    assert result["items"][0]["preview_pnl"] == 25_000


def test_signal_events_link_to_real_orders() -> None:
    from alphaagent.server.services.backtest import engine

    events = [
        {
            "trade_date": date(2026, 1, 6),
            "signal_date": date(2026, 1, 5),
            "execute_date": date(2026, 1, 6),
            "vt_symbol": "600000.SSE",
            "side": "BUY",
            "price": 10.0,
            "raw": {"mode": "daily_close_proxy"},
        }
    ]
    orders = [
        {
            "id": 88,
            "trade_date": date(2026, 1, 6),
            "vt_symbol": "600000.SSE",
            "side": "BUY",
            "status": "filled",
            "reason": "entry_signal",
            "price": 10.0,
            "volume": 1000,
        }
    ]

    linked = engine._link_signal_events_to_orders(events, orders)

    assert linked[0]["linked_order_id"] == 88
    assert linked[0]["linked_order_status"] == "filled"
    assert linked[0]["linked_order_reason"] == "entry_signal"
    assert linked[0]["raw"]["event_role"] == "theoretical_signal"
    assert linked[0]["raw"]["linked_order"]["volume"] == 1000


def test_signal_plan_module_links_orders_and_labels_untriggered_events() -> None:
    from alphaagent.server.services.backtest import signal_plan

    def as_date(value):
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))

    linked = signal_plan.link_signal_events_to_orders(
        [
            {
                "trade_date": "2026-01-06",
                "execute_date": "2026-01-06",
                "vt_symbol": "600000.SSE",
                "side": "BUY",
                "raw": {"status": "filled"},
            },
            {
                "trade_date": "2026-01-07",
                "execute_date": "2026-01-07",
                "vt_symbol": "000001.SZSE",
                "side": "BUY",
                "raw": {"status": "rejected", "reason": "tail_entry_not_triggered"},
            },
        ],
        [
            {
                "id": 88,
                "trade_date": "2026-01-06",
                "vt_symbol": "600000.SSE",
                "side": "BUY",
                "status": "filled",
                "reason": "entry_signal",
                "price": 10.0,
                "volume": 1000,
            }
        ],
        as_date=as_date,
    )

    assert linked[0]["linked_order_id"] == 88
    assert linked[0]["plan_status"] == "filled"
    assert linked[0]["plan_status_label"] == "已成交"
    assert linked[1]["linked_order_id"] is None
    assert linked[1]["plan_status"] == "not_triggered"
    assert linked[1]["plan_status_label"] == "理论未触发"
    assert linked[1]["raw"]["linked_order"] is None


def test_backtest_drilldown_options_include_signal_only_symbols_and_reason_labels() -> None:
    from alphaagent.server.services.backtest import engine

    dates = engine._backtest_drilldown_date_options(
        equity_rows=[
            {
                "trade_date": date(2026, 1, 6),
                "cash": 900_000,
                "market_value": 100_000,
                "total_equity": 1_000_000,
                "drawdown_pct": 0,
                "position_count": 1,
            }
        ],
        trade_rows=[
            {"trade_date": date(2026, 1, 6), "vt_symbol": "600000.SSE", "side": "BUY"},
        ],
        order_rows=[
            {
                "trade_date": date(2026, 1, 6),
                "vt_symbol": "002636.SZSE",
                "side": "BUY",
                "status": "rejected",
                "reason": "tail_entry_not_triggered",
            }
        ],
        signal_rows=[
            {
                "trade_date": date(2026, 1, 6),
                "signal_date": date(2026, 1, 5),
                "vt_symbol": "002636.SZSE",
                "side": "BUY",
                "raw": {"reason": "tail_entry_not_triggered"},
            },
        ],
        position_rows=[
            {"trade_date": date(2026, 1, 6), "vt_symbol": "600000.SSE"},
        ],
        recommendation_rows=[
            {"trade_date": date(2026, 1, 5), "vt_symbol": "002636.SZSE", "action": "BUY"},
            {"trade_date": date(2026, 1, 5), "vt_symbol": "600000.SSE", "action": "WATCH"},
        ],
    )
    symbols = engine._backtest_drilldown_symbol_options(
        trade_rows=[
            {"trade_date": date(2026, 1, 6), "vt_symbol": "600000.SSE", "side": "BUY"},
        ],
        order_rows=[
            {
                "trade_date": date(2026, 1, 6),
                "vt_symbol": "002636.SZSE",
                "side": "BUY",
                "status": "rejected",
                "reason": "tail_entry_not_triggered",
            }
        ],
        signal_rows=[
            {
                "trade_date": date(2026, 1, 6),
                "signal_date": date(2026, 1, 5),
                "vt_symbol": "002636.SZSE",
                "side": "BUY",
                "raw": {"reason": "tail_entry_not_triggered"},
            },
        ],
        position_rows=[
            {"trade_date": date(2026, 1, 6), "vt_symbol": "600000.SSE"},
        ],
        stock_names={
            "600000.SSE": {"name": "浦发银行", "exchange": "SSE"},
            "002636.SZSE": {"name": "金安国纪", "exchange": "SZSE"},
        },
    )

    assert dates[0]["trade_date"] == "2026-01-06"
    assert dates[0]["buy_trade_count"] == 1
    assert dates[0]["buy_candidate_count"] == 1
    assert dates[0]["watch_candidate_count"] == 1
    assert dates[0]["buy_signal_count"] == 1
    assert dates[0]["sell_signal_count"] == 0
    assert dates[0]["rejected_order_count"] == 1
    assert dates[0]["signal_event_count"] == 1
    assert dates[0]["position_snapshot_count"] == 1
    by_symbol = {row["vt_symbol"]: row for row in symbols}
    assert by_symbol["600000.SSE"]["status_label"] == "有成交"
    assert by_symbol["600000.SSE"]["main_reason_label"] is None
    assert by_symbol["002636.SZSE"]["status_label"] == "有拒单"
    assert by_symbol["002636.SZSE"]["buy_signal_count"] == 1
    assert by_symbol["002636.SZSE"]["main_reason_label"] == "尾盘入场未触发"
    assert engine.backtest_reason_label("insufficient_cash") == "现金不足"
    assert engine.backtest_reason_label("missing_1430_snapshot") == "缺14:30快照"


def test_backtest_sell_signal_executes_next_day_open_without_lookahead() -> None:
    from alphaagent.server.services.backtest import engine

    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)
    d2 = date(2026, 1, 3)
    d3 = date(2026, 1, 4)
    bars_by_symbol = {
        "600000.SSE": [
            engine.Bar(trade_date=d0, open_price=10.0, high_price=10.0, low_price=10.0, close_price=10.0),
            engine.Bar(trade_date=d1, open_price=10.0, high_price=10.1, low_price=9.9, close_price=10.0),
            engine.Bar(trade_date=d2, open_price=5.0, high_price=12.5, low_price=4.9, close_price=12.0),
            engine.Bar(trade_date=d3, open_price=13.0, high_price=13.2, low_price=12.8, close_price=13.1),
        ]
    }
    candidate = SignalScore(
        vt_symbol="600000.SSE",
        trade_date=d0,
        signal_type="mainline_leader_pullback",
        total_score=80,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "note": "unit_test_candidate", "ma5_distance_pct": 0.0},
    )
    params = engine.BacktestParams(
        strategy="mainline_leader_pullback",
        start=d0,
        end=d3,
        initial_cash=100_000,
        max_positions=1,
        max_position_pct=1.0,
        commission_rate=0.0,
        stamp_tax_rate=0.0,
        slippage_bps=0.0,
        take_profit_pct=0.1,
        stop_loss_pct=0.5,
        trailing_stop_pct=0.9,
        time_stop_days=999,
        execution_model="legacy_next_open",
        intraday_entry=False,
    )

    run = engine._simulate(
        None,
        params,
        bars_by_symbol,
        [d0, d1, d2, d3],
        {"600000.SSE": {"name": "测试股"}},
        score_cache={d0: [candidate], d2: []},
        minute_index={},
        score_context=engine.ScoreContext(),
    )

    sells = [trade for trade in run["trades"] if trade["side"] == "SELL"]
    assert len(sells) == 1
    assert sells[0]["trade_date"] == d3.isoformat()
    assert sells[0]["price"] == 13.0
    assert sells[0]["raw"]["signal_date"] == d2.isoformat()
    assert sells[0]["raw"]["mode"] == "daily_next_open_sell"
    assert not any(trade["side"] == "SELL" and trade["trade_date"] == d2.isoformat() for trade in run["trades"])

    pending_orders = [order for order in run["orders"] if order["side"] == "SELL" and order["status"] == "pending"]
    assert pending_orders[0]["trade_date"] == d2.isoformat()
    assert pending_orders[0]["raw"]["execute_date"] == d3.isoformat()


def test_backtest_tail_close_sell_signal_executes_next_trade_day_without_lookahead() -> None:
    from alphaagent.server.services.backtest import engine

    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)
    d2 = date(2026, 1, 3)
    d3 = date(2026, 1, 4)
    symbol = "600000.SSE"
    bars_by_symbol = {
        symbol: [
            engine.Bar(trade_date=d0, open_price=10.0, high_price=10.0, low_price=10.0, close_price=10.0),
            engine.Bar(trade_date=d1, open_price=10.0, high_price=10.1, low_price=9.9, close_price=10.0),
            engine.Bar(trade_date=d2, open_price=5.0, high_price=12.5, low_price=4.9, close_price=12.0),
            engine.Bar(trade_date=d3, open_price=13.0, high_price=13.2, low_price=12.8, close_price=13.1),
        ]
    }
    candidate = SignalScore(
        vt_symbol=symbol,
        trade_date=d0,
        signal_type="mainline_leader_pullback",
        total_score=80,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "note": "unit_test_candidate", "ma5_distance_pct": 0.0},
    )
    minute_index = {
        symbol: {
            d1: [
                engine.MinuteBar(
                    bar_time=datetime(2026, 1, 2, 14, 30),
                    trade_date=d1,
                    open_price=10.0,
                    high_price=10.0,
                    low_price=10.0,
                    close_price=10.0,
                )
            ],
            d2: [
                engine.MinuteBar(
                    bar_time=datetime(2026, 1, 3, 14, 30),
                    trade_date=d2,
                    open_price=6.0,
                    high_price=6.0,
                    low_price=6.0,
                    close_price=6.0,
                )
            ],
            d3: [
                engine.MinuteBar(
                    bar_time=datetime(2026, 1, 4, 14, 30),
                    trade_date=d3,
                    open_price=13.0,
                    high_price=13.0,
                    low_price=13.0,
                    close_price=13.0,
                )
            ],
        }
    }
    params = engine.BacktestParams(
        strategy="mainline_leader_pullback",
        start=d0,
        end=d3,
        initial_cash=100_000,
        max_positions=1,
        max_position_pct=1.0,
        commission_rate=0.0,
        stamp_tax_rate=0.0,
        slippage_bps=0.0,
        take_profit_pct=0.1,
        stop_loss_pct=0.5,
        trailing_stop_pct=0.9,
        time_stop_days=999,
        execution_model="tail_close_hybrid",
    )

    run = engine._simulate(
        None,
        params,
        bars_by_symbol,
        [d0, d1, d2, d3],
        {symbol: {"name": "测试股"}},
        score_cache={d0: [candidate], d2: []},
        minute_index=minute_index,
        score_context=engine.ScoreContext(),
    )

    sells = [trade for trade in run["trades"] if trade["side"] == "SELL"]
    assert len(sells) == 1
    assert sells[0]["trade_date"] == d3.isoformat()
    assert sells[0]["price"] == 13.1
    assert sells[0]["raw"]["signal_date"] == d2.isoformat()
    assert sells[0]["raw"]["execute_date"] == d3.isoformat()
    assert sells[0]["raw"]["mode"] == "daily_close_proxy_sell"
    assert not any(trade["side"] == "SELL" and trade["trade_date"] == d2.isoformat() for trade in run["trades"])

    pending_orders = [order for order in run["orders"] if order["side"] == "SELL" and order["status"] == "pending"]
    assert pending_orders[0]["trade_date"] == d2.isoformat()
    assert pending_orders[0]["raw"]["execute_date"] == d3.isoformat()


def test_backtest_persist_filters_api_only_order_fields() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.backtest import persistence

    row = {
        "trade_date": "2026-01-03",
        "vt_symbol": "600000.SSE",
        "board": "main",
        "board_label": "主板",
        "side": "SELL",
        "price": 13.0,
        "volume": 1000,
        "status": "filled",
        "reason": "take_profit",
        "raw": {"mode": "daily_next_open_sell"},
    }

    values = engine._table_values(engine.schema.backtest_orders, row)

    assert values == {
        "trade_date": date(2026, 1, 3),
        "vt_symbol": "600000.SSE",
        "side": "SELL",
        "price": 13.0,
        "volume": 1000,
        "status": "filled",
        "reason": "take_profit",
        "raw": {"mode": "daily_next_open_sell"},
    }
    assert values == persistence.table_values(engine.schema.backtest_orders, row)


def test_backtest_report_tables_pair_closed_trades_and_symbol_performance() -> None:
    from alphaagent.server.services.backtest import engine

    trades = [
        {
            "id": 1,
            "trade_date": date(2026, 1, 2),
            "vt_symbol": "600000.SSE",
            "name": "浦发银行",
            "side": "BUY",
            "price": 10.0,
            "volume": 1000,
            "amount": 10_000.0,
            "fee": 3.0,
            "pnl": None,
            "reason": "entry_signal",
            "raw": {},
        },
        {
            "id": 2,
            "trade_date": date(2026, 1, 9),
            "vt_symbol": "600000.SSE",
            "name": "浦发银行",
            "side": "SELL",
            "price": 11.0,
            "volume": 1000,
            "amount": 11_000.0,
            "fee": 8.8,
            "pnl": 991.2,
            "reason": "take_profit",
            "raw": {"entry_date": "2026-01-02"},
        },
        {
            "id": 3,
            "trade_date": date(2026, 1, 10),
            "vt_symbol": "000001.SZSE",
            "name": "平安银行",
            "side": "BUY",
            "price": 20.0,
            "volume": 500,
            "amount": 10_000.0,
            "fee": 3.0,
            "pnl": None,
            "reason": "entry_signal",
            "raw": {},
        },
        {
            "id": 4,
            "trade_date": date(2026, 1, 16),
            "vt_symbol": "000001.SZSE",
            "name": "平安银行",
            "side": "SELL",
            "price": 19.0,
            "volume": 500,
            "amount": 9_500.0,
            "fee": 7.6,
            "pnl": -507.6,
            "reason": "stop_loss",
            "raw": {"entry_date": "2026-01-10"},
        },
    ]

    closed = engine._closed_trades(trades)
    symbols = engine._symbol_performance(closed)
    stats = engine._extended_metrics(
        {"initial_cash": 100_000},
        closed,
        trades,
        [
            {"status": "filled"},
            {"status": "rejected", "reason": "limit_up_open_blocked"},
            {"status": "rejected", "reason": "missing_1430_snapshot", "raw": {"execution_model": "strict_1430", "reason": "missing_1430_snapshot"}},
            {"status": "rejected", "reason": "tail_entry_not_triggered", "raw": {"execution_model": "strict_1430", "price_source": "stock_minute_bars.close_price"}},
        ],
        [
            {"trade_date": date(2026, 1, 2), "market_value": 10_000, "total_equity": 100_000, "position_count": 1},
            {"trade_date": date(2026, 1, 9), "market_value": 0, "total_equity": 100_991.2, "position_count": 0},
        ],
    )

    assert len(closed) == 2
    assert closed[0]["name"] == "浦发银行"
    assert closed[0]["entry_price"] == 10.0
    assert closed[0]["holding_days"] == 7
    assert closed[1]["return_pct"] == -5.076
    assert symbols[0]["vt_symbol"] == "600000.SSE"
    assert symbols[0]["name"] == "浦发银行"
    assert symbols[0]["pnl"] == 991.2
    assert stats["closed_trade_count"] == 2
    assert stats["rejected_order_count"] == 3
    assert stats["strict_1430_rejected_count"] == 2
    assert stats["minute_gap_rejected_count"] == 1
    assert stats["tail_entry_rejected_count"] == 1
    assert stats["average_holding_days"] == 6.5


def test_backtest_metrics_report_open_buys_separately_from_closed_trades() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.backtest.schemas import Trade

    equity = [
        {"trade_date": date(2026, 1, 2), "total_equity": 100_000.0},
        {"trade_date": date(2026, 1, 3), "total_equity": 101_000.0},
    ]
    trades = [
        Trade(date(2026, 1, 2), "600000.SSE", "BUY", 10.0, 1000, 10_000.0, 3.0, raw={"execution": {"mode": "minute_1430"}}),
        Trade(date(2026, 1, 3), "000001.SZSE", "BUY", 20.0, 500, 10_000.0, 3.0, raw={"execution": {"mode": "minute_1430"}}),
        Trade(date(2026, 1, 3), "600000.SSE", "SELL", 11.0, 1000, 11_000.0, 8.8, pnl=991.2),
    ]

    metrics = engine._metrics(100_000, equity, trades)

    assert metrics["total_trade_rows"] == 3
    assert metrics["buy_count"] == 2
    assert metrics["sell_count"] == 1
    assert metrics["trade_count"] == 1
    assert metrics["open_trade_count"] == 1
    assert metrics["minute_1430_count"] == 2


def test_persist_run_uses_registered_strategy_version(monkeypatch) -> None:
    from alphaagent.server.db import schema
    from alphaagent.server.services.backtest import persistence
    from alphaagent.server.services.backtest.schemas import BacktestParams

    captured_runs: list[dict] = []

    class FakeInsertResult:
        def __init__(self, statement):
            self.statement = statement

        def scalar_one(self):
            captured_runs.append(dict(self.statement.compile().params))
            return 99

    class FakeSession:
        def execute(self, statement):
            if getattr(statement, "table", None) is schema.backtest_runs:
                return FakeInsertResult(statement)
            return None

    run = {
        "metrics": {"initial_cash": 100_000, "final_equity": 100_000},
        "equity": [],
        "positions": [],
        "signal_events": [],
        "orders": [],
        "trades": [],
    }

    backtest_id = persistence.persist_run(
        FakeSession(),
        BacktestParams(strategy="limit_up_after_pullback", start=date(2026, 2, 2)),
        run,
        date(2026, 6, 13),
        params_to_json=lambda params: {"strategy": params.strategy},
    )

    assert backtest_id == 99
    assert captured_runs[0]["strategy_id"] == "limit_up_after_pullback"
    assert captured_runs[0]["strategy_version"] == "0.1.0"


def test_backtest_audit_events_keep_stock_names() -> None:
    from alphaagent.server.services.backtest import engine

    events = engine._audit_events(
        [
            {
                "trade_date": "2026-01-02",
                "vt_symbol": "600000.SSE",
                "name": "浦发银行",
                "side": "BUY",
                "price": 10.0,
                "volume": 1000,
                "status": "filled",
                "reason": "entry_signal",
                "raw": {"execution": {"mode": "minute_tail_ma5"}},
            }
        ],
        [
            {
                "trade_date": "2026-01-02",
                "vt_symbol": "600000.SSE",
                "name": "浦发银行",
                "side": "BUY",
                "price": 10.0,
                "volume": 1000,
                "pnl": None,
                "reason": "entry_signal",
                "raw": {"execution": {"mode": "minute_tail_ma5"}},
            }
        ],
    )

    assert events[0]["name"] == "浦发银行"
    assert events[1]["name"] == "浦发银行"
    assert events[0]["reason_label"] == "买入信号"
    assert events[1]["reason_label"] == "买入信号"


def test_backtest_audit_events_include_precise_rejection_label_and_message() -> None:
    from alphaagent.server.services.backtest import engine

    events = engine._audit_events(
        [
            {
                "trade_date": "2025-12-31",
                "vt_symbol": "002536.SZSE",
                "side": "BUY",
                "price": 29.7,
                "volume": 0,
                "status": "rejected",
                "reason": "tail_entry_not_triggered",
                "raw": {
                    "mode": "strict_1430_required",
                    "price": 29.7,
                    "ma5": 31.744,
                    "ma5_distance_pct": -6.439012096774199,
                    "signal_date": "2025-12-30",
                    "execute_date": "2025-12-31",
                },
            }
        ],
        [],
    )

    assert events[0]["reason_label"] == "尾盘入场未触发"
    assert "执行价 29.7" in events[0]["message"]
    assert "信号日MA5 31.744" in events[0]["message"]
    assert "距MA5 -6.44%" in events[0]["message"]


def test_backtest_monthly_returns_and_order_stats_are_report_ready() -> None:
    from alphaagent.server.services.backtest import engine

    monthly = engine._monthly_returns(
        [
            {"trade_date": date(2026, 1, 2), "total_equity": 100_000},
            {"trade_date": date(2026, 1, 31), "total_equity": 110_000},
            {"trade_date": date(2026, 2, 1), "total_equity": 108_000},
            {"trade_date": date(2026, 2, 28), "total_equity": 120_000},
        ]
    )
    orders = engine._order_stats(
        [
            {"trade_date": date(2026, 1, 2), "vt_symbol": "600000.SSE", "side": "BUY", "status": "filled", "reason": "entry_signal"},
            {"trade_date": date(2026, 1, 3), "vt_symbol": "000001.SZSE", "side": "BUY", "status": "rejected", "reason": "limit_up_open_blocked"},
        ]
    )

    assert monthly == [
        {
            "month": "2026-01",
            "start_date": "2026-01-02",
            "end_date": "2026-01-31",
            "start_equity": 100_000,
            "end_equity": 110_000,
            "return_pct": 10.000000000000009,
            "max_drawdown_pct": 0.0,
        },
        {
            "month": "2026-02",
            "start_date": "2026-02-01",
            "end_date": "2026-02-28",
            "start_equity": 110_000,
            "end_equity": 120_000,
            "return_pct": 9.090909090909083,
            "max_drawdown_pct": -1.8181818181818188,
        },
    ]
    assert orders["total"] == 2
    assert orders["by_status"] == {"filled": 1, "rejected": 1}
    assert orders["by_reason"]["limit_up_open_blocked"] == 1
    assert orders["rejected_examples"][0]["trade_date"] == "2026-01-03"


def test_backtest_benchmark_and_period_analysis_are_report_ready() -> None:
    from alphaagent.server.services.backtest import engine

    sample_bars = [
        {"vt_symbol": "600000.SSE", "trade_date": date(2026, 1, 1), "close_price": 10.0},
        {"vt_symbol": "600000.SSE", "trade_date": date(2026, 1, 2), "close_price": 11.0},
        {"vt_symbol": "600000.SSE", "trade_date": date(2026, 1, 3), "close_price": 12.1},
        {"vt_symbol": "000001.SZSE", "trade_date": date(2026, 1, 1), "close_price": 20.0},
        {"vt_symbol": "000001.SZSE", "trade_date": date(2026, 1, 2), "close_price": 19.0},
        {"vt_symbol": "000001.SZSE", "trade_date": date(2026, 1, 3), "close_price": 20.9},
    ]
    equity = [
        {"trade_date": date(2026, 1, 1), "total_equity": 100_000},
        {"trade_date": date(2026, 1, 2), "total_equity": 102_000},
        {"trade_date": date(2026, 1, 3), "total_equity": 104_000},
    ]
    closed = [
        {"exit_date": "2026-01-02", "pnl": 500.0},
        {"exit_date": "2026-01-03", "pnl": -100.0},
    ]

    curve = engine._sample_equal_weight_curve(sample_bars)
    report = engine._benchmark_report(equity, curve)
    periods = engine._period_analysis(equity, closed, curve)

    assert len(curve) == 3
    assert curve[0]["nav"] == 1.0
    assert round(curve[1]["daily_return"], 4) == 0.025
    assert report["benchmarks"][0]["id"] == "sample_equal_weight"
    assert report["benchmarks"][0]["status"] == "ready"
    assert periods["status"] == "ready"
    assert periods["periods"][0]["id"] == "in_sample"
    assert periods["periods"][1]["id"] == "out_of_sample"
    assert periods["periods"][1]["benchmark_return_pct"] is not None


def test_index_benchmark_curve_from_bars_is_report_ready() -> None:
    from alphaagent.server.services.backtest import engine

    curve = engine._bars_nav_curve(
        [
            {"trade_date": "2026-01-01", "close": 100},
            {"trade_date": "2026-01-02", "close": 110},
            {"trade_date": "2026-01-03", "close": 99},
        ],
        date(2026, 1, 1),
        date(2026, 1, 3),
    )
    report = engine._benchmark_report(
        [{"trade_date": date(2026, 1, 1), "total_equity": 100_000}, {"trade_date": date(2026, 1, 3), "total_equity": 105_000}],
        [],
        [{"id": "index_000300_sse", "name": "沪深300", "source": "test", "curve": curve}],
    )

    assert len(curve) == 3
    assert round(curve[-1]["nav"], 4) == 0.99
    assert report["benchmarks"][0]["id"] == "index_000300_sse"
    assert report["benchmarks"][0]["status"] == "ready"
    assert round(report["benchmarks"][0]["return_pct"], 4) == -1.0


def test_backtest_regime_analysis_and_csv_are_report_ready() -> None:
    from alphaagent.server.services.backtest import engine

    equity = [
        {"trade_date": date(2026, 1, 1) + timedelta(days=index), "total_equity": 100_000 + index * 1_000}
        for index in range(60)
    ]
    benchmark_curve = []
    nav = 1.0
    for index in range(60):
        daily_return = 0.01 if index < 20 else -0.004 if index < 40 else 0.001
        nav *= 1 + daily_return
        benchmark_curve.append(
            {
                "trade_date": date(2026, 1, 1) + timedelta(days=index),
                "nav": nav,
                "daily_return": daily_return,
                "member_count": 2,
            }
        )
    closed = [
        {"exit_date": "2026-01-10", "pnl": 1000.0},
        {"exit_date": "2026-01-30", "pnl": -500.0},
        {"exit_date": "2026-02-20", "pnl": 700.0},
    ]

    regimes = engine._regime_analysis(equity, closed, benchmark_curve)
    report = {
        "backtest_id": 7,
        "strategy_id": "mainline_leader_pullback",
        "strategy_version": "0.1.0",
        "start_date": "2026-01-01",
        "end_date": "2026-03-01",
        "assumptions": {"execution": "D close signal, D+1 open simulated fill"},
        "summary_rows": [{"label": "总收益率", "value": 10.0}],
        "sample": {"symbol_count": 2, "bar_count": 120},
        "extended_metrics": {"trade_count": 3},
        "benchmark": {"benchmarks": [{"id": "sample_equal_weight", "status": "ready", "return_pct": 8.0}]},
        "period_analysis": {"periods": []},
        "regime_analysis": regimes,
        "monthly_returns": [],
        "symbol_performance": [],
        "worst_trades": [],
        "trades": [{"trade_date": "2026-01-02", "vt_symbol": "600000.SSE", "side": "BUY"}],
        "closed_trades": closed,
        "order_stats": {"by_status": {"filled": 1}, "by_reason": {"entry_signal": 1}, "rejected_examples": []},
        "data_quality": {"stocks": {"count": 2}, "limitations": ["数据限制"]},
        "limitations": ["回测限制"],
    }

    csv_content = engine._report_csv_content(report)

    assert regimes["status"] == "ready"
    assert {item["regime"] for item in regimes["periods"]} >= {"strong", "choppy"}
    assert csv_content.startswith("\ufeff")
    assert "## 核心指标" in csv_content
    assert "## 市场环境分段" in csv_content
    assert "## 交易明细" in csv_content
    assert "回测限制" in csv_content


def test_backtest_robustness_checks_are_report_ready() -> None:
    from alphaagent.server.services.backtest import engine

    equity = [
        {"trade_date": date(2025, 12, 30), "total_equity": 100_000},
        {"trade_date": date(2025, 12, 31), "total_equity": 101_000},
        {"trade_date": date(2026, 1, 2), "total_equity": 103_000},
        {"trade_date": date(2026, 1, 5), "total_equity": 104_000},
    ]
    closed = [
        {"exit_date": "2025-12-31", "pnl": 1000.0},
        {"exit_date": "2026-01-05", "pnl": 1200.0},
    ]
    trades = [
        {"side": "BUY", "amount": 10_000.0},
        {"side": "SELL", "amount": 11_000.0},
    ]
    sample_bars = [
        {"vt_symbol": "600000.SSE", "trade_date": date(2025, 12, 30), "close_price": 10.0},
        {"vt_symbol": "600000.SSE", "trade_date": date(2025, 12, 31), "close_price": 11.0},
        {"vt_symbol": "600000.SSE", "trade_date": date(2026, 1, 2), "close_price": 12.0},
        {"vt_symbol": "000001.SZSE", "trade_date": date(2025, 12, 30), "close_price": 20.0},
        {"vt_symbol": "000001.SZSE", "trade_date": date(2025, 12, 31), "close_price": 19.0},
        {"vt_symbol": "000001.SZSE", "trade_date": date(2026, 1, 2), "close_price": 21.0},
    ]
    benchmark = engine._sample_equal_weight_curve(sample_bars)

    checks = engine._robustness_checks(
        {"initial_cash": 100_000, "final_equity": 104_000, "total_return_pct": 4.0},
        equity,
        closed,
        trades,
        sample_bars,
        benchmark,
    )
    csv_content = engine._report_csv_content(
        {
            "backtest_id": 8,
            "strategy_id": "mainline_leader_pullback",
            "strategy_version": "0.1.0",
            "start_date": "2025-12-30",
            "end_date": "2026-01-05",
            "assumptions": {"execution": "test"},
            "summary_rows": [],
            "sample": {},
            "extended_metrics": {},
            "benchmark": {"benchmarks": []},
            "period_analysis": {"periods": []},
            "regime_analysis": {"periods": []},
            "robustness_checks": checks,
            "monthly_returns": [],
            "symbol_performance": [],
            "worst_trades": [],
            "trades": [],
            "closed_trades": [],
            "order_stats": {"by_status": {}, "by_reason": {}, "rejected_examples": []},
            "data_quality": {},
            "limitations": [],
        }
    )

    assert checks["status"] == "ready"
    assert len(checks["yearly_periods"]) == 2
    assert checks["cost_stress"][-1]["id"] == "high_friction"
    assert checks["random_baseline"]["status"] == "ready"
    assert {item["id"] for item in checks["diagnostics"]} >= {"high_friction_positive", "random_baseline_excess"}
    assert next(item for item in checks["diagnostics"] if item["id"] == "calendar_periods_positive")["value_type"] == "count"
    assert "## 年度分段" in csv_content
    assert "## 成本压力测试" in csv_content
    assert "## 反过拟合诊断" in csv_content


def test_backtest_yearly_periods_include_win_rate_and_benchmark_excess() -> None:
    from alphaagent.server.services.backtest import engine

    equity = [
        {"trade_date": date(2025, 12, 30), "total_equity": 100_000},
        {"trade_date": date(2025, 12, 31), "total_equity": 101_000},
        {"trade_date": date(2026, 1, 2), "total_equity": 103_000},
        {"trade_date": date(2026, 1, 5), "total_equity": 104_000},
    ]
    closed = [
        {"exit_date": "2025-12-31", "pnl": 1000.0},
        {"exit_date": "2026-01-05", "pnl": -300.0},
    ]
    benchmark_curve = [
        {"trade_date": date(2025, 12, 30), "nav": 1.0},
        {"trade_date": date(2025, 12, 31), "nav": 1.01},
        {"trade_date": date(2026, 1, 2), "nav": 1.02},
        {"trade_date": date(2026, 1, 5), "nav": 1.01},
    ]

    yearly = engine._calendar_period_analysis(equity, closed, benchmark_curve)

    assert {row["id"] for row in yearly} == {"2025", "2026"}
    assert all("return_pct" in row for row in yearly)
    assert all("max_drawdown_pct" in row for row in yearly)
    assert all("trade_count" in row for row in yearly)
    assert all("win_rate" in row for row in yearly)
    assert all("benchmark_return_pct" in row for row in yearly)
    assert all("excess_return_pct" in row for row in yearly)


def test_backtest_robustness_checks_include_market_regime_concentration() -> None:
    from alphaagent.server.services.backtest import engine

    start = date(2026, 1, 1)
    equity = []
    benchmark_curve = []
    equity_value = 100_000.0
    benchmark_nav = 1.0
    for index in range(60):
        trade_date = start + timedelta(days=index)
        if index < 20:
            benchmark_nav *= 1.004
            equity_value *= 1.003
        elif index < 40:
            benchmark_nav *= 0.997
            equity_value *= 1.001
        else:
            benchmark_nav *= 1.0005
            equity_value *= 1.0008
        equity.append({"trade_date": trade_date, "total_equity": equity_value})
        benchmark_curve.append({"trade_date": trade_date, "nav": benchmark_nav})
    closed = [
        {"exit_date": "2026-01-10", "pnl": 500.0},
        {"exit_date": "2026-01-30", "pnl": 200.0},
        {"exit_date": "2026-02-20", "pnl": -100.0},
    ]

    checks = engine._robustness_checks(
        {"initial_cash": 100_000, "final_equity": equity[-1]["total_equity"], "total_return_pct": 5.0},
        equity,
        closed,
        [{"side": "BUY", "amount": 10_000.0}, {"side": "SELL", "amount": 10_500.0}],
        [],
        benchmark_curve,
    )

    diagnostic_ids = {item["id"] for item in checks["diagnostics"]}

    assert len(checks["market_regime_periods"]) >= 2
    assert {"market_regime_positive", "weak_market_usability", "market_regime_return_concentration"} <= diagnostic_ids


def test_backtest_validation_grid_summary_and_csv_are_report_ready() -> None:
    from alphaagent.server.services.backtest import engine

    rows = [
        {
            "variant_id": 1,
            "is_base_params": True,
            "min_entry_score": 68.0,
            "stop_loss_pct": 0.07,
            "take_profit_pct": 0.18,
            "strict_entry": True,
            "total_return_pct": 10.0,
            "out_sample_return_pct": 4.0,
            "sample_equal_weight_excess_pct": -2.0,
            "high_friction_return_pct": 8.0,
            "max_drawdown_pct": -5.0,
        },
        {
            "variant_id": 2,
            "is_base_params": False,
            "min_entry_score": 64.0,
            "stop_loss_pct": 0.05,
            "take_profit_pct": 0.14,
            "strict_entry": False,
            "total_return_pct": -1.0,
            "out_sample_return_pct": -2.0,
            "sample_equal_weight_excess_pct": -5.0,
            "high_friction_return_pct": -3.0,
            "max_drawdown_pct": -8.0,
        },
    ]
    summary = engine._validation_grid_summary(rows)
    diagnostics = engine._validation_grid_diagnostics(summary)
    grid = {
        "status": "ready",
        "backtest_id": 9,
        "strategy": "mainline_leader_pullback",
        "strategy_version": "0.1.0",
        "start_date": "2026-01-01",
        "end_date": "2026-03-01",
        "method": "full_resimulation_parameter_grid",
        "variant_count": 2,
        "param_space": {"min_entry_score": [64.0, 68.0]},
        "summary": summary,
        "diagnostics": diagnostics,
        "walk_forward": {
            "summary": {"fold_count": 1, "positive_test_ratio": 100.0},
            "diagnostics": [{"id": "walk_forward_positive_ratio", "status": "pass"}],
            "folds": [{"id": "fold_1", "test_return_pct": 3.0}],
        },
        "top_variants": rows[:1],
        "rows": rows,
        "limitations": ["日线限制"],
    }

    csv_content = engine._validation_grid_csv_content(grid)

    assert summary["positive_ratio"] == 50.0
    assert summary["base_variant_id"] == 1
    assert summary["base_out_sample_rank"] == 1
    assert {item["id"] for item in diagnostics} >= {"grid_positive_ratio", "base_out_sample_rank"}
    assert "## 参数网格摘要" in csv_content
    assert "## Walk Forward 汇总" in csv_content
    assert "## Walk Forward 折叠" in csv_content
    assert "## 全部参数组合" in csv_content
    assert "full_resimulation_parameter_grid" in csv_content


def test_backtest_walk_forward_selects_train_variant_then_scores_future_window() -> None:
    from alphaagent.server.services.backtest import engine

    dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(100)]

    def equity_curve(train_return: float, test_return: float) -> list[dict[str, object]]:
        rows = []
        for index, trade_date in enumerate(dates):
            if index < 60:
                equity = 100_000 * (1 + train_return * index / 59)
            else:
                equity = 100_000 * (1 + train_return) * (1 + test_return * (index - 59) / 20)
            rows.append({"trade_date": trade_date, "total_equity": equity})
        return rows

    benchmark = []
    nav = 1.0
    for trade_date in dates:
        benchmark.append({"trade_date": trade_date, "nav": nav, "daily_return": 0.0, "member_count": 1})
        nav *= 1.001

    variant_runs = [
        {
            "variant_id": 1,
            "params": engine.BacktestParams(min_entry_score=64, stop_loss_pct=0.05, take_profit_pct=0.18, strict_entry=False),
            "equity": equity_curve(0.20, -0.03),
            "closed_trades": [{"exit_date": dates[70].isoformat(), "pnl": -100.0}],
        },
        {
            "variant_id": 2,
            "params": engine.BacktestParams(min_entry_score=68, stop_loss_pct=0.07, take_profit_pct=0.18, strict_entry=True),
            "equity": equity_curve(0.05, 0.04),
            "closed_trades": [{"exit_date": dates[70].isoformat(), "pnl": 200.0}],
        },
    ]

    analysis = engine._walk_forward_grid_analysis(variant_runs, benchmark, train_days=60, test_days=20, step_days=20)

    assert analysis["status"] == "ready"
    assert analysis["summary"]["fold_count"] == 2
    assert analysis["folds"][0]["selected_variant_id"] == 1
    assert analysis["folds"][0]["test_return_pct"] < 0
    assert {item["id"] for item in analysis["diagnostics"]} >= {"walk_forward_positive_ratio", "walk_forward_excess_ratio"}


def test_backtest_validation_grid_small_limit_includes_base_params() -> None:
    from alphaagent.server.services.backtest import engine

    base_params = engine.BacktestParams(
        min_entry_score=68.0,
        stop_loss_pct=0.07,
        take_profit_pct=0.18,
        strict_entry=True,
    )
    variants = engine._validation_param_variants(base_params, 3)

    assert len(variants) == 3
    assert any(engine._same_grid_params(item, base_params) for item in variants)


def test_backtest_validation_grid_reuses_minute_index(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    calls = {"minute_loads": 0}
    trading_days = [date(2026, 1, 1) + timedelta(days=index) for index in range(85)]
    bars_by_symbol = {"600000.SSE": _bars(85)}

    def fake_minute_index(session, vt_symbols, start, end, interval="1m"):
        del session, vt_symbols, start, end
        assert interval == "1m"
        calls["minute_loads"] += 1
        return {}

    def fake_simulate(session, params, bars_by_symbol_arg, trading_days_arg, stock_meta, score_cache=None, minute_index=None, score_context=None):
        del session, params, bars_by_symbol_arg, stock_meta, score_cache, score_context
        assert minute_index == {}
        return {
            "metrics": {
                "initial_cash": 100_000,
                "final_equity": 101_000,
                "total_return_pct": 1.0,
                "annual_return_pct": 3.0,
                "max_drawdown_pct": -1.0,
                "trade_count": 1,
                "win_rate": 1.0,
                "profit_factor": 2.0,
                "sharpe": 1.0,
            },
            "equity": [{"trade_date": item, "total_equity": 100_000 + index} for index, item in enumerate(trading_days_arg)],
            "trades": [],
            "orders": [],
        }

    monkeypatch.setattr(engine, "_load_minute_bar_index", fake_minute_index)
    monkeypatch.setattr(engine, "_simulate", fake_simulate)

    result = engine._run_validation_grid(
        session=None,
        backtest_id=9,
        base_params=engine.BacktestParams(intraday_entry=True, minute_interval="1m"),
        bars_by_symbol=bars_by_symbol,
        trading_days=trading_days,
        stock_meta={},
        max_variants=3,
    )

    assert result["status"] == "ready"
    assert result["variant_count"] == 3
    assert calls["minute_loads"] == 1


def test_financial_scores_from_context_respects_publish_date() -> None:
    from alphaagent.server.services.backtest import engine

    context = engine.ScoreContext(
        financial_rows_by_symbol={
            "600000.SSE": [
                {
                    "vt_symbol": "600000.SSE",
                    "report_date": "2026-03-31",
                    "publish_date": "2026-04-30",
                    "revenue_yoy": 30.0,
                    "net_profit_yoy": 40.0,
                    "operating_cash_flow": 10_000_000,
                    "cash_flow_quality": 2.0,
                },
                {
                    "vt_symbol": "600000.SSE",
                    "report_date": "2025-12-31",
                    "publish_date": "2026-03-31",
                    "revenue_yoy": 5.0,
                    "net_profit_yoy": 5.0,
                },
            ]
        }
    )

    before_publish = engine._financial_scores_from_context(context, date(2026, 4, 15))
    after_publish = engine._financial_scores_from_context(context, date(2026, 5, 1))

    assert before_publish["600000.SSE"] < after_publish["600000.SSE"]


def test_symbol_financial_coverage_summary_uses_publish_date_cutoff() -> None:
    from alphaagent.server.services.quant import financials

    rows = [
        {"publish_date": "2026-05-01", "report_date": "2026-03-31", "period_type": "quarterly"},
        {"publish_date": "2026-03-30", "report_date": "2025-12-31", "period_type": "quarterly"},
        {"publish_date": None, "report_date": "2025-09-30", "period_type": "quarterly"},
    ]

    class FakeRows:
        def mappings(self):
            return self

        def all(self):
            return rows

    class FakeSession:
        def execute(self, statement):
            del statement
            return FakeRows()

    summary = financials.financial_coverage_summary(FakeSession(), "600000.SSE", date(2026, 4, 15))

    assert summary["local_report_count"] == 3
    assert summary["usable_report_count"] == 1
    assert summary["missing_publish_date_count"] == 1
    assert summary["future_publish_date_count"] == 1
    assert summary["latest_publish_date"] == "2026-05-01"
    assert summary["latest_usable_publish_date"] == "2026-03-30"
    assert summary["latest_usable_report_date"] == "2025-12-31"
    assert "publish_date <= trade_date" in summary["policy"]


def test_backtest_validation_grid_csv_endpoint_returns_download(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    monkeypatch.setattr(
        backtests,
        "backtest_validation_grid_csv",
        lambda backtest_id, max_variants: {
            "status": "ready",
            "filename": f"alphaagent_validation_grid_{backtest_id}.csv",
            "content": "\ufeff## 参数网格摘要\n",
        },
    )

    client = TestClient(create_app())
    response = client.get("/api/backtests/9/validation-grid.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "alphaagent_validation_grid_9.csv" in response.headers["content-disposition"]
    assert "## 参数网格摘要" in response.text


def test_backtest_csv_endpoint_returns_download(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    monkeypatch.setattr(
        backtests,
        "backtest_report_csv",
        lambda backtest_id, trade_limit: {
            "status": "ready",
            "filename": f"alphaagent_backtest_{backtest_id}.csv",
            "content": "\ufeff## 回测摘要\n",
        },
    )

    client = TestClient(create_app())
    response = client.get("/api/backtests/9/report.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "alphaagent_backtest_9.csv" in response.headers["content-disposition"]
    assert "## 回测摘要" in response.text


def test_backtest_report_api_defaults_to_light_report(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    calls = []

    def fake_report(backtest_id, trade_limit, *, include_analysis=False):
        calls.append(
            {
                "backtest_id": backtest_id,
                "trade_limit": trade_limit,
                "include_analysis": include_analysis,
            }
        )
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "benchmark": {"status": "ready"} if include_analysis else None,
        }

    monkeypatch.setattr(backtests, "backtest_report", fake_report)

    client = TestClient(create_app())
    light_response = client.get("/api/backtests/9/report?trade_limit=80")
    full_response = client.get("/api/backtests/9/report?trade_limit=80&include_analysis=true")

    assert light_response.status_code == 200
    assert light_response.json()["data"]["benchmark"] is None
    assert full_response.status_code == 200
    assert full_response.json()["data"]["benchmark"]["status"] == "ready"
    assert calls == [
        {"backtest_id": 9, "trade_limit": 80, "include_analysis": False},
        {"backtest_id": 9, "trade_limit": 80, "include_analysis": True},
    ]


def test_backtest_api_parses_strict_minute_entry_params(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_run_backtest(params):
        captured["params"] = params
        return {"status": "ready", "backtest_id": 10, "metrics": {}, "trades": [], "start": "2026-01-01", "end": "2026-01-31"}

    monkeypatch.setattr(backtests, "run_backtest", fake_run_backtest)

    client = TestClient(create_app())
    response = client.post(
        "/api/backtests",
            json={
                "start": "2026-01-01",
                "execution_model": "strict_1430",
                "intraday_entry": "false",
                "minute_entry_required": "false",
                "minute_interval": "1m",
                "tail_entry_start": "14:30",
                "tail_entry_end": "14:30",
                "tail_entry_ma5_tolerance_pct": 0.8,
                "persist": False,
            },
    )

    assert response.status_code == 200
    assert captured["params"].execution_model == "strict_1430"
    assert captured["params"].intraday_entry is True
    assert captured["params"].minute_entry_required is True
    assert captured["params"].minute_interval == "1m"
    assert captured["params"].tail_entry_start == "14:30"
    assert captured["params"].tail_entry_end == "14:30"
    assert captured["params"].tail_entry_ma5_tolerance_pct == 0.8


def test_backtest_api_derives_tail_hybrid_flags_from_execution_model(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_run_backtest(params):
        captured["params"] = params
        return {"status": "ready", "backtest_id": 10, "metrics": {}, "trades": [], "start": "2026-01-01", "end": "2026-01-31"}

    monkeypatch.setattr(backtests, "run_backtest", fake_run_backtest)

    client = TestClient(create_app())
    response = client.post(
        "/api/backtests",
        json={
            "start": "2026-01-01",
            "execution_model": "tail_close_hybrid",
            "intraday_entry": "false",
            "minute_entry_required": "true",
            "persist": False,
        },
    )

    assert response.status_code == 200
    assert captured["params"].execution_model == "tail_close_hybrid"
    assert captured["params"].intraday_entry is True
    assert captured["params"].minute_entry_required is False


def test_backtest_api_defaults_to_daily_next_open(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_run_backtest(params):
        captured["params"] = params
        return {"status": "ready", "backtest_id": 10, "metrics": {}, "trades": [], "start": "2026-01-01", "end": "2026-01-31"}

    monkeypatch.setattr(backtests, "run_backtest", fake_run_backtest)

    client = TestClient(create_app())
    response = client.post("/api/backtests", json={"start": "2026-01-01", "persist": False})

    assert response.status_code == 200
    assert captured["params"].tail_entry_start == "14:30"
    assert captured["params"].tail_entry_end == "14:30"
    assert captured["params"].minute_interval == "1m"
    assert captured["params"].execution_model == "legacy_next_open"
    assert captured["params"].intraday_entry is False
    assert captured["params"].minute_entry_required is False
    assert captured["params"].max_positions == 10
    assert captured["params"].candidate_limit == 20
    assert captured["params"].max_position_pct == 0.1


def test_symbol_backtest_api_passes_single_symbol_and_returns_audit(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_run_backtest(params):
        captured["params"] = params
        return {"status": "ready", "backtest_id": 11, "metrics": {}, "trades": [], "start": "2026-01-01", "end": "2026-01-31"}

    def fake_audit(backtest_id, vt_symbol=None, limit=200):
        return {"status": "ready", "backtest_id": backtest_id, "vt_symbol": vt_symbol, "events": [], "orders": [], "trades": [], "limit": limit}

    monkeypatch.setattr(backtests, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(backtests, "backtest_audit", fake_audit)

    client = TestClient(create_app())
    response = client.post("/api/backtests/symbol", json={"vt_symbol": "600000.SSE", "start": "2026-01-01", "audit_limit": 88})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["backtest_id"] == 11
    assert data["audit"]["vt_symbol"] == "600000.SSE"
    assert data["audit"]["limit"] == 88
    assert captured["params"].symbols == ["600000.SSE"]
    assert captured["params"].max_symbols == 1
    assert captured["params"].max_positions == 1
    assert captured["params"].candidate_limit == 1
    assert captured["params"].persist is True


def test_backtest_audit_api_passes_symbol_filter(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_audit(backtest_id, vt_symbol=None, limit=200):
        captured.update({"backtest_id": backtest_id, "vt_symbol": vt_symbol, "limit": limit})
        return {"status": "ready", "backtest_id": backtest_id, "vt_symbol": vt_symbol, "events": [], "orders": [], "trades": []}

    monkeypatch.setattr(backtests, "backtest_audit", fake_audit)

    client = TestClient(create_app())
    response = client.get("/api/backtests/11/audit?vt_symbol=600000.SSE&limit=77")

    assert response.status_code == 200
    assert response.json()["data"]["vt_symbol"] == "600000.SSE"
    assert captured == {"backtest_id": 11, "vt_symbol": "600000.SSE", "limit": 77}


def test_backtest_candidate_trace_api_passes_symbol_and_signal_date(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_trace(backtest_id, vt_symbol, signal_date):
        captured.update({"backtest_id": backtest_id, "vt_symbol": vt_symbol, "signal_date": signal_date})
        return {"status": "filled", "backtest_id": backtest_id, "vt_symbol": vt_symbol, "signal_date": signal_date.isoformat()}

    monkeypatch.setattr(backtests, "backtest_candidate_trace", fake_trace)

    client = TestClient(create_app())
    response = client.get("/api/backtests/11/candidate-trace?vt_symbol=600000.SSE&signal_date=2026-01-05")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "filled"
    assert captured == {"backtest_id": 11, "vt_symbol": "600000.SSE", "signal_date": date(2026, 1, 5)}


def test_backtest_execution_model_comparison_summary_warns_on_proxy_dependence() -> None:
    from alphaagent.server.services.backtest import engine

    rows = [
        {
            "execution_model": "tail_close_hybrid",
            "status": "ready",
            "total_return_pct": -13.47,
            "buy_count": 21,
            "daily_close_proxy_ratio": 90.0,
        },
        {
            "execution_model": "strict_1430",
            "status": "ready",
            "total_return_pct": -0.25,
            "buy_count": 2,
            "strict_1430_rejected_count": 0,
        },
    ]

    summary = engine._execution_model_comparison_summary(rows)

    assert summary["status"] == "warning"
    assert summary["return_delta_pct"] == 13.22
    assert "收盘代理" in summary["message"]


def test_backtest_execution_model_comparison_summary_distinguishes_condition_rejections() -> None:
    from alphaagent.server.services.backtest import engine

    rows = [
        {
            "execution_model": "tail_close_hybrid",
            "status": "ready",
            "total_return_pct": -10.37,
            "buy_count": 21,
            "daily_close_proxy_ratio": 0.0,
        },
        {
            "execution_model": "strict_1430",
            "status": "ready",
            "total_return_pct": -10.37,
            "buy_count": 21,
            "strict_1430_rejected_count": 83,
            "minute_gap_rejected_count": 0,
        },
    ]

    summary = engine._execution_model_comparison_summary(rows)

    assert summary["status"] == "warning"
    assert "策略条件约束" in summary["message"]
    assert "补齐对应执行日快照" not in summary["message"]


def test_backtest_execution_model_comparison_api(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_comparison(backtest_id):
        captured["backtest_id"] = backtest_id
        return {"status": "ready", "backtest_id": backtest_id, "rows": []}

    monkeypatch.setattr(backtests, "backtest_execution_model_comparison", fake_comparison)

    client = TestClient(create_app())
    response = client.get("/api/backtests/11/execution-model-comparison")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ready"
    assert captured == {"backtest_id": 11}


def test_backtest_drilldown_options_api(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_options(backtest_id: int):
        captured["backtest_id"] = backtest_id
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "dates": [{"trade_date": "2026-01-06"}],
            "symbols": [{"vt_symbol": "002636.SZSE", "status_label": "有拒单"}],
        }

    monkeypatch.setattr(backtests, "backtest_drilldown_options", fake_options)

    client = TestClient(create_app())
    response = client.get("/api/backtests/7/drilldown-options")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["symbols"][0]["vt_symbol"] == "002636.SZSE"
    assert captured == {"backtest_id": 7}


def test_backtest_daily_decisions_api(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_daily_decisions(backtest_id: int, limit: int, offset: int, order: str):
        captured.update({"backtest_id": backtest_id, "limit": limit, "offset": offset, "order": order})
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "items": [{"trade_date": "2026-01-06", "buy_candidate_count": 1}],
        }

    monkeypatch.setattr(backtests, "backtest_daily_decisions", fake_daily_decisions)

    client = TestClient(create_app())
    response = client.get("/api/backtests/7/daily-decisions?limit=20&offset=40&order=asc")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["items"][0]["trade_date"] == "2026-01-06"
    assert captured == {"backtest_id": 7, "limit": 20, "offset": 40, "order": "asc"}


def test_backtest_trade_attribution_api(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_trade_attribution(backtest_id: int, limit: int, offset: int, sort: str):
        captured.update({"backtest_id": backtest_id, "limit": limit, "offset": offset, "sort": sort})
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "summary": {"closed_count": 1},
            "items": [{"vt_symbol": "002636.SZSE", "pnl": -120.0}],
        }

    monkeypatch.setattr(backtests, "backtest_trade_attribution", fake_trade_attribution)

    client = TestClient(create_app())
    response = client.get("/api/backtests/7/trade-attribution?limit=30&offset=60&sort=entry_desc")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["items"][0]["vt_symbol"] == "002636.SZSE"
    assert captured == {"backtest_id": 7, "limit": 30, "offset": 60, "sort": "entry_desc"}


def test_backtest_top_candidate_audit_api(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    def fake_top_candidate_audit(backtest_id: int, top_n: int):
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "top_n": top_n,
            "summary": {"top_count": 2, "top_win_rate": 0.5},
        }

    monkeypatch.setattr(backtests, "backtest_top_candidate_audit", fake_top_candidate_audit)
    client = TestClient(create_app())

    response = client.get("/api/backtests/175/top-candidate-audit?top_n=10")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["backtest_id"] == 175
    assert payload["top_n"] == 10
    assert payload["summary"]["top_win_rate"] == 0.5


def test_backtest_setup_market_exit_audit_api(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_setup_market_exit_audit(backtest_id: int, lookahead_days: int):
        captured.update({"backtest_id": backtest_id, "lookahead_days": lookahead_days})
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "lookahead_days": lookahead_days,
            "summary": {"overall": {"trade_count": 2}},
        }

    monkeypatch.setattr(backtests, "backtest_setup_market_exit_audit", fake_setup_market_exit_audit)
    client = TestClient(create_app())

    response = client.get("/api/backtests/194/setup-market-exit-audit?lookahead_days=12")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["backtest_id"] == 194
    assert payload["summary"]["overall"]["trade_count"] == 2
    assert captured == {"backtest_id": 194, "lookahead_days": 12}


def test_backtest_support_stop_matrix_api(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_support_stop_matrix(backtest_id: int, lookahead_days: int = 10, sample_limit: int = 40):
        captured.update({"backtest_id": backtest_id, "lookahead_days": lookahead_days, "sample_limit": sample_limit})
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "audit_only": True,
            "not_used_for_signal_score": True,
            "summary": {"overall": {"trade_count": 4}},
        }

    monkeypatch.setattr(backtests, "backtest_support_stop_matrix", fake_support_stop_matrix)
    client = TestClient(create_app())

    response = client.get("/api/backtests/203/support-stop-matrix?lookahead_days=12&sample_limit=25")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["backtest_id"] == 203
    assert payload["audit_only"] is True
    assert payload["not_used_for_signal_score"] is True
    assert payload["summary"]["overall"]["trade_count"] == 4
    assert captured == {"backtest_id": 203, "lookahead_days": 12, "sample_limit": 25}


def test_backtest_market_phase_audit_api(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_market_phase_audit(backtest_id: int, candidate_top_n: int = 20):
        captured.update({"backtest_id": backtest_id, "candidate_top_n": candidate_top_n})
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "candidate_top_n": candidate_top_n,
            "summary": {"overall": {"trade_count": 3}},
        }

    monkeypatch.setattr(backtests, "backtest_market_phase_audit", fake_market_phase_audit)
    client = TestClient(create_app())

    response = client.get("/api/backtests/203/market-phase-audit?candidate_top_n=30")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["backtest_id"] == 203
    assert payload["candidate_top_n"] == 30
    assert payload["summary"]["overall"]["trade_count"] == 3
    assert captured == {"backtest_id": 203, "candidate_top_n": 30}


def test_backtest_low_suction_confirmed_path_audit_api(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_low_suction_confirmed_path_audit(backtest_id: int, lookahead_days: int = 20):
        captured.update({"backtest_id": backtest_id, "lookahead_days": lookahead_days})
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "lookahead_days": lookahead_days,
            "audit_only": True,
            "summary": {"overall": {"trade_count": 2}},
        }

    monkeypatch.setattr(backtests, "backtest_low_suction_confirmed_path_audit", fake_low_suction_confirmed_path_audit)
    client = TestClient(create_app())

    response = client.get("/api/backtests/261/low-suction-confirmed-path-audit?lookahead_days=20")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["backtest_id"] == 261
    assert payload["audit_only"] is True
    assert payload["summary"]["overall"]["trade_count"] == 2
    assert captured == {"backtest_id": 261, "lookahead_days": 20}


def test_backtest_phase_strategy_family_matrix_api(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_phase_strategy_family_matrix(backtest_id: int, candidate_rank_limits: list[int] | None = None):
        captured.update({"backtest_id": backtest_id, "candidate_rank_limits": candidate_rank_limits})
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "candidate_rank_limits": candidate_rank_limits,
            "summary": {"not_used_for_signal_score": True},
        }

    monkeypatch.setattr(backtests, "backtest_phase_strategy_family_matrix", fake_phase_strategy_family_matrix)
    client = TestClient(create_app())

    response = client.get("/api/backtests/203/phase-strategy-family-matrix?candidate_rank_limits=10,20,100")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["backtest_id"] == 203
    assert payload["summary"]["not_used_for_signal_score"] is True
    assert captured == {"backtest_id": 203, "candidate_rank_limits": [10, 20, 100]}


def test_execution_breakpoint_rows_classify_full_and_theoretical_holding_gap() -> None:
    from alphaagent.server.services.backtest import queries

    signal_date = date(2026, 4, 15)
    execute_date = date(2026, 4, 16)
    rows = queries.execution_breakpoint_rows(
        recommendations=[
            {
                "trade_date": signal_date,
                "vt_symbol": "603115.SSE",
                "name": "海星股份",
                "action": "BUY",
                "rank": 2,
                "total_score": 96.03,
                "reason": {
                    "entry_setup": "dragon_pullback",
                    "low_suction_days": 4,
                    "low_suction_launch_confirmed": True,
                    "ma_convergence_pct": 4.2,
                },
            },
            {
                "trade_date": date(2025, 10, 24),
                "vt_symbol": "002407.SZSE",
                "name": "多氟多",
                "action": "BUY",
                "rank": 4,
                "total_score": 99.951,
                "reason": {"entry_setup": "dragon_pullback"},
            },
            {
                "trade_date": date(2026, 5, 8),
                "vt_symbol": "002938.SZSE",
                "name": "鹏鼎控股",
                "action": "BUY",
                "rank": 5,
                "total_score": 97.22,
                "reason": {"entry_setup": "dragon_pullback"},
            },
        ],
        signal_events=[
            {
                "id": 1,
                "signal_date": signal_date,
                "trade_date": execute_date,
                "execute_date": execute_date,
                "vt_symbol": "603115.SSE",
                "side": "BUY",
                "score": 96.03,
                "raw": {
                    "status": "filled",
                    "evidence": {"entry_setup": "dragon_pullback"},
                    "candidate_execution": {
                        "execution_candidate_rank": 3,
                        "execution_candidate_selected": True,
                        "execution_lane": "dragon_pullback",
                    },
                },
            },
            {
                "id": 2,
                "signal_date": date(2025, 9, 25),
                "trade_date": date(2025, 9, 26),
                "execute_date": date(2025, 9, 26),
                "vt_symbol": "002407.SZSE",
                "side": "BUY",
                "score": 95.0,
                "raw": {"status": "filled", "evidence": {"entry_setup": "dragon_pullback"}},
            },
            {
                "id": 3,
                "signal_date": date(2026, 4, 20),
                "trade_date": date(2026, 4, 21),
                "execute_date": date(2026, 4, 21),
                "vt_symbol": "000001.SZSE",
                "side": "BUY",
                "score": 90.0,
                "raw": {
                    "status": "filled",
                    "evidence": {"entry_setup": "stealth_low_suction"},
                    "candidate_execution": {"execution_candidate_rank": 101, "raw_signal_rank": 101},
                },
            },
        ],
        orders=[],
        trades=[],
        equities=[
            {"trade_date": execute_date, "position_count": 10},
            {"trade_date": date(2025, 10, 24), "position_count": 10},
            {"trade_date": date(2026, 5, 8), "position_count": 6},
        ],
        positions=[],
        run_params={"candidate_limit": 20, "max_positions": 10},
    )

    by_key = {(row["vt_symbol"], row["signal_date"]): row for row in rows}
    full_row = by_key[("603115.SSE", signal_date)]
    gap_row = by_key[("002407.SZSE", date(2025, 10, 24))]
    no_order_row = by_key[("002938.SZSE", date(2026, 5, 8))]
    assert ("000001.SZSE", date(2026, 4, 20)) not in by_key
    assert full_row["status"] == "planned_not_ordered_unfilled"
    assert full_row["execution_candidate_rank"] == 3
    assert full_row["low_suction_days"] == 4
    assert full_row["ma_convergence_pct"] == 4.2
    assert full_row["setup_family"] == "dragon_low_suction_overlap"
    assert "没有形成组合成交" in full_row["summary"]
    assert gap_row["status"] == "candidate_top_rank_unfilled"
    assert gap_row["theoretical_marker_gap"] is True
    assert gap_row["theoretical_entry_date"] == "2025-09-26"
    assert no_order_row["status"] == "candidate_top_rank_no_order"

    summary = queries.execution_breakpoint_matrix_summary(rows)
    assert summary["audit_only"] is True
    assert summary["not_used_for_signal_score"] is True
    assert summary["unfilled_top_candidate_count"] == 2
    assert summary["theoretical_real_gap_count"] == 1
    assert summary["interpretation"]["primary_issue"] == "top_candidate_unfilled"


def test_execution_breakpoint_filled_trade_without_recommendation_counts_as_buy() -> None:
    from alphaagent.server.services.backtest import queries

    signal_date = date(2026, 4, 15)
    execute_date = date(2026, 4, 16)
    rows = queries.execution_breakpoint_rows(
        recommendations=[],
        signal_events=[
            {
                "id": 1,
                "signal_date": signal_date,
                "trade_date": execute_date,
                "execute_date": execute_date,
                "vt_symbol": "603115.SSE",
                "side": "BUY",
                "score": 96.03,
                "raw": {
                    "status": "filled",
                    "evidence": {"entry_setup": "dragon_pullback"},
                    "candidate_execution": {
                        "execution_candidate_rank": 3,
                        "execution_candidate_selected": True,
                    },
                },
            },
        ],
        orders=[
            {
                "id": 1,
                "signal_date": signal_date,
                "trade_date": execute_date,
                "vt_symbol": "603115.SSE",
                "side": "BUY",
                "status": "filled",
            }
        ],
        trades=[
            {
                "id": 1,
                "signal_date": signal_date,
                "trade_date": execute_date,
                "vt_symbol": "603115.SSE",
                "side": "BUY",
            }
        ],
        equities=[{"trade_date": execute_date, "position_count": 1}],
        positions=[],
        run_params={"candidate_limit": 20, "max_positions": 10},
    )

    assert rows[0]["status"] == "filled"
    assert rows[0]["action"] == "BUY"
    summary = queries.execution_breakpoint_matrix_summary(rows)
    assert summary["overall"]["buy_candidate_count"] == 1
    assert summary["overall"]["filled_count"] == 1
    assert summary["overall"]["filled_rate"] == 1.0


def test_backtest_execution_breakpoint_matrix_api(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_execution_breakpoint_matrix(
        backtest_id: int,
        candidate_rank_limit: int = 100,
        sample_limit: int = 120,
    ):
        captured.update(
            {
                "backtest_id": backtest_id,
                "candidate_rank_limit": candidate_rank_limit,
                "sample_limit": sample_limit,
            }
        )
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "audit_only": True,
            "not_used_for_signal_score": True,
            "summary": {"overall": {"candidate_count": 2}},
        }

    monkeypatch.setattr(backtests, "backtest_execution_breakpoint_matrix", fake_execution_breakpoint_matrix)
    client = TestClient(create_app())

    response = client.get("/api/backtests/267/execution-breakpoint-matrix?candidate_rank_limit=50&sample_limit=30")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["backtest_id"] == 267
    assert payload["audit_only"] is True
    assert payload["not_used_for_signal_score"] is True
    assert payload["summary"]["overall"]["candidate_count"] == 2
    assert captured == {"backtest_id": 267, "candidate_rank_limit": 50, "sample_limit": 30}


def test_backtest_minute_coverage_classifies_proxy_and_gap_states(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    def fake_report(backtest_id, trade_limit=1):
        del trade_limit
        if backtest_id == 1:
            quality = {
                "buy_count": 3,
                "minute_1430_count": 3,
                "minute_1430_ratio": 100.0,
                "daily_close_proxy_count": 0,
                "strict_1430_rejected_count": 0,
                "minute_gap_rejected_count": 0,
            }
        elif backtest_id == 2:
            quality = {
                "buy_count": 5,
                "minute_1430_count": 1,
                "minute_1430_ratio": 20.0,
                "daily_close_proxy_count": 4,
                "daily_close_proxy_ratio": 80.0,
                "strict_1430_rejected_count": 0,
                "minute_gap_rejected_count": 0,
            }
        elif backtest_id == 3:
            quality = {
                "buy_count": 1,
                "minute_1430_count": 0,
                "daily_close_proxy_count": 0,
                "strict_1430_rejected_count": 9,
                "minute_gap_rejected_count": 4,
            }
        else:
            quality = {
                "buy_count": 2,
                "minute_1430_count": 2,
                "daily_close_proxy_count": 0,
                "strict_1430_rejected_count": 8,
                "minute_gap_rejected_count": 0,
            }
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "execution_quality": quality,
            "method": {"execution": {"execution_model": "strict_1430"}},
        }

    monkeypatch.setattr(engine, "backtest_report", fake_report)

    assert engine.backtest_minute_coverage(1)["status"] == "ready"
    assert engine.backtest_minute_coverage(2)["status"] == "mixed_proxy"
    assert engine.backtest_minute_coverage(3)["status"] == "missing_snapshots"
    assert engine.backtest_minute_coverage(4)["status"] == "strategy_not_triggered"


def test_backtest_minute_coverage_api(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_coverage(backtest_id):
        captured["backtest_id"] = backtest_id
        return {"status": "ready", "backtest_id": backtest_id, "buy_count": 1}

    monkeypatch.setattr(backtests, "backtest_minute_coverage", fake_coverage)

    client = TestClient(create_app())
    response = client.get("/api/backtests/11/minute-coverage")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ready"
    assert captured == {"backtest_id": 11}


def test_backtest_data_quality_summarizes_existing_report_and_coverage() -> None:
    from alphaagent.server.services.backtest import data_quality

    def fake_report(backtest_id, trade_limit):
        assert backtest_id == 62
        assert trade_limit == 1
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "strategy_id": "mainline_leader_pullback",
            "strategy_version": "0.1.1",
            "start_date": "2026-02-02",
            "end_date": "2026-06-13",
            "execution_quality": {
                "daily_close_proxy_count": 0,
                "minute_gap_rejected_count": 0,
            },
            "data_quality": {"stock_financial_reports": {"count": 20}},
            "sample": {"symbol_count": 80, "coverage_pct": 2.5},
            "data_as_of_audit": {"status": "ready"},
        }

    def fake_coverage(backtest_id):
        assert backtest_id == 62
        return {
            "status": "ready",
            "execution_model": "strict_1430",
            "minute_1430_count": 21,
            "next_action": "本次买入均可按 14:30 分钟快照解读。",
        }

    result = data_quality.backtest_data_quality(62, report_loader=fake_report, coverage_loader=fake_coverage)

    assert result["status"] == "ready"
    assert result["execution_model"] == "strict_1430"
    assert result["checks"][0]["id"] == "minute_1430_coverage"
    assert result["checks"][0]["status"] == "pass"
    assert result["checks"][3]["id"] == "financial_visibility"
    assert result["checks"][3]["status"] == "pass"


def test_backtest_data_quality_uses_full_report_analysis(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    calls = []

    def fake_report(backtest_id, trade_limit, *, include_analysis=False):
        calls.append(
            {
                "backtest_id": backtest_id,
                "trade_limit": trade_limit,
                "include_analysis": include_analysis,
            }
        )
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "strategy_id": "mainline_dragon_pullback",
            "strategy_version": "0.1.8",
            "start_date": "2025-03-26",
            "end_date": "2026-06-16",
            "execution_quality": {
                "daily_close_proxy_count": 0,
                "minute_gap_rejected_count": 0,
            },
            "data_quality": {"stock_financial_reports": {"count": 20}},
            "sample": {"symbol_count": 100, "coverage_pct": 2.5},
            "data_as_of_audit": {"status": "pass"},
        }

    def fake_coverage(backtest_id):
        return {
            "status": "ready",
            "backtest_id": backtest_id,
            "execution_model": "legacy_next_open",
            "minute_1430_count": 0,
            "next_action": "日线 D+1 回测不依赖历史 14:30 快照。",
        }

    monkeypatch.setattr(engine, "backtest_report", fake_report)
    monkeypatch.setattr(engine, "backtest_minute_coverage", fake_coverage)

    result = engine.backtest_data_quality(149)

    assert result["status"] == "ready"
    assert result["data_as_of_audit"] == {"status": "pass"}
    assert calls == [
        {
            "backtest_id": 149,
            "trade_limit": 1,
            "include_analysis": True,
        }
    ]


def test_backtest_data_quality_api(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_data_quality(backtest_id):
        captured["backtest_id"] = backtest_id
        return {"status": "ready", "backtest_id": backtest_id, "checks": []}

    monkeypatch.setattr(backtests, "backtest_data_quality", fake_data_quality)

    client = TestClient(create_app())
    response = client.get("/api/backtests/62/data-quality")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ready"
    assert captured == {"backtest_id": 62}


def test_backtest_trades_api_passes_pagination(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_trades(backtest_id, limit=500, offset=0, order="desc"):
        captured.update({"backtest_id": backtest_id, "limit": limit, "offset": offset, "order": order})
        return {"status": "ready", "backtest_id": backtest_id, "items": [], "limit": limit, "offset": offset, "total": 0, "has_more": False}

    monkeypatch.setattr(backtests, "backtest_trades", fake_trades)

    client = TestClient(create_app())
    response = client.get("/api/backtests/11/trades?limit=20&offset=40&order=desc")

    assert response.status_code == 200
    assert response.json()["data"]["offset"] == 40
    assert captured == {"backtest_id": 11, "limit": 20, "offset": 40, "order": "desc"}


def test_backtest_execution_quality_flags_minute_fallback_risk() -> None:
    from alphaagent.server.services.backtest import engine

    quality = engine._execution_quality_report(
        {"minute_tail_entry_count": 0, "daily_open_fallback_count": 10},
        {"buy_count": 10, "execution_modes": {"daily_next_open_fallback": 10}},
        {
            "stock_minute_bars": {"count": 0},
            "stock_daily_bars": {"count": 1000},
            "stock_financial_reports": {"count": 3},
        },
        {"coverage_pct": 25.0},
    )

    assert quality["status"] == "warning"
    assert quality["minute_1430_ratio"] == 0.0
    assert quality["daily_open_fallback_ratio"] == 100.0
    assert any(item["id"] == "minute_1430_coverage" and item["status"] == "warning" for item in quality["diagnostics"])
    assert any(item["id"] == "legacy_open_fallback_rate" and item["status"] == "warning" for item in quality["diagnostics"])


def test_backtest_execution_quality_flags_strict_tail_rejections() -> None:
    from alphaagent.server.services.backtest import engine

    quality = engine._execution_quality_report(
        {"minute_1430_count": 2, "daily_close_proxy_count": 0},
        {
            "buy_count": 2,
            "strict_1430_rejected_count": 780,
            "minute_gap_rejected_count": 780,
            "execution_modes": {"minute_1430": 2},
        },
        {
            "stock_minute_bars": {"count": 61544},
            "stock_daily_bars": {"count": 1000},
            "stock_financial_reports": {"count": 3},
        },
        {"coverage_pct": 99.0},
    )

    assert quality["status"] == "warning"
    assert quality["minute_1430_ratio"] == 100.0
    assert quality["strict_1430_rejected_count"] == 780
    assert quality["strict_1430_rejected_ratio"] > 99
    assert quality["minute_gap_rejected_count"] == 780
    assert any(item["id"] == "strict_tail_rejected_orders" and item["status"] == "warning" for item in quality["diagnostics"])


def test_data_sync_truthy_handles_string_params() -> None:
    from alphaagent.server.services import data_sync

    assert data_sync._truthy(True)
    assert data_sync._truthy("true")
    assert data_sync._truthy("1")
    assert not data_sync._truthy(False)
    assert not data_sync._truthy("false")


def test_financial_sync_runner_uses_missing_first_stock_selection(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    seen: list[tuple[int, bool]] = []

    def fake_rows(stock_limit: int, only_missing: bool):
        seen.append((stock_limit, only_missing))
        return []

    monkeypatch.setattr(data_sync, "_financial_sync_stock_rows", fake_rows)

    runner = data_sync.DataSyncRunner()
    result = runner._run_sync_stock_financial_quarterly({"stock_limit": 123, "only_missing": "true"})

    assert result["rows_read"] == 0
    assert seen == [(123, True)]


def test_quarterly_cash_flow_enrichment_maps_operating_cash_quality() -> None:
    from alphaagent.server.services import data_sync

    class FakeAdapter:
        def stock_cash_flow_sheet(self, symbol, exchange=None):
            assert symbol == "600000"
            assert exchange == "SSE"
            return {
                "items": [
                    {
                        "REPORT_DATE": "2026-03-31 00:00:00",
                        "NOTICE_DATE": "2026-04-30 00:00:00",
                        "NETCASH_OPERATE": 30_000_000,
                    }
                ]
            }

    items = [{"report_date": "2026-03-31 00:00:00", "net_profit": 10_000_000}]
    runner = data_sync.DataSyncRunner(adapter=FakeAdapter())

    runner._enrich_quarterly_with_cash_flow(items, "600000", "SSE")

    assert items[0]["publish_date"] == "2026-04-30 00:00:00"
    assert items[0]["operating_cash_flow"] == 30_000_000
    assert items[0]["cash_flow_quality"] == 3.0


def test_financial_report_upsert_persists_publish_and_cash_flow_fields(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    inserted: list[dict[str, object]] = []

    class FakeSelectResult:
        def first(self):
            return None

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if text.startswith("INSERT INTO stock_financial_reports"):
                inserted.append(dict(statement.compile().params))
                return None
            return FakeSelectResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(data_sync, "session_scope", fake_session_scope)

    written = data_sync._upsert_stock_financial_reports(
        "600000",
        "SSE",
        [
            {
                "report_date": "2026-03-31 00:00:00",
                "publish_date": "2026-04-30 00:00:00",
                "revenue_qoq": 12.5,
                "net_profit_qoq": 20.0,
                "deducted_net_profit": 9_000_000,
                "operating_cash_flow": 30_000_000,
                "cash_flow_quality": 3.0,
            }
        ],
        "quarterly",
    )

    assert written == 1
    assert inserted[0]["publish_date"] == "2026-04-30 00:00:00"
    assert inserted[0]["operating_cash_flow"] == 30_000_000
    assert inserted[0]["cash_flow_quality"] == 3.0
    assert inserted[0]["deducted_net_profit"] == 9_000_000


def test_simulation_auto_group_item_upsert_records_cost_and_reason() -> None:
    from alphaagent.server.services.simulation import account

    calls: list[object] = []

    class FakeScalarNone:
        def scalar_one_or_none(self):
            return None

    class FakeScalarGroup:
        def scalar_one(self):
            return 9

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            calls.append(statement)
            if text.startswith("SELECT portfolio_groups.id"):
                return FakeScalarNone()
            if text.startswith("INSERT INTO portfolio_groups"):
                return FakeScalarGroup()
            if text.startswith("SELECT portfolio_group_items.vt_symbol"):
                return FakeScalarNone()
            return FakeScalarGroup()

    written = account._upsert_simulation_auto_group_item(
        FakeSession(),
        "600000.SSE",
        "浦发银行",
        "mainline_leader_pullback",
        "quant recommendation #1",
        {
            "trade_date": date(2026, 6, 11),
            "strategy_version": "0.1.0",
            "total_score": 72.5,
        },
        10.25,
        1000,
    )

    insert_params = [
        dict(statement.compile().params)
        for statement in calls
        if str(statement).startswith("INSERT INTO portfolio_group_items")
    ][0]
    assert written == 1
    assert insert_params["group_id"] == 9
    assert insert_params["source"] == "simulation_auto"
    assert "cost=10.2500" in insert_params["reason"]
    assert "volume=1000" in insert_params["reason"]


def test_holding_trade_summary_exposes_latest_buy_and_sell() -> None:
    from datetime import datetime, timezone

    from alphaagent.server.services.portfolio import groups

    class FakeResult:
        def __init__(self, row):
            self.row = row

        def mappings(self):
            return self

        def first(self):
            return self.row

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def execute(self, statement):
            del statement
            self.calls += 1
            if self.calls == 1:
                return FakeResult(
                    {
                        "trade_time": datetime(2026, 6, 11, 14, 56, tzinfo=timezone.utc),
                        "price": 10.25,
                        "volume": 1000,
                        "amount": 10_250,
                        "order_reason": "quant recommendation #1",
                        "recommendation_id": 7,
                    }
                )
            return FakeResult(
                {
                    "trade_time": datetime(2026, 6, 12, 10, 1, tzinfo=timezone.utc),
                    "price": 11.0,
                    "volume": 500,
                    "amount": 5_500,
                    "pnl": 360.0,
                }
            )

    summary = groups._position_trade_summary(FakeSession(), 1, "600000.SSE")

    assert summary["last_buy_price"] == 10.25
    assert summary["last_buy_reason"] == "quant recommendation #1"
    assert summary["recommendation_id"] == 7
    assert summary["last_sell_price"] == 11.0
    assert summary["last_sell_pnl"] == 360.0


def test_vnpy_status_reports_core_without_claiming_a_share_gateway() -> None:
    from alphaagent.server.services.vnpy_integration.status import vnpy_status

    status = vnpy_status()

    assert status["product"] == "AlphaAgent"
    assert status["vnpy_package_name"] == "vnpy"
    assert status["launcher"]["registered_gateways"] == ["CtpGateway"]
    assert "vnpy_a_share_gateway" in status["capabilities"]
    assert status["launcher"]["a_share_gateway_registered"] is False
    assert "integration_plan" in status
    assert "alphaagent_local_vnpy_bar_adapter" in status["capabilities"]


def test_vnpy_local_data_builds_history_request_and_bardata() -> None:
    from alphaagent.server.services.vnpy_integration import local_data

    request = local_data.history_request("600000.SSE", date(2026, 1, 1), date(2026, 1, 31))
    bar = local_data._row_to_bar(
        {
            "trade_date": date(2026, 1, 2),
            "open_price": 10.0,
            "high_price": 10.5,
            "low_price": 9.8,
            "close_price": 10.2,
            "volume": 1_000_000,
            "turnover": 10_200_000,
        },
        request,
    )

    assert request.vt_symbol == "600000.SSE"
    assert request.interval.value == "d"
    assert bar.vt_symbol == "600000.SSE"
    assert bar.gateway_name == "ALPHAAGENT_LOCAL"
    assert bar.close_price == 10.2


def test_vnpy_database_import_loads_minute_bars(monkeypatch) -> None:
    from datetime import datetime

    from vnpy.trader.constant import Exchange, Interval
    from vnpy.trader.object import BarData

    from alphaagent.server.services.vnpy_integration import database_import

    class FakeDatabase:
        @staticmethod
        def load_bar_data(symbol, exchange, interval, start, end):
            assert symbol == "600000"
            assert exchange == Exchange.SSE
            assert interval == Interval.MINUTE
            assert start.date() == date(2026, 1, 8)
            assert end.date() == date(2026, 1, 8)
            return [
                BarData(
                    gateway_name="VNDB",
                    symbol=symbol,
                    exchange=exchange,
                    datetime=datetime(2026, 1, 8, 14, 56),
                    interval=interval,
                    open_price=10,
                    high_price=10.2,
                    low_price=9.9,
                    close_price=10.1,
                    volume=1200,
                    turnover=12120,
                )
            ]

    calls = []
    monkeypatch.setattr(database_import, "is_database_configured", lambda: True)
    monkeypatch.setattr(database_import, "get_database", lambda: FakeDatabase())
    monkeypatch.setattr(database_import, "_upsert_minute_bars", lambda symbol, exchange, items, interval, source: calls.append((symbol, exchange, interval, source, items[0]["close"])) or len(items))

    result = database_import.import_vnpy_minute_bars("600000.SSE", date(2026, 1, 8), date(2026, 1, 8))

    assert result["status"] == "ready"
    assert result["rows_read"] == 1
    assert result["rows_written"] == 1
    assert calls == [("600000", "SSE", "1m", "vnpy_database", 10.1)]


def test_vnpy_database_import_dry_run_does_not_upsert(monkeypatch) -> None:
    from alphaagent.server.services.vnpy_integration import database_import

    class FakeDatabase:
        @staticmethod
        def load_bar_data(symbol, exchange, interval, start, end):
            del symbol, exchange, interval, start, end
            return []

    monkeypatch.setattr(database_import, "is_database_configured", lambda: True)
    monkeypatch.setattr(database_import, "get_database", lambda: FakeDatabase())
    monkeypatch.setattr(database_import, "_upsert_minute_bars", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not write")))

    result = database_import.import_vnpy_minute_bars("600000.SSE", "2026-01-08", dry_run=True)

    assert result["status"] == "empty"
    assert result["rows_written"] == 0


def test_vnpy_database_imports_gap_minute_bars(monkeypatch) -> None:
    from datetime import datetime

    from vnpy.trader.constant import Exchange, Interval
    from vnpy.trader.object import BarData

    from alphaagent.server.services.vnpy_integration import database_import

    seen_windows = []

    class FakeDatabase:
        @staticmethod
        def load_bar_data(symbol, exchange, interval, start, end):
            seen_windows.append((symbol, exchange, interval, start.strftime("%H:%M"), end.strftime("%H:%M")))
            return [
                BarData(
                    gateway_name="VNDB",
                    symbol=symbol,
                    exchange=exchange,
                    datetime=datetime(2026, 1, 8, 14, 56),
                    interval=interval,
                    open_price=10,
                    high_price=10.2,
                    low_price=9.9,
                    close_price=10.1,
                    volume=1200,
                    turnover=12120,
                )
            ]

    writes = []
    gap_csv = "trade_date,vt_symbol,reference_date,window,ma5\n2026-01-08,600000.SSE,2026-01-07,14:30-14:30,10.0\n"
    monkeypatch.setattr(database_import, "is_database_configured", lambda: True)
    monkeypatch.setattr(database_import, "get_database", lambda: FakeDatabase())
    monkeypatch.setattr(
        database_import,
        "_upsert_minute_bars",
        lambda symbol, exchange, items, interval, source: writes.append((symbol, exchange, len(items), interval, source)) or len(items),
    )
    monkeypatch.setattr(
        database_import,
        "_audit_minute_gap_requirements",
        lambda requirements, **kwargs: {
            "status": "ready",
            "gap_count": len(requirements["items"]),
            "covered_count": len(requirements["items"]),
            "missing_count": 0,
            "coverage_pct": 100.0,
        },
    )

    result = database_import.import_vnpy_minute_bars_for_gaps(gap_csv_text=gap_csv, dry_run=False)

    assert result["status"] == "ready"
    assert result["gap_count"] == 1
    assert result["rows_read"] == 1
    assert result["rows_written"] == 1
    assert seen_windows == [("600000", Exchange.SSE, Interval.MINUTE, "14:30", "14:30")]
    assert writes == [("600000", "SSE", 1, "1m", "vnpy_database_gap")]
    assert result["audit_after"]["status"] == "ready"


def test_vnpy_gap_import_reports_empty_when_database_has_no_bars(monkeypatch) -> None:
    from alphaagent.server.services.vnpy_integration import database_import

    class FakeDatabase:
        @staticmethod
        def load_bar_data(symbol, exchange, interval, start, end):
            del symbol, exchange, interval, start, end
            return []

    gap_csv = "trade_date,vt_symbol,reference_date,window,ma5\n2026-01-08,600000.SSE,2026-01-07,14:30-14:30,10.0\n"
    monkeypatch.setattr(database_import, "is_database_configured", lambda: True)
    monkeypatch.setattr(database_import, "get_database", lambda: FakeDatabase())
    monkeypatch.setattr(
        database_import,
        "_audit_minute_gap_requirements",
        lambda requirements, **kwargs: {
            "status": "incomplete",
            "gap_count": len(requirements["items"]),
            "covered_count": 0,
            "missing_count": len(requirements["items"]),
            "coverage_pct": 0.0,
        },
    )

    result = database_import.import_vnpy_minute_bars_for_gaps(gap_csv_text=gap_csv, dry_run=True)

    assert result["status"] == "empty"
    assert result["rows_read"] == 0
    assert result["empty_request_count"] == 1
    assert result["audit_after"]["status"] == "incomplete"


def test_vnpy_import_minute_bars_endpoint(monkeypatch) -> None:
    from alphaagent.server.api import vnpy_local_data

    captured = {}

    def fake_import(vt_symbol, start, end, interval, dry_run):
        captured.update({"vt_symbol": vt_symbol, "start": start, "end": end, "interval": interval, "dry_run": dry_run})
        return {"status": "ready", "rows_read": 1, "rows_written": 0}

    monkeypatch.setattr(vnpy_local_data, "import_vnpy_minute_bars", fake_import)

    client = TestClient(create_app())
    response = client.post(
        "/api/vnpy/import-minute-bars",
        json={"vt_symbol": "600000.SSE", "start": "2026-01-08", "end": "2026-01-08", "interval": "1m", "dry_run": True},
    )

    assert response.status_code == 200
    assert captured == {"vt_symbol": "600000.SSE", "start": "2026-01-08", "end": "2026-01-08", "interval": "1m", "dry_run": True}
    assert response.json()["data"]["status"] == "ready"


def test_vnpy_import_gap_minute_bars_endpoint(monkeypatch) -> None:
    from alphaagent.server.api import vnpy_local_data

    captured = {}

    def fake_import(**kwargs):
        captured.update(kwargs)
        return {"status": "ready", "rows_read": 2, "rows_written": 0}

    monkeypatch.setattr(vnpy_local_data, "import_vnpy_minute_bars_for_gaps", fake_import)

    client = TestClient(create_app())
    response = client.post(
        "/api/vnpy/import-minute-bars/gaps",
        json={
            "gap_file_path": "memory/06_backtests/gaps.csv",
            "interval": "1m",
            "tail_entry_start": "14:30",
            "tail_entry_end": "14:30",
            "dry_run": True,
            "max_gaps": 50,
        },
    )

    assert response.status_code == 200
    assert captured == {
        "gap_csv_text": "",
        "gap_file_path": "memory/06_backtests/gaps.csv",
        "interval": "1m",
        "tail_entry_start": "14:30",
        "tail_entry_end": "14:30",
        "dry_run": True,
        "max_gaps": 50,
    }
    assert response.json()["data"]["status"] == "ready"


def test_vnpy_import_gap_minute_bars_endpoint_accepts_backtest_id(monkeypatch) -> None:
    from alphaagent.server.api import vnpy_local_data

    captured = {}

    monkeypatch.setattr(
        vnpy_local_data.data_sync_service,
        "minute_gap_requirements_from_params",
        lambda params: {
            "items": [{"vt_symbol": "600000.SSE", "trade_date": date(2026, 1, 8), "reference_date": None, "ma5": None, "window": "14:30-14:30"}],
            "rows_read": 1,
            "rows_skipped": 0,
            "errors": [],
        },
    )

    def fake_import(**kwargs):
        captured.update(kwargs)
        return {"status": "ready", "rows_read": 2, "rows_written": 0}

    monkeypatch.setattr(vnpy_local_data, "import_vnpy_minute_bars_for_gaps", fake_import)

    client = TestClient(create_app())
    response = client.post(
        "/api/vnpy/import-minute-bars/gaps",
        json={"backtest_id": 42, "interval": "1m", "tail_entry_start": "14:30", "tail_entry_end": "14:30", "dry_run": True},
    )

    assert response.status_code == 200
    assert captured["gap_csv_text"].startswith("trade_date,vt_symbol")
    assert captured["gap_file_path"] == ""
    assert response.json()["data"]["status"] == "ready"


def test_vnpy_local_bars_endpoint_rejects_invalid_symbol() -> None:
    client = TestClient(create_app())
    response = client.get("/api/vnpy/local-bars?vt_symbol=BAD&start=2026-01-01")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_VT_SYMBOL"


def test_tushare_gap_import_requires_token(monkeypatch) -> None:
    from types import SimpleNamespace

    from alphaagent.server.services.data_providers import tushare_minute_import

    monkeypatch.setattr(tushare_minute_import, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        tushare_minute_import,
        "get_settings",
        lambda: SimpleNamespace(tushare_token="", tushare_api_url="https://api.tushare.pro", tushare_timeout_seconds=1),
    )

    result = tushare_minute_import.import_tushare_minute_bars_for_gaps(gap_csv_text="trade_date,vt_symbol\n2026-01-08,600000.SSE\n")

    assert result["status"] == "unavailable"
    assert "TUSHARE_TOKEN" in result["message"]


def test_minute_gap_vendor_manifest_builds_provider_rows() -> None:
    from alphaagent.server.services import data_sync

    gap_csv = (
        "trade_date,vt_symbol,reference_date,window,ma5\n"
        "2026-01-08,600000.SSE,2026-01-07,14:30-14:30,10.0\n"
        "2026-01-08,600000.SSE,2026-01-07,14:30-14:30,10.0\n"
        "2026-01-09,000001.SZSE,2026-01-08,14:30-14:30,12.0\n"
    )

    manifest = data_sync.minute_gap_vendor_manifest(gap_csv, tail_entry_start="14:30", tail_entry_end="14:57")
    csv_text = data_sync.minute_gap_vendor_manifest_csv(gap_csv, tail_entry_start="14:30", tail_entry_end="14:57")

    assert manifest["status"] == "ready"
    assert manifest["request_count"] == 2
    assert manifest["symbol_count"] == 2
    assert manifest["date_count"] == 2
    assert manifest["sample_rows"][0]["tushare_ts_code"] == "600000.SH"
    assert "000001.SZ" in csv_text
    assert "vt_symbol,bar_time,open,high,low,close,volume,turnover" in csv_text


def test_minute_gap_vendor_manifest_endpoint(monkeypatch) -> None:
    from alphaagent.server.api import data_sync

    monkeypatch.setattr(
        data_sync.service,
        "minute_gap_vendor_manifest",
        lambda *args, **kwargs: {"status": "ready", "request_count": 1, "symbol_count": 1, "date_count": 1},
    )
    monkeypatch.setattr(data_sync.service, "minute_gap_vendor_manifest_csv", lambda *args, **kwargs: "\ufeffvt_symbol\n600000.SSE\n")

    client = TestClient(create_app())
    response = client.post("/api/data-sync/imports/minute-bars/vendor-manifest", json={"gap_csv_text": "x"})
    csv_response = client.post("/api/data-sync/imports/minute-bars/vendor-manifest.csv", json={"gap_csv_text": "x"})

    assert response.status_code == 200
    assert response.json()["data"]["request_count"] == 1
    assert csv_response.status_code == 200
    assert "600000.SSE" in csv_response.text


def test_minute_gap_vendor_manifest_endpoint_accepts_backtest_id(monkeypatch) -> None:
    from alphaagent.server.api import data_sync

    monkeypatch.setattr(
        data_sync.service,
        "minute_gap_requirements_from_params",
        lambda params: {
            "items": [{"vt_symbol": "600000.SSE", "trade_date": date(2026, 1, 8), "reference_date": None, "ma5": None, "window": "14:30-14:30"}],
            "rows_read": 1,
            "rows_skipped": 0,
            "errors": [],
        },
    )

    client = TestClient(create_app())
    response = client.post("/api/data-sync/imports/minute-bars/vendor-manifest", json={"backtest_id": 42})
    csv_response = client.post("/api/data-sync/imports/minute-bars/vendor-manifest.csv", json={"backtest_id": 42})

    assert response.status_code == 200
    assert response.json()["data"]["request_count"] == 1
    assert csv_response.status_code == 200
    assert "600000.SSE" in csv_response.text


def test_tushare_gap_import_filters_and_upserts(monkeypatch) -> None:
    from types import SimpleNamespace

    from alphaagent.server.services.data_providers import tushare_minute_import

    class FakeResponse:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "code": 0,
                "data": {
                    "fields": ["ts_code", "trade_time", "open", "close", "high", "low", "vol", "amount"],
                    "items": [
                        ["600000.SH", "2026-01-08 14:30:00", 10, 10.1, 10.2, 9.9, 1000, 10100],
                        ["600000.SH", "2026-06-11 14:30:00", 11, 11.1, 11.2, 10.9, 1000, 11100],
                    ],
                },
            }

    posted = []
    writes = []
    gap_csv = "trade_date,vt_symbol,reference_date,window,ma5\n2026-01-08,600000.SSE,2026-01-07,14:30-14:30,10.0\n"
    monkeypatch.setattr(tushare_minute_import, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        tushare_minute_import,
        "get_settings",
        lambda: SimpleNamespace(tushare_token="token", tushare_api_url="https://api.tushare.pro", tushare_timeout_seconds=1),
    )
    monkeypatch.setattr(
        tushare_minute_import.requests,
        "post",
        lambda url, json, timeout: posted.append((url, json, timeout)) or FakeResponse(),
    )
    monkeypatch.setattr(
        tushare_minute_import,
        "_upsert_minute_bars",
        lambda symbol, exchange, items, interval, source: writes.append((symbol, exchange, len(items), interval, source, items[0]["close"])) or len(items),
    )
    monkeypatch.setattr(
        tushare_minute_import,
        "_audit_minute_gap_requirements",
        lambda requirements, **kwargs: {
            "status": "ready",
            "gap_count": len(requirements["items"]),
            "covered_count": len(requirements["items"]),
            "missing_count": 0,
            "coverage_pct": 100.0,
        },
    )

    result = tushare_minute_import.import_tushare_minute_bars_for_gaps(gap_csv_text=gap_csv, dry_run=False)

    assert result["status"] == "ready"
    assert result["rows_read"] == 1
    assert result["wrong_date_row_count"] == 1
    assert result["rows_written"] == 1
    assert writes == [("600000", "SSE", 1, "1m", "tushare_stk_mins", 10.1)]
    assert posted[0][1]["api_name"] == "stk_mins"
    assert posted[0][1]["params"]["ts_code"] == "600000.SH"
    assert posted[0][1]["params"]["start_date"] == "2026-01-08 14:30:00"


def test_tdx_gap_import_writes_real_minute_rows(monkeypatch) -> None:
    from alphaagent.server.services.data_providers import tdx_minute_import

    class FakeApi:
        def get_security_bars(self, category, market, symbol, start, count):
            assert category == 8
            assert market == 1
            assert symbol == "600000"
            assert start == 0
            assert count == 800
            return [
                {
                    "datetime": "2026-01-08 14:30",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "vol": 1200,
                    "amount": 12120,
                },
                {
                    "datetime": "2026-01-08 14:57",
                    "open": 10.1,
                    "high": 10.3,
                    "low": 10.0,
                    "close": 10.2,
                    "vol": 1300,
                    "amount": 13260,
                },
            ]

        @staticmethod
        def disconnect():
            return None

    writes = []
    gap_csv = "trade_date,vt_symbol,reference_date,window,ma5\n2026-01-08,600000.SSE,2026-01-07,14:30-14:30,10.0\n"
    monkeypatch.setattr(tdx_minute_import, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        tdx_minute_import,
        "_connect_tdx",
        lambda timeout_seconds: (FakeApi(), {"name": "fake", "ip": "127.0.0.1", "port": 7709}),
    )
    monkeypatch.setattr(
        tdx_minute_import,
        "_upsert_minute_bars",
        lambda symbol, exchange, items, interval, source: writes.append((symbol, exchange, len(items), interval, source)) or len(items),
    )
    monkeypatch.setattr(
        tdx_minute_import,
        "_audit_minute_gap_requirements",
        lambda requirements, **kwargs: {
            "status": "ready",
            "gap_count": len(requirements["items"]),
            "covered_count": len(requirements["items"]),
            "missing_count": 0,
            "coverage_pct": 100.0,
        },
    )

    result = tdx_minute_import.import_tdx_minute_bars_for_gaps(gap_csv_text=gap_csv, dry_run=False, max_pages_per_symbol=1)

    assert result["status"] == "ready"
    assert result["rows_read"] == 1
    assert result["rows_written"] == 1
    assert result["preview_covered_gap_count"] == 1
    assert writes == [("600000", "SSE", 1, "1m", "tdx_public_hq")]
    assert result["audit_after"]["status"] == "ready"


def test_tdx_gap_import_reconnects_after_a_broken_quote_connection(monkeypatch) -> None:
    from alphaagent.server.services.data_providers import tdx_minute_import

    class BrokenApi:
        def get_security_bars(self, *_args):
            raise RuntimeError("connection lost")

        @staticmethod
        def disconnect():
            return None

    class HealthyApi:
        def get_security_bars(self, _category, _market, _symbol, _start, _count):
            return [{
                "datetime": "2026-07-10 14:30",
                "open": 10,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "vol": 1200,
                "amount": 12120,
            }]

        @staticmethod
        def disconnect():
            return None

    connections = iter([
        (BrokenApi(), {"name": "broken", "ip": "127.0.0.1", "port": 7709}),
        (HealthyApi(), {"name": "healthy", "ip": "127.0.0.2", "port": 7709}),
    ])
    monkeypatch.setattr(tdx_minute_import, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        tdx_minute_import,
        "_connect_tdx",
        lambda timeout_seconds: next(connections),
    )
    monkeypatch.setattr(
        tdx_minute_import,
        "_audit_minute_gap_requirements",
        lambda requirements, **_kwargs: {
            "status": "missing",
            "gap_count": len(requirements["items"]),
            "covered_count": 0,
            "missing_count": len(requirements["items"]),
            "coverage_pct": 0.0,
        },
    )
    gap_csv = "trade_date,vt_symbol\n2026-07-10,002730.SZSE\n"

    result = tdx_minute_import.import_tdx_minute_bars_for_gaps(
        gap_csv_text=gap_csv,
        tail_entry_start="09:15",
        tail_entry_end="15:00",
        dry_run=True,
        max_pages_per_symbol=1,
    )

    assert result["status"] == "ready"
    assert result["rows_read"] == 1
    assert result["preview_covered_gap_count"] == 1
    assert result["reconnect_count"] == 1
    assert result["errors"] == []
    assert result["host"]["name"] == "healthy"


def test_tdx_gap_import_endpoint(monkeypatch) -> None:
    from alphaagent.server.api import data_sync

    captured = {}

    def fake_import(**kwargs):
        captured.update(kwargs)
        return {"status": "ready", "rows_read": 1, "rows_written": 0}

    monkeypatch.setattr(data_sync, "import_tdx_minute_bars_for_gaps", fake_import)

    client = TestClient(create_app())
    response = client.post(
        "/api/data-sync/imports/minute-bars/tdx-gaps",
        json={
            "gap_file_path": "memory/06_backtests/gaps.csv",
            "interval": "1m",
            "tail_entry_start": "14:30",
            "dry_run": True,
            "max_gaps": 12,
            "max_pages_per_symbol": 3,
            "timeout_seconds": 1.5,
        },
    )

    assert response.status_code == 200
    assert captured == {
        "gap_csv_text": "",
        "gap_file_path": "memory/06_backtests/gaps.csv",
        "interval": "1m",
        "tail_entry_start": "14:30",
        "tail_entry_end": "14:30",
        "dry_run": True,
        "max_gaps": 12,
        "max_pages_per_symbol": 3,
        "timeout_seconds": 1.5,
    }
    assert response.json()["data"]["status"] == "ready"


def test_backtest_minute_gap_csv_content_uses_rejected_orders() -> None:
    from datetime import date

    from alphaagent.server.services.backtest import engine

    content, gap_count = engine._minute_gap_csv_content(
        [
            {
                "trade_date": date(2026, 5, 11),
                "vt_symbol": "688668.SSE",
                "raw": {
                    "mode": "strict_1430_required",
                    "reference_date": "2026-05-08",
                    "window": "14:30-14:30",
                    "ma5": 220.918,
                    "minute_bar_count": 0,
                    "reason": "missing_1430_snapshot",
                },
            },
            {
                "trade_date": date(2026, 5, 11),
                "vt_symbol": "688668.SSE",
                "raw": {
                    "mode": "strict_1430_required",
                    "reference_date": "2026-05-08",
                    "window": "14:30-14:30",
                    "ma5": 220.918,
                },
            },
            {
                "trade_date": date(2026, 5, 12),
                "vt_symbol": "600000.SSE",
                "raw": {
                    "mode": "strict_1430_required",
                    "reference_date": "2026-05-11",
                    "window": "14:30-14:30",
                    "ma5": 10.5,
                    "price_source": "stock_minute_bars.close_price",
                    "reason": "tail_entry_not_triggered",
                },
            },
            {
                "trade_date": date(2026, 5, 13),
                "vt_symbol": "000001.SZSE",
                "raw": {
                    "mode": "strict_1430_required_sell",
                    "reference_date": "2026-05-13",
                    "window": "14:30-14:30",
                    "minute_bar_count": 0,
                    "reason": "tail_exit_not_triggered",
                },
            },
        ]
    )

    assert gap_count == 2
    assert "trade_date,vt_symbol,reference_date,window,ma5,minute_bar_count,missing_reason" in content
    assert "2026-05-11,688668.SSE,2026-05-08,14:30-14:30,220.918,0,missing_1430_snapshot" in content
    assert "2026-05-13,000001.SZSE,2026-05-13,14:30-14:30,,0,tail_exit_not_triggered" in content
    assert "2026-05-12,600000.SSE" not in content


def test_tushare_gap_import_endpoint(monkeypatch) -> None:
    from alphaagent.server.api import data_sync

    captured = {}

    def fake_import(**kwargs):
        captured.update(kwargs)
        return {"status": "unavailable", "message": "TUSHARE_TOKEN not configured"}

    monkeypatch.setattr(data_sync, "import_tushare_minute_bars_for_gaps", fake_import)

    client = TestClient(create_app())
    response = client.post(
        "/api/data-sync/imports/minute-bars/tushare-gaps",
        json={
            "gap_file_path": "memory/06_backtests/gaps.csv",
            "interval": "1m",
            "tail_entry_start": "14:30",
            "dry_run": True,
            "max_gaps": 20,
        },
    )

    assert response.status_code == 200
    assert captured == {
        "gap_csv_text": "",
        "gap_file_path": "memory/06_backtests/gaps.csv",
        "interval": "1m",
        "tail_entry_start": "14:30",
        "tail_entry_end": "14:30",
        "dry_run": True,
        "max_gaps": 20,
    }
    assert response.json()["data"]["status"] == "unavailable"


def test_strict_minute_pipeline_blocks_when_gap_audit_incomplete(monkeypatch) -> None:
    from alphaagent.server.services.backtest import strict_pipeline
    from alphaagent.server.services.backtest.engine import BacktestParams

    captured = {}

    def fake_audit(**kwargs):
        captured.update(kwargs)
        return {"status": "incomplete", "gap_count": 3, "covered_count": 1, "missing_count": 2, "coverage_pct": 33.3333}

    monkeypatch.setattr(strict_pipeline, "_audit_gap_coverage", fake_audit)
    monkeypatch.setattr(strict_pipeline, "run_backtest", lambda params: (_ for _ in ()).throw(AssertionError("should not run")))

    result = strict_pipeline.run_strict_minute_backtest_pipeline(BacktestParams(max_symbols=20, minute_interval="1m"), gap_csv_text="x")

    assert result["status"] == "blocked_by_minute_gaps"
    assert result["audit"]["missing_count"] == 2
    assert result["params"]["execution_model"] == "strict_1430"
    assert result["params"]["minute_entry_required"] is True
    assert result["params"]["minute_interval"] == "1m"
    assert result["params"]["max_symbols"] == 20
    assert captured["interval"] == "1m"


def test_strict_minute_pipeline_accepts_backtest_id(monkeypatch) -> None:
    from alphaagent.server.services.backtest import strict_pipeline
    from alphaagent.server.services.backtest.engine import BacktestParams

    captured = {}

    monkeypatch.setattr(
        strict_pipeline,
        "backtest_minute_gap_csv",
        lambda backtest_id: {"status": "ready", "content": "trade_date,vt_symbol\n2026-01-08,600000.SSE\n"},
    )
    monkeypatch.setattr(
        strict_pipeline,
        "get_backtest",
        lambda backtest_id: {
            "status": "ready",
            "item": {
                "strategy_id": "mainline_leader_pullback",
                "start_date": "2026-01-01",
                "end_date": "2026-02-01",
                "initial_cash": 1_000_000,
                "params": {"max_symbols": 80, "minute_interval": "1m"},
            },
        },
    )
    monkeypatch.setattr(strict_pipeline, "_audit_gap_coverage", lambda **kwargs: captured.update(kwargs) or {"status": "incomplete"})

    result = strict_pipeline.run_strict_minute_backtest_pipeline(BacktestParams(max_symbols=20, minute_interval="1m"), backtest_id=42)

    assert result["status"] == "blocked_by_minute_gaps"
    assert result["params"]["max_symbols"] == 80
    assert captured["gap_csv_text"].startswith("trade_date,vt_symbol")
    assert captured["gap_file_path"] == ""
    assert captured["tail_entry_start"] == "14:30"


def test_strict_minute_pipeline_runs_when_gap_audit_ready(monkeypatch) -> None:
    from alphaagent.server.services.backtest import strict_pipeline
    from alphaagent.server.services.backtest.engine import BacktestParams

    captured = {}

    def fake_run(params):
        captured["params"] = params
        return {"status": "ready", "backtest_id": 99, "metrics": {"total_return_pct": 1.2}, "start": "2026-01-01", "end": "2026-02-01"}

    monkeypatch.setattr(strict_pipeline, "_audit_gap_coverage", lambda **kwargs: {"status": "ready", "gap_count": 1, "covered_count": 1, "missing_count": 0, "coverage_pct": 100.0})
    monkeypatch.setattr(strict_pipeline, "run_backtest", fake_run)
    monkeypatch.setattr(strict_pipeline, "backtest_report", lambda backtest_id, trade_limit: {"status": "ready", "backtest_id": backtest_id, "metrics": {"total_return_pct": 1.2}})
    monkeypatch.setattr(strict_pipeline, "backtest_report_csv", lambda backtest_id, trade_limit: {"status": "ready", "filename": f"alphaagent_backtest_{backtest_id}.csv"})

    result = strict_pipeline.run_strict_minute_backtest_pipeline(BacktestParams(max_symbols=20, minute_interval="1m"), gap_csv_text="x")

    assert result["status"] == "ready"
    assert result["backtest"]["backtest_id"] == 99
    assert result["csv"]["filename"] == "alphaagent_backtest_99.csv"
    assert captured["params"].minute_entry_required is True
    assert captured["params"].intraday_entry is True
    assert captured["params"].execution_model == "strict_1430"
    assert captured["params"].minute_interval == "1m"
    assert captured["params"].persist is True


def test_strict_minute_pipeline_reuses_source_backtest_params(monkeypatch) -> None:
    from alphaagent.server.services.backtest import strict_pipeline
    from alphaagent.server.services.backtest.engine import BacktestParams

    captured = {}

    monkeypatch.setattr(
        strict_pipeline,
        "backtest_minute_gap_csv",
        lambda backtest_id: {"status": "ready", "content": "trade_date,vt_symbol\n2026-01-08,600000.SSE\n"},
    )
    monkeypatch.setattr(
        strict_pipeline,
        "get_backtest",
        lambda backtest_id: {
            "status": "ready",
            "item": {
                "strategy_id": "mainline_leader_pullback",
                "start_date": "2026-02-02",
                "end_date": "2026-06-13",
                "initial_cash": 1_000_000,
                "params": {
                    "strategy": "mainline_leader_pullback",
                    "start": "2026-02-02",
                    "end": "2026-06-13",
                    "max_symbols": 80,
                    "max_positions": 8,
                    "included_boards": ["main"],
                    "execution_model": "strict_1430",
                    "minute_interval": "1m",
                },
            },
        },
    )

    def fake_run(params):
        captured["params"] = params
        return {"status": "ready", "backtest_id": 99, "metrics": {}, "start": "2026-02-02", "end": "2026-06-13"}

    monkeypatch.setattr(strict_pipeline, "_audit_gap_coverage", lambda **kwargs: {"status": "ready"})
    monkeypatch.setattr(strict_pipeline, "run_backtest", fake_run)
    monkeypatch.setattr(strict_pipeline, "backtest_report", lambda backtest_id, trade_limit: {"status": "ready", "backtest_id": backtest_id})
    monkeypatch.setattr(strict_pipeline, "backtest_report_csv", lambda backtest_id, trade_limit: {"status": "ready", "filename": "report.csv"})

    result = strict_pipeline.run_strict_minute_backtest_pipeline(
        BacktestParams(max_symbols=1500, minute_interval="1m"),
        backtest_id=42,
    )

    assert result["status"] == "ready"
    assert captured["params"].max_symbols == 80
    assert captured["params"].included_boards == ("main",)
    assert captured["params"].execution_model == "strict_1430"
    assert captured["params"].persist is True


def test_strict_minute_pipeline_endpoint(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_pipeline(params, **kwargs):
        captured["params"] = params
        captured.update(kwargs)
        return {"status": "blocked_by_minute_gaps", "audit": {"status": "incomplete"}}

    monkeypatch.setattr(backtests, "run_strict_minute_backtest_pipeline", fake_pipeline)

    client = TestClient(create_app())
    response = client.post(
        "/api/backtests/strict-minute-pipeline",
        json={
            "start": "2026-01-01",
            "max_symbols": 1500,
            "gap_file_path": "memory/06_backtests/gaps.csv",
            "tail_entry_start": "14:30",
            "trade_limit": 12,
        },
    )

    assert response.status_code == 200
    assert captured["gap_file_path"] == "memory/06_backtests/gaps.csv"
    assert captured["trade_limit"] == 12
    assert captured["params"].start.isoformat() == "2026-01-01"
    assert captured["params"].tail_entry_end == "14:30"
    assert response.json()["data"]["status"] == "blocked_by_minute_gaps"


def test_backtest_daily_decision_summary_counts_candidate_order_trade_chain() -> None:
    from alphaagent.server.services.backtest import queries

    summary = queries.daily_decision_summary(
        recommendations=[
            {"trade_date": date(2026, 1, 2), "vt_symbol": "600000.SSE", "action": "BUY"},
            {"trade_date": date(2026, 1, 2), "vt_symbol": "000001.SZSE", "action": "WATCH"},
        ],
        signals=[
            {"trade_date": date(2026, 1, 3), "signal_date": date(2026, 1, 2), "vt_symbol": "600000.SSE", "side": "BUY"},
            {"trade_date": date(2026, 1, 3), "signal_date": date(2026, 1, 2), "vt_symbol": "600000.SSE", "side": "SELL"},
        ],
        orders=[
            {"trade_date": date(2026, 1, 3), "vt_symbol": "600000.SSE", "side": "BUY", "status": "filled"},
            {"trade_date": date(2026, 1, 3), "vt_symbol": "000001.SZSE", "side": "BUY", "status": "rejected", "reason": "tail_entry_not_triggered"},
            {"trade_date": date(2026, 1, 3), "vt_symbol": "600000.SSE", "side": "SELL", "status": "filled"},
        ],
        trades=[
            {"trade_date": date(2026, 1, 3), "vt_symbol": "600000.SSE", "side": "BUY", "amount": 10_000.0, "fee": 3.0},
            {"trade_date": date(2026, 1, 3), "vt_symbol": "600000.SSE", "side": "SELL", "amount": 10_500.0, "fee": 8.0, "pnl": 489.0},
        ],
    )

    assert summary["status"] == "traded"
    assert summary["buy_candidate_count"] == 1
    assert summary["watch_candidate_count"] == 1
    assert summary["buy_signal_count"] == 1
    assert summary["sell_signal_count"] == 1
    assert summary["buy_order_count"] == 2
    assert summary["sell_order_count"] == 1
    assert summary["buy_trade_count"] == 1
    assert summary["sell_trade_count"] == 1
    assert summary["buy_amount"] == 10_003.0
    assert summary["sell_cash_in"] == 10_492.0
    assert summary["realized_pnl"] == 489.0
    assert summary["rejected_reasons"] == [{"reason": "tail_entry_not_triggered", "reason_label": "尾盘入场未触发", "count": 1}]


def test_backtest_daily_decision_rows_map_signal_date_candidates_to_execute_day() -> None:
    from alphaagent.server.services.backtest import queries

    rows = queries.daily_decision_rows(
        equity_rows=[
            {"trade_date": date(2026, 1, 2), "cash": 100_000.0, "market_value": 0.0, "total_equity": 100_000.0, "position_count": 0},
            {"trade_date": date(2026, 1, 5), "cash": 89_997.0, "market_value": 10_100.0, "total_equity": 100_097.0, "position_count": 1},
        ],
        recommendations=[
            {"trade_date": date(2026, 1, 2), "vt_symbol": "600000.SSE", "action": "BUY"},
            {"trade_date": date(2026, 1, 2), "vt_symbol": "000001.SZSE", "action": "WATCH"},
        ],
        signals=[
            {"trade_date": date(2026, 1, 5), "signal_date": date(2026, 1, 2), "execute_date": date(2026, 1, 5), "vt_symbol": "600000.SSE", "side": "BUY"},
        ],
        orders=[
            {"trade_date": date(2026, 1, 5), "vt_symbol": "600000.SSE", "side": "BUY", "status": "filled"},
        ],
        trades=[
            {"trade_date": date(2026, 1, 5), "vt_symbol": "600000.SSE", "side": "BUY", "amount": 10_000.0, "fee": 3.0},
        ],
        position_counts=[
            {"trade_date": date(2026, 1, 5), "position_snapshot_count": 1},
        ],
    )

    by_date = {row["trade_date"]: row for row in rows}
    execute_day = by_date[date(2026, 1, 5)]
    assert execute_day["source_signal_dates"] == [date(2026, 1, 2)]
    assert execute_day["buy_candidate_count"] == 1
    assert execute_day["watch_candidate_count"] == 1
    assert execute_day["buy_signal_count"] == 1
    assert execute_day["buy_trade_count"] == 1
    assert execute_day["buy_amount"] == 10_003.0
    assert execute_day["position_snapshot_count"] == 1


def test_backtest_trade_attribution_reports_floating_extremes() -> None:
    from alphaagent.server.services.backtest import queries

    rows = queries.trade_attribution(
        trades=[
            {
                "trade_date": date(2026, 1, 2),
                "vt_symbol": "600000.SSE",
                "side": "BUY",
                "price": 10.0,
                "volume": 1000,
                "amount": 10_000.0,
                "fee": 3.0,
                "raw": {
                    "entry_total_score": 91.5,
                    "dragon_state": "TAIL_BUY_READY",
                    "support_type": "ma5_reclaim",
                    "low_suction_days": 4,
                    "low_suction_buildup_score": 96.0,
                    "ma_convergence_pct": 2.4,
                    "failed_rules": [],
                    "execution": {"mode": "minute_1430", "price_source": "stock_minute_bars.close_price", "proxy_used": False},
                },
            },
            {
                "trade_date": date(2026, 1, 5),
                "vt_symbol": "600000.SSE",
                "side": "SELL",
                "price": 10.8,
                "volume": 1000,
                "amount": 10_800.0,
                "fee": 8.4,
                "pnl": 788.6,
                "reason": "take_profit",
            },
        ],
        positions=[
            {"trade_date": date(2026, 1, 2), "vt_symbol": "600000.SSE", "floating_pnl": 100.0, "floating_pnl_pct": 1.0},
            {"trade_date": date(2026, 1, 3), "vt_symbol": "600000.SSE", "floating_pnl": -250.0, "floating_pnl_pct": -2.5},
            {"trade_date": date(2026, 1, 4), "vt_symbol": "600000.SSE", "floating_pnl": 900.0, "floating_pnl_pct": 9.0},
        ],
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "closed"
    assert row["entry_date"] == date(2026, 1, 2)
    assert row["exit_date"] == date(2026, 1, 5)
    assert row["pnl"] == 788.6
    assert row["return_pct"] == 7.886
    assert row["max_floating_pnl"] == 900.0
    assert row["min_floating_pnl"] == -250.0
    assert row["max_floating_pnl_pct"] == 9.0
    assert row["min_floating_pnl_pct"] == -2.5
    assert row["entry_score"] == 91.5
    assert row["entry_state"] == "TAIL_BUY_READY"
    assert row["entry_support_type"] == "ma5_reclaim"
    assert row["low_suction_days"] == 4
    assert row["low_suction_buildup_score"] == 96.0
    assert row["ma_convergence_pct"] == 2.4
    assert row["entry_failed_rules"] == []
    assert row["execution_mode"] == "minute_1430"
    assert row["exit_reason_label"] == "止盈"


def test_trade_path_diagnostics_calculates_mae_mfe_and_post_exit_return() -> None:
    from alphaagent.server.services.backtest import queries

    entry = {
        "id": 1,
        "trade_date": date(2026, 4, 1),
        "vt_symbol": "002208.SZSE",
        "side": "BUY",
        "price": 10.0,
        "amount": 1000.0,
        "fee": 1.0,
        "raw": {
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 4,
            "low_suction_launch_confirmed": True,
            "entry_total_score": 78.0,
        },
    }
    exit_trade = {
        "id": 2,
        "trade_date": date(2026, 4, 8),
        "vt_symbol": "002208.SZSE",
        "side": "SELL",
        "price": 9.6,
        "amount": 960.0,
        "fee": 1.0,
        "pnl": -42.0,
        "reason": "support_stop",
        "raw": {},
    }
    positions = [
        {"trade_date": date(2026, 4, 2), "vt_symbol": "002208.SZSE", "floating_pnl_pct": -2.0, "close_price": 9.8},
        {"trade_date": date(2026, 4, 3), "vt_symbol": "002208.SZSE", "floating_pnl_pct": 5.0, "close_price": 10.5},
        {"trade_date": date(2026, 4, 8), "vt_symbol": "002208.SZSE", "floating_pnl_pct": -4.0, "close_price": 9.6},
    ]
    future_bars = [
        {"trade_date": date(2026, 4, 9), "vt_symbol": "002208.SZSE", "close_price": 10.2},
        {"trade_date": date(2026, 4, 10), "vt_symbol": "002208.SZSE", "close_price": 11.2},
    ]

    row = queries.trade_path_diagnostic_row("002208.SZSE", entry, exit_trade, positions, future_bars, lookahead_days=5)

    assert row["entry_setup"] == "stealth_low_suction"
    assert row["mae_pct"] == -4.0
    assert row["mfe_pct"] == 5.0
    assert row["early_mae_pct"] == -4.0
    assert row["early_mfe_pct"] == 5.0
    assert row["early_follow_through_state"] == "confirmed_follow_through"
    assert row["post_exit_max_return_pct"] == 16.6667
    assert row["sold_before_rebound"] is True


def test_trade_path_diagnostics_marks_failed_early_follow_through() -> None:
    from alphaagent.server.services.backtest import queries

    entry = {
        "id": 1,
        "trade_date": date(2026, 3, 12),
        "vt_symbol": "600352.SSE",
        "side": "BUY",
        "price": 10.0,
        "raw": {"entry_setup": "stealth_low_suction", "entry_total_score": 82.0},
    }
    exit_trade = {
        "id": 2,
        "trade_date": date(2026, 3, 16),
        "vt_symbol": "600352.SSE",
        "side": "SELL",
        "price": 9.15,
        "reason": "support_stop",
        "raw": {},
    }
    positions = [
        {"trade_date": date(2026, 3, 12), "vt_symbol": "600352.SSE", "floating_pnl_pct": -1.8},
        {"trade_date": date(2026, 3, 13), "vt_symbol": "600352.SSE", "floating_pnl_pct": -4.4},
        {"trade_date": date(2026, 3, 16), "vt_symbol": "600352.SSE", "floating_pnl_pct": -8.5},
    ]

    row = queries.trade_path_diagnostic_row("600352.SSE", entry, exit_trade, positions)
    enriched = queries.setup_market_exit_audit_summary([row])

    assert row["early_follow_through_days"] == 3
    assert row["early_mae_pct"] == -8.5
    assert row["early_mfe_pct"] == -1.8
    assert row["early_follow_through_state"] == "failed_launch"
    assert enriched["overall"]["entry_follow_through_issue_count"] == 1
    assert enriched["by_early_follow_through"][0]["early_follow_through_state"] == "failed_launch"
    assert enriched["by_entry_launch_diagnostic"][0]["entry_launch_diagnostic_state"] == "failed_launch"
    assert enriched["by_entry_context"][0]["label"] == "市场环境未知"


def test_low_suction_confirmed_path_item_compares_current_fixed_and_model_exits() -> None:
    from alphaagent.server.services.backtest import queries

    entry = {
        "id": 1,
        "trade_date": date(2026, 4, 1),
        "vt_symbol": "002384.SZSE",
        "side": "BUY",
        "price": 10.0,
        "amount": 10_000.0,
        "raw": {
            "entry_setup": "stealth_low_suction",
            "entry_total_score": 92.0,
            "low_suction_days": 5,
            "low_suction_launch_quality_bucket": "balanced_first_lift",
            "execution": {"mode": "low_suction_trigger_day_confirmed_next_open"},
            "trigger_day_confirmation": {"confirmed": True, "trigger_date": "2026-03-31"},
        },
    }
    exit_trade = {
        "id": 2,
        "trade_date": date(2026, 4, 8),
        "vt_symbol": "002384.SZSE",
        "side": "SELL",
        "price": 9.8,
        "amount": 9_800.0,
        "pnl": -220.0,
        "reason": "support_stop",
        "raw": {},
    }
    bars = [
        {"trade_date": date(2026, 4, 1), "vt_symbol": "002384.SZSE", "open_price": 10.0, "high_price": 10.4, "low_price": 9.9, "close_price": 10.2},
        {"trade_date": date(2026, 4, 2), "vt_symbol": "002384.SZSE", "open_price": 10.2, "high_price": 10.6, "low_price": 10.0, "close_price": 10.4},
        {"trade_date": date(2026, 4, 3), "vt_symbol": "002384.SZSE", "open_price": 10.4, "high_price": 11.0, "low_price": 10.2, "close_price": 10.8},
        {"trade_date": date(2026, 4, 6), "vt_symbol": "002384.SZSE", "open_price": 10.8, "high_price": 11.5, "low_price": 10.7, "close_price": 11.2},
        {"trade_date": date(2026, 4, 7), "vt_symbol": "002384.SZSE", "open_price": 11.2, "high_price": 10.7, "low_price": 10.2, "close_price": 10.3},
    ]

    item = queries.low_suction_confirmed_path_item(entry, exit_trade, bars, lookahead_days=20)

    assert item["execution_mode"] == "low_suction_trigger_day_confirmed_next_open"
    assert item["current_exit_return_pct"] == -2.0
    assert item["fixed_5d_return_pct"] == 3.0
    assert item["forward_mfe_pct"] == 15.0
    assert item["forward_mae_pct"] == -1.0
    assert item["failed_follow_exit_triggered"] is False
    assert item["trend_giveback_exit_triggered"] is True
    assert item["low_suction_model_exit_type"] == "trend_giveback"
    assert item["low_suction_model_return_pct"] == 3.0
    assert item["model_vs_current_delta_pct"] == 5.0
    assert item["not_used_for_signal_score"] is True


def test_low_suction_confirmed_path_item_marks_failed_follow_exit() -> None:
    from alphaagent.server.services.backtest import queries

    entry = {
        "id": 1,
        "trade_date": date(2026, 4, 1),
        "vt_symbol": "600352.SSE",
        "side": "BUY",
        "price": 10.0,
        "amount": 10_000.0,
        "raw": {"execution": {"mode": "low_suction_trigger_day_confirmed_next_open"}},
    }
    exit_trade = {
        "id": 2,
        "trade_date": date(2026, 4, 3),
        "vt_symbol": "600352.SSE",
        "side": "SELL",
        "price": 9.2,
        "amount": 9_200.0,
        "pnl": -820.0,
        "reason": "support_stop",
        "raw": {},
    }
    bars = [
        {"trade_date": date(2026, 4, 1), "vt_symbol": "600352.SSE", "high_price": 10.1, "low_price": 9.6, "close_price": 9.7},
        {"trade_date": date(2026, 4, 2), "vt_symbol": "600352.SSE", "high_price": 9.9, "low_price": 9.4, "close_price": 9.5},
    ]

    item = queries.low_suction_confirmed_path_item(entry, exit_trade, bars, lookahead_days=20)
    summary = queries.low_suction_confirmed_path_audit_summary([item])

    assert item["current_exit_return_pct"] == -8.0
    assert item["failed_follow_exit_triggered"] is True
    assert item["low_suction_model_exit_type"] == "failed_follow"
    assert item["low_suction_model_return_pct"] == -3.0
    assert summary["overall"]["failed_follow_exit_count"] == 1
    assert summary["overall"]["current_exit"]["avg_return_pct"] == -8.0
    assert summary["overall"]["low_suction_model"]["avg_return_pct"] == -3.0
    assert "低吸专用失败/回撤模型优于当前卖点代理" in " ".join(summary["read"]["notes"])


def test_trade_path_diagnostics_marks_low_suction_dragon_context() -> None:
    from alphaagent.server.services.backtest import queries

    entry = {
        "id": 1,
        "trade_date": date(2026, 3, 12),
        "vt_symbol": "600352.SSE",
        "side": "BUY",
        "price": 10.0,
        "raw": {
            "entry_setup": "stealth_low_suction",
            "entry_total_score": 95.0,
            "low_suction_days": 6,
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "late_pullback_launch",
            "low_suction_launch_quality_label": "低吸启动回踩过久",
            "ma_convergence_pct": 4.0,
            "volume_ratio_5d_20d": 0.85,
            "pullback_days": 13,
            "close_location_in_range": 0.62,
        },
    }
    exit_trade = {
        "id": 2,
        "trade_date": date(2026, 3, 16),
        "vt_symbol": "600352.SSE",
        "side": "SELL",
        "price": 9.15,
        "reason": "support_stop",
        "raw": {},
    }
    positions = [
        {"trade_date": date(2026, 3, 12), "vt_symbol": "600352.SSE", "floating_pnl_pct": -1.8},
        {"trade_date": date(2026, 3, 13), "vt_symbol": "600352.SSE", "floating_pnl_pct": -4.4},
        {"trade_date": date(2026, 3, 16), "vt_symbol": "600352.SSE", "floating_pnl_pct": -8.5},
    ]

    row = queries.trade_path_diagnostic_row("600352.SSE", entry, exit_trade, positions)
    enriched_row = queries.setup_market_exit_audit_summary([row])
    context_bucket = enriched_row["by_low_suction_dragon_context"][0]

    assert row["low_suction_launch_quality_bucket"] == "late_pullback_launch"
    assert context_bucket["low_suction_dragon_state"] == "low_suction_confirmed_failed_follow"
    assert context_bucket["label"] == "低吸确认后无承接"
    assert context_bucket["trade_count"] == 1
    assert queries.trade_path_diagnostics_summary([row])["by_low_suction_dragon_context"][0]["label"] == "低吸确认后无承接"


def test_trade_path_diagnostics_marks_market_mainline_context_buckets() -> None:
    from alphaagent.server.services.backtest import queries

    rows = [
        {
            "entry_setup": "dragon_pullback",
            "return_pct": 8.0,
            "dynamic_market_regime": "narrow_theme_bull",
            "dynamic_market_label": "窄幅主线牛",
            "theme_state": "active_pullback",
            "stock_theme_alignment": "leader_theme",
            "dominant_theme": "光模块",
            "market_warning_level": 1,
            "fund_flow_state": "balanced",
            "early_follow_through_state": "confirmed_follow_through",
        },
        {
            "entry_setup": "stealth_low_suction",
            "return_pct": -6.0,
            "dynamic_market_regime": "weak_defensive",
            "dynamic_market_label": "弱势防守",
            "theme_state": "none",
            "stock_theme_alignment": "isolated_candidate",
            "market_warning_level": 3,
            "fund_flow_state": "continuous_outflow",
            "early_follow_through_state": "failed_launch",
        },
        {
            "entry_setup": "stealth_low_suction",
            "return_pct": 2.0,
            "dynamic_market_regime": "choppy_rotation",
            "dynamic_market_label": "震荡轮动",
            "theme_state": "emerging",
            "stock_theme_alignment": "unknown",
            "market_warning_level": 1,
            "fund_flow_state": "balanced",
            "early_follow_through_state": "weak_follow_through",
        },
    ]

    summary = queries.trade_path_diagnostics_summary(rows)
    buckets = {row["market_mainline_trade_context"]: row for row in summary["by_market_mainline_trade_context"]}

    assert buckets["mainline_pullback"]["label"] == "主线分歧回踩"
    assert buckets["risk_off"]["label"] == "退潮/弱市防守"
    assert buckets["rotation_low_suction_watch"]["label"] == "震荡低吸观察"
    assert buckets["mainline_pullback"]["trade_count"] == 1


def test_trade_path_diagnostics_marks_rebound_prone_support_stop_review_from_visible_context() -> None:
    from alphaagent.server.services.backtest import queries

    entry = {
        "id": 1,
        "trade_date": date(2026, 4, 1),
        "vt_symbol": "002384.SZSE",
        "side": "BUY",
        "price": 10.0,
        "raw": {"entry_setup": "stealth_low_suction", "entry_total_score": 86.0},
    }
    exit_trade = {
        "id": 2,
        "trade_date": date(2026, 4, 8),
        "vt_symbol": "002384.SZSE",
        "side": "SELL",
        "price": 9.5,
        "reason": "support_stop",
        "raw": {},
    }
    positions = [
        {"trade_date": date(2026, 4, 2), "vt_symbol": "002384.SZSE", "floating_pnl_pct": 0.8},
        {"trade_date": date(2026, 4, 3), "vt_symbol": "002384.SZSE", "floating_pnl_pct": 2.2},
        {"trade_date": date(2026, 4, 7), "vt_symbol": "002384.SZSE", "floating_pnl_pct": -3.6},
    ]
    daily_bars = [
        {
            "trade_date": date(2026, 4, 6),
            "vt_symbol": "002384.SZSE",
            "open_price": 10.2,
            "high_price": 10.4,
            "low_price": 10.0,
            "close_price": 10.1,
            "change_pct": -0.5,
        },
        {
            "trade_date": date(2026, 4, 7),
            "vt_symbol": "002384.SZSE",
            "open_price": 10.1,
            "high_price": 10.35,
            "low_price": 9.35,
            "close_price": 9.5,
            "change_pct": -5.94,
        },
        {
            "trade_date": date(2026, 4, 8),
            "vt_symbol": "002384.SZSE",
            "open_price": 9.5,
            "high_price": 9.7,
            "low_price": 9.3,
            "close_price": 9.45,
            "change_pct": -0.53,
        },
    ]
    future_bars = [
        {"trade_date": date(2026, 4, 9), "vt_symbol": "002384.SZSE", "close_price": 9.6},
        {"trade_date": date(2026, 4, 10), "vt_symbol": "002384.SZSE", "close_price": 9.8},
    ]

    row = queries.trade_path_diagnostic_row(
        "002384.SZSE",
        entry,
        exit_trade,
        positions,
        future_bars,
        lookahead_days=5,
        daily_bars=daily_bars,
    )

    assert row["sell_signal_date"] == date(2026, 4, 7)
    assert row["sell_signal_intraday_range_pct"] == 10.5263
    assert row["sell_signal_gap_pct"] == 0.0
    assert row["early_mfe_pct"] == 2.2
    assert row["mfe_pct"] == 2.2
    assert row["rebound_prone_support_stop_review"] is True
    assert row["rebound_prone_support_stop_score"] >= 60.0
    assert row["sold_before_rebound"] is False


def test_trade_path_diagnostics_marks_probable_unadjusted_price_discontinuity() -> None:
    from alphaagent.server.services.backtest import queries

    entry = {
        "id": 1,
        "trade_date": date(2026, 4, 1),
        "vt_symbol": "001207.SZSE",
        "side": "BUY",
        "price": 10.0,
        "raw": {"entry_setup": "stealth_low_suction", "entry_total_score": 86.0},
    }
    exit_trade = {
        "id": 2,
        "trade_date": date(2026, 4, 10),
        "vt_symbol": "001207.SZSE",
        "side": "SELL",
        "price": 7.3,
        "reason": "support_stop",
        "raw": {},
    }
    daily_bars = [
        {
            "trade_date": date(2026, 4, 1),
            "vt_symbol": "001207.SZSE",
            "open_price": 10.0,
            "high_price": 10.2,
            "low_price": 9.8,
            "close_price": 10.0,
            "change_pct": 0.0,
        },
        {
            "trade_date": date(2026, 4, 2),
            "vt_symbol": "001207.SZSE",
            "open_price": 10.0,
            "high_price": 10.3,
            "low_price": 9.9,
            "close_price": 10.1,
            "change_pct": 1.0,
        },
        {
            "trade_date": date(2026, 4, 8),
            "vt_symbol": "001207.SZSE",
            "open_price": 7.1,
            "high_price": 7.4,
            "low_price": 7.0,
            "close_price": 7.3,
            "change_pct": -27.0608,
        },
        {
            "trade_date": date(2026, 4, 10),
            "vt_symbol": "001207.SZSE",
            "open_price": 7.3,
            "high_price": 7.5,
            "low_price": 7.2,
            "close_price": 7.35,
            "change_pct": 0.68,
        },
    ]

    row = queries.trade_path_diagnostic_row("001207.SZSE", entry, exit_trade, positions=[], daily_bars=daily_bars)

    assert row["has_price_discontinuity"] is True
    assert row["first_price_discontinuity_date"] == date(2026, 4, 8)
    assert row["first_price_discontinuity_open_gap_pct"] < -20.0


def test_rebound_prone_review_ignores_non_support_stop() -> None:
    from alphaagent.server.services.backtest import queries

    entry = {"id": 1, "trade_date": date(2026, 4, 1), "vt_symbol": "002119.SZSE", "side": "BUY", "price": 10.0, "raw": {}}
    exit_trade = {
        "id": 2,
        "trade_date": date(2026, 4, 8),
        "vt_symbol": "002119.SZSE",
        "side": "SELL",
        "price": 9.5,
        "reason": "trend_break",
        "raw": {},
    }
    positions = [
        {"trade_date": date(2026, 4, 2), "vt_symbol": "002119.SZSE", "floating_pnl_pct": 1.0},
        {"trade_date": date(2026, 4, 3), "vt_symbol": "002119.SZSE", "floating_pnl_pct": 2.0},
        {"trade_date": date(2026, 4, 7), "vt_symbol": "002119.SZSE", "floating_pnl_pct": -3.5},
    ]
    daily_bars = [
        {"trade_date": date(2026, 4, 6), "vt_symbol": "002119.SZSE", "open_price": 10.2, "high_price": 10.4, "low_price": 10.0, "close_price": 10.1},
        {"trade_date": date(2026, 4, 7), "vt_symbol": "002119.SZSE", "open_price": 10.1, "high_price": 10.4, "low_price": 9.3, "close_price": 9.5},
        {"trade_date": date(2026, 4, 8), "vt_symbol": "002119.SZSE", "open_price": 9.5, "high_price": 9.7, "low_price": 9.3, "close_price": 9.45},
    ]

    row = queries.trade_path_diagnostic_row("002119.SZSE", entry, exit_trade, positions, daily_bars=daily_bars)

    assert row["sell_signal_intraday_range_pct"] >= 5.0
    assert row["rebound_prone_support_stop_review"] is False
    assert row["rebound_prone_support_stop_score"] == 0.0


def test_trade_path_diagnostics_pairs_buy_sell_trades_fifo() -> None:
    from alphaagent.server.services.backtest import queries

    trades = [
        {"id": 1, "trade_date": date(2026, 4, 1), "vt_symbol": "A", "side": "BUY", "price": 10.0, "raw": {"entry_setup": "dragon_pullback"}},
        {"id": 2, "trade_date": date(2026, 4, 2), "vt_symbol": "A", "side": "BUY", "price": 11.0, "raw": {"entry_setup": "stealth_low_suction"}},
        {"id": 3, "trade_date": date(2026, 4, 5), "vt_symbol": "A", "side": "SELL", "price": 12.0, "reason": "trend_trailing_stop", "raw": {}},
        {"id": 4, "trade_date": date(2026, 4, 6), "vt_symbol": "A", "side": "SELL", "price": 10.5, "reason": "support_stop", "raw": {}},
    ]

    rows = queries.trade_path_diagnostics_from_trades(trades, positions=[], future_bars=[])

    assert [row["entry_price"] for row in rows] == [10.0, 11.0]
    assert [row["exit_price"] for row in rows] == [12.0, 10.5]
    assert [round(row["return_pct"], 4) for row in rows] == [20.0, -4.5455]


def test_theoretical_position_context_uses_execute_date_not_signal_date() -> None:
    from alphaagent.server.services.backtest import queries

    signal_date = date(2026, 4, 1)
    rows = [
        {
            "id": 1,
            "signal_date": signal_date,
            "trade_date": date(2026, 4, 2),
            "execute_date": date(2026, 4, 2),
            "vt_symbol": "A",
            "side": "BUY",
            "raw": {"status": "filled"},
        }
    ]

    assert queries._theoretical_position_context("A", rows, signal_date)["held"] is False
    assert queries._theoretical_position_context("A", rows, date(2026, 4, 2)) == {"held": True, "entry_date": "2026-04-02"}
    rows.append(
        {
            "id": 2,
            "signal_date": date(2026, 4, 3),
            "trade_date": date(2026, 4, 6),
            "execute_date": date(2026, 4, 6),
            "vt_symbol": "A",
            "side": "SELL",
            "raw": {"status": "filled"},
        }
    )
    assert queries._theoretical_position_context("A", rows, date(2026, 4, 5)) == {"held": True, "entry_date": "2026-04-02"}
    assert queries._theoretical_position_context("A", rows, date(2026, 4, 6)) == {"held": False, "entry_date": None}


def test_backtest_path_diagnostics_attaches_read_only_market_context(monkeypatch) -> None:
    from alphaagent.server.services.backtest import queries
    from alphaagent.server.db import schema as db_schema

    class FakeResult:
        def __init__(self, rows=None, first=None):
            self._rows = rows or []
            self._first = first

        def mappings(self):
            return self

        def first(self):
            return self._first

        def all(self):
            return self._rows

    class FakeSession:
        def __init__(self):
            self.daily_bar_calls = 0

        def execute(self, statement):
            text = str(statement)
            if "FROM backtest_runs" in text:
                return FakeResult(
                    first={
                        "id": 194,
                        "start_date": date(2026, 4, 1),
                        "end_date": date(2026, 4, 10),
                    }
                )
            if "FROM backtest_trades" in text:
                return FakeResult(
                    rows=[
                        {
                            "id": 1,
                            "trade_date": date(2026, 4, 1),
                            "vt_symbol": "002384.SZSE",
                            "side": "BUY",
                            "price": 10.0,
                            "amount": 1000.0,
                            "fee": 1.0,
                            "raw": {"entry_setup": "stealth_low_suction", "entry_total_score": 86.0},
                        },
                        {
                            "id": 2,
                            "trade_date": date(2026, 4, 8),
                            "vt_symbol": "002384.SZSE",
                            "side": "SELL",
                            "price": 9.5,
                            "amount": 950.0,
                            "fee": 1.0,
                            "pnl": -52.0,
                            "reason": "support_stop",
                            "raw": {},
                        },
                    ]
                )
            if "FROM backtest_daily_positions" in text:
                return FakeResult(
                    rows=[
                        {"trade_date": date(2026, 4, 2), "vt_symbol": "002384.SZSE", "floating_pnl_pct": 1.2},
                        {"trade_date": date(2026, 4, 3), "vt_symbol": "002384.SZSE", "floating_pnl_pct": 2.2},
                        {"trade_date": date(2026, 4, 7), "vt_symbol": "002384.SZSE", "floating_pnl_pct": -3.0},
                    ]
                )
            if "FROM stock_daily_bars" in text:
                self.daily_bar_calls += 1
                if self.daily_bar_calls == 1:
                    return FakeResult(rows=[{"trade_date": date(2026, 4, 9), "vt_symbol": "002384.SZSE", "close_price": 9.8}])
                return FakeResult(
                    rows=[
                        {
                            "trade_date": date(2026, 4, 7),
                            "vt_symbol": "002384.SZSE",
                            "open_price": 10.1,
                            "high_price": 10.35,
                            "low_price": 9.35,
                            "close_price": 9.5,
                            "change_pct": -5.94,
                        },
                        {
                            "trade_date": date(2026, 4, 8),
                            "vt_symbol": "002384.SZSE",
                            "open_price": 9.5,
                            "high_price": 9.7,
                            "low_price": 9.3,
                            "close_price": 9.45,
                            "change_pct": -0.53,
                        },
                    ]
                )
            raise AssertionError(text)

    sessions: list[FakeSession] = []

    @contextmanager
    def fake_session_scope():
        session = FakeSession()
        sessions.append(session)
        yield session

    def fake_market_context(session, schema, rows, *, date_key):
        assert date_key == "entry_date"
        assert rows[0]["entry_date"] == date(2026, 4, 1)
        return [
            {
                **row,
                "dynamic_market_regime": "weak_defensive",
                "dynamic_market_label": "弱势防守",
                "dynamic_market_source": "stock_daily_bars",
                "market_warning_level": 3,
                "market_warning_label": "强风险",
                "fund_flow_state": "continuous_outflow",
                "fund_flow_label": "资金连续流出",
                "fund_flow_source": "sector_fund_flows",
                "recovery_label": "未回暖",
            }
            for row in rows
        ]

    monkeypatch.setattr(queries.market_context, "annotate_rows_with_market_context", fake_market_context)

    result = queries.backtest_path_diagnostics(
        schema=db_schema,
        session_scope=fake_session_scope,
        is_database_configured=lambda: True,
        ensure_schema=lambda: None,
        load_stock_names=lambda session, symbols: {},
        symbols_from_rows=lambda *rows: [],
        with_stock_names=lambda rows, stock_names: rows,
        to_api=lambda row: row,
        backtest_id=194,
    )

    assert result["status"] == "ready"
    assert result["items"][0]["dynamic_market_regime"] == "weak_defensive"
    assert result["items"][0]["market_warning_label"] == "强风险"
    assert result["items"][0]["entry_context_state"] == "risk_off"
    assert result["items"][0]["fund_flow_coverage_state"] == "market_fund_flow"
    assert result["summary"]["by_dynamic_market_regime"][0]["dynamic_market_regime"] == "weak_defensive"
    assert result["summary"]["by_market_warning"][0]["market_warning_label"] == "强风险"
    assert result["summary"]["by_entry_context"][0]["entry_context_state"] == "risk_off"
    assert result["summary"]["dynamic_market_sources"] == [{"source": "stock_daily_bars", "count": 1}]


def test_low_suction_start_factor_summary_compares_winners_and_losers() -> None:
    from alphaagent.server.services.backtest import queries

    rows = [
        {
            "entry_setup": "stealth_low_suction",
            "return_pct": 18.0,
            "limit_up_start_factor_count": 4,
            "recent_limit_up_20d": True,
            "consecutive_bull_closes": 5,
            "upward_gap_in_leg": True,
            "persistent_volume_expansion": True,
            "weak_index_strength_confirmation": True,
        },
        {
            "entry_setup": "stealth_low_suction",
            "return_pct": -6.0,
            "limit_up_start_factor_count": 1,
            "recent_limit_up_20d": False,
            "consecutive_bull_closes": 2,
            "upward_gap_in_leg": False,
            "persistent_volume_expansion": True,
            "index_return_20d": -2.0,
        },
        {
            "entry_setup": "dragon_pullback",
            "return_pct": 10.0,
            "limit_up_start_factor_count": 4,
        },
    ]

    summary = queries.low_suction_start_factor_summary(rows)

    assert summary["total"] == 2
    assert summary["winner_count"] == 1
    assert summary["loser_count"] == 1
    assert summary["winner_factor_avg"] == 4.0
    assert summary["loser_factor_avg"] == 1.0
    assert summary["weak_or_sideways_index_count"] == 2
    assert summary["factor_buckets"][0]["bucket"] == "0-1"
    assert summary["factor_buckets"][0]["trade_count"] == 1
    assert summary["factor_buckets"][2]["bucket"] == "3-4"
    assert summary["factor_buckets"][2]["win_rate"] == 100.0


def test_setup_market_exit_audit_summary_finds_entry_and_exit_issue_buckets() -> None:
    from alphaagent.server.services.backtest import queries

    rows = [
        {
            "entry_setup": "stealth_low_suction",
            "dynamic_market_regime": "false_bull",
            "dynamic_market_label": "假强势",
            "market_warning_label": "风险",
            "market_warning_level": 3,
            "exit_reason": "support_stop",
            "return_pct": -6.0,
            "mae_pct": -7.2,
            "mfe_pct": 1.5,
            "early_follow_through_state": "failed_launch",
            "early_follow_through_label": "启动后立即失败",
            "sold_before_rebound": False,
        },
        {
            "entry_setup": "stealth_low_suction",
            "dynamic_market_regime": "false_bull",
            "dynamic_market_label": "假强势",
            "market_warning_label": "风险",
            "exit_reason": "trend_trailing_stop",
            "return_pct": 4.0,
            "mae_pct": -1.0,
            "mfe_pct": 16.0,
            "recovery_state": "warming_confirmed",
            "recovery_label": "回暖确认",
            "early_follow_through_state": "confirmed_follow_through",
            "early_follow_through_label": "买后资金跟随",
            "sold_before_rebound": False,
        },
        {
            "entry_setup": "dragon_pullback",
            "dynamic_market_regime": "strong_broad",
            "dynamic_market_label": "全面强势",
            "market_warning_label": "正常",
            "exit_reason": "trend_break",
            "return_pct": -2.0,
            "mae_pct": -4.0,
            "mfe_pct": 2.5,
            "early_follow_through_state": "weak_follow_through",
            "early_follow_through_label": "买后弱跟随",
            "sold_before_rebound": True,
        },
    ]

    summary = queries.setup_market_exit_audit_summary(rows)

    assert summary["overall"]["trade_count"] == 3
    assert summary["overall"]["entry_follow_through_issue_count"] == 1
    assert summary["overall"]["entry_quality_issue_count"] == 0
    assert summary["overall"]["exit_giveback_count"] == 1
    assert summary["overall"]["sold_before_rebound_count"] == 1
    assert summary["overall"]["failed_launch_count"] == 1
    assert summary["overall"]["confirmed_follow_through_count"] == 1
    assert summary["by_entry_setup"][0]["entry_setup"] == "stealth_low_suction"
    short_term_buckets = {row["short_term_trade_context"]: row for row in summary["by_short_term_trade_context"]}
    assert short_term_buckets["defensive_tide"]["label"] == "退潮防守"
    assert short_term_buckets["trend_profit_giveback"]["trade_count"] == 1
    follow_through_buckets = {row["early_follow_through_state"]: row for row in summary["by_early_follow_through"]}
    assert follow_through_buckets["confirmed_follow_through"]["label"] == "买后资金跟随"
    assert follow_through_buckets["failed_launch"]["trade_count"] == 1
    assert summary["by_dynamic_market_regime"][0]["dynamic_market_regime"] == "false_bull"
    matrix = summary["setup_market_exit_matrix"]
    assert matrix[0]["entry_setup"] == "stealth_low_suction"
    assert matrix[0]["dynamic_market_regime"] == "false_bull"
    assert matrix[0]["exit_reason"] == "support_stop"
    assert matrix[0]["entry_follow_through_issue_count"] == 1


def test_setup_market_exit_audit_summary_exposes_plan_validation_nodes() -> None:
    from alphaagent.server.services.backtest import queries

    rows = [
        {
            "entry_setup": "stealth_low_suction",
            "dynamic_market_regime": "false_bull",
            "dynamic_market_label": "假强势",
            "market_warning_level": 3,
            "market_warning_label": "风险",
            "market_recovery_level": 0,
            "market_recovery_label": "未回暖",
            "fund_flow_state": "insufficient_data",
            "fund_flow_source": "",
            "exit_reason": "support_stop",
            "return_pct": -6.0,
            "return_20d": -4.0,
            "mfe_pct": 2.0,
            "mae_pct": -7.0,
            "early_follow_through_state": "failed_launch",
            "sold_before_rebound": False,
        },
        {
            "entry_setup": "dragon_pullback",
            "dynamic_market_regime": "strong_broad",
            "dynamic_market_label": "全面强势",
            "market_warning_level": 0,
            "market_warning_label": "正常",
            "market_recovery_level": 3,
            "market_recovery_label": "回暖",
            "fund_flow_state": "inflow",
            "fund_flow_source": "sector_fund_flows",
            "exit_reason": "trend_trailing_stop",
            "return_pct": 15.0,
            "mfe_pct": 20.0,
            "mae_pct": -1.0,
            "early_follow_through_state": "confirmed_follow_through",
            "sold_before_rebound": False,
        },
    ]

    summary = queries.setup_market_exit_audit_summary(rows)
    market_validation = summary["market_context_validation"]

    assert summary["support_stop_context_audit"]["by_context"][0]["support_stop_context"] == "true_failed_launch_stop"
    assert summary["buy_sell_problem_matrix"]["by_problem"][0]["trade_problem_type"] in {"buy_point_bad", "healthy_trend_winner"}
    assert market_validation["not_used_for_signal_score"] is True
    assert market_validation["excluding_strong_market"]["trade_count"] == 1
    assert market_validation["fund_flow_coverage"]["insufficient_data_count"] == 1
    assert market_validation["by_market_regime"][0]["dynamic_market_regime"] == "false_bull"


def test_buy_sell_problem_matrix_classifies_trade_paths() -> None:
    from alphaagent.server.services.backtest import queries

    rows = [
        {
            "vt_symbol": "BUYBAD",
            "entry_setup": "stealth_low_suction",
            "dynamic_market_regime": "false_bull",
            "return_pct": -4.0,
            "return_20d": -5.0,
            "path_issue_type": "entry_follow_through",
        },
        {
            "vt_symbol": "GIVEBACK",
            "entry_setup": "dragon_pullback",
            "dynamic_market_regime": "choppy_rotation",
            "return_pct": -2.0,
            "return_20d": 8.0,
            "mfe_pct": 12.0,
            "giveback_pct": 14.0,
        },
        {
            "vt_symbol": "REBOUND",
            "entry_setup": "dragon_pullback",
            "dynamic_market_regime": "choppy_rotation",
            "exit_reason": "support_stop",
            "return_pct": -6.0,
            "sold_before_rebound": True,
        },
        {
            "vt_symbol": "WINNER",
            "entry_setup": "dragon_pullback",
            "dynamic_market_regime": "strong_broad",
            "return_pct": 18.0,
            "mfe_pct": 22.0,
        },
    ]

    matrix = queries.buy_sell_problem_matrix(rows)
    buckets = {row["trade_problem_type"]: row for row in matrix["by_problem"]}

    assert buckets["buy_point_bad"]["trade_count"] == 1
    assert buckets["sell_giveback"]["trade_count"] == 1
    assert buckets["sold_too_early"]["trade_count"] == 1
    assert buckets["healthy_trend_winner"]["trade_count"] == 1
    assert any(row["entry_setup"] == "dragon_pullback" and row["trade_problem_type"] == "sell_giveback" for row in matrix["by_setup_problem"])
    assert matrix["focused_symbols"][0]["trade_problem_type"] in {"sell_giveback", "sold_too_early", "buy_point_bad"}


def test_support_stop_context_audit_splits_stop_loss_path_types() -> None:
    from alphaagent.server.services.backtest import queries

    rows = [
        {
            "exit_reason": "support_stop",
            "return_pct": -7.5,
            "pnl": -7500.0,
            "mae_pct": -8.2,
            "mfe_pct": -1.5,
            "early_follow_through_state": "failed_launch",
            "sold_before_rebound": False,
            "has_price_discontinuity": True,
            "first_price_discontinuity_open_gap_pct": -29.0,
        },
        {
            "exit_reason": "support_stop",
            "return_pct": -6.8,
            "pnl": -6800.0,
            "mae_pct": -7.0,
            "mfe_pct": 2.0,
            "early_follow_through_state": "failed_launch",
            "sold_before_rebound": True,
        },
        {
            "exit_reason": "support_stop",
            "return_pct": -5.0,
            "pnl": -5000.0,
            "mae_pct": -5.8,
            "mfe_pct": 6.5,
            "early_follow_through_state": "confirmed_follow_through",
            "sold_before_rebound": False,
        },
        {
            "exit_reason": "support_stop",
            "return_pct": -4.0,
            "pnl": -4000.0,
            "mae_pct": -5.0,
            "mfe_pct": 12.0,
            "early_follow_through_state": "confirmed_follow_through",
            "sold_before_rebound": True,
        },
        {
            "exit_reason": "trend_trailing_stop",
            "return_pct": 20.0,
            "pnl": 20000.0,
            "mae_pct": -1.0,
            "mfe_pct": 28.0,
            "early_follow_through_state": "confirmed_follow_through",
            "sold_before_rebound": False,
        },
    ]

    audit = queries.setup_market_exit_audit_summary(rows)["support_stop_context_audit"]
    buckets = {row["support_stop_context"]: row for row in audit["by_context"]}

    assert audit["overall"]["trade_count"] == 4
    assert audit["data_quality"]["price_discontinuity_count"] == 1
    assert audit["overall_without_price_discontinuity"]["trade_count"] == 3
    assert buckets["true_failed_launch_stop"]["trade_count"] == 1
    assert buckets["stopped_then_rebounded"]["trade_count"] == 1
    assert buckets["had_follow_through_but_lost_support"]["trade_count"] == 1
    assert buckets["high_mfe_then_rebound_after_stop"]["trade_count"] == 1


def test_support_stop_matrix_exposes_clean_price_discontinuity_buckets() -> None:
    from alphaagent.server.services.backtest import queries

    rows = [
        {
            "exit_reason": "support_stop",
            "return_pct": -29.0,
            "pnl": -29000.0,
            "mae_pct": -31.0,
            "mfe_pct": 1.0,
            "early_follow_through_state": "failed_launch",
            "sold_before_rebound": False,
            "has_price_discontinuity": True,
            "first_price_discontinuity_open_gap_pct": -29.0,
            "setup_family": "low_suction_first_lift",
            "market_phase": "retreat",
        },
        {
            "exit_reason": "support_stop",
            "return_pct": -6.0,
            "pnl": -6000.0,
            "mae_pct": -8.0,
            "mfe_pct": 2.0,
            "early_follow_through_state": "failed_launch",
            "sold_before_rebound": False,
            "has_price_discontinuity": False,
            "setup_family": "dragon_pullback",
            "market_phase": "retreat",
        },
        {
            "exit_reason": "support_stop",
            "return_pct": -4.0,
            "pnl": -4000.0,
            "mae_pct": -5.0,
            "mfe_pct": 12.0,
            "giveback_pct": 16.0,
            "early_follow_through_state": "confirmed_follow_through",
            "sold_before_rebound": False,
            "has_price_discontinuity": False,
            "setup_family": "low_suction_first_lift",
            "market_phase": "warming",
        },
    ]

    summary = queries.support_stop_matrix_summary(rows)
    raw_context = {row["support_stop_context"]: row for row in summary["by_support_stop_context"]}
    clean_context = {
        row["support_stop_context"]: row
        for row in summary["by_support_stop_context_without_price_discontinuity"]
    }
    clean_setups = {
        row["setup_family"]: row
        for row in summary["by_setup_family_without_price_discontinuity"]
    }

    assert summary["overall"]["trade_count"] == 3
    assert summary["data_quality"]["price_discontinuity_count"] == 1
    assert summary["overall_without_price_discontinuity"]["trade_count"] == 2
    assert raw_context["true_failed_launch_stop"]["trade_count"] == 2
    assert clean_context["true_failed_launch_stop"]["trade_count"] == 1
    assert clean_context["clean_float_profit_giveback"]["trade_count"] == 1
    assert clean_setups["low_suction_first_lift"]["trade_count"] == 1
    assert summary["interpretation_without_price_discontinuity"]["needs_failed_launch_control"] is True


def test_entry_launch_quality_audit_groups_visible_entry_factors() -> None:
    from alphaagent.server.services.backtest import queries

    rows = [
        {
            "entry_setup": "dragon_pullback",
            "return_pct": -9.0,
            "early_follow_through_state": "failed_launch",
            "entry_score": 96.0,
            "low_suction_days": 0,
            "ma_convergence_pct": 18.0,
            "volume_ratio_5d_20d": 0.65,
            "pullback_days": 9,
            "close_location_in_range": 0.35,
            "tail_buy_repeat_days": 2,
            "sold_before_rebound": False,
        },
        {
            "entry_setup": "stealth_low_suction",
            "return_pct": 12.0,
            "early_follow_through_state": "confirmed_follow_through",
            "entry_score": 91.0,
            "low_suction_days": 5,
            "ma_convergence_pct": 4.5,
            "volume_ratio_5d_20d": 1.05,
            "pullback_days": 5,
            "close_location_in_range": 0.66,
            "tail_buy_repeat_days": 0,
            "low_suction_launch_confirmed": True,
            "recent_limit_up_20d": True,
            "sold_before_rebound": False,
        },
        {
            "entry_setup": "stealth_low_suction",
            "return_pct": -6.0,
            "early_follow_through_state": "failed_launch",
            "entry_score": 82.0,
            "low_suction_days": 6,
            "ma_convergence_pct": 4.0,
            "volume_ratio_5d_20d": 0.82,
            "pullback_days": 14,
            "close_location_in_range": 0.64,
            "tail_buy_repeat_days": 0,
            "low_suction_launch_confirmed": True,
            "sold_before_rebound": False,
        },
        {
            "entry_setup": "stealth_low_suction",
            "return_pct": -4.0,
            "early_follow_through_state": "no_follow_through",
            "entry_score": 79.0,
            "low_suction_days": 5,
            "ma_convergence_pct": 4.0,
            "volume_ratio_5d_20d": 0.9,
            "pullback_days": 8,
            "close_location_in_range": 0.62,
            "tail_buy_repeat_days": 0,
            "low_suction_launch_confirmed": False,
            "sold_before_rebound": False,
        },
    ]

    audit = queries.entry_launch_quality_audit(rows)

    assert audit["overall"]["trade_count"] == 4
    assert audit["overall"]["failed_launch_rate"] == 50.0
    assert audit["overall"]["confirmed_follow_through_rate"] == 25.0
    setup_buckets = {row["entry_setup"]: row for row in audit["by_entry_setup"]}
    assert setup_buckets["dragon_pullback"]["failed_launch_rate"] == 100.0
    assert round(setup_buckets["stealth_low_suction"]["confirmed_follow_through_rate"], 2) == 33.33
    ma_buckets = {row["ma_convergence_bucket"]: row for row in audit["by_ma_convergence"]}
    assert ma_buckets[">13%"]["failed_launch_count"] == 1
    assert ma_buckets["<=5%"]["confirmed_follow_through_count"] == 1
    repeat_buckets = {row["tail_repeat_bucket"]: row for row in audit["by_tail_repeat"]}
    assert repeat_buckets["1-2"]["failed_launch_count"] == 1
    low_suction_quality = {row["low_suction_launch_quality_bucket"]: row for row in audit["by_low_suction_launch_quality"]}
    assert low_suction_quality["balanced_first_lift"]["confirmed_follow_through_count"] == 1
    assert low_suction_quality["late_pullback_launch"]["failed_launch_count"] == 1
    assert low_suction_quality["unconfirmed_buildup"]["no_follow_through_count"] == 1
    assert audit["risk_contrast"]["failed_launch"]["trade_count"] == 2
    assert audit["risk_contrast"]["failed_launch"]["low_suction_launch_confirmed_rate"] == 50.0
    assert audit["risk_contrast"]["confirmed_follow_through"]["low_suction_launch_confirmed_rate"] == 100.0


def test_top_candidate_bucket_summary_groups_by_rank_and_market_return() -> None:
    from alphaagent.server.services.backtest import queries

    rows = [
        {"signal_date": date(2026, 1, 2), "rank": 1, "vt_symbol": "A", "return_pct": 10.0, "benchmark_return_pct": 2.0},
        {"signal_date": date(2026, 1, 2), "rank": 9, "vt_symbol": "B", "return_pct": -3.0, "benchmark_return_pct": 2.0},
        {"signal_date": date(2026, 1, 3), "rank": 15, "vt_symbol": "C", "return_pct": 5.0, "benchmark_return_pct": -1.0},
    ]

    result = queries.top_candidate_bucket_summary(rows, top_n=10)

    assert result["top_n"] == 10
    assert result["top_count"] == 2
    assert result["top_evaluated_count"] == 2
    assert result["top_win_rate"] == 0.5
    assert result["top_avg_return_pct"] == 3.5
    assert result["top_avg_benchmark_return_pct"] == 2.0
    assert result["top_excluding_strong_summary"]["candidate_count"] == 2
    assert result["top_excluding_strong_summary"]["evaluated_count"] == 2
    assert result["top_excluding_strong_summary"]["win_rate"] == 0.5
    assert result["top_strong_summary"]["candidate_count"] == 0


def test_top_candidate_bucket_summary_excludes_strong_market_for_overfit_audit() -> None:
    from alphaagent.server.services.backtest import queries

    rows = [
        {
            "signal_date": date(2026, 1, 2),
            "rank": 1,
            "vt_symbol": "A",
            "return_pct": 12.0,
            "benchmark_return_pct": 8.0,
            "excess_return_pct": 4.0,
            "market_regime": "strong",
            "benchmark_source": "equal_weight_stock_proxy",
        },
        {
            "signal_date": date(2026, 1, 3),
            "rank": 2,
            "vt_symbol": "B",
            "return_pct": -4.0,
            "benchmark_return_pct": -5.0,
            "excess_return_pct": 1.0,
            "market_regime": "weak",
            "benchmark_source": "equal_weight_stock_proxy",
        },
        {
            "signal_date": date(2026, 1, 4),
            "rank": 8,
            "vt_symbol": "C",
            "return_pct": 6.0,
            "benchmark_return_pct": 1.0,
            "excess_return_pct": 5.0,
            "market_regime": "choppy",
            "benchmark_source": "index_daily_bars",
        },
        {
            "signal_date": date(2026, 1, 5),
            "rank": 14,
            "vt_symbol": "D",
            "return_pct": 20.0,
            "benchmark_return_pct": 7.0,
            "excess_return_pct": 13.0,
            "market_regime": "strong",
            "benchmark_source": "index_daily_bars",
        },
    ]

    result = queries.top_candidate_bucket_summary(rows, top_n=10)

    assert result["top_count"] == 3
    assert round(result["top_strong_candidate_share"], 6) == round(1 / 3, 6)
    assert result["top_strong_summary"]["candidate_count"] == 1
    assert result["top_strong_summary"]["win_rate"] == 1.0
    assert result["top_excluding_strong_summary"]["candidate_count"] == 2
    assert result["top_excluding_strong_summary"]["evaluated_count"] == 2
    assert result["top_excluding_strong_summary"]["win_rate"] == 0.5
    assert result["top_excluding_strong_summary"]["avg_return_pct"] == 1.0
    assert result["top_excluding_strong_summary"]["avg_benchmark_return_pct"] == -2.0
    assert result["top_excluding_strong_summary"]["avg_excess_return_pct"] == 3.0
    assert result["benchmark_sources"] == [
        {"source": "equal_weight_stock_proxy", "count": 2},
        {"source": "index_daily_bars", "count": 1},
    ]


def test_top_candidate_bucket_summary_includes_fixed_horizon_observation_audit() -> None:
    from alphaagent.server.services.backtest import queries

    rows = [
        {
            "rank": 1,
            "vt_symbol": "A",
            "benchmark_return_pct": 8.0,
            "market_regime": "strong",
            "observation_return_pct": 12.0,
            "observation_excess_return_pct": 4.0,
        },
        {
            "rank": 2,
            "vt_symbol": "B",
            "benchmark_return_pct": -5.0,
            "market_regime": "weak",
            "observation_return_pct": -4.0,
            "observation_excess_return_pct": 1.0,
        },
        {
            "rank": 9,
            "vt_symbol": "C",
            "benchmark_return_pct": 1.0,
            "market_regime": "choppy",
            "observation_return_pct": 6.0,
            "observation_excess_return_pct": 5.0,
        },
        {
            "rank": 11,
            "vt_symbol": "D",
            "benchmark_return_pct": -2.0,
            "market_regime": "choppy",
            "observation_return_pct": 9.0,
            "observation_excess_return_pct": 11.0,
        },
    ]

    result = queries.top_candidate_bucket_summary(rows, top_n=10)
    observation = result["candidate_observation"]

    assert observation["candidate_count"] == 3
    assert observation["observed_count"] == 3
    assert observation["win_rate"] == 2 / 3
    assert observation["avg_return_pct"] == (12.0 - 4.0 + 6.0) / 3
    assert observation["excluding_strong_summary"]["candidate_count"] == 2
    assert observation["excluding_strong_summary"]["observed_count"] == 2
    assert observation["excluding_strong_summary"]["win_rate"] == 0.5
    assert observation["excluding_strong_summary"]["avg_return_pct"] == 1.0
    assert observation["excluding_strong_summary"]["avg_benchmark_return_pct"] == -2.0
    assert observation["excluding_strong_summary"]["avg_excess_return_pct"] == 3.0
    assert [row["regime"] for row in observation["market_buckets"]] == ["strong", "weak", "choppy"]


def test_market_context_classifies_narrow_theme_pullback_without_killing_mainline() -> None:
    from alphaagent.server.services.quant import market_context

    regime, notes = market_context._classify_dynamic_regime(
        market_score=61.0,
        trend_score=59.0,
        momentum_score=57.0,
        breadth_score=38.0,
        risk_score=48.0,
        theme_strength=78.0,
        growth_score=74.0,
        value_score=55.0,
    )
    theme_state = market_context._theme_state(
        theme_strength=64.0,
        breadth_score=42.0,
        risk_score=54.0,
        regime=regime,
    )

    assert regime == "narrow_theme_bull"
    assert theme_state == "active_pullback"
    assert notes == ["成长/小盘主线强于宽基，市场广度偏窄"]


def test_market_context_classifies_rotation_and_bear_market_separately() -> None:
    from alphaagent.server.services.quant import market_context

    rotation, _ = market_context._classify_dynamic_regime(
        market_score=54.0,
        trend_score=52.0,
        momentum_score=50.0,
        breadth_score=50.0,
        risk_score=45.0,
        theme_strength=57.0,
        growth_score=52.0,
        value_score=54.0,
    )
    crash, crash_notes = market_context._classify_dynamic_regime(
        market_score=35.0,
        trend_score=36.0,
        momentum_score=32.0,
        breadth_score=22.0,
        risk_score=82.0,
        theme_strength=40.0,
        growth_score=35.0,
        value_score=37.0,
    )

    assert rotation == "choppy_rotation"
    assert crash == "crash"
    assert crash_notes == ["指数破位且波动/回撤风险高"]


def test_market_context_marks_capital_outflow_warning_and_recovery() -> None:
    from alphaagent.server.services.quant import market_context

    panic_level, panic_label = market_context._market_warning(
        regime="weak_defensive",
        risk_score=72.0,
        trend_score=38.0,
        breadth_score=26.0,
        fund_flow_state="continuous_outflow",
        outflow_streak=4,
        drawdown_60d_pct=-9.0,
        index_return_20d=-7.0,
    )
    recovery_state, recovery_label = market_context._recovery_state(
        trend_score=56.0,
        momentum_score=58.0,
        breadth_score=57.0,
        risk_score=42.0,
        fund_flow_state="inflow",
        fund_flow_score=66.0,
        index_return_5d=1.2,
    )

    assert panic_level == 3
    assert panic_label == "强风险"
    assert recovery_state == "warming_confirmed"
    assert recovery_label in {"资金回流", "回暖确认"}


def test_market_context_summary_marks_risk_and_warming_states() -> None:
    from alphaagent.server.services.quant import market_context

    risk = market_context.market_context_summary(
        {
            "regime": "weak_defensive",
            "label": "弱势防守",
            "market_warning_level": 3,
            "market_warning_label": "强风险",
            "fund_flow_state": "continuous_outflow",
            "fund_flow_label": "连续流出",
            "fund_flow_streak_days": 4,
            "recovery_state": "none",
            "recovery_label": "未回暖",
        }
    )
    warming = market_context.market_context_summary(
        {
            "regime": "choppy_rotation",
            "label": "震荡轮动",
            "market_warning_level": 0,
            "market_warning_label": "正常",
            "fund_flow_state": "inflow",
            "fund_flow_label": "资金流入",
            "recovery_state": "warming_confirmed",
            "recovery_label": "资金回流",
        }
    )

    assert risk["state"] == "risk_off"
    assert risk["severity"] == "warning"
    assert risk["label"] == "大盘向下/资金防守"
    assert risk["fund_flow_marker"]["state"] == "continuous_outflow"
    assert risk["fund_flow_marker"]["level"] == 3
    assert "资金连续流出 4 天" in risk["notes"]
    assert warming["state"] == "warming"
    assert warming["severity"] == "positive"
    assert warming["label"] == "资金回流"
    assert warming["fund_flow_marker"]["state"] == "inflow"
    assert warming["fund_flow_marker"]["note"] == "资金回流"


def test_market_context_breadth_rolling_loader_uses_visible_closes() -> None:
    from alphaagent.server.services.quant import market_context

    start = date(2026, 1, 1)
    rows = []
    for index in range(20):
        trade_date = start + timedelta(days=index)
        rows.append(("000001.SZ", trade_date, 10.0 + index))
        rows.append(("000002.SZ", trade_date, 20.0 - index))
    rows.sort(key=lambda row: (row[0], row[1]))

    result = market_context._market_breadth_from_close_rows(rows)
    latest = result[start + timedelta(days=19)]

    assert start + timedelta(days=18) not in result
    assert latest["above20_pct"] == 50.0
    assert latest["above60_pct"] == 0.0
    assert latest["rising_pct"] == 50.0
    assert latest["breadth_score"] == 32.5


def test_market_phase_classifier_maps_four_trading_states() -> None:
    from alphaagent.server.services.quant import market_context

    uptrend = market_context.classify_trading_market_phase(
        {
            "regime": "narrow_theme_bull",
            "market_warning_level": 1,
            "recovery_state": "stabilizing",
            "theme_strength": 82.0,
            "market_score": 68.0,
        }
    )
    rotation = market_context.classify_trading_market_phase(
        {
            "regime": "false_bull",
            "market_warning_level": 2,
            "recovery_state": "none",
            "breadth_score": 36.0,
        }
    )
    retreat = market_context.classify_trading_market_phase(
        {
            "regime": "weak_defensive",
            "market_warning_level": 3,
            "recovery_state": "none",
            "fund_flow_state": "continuous_outflow",
        }
    )
    warming = market_context.classify_trading_market_phase(
        {
            "regime": "weak_rebound",
            "market_warning_level": 2,
            "recovery_state": "warming_confirmed",
            "fund_flow_state": "inflow",
        }
    )

    assert uptrend["phase"] == "uptrend"
    assert uptrend["label"] == "主升"
    assert "低吸首启" in uptrend["preferred_setups"]
    assert rotation["phase"] == "rotation"
    assert retreat["phase"] == "retreat"
    assert retreat["position_hint"] == "防守/空仓"
    assert warming["phase"] == "warming"
    assert warming["not_used_for_signal_score"] is True


def test_market_phase_classifier_uses_multi_index_tide_overlay() -> None:
    from alphaagent.server.services.quant import market_context

    retreat = market_context.classify_trading_market_phase(
        {
            "regime": "choppy_rotation",
            "market_score": 58.0,
            "market_warning_level": 2,
            "recovery_state": "none",
            "index_return_5d": -1.8,
            "index_return_20d": -2.8,
            "breadth_score": 44.0,
            "growth_score": 42.0,
            "value_score": 45.0,
            "small_cap_score": 47.0,
        }
    )
    warming = market_context.classify_trading_market_phase(
        {
            "regime": "choppy_rotation",
            "market_score": 56.0,
            "market_warning_level": 2,
            "recovery_state": "none",
            "index_return_5d": 3.2,
            "index_return_20d": -1.2,
            "breadth_score": 50.0,
            "growth_score": 59.0,
            "value_score": 55.0,
            "small_cap_score": 52.0,
        }
    )
    high_distribution = market_context.classify_trading_market_phase(
        {
            "regime": "false_bull",
            "market_score": 58.0,
            "market_warning_level": 2,
            "recovery_state": "none",
            "index_return_5d": 1.1,
            "index_return_20d": 6.2,
            "breadth_score": 36.5,
            "growth_score": 87.0,
            "value_score": 61.0,
            "small_cap_score": 64.0,
        }
    )

    assert retreat["phase"] == "retreat"
    assert retreat["tide_state"] == "retreat"
    assert "多指数同步走弱" in " ".join(retreat["notes"])
    assert warming["phase"] == "warming"
    assert warming["tide_state"] == "warming"
    assert "多指数同步修复" in " ".join(warming["notes"])
    assert high_distribution["phase"] == "retreat"
    assert high_distribution["tide_state"] == "retreat"
    assert "指数高位但广度退潮" in " ".join(high_distribution["notes"])


def test_symbol_review_bull_bear_line_uses_visible_market_context() -> None:
    from alphaagent.server.services.quant import symbol_review

    bull = symbol_review.bull_bear_line_from_row(
        {
            "trade_date": "2026-06-10",
            "evidence": {
                "market_context": {
                    "regime": "narrow_theme_bull",
                    "market_score": 78,
                    "market_warning_level": 1,
                    "theme_strength": 82,
                }
            },
        }
    )
    bear = symbol_review.bull_bear_line_from_row(
        {
            "trade_date": "2026-06-11",
            "evidence": {
                "market_context": {
                    "regime": "risk_off",
                    "market_score": 24,
                    "market_warning_level": 4,
                    "fund_flow_state": "continuous_outflow",
                }
            },
        }
    )

    assert bull["state"] == "bull"
    assert bull["label"] == "主升"
    assert bull["score"] == 78
    assert bear["state"] == "bear"
    assert bear["level"] == 0
    assert bear["not_used_for_signal_score"] is True


def test_symbol_review_clusters_buys_and_matches_sell_without_future_pick() -> None:
    from alphaagent.server.services.quant import symbol_review

    rows = [
        {
            "trade_date": "2026-04-01",
            "vt_symbol": "002384.SZSE",
            "total_score": 76,
            "executable_entry_signal": True,
            "action": "BUY",
            "signal_role": "candidate",
            "evidence": {"close": 10.0, "high": 10.2, "low": 9.8},
        },
        {
            "trade_date": "2026-04-02",
            "vt_symbol": "002384.SZSE",
            "total_score": 83,
            "executable_entry_signal": True,
            "action": "BUY",
            "key_entry_signal": True,
            "evidence": {"close": 10.5, "high": 10.8, "low": 10.1},
        },
        {
            "trade_date": "2026-04-03",
            "vt_symbol": "002384.SZSE",
            "total_score": 74,
            "executable_entry_signal": False,
            "entry_signal": True,
            "raw_entry_signal": True,
            "action": "WATCH",
            "failed_rules": ["total_score"],
            "evidence": {"close": 10.4, "high": 10.6, "low": 10.0},
        },
        {
            "trade_date": "2026-04-06",
            "vt_symbol": "002384.SZSE",
            "total_score": 20,
            "action": "WATCH",
            "evidence": {"close": 9.9, "high": 10.2, "low": 9.7},
        },
        {
            "trade_date": "2026-04-07",
            "vt_symbol": "002384.SZSE",
            "side": "SELL",
            "evidence": {"close": 11.55, "high": 11.8, "low": 11.2},
        },
    ]

    result = symbol_review.build_unified_signal_review(rows)
    markers = result["markers"]

    assert [marker["kind"] for marker in markers] == ["buy", "rejected_buy", "sell"]
    assert markers[0]["trade_date"] == "2026-04-02"
    assert markers[0]["cluster_size"] == 2
    assert markers[2]["return_pct"] == 10.000000000000009
    assert result["segments"][0]["entry_date"] == "2026-04-02"
    assert result["segments"][0]["exit_date"] == "2026-04-07"
    assert round(result["summary"]["win_rate_pct"], 2) == 100.0
    assert result["summary"]["trade_count"] == 1
    assert result["not_used_for_signal_score"] is True


def test_symbol_review_marks_support_divergence_research_without_trade_segment() -> None:
    from alphaagent.server.services.quant import symbol_review

    rows = [
        {
            "trade_date": "2026-06-12",
            "vt_symbol": "003004.SZSE",
            "total_score": 90.27,
            "executable_entry_signal": False,
            "research_entry_signal": True,
            "action": "WATCH",
            "signal_label": "支撑分歧低吸买点",
            "failed_rules": ["reclaim_confirmation"],
            "evidence": {
                "close": 32.1,
                "support_divergence_entry_profile": "high_level_support_divergence",
                "support_divergence_entry_observation_only": True,
            },
        },
        {
            "trade_date": "2026-06-17",
            "vt_symbol": "003004.SZSE",
            "side": "SELL",
            "evidence": {"close": 34.2},
        },
    ]

    result = symbol_review.build_unified_signal_review(rows)

    assert [marker["kind"] for marker in result["markers"]] == ["research_buy", "sell"]
    assert result["markers"][0]["label"] == "支撑分歧低吸买点"
    assert result["segments"] == []
    assert result["summary"]["trade_count"] == 0


def test_symbol_review_marks_strong_trend_ma_pullback_research_without_trade_segment() -> None:
    from alphaagent.server.services.quant import symbol_review

    rows = [
        {
            "trade_date": "2026-05-25",
            "vt_symbol": "003004.SZSE",
            "total_score": 78.49,
            "executable_entry_signal": False,
            "research_entry_signal": True,
            "action": "WATCH",
            "signal_label": "强趋势均线回踩研究买点",
            "failed_rules": ["pullback_too_short"],
            "evidence": {
                "close": 49.76,
                "strong_trend_ma_pullback_entry_profile": "strong_trend_intraday_ma_pullback",
                "strong_trend_ma_pullback_entry_observation_only": True,
            },
        },
        {
            "trade_date": "2026-05-28",
            "vt_symbol": "003004.SZSE",
            "side": "SELL",
            "evidence": {"close": 55.0},
        },
    ]

    result = symbol_review.build_unified_signal_review(rows)

    assert [marker["kind"] for marker in result["markers"]] == ["research_buy", "sell"]
    assert result["markers"][0]["label"] == "强趋势均线回踩研究买点"
    assert result["segments"] == []
    assert result["summary"]["trade_count"] == 0


def test_classify_dynamic_market_context_separates_mainline_pullback_and_missing_flow() -> None:
    from alphaagent.server.services.quant import market_context

    mainline_pullback = market_context.classify_dynamic_market_context(
        index_trend={"return_20d": -1.5, "return_5d": -1.0, "ma20_slope_pct": 0.3},
        breadth={"breadth_score": 42.0, "up_ratio": 0.45, "limit_down_count": 4},
        sector_flow={"dominant_theme": "technology", "theme_strength": 88.0, "fund_flow_state": "unknown"},
        stock_theme_alignment="aligned",
    )
    risk_off = market_context.classify_dynamic_market_context(
        index_trend={"return_20d": -7.5, "return_5d": -3.0, "drawdown_20d_pct": -9.2},
        breadth={"breadth_score": 24.0, "limit_down_count": 36},
        sector_flow={"dominant_theme": None, "theme_strength": 20.0, "main_net_inflow_ratio": -9.0, "fund_flow_source": "sector_fund_flows"},
        stock_theme_alignment="unknown",
    )

    assert mainline_pullback["dynamic_market_regime"] == "mainline_pullback"
    assert mainline_pullback["fund_flow_state"] == "insufficient_data"
    assert mainline_pullback["not_used_for_signal_score"] is True
    assert "主线仍强但处于回踩" in mainline_pullback["explain"]
    assert risk_off["dynamic_market_regime"] == "risk_off"
    assert risk_off["market_warning_level"] == 4
    assert risk_off["fund_flow_state"] == "panic_outflow"


def test_market_context_fund_flow_marker_marks_worsening_and_recovery_streaks() -> None:
    from alphaagent.server.services.quant import market_context

    rows = [
        {"trade_date": date(2026, 6, 10), "main_net_inflow_ratio": -3.0},
        {"trade_date": date(2026, 6, 11), "main_net_inflow_ratio": -4.0},
        {"trade_date": date(2026, 6, 12), "main_net_inflow_ratio": -5.0},
        {"trade_date": date(2026, 6, 15), "main_net_inflow_ratio": -6.0},
        {"trade_date": date(2026, 6, 16), "main_net_inflow_ratio": 6.0},
    ]

    payloads = market_context._fund_flow_payloads_from_rows(rows, source="sector_fund_flows")
    worsening = payloads[date(2026, 6, 12)]
    recovery = payloads[date(2026, 6, 16)]
    risk_summary = market_context.market_context_summary(
        {
            "regime": "choppy_rotation",
            "label": "震荡轮动",
            "market_warning_level": 0,
            "market_warning_label": "正常",
            "fund_flow_state": "continuous_outflow",
            "fund_flow_label": "连续流出",
            "fund_flow_score": worsening["fund_flow_score"],
            "fund_flow_streak_days": worsening["outflow_streak_days"],
            "fund_flow_worsening_days": worsening["outflow_worsening_days"],
            "fund_flow_new_low": worsening["outflow_new_low"],
        }
    )
    recovery_summary = market_context.market_context_summary(
        {
            "regime": "choppy_rotation",
            "label": "震荡轮动",
            "market_warning_level": 0,
            "market_warning_label": "正常",
            "fund_flow_state": "inflow",
            "fund_flow_label": "资金流入",
            "fund_flow_score": recovery["fund_flow_score"],
            "fund_flow_recovery_from_streak_days": recovery["recovery_from_outflow_streak_days"],
            "recovery_state": "warming_confirmed",
            "recovery_label": "资金回流",
        }
    )

    assert worsening["outflow_streak_days"] == 3
    assert worsening["outflow_new_low"] is True
    assert risk_summary["fund_flow_marker"]["level"] == 4
    assert risk_summary["fund_flow_marker"]["trend"] == "worsening"
    assert risk_summary["fund_flow_marker"]["note"] == "连续流出 3 天且流出扩大"
    assert risk_summary["severity"] == "danger"
    assert recovery["recovery_from_outflow_streak_days"] == 4
    assert recovery_summary["fund_flow_marker"]["trend"] == "recovery"
    assert recovery_summary["fund_flow_marker"]["note"] == "连续流出 4 天后资金回流"


def test_market_context_uses_partial_stock_fund_flow_as_marked_fallback(monkeypatch) -> None:
    from alphaagent.server.services.quant import market_context

    monkeypatch.setattr(market_context, "_load_sector_fund_flows_by_date", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        market_context,
        "_load_stock_fund_flows_by_date",
        lambda *args, **kwargs: {
            date(2026, 6, 18): {
                "fund_flow_score": 72.0,
                "fund_flow_source": "stock_fund_flows_partial",
                "main_net_inflow": 1_500_000_000,
                "main_net_inflow_ratio": 4.2,
                "outflow_streak_days": 0,
            }
        },
    )

    result = market_context._load_fund_flows_by_date(None, None, date(2026, 6, 1), date(2026, 6, 18))

    assert result[date(2026, 6, 18)]["fund_flow_score"] == 72.0
    assert result[date(2026, 6, 18)]["fund_flow_source"] == "stock_fund_flows_partial"

    context = market_context._build_context(
        date(2026, 6, 18),
        {},
        {date(2026, 6, 18): {"breadth_score": 52.0, "above20_pct": 55.0, "above60_pct": 48.0, "rising_pct": 50.0}},
        [],
        result,
    )

    assert context.fund_flow_source == "stock_fund_flows_partial"
    assert context.fund_flow_label == "局部资金流入"
    assert "局部榜单兜底" in " ".join(context.notes)


def test_top_candidate_bucket_summary_includes_dynamic_market_and_theme_alignment() -> None:
    from alphaagent.server.services.backtest import queries

    rows = [
        {
            "rank": 1,
            "return_pct": 9.0,
            "excess_return_pct": 5.0,
            "observation_return_pct": 6.0,
            "observation_excess_return_pct": 3.0,
            "dynamic_market_regime": "narrow_theme_bull",
            "market_score": 66.0,
            "market_breadth_score": 41.0,
            "market_risk_score": 45.0,
            "dynamic_market_source": "stock_daily_bars",
            "theme_strength": 82.0,
            "stock_theme_alignment": "leader_theme",
        },
        {
            "rank": 2,
            "return_pct": -4.0,
            "excess_return_pct": -2.0,
            "observation_return_pct": 2.0,
            "observation_excess_return_pct": 1.0,
            "dynamic_market_regime": "weak_defensive",
            "market_score": 38.0,
            "market_breadth_score": 28.0,
            "market_risk_score": 72.0,
            "dynamic_market_source": "benchmark_return_20d_proxy",
            "theme_strength": 48.0,
            "stock_theme_alignment": "isolated_candidate",
        },
        {
            "rank": 11,
            "return_pct": 11.0,
            "excess_return_pct": 8.0,
            "observation_return_pct": 7.0,
            "observation_excess_return_pct": 5.0,
            "dynamic_market_regime": "strong_broad",
            "market_score": 76.0,
            "market_breadth_score": 65.0,
            "market_risk_score": 35.0,
            "dynamic_market_source": "stock_daily_bars",
            "theme_strength": 70.0,
            "stock_theme_alignment": "theme_related",
        },
    ]

    result = queries.top_candidate_bucket_summary(rows, top_n=10)

    assert [row["regime"] for row in result["dynamic_market_buckets"]] == ["narrow_theme_bull", "weak_defensive"]
    assert result["dynamic_market_buckets"][0]["win_rate"] == 1.0
    assert result["dynamic_market_buckets"][1]["win_rate"] == 0.0
    assert [row["alignment"] for row in result["theme_alignment_buckets"]] == ["leader_theme", "isolated_candidate"]
    assert result["theme_alignment_buckets"][0]["avg_theme_strength"] == 82.0
    assert result["dynamic_market_sources"] == [
        {"source": "benchmark_return_20d_proxy", "count": 1},
        {"source": "stock_daily_bars", "count": 1},
    ]
    assert [row["regime"] for row in result["candidate_observation"]["dynamic_market_buckets"]] == [
        "narrow_theme_bull",
        "weak_defensive",
    ]


def test_market_phase_strategy_audit_summary_keeps_setup_per_phase() -> None:
    from alphaagent.server.services.backtest import queries

    trades = [
        {
            "entry_setup": "dragon_pullback",
            "return_pct": 12.0,
            "pnl": 1200.0,
            "dynamic_market_regime": "narrow_theme_bull",
            "market_warning_level": 1,
            "recovery_state": "stabilizing",
            "theme_strength": 82.0,
        },
        {
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 4,
            "low_suction_launch_confirmed": True,
            "return_pct": 6.0,
            "pnl": 600.0,
            "dynamic_market_regime": "narrow_theme_bull",
            "market_warning_level": 1,
            "recovery_state": "stabilizing",
            "theme_strength": 82.0,
        },
        {
            "entry_setup": "dragon_pullback",
            "return_pct": -5.0,
            "pnl": -500.0,
            "dynamic_market_regime": "weak_defensive",
            "market_warning_level": 3,
            "recovery_state": "none",
            "fund_flow_state": "continuous_outflow",
        },
    ]
    candidates = [
        {
            "entry_family": "dragon_pullback",
            "observation_return_pct": 8.0,
            "dynamic_market_regime": "narrow_theme_bull",
            "market_warning_level": 1,
            "recovery_state": "stabilizing",
        },
        {
            "entry_family": "low_position_reclaim",
            "low_suction_days": 5,
            "low_suction_launch_confirmed": True,
            "observation_return_pct": -3.0,
            "dynamic_market_regime": "weak_defensive",
            "market_warning_level": 3,
            "recovery_state": "none",
        },
    ]

    summary = queries.market_phase_strategy_audit_summary(trades, candidates, candidate_top_n=20)

    assert summary["overall"]["trade_count"] == 3
    assert summary["overall"]["win_rate"] == 2 / 3 * 100
    phase_rows = {row["market_phase"]: row for row in summary["by_phase"]}
    assert phase_rows["uptrend"]["trade_count"] == 2
    assert phase_rows["uptrend"]["win_rate"] == 100.0
    assert phase_rows["retreat"]["trade_count"] == 1
    setup_rows = {(row["market_phase"], row["setup_family"]): row for row in summary["by_phase_setup"]}
    assert setup_rows[("uptrend", "dragon_pullback")]["trade_count"] == 1
    assert setup_rows[("uptrend", "low_suction_first_lift")]["trade_count"] == 1
    candidate_rows = {row["market_phase"]: row for row in summary["candidate_by_phase"]}
    assert candidate_rows["uptrend"]["win_rate"] == 100.0
    assert candidate_rows["retreat"]["win_rate"] == 0.0
    assert summary["not_used_for_signal_score"] is True


def test_market_phase_strategy_audit_reads_nested_signal_evidence() -> None:
    from alphaagent.server.services.backtest import queries

    trades = [
        {
            "return_pct": 5.0,
            "pnl": 500.0,
            "raw": {
                "evidence": {
                    "entry_setup": "dragon_pullback",
                    "dynamic_market_regime": "strong_broad",
                    "market_warning_level": 0,
                    "recovery_state": "warming_confirmed",
                }
            },
        }
    ]
    candidates = [
        {
            "rank": 1,
            "observation_return_pct": 8.0,
            "raw": {
                "evidence": {
                    "entry_family": "stealth_low_suction",
                    "low_suction_days": 5,
                    "low_suction_launch_confirmed": True,
                    "dynamic_market_regime": "strong_broad",
                    "market_warning_level": 0,
                    "recovery_state": "warming_confirmed",
                }
            },
        }
    ]

    summary = queries.market_phase_strategy_audit_summary(trades, candidates, candidate_top_n=20)

    assert summary["by_phase"][0]["market_phase"] == "uptrend"
    assert summary["by_setup"][0]["setup_family"] == "dragon_pullback"
    assert summary["candidate_by_phase"][0]["market_phase"] == "uptrend"
    assert summary["candidate_by_phase_setup"][0]["setup_family"] == "low_suction_first_lift"


def test_phase_strategy_family_matrix_summary_returns_rank_matrices() -> None:
    from alphaagent.server.services.backtest import queries

    trades = [
        {
            "entry_setup": "dragon_pullback",
            "return_pct": -4.0,
            "pnl": -400.0,
            "dynamic_market_regime": "strong_broad",
            "market_warning_level": 0,
            "recovery_state": "warming_confirmed",
        },
        {
            "entry_setup": "stealth_low_suction",
            "low_suction_days": 5,
            "low_suction_launch_confirmed": False,
            "return_pct": -3.0,
            "pnl": -300.0,
            "dynamic_market_regime": "strong_broad",
            "market_warning_level": 0,
            "recovery_state": "warming_confirmed",
        },
        {
            "entry_setup": "dragon_pullback",
            "low_suction_days": 4,
            "return_pct": -6.0,
            "pnl": -600.0,
            "dynamic_market_regime": "choppy_rotation",
            "market_warning_level": 1,
            "recovery_state": "none",
        },
    ]
    candidates = [
        {
            "rank": 1,
            "entry_family": "dragon_pullback",
            "observation_return_pct": 12.0,
            "dynamic_market_regime": "strong_broad",
            "market_warning_level": 0,
            "recovery_state": "warming_confirmed",
        },
        {
            "rank": 15,
            "entry_family": "low_position_reclaim",
            "low_suction_days": 6,
            "low_suction_launch_confirmed": True,
            "observation_return_pct": 4.0,
            "dynamic_market_regime": "choppy_rotation",
            "market_warning_level": 1,
            "recovery_state": "none",
        },
        {
            "rank": 75,
            "entry_family": "dragon_pullback",
            "low_suction_days": 4,
            "observation_return_pct": -2.0,
            "dynamic_market_regime": "weak_defensive",
            "market_warning_level": 3,
            "recovery_state": "none",
        },
    ]

    summary = queries.phase_strategy_family_matrix_summary(
        trades,
        candidates,
        candidate_rank_limits=[20, 10, 100],
    )

    assert summary["not_used_for_signal_score"] is True
    assert summary["audit_only"] is True
    assert summary["candidate_rank_limits"] == [10, 20, 100]
    assert summary["coverage"] == {"trade_count": 3, "candidate_count": 3, "candidate_max_rank_loaded": 100}
    matrices = {row["rank_limit"]: row for row in summary["candidate_rank_matrices"]}
    assert matrices[10]["candidate_count"] == 1
    assert matrices[20]["candidate_count"] == 2
    assert matrices[100]["candidate_count"] == 3
    real_matrix = {(row["market_phase"], row["setup_family"]): row for row in summary["real_trade_matrix"]}
    assert real_matrix[("uptrend", "low_suction_buildup")]["trade_count"] == 1
    assert real_matrix[("rotation", "dragon_low_suction_overlap")]["trade_count"] == 1
    assert summary["interpretation"]["low_suction_buildup_observation_only"] is True
    assert summary["interpretation"]["overlap_requires_conflict_resolution"] is True


def test_market_context_falls_back_to_benchmark_proxy_without_index_data() -> None:
    from alphaagent.server.services.quant import market_context

    rows = [
        {
            "vt_symbol": "A",
            "benchmark_return_pct": 7.0,
            "reason": {"smart_money_proxy_score": 76.0},
        },
        {
            "vt_symbol": "B",
            "benchmark_return_pct": -4.0,
            "reason": {"smart_money_proxy_score": 61.0},
        },
        {
            "vt_symbol": "C",
            "benchmark_return_pct": -9.0,
            "reason": {"smart_money_proxy_score": 45.0},
        },
    ]

    result = market_context._annotate_rows_with_benchmark_proxy(rows)

    assert [row["dynamic_market_regime"] for row in result] == ["strong_broad", "weak_defensive", "crash"]
    assert [row["stock_theme_alignment"] for row in result] == [
        "leader_theme",
        "theme_related",
        "isolated_candidate",
    ]


def test_market_returns_20d_batch_uses_index_when_available(monkeypatch) -> None:
    from alphaagent.server.services.backtest import queries

    calls = []

    def fake_index_returns(session, schema, dates):
        calls.append(("index", tuple(dates)))
        return {date(2026, 1, 30): 4.5}

    def fake_proxy_returns(session, schema, dates):
        calls.append(("proxy", tuple(dates)))
        return {date(2026, 2, 2): -2.0}

    monkeypatch.setattr(queries, "_index_returns_20d_from_session", fake_index_returns)
    monkeypatch.setattr(queries, "_equal_weight_market_returns_20d_from_session", fake_proxy_returns)

    result = queries._market_returns_20d_for_audit(None, None, [date(2026, 1, 30), date(2026, 2, 2)])

    assert result[date(2026, 1, 30)] == {"return_20d": 4.5, "source": "000001.SSE"}
    assert result[date(2026, 2, 2)] == {"return_20d": -2.0, "source": "equal_weight_stock_proxy"}
    assert calls == [
        ("index", (date(2026, 1, 30), date(2026, 2, 2))),
        ("proxy", (date(2026, 2, 2),)),
    ]


def test_backtest_entry_raw_payload_backfills_early_dragon_pullback_risk() -> None:
    from alphaagent.server.services.backtest import queries

    old_raw = {
        "entry_setup": "dragon_pullback",
        "low_suction_days": 0,
        "ma_convergence_pct": 22.91,
        "latest_change_pct": 7.58,
        "close_location_in_range": 0.62,
    }
    raw = queries._entry_raw_payload({"raw": old_raw})
    api_row = queries._entry_enriched_api_row({"raw": old_raw}, dict)

    assert raw["early_dragon_pullback_risk"] is True
    assert api_row["raw"]["early_dragon_pullback_risk"] is True


def _candidate_quality_row(
    vt_symbol: str,
    trade_date: date,
    *,
    rank: int = 1,
    score: float = 88.0,
    setup: str = "stealth_low_suction",
    action: str = "BUY",
    launch_confirmed: bool = False,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "vt_symbol": vt_symbol,
        "rank": rank,
        "action": action,
        "total_score": score,
        "reason": {
            "action": action,
            "entry_setup": setup,
            "entry_family": setup,
            "executable_entry_signal": action == "BUY",
            "low_suction_launch_confirmed": launch_confirmed,
            "low_suction_days": 4 if setup == "stealth_low_suction" else 0,
        },
    }


def test_candidate_trade_quality_clusters_consecutive_buy_rows() -> None:
    from alphaagent.server.services.backtest.factor_audit import build_candidate_clusters

    rows = [
        _candidate_quality_row("600000.SSE", date(2026, 1, 2), rank=1),
        _candidate_quality_row("600000.SSE", date(2026, 1, 3), rank=2),
        _candidate_quality_row("600001.SSE", date(2026, 1, 3), rank=3),
    ]

    clusters = build_candidate_clusters(rows)

    assert len(clusters) == 2
    first = next(cluster for cluster in clusters if cluster.vt_symbol == "600000.SSE")
    assert first.cluster_start_date == date(2026, 1, 2)
    assert first.cluster_end_date == date(2026, 1, 3)
    assert len(first.rows) == 2


def test_candidate_trade_quality_daily_clusters_keep_each_candidate_day() -> None:
    from alphaagent.server.services.backtest.factor_audit import build_daily_candidate_clusters

    rows = [
        _candidate_quality_row("600000.SSE", date(2026, 1, 2), rank=1),
        _candidate_quality_row("600000.SSE", date(2026, 1, 3), rank=2),
        _candidate_quality_row("600001.SSE", date(2026, 1, 3), rank=3),
    ]

    clusters = build_daily_candidate_clusters(rows)

    assert len(clusters) == 3
    assert [(cluster.vt_symbol, cluster.cluster_start_date) for cluster in clusters] == [
        ("600000.SSE", date(2026, 1, 2)),
        ("600000.SSE", date(2026, 1, 3)),
        ("600001.SSE", date(2026, 1, 3)),
    ]
    assert all(len(cluster.rows) == 1 for cluster in clusters)


def test_candidate_trade_quality_splits_cluster_after_gap() -> None:
    from alphaagent.server.services.backtest.factor_audit import build_candidate_clusters

    rows = [
        _candidate_quality_row("600000.SSE", date(2026, 1, 2), rank=1),
        _candidate_quality_row("600001.SSE", date(2026, 1, 3), rank=1),
        _candidate_quality_row("600002.SSE", date(2026, 1, 4), rank=1),
        _candidate_quality_row("600000.SSE", date(2026, 1, 5), rank=1),
    ]

    clusters = [cluster for cluster in build_candidate_clusters(rows) if cluster.vt_symbol == "600000.SSE"]

    assert len(clusters) == 2
    assert [cluster.cluster_start_date for cluster in clusters] == [date(2026, 1, 2), date(2026, 1, 5)]


def test_candidate_trade_quality_uses_first_visible_buy_entry_not_later_confirmation() -> None:
    from alphaagent.server.services.backtest.factor_audit import build_candidate_clusters

    rows = [
        _candidate_quality_row("600000.SSE", date(2026, 1, 2), rank=1, score=95, launch_confirmed=False),
        _candidate_quality_row("600000.SSE", date(2026, 1, 3), rank=2, score=80, launch_confirmed=True),
        _candidate_quality_row("600001.SSE", date(2026, 1, 2), rank=1, score=82, launch_confirmed=False),
        _candidate_quality_row("600001.SSE", date(2026, 1, 3), rank=2, score=90, launch_confirmed=False),
        _candidate_quality_row("600001.SSE", date(2026, 1, 4), rank=3, score=90, launch_confirmed=False),
    ]

    clusters = build_candidate_clusters(rows)
    confirmed = next(cluster for cluster in clusters if cluster.vt_symbol == "600000.SSE")
    high_score = next(cluster for cluster in clusters if cluster.vt_symbol == "600001.SSE")

    assert confirmed.entry_row["trade_date"] == date(2026, 1, 2)
    assert high_score.entry_row["trade_date"] == date(2026, 1, 2)


def test_candidate_trade_quality_marks_missing_d1_bar() -> None:
    from alphaagent.server.services.backtest.factor_audit import (
        build_candidate_clusters,
        simulate_independent_candidate_trade,
    )
    from alphaagent.server.services.backtest.schemas import BacktestParams

    cluster = build_candidate_clusters([
        _candidate_quality_row("600000.SSE", date(2026, 1, 2), rank=1),
    ])[0]

    result = simulate_independent_candidate_trade(
        cluster,
        [Bar(date(2026, 1, 2), 10, 10.5, 9.8, 10.2)],
        params=BacktestParams(),
        sell_reason_fn=lambda *args, **kwargs: None,
    )

    assert result.status == "no_execute_bar"
    assert result.return_pct is None


def test_candidate_trade_quality_independent_trade_ignores_transaction_constraints() -> None:
    from alphaagent.server.services.backtest.factor_audit import (
        build_candidate_clusters,
        candidate_trade_quality_report_from_results,
        simulate_independent_candidate_trade,
    )
    from alphaagent.server.services.backtest.schemas import BacktestParams

    cluster = build_candidate_clusters([
        _candidate_quality_row("600000.SSE", date(2026, 1, 2), rank=1, score=96, launch_confirmed=True),
    ])[0]
    bars = [
        Bar(date(2026, 1, 2), 10, 10.2, 9.8, 10),
        Bar(date(2026, 1, 3), 10, 10.6, 9.9, 10.5),
        Bar(date(2026, 1, 4), 10.5, 11, 10.4, 10.9),
        Bar(date(2026, 1, 5), 10.8, 11, 10.7, 10.9),
    ]

    def sell_next_day(position, bar, current_day, params, **kwargs):
        del position, params, kwargs
        return "test_exit" if current_day == date(2026, 1, 4) else None

    result = simulate_independent_candidate_trade(
        cluster,
        bars,
        params=BacktestParams(max_positions=0, initial_cash=0),
        sell_reason_fn=sell_next_day,
    )
    report = candidate_trade_quality_report_from_results([result])

    assert result.status == "closed"
    assert result.entry_execute_date == date(2026, 1, 3)
    assert result.exit_execute_date == date(2026, 1, 5)
    assert result.return_pct == 8.0
    assert report["summary"]["sample_count"] == 1
    assert report["summary"]["win_rate"] == 100.0
    assert report["coverage"]["sample_count"] == 1
    assert report["coverage"]["daily_candidate_trade_count"] == 1
    assert report["coverage"]["rank_limited_sample_count"] == 1
    assert report["items"][0]["uses_future_for_label_only"] is True
    assert report["items"][0]["not_used_for_signal_score"] is True


def test_candidate_trade_quality_report_can_measure_reentry_overlay_when_explicitly_provided() -> None:
    from alphaagent.server.services.backtest.factor_audit import (
        build_daily_candidate_clusters,
        candidate_trade_quality_report_from_results,
        simulate_independent_candidate_trade,
    )
    from alphaagent.server.services.backtest.schemas import BacktestParams

    row = _candidate_quality_row("600000.SSE", date(2026, 1, 2), rank=1001, setup="support_stop_reentry")
    row["candidate_source"] = "support_stop_reentry"
    row["candidate_execution"] = {
        "execution_candidate_rank": 1,
        "execution_candidate_selected": True,
        "raw_signal_rank": 1001,
    }
    cluster = build_daily_candidate_clusters([row])[0]
    bars = [
        Bar(date(2026, 1, 2), 10.0, 10.2, 9.8, 10.0),
        Bar(date(2026, 1, 3), 10.0, 10.6, 9.9, 10.5),
        Bar(date(2026, 1, 4), 10.5, 11.0, 10.4, 10.9),
        Bar(date(2026, 1, 5), 10.8, 11.0, 10.7, 10.9),
    ]

    def sell_next_day(position, bar, current_day, params, **kwargs):
        del position, params, kwargs
        return "test_exit" if current_day == date(2026, 1, 4) else None

    result = simulate_independent_candidate_trade(
        cluster,
        bars,
        params=BacktestParams(),
        sell_reason_fn=sell_next_day,
    )
    report = candidate_trade_quality_report_from_results([result], rank_limit=20, sample_limit=5)

    assert report["summary"]["sample_count"] == 1
    assert report["coverage"]["rank_limited_sample_count"] == 1
    assert report["items"][0]["rank"] == 1001
    assert report["items"][0]["effective_rank"] == 1
    assert report["items"][0]["rank_bucket"] == "top_10"


def test_candidate_trade_quality_scope_excludes_support_stop_reentry_but_keeps_real_execution_rank() -> None:
    from alphaagent.server.services.backtest import engine

    run_row = {"params": {"candidate_limit": 20}}
    ordinary = {
        "rank": 24,
        "candidate_execution": {"execution_candidate_rank": 18, "execution_candidate_selected": True},
    }
    reentry = {
        "rank": 1001,
        "candidate_source": "support_stop_reentry",
        "reason": {"entry_setup": "support_stop_reentry", "support_stop_reentry": True},
        "candidate_execution": {
            "execution_lane": "support_stop_reentry",
            "execution_candidate_rank": 1,
            "execution_candidate_selected": True,
        },
    }

    assert engine._candidate_quality_cluster_in_scope(ordinary, 20, run_row) is True
    assert engine._candidate_quality_cluster_in_scope(reentry, 20, run_row) is False


def test_candidate_trade_quality_scoped_items_rebuilds_current_execution_pool_for_legacy_snapshots() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.quant.factors import DRAGON_PULLBACK_STRATEGY_ID

    rows = [
        _candidate_quality_row("600001.SSE", date(2026, 1, 2), rank=1, score=90, setup="dragon_pullback"),
        _candidate_quality_row("600002.SSE", date(2026, 1, 2), rank=2, score=89, setup="dragon_pullback"),
        _candidate_quality_row("600003.SSE", date(2026, 1, 2), rank=3, score=95, setup="dragon_pullback"),
        _candidate_quality_row("600005.SSE", date(2026, 1, 2), rank=101, score=99, setup="dragon_pullback"),
        {
            **_candidate_quality_row("600004.SSE", date(2026, 1, 2), rank=1001, score=88, setup="support_stop_reentry"),
            "candidate_source": "support_stop_reentry",
        },
    ]

    scoped = engine._candidate_quality_scoped_items(
        rows,
        2,
        {"strategy_id": DRAGON_PULLBACK_STRATEGY_ID, "params": {"candidate_limit": 20}},
    )

    assert [row["vt_symbol"] for row in scoped] == ["600003.SSE", "600001.SSE"]
    assert [row["candidate_execution"]["execution_candidate_rank"] for row in scoped] == [1, 2]
    assert all(row["vt_symbol"] != "600005.SSE" for row in scoped)
    assert all(row["vt_symbol"] != "600004.SSE" for row in scoped)


def test_candidate_trade_quality_support_stop_reentry_overlay_is_read_only_daily_cap() -> None:
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.backtest.factor_audit import (
        CandidateCluster,
        IndependentTradeResult,
        candidate_trade_quality_report_from_results,
    )
    from alphaagent.server.services.backtest.schemas import BacktestParams

    symbol = "600000.SSE"
    start = date(2026, 1, 1)
    bars = []
    for index in range(30):
        day = start + timedelta(days=index)
        close = 10.0
        if day == date(2026, 1, 25):
            close = 9.95
        elif day == date(2026, 1, 26):
            close = 10.03
        elif day >= date(2026, 1, 27):
            close = 10.12
        bars.append(
            Bar(
                day,
                close,
                close * 1.01,
                close * 0.98,
                close,
                volume=1_000_000,
                turnover=100_000_000,
                change_pct=0.8 if day == date(2026, 1, 26) else 0.0,
            )
        )
    source_cluster = CandidateCluster(
        vt_symbol=symbol,
        rows=(
            _candidate_quality_row(symbol, date(2026, 1, 20), rank=1, setup="dragon_pullback"),
        ),
        cluster_start_date=date(2026, 1, 20),
        cluster_end_date=date(2026, 1, 20),
        entry_row=_candidate_quality_row(symbol, date(2026, 1, 20), rank=1, setup="dragon_pullback"),
    )
    source_result = IndependentTradeResult(
        status="closed",
        cluster=source_cluster,
        entry_signal_date=date(2026, 1, 20),
        entry_execute_date=date(2026, 1, 21),
        entry_price=10.0,
        exit_signal_date=date(2026, 1, 23),
        exit_execute_date=date(2026, 1, 24),
        exit_price=9.8,
        return_pct=-2.0,
        max_drawdown_pct=-3.0,
        max_runup_pct=1.0,
        holding_days=3,
        exit_reason="support_stop",
        window=tuple(bar for bar in bars if date(2026, 1, 21) <= bar.trade_date <= date(2026, 1, 24)),
    )
    ordinary_cluster = CandidateCluster(
        vt_symbol="600001.SSE",
        rows=(
            _candidate_quality_row("600001.SSE", date(2026, 1, 26), rank=1),
        ),
        cluster_start_date=date(2026, 1, 26),
        cluster_end_date=date(2026, 1, 26),
        entry_row=_candidate_quality_row("600001.SSE", date(2026, 1, 26), rank=1),
    )
    ordinary_result = IndependentTradeResult(
        status="open",
        cluster=ordinary_cluster,
        entry_signal_date=date(2026, 1, 26),
        entry_execute_date=date(2026, 1, 27),
        entry_price=10.0,
        exit_signal_date=None,
        exit_execute_date=None,
        exit_price=10.0,
        return_pct=0.0,
        max_drawdown_pct=0.0,
        max_runup_pct=0.0,
        holding_days=1,
        exit_reason="open",
        window=(),
    )

    baseline = candidate_trade_quality_report_from_results([source_result, ordinary_result], rank_limit=1)
    overlay = engine._support_stop_reentry_candidate_quality_overlay(
        [source_result, ordinary_result],
        bars_by_symbol={symbol: bars},
        params=BacktestParams(time_stop_days=999),
        buy_dates_by_symbol={symbol: {date(2026, 1, 20)}},
        candidate_limit=1,
        sample_limit=10,
    )

    assert baseline["summary"]["sample_count"] == 2
    assert overlay["not_used_for_signal_score"] is True
    assert overlay["not_used_for_portfolio_execution"] is True
    assert overlay["coverage"]["source_support_stop_count"] == 1
    assert overlay["coverage"]["reentry_candidate_count"] == 1
    assert overlay["reentry_only"]["sample_count"] == 1
    assert overlay["merged_append"]["sample_count"] == 3
    assert overlay["merged_daily_cap"]["sample_count"] == 2
    assert overlay["reentry_samples"][0]["entry_signal_date"] == "2026-01-26"
    assert overlay["reentry_samples"][0]["entry_reason"]["support_stop_reentry_spec"] == engine.SUPPORT_STOP_REENTRY_OVERLAY_SPEC["name"]


def test_candidate_trade_quality_reports_daily_topn_and_rank_windows() -> None:
    from alphaagent.server.services.backtest.factor_audit import (
        IndependentTradeResult,
        build_candidate_clusters,
        candidate_trade_quality_report_from_results,
    )

    clusters = build_candidate_clusters(
        [
            _candidate_quality_row("600001.SSE", date(2026, 1, 2), rank=1),
            _candidate_quality_row("600012.SSE", date(2026, 1, 2), rank=12),
            _candidate_quality_row("600025.SSE", date(2026, 1, 2), rank=25),
            _candidate_quality_row("600007.SSE", date(2026, 1, 3), rank=7),
        ]
    )
    returns_by_rank = {1: 10.0, 12: -5.0, 25: 2.0, 7: -3.0}
    results = []
    for cluster in clusters:
        signal_date = cluster.entry_row["trade_date"]
        rank = cluster.entry_row["rank"]
        results.append(
            IndependentTradeResult(
                status="closed",
                cluster=cluster,
                entry_signal_date=signal_date,
                entry_execute_date=signal_date,
                entry_price=10.0,
                exit_signal_date=signal_date,
                exit_execute_date=signal_date,
                exit_price=10.0,
                return_pct=returns_by_rank[rank],
                max_drawdown_pct=-2.0,
                max_runup_pct=12.0,
                holding_days=3,
                exit_reason="test_exit",
            )
        )

    report = candidate_trade_quality_report_from_results(results, rank_limit=50)
    rank_limits = {row["rank_limit"]: row for row in report["by_rank_limit"]}
    windows = {row["daily_rank_window"]: row for row in report["by_daily_rank_window"]}
    daily = {row["entry_signal_date"]: row for row in report["daily_summaries"]}

    assert rank_limits[10]["sample_count"] == 2
    assert rank_limits[10]["average_return_pct"] == 3.5
    assert rank_limits[20]["sample_count"] == 3
    assert rank_limits[20]["average_return_pct"] == 0.6667
    assert windows["rank_11_20"]["sample_count"] == 1
    assert windows["rank_11_20"]["average_return_pct"] == -5.0
    assert daily["2026-01-02"]["top10"]["sample_count"] == 1
    assert daily["2026-01-02"]["top20"]["sample_count"] == 2
    assert daily["2026-01-02"]["top20"]["average_return_pct"] == 2.5
    assert daily["2026-01-02"]["best_candidate"]["rank"] == 1


def test_candidate_trade_quality_bucket_audit_classifies_loss_and_winner_paths() -> None:
    from alphaagent.server.services.backtest.factor_audit import (
        IndependentTradeResult,
        build_daily_candidate_clusters,
        candidate_trade_quality_report_from_results,
    )

    rows = [
        _candidate_quality_row("600001.SSE", date(2026, 1, 2), rank=1),
        _candidate_quality_row("600002.SSE", date(2026, 1, 2), rank=2),
        _candidate_quality_row("600003.SSE", date(2026, 1, 2), rank=3, launch_confirmed=True),
    ]
    rows[0]["reason"]["ma5_distance_pct"] = 8.0
    rows[1]["reason"]["volume_stall_risk"] = True
    rows[2]["reason"]["low_suction_days"] = 5
    rows[2]["reason"]["first_effective_lift"] = True
    clusters = build_daily_candidate_clusters(rows)
    returns = {
        "600001.SSE": (-6.0, -7.0, 2.0),
        "600002.SSE": (-2.0, -4.0, 10.0),
        "600003.SSE": (12.0, -3.0, 18.0),
    }
    results = []
    for cluster in clusters:
        return_pct, mae, mfe = returns[cluster.vt_symbol]
        results.append(
            IndependentTradeResult(
                status="closed",
                cluster=cluster,
                entry_signal_date=cluster.entry_row["trade_date"],
                entry_execute_date=cluster.entry_row["trade_date"],
                entry_price=10.0,
                exit_signal_date=cluster.entry_row["trade_date"],
                exit_execute_date=cluster.entry_row["trade_date"],
                exit_price=10.0,
                return_pct=return_pct,
                max_drawdown_pct=mae,
                max_runup_pct=mfe,
                holding_days=4,
                exit_reason="test_exit",
            )
        )

    report = candidate_trade_quality_report_from_results(results, rank_limit=20)
    audit = report["bucket_audit"]
    loss_buckets = {row["bucket"]: row for row in audit["loss_buckets"]}
    winner_buckets = {row["bucket"]: row for row in audit["winner_buckets"]}
    path_buckets = {row["path_bucket"]: row for row in audit["path_buckets"]}

    assert audit["entry_selection"] == "daily_candidate"
    assert audit["coverage"]["sample_count"] == 3
    assert loss_buckets["pure_loss"]["sample_count"] == 1
    assert loss_buckets["ma5_overextended"]["sample_count"] == 1
    assert loss_buckets["loss_mfe_giveback"]["sample_count"] == 1
    assert loss_buckets["volume_stall"]["sample_count"] == 1
    assert winner_buckets["right_tail_winner"]["sample_count"] == 1
    assert winner_buckets["mature_low_suction_lift"]["sample_count"] == 1
    assert path_buckets["mfe_giveback"]["sample_count"] == 1


def test_candidate_trade_quality_volume_audit_groups_preparation_paths() -> None:
    from alphaagent.server.services.backtest.factor_audit import (
        IndependentTradeResult,
        build_daily_candidate_clusters,
        candidate_trade_quality_report_from_results,
    )

    rows = [
        _candidate_quality_row("600001.SSE", date(2026, 1, 2), rank=1),
        _candidate_quality_row("600002.SSE", date(2026, 1, 2), rank=2),
        _candidate_quality_row("600003.SSE", date(2026, 1, 2), rank=3),
    ]
    rows[0]["reason"].update(
        {
            "volume_ratio_5d_20d": 1.8,
            "volume_stall_risk": True,
            "large_bull_count_20d": 1,
        }
    )
    rows[1]["reason"].update(
        {
            "volume_ratio_5d_20d": 0.72,
            "low_suction_days": 4,
            "first_effective_lift": True,
            "recent_limit_up_20d": True,
        }
    )
    rows[2]["reason"].update(
        {
            "volume_ratio_5d_20d": 1.0,
            "low_suction_days": 0,
            "large_bull_count_20d": 0,
            "recent_limit_up_20d": False,
        }
    )
    clusters = build_daily_candidate_clusters(rows)
    returns = {
        "600001.SSE": (-10.0, -12.0, 2.0),
        "600002.SSE": (15.0, -3.0, 20.0),
        "600003.SSE": (-4.0, -5.0, 1.0),
    }
    results = []
    for cluster in clusters:
        return_pct, mae, mfe = returns[cluster.vt_symbol]
        results.append(
            IndependentTradeResult(
                status="closed",
                cluster=cluster,
                entry_signal_date=cluster.entry_row["trade_date"],
                entry_execute_date=cluster.entry_row["trade_date"],
                entry_price=10.0,
                exit_signal_date=cluster.entry_row["trade_date"],
                exit_execute_date=cluster.entry_row["trade_date"],
                exit_price=10.0,
                return_pct=return_pct,
                max_drawdown_pct=mae,
                max_runup_pct=mfe,
                holding_days=4,
                exit_reason="test_exit",
            )
        )

    audit = candidate_trade_quality_report_from_results(results, rank_limit=20)["volume_audit"]
    by_volume = {row["volume_bucket"]: row for row in audit["by_volume_ratio"]}
    by_preparation = {row["preparation_bucket"]: row for row in audit["by_preparation"]}
    path_preparation = {
        (row["loss_path"], row["preparation_bucket"]): row
        for row in audit["loss_path_by_preparation"]
    }

    assert audit["entry_selection"] == "daily_candidate"
    assert audit["coverage"]["sample_count"] == 3
    assert by_volume["heavy_volume_expansion"]["sample_count"] == 1
    assert by_volume["shrinking_volume"]["right_tail_count"] == 1
    assert by_preparation["volume_stall_distribution"]["deep_drawdown_loss_count"] == 1
    assert by_preparation["prepared_shrink_lift"]["right_tail_count"] == 1
    assert by_preparation["no_active_no_lift"]["pure_loss_count"] == 1
    assert path_preparation[("loss_deep_drawdown", "volume_stall_distribution")]["sample_count"] == 1
    assert path_preparation[("winner_or_flat", "prepared_shrink_lift")]["sample_count"] == 1


def test_candidate_trade_quality_marks_later_preferred_entry_audit_only() -> None:
    from alphaagent.server.services.backtest.factor_audit import (
        build_candidate_clusters,
        candidate_trade_quality_report_from_results,
        simulate_independent_candidate_trade,
    )
    from alphaagent.server.services.backtest.schemas import BacktestParams

    cluster = build_candidate_clusters([
        _candidate_quality_row("600000.SSE", date(2026, 1, 2), rank=3, score=80, launch_confirmed=False),
        _candidate_quality_row("600000.SSE", date(2026, 1, 3), rank=1, score=98, launch_confirmed=True),
    ])[0]
    bars = [
        Bar(date(2026, 1, 2), 10, 10.2, 9.8, 10),
        Bar(date(2026, 1, 3), 10, 10.6, 9.9, 10.5),
        Bar(date(2026, 1, 4), 10.5, 11, 10.4, 10.9),
    ]

    result = simulate_independent_candidate_trade(
        cluster,
        bars,
        params=BacktestParams(),
        sell_reason_fn=lambda *args, **kwargs: None,
    )
    report = candidate_trade_quality_report_from_results([result])
    item = report["items"][0]

    assert item["entry_selection"] == "daily_candidate"
    assert item["entry_signal_date"] == "2026-01-02"
    assert item["entry_execute_date"] == "2026-01-03"
    assert item["cluster_preferred_entry_signal_date_for_audit"] == "2026-01-03"
    assert item["cluster_preferred_entry_not_used_for_trade"] is True


def test_candidate_trade_quality_passes_current_buy_signal_to_sell_logic() -> None:
    from alphaagent.server.services.backtest.factor_audit import (
        build_candidate_clusters,
        simulate_independent_candidate_trade,
    )
    from alphaagent.server.services.backtest.schemas import BacktestParams

    cluster = build_candidate_clusters([
        _candidate_quality_row("600000.SSE", date(2026, 1, 2), rank=1),
    ])[0]
    bars = [
        Bar(date(2026, 1, 2), 10, 10.2, 9.8, 10),
        Bar(date(2026, 1, 3), 10, 10.5, 9.9, 10.2),
        Bar(date(2026, 1, 4), 10.2, 10.4, 9.9, 10.1),
        Bar(date(2026, 1, 5), 10.1, 10.4, 10.0, 10.3),
    ]
    seen_current_buy_signals = []

    def sell_when_current_buy_signal(position, bar, current_day, params, *, current_buy_signal=False, **kwargs):
        del position, bar, current_day, params, kwargs
        seen_current_buy_signals.append(current_buy_signal)
        return "current_buy_signal_seen" if current_buy_signal else None

    result = simulate_independent_candidate_trade(
        cluster,
        bars,
        params=BacktestParams(),
        sell_reason_fn=sell_when_current_buy_signal,
        buy_signal_dates={date(2026, 1, 4)},
    )

    assert True in seen_current_buy_signals
    assert result.status == "closed"
    assert result.exit_signal_date == date(2026, 1, 4)


def test_candidate_trade_quality_preserves_reason_for_contextual_failed_launch_exit() -> None:
    from alphaagent.server.services.backtest import simulation
    from alphaagent.server.services.backtest.factor_audit import (
        build_daily_candidate_clusters,
        candidate_feature_row,
        simulate_independent_candidate_trade,
    )
    from alphaagent.server.services.backtest.schemas import BacktestParams

    feature = candidate_feature_row(
        {
            "trade_date": date(2026, 1, 2),
            "vt_symbol": "600000.SSE",
            "rank": 1,
            "action": "BUY",
            "total_score": 88.0,
            "reason": {
                "action": "BUY",
                "entry_setup": "stealth_low_suction",
                "entry_family": "low_position_reclaim",
                "executable_entry_signal": True,
                "support_price": 10.0,
                "ma10": 10.0,
                "ma20": 9.7,
                "low_suction_days": 4,
            },
        }
    )
    cluster = build_daily_candidate_clusters([feature])[0]
    bars = [
        Bar(date(2026, 1, 2), 10.0, 10.2, 9.9, 10.0),
        Bar(date(2026, 1, 3), 10.0, 10.15, 9.9, 10.0),
        Bar(date(2026, 1, 4), 10.0, 10.1, 9.7, 9.78),
        Bar(date(2026, 1, 5), 9.78, 9.85, 9.65, 9.75),
        Bar(date(2026, 1, 6), 9.65, 9.7, 9.45, 9.5),
    ]

    result = simulate_independent_candidate_trade(
        cluster,
        bars,
        params=BacktestParams(enable_contextual_failed_launch_exit_stop=True),
        sell_reason_fn=simulation.sell_reason_for_position,
    )

    assert cluster.entry_row["reason"]["entry_setup"] == "stealth_low_suction"
    assert result.status == "closed"
    assert result.exit_reason == "contextual_failed_launch_exit_stop"
    assert result.exit_signal_date == date(2026, 1, 5)


def test_candidate_trade_quality_report_endpoint_passes_params(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_report(backtest_id, **kwargs):
        captured["backtest_id"] = backtest_id
        captured.update(kwargs)
        return {"status": "ready", "backtest_id": backtest_id, "summary": {"sample_count": 0}, "items": []}

    monkeypatch.setattr(backtests, "backtest_candidate_trade_quality_report", fake_report)
    client = TestClient(create_app())

    response = client.get(
        "/api/backtests/203/candidate-trade-quality-report"
        "?rank_limit=20&sample_limit=25&start_date=2026-01-01&end_date=2026-02-01"
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ready"
    assert captured == {
        "backtest_id": 203,
        "rank_limit": 20,
        "sample_limit": 25,
        "start_date": date(2026, 1, 1),
        "end_date": date(2026, 2, 1),
    }


def test_candidate_trade_quality_report_endpoint_validates_limits(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    monkeypatch.setattr(backtests, "backtest_candidate_trade_quality_report", lambda *args, **kwargs: {"status": "ready"})
    client = TestClient(create_app())

    response = client.get("/api/backtests/203/candidate-trade-quality-report?rank_limit=21")

    assert response.status_code == 422


def test_candidate_trade_quality_report_builds_full_candidate_cache(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    captured = {}

    def fake_cache(backtest_id, *, limit):
        captured["backtest_id"] = backtest_id
        captured["limit"] = limit
        return {"status": "unavailable", "coverage": {}}

    monkeypatch.setattr(engine, "is_database_configured", lambda: True)
    monkeypatch.setattr(engine, "_ensure_backtest_schema", lambda: None)
    monkeypatch.setattr(engine, "ensure_factor_audit_cache", fake_cache)

    result = engine.backtest_candidate_trade_quality_report(203)

    assert result["status"] == "unavailable"
    assert captured == {"backtest_id": 203, "limit": 20000}


def test_candidate_trade_quality_scope_uses_execution_selected_inside_candidate_limit() -> None:
    from alphaagent.server.services.backtest import engine

    run_row = {"params": {"candidate_limit": 20}}
    selected = {
        "rank": 24,
        "candidate_execution": {"execution_candidate_rank": 18, "execution_candidate_selected": True},
    }
    filtered = {
        "rank": 19,
        "candidate_execution": {
            "execution_candidate_selected": False,
            "execution_quality_filtered": True,
        },
    }

    assert engine._candidate_quality_cluster_in_scope(selected, 20, run_row) is True
    assert engine._candidate_quality_cluster_in_scope(filtered, 20, run_row) is False
    assert engine._candidate_quality_cluster_in_scope(filtered, 100, run_row) is True


def test_backtest_performance_attribution_endpoint_passes_params(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_report(backtest_id, **kwargs):
        captured["backtest_id"] = backtest_id
        captured.update(kwargs)
        return {"status": "ready", "backtest_id": backtest_id, "reference_backtest_id": kwargs["reference_backtest_id"]}

    monkeypatch.setattr(backtests, "backtest_performance_attribution_report", fake_report)
    client = TestClient(create_app())

    response = client.get("/api/backtests/274/performance-attribution?reference_backtest_id=203&sample_limit=12")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ready"
    assert captured == {"backtest_id": 274, "reference_backtest_id": 203, "sample_limit": 12}


def test_backtest_performance_attribution_endpoint_validates_sample_limit(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    monkeypatch.setattr(backtests, "backtest_performance_attribution_report", lambda *args, **kwargs: {"status": "ready"})
    client = TestClient(create_app())

    response = client.get("/api/backtests/274/performance-attribution?sample_limit=101")

    assert response.status_code == 422
