"""半小时时段 × +7% 直买 入场质量研究(用户 2026-08-26).

问题: 潜龙首板 A/B 分开, 用已有分钟数据(stock_minute_bars), 按「首次涨幅≥+7%
直接买」发生的半小时时段分桶, 统计 触板率/D+1溢价/连板率 哪个时段高.
对照: 现行 +8% 触发口径同表(能看出阈值差在哪个时段).

事件集 = 运行时 patch TRIGGER_PCT=0.07 后 build_events()(单一口径源; 含当日
最高只到 7~8% 的回落票——7% 口径完整模拟); sealed/streak_k/exit_px 为日线
属性与触发阈值无关,直接复用; entry 用分钟级(首触bar max(open,触发价)×1.005).
分钟: 该票当日有 1m 用 1m(2026-01-20~08-12), 否则 5m(2024-08-01 起);
首触 bar = 当日首条 high ≥ 昨收×阈值 的 bar, bar_time 归半小时桶.
D+1 = 次日开盘/入场-1(未含卖出滑点); ret = exit_px/入场-1(exit 沿用产品口径).
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
           "10:10-10:15", "10:15-10:20", "10:20-10:25", "10:25-10:30"]


def bucket_of(ts) -> int | None:
    """5 分钟桶, 只覆盖 09:30~10:30(黄金窗口内部结构); 窗外样本返回 None 不入桶."""
    t = ts.time()
    minutes = t.hour * 60 + t.minute
    if 570 <= minutes < 630:      # 09:30~10:30
        return (minutes - 570) // 5
    return None


def load_minute_events(keys: list[tuple[str, str]]) -> pd.DataFrame:
    """按 (vt_symbol, trade_date) 组合拉分钟 bar(1m 优先)."""
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
        return pd.read_sql(sql, conn, params=(syms, dates))


def main() -> None:
    pd.set_option("display.width", 200)

    # ── 7% 口径事件集(主) ──
    contracts.TRIGGER_PCT = 0.07
    ev7 = build_events()
    contracts.TRIGGER_PCT = 0.08
    ev8 = build_events()
    print(f"事件集: 7%口径 {len(ev7)} 笔   8%口径(现行) {len(ev8)} 笔")

    ev7 = ev7.dropna(subset=["exit_px"])
    keys = [(r.vt_symbol, r.trade_date.date().isoformat())
            for r in ev7[["vt_symbol", "trade_date"]].itertuples()]
    print(f"待定位分钟: {len(keys)} 组 (票,日)")
    minute = load_minute_events(keys)
    print(f"分钟 bar 拉取: {len(minute)} 行  "
          f"interval 构成: {minute['interval'].value_counts().to_dict()}  "
          f"日期范围 {minute['trade_date'].min()}~{minute['trade_date'].max()}")

    # 预计算两种触发价 映射回分钟
    trig = {}
    for r in ev7[["vt_symbol", "trade_date", "close_price_tm1"]].itertuples():
        key = (r.vt_symbol, pd.Timestamp(r.trade_date).date())
        trig[key] = float(r.close_price_tm1)

    rows = []
    minute["day"] = minute["trade_date"].apply(lambda d: d if not isinstance(d, str) else pd.Timestamp(d).date())
    for (vt, day), g in minute.groupby(["vt_symbol", "day"]):
        g = g.sort_values("bar_time")
        if (g["interval"] == "1m").any():
            g = g[g["interval"] == "1m"]
        pc = trig.get((vt, day))
        if pc is None:
            continue
        h = g["high_price"].values
        hit7 = np.where(h >= pc * 1.07)[0]
        if not len(hit7):
            continue
        i = hit7[0]
        bar = g.iloc[i]
        entry7 = max(float(bar["open_price"]), pc * 1.07) * 1.005
        rows.append({
            "vt_symbol": vt, "day": day,
            "bucket7": bucket_of(bar["bar_time"]), "entry7": entry7,
            "interval": bar["interval"],
        })
    touch = pd.DataFrame(rows)
    print(f"成功定位首触: {len(touch)}/{len(keys)}  "
          f"(未定位=分钟数据缺口或昨日收盘缺失)")

    ev7["day"] = ev7["trade_date"].apply(lambda t: t.date())
    m = ev7.merge(touch, on=["vt_symbol", "day"], how="inner")
    m["d1_7"] = m["open_p1"] / m["entry7"] - 1
    m["ret_7"] = m["exit_px"] / m["entry7"] - 1
    m = m[m["bucket7"].notna()]
    print(f"合并后样本 {len(m)} 笔\n")

    def _table(df: pd.DataFrame, tag: str) -> None:
        print(f"\n[{tag}] 时段 × A/B (D+1=次日开盘/入场-1; ret=产品exit口径)")
        for gname, gmask in [("A(含AB)", df["chassis_tag"].isin(["A", "AB"])),
                             ("B(含AB)", df["chassis_tag"].isin(["B", "AB"]))]:
            sub = df[gmask]
            base_n = len(sub)
            print(f"\n-- {gname} 基线(9:30-10:30 窗内): n={base_n} "
                  f"触板{sub['sealed'].mean() * 100:.1f}% "
                  f"连板{(sub['streak_k'] >= 2).mean() * 100:.1f}% "
                  f"D+1均{sub['d1_7'].mean() * 100:+.2f}% "
                  f"ret均{sub['ret_7'].mean() * 100:+.2f}% "
                  f"胜率{(sub['ret_7'] > 0).mean() * 100:.1f}%")
            print(f"{'时段':<12}{'n':>5}{'触板%':>7}{'连板%':>7}{'D+1均':>8}{'ret均':>8}{'胜率%':>7}")
            for b in range(12):
                gdf = sub[sub["bucket7"] == b]
                n = len(gdf)
                if n == 0:
                    print(f"{BUCKETS[b]:<12}{0:>5}")
                    continue
                print(f"{BUCKETS[b]:<12}{n:>5}{gdf['sealed'].mean() * 100:>7.1f}"
                      f"{(gdf['streak_k'] >= 2).mean() * 100:>7.1f}"
                      f"{gdf['d1_7'].mean() * 100:>8.2f}{gdf['ret_7'].mean() * 100:>8.2f}"
                      f"{(gdf['ret_7'] > 0).mean() * 100:>7.1f}")

    _table(m, "主口径: 首次触及 +7% 直买")

    # ── 8% 对照: 同一批分钟数据定位首触 8% 时刻 ──
    rows8 = []
    for (vt, day), g in minute.groupby(["vt_symbol", "day"]):
        g = g.sort_values("bar_time")
        if (g["interval"] == "1m").any():
            g = g[g["interval"] == "1m"]
        pc = trig.get((vt, day))
        if pc is None:
            continue
        h = g["high_price"].values
        hit = np.where(h >= pc * 1.08)[0]
        if not len(hit):
            continue
        bar = g.iloc[hit[0]]
        entry8 = max(float(bar["open_price"]), pc * 1.08) * 1.005
        t = bar["bar_time"].time()
        rows8.append({"vt_symbol": vt, "day": day,
                      "bucket8": bucket_of(bar["bar_time"]), "entry8": entry8,
                      "minutes8": t.hour * 60 + t.minute})
    t8 = pd.DataFrame(rows8)
    ev8c = ev8.dropna(subset=["exit_px"]).copy()
    ev8c["day"] = ev8c["trade_date"].apply(lambda t: t.date())
    m8_all = ev8c.merge(t8, on=["vt_symbol", "day"], how="inner")
    m8_all["d1_7"] = m8_all["open_p1"] / m8_all["entry8"] - 1
    m8_all["ret_7"] = m8_all["exit_px"] / m8_all["entry8"] - 1

    # ── 窗口级聚合(供 contracts.INTRADAY_WINDOWS stats;8% 口径, A/B 分开) ──
    print("\n[窗口级聚合] +8% 触发口径,按产品时段窗(A/B 分开)")
    WIN_RANGES = [("gold 09:30-09:50", 570, 590), ("fading 09:50-10:30", 590, 630),
                  ("weak 10:30-11:30", 630, 690), ("none 13:00-15:00", 780, 900)]
    print(f"{'窗口':<20}{'组':<8}{'n':>5}{'触板%':>7}{'连板%':>7}{'D+1均':>8}{'ret均':>8}")
    for wname, lo, hi in WIN_RANGES:
        wdf = m8_all[(m8_all["minutes8"] >= lo) & (m8_all["minutes8"] < hi)]
        for gname, gmask in [("A(含AB)", wdf["chassis_tag"].isin(["A", "AB"])),
                             ("B(含AB)", wdf["chassis_tag"].isin(["B", "AB"]))]:
            sub = wdf[gmask]
            if not len(sub):
                print(f"{wname:<20}{gname:<8}{0:>5}")
                continue
            print(f"{wname:<20}{gname:<8}{len(sub):>5}"
                  f"{sub['sealed'].mean() * 100:>7.1f}"
                  f"{(sub['streak_k'] >= 2).mean() * 100:>7.1f}"
                  f"{sub['d1_7'].mean() * 100:>8.2f}{sub['ret_7'].mean() * 100:>8.2f}")

    m8 = m8_all[m8_all["bucket8"].notna()].rename(columns={"bucket8": "bucket7"})
    _table(m8, "对照: 现行 +8% 触发(同一分钟数据)")


if __name__ == "__main__":
    main()
