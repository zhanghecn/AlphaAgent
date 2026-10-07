# -*- coding: utf-8 -*-
"""一接二 · 第二轮A: G1卖出端深挖——断板卖是不是卖早了。

G1封住的票(主窗203笔): E3=断板日收盘卖, 持有中位仅1天。
对照方案(全部卖出日可知信息, 无未来函数):
  H0 E3现行: 断板日收盘卖(基准)
  H1 多拿1天: 断板后次日收盘卖
  H2 多拿2天
  H3 殞板日盘中高点卖(理论上限参考, 不可执行, 只看空间)
  H4 条件多拿: 断板日缩量(量比<0.8)才多拿1天, 否则照E3
  H5 条件多拿: 二板换手<8(锁)才多拿1天
  H6 条件多拿: 深坑(距MA20<-5)才多拿1天
另看: 断板日当天的特征(是否缩量断板)分组下「多拿1天」的增益。
"""
import os

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

OUT = "/tmp/research/j12_out"


def main():
    E = pd.read_csv(f"{OUT}/全量明细.csv", parse_dates=["买入日"])
    E["年"] = E["年"].astype(str)
    d = E[~E["未完"]]
    g1 = d[(d["地基阴阳"] == "阴") & d["买入开盘%"].between(7.5, 9.5, inclusive="left")].copy()

    eng = create_engine(os.environ["DATABASE_URL"])
    # 拉G1每笔买入日前后20行日线, 计算各持有方案收益
    rows = []
    for _, r in g1.iterrows():
        vsym, dt = r["代码"], pd.Timestamp(r["买入日"])
        bars = pd.read_sql(
            f"select trade_date, open_price, high_price, low_price, close_price, volume "
            f"from stock_daily_bars where vt_symbol='{vsym}' and trade_date >= '{(dt - pd.Timedelta(days=10)).date()}' "
            f"and trade_date <= '{(dt + pd.Timedelta(days=45)).date()}' order by trade_date",
            eng, parse_dates=["trade_date"]).reset_index(drop=True)
        idx = bars.index[bars["trade_date"] == dt]
        if not len(idx):
            continue
        i = int(idx[0])
        buy = float(r["买价"])
        b = bars.iloc[i: i + 18].reset_index(drop=True)   # 买入日起最多18行
        if len(b) < 2:
            continue
        # 断板日=买入日(若炸板)或首个不再涨停日
        def is_lim(k):
            if k == 0:   # 买入日: 涨停价=买价本身
                return abs(b["close_price"].iat[0] - buy) <= 1e-6
            pc = b["close_price"].iat[k - 1]
            return abs(b["close_price"].iat[k] - round(pc * 1.10 + 1e-9, 2)) <= 1e-6
        sealed0 = is_lim(0)
        if not sealed0:
            bk = 0
        else:
            bk = None
            for k in range(1, len(b)):
                if not is_lim(k):
                    bk = k
                    break
            if bk is None:
                continue
        rec = {"代码": vsym, "买入日": dt, "年": r["年"], "段": r["段"], "封住": sealed0,
               "E3%": r["E3%"], "首板换手%": r["首板换手%"], "地基距MA20%": r["地基距MA20%"],
               "断板k": bk}
        # 各方案收益
        def ret(k_close, k_high=None):
            if k_close >= len(b):
                return np.nan
            v = (b["close_price"].iat[k_close] / buy - 1) * 100
            return round(v, 2)
        rec["H0断板收盘"] = ret(bk)
        rec["H1多拿1天"] = ret(bk + 1)
        rec["H2多拿2天"] = ret(bk + 2)
        rec["H3断板日高点"] = round((b["high_price"].iat[bk] / buy - 1) * 100, 2) if bk < len(b) else np.nan
        # 断板日量比(断板日量/断板前5日均量, 含断板日)
        if bk < len(b) and bk >= 1:
            v5 = bars["volume"].iloc[i + bk - 5: i + bk].mean()
            rec["断板量比"] = round(b["volume"].iat[bk] / v5, 2) if v5 else np.nan
        else:
            rec["断板量比"] = np.nan
        rows.append(rec)
    H = pd.DataFrame(rows)
    H.to_csv(f"{OUT}/汇总/G1持有方案明细.csv", index=False, encoding="utf-8-sig")

    lines = [f"# 一接二 · 第二轮A: 卖出端深挖(G1 {len(H)}笔有前向数据)", ""]

    def blk(sub, tag):
        if not len(sub):
            return f"- {tag}: 0笔"
        yr = sub.groupby("年")["H0断板收盘"].mean()
        yrs = " / ".join(f"{y}:{sub[sub['年'] == y].shape[0]}笔{v:+.2f}" for y, v in yr.items())
        return (f"- {tag}: {len(sub)}笔 均{sub['H0断板收盘'].mean():+.2f} → "
                f"H1多拿1天均{sub['H1多拿1天'].mean():+.2f}(Δ{sub['H1多拿1天'].mean() - sub['H0断板收盘'].mean():+.2f}) "
                f"H2多拿2天均{sub['H2多拿2天'].mean():+.2f} ｜ {yrs}")

    lines.append("## 全体(G1封住的票)")
    lines.append(blk(H, "全部"))
    sealed = H[H["封住"]]
    lines.append(blk(sealed, "其中当天封住"))
    # 条件多拿
    lines.append("\n## 条件多拿1天(分组看Δ)")
    for name, m in [("断板量比<0.8(缩量断板)", sealed["断板量比"] < 0.8),
                    ("断板量比>=0.8(放量断板)", sealed["断板量比"] >= 0.8),
                    ("二板换手<8(锁)", sealed["首板换手%"] < 8),
                    ("二板换手>=8", sealed["首板换手%"] >= 8),
                    ("深坑距MA20<-5", sealed["地基距MA20%"] < -5),
                    ("高位距MA20>0", sealed["地基距MA20%"] >= 0)]:
        sub = sealed[m].dropna(subset=["H1多拿1天"])
        if len(sub) >= 10:
            d0, d1 = sub["H0断板收盘"].mean(), sub["H1多拿1天"].mean()
            lines.append(f"- {name}: {len(sub)}笔 断板卖{d0:+.2f} → 多拿1天{d1:+.2f} "
                         f"(Δ{d1 - d0:+.2f}) H2{sub['H2多拿2天'].mean():+.2f}")
    # 理论上限
    lines.append(f"\n## 空间参考: 断板日盘中高点卖(不可执行) 均{sealed['H3断板日高点'].mean():+.2f} "
                 f"vs 收盘卖{sealed['H0断板收盘'].mean():+.2f}")
    txt = "\n".join(lines)
    with open(f"{OUT}/汇总/持有方案对比.md", "w", encoding="utf-8") as fh:
        fh.write(txt)
    print(txt)


if __name__ == "__main__":
    main()
