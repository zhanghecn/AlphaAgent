"""池哨兵 get_pool_alert:次日池未按时产出时报警+原因(11-04 事故产物)。"""

from __future__ import annotations

from datetime import date, datetime

from alphaagent.server.services.high_relay import service


def _now(day: str, hour: int, minute: int = 0, weekday: int | None = None) -> datetime:
    # 2026-11-04 是周三;按需选周末日 2026-11-07(六)
    dt = datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00+08:00")
    if weekday is not None:
        assert dt.weekday() == weekday
    return dt


def _data(**over):
    base = {
        "next_pool_date": None,
        "today_has_bars": True,
        "batch_status": "partial",
        "batch_started_at": datetime.fromisoformat("2026-11-04T18:00:28+08:00"),
        "failed_jobs": [
            {"job_id": "sync_stock_daily_bars", "message": "日线覆盖未完成：5 只"},
        ],
    }
    base.update(over)
    return base


def test_weekend_is_ok(monkeypatch):
    monkeypatch.setattr(service.repository, "pool_sentinel_data", lambda _t: _data())
    out = service.get_pool_alert(_now("2026-11-07", 20, 0, weekday=5))
    assert out["status"] == "ok"
    assert "reasons" not in out


def test_next_pool_present_is_ok(monkeypatch):
    monkeypatch.setattr(service.repository, "pool_sentinel_data",
                        lambda _t: _data(next_pool_date=date(2026, 11, 5)))
    out = service.get_pool_alert(_now("2026-11-04", 20, 0, weekday=2))
    assert out["status"] == "ok"
    assert out["next_pool_date"] == "2026-11-05"


def test_before_alert_hour_is_ok(monkeypatch):
    monkeypatch.setattr(service.repository, "pool_sentinel_data", lambda _t: _data())
    out = service.get_pool_alert(_now("2026-11-04", 18, 30, weekday=2))
    assert out["status"] == "ok"
    assert "盘后批窗口内" in str(out.get("detail"))


def test_running_batch_today_is_ok(monkeypatch):
    monkeypatch.setattr(service.repository, "pool_sentinel_data",
                        lambda _t: _data(batch_status="running"))
    out = service.get_pool_alert(_now("2026-11-04", 19, 30, weekday=2))
    assert out["status"] == "ok"
    assert "仍在运行" in str(out.get("detail"))


def test_missing_pool_after_hour_alerts_with_reasons(monkeypatch):
    monkeypatch.setattr(service.repository, "pool_sentinel_data", lambda _t: _data())
    out = service.get_pool_alert(_now("2026-11-04", 19, 30, weekday=2))
    assert out["status"] == "alert"
    assert out["message"] == "今晚次日池未更新"
    assert out["batch_status"] == "partial"
    assert any("次日池未产出" in r for r in out["reasons"])
    assert any("sync_stock_daily_bars" in r and "5 只" in r for r in out["reasons"])


def test_no_bars_today_reports_sync_failure(monkeypatch):
    monkeypatch.setattr(service.repository, "pool_sentinel_data",
                        lambda _t: _data(today_has_bars=False, failed_jobs=[]))
    out = service.get_pool_alert(_now("2026-11-04", 19, 30, weekday=2))
    assert out["status"] == "alert"
    assert any("今日日线未入库" in r for r in out["reasons"])
