# -*- coding: utf-8 -*-
"""高位接力 · 连板链组合研究总结（精简版文档生成，第三十三遍）。

结构: 最终方案(10买点+分年) → 回避清单(紧凑) → 今天开盘速查(只列买行) → 铁律。
口径: 正常开盘(全天一字与开盘≥9.5%顶格票剔除); 四组分开; 互斥组合无「或」; 指标分列。

宿主机纯CSV: uv run python relay_summary2.py  → 汇总/连板链组合总结.md (覆盖)
"""
import numpy as np
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
OUT = f"{ROOT}/汇总/连板链组合总结.md"
B4 = [(-99, 0, "低"), (0, 3, "平"), (3, 7, "高"), (7, 99, "强")]
L4 = [b[2] for b in B4]
GROUPS = ["二接三阳", "二接三阴", "三接四阳", "三接四阴"]
TODAY_LABS = ["低开", "平开", "高开", "强开"]
rng = np.random.default_rng(20260925)


def cut4(s):
    out = pd.Series(index=s.index, dtype="object")
    for lo, hi, lab in B4:
        out[(s >= lo) & (s < hi)] = lab
    return out


def load():
    E = pd.read_csv(f"{ROOT}/全量明细.csv", dtype={"代码": str})
    P = pd.read_csv(f"{ROOT}/首板前3日明细.csv", dtype={"代码": str})
    M = E.merge(P.drop(columns=["首板日"]), on=["代码", "买入日"], how="inner")
    M = M[~M["未完"]].copy()
    M["年"] = M["年"].astype(str)
    M["胜"] = ~M["坏票"].fillna(True).astype(bool)
    M["一板"] = cut4(M["b1开盘%"])
    M["二板"] = cut4(M["b2开盘%"])
    M["三板"] = cut4(pd.Series(np.where(M["组"] == "二接三", M["买入开盘%"], M["b3开盘%"]), index=M.index))
    M["正常"] = M["买入开盘%"] < 9.5
    # 今日档左闭右开: 0算平开; 今天开≥6%即强开(精细分箱: 6~7%连板31%收益转正, 谷底只到6%)
    # 链上板(一/二/三板)保持7线(二板6~7%仍27%在谷里)
    M["今日档"] = pd.cut(M["买入开盘%"], [-99, 0, 3, 6, 9.5], labels=TODAY_LABS, right=False)
    return M


def perm(a, b, n=2000):
    x, y = a.to_numpy(float), b.to_numpy(float)
    obs = x.mean() - y.mean()
    pool = np.concatenate([x, y])
    cnt = 0
    for _ in range(n):
        rng.shuffle(pool)
        if abs(pool[:len(x)].mean() - pool[len(x):].mean()) >= abs(obs) - 1e-12:
            cnt += 1
    return (cnt + 1) / (n + 1)


def cells4(sub):
    if len(sub) == 0:
        return "—", "—", "—", "—"
    return (f"{sub['次日连板'].mean():.0%}", f"{sub['胜'].mean():.0%}",
            f"{sub['持有到断板%'].mean():+.1f}", f"{len(sub)}")


def today(d, lo, hi):
    return (d["买入开盘%"] >= lo) & (d["买入开盘%"] < hi)


# ---------- 最终方案: 每组综合分前2(二接三阴/阳各2, 三接四阴2, 三接四阳仅1个达标) ----------
# 入选: 连板率≥40% 且 胜率≥50% 且 收益>0 且 n≥10; 组内按 综合分=胜率+每笔收益 取前2
GROUP_TOP2 = {
    "二接三阳": [
        ("【双低转强】一板低开(<0%) × 二板低开(<0%) → 今天开6~9.5%",
         lambda d: (d["一板"] == "低") & (d["二板"] == "低") & today(d, 6, 9.5)),
        ("【双平转强】一板平开(0~3%) × 二板平开(0~3%) → 今天开6~9.5%",
         lambda d: (d["一板"] == "平") & (d["二板"] == "平") & today(d, 6, 9.5)),
        ("【双强续强】一板强开(≥7%) × 二板强开(≥7%) → 今天开6~9.5%",
         lambda d: (d["一板"] == "强") & (d["二板"] == "强") & today(d, 6, 9.5)),
    ],
    "二接三阴": [
        ("【强强高启】一板强开(≥7%) × 二板强开(≥7%) → 今天开3~5%",
         lambda d: (d["一板"] == "强") & (d["二板"] == "强") & today(d, 3, 5)),
        ("【低强转强】一板低开(<0%) × 二板强开(≥7%) → 今天开6~9.5%",
         lambda d: (d["一板"] == "低") & (d["二板"] == "强") & today(d, 6, 9.5)),
    ],
    "三接四阳": [
        ("【高板低吸】三板高开(3~7%) → 今天低开(<0%)",
         lambda d: (d["三板"] == "高") & (d["买入开盘%"] < 0)),
        ("【平强确认】一板平开(0~3%) × 二板强开(≥7%) → 今天开6~9.5%",
         lambda d: (d["一板"] == "平") & (d["二板"] == "强") & today(d, 6, 9.5)),
    ],
    "三接四阴": [
        ("【低板转强】三板低开(<0%) → 今天开6~9.5%",
         lambda d: (d["三板"] == "低") & today(d, 6, 9.5)),
        ("【平推转强】一板平开(0~3%) × 二板平开(0~3%) → 今天开6~9.5%",
         lambda d: (d["一板"] == "平") & (d["二板"] == "平") & today(d, 6, 9.5)),
        ("【三板平启】三板平开(0~3%) → 今天开6~9.5%",
         lambda d: (d["三板"] == "平") & today(d, 6, 9.5)),
    ],
}


