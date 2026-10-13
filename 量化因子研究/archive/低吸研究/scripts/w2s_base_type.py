# -*- coding: utf-8 -*-
"""地基形态识别 + 分类统计: 断板期(上波末板→昨日)价格路径 → U/平/高/趴/阴跌 等地基类型.

识别函数 classify_base(): 全部 D-1 可观测(昨收口径), 买点日直接调用.
七类互斥完备(按优先级):
  HIGH 新高贴顶  昨收距上波顶<4%          (含深V回来的, 子标记=是否破过顶)
  FLAT 横盘平台  断板期收盘振幅<=10% 且 昨收>-12%
  DN   阴跌到点  最低点就在最近(pos_low>0.6) 且 没反弹(reb<3%)  → 还在跌, 今日涨停=末端反转
  LB   L趴底     蹲深(<=-12%) 且 没反弹(reb<3%)                → 跌下去横住, 死票嫌疑
  U    U型蹲     蹲深(<=-12%) 且 弹回>=6% 且 低点在前中段(pos_low<=0.6)
  V    V末反     蹲深(<=-12%) 且 弹回>=6% 且 低点在后段         → 刚从坑里爬出来
  MID  中位浅调  其余(回撤-4~-12%有起伏 / 半程反弹)
"""
import os
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w

pd.set_option("display.width", 400)

# 地基标签(显示顺序=报表顺序)
BASE_ORDER = ["HIGH", "FLAT", "U", "V", "MID", "LB", "DN"]
BASE_NAME = {"HIGH": "新高贴顶", "FLAT": "横盘平台", "U": "U型蹲", "V": "V末反",
             "MID": "中位浅调", "LB": "L趴底", "DN": "阴跌到点"}


def classify_base(mid_c, top_px, prev_close):
    """断板期收盘序列 → 地基类型 + 特征. 返回 dict(base, pull, low_dd, reb, pos_low, amp, brk).

    mid_c: 断板期每日收盘(np.array, 含昨日, 不含上波末板与D0)
    top_px: 上波(>=2板段)最高价; prev_close: 昨收
    """
    n = len(mid_c)
    if n == 0 or top_px != top_px or prev_close != prev_close:
        return None
    pull = prev_close / top_px - 1                    # 现位置(昨收距顶)
    low_i = int(np.argmin(mid_c))                     # 最低收盘索引
    low_dd = mid_c[low_i] / top_px - 1                # 最深蹲(收盘口径, 插针不算)
    reb = prev_close / mid_c[low_i] - 1               # 洗后反弹高度
    pos_low = (low_i / (n - 1)) if n > 1 else 0.0     # 低点位置(0=断板首日, 1=昨日)
    amp = mid_c.max() / mid_c[low_i] - 1              # 期间收盘总振幅
    brk = mid_c.max() > top_px                        # 期间破过顶
    if pull > -0.04:
        base = "HIGH"
    elif amp <= 0.10 and pull > -0.12:
        base = "FLAT"
    elif reb < 0.03 and pos_low > 0.6:
        base = "DN"
    elif low_dd <= -0.12 and reb < 0.03:
        base = "LB"
    elif low_dd <= -0.12 and reb >= 0.06:
        base = "U" if pos_low <= 0.6 else "V"
    else:
        base = "MID"
    return {"base": base, "pull": pull, "low_dd": low_dd, "reb": reb,
            "pos_low": pos_low, "amp": amp, "brk": bool(brk)}


