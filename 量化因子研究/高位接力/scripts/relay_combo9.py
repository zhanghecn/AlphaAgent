# -*- coding: utf-8 -*-
"""高位接力 · 二接三阳细边界扫描（第三十一遍）。

主人质疑: 边界没细扫过。一板 1%/2%/3%/4%/5%/<0% 各档? 二板走强走多少最好
(>7? >8? 7.5/8.5?)? 三板(今天)>6% 后再细分? 全面细网格, 不预设四档边界。
口径: 二接三阳 × 今开6~9.5(强开池), 逐维度细箱扫描。
宿主机纯CSV: uv run python relay_combo9.py
"""
import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 480)
pd.set_option("display.max_rows", 400)

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
    return M[(M["组"] == "二接三") & (M["阴阳"] == "阳")
             & (M["买入开盘%"] >= 6) & (M["买入开盘%"] < 9.5)].copy()


def stat(M, by):
    return M.groupby(by, observed=True).agg(**AGG).round(3)


def scan(M, col, bins, labels, title):
    print("=" * 110)
    print(f"{title}")
    print("=" * 110)
    t = M.groupby(pd.cut(M[col], bins, labels=labels, right=False), observed=False).agg(**AGG)
    print(t.round(3).to_string())
    print()


if __name__ == "__main__":
    S = load()
    print(f"二接三阳 × 今开6~9.5 强开池: {len(S)}笔\n")

    # ── ① 一板开盘% 细扫: <0% / 0~1 / 1~2 / 2~3 / 3~4 / 4~5 / 5~7 / ≥7 ──
    scan(S, "b1开盘%", [-99, 0, 1, 2, 3, 4, 5, 7, 99],
         ["<0", "0~1", "1~2", "2~3", "3~4", "4~5", "5~7", "≥7"],
         "① 一板开盘% 细箱 (今开6~9.5 全池)")

    # ── ② 二板开盘% 细扫: 半%步长走强段 ──
    scan(S, "b2开盘%", [-99, -3, 0, 1, 2, 3, 5, 7, 7.5, 8, 8.5, 9, 9.5, 99],
         ["<-3", "-3~0", "0~1", "1~2", "2~3", "3~5", "5~7",
          "7~7.5", "7.5~8", "8~8.5", "8.5~9", "9~9.5", "≥9.5一字"],
         "② 二板开盘% 细箱 (今开6~9.5 全池)")

    # ── ③ 今天开盘% 细扫 ──
    scan(S, "买入开盘%", [5.999, 6.5, 7, 7.5, 8, 8.5, 9, 9.5],
         ["6~6.5", "6.5~7", "7~7.5", "7.5~8", "8~8.5", "8.5~9", "9~9.5"],
         "③ 今天开盘% 细箱 (强开池内)")

    # ── ④ 一板×二板 二维矩阵: 一板3档(<0/0~3/≥3) × 二板细档 ──
    B1C = pd.cut(S["b1开盘%"], [-99, 0, 3, 99], labels=["一板<0", "一板0~3", "一板≥3"])
    B2C = pd.cut(S["b2开盘%"], [-99, 0, 2, 3, 5, 7, 8.5, 9.5, 99],
                 labels=["<0", "0~2", "2~3", "3~5", "5~7", "7~8.5", "8.5~9.5", "一字"])
    print("=" * 110)
    print("④ 一板×二板 矩阵: n | 胜率 | 收益 (今开6~9.5)")
    print("=" * 110)
    g = S.groupby([B1C, B2C], observed=True)
    for (a, b), sub in g:
        print(f"{a} × 二板{b}: {len(sub):3d}笔 胜{sub['胜'].mean()*100:3.0f}% "
              f"连板{sub['次日连板'].mean()*100:3.0f}% 均{sub['持有到断板%'].mean():+7.2f}")
    print()

    # ── ⑤ 主人猜想: 一板<3 × 二板细档 × 今开>6 ──
    print("=" * 110)
    print("⑤ 一板<3% × 二板细档 (A1/A2 优化候选框架)")
    print("=" * 110)
    T = S[S["b1开盘%"] < 3]
    for lo, hi, lab in [(-99, 0, "二板<0"), (0, 1, "0~1"), (1, 2, "1~2"), (2, 3, "2~3"),
                        (3, 5, "3~5"), (5, 7, "5~7"), (7, 8.5, "7~8.5"),
                        (8.5, 9.5, "8.5~9.5"), (9.5, 99, "一字")]:
        sub = T[(T["b2开盘%"] >= lo) & (T["b2开盘%"] < hi)]
        if not len(sub):
            continue
        y = sub.groupby("年")["胜"].agg(["size", "mean"])
        ys = " ".join(f"{i}年{int(r['size'])}笔{r['mean']*100:.0f}%" for i, r in y.iterrows())
        print(f"二板{lab}: {len(sub):3d}笔 胜{sub['胜'].mean()*100:3.0f}% "
              f"连板{sub['次日连板'].mean()*100:3.0f}% 均{sub['持有到断板%'].mean():+7.2f} | {ys}")
    print()

    # ── ⑥ 二板换手% 验证: 开盘档 vs 换手率 谁是真判别器 ──
    scan(S, "b2换手%", [-1, 3, 5, 8, 12, 18, 999],
         ["<3", "3~5", "5~8", "8~12", "12~18", "≥18"],
         "⑥ 二板换手率% 细箱 (开盘档之外的真判别器验证)")
    print("--- ⑥b 二板一字(≥9.5)池内 × 二板换手率 ---")
    YZ = S[S["b2开盘%"] >= 9.5]
    for lo, hi in [(-1, 3), (3, 5), (5, 8), (8, 12), (12, 999)]:
        sub = YZ[(YZ["b2换手%"] >= lo) & (YZ["b2换手%"] < hi)]
        if not len(sub):
            continue
        print(f"一字×换手{lo}~{hi}: {len(sub)}笔 胜{sub['胜'].mean()*100:.0f}% "
              f"均{sub['持有到断板%'].mean():+.2f}")
    print("--- ⑥c 二板强开7~9.5池内 × 二板换手率 ---")
    HS = S[(S["b2开盘%"] >= 7) & (S["b2开盘%"] < 9.5)]
    for lo, hi in [(-1, 5), (5, 8), (8, 12), (12, 999)]:
        sub = HS[(HS["b2换手%"] >= lo) & (HS["b2换手%"] < hi)]
        if not len(sub):
            continue
        print(f"强开×换手{lo}~{hi}: {len(sub)}笔 胜{sub['胜'].mean()*100:.0f}% "
              f"均{sub['持有到断板%'].mean():+.2f}")
