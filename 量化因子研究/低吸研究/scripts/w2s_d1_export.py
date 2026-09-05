# -*- coding: utf-8 -*-
"""导出2板系触板事件: 15m首触 × D+1收盘收益 ret_d1 × 板留 ret_bw(主人2026-09-05
'最佳区间=月均可交易笔数可观+D+1胜率收益可观'筛选用)."""
import sys
sys.path.insert(0, "/app")

import numpy as np
import pandas as pd

from alphaagent.server.services.weak_to_strong import backtest, repository


def main() -> None:
    T = backtest._build_events()
    s = T[T["touch"] & ~T["one_word"]].copy()
    s["g2"] = s["group_key"].replace({"yang2a": "yang2", "yang2b": "yang2"})
    s = s[s["g2"].isin(["yin2", "yang2"])].copy()
    s["ret_d1"] = s["n2_close"] / s["lim_px"] - 1          # D+1收盘(涨停则按收盘价)
    # 板留断走
    ncol = max(int(c.split("_")[0][1:]) for c in s.columns if c.endswith("_is_lim"))
    exit_px = pd.Series(np.nan, index=s.index)
    for k in range(2, ncol + 1):
        lim = s[f"n{k}_is_lim"].fillna(False).astype(bool)
        hit = exit_px.isna() & (~lim) & s[f"n{k}_close"].notna()
        exit_px[hit] = s.loc[hit, f"n{k}_close"]
    still = exit_px.isna() & s[f"n{ncol}_close"].notna()
    exit_px[still] = s.loc[still, f"n{ncol}_close"]
    s["ret_bw"] = exit_px / s["lim_px"] - 1
    tmap = repository.load_touch_map()
    s["touch"] = [tmap.get((str(v), d.date() if hasattr(d, "date") else d))
                  for v, d in zip(s["vt_symbol"], s["n1_date"])]
    out = s[s["touch"].notna()]
    out = out[["vt_symbol", "name", "g2", "n1_date", "touch", "seal", "ret_d1", "ret_bw"]]
    out = out.copy()
    out["n1_date"] = pd.to_datetime(out["n1_date"]).dt.strftime("%Y-%m-%d")
    out.to_csv("/tmp/w2s_d1.csv", index=False, encoding="utf-8-sig")
    print(f"导出 {len(out)} 笔 (2024-08后touch覆盖)")


if __name__ == "__main__":
    main()
