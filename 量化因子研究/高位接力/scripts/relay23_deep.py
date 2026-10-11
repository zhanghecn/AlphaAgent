# -*- coding: utf-8 -*-
"""二接三/三接四 · P4 深挖三路(宿主机: uv run python relay23_deep.py)。

A. 环境×口诀命中票: 昨日4板+家数/涨停家数 在口诀命中子集上的判别力
   (若精选票在拥挤段也崩, 环境=信息层/仓位层候选; 若精选票免疫, 环境无用)。
B. C2 大亏手术: 96笔命中中17笔大亏的事前特征归因(逐票+维度对比)。
C. 跨时代通用格搜索: 板位×阴阳×末板开档×今开档×腿,
   找 20-22胜≥45%且E3>0 且 23+胜≥55%且E3≥+3 且 总n≥12 的格。
"""
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 240)

OPEN_BINS = [-99, 0, 1, 3, 7, 9.5, 99]
OPEN_LABELS = ["低<0", "贴0~1", "平1~3", "高3~7", "强7~9.5", "一字≥9.5"]
JIN_BINS = [-99, 0, 3, 6, 9.5]
JIN_LABELS = ["低<0", "平0~3", "温3~6", "强6~9.5"]


def stat(g: pd.DataFrame) -> str:
    e3 = g["E3%"].dropna()
    if not len(g):
        return "0笔"
    trim = e3.sort_values().iloc[:-3] if len(e3) > 3 else e3
    return (f"{len(g):3d}笔 {e3.mean():+6.2f}/{(e3 > 0).mean() * 100:3.0f}% "
            f"剔3:{trim.mean():+5.2f}")


def main() -> None:
    E = pd.read_pickle("/tmp/relay23_tagged.pkl")
    E["末板开"] = E.apply(lambda r: r["b2开盘%"] if r["N"] == 2 else r["b3开盘%"], axis=1)
    E["末板换"] = E.apply(lambda r: r["b2换手%"] if r["N"] == 2 else r["b3换手%"], axis=1)
    E["末板开档"] = pd.cut(E["末板开"], OPEN_BINS, labels=OPEN_LABELS, right=False)
    E["今开档"] = pd.cut(E["买入开盘%"], JIN_BINS, labels=JIN_LABELS, right=False)

    print("=" * 24, "A. 环境 × 口诀命中票(精选票是否免疫拥挤)", "=" * 24)
    H = E[E["口诀"] != "—"]
    for col, bins, labels in [
        ("昨日4板+家数", [0.5, 1.5, 3.5, 6.5, 99], ["1独苗", "2~3", "4~6", "7+"]),
        ("昨日涨停家数", [0, 30, 60, 100, 999], ["<30", "30~60", "60~100", "100+"]),
    ]:
        print(f"\n—— {col} —— (左=口诀命中票, 右=漏网票)")
        Hc = pd.cut(H[col].astype(float), bins=bins, labels=labels, right=False)
        Mc = pd.cut(E[E["口诀"] == "—"][col].astype(float), bins=bins, labels=labels, right=False)
        for lab in labels:
            gh = H[Hc == lab]
            gm = E[E["口诀"] == "—"][Mc == lab]
            print(f"  {lab:>7s}: 命中 {stat(gh):>28s} | 漏网 {stat(gm)}")

    print("\n" + "=" * 24, "B. C2 大亏手术(96笔命中)", "=" * 24)
    C2 = E[E["口诀"] == "C2"].copy()
    big_loss = C2[C2["E3%"] <= -10]
    rest = C2[C2["E3%"] > -10]
    print(f"C2 大亏 {len(big_loss)} 笔 vs 其余 {len(rest)} 笔 {stat(rest)}")
    print("\n大亏17笔逐票:")
    for _, r in big_loss.sort_values("E3%").iterrows():
        print(f"  {r['买入日']} {r['代码']} {r['名称']} E3={r['E3%']:+6.1f} "
          f"{r['阴阳']} b3开{r['b3开盘%']:6.2f} b3换{r['b3换手%']:6.2f} 今开{r['买入开盘%']:5.2f} "
          f"地基{r['地基涨跌%']:+6.2f} 前波{r['前波60日最高板']} 锚{r['锚位%']}"
          f"{'/距' + str(r['锚距']) if pd.notna(r['锚距']) else ''} 家数{r['昨日4板+家数']} "
          f"终高{r['最终高度']}")
    print("\n数值维度对比(大亏 vs 其余, 中位):")
    for d in ("b3开盘%", "b3换手%", "b2换手%", "买入开盘%", "地基涨跌%", "前波60日最高板",
              "距60日新高%", "锚位%", "首20日涨幅%", "昨日4板+家数", "昨日涨停家数"):
        print(f"  {d:>12s}: 大亏中位 {big_loss[d].median():8.2f} | 其余中位 {rest[d].median():8.2f}")
    print("\n类别分布(大亏/其余):")
    for d in ("阴阳", "b4板型" if "b4板型" in C2 else "b3板型", "地基姿态", "换手梯度"):
        if d not in C2.columns:
            continue
        print(f"  {d}: 大亏 {big_loss[d].value_counts().to_dict()} | 其余 {rest[d].value_counts().to_dict()}")

    print("\n" + "=" * 24, "C. 跨时代通用格搜索", "=" * 24)
    legs = {
        "无腿": pd.Series(True, index=E.index),
        "前波60=0": E["前波60日最高板"] == 0,
        "末板缩量<5": E["末板换"] < 5,
        "末板换10~20": E["末板换"].between(10, 20),
        "一板≥7": E["b1开盘%"] >= 7,
        "一板<0": E["b1开盘%"] < 0,
        "贴顶≥-8": E["距60日新高%"] >= -8,
        "地基平-2~1": E["地基涨跌%"].between(-2, 1),
    }
    hits = []
    for n in (2, 3):
        for y in ("阳", "阴"):
            for ol in OPEN_LABELS:
                for jl in JIN_LABELS:
                    base = ((E["N"] == n) & (E["阴阳"] == y)
                            & (E["末板开档"] == ol) & (E["今开档"] == jl))
                    for lname, lm in legs.items():
                        g = E[base & lm]
                        if len(g) < 12:
                            continue
                        wk = g[g["年"] <= 2022]["E3%"].dropna()
                        st = g[g["年"] >= 2023]["E3%"].dropna()
                        if len(wk) < 4 or len(st) < 6:
                            continue
                        if ((wk > 0).mean() >= 0.45 and wk.mean() > 0
                                and (st > 0).mean() >= 0.55 and st.mean() >= 3):
                            hits.append({
                                "格": f"{n}接{n + 1}{y} 末{ol}×今{jl} × {lname}",
                                "n": len(g),
                                "弱": f"{len(wk)}笔{wk.mean():+.1f}/{(wk > 0).mean() * 100:.0f}%",
                                "强": f"{len(st)}笔{st.mean():+.1f}/{(st > 0).mean() * 100:.0f}%",
                                "总均": round(g["E3%"].mean(), 2),
                                "口诀": g["口诀"].value_counts().head(2).to_dict(),
                            })
    print(f"满足双时代门槛的格 {len(hits)} 个:")
    for h in sorted(hits, key=lambda x: -x["总均"]):
        print(f"  ◆ {h['格']}: n={h['n']} 总均{h['总均']:+.2f} | 弱{h['弱']} | 强{h['强']} | 现有命中{h['口诀']}")


if __name__ == "__main__":
    main()
