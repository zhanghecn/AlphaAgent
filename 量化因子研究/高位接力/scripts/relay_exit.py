# -*- coding: utf-8 -*-
"""高位接力 · 卖出纪律研究（第十一遍）。

买入规则冻结为因子方案v1, 本脚本只改卖出侧, 回答「什么情况下卖出风险和收益兼容」。
买入价 = 买入日涨停价。所有卖出决策用的信息在决策时刻都是可知的:
- 当日收盘卖 = 当天14:55已知是否涨停/大致量比
- 次日开盘卖 = 竞价已知开盘价
- 次日低开走 = 竞价已知

候选规则:
  E0 基准: 持有到首次断板日收盘(T+15兜底)
  E1 次日开盘无脑走
  E2 次日收盘无脑走(=次日收%)
  E3 炸板当日收盘走; 封住→E0
  E4 次日低开(<买价)开盘走; 否则→E0
  E5 买入日缩量封板(量比<0.8)且bias10>5% → 多拿一天(首个断板日的次日收盘); 否则→E0
  E6 断板次日收盘走(比E0多拿一个断板日)
  E7 炸板票专用: 次日开盘走 vs E0 对比(只在炸板子集上看)

评估: 按 方案合计/A1/A2/B1/B2/四组 × 封住/炸板 分层,
报 n/均值/中位/胜率/最差5笔均值/分年。

容器内跑: python /tmp/research/relay_exit.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/tmp/research")
import relay_research as R                       # 复用样本构建(已冻结的事实源)

pd.set_option("display.width", 340)
pd.set_option("display.max_columns", 100)


def tag_points(E):
    E["换手梯度"] = E["b2换手%"] - E["b1换手%"]
    def tag(r):
        if r["四组"] == "三接四阳" and -15 <= r["距60日新高%"] < -8 \
                and r["均线"] not in ("+++", "-++", "+--") and r["前波60日最高板"] == 0:
            return "A1"
        if r["四组"] == "三接四阴" and r["前波120日最高板"] >= 3 and r["换手梯度"] < -5:
            return "A2"
        if r["四组"] == "二接三阴" and 6 <= r["b2开盘%"] < 9.5 and 0 <= r["换手梯度"] < 2:
            return "B1"
        if r["四组"] == "二接三阳" and -9 <= r["距60日新高%"] < -2 and r["b2开盘%"] < 0 \
                and 4 <= r["买入开盘%"] < 7:
            return "B2"
        fb_h = r.get("前板高度")
        ma10 = r.get("距MA10%")
        if r["四组"] == "三接四阳" and fb_h == fb_h and (fb_h or 0) >= 2 \
                and ma10 == ma10 and ma10 < 5:
            return "B3"
        return "—"
    E["方案点"] = E.apply(tag, axis=1)
    return E


def exits_for(row, buy):
    """输入 bars 行(含n1..n15前向列), 返回各规则卖出价。"""
    out = {}
    n_close = {k: row.get(f"n{k}_close") for k in range(1, 16)}
    n_open = {k: row.get(f"n{k}_open") for k in range(1, 16)}
    n_lim = {k: bool(row.get(f"n{k}_is_lim")) if pd.notna(row.get(f"n{k}_is_lim")) else None
             for k in range(1, 16)}
    if pd.isna(n_close[1]):
        return None
    # E0 基准: 首个未涨停日收盘, 15兜底
    e0 = np.nan
    for k in range(1, 16):
        if pd.isna(n_close[k]):
            break
        if not n_lim[k]:
            e0 = n_close[k]
            break
    if pd.isna(e0) and pd.notna(n_close[15]):
        e0 = n_close[15]
    out["E0"] = e0
    out["E1"] = n_open[1]
    out["E2"] = n_close[1]
    # E3: 买入日没封住→当天收盘(=买入日收盘价row['close_price']); 封住→E0
    out["E3"] = e0 if row["is_lim"] else row["close_price"]
    # E4: 次日低开(开盘<买价)→次日开盘; 否则E0
    out["E4"] = n_open[1] if (pd.notna(n_open[1]) and n_open[1] < buy) else e0
    # E5: 缩量封板+强趋势 → 多拿一天(第二断板日收盘/15+1兜底)
    e5 = e0
    if row["is_lim"]:
        e5 = np.nan
        seen_break = False
        for k in range(1, 16):
            if pd.isna(n_close[k]):
                break
            if not n_lim[k]:
                if seen_break:
                    e5 = n_close[k]
                    break
                seen_break = True
        if pd.isna(e5) and pd.notna(n_close[15]):
            e5 = n_close[15]
    out["E5"] = e5
    # E6: 断板次日(首个未涨停日的下一天收盘)
    e6 = np.nan
    for k in range(1, 16):
        if pd.isna(n_close[k]):
            break
        if not n_lim[k]:
            kk = min(k + 1, 15)
            if pd.notna(n_close[kk]):
                e6 = n_close[kk]
            break
    if pd.isna(e6) and pd.notna(n_close[15]):
        e6 = n_close[15]
    out["E6"] = e6
    return out


def main():
    eng = create_engine(os.environ["DATABASE_URL"]) if False else None
    from sqlalchemy import create_engine
    eng = create_engine(os.environ["DATABASE_URL"])
    E, bars, end = R.build_events(eng)
    import relay_foundation as rf                # 地基/均线/反包扩展字段(B3需要)
    E = rf.augment(E, bars)
    E = E[~E["未完"]].copy()
    E = tag_points(E)

    # bars 行索引: (vt_symbol, trade_date) → 行号
    key = bars["vt_symbol"] + "_" + bars["trade_date"].dt.strftime("%Y-%m-%d")
    idx_of = dict(zip(key, bars.index))

    rows = []
    for _, r in E.iterrows():
        i = idx_of.get(f"{r['代码']}_{r['买入日']}")
        if i is None:
            continue
        br = bars.loc[i]
        buy = r["买价"]
        ex = exits_for(br, buy)
        if ex is None:
            continue
        vr = r["买入量比"] if pd.notna(r["买入量比"]) else np.nan
        bias10 = br["close_price"] / br["ma10"] - 1 if pd.notna(br["ma10"]) else np.nan
        golden = bool(br["is_lim"]) and pd.notna(vr) and vr < 0.8 and pd.notna(bias10) and bias10 > 0.05
        rec = {"方案点": r["方案点"], "四组": r["四组"], "年": str(r["年"]), "封住": r["封住"],
               "缩量强趋势": golden}
        for k, px in ex.items():
            rec[k] = (px / buy - 1) * 100 if pd.notna(px) else np.nan
        rows.append(rec)
    X = pd.DataFrame(rows)
    X.insert(0, "买入日", [r["买入日"] for _, r in E.iterrows() if f"{r['代码']}_{r['买入日']}" in idx_of][:len(X)])
    X.insert(0, "代码", [r["代码"] for _, r in E.iterrows() if f"{r['代码']}_{r['买入日']}" in idx_of][:len(X)])
    X.to_csv("/tmp/research/relay_out/逐笔卖出规则.csv", index=False, encoding="utf-8-sig")

    rules = ["E0", "E1", "E2", "E3", "E4", "E5", "E6"]
    layers = [("方案合计", X[X["方案点"] != "—"]), ("A1", X[X["方案点"] == "A1"]),
              ("A2", X[X["方案点"] == "A2"]), ("B1", X[X["方案点"] == "B1"]),
              ("B2", X[X["方案点"] == "B2"]), ("B3", X[X["方案点"] == "B3"]),
              ("二接三全部", X[X["四组"].isin(["二接三阴", "二接三阳"])]),
              ("三接四全部", X[X["四组"].isin(["三接四阴", "三接四阳"])])]
    # E5只对缩量强趋势票生效, 其余同E0 → 单独看该子集
    lines = []
    lines.append(f"样本 {len(X)} 笔（全量事件, 含未命中; 方案合计={len(layers[0][1])}笔）")
    lines.append("缩量封板+强趋势(bias10>5%)的票: "
                 f"{int(X['缩量强趋势'].sum())} 笔（E5只对它们有区别）\n")
    for lname, sub in layers:
        if len(sub) == 0:
            continue
        lines.append(f"\n===== {lname} (n={len(sub)}) =====")
        lines.append("规则 | 均值 | 中位 | 胜率 | 最差5笔均值 | 单笔最差")
        for rl in rules:
            v = sub[rl].dropna()
            if len(v) == 0:
                continue
            lines.append(f"{rl} | {v.mean():+.2f} | {v.median():+.2f} | {(v>0).mean()*100:.0f}% "
                         f"| {v.nsmallest(5).mean():+.2f} | {v.min():+.2f}")
        # 封住/炸板分开看 E0 vs E3
        for sealed, tag in ((True, "封住票"), (False, "炸板票")):
            ss = sub[sub["封住"] == sealed]
            if len(ss) == 0:
                continue
            e0 = ss["E0"].dropna()
            e3 = ss["E3"].dropna()
            alt = ss["E1"].dropna() if not sealed else None
            txt = f"  {tag}(n={len(ss)}): E0均值{e0.mean():+.2f}"
            if not sealed:
                txt += f" | E3当日收盘走 {e3.mean():+.2f} | E1次日开盘走 {alt.mean():+.2f}"
            lines.append(txt)
        # E5 子集
        g = sub[sub["缩量强趋势"]]
        if len(g) > 0:
            lines.append(f"  缩量强趋势子集(n={len(g)}): E0 {g['E0'].mean():+.2f} vs "
                         f"E5多拿一天 {g['E5'].mean():+.2f} | "
                         f"胜率 {(g['E0']>0).mean()*100:.0f}%→{(g['E5']>0).mean()*100:.0f}%")
    # 分年稳定性: 方案合计 E0/E3/E4
    lines.append("\n===== 方案合计 分年 =====")
    sch = X[X["方案点"] != "—"]
    for rl in ("E0", "E3", "E4", "E6"):
        by = sch.groupby("年")[rl].agg(["size", "mean"])
        lines.append(f"{rl}: " + " ".join(f"{y}:{m:+.2f}(n={int(n)})" for y, (n, m) in by.iterrows()))
    text = "\n".join(lines)
    print(text)
    with open("/tmp/research/relay_out/卖出纪律.md", "w", encoding="utf-8") as f:
        f.write("# 高位接力 · 卖出纪律研究（2026-09-19 第十一遍）\n\n"
                "规则编号: E0=持有到断板(基准) E1=次日开盘走 E2=次日收盘走 E3=炸板当日走 "
                "E4=次日低开走 E5=缩量强趋势多拿一天 E6=断板次日走\n\n```\n" + text + "\n```\n")


if __name__ == "__main__":
    main()
