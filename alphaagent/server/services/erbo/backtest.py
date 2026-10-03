"""二波反包打板回测引擎:日线口径全量回放 + 物化报告。

口径 = erbo-v1.0 定稿(2026-10-01,研究=记忆 erbo-second-wave):
- 事件 = 妖股波段结构(见 pool._struct_ok)× 当日触涨停价(最高≥涨停价)×非一字全天;
  买价=涨停价(=昨收×1.10四舍五入到分);样本自 2023-01 起
- 打档 = 末日开盘 A 平开-2~+2 / B 深低开≤-4;死格(浅低开/高开)留回测参考行不打标
- 收益 = 反包日炸板次日收盘卖(一字跌停四价合一跌≥9.5%顺延首个开板日);
  封住→持有到首次不再涨停日收盘,15日兜底(与 fanbao v2.2 同款 T+1)
- 胜率 = 好票率(次日收盘≥买价)
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine
from alphaagent.server.services.erbo import contracts, pool as pool_mod
from alphaagent.server.services.fanbao import pool as fbb_pool

REPLAY_START = pd.Timestamp("2023-01-01")
BARS_START = "2022-10-01"   # 31日波段+20日均线暖机
MAX_K = 15


def build_events() -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回 (E, bars):E 带 _bar_i/_exit_i 行号(bars 复用于题库切窗,若做)。"""
    engine = get_engine()
    universe = fbb_pool.load_universe(engine)
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
    bars = fbb_pool.derive_daily(bars)
    bars = pool_mod.derive_features(bars)
    g = bars.groupby("sid", sort=False)
    for k in range(1, MAX_K + 1):
        bars[f"n{k}_close"] = g["close_price"].shift(-k)
        bars[f"n{k}_open"] = g["open_price"].shift(-k)
        bars[f"n{k}_high"] = g["high_price"].shift(-k)
        bars[f"n{k}_low"] = g["low_price"].shift(-k)
        bars[f"n{k}_is_lim"] = g["is_lim"].shift(-k)

    struct = pool_mod._struct_ok(bars)
    ev_mask = (bars["touch"] & (~bars["one_word"])
               & (bars["trade_date"] >= REPLAY_START)
               & struct & bars["gain30"].notna() & bars["ma20gap"].notna())
    ev = bars[ev_mask]
    rows: list[dict[str, object]] = []
    for i in ev.index.to_numpy():
        i = int(i)
        last_open = float(bars["last_open"].iat[i]) \
            if bars["last_open"].iat[i] == bars["last_open"].iat[i] else None
        point = contracts.tag_point(last_open)
        buy = round(float(bars["limit_price"].iat[i]), 2)
        sealed = bool(bars["is_lim"].iat[i])
        # T+1 卖出纪律(同 fanbao v2.2)
        exit_px, hold_days = np.nan, None
        exit_idx: int | None = None
        capped = False
        if not sealed:
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
                exit_px, hold_days, exit_idx = kc, k, i + k
                break
        else:
            for k in range(1, MAX_K + 1):
                v = bars[f"n{k}_is_lim"].iat[i]
                c = bars[f"n{k}_close"].iat[i]
                if c != c:
                    break
                if not bool(v):
                    exit_px, hold_days, exit_idx = c, k, i + k
                    break
            if exit_px != exit_px and bars[f"n{MAX_K}_close"].iat[i] == bars[f"n{MAX_K}_close"].iat[i]:
                exit_px, hold_days, exit_idx = bars[f"n{MAX_K}_close"].iat[i], MAX_K, i + MAX_K
                capped = True
        unfinished = exit_px != exit_px
        exit_reason = None
        if not unfinished:
            if not sealed:
                exit_reason = "break_day_close"
            elif hold_days == 1:
                exit_reason = "next_close_fail"
            elif capped:
                exit_reason = "max_hold_close"
            else:
                exit_reason = "break_close"
        n1c = bars["n1_close"].iat[i]
        rows.append({
            "_bar_i": i,
            "_exit_i": exit_idx,
            "代码": str(bars["vt_symbol"].iat[i]),
            "名称": name_map.get(str(bars["vt_symbol"].iat[i]), ""),
            "买入日": pd.Timestamp(bars["trade_date"].iat[i]),
            "断板天数": int(bars["notlim_prev"].iat[i]),
            "波段%": round(float(bars["gain30"].iat[i]) * 100, 1),
            "回调%": round(float(bars["dd"].iat[i]) * 100, 1),
            "MA20距%": round(float(bars["ma20gap"].iat[i]) * 100, 1),
            "涨停次数": int(bars["lim30"].iat[i]) if bars["lim30"].iat[i] == bars["lim30"].iat[i] else None,
            "阴阳": str(bars["yy"].iat[i]),
            "末开%": round(last_open, 1) if last_open is not None else None,
            "反包次数": int(bars["rebreak30"].iat[i])
                        if bars["rebreak30"].iat[i] == bars["rebreak30"].iat[i] else 0,
            "方案点": point,
            "死格": contracts.dead_open_reason(last_open),
            "买价": buy,
            "封住": sealed,
            "次日收%": round((n1c / buy - 1) * 100, 2) if n1c == n1c else np.nan,
            "持有到断板%": round((exit_px / buy - 1) * 100, 2) if not unfinished else np.nan,
            "持有天数": hold_days,
            "未完": unfinished,
            "退出日": pd.Timestamp(bars["trade_date"].iat[exit_idx]).date().isoformat()
                      if exit_idx is not None else None,
            "退出价": round(float(exit_px), 3) if not unfinished else None,
            "退出原因": exit_reason,
            "昨日涨停家数": int(bars["mkt_prev"].iat[i])
                            if bars["mkt_prev"].iat[i] == bars["mkt_prev"].iat[i] else None,
        })
    E = pd.DataFrame(rows)
    E["月"] = E["买入日"].dt.strftime("%Y-%m")
    E["年"] = E["买入日"].dt.strftime("%Y")
    return E, bars


