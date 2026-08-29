# -*- coding: utf-8 -*-
"""U型 高度×深度 系统矩阵: 检验主人的四个问题.
Q1 2板U是否无论多深多浅都行?
Q2 3/4板能不能做U? 是3不能4能, 还是4需要更深?
Q3 5板+U是不是为了创新高? (蹲深单调性+弹回反转+破顶/距顶证据链)
Q4 5板+的最佳蹲深?
数据: 弱转强v3/地基研究/补涨阴地基全量.csv (1905笔, U型=地基以U开头)
"""
import pandas as pd

SRC = "/root/project/ai/vnpy/量化因子研究/低吸研究/弱转强v3/地基研究/补涨阴地基全量.csv"
df = pd.read_csv(SRC, encoding="utf-8-sig", dtype={"vt_symbol": str})
u = df[df["地基"].astype(str).str.startswith("U")].copy()
u["dd"] = -u["蹲深%"]          # 蹲深绝对值(12~...)
u["bad"] = u["res"].isin(["炸板", "封D1负"])
u["h"] = u["上波高"].clip(upper=5)   # 5=5板+
print(f"全量 {len(df)} 笔 | U型 {len(u)} 笔 | 高度分布: "
      f"{u['上波高'].value_counts().sort_index().to_dict()}")
print(f"U型整体: 板留均 {u['板留%'].mean():+.2f} 中位 {u['板留%'].median():+.2f} "
      f"差票率 {u['bad'].mean()*100:.0f}% 连板率 {(u['res']=='连板').mean()*100:.0f}%")

DD_BINS = [12, 15, 20, 25, 30, 40, 99]
DD_LABS = ["12-15", "15-20", "20-25", "25-30", "30-40", "40+"]
REB_BINS = [0, 3, 8, 14, 99]
REB_LABS = ["<3趴", "3-8低", "8-14弹", "14+过头"]
u["ddb"] = pd.cut(u["dd"], DD_BINS, right=False, labels=DD_LABS)
u["reb5"] = pd.cut(u["弹回%"], REB_BINS, right=False, labels=REB_LABS)


def tbl(d, by, title):
    print(f"\n== {title} ==")
    g = d.groupby(by, observed=True)
    out = pd.DataFrame({
        "n": g.size(),
        "板留均": g["板留%"].mean().round(2),
        "板留中位": g["板留%"].median().round(2),
        "差票%": (g["bad"].mean() * 100).round(0),
        "连板%": ((g["res"].apply(lambda s: (s == "连板").mean())) * 100).round(0),
        "D1收均": g["D1收%"].mean().round(2),
    })
    print(out.to_string())


# ── Q1/Q2/Q4 主矩阵: 高度 × 蹲深 ──
print("\n" + "=" * 80)
print("① 主矩阵: 上波高 × 蹲深 (板留均/中位, n, 差票%)")
piv_mean = u.pivot_table(index="h", columns="ddb", values="板留%", aggfunc="mean").round(2)
piv_n = u.pivot_table(index="h", columns="ddb", values="板留%", aggfunc="size")
piv_bad = (u.pivot_table(index="h", columns="ddb", values="bad", aggfunc="mean") * 100).round(0)
print("板留均:"); print(piv_mean.to_string())
print("n:"); print(piv_n.to_string())
print("差票%:"); print(piv_bad.to_string())

# ── 高度 × 弹回 (反转效应) ──
print("\n" + "=" * 80)
print("② 高度 × 弹回")
piv_r = u.pivot_table(index="h", columns="reb5", values="板留%", aggfunc="mean").round(2)
piv_rn = u.pivot_table(index="h", columns="reb5", values="板留%", aggfunc="size")
print("板留均:"); print(piv_r.to_string())
print("n:"); print(piv_rn.to_string())

