# -*- coding: utf-8 -*-
"""N型补涨打板 · 首次触板时间分布研究(好票 vs 差票 → 最佳打板时段).

主人问题(2026-09-04): N型好票/坏票的首次涨停时间分布, 能否从涨停时间段划分最佳打板时间.

数据源: 本地 stock_minute_bars(interval='1m', 2024-08-01~2026-08-12, 关注池~449票/日).
口径: 首次触板时间 = 入场日(D0)第一根 high_price >= 涨停价 的1分钟K收盘时间戳
      (bar_time=09:31 即 09:30-09:31 那根). 与回测「触板买」口径天然一致
      (回测已排一字: 开盘>=涨停价不入场, 所以事件里 open<limit).
      ⚠️ 分钟库只存关注池, 事件覆盖率见输出; 未覆盖笔不进统计.
好差票: 好=板留收益 ret_bw>0 / 差=ret_bw<=0 (案例库同口径).
"""
import sys
sys.path.insert(0, "/app")

import pandas as pd
from sqlalchemy import text

from alphaagent.server.db.session import get_engine
from alphaagent.server.services.weak_to_strong import backtest, contracts


def load_events() -> pd.DataFrame:
    T = backtest._build_events()
    frames = [backtest._trades_for(T[T["group_key"] == gk].copy())
              for gk in contracts.GROUP_KEYS]
    t = pd.concat(frames, ignore_index=True)
    return t[["vt_symbol", "name", "group_key", "entry_date", "entry_price",
              "ret_bw", "seal", "open_g", "exit_reason"]].copy()


def load_first_touch(events: pd.DataFrame) -> pd.DataFrame:
    """(vt_symbol, entry_date) VALUES-join 拉 1m 分钟线 → 首次触板时间."""
    pairs = sorted({(r.vt_symbol, str(pd.Timestamp(r.entry_date).date()))
                    for r in events.itertuples()})
    values = ",".join(f"('{v}','{d}'::date)" for v, d in pairs)
    sql = f"""
        SELECT m.vt_symbol, m.trade_date, m.bar_time, m.high_price, m.open_price
        FROM stock_minute_bars m
        JOIN (VALUES {values}) AS e(vt_symbol, trade_date)
          ON m.vt_symbol = e.vt_symbol AND m.trade_date = e.trade_date
        WHERE m.interval = '1m'
        ORDER BY m.vt_symbol, m.trade_date, m.bar_time
    """
    bars = pd.read_sql(text(sql), get_engine())
    bars["limit_px"] = None
    # 事件涨停价挂回(同票同日唯一)
    ev = events.copy()
    ev["date_str"] = pd.to_datetime(ev["entry_date"]).dt.strftime("%Y-%m-%d")
    lim = {(r.vt_symbol, r.date_str): float(r.entry_price) for r in ev.itertuples()}
    bars["limit_px"] = [lim.get((v, str(d)), None)
                        for v, d in zip(bars["vt_symbol"], bars["trade_date"])]
    bars = bars.dropna(subset=["limit_px"])
    # 首次触板: high >= 涨停价(1e-6容差)
    touched = bars[bars["high_price"] >= bars["limit_px"] - 1e-6]
    first = touched.groupby(["vt_symbol", "trade_date"], as_index=False).agg(
        touch_time=("bar_time", "min"),
        first_bar_open=("open_price", "first"))  # 09:31开盘价(一字复核用)
    return first


BUCKETS = [
    ("09:31-10:00", "09:31", "10:00"),
    ("10:00-10:30", "10:00", "10:30"),
    ("10:30-11:00", "10:30", "11:00"),
    ("11:00-11:30", "11:00", "11:30"),
    ("13:01-13:30", "13:01", "13:30"),
    ("13:30-14:00", "13:30", "14:00"),
    ("14:00-14:30", "14:00", "14:30"),
    ("14:30-15:00", "14:30", "15:01"),
]
COARSE = {
    "09:31-10:00": "①早盘9:31-10:00", "10:00-10:30": "②上午前段10:00-10:30",
    "10:30-11:00": "②上午前段10:00-10:30", "11:00-11:30": "③上午后段11:00-11:30",
    "13:01-13:30": "④午后13:00-14:00", "13:30-14:00": "④午后13:00-14:00",
    "14:00-14:30": "⑤尾盘14:00-15:00", "14:30-15:00": "⑤尾盘14:00-15:00",
}


