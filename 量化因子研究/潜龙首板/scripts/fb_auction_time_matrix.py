"""竞价档 × 首5分钟时段 交叉矩阵(用户 2026-08-26): 帮用户识别「什么竞价开盘 ×
什么时间点, +7% 直买」的涨停概率/溢价概率.

样本 = 产品口径(v6.2 池, 高开≥8% 禁做保留) + TRIGGER_PCT patch 0.07 的 7% 触发
事件集 × 分钟可定位(1m 优先/5m 回补, 2025-06~2026-08 零散覆盖 916 组).
竞价档: 低开<0 / 0~2 / 2~4 / 4~6 / 6~8(激进, 接近禁做线).
时段: 09:30-10:30 每 5 分钟(12 桶) + 10:30后 + 午后(对照).
指标: n / 封板%(涨停概率) / D+1>0%(溢价概率) / D+1均 / ret均(产品exit口径).
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import psycopg

sys.path.insert(0, "/app")
from alphaagent.server.services.qianlong import contracts  # noqa: E402
from alphaagent.server.services.qianlong.backtest import build_events  # noqa: E402

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")

BUCKETS = ["09:30-09:35", "09:35-09:40", "09:40-09:45", "09:45-09:50",
           "09:50-09:55", "09:55-10:00", "10:00-10:05", "10:05-10:10",
           "10:10-10:15", "10:15-10:20", "10:20-10:25", "10:25-10:30",
           "10:30后", "午后"]
GAP_BINS = [-9.9, 0, 0.02, 0.04, 0.06, 0.08]
GAP_LABELS = ["低开<0%", "平开0~2%", "高开2~4%", "高开4~6%", "高开6~8%"]


def bucket_of(ts) -> int | None:
    t = ts.time()
    m = t.hour * 60 + t.minute
    if 570 <= m < 630:
        return (m - 570) // 5          # 0..11 黄金窗 5 分钟桶
    if 630 <= m < 690:
        return 12                       # 10:30-11:30
    if 780 <= m < 900:
        return 13                       # 13:00-15:00
    return None


def main() -> None:
    pd.set_option("display.width", 220)
    contracts.TRIGGER_PCT = 0.07
    ev = build_events()
    contracts.TRIGGER_PCT = 0.08
    ev = ev.dropna(subset=["exit_px"])
    keys = [(r.vt_symbol, r.trade_date.date().isoformat())
            for r in ev[["vt_symbol", "trade_date"]].itertuples()]
    syms = [k[0] for k in keys]
    dates = [k[1] for k in keys]
    sql = """
        SELECT m.vt_symbol, m.trade_date, m.bar_time, m.interval,
               m.open_price, m.high_price
        FROM stock_minute_bars m
        JOIN unnest(%s::text[], %s::date[]) AS k(vt_symbol, trade_date)
          ON m.vt_symbol = k.vt_symbol AND m.trade_date = k.trade_date
        WHERE m.interval IN ('1m', '5m')"""
    with psycopg.connect(DSN) as conn:
        minute = pd.read_sql(sql, conn, params=(syms, dates))
    minute["day"] = minute["trade_date"].apply(
        lambda d: d if not isinstance(d, str) else pd.Timestamp(d).date())
    trig = {}
    for r in ev[["vt_symbol", "trade_date", "close_price_tm1"]].itertuples():
        trig[(r.vt_symbol, pd.Timestamp(r.trade_date).date())] = float(r.close_price_tm1)

    rows = []
    for (vt, day), g in minute.groupby(["vt_symbol", "day"]):
        g = g.sort_values("bar_time")
        if (g["interval"] == "1m").any():
            g = g[g["interval"] == "1m"]
        pc = trig.get((vt, day))
        if pc is None:
            continue
        hit = np.where(g["high_price"].values >= pc * 1.07)[0]
        if not len(hit):
            continue
        bar = g.iloc[hit[0]]
        entry = max(float(bar["open_price"]), pc * 1.07) * 1.005
        rows.append({"vt_symbol": vt, "day": day, "bucket": bucket_of(bar["bar_time"]),
                     "entry7": entry})
    touch = pd.DataFrame(rows)
    ev["day"] = ev["trade_date"].apply(lambda t: t.date())
    m = ev.merge(touch, on=["vt_symbol", "day"], how="inner")
    m["d1"] = m["open_p1"] / m["entry7"] - 1
    m["ret7"] = m["exit_px"] / m["entry7"] - 1
    m = m[m["bucket"].notna()].copy()
    print(f"样本 {len(m)} 笔(7% 触发产品口径 × 分钟定位)\n")

    m["gap_bin"] = pd.cut(m["gap_open"], GAP_BINS, labels=GAP_LABELS)
    for gap_label in GAP_LABELS:
        sub = m[m["gap_bin"] == gap_label]
        if not len(sub):
            continue
        print(f"\n== 竞价 {gap_label}  基线: n={len(sub)} 封板{sub.sealed.mean()*100:.0f}% "
              f"D+1胜{(sub.d1 > 0).mean()*100:.0f}% ret{sub.ret7.mean()*100:+.2f}% ==")
        print(f"{'时段':<12}{'n':>4}{'封板%':>7}{'连板%':>7}{'D+1胜%':>8}{'D+1均':>8}{'ret均':>8}")
        for b in range(14):
            gdf = sub[sub["bucket"] == b]
            n = len(gdf)
            if n == 0:
                print(f"{BUCKETS[b]:<12}{0:>4}")
                continue
            print(f"{BUCKETS[b]:<12}{n:>4}{gdf.sealed.mean()*100:>7.1f}"
                  f"{(gdf.streak_k >= 2).mean()*100:>7.1f}"
                  f"{(gdf.d1 > 0).mean()*100:>8.1f}{gdf.d1.mean()*100:>8.2f}"
                  f"{gdf.ret7.mean()*100:>8.2f}")

    # 交叉汇总: 黄金窗(09:30-09:50)内 竞价×5分钟 的封板率热感
    print("\n== 汇总: 09:30-10:00 内 竞价档 × 5分钟 封板% (n) ==")
    print("(空格=样本不足3笔;行=竞价档,列=5分钟桶)")
    head = "竞价\\时段   " + "  ".join(f"{b[0:5]}" for b in BUCKETS[:6])
    print(head)
    for gap_label in GAP_LABELS:
        sub = m[(m["gap_bin"] == gap_label) & (m["bucket"] < 6)]
        cells = []
        for b in range(6):
            gdf = sub[sub["bucket"] == b]
            cells.append(f"{gdf.sealed.mean()*100:4.0f}%({len(gdf):<2d})" if len(gdf) >= 3 else "    -    ")
        print(f"{gap_label:<10}" + " ".join(cells))


if __name__ == "__main__":
    main()
