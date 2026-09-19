# -*- coding: utf-8 -*-
"""高位接力 · 稳健性与过拟合检验（第八遍）。

对五个入围格子 + 并集做五道检验:
1. 搜索级零假设: 结果在同年份内打乱后跑完全相同的筛选流程, 看假数据能挖出几个
   「分年全正」格子(每格重复25次) —— 检验筛选流程本身有没有真区分能力
2. 单格置换检验: 固定格子条件, 同年份内打乱结果2000次, p=出现「胜率≥实测 且
   分年全正」的比例
3. Bootstrap: 持有到断板均值与胜率的5%~95%置信区间, P(均值<=0)
4. 去尾部: 拿掉最好的3笔后, 均值和分年是否还活着
5. 留一年/留一月: 拿掉任何一年或一个月, 并集收益是否还为正
"""
import itertools
import os

import numpy as np
import pandas as pd
from scipy.stats import binomtest

pd.set_option("display.width", 340)
CSV = "/root/project/ai/vnpy/量化因子研究/高位接力/全量明细.csv"
OUTD = "/root/project/ai/vnpy/量化因子研究/高位接力/汇总"
GROUPS = ["二接三阴", "二接三阳", "三接四阴", "三接四阳"]
YEARS = ["2023", "2024", "2025", "2026"]
rng = np.random.default_rng(42)

DIMS = [
    ("买入开盘%", [-99, 0, 2, 4, 6, 8, 9.5, 99]),
    ("距60日新高%", [-99, -25, -15, -8, -3, 0.01]),
    ("距60日低点%", [-1, 10, 20, 35, 60, 999]),
    ("地基涨跌%", [-99, -5, -3, 0, 3, 99]),
    ("地基前20日涨幅%", [-99, 0, 15, 30, 999]),
    ("前波60日最高板", [-1, 0, 2, 3, 99]),
    ("前波120日最高板", [-1, 0, 2, 3, 99]),
    ("距前波末板", [-2, -0.5, 5, 10, 20, 9999]),
    ("昨日涨停家数", [-1, 30, 50, 80, 9999]),
    ("b1开盘%", [-99, 0, 3, 6, 9.5, 99]),
    ("b2开盘%", [-99, 0, 3, 6, 9.5, 99]),
    ("b1换手%", [-1, 3, 6, 10, 15, 99]),
    ("b2换手%", [-1, 3, 6, 10, 15, 99]),
    ("竞价梯度", [-99, -5, -2, 0, 2, 5, 99]),
    ("二板梯度", [-99, -5, -2, 0, 2, 5, 99]),
    ("换手梯度", [-99, -5, -2, 0, 2, 5, 99]),
    ("链一字数", [-1, 0, 1, 9]),
    ("链开口数", [-1, 0, 1, 2, 9]),
    ("均线归并", None),
    ("b1板型", None),
    ("b2板型", None),
    ("链组合", None),
]

CELLS = {
    "1_二接三阴_二板高开6-9.5_换手微增0-2": lambda E: (E["四组"] == "二接三阴")
        & E["b2开盘%"].between(6, 9.5, inclusive="left")
        & (E["换手梯度"].between(0, 2, inclusive="left")),
    "2_二接三阳_地基距新高2-9_二板低开": lambda E: (E["四组"] == "二接三阳")
        & E["距60日新高%"].between(-9, -2, inclusive="left") & (E["b2开盘%"] < 0),
    "3_三接四阴_前波120有3板_二板缩量5点": lambda E: (E["四组"] == "三接四阴")
        & (E["前波120日最高板"] >= 3) & (E["换手梯度"] < -5),
    "4_三接四阴_首板下影_二板实体": lambda E: (E["四组"] == "三接四阴")
        & (E["b1板型"] == "下影") & (E["b2板型"] == "实体"),
    "5_三接四阳_地基8-15_均线不齐_无前波": lambda E: (E["四组"] == "三接四阳")
        & E["距60日新高%"].between(-15, -8, inclusive="left")
        & (~E["均线"].isin(["+++", "-++", "+--"])) & (E["前波60日最高板"] == 0),
}


