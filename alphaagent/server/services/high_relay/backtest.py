"""高位接力打板回测引擎:日线口径全量回放 + 物化报告。

口径 = 量化因子研究/高位接力/高位接力规则.md v1.3 定稿(2026-09-19),
事件构建逐行对齐研究脚本 relay_research.py build_events:
- 事件 = 昨日收盘恰好 N 连板(N=2/3),当日盘中触涨停价(最高≥涨停价)且非一字全天
  (T字含在内);买价 = 涨停价(=昨收×1.10 四舍五入到分);样本自 2023-01 起
- 打标 = 五方案点(静态字段 + 买入开盘%——回测里竞价已知,与研究打标完全一致)
- 收益主算法(E0/锚点口径) = 持有到首次不再涨停日收盘,15 个交易日兜底;
  胜率 = 次日收盘收益>0(研究「胜」口径);未完(数据末端没走到卖出)不进统计
- 产品卖出纪律(E3) = 买入日没封住→当天收盘走;封住→E0;报告同时给 E3 均值/胜率
- 执行口径(首刻过滤×E3) = 15m 覆盖窗(2024-08-15起)内,首刻=首触时刻桶≤09:45,
  时刻表 = w2s_touch_times(全市场通用,pytdx历史+zt_pool每日增量)
统计口径: avg_pct=次日收%均值;win=次日收%>0占比(=研究胜率);bw_pct=持有到断板均值;
bw_median=中位;e3_pct/e3_win=产品卖出纪律口径;锚点数字=研究定稿。
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine
from alphaagent.server.services.high_relay import contracts, pool as pool_mod, repository

REPLAY_START = pd.Timestamp("2023-01-01")
BARS_START = "2022-06-01"  # 暖机窗口(前波120/h60/ma30 需要的全部历史深度;与研究一致)
MAX_K = 15                 # 前向列深度:n1=入场次日 … n15=兜底出口(研究 15 日口径)


def run_backtest() -> dict[str, object]:
    """全量回放并返回物化 payload(不写库,由调用方持久化)。"""
    E = _build_events()
    done = E[~E["未完"]].copy()

    keys = list(contracts.POINT_KEYS) + ["A级", "all", "miss"]

    def subset(key: str) -> pd.DataFrame:
        if key == "all":
            return done[done["方案点"] != "—"]
        if key == "A级":
            return done[done["方案点"].isin(["A1", "A2"])]
        if key == "miss":
            return done[done["方案点"] == "—"]
        return done[done["方案点"] == key]

    frames = {k: subset(k) for k in keys}
    summary = {k: _stats(frames[k]) for k in keys}
    coverage = {
        "from": _date_str(done["买入日"].min()) if len(done) else None,
        "to": _date_str(done["买入日"].max()) if len(done) else None,
        "months": int(pd.to_datetime(done["买入日"]).dt.to_period("M").nunique())
        if len(done) else 0,
    }
    payload: dict[str, object] = {
        "rules_version": contracts.HPR_RULES_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coverage": coverage,
        "caliber": ("日线口径:昨日恰好2/3连板,当日最高价触涨停价(=昨收×1.10)按涨停价买,"
                    "一字全天不开排除(T字可买);E0=持有到首次断板日收盘(15日兜底,锚点口径),"
                    "E3=炸板当日收盘走/封住→E0(产品卖出纪律);胜率=次日收盘收益>0;"
                    "无滑点,日线未复权。池=昨日2/3连板全量(雷达),出手=五方案点命中。"),
        "group4_labels": contracts.GROUP4_LABELS,
        "point_labels": contracts.POINT_LABELS,
        "point_levels": contracts.POINT_LEVELS,
        "summary": summary,
        "yearly": {k: _yearly(frames[k]) for k in keys},
        "monthly": {k: _monthly(frames[k]) for k in keys},
        "curves": {k: _curve(frames[k]) for k in keys},
        "yearly_totals": _yearly_totals(frames["all"]),
        "execution": _execution_caliber(done),
        "anchors": contracts.BACKTEST_ANCHORS,
        "anchor_tolerances": contracts.ANCHOR_TOLERANCES,
        "anchor_check": _anchor_check(summary),
        "exec_anchor": contracts.EXEC_ANCHOR,
        "case_gates": _case_gates(done),
        "avoid_stats": _avoid_stats(done),
        "radar": _radar_stats(done),
    }
    payload["ledger_days"] = _ledger_days(frames["all"], repository.load_touch_map())
    return payload


# ── 事件池构建(买入日 D 行;静态字段由 pool.static_fields 按行算) ──

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
               schema.stock_daily_bars.c.volume,
               schema.stock_daily_bars.c.turnover_rate)
        .where(schema.stock_daily_bars.c.trade_date >= date.fromisoformat(BARS_START)),
        engine, parse_dates=["trade_date"])
    bars = bars[bars["vt_symbol"].isin(set(universe["vt_symbol"]))].copy()
    bars = pool_mod.derive_daily(bars)
    g = bars.groupby("sid", sort=False)
    for k in range(1, MAX_K + 1):
        bars[f"n{k}_close"] = g["close_price"].shift(-k)
        bars[f"n{k}_open"] = g["open_price"].shift(-k)
        bars[f"n{k}_is_lim"] = g["is_lim"].shift(-k)

    # 事件 = 昨日恰好 2/3 连板 × 当日触板 × 非一字全天(研究 ev_mask 口径)
    ev_mask = (bars["streak_prev"].isin([2, 3]) & bars["touch"]
               & (bars["trade_date"] >= REPLAY_START) & (~bars["one_word"]))
    ev = bars[ev_mask]
    ctx = pool_mod.make_ctx(bars)

    cols = {c: bars[c].to_numpy() for c in
            ["close_price", "open_price", "prev_close", "limit_price", "is_lim",
             "turnover_rate", "vol_rel5", "mkt_lim", "mkt_prev", "trade_date"]}
    rows: list[dict[str, object]] = []
    for i in ev.index.to_numpy():
        i = int(i)
        i_last = i - 1
        n_board = int(bars["streak"].iat[i_last])
        if n_board not in (2, 3):
            continue
        rec = pool_mod.static_fields(ctx, i_last, n_board)
        if rec is None:
            continue
        yang = bool(rec["foundation_yang"])
        group4 = ("二接三" if n_board == 2 else "三接四") + ("阳" if yang else "阴")
        buy = round(float(cols["limit_price"][i]), 2)
        buy_open = round((float(cols["open_price"][i])
                          / float(cols["prev_close"][i]) - 1) * 100, 2)
        point = pool_mod.tag_point(
            group4, rec["dist_h60"], rec["ma_state"], rec["prev_wave60"],
            rec["prev_wave120"], rec.get("b2_open"), rec["turn_grad"],
            rec["dist_ma10"], rec["prior_height"], auction_pct=buy_open)
        avoid = pool_mod.static_avoid(point, group4, rec["dist_h60"],
                                      rec["prev_wave60"],
                                      rec.get("b1_type"), rec.get("b2_type"))
        sealed = bool(cols["is_lim"][i])
        n1c = bars["n1_close"].iat[i]
        n1o = bars["n1_open"].iat[i]
        # E0 持有到断板: 次日(T+1)起首个不再涨停日收盘卖,15 日兜底
        exit_e0, hold_days = np.nan, None
        exit_idx: int | None = None
        capped = False
        for k in range(1, MAX_K + 1):
            v = bars[f"n{k}_is_lim"].iat[i]
            c = bars[f"n{k}_close"].iat[i]
            if c != c:
                break
            if not bool(v):
                exit_e0, hold_days = c, k
                exit_idx = i + k
                break
        if exit_e0 != exit_e0 and bars[f"n{MAX_K}_close"].iat[i] == bars[f"n{MAX_K}_close"].iat[i]:
            exit_e0, hold_days = bars[f"n{MAX_K}_close"].iat[i], MAX_K
            exit_idx = i + MAX_K
            capped = True
        unfinished = exit_e0 != exit_e0
        buy_close = float(cols["close_price"][i])
        # E3: 炸板→当天收盘(break_day_close);封住→E0
        if sealed:
            exit_e3, e3_date, e3_reason = exit_e0, exit_idx, (
                "next_close_fail" if hold_days == 1 else
                ("max_hold_close" if capped else "break_close"))
        else:
            exit_e3, e3_date, e3_reason = buy_close, i, "break_day_close"
        e3_exit_date = None
        if not unfinished and e3_date is not None:
            e3_exit_date = pd.Timestamp(bars["trade_date"].iat[e3_date]).date().isoformat()
        rows.append({
            "代码": str(bars["vt_symbol"].iat[i]),
            "名称": str(name_map.get(bars["vt_symbol"].iat[i]) or ""),
            "买入日": pd.Timestamp(cols["trade_date"][i]),
            "组": "二接三" if n_board == 2 else "三接四",
            "四组": group4,
            "N": n_board,
            "阴阳": "阳" if yang else "阴",
            "方案点": point,
            "回避": avoid,
            "买价": buy,
            "买入开盘%": buy_open,
            "封住": sealed,
            "次日开%": round((n1o / buy - 1) * 100, 2) if n1o == n1o else np.nan,
            "次日收%": round((n1c / buy - 1) * 100, 2) if n1c == n1c else np.nan,
            "持有到断板%": round((exit_e0 / buy - 1) * 100, 2) if not unfinished else np.nan,
            "E3%": round((exit_e3 / buy - 1) * 100, 2) if not unfinished else np.nan,
            "E3退出日": e3_exit_date,
            "E3退出价": round(float(exit_e3), 3) if not unfinished else None,
            "E3原因": e3_reason if not unfinished else None,
            "持有天数": hold_days,
            "未完": unfinished,
            "地基涨跌%": rec["foundation_chg"],
            "距60日新高%": rec["dist_h60"],
            "均线": rec["ma_state"],
            "距MA10%": rec["dist_ma10"],
            "前板高度": rec["prior_height"],
            "前波60日最高板": rec["prev_wave60"],
            "前波120日最高板": rec["prev_wave120"],
            "链": rec["chain"],
            "b1板型": rec.get("b1_type"),
            "b2板型": rec.get("b2_type"),
            "b2开盘%": rec.get("b2_open"),
            "b1换手%": rec.get("b1_turn"),
            "b2换手%": rec.get("b2_turn"),
            "换手梯度": rec["turn_grad"],
            "昨日涨停家数": int(cols["mkt_prev"][i]) if cols["mkt_prev"][i] == cols["mkt_prev"][i] else None,
        })
    E = pd.DataFrame(rows)
    E["月"] = E["买入日"].dt.strftime("%Y-%m")
    E["年"] = E["买入日"].dt.strftime("%Y")
    E["胜"] = E["次日收%"] > 0
    return E


# ── 统计与物化 ──

def _stats(e: pd.DataFrame) -> dict[str, object]:
    if not len(e):
        return {"n": 0}
    d1 = e["次日收%"].dropna()
    bw = e["持有到断板%"].dropna()
    e3 = e["E3%"].dropna()
    return {
        "n": int(len(e)),
        "seal": round(float(e["封住"].mean()), 3),
        "avg_pct": round(float(d1.mean()), 2) if len(d1) else None,
        "win": round(float((d1 > 0).mean()), 3) if len(d1) else None,
        "bw_pct": round(float(bw.mean()), 2) if len(bw) else None,
        "bw_median": round(float(bw.median()), 2) if len(bw) else None,
        "bw_win": round(float((bw > 0).mean()), 3) if len(bw) else None,
        "e3_pct": round(float(e3.mean()), 2) if len(e3) else None,
        "e3_win": round(float((e3 > 0).mean()), 3) if len(e3) else None,
    }


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


def _execution_caliber(done: pd.DataFrame) -> dict[str, object]:
    """执行口径:首刻过滤×E3卖出(15m 覆盖窗内,触板时刻=w2s_touch_times)。"""
    touch_map = repository.load_touch_map()
    hit = done[done["方案点"] != "—"].copy()
    hit["触板"] = [touch_map.get((str(c), pd.Timestamp(d).date()))
                   for c, d in zip(hit["代码"], hit["买入日"], strict=False)]
    hm = hit[hit["触板"].notna()].copy()
    if not len(hm):
        return {"caliber": "15m覆盖窗 2024-08-15 起;无触板时刻数据", "subsets": []}
    hm["首刻"] = hm["触板"] <= "09:45"

    def row(name: str, s: pd.DataFrame) -> dict[str, object]:
        e0 = s["持有到断板%"].dropna()
        e3 = s["E3%"].dropna()
        yearly = [{"year": y, "n": int(len(g_)),
                   "e3_pct": round(float(g_["E3%"].mean()), 2)}
                  for y, g_ in s.groupby("年")]
        return {"name": name, "n": int(len(s)),
                "e0_win": round(float((e0 > 0).mean()), 3) if len(e0) else None,
                "e0_pct": round(float(e0.mean()), 2) if len(e0) else None,
                "e3_pct": round(float(e3.mean()), 2) if len(e3) else None,
                "e3_win": round(float((e3 > 0).mean()), 3) if len(e3) else None,
                "e3_worst": round(float(e3.min()), 1) if len(e3) else None,
                "yearly": yearly}

    return {
        "caliber": ("首刻过滤×E3卖出(15m覆盖窗 2024-08-15起):首刻=首触时刻桶≤09:45;"
                    "E0=持有到断板,E3=炸板当日收盘走/封住→E0"),
        "subsets": [
            row("方案点命中全部", hm),
            row("命中×首刻(v1.3执行口径)", hm[hm["首刻"]]),
            row("命中×非首刻(放弃)", hm[~hm["首刻"]]),
        ],
    }


def _anchor_check(summary: dict[str, object]) -> dict[str, object]:
    """与研究定稿锚点自校对;容差吸收宇宙/数据口径微差,形态漂移不容忍。"""
    tol = contracts.ANCHOR_TOLERANCES
    out: dict[str, object] = {}
    for key, anchor in contracts.BACKTEST_ANCHORS.items():
        s = summary.get(key) or {}
        n = int(s.get("n", 0) or 0)
        bw = float(s.get("bw_pct", 0.0) or 0.0)
        # 锚点胜率=研究「胜率」列=次日收%>0 占比
        win = float(s.get("win", 0.0) or 0.0)
        n_diff = n - int(anchor["n"])
        bw_diff = round(bw - float(anchor["bw_pct"]), 2)
        win_diff = round(win - float(anchor["bw_win"]), 3)
        passed = (abs(n_diff) <= max(5, int(anchor["n"] * tol["n_pct"]))
                  and abs(bw_diff) <= tol["bw_pct"]
                  and abs(win_diff) <= tol["bw_win"])
        out[key] = {"n_diff": n_diff, "bw_diff": bw_diff, "win_diff": win_diff,
                    "pass": bool(passed)}
    out["note"] = "锚点=研究定稿数字(E0持有到断板口径+次日胜率);差异应仅来自宇宙/数据口径微差与新增交易日"
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


def _avoid_stats(done: pd.DataFrame) -> dict[str, object]:
    """静态回避影响(信息项;锚点口径=研究未回避数字,实时执行会回避)。"""
    hit = done[done["方案点"] != "—"]
    out: dict[str, object] = {}
    for p in contracts.POINT_KEYS:
        sub = hit[hit["方案点"] == p]
        av = sub[sub["回避"].astype(bool)]
        out[p] = {"hit_n": int(len(sub)), "avoid_n": int(len(av))}
    out["all"] = {"hit_n": int(len(hit)),
                  "avoid_n": int(len(hit[hit["回避"].astype(bool)]))}
    return out


def _radar_stats(done: pd.DataFrame) -> dict[str, object]:
    """事件全量(触板买入口径) vs 方案点命中笔数。"""
    out: dict[str, object] = {"all": {"trigger_n": int(len(done)),
                                      "hit_n": int((done["方案点"] != "—").sum())}}
    for g4 in contracts.GROUP4_KEYS:
        sub = done[done["四组"] == g4]
        out[g4] = {"trigger_n": int(len(sub)),
                   "hit_n": int((sub["方案点"] != "—").sum())}
    return out


def _ledger_days(trades: pd.DataFrame, touch_map: dict | None = None) -> list[dict[str, object]]:
    """全历史模拟交割单(方案点命中口径,全点合并,不限仓位不限天数;月份筛选由 API 层切片)。

    退出 = 产品卖出纪律(E3):炸板当日收盘走/封住→断板收盘(15日兜底);
    ret_e0 = 研究主算法(持有到断板)收益,对照列。
    touch: {(vt_symbol, 买入日): 'HH:MM'} 首触板15分钟末刻;无数据=None(2024-08前)。
    """
    touch_map = touch_map or {}
    e = trades.dropna(subset=["E3%", "持有到断板%"]).copy()
    if not len(e):
        return []
    e["entry_day"] = e["买入日"].dt.date
    out: list[dict[str, object]] = []
    for day, g_ in sorted(e.groupby("entry_day"), key=lambda kv: kv[0], reverse=True):
        items = [{
            "vt_symbol": str(r["代码"]),
            "name": str(r["名称"]),
            "point": str(r["方案点"]),
            "level": contracts.POINT_LEVELS.get(str(r["方案点"]), "—"),
            "group4": str(r["四组"]),
            "entry_price": _sr(r["买价"], 3),
            "auction_pct": _sr(r["买入开盘%"], 2),
            "sealed": bool(r["封住"]),
            "streak_h": int(r["持有天数"]) if pd.notna(r["持有天数"]) else 0,
            "exit_date": r["E3退出日"],
            "exit_price": _sr(r["E3退出价"], 3),
            "exit_reason": r["E3原因"],
            "ret_pct": _sr(r["E3%"], 2),
            "ret_e0": _sr(r["持有到断板%"], 2),
            "touch": touch_map.get((str(r["代码"]), r["entry_day"])),
        } for _, r in g_.iterrows()]
        rets = [float(t["ret_pct"]) for t in items if t["ret_pct"] is not None]
        out.append({
            "trade_date": day.isoformat(),
            "trades": items,
            "count": len(items),
            "win": sum(1 for r in rets if r > 0),
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
