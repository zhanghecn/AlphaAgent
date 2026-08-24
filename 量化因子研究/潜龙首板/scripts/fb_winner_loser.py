"""好票 vs 差票 对比挖掘: 什么条件砍得掉负票又不伤好票.

问题(用户 2026-08-24): 在 v6 产品事件集(5,143笔)内,
  好票 W = 连板(streak>=2) 或 D+1 溢价 >= +5%
  差票 L = 炸板(当日未封住) 且 D+1 < 0
逐特征(T-1 涨幅/振幅/量比/换手/乖离/区间位置/价格/市值/竞价高开/...)
对比 W 与 L 的分布, 再扫描单条件切点:
  找出「差票杀伤率高、好票误伤率低、训练/验证双段同向」的过滤候选.

口径 = 产品 build_events()(单一口径来源, 不复制管线; D+1 溢价 = 次日开盘/进场-1).
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/app")
from alphaagent.server.services.qianlong.backtest import build_events  # noqa: E402

W_D1_MIN = 0.05  # 好票 D+1 溢价阈值(用户口径"高收益"取涨停半档 +5%)

# 特征: (列名, 展示名, 分箱边)
FEATURES = [
    ("change_pct_tm1", "T-1涨幅%", [-99, -5, -2, 0, 2, 5, 8, 99]),
    ("amp_tm1", "T-1振幅", [0, 0.02, 0.04, 0.06, 0.09, 0.13, 9]),
    ("vol_ratio_tm1", "T-1量比", [0, 0.6, 0.9, 1.2, 1.8, 3.0, 99]),
    ("turnover_rate_tm1", "T-1换手%", [0, 1, 2, 3, 5, 8, 12, 99]),
    ("ret5_tm1", "近5日涨幅", [-9, -0.05, -0.02, 0, 0.03, 0.08, 0.15, 9]),
    ("ret10_tm1", "近10日涨幅", [-9, -0.05, 0, 0.05, 0.10, 0.15, 9]),
    ("yang10_tm1", "近10日阳线", [-1, 2.5, 4.5, 6.5, 8.5, 11]),
    ("trend_days_tm1", "多头天数", [-1, 0.5, 3.5, 6.5, 10.5]),
    ("dist_ma20", "乖离MA20", [-9, -0.05, -0.02, 0, 0.03, 0.06, 0.10, 9]),
    ("pos60_tm1", "60日位置", [-1, 0.2, 0.4, 0.6, 0.8, 2]),
    ("close_price_tm1", "价格元", [0, 3, 5, 8, 12, 20, 50, 9999]),
    ("cap_yi", "市值亿", [0, 20, 35, 50, 100, 300, 800, 99999]),
    ("gap_open", "竞价高开", [-9, -0.02, 0, 0.02, 0.04, 0.06, 0.08]),
    ("vol_ratio", "T日量比(前视)", [0, 0.5, 0.7, 0.9, 1.1, 1.3, 1.5]),
]
PCT_FEATURES = {"change_pct_tm1"}  # 已是百分数单位, 其余小数特征打印时 ×100


def _fmt_val(col: str, v: float) -> str:
    if col in PCT_FEATURES or col in ("cap_yi", "close_price_tm1", "yang10_tm1",
                                      "trend_days_tm1", "turnover_rate_tm1"):
        return f"{v:.0f}"
    if col in ("vol_ratio_tm1", "vol_ratio"):
        return f"{v:.1f}"
    return f"{v * 100:.0f}"


def _row_stats(df: pd.DataFrame) -> tuple[int, float, float, float, float]:
    """n, 好票率%, 差票率%, 均收%, 胜率%. 小样本也显示均值(主人规则)."""
    n = len(df)
    if n == 0:
        return 0, np.nan, np.nan, np.nan, np.nan
    return (n, round(float(df["W"].mean()) * 100, 1),
            round(float(df["L"].mean()) * 100, 1),
            round(float(df["ret"].mean()) * 100, 2),
            round(float((df["ret"] > 0).mean()) * 100, 1))


def main() -> None:
    pd.set_option("display.width", 200)
    ev = build_events()
    ev["d1_ret"] = ev["open_p1"] / ev["entry"] - 1
    n_d1_nan = int(ev["d1_ret"].isna().sum())
    ev["W"] = (ev["streak_k"] >= 2) | (ev["d1_ret"] >= W_D1_MIN)
    ev["L"] = (~ev["sealed"]) & (ev["d1_ret"] < 0)
    ev["M"] = ~ev["W"] & ~ev["L"]

    print("=" * 96)
    print(f"事件总数 {len(ev)}  (D+1 缺失 {n_d1_nan} 笔, 只影响 D+1 判定不影响连板判定)")
    print(f"好票 W = 连板 或 D+1>=+{W_D1_MIN * 100:.0f}%   "
          f"差票 L = 炸板且D+1<0   中间 M = 其余")
    print("=" * 96)

    # ── 第一部分: 三群体画像 ──
    print("\n[1] 三群体画像 (n / 占比% / 均收% / 中位% / 胜率% / 封板率% / 连板率% / D+1均%)")
    for label, mask in [("W 好票(连板/D+1高)", ev["W"]), ("L 差票(炸板D+1负)", ev["L"]),
                        ("M 中间", ev["M"]),
                        ("M-封板但D+1<0", ev["M"] & ev["sealed"] & (ev["d1_ret"] < 0)),
                        ("M-炸板但D+1>=0", ev["M"] & ~ev["sealed"])]:
        for seg_name, seg_mask in [("全期", mask), ("训练", mask & ev.is_train),
                                   ("验证", mask & ~ev.is_train)]:
            seg = ev[seg_mask]
            n = len(seg)
            if n == 0:
                print(f"{label:<22}{seg_name:<6}{0:>6}")
                continue
            base = ev.is_train.sum() if seg_name == "训练" else (
                (~ev.is_train).sum() if seg_name == "验证" else len(ev))
            print(f"{label:<22}{seg_name:<6}{n:>6}{n / base * 100:>7.1f}"
                  f"{seg.ret.mean() * 100:>8.2f}{seg.ret.median() * 100:>7.2f}"
                  f"{(seg.ret > 0).mean() * 100:>7.1f}{seg.sealed.mean() * 100:>7.1f}"
                  f"{(seg.streak_k >= 2).mean() * 100:>7.1f}{seg.d1_ret.mean() * 100:>8.2f}")

    # ── 第二部分: 特征分箱对照 ──
    print(f"\n[2] 特征分箱: 好票率W% vs 差票率L% "
          f"(基线 W={ev['W'].mean() * 100:.1f}% L={ev['L'].mean() * 100:.1f}%)")
    for col, label, edges in FEATURES:
        binned = pd.cut(ev[col], edges)
        print(f"\n--- {label} ({col}) ---")
        print(f"{'区间':<16}{'n':>6}{'W%':>7}{'L%':>7}{'均收':>8}{'胜率':>7}"
              f"{'| 验n':>7}{'验W%':>7}{'验L%':>7}{'验均收':>8}")
        for iv, gdf in ev.groupby(binned, observed=True):
            v = gdf[~gdf.is_train]
            n, w, l, avg, win = _row_stats(gdf)
            vn, vw, vl, vavg, _ = _row_stats(v)
            rng = f"({_fmt_val(col, iv.left)},{_fmt_val(col, iv.right)}]"
            print(f"{rng:<16}{n:>6}{w:>7.1f}{l:>7.1f}{avg:>8.2f}{win:>7.1f}"
                  f"{vn:>7}{vw:>7.1f}{vl:>7.1f}{vavg:>8.2f}")

    # ── 第2.5部分: W vs L 分离度(AUC)排名 ──
    print("\n[2b] 特征分离度排名: AUC(好票W vs 差票L, 0.5=无区分; >0.5=高值偏好票)")
    auc_rows = []
    wl = ev[ev["W"] | ev["L"]]
    wl_v = wl[~wl.is_train]
    for col, label, _ in FEATURES:
        for seg_name, seg in [("全期", wl), ("验证", wl_v)]:
            w_vals = seg.loc[seg["W"], col].dropna()
            l_vals = seg.loc[seg["L"], col].dropna()
            if len(w_vals) < 10 or len(l_vals) < 10:
                continue
            ranks = pd.concat([w_vals, l_vals]).rank()
            auc = (ranks.iloc[:len(w_vals)].sum() - len(w_vals) * (len(w_vals) + 1) / 2) \
                / (len(w_vals) * len(l_vals))
            auc_rows.append({"特征": label, "段": seg_name, "AUC": round(float(auc), 3)})
    auc_df = pd.DataFrame(auc_rows).pivot(index="特征", columns="段", values="AUC")
    auc_df["分离度"] = (auc_df["全期"] - 0.5).abs().round(3)
    print(auc_df.sort_values("分离度", ascending=False).to_string())

    # ── 第三部分: 单条件切点扫描 ──
    print("\n[3] 单条件切点扫描: 移除规则 = 特征<=c 或 >=c")
    print("    留选标准: 差票杀伤>=3%; 按 杀伤%-误伤% 排序")
    print("    (注: 全池各特征带均收均为正, 不存在负期望带——'优化'的含义是剔除")
    print("     差票密集且显著稀释(<+1.0%)的带, 而非剔除负期望带)")
    ev_v = ev[~ev.is_train]
    total_w, total_l = ev["W"].sum(), ev["L"].sum()
    total_w_v, total_l_v = ev_v["W"].sum(), ev_v["L"].sum()
    rows = []
    for col, label, edges in FEATURES:
        for cut in sorted(set(float(x) for x in edges[1:-1])):
            for op, mask in [("<=", ev[col] <= cut), (">=", ev[col] >= cut)]:
                mask = mask.fillna(False)
                rm = ev[mask]
                if len(rm) < 30:
                    continue
                rm_v = rm[~rm.is_train]
                kill = rm["L"].sum() / total_l * 100
                coll = rm["W"].sum() / total_w * 100
                avg_all = rm.ret.mean() * 100
                if kill < 3:
                    continue
                remain = ev[~mask]
                rows.append({
                    "规则": f"{label}{op}{_fmt_val(col, cut)}", "col": col,
                    "op": op, "cut": cut,
                    "移除n": len(rm), "移除均收": round(avg_all, 2),
                    "杀伤%": round(kill, 1), "误伤%": round(coll, 1),
                    "剩均收": round(remain.ret.mean() * 100, 2),
                    "验移除n": len(rm_v),
                    "验移除均收": round(rm_v.ret.mean() * 100, 2) if len(rm_v) else np.nan,
                    "验杀伤%": round(rm_v["L"].sum() / total_l_v * 100, 1) if len(rm_v) else np.nan,
                    "验误伤%": round(rm_v["W"].sum() / total_w_v * 100, 1) if len(rm_v) else np.nan,
                    "score": kill - coll,
                })
    scan = pd.DataFrame(rows)
    if not len(scan):
        print("(无任何规则通过留选标准)")
        return
    scan = scan.sort_values("score", ascending=False)
    show_cols = ["规则", "移除n", "移除均收", "杀伤%", "误伤%", "剩均收",
                 "验移除n", "验移除均收", "验杀伤%", "验误伤%"]
    print(scan.head(30)[show_cols].to_string(index=False))

    # ── 第四部分: 干净规则组合(并集移除) ──
    print("\n[4] 组合候选: 误伤<=3% 且 移除组显著稀释(全期与验证均收均<=+1.0%) 的规则取并集")
    clean = scan[(scan["误伤%"] <= 3) & (scan["验误伤%"] <= 5)
                 & (scan["移除均收"] <= 1.0)
                 & (scan["验移除均收"].fillna(1.0) <= 1.0)]
    print("干净规则池:")
    print(clean[show_cols].to_string(index=False) if len(clean) else "(无)")
    mask_any = pd.Series(False, index=ev.index)
    picked = []
    for _, r in clean.iterrows():
        feature_col = str(r["col"])
        cut = float(r["cut"])
        m = (ev[feature_col] <= cut) if r["op"] == "<=" else (ev[feature_col] >= cut)
        mask_any |= m.fillna(False)
        picked.append(str(r["规则"]))
    if picked:
        rm = ev[mask_any]
        keep = ev[~mask_any]
        rm_v = rm[~rm.is_train]
        print(f"\n组合规则: {' ∪ '.join(picked)}")
        for name, sub in [("移除组", rm), ("保留组", keep)]:
            v = sub[~sub.is_train]
            pos_m = (sub.groupby(sub.trade_date.dt.to_period("M")).ret.mean() > 0).mean() * 100
            print(f"{name}: n={len(sub)} 均收{sub.ret.mean() * 100:+.2f} "
                  f"胜率{(sub.ret > 0).mean() * 100:.1f} 正月率{pos_m:.0f}% | "
                  f"验证 n={len(v)} 均收{v.ret.mean() * 100:+.2f} "
                  f"胜率{(v.ret > 0).mean() * 100:.1f}")
        print(f"差票总杀伤 {rm['L'].sum() / total_l * 100:.1f}%  "
              f"好票总误伤 {rm['W'].sum() / total_w * 100:.1f}%  |  "
              f"验证段 杀伤{rm_v['L'].sum() / total_l_v * 100:.1f}%  "
              f"误伤{rm_v['W'].sum() / total_w_v * 100:.1f}%")

    # ── 第五部分: 双特征交叉(AND)网格 ──
    print("\n[5] 双特征交叉: 移除 = 条件1 且 条件2 (找单条件挖不动的毒带)")
    grid_feats = [
        ("gap_open", "竞价高开", "<=", [0, 0.02]),
        ("change_pct_tm1", "T-1涨幅%", "<=", [-2, 0]),
        ("dist_ma20", "乖离MA20", "<=", [-0.05, -0.02]),
        ("ret5_tm1", "近5日涨幅", "<=", [-0.05, -0.02]),
        ("trend_days_tm1", "多头天数", "<=", [0.5]),
        ("vol_ratio_tm1", "T-1量比", "<=", [0.9, 1.2]),
        ("pos60_tm1", "60日位置", "<=", [0.2, 0.4]),
        ("turnover_rate_tm1", "T-1换手%", "<=", [2, 3]),
        ("amp_tm1", "T-1振幅", ">=", [0.06, 0.09]),
    ]
    grid_rows = []
    for i in range(len(grid_feats)):
        for j in range(i + 1, len(grid_feats)):
            c1, l1, op1, cuts1 = grid_feats[i]
            c2, l2, op2, cuts2 = grid_feats[j]
            for k1 in cuts1:
                for k2 in cuts2:
                    m1 = (ev[c1] <= k1) if op1 == "<=" else (ev[c1] >= k1)
                    m2 = (ev[c2] <= k2) if op2 == "<=" else (ev[c2] >= k2)
                    mask = (m1 & m2).fillna(False)
                    rm = ev[mask]
                    if len(rm) < 40:
                        continue
                    kill = rm["L"].sum() / total_l * 100
                    coll = rm["W"].sum() / total_w * 100
                    if kill < 3:
                        continue
                    rm_v = rm[~rm.is_train]
                    grid_rows.append({
                        "规则": f"{l1}{op1}{_fmt_val(c1, k1)} & {l2}{op2}{_fmt_val(c2, k2)}",
                        "移除n": len(rm), "移除均收": round(rm.ret.mean() * 100, 2),
                        "杀伤%": round(kill, 1), "误伤%": round(coll, 1),
                        "剩均收": round(ev[~mask].ret.mean() * 100, 2),
                        "验移除n": len(rm_v),
                        "验移除均收": round(rm_v.ret.mean() * 100, 2) if len(rm_v) else np.nan,
                        "验误伤%": round(rm_v["W"].sum() / total_w_v * 100, 1) if len(rm_v) else np.nan,
                        "score": kill - coll,
                    })
    grid = pd.DataFrame(grid_rows)
    if len(grid):
        grid = grid.sort_values("score", ascending=False)
        gshow = ["规则", "移除n", "移除均收", "杀伤%", "误伤%", "剩均收",
                 "验移除n", "验移除均收", "验误伤%"]
        print(grid.head(25)[gshow].to_string(index=False))
        clean2 = grid[(grid["误伤%"] <= 4) & (grid["移除均收"] <= 1.2)
                      & (grid["验移除均收"].fillna(1.2) <= 1.2)]
        print("\n双特征干净池(误伤<=4% 且双段稀释):")
        print(clean2[gshow].to_string(index=False) if len(clean2) else "(无)")
    else:
        print("(无)")


if __name__ == "__main__":
    main()
