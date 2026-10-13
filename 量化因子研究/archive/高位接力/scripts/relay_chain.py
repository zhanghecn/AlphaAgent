# -*- coding: utf-8 -*-
"""高位接力 · 一板→二板→三板 开盘链匹配规则（第二十三遍）。

主人原话：二板怎么样有什么关系——「二（板）如果是多少，三板就必须多少才行。
然后一板也是：如果一怎么样，二就怎么样，三然后再怎么样」。

= 三级开盘链的匹配规则：一板开盘档 × 二板开盘档 × 三板(进三竞价)开盘档 立方体，
阴阳分开，读法=给定(一X,二Y)，看三板开哪档活、哪档死 → 「一X二Y则三必须Z」。

档：低开<0 / 平0~3 / 高开3~7 / 强开≥7（四档，保样本量）。
宿主机纯CSV: uv run python relay_chain.py
输出: 汇总/开盘链匹配.md
"""
import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
YEARS = ["2023", "2024", "2025", "2026"]
BINS = [(-99, 0, "低开<0"), (0, 3, "平0~3"), (3, 7, "高开3~7"), (7, 99, "强开≥7")]
LABS = [b[2] for b in BINS]
rng = np.random.default_rng(20260919)


def cut(s):
    out = pd.Series("缺失", index=s.index)
    for lo, hi, lab in BINS:
        out[(s >= lo) & (s < hi)] = lab
    return out


def load():
    E = pd.read_csv(f"{ROOT}/全量明细.csv", dtype={"代码": str})
    E = E[~E["未完"]].copy()
    E["年"] = E["年"].astype(str)
    E["胜"] = E["次日收%"] > 0
    E["一档"] = cut(E["b1开盘%"])
    E["二档"] = cut(E["b2开盘%"])
    E["三档"] = cut(E["买入开盘%"])
    return E


def cell(sub):
    if len(sub) < 5:
        return f"{len(sub)}" if len(sub) else "·"
    return f"{len(sub)}笔{sub['胜'].mean() * 100:.0f}%{sub['持有到断板%'].mean():+.1f}"


def year_str(sub):
    return " | ".join(
        f"{sy['持有到断板%'].mean():+.2f}/{len(sy)}" if len(sy := sub[sub["年"] == y]) else "0笔"
        for y in YEARS)


def all_pos(sub):
    return all(len(sub[sub["年"] == y]) > 0 and
               sub[sub["年"] == y]["持有到断板%"].mean() > 0 for y in YEARS)


