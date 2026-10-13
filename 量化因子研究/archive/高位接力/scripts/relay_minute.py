# -*- coding: utf-8 -*-
"""高位接力 · 买入时间研究（第十二遍, 1m子窗口版）。

数据源: stock_minute_bars interval='1m'(DB内, 覆盖2026-01-20~2026-08-12, 198笔接力事件)。
外部通达信/东财分钟接口 2026-09-19 全部不可用(连接不上或不出数据), 历史回补等恢复后补。

计算(每笔买入日):
- 首次触板时间: 第一根 high>=涨停价 的1mK bar_time(口径标注: bar_time是周期开始还是结束, 打印时标明)
- 开口段数(≈炸板次数): 首次触板后, 掉下涨停价(低点 < 涨停价×0.998)再摸回的段数
- 封板时间: 最后一根 high>=涨停价 的bar(当天封住的前提下)
- 触板后最深回落%: 首次触板后~收盘前的最低价 / 涨停价 - 1
- 对照: 东财涨停池快照 first_limit_time/break_count(67笔重叠) 校口径
- 前置板(b1/b2/b3)同日内如有1m数据也记开口段数

分析: 触板时间5m分档 × 封住率/次日胜率/持有到断板, 分组+方案点; 开口段数 × 结局。
输出: /tmp/research/relay_out/触板时间明细.csv + 汇总/买入时间.md
"""
import os
import sys

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

pd.set_option("display.width", 340)
pd.set_option("display.max_columns", 100)

CSV_IN = "/tmp/research/relay_out/全量明细.csv"
OUT = "/tmp/research/relay_out"


def load_minute(eng, vt, day):
    df = pd.read_sql(
        "select bar_time, open_price, high_price, low_price, close_price from stock_minute_bars "
        f"where vt_symbol='{vt}' and trade_date='{day}' and interval='1m' order by bar_time", eng)
    return df


def minute_metrics(mb, limit_px):
    """1m序列 → 触板时间/开口段数/封板时间/最深回落。无触板返回None。"""
    if len(mb) == 0:
        return None
    hi = mb["high_price"].to_numpy()
    lo = mb["low_price"].to_numpy()
    tt = mb["bar_time"].astype(str).str[11:16].to_numpy()
    eps = limit_px * 0.002          # 掉下0.2%才算开口
    at = hi >= limit_px - 1e-6
    if not at.any():
        return None
    first = int(np.argmax(at))
    last = int(len(at) - 1 - np.argmax(at[::-1]))
    # 开口段数: first~last 之间, 低点<limit×0.998 的连续段数(段间以重新摸到板分隔)
    seg = 0
    in_break = False
    for i in range(first, last + 1):
        below = lo[i] < limit_px - eps
        if below and not in_break:
            seg += 1
            in_break = True
        if at[i]:
            in_break = False
    dip = lo[first:].min() / limit_px - 1
    return {"触板时间": tt[first], "封板时间": tt[last], "开口段数": seg,
            "最深回落%": round(dip * 100, 2)}


