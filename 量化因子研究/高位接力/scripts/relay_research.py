# -*- coding: utf-8 -*-
"""高位接力(二接三/三接四)研究 —— 样本构建、基线统计、按月归档、好票坏票清单。

用法(容器内):
    python /tmp/research/relay_research.py            # 全跑: 构建事件+统计+导出文件
    python /tmp/research/relay_research.py stats      # 只读已导出的明细重新打印统计

口径 = 量化因子研究/高位接力/高位接力需求.md (2026-09-19 定稿):
- 事件: 昨日收盘恰好N连板(N=2 二接三 / N=3 三接四), 当日盘中碰到涨停价 → 涨停价买入;
  一字板(全天没打开)买不进, 排除; T字(一字开盘盘中打开)可以买
- 阴阳分组: 首板前一天K线, 收盘>=开盘=阳, 否则=阴
- 坏票: 买入后第二天收盘低于买价(炸板但第二天涨回来的算好票)
- 收益主算法: 涨停价买入, 持有到首次不再涨停日的收盘卖出, 15个交易日兜底
- 股票范围: 主板非ST非退(按当前名称); 涨停判定=不复权昨收×1.10四舍五入到分;
  上市前5个交易日不参与
- 数据末端附近的票: 还没走到卖出日数据就没了的, 标记「未完」, 不进收益统计

输出(容器内 /tmp/research/relay_out, 跑完 docker cp 回宿主 量化因子研究/高位接力/):
    全量明细.csv / 汇总/基线汇总.md / 汇总/按月汇总.csv / 汇总/月度环境.csv
    好差票验证/<组>/YYYY-MM.md + _索引_<组>.csv
"""
import os
import sys

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

OUT = "/tmp/research/relay_out"
START_BARS = "2022-06-01"          # 给2023-01的事件留足地基/均线/前波的回看窗口
START_EVT = pd.Timestamp("2023-01-01")
LSHADOW_TH = 0.3                   # 板型分类: 下影线≥0.3%算「带下影线」, 否则「换手实体阳线」
GROUPS = [("二接三", 2), ("三接四", 3)]

pd.set_option("display.width", 320)
pd.set_option("display.max_columns", 100)


def board_type(one_word, lshadow):
    if one_word:
        return "一字"
    return "下影" if lshadow >= LSHADOW_TH else "实体"


