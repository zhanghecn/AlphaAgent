# -*- coding: utf-8 -*-
"""高位接力 · 1/2/3板条件联动研究（第二十一遍）。

主人观察(好差票验证/二接三阳/2023-10.md)：坏票大多差在二板，但二板不低开的好票也不少
（顺发恒能二板+7.8竞价+4.9窗内连板、莲花控股只差二板低开一条、恒润股份二板顶格竞价顶格连板），
猜想：首板/二板/进三竞价三个条件是互动的，不该各自卡死。

本脚本（宿主机纯CSV跑，不需容器）：
1. 二板开盘档 × 进三竞价档 矩阵（四组各一张）；
2. 首板开盘档 × 二板开盘档、首板板型 × 竞价档 辅助矩阵；
3. 梯度 = 竞价% - 二板开盘%（加速/减速）× 二板开盘档；
4. 与地基距新高交叉（B2已有位置窗，看联动格是否要位置配合）；
5. 候选联动格：分年全正 + 边界晃动 + 置换检验。

输出: 汇总/一二三板联动.md
"""
import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
YEARS = ["2023", "2024", "2025", "2026"]
GROUPS4 = ["二接三阴", "二接三阳", "三接四阴", "三接四阳"]

# 统一开盘档（竞价与二板共用，便于看梯度）
OPEN_BINS = [(-99, 0, "低开<0"), (0, 2, "0~2"), (2, 4, "2~4"),
             (4, 7, "4~7"), (7, 9.5, "7~9.5"), (9.5, 99, "顶格≥9.5")]
OPEN_LABELS = [b[2] for b in OPEN_BINS]

GRAD_BINS = [(-99, -6, "减速≥6"), (-6, -3, "减速3~6"), (-3, 0, "减速0~3"),
             (0, 3, "加速0~3"), (3, 6, "加速3~6"), (6, 99, "加速≥6")]
GRAD_LABELS = [b[2] for b in GRAD_BINS]

POS_BINS = [(-99, -15, "深<-15"), (-15, -9, "-15~-9"), (-9, -2, "-9~-2(B2窗)"),
            (-2, 0.01, "-2~0贴顶"), (0.01, 99, "新高")]
POS_LABELS = [b[2] for b in POS_BINS]


def cut_bins(s, bins):
    out = pd.Series("缺失", index=s.index)
    for lo, hi, lab in bins:
        out[(s >= lo) & (s < hi)] = lab
    return out


def load():
    E = pd.read_csv(f"{ROOT}/全量明细.csv", dtype={"代码": str})
    X = pd.read_csv(f"{ROOT}/地基均线反包明细.csv", dtype={"代码": str})
    E = E.merge(X[["代码", "买入日", "距MA10%", "前板高度", "反包结构", "断板天数"]],
                on=["代码", "买入日"], how="left")
    E = E[~E["未完"]].copy()
    E["年"] = E["年"].astype(str)
    E["胜"] = E["次日收%"] > 0
    E["b1开档"] = cut_bins(E["b1开盘%"], OPEN_BINS)
    E["b2开档"] = cut_bins(E["b2开盘%"], OPEN_BINS)
    E["竞价档"] = cut_bins(E["买入开盘%"], OPEN_BINS)
    E["梯度"] = E["买入开盘%"] - E["b2开盘%"]
    E["梯度档"] = cut_bins(E["梯度"], GRAD_BINS)
    E["位置档"] = cut_bins(E["距60日新高%"], POS_BINS)
    return E


def cell(sub):
    if len(sub) < 5:
        return f"{len(sub)}" if len(sub) else ""
    win = sub["胜"].mean() * 100
    hold = sub["持有到断板%"].mean()
    mark = "★" if (hold > 1.5 and win >= 50 and len(sub) >= 10) else ""
    return f"{len(sub)}笔{win:.0f}%{hold:+.1f}{mark}"