def run_backtest() -> dict[str, object]:
    E, _ = build_events()
    return assemble_report(E)


def assemble_report(E: pd.DataFrame) -> dict[str, object]:
    done = E[~E["未完"]].copy()
    keys = list(contracts.POINT_KEYS) + ["all", "miss"]

    def subset(key: str) -> pd.DataFrame:
        if key == "all":
            return done[done["方案点"] != "—"]
        if key == "miss":
            return done[done["方案点"] == "—"]
        if key == "S4":
            # 精选层 = A/B 档内「断过两回」(叠加标记,不改变 A/B/all 口径)
            return done[(done["方案点"] != "—") & (done["反包次数"] >= contracts.REBREAK_MIN)]
        return done[done["方案点"] == key]

    frames = {k: subset(k) for k in keys}
    summary = {k: _stats(frames[k]) for k in keys}
    payload: dict[str, object] = {
        "rules_version": contracts.ERBO_RULES_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coverage": {
            "from": _date_str(done["买入日"].min()) if len(done) else None,
            "to": _date_str(done["买入日"].max()) if len(done) else None,
            "months": int(done["月"].nunique()) if len(done) else 0,
        },
        "caliber": ("日线口径:30日波段50~80%×深洗8~15%×MA20上方5%×30日涨停≥2×昨阴×断板3~7天"
                    "→当日触涨停价按涨停价买(一字排除,T字可买);末日开盘A平开-2~2/B深低开≤-4;"
                    "收益=炸板次日收盘走(T+1,一字跌停顺延)/封住→断板日收盘(15日兜底);"
                    "胜率=好票率(次日收≥买价);无滑点,日线未复权。"
                    "死格(末日浅低开-4~-2/高开>+2)为标注层;"
                    "断过两回=A/B档内30日内断≥2天再拉≥2次精选层(页面「断过两回」),不改变出手口径。"),
        "point_labels": contracts.POINT_LABELS,
        "point_levels": contracts.POINT_LEVELS,
        "summary": summary,
        "dead_summary": _stats(done[done["死格"] != ""]),
        "yearly": {k: _yearly(frames[k]) for k in keys},
        "monthly": {k: _monthly(frames[k]) for k in keys},
        "ledger_days": _ledger_days(frames["all"]),
        "anchors": contracts.BACKTEST_ANCHORS,
        "anchor_tolerances": contracts.ANCHOR_TOLERANCES,
        "anchor_check": _anchor_check(summary),
        "case_gates": _case_gates(done),
    }
    return payload


def _stats(e: pd.DataFrame) -> dict[str, object]:
    if not len(e):
        return {"n": 0}
    d1 = e["次日收%"].dropna()
    bw = e["持有到断板%"].dropna()
    return {
        "n": int(len(e)),
        "seal": round(float(e["封住"].mean()), 3),
        "seal_fail": round(float((~e["封住"]).mean()), 3),
        "avg_pct": round(float(d1.mean()), 2) if len(d1) else None,
        "win": round(float((d1 >= 0).mean()), 3) if len(d1) else None,   # 好票率
        "bw_pct": round(float(bw.mean()), 2) if len(bw) else None,
        "bw_median": round(float(bw.median()), 2) if len(bw) else None,
        "bw_win": round(float((bw >= 0).mean()), 3) if len(bw) else None,
    }


