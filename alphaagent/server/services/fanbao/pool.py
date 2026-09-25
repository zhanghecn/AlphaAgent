"""断板反包打板盘前池计算:全部条件来自 T-1 收盘数据(无未来函数)。

口径 = 量化因子研究/反包/反包规则.md v2 定稿(2026-09-25),
字段计算逐行对齐研究脚本 fanbao_research.py build_events:
  池入选 = 今日处于断板第 1~3 天(连续收盘不涨停)且前波高度 2/4/5+板
          (3板删除四年皆弱,断4~5天留回测参考行不进池),主板非ST非退,上市>5日;
  分组 = 六组(高度段2/4/5+ × 跌幅阴阳:昨收<前日收=阴);
  打标 = 五方案点 S1/S2/S3/O1/O2(全部为 T-1 静态信息,反包无竞价门);
  回避 = 死格在池里打标(格级+2板条件级,未命中也标,命中也不买);
  触发价 = 今日涨停价 = round(昨收×1.10+1e-9, 2)(与研究浮点口径一致)。
⚠️ yin_yang=跌幅口径(分组);break_yin_count=实体口径(S1条件),两把尺子严禁互换。
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine, session_scope
from alphaagent.server.services.fanbao import contracts

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
    """日线派生列(pool/backtest 共用基础件;与 fanbao_research 同口径)。"""
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
    # 断板计数(研究 notlim_run/notlim_prev): 段号 = is_lim 状态切换计数(同票内每段一个常数),
    # 断板段内从 1 数起,涨停段内恒 0 —— 不能用 brk(那是跨段累计的全部不涨停天数)
    seg_cs = bars["is_lim"].ne(g["is_lim"].shift(1)).groupby(bars["sid"], sort=False).cumsum()
    bars["notlim_run"] = (~bars["is_lim"]).astype("int8").groupby(
        [bars["sid"], seg_cs], sort=False).cumsum()
    bars["notlim_prev"] = g["notlim_run"].shift(1)
    bars["touch"] = elig & (bars["high_price"] >= bars["limit_price"] - 1e-6)
    bars["chg"] = bars["close_price"] / bars["prev_close"] - 1
    lo = pd.concat([bars["open_price"], bars["close_price"]], axis=1).min(axis=1)
    bars["lshadow"] = (lo - bars["low_price"]) / bars["prev_close"] * 100
    gc = g["close_price"]
    for w in (5, 10, 20, 30):
        bars[f"ma{w}"] = gc.transform(lambda s, w=w: s.rolling(w, min_periods=w).mean())
    bars["h60"] = g["high_price"].transform(lambda s: s.rolling(60, min_periods=20).max())
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

    bars 必须先过 derive_daily(已按 vt_symbol,trade_date 排序,同票行连续)。"""
    cols = {c: bars[c].to_numpy() for c in
            ["close_price", "open_price", "high_price", "low_price", "prev_close",
             "is_lim", "one_word", "streak", "notlim_run", "touch", "chg", "lshadow",
             "ma5", "ma10", "ma20", "ma30", "h60"]}
    sid = bars["sid"].to_numpy()
    pos = bars["pos"].to_numpy()
    dates = bars["trade_date"].to_numpy()
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
    return {"cols": cols, "sid": sid, "pos": pos, "dates": dates,
            "starts": starts, "run_by": run_by}


