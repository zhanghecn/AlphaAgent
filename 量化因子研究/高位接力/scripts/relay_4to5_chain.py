# -*- coding: utf-8 -*-
"""四进五 · 好票坏票对比·正确版(宿主机: uv run python relay_4to5_chain.py)。

方法论对齐打板口诀体系: 特征只用 T-1 收盘可知 + 当天竞价(9:25)可知——
地基(阴阳/涨跌/姿态/锚/前波) × 连续链条(b1→b4 开盘档结构) × 换手窗 × 竞价档。
当天换手/量比/封住一律不用(未来函数)。
分析形式 = 速查树交叉矩阵(A1 教训:信号在交互不在边际) + 边界细扫 + 好坏票分布。
"""
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 230)

# 档位定义与产品一致: 低<0 / 平0~3 / 高3~7 / 强7~9.5 / 一字≥9.5(链上板可一字)
BINS = [-99, 0, 3, 7, 9.5, 99]
LABELS = ["低", "平", "高", "强", "一字"]


def auc(good: pd.Series, bad: pd.Series) -> float:
    both = pd.concat([good.dropna(), bad.dropna()])
    if len(good.dropna()) < 5 or len(bad.dropna()) < 5:
        return float("nan")
    ranks = both.rank()
    n1 = len(good.dropna())
    u = ranks.iloc[:n1].sum() - n1 * (n1 + 1) / 2
    return u / (n1 * len(bad.dropna()))


def load() -> pd.DataFrame:
    E = pd.read_csv(f"{ROOT}/四进五全量明细.csv", dtype={"代码": str})
    E = E[(~E["顶格"].astype(bool)) & (~E["未完"].astype(bool))]
    F = E[E["N"] == 4].copy()
    for k in (1, 2, 3, 4):
        F[f"b{k}档"] = pd.cut(F[f"b{k}开盘%"], BINS, labels=LABELS, right=False)
    F["竞价档"] = pd.cut(F["买入开盘%"], [-99, 0, 3, 6, 9.5],
                       labels=["低<0", "平0~3", "温3~6", "强6~9.5"], right=False)
    F["b4换手窗"] = pd.cut(F["b4换手%"], [0, 5, 10, 15, 20, 30, 999],
                        labels=["<5", "5~10", "10~15", "15~20", "20~30", "30+"], right=False)
    F["b3换手窗"] = pd.cut(F["b3换手%"], [0, 5, 10, 15, 20, 30, 999],
                        labels=["<5", "5~10", "10~15", "15~20", "20~30", "30+"], right=False)
    F["链一字数"] = F["链"].fillna("").str.count("一字")
    # 链型: 连续开盘档的结构分类(速查树语言)
    def chain_type(r):
        b1, b2, b3, b4 = r["b1档"], r["b2档"], r["b3档"], r["b4档"]
        if b4 == "一字":
            return "尾锁链(四板一字)"
        if b2 == "一字" or b3 == "一字":
            return "中锁链(二三板一字,四板开)"
        seq = [r["b1开盘%"], r["b2开盘%"], r["b3开盘%"], r["b4开盘%"]]
        if all(seq[i] < seq[i + 1] for i in range(3)):
            return "递强链(逐板越开越高)"
        if r["b1开盘%"] < 0 and r["b4开盘%"] >= 7:
            return "洗后强链(一板低开洗,四板强开)"
        if r["b2开盘%"] >= 3 and r["b4开盘%"] >= 3:
            return "高开链(全程高开)"
        if r["b2开盘%"] < 3 and r["b4开盘%"] >= 7:
            return "贴零转强链(前板贴零,四板强开)"
        return "平低混开链(其余)"
    F["链型"] = F.apply(chain_type, axis=1)
    return F


def cell(g: pd.DataFrame) -> str:
    if not len(g):
        return "     —    "
    e3 = g["E3%"].dropna()
    return (f"{len(g):3d}笔 胜{(e3 > 0).mean() * 100:3.0f}% 均{e3.mean():+6.2f} "
            f"妖率{(g['最终高度'] >= 6).mean() * 100:3.0f}%")


