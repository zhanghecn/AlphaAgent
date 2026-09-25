# -*- coding: utf-8 -*-
"""反包(断板1~3天后再涨停)研究 —— 六组=高度段(2/4/5+)×跌幅阴阳, 带方案点。

口径 = 量化因子研究/反包/反包需求.md (2026-09-25 终版):
- 事件: 前波恰好N连板 → 断板g天(每日收盘不涨停) → 反包日盘中触及涨停价 → 涨停价买入;
  一字板(全天没打开)买不进, 排除; g=昨日连续不涨停天数(唯一确定), 末板日=反包日往前g+1个交易日
- 六组 = 高度段(2板 / 4板 / 5+板无上限; 3板删除四年皆弱) × 跌幅阴阳(阴=末日收盘低于前日收盘)
- 方案点: S1一根急杀(2板, 断板累计跌8~15%且恰1阴) / S2四板阴断1 / S3五板+阳断1
  / O1五板+阴断1 / O2四板阴断3 (见需求文档第七节)
- 参考行: g=4~5天 / 3板(只进统计, 不进好差票验证目录)
- 坏票: 买入后第二天收盘低于买价(炸板但第二天涨回来的算好票)
- 收益: 涨停价买入, 持有到首次不再涨停日收盘卖出, 15日兜底(反包日炸板=当天收盘卖)
- 范围: 主板非ST非退(按当前名称); 涨停=不复权昨收×1.10四舍五入到分(+1e-9防x.xx5舍反); 上市前5日不参与
- 数据末端还没走到卖出日的标「未完」, 不进收益统计

用法(容器内):
    python /tmp/research/fanbao_research.py
输出(容器内 /tmp/research/fanbao_out, 跑完 docker cp 回宿主 量化因子研究/反包/):
    全量明细.csv / 汇总/基础矩阵.md / 汇总/按月汇总.csv / 汇总/月度环境.csv
    好差票验证/<六组>/YYYY-MM.md + _索引_<组>.csv
"""
import os
import sys

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

OUT = "/tmp/research/fanbao_out"
START_BARS = "2022-06-01"          # 给2023-01的事件留足地基/均线/前波回看窗口
START_EVT = pd.Timestamp("2023-01-01")
LSHADOW_TH = 0.3                   # 板型分类: 下影线>=0.3%算「带下影线」
GS_MAIN = [1, 2, 3]                # 次分组: 断板天数
SEGS = ["2板", "4板", "5+板"]       # 高度段: 2/4/5+(无上限); 3板删除
HOLD_MAX = 15                      # 持有兜底交易日数


def seg_of(N):
    """高度段: 2板/4板/5+板; 3板删除返回None(进参考行)。"""
    if N == 2:
        return "2板"
    if N == 4:
        return "4板"
    if N >= 5:
        return "5+板"
    return None


def scheme_tags(r):
    """方案点标记(需求文档第七节)。r需含 N/阴阳/断板累计%/断板阴线数/断板天数。"""
    tags = []
    if r["N"] == 2 and r["断板天数"] in (1, 2, 3) and -15 < r["断板累计%"] <= -8 and r["断板阴线数"] == 1:
        tags.append("S1一根急杀")
    if r["N"] == 4 and r["阴阳"] == "阴" and r["断板天数"] == 1:
        tags.append("S2四板阴断1")
    if r["N"] >= 5 and r["阴阳"] == "阳" and r["断板天数"] == 1:
        tags.append("S3五板+阳断1")
    if r["N"] >= 5 and r["阴阳"] == "阴" and r["断板天数"] == 1:
        tags.append("O1五板+阴断1")
    if r["N"] == 4 and r["阴阳"] == "阴" and r["断板天数"] == 3:
        tags.append("O2四板阴断3")
    return "·".join(tags)

pd.set_option("display.width", 320)
pd.set_option("display.max_columns", 100)


def board_type(one_word, lshadow):
    if one_word:
        return "一字"
    return "下影" if lshadow >= LSHADOW_TH else "实体"


