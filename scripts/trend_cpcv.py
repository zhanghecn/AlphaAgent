"""CPCV 验证 trend trailing 0.08 vs 0.10（B 扫描赢家是否样本外稳健）。

B 扫描结论：trailing 0.10 全样本 return 64.7% vs 0.08 的 47.9%（+16.8pp），
sharpe 1.56 vs 1.17，组合验证确认 take_profit 保持 0.18。本脚本 CPCV 检验
trailing 0.10 是否过拟合（IS 最优→OOS 是否崩）。PBO < 0.5 才算样本外稳健。

复用 overfit_validation.cpcv_analyze（内部 run_backtest(persist=False)）。
只读，不写库，不改策略代码。跑完即可删除。
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

from sqlalchemy import and_, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.backtest import overfit_validation as ov
from alphaagent.server.services.backtest.schemas import BacktestParams
from alphaagent.server.services.quant.factors import TREND_ACCELERATION_STRATEGY_ID

STRATEGY_VERSION = "0.1.21"  # 交易日切分用龙回头 signal_runs（市场交易日，与策略无关）
RANGE_START = date(2025, 3, 26)
RANGE_END = date(2026, 6, 18)
OUT_JSON = Path("/tmp/trend_cpcv.json")


def load_trading_days() -> list[date]:
    with session_scope() as session:
        rows = (
            session.execute(
                select(schema.quant_signal_runs.c.trade_date)
                .where(
                    and_(
                        schema.quant_signal_runs.c.strategy_version == STRATEGY_VERSION,
                        schema.quant_signal_runs.c.trade_date >= RANGE_START,
                        schema.quant_signal_runs.c.trade_date <= RANGE_END,
                    )
                )
                .distinct()
            )
            .scalars()
            .all()
        )
    return sorted(set(rows))


def main() -> int:
    trading_days = load_trading_days()
    print(f"trading_days: {len(trading_days)} ({trading_days[0]} .. {trading_days[-1]})", flush=True)

    base = BacktestParams(
        strategy=TREND_ACCELERATION_STRATEGY_ID,
        start=RANGE_START,
        end=RANGE_END,
        min_entry_score=73.0,  # trend default_min_entry_score
        strict_entry=True,
        max_symbols=5000,
        max_position_pct=0.125,  # 与 trend_exit_sweep 一致
        stop_loss_pct=0.08,
        take_profit_pct=0.18,
        persist=False,
    )
    variants = [
        ("tr_0.08", replace(base, trailing_stop_pct=0.08)),
        ("tr_0.10", replace(base, trailing_stop_pct=0.10)),
    ]
    print("variants:", [name for name, _ in variants], flush=True)

    started = time.time()
    print(f"\n开始 CPCV: n_groups=3 n_test_groups=1 预计回测次数={6*2*2}=24...", flush=True)

    def progress(done: int, total: int, info: dict) -> None:
        print(f"  [{done}/{total}] path={info.get('path_id')} {info.get('stage')}", flush=True)

    result = ov.cpcv_analyze(
        base_params=variants[0][1],
        variant_params=[p for _, p in variants],
        trading_days=trading_days,
        n_groups=3,
        n_test_groups=1,
        metric="sharpe",
        on_progress=progress,
    )
    elapsed = time.time() - started

    print("\n" + "=" * 60, flush=True)
    print(f"耗时 {elapsed:.0f}s", flush=True)
    print(f"PBO (过拟合概率，<0.5 稳健): {result.get('pbo')}", flush=True)
    print(f"Deflated Sharpe (>0.95 显著): {result.get('dsr')}", flush=True)
    print(f"OOS 年化 Sharpe 均值:         {result.get('oos_mean_sharpe_annualized')}", flush=True)
    print(f"OOS 最优变体排名分布(0=最差):  {result.get('oos_rank_distribution')}", flush=True)
    for p in result.get("paths", []):
        name = variants[p["best_variant_idx"]][0]
        oos = p["oos_metric"]
        print(
            f"  path{p['path_id']} test{p['test_groups']}: IS最优={name}(IS {p['is_metric']:.2f}) "
            f"-> OOS {round(oos, 3) if oos is not None else None}, rank {p['oos_rank']}/1",
            flush=True,
        )
    print(f"\n明细落盘: {OUT_JSON}", flush=True)

    summary = {
        "comparison": "trend tr_0.08 vs tr_0.10",
        "elapsed_seconds": round(elapsed, 0),
        "pbo": result.get("pbo"),
        "dsr": result.get("dsr"),
        "oos_mean_sharpe_annualized": result.get("oos_mean_sharpe_annualized"),
        "oos_rank_distribution": result.get("oos_rank_distribution"),
        "paths": result.get("paths"),
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
