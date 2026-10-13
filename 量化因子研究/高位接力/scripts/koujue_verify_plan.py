# -*- coding: utf-8 -*-
"""核查外部方案(2026-10-13): K5常驻+连续强开+势位打分卡+组合242笔。
容器内跑: docker exec -i vnpy-alphaagent-api-1 python < 本文件
对照口径: v7.15切换器(trim3/9月/3笔), 研究口径全部信号, E3。
"""
import sys
from collections import defaultdict

from alphaagent.server.services.high_relay import backtest


def log(*a):
    print(*a, file=sys.stderr)


def stats(rs):
    if not rs:
        return "  —"
    n = len(rs)
    win = sum(1 for x in rs if x > 0) / n
    avg = sum(rs) / n
    return f"{n:>3}笔 胜{win:>4.0%} 均{avg:>+7.2f} 和{sum(rs):>+8.1f}"


def trim3(rs):
    core = sorted(rs)[:-3] if len(rs) > 3 else rs
    return sum(core) / len(core) if core else None


def yearly(rows, key=lambda t: t["年"]):
    by = defaultdict(list)
    for t in rows:
        by[key(t)].append(t["e3"])
    return by


def show_yearly(title, rows, key=lambda t: t["年"]):
    print(f"\n[{title}]  合计: {stats([t['e3'] for t in rows])}")
    by = yearly(rows, key)
    for y in sorted(by):
        print(f"  {y}: {stats(by[y])}")


