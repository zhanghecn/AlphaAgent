"""二接三阳·二板开[1,3)死段审计(2026-10-23 立项;计划=requirements/hpr_dead_band_audit_plan.md)。

背景:诺德股份(600110 2025-06-19 +53.85%)落在阳组二板开 1~3 死段;当年死段结论
38~40% 胜率只切过换手维度。本脚本按已入库特征重切死段,找被均值掩埋的可救子格。

口径:样本枚举/涨停判定/阴阳分组/E3 卖出纪律全部复用 backtest.build_events(),
与产品回测完全同源;本脚本只做过滤/切格/统计,不手搓任何判定。
翻案三道门:分年全正 + n≥8 + 与八条零重叠(b2∈[1,3) 与八条链区间天然不相交)。

用法(api 容器内,只读不写库):python dead_band_audit.py
"""

from __future__ import annotations

import os

import pandas as pd
from sqlalchemy import create_engine, text

from alphaagent.server.services.high_relay import contracts
from alphaagent.server.services.high_relay.backtest import build_events

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 50)

GATE_N = 8          # 翻案门:样本数
GATE_YEAR_N = 3     # 分年全正判据只看样本≥3 的年
GATE_AVG = 5.0      # 候选格预筛:E3 均值远超死段基准


def _fmt_stats(g: pd.DataFrame) -> dict[str, object]:
    e3 = g["E3%"].dropna()
    if len(g) == 0:
        return {"n": 0, "胜%": None, "均E3%": None, "中位E3%": None, "分年min%": None}
    yearly = g.groupby(g["买入日"].dt.strftime("%Y"))["E3%"].agg(["count", "mean"])
    good = yearly[yearly["count"] >= GATE_YEAR_N]["mean"]
    return {
        "n": len(g),
        "胜%": round(float((e3 >= 0).mean() * 100), 1) if len(e3) else None,
        "均E3%": round(float(e3.mean()), 2) if len(e3) else None,
        "中位E3%": round(float(e3.median()), 2) if len(e3) else None,
        "分年min%": round(float(good.min()), 2) if len(good) else None,
    }


def cut_report(d: pd.DataFrame, title: str,
               cuts: list[tuple[str, object]]) -> None:
    rows = [{"档": label, **_fmt_stats(d[sel(d)])} for label, sel in cuts]
    out = pd.DataFrame(rows)
    print(f"\n── {title} ──")
    print(out.to_string(index=False))


def load_month_states() -> dict[str, str]:
    """动态组月状态(物化单一事实源;结构自适应 dict/list)。"""
    eng = create_engine(os.environ["DATABASE_URL"])
    ms = pd.read_sql(text(
        "SELECT payload->'dyn_month_states' AS ms FROM hpr_backtest_runs "
        "ORDER BY id DESC LIMIT 1"), eng)["ms"].iloc[0]
    if isinstance(ms, dict):
        return {str(k): str(v) for k, v in ms.items()}
    if isinstance(ms, list):
        return {str(m.get("m")): str(m.get("state", m)) for m in ms}
    return {}


