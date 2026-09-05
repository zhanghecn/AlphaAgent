# -*- coding: utf-8 -*-
"""N型补涨打板 · 连板延续研究(多拿一天)——主人2026-09-05命题:
「2板阴阳 4板阴阳 什么形态下连板几率最高 最高到几板,按MA10/20/30+量能+涨停时间段多维分析,
让用户知道什么时刻可以多拿一天」.

口径=触发池全量×触板×非一字(与首触时间研究同基,好票坏票都算):
  高度h = D0起连续涨停天数(D0炸板=0,15m/日线全期,22日截断)
  seal  = h>=1  D0封板率(触板→收住)
  a1    = h>=2  D+1再板率 = 多拿一天
  a2    = h>=3  接力2进3
  [封住]子集内 P(h>=2) = 真正"持过夜后多拿一天"成功率
自变量(决策时点=D0收盘后,全部合法无未来函数):
  MA   = D0收盘 ma10/20/30 排列串st3 + bias(D0收/MA-1)
  量能 = vr_d0(D0量/前5日均量)、vr_tm1(D-1量比)
  时间 = D0首触板(DB w2s_touch_times,2024-08-15起)四段+15m细桶

容器内跑: docker cp 进 api 后 python w2s_streak_odds.py
"""
import sys
sys.path.insert(0, "/app")

import numpy as np
import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine
from alphaagent.server.services.weak_to_strong import backtest, contracts, repository

GNAME = {"yin2": "2板阴", "yang2": "2板阳", "yin4": "4+阴", "yang4": "4+阳"}

# 时间四段(15m末刻 hh:mm)
def seg_of(hhmm: str) -> str:
    m = int(hhmm[:2]) * 60 + int(hhmm[3:5])
    if m <= 10 * 60 + 30:
        return "早09:30~10:30"
    if m <= 11 * 60 + 30:
        return "中10:30~11:30"
    if m <= 14 * 60:
        return "午13:00~14:00"
    return "尾14:00~15:00"


def build_sample() -> pd.DataFrame:
    T = backtest._build_events()
    s = T[T["touch"] & ~T["one_word"]].copy()
    s["g4"] = s["group_key"].replace({"yang2a": "yang2", "yang2b": "yang2"})
    s = s[s["g4"].isin(GNAME)].copy()

    # 高度: n1..nK is_lim 连续True计数(K=事件表实际前向深度)
    ncol = max(int(c.split("_")[0][1:]) for c in s.columns if c.endswith("_is_lim"))
    mat = s[[f"n{k}_is_lim" for k in range(1, ncol + 1)]].fillna(False).to_numpy(dtype=bool)
    h = np.zeros(len(s), dtype=int)
    for j in range(mat.shape[1]):
        h[(h == j) & mat[:, j]] = j + 1
    s["h"] = h
    s["seal"] = h >= 1
    s["a1"] = h >= 2
    s["a2"] = h >= 3

    # ── MA/量能(只读事件票,算 D0 与 D-1 时点值) ──
    vts = sorted(set(s["vt_symbol"]))
    engine = get_engine()
    bars = pd.read_sql(
        select(schema.stock_daily_bars.c.vt_symbol,
               schema.stock_daily_bars.c.trade_date,
               schema.stock_daily_bars.c.close_price,
               schema.stock_daily_bars.c.volume)
        .where(schema.stock_daily_bars.c.vt_symbol.in_(vts)), engine,
        parse_dates=["trade_date"])
    bars = bars.sort_values(["vt_symbol", "trade_date"])
    g = bars.groupby("vt_symbol", sort=False)
    for w in (10, 20, 30):
        bars[f"ma{w}"] = g["close_price"].transform(lambda x: x.rolling(w).mean())
    bars["vol5p"] = g["volume"].transform(lambda x: x.rolling(5).mean().shift(1))  # 前五日均量(不含当日)
    bars["vr"] = bars["volume"] / bars["vol5p"]

    d0 = bars.rename(columns={"trade_date": "n1_date"})[
        ["vt_symbol", "n1_date", "close_price", "ma10", "ma20", "ma30", "vr"]]
    d0 = d0.rename(columns={"close_price": "close_d0", "ma10": "ma10_d0", "ma20": "ma20_d0",
                            "ma30": "ma30_d0", "vr": "vr_d0"})
    tm1 = bars.rename(columns={"trade_date": "trade_date"})[
        ["vt_symbol", "trade_date", "vr"]].rename(columns={"vr": "vr_tm1"})
    s = s.merge(d0, on=["vt_symbol", "n1_date"], how="left")
    s = s.merge(tm1, on=["vt_symbol", "trade_date"], how="left")

    s["st3"] = ((np.where(s["ma10_d0"] > s["ma20_d0"], "+", "-")
                 + np.where(s["ma20_d0"] > s["ma30_d0"], "+", "-")).tolist())
    # 粗类: ++=多头有序(10>20>30) / --=空头有序 / 其余混合(+- / -+)
    s["st3c"] = np.where(s["st3"] == "++", "全多(10>20>30)",
                 np.where(s["st3"] == "--", "全空(10<20<30)", "混合"))
    for w in (10, 20, 30):
        s[f"bias{w}"] = (s["close_d0"] / s[f"ma{w}_d0"] - 1) * 100

    # ── 首触时间 ──
    tmap = repository.load_touch_map()
    s["touch"] = [tmap.get((str(v), d.date() if hasattr(d, "date") else d))
                  for v, d in zip(s["vt_symbol"], s["n1_date"])]
    s["tseg"] = s["touch"].map(lambda x: seg_of(x) if isinstance(x, str) else None)
    s["h_seg"] = s["h"]  # 别名便于统一引用
    return s