def build_events(eng):
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
    bars["chg"] = bars["close_price"] / bars["prev_close"] - 1
    lo = pd.concat([bars["open_price"], bars["close_price"]], axis=1).min(axis=1)
    bars["lshadow"] = (lo - bars["low_price"]) / bars["prev_close"] * 100
    gv = g["volume"]
    bars["vol_rel5"] = bars["volume"] / gv.transform(lambda s: s.rolling(5, min_periods=3).mean())
    gc = g["close_price"]
    for w in (5, 10, 20, 30):
        bars[f"ma{w}"] = gc.transform(lambda s: s.rolling(w, min_periods=w).mean())
    bars["h60"] = g["high_price"].transform(lambda s: s.rolling(60, min_periods=20).max())
    bars["l60"] = g["low_price"].transform(lambda s: s.rolling(60, min_periods=20).min())
    bars["c20"] = g["close_price"].shift(20)
    bars["streak_prev"] = g["streak"].shift(1).fillna(0).astype(int)
    # 连板段尾(供前波查询): 当天涨停且第二天不再涨停
    bars["run_end"] = bars["is_lim"] & (~g["is_lim"].shift(-1).fillna(False).astype(bool))
    for k in range(1, 16):
        bars[f"n{k}_close"] = g["close_price"].shift(-k)
        bars[f"n{k}_open"] = g["open_price"].shift(-k)
        bars[f"n{k}_is_lim"] = g["is_lim"].shift(-k)

    # 市场环境: 每天全市场涨停家数
    mkt = bars.groupby("trade_date", sort=False)["is_lim"].sum()
    bars["mkt_lim"] = bars["trade_date"].map(mkt)
    mkt_prev = mkt.shift(1)
    bars["mkt_prev"] = bars["trade_date"].map(mkt_prev)

    # ---- 事件 ----
    ev_mask = bars["streak_prev"].isin([2, 3]) & bars["touch"] & (bars["trade_date"] >= START_EVT)
    n_ow = int((ev_mask & bars["one_word"]).sum())
    ev = bars[ev_mask & ~bars["one_word"]].copy()
    print(f"日线数据 {START_BARS} ~ {end}, 主板非ST {bars['vt_symbol'].nunique()} 只")
    print(f"碰到涨停价的事件 {int(ev_mask.sum())} 笔, 其中一字买不进剔除 {n_ow} 笔, 入池 {len(ev)} 笔")

    # 列数组化, 事件行用整数偏移取前后行(同一只票内部 pos 连续)
    cols = {c: bars[c].to_numpy() for c in
            ["vt_symbol", "name", "close_price", "open_price", "high_price", "low_price",
             "prev_close", "limit_price", "is_lim", "one_word", "streak", "chg", "lshadow",
             "turnover_rate", "vol_rel5", "ma5", "ma10", "ma20", "ma30", "h60", "l60", "c20",
             "trade_date", "mkt_lim", "mkt_prev"]}
    dates = bars["trade_date"].to_numpy()
    sid_arr = bars["sid"].to_numpy()

    # 前波查询: 每只票的连板段(高度>=2)段尾pos与高度
    runs = bars[bars["run_end"] & (bars["streak"] >= 2)][["sid", "pos", "streak"]]
    run_by = {s: (a["pos"].to_numpy(), a["streak"].to_numpy())
              for s, a in runs.groupby("sid", sort=False)}

    rows = []
    for i in ev.index.to_numpy():
        N = int(cols["streak"][i - 1])          # 昨日连板数 = 2或3
        p = int(i)                               # 事件行即买入日D
        pos = int(bars["pos"].iat[p])
        if pos - N - 1 < 0:
            continue                             # 首板前一天都没有, 地基缺失, 跳过
        f = p - N - 1                            # 首板前一天(地基日)
        if sid_arr[f] != sid_arr[p]:             # 同票偏移校验, 防跨票
            continue
        rec = {}
        rec["代码"] = cols["vt_symbol"][p]
        rec["名称"] = cols["name"][p]
        rec["买入日"] = pd.Timestamp(dates[p]).strftime("%Y-%m-%d")
        rec["组"] = "二接三" if N == 2 else "三接四"
        rec["N"] = N
        # 阴阳与地基(首板前一天)
        fo, fc = cols["open_price"][f], cols["close_price"][f]
        rec["阴阳"] = "阳" if fc >= fo else "阴"
        rec["首板日"] = pd.Timestamp(dates[p - N]).strftime("%Y-%m-%d")
        rec["地基涨跌%"] = round((cols["chg"][f]) * 100, 2)
        rec["距60日新高%"] = round((fc / cols["h60"][f] - 1) * 100, 1) if cols["h60"][f] == cols["h60"][f] else np.nan
        rec["距60日低点%"] = round((fc / cols["l60"][f] - 1) * 100, 1) if cols["l60"][f] == cols["l60"][f] else np.nan
        ma = [cols[m][f] for m in ("ma5", "ma10", "ma20", "ma30")]
        rec["均线"] = "".join("+" if a >= b else "-" for a, b in zip(ma, ma[1:])) if all(x == x for x in ma) else ""
        rec["地基前20日涨幅%"] = round((fc / cols["c20"][f] - 1) * 100, 1) if cols["c20"][f] == cols["c20"][f] else np.nan
        # 前波: 首板之前的连板段
        ends, hts = run_by.get(sid_arr[p], (np.array([]), np.array([])))
        before = ends < (pos - N)
        rec["距前波末板"] = int(pos - N - ends[before].max()) if before.any() else None
        for win in (60, 120):
            inwin = before & (ends >= pos - N - win)
            rec[f"前波{win}日最高板"] = int(hts[inwin].max()) if inwin.any() else 0
        # 接力链: 首板~买入前一天逐板
        chain = []
        for k in range(1, N + 1):
            j = p - N + k - 1
            bt = board_type(bool(cols["one_word"][j]), cols["lshadow"][j])
            og = (cols["open_price"][j] / cols["prev_close"][j] - 1) * 100
            rec[f"b{k}日"] = pd.Timestamp(dates[j]).strftime("%m-%d")
            rec[f"b{k}板型"] = bt
            rec[f"b{k}开盘%"] = round(og, 1)
            rec[f"b{k}下影%"] = round(cols["lshadow"][j], 1)
            rec[f"b{k}换手%"] = round(cols["turnover_rate"][j], 1) if cols["turnover_rate"][j] == cols["turnover_rate"][j] else np.nan
            chain.append(f"{bt}{og:+.0f}")
        rec["链"] = "→".join(chain)
        # 买入日
        buy = cols["limit_price"][p]
        rec["买价"] = round(buy, 2)
        rec["买入开盘%"] = round((cols["open_price"][p] / cols["prev_close"][p] - 1) * 100, 2)
        rec["买入换手%"] = round(cols["turnover_rate"][p], 1) if cols["turnover_rate"][p] == cols["turnover_rate"][p] else np.nan
        rec["买入量比"] = round(cols["vol_rel5"][p], 2) if cols["vol_rel5"][p] == cols["vol_rel5"][p] else np.nan
        rec["买入日涨停家数"] = int(cols["mkt_lim"][p])
        rec["昨日涨停家数"] = int(cols["mkt_prev"][p]) if cols["mkt_prev"][p] == cols["mkt_prev"][p] else None
        # 结果: 封住/炸板, 次日收益, 持有到断板
        rec["封住"] = bool(cols["is_lim"][p])
        n1c = bars["n1_close"].iat[p]
        n1o = bars["n1_open"].iat[p]
        rec["次日开%"] = round((n1o / buy - 1) * 100, 2) if n1o == n1o else np.nan
        rec["次日收%"] = round((n1c / buy - 1) * 100, 2) if n1c == n1c else np.nan
        rec["次日连板"] = bool(bars["n1_is_lim"].iat[p]) if n1c == n1c else False
        # 持有到断板: 买入次日(T+1)起首个不再涨停日收盘卖, 15个交易日兜底
        exit_px, hold_days = np.nan, None
        for k in range(1, 16):
            v = bars[f"n{k}_is_lim"].iat[p]
            c = bars[f"n{k}_close"].iat[p]
            if c != c:
                break
            if not bool(v):
                exit_px, hold_days = c, k
                break
        if exit_px != exit_px and bars["n15_close"].iat[p] == bars["n15_close"].iat[p]:
            exit_px, hold_days = bars["n15_close"].iat[p], 15
        rec["持有到断板%"] = round((exit_px / buy - 1) * 100, 2) if exit_px == exit_px else np.nan
        rec["持有天数"] = hold_days
        rec["未完"] = exit_px != exit_px
        # 最终高度
        h = N + 1 if rec["封住"] else N
        for k in range(1, 16):
            if bool(bars[f"n{k}_is_lim"].iat[p]):
                h = N + 1 + k
            else:
                break
        rec["最终高度"] = h
        # 结果分类与好票坏票
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
        rec["月"] = rec["买入日"][:7]
        rec["年"] = rec["买入日"][:4]
        rows.append(rec)

    E = pd.DataFrame(rows)
    E["四组"] = E["组"] + E["阴阳"]
    E["坏票"] = E["坏票"].astype("boolean")
    return E, bars, end