def matrix(lines, E, gname, row_col, row_labels, col_col, col_labels, title):
    sub = E[E["四组"] == gname]
    lines.append(f"\n**{gname}**（n={len(sub)}）{title}\n")
    lines.append("| 行\\列 | " + " | ".join(col_labels) + " |")
    lines.append("|---|" + "---|" * len(col_labels))
    for rl in row_labels:
        cells = [cell(sub[(sub[row_col] == rl) & (sub[col_col] == cl)]) for cl in col_labels]
        lines.append(f"| {rl} | " + " | ".join(cells) + " |")
    lines.append("")


def year_str(sub):
    out = []
    for y in YEARS:
        sy = sub[sub["年"] == y]
        out.append(f"{sy['持有到断板%'].mean():+.2f}/{len(sy)}" if len(sy) else "0笔")
    return " | ".join(out)


def all_pos(sub):
    return all(len(sub[sub["年"] == y]) > 0 and
               sub[sub["年"] == y]["持有到断板%"].mean() > 0 for y in YEARS)


def candidates(lines, E):
    """候选联动格: 围绕主人猜想的几族, 逐个分年+晃动+置换。"""
    rng = np.random.default_rng(20260919)
    lines.append("\n## 候选联动格验证（分年全正+晃动+置换2000次）\n")

    def report(name, mask, pool_mask):
        sub = E[mask]
        pool = E[pool_mask]
        n = len(sub)
        if n == 0:
            lines.append(f"### {name}\n0笔\n")
            return
        win = sub["胜"].mean() * 100
        hold = sub["持有到断板%"].mean()
        pv = pool["持有到断板%"].to_numpy()
        p_hold = (rng.choice(pv, size=(2000, n), replace=True).mean(axis=1) >= hold).mean() if n >= 8 else np.nan
        lines.append(f"### {name}\n")
        lines.append(f"- 合计 {n}笔 胜率{win:.0f}% 持有{hold:+.2f}　分年：{year_str(sub)}"
                     f"　{'✅全正' if all_pos(sub) else '❌有负年'}"
                     + (f"　置换p={p_hold:.3f}" if p_hold == p_hold else ""))
        # 列出逐票(<=15笔时)
        if n <= 15:
            names = "、".join(f"{r['名称']}{r['买入日'][2:7]}({r['持有到断板%']:+.0f})"
                              for _, r in sub.sort_values("持有到断板%", ascending=False).iterrows())
            lines.append(f"- 逐票：{names}")
        lines.append("")

    g = "二接三阳"
    gm = E["四组"] == g
    in_win = E["竞价档"] == "4~7"
    lines.append("**第一族：竞价4~7窗内，二板开盘各档的表现（检验「二板必须低开」是否过严）**\n")
    for lab in OPEN_LABELS:
        report(f"{g} × 竞价4~7 × 二板开{lab}", gm & in_win & (E["b2开档"] == lab), gm)
    lines.append("**第二族：二板高开(≥4)时，竞价各档的表现（高开二板的出路在哪）**\n")
    for lab in OPEN_LABELS:
        report(f"{g} × 二板开≥4 × 竞价{lab}", gm & (E["b2开盘%"] >= 4) & (E["竞价档"] == lab), gm)
    lines.append("**第三族：梯度（竞价-二板开）× 二板开档（减速/加速互动）**\n")
    for glab in GRAD_LABELS:
        report(f"{g} × 二板开≥4 × {glab}", gm & (E["b2开盘%"] >= 4) & (E["梯度档"] == glab), gm)
    lines.append("**第四族：有前途的组合 × 位置窗（B2的位置条件要不要保留）**\n")
    for plab in POS_LABELS:
        report(f"{g} × 竞价4~7 × 二板开≥4 × 位置{plab}",
               gm & in_win & (E["b2开盘%"] >= 4) & (E["位置档"] == plab), gm)
    lines.append("**第五族：其他三组同样拆 竞价4~7×二板开档（联动是否二接三阳独有）**\n")
    for g2 in ["二接三阴", "三接四阴", "三接四阳"]:
        gm2 = E["四组"] == g2
        for lab in ["低开<0", "0~2", "2~4", "4~7", "7~9.5", "顶格≥9.5"]:
            report(f"{g2} × 竞价4~7 × 二板开{lab}", gm2 & in_win & (E["b2开档"] == lab), gm2)