def build_bars(eng):
    """日线基础设施: 连板段streak/段尾run_end/触板touch/一字/均线/环境/前瞻列。"""
    end = pd.read_sql("select max(trade_date)::text from stock_daily_bars", eng).iloc[0, 0]
    stocks = pd.read_sql("select vt_symbol, name from stocks", eng)
    stocks["code6"] = stocks["vt_symbol"].str[:6]

    def board_of(c):
        if c.startswith(("300", "301")):
            return "cyb"
        if c.startswith(("688", "689")):
            return "kcb"
        if c.startswith(("8", "4", "92")):
            return "bse"
        return "main"

    stocks["board"] = stocks["code6"].map(board_of)
    stocks["bad"] = stocks["name"].str.upper().str.contains("ST") | stocks["name"].str.contains("退")

    bars = pd.read_sql(
        "select vt_symbol, trade_date, open_price, high_price, low_price, close_price, volume, turnover_rate "
        f"from stock_daily_bars where trade_date >= '{START_BARS}' and trade_date <= '{end}'",
        eng, parse_dates=["trade_date"])
    bars = bars.merge(stocks[["vt_symbol", "name", "board", "bad"]], on="vt_symbol", how="left")
    bars = bars[(bars["board"] == "main") & (~bars["bad"])].copy()
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True, ignore_index=True)
    bars["sid"], _ = pd.factorize(bars["vt_symbol"])
    g = bars.groupby("sid", sort=False)
    bars["prev_close"] = g["close_price"].shift(1)
    bars["pos"] = g.cumcount().astype("int32")
    bars["limit_price"] = np.round(bars["prev_close"] * 1.10 + 1e-9, 2)
    elig = bars["prev_close"].notna() & (bars["prev_close"] > 0) & (bars["pos"] >= 5)
    bars["is_lim"] = elig & ((bars["close_price"] - bars["limit_price"]).abs() <= 1e-6)
    ow = ((bars["open_price"] - bars["close_price"]).abs() <= 1e-6) & \
         ((bars["open_price"] - bars["high_price"]).abs() <= 1e-6) & \
         ((bars["open_price"] - bars["low_price"]).abs() <= 1e-6)
    bars["one_word"] = bars["is_lim"] & ow
    is_lim_i = bars["is_lim"].astype("int8")
    brk = (~bars["is_lim"]).groupby(bars["sid"], sort=False).cumsum()
    bars["streak"] = is_lim_i.groupby([bars["sid"], brk], sort=False).cumsum()
    bars["touch"] = elig & (bars["high_price"] >= bars["limit_price"] - 1e-6)
    # 连续不涨停天数(截至当日收盘): 昨日值=断板间隔g
    lim_cs = bars["is_lim"].groupby(bars["sid"], sort=False).cumsum()
    bars["notlim_run"] = (~bars["is_lim"]).astype("int8").groupby(
        [bars["sid"], lim_cs], sort=False).cumsum()
    bars["notlim_prev"] = g["notlim_run"].shift(1)
    bars["chg"] = bars["close_price"] / bars["prev_close"] - 1
    lo = pd.concat([bars["open_price"], bars["close_price"]], axis=1).min(axis=1)
    bars["lshadow"] = (lo - bars["low_price"]) / bars["prev_close"] * 100
    gv = g["volume"]
    bars["vol_rel5"] = bars["volume"] / gv.transform(lambda s: s.rolling(5, min_periods=3).mean())
    gc = g["close_price"]
    for w in (5, 10, 20, 30):
        bars[f"ma{w}"] = gc.transform(lambda s, w=w: s.rolling(w, min_periods=w).mean())
    bars["h60"] = g["high_price"].transform(lambda s: s.rolling(60, min_periods=20).max())
    bars["run_end"] = bars["is_lim"] & (~g["is_lim"].shift(-1).fillna(False).astype(bool))
    for k in range(1, HOLD_MAX + 1):
        bars[f"n{k}_close"] = g["close_price"].shift(-k)
        bars[f"n{k}_open"] = g["open_price"].shift(-k)
        bars[f"n{k}_is_lim"] = g["is_lim"].shift(-k)
    # 市场环境: 每天全市场涨停家数
    mkt = bars.groupby("trade_date", sort=False)["is_lim"].sum()
    bars["mkt_lim"] = bars["trade_date"].map(mkt)
    bars["mkt_prev"] = bars["trade_date"].map(mkt.shift(1))
    return bars, end


