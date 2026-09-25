"""断板反包打板回测引擎:日线口径全量回放 + 物化报告。

口径 = 量化因子研究/反包/反包规则.md v2 定稿(2026-09-25),
事件构建逐行对齐研究脚本 fanbao_research.py build_events:
- 事件 = 前波恰好 N 连板(N=2/4/5+,5+无上限)→ 断板 g 天(昨日 notlim_prev≥1)
  → 当日盘中触涨停价(最高≥涨停价)且非一字全天(T字含在内);
  买价 = 涨停价(=昨收×1.10 四舍五入到分);样本自 2023-01 起
- 打标 = 五方案点 S1/S2/S3/O1/O2(全部 T-1 静态,与研究打标完全一致);
  3板与断4~5天保留在 E(参考行)但主格=False,不进 ledger_days
- 收益(单一口径,研究主算法,无 E0/E3 双轨) = 反包日炸板→当天收盘卖;
  封住→持有到首次不再涨停日收盘,15 个交易日兜底
- 胜率 = 好票率(次日收盘≥买价;坏票=次日收盘<买价,炸板但涨回来的算好票)
- 再连板率 = 封住的票里次日继续涨停占比;后续板分布 = 反包日起连板数 0/1/2/3+
统计口径: avg_pct=次日收%均值;win=次日收%≥0占比(=研究胜率);bw_pct=持有到断板均值;
bw_median=中位;锚点数字=研究定稿(汇总/基础矩阵.md)。
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine
from alphaagent.server.services.fanbao import contracts, pool as pool_mod, repository

REPLAY_START = pd.Timestamp("2023-01-01")
BARS_START = "2022-06-01"  # 暖机窗口(前波120/h60/ma30 需要的全部历史深度;与研究一致)
MAX_K = 15                 # 前向列深度:n1=入场次日 … n15=兜底出口(研究 15 日口径)


def run_backtest() -> dict[str, object]:
    """全量回放并返回物化 payload(不写库,由调用方持久化)。"""
    E = _build_events()
    done = E[~E["未完"]].copy()
    main = done[done["主格"]].copy()

    keys = list(contracts.POINT_KEYS) + ["S级", "all", "miss"]

    def subset(key: str) -> pd.DataFrame:
        if key == "all":
            return main[main["方案点"] != "—"]
        if key == "S级":
            return main[main["方案点"].isin(["S1", "S2", "S3"])]
        if key == "miss":
            return main[main["方案点"] == "—"]
        return main[main["方案点"] == key]

    frames = {k: subset(k) for k in keys}
    summary = {k: _stats(frames[k]) for k in keys}
    coverage = {
        "from": _date_str(main["买入日"].min()) if len(main) else None,
        "to": _date_str(main["买入日"].max()) if len(main) else None,
        "months": int(pd.to_datetime(main["买入日"]).dt.to_period("M").nunique())
        if len(main) else 0,
    }
    payload: dict[str, object] = {
        "rules_version": contracts.FANBAO_RULES_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coverage": coverage,
        "caliber": ("日线口径:前波恰好2/4/5+连板(5+无上限)→断板1~3天→当日最高价触涨停价"
                    "(=昨收×1.10)按涨停价买,一字全天不开排除(T字可买);"
                    "收益=反包日炸板当天收盘走/封住→持有到断板日收盘(15日兜底);"
                    "胜率=好票率(次日收盘≥买价);无滑点,日线未复权。"
                    "池=断板中全量(雷达),出手=五方案点命中,死格命中也不买。"),
        "group6_labels": contracts.GROUP6_LABELS,
        "point_labels": contracts.POINT_LABELS,
        "point_levels": contracts.POINT_LEVELS,
        "summary": summary,
        "group6_summary": {g6: _stats(main[main["六组"] == g6])
                           for g6 in contracts.GROUP6_KEYS},
        "matrix18": _matrix18(main),
        "matrix18_yearly": _matrix18_yearly(main),
        "ref_rows": _ref_rows(done),
        "yin_split": _yin_split(main),
        "pit_split": _pit_split(main),
        "yearly": {k: _yearly(frames[k]) for k in keys},
        "monthly": {k: _monthly(frames[k]) for k in keys},
        "curves": {k: _curve(frames[k]) for k in keys},
        "yearly_totals": _yearly_totals(frames["all"]),
        "anchors": contracts.BACKTEST_ANCHORS,
        "anchor_tolerances": contracts.ANCHOR_TOLERANCES,
        "anchor_check": _anchor_check(summary),
        "matrix_anchors": contracts.MATRIX_ANCHORS,
        "matrix_anchor_check": _matrix_anchor_check(_matrix18(main)),
        "case_gates": _case_gates(done),
        "dead_stats": _dead_stats(done),
        "radar": _radar_stats(main),
    }
    payload["ledger_days"] = _ledger_days(frames["all"], repository.load_touch_map())
    return payload


# ── 事件池构建(反包日 D 行;断板期字段由 pool.break_fields 按昨日行算) ──

def _build_events() -> pd.DataFrame:
    engine = get_engine()
    universe = pool_mod.load_universe(engine)
    name_map = universe.set_index("vt_symbol")["name"].to_dict()

    bars = pd.read_sql(
        select(schema.stock_daily_bars.c.vt_symbol,
               schema.stock_daily_bars.c.trade_date,
               schema.stock_daily_bars.c.open_price,
               schema.stock_daily_bars.c.high_price,
               schema.stock_daily_bars.c.low_price,
               schema.stock_daily_bars.c.close_price,
               schema.stock_daily_bars.c.volume)
        .where(schema.stock_daily_bars.c.trade_date >= date.fromisoformat(BARS_START)),
        engine, parse_dates=["trade_date"])
    bars = bars[bars["vt_symbol"].isin(set(universe["vt_symbol"]))].copy()
    bars = pool_mod.derive_daily(bars)
    g = bars.groupby("sid", sort=False)
    for k in range(1, MAX_K + 1):
        bars[f"n{k}_close"] = g["close_price"].shift(-k)
        bars[f"n{k}_open"] = g["open_price"].shift(-k)
        bars[f"n{k}_is_lim"] = g["is_lim"].shift(-k)

    # 事件 = 昨日已断板 × 当日触板 × 非一字全天(研究 cand 口径)
    ev_mask = (bars["notlim_prev"] >= 1) & bars["touch"] \
              & (bars["trade_date"] >= REPLAY_START) & (~bars["one_word"])
    ev = bars[ev_mask]
    ctx = pool_mod.make_ctx(bars)

    cols = {c: bars[c].to_numpy() for c in
            ["close_price", "open_price", "prev_close", "limit_price", "is_lim",
             "mkt_prev", "trade_date"]}
    rows: list[dict[str, object]] = []
    for i in ev.index.to_numpy():
        i = int(i)
        # 昨日(=断板期最后一天)行号;break_fields 按断板中日算全部断板期字段
        p = i - 1
        if int(ctx["sid"][p]) != int(ctx["sid"][i]):
            continue
        rec = pool_mod.break_fields(ctx, p)
        if rec is None:
            continue
        n_board = int(rec["n_board"])
        gap = int(rec["gap"])
        seg = rec["seg"]
        yy = str(rec["yin_yang"])
        main_cell = bool(seg) and gap in contracts.GS_MAIN
        group6 = f"{seg}{yy}" if seg else f"{n_board}板{yy}"
        buy = round(float(cols["limit_price"][i]), 2)
        point = contracts.tag_point(n_board, gap, yy,
                                    rec["break_drop_pct"], int(rec["break_yin_count"]),
                                    last_entity=str(rec["last_entity"]),
                                    last_open_pct=rec["last_open_pct"])
        sealed = bool(cols["is_lim"][i])
        n1c = bars["n1_close"].iat[i]
        n1o = bars["n1_open"].iat[i]
        n1lim = bars["n1_is_lim"].iat[i]
        # 收益(单一口径): 炸板→当天收盘;封住→次日起首个不再涨停日收盘,15 日兜底
        exit_px, hold_days = np.nan, None
        exit_idx: int | None = None
        capped = False
        if not sealed:
            exit_px, hold_days, exit_idx = float(cols["close_price"][i]), 0, i
        else:
            for k in range(1, MAX_K + 1):
                v = bars[f"n{k}_is_lim"].iat[i]
                c = bars[f"n{k}_close"].iat[i]
                if c != c:
                    break
                if not bool(v):
                    exit_px, hold_days = c, k
                    exit_idx = i + k
                    break
            if exit_px != exit_px and bars[f"n{MAX_K}_close"].iat[i] == bars[f"n{MAX_K}_close"].iat[i]:
                exit_px, hold_days = bars[f"n{MAX_K}_close"].iat[i], MAX_K
                exit_idx = i + MAX_K
                capped = True
        unfinished = exit_px != exit_px
        exit_reason = None
        exit_day = None
        if not unfinished:
            if not sealed:
                exit_reason = "break_day_close"
            elif hold_days == 1:
                exit_reason = "next_close_fail"
            elif capped:
                exit_reason = "max_hold_close"
            else:
                exit_reason = "break_close"
            if exit_idx is not None:
                exit_day = pd.Timestamp(bars["trade_date"].iat[exit_idx]).date().isoformat()
        # 反包日起连板数(后续板分布;炸板=0)
        follow = 0
        if sealed:
            follow = 1
            for k in range(1, MAX_K + 1):
                v = bars[f"n{k}_is_lim"].iat[i]
                if v != v or not bool(v):
                    break
                follow += 1
        rows.append({
            "代码": str(bars["vt_symbol"].iat[i]),
            "名称": str(name_map.get(bars["vt_symbol"].iat[i]) or ""),
            "买入日": pd.Timestamp(cols["trade_date"][i]),
            "N": n_board,
            "高度段": seg or f"{n_board}板",
            "断板天数": gap,
            "阴阳": yy,
            "主格": main_cell,
            "六组": group6,
            "末板日": rec["break_end"].isoformat() if rec["break_end"] else None,
            "断板期": rec["break_days"],
            "断板阴线数": int(rec["break_yin_count"]),
            "断板炸板日数": int(rec["break_zha_days"]),
            "断板累计%": rec["break_drop_pct"],
            "坑深%": rec["pit_depth_pct"],
            "末日实体": rec["last_entity"],
            "末日开盘%": rec["last_open_pct"],
            "链": rec["chain"],
            "距MA5%": rec["dist_ma5"],
            "距60日新高%": rec["dist_h60"],
            "均线": rec["ma_state"],
            "方案点": point,
            "死格": contracts.dead_cell_reason(n_board, gap, yy,
                                                int(rec["break_yin_count"]),
                                                rec["break_drop_pct"]) if main_cell else "",
            "买价": buy,
            "封住": sealed,
            "次日开%": round((n1o / buy - 1) * 100, 2) if n1o == n1o else np.nan,
            "次日收%": round((n1c / buy - 1) * 100, 2) if n1c == n1c else np.nan,
            "次日连板": bool(n1lim) if n1lim == n1lim else False,
            "持有到断板%": round((exit_px / buy - 1) * 100, 2) if not unfinished else np.nan,
            "持有天数": hold_days,
            "未完": unfinished,
            "后续板数": follow,
            "退出日": exit_day,
            "退出价": round(float(exit_px), 3) if not unfinished else None,
            "退出原因": exit_reason,
            "坏票": bool(n1c == n1c and n1c < buy),
            "昨日涨停家数": int(cols["mkt_prev"][i]) if cols["mkt_prev"][i] == cols["mkt_prev"][i] else None,
        })
    E = pd.DataFrame(rows)
    E["月"] = E["买入日"].dt.strftime("%Y-%m")
    E["年"] = E["买入日"].dt.strftime("%Y")
    # 研究胜率口径 = 好票率(次日收盘≥买价;炸板但涨回来的算好票)
    E["胜"] = E["次日收%"] >= 0
    return E


# ── 统计与物化 ──

def _stats(e: pd.DataFrame) -> dict[str, object]:
    if not len(e):
        return {"n": 0}
    d1 = e["次日收%"].dropna()
    bw = e["持有到断板%"].dropna()
    sealed = e[e["封住"]]
    return {
        "n": int(len(e)),
        "seal": round(float(e["封住"].mean()), 3),
        "seal_fail": round(float((~e["封住"]).mean()), 3),
        "avg_pct": round(float(d1.mean()), 2) if len(d1) else None,
        "win": round(float((d1 >= 0).mean()), 3) if len(d1) else None,
        "bad": round(float(e["坏票"].mean()), 3),
        "bw_pct": round(float(bw.mean()), 2) if len(bw) else None,
        "bw_median": round(float(bw.median()), 2) if len(bw) else None,
        "bw_win": round(float((bw > 0).mean()), 3) if len(bw) else None,
        "re_limit": round(float(sealed["次日连板"].mean()), 3) if len(sealed) else None,
    }


def _matrix18(main: pd.DataFrame) -> list[dict[str, object]]:
    """18格总表(六组×断1/2/3,复刻基础矩阵表一)。"""
    out: list[dict[str, object]] = []
    for g6 in contracts.GROUP6_KEYS:
        for gap in contracts.GS_MAIN:
            sub = main[(main["六组"] == g6) & (main["断板天数"] == gap)]
            s = _stats(sub)
            follow = sub["后续板数"]
            n = len(sub)
            out.append({
                "group6": g6, "gap": gap, **s,
                "follow0": round(float((follow == 0).mean()), 3) if n else None,
                "follow1": round(float((follow == 1).mean()), 3) if n else None,
                "follow2": round(float((follow == 2).mean()), 3) if n else None,
                "follow3plus": round(float((follow >= 3).mean()), 3) if n else None,
            })
    return out


def _matrix18_yearly(main: pd.DataFrame) -> list[dict[str, object]]:
    """18格分年(持有到断板%/n;复刻基础矩阵表四)。"""
    out: list[dict[str, object]] = []
    for g6 in contracts.GROUP6_KEYS:
        for gap in contracts.GS_MAIN:
            sub = main[(main["六组"] == g6) & (main["断板天数"] == gap)]
            yearly = [{"year": y,
                       "bw_pct": round(float(g_["持有到断板%"].dropna().mean()), 2)
                       if len(g_.dropna(subset=["持有到断板%"])) else None,
                       "n": int(len(g_))}
                      for y, g_ in sub.groupby("年")]
            out.append({"group6": g6, "gap": gap, "n": int(len(sub)), "yearly": yearly})
    return out


def _ref_rows(done: pd.DataFrame) -> list[dict[str, object]]:
    """参考行(3板全系 + 断4~5天;只统计不进池,复刻基础矩阵表三)。"""
    out: list[dict[str, object]] = []
    for n_board, label in ((3, "3板"), (2, "2板"), (4, "4板"), (99, "5+板")):
        for gap in (1, 2, 3, 4, 5):
            if n_board == 3 and gap > 3:
                continue
            if n_board != 3 and gap < 4:
                continue
            if n_board == 99:
                sub = done[(done["N"] >= 5) & (done["断板天数"] == gap)]
            else:
                sub = done[(done["N"] == n_board) & (done["断板天数"] == gap)]
            if not len(sub):
                continue
            s = _stats(sub)
            out.append({"label": f"{label}×断{gap}天", **s})
    return out


def _yin_split(main: pd.DataFrame) -> list[dict[str, object]]:
    """断板期阴线数切分(段合并;复刻基础矩阵表五)。"""
    out: list[dict[str, object]] = []
    for seg, lo, hi in (("2板", 0, 0), ("2板", 1, 1), ("2板", 2, 99),
                        ("4板", 0, 0), ("4板", 1, 1), ("4板", 2, 99),
                        ("5+板", 0, 0), ("5+板", 1, 1), ("5+板", 2, 99)):
        if seg == "5+板":
            sub = main[(main["N"] >= 5) & (main["断板阴线数"].between(lo, hi))]
        else:
            sub = main[(main["高度段"] == seg) & (main["断板阴线数"].between(lo, hi))]
        out.append({"seg": seg, "yin": "0阴" if hi == 0 else ("1阴" if hi == 1 else "2+阴"),
                    **_stats(sub)})
    return out


def _pit_split(main: pd.DataFrame) -> list[dict[str, object]]:
    """坑深切分(断板期最低收盘距末板收盘;复刻基础矩阵表六)。"""
    out: list[dict[str, object]] = []
    for seg in ("2板", "4板", "5+板"):
        base = main[main["N"] >= 5] if seg == "5+板" else main[main["高度段"] == seg]
        pit = base["坑深%"]
        sub = base[(pit >= -3) & pit.notna()]
        out.append({"seg": seg, "pit": "浅坑>-3%", **_stats(sub)})
        sub = base[(pit >= -8) & (pit < -3) & pit.notna()]
        out.append({"seg": seg, "pit": "中坑-3~-8%", **_stats(sub)})
        sub = base[(pit < -8) & pit.notna()]
        out.append({"seg": seg, "pit": "深坑<-8%", **_stats(sub)})
    return out


def _yearly(e: pd.DataFrame) -> list[dict[str, object]]:
    if not len(e):
        return []
    return [{"year": y, **_stats(g_)} for y, g_ in e.groupby("年")]


def _monthly(e: pd.DataFrame) -> list[dict[str, object]]:
    if not len(e):
        return []
    return [{"month": m, **_stats(g_)} for m, g_ in e.groupby("月")]


def _curve(e: pd.DataFrame) -> list[dict[str, object]]:
    """逐笔等权累计收益曲线(每笔固定 1 单位,按入场日汇总后累加,不复利)。"""
    if not len(e):
        return []
    daily = e.dropna(subset=["持有到断板%"]).groupby(
        e["买入日"].dt.date)["持有到断板%"].sum().sort_index()
    cum = daily.cumsum()
    return [{"date": d.isoformat(), "cum_pct": round(float(v), 2)} for d, v in cum.items()]


def _yearly_totals(e: pd.DataFrame) -> list[dict[str, object]]:
    """方案合计的一年总收益(单笔平均/年累计等权/年复利理论上限)。"""
    if not len(e):
        return []
    out = []
    for y, g_ in e.groupby("年"):
        r = g_["持有到断板%"].dropna()
        out.append({"year": y, "n": int(len(g_)),
                    "avg_pct": round(float(r.mean()), 2) if len(r) else None,
                    "sum_pct": round(float(r.sum()), 1),
                    "compound_pct": round(float(((1 + r / 100).prod() - 1) * 100), 1)
                    if len(r) else None})
    return out


def _anchor_check(summary: dict[str, object]) -> dict[str, object]:
    """与研究定稿锚点自校对;容差吸收宇宙/数据口径微差,形态漂移不容忍。"""
    tol = contracts.ANCHOR_TOLERANCES
    out: dict[str, object] = {}
    for key, anchor in contracts.BACKTEST_ANCHORS.items():
        s = summary.get(key) or {}
        n = int(s.get("n", 0) or 0)
        bw = float(s.get("bw_pct", 0.0) or 0.0)
        # 锚点胜率=研究「胜率」列=好票率(次日收%≥0 占比)
        win = float(s.get("win", 0.0) or 0.0)
        n_diff = n - int(anchor["n"])
        bw_diff = round(bw - float(anchor["bw_pct"]), 2)
        win_diff = round(win - float(anchor["bw_win"]), 3)
        passed = (abs(n_diff) <= max(5, int(anchor["n"] * tol["n_pct"]))
                  and abs(bw_diff) <= tol["bw_pct"]
                  and abs(win_diff) <= tol["bw_win"])
        out[key] = {"n_diff": n_diff, "bw_diff": bw_diff, "win_diff": win_diff,
                    "pass": bool(passed)}
    out["note"] = ("锚点=研究定稿数字(单一收益口径+好票率胜率);差异应仅来自宇宙/数据口径"
                   "微差与新增交易日")
    return out


def _matrix_anchor_check(matrix18: list[dict[str, object]]) -> dict[str, object]:
    """18格抽3格锚点(非方案点格)。"""
    out: dict[str, object] = {}
    tol = contracts.ANCHOR_TOLERANCES
    for key, anchor in contracts.MATRIX_ANCHORS.items():
        g6, gap = key.split("|")
        row = next((r for r in matrix18
                    if r.get("group6") == g6 and str(r.get("gap")) == gap), None)
        if row is None:
            out[key] = {"pass": False, "note": "格缺失"}
            continue
        n_diff = int(row.get("n", 0) or 0) - int(anchor["n"])
        bw_diff = round(float(row.get("bw_pct", 0.0) or 0.0) - float(anchor["bw_pct"]), 2)
        win_diff = round(float(row.get("win", 0.0) or 0.0) - float(anchor["bw_win"]), 3)
        passed = (abs(n_diff) <= max(5, int(anchor["n"] * tol["n_pct"]))
                  and abs(bw_diff) <= tol["bw_pct"]
                  and abs(win_diff) <= tol["bw_win"])
        out[key] = {"n_diff": n_diff, "bw_diff": bw_diff, "win_diff": win_diff,
                    "pass": bool(passed)}
    return out


def _case_gates(done: pd.DataFrame) -> list[dict[str, object]]:
    """案例门禁:具名案例买入日的方案点归属与期望比对。"""
    out: list[dict[str, object]] = []
    for case in contracts.CASE_GATES:
        sub = done[(done["名称"] == case["name"])
                   & (done["买入日"] == pd.Timestamp(str(case["date"])))]
        actual = sorted({str(p) for p in sub["方案点"]})
        expect = str(case["expect"])
        if expect == "out_any":
            passed = not actual or actual == ["—"]
        elif expect.startswith("out_"):
            passed = expect[4:] not in actual
        else:  # in_<point>
            passed = expect[3:] in actual
        out.append({"name": case["name"], "date": case["date"], "expect": expect,
                    "actual_points": actual, "pass": bool(passed),
                    "note": case["note"]})
    return out


def _dead_stats(done: pd.DataFrame) -> list[dict[str, object]]:
    """死格清单统计(六组主格内 point='—' 的格;数字证明死格该死)。"""
    out: list[dict[str, object]] = []
    for g6 in contracts.GROUP6_KEYS:
        for gap in contracts.GS_MAIN:
            sub = done[(done["六组"] == g6) & (done["断板天数"] == gap)
                       & (done["方案点"] == "—")]
            if not len(sub):
                continue
            reasons = sorted({str(r) for r in sub["死格"] if r})
            out.append({"group6": g6, "gap": gap, **_stats(sub),
                        "reasons": reasons})
    return out


def _radar_stats(main: pd.DataFrame) -> dict[str, object]:
    """事件全量(触板买入口径) vs 方案点命中笔数。"""
    out: dict[str, object] = {"all": {"trigger_n": int(len(main)),
                                      "hit_n": int((main["方案点"] != "—").sum())}}
    for g6 in contracts.GROUP6_KEYS:
        sub = main[main["六组"] == g6]
        out[g6] = {"trigger_n": int(len(sub)),
                   "hit_n": int((sub["方案点"] != "—").sum())}
    return out


def _ledger_days(trades: pd.DataFrame, touch_map: dict | None = None) -> list[dict[str, object]]:
    """全历史模拟交割单(方案点命中口径,全点合并,不限仓位不限天数;月份筛选由 API 层切片)。

    退出 = 单一卖出纪律:反包日炸板当日收盘走/封住→断板收盘(15日兜底)。
    is_bad = 坏票(次日收盘<买价);result = 炸板|封次日负|封次日正。
    touch: {(vt_symbol, 买入日): 'HH:MM'} 首触板15分钟末刻;无数据=None(2024-08前)。
    """
    touch_map = touch_map or {}
    e = trades.dropna(subset=["持有到断板%"]).copy()
    if not len(e):
        return []
    e["entry_day"] = e["买入日"].dt.date
    out: list[dict[str, object]] = []
    for day, g_ in sorted(e.groupby("entry_day"), key=lambda kv: kv[0], reverse=True):
        items = []
        for _, r in g_.iterrows():
            d1 = r["次日收%"]
            if not bool(r["封住"]):
                result = "炸板"
            elif d1 == d1 and float(d1) < 0:
                result = "封次日负"
            else:
                result = "封次日正"
            items.append({
                "vt_symbol": str(r["代码"]),
                "name": str(r["名称"]),
                "point": str(r["方案点"]),
                "level": contracts.POINT_LEVELS.get(str(r["方案点"]), "—"),
                "group6": str(r["六组"]),
                "gap": int(r["断板天数"]),
                "n_board": int(r["N"]),
                "yin_yang": str(r["阴阳"]),
                "entry_price": _sr(r["买价"], 3),
                "sealed": bool(r["封住"]),
                "streak_h": int(r["后续板数"]) if pd.notna(r["后续板数"]) else 0,
                "exit_date": r["退出日"],
                "exit_price": _sr(r["退出价"], 3),
                "exit_reason": r["退出原因"],
                "ret_pct": _sr(r["持有到断板%"], 2),
                "is_bad": bool(r["坏票"]),
                "result": result,
                "break_drop_pct": _sr(r["断板累计%"], 1),
                "break_yin_count": int(r["断板阴线数"]),
                "pit_depth_pct": _sr(r["坑深%"], 1),
                "last_entity": r["末日实体"],
                "last_open_pct": _sr(r["末日开盘%"], 2),
                "high_var": bool(str(r["方案点"]) == "S2"
                                 and contracts.is_high_var_open(_sr(r["末日开盘%"], 2))),
                "dist_ma5": _sr(r["距MA5%"], 1),
                "touch": touch_map.get((str(r["代码"]), r["entry_day"])),
            })
        rets = [float(t["ret_pct"]) for t in items if t["ret_pct"] is not None]
        out.append({
            "trade_date": day.isoformat(),
            "trades": items,
            "count": len(items),
            "win": sum(1 for r in rets if r > 0),
            "bad": sum(1 for t in items if t["is_bad"]),
            "avg_ret_pct": round(sum(rets) / len(rets), 2) if rets else None,
        })
    return out


def _date_str(value: object) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return pd.Timestamp(value).date().isoformat()  # type: ignore[arg-type]


def _sr(value: object, ndigits: int) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return round(number, ndigits) if math.isfinite(number) else None
