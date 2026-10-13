# -*- coding: utf-8 -*-
"""二接三/三接四 · P1 基线与覆盖审计(宿主机: uv run python relay23_audit.py)。

数据: 四进五全量明细.csv(2020-01 起, N=2/3 子集, E3 产品口径)。
打标: 产品真判定 tag_scheme(强市八条)/tag_weak(弱市K系), 零手搓。
输出:
  ① 全池基线(板位×时代×分年×阴阳)
  ② 14条口诀全时段成绩 + 时代交叉(强市条在20-22 / K系在23+)
  ③ 覆盖审计: 大肉(E3≥+10)命中分布 / 漏网清单
  ④ 大亏(E3≤-10)口诀归属分布
  ⑤ 口诀重叠审计(同票双命中)
"""
import math

import pandas as pd

from alphaagent.server.services.high_relay.pool import tag_scheme, tag_weak

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 240)


def nn(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def load() -> pd.DataFrame:
    E = pd.read_csv(f"{ROOT}/四进五全量明细.csv", dtype={"代码": str})
    E = E[(~E["顶格"].astype(bool)) & (~E["未完"].astype(bool))].copy()
    E["年"] = E["年"].astype(int)
    E["时代"] = E["年"].map(lambda y: "弱20-22" if y <= 2022 else "强23+")
    return E[E["N"].isin((2, 3))].copy()


def tag_row(row) -> str:
    """强市组优先,再弱市组(与动态组纪律无关——这里只问'形态命中谁')。"""
    g4 = row["四组"]
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


def tag_both(row) -> tuple[str, str]:
    """两组独立打标(重叠审计用)。"""
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
    return (str(s["no"]) if s is not None else "—",
            str(w["no"]) if w is not None else "—")


def line(g: pd.DataFrame) -> str:
    e3 = g["E3%"].dropna()
    if not len(g):
        return "0笔"
    trim = e3.sort_values().iloc[:-3] if len(e3) > 3 else e3
    return (f"n={len(g):4d} E3均={e3.mean():+6.2f} 中位={e3.median():+6.2f} "
            f"胜={(e3 > 0).mean() * 100:4.0f}% 剔Top3={trim.mean():+6.2f} "
            f"大亏={(e3 <= -10).sum():2d}笔")


def yearly(g: pd.DataFrame) -> str:
    parts = []
    for y, gg in g.groupby("年"):
        e3 = gg["E3%"].dropna()
        parts.append(f"{y}:{len(gg)}笔{e3.mean():+.1f}/{(e3 > 0).mean() * 100:.0f}%")
    return " ".join(parts)


def main() -> None:
    E = load()
    print(f"二接三/三接四 研究池 {len(E)} 笔({E['买入日'].min()[:10]}~{E['买入日'].max()[:10]})\n")

    print("=" * 26, "① 全池基线", "=" * 26)
    for n in (2, 3):
        g = E[E["N"] == n]
        print(f"\n◆ {n}接{n + 1} 全池: {line(g)}")
        for era in ("弱20-22", "强23+"):
            print(f"  {era}: {line(g[g['时代'] == era])}")
        print(f"  分年: {yearly(g)}")
        for y in ("阳", "阴"):
            gy = g[g["阴阳"] == y]
            print(f"  {y}地基: {line(gy)}")

    print("\n" + "=" * 26, "② 口诀打标(强市优先)全时段成绩", "=" * 26)
    E["口诀"] = E.apply(tag_row, axis=1)
    for no in ("A1", "A2", "B1", "B2", "B3", "C1", "C2", "C3",
               "K2", "K4", "K5", "K9", "K3", "—"):
        g = E[E["口诀"] == no]
        if not len(g):
            print(f"{no:3s}: 0笔")
            continue
        gw = g[g["时代"] == "弱20-22"]
        gs = g[g["时代"] == "强23+"]
        print(f"\n◆ {no}: {line(g)}")
        print(f"   弱20-22: {line(gw)}")
        print(f"   强23+  : {line(gs)}")
        print(f"   分年: {yearly(g)}")

    print("\n" + "=" * 26, "③ 大肉覆盖审计(E3≥+10)", "=" * 26)
    big = E[E["E3%"] >= 10]
    print(f"大肉总数 {len(big)} 笔(占池 {len(big) / len(E) * 100:.0f}%)")
    cov = big["口诀"].value_counts()
    for no, c in cov.items():
        g = big[big["口诀"] == no]
        print(f"  {no:3s}: {c:4d} 笔({c / len(big) * 100:4.1f}%) E3均={g['E3%'].mean():+.2f}")
    missed = big[big["口诀"] == "—"]
    print(f"\n漏网大肉 {len(missed)} 笔, E3均={missed['E3%'].mean():+.2f}")
    print("漏网大肉 分时代:", missed["时代"].value_counts().to_dict(),
          " 分板位:", missed["N"].value_counts().to_dict())

    print("\n" + "=" * 26, "④ 大亏归属(E3≤-10)", "=" * 26)
    loss = E[E["E3%"] <= -10]
    print(f"大亏总数 {len(loss)} 笔(占池 {len(loss) / len(E) * 100:.0f}%)")
    for no, c in loss["口诀"].value_counts().items():
        print(f"  {no:3s}: {c:3d} 笔")

    print("\n" + "=" * 26, "⑤ 两组重叠审计(同票双命中)", "=" * 26)
    both = E.apply(tag_both, axis=1, result_type="expand")
    both.columns = ["强", "弱"]
    overlap = both[(both["强"] != "—") & (both["弱"] != "—")]
    print(f"强市命中 {(both['强'] != '—').sum()} 笔 | 弱市命中 {(both['弱'] != '—').sum()} 笔 | "
          f"双命中 {len(overlap)} 笔")
    if len(overlap):
        print(overlap.value_counts().to_string())

    E.to_pickle("/tmp/relay23_tagged.pkl")
    print("\n已存 /tmp/relay23_tagged.pkl(带口诀列)")


main()