def main() -> None:
    E, bars = build_events()
    vol = bars["volume"].to_numpy()

    # 样本 = 二接三阳 · 正常开盘(顶格剔,与 miss 对照同口径) · 已完
    d = E[(E["四组"] == "二接三阳") & (E["买入开盘%"] < contracts.TODAY_CAP)
          & (~E["未完"])].copy()
    for c in ("昨日涨停家数", "前波60日最高板", "前20日涨幅%"):
        d[c] = pd.to_numeric(d[c], errors="coerce")

    # 量能倍数 = 二板量/一板量(_bar_i=买入日行号;二板=i-1,一板=i-2)
    vr: list[float | None] = []
    for i in d["_bar_i"]:
        v1, v2 = vol[i - 2], vol[i - 1]
        vr.append(round(float(v2) / float(v1), 2) if v1 and v1 > 0 else None)
    d["量能倍数"] = vr

    dead = d[(d["b2开盘%"] >= 1.0) & (d["b2开盘%"] < 3.0)].copy()

    print("== 基准(二接三阳·正常开盘·已完) ==")
    print(pd.DataFrame([
        {"池": "全组(对照)", **_fmt_stats(d)},
        {"池": "死段 b2开[1,3)", **_fmt_stats(dead)},
        {"池": "非死段(对照-死段)", **_fmt_stats(d.drop(dead.index))},
    ]).to_string(index=False))
    print("\n[死段分年 E3%]")
    print(dead.groupby(dead["买入日"].dt.strftime("%Y"))["E3%"]
          .agg(["count", "mean"]).round(2).to_string())

    L = lambda g, col, lo, hi: g[col].between(lo, hi, inclusive="left")  # noqa: E731
    GE = lambda g, col, x: g[col] >= x  # noqa: E731
    LT = lambda g, col, x: g[col] < x  # noqa: E731
    EQ = lambda g, col, x: g[col] == x  # noqa: E731
    NA = lambda g, col: g[col].isna()  # noqa: E731

    cut_report(dead, "前20日涨幅%(半山腰毒档迁移)", [
        ("<0 回调地基", lambda g: LT(g, "前20日涨幅%", 0)),
        ("0~5 刚启动", lambda g: L(g, "前20日涨幅%", 0, 5)),
        ("5~15 半山腰", lambda g: L(g, "前20日涨幅%", 5, 15)),
        ("15+ 高位", lambda g: GE(g, "前20日涨幅%", 15)),
        ("缺", lambda g: NA(g, "前20日涨幅%")),
    ])
    cut_report(dead, "前波60日最高板(跨档真判别器迁移)", [
        ("0 无连板段", lambda g: EQ(g, "前波60日最高板", 0)),
        ("1~2", lambda g: L(g, "前波60日最高板", 1, 3)),
        ("3+ 高位前波", lambda g: GE(g, "前波60日最高板", 3)),
    ])
    cut_report(dead, "今天开%", [
        ("0~3", lambda g: L(g, "买入开盘%", 0, 3)),
        ("3~6 温开", lambda g: L(g, "买入开盘%", 3, 6)),
        ("6~9.5 强开", lambda g: GE(g, "买入开盘%", 6)),
    ])
    cut_report(dead, "量能倍数(二板量/一板量)", [
        ("<1 缩量", lambda g: LT(g, "量能倍数", 1)),
        ("1~2", lambda g: L(g, "量能倍数", 1, 2)),
        ("2~4", lambda g: L(g, "量能倍数", 2, 4)),
        ("4+ 巨量", lambda g: GE(g, "量能倍数", 4)),
        ("缺", lambda g: NA(g, "量能倍数")),
    ])
    cut_report(dead, "昨日涨停家数(环境)", [
        ("<30 冰点", lambda g: LT(g, "昨日涨停家数", 30)),
        ("30~60", lambda g: L(g, "昨日涨停家数", 30, 60)),
        ("60+ 沸腾", lambda g: GE(g, "昨日涨停家数", 60)),
        ("缺", lambda g: NA(g, "昨日涨停家数")),
    ])
    cut_report(dead, "b2板型", [
        ("实体", lambda g: g["b2板型"] == "实体"),
        ("下影", lambda g: g["b2板型"] == "下影"),
        ("一字", lambda g: g["b2板型"] == "一字"),
    ])
    cut_report(dead, "地基涨跌%", [
        ("<0 阴地基", lambda g: LT(g, "地基涨跌%", 0)),
        ("0~3 小阳", lambda g: L(g, "地基涨跌%", 0, 3)),
        ("3+ 大阳", lambda g: GE(g, "地基涨跌%", 3)),
        ("缺", lambda g: NA(g, "地基涨跌%")),
    ])
    cut_report(dead, "地基姿态(v6.10 尺)", [
        ("站线上", lambda g: g["地基姿态"] == "站线上"),
        ("骑线", lambda g: g["地基姿态"] == "骑线"),
        ("贴线", lambda g: g["地基姿态"] == "贴线"),
        ("掉线下", lambda g: g["地基姿态"] == "掉线下"),
        ("缺", lambda g: g["地基姿态"].isna()),
    ])
    cut_report(dead, "b2换手%(复核当年『换手救不动』)", [
        ("<5", lambda g: LT(g, "b2换手%", 5)),
        ("5~12", lambda g: L(g, "b2换手%", 5, 12)),
        ("12+", lambda g: GE(g, "b2换手%", 12)),
        ("缺", lambda g: NA(g, "b2换手%")),
    ])
    cut_report(dead, "换手梯度(b2-b1)", [
        ("<0 降", lambda g: LT(g, "换手梯度", 0)),
        ("0~5", lambda g: L(g, "换手梯度", 0, 5)),
        ("5+", lambda g: GE(g, "换手梯度", 5)),
        ("缺", lambda g: NA(g, "换手梯度")),
    ])

    # ── 先验组合格(单特征方向为正才看;防多重检验不做全枚举) ──
    print("\n== 先验组合格 ==")
    combos = {
        "刚启动(0~5)×前波60≤2": lambda g: L(g, "前20日涨幅%", 0, 5) & L(g, "前波60日最高板", 0, 3),
        "刚启动(0~5)×今开3~6": lambda g: L(g, "前20日涨幅%", 0, 5) & L(g, "买入开盘%", 3, 6),
        "前波60≤2×今开3~6": lambda g: L(g, "前波60日最高板", 0, 3) & L(g, "买入开盘%", 3, 6),
        "刚启动×前波60=0(60日无连板段)": lambda g: L(g, "前20日涨幅%", 0, 5) & EQ(g, "前波60日最高板", 0),
    }
    for name, fn in combos.items():
        row = _fmt_stats(dead[fn(dead)])
        gate = (row["n"] and row["n"] >= GATE_N and row["均E3%"] is not None
                and row["均E3%"] >= GATE_AVG and row["分年min%"] is not None
                and row["分年min%"] > 0)
        print(f"{'✅候选' if gate else '  '} {name}: {row}")

    # ── 巨量格深挖(第一轮唯一爆出的正格;防假格子:分年/门槛/离群/组合四连检) ──
    cols = ["代码", "名称", "买入日", "b2开盘%", "b2换手%", "买入开盘%",
            "前20日涨幅%", "前波60日最高板", "量能倍数", "昨日涨停家数", "E3%", "E3原因"]
    big = dead[GE(dead, "量能倍数", 4)]
    print("\n== 巨量格(量能倍数≥4)深挖 ==")
    print(big.groupby(big["买入日"].dt.strftime("%Y"))["E3%"]
          .agg(["count", "mean"]).round(2).to_string())
    for th in (2.5, 3.0, 3.5, 4.0, 4.5, 5.0):
        sel = dead[GE(dead, "量能倍数", th)]
        print(f"  量能≥{th}: {_fmt_stats(sel)}")
    for name, fn in {
        "量4+×地基3+": lambda g: GE(g, "量能倍数", 4) & GE(g, "地基涨跌%", 3),
        "量4+×换手12+": lambda g: GE(g, "量能倍数", 4) & GE(g, "b2换手%", 12),
        "量4+×梯度5+": lambda g: GE(g, "量能倍数", 4) & GE(g, "换手梯度", 5),
        "量3+×换手12+": lambda g: GE(g, "量能倍数", 3) & GE(g, "b2换手%", 12),
    }.items():
        print(f"  {name}: {_fmt_stats(dead[fn(dead)])}")
    print(f"  剔top1离群: {_fmt_stats(big.sort_values('E3%', ascending=False).iloc[1:])}")
    print("[巨量格逐笔]")
    print(big.sort_values("E3%", ascending=False)[cols].to_string(index=False))

    # ── 候选格窗边界扰动(b2 窗 ±0.5 抖动) ──
    print("\n== 窗边界扰动(死段基准复核:全段对窗边界不敏感才算段,不挑格) ==")
    for lo, hi in [(0.5, 3.0), (1.5, 3.0), (1.0, 2.5), (1.0, 3.5), (1.5, 2.5)]:
        sel = dead[(dead["b2开盘%"] >= lo) & (dead["b2开盘%"] < hi)]
        print(f"  b2[{lo},{hi}): {_fmt_stats(sel)}")

    # ── 动态组月状态下的死段(八条启用时代才有意义) ──
    states = load_month_states()
    if states:
        d["dyn"] = d["月"].map(states)
        dd = dead.copy()
        dd["dyn"] = dd["月"].map(states)
        print("\n== 死段 × 动态组月状态 ==")
        for st in ("strong", "weak", "both"):
            sel = dd[dd["dyn"] == st]
            if len(sel):
                print(f"  {st}: {_fmt_stats(sel)}")
    else:
        print("\n(动态组月状态物化不可读,跳过)")

    # ── 案例门禁:诺德 + 死段盈亏两端各 8 笔 ──
    print("\n== 案例点名 ==")
    nd = dead[(dead["代码"] == "600110.SSE") & (dead["买入日"] == "2025-06-19")]
    print(f"诺德在死段样本内: {len(nd)} 笔, E3%={float(nd['E3%'].iloc[0]) if len(nd) else '—'}")
    show = dead.sort_values("E3%", ascending=False)
    print("\n[盈端 top8]")
    print(show.head(8)[cols].to_string(index=False))
    print("\n[亏端 bottom8]")
    print(show.tail(8)[cols].to_string(index=False))
    print(f"\n死段合计 {len(dead)} 笔,明细列同上(如需全量逐笔再跑一次改打印)")


if __name__ == "__main__":
    main()