def stat_tables(E):
    lines = []
    fin = E[~E["未完"]].copy()

    def agg(sub):
        if len(sub) == 0:
            return dict(n=0)
        return dict(
            n=len(sub),
            封住率=f"{sub['封住'].mean() * 100:.0f}%",
            坏票率=f"{sub['坏票'].mean() * 100:.0f}%",
            次日收益=f"{sub['次日收%'].mean():+.2f}",
            次日胜率=f"{(sub['次日收%'] > 0).mean() * 100:.0f}%",
            再连板率=f"{sub['次日连板'].mean() * 100:.0f}%",
            持有到断板=f"{sub['持有到断板%'].mean():+.2f}",
        )

    order = ["二接三阴", "二接三阳", "三接四阴", "三接四阳"]
    rows = []
    for name in order + ["二接三", "三接四", "全部"]:
        sub = fin[fin["四组"] == name] if name in order else (
            fin[fin["组"] == name] if name != "全部" else fin)
        d = agg(sub)
        d["组"] = name
        rows.append(d)
    t1 = pd.DataFrame(rows).set_index("组")
    lines.append("## 四组基线\n")
    lines.append(t1.to_markdown())
    lines.append("")

    lines.append("## 分年（持有到断板% / 样本量）\n")
    for name in order:
        sub = fin[fin["四组"] == name]
        by = sub.groupby("年").agg(
            n=("持有到断板%", "size"),
            收益=("持有到断板%", lambda s: round(s.mean(), 2)),
            胜率=("次日收%", lambda s: f"{(s > 0).mean() * 100:.0f}%"))
        lines.append(f"**{name}** (n={len(sub)})")
        lines.append(by.to_markdown())
        lines.append("")
    return "\n".join(lines), t1


