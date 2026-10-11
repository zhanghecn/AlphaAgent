# -*- coding: utf-8 -*-
"""四进五 · P1 全谱画像(宿主机: uv run python relay_4to5_scan.py)。

读 四进五全量明细.csv(N=2/3/4/5,2020-01起,触板&非一字;顶格行有标记)。
研究池 = 非顶格(≥9.5排队买不到);E3 = 产品卖出纪律口径。
输出: 各板位基线 → N=4 全谱单维 → 二维交互 → 好票坏票对比 → 顶格逆向选择。
"""
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 200)


def load() -> pd.DataFrame:
    E = pd.read_csv(f"{ROOT}/四进五全量明细.csv", dtype={"代码": str})
    E["买入日"] = pd.to_datetime(E["买入日"])
    return E


def stats(e: pd.DataFrame) -> dict[str, object]:
    e3 = e["E3%"].dropna()
    return {
        "n": len(e),
        "E3均": round(e3.mean(), 2) if len(e3) else None,
        "胜率": round((e3 > 0).mean() * 100, 1) if len(e3) else None,
        "封住率": round(e["封住"].mean() * 100, 1) if len(e) else None,
    }


def cut_table(e: pd.DataFrame, col: str, bins: list, labels: list,
              era_col: str = "年") -> pd.DataFrame:
    """单维切表: n/E3均/胜率/封住率 + 弱市(20-22)均/强市(23+)均。"""
    c = pd.cut(e[col].astype(float), bins=bins, labels=labels, right=False)
    rows = []
    for lab in labels:
        g = e[c == lab]
        if not len(g):
            continue
        wk = g[g[era_col].astype(int) <= 2022]["E3%"].dropna()
        st = g[g[era_col].astype(int) >= 2023]["E3%"].dropna()
        s = stats(g)
        s["弱20-22"] = f"{wk.mean():+.2f}({len(wk)})" if len(wk) else "—"
        s["强23+"] = f"{st.mean():+.2f}({len(st)})" if len(st) else "—"
        s["档"] = lab
        rows.append(s)
    return pd.DataFrame(rows)[["档", "n", "E3均", "胜率", "封住率", "弱20-22", "强23+"]]


def cat_table(e: pd.DataFrame, col: str) -> pd.DataFrame:
    rows = []
    for lab, g in e.groupby(col, dropna=False):
        wk = g[g["年"].astype(int) <= 2022]["E3%"].dropna()
        st = g[g["年"].astype(int) >= 2023]["E3%"].dropna()
        s = stats(g)
        s["弱20-22"] = f"{wk.mean():+.2f}({len(wk)})" if len(wk) else "—"
        s["强23+"] = f"{st.mean():+.2f}({len(st)})" if len(st) else "—"
        s["档"] = str(lab)
        rows.append(s)
    return pd.DataFrame(rows)[["档", "n", "E3均", "胜率", "封住率", "弱20-22", "强23+"]]