def build_events(bars):
    """反包事件: 反包日=touch且非一字; g=notlim_prev; 末板日=e=p-1-g; N=streak[e]。"""
    dates = bars["trade_date"].to_numpy()
    sid_arr = bars["sid"].to_numpy()
    cols = {c: bars[c].to_numpy() for c in
            ["vt_symbol", "name", "close_price", "open_price", "high_price", "low_price",
             "prev_close", "limit_price", "is_lim", "one_word", "streak", "notlim_prev",
             "touch", "chg", "lshadow", "turnover_rate", "vol_rel5",
             "ma5", "ma10", "ma20", "ma30", "h60", "mkt_lim", "mkt_prev"]}
    # 前波查询: 每只票连板段(高度>=2)段尾pos与高度
    runs = bars[bars["run_end"] & (bars["streak"] >= 2)][["sid", "pos", "streak"]]
    run_by = {s: (a["pos"].to_numpy(), a["streak"].to_numpy())
              for s, a in runs.groupby("sid", sort=False)}

    cand = bars[(bars["touch"]) & (~bars["one_word"]) &
                (bars["trade_date"] >= START_EVT) &
                (bars["notlim_prev"].notna())]
    print(f"触板非一字候选日 {len(cand)} 个, 逐个判反包结构…")

    rows = []
    for p in cand.index.to_numpy():
        p = int(p)
        gp = cols["notlim_prev"][p]
        if gp != gp or gp < 1:
            continue                     # 昨日涨停 = 不是断板反包结构
        ggap = int(gp)
        e = p - 1 - ggap                 # 末板日
        if e < 0 or sid_arr[e] != sid_arr[p]:
            continue
        if not cols["is_lim"][e]:
            continue                     # 防御: notlim_prev口径下应为涨停日
        N = int(cols["streak"][e])
        if N < 2:
            continue                     # 前波1板不研究
        f = e - N                        # 前波首板前一天(地基日)
        if f < 0 or sid_arr[f] != sid_arr[p]:
            continue                     # 地基缺失, 跳过
        rec = {}
        rec["代码"] = cols["vt_symbol"][p]
        rec["名称"] = cols["name"][p]
        rec["反包日"] = pd.Timestamp(dates[p]).strftime("%Y-%m-%d")
        rec["N"] = N
        rec["断板天数"] = ggap
        # 跌幅口径阴阳(2026-09-25主人拍板): 阴=末日收盘低于前日收盘, 阳=涨或平
        yy = "阳" if cols["close_price"][p - 1] >= cols["prev_close"][p - 1] else "阴"
        rec["阴阳"] = yy
        seg = seg_of(N)
        rec["主格"] = bool(seg) and (ggap in GS_MAIN)
        rec["组"] = f"{seg}反包{yy}" if rec["主格"] else f"{seg or f'{N}板'}反包"
        rec["末板日"] = pd.Timestamp(dates[e]).strftime("%Y-%m-%d")
        rec["首板日"] = pd.Timestamp(dates[e - N + 1]).strftime("%Y-%m-%d")
        # ---- 断板期行为(本研究核心新增) ----
        seg, yin, zb_days = [], 0, 0
        low_c = np.inf
        for k in range(ggap):
            j = p - ggap + k
            o, c = cols["open_price"][j], cols["close_price"][j]
            tag = "阳" if c >= o else "阴"
            seg.append(f"{tag}{cols['chg'][j] * 100:+.1f}")
            yin += tag == "阴"
            if cols["touch"][j] and not cols["is_lim"][j]:
                zb_days += 1             # 断板期炸板日(触板收盘未封)
            low_c = min(low_c, c)
        end_c = cols["close_price"][p - 1]
        last_c = cols["close_price"][e]
        rec["断板期"] = "→".join(seg)
        rec["断板阴线数"] = yin
        rec["断板炸板日数"] = zb_days
        rec["断板累计%"] = round((end_c / last_c - 1) * 100, 1)
        rec["坑深%"] = round((low_c / last_c - 1) * 100, 1)
        # 断板末日(反包前一天)阴阳(=分组口径, 前面已算yy)
        rec["末日阴阳"] = yy
        # ---- 前波板型链 ----
        chain = []
        for k in range(N):
            j = e - N + 1 + k
            bt = board_type(bool(cols["one_word"][j]), cols["lshadow"][j])
            og = (cols["open_price"][j] / cols["prev_close"][j] - 1) * 100
            chain.append(f"{bt}{og:+.0f}")
        rec["链"] = "→".join(chain)
        # ---- 地基(前波首板前一天) ----
        fo, fc = cols["open_price"][f], cols["close_price"][f]
        rec["地基"] = ("阳" if fc >= fo else "阴") + f"{cols['chg'][f] * 100:+.1f}"
        # ---- 位置/均线(反包前一天口径, D-1) ----
        d1c = end_c
        rec["位置%"] = round((d1c / cols["h60"][p - 1] - 1) * 100, 1) if cols["h60"][p - 1] == cols["h60"][p - 1] else np.nan
        ma = [cols[m][p - 1] for m in ("ma5", "ma10", "ma20", "ma30")]
        rec["均线"] = "".join("+" if a >= b else "-" for a, b in zip(ma, ma[1:])) if all(x == x for x in ma) else ""
        rec["MA10%"] = round((d1c / cols["ma10"][p - 1] - 1) * 100, 1) if cols["ma10"][p - 1] == cols["ma10"][p - 1] else np.nan
        rec["距MA5%"] = round((d1c / cols["ma5"][p - 1] - 1) * 100, 1) if cols["ma5"][p - 1] == cols["ma5"][p - 1] else np.nan
        # ---- 前波历史(本波首板之前的更早连板段) ----
        ends, hts = run_by.get(sid_arr[p], (np.array([]), np.array([])))
        first_pos = e - N + 1
        before = ends < first_pos
        rec["距前波"] = int(first_pos - ends[before].max()) if before.any() else None
        for win in (60, 120):
            inwin = before & (ends >= first_pos - win)
            rec[f"前波{win}日最高板"] = int(hts[inwin].max()) if inwin.any() else 0
        # ---- 反包日(买入日) ----
        buy = cols["limit_price"][p]
        rec["买价"] = round(buy, 2)
        rec["反包开盘%"] = round((cols["open_price"][p] / cols["prev_close"][p] - 1) * 100, 1)
        rec["开盘距涨停%"] = round((buy / cols["open_price"][p] - 1) * 100, 1)
        rec["昨日涨停家数"] = int(cols["mkt_prev"][p]) if cols["mkt_prev"][p] == cols["mkt_prev"][p] else None
        # ---- 结果 ----
        rec["封住"] = bool(cols["is_lim"][p])
        n1c = bars[f"n1_close"].iat[p]
        n1o = bars[f"n1_open"].iat[p]
        rec["次日开%"] = round((n1o / buy - 1) * 100, 2) if n1o == n1o else np.nan
        rec["次日收%"] = round((n1c / buy - 1) * 100, 2) if n1c == n1c else np.nan
        rec["次日连板"] = bool(bars["n1_is_lim"].iat[p]) if n1c == n1c else False
        # 持有到断板: 反包日封住→次日起首个不再涨停日收盘卖; 当天炸板→当天收盘卖; 15日兜底
        if not rec["封住"]:
            exit_px, hold_days = cols["close_price"][p], 0
        else:
            exit_px, hold_days = np.nan, None
            for k in range(1, HOLD_MAX + 1):
                v = bars[f"n{k}_is_lim"].iat[p]
                c = bars[f"n{k}_close"].iat[p]
                if c != c:
                    break
                if not bool(v):
                    exit_px, hold_days = c, k
                    break
            if exit_px != exit_px and bars[f"n{HOLD_MAX}_close"].iat[p] == bars[f"n{HOLD_MAX}_close"].iat[p]:
                exit_px, hold_days = bars[f"n{HOLD_MAX}_close"].iat[p], HOLD_MAX
        rec["持有到断板%"] = round((exit_px / buy - 1) * 100, 2) if exit_px == exit_px else np.nan
        rec["持有天数"] = hold_days
        rec["未完"] = exit_px != exit_px
        # 反包后再连板数(封住后的新连板段高度, 炸板=0)
        h = 0
        if rec["封住"]:
            h = 1
            for k in range(1, HOLD_MAX + 1):
                if bool(bars[f"n{k}_is_lim"].iat[p]):
                    h = 1 + k
                else:
                    break
        rec["反包后高度"] = h
        if rec["未完"]:
            rec["结果"] = "未完"
        elif not rec["封住"]:
            rec["结果"] = "炸板"
        elif rec["次日连板"]:
            rec["结果"] = "连板"
        elif rec["次日收%"] < 0:
            rec["结果"] = "封次日负"
        else:
            rec["结果"] = "封次日正"
        rec["坏票"] = bool(rec["次日收%"] < 0) if rec["次日收%"] == rec["次日收%"] else None
        rec["方案点"] = scheme_tags(rec)
        rec["月"] = rec["反包日"][:7]
        rec["年"] = rec["反包日"][:4]
        rows.append(rec)

    E = pd.DataFrame(rows)
    E["坏票"] = E["坏票"].astype("boolean")
    print(f"反包事件 {len(E)} 笔(含参考行 g=4~5 / N>=6), 主格 {int(E['主格'].sum())} 笔")
    return E


