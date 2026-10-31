"""一接二 j12-v2.0 全量回放：严格 +9% 入场 + 纯断板尾盘退出 + 报告物化。

- 判定唯一真源 = contracts.match_points，静态字段与实时池共用 pool.event_fields
- 事件 = 昨日孤立首板 × 当日最高严格过 +9% × 开盘非涨停，不要求之后触板
- 兼容报告字段 E3% 在 v2 中只表示纯 tail 收益，不再使用旧 E3 深开竞价卖
- 旧 _e3_exit 原样保留，仅供既有研究脚本调用
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from alphaagent.server.db.session import get_engine
from alphaagent.server.services.first_relay import contracts, execution, pool as pool_mod, repository

logger = logging.getLogger(__name__)

START_BARS = "2020-06-01"     # 给 2021-01 事件留足 60/120 日回看
START_EVT = pd.Timestamp("2021-01-01")
MAIN_START = pd.Timestamp("2023-01-01")
MAX_K = 15                     # 持有兜底天数(对齐 hpr)


def build_events(
    bars: pd.DataFrame | None = None,
    name_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """全量事件回放；注入 bars 时完全离线，否则只读数据库与股票宇宙。"""
    if bars is None:
        engine = get_engine()
        universe = pool_mod.hpr_pool.load_universe(engine)
        if name_map is None:
            name_map = universe.set_index("vt_symbol")["name"].to_dict()
        bars = pd.read_sql(
            "select vt_symbol, trade_date, open_price, high_price, low_price, close_price, "
            f"volume, turnover_rate from stock_daily_bars where trade_date >= '{START_BARS}'",
            engine, parse_dates=["trade_date"])
        bars = bars[bars["vt_symbol"].isin(set(universe["vt_symbol"]))].copy()

    daily = pool_mod.hpr_pool.derive_daily(bars)
    lim_i = daily["is_lim"].astype("int8")
    daily["lim_cnt60"] = lim_i.groupby(daily["sid"], sort=False)\
        .transform(lambda s: s.rolling(60, min_periods=20).sum()).shift(1)
    daily["max_streak60"] = daily["streak"].groupby(daily["sid"], sort=False)\
        .transform(lambda s: s.rolling(60, min_periods=20).max()).shift(1)

    grouped = daily.groupby("sid", sort=False)
    future: dict[str, pd.Series] = {}
    source_fields = {
        "close": "close_price", "open": "open_price", "high": "high_price",
        "low": "low_price", "is_lim": "is_lim",
    }
    for k in range(1, MAX_K + 1):
        for field, source in source_fields.items():
            future[f"n{k}_{field}"] = grouped[source].shift(-k)
    daily = pd.concat([daily, pd.DataFrame(future, index=daily.index)], axis=1)
    ctx = pool_mod.hpr_pool.make_ctx(daily)

    trigger = daily["prev_close"].map(
        lambda value: execution.trigger_9pct(value) if pd.notna(value) and value > 0 else np.nan)
    event_mask = (
        daily["streak_prev"].eq(1)
        & daily["trade_date"].ge(START_EVT)
        & daily["high_price"].ge(trigger - 1e-9)
        & daily["open_price"].lt(daily["limit_price"] - 1e-9)
    )

    rows: list[dict[str, object]] = []
    seen: set[tuple[str, pd.Timestamp]] = set()
    for i in daily.index[event_mask].to_numpy():
        i = int(i)
        symbol = str(daily["vt_symbol"].iat[i])
        trade_date = pd.Timestamp(daily["trade_date"].iat[i])
        event_key = (symbol, trade_date)
        if event_key in seen:
            continue
        seen.add(event_key)

        prev_close = float(daily["prev_close"].iat[i])
        buy = execution.open9_entry(
            float(daily["open_price"].iat[i]),
            float(daily["high_price"].iat[i]),
            prev_close,
        )
        if buy is None:
            continue
        p1 = i - 1
        fields = pool_mod.event_fields(daily, ctx, p1)
        if fields is None:
            continue

        today_open = round((float(daily["open_price"].iat[i]) / prev_close - 1) * 100, 2)
        fields["today_open"] = today_open
        hits = contracts.match_points(fields, check_gate=True)
        point = hits[0] if hits else "—"
        level = str(contracts.POINTS[point]["level"]) if hits else "—"
        bonus = "同中" + ",".join(hits[1:]) if len(hits) > 1 else None
        sealed = bool(daily["is_lim"].iat[i])

        # E0 只在封住时预扫描首次断板；未封买日由 T+1 尾盘规则直接退出。
        exit_e0, e0_hold_days, e0_exit_idx, capped = np.nan, None, None, False
        if sealed:
            for k in range(1, MAX_K + 1):
                next_close = daily[f"n{k}_close"].iat[i]
                if pd.isna(next_close):
                    break
                if not bool(daily[f"n{k}_is_lim"].iat[i]):
                    exit_e0 = float(next_close)
                    e0_hold_days, e0_exit_idx = k, i + k
                    break
            if pd.isna(exit_e0) and pd.notna(daily[f"n{MAX_K}_close"].iat[i]):
                exit_e0 = float(daily[f"n{MAX_K}_close"].iat[i])
                e0_hold_days, e0_exit_idx, capped = MAX_K, i + MAX_K, True

        tail_price, tail_i, tail_reason = _tail_exit(
            daily, i, sealed, exit_e0, e0_hold_days, e0_exit_idx, capped)
        unfinished = tail_i is None or pd.isna(tail_price)
        tail_exit_date = None
        hold_days = None
        if tail_i is not None:
            tail_exit_date = pd.Timestamp(daily["trade_date"].iat[tail_i]).date().isoformat()
            hold_days = int(tail_i - i)

        def finite_number(key: str) -> float | None:
            value = fields.get(key)
            return float(value) if value is not None and pd.notna(value) else None

        dist_ma20 = finite_number("dist_ma20")
        dist_h60 = finite_number("dist_h60")
        pre10 = finite_number("pre10_pct")
        pre20 = finite_number("pre20_pct")
        turn = finite_number("b1_turn")
        bad_gap = any(
            (value := fields.get(key)) is not None
            and pd.notna(value)
            and abs(float(value)) > 11
            for key in ("today_open", "b1_open", "foundation_chg")
        )
        rows.append({
            "代码": symbol,
            "名称": str((name_map or {}).get(symbol) or ""),
            "买入日": trade_date,
            "段": "主窗" if trade_date >= MAIN_START else "样本外",
            "方案点": point,
            "级别": level,
            "规则IDs": "+".join(hits),
            "回避": None,
            "加分": bonus,
            "地基阴阳": "阳" if fields.get("foundation_yang") else "阴",
            "今开%": today_open,
            "首板换手%": round(turn, 2) if turn is not None else None,
            "距MA20%": round(dist_ma20, 2) if dist_ma20 is not None else None,
            "距60高%": round(dist_h60, 2) if dist_h60 is not None else None,
            "前10日%": round(pre10, 2) if pre10 is not None else None,
            "前20日%": round(pre20, 2) if pre20 is not None else None,
            "买价": buy,
            "触发价": execution.trigger_9pct(prev_close),
            "封住": sealed,
            "触板": bool(daily["touch"].iat[i]),
            "数据异常": bool(bad_gap),
            # v2 兼容字段：E3%/退出日/原因均来自纯 tail，绝不是旧 E3 收益。
            "E3%": round((tail_price / buy - 1) * 100, 2) if not unfinished else np.nan,
            "E3退出日": tail_exit_date,
            "E3原因": tail_reason if not unfinished else None,
            "断板天数": int(e0_hold_days) if sealed and e0_hold_days is not None else None,
            "持有天数": hold_days,
            "持有到断板%": round((exit_e0 / buy - 1) * 100, 2) if pd.notna(exit_e0) else np.nan,
            "未完": unfinished,
        })
    E = pd.DataFrame(rows)
    if len(E):
        E["月"] = E["买入日"].dt.strftime("%Y-%m")
        E["年"] = E["买入日"].dt.strftime("%Y")
    return E


def _tail_exit(daily, i, sealed, exit_e0, hold_days, exit_idx, capped):
    """纯断板尾盘退出：不用D+2深开卖；一字跌停顺延，持续锁死保持未完。"""
    if not sealed:
        return _e3_exit(daily, i, sealed, exit_e0, hold_days, exit_idx, capped)
    if hold_days is None:
        return np.nan, None, None
    reason = "next_close_fail" if hold_days == 1 else (
        "max_hold_close" if capped else "break_close")
    hd0 = int(hold_days)
    previous_close = float(daily[f"n{hd0 - 1}_close"].iat[i]) if hd0 > 1 \
        else float(daily["limit_price"].iat[i])
    day_open = float(daily[f"n{hd0}_open"].iat[i])
    day_high = float(daily[f"n{hd0}_high"].iat[i])
    day_low = float(daily[f"n{hd0}_low"].iat[i])
    if (float(exit_e0) <= previous_close * 0.905 + 0.011
            and day_open == day_high == day_low
            and abs(day_open - float(exit_e0)) <= 0.011):
        previous = float(exit_e0)
        for j in range(hd0 + 1, MAX_K + 1):
            next_open = float(daily[f"n{j}_open"].iat[i])
            if pd.isna(next_open):
                break
            next_high = float(daily[f"n{j}_high"].iat[i])
            next_low = float(daily[f"n{j}_low"].iat[i])
            next_close = float(daily[f"n{j}_close"].iat[i])
            if next_open == next_high == next_low == next_close \
                    and (next_close / previous - 1) <= -0.095:
                previous = next_close
                continue
            return next_open, i + j, "limit_down_defer"
        # 连续一字跌停锁死到最长持有窗仍无法成交：保留未完，不伪造退出价。
        return np.nan, None, None
    return float(exit_e0), exit_idx, reason


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

def _trim3(values: pd.Series) -> float | None:
    """去掉收益最高的三笔后求均值；不超过三笔时不伪造统计量。"""
    if len(values) <= 3:
        return None
    trimmed = values.sort_values(ascending=False).iloc[3:]
    return round(float(trimmed.mean()), 2)


def _empty_agg() -> dict[str, object]:
    return {
        "n": 0, "win": None, "e3": None, "med": None, "worst": None,
        "seal": None, "trim3": None, "by_year": {}, "allpos": False,
    }


def _agg(sub: pd.DataFrame) -> dict[str, object]:
    if "E3%" not in sub:
        return _empty_agg()
    if "未完" in sub:
        done = sub[~sub["未完"].fillna(True).astype(bool)].copy()
    else:
        done = sub.copy()
    done["E3%"] = pd.to_numeric(done["E3%"], errors="coerce")
    done = done[np.isfinite(done["E3%"])]
    if not len(done):
        return _empty_agg()

    by_year: dict[str, dict[str, object]] = {}
    raw_year_means: list[float] = []
    if "年" in done:
        for year, group in done.groupby("年", sort=True):
            mean = float(group["E3%"].mean())
            raw_year_means.append(mean)
            by_year[str(year)] = {
                "n": int(len(group)),
                "e3": round(mean, 2),
                "win": round(float((group["E3%"] > 0).mean() * 100), 1),
                "med": round(float(group["E3%"].median()), 2),
                "sum_pct": round(float(group["E3%"].sum()), 1),
                "trim3": _trim3(group["E3%"]),
            }
    return {
        "n": int(len(done)),
        "win": round(float((done["E3%"] > 0).mean() * 100), 1),
        "e3": round(float(done["E3%"].mean()), 2),
        "med": round(float(done["E3%"].median()), 2),
        "worst": round(float(done["E3%"].min()), 1),
        "seal": round(float(done["封住"].mean() * 100), 1),
        "trim3": _trim3(done["E3%"]),
        "by_year": by_year,
        "allpos": bool(raw_year_means) and all(mean > 0 for mean in raw_year_means),
    }


def assemble_report(E: pd.DataFrame) -> dict[str, object]:
    work = E.copy()
    defaults = {
        "代码": "", "名称": "", "买入日": pd.NaT, "段": "", "方案点": "—",
        "规则IDs": "", "回避": None, "今开%": np.nan, "E3%": np.nan,
        "未完": False, "数据异常": False, "封住": False, "持有天数": np.nan,
        "断板天数": np.nan, "月": "", "年": "",
    }
    for column, default in defaults.items():
        if column not in work:
            work[column] = default

    # 最终账本先清洗：未完、异常及非有限收益均不得进入命中或对照组。
    unfinished = work["未完"].fillna(True).astype(bool)
    bad_data = work["数据异常"].fillna(True).astype(bool)
    cleaned = work[~unfinished & ~bad_data].copy()
    cleaned["E3%"] = pd.to_numeric(cleaned["E3%"], errors="coerce")
    cleaned = cleaned[np.isfinite(cleaned["E3%"])]

    hit_mask = cleaned["方案点"].isin(contracts.POINTS)
    hit = cleaned[hit_mask].drop_duplicates(["代码", "买入日"], keep="first").copy()
    miss = cleaned[~hit_mask].copy()
    main = hit[hit["段"] == "主窗"]
    oos = hit[hit["段"] == "样本外"]

    def by_point(sub: pd.DataFrame) -> dict[str, dict[str, object]]:
        # F1 不能靠字符串前缀匹配，否则会误收 F10；重叠票按成员资格进入多条规则。
        memberships = {
            point: sub["规则IDs"].fillna("").astype(str).map(
                lambda value: point in value.split("+"))
            for point in contracts.POINTS
        }
        return {point: _agg(sub[memberships[point]]) for point in contracts.POINTS}

    def tail_structure(sub: pd.DataFrame) -> dict[str, dict[str, object]]:
        sealed = sub["封住"].fillna(False).astype(bool)
        break_days = pd.to_numeric(sub["断板天数"], errors="coerce")
        groups = {
            "未封": ~sealed,
            "次日断": sealed & break_days.eq(1),
            "连板尾": sealed & break_days.ge(2),
        }
        result = {}
        for label, mask in groups.items():
            stats = _agg(sub[mask])
            result[label] = {
                "n": stats["n"],
                "share": round(float(stats["n"] / len(sub) * 100), 1) if len(sub) else 0.0,
                "win": stats["win"],
                "e3": stats["e3"],
            }
        return result

    months = hit.groupby("月").size()
    ledger_days = []
    for month, sub in hit.groupby("月"):
        ledger_days.append({
            "month": str(month),
            "n": int(len(sub)),
            "win": round(float((sub["E3%"] > 0).mean() * 100), 1),
            "e3": round(float(sub["E3%"].mean()), 2),
            "sum_pct": round(float(sub["E3%"].sum()), 1),
            "worst": round(float(sub["E3%"].min()), 1),
        })

    # 一年的成绩：复利按时间序连乘；固定一份为逐笔相加；trim3 去掉当年最好三笔。
    yearly_totals = []
    for year, sub in hit.groupby("年"):
        seq = sub.sort_values("买入日")["E3%"]
        compound = ((1 + seq / 100).prod() - 1) * 100
        yearly_totals.append({
            "year": str(year), "n": int(len(sub)),
            "avg_pct": round(float(sub["E3%"].mean()), 2),
            "win": round(float((sub["E3%"] > 0).mean() * 100), 1),
            "med": round(float(sub["E3%"].median()), 2),
            "trim3": _trim3(sub["E3%"]),
            "compound_pct": round(float(compound), 1),
            "sum_pct": round(float(sub["E3%"].sum()), 1),
        })

    def _cases(sub, n=5, largest=True):
        ordered = sub.nlargest(n, "E3%") if largest else sub.nsmallest(n, "E3%")
        return [{"date": str(r["买入日"].date()), "name": r["名称"], "point": r["方案点"],
                 "open": r["今开%"], "e3": r["E3%"]} for _, r in ordered.iterrows()]

    return {
        "window": {"start": START_EVT.date().isoformat(),
                   "main_start": MAIN_START.date().isoformat()},
        "total": _agg(hit),
        "main": _agg(main),
        "oos": _agg(oos),
        "by_point": {"main": by_point(main), "oos": by_point(oos), "all": by_point(hit)},
        "miss_control": _agg(miss),
        # 仅为旧 API 保留字段；v2 没有毒格分组。
        "poison": {"n": 0, "e3": None},
        "supply": {"months": int(len(months)),
                   "per_month": round(float(months.mean()), 1) if len(months) else 0.0},
        "yearly_totals": yearly_totals,
        "info_layer": {},
        "tail_structure": {
            "all": tail_structure(hit),
            "main": tail_structure(main),
            "oos": tail_structure(oos),
        },
        "note_binary": "同票同日只计一笔；多规则命中不重复计算，不含额外仓位指令。",
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
