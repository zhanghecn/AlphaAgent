# -*- coding: utf-8 -*-
"""高位接力 · 触板时间/炸板次数 全量回补（通达信15mK, 宿主机跑）。

只拉接力事件涉及的(票,日): 买入日 + 前置各板日(首板~买入前一天), 每事件1次日线定位+1次15m拉取。
口径(与w2s一致): 首次触板=第一根 high>=涨停价 的15mK周期结束时点(09:45=09:30~09:45那根);
涨停价=TDX日线昨收×1.10四舍五入(未复权, 与研究口径一致, 逐笔与DB买价对账)。
开口段数: 首次触板后, 低点掉下涨停价0.2%以上再摸回的段数; 一封到底=0。
15mK存档深度约2024-08-15起, 更早事件标「无数据」。
输出: 量化因子研究/高位接力/触板时间明细-全量.csv
断点续跑: 已存在的(代码,买入日)跳过。
"""
import os
import socket
import sys
import time

import numpy as np
import pandas as pd

socket.setdefaulttimeout(8)
from pytdx.hq import TdxHq_API

HOSTS = [("117.34.114.14", 7709), ("117.34.114.15", 7709), ("117.34.114.16", 7709),
         ("117.34.114.17", 7709), ("117.34.114.18", 7709), ("117.34.114.20", 7709),
         ("117.34.114.27", 7709)]
ROOT = "/root/project/ai/vnpy/量化因子研究/高位接力"
CSV_IN = f"{ROOT}/全量明细.csv"
CSV_OUT = f"{ROOT}/触板时间明细-全量.csv"
ARCHIVE_START = "2024-08-15"        # 15mK存档大约从这开始


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


def day_metrics(bars15, limit_px):
    """一天的15m序列 → 触板时间/封板时间/开口段数/最深回落%。"""
    if not bars15:
        return None
    his = np.array([b["high"] for b in bars15])
    los = np.array([b["low"] for b in bars15])
    tts = [b["datetime"][11:16] for b in bars15]
    at = his >= limit_px - 1e-6
    if not at.any():
        return None
    first = int(np.argmax(at))
    last = len(at) - 1 - int(np.argmax(at[::-1]))
    eps = limit_px * 0.002
    seg, in_break = 0, False
    for i in range(first, last + 1):
        if los[i] < limit_px - eps:
            if not in_break:
                seg += 1
                in_break = True
        if at[i]:
            in_break = False
    return {"触板时间": tts[first], "封板时间": tts[last],
            "开口段数": seg, "最深回落%": round(float(los[first:].min() / limit_px - 1) * 100, 2)}


def main():
    E = pd.read_csv(CSV_IN)
    done = set()
    if os.path.exists(CSV_OUT):
        old = pd.read_csv(CSV_OUT, dtype={"代码": str})
        done = set(zip(old["代码"], old["买入日"]))
        print(f"断点: 已有 {len(done)} 笔")
    tdx = Tdx()
    daily_cache = {}
    out_rows = []
    events = E.to_dict("records")
    t0 = time.time()
    for idx, r in enumerate(events):
        code, day = r["代码"], r["买入日"]
        if (code, day) in done:
            continue
        if day < ARCHIVE_START:
            continue
        N = int(r["N"])
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
            # 一次15m拉取: 从买入日往前32根开始取800根, 覆盖买入日+前置各板日(位置口径见w2s)
            start = max(0, back * 16 - 32)
            chunk = tdx.bars(1, mkt, c6, start, 800) or []
            by_date = {}
            for b in chunk:
                by_date.setdefault(b["datetime"][:10], []).append(b)
            # 需要的日期: 首板日~买入日(连续N+1个交易日)
            dates = sorted(d["datetime"][:10] for d in daily if r["首板日"] <= d["datetime"][:10] <= day)
            # 买入日指标
            rec = {"代码": code, "名称": r["名称"], "买入日": day, "组": r["组"],
                   "四组": r["四组"], "阴阳": r["阴阳"], "月": r["月"], "年": str(r["年"])}
            lim_buy = r["买价"]
            mb = by_date.get(day)
            if mb:
                mb.sort(key=lambda b: b["datetime"])
                m = day_metrics(mb, lim_buy)
                if m:
                    rec.update(m)
                    # 对账: TDX日线昨收×1.1 vs DB买价
                    prev = daily[ki - 1]["close"] if ki > 0 else np.nan
                    lim_tdx = round(prev * 1.10 + 1e-9, 2)
                    if abs(lim_tdx - lim_buy) > 0.011:
                        rec["对账异常"] = f"tdx{lim_tdx}≠db{lim_buy}"
            # 前置各板
            for k in range(1, N + 1):
                if k - 1 < len(dates) - 1:
                    bd = dates[k - 1]
                    kb = next((i for i, b in enumerate(daily) if b["datetime"][:10] == bd), None)
                    if kb and kb > 0:
                        lim_k = round(daily[kb - 1]["close"] * 1.10 + 1e-9, 2)
                        mbk = by_date.get(bd)
                        if mbk:
                            mbk.sort(key=lambda b: b["datetime"])
                            mk = day_metrics(mbk, lim_k)
                            if mk:
                                rec[f"b{k}触板时间"] = mk["触板时间"]
                                rec[f"b{k}封板时间"] = mk["封板时间"]
                                rec[f"b{k}开口段数"] = mk["开口段数"]
            out_rows.append(rec)
        except Exception as e:
            print(f"{code} {day} 失败: {str(e)[:60]}")
        if idx % 200 == 0 and idx > 0:
            print(f"进度 {idx}/{len(events)} 已取 {len(out_rows)} 用时{time.time()-t0:.0f}s", flush=True)
            time.sleep(0.2)
    new = pd.DataFrame(out_rows)
    if os.path.exists(CSV_OUT) and done:
        old = pd.read_csv(CSV_OUT, dtype={"代码": str})
        new = pd.concat([old, new], ignore_index=True)
    new.to_csv(CSV_OUT, index=False, encoding="utf-8-sig")
    print(f"完成: 本次新取 {len(out_rows)} 笔, 累计 {len(new)} 笔, 用时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