def main():
    E = load()
    lines = ["# 高位接力 · 1/2/3板条件联动研究（2026-09-19 第二十一遍）", "",
             "主人猜想：首板/二板/进三竞价三个条件是互动的，B2「二板必须低开」可能过严——",
             "二板高开的好票，区分条件可能在进三竞价开多少。", "",
             "开盘档统一：低开<0 / 0~2 / 2~4 / 4~7(B2窗) / 7~9.5 / 顶格≥9.5。",
             "格内=笔数 胜率% 持有均值；★=笔数≥10且胜率≥50%且持有>+1.5。格<5笔只标笔数。", ""]
    lines.append("\n# 一、二板开盘档 × 进三竞价档 矩阵（核心联动图）")
    for gname in GROUPS4:
        matrix(lines, E, gname, "b2开档", OPEN_LABELS, "竞价档", OPEN_LABELS, "")
    lines.append("\n# 二、首板开盘档 × 二板开盘档（前两板的互动）")
    for gname in GROUPS4:
        matrix(lines, E, gname, "b1开档", OPEN_LABELS, "b2开档", OPEN_LABELS, "")
    lines.append("\n# 三、首板板型 × 进三竞价档")
    for gname in GROUPS4:
        matrix(lines, E, gname, "b1板型", ["一字", "下影", "实体"], "竞价档", OPEN_LABELS, "")
    lines.append("\n# 四、梯度（竞价-二板开） × 位置档（二接三阳）")
    matrix(lines, E, "二接三阳", "梯度档", GRAD_LABELS, "位置档", POS_LABELS, "")
    lines.append("\n# 五、地基大小（涨跌轴） × 竞价档（二接三阳，接第十九遍假阴/假阳发现）")
    size_labels = ["巨阴≤-5", "大阴-5~-3", "小阴-3~0", "小阳0~3", "大阳3~5", "巨阳≥5"]
    E["地基档"] = cut_bins(E["地基涨跌%"], [(-99, -5, "巨阴≤-5"), (-5, -3, "大阴-5~-3"),
                                            (-3, 0, "小阴-3~0"), (0, 3, "小阳0~3"),
                                            (3, 5, "大阳3~5"), (5, 99, "巨阳≥5")])
    matrix(lines, E, "二接三阳", "地基档", size_labels, "竞价档", OPEN_LABELS, "")

    candidates(lines, E)

    text = "\n".join(lines)
    with open(f"{ROOT}/汇总/一二三板联动.md", "w", encoding="utf-8") as f:
        f.write(text)
    print(f"已写 {ROOT}/汇总/一二三板联动.md ({len(text.splitlines())}行)")
    # 控制台直接打核心矩阵: 二接三阳 二板开×竞价
    sub = E[E["四组"] == "二接三阳"]
    print("\n二接三阳 二板开盘×进三竞价 (n=1322):")
    print("行\\列 | " + " | ".join(OPEN_LABELS))
    for rl in OPEN_LABELS:
        print(rl, " | ".join(f"{cell(sub[(sub['b2开档'] == rl) & (sub['竞价档'] == cl)]):>14s}"
                              for cl in OPEN_LABELS))
    print("\n二接三阴 二板开盘×进三竞价 (n=1002):")
    sub = E[E["四组"] == "二接三阴"]
    for rl in OPEN_LABELS:
        print(rl, " | ".join(f"{cell(sub[(sub['b2开档'] == rl) & (sub['竞价档'] == cl)]):>14s}"
                              for cl in OPEN_LABELS))


if __name__ == "__main__":
    main()
