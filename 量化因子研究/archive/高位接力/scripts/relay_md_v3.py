# -*- coding: utf-8 -*-
"""高位接力 · 月度文件附加十点类别 + 十点命中清单单文件（第三十四遍v2）。

主人要求(2026-09-26):
  ① 旧月度文件(全量触发票好差票清单)全部保留,只在每票「方案」行附加十点类别;
  ② 新十点命中的票合并成一个文件(十点命中清单.md),A/B/C/D 分章,内容按年月为标题。
宿主机纯CSV: uv run python relay_md_v3.py
"""
import re
from pathlib import Path

import pandas as pd

ROOT = Path("/root/project/ai/vnpy/量化因子研究/高位接力")
OUT = ROOT / "好差票验证"
GROUPS = [("二接三阳", "A"), ("二接三阴", "B"), ("三接四阳", "C"), ("三接四阴", "D")]

# 十点定义: (点号, 名称, 组目录, 条件描述列表[(key, label)], 判定函数)
# key: b1=一板开 b2=二板开 b3=三板开 v2=二板换手 t=今天开
SCHEMES = {
    "A1": ("双低贴零", "二接三阳",
           [("b1", "一板低开(<0)"), ("b2", "二板<1(低开或贴零)"), ("v2", "二板换手<12"), ("t", "今天开6~9.5")]),
    "A2": ("平启贴零", "二接三阳",
           [("b1", "一板平开(0~3)"), ("b2", "二板0~1(贴零)"), ("t", "今天开6~9.5")]),
    "A3": ("一字急锁缓启", "二接三阳",
           [("b1", "一板≥3(高/强开)"), ("b2", "二板一字(≥9.5)"), ("t", "今天开7~8.5")]),
    "B1": ("强强活跃温开", "二接三阴",
           [("b1", "一板强开(≥7)"), ("b2", "二板强开(≥7)"), ("v2", "二板换手≥5"), ("t", "今天开3~5")]),
    "B2": ("低洗走强", "二接三阴",
           [("b1", "一板低开(<0)"), ("b2", "二板7~8.5(走强)"), ("t", "今天开6~9.5")]),
    "C1": ("放量高板低吸", "三接四阳",
           [("b3", "三板5~7(高开)"), ("t", "今天低开(<0)")]),
    "C2": ("双一字确认", "三接四阳",
           [("b1", "一板平开(0~3)"), ("b2", "二板一字(≥9.5)"), ("b3", "三板一字(≥9.5)"), ("t", "今天开6~9.5")]),
    "D1": ("低板转强", "三接四阴",
           [("b3", "三板低开(<0)"), ("t", "今天开6~9.5")]),
    "D2": ("低洗平推", "三接四阴",
           [("b1", "一板<3(低/平开)"), ("b3", "三板0~3(平开)"), ("t", "今天开6~9.5")]),
    "D3": ("贴零温开", "三接四阴",
           [("b2", "二板<1(低开或贴零)"), ("t", "今天开3~6")]),
}


def _cond_ok(key, r):
    b1, b2 = r.get("b1开盘%"), r.get("b2开盘%")
    b3 = r.get("b3开盘%")
    v2, t = r.get("b2换手%"), r.get("买入开盘%")
    if key == "b1": return b1 is not None and b1 < 0
    if key == "b2<1": return b2 is not None and b2 < 1
    raise ValueError(key)


