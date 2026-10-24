# -*- coding: utf-8 -*-
"""候选口诀卡: 锻造炉代表格 → contracts.CHEAT_ROWS 的六栏结构。

格式对齐(与主人/答题训练的肌肉记忆一致):
  编号+人话名 / 一句话口诀(窗→口诀语言) / 成绩行(笔胜均剔3+分年) /
  体检行(边界扰动/与现有重叠/类状态) / 样例票(逐票带链上数字, 行格式照抄口诀卡) /
  主力心理(留空待主人填——机器不编故事)。

后续用途(闭环): 主人审卡拍板 → 进 SCHEMES/题库/速查表/体检仪/动态组;
重叠≥50% 的卡 → 现有口诀的收窗扩窗建议; 未立规卡 → 类内候补(类衰退时第一顺位)。
"""
import math

import pandas as pd

from alphaagent.server.services.high_relay.pool import tag_scheme, tag_weak

PKL = "/tmp/relay23_tagged.pkl"
CSV = "量化因子研究/高位接力/四进五全量明细.csv"

# 窗 → 口诀语言(人话模板)
OPEN_LANG = [((-99, 0), "低开洗"), ((0, 3), "贴零锁"), ((3, 7), "温开蓄"),
             ((7, 9.5), "强开攻"), ((9.5, 99), "一字板")]


def nn(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return v


def tag_both(row):
    g4 = row["四组"]
    s = tag_scheme(g4, nn(row["b1开盘%"]), nn(row["b2开盘%"]), nn(row["b3开盘%"]),
                   auction_pct=nn(row["买入开盘%"]), b2_turn=nn(row["b2换手%"]),
                   b3_turn=nn(row["b3换手%"]), foundation_chg=nn(row["地基涨跌%"]),
                   pre10_pct=nn(row["首10日涨幅%"]), foundation_pose=nn(row["地基姿态"]),
                   anchor_pos=nn(row["锚位%"]), anchor_dist=nn(row["锚距"]))
    w = tag_weak(g4, nn(row["b1开盘%"]), nn(row["b2开盘%"]), nn(row["b3开盘%"]),
                 auction_pct=nn(row["买入开盘%"]), b1_turn=nn(row["b1换手%"]),
                 b2_turn=nn(row["b2换手%"]), b3_turn=nn(row["b3换手%"]),
                 foundation_chg=nn(row["地基涨跌%"]), prev_wave60=nn(row["前波60日最高板"]),
                 dist_h60=nn(row["距60日新高%"]))
    return (str(s["no"]) if s is not None else None,
            str(w["no"]) if w is not None else None)


def rng_lang(rng):
    """数值窗 → 口诀语言段。"""
    seg = None
    for (lo, hi), nm in OPEN_LANG:
        if rng[0] <= lo and rng[1] >= hi:
            seg = nm  # 取最宽覆盖档的名
    if seg is None:
        return f"{rng[0]:g}~{rng[1]:g}"
    if (rng[1] - rng[0]) > 6:  # 跨多档的宽窗
        return f"{rng[0]:g}~{rng[1]:g}"
    return f"{seg}({rng[0]:g}~{rng[1]:g})" if rng != (seg and [k for (k, _), v in
            [(x, y) for x, y in OPEN_LANG] if v == seg][0] if False else rng) else seg


def ticket_line(r):
    """样例票行——格式照抄打板口诀卡: 日期 名称(阴阳) 前10日 一板x 二板x(换手y) 今开z → E3%。"""
    def f(v, suf=""):
        return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:+.1f}{suf}"

    b2 = f" 二板{f(r['b2开盘%'])}"
    if not math.isnan(r.get("b2换手%", math.nan)):
        b2 += f"(换手{r['b2换手%']:.1f})"
    b3 = ""
    if not (isinstance(r.get("b3开盘%"), float) and math.isnan(r["b3开盘%"])):
        b3 = f" 三板{f(r['b3开盘%'])}"
        if not math.isnan(r.get("b3换手%", math.nan)):
            b3 += f"(换手{r['b3换手%']:.1f})"
    return (f"- {str(r['买入日'])[:10]} {str(r['名称'])}({r['阴阳']}) "
            f"前10日{f(r['首10日涨幅%'])} 一板{f(r['b1开盘%'])}{b2}{b3} "
            f"今开{f(r['买入开盘%'])} → {r['E3%']:+.1f}%")


