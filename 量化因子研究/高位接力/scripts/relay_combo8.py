# -*- coding: utf-8 -*-
"""高位接力 · 二接三阳细网格·聚焦今开6~9.5（第三十遍v2）。

主人问题: 在"今天开6~9.5"窗口内, 二板一字/强开分别配 一板开多少 × 今开多少 最合适。
口径: 二接三阳 × 正常开盘(今开∈[6,9.5)), 一板细分箱 × 二板形态 × 今开细分箱。
宿主机纯CSV: uv run python relay_combo8.py
"""
import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 420)
pd.set_option("display.max_rows", 300)

AGG = dict(
    n=("代码", "size"),
    胜率=("胜", "mean"),
    收益=("持有到断板%", "mean"),
    连板率=("次日连板", "mean"),
)


def load():
    E = pd.read_csv(f"{ROOT}/全量明细.csv", dtype={"代码": str})
    M = E[~E["未完"]].copy()
    M["年"] = M["年"].astype(str)
    M["胜"] = ~M["坏票"].fillna(True).astype(bool)
    M["二板形态"] = np.select(
        [M["b2开盘%"] >= 9.5, M["b2开盘%"] >= 7, M["b2开盘%"] >= 3],
        ["一字", "换手强", "高"], default="低平",
    )
    # 一板细分箱: 平开内部也拆开(主人问"一板开多少才合适")
    M["一板箱"] = pd.cut(M["b1开盘%"], [-99, -1, 0, 1, 2, 3, 7, 99],
                       labels=["<-1", "-1~0", "0~1", "1~2", "2~3", "3~7", "≥7"])
    M["今开箱"] = pd.cut(M["买入开盘%"], [5.999, 6.5, 7, 7.5, 8, 8.5, 9, 9.5],
                       labels=["6~6.5", "6.5~7", "7~7.5", "7.5~8", "8~8.5", "8.5~9", "9~9.5"])
    return M[(M["组"] == "二接三") & (M["阴阳"] == "阳") & (M["买入开盘%"] >= 6) & (M["买入开盘%"] < 9.5)].copy()


def stat(M, by):
    return M.groupby(by, observed=True).agg(**AGG).round(3)


def yearly(M, label):
    y = M.groupby("年").agg(n=("胜", "size"), 胜=("胜", "mean")).round(2)
    parts = " ".join(f"{i}年{int(r['n'])}笔{r['胜']*100:.0f}%" for i, r in y.iterrows())
    print(f"    {label} 分年: {parts}")


if __name__ == "__main__":
    S = load()
    print(f"二接三阳·今开6~9.5 全样本 {len(S)}笔\n")
    print("--- 二板形态 边际 ---")
    print(stat(S, ["二板形态"]))

    for form in ["换手强", "一字"]:
        F = S[S["二板形态"] == form]
        if not len(F):
            continue
        print("\n" + "=" * 100)
        print(f"■ 二板{form} ({len(F)}笔 胜{F['胜'].mean()*100:.0f}% 连板{F['次日连板'].mean()*100:.0f}% 均{F['持有到断板%'].mean():+.2f})")
        print("=" * 100)

        print(f"\n① 二板{form} × 一板箱 (回答: 一板开多少才合适)")
        t = stat(F, ["一板箱"])
        print(t)
        for lo in ["<-1", "-1~0", "0~1", "1~2"]:
            sub = F[F["一板箱"] == lo]
            if len(sub):
                yearly(sub, f"一板{lo}")

        print(f"\n② 二板{form} × 今开箱 (回答: 三板开到多少最合适)")
        t = stat(F, ["今开箱"])
        print(t)

        print(f"\n③ 二板{form} × 一板箱 × 今开箱 (n≥3)")
        t = stat(F, ["一板箱", "今开箱"])
        print(t[t["n"] >= 3])

        print(f"\n④ 二板{form} 逐笔 (按今开排序)")
        cols = ["买入日", "名称", "b1开盘%", "b2开盘%", "买入开盘%", "胜", "持有到断板%"]
        print(F[cols].sort_values("买入开盘%").to_string(index=False, float_format=lambda x: f"{x:.2f}"))
