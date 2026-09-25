"""高位接力打板池计算:T-1 收盘后给次日 2/3 连板票打链式方案候选标。

口径 = 连板链组合方案 A1~D2 七方案(2026-09-25 定稿,汇总/连板链组合总结.md):
- 池 = 昨日恰好 2/3 连板的主板非ST票(全量,雷达);地基日=首板前一天,阴阳分组
- 候选 = 链档条件(一板×二板[×三板]的开盘档;低<0/平0~3/高3~7毒区/强≥7);
  今天开窗(竞价定型后由盘中扫描复核:低<0/平0~3/高3~6/强6~9.5,≥9.5顶格不命中)
- 回避 = 一板或二板开3~7%(半温不火);二板开≥3%×首3日涨超5%(追高透支);
  三接四阴今天低开(盘中判)
- 字段与 relay_research.py/relay_summary2.py 同口径(事件静态字段含 b1/b2/b3 开盘档)
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.high_relay import contracts

_LOOKBACK_CAL_DAYS = 300  # ≈200 个交易日,覆盖 前波120(120)+h60(60)+ma30(30)+余量


def latest_daily_date() -> date | None:
    """全市场日线最新交易日(数据基准日 T-1)。"""
    with session_scope() as session:
        value = session.execute(
            select(func.max(schema.stock_daily_bars.c.trade_date))
        ).scalar_one_or_none()
    return value if isinstance(value, date) else None


def next_weekday(day: date) -> date:
    """下一工作日(周一~周五)。节假日池会闲置,由下一真交易日的 EOD 重算覆盖。"""
    nxt = day + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def board_of(code6: str) -> str:
    """板块分类(与研究 board_of 逐字一致):主板/创业板/科创板/北交所。"""
    if code6.startswith(("300", "301")):
        return "cyb"
    if code6.startswith(("688", "689")):
        return "kcb"
    if code6.startswith(("8", "4", "92")):
        return "bse"
    return "main"


def load_universe(engine) -> pd.DataFrame:
    """主板非ST非退宇宙(与研究过滤逐字一致:板块=main,名称不含ST/退)。"""
    stocks = pd.read_sql(select(schema.stocks.c.vt_symbol, schema.stocks.c.name), engine)
    stocks["code6"] = stocks["vt_symbol"].str[:6]
    stocks["board"] = stocks["code6"].map(board_of)
    stocks["bad"] = (stocks["name"].str.upper().str.contains("ST")
                     | stocks["name"].str.contains("退"))
    return stocks[(stocks["board"] == "main") & (~stocks["bad"])].copy()


def derive_daily(bars: pd.DataFrame) -> pd.DataFrame:
    """日线派生列(pool/backtest 共用基础件;与 relay_research.build_events 同口径)。"""
    bars = bars.copy()
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
    bars["vol_rel5"] = bars["volume"] / gv.transform(
        lambda s: s.rolling(5, min_periods=3).mean())
    gc = g["close_price"]
    for w in (5, 10, 20, 30):
        bars[f"ma{w}"] = gc.transform(lambda s, w=w: s.rolling(w, min_periods=w).mean())
    bars["h60"] = g["high_price"].transform(lambda s: s.rolling(60, min_periods=20).max())
    bars["l60"] = g["low_price"].transform(lambda s: s.rolling(60, min_periods=20).min())
    bars["c20"] = gc.shift(20)
    bars["streak_prev"] = g["streak"].shift(1).fillna(0).astype(int)
    # 连板段尾(供前波查询): 当天涨停且第二天不再涨停
    bars["run_end"] = bars["is_lim"] & (~g["is_lim"].shift(-1).fillna(False).astype(bool))
    # 市场环境: 每天全市场(宇宙内)涨停家数
    mkt = bars.groupby("trade_date", sort=False)["is_lim"].sum()
    bars["mkt_lim"] = bars["trade_date"].map(mkt)
    bars["mkt_prev"] = bars["trade_date"].map(mkt.shift(1))
    return bars


def board_type(one_word: bool, lshadow: float) -> str:
    if one_word:
        return "一字"
    return "下影" if lshadow >= contracts.LSHADOW_TH else "实体"


def make_ctx(bars: pd.DataFrame) -> dict[str, object]:
    """事件字段计算上下文(一次性预建;pool/backtest 共用,O(1)/事件)。

    bars 必须先过 derive_daily(已按 vt_symbol,trade_date 排序,同票行连续)。
    """
    cols = {c: bars[c].to_numpy() for c in
            ["close_price", "open_price", "high_price", "low_price", "prev_close",
             "is_lim", "one_word", "streak", "chg", "lshadow", "turnover_rate",
             "ma5", "ma10", "ma20", "ma30", "h60", "l60", "c20"]}
    sid = bars["sid"].to_numpy()
    pos = bars["pos"].to_numpy()
    # 每只票的首行 iloc(同票行连续 → iloc = start + pos)
    starts: dict[int, int] = {}
    for i in range(len(bars)):
        s = int(sid[i])
        if s not in starts:
            starts[s] = i
    # 连板段尾(高度≥2): sid → (段尾 pos 数组, 高度数组)
    runs = bars[bars["run_end"] & (bars["streak"] >= 2)]
    run_by = {int(s_): (a["pos"].to_numpy(), a["streak"].to_numpy())
              for s_, a in runs.groupby("sid", sort=False)}
    return {"cols": cols, "sid": sid, "pos": pos, "starts": starts, "run_by": run_by}


def static_fields(ctx: dict[str, object], i_last: int, n_board: int) -> dict[str, object] | None:
    """事件静态字段(地基/均线/前波/接力链/前板高度)。

    i_last = 末板日(信号日 T-1)在 bars 中的行号;n_board = 昨日连板数(2/3)。
    与 relay_research.build_events 事件段 + relay_foundation.augment 同口径
    (前板高度的 60 日窗按同票 pos 计算,不跨票)。
    """
    cols: dict[str, np.ndarray] = ctx["cols"]  # type: ignore[assignment]
    sid: np.ndarray = ctx["sid"]  # type: ignore[assignment]
    pos_arr: np.ndarray = ctx["pos"]  # type: ignore[assignment]
    s = int(sid[i_last])
    pos = int(pos_arr[i_last])
    if pos - n_board < 0:
        return None  # 首板前一天都没有,地基缺失
    f = i_last - n_board        # 地基日(首板前一天)
    if int(sid[f]) != s:
        return None
    rec: dict[str, object] = {}
    fc = float(cols["close_price"][f])
    fo = float(cols["open_price"][f])
    rec["foundation_yang"] = bool(fc >= fo)
    rec["foundation_chg"] = round(float(cols["chg"][f]) * 100, 2) \
        if cols["chg"][f] == cols["chg"][f] else None
    h60 = cols["h60"][f]
    rec["dist_h60"] = round((fc / h60 - 1) * 100, 1) if h60 == h60 and h60 > 0 else None
    ma = [cols[m][f] for m in ("ma5", "ma10", "ma20", "ma30")]
    rec["ma_state"] = "".join("+" if a >= b else "-" for a, b in zip(ma, ma[1:], strict=False)) \
        if all(x == x for x in ma) else ""
    ma10 = cols["ma10"][f]
    rec["dist_ma10"] = round((fc / ma10 - 1) * 100, 1) if ma10 == ma10 and ma10 > 0 else None
    # 前波(连板段尾高度≥2 的段,首板之前)
    ends, hts = ctx["run_by"].get(s, (np.array([]), np.array([])))  # type: ignore[attr-defined]
    b1_pos = pos - n_board + 1                     # 首板日 pos
    before = ends < b1_pos
    for win in (60, 120):
        inwin = before & (ends >= b1_pos - win)
        rec[f"prev_wave{win}"] = int(hts[inwin].max()) if inwin.any() else 0
    # 前板高度(B3): 首板前 60 个交易日内最近一个涨停的连板高度(同票窗,不跨票)
    start = ctx["starts"][s]  # type: ignore[index]
    lo_i = start + max(0, b1_pos - 60)
    hi_i = start + b1_pos                          # 首板 iloc(不含)
    lim_idx = np.flatnonzero(cols["is_lim"][lo_i:hi_i])
    if len(lim_idx):
        j = lo_i + int(lim_idx[-1])
        rec["prior_height"] = int(cols["streak"][j])
        rec["prior_gap"] = int(b1_pos - int(pos_arr[j]) - 1)
    else:
        rec["prior_height"] = None
        rec["prior_gap"] = None
    # 接力链: 首板~末板逐板
    types: list[str] = []
    for k in range(1, n_board + 1):
        j = i_last - n_board + k
        bt = board_type(bool(cols["one_word"][j]), float(cols["lshadow"][j]))
        og = (float(cols["open_price"][j]) / float(cols["prev_close"][j]) - 1) * 100
        turn = cols["turnover_rate"][j]
        rec[f"b{k}_type"] = bt
        rec[f"b{k}_open"] = round(og, 1)
        rec[f"b{k}_turn"] = round(float(turn), 1) if turn == turn else None
        types.append(bt)
    rec["chain"] = "→".join(types)
    b1t = rec.get("b1_turn")
    b2t = rec.get("b2_turn")
    rec["turn_grad"] = round(b2t - b1t, 1) if b1t is not None and b2t is not None else None
    # 首3日累计涨幅(含地基日): 地基日收盘 / 3个交易日前收盘 - 1(回避「追高透支」用)
    if f - 3 >= 0 and int(sid[f - 3]) == s:
        c3 = float(cols["close_price"][f - 3])
        rec["pre3_pct"] = round((fc / c3 - 1) * 100, 1) if c3 > 0 else None
    else:
        rec["pre3_pct"] = None
    return rec


def chain_tier(open_pct) -> str | None:
    """链上板的开盘档: 低<0 / 平0~3 / 高3~7(毒区) / 强≥7。"""
    c = contracts
    if open_pct is None:
        return None
    if open_pct < c.CHAIN_LOW_HI:
        return "低"
    if open_pct < c.CHAIN_FLAT_HI:
        return "平"
    if open_pct < c.CHAIN_HIGH_HI:
        return "高"
    return "强"


def tag_point(group4: str, b1_open, b2_open, b3_open, auction_pct=None) -> str:
    """链式七方案打标(与 汇总/连板链组合总结.md 口径一致)。
    auction_pct = 今天开盘 %(池计算时未知传 None → 只按链条件打候选标,
    今天开窗由盘中扫描/回测复核;≥9.5 顶格一律不命中)。"""
    c = contracts
    if auction_pct is not None and auction_pct >= c.TODAY_CAP:
        return "—"
    t = (chain_tier(b1_open), chain_tier(b2_open), chain_tier(b3_open))
    for s in c.SCHEMES:
        if s["group4"] != group4:
            continue
        ct = s["chain"]
        if all(w is None or w == tt for w, tt in zip(ct, t, strict=False)):
            if auction_pct is None:
                return str(s["no"])
            lo, hi = s["today"]
            return str(s["no"]) if lo <= auction_pct < hi else "—"
    return "—"


def scheme_today_window(point: str):
    """方案「今天开」窗 (lo, hi);非方案返回 None(供盘中扫描/前端展示)。"""
    for s in contracts.SCHEMES:
        if s["no"] == point:
            return s["today"]
    return None


def static_avoid(point: str, group4: str, b1_open, b2_open, pre3_pct) -> str:
    """静态回避原因(命中也不买;空串=不回避)。三接四阴今天低开属盘中回避(live_scan)。"""
    if point == "—":
        return ""
    reasons: list[str] = []
    if chain_tier(b1_open) == "高" or chain_tier(b2_open) == "高":
        reasons.append("一板或二板开过3~7%(半温不火)")
    if chain_tier(b2_open) in ("高", "强") and pre3_pct is not None \
            and pre3_pct > contracts.AVOID_PRE3_MAX:
        reasons.append("二板开≥3%×首3日涨超5%(追高透支)")
    return ";".join(reasons)


def compute_pool(data_date: date | None = None) -> dict[str, object]:
    """以 data_date(默认最新日线日)为 T-1 计算次日池(2/3连板全量+链式方案候选打标)。

    返回 {data_date, exec_date, rules_version, mkt_lim_tm1, entries, filter_stats}。
    """
    engine = get_engine()
    if data_date is None:
        data_date = latest_daily_date()
    if data_date is None:
        return {"data_date": None, "exec_date": None, "mkt_lim_tm1": None, "entries": [],
                "rules_version": contracts.HPR_RULES_VERSION,
                "filter_stats": {"error": "no_daily_bars"}}
    window_start = data_date - timedelta(days=_LOOKBACK_CAL_DAYS)

    bars = pd.read_sql(
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.volume,
            schema.stock_daily_bars.c.turnover_rate,
        ).where(schema.stock_daily_bars.c.trade_date >= window_start,
                schema.stock_daily_bars.c.trade_date <= data_date),
        engine, parse_dates=["trade_date"],
    )
    universe = load_universe(engine)
    stats: dict[str, int] = {"bars_rows": int(len(bars))}
    if bars.empty or universe.empty:
        return {"data_date": data_date.isoformat(), "exec_date": None, "mkt_lim_tm1": None,
                "entries": [], "rules_version": contracts.HPR_RULES_VERSION,
                "filter_stats": {**stats, "error": "empty_source"}}

    name_map = universe.set_index("vt_symbol")["name"]
    bars = bars[bars["vt_symbol"].isin(set(universe["vt_symbol"]))].copy()
    bars = derive_daily(bars)
    stats["eligible_universe"] = int(len(universe))

    mkt_prev = bars.loc[bars["trade_date"] == pd.Timestamp(data_date), "is_lim"].sum()
    stats["mkt_lim_tm1"] = int(mkt_prev)

    last = bars[(bars["trade_date"] == pd.Timestamp(data_date))
                & (bars["streak"].isin([2, 3]))]
    stats["pool_raw"] = int(len(last))

    ctx = make_ctx(bars)
    entries: list[dict[str, object]] = []
    n_actionable = 0
    for row in last.itertuples():
        i_last = int(row.Index)
        n_board = int(row.streak)
        rec = static_fields(ctx, i_last, n_board)
        if rec is None:
            continue
        yang = bool(rec["foundation_yang"])
        group4 = ("二接三" if n_board == 2 else "三接四") + ("阳" if yang else "阴")
        point = tag_point(group4, rec.get("b1_open"), rec.get("b2_open"),
                          rec.get("b3_open"))
        avoid = static_avoid(point, group4, rec.get("b1_open"),
                             rec.get("b2_open"), rec.get("pre3_pct"))
        actionable = point != "—" and not avoid
        n_actionable += int(actionable)
        # 候选=链条件已命中,今天开窗(竞价定型后对照;顶格≥9.5不命中)
        win = scheme_today_window(point) if point != "—" else None
        gate = None
        if win is not None:
            gate = f"today_{win[0]:g}_{win[1]:g}"
        prev_close = float(row.close_price)
        entries.append({
            "vt_symbol": str(row.vt_symbol),
            "name": str(name_map.get(row.vt_symbol) or ""),
            "group4": group4,
            "n_board": n_board,
            "point": point,
            "level": contracts.POINT_LEVELS.get(point, "—"),
            "actionable": actionable,
            "avoid_static": avoid or None,
            "auction_gate": gate,
            "prev_close": prev_close,
            "limit_price": round(prev_close * 1.10 + 1e-9, 2),
            "foundation_yang": yang,
            "foundation_chg": rec["foundation_chg"],
            "dist_h60": rec["dist_h60"],
            "ma_state": rec["ma_state"],
            "dist_ma10": rec["dist_ma10"],
            "prior_height": rec["prior_height"],
            "prior_gap": rec["prior_gap"],
            "prev_wave60": rec["prev_wave60"],
            "prev_wave120": rec["prev_wave120"],
            "chain": rec["chain"],
            "b1_type": rec.get("b1_type"),
            "b2_type": rec.get("b2_type"),
            "b3_type": rec.get("b3_type"),
            "b1_open": rec.get("b1_open"),
            "b2_open": rec.get("b2_open"),
            "b3_open": rec.get("b3_open"),
            "b1_turn": rec.get("b1_turn"),
            "b2_turn": rec.get("b2_turn"),
            "turn_grad": rec["turn_grad"],
            "pre3_pct": rec.get("pre3_pct"),
            "mkt_lim_tm1": int(mkt_prev),
        })
    stats["actionable"] = n_actionable
    for pk in contracts.POINT_KEYS:
        stats[f"pool_{pk}"] = sum(1 for e in entries if e["point"] == pk)
        stats[f"act_{pk}"] = sum(1 for e in entries if e["point"] == pk and e["actionable"])
    entries.sort(key=lambda e: (str(e["group4"]), str(e["point"]), str(e["vt_symbol"])))
    return {
        "data_date": data_date.isoformat(),
        "exec_date": next_weekday(data_date).isoformat(),
        "rules_version": contracts.HPR_RULES_VERSION,
        "mkt_lim_tm1": int(mkt_prev),
        "entries": entries,
        "filter_stats": stats,
    }