def judge(r):
    """十点判定: 返回 (点位 or None, 顶格?)。顶格=今天开≥9.5。"""
    t = r.get("买入开盘%")
    if t is None or t >= 9.5:
        return None, True
    grp_dir = r["_grp_dir"]
    b1, b2 = r.get("b1开盘%"), r.get("b2开盘%")
    b3 = r.get("b3开盘%")
    b3 = None if b3 is not None and pd.isna(b3) else b3
    v2 = r.get("b2换手%")
    for no, (nm, gdir, conds) in SCHEMES.items():
        if gdir != grp_dir:
            continue
        ok = True
        for key, _label in conds:
            if key == "b1":
                if no == "A1" and not (b1 is not None and b1 < 0): ok = False
                elif no == "A2" and not (b1 is not None and 0 <= b1 < 3): ok = False
                elif no == "A3" and not (b1 is not None and b1 >= 3): ok = False
                elif no == "B1" and not (b1 is not None and b1 >= 7): ok = False
                elif no == "B2" and not (b1 is not None and b1 < 0): ok = False
                elif no == "C2" and not (b1 is not None and 0 <= b1 < 3): ok = False
                elif no == "D2" and not (b1 is not None and b1 < 3): ok = False
            elif key == "b2":
                if no == "A1" and not (b2 is not None and b2 < 1): ok = False
                elif no == "A2" and not (b2 is not None and 0 <= b2 < 1): ok = False
                elif no == "A3" and not (b2 is not None and b2 >= 9.5): ok = False
                elif no == "B1" and not (b2 is not None and b2 >= 7): ok = False
                elif no == "B2" and not (b2 is not None and 7 <= b2 < 8.5): ok = False
                elif no == "C2" and not (b2 is not None and b2 >= 9.5): ok = False
                elif no == "D3" and not (b2 is not None and b2 < 1): ok = False
            elif key == "b3":
                if b3 is None: ok = False
                elif no == "C1" and not (5 <= b3 < 7): ok = False
                elif no == "C2" and not (b3 >= 9.5): ok = False
                elif no == "D1" and not (b3 < 0): ok = False
                elif no == "D2" and not (0 <= b3 < 3): ok = False
            elif key == "v2":
                if no == "A1" and not (v2 is not None and not pd.isna(v2) and v2 < 12): ok = False
                elif no == "B1" and not (v2 is not None and not pd.isna(v2) and v2 >= 5): ok = False
            elif key == "t":
                if no == "C1" and not (t < 0): ok = False
                elif no == "A3" and not (7 <= t < 8.5): ok = False
                elif no == "B1" and not (3 <= t < 5): ok = False
                elif no == "D3" and not (3 <= t < 6): ok = False
                elif no in ("A1", "A2", "B2", "C2", "D1", "D2") and not (t >= 6): ok = False
            if not ok:
                break
        if ok:
            return no, False
    return None, False


def scheme_line(r):
    """每票「- 方案：」行的十点版内容。"""
    point, gap = judge(r)
    if gap:
        return "- 方案：—（开盘≥9.5%顶格，买不进不计）"
    if point:
        nm = SCHEMES[point][0]
        return f"- 方案：{point}【{nm}】"
    parts = []
    for no, (nm, gdir, cs) in SCHEMES.items():
        if gdir != r["_grp_dir"]:
            continue
        miss = cond_miss(no, r)
        if miss:
            parts.append(f"{no}差[{'；'.join(miss)}]")
    return f"- 方案：—（{'；'.join(parts)}）" if parts else "- 方案：—"


def cond_miss(no, r):
    """该点未满足的条件标签列表。"""
    b1, b2 = r.get("b1开盘%"), r.get("b2开盘%")
    b3 = r.get("b3开盘%")
    b3 = None if b3 is not None and pd.isna(b3) else b3
    v2 = r.get("b2换手%")
    t = r.get("买入开盘%")
    labels = dict(SCHEMES[no][2])
    miss = []
    for key, label in SCHEMES[no][2]:
        bad = False
        if key == "b1":
            bad = not ({"A1": b1 is not None and b1 < 0,
                        "A2": b1 is not None and 0 <= b1 < 3,
                        "A3": b1 is not None and b1 >= 3,
                        "B1": b1 is not None and b1 >= 7,
                        "B2": b1 is not None and b1 < 0,
                        "C2": b1 is not None and 0 <= b1 < 3,
                        "D2": b1 is not None and b1 < 3}[no])
        elif key == "b2":
            bad = not ({"A1": b2 is not None and b2 < 1,
                        "A2": b2 is not None and 0 <= b2 < 1,
                        "A3": b2 is not None and b2 >= 9.5,
                        "B1": b2 is not None and b2 >= 7,
                        "B2": b2 is not None and 7 <= b2 < 8.5,
                        "C2": b2 is not None and b2 >= 9.5,
                        "D3": b2 is not None and b2 < 1}[no])
        elif key == "b3":
            bad = not ({"C1": b3 is not None and 5 <= b3 < 7,
                        "C2": b3 is not None and b3 >= 9.5,
                        "D1": b3 is not None and b3 < 0,
                        "D2": b3 is not None and 0 <= b3 < 3}[no])
        elif key == "v2":
            vv = v2 is not None and not pd.isna(v2)
            bad = not ({"A1": vv and v2 < 12, "B1": vv and v2 >= 5}[no])
        elif key == "t":
            bad = not ({"A1": t >= 6, "A2": t >= 6, "A3": 7 <= t < 8.5,
                        "B1": 3 <= t < 5, "B2": t >= 6, "C1": t < 0,
                        "C2": t >= 6, "D1": t >= 6, "D2": t >= 6, "D3": 3 <= t < 6}[no])
        if bad:
            miss.append(label)
    return miss


