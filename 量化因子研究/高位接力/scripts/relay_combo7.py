# -*- coding: utf-8 -*-
"""高位接力 · 四环链全量 + 多维整体组合（第二十九遍）。

主人两点: ①三接四的第4板(买入日竞价)也是链的一环, 全量看;
         ②要看多维组合的整体, 不是零散格子。

整体 = 节奏签名(每板相对前一板 升/平/降 的序列) + 链总热度(各板档位数值和) × 阴阳 × 买位。
宿主机纯CSV: uv run python relay_combo7.py
"""
import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
B4 = [(-99, 0, "低"), (0, 3, "平"), (3, 7, "高"), (7, 99, "强")]
L4 = [b[2] for b in B4]
rng = np.random.default_rng(20260925)
pd.set_option("display.width", 420)
pd.set_option("display.max_rows", 300)

AGG = dict(
    n=("代码", "size"),
    胜率=("胜", "mean"),
    收益=("持有到断板%", "mean"),
    连板率=("次日连板", "mean"),
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
    M["胜"] = ~M["坏票"].fillna(True).astype(bool)
    M["一板"] = cut4(M["b1开盘%"])
    M["二板"] = cut4(M["b2开盘%"])
    M["三板"] = cut4(pd.Series(np.where(M["组"] == "二接三", M["买入开盘%"], M["b3开盘%"]), index=M.index))
    M34 = M["组"] == "三接四"
    M["四板"] = "—"
    M.loc[M34, "四板"] = cut4(M.loc[M34, "买入开盘%"])
    rk = {l: i for i, l in enumerate(L4)}
    # 节奏签名: 每板相对前一板的 变化
    r1, r2 = M["一板"].map(rk), M["二板"].map(rk)
    r3 = M["三板"].map(rk)
    r4 = M["四板"].map(rk).fillna(-1).astype(int)
    def sym(a, b):
        return np.where(b > a, "升", np.where(b < a, "降", "平"))
    M["签名23"] = np.char.add(sym(r1, r2), sym(r2, r3))                 # 二接三: 一→二→三 两个符号
    M["签名34"] = np.where(M34, np.char.add(np.char.add(sym(r1, r2), sym(r2, r3)), sym(r3, r4)), "")
    # 链总热度: 已走完板的档位数值和 (二接三=一+二, 三接四=一+二+三)
    M["热度"] = np.where(M34, r1 + r2 + r3, r1 + r2)
    M["pre3档"] = pd.cut(M["pre3%"], [-99, -5, 0, 5, 99], labels=["≤-5", "-5~0", "0~5", ">5"])
    return M


def stat(M, by):
    return M.groupby(by, observed=True).agg(**AGG).round(3)


if __name__ == "__main__":
    M = load()
    print(f"样本 {len(M)}")

    print("=" * 100)
    print("① 三接四 · 三板×四板(买入日竞价) 全量矩阵, 分阴阳 ←—— 第4板全量(新)")
    print("=" * 100)
    for yy in ["阳", "阴"]:
        S = M[(M["组"] == "三接四") & (M["阴阳"] == yy)]
        print(f"\n===== 三接四 {yy}地基: 行=三板开, 列=四板开(买入当天竞价) =====")
        piv_r = S.groupby(["三板", "四板"], observed=True)["次日连板"].mean().unstack().reindex(index=L4, columns=L4)
        piv_n = S.groupby(["三板", "四板"], observed=True)["次日连板"].size().unstack().reindex(index=L4, columns=L4)
        piv_y = S.groupby(["三板", "四板"], observed=True)["持有到断板%"].mean().unstack().reindex(index=L4, columns=L4)
        print("连板率 (n / 收益%):")
        for g3 in L4:
            row = []
            for g4 in L4:
                r, n, y = piv_r.loc[g3, g4], piv_n.loc[g3, g4], piv_y.loc[g3, g4]
                row.append(f"{r:.0%}({int(n)}/{y:+.1f})" if r == r else "—")
            print(f"  三板{g3}: " + " | ".join(row))

    print("\n" + "=" * 100)
    print("② 三接四 · 四环节奏签名(一→二→三→四 每步 升/平/降) 整体排行, 分阴阳")
    print("=" * 100)
    for yy in ["阳", "阴"]:
        S = M[(M["组"] == "三接四") & (M["阴阳"] == yy)]
        t = stat(S, ["签名34"])
        t = t[t["n"] >= 12].sort_values("连板率", ascending=False)
        print(f"\n===== 三接四 {yy} (n≥12) =====")
        print(t.to_string())

    print("\n" + "=" * 100)
    print("③ 二接三 · 三环节奏签名(一→二→三) 整体排行, 分阴阳")
    print("=" * 100)
    for yy in ["阳", "阴"]:
        S = M[(M["组"] == "二接三") & (M["阴阳"] == yy)]
        t = stat(S, ["一板", "签名23"])
        t = t[t["n"] >= 15].sort_values("连板率", ascending=False)
        print(f"\n===== 二接三 {yy} (一板档×签名, n≥15) =====")
        print(t.head(15).to_string())
        print("... 毒端:")
        print(t.tail(8).to_string())

    print("\n" + "=" * 100)
    print("④ 链总热度 × 阴阳 × 买位 → 整体 (热度=已走完板的档位和: 低0平1高2强3)")
    print("=" * 100)
    M["热度档"] = pd.cut(M["热度"], [-1, 1, 3, 4, 9], labels=["很冷0~1", "温2~3", "热4", "很热5+"])
    print(stat(M, ["阴阳", "买位" if "买位" in M else "组", "热度档"]))
    print("\n热度档 × pre3档 (整体组合, 买位合并):")
    print(stat(M, ["热度档", "pre3档"])[lambda t: t["n"] >= 25])

    print("\n" + "=" * 100)
    print("⑤ 全维一体: 签名(链形状) × pre3档 × 阴阳 → 连板率 (n≥20 的格)")
    print("=" * 100)
    M["签名"] = np.where(M["组"] == "三接四", M["签名34"], M["签名23"])
    t = stat(M, ["阴阳", "签名", "pre3档"])
    print(t[t["n"] >= 20].sort_values("连板率", ascending=False).to_string())
