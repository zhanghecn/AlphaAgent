# -*- coding: utf-8 -*-
"""N型 · 首触板时间 5分钟细分(主人2026-09-05要求: 15m甜区再切三格看).

pytdx 5mK(category=0, 每天48根) 重新定位首触时刻, 样本=首次触板时间-全量.csv 的
2板系(阴/阳)触板事件. 5m存档深度待实测(15m约8000根=2024-08起, 5m同档位数覆盖更短,
脚本报告实际覆盖窗口). 口径同15m版: 首触=入场日第一根 high>=涨停价 的5mK末刻.

容器内跑: docker cp 脚本+CSV 后 python w2s_limit_time_5m.py <csv>
"""
import socket
import sys

import pandas as pd
from pytdx.hq import TdxHq_API

socket.setdefaulttimeout(8)
TDX_HOSTS = ["115.238.56.198", "123.125.108.14", "60.12.136.250", "218.75.126.9"]


def connect(api: TdxHq_API) -> TdxHq_API:
    for h in TDX_HOSTS:
        try:
            if api.connect(h, 7709, time_out=8):
                return api
        except Exception:
            continue
    raise RuntimeError("所有通达信节点连接失败")


def market_of(vt: str) -> int:
    return 0 if vt.endswith(".SZSE") else 1


def code_of(vt: str) -> str:
    return vt.split(".")[0]


def first_touch_5m(api: TdxHq_API, vt: str, entry_day: str, limit_px: float) -> str | None:
    """日线定位 → 拉5m页(每天48根) → 首根 high>=涨停价 的5mK末刻'HH:MM'."""
    mkt, code = market_of(vt), code_of(vt)
    daily = api.get_security_bars(4, mkt, code, 0, 800)
    if not daily:
        return None
    k = next((i for i, b in enumerate(daily) if b["datetime"][:10] == entry_day), None)
    if k is None:
        return None
    back_idx = (len(daily) - 1) - k
    if back_idx * 48 > 60000:   # 5m存档外的老事件, 不浪费请求
        return None
    start = max(0, back_idx * 48 - 48)
    chunk = api.get_security_bars(0, mkt, code, start, 800)  # 800根≈16天, 足含当日全天
    if not chunk:
        return None
    day_bars = sorted([b for b in chunk if b["datetime"][:10] == entry_day],
                      key=lambda b: b["datetime"])
    for b in day_bars:
        if b["high"] >= limit_px - 1e-3:
            return b["datetime"][11:16]
    return None


def main() -> None:
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/首次触板时间-全量.csv"
    df = pd.read_csv(csv_path, dtype={"vt_symbol": str})
    df["g2"] = df["group_key"].replace({"yang2a": "yang2", "yang2b": "yang2"})
    ev = df[df["g2"].isin(["yin2", "yang2"])].drop_duplicates(
        subset=["vt_symbol", "entry_day"]).copy()
    print(f"2板系触板事件: {len(ev)} 笔")

    api = TdxHq_API()
    connect(api)
    rows, fails = [], 0
    for n, r in enumerate(ev.itertuples(), 1):
        try:
            hm = first_touch_5m(api, r.vt_symbol, r.entry_day, float(r.entry_price))
        except Exception:
            try:
                api = TdxHq_API(); connect(api)
                hm = first_touch_5m(api, r.vt_symbol, r.entry_day, float(r.entry_price))
            except Exception:
                hm = None
        if hm is None:
            fails += 1
        else:
            rows.append({"vt_symbol": r.vt_symbol, "g2": r.g2, "entry_day": r.entry_day,
                         "touch": hm, "ret_bw": float(r.ret_bw)})
        if n % 300 == 0:
            print(f"  进度 {n}/{len(ev)}  已取 {len(rows)}")
    m = pd.DataFrame(rows)
    cov = f"{m['entry_day'].min()}~{m['entry_day'].max()}" if len(m) else "无"
    print(f"\n5m覆盖: {len(m)} / {len(ev)} 笔 ({len(m)/len(ev)*100:.0f}%)  窗口 {cov}  未取到 {fails}")

    m["year"] = pd.to_datetime(m["entry_day"]).dt.year
    m.to_csv("/tmp/w2s_touch_5m.csv", index=False, encoding="utf-8-sig")

    EDGES = ["09:35", "09:40", "09:45", "09:50", "09:55", "10:00", "10:05", "10:10",
             "10:15", "10:20", "10:25", "10:30", "10:35", "10:40", "10:45", "10:50",
             "10:55", "11:00", "11:05", "11:10", "11:15", "11:20", "11:25", "11:30",
             "13:05", "13:10", "13:15", "13:20", "13:25", "13:30", "13:35", "13:40",
             "13:45", "13:50", "13:55", "14:00", "14:05", "14:10", "14:15", "14:20",
             "14:25", "14:30", "14:35", "14:40", "14:45", "14:50", "14:55", "15:00"]
    PREV = {EDGES[0]: "09:30"}
    for a, b in zip(EDGES, EDGES[1:]):
        PREV[b] = a
    PREV["13:05"] = "13:00"

    for gk, name in [("yin2", "2板阴"), ("yang2", "2板阳")]:
        g = m[m["g2"] == gk]
        print(f"\n===== {name} × 5分钟桶 (n|均值%|胜率%|中位%) =====")
        for t in EDGES:
            x = g[g["touch"] == t]
            if not len(x):
                continue
            r5 = x["ret_bw"] * 100
            ny = sum(1 for _, xx in x.groupby("year") if xx["ret_bw"].mean() < 0)
            print(f"{PREV[t]}~{t}  n={len(x):>3}  {r5.mean():+6.2f}  {(r5>0).mean()*100:3.0f}%  {r5.median():+6.2f}  负年{ny}")
        r5 = g["ret_bw"] * 100
        print(f"  合计 n={len(g)} 均{r5.mean():+.2f} 胜率{(r5>0).mean()*100:.0f}%")


if __name__ == "__main__":
    main()
