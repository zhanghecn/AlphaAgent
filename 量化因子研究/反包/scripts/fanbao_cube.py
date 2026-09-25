# -*- coding: utf-8 -*-
"""反包 · 多维立方体总表（宿主机纯CSV跑）。

一张表看全: 高度(4/5/6/7/8+) × 阴阳 × 断板天数(1/2/3/4/5/6~10/11+) × 全指标。
阴阳口径 = 主人2026-09-25拍板的跌幅口径: 阴=末日跌(收盘低于前日收盘), 阳=末日涨/平。
(实体口径切分见 fanbao_research.py 八组产物; 两把尺的差异在「低开高走假阳/假阴」票上)
用法: uv run --project /root/project/ai/vnpy python fanbao_cube.py
"""
import pandas as pd

fb = pd.read_csv("/root/project/ai/vnpy/量化因子研究/反包/全量明细.csv", dtype={"代码": str})
fin = fb[(~fb["未完"]) & (fin_ok := (fb["次日收%"] == fb["次日收%"]))].copy()
fin["年"] = fin["年"].astype(str)
fin["末日幅%"] = fin["断板期"].str.extract(r"([+-]\d+\.?\d*)$").astype(float)
H = fin[fin["N"] >= 4].copy()
H["阴阳"] = (H["末日幅%"] >= 0).map({True: "阳(没跌)", False: "阴(跌)"})


def band(g):
    if g <= 5:
        return f"断{g}"
    return "断6~10" if g <= 10 else "断11+"


H["档"] = H["断板天数"].map(band)
COLS = ["断1", "断2", "断3", "断4", "断5", "断6~10", "断11+"]


def cell(s):
    if len(s) == 0:
        return "—"
    return (f"{len(s)}<br>{s['持有到断板%'].mean():+.2f}<br>"
            f"{(s['次日收%'] > 0).mean() * 100:.0f}%/{(~s['封住']).mean() * 100:.0f}%/"
            f"{(s['反包后高度'] >= 2).mean() * 100:.0f}%")


def main():
    rows = []
    for N, lab in [(4, "4板"), (5, "5板"), (6, "6板"), (7, "7板"), (8, "8板+")]:
        base = H[H["N"] == N] if N < 8 else H[H["N"] >= 8]
        for yy in ["阴(跌)", "阳(没跌)"]:
            sub = base[base["阴阳"] == yy]
            r = {"高度×阴阳": f"{lab}{yy}"}
            for c in COLS:
                r[c] = cell(sub[sub["档"] == c])
            r["合计"] = cell(sub)
            rows.append(r)
    r = {"高度×阴阳": "4+合计"}
    for c in COLS:
        r[c] = cell(H[H["档"] == c])
    r["合计"] = cell(H)
    rows.append(r)
    t = pd.DataFrame(rows)
    md = ["# 反包 · 4+板多维立方体总表（高度×阴阳×断板天数）", "",
          "阴阳 = 跌幅口径（主人2026-09-25拍板）：**阴=末日跌、阳=末日涨/平**。",
          "每格 = 笔数 / 持有到断板% / 胜率/炸板率/再连板率。事件含断1~11+天全档、高度不设上限。", "",
          t.to_markdown(index=False), "",
          "## 候选格分年（n≥8 且 持有>0.5）", ""]
    for N, lab in [(4, "4板"), (5, "5板"), (6, "6板"), (7, "7板"), (8, "8板+")]:
        base = H[H["N"] == N] if N < 8 else H[H["N"] >= 8]
        for yy in ["阴(跌)", "阳(没跌)"]:
            for c in COLS:
                if c == "断6~10":
                    s = base[(base["阴阳"] == yy) & base["断板天数"].between(6, 10)]
                elif c == "断11+":
                    s = base[(base["阴阳"] == yy) & (base["断板天数"] >= 11)]
                else:
                    s = base[(base["阴阳"] == yy) & (base["断板天数"] == int(c[1]))]
                if len(s) >= 8 and s["持有到断板%"].mean() > 0.5:
                    yr = " ".join(f"{a}:{s[s['年'] == a]['持有到断板%'].mean():+.2f}/{len(s[s['年'] == a])}"
                                  for a in sorted(s["年"].unique()) if len(s[s["年"] == a]))
                    md.append(f"- **{lab}{yy}{c}** (n={len(s)}): {yr}")
    out = "/root/project/ai/vnpy/量化因子研究/反包/汇总/4+多维立方体.md"
    with open(out, "w", encoding="utf-8") as fp:
        fp.write("\n".join(md) + "\n")
    print("\n".join(md))
    print(f"\n已写入 {out}")


if __name__ == "__main__":
    main()
