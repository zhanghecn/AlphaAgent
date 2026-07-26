from datetime import date

import pandas as pd

from alphaagent.server.services.limit_up.daily_proxy_quality import (
    attach_causal_stock_profitability,
    build_daily_proxy_frame,
    evaluate_daily_proxy,
)


def test_daily_proxy_builds_touch_entry_without_inventing_signal_time(monkeypatch) -> None:
    monkeypatch.setattr(
        "alphaagent.server.services.limit_up.daily_proxy_quality.financial_snapshot_as_of",
        lambda *args: {"net_profit_yoy": 20.0},
    )
    monkeypatch.setattr(
        "alphaagent.server.services.limit_up.daily_proxy_quality.financial_risk_as_of",
        lambda *args: {"blocked": False},
    )
    frame = pd.DataFrame.from_records(
        [
            _feature_row(date(2026, 1, 5), "600001.SSE", touched=True),
            _feature_row(date(2026, 1, 5), "600002.SSE", touched=False),
        ]
    )

    result = build_daily_proxy_frame(frame, {}, start=date(2026, 1, 1), end=date(2026, 1, 31))

    assert result["vt_symbol"].tolist() == ["600001.SSE"]
    assert result.iloc[0]["entry_price"] == 11.0
    assert result.iloc[0]["signal_time"] is None
    assert result.iloc[0]["execution_confidence"] == "daily_touch_proxy_without_time_or_queue"
    assert result.iloc[0]["return_pct"] > 0


def test_causal_stock_profitability_uses_only_matured_prior_events() -> None:
    rows = []
    dates = pd.bdate_range("2026-01-05", periods=7).date
    for index, trade_date in enumerate(dates):
        rows.append(
            {
                "trade_date": trade_date,
                "result_date": dates[index + 1] if index + 1 < len(dates) else None,
                "vt_symbol": "600001.SSE",
                "lane": "first_board",
                "daily_structural_eligible": True,
                "outcome_sealed": True,
                "return_pct": 2.0,
                "prior_seal_success_rate_126": 0.8,
            }
        )

    result = attach_causal_stock_profitability(pd.DataFrame.from_records(rows))

    assert result.loc[0, "stock_d1_sample_count"] == 0
    assert result.loc[1, "stock_d1_sample_count"] == 0
    assert result.loc[6, "stock_d1_sample_count"] == 5
    assert bool(result.loc[6, "profitability_gate_passed"]) is True


def test_causal_stock_profitability_expires_events_by_market_sessions() -> None:
    market_dates = pd.bdate_range("2024-01-02", periods=260).date.tolist()
    rows = [
        {
            "trade_date": trade_date,
            "result_date": market_dates[index + 1],
            "vt_symbol": "600001.SSE",
            "lane": "first_board",
            "daily_structural_eligible": True,
            "outcome_sealed": True,
            "return_pct": 2.0,
            "prior_seal_success_rate_126": 0.8,
        }
        for index, trade_date in enumerate(market_dates[:5])
    ]
    rows.append(
        {
            **rows[-1],
            "trade_date": market_dates[-1],
            "result_date": None,
        }
    )

    result = attach_causal_stock_profitability(
        pd.DataFrame.from_records(rows),
        trade_dates=market_dates,
    )

    assert result.iloc[-1]["stock_d1_sample_count"] == 0
    assert result.iloc[-1]["profitability_gate_reason"] == "same_stock_d1_samples_below_5"


def test_daily_proxy_evaluation_reports_core_complement_separately() -> None:
    frame = pd.DataFrame.from_records(
        [
            _evaluation_row(date(2024, 1, 2), 3, 1.1, 2.0),
            _evaluation_row(date(2024, 1, 3), 4, 1.2, 1.0),
            _evaluation_row(date(2024, 1, 4), 1, 1.3, -2.0),
            _evaluation_row(date(2024, 1, 5), 8, 0.8, -3.0),
        ]
    )

    result = evaluate_daily_proxy(frame)["pools"]["daily_structural"]

    assert result["core"]["closed_count"] == 2
    assert result["core"]["win_rate_pct"] == 100.0
    assert result["incremental_complement"]["closed_count"] == 2
    assert result["incremental_complement"]["win_rate_pct"] == 0.0
    assert result["core_before_real_event_coverage"]["closed_count"] == 2


def _feature_row(trade_date: date, symbol: str, *, touched: bool) -> dict[str, object]:
    return {
        "trade_date": pd.Timestamp(trade_date),
        "next_trade_date": pd.Timestamp("2026-01-06"),
        "vt_symbol": symbol,
        "name": symbol,
        "touched": touched,
        "sealed": touched,
        "prev_close": 10.0,
        "limit_price": 11.0,
        "next_close_price": 11.5,
        "prior_streak": 0,
        "prior_limit_count_5": 0,
        "prior_limit_count_126": 3,
        "prior_touch_count_126": 8,
        "prior_seal_success_rate_126": 0.5,
        "prior_position_120": 0.4,
        "pullback_from_prior_limit_pct": -10.0,
        "trade_days_since_prior_limit": 10,
        "prior_industry_heat_score": 60.0,
        "prior_industry_turnover_ratio_5d": 1.1,
        "prior_market_failed_rate": 0.4,
        "auction_gap_pct": 2.0,
    }


def _evaluation_row(
    trade_date: date,
    limit_count: int,
    industry_turnover: float,
    return_pct: float,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "vt_symbol": f"60000{limit_count}.SSE",
        "lane": "first_board",
        "return_pct": return_pct,
        "daily_structural_eligible": True,
        "profitability_gate_passed": True,
        "prior_limit_count_126": limit_count,
        "prior_industry_turnover_ratio_5d": industry_turnover,
    }
