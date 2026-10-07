# -*- coding: utf-8 -*-
"""低位一接二(首板次日打二板)研究 —— 样本构建、基线统计、按月归档。

用法(容器内):
    python /tmp/research/j12_research.py

口径 = 量化因子研究/一接二/一接二需求与计划.md (2026-10-06 立项):
- 事件: 昨日涨停且前日不涨停(孤立首板, streak_prev==1; 断板后再起的二波首板不排除,
  60日板史作分层维度), 当日盘中碰到涨停价 → 涨停价买入;
  一字板(全天没打开)买不进, 排除; T字(一字开盘盘中打开)可以买
- 池子: 主板非ST非退(按当前名称); 涨停判定=不复权昨收×1.10四舍五入到分;
  上市前5个交易日不参与
- 卖出: 全套沿用 hpr v6.7(算法逐行取自产品 high_relay/backtest.py, 注释保留):
  E3=炸板次日走/封住→断板日, 退出价=退出日收盘价; 收盘跌停仅全天一字死封顺延次日开盘,
  其余按跌停价卖出; v6.4 D+2深开竞价卖(昨天封板+今开≤-5%→竞价直接卖)
- 窗口: 主窗 2023-01~数据末端 + 样本外 2021-01~2022-12 同批建样本分开统计
- 无未来函数: 入场条件只用前一晚静态信息+竞价; 环境字段(涨停家数)只做信息层

行号语义: i=买入日, p1=i-1首板日, p2=i-2地基日(首板前一天), p3=i-3地基前一日。
位置五档用「地基日收盘距60日最高价」(hpr A1 同款口径, 窗口到地基日为止不含首板;
首板收盘=涨停价必然是窗口最高, 用首板日口径恒<=0 无意义)。

输出(容器内 /tmp/research/j12_out, 跑完 docker cp 回宿主 量化因子研究/一接二/):
    全量明细.csv / 汇总/基线汇总.md / 汇总/基线分档.csv / 汇总/按月汇总.csv
"""
import os

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

OUT = "/tmp/research/j12_out"
START_BARS = "2020-06-01"           # 给2021-01的事件留足60/120日回看窗口
START_EVT = pd.Timestamp("2021-01-01")
MAIN_START = pd.Timestamp("2023-01-01")   # 主窗与样本外(2021-2022)的分界
MAX_K = 15                          # 持有兜底天数(对齐 hpr)
LSHADOW_TH = 0.3                    # 板型分类: 下影线≥0.3%算「带下影线」

pd.set_option("display.width", 320)
pd.set_option("display.max_columns", 100)


# ── 派生 ────────────────────────────────────────────────────────────

def board_type_b1(o, h, l, c, limit):
    """首板板型四分类(比 hpr 三分类多拆 T 字: 一字开盘盘中砸开又回封, 封板质量信号)。"""
    if abs(o - c) <= 1e-6 and abs(o - h) <= 1e-6 and abs(o - l) <= 1e-6:
        return "一字"
    if abs(o - c) <= 1e-6 and abs(o - h) <= 1e-6:
        return "T字"          # 一字开盘、收盘回封、盘中砸开(low<open)
    lo = min(o, c)
    return "下影" if (lo - l) / (c / 1.10) * 100 >= LSHADOW_TH else "实体"
    # 上式分母=首板昨收的近似(c/1.10); 精确昨收在外层传入判断, 差异<0.01% 可忽略


def pos5(d):
    """位置五档: 地基日收盘距60日最高价(%), hpr A1 同款。"""
    if d != d:
        return "缺数据"
    if d < -30:
        return "跌透"
    if d < -10:
        return "低位"
    if d < 0:
        return "半山"
    if d <= 10:
        return "贴顶"
    return "新高"


def open6(o):
    """今开六档(对齐 hpr 开盘档)。"""
    if o != o:
        return "缺数据"
    if o < 0:
        return "低开"
    if o < 2:
        return "0~2"
    if o < 4:
        return "2~4"
    if o < 7:
        return "4~7"
    if o < 9.5:
        return "7~9.5"
    return "顶格"


