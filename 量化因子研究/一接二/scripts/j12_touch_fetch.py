# -*- coding: utf-8 -*-
"""一接二 · 触板时间回补(通达信15mK, 宿主机跑)——首刻过滤判别力验证。

只拉 G1(阴×今开7.5~9.5) ∪ S1(阳×前10<-3×今开7.5~8.5) 命中票的买入日。
首触时间=第一根 high>=涨停价 的15mK周期结束时点(09:45=9:30~9:45那根, 与hpr口径一致)。
15mK存档深度约2024-08-15起。输出: ../触板时间-G1S1.csv (断点续跑), 并打印判别力统计。
"""
import os
import socket
import time

import numpy as np
import pandas as pd

socket.setdefaulttimeout(8)
from pytdx.hq import TdxHq_API

HOSTS = [("117.34.114.14", 7709), ("117.34.114.15", 7709), ("117.34.114.16", 7709),
         ("117.34.114.17", 7709), ("117.34.114.18", 7709), ("117.34.114.20", 7709)]
ROOT = "/root/project/ai/vnpy/量化因子研究/一接二"
CSV_IN = f"{ROOT}/全量明细.csv"
CSV_OUT = f"{ROOT}/触板时间-G1S1.csv"
ARCHIVE_START = "2024-08-15"


class Tdx:
    def __init__(self):
        self.api = None
        self.hi = 0
        self.connect()

    def connect(self):
        for _ in range(len(HOSTS)):
            ip, port = HOSTS[self.hi % len(HOSTS)]
            self.hi += 1
            api = TdxHq_API()
            try:
                if api.connect(ip, port, time_out=8):
                    self.api = api
                    return
            except Exception:
                continue
        raise RuntimeError("无可用通达信节点")

    def bars(self, cat, mkt, code, start, count, retry=3):
        for _ in range(retry):
            try:
                r = self.api.get_security_bars(cat, mkt, code, start, count)
                if r is not None:
                    return r
            except Exception:
                pass
            try:
                self.api.disconnect()
            except Exception:
                pass
            self.connect()
        return None


def main():
    E = pd.read_csv(CSV_IN, dtype={"代码": str})
    E["年"] = E["年"].astype(str)
    g1 = (E["地基阴阳"] == "阴") & E["买入开盘%"].between(7.5, 9.5, inclusive="left")
    s1 = ((E["地基阴阳"] == "阳") & (E["前10日涨幅%"] < -3)
          & E["买入开盘%"].between(7.5, 8.5, inclusive="left"))
    ev = E[(g1 | s1) & ~E["未完"] & (E["买入日"] >= ARCHIVE_START)].copy()
    ev["口诀"] = np.where(g1[g1.index.intersection(ev.index)], "G1", "")
    # 重新标记(索引对齐简化)
    ev["口诀"] = [
        "G1" if (r["地基阴阳"] == "阴") else "S1" for _, r in ev.iterrows()]

    done = set()
    if os.path.exists(CSV_OUT):
        old = pd.read_csv(CSV_OUT, dtype={"代码": str})
        done = set(zip(old["代码"], old["买入日"].astype(str)))
        print(f"断点: 已有 {len(done)} 笔")
    tdx = Tdx()
    daily_cache = {}
    rows = []
    t0 = time.time()
    todo = ev[~ev.apply(lambda r: (r["代码"], str(r["买入日"])) in done, axis=1)]
    print(f"需拉 {len(todo)} 笔(共 {len(ev)} 笔命中)")
    for n, (_, r) in enumerate(todo.iterrows()):
        code, day = r["代码"], str(r["买入日"])[:10]
        mkt = 0 if code.endswith(".SZSE") else 1
        c6 = code.split(".")[0]
        try:
            if code not in daily_cache:
                daily_cache[code] = tdx.bars(4, mkt, c6, 0, 800) or []
            daily = daily_cache[code]
            ki = next((i for i, b in enumerate(daily) if b["datetime"][:10] == day), None)
            if ki is None:
                continue
            back = (len(daily) - 1) - ki
            chunk = tdx.bars(1, mkt, c6, max(0, back * 16 - 16), 48) or []
            mb = sorted([b for b in chunk if b["datetime"][:10] == day],
                        key=lambda b: b["datetime"])
            if not mb:
                continue
            lim = float(r["买价"])
            his = np.array([b["high"] for b in mb])
            at = his >= lim - 1e-6
            if not at.any():
                rows.append({"代码": code, "买入日": day, "口诀": r["口诀"], "首触": "未触板",
                             "E3%": r["E3%"], "年": r["年"], "封住": r["封住"]})
                continue
            first = int(np.argmax(at))
            rows.append({"代码": code, "买入日": day, "口诀": r["口诀"],
                         "首触": mb[first]["datetime"][11:16], "E3%": r["E3%"],
                         "年": r["年"], "封住": r["封住"]})
        except Exception as e:
            print(f"异常 {code} {day}: {e}")
            time.sleep(2)
        if n % 40 == 0:
            el = time.time() - t0
            print(f"  {n}/{len(todo)} 已拉 ({el:.0f}s)", flush=True)
            pd.DataFrame(rows).to_csv(CSV_OUT, index=False, encoding="utf-8-sig")
    pd.DataFrame(rows).to_csv(CSV_OUT, index=False, encoding="utf-8-sig")
    print(f"完成, 共 {len(rows)} 笔新拉")

    # ── 判别力统计 ──
    T = pd.read_csv(CSV_OUT, dtype={"代码": str})
    T = T[T["首触"] != "未触板"].copy()

    def bucket(t):
        if t <= "09:45":
            return "①9:45首刻"
        if t <= "10:30":
            return "②9:45~10:30"
        if t <= "14:00":
            return "③10:30~14:00"
        return "④14:00后"

    T["时段"] = T["首触"].map(bucket)
    print("\n=== 首触时段 × 成绩(全部口径) ===")
    for tag, sub in T.groupby("时段"):
        s = sub[sub["口诀"] == "G1"]
        print(f"{tag}: G1 {len(s)}笔 胜{(s['E3%'] > 0).mean() * 100:.0f}% 均{s['E3%'].mean():+.2f}"
              + (f" ｜ S1 {len(sub) - len(s)}笔" if len(sub) > len(s) else ""))
    s1s = T[T["口诀"] == "S1"]
    if len(s1s):
        print(f"S1单独: {len(s1s)}笔 胜{(s1s['E3%'] > 0).mean() * 100:.0f}% 均{s1s['E3%'].mean():+.2f}")
    G = T[T["口诀"] == "G1"]
    print(f"\nG1首刻过滤版(≤9:45): {len(G[G['时段'] == '①9:45首刻'])}笔 "
          f"均{G[G['时段'] == '①9:45首刻']['E3%'].mean():+.2f} vs 全部 {len(G)}笔 均{G['E3%'].mean():+.2f}")


if __name__ == "__main__":
    main()
