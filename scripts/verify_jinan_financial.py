"""验证 operating_cash_flow 同比修复后金安 6-3 的 financial 分。"""

from __future__ import annotations

from datetime import date

from sqlalchemy import text

from alphaagent.server.db.session import session_scope
from alphaagent.server.services.quant.financials import (
    as_report_date,
    financial_scores_from_rows_by_symbol,
    operating_cash_flow_yoy,
)

TRADE_DATE = date(2026, 6, 3)


def main() -> int:
    with session_scope() as s:
        rows = list(
            s.execute(
                text(
                    "SELECT * FROM stock_financial_reports WHERE vt_symbol='002636.SZSE' "
                    "ORDER BY report_date DESC"
                )
            ).mappings()
        )
        rows_list = [dict(r) for r in rows]
        scores = financial_scores_from_rows_by_symbol({"002636.SZSE": rows_list}, TRADE_DATE)
        print(f"金安 6-3 financial(修复后) = {scores.get('002636.SZSE'):.2f}  (修复前=54)", flush=True)

        current = None
        for r in rows_list:
            pd = as_report_date(r.get("publish_date"))
            if pd and pd <= TRADE_DATE:
                current = r
                break
        if current:
            yoy = operating_cash_flow_yoy(rows_list, current, TRADE_DATE)
            print(f"当期 report={str(current.get('report_date'))[:10]} ocf={current.get('operating_cash_flow')}", flush=True)
            print(f"ocf_yoy(同比改善) = {yoy:+.1f}%  → 评分加 max(min(yoy/5,12),-12) = {max(min(yoy/5,12),-12) if yoy else 'N/A'}", flush=True)

        # 顺带验证 002585（财务83，对照组，现金流本来就正）
        rows2 = list(
            s.execute(
                text(
                    "SELECT * FROM stock_financial_reports WHERE vt_symbol='002585.SZSE' "
                    "ORDER BY report_date DESC"
                )
            ).mappings()
        )
        scores2 = financial_scores_from_rows_by_symbol({"002585.SZSE": [dict(r) for r in rows2]}, TRADE_DATE)
        print(f"\n002585 6-3 financial(修复后) = {scores2.get('002585.SZSE'):.2f}  (修复前=83，对照组)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
