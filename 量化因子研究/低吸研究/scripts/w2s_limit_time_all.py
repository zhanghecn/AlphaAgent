# -*- coding: utf-8 -*-
"""N型补涨打板 · 首触板时间分布(全量口径)——主人2026-09-04定调:
「不用管白名单,N型好票坏票都算上,做个真实的统计」.

口径=触发池全量×真触板×非一字(≈3744笔,与好差票验证库同基):
  好票/差票=板留(ret_bw)正负,不再按白名单过滤——统计的是
  「雷达看到的全部触板事件」的时间结构,不是「战法出手」的.
拉取=pytdx通达信15mK(存档2024-08-15起,窗口内全市场);
  增量复用出手口径缓存 /app/w2s_touch_out.csv(246笔),只拉缺失.
统计复用 w2s_limit_time_tdx.analyze(四大组×15分钟区间等全部分析).
"""
import sys
sys.path.insert(0, "/app")

import pandas as pd

from alphaagent.server.services.weak_to_strong import backtest, contracts
from w2s_limit_time_tdx import (TDX_HOSTS, analyze, connect, first_touch_for)
from pytdx.hq import TdxHq_API


def load_all_events() -> pd.DataFrame:
    """触发池全量×触板×非一字 → 板留结果(好差票都算)."""
    T = backtest._build_events()
    T2 = T[T["touch"] & ~T["one_word"]].copy()   # 全量触板事件(不管白名单)
    T2["actionable"] = True                      # 放开白名单过滤
    frames = [backtest._trades_for(T2[T2["group_key"] == gk].copy())
              for gk in contracts.GROUP_KEYS]
    t = pd.concat(frames, ignore_index=True)
    return t[["vt_symbol", "name", "group_key", "entry_date", "entry_price",
              "ret_bw", "seal", "open_g", "exit_reason"]].copy()


def main() -> None:
    ev = load_all_events()
    ev["entry_day"] = pd.to_datetime(ev["entry_date"]).dt.strftime("%Y-%m-%d")
    print(f"全量触板事件(不管白名单): {len(ev)} 笔  {ev['entry_day'].min()} ~ {ev['entry_day'].max()}")

    # 增量缓存: 出手口径已拉的246笔直接复用
    cache: dict[tuple[str, str], tuple[str, float]] = {}
    try:
        old = pd.read_csv("/app/w2s_touch_out.csv", dtype={"vt_symbol": str})
        for r in old.itertuples():
            cache[(r.vt_symbol, r.entry_day)] = (str(r.touch), float(r.open))
        print(f"缓存命中基座: {len(cache)} 笔(出手口径)")
    except FileNotFoundError:
        pass

    rows, misses = [], []
    api = TdxHq_API()
    connect(api)
    todo = [(r.vt_symbol, r.entry_day, float(r.entry_price)) for r in ev.itertuples()]
    for n, (vt, day, lim) in enumerate(todo, 1):
        got = cache.get((vt, day))
        if got is None:
            try:
                got = first_touch_for(api, vt, day, lim)
            except Exception:
                try:
                    api = TdxHq_API(); connect(api)
                    got = first_touch_for(api, vt, day, lim)
                except Exception:
                    got = None
        if got is None:
            misses.append((vt, day))
            continue
        hm, day_open = got
        rows.append({"vt_symbol": vt, "entry_day": day, "touch": hm, "open": day_open})
        if n % 200 == 0:
            print(f"  进度 {n}/{len(todo)}  已取 {len(rows)}")

    touch_df = pd.DataFrame(rows)
    print(f"\n触板时间覆盖: {len(touch_df)} / {len(ev)} 笔"
          f" ({len(touch_df)/len(ev)*100:.0f}%)  [15m存档2024-08-15起]"
          + (f"; 未取到 {len(misses)} 笔" if misses else ""))

    m = ev.merge(touch_df, on=["vt_symbol", "entry_day"], how="inner")
    # 同票同日唯一(entry_day==touch 行的 day); 防重复行
    m = m.drop_duplicates(subset=["vt_symbol", "entry_day"])
    m = m.rename(columns={"entry_day": "entry_day"})
    analyze(m)
    m.to_csv("/app/w2s_touch_all.csv", index=False, encoding="utf-8-sig")
    print(f"\n全量逐笔明细: /app/w2s_touch_all.csv")


if __name__ == "__main__":
    main()
