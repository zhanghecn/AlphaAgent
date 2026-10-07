# -*- coding: utf-8 -*-
"""一接二 · 第9步样本外终验: 2021-01~2022-12 纯样本外重放(数据在建样本时已同批构建)。

G1/G2/G3 口径与主窗完全一致, 不做任何调整:
  G1 = 阴地基 × 今开7.5~9.5
  G2 = G1 × 首板换手<8
  G3 = G1 × 低位/跌透
毒格回避同口径: 贴顶 / 今开顶格 / T字×今开<4 / 一字×前10日5~10
"""
import pandas as pd

OUT = "/tmp/research/j12_out"


def load():
    E = pd.read_csv(f"{OUT}/全量明细.csv", parse_dates=["买入日"])
    E["年"] = E["年"].astype(str)
    oos = E[(E["段"] == "样本外") & (~E["未完"])].copy()
    main = E[(E["段"] == "主窗") & (~E["未完"])].copy()
    return oos, main


def years_table(sub):
    yr = sub.groupby("年")["E3%"].agg(["count", "mean"])
    return " / ".join(f"{y[:4]}:{int(r['count'])}笔{r['mean']:+.2f}" for y, r in yr.iterrows())


def allpos(sub):
    yr = sub.groupby("年")["E3%"].agg(["count", "mean"])
    return all(r["mean"] > 0 for _, r in yr.iterrows()) and len(yr) >= 2


def head(sub):
    if not len(sub):
        return "0笔"
    return (f"{len(sub)}笔 胜{(sub['E3%'] > 0).mean() * 100:.0f}% 均{sub['E3%'].mean():+.2f} "
            f"中位{sub['E3%'].median():+.2f} 最差{sub['E3%'].min():+.1f} "
            f"{'✅全正' if allpos(sub) else '❌'}")


def main():
    oos, main = load()
    lines = [f"# 一接二 · 样本外终验 2021-01~2022-12 (入池{len(oos)}笔已完)", ""]

    def g1(d):
        return d[(d["地基阴阳"] == "阴") & d["买入开盘%"].between(7.5, 9.5, inclusive="left")]

    def g2(d):
        G = g1(d)
        return G[G["首板换手%"] < 8]

    def g3(d):
        G = g1(d)
        return G[G["位置五档"].isin(["低位", "跌透"])]

    lines.append("## 口诀格样本外重放(口径零调整)")
    for name, fn in [("G1 阴×今开7.5~9.5", g1), ("G2 G1×换手<8", g2), ("G3 G1×低位/跌透", g3)]:
        s, m = fn(oos), fn(main)
        lines.append(f"- {name}")
        lines.append(f"  - 主窗: {head(m)} ｜ {years_table(m)}")
        lines.append(f"  - 样本外: {head(s)} ｜ {years_table(s)}")
        # 逐笔案例(样本外命中)
        for _, r in s.sort_values("E3%", ascending=False).head(5).iterrows():
            lines.append(f"    · {r['买入日'].date()} {r['名称']} 今开{r['买入开盘%']:+.1f} "
                         f"换手{r['首板换手%']:.1f} 距MA20{r['地基距MA20%']:+.1f} → {r['E3%']:+.1f}%")
        bad = s[s["E3%"] < 0].nsmallest(3, "E3%")
        for _, r in bad.iterrows():
            lines.append(f"    · (亏) {r['买入日'].date()} {r['名称']} 今开{r['买入开盘%']:+.1f} "
                         f"换手{r['首板换手%']:.1f} 距MA20{r['地基距MA20%']:+.1f} → {r['E3%']:+.1f}%")

    lines.append("\n## 毒格样本外复验")
    for name, mk in [
        ("贴顶全部", lambda d: d[d["位置五档"] == "贴顶"]),
        ("今开顶格", lambda d: d[d["买入开盘%"] >= 9.5]),
        ("阳×今开7.5~9.5(反面对照)", lambda d: d[(d["地基阴阳"] == "阳") & d["买入开盘%"].between(7.5, 9.5, inclusive="left")]),
    ]:
        s, m = mk(oos), mk(main)
        lines.append(f"- {name}: 主窗 {head(m)} → 样本外 {head(s)} ｜ OOS {years_table(s)}")

    lines.append("\n## 样本外环境参考(信息层)")
    lines.append(f"- 全池样本外: {head(oos)} ｜ {years_table(oos)}")

    txt = "\n".join(lines)
    with open(f"{OUT}/样本外2021_2022.md", "w", encoding="utf-8") as fh:
        fh.write(txt)
    print(txt)


if __name__ == "__main__":
    main()
