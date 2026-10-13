# -*- coding: utf-8 -*-
"""二接三/三接四 · P3 三路并进(宿主机: uv run python relay23_grid.py)。

A. 漏网池全谱网格: 口诀=— 的 4120 笔, 竞价档×末板开档×板位×阴阳,
   找「格内整体肥」(n≥15 且 胜率≥50% 且 E3均≥+2)的收编候选格。
B. 腿的通用性网格: 现有腿(前波=0/缩量末板/一板≥7/贴顶/地基阴阳等)
   在各原型格上的加减分。
C. 环境维度判别力: 昨日涨停家数/昨日最高板/昨日4板+家数 分档×时代。
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
        return "—"
    trim = e3.sort_values().iloc[:-3] if len(e3) > 3 else e3
    return (f"{len(g):4d}笔 {e3.mean():+6.2f}/{(e3 > 0).mean() * 100:3.0f}% "
            f"剔3:{trim.mean():+6.2f} 亏:{(e3 <= -10).sum():2d}")


def era_split(g: pd.DataFrame) -> str:
    wk = g[g["年"] <= 2022]["E3%"].dropna()
    st = g[g["年"] >= 2023]["E3%"].dropna()
    return (f"弱{len(wk):3d}笔{wk.mean():+5.2f} 强{len(st):3d}笔{st.mean():+5.2f}")


def yearly(g: pd.DataFrame) -> str:
    return " ".join(f"{y}:{len(gg)}{gg['E3%'].mean():+.1f}"
                    for y, gg in g.groupby("年"))


def main() -> None:
    E = pd.read_pickle("/tmp/relay23_tagged.pkl")
    E["末板开"] = E.apply(lambda r: r["b2开盘%"] if r["N"] == 2 else r["b3开盘%"], axis=1)
    E["末板换"] = E.apply(lambda r: r["b2换手%"] if r["N"] == 2 else r["b3换手%"], axis=1)
    E["末板开档"] = pd.cut(E["末板开"], OPEN_BINS, labels=OPEN_LABELS, right=False)
    E["今开档"] = pd.cut(E["买入开盘%"], JIN_BINS, labels=JIN_LABELS, right=False)

    print("=" * 26, "A. 漏网池(口诀=—)全谱网格", "=" * 26)
    M = E[E["口诀"] == "—"]
    print(f"漏网池 {len(M)} 笔: {stat(M)}\n")
    for n in (2, 3):
        for y in ("阳", "阴"):
            sub = M[(M["N"] == n) & (M["阴阳"] == y)]
            print(f"\n◆ {n}接{n + 1}{y} 漏网 {len(sub)}笔 (行=末板开档 列=今开档; n|均|胜)")
            hdr = "        " + "".join(f"{jl:>18s}" for jl in JIN_LABELS)
            print(hdr)
            for ol in OPEN_LABELS:
                cells = []
                for jl in JIN_LABELS:
                    g = sub[(sub["末板开档"] == ol) & (sub["今开档"] == jl)]
                    if len(g) < 8:
                        cells.append(f"{'—':>18s}")
                        continue
                    e3 = g["E3%"].dropna()
                    cells.append(f"{len(g):3d}|{e3.mean():+5.1f}|{(e3 > 0).mean() * 100:2.0f}%"
                                 f"{'*' if (e3.mean() >= 2 and (e3 > 0).mean() >= 0.5) else ' '}"
                                 .rjust(18))
                print(f"{ol:>7s} " + "".join(cells))

    print("\n\n" + "=" * 26, "B. 腿的通用性网格(全池, 含已命中)", "=" * 26)
    legs = {
        "前波60=0": E["前波60日最高板"] == 0,
        "前波60≤2": E["前波60日最高板"] <= 2,
        "末板缩量<5": E["末板换"] < 5,
        "末板换10~20": E["末板换"].between(10, 20),
        "一板≥7强开": E["b1开盘%"] >= 7,
        "一板<0低开": E["b1开盘%"] < 0,
        "贴顶(距新高≥-8)": E["距60日新高%"] >= -8,
        "远离顶(距新高<-20)": E["距60日新高%"] < -20,
        "地基平(-2~+1)": E["地基涨跌%"].between(-2, 1),
        "首20日<0(超跌)": E["首20日涨幅%"] < 0,
        "首10日<10(无透支)": E["首10日涨幅%"] < 10,
    }
    print(f"{'腿':>18s} | {'N=2阳':>22s} | {'N=2阴':>22s} | {'N=3阳':>22s} | {'N=3阴':>22s}")
    for lname, lm in legs.items():
        cells = []
        for n in (2, 3):
            for y in ("阳", "阴"):
                g = E[lm & (E["N"] == n) & (E["阴阳"] == y)]
                e3 = g["E3%"].dropna()
                cells.append(f"{len(g):4d}笔{e3.mean():+5.2f}/{(e3 > 0).mean() * 100:2.0f}%")
        print(f"{lname:>18s} | " + " | ".join(c.rjust(22) for c in cells))

    print("\n" + "=" * 26, "C. 环境维度(昨日, T-1可知) × 时代", "=" * 26)
    for col, bins, labels in [
        ("昨日涨停家数", [0, 30, 60, 100, 999], ["<30冰点", "30~60", "60~100", "100+高热"]),
        ("昨日4板+家数", [0.5, 1.5, 3.5, 6.5, 99], ["1独苗", "2~3", "4~6", "7+"]),
        ("昨日最高板", [0.5, 2.5, 4.5, 6.5, 99], ["≤2", "3~4", "5~6", "7+"]),
    ]:
        E["env"] = pd.cut(E[col].astype(float), bins=bins, labels=labels, right=False)
        print(f"\n—— {col} ——")
        for lab in labels:
            g = E[E["env"] == lab]
            if not len(g):
                continue
            print(f"  {lab:>8s}: {stat(g)} | {era_split(g)}")


if __name__ == "__main__":
    main()
