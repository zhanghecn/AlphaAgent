# -*- coding: utf-8 -*-
"""高位接力 · 胜率关键第三遍：只用买入前可知的信息（无未来函数）。

允许的维度（买入前 100% 能确定）:
- 昨天及以前(静态): 阴阳(分组轴)、地基涨跌/距60日新高/均线/前20日涨幅/前波、
  接力链各板的板型/开盘涨幅/换手/下影
- 竞价(9:25定型, 打板在9:30后, 合法): 买入当天开盘涨幅
- 环境: 昨日涨停家数
禁止: 买入当天量比/换手/封板时间/炸板次数等全天或盘中动态数据(收盘才定型=未来函数)。

方法: 单维分档扫描排序 + 贪心组合树(每次选区分度最大的维度切分, 钻进最好的格子继续切),
每条路径报 样本量/胜率/次日收益/持有到断板/分年, 验收看分年是否全正。
"""
import numpy as np
import pandas as pd

pd.set_option("display.width", 320)
pd.set_option("display.max_columns", 100)

CSV = "/root/project/ai/vnpy/量化因子研究/高位接力/全量明细.csv"
GROUPS = ["二接三阴", "二接三阳", "三接四阴", "三接四阳"]
MIN_BIN = 25        # 每个格子至少25笔才参与区分度评比
MIN_LEAF = 25       # 组合树的叶子至少25笔

# (列名, 分档边界None=类别, 显示名) —— 全部是买入前可知的
DIMS = [
    ("买入开盘%", [-99, 0, 2, 4, 6, 8, 9.5, 99], "竞价开盘"),
    ("距60日新高%", [-99, -25, -15, -8, -3, 0.01], "地基位置(距新高)"),
    ("地基涨跌%", [-99, -5, -3, 0, 3, 99], "地基日涨跌"),
    ("地基前20日涨幅%", [-99, 0, 15, 30, 999], "地基前20日涨幅"),
    ("前波60日最高板", [-1, 0, 2, 3, 99], "前波60日"),
    ("距前波末板", [-2, -0.5, 5, 10, 20, 9999], "距前波末板"),
    ("昨日涨停家数", [-1, 30, 50, 80, 9999], "昨日涨停家数"),
    ("b1开盘%", [-99, 0, 3, 6, 9.5, 99], "首板开盘"),
    ("b2开盘%", [-99, 0, 3, 6, 9.5, 99], "二板开盘"),
    ("b1换手%", [-1, 3, 6, 10, 15, 99], "首板换手"),
    ("b2换手%", [-1, 3, 6, 10, 15, 99], "二板换手"),
    ("b2下影%", [-0.1, 0.3, 2, 5, 99], "二板下影"),
    ("均线归并", None, "均线三态"),
    ("b1板型", None, "首板板型"),
    ("b2板型", None, "二板板型"),
    ("b3板型", None, "三板板型"),
    ("链组合", None, "链组合"),
]


def load():
    E = pd.read_csv(CSV)
    E = E[~E["未完"]].copy()
    E["胜"] = E["次日收%"] > 0
    E["链组合"] = E["b1板型"] + "→" + E["b2板型"]
    E["均线归并"] = np.where(E["均线"] == "+++", "全多头",
                    np.where(E["均线"].isin(["-++", "+--"]), "纠缠", "其他"))
    E["距前波末板"] = E["距前波末板"].fillna(-1)
    return E


def bin_series(s, col, edges):
    if edges is not None:
        return pd.cut(s[col], edges, right=False)
    return s[col].fillna("(无)").astype(str)


def best_split(sub, dims, min_bin=MIN_BIN):
    """返回 (显示名, 分档表, 区分度) 最优维度; 没有合格维度返回 None。"""
    best = None
    for col, edges, label in dims:
        if col not in sub.columns or sub[col].isna().all():
            continue
        s = sub.copy()
        s["档"] = bin_series(s, col, edges)
        t = s.groupby("档", observed=True).agg(n=("胜", "size"), 胜率=("胜", "mean"),
                                               持有=("持有到断板%", "mean"))
        t = t[t["n"] >= min_bin]
        if len(t) < 2:
            continue
        spread = t["胜率"].max() - t["胜率"].min()
        if best is None or spread > best[2]:
            best = (label, t, spread, col, edges)
    return best


def yearly_line(sub):
    by = sub.groupby("年").agg(n=("持有到断板%", "size"), 收益=("持有到断板%", "mean"),
                               胜率=("胜", "mean"))
    return " ".join(f"{y}:{r.收益:+.2f}/{r.胜率*100:.0f}%(n={r.n:.0f})" for y, r in by.iterrows())


