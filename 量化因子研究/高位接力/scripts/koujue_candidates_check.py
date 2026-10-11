# -*- coding: utf-8 -*-
"""候选口诀立规检验(koujue_candidates_check): 研究过程挖出的非现役格, 全部过一遍
立规门槛——分年一致性/剔3/近24月/边界扰动/与现役重叠, 输出可直接看票的数字。

候选来源:
  锻造炉(S2.1): 双低开×今开强开×前波=0(13笔77%七年全正)
  重演引擎v2(S2.8): A1第三分支(贴零链低吸捡尸) / B3平行格(阴组缩量承接强开) /
    B2平行格(前波=0捡尸) / K4平行格
立规门槛(hpr方法论+walk-forward六指标):
  ① n≥10 ② 胜率≥60% ③ 剔3>0 ④ 分年一致性(每笔均值最差年>-5, 主人口径)
  ⑤ 近24月仍有肉(均值>0) ⑥ 边界扰动±0.5剔3中位>0(R1语言档内高原)
  ⑦ 训练窗均值≤13(R6天花板) ⑧ 与现役13条重叠J<0.5(≥0.5=收扩窗建议非新诀)
全部门槛只用事前可知列(T-1收盘+9:25竞价), 无未来函数。
"""
import numpy as np
import pandas as pd

from alphaagent.server.services.high_relay.pool import tag_scheme, tag_weak

pd.set_option("display.width", 250)

CSV = "量化因子研究/高位接力/四进五全量明细.csv"
LIVE_POOLS = ("二接三阳", "二接三阴", "三接四阳", "三接四阴")

# 候选格(全部事前可知条件; 今开=9:25竞价可知)
CANDS = [
    ("甲·双低开强攻前波0", "二接三阳",
     lambda d: (d["b1开盘%"] < 0) & (d["b2开盘%"] < 0) & (d["买入开盘%"] >= 6)
     & (d["买入开盘%"] < 9.5) & (d["前波60日最高板"] < 0.5)),
    ("乙·贴零链低吸捡尸", "二接三阳",
     lambda d: (d["b2开盘%"] < 1) & (d["b1开盘%"] < 0) & (d["买入开盘%"] < 0)
     & (d["前波60日最高板"] < 0.5)),
    ("丙·阴组缩量承接强开", "三接四阴",
     lambda d: (d["b2开盘%"] >= 0) & (d["b2开盘%"] < 3)
     & (d["b3换手%"] < d["b2换手%"]) & (d["买入开盘%"] >= 6) & (d["买入开盘%"] < 9.5)
     & (d["b1开盘%"] < 1)),
    ("丁·阴组前波0捡尸带", "二接三阴",
     lambda d: (d["b1开盘%"] < 0) & (d["b2开盘%"] >= 0) & (d["b2开盘%"] < 3)
     & (d["买入开盘%"] >= 0) & (d["买入开盘%"] < 3)
     & (d["前波60日最高板"] < 0.5)),
    # 总表活挖候选(koujue_table mine_candidates 当次产出)
    ("S1·一板强开低吸(总表)", "二接三阳",
     lambda d: (d["b1开盘%"] >= 7) & (d["b1开盘%"] < 99) & (d["买入开盘%"] < 3)
     & (d["b2换手%"] > 20)),
    ("Q1·双温深坑(总表)", "二接三阳",
     lambda d: (d["b1开盘%"] >= 3) & (d["b1开盘%"] < 9.5) & (d["b2开盘%"] >= 3)
     & (d["b2开盘%"] < 9.5) & (d["买入开盘%"] >= 3) & (d["买入开盘%"] < 7)
     & (d["距60日新高%"] < -8)),
    ("Z1·前波12强开(总表)", "三接四阴",
     lambda d: (d["买入开盘%"] >= 7) & (d["买入开盘%"] < 9.5)
     & (d["前波60日最高板"] >= 0.5) & (d["前波60日最高板"] < 2.5)),
]

# 边界扰动轴(每候选的可动边界: 列名→默认边界)
PERTURB = {
    "甲·双低开强攻前波0": [("买入开盘%", 6.0), ("买入开盘%", 9.5), ("b2开盘%", 0.0), ("b1开盘%", 0.0)],
    "乙·贴零链低吸捡尸": [("b2开盘%", 1.0), ("买入开盘%", 0.0), ("b1开盘%", 0.0)],
    "丙·阴组缩量承接强开": [("b2开盘%", 3.0), ("买入开盘%", 6.0), ("买入开盘%", 9.5), ("b1开盘%", 1.0)],
    "丁·阴组前波0捡尸带": [("b2开盘%", 3.0), ("买入开盘%", 3.0), ("买入开盘%", 0.0)],
    "S1·一板强开低吸(总表)": [("b1开盘%", 7.0), ("买入开盘%", 3.0)],
    "Q1·双温深坑(总表)": [("b1开盘%", 3.0), ("b1开盘%", 9.5), ("b2开盘%", 3.0),
                     ("b2开盘%", 9.5), ("买入开盘%", 3.0), ("买入开盘%", 7.0),
                     ("距60日新高%", -8.0)],
    "Z1·前波12强开(总表)": [("买入开盘%", 7.0), ("买入开盘%", 9.5), ("前波60日最高板", 0.5),
                     ("前波60日最高板", 2.5)],
}


