# -*- coding: utf-8 -*-
"""反包 Phase 0 案例门禁：独立代码路径重算抽样票全部字段（容器内跑）。

与 fanbao_research.py 完全不同的实现：纯 SQL 逐票拉原始日线, Python 逐日循环判
连板/断板/触板/一字/买价/次日收/持有到断板, 与全量明细.csv 对账。
抽样 = 主12格每格2笔(random_state=7) + 5板断1天格全量45笔全部重算(最亮格重点验)。
用法(容器内): 先把全量明细.csv 拷到 /tmp/research/, 再 python fanbao_casecheck.py
"""
import os

import pandas as pd
from sqlalchemy import create_engine

FB_CSV = "/tmp/research/全量明细.csv"
YEARS_BACK = 1  # 每票反包日前推自然日窗口(拉1年日线足够覆盖15板+断板期)


def recompute(sym, rb_day, eng):
    """独立重算一笔反包事件的全部关键字段, 返回dict或None(结构对不上)。"""
    q = pd.read_sql(
        f"""select trade_date::text d, open_price o, high_price h, low_price l, close_price c
        from stock_daily_bars where vt_symbol='{sym}'
          and trade_date between '{rb_day}'::date - interval '{365 * YEARS_BACK + 60} day'
                             and '{rb_day}'::date + interval '40 day'
        order by trade_date""", eng)
    q = q.reset_index(drop=True)
    if q.empty:
        return None
    # 涨停价 = 昨收*1.10四舍五入到分(与主脚本/交易所一致: +1e-9防浮点把x.xx5边界舍反)
    q["pc"] = q["c"].shift(1)
    q["lim"] = (q["pc"] * 1.1 + 1e-9).round(2)
    q["is_lim"] = (q["c"] - q["lim"]).abs() <= 1e-6
    q["ow"] = (q["o"] == q["h"]) & (q["o"] == q["l"])
    i = q.index[q["d"] == rb_day]
    if len(i) == 0:
        return None
    i = int(i[0])
    if i < 1:
        return None
    # 断板天数: 从反包日前一天往回数连续收盘不涨停天数
    g = 0
    j = i - 1
    while j >= 0 and not bool(q.at[j, "is_lim"]):
        g += 1
        j -= 1
    if j < 0 or not bool(q.at[j, "is_lim"]):
        return None
    e = j                                    # 末板日
    # 末板所在连板段高度: 从e往前数连续涨停
    N = 0
    k = e
    while k >= 0 and bool(q.at[k, "is_lim"]):
        N += 1
        k -= 1
    # 断板期每天不涨停(结构自检)
    seg_bad = any(bool(q.at[t, "is_lim"]) for t in range(e + 1, i))
    buy = float(q.at[i, "lim"])
    touch = float(q.at[i, "h"]) >= buy - 0.005
    ow = bool(q.at[i, "ow"]) and bool(q.at[i, "is_lim"])
    seal = bool(q.at[i, "is_lim"])
    # 持有到断板: 封住→次日起首个非涨停日收盘; 炸板→当天收盘; 15日兜底
    if not seal:
        exit_px, hold = float(q.at[i, "c"]), 0
    else:
        exit_px, hold = None, None
        for kk in range(1, 16):
            if i + kk >= len(q):
                break
            if not bool(q.at[i + kk, "is_lim"]):
                exit_px, hold = float(q.at[i + kk, "c"]), kk
                break
        if exit_px is None:
            hold = None
    n1c = float(q.at[i + 1, "c"]) if i + 1 < len(q) else None
    return dict(末板日=q.at[e, "d"], N=int(N), 断板天数=int(g), 断板期含涨停=bool(seg_bad),
                触板=bool(touch), 一字=bool(ow), 封住=bool(seal), 买价=round(buy, 2),
                次日收=round((n1c / buy - 1) * 100, 2) if n1c else None,
                持有到断板=round((exit_px / buy - 1) * 100, 2) if exit_px else None,
                持有天数=hold, 未完=exit_px is None)


def main():
    eng = create_engine(os.environ["DATABASE_URL"])
    fb = pd.read_csv(FB_CSV, dtype={"代码": str})
    idx = []
    for _, sub in fb[fb["主格"]].groupby(["N", "断板天数"]):
        idx += sub.sample(min(2, len(sub)), random_state=7).index.tolist()
    smp = fb.loc[idx]
    smp = pd.concat([smp, fb[(fb["N"] == 5) & (fb["断板天数"] == 1)]])  # 最亮格全验
    smp = smp.drop_duplicates(subset=["代码", "反包日"]).reset_index(drop=True)
    bad = 0
    for _, r in smp.iterrows():
        rec = recompute(r["代码"], r["反包日"], eng)
        if rec is None:
            print(f"✘ {r['代码']} {r['反包日']} 独立重算结构失败(库里是 N={r['N']} g={r['断板天数']})")
            bad += 1
            continue
        errs = []
        if rec["末板日"] != r["末板日"]:
            errs.append(f"末板日{rec['末板日']}≠{r['末板日']}")
        if rec["N"] != r["N"]:
            errs.append(f"N={rec['N']}≠{r['N']}")
        if rec["断板天数"] != r["断板天数"]:
            errs.append(f"g={rec['断板天数']}≠{r['断板天数']}")
        if rec["断板期含涨停"]:
            errs.append("断板期含涨停!")
        if not rec["触板"] or rec["一字"]:
            errs.append(f"触板{rec['触板']}/一字{rec['一字']}")
        if abs(rec["买价"] - r["买价"]) > 0.005:
            errs.append(f"买价{rec['买价']}≠{r['买价']}")
        if rec["封住"] != bool(r["封住"]):
            errs.append(f"封住{rec['封住']}≠{r['封住']}")
        if r["次日收%"] == r["次日收%"] and rec["次日收"] is not None and abs(rec["次日收"] - r["次日收%"]) > 0.02:
            errs.append(f"次日收{rec['次日收']}≠{r['次日收%']}")
        if r["持有到断板%"] == r["持有到断板%"] and rec["持有到断板"] is not None and abs(rec["持有到断板"] - r["持有到断板%"]) > 0.02:
            errs.append(f"持有到断板{rec['持有到断板']}≠{r['持有到断板%']}")
        if errs:
            bad += 1
            print(f"✘ {r['代码']} {r['名称']} {r['反包日']} N{r['N']}g{r['断板天数']}: " + "; ".join(errs))
    print(f"\n案例门禁: 抽样 {len(smp)} 笔(12格各2笔+5板断1天全量{int(((fb['N']==5)&(fb['断板天数']==1)).sum())}笔), "
          f"不一致 {bad} 笔")
    print("✅ 全部通过" if bad == 0 else "❌ 存在不一致, 须归零后才能进Phase1")


if __name__ == "__main__":
    main()