def derive(bars):
    bars = bars.sort_values(["vt_symbol", "trade_date"], ignore_index=True)
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
    lo = pd.concat([bars["open_price"], bars["close_price"]], axis=1).min(axis=1)
    bars["lshadow"] = (lo - bars["low_price"]) / bars["prev_close"] * 100
    gv = g["volume"]
    bars["vol_rel5"] = bars["volume"] / gv.transform(lambda s: s.rolling(5, min_periods=3).mean())
    gc = g["close_price"]
    for w in (5, 10, 20, 30):
        bars[f"ma{w}"] = gc.transform(lambda s: s.rolling(w, min_periods=w).mean())
    bars["h60"] = g["high_price"].transform(lambda s: s.rolling(60, min_periods=20).max())
    bars["c10"] = gc.shift(10)
    bars["c20"] = gc.shift(20)
    bars["streak_prev"] = g["streak"].shift(1).fillna(0).astype(int)
    # 板史(不含当日, shift(1)): 60/120日涨停次数 + 窗口内最大连板数(识别断板后再起的二波首板)
    lim_i = bars["is_lim"].astype("int8")
    for w in (60, 120):
        bars[f"lim_cnt{w}"] = lim_i.groupby(bars["sid"], sort=False)\
            .transform(lambda s: s.rolling(w, min_periods=20).sum()).shift(1)
        bars[f"max_streak{w}"] = bars["streak"].groupby(bars["sid"], sort=False)\
            .transform(lambda s: s.rolling(w, min_periods=20).max()).shift(1)
    # 市场环境: 每天全市场涨停家数(信息层, 不进口诀)
    mkt = bars.groupby("trade_date", sort=False)["is_lim"].sum()
    bars["mkt_lim"] = bars["trade_date"].map(mkt)
    bars["mkt_prev"] = bars["trade_date"].map(mkt.shift(1))
    return bars


# ── E3 退出(v6.7, 逐行取自产品 high_relay/backtest.py) ────────────────

def e3_exit(bars, i, sealed, exit_e0, hold_days, exit_idx, capped):
    """返回 (exit_e3, e3_i, reason)。"""
    if sealed:
        d2o = bars["n2_open"].iat[i]
        d1c = bars["n1_close"].iat[i]
        if (hold_days is not None and hold_days >= 2 and d2o == d2o
                and d1c == d1c and (d2o / d1c - 1) <= -0.05):
            # v6.4 D+2 深开竞价卖: 昨天封板+今开≤-5%(高位出货车)→集合竞价直接卖
            return float(d2o), i + 2, "d2_deep_open_sell"
        if hold_days is None:
            return np.nan, None, None   # 数据尾部未完
        exit_e3, e3_date, e3_reason = float(exit_e0), exit_idx, (
            "next_close_fail" if hold_days == 1 else ("max_hold_close" if capped else "break_close"))
        hd0 = int(hold_days)
        prev0 = (float(bars[f"n{hd0 - 1}_close"].iat[i]) if hd0 > 1
                 else float(bars["limit_price"].iat[i]))
        k0o = float(bars[f"n{hd0}_open"].iat[i])
        k0h = float(bars[f"n{hd0}_high"].iat[i])
        k0l = float(bars[f"n{hd0}_low"].iat[i])
        if (float(exit_e0) <= prev0 * 0.905 + 0.011
                and k0o == k0h and k0h == k0l
                and abs(k0o - float(exit_e0)) <= 0.011):
            # v6.7: 仅一字死封(全天一价跌停)才顺延次日开盘; 其余收盘跌停按跌停价卖出
            pc = float(exit_e0)
            for j in range(hd0 + 1, MAX_K + 1):
                jo = float(bars[f"n{j}_open"].iat[i])
                if jo != jo:
                    break
                jh = float(bars[f"n{j}_high"].iat[i])
                jl = float(bars[f"n{j}_low"].iat[i])
                jc = float(bars[f"n{j}_close"].iat[i])
                if jo == jh == jl == jc and (jc / pc - 1) <= -0.095:
                    pc = jc
                    continue
                return float(jo), i + j, "limit_down_defer"
            return float(exit_e0), exit_idx, "limit_down_locked"
        return exit_e3, e3_date, e3_reason
    # 炸板: 次日走(当天卖不了), 一字跌停锁死续顺延
    prev_c = float(bars["close_price"].iat[i])
    for k in range(1, MAX_K + 1):
        ko = float(bars[f"n{k}_open"].iat[i])
        kc = float(bars[f"n{k}_close"].iat[i])
        if kc != kc:
            break
        kh = float(bars[f"n{k}_high"].iat[i])
        kl = float(bars[f"n{k}_low"].iat[i])
        locked = ko == kc == kh == kl and (kc / prev_c - 1) <= -0.095
        prev_c = kc
        if locked:
            continue
        return float(kc), i + k, "break_day_close"
    return np.nan, None, None


# ── 主流程 ──────────────────────────────────────────────────────────

