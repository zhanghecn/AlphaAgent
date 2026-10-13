"""差月份解剖: 2026-04~07 连板宇宙反查 + 好差票三维对比 + 口径/排序/条件反事实.

背景: 产品回测页 2026-05/06/07 全信号月度为负(-0.51/-0.86/-0.88),
三槽模拟仓 2026-02~07 连亏六个月(-10/-4/-5/-12/-5/-16%).
用户质问: 5/6 月行情好、7 月妖股多, 为什么还亏? 研究是否虚假?

输出:
U  月度宇宙表: 全市场连板(首板→streak>=2)按板块计数; 主板非ST赢家中池子抓到/漏掉
U2 漏网赢家逐条件失败计数(哪条条件挡赢家) + 特征
T  妖股明细: 2026-04~07 最高 streak 前 15 名(板块归属)
F  三维特征对比(2026-04~07): 池内连板赢家 vs 池内未连板 vs 池外漏网赢家 + 好月对照
C  口径拆解: 月度 全信号 vs 剔高开>=8% vs gap2~6%
M  分钟口径: 2026-06/07 池内信号 日线口径 vs 分钟收住可执行口径
S  排序诊断: 每日前3(优先级)吃到的票 vs 全信号月均
X  条件反事实: 2026-04~07 窗口 + 全样本训/验, 逐条放松
"""
from __future__ import annotations

import os, json, sys
import pandas as pd
import numpy as np
import psycopg

sys.path.insert(0, "/app")
from alphaagent.server.services.a_share_universe import is_eligible_main_board  # noqa: E402

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
SLIP = 0.005
TRAIN_END = pd.Timestamp("2025-07-01")


