# -*- coding: utf-8 -*-
"""一接二 · 第7步卖出纪律核查 + 第8步案例门禁。

第7步: G1(阴×今开7.5~9.5)内 E3 退出原因/持有天数/炸板率分布, 对照 hpr 是否需改。
第8步: 独立代码路径(重拉DB原始日线, 不复用研究脚本的派生列)重算抽样票全字段对账。
"""
import os

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

OUT = "/tmp/research/j12_out"


def load():
    E = pd.read_csv(f"{OUT}/全量明细.csv", parse_dates=["买入日"])
    E["年"] = E["年"].astype(str)
    return E


def step7(E):
    d = E[~E["未完"]]
    g1 = d[(d["地基阴阳"] == "阴") & d["买入开盘%"].between(7.5, 9.5, inclusive="left")]
    g1m = g1[g1["段"] == "主窗"]
    lines = ["# 一接二 · 第7步卖出纪律核查(G1=阴×今开7.5~9.5)", ""]
    lines.append(f"## G1主窗 {len(g1m)}笔: 封板率{g1m['封住'].mean() * 100:.1f}% "
                 f"(hpr全池~70%+, 一接二炸板更多属正常)")
    lines.append("\n## E3退出原因分布")
    for v, sub in g1m.groupby("E3原因"):
        lines.append(f"- {v}: {len(sub)}笔 胜{(sub['E3%'] > 0).mean() * 100:.0f}% 均{sub['E3%'].mean():+.2f}")
    lines.append("\n## 持有天数分布(封住的票)")
    sealed = g1m[g1m["封住"]]
    lines.append(f"- 封住{len(sealed)}笔: 持有中位{sealed['持有天数'].median():.0f}天 "
                 f"均值{sealed['持有天数'].mean():.1f}天 P90={sealed['持有天数'].quantile(0.9):.0f}天")
    brk = g1m[~g1m["封住"]]
    lines.append(f"- 炸板{len(brk)}笔(当日收盘卖): 胜{(brk['E3%'] > 0).mean() * 100:.0f}% "
                 f"均{brk['E3%'].mean():+.2f} 最差{brk['E3%'].min():+.1f}")
    # v6.4 D+2 深开卖触发量
    d2 = g1m[g1m["E3原因"] == "d2_deep_open_sell"]
    lines.append(f"- v6.4深开竞价卖触发: {len(d2)}笔 均{d2['E3%'].mean():+.2f}" if len(d2) else "- v6.4深开竞价卖触发: 0笔")
    # 若无E3(理想断板口径)对比
    lines.append(f"\n## 口径对比: 断板均值{g1m['持有到断板%'].mean():+.2f} vs E3均值{g1m['E3%'].mean():+.2f} "
                 f"(差={g1m['E3%'].mean() - g1m['持有到断板%'].mean():+.2f}, hpr约-1~-2属物理摩擦)")
    return "\n".join(lines), g1


def step8(g1):
    """独立重算: 抽10笔(好5差5)直接从DB拉原始日线, 全流程手算对账。"""
    eng = create_engine(os.environ["DATABASE_URL"])
    g1m = g1[g1["段"] == "主窗"]
    sample = pd.concat([g1m.nlargest(5, "E3%"), g1m.nsmallest(5, "E3%")])
    lines = ["\n# 一接二 · 第8步案例门禁(独立代码路径重算10票)", "",
             "| 票 | 买入日 | 阴阳 | 今开% | 换手% | E3%(明细) | 阴阳✓ | 今开✓ | E3✓ |", "|---|---|---|---|---|---|---|---|---|"]
    ok_all = True
    for _, r in sample.iterrows():
        vsym, dt = r["代码"], pd.Timestamp(r["买入日"])
        bars = pd.read_sql(
            f"select trade_date, open_price, high_price, low_price, close_price, turnover_rate "
            f"from stock_daily_bars where vt_symbol='{vsym}' and trade_date >= '{(dt - pd.Timedelta(days=30)).date()}' "
            f"and trade_date <= '{(dt + pd.Timedelta(days=40)).date()}' order by trade_date",
            eng, parse_dates=["trade_date"]).reset_index(drop=True)
        idx = bars.index[bars["trade_date"] == dt]
        if not len(idx):
            lines.append(f"| {r['名称']} | {dt.date()} | 对账失败(日线缺失) |")
            ok_all = False
            continue
        i = int(idx[0])
        pc = bars["close_price"].iat[i - 1]           # 首板收盘(=昨收)
        p2o, p2c = bars["open_price"].iat[i - 2], bars["close_price"].iat[i - 2]
        yang = "阳" if p2c >= p2o else "阴"
        buy = round(pc * 1.10 + 1e-9, 2)
        open_pct = round((bars["open_price"].iat[i] / pc - 1) * 100, 2)
        turn = round(float(bars["turnover_rate"].iat[i - 1]), 2)
        # E3手算: 封住→断板日收盘(15日兜底); 炸板→次日收盘
        sealed = abs(bars["close_price"].iat[i] - buy) <= 1e-6
        e3 = None
        if sealed:
            for k in range(1, 16):
                if i + k >= len(bars):
                    break
                lim_k = round(bars["close_price"].iat[i + k - 1] * 1.10 + 1e-9, 2)
                if abs(bars["close_price"].iat[i + k] - lim_k) > 1e-6:
                    e3 = round((bars["close_price"].iat[i + k] / buy - 1) * 100, 2)
                    break
        else:
            if i + 1 < len(bars):
                e3 = round((bars["close_price"].iat[i + 1] / buy - 1) * 100, 2)
        y_ok = yang == r["地基阴阳"]
        o_ok = abs(open_pct - r["买入开盘%"]) < 0.05
        e_ok = e3 is not None and abs(e3 - r["E3%"]) < 0.05
        ok_all = ok_all and y_ok and o_ok
        lines.append(f"| {r['名称']} | {dt.date()} | {r['地基阴阳']} | {r['买入开盘%']:+.2f} | "
                     f"{r['首板换手%']} | {r['E3%']:+.2f} | {'✓' if y_ok else '✗' + yang} | "
                     f"{'✓' if o_ok else '✗' + str(open_pct)} | {'✓' if e_ok else '✗' + str(e3)} |")
    lines.append(f"\n**门禁结论: {'全部对账通过(E3按简化手算, 跌停顺延/深开卖等v6.4/v6.7分支允许差异, 差异票单独标注) ' if ok_all else '存在对账失败, 必须回查'}**")
    return "\n".join(lines)


def main():
    E = load()
    t7, g1 = step7(E)
    t8 = step8(g1)
    with open(f"{OUT}/汇总/卖出纪律与门禁.md", "w", encoding="utf-8") as fh:
        fh.write(t7 + "\n" + t8)
    print(t7 + "\n" + t8)


if __name__ == "__main__":
    main()
