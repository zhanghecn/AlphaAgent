"""补 7 大指数 2015-01-01 ~ 2024-05-27 历史日线(衔接现有 2024-05-28)。

为大盘择时银手指验证补熊市大顶样本(2015 股灾 / 2018 贸易战 / 2021 抱团顶)。
分批每年取(AkShare eastmoney 源), 复用 data_sync 的 _upsert_daily_bars 写库。

宿主跑:
  set -a; source .env; set +a
  PG_IP=$(docker inspect vnpy-postgres-1 --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
  DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${PG_IP}:5432/${POSTGRES_DB}" \
    uv run python scripts/backfill_index_history.py
"""

from __future__ import annotations

import sys
import time
from datetime import date

from alphaagent.market.providers import AkShareAdapter
from alphaagent.market.symbols import INDEX_SYMBOLS
from alphaagent.server.services.data_sync import _upsert_daily_bars, _upsert_stocks

START = date(2015, 1, 1)
END = date(2024, 5, 27)  # 衔接现有 2024-05-28, 避免重叠


def main() -> int:
    adapter = AkShareAdapter()
    _upsert_stocks(
        [
            {
                "symbol": str(it["symbol"]),
                "exchange": str(it["exchange"]),
                "name": str(it.get("name") or it["symbol"]),
                "source": "index_benchmark",
                "raw": {"instrument_type": "index"},
            }
            for it in INDEX_SYMBOLS
        ]
    )
    grand = 0
    for it in INDEX_SYMBOLS:
        symbol = str(it["symbol"])
        exchange = str(it["exchange"])
        name = str(it.get("name") or symbol)
        t0 = time.time()
        sym_total = 0
        year = START.year
        while year <= END.year:
            s = max(date(year, 1, 1), START)
            e = min(date(year, 12, 31), END)
            try:
                data = adapter.stock_bars(
                    symbol, exchange, interval="1d",
                    start_date=s.isoformat(), end_date=e.isoformat(), limit=100000,
                )
            except Exception as exc:  # noqa: BLE001  科创50 等早期不存在的指数会失败, 跳过
                year += 1
                continue
            items = data.get("items") or []
            sym_total += _upsert_daily_bars(symbol, exchange, items)
            year += 1
        grand += sym_total
        print(f"{name}({symbol}.{exchange}): 写 {sym_total} 条  {time.time()-t0:.1f}s", flush=True)
    print(f"\n=== 共写入 {grand} 条 (7 指数 {START} ~ {END}) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