def main() -> None:
    log("build_events...")
    E, _bars = backtest.build_events()
    done = E[~E["未完"]].copy()
    log("四组分布:", done["四组"].value_counts().to_dict())
    log("N分布:", done["N"].value_counts().to_dict())
    log("昨日涨停家数非空:", done["昨日涨停家数"].notna().sum(), "/", len(done))

    # ---- 通用: 研究口径命中票(弱口诀或方案点任一) ----
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
        rich.append({
            "月": str(r["月"]), "年": str(r["月"])[:4], "组": g, "e3": round(float(e3), 2),
            "wk": wk, "pt": pt, "代码": str(r["代码"]), "名称": str(r["名称"]),
        })
    tm = sorted({t["月"] for t in rich})
    by_m = defaultdict(list)
    for t in rich:
        by_m[t["月"]].append(t)

    # ---- v7.15 状态机(与 contracts.dyn_month_states 同构) ----
    def states_for(metric="trim3", w=9, n_min=3):
        def m(rs):
            if metric == "trim3":
                core = sorted(rs)[:-3] if len(rs) > 3 else rs
                return sum(core) / len(core)
            return sum(rs) / len(rs)

        out, cur = {}, "both"
        for i, mo in enumerate(tm):
            ms = set(tm[max(0, i - w):i])
            wk = [t["e3"] for t in rich if t["月"] in ms and t["组"] == "weak"]
            st = [t["e3"] for t in rich if t["月"] in ms and t["组"] == "strong"]
            wa, sa = m(wk) if wk else None, m(st) if st else None
            if len(wk) >= n_min and len(st) >= n_min and wa is not None and sa is not None:
                cur = "weak" if wa > sa else "strong"
            elif len(wk) >= n_min and wa is not None and wa > 0:
                cur = "weak"
            elif len(st) >= n_min and sa is not None and sa > 0:
                cur = "strong"
            else:
                cur = "both"
            out[mo] = cur
        return out

    sd = states_for()
    mos = list(sd.keys())
    log("切换史:", [(mos[i], sd[mos[i]]) for i in range(1, len(mos)) if sd[mos[i]] != sd[mos[i - 1]]])

    def sim(k5_always=False):
        out, cur = [], "both"
        for mo in tm:
            cur = sd.get(mo, cur)
            for t in by_m[mo]:
                if cur == "both" or t["组"] == cur:
                    out.append(t)
                elif k5_always and t["组"] == "weak" and t["wk"] == "K5":
                    out.append(t)  # K5常驻: 强市月也买K5
        return out

    base = sim()
    show_yearly("A·基线 v7.15 复现(期望177笔/76%/+11.55)", base)

    # ---- B·K5 全时段分年(研究口径全命中) ----
    k5_all = [t for t in rich if t["wk"] == "K5"]
    show_yearly("B·K5 全时段全命中分年(检验7/7年为正)", k5_all)

    # ---- C·K5常驻组合 ----
    k5v = sim(k5_always=True)
    added = {(t["月"], t["代码"]) for t in k5v} - {(t["月"], t["代码"]) for t in base}
    adds = [t for t in k5v if (t["月"], t["代码"]) in added]
    print(f"\n[C·K5常驻] 增量票 {len(adds)} 笔:")
    for t in sorted(adds, key=lambda x: x["月"]):
        print(f"  {t['月']} {t['名称']:　<6} {t['e3']:+7.2f} (当月组={sd[t['月']]})")
    show_yearly("C·K5常驻组合分年", k5v)

    # ---- D·连续强开裸格: 三接四 × b2开≥7 × b3开≥7 × 三换5~20 ----
    lk = []
    for _, r in done.iterrows():
        e3 = r.get("E3%")
        if e3 is None or e3 != e3:
            continue
        grp = str(r.get("四组") or "")
        b2, b3, t3 = r.get("b2开盘%"), r.get("b3开盘%"), r.get("b3换手%")
        if None in (b2, b3, t3) or b2 != b2 or b3 != b3 or t3 != t3:
            continue
        if "三接四" not in grp:
            continue
        if b2 >= 7 and b3 >= 7 and 5 <= t3 <= 20:
            lk.append({
                "月": str(r["月"]), "年": str(r["月"])[:4], "e3": round(float(e3), 2),
                "代码": str(r["代码"]), "名称": str(r["名称"]),
                "b1开": r.get("b1开盘%"), "阴阳": str(r.get("阴阳") or "?"),
                "zt": r.get("昨日涨停家数"),
                "wk": str(r.get("弱口诀") or "—"), "pt": str(r.get("方案点") or "—"),
            })
    show_yearly("D·连续强开裸格(三接四×b2开≥7×b3开≥7×三换5~20, 不含势位)", lk,
                key=lambda t: t["年"])
    ov = [t for t in lk if t["wk"] != "—" or t["pt"] != "—"]
    pure = [t for t in lk if t["wk"] == "—" and t["pt"] == "—"]
    print(f"  与现役口诀重叠: {len(ov)}/{len(lk)} 笔 "
          f"(重叠部分均{sum(t['e3'] for t in ov) / len(ov) if ov else 0:+.2f}, "
          f"纯新增 {len(pure)} 笔 均{sum(t['e3'] for t in pure) / len(pure) if pure else 0:+.2f})")
    print(f"  剔3均值: {trim3([t['e3'] for t in lk])}")

    # ---- E·势位三腿近似(首板强开b1开≥6 + 阴地基 + 昨涨停<100) ----
    def leg_n(t):
        return sum([t["b1开"] is not None and t["b1开"] == t["b1开"] and t["b1开"] >= 6,
                    t["阴阳"] == "阴",
                    t["zt"] is not None and t["zt"] == t["zt"] and t["zt"] < 100])
    for need in (3, 2):
        sub = [t for t in lk if leg_n(t) >= need]
        show_yearly(f"E·连续强开×势位可算{need}腿(首板强开+阴地基+昨涨停<100, 缺高度稀缺/流通)",
                    sub, key=lambda t: t["年"])
    zt_na = sum(1 for t in lk if t["zt"] is None or t["zt"] != t["zt"])
    print(f"  (势位腿数据: 昨涨停家数缺 {zt_na}/{len(lk)} 笔; 高度稀缺与历史流通市值 E表无)")

    # ---- F·组合复现: 基线 + K5常驻 + 连续强开纯新增 ----
    seen = {(t["月"], t["代码"]) for t in k5v}
    combo = list(k5v)
    for t in lk:
        if (t["月"], t["代码"]) not in seen:
            seen.add((t["月"], t["代码"]))
            combo.append({"月": t["月"], "年": t["年"], "e3": t["e3"], "代码": t["代码"], "名称": t["名称"]})
    show_yearly("F·组合复现(基线+K5常驻+连续强开全量, 对照242笔/73%/+9.8/+2360)", combo)
    # 只加连续强开纯新增(未被现役命中的)的版本
    seen2 = {(t["月"], t["代码"]) for t in k5v}
    combo2 = list(k5v)
    for t in lk:
        if t["wk"] == "—" and t["pt"] == "—" and (t["月"], t["代码"]) not in seen2:
            seen2.add((t["月"], t["代码"]))
            combo2.append({"月": t["月"], "年": t["年"], "e3": t["e3"], "代码": t["代码"], "名称": t["名称"]})
    show_yearly("F2·组合(连续强开只加纯新增)", combo2)

    # ---- G·数据完整性附注: 昨日涨停家数分年非空 ----
    dd = done[done["E3%"].notna()] if "E3%" in done else done
    by_y = defaultdict(lambda: [0, 0])
    for _, r in dd.iterrows():
        y = str(r["月"])[:4]
        by_y[y][1] += 1
        z = r.get("昨日涨停家数")
        if z is not None and z == z:
            by_y[y][0] += 1
    print("\n[G·昨涨停家数可用性] " + "  ".join(f"{y}:{v[0]}/{v[1]}" for y, v in sorted(by_y.items())))


main()
