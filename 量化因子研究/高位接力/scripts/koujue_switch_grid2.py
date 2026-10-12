# -*- coding: utf-8 -*-
"""穷举诊断: Top配置(trim3/9/3)与现状(mean/12/8)的行为差异——切换点/分年/
状态路径diff/2023明细/近年状态。容器跑。"""
import sys
from collections import defaultdict

from alphaagent.server.services.high_relay import backtest


def log(*a):
    print(*a, file=sys.stderr)


def avg(xs):
    return sum(xs) / len(xs) if xs else None


METRICS = {
    "mean": lambda rs: avg(rs),
    "trim3": lambda rs: avg(sorted(rs)[:-3]) if len(rs) > 3 else avg(rs),
}


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
        rich.append({"m": str(r["月"]), "g": g, "p": wk if wk != "—" else pt,
                     "r": round(float(e3), 2), "n": str(r.get("名称") or ""),
                     "y": str(r["月"])[:4]})
    tm = sorted({t["m"] for t in rich})
    by_m = defaultdict(list)
    for t in rich:
        by_m[t["m"]].append(t)

    def states_for(metric, w, n_min):
        f = METRICS[metric]
        out = {}
        for i, m in enumerate(tm):
            ms = set(tm[max(0, i - w):i])
            wk = [t["r"] for t in rich if t["m"] in ms and t["g"] == "weak"]
            st = [t["r"] for t in rich if t["m"] in ms and t["g"] == "strong"]
            wa, sa = f(wk) if wk else None, f(st) if st else None
            if len(wk) >= n_min and len(st) >= n_min and wa is not None and sa is not None:
                out[m] = "weak" if wa > sa else "strong"
            elif len(wk) >= n_min and wa is not None and wa > 0:
                out[m] = "weak"
            elif len(st) >= n_min and sa is not None and sa > 0:
                out[m] = "strong"
            else:
                out[m] = "both"
        return out

    def sim(sd):
        out, cur = [], "both"
        for m in tm:
            cur = sd.get(m, cur)
            for t in by_m[m]:
                if cur == "both" or t["g"] == cur:
                    q = dict(t)
                    q["st"] = cur
                    out.append(q)
        return out

    cfgs = {"现状 mean/12/8": ("mean", 12, 8), "Top1 trim3/9/3": ("trim3", 9, 3),
            "邻居 mean/9/3": ("mean", 9, 3), "邻居 trim3/6/3": ("trim3", 6, 3)}
    sd = {k: states_for(*v) for k, v in cfgs.items()}

    for k in cfgs:
        pts, s0 = [], "both"
        for m in sorted(sd[k]):
            if sd[k][m] != s0:
                pts.append(f"{m}:{s0[:2]}→{sd[k][m][:2]}")
                s0 = sd[k][m]
        print(f"{k:<18} 切换点: {' | '.join(pts)}")

    base, top = sd["现状 mean/12/8"], sd["Top1 trim3/9/3"]
    diff = [m for m in tm if base.get(m) != top.get(m)]
    print(f"\n状态路径diff({len(diff)}个月不同): {diff}")

    print("\n分年对照:")
    outs = {k: sim(s) for k, s in sd.items()}
    years = sorted({t["y"] for t in rich})
    hdr = "年份   " + "".join(f"{k:<20}" for k in cfgs)
    print(hdr)
    for y in years:
        line = f"{y}  "
        for k in cfgs:
            rs = [t["r"] for t in outs[k] if t["y"] == y]
            line += f"{len(rs):>3}笔{sum(rs):>+7.0f}     "
        print(line)

    print("\n2023年 Top1 与现状的出手diff:")
    b23 = {(t["m"], t["n"]): t for t in outs["现状 mean/12/8"] if t["y"] == "2023"}
    t23 = {(t["m"], t["n"]): t for t in outs["Top1 trim3/9/3"] if t["y"] == "2023"}
    for key in sorted(set(b23) | set(t23)):
        b, t = b23.get(key), t23.get(key)
        if b and t:
            print(f"  {key[0]} {key[1]:<8} 两边都打 {b['r']:+.1f}")
        elif t:
            print(f"  {key[0]} {key[1]:<8} 仅Top1 [{t['st']}] {t['p']} {t['r']:+.1f}")
        else:
            print(f"  {key[0]} {key[1]:<8} 仅现状 [{b['st']}] {b['p']} {b['r']:+.1f}")

    print("\n近年状态(2025-10~2026-09)各配置:")
    for k in cfgs:
        tail = {m: sd[k][m] for m in sorted(sd[k]) if m >= "2025-10"}
        print(f"  {k:<18} {tail}")


main()