def agg_cell(sub):
    """一格统计: n/炸板率/胜率/次日收/持有到断板/连板率。"""
    if len(sub) == 0:
        return None
    return dict(
        n=len(sub),
        炸板率=(~sub["封住"]).mean() * 100,
        胜率=(sub["次日收%"] > 0).mean() * 100,
        次日收=sub["次日收%"].mean(),
        持有到断板=sub["持有到断板%"].mean(),
        连板率=sub["次日连板"].mean() * 100,
    )


def year_line(sub):
    ys = sorted(sub["年"].unique())
    return " ".join(
        f"{y}:{sub[sub['年'] == y]['持有到断板%'].mean():+.2f}/{len(sub[sub['年'] == y])}"
        if len(sub[sub["年"] == y]) else f"{y}:0笔" for y in ys)


def stat_tables(E, end):
    fin = E[(~E["未完"]) & (E["次日收%"] == E["次日收%"])]
    L = [f"# 反包 · 基础矩阵（六组 = 高度段2/4/5+ × 跌幅阴阳 × 断1~3天）", "",
         f"数据范围 2023-01 ~ {end} | 主板非ST非退 | 反包日盘中触板按涨停价买（一字剔除） | 收益=持有到断板(15日兜底)",
         "阴阳 = **跌幅口径**（阴=反包前一天收盘低于前日收盘）；3板已删除（四年皆弱）；5+板不设上限。", ""]

    # 一、18格总表
    L += ["## 一、18格总表（六组×断1/2/3天，每格全指标）", "",
          "| 组 | 断 | 笔数 | 胜率% | 炸板% | 次日收% | 持有到断板% | 再连板率% | 后续0/1/2/3+板% |",
          "|---|---|---|---|---|---|---|---|---|"]
    for seg in SEGS:
        for yy in ("阴", "阳"):
            for gg in GS_MAIN:
                if seg == "5+板":
                    s = fin[(fin["N"] >= 5) & (fin["阴阳"] == yy) & (fin["断板天数"] == gg)]
                else:
                    s = fin[(fin["N"] == int(seg[0])) & (fin["阴阳"] == yy) & (fin["断板天数"] == gg)]
                if len(s) == 0:
                    L.append(f"| {seg}反包{yy} | {gg} | 0 | - | - | - | - | - | - |")
                    continue
                h = s["反包后高度"]
                dist = "/".join(f"{(h == k).mean() * 100:.0f}" for k in (0, 1, 2)) + f"/{(h >= 3).mean() * 100:.0f}"
                L.append(f"| {seg}反包{yy} | {gg} | {len(s)} "
                         f"| {(s['次日收%'] > 0).mean() * 100:.0f} "
                         f"| {(~s['封住']).mean() * 100:.0f} "
                         f"| {s['次日收%'].mean():+.2f} "
                         f"| {s['持有到断板%'].mean():+.2f} "
                         f"| {(h >= 2).mean() * 100:.0f} | {dist} |")
    L.append("")

    # 二、方案点统计
    L += ["## 二、方案点统计（出手规则，条件见需求文档第七节）", "",
          "| 方案点 | n | 持有到断板 | 胜率 | 炸板 | 再连板 | 分年 | 级别 |",
          "|---|---|---|---|---|---|---|---|"]
    meta = [("S1一根急杀", "出手"), ("S2四板阴断1", "出手"), ("S3五板+阳断1", "出手"),
            ("O1五板+阴断1", "观察"), ("O2四板阴断3", "观察")]
    for tag, lv in meta:
        s = fin[fin["方案点"].str.contains(tag, na=False, regex=False)]
        if len(s) == 0:
            L.append(f"| {tag} | 0 | - | - | - | - | - | {lv} |")
            continue
        h = s["反包后高度"]
        L.append(f"| **{tag}** | {len(s)} | {s['持有到断板%'].mean():+.2f} "
                 f"| {(s['次日收%'] > 0).mean() * 100:.0f}% "
                 f"| {(~s['封住']).mean() * 100:.0f}% "
                 f"| {(h >= 2).mean() * 100:.0f}% | {year_line(s)} | {lv} |")
    L.append("")

    # 三、参考行
    L += ["## 三、参考行（只统计不进好差票目录）", "",
          "| 分组 | n | 持有到断板 | 胜率 | 炸板率 | 说明 |", "|---|---|---|---|---|---|"]
    for gg in GS_MAIN:
        sub = fin[(fin["N"] == 3) & (fin["断板天数"] == gg)]
        d = agg_cell(sub)
        if d:
            L.append(f"| 3板×断{gg}天 | {d['n']} | {d['持有到断板']:+.2f} | {d['胜率']:.0f}% | {d['炸板率']:.0f}% | 3板删除留档 |")
    for N in (2, 4, 5):
        base = fin[fin["N"] == N] if N < 5 else fin[fin["N"] >= 5]
        for gg in (4, 5):
            sub = base[base["断板天数"] == gg]
            d = agg_cell(sub)
            if d:
                lab = f"{N}板" if N < 5 else "5+板"
                L.append(f"| {lab}×断{gg}天 | {d['n']} | {d['持有到断板']:+.2f} | {d['胜率']:.0f}% | {d['炸板率']:.0f}% | 间隔单调性参考 |")
    L.append("")

    # 四、18格分年
    L += ["## 四、18格分年（持有到断板%/n）", ""]
    for seg in SEGS:
        for yy in ("阴", "阳"):
            for gg in GS_MAIN:
                if seg == "5+板":
                    sub = fin[(fin["N"] >= 5) & (fin["阴阳"] == yy) & (fin["断板天数"] == gg)]
                else:
                    sub = fin[(fin["N"] == int(seg[0])) & (fin["阴阳"] == yy) & (fin["断板天数"] == gg)]
                if len(sub):
                    L.append(f"- **{seg}反包{yy}×断{gg}天** (n={len(sub)}): {year_line(sub)}")
    L.append("")

    # 五、六、切分表(主格池)
    pool = fin[fin["主格"]]
    L += ["## 五、断板期阴线数切分（主格池，段合并）", "",
          "| 高度段 | 0阴(全阳) | 1阴 | 2+阴 |", "|---|---|---|---|"]
    for seg in SEGS:
        base = pool[pool["N"] == int(seg[0])] if seg != "5+板" else pool[pool["N"] >= 5]
        cells = []
        for m in (0, 1, 2):
            sub = base[base["断板阴线数"] == m] if m < 2 else base[base["断板阴线数"] >= 2]
            d = agg_cell(sub)
            cells.append(f"{d['n']}笔 持{d['持有到断板']:+.2f} 胜{d['胜率']:.0f}%" if d else "0笔")
        L.append(f"| {seg} | " + " | ".join(cells) + " |")
    L.append("")
    L += ["## 六、坑深切分（主格池，断板期最低收盘距末板收盘）", "",
          "| 高度段 | 浅坑>-3% | 中坑-3~-8% | 深坑<-8% |", "|---|---|---|---|"]
    for seg in SEGS:
        base = pool[pool["N"] == int(seg[0])] if seg != "5+板" else pool[pool["N"] >= 5]
        cells = []
        for lo_, hi_ in [(-3, 99), (-8, -3), (-99, -8)]:
            sub = base[(base["坑深%"] > lo_) & (base["坑深%"] <= hi_)]
            d = agg_cell(sub)
            cells.append(f"{d['n']}笔 持{d['持有到断板']:+.2f} 胜{d['胜率']:.0f}%" if d else "0笔")
        L.append(f"| {seg} | " + " | ".join(cells) + " |")
    return "\n".join(L) + "\n"