def _yearly(e: pd.DataFrame) -> list[dict[str, object]]:
    if not len(e):
        return []
    out = []
    for y, sub in e.groupby("年"):
        s = _stats(sub)
        s["year"] = str(y)
        out.append(s)
    return out


def _monthly(e: pd.DataFrame) -> list[dict[str, object]]:
    if not len(e):
        return []
    out = []
    for m, sub in e.groupby("月"):
        out.append({"month": str(m), "n": int(len(sub)),
                    "bw_pct": round(float(sub["持有到断板%"].mean()), 2)})
    return out


def _ledger_days(e: pd.DataFrame) -> list[dict[str, object]]:
    if not len(e):
        return []
    days = []
    for day, sub in e.groupby("买入日"):
        trades = []
        for _, r in sub.iterrows():
            trades.append({
                "vt_symbol": r["代码"], "name": r["名称"],
                "point": r["方案点"], "level": contracts.POINT_LEVELS.get(r["方案点"], "—"),
                "gap": int(r["断板天数"]), "gain30_pct": r["波段%"], "dd_pct": r["回调%"],
                "ma20gap_pct": r["MA20距%"], "lim30": r["涨停次数"],
                "last_open_pct": r["末开%"], "entry_price": r["买价"],
                "reb30": int(r["反包次数"]),
                "s4": bool(r["方案点"] != "—" and int(r["反包次数"]) >= contracts.REBREAK_MIN),
                "sealed": bool(r["封住"]),
                "exit_date": r["退出日"], "exit_price": r["退出价"],
                "exit_reason": r["退出原因"], "ret_pct": r["持有到断板%"],
                "is_bad": bool(r["次日收%"] == r["次日收%"] and r["次日收%"] < 0),
            })
        days.append({"trade_date": day.date().isoformat(), "count": len(sub),
                     "win": sum(1 for t in trades if (t["ret_pct"] or 0) >= 0),
                     "bad": sum(1 for t in trades if t["is_bad"]),
                     "avg_ret_pct": round(float(sub["持有到断板%"].mean()), 2),
                     "trades": trades})
    return days


def _anchor_check(summary: dict[str, object]) -> dict[str, object]:
    tol = contracts.ANCHOR_TOLERANCES
    out: dict[str, object] = {}
    for key, anchor in contracts.BACKTEST_ANCHORS.items():
        s = summary.get(key) or {}
        n = int(s.get("n", 0) or 0)
        bw = float(s.get("bw_pct", 0.0) or 0.0)
        n_diff = n - int(anchor["n"])
        bw_diff = round(bw - float(anchor["bw_pct"]), 2)
        # bw_win 锚点首跑校准(None=跳过,首跑后回填锁死)
        win_ok = True
        if anchor.get("bw_win") is not None:
            win_ok = abs(float(s.get("win", 0) or 0) - float(anchor["bw_win"])) <= tol["bw_win"]
        passed = (abs(n_diff) <= max(3, int(anchor["n"] * tol["n_pct"]))
                  and abs(bw_diff) <= tol["bw_pct"] and win_ok)
        out[key] = {"n_diff": n_diff, "bw_diff": bw_diff, "pass": bool(passed)}
    out["note"] = "锚点=erbo-v1.0 定稿(42笔);bw_win=好票率,首跑校准回填"
    return out


def _case_gates(done: pd.DataFrame) -> list[dict[str, object]]:
    out = []
    for case in contracts.CASE_GATES:
        sub = done[(done["名称"] == case["name"])
                   & (done["买入日"] == pd.Timestamp(str(case["date"])))]
        if not len(sub):
            # 结构外:池结构条件就没满足,天然规则外(out 案例的正常归宿)
            ok = case["expect"] == "out"
            out.append({**case, "actual": "结构外(未入事件集)", "pass": bool(ok)})
            continue
        r = sub.iloc[0]
        if case["expect"] == "in":
            actual, ok = str(r["方案点"]), r["方案点"] != "—"
        elif case["expect"] == "in_dead":
            actual, ok = f"死格:{r['方案点']}", str(r["死格"]) != ""
        else:  # out:在事件集内则必须是死格
            actual, ok = f"{r['方案点']}", r["方案点"] == "—" and str(r["死格"]) != ""
        out.append({**case, "actual": actual, "pass": bool(ok)})
    return out


def _date_str(v) -> str | None:
    return pd.Timestamp(v).date().isoformat() if v is not None else None
