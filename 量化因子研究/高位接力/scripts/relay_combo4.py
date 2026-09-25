# -*- coding: utf-8 -*-
"""高位接力 · 节奏链核心格子稳健性（第二十六遍配套）。

对 relay_combo3.py 扫出的头部/毒格子: 分年 + 去最好3笔 + 置换 vs 组内其余。
宿主机纯CSV: uv run python relay_combo4.py
"""
import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
B4 = [(-99, 0, "低开"), (0, 3, "平开"), (3, 7, "高开"), (7, 99, "强开")]
rng = np.random.default_rng(20260919)
pd.set_option("display.width", 400)


def cut4(s):
    out = pd.Series(index=s.index, dtype="object")
    for lo, hi, lab in B4:
        out[(s >= lo) & (s < hi)] = lab
    return out


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


def load():
    E = pd.read_csv(f"{ROOT}/全量明细.csv", dtype={"代码": str})
    P = pd.read_csv(f"{ROOT}/首板前3日明细.csv", dtype={"代码": str})
    M = E.merge(P.drop(columns=["首板日"]), on=["代码", "买入日"], how="inner")
    M = M[~M["未完"]].copy()
    M["年"] = M["年"].astype(str)
    M["高度增益"] = M["最终高度"] - M["N"]
    M["一档"] = cut4(M["b1开盘%"])
    M["二档"] = cut4(M["b2开盘%"])
    M["三档"] = cut4(M["买入开盘%"])
    rank = {b[2]: i for i, b in enumerate(B4)}
    M["r1"] = M["一档"].map(rank); M["r2"] = M["二档"].map(rank)
    M["节奏"] = np.select([M["r2"] > M["r1"], M["r2"] == M["r1"]], ["加速", "续档"], "减速")
    return M


def check(M, mask, name, pool):
    sel = M[mask]
    base = M[pool]
    rest = base.drop(sel.index)
    obs, p = perm(sel["次日连板"], rest["次日连板"])
    print(f"\n### {name}")
    print(f"n={len(sel)} 连板率={sel['次日连板'].mean():.3f} 好票率={1 - sel['坏票'].mean():.3f} "
          f"高度增益={sel['高度增益'].mean():.2f} 断板={sel['持有到断板%'].mean():+.2f} | "
          f"池内其余 {rest['次日连板'].mean():.3f} 差={obs:+.3f} p={p:.4f}")
    yr = sel.groupby("年").agg(n=("代码", "size"), 连板率=("次日连板", "mean"),
                              断板=("持有到断板%", "mean")).round(3)
    print(yr.to_string().replace("\n", "\n"))
    r2 = sel.drop(sel.nlargest(3, "持有到断板%").index)
    print(f"去最好3笔: 连板率={r2['次日连板'].mean():.3f} 好票率={1 - r2['坏票'].mean():.3f} 断板={r2['持有到断板%'].mean():+.2f}")


if __name__ == "__main__":
    M = load()
    G = M["四组"] == "x"  # 占位
    print("=" * 90)
    print("节奏链核心格子稳健性")
    print("=" * 90)

    check(M, (M["四组"] == "二接三阳") & (M["一档"] == "低开") & (M["二档"] == "低开"),
          "好格① 二接三阳 双低链(一低×二低)", M["四组"] == "二接三阳")
    check(M, (M["四组"] == "二接三阴") & (M["一档"] == "强开") & (M["二档"].isin(["强开", "高开"])),
          "好格② 二接三阴 一板加速后二板保持高热度(强/高)", M["四组"] == "二接三阴")
    check(M, (M["一档"] == "强开") & (M["节奏"] == "减速") & (M["三档"].isin(["平开", "强开"])),
          "好格③ 强→减速 × 三板平/强开", pd.Series(True, index=M.index))
    check(M, (M["组"] == "三接四") & (M["一档"] == "低开") & (M["二档"].isin(["低开", "平开"])),
          "好格④ 三接四 低起温和链(一低×二低/平)", M["组"] == "三接四")
    check(M, (M["一档"] == "低开") & (M["二档"] == "强开") & (M["三档"] == "强开"),
          "好格⑤ 低→强 × 三板强开确认(主人猜想修正版)", pd.Series(True, index=M.index))
    check(M, (M["四组"] == "二接三阳") & (M["一档"] == "低开") & (M["二档"] == "强开"),
          "毒格⑥ 二接三阳 低开→二板强开(主人原猜想)", M["四组"] == "二接三阳")
    check(M, (M["四组"] == "二接三阳") & (M["一档"] == "平开") & (M["二档"] == "高开"),
          "毒格⑦ 二接三阳 平开→二板高开3~7(死亡峡谷)", M["四组"] == "二接三阳")
    check(M, (M["一档"] == "强开") & (M["节奏"] == "减速") & (M["pre3%"] > -5) & (M["pre3%"] <= 0),
          "王格⑧ 强→减速 × pre3(-5,0]", pd.Series(True, index=M.index))
