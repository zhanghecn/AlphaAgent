# -*- coding: utf-8 -*-
"""高位接力 · 买入时间 × 条件研究 联调版（全量回补后, 第十四遍）。

样本 = 触板时间明细-全量.csv(2386笔, 2024-08-15~2026-09, 通达信15mK) ⋈ 全量明细.csv。
15mK标签口径: 周期结束时点(09:45 = 09:30~09:45那根)。
触板段分档: 首刻=09:30~45 / 09:45~10:00 / 10:00~10:30 / 10:30~11:30 /
           13:00~14:00 / 14:00~14:30 / 14:30~14:45 / 14:45~15:00。
交叉维度: 四组/阴阳/地基位置/竞价/换手梯度/开口段数/方案点; 关键结论看分年。
"""
import numpy as np
import pandas as pd

pd.set_option("display.width", 340)
pd.set_option("display.max_columns", 100)

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
SEG_ORDER = ["首刻09:30~45", "09:45~10:00", "10:00~10:30", "10:30~11:30",
             "13:00~14:00", "14:00~14:30", "14:30~14:45", "14:45~15:00"]


def load():
    T = pd.read_csv(f"{ROOT}/触板时间明细-全量.csv", dtype={"代码": str})
    T = T.dropna(subset=["触板时间"]).copy()
    E = pd.read_csv(f"{ROOT}/全量明细.csv")
    E = E[~E["未完"]].copy()
    E["年"] = E["年"].astype(str)
    E["换手梯度"] = E["b2换手%"] - E["b1换手%"]
    E["方案点"] = "—"
    E.loc[(E["四组"] == "三接四阳") & E["距60日新高%"].between(-15, -8, inclusive="left")
          & (~E["均线"].isin(["+++", "-++", "+--"])) & (E["前波60日最高板"] == 0), "方案点"] = "A1"
    E.loc[(E["四组"] == "三接四阴") & (E["前波120日最高板"] >= 3)
          & (E["换手梯度"] < -5), "方案点"] = "A2"
    E.loc[(E["四组"] == "二接三阴") & E["b2开盘%"].between(6, 9.5, inclusive="left")
          & E["换手梯度"].between(0, 2, inclusive="left"), "方案点"] = "B1"
    E.loc[(E["四组"] == "二接三阳") & E["距60日新高%"].between(-9, -2, inclusive="left")
          & (E["b2开盘%"] < 0), "方案点"] = "B2"
    keep = ["代码", "买入日", "距60日新高%", "均线", "前波60日最高板", "前波120日最高板",
            "地基涨跌%", "买入开盘%", "b1板型", "b2板型", "b2开盘%", "换手梯度",
            "昨日涨停家数", "链", "封住", "次日收%", "持有到断板%", "结果", "方案点", "最终高度"]
    T = T.merge(E[keep], on=["代码", "买入日"], how="left")
    T = T.dropna(subset=["次日收%"]).copy()
    T["胜"] = T["次日收%"] > 0
    mm = pd.to_datetime(T["触板时间"], format="%H:%M").dt.hour * 60 + \
        pd.to_datetime(T["触板时间"], format="%H:%M").dt.minute
    T["触板段"] = pd.cut(mm, bins=[0, 585, 600, 630, 690, 840, 870, 885, 960],
                        labels=SEG_ORDER)
    T["地基位置档"] = pd.cut(T["距60日新高%"], [-99, -15, -8, -3, 0.01], right=False,
                           labels=["<-15", "-15~-8", "-8~-3", "贴顶-3内"])
    T["竞价档"] = pd.cut(T["买入开盘%"], [-99, 0, 3, 6, 9.5, 99], right=False,
                       labels=["低开", "0~3", "3~6", "6~9.5", "顶格开"])
    T["换手梯度档"] = pd.cut(T["换手梯度"], [-99, -5, 0, 2, 99], right=False,
                           labels=["缩量5点+", "缩量0~5", "放量0~2", "放量2+"])
    T["开口档"] = pd.cut(T["开口段数"], [-1, 0, 1, 2, 99], labels=["0段", "1段", "2段", "3段+"])
    return T