def break_fields(ctx: dict[str, object], i: int) -> dict[str, object] | None:
    """断板期静态字段(池与回测共用的核心件)。

    i = 池计算日(T-1,处于断板中)在 bars 中的行号。g = notlim_run[i],
    e = i - g(末板日),N = streak[e](前波高度)。返回 None = 无有效前波。
    与 fanbao_research.build_events 断板期段同口径。"""
    cols: dict[str, np.ndarray] = ctx["cols"]  # type: ignore[assignment]
    sid: np.ndarray = ctx["sid"]  # type: ignore[assignment]
    pos_arr: np.ndarray = ctx["pos"]  # type: ignore[assignment]
    s = int(sid[i])
    g = int(cols["notlim_run"][i])
    e = i - g
    if g < 1 or e < 0 or int(sid[e]) != s:
        return None
    n_board = int(cols["streak"][e])
    if n_board < 2:
        return None  # 前波高度1板(孤立涨停)不构成反包事件
    rec: dict[str, object] = {"gap": g, "n_board": n_board}
    ci = float(cols["close_price"][i])
    ce = float(cols["close_price"][e])
    # 跌幅口径阴阳(分组): 昨收 vs 前日收 → 今日收 vs prev_close
    rec["yin_yang"] = "阳" if ci >= float(cols["prev_close"][i]) else "阴"
    rec["seg"] = contracts.seg_of(n_board)
    dates: np.ndarray = ctx["dates"]  # type: ignore[assignment]
    rec["break_end"] = pd.Timestamp(dates[e]).date()
    rec["wave_start"] = pd.Timestamp(dates[e - n_board + 1]).date()
    # 断板期逐日(末板次日~今日,共 g 行)
    days: list[str] = []
    yin_cnt = 0
    zha_cnt = 0
    low_close = ci
    for j in range(e + 1, i + 1):
        cj = float(cols["close_price"][j])
        oj = float(cols["open_price"][j])
        tag = "阳" if cj >= oj else "阴"          # 实体口径(S1 条件用)
        yin_cnt += tag == "阴"
        zha_cnt += bool(cols["touch"][j]) and not bool(cols["is_lim"][j])
        days.append(f"{tag}{cols['chg'][j] * 100:+.1f}")
        low_close = min(low_close, cj)
    rec["break_days"] = "→".join(days)
    rec["break_yin_count"] = yin_cnt
    rec["break_zha_days"] = zha_cnt
    rec["break_drop_pct"] = round((ci / ce - 1) * 100, 1)
    rec["pit_depth_pct"] = round((low_close / ce - 1) * 100, 1)
    # 末日开盘方式(v2.1 S1/S2 条件):实体阴/阳 + 开盘涨幅
    oi = float(cols["open_price"][i])
    rec["last_entity"] = "阳" if ci >= oi else "阴"
    pci = cols["prev_close"][i]
    rec["last_open_pct"] = round((oi / pci - 1) * 100, 2) if pci == pci and pci > 0 else None
    # 技术位(T-1=今日口径,非 hpr 的地基日口径)
    rec["dist_ma5"] = round((ci / cols["ma5"][i] - 1) * 100, 1) \
        if cols["ma5"][i] == cols["ma5"][i] and cols["ma5"][i] > 0 else None
    h60 = cols["h60"][i]
    rec["dist_h60"] = round((ci / h60 - 1) * 100, 1) if h60 == h60 and h60 > 0 else None
    ma = [cols[m][i] for m in ("ma5", "ma10", "ma20", "ma30")]
    rec["ma_state"] = "".join("+" if a >= b else "-" for a, b in zip(ma, ma[1:], strict=False)) \
        if all(x == x for x in ma) else ""
    ma10 = cols["ma10"][i]
    rec["dist_ma10"] = round((ci / ma10 - 1) * 100, 1) if ma10 == ma10 and ma10 > 0 else None
    # 地基(首板前一天;新股首板贴数据头则缺失)
    f = e - n_board
    if f >= 0 and int(sid[f]) == s:
        fc = float(cols["close_price"][f])
        rec["foundation_yang"] = bool(fc >= float(cols["open_price"][f]))
        rec["foundation_chg"] = round(float(cols["chg"][f]) * 100, 2) \
            if cols["chg"][f] == cols["chg"][f] else None
    else:
        rec["foundation_yang"] = None
        rec["foundation_chg"] = None
    # 前波(连板段尾高度≥2 的段,首板之前)
    ends, hts = ctx["run_by"].get(s, (np.array([]), np.array([])))  # type: ignore[attr-defined]
    b1_pos = int(pos_arr[e]) - n_board + 1               # 首板日 pos
    before = ends < b1_pos
    for win in (60, 120):
        inwin = before & (ends >= b1_pos - win)
        rec[f"prev_wave{win}"] = int(hts[inwin].max()) if inwin.any() else 0
    # 前波之前的断板天数(最近一个前段末板~本波首板)
    rec["prior_gap"] = None
    if before.any():
        rec["prior_gap"] = int(b1_pos - int(ends[before].max()) - 1)
    # 前波板型链(首板~末板逐板;streak 连续性保证同票)
    types: list[str] = []
    for k in range(1, n_board + 1):
        j = e - n_board + k
        types.append(board_type(bool(cols["one_word"][j]), float(cols["lshadow"][j])))
    rec["chain"] = "→".join(types)
    return rec


