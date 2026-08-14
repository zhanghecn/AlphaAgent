"""Tests for the data health dashboard freshness logic.

Covers cadence metadata, staleness evaluation (eod_daily / quarterly disclosure
season / lhb time window / intraday), disclosure-season detection, and
recommended-job ordering. Pure-function tests — no database required. See
memory/03_data/data_flow.md「数据健康仪表盘 + 推荐同步」.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from alphaagent.server.services import data_sync as svc

_CN = timezone(timedelta(hours=8))


def test_job_cadences_cover_all_default_jobs():
    """Every DEFAULT_JOBS entry must have a cadence entry."""
    cadenced = set(svc.JOB_CADENCES)
    for job in svc.DEFAULT_JOBS:
        assert job.id in cadenced, f"{job.id} missing from JOB_CADENCES"


def test_categories_have_labels_and_order():
    for key in svc.CATEGORY_ORDER:
        assert key in svc.CATEGORY_LABELS
    # critical categories for overall-health red logic
    assert svc.CATEGORY_MARKET_BASIC in svc.CATEGORY_ORDER
    assert svc.CATEGORY_MARKET_BARS in svc.CATEGORY_ORDER


def test_disclosure_season_windows():
    # A-share disclosure: 1 / 4 / 7 / 8 / 10 + early-May annual-report tail
    assert svc._is_disclosure_season(datetime(2026, 1, 15, tzinfo=_CN))
    assert svc._is_disclosure_season(datetime(2026, 4, 30, tzinfo=_CN))
    assert svc._is_disclosure_season(datetime(2026, 7, 1, tzinfo=_CN))
    assert svc._is_disclosure_season(datetime(2026, 8, 31, tzinfo=_CN))
    assert svc._is_disclosure_season(datetime(2026, 10, 31, tzinfo=_CN))
    assert svc._is_disclosure_season(datetime(2026, 5, 15, tzinfo=_CN))
    # off-season must NOT trigger (avoids false "financial stale" in June)
    assert not svc._is_disclosure_season(datetime(2026, 6, 15, tzinfo=_CN))
    assert not svc._is_disclosure_season(datetime(2026, 5, 16, tzinfo=_CN))


def test_eod_daily_staleness_against_latest_trade_date():
    cad = svc.JOB_CADENCES["sync_stock_daily_bars"]
    now = datetime(2026, 6, 19, 22, 0, tzinfo=_CN)  # Friday EOD
    latest = date(2026, 6, 19)
    # caught up → fresh
    sev, _, stale = svc._evaluate_job_staleness(cad, now, latest, False, latest)
    assert not stale and sev == "fresh"
    # 2 trading days behind → stale
    sev, reason, stale = svc._evaluate_job_staleness(cad, now, latest, False, date(2026, 6, 17))
    assert stale and sev == "stale"
    assert "2" in reason
    # no local data → empty
    sev, _, stale = svc._evaluate_job_staleness(cad, now, latest, False, None)
    assert stale and sev == "empty"


def test_quarterly_not_flagged_off_season():
    """Off disclosure-season, financial jobs must not be flagged stale (June safety)."""
    cad = svc.JOB_CADENCES["sync_stock_financial_quarterly"]
    now = datetime(2026, 6, 15, tzinfo=_CN)  # June, off-season
    sev, _, stale = svc._evaluate_job_staleness(cad, now, date(2026, 6, 13), False, date(2026, 3, 31))
    assert not stale and sev == "fresh"
    # disclosure season + old data → stale
    now_april = datetime(2026, 4, 15, tzinfo=_CN)
    sev, _, stale = svc._evaluate_job_staleness(cad, now_april, date(2026, 4, 14), True, date(2026, 1, 1))
    assert stale and sev == "stale"


def test_lhb_time_window_before_18h():
    """Dragon-tiger list publishes after 18:00; intraday tolerates last trade day."""
    cad = svc.JOB_CADENCES["sync_stock_lhb_records"]
    latest = date(2026, 6, 19)
    # 14:00, local = previous trade day → fresh (today not published yet)
    sev, _, stale = svc._evaluate_job_staleness(
        cad, datetime(2026, 6, 19, 14, 0, tzinfo=_CN), latest, False, date(2026, 6, 18)
    )
    assert not stale and sev == "fresh"
    # 22:00 (after publish), local behind → stale
    sev, _, stale = svc._evaluate_job_staleness(
        cad, datetime(2026, 6, 19, 22, 0, tzinfo=_CN), latest, False, date(2026, 6, 18)
    )
    assert stale and sev == "stale"
    # 14:00 but 5 days behind → still stale (genuinely behind)
    sev, _, stale = svc._evaluate_job_staleness(
        cad, datetime(2026, 6, 19, 14, 0, tzinfo=_CN), latest, False, date(2026, 6, 14)
    )
    assert stale


def test_intraday_staleness_by_hours():
    cad = svc.JOB_CADENCES["sync_stock_fund_flows"]
    now = datetime(2026, 6, 19, 22, 0, tzinfo=_CN)
    # 3 hours ago → fresh
    sev, _, stale = svc._evaluate_job_staleness(cad, now, date(2026, 6, 19), False, now - timedelta(hours=3))
    assert not stale and sev == "fresh"
    # 3 days ago → stale
    sev, _, stale = svc._evaluate_job_staleness(cad, now, date(2026, 6, 19), False, now - timedelta(days=3))
    assert stale


def test_recommended_jobs_sorted_by_priority():
    results = {
        "sync_stock_lhb_records": {"is_stale": True},
        "sync_stock_daily_bars": {"is_stale": True},
        "sync_stock_list": {"is_stale": False},  # fresh → excluded
        "sync_stock_financial_quarterly": {"is_stale": True},
    }
    rec = svc._compute_recommended_jobs(results)
    assert rec == ["sync_stock_daily_bars", "sync_stock_financial_quarterly", "sync_stock_lhb_records"]
    assert "sync_stock_list" not in rec


def test_stock_daily_incomplete_health_marks_latest_partial_date_without_recommending_sync():
    severity, reason, stale = svc._stock_daily_incomplete_health(
        {
            "latest_trade_date": "2026-07-07",
            "latest_trade_date_symbol_count": 1446,
            "latest_complete_trade_date": "2026-07-06",
            "min_complete_daily_symbol_count": 3000,
        }
    )

    assert stale is False
    assert severity == "partial"
    assert "1446/3000" in reason
    assert "2026-07-06" in reason


def test_stock_daily_incomplete_health_ignores_complete_latest_date():
    assert svc._stock_daily_incomplete_health(
        {
            "latest_trade_date": "2026-07-07",
            "latest_trade_date_symbol_count": 5524,
            "latest_complete_trade_date": "2026-07-07",
            "min_complete_daily_symbol_count": 3000,
        }
    ) is None


def test_stock_daily_health_recommends_sync_when_history_depth_is_underfilled():
    severity, reason, stale = svc._stock_daily_incomplete_health(
        {
            "latest_trade_date": "2026-07-15",
            "latest_trade_date_symbol_count": 5532,
            "latest_complete_trade_date": "2026-07-15",
            "min_complete_daily_symbol_count": 3000,
            "reliable_history_trade_days": 268,
            "target_history_trade_days": 750,
            "history_depth_ready": False,
        }
    )

    assert stale is True
    assert severity == "stale"
    assert "268/750" in reason
    assert "历史" in reason


def test_stock_daily_health_accepts_ready_history_depth():
    assert svc._stock_daily_incomplete_health(
        {
            "latest_trade_date": "2026-07-15",
            "latest_trade_date_symbol_count": 5532,
            "latest_complete_trade_date": "2026-07-15",
            "min_complete_daily_symbol_count": 3000,
            "reliable_history_trade_days": 800,
            "target_history_trade_days": 750,
            "history_depth_ready": True,
        }
    ) is None


def test_data_health_exposes_stock_daily_history_depth(monkeypatch):
    stock_daily_coverage = {
        "count": 3_300_000,
        "latest_trade_date": "2026-07-15",
        "latest_complete_trade_date": "2026-07-15",
        "latest_trade_date_symbol_count": 5_532,
        "reliable_history_start": "2023-03-28",
        "reliable_history_end": "2026-07-15",
        "reliable_history_trade_days": 799,
        "target_history_trade_days": 750,
        "history_depth_ready": True,
    }
    monkeypatch.setattr(
        svc,
        "coverage",
        lambda: {"tables": {"stock_daily_bars": stock_daily_coverage}},
    )
    monkeypatch.setattr(
        svc,
        "_resolve_latest_trade_date",
        lambda: (date(2026, 7, 15), "stock_daily_bars.complete"),
    )
    monkeypatch.setattr(svc, "_collect_freshness_probes", lambda: {})
    monkeypatch.setattr(
        svc,
        "_lianban_parity_health",
        lambda: {"health": "unknown", "reason": "test stub"},
    )

    context = svc.data_health()["market_context"]

    assert context["reliable_history_start"] == "2023-03-28"
    assert context["reliable_history_end"] == "2026-07-15"
    assert context["reliable_history_trade_days"] == 799
    assert context["target_history_trade_days"] == 750
    assert context["history_depth_ready"] is True


def test_data_health_exposes_lianban_parity(monkeypatch):
    """payload 顶层带 lianban_parity 摘要(连板双口径对账), 由巡检函数原样透传。"""
    monkeypatch.setattr(svc, "coverage", lambda: {"tables": {}})
    monkeypatch.setattr(
        svc,
        "_resolve_latest_trade_date",
        lambda: (date(2026, 8, 12), "stock_daily_bars.complete"),
    )
    monkeypatch.setattr(svc, "_collect_freshness_probes", lambda: {})
    monkeypatch.setattr(
        svc,
        "_lianban_parity_health",
        lambda: {
            "health": "warning",
            "trade_date": "2026-08-12",
            "status": "ok",
            "verdict": "major_diff",
            "diff_count": 3,
            "em_count": 92,
            "daily_count": 91,
            "matched": 90,
        },
    )

    parity = svc.data_health()["lianban_parity"]

    assert parity["health"] == "warning"
    assert parity["verdict"] == "major_diff"
    assert parity["diff_count"] == 3
    assert parity["em_count"] == 92
