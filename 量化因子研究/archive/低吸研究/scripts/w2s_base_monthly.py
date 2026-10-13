# -*- coding: utf-8 -*-
"""月度md升级为 地基分组版: 每月 × 每地基 → 差票/好票分表 + 月内小计.

输入: 弱转强v3/地基研究/补涨阴地基全量.csv (w2s_base_type.py 产出)
输出: 覆盖 弱转强v3/地基研究/补涨阴/YYYY-MM.md
地基块顺序 = 板留从好到差: U > 横盘 > 中位 > 新高 > 趴底 > 阴跌 > V末反(样本小殿后)
"""
import csv
import os
from collections import defaultdict

SRC = "/root/project/ai/vnpy/量化因子研究/低吸研究/弱转强v3/地基研究/补涨阴地基全量.csv"
OUT_DIR = "/root/project/ai/vnpy/量化因子研究/低吸研究/弱转强v3/好差票验证/补涨阴"

ORDER = ["U", "FLAT", "MID", "HIGH", "LB", "DN", "V"]
BAD_RES = {"炸板", "封D1负"}
COLS = ["代码", "名称", "D0", "结果", "D1开%", "D1收%", "板留%", "回撤%", "蹲深%", "弹回%",
        "低点位置", "振幅%", "断板", "上波高", "昨幅%", "昨涨停家", "V3"]
HEADER = "| " + " | ".join(COLS) + " |"
SEP = "|" + "---|" * len(COLS)


def row(r):
    return (f"| {r['vt_symbol']} | {r['name']} | {r['date']} | {r['res']} "
            f"| {float(r['D1开%']):+.1f} | {float(r['D1收%']):+.1f} | {float(r['板留%']):+.1f} "
            f"| {float(r['回撤%']):+.1f} | {float(r['蹲深%']):+.1f} | {float(r['弹回%']):+.1f} "
            f"| {float(r['低点位置']):.2f} | {float(r['振幅%']):.0f} | {float(r['断板']):.0f} "
            f"| {float(r['上波高']):.0f} | {float(r['昨幅%']):+.1f} | {float(r['昨涨停家']):.0f} "
            f"| {'✓' if r['is_wv'] in ('True', 'True ') else ''} |")


def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def main():
    with open(SRC, encoding="utf-8-sig") as f:
        data = list(csv.DictReader(f))
    by_month = defaultdict(list)
    for r in data:
        by_month[r["ym"]].append(r)

    for ym in sorted(by_month):
        sub = by_month[ym]
        by_base = defaultdict(list)
        for r in sub:
            by_base[r["地基"].split("·")[0]].append(r)
        n_bad = sum(r["res"] in BAD_RES for r in sub)
        lines = [
            f"# 补涨阴 · {ym} · 地基分组好差票", "",
            f"触发 {len(sub)} 笔 | 差票 {n_bad} | 好票 {len(sub) - n_bad} | "
            f"差票率 {n_bad / len(sub) * 100:.0f}%",
            "地基块顺序 = 全量板留从好到差(U+2.11 > 横盘+1.10 > 中位+1.09 > 新高+0.36 > "
            "趴底+0.24 > 阴跌+0.18 > V末反样本小殿后)。",
            "差票 = D0炸板 或 封板但D1收<0(相对涨停价买入); 好票 = 封D1正/连板。",
            "",
        ]
        for kind, pool in [("差票", [r for r in sub if r["res"] in BAD_RES]),
                           ("好票", [r for r in sub if r["res"] not in BAD_RES])]:
            m_d1 = mean([float(r["D1收%"]) for r in pool])
            m_bh = mean([float(r["板留%"]) for r in pool])
            lines += [
                f"## {'🟢' if kind == '好票' else '🔴'} {kind} — {len(pool)}笔"
                + (f"（连板 {sum(r['res'] == '连板' for r in pool)}）" if kind == "好票" else "")
                + f" | 均D1收 {m_d1:+.2f} 均板留 {m_bh:+.2f} | 按地基分组 ↓",
                "",
            ]
            for base in ORDER:
                grp = [r for r in pool if r["地基"].split("·")[0] == base]
                if not grp:
                    continue
                extra = (f"（连板 {sum(r['res'] == '连板' for r in grp)}）" if kind == "好票"
                         else f"（占月内差票 {len(grp) / len(pool) * 100:.0f}%）")
                lines += [
                    f"### {grp[0]['地基']} — {len(grp)}笔{extra} | "
                    f"均D1收 {mean([float(r['D1收%']) for r in grp]):+.2f} "
                    f"均板留 {mean([float(r['板留%']) for r in grp]):+.2f}",
                    "", HEADER, SEP,
                ]
                lines += [row(r) for r in sorted(grp, key=lambda x: -float(x["D1收%"])
                                                 if kind == "好票" else float(x["D1收%"]))]
                lines.append("")
        with open(os.path.join(OUT_DIR, f"{ym}.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    print(f"已重写 {len(by_month)} 个月度md(地基分组版): {OUT_DIR}/YYYY-MM.md")


if __name__ == "__main__":
    main()
