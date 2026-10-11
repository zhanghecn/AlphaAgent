# -*- coding: utf-8 -*-
"""四进五 · P3 终验(宿主机: uv run python relay_4to5_final.py)。

1) 6板位缩量通用性(N=5 × b5换手<5)  2) 一字链切分  3) D2候选2026亏票
4) 增量重叠审计: N=3行用产品 tag_scheme/tag_weak 打标(真判定,零手搓),
   与 N=4 候选(同票前一交易日)对撞——现有口诀持仓已骑走的票占多少。
"""
import math

import pandas as pd

from alphaagent.server.services.high_relay.pool import tag_scheme, tag_weak

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 220)


def nn(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def load() -> pd.DataFrame:
    E = pd.read_csv(f"{ROOT}/四进五全量明细.csv", dtype={"代码": str})
    return E[(~E["顶格"].astype(bool)) & (~E["未完"].astype(bool))].copy()


def stat_line(g: pd.DataFrame) -> str:
    e3 = g["E3%"].dropna()
    if not len(g):
        return "0笔"
    trim = e3.sort_values().iloc[:-3] if len(e3) > 3 else e3
    return (f"n={len(g)} 月均={len(g) / 82:.2f} E3均={e3.mean():+.2f} 中位={e3.median():+.2f} "
            f"胜率={(e3 > 0).mean() * 100:.0f}% 剔Top3={trim.mean():+.2f}")


def tag_n3(row) -> str:
    """给 N=3 行打产品口诀标(强市组+弱市组),返回 'C2'-style 编号或 '—'。"""
    g4 = row["四组"]          # 三接四阳/三接四阴
    s = tag_scheme(g4, nn(row["b1开盘%"]), nn(row["b2开盘%"]), nn(row["b3开盘%"]),
                   auction_pct=nn(row["买入开盘%"]), b2_turn=nn(row["b2换手%"]),
                   b3_turn=nn(row["b3换手%"]), foundation_chg=nn(row["地基涨跌%"]),
                   pre10_pct=nn(row["首10日涨幅%"]), foundation_pose=nn(row["地基姿态"]),
                   anchor_pos=nn(row["锚位%"]), anchor_dist=nn(row["锚距"]))
    if s is not None:
        return str(s["no"])
    w = tag_weak(g4, nn(row["b1开盘%"]), nn(row["b2开盘%"]), nn(row["b3开盘%"]),
                 auction_pct=nn(row["买入开盘%"]), b1_turn=nn(row["b1换手%"]),
                 b2_turn=nn(row["b2换手%"]), b3_turn=nn(row["b3换手%"]),
                 foundation_chg=nn(row["地基涨跌%"]), prev_wave60=nn(row["前波60日最高板"]),
                 dist_h60=nn(row["距60日新高%"]))
    return str(w["no"]) if w is not None else "—"


def main() -> None:
    E = load()

    print("=" * 24, "1) 缩量通用性最后一块: 6板位(N=5)", "=" * 24)
    g5 = E[E["N"] == 5]
    print("N=5 全池:", stat_line(g5))
    print("N=5 × b5换手<5:", stat_line(g5[g5["b5换手%"] < 5]))
    print("N=5 × b5换手<5 × 家数≤3:", stat_line(g5[(g5["b5换手%"] < 5) & (g5["昨日4板+家数"] <= 3)]))

    print("\n" + "=" * 24, "2) 一字链(N=4)", "=" * 24)
    F = E[E["N"] == 4].copy()
    F["链一字数"] = F["链"].fillna("").str.count("一字")
    for k in (0, 1, 2, 3, 4):
        g = F[F["链一字数"] == k]
        if len(g):
            print(f"链含{k}个一字: {stat_line(g)}")
    print("双一字链×b4换手<5:", stat_line(F[(F["链一字数"] >= 2) & (F["b4换手%"] < 5)]))

    print("\n" + "=" * 24, "3) D2(缩量×家数≤3) 2025-26 亏票", "=" * 24)
    d2 = F[(F["b4换手%"] < 5) & (F["昨日4板+家数"] <= 3)]
    for _, r in d2[d2["年"].astype(int) >= 2025].sort_values("E3%").head(8).iterrows():
        print(f"  {r['买入日']} {r['代码']} {r['名称']} E3={r['E3%']:+.1f} 终高{r['最终高度']} "
              f"b4换{r['b4换手%']} 今开{r['买入开盘%']} 阴{r['阴阳']} 链{r['链']}")

    print("\n" + "=" * 24, "4) 增量重叠审计", "=" * 24)
    n3 = E[E["N"] == 3].copy()
    n3["口诀"] = n3.apply(tag_n3, axis=1)
    n3 = n3[["代码", "买入日", "口诀", "封住", "E3%"]].rename(
        columns={"买入日": "四板日", "E3%": "四板E3%"})
    F2 = F.copy()
    # 同票四板日 = 5板买入日之前最近的该票N=3事件日
    F2 = F2.sort_values(["代码", "买入日"])
    hits3 = n3.sort_values(["代码", "四板日"])
    F2["买入日"] = pd.to_datetime(F2["买入日"])
    hits3["四板日"] = pd.to_datetime(hits3["四板日"])
    m = pd.merge_asof(F2.sort_values("买入日"), hits3.sort_values("四板日"),
                      left_on="买入日", right_on="四板日", by="代码",
                      direction="backward",
                      tolerance=pd.Timedelta(days=10))
    m["口诀"] = m["口诀"].fillna("—")
    m["隔日"] = (pd.to_datetime(m["买入日"]) - pd.to_datetime(m["四板日"])).dt.days
    cont = m[(m["隔日"] <= 7)]     # 前一交易日(含节假日跨度的近似上界)
    print(f"N=4 池 {len(F2)} 笔,能对上前一交易日四板事件的 {len(cont)} 笔")
    print("其中前一交易日(四板位)口诀命中分布:")
    print(cont["口诀"].value_counts().to_string())
    for name, mask in [("B1 缩量<5", F["b4换手%"] < 5),
                       ("D2 缩量<5×家数≤3", (F["b4换手%"] < 5) & (F["昨日4板+家数"] <= 3))]:
        F2m = m[[str(c) for c in ["代码", "买入日"]]].copy()
        sel = cont[cont["代码"].isin(F[mask]["代码"])
                   & cont["买入日"].isin(F[mask]["买入日"])]
        # 直接用 mask 对齐:重建键集合(买入日统一转 datetime)
        keys = set(zip(F[mask]["代码"], pd.to_datetime(F[mask]["买入日"])))
        sel = cont[[k in keys for k in zip(cont["代码"], cont["买入日"])]]
        n_hit = (sel["口诀"] != "—").sum()
        print(f"\n{name}: {len(sel)} 笔中 {n_hit} 笔前一交易日已有口诀命中(会被现有持仓骑走), "
              f"占 {n_hit / max(len(sel), 1) * 100:.0f}%")
        if len(sel):
            both = sel[sel["口诀"] != "—"]
            new = sel[sel["口诀"] == "—"]
            e_new = new["E3%"].dropna() if "E3%" in new else pd.Series(dtype=float)
            print(f"  已有口诀的5板票E3均 {both['E3%'].mean() if len(both) else float('nan'):+.2f}"
                  f" | 纯新增票 "
                  f"{new['E3%'].dropna().mean() if 'E3%' in new and len(new) else float('nan'):+.2f}")


main()
