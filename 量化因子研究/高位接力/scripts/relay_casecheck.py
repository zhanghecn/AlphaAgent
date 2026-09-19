# -*- coding: utf-8 -*-
"""高位接力 · 案例门禁（第十遍）：独立代码路径逐票重算核验。

原则: 不复用 relay_research.py 的任何代码, 从 stock_daily_bars 原始K线独立重算:
- 事件判定: 昨日恰好N连板 / 当日触板 / 非一字 / 买价=涨停价
- 条件字段: 距60日新高% / 均线排列 / 前波60/120日最高板 / 各板开盘%·换手·板型 / 换手梯度
- 结果字段: 次日收% / 持有到断板%
抽样: 每个方案点(A1/A2/B1/B2) 最大赢家2笔 + 中位附近2笔 + 最差输家2~3笔。
核验通过=重算值与全量明细.csv一致(容差0.05pp)。

容器内跑: python /tmp/research/relay_casecheck.py
"""
import os
import sys

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

pd.set_option("display.width", 340)
pd.set_option("display.max_columns", 100)

CSV_IN = "/tmp/research/relay_out/全量明细.csv"
MD_OUT = "/tmp/research/relay_out/案例门禁.md"

POINTS = {
    "A1": lambda r: r["四组"] == "三接四阳" and -15 <= r["距60日新高%"] < -8
        and r["均线"] not in ("+++", "-++", "+--") and r["前波60日最高板"] == 0,
    "A2": lambda r: r["四组"] == "三接四阴" and r["前波120日最高板"] >= 3 and r["换手梯度"] < -5,
    "B1": lambda r: r["四组"] == "二接三阴" and 6 <= r["b2开盘%"] < 9.5 and 0 <= r["换手梯度"] < 2,
    "B2": lambda r: r["四组"] == "二接三阳" and -9 <= r["距60日新高%"] < -2 and r["b2开盘%"] < 0,
}


def load_csv():
    E = pd.read_csv(CSV_IN)
    E["换手梯度"] = E["b2换手%"] - E["b1换手%"]
    E["方案点"] = "—"
    for p, fn in POINTS.items():
        E.loc[E.apply(fn, axis=1), "方案点"] = p
    return E


def recompute(bars, buy_date, N):
    """独立重算。bars=该票全部日线(按日期升序)。返回 dict 或 None。"""
    b = bars.copy().reset_index(drop=True)
    b["prev_close"] = b["close_price"].shift(1)
    b["limit_price"] = np.round(b["prev_close"] * 1.10 + 1e-9, 2)
    elig = b["prev_close"].notna() & (b.index >= 5)
    b["is_lim"] = elig & ((b["close_price"] - b["limit_price"]).abs() <= 1e-6)
    b["one_word"] = b["is_lim"] & (b["open_price"] == b["close_price"]) & \
        (b["open_price"] == b["high_price"]) & (b["open_price"] == b["low_price"])
    # 连板数: 从后往前累
    streak = np.zeros(len(b), dtype=int)
    for i in range(1, len(b)):
        streak[i] = streak[i - 1] + 1 if b.loc[i, "is_lim"] else 0
    b["streak"] = streak
    hit = b.index[b["trade_date"] == buy_date]
    if len(hit) == 0:
        return None
    p = int(hit[0])
    if p < N + 1:
        return None
    rec = {}
    rec["昨日连板数"] = int(b.loc[p - 1, "streak"])
    rec["当日触板"] = bool(b.loc[p, "high_price"] >= b.loc[p, "limit_price"] - 1e-6)
    rec["当日一字"] = bool(b.loc[p, "one_word"])
    rec["买价"] = round(float(b.loc[p, "limit_price"]), 2)
    # 首板前一天(地基日)
    f = p - N - 1
    rec["地基日"] = str(b.loc[f, "trade_date"])
    h60 = b.loc[max(0, f - 59):f, "high_price"].max()
    rec["距60日新高%"] = round((b.loc[f, "close_price"] / h60 - 1) * 100, 1)
    ma = {}
    for w in (5, 10, 20, 30):
        ma[w] = b.loc[max(0, f - w + 1):f, "close_price"].mean() if f - w + 1 >= 0 else np.nan
    if all(v == v for v in ma.values()):
        rec["均线"] = ("+" if ma[5] >= ma[10] else "-") + ("+" if ma[10] >= ma[20] else "-") + \
                    ("+" if ma[20] >= ma[30] else "-")
    else:
        rec["均线"] = ""
    # 前波: 首板(p-N)之前的连板段(段高>=2), 段尾在窗口内
    first = p - N
    for win in (60, 120):
        hmax = 0
        for i in range(max(0, first - win), first):
            if b.loc[i, "streak"] >= 2 and (i + 1 >= len(b) or b.loc[i + 1, "streak"] == 0):
                hmax = max(hmax, int(b.loc[i, "streak"]))
        rec[f"前波{win}日最高板"] = hmax
    # 逐板
    for k in range(1, N + 1):
        j = first + k - 1
        o, c, h, l, pc = (float(b.loc[j, col]) for col in
                          ("open_price", "close_price", "high_price", "low_price", "prev_close"))
        lsh = (min(o, c) - l) / pc * 100
        rec[f"b{k}开盘%"] = round((o / pc - 1) * 100, 1)
        rec[f"b{k}换手%"] = round(float(b.loc[j, "turnover_rate"]), 1)
        rec[f"b{k}板型"] = "一字" if b.loc[j, "one_word"] else ("下影" if lsh >= 0.3 else "实体")
    rec["换手梯度"] = round(rec["b2换手%"] - rec["b1换手%"], 1)
    # 结果
    if p + 1 < len(b):
        rec["次日收%"] = round((float(b.loc[p + 1, "close_price"]) / rec["买价"] - 1) * 100, 2)
    exit_px = np.nan
    for k in range(1, 16):
        if p + k >= len(b):
            break
        if not b.loc[p + k, "is_lim"]:
            exit_px = float(b.loc[p + k, "close_price"])
            break
    if exit_px != exit_px and p + 15 < len(b):
        exit_px = float(b.loc[p + 15, "close_price"])
    rec["持有到断板%"] = round((exit_px / rec["买价"] - 1) * 100, 2) if exit_px == exit_px else np.nan
    return rec


