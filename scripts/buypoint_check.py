"""主人 6 个买点检查（最新 run 口径）：entry=True? rank? 距 top5 门槛差多少?

每个买点取该日期最新 screen-run 的信号 + 推荐，看：
1. 当天 entry_signal 是否 True（门控放行）
2. 进没进 top5（rank<=5）
3. 没进的话，总分距当天 top5 最低分差多少
4. dragon_state + score_notes（解释为什么 entry=False 或分低）
"""

from __future__ import annotations

from sqlalchemy import text

from alphaagent.server.db.session import session_scope

BUYPOINTS = [
    ("600367.SSE", "2026-05-22"),
    ("002384.SZSE", "2026-06-12"),
    ("600487.SSE", "2025-12-17"),
    ("600487.SSE", "2026-01-15"),
    ("600487.SSE", "2026-02-09"),
    ("002636.SZSE", "2026-06-04"),
]


def latest_run(s, date: str) -> int | None:
    return s.execute(
        text(
            "SELECT max(run_id) FROM quant_stock_signals "
            "WHERE strategy_id='mainline_dragon_pullback' AND trade_date=:d"
        ),
        {"d": date},
    ).scalar()


def main() -> int:
    with session_scope() as s:
        for vts, date in BUYPOINTS:
            run = latest_run(s, date)
            print(f"\n{'=' * 76}", flush=True)
            print(f"{vts}  买点 {date}  (最新 run={run})", flush=True)
            print("=" * 76, flush=True)
            if not run:
                print("  该日期无任何 screen-run 信号", flush=True)
                continue

            # 目标股票该 run 的信号
            sig = s.execute(
                text(
                    "SELECT total_score, entry_signal, evidence "
                    "FROM quant_stock_signals "
                    "WHERE vt_symbol=:v AND strategy_id='mainline_dragon_pullback' "
                    "AND trade_date=:d AND run_id=:r"
                ),
                {"v": vts, "d": date, "r": run},
            ).mappings().first()
            if not sig:
                print("  该 run 无此股票信号", flush=True)
                continue
            ev = sig.get("evidence") or {}
            print(
                f"  total={float(sig['total_score']):.1f}  entry={bool(sig['entry_signal'])}  "
                f"state={ev.get('dragon_state')}",
                flush=True,
            )

            # 该 run 当天 top5 门槛
            top5 = s.execute(
                text(
                    "SELECT total_score, rank, action FROM quant_recommendations "
                    "WHERE strategy_id='mainline_dragon_pullback' AND trade_date=:d "
                    "AND run_id=:r AND rank<=5 ORDER BY rank"
                ),
                {"d": date, "r": run},
            ).mappings().all()
            if not top5:
                # recommendations 可能没 run_id 列，退化查该日期所有
                top5 = s.execute(
                    text(
                        "SELECT DISTINCT ON (vt_symbol) total_score, rank, action "
                        "FROM quant_recommendations "
                        "WHERE strategy_id='mainline_dragon_pullback' AND trade_date=:d "
                        "AND rank<=5 ORDER BY vt_symbol, run_id DESC"
                    ),
                    {"d": date},
                ).mappings().all()
                top5 = sorted(top5, key=lambda x: x["rank"])[:5]
            if top5:
                gate = min(float(t["total_score"]) for t in top5)
                gap = float(sig["total_score"]) - gate
                print(
                    f"  top5 门槛={gate:.1f}  距门槛 {gap:+.1f}  "
                    f"{'✅已进top5' if gap >= 0 else '❌未进top5'}",
                    flush=True,
            )
            else:
                print("  当天无 top5 推荐数据", flush=True)

            # 目标股票 rank（若进推荐）
            rec = s.execute(
                text(
                    "SELECT rank, total_score, action FROM quant_recommendations "
                    "WHERE vt_symbol=:v AND strategy_id='mainline_dragon_pullback' "
                    "AND trade_date=:d ORDER BY run_id DESC LIMIT 1"
                ),
                {"v": vts, "d": date},
            ).mappings().first()
            if rec:
                print(f"  推荐排名: rank={rec['rank']} total={float(rec['total_score']):.1f} {rec['action']}", flush=True)
            else:
                print("  推荐排名: 未进推荐表（rank>100 或 entry=False）", flush=True)

            notes = ev.get("score_notes") or []
            if notes:
                print(f"  score_notes: {notes}", flush=True)
            failed = ev.get("failed_rules") or []
            if failed:
                print(f"  failed_rules: {failed}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