def build_base(bars, segs, conds=("c_by",)):
    """对满足 conds 之一的触发行计算地基特征, 返回增强后的触发子集(行级循环, 量小)."""
    big = segs[segs["height"] >= 2].sort_values(["sid", "last_pos"])
    big_by = {sid: grp[["last_pos", "high_price"]].to_numpy()
              for sid, grp in big.groupby("sid", sort=False)}
    seg_h_by = {(int(r.sid), int(r.last_pos)): int(r.height) for r in big.itertuples()}
    cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}

    cond = np.zeros(len(bars), dtype=bool)
    for c in conds:
        cond |= bars[c].to_numpy()
    cond_ok = cond & bars["touch"] & ~bars["d0_open_lim"] & bars["n1_close"].notna() & bars["n1_open"].notna()
    tg = bars[cond_ok].copy()

    rows, drop = [], 0
    for r in tg.itertuples():
        sid = int(r.sid)
        arr = big_by.get(sid)
        i = p2i[sid][int(r.pos)]
        if arr is None or arr[:, 0].searchsorted(int(r.pos), side="left") == 0:
            drop += 1
            continue
        li = arr[:, 0].searchsorted(int(r.pos), side="left")
        lp, ph = int(arr[li - 1, 0]), float(arr[li - 1, 1])
        mid_c = cl_by[sid][lp + 1: i]                 # 断板期收盘(上波末板次日..昨日)
        info = classify_base(mid_c, ph, r.prev_close)
        if info is None:
            drop += 1
            continue
        rows.append({"sid": sid, "pos": int(r.pos), "gap": int(r.pos) - lp,
                     "seg_h": seg_h_by.get((sid, lp), np.nan), **info})
    feat = pd.DataFrame(rows)
    tg = tg.merge(feat, on=["sid", "pos"], how="inner")
    return tg, drop


