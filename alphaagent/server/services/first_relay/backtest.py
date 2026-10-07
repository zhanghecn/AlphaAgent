"""一接二全量回放:事件构建(2021-01 起) + E3 退出(v6.7 逐行取自 hpr) + 报告物化。

- 判定唯一真源 = pool.tag_point(实时/回测同函数, 零漂移)
- 事件 = 昨日恰好 1 板 × 当日触板 × 非一字; 主板非ST; 涨停=昨收×1.10四舍五入
- E3 算法逐行取自产品 high_relay/backtest.py(v6.4 D+2 深开竞价卖 + v6.7 跌停口径)
- 报告 = 全段(2021-01~今) + 主窗(2023-01起)/样本外(2021-2022)分段成绩卡
  + 分年 + 按月 + 毒格/未命中对照 + 信息层分解
"""
from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from alphaagent.server.db.session import get_engine
from alphaagent.server.services.first_relay import contracts, pool as pool_mod, repository

logger = logging.getLogger(__name__)

START_BARS = "2020-06-01"     # 给 2021-01 事件留足 60/120 日回看
START_EVT = pd.Timestamp("2021-01-01")
MAIN_START = pd.Timestamp("2023-01-01")
MAX_K = 15                     # 持有兜底天数(对齐 hpr)


def build_events() -> pd.DataFrame:
    """全量事件回放;返回逐笔明细 E(含判定/收益/分段)。"""
    engine = get_engine()
    universe = pool_mod.hpr_pool.load_universe(engine)
    name_map = universe.set_index("vt_symbol")["name"].to_dict()

    bars = pd.read_sql(
        "select vt_symbol, trade_date, open_price, high_price, low_price, close_price, "
        f"volume, turnover_rate from stock_daily_bars where trade_date >= '{START_BARS}'",
        engine, parse_dates=["trade_date"])
    bars = bars[bars["vt_symbol"].isin(set(universe["vt_symbol"]))].copy()
    bars = pool_mod.hpr_pool.derive_daily(bars)
    lim_i = bars["is_lim"].astype("int8")
    bars["lim_cnt60"] = lim_i.groupby(bars["sid"], sort=False)\
        .transform(lambda s: s.rolling(60, min_periods=20).sum()).shift(1)
    bars["max_streak60"] = bars["streak"].groupby(bars["sid"], sort=False)\
        .transform(lambda s: s.rolling(60, min_periods=20).max()).shift(1)
    gc = bars.groupby("sid", sort=False)["close_price"]
    bars["c10"] = gc.shift(10)
    bars["c20"] = gc.shift(20)
    g = bars.groupby("sid", sort=False)
    for k in range(1, MAX_K + 1):
        bars[f"n{k}_close"] = g["close_price"].shift(-k)
        bars[f"n{k}_open"] = g["open_price"].shift(-k)
        bars[f"n{k}_high"] = g["high_price"].shift(-k)
        bars[f"n{k}_low"] = g["low_price"].shift(-k)
        bars[f"n{k}_is_lim"] = g["is_lim"].shift(-k)

    # 二板开盘即一字(开盘=涨停价, 含盘中砸开的T字)不参与: 买不进/接炸板(主人2026-10-06拍板)
    open_ow = (bars["open_price"] - bars["limit_price"]).abs() <= 1e-6
    ev_mask = (bars["streak_prev"] == 1) & bars["touch"] & \
              (bars["trade_date"] >= START_EVT) & (~bars["one_word"]) & (~open_ow)
    ev = bars[ev_mask]

    cols = {c: bars[c].to_numpy() for c in
            ["vt_symbol", "trade_date", "close_price", "open_price", "prev_close",
             "limit_price", "is_lim", "turnover_rate", "ma20", "h60", "c10", "c20",
             "pos"]}
    rows: list[dict[str, object]] = []
    for i in ev.index.to_numpy():
        i = int(i)
        p1, p2, p3 = i - 1, i - 2, i - 3      # 首板日 / 地基日 / 地基前一日
        if cols["pos"][p1] < 2:
            continue
        vsym = str(bars["vt_symbol"].iat[i])
        buy = round(float(cols["limit_price"][i]), 2)
        # 竞价涨幅四舍五入两位再判窗(与研究/问财显示口径一致, 避免边缘丝差)
        buy_open = round((float(cols["open_price"][i]) / float(cols["prev_close"][i]) - 1) * 100, 2)
        sealed = bool(cols["is_lim"][i])

        # 判定字段(与 pool.compute_pool 同口径)
        f2c = float(cols["close_price"][p2])
        f3c = float(cols["close_price"][p3])
        f2_h60 = cols["h60"][p2]
        f2_ma20 = cols["ma20"][p2]
        dist_h60 = (f2c / f2_h60 - 1) * 100 if f2_h60 == f2_h60 else None
        dist_ma20 = (f2c / f2_ma20 - 1) * 100 if f2_ma20 == f2_ma20 else None
        pre10 = (f2c / cols["c10"][p2] - 1) * 100 if cols["c10"][p2] == cols["c10"][p2] else None
        pre20 = (f2c / cols["c20"][p2] - 1) * 100 if cols["c20"][p2] == cols["c20"][p2] else None
        f_yang = bool(f2c >= float(cols["open_price"][p2]))
        f_chg = (f2c / f3c - 1) * 100 if f3c == f3c else None
        turn = float(cols["turnover_rate"][p1])
        point, level, avoid, gate, _actionable = pool_mod.tag_point(
            f_yang, dist_h60, pre10, pre20)
        p1_open_pct = (float(cols["open_price"][p1]) / f2c - 1) * 100 if f2c == f2c else None
        bonus = pool_mod.bonus_tags(turn if turn == turn else None, pre20, p1_open_pct)
        # 竞价复核(回放口径直接判, 实时端由扫描判): 今开 ≥9.5=顶格毒;
        # 不在 gate 窗 = no_trigger(池命中但今开不配合, 不出手)
        if point in ("G1", "S1"):
            lo, hi = contracts.POINTS[point]["gate"]  # type: ignore[assignment]
            if buy_open >= 9.5:
                avoid = contracts.AVOID_AUCTION_CAP
                point, level, gate = "—", "—", None
            elif not (lo <= buy_open < hi):
                point, level, gate = "—", "—", None

        # E0 持有到断板(15 日兜底)
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
            _e3_exit(bars, i, sealed, exit_e0, hold_days, exit_idx, capped)

        e3_exit_date = None
        if not unfinished and e3_i is not None:
            e3_exit_date = pd.Timestamp(bars["trade_date"].iat[e3_i]).date().isoformat()
        rows.append({
            "代码": vsym,
            "名称": str(name_map.get(vsym) or ""),
            "买入日": pd.Timestamp(cols["trade_date"][i]),
            "段": "主窗" if cols["trade_date"][i] >= MAIN_START else "样本外",
            "方案点": point if avoid is None else "—",
            "级别": level if avoid is None else "—",
            "回避": avoid,
            "加分": bonus,
            "地基阴阳": "阳" if f_yang else "阴",
            "今开%": round(buy_open, 2),
            "首板换手%": round(turn, 2) if turn is not None and turn == turn else None,
            "距MA20%": round(dist_ma20, 2) if dist_ma20 is not None and dist_ma20 == dist_ma20 else None,
            "距60高%": round(dist_h60, 2) if dist_h60 is not None and dist_h60 == dist_h60 else None,
            "前10日%": round(pre10, 2) if pre10 is not None and pre10 == pre10 else None,
            "前20日%": round(pre20, 2) if pre20 is not None and pre20 == pre20 else None,
            "买价": buy,
            "封住": sealed,
            "E3%": round((exit_e3 / buy - 1) * 100, 2) if not unfinished else np.nan,
            "E3退出日": e3_exit_date,
            "E3原因": e3_reason if not unfinished else None,
            "持有天数": hold_days,
            "持有到断板%": round((exit_e0 / buy - 1) * 100, 2) if not unfinished else np.nan,
            "未完": unfinished,
        })
    E = pd.DataFrame(rows)
    if len(E):
        E["月"] = E["买入日"].dt.strftime("%Y-%m")
        E["年"] = E["买入日"].dt.strftime("%Y")
    return E


