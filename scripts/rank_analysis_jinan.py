"""金安 002636.SZSE 6-03 排名根因：对比金安 vs 当天 top5 的各子分。

查清：金安 6-03 entry=True（TAIL_BUY_READY），但 rank#14 没进 top10。
对比当天 top5 各子分，找金安哪个子分偏低 → 合理提升空间。
"""

from __future__ import annotations

from sqlalchemy import text

from alphaagent.server.db.session import session_scope

DATE = "2026-06-03"
TARGET = "002636.SZSE"


def _scores(row: dict, score_cols: list[str]) -> dict:
    return {c: row.get(c) for c in score_cols if row.get(c) is not None}


def main() -> int:
    with session_scope() as s:
        # 1. 数值型 _score 列
        cols = s.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='quant_stock_signals' ORDER BY ordinal_position"
            )
        ).scalars().all()
        score_cols = [c for c in cols if c.endswith("_score")]
        print(f"子分列({len(score_cols)}): {score_cols}", flush=True)

        # 2. 金安 6-03
        print(f"\n{'=' * 72}\n金安 {TARGET} {DATE}\n{'=' * 72}", flush=True)
        tgt = s.execute(
            text(
                "SELECT * FROM quant_stock_signals "
                "WHERE vt_symbol=:v AND strategy_id='mainline_dragon_pullback' AND trade_date=:d"
            ),
            {"v": TARGET, "d": DATE},
        ).mappings().first()
        if not tgt:
            print("无信号！", flush=True)
        else:
            for c in score_cols:
                v = tgt.get(c)
                vs = f"{float(v):.1f}" if isinstance(v, (int, float)) else v
                print(f"  {c:<28} = {vs}", flush=True)
            ev = tgt.get("evidence") or {}
            print(f"  dragon_state  = {ev.get('dragon_state')}", flush=True)
            print(f"  entry_signal  = {tgt.get('entry_signal')}", flush=True)
            print(f"  score_notes   = {ev.get('score_notes')}", flush=True)

        # 3. top5 各子分
        print(f"\n{'=' * 72}\n{DATE} top5 候选各子分\n{'=' * 72}", flush=True)
        top = s.execute(
            text(
                "SELECT vt_symbol, total_score, rank FROM quant_recommendations "
                "WHERE strategy_id='mainline_dragon_pullback' AND trade_date=:d AND rank<=5 "
                "ORDER BY rank"
            ),
            {"d": DATE},
        ).mappings().all()
        header = "  #rank symbol         total"
        for c in score_cols:
            if c == "total_score":
                continue
            header += f" {c.replace('_score','').replace('total_','t')[:6]:>6}"
        print(header, flush=True)
        for t in top:
            sig = s.execute(
                text(
                    "SELECT * FROM quant_stock_signals "
                    "WHERE vt_symbol=:v AND strategy_id='mainline_dragon_pullback' AND trade_date=:d"
                ),
                {"v": t["vt_symbol"], "d": DATE},
            ).mappings().first()
            line = f"  #{t['rank']:<4}{t['vt_symbol']:<15}{float(t['total_score']):>6.1f}"
            if sig:
                for c in score_cols:
                    if c == "total_score":
                        continue
                    v = sig.get(c)
                    line += f"{float(v):>6.0f}" if isinstance(v, (int, float)) else f"{'?':>6}"
            print(line, flush=True)

        # 4. 金安当天排名
        print(f"\n{'=' * 72}\n金安在 {DATE} 排名\n{'=' * 72}", flush=True)
        rec = s.execute(
            text(
                "SELECT rank, total_score FROM quant_recommendations "
                "WHERE vt_symbol=:v AND strategy_id='mainline_dragon_pullback' AND trade_date=:d"
            ),
            {"v": TARGET, "d": DATE},
        ).mappings().first()
        if rec:
            print(f"  rank={rec['rank']} total={float(rec['total_score']):.1f}", flush=True)
        else:
            cnt = s.execute(
                text(
                    "SELECT count(*) FROM quant_recommendations "
                    "WHERE strategy_id='mainline_dragon_pullback' AND trade_date=:d"
                ),
                {"d": DATE},
            ).scalar()
            print(f"  未进推荐表（当天推荐共 {cnt} 条 = 前100）", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