def vr_bucket(x):
    if pd.isna(x):
        return None
    if x < 0.8:
        return "缩<0.8"
    if x < 1.5:
        return "平0.8~1.5"
    if x < 3.0:
        return "放1.5~3"
    return "暴>=3"


def bias_bucket(x):
    if pd.isna(x):
        return None
    if x < -5:
        return "<-5"
    if x < 0:
        return "-5~0"
    if x < 5:
        return "0~5"
    return ">5"


def report(s: pd.DataFrame, title: str) -> None:
    print(f"\n{'=' * 78}\n【{title}】  n={len(s)}")
    print(baseline(s))


def baseline(s: pd.DataFrame) -> str:
    seal = s["seal"].mean() * 100
    a1 = s["a1"].mean() * 100
    a2 = s["a2"].mean() * 100
    sub = s[s["seal"]]
    cond = sub["a1"].mean() * 100 if len(sub) else float("nan")
    dist = s["h"].value_counts().sort_index()
    def bucket_pct(lo, hi=None):
        n = int(dist.loc[lo:hi].sum()) if hi else int(dist.get(lo, 0))
        return n / len(s) * 100 if len(s) else 0
    dist_s = (f"炸{bucket_pct(0):.0f}% 1板{bucket_pct(1):.0f}% 2板{bucket_pct(2):.0f}% "
              f"3板{bucket_pct(3):.0f}% 4板+{bucket_pct(4, 99):.0f}%")
    return (f"  封板 {seal:.1f}% | D+1板 {a1:.1f}% | D+2板 {a2:.1f}% | "
            f"[封住后]多拿一天 {cond:.1f}% | 均高 {s['h'].mean():.2f}\n  高度分布: {dist_s}")


def matrix(s: pd.DataFrame, dim: str, order: list[str] | None = None) -> None:
    rows = []
    for b in (order or sorted(x for x in s[dim].dropna().unique())):
        sub = s[s[dim] == b]
        if not len(sub):
            continue
        sealed = sub[sub["seal"]]
        rows.append({
            "桶": b, "n": len(sub),
            "封板%": round(sub["seal"].mean() * 100, 1),
            "D+1板%": round(sub["a1"].mean() * 100, 1),
            "D+2板%": round(sub["a2"].mean() * 100, 1),
            "[封]多拿%": round(sealed["a1"].mean() * 100, 1) if len(sealed) else None,
            "均高": round(sub["h"].mean(), 2),
            "4板+%": round((sub["h"] >= 4).mean() * 100, 1),
        })
    df = pd.DataFrame(rows)
    if len(df):
        print(df.to_string(index=False))
    else:
        print("  (空)")


def main() -> None:
    s = build_sample()
    print(f"全量触板事件(非一字): {len(s)} 笔  {s['trade_date'].min():%Y-%m-%d} ~ {s['trade_date'].max():%Y-%m-%d}")
    print(f"touch覆盖: {s['touch'].notna().sum()} 笔({s['touch'].notna().mean() * 100:.0f}%)")

    # 各组基准
    for gk, name in GNAME.items():
        report(s[s["g4"] == gk], f"{name}({gk}) 基准")

    # 单维矩阵: 每组 × 每维
    dims = [
        ("st3", "MA排列(D0收盘 10/20/30: +=上穿序)", ["++", "+-", "-+", "--"]),
        ("bias20", "bias_ma20%(D0收/ma20)", ["<-5", "-5~0", "0~5", ">5"]),
        ("bias10", "bias_ma10%(D0收/ma10)", ["<-5", "-5~0", "0~5", ">5"]),
        ("bias30", "bias_ma30%(D0收/ma30)", ["<-5", "-5~0", "0~5", ">5"]),
        ("vr_d0b", "D0量比(触板日量/前5日均量)", ["缩<0.8", "平0.8~1.5", "放1.5~3", "暴>=3"]),
        ("vr_tm1b", "D-1量比(坑底量能)", ["缩<0.8", "平0.8~1.5", "放1.5~3", "暴>=3"]),
        ("tseg", "首触时间段", ["早09:30~10:30", "中10:30~11:30", "午13:00~14:00", "尾14:00~15:00"]),
        ("touch", "首触15m细桶(末刻)", None),
    ]
    s["vr_d0b"] = s["vr_d0"].map(vr_bucket)
    s["vr_tm1b"] = s["vr_tm1"].map(vr_bucket)
    s["bias10"] = s["bias10"].map(bias_bucket)
    s["bias20"] = s["bias20"].map(bias_bucket)
    s["bias30"] = s["bias30"].map(bias_bucket)

    for gk, name in GNAME.items():
        sub = s[s["g4"] == gk]
        for dim, label, order in dims:
            print(f"\n──── {name} × {label} ────")
            matrix(sub, dim, order)

    out = s[["vt_symbol", "name", "g4", "trade_date", "n1_date", "h", "seal", "a1", "a2",
             "st3", "st3c", "bias10", "bias20", "bias30", "vr_d0", "vr_tm1", "touch", "tseg"]].copy()
    out["n1_date"] = pd.to_datetime(out["n1_date"]).dt.strftime("%Y-%m-%d")
    out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.strftime("%Y-%m-%d")
    out.to_csv("/tmp/w2s_streak_detail.csv", index=False, encoding="utf-8-sig")
    print(f"\n逐笔明细: /tmp/w2s_streak_detail.csv ({len(out)}行)")


if __name__ == "__main__":
    main()