def _e3_exit(bars, i, sealed, exit_e0, hold_days, exit_idx, capped):
    """E3 退出(逐行取自 hpr backtest.py, v6.4+v6.7 口径注释见原文)。"""
    if sealed:
        d2o = bars["n2_open"].iat[i]
        d1c = bars["n1_close"].iat[i]
        if (hold_days is not None and hold_days >= 2 and d2o == d2o
                and d1c == d1c and (d2o / d1c - 1) <= -0.05):
            return float(d2o), i + 2, "d2_deep_open_sell"
        if hold_days is None:
            return np.nan, None, None
        exit_e3, e3_date, e3_reason = float(exit_e0), exit_idx, (
            "next_close_fail" if hold_days == 1 else ("max_hold_close" if capped else "break_close"))
        hd0 = int(hold_days)
        prev0 = (float(bars[f"n{hd0 - 1}_close"].iat[i]) if hd0 > 1
                 else float(bars["limit_price"].iat[i]))
        k0o = float(bars[f"n{hd0}_open"].iat[i])
        k0h = float(bars[f"n{hd0}_high"].iat[i])
        k0l = float(bars[f"n{hd0}_low"].iat[i])
        if (float(exit_e0) <= prev0 * 0.905 + 0.011 and k0o == k0h and k0h == k0l
                and abs(k0o - float(exit_e0)) <= 0.011):
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


# ── 统计与物化 ──

def _agg(sub: pd.DataFrame) -> dict[str, object]:
    done = sub[~sub["未完"]]
    if not len(done):
        return {"n": 0}
    yr = done.groupby("年")["E3%"].agg(["count", "mean"])
    yr_med = done.groupby("年")["E3%"].median()
    return {
        "n": int(len(done)),
        "win": round(float((done["E3%"] > 0).mean() * 100), 1),
        "e3": round(float(done["E3%"].mean()), 2),
        "med": round(float(done["E3%"].median()), 2),
        "worst": round(float(done["E3%"].min()), 1),
        "seal": round(float(done["封住"].mean() * 100), 1),
        "by_year": {str(y): {"n": int(r["count"]), "e3": round(float(r["mean"]), 2),
                             "win": round(float((done[done["年"] == y]["E3%"] > 0).mean() * 100), 1),
                             "med": round(float(yr_med[y]), 2),
                             "sum_pct": round(float(done[done["年"] == y]["E3%"].sum()), 1)}
                    for y, r in yr.iterrows()},
        "allpos": bool(all(yr["mean"] > 0)),
    }