def _score(a):
    return a["胜"].mean() * 100 + a["持有到断板%"].mean()


def scheme_table(M, NB):
    finals = []
    for gi, g in enumerate(GROUPS):
        cands = []
        for desc, fn in GROUP_TOP2[g]:
            a = M[(M["四组"] == g) & NB & fn(M)]
            if len(a) == 0:
                continue
            # 入选四条硬校验(边界调整后数字漂移, 不达标者自动出局)
            if len(a) < 10 or a["次日连板"].mean() < 0.40 or a["胜"].mean() < 0.50 or a["持有到断板%"].mean() <= 0:
                continue
            cands.append((_score(a), desc, a))
        cands.sort(reverse=True, key=lambda x: x[0])
        for k, (sc, desc, a) in enumerate(cands[:2]):
            no = f"{'ABCD'[gi]}{k + 1}"          # A1/A2 B1 C1/C2 D1/D2
            finals.append((no, g, desc, a))
    main_rows, yr_rows = [], []
    for no, g, desc, a in finals:
        lb, sv, sy, n_ = cells4(a)
        sc = _score(a)
        main_rows.append(f"| {no} | {g} | {desc} | {lb} | {sv} | {sy} | {n_} | **{sc:.1f}** |")
        cells = []
        for y in ["2023", "2024", "2025", "2026"]:
            x = a[a["年"] == y]
            cells.append(f"{len(x)}笔·{x['胜'].mean():.0%}" if len(x) else "无")
        yr_rows.append(f"| {no}（{g}） | " + " | ".join(cells) + " |")
    main_tbl = "\n".join(main_rows)
    yr_tbl = "\n".join(["| 方案 | 2023 | 2024 | 2025 | 2026 |", "|---|---|---|---|---|"] + yr_rows)
    return main_tbl, yr_tbl, no, finals


def avoid_table(M, NB):
    items = [
        ("二板开3~7%（半温不火，全场最毒）", lambda d: d["二板"] == "高"),
        ("一板开3~7%", lambda d: d["一板"] == "高"),
        ("二板开3%以上 × 首板前3天涨超5%（追高透支）", lambda d: d["二板"].isin(["高", "强"]) & (d["pre3%"] > 5)),
        ("三接四阴：今天低开（板深没人接；阳组不毒别误伤）",
         lambda d: (d["四组"] == "三接四阴") & (d["买入开盘%"] < 0)),
    ]
    out = ["| 别碰 | 二接三阳 | 二接三阴 | 三接四阳 | 三接四阴 | 各组池 |",
           "|---|---|---|---|---|---|"]
    for desc, fn in items:
        cells, pools = [], []
        for g in GROUPS:
            S = M[(M["四组"] == g) & NB]
            a = S[fn(S)]
            if "三接四阴" in desc and g != "三接四阴":
                cells.append("不适用")
            else:
                cells.append(f"{a['次日连板'].mean():.0%}({len(a)})" if len(a) else "—")
            pools.append(f"{S['次日连板'].mean():.0%}")
        out.append(f"| {desc} | " + " | ".join(cells) + " | " + "/".join(pools) + " |")
    return "\n".join(out)


