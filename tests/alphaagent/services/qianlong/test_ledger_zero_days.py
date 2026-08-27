"""Tests for zero-trade days merged into the qianlong ledger.

「建过池但零开张」的日子(如 2026-08-26 全池零触发)以 0 笔入册,
证明覆盖完整而非数据缺失;月度汇总在合并前完成,零行不影响统计。
"""

from __future__ import annotations

from alphaagent.server.services.qianlong.service import _merge_zero_trade_days


def _day(trade_date: str, count: int = 1) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "trades": [{}] * count,
        "count": count,
        "win": count,
        "avg_ret_pct": 1.0 if count else None,
    }


def test_zero_days_appended_and_sorted_desc() -> None:
    days = [_day("2026-08-25"), _day("2026-08-21")]
    pool_dates = ["2026-08-26", "2026-08-24", "2026-08-22", "2026-08-25"]

    out = _merge_zero_trade_days(days, pool_dates, month_prefix=None)

    assert [d["trade_date"] for d in out] == [
        "2026-08-26", "2026-08-25", "2026-08-24", "2026-08-22", "2026-08-21",
    ]
    added = {d["trade_date"]: d for d in out if d["trade_date"] in {"2026-08-26", "2026-08-24"}}
    assert all(d["count"] == 0 and d["trades"] == [] and d["avg_ret_pct"] is None
               for d in added.values())


def test_zero_days_respect_month_filter() -> None:
    days: list[dict[str, object]] = []
    pool_dates = ["2026-08-26", "2026-07-30"]

    out = _merge_zero_trade_days(days, pool_dates, month_prefix="2026-08")

    assert [d["trade_date"] for d in out] == ["2026-08-26"]


def test_zero_days_keep_month_summaries_unaffected() -> None:
    """月度汇总基于合并前的成交日列表计算(服务内顺序),零行不得污染。"""
    from alphaagent.server.services.qianlong.service import _month_summaries

    days = [_day("2026-08-25"), _day("2026-08-21")]
    months = _month_summaries(days)
    out = _merge_zero_trade_days(
        days, ["2026-08-26", "2026-08-24"], month_prefix="2026-08")

    # 合并后的列表喂给 _month_summaries 时,零行同样不应改变统计
    after = _month_summaries(out)
    assert months == after
