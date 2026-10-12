# -*- coding: utf-8 -*-
"""v7.15 vs v7.14 切换器分年对比: 每年总收益+胜率(研究口径同数据重算两配置)。
容器内跑: docker exec -i vnpy-alphaagent-api-1 python < 本文件
"""
import sys
from collections import defaultdict

from alphaagent.server.services.high_relay import backtest, contracts, repository


def log(*a):
    print(*a, file=sys.stderr)


def avg(xs):
    return sum(xs) / len(xs) if xs else None


def main() -> None:
    log("回放...")
    E, _bars = backtest.build_events()
    done = E[~E["未完"]].copy()
    rich = []
    for _, r in done.iterrows():
        e3 = r.get("E3%")
        if e3 is None or e3 != e3:
            continue
        wk = str(r.get("弱口诀") or "—")
        pt = str(r.get("方案点") or "—")
        g = "weak" if wk != "—" else ("strong" if pt != "—" else None)
        if g is None:
            continue
        rich.append((str(r["月"]), g, round(float(e3), 2), str(r["月"])[:4]))
    tm = sorted({t[0] for t in rich})
    by_m = defaultdict(list)
    for t in rich:
        by_m[t[0]].append(t)

    def states_for(metric, w, n_min):
        def m(rs):
            if metric == "trim3":
                core = sorted(rs)[:-3] if len(rs) > 3 else rs
                return sum(core) / len(core)
            return sum(rs) / len(rs)

        out = {}
        for i, mo in enumerate(tm):
            ms = set(tm[max(0, i - w):i])
            wk = [t[2] for t in rich if t[0] in ms and t[1] == "weak"]
            st = [t[2] for t in rich if t[0] in ms and t[1] == "strong"]
            wa, sa = m(wk) if wk else None, m(st) if st else None
            if len(wk) >= n_min and len(st) >= n_min and wa is not None and sa is not None:
                out[mo] = "weak" if wa > sa else "strong"
            elif len(wk) >= n_min and wa is not None and wa > 0:
                out[mo] = "weak"
            elif len(st) >= n_min and sa is not None and sa > 0:
                out[mo] = "strong"
            else:
                out[mo] = "both"
        return out

    def sim(sd):
        out, cur = [], "both"
        for mo in tm:
            cur = sd.get(mo, cur)
            out.extend(t for t in by_m[mo] if cur == "both" or t[1] == cur)
        return out

    cfgs = {"旧v7.14(均值/12月/8笔)": ("mean", 12, 8),
            "新v7.15(剔3/9月/3笔)": ("trim3", 9, 3)}
    outs = {k: sim(states_for(*v)) for k, v in cfgs.items()}
    years = sorted({t[3] for t in rich})

    print("研究口径(全部信号)分年对比:")
    print(f"{'年':<6}", end="")
    for k in cfgs:
        print(f"|{k[:14]:<30}", end="")
    print()
    for y in years:
        print(f"{y:<6}", end="")
        for k in cfgs:
            rs = [t[2] for t in outs[k] if t[3] == y]
            if not rs:
                print(f"|  —", end="")
                continue
            print(f"| {len(rs):>3}笔 胜{sum(1 for x in rs if x > 0) / len(rs):>4.0%} "
                  f"均{avg(rs):>+6.2f} 和{sum(rs):>+7.1f}", end="")
        print()
    for k in cfgs:
        rs = [t[2] for t in outs[k]]
        print(f"合计 {k}: {len(rs)}笔 胜{sum(1 for x in rs if x > 0) / len(rs):.0%} "
              f"均{avg(rs):+.2f} 和{sum(rs):+.1f}")

    print("\n执行口径(同票重叠不成交)·物化分年对比:")
    row15 = repository.load_backtest_report("hpr-v7.15") or {}
    for tag, row in (("新v7.15(本地物化)", row15),):
        print(f"[{tag}]")
        for r in row.get("dyn_sim_yearly") or []:
            print(f"  {r['year']}: {r['n']:>3}笔 胜{round((r.get('e3_win') or 0) * 100):>3}% "
                  f"E3均{r.get('e3_pct'):+.2f}")


main()
