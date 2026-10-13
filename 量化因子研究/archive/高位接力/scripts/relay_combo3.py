# -*- coding: utf-8 -*-
"""高位接力 · 连板节奏链组合研究（第二十六遍）：一板×二板×三板竞价×前3日 全链一起看。

主人方向: 不是各板各看, 是链式节奏 —— 「首板低开×二板加速(≥7)→三板更容易连板?」
          「一板就加速, 二板要怎样?」→ 全链组合对连板结果的影响。

档位(贴主人语言, 7%=加速线, 沿用开盘链边界):
  低开<0 / 平0~3 / 高3~7 / 强开≥7 (四档)
节奏 = b1档→b2档 的升降(加速/续/减速)

结果: 次日连板率(主) / 高度增益 / 好票率 / 断板收益
宿主机纯CSV: uv run python relay_combo3.py
"""
import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
B4 = [(-99, 0, "低开"), (0, 3, "平开"), (3, 7, "高开"), (7, 99, "强开")]
L4 = [b[2] for b in B4]
rng = np.random.default_rng(20260919)

pd.set_option("display.width", 400)
pd.set_option("display.max_columns", 100)
pd.set_option("display.max_rows", 300)

AGG = dict(
    n=("代码", "size"),
    连板率=("次日连板", "mean"),
    高度增益=("高度增益", "mean"),
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
    M["一档"] = cut4(M["b1开盘%"])
    M["二档"] = cut4(M["b2开盘%"])
    M["三档"] = cut4(M["买入开盘%"])          # 买入日开盘=竞价档
    M["pre3档"] = pd.cut(M["pre3%"], [-99, -5, 0, 5, 10, 99],
                         labels=["≤-5", "-5~0", "0~5", "5~10", ">10"])
    # 节奏: 二板相对首板 升/平/降
    rank = {l: i for i, l in enumerate(L4)}
    M["r1"] = M["一档"].map(rank); M["r2"] = M["二档"].map(rank)
    M["节奏"] = np.select([M["r2"] > M["r1"], M["r2"] == M["r1"]], ["加速", "续档"], "减速")
    return M


def stat(M, by):
    return M.groupby(by, observed=True).agg(**AGG).round(3)


def robust(M, sel, name):
    if len(sel) < 15:
        print(f"\n### {name}: n={len(sel)} <15 只报数字不作稳健性")
        if len(sel):
            print(f"  连板率={sel['次日连板'].mean():.3f} 高度增益={sel['高度增益'].mean():.2f}")
        return
    print(f"\n### {name}: n={len(sel)} 连板率={sel['次日连板'].mean():.3f} "
          f"高度增益={sel['高度增益'].mean():.2f} 好票率={1 - sel['坏票'].mean():.3f} "
          f"断板={sel['持有到断板%'].mean():+.2f}")
    yr = sel.groupby("年").agg(n=("代码", "size"), 连板率=("次日连板", "mean"),
                              断板=("持有到断板%", "mean")).round(3)
    print("  分年:"); print(yr.to_string().replace("\n", "\n  "))
    rest = sel.drop(sel.nlargest(3, "持有到断板%").index)
    print(f"  去最好3笔: 连板率={rest['次日连板'].mean():.3f} 好票率={1 - rest['坏票'].mean():.3f} "
          f"断板={rest['持有到断板%'].mean():+.2f}")


if __name__ == "__main__":
    M = load()
    print(f"样本 {len(M)}\n")

    print("=" * 95)
    print("① 节奏单维: 一板档 × 节奏(二板相对一首板 升/平/降) → 连板 (分四组)")
    print("=" * 95)
    print(stat(M, ["四组", "一档", "节奏"]))

    print("\n" + "=" * 95)
    print("② 主人两问直接回答")
    print("=" * 95)
    print("\n问1: 首板低开 × 二板各走法 → 连板率 (四组)")
    print(stat(M[M["一档"] == "低开"], ["四组", "二档"]))
    print("\n问2: 首板强开(≥7) × 二板各走法 → 连板率 (四组)")
    print(stat(M[M["一档"] == "强开"], ["四组", "二档"]))
    print("\n问2b: 首板高开(3~7) × 二板各走法 → 连板率 (四组)")
    print(stat(M[M["一档"] == "高开"], ["四组", "二档"]))

    print("\n" + "=" * 95)
    print("③ 全链矩阵: 一档 × 二档 → 连板 (二接三 阴/阳分开; 三接四合并阴阳)")
    print("=" * 95)
    for g in ["二接三阳", "二接三阴"]:
        print(f"\n===== {g}: 一板开盘 × 二板开盘 =====")
        print(stat(M[M["四组"] == g], ["一档", "二档"]))
    print("\n===== 三接四(合并阴阳): 一板 × 二板 =====")
    print(stat(M[M["组"] == "三接四"], ["一档", "二档"]))
    print("\n===== 三接四: 二板 × 三板(买入前一日b3板的开盘, 非竞价) =====")
    M34 = M[M["组"] == "三接四"].copy()
    M34["b3档"] = cut4(M34["b3开盘%"])
    print(stat(M34, ["二档", "b3档"]))

    print("\n" + "=" * 95)
    print("④ 三板(买入日)竞价档: 对头两类链, 三板开在哪最连板")
    print("=" * 95)
    for name, sel in [
        ("链=低开→强开(主人猜想: 缓启加速)", M[(M["一档"] == "低开") & (M["二档"] == "强开")]),
        ("链=低开→平开/高开", M[(M["一档"] == "低开") & (M["二档"].isin(["平开", "高开"]))]),
        ("链=强开→强开(全程顶格)", M[(M["一档"] == "强开") & (M["二档"] == "强开")]),
        ("链=强开→减速", M[(M["一档"] == "强开") & (M["节奏"] == "减速")]),
    ]:
        print(f"\n--- {name} × 三板竞价档 ---")
        print(stat(sel, ["三档"]))

    print("\n" + "=" * 95)
    print("⑤ 前3日涨幅档 配链: 头部链 × pre3档 → 连板 (合并四组, 链内分二接三/三接四)")
    print("=" * 95)
    for name, sel in [
        ("链=低开→强开", M[(M["一档"] == "低开") & (M["二档"] == "强开")]),
        ("链=强开→强开", M[(M["一档"] == "强开") & (M["二档"] == "强开")]),
        ("链=低开→低开(双低)", M[(M["一档"] == "低开") & (M["二档"] == "低开")]),
        ("链=强开→减速", M[(M["一档"] == "强开") & (M["节奏"] == "减速")]),
    ]:
        print(f"\n--- {name} × pre3档 × 组 ---")
        t = stat(sel, ["组", "pre3档"])
        print(t[t["n"] >= 10])

    print("\n" + "=" * 95)
    print("⑥ 完整四元组合(样本够才显示): 二档 × 三档 × pre3档, 一档=低开(缓启家族)")
    print("=" * 95)
    sel = M[M["一档"] == "低开"]
    t = stat(sel, ["组", "二档", "三档"])
    print("一档=低开: 组×二档×三档竞价 (n≥15)")
    print(t[t["n"] >= 15])
