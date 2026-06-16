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
    assert [item["id"] for item in list_strategies()] == ["mainline_dragon_pullback"]
    assert "mainline_leader_pullback" in {item["id"] for item in list_internal_strategies()}
    assert score.signal_type == "mainline_leader_pullback"
    assert score.evidence["entry_setup"] == "ma5_pullback"


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


def test_dragon_pullback_score_accepts_ma10_support_reclaim() -> None:
    start = date(2026, 1, 1)
    closes = [20 + index * 0.12 for index in range(74)]
    closes.extend([29.0, 31.9, 35.1, 38.6, 42.1, 39.4, 37.2, 36.8, 37.3, 39.0])
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


def test_dragon_pullback_suppresses_repeated_tail_buy_ready_setup() -> None:
    start = date(2026, 1, 1)
    closes = [20 + index * 0.12 for index in range(74)]
    closes.extend([29.0, 31.9, 35.1, 38.6, 42.1, 39.4, 37.2, 36.8, 37.3, 39.0, 38.0])
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
        bars[:-1],
        bars[-2].trade_date,
        index_return_20d=-2.0,
        sector_score=82.0,
        financial_score=65.0,
        fund_flow_score=70.0,
        hot_rank_score=70.0,
        lhb_score=65.0,
    )
    repeated_ready = score_dragon_pullback(
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

    assert first_ready.evidence["dragon_state"] == "TAIL_BUY_READY"
    assert first_ready.evidence["fresh_tail_buy"] is True
    assert first_ready.entry_signal is True
    assert repeated_ready.evidence["dragon_state"] == "TAIL_BUY_READY"
    assert repeated_ready.evidence["fresh_tail_buy"] is False
    assert "repeat_tail_buy_setup" in repeated_ready.evidence["failed_rules"]
    assert repeated_ready.entry_signal is False


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
    assert strategies["mainline_dragon_pullback"]["primary_metric_keys"] == ["dragon_state", "support_type", "ma5_distance_pct"]
    assert strategies["mainline_dragon_pullback"]["evidence_labels"]["support_type"] == "承接类型"


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
        highest_price=140.0,
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
            "orders": [{"status": "rejected", "reason": "position_slot_unavailable", "reason_label": "持仓名额不足"}],
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
    assert "资金" in summary["next_action"]


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
    monkeypatch.setattr(
        engine,
        "_simulate",
        lambda session, params, bars_by_symbol_arg, trading_days_arg, stock_meta, score_context=None: {
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
            "recommendation_limit": 10,
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
    assert captured["max_positions"] == 10
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
                    "strategy_version": "0.1.1",
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
                    "strategy_version": "0.1.1",
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
                    "strategy_version": "0.1.1",
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


def test_quant_recommendation_marks_buy_only_for_entry_signal() -> None:
    from alphaagent.server.services.quant import screening

    buy_score = SignalScore(
        vt_symbol="600000.SSE",
        trade_date=date(2026, 1, 2),
        total_score=72,
        entry_signal=True,
        evidence={"status": "ready"},
    )
    watch_score = SignalScore(
        vt_symbol="000001.SZSE",
        trade_date=date(2026, 1, 2),
        total_score=72,
        entry_signal=False,
        evidence={"status": "ready"},
    )

    assert screening._recommendation_to_db(1, buy_score, None, "mainline_leader_pullback")["action"] == "BUY"
    assert screening._recommendation_to_db(2, watch_score, None, "mainline_leader_pullback")["action"] == "WATCH"


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
        {"vt_symbol": "600000.SSE", "exchange": "SSE", "turnover": 200, "market_cap": 200},
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

    default_symbols = [row["vt_symbol"] for row in screening._load_stock_universe(FakeSession(), 10, ("main",))]
    all_symbols = [row["vt_symbol"] for row in screening._load_stock_universe(FakeSession(), 10, ("main", "chinext", "star", "bse"))]

    assert "300750.SZSE" not in default_symbols
    assert "688981.SSE" not in default_symbols
    assert "920001.BSE" not in default_symbols
    assert default_symbols == ["600000.SSE"]
    assert "300750.SZSE" in all_symbols
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
                    ("300750.SZSE", "SZSE"),
                    ("600000.SSE", "SSE"),
                    ("688981.SSE", "SSE"),
                ]
            )

    generated = engine._load_symbol_universe(FakeSession(), 10, None, ("main",))
    requested = engine._load_symbol_universe(FakeSession(), 10, ["300750.SZSE"], ("main",))

    assert generated == ["600000.SSE"]
    assert requested == ["300750.SZSE"]


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
        def execute(self, statement):
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


def test_recommendations_use_latest_screen_run_id_when_latest_run_has_no_items(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    executed: list[str] = []

    class FakeRows:
        def __init__(self, rows=None):
            self.rows = rows or []

        def mappings(self):
            return self

        def first(self):
            return self.rows[0] if self.rows else None

        def all(self):
            return []

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
                        "params": {"included_boards": ["main"]},
                    }
                ])
            return FakeRows()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)

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
                        "params": {"included_boards": ["main"]},
                    }
                ])
            return FakeRows([])

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)

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

    result = screening.list_trading_dates(limit=20)

    assert result["status"] == "ready"
    assert result["latest_trade_date"] == "2026-06-12"
    assert result["earliest_trade_date"] == "2026-06-11"
    assert result["returned_count"] == 2
    assert result["items"] == [
        {"trade_date": "2026-06-12", "symbol_count": 2},
        {"trade_date": "2026-06-11", "symbol_count": 1},
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
    monkeypatch.setattr(screening, "_screen_runs_by_date", lambda session, strategy_id, strategy_version, trade_dates: {})
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
    monkeypatch.setattr(screening, "_screen_runs_by_date", lambda session, strategy_id, strategy_version, trade_dates: {})
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
    monkeypatch.setattr(screening, "_screen_runs_by_date", lambda session, strategy_id, strategy_version, trade_dates: {})
    monkeypatch.setattr(screening, "screen_stocks", fake_screen_stocks)

    result = screening.screen_stocks_range(start=date(2026, 6, 10), included_boards=["main"])

    assert calls == [
        (date(2026, 6, 10), False),
        (date(2026, 6, 11), False),
        (date(2026, 6, 12), True),
    ]
    assert result["status"] == "ready"
    assert result["start_date"] == "2026-06-10"
    assert result["end_date"] == "2026-06-12"
    assert result["trade_date"] == "2026-06-12"
    assert result["total_dates"] == 3
    assert result["succeeded_count"] == 3
    assert result["range_recommendation_count"] == 6
    assert result["recommendation_count"] == 3
    assert result["portfolio_sync"] == {"synced": 1}
    assert [item["trade_date"] for item in result["runs"]] == ["2026-06-10", "2026-06-11", "2026-06-12"]


def test_screen_stocks_range_skips_existing_persisted_dates(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

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
        "params": {"included_boards": ["main"]},
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
        lambda session, strategy_id, strategy_version, trade_dates: {date(2026, 6, 10): existing_run},
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


def test_screen_stocks_range_force_refresh_regenerates_existing_persisted_dates(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

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
        "params": {"included_boards": ["main"]},
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
        lambda session, strategy_id, strategy_version, trade_dates: {date(2026, 6, 10): existing_run},
    )
    monkeypatch.setattr(screening, "screen_stocks", fake_screen_stocks)

    result = screening.screen_stocks_range(
        start=date(2026, 6, 10),
        end=date(2026, 6, 11),
        persist=True,
        included_boards=["main"],
        force_refresh=True,
    )

    assert generated_dates == [date(2026, 6, 10), date(2026, 6, 11)]
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
        "params": {"included_boards": ["main"]},
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
        lambda session, strategy_id, strategy_version, trade_dates: {date(2026, 6, 10): empty_run},
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
    monkeypatch.setattr(screening, "_screen_runs_by_date", lambda session, strategy_id, strategy_version, trade_dates: {})
    monkeypatch.setattr(screening, "screen_stocks", fake_screen_stocks)

    result = screening.screen_stocks_range(
        start=date(2026, 6, 10),
        end=date(2026, 6, 12),
        included_boards=["main"],
        progress=progress_events.append,
    )

    assert result["status"] == "ready"
    assert [event["trade_date"] for event in progress_events] == ["2026-06-10", "2026-06-11", "2026-06-12"]
    assert [event["progress_current"] for event in progress_events] == [1, 2, 3]
    assert {event["progress_total"] for event in progress_events} == {3}
    assert all(event["status"] == "ready" for event in progress_events)


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
            "evidence": {"status": "ready", "ma5": 10.0},
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
    from alphaagent.server.services.quant import symbol_quant_state

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
                        "params": {"included_boards": ["main"]},
                        "metrics": {"attempt_count": 0},
                        "message": None,
                    }
                )
            if "FROM quant_signal_runs" in text:
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
                            "evidence": {"status": "ready", "close_price": 29.7},
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
        evidence={"status": "ready"},
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
    assert result["summary"] == "候选为 BUY，组合回测已下单并成交。"
    assert result["equity"]["cash"] == 989_897
    assert result["trades"][0]["amount"] == 10_100


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
    assert result["summary"] == "候选是 WATCH，默认组合回测不会买入观察股。"


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
        evidence={"status": "ready", "note": "unit_test_candidate"},
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
        evidence={"status": "ready", "note": "unit_test_candidate"},
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
    assert captured["params"].candidate_limit == 10
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
                "raw": {"execution": {"mode": "minute_1430", "price_source": "stock_minute_bars.close_price", "proxy_used": False}},
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
    assert row["execution_mode"] == "minute_1430"
    assert row["exit_reason_label"] == "止盈"
