# -*- coding: utf-8 -*-
"""w2s A1/A2/B 半小时时段 × 首触 +7% 直买 统计(主人 2026-08-26).

问题: 按盘中「首次涨幅≥+7%」发生的半小时时段分桶, 统计当日封板率(连板概率)/
D+1 溢价/产品口径收益, 让用户知道什么时间打比较好。

口径:
- 事件 = 产品口径池(w2s-v3.0): A1/A2 +竞价0~4 +大盘停手; B 仅停手。
  三组触发放宽为统一 reach7(当日 high≥昨收×1.07 且 low≤昨收×1.07 排一字),
  A2 另附产品 +9% 基线对照。
- 分钟定位(n1=触发日): 1m 优先(2026-01-20 后), 否则 5m(2024-08-01 起);
  首触 bar = 当日首条 high ≥ 昨收×1.07 的 bar, bar_time(起点)归半小时桶。
- entry = max(bar开盘, 昨收×1.07)×1.005(含滑点, 同潜龙口径);
  D+1 溢价 = n2开盘/entry-1; 连板概率 = 当日封板(n1收盘涨停)%;
  次日再板 = n2涨停%; 产品ret = A2未封当日收盘卖/封板及A1/B板留断走。

用法(容器内, 依赖 /tmp/w2s_replay.py):
    docker cp 本文件 <api容器>:/tmp/ ; docker exec ... python /tmp/w2s_halfhour_entry.py
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import os

import numpy as np
import pandas as pd
import psycopg

# 复用研究侧单一口径源(w2s_replay.py), 避免 build_events/split_groups/board_walk_ret 抄写漂移
_spec = importlib.util.spec_from_file_location("w2s_replay", "/tmp/w2s_replay.py")
w2s = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(w2s)

DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")

BUCKETS = ["09:30-10:00", "10:00-10:30", "10:30-11:00", "11:00-11:30",
           "13:00-13:30", "13:30-14:00", "14:00-14:30", "14:30-15:00"]

BUCKETS5 = [f"09:{m:02d}-{f'09:{m+5:02d}' if m + 5 < 60 else '10:00'}" for m in range(30, 60, 5)] + \
           [f"10:{m:02d}-10:{m+5:02d}" for m in range(0, 30, 5)]   # 5 分钟桶,只覆盖 09:30~10:30

# 竞价档(开盘 gap);A1/A2 产品门禁 0~4%,B 无门禁全域
GAP_BINS = [-99, 0, 1, 2, 3, 4, 99]
GAP_LABELS = ["低开<0%", "0~1%", "1~2%", "2~3%", "3~4%", "高开≥4%"]


def bucket_of(ts) -> int | None:
    """半小时桶 0..7(全天); 盘前/午休等窗外返回 None."""
    t = ts if isinstance(ts, dt.time) else ts.time()
    m = t.hour * 60 + t.minute
    if 570 <= m < 690:            # 09:30 ~ 11:30
        return (m - 570) // 30
    if 780 <= m < 900:            # 13:00 ~ 15:00
        return 4 + (m - 780) // 30
    return None


def bucket5_of(ts) -> int | None:
    """5 分钟桶 0..11, 只覆盖 09:30~10:30(黄金窗口内部结构); 窗外 None."""
    t = ts if isinstance(ts, dt.time) else ts.time()
    m = t.hour * 60 + t.minute
    if 570 <= m < 630:
        return (m - 570) // 5
    return None


def n1_dates(conn, pairs: list[tuple[str, str]]) -> dict[tuple[str, str], dt.date]:
    """(vt_symbol, 特征日) → 次一交易日(n1) 日期, 日线 LEAD 窗口(与事件 n1_ 列同源)."""
    syms = [p[0] for p in pairs]     # 与 dates 等长配对(unnest 双数组按位对齐, 不能去重)
    dates = [p[1] for p in pairs]
    sql = """
        SELECT vt_symbol, trade_date, n1_date FROM (
            SELECT vt_symbol, trade_date,
                   LEAD(trade_date) OVER (PARTITION BY vt_symbol ORDER BY trade_date) AS n1_date
            FROM stock_daily_bars
            WHERE vt_symbol = ANY(%s) AND trade_date >= DATE '2023-03-01'
        ) t WHERE (vt_symbol, trade_date) IN (
            SELECT * FROM unnest(%s::text[], %s::date[]))"""
    df = pd.read_sql(sql, conn, params=(syms, syms, dates))
    # key 统一 Timestamp(与 T.trade_date 同型, date/Timestamp 哈希不同否则永远 miss)
    return {(r.vt_symbol, pd.Timestamp(r.trade_date)): r.n1_date for r in df.itertuples()}


def load_minute(conn, keys: list[tuple[str, dt.date]]) -> pd.DataFrame:
    syms = [k[0] for k in keys]
    dates = [k[1] for k in keys]
    sql = """
        SELECT m.vt_symbol, m.trade_date, m.bar_time, m.interval,
               m.open_price, m.high_price
        FROM stock_minute_bars m
        JOIN unnest(%s::text[], %s::date[]) AS k(vt, d)
          ON m.vt_symbol = k.vt AND m.trade_date = k.d
        WHERE m.interval IN ('1m', '5m')"""
    return pd.read_sql(sql, conn, params=(syms, dates))


def first_touch(minute: pd.DataFrame, trig: dict, pct: float) -> pd.DataFrame:
    """每组(票,日): 首条 high≥昨收×pct 的分钟 bar → 桶/entry."""
    rows = []
    for (vt, day), g in minute.groupby(["vt_symbol", "trade_date"]):
        g = g.sort_values("bar_time")
        if (g["interval"] == "1m").any():
            g = g[g["interval"] == "1m"]
        pc = trig.get((vt, day))
        if pc is None:
            continue
        hit = np.where(g["high_price"].values >= pc * (1 + pct))[0]
        if not len(hit):
            continue
        bar = g.iloc[hit[0]]
        rows.append({"vt_symbol": vt, "n1_day": day,
                     "bucket": bucket_of(bar["bar_time"]),
                     "b5": bucket5_of(bar["bar_time"]),
                     "entry": max(float(bar["open_price"]), pc * (1 + pct)) * 1.005,
                     "ivl": bar["interval"]})
    return pd.DataFrame(rows)


def group_table(e: pd.DataFrame, label: str) -> None:
    print(f"\n== {label} ==")
    if len(e) == 0:
        print("n=0")
        return

    def _row(df: pd.DataFrame) -> str:
        n = len(df)
        if n == 0:
            return f"{n:>4}"
        return (f"{n:>4} {df['seal'].mean()*100:>5.1f}% {df['d1'].mean()*100:>+7.2f}% "
                f"{(df['d1']>0).mean()*100:>5.1f}% {df['n2_lim'].mean()*100:>5.1f}% "
                f"{df['ret'].mean()*100:>+7.2f}% {(df['ret']>0).mean()*100:>5.1f}%")

    head = f"{'时段':<12}{'n':>4}{'封板%':>7}{'D+1均':>9}{'D+1胜':>7}{'再板%':>7}{'ret均':>9}{'ret胜':>7}"
    print(f"{'全部':<12}{_row(e)}")
    print(head)
    for b, name in enumerate(BUCKETS):
        print(f"{name:<12}{_row(e[e['bucket'] == b])}")
    by = e.groupby("bucket").agg(n=("ret", "size"), ret=("ret", "mean"), d1=("d1", "mean"))
    if len(by) > 1:
        best = by["ret"].idxmax()
        print(f"  ↳ ret 最高时段 {BUCKETS[int(best)]}: n={int(by.loc[best,'n'])} "
              f"ret均{by.loc[best,'ret']*100:+.2f}%  D+1均{by.loc[best,'d1']*100:+.2f}%")


def build_frame(T, mask, gk, touch, trig_key) -> pd.DataFrame:
    """事件行 × 分钟首触定位 → 统计行(group/bucket/seal/n2_lim/d1/ret)."""
    frames = []
    if not len(touch):
        return pd.DataFrame(frames)
    for r in T[mask].itertuples():
        e = T.loc[[r.Index]]
        loc = touch[(touch["vt_symbol"] == r.vt_symbol) & (touch["n1_day"] == trig_key(r))]
        if not len(loc) or pd.isna(loc.iloc[0]["bucket"]) or pd.isna(r.n2_open):
            continue
        entry = float(loc.iloc[0]["entry"])
        bw = w2s.board_walk_ret(e, pd.Series([entry], index=e.index))
        if gk == "a2" and not bool(r.seal):
            ret = r.n1_close / entry - 1          # A2 未封当日收盘卖
        else:
            ret = float(bw.iloc[0])               # 封板及 A1/B 板留断走
        frames.append({"group": gk, "bucket": int(loc.iloc[0]["bucket"]),
                       "b5": loc.iloc[0]["b5"],
                       "gap": (r.open_g if pd.notna(r.open_g) else np.nan) * 100,
                       "seal": bool(r.seal), "n2_lim": bool(r.n2_lim),
                       "d1": r.n2_open / entry - 1, "ret": ret})
    return pd.DataFrame(frames)


def dim_table(e: pd.DataFrame, dimcol: str, names: list[str], tag: str) -> None:
    """通用单维分桶表: 行=档位(dimcol 整数索引/NaN), 每组一段。"""
    print(f"\n== {tag} ==")
    for gk in ("a1", "a2", "b"):
        sub = e[(e["group"] == gk) & e[dimcol].notna()]
        if not len(sub):
            continue
        print(f"-- {gk.upper()} (n={len(sub)})  {'档位':<10}{'n':>4}{'封板%':>7}"
              f"{'D+1均':>8}{'D+1胜':>7}{'再板%':>7}{'ret均':>8}{'ret胜':>7}")
        for i, name in enumerate(names):
            r = sub[sub[dimcol] == i]
            n = len(r)
            if n == 0:
                print(f"{name:<14}{n:>4}")
                continue
            print(f"{name:<14}{n:>4}{r['seal'].mean()*100:>7.1f}"
                  f"{r['d1'].mean()*100:>+8.2f}{(r['d1']>0).mean()*100:>7.1f}"
                  f"{r['n2_lim'].mean()*100:>7.1f}{r['ret'].mean()*100:>+8.2f}"
                  f"{(r['ret']>0).mean()*100:>7.1f}")


def main() -> None:
    pd.set_option("display.width", 200)
    T = w2s.build_events(w2s.create_engine(os.environ["DATABASE_URL"]))
    groups = w2s.split_groups(T)
    print(f"规则版本 {w2s.RULES_VERSION}  事件池 {len(T)} 票日  触发统一=+7%(A2另附产品+9%基线)")

    auction = T["open_g"].between(0.0, 0.04)
    halt = T["mkt_lim"] <= 110
    masks = {   # 产品池 × 统一 reach7(A1/B 本就 reach7; A2 由 reach9 放宽, 用户 7% 直打视角)
        "a1": groups["a1"] & T["reach7"] & auction & halt,
        "a2": groups["a2"] & T["reach7"] & auction & halt,
        "b": groups["b"] & T["reach7"] & halt,
    }
    a2_prod = groups["a2"] & T["reach9"] & auction & halt

    need = pd.concat([T[a2_prod], T[masks["b"]], T[masks["a2"]], T[masks["a1"]]]).drop_duplicates(
        subset=["vt_symbol", "trade_date"])
    pairs = [(r.vt_symbol, r.trade_date.date().isoformat()) for r in need.itertuples()]
    with psycopg.connect(DSN) as conn:
        n1 = n1_dates(conn, pairs)
        trig, feats = {}, []
        for r in need.itertuples():
            d1 = n1.get((r.vt_symbol, r.trade_date))
            if d1 is None:
                continue
            trig[(r.vt_symbol, d1)] = float(r.close_price)          # n1 昨收 = T日收盘
            feats.append((r.vt_symbol, r.trade_date, d1))
        minute = load_minute(conn, sorted(trig.keys()))
    print(f"待定位: {len(feats)} 组(票,特征日) → 触发日分钟 {len(trig)} 个")
    if len(minute):
        print(f"分钟 bar {len(minute)} 行  interval={minute['interval'].value_counts().to_dict()}  "
              f"覆盖 {minute['trade_date'].min()}~{minute['trade_date'].max()}")
    touch7 = first_touch(minute, trig, 0.07)
    touch9 = first_touch(minute, trig, 0.09)
    print(f"首触+7% 定位 {len(touch7)}/{len(trig)}  首触+9% 定位 {len(touch9)}/{len(trig)}"
          f"  (缺口=无分钟数据或未触)")

    key7 = lambda r: n1.get((r.vt_symbol, r.trade_date))   # noqa: E731
    all7 = []
    for gk, label in (("a1", "A1(产品池, 触7直买)"), ("a2", "A2(产品池, 触7直买口径)"),
                      ("b", "B(产品池, 触7直买)")):
        m = build_frame(T, masks[gk], gk, touch7, key7)
        print(f"\n入表 {gk.upper()}: {len(m)} 笔 (分钟定位成功 × 全天桶内 × n2有数据)")
        group_table(m, label)
        all7.append(m)
    m9 = build_frame(T, a2_prod, "a2", touch9, key7)
    group_table(m9, "A2 产品口径对照(触+9%直买)")

    # ── 竞价档 × 首触5分钟桶(用户 2026-08-26 追加: 什么情况下/什么时间点打) ──
    allm = pd.concat(all7, ignore_index=True)
    gd = allm.dropna(subset=["gap"]).copy()
    gd["gapbin"] = np.digitize(gd["gap"], [0, 1, 2, 3, 4])
    dim_table(gd, "gapbin", GAP_LABELS, "竞价档 × 组 (开盘gap; A1/A2 门禁0~4, B 全域)")
    b5 = allm.copy()
    dim_table(b5, "b5", BUCKETS5, "首触5分钟桶 × 组 (只覆盖 09:30~10:30 黄金窗口)")
    print("\n列义: 封板%=当日封死即连板概率  D+1=次日开盘/entry-1(隔夜溢价)  "
          "再板%=次日继续涨停  ret=产品口径卖出(A2未封当日卖/其余板留断走)")
    iv = touch7["ivl"].value_counts().to_dict() if len(touch7) else {}
    print(f"首触 bar 构成: {iv}  (1m=2026-01-20后精确, 5m=2024-08起起点归桶)")


if __name__ == "__main__":
    main()
