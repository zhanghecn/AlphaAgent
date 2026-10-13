# -*- coding: utf-8 -*-
"""高位接力 · 统一连链完整立方（第二十七遍）：一板×二板×三板(×四板) 整条链一起看。

主人方向: 三板开盘是链条的一环, 不是附属条件。
- 二接三: 链 = 一板开 → 二板开 → 三板开(=买入日竞价, 打的就是3板)
- 三接四: 链 = 一板开 → 二板开 → 三板开(=b3) → 四板开(=买入日竞价, 打的是4板)
- 两组共用「一→二→三」前缀结构, 统一进同一个立方, 分阴阳, 买入位置(2板买/3板买)做标注维度。

档位: 低<0 / 平0~3 / 高3~7 / 强≥7
结果: 次日连板率(主) / 好票率 / 断板收益
宿主机纯CSV: uv run python relay_combo5.py
"""
import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
B4 = [(-99, 0, "低"), (0, 3, "平"), (3, 7, "高"), (7, 99, "强")]
L4 = [b[2] for b in B4]
rng = np.random.default_rng(20260925)

pd.set_option("display.width", 400)
pd.set_option("display.max_columns", 100)
pd.set_option("display.max_rows", 300)

AGG = dict(
    n=("代码", "size"),
    连板率=("次日连板", "mean"),
    好票率=("坏票", lambda s: 1 - s.mean()),
    断板收益=("持有到断板%", "mean"),
)


def cut4(s):
    out = pd.Series(index=s.index, dtype="object")
    for lo, hi, lab in B4:
        out[(s >= lo) & (s < hi)] = lab
    return out


def load():
    E = pd.read_csv(f"{ROOT}/全量明细.csv", dtype={"代码": str})
    P = pd.read_csv(f"{ROOT}/首板前3日明细.csv", dtype={"代码": str})
    M = E.merge(P.drop(columns=["首板日"]), on=["代码", "买入日"], how="inner")
    M = M[~M["未完"]].copy()
    M["年"] = M["年"].astype(str)
    M["高度增益"] = M["最终高度"] - M["N"]
    M["一板"] = cut4(M["b1开盘%"])
    M["二板"] = cut4(M["b2开盘%"])
    # 统一第三环: 二接三=买入日竞价(打3板), 三接四=三板b3的开盘
    M["三板"] = np.where(M["组"] == "二接三", M["买入开盘%"], M["b3开盘%"])
    M["三板"] = cut4(M["三板"])
    M["四板"] = np.where(M["组"] == "三接四", M["买入开盘%"], np.nan)   # 仅三接四有
    M["四板"] = cut4(M["四板"].fillna(-99)) if False else M["四板"]
    # 重算四板档(三接四才有, 二接三填'—')
    M.loc[M["组"] == "三接四", "四板"] = cut4(M.loc[M["组"] == "三接四", "买入开盘%"])
    M["四板"] = M["四板"].fillna("—")
    M["买位"] = M["组"].map({"二接三": "打3板", "三接四": "打4板"})
    return M


def stat(M, by):
    return M.groupby(by, observed=True).agg(**AGG).round(3)


def mini_year(sel):
    yr = sel.groupby("年").agg(n=("代码", "size"), 连板率=("次日连板", "mean")).round(2)
    return " ".join(f"{y}:{int(r['n'])}笔{r['连板率']:.0%}" for y, r in yr.iterrows())


def perm(a, b, n=2000):
    x, y = a.to_numpy(float), b.to_numpy(float)
    obs = x.mean() - y.mean()
    pool = np.concatenate([x, y])
    cnt = 0
    for _ in range(n):
        rng.shuffle(pool)
        if abs(pool[:len(x)].mean() - pool[len(x):].mean()) >= abs(obs) - 1e-12:
            cnt += 1
    return obs, (cnt + 1) / (n + 1)