def export_files(E, bars, end):
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(f"{OUT}/汇总", exist_ok=True)
    os.makedirs(f"{OUT}/好差票验证", exist_ok=True)

    E.to_csv(f"{OUT}/全量明细.csv", index=False, encoding="utf-8-sig")

    fin = E[~E["未完"]]
    # 按月汇总
    mo = fin.groupby(["四组", "月"]).agg(
        笔数=("持有到断板%", "size"),
        坏票率=("坏票", lambda s: f"{s.mean() * 100:.0f}%"),
        封住率=("封住", lambda s: f"{s.mean() * 100:.0f}%"),
        次日收益=("次日收%", lambda s: round(s.mean(), 2)),
        持有到断板=("持有到断板%", lambda s: round(s.mean(), 2)),
    ).reset_index()
    mo.to_csv(f"{OUT}/汇总/按月汇总.csv", index=False, encoding="utf-8-sig")

    # 月度环境: 日均涨停家数 + 当月最高连板 + 龙头
    bm = bars[bars["trade_date"] >= START_EVT].copy()
    bm["月"] = bm["trade_date"].dt.strftime("%Y-%m")
    daily_lim = bm.groupby("trade_date")["is_lim"].sum()
    env = daily_lim.groupby(daily_lim.index.strftime("%Y-%m")).mean().round(1).rename("日均涨停家数")
    top = bm.groupby("月")["streak"].max().rename("当月最高连板")
    leaders = []
    for ym, sub in bm.groupby("月"):
        mx = sub["streak"].max()
        names = sub[sub["streak"] == mx]["name"].unique()[:3]
        leaders.append("、".join(f"{n}" for n in names))
    env_df = pd.concat([env, top, pd.Series(leaders, index=top.index, name="当月龙头")], axis=1)
    env_df.index.name = "月"
    env_df.to_csv(f"{OUT}/汇总/月度环境.csv", encoding="utf-8-sig")

    # 好差票验证: 每组每月一个md
    idx_rows = []
    for gname in ["二接三阴", "二接三阳", "三接四阴", "三接四阳"]:
        sub_all = E[E["四组"] == gname]
        gdir = f"{OUT}/好差票验证/{gname}"
        os.makedirs(gdir, exist_ok=True)
        for ym, sub in sub_all.groupby("月"):
            sub = sub.sort_values("买入日")
            done = sub[~sub["未完"]]
            bad = done[done["坏票"]].sort_values("次日收%")
            good = done[~done["坏票"]].sort_values("持有到断板%", ascending=False)
            zb = int((done["结果"] == "炸板").sum())
            zb_bad = int(((done["结果"] == "炸板") & done["坏票"]).sum())
            fb = int((done["结果"] == "封次日负").sum())
            lb = int((done["结果"] == "连板").sum())
            env_line = ""
            if ym in env_df.index:
                e0 = env_df.loc[ym]
                env_line = (f"当月环境: 日均涨停 {e0['日均涨停家数']:.0f} 家 | "
                            f"当月最高 {e0['当月最高连板']} 连板 | 龙头: {e0['当月龙头']}")
            L = [
                f"# 高位接力 · {gname} · {ym} · 好票坏票清单", "",
                f"本月触发 {len(done)} 笔 | 坏票 {len(bad)}（炸板没收回 {zb_bad} + 封住次日跌 {fb}） | "
                f"好票 {len(good)}（继续连板 {lb}） | 坏票率 {len(bad) / max(len(done), 1) * 100:.0f}%"
                + (f" | 数据末端未完 {len(sub) - len(done)} 笔不计" if len(sub) > len(done) else ""),
                "", env_line, "",
                "**判定标准**",
                "- 买入 = 盘中碰到涨停价按涨停价买；一字板（全天没打开）买不进，已剔除",
                "- 坏票 = 买入后第二天收盘低于买价（炸板但第二天涨回来的算好票）",
                "- 持有到断板 = 涨停价买入，首次不再涨停的那天收盘卖出，15个交易日兜底", "",
                "**列说明**",
                f"- 链 = 首板→买入前一天各板的「板型+开盘涨幅%」；板型分 一字 / 实体（换手实体阳线，下影<{LSHADOW_TH}%）/ 下影",
                "- 地基 = 首板前一天的阴阳和涨跌幅；位置 = 首板前一天收盘距60日新高%；均线 = 首板前一天5/10/20/30日线排列（+=短线在上）",
                "- 前波 = 近60天内前一波连板最高几板；环境 = 前一天全市场涨停家数", "",
            ]
            header = ("| 代码 | 名称 | 买入日 | 结果 | 次日开% | 次日收% | 持有到断板% | 链 | 买入开盘% | "
                      "地基 | 位置% | 均线 | 前波 | 环境 |")
            sep = "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"

            def row_of(r):
                return (f"| {r['代码']} | {r['名称']} | {r['买入日']} | {r['结果']} "
                        f"| {r['次日开%']:+.1f} | {r['次日收%']:+.1f} | {r['持有到断板%']:+.1f} "
                        f"| {r['链']} | {r['买入开盘%']:+.1f} "
                        f"| {r['阴阳']}{r['地基涨跌%']:+.1f} | {r['距60日新高%']:+.1f} | {r['均线']} "
                        f"| {r['前波60日最高板'] or ''} | {r['昨日涨停家数'] or ''} |")

            L += [f"## 坏票 — {len(bad)} 笔", "", header, sep]
            L += [row_of(r) for _, r in bad.iterrows()]
            L += ["", f"## 好票 — {len(good)} 笔", "", header, sep]
            L += [row_of(r) for _, r in good.iterrows()]
            with open(f"{gdir}/{ym}.md", "w", encoding="utf-8") as fp:
                fp.write("\n".join(L) + "\n")
            idx_rows.append({"组": gname, "月": ym, "触发": len(done), "炸板": zb,
                             "封次日负": fb, "好票": len(good), "连板": lb,
                             "坏票率%": round(len(bad) / max(len(done), 1) * 100)})
        pd.DataFrame([r for r in idx_rows if r["组"] == gname]).to_csv(
            f"{OUT}/好差票验证/_索引_{gname}.csv", index=False, encoding="utf-8-sig")
    return mo, env_df


