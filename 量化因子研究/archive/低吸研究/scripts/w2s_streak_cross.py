# -*- coding: utf-8 -*-
"""连板延续交叉分析(本地,读连板延续明细.csv)——单维信号之后的混淆检验+组合画像+2进3接力."""
import sys

import numpy as np
import pandas as pd

CSV = "/root/project/ai/vnpy/量化因子研究/低吸研究/N型补涨打板/连板延续明细.csv"
GNAME = {"yin2": "2板阴", "yang2": "2板阳", "yin4": "4+阴", "yang4": "4+阳"}
EARLY = {"早09:30~10:30", "中10:30~11:30"}  # 上午触板


def load() -> pd.DataFrame:
    df = pd.read_csv(CSV, dtype={"vt_symbol": str, "touch": str})
    df["seal"] = df["h"] >= 1
    df["a1"] = df["h"] >= 2
    df["a2"] = df["h"] >= 3
    return df


def cross(s: pd.DataFrame, d1: str, d2: str, title: str) -> None:
    print(f"\n──── {title} ────")
    rows = []
    for v1 in sorted(x for x in s[d1].dropna().unique()):
        for v2 in sorted(x for x in s[d2].dropna().unique()):
            sub = s[(s[d1] == v1) & (s[d2] == v2)]
            if len(sub) < 5:
                continue
            sealed = sub[sub["seal"]]
            rows.append({
                d1: v1, d2: v2, "n": len(sub),
                "封板%": round(sub["seal"].mean() * 100, 1),
                "D+1板%": round(sub["a1"].mean() * 100, 1),
                "[封]多拿%": round(sealed["a1"].mean() * 100, 1) if len(sealed) else None,
                "均高": round(sub["h"].mean(), 2),
                "4板+%": round((sub["h"] >= 4).mean() * 100, 1),
            })
    if rows:
        print(pd.DataFrame(rows).to_string(index=False))
    else:
        print("  (n<5 全空)")


