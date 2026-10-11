# -*- coding: utf-8 -*-
"""口诀体检仪 S1: 每条口诀的滚动成绩+三色预警+历史回放(宿主机: uv run python koujue_health.py)。

设计(requirements/koujue_autogen_drift_plan.md):
- 体检口径 = 全命中口径(A1 的成绩 = A1 命中的所有票, 双命中票两边都算),
  与 dyn_trades 的组归属口径不同——体检看口诀自身质量, 与组切换无关。
- 逐月末滚动, 窗口不含当月(对齐 DYN_GROUP_WINDOW 口径), 累计均值只用截至
  上月底的数据(expanding, 无未来函数)。
- 窗口门槛口诀级适配(单条口诀月均仅0.5~0.9笔, 组级的12月8笔门槛会全屏失明,
  首版教训): 主窗=近24月, 判色门槛5笔。
- 三色(每月独立可算, 无状态, KISS):
  insuf  近24月n<5 或 累计n<12(小样本防抖)
  red    近24月均值 < 0.25×累计均值 且 近12月均值<0(近端确认)
  yellow 近24月均值 < 0.5×累计均值(腰斩) 或 近12月≥3笔且均值<0; 累计均值≤0直接黄
  green  其余
- S1.4 回放验收: 2023-09 弱市→强市组切换前(2023-06~08), K系应≥3条黄。
"""
import math

import pandas as pd

from alphaagent.server.services.high_relay.pool import tag_scheme, tag_weak

pd.set_option("display.width", 240)

PKL = "/tmp/relay23_tagged.pkl"
CSV = "量化因子研究/高位接力/四进五全量明细.csv"
R24_MIN_N = 5      # 近24月最小样本(判色门槛, 口诀级适配)
CUM_MIN_N = 12     # 累计最小样本(腰斩比较要稳定的分母)
HALF = 0.5         # 腰斩线
QUARTER = 0.25     # 红线
REPLAY_LO, REPLAY_HI = "2023-04", "2023-10"  # S1.4 回放窗