def nn(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else v


def tag_row(row):
    g4 = row["四组"]
    s = tag_scheme(g4, nn(row["b1开盘%"]), nn(row["b2开盘%"]), nn(row["b3开盘%"]),
                   auction_pct=nn(row["买入开盘%"]), b2_turn=nn(row["b2换手%"]),
                   b3_turn=nn(row["b3换手%"]), foundation_chg=nn(row["地基涨跌%"]),
                   pre10_pct=nn(row["首10日涨幅%"]), foundation_pose=nn(row["地基姿态"]),
                   anchor_pos=nn(row["锚位%"]), anchor_dist=nn(row["锚距"]))
    w = tag_weak(g4, nn(row["b1开盘%"]), nn(row["b2开盘%"]), nn(row["b3开盘%"]),
                 auction_pct=nn(row["买入开盘%"]), b1_turn=nn(row["b1换手%"]),
                 b2_turn=nn(row["b2换手%"]), b3_turn=nn(row["b3换手%"]),
                 foundation_chg=nn(row["地基涨跌%"]), prev_wave60=nn(row["前波60日最高板"]),
                 dist_h60=nn(row["距60日新高%"]))
    return (str(s["no"]) if s else None, str(w["no"]) if w else None)


def st(v):
    n = len(v)
    if n == 0:
        return "0笔"
    t3 = v.drop(v.nlargest(3).index).mean() if n > 3 else v.mean()
    return f"{n}笔 均{v.mean():+.1f} 胜{(v > 0).mean():.0%} 剔3{t3:+.1f}"


def main() -> None:
    E = pd.read_csv(CSV, dtype={"代码": str})
    E = E[E["E3%"].notna()]
    E = E[E["四组"].isin(LIVE_POOLS)].copy()
    E["月"] = E["买入日"].astype(str).str[:7]
    tags = E.apply(tag_row, axis=1, result_type="expand")
    E["s_no"], E["w_no"] = tags[0], tags[1]
    live = (E["s_no"].notna() | E["w_no"].notna())
    print(f"底数 {len(E)}笔 ({E['月'].min()}~{E['月'].max()}), 现役命中{int(live.sum())}笔\n")
    rows = []
    for name, pool, fn in CANDS:
        d = E[E["四组"] == pool]
        m = fn(d)
        sub = d[m]
        print(f"{'=' * 18} {name} ({pool}) {'=' * 18}")
        print(f"  全时段: {st(sub['E3%'])}")
        yr = sub.groupby("年")["E3%"].agg(["count", "mean", "sum"])
        worst = yr["mean"].min() if len(yr) else float("nan")
        print("  分年: " + "  ".join(f"{int(i)}:{int(r['count'])}笔{r['mean']:+.1f}"
                                     for i, r in yr.iterrows()))
        m24 = sub["月"] >= sorted(E["月"].unique())[-24]
        s24 = sub[m24]["E3%"]
        print(f"  近24月: {st(s24) if len(s24) else '无票'} | 最差分年{worst:+.1f}")
        # 边界扰动±0.5(各边界逐一, 剔3中位): 整列平移=等价窗反向移动
        t3s = []
        for col, bnd in PERTURB[name]:
            for dd in (-0.5, 0.5):
                d2 = d.copy()
                d2[col] = d[col] + dd
                s2 = fn(d2)
                v2 = d2[s2]["E3%"]
                if len(v2):
                    t3s.append(v2.drop(v2.nlargest(3).index).mean() if len(v2) > 3
                               else v2.mean())
        t3med = float(np.median(t3s)) if t3s else float("nan")
        print(f"  边界扰动({len(t3s)}次): 剔3中位{t3med:+.1f}")
        inter = int((m & live[m.index]).sum()) if len(sub) else 0
        union = len(set(sub.index) | set(E[live].index) & set(d.index))
        jac = inter / len(sub) if len(sub) else 0.0   # 简化=人工命中占候选比
        hit_nos = pd.concat([sub.loc[m & live[m.index], "s_no"],
                             sub.loc[m & live[m.index], "w_no"]]).value_counts()
        print(f"  与现役重叠: {inter}/{len(sub)}笔 " +
              (" ".join(f"{k}:{v}" for k, v in hit_nos.items()) or "零重叠"))
        gates = [len(sub) >= 10, (sub["E3%"] > 0).mean() >= 0.6,
                 True, worst > -5, len(s24) > 0 and s24.mean() > 0, t3med > 0,
                 sub["E3%"].mean() <= 13, inter / max(len(sub), 1) < 0.5]
        labels = ["n≥10", "胜≥60%", "剔3>0", "最差年>-5", "近24月>0", "扰动中位>0",
                  "均值≤13(R6)", "重叠<50%"]
        v = sub["E3%"]
        t3 = v.drop(v.nlargest(3).index).mean() if len(v) > 3 else v.mean()
        gates[2] = t3 > 0
        verdict = "".join("✓" if g else "✗" for g in gates)
        print(f"  立规八门: {verdict}")
        print("           n≥10/胜60/剔3/最差年/近24月/扰动/R6/重叠 "
              + " ".join(f"[{l}{'✓' if g else '✗'}]" for l, g in zip(labels, gates)))
        rows.append((name, len(sub), f"{(v > 0).mean():.0%}", f"{v.mean():+.1f}",
                     f"{t3:+.1f}", f"{worst:+.1f}", verdict))
    print(f"\n{'=' * 18} 候选总表 {'=' * 18}")
    for r in rows:
        print(f"  {r[0]}: {r[1]}笔 胜{r[2]} 均{r[3]} 剔3{r[4]} 最差年{r[5]} [{r[6]}]")


main()
