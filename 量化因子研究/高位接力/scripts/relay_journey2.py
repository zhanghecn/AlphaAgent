# -*- coding: utf-8 -*-
"""高位接力 · 好票坏票全过程对比 · 全家族版（第十八遍, 主人要求: 看全部）。

四组 × 全部板型链家族:
- 二接三阴/阳: 家族=首板型×二板型(3×3=9)
- 三接四阴/阳: 家族=首板型×二板型×三板型(3×3×3=27)
每个家族: 好票vs坏票全特征中位对比(地基/首板/二板/三板/进三竞价/触板开口/环境)
+ 家族内进三竞价档拆解 + 好票坏票代表各1笔逐日全过程。
家族按持有到断板均值排序(最好的在前), 小样本也显示不藏。
买入当天走势类字段(最深回落/开口段数)标【结果侧】=只能看不能当买入条件。

容器内跑: python /tmp/research/relay_journey2.py
"""
import os
import sys

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

pd.set_option("display.width", 340)
pd.set_option("display.max_columns", 100)
IN_DIR = "/tmp/research/relay_out"
MD_OUT = f"{IN_DIR}/好票坏票全过程.md"

DAILY_FEATS = [("地基涨跌%", "地基日涨跌"), ("距60日新高%", "地基距新高%"), ("地基前20日涨幅%", "地基前20日涨幅"),
               ("前波60日最高板", "前波60日"), ("昨日涨停家数", "昨日涨停家数(环境)"),
               ("b1开盘%", "首板开盘%"), ("b1换手%", "首板换手%"), ("b1下影%", "首板下影%"),
               ("b2开盘%", "二板开盘%"), ("b2换手%", "二板换手%"), ("b2下影%", "二板下影%"),
               ("换手梯度", "换手梯度(二板-首板)"), ("买入开盘%", "进三开盘%")]
MIN_FEATS = [("触板分钟", "进三触板分钟"), ("开口段数", "进三开口段数【结果侧】"),
             ("最深回落%", "进三最深回落%【结果侧】"),
             ("b1开口段数", "首板开口段数"), ("b2开口段数", "二板开口段数"), ("b3开口段数", "三板开口段数")]
AUC = [(-99, 0, "低开"), (0, 3, "0~3"), (3, 6, "3~6"), (6, 9.5, "6~9.5"), (9.5, 99, "顶格开")]
BOARD = ["一字", "下影", "实体"]


def load_all():
    E = pd.read_csv(f"{IN_DIR}/全量明细.csv")
    E = E[~E["未完"]].copy()
    E["年"] = E["年"].astype(str)
    E["换手梯度"] = E["b2换手%"] - E["b1换手%"]
    E["胜"] = E["次日收%"] > 0
    T = pd.read_csv(f"{IN_DIR}/触板时间明细-全量.csv", dtype={"代码": str})
    mm = pd.to_datetime(T["触板时间"], format="%H:%M", errors="coerce")
    T["触板分钟"] = mm.dt.hour * 60 + mm.dt.minute
    sm = pd.to_datetime(T["封板时间"], format="%H:%M", errors="coerce")
    T["封板分钟"] = sm.dt.hour * 60 + sm.dt.minute
    E = E.merge(T[["代码", "买入日", "触板分钟", "封板分钟", "开口段数", "最深回落%",
                   "b1开口段数", "b2开口段数", "b3开口段数"]],
                on=["代码", "买入日"], how="left")
    return E


def med_str(g, b, col):
    g_, b_ = g[col].dropna(), b[col].dropna()
    if len(g_) < 3 or len(b_) < 3:
        return None
    return g_.median(), b_.median()