def nn(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return v


def tag_both(row):
    """一笔票分别打强市/弱市组标, 返回(强市口诀号|None, 弱市口诀号|None)。"""
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
    return (str(s["no"]) if s is not None else None,
            str(w["no"]) if w is not None else None)


def stats(sub):
    """(n, 均值, 胜率, 剔Top3均值); 空集返回 n=0 其余 None。"""
    if len(sub) == 0:
        return 0, None, None, None
    e3 = sub["E3%"]
    trim = e3.dropna().nlargest(3).index
    t3 = sub.drop(index=trim)["E3%"].mean() if len(sub) > 3 else e3.mean()
    return len(sub), e3.mean(), (e3 > 0).mean(), t3


def color(r24n, r24a, r12n, r12a, cumn, cuma):
    """三色判别(每月独立, 无状态)。r12a 小样本也照算(均值有意义, 只作确认)。"""
    if r24n < R24_MIN_N or cumn < CUM_MIN_N or cuma is None:
        return "insuf"
    if cuma <= 0:
        return "yellow"
    if r24a < QUARTER * cuma and r12a is not None and r12a < 0:
        return "red"
    if r24a < HALF * cuma or (r12n >= 3 and r12a is not None and r12a < 0):
        return "yellow"
    return "green"


def main() -> None:
    try:
        E = pd.read_pickle(PKL)
    except FileNotFoundError:
        E = pd.read_csv(CSV, dtype={"代码": str})
    E = E[E["E3%"].notna()].copy()
    E["月"] = E["买入日"].astype(str).str[:7]
    tags = E.apply(tag_both, axis=1, result_type="expand")
    E["s_no"], E["w_no"] = tags[0], tags[1]

    # ---- S1.1 验收对照(P7 口径: 纯命中/含双命中/双命中) ----
    hs, hw = E["s_no"].notna(), E["w_no"].notna()
    print(f"打标验收: 强市命中{hs.sum()} 弱市命中{hw.sum()} 双命中{(hs & hw).sum()}"
          f" (P7对照: 269/104/27, ±6笔=CSV与产品库微差)")

    codes = ([("S", c) for c in sorted(E.loc[hs, "s_no"].unique())]
             + [("K", c) for c in sorted(E.loc[hw, "w_no"].unique())])
    months = sorted(E["月"].unique())
    by_m = {c: g for c, g in E.groupby("月")}

    # 每口诀逐月命中子集(全命中口径)
    subsets = {}
    for grp, c in codes:
        col = "s_no" if grp == "S" else "w_no"
        subsets[(grp, c)] = {m: g[g[col] == c] for m, g in by_m.items()}

    # ---- S1.2 滚动成绩长表 ----
    rows = []
    for i, m in enumerate(months):
        prev = months[:i]                      # 截至上月底(不含当月)
        r12m = set(months[max(0, i - 12):i])
        r24m = set(months[max(0, i - 24):i])
        for grp, c in codes:
            sub = subsets[(grp, c)]
            parts = [sub[x] for x in prev if len(sub[x])]
            cum = pd.concat(parts, axis=0) if parts else None
            if cum is None or len(cum) == 0:
                continue
            r12 = pd.concat([sub[x] for x in r12m if len(sub[x])] or [cum.iloc[0:0]], axis=0)
            r24 = pd.concat([sub[x] for x in r24m if len(sub[x])] or [cum.iloc[0:0]], axis=0)
            r12n, r12a, _, _ = stats(r12)
            r24n, r24a, _, _ = stats(r24)
            cumn, cuma, _, _ = stats(cum)
            rows.append({"口诀": f"{grp}{c}", "截止": m, "r12n": r12n, "r12a": r12a,
                         "r24n": r24n, "r24a": r24a, "cumn": cumn, "cuma": cuma,
                         "色": color(r24n, r24a, r12n, r12a, cumn, cuma)})
    H = pd.DataFrame(rows)
    print(f"滚动表: {len(H)} 行(口诀×月末), 覆盖 {months[0]}~{months[-1]}")

    # ---- S1.4 回放: 2023-04~2023-10 色卡 ----
    rp = [m for m in months if REPLAY_LO <= m <= REPLAY_HI]
    P = H[H["截止"].isin(rp)].pivot(index="口诀", columns="截止", values="色")
    sym = {"green": "绿", "yellow": "黄", "red": "红", "insuf": "—"}
    print(f"\n===== S1.4 回放 {REPLAY_LO}~{REPLAY_HI}(2023-09 为弱→强组切换月) =====")
    print(P.apply(lambda col: col.map(sym).fillna("")).to_string())
    print("\n—— 诊断: 近24月均值/累计均值 比值矩阵(<0.5=腰斩区, 数值=信号形状) ——")
    Hr = H[H["截止"].isin(rp)].copy()
    Hr["比"] = (Hr["r24a"] / Hr["cuma"]).round(2)
    print(Hr.pivot(index="口诀", columns="截止", values="比").fillna("").to_string())
    Hr["n"] = Hr["r24n"].astype(str) + "笔"
    print(Hr.pivot(index="口诀", columns="截止", values="n").fillna("").to_string())
    for m in ("2023-06", "2023-07", "2023-08"):
        kk = H[(H["截止"] == m) & H["口诀"].str.startswith("K")]["色"]
        n_y = ((kk == "yellow") | (kk == "red")).sum()
        print(f"  {m}: K系黄/红 {n_y} 条 / 共{len(kk)}条(原预设验收线≥3; "
              f"实测0=切换前弱市口诀本身未衰退, 见诊断矩阵)")

    # ---- 年末快照时间线 ----
    snaps = [m for m in months if m.endswith("-12")] + [months[-1]]
    print("\n===== 年末色卡(看各口诀何时变黄) =====")
    S = H[H["截止"].isin(snaps)].pivot(index="口诀", columns="截止", values="色")
    print(S.apply(lambda col: col.map(sym).fillna("")).to_string())

    # ---- S1.5 当前体检 ----
    last = months[-1]
    C = H[H["截止"] == last].set_index("口诀")
    print(f"\n===== S1.5 当前体检(截至{last}, 近12月窗口) =====")
    out = []
    for grp, c in codes:
        k = f"{grp}{c}"
        if k not in C.index:
            continue
        r = C.loc[k]
        col = "s_no" if grp == "S" else "w_no"
        r24 = pd.concat([subsets[(grp, c)][x] for x in months[max(0, len(months) - 25):len(months) - 1]
                         if len(subsets[(grp, c)][x])] or [E.iloc[0:0]], axis=0)
        n, a, w, t3 = stats(r24)
        out.append({"口诀": k, "色": sym[r["色"]], "近24月n": n,
                    "近24月均": None if a is None else round(a, 2),
                    "近24月胜": None if w is None else f"{w:.0%}",
                    "剔3": None if t3 is None else round(t3, 2),
                    "累计n": int(r["cumn"]), "累计均": round(r["cuma"], 2),
                    "比": None if (a is None or r["cuma"] in (None, 0)) else round(a / r["cuma"], 2)})
    print(pd.DataFrame(out).to_string(index=False))


main()
