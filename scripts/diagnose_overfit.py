"""一次性诊断：CPCV 过拟合验证主线 0.1.21 + 门控变体对比。

只读调用 overfit_validation.cpcv_analyze（内部 run_backtest(persist=False)），
不写库、不改任何策略代码、对主线 0.1.21 零影响。跑完即可删除。

回答两个问题：
1. 当前 0.1.21 的 +83%/胜率32% 有多少水分（PBO / Deflated Sharpe）？
2. 放宽门控（variant C）/ 收紧启动确认（variant B）样本外到底值不值？

用法：
    uv run python scripts/diagnose_overfit.py --dry-run   # 仅验证数据加载与变体构造
    uv run python scripts/diagnose_overfit.py             # 跑 CPCV（约 40 分钟）
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from datetime import date
from pathlib import Path

from sqlalchemy import and_, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.backtest import overfit_validation as ov
from alphaagent.server.services.backtest.schemas import BacktestParams

STRATEGY_VERSION = "0.1.21"
RANGE_START = date(2025, 3, 26)
RANGE_END = date(2026, 6, 18)
OUT_JSON = Path("/tmp/overfit_result.json")


def load_trading_days() -> list[date]:
    """取主线 0.1.21 在对比区间内、已有候选缓存的交易日（保证 run_backtest 可跑）。"""

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


def build_variants(max_symbols: int = 5000, variants: str = "core") -> list[tuple[str, BacktestParams]]:
    """门控变体，min_entry_score 统一 76.0（主线策略 default），只改门控严格度。

    max_symbols 必须 >=5000：缩小子集会破坏策略表现（实测 400 股 IS Sharpe 为负），
    在残缺策略上验证过拟合无意义。variants=core 只跑 baseline vs loose。
    """

    base = BacktestParams(
        start=RANGE_START,
        end=RANGE_END,
        min_entry_score=76.0,
        strict_entry=True,
        max_symbols=max_symbols,
        persist=False,
    )
    all_variants = [
        (
            "baseline",
            replace(base),  # 主线默认：strict_entry=True，门控全 off
        ),
        (
            "strict_launch",
            replace(
                base,
                require_low_suction_launch_confirmation=True,
                require_low_suction_launch_for_low_suction_context=True,
            ),
        ),
        (
            "loose",
            replace(base, strict_entry=False),  # 放宽：买更多形态信号点
        ),
    ]
    if variants == "core":
        return [all_variants[0], all_variants[2]]
    return all_variants


def _progress(done: int, total: int, info: dict) -> None:
    print(f"  [{done}/{total}] path={info.get('path_id')} {info.get('stage')}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只验证数据与变体，不跑 CPCV")
    parser.add_argument("--n-groups", type=int, default=4)
    parser.add_argument("--n-test-groups", type=int, default=1)
    parser.add_argument("--max-symbols", type=int, default=5000)
    parser.add_argument("--variants", choices=["all", "core"], default="core")
    args = parser.parse_args()

    trading_days = load_trading_days()
    if len(trading_days) < args.n_groups:
        print(f"[ERROR] 交易日 {len(trading_days)} 少于 n_groups={args.n_groups}", file=sys.stderr)
        return 1
    print(f"trading_days: {len(trading_days)} ({trading_days[0]} .. {trading_days[-1]})", flush=True)

    variants = build_variants(args.max_symbols, args.variants)
    print("variants:", flush=True)
    for name, params in variants:
        diffs = {
            k: getattr(params, k)
            for k in ("strict_entry", "require_low_suction_launch_confirmation",
                      "require_low_suction_launch_for_low_suction_context", "min_entry_score")
        }
        print(f"  - {name}: {diffs}", flush=True)

    if args.dry_run:
        print("\n[dry-run] 数据与变体就绪，未跑 CPCV。", flush=True)
        return 0

    started = time.time()
    print(f"\n开始 CPCV：n_groups={args.n_groups} n_test_groups={args.n_test_groups} "
          f"variants={len(variants)} "
          f"预计回测次数={_estimate_runs(args.n_groups, args.n_test_groups, len(variants))}", flush=True)

    result = ov.cpcv_analyze(
        base_params=variants[0][1],
        variant_params=[p for _, p in variants],
        trading_days=trading_days,
        n_groups=args.n_groups,
        n_test_groups=args.n_test_groups,
        metric="sharpe",
        on_progress=_progress,
    )
    elapsed = time.time() - started

    summary = {
        "strategy_version": STRATEGY_VERSION,
        "max_symbols": args.max_symbols,
        "range": [str(RANGE_START), str(RANGE_END)],
        "n_trading_days": len(trading_days),
        "n_groups": args.n_groups,
        "n_test_groups": args.n_test_groups,
        "variant_names": [name for name, _ in variants],
        "elapsed_seconds": round(elapsed, 1),
        "pbo": result.get("pbo"),
        "logit_pbo": result.get("logit_pbo"),
        "dsr": result.get("dsr"),
        "dsr_expected_max_sharpe": result.get("dsr_expected_max_sharpe"),
        "oos_mean_sharpe_annualized": result.get("oos_mean_sharpe_annualized"),
        "n_paths": result.get("n_paths"),
        "n_evaluated_paths": result.get("n_evaluated_paths"),
        "oos_rank_distribution": result.get("oos_rank_distribution"),
        "paths": result.get("paths"),
    }

    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    print("\n" + "=" * 60, flush=True)
    print(f"CPCV 完成，耗时 {elapsed:.0f}s", flush=True)
    print(f"PBO (过拟合概率，越低越稳):       {summary['pbo']}", flush=True)
    print(f"logit PBO (越负越稳):              {summary['logit_pbo']}", flush=True)
    print(f"Deflated Sharpe (>0.95 才显著):    {summary['dsr']}", flush=True)
    print(f"OOS 年化 Sharpe 均值:              {summary['oos_mean_sharpe_annualized']}", flush=True)
    print(f"OOS 最优变体排名分布:              {summary['oos_rank_distribution']}", flush=True)
    print(f"评估路径数: {summary['n_evaluated_paths']}/{summary['n_paths']}", flush=True)
    print(f"明细已落盘: {OUT_JSON}", flush=True)
    return 0


def _estimate_runs(n_groups: int, n_test_groups: int, n_variants: int) -> int:
    """C(n_groups, n_test_groups) 条路径 × n_variants × 2(IS+OOS)。"""

    from math import comb
    return comb(n_groups, n_test_groups) * n_variants * 2


if __name__ == "__main__":
    sys.exit(main())