def main():
    E = pd.read_csv(ROOT / "全量明细.csv", dtype={"代码": str})
    E["买入日"] = pd.to_datetime(E["买入日"])
    E["胜"] = ~E["坏票"].fillna(True).astype(bool)
    E = E[~E["未完"]]
    lookup = {}
    for _, r in E.iterrows():
        gdir = next(g for g, _ in GROUPS if g.startswith("二接三") == (r["组"] == "二接三"))
        gdir = (r["组"] + ("阳" if r["阴阳"] == "阳" else "阴"))
        lookup[(str(r["代码"]), r["买入日"].strftime("%Y-%m-%d"))] = {
            "_grp_dir": gdir, "b1开盘%": r["b1开盘%"], "b2开盘%": r["b2开盘%"],
            "b3开盘%": r.get("b3开盘%"), "b2换手%": r["b2换手%"],
            "买入开盘%": r["买入开盘%"], "胜": bool(r["胜"]),
            "持有到断板%": r["持有到断板%"], "名称": r["名称"].strip(), "代码": str(r["代码"])}

    hits = []           # (组目录, AB, 年月, 票dict)
    total_touched = 0
    for gdir, ab in GROUPS:
        group_pts = [(no, v[0]) for no, v in SCHEMES.items() if v[1] == gdir]
        header_lines = ["**本组链式方案·十点版(买入前可知 × 今天竞价，命中才出手)**"] + [
            f"- **{no}【{nm}】**：" + " × ".join(l for _, l in SCHEMES[no][2])
            for no, nm in group_pts]
        header_block = ("\n".join(header_lines) + "\n"
                        "- 「—」= 未命中不出手；差的条件在每票「方案」行逐条列出\n")
        for f in sorted((OUT / gdir).glob("*.md")):
            if f.name.startswith("_"):
                continue
            new_text = rebuild(f.read_text(encoding="utf-8"), header_block, lookup, (gdir, f.name))
            f.write_text(new_text, encoding="utf-8")
            total_touched += 1
        print(f"{gdir}: 完成")

    write_merged()
    n_hit = sum(len(v) for v in REBUILD_CACHE.values())
    print(f"月度文件改写 {total_touched} 个, 十点命中 {n_hit} 笔")


def cur_month(fname):
    return fname.replace(".md", "")


