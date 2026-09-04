# -*- coding: utf-8 -*-
"""N型补涨打板 · 首次触板时间分布研究(通达信15mK全市场版).

主人问题(2026-09-04): 好票/差票首次涨停时间分布 → 能否划分最佳打板时段.

数据路径(东财涨停池只留~11天/K线域被封锁后改走通达信):
  pytdx get_security_bars(category=1 15mK, 纯TCP 7709) —— 15m存档约8000根,
  覆盖 2024-08-15 起(全市场, 不限关注池). 日线(category=4)定位入场日偏移再精准拉页.
口径: 首次触板 = 入场日(D0)第一根 high >= 涨停价 的15mK周期结束时点
      (09:45=09:30-09:45那根). 涨停价=事件entry_price(信号日收盘×1.1, 未复权,
      通达信原始价同口径). 回测已排一字(开盘>=涨停价不入场).
好差票: 好=板留收益 ret_bw>0 / 差=ret_bw<=0.
输出: 统计打印 + 逐笔明细 N型补涨打板/首次触板时间.csv
"""
import sys
sys.path.insert(0, "/app")

import pandas as pd
from pytdx.hq import TdxHq_API
import socket

from alphaagent.server.services.weak_to_strong import backtest, contracts

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


def first_touch_for(api: TdxHq_API, vt: str, entry_day: str, limit_px: float) -> tuple[str, float] | None:
    """日线定位入场日偏移 → 拉15m页 → 返回(首触周期结束时点'HH:MM', 当日开盘价).

    pytdx 返回从旧到新排列; start=跳过最新N根取更旧. 故:
      back_idx = (len-1) - k  → 入场日距最新多少个交易日
      15m偏移 ≈ back_idx*16 (每交易日16根)
    """
    mkt, code = market_of(vt), code_of(vt)
    daily = api.get_security_bars(4, mkt, code, 0, 800)
    if not daily:
        return None
    k = next((i for i, b in enumerate(daily) if b["datetime"][:10] == entry_day), None)
    if k is None:
        return None          # 通达信无该日(停牌/数据缺失)
    back_idx = (len(daily) - 1) - k
    start = max(0, back_idx * 16 - 32)
    bars = []
    while start < back_idx * 16 + 48:
        chunk = api.get_security_bars(1, mkt, code, start, 800)
        if not chunk:
            break
        bars.extend(chunk)
        start += 800
    day_bars = sorted([b for b in bars if b["datetime"][:10] == entry_day],
                      key=lambda b: b["datetime"])
    if not day_bars:
        return None
    for b in day_bars:
        if b["high"] >= limit_px - 1e-3:
            return b["datetime"][11:16], float(day_bars[0]["open"])
    return None               # 当日15m无触板(理论不可能, 事件已筛 high>=limit)


BUCKETS = [
    ("09:30-10:00", "09:31", "10:15"),   # 15m周期结束时点: 09:45/10:00 两根
    ("10:00-10:30", "10:15", "10:45"),
    ("10:30-11:00", "10:45", "11:15"),
    ("11:00-11:30", "11:15", "11:31"),
    ("13:00-13:30", "13:15", "13:45"),
    ("13:30-14:00", "13:45", "14:15"),
    ("14:00-14:30", "14:15", "14:45"),
    ("14:30-15:00", "14:45", "15:01"),
]
COARSE = {
    "09:30-10:00": "①早盘9:30-10:00", "10:00-10:30": "②上午10:00-11:00",
    "10:30-11:00": "②上午10:00-11:00", "11:00-11:30": "③上午11:00-11:30",
    "13:00-13:30": "④午后13:00-14:00", "13:30-14:00": "④午后13:00-14:00",
    "14:00-14:30": "⑤尾盘14:00-15:00", "14:30-15:00": "⑤尾盘14:00-15:00",
}


def bucket_of(hm: str) -> str | None:
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
            "连板率%(res=连板)": round((g["exit_reason"] == "连板").mean() * 100, 1),
        })
    return pd.DataFrame(rows).sort_values(by)


