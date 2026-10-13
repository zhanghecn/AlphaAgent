# -*- coding: utf-8 -*-
"""高位接力 · 主人形态猜想验证（第十五遍）：二进三的板型加速结构。

主人猜想: 二进三 = ①首板不要一字 ②二板走加速(一字 或 高开多少比较好)
③进三(买入日)高开多少比较合适。
逐层验证, 每层给 n/胜率/持有到断板/分年; 最后和现有 B1/B2 格子对比。
"""
import numpy as np
import pandas as pd

pd.set_option("display.width", 340)
pd.set_option("display.max_columns", 100)
CSV = "/root/project/ai/vnpy/量化因子研究/高位接力/全量明细.csv"
YEARS = ["2023", "2024", "2025", "2026"]


def yearly_str(sub):
    by = sub.groupby("年")["持有到断板%"].agg(["size", "mean"])
    return " ".join(f"{y}:{float(by.loc[y,'mean']):+.2f}(n={int(by.loc[y,'size'])})"
                    for y in YEARS if y in by.index)


def line(tag, sub):
    if len(sub) == 0:
        print(f"    {tag}: 空")
        return
    w = (sub["次日收%"] > 0).mean() * 100
    print(f"    {tag:26s} n={len(sub):4d} 胜率{w:3.0f}% 持有{sub['持有到断板%'].mean():+6.2f} | {yearly_str(sub)}")


def main():
    E = pd.read_csv(CSV)
    E = E[~E["未完"]].copy()
    E["年"] = E["年"].astype(str)
    E["换手梯度"] = E["b2换手%"] - E["b1换手%"]
    E["二板加速"] = E["b2开盘%"] > E["b1开盘%"]

    for gname in ["二接三阴", "二接三阳"]:
        sub = E[E["四组"] == gname].copy()
        print(f"\n{'='*100}\n【{gname}】n={len(sub)} 池胜率{(sub['次日收%']>0).mean()*100:.0f}% "
              f"持有{sub['持有到断板%'].mean():+.2f}")

        print("\n  ① 首板一字 vs 非一字（主人: 一板不要一字）")
        line("首板一字", sub[sub["b1板型"] == "一字"])
        line("首板非一字", sub[sub["b1板型"] != "一字"])
        base = sub[sub["b1板型"] != "一字"].copy()

        print("\n  ② 首板非一字后, 二板形态（一字=最强加速）")
        line("二板一字", base[base["b2板型"] == "一字"])
        line("二板下影", base[base["b2板型"] == "下影"])
        line("二板实体", base[base["b2板型"] == "实体"])

        print("\n  ②b 首板非一字 × 二板开盘档（高开多少好）")
        b2_edges = [(-99, 0, "低开"), (0, 3, "0~3"), (3, 6, "3~6"), (6, 9.5, "6~9.5"), (9.5, 99, "顶格开")]
        for lo, hi, tag in b2_edges:
            line(f"二板开盘{tag}", base[(base["b2开盘%"] >= lo) & (base["b2开盘%"] < hi)])

        print("\n  ②c 首板非一字 × 二板是否加速（二板开盘 > 首板开盘）")
        line("二板加速", base[base["二板加速"]])
        line("二板减速", base[~base["二板加速"]])

        print("\n  ③ 首板非一字 × 二板加速 之后, 进三竞价开盘档")
        acc = base[base["二板加速"]]
        for lo, hi, tag in [(-99, 0, "低开"), (0, 2, "0~2"), (2, 4, "2~4"), (4, 6, "4~6"),
                            (6, 8, "6~8"), (8, 9.5, "8~9.5"), (9.5, 99, "顶格开")]:
            line(f"进三开盘{tag}", acc[(acc["买入开盘%"] >= lo) & (acc["买入开盘%"] < hi)])

        print("\n  ④ 组合最佳格探索: 首板非一字 × 二板开盘档 × 进三开盘档")
        best = []
        for blo, bhi, btag in b2_edges:
            for alo, ahi, atag in [(-99, 0, "低开"), (0, 4, "0~4"), (4, 7, "4~7"), (7, 9.5, "7~9.5"), (9.5, 99, "顶格")]:
                s2 = base[(base["b2开盘%"] >= blo) & (base["b2开盘%"] < bhi)
                          & (base["买入开盘%"] >= alo) & (base["买入开盘%"] < ahi)]
                if len(s2) >= 25:
                    best.append((float((s2["次日收%"] > 0).mean()), float(s2["持有到断板%"].mean()),
                                 len(s2), btag, atag, s2))
        best.sort(key=lambda x: -x[1])
        for wr, bw, n, btag, atag, s2 in best[:5]:
            print(f"    二板{btag} × 进三{atag}: n={n} 胜率{wr*100:.0f}% 持有{bw:+.2f} | {yearly_str(s2)}")

        # 与现有格子对比
        b1 = sub[(sub["b2开盘%"].between(6, 9.5, inclusive="left")) & (sub["换手梯度"].between(0, 2, inclusive="left"))]
        b2c = sub[(sub["距60日新高%"].between(-9, -2, inclusive="left")) & (sub["b2开盘%"] < 0)]
        if gname == "二接三阴":
            line("对照B1(二板高开6~9.5×换手微增)", b1)
        else:
            line("对照B2(地基2~9×二板低开)", b2c)


if __name__ == "__main__":
    main()