def add_outcome(tg, bars):
    """结果口径列: r_d1o/r_d1c(相对涨停价买入) / res 四分类 / 板留断走."""
    idx = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}
    closes_all = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    pcs = {sid: grp["prev_close"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}

    def banhold(sid, pos0):
        bd_p, bd_c = idx.get(sid), closes_all.get(sid)
        if bd_p is None:
            return np.nan
        for d in range(1, 21):
            j = bd_p.get(pos0 + d)
            if j is None:
                k = bd_p.get(pos0 + d - 1)
                return bd_c[k] if k is not None else np.nan
            lim = round(pcs[sid][j] * 1.10 + 1e-9, 2)
            if abs(bd_c[j] - lim) > 1e-6:
                return bd_c[j]
        return bd_c[bd_p.get(pos0 + 20, len(bd_c) - 1)]

    tg = tg.copy()
    tg["r_d1o"] = tg["n1_open"] / tg["lim_px"] - 1
    tg["r_d1c"] = tg["n1_close"] / tg["lim_px"] - 1
    tg["res"] = np.where(~tg["is_lim"], "炸板",
                         np.where(tg["r_d1c"] < 0, np.where(tg["n1_lim"], "连板", "封D1负"),
                                  np.where(tg["n1_lim"], "连板", "封D1正")))
    tg["r_bh"] = [banhold(int(s), int(p)) / lp - 1 for s, p, lp
                  in zip(tg["sid"], tg["pos"], tg["lim_px"])]
    return tg


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)
    mkt = bars.groupby("trade_date")["is_lim"].sum().rename("mkt_lim").reset_index()
    mkt["mkt_prev"] = mkt["mkt_lim"].shift(1)
    bars = bars.merge(mkt, on="trade_date", how="left")
    wave_keys = set(zip(waves["sid"], waves["first_pos"]))

    tg, drop = build_base(bars, segs, conds=("c_by",))
    tg = add_outcome(tg, bars)
    tg["ym"] = tg["trade_date"].dt.strftime("%Y-%m")
    tg["date"] = tg["trade_date"].dt.strftime("%Y-%m-%d")
    tg["is_wv"] = [(s, p) in wave_keys for s, p in zip(tg["sid"], tg["pos"])]
    tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
    print(f"补涨阴全量触发 {len(tg)} 笔(地基可算), 丢弃(无上波>=2板段) {drop}\n")

    # ── ① 地基分布 × 好差/收益(全量 + 分年) ──
    print("=" * 100)
    print("== ① 地基类型 × 结局(全量) ==")
    t = tg.groupby("base").agg(
        n=("bad", "size"), 差票率=("bad", "mean"), 封板率=("is_lim", "mean"),
        D1开=("r_d1o", "mean"), D1收=("r_d1c", "mean"), 板留=("r_bh", "mean"))
    sealed = tg[tg["is_lim"]]
    t["连板率"] = sealed.groupby("base")["n1_lim"].mean()
    t["V3波%"] = tg.groupby("base")["is_wv"].mean()
    for c in ("差票率", "封板率", "连板率", "V3波%"):
        t[c] = (t[c] * 100).round(0)
    for c in ("D1开", "D1收", "板留"):
        t[c] = (t[c] * 100).round(2)
    t["占比%"] = (t["n"] / t["n"].sum() * 100).round(0)
    print(t.reindex(BASE_ORDER).dropna(how="all").to_string())

    for y in (2023, 2024, 2025, 2026):
        sub = tg[tg["trade_date"].dt.year == y]
        if not len(sub):
            continue
        t = sub.groupby("base").agg(n=("bad", "size"), 差票率=("bad", "mean"),
                                    D1收=("r_d1c", "mean"), 板留=("r_bh", "mean"))
        t["差票率"] = (t["差票率"] * 100).round(0)
        for c in ("D1收", "板留"):
            t[c] = (t[c] * 100).round(2)
        print(f"\n-- {y} --")
        print(t.reindex(BASE_ORDER).dropna(how="all").to_string())

    # ── ② 地基 × 断板天数 交叉 ──
    print("\n" + "=" * 100)
    print("== ② 地基 × 断板天数: 差票率(上) / 板留%(下) ==")
    gb = pd.cut(tg["gap"], [1, 6, 11, 16, 99], labels=["断2-5", "断6-10", "断11-15", "断16+"])
    t1 = tg.pivot_table(index="base", columns=gb, values="bad", aggfunc="mean", observed=True) * 100
    t2 = tg.pivot_table(index="base", columns=gb, values="r_bh", aggfunc="mean", observed=True) * 100
    print(t1.reindex(BASE_ORDER).round(0).to_string())
    print()
    print(t2.reindex(BASE_ORDER).round(1).to_string())

    # ── ③ 月度 × 地基 差票率矩阵 ──
    print("\n" + "=" * 100)
    print("== ③ 月度 × 地基: n/差票率 (全量) ==")
    tg2 = tg
    for base in BASE_ORDER:
        sub = tg2[tg2["base"] == base]
        if not len(sub):
            continue
        line = f"{base:<5s}{BASE_NAME[base]:<6s}: " + " ".join(
            f"{ym.split('-')[1]}月 n{len(s)}/{s['bad'].mean() * 100:.0f}%"
            for ym, s in sub.groupby("ym"))
        print(line)

    # ── ④ U型内部深挖: 深度/反弹/破顶 ──
    print("\n" + "=" * 100)
    print("== ④ 关键地基内部维度 ==")
    for base in ("HIGH", "U", "FLAT"):
        sub = tg[tg["base"] == base]
        if not len(sub):
            continue
        print(f"\n-- {base} {BASE_NAME[base]} (n={len(sub)}) --")
        if base == "HIGH":
            b = sub.groupby("brk")["bad"].agg(["size", "mean"])
            b.columns = ["n", "差票率"]
            b["差票率"] = (b["差票率"] * 100).round(0)
            b.index = ["未破顶(贴顶)" if not x else "破过顶(新高回踩)" for x in b.index]
            print(b.to_string())
        if base == "U":
            for dim, bins, labs in [
                ("low_dd", [-0.99, -0.25, -0.18, -0.12], ["蹲12~18%", "蹲18~25%", "蹲>25%"]),
                ("reb", [0.05, 0.10, 0.16, 99], ["弹6~10", "弹10~16", "弹>16"]),
                ("seg_h", [1.5, 2.5, 3.5, 99], ["上波2板", "上波3板", "上波4板+"]),
            ]:
                b = pd.cut(sub[dim], bins, labels=labs)
                t = sub.groupby(b, observed=True)["bad"].agg(["size", "mean"])
                t["板留"] = sub.groupby(b, observed=True)["r_bh"].mean() * 100
                t.columns = ["n", "差票率", "板留%"]
                t["差票率"] = (t["差票率"] * 100).round(0)
                t["板留%"] = t["板留%"].round(2)
                print(f"{dim}:")
                print(t.to_string())
        if base == "FLAT":
            b = pd.cut(sub["gap"], [1, 6, 11, 16, 99], labels=["断2-5", "断6-10", "断11-15", "断16+"])
            t = sub.groupby(b, observed=True).agg(n=("bad", "size"), 差票率=("bad", "mean"),
                                                  板留=("r_bh", "mean"))
            t["差票率"] = (t["差票率"] * 100).round(0)
            t["板留"] = (t["板留"] * 100).round(2)
            print("横盘时长:")
            print(t.to_string())
    for base in ("DN",):
        sub = tg[tg["base"] == base]
        if not len(sub):
            continue
        print(f"\n-- {base} {BASE_NAME[base]} 深挖 (n={len(sub)}) --")
        for dim, bins, labs in [
            ("low_dd", [-0.99, -0.20, -0.12, -0.001], ["深阴跌>20%", "中阴跌12~20%", "浅阴跌<12%"]),
            ("gap", [1, 6, 11, 16, 99], ["断2-5", "断6-10", "断11-15", "断16+"]),
        ]:
            b = pd.cut(sub[dim], bins, labels=labs)
            t = sub.groupby(b, observed=True).agg(n=("bad", "size"), 差票率=("bad", "mean"),
                                                  D1收=("r_d1c", "mean"), 板留=("r_bh", "mean"))
            t["差票率"] = (t["差票率"] * 100).round(0)
            t["D1收"] = (t["D1收"] * 100).round(2)
            t["板留"] = (t["板留"] * 100).round(2)
            print(f"{dim}:")
            print(t.to_string())

    # ── ⑤ 输出: 全量csv + 月度md ──
    out_root = "/app/w2s_v3_out/地基研究"
    os.makedirs(out_root, exist_ok=True)
    cols = ["vt_symbol", "name", "date", "ym", "res", "r_d1o", "r_d1c", "r_bh", "base",
            "pull", "low_dd", "reb", "pos_low", "amp", "brk", "gap", "seg_h", "p_chg",
            "p_ush", "mkt_prev", "is_wv", "is_lim", "n1_lim"]
    exp = tg[cols].copy()
    for c in ("r_d1o", "r_d1c", "r_bh", "pull", "low_dd", "reb", "amp", "p_chg", "p_ush"):
        exp[c] = (exp[c] * 100).round(2)
    exp = exp.rename(columns={"r_d1o": "D1开%", "r_d1c": "D1收%", "r_bh": "板留%",
                              "pull": "回撤%", "low_dd": "蹲深%", "reb": "弹回%",
                              "pos_low": "低点位置", "amp": "振幅%", "p_chg": "昨幅%",
                              "p_ush": "昨上影%", "mkt_prev": "昨涨停家", "seg_h": "上波高",
                              "gap": "断板", "base": "地基", "brk": "破顶"})
    exp["地基"] = exp["地基"].map(lambda x: f"{x}·{BASE_NAME[x]}")
    exp.to_csv(os.path.join(out_root, "补涨阴地基全量.csv"), index=False, encoding="utf-8-sig")

    gdir = os.path.join(out_root, "补涨阴")
    os.makedirs(gdir, exist_ok=True)
    for ym, sub in tg.groupby("ym"):
        bad, good = sub[sub["bad"]], sub[~sub["bad"]]
        bs = sub.groupby("base").agg(n=("bad", "size"), 差=("bad", "sum"))
        bs["好"] = bs["n"] - bs["差"]
        head = " | ".join(
            f"{b}·{BASE_NAME[b]} {int(r['n'])}笔(差{int(r['差'])})" for b, r in bs.iterrows())
        lines = [
            f"# 补涨阴 · {ym} · 地基好差票", "",
            f"触发 {len(sub)} 笔 | 差票 {len(bad)}（炸板 {int((sub['res'] == '炸板').sum())} + "
            f"封D1负 {int((sub['res'] == '封D1负').sum())}） | 好票 {len(good)}（连板 "
            f"{int((sub['res'] == '连板').sum())}） | 差票率 {len(bad) / len(sub) * 100:.0f}%", "",
            f"地基分布: {head}", "",
            "地基口径: HIGH新高贴顶(昨收距顶<4%) FLAT横盘(振幅<=10%) U型蹲(蹲>=12%弹>=6%低点前段)",
            "V末反(蹲>=12%弹>=6%低点后段) MID中位浅调 LB趴底(蹲>=12%无弹) DN阴跌(低点在最近无弹)。",
            "回撤%=昨收距上波顶; 蹲深%=期间最低收盘距顶; 弹回%=昨收距期间最低; 低点位置=最低收盘在断板期的相对位置(0初1末)。",
            "",
            "## 差票",
            "",
            "| 代码 | 名称 | D0 | 地基 | 结果 | D1开% | D1收% | 板留% | 回撤% | 蹲深% | 弹回% | 低点位置 | 振幅% | 断板 | 上波高 | 昨幅% | 昨涨停家 | V3 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for _, r in bad.sort_values("r_d1c").iterrows():
            lines.append(
                f"| {r['vt_symbol']} | {r['name']} | {r['date']} | {r['base']}·{BASE_NAME[r['base']]} "
                f"| {r['res']} | {r['r_d1o'] * 100:+.1f} | {r['r_d1c'] * 100:+.1f} | {r['r_bh'] * 100:+.1f} "
                f"| {r['pull'] * 100:+.1f} | {r['low_dd'] * 100:+.1f} | {r['reb'] * 100:+.1f} "
                f"| {r['pos_low']:.2f} | {r['amp'] * 100:.0f} | {r['gap']:.0f} | {r['seg_h']:.0f} "
                f"| {r['p_chg'] * 100:+.1f} | {r['mkt_prev']:.0f} | {'✓' if r['is_wv'] else ''} |")
        lines += ["", "## 好票", "",
                  "| 代码 | 名称 | D0 | 地基 | 结果 | D1开% | D1收% | 板留% | 回撤% | 蹲深% | 弹回% | 低点位置 | 振幅% | 断板 | 上波高 | 昨幅% | 昨涨停家 | V3 |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for _, r in good.sort_values("r_d1c", ascending=False).iterrows():
            lines.append(
                f"| {r['vt_symbol']} | {r['name']} | {r['date']} | {r['base']}·{BASE_NAME[r['base']]} "
                f"| {r['res']} | {r['r_d1o'] * 100:+.1f} | {r['r_d1c'] * 100:+.1f} | {r['r_bh'] * 100:+.1f} "
                f"| {r['pull'] * 100:+.1f} | {r['low_dd'] * 100:+.1f} | {r['reb'] * 100:+.1f} "
                f"| {r['pos_low']:.2f} | {r['amp'] * 100:.0f} | {r['gap']:.0f} | {r['seg_h']:.0f} "
                f"| {r['p_chg'] * 100:+.1f} | {r['mkt_prev']:.0f} | {'✓' if r['is_wv'] else ''} |")
        with open(os.path.join(gdir, f"{ym}.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    print(f"\n已输出: {out_root}/补涨阴/YYYY-MM.md + 补涨阴地基全量.csv ({len(exp)} 笔)")


if __name__ == "__main__":
    main()