BIG4 = {  # 阴阳×板高 2×2 大组(主人2026-09-04要求拆开看)
    "yin2": "2板阴", "yang2a": "2板阳", "yang2b": "2板阳",
    "yin4": "4+阴", "yang4": "4+阳",
}
YIN_YANG = {"2板阴": "阴系", "2板阳": "阳系", "4+阴": "阴系", "4+阳": "阳系"}
HEIGHT = {"2板阴": "2板系", "2板阳": "2板系", "4+阴": "4+系", "4+阳": "4+系"}
SEG_ORDER = ["①早盘9:30-10:00", "②上午10:00-11:00", "③上午11:00-11:30",
             "④午后13:00-14:00", "⑤尾盘14:00-15:00"]


def analyze(m: pd.DataFrame, from_csv: bool = False) -> None:
    m = m.copy()
    if "bucket" not in m.columns or m["bucket"].isna().all():
        m["bucket"] = m["touch"].apply(bucket_of)
        m = m.dropna(subset=["bucket"])
        m["coarse"] = m["bucket"].map(COARSE)
    m["year"] = pd.to_datetime(m["entry_day"]).dt.year
    m["good"] = m["ret_bw"] > 0
    m["big4"] = m["group_key"].map(BIG4)

    print("\n== 全体 · 按首次触板时段(半小时) ==")
    print(stats_block(m, "bucket").to_string(index=False))

    print("\n== 好票 vs 差票 · 时段分布(组内占比%) ==")
    cross = pd.crosstab(m["bucket"], m["good"], normalize="columns") * 100
    cross.columns = ["差票组内%", "好票组内%"]
    cnt = pd.crosstab(m["bucket"], m["good"])
    cnt.columns = ["差票n", "好票n"]
    print(cross.join(cnt).round(1).to_string())

    # ── 主人2026-09-04要求: 2板阴/2板阳/4板阴/4板阳 × 15分钟粒度 ──
    print("\n" + "=" * 100)
    print("== ① 四大组(2板阴/2板阳/4+阴/4+阳) × 15分钟粒度 (格= n|板留均%/好票率%) ==")
    print("=" * 100)
    bigs = ["2板阴", "2板阳", "4+阴", "4+阳"]
    times = sorted(m["touch"].unique())
    header = f"{'触板时刻':<8}" + "".join(f"{b:^24}" for b in bigs) + f"{'合计':^24}"
    print(header)
    for t in times:
        row = f"{t:<8}"
        for big in bigs + ["合计"]:
            s = m if big == "合计" else m[m["big4"] == big]
            s = s[s["touch"] == t]
            r = s["ret_bw"].dropna()
            if len(r):
                wr = (r > 0).mean() * 100
                row += f"{len(r):>3}|{r.mean()*100:+7.2f}/{wr:3.0f}%".rjust(24)
            else:
                row += f"{'--':^24}"
        print(row)
    for big in bigs:
        g = m[m["big4"] == big]
        r = g["ret_bw"].dropna()
        print(f"  {big} 合计: n={len(r)} 均{r.mean()*100:+.2f}% 好票率{(r>0).mean()*100:.1f}%")
    print("注: 时刻=15分钟K周期结束时点(09:45=09:30-09:45触板; 11:15=上午最后一根; 15:00=收盘)")

    print("\n== ② 阴系 vs 阳系 × 粗五段 ==")
    m["yy"] = m["big4"].map(YIN_YANG)
    for yy in ["阴系", "阳系"]:
        g = m[m["yy"] == yy]
        print(f"\n── {yy} (n={len(g)}) ──")
        blk = stats_block(g, "coarse")
        blk["n占比%"] = (blk["n"] / blk["n"].sum() * 100).round(1)
        print(blk.to_string(index=False))

    print("\n== ③ 2板系 vs 4+系 × 粗五段 ==")
    m["hh"] = m["big4"].map(HEIGHT)
    for hh in ["2板系", "4+系"]:
        g = m[m["hh"] == hh]
        print(f"\n── {hh} (n={len(g)}) ──")
        blk = stats_block(g, "coarse")
        blk["n占比%"] = (blk["n"] / blk["n"].sum() * 100).round(1)
        print(blk.to_string(index=False))

    print("\n== ④ 五细组各自 × 粗五段(完整) ==")
    for gk in contracts.GROUP_KEYS:
        g = m[m["group_key"] == gk]
        print(f"\n── {gk} · {BIG4[gk]} (n={len(g)}) ──")
        blk = stats_block(g, "coarse")
        blk["n占比%"] = (blk["n"] / blk["n"].sum() * 100).round(1)
        print(blk.to_string(index=False))

    print("\n== 粗五段 × 分年(稳健性) ==")
    for seg in SEG_ORDER:
        g = m[m["coarse"] == seg]
        line = f"{seg:18s} n={len(g):3d} |"
        for y, gy in g.groupby("year"):
            line += f"  {y}: n={len(gy):3d} 均{gy['ret_bw'].mean()*100:+6.2f}"
        print(line)

    print("\n== 各大组 × 粗五段 × 分年(稳健性) ==")
    for big in ["2板阴", "2板阳", "4+阴", "4+阳"]:
        for seg in SEG_ORDER:
            g = m[(m["big4"] == big) & (m["coarse"] == seg)]
            if not len(g):
                continue
            line = f"{big} {seg:18s} n={len(g):3d} |"
            for y, gy in g.groupby("year"):
                line += f"  {y}: n={len(gy):3d} 均{gy['ret_bw'].mean()*100:+6.2f}"
            print(line)

    print("\n== 差票 top10 亏损(个体核查) ==")
    worst = m.nsmallest(10, "ret_bw")
    worst = worst.assign(ret_pct=lambda d: (d["ret_bw"] * 100).round(2))
    print(worst[["name", "big4", "entry_day", "touch", "ret_pct"]].to_string(index=False))


