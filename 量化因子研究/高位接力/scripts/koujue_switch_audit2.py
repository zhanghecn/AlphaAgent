# -*- coding: utf-8 -*-
"""动态口诀切换审计·第二轮: 窗宽敏感性+口诀级对照+2023漏票逐笔明细。
容器内跑: docker exec -i vnpy-alphaagent-api-1 python < 本文件
"""
import sys
from collections import defaultdict

import pandas as pd

from alphaagent.server.services.high_relay import backtest, contracts


def log(*a):
    print(*a, file=sys.stderr)


def avg(xs):
    return sum(xs) / len(xs) if xs else None


def main() -> None:
    log("全量事件回放...")
    E, _bars = backtest.build_events()
    done = E[~E["未完"]].copy()
    dyn_trades = backtest._dyn_trades(done)
    states = contracts.dyn_month_states(dyn_trades)

    rich = []
    for _, r in done.iterrows():
        e3 = r.get("E3%")
        if e3 is None or e3 != e3:
            continue
        wk = str(r.get("弱口诀") or "—")
        pt = str(r.get("方案点") or "—")
        g, p = ("weak", wk) if wk != "—" else (("strong", pt) if pt != "—" else (None, None))
        if g is None:
            continue
        rich.append({"m": str(r["月"]), "g": g, "p": p, "r": round(float(e3), 2),
                     "name": str(r.get("名称") or ""), "buy": str(r["买入日"])[:10],
                     "y": str(r["月"])[:4]})
    tm = sorted({t["m"] for t in rich})
    tmi = {m: i for i, m in enumerate(tm)}
    ALL_K = sorted({t["p"] for t in rich})

    def states_w(window):
        out = {}
        for i, m in enumerate(tm):
            ms = set(tm[max(0, i - window):i])
            wk = [t["r"] for t in rich if t["m"] in ms and t["g"] == "weak"]
            st = [t["r"] for t in rich if t["m"] in ms and t["g"] == "strong"]
            wa, sa = avg(wk), avg(st)
            if len(wk) >= 8 and len(st) >= 8 and wa is not None and sa is not None:
                out[m] = "weak" if wa > sa else "strong"
            elif len(wk) >= 8 and wa is not None and wa > 0:
                out[m] = "weak"
            elif len(st) >= 8 and sa is not None and sa > 0:
                out[m] = "strong"
            else:
                out[m] = "both"
        return out

    # ════ 1. 窗宽敏感性: 各窗宽的切换点(2023年前后) ════
    print("=" * 26, "1. 窗宽敏感性(切换点对比)", "=" * 26)
    for w in (6, 9, 12, 15, 18):
        sw = states_w(w)
        pts = []
        st0 = "both"
        for m in sorted(sw):
            if sw[m] != st0:
                pts.append(f"{m}:{st0[:2]}→{sw[m][:2]}")
                st0 = sw[m]
        print(f"  窗{w:>2}月: {' | '.join(pts)}")

    def sim(states_d):
        """按月状态出手(both=两组任一; 双命中归weak), 返回逐笔"""
        out = []
        for m in sorted(states_d):
            s = states_d[m]
            for t in rich:
                if t["m"] != m:
                    continue
                if s == "both" or t["g"] == s:
                    out.append(t)
        return out

    def book(name, out, only_year=None):
        out2 = [t for t in out if not only_year or t["y"] == only_year]
        if not out2:
            print(f"  {name:<28} 0笔")
            return
        rs = [t["r"] for t in out2]
        yr = defaultdict(float)
        for t in out2:
            yr[t["y"]] += t["r"]
        print(f"  {name:<28} {len(rs):>3}笔 胜{sum(1 for x in rs if x > 0) / len(rs):.0%} "
              f"均{avg(rs):+.2f} 和{sum(rs):+8.1f} | " +
              " ".join(f"{y}:{v:+.0f}" for y, v in sorted(yr.items())))

    print()
    print("  七年总账(各窗宽):")
    book("全开(两组并集)", rich)
    for w in (6, 9, 12, 15, 18):
        book(f"两组切换·窗{w}月", sim(states_w(w)))
    print()
    print("  仅2023年:")
    book("全开", rich, "2023")
    for w in (6, 9, 12, 15, 18):
        book(f"两组切换·窗{w}月", sim(states_w(w)), "2023")
    st_h = {**states_w(12)}
    for m in st_h:
        if m >= "2023-01":
            st_h[m] = "strong"
    book("完美后见(2023-01即strong)", sim(st_h), "2023")

    # ════ 2. 口诀级开关对照(变体B: 每条口诀近12交易月n≥3且均>0才开) ════
    print()
    print("=" * 26, "2. 口诀级开关(为什么不用它抓漏)", "=" * 26)

    def sim_koujue():
        out = []
        open_track = []
        for i, m in enumerate(tm):
            ms = set(tm[max(0, i - 12):i])
            allowed = set()
            for p in ALL_K:
                rs = [t["r"] for t in rich if t["m"] in ms and t["p"] == p]
                if len(rs) >= 3 and avg(rs) > 0:
                    allowed.add(p)
            open_track.append((m, sorted(allowed)))
            for t in rich:
                if t["m"] == m and t["p"] in allowed:
                    out.append(t)
        return out, open_track

    ko, open_track = sim_koujue()
    book("口诀级滚动(12月,n≥3)", ko)
    book("口诀级滚动·仅2023", ko, "2023")
    print("  2023-06/07/08 各口诀拖尾12月(n/均)与开关状态:")
    for m in ("2023-06", "2023-07", "2023-08"):
        ms = set(tm[max(0, tmi[m] - 12):tmi[m]])
        cells = []
        for p in ALL_K:
            rs = [t["r"] for t in rich if t["m"] in ms and t["p"] == p]
            if not rs:
                continue
            a = avg(rs)
            cells.append(f"{p}:{len(rs)}笔{a:+.1f}{'√' if len(rs) >= 3 and a > 0 else '×'}")
        print(f"    {m}  " + "  ".join(cells))

    # ════ 3. 2023 漏票逐笔明细 ════
    print()
    print("=" * 26, "3. 2023 被停组命中·逐笔", "=" * 26)
    for m in sorted({t["m"] for t in rich if t["y"] == "2023"}):
        s = contracts.dyn_state_at(states, m)
        off = [t for t in rich if t["m"] == m and t["g"] != s and s != "both"]
        for t in off:
            print(f"  {m} [{t['g'][:2]}停] {t['p']:<4}{t['name']:<8} E3{t['r']:+7.1f} "
                  f"买{t['buy']}")


main()
