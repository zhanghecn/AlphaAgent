from __future__ import annotations

from datetime import date

from alphaagent.server.services.backtest import scoring
from alphaagent.server.services.backtest.schemas import BacktestParams
from alphaagent.server.services.quant.factors import Bar, DRAGON_PULLBACK_STRATEGY_ID, SignalScore
from alphaagent.server.services.quant.retreat_momentum_source import board_survival_pressure_source_allowed


def test_score_day_passes_only_signal_date_visible_bars_to_retreat_source(monkeypatch) -> None:
    captured: dict[str, date] = {}
    signal_date = date(2026, 3, 17)
    future_date = date(2026, 3, 18)
    raw = SignalScore(
        vt_symbol="603693.SSE",
        trade_date=signal_date,
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=90.0,
        liquidity_score=80.0,
        risk_score=70.0,
        entry_signal=False,
        evidence={"status": "ready"},
    )

    def fake_scorer(session, bars_by_symbol, trade_date, params, score_context):
        assert bars_by_symbol["603693.SSE"][-1].trade_date == signal_date
        return [raw]

    def fake_append(scores, *, visible_bars, **kwargs):
        captured["latest_visible_date"] = visible_bars["603693.SSE"][-1].trade_date
        return list(scores)

    monkeypatch.setattr(
        scoring.retreat_momentum_source,
        "append_board_survival_pressure_sources",
        fake_append,
    )

    params = BacktestParams(
        strategy=DRAGON_PULLBACK_STRATEGY_ID,
        start=signal_date,
        end=future_date,
        min_entry_score=68.0,
        strict_entry=False,
        persist=False,
    )
    scoring.score_day(
        None,
        {
            "603693.SSE": [
                Bar(signal_date, 10.0, 11.0, 9.9, 11.0),
                Bar(future_date, 11.0, 12.0, 10.8, 12.0),
            ]
        },
        signal_date,
        params,
        score_candidates_for_day=fake_scorer,
    )

    assert captured["latest_visible_date"] == signal_date


def test_board_survival_source_rejects_sparse_theme_unless_raw_rank_is_frontrow() -> None:
    sparse_late = _board_source(raw_rank=178, theme_source_count=1)
    sparse_frontrow = _board_source(raw_rank=107, theme_source_count=1)
    confirmed_theme = _board_source(raw_rank=178, theme_source_count=2)

    assert board_survival_pressure_source_allowed(sparse_late) is False
    assert board_survival_pressure_source_allowed(sparse_frontrow) is True
    assert board_survival_pressure_source_allowed(confirmed_theme) is True


def _board_source(*, raw_rank: int, theme_source_count: int) -> SignalScore:
    return SignalScore(
        vt_symbol="603693.SSE",
        trade_date=date(2026, 3, 17),
        signal_type=DRAGON_PULLBACK_STRATEGY_ID,
        total_score=94.0,
        liquidity_score=80.0,
        risk_score=70.0,
        entry_signal=True,
        evidence={
            "status": "ready",
            "entry_setup": "retreat_high_low_switch_momentum",
            "retreat_momentum_board_survival_source": True,
            "retreat_momentum_subtype": "active_first_pullback_switch",
            "retreat_momentum_opportunity_score": 94.0,
            "retreat_momentum_raw_signal_rank": raw_rank,
            "retreat_momentum_theme_confirmed": True,
            "retreat_momentum_theme_source_rank": 1,
            "retreat_momentum_theme_source_count": theme_source_count,
            "timing_window": "after_silver_late",
            "market_phase": "retreat",
            "latest_change_pct": 9.8,
            "return_5d": 18.0,
            "return_20d": 28.0,
            "return_60d": 35.0,
            "ma20_distance_pct": 18.0,
            "near_limit_up_count_20d": 2,
            "volume_ratio_5d_20d": 1.6,
            "board_is_limit_up": True,
            "board_near_limit_close": True,
            "board_failed_limit_up": False,
            "board_close_location_in_range": 1.0,
            "board_upper_shadow_pct": 0.0,
            "board_limit_up_streak": 1,
            "board_limit_up_count_5d": 2,
            "board_theme_promoted_limit_up_count": 1,
        },
    )
