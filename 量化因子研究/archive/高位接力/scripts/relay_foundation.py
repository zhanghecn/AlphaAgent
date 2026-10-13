# -*- coding: utf-8 -*-
"""高位接力 · 地基细分 + 均线位置 + 断板反包 全量研究（第十九遍）。

主人指示(2026-09-19): 只看统计不行, 阴阳之外还要看:
1. 地基是大阴还是小阴 / 大阳还是小阳 (地基日涨跌幅度分档);
2. 均线处于什么位置 (地基日收盘 vs 5/10/20/30日线, 站上几条, 均线斜率);
3. 「一板后断板, 再反包重新起板」的链条 (首板之前近期有板→断板→本波首板=反包板)。

本脚本:
- 复用 relay_research.build_events 重建事件(口径完全一致)和日线;
- 给每笔事件补三组新字段, 导出 地基均线反包明细.csv;
- 三个新维度 × 四组的胜率/持有/分年全表 + 与四个方案点交叉;
- 候选组合扫描(分年全正筛选) + 边界晃动;
- 关键对比配代表票逐日K线。

容器内跑: python /tmp/research/relay_foundation.py
输出: /tmp/research/relay_out/汇总/地基均线反包.md + 地基均线反包明细.csv
"""
import os
import sys

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

sys.path.insert(0, "/tmp/research")
import relay_research as rr

OUT = "/tmp/research/relay_out"
YEARS = ["2023", "2024", "2025", "2026"]
GROUPS4 = ["二接三阴", "二接三阳", "三接四阴", "三接四阳"]

SIZE_BINS = ["巨阴≤-5", "大阴-5~-3", "小阴-3~0", "小阳0~3", "大阳3~5", "巨阳≥5"]
MA10_BINS = ["≤-10", "-10~-5", "-5~0", "0~5", "5~10", "≥10"]
FANBAO_BINS = ["60日内无板", "断1天", "断2~3天", "断4~7天", "断8~15天", "断16~60天"]


def size_bin(x):
    if x <= -5:
        return SIZE_BINS[0]
    if x <= -3:
        return SIZE_BINS[1]
    if x < 0:
        return SIZE_BINS[2]
    if x < 3:
        return SIZE_BINS[3]
    if x < 5:
        return SIZE_BINS[4]
    return SIZE_BINS[5]


def ma10_bin(x):
    if x != x:
        return "缺失"
    for i, (lo, hi) in enumerate([(-999, -10), (-10, -5), (-5, 0), (0, 5), (5, 10), (10, 999)]):
        if lo < x <= hi:
            return MA10_BINS[i]
    return MA10_BINS[-1]


def fanbao_bin(gap):
    """gap = 首板日 - 前板日(交易日数)。None=60日内无板。"""
    if gap is None:
        return FANBAO_BINS[0]
    d = gap - 1  # 断板天数
    if d <= 1:
        return "断1天"
    if d <= 3:
        return "断2~3天"
    if d <= 7:
        return "断4~7天"
    if d <= 15:
        return "断8~15天"
    return "断16~60天"


