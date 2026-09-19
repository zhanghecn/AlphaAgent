# -*- coding: utf-8 -*-
"""候选格置换检验+bootstrap（纯CSV, 快）。容器内: python /tmp/research/relay_perm2.py"""
import numpy as np
import pandas as pd

OUT = "/tmp/research/relay_out"
YEARS = ["2023", "2024", "2025", "2026"]
rng = np.random.default_rng(20260919)

E = pd.read_csv(f"{OUT}/地基均线反包明细.csv", dtype={"代码": str})
E["年"] = E["年"].astype(str)
fin = E[E["持有到断板%"].notna()].copy()
fin["胜"] = fin["次日收%"] > 0

g23y = fin["四组"] == "二接三阴"
g22y = fin["四组"] == "二接三阳"
g34yang = fin["四组"] == "三接四阳"

cells = {
    "C1 二接三阴×假阴真阳(涨跌>=0)": g23y & (fin["地基涨跌%"] >= 0),
    "C2 二接三阳×涨>=4%×断1~3天": g22y & (fin["地基涨跌%"] >= 4)
        & fin["反包结构"].isin(["断1天", "断2~3天"]),
    "C3 三接四阳×前板>=2×距MA10<5%": g34yang & (fin["前板高度"].fillna(0) >= 2)
        & (fin["距MA10%"] < 5),
    "C3b 三接四阳×前板>=2×地基|涨跌|<4%": g34yang & (fin["前板高度"].fillna(0) >= 2)
        & (fin["地基涨跌%"].abs() < 4),
}

for name, m in cells.items():
    sub = fin[m]
    pool = fin[fin["四组"] == sub["四组"].iloc[0]]
    n, hold = len(sub), sub["持有到断板%"].mean()
    win = sub["胜"].mean()
    # 置换: 从同组池随机抽n笔, 均值>=观测值 的比例
    pv = pool["持有到断板%"].to_numpy()
    draws = rng.choice(pv, size=(2000, n), replace=True).mean(axis=1)
    p_hold = (draws >= hold).mean()
    # 胜率置换
    wv = pool["胜"].astype(float).to_numpy()
    wdraws = rng.choice(wv, size=(2000, n), replace=True).mean(axis=1)
    p_win = (wdraws >= win).mean()
    # bootstrap 95% CI
    sv = sub["持有到断板%"].to_numpy()
    bs = rng.choice(sv, size=(2000, n), replace=True).mean(axis=1)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    ys = " ".join(f"{y}:{sub[sub['年'] == y]['持有到断板%'].mean():+.2f}/{len(sub[sub['年'] == y])}"
                  if len(sub[sub['年'] == y]) else f"{y}:0笔" for y in YEARS)
    print(f"{name}\n  n={n} 胜率{win * 100:.0f}% 持有{hold:+.2f} | "
          f"置换p(持有)={p_hold:.4f} p(胜率)={p_win:.4f} | bootstrap95%[{lo:+.2f},{hi:+.2f}]")
    print(f"  分年 {ys}")
    # 分年全正稳定性: 每年各剔掉最好1笔再看
    ok = True
    for y in YEARS:
        sy = sub[sub["年"] == y].sort_values("持有到断板%", ascending=False)
        if len(sy) < 2:
            ok = False
            continue
        if sy.iloc[1:]["持有到断板%"].mean() <= 0:
            ok = False
    print(f"  每年各剔最好1笔后分年仍全正: {'是' if ok else '否'}")
    # C3与前波60日关系旁证
    if name.startswith("C3"):
        print(f"  前板高度分布: {dict(sub['前板高度'].value_counts().sort_index())}")
        print(f"  断板天数分布: {dict(sub['断板天数'].value_counts().sort_index())}")