def rebuild(text, header_block, lookup, cache_key):
    """整体重写: 标题命中数/头部方案块/统计行命中段/每票方案行。"""
    lines = text.splitlines()
    out = []
    cur_code = cur_date = None
    n_hit = 0
    hit_stats = []
    skip_old_scheme = False
    for ln in lines:
        m = re.match(r"^### (.+?) (\S+)｜(\d{4}-\d{2}-\d{2})", ln)
        if m:
            cur_code, cur_date = m.group(2), m.group(3)
            skip_old_scheme = False
            out.append(ln)
            continue
        if ln.startswith("**本组链式方案"):
            out.append(header_block)
            skip_old_scheme = True      # 跳过旧行直到「- 首刻参考」或空行后新块
            continue
        if skip_old_scheme:
            if ln.startswith("- 首刻参考") or ln.startswith("**判定标准"):
                skip_old_scheme = False
                # 首刻行改写交给下方新规则; 判定标准行直接放行
                if ln.startswith("**判定标准"):
                    out.append(ln)
                    continue
            else:
                continue
        if ln.startswith("> 方案 = 连板链组合方案"):
            out.append("> 方案 = 连板链组合方案 A1~D3 十点（条件见本目录《链式方案策略.md》）")
            continue
        if ln.startswith("- 首刻参考"):
            out.append("- 触板口径 = 盘中首次触涨停价即买（十点方案无时间窗）；无分钟存档=2024-08-15前")
            continue
        if ln.startswith("- 方案：") and cur_code and cur_date:
            r = lookup.get((cur_code, cur_date))
            if r is None:
                out.append(ln)
            else:
                out.append(scheme_line(r))
                point, _g = judge(r)
                if point:
                    n_hit += 1
                    hit_stats.append((point, r))
            continue
        out.append(ln)
    # 标题命中数
    out[0] = re.sub(r"本月命中 \d+ 笔", f"本月命中 {n_hit} 笔", out[0])
    # 统计行命中段(v2.0 格式 "| **命中 X（...）n笔/胜率x%/-y**") 替换十点版
    if hit_stats:
        pts = "、".join(sorted({p for p, _ in hit_stats}))
        win = sum(1 for _, r in hit_stats if r["胜"]) / len(hit_stats)
        avg = sum(r["持有到断板%"] for _, r in hit_stats) / len(hit_stats)
        seg = f" | **十点命中 {len(hit_stats)} 笔（{pts}）胜率{win*100:.0f}%/均{avg:+.2f}**"
        for i, ln in enumerate(out):
            if re.search(r"\| \*\*命中 .*?\*\*$", ln):
                out[i] = re.sub(r"( \| \*\*命中 .*?\*\*)$", seg, ln)
                break
            if re.search(r"坏票率 \d+%( \| \*\*命中 .*?\*\*)?$", ln) and i < 12:
                if not re.search(r"\*\*命中", ln):
                    out[i] = ln + seg
                    break
    # 票目汇总(收集给单文件)
    REBUILD_CACHE[cache_key] = hit_stats
    return "\n".join(out)


REBUILD_CACHE: dict[str, list] = {}


def write_merged():
    """十点命中清单.md: A/B/C/D 章 → 年月标题 → 好差票形式。"""
    # 从 REBUILD_CACHE 汇集(带月文件名)
    rows = []
    for (gdir, fname), stats in REBUILD_CACHE.items():
        month = cur_month(fname)
        for point, r in stats:
            rows.append((point, month, r))
    point_order = {no: i for i, no in enumerate(SCHEMES)}
    rows.sort(key=lambda x: (point_order[x[0]], x[1], x[2]["名称"]))
    lines = ["# 高位接力 · 十点方案命中清单（每点一章 × 年月）", "",
             "> 2026-09-26 十点定稿（hpr-v3.0）｜2023-03 ~ 2026-09 全市场回放｜正常开盘口径（开盘≥9.5%顶格不计）",
             "> A=二接三阳 B=二接三阴 C=三接四阳 D=三接四阴；条件与成绩详见本目录《链式方案策略.md》",
             "> 全量触发票逐笔见各分组月文件（每票「方案」行已附十点类别）",
             f"> 十点命中合计 {len(rows)} 笔（研究口径；D3 含 3 笔未真实触板票，产品回测按 10 笔记账）", ""]
    cur_point = cur_month_key = None
    for point, month, r in rows:
        if point != cur_point:
            nm, gdir = SCHEMES[point][0], SCHEMES[point][1]
            lines += [f"## {point}【{nm}】｜{gdir}", ""]
            cur_point, cur_month_key = point, None
        if month != cur_month_key:
            lines += [f"### {month}", ""]
            cur_month_key = month
        verdict = "好票" if r["胜"] else "差票"
        lines.append(f"- **{r['名称']} {r['代码']}｜{r['买入开盘%']:+.1f}%开｜{verdict}** "
                     f"断板{r['持有到断板%']:+.1f}%")
    (OUT / "十点命中清单.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
