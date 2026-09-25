# -*- coding: utf-8 -*-
"""高位接力 · 好差票验证月度文件切换到链式方案 A1~D2（去掉旧 v1.3 方案点判定）。

- 每票「方案」行 = 命中 A1~D2 或 —（差的条件按新方案逐条列出）
- 删除旧 v1.3 方案点行/不符合在哪
- 文件头说明区换成链式方案清单
- 月度统计「本月无命中」换成链式命中数

宿主机纯CSV: uv run python relay_md_replan.py
"""
import os

import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
BASE = f"{ROOT}/好差票验证"
B4 = [(-99, 0, "低"), (0, 3, "平"), (3, 7, "高"), (7, 99, "强")]
GROUPS = ["二接三阳", "二接三阴", "三接四阳", "三接四阴"]


def cut4(s):
    out = pd.Series(index=s.index, dtype="object")
    for lo, hi, lab in B4:
        out[(s >= lo) & (s < hi)] = lab
    return out


def today(d, lo, hi):
    return (d["买入开盘%"] >= lo) & (d["买入开盘%"] < hi)


# (编号, 名, 组, 条件描述+判定fn列表) —— 与 relay_summary2.GROUP_TOP2 一致
SCHEMES = [
    ("A1", "双低转强", "二接三阳", [
        ("一板低开(<0%)", lambda d: d["一板"] == "低"),
        ("二板低开(<0%)", lambda d: d["二板"] == "低"),
        ("今天开6~9.5%", lambda d: today(d, 6, 9.5))]),
    ("A2", "双平转强", "二接三阳", [
        ("一板平开(0~3%)", lambda d: d["一板"] == "平"),
        ("二板平开(0~3%)", lambda d: d["二板"] == "平"),
        ("今天开6~9.5%", lambda d: today(d, 6, 9.5))]),
    ("B1", "强强高启", "二接三阴", [
        ("一板强开(≥7%)", lambda d: d["一板"] == "强"),
        ("二板强开(≥7%)", lambda d: d["二板"] == "强"),
        ("今天开3~5%", lambda d: today(d, 3, 5))]),
    ("C1", "高板低吸", "三接四阳", [
        ("三板高开(3~7%)", lambda d: d["三板"] == "高"),
        ("今天低开(<0%)", lambda d: d["买入开盘%"] < 0)]),
    ("C2", "平强确认", "三接四阳", [
        ("一板平开(0~3%)", lambda d: d["一板"] == "平"),
        ("二板强开(≥7%)", lambda d: d["二板"] == "强"),
        ("今天开6~9.5%", lambda d: today(d, 6, 9.5))]),
    ("D1", "低板转强", "三接四阴", [
        ("三板低开(<0%)", lambda d: d["三板"] == "低"),
        ("今天开6~9.5%", lambda d: today(d, 6, 9.5))]),
    ("D2", "平推转强", "三接四阴", [
        ("一板平开(0~3%)", lambda d: d["一板"] == "平"),
        ("二板平开(0~3%)", lambda d: d["二板"] == "平"),
        ("今天开6~9.5%", lambda d: today(d, 6, 9.5))]),
]


def load():
    E = pd.read_csv(f"{ROOT}/全量明细.csv", dtype={"代码": str})
    M = E.copy()
    M["一板"] = cut4(M["b1开盘%"])
    M["二板"] = cut4(M["b2开盘%"])
    M["三板"] = cut4(pd.Series(np.where(M["组"] == "二接三", M["买入开盘%"], M["b3开盘%"]), index=M.index))
    M["正常"] = M["买入开盘%"] < 9.5
    # 每票的方案判定
    verdict = {}
    for _, r in M.iterrows():
        row = M.loc[[r.name]]
        if not bool(row["正常"].iloc[0]):
            verdict[(r["代码"], r["买入日"])] = "—（开盘≥9.5%顶格，买不进不计）"
            continue
        hit, misses = None, []
        for no, nm, g, conds in SCHEMES:
            if g != r["四组"]:
                continue
            ok = True
            bad = []
            for desc, fn in conds:
                if not bool(fn(row).iloc[0]):
                    bad.append(desc)
            if not bad:
                hit = f"{no}【{nm}】"
                break
            misses.append(f"{no}差[{'；'.join(bad)}]")
        if hit:
            verdict[(r["代码"], r["买入日"])] = hit
        else:
            verdict[(r["代码"], r["买入日"])] = "—（" + "；".join(misses) + "）"
    return M, verdict


def group_block(g):
    lines = ["**本组链式方案（买入前可知 × 今天竞价，命中才出手）**"]
    for no, nm, gg, conds in SCHEMES:
        if gg == g:
            lines.append(f"- **{no}【{nm}】**：{' × '.join(c[0] for c in conds)}")
    lines.append("- 「—」= 未命中不出手；差的条件在每票「方案」行逐条列出")
    lines.append("- 首刻参考 = 开盘15分钟内首次触板（09:30~09:45）才出手；非首刻=放弃；无数据=2024-08-15前无分钟存档")
    return lines


def month_hits(M, grp, ym):
    sel = M[(M["四组"] == grp) & (M["月"] == ym) & (M["正常"])]
    hit_codes = set()
    for no, nm, g, conds in SCHEMES:
        if g != grp:
            continue
        m = sel
        for _, fn in conds:
            m = m[fn(m)]
        hit_codes.update(zip(m["代码"], m["买入日"]))
    return len(hit_codes)


def convert(path, grp, M, verdict):
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    if not any("链式方案：" in x or "- 方案：" in x for x in lines):
        return False
    ym = os.path.basename(path)[:-3]
    hits = month_hits(M, grp, ym)
    out = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if "（方案点已标记）" in s:
            out.append(s.replace("（方案点已标记）", f"（链式方案标记，本月命中 {hits} 笔）"))
        elif "（链式方案标记" in s:
            out.append(f"{s.split('（链式方案标记')[0]}（链式方案标记，本月命中 {hits} 笔）")
        elif s.startswith("> 链式方案"):
            out.append("> 方案 = 连板链组合方案 A1~D2（条件见本目录《链式方案策略.md》）")
        elif s.startswith("**本组方案点") or s.startswith("**本组链式方案"):
            # 跳过旧/已有说明块直到 **判定标准**, 用当前方案重新生成
            while i < len(lines) and not lines[i].strip().startswith("**判定标准**"):
                i += 1
            out.extend(group_block(grp))
            out.append("")
            out.append(lines[i])
        elif s.startswith("- v1.3方案点") or s.startswith("- 不符合在哪") or s.startswith("- 不符合"):
            pass                                        # 旧方案行删除
        elif s.startswith("- 链式方案：") or s.startswith("- 方案："):
            code, date = None, None
            for back in range(len(out) - 1, max(-1, len(out) - 12), -1):
                if out[back].startswith("### "):
                    parts = out[back].split("｜")[0].split(" ")
                    code = parts[-1]
                    date = out[back].split("｜")[1]
                    break
            v = verdict.get((code, date), "—") if code else "—"
            out.append(f"- 方案：{v}")
        else:
            out.append(ln)
        i += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return True


def main():
    M, verdict = load()
    n = 0
    for grp in GROUPS:
        d = f"{BASE}/{grp}"
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".md") and convert(f"{d}/{fn}", grp, M, verdict):
                n += 1
    print(f"{n} 个月度文件已切换到链式方案判定")


if __name__ == "__main__":
    main()