# ── Q1: 2板蹲深细桶(深度无关检验) ──
print("\n" + "=" * 80)
u2 = u[u["上波高"] == 2]
tbl(u2, "ddb", "Q1: 2板U 蹲深细桶")
print(f"2板U整体: n={len(u2)} 板留均 {u2['板留%'].mean():+.2f} 中位 {u2['板留%'].median():+.2f} "
      f"差票 {u2['bad'].mean()*100:.0f}%")
print(f"2板U蹲深分桶板留极差: {u2.groupby('ddb', observed=True)['板留%'].mean().max() - u2.groupby('ddb', observed=True)['板留%'].mean().min():+.2f}个点")

# ── Q2: 3板/4板 ──
print("\n" + "=" * 80)
for h in (3, 4):
    s = u[u["上波高"] == h]
    print(f"\n{h}板U: n={len(s)} 板留均 {s['板留%'].mean():+.2f} 中位 {s['板留%'].median():+.2f} "
          f"差票 {s['bad'].mean()*100:.0f}% 连板 {(s['res']=='连板').mean()*100:.0f}%")
    if len(s):
        tbl(s, "ddb", f"Q2: {h}板U 蹲深")
# 3+4板合并看深度阈值方向
u34 = u[u["上波高"].isin([3, 4])]
if len(u34):
    tbl(u34, "ddb", "Q2: 3+4板合并 蹲深")

# ── Q3/Q4: 5板+ ──
print("\n" + "=" * 80)
u5 = u[u["上波高"] >= 5]
print(f"5板+U: n={len(u5)} 板留均 {u5['板留%'].mean():+.2f} 中位 {u5['板留%'].median():+.2f} "
      f"差票 {u5['bad'].mean()*100:.0f}% 连板 {(u5['res']=='连板').mean()*100:.0f}%")
tbl(u5, "ddb", "Q4: 5板+U 蹲深(最佳深度)")
tbl(u5, "reb5", "Q3: 5板+U 弹回(趴vs弹)")
tbl(u5, pd.cut(u5["断板"], [0, 5, 11, 16, 99], labels=["断0-5", "断6-10", "断11-15", "断16+"]),
    "5板+U 断板天数")
# 创新高证据链: 距顶距离(回撤%) × 板留 + 破顶
tbl(u5, pd.cut(u5["回撤%"], [-99, -20, -10, -4], labels=["距顶>20%", "距顶10-20%", "距顶4-10%"]),
    "Q3: 5板+U 距顶距离(洗得越深离新高越远=空间?)")
print(f"\n5板+U 破顶比例: {u5['破顶'].mean()*100:.0f}% | 破顶票板留 "
      f"{u5[u5['破顶']]['板留%'].mean() if u5['破顶'].any() else float('nan'):+.2f}"
      f" vs 未破顶 {u5[~u5['破顶']]['板留%'].mean() if (~u5['破顶']).any() else float('nan'):+.2f}")
# 蹲深与弹回交互(5板+): 趴+深 是否最优
u5c = u5.copy()
u5c["蹲弹"] = u5c["ddb"].astype(str) + "×" + u5c["reb5"].astype(str)
tbl(u5c, "蹲弹", "Q3/Q4: 5板+ 蹲深×弹回 交互")

# ── ⑥ 对照: 同高度非U ──
print("\n" + "=" * 80)
print("⑥ 对照: U vs 非U(FLAT/MID/LB/HIGH/DN/V合并) 分高度")
dfx = df.copy()
dfx["bad"] = dfx["res"].isin(["炸板", "封D1负"])
dfx["h"] = dfx["上波高"].clip(upper=5)
dfx["is_u"] = dfx["地基"].astype(str).str.startswith("U")
g = dfx.groupby(["h", "is_u"])
cmp = pd.DataFrame({
    "n": g.size(),
    "板留均": g["板留%"].mean().round(2),
    "板留中位": g["板留%"].median().round(2),
    "差票%": (g["bad"].mean() * 100).round(0),
})
print(cmp.to_string())