def main():
    with psycopg.connect(DSN) as conn:
        stocks = pd.read_sql("SELECT vt_symbol, symbol, name, market_cap FROM stocks", conn)
        bars = pd.read_sql(
            """SELECT vt_symbol, trade_date, open_price, close_price, high_price,
                      low_price, volume, turnover_rate, change_pct
               FROM stock_daily_bars WHERE trade_date >= '2022-01-01'""", conn)
        lu = pd.read_sql(
            """SELECT vt_symbol, trade_date, is_limit_up, limit_up_count, is_one_word, touched_limit
               FROM stock_limit_up_daily""", conn)

    stocks["board"] = np.where(
        stocks["symbol"].str.startswith(("300", "301")), "cyb",
        np.where(stocks["symbol"].str.startswith(("688", "689")), "kcb",
                 np.where(stocks["symbol"].str.startswith(("8", "4", "92")), "bse", "main")))
    stocks["is_st"] = stocks["name"].str.upper().str.contains("ST")
    board_map = stocks.set_index("vt_symbol")["board"].to_dict()
    name_map = stocks.set_index("vt_symbol")["name"].to_dict()
    st_map = stocks.set_index("vt_symbol")["is_st"].to_dict()
    stocks["eligible"] = stocks.apply(
        lambda r: is_eligible_main_board(str(r["vt_symbol"]), str(r["name"])), axis=1)
    main_syms = set(stocks.loc[stocks["eligible"], "vt_symbol"])
    cap_map = (stocks.set_index("vt_symbol")["market_cap"] / 1e8).to_dict()

    # ── 连板宇宙(全板块, 只用 lu 表) ───────────────────────────────
    lu = lu.copy()
    lu["trade_date"] = pd.to_datetime(lu["trade_date"])
    lu["board"] = lu.vt_symbol.map(board_map)
    lu_all = lu[lu.is_limit_up].sort_values(["vt_symbol", "trade_date"]).copy()
    lu_all["gap"] = lu_all.groupby("vt_symbol")["trade_date"].diff().dt.days
    lu_all["new_seg"] = (lu_all["gap"].isna()) | (lu_all["gap"] > 7) | (lu_all["limit_up_count"] == 1)
    lu_all["seg"] = lu_all.groupby("vt_symbol")["new_seg"].cumsum()
    segmax = lu_all.groupby(["vt_symbol", "seg"])["limit_up_count"].max().rename("streak_h")
    lu_all = lu_all.join(segmax, on=["vt_symbol", "seg"])
    firsts = lu_all[lu_all.limit_up_count == 1].copy()
    firsts["month"] = firsts.trade_date.dt.to_period("M").astype(str)
    firsts["name"] = firsts.vt_symbol.map(name_map)
    firsts["is_st"] = firsts.vt_symbol.map(st_map).fillna(False)
    winners = firsts[firsts.streak_h >= 2].copy()

    # ── 主板 bars 管线(口径 = 产品: change_pct 推导回填) ────────────
    bars = bars[bars.vt_symbol.isin(main_syms)].copy()
    bars["trade_date"] = pd.to_datetime(bars["trade_date"])
    bars.sort_values(["vt_symbol", "trade_date"], inplace=True)
    g = bars.groupby("vt_symbol", sort=False)
    derived_chg = g["close_price"].transform(lambda s: (s / s.shift(1) - 1) * 100)
    bars["change_pct"] = bars["change_pct"].fillna(derived_chg)
    lu_m = lu[lu.vt_symbol.isin(main_syms)]
    lu_key = lu_m.set_index(["vt_symbol", "trade_date"])
    bars["ma20"] = g["close_price"].transform(lambda s: s.rolling(20).mean())
    bars["ret5"] = g["close_price"].transform(lambda s: s / s.shift(5) - 1)
    bars["ret60"] = g["close_price"].transform(lambda s: s / s.shift(60) - 1)
    bars["open_p1"] = g["open_price"].shift(-1)
    bars["close_p1"] = g["close_price"].shift(-1)
    for k in (2, 3, 4, 5, 6):
        bars[f"open_p{k}"] = g["open_price"].shift(-k)
        bars[f"close_p{k}"] = g["close_price"].shift(-k)
    for col in ["close_price", "low_price", "turnover_rate", "change_pct", "ma20", "ret5", "ret60"]:
        bars[col + "_tm1"] = g[col].shift(1)
    idx = pd.MultiIndex.from_frame(bars[["vt_symbol", "trade_date"]])
    bars["lu_T"] = idx.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    tm1_date = g["trade_date"].shift(1)
    idx_tm1 = pd.MultiIndex.from_arrays([bars["vt_symbol"], tm1_date])
    bars["lu_tm1"] = idx_tm1.map(lu_key["is_limit_up"]).fillna(False).astype(bool).values
    bars["lu_cnt20"] = bars.groupby("vt_symbol")["lu_T"].transform(
        lambda s: s.shift(1).rolling(20, min_periods=1).sum())
    bars["lu_cnt60"] = bars.groupby("vt_symbol")["lu_T"].transform(
        lambda s: s.shift(1).rolling(60, min_periods=1).sum())
    first_m = (lu_all[lu_all.vt_symbol.isin(main_syms) & (lu_all.limit_up_count == 1)]
               [["vt_symbol", "trade_date", "streak_h"]].set_index(["vt_symbol", "trade_date"]))
    bars = bars.join(first_m, on=["vt_symbol", "trade_date"])

    bars["trigger_price"] = bars["close_price_tm1"] * 1.08
    bars["triggered"] = bars["high_price"] >= bars["trigger_price"] - 1e-9
    bars["entry"] = np.where(bars["open_price"] > bars["trigger_price"],
                             bars["open_price"], bars["trigger_price"]) * (1 + SLIP)
    bars["sealed"] = bars["lu_T"]
    bars["cap_yi"] = bars.vt_symbol.map(cap_map)
    bars["gap_open"] = bars["open_price"] / bars["close_price_tm1"] - 1
    bars["dist_ma20"] = bars["close_price_tm1"] / bars["ma20_tm1"] - 1
    limit_px = (bars["close_price_tm1"] * 1.1 + 1e-9).round(2)
    bars["oneword_strict"] = bars["low_price"] >= limit_px * 0.999

    conds = {
        "昨日未涨停": ~bars["lu_tm1"],
        "昨涨0~5%": bars["change_pct_tm1"].between(0, 5),
        "昨低>MA20": bars["low_price_tm1"] > bars["ma20_tm1"],
        "距MA20<=12%": bars["dist_ma20"] <= 0.12,
        "换手<8%": bars["turnover_rate_tm1"] < 8,
        "市值<1200亿": bars["cap_yi"] < 1200,
        "股价<12": bars["close_price_tm1"] < 12,
    }
    pool_mask = np.logical_and.reduce(list(conds.values()))

    def simulate(frame):
        ev = frame[frame["triggered"] & ~frame["oneword_strict"]].copy()
        if not len(ev):
            return ev
        k = ev["streak_h"].fillna(0).astype(int).clip(0, 6)
        eo = np.full(len(ev), np.nan)
        for kk in range(2, 7):
            eo = np.where((k == kk).values, ev[f"open_p{kk}"].values, eo)
        eo = np.where(~ev["sealed"] | (k < 2), ev["open_p1"].values, eo)
        ev["ret"] = pd.Series(eo / ev["entry"].values - 1, index=ev.index)
        disc = (ev["open_p1"] / ev["close_price"] - 1).abs() > 0.11
        for kk in range(2, 7):
            disc |= (pd.Series(ev[f"open_p{kk}"].values / ev[f"close_p{kk-1}"].values - 1,
                               index=ev.index).abs() > 0.11)
        return ev[~disc.fillna(False)].dropna(subset=["ret"])

    ev_all = simulate(bars[(bars.trade_date >= "2023-01-01") & pool_mask])
    ev_all["month"] = ev_all.trade_date.dt.to_period("M").astype(str)
    ev_all["name"] = ev_all.vt_symbol.map(name_map)

    out = {"自检_全信号n": len(ev_all), "自检_锚点n": 6351}

    caught_keys = set(zip(ev_all.loc[ev_all.streak_h.fillna(0) >= 2, "vt_symbol"],
                          ev_all.loc[ev_all.streak_h.fillna(0) >= 2, "trade_date"]))

    # ── U: 月度宇宙表 ─────────────────────────────────────────────
    w = winners[winners.trade_date >= "2025-10-01"].copy()
    w["caught"] = [(s, d) in caught_keys for s, d in zip(w.vt_symbol, w.trade_date)]
    rows = []
    for mth, sub in w.groupby("month"):
        mw = sub[(sub.board == "main") & (~sub.is_st)]
        rows.append({
            "month": mth, "连板总数": len(sub),
            "主板非ST": len(mw), "创业板": int((sub.board == "cyb").sum()),
            "科创板": int((sub.board == "kcb").sum()), "北交": int((sub.board == "bse").sum()),
            "全场最高板": int(sub.streak_h.max()),
            "主板非ST最高": int(mw.streak_h.max()) if len(mw) else 0,
            "池抓到": int(mw.caught.sum()),
            "覆盖率": round(float(mw.caught.mean()), 2) if len(mw) else None,
        })
    out["U_月度宇宙"] = rows

    # ── T: 妖股明细(2026-04~07) ────────────────────────────────────
    tall = w[(w.month >= "2026-04") & (w.month <= "2026-07")]
    tall = tall.nlargest(15, "streak_h")[["trade_date", "name", "board", "streak_h", "caught"]]
    tall["trade_date"] = tall.trade_date.dt.strftime("%Y-%m-%d")
    out["T_妖股明细"] = tall.to_dict("records")

    # ── U2: 漏网赢家条件解剖(2026-04~07 主板非ST) ───────────────────
    bm = winners[(winners.month >= "2026-04") & (winners.month <= "2026-07")
                 & (winners.board == "main") & (~winners.is_st)]
    bidx = bars.set_index(["vt_symbol", "trade_date"])

    def row_conds(row):
        def f(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return np.nan
        fails = []
        if bool(row["lu_tm1"]):
            fails.append("昨日已涨停")
        if not (0 <= f(row["change_pct_tm1"]) <= 5):
            fails.append("昨涨0~5%")
        if not (f(row["low_price_tm1"]) > f(row["ma20_tm1"])):
            fails.append("昨低>MA20")
        if not (f(row["dist_ma20"]) <= 0.12):
            fails.append("距MA20>12%")
        if not (f(row["turnover_rate_tm1"]) < 8):
            fails.append("换手>=8%")
        if not (f(row["cap_yi"]) < 1200):
            fails.append("市值>=1200亿")
        if not (f(row["close_price_tm1"]) < 12):
            fails.append("股价>=12")
        return fails

    fail_cnt: dict[str, int] = {}
    miss_rows, n_caught = [], 0
    for s, d, sh in zip(bm.vt_symbol, bm.trade_date, bm.streak_h):
        key = (s, d)
        if (s, d) in caught_keys:
            n_caught += 1
            continue
        if key not in bidx.index:
            continue
        row = bidx.loc[key]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        fails = row_conds(row)
        tag = ""
        if bool(row["oneword_strict"]):
            tag = "一字不可买"
        elif not bool(row["triggered"]):
            tag = "日内未触+8%"
        for f in fails:
            fail_cnt[f] = fail_cnt.get(f, 0) + 1
        if not fails:
            fail_cnt[tag or "条件全过仍漏"] = fail_cnt.get(tag or "条件全过仍漏", 0) + 1
        miss_rows.append({
            "date": d.strftime("%m-%d"), "name": name_map.get(s), "streak": int(sh),
            "price": round(float(row.close_price_tm1), 2),
            "chg": round(float(row.change_pct_tm1), 1),
            "dist": round(float(row.dist_ma20) * 100, 1),
            "to": round(float(row.turnover_rate_tm1), 1),
            "cap": round(float(row.cap_yi), 0),
            "gap": round(float(row.gap_open) * 100, 1),
            "failed": ",".join(fails) if fails else tag,
        })
    out["U2_漏网解剖"] = {"主板非ST赢家": len(bm), "抓到": n_caught, "漏网": len(miss_rows),
                          "失败条件计数": dict(sorted(fail_cnt.items(), key=lambda x: -x[1]))}

    # ── F: 三维特征对比(2026-04~07) ────────────────────────────────
    bad = ev_all[(ev_all.month >= "2026-04") & (ev_all.month <= "2026-07")]
    good = ev_all[ev_all.month.isin(["2025-11", "2025-12", "2026-01", "2026-08"])]
    feats = ["close_price_tm1", "cap_yi", "turnover_rate_tm1", "dist_ma20", "change_pct_tm1",
             "gap_open", "ret5_tm1", "ret60_tm1", "lu_cnt20", "lu_cnt60"]

    def med_block(df, label):
        r = {"label": label, "n": len(df)}
        if len(df) >= 3:
            r["seal"] = round(float(df.sealed.mean()), 3)
            r["streak2率"] = round(float((df.streak_h.fillna(0) >= 2).mean()), 3)
            for f in feats:
                v = pd.to_numeric(df[f], errors="coerce")
                mult = 100 if f in ("dist_ma20", "gap_open", "ret5_tm1", "ret60_tm1") else 1
                r[f] = round(float(v.median()) * mult, 2)
        return r

    mf = pd.DataFrame(miss_rows).rename(columns={
        "price": "close_price_tm1", "cap": "cap_yi", "to": "turnover_rate_tm1",
        "dist": "dist_ma20", "chg": "change_pct_tm1", "gap": "gap_open"})
    if len(mf):
        mf["sealed"] = True
        mf["streak_h"] = 2
        for f in ("ret5_tm1", "ret60_tm1", "lu_cnt20", "lu_cnt60"):
            mf[f] = np.nan
        # 距/涨幅/高开已按 % 存, 除回去统一 med_block 的 ×100
        for f in ("dist_ma20", "gap_open", "change_pct_tm1"):
            mf[f] = mf[f] / 100
    out["F_差月三维"] = [med_block(bad[bad.streak_h.fillna(0) >= 2], "池内连板赢家"),
                         med_block(bad[bad.streak_h.fillna(0) < 2], "池内未连板"),
                         med_block(mf, "池外漏网连板赢家")]
    out["F_好月对照"] = [med_block(good[good.streak_h.fillna(0) >= 2], "好月池内连板赢家"),
                         med_block(good[good.streak_h.fillna(0) < 2], "好月池内未连板")]

    # ── C: 口径月度拆解 ───────────────────────────────────────────
    rows = []
    for mth, sub in ev_all.groupby("month"):
        if mth < "2026-01":
            continue
        g8 = sub[sub.gap_open < 0.08]
        g26 = sub[sub.gap_open.between(0.02, 0.06, inclusive="left")]
        rows.append({"month": mth,
                     "全信号": f"n={len(sub)} {sub.ret.mean()*100:+.2f}",
                     "剔高开8": f"n={len(g8)} {g8.ret.mean()*100:+.2f}",
                     "gap2~6": f"n={len(g26)} {g26.ret.mean()*100:+.2f}" if len(g26) else "n=0"})
    out["C_口径月度"] = rows

    # ── S: 排序诊断(每日前3近似) ────────────────────────────────────
    usable = ev_all.copy()
    usable["priority"] = usable.gap_open.between(0.02, 0.06, inclusive="left")
    picks = usable.sort_values(["trade_date", "priority", "gap_open"], ascending=[True, False, True])
    taken = picks.groupby(picks.trade_date.dt.date).head(3)
    sm = taken.groupby(taken.trade_date.dt.to_period("M").astype(str))["ret"].agg(["count", "mean"])
    am = usable.groupby(usable.trade_date.dt.to_period("M").astype(str))["ret"].mean()
    out["S_排序诊断"] = [
        {"month": m, "吃到n": int(r["count"]), "吃到均": round(r["mean"] * 100, 2),
         "全信号均": round(float(am.get(m, np.nan)) * 100, 2)}
        for m, r in sm.iterrows() if m >= "2025-11"]

    # ── M: 分钟口径校验(2026-06/07, 1m) ─────────────────────────────
    mrows = []
    with psycopg.connect(DSN) as conn:
        for lo, hi in [("2026-06-01", "2026-06-30"), ("2026-07-01", "2026-07-31")]:
            evd = ev_all[(ev_all.trade_date >= lo) & (ev_all.trade_date <= hi)]
            pairs = evd[["vt_symbol", "trade_date"]].drop_duplicates()
            if not len(pairs):
                continue
            vals = ",".join(f"('{s}','{d.date()}')" for s, d in pairs.itertuples(index=False))
            mb = pd.read_sql(
                f"""SELECT m.vt_symbol, m.trade_date, m.bar_time, m.open_price, m.close_price,
                           m.high_price, m.low_price
                    FROM stock_minute_bars m JOIN (VALUES {vals}) AS v(s, d)
                      ON m.vt_symbol = v.s AND m.trade_date = v.d::date
                    WHERE m.interval = '1m'""", conn)
            if mb.empty:
                continue
            mb["bar_time"] = pd.to_datetime(mb["bar_time"])
            mb["trade_date"] = pd.to_datetime(mb["trade_date"])
            mb["tt"] = mb["bar_time"].dt.strftime("%H:%M")
            ev_idx = evd.set_index(["vt_symbol", "trade_date"])
            for (sym, d), day in mb.groupby(["vt_symbol", "trade_date"]):
                key = (sym, d)
                if key not in ev_idx.index:
                    continue
                ev = ev_idx.loc[key]
                if isinstance(ev, pd.DataFrame):
                    ev = ev.iloc[0]
                day = day.sort_values("bar_time").reset_index(drop=True)
                trig = ev["trigger_price"]
                hit = day.index[day["high_price"] >= trig - 1e-9]
                if len(hit) == 0:
                    continue
                fh = int(hit[0])
                held = day.loc[fh, "close_price"] >= trig - 1e-9
                tt = day.loc[fh, "tt"]
                ok_entry = held and fh + 1 < len(day) and tt <= "11:30" and ev["gap_open"] < 0.08
                if ok_entry:
                    entry = float(day.loc[fh + 1, "open_price"]) * (1 + SLIP)
                    ret_m = float(ev["open_p1"] if (not ev["sealed"] or int(ev["streak_h"] if np.isfinite(ev["streak_h"]) else 0) < 2)
                                  else ev[f"open_p{min(int(ev['streak_h']), 6)}"]) / entry - 1
                else:
                    ret_m = np.nan
                mrows.append({"month": d.strftime("%Y-%m"), "daily_ret": float(ev["ret"]),
                              "held": bool(held), "tt": tt, "tradable": bool(ok_entry),
                              "minute_ret": ret_m})
    if mrows:
        mdf = pd.DataFrame(mrows)
        out["M_分钟口径"] = [
            {"month": m, "日线信号n": len(sub_),
             "收住率": round(float(sub_.held.mean()), 2),
             "可交易n": int(sub_.tradable.sum()),
             "日线口径均": round(float(sub_.daily_ret.mean()) * 100, 2),
             "分钟可执行均": round(float(sub_.minute_ret.dropna().mean()) * 100, 2)
             if sub_.tradable.sum() > 3 else None,
             "午后触发占比": round(float((sub_.tt > "11:30").mean()), 2),
             "高开>=8%占比": round(float((ev_all[(ev_all.month == m)].gap_open >= 0.08).mean()), 2)}
            for m, sub_ in mdf.groupby("month")]

    # ── X: 条件反事实 ─────────────────────────────────────────────
    def variant(mask_extra, label):
        evv = simulate(bars[(bars.trade_date >= "2023-01-01") & mask_extra])
        if len(evv) < 30:
            return {"label": label, "note": "样本不足"}
        win = evv[(evv.trade_date >= "2026-04-01") & (evv.trade_date <= "2026-07-31")]
        tr = evv[evv.trade_date < TRAIN_END]
        va = evv[evv.trade_date >= TRAIN_END]
        return {"label": label,
                "差月窗": f"n={len(win)} {win.ret.mean()*100:+.2f}" if len(win) > 5 else f"n={len(win)}",
                "训": f"n={len(tr)} {tr.ret.mean()*100:+.2f}",
                "验": f"n={len(va)} {va.ret.mean()*100:+.2f}"}

    out["X_反事实"] = [
        variant(pool_mask, "基线8条件"),
        variant(np.logical_and.reduce([v for k, v in conds.items() if k != "股价<12"]), "去掉股价线"),
        variant(np.logical_and.reduce([v for k, v in conds.items() if k != "股价<12"])
                & (bars.close_price_tm1 < 20), "股价<20"),
        variant(np.logical_and.reduce([v for k, v in conds.items() if k != "距MA20<=12%"])
                & (bars.dist_ma20 <= 0.20), "距MA20放宽20%"),
        variant(np.logical_and.reduce([v for k, v in conds.items() if k != "换手<8%"])
                & (bars.turnover_rate_tm1 < 12), "换手放宽12%"),
        variant(np.logical_and.reduce([v for k, v in conds.items() if k != "昨涨0~5%"])
                & bars.change_pct_tm1.between(-2, 7), "昨涨放宽-2~7%"),
        variant(pool_mask & (bars.gap_open < 0.08), "基线+剔高开>=8%"),
        variant(pool_mask & (bars.gap_open >= 0.02), "基线+只做高开>=2%"),
    ]

    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