def cmp_block(sub, title, lines, n_boards):
    good = sub[sub["胜"]]
    bad = sub[~sub["胜"]]
    lines.append(f"\n#### {title}：好票 {len(good)} 笔 vs 坏票 {len(bad)} 笔\n")
    lines.append("| 特征 | 好票中位 | 坏票中位 | 差 | 判断 |")
    lines.append("|---|---|---|---|---|")
    feats = DAILY_FEATS[:]
    if n_boards < 3:
        feats = [f for f in feats if "三板" not in f[1]]
    for col, label in feats + MIN_FEATS:
        r = med_str(good, bad, col)
        if r is None:
            continue
        gm, bm = r
        diff = gm - bm
        std = sub[col].std()
        judge = "✅" if std > 0 and abs(diff) > 0.5 * std and abs(diff) > 0.3 else ""
        lines.append(f"| {label} | {gm:+.2f} | {bm:+.2f} | {diff:+.2f} | {judge} |")
    # 板型/均线分布
    for col, label in [("均线", "均线排列")]:
        cg = good[col].value_counts(normalize=True)
        cb = bad[col].value_counts(normalize=True)
        cats = sorted(set(cg.index) | set(cb.index))
        lines.append(f"| {label}分布 | 好: " + " ".join(f"{c}:{cg.get(c,0)*100:.0f}%" for c in cats)
                     + " | 坏: " + " ".join(f"{c}:{cb.get(c,0)*100:.0f}%" for c in cats) + " | | |")
    if good["触板分钟"].notna().sum() >= 3 and bad["触板分钟"].notna().sum() >= 3:
        fg = (good["触板分钟"] <= 585).mean() * 100
        fb = (bad["触板分钟"] <= 585).mean() * 100
        lines.append(f"| 首刻触板比例 | {fg:.0f}% | {fb:.0f}% | {fg-fb:+.0f}pp |"
                     f" {'✅' if abs(fg-fb) >= 10 else ''} |")
    # 家族内 进三竞价档拆解
    lines.append("")
    lines.append("| 进三竞价档 | 笔数 | 胜率 | 持有均值 |")
    lines.append("|---|---|---|---|")
    for lo, hi, tag in AUC:
        s2 = sub[(sub["买入开盘%"] >= lo) & (sub["买入开盘%"] < hi)]
        if len(s2):
            lines.append(f"| {tag} | {len(s2)} | {(s2['胜'].mean())*100:.0f}% "
                         f"| {s2['持有到断板%'].mean():+.2f} |")


