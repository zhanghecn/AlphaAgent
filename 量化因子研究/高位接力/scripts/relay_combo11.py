# -*- coding: utf-8 -*-
"""高位接力 · C/D 与 A/B 血缘关系验证（第三十三遍v2）。

主人猜想: 二接三盈利封住 → 次日即三接四接力,C/D 可否精简为「A/B + 开盘价」共用?
① 正向: C/D 九点票回溯「昨天按二接三五点判」命中什么(链=同一根一板二板,
   昨天的今开=三板开盘%)
② 反向: A/B 命中且封住的票, 次日四板按 C/D 判命中什么(首板日对齐同一条链)
宿主机纯CSV: uv run python relay_combo11.py
"""
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 480)
pd.set_option("display.max_rows", 200)

E = pd.read_csv(f"{ROOT}/全量明细.csv", dtype={"代码": str})
M = E[~E["未完"]].copy()
M["年"] = M["年"].astype(str)
M["胜"] = ~M["坏票"].fillna(True).astype(bool)


def ab_point(b1, b2, t, v):
    """二接三五点判定: b1/b2=链开盘%, t=今天开盘%, v=二板换手%。"""
    if 6 <= t < 9.5:
        if b1 < 0 and b2 < 1 and v < 12:
            return "A1"
        if 0 <= b1 < 3 and 0 <= b2 < 1:
            return "A2"
        if b1 < 0 and 7 <= b2 < 8.5:
            return "B2"
        if b1 >= 3 and b2 >= 9.5 and 7 <= t < 8.5:
            return "A3"
    if b1 >= 7 and b2 >= 7 and v >= 5 and 3 <= t < 5:
        return "B1"
    return "miss"


def cd_point(r):
    """三接四四点判定(九点版)。"""
    b1, b2, b3, t, yy = r["b1开盘%"], r["b2开盘%"], r["b3开盘%"], r["买入开盘%"], r["阴阳"]
    if yy == "阳" and 5 <= b3 < 7 and t < 0:
        return "C1"
    if yy == "阳" and 0 <= b1 < 3 and b2 >= 9.5 and b3 >= 9.5 and 6 <= t < 9.5:
        return "C2"
    if yy == "阴" and b3 < 0 and 6 <= t < 9.5:
        return "D1"
    if yy == "阴" and b1 < 3 and 0 <= b3 < 3 and 6 <= t < 9.5:
        return "D2"
    return "miss"


S34 = M[(M["组"] == "三接四") & (M["买入开盘%"] < 9.5)].copy()
S34["四板点"] = S34.apply(cd_point, axis=1)
S34["昨日命中"] = S34.apply(
    lambda r: ab_point(r["b1开盘%"], r["b2开盘%"], r["b3开盘%"], r["b2换手%"]), axis=1)

print("=" * 100)
print("① C/D 各点票的「昨日命中」分布")
print("=" * 100)
for no in ["C1", "C2", "D1", "D2"]:
    d = S34[S34["四板点"] == no]
    dist = d["昨日命中"].value_counts().to_dict()
    print(f"\n{no} ({len(d)}笔) 昨日命中: {dist}")
    # 链结构透视: 即使miss, 看链一板二板像A/B哪个点
    for lab, f in [("一板<0×二板<1(A1链)", lambda x: (x["b1开盘%"]<0)&(x["b2开盘%"]<1)),
                   ("一板0~3×二板0~1(A2链)", lambda x: (x["b1开盘%"]>=0)&(x["b1开盘%"]<3)&(x["b2开盘%"]>=0)&(x["b2开盘%"]<1)),
                   ("一板≥3×二板一字(A3链)", lambda x: (x["b1开盘%"]>=3)&(x["b2开盘%"]>=9.5)),
                   ("一板≥7×二板≥7(B1链)", lambda x: (x["b1开盘%"]>=7)&(x["b2开盘%"]>=7)),
                   ("一板<0×二板7~8.5(B2链)", lambda x: (x["b1开盘%"]<0)&(x["b2开盘%"]>=7)&(x["b2开盘%"]<8.5))]:
        sub = d[f(d)]
        if len(sub):
            print(f"    {lab}: {len(sub)}笔 (三板开 {sorted(sub['b3开盘%'].round(1).tolist())})")

print()
print("=" * 100)
print("② 反向: A/B 命中且封住(次日连板)的票 → 次日四板点分布")
print("=" * 100)
S23 = M[(M["组"] == "二接三") & (M["买入开盘%"] < 9.5)].copy()
S23["命中"] = S23.apply(
    lambda r: ab_point(r["b1开盘%"], r["b2开盘%"], r["买入开盘%"], r["b2换手%"]), axis=1)
AB = S23[S23["命中"] != "miss"]
kept = AB[AB["次日连板"]]
print(f"A/B 命中 {len(AB)}笔, 封住 {len(kept)}笔")
T34 = S34[["代码", "首板日", "四板点", "买入开盘%", "b3开盘%", "胜", "持有到断板%"]].rename(
    columns={"买入开盘%": "四板今开", "胜": "四板胜", "持有到断板%": "四板收益%"})
al = kept.merge(T34, on=["代码", "首板日"], how="inner")
print(f"次日仍在三接四表(未断板未完)对齐到 {len(al)}笔:")
if len(al):
    print(al["四板点"].value_counts().to_string())
    print()
    cols = ["名称", "命中", "b3开盘%", "四板今开", "四板点", "四板收益%"]
    print(al[cols].to_string(index=False, float_format=lambda x: f"{x:.2f}"))

print()
print("=" * 100)
print("③ 共用框架检查: 九点里 C/D 的链是否就是 A/B 的链(换个今天开窗)?")
print("=" * 100)
print("""
C1 链 = 不限(只看三板5~7)   ≠ 任何A/B链
C2 链 = 一板0~3×二板一字     ≈ A2一板段×A3二板一字 的杂交, 不等于任何A/B链
D1 链 = 不限(只看三板<0)     ≠ 任何A/B链
D2 链 = 一板<3×二板不限       ≈ A1/B2一板段×二板放宽, 不等于任何A/B链
""")
