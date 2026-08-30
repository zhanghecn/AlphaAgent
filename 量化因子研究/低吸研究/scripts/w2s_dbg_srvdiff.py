# -*- coding: utf-8 -*-
"""服务侧 vs 研究侧 yin2 出手票集合差异诊断 + 共进股份 d23ok 个案."""
import sys

sys.path.insert(0, "/app")
import pandas as pd
from alphaagent.server.services.weak_to_strong import backtest as bt

# 研究侧出手票(库 csv)
ref = pd.read_csv("/app/v4_all.csv")
ref = ref[(ref["组"] == "2板补涨阴") & (ref["出手"] == True)]
ref_keys = set(zip(ref["vt_symbol"], ref["date"]))
print(f"研究侧 2板阴出手 {len(ref_keys)} 笔")

# 服务侧
T = bt._build_events()
T["sig_date"] = T["trade_date"].dt.strftime("%Y-%m-%d")
T["d0_date"] = T["n1_date"].dt.strftime("%Y-%m-%d")
yin2 = T[(T["group_key"] == "yin2") & T["actionable"] & T["touch"] & ~T["one_word"]].copy()
srv_keys = set(zip(yin2["vt_symbol"], yin2["d0_date"]))
print(f"服务侧 yin2 出手 {len(srv_keys)} 笔 (锚123, diff={len(srv_keys)-123})")

only_ref = ref_keys - srv_keys
only_srv = srv_keys - ref_keys
print(f"研究有服务无 {len(only_ref)} | 服务有研究无 {len(only_srv)}")
for k in sorted(only_srv)[:8]:
    print("  服务多出:", k)
for k in sorted(only_ref)[:8]:
    print("  研究多出:", k)

# 抽样深挖: 研究有服务无的前3笔 —— 查服务侧事件帧里该票当天的状态
for vt, d0 in sorted(only_ref)[:5]:
    sub = T[(T["vt_symbol"] == vt) & (T["d0_date"] == d0)]
    if not len(sub):
        print(f"  {vt} {d0}: 服务侧事件帧无此行(未触板/非一字/无n1/未触发基本条件)")
        # 看未过 touch 还是基本条件
        continue
    r = sub.iloc[0]
    print(f"  {vt} {d0}: actionable={r['actionable']} touch={r['touch']} one_word={r['one_word']} "
          f"base={r['u_base']} gap={r['gap_d0']} reb={r['reb']:.3f} topped={r['topped']} "
          f"low_dd={r['low_dd']:.3f} pull={r['pull']:.3f} pos3={r['pos3']}")

# 共进股份个案
print("\n共进股份 603118 2026-08:")
sub = T[(T["vt_symbol"] == "603118.SSE")
        & (T["trade_date"] >= "2026-07-28") & (T["trade_date"] <= "2026-08-05")]
for r in sub.itertuples():
    print(f"  T-1={r.trade_date.date()} grp={r.group_key} act={r.actionable} "
          f"d23ok={r.d23ok} base={r.u_base} ma={r.ma_st} topped={r.topped} "
          f"touch={r.touch} ow={r.one_word}")
# 逐日还原 d23ok 的输入
from datetime import date as _date
from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine
from sqlalchemy import select
bars = pd.read_sql(
    select(schema.stock_daily_bars.c.vt_symbol,
           schema.stock_daily_bars.c.trade_date,
           schema.stock_daily_bars.c.open_price,
           schema.stock_daily_bars.c.high_price,
           schema.stock_daily_bars.c.low_price,
           schema.stock_daily_bars.c.close_price)
    .where(schema.stock_daily_bars.c.vt_symbol == "603118.SSE",
           schema.stock_daily_bars.c.trade_date >= _date(2026, 7, 24),
           schema.stock_daily_bars.c.trade_date <= _date(2026, 8, 6)),
    get_engine(), parse_dates=["trade_date"]).sort_values("trade_date")
from alphaagent.server.services.weak_to_strong import pool as pool_mod
bars = pool_mod.derive_daily(bars)
for r in bars.itertuples():
    print(f"  {r.trade_date.date()} 收{r.close_price:.2f} 阳={r.yang} 板={r.is_lim} streak={r.streak}")

# 000062 深挖: 锚为何在 399 天前
print("\n000062.SZSE 2026-04~05 逐日:")
b2 = pd.read_sql(
    select(schema.stock_daily_bars.c.vt_symbol,
           schema.stock_daily_bars.c.trade_date,
           schema.stock_daily_bars.c.open_price,
           schema.stock_daily_bars.c.high_price,
           schema.stock_daily_bars.c.low_price,
           schema.stock_daily_bars.c.close_price)
    .where(schema.stock_daily_bars.c.vt_symbol == "000062.SZSE",
           schema.stock_daily_bars.c.trade_date >= _date(2026, 4, 1),
           schema.stock_daily_bars.c.trade_date <= _date(2026, 5, 12)),
    get_engine(), parse_dates=["trade_date"]).sort_values("trade_date")
b2 = pool_mod.derive_daily(b2)
for r in b2.itertuples():
    print(f"  {r.trade_date.date()} 收{r.close_price:.2f} 板={r.is_lim} streak={r.streak} mx20={r.mx20}")

# 对照 detector 口径(stock_limit_up_daily)——研究侧可能用 detector 而非浮点
lu = pd.read_sql(
    select(schema.stock_limit_up_daily.c.trade_date,
           schema.stock_limit_up_daily.c.is_limit_up)
    .where(schema.stock_limit_up_daily.c.vt_symbol == "000062.SZSE",
           schema.stock_limit_up_daily.c.trade_date >= _date(2026, 4, 1),
           schema.stock_limit_up_daily.c.trade_date <= _date(2026, 5, 12)),
    get_engine(), parse_dates=["trade_date"]).sort_values("trade_date")
print("  detector口径涨停日:", [str(d.date()) for d in lu[lu["is_limit_up"]]["trade_date"]])