def main():
    M = load()
    NB = M["正常"]
    N = M[NB]
    print(f"正常开盘样本 {len(N)} (顶格剔除 {(~NB).sum()})")

    main_tbl, yr_tbl, n_pts, finals = scheme_table(M, NB)
    avoid = avoid_table(M, NB)

    # 好差票验证/链式方案策略.md (标题+条目式, 不用表格)
    strat = ["# 高位接力 · 链式方案策略（对照好差票验证月度清单用）", "",
             f"生成日期 2026-09-25 ｜ 依据：汇总/连板链组合总结.md ｜ 正常开盘口径（全天一字与开盘≥9.5%顶格票不计）",
             f"共 {len(finals)} 个方案：A=二接三阳，B=二接三阴，C=三接四阳，D=三接四阴，组内按综合分排序。", "",
             "买入前已知 = 一板、二板（三接四还有三板）的开盘涨幅，收盘后就能查到；",
             "今天开 = 买入当天（打第3板/第4板）的竞价开盘涨幅，9:25 出来后对照。", ""]
    for i, (no, g, desc, a) in enumerate(finals):
        lb, sv, sy, n_ = cells4(a)
        sc = _score(a)
        # desc = 【名】条件 → 拆成名字和分行情件
        name = desc[1:desc.index("】")]
        strat.append(f"## {no}【{name}】｜{g}")
        strat.append("")
        body = desc[desc.index("】") + 1:]
        if "→" in body:
            chain_part, today_part = body.split("→")
        else:
            chain_part, today_part = body, ""
        for cond in chain_part.split("×"):
            strat.append("- " + cond.strip())
        if today_part.strip():
            strat.append("- " + today_part.strip())
        strat.append("")
        strat.append(f"**成绩**：{n_} 笔 ｜ 连板率 {lb} ｜ 胜率 {sv} ｜ 平均每笔 {sy} ｜ 综合分 {sc:.1f}")
        strat.append("")
        parts = []
        for y in ["2023", "2024", "2025", "2026"]:
            x = a[a["年"] == y]
            if len(x):
                parts.append(f"{y}年 {len(x)}笔·胜{x['胜'].mean():.0%}·{x['持有到断板%'].mean():+.1f}")
            else:
                parts.append(f"{y}年 无")
        strat.append("**分年**：" + " ｜ ".join(parts))
        strat.append("")
        if i < len(finals) - 1:
            strat.append("---")
            strat.append("")
    strat += ["## 回避（先过滤再看方案）", "",
              "1. 一板或二板开 3~7%（半温不火，链上最毒）",
              "2. 二板开 3% 以上 × 首板前3天涨超 5%（追高透支）",
              "3. 三接四阴今天低开（板深没人接；三接四阳不适用此条）",
              "4. 全天一字、开盘 ≥9.5% 顶格（买不进，直接跳过）", "",
              "## 用法", "",
              "1. 收盘后：筛出昨日 2 连板（打3板，看 A/B 组）或 3 连板（打4板，看 C/D 组）的主板非ST票",
              "2. 按回避清单过滤",
              "3. 第二天 9:25 竞价出来后，对照方案的「今天开」档位",
              "4. 命中就打板（涨停价买入），不命中不买", "",
              "**卖出**：炸板当天收盘走；封住拿到不再涨停那天收盘（15个交易日兜底）。**仓位**：轻仓一票一份。", ""]
    with open(f"{ROOT}/好差票验证/链式方案策略.md", "w", encoding="utf-8") as f:
        f.write("\n".join(strat))
    print("已生成 好差票验证/链式方案策略.md")

    md = f"""# 高位接力 · 连板链组合总结（精简版）

样本：2023-03 ~ 2026-09，主板非ST，昨日2连板打3板 / 3连板打4板，涨停价买入持有到断板，正常开盘 {len(N)} 笔（全天一字与开盘≥9.5%顶格票已剔除）。
连板率=今天封住明天再涨停 ｜ 胜率=买入次日收盘不低于买价 ｜ 收益=每笔平均。
开盘档位：**今天开盘** 低开(<0%)｜平开(0~3%)｜高开(3~6%)｜强开(6~9.5%)｜顶格(≥9.5%买不到)；**链上的板** 低开(<0%)｜平开(0~3%)｜高开(3~7%最毒)｜强开(≥7%)。今天6%就算强，链上的板要7%。

## 一、最终方案：{n_pts} 个买点（每组综合分前2，入选=连板率≥40% 且 胜率≥50% 且 收益>0 且 ≥10笔）

| 编号 | 组 | 方案与条件 | 连板率 | 胜率 | 每笔收益 | 笔数 | 综合分 |
|---|---|---|---|---|---|---|---|
{main_tbl}

综合分=胜率+每笔收益（收益每+1%折1分）——连板率是过程指标，连板后炸板回吐的票连板率高但赚得少，排序看胜率和收益。

分年胜率：

{yr_tbl}

**用法**：收盘后筛连板池 → 过回避清单 → 竞价对照「今天开」档 → 命中打板。方案对照表在 `好差票验证/链式方案策略.md`。

## 二、回避清单（格=连板率(笔数)，四组全部低于各自池）

{avoid}

## 三、铁律（大白话）

1. **链上的板别开3~7%**：半温不火四组全部更差——要低就低到底，要强就顶格
2. **今天开6~9.5%是四组共同的确认信号**；顶格≥9.5%买不到且平庸，直接跳过
3. **二板低开只对二接三阳和三接四阴是买点**，另外两组低开没优势
4. **板打得越深低开越危险**：三接四阴今天低开=没人接，和二接三阴三板低开好完全相反
5. **首板前3天看节奏不看幅度**：先跌一天再连涨两天四组全部更好；涨跌涨反复拉锯四组全部更差
6. **整条链要么冷到底要么热到底**：温链最先死

> 每个方案点每年约5笔，分年波动大仅作参考；可靠性来自四组分开的方向一致性。完整推演用 relay_combo*.py 可复现。
"""
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"已生成 {OUT}")


if __name__ == "__main__":
    main()