def augment(E, bars):
    """给事件补三组新字段。返回 E2。"""
    cols = {c: bars[c].to_numpy() for c in
            ["close_price", "open_price", "low_price", "high_price", "is_lim", "streak",
             "ma5", "ma10", "ma20", "ma30"]}
    dates = bars["trade_date"].to_numpy()
    sid = bars["sid"].to_numpy()
    sym2sid = dict(zip(bars["vt_symbol"], bars["sid"]))
    key = {}
    for i in range(len(bars)):
        key[(sid[i], dates[i])] = i

    recs = []
    for _, r in E.iterrows():
        s = sym2sid.get(r["代码"])
        i = key.get((s, pd.Timestamp(r["买入日"]).to_datetime64()))
        if i is None:
            recs.append({})
            continue
        N = int(r["N"])
        f = i - N - 1          # 地基日
        b1 = i - N             # 首板日
        rec = {}
        fc = cols["close_price"][f]
        # --- 维度1: 地基大小 ---
        rec["地基档"] = size_bin(r["地基涨跌%"])
        # --- 维度2: 均线位置(地基日) ---
        for w in (5, 10, 20, 30):
            ma = cols[f"ma{w}"][f]
            rec[f"距MA{w}%"] = round((fc / ma - 1) * 100, 1) if ma == ma and ma > 0 else np.nan
        rec["站上均线数"] = int(sum(1 for w in (5, 10, 20, 30)
                                   if rec[f"距MA{w}%"] == rec[f"距MA{w}%"] and rec[f"距MA{w}%"] >= 0))
        rec["MA10位置"] = ("上" if rec["距MA10%"] >= 0 else "下") if rec["距MA10%"] == rec["距MA10%"] else "缺失"
        # 斜率: 均线值 对 5个交易日前的均线值
        for w in (10, 20):
            if f - 5 >= 0 and sid[f - 5] == sid[f]:
                m0, m1 = cols[f"ma{w}"][f - 5], cols[f"ma{w}"][f]
                rec[f"MA{w}斜率%"] = round((m1 / m0 - 1) * 100, 2) if m0 == m0 and m1 == m1 and m0 > 0 else np.nan
            else:
                rec[f"MA{w}斜率%"] = np.nan
        # --- 维度3: 断板反包(首板之前60个交易日内最近一个涨停) ---
        lo = max(0, b1 - 60)
        is_lim_seg = cols["is_lim"][lo:b1]
        idxs = np.flatnonzero(is_lim_seg)
        if len(idxs) == 0:
            rec["前板日"] = None
            rec["断板天数"] = None
            rec["前板高度"] = None
            rec["反包收复%"] = np.nan
            rec["断板回撤%"] = np.nan
            rec["反包结构"] = FANBAO_BINS[0]
        else:
            j = lo + int(idxs[-1])
            gap = b1 - j
            rec["前板日"] = pd.Timestamp(dates[j]).strftime("%m-%d")
            rec["断板天数"] = gap - 1
            rec["前板高度"] = int(cols["streak"][j])
            pc = cols["close_price"][j]
            rec["反包收复%"] = round((cols["close_price"][b1] / pc - 1) * 100, 1)
            seg_lo = cols["low_price"][j + 1:b1]
            rec["断板回撤%"] = round((seg_lo.min() / pc - 1) * 100, 1) if len(seg_lo) else 0.0
            rec["反包结构"] = fanbao_bin(gap)
        recs.append(rec)
    A = pd.DataFrame(recs, index=E.index)
    E2 = pd.concat([E, A], axis=1)
    E2["距MA10档"] = E2["距MA10%"].map(ma10_bin)
    return E2


def tag_scheme(E2):
    """四个方案点打标(与 relay_scheme.py 逐字一致), 校验笔数=定稿49/24/29/16。"""
    grad = E2["b2换手%"] - E2["b1换手%"]
    tag = pd.Series("—", index=E2.index)
    m = (E2["四组"] == "三接四阳") & (E2["距60日新高%"] >= -15) & (E2["距60日新高%"] < -8) & \
        (~E2["均线"].isin(["+++", "-++", "+--"])) & (E2["前波60日最高板"] == 0)
    tag[m] = "A1"
    m = (E2["四组"] == "三接四阴") & (E2["前波120日最高板"] >= 3) & (grad < -5)
    tag[m] = "A2"
    m = (E2["四组"] == "二接三阴") & (E2["b2开盘%"] >= 6) & (E2["b2开盘%"] < 9.5) & \
        (grad >= 0) & (grad < 2)
    tag[m] = "B1"
    m = (E2["四组"] == "二接三阳") & (E2["距60日新高%"] >= -9) & (E2["距60日新高%"] < -2) & \
        (E2["b2开盘%"] < 0) & (E2["买入开盘%"] >= 4) & (E2["买入开盘%"] < 7)
    tag[m] = "B2"
    E2["方案点"] = tag
    fin = E2[~E2["未完"]]
    print("方案点校验(定稿=49/24/29/16):",
          {t: int((fin["方案点"] == t).sum()) for t in ["A1", "A2", "B1", "B2"]})
    return E2


def fmt_cell(sub):
    if len(sub) == 0:
        return "0笔"
    win = (sub["次日收%"] > 0).mean() * 100
    hold = sub["持有到断板%"].mean()
    return f"{len(sub)}笔 {win:.0f}% {hold:+.2f}"


