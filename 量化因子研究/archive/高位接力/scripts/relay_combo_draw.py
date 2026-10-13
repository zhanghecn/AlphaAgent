# -*- coding: utf-8 -*-
"""高位接力 · 好差票组合研究多维图（三张，宿主机跑）。

图1 主图: 四组×b2开盘(阴/中/阳)×首板前3日涨幅 → 次日连板率 分面热力图(5维一张图)
图2: b2阴阳中效应 —— 连板率+断板收益 分组条形
图3: 前3日阴阳串排序 —— 连板率条形+好票率散点

颜色: 热力图=单色蓝渐变(量级); 三档=同色系深浅(有序,亮度单调); 双指标=蓝#3b82f6+琥珀#d97706(validator PASS)
小样本规则: n<10 灰字显示不隐藏(主人规则); n≥15 才判好/毒格
宿主机纯CSV: uv run python relay_combo_draw.py
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Rectangle

plt.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
OUT = f"{ROOT}/图解"

CMAP = LinearSegmentedColormap.from_list("blues", ["#eff6ff", "#93c5fd", "#3b82f6", "#172554"])
STEP3 = {"阴<0": "#60a5fa", "中0~3": "#3b82f6", "阳≥3": "#1e3a8a"}   # 有序三档, 亮度单调
C_MAIN, C_SUB = "#3b82f6", "#d97706"                                    # validator PASS 双色
C_GOOD, C_BAD, INK, INK2 = "#059669", "#dc2626", "#1e293b", "#64748b"
GROUPS = ["二接三阳", "二接三阴", "三接四阳", "三接四阴"]
B3L = ["阴<0", "中0~3", "阳≥3"]
P3L = ["≤-5", "-5~0", "0~5", "5~10", ">10"]


def load():
    E = pd.read_csv(f"{ROOT}/全量明细.csv", dtype={"代码": str})
    P = pd.read_csv(f"{ROOT}/首板前3日明细.csv", dtype={"代码": str})
    M = E.merge(P.drop(columns=["首板日"]), on=["代码", "买入日"], how="inner")
    M = M[~M["未完"]].copy()
    M["b2三档"] = pd.cut(M["b2开盘%"], [-99, 0, 3, 99], labels=B3L)
    M["pre3档"] = pd.cut(M["pre3%"], [-99, -5, 0, 5, 10, 99], labels=P3L)
    return M


def fig1(M):
    fig, axes = plt.subplots(2, 2, figsize=(15.5, 10.5))
    fig.suptitle("高位接力 · 连板影响力多维图：四组 × 二板开盘(阴/中/阳) × 首板前3日涨幅",
                 fontsize=17, fontweight="bold", color=INK, y=0.985)
    fig.text(0.5, 0.955,
             "格子=次日连板率(买后再连一板) · 底色越深连板率越高 · 灰字=样本<10(照显不藏) · "
             "绿框=高于组基线8pp(n≥15) · 红框=低于组基线8pp(n≥15) · 持有到断板口径, 未完剔除",
             ha="center", fontsize=10.5, color=INK2)
    vmax = 0.55
    for ax, g in zip(axes.flat, GROUPS):
        sub = M[M["四组"] == g]
        base = sub["次日连板"].mean()
        def _piv(col, how):
            return getattr(sub.groupby(["b2三档", "pre3档"], observed=True)[col], how)() \
                .unstack().reindex(index=B3L, columns=P3L)
        piv_n = _piv("次日连板", "size")
        piv_r = _piv("次日连板", "mean")
        piv_y = _piv("持有到断板%", "mean")
        ax.set_facecolor("#f8fafc")
        for i in range(3):
            for j in range(5):
                n, r = piv_n.iloc[i, j], piv_r.iloc[i, j]
                yv = piv_y.iloc[i, j]
                if pd.isna(n):
                    ax.add_patch(Rectangle((j, 2 - i), 0.96, 0.96, facecolor="#f1f5f9", edgecolor="#e2e8f0"))
                    ax.text(j + 0.48, 2 - i + 0.48, "—", ha="center", va="center", color="#94a3b8", fontsize=10)
                    continue
                color = CMAP(min(r / vmax, 1.0))
                ax.add_patch(Rectangle((j, 2 - i), 0.96, 0.96, facecolor=color, edgecolor="white", lw=1.5))
                small = n < 10
                ax.text(j + 0.48, 2 - i + 0.62, f"{r:.1%}", ha="center", va="center",
                        fontsize=13, fontweight="bold", color="#94a3b8" if small else "#0f172a" if r < 0.33 else "white")
                ax.text(j + 0.48, 2 - i + 0.30, f"n={int(n)}", ha="center", va="center",
                        fontsize=8.5, color="#94a3b8" if small else ("#cbd5e1" if r >= 0.33 else "#475569"))
                if not np.isnan(yv):
                    ax.text(j + 0.48, 2 - i + 0.10, f"{yv:+.1f}", ha="center", va="center",
                            fontsize=8, color="#94a3b8" if small else ("#cbd5e1" if r >= 0.33 else "#64748b"))
                if n >= 15 and r >= base + 0.08:
                    ax.add_patch(Rectangle((j + 0.02, 2 - i + 0.02), 0.92, 0.92,
                                           fill=False, edgecolor=C_GOOD, lw=2.6))
                elif n >= 15 and r <= base - 0.08:
                    ax.add_patch(Rectangle((j + 0.02, 2 - i + 0.02), 0.92, 0.92,
                                           fill=False, edgecolor=C_BAD, lw=2.6))
        ax.set_xlim(0, 5); ax.set_ylim(0, 3)
        ax.set_xticks(np.arange(5) + 0.48)
        ax.set_xticklabels([f"前3日\n{c}%" for c in P3L], fontsize=9.5)
        ax.set_yticks(np.arange(3) + 0.48)
        ax.set_yticklabels([f"二板开盘 {c}%" for c in B3L], fontsize=10)
        ax.set_title(f"{g}（基线连板率 {base:.1%}, n={len(sub)}）", fontsize=13, fontweight="bold", color=INK, pad=8)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.tick_params(length=0)
    sm = plt.cm.ScalarMappable(cmap=CMAP, norm=plt.Normalize(0, vmax))
    cb = fig.colorbar(sm, ax=axes, orientation="vertical", fraction=0.018, pad=0.015)
    cb.set_label("次日连板率", fontsize=10)
    cb.ax.tick_params(labelsize=9)
    fig.savefig(f"{OUT}/组合_主图_四组×二板开盘×前3日涨幅.png", dpi=150, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)


def fig2(M):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.6), gridspec_kw={"width_ratios": [1, 1]})
    fig.suptitle("二板开盘「阴/中/阳」效应：低开接力显著更强（置换 p=0.0005，四组方向一致）",
                 fontsize=15, fontweight="bold", color=INK, y=1.0)
    metrics = [("次日连板", "次日连板率", 0, 0.62, "{:.1%}"),
               ("持有到断板%", "持有到断板收益 %", -5, 5.5, "{:+.1f}")]
    for ax, (col, ttl, lo, hi, fmt) in zip(axes, metrics):
        xs = np.arange(len(GROUPS))
        w = 0.26
        ax.axhline(0 if col == "持有到断板%" else M[col].mean(),
                   color="#cbd5e1", lw=1, ls="--", zorder=1)
        if col == "次日连板":
            ax.text(3.42, M[col].mean() + 0.012, f"全场基线 {M[col].mean():.1%}",
                    fontsize=8.5, color=INK2, ha="right")
        for k, lab in enumerate(B3L):
            vals = [M[(M["四组"] == g) & (M["b2三档"] == lab)][col].mean() for g in GROUPS]
            pos = xs + (k - 1) * w
            bars = ax.bar(pos, vals, width=w * 0.92, color=STEP3[lab],
                          label=f"二板开盘 {lab}", zorder=3)
            for x, v in zip(pos, vals):
                if col == "持有到断板%":
                    dy = 0.18 if v >= 0 else -(0.18 + 0.5 * (k == 1))   # 中间档再下错一行防重叠
                    ax.text(x, v + dy, fmt.format(v), ha="center",
                            va="bottom" if v >= 0 else "top", fontsize=9, color=INK)
                else:
                    ax.text(x, v + 0.008, fmt.format(v), ha="center", va="bottom",
                            fontsize=9, color=INK)
        ax.set_xticks(xs); ax.set_xticklabels(GROUPS, fontsize=11)
        ax.set_ylim(lo, hi)
        ax.set_title(ttl, fontsize=12, color=INK, pad=8)
        ax.grid(axis="y", color="#e2e8f0", lw=0.8, zorder=0)
        ax.set_axisbelow(True)
        for s in ["top", "right"]:
            ax.spines[s].set_visible(False)
        ax.spines["left"].set_color("#cbd5e1"); ax.spines["bottom"].set_color("#cbd5e1")
    axes[0].legend(fontsize=9.5, frameon=False, loc="upper left")
    fig.text(0.5, -0.02, "色深=开盘强度递增(有序) · 左: 买后再连一板概率 · 右: 涨停价买入持有到断板的收益",
             ha="center", fontsize=9.5, color=INK2)
    fig.savefig(f"{OUT}/组合_二板开盘阴阳中效应.png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig3(M):
    t = M.groupby("p3阴阳").agg(
        n=("代码", "size"), 连板率=("次日连板", "mean"),
        好票率=("坏票", lambda s: 1 - s.mean()), pre3均值=("pre3%", "mean")).sort_values("连板率")
    order = ["阳阴阳", "阳阳阴", "阴阴阴", "阳阳阳", "阳阴阴", "阴阳阴", "阴阴阳", "阴阳阳"]
    t = t.reindex(order[::-1])
    fig, ax = plt.subplots(figsize=(12.5, 6.2))
    ax.set_title("首板前3日「阴阳构成」对连板的影响力：先蹲后起(阴阳阳)最强，反复拉锯(阳阴阳)最弱",
                 fontsize=14.5, fontweight="bold", color=INK, pad=12)
    xs = np.arange(len(t))
    bars = ax.bar(xs, t["连板率"], width=0.62, color=C_MAIN, zorder=3, label="次日连板率")
    ax.scatter(xs, t["好票率"], s=64, color=C_SUB, zorder=4, marker="D", label="好票率")
    for x, (r, g_, n, p3) in enumerate(zip(t["连板率"], t["好票率"], t["n"], t["pre3均值"])):
        ax.text(x, r + 0.010, f"{r:.1%}", ha="center", fontsize=10, color=INK, fontweight="bold")
        ax.text(x, g_ + 0.012, f"{g_:.0%}", ha="center", fontsize=8.5, color="#92400e")
        ax.text(x, -0.045, f"n={int(n)}", ha="center", fontsize=8.5, color=INK2)
        ax.text(x, -0.075, f"3日均涨{p3:+.1f}%", ha="center", fontsize=8, color="#94a3b8")
    ax.set_xticks(xs)
    ax.set_xticklabels([f"{s[0]}→{s[1]}→{s[2]}\n({s}  早→晚)" for s in t.index], fontsize=10.5)
    ax.set_ylim(0, 0.60)
    ax.set_ylabel("比率", fontsize=11)
    ax.grid(axis="y", color="#e2e8f0", lw=0.8, zorder=0)
    ax.set_axisbelow(True)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_color("#cbd5e1"); ax.spines["bottom"].set_color("#cbd5e1")
    ax.legend(fontsize=10, frameon=False, loc="upper left")
    fig.text(0.5, -0.015, "阴阳阳 vs 阳阴阳 连板率差 +10.6pp (置换 p=0.001) · 串顺序独立于涨幅幅度 · 档内=该日收盘涨跌",
             ha="center", fontsize=9.5, color=INK2)
    fig.savefig(f"{OUT}/组合_前3日阴阳构成.png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    M = load()
    fig1(M); fig2(M); fig3(M)
    print("三张图已输出到", OUT)