def export_files(E, bars, end, matrix_text):
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(f"{OUT}/汇总", exist_ok=True)
    os.makedirs(f"{OUT}/好差票验证", exist_ok=True)
    E.to_csv(f"{OUT}/全量明细.csv", index=False, encoding="utf-8-sig")
    with open(f"{OUT}/汇总/基础矩阵.md", "w", encoding="utf-8") as fp:
        fp.write(matrix_text)

    fin = E[~E["未完"]]
    mo = fin.groupby(["组", "月"]).agg(
        笔数=("持有到断板%", "size"),
        坏票率=("坏票", lambda s: f"{s.mean() * 100:.0f}%"),
        封住率=("封住", lambda s: f"{s.mean() * 100:.0f}%"),
        次日收=("次日收%", lambda s: round(s.mean(), 2)),
        持有到断板=("持有到断板%", lambda s: round(s.mean(), 2)),
    ).reset_index()
    mo.to_csv(f"{OUT}/汇总/按月汇总.csv", index=False, encoding="utf-8-sig")

    # 月度环境(同高位接力)
    bm = bars[bars["trade_date"] >= START_EVT].copy()
    bm["月"] = bm["trade_date"].dt.strftime("%Y-%m")
    daily_lim = bm.groupby("trade_date")["is_lim"].sum()
    env = daily_lim.groupby(daily_lim.index.strftime("%Y-%m")).mean().round(1).rename("日均涨停家数")
    top = bm.groupby("月")["streak"].max().rename("当月最高连板")
    leaders = []
    for ym, sub in bm.groupby("月"):
        mx = sub["streak"].max()
        names = sub[sub["streak"] == mx]["name"].unique()[:3]
        leaders.append("、".join(names))
    env_df = pd.concat([env, top, pd.Series(leaders, index=top.index, name="当月龙头")], axis=1)
    env_df.index.name = "月"
    env_df.to_csv(f"{OUT}/汇总/月度环境.csv", encoding="utf-8-sig")

    # 好差票验证: 六组每月一个md(组=高度段×跌幅阴阳; 断4天+/3板参考行只进全量明细)
    scheme_note = {
        "2板反包阴": "**S1 一根急杀**（出手）= 断板期累计跌8~15% 且恰好1根阴线——2板专用，不分阴阳",
        "2板反包阳": "**S1 一根急杀**（出手）= 断板期累计跌8~15% 且恰好1根阴线——2板专用，不分阴阳",
        "4板反包阴": "**S2 四板阴断1**（出手）= 断1天；O2 四板阴断3（观察）= 断3天",
        "4板反包阳": "本组无出手格（4板断板没跌=假强势，历史-1.09），数据留档观察",
        "5+板反包阴": "**O1 五板+阴断1**（观察）= 断1天；弱于S3，等条件加持",
        "5+板反包阳": "**S3 五板+阳断1**（出手）= 断1天；5+不设高度上限（含6/7/8板…）",
    }
    for gname in ["2板反包阴", "2板反包阳", "4板反包阴", "4板反包阳", "5+板反包阴", "5+板反包阳"]:
        sub_all = E[E["组"] == gname]
        gdir = f"{OUT}/好差票验证/{gname}"
        os.makedirs(gdir, exist_ok=True)
        idx_rows = []
        for ym, sub in sub_all.groupby("月"):
            sub = sub.sort_values("反包日")
            done = sub[~sub["未完"]]
            bad = done[done["坏票"] == True]  # noqa: E712
            good = done[done["坏票"] == False]  # noqa: E712
            bad = bad.sort_values("次日收%")
            good = good.sort_values("持有到断板%", ascending=False)
            zb_bad = int(((done["结果"] == "炸板") & (done["坏票"] == True)).sum())  # noqa: E712
            fb = int((done["结果"] == "封次日负").sum())
            lb = int((done["结果"] == "连板").sum())
            gc = [int((done["断板天数"] == k).sum()) for k in GS_MAIN]
            hit = done[done["方案点"].astype(str) != ""]
            hit_s = hit[hit["方案点"].str.startswith(("S1", "S2", "S3"))]
            hs = (f" | ✅方案点命中 {len(hit)} 笔（S级出手 {len(hit_s)} 笔"
                  f"{'，胜率' + f'{(hit_s['次日收%'] > 0).mean() * 100:.0f}%' if len(hit_s) else ''}）"
                  if len(hit) else " | 方案点命中 0 笔")
            env_line = ""
            if ym in env_df.index:
                e0 = env_df.loc[ym]
                env_line = (f"当月环境: 日均涨停 {e0['日均涨停家数']:.0f} 家 | "
                            f"当月最高 {e0['当月最高连板']} 连板 | 龙头: {e0['当月龙头']}")
            seg_lab = gname[:gname.index("反包")]
            yy = gname[-1]
            L = [
                f"# 反包 · {gname} · {ym} · 好票坏票清单（v2 六组）", "",
                f"本月触发 {len(done)} 笔（断1天 {gc[0]} / 断2天 {gc[1]} / 断3天 {gc[2]}） | "
                f"坏票 {len(bad)}（炸板没收回 {zb_bad} + 封住次日跌 {fb}） | "
                f"好票 {len(good)}（继续连板 {lb}） | 坏票率 {len(bad) / max(len(done), 1) * 100:.0f}%"
                + (f" | 数据末端未完 {len(sub) - len(done)} 笔不计" if len(sub) > len(done) else "") + hs,
                "", env_line, "",
                "**本组方案点**（买入前可知，命中才出手）",
                "- " + scheme_note[gname],
                "- 「—」= 未命中，方案不出手", "",
                "**判定标准**（同高位接力口径）",
                f"- 事件 = 前波{seg_lab}连板 → 断板1~3天（每日收盘不涨停）→ 反包日盘中触及涨停价",
                f"- 阴阳 = 跌幅口径（阴=收盘低于前日收盘，阳=涨或平）；本组末日为{yy}",
                "- 买入 = 反包日盘中碰到涨停价按涨停价买；一字板（全天没打开）买不进，已剔除",
                "- 坏票 = 买入后第二天收盘低于买价（炸板但第二天涨回来的算好票）",
                "- 持有到断板 = 涨停价买入，首次不再涨停的那天收盘卖出，15个交易日兜底（反包日炸板=当天收盘卖）", "",
                "**列说明**",
                "- 断 = 断板天数；断板期 = 逐日「阴阳+涨跌幅」；坑深 = 断板期最低收盘距末板收盘%；炸板日 = 断板期盘中触板但收盘未封",
                "- 距MA5% = 反包前一天收盘距5日线%（4+板断1天恒在线上，2板看是否杀破）",
                "- 链 = 前波首板→末板各板「板型+开盘涨幅%」（一字/实体/下影）；地基 = 前波首板前一天阴阳涨跌",
                "- 位置 = 反包前一天收盘距60日新高%；均线 = 反包前一天5/10/20/30日线排列（+=短线在上）",
                "- 前波 = 本波首板之前60天内最高连板；环境 = 前一天全市场涨停家数；反包开盘% = 反包日开盘涨幅", "",
            ]
            header = ("| 代码 | 名称 | 反包日 | 断 | 方案点 | 结果 | 次日开% | 次日收% | 持有到断板% | 断板期 | 坑深% | "
                      "距MA5% | 链 | 反包开盘% | 地基 | 位置% | 均线 | 前波 | 环境 |")
            sep = "|---|" * 18 + "---|"

            def row_of(r):
                ma5 = r["距MA5%"]
                ma5s = f"{ma5:+.1f}" if ma5 == ma5 else ""
                return (f"| {r['代码']} | {r['名称']} | {r['反包日']} | {r['断板天数']} | "
                        f"{'**' + r['方案点'] + '**' if r['方案点'] else '—'} | {r['结果']} "
                        f"| {r['次日开%']:+.1f} | {r['次日收%']:+.1f} | {r['持有到断板%']:+.1f} "
                        f"| {r['断板期']} | {r['坑深%']:+.1f} | {ma5s} | {r['链']} | {r['反包开盘%']:+.1f} "
                        f"| {r['地基']} | {r['位置%']:+.1f} | {r['均线']} | {r['前波60日最高板'] or ''} "
                        f"| {r['昨日涨停家数'] or ''} |")

            L += [f"## 坏票 — {len(bad)} 笔", "", header, sep]
            L += [row_of(r) for _, r in bad.iterrows()]
            L += ["", f"## 好票 — {len(good)} 笔", "", header, sep]
            L += [row_of(r) for _, r in good.iterrows()]
            with open(f"{gdir}/{ym}.md", "w", encoding="utf-8") as fp:
                fp.write("\n".join(L) + "\n")
            idx_rows.append({"月": ym, "触发": len(done), "方案点命中": len(hit),
                             "S级出手": len(hit_s), "炸板坏票": zb_bad,
                             "封次日负": fb, "好票": len(good), "连板": lb,
                             "坏票率%": round(len(bad) / max(len(done), 1) * 100)})
        pd.DataFrame(idx_rows).to_csv(f"{OUT}/好差票验证/_索引_{gname}.csv",
                                      index=False, encoding="utf-8-sig")
    return mo, env_df


def main():
    eng = create_engine(os.environ["DATABASE_URL"])
    bars, end = build_bars(eng)
    print(f"日线 {START_BARS} ~ {end}, 主板非ST {bars['vt_symbol'].nunique()} 只")
    E = build_events(bars)
    matrix_text = stat_tables(E, end)
    mo, env_df = export_files(E, bars, end, matrix_text)
    print(matrix_text)
    print(f"\n已输出到 {OUT}")


if __name__ == "__main__":
    main()
