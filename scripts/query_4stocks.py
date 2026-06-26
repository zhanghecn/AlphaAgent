"""查主人 4 买点股票在关键日期的龙回头评分 + 候选排名 + 当天 top5 对比。

搞清为什么这些买点没进龙回头候选 top5。
"""

from __future__ import annotations

from sqlalchemy import text

from alphaagent.server.db.session import session_scope

STOCKS = ["600367.SSE", "002384.SZSE", "600487.SSE", "002636.SZSE"]
# 主人提的关键买点日期窗口
WINDOWS = [
    ("2026-01 买点", "2026-01-10", "2026-01-20"),
    ("2026-06-04 买点", "2026-06-01", "2026-06-09"),
    ("2026-06-12 买点", "2026-06-09", "2026-06-15"),
]


def main() -> int:
    with session_scope() as s:
        # 先确认 4 股票有没有任何龙回头信号
        for vts in STOCKS:
            cnt = s.execute(
                text(
                    "SELECT count(*), min(trade_date), max(trade_date) "
                    "FROM quant_stock_signals WHERE vt_symbol=:vts AND strategy_id='dragon_pullback'"
                ),
                {"vts": vts},
            ).first()
            print(f"{vts}: 龙回头信号 {cnt[0]} 条，{cnt[1]} ~ {cnt[2]}", flush=True)

        for label, start, end in WINDOWS:
            print(f"\n{'=' * 78}", flush=True)
            print(f"{label} ({start} ~ {end})", flush=True)
            print("=" * 78, flush=True)

            # 当天 top5 候选（看 top5 是谁、分数多高）
            top = s.execute(
                text(
                    "SELECT trade_date, vt_symbol, rank, total_score, action "
                    "FROM quant_recommendations "
                    "WHERE strategy_id='dragon_pullback' AND rank<=5 "
                    "AND trade_date BETWEEN :s AND :e "
                    "ORDER BY trade_date, rank"
                ),
                {"s": start, "e": end},
            ).mappings().all()
            cur_date = None
            for r in top:
                if r["trade_date"] != cur_date:
                    cur_date = r["trade_date"]
                    print(f"\n  [{cur_date}] top5 候选:", flush=True)
                print(
                    f"    #{r['rank']} {r['vt_symbol']:<12} score={r['total_score']:.1f} {r['action']}",
                    flush=True,
                )

            # 4 股票在这些日期的信号 + 是否进候选
            print(f"\n  --- 4 买点股票的评分/排名 ---", flush=True)
            for vts in STOCKS:
                sig = s.execute(
                    text(
                        "SELECT trade_date, total_score, entry_signal, risk_score, "
                        "washout_score, trend_quality_score, relative_strength_score "
                        "FROM quant_stock_signals "
                        "WHERE vt_symbol=:vts AND strategy_id='dragon_pullback' "
                        "AND trade_date BETWEEN :s AND :e ORDER BY trade_date"
                    ),
                    {"vts": vts, "s": start, "e": end},
                ).mappings().all()
                rec = s.execute(
                    text(
                        "SELECT trade_date, rank, total_score, action "
                        "FROM quant_recommendations "
                        "WHERE vt_symbol=:vts AND strategy_id='dragon_pullback' "
                        "AND trade_date BETWEEN :s AND :e ORDER BY trade_date"
                    ),
                    {"vts": vts, "s": start, "e": end},
                ).mappings().all()
                rec_by_date = {r["trade_date"]: r for r in rec}
                if not sig:
                    print(f"    {vts}: 该窗口无龙回头信号", flush=True)
                    continue
                print(f"    {vts}:", flush=True)
                for r in sig:
                    rb = rec_by_date.get(r["trade_date"])
                    rank = f"排名#{rb['rank']}" if rb else "未进候选"
                    # top5 门槛：当天 top5 最低分
                    top5_scores = [
                        t["total_score"]
                        for t in top
                        if t["trade_date"] == r["trade_date"]
                    ]
                    gate = min(top5_scores) if top5_scores else None
                    gap = f"(距top5门槛 {r['total_score'] - gate:+.1f})" if gate else ""
                    print(
                        f"      {r['trade_date']} score={r['total_score']:.1f} "
                        f"entry={bool(r['entry_signal'])} {rank} {gap} "
                        f"[risk={r['risk_score']:.0f} washout={r['washout_score']:.0f} "
                        f"trend={r['trend_quality_score']:.0f} RS={r['relative_strength_score']:.0f}]",
                        flush=True,
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
