# -*- coding: utf-8 -*-
"""高位接力 · 好差票验证月度文件加「链式方案」列。

在每个 好差票验证/<组>/YYYY-MM.md 的表格「方案点」列后插入「链式」列,
标注该票命中连板链组合研究的 A1~D2 方案(依据 汇总/连板链组合总结.md), 未命中=「—」。
研究侧重跑月度文件后, 再执行本脚本即可补列。

宿主机纯CSV: uv run python relay_chain_tag.py
"""
import os
import re

import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
BASE = f"{ROOT}/好差票验证"
B4 = [(-99, 0, "低"), (0, 3, "平"), (3, 7, "高"), (7, 99, "强")]


def cut4(s):
    out = pd.Series(index=s.index, dtype="object")
    for lo, hi, lab in B4:
        out[(s >= lo) & (s < hi)] = lab
    return out


def today(d, lo, hi):
    return (d["买入开盘%"] >= lo) & (d["买入开盘%"] < hi)


# 与 relay_summary2.GROUP_TOP2 保持一致(字母编号 A=二接三阳 B=二接三阴 C=三接四阳 D=三接四阴)
SCHEMES = [
    ("A1", "二接三阳", lambda d: (d["一板"] == "低") & (d["二板"] == "低") & today(d, 6, 9.5)),
    ("A2", "二接三阳", lambda d: (d["一板"] == "平") & (d["二板"] == "平") & today(d, 6, 9.5)),
    ("B1", "二接三阴", lambda d: (d["一板"] == "强") & (d["二板"] == "强") & today(d, 3, 6)),
    ("C1", "三接四阳", lambda d: (d["三板"] == "高") & (d["买入开盘%"] < 0)),
    ("C2", "三接四阳", lambda d: (d["一板"] == "平") & (d["二板"] == "强") & today(d, 6, 9.5)),
    ("D1", "三接四阴", lambda d: (d["三板"] == "低") & today(d, 6, 9.5)),
    ("D2", "三接四阴", lambda d: (d["一板"] == "平") & (d["二板"] == "平") & today(d, 6, 9.5)),
]


def load_tags():
    E = pd.read_csv(f"{ROOT}/全量明细.csv", dtype={"代码": str})
    M = E.copy()
    M["一板"] = cut4(M["b1开盘%"])
    M["二板"] = cut4(M["b2开盘%"])
    M["三板"] = cut4(pd.Series(np.where(M["组"] == "二接三", M["买入开盘%"], M["b3开盘%"]), index=M.index))
    tags = {}
    for no, g, fn in SCHEMES:
        sel = M[(M["四组"] == g) & (M["买入开盘%"] < 9.5) & fn(M)]
        for _, r in sel.iterrows():
            tags[(r["代码"], r["买入日"])] = no          # 同票多方案命中取最后写入(罕见)
    return tags


def patch_file(path, tags):
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    out, hit, rows = [], 0, 0
    for ln in lines:
        if ln.startswith("|") and "代码" in ln and "方案点" in ln:
            cells = [c.strip() for c in ln.split("|")]
            i = cells.index("方案点")
            cells.insert(i + 1, "链式")
            out.append("| " + " | ".join(c for c in cells[1:-1] if True) + " |")
            continue
        if ln.startswith("|---"):
            out.append(ln + "---|")
            continue
        if ln.startswith("|") and ".S" in ln:
            cells = ln.split("|")
            if len(cells) >= 8:                        # 数据行
                code, date = cells[1].strip(), cells[3].strip()
                tag = tags.get((code, date), "—")
                cells.insert(6, f" {tag} ")
                out.append("|".join(cells))
                rows += 1
                if tag != "—":
                    hit += 1
                continue
        out.append(ln)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return rows, hit


def main():
    tags = load_tags()
    print(f"链式方案命中 {len(tags)} 笔")
    total_rows = total_hit = n_files = 0
    for grp in ["二接三阳", "二接三阴", "三接四阳", "三接四阴"]:
        d = f"{BASE}/{grp}"
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".md"):
                continue
            rows, hit = patch_file(f"{d}/{fn}", tags)
            total_rows += rows
            total_hit += hit
            n_files += 1
    print(f"处理 {n_files} 个月度文件, 数据行 {total_rows}, 命中标注 {total_hit}")


if __name__ == "__main__":
    main()
