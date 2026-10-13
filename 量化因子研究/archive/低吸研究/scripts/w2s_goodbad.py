# -*- coding: utf-8 -*-
"""终版四组触发 好票/差票票例库: 按 组×月 分文件归档(供主人逐票复盘归因).

差票 = D0炸板(触板未封) 或 封板但D1收<0(相对涨停价买入); 好票 = 封板且D1收>=0(连板单标).
特征列全部为 D0/D-1 可观测口径 + 市场环境, 供「为什么炸/为什么D1负」人工归因.
输出: /app/w2s_v3_out/好差票验证/<组名>/YYYY-MM.md + _索引.md
"""
import os
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from sqlalchemy import create_engine

pd.set_option("display.width", 320)

bars, segs, clusters, waves, bounds = w.load_all()
w._ths_daily(bars)
g = bars.groupby("sid", sort=False)
bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)

# 缓启背离条件(与主脚本一致) + 断板天数
big = segs[segs["height"] >= 2].sort_values(["sid", "last_pos"])
big_by = {sid: grp.sort_values("last_pos")[["last_pos", "high_price"]].to_numpy()
          for sid, grp in big.groupby("sid", sort=False)}
pull = np.full(len(bars), np.nan)
gap_prev = np.full(len(bars), np.nan)
for i, (s, p, pc) in enumerate(zip(bars["sid"], bars["pos"], bars["prev_close"])):
    arr = big_by.get(s)
    if arr is None or pc != pc:
        continue
    li = arr[:, 0].searchsorted(p, side="left")
    if li == 0:
        continue
    pull[i] = pc / arr[li - 1, 1] - 1
    gap_prev[i] = p - arr[li - 1, 0]
bars["pull_top"] = pull
bars["gap_prev"] = gap_prev
bars["c_dh"] = bars["c_dh"] & (bars["pull_top"] < -0.04)

eng = create_engine(os.environ["DATABASE_URL"])
opens_map = w._open_counts(eng, bars)
bars["opens"] = [opens_map.get((s, p), np.nan) for s, p in zip(bars["sid"], bars["pos"])]
bars["c_rzq"] = (bars["c_rzq_daily"] & (bars["opens"] > 5)).fillna(False).astype(bool)

# 市场环境: 当日/昨日全市场涨停家数
mkt = bars.groupby("trade_date")["is_lim"].sum().rename("mkt_lim").reset_index()
mkt["mkt_prev"] = mkt["mkt_lim"].shift(1)
bars = bars.merge(mkt, on="trade_date", how="left")

cond_ok = bars["touch"] & ~bars["d0_open_lim"] & bars["n1_close"].notna() & bars["n1_open"].notna()
wave_keys = set(zip(waves["sid"], waves["first_pos"]))

out_root = "/app/w2s_v3_out/好差票验证"
os.makedirs(out_root, exist_ok=True)
index_rows = []

