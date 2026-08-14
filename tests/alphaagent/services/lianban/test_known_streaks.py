"""known_streaks.verify_known_streaks 报告结构单测(sqlite 夹具)。

真实数据断言(天普15/ST中迪22/秦安5)在容器内对开发库执行,见
alphaagent/server/services/lianban/known_streaks.py 模块 docstring。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import insert

from alphaagent.server.db import schema
from alphaagent.server.services.lianban.known_streaks import (
    KNOWN_STREAK_CASES,
    KnownStreakCase,
    verify_known_streaks,
)


def _row(vt_symbol: str, trade_date: date, streak: int, *, is_up: bool = True) -> dict:
    return {
        "vt_symbol": vt_symbol,
        "trade_date": trade_date,
        "is_limit_up": is_up,
        "limit_up_count": streak,
        "board": "main",
    }


def test_verify_known_streaks_pass_and_structure(fake_session):
    case = KnownStreakCase(
        vt_symbol="600001.SSE",
        name="测试妖股",
        window_start=date(2026, 8, 3),
        window_end=date(2026, 8, 14),
        expected_peak_streak=3,
    )
    fake_session.execute(
        insert(schema.stock_limit_up_daily),
        [
            _row("600001.SSE", date(2026, 8, 10), 1),
            _row("600001.SSE", date(2026, 8, 11), 2),
            _row("600001.SSE", date(2026, 8, 12), 3),
            # 窗口外的更高峰值不应计入
            _row("600001.SSE", date(2026, 9, 1), 9),
        ],
    )

    report = verify_known_streaks(fake_session, (case,))

    assert report["all_passed"] is True
    (result,) = report["cases"]
    assert result["passed"] is True
    assert result["actual_peak_streak"] == 3
    assert result["peak_date"] == "2026-08-12"
    assert result["limit_up_days"] == 3


def test_verify_known_streaks_mismatch_and_missing(fake_session):
    mismatch = KnownStreakCase(
        vt_symbol="600001.SSE",
        name="峰值不符",
        window_start=date(2026, 8, 3),
        window_end=date(2026, 8, 14),
        expected_peak_streak=5,
    )
    missing = KnownStreakCase(
        vt_symbol="600002.SSE",
        name="无数据",
        window_start=date(2026, 8, 3),
        window_end=date(2026, 8, 14),
        expected_peak_streak=2,
    )
    fake_session.execute(
        insert(schema.stock_limit_up_daily),
        [_row("600001.SSE", date(2026, 8, 10), 1)],
    )

    report = verify_known_streaks(fake_session, (mismatch, missing))

    assert report["all_passed"] is False
    first, second = report["cases"]
    assert first["passed"] is False
    assert first["actual_peak_streak"] == 1
    assert second["passed"] is False
    assert second["reason"] == "no rows in window"


def test_builtin_cases_reference_real_symbols():
    vt_symbols = {case.vt_symbol for case in KNOWN_STREAK_CASES}
    assert {"605255.SSE", "000609.SZSE", "603758.SSE"} <= vt_symbols
