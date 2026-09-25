# -*- coding: utf-8 -*-
"""高位接力 · 好差票组合研究(二)：核心格子稳健性检验。

对 relay_combo.py 扫出的核心发现做: 分年方向 / 去最好3笔 / 置换检验2000次。
宿主机纯CSV: uv run python relay_combo2.py
"""
import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
rng = np.random.default_rng(20260919)


def load():
    E = pd.read_csv(f"{ROOT}/全量明细.csv", dtype={"代码": str})
    P = pd.read_csv(f"{ROOT}/首板前3日明细.csv", dtype={"代码": str})
    M = E.merge(P.drop(columns=["首板日"]), on=["代码", "买入日"], how="inner")
    M = M[~M["未完"]].copy()
    M["年"] = M["年"].astype(str)
    M["高度增益"] = M["最终高度"] - M["N"]
    M["b2三档"] = pd.cut(M["b2开盘%"], [-99, 0, 3, 99], labels=["阴<0", "中0~3", "阳≥3"])
    M["pre3档"] = pd.cut(M["pre3%"], [-99, -5, 0, 5, 10, 99], labels=["≤-5", "-5~0", "0~5", "5~10", ">10"])
    return M


def perm_test(a, b, col="次日连板", n=2000):
    """两组连板率差的置换检验, 返回 p 值(双侧)"""
    x, y = a[col].to_numpy(float), b[col].to_numpy(float)
    obs = x.mean() - y.mean()
    pool = np.concatenate([x, y])
    cnt = 0
    for _ in range(n):
        rng.shuffle(pool)
        d = pool[:len(x)].mean() - pool[len(x):].mean()
        if abs(d) >= abs(obs) - 1e-12:
            cnt += 1
    return obs, (cnt + 1) / (n + 1)


def report(M, sel, name, ctrl=None):
    print(f"\n### {name}: n={len(sel)}")
    print(f"  次日连板率={sel['次日连板'].mean():.3f} 好票率={1 - sel['坏票'].mean():.3f} "
          f"高度增益={sel['高度增益'].mean():.2f} 断板收益={sel['持有到断板%'].mean():+.2f}")
    yr = sel.groupby("年").agg(n=("代码", "size"), 连板率=("次日连板", "mean"),
                              断板收益=("持有到断板%", "mean")).round(3)
    print("  分年:"); print(yr.to_string().replace("\n", "\n  "))
    if ctrl is not None:
        rest = M.drop(sel.index)
        obs, p = perm_test(sel, rest)
        print(f"  vs 组外(n={len(rest)}): 连板率差={obs:+.3f} 置换p={p:.4f}")
    sub = sel.nlargest(3, "持有到断板%")
    rest2 = sel.drop(sub.index)
    print(f"  去最好3笔: n={len(rest2)} 连板率={rest2['次日连板'].mean():.3f} "
          f"好票率={1 - rest2['坏票'].mean():.3f} 断板收益={rest2['持有到断板%'].mean():+.2f}")


if __name__ == "__main__":
    M = load()
    print(f"样本 {len(M)}")

    print("\n" + "=" * 80)
    print("稳健性检验 · 核心发现")
    print("=" * 80)

    # 1. b2 开盘 阴 vs 阳 (全场最强单维)
    a = M[M["b2三档"] == "阴<0"]
    b = M[M["b2三档"] == "阳≥3"]
    obs, p = perm_test(a, b)
    print(f"\n[1] b2开盘 阴<0 vs 阳≥3: 连板率 {a['次日连板'].mean():.3f} vs {b['次日连板'].mean():.3f} "
          f"差={obs:+.3f} 置换p={p:.4f}")
    for g in ["二接三阳", "二接三阴", "三接四阳", "三接四阴"]:
        s1 = a[a["四组"] == g]; s2 = b[b["四组"] == g]
        print(f"    {g}: {s1['次日连板'].mean():.3f}(n={len(s1)}) vs {s2['次日连板'].mean():.3f}(n={len(s2)}) "
              f"断板收益 {s1['持有到断板%'].mean():+.2f} vs {s2['持有到断板%'].mean():+.2f}")

    # 2. p3 阴阳串 阴阳阳 vs 阳阴阳
    a = M[M["p3阴阳"] == "阴阳阳"]
    b = M[M["p3阴阳"] == "阳阴阳"]
    obs, p = perm_test(a, b)
    print(f"\n[2] 前3日串 阴阳阳 vs 阳阴阳: 连板率 {a['次日连板'].mean():.3f} vs {b['次日连板'].mean():.3f} "
          f"差={obs:+.3f} 置换p={p:.4f}")

    # 3. 毒格通式: b2阳≥3 × pre3>5 全场
    print("\n[3] 毒格通式 b2阳≥3 × pre3>5 (四组分别):")
    for g, sub in M.groupby("四组"):
        sel = sub[(sub["b2三档"] == "阳≥3") & (sub["pre3%"] > 5)]
        rest = sub.drop(sel.index)
        print(f"  {g}: 毒格n={len(sel)} 连板率={sel['次日连板'].mean():.3f} 断板={sel['持有到断板%'].mean():+.2f} | "
              f"组内其余 连板率={rest['次日连板'].mean():.3f} 断板={rest['持有到断板%'].mean():+.2f}")
    sel = M[(M["b2三档"] == "阳≥3") & (M["pre3%"] > 5)]
    report(M, sel, "毒格通式 b2阳≥3×pre3>5 全场")

    # 4. 好格: 二接三阳 × b2阴<0 × pre3 -5~10
    sel = M[(M["四组"] == "二接三阳") & (M["b2三档"] == "阴<0") & (M["pre3%"] > -5) & (M["pre3%"] <= 10)]
    report(M, sel, "好格 二接三阳×b2阴<0×pre3(-5,10]", ctrl=True)

    # 5. 好格: 三接四阴 × b2非阳(pre3任意)
    sel = M[(M["四组"] == "三接四阴") & (M["b2三档"] != "阳≥3")]
    report(M, sel, "好格 三接四阴×b2(阴或中)", ctrl=True)

    # 6. 三接四 × pre3>5 的组内差异
    sel = M[(M["组"] == "三接四") & (M["pre3%"] > 5)]
    report(M, sel, "三接四×pre3>5")

    # 7. b2阴<0×pre3≤-5 反例格 (二接三阳)
    sel = M[(M["四组"] == "二接三阳") & (M["b2三档"] == "阴<0") & (M["pre3%"] <= -5)]
    report(M, sel, "反例格 二接三阳×b2阴<0×pre3≤-5")

    # 8. 阴阳阳串 的构成: 是不是 pre3 低 + 地基阳 的代理?
    print("\n[8] 阴阳阳串 vs 其他串的 pre3% 均值与构成:")
    t = M.groupby("p3阴阳").agg(n=("代码", "size"), pre3均值=("pre3%", "mean"),
                               连板率=("次日连板", "mean"), 好票率=("坏票", lambda s: 1 - s.mean())).round(3)
    print(t)