def build_events(eng):
    end = pd.read_sql("select max(trade_date)::text from stock_daily_bars", eng).iloc[0, 0]
    stocks = pd.read_sql("select vt_symbol, name, market_cap from stocks", eng)
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
    name_map = stocks.set_index("vt_symbol")["name"].to_dict()
    cap_map = stocks.set_index("vt_symbol")["market_cap"].to_dict()

    bars = pd.read_sql(
        "select vt_symbol, trade_date, open_price, high_price, low_price, close_price, volume, turnover_rate "
        f"from stock_daily_bars where trade_date >= '{START_BARS}' and trade_date <= '{end}'",
        eng, parse_dates=["trade_date"])
    bars = bars.merge(stocks[["vt_symbol", "board", "bad"]], on="vt_symbol", how="left")
    bars = bars[(bars["board"] == "main") & (~bars["bad"])].copy()
    bars = bars.drop(columns=["board", "bad"]).reset_index(drop=True)
    bars = derive(bars)
    g = bars.groupby("sid", sort=False)
    for k in range(1, MAX_K + 1):
        bars[f"n{k}_close"] = g["close_price"].shift(-k)
        bars[f"n{k}_open"] = g["open_price"].shift(-k)
        bars[f"n{k}_high"] = g["high_price"].shift(-k)
        bars[f"n{k}_low"] = g["low_price"].shift(-k)
        bars[f"n{k}_is_lim"] = g["is_lim"].shift(-k)

    ev_mask = (bars["streak_prev"] == 1) & bars["touch"] & \
              (bars["trade_date"] >= START_EVT) & (~bars["one_word"])
    n_ow = int((ev_mask & bars["one_word"]).sum())
    ev = bars[ev_mask].copy()
    print(f"日线数据 {START_BARS} ~ {end}, 主板非ST {bars['vt_symbol'].nunique()} 只")
    print(f"首板次日触板事件 {int(ev_mask.sum())} 笔, 一字买不进已剔 {n_ow} 笔, 入池 {len(ev)} 笔")

    cols = {c: bars[c].to_numpy() for c in
            ["vt_symbol", "trade_date", "close_price", "open_price", "prev_close",
             "limit_price", "is_lim", "lshadow", "turnover_rate",
             "vol_rel5", "ma5", "ma10", "ma20", "ma30", "h60", "c10", "c20",
             "lim_cnt60", "max_streak60", "max_streak120", "mkt_prev", "pos"]}
    rows = []
    for i in ev.index.to_numpy():
        i = int(i)
        p1, p2, p3 = i - 1, i - 2, i - 3     # 首板日 / 地基日 / 地基前一日
        if cols["pos"][p1] < 2:              # 地基与地基前一日必须同票存在
            continue
        vsym = str(bars["vt_symbol"].iat[i])
        buy = round(float(cols["limit_price"][i]), 2)
        buy_open = round((float(cols["open_price"][i]) / float(cols["prev_close"][i]) - 1) * 100, 2)
        # 首开一字 = 买入日开盘即涨停价(含盘中砸开的T字; 全天一字已在ev_mask剔除)
        open_one_word = abs(float(cols["open_price"][i]) - buy) <= 1e-6
        sealed = bool(cols["is_lim"][i])

        # E0 持有到断板: 次日起首个不再涨停日收盘卖, 15日兜底
        exit_e0, hold_days, exit_idx, capped = np.nan, None, None, False
        for k in range(1, MAX_K + 1):
            v = bars[f"n{k}_is_lim"].iat[i]
            c = bars[f"n{k}_close"].iat[i]
            if c != c:
                break
            if not bool(v):
                exit_e0, hold_days, exit_idx = c, k, i + k
                break
        if exit_e0 != exit_e0 and bars[f"n{MAX_K}_close"].iat[i] == bars[f"n{MAX_K}_close"].iat[i]:
            exit_e0, hold_days, exit_idx = bars[f"n{MAX_K}_close"].iat[i], MAX_K, i + MAX_K
            capped = True
        unfinished = exit_e0 != exit_e0
        exit_e3, e3_i, e3_reason = (np.nan, None, None) if unfinished else \
            e3_exit(bars, i, sealed, exit_e0, hold_days, exit_idx, capped)

        # ── 地基日(p2)字段: 阴阳/位置/涨幅/均线 ──
        f2o, f2c = float(cols["open_price"][p2]), float(cols["close_price"][p2])
        f3c = float(cols["close_price"][p3])
        yang = f2c >= f2o
        f2_h60 = cols["h60"][p2]
        dist_h60 = (f2c / f2_h60 - 1) * 100 if f2_h60 == f2_h60 else np.nan
        f2_ma20 = cols["ma20"][p2]
        ma5f, ma10f = cols["ma5"][p2], cols["ma10"][p2]
        ma20f, ma30f = cols["ma20"][p2], cols["ma30"][p2]
        ma_state = ("多头" if (ma5f == ma5f and ma5f > ma10f > ma20f > ma30f) else "乱")
        f2_c10, f2_c20 = cols["c10"][p2], cols["c20"][p2]
        # ── 首板日(p1)字段: 板型/开盘/换手/开口/量比/板史 ──
        p1o = float(cols["open_price"][p1])
        p1h = float(bars["high_price"].iat[p1])
        p1l = float(bars["low_price"].iat[p1])
        p1c = float(cols["close_price"][p1])
        p1_limit = float(cols["limit_price"][p1])
        p1_prevc = float(cols["prev_close"][p1])      # = 地基日收盘
        lc60 = cols["lim_cnt60"][p1]
        ms60 = cols["max_streak60"][p1]
        ms120 = cols["max_streak120"][p1]
        h60_to_f2 = cols["h60"][p2]                   # 截至地基日的60日高(首板破没破它)

        e3_exit_date = None
        if not unfinished and e3_i is not None:
            e3_exit_date = pd.Timestamp(bars["trade_date"].iat[e3_i]).date().isoformat()
        n1o = bars["n1_open"].iat[i]
        n1c = bars["n1_close"].iat[i]
        rows.append({
            "代码": vsym,
            "名称": str(name_map.get(vsym) or ""),
            "买入日": pd.Timestamp(cols["trade_date"][i]),
            "段": "主窗" if cols["trade_date"][i] >= MAIN_START else "样本外",
            "买价": buy,
            "买入开盘%": buy_open,
            "首开一字": open_one_word,
            "封住": sealed,
            "次日开%": round((n1o / buy - 1) * 100, 2) if n1o == n1o else np.nan,
            "次日收%": round((n1c / buy - 1) * 100, 2) if n1c == n1c else np.nan,
            "持有到断板%": round((exit_e0 / buy - 1) * 100, 2) if not unfinished else np.nan,
            "E3%": round((exit_e3 / buy - 1) * 100, 2) if not unfinished else np.nan,
            "E3退出日": e3_exit_date,
            "E3原因": e3_reason if not unfinished else None,
            "持有天数": hold_days,
            "未完": unfinished,
            # ── 分组维度(全部买入前一晚可知) ──
            "地基阴阳": "阳" if yang else "阴",
            "位置五档": pos5(dist_h60),
            "地基距60高%": round(dist_h60, 2),
            "首板破60高": bool(p1c > h60_to_f2) if h60_to_f2 == h60_to_f2 else None,  # 首板涨停创60日新高
            "底盘纯度": ("纯底盘" if lc60 == 0 else ("孤立板" if ms60 == 1 else "前波连板")),
            "60日板数": int(lc60) if lc60 == lc60 else None,
            "60日最大连板": int(ms60) if ms60 == ms60 else None,
            "120日最大连板": int(ms120) if ms120 == ms120 else None,
            "首板板型": board_type_b1(p1o, p1h, p1l, p1c, p1_limit),
            "首板开盘%": round((p1o / p1_prevc - 1) * 100, 2),
            "首板换手%": round(float(cols["turnover_rate"][p1]), 2),
            "首板开口%": round((p1_limit - p1l) / p1_prevc * 100, 2),   # 盘中离涨停最远砸到多少
            "首板量比": round(float(cols["vol_rel5"][p1]), 2),
            "地基涨跌%": round((f2c / f3c - 1) * 100, 2),
            "地基距MA20%": round((f2c / f2_ma20 - 1) * 100, 2) if f2_ma20 == f2_ma20 else np.nan,
            "首板距MA20%": round((p1c / f2_ma20 - 1) * 100, 2) if f2_ma20 == f2_ma20 else np.nan,
            "前10日涨幅%": round((f2c / f2_c10 - 1) * 100, 2) if f2_c10 == f2_c10 else np.nan,
            "前20日涨幅%": round((f2c / f2_c20 - 1) * 100, 2) if f2_c20 == f2_c20 else np.nan,
            "均线": ma_state,
            "市值亿": round(float(cap_map[vsym]), 1) if cap_map.get(vsym) else None,  # 当前快照, 近似
            "今开档": open6(buy_open),
            # ── 信息层(不进口诀) ──
            "昨日涨停家数": int(cols["mkt_prev"][i]) if cols["mkt_prev"][i] == cols["mkt_prev"][i] else None,
        })
    E = pd.DataFrame(rows)
    E["月"] = E["买入日"].dt.strftime("%Y-%m")
    E["年"] = E["买入日"].dt.strftime("%Y")
    E["胜"] = E["次日收%"] > 0
    return E