def year_cells(sub):
    out = []
    for y in YEARS:
        sy = sub[sub["年"] == y]
        out.append(f"{sy['持有到断板%'].mean():+.2f}/{len(sy)}" if len(sy) else "0笔")
    return out


def dim_table(lines, fin, dimcol, order, title):
    lines.append(f"\n## {title}\n")
    for g in GROUPS4:
        sub = fin[fin["四组"] == g]
        lines.append(f"**{g}**（合计 {fmt_cell(sub)}）\n")
        lines.append("| 档 | 笔数 | 胜率 | 持有到断板 | 2023 | 2024 | 2025 | 2026 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for v in order:
            s2 = sub[sub[dimcol] == v]
            if len(s2) == 0:
                row = [str(v), "0", "", ""]
            else:
                row = [str(v), str(len(s2)), f"{(s2['次日收%'] > 0).mean() * 100:.0f}%",
                       f"{s2['持有到断板%'].mean():+.2f}"]
            lines.append("| " + " | ".join(row + year_cells(s2)) + " |")
        lines.append("")


def cross_size_ma(lines, fin):
    lines.append("\n## 交叉：地基大小 × 相对10日线位置（格内=笔数 胜率 持有）\n")
    for g in GROUPS4:
        sub = fin[fin["四组"] == g]
        lines.append(f"**{g}**\n")
        lines.append("| 地基档 | 10日线上 | 10日线下 |")
        lines.append("|---|---|---|")
        for v in SIZE_BINS:
            s_up = sub[(sub["地基档"] == v) & (sub["MA10位置"] == "上")]
            s_dn = sub[(sub["地基档"] == v) & (sub["MA10位置"] == "下")]
            lines.append(f"| {v} | {fmt_cell(s_up)} | {fmt_cell(s_dn)} |")
        lines.append("")


def fanbao_detail(lines, fin):
    """反包结构内部: 前板高度 / 收复度 / 回撤。"""
    fb = fin[fin["反包结构"].isin(["断1天", "断2~3天", "断4~7天", "断8~15天"])].copy()
    lines.append(f"\n## 断板反包内部拆解（只含断1~15天, n={len(fb)}）\n")
    fb["前板高度档"] = fb["前板高度"].map(lambda h: "1板" if h == 1 else ("2板" if h == 2 else "3板+"))
    fb["收复档"] = pd.cut(fb["反包收复%"], [-99, 0, 3, 8, 99], labels=["没收复<0", "0~3", "3~8", "≥8"])
    fb["回撤档"] = pd.cut(fb["断板回撤%"], [-99, -15, -8, -3, 99], labels=["≤-15", "-15~-8", "-8~-3", ">-3"])
    for col, order, title in [("前板高度档", ["1板", "2板", "3板+"], "前一波板的高度"),
                              ("收复档", ["没收复<0", "0~3", "3~8", "≥8"], "反包收复%（首板收盘 vs 前板收盘）"),
                              ("回撤档", ["≤-15", "-15~-8", "-8~-3", ">-3"], "断板期间最深回撤%")]:
        lines.append(f"**{title}**\n")
        lines.append("| 档 | 组 | 笔数 | 胜率 | 持有到断板 | 2023 | 2024 | 2025 | 2026 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for v in order:
            for g in GROUPS4:
                s2 = fb[(fb[col].astype(str) == v) & (fb["四组"] == g)]
                if len(s2) == 0:
                    continue
                row = [v, g, str(len(s2)), f"{(s2['次日收%'] > 0).mean() * 100:.0f}%",
                       f"{s2['持有到断板%'].mean():+.2f}"]
                lines.append("| " + " | ".join(row + year_cells(s2)) + " |")
        lines.append("")


def scheme_cross(lines, fin):
    lines.append("\n## 方案点 × 新维度（每个方案点内部按新维度拆）\n")
    for t in ["A1", "A2", "B1", "B2"]:
        sub = fin[fin["方案点"] == t]
        lines.append(f"### {t}（{fmt_cell(sub)}）\n")
        for col, order in [("地基档", SIZE_BINS), ("MA10位置", ["上", "下"]),
                           ("反包结构", FANBAO_BINS)]:
            rows = []
            for v in order:
                s2 = sub[sub[col] == v]
                if len(s2):
                    rows.append(f"{v}: {fmt_cell(s2)}")
            lines.append(f"- {col}：" + ("；".join(rows) if rows else "无"))
        lines.append("")


def candidate_scan(lines, fin):
    """两条件组合扫描: 新维度条件 × 分年全正 + n>=12。"""
    lines.append("\n## 候选组合扫描（分年全正 + 总笔数≥12, 只列通过的）\n")

    def ev(sub):
        n = len(sub)
        if n < 12:
            return None
        ys = [sub[sub["年"] == y]["持有到断板%"].mean() for y in YEARS]
        ns = [len(sub[sub["年"] == y]) for y in YEARS]
        if any(x != x for x in ys) or min(ys) <= 0 or min(ns) < 1:
            return None
        return (n, (sub["次日收%"] > 0).mean() * 100, sub["持有到断板%"].mean(), ys, ns)

    conds = []
    for t in (1, 2, 3, 4, 5):
        conds.append((f"地基大阳≥{t}%", lambda d, t=t: d["地基涨跌%"] >= t))
        conds.append((f"地基大阴≤-{t}%", lambda d, t=t: d["地基涨跌%"] <= -t))
        conds.append((f"地基小|·|<{t}%", lambda d, t=t: d["地基涨跌%"].abs() < t))
    for b in (-10, -5, 0, 5, 10):
        conds.append((f"MA10上距>{b}%", lambda d, b=b: d["距MA10%"] > b))
        conds.append((f"MA10下距<{b}%", lambda d, b=b: d["距MA10%"] < b))
    conds.append(("站上均线≥3条", lambda d: d["站上均线数"] >= 3))
    conds.append(("站上均线≤1条", lambda d: d["站上均线数"] <= 1))
    conds.append(("MA10斜率向上", lambda d: d["MA10斜率%"] > 0))
    conds.append(("MA10斜率向下", lambda d: d["MA10斜率%"] < 0))
    conds.append(("MA20斜率向上", lambda d: d["MA20斜率%"] > 0))
    conds.append(("MA20斜率向下", lambda d: d["MA20斜率%"] < 0))
    conds.append(("断板反包(断1~15天)", lambda d: d["反包结构"].isin(["断1天", "断2~3天", "断4~7天", "断8~15天"])))
    conds.append(("60日内无板", lambda d: d["反包结构"] == "60日内无板"))
    conds.append(("断1~3天", lambda d: d["反包结构"].isin(["断1天", "断2~3天"])))
    conds.append(("断4~15天", lambda d: d["反包结构"].isin(["断4~7天", "断8~15天"])))
    conds.append(("反包收复>0", lambda d: d["反包收复%"] > 0))
    conds.append(("前板高度≥2", lambda d: d["前板高度"].fillna(0) >= 2))

    hits = []
    for g in GROUPS4:
        sub0 = fin[fin["四组"] == g]
        for i1, (n1, f1) in enumerate(conds):
            for n2, f2 in conds[i1:]:
                try:
                    m = f1(sub0) & f2(sub0)
                    m = m.fillna(False) if hasattr(m, "fillna") else m
                    r = ev(sub0[m])
                except Exception:
                    continue
                if r:
                    hits.append((g, f"{n1} × {n2}", r))
    hits.sort(key=lambda x: -x[2][2])
    lines.append("| 组 | 组合 | 笔数 | 胜率 | 持有 | 2023 | 2024 | 2025 | 2026 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for g, name, (n, win, hold, ys, ns) in hits[:40]:
        ycells = [f"{y:+.2f}/{nn}" for y, nn in zip(ys, ns)]
        lines.append(f"| {g} | {name} | {n} | {win:.0f}% | {hold:+.2f} | "
                     + " | ".join(ycells) + " |")
    if not hits:
        lines.append("| （无通过组合） | | | | | | | | |")
    lines.append("")


def ticket_block(bars, r, N):
    """一票的逐日过程(日线, 无前板的开口数据)。"""
    code, day = r["代码"], r["买入日"]
    sub = bars[bars["vt_symbol"] == code]
    sub = sub[sub["trade_date"] <= pd.Timestamp(day) + pd.Timedelta(days=30)]
    if not len(sub):
        return ""
    sub = sub.reset_index(drop=True)
    hit = sub.index[sub["trade_date"] == pd.Timestamp(day)]
    if not len(hit):
        return ""
    p = int(hit[0])
    lo = max(0, p - N - 3)
    hd = r.get("持有天数")
    hi = min(len(sub) - 1, p + max(3, int(hd) if hd == hd else 3))
    ls = ["日期         开盘    最高    最低    收盘   涨跌%  换手%  标记"]
    prev = None
    for i in range(lo, hi + 1):
        b = sub.loc[i]
        chg = (b["close_price"] / prev - 1) * 100 if prev else np.nan
        mark = ""
        if i == p - N - 1:
            mark = "←地基日"
        elif p - N <= i < p:
            mark = f"←第{i - (p - N) + 1}板"
        elif i == p:
            mark = "←买入日(打板)"
        elif i == p + 1:
            mark = "←次日"
        prev = b["close_price"]
        ls.append(f"{b['trade_date'].strftime('%Y-%m-%d')}  {b['open_price']:7.2f} {b['high_price']:7.2f} "
                  f"{b['low_price']:7.2f} {b['close_price']:7.2f} {chg:+6.2f} "
                  f"{b['turnover_rate']:6.1f}  {mark}")
    fb = (f"，断板{int(r['断板天数'])}天/前板{int(r['前板高度'])}板/收复{r['反包收复%']:+.1f}%"
          if r.get("断板天数") == r.get("断板天数") and r.get("断板天数") is not None else "")
    head = (f"**{r['名称']} {day}（{'好票' if r['次日收%'] > 0 else '坏票'}，{r['四组']}，"
            f"地基{r['阴阳']}{r['地基涨跌%']:+.1f}%/{r['地基档']}，距MA10 {r['距MA10%']:+.1f}%{fb}，"
            f"次日{r['次日收%']:+.1f}%，持有{r['持有到断板%']:+.1f}%）**")
    return head + "\n\n```\n" + "\n".join(ls) + "\n```\n"


def contrast_tickets(lines, fin, bars):
    """关键对比的代表票: 大阴vs大阳 / MA10上vs下 / 反包vs无板。"""
    lines.append("\n## 代表票逐日过程（关键对比各取好坏1笔）\n")
    pairs = [
        ("地基大阴(≤-3%)", fin[fin["地基涨跌%"] <= -3]),
        ("地基大阳(≥3%)", fin[fin["地基涨跌%"] >= 3]),
        ("10日线上方", fin[fin["MA10位置"] == "上"]),
        ("10日线下方", fin[fin["MA10位置"] == "下"]),
        ("断板反包(断1~15天)", fin[fin["反包结构"].isin(["断1天", "断2~3天", "断4~7天", "断8~15天"])]),
        ("60日内无板", fin[fin["反包结构"] == "60日内无板"]),
    ]
    for title, pool in pairs:
        good = pool[pool["次日收%"] > 0].sort_values("持有到断板%", ascending=False)
        bad = pool[pool["次日收%"] <= 0].sort_values("持有到断板%")
        lines.append(f"\n### {title}\n")
        for pick in ([good.iloc[3]] if len(good) > 3 else []) + ([bad.iloc[3]] if len(bad) > 3 else []):
            lines.append(ticket_block(bars, pick, int(pick["N"])))


def main():
    eng = create_engine(os.environ["DATABASE_URL"])
    E, bars, end = rr.build_events(eng)
    E["年"] = E["年"].astype(str)
    E2 = augment(E, bars)
    E2 = tag_scheme(E2)
    fin = E2[~E2["未完"]].copy()

    # 导出扩展明细
    keep = ["代码", "名称", "买入日", "四组", "方案点", "阴阳", "地基涨跌%", "地基档",
            "距MA5%", "距MA10%", "距MA20%", "距MA30%", "站上均线数", "MA10位置",
            "MA10斜率%", "MA20斜率%", "反包结构", "断板天数", "前板高度", "反包收复%",
            "断板回撤%", "前板日", "链", "买入开盘%", "次日收%", "持有到断板%", "月", "年"]
    E2[keep].to_csv(f"{OUT}/地基均线反包明细.csv", index=False, encoding="utf-8-sig")

    lines = [f"# 高位接力 · 地基细分 + 均线位置 + 断板反包（2026-09-19 第十九遍）", "",
             f"样本 = 全量事件 {len(fin)} 笔（2023-01 ~ {end}，剔除数据末端未完）。", "",
             "三个新维度全部是买入前可知的静态信息：", "",
             "1. **地基大小**：首板前一天K线涨跌幅度分档（阴阳之外再看大小）；",
             "2. **均线位置**：地基日收盘 vs 5/10/20/30日线的距离、站上几条、均线斜率；",
             "3. **断板反包**：首板前60个交易日内最近一个涨停板 → 断板天数 / 前板高度 / "
             "反包收复%（首板收盘 vs 前板收盘）/ 断板期间最深回撤%。"
             "「一板后断板再反包重新起板」= 断1~15天的家族。", "",
             "口径同前：胜率=次日收盘不亏比例；持有=涨停价买入持有到断板收盘卖出；"
             "分年列为「持有均值/笔数」，0笔也写明不藏。", ""]

    dim_table(lines, fin, "地基档", SIZE_BINS, "维度1：地基大小档（涨跌%）")
    dim_table(lines, fin, "MA10位置", ["上", "下"], "维度2a：地基收盘在10日线上/下")
    dim_table(lines, fin, "距MA10档", MA10_BINS, "维度2b：地基收盘距10日线幅度档")
    dim_table(lines, fin, "站上均线数", [0, 1, 2, 3, 4], "维度2c：地基日站上几条均线（5/10/20/30）")
    # 斜率表(自定义, 因为维度值是连续→二值)
    lines.append("\n## 维度2d：均线斜率（地基日 MA 值 vs 5个交易日前的 MA 值）\n")
    for w in (10, 20):
        for g in GROUPS4:
            sub = fin[fin["四组"] == g]
            up = sub[sub[f"MA{w}斜率%"] > 0]
            dn = sub[sub[f"MA{w}斜率%"] <= 0]
            lines.append(f"- MA{w} {g}：向上 {fmt_cell(up)}；向下/平 {fmt_cell(dn)}")
        lines.append("")

    dim_table(lines, fin, "反包结构", FANBAO_BINS, "维度3：断板反包结构（首板前最近的板距今）")
    fanbao_detail(lines, fin)
    cross_size_ma(lines, fin)
    scheme_cross(lines, fin)
    candidate_scan(lines, fin)
    contrast_tickets(lines, fin, bars)

    text = "\n".join(lines)
    os.makedirs(f"{OUT}/汇总", exist_ok=True)
    with open(f"{OUT}/汇总/地基均线反包.md", "w", encoding="utf-8") as fp:
        fp.write(text)
    print(f"\n已写 {OUT}/汇总/地基均线反包.md （{len(text.splitlines())}行）")

    # 控制台速览
    print("\n===== 速览：地基大小 × 四组 =====")
    for g in GROUPS4:
        sub = fin[fin["四组"] == g]
        print(f"\n{g} (n={len(sub)})")
        for v in SIZE_BINS:
            s2 = sub[sub["地基档"] == v]
            if len(s2):
                ys = " ".join(f"{y}:{s2[s2['年'] == y]['持有到断板%'].mean():+.2f}/{len(s2[s2['年'] == y])}"
                              if len(s2[s2['年'] == y]) else f"{y}:0笔" for y in YEARS)
                print(f"  {v:10s} {fmt_cell(s2):22s} {ys}")
    print("\n===== 速览：MA10位置 × 四组 =====")
    for g in GROUPS4:
        sub = fin[fin["四组"] == g]
        for v in ["上", "下"]:
            s2 = sub[sub["MA10位置"] == v]
            print(f"  {g} MA10{v}: {fmt_cell(s2)}")
    print("\n===== 速览：反包结构 × 四组 =====")
    for g in GROUPS4:
        sub = fin[fin["四组"] == g]
        print(f"\n{g}")
        for v in FANBAO_BINS:
            s2 = sub[sub["反包结构"] == v]
            if len(s2):
                ys = " ".join(f"{y}:{s2[s2['年'] == y]['持有到断板%'].mean():+.2f}/{len(s2[s2['年'] == y])}"
                              if len(s2[s2['年'] == y]) else f"{y}:0笔" for y in YEARS)
                print(f"  {v:10s} {fmt_cell(s2):22s} {ys}")


if __name__ == "__main__":
    main()
