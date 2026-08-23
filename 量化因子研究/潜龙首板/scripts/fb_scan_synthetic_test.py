"""P4 合成扫描测试:不依赖真实交易日,验证状态机转移.

场景:
A 平开+2%, 10:00 触及触发价 → touched; 10:01 仍 ≥ 触发价 → holding(买入价=现价×1.005)
B 高开 +9% → skipped_gap
C 平开, 触及后下一分钟跌回 → unconfirmed
D 11:31 新触及 → 不产生(超过 11:30 新触发截止)
E 全天未触发 → watching 保留(尾盘 EOD 置 no_trigger)
"""
from __future__ import annotations

import os, sys, json
from datetime import datetime, date
from zoneinfo import ZoneInfo

sys.path.insert(0, "/app")
os.environ.setdefault("DATABASE_URL", "")

from alphaagent.server.services.qianlong import live_scan, contracts, repository  # noqa: E402

SH = ZoneInfo("Asia/Shanghai")
TODAY = date(2026, 8, 24)
PREV = 10.0
TRIG = round(PREV * 1.08 + 1e-9, 4)

pool = [
    {"vt_symbol": "600001.SSE", "name": "A票", "prev_close": PREV, "trigger_price": TRIG,
     "chassis_tag": "AB", "vol_ma5": 1000.0},
    {"vt_symbol": "600002.SSE", "name": "B票", "prev_close": PREV, "trigger_price": TRIG},
    {"vt_symbol": "600003.SSE", "name": "C票", "prev_close": PREV, "trigger_price": TRIG},
    {"vt_symbol": "600004.SSE", "name": "D票", "prev_close": PREV, "trigger_price": TRIG},
    {"vt_symbol": "600005.SSE", "name": "E票", "prev_close": PREV, "trigger_price": TRIG},
    {"vt_symbol": "600006.SSE", "name": "F票", "prev_close": PREV, "trigger_price": TRIG,
     "chassis_tag": "A", "vol_ma5": 5.0},
]

# spot 快照随场景推进变化
SPOT = {}


def fake_spot(force_refresh=False):
    return {"items": SPOT["items"]}


def set_spot(prices: dict[str, float], opens: dict[str, float] | None = None):
    items = []
    for e in pool:
        vt = e["vt_symbol"]
        last = prices.get(vt, PREV * 1.01)
        op = (opens or {}).get(vt, PREV * 1.02)
        items.append({"vt_symbol": vt, "last_price": last, "open_price": op,
                      "volume": 1000.0, "trade_time": f"{TODAY.isoformat()} 10:00:00"})
    # 填充全市场背景行,满足新鲜度门槛
    for i in range(MIN := 3100):
        items.append({"vt_symbol": f"9{i:05d}.SSE", "last_price": 10, "open_price": 10,
                      "volume": 100, "trade_time": f"{TODAY.isoformat()} 10:00:00"})
    SPOT["items"] = items


saved: dict[str, dict] = {}


def fake_upsert(trade_date, vt, **fields):
    row = saved.setdefault(vt, {"trade_date": trade_date, "vt_symbol": vt, "status": "watching"})
    row.update(fields)


live_scan.AkShareAdapter = None  # 占位
import alphaagent.server.services.qianlong.live_scan as ls  # noqa: E402

class _FakeAdapter:
    def all_stock_ohlcv_spot(self, force_refresh=False):
        return fake_spot(force_refresh)

import alphaagent.data_sources.akshare_adapter as ak  # noqa: E402
ak.AkShareAdapter = _FakeAdapter
ls.repository.upsert_signal = fake_upsert
ls.repository.save_scan_run = lambda **kw: None
ls.repository.load_signal_map = lambda d: {vt: dict(r) for vt, r in saved.items()}
ls._scan_lock = __import__("contextlib").nullcontext

out = {}

# T1: 10:00 A/C/D 触及, B 高开 9%
set_spot(
    {"600001.SSE": TRIG + 0.01, "600003.SSE": TRIG + 0.02, "600004.SSE": PREV * 1.01,
     "600006.SSE": TRIG + 0.01},
    opens={"600002.SSE": PREV * 1.09},
)
r = ls._scan_once(TODAY, pool, datetime(2026, 8, 24, 10, 0, tzinfo=SH))
out["T1_1000"] = {"result": r, "status": {vt: saved[vt]["status"] for vt in saved}}
assert saved["600001.SSE"]["status"] == "touched"
assert saved["600002.SSE"]["status"] == "skipped_gap"
assert saved["600003.SSE"]["status"] == "touched"
assert saved["600001.SSE"].get("priority") is True  # 高开2%

# T2: 10:01 A 收住→holding; C 跌回→unconfirmed; D 此刻才触及(允许,10:01<11:30)
set_spot({"600001.SSE": TRIG + 0.03, "600003.SSE": PREV * 1.05, "600004.SSE": TRIG + 0.01,
          "600006.SSE": TRIG + 0.02})
r = ls._scan_once(TODAY, pool, datetime(2026, 8, 24, 10, 1, tzinfo=SH))
out["T2_1001"] = {"result": r, "status": {vt: saved[vt]["status"] for vt in saved}}
a = saved["600001.SSE"]
assert a["status"] == "holding" and abs(a["entry_price"] - (TRIG + 0.03) * 1.005) < 1e-3  # 实现按 4 位小数舍入
assert saved["600003.SSE"]["status"] == "unconfirmed"
assert saved["600006.SSE"]["status"] == "unconfirmed"  # 收住但爆量(量比2.0≥1.0)拒买
assert saved["600004.SSE"]["status"] == "touched"

# T3: 11:31 E 新触及?不允许(>11:30);D 的确认允许(11:31 ≤ 截止)
set_spot({"600001.SSE": TRIG + 0.03, "600004.SSE": TRIG + 0.02, "600005.SSE": TRIG + 0.05})
r = ls._scan_once(TODAY, pool, datetime(2026, 8, 24, 11, 31, tzinfo=SH))
out["T3_1131"] = {"result": r, "status": {vt: saved[vt]["status"] for vt in saved}}
assert saved["600005.SSE"]["status"] == "watching", "11:31 不应产生新触发"
assert saved["600004.SSE"]["status"] == "holding", "11:31 应允许完成确认"

print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
print("SYNTHETIC SCAN STATE MACHINE: ALL ASSERTIONS PASSED")
