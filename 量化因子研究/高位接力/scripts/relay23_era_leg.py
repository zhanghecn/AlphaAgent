# -*- coding: utf-8 -*-
"""二接三/三接四 · P6 时代稳定腿研究(宿主机: uv run python relay23_era_leg.py)。

目标: 给强市口诀找「时代稳定腿」——剔弱市段毒票、不伤强市段好票,
让口诀跨时代可用(弱市段可交易数翻倍, 降低对动态组切换的依赖)。

逐条: A1/A2/B1/B2/B3/C1/C2/C3 在弱20-22段的命中票,
  ① 逐票看弱市段亏票共性
  ② 候选腿(前波=0/换手/锚/距新高/地基/环境)在弱市段的提纯效果
  ③ 腿在强市段的误伤检查(剔了好票=不可接受)
反向: K5/K3 已在强市段肥, 确认其跨时代成色。
"""
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 240)


def stat(g: pd.DataFrame) -> str:
    e3 = g["E3%"].dropna()
    if not len(g):
        return "0笔"
    trim = e3.sort_values().iloc[:-3] if len(e3) > 3 else e3
    return (f"{len(g):3d}笔 {e3.mean():+6.2f}/{(e3 > 0).mean() * 100:3.0f}% "
            f"剔3:{trim.mean():+5.2f} 亏:{(e3 <= -10).sum()}")


def yearly(g: pd.DataFrame) -> str:
    return " ".join(f"{y}:{len(gg)}{gg['E3%'].mean():+.1f}"
                    for y, gg in g.groupby("年"))


LEG_DEFS = {
    "前波60=0": lambda E: E["前波60日最高板"] == 0,
    "前波60≤2": lambda E: E["前波60日最高板"] <= 2,
    "末板缩<8": lambda E: E["末板换"] < 8,
    "末板缩<5": lambda E: E["末板换"] < 5,
    "贴顶≥-12": lambda E: E["距60日新高%"] >= -12,
    "远顶<-20": lambda E: E["距60日新高%"] < -20,
    "地基≤1": lambda E: E["地基涨跌%"] <= 1,
    "地基<-2": lambda E: E["地基涨跌%"] < -2,
    "首20日<5": lambda E: E["首20日涨幅%"] < 5,
    "首10日<5": lambda E: E["首10日涨幅%"] < 5,
    "家数≤3": lambda E: E["昨日4板+家数"] <= 3,
    "涨停<60": lambda E: E["昨日涨停家数"] < 60,
    "锚nan": lambda E: E["锚位%"].isna(),
}


def era_leg_report(E: pd.DataFrame, no: str) -> None:
    g = E[E["口诀"] == no]
    if not len(g):
        return
    wk = g[g["年"] <= 2022]
    st = g[g["年"] >= 2023]
    print("\n" + "=" * 20, f"{no} 时代稳定腿(弱段{len(wk)}笔/强段{len(st)}笔)", "=" * 20)
    print(f"  无腿: 弱 {stat(wk)} | 强 {stat(st)}")
    if len(wk):
        print(f"  弱市段逐票: ")
        for _, r in wk.sort_values("买入日").iterrows():
            mb = f"b{r['N']}"
            print(f"    {r['买入日']} {r['代码']} {r['名称']:<8s} E3={r['E3%']:+6.1f} "
                  f"{mb}开{r[f'{mb}开盘%']:+6.2f} {mb}换{r[f'{mb}换手%']:6.2f} "
                  f"今开{r['买入开盘%']:+5.2f} 地基{r['地基涨跌%']:+5.1f} "
                  f"前波{r['前波60日最高板']} 距新高{r['距60日新高%']:7.1f} "
                  f"锚{r['锚位%']} 首20{r['首20日涨幅%']:6.1f} 家数{r['昨日4板+家数']}")
    for lname, lf in LEG_DEFS.items():
        gw = wk[lf(wk)]
        gs = st[lf(st)]
        if not len(gw):
            continue
        print(f"  +{lname:<10s}: 弱 {stat(gw)} | 强 {stat(gs)}")


def main() -> None:
    E = pd.read_pickle("/tmp/relay23_tagged.pkl")
    E["末板换"] = E.apply(lambda r: r["b2换手%"] if r["N"] == 2 else r["b3换手%"], axis=1)

    # 强市条逐条: 弱市段有毒的优先(B1/B2/B3/C3/A1), C1/A2/C2也看
    for no in ("B1", "B2", "B3", "C3", "A1", "A2", "C1", "C2"):
        era_leg_report(E, no)

    print("\n\n" + "=" * 20, "K系跨时代复核", "=" * 20)
    for no in ("K5", "K3", "K4", "K9", "K2"):
        g = E[E["口诀"] == no]
        wk = g[g["年"] <= 2022]
        st = g[g["年"] >= 2023]
        print(f"  {no}: 弱 {stat(wk)} | 强 {stat(st)}")
        if len(st):
            print(f"     强市段分年: {yearly(st)}")


if __name__ == "__main__":
    main()