def ticket_block(eng, r, N):
    code, day = r["代码"], r["买入日"]
    bars = pd.read_sql(f"select trade_date, open_price, high_price, low_price, close_price, "
                       f"turnover_rate from stock_daily_bars where vt_symbol='{code}' "
                       f"and trade_date <= '{day}'::date + 20 order by 1", eng,
                       parse_dates=["trade_date"])
    bars["trade_date"] = bars["trade_date"].dt.strftime("%Y-%m-%d")
    hit = bars.index[bars["trade_date"] == day]
    if len(hit) == 0:
        return ""
    p = int(hit[0])
    lo = max(0, p - N - 3)
    hd = r.get("持有天数")
    hi = min(len(bars) - 1, p + max(3, int(hd) if hd == hd else 3))
    lines = ["日期         开盘    最高    最低    收盘   涨跌%  换手%  标记"]
    prev = None
    for i in range(lo, hi + 1):
        b = bars.loc[i]
        chg = (b["close_price"] / prev - 1) * 100 if prev else np.nan
        mark = ""
        if i == p - N - 1:
            mark = "←地基日"
        elif p - N <= i < p:
            mark = f"←第{i-(p-N)+1}板"
        elif i == p:
            mark = "←买入日(打板)"
        elif i == p + 1:
            mark = "←次日"
        prev = b["close_price"]
        lines.append(f"{b['trade_date']}  {b['open_price']:7.2f} {b['high_price']:7.2f} "
                     f"{b['low_price']:7.2f} {b['close_price']:7.2f} {chg:+6.2f} "
                     f"{b['turnover_rate']:6.1f}  {mark}")
    head = (f"**{r['名称']} {day}（{'好票' if r['胜'] else '坏票'}，链={r['链']}，"
            f"进三开盘{r['买入开盘%']:+.1f}%，次日{r['次日收%']:+.1f}%，持有到断板{r['持有到断板%']:+.1f}%）**")
    touch = []
    for k, lab in ((1, "首板"), (2, "二板"), (3, "三板")):
        if N >= k:
            os_ = r.get(f"b{k}开口段数")
            touch.append(f"{lab}开口{int(os_) if os_ == os_ else '?'}段")
    if r.get("触板分钟") == r.get("触板分钟"):
        hh, m2 = int(r["触板分钟"] // 60), int(r["触板分钟"] % 60)
        touch.append(f"进三触板{hh:02d}:{m2:02d}")
        if r.get("开口段数") == r.get("开口段数"):
            touch.append(f"开口{int(r['开口段数'])}段")
        if r.get("最深回落%") == r.get("最深回落%"):
            touch.append(f"最深回落{r['最深回落%']:+.1f}%")
    return head + "\n（" + "，".join(touch) + "）\n\n```\n" + "\n".join(lines) + "\n```\n"


def main():
    E = load_all()
    eng = create_engine(os.environ["DATABASE_URL"])
    lines = ["# 高位接力 · 好票坏票全过程对比 · 全家族版（2026-09-19 第十八遍）", "",
             "四组 × 全部板型链家族（二接三=首板×二板 9 个；三接四=首板×二板×三板 27 个），",
             "每个家族：好票vs坏票全特征中位对比 + 进三竞价档拆解 + 代表票逐日全过程。",
             "家族按持有到断板均值排序（最好的在前）。小样本也显示不藏。",
             "【结果侧】= 买入当天走势字段，只能用于卖出纪律，不能当买入条件。", ""]
    for gname, n_boards in [("二接三阴", 2), ("二接三阳", 2), ("三接四阴", 3), ("三接四阳", 3)]:
        sub = E[E["四组"] == gname].copy()
        if n_boards == 2:
            sub["家族"] = sub["b1板型"] + "→" + sub["b2板型"]
        else:
            sub["家族"] = sub["b1板型"] + "→" + sub["b2板型"] + "→" + sub["b3板型"]
        lines.append(f"\n# 【{gname}】n={len(sub)} 池胜率{sub['胜'].mean()*100:.0f}% "
                     f"持有{sub['持有到断板%'].mean():+.2f}")

        # 全组对比
        cmp_block(sub, f"{gname} 全组", lines, n_boards)

        # 家族总览矩阵
        fam_stat = sub.groupby("家族").agg(n=("胜", "size"), 胜率=("胜", "mean"),
                                           持有=("持有到断板%", "mean")).sort_values("持有", ascending=False)
        lines.append(f"\n### {gname} 家族总览（按持有排序）\n")
        lines.append("| 家族 | 笔数 | 胜率 | 持有到断板 |")
        lines.append("|---|---|---|---|")
        for fam, r in fam_stat.iterrows():
            lines.append(f"| {fam} | {int(r['n'])} | {r['胜率']*100:.0f}% | {r['持有']:+.2f} |")

        # 家族明细 + 代表票
        lines.append(f"\n### {gname} 家族明细与代表票")
        for fam, r in fam_stat.iterrows():
            fam_sub = sub[sub["家族"] == fam]
            if len(fam_sub) < 15:
                continue
            cmp_block(fam_sub, f"家族 {fam}", lines, n_boards)
            fam15 = fam_sub[fam_sub["触板分钟"].notna()]
            pool = fam15 if len(fam15) >= 4 else fam_sub
            good = pool[pool["胜"]].sort_values("持有到断板%", ascending=False)
            bad = pool[~pool["胜"]].sort_values("持有到断板%")
            for pick in ([good.iloc[0]] if len(good) else []) + ([bad.iloc[0]] if len(bad) else []):
                lines.append(ticket_block(eng, pick, n_boards))

    text = "\n".join(lines)
    with open(MD_OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"写入 {MD_OUT}, 共 {len(text.splitlines())} 行")
    # 打印总览部分供快速查看
    for gname, n_boards in [("二接三阴", 2), ("二接三阳", 2), ("三接四阴", 3), ("三接四阳", 3)]:
        sub = E[E["四组"] == gname].copy()
        if n_boards == 2:
            sub["家族"] = sub["b1板型"] + "→" + sub["b2板型"]
        else:
            sub["家族"] = sub["b1板型"] + "→" + sub["b2板型"] + "→" + sub["b3板型"]
        fam_stat = sub.groupby("家族").agg(n=("胜", "size"), 胜率=("胜", "mean"),
                                           持有=("持有到断板%", "mean")).sort_values("持有", ascending=False)
        print(f"\n【{gname}】家族总览:")
        print(fam_stat.round(2).to_string())


if __name__ == "__main__":
    main()
