"""Focused tests for low-suction live payload paging."""

from datetime import date

from alphaagent.server.services.low_suction import daily_picks_service
from alphaagent.server.services.low_suction.daily_picks_service import (
    _exclude_current_st_candidates,
    _paginate_live_payload,
)
from alphaagent.server.services.low_suction.daily_picks_scanner import (
    LowSuctionCandidate,
)
from alphaagent.server.services.low_suction.daily_picks_scoring import QuietStreak


def _candidate(vt_symbol: str) -> LowSuctionCandidate:
    return LowSuctionCandidate(
        vt_symbol=vt_symbol,
        trade_date=date(2026, 8, 6),
        setup_type="oversold_rebound",
        rule_key="test_rule",
        matched_rule_keys=("test_rule",),
        score=50.0,
        band="40-59",
        streak=QuietStreak(total=0, yin=0, yang=0),
        components=(),
        close_price=10.0,
        daily_return_pct=0.0,
        turnover_rate_pct=2.0,
        candle_range_pct=1.0,
        d1_trade_date=None,
        d1_close_return_pct=None,
    )


def test_live_pagination_keeps_each_family_within_cached_top_hundred() -> None:
    payload = {
        "status": "ok",
        "trend": {
            "total": 140,
            "limit": 100,
            "items": [{"rank": value} for value in range(1, 101)],
        },
        "oversold": {
            "total": 7,
            "limit": 100,
            "items": [{"rank": value} for value in range(1, 8)],
        },
    }

    paged = _paginate_live_payload(payload, trend_page=3, oversold_page=9)

    assert payload["trend"]["items"][0]["rank"] == 1
    assert paged["trend"]["page"] == 3
    assert paged["trend"]["pages"] == 5
    assert [item["rank"] for item in paged["trend"]["items"]] == list(range(41, 61))
    assert paged["oversold"]["page"] == 1
    assert paged["oversold"]["pages"] == 1
    assert [item["rank"] for item in paged["oversold"]["items"]] == list(range(1, 8))


def test_backtest_candidate_filter_matches_live_current_name_st_screen() -> None:
    candidates = [_candidate("000001.SZSE"), _candidate("000002.SZSE")]

    filtered = _exclude_current_st_candidates(
        candidates,
        {"000001.SZSE": "平安银行", "000002.SZSE": "*ST样例"},
    )

    assert [candidate.vt_symbol for candidate in filtered] == ["000001.SZSE"]


def test_daily_backtest_report_rejects_stale_scoring_payload(monkeypatch) -> None:
    payload = {
        "version": daily_picks_service.BACKTEST_VERSION,
        "score_version": "low-suction-daily-score-v2.4",
    }
    monkeypatch.setattr(
        daily_picks_service,
        "load_daily_backtest_run",
        lambda: payload,
    )

    assert daily_picks_service.get_daily_backtest_report() is None


def test_daily_backtest_report_rejects_stale_backtest_payload(monkeypatch) -> None:
    payload = {
        "version": "low-suction-daily-backtest-v2",
        "score_version": daily_picks_service.SCORE_VERSION,
    }
    monkeypatch.setattr(
        daily_picks_service,
        "load_daily_backtest_run",
        lambda: payload,
    )

    assert daily_picks_service.get_daily_backtest_report() is None


def test_daily_backtest_report_accepts_matching_versions(monkeypatch) -> None:
    payload = {
        "version": daily_picks_service.BACKTEST_VERSION,
        "score_version": daily_picks_service.SCORE_VERSION,
    }
    monkeypatch.setattr(
        daily_picks_service,
        "load_daily_backtest_run",
        lambda: payload,
    )

    assert daily_picks_service.get_daily_backtest_report() == payload