def make_card(E, sub, no, name, koujue_txt, family, overlap_txt, n_show=6):
    """渲染一张候选口诀卡。"""
    e3 = sub["E3%"]
    trim = e3.drop(e3.nlargest(3).index).mean() if len(sub) > 3 else e3.mean()
    yrs = {int(y): g["E3%"].sum() for y, g in sub.groupby("年")}
    yr_txt = "／".join(f"{y}{len(g)}笔" if False else f"{y} {yrs.get(y, 0):+.0f}"
                       for y, g in sub.groupby("年"))
    lines = [
        f"### {no}. {name}（{family}类·候选）",
        "",
        f"**{koujue_txt}**",
        "",
        f"{len(sub)}笔 胜{(e3 > 0).mean():.0%} 均{e3.mean():+.2f} 剔3{trim:+.2f}"
        f"｜分年 {yr_txt}",
        "",
        f"体检：{overlap_txt}",
        "",
        "样例（最近，行格式同现有口诀卡）：",
    ]
    for _, r in sub.sort_values("买入日").tail(n_show).iterrows():
        lines.append(ticket_line(r))
    lines.append("")
    lines.append("**主力心理**：（待主人看票填写——机器只出数字不编故事）")
    return "\n".join(lines)


def main() -> None:
    try:
        E = pd.read_pickle(PKL)
    except FileNotFoundError:
        E = pd.read_csv(CSV, dtype={"代码": str})
    E = E[E["E3%"].notna()].copy()
    tags = E.apply(tag_both, axis=1, result_type="expand")
    E["s_no"], E["w_no"] = tags[0], tags[1]
    E["月"] = E["买入日"].astype(str).str[:7]

    # —— 示范卡1: 低吸类阳组捡尸(forge 低吸类代表格) ——
    c = E[(E["四组"] == "二接三阳")
          & (E["b1开盘%"] < 0) & (E["b2开盘%"] < 0)
          & (E["买入开盘%"] >= 5) & (E["买入开盘%"] < 9.5)
          & (E["前波60日最高板"] == 0)]
    k9 = E[E["w_no"] == "K9"].index
    j9 = len(set(c.index) & set(k9)) / len(set(c.index) | set(k9)) if len(c) else 0
    print(make_card(E, c, "L1", "阳组捡尸(暂名)", "一板低开二板也低开(双洗到底)，今开5~9.5抢反弹，前波60日内没炒过(最高板=0)",
                    "低吸", f"与K9重叠J={j9:.2f}｜边界扰动见锻造炉报告｜低吸类近24月绿(5.04)"))
    print()
    # —— 示范卡2: 强开类三接四阴三板强开 ——
    c2 = E[(E["四组"] == "三接四阴")
           & (E["b3开盘%"] >= 7) & (E["b3开盘%"] < 9.5)
           & (E["买入开盘%"] >= 3) & (E["买入开盘%"] < 8.5)
           & (E["地基涨跌%"] < 1)
           & (E["b3换手%"] >= E["b2换手%"])]
    b1i = E[E["s_no"] == "B1"].index
    jb = len(set(c2.index) & set(b1i)) / len(set(c2.index) | set(b1i)) if len(c2) else 0
    print(make_card(E, c2, "Q1", "三板强攻(暂名)", "三板强开(≥7)主力还在攻，地基没动过(涨<1)，今开3~8.5接，三换手不缩(≥二换手)",
                    "强开", f"与B1重叠J={jb:.2f}｜强开类近24月绿(20.64)"))


main()
