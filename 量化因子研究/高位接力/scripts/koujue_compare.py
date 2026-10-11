# -*- coding: utf-8 -*-
"""口诀对比工作台: 把「和主人一起看出口诀腿」的研究动作脚本化。

研究动作的原型(先手小阳腿/前10日腿/姿态尺的诞生过程):
  拿两组票(好票 vs 差票) → 把地基及其他多维特征全部数据化 → 逐一对比分布
  → 差异大的维度=候选判别腿 → 逐票点名给主人看K线定故事。

对照预设:
  winvloss   命中内赚票(E3≥0) vs 亏票(E3<0)      —— 找「剔毒腿」(差票过滤)
  hitvsmiss  口诀命中 vs 全池未命中               —— 找「收编腿」(漏网肥肉)
  meatgap    大肉漏网(E3≥10未命中) vs 命中票      —— 漏网大肉长什么样
  strongweak 强市组命中 vs 弱市组命中             —— 两组形态差异(时代画像)

无未来函数硬约束: 特征白名单只用 T-1收盘+9:25竞价+链上历史板已知列,
E3/次日/持有/封住(收盘态)等结果列一律排除。
"""
import math

import pandas as pd

from alphaagent.server.services.high_relay.pool import tag_scheme, tag_weak

pd.set_option("display.width", 250)

PKL = "/tmp/relay23_tagged.pkl"
CSV = "量化因子研究/高位接力/四进五全量明细.csv"
MIN_CELL = 5      # 档内某侧最小票数(低于不列)
MIN_GAP = 0.15    # 占比差≥15pct 才算判别档

# ---- 特征白名单与档位化(全部事前可知) ----
OPEN_COLS = ["b1开盘%", "b2开盘%", "b3开盘%", "b4开盘%", "b5开盘%", "买入开盘%"]
OPEN_BINS = [(-99, 0, "低开"), (0, 3, "贴零"), (3, 7, "温开"), (7, 9.5, "强开"),
             (9.5, 99, "一字")]
TURN_COLS = ["b1换手%", "b2换手%", "b3换手%", "b4换手%"]
TURN_BINS = [(0, 5, "<5"), (5, 10, "5~10"), (10, 20, "10~20"), (20, 30, "20~30"),
             (30, 999, ">30")]
# 注: 「买入换手%」收盘才知道=未来函数, 不入判定白名单(对比结果只作盘后信息层);
# 「买入量比」9:25竞价可知, 进环境四分位档。
PCT_COLS = ["地基涨跌%", "首3日涨幅%", "首10日涨幅%", "首20日涨幅%", "距60日新高%",
            "地基距MA20%", "距MA10%", "锚位%", "锚距"]
PCT_BINS = [(-99, -5, "<-5"), (-5, 0, "-5~0"), (0, 3, "0~3"), (3, 10, "3~10"),
            (10, 999, "≥10")]
WAVE_COLS = ["前波60日最高板", "前波120日最高板", "前板高度"]
WAVE_BINS = [(-0.5, 0.5, "=0"), (0.5, 2.5, "1~2"), (2.5, 4.5, "3~4"), (4.5, 99, "≥5")]
ENV_COLS = ["昨日涨停家数", "买入日涨停家数", "昨日最高板", "昨日4板+家数", "买入量比"]
ENUM_COLS = ["阴阳", "地基阴阳", "地基姿态", "b1板型", "b2板型", "b3板型", "N", "链", "顶格",
             "换手梯度", "四组"]


