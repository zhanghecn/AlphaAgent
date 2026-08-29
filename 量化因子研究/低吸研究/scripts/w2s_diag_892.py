# -*- coding: utf-8 -*-
"""核查 000892 欢瑞世纪 2026-07/08 信号链(主人质疑):
  ① 阴组为何 8-04 才入库, 而不是 7-29 / 7-31?
  ② 8-04 判 U型蹲 是否成立? 主人认为已"创新高"不该是 U.
逐日打印四组条件分量 + 两个触发日的地基判定链 + 上波段结构.
"""
import sys

sys.path.insert(0, "/app")
import numpy as np
import pandas as pd
import w2s_v3_wave_research as w
from w2s_base_type import classify_base

pd.set_option("display.width", 400)

VT = "000892.SZSE"


def main():
    bars, segs, clusters, waves, bounds = w.load_all()
    w._ths_daily(bars)
    bars["c4a"] = ((bars["mx20"] == 2) & bars["p_yin"] & (bars["p_chg"] > -0.09)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)
    bars["c4b"] = ((bars["mx20"] == 2) & bars["p_yang"] & (bars["p_chg"] > -0.03)
                   & (bars["p_ush"] < 0.04) & ~bars["prev_lim"]).fillna(False).astype(bool)

    sid = int(bars.loc[bars["vt_symbol"] == VT, "sid"].iloc[0])
    sub = bars[(bars["sid"] == sid) & (bars["trade_date"] >= "2026-06-20")
               & (bars["trade_date"] <= "2026-08-15")]

    print("=" * 118)
    print(f"== ① {VT} 欢瑞世纪 每日明细 (板=收盘涨停 触=盘中触板 c4a=阴组昨日口径 c4b=阳组昨日口径) ==")
    for r in sub.itertuples():
        chg = r.close_price / r.prev_close - 1
        lim_px = round(r.prev_close * 1.10 + 1e-9, 2)
        print(f"{str(r.trade_date)[:10]} O{r.open_price:6.2f} H{r.high_price:6.2f} "
              f"L{r.low_price:6.2f} C{r.close_price:6.2f} 涨{chg * 100:+6.2f}% "
              f"板价{lim_px:6.2f} {'板' if r.is_lim else '  '}{'触' if r.touch else '  '}"
              f"{'一字' if r.d0_open_lim else '    '} | 昨{'阴' if r.p_yin else '阳' if r.p_yang else '平'}"
              f" 昨幅{r.p_chg * 100:+6.2f}% 上影{r.p_ush * 100:5.2f}% "
              f"昨涨停{'Y' if r.prev_lim else 'N'} streak={r.streak:.0f} mx20={r.mx20:.0f} "
              f"| c4a={int(r.c4a)} c4b={int(r.c4b)}")

    print("\n== ② 该票 2026-05 之后的连板段 (height>=2 为上波段) ==")
    sg = segs[segs["sid"] == sid]
    allb = bars[bars["sid"] == sid]
    dts_all = dict(zip(allb["pos"], allb["trade_date"]))
    for r in sg.itertuples():
        if int(r.last_pos) < (sub["pos"].min() - 45):
            continue
        print(f"  段 first_pos={int(r.first_pos)}({str(dts_all.get(int(r.first_pos), '?'))[:10]}) "
              f"last_pos={int(r.last_pos)}({str(dts_all.get(int(r.last_pos), '?'))[:10]}) "
              f"height={r.height} 段最高={r.high_price:.2f}")

    # ③ 两个触发日的地基判定链
    big = segs[segs["height"] >= 2].sort_values(["sid", "last_pos"])
    arr = big[big["sid"] == sid][["last_pos", "high_price"]].to_numpy()
    cl_all = allb["close_price"].to_numpy()
    for dstr in ("2026-07-29", "2026-08-04"):
        row = sub[sub["trade_date"] == dstr]
        if not len(row):
            continue
        r = row.iloc[0]
        pos0, pc = int(r["pos"]), float(r["prev_close"])
        li = arr[:, 0].searchsorted(pos0, side="left")
        lp, ph = int(arr[li - 1, 0]), float(arr[li - 1, 1])
        mid_c = cl_all[lp + 1: pos0]
        mid_dates = [str(dts_all[p])[:10] for p in range(lp + 1, pos0)]
        info = classify_base(mid_c, ph, pc)
        print(f"\n== ③ {dstr} 触发行地基判定链 ==")
        print(f"  上波末板 lp={lp}({str(dts_all[lp])[:10]}) 段顶 ph={ph:.2f} "
              f"断板期 {mid_dates[0]}~{mid_dates[-1]} 共{len(mid_c)}天 昨收={pc:.2f}")
        print(f"  断板期逐日收盘: " + " ".join(
            f"{d[5:]}:{c:.2f}" for d, c in zip(mid_dates, mid_c)))
        print(f"  pull(昨收/顶-1)={info['pull'] * 100:+.2f}%  low_dd={info['low_dd'] * 100:+.2f}% "
              f"reb={info['reb'] * 100:+.2f}%  pos_low={info['pos_low']:.3f} "
              f"amp={info['amp'] * 100:.1f}%  brk={info['brk']}")
        print(f"  判定链: pull>-4%?{'Y' if info['pull'] > -0.04 else 'N'} → "
              f"amp<=10%?{'Y' if info['amp'] <= 0.10 else 'N'} → "
              f"reb<3%?{'Y' if info['reb'] < 0.03 else 'N'} → "
              f"蹲深<=-12%且弹>=6%?{'Y' if info['low_dd'] <= -0.12 and info['reb'] >= 0.06 else 'N'} → "
              f"pos_low<=0.6?{'Y' if info['pos_low'] <= 0.6 else 'N'} ⇒ {info['base']}")
        print(f"  昨收距顶还有 {info['pull'] * 100:+.1f}% (未破顶), 当日板价 "
              f"{round(pc * 1.10 + 1e-9, 2):.2f} = 顶的 {round(pc * 1.10 + 1e-9, 2) / ph * 100:.1f}%")


if __name__ == "__main__":
    main()