def kline_text(bars, buy_date, N):
    """迷你K线: 首板前3日~买入后3日。"""
    b = bars.reset_index(drop=True)
    hit = b.index[b["trade_date"] == buy_date]
    if len(hit) == 0:
        return ""
    p = int(hit[0])
    lo = max(0, p - N - 3)
    hi = min(len(b) - 1, p + 3)
    lines = ["日期         开盘    最高    最低    收盘   涨跌%  换手%  标记"]
    prev = None
    for i in range(lo, hi + 1):
        r = b.loc[i]
        chg = (r["close_price"] / prev - 1) * 100 if prev else np.nan
        mark = ""
        if i == p - N - 1:
            mark = "←地基日(阴阳分组依据)"
        elif p - N <= i < p:
            mark = f"←第{i - (p - N) + 1}板"
        elif i == p:
            mark = "←买入日(打板)"
        lines.append(f"{r['trade_date']}  {r['open_price']:7.2f} {r['high_price']:7.2f} "
                     f"{r['low_price']:7.2f} {r['close_price']:7.2f} "
                     f"{chg:+6.2f} {r['turnover_rate']:6.1f}  {mark}")
        prev = r["close_price"]
    return "\n".join(lines)


def main():
    E = load_csv()
    eng = create_engine(os.environ["DATABASE_URL"])
    checks = ["昨日连板数", "当日触板", "当日一字", "买价", "距60日新高%", "均线",
              "前波60日最高板", "前波120日最高板", "b1开盘%", "b1换手%", "b1板型",
              "b2开盘%", "b2换手%", "b2板型", "换手梯度", "次日收%", "持有到断板%"]
    total, fails = 0, []
    case_rows = []
    kline_blocks = []
    bars_cache = {}
    for p in ("A1", "A2", "B1", "B2"):
        s = E[E["方案点"] == p].sort_values("持有到断板%", ascending=False)
        picks = pd.concat([s.head(2), s.iloc[len(s) // 2 - 1:len(s) // 2 + 1], s.tail(3 if p == "A1" else 2)])
        N = 3 if p in ("A1", "A2") else 2
        for _, r in picks.iterrows():
            code, day = r["代码"], r["买入日"]
            if code not in bars_cache:
                bd = pd.read_sql(f"select trade_date, open_price, high_price, low_price, close_price, "
                                 f"volume, turnover_rate from stock_daily_bars where vt_symbol='{code}' "
                                 f"and trade_date <= '{day}'::date + 40 order by 1", eng,
                                 parse_dates=["trade_date"])
                bd["trade_date"] = bd["trade_date"].dt.strftime("%Y-%m-%d")
                bars_cache[code] = bd
            bars = bars_cache[code]
            rec = recompute(bars, day, N)
            row = [f"{p} {r['名称']} {day}"]
            if rec is None:
                fails.append((p, r["名称"], day, "事件日找不到"))
                continue
            n_boards_ok = rec["昨日连板数"] == N
            for c in checks:
                total += 1
                exp, got = r[c] if c in r else None, rec.get(c)
                if c == "昨日连板数":
                    ok = got == N
                elif c in ("当日触板",):
                    ok = got
                elif c in ("当日一字",):
                    ok = (not got)
                elif c in ("均线", "b1板型", "b2板型"):
                    ok = str(exp) == str(got)
                elif "板" in c and "最高板" in c:
                    ok = int(exp) == int(got)
                else:
                    try:
                        ok = abs(float(exp) - float(got)) <= 0.051
                    except (TypeError, ValueError):
                        ok = False
                if not ok:
                    fails.append((p, r["名称"], day, c, exp, got))
                    row.append(f"{c}:✗({exp}≠{got})")
            case_rows.append(" ".join(row) if len(row) > 1 else row[0] + " 全字段一致✓")
            # 展示用K线: 每点第一笔(最大赢家)+最后一笔(最差输家)
            if r.name == picks.index[0] or r.name == picks.index[-1]:
                kline_blocks.append(f"### {p} · {r['名称']} {day}（买入N={N}板, "
                                    f"结果={r['结果']}, 持有到断板{r['持有到断板%']:+.1f}%）\n\n```\n"
                                    + kline_text(bars, day, N) + "\n```")
    print(f"核验 {total} 个字段值, 不一致 {len(fails)} 个")
    for f_ in fails[:30]:
        print("  不一致:", f_)
    print("\n".join(case_rows))

    md = ["# 高位接力 · 案例门禁（2026-09-19 第十遍）", "",
          "独立代码路径（不复用研究脚本）从原始K线重算全部字段，逐票核对。",
          "抽样 = 每个方案点 最大赢家2笔 + 中位2笔 + 最差输家2~3笔。", "",
          f"**核验字段 {total} 个，不一致 {len(fails)} 个。**", ""]
    if fails:
        md.append("## 不一致清单")
        md += [f"- {f_}" for f_ in fails]
    md.append("\n## 代表案例K线（每点最大赢家+最差输家）\n")
    md += kline_blocks
    with open(MD_OUT, "w", encoding="utf-8") as fp:
        fp.write("\n".join(md) + "\n")
    print(f"\n已写 {MD_OUT}")


if __name__ == "__main__":
    main()