def yearly(e: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for y, g in e.groupby("年"):
        s = stats(g)
        s["年"] = y
        rows.append(s)
    return pd.DataFrame(rows)[["年", "n", "E3均", "胜率", "封住率"]]


def grid(e: pd.DataFrame, rc: str, cc: str, rbins, rlabels, cbins, clabels) -> pd.DataFrame:
    """二维格: 行列交叉,格子=n|E3均|胜率。"""
    r = pd.cut(e[rc].astype(float), bins=rbins, labels=rlabels, right=False)
    c = pd.cut(e[cc].astype(float), bins=cbins, labels=clabels, right=False)
    out = pd.DataFrame(index=rlabels, columns=clabels, dtype=object)
    for rl in rlabels:
        for cl in clabels:
            g = e[(r == rl) & (c == cl)]
            if not len(g):
                out.loc[rl, cl] = "—"
                continue
            e3 = g["E3%"].dropna()
            out.loc[rl, cl] = f"{len(g)}|{e3.mean():+.2f}|{(e3 > 0).mean() * 100:.0f}%"
    return out


def main() -> None:
    E = load()
    R = E[(~E["顶格"].astype(bool)) & (~E["未完"].astype(bool))].copy()
    R["年"] = R["年"].astype(int)
    F = R[R["N"] == 4].copy()          # 四接五研究主池
    print(f"研究池(非顶格非未完) {len(R)} 行;四接五 {len(F)} 行,月均 {len(F) / 82:.1f} 笔\n")

    print("=" * 30, "① 各板位基线(E3)", "=" * 30)
    rows = []
    for n, g in R.groupby("N"):
        s = stats(g)
        s["板位"] = f"{n}接{n + 1}"
        s["月均"] = round(len(g) / 82, 1)
        rows.append(s)
    print(pd.DataFrame(rows)[["板位", "n", "月均", "E3均", "胜率", "封住率"]].to_string(index=False))

    for n in (3, 4, 5):
        print(f"\n—— {n}接{n + 1} 分年 ——")
        print(yearly(R[R["N"] == n]).to_string(index=False))

    print("\n" + "=" * 30, "② 四接五全谱·单维", "=" * 30)
    print("\n—— 地基阴阳 ——")
    print(cat_table(F, "阴阳").to_string(index=False))
    print("\n—— 四板开盘档 ——")
    print(cut_table(F, "b4开盘%", [-99, 0, 3, 7, 9.5], ["低<0", "平0~3", "高3~7", "强7~9.5"]).to_string(index=False))
    print("\n—— 四板换手档 ——")
    print(cut_table(F, "b4换手%", [0, 3, 5, 10, 15, 20, 30, 999],
                    ["<3", "3~5", "5~10", "10~15", "15~20", "20~30", "30+"],
                    ).to_string(index=False))
    print("\n—— 三板换手档 ——")
    print(cut_table(F, "b3换手%", [0, 3, 5, 10, 15, 20, 30, 999],
                    ["<3", "3~5", "5~10", "10~15", "15~20", "20~30", "30+"],
                    ).to_string(index=False))
    print("\n—— 今开档(买入开盘%) ——")
    print(cut_table(F, "买入开盘%", [-99, 0, 3, 6, 9.5], ["低<0", "平0~3", "温3~6", "强6~9.5"]).to_string(index=False))
    print("\n—— 四板板型 ——")
    print(cat_table(F, "b4板型").to_string(index=False))
    print("\n—— 前波60日最高板 ——")
    print(cut_table(F, "前波60日最高板", [-1, 0.5, 2.5, 4.5, 99], ["0", "1~2", "3~4", "5+"],
                    ).to_string(index=False))
    print("\n—— 距60日新高% ——")
    print(cut_table(F, "距60日新高%", [-99, -20, -8, 0, 99], ["<-20", "-20~-8", "-8~0", "≥0"],
                    ).to_string(index=False))
    print("\n—— 地基涨跌% ——")
    print(cut_table(F, "地基涨跌%", [-99, -2, 0, 1, 3, 99], ["<-2", "-2~0", "0~1", "1~3", "≥3"],
                    ).to_string(index=False))
    print("\n—— 锚位% ——")
    print(cut_table(F, "锚位%", [-99, -2, 0, 2, 5, 99], ["<-2", "-2~0", "0~2", "2~5", "≥5"]).to_string(index=False))
    print("\n—— 首20日涨幅% ——")
    print(cut_table(F, "首20日涨幅%", [-99, 0, 5, 15, 99], ["<0", "0~5", "5~15", "≥15"]).to_string(index=False))
    print("\n—— 昨日涨停家数 ——")
    print(cut_table(F, "昨日涨停家数", [0, 30, 60, 100, 999], ["<30", "30~60", "60~100", "100+"],
                    ).to_string(index=False))
    print("\n—— 昨日最高板(4=昨日自己就是市场最高) ——")
    print(cut_table(F, "昨日最高板", [3.5, 4.5, 6.5, 99], ["=4(我就是最高)", "5~6", "7+"],
                    ).to_string(index=False))
    print("\n—— 昨日4板+家数(1=独苗) ——")
    print(cut_table(F, "昨日4板+家数", [0.5, 1.5, 3.5, 99], ["1(独苗)", "2~3", "4+"],
                    ).to_string(index=False))
    print("\n—— 地基姿态 ——")
    print(cat_table(F, "地基姿态").to_string(index=False))
    print("\n—— 均线排列 ——")
    print(cat_table(F, "均线").to_string(index=False))

    print("\n" + "=" * 30, "③ 判别器轮换检验(远板信息是否过期)", "=" * 30)
    for col in ("b1开盘%", "b2开盘%", "b3开盘%", "b4开盘%", "b3换手%", "b4换手%"):
        cor = F[[col, "E3%"]].dropna().corr().iloc[0, 1]
        print(f"{col:8s} 与E3相关系数: {cor:+.3f}")

    print("\n" + "=" * 30, "④ 二维交互", "=" * 30)
    print("\n—— 四板换手 × 今开 ——")
    print(grid(F, "b4换手%", "买入开盘%", [0, 5, 10, 15, 20, 30, 999],
          ["<5", "5~10", "10~15", "15~20", "20~30", "30+"],
          [-99, 0, 3, 6, 9.5], ["低<0", "平0~3", "温3~6", "强6~9.5"]).to_string())
    print("\n—— 阴阳 × 四板换手 ——")
    for lab, g in F.groupby("阴阳"):
        c = pd.cut(g["b4换手%"].astype(float), bins=[0, 5, 10, 15, 20, 30, 999],
                   labels=["<5", "5~10", "10~15", "15~20", "20~30", "30+"], right=False)
        parts = []
        for l2 in ["<5", "5~10", "10~15", "15~20", "20~30", "30+"]:
            gg = g[c == l2]
            if not len(gg):
                parts.append(f"{l2}:—")
                continue
            e3 = gg["E3%"].dropna()
            parts.append(f"{l2}:{len(gg)}|{e3.mean():+.2f}|{(e3 > 0).mean() * 100:.0f}%")
        print(f"{lab}: " + "  ".join(parts))
    print("\n—— 四板开盘 × 今开 ——")
    print(grid(F, "b4开盘%", "买入开盘%", [-99, 0, 3, 7, 9.5], ["低<0", "平0~3", "高3~7", "强7~9.5"],
          [-99, 0, 3, 6, 9.5], ["低<0", "平0~3", "温3~6", "强6~9.5"]).to_string())
    print("\n—— 三板换手 × 四板换手 ——")
    print(grid(F, "b3换手%", "b4换手%", [0, 5, 10, 15, 20, 999], ["<5", "5~10", "10~15", "15~20", "20+"],
          [0, 5, 10, 15, 20, 30, 999], ["<5", "5~10", "10~15", "15~20", "20~30", "30+"],
          ).to_string())

    print("\n" + "=" * 30, "⑤ 好票坏票对比(E3>0 vs E3≤0)", "=" * 30)
    good = F[F["E3%"] > 0]
    bad = F[F["E3%"] <= 0]
    dims = ["b4开盘%", "b4换手%", "b3换手%", "b2换手%", "买入开盘%", "地基涨跌%",
            "距60日新高%", "前波60日最高板", "锚位%", "首20日涨幅%", "昨日涨停家数",
            "昨日最高板", "昨日4板+家数", "买入量比", "换手梯度"]
    rows = []
    for d in dims:
        rows.append({"维度": d, "好票中位": round(good[d].median(), 2),
                     "坏票中位": round(bad[d].median(), 2),
                     "好票均值": round(good[d].mean(), 2), "坏票均值": round(bad[d].mean(), 2)})
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"\n好票 {len(good)} / 坏票 {len(bad)};阴阳占比 好:{good['阴阳'].value_counts().to_dict()} "
          f"坏:{bad['阴阳'].value_counts().to_dict()}")

    print("\n" + "=" * 30, "⑥ 顶格逆向选择(诊断)", "=" * 30)
    for n in (3, 4):
        g = E[(E["N"] == n) & (~E["未完"].astype(bool))]
        tg = g[g["顶格"].astype(bool)]
        nt = g[~g["顶格"].astype(bool)]
        print(f"{n}接{n + 1}: 顶格 {len(tg)} 笔 E3均 {tg['E3%'].mean():+.2f} 胜率 "
              f"{(tg['E3%'] > 0).mean() * 100:.0f}% | 非顶格 {len(nt)} 笔 E3均 "
              f"{nt['E3%'].mean():+.2f} 胜率 {(nt['E3%'] > 0).mean() * 100:.0f}%")

    print("\n" + "=" * 30, "⑦ 最终高度分布(四接五买后走多远)", "=" * 30)
    print(F.groupby("最终高度").agg(n=("E3%", "size"), E3均=("E3%", "mean")).round(2).to_string())


main()
