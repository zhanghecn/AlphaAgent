# -*- coding: utf-8 -*-
"""切换器判据穷举(2026-10-12 主人「怎么选取的 胜率/收益/笔数/综合 是否每个
组合都试过一遍」): 判据×窗宽×门槛 全交叉 6×5×3=90 配置。
容器内跑: docker exec -i vnpy-alphaagent-api-1 python < 本文件
判据(每组在窗内的命中笔rs上算一个分数):
  mean   每笔平均收益(现状)      win  胜率
  sum    收益总和(笔数加权)      median 中位数
  trim3  剔最高3笔后的均值(防妖) meanwin 均值×胜率(质量×稳定)
门槛=组内n≥门槛才可选(笔数只当资格线不当判据); 指标不过中性值(win=0.5,余0)不选。
"""
import sys
from collections import defaultdict

from alphaagent.server.services.high_relay import backtest


def log(*a):
    print(*a, file=sys.stderr)


def avg(xs):
    return sum(xs) / len(xs) if xs else None


METRICS = {
    "mean": lambda rs: avg(rs),
    "win": lambda rs: sum(1 for x in rs if x > 0) / len(rs),
    "sum": lambda rs: float(sum(rs)),
    "median": lambda rs: float(sorted(rs)[len(rs) // 2]),
    "trim3": lambda rs: avg(sorted(rs)[:-3]) if len(rs) > 3 else avg(rs),
    "meanwin": lambda rs: avg(rs) * sum(1 for x in rs if x > 0) / len(rs),
}
NEUTRAL = {"win": 0.5, "mean": 0.0, "sum": 0.0, "median": 0.0, "trim3": 0.0, "meanwin": 0.0}


def main() -> None:
    log("全量事件回放...")
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

    # 预缓存: 每月×每窗宽 → 两组rs
    wins = {}
    tmi = {m: i for i, m in enumerate(tm)}
    for w in (6, 9, 12, 15, 18):
        for i, m in enumerate(tm):
            ms = set(tm[max(0, i - w):i])
            wk = [t[2] for t in rich if t[0] in ms and t[1] == "weak"]
            st = [t[2] for t in rich if t[0] in ms and t[1] == "strong"]
            wins[(m, w)] = (wk, st)

    def states_for(metric, w, n_min):
        f, neu = METRICS[metric], NEUTRAL[metric]
        out = {}
        for m in tm:
            wk, st = wins[(m, w)]
            wa, sa = f(wk) if wk else None, f(st) if st else None
            if len(wk) >= n_min and len(st) >= n_min and wa is not None and sa is not None:
                out[m] = "weak" if wa > sa else "strong"
            elif len(wk) >= n_min and wa is not None and wa > neu:
                out[m] = "weak"
            elif len(st) >= n_min and sa is not None and sa > neu:
                out[m] = "strong"
            else:
                out[m] = "both"
        return out

    def sim(states_d):
        out = []
        cur = "both"
        for m in tm:
            cur = states_d.get(m, cur)
            for t in by_m[m]:
                if cur == "both" or t[1] == cur:
                    out.append(t)
        return out

    results = []
    for metric in METRICS:
        for w in (6, 9, 12, 15, 18):
            for n_min in (3, 5, 8):
                sd = states_for(metric, w, n_min)
                out = sim(sd)
                rs = [t[2] for t in out]
                yr = defaultdict(float)
                for t in out:
                    yr[t[3]] += t[2]
                worst = min(yr.values()) if yr else 0
                pos_years = sum(1 for v in yr.values() if v > 0)
                switches = 0
                s0 = "both"
                for m in tm:
                    if sd.get(m, s0) != s0:
                        switches += 1
                        s0 = sd.get(m, s0)
                r23 = [t[2] for t in out if t[3] == "2023"]
                results.append({
                    "metric": metric, "w": w, "n_min": n_min,
                    "n": len(rs), "win": sum(1 for x in rs if x > 0) / len(rs) if rs else 0,
                    "mean": avg(rs) or 0, "total": sum(rs),
                    "worst": worst, "pos": pos_years, "sw": switches,
                    "n23": len(r23), "m23": avg(r23) or 0, "t23": sum(r23),
                })

    base = next(r for r in results
                if r["metric"] == "mean" and r["w"] == 12 and r["n_min"] == 8)
    print(f"现状(mean/12月/门槛8): {base['n']}笔 胜{base['win']:.0%} 均{base['mean']:+.2f} "
          f"和{base['total']:+.0f} 最差年{base['worst']:+.0f} 正年{base['pos']}/7 "
          f"切换{base['sw']}次 | 2023: {base['n23']}笔 均{base['m23']:+.2f} 和{base['t23']:+.0f}\n")

    # 主效应: 按指标/窗宽/门槛聚合均值
    print("─" * 8, "主效应(七年每笔均值, 按维度聚合)", "─" * 8)
    for dim, key in (("判据", "metric"), ("窗宽", "w"), ("门槛", "n_min")):
        agg = defaultdict(list)
        for r in results:
            agg[str(r[key])].append(r["mean"])
        line = "  " + f"{dim}: " + "  ".join(
            f"{k}={avg(v):+.2f}" for k, v in sorted(agg.items(), key=lambda kv: -avg(kv[1])))
        print(line + "\n")

    # 全表: 按主人方法论排序=先最差年(一致性)再均值
    results.sort(key=lambda r: (-r["worst"], -r["mean"]))
    print("─" * 8, "Top15(排序: 最差年↓ → 每笔均值↓)  [◆=现状]", "─" * 8)
    print(f"{'判据':<8}{'窗':>3}{'门':>3}{'笔数':>5}{'胜率':>5}{'每笔':>7}{'总和':>8}"
          f"{'最差年':>7}{'正年':>4}{'切换':>4}{'|2023笔/均/和':>20}")
    for r in results[:15]:
        mark = "◆" if (r["metric"] == "mean" and r["w"] == 12 and r["n_min"] == 8) else " "
        print(f"{r['metric']:<8}{r['w']:>3}{r['n_min']:>3}{r['n']:>5}{r['win']:>5.0%}"
              f"{r['mean']:>+7.2f}{r['total']:>+8.0f}{r['worst']:>+7.0f}"
              f"{r['pos']:>3}/7{r['sw']:>4}{mark} | {r['n23']:>2}笔 {r['m23']:+.1f} {r['t23']:+.0f}")
    rank = next(i for i, r in enumerate(results)
                if r["metric"] == "mean" and r["w"] == 12 and r["n_min"] == 8)
    print(f"\n现状在90配置中排第 {rank + 1} 位")
    print("\n─" * 8, "Bottom5(反面教材)", "─" * 8)
    for r in results[-5:]:
        print(f"{r['metric']:<8}窗{r['w']}门{r['n_min']}: {r['n']}笔 均{r['mean']:+.2f} "
              f"最差年{r['worst']:+.0f} 切换{r['sw']}次")


main()