def cross(T, dim, title, lines, min_n=10):
    lines.append(f"\n### {title}")
    t = T.groupby(["触板段", dim], observed=True).agg(
        n=("胜", "size"), 胜率=("胜", "mean"), 持有=("持有到断板%", "mean"),
        封住率=("封住", "mean"))
    pv_n = t["n"].reset_index().pivot(index="触板段", columns=dim, values="n")
    pv_w = t["胜率"].reset_index().pivot(index="触板段", columns=dim, values="胜率")
    pv_r = t["持有"].reset_index().pivot(index="触板段", columns=dim, values="持有")
    pv_f = t["封住率"].reset_index().pivot(index="触板段", columns=dim, values="封住率")
    header = ["触板段"] + [str(c) for c in pv_n.columns]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    lines.append("（每格 = 封住率/次日胜率/持有均值，样本量）")
    for seg in SEG_ORDER:
        if seg not in pv_n.index:
            continue
        row = [seg]
        for c in pv_n.columns:
            n = pv_n.loc[seg, c]
            if n != n or n < min_n:
                row.append(f"薄{int(n)}" if n == n else "--")
            else:
                f, w, r = pv_f.loc[seg, c], pv_w.loc[seg, c], pv_r.loc[seg, c]
                row.append(f"{f*100:.0f}/{w*100:.0f}/{r:+.1f}({int(n)})")
        lines.append("| " + " | ".join(row) + " |")


def yearly_of(sub):
    by = sub.groupby("年").agg(n=("持有到断板%", "size"), 收益=("持有到断板%", "mean"),
                               胜率=("胜", "mean"))
    return " ".join(f"{y}:{r.收益:+.2f}/{r.胜率*100:.0f}%(n={r.n:.0f})" for y, r in by.iterrows())


def main():
    T = load()
    lines = [f"联调全量样本 {len(T)} 笔（2024-08-15 ~ 2026-09，通达信15mK）",
             "每格 = 封住率%/次日胜率%/持有均值(样本量)；薄=n<10",
             "",
             "## 全局时段地图",
             ""]
    g = T.groupby("触板段", observed=True).agg(n=("胜", "size"), 封住率=("封住", "mean"),
                                               胜率=("胜", "mean"), 持有=("持有到断板%", "mean"))
    lines.append(g.round(2).to_string())
    lines.append("\n## 交叉")
    cross(T, "四组", "时段 × 四组", lines)
    cross(T, "阴阳", "时段 × 阴阳", lines)
    cross(T, "地基位置档", "时段 × 地基位置", lines)
    cross(T, "竞价档", "时段 × 竞价开盘", lines)
    cross(T, "换手梯度档", "时段 × 换手梯度（静态缩量）", lines)
    cross(T, "开口档", "时段 × 触板后开口段数", lines)
    cross(T, "方案点", "时段 × 方案点（命中票）", lines)

    lines.append("\n## 开口段数 × 四组")
    t2 = T.groupby(["开口档", "四组"], observed=True).agg(
        n=("胜", "size"), 封住率=("封住", "mean"), 胜率=("胜", "mean"), 持有=("持有到断板%", "mean"))
    lines.append(t2.round(2).to_string())

    lines.append("\n## 前置板开口段数（接力链质量）× 结局")
    for k in (1, 2, 3):
        col = f"b{k}开口段数"
        tk = T.dropna(subset=[col]).copy()
        tk["档"] = pd.cut(tk[col], [-1, 0, 1, 2, 99], labels=["0段", "1段", "2段", "3段+"])
        t3 = tk.groupby("档", observed=True).agg(n=("胜", "size"), 胜率=("胜", "mean"),
                                                 持有=("持有到断板%", "mean"))
        lines.append(f"\n第{k}板开口段数（n={len(tk)}）:")
        lines.append(t3.round(2).to_string())

    lines.append("\n## 关键格子的分年稳定性")
    checks = [
        ("尾盘偷袭(14:30后首触)", T[T["触板段"].isin(["14:30~14:45", "14:45~15:00"])]),
        ("首刻09:30~45", T[T["触板段"] == "首刻09:30~45"]),
        ("首刻 × 开口≤1段", T[(T["触板段"] == "首刻09:30~45") & (T["开口段数"] <= 1)]),
        ("首刻 × 开口≥2段", T[(T["触板段"] == "首刻09:30~45") & (T["开口段数"] >= 2)]),
        ("方案点命中(全部)", T[T["方案点"] != "—"]),
        ("方案点命中 × 首刻", T[(T["方案点"] != "—") & (T["触板段"] == "首刻09:30~45")]),
        ("方案点命中 × 非首刻", T[(T["方案点"] != "—") & (T["触板段"] != "首刻09:30~45")]),
    ]
    for name, sub in checks:
        if len(sub):
            lines.append(f"- {name}: n={len(sub)} 封住率{sub['封住'].mean()*100:.0f}% "
                         f"胜率{sub['胜'].mean()*100:.0f}% 持有{sub['持有到断板%'].mean():+.2f} | "
                         f"{yearly_of(sub)}")

    text = "\n".join(lines)
    print(text)
    with open(f"{ROOT}/汇总/买入时间联调.md", "w", encoding="utf-8") as f:
        f.write("# 高位接力 · 买入时间 × 条件研究 联调（全量回补版 2026-09-19, "
                "2024-08-15~2026-09 共2386笔, 通达信15mK）\n\n" + text + "\n")


if __name__ == "__main__":
    main()