def tree(sub, path, depth, gname, out):
    """贪心组合树: 选区分度最大的维度, 钻进最好和最差的格子递归。"""
    base_wr = sub["胜"].mean()
    bw = sub["持有到断板%"].mean()
    tag = "  " * (3 - depth)
    out.append(f"{tag}【{' × '.join(path)}】n={len(sub)} 胜率{base_wr*100:.0f}% "
               f"持有{bw:+.2f} | {yearly_line(sub)}")
    if depth == 0 or len(sub) < 2 * MIN_LEAF:
        return
    b = best_split(sub, DIMS)
    if b is None:
        return
    label, t, spread, col, edges = b
    out.append(f"{tag}  ↓ 用「{label}」切（区分度{spread*100:.0f}pp）")
    s = sub.copy()
    s["档"] = bin_series(s, col, edges)
    order = t.sort_values("胜率", ascending=False).index.tolist()
    for i, lv in enumerate(order):
        if i >= 2:      # 只钻最好两格
            break
        sub2 = s[s["档"] == lv]
        if len(sub2) < MIN_LEAF:
            continue
        dims2 = [d for d in DIMS if d[0] != col]
        tree2(sub2, path + [f"{label}={lv}"], depth - 1, gname, out, dims2)


def tree2(sub, path, depth, gname, out, dims2):
    base_wr = sub["胜"].mean()
    bw = sub["持有到断板%"].mean()
    tag = "  " * (3 - depth) + "  "
    out.append(f"{tag}【{' × '.join(path)}】n={len(sub)} 胜率{base_wr*100:.0f}% "
               f"持有{bw:+.2f} | {yearly_line(sub)}")
    if depth == 0 or len(sub) < 2 * MIN_LEAF:
        return
    b = best_split(sub, dims2)
    if b is None:
        return
    label, t, spread, col, edges = b
    out.append(f"{tag}  ↓ 用「{label}」切（区分度{spread*100:.0f}pp）")
    s = sub.copy()
    s["档"] = bin_series(s, col, edges)
    order = t.sort_values("胜率", ascending=False).index.tolist()
    for i, lv in enumerate(order):
        if i >= 2:
            break
        sub2 = s[s["档"] == lv]
        if len(sub2) < MIN_LEAF:
            continue
        tree2(sub2, path + [f"{label}={lv}"], depth - 1, gname, out,
              [d for d in dims2 if d[0] != col])


def main():
    E = load()
    out = []
    for gname in GROUPS:
        sub = E[E["四组"] == gname]
        out.append(f"\n{'='*100}\n【{gname}】n={len(sub)} 池胜率{sub['胜'].mean()*100:.0f}%  "
                   f"池持有{sub['持有到断板%'].mean():+.2f}")
        out.append("\n  单维扫描（按区分度排序, 只显示前8）")
        scored = []
        for col, edges, label in DIMS:
            if col not in sub.columns or sub[col].isna().all():
                continue
            s = sub.copy()
            s["档"] = bin_series(s, col, edges)
            t = s.groupby("档", observed=True).agg(n=("胜", "size"), 胜率=("胜", "mean"),
                                                   封住率=("封住", "mean"),
                                                   持有=("持有到断板%", "mean"))
            t = t[t["n"] >= MIN_BIN]
            if len(t) < 2:
                continue
            scored.append((t["胜率"].max() - t["胜率"].min(), label, t))
        scored.sort(key=lambda x: -x[0])
        for spread, label, t in scored[:8]:
            out.append(f"\n  [{label}] 区分度{spread*100:.0f}pp")
            d = t.copy()
            d["胜率"] = (d["胜率"] * 100).round(0)
            d["封住率"] = (d["封住率"] * 100).round(0)
            d["持有"] = d["持有"].round(2)
            out.append(d.to_string())
        out.append("\n  贪心组合树（只钻每层最好的两格, 三层深）")
        tree(sub, [gname], 3, gname, out)
    text = "\n".join(out)
    print(text)
    with open("/root/project/ai/vnpy/量化因子研究/高位接力/汇总/静态条件扫描.md", "w", encoding="utf-8") as f:
        f.write("# 高位接力 · 静态条件扫描（只用买入前可知信息, 2026-09-19）\n\n```\n" + text + "\n```\n")


if __name__ == "__main__":
    main()