def load():
    E = pd.read_csv(CSV)
    E = E[~E["未完"]].copy()
    E["年"] = E["年"].astype(str)
    E["月"] = E["月"].astype(str)
    E["胜"] = (E["次日收%"] > 0).astype(int)
    E["均线归并"] = np.where(E["均线"] == "+++", "全多头",
                    np.where(E["均线"].isin(["-++", "+--"]), "纠缠", "其他"))
    E["距前波末板"] = E["距前波末板"].fillna(-1)
    E["链组合"] = E["b1板型"] + "→" + E["b2板型"]
    for k in (1, 2, 3):
        E[f"b{k}一字"] = (E[f"b{k}板型"] == "一字").astype(int)
        E[f"b{k}开口"] = (E[f"b{k}板型"] == "下影").astype(int)
    E["链一字数"] = E["b1一字"] + E["b2一字"] + np.where(E["N"] >= 3, E["b3一字"], 0)
    E["链开口数"] = E["b1开口"] + E["b2开口"] + np.where(E["N"] >= 3, E["b3开口"], 0)
    E["竞价梯度"] = E["买入开盘%"] - E["b2开盘%"]
    E["二板梯度"] = E["b2开盘%"] - E["b1开盘%"]
    E["换手梯度"] = E["b2换手%"] - E["b1换手%"]
    return E


def bin_codes(s, col, edges):
    """返回整数编码数组(NaN=-1)。"""
    if edges is not None:
        return pd.cut(s[col], edges, right=False).cat.codes.to_numpy()
    return pd.Categorical(s[col].fillna("(无)")).codes


def allpos_count(win, ret, yr, masks, min_n, year_codes):
    """一组候选掩码下, 分年全正的组合数。win/ret/yr为numpy数组。"""
    cnt = 0
    for m in masks:
        n = int(m.sum())
        if n < min_n:
            continue
        ok, ny = True, 0
        for yc in year_codes:
            my = m & (yr == yc)
            if my.sum() > 0:
                ny += 1
                if ret[my].mean() <= 0:
                    ok = False
                    break
        if ok and ny >= 3:
            cnt += 1
    return cnt


def search_pipeline(win, ret, yr, bin_list, year_codes):
    """完整筛选流程(原子→两两/三三→分年全正计数), 输入输出全numpy。"""
    n_pool = len(win)
    pool_wr = win.mean()
    atom_masks = []
    for codes in bin_list:
        for c in np.unique(codes):
            if c < 0:
                continue
            m = codes == c
            if m.sum() >= 20 and win[m].mean() > pool_wr + 0.03:
                atom_masks.append(m)
    c2 = list(itertools.combinations(range(len(atom_masks)), 2))
    c3 = list(itertools.combinations(range(len(atom_masks)), 3))
    masks2 = [atom_masks[i] & atom_masks[j] for i, j in c2]
    masks3 = [atom_masks[i] & atom_masks[j] & atom_masks[k] for i, j, k in c3]
    return (allpos_count(win, ret, yr, masks2, 20, year_codes)
            + allpos_count(win, ret, yr, masks3, 15, year_codes))


def shuffle_within_year(values, yr, year_codes, gen):
    out = values.copy()
    for yc in year_codes:
        idx = np.where(yr == yc)[0]
        out[idx] = values[idx][gen.permutation(len(idx))]
    return out


