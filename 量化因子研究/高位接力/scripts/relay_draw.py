# -*- coding: utf-8 -*-
"""高位接力 · 规则图解：五个方案点各一票真实K线标注（宿主机跑）。

输入: 图解数据.csv（容器导出） + 全量明细.csv（取事件数值）
输出: 图解/<点>_<名称>.png × 5
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

plt.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei"]
plt.rcParams["axes.unicode_minus"] = False

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"

PICKS = [
    # (方案点, 代码, 名称, 买入日, N, 规则一句话, 图注重点)
    ("A1", "605179.SSE", "一鸣食品", "2024-11-29", 3,
     "首板前一天收盘比60日最高价低8~15% × 均线不整齐 × 60日内首次连板",
     "跌透了第一次启动"),
    ("A2", "002583.SZSE", "海能达", "2024-10-23", 3,
     "近120日有过≥3连板 × 二板换手率比首板低5个百分点以上",
     "老龙头缩量再来一波"),
    ("B1", "605033.SSE", "美邦股份", "2025-01-06", 2,
     "二板开盘涨6~9.5% × 二板换手只比首板多0~2个百分点",
     "高开确认、量能不爆"),
    ("B2", "002820.SZSE", "桂发祥", "2024-11-26", 2,
     "首板前一天收盘比60日最高价低2~9% × 二板开盘跌（<0%） × 竞价开盘涨4~7%",
     "低开洗盘、竞价转强"),
    ("B3", "603266.SSE", "天龙股份", "2023-10-30", 3,
     "近60日有过≥2连板前一波 × 首板前一天收盘贴10日线（±5%内）",
     "二波接力贴线起"),
]


def load_events():
    E = pd.read_csv(f"{ROOT}/全量明细.csv", dtype={"代码": str})
    return E


def draw(code, name, day, N, point, rule, gist, E, D):
    r = E[(E["代码"] == code) & (E["买入日"] == day)].iloc[0]
    d = D[D["vt_symbol"] == code].sort_values("trade_date").reset_index(drop=True)
    p = int(d.index[d["trade_date"] == pd.Timestamp(day)][0])
    f = p - N - 1                     # 地基日
    hold = int(r["持有天数"])
    sell = p + hold                   # 卖出日(首个不涨停日)
    lo = max(0, f - 12)
    hi = min(len(d) - 1, sell + 2)
    # 60日最高价(地基日前60个交易日)
    h60 = d.loc[max(0, f - 60):f - 1, "high_price"].max() if f > 0 else np.nan
    d["ma10"] = d["close_price"].rolling(10).mean()

    fig, (ax, axv) = plt.subplots(2, 1, figsize=(13, 8), sharex=True,
                                  gridspec_kw={"height_ratios": [3.2, 1]})
    xs = np.arange(lo, hi + 1)
    for i in xs:
        o, h, l, c = d.loc[i, ["open_price", "high_price", "low_price", "close_price"]]
        up = c >= o
        color = "#d43f3a" if up else "#3aa655"
        ax.plot([i, i], [l, h], color=color, lw=1.0, zorder=2)
        ax.add_patch(Rectangle((i - 0.32, min(o, c)), 0.64, max(abs(c - o), 1e-4),
                               facecolor=color, edgecolor=color, zorder=3))
        # 涨停日金边
        lim = round(d.loc[i - 1, "close_price"] * 1.10 + 1e-9, 2) if i > 0 else None
        if lim and abs(c - lim) < 1e-6:
            ax.add_patch(Rectangle((i - 0.36, min(o, c)), 0.72, max(abs(c - o), 1e-4),
                                   fill=False, edgecolor="#e6a23c", lw=1.6, zorder=4))
        axv.bar(i, d.loc[i, "volume"], color=color, width=0.64)
    ax.plot(xs, d.loc[xs, "ma10"], color="#3b82f6", lw=1.2, label="10日均线", zorder=5)
    if h60 == h60:
        ax.axhline(h60, color="#999999", ls="--", lw=1.0)
        ax.text(lo + 0.2, h60, f" 60日最高价 {h60:.2f}", color="#666666",
                va="bottom", fontsize=9)
    # 买价虚线
    buy = r["买价"]
    ax.axhline(buy, color="#d43f3a", ls=":", lw=1.0)
    ax.text(hi - 0.2, buy, f" 涨停价买 {buy:.2f} ", color="#d43f3a",
            va="bottom", ha="right", fontsize=9)

    def note(i, text, dy=1.0, color="#333333", va="bottom"):
        ax.annotate(text, xy=(i, d.loc[i, "high_price"]), xytext=(i, d.loc[i, "high_price"] + dy),
                    ha="center", fontsize=9, color=color)

    yspan = d.loc[xs, "high_price"].max() - d.loc[xs, "low_price"].min()
    note(f, f"地基日\n{r['阴阳']}{r['地基涨跌%']:+.1f}%\n比60日新高{r['距60日新高%']:+.1f}%", yspan * 0.10)
    for k in range(1, N + 1):
        j = p - N + k - 1
        note(j, f"第{k}板\n开{r[f'b{k}开盘%']:+.1f}%\n换手{r[f'b{k}换手%']:.1f}", yspan * 0.06)
    ax.annotate("打板买入", xy=(p, d.loc[p, "low_price"]), xytext=(p - 1.5, d.loc[p, "low_price"] - yspan * 0.16),
                fontsize=11, fontweight="bold", color="#d43f3a",
                arrowprops=dict(arrowstyle="->", color="#d43f3a", lw=1.6))
    ax.annotate(f"竞价{r['买入开盘%']:+.1f}%", xy=(p, d.loc[p, "high_price"]),
                xytext=(p, d.loc[p, "high_price"] + yspan * 0.05), ha="center", fontsize=9, color="#d43f3a")
    if sell <= hi:
        ax.annotate("断板卖出", xy=(sell, d.loc[sell, "high_price"]),
                    xytext=(sell - 1.0, d.loc[sell, "high_price"] + yspan * 0.12),
                    fontsize=10, fontweight="bold", color="#3aa655",
                    arrowprops=dict(arrowstyle="->", color="#3aa655", lw=1.6))
    ax.set_title(f"{point} {gist}｜{name} {code[:6]}｜{day} 打第{N + 1}板 → "
                 f"持有{hold}天 {r['持有到断板%']:+.0f}%\n规则：{rule}",
                 fontsize=12, loc="left")
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.25)
    axv.grid(alpha=0.25)
    tick_pos = xs[::max(1, len(xs) // 12)]
    axv.set_xticks(tick_pos)
    axv.set_xticklabels([d.loc[i, "trade_date"].strftime("%m-%d") for i in tick_pos], fontsize=8)
    ax.set_xlim(lo - 0.7, hi + 0.7)
    fig.tight_layout()
    out = f"{ROOT}/图解/{point}_{name}.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print("已画", out)


def main():
    import os
    os.makedirs(f"{ROOT}/图解", exist_ok=True)
    E = load_events()
    D = pd.read_csv(f"{ROOT}/图解数据.csv", dtype={"vt_symbol": str}, parse_dates=["trade_date"])
    for point, code, name, day, N, rule, gist in PICKS:
        draw(code, name, day, N, point, rule, gist, E, D)


if __name__ == "__main__":
    main()