def nn(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return v


def tag_both(row):
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


def bin_value(col, v, quantiles):
    """白名单列 → 档位标签; 无档返回 None。"""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    for cols, bins in ((OPEN_COLS, OPEN_BINS), (TURN_COLS, TURN_BINS),
                       (PCT_COLS, PCT_BINS), (WAVE_COLS, WAVE_BINS)):
        if col in cols:
            for lo, hi, nm in bins:
                if lo <= v < hi:
                    return nm
            return None
    if col in ENV_COLS:
        for lo, hi, nm in quantiles.get(col, []):
            if lo <= v < hi:
                return nm
        return None
    if col in ENUM_COLS:
        return str(v)
    return None


def build_quantiles(E):
    """环境列用四分位档(数据定档, 主人方法论「长度阈值数据定」)。"""
    qs = {}
    for col in ENV_COLS:
        v = pd.to_numeric(E[col], errors="coerce").dropna()
        if len(v) < 50:
            continue
        cuts = v.quantile([0.25, 0.5, 0.75]).tolist()
        qs[col] = [(-1e9, cuts[0], "Q1"), (cuts[0], cuts[1], "Q2"),
                   (cuts[1], cuts[2], "Q3"), (cuts[2], 1e9, "Q4")]
    return qs


def compare(E, A, B, label, quantiles, name_a="A", name_b="B", top_dims=12):
    """两组票全维对比: 每维每档占比差, 判别力排行+富集档点名。"""
    na, nb = len(A), len(B)
    print(f"\n{'=' * 24} {label}: {name_a}{na}笔 vs {name_b}{nb}笔 {'=' * 24}")
    cols = (OPEN_COLS + TURN_COLS + PCT_COLS + WAVE_COLS + ENV_COLS + ENUM_COLS)
    rows = []
    for col in cols:
        if col not in E.columns:
            continue
        va = E.loc[A.index, col].map(lambda x: bin_value(col, x, quantiles))
        vb = E.loc[B.index, col].map(lambda x: bin_value(col, x, quantiles))
        pa, pb = va.value_counts(normalize=True), vb.value_counts(normalize=True)
        ca, cb = va.value_counts(), vb.value_counts()
        power = 0.0
        for nm in sorted(set(pa.index) | set(pb.index), key=str):
            fa, fb = pa.get(nm, 0.0), pb.get(nm, 0.0)
            gap = fa - fb
            if ca.get(nm, 0) >= MIN_CELL and cb.get(nm, 0) >= MIN_CELL and abs(gap) >= MIN_GAP:
                rows.append({"维": col, "档": nm, f"{name_a}%": f"{fa:.0%}",
                             f"{name_b}%": f"{fb:.0%}", "差": gap,
                             "向": name_a if gap > 0 else name_b})
            power += abs(gap) * (1 if (ca.get(nm, 0) >= MIN_CELL and cb.get(nm, 0) >= MIN_CELL) else 0)
        # 单维判别力存入首档行
        if rows and rows[-1]["维"] == col:
            rows[-1]["判别力"] = power
        else:
            rows.append({"维": col, "档": "(无差异档)", "判别力": power})
    R = pd.DataFrame(rows)
    if R.empty:
        print("无显著判别档")
        return
    dim_pow = R.groupby("维")["判别力"].max().sort_values(ascending=False)
    print(f"维度判别力排行(Top{top_dims}, Σ|占比差|):")
    strong_dims = dim_pow.head(top_dims).index.tolist()
    for d in dim_pow.head(top_dims).index:
        sub = R[(R["维"] == d) & (R["档"] != "(无差异档)")]
        if len(sub) == 0:
            continue
        tops = sub.reindex(sub["差"].abs().sort_values(ascending=False).index).head(3)
        seg = " | ".join(f"{r['档']}: {r[f'{name_a}%']}vs{r[f'{name_b}%']}({r['差']:+.0%})"
                         for _, r in tops.iterrows())
        print(f"  {d:<12s} 判别力{dim_pow[d]:.2f}  {seg}")
    # 富集档逐票点名: 判别力最强维度的最大差档
    best_dim = dim_pow.index[0]
    sub = R[(R["维"] == best_dim) & (R["档"] != "(无差异档)")]
    if len(sub):
        r0 = sub.reindex(sub["差"].abs().sort_values(ascending=False).index).iloc[0]
        bin_label, side = r0["档"], (name_a if r0["差"] > 0 else name_b)
        print(f"\n最强档[{best_dim}={bin_label}] 偏{side}; 该档两组票点名(看票定故事):")
        va = E.loc[A.index, best_dim].map(lambda x: bin_value(best_dim, x, quantiles))
        vb = E.loc[B.index, best_dim].map(lambda x: bin_value(best_dim, x, quantiles))
        for nm_, idx in ((f"{name_a}组", va[va == bin_label].index),
                         (f"{name_b}组", vb[vb == bin_label].index)):
            got = E.loc[idx].sort_values("E3%", ascending=False)
            tail = got.head(6) if side == nm_[:len(name_a)] or True else got.tail(6)
            names = " ".join(f"{str(r['买入日'])[:10]}{str(r['名称'])[:5]}({r['E3%']:+.0f})"
                             for _, r in tail.iterrows())
            print(f"  {nm_}({len(got)}笔): {names}")


def main() -> None:
    try:
        E = pd.read_pickle(PKL)
    except FileNotFoundError:
        E = pd.read_csv(CSV, dtype={"代码": str})
    E = E[E["E3%"].notna()].copy()
    tags = E.apply(tag_both, axis=1, result_type="expand")
    E["s_no"], E["w_no"] = tags[0], tags[1]
    quantiles = build_quantiles(E)
    hit = E[E["s_no"].notna() | E["w_no"].notna()]
    miss = E[~(E["s_no"].notna() | E["w_no"].notna())]

    compare(E, hit[hit["E3%"] >= 0], hit[hit["E3%"] < 0],
            "winvloss 命中内赚vs亏(找剔毒腿)", quantiles, "赚", "亏")
    compare(E, hit, miss, "hitvsmiss 命中vs未命中(找收编腿)", quantiles, "命中", "未中")
    compare(E, miss[miss["E3%"] >= 10], hit,
            "meatgap 大肉漏网vs命中(漏网肉画像)", quantiles, "漏网肉", "命中")
    compare(E, E[E["s_no"].notna()], E[E["w_no"].notna()],
            "strongweak 强市组vs弱市组(时代画像)", quantiles, "强市", "弱市")


main()
