"""Targeted five-minute collection for low-suction gold-strong-reclaim signal days.

为方向②(盘中提前扫描弱转强)回填分钟线。镜像 forward_ma5_minutes 的 TDX 路径与
48 根 5m 覆盖契约;宇宙源是 select_gold_strong_reclaim_signals 重算(无持久化表)。
manual-only,不进默认 21:30 批次。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import pandas as pd

from .event_recognition_minutes import (
    INTERVAL,
    WINDOW_END,
    WINDOW_START,
    build_event_5m_manifest,
)


DATASET = "low_suction_gold_strong_reclaim_5m"
WINDOW = "reclaim_signal_day_5m"
MAX_BACKFILL_GAPS = 500


def load_reclaim_signal_pairs(
    *,
    start: date = date(2024, 8, 1),
    end: date | None = None,
) -> pd.DataFrame:
    """Recompute the reclaim signal universe and emit exact (symbol, date) pairs."""

    from .causal_leader_pullback import select_gold_strong_reclaim_signals
    from .causal_leader_pullback_study import (
        build_causal_stock_features,
        build_concept_campaign_ledger,
        build_dynamic_leader_paths,
        load_causal_leader_pullback_inputs,
        prepare_dynamic_leader_paths,
    )

    inputs = load_causal_leader_pullback_inputs()
    features = build_causal_stock_features(inputs.stock_bars)
    _, campaign_paths = build_concept_campaign_ledger(inputs.concept_bars)
    leader_paths, _ = build_dynamic_leader_paths(
        campaign_paths, inputs.memberships, features
    )
    prepared = prepare_dynamic_leader_paths(leader_paths, inputs.market_timing)
    signals = select_gold_strong_reclaim_signals(prepared.signals)
    if signals.empty:
        return _empty_pairs()
    frame = signals.loc[:, ["vt_symbol", "signal_date"]].copy()
    frame["signal_date"] = pd.to_datetime(frame["signal_date"], errors="raise").dt.date
    end_date = end or frame["signal_date"].max()
    frame = frame.loc[frame["signal_date"].between(start, end_date)]
    frame = frame.drop_duplicates(["vt_symbol", "signal_date"], keep="first")
    rows = [
        {
            "event_id": f"{row.vt_symbol}:{row.signal_date.isoformat()}",
            "source_date": row.signal_date,
            "entry_date": row.signal_date,
            "vt_symbol": row.vt_symbol,
        }
        for row in frame.itertuples(index=False)
    ]
    return pd.DataFrame.from_records(rows).reset_index(drop=True)


def load_reclaim_signal_manifest() -> pd.DataFrame:
    """Classify current local 5m coverage for every reclaim signal pair."""

    from .leader_ma5_scheme_minutes import load_existing_scheme_minutes

    pairs = load_reclaim_signal_pairs()
    existing = load_existing_scheme_minutes(pairs)
    return build_event_5m_manifest(pairs, existing)


def backfill_reclaim_signal_5m(
    *,
    dry_run: bool,
    max_gaps: int = 100,
) -> dict[str, Any]:
    """Backfill bounded reclaim-signal-day gaps through the public TDX importer."""

    capped_max_gaps = min(max(int(max_gaps), 1), MAX_BACKFILL_GAPS)
    manifest = load_reclaim_signal_manifest()
    missing = manifest.loc[manifest["status"].ne("complete")].head(capped_max_gaps)
    complete_before = int(manifest["status"].eq("complete").sum())
    gaps = [
        {
            "vt_symbol": str(row.vt_symbol),
            "trade_date": row.entry_date,
            "reference_date": row.source_date,
            "window": WINDOW,
        }
        for row in missing.itertuples(index=False)
    ]
    if not gaps:
        return {
            "status": "ready",
            "dry_run": dry_run,
            "dataset": DATASET,
            "manifest_pairs": int(len(manifest)),
            "manifest_complete_before": complete_before,
            "manifest_missing_before": 0,
            "requested_missing_pairs": 0,
            "rows_read": 0,
            "rows_written": 0,
        }
    result = _import_tdx_gaps(
        gaps=gaps,
        interval=INTERVAL,
        tail_entry_start=WINDOW_START,
        tail_entry_end=WINDOW_END,
        dry_run=dry_run,
        max_gaps=capped_max_gaps,
        max_pages_per_symbol=81,
        timeout_seconds=3.0,
    )
    return {
        **result,
        "dataset": DATASET,
        "manifest_pairs": int(len(manifest)),
        "manifest_complete_before": complete_before,
        "manifest_missing_before": int(len(manifest) - complete_before),
        "requested_missing_pairs": len(gaps),
    }


def _import_tdx_gaps(**kwargs: Any) -> dict[str, Any]:
    from alphaagent.server.services.data_providers.tdx_minute_import import (
        import_tdx_minute_bars_for_gaps,
    )

    return import_tdx_minute_bars_for_gaps(**kwargs)


def _empty_pairs() -> pd.DataFrame:
    return pd.DataFrame(columns=["event_id", "source_date", "entry_date", "vt_symbol"])


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
