# -*- coding: utf-8 -*-
"""诊断: 2板系「曾收顶上(topped)/U突破贴顶」被排除票的全样本表现.

起因: 协鑫集成002506 2026-02-04(D0) 被 topped=True 排除, 实际+39.2%.
主人质疑: 涨停才出坑的不算贴顶, 标准U可以打板.
本脚本用服务侧回测同一事件帧+同一板留断走回放, 量被排除子群:
  A) 2板阳 × topped=True × pull>-4%(突破贴顶, 协鑫同款)
  B) 2板阳 × topped=True × pull<=-4%(曾收顶上但信号日仍在坑里)
  C) 2板阴 × topped=True
  D) 参照: 2板阳当前白名单(yang2a+yang2b出手), 2板阴当前白名单
另外核查协鑫集成个案在帧内的归属.
"""
import sys

sys.path.insert(0, "/app")

import pandas as pd

from alphaagent.server.services.weak_to_strong import backtest as bt
from alphaagent.server.services.weak_to_strong import u_shape


def sim(e: pd.DataFrame) -> pd.DataFrame:
    """对任意子集跑同一板留断走回放(把 actionable 置真复用 _trades_for)。"""
    e = e.copy()
    e["actionable"] = True
    return bt._trades_for(e)


def report(name: str, e: pd.DataFrame) -> None:
    t = sim(e[e["touch"] & ~e["one_word"]])
    if not len(t):
        print(f"{name}: n=0")
        return
    bw = t["ret_bw"].dropna()
    d1 = t["ret_d1"].dropna()
    yr = t.assign(y=pd.to_datetime(t["entry_date"]).dt.year).groupby("y")["ret_bw"].agg(["count", "mean"])
    yr_s = "  ".join(f"{int(y)}:{int(r['count'])}笔{r['mean']*100:+.2f}" for y, r in yr.iterrows())
    print(f"{name}: n={len(t)} 封板率={t['seal'].mean():.2f} D1均={d1.mean()*100:+.2f} "
          f"bw均={bw.mean()*100:+.2f} bw胜率={(bw > 0).mean():.2f} 中位={bw.median()*100:+.2f}")
    print(f"    分年: {yr_s}")


def main() -> None:
    T = bt._build_events()
    print(f"事件帧: {len(T)} 行")

    yang2 = T["group_key"].isin([u_shape.GROUP_YANG2A, u_shape.GROUP_YANG2B])
    yin2 = T["group_key"] == u_shape.GROUP_YIN2

    # 个案核查
    case = T[(T["vt_symbol"] == "002506.SZSE")]
    cols = ["trade_date", "group_key", "u_base", "pos3", "low_dd", "pull", "reb",
            "topped", "ma_st", "gap_d0", "touch", "one_word", "actionable"]
    print("\n协鑫集成事件行:")
    print(case[cols].to_string(index=False))

    # 当前白名单参照(2板系)
    report("参照·2板阳白名单(yang2a+b)", T[yang2 & T["actionable"]])
    report("参照·2板阴白名单(yin2)", T[yin2 & T["actionable"]])

    # 被排除子群
    report("A·2板阳 topped×突破(pull>-4%)", T[yang2 & T["topped"] & (T["pull"] > -0.04)])
    report("B·2板阳 topped×仍在坑(pull<=-4%)", T[yang2 & T["topped"] & (T["pull"] <= -0.04)])
    report("C·2板阴 topped", T[yin2 & T["topped"]])

    # 更细: 突破组按是否全多头/坑深拆
    a = T[yang2 & T["topped"] & (T["pull"] > -0.04)]
    report("A1·突破×全多头+++", a[a["ma_st"] == "+++"])
    report("A2·突破×非全多头", a[a["ma_st"] != "+++"])
    report("A3·突破×浅坑(>-8%)", a[a["low_dd"] > -0.08])
    report("A4·突破×深坑(<=-8%)", a[a["low_dd"] <= -0.08])


if __name__ == "__main__":
    main()
