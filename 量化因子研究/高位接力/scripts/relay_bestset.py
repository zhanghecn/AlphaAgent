# -*- coding: utf-8 -*-
"""高位接力 · 最优组合集终验（第二十四遍）。

把开盘链/联动矩阵里的强格 × 方案点维度（位置窗/换手梯度/前波/反包断1天）交叉补强，
每组筛「最优组合集」。每条：分年全正/置换2000/去尾3/与五方案点重叠。

宿主机纯CSV: uv run python relay_bestset.py
输出: 汇总/最优组合集.md + 控制台
"""
import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
YEARS = ["2023", "2024", "2025", "2026"]
rng = np.random.default_rng(20260919)


def load():
    E = pd.read_csv(f"{ROOT}/全量明细.csv", dtype={"代码": str})
    X = pd.read_csv(f"{ROOT}/地基均线反包明细.csv", dtype={"代码": str})
    E = E.merge(X[["代码", "买入日", "距MA10%", "前板高度", "反包结构"]],
                on=["代码", "买入日"], how="left")
    E = E[~E["未完"]].copy()
    E["年"] = E["年"].astype(str)
    E["胜"] = E["次日收%"] > 0
    E["换手梯度"] = E["b2换手%"] - E["b1换手%"]
    return E


def year_str(sub):
    return " ".join(
        f"{y}:{sy['持有到断板%'].mean():+.2f}/{len(sy)}" if len(sy := sub[sub["年"] == y]) else f"{y}:0笔"
        for y in YEARS)


def all_pos(sub):
    return all(len(sub[sub["年"] == y]) > 0 and
               sub[sub["年"] == y]["持有到断板%"].mean() > 0 for y in YEARS)


def verify(lines, E, name, mask, scheme_masks):
    gname = name.split("·")[0].strip()
    pool = E[E["四组"] == gname]
    sub = E[mask]
    n = len(sub)
    if n == 0:
        lines.append(f"| {name} | 0 | | | | | | | |")
        return None
    win = sub["胜"].mean() * 100
    hold = sub["持有到断板%"].mean()
    p = (rng.choice(pool["持有到断板%"].to_numpy(), size=(2000, n), replace=True).mean(axis=1) >= hold).mean() if n >= 8 else np.nan
    tri = sub.sort_values("持有到断板%", ascending=False).iloc[3:]
    tri_txt = f"{tri['持有到断板%'].mean():+.2f}" if len(tri) else ""
    ov = []
    for pname, pm in scheme_masks.items():
        k = int((mask & pm).sum())
        if k:
            ov.append(f"{pname}{k}")
    lines.append(f"| {name} | {n} | {win:.0f}% | {hold:+.2f} | {year_str(sub)} "
                 f"| {'✅' if all_pos(sub) else '❌'} | {p:.3f} | {tri_txt} | {'/'.join(ov) or '0'} |")
    return sub