def main() -> None:
    F = load()
    good, bad = F["E3%"] > 0, F["E3%"] <= 0
    bigw, bigl = F["E3%"] >= 10, F["E3%"] <= -10
    print(f"四接五池 {len(F)} 笔; 好(赚){int(good.sum())} / 坏(亏){int(bad.sum())}; "
          f"大赚{int(bigw.sum())} / 大亏{int(bigl.sum())}\n")

    print("=" * 22, "① 纯事前+竞价维度 AUC 复查(好vs坏 / 大赚vs大亏)", "=" * 22)
    dims = ["b1开盘%", "b2开盘%", "b3开盘%", "b4开盘%",
            "b2换手%", "b3换手%", "b4换手%", "买入开盘%",
            "地基涨跌%", "地基距MA20%", "距60日新高%", "锚位%", "锚距",
            "前波60日最高板", "前板高度", "首20日涨幅%", "首10日涨幅%",
            "昨日涨停家数", "昨日最高板", "昨日4板+家数", "链一字数"]
    rows = []
    for d in dims:
        rows.append({"维度": d,
                     "好vs坏AUC": round(auc(F.loc[good, d], F.loc[bad, d]), 3),
                     "大赚vs大亏AUC": round(auc(F.loc[bigw, d], F.loc[bigl, d]), 3)})
    t = pd.DataFrame(rows)
    t["偏"] = (t["大赚vs大亏AUC"] - 0.5).abs()
    print(t.sort_values("偏", ascending=False).drop(columns="偏").to_string(index=False))

    print("\n" + "=" * 22, "② 连续链条结构:链型好坏票", "=" * 22)
    for ct, g in F.groupby("链型"):
        wk = g[g["年"].astype(int) <= 2022]["E3%"].dropna()
        st = g[g["年"].astype(int) >= 2023]["E3%"].dropna()
        print(f"\n◆ {ct}: {cell(g)}")
        print(f"   大赚率{(g['E3%'] >= 10).mean() * 100:.0f}% 大亏率{(g['E3%'] <= -10).mean() * 100:.0f}% "
              f"| 弱20-22均{wk.mean():+.2f}({len(wk)}) 强23+均{st.mean():+.2f}({len(st)})")
        print(f"   地基阴阳: {g['阴阳'].value_counts().to_dict()} | b4板型: {g['b4板型'].value_counts().to_dict()}")

    print("\n" + "=" * 22, "③ 竞价交叉(A1式:信号在交互)", "=" * 22)
    for xdim, order in [("b4档", LABELS), ("b4换手窗", ["<5", "5~10", "10~15", "15~20", "20~30", "30+"]),
                        ("地基阴阳", ["阳", "阴"]), ("链一字数", [0, 1, 2, 3, 4]),
                        ("b3换手窗", ["<5", "5~10", "10~15", "15~20", "20~30", "30+"])]:
        print(f"\n—— 竞价档 × {xdim} (n/胜率/E3均/走妖率) ——")
        for jl in ["低<0", "平0~3", "温3~6", "强6~9.5"]:
            parts = []
            for xl in order:
                g = F[(F["竞价档"] == jl) & (F[xdim] == xl)]
                parts.append(f"{xl}:{cell(g)}")
            print(f"竞价{jl}: " + " | ".join(parts))

    print("\n" + "=" * 22, "④ 链型 × 竞价 × 换手(三刀收口)", "=" * 22)
    for ct in F["链型"].value_counts().index:
        g0 = F[F["链型"] == ct]
        if len(g0) < 15:
            continue
        print(f"\n◆ {ct} (池{len(g0)})")
        for jl in ["低<0", "平0~3", "温3~6", "强6~9.5"]:
            g = g0[g0["竞价档"] == jl]
            if not len(g):
                continue
            e3 = g["E3%"].dropna()
            print(f"  竞价{jl}: {cell(g)} 大亏率{(g['E3%'] <= -10).mean() * 100:.0f}%")
        # 该链型内 b4换手 粗扫
        for w in ["<5", "5~10", "10~20", "20+"]:
            lo, hi = {"<5": (0, 5), "5~10": (5, 10), "10~20": (10, 20), "20+": (20, 999)}[w]
            g = g0[(g0["b4换手%"] >= lo) & (g0["b4换手%"] < hi)]
            if len(g):
                e3 = g["E3%"].dropna()
                print(f"  b4换{w}: {cell(g)}")

    print("\n" + "=" * 22, "⑤ 地基 × 链型/竞价", "=" * 22)
    for y in ["阳", "阴"]:
        for ct in F["链型"].value_counts().index:
            g = F[(F["阴阳"] == y) & (F["链型"] == ct)]
            if len(g) >= 10:
                print(f"地基{y} × {ct}: {cell(g)}")


main()
