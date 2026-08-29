# -*- coding: utf-8 -*-
"""V4白名单 → 可直接使用条件句的翻译验证(问财/同花顺近似版回测, 复用U1方法论).

主人需求: 「基本条件 + 白名单条件N」逐层给出可粘贴条件句并量化近似代价.
锚(问财经口径): 最后一次涨停=今日之前最近的涨停日; 顶=涨停当日收盘价(连板日high=close恒等);
  上涨停后最低/最高收盘 = 断板期(不含今日)收盘; 弹回=昨收/最低-1; 近3日新低=低点位置近似.
层1 蹲类(并集): 基本条件 + 昨收较涨停日收盘跌幅>4%(排除新高贴顶) + (弹回>=3% 或 最低收盘不在近3日)(排除阴跌到点)
层1细分: U型蹲=蹲>12%+弹>6%+低点不在近3日; 横盘平台=振幅<=10%+跌幅>12%; L趴底=蹲>12%+弹<3%
层2 首阳: 阳基本 + 跌幅>4% + 最低收盘在近3日 + 弹回<3%
层3 孤板穿插: 4+阴基本 + 近20日涨停次数5~10(大波4+夹板1~2的近似)
层4 2板穿插: 4+阳基本 + 近10日最大连板=2(拆窗表达)
对照: 研究版(w2s_v4_final.py 层1-4)数字.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import add_outcome, build_base

pd.set_option("display.width", 500)


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    g = bars.groupby("sid", sort=False)
    stk = bars["streak"].astype(float)
    bars["mx10"] = stk.groupby(bars["sid"], sort=False).transform(
        lambda s: s.shift(1).rolling(10, min_periods=1).max())
    zt = bars["is_lim"].astype(bool)
    bars["cnt20"] = zt.groupby(bars["sid"], sort=False).transform(
        lambda s: s.shift(1).fillna(False).astype(int).rolling(20, min_periods=1).sum())
    bars["n1_lim"] = g["is_lim"].shift(-1).fillna(False).astype(bool)
    bars["n1_close"] = g["close_price"].shift(-1)
    bars["n1_open"] = g["open_price"].shift(-1)
    # 均线排列态(D-1口径, 融合五层定稿用; 均线是问财原生字段=精确条件非近似)
    for n in (5, 10, 20, 30):
        bars[f"ma{n}"] = g["close_price"].transform(
            lambda s, n=n: s.rolling(n, min_periods=n).mean().shift(1))
    ok = bars[["ma5", "ma10", "ma20", "ma30"]].notna().all(axis=1)
    bars["ma_st"] = ""
    bars.loc[ok, "ma_st"] = (
        np.where(bars.loc[ok, "ma5"] > bars.loc[ok, "ma10"], "+", "-")
        + np.where(bars.loc[ok, "ma10"] > bars.loc[ok, "ma20"], "+", "-")
        + np.where(bars.loc[ok, "ma20"] > bars.loc[ok, "ma30"], "+", "-"))

    # 基本条件(四组, 20日窗定稿+~prev_lim)
    bars["cA"] = ((bars["mx20"] == 2) & bars["p_yin"] & (bars["p_chg"] > -0.09)
                  & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["cB"] = ((bars["mx20"] == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                  & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["cC"] = ((bars["mx20"] >= 4) & bars["p_yin"] & (bars["p_chg"] > -0.08)
                  & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["cD"] = ((bars["mx20"] >= 4) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                  & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)

    # 执行列
    bars["lim_px"] = np.round(bars["prev_close"] * 1.10 + 1e-9, 2)
    bars["touch"] = bars["high_price"] >= bars["lim_px"] - 1e-6
    bars["d0_open_lim"] = bars["open_price"] >= bars["lim_px"] - 1e-6
    cond_ok = bars["touch"] & ~bars["d0_open_lim"] & bars["n1_close"].notna() & bars["n1_open"].notna()

    cl_by = {sid: grp["close_price"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}
    zt_by = {sid: grp.to_numpy() for sid, grp in zt.groupby(bars["sid"], sort=False)}
    p2i = {sid: {int(p): i for i, p in enumerate(grp["pos"])}
           for sid, grp in bars.groupby("sid", sort=False)}
    idx = p2i
    closes_all = cl_by
    pcs_all = {sid: grp["prev_close"].to_numpy() for sid, grp in bars.groupby("sid", sort=False)}

    def banhold(sid, pos0):
        bd_p, bd_c = idx.get(sid), closes_all.get(sid)
        if bd_p is None:
            return np.nan
        for d in range(1, 21):
            j = bd_p.get(pos0 + d)
            if j is None:
                k = bd_p.get(pos0 + d - 1)
                return bd_c[k] if k is not None else np.nan
            lim = round(pcs_all[sid][j] * 1.10 + 1e-9, 2)
            if abs(bd_c[j] - lim) > 1e-6:
                return bd_c[j]
        return bd_c[bd_p.get(pos0 + 20, len(bd_c) - 1)]

    def backtest(sel_idx, label):
        tg = bars.loc[sel_idx].copy()
        if not len(tg):
            print(f"  {label}: n=0")
            return
        tg["r_d1c"] = tg["n1_close"] / tg["lim_px"] - 1
        tg["res"] = np.where(~tg["is_lim"], "炸板",
                             np.where(tg["r_d1c"] < 0, np.where(tg["n1_lim"], "连板", "封D1负"),
                                      np.where(tg["n1_lim"], "连板", "封D1正")))
        tg["bad"] = tg["res"].isin(["炸板", "封D1负"])
        tg["r_bh"] = [banhold(int(s), int(p)) / lp - 1
                      for s, p, lp in zip(tg["sid"], tg["pos"], tg["lim_px"])]
        yr = " / ".join(f"{sy['r_bh'].mean() * 100:+.2f}" for yy in (2023, 2024, 2025, 2026)
                        if len(sy := tg[tg["trade_date"].dt.year == yy]))
        print(f"  {label}: n={len(tg)} 板留均 {tg['r_bh'].mean() * 100:+.2f} "
              f"中位 {tg['r_bh'].median() * 100:+.2f} 胜率 {(tg['r_bh'] > 0).mean() * 100:.0f}% "
              f"差票 {tg['bad'].mean() * 100:.0f}% 连板 {(tg['res'] == '连板').mean() * 100:.0f}% | 分年 {yr}")

    def qiwen_pick(r, mode):
        """问财经近似: 返回 True/False. 锚=今日之前最后一次涨停日j; seg=涨停后..昨日收盘."""
        sid = int(r.sid)
        i = p2i[sid][int(r.pos)]
        y = i - 1
        closes, zt_arr = cl_by[sid], zt_by[sid]
        j = y
        while j >= 0 and not zt_arr[j]:
            j -= 1
        if j < 0:
            return False
        seg_c = closes[j + 1:y + 1]
        if not len(seg_c):
            return False
        top = closes[j]                       # 涨停当日收盘价=顶(数学恒等)
        low_c, pc_ = seg_c.min(), closes[y]
        pull = pc_ / top - 1
        reb = pc_ / low_c - 1
        amp = seg_c.max() / low_c - 1
        near3_low = seg_c[-3:].min() <= low_c if len(seg_c) >= 3 else True
        n2 = i - j
        if not (2 <= n2 <= 20):
            return False
        if mode == "L1":                      # 蹲类并集: 排除贴顶+排阴跌+弹回≤16%(五层版含坑宽)
            return (pull <= -0.04 and reb <= 0.16 and (reb >= 0.03 or not near3_low)
                    and 6 <= n2 <= 15)
        if mode == "L1S":                     # U坑清晰版(主人定调: 无"或", 单句): 已弹起>3%替"或"表达
            return pull <= -0.04 and 0.03 <= reb <= 0.16 and 6 <= n2 <= 15
        if mode == "L1S2":                    # 清晰版2: "低点已过去"单句(近5日最低>全程最低)
            return (pull <= -0.04 and reb <= 0.16 and 6 <= n2 <= 15
                    and len(seg_c) >= 5 and seg_c[-5:].min() > low_c)
        if mode == "L1T":                     # 蹲类纠缠态(层②'): L1去坑宽 + 均线纠缠(精确)
            return (pull <= -0.04 and reb <= 0.16 and (reb >= 0.03 or not near3_low)
                    and r.ma_st in ("-++", "+--"))
        if mode == "L1TS":                    # 纠缠态清晰版: 弹回>3%单句
            return (pull <= -0.04 and 0.03 <= reb <= 0.16
                    and r.ma_st in ("-++", "+--"))
        if mode == "L1U":                     # U型蹲细分(弹6~16%)
            return (low_c / top - 1 <= -0.12) and 0.06 <= reb <= 0.16 and not near3_low
        if mode == "L1F":                     # 横盘平台细分(五层版含坑宽)
            return amp <= 0.10 and pull <= -0.12 and 6 <= n2 <= 15
        if mode == "L1L":                     # L趴底细分
            return (low_c / top - 1 <= -0.12) and (reb < 0.03)
        if mode == "L2":                      # 阴跌到点(首阳)
            return pull <= -0.04 and near3_low and reb < 0.03
        return False

    print("=" * 96)
    print("① 层①: 2板补涨阴基本 + 蹲类白名单五层版(含坑宽6-15; 研究版层① 211笔+3.00)")
    base_a = bars[bars["cA"] & cond_ok]
    for mode, lab in (("L1", "基本+蹲类并集+坑宽6-15(距最后涨停6~15天)"),
                      ("L1S", "U坑清晰版·无或(距顶>4%+弹3~16%+坑宽6-15)"),
                      ("L1S2", "清晰版2·低点已过(距顶>4%+近5日未创新低+弹≤16%+坑宽6-15)"),
                      ("L1U", "基本+U型蹲(蹲>12%+弹>6%+低点不在近3日)"),
                      ("L1L", "基本+L趴底(蹲>12%+弹<3%)")):
        keep = [r.Index for r in base_a.itertuples() if qiwen_pick(r, mode)]
        backtest(keep, lab)

    print("\n①' 层②': 2板补涨阳基本 + 蹲类×均线纠缠态(研究版 118笔+2.96)")
    base_b0 = bars[bars["cB"] & cond_ok]
    for mode, lab in (("L1T", "基本+蹲类+纠缠态(含或表达)"),
                      ("L1TS", "纠缠态清晰版·无或(距顶>4%+弹3~16%+纠缠)")):
        keep = [r.Index for r in base_b0.itertuples() if qiwen_pick(r, mode)]
        backtest(keep, lab)

    print("\n② 层2: 2板补涨阳基本条件 + 阴跌到点首阳(研究版127笔+1.55)")
    base_b = bars[bars["cB"] & cond_ok]
    keep = [r.Index for r in base_b.itertuples() if qiwen_pick(r, "L2")]
    backtest(keep, "基本+首阳(跌幅>4%+最低在近3日+弹<3%)")

    print("\n③ 层3: 4+补涨阴基本条件 + 孤立板穿插(研究版111笔+1.55)")
    base_c = bars[bars["cC"] & cond_ok]
    for lab, m in (("基本+近20日涨停次数5~10", bars["cnt20"].between(5, 10)),
                   ("基本+涨停次数5~8", bars["cnt20"].between(5, 8))):
        keep = base_c[m.reindex(base_c.index).fillna(False)]
        backtest(keep.index, lab)
    # 锚版: 最后一次涨停为孤立板(前日未涨停)且其前有>=4连波 → 近似「大波后有夹板」
    def iso_pick(r, need_dip=False):
        sid = int(r.sid)
        i = p2i[sid][int(r.pos)]
        arr = zt_by[sid]
        j = i - 1
        while j >= 0 and not arr[j]:
            j -= 1
        if j < 0:
            return False
        if not (j == 0 or not arr[j - 1]):      # 最后涨停须是孤立板(前日未涨停)
            return False
        if need_dip:                            # 蹲过: 涨停后最低收盘距涨停日收盘>4%
            seg_c = cl_by[sid][j + 1:i]
            return len(seg_c) > 0 and seg_c.min() / cl_by[sid][j] - 1 <= -0.04
        return True
    keep = [r.Index for r in base_c.itertuples() if iso_pick(r)]
    backtest(keep, "基本+最后一次涨停为孤立板")
    keep = [r.Index for r in base_c.itertuples() if iso_pick(r) and r.ma_st == "+++"]
    backtest(keep, "基本+孤立板+全多头(5>10>20>30日线)")
    keep = [r.Index for r in base_c.itertuples()
            if iso_pick(r, need_dip=True) and r.ma_st == "+++"]
    backtest(keep, "基本+孤立板+全多头+蹲过(涨停后最低收盘较涨停日收盘跌超4%)")
    m_plus = (bars["ma_st"] == "+++").reindex(base_c.index).fillna(False)
    backtest(base_c[m_plus].index, "对照·基本+全多头(无孤立板锚)")
    keep2 = [r.Index for r in base_c.itertuples() if iso_pick(r) and r.ma_st != "+++"]
    backtest(keep2, "对照·孤立板锚无全多头")

    print("\n④ 层4: 4+补涨阳基本条件 + 2板小波穿插(研究版45笔+2.45)")
    base_d = bars[bars["cD"] & cond_ok]
    m = (bars["mx10"] == 2).reindex(base_d.index).fillna(False)
    backtest(base_d[m].index, "基本+近10日最大连板=2")
    m2 = ((bars["mx10"] == 2) & (bars["cnt20"] >= 6)).reindex(base_d.index).fillna(False)
    backtest(base_d[m2].index, "基本+近10日最大连板=2+涨停次数>=6")


if __name__ == "__main__":
    main()