bars["c_rm"] = (bars["c_g"] & bars["c_mid"]).fillna(False).astype(bool)   # 雷达+通用条件
for name, c in [("补涨阴", "c_by"), ("补涨阳", "c_by2"), ("双板缓启", "c_dh"), ("弱转强", "c_rzq"), ("雷达试盘", "c_rm")]:
    tg = bars[bars[c] & cond_ok].copy()
    tg["buy"] = tg["lim_px"]
    tg["r_d1o"] = tg["n1_open"] / tg["buy"] - 1
    tg["r_d1c"] = tg["n1_close"] / tg["buy"] - 1
    tg["open_g"] = tg["open_price"] / tg["prev_close"] - 1
    tg["close_g"] = tg["close_price"] / tg["prev_close"] - 1
    tg["ym"] = tg["trade_date"].dt.strftime("%Y-%m")
    tg["date"] = tg["trade_date"].dt.strftime("%Y-%m-%d")
    tg["res"] = np.where(~tg["is_lim"], "炸板",
                         np.where(tg["r_d1c"] < 0, "封D1负", np.where(tg["n1_lim"], "连板", "封D1正")))
    tg["is_wv"] = [(s, p) in wave_keys for s, p in zip(tg["sid"], tg["pos"])]
    tg["yin_yang"] = np.where(tg["p_yin"], "阴", np.where(tg["p_yang"], "阳", "平"))

    gdir = os.path.join(out_root, name)
    os.makedirs(gdir, exist_ok=True)
    for ym, sub in tg.groupby("ym"):
        bad = sub[sub["res"].isin(["炸板", "封D1负"])].sort_values("r_d1c")
        good = sub[sub["res"].isin(["封D1正", "连板"])].sort_values("r_d1c", ascending=False)
        lines = [
            f"# {name} · {ym} · 好/差票验证清单", "",
            f"触发 {len(sub)} 笔 | 差票 {len(bad)}（炸板 {int((sub['res'] == '炸板').sum())} + "
            f"封D1负 {int((sub['res'] == '封D1负').sum())}） | 好票 {len(good)}（连板 "
            f"{int((sub['res'] == '连板').sum())}） | 差票率 {len(bad) / len(sub) * 100:.0f}%",
            "",
            "口径: 买入=触板涨停价; D1开%/D1收% 相对涨停价; 回撤%=昨收距上波顶; 断板=上波末板距D0交易日数;",
            "昨涨停家数=D-1全市场涨停数(情绪环境)。差票按D1收最差在前。",
            "",
            "## 差票",
            "",
            "| 代码 | 名称 | D0 | 结果 | D1开% | D1收% | 开盘% | 收盘% | 昨K | 昨幅% | 昨上影% | 回撤% | 断板 | 昨涨停家 | V3 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for _, r in bad.iterrows():
            lines.append(
                f"| {r['vt_symbol']} | {r['name']} | {r['date']} | {r['res']} "
                f"| {r['r_d1o'] * 100:+.1f} | {r['r_d1c'] * 100:+.1f} "
                f"| {r['open_g'] * 100:+.1f} | {r['close_g'] * 100:+.1f} "
                f"| {r['yin_yang']} | {r['p_chg'] * 100:+.1f} | {(r['p_ush'] if r['p_ush'] == r['p_ush'] else 0) * 100:.1f} "
                f"| {r['pull_top'] * 100:+.1f} | {r['gap_prev']:.0f} | {r['mkt_prev']:.0f} "
                f"| {'✓' if r['is_wv'] else ''} |")
        lines += ["", "## 好票", "",
                  "| 代码 | 名称 | D0 | 结果 | D1开% | D1收% | 开盘% | 收盘% | 昨K | 昨幅% | 昨上影% | 回撤% | 断板 | 昨涨停家 | V3 |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for _, r in good.iterrows():
            lines.append(
                f"| {r['vt_symbol']} | {r['name']} | {r['date']} | {r['res']} "
                f"| {r['r_d1o'] * 100:+.1f} | {r['r_d1c'] * 100:+.1f} "
                f"| {r['open_g'] * 100:+.1f} | {r['close_g'] * 100:+.1f} "
                f"| {r['yin_yang']} | {r['p_chg'] * 100:+.1f} | {(r['p_ush'] if r['p_ush'] == r['p_ush'] else 0) * 100:.1f} "
                f"| {r['pull_top'] * 100:+.1f} | {r['gap_prev']:.0f} | {r['mkt_prev']:.0f} "
                f"| {'✓' if r['is_wv'] else ''} |")
        with open(os.path.join(gdir, f"{ym}.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        index_rows.append({"组": name, "月": ym, "触发": len(sub), "炸板": int((sub['res'] == '炸板').sum()),
                           "封D1负": int((sub['res'] == '封D1负').sum()),
                           "好票": len(good), "连板": int((sub['res'] == '连板').sum()),
                           "差票率%": round(len(bad) / len(sub) * 100)})

idx = pd.DataFrame(index_rows).sort_values(["组", "月"])
idx.to_csv(os.path.join(out_root, "_索引.csv"), index=False, encoding="utf-8-sig")
print(idx.to_string(index=False))
print(f"\n已生成: {out_root}/<组>/YYYY-MM.md + _索引.csv")
print("\n== 组×年 差票率汇总 ==")
idx["年"] = idx["月"].str[:4]
print(idx.groupby(["组", "年"]).apply(
    lambda s: pd.Series({"触发": s["触发"].sum(), "差票率%": round(
        (s["炸板"].sum() + s["封D1负"].sum()) / s["触发"].sum() * 100)}),
    include_groups=False).to_string())