def main() -> None:
    df = load()
    print(f"n={len(df)}  touch覆盖 {df['touch'].notna().sum()}")

    # ── 1. 缩量桶的混淆检查: vr_d0<0.8 是不是就是"秒板"? ──
    shrink = df[df["vr_d0"] < 0.8]
    print(f"\n[混淆检查] vr_d0<0.8 (n={len(shrink)}) 的首触时间分布:")
    tt = shrink["touch"].fillna("无").value_counts().head(6)
    for k, v in tt.items():
        print(f"  {k}: {v} ({v / len(shrink) * 100:.0f}%)")
    fast = shrink[shrink["touch"] == "09:45"]
    print(f"  其中首触09:45(开盘首刻): {len(fast)}笔 "
          f"D+1板 {fast['a1'].mean() * 100:.1f}% vs 缩量非首刻 "
          f"{shrink[shrink['touch'] != '09:45']['a1'].mean() * 100:.1f}%")

    # ── 2. vr_d0 细分单调性(全样本) ──
    print("\n[vr_d0 细分] 全体(四组并):")
    bins = [0, 0.5, 0.8, 1.5, 3.0, 99]
    lab = ["<0.5", "0.5~0.8", "0.8~1.5", "1.5~3", ">=3"]
    df["vrb"] = pd.cut(df["vr_d0"], bins=bins, labels=lab)
    rows = []
    for b in lab:
        sub = df[df["vrb"] == b]
        if not len(sub):
            continue
        sealed = sub[sub["seal"]]
        rows.append({"量比": b, "n": len(sub),
                     "封板%": round(sub["seal"].mean() * 100, 1),
                     "D+1板%": round(sub["a1"].mean() * 100, 1),
                     "[封]多拿%": round(sealed["a1"].mean() * 100, 1),
                     "均高": round(sub["h"].mean(), 2),
                     "4板+%": round((sub["h"] >= 4).mean() * 100, 1)})
    print(pd.DataFrame(rows).to_string(index=False))

    # ── 3. 每组: 量比×首触段交叉 ──
    for gk, name in GNAME.items():
        sub = df[(df["g4"] == gk) & df["tseg"].notna()].copy()
        sub["量桶"] = np.where(sub["vr_d0"] < 0.8, "缩<0.8",
                       np.where(sub["vr_d0"] < 1.5, "平", "放>=1.5"))
        cross(sub, "量桶", "tseg", f"{name} × D0量比 × 首触段")

    # ── 4. 组合画像: 每组"缩量+上午"vs其余 ──
    print("\n──── 组合画像(缩量<0.8 × 上午触板) ────")
    rows = []
    for gk, name in GNAME.items():
        sub = df[(df["g4"] == gk) & df["tseg"].notna()].copy()
        best = sub[(sub["vr_d0"] < 0.8) & sub["tseg"].isin(EARLY)]
        rest = sub.drop(best.index)
        for tag, x in (("缩量×上午", best), (f"其余(基准)", rest)):
            sealed = x[x["seal"]]
            rows.append({"组": name, "画像": tag, "n": len(x),
                         "封板%": round(x["seal"].mean() * 100, 1) if len(x) else None,
                         "D+1板%": round(x["a1"].mean() * 100, 1) if len(x) else None,
                         "[封]多拿%": round(sealed["a1"].mean() * 100, 1) if len(sealed) else None,
                         "均高": round(x["h"].mean(), 2) if len(x) else None,
                         "4板+%": round((x["h"] >= 4).mean() * 100, 1) if len(x) else None})
    print(pd.DataFrame(rows).to_string(index=False))

    # ── 5. 组合画像2: 趋势位(bias10>5) × 量比 ──
    print("\n──── 组合画像2(bias_ma10>5 × 量比<0.8) ────")
    rows = []
    for gk, name in GNAME.items():
        sub = df[df["g4"] == gk].copy()
        strong = sub["bias10"] == ">5"  # 明细CSV已桶化为 '>5'/...
        best = sub[strong & (sub["vr_d0"] < 0.8)]
        trend = sub[strong & (sub["vr_d0"] >= 0.8)]
        weak = sub[~strong]
        for tag, x in (("强趋势×缩量", best), ("强趋势×常量", trend), ("趋势下方", weak)):
            sealed = x[x["seal"]]
            rows.append({"组": name, "画像": tag, "n": len(x),
                         "封板%": round(x["seal"].mean() * 100, 1) if len(x) else None,
                         "D+1板%": round(x["a1"].mean() * 100, 1) if len(x) else None,
                         "[封]多拿%": round(sealed["a1"].mean() * 100, 1) if len(sealed) else None,
                         "均高": round(x["h"].mean(), 2) if len(x) else None})
    print(pd.DataFrame(rows).to_string(index=False))

    # ── 6. 2进3接力: 已到2板后什么特征还能继续 ──
    print("\n──── 2进3接力率 P(h>=3 | h>=2) ────")
    two = df[df["a1"]]  # 已到2板
    rows = []
    for gk, name in GNAME.items():
        sub = two[two["g4"] == gk]
        if not len(sub):
            continue
        rows.append({"组": name, "n(2板)": len(sub),
                     "2进3%": round(sub["a2"].mean() * 100, 1)})
    print(pd.DataFrame(rows).to_string(index=False))
    # 特征维度(全体2板样本)
    for dim, lab_f, name in [
        ("vr_d0", lambda x: "缩<0.8" if x < 0.8 else ("平0.8~1.5" if x < 1.5 else "放>=1.5"), "D0量比"),
        ("tseg", None, "首触段"),
    ]:
        sub = two[two[dim].notna()].copy() if dim == "tseg" else two.copy()
        key = sub[dim].map(lab_f) if lab_f else sub[dim]
        rows = []
        for b in sorted(x for x in key.dropna().unique()):
            x = sub[key == b]
            rows.append({name: b, "n": len(x), "2进3%": round(x["a2"].mean() * 100, 1),
                         "3板+占全样本%": "--"})
        print(f"  [全体2进3 × {name}]")
        print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