def assemble_report(E: pd.DataFrame) -> dict[str, object]:
    done = E[~E["未完"]]
    hit = done[done["方案点"].isin(["G1", "S1"])]
    main = hit[hit["段"] == "主窗"]
    oos = hit[hit["段"] == "样本外"]

    def by_point(sub):
        return {p: _agg(sub[sub["方案点"] == p]) for p in ("G1", "S1")}

    # 对照: 未命中(非毒)与毒格
    miss = done[(done["方案点"] == "—") & (done["回避"].isna())]
    poison = done[done["回避"].notna()]
    months = hit.groupby("月").size()
    # 信息层分解(主窗命中票)
    g1m = main[main["方案点"] == "G1"]
    info = {}
    for tag, m in [("锁板(换手<8)", g1m["加分"].str.contains("锁板", na=False)),
                   ("动量深坑(前20日<-5)", g1m["加分"].str.contains("动量深坑", na=False)),
                   ("秒板(首板开≥5)", g1m["加分"].str.contains("秒板", na=False))]:
        s = g1m[m]
        if len(s):
            info[tag] = {"n": int(len(s)), "win": round(float((s["E3%"] > 0).mean() * 100), 1),
                         "e3": round(float(s["E3%"].mean()), 2)}
    # 月度交割
    ledger_days = []
    for m, sub in hit.groupby("月"):
        ledger_days.append({
            "month": str(m),
            "n": int(len(sub)),
            "win": round(float((sub["E3%"] > 0).mean() * 100), 1) if len(sub) else None,
            "e3": round(float(sub["E3%"].mean()), 2) if len(sub) else None,
            "sum_pct": round(float(sub["E3%"].sum()), 1) if len(sub) else None,
            "worst": round(float(sub["E3%"].min()), 1) if len(sub) else None,
        })
    # 一年的成绩(hpr 同款口径): 复利=按时间序连乘(每笔全仓押一票); 固定1份=相加
    yearly_totals = []
    for y, sub in hit.groupby("年"):
        seq = sub.sort_values("买入日")["E3%"]
        compound = ((1 + seq / 100).prod() - 1) * 100
        yearly_totals.append({
            "year": str(y), "n": int(len(sub)),
            "avg_pct": round(float(sub["E3%"].mean()), 2),
            "win": round(float((sub["E3%"] > 0).mean() * 100), 1),
            "med": round(float(sub["E3%"].median()), 2),
            "compound_pct": round(float(compound), 1),
            "sum_pct": round(float(sub["E3%"].sum()), 1),
        })
    # 最好/最差案例
    def _cases(sub, n=5, largest=True):
        s = sub.nlargest(n, "E3%") if largest else sub.nsmallest(n, "E3%")
        return [{"date": str(r["买入日"].date()), "name": r["名称"], "point": r["方案点"],
                 "open": r["今开%"], "e3": r["E3%"]} for _, r in s.iterrows()]

    return {
        "window": {"start": START_EVT.date().isoformat(),
                   "main_start": MAIN_START.date().isoformat()},
        "total": _agg(hit),
        "main": _agg(main),
        "oos": _agg(oos),
        "by_point": {"main": by_point(main), "oos": by_point(oos), "all": by_point(hit)},
        "miss_control": _agg(miss),
        "poison": {"n": int(len(poison)),
                   "e3": round(float(poison["E3%"].mean()), 2) if len(poison) else None},
        "supply": {"months": int(len(months)), "per_month": round(float(months.mean()), 1)},
        "yearly_totals": yearly_totals,
        "info_layer": info,
        "note_binary": "仓位二值化:命中且非毒格=满仓打;死水/贴顶/顶格=空仓。",
        "ledger_days": ledger_days,
        "best": _cases(main),
        "worst": _cases(main, largest=False),
        "rules_version": contracts.J12_RULES_VERSION,
    }


def run_backtest_sync(source: str = "scheduler") -> dict[str, object]:
    """全量重算并物化报告(CLI/调度/手动共用;线程内直接跑)。"""
    E = build_events()
    report = assemble_report(E)
    repository.save_backtest_report(contracts.J12_RULES_VERSION, report)
    total = report["total"]
    logger.info("j12 backtest(%s): %s笔 胜%s%% 均%s (主窗%s/样本外%s)",
                source, total.get("n"), total.get("win"), total.get("e3"),
                report["main"].get("n"), report["oos"].get("n"))
    return {"status": "ok", "trades": int(total.get("n") or 0),
            "rules_version": contracts.J12_RULES_VERSION,
            "summary": {k: total.get(k) for k in ("n", "win", "e3", "allpos")}}
