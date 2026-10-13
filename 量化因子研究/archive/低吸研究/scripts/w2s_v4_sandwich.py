# -*- coding: utf-8 -*-
"""高位夹层实验: 大波(4+/5+/6+)断板后穿插<=2板小波再起第二波, 是否救活阳线.

主人假设: 高位阳线毒, 但「大波→断板→穿插小波(1孤立板或2板段)→再涨停起第二波」的夹层结构呢?
分桶维度:
  大波高度 = mx20 窗口内最大连板(4/5/6+)
  夹层结构(按最近≥2板段高度 seg_h + 断板期孤立板数 n_lim_mid):
    无穿插     seg_h>=4(最近段=大波) 且 断板期无孤立板
    孤立板穿插  seg_h>=4 且 断板期孤立板1~2个 (小波=1板, 地基锚大波)
    2板小波穿插  seg_h==2 (最近段=2板小波, 地基锚小波, 大波在更早)
阴/阳各跑, 阳线为主人核心问题.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base, BASE_ORDER

pd.set_option("display.width", 500)

BASE_CN = {"HIGH": "新高贴顶", "FLAT": "横盘平台", "U": "U型蹲", "V": "V末反",
           "MID": "中位浅调", "LB": "L趴底", "DN": "阴跌到点"}


def stat(tg, label):
    if not len(tg):
        print(f"  {label}: n=0")
        return
    bad = tg["res"].isin(["炸板", "封D1负"])
    yr = " / ".join(f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
                    if len(sy := tg[tg["trade_date"].dt.year == yy]))
    print(f"  {label}: n={len(tg)} 板留均 {tg['r_bh'].mean() * 100:+.2f} 中位 {tg['r_bh'].median() * 100:+.2f} "
          f"胜率 {(tg['r_bh'] > 0).mean() * 100:.0f}% 差票 {bad.mean() * 100:.0f}% "
          f"连板 {(tg['res'] == '连板').mean() * 100:.0f}% | 分年 {yr}")


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)

    for yside, pcol, chg_min in (("阳", "p_yang", -0.03), ("阴", "p_yin", -0.08)):
        print("=" * 96)
        print(f"【{yside}线 · 高位夹层矩阵】(条件=V4四组, 门槛≥4)")
        c = f"cs_{yside}"
        bars[c] = ((bars["mx20"] >= 4) & bars[pcol] & (bars["p_chg"] > chg_min)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
        tg, _ = build_base(bars, segs, conds=(c,))
        tg = add_outcome(tg, bars)
        tg["bad"] = tg["res"].isin(["炸板", "封D1负"])

        # 夹层结构分桶
        def _sand(r):
            if r["seg_h"] == 2:
                return "2板小波穿插"
            if r["seg_h"] == 3:
                return "3板小波穿插"
            nm = r["n_lim_mid"]
            if nm == nm and 1 <= nm <= 2:
                return "孤立板穿插"
            return "无穿插"

        tg["夹层"] = tg.apply(_sand, axis=1)
        for lab in ("无穿插", "孤立板穿插", "2板小波穿插", "3板小波穿插"):
            s = tg[tg["夹层"] == lab]
            if len(s):
                stat(s, f"{lab} 全体(≥4)")

        # 主人核心: 大波高度 × 夹层结构
        print(f"\n── {yside}线 大波高度 × 夹层结构 ──")
        rows = []
        for hlab, hmask in (("恰4板", tg["mx20"] == 4), ("恰5板", tg["mx20"] == 5),
                            ("6板+", tg["mx20"] >= 6)):
            for slab in ("无穿插", "孤立板穿插", "2板小波穿插", "3板小波穿插"):
                s = tg[hmask & (tg["夹层"] == slab)]
                if not len(s):
                    continue
                bad = s["res"].isin(["炸板", "封D1负"])
                rows.append({"大波": hlab, "夹层": slab, "n": len(s),
                             "板留均": round(s["r_bh"].mean() * 100, 2),
                             "胜率%": round((s["r_bh"] > 0).mean() * 100),
                             "连板%": round((s["res"] == "连板").mean() * 100)})
        print(pd.DataFrame(rows).to_string(index=False))

        # 夹层甜点格的分年
        print(f"\n── {yside}线 夹层候选甜点分年 ──")
        for hlab, hmask in (("全体≥4", tg["mx20"] >= 4), ("恰4板", tg["mx20"] == 4),
                            ("6板+", tg["mx20"] >= 6)):
            for slab in ("孤立板穿插", "2板小波穿插"):
                s = tg[hmask & (tg["夹层"] == slab)]
                if len(s) >= 15:
                    stat(s, f"{hlab}×{slab}")

        # 夹层结构 × 地基(阳线, 找夹层票的地基画像)
        print(f"\n── {yside}线 夹层(2板小波+孤立板) × 地基 ──")
        sw = tg[tg["夹层"].isin(["孤立板穿插", "2板小波穿插"])]
        rows = []
        for b in BASE_ORDER:
            s = sw[sw["base"] == b]
            if not len(s):
                continue
            rows.append({"地基": BASE_CN[b], "n": len(s),
                         "板留均": round(s["r_bh"].mean() * 100, 2),
                         "胜率%": round((s["r_bh"] > 0).mean() * 100),
                         "连板%": round((s["res"] == "连板").mean() * 100)})
        if rows:
            print(pd.DataFrame(rows).to_string(index=False))

        # 断板天数: 夹层票的等待时长分布(第二波启动前的蓄势)
        print(f"\n── {yside}线 2板小波穿插 × 断板分桶(距小波末板) ──")
        s2 = tg[tg["夹层"] == "2板小波穿插"].copy()
        if len(s2):
            s2["gb"] = pd.cut(s2["gap"], [1, 5.5, 10.5, 15.5, 20.5],
                             labels=["断2-5", "断6-10", "断11-15", "断16-20"])
            t = s2.groupby("gb", observed=True).agg(n=("r_bh", "size"), 板留均=("r_bh", "mean"),
                                                    胜率=("r_bh", lambda s: (s > 0).mean()))
            t["胜率"] = (t["胜率"] * 100).round(0)
            t["板留均"] = (t["板留均"] * 100).round(2)
            print(t.to_string())


if __name__ == "__main__":
    main()