def grp_stats(E, by, label):
    done = E[~E["未完"]]
    out = []
    for key, sub in done.groupby(by, observed=True):
        e3 = sub["E3%"]
        yr = sub.groupby("年")["E3%"].agg(["count", "mean"])
        yr_s = " / ".join(f"{y}:{int(r['count'])}笔{r['mean']:+.2f}" for y, r in yr.iterrows())
        out.append({
            "分组": label, "档": key, "笔数": len(sub),
            "胜率断板%": round((sub["持有到断板%"] > 0).mean() * 100, 1),
            "断板均值": round(sub["持有到断板%"].mean(), 2),
            "胜率E3%": round((e3 > 0).mean() * 100, 1),
            "E3均值": round(e3.mean(), 2),
            "E3中位": round(e3.median(), 2),
            "封板率%": round(sub["封住"].mean() * 100, 1),
            "分年E3": yr_s,
        })
    return pd.DataFrame(out)


def main():
    eng = create_engine(os.environ["DATABASE_URL"])
    os.makedirs(f"{OUT}/汇总", exist_ok=True)
    E = build_events(eng)
    E.to_csv(f"{OUT}/全量明细.csv", index=False, encoding="utf-8-sig")
    print(f"全量明细 {len(E)} 笔已导出")

    main_e = E[E["段"] == "主窗"].copy()
    oos_e = E[E["段"] == "样本外"]
    main_e["首板量比分档"] = pd.cut(main_e["首板量比"], [-.01, 1, 2, 3, 5, 10000],
                                  labels=["<1缩量", "1~2", "2~3", "3~5", "5+放量"])
    main_e["首板换手分档"] = pd.cut(main_e["首板换手%"], [-.01, 5, 10, 15, 25, 10000],
                                  labels=["<5", "5~10", "10~15", "15~25", "25+"])
    main_e["首板开口分档"] = pd.cut(main_e["首板开口%"], [-.01, 0.001, 1, 3, 100],
                                  labels=["0未开口", "0~1", "1~3", "3+深砸"])

    lines = ["# 一接二 · 基线汇总(第1-2步产出)", ""]
    for tag, D in (("主窗 2023-01~今", main_e), ("样本外 2021-01~2022-12", oos_e)):
        done = D[~D["未完"]]
        if not len(done):
            continue
        lines.append(f"## {tag}: 入池 {len(D)} 笔, 已完 {len(done)} 笔")
        e3 = done["E3%"]
        yr = done.groupby("年")["E3%"].agg(["count", "mean"])
        lines.append(
            f"- 全池不挑就买: 胜率(断板) {(done['持有到断板%'] > 0).mean() * 100:.1f}% / "
            f"断板均值 {done['持有到断板%'].mean():+.2f} / E3均值 {e3.mean():+.2f} / "
            f"E3中位 {e3.median():+.2f} / 封板率 {done['封住'].mean() * 100:.1f}%")
        lines.append("- 分年E3: " + " / ".join(
            f"{y}:{int(r['count'])}笔{r['mean']:+.2f}" for y, r in yr.iterrows()))
        lines.append("")

    all_tbl = []
    for col, label in [("地基阴阳", "地基阴阳"), ("位置五档", "位置五档(地基收盘距60高)"),
                       ("底盘纯度", "底盘纯度(60日板史)"), ("首板板型", "首板板型"),
                       ("今开档", "今开六档"), ("均线", "均线形态"),
                       ("首板量比分档", "首板量比"), ("首板换手分档", "首板换手"),
                       ("首板开口分档", "首板开口深度"), ("首板破60高", "首板破60日高")]:
        all_tbl.append(grp_stats(main_e, col, label))
    tbl = pd.concat(all_tbl, ignore_index=True)
    tbl.to_csv(f"{OUT}/汇总/基线分档.csv", index=False, encoding="utf-8-sig")
    with open(f"{OUT}/汇总/基线汇总.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
        fh.write("\n## 主窗分档基线(逐维, E3 口径)\n\n")
        fh.write(tbl.to_markdown(index=False))
    print(tbl.to_string(index=False))
    mth = main_e.groupby("月").agg(笔数=("代码", "count"), E3均值=("E3%", "mean"))
    mth.to_csv(f"{OUT}/汇总/按月汇总.csv", encoding="utf-8-sig")
    print(f"\n按月已导出; 月均 {len(main_e) / max(1, main_e['月'].nunique()):.1f} 笔")


if __name__ == "__main__":
    main()
