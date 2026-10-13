# -*- coding: utf-8 -*-
"""w2s_touch_times 历史导入: 首次触板时间-全量.csv(2841笔,pytdx研究产物) → DB.

容器内跑: docker cp 本脚本+CSV 进 api 容器后 python w2s_touch_import.py <csv路径>
线上同样跑一次. 每日增量由 eod_finalize._backfill_touch_times(涨停池快照fbt)自动补.
"""
import sys
sys.path.insert(0, "/app")

from datetime import date

import pandas as pd

from alphaagent.server.services.weak_to_strong import repository


def main() -> None:
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/首次触板时间-全量.csv"
    df = pd.read_csv(csv_path, dtype={"vt_symbol": str}).dropna(subset=["touch"])
    rows = [{"vt_symbol": r.vt_symbol,
             "trade_date": date.fromisoformat(str(r.entry_day)),
             "touch": str(r.touch), "source": "pytdx"}
            for r in df.itertuples()]
    n = repository.upsert_touch_times(rows)
    print(f"导入 w2s_touch_times: {n} 笔 (来自 {csv_path})")
    m = repository.load_touch_map()
    print(f"表现有映射: {len(m)} 条")


if __name__ == "__main__":
    main()