def print_overview(E, t1, env_df, end):
    fin = E[~E["未完"]]
    print(f"\n===== 高位接力基线（2023-01 ~ {end}）=====")
    print(t1.to_string())
    print("\n== 分年（持有到断板%）==")
    for name in ["二接三阴", "二接三阳", "三接四阴", "三接四阳"]:
        sub = fin[fin["四组"] == name]
        by = sub.groupby("年").agg(n=("持有到断板%", "size"),
                                   收益=("持有到断板%", lambda s: round(s.mean(), 2)),
                                   胜率=("次日收%", lambda s: round((s > 0).mean() * 100)))
        print(f"{name:8s}", " ".join(f"{y}:{r.收益:+.2f}/{r.胜率}(n={r.n})" for y, r in by.iterrows()))
    print("\n== 板型分布（前置各板，全事件）==")
    for k in (1, 2, 3):
        col = f"b{k}板型"
        sub_k = E if k <= 2 else E[E["N"] >= 3]
        vc = sub_k[col].value_counts()
        print(f"第{k}板:", dict(vc))
    print("\n== 月度环境（近12个月）==")
    print(env_df.tail(12).to_string())


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "stats":
        E = pd.read_csv(f"{OUT}/全量明细.csv")
        text, t1 = stat_tables(E)
        print(text)
        return
    eng = create_engine(os.environ["DATABASE_URL"])
    E, bars, end = build_events(eng)
    text, t1 = stat_tables(E)
    mo, env_df = export_files(E, bars, end)
    with open(f"{OUT}/汇总/基线汇总.md", "w", encoding="utf-8") as f:
        f.write(f"# 高位接力 · 基线汇总（2023-01 ~ {end}）\n\n" + text + "\n")
    print_overview(E, t1, env_df, end)
    print(f"\n文件已输出到 {OUT}/ （全量明细.csv / 汇总/ / 好差票验证/）")


if __name__ == "__main__":
    main()