def main():
    E = load()
    b1o, b2o, auc = E["b1开盘%"], E["b2开盘%"], E["买入开盘%"]
    pos = E["距60日新高%"]
    grad = E["换手梯度"]
    yy = E["四组"] == "二接三阳"
    yn = E["四组"] == "二接三阴"
    sy = E["四组"] == "三接四阳"
    sn = E["四组"] == "三接四阴"

    scheme_masks = {
        "A1": sy & (pos >= -15) & (pos < -8) & (~E["均线"].isin(["+++", "-++", "+--"])) & (E["前波60日最高板"] == 0),
        "A2": sn & (E["前波120日最高板"] >= 3) & (grad < -5),
        "B1": yn & (b2o >= 6) & (b2o < 9.5) & (grad >= 0) & (grad < 2),
        "B2": yy & (pos >= -9) & (pos < -2) & (b2o < 0) & (auc >= 4) & (auc < 7),
        "B3": sy & (E["前板高度"].fillna(0) >= 2) & (E["距MA10%"] < 5),
    }

    lines = ["# 高位接力 · 最优组合集终验（2026-09-19 第二十四遍）", "",
             "链表强格 × 方案点维度交叉补强。列：笔数/胜率/持有/分年/全正/置换p/去尾3/与方案点重叠。", "",
             "## 二接三阳\n",
             "| 组合 | 笔数 | 胜率 | 持有 | 分年 | 全正 | p | 去尾3 | 重叠 |",
             "|---|---|---|---|---|---|---|---|---|"]
    cand = [
        ("二接三阳·B2本体(对照)", scheme_masks["B2"]),
        ("二接三阳·一低开/平开×二低开×三高4~7", yy & (b1o < 3) & (b2o < 0) & (auc >= 4) & (auc < 7)),
        ("二接三阳·一低开/平开×二低开×三高4~7×位置-9~-2", yy & (b1o < 3) & (b2o < 0) & (auc >= 4) & (auc < 7) & (pos >= -9) & (pos < -2)),
        ("二接三阳·一低开×二低开×三高3~7×位置-9~-2", yy & (b1o < 0) & (b2o < 0) & (auc >= 3) & (auc < 7) & (pos >= -9) & (pos < -2)),
        ("二接三阳·一平开×二低开×三高3~7×位置-9~-2", yy & (b1o >= 0) & (b1o < 3) & (b2o < 0) & (auc >= 3) & (auc < 7) & (pos >= -9) & (pos < -2)),
        ("二接三阳·二顶格×三7~9.5×断1天反包", yy & (b2o >= 9.5) & (auc >= 7) & (auc < 9.5) & (E["反包结构"] == "断1天")),
    ]
    for nm, m in cand:
        verify(lines, E, nm, m, scheme_masks)

    lines += ["", "## 二接三阴\n",
              "| 组合 | 笔数 | 胜率 | 持有 | 分年 | 全正 | p | 去尾3 | 重叠 |",
              "|---|---|---|---|---|---|---|---|---|"]
    cand = [
        ("二接三阴·B1本体(对照)", scheme_masks["B1"]),
        ("二接三阴·一平开×二高开3~7×三强开≥7", yn & (b1o >= 0) & (b1o < 3) & (b2o >= 3) & (b2o < 7) & (auc >= 7)),
        ("二接三阴·一平开×二高开3~7×三强开×换手微增", yn & (b1o >= 0) & (b1o < 3) & (b2o >= 3) & (b2o < 7) & (auc >= 7) & (grad >= 0) & (grad < 2)),
        ("二接三阴·一强开×二强开×三高3~7", yn & (b1o >= 7) & (b2o >= 7) & (auc >= 3) & (auc < 7)),
        ("二接三阴·一强开×二强开×三高3~7×换手微增", yn & (b1o >= 7) & (b2o >= 7) & (auc >= 3) & (auc < 7) & (grad >= 0) & (grad < 2)),
        ("二接三阴·B1×竞价低开或顶格", scheme_masks["B1"] & ((auc < 2) | (auc >= 9.5))),
        ("二接三阴·一低开×二低开×三低开", yn & (b1o < 0) & (b2o < 0) & (auc < 0)),
    ]
    for nm, m in cand:
        verify(lines, E, nm, m, scheme_masks)

    lines += ["", "## 三接四阳\n",
              "| 组合 | 笔数 | 胜率 | 持有 | 分年 | 全正 | p | 去尾3 | 重叠 |",
              "|---|---|---|---|---|---|---|---|---|"]
    cand = [
        ("三接四阳·A1本体(对照)", scheme_masks["A1"]),
        ("三接四阳·B3本体(对照)", scheme_masks["B3"]),
        ("三接四阳·一低开×二强开×三高3~7", sy & (b1o < 0) & (b2o >= 7) & (auc >= 3) & (auc < 7)),
        ("三接四阳·一低开×二强开×三高3~7×前板≥2", sy & (b1o < 0) & (b2o >= 7) & (auc >= 3) & (auc < 7) & (E["前板高度"].fillna(0) >= 2)),
        ("三接四阳·一平开×二强开×三平开0~3", sy & (b1o >= 0) & (b1o < 3) & (b2o >= 7) & (auc >= 0) & (auc < 3)),
    ]
    for nm, m in cand:
        verify(lines, E, nm, m, scheme_masks)

    lines += ["", "## 三接四阴\n",
              "| 组合 | 笔数 | 胜率 | 持有 | 分年 | 全正 | p | 去尾3 | 重叠 |",
              "|---|---|---|---|---|---|---|---|---|"]
    cand = [
        ("三接四阴·A2本体(对照)", scheme_masks["A2"]),
        ("三接四阴·一平开×二平开×三强开≥7", sn & (b1o >= 0) & (b1o < 3) & (b2o >= 0) & (b2o < 3) & (auc >= 7)),
        ("三接四阴·一平开×二平开×三强开×老龙前波≥3", sn & (b1o >= 0) & (b1o < 3) & (b2o >= 0) & (b2o < 3) & (auc >= 7) & (E["前波120日最高板"] >= 3)),
        ("三接四阴·一低开×二强开×三强开≥7", sn & (b1o < 0) & (b2o >= 7) & (auc >= 7)),
    ]
    for nm, m in cand:
        verify(lines, E, nm, m, scheme_masks)

    text = "\n".join(lines)
    with open(f"{ROOT}/汇总/最优组合集.md", "w", encoding="utf-8") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    main()
