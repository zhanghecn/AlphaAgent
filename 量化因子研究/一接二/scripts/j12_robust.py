# -*- coding: utf-8 -*-
"""一接二 · 第6步稳健性五道检验: 零假设/置换/bootstrap/去尾部/留一年 + 边界晃动终验。

检验对象(第5步联调定稿):
  G1 主格  = 阴地基 × 今开7.5~9.5           (250笔 57% +4.74 四年全正)
  G2 收紧  = G1 × 首板换手<8                (换手心法: 首板锁住)
  G3 低位  = G1 × 低位/跌透                 (坑深腿)
对照: 阳×今开7.5~9.5 (预期不过)

五道(对齐 hpr 汇总/稳健性检验.md):
  1 搜索级零假设: 同容量随机抽票 vs G1 均值分位(池=主窗全池)
  2 月度块置换: 打乱月份标签×1000, G1 均值分位
  3 bootstrap: G1 笔内重采样95%CI
  4 去最好3笔: 均值/分年
  5 留一年: 每年剔除一年后剩余年是否全正(分年一致性已含, 此处看均值)
"""
import numpy as np
import pandas as pd

OUT = "/tmp/research/j12_out"
rng = np.random.default_rng(42)


def load():
    E = pd.read_csv(f"{OUT}/全量明细.csv", parse_dates=["买入日"])
    E["年"] = E["年"].astype(str)
    d = E[(E["段"] == "主窗") & (~E["未完"])].copy()
    return d


def years_table(sub):
    yr = sub.groupby("年")["E3%"].agg(["count", "mean"])
    return " / ".join(f"{y[:4]}:{int(r['count'])}笔{r['mean']:+.2f}" for y, r in yr.iterrows())


def allpos(sub):
    yr = sub.groupby("年")["E3%"].agg(["count", "mean"])
    return all(r["mean"] > 0 for _, r in yr.iterrows()) and len(yr) >= 3


def head(sub):
    return (f"{len(sub)}笔 胜{(sub['E3%'] > 0).mean() * 100:.0f}% 均{sub['E3%'].mean():+.2f} "
            f"中位{sub['E3%'].median():+.2f} {'✅全正' if allpos(sub) else '❌'}")


def main():
    d = load()
    yin = d["地基阴阳"] == "阴"
    G1 = d[yin & d["买入开盘%"].between(7.5, 9.5, inclusive="left")]
    G2 = G1[G1["首板换手%"] < 8]
    G3 = G1[G1["位置五档"].isin(["低位", "跌透"])]
    Gc = d[(d["地基阴阳"] == "阳") & d["买入开盘%"].between(7.5, 9.5, inclusive="left")]
    lines = ["# 一接二 · 第6步稳健性五道检验", ""]

    for name, G in [("G1 阴×今开7.5~9.5", G1), ("G2 G1×换手<8", G2),
                    ("G3 G1×低位/跌透", G3), ("对照 阳×今开7.5~9.5", Gc)]:
        lines.append(f"## {name}: {head(G)} ｜ {years_table(G)}")

        # 1 搜索级零假设: 同容量随机抽样(池=主窗全池8176)
        pool = d["E3%"].to_numpy()
        n = len(G)
        if n >= 15:
            draws = [rng.choice(pool, size=n, replace=False).mean() for _ in range(2000)]
            pct = (np.array(draws) < G["E3%"].mean()).mean() * 100
            lines.append(f"- ①零假设: 随机同容量均值分位 P{pct:.1f}%"
                         f"({'通过' if pct >= 99 else '存疑' if pct >= 95 else '不过'})")

        # 2 月度块置换: 打乱「月→组员归属」保留月度簇结构
        months = G["月"].unique()
        pool_m = d["月"].isin(months)
        base_pool = d[pool_m]
        vals = G["E3%"].to_numpy()
        cnt = 0
        for _ in range(1000):
            samp = base_pool.sample(n, random_state=None)
            if samp["E3%"].mean() >= vals.mean():
                cnt += 1
        lines.append(f"- ②月块置换: P(随机≥G)={cnt / 10:.1f}%({'通过' if cnt / 10 <= 5 else '存疑' if cnt / 10 <= 10 else '不过'})")

        # 3 bootstrap
        boots = [rng.choice(vals, size=n, replace=True).mean() for _ in range(2000)]
        lo, hi = np.percentile(boots, [2.5, 97.5])
        lines.append(f"- ③bootstrap95%CI: [{lo:+.2f}, {hi:+.2f}]({'通过' if lo > 0 else '不过'})")

        # 4 去最好3笔
        trimmed = G.nsmallest(len(G) - 3, "E3%")
        lines.append(f"- ④去最好3笔: 均{trimmed['E3%'].mean():+.2f}({'通过' if allpos(trimmed) else '均值仍在,分年:' + years_table(trimmed)})")

        # 5 留一年(每年剔一年看剩余)
        for y in sorted(G["年"].unique()):
            rest = G[G["年"] != y]
            if len(rest):
                lines.append(f"- ⑤剔{y}: {head(rest)}")
        lines.append("")

    # 边界晃动终验(G1/G2)
    lines.append("## 边界晃动终验")
    for a in [7.0, 7.25, 7.5, 7.75, 8.0]:
        for tname, tf in [("换手<8", lambda x: x["首板换手%"] < 8), ("不限", lambda x: x["首板换手%"] >= 0)]:
            G = d[yin & d["买入开盘%"].between(a, 9.5, inclusive="left")]
            G = G[tf(G)]
            if len(G) >= 15:
                lines.append(f"- 今开{a}~9.5×{tname}: {head(G)} ｜ {years_table(G)}")
    for tb in [5, 8, 10]:
        G = d[yin & d["买入开盘%"].between(7.5, 9.5, inclusive="left")]
        G = G[G["首板换手%"] < tb]
        if len(G) >= 15:
            lines.append(f"- G1×换手<{tb}: {head(G)} ｜ {years_table(G)}")

    # 尾部依赖: G1 最好5笔
    lines.append("\n## G1 最好5笔(尾部依赖目检)")
    for _, r in G1.nlargest(5, "E3%").iterrows():
        lines.append(f"- {r['买入日'].date()} {r['名称']} 今开{r['买入开盘%']:+.1f} 换手{r['首板换手%']:.1f} "
                     f"距MA20{r['地基距MA20%']:+.1f} 前20日{r['前20日涨幅%']:+.1f} → E3{r['E3%']:+.1f}%")
    lines.append("\n## G1 最差5笔(最坏情形)")
    for _, r in G1.nsmallest(5, "E3%").iterrows():
        lines.append(f"- {r['买入日'].date()} {r['名称']} 今开{r['买入开盘%']:+.1f} 换手{r['首板换手%']:.1f} "
                     f"距MA20{r['地基距MA20%']:+.1f} 前20日{r['前20日涨幅%']:+.1f} → E3{r['E3%']:+.1f}%")

    txt = "\n".join(lines)
    with open(f"{OUT}/汇总/稳健性检验.md", "w", encoding="utf-8") as fh:
        fh.write(txt)
    print(txt)


if __name__ == "__main__":
    main()