if __name__ == "__main__":
    M = load()
    print(f"样本 {len(M)}  (二接三=打3板 {len(M[M['组']=='二接三'])}, 三接四=打4板 {len(M[M['组']=='三接四'])})")

    print("\n" + "=" * 100)
    print("① 完整链立方: 一板×二板×三板 → 连板率, 分阴阳 (买位混合, 每格标注两组占比)")
    print("=" * 100)
    for yy in ["阳", "阴"]:
        S = M[M["阴阳"] == yy]
        t = S.groupby(["一板", "二板", "三板"], observed=True).agg(**AGG)
        t = t[t["n"] >= 20].sort_values("连板率", ascending=False).round(3)
        # 组内买位占比
        mix = S.groupby(["一板", "二板", "三板"], observed=True)["买位"].value_counts(normalize=True).unstack().round(2)
        t = t.join(mix[["打3板"]] if "打3板" in mix else None)
        print(f"\n===== 地基{yy} · 链=一板→二板→三板 (n≥20, 按连板率降序) =====")
        print(t.to_string())
        print(f"\n--- 地基{yy} 毒链 (连板率最低的12条, n≥20) ---")
        t2 = S.groupby(["一板", "二板", "三板"], observed=True).agg(**AGG)
        print(t2[t2["n"] >= 20].sort_values("连板率").head(12).round(3).to_string())

    print("\n" + "=" * 100)
    print("② 「一X 二Y → 三板开哪档最好」读法矩阵 (分阴阳, 买位混合)")
    print("=" * 100)
    for yy in ["阳", "阴"]:
        S = M[M["阴阳"] == yy]
        print(f"\n===== 地基{yy}: 行=一板, 列=二板, 格=三板最优档 连板率(该档n / 池n / 池率) =====")
        for g1 in L4:
            row = []
            for g2 in L4:
                sub = S[(S["一板"] == g1) & (S["二板"] == g2)]
                if len(sub) < 25:
                    row.append("  样本少  ")
                    continue
                g = sub.groupby("三板", observed=True).agg(**AGG)
                g = g[g["n"] >= 8]
                if len(g) == 0:
                    row.append("  样本少  ")
                    continue
                best = g["连板率"].idxmax()
                b = g.loc[best]
                row.append(f"三{best} {b['连板率']:.0%}({int(b['n'])}/{len(sub)},{sub['次日连板'].mean():.0%})")
            print(f"一板{g1}: " + " | ".join(row))

    print("\n" + "=" * 100)
    print("③ 三接四延伸第四环: 头部前三链 × 四板开(买入竞价) → 连板")
    print("=" * 100)
    S34 = M[M["组"] == "三接四"]
    t = S34.groupby(["阴阳", "一板", "二板", "三板"], observed=True).agg(**AGG)
    heads = t[t["n"] >= 30].sort_values("连板率", ascending=False).head(6).index
    for key in heads:
        yy, g1, g2, g3 = key
        sub = S34[(S34["阴阳"] == yy) & (S34["一板"] == g1) & (S34["二板"] == g2) & (S34["三板"] == g3)]
        print(f"\n--- {yy}地基 链 {g1}→{g2}→{g3} (n={len(sub)}) × 四板开 ---")
        print(stat(sub, "四板").to_string())

    print("\n" + "=" * 100)
    print("④ 轨迹形状速览: 前三环形状 × 起始档 → 连板率 (分阴阳)")
    print("=" * 100)
    rk = {l: i for i, l in enumerate(L4)}
    r1, r2, r3 = M["一板"].map(rk), M["二板"].map(rk), M["三板"].map(rk)
    M["形状"] = np.select(
        [(r2 > r1) & (r3 >= r2), (r2 < r1) & (r3 <= r2), (r2 > r1) & (r3 < r2), (r2 < r1) & (r3 > r2)],
        ["一路升", "一路降", "峰在二", "谷在二"], "平稳/波动")
    print(stat(M, ["阴阳", "一板", "形状"]))