def main() -> None:
    csv_path = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else None
    if csv_path:
        analyze(pd.read_csv(csv_path), from_csv=True)
        return
    T = backtest._build_events()
    frames = [backtest._trades_for(T[T["group_key"] == gk].copy())
              for gk in contracts.GROUP_KEYS]
    ev = pd.concat(frames, ignore_index=True)
    ev["entry_day"] = pd.to_datetime(ev["entry_date"]).dt.strftime("%Y-%m-%d")
    ev = ev[["vt_symbol", "name", "group_key", "entry_day", "entry_date",
             "entry_price", "ret_bw", "exit_reason", "seal", "open_g"]]
    print(f"回测事件: {len(ev)} 笔  {ev['entry_day'].min()} ~ {ev['entry_day'].max()}")

    api = TdxHq_API()
    connect(api)
    rows, fails = [], []
    for n, r in enumerate(ev.itertuples(), 1):
        try:
            got = first_touch_for(api, r.vt_symbol, r.entry_day, float(r.entry_price))
        except Exception:
            try:
                api = TdxHq_API(); connect(api)
                got = first_touch_for(api, r.vt_symbol, r.entry_day, float(r.entry_price))
            except Exception:
                got = None
        if got is None:
            fails.append((r.vt_symbol, r.entry_day))
            continue
        hm, day_open = got
        rows.append({"vt_symbol": r.vt_symbol, "name": r.name, "group_key": r.group_key,
                     "entry_day": r.entry_day, "touch": hm, "open": day_open,
                     "limit_px": float(r.entry_price), "ret_bw": float(r.ret_bw),
                     "exit_reason": r.exit_reason, "seal": bool(r.seal),
                     "open_g": float(r.open_g) if r.open_g == r.open_g else None})
        if n % 50 == 0:
            print(f"  进度 {n}/{len(ev)}  已取 {len(rows)}")
    m = pd.DataFrame(rows)
    print(f"\n通达信15m覆盖: {len(m)} / {len(ev)} 笔 ({len(m)/len(ev)*100:.0f}%)"
          f"  [15m存档2024-08-15起; 未覆盖多为更早事件]"
          + (f"; 失败重试仍未取到 {len(fails)} 笔" if fails else ""))

    # 一字复核: 15m首根开盘>=涨停价(回测已排, 应≈0)
    ow = m[m["open"] >= m["limit_px"] - 1e-3]
    if len(ow):
        print(f"⚠️ 当日首根15m开盘即≥涨停价 {len(ow)} 笔(回测口径应已排除,样本: "
              f"{list(ow['name'][:5])})——明细排查")

    m["bucket"] = m["touch"].apply(bucket_of)
    m = m.dropna(subset=["bucket"]).copy()
    m["coarse"] = m["bucket"].map(COARSE)
    analyze(m)

    out = "/app/w2s_touch_out.csv"
    m.drop(columns=["good"] if "good" in m.columns else []).to_csv(
        out, index=False, encoding="utf-8-sig")
    print(f"\n逐笔明细: {out}")


if __name__ == "__main__":
    main()