def main():
    eng = create_engine(os.environ["DATABASE_URL"])
    E = pd.read_csv(CSV_IN)
    E["年"] = E["年"].astype(str)
    E["换手梯度"] = E["b2换手%"] - E["b1换手%"]
    # 方案点
    E["方案点"] = "—"
    E.loc[(E["四组"] == "三接四阳") & E["距60日新高%"].between(-15, -8, inclusive="left")
          & (~E["均线"].isin(["+++", "-++", "+--"])) & (E["前波60日最高板"] == 0), "方案点"] = "A1"
    E.loc[(E["四组"] == "三接四阴") & (E["前波120日最高板"] >= 3)
          & (E["换手梯度"] < -5), "方案点"] = "A2"
    E.loc[(E["四组"] == "二接三阴") & E["b2开盘%"].between(6, 9.5, inclusive="left")
          & E["换手梯度"].between(0, 2, inclusive="left"), "方案点"] = "B1"
    E.loc[(E["四组"] == "二接三阳") & E["距60日新高%"].between(-9, -2, inclusive="left")
          & (E["b2开盘%"] < 0), "方案点"] = "B2"

    # 覆盖检查
    cov = pd.read_sql("""select distinct vt_symbol, trade_date from stock_minute_bars
        where interval='1m' and trade_date>='2026-01-20' and trade_date<='2026-08-12'""", eng)
    cov["trade_date"] = cov["trade_date"].astype(str)
    covset = set(zip(cov["vt_symbol"], cov["trade_date"]))
    E["有分钟数据"] = [(v, d) in covset for v, d in zip(E["代码"], E["买入日"])]
    sub = E[E["有分钟数据"]].copy()
    print(f"1m覆盖窗口内接力事件 {len(sub)} 笔, 开始逐笔算触板指标…")

    # 东财快照对照
    snap = pd.read_sql("""select vt_symbol, trade_date, first_limit_time, break_count
        from limit_up_pool_snapshots where first_limit_time is not null""", eng)
    snap["trade_date"] = snap["trade_date"].astype(str)
    snap_map = {(r["vt_symbol"], r["trade_date"]): (r["first_limit_time"], r["break_count"])
                for _, r in snap.iterrows()}

    rows = []
    for _, r in sub.iterrows():
        vt, day = r["代码"], r["买入日"]
        mb = load_minute(eng, vt, day)
        m = minute_metrics(mb, r["买价"])
        if m is None:
            continue
        rec = {"代码": vt, "名称": r["名称"], "买入日": day, "组": r["组"], "四组": r["四组"],
               "阴阳": r["阴阳"], "方案点": r["方案点"], "买价": r["买价"], "封住": r["封住"],
               "次日收%": r["次日收%"], "持有到断板%": r["持有到断板%"], "结果": r["结果"],
               "买入开盘%": r["买入开盘%"], **m}
        # 快照对照
        sp = snap_map.get((vt, day))
        if sp:
            rec["快照首封"] = str(sp[0])
            rec["快照炸板次数"] = sp[1]
        # 前置板开口段数(有数据才算)
        for k, col in ((1, "b1日"), (2, "b2日"), (3, "b3日")):
            d0 = r.get(col)
            if isinstance(d0, str) and r["N"] >= k:
                # b日列格式是MM-DD, 补年份=买入日年(跨年元旦周取上一年的12月)
                yr = day[:4]
                full = f"{yr}-{d0}"
                if full > day:      # 跨年修正
                    full = f"{int(yr)-1}-{d0}"
                if (vt, full) in covset:
                    mbk = load_minute(eng, vt, full)
                    # 前置板涨停价: 用该日收盘价(=涨停价)
                    if len(mbk):
                        lp = mbk["close_price"].iloc[-1]
                        mk = minute_metrics(mbk, lp)
                        if mk:
                            rec[f"b{k}开口段数"] = mk["开口段数"]
                            rec[f"b{k}封板时间"] = mk["封板时间"]
        rows.append(rec)
    T = pd.DataFrame(rows)
    T.to_csv(f"{OUT}/触板时间明细.csv", index=False, encoding="utf-8-sig")
    print(f"算出 {len(T)} 笔触板指标")

    # 快照口径对照
    cmp_ = T.dropna(subset=["快照炸板次数"])
    if len(cmp_):
        agree = (cmp_["开口段数"] == cmp_["快照炸板次数"]).mean()
        print(f"与东财快照对照({len(cmp_)}笔): 开口段数==炸板次数 比例 {agree*100:.0f}%")
        print(cmp_[["代码", "买入日", "触板时间", "快照首封", "开口段数", "快照炸板次数"]].head(10).to_string(index=False))

    # ===== 分析 =====
    T["胜"] = T["次日收%"] > 0
    T["触板段"] = pd.cut(pd.to_datetime(T["触板时间"], format="%H:%M").dt.hour * 60
                        + pd.to_datetime(T["触板时间"], format="%H:%M").dt.minute,
                        bins=[0, 575, 600, 630, 690, 750, 840, 890, 960],
                        labels=["09:30~35", "09:35~10:00", "10:00~10:30", "10:30~11:30",
                                "13:00~14:00", "14:00~14:30", "14:30~14:50", "14:50~15:00"])
    print("\n== 触板时段 × 结局(全体198笔) ==")
    t = T.groupby("触板段", observed=True).agg(n=("胜", "size"), 封住率=("封住", "mean"),
                                                 胜率=("胜", "mean"), 持有=("持有到断板%", "mean"))
    print(t.round(2).to_string())
    print("\n== 开口段数 × 结局 ==")
    t2 = T.groupby(pd.cut(T["开口段数"], [-1, 0, 1, 2, 99], labels=["0段(一封到底)", "1段", "2段", "3段+"]),
                   observed=True).agg(n=("胜", "size"), 封住率=("封住", "mean"),
                                      胜率=("胜", "mean"), 持有=("持有到断板%", "mean"))
    print(t2.round(2).to_string())
    print("\n== 分组 × 触板时段(胜率%) ==")
    for g in ["二接三阴", "二接三阳", "三接四阴", "三接四阳"]:
        tg = T[T["四组"] == g]
        tt = tg.groupby("触板段", observed=True).agg(n=("胜", "size"), 胜率=("胜", "mean"),
                                                     持有=("持有到断板%", "mean"))
        tt = tt[tt["n"] >= 3]
        print(f"\n【{g}】n={len(tg)}")
        print(tt.round(2).to_string())
    print("\n== 方案点命中票 ==")
    tp = T[T["方案点"] != "—"]
    for p, tp2 in tp.groupby("方案点"):
        print(f"{p}: n={len(tp2)} 胜率{tp2['胜'].mean()*100:.0f}% 持有{tp2['持有到断板%'].mean():+.2f}")
        tq = tp2.groupby("触板段", observed=True).agg(n=("胜", "size"), 胜率=("胜", "mean"))
        print(tq[tq["n"] >= 1].round(2).to_string())


if __name__ == "__main__":
    main()
