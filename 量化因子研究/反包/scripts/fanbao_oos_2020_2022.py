# -*- coding: utf-8 -*-
"""断板反包 样本外检验 2020~2022 —— 复用产品引擎(fanbao/backtest.build_events)前推窗口。

口径 = 产品 fbb-v2.3 引擎逐字复用, 仅 monkeypatch:
    BARS_START "2022-06-01"→"2019-06-01"(同样 7 个月暖机深度)
    REPLAY_START 2023-01-01→2020-01-01
产出:
    oos_yearly.csv     分年×方案点(S1/S2/S3/S级/all/miss)全指标
    oos_matrix18.csv   18格(六组×断1/2/3)分年 n/bw/win/avg
    oos_dead.csv       死格分年(命中也不买, 验证样本外也该死)
    oos_trades.csv     2020~2022 出手逐笔(S级=all 口径)
    2023+顺带重算分年 → 与产品物化报告对表(应仅 ±微差)
用法(容器内): python /tmp/research/fanbao_oos_2020_2022.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/app")

import alphaagent.server.services.fanbao.backtest as fbt  # noqa: E402
from alphaagent.server.services.fanbao import contracts  # noqa: E402

OUT = "/tmp/research/fanbao_oos_out"


def stats(e: pd.DataFrame) -> dict:
    if not len(e):
        return {"n": 0}
    d1 = e["次日收%"].dropna()
    bw = e["持有到断板%"].dropna()
    sealed = e[e["封住"]]
    return {
        "n": int(len(e)),
        "avg_pct": round(float(d1.mean()), 2) if len(d1) else None,
        "win": round(float((d1 >= 0).mean()), 3) if len(d1) else None,
        "bad": round(float(e["坏票"].mean()), 3),
        "seal": round(float(e["封住"].mean()), 3),
        "bw_pct": round(float(bw.mean()), 2) if len(bw) else None,
        "bw_median": round(float(bw.median()), 2) if len(bw) else None,
        "bw_win": round(float((bw > 0).mean()), 3) if len(bw) else None,
        "sum_pct": round(float(bw.sum()), 1) if len(bw) else None,
        "compound_pct": round(float(((1 + bw / 100).prod() - 1) * 100), 1)
        if len(bw) else None,
    }


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    fbt.BARS_START = "2019-06-01"
    fbt.REPLAY_START = pd.Timestamp("2020-01-01")
    E, _ = fbt.build_events()
    done = E[~E["未完"]].copy()
    main_ = done[done["主格"]].copy()
    print(f"事件总数={len(E)} 完成={len(done)} 主格={len(main_)} "
          f"覆盖 {E['买入日'].min():%Y-%m-%d}~{E['买入日'].max():%Y-%m-%d}")

    def subset(key: str) -> pd.DataFrame:
        if key == "all":
            return main_[main_["方案点"] != "—"]
        if key == "S级":
            return main_[main_["方案点"].isin(["S1", "S2", "S3"])]
        if key == "miss":
            return main_[main_["方案点"] == "—"]
        return main_[main_["方案点"] == key]

    keys = list(contracts.POINT_KEYS) + ["S级", "all", "miss"]

    # 1) 分年 × 方案点
    rows = []
    for y, yg in done.groupby("年"):
        ym = yg[yg["主格"]]
        for k in keys:
            frame = ym[ym["方案点"] != "—"] if k == "all" else (
                ym[ym["方案点"].isin(["S1", "S2", "S3"])] if k == "S级" else (
                    ym[ym["方案点"] == "—"] if k == "miss" else ym[ym["方案点"] == k]))
            rows.append({"年": y, "方案点": k, **stats(frame)})
    pd.DataFrame(rows).to_csv(f"{OUT}/oos_yearly.csv", index=False)

    # 2) 18格分年
    rows = []
    for g6 in contracts.GROUP6_KEYS:
        for gap in contracts.GS_MAIN:
            sub = main_[(main_["六组"] == g6) & (main_["断板天数"] == gap)]
            for y, g_ in sub.groupby("年"):
                rows.append({"六组": g6, "断板": gap, "年": y, **stats(g_)})
    pd.DataFrame(rows).to_csv(f"{OUT}/oos_matrix18.csv", index=False)

    # 3) 死格分年(主格内 miss)
    rows = []
    for g6 in contracts.GROUP6_KEYS:
        for gap in contracts.GS_MAIN:
            sub = main_[(main_["六组"] == g6) & (main_["断板天数"] == gap)
                       & (main_["方案点"] == "—")]
            for y, g_ in sub.groupby("年"):
                rows.append({"六组": g6, "断板": gap, "年": y, **stats(g_)})
    pd.DataFrame(rows).to_csv(f"{OUT}/oos_dead.csv", index=False)

    # 4) 出手逐笔 2020~2022
    trades = main_[(main_["方案点"] != "—")
                   & (main_["年"].between("2020", "2022"))].copy()
    cols = ["买入日", "代码", "名称", "方案点", "六组", "断板天数", "N", "阴阳",
            "断板累计%", "断板阴线数", "末日开盘%", "坑深%", "买价", "封住",
            "次日收%", "持有到断板%", "持有天数", "后续板数", "退出原因", "坏票"]
    trades[cols].sort_values("买入日").to_csv(f"{OUT}/oos_trades.csv", index=False)

    # 5) 出手逐月分布(样本外三年)
    m = main_[main_["方案点"] != "—"]
    rows = [{"月": mo, **stats(g_)}
            for mo, g_ in m[m["年"].between("2020", "2022")].groupby("月")]
    pd.DataFrame(rows).to_csv(f"{OUT}/oos_monthly.csv", index=False)

    # 控制台速览
    oos = m[m["年"].between("2020", "2022")]
    print("\n== 出手(all) 分年 ==")
    for y, g_ in m.groupby("年"):
        s = stats(g_)
        print(f"{y}: n={s['n']:>3} avg={s['avg_pct']} win={s['win']} "
              f"bw={s['bw_pct']} med={s['bw_median']} bad={s['bad']}")
    print(f"\n样本外三年出手合计 n={len(oos)}; 逐笔在 {OUT}/oos_trades.csv")


if __name__ == "__main__":
    main()