def compute_pool(data_date: date | None = None) -> dict[str, object]:
    """以 data_date(默认最新日线日)为 T-1 计算次日池(断板中全量+五点打标)。

    返回 {data_date, exec_date, rules_version, mkt_lim_tm1, entries, filter_stats}。"""
    engine = get_engine()
    if data_date is None:
        data_date = latest_daily_date()
    if data_date is None:
        return {"data_date": None, "exec_date": None, "mkt_lim_tm1": None, "entries": [],
                "rules_version": contracts.FANBAO_RULES_VERSION,
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
        ).where(schema.stock_daily_bars.c.trade_date >= window_start,
                schema.stock_daily_bars.c.trade_date <= data_date),
        engine, parse_dates=["trade_date"],
    )
    universe = load_universe(engine)
    stats: dict[str, int] = {"bars_rows": int(len(bars))}
    if bars.empty or universe.empty:
        return {"data_date": data_date.isoformat(), "exec_date": None, "mkt_lim_tm1": None,
                "entries": [], "rules_version": contracts.FANBAO_RULES_VERSION,
                "filter_stats": {**stats, "error": "empty_source"}}

    name_map = universe.set_index("vt_symbol")["name"]
    bars = bars[bars["vt_symbol"].isin(set(universe["vt_symbol"]))].copy()
    bars = derive_daily(bars)
    stats["eligible_universe"] = int(len(universe))

    mkt_tm1 = bars.loc[bars["trade_date"] == pd.Timestamp(data_date), "is_lim"].sum()
    stats["mkt_lim_tm1"] = int(mkt_tm1)

    # 候选 = 今日处于断板中(notlim_run>=1)且前波高度>=2
    last = bars[(bars["trade_date"] == pd.Timestamp(data_date))
                & (bars["notlim_run"] >= 1)]
    stats["pool_raw"] = int(len(last))

    ctx = make_ctx(bars)
    entries: list[dict[str, object]] = []
    n_actionable = 0
    for row in last.itertuples():
        i = int(row.Index)
        rec = break_fields(ctx, i)
        if rec is None:
            continue
        n_board = int(rec["n_board"])
        g = int(rec["gap"])
        seg = rec["seg"]
        if not seg or g not in contracts.GS_MAIN:
            continue  # 3板与断4+不进池(回测留参考行)
        yy = str(rec["yin_yang"])
        group6 = f"{seg}{yy}"
        drop = rec["break_drop_pct"]
        point = contracts.tag_point(n_board, g, yy, drop, int(rec["break_yin_count"]),
                                    last_entity=str(rec["last_entity"]),
                                    last_open_pct=rec["last_open_pct"])
        # 死格对池内所有票打标(格级+2板条件级;命中也不买)
        avoid = contracts.dead_cell_reason(n_board, g, yy,
                                           int(rec["break_yin_count"]), drop)
        actionable = point != "—" and not avoid
        n_actionable += int(actionable)
        prev_close = float(row.close_price)
        entries.append({
            "vt_symbol": str(row.vt_symbol),
            "name": str(name_map.get(row.vt_symbol) or ""),
            "group6": group6,
            "n_board": n_board,
            "seg": seg,
            "gap": g,
            "yin_yang": yy,
            "point": point,
            "level": contracts.POINT_LEVELS.get(point, "—"),
            "actionable": actionable,
            "avoid_static": avoid or None,
            "prev_close": prev_close,
            "limit_price": round(prev_close * 1.10 + 1e-9, 2),
            "break_end": rec["break_end"],
            "wave_start": rec["wave_start"],
            "break_days": rec["break_days"],
            "break_yin_count": rec["break_yin_count"],
            "break_zha_days": rec["break_zha_days"],
            "break_drop_pct": drop,
            "pit_depth_pct": rec["pit_depth_pct"],
            "last_entity": rec["last_entity"],
            "last_open_pct": rec["last_open_pct"],
            "dist_ma5": rec["dist_ma5"],
            "dist_h60": rec["dist_h60"],
            "ma_state": rec["ma_state"],
            "dist_ma10": rec["dist_ma10"],
            "chain": rec["chain"],
            "foundation_yang": rec["foundation_yang"],
            "foundation_chg": rec["foundation_chg"],
            "prior_gap": rec["prior_gap"],
            "prev_wave60": rec["prev_wave60"],
            "prev_wave120": rec["prev_wave120"],
            "mkt_lim_tm1": int(mkt_tm1),
        })
    stats["pool_main"] = len(entries)
    stats["actionable"] = n_actionable
    for pk in contracts.POINT_KEYS:
        stats[f"pool_{pk}"] = sum(1 for e in entries if e["point"] == pk)
        stats[f"act_{pk}"] = sum(1 for e in entries if e["point"] == pk and e["actionable"])
    for gg in contracts.GS_MAIN:
        stats[f"pool_gap{gg}"] = sum(1 for e in entries if e["gap"] == gg)
    for seg in contracts.SEGS:
        stats[f"pool_{seg}"] = sum(1 for e in entries if e["seg"] == seg)
    entries.sort(key=lambda e: (str(e["group6"]), str(e["point"]), str(e["vt_symbol"])))
    return {
        "data_date": data_date.isoformat(),
        "exec_date": next_weekday(data_date).isoformat(),
        "rules_version": contracts.FANBAO_RULES_VERSION,
        "mkt_lim_tm1": int(mkt_tm1),
        "entries": entries,
        "filter_stats": stats,
    }
