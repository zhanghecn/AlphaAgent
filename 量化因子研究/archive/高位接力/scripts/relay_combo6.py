# -*- coding: utf-8 -*-
"""高位接力 · 统一链立方核心格子稳健性（第二十七遍配套）。

头部好链/毒链: 分年 + 去最好3笔 + 置换 vs 同阴阳池其余。
宿主机纯CSV: uv run python relay_combo6.py
"""
import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
B4 = [(-99, 0, "低"), (0, 3, "平"), (3, 7, "高"), (7, 99, "强")]
rng = np.random.default_rng(20260925)
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
    M = E[~E["未完"]].copy()
    M["年"] = M["年"].astype(str)
    M["一板"] = cut4(M["b1开盘%"])
    M["二板"] = cut4(M["b2开盘%"])
    M["三板"] = cut4(pd.Series(np.where(M["组"] == "二接三", M["买入开盘%"], M["b3开盘%"]), index=M.index))
    return M


def check(M, mask, name, pool_mask):
    sel = M[mask]
    pool = M[pool_mask]
    rest = pool.drop(sel.index)
    obs, p = perm(sel["次日连板"], rest["次日连板"])
    print(f"\n### {name}")
    print(f"n={len(sel)} 连板率={sel['次日连板'].mean():.3f} 好票率={1 - sel['坏票'].mean():.3f} "
          f"断板={sel['持有到断板%'].mean():+.2f} | 池其余 {rest['次日连板'].mean():.3f} 差={obs:+.3f} p={p:.4f}")
    yr = sel.groupby("年").agg(n=("代码", "size"), 连板率=("次日连板", "mean"),
                              断板=("持有到断板%", "mean")).round(3)
    print(yr.to_string().replace("\n", "\n"))
    r2 = sel.drop(sel.nlargest(3, "持有到断板%").index)
    print(f"去最好3笔: 连板率={r2['次日连板'].mean():.3f} 好票率={1 - r2['坏票'].mean():.3f} 断板={r2['持有到断板%'].mean():+.2f}")


if __name__ == "__main__":
    M = load()
    Y = M["阴阳"] == "阳"; N_ = M["阴阳"] == "阴"
    print("=" * 92)
    print("统一链(一板×二板×三板)核心格子稳健性 · 池=同地基阴阳全体")
    print("=" * 92)

    check(M, Y & (M["一板"] == "平") & (M["二板"] == "平") & (M["三板"] == "强"),
          "好链① 阳 平→平→强", Y)
    check(M, Y & (M["一板"] == "平") & (M["二板"] == "强") & (M["三板"] == "高"),
          "好链② 阳 平→强→高", Y)
    check(M, Y & (M["一板"] == "低") & (M["二板"] == "低") & (M["三板"].isin(["高", "强"])),
          "好链③ 阳 双低→三高/强", Y)
    check(M, Y & (M["一板"] == "低") & (M["二板"] == "平") & (M["三板"] == "强"),
          "好链④ 阳 低→平→强", Y)
    check(M, Y & (M["一板"] == "平") & (M["二板"] == "强") & (M["三板"] == "强"),
          "主链⑤ 阳 平→强→强 (最大样本主通道)", Y)
    check(M, N_ & (M["一板"] == "强") & (M["二板"] == "强") & (M["三板"].isin(["高", "强"])),
          "好链⑥ 阴 强→强→高/强(保持高热度)", N_)
    check(M, N_ & (M["一板"] == "低") & (M["二板"] == "平") & (M["三板"].isin(["平", "低"])),
          "好链⑦ 阴 低→平→平/低(温和链)", N_)
    check(M, Y & (M["二板"] == "高"),
          "毒链⑧ 阳 二板高开3~7 (全一板合并)", Y)
    check(M, N_ & (M["二板"] == "高"),
          "毒链⑨ 阴 二板高开3~7 (全一板合并)", N_)
    check(M, Y & (M["三板"] == "平") & (M["二板"].isin(["高", "强"])),
          "毒链⑩ 阳 二板高/强 × 三板平(半途熄火)", Y)
    check(M, Y & (M["一板"] == "高"),
          "毒⑪ 阳 一板高开3~7 (透支起手)", Y)
