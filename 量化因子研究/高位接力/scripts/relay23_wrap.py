# -*- coding: utf-8 -*-
"""二接三/三接四 · P10 收尾(宿主机: uv run python relay23_wrap.py)。

A. C2 双腿重叠度: 小阳腿(block_foundation_chg 1~3×三开<7) × 锚点腿(block_anchor)
   各剔多少票/重叠多少 → 若高度重叠可合并简化。
B. 动态组当前状态: 近12月两组各自E3均值(2025-10~2026-09), 现在该用哪组?
   逐月滚动表现 + 切换预警信号。
C. 2026年(最近一年)口诀逐条体检: 哪条正在失效/走强?
"""
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 240)


def stat(g: pd.DataFrame) -> str:
    e3 = g["E3%"].dropna()
    if not len(g):
        return "0笔"
    return f"{len(g):3d}笔 {e3.mean():+6.2f}/{(e3 > 0).mean() * 100:3.0f}%"


def main() -> None:
    E = pd.read_pickle("/tmp/relay23_tagged.pkl")

    print("=" * 24, "A. C2 双腿重叠度(全池 C2链条件票)", "=" * 24)
    # C2 链条件: 三接四(不分阴阳) × 三换10~20 × 今开5~9.5(不含一字系——那是C3)
    # 重建C2链池: N=3 × b3换10~20 × 今开5~9.5 × 非一字系(b2/b3无一字)
    n3 = E[E["N"] == 3].copy()
    yizi = (n3["b2开盘%"] >= 9.5) | (n3["b3开盘%"] >= 9.5)
    c2pool = n3[n3["b3换手%"].between(10, 20) & n3["买入开盘%"].between(5, 9.5) & ~yizi]
    print(f"C2链池(三换10~20×今开5~9.5×非一字): {len(c2pool)}笔 {stat(c2pool)}")
    # 小阳腿剔: 地基1~3 且 三开<7
    leg_xy = c2pool["地基涨跌%"].between(1, 3) & (c2pool["b3开盘%"] < 7)
    # 锚点腿剔: 贴锚-2~0且距≤7, 或超锚≥5
    ap = c2pool["锚位%"]
    ad = c2pool["锚距"]
    leg_anchor = ((ap >= -2) & (ap < 0) & (ad <= 7)) | (ap >= 5)
    print(f"  小阳腿剔: {leg_xy.sum()}笔 | 锚点腿剔: {leg_anchor.sum()}笔 | "
          f"两腿都剔(重叠): {(leg_xy & leg_anchor).sum()}笔")
    print(f"  小阳腿剔的票: {stat(c2pool[leg_xy])}")
    print(f"  锚点腿剔的票: {stat(c2pool[leg_anchor])}")
    print(f"  两腿都不剔(=C2命中): {stat(c2pool[~leg_xy & ~leg_anchor])}")
    print(f"  仅小阳腿剔: {stat(c2pool[leg_xy & ~leg_anchor])}")
    print(f"  仅锚点腿剔: {stat(c2pool[~leg_xy & leg_anchor])}")

    print("\n" + "=" * 24, "B. 动态组当前状态(近12月滚动)", "=" * 24)
    H = E[E["口诀"] != "—"].copy()
    strong_nos = ("A1", "A2", "B1", "B2", "B3", "C1", "C2", "C3")
    weak_nos = ("K2", "K4", "K5", "K9", "K3")
    H["组"] = H["口诀"].map(lambda s: "强市" if s in strong_nos else "弱市")
    # 近12个交易月(2025-10 ~ 2026-09)
    months = sorted(H["月"].unique())
    recent = months[-14:]
    print(f"最近月份: {recent}")
    for m in recent:
        g = H[H["月"] == m]
        gs = g[g["组"] == "强市"]["E3%"]
        gw = g[g["组"] == "弱市"]["E3%"]
        print(f"  {m}: 强市{len(gs):2d}笔{gs.mean() if len(gs) else float('nan'):+6.2f} | "
              f"弱市{len(gw):2d}笔{gw.mean() if len(gw) else float('nan'):+6.2f}")
    r12 = H[H["月"].isin(months[-12:])]
    s12 = r12[r12["组"] == "强市"]["E3%"]
    w12 = r12[r12["组"] == "弱市"]["E3%"]
    print(f"\n近12月({months[-12]}~{months[-1]}): 强市 {len(s12)}笔 均{s12.mean():+.2f} | "
          f"弱市 {len(w12)}笔 均{w12.mean():+.2f}")
    print(f"→ 按动态组判据(近12月均值高者): 当前应启用 "
          f"{'强市组' if s12.mean() >= w12.mean() else '弱市组'}"
          f"(样本不足8笔双开规则: 强{len(s12)}/弱{len(w12)})")
    # 全时段各年两组对比
    print("\n  分年两组对比:")
    for y, gg in H.groupby("年"):
        gs = gg[gg["组"] == "强市"]["E3%"]
        gw = gg[gg["组"] == "弱市"]["E3%"]
        print(f"    {y}: 强市{len(gs):3d}笔{gs.mean() if len(gs) else float('nan'):+7.2f} | "
              f"弱市{len(gw):3d}笔{gw.mean() if len(gw) else float('nan'):+7.2f}")

    print("\n" + "=" * 24, "C. 2026年口诀逐条体检", "=" * 24)
    y26 = H[H["年"] == 2026]
    for no in ("A1", "A2", "B1", "B2", "B3", "C1", "C2", "C3", "K2", "K4", "K5", "K9", "K3"):
        g = y26[y26["口诀"] == no]
        if len(g):
            print(f"  {no}: {stat(g)} | 逐笔: "
                  + " ".join(f"{r['名称']}{r['E3%']:+.0f}" for _, r in g.iterrows()))


if __name__ == "__main__":
    main()
