# -*- coding: utf-8 -*-
"""二接三/三接四 · P2 形态原型全因子检验(宿主机: uv run python relay23_morph.py)。

假说: 现有14条口诀是少数「形态原型」在 板位×阴阳×时代 上的碎片。
抽出原型做全谱检验, 找「跨板位/跨阴阳/跨时代」皆正的通用格(合并候选),
以及只在单一格成立的时代专属格(维持现状的证据)。

原型(全部事前特征: 链开盘+换手+竞价, T-1收盘+9:25竞价可知):
  M1 贴零强开: 末板开∈[0,3) × 今开∈[6,9.5)      (A1/K5 同构)
  M2 贴零强开·深贴: 末板开<1 × 今开∈[6,9.5)      (A1原版)
  M3 一字转强: 末板开≥9.5 × 今开∈[7,8.5)          (A2)
  M4 强开续强: 末板开∈[7,9.5) × 今开∈[6,9.5)      (B1续强)
  M5 冒泡转弱: 末板开∈[3,7) × 今开<3              (C1骨架)
  M6 双洗温推: 一板<0 × 二板<0 × 今开∈[3,7)       (K3/K9 骨架)
  M7 低开捡尸: 一板<0 × 二板<0 × 今开<0           (B2骨架)
  M8 温开慢推: 末板开<1 × 今开∈[3,6)              (B3骨架)
每原型 × 板位(N=2/3) × 阴阳 × 时代(20-22/23+) 全因子展开。
"""
import pandas as pd

ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
pd.set_option("display.width", 240)


def load() -> pd.DataFrame:
    E = pd.read_pickle("/tmp/relay23_tagged.pkl")
    return E


def stat(g: pd.DataFrame) -> str:
    e3 = g["E3%"].dropna()
    if not len(g):
        return "—"
    trim = e3.sort_values().iloc[:-3] if len(e3) > 3 else e3
    return (f"{len(g):3d}笔 {e3.mean():+6.2f}/{(e3 > 0).mean() * 100:3.0f}% "
            f"剔3:{trim.mean():+5.2f} 亏≤-10:{(e3 <= -10).sum()}")


def morph_masks(E: pd.DataFrame) -> dict[str, pd.Series]:
    """每个原型返回布尔mask。末板开盘: N=2看b2, N=3看b3。"""
    last_open = E.apply(lambda r: r["b2开盘%"] if r["N"] == 2 else r["b3开盘%"], axis=1)
    E = E.assign(末板开=last_open)
    b1 = E["b1开盘%"]
    jin = E["买入开盘%"]
    return {
        "M1 贴零强开(末0~3×今6~9.5)": E["末板开"].between(0, 3) & jin.between(6, 9.5),
        "M2 深贴强开(末<1×今6~9.5)": (E["末板开"] < 1) & jin.between(6, 9.5),
        "M3 一字转强(末≥9.5×今7~8.5)": (E["末板开"] >= 9.5) & jin.between(7, 8.5),
        "M4 强开续强(末7~9.5×今6~9.5)": E["末板开"].between(7, 9.5) & jin.between(6, 9.5),
        "M5 冒泡转弱(末3~7×今<3)": E["末板开"].between(3, 7) & (jin < 3),
        "M6 双洗温推(1<0×2<0×今3~7)": (b1 < 0) & (E["b2开盘%"] < 0) & jin.between(3, 7),
        "M7 低开捡尸(1<0×2<0×今<0)": (b1 < 0) & (E["b2开盘%"] < 0) & (jin < 0),
        "M8 温开慢推(末<1×今3~6)": (E["末板开"] < 1) & jin.between(3, 6),
    }


def main() -> None:
    E = load()
    masks = morph_masks(E)
    print(f"池 {len(E)} 笔(N=2 {(E['N'] == 2).sum()} / N=3 {(E['N'] == 3).sum()})\n")
    print("列格式: n笔 E3均/胜率 剔Top3 大亏数;时代列同。\n")

    for name, m in masks.items():
        g = E[m]
        print("=" * 20, name, f" 合计 {len(g)}笔", "=" * 20)
        # 板位 × 阴阳 全因子
        for n in (2, 3):
            for y in ("阳", "阴"):
                sub = g[(g["N"] == n) & (g["阴阳"] == y)]
                if len(sub) < 5:
                    continue
                wk = sub[sub["年"] <= 2022]["E3%"].dropna()
                st = sub[sub["年"] >= 2023]["E3%"].dropna()
                hit = sub["口诀"].value_counts().head(3).to_dict()
                print(f"  {n}接{n + 1}{y}: {stat(sub)}")
                print(f"      弱20-22: {len(wk):3d}笔 {wk.mean():+6.2f}"
                      f"/{(wk > 0).mean() * 100 if len(wk) else 0:3.0f}%  |  "
                      f"强23+: {len(st):3d}笔 {st.mean():+6.2f}"
                      f"/{(st > 0).mean() * 100 if len(st) else 0:3.0f}%  |  现有命中: {hit}")
        print()


if __name__ == "__main__":
    main()
