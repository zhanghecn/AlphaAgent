"""U型补涨打板回测引擎:日线口径全量回放 + 物化报告。

口径 = 量化因子研究/低吸研究/U型补涨打板.md 定稿(2026-08-30, commit f6737678):
- 事件 = 信号日(T-1)四组基本条件命中行(触发池全量);出手 = u_shape.actionable_of 白名单
- 买入(D0=T): 最高价触及涨停价(=T-1收盘×1.10) 且 开盘<涨停价(一字买不进排除);
  买价=涨停价(板上买)
- 卖出: 买入次日(T+1)起首个未涨停日收盘卖(板留断走), T+20 兜底;无滑点,日线未复权
- 单一口径: 无竞价过滤/大盘停手/分组触发价(V3 盘中规则属旧研究证据,不带入)
统计口径: avg_pct=D+1(买入次日)收盘收益均值%;win=D+1胜率;bw_pct=板留断走均值%;
bw_win=板留胜率(=研究 r_bh 口径,锚点数字即研究定稿)。
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine
from alphaagent.server.services.a_share_universe import is_eligible_main_board
from alphaagent.server.services.weak_to_strong import contracts, pool as pool_mod
from alphaagent.server.services.weak_to_strong import u_shape

REPLAY_START = pd.Timestamp("2023-04-01")
BARS_START = "2021-01-01"  # 暖机窗口(ma30/mx20/段锚需要的全部历史深度;锚点口径=研究全历史)
MAX_K = contracts.MAX_HOLD_DAYS + 1  # 前向列深度:n1=入场日 … n21=兜底出口


def run_backtest() -> dict[str, object]:
    """全量回放并返回物化 payload(不写库,由调用方持久化)。"""
    T = _build_events()

    trades: dict[str, pd.DataFrame] = {}
    for gk in contracts.GROUP_KEYS:
        trades[gk] = _trades_for(T[T["group_key"] == gk].copy())
    all_t = pd.concat(list(trades.values()), ignore_index=True)

    summary: dict[str, object] = {gk: _stats(trades[gk]) for gk in contracts.GROUP_KEYS}
    summary["all"] = _stats(all_t)
    coverage = {
        "from": _date_str(all_t["entry_date"].min()) if len(all_t) else None,
        "to": _date_str(all_t["entry_date"].max()) if len(all_t) else None,
        "months": int(all_t["entry_date"].dt.to_period("M").nunique()) if len(all_t) else 0,
    }
    keys = list(contracts.GROUP_KEYS) + ["all"]
    frames = {**trades, "all": all_t}

    payload: dict[str, object] = {
        "rules_version": contracts.W2S_RULES_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coverage": coverage,
        "caliber": ("日线口径:买入=信号次日(入场日)最高价触及涨停价(=信号日收盘×1.10)按涨停价买,"
                    "开盘≥涨停价(一字)买不进排除;卖出=买入次日起首个未涨停日收盘(板留断走),"
                    "20个交易日兜底;无滑点,日线未复权。池=触发池全量(雷达),出手=四组白名单。"),
        "group_labels": contracts.GROUP_LABELS,
        "summary": summary,
        "yearly": {k: _yearly(frames[k]) for k in keys},
        "monthly": {k: _monthly(frames[k]) for k in keys},
        "curves": {k: _curve(frames[k]) for k in keys},
        "anchors": contracts.BACKTEST_ANCHORS,
        "anchor_tolerances": contracts.ANCHOR_TOLERANCES,
        "anchor_check": _anchor_check(summary),
        "case_gates": _case_gates(T),
        "radar": {k: _radar_stats(T, k) for k in keys},
    }
    payload["ledger_days"] = _ledger_days(all_t)
    return payload


# ── 事件池构建(信号日 T-1 行;U模型特征由 u_shape 按行算) ──

def _build_events() -> pd.DataFrame:
    engine = get_engine()
    stocks = pd.read_sql(
        select(schema.stocks.c.vt_symbol, schema.stocks.c.name), engine)
    stocks["eligible"] = stocks.apply(
        lambda r: is_eligible_main_board(str(r["vt_symbol"]), str(r["name"])), axis=1)
    main = stocks[stocks["eligible"]]
    name_map = main.set_index("vt_symbol")["name"].to_dict()

    bars = pd.read_sql(
        select(schema.stock_daily_bars.c.vt_symbol,
               schema.stock_daily_bars.c.trade_date,
               schema.stock_daily_bars.c.open_price,
               schema.stock_daily_bars.c.high_price,
               schema.stock_daily_bars.c.low_price,
               schema.stock_daily_bars.c.close_price)
        .where(schema.stock_daily_bars.c.trade_date >= date.fromisoformat(BARS_START)),
        engine, parse_dates=["trade_date"])
    bars = bars[bars["vt_symbol"].isin(set(main["vt_symbol"]))].copy()
    bars = pool_mod.derive_daily(bars)
    bars["gap_days"] = bars.groupby("vt_symbol", sort=False)["trade_date"].diff().dt.days
    g = bars.groupby("vt_symbol", sort=False)
    bars["name"] = bars["vt_symbol"].map(name_map)

    for k in range(1, MAX_K + 1):
        bars[f"n{k}_close"] = g["close_price"].shift(-k)
        bars[f"n{k}_high"] = g["high_price"].shift(-k)
        bars[f"n{k}_low"] = g["low_price"].shift(-k)
        bars[f"n{k}_open"] = g["open_price"].shift(-k)
        bars[f"n{k}_is_lim"] = g["is_lim"].shift(-k)
        bars[f"n{k}_date"] = g["trade_date"].shift(-k)
        bars[f"n{k}_gap"] = g["gap_days"].shift(-k)

    masks = pool_mod.group_masks(bars)
    hit = masks["yin2"] | masks["yang2*"] | masks["yin4"] | masks["yang4"]
    T = bars[(bars["trade_date"] >= REPLAY_START) & hit].copy()
    T = T[T["n1_close"].notna() & T["n1_high"].notna() & (T["n1_gap"] <= 10)].copy()

    # U模型特征(按事件行;候选量≈数千,行循环与研究 build_base 同构;
    # bigtop 锚修正只对 4+组启用——2板组锚就是2板段, 不做大波重算)
    arr_by: dict[str, dict[str, object]] = {}
    for vt, grp in bars.groupby("vt_symbol", sort=False):
        arr_by[str(vt)] = {
            "close": grp["close_price"].to_numpy(dtype=float),
            "high": grp["high_price"].to_numpy(dtype=float),
            "is_lim": grp["is_lim"].to_numpy(dtype=bool),
            "streak": grp["streak"].to_numpy(dtype=float),
        }
    m4 = (masks["yin4"] | masks["yang4"])
    feats: list[dict | None] = []
    for row in T.itertuples():
        arr = arr_by[str(row.vt_symbol)]
        feats.append(u_shape.u_features(arr["close"], arr["high"], arr["is_lim"],
                                        arr["streak"], int(row.pos),
                                        bigtop=bool(m4.loc[row.Index])))
    ok = [f is not None for f in feats]
    T = T[ok].copy()
    feats = [f for f in feats if f is not None]

    def _col(key: str):
        return [f[key] for f in feats]

    T["u_base"] = _col("base")
    T["pos3"] = _col("pos3")
    T["low_dd"] = _col("low_dd")
    T["pull"] = _col("pull")
    T["reb"] = _col("reb")
    T["ma_st"] = _col("ma_st")
    T["n_lim_mid"] = _col("n_lim_mid")
    T["topped"] = _col("topped")
    T["d23ok"] = _col("d23ok")
    T["seg_h"] = _col("seg_h")
    T["gap_d0"] = _col("gap_d0")

    # 五组归属(互斥;yang2 按地基分道)
    gk = pd.Series("", index=T.index, dtype=object)
    m = pool_mod.group_masks(T)  # T 保持 bars 列,直接在事件帧上重算 mask
    gk[m["yin2"].reindex(T.index).fillna(False)] = u_shape.GROUP_YIN2
    gk[m["yin4"].reindex(T.index).fillna(False)] = u_shape.GROUP_YIN4
    gk[m["yang4"].reindex(T.index).fillna(False)] = u_shape.GROUP_YANG4
    yang2 = m["yang2*"].reindex(T.index).fillna(False)
    gk[yang2 & (T["u_base"] == "DN")] = u_shape.GROUP_YANG2A
    gk[yang2 & (T["u_base"] != "DN")] = u_shape.GROUP_YANG2B
    T["group_key"] = gk

    # 白名单出手判定
    T["actionable"] = [u_shape.actionable_of(g, f) for g, f in
                       zip(T["group_key"], (f for f in feats))]

    # 入场可行性(D0=T):触板且非一字
    lim = np.round(T["close_price"] * 1.10 + 1e-9, 2)
    T["lim_px"] = lim
    T["touch"] = T["n1_high"] >= lim - 1e-6
    T["one_word"] = T["n1_open"] >= lim - 1e-6
    T["seal"] = T["n1_is_lim"].fillna(False).astype(bool)
    T["open_g"] = T["n1_open"] / T["close_price"] - 1
    T["n2_lim"] = T["n2_is_lim"].fillna(False).astype(bool)
    return T


# ── 成交回放 ──

def _trades_for(e: pd.DataFrame) -> pd.DataFrame:
    """actionable × 触板 × 非一字 → 板上买入场,板留断走出场。"""
    e = e[e["actionable"] & e["touch"] & ~e["one_word"]].copy()
    if not len(e):
        return e.assign(entry_price=[], entry_date=[], ret_d1=[], ret_bw=[],
                        exit_price_bw=[], exit_date_bw=[], hold_days=[],
                        exit_reason=[], streak_h=[], group=[])
    e["entry_price"] = e["lim_px"]
    e["entry_date"] = e["n1_date"]
    e["ret_d1"] = e["n2_close"] / e["entry_price"] - 1

    exit_px = pd.Series(np.nan, index=e.index)
    exit_dt = pd.Series(pd.NaT, index=e.index)
    hold_days = pd.Series(np.nan, index=e.index)  # 退出日相对信号日的日序(n1=1=入场日)
    reason = pd.Series("open_end", index=e.index, dtype=object)
    for k in range(2, MAX_K + 1):
        lim = e[f"n{k}_is_lim"].fillna(False).astype(bool)
        avail = e[f"n{k}_close"].notna() & e[f"n{k}_date"].notna()
        hit = exit_px.isna() & (~lim) & avail
        exit_px[hit] = e.loc[hit, f"n{k}_close"]
        exit_dt[hit] = e.loc[hit, f"n{k}_date"]
        hold_days[hit] = k
        reason[hit] = "next_close_fail" if k == 2 else "break_close"
    still = exit_px.isna() & e[f"n{MAX_K}_close"].notna() & e[f"n{MAX_K}_date"].notna()
    exit_px[still] = e.loc[still, f"n{MAX_K}_close"]
    exit_dt[still] = e.loc[still, f"n{MAX_K}_date"]
    hold_days[still] = MAX_K
    reason[still] = "max_hold_close"
    e["exit_price_bw"] = exit_px
    e["exit_date_bw"] = exit_dt
    e["hold_days"] = hold_days
    e["ret_bw"] = e["exit_price_bw"] / e["entry_price"] - 1
    e["exit_reason"] = reason
    # 连板高度 = 入场日起连续涨停天数(入场日未封→0)
    e["streak_h"] = (e["hold_days"] - 1 - (~e["seal"]).astype(int)).clip(lower=0)
    e["group"] = e["group_key"]
    return e


# ── 统计与物化 ──

def _stats(e: pd.DataFrame) -> dict[str, object]:
    if not len(e):
        return {"n": 0}
    r = e["ret_d1"].dropna()
    bw = e["ret_bw"].dropna()
    return {
        "n": int(len(e)),
        "seal": round(float(e["seal"].mean()), 3),
        "avg_pct": round(float(r.mean()) * 100, 2) if len(r) else None,
        "win": round(float((r > 0).mean()), 3) if len(r) else None,
        "streak2": round(float(e["n2_lim"].mean()), 3),
        "bw_pct": round(float(bw.mean()) * 100, 2) if len(bw) else None,
        "bw_win": round(float((bw > 0).mean()), 3) if len(bw) else None,
    }


def _radar_stats(T: pd.DataFrame, key: str) -> dict[str, object]:
    """触发池(含未出手)规模参考:不加 actionable/touch 过滤。"""
    sub = T if key == "all" else T[T["group_key"] == key]
    act = sub[sub["actionable"]]
    return {"trigger_n": int(len(sub)), "actionable_n": int(len(act))}


def _yearly(e: pd.DataFrame) -> list[dict[str, object]]:
    if not len(e):
        return []
    year = e["entry_date"].dt.year.astype(str)
    return [{"year": y, **_stats(g_)} for y, g_ in e.groupby(year)]


def _monthly(e: pd.DataFrame) -> list[dict[str, object]]:
    if not len(e):
        return []
    month = e["entry_date"].dt.to_period("M").astype(str)
    return [{"month": m, **_stats(g_)} for m, g_ in e.groupby(month)]


def _curve(e: pd.DataFrame) -> list[dict[str, object]]:
    """逐笔等权累计收益曲线(每笔固定 1 单位,按入场日汇总后累加,不复利)。"""
    if not len(e):
        return []
    daily = e.dropna(subset=["ret_bw"]).groupby(
        e["entry_date"].dt.date)["ret_bw"].sum().sort_index()
    cum = (daily * 100).cumsum()
    return [{"date": d.isoformat(), "cum_pct": round(float(v), 2)} for d, v in cum.items()]


def _anchor_check(summary: dict[str, object]) -> dict[str, object]:
    """与研究定稿锚点自校对;容差吸收宇宙/数据口径微差,形态漂移不容忍。"""
    tol = contracts.ANCHOR_TOLERANCES
    out: dict[str, object] = {}
    for key, anchor in contracts.BACKTEST_ANCHORS.items():
        s = summary.get(key) or {}
        n = int(s.get("n", 0) or 0)
        bw = float(s.get("bw_pct", 0.0) or 0.0)
        bw_win = float(s.get("bw_win", 0.0) or 0.0)
        n_diff = n - int(anchor["n"])
        bw_diff = round(bw - float(anchor["bw_pct"]), 2)
        win_diff = round(bw_win - float(anchor["bw_win"]), 3)
        passed = (abs(n_diff) <= max(5, int(anchor["n"] * tol["n_pct"]))
                  and abs(bw_diff) <= tol["bw_pct"]
                  and abs(win_diff) <= tol["bw_win"])
        out[key] = {"n_diff": n_diff, "bw_diff": bw_diff, "win_diff": win_diff,
                    "pass": bool(passed)}
    out["note"] = "锚点=研究定稿数字(板留口径);差异应仅来自宇宙/数据口径微差与新增交易日"
    return out


def _case_gates(T: pd.DataFrame) -> list[dict[str, object]]:
    """案例门禁:具名案例信号日的「可成交出手组」与期望比对。"""
    fired = T[T["actionable"] & T["touch"] & ~T["one_word"]]
    out: list[dict[str, object]] = []
    for case in contracts.CASE_GATES:
        sub = fired[(fired["name"] == case["name"])
                    & (fired["trade_date"] == pd.Timestamp(str(case["date"])))]
        actual_groups = sorted({str(g_) for g_ in sub["group_key"]})
        expect = str(case["expect"])
        if expect == "out_any":
            passed = not actual_groups
        elif expect.startswith("out_"):
            passed = expect[4:] not in actual_groups
        else:  # in_<gk>
            passed = expect[3:] in actual_groups
        out.append({"name": case["name"], "date": case["date"], "expect": expect,
                    "actual_groups": actual_groups, "pass": bool(passed),
                    "note": case["note"]})
    return out


def _ledger_days(all_trades: pd.DataFrame) -> list[dict[str, object]]:
    """全历史模拟交割单(出手口径,全组合并,不限仓位不限天数;月份筛选由 API 层切片)。"""
    e = all_trades.dropna(subset=["ret_bw", "exit_date_bw"]).copy()
    if not len(e):
        return []
    e["entry_day"] = e["entry_date"].dt.date
    out: list[dict[str, object]] = []
    for day, g_ in sorted(e.groupby("entry_day"), key=lambda kv: kv[0], reverse=True):
        items = [{
            "vt_symbol": str(r.vt_symbol),
            "name": str(r.name),
            "group": str(r.group),
            "group_label": contracts.GROUP_LABELS.get(str(r.group), ""),
            "entry_price": _sr(r.entry_price, 3),
            "gap_open_pct": _sr(float(r.open_g) * 100 if pd.notna(r.open_g) else None, 2),
            "sealed": bool(r.seal),
            "streak_h": int(r.streak_h) if pd.notna(r.streak_h) else 0,
            "exit_date": pd.Timestamp(r.exit_date_bw).date().isoformat(),
            "exit_price": _sr(r.exit_price_bw, 3),
            "exit_reason": str(r.exit_reason),
            "ret_pct": _sr(float(r.ret_bw) * 100, 2),
        } for r in g_.itertuples()]
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
