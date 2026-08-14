"""已知妖股连板案例验证 — 全历史重建数据资产的可信度断言。

这些案例的连板数来自公开复盘记录(2026-08-13 人工核对):
- 天普股份(605255): 2025-08-22 首板 → 2025-09-23 十五连板(中间两次停牌核查,
  streak 跨停牌延续)
- ST中迪(000609): 2025-10-17 首板 → 2025-11-20 二十二连板(ST 5% 档,
  11-13~11-17 停牌)
- 秦安股份(603758): 2026-08-07 首板 → 2026-08-13 五连板(08-11 起一字板)

用途:全量重建/判定器改动后在容器里跑一次,确认数据资产没有漂移:

    docker exec vnpy-alphaagent-data-sync-worker-1 python -c \\
        "from alphaagent.server.db.session import session_scope; \\
         from alphaagent.server.services.lianban.known_streaks import verify_known_streaks; \\
         from alphaagent.server.db.session import get_engine; \\
         import json; \\
         with session_scope() as s: \\
             r = verify_known_streaks(s); \\
         print(json.dumps(r, ensure_ascii=False, indent=1)); \\
         assert r['all_passed'], r"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select

from alphaagent.server.db import schema


@dataclass(frozen=True)
class KnownStreakCase:
    vt_symbol: str
    name: str
    window_start: date
    window_end: date
    expected_peak_streak: int
    note: str = ""


KNOWN_STREAK_CASES: tuple[KnownStreakCase, ...] = (
    KnownStreakCase(
        vt_symbol="605255.SSE",
        name="天普股份",
        window_start=date(2025, 8, 20),
        window_end=date(2025, 10, 10),
        expected_peak_streak=15,
        note="2025-09 芯片妖股,两次停牌核查 streak 延续",
    ),
    KnownStreakCase(
        vt_symbol="000609.SZSE",
        name="ST中迪",
        window_start=date(2025, 10, 14),
        window_end=date(2025, 11, 25),
        expected_peak_streak=22,
        note="2025-10 ST 5% 档连板王",
    ),
    KnownStreakCase(
        vt_symbol="603758.SSE",
        name="秦安股份",
        window_start=date(2026, 8, 5),
        window_end=date(2026, 8, 13),
        expected_peak_streak=5,
        note="2026-08-13 总龙头,5天5板",
    ),
)


def verify_known_streaks(
    session: Any,
    cases: tuple[KnownStreakCase, ...] = KNOWN_STREAK_CASES,
) -> dict[str, Any]:
    """对每个案例查 stock_limit_up_daily 窗口内 max(limit_up_count) 并比对期望值。

    返回 {"all_passed": bool, "cases": [{...}]},单案例含实际峰值/峰值日/轨迹长度。
    数据缺失(表空/股票无行)记为 failed 并附 reason,不抛异常。
    """

    table = schema.stock_limit_up_daily
    results: list[dict[str, Any]] = []
    for case in cases:
        rows = session.execute(
            select(table.c.trade_date, table.c.limit_up_count)
            .where(
                table.c.vt_symbol == case.vt_symbol,
                table.c.is_limit_up.is_(True),
                table.c.trade_date >= case.window_start,
                table.c.trade_date <= case.window_end,
            )
            .order_by(table.c.trade_date)
        ).all()
        if not rows:
            results.append(
                {
                    "vt_symbol": case.vt_symbol,
                    "name": case.name,
                    "passed": False,
                    "reason": "no rows in window",
                    "expected_peak_streak": case.expected_peak_streak,
                }
            )
            continue
        peak = max(int(r.limit_up_count) for r in rows)
        peak_date = max(r.trade_date for r in rows if int(r.limit_up_count) == peak)
        results.append(
            {
                "vt_symbol": case.vt_symbol,
                "name": case.name,
                "passed": peak == case.expected_peak_streak,
                "expected_peak_streak": case.expected_peak_streak,
                "actual_peak_streak": peak,
                "peak_date": peak_date.isoformat(),
                "limit_up_days": len(rows),
                "note": case.note,
            }
        )
    return {"all_passed": all(r["passed"] for r in results), "cases": results}
