# -*- coding: utf-8 -*-
"""二接三/三接四 · P7 量价结构与板型深挖(宿主机: uv run python relay23_vol.py)。

现有体系只用了「单点换手」(二板换手/三板换手窗), 没用过:
  A. 换手趋势: b1→b2(→b3) 换手增减模式(递量/缩量/平量)
  B. 累计换手: 链上总换手(筹码换代总量)
  C. 换手×开盘交互: 高换手低开(洗盘?) vs 高换手强开(抢筹?)
  D. 板型链: 实体/下影/一字 的组合模式(下影=盘中砸过拉回=分歧转一致?)
每维 × 板位 × 阴阳, 找「池底外显著偏移」的格, 再与现有口诀对照增量。
"""
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 240)


def stat(g: pd.DataFrame) -> str:
    e3 = g["E3%"].dropna()
    if not len(g):
        return "—"
    trim = e3.sort_values().iloc[:-3] if len(e3) > 3 else e3
    return (f"{len(g):4d}笔 {e3.mean():+6.2f}/{(e3 > 0).mean() * 100:3.0f}% "
            f"剔3:{trim.mean():+5.2f} 亏:{(e3 <= -10).sum():2d}")


def era(g: pd.DataFrame) -> str:
    wk = g[g["年"] <= 2022]["E3%"].dropna()
    st = g[g["年"] >= 2023]["E3%"].dropna()
    return (f"弱{len(wk):3d}{wk.mean():+5.1f}/{(wk > 0).mean() * 100:2.0f}% "
            f"强{len(st):3d}{st.mean():+5.1f}/{(st > 0).mean() * 100:2.0f}%")


def main() -> None:
    E = pd.read_pickle("/tmp/relay23_tagged.pkl")
    E["末板换"] = E.apply(lambda r: r["b2换手%"] if r["N"] == 2 else r["b3换手%"], axis=1)
    E["末板型"] = E.apply(lambda r: r["b2板型"] if r["N"] == 2 else r["b3板型"], axis=1)
    E["累计换手"] = E["b1换手%"].fillna(0) + E["b2换手%"].fillna(0) + E["b3换手%"].fillna(0)
    E["换手趋势"] = E.apply(
        lambda r: ("递量" if r["b2换手%"] > r["b1换手%"] * 1.3 else
                   ("缩量" if r["b2换手%"] < r["b1换手%"] * 0.7 else "平量"))
        if r["N"] == 2 else
        ("递量" if r["b3换手%"] > r["b2换手%"] * 1.3 else
         ("缩量" if r["b3换手%"] < r["b2换手%"] * 0.7 else "平量")), axis=1)

    print("=" * 26, "A. 换手趋势(末板 vs 前板)", "=" * 26)
    for n in (2, 3):
        for y in ("阳", "阴"):
            sub = E[(E["N"] == n) & (E["阴阳"] == y)]
            parts = []
            for t in ("递量", "平量", "缩量"):
                g = sub[sub["换手趋势"] == t]
                if len(g) >= 10:
                    parts.append(f"{t}:{stat(g)}")
            print(f"  {n}接{n + 1}{y}: " + " | ".join(parts))

    print("\n" + "=" * 26, "B. 累计换手分档", "=" * 26)
    E["累换档"] = pd.cut(E["累计换手"], [0, 10, 20, 30, 45, 999],
                         labels=["<10", "10~20", "20~30", "30~45", "45+"], right=False)
    for n in (2, 3):
        for y in ("阳", "阴"):
            sub = E[(E["N"] == n) & (E["阴阳"] == y)]
            parts = []
            for lab in ["<10", "10~20", "20~30", "30~45", "45+"]:
                g = sub[sub["累换档"] == lab]
                if len(g) >= 10:
                    parts.append(f"{lab}:{stat(g)}")
            print(f"  {n}接{n + 1}{y}:\n    " + "\n    ".join(parts))

    print("\n" + "=" * 26, "C. 末板换手 × 末板开盘 交互(量价结构)", "=" * 26)
    E["末板开档"] = pd.cut(E.apply(lambda r: r["b2开盘%"] if r["N"] == 2 else r["b3开盘%"], axis=1),
                           [-99, 0, 3, 7, 9.5, 99], labels=["低", "平", "高", "强", "一字"], right=False)
    E["末板换档"] = pd.cut(E["末板换"], [0, 5, 10, 20, 999],
                           labels=["缩<5", "中5~10", "充10~20", "爆20+"], right=False)
    for n in (2, 3):
        for y in ("阳", "阴"):
            sub = E[(E["N"] == n) & (E["阴阳"] == y)]
            print(f"\n  ◆ {n}接{n + 1}{y} (行=开盘档 列=换手档)")
            print("        " + "".join(f"{w:>22s}" for w in ["缩<5", "中5~10", "充10~20", "爆20+"]))
            for ol in ["低", "平", "高", "强", "一字"]:
                cells = []
                for wl in ["缩<5", "中5~10", "充10~20", "爆20+"]:
                    g = sub[(sub["末板开档"] == ol) & (sub["末板换档"] == wl)]
                    if len(g) < 10:
                        cells.append(f"{'—':>22s}")
                    else:
                        e3 = g["E3%"].dropna()
                        cells.append(f"{len(g):4d}|{e3.mean():+5.1f}|{(e3 > 0).mean() * 100:2.0f}%".rjust(22))
                print(f"  {ol:>5s} " + "".join(cells))

    print("\n" + "=" * 26, "D. 板型链(末板型 × 前板型)", "=" * 26)
    E["前板型"] = E.apply(lambda r: r["b1板型"] if r["N"] == 2 else r["b2板型"], axis=1)
    for n in (2, 3):
        for y in ("阳", "阴"):
            sub = E[(E["N"] == n) & (E["阴阳"] == y)]
            print(f"\n  ◆ {n}接{n + 1}{y}")
            for pre in ("实体", "下影", "一字"):
                parts = []
                for cur in ("实体", "下影", "一字"):
                    g = sub[(sub["前板型"] == pre) & (sub["末板型"] == cur)]
                    if len(g) >= 10:
                        e3 = g["E3%"].dropna()
                        parts.append(f"{pre}→{cur}:{len(g)}|{e3.mean():+.1f}|{(e3 > 0).mean() * 100:.0f}%")
                if parts:
                    print("    " + "  ".join(parts))


if __name__ == "__main__":
    main()