def bucket_of(ts) -> str | None:
    hm = pd.Timestamp(ts).strftime("%H:%M")
    for lab, lo, hi in BUCKETS:
        if lo <= hm < hi:
            return lab
    return None


def stats_block(df: pd.DataFrame, by: str) -> pd.DataFrame:
    rows = []
    for key, g in df.groupby(by):
        rows.append({
            by: key, "n": len(g),
            "好票率%": round((g["ret_bw"] > 0).mean() * 100, 1),
            "板留均%": round(g["ret_bw"].mean() * 100, 2),
            "板留中位%": round(g["ret_bw"].median() * 100, 2),
            "封板率%(D0收封)": round(g["seal"].mean() * 100, 1) if "seal" in g else None,
        })
    return pd.DataFrame(rows).sort_values(by)


def main() -> None:
    ev = load_events()
    print(f"回测事件(出手触板): {len(ev)} 笔  覆盖 {ev['entry_date'].min().date()} ~ "
          f"{ev['entry_date'].max().date()}")

    first = load_first_touch(ev)
    first["date_str"] = pd.to_datetime(first["trade_date"]).dt.strftime("%Y-%m-%d")
    ev["date_str"] = pd.to_datetime(ev["entry_date"]).dt.strftime("%Y-%m-%d")
    m = ev.merge(first, left_on=["vt_symbol", "date_str"],
                 right_on=["vt_symbol", "date_str"], how="inner")
    print(f"分钟线覆盖: {len(m)} / {len(ev)} 笔 ({len(m)/len(ev)*100:.0f}%)"
          f"  [分钟库 2024-08-01~2026-08-12 关注池]")
    # 一字复核: 事件口径已排开盘>=limit, 分钟复核 09:31 开盘
    one_word = m[m["first_bar_open"] >= m["entry_price"] - 1e-6]
    if len(one_word):
        print(f"⚠️ 开盘即涨停(09:31 open>=limit) {len(one_word)} 笔——回测已排除口径,"
              f"此处应为0, 若>0需查: {list(one_word['name'][:5])}")

    m["bucket"] = m["touch_time"].apply(bucket_of)
    m = m.dropna(subset=["bucket"]).copy()
    m["year"] = pd.to_datetime(m["entry_date"]).dt.year
    m["good"] = m["ret_bw"] > 0

    print("\n== 全体 · 按首次触板时段(半小时) ==")
    print(stats_block(m, "bucket").to_string(index=False))

    print("\n== 好票 vs 差票 · 时段分布对照(组内占比%) ==")
    cross = pd.crosstab(m["bucket"], m["good"], normalize="columns") * 100
    cross.columns = ["差票组内%", "好票组内%"]
    cnt = pd.crosstab(m["bucket"], m["good"])
    cnt.columns = ["差票n", "好票n"]
    print(cross.join(cnt).round(1).to_string())

    print("\n== 粗四段(合并) ==")
    m["coarse"] = m["bucket"].map(COARSE)
    blk = stats_block(m, "coarse")
    print(blk.to_string(index=False))

    print("\n== 粗四段 × 分年(稳健性) ==")
    for seg, g in m.groupby("coarse"):
        line = f"{seg:16s} n={len(g):3d} |"
        for y, gy in g.groupby("year"):
            line += f" {y}: n={len(gy):3d} 均{gy['ret_bw'].mean()*100:+6.2f}"
        print(line)

    print("\n== 四组 × 粗四段(样本小,仅参考) ==")
    for gk, g in m.groupby("group_key"):
        line = f"{gk:7s} |"
        for seg in sorted(set(COARSE.values())):
            s = g[g["coarse"] == seg]
            line += f" {seg.split('①②③④⑤')[0] if False else seg[-11:]}: {len(s):3d}笔" \
                    + (f"/{s['ret_bw'].mean()*100:+.1f}" if len(s) else "  --")
        print(line)

    print("\n== 差票(top亏损)在各时段的分布(个体核查用) ==")
    worst = m.nsmallest(10, "ret_bw")
    print(worst[["name", "group_key", "entry_date", "bucket",
                 "ret_bw"]].assign(ret_bw=lambda d: (d["ret_bw"] * 100).round(2)
                   ).to_string(index=False))


if __name__ == "__main__":
    main()