def main():
    E = load()
    lines = ["# 高位接力 · 一→二→三板开盘链匹配规则（2026-09-19 第二十三遍）", "",
             "读法：每个（一板档×二板档）小表 = 三板（进三竞价）开各档的表现 → 「一X二Y则三必须Z」。",
             "档：低开<0 / 平0~3 / 高开3~7 / 强开≥7。格内=笔数胜率%持有均值，<5笔只标笔数。", ""]

    best_rules = []
    for gname in ["二接三阳", "二接三阴", "三接四阳", "三接四阴"]:
        sub = E[E["四组"] == gname]
        lines.append(f"\n# 【{gname}】n={len(sub)}\n")
        for l1 in LABS:
            for l2 in LABS:
                base = sub[(sub["一档"] == l1) & (sub["二档"] == l2)]
                if len(base) < 10:
                    continue
                row = {l3: base[base["三档"] == l3] for l3 in LABS}
                # 找该(一,二)下最好的三板档
                scored = [(l3, s) for l3, s in row.items() if len(s) >= 5]
                if not scored:
                    continue
                best = max(scored, key=lambda t: t[1]["持有到断板%"].mean())
                bst = best[1]
                lines.append(f"**一{l1} × 二{l2}**（共{len(base)}笔）→ 三板："
                             + "；".join(f"{l3}: {cell(row[l3])}" for l3 in LABS)
                             + f"　**→ 最好=三板{best[0]}（{cell(bst)}）**")
                # 记录可用的规则候选: 最好格持有>+1.5且胜率>=50%
                if bst["持有到断板%"].mean() > 1.5 and bst["胜"].mean() >= 0.5:
                    best_rules.append((gname, l1, l2, best[0], bst))
                lines.append("")

    # ---- 规则候选全量验证 ----
    lines.append("\n# 匹配规则候选验证（分年全正/置换/去尾3/晃动）\n")
    lines.append("| 链规则 | 笔数 | 胜率 | 持有 | 分年(持有/n) | 全正 | 置换p | 去尾3 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    passed = []
    for gname, l1, l2, l3, _ in best_rules:
        sub = E[(E["四组"] == gname) & (E["一档"] == l1) & (E["二档"] == l2) & (E["三档"] == l3)]
        pool = E[E["四组"] == gname]
        n = len(sub)
        hold = sub["持有到断板%"].mean()
        p = (rng.choice(pool["持有到断板%"].to_numpy(), size=(2000, n), replace=True).mean(axis=1) >= hold).mean()
        tri = sub.sort_values("持有到断板%", ascending=False).iloc[3:]
        ok = all_pos(sub)
        lines.append(f"| {gname} 一{l1}→二{l2}→三{l3} | {n} | {sub['胜'].mean() * 100:.0f}% "
                     f"| {hold:+.2f} | {year_str(sub)} | {'✅' if ok else '❌'} | {p:.3f} "
                     f"| {tri['持有到断板%'].mean():+.2f} |")
        if ok:
            passed.append((gname, l1, l2, l3, sub))
    if not best_rules:
        lines.append("| （没有任何（一,二）组合下有持有>+1.5且胜率≥50%的三板档） | | | | | | | |")

    # 通过分年全正的做边界晃动
    if passed:
        lines.append("\n## 通过分年全正的链规则 · 边界晃动（开盘边界±1%）\n")
        lines.append("| 规则 | 变体 | 笔数 | 胜率 | 持有 | 全正 |")
        lines.append("|---|---|---|---|---|---|")
        for gname, l1, l2, l3, sub0 in passed:
            # 用数值边界重建该档的窗口, 每个维度±1晃动
            b1 = dict((lab, (lo, hi)) for lo, hi, lab in BINS)[l1]
            b2 = dict((lab, (lo, hi)) for lo, hi, lab in BINS)[l2]
            b3 = dict((lab, (lo, hi)) for lo, hi, lab in BINS)[l3]

            def m(d1, d2, d3):
                return ((E["四组"] == gname)
                        & (E["b1开盘%"] >= b1[0] + d1) & (E["b1开盘%"] < b1[1] + (d1 if b1[1] < 90 else 0))
                        & (E["b2开盘%"] >= b2[0] + d2) & (E["b2开盘%"] < b2[1] + (d2 if b2[1] < 90 else 0))
                        & (E["买入开盘%"] >= b3[0] + d3) & (E["买入开盘%"] < b3[1] + (d3 if b3[1] < 90 else 0)))
            for tag, d in [("原窗", (0, 0, 0)), ("三板上沿+1", (0, 0, 1)), ("三板上沿-1", (0, 0, -1)),
                           ("二板±1放宽", (0, 1, 0)), ("一板±1放宽", (1, 0, 0))]:
                s = E[m(*d)]
                lines.append(f"| {gname} 一{l1}→二{l2}→三{l3} | {tag} | {len(s)} "
                             f"| {s['胜'].mean() * 100:.0f}% | {s['持有到断板%'].mean():+.2f} "
                             f"| {'✅' if all_pos(s) else '❌'} |")

    text = "\n".join(lines)
    with open(f"{ROOT}/汇总/开盘链匹配.md", "w", encoding="utf-8") as f:
        f.write(text)
    print(f"已写 ({len(text.splitlines())}行)\n")
    # 控制台速览: 只打二接三阳/二接三阴的规则候选
    for ln in lines:
        if ln.startswith("**一") or ln.startswith("| 二接") or "最好=" in ln:
            print(ln)


if __name__ == "__main__":
    main()
