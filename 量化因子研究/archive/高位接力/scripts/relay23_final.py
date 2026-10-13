# -*- coding: utf-8 -*-
"""二接三/三接四 · P9 收尾三题(宿主机: uv run python relay23_final.py)。

A. 「换手接力」跨板位: C2形态(末板换10~20×今开5~9.5)在 N=2 的表现?
   若成立 → 跨板位通用口诀候选; 若不成立 → C2专属是三接四特殊性证据。
B. 环境仓位层模拟(方向2·不降判定质量提收益):
   口诀命中票按「昨日4板+家数≥7 或 涨停≥100」拥挤段减半仓(0.5仓),
   对比 满仓基准 的 总收益/回撤/大亏暴露。
C. 口诀族合计体检: 锁仓系(A1/A2/K5/C3)/强开系(B1/C1)/低吸系(B2/K9/K3)/
   换手系(C2/K2/K4/B3) 各族全时段成绩——「族」视角的合并可行性。
"""
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 240)


def stat(g: pd.DataFrame) -> str:
    e3 = g["E3%"].dropna()
    if not len(g):
        return "—"
    trim = e3.sort_values().iloc[:-3] if len(e3) > 3 else e3
    return (f"{len(g):4d}笔 {e3.mean():+6.2f}/{(e3 > 0).mean() * 100:3.0f}% "
            f"剔3:{trim.mean():+5.2f} 亏:{(e3 <= -10).sum():2d}")


def main() -> None:
    E = pd.read_pickle("/tmp/relay23_tagged.pkl")
    E["末板换"] = E.apply(lambda r: r["b2换手%"] if r["N"] == 2 else r["b3换手%"], axis=1)

    print("=" * 24, "A. 换手接力跨板位(末换10~20×今开5~9.5)", "=" * 24)
    base = E["末板换"].between(10, 20) & E["买入开盘%"].between(5, 9.5)
    for n in (2, 3):
        for y in ("阳", "阴"):
            g = E[base & (E["N"] == n) & (E["阴阳"] == y)]
            wk = g[g["年"] <= 2022]
            st = g[g["年"] >= 2023]
            print(f"  {n}接{n + 1}{y}: {stat(g)}")
            print(f"      弱: {stat(wk)} | 强: {stat(st)} | 现有命中: {g['口诀'].value_counts().head(3).to_dict()}")

    print("\n" + "=" * 24, "B. 环境拥挤段减半仓模拟(口诀命中票)", "=" * 24)
    H = E[E["口诀"] != "—"].copy()
    crowd = (H["昨日4板+家数"] >= 7) | (H["昨日涨停家数"] >= 100)
    H["拥挤"] = crowd
    print(f"命中票 {len(H)} 笔, 拥挤段 {crowd.sum()} 笔({crowd.mean() * 100:.0f}%)")
    full = H["E3%"].sum()
    half = H["E3%"].where(~crowd, H["E3%"] * 0.5).sum()
    skip = H["E3%"].where(~crowd, 0).sum()
    print(f"  满仓基准: 总和{full:+.1f} 均值{H['E3%'].mean():+.2f}")
    print(f"  拥挤减半: 总和{half:+.1f} (对满仓 {half - full:+.1f})")
    print(f"  拥挤跳过: 总和{skip:+.1f} (对满仓 {skip - full:+.1f})")
    cw = H[crowd]
    ncw = H[~crowd]
    print(f"  拥挤段票: {stat(cw)}")
    print(f"  非拥挤段: {stat(ncw)}")
    print("  拥挤段逐票(看减半仓救回/错过什么):")
    for _, r in cw.sort_values("E3%").iterrows():
        print(f"    {r['买入日']} {r['代码']} {r['名称']:<8s} {r['口诀']:>3s} E3={r['E3%']:+6.1f} "
              f"家数{r['昨日4板+家数']:.0f} 涨停{r['昨日涨停家数']:.0f}")
    # 分年稳健性
    print("  减半仓分年(总和):")
    for y, gg in H.groupby("年"):
        f_ = gg["E3%"].sum()
        h_ = gg["E3%"].where(~gg["拥挤"], gg["E3%"] * 0.5).sum()
        print(f"    {y}: 满仓{f_:+7.1f} → 减半{h_:+7.1f} (差{h_ - f_:+6.1f})")

    print("\n" + "=" * 24, "C. 口诀族体检(全时段)", "=" * 24)
    fams = {
        "锁仓系(A1/A2/K5/C3)": ["A1", "A2", "K5", "C3"],
        "强开系(B1/C1)": ["B1", "C1"],
        "低吸系(B2/K9/K3)": ["B2", "K9", "K3"],
        "换手系(C2/K2/K4/B3)": ["C2", "K2", "K4", "B3"],
    }
    for fname, nos in fams.items():
        g = H[H["口诀"].isin(nos)]
        wk = g[g["年"] <= 2022]
        st = g[g["年"] >= 2023]
        print(f"  {fname}: {stat(g)}")
        print(f"      弱: {stat(wk)} | 强: {stat(st)}")


if __name__ == "__main__":
    main()
