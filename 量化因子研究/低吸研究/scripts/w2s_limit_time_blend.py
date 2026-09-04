# -*- coding: utf-8 -*-
"""N型补涨打板 · 首触板时间「综合区间」——全量基线×白名单出手收缩合成.

主人2026-09-04要求:全量口径(时间效应,2841笔)与白名单出手口径(选票效应,246笔)
结合,得最综合的区间.

方法=经验贝叶斯收缩: 每格综合分 = (n_act*ret_act + K*ret_all)/(n_act+K)
  n_act大(出手样本厚)→信任出手实绩; n_act小→回退全量基线.
  K=10 主报告, K=6/15 稳健性对照(主/次是否翻格).
好票率同法收缩. 两份明细本地CSV, 纯pandas无DB依赖.
"""
import pandas as pd

BIG4 = {"yin2": "2板阴", "yang2a": "2板阳", "yang2b": "2板阳", "yin4": "4+阴", "yang4": "4+阳"}
EDGE = ["09:45", "10:00", "10:15", "10:30", "10:45", "11:00", "11:15", "11:30",
        "13:15", "13:30", "13:45", "14:00", "14:15", "14:30", "14:45", "15:00"]
PREV = {EDGE[0]: "09:30"}
for a, b in zip(EDGE, EDGE[1:]):
    PREV[b] = a
PREV["13:15"] = "13:00"

BASE = "/root/project/ai/vnpy/量化因子研究/低吸研究/N型补涨打板"


def interval(t: str) -> str:
    return f"{PREV.get(t, '?')}~{t}"


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"vt_symbol": str}).dropna(subset=["touch"])
    df = df[df["touch"].isin(EDGE)].copy()
    df["big4"] = df["group_key"].map(BIG4)
    return df


def agg(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    g = df.groupby(["big4", "touch"])["ret_bw"]
    out = g.agg(**{f"n_{prefix}": "count", f"ret_{prefix}": "mean",
                   f"win_{prefix}": lambda s: (s > 0).mean()})
    return out.reset_index()


def main() -> None:
    allm = load(f"{BASE}/首次触板时间-全量.csv")      # 全量2841(时间效应)
    act = load(f"{BASE}/首次触板时间.csv")            # 出手246(选票效应)
    A, B = agg(allm, "all"), agg(act, "act")
    m = A.merge(B, on=["big4", "touch"], how="left")

    for K in (6, 10, 15):
        w = m["n_act"].fillna(0) / (m["n_act"].fillna(0) + K)
        m[f"score{K}"] = w * m["ret_act"].fillna(0) + (1 - w) * m["ret_all"]
        # 出手格缺样本时纯全量; n_act=NaN填0避免传染
        m.loc[m["n_act"].isna(), f"score{K}"] = m["ret_all"]
        ww = m["n_act"].fillna(0) / (m["n_act"].fillna(0) + K)
        m[f"win{K}"] = ww * m["win_act"].fillna(0) + (1 - ww) * m["win_all"]
        m.loc[m["n_act"].isna(), f"win{K}"] = m["win_all"]

    K = 10
    print(f"== 综合(K={K}): 全量基线×出手收缩  格= n全|全量均 → n出|出手均 ⇒ 综合均/综合胜率 ==\n")
    for big in ["2板阴", "2板阳", "4+阴", "4+阳"]:
        g = m[m["big4"] == big].sort_values(f"score{K}", ascending=False)
        print(f"── {big} (按综合分排序) ──")
        for _, r in g.iterrows():
            nact = "-" if pd.isna(r["n_act"]) else int(r["n_act"])
            ract = "  --  " if pd.isna(r["ret_act"]) else f"{r['ret_act']*100:+6.2f}"
            print(f"  {interval(r['touch']):<14} 全量 {int(r['n_all']):>4}|{r['ret_all']*100:+6.2f}%"
                  f"  出手 {nact:>3}|{ract}%  ⇒ 综合 {r[f'score{K}']*100:+6.2f}%/{r[f'win{K}']*100:3.0f}%")
        print()

    print("== K稳健性: 各组主/次区间在 K=6/10/15 下是否一致 ==")
    for big in ["2板阴", "2板阳", "4+阴", "4+阳"]:
        g = m[m["big4"] == big]
        line = f"{big:5s}:"
        for k in (6, 10, 15):
            top = g.nlargest(2, f"score{k}")["touch"].tolist()
            line += f"  K={k}: 主{interval(top[0])} 次{interval(top[1])}"
        print(line)

    # 附加: 综合口径下的尾盘检查(全量毒格在出手收缩后是否仍毒)
    print("\n== 尾盘三段综合分(全量毒格经出手修正后) ==")
    tail = m[m["touch"].isin(["14:15", "14:30", "14:45"])]
    for big, g in tail.groupby("big4"):
        line = f"{big:5s}:"
        for _, r in g.iterrows():
            line += f"  {interval(r['touch'])}={r['score10']*100:+.2f}%"
        print(line)


if __name__ == "__main__":
    main()