def main():
    E = load()
    lines = []

    # ============ 检验1: 搜索级零假设 ============
    lines.append("## 检验1 搜索级零假设（同年份内打乱结果, 跑相同筛选流程, 25次）\n")
    year_codes = np.unique(E["年"].to_numpy())
    real_counts = {"二接三阴": 9, "二接三阳": 2, "三接四阴": 18, "三接四阳": 3}
    for gname in GROUPS:
        sub = E[E["四组"] == gname]
        win = sub["胜"].to_numpy(float)
        ret = sub["持有到断板%"].to_numpy(float)
        yr = sub["年"].to_numpy()
        yc = np.unique(yr)
        bin_list = [bin_codes(sub, col, edges) for col, edges in DIMS]
        nulls = []
        for b in range(25):
            wr_s = shuffle_within_year(win, yr, yc, rng)
            rt_s = shuffle_within_year(ret, yr, yc, rng)
            nulls.append(search_pipeline(wr_s, rt_s, yr, bin_list, yc))
        nulls = np.array(nulls)
        lines.append(f"- {gname}: 真数据挖出 **{real_counts[gname]}** 个分年全正格子; "
                     f"假数据 25 次挖出 均值{nulls.mean():.1f} / 最多{nulls.max()} 个 "
                     f"(p≈{(nulls >= real_counts[gname]).mean():.2f})")

    # ============ 检验2~4: 单格 ============
    lines.append("\n## 检验2~4 单格: 置换p值 / Bootstrap / 去尾部 / 二项检验\n")
    all_cells = []
    for name, fn in CELLS.items():
        s = E[fn(E)].copy()
        all_cells.append((name, s))
    union = pd.concat([s for _, s in all_cells]).drop_duplicates(subset=["代码", "买入日"])
    all_cells.append(("并集", union))

    for name, s in all_cells:
        gname4 = None
        for g in GROUPS:
            if g in name:
                gname4 = g
        pool = E[E["四组"] == gname4] if gname4 else E
        wr_obs = s["胜"].mean()
        ret_obs = s["持有到断板%"].mean()
        n = len(s)
        # 置换: 在所属组的同年份内打乱
        p_win, p_both = 0, 0
        syr = s["年"].to_numpy()
        syc = np.unique(syr)
        # 格子在年内的样本量结构固定, 从池子里按年抽样同结构的结果
        pool_by_year = {y: pool[pool["年"] == y] for y in syc}
        obs_allpos = all(s[s["年"] == y]["持有到断板%"].mean() > 0 for y in syc)
        for _ in range(2000):
            parts = []
            for y in syc:
                py = pool_by_year[y]
                parts.append(py.sample(n=int((syr == y).sum()), replace=True))
            sim = pd.concat(parts)
            if sim["胜"].mean() >= wr_obs:
                p_win += 1
                if all(sim[sim["年"] == y]["持有到断板%"].mean() > 0 for y in syc):
                    p_both += 1
        # bootstrap
        boot = [s["持有到断板%"].sample(n=n, replace=True).mean() for _ in range(2000)]
        lo, hi = np.percentile(boot, [5, 95])
        p_neg = np.mean(np.array(boot) <= 0)
        bw_lo, bw_hi = np.percentile([s["胜"].sample(n=n, replace=True).mean() for _ in range(2000)], [5, 95])
        # 去尾部
        s_trim = s.sort_values("持有到断板%", ascending=False).iloc[3:]
        trim_ok = all(s_trim[s_trim["年"] == y]["持有到断板%"].mean() > 0
                      for y in YEARS if len(s_trim[s_trim["年"] == y]) > 0)
        # 二项检验 vs 池胜率
        p_binom = binomtest(int(s["胜"].sum()), n, pool["胜"].mean(), alternative="greater").pvalue
        lines.append(f"### {name} (n={n})")
        lines.append(f"- 实测: 胜率{wr_obs*100:.0f}% 持有{ret_obs:+.2f} 分年全正={'是' if obs_allpos else '否'}")
        lines.append(f"- 置换检验(同年份内抽2000次): P(胜率≥实测)={p_win/2000:.3f}  "
                     f"P(胜率≥实测且分年全正)={p_both/2000:.3f}")
        lines.append(f"- Bootstrap: 持有95%区间[{lo:+.2f}, {hi:+.2f}] P(均值≤0)={p_neg:.3f}; "
                     f"胜率区间[{bw_lo*100:.0f}%, {bw_hi*100:.0f}%]")
        lines.append(f"- 去最好3笔: 均值{s_trim['持有到断板%'].mean():+.2f} "
                     f"分年仍全正={'是' if trim_ok else '否'}")
        lines.append(f"- 二项检验(vs池胜率{pool['胜'].mean()*100:.0f}%): p={p_binom:.4f}")

    # ============ 检验5: 留一年/留一月(并集) ============
    lines.append("\n## 检验5 留一年/留一月（并集 172 笔）\n")
    for y in YEARS:
        s2 = union[union["年"] != y]
        lines.append(f"- 去掉{y}: n={len(s2)} 胜率{s2['胜'].mean()*100:.0f}% "
                     f"持有{s2['持有到断板%'].mean():+.2f}")
    mo = union.groupby("月")["持有到断板%"].mean().sort_values()
    lines.append(f"- 按月: {len(mo)}个月, 负月{(mo<0).sum()}个; 最差3个月: "
                 + " ".join(f"{m}{v:+.1f}" for m, v in mo.head(3).items()))
    worst_month = mo.idxmin()
    s3 = union[union["月"] != worst_month]
    lines.append(f"- 去掉最差月({worst_month}): n={len(s3)} 持有{s3['持有到断板%'].mean():+.2f}")

    text = "\n".join(lines)
    print(text)
    with open(f"{OUTD}/稳健性检验.md", "w", encoding="utf-8") as f:
        f.write("# 高位接力 · 稳健性与过拟合检验（2026-09-19 第八遍）\n\n" + text + "\n")


if __name__ == "__main__":
    main()
