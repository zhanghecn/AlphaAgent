# -*- coding: utf-8 -*-
"""高位接力 · 好票坏票全过程对比（第十七遍, 主人纠正: 不能只看聚合统计）。

两件事:
1. 全过程档案: 每笔接力从地基日→首板→…→买入日→次日→断板日, 每天的
   开高低收/涨跌/换手/板型/触板时间/开口段数/封板时间/最深回落 —— 好票坏票逐项对比中位数;
2. 代表票摊开看: 二接三每个板型家族(首板一字/下影/实体 × 二板一字/下影/实体)里
   各挑最好和最差1~2笔(要有15m数据的), 打印逐日过程。

容器内跑: python /tmp/research/relay_journey.py
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
               ("前波60日最高板", "前波60日"), ("昨日涨停家数", "昨日涨停家数"),
               ("b1开盘%", "首板开盘%"), ("b1换手%", "首板换手%"), ("b1下影%", "首板下影%"),
               ("b2开盘%", "二板开盘%"), ("b2换手%", "二板换手%"), ("b2下影%", "二板下影%"),
               ("换手梯度", "换手梯度"), ("买入开盘%", "进三开盘%")]
MIN_FEATS = [("触板分钟", "进三触板分钟"), ("开口段数", "进三开口段数"), ("最深回落%", "进三最深回落%"),
             ("b1开口段数", "首板开口段数"), ("b2开口段数", "二板开口段数")]


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


def cmp_block(sub, title, lines):
    good = sub[sub["胜"]]
    bad = sub[~sub["胜"]]
    lines.append(f"\n### {title}：好票 {len(good)} 笔 vs 坏票 {len(bad)} 笔")
    lines.append("")
    lines.append("| 特征 | 好票中位 | 坏票中位 | 差 | 判断 |")
    lines.append("|---|---|---|---|---|")
    for col, label in DAILY_FEATS + MIN_FEATS:
        g_, b_ = good[col].dropna(), bad[col].dropna()
        if len(g_) < 5 or len(b_) < 5:
            continue
        gm, bm = g_.median(), b_.median()
        diff = gm - bm
        judge = "✅有区分" if abs(diff) > 0.5 * (sub[col].std() + 1e-9) and abs(diff) > 0.3 else ""
        lines.append(f"| {label} | {gm:+.2f} | {bm:+.2f} | {diff:+.2f} | {judge} |")
    # 类别特征分布对比
    for col, label in [("b1板型", "首板板型"), ("b2板型", "二板板型"), ("均线", "均线排列")]:
        cg = good[col].value_counts(normalize=True)
        cb = bad[col].value_counts(normalize=True)
        cats = sorted(set(cg.index) | set(cb.index))
        row_g = " ".join(f"{c}:{cg.get(c, 0)*100:.0f}%" for c in cats)
        row_b = " ".join(f"{c}:{cb.get(c, 0)*100:.0f}%" for c in cats)
        lines.append(f"| {label}分布 | {row_g} | {row_b} | | |")
    # 首刻比例
    if good["触板分钟"].notna().sum() >= 5 and bad["触板分钟"].notna().sum() >= 5:
        fg = (good["触板分钟"] <= 585).mean() * 100
        fb = (bad["触板分钟"] <= 585).mean() * 100
        lines.append(f"| 首刻触板比例 | {fg:.0f}% | {fb:.0f}% | {fg-fb:+.0f}pp | "
                     f"{'✅有区分' if abs(fg-fb) >= 10 else ''} |")


def ticket_block(eng, r, N):
    """一票的逐日过程表。"""
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
    hi = min(len(bars) - 1, p + max(3, int(r.get("持有天数", 1) or 1)))
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
    head = (f"#### {r['名称']} {day}（{'好票' if r['胜'] else '坏票'}，{r['四组']}，"
            f"链={r['链']}，进三开盘{r['买入开盘%']:+.1f}%，次日{r['次日收%']:+.1f}%，"
            f"持有到断板{r['持有到断板%']:+.1f}%）")
    touch = []
    for k, lab in ((1, "首板"), (2, "二板"), (3, "三板")):
        if N >= k:
            os_ = r.get(f"b{k}开口段数")
            touch.append(f"{lab}开口{int(os_) if os_ == os_ else '?'}段")
    if r.get("触板分钟") == r.get("触板分钟"):
        hh, m2 = int(r["触板分钟"] // 60), int(r["触板分钟"] % 60)
        touch.append(f"进三触板{hh:02d}:{m2:02d}")
        touch.append(f"开口{int(r['开口段数'])}段" if r.get("开口段数") == r.get("开口段数") else "")
        touch.append(f"最深回落{r['最深回落%']:+.1f}%")
    return head + "\n（" + "，".join(touch) + "）\n\n```\n" + "\n".join(lines) + "\n```\n"


def main():
    E = load_all()
    eng = create_engine(os.environ["DATABASE_URL"])
    lines = ["# 高位接力 · 好票坏票全过程对比（2026-09-19 第十七遍）", "",
             "每笔接力从地基日到断板日的全过程特征，好票（次日不亏）vs 坏票（次日亏）逐项对比。",
             "触板/开口字段只有 2024-08-15 起（通达信15m存档深度），日线字段全窗。", ""]
    for gname in ["二接三阴", "二接三阳", "三接四阴", "三接四阳"]:
        sub = E[E["四组"] == gname]
        cmp_block(sub, f"{gname} 全组", lines)
        # 板型家族细分: 首板一字 vs 非一字
        cmp_block(sub[sub["b1板型"] == "一字"], f"{gname} · 首板一字", lines)
        cmp_block(sub[sub["b1板型"] == "下影"], f"{gname} · 首板下影", lines)
        cmp_block(sub[sub["b1板型"] == "实体"], f"{gname} · 首板实体", lines)

    # 代表票: 二接三 每个板型家族的好坏各1笔(有15m数据的优先)
    lines.append("\n## 代表票逐日过程（二接三，板型家族好坏对照）\n")
    for gname in ["二接三阴", "二接三阳"]:
        sub = E[E["四组"] == gname]
        for b1t in ["一字", "下影", "实体"]:
            fam = sub[sub["b1板型"] == b1t].copy()
            fam15 = fam[fam["触板分钟"].notna()]
            if len(fam15) < 4:
                continue
            good = fam15[fam15["胜"]].sort_values("持有到断板%", ascending=False)
            bad = fam15[~fam15["胜"]].sort_values("持有到断板%")
            picks = []
            if len(good):
                picks.append(good.iloc[0])
            if len(bad):
                picks.append(bad.iloc[0])
            lines.append(f"\n### {gname} · 首板{b1t}家族\n")
            for r in picks:
                lines.append(ticket_block(eng, r, 2))
    text = "\n".join(lines)
    print(text[:6000])
    with open(MD_OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"\n已写 {MD_OUT}")


if __name__ == "__main__":
    main()
