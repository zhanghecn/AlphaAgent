"""Causal point-in-time replay for the shared first-board decision chain."""

from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from statistics import median
from time import monotonic
from zoneinfo import ZoneInfo

import pandas as pd

from alphaagent.server.services.limit_up import (
    cash_backtest,
    history_engine,
    history_repository,
    preboard_decision_repository,
    scheduled_execution,
)
from alphaagent.server.services.limit_up.cash_backtest import CashBacktestConfig
from alphaagent.server.services.limit_up.first_board_stock_gene_research import (
    attach_prior_stock_gene_evidence_to_orders,
)
from alphaagent.server.services.limit_up.first_board_quality import (
    build_preboard_pools,
)
from alphaagent.server.services.limit_up.features import market_snapshot_for_trade
from alphaagent.server.services.limit_up.live_evidence import (
    build_same_stock_first_board_d1_index,
    resolve_candidate_historical_evidence,
)
from alphaagent.server.services.limit_up.lane_repository import (
    financial_risk_as_of,
    financial_snapshot_as_of,
)
from alphaagent.server.services.limit_up.lane_research import (
    FIRST_BOARD_MOMENTUM_MIN_SCORE,
)
from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PreboardPolicyThresholds,
    apply_preboard_parity_contract,
    preboard_market_gate,
)
from alphaagent.server.services.limit_up.preboard_decision_features import (
    MODEL_FEATURE_NAMES,
    build_lane_prefix,
    build_lane_prefixes,
    project_historical_decision_features,
    project_prepared_historical_decision_features,
    session_minute_index,
)
from alphaagent.server.services.limit_up.preboard_live_minute_buffer import (
    LiveMinuteBuffer,
)
from alphaagent.server.services.limit_up.preboard_decision_policy import (
    can_compete_for_action,
    evaluate_preboard_decisions,
    preboard_action_sort_key,
    select_preboard_decisions,
)
from alphaagent.server.services.limit_up.preboard_decision_model import (
    fit_preboard_model,
    qualify_preboard_probabilities,
    score_preboard_rows,
)
from alphaagent.server.services.limit_up.preboard_transaction_features import (
    TRANSACTION_FEATURE_NAMES,
    TRANSACTION_FEATURE_VERSION,
)
from alphaagent.server.services.limit_up.scheduled_execution import MAX_POSITIONS
from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION


ENTRY_CONTRACT = "first_new_quote_after_action_strictly_below_limit"
EXIT_CONTRACT = "d1_official_close_after_formal_costs"
FORMAL_BASELINE_ENTRY_CONTRACT = "formal_touch_event"
FORMAL_BASELINE_PREBOARD_EXECUTABLE = False
MAXIMUM_FIRST_BOARD_POSITIONS = MAX_POSITIONS
REPLAY_CONTRACT_VERSION = "limit-up-preboard-decision-replay-v1"
FROZEN_PATH_MANIFEST_VERSION = "limit-up-preboard-decision-pairs-v1"
FROZEN_PATH_SESSION_COUNT = 89
FROZEN_PATH_START_DATE = date(2026, 3, 11)
FROZEN_PATH_END_DATE = date(2026, 7, 20)
FROZEN_PATH_PAIR_COUNT = 1_044
RECENT_TIMING_AUDIT_START = date(2026, 7, 20)
RECENT_TIMING_AUDIT_END = date(2026, 7, 22)
MINIMUM_FIT_DATES = 40
MINIMUM_VALIDATION_ACTIONS = 20
MINIMUM_CALIBRATION_ACTIONS = 10
HALF_HOUR_BUCKETS = (
    ("10:00-10:30", time(10, 0), time(10, 30)),
    ("10:30-11:00", time(10, 30), time(11, 0)),
    ("11:00-11:30", time(11, 0), time(11, 30)),
    ("13:00-13:30", time(13, 0), time(13, 30)),
    ("13:30-14:00", time(13, 30), time(14, 0)),
    ("14:00-14:30", time(14, 0), time(14, 30)),
)
PROMOTION_STATUSES = frozenset(
    {
        "historical_pass_for_shadow",
        "historical_rejected",
        "insufficient_for_portfolio_promotion",
    }
)

_STATIC_CANDIDATE_FIELDS = (
    "industry_id",
    "industry_name",
    "auction_gap_pct",
    "prior_streak",
    "prior_break_streak",
    "prior_limit_count_126",
    "prior_touch_count_126",
    "prior_limit_count_5",
    "prior_limit_count_10",
    "prior_seal_success_rate_126",
    "trade_days_since_prior_limit",
    "pullback_from_prior_limit_pct",
    "prior_position_120",
    "prior_change_pct",
    "prior_open_gap_pct",
    "prior_low_change_pct",
    "prior_amplitude_pct",
    "prior_return_5d_pct",
    "prior_return_20d_pct",
    "prior_turnover_rate",
    "prior_amount_ratio_5d",
    "prior_industry_change_pct",
    "prior_industry_return_5d_pct",
    "prior_industry_advancing_rate",
    "prior_industry_turnover_ratio_5d",
    "prior_industry_sealed_count",
    "prior_industry_sealed_rate",
    "prior_industry_heat_score",
    "prior_industry_heat_rank",
    "prior_industry_count",
    "prior_industry_leadership_score",
    "prior_industry_leader_rank",
    "prior_industry_stock_count",
    "prior_market_phase",
    "prior_market_advancing_rate",
    "prior_market_sealed_count",
    "prior_market_failed_rate",
    "prior_market_max_board",
    "prior_market_first_board_count",
    "prior_market_one_to_two_rate",
    "prior_market_two_to_three_rate",
)

_LABEL_ONLY_FIELDS = frozenset(
    {
        "physical_touch_at",
        "first_limit_time",
        "last_limit_time",
        "final_sealed",
        "formal_baseline_identity",
        "formal_identity_matched",
        "touched_limit",
        "sealed_limit",
        "d1_trade_date",
        "d1_close_price",
        "result_date",
        "net_return_pct",
        "next_close_return_pct",
        "fill_price",
    }
)

TRANSIENT_REPLAY_FIELDS = frozenset(
    {
        "minute_bars",
        "path_prefix",
        "candidates",
        "cross_section_snapshots",
        "transaction_rows",
        "historical_evidence",
        "execution_checks",
        "transaction_features",
        "financial_snapshot",
        "financial_risk",
        "features",
        "feature_names",
    }
)


@dataclass(frozen=True)
class ReplayDateSplit:
    fit: tuple[date, ...]
    calibration: tuple[date, ...]
    validation: tuple[date, ...]


@dataclass(frozen=True)
class ReplayCalibration:
    status: str
    thresholds: PreboardPolicyThresholds | None
    selected_metrics: dict[str, object] | None
    metrics_by_threshold: tuple[dict[str, object], ...]
    calibration_dates: tuple[date, ...]


@dataclass(frozen=True)
class FrozenPreboardPathIndex:
    status: str
    manifest_version: str
    session_count: int
    start_date: date
    end_date: date
    input_fingerprint: str
    pairs: tuple[tuple[str, date], ...]
    raw_upper_bound_pair_count: int
    source_complete_minute_pair_count: int
    static_high_quality_pair_count: int
    candidate_index_fingerprint: str
    minute_complete_pair_count: int
    transaction_ready_pair_count: int
    minute_status_counts: dict[str, int]


@dataclass(frozen=True)
class ReplayDataset:
    status: str
    dates: tuple[date, ...]
    rows: tuple[dict[str, object], ...]
    formal_orders: tuple[dict[str, object], ...]
    account_bars: tuple[dict[str, object], ...]
    trade_dates: tuple[date, ...]
    market_diagnostics: dict[str, dict[str, object]]
    coverage: dict[str, object]
    candidate_index_audit: dict[str, object]
    pool_audit: dict[str, object]
    profitability_audit: dict[str, object]
    input_fingerprint: str


@dataclass(frozen=True)
class RecentReplayInputs:
    status: str
    candidates: dict[tuple[str, date], dict[str, object]]
    minute_rows: tuple[dict[str, object], ...]
    transaction_rows: tuple[dict[str, object], ...]
    audit: dict[str, object]
    static_pair_audit: dict[tuple[str, date], dict[str, object]] = field(
        default_factory=dict
    )


def load_frozen_preboard_path_index(
    *,
    session_count: int = FROZEN_PATH_SESSION_COUNT,
    end_date: date | None = FROZEN_PATH_END_DATE,
    verify_reference: bool = True,
    manifest_loader: Callable[..., Mapping[str, object] | None] | None = None,
    minute_coverage_loader: Callable[[pd.DataFrame], object] | None = None,
    transaction_coverage_loader: Callable[..., Mapping[str, object]] | None = None,
) -> FrozenPreboardPathIndex:
    """Load the immutable path list without rebuilding it from outcome labels."""

    if manifest_loader is None:
        from alphaagent.server.services.limit_up.preboard_transaction_repository import (
            load_latest_transaction_pair_manifest,
        )

        manifest_loader = load_latest_transaction_pair_manifest
    if minute_coverage_loader is None:
        from alphaagent.server.services.limit_up.preboard_hazard_data import (
            load_one_minute_coverage,
        )

        minute_coverage_loader = load_one_minute_coverage
    if transaction_coverage_loader is None:
        from alphaagent.server.services.limit_up.preboard_transaction_repository import (
            load_transaction_feature_coverage,
        )

        transaction_coverage_loader = load_transaction_feature_coverage

    manifest = manifest_loader(
        manifest_version=FROZEN_PATH_MANIFEST_VERSION,
        session_count=int(session_count),
        end_date=end_date,
    )
    if manifest is None:
        raise ValueError("frozen v1 preboard path manifest is unavailable")
    manifest_version = str(manifest.get("manifest_version") or "")
    if manifest_version != FROZEN_PATH_MANIFEST_VERSION:
        raise ValueError("frozen preboard path manifest version differs")
    if str(manifest.get("status") or "") != "ready":
        raise ValueError("frozen preboard path manifest is not ready")
    start = _as_date(manifest.get("start_date"))
    end = _as_date(manifest.get("end_date"))
    if start is None or end is None or start > end:
        raise ValueError("frozen preboard path manifest dates are invalid")
    raw_pairs = manifest.get("pairs")
    pairs = tuple(
        sorted(
            {
                (symbol, trade_date)
                for row in _mapping_rows(raw_pairs)
                if (symbol := str(row.get("vt_symbol") or "").strip())
                and (trade_date := _as_date(row.get("trade_date"))) is not None
            },
            key=lambda pair: (pair[1], pair[0]),
        )
    )
    declared_count = int(_number(manifest.get("shared_pair_count")) or 0)
    if not pairs or declared_count != len(pairs):
        raise ValueError("frozen preboard path manifest pair count differs")
    raw_upper_bound_pair_count = int(
        _number(manifest.get("manifest_pair_count")) or 0
    )
    source_complete_minute_pair_count = int(
        _number(manifest.get("complete_minute_pair_count")) or 0
    )
    static_high_quality_pair_count = int(
        _number(manifest.get("static_upper_bound_pair_count")) or 0
    )
    if not (
        raw_upper_bound_pair_count
        >= source_complete_minute_pair_count
        >= static_high_quality_pair_count
        >= len(pairs)
        > 0
    ):
        raise ValueError("frozen preboard path manifest audit counts differ")
    if verify_reference and (
        int(session_count) != FROZEN_PATH_SESSION_COUNT
        or start != FROZEN_PATH_START_DATE
        or end != FROZEN_PATH_END_DATE
        or len(pairs) != FROZEN_PATH_PAIR_COUNT
    ):
        raise ValueError("frozen preboard reference scope differs from the audited v1 set")

    frame = pd.DataFrame(
        [
            {"vt_symbol": symbol, "trade_date": trade_date}
            for symbol, trade_date in pairs
        ]
    )
    minute_rows = _records(minute_coverage_loader(frame))
    minute_status_counts: defaultdict[str, int] = defaultdict(int)
    complete_pairs: set[tuple[str, date]] = set()
    for row in minute_rows:
        status = str(row.get("coverage_status") or "unknown")
        minute_status_counts[status] += 1
        pair = (str(row.get("vt_symbol") or ""), _as_date(row.get("trade_date")))
        if (
            status == "complete"
            and pair[1] is not None
            and int(_number(row.get("raw_row_count")) or 0) == 240
        ):
            complete_pairs.add((pair[0], pair[1]))
    transaction = transaction_coverage_loader(
        pairs,
        feature_version=TRANSACTION_FEATURE_VERSION,
    )
    transaction_ready = int(transaction.get("ready_pair_count") or 0)
    status = "ready"
    if len(complete_pairs) != len(pairs):
        status = "blocked_by_one_minute_path_coverage"
    elif transaction_ready != len(pairs):
        status = "blocked_by_transaction_path_coverage"
    return FrozenPreboardPathIndex(
        status=status,
        manifest_version=manifest_version,
        session_count=int(session_count),
        start_date=start,
        end_date=end,
        input_fingerprint=str(manifest.get("input_fingerprint") or ""),
        pairs=pairs,
        raw_upper_bound_pair_count=raw_upper_bound_pair_count,
        source_complete_minute_pair_count=source_complete_minute_pair_count,
        static_high_quality_pair_count=static_high_quality_pair_count,
        candidate_index_fingerprint=candidate_index_fingerprint(pairs),
        minute_complete_pair_count=len(complete_pairs),
        transaction_ready_pair_count=transaction_ready,
        minute_status_counts=dict(sorted(minute_status_counts.items())),
    )


def load_frozen_replay_dataset(
    *,
    session_count: int = FROZEN_PATH_SESSION_COUNT,
    end_date: date | None = FROZEN_PATH_END_DATE,
    progress: Callable[[str], None] | None = None,
) -> ReplayDataset:
    """Load and project the immutable v1 paths through the current shared chain."""

    emit = progress or (lambda _message: None)
    emit("stage=frozen_path_index")
    path_index = load_frozen_preboard_path_index(
        session_count=session_count,
        end_date=end_date,
    )
    if path_index.status != "ready":
        return _blocked_dataset(path_index.status, path_index)

    from alphaagent.server.services.limit_up import preboard_transaction_data
    from alphaagent.server.services.limit_up import preboard_transaction_repository
    from alphaagent.server.services.limit_up import radar_observation_repository
    from alphaagent.server.services.limit_up.preboard_hazard_data import (
        load_one_minute_bars,
    )

    emit("stage=static_scope")
    scope, scope_audit = preboard_transaction_data.load_preboard_decision_static_scope(
        session_count=session_count,
        end_date=path_index.end_date,
    )
    if scope is None:
        return _blocked_dataset(str(scope_audit.get("status") or "blocked"), path_index)
    scoped_manifest = _frame_for_pairs(scope.minute_manifest, set(path_index.pairs))
    if len(scoped_manifest) != len(path_index.pairs):
        return _blocked_dataset("blocked_by_frozen_static_scope_parity", path_index)
    scoped_features, scoped_financials = _filter_static_scope_indexes(
        path_index.pairs,
        scope.feature_by_pair,
        scope.financial_index,
    )
    del scope

    emit("stage=minute_paths")
    minute_frame = load_one_minute_bars(scoped_manifest)
    emit("stage=transaction_paths")
    transaction_rows = preboard_transaction_repository.load_transaction_features(
        path_index.pairs,
        feature_version=TRANSACTION_FEATURE_VERSION,
    )
    symbols = sorted({symbol for symbol, _trade_date in path_index.pairs})
    emit("stage=historical_environment")
    environment_rows = radar_observation_repository.load_observations(
        path_index.start_date,
        path_index.end_date,
        symbols=symbols,
    )
    emit("stage=prior_only_evidence")
    history_days = history_repository.load_history_evidence_rows(
        HISTORY_STRATEGY_VERSION,
        path_index.end_date,
    )

    emit("stage=point_in_time_quality")
    rows, pool_audit = _build_frozen_path_decision_rows(
        scoped_manifest.to_dict(orient="records"),
        minute_frame.to_dict(orient="records"),
        feature_by_pair=scoped_features,
        financial_index=scoped_financials,
        history_days=history_days,
        transaction_rows=transaction_rows,
        environment_rows=environment_rows,
    )

    emit("stage=formal_baseline")
    complete_history = history_repository.load_history_range(
        HISTORY_STRATEGY_VERSION,
        None,
        path_index.end_date,
        False,
    )
    scoped_history = [
        day
        for day in complete_history
        if path_index.start_date
        <= (_as_date(day.get("trade_date")) or date.min)
        <= path_index.end_date
    ]
    formal_orders, profitability_audit = _formal_orders(
        complete_history,
        scoped_history,
        path_index.start_date,
        path_index.end_date,
    )
    labels = _manifest_labels(
        scoped_manifest.to_dict(orient="records"),
        minute_frame.to_dict(orient="records"),
        formal_orders,
    )
    candidate_index_audit = _candidate_index_audit(path_index, labels)
    labeled_rows = attach_replay_labels(rows, labels)

    account_end = max(
        (
            result_date
            for order in formal_orders
            if (result_date := _as_date(order.get("result_date"))) is not None
        ),
        default=path_index.end_date,
    )
    account_symbols = sorted(
        {
            *symbols,
            *(
                str(order.get("vt_symbol") or "")
                for order in formal_orders
                if order.get("vt_symbol")
            ),
        }
    )
    account_bars = history_repository.load_account_daily_bars(
        account_symbols,
        path_index.start_date,
        account_end,
    )
    from alphaagent.server.services.limit_up.preboard_momentum_data import (
        load_reliable_trade_dates,
    )

    trade_dates = load_reliable_trade_dates(path_index.start_date, account_end)
    emit("stage=market_diagnostics")
    market_diagnostics = _load_market_diagnostics(
        path_index.start_date,
        path_index.end_date,
        trade_dates,
    )
    dates = _bounded_replay_dates(
        start=path_index.start_date,
        end=path_index.end_date,
        trade_dates=trade_dates,
    )
    coverage = _coverage_report(
        path_index,
        rows=labeled_rows,
        transaction_rows=transaction_rows,
        environment_rows=environment_rows,
        static_scope_audit=scope_audit,
    )
    input_fingerprint = _dataset_fingerprint(
        path_index,
        labeled_rows,
        formal_orders,
    )
    return ReplayDataset(
        status="ready",
        dates=dates,
        rows=tuple(labeled_rows),
        formal_orders=tuple(formal_orders),
        account_bars=tuple(dict(row) for row in account_bars),
        trade_dates=tuple(trade_dates),
        market_diagnostics=market_diagnostics,
        coverage=coverage,
        candidate_index_audit=candidate_index_audit,
        pool_audit=pool_audit,
        profitability_audit=profitability_audit,
        input_fingerprint=input_fingerprint,
    )


def _build_frozen_path_decision_rows(
    manifest_rows: Sequence[Mapping[str, object]],
    minute_rows: Sequence[Mapping[str, object]],
    *,
    feature_by_pair: Mapping[tuple[str, date], Mapping[str, object]],
    financial_index: object,
    history_days: list[Mapping[str, object]],
    transaction_rows: Sequence[Mapping[str, object]],
    environment_rows: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    manifests = {
        pair: dict(row)
        for row in manifest_rows
        if (pair := _row_pair(row)) is not None
    }
    bars_by_pair = _bars_by_pair(minute_rows)
    cross_sections = _build_cross_section_snapshots(manifests, bars_by_pair)
    cross_section_times = {
        trade_date: [captured_at for captured_at, _row in snapshots]
        for trade_date, snapshots in cross_sections.items()
    }
    transaction_index = _transaction_index(transaction_rows)
    environment_index = _environment_index(environment_rows)
    pairs_by_date: defaultdict[date, list[tuple[str, date]]] = defaultdict(list)
    for pair in bars_by_pair:
        pairs_by_date[pair[1]].append(pair)
    rows: list[dict[str, object]] = []
    raw_capture_counts: Counter[str] = Counter()
    raw_capture_symbols: defaultdict[str, set[str]] = defaultdict(set)

    for trade_date, (analog_index, stock_d1_index) in _iter_prior_indexes(
        sorted(pairs_by_date),
        history_days,
    ):
        points: list[dict[str, object]] = []
        for pair in sorted(pairs_by_date[trade_date]):
            bars = bars_by_pair[pair]
            manifest = manifests.get(pair)
            feature_row = feature_by_pair.get(pair)
            if manifest is None or feature_row is None:
                continue
            static_candidate = _static_candidate(
                manifest,
                feature_row,
                financial_index=financial_index,
            )
            previous_close = _number(manifest.get("previous_close"))
            limit_price = _number(manifest.get("limit_price"))
            if previous_close is None or limit_price is None:
                continue
            lane_prefixes = build_lane_prefixes(
                bars,
                previous_close=previous_close,
            )
            first_observed_at: datetime | None = None
            for index, bar in enumerate(bars[:-1]):
                decision_at = _as_datetime(bar.get("bar_time"))
                if decision_at is None:
                    continue
                if (
                    (_number(bar.get("high_price")) or float("-inf"))
                    >= limit_price - 0.001
                ):
                    break
                gain = _return_pct(previous_close, _number(bar.get("close_price")))
                if first_observed_at is None and gain is not None and gain >= 3.0:
                    first_observed_at = decision_at
                if (
                    first_observed_at is None
                    or gain is None
                    or gain < 3.0
                    or not scheduled_execution.is_entry_time(decision_at.time())
                ):
                    continue
                trade_date_text = decision_at.date().isoformat()
                raw_capture_counts[trade_date_text] += 1
                raw_capture_symbols[trade_date_text].add(pair[0])
                environment = _environment_at(
                    environment_index.get(pair, ()),
                    decision_at,
                )
                candidate = _candidate_at_time(
                    static_candidate,
                    manifest,
                    bars,
                    index,
                    path_prefix=lane_prefixes[index],
                    first_observed_at=first_observed_at,
                    transaction=transaction_index.get(
                        (pair[0], pair[1], decision_at)
                    ),
                    environment=environment,
                )
                evidence = resolve_candidate_historical_evidence(
                    {
                        "vt_symbol": pair[0],
                        "entry_kind": "momentum",
                        "target_board": 1,
                    },
                    candidate,
                    {},
                    "now",
                    pair[1],
                    analog_index,
                    stock_d1_index,
                )
                candidate["historical_evidence"] = evidence
                snapshots = cross_sections.get(pair[1], ())
                snapshot_position = bisect_right(
                    cross_section_times.get(pair[1], ()),
                    decision_at,
                )
                visible_snapshots = [
                    snapshot
                    for _captured_at, snapshot in snapshots[
                        max(snapshot_position - 2, 0) : snapshot_position
                    ]
                ]
                points.append(
                    {
                        "decision_at": decision_at.isoformat(),
                        "market_gate": _market_gate_from_environment(environment),
                        "candidates": [candidate],
                        "cross_section_snapshots": visible_snapshots,
                    }
                )
        day_rows = build_historical_point_rows(points)
        rows.extend(day_rows)

    pool_audit = _pool_audit(rows, raw_capture_counts, raw_capture_symbols)
    return rows, pool_audit


def _iter_prior_indexes(
    trade_dates: Sequence[date],
    history_days: Sequence[Mapping[str, object]],
) -> Iterator[
    tuple[
        date,
        tuple[
            Mapping[tuple[object, ...], object],
            Mapping[str, Mapping[str, object]],
        ],
    ]
]:
    replay_days = history_days if isinstance(history_days, list) else list(history_days)
    for trade_date in trade_dates:
        yield trade_date, (
            history_engine.build_analog_index(
                replay_days,
                result_before=trade_date,
            ),
            build_same_stock_first_board_d1_index(
                replay_days,
                signal_date=trade_date,
            ),
        )


def _blocked_dataset(
    status: str,
    path_index: FrozenPreboardPathIndex,
) -> ReplayDataset:
    return ReplayDataset(
        status=status,
        dates=tuple(sorted({trade_date for _symbol, trade_date in path_index.pairs})),
        rows=(),
        formal_orders=(),
        account_bars=(),
        trade_dates=(),
        market_diagnostics={},
        coverage={"frozen_path_index": asdict(path_index)},
        candidate_index_audit={},
        pool_audit={},
        profitability_audit={},
        input_fingerprint=path_index.input_fingerprint,
    )


def _frame_for_pairs(
    frame: pd.DataFrame,
    pairs: set[tuple[str, date]],
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    selected = frame.loc[
        [
            (str(row.vt_symbol), _as_date(row.trade_date)) in pairs
            for row in frame.itertuples()
        ]
    ].copy()
    return selected.sort_values(["trade_date", "vt_symbol"], kind="stable")


def _filter_static_scope_indexes(
    pairs: Sequence[tuple[str, date]],
    feature_by_pair: Mapping[tuple[str, date], Mapping[str, object]],
    financial_index: object,
) -> tuple[dict[tuple[str, date], Mapping[str, object]], object]:
    requested_pairs = set(pairs)
    features = {
        pair: row
        for pair, row in feature_by_pair.items()
        if pair in requested_pairs
    }
    if not isinstance(financial_index, Mapping):
        return features, financial_index
    requested_symbols = {symbol for symbol, _trade_date in requested_pairs}
    financials = {
        str(symbol): rows
        for symbol, rows in financial_index.items()
        if str(symbol) in requested_symbols
    }
    return features, financials


def _row_pair(row: Mapping[str, object]) -> tuple[str, date] | None:
    symbol = str(row.get("vt_symbol") or "").strip()
    trade_date = _as_date(
        row.get("trade_date")
        or row.get("signal_date")
        or row.get("entry_date")
    )
    return (symbol, trade_date) if symbol and trade_date is not None else None


def _bars_by_pair(
    rows: Sequence[Mapping[str, object]],
) -> dict[tuple[str, date], list[dict[str, object]]]:
    grouped: defaultdict[tuple[str, date], list[dict[str, object]]] = defaultdict(list)
    for raw in rows:
        row = raw if isinstance(raw, dict) else dict(raw)
        pair = _row_pair(row)
        bar_time = _local_naive_datetime(row.get("bar_time"))
        if pair is None or bar_time is None:
            continue
        row["bar_time"] = bar_time
        grouped[pair].append(row)
    for bars in grouped.values():
        bars.sort(key=lambda row: _as_datetime(row.get("bar_time")) or datetime.max)
    return dict(grouped)


def _static_candidate(
    manifest: Mapping[str, object],
    feature_row: Mapping[str, object],
    *,
    financial_index: object,
) -> dict[str, object]:
    pair = _row_pair(manifest)
    if pair is None:
        raise ValueError("static candidate identity is unavailable")
    symbol, trade_date = pair
    financial_snapshot = feature_row.get("financial_snapshot")
    if not isinstance(financial_snapshot, Mapping):
        financial_snapshot = financial_snapshot_as_of(
            financial_index,
            symbol,
            trade_date,
        )
    financial_risk = feature_row.get("financial_risk")
    if not isinstance(financial_risk, Mapping):
        financial_risk = financial_risk_as_of(
            financial_index,
            symbol,
            trade_date,
        )
    result = {
        key: _plain_value(feature_row.get(key))
        for key in _STATIC_CANDIDATE_FIELDS
    }
    result.update(
        {
            key: _plain_value(manifest.get(key))
            for key in (
                "stock_d1_sample_count",
                "stock_d1_win_count",
                "stock_d1_win_rate",
                "stock_d1_average_return_pct",
                "stock_gene_combined_win_rate",
            )
        }
    )
    result.update(
        {
            "vt_symbol": symbol,
            "name": str(manifest.get("name") or ""),
            "trade_date": trade_date.isoformat(),
            "signal_date": trade_date.isoformat(),
            "board_lane": "first_board",
            "board_level": 1,
            "target_board": 1,
            "prior_streak": 0,
            "previous_limit_up": bool(manifest.get("prior_day_limit_up")),
            "previous_close": _number(manifest.get("previous_close")),
            "limit_price": _number(manifest.get("limit_price")),
            "financial_snapshot": (
                dict(financial_snapshot)
                if isinstance(financial_snapshot, Mapping)
                else None
            ),
            "financial_risk": dict(financial_risk),
            "risk_gate_passed": financial_risk.get("blocked") is False,
            "universe_gate_passed": manifest.get("eligible_main_board") is not False,
            "signal_kind": "momentum",
            "source_mode": "frozen_v1_complete_one_minute_path",
            "has_l2": False,
        }
    )
    return result


def _candidate_at_time(
    static_candidate: Mapping[str, object],
    manifest: Mapping[str, object],
    bars: Sequence[Mapping[str, object]],
    index: int,
    *,
    path_prefix: Mapping[str, object],
    first_observed_at: datetime,
    transaction: Mapping[str, object] | None,
    environment: Mapping[str, object] | None,
) -> dict[str, object]:
    decision_at = _as_datetime(bars[index].get("bar_time"))
    next_at = _as_datetime(bars[index + 1].get("bar_time"))
    if decision_at is None or next_at is None:
        raise ValueError("minute path contains an invalid decision timestamp")
    previous_close = _number(manifest.get("previous_close"))
    last_price = _number(bars[index].get("close_price"))
    transaction_values = _mapping((transaction or {}).get("values"))
    transaction_ready = bool(
        transaction is not None
        and all(_number(transaction_values.get(name)) is not None for name in TRANSACTION_FEATURE_NAMES)
    )
    candidate = {
        **dict(static_candidate),
        **_environment_candidate_fields(environment),
        "decision_at": decision_at.isoformat(),
        "signal_time": decision_at.time().replace(microsecond=0).isoformat(),
        "evaluation_time": decision_at.time().replace(microsecond=0).isoformat(),
        "entry_window_passed": scheduled_execution.is_entry_time(decision_at.time()),
        "state": "near_limit",
        "capture_state": "pre_radar",
        "action": "observe",
        "last_price": last_price,
        "change_pct": _return_pct(previous_close, last_price),
        "path_prefix": dict(path_prefix),
        "minute_bars": [dict(row) for row in bars[max(index - 7, 0) : index + 1]],
        "candidate_first_observed_at": first_observed_at.isoformat(),
        "next_quote_at": next_at.isoformat(),
        "next_quote_price": _number(bars[index + 1].get("open_price")),
        "transaction_status": "flow_ready" if transaction_ready else "missing",
        "transaction_feature_at": decision_at.isoformat() if transaction_ready else None,
        "transaction_features": transaction_values if transaction_ready else {},
        "snapshot_fresh": _environment_fresh(environment, decision_at),
        "quote_fresh": _quote_fresh(environment, decision_at),
    }
    return apply_preboard_parity_contract(candidate)


def _transaction_index(
    rows: Sequence[Mapping[str, object]],
) -> dict[tuple[str, date, datetime], dict[str, object]]:
    result: dict[tuple[str, date, datetime], dict[str, object]] = {}
    for raw in rows:
        row = raw if isinstance(raw, dict) else dict(raw)
        pair = _row_pair(row)
        bar_time = _local_naive_datetime(row.get("bar_time"))
        if pair is not None and bar_time is not None:
            result[(pair[0], pair[1], bar_time)] = row
    return result


def _environment_index(
    rows: Sequence[Mapping[str, object]],
) -> dict[tuple[str, date], tuple[dict[str, object], ...]]:
    grouped: defaultdict[tuple[str, date], list[dict[str, object]]] = defaultdict(list)
    for raw in rows:
        row = raw if isinstance(raw, dict) else dict(raw)
        pair = _row_pair(row)
        captured_at = _local_naive_datetime(row.get("captured_at"))
        if pair is None or captured_at is None:
            continue
        row["captured_at"] = captured_at
        quote_at = _local_naive_datetime(row.get("quote_observed_at"))
        if quote_at is not None:
            row["quote_observed_at"] = quote_at
        grouped[pair].append(row)
    return {
        pair: tuple(sorted(values, key=lambda row: row["captured_at"]))
        for pair, values in grouped.items()
    }


def _environment_at(
    rows: Sequence[Mapping[str, object]],
    decision_at: datetime,
) -> Mapping[str, object] | None:
    captured = [
        value
        for row in rows
        if (value := _local_naive_datetime(row.get("captured_at"))) is not None
    ]
    position = bisect_right(captured, decision_at) - 1
    return rows[position] if position >= 0 else None


def _environment_candidate_fields(
    environment: Mapping[str, object] | None,
) -> dict[str, object]:
    if environment is None:
        return {}
    fields = (
        "turnover_rate",
        "volume_ratio",
        "concept_id",
        "concept_state",
        "concept_strength_score",
        "concept_leader_rank",
        "concept_strong_5_count",
        "concept_change_acceleration_1m",
        "concept_change_acceleration_3m",
        "concept_change_acceleration_5m",
        "concept_turnover_acceleration_1m",
        "concept_turnover_acceleration_3m",
        "concept_turnover_acceleration_5m",
        "sector_id",
        "sector_heat",
        "sector_touch_count",
        "sector_main_net_inflow",
        "sector_main_net_inflow_ratio",
        "stock_main_net_inflow",
        "stock_main_net_inflow_ratio",
    )
    result = {key: _plain_value(environment.get(key)) for key in fields}
    trade_date = _as_date(environment.get("trade_date"))
    result["sector_flow_current"] = (
        _as_date(environment.get("sector_flow_trade_date")) == trade_date
    )
    return result


def _environment_fresh(
    environment: Mapping[str, object] | None,
    decision_at: datetime,
) -> bool:
    if environment is None or environment.get("is_stale") is not False:
        return False
    captured_at = _local_naive_datetime(environment.get("captured_at"))
    if captured_at is None or captured_at > decision_at:
        return False
    age = (decision_at - captured_at).total_seconds()
    return age <= scheduled_execution.MAX_SNAPSHOT_AGE_SECONDS


def _quote_fresh(
    environment: Mapping[str, object] | None,
    decision_at: datetime,
) -> bool:
    if not _environment_fresh(environment, decision_at):
        return False
    quote_at = _local_naive_datetime((environment or {}).get("quote_observed_at"))
    if quote_at is None or quote_at > decision_at:
        return False
    return (decision_at - quote_at).total_seconds() <= scheduled_execution.MAX_SNAPSHOT_AGE_SECONDS


def _market_gate_from_environment(
    environment: Mapping[str, object] | None,
) -> dict[str, object]:
    explicit = (environment or {}).get("market_gate_passed")
    return preboard_market_gate({
        "passed": explicit is True,
        "source": (
            "point_in_time_market_gate"
            if explicit is not None
            else "unavailable_in_radar_observation_contract"
        ),
    })


def _build_cross_section_snapshots(
    manifests: Mapping[tuple[str, date], Mapping[str, object]],
    bars_by_pair: Mapping[tuple[str, date], Sequence[Mapping[str, object]]],
) -> dict[date, tuple[tuple[datetime, dict[str, object]], ...]]:
    by_date: defaultdict[date, defaultdict[datetime, list[dict[str, object]]]] = (
        defaultdict(lambda: defaultdict(list))
    )
    for pair, bars in bars_by_pair.items():
        manifest = manifests.get(pair)
        if manifest is None:
            continue
        previous_close = _number(manifest.get("previous_close"))
        limit_price = _number(manifest.get("limit_price"))
        if previous_close is None or previous_close <= 0 or limit_price is None:
            continue
        already_touched = False
        for bar in bars:
            captured_at = _as_datetime(bar.get("bar_time"))
            high_price = _number(bar.get("high_price"))
            if captured_at is None:
                continue
            if high_price is not None and high_price >= limit_price - 0.001:
                already_touched = True
            if already_touched:
                continue
            gain = _return_pct(previous_close, _number(bar.get("close_price")))
            if gain is None or gain < 3.0:
                continue
            by_date[pair[1]][captured_at].append(
                {
                    "vt_symbol": pair[0],
                    "gain_pct": gain,
                    "change_pct": gain,
                }
            )

    result: dict[date, tuple[tuple[datetime, dict[str, object]], ...]] = {}
    for trade_date, candidates_by_time in by_date.items():
        times = sorted(
            {
                *candidates_by_time,
                *(
                    captured_at
                    for (symbol, pair_date), bars in bars_by_pair.items()
                    if pair_date == trade_date
                    for row in bars
                    if (captured_at := _as_datetime(row.get("bar_time"))) is not None
                ),
            }
        )
        result[trade_date] = tuple(
            (
                captured_at,
                {
                    "captured_at": captured_at.isoformat(),
                    "candidates": sorted(
                        candidates_by_time.get(captured_at, ()),
                        key=lambda row: (-float(row["gain_pct"]), str(row["vt_symbol"])),
                    ),
                },
            )
            for captured_at in times
        )
    return result


def _formal_orders(
    history_days: Sequence[Mapping[str, object]],
    scoped_days: Sequence[Mapping[str, object]],
    start: date,
    end: date,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    extracted = scheduled_execution.extract_scheduled_orders(scoped_days)
    enriched = attach_prior_stock_gene_evidence_to_orders(history_days, extracted)
    qualified, audit = scheduled_execution.filter_profitability_qualified_orders(enriched)
    return (
        [
            dict(order)
            for order in qualified
            if start
            <= (_as_date(order.get("entry_date")) or date.min)
            <= end
        ],
        dict(audit),
    )


def _manifest_labels(
    manifests: Sequence[Mapping[str, object]],
    minute_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
) -> dict[tuple[date, str], dict[str, object]]:
    formal_first_board_pairs = {
        pair
        for order in formal_orders
        if not _is_relay_order(order)
        and (pair := _row_pair(order)) is not None
    }
    bars_by_pair = _bars_by_pair(minute_rows)
    labels: dict[tuple[date, str], dict[str, object]] = {}
    for raw in manifests:
        manifest = dict(raw)
        pair = _row_pair(manifest)
        if pair is None:
            continue
        limit_price = _number(manifest.get("limit_price"))
        touch_at = next(
            (
                _as_datetime(bar.get("bar_time"))
                for bar in bars_by_pair.get(pair, ())
                if limit_price is not None
                and (_number(bar.get("high_price")) or float("-inf"))
                >= limit_price - 0.001
            ),
            None,
        )
        labels[(pair[1], pair[0])] = {
            "physical_touch_at": touch_at.isoformat() if touch_at else None,
            "formal_baseline_identity": pair in formal_first_board_pairs,
            "sealed_limit": bool(manifest.get("sealed_limit")),
            "d1_close_price": _number(manifest.get("d1_close_price")),
            "result_date": _date_text(
                manifest.get("d1_trade_date") or manifest.get("result_date")
            ),
        }
    return labels


def candidate_index_fingerprint(
    rows_or_pairs: Sequence[Mapping[str, object] | tuple[str, date]],
) -> str:
    """Fingerprint candidate membership without reading any outcome label."""

    pairs: set[tuple[str, date]] = set()
    for value in rows_or_pairs:
        if isinstance(value, tuple) and len(value) == 2:
            symbol = str(value[0]).strip()
            trade_date = _as_date(value[1])
            pair = (symbol, trade_date) if symbol and trade_date is not None else None
        elif isinstance(value, Mapping):
            pair = _row_pair(value)
        else:
            pair = None
        if pair is not None:
            pairs.add(pair)
    payload = [
        {"vt_symbol": symbol, "trade_date": trade_date.isoformat()}
        for symbol, trade_date in sorted(pairs, key=lambda item: (item[1], item[0]))
    ]
    return "sha256:" + sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def _candidate_index_audit(
    path_index: FrozenPreboardPathIndex,
    labels: Mapping[tuple[date, str], Mapping[str, object]],
) -> dict[str, object]:
    membership_rows = [
        {
            "vt_symbol": symbol,
            "trade_date": trade_date.isoformat(),
            **dict(labels.get((trade_date, symbol), {})),
        }
        for symbol, trade_date in path_index.pairs
    ]
    mutated_labels = [
        {
            **row,
            "physical_touch_at": (
                None if row.get("physical_touch_at") else "2099-01-01T10:00:00"
            ),
            "sealed_limit": row.get("sealed_limit") is not True,
            "d1_close_price": None if row.get("d1_close_price") is not None else 1.0,
            "formal_baseline_identity": row.get("formal_baseline_identity") is not True,
        }
        for row in membership_rows
    ]
    fingerprint = candidate_index_fingerprint(membership_rows)
    positive_count = sum(row.get("physical_touch_at") is not None for row in membership_rows)
    return {
        "candidate_index_rule": (
            "label_independent_main_board_mature_prior_non_limit_ge_3pct_upper_bound"
            "_then_static_quality_and_complete_path"
        ),
        "raw_upper_bound_pair_count": path_index.raw_upper_bound_pair_count,
        "complete_minute_path_pair_count": path_index.source_complete_minute_pair_count,
        "static_high_quality_pair_count": path_index.static_high_quality_pair_count,
        "candidate_index_pair_count": len(path_index.pairs),
        "candidate_index_positive_count": positive_count,
        "candidate_index_negative_count": len(path_index.pairs) - positive_count,
        "candidate_index_fingerprint": fingerprint,
        "manifest_input_fingerprint": path_index.input_fingerprint,
        "label_mutation_membership_invariant": bool(
            fingerprint == path_index.candidate_index_fingerprint
            == candidate_index_fingerprint(mutated_labels)
        ),
    }


def _coverage_report(
    path_index: FrozenPreboardPathIndex,
    *,
    rows: Sequence[Mapping[str, object]],
    transaction_rows: Sequence[Mapping[str, object]],
    environment_rows: Sequence[Mapping[str, object]],
    static_scope_audit: Mapping[str, object],
) -> dict[str, object]:
    quality_pairs = {
        pair for row in rows if (pair := _row_pair(row)) is not None
    }
    transaction_pairs = {
        pair for row in transaction_rows if (pair := _row_pair(row)) is not None
    }
    environment_pairs = {
        pair for row in environment_rows if (pair := _row_pair(row)) is not None
    }
    environment_dates = sorted({pair[1] for pair in environment_pairs})
    quality_row_count = len(rows)
    field_coverage = {
        "concept_strength": {
            **_field_coverage(environment_rows, "concept_state"),
            "parity_status": "diagnostic",
            "blocking": False,
        },
        "industry_flow": {
            **_field_coverage(environment_rows, "sector_main_net_inflow"),
            "parity_status": "diagnostic",
            "blocking": False,
        },
        "stock_flow": {
            **_field_coverage(environment_rows, "stock_main_net_inflow"),
            "parity_status": "diagnostic",
            "blocking": False,
        },
        "turnover_rate": {
            **_field_coverage(environment_rows, "turnover_rate"),
            "parity_status": "diagnostic",
            "blocking": False,
        },
        "quote_freshness": {
            "point_count": sum(row.get("quote_fresh") is True for row in rows),
            "quality_point_count": quality_row_count,
            "parity_status": "diagnostic",
            "blocking": False,
        },
        "snapshot_freshness": {
            "point_count": sum(row.get("snapshot_fresh") is True for row in rows),
            "quality_point_count": quality_row_count,
            "parity_status": "diagnostic",
            "blocking": False,
        },
        "market_gate": {
            "point_count": sum(
                "market_gate"
                not in set(row.get("diagnostic_environment_checks") or ())
                for row in rows
            ),
            "quality_point_count": quality_row_count,
            "parity_status": "diagnostic",
            "blocking": False,
            "contract": "diagnostic_until_historical_and_live_semantics_match",
        },
        "risk_gate": {
            "point_count": sum(row.get("risk_gate_passed") is True for row in rows),
            "quality_point_count": quality_row_count,
            "parity_status": "shared",
            "blocking": True,
        },
    }
    return {
        "frozen_path_index": asdict(path_index),
        "one_minute_paths": {
            "pair_count": path_index.minute_complete_pair_count,
            "expected_pair_count": len(path_index.pairs),
            "bar_count_per_pair": 240,
        },
        "transaction_flow": {
            "pair_count": len(transaction_pairs),
            "expected_pair_count": len(path_index.pairs),
            "stored_feature_row_count": len(transaction_rows),
        },
        "quality_pool": {
            "point_count": quality_row_count,
            "pair_count": len(quality_pairs),
            "date_count": len({pair[1] for pair in quality_pairs}),
        },
        "historical_environment": {
            "observation_count": len(environment_rows),
            "pair_count": len(environment_pairs),
            "date_count": len(environment_dates),
            "start_date": environment_dates[0].isoformat() if environment_dates else None,
            "end_date": environment_dates[-1].isoformat() if environment_dates else None,
            "field_coverage": field_coverage,
            "known_at_contract": "environment_observation_at_or_before_decision_at",
        },
        "static_scope": dict(static_scope_audit),
        "survivorship_risk": "current_security_name_and_mixed_industry_membership_proxy",
    }


def _field_coverage(
    rows: Sequence[Mapping[str, object]],
    field: str,
) -> dict[str, object]:
    available = [row for row in rows if row.get(field) not in (None, "")]
    return {
        "observation_count": len(available),
        "date_count": len(
            {
                trade_date
                for row in available
                if (trade_date := _as_date(row.get("trade_date"))) is not None
            }
        ),
        "pair_count": len(
            {pair for row in available if (pair := _row_pair(row)) is not None}
        ),
    }


def _load_market_diagnostics(
    start: date,
    end: date,
    trade_dates: Sequence[date | datetime | str],
) -> dict[str, dict[str, object]]:
    from alphaagent.server.services.limit_up.repository import (
        load_limit_up_dataset,
    )

    source = load_limit_up_dataset(start, end)
    events = _mapping_rows(source.get("events"))
    sentiment_points = _mapping_rows(source.get("sentiment_points"))
    timing_signals = _mapping_rows(source.get("timing_signals"))
    calendar = sorted(
        {
            parsed
            for value in trade_dates
            if (parsed := _as_date(value)) is not None
        }
    )
    calendar_text = [value.isoformat() for value in calendar]
    events_by_date: defaultdict[date, list[dict[str, object]]] = defaultdict(list)
    for event in events:
        trade_date = _as_date(event.get("trade_date"))
        if trade_date is not None:
            events_by_date[trade_date].append(event)

    result: dict[str, dict[str, object]] = {}
    for trade_date in calendar:
        if not start <= trade_date <= end:
            continue
        prior_trade_date = max(
            (value for value in calendar if value < trade_date),
            default=None,
        )
        snapshot = market_snapshot_for_trade(
            trade_date,
            prior_trade_date,
            sentiment_points,
            timing_signals,
            calendar_text,
        )
        day_events = events_by_date.get(trade_date, [])
        sealed_count = sum(event.get("is_sealed") is True for event in day_events)
        failed_count = len(day_events) - sealed_count
        timing = _mapping(snapshot.get("timing"))
        result[trade_date.isoformat()] = {
            "trade_date": trade_date.isoformat(),
            "event_source": "verified_limit_up_and_failed_board_events",
            "touched_count": len(day_events),
            "sealed_count": sealed_count,
            "failed_count": failed_count,
            "failed_rate_pct": _percentage(failed_count, len(day_events)),
            "d1_market_snapshot": snapshot,
            "d1_gold_silver_state": str(timing.get("signal_state") or "NONE"),
            "d1_last_confirmed_direction": timing.get(
                "last_confirmed_direction"
            ),
            "d1_trading_days_since_gold": timing.get(
                "trading_days_since_gold"
            ),
            "d1_trading_days_since_silver": timing.get(
                "trading_days_since_silver"
            ),
        }
    return result


def _pool_audit(
    rows: Sequence[Mapping[str, object]],
    raw_capture_counts: Mapping[str, int],
    raw_capture_symbols: Mapping[str, Sequence[str] | set[str]],
) -> dict[str, object]:
    eligible_by_date: Counter[str] = Counter(
        str(row.get("trade_date") or row.get("signal_date") or "")[:10]
        for row in rows
    )
    eligible_symbols_by_date: defaultdict[str, set[str]] = defaultdict(set)
    for row in rows:
        trade_date = str(row.get("trade_date") or row.get("signal_date") or "")[:10]
        symbol = str(row.get("vt_symbol") or "").strip()
        if trade_date and symbol:
            eligible_symbols_by_date[trade_date].add(symbol)

    # The frozen adapter starts emitting decision rows only after >=3%. It cannot
    # reconstruct a separate below-3% eligible count, so the two layers are equal
    # in this historical dataset and the limitation is reported explicitly.
    quality_by_date = eligible_by_date
    quality_symbols_by_date = eligible_symbols_by_date
    environment_by_date: Counter[str] = Counter(
        str(row.get("trade_date") or row.get("signal_date") or "")[:10]
        for row in rows
        if row.get("execution_environment_passed") is True
    )
    dates = sorted(
        {
            *raw_capture_counts,
            *raw_capture_symbols,
            *eligible_by_date,
            *quality_by_date,
            *environment_by_date,
        }
    )
    daily = [
        {
            "trade_date": trade_date,
            "raw_capture_point_count": int(raw_capture_counts.get(trade_date, 0)),
            "raw_capture_symbol_count": len(
                set(raw_capture_symbols.get(trade_date, ()))
            ),
            "eligible_first_board_point_count": int(
                eligible_by_date.get(trade_date, 0)
            ),
            "eligible_first_board_symbol_count": len(
                eligible_symbols_by_date.get(trade_date, ())
            ),
            "quality_pool_point_count": int(quality_by_date.get(trade_date, 0)),
            "environment_ready_point_count": int(environment_by_date.get(trade_date, 0)),
            "quality_pool_symbol_count": len(
                quality_symbols_by_date.get(trade_date, ())
            ),
        }
        for trade_date in dates
    ]
    return {
        "daily": daily,
        "distributions": {
            field: _distribution([float(row[field]) for row in daily])
            for field in (
                "raw_capture_point_count",
                "raw_capture_symbol_count",
                "eligible_first_board_point_count",
                "eligible_first_board_symbol_count",
                "quality_pool_point_count",
                "environment_ready_point_count",
                "quality_pool_symbol_count",
            )
        },
        "eligible_measurement_contract": (
            "frozen_adapter_begins_at_ge_3pct; eligible_first_board_pool "
            "equals_activated_quality_pool in this historical dataset"
        ),
        "quality_rejection_point_count": max(
            sum(raw_capture_counts.values()) - len(rows),
            0,
        ),
        "environment_rejection_point_count": sum(
            row.get("execution_environment_passed") is not True for row in rows
        ),
        "environment_failure_counts": dict(
            Counter(
                str(reason)
                for row in rows
                for reason in row.get("failed_environment_checks") or ()
            ).most_common()
        ),
    }


def _dataset_fingerprint(
    path_index: FrozenPreboardPathIndex,
    rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
) -> str:
    payload = {
        "manifest_fingerprint": path_index.input_fingerprint,
        "row_features": sorted(
            str(row.get("feature_fingerprint") or "") for row in rows
        ),
        "formal_orders": sorted(
            (
                str(order.get("entry_date") or order.get("signal_date") or ""),
                str(order.get("vt_symbol") or ""),
                str(order.get("lane") or ""),
            )
            for order in formal_orders
        ),
    }
    return "sha256:" + sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def _plain_value(value: object) -> object:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except (TypeError, ValueError):
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except (AttributeError, ValueError):
            return value
    return value


def evaluate_preboard_replay(
    *,
    session_count: int = FROZEN_PATH_SESSION_COUNT,
    end_date: date | None = FROZEN_PATH_END_DATE,
    progress: Callable[[str], None] | None = None,
    publish_research_model: bool = False,
) -> dict[str, object]:
    """Run the one frozen historical study and return its auditable decision."""

    started = monotonic()
    emit = progress or (lambda _message: None)
    dataset = load_frozen_replay_dataset(
        session_count=session_count,
        end_date=end_date,
        progress=emit,
    )
    if dataset.status != "ready":
        return _blocked_report(dataset, started)
    split = split_replay_dates(dataset.dates)
    if len(split.fit) < MINIMUM_FIT_DATES or not split.calibration or not split.validation:
        return _insufficient_report(
            dataset,
            split,
            reason="frozen_date_split_insufficient",
            started=started,
        )

    emit("stage=model_fit")
    model = fit_preboard_model(
        dataset.rows,
        fit_dates=set(split.fit),
        calibration_dates=set(split.calibration),
    )
    scored_rows = score_preboard_rows(model, dataset.rows)
    validation_scored_rows = [
        row
        for row in scored_rows
        if _as_date(row.get("trade_date") or row.get("signal_date"))
        in set(split.validation)
    ]
    emit("stage=probability_qualification")
    probability_qualification = qualify_preboard_probabilities(
        validation_scored_rows
    )
    emit("stage=recent_timing_audit")
    recent_timing = load_recent_live_timing_audit(
        RECENT_TIMING_AUDIT_START,
        RECENT_TIMING_AUDIT_END,
        model_bundle=model,
    )
    if probability_qualification.get("status") != "ready":
        return _probability_rejected_report(
            dataset,
            split,
            model=model,
            scored_rows=scored_rows,
            qualification=probability_qualification,
            recent_timing=recent_timing,
            started=started,
        )
    emit("stage=policy_calibration")
    calibration = calibrate_policy_thresholds(
        scored_rows,
        calibration_dates=set(split.calibration),
        model_fingerprint=model.fingerprint,
        minimum_action_count=MINIMUM_CALIBRATION_ACTIONS,
    )
    if calibration.thresholds is None:
        order_sets = _baseline_only_order_sets(dataset.formal_orders)
    else:
        order_sets = build_replay_order_sets(
            rows=scored_rows,
            thresholds=calibration.thresholds,
            formal_orders=dataset.formal_orders,
        )

    emit("stage=validation_accounts")
    validation_accounts = _phase_accounts(
        order_sets,
        dataset,
        allowed_dates=set(split.validation),
    )
    c_half_hour = _half_hour_report(
        order_sets.get("c_action_rows") or (),
        orders=order_sets.get("c_first_board_orders") or (),
        dataset=dataset,
        allowed_dates=set(split.validation),
    )
    a_half_hour = _half_hour_report(
        order_sets.get("a_first_board_orders") or (),
        orders=order_sets.get("a_first_board_orders") or (),
        dataset=dataset,
        allowed_dates=set(split.validation),
    )
    stability = _stability_report(order_sets, dataset, split.validation)
    strict_action_count = int(
        validation_accounts["c_first_board"].get("filled_count") or 0
    )
    if calibration.thresholds is None:
        promotion = {
            "status": "insufficient_for_portfolio_promotion",
            "passed": False,
            "reason": calibration.status,
            "strict_action_count": strict_action_count,
            "checks": {},
        }
    else:
        promotion = decide_historical_promotion(
            strict_first_board=validation_accounts["c_first_board"],
            formal_first_board=validation_accounts["a_first_board"],
            strict_combined=validation_accounts["c_combined"],
            formal_combined=validation_accounts["a_combined"],
            strict_double_cost=validation_accounts["c_combined_double_cost"],
            positive_stability_blocks=int(stability["positive_block_count"]),
            strict_action_count=strict_action_count,
        )
    if promotion["status"] not in PROMOTION_STATUSES:
        raise ValueError("historical promotion returned an unsupported status")

    report = {
        "study_version": REPLAY_CONTRACT_VERSION,
        "status": promotion["status"],
        "decision": promotion,
        "formal_strategy_changed": False,
        "adversarial_reuse": True,
        "contract": {
            "observation_gain_operator": ">=",
            "observation_gain_pct": 3.0,
            "observation_is_buy_signal": False,
            "quality_pool": "shared_point_in_time_first_board_quality_only",
            "entry": ENTRY_CONTRACT,
            "exit": EXIT_CONTRACT,
            "maximum_first_board_positions": MAXIMUM_FIRST_BOARD_POSITIONS,
            "two_to_three": "unchanged",
        },
        "date_split": _date_split_report(split),
        "dataset": {
            "status": dataset.status,
            "input_fingerprint": dataset.input_fingerprint,
            "quality_point_count": len(dataset.rows),
            "scoreable_point_count": sum(
                row.get("feature_status") == "scoreable" for row in dataset.rows
            ),
            "formal_order_count": len(dataset.formal_orders),
            "coverage": dataset.coverage,
            "candidate_index_audit": dataset.candidate_index_audit,
            "feature_parity_audit": _feature_parity_report(scored_rows, split),
            "pool_audit": dataset.pool_audit,
            "profitability_audit": dataset.profitability_audit,
        },
        "model": _model_report(model, scored_rows, split),
        "calibration": _calibration_report(calibration),
        "validation": {
            "probabilities": probability_qualification,
            "accounts": validation_accounts,
            "stability": stability,
            "identity_and_timing": _decision_quality_report(
                order_sets.get("c_action_rows") or (),
                allowed_dates=set(split.validation),
            ),
            "daily_pools": _daily_pool_report(
                scored_rows,
                order_sets,
                allowed_dates=set(split.validation),
                pool_audit=dataset.pool_audit,
            ),
            "half_hour": c_half_hour,
            "half_hour_by_account": {
                "a_first_board": a_half_hour,
                "c_first_board": c_half_hour,
            },
            "consecutive_losses": _consecutive_loss_report(
                validation_accounts,
                scored_rows,
                market_diagnostics=dataset.market_diagnostics,
                allowed_dates=set(split.validation),
            ),
        },
        "recent_live_timing": recent_timing,
        "limitations": [
            "冻结v1只作为完整路径索引，后来触板、封板和D+1字段只用于标签与结算。",
            "一分钟成交代理无法还原分钟内10秒拉升及委托队列。",
            "市场、概念、行业、个股资金、当前换手与新鲜度尚不能历史实时同源，当前统一只作诊断。",
            "风险、正式窗口、完整分钟与严格板前价格继续按共享合同失败关闭。",
            "后30日已被既有研究查看，因此标记为adversarial_reuse而非全新盲测。",
        ],
        "performance": {"total_seconds": round(monotonic() - started, 3)},
    }
    if publish_research_model:
        report["model_publication"] = preboard_decision_repository.save_decision_model(
            model,
            probability_qualification=probability_qualification,
            historical_promotion_status=str(promotion["status"]),
            thresholds=(
                calibration.thresholds
                if promotion["status"] == "historical_pass_for_shadow"
                else None
            ),
            validation_dates=split.validation,
        )
    return report


def _baseline_only_order_sets(
    formal_orders: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    formal = [dict(order) for order in formal_orders]
    relay = [order for order in formal if _is_relay_order(order)]
    first_board = [order for order in formal if not _is_relay_order(order)]
    return {
        "c_action_pool_rows": [],
        "c_action_rows": [],
        "c_first_board_orders": [],
        "a_first_board_orders": first_board,
        "relay_orders": relay,
        "a_combined_orders": formal,
        "c_combined_orders": [*relay],
    }


def _phase_accounts(
    order_sets: Mapping[str, object],
    dataset: ReplayDataset,
    *,
    allowed_dates: set[date],
) -> dict[str, dict[str, object]]:
    sources = {
        "a_first_board": order_sets.get("a_first_board_orders") or (),
        "c_first_board": order_sets.get("c_first_board_orders") or (),
        "a_combined": order_sets.get("a_combined_orders") or (),
        "c_combined": order_sets.get("c_combined_orders") or (),
    }
    accounts = {
        name: _account_summary(
            _orders_on_dates(orders, allowed_dates),
            dataset,
        )
        for name, orders in sources.items()
    }
    accounts["c_first_board_double_cost"] = _account_summary(
        _orders_on_dates(sources["c_first_board"], allowed_dates),
        dataset,
        cost_multiplier=2.0,
    )
    accounts["c_combined_double_cost"] = _account_summary(
        _orders_on_dates(sources["c_combined"], allowed_dates),
        dataset,
        cost_multiplier=2.0,
    )
    return accounts


def _account_summary(
    orders: Sequence[Mapping[str, object]],
    dataset: ReplayDataset,
    *,
    cost_multiplier: float = 1.0,
) -> dict[str, object]:
    multiplier = max(float(cost_multiplier), 0.0)
    config = CashBacktestConfig(
        initial_cash=100_000.0,
        max_positions=MAX_POSITIONS,
        commission_rate=0.0003 * multiplier,
        minimum_commission=5.0 * multiplier,
        stamp_tax_rate=0.0005 * multiplier,
        transfer_fee_rate=0.00001 * multiplier,
        slippage_bps=10.0 * multiplier,
    )
    account = cash_backtest.simulate_limit_up_account(
        orders,
        dataset.account_bars,
        dataset.trade_dates,
        scheduled_execution.EXIT_MODE,
        config,
    )
    return {
        **dict(account["execution_summary"]),
        "executed_trades": [
            dict(row) for row in account.get("executed_trades") or ()
        ],
    }


def _orders_on_dates(
    orders: Sequence[Mapping[str, object]],
    allowed_dates: set[date],
) -> list[dict[str, object]]:
    return [
        dict(order)
        for order in orders
        if _as_date(
            order.get("entry_date")
            or order.get("signal_date")
            or order.get("trade_date")
        )
        in allowed_dates
    ]


def _stability_report(
    order_sets: Mapping[str, object],
    dataset: ReplayDataset,
    validation_dates: Sequence[date],
) -> dict[str, object]:
    blocks = _fixed_blocks(validation_dates, count=5)
    rows = []
    for index, block in enumerate(blocks, start=1):
        account = _account_summary(
            _orders_on_dates(
                order_sets.get("c_first_board_orders") or (),
                set(block),
            ),
            dataset,
        )
        rows.append(
            {
                "block": index,
                "start_date": block[0].isoformat() if block else None,
                "end_date": block[-1].isoformat() if block else None,
                "date_count": len(block),
                **account,
            }
        )
    return {
        "blocks": rows,
        "positive_block_count": sum(
            (_number(row.get("total_return_pct")) or 0.0) > 0.0 for row in rows
        ),
    }


def _fixed_blocks(values: Sequence[date], *, count: int) -> list[tuple[date, ...]]:
    ordered = tuple(sorted(set(values)))
    if count <= 0:
        raise ValueError("block count must be positive")
    return [
        tuple(
            ordered[
                len(ordered) * index // count : len(ordered) * (index + 1) // count
            ]
        )
        for index in range(count)
    ]


def _model_report(
    model: object,
    rows: Sequence[Mapping[str, object]],
    split: ReplayDateSplit,
) -> dict[str, object]:
    return {
        "status": getattr(model, "status", "unknown"),
        "model_version": getattr(model, "model_version", None),
        "feature_version": getattr(model, "feature_version", None),
        "model_fingerprint": getattr(model, "fingerprint", None),
        "training_input_fingerprint": getattr(
            model,
            "training_input_fingerprint",
            None,
        ),
        "fit_dates": [value.isoformat() for value in split.fit],
        "calibration_dates": [value.isoformat() for value in split.calibration],
        "feature_count": len(getattr(model, "feature_names", ())),
        "heads": getattr(model, "head_reports", {}),
        "probability_status_counts": dict(
            Counter(str(row.get("probability_status") or "unknown") for row in rows)
        ),
    }


def _feature_parity_report(
    rows: Sequence[Mapping[str, object]],
    split: ReplayDateSplit,
) -> dict[str, object]:
    phases = {
        "fit": set(split.fit),
        "calibration": set(split.calibration),
        "validation": set(split.validation),
    }
    fields: dict[str, dict[str, object]] = {}
    for feature_name in MODEL_FEATURE_NAMES:
        phase_reports: dict[str, dict[str, object]] = {}
        for phase, dates in phases.items():
            phase_rows = [
                row
                for row in rows
                if _as_date(row.get("trade_date") or row.get("signal_date"))
                in dates
                and row.get("feature_status") == "scoreable"
            ]
            available_count = sum(
                _number(_mapping(row.get("feature_values")).get(feature_name))
                is not None
                for row in phase_rows
            )
            known_at_legal_count = sum(
                _known_at_is_causal(row) for row in phase_rows
            )
            phase_reports[phase] = {
                "scoreable_point_count": len(phase_rows),
                "available_point_count": available_count,
                "coverage_pct": _percentage(available_count, len(phase_rows)),
                "known_at_legal_point_count": known_at_legal_count,
                "known_at_legal_pct": _percentage(
                    known_at_legal_count,
                    len(phase_rows),
                ),
            }
        fields[feature_name] = {
            "parity_status": "shared",
            "historical_adapter": "project_historical_decision_features",
            "live_adapter": "project_live_decision_features",
            "shared_core": "project_decision_features",
            "phases": phase_reports,
        }
    return {
        "contract": "same_normalized_inputs_same_feature_fingerprint",
        "field_count": len(fields),
        "fields": fields,
    }


def _known_at_is_causal(row: Mapping[str, object]) -> bool:
    known_at = _as_datetime(row.get("known_at"))
    decision_at = _as_datetime(row.get("decision_at"))
    return bool(
        known_at is not None
        and decision_at is not None
        and _local_naive_datetime(known_at) <= _local_naive_datetime(decision_at)
    )


def _calibration_report(calibration: ReplayCalibration) -> dict[str, object]:
    return {
        "status": calibration.status,
        "calibration_dates": [
            value.isoformat() for value in calibration.calibration_dates
        ],
        "thresholds": (
            {
                **asdict(calibration.thresholds),
                "calibrated_dates": [
                    value.isoformat()
                    for value in calibration.thresholds.calibrated_dates
                ],
            }
            if calibration.thresholds is not None
            else None
        ),
        "selected_metrics": calibration.selected_metrics,
        "candidate_threshold_count": len(calibration.metrics_by_threshold),
    }


def _decision_quality_report(
    rows: Sequence[Mapping[str, object]],
    *,
    allowed_dates: set[date],
) -> dict[str, object]:
    actions = [
        row
        for row in rows
        if _as_date(row.get("trade_date") or row.get("signal_date")) in allowed_dates
    ]
    return {
        "action_count": len(actions),
        "fillable_count": sum(row.get("fillable") is True for row in actions),
        "strictly_preboard_count": sum(
            (_number(row.get("signal_price")) or float("inf"))
            < (_number(row.get("limit_price")) or 0.0) - 0.001
            and (_number(row.get("entry_price")) or float("inf"))
            < (_number(row.get("limit_price")) or 0.0) - 0.001
            for row in actions
        ),
        "formal_touch_within_3m_rate_pct": _percentage(
            sum(row.get("formal_touch_within_3m") is True for row in actions),
            len(actions),
        ),
        "eventual_formal_touch_rate_pct": _percentage(
            sum(row.get("eventual_formal_touch") is True for row in actions),
            len(actions),
        ),
        "sealed_rate_pct": _percentage(
            sum(row.get("sealed_limit") is True for row in actions),
            len(actions),
        ),
        "unreached_false_positive_rate_pct": _percentage(
            sum(row.get("eventual_formal_touch") is not True for row in actions),
            len(actions),
        ),
        "d1_win_rate_pct": _percentage(
            sum((_number(row.get("d1_net_return_pct")) or 0.0) > 0.0 for row in actions),
            sum(_number(row.get("d1_net_return_pct")) is not None for row in actions),
        ),
    }


def _daily_pool_report(
    rows: Sequence[Mapping[str, object]],
    order_sets: Mapping[str, object],
    *,
    allowed_dates: set[date],
    pool_audit: Mapping[str, object],
) -> list[dict[str, object]]:
    actions = Counter(
        _as_date(row.get("trade_date") or row.get("signal_date"))
        for row in order_sets.get("c_action_pool_rows") or ()
    )
    fills = Counter(
        _as_date(row.get("entry_date") or row.get("signal_date"))
        for row in order_sets.get("c_first_board_orders") or ()
    )
    audit_by_date = {
        parsed: dict(row)
        for row in _mapping_rows(pool_audit.get("daily"))
        if (parsed := _as_date(row.get("trade_date"))) is not None
    }
    return [
        {
            **audit_by_date.get(trade_date, {}),
            "trade_date": trade_date.isoformat(),
            "raw_capture_symbol_count": int(
                audit_by_date.get(trade_date, {}).get(
                    "raw_capture_symbol_count",
                    0,
                )
            ),
            "eligible_first_board_symbol_count": int(
                audit_by_date.get(trade_date, {}).get(
                    "eligible_first_board_symbol_count",
                    0,
                )
            ),
            "quality_pool_symbol_count": int(
                audit_by_date.get(trade_date, {}).get(
                    "quality_pool_symbol_count",
                    len(
                        {
                            str(row.get("vt_symbol") or "")
                            for row in rows
                            if _as_date(
                                row.get("trade_date") or row.get("signal_date")
                            )
                            == trade_date
                        }
                    ),
                )
            ),
            "action_pool_point_count": int(actions.get(trade_date, 0)),
            "action_pool_count": int(actions.get(trade_date, 0)),
            "filled_pool_count": int(fills.get(trade_date, 0)),
        }
        for trade_date in sorted(allowed_dates)
    ]


def _half_hour_report(
    rows: Sequence[Mapping[str, object]],
    *,
    orders: Sequence[Mapping[str, object]],
    dataset: ReplayDataset,
    allowed_dates: set[date],
) -> list[dict[str, object]]:
    reports: list[dict[str, object]] = []
    for label, start, end in HALF_HOUR_BUCKETS:
        action_rows = [
            row
            for row in rows
            if _row_in_time_bucket(row, start, end, allowed_dates)
        ]
        bucket_orders = [
            row
            for row in orders
            if _row_in_time_bucket(row, start, end, allowed_dates)
        ]
        quality = _decision_quality_report(
            action_rows,
            allowed_dates=allowed_dates,
        )
        account = _account_summary(bucket_orders, dataset)
        reports.append(
            {
                "time_bucket": label,
                "action_count": len(action_rows),
                "strict_fill_count": int(account.get("filled_count") or 0),
                "formal_touch_within_3m_rate_pct": quality.get(
                    "formal_touch_within_3m_rate_pct"
                ),
                "eventual_formal_touch_rate_pct": quality.get(
                    "eventual_formal_touch_rate_pct"
                ),
                "d1_win_rate_pct": account.get("win_rate"),
                "d1_expected_return_pct": account.get("average_return_pct"),
                "cash_compound_return_pct": account.get("total_return_pct"),
            }
        )
    return reports


def _row_in_time_bucket(
    row: Mapping[str, object],
    start: time,
    end: time,
    allowed_dates: set[date],
) -> bool:
    row_date = _as_date(
        row.get("entry_date") or row.get("signal_date") or row.get("trade_date")
    )
    if row_date not in allowed_dates:
        return False
    decision_at = _as_datetime(row.get("decision_at"))
    if decision_at is not None:
        row_time = decision_at.time().replace(tzinfo=None)
    else:
        raw_time = str(row.get("buy_time") or row.get("signal_time") or "")[:8]
        try:
            row_time = time.fromisoformat(raw_time)
        except ValueError:
            return False
    return start <= row_time < end


def _consecutive_loss_report(
    accounts: Mapping[str, Mapping[str, object]],
    quality_rows: Sequence[Mapping[str, object]],
    *,
    market_diagnostics: Mapping[str, Mapping[str, object]],
    allowed_dates: set[date],
) -> dict[str, object]:
    return {
        "a_first_board": _account_loss_runs(
            accounts.get("a_first_board") or {},
            quality_rows,
            market_diagnostics=market_diagnostics,
            allowed_dates=allowed_dates,
        ),
        "c_first_board": _account_loss_runs(
            accounts.get("c_first_board") or {},
            quality_rows,
            market_diagnostics=market_diagnostics,
            allowed_dates=allowed_dates,
        ),
        "classification_contract": {
            "false_positive_occupancy": "selected trade never reached the formal touch baseline",
            "ranking_error": "same-day unselected quality candidate had positive D+1 return",
            "market_style_switch": "same-day verified failed-board rate was at least 40 percent",
            "model_or_execution_error": "loss not explained by the three observable categories",
        },
        "gold_silver_usage": "D-1 diagnostic stratification only; never a validation filter",
    }


def _account_loss_runs(
    account: Mapping[str, object],
    quality_rows: Sequence[Mapping[str, object]],
    *,
    market_diagnostics: Mapping[str, Mapping[str, object]],
    allowed_dates: set[date],
) -> dict[str, object]:
    trades = sorted(
        (
            dict(row)
            for row in _mapping_rows(account.get("executed_trades"))
            if _as_date(row.get("entry_date") or row.get("buy_date"))
            in allowed_dates
        ),
        key=lambda row: (
            str(row.get("entry_date") or row.get("buy_date") or ""),
            str(row.get("buy_time") or ""),
            str(row.get("vt_symbol") or ""),
        ),
    )
    selected_pairs = {
        (
            str(row.get("vt_symbol") or ""),
            _as_date(row.get("entry_date") or row.get("buy_date")),
        )
        for row in trades
    }
    positive_unselected = _positive_unselected_quality_rows(
        quality_rows,
        selected_pairs=selected_pairs,
        allowed_dates=allowed_dates,
    )
    raw_runs: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    maximum = 0
    for trade in trades:
        if (_number(trade.get("return_pct")) or 0.0) < 0:
            current.append(trade)
            maximum = max(maximum, len(current))
            continue
        if len(current) >= 2:
            raw_runs.append(current)
        current = []
    if len(current) >= 2:
        raw_runs.append(current)

    runs = [
        _loss_run_details(
            run,
            positive_unselected=positive_unselected,
            market_diagnostics=market_diagnostics,
        )
        for run in raw_runs
    ]
    return {
        "executed_trade_count": len(trades),
        "loss_trade_count": sum(
            (_number(row.get("return_pct")) or 0.0) < 0 for row in trades
        ),
        "maximum_consecutive_losses": maximum,
        "run_count": len(runs),
        "runs": runs,
    }


def _positive_unselected_quality_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    selected_pairs: set[tuple[str, date | None]],
    allowed_dates: set[date],
) -> dict[date, list[dict[str, object]]]:
    best_by_pair: dict[tuple[str, date], dict[str, object]] = {}
    for row in rows:
        trade_date = _as_date(row.get("trade_date") or row.get("signal_date"))
        symbol = str(row.get("vt_symbol") or "").strip()
        d1_return = _number(row.get("d1_net_return_pct"))
        if (
            trade_date not in allowed_dates
            or not symbol
            or d1_return is None
            or d1_return <= 0
            or (symbol, trade_date) in selected_pairs
        ):
            continue
        pair = (symbol, trade_date)
        previous = best_by_pair.get(pair)
        if previous is None or d1_return > (
            _number(previous.get("d1_net_return_pct")) or float("-inf")
        ):
            best_by_pair[pair] = dict(row)
    result: defaultdict[date, list[dict[str, object]]] = defaultdict(list)
    for (_symbol, trade_date), row in best_by_pair.items():
        result[trade_date].append(
            {
                "vt_symbol": row.get("vt_symbol"),
                "name": row.get("name"),
                "decision_at": row.get("decision_at"),
                "d1_net_return_pct": row.get("d1_net_return_pct"),
                "expected_d1_net_return_pct": row.get(
                    "expected_d1_net_return_pct"
                ),
                "d1_win_probability": row.get("d1_win_probability"),
                "touch_probability_3m": row.get("touch_probability_3m"),
                "eventual_touch_probability": row.get(
                    "eventual_touch_probability"
                ),
            }
        )
    for values in result.values():
        values.sort(
            key=lambda row: (
                -float(_number(row.get("d1_net_return_pct")) or 0.0),
                str(row.get("vt_symbol") or ""),
            )
        )
    return dict(result)


def _loss_run_details(
    trades: Sequence[Mapping[str, object]],
    *,
    positive_unselected: Mapping[date, Sequence[Mapping[str, object]]],
    market_diagnostics: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    trade_dates = sorted(
        {
            parsed
            for row in trades
            if (parsed := _as_date(row.get("entry_date") or row.get("buy_date")))
            is not None
        }
    )
    unselected = [
        dict(row)
        for trade_date in trade_dates
        for row in positive_unselected.get(trade_date, ())
    ]
    markets = [
        dict(market_diagnostics.get(trade_date.isoformat()) or {})
        for trade_date in trade_dates
    ]
    compact_trades = []
    classifications: Counter[str] = Counter()
    for raw in trades:
        trade = dict(raw)
        trade_date = _as_date(trade.get("entry_date") or trade.get("buy_date"))
        same_day_positive = bool(
            trade_date is not None and positive_unselected.get(trade_date)
        )
        market = (
            market_diagnostics.get(trade_date.isoformat(), {})
            if trade_date is not None
            else {}
        )
        if trade.get("eventual_formal_touch") is False:
            classification = "false_positive_occupancy"
        elif same_day_positive:
            classification = "ranking_error"
        elif (_number(market.get("failed_rate_pct")) or 0.0) >= 40.0:
            classification = "market_style_switch"
        else:
            classification = "model_or_execution_error"
        classifications[classification] += 1
        compact_trades.append(
            {
                "entry_date": _date_text(
                    trade.get("entry_date") or trade.get("buy_date")
                ),
                "vt_symbol": trade.get("vt_symbol"),
                "name": trade.get("name"),
                "buy_time": trade.get("buy_time"),
                "entry_price": trade.get("entry_price"),
                "exit_price": trade.get("exit_price"),
                "return_pct": trade.get("return_pct"),
                "eventual_formal_touch": trade.get("eventual_formal_touch"),
                "classification": classification,
            }
        )
    return {
        "start_date": trade_dates[0].isoformat() if trade_dates else None,
        "end_date": trade_dates[-1].isoformat() if trade_dates else None,
        "trade_count": len(trades),
        "classification_counts": dict(classifications),
        "trades": compact_trades,
        "market_environment": markets,
        "unselected_positive_quality_pool": unselected,
    }


def _date_split_report(split: ReplayDateSplit) -> dict[str, object]:
    return {
        name: {
            "date_count": len(values),
            "start_date": values[0].isoformat() if values else None,
            "end_date": values[-1].isoformat() if values else None,
            "dates": [value.isoformat() for value in values],
        }
        for name, values in (
            ("fit", split.fit),
            ("calibration", split.calibration),
            ("validation", split.validation),
        )
    }


def _load_recent_replay_inputs(start: date, end: date) -> RecentReplayInputs:
    """Load a label-independent recent mother pool and causal intraday inputs."""

    from alphaagent.server.services.limit_up import (
        preboard_transaction_data,
        preboard_transaction_repository,
    )
    from alphaagent.server.services.limit_up.preboard_hazard_data import (
        load_one_minute_bars,
        load_one_minute_coverage,
    )

    scope, scope_audit = (
        preboard_transaction_data.load_preboard_decision_static_scope_for_dates(
            start_date=start,
            end_date=end,
        )
    )
    if scope is None:
        return RecentReplayInputs(
            str(scope_audit.get("status") or "static_scope_unavailable"),
            {},
            (),
            (),
            {"static_scope": dict(scope_audit)},
        )
    manifest = scope.minute_manifest.copy()
    manifest_dates = pd.to_datetime(manifest["trade_date"], errors="coerce").dt.date
    manifest = manifest.loc[manifest_dates.between(start, end)].copy()
    if manifest.empty:
        return RecentReplayInputs(
            "empty_recent_static_scope",
            {},
            (),
            (),
            {"static_scope": dict(scope_audit)},
        )
    pairs = {
        (str(row.vt_symbol), _as_date(row.trade_date))
        for row in manifest.itertuples()
    }
    feature_by_pair, financial_index = _filter_static_scope_indexes(
        tuple(pairs),
        scope.feature_by_pair,
        scope.financial_index,
    )
    candidates: dict[tuple[str, date], dict[str, object]] = {}
    for raw in manifest.to_dict(orient="records"):
        pair = _row_pair(raw)
        feature = feature_by_pair.get(pair) if pair is not None else None
        if pair is None or feature is None:
            continue
        candidates[pair] = _static_candidate(
            raw,
            feature,
            financial_index=financial_index,
        )
    history_days = history_repository.load_history_evidence_rows(
        HISTORY_STRATEGY_VERSION,
        end,
    )
    for trade_date, (analog_index, stock_d1_index) in _iter_prior_indexes(
        sorted({pair[1] for pair in candidates}),
        history_days,
    ):
        for pair, candidate in candidates.items():
            if pair[1] != trade_date:
                continue
            candidate["historical_evidence"] = resolve_candidate_historical_evidence(
                {
                    "vt_symbol": pair[0],
                    "entry_kind": "momentum",
                    "target_board": 1,
                },
                candidate,
                {},
                "now",
                trade_date,
                analog_index,
                stock_d1_index,
            )

    candidate_manifest = _frame_for_pairs(manifest, set(candidates))
    coverage = load_one_minute_coverage(candidate_manifest)
    minute_rows = load_one_minute_bars(candidate_manifest)
    transaction_rows = preboard_transaction_repository.load_transaction_features(
        sorted(candidates, key=lambda pair: (pair[1], pair[0])),
        feature_version=TRANSACTION_FEATURE_VERSION,
    )
    coverage_counts = (
        {
            str(key): int(value)
            for key, value in coverage["coverage_status"].value_counts().items()
        }
        if not coverage.empty
        else {}
    )
    return RecentReplayInputs(
        "ready",
        candidates,
        tuple(minute_rows.to_dict(orient="records")),
        tuple(dict(row) for row in transaction_rows),
        {
            "membership_rule": "label_independent_static_quality_scope_before_ge_3_activation",
            "raw_capture_pair_count": int(
                scope_audit.get("raw_capture_pair_count") or 0
            ),
            "prior_only_quality_pair_count": int(
                scope_audit.get("manifest_pair_count") or 0
            ),
            "static_hazard_rejected_pair_count": int(
                scope_audit.get("static_hazard_rejected_pair_count") or 0
            ),
            "static_prefilter_rejected_pair_count": max(
                int(scope_audit.get("manifest_pair_count") or 0) - len(candidates),
                0,
            ),
            "static_candidate_pair_count": len(candidates),
            "minute_coverage_status_counts": coverage_counts,
            "minute_row_count": int(len(minute_rows)),
            "transaction_row_count": len(transaction_rows),
            "static_scope": dict(scope_audit),
        },
        static_pair_audit={
            pair: dict(row) for pair, row in scope.static_pair_audit.items()
        },
    )


def _replay_recent_current_code(
    inputs: RecentReplayInputs,
    observations: Sequence[Mapping[str, object]],
    *,
    model_bundle: object | None,
) -> tuple[dict[str, object], dict[tuple[str, date], dict[str, object]]]:
    """Replay saved recent frames through the current shared quality/model code."""

    if model_bundle is None or inputs.status != "ready" or not inputs.candidates:
        return (
            {
                "status": "not_run" if model_bundle is None else inputs.status,
                **dict(inputs.audit),
            },
            {},
        )

    bars_by_pair = _bars_by_pair(inputs.minute_rows)
    bar_times = {
        pair: [
            value
            for row in rows
            if (value := _local_naive_datetime(row.get("bar_time"))) is not None
        ]
        for pair, rows in bars_by_pair.items()
    }
    prefixes_by_pair = {
        pair: build_lane_prefixes(
            rows,
            previous_close=float(
                _number(inputs.candidates[pair].get("previous_close")) or 0.0
            ),
        )
        for pair, rows in bars_by_pair.items()
        if pair in inputs.candidates
    }
    transaction_by_pair: defaultdict[
        tuple[str, date], list[dict[str, object]]
    ] = defaultdict(list)
    for raw in inputs.transaction_rows:
        row = dict(raw)
        pair = _row_pair(row)
        observed_at = _local_naive_datetime(row.get("bar_time"))
        if pair is None or observed_at is None:
            continue
        row["bar_time"] = observed_at
        transaction_by_pair[pair].append(row)
    transaction_times: dict[tuple[str, date], list[datetime]] = {}
    for pair, rows in transaction_by_pair.items():
        rows.sort(key=lambda row: row["bar_time"])
        transaction_times[pair] = [row["bar_time"] for row in rows]

    frames: defaultdict[datetime, list[dict[str, object]]] = defaultdict(list)
    for raw in observations:
        row = dict(raw)
        pair = _row_pair(row)
        captured_at = _local_naive_datetime(row.get("captured_at"))
        if pair not in inputs.candidates or captured_at is None:
            continue
        row["captured_at"] = captured_at
        frames[captured_at].append(row)

    metrics: defaultdict[tuple[str, date], dict[str, object]] = defaultdict(
        lambda: {
            "quality_point_count": 0,
            "scoreable_point_count": 0,
            "probability_point_count": 0,
            "best_preboard_rank": None,
            "best_touch_probability_rank": None,
        }
    )
    first_observed_at: dict[tuple[str, date], datetime] = {}
    quality_buffer = LiveMinuteBuffer()
    capture_pairs: set[tuple[str, date]] = set()
    eligible_pairs: set[tuple[str, date]] = set()
    quality_pairs: set[tuple[str, date]] = set()
    scoreable_pairs: set[tuple[str, date]] = set()
    probability_pairs: set[tuple[str, date]] = set()
    rejection_counts: Counter[str] = Counter()
    quality_point_count = 0
    scoreable_point_count = 0
    probability_point_count = 0

    for decision_at in sorted(frames):
        visible: list[dict[str, object]] = []
        for environment in sorted(
            frames[decision_at],
            key=lambda row: str(row.get("vt_symbol") or ""),
        ):
            pair = _row_pair(environment)
            static = inputs.candidates.get(pair) if pair is not None else None
            if pair is None or static is None:
                continue
            first_observed_at.setdefault(pair, decision_at)
            rows = bars_by_pair.get(pair, ())
            times = bar_times.get(pair, ())
            bar_position = bisect_right(times, decision_at) - 1
            available_bars = (
                rows[max(bar_position - 7, 0) : bar_position + 1]
                if bar_position >= 0
                else []
            )
            prefixes = prefixes_by_pair.get(pair, ())
            path_prefix = (
                prefixes[bar_position]
                if 0 <= bar_position < len(prefixes)
                else build_lane_prefix(
                    (),
                    0,
                    previous_close=float(
                        _number(static.get("previous_close")) or 0.0
                    ),
                )
            )
            transaction_rows = transaction_by_pair.get(pair, ())
            transaction_position = bisect_right(
                transaction_times.get(pair, ()),
                decision_at,
            ) - 1
            transaction = (
                transaction_rows[transaction_position]
                if transaction_position >= 0
                else None
            )
            transaction_values = _mapping((transaction or {}).get("values"))
            transaction_ready = bool(
                transaction is not None
                and all(
                    _number(transaction_values.get(name)) is not None
                    for name in TRANSACTION_FEATURE_NAMES
                )
            )
            candidate = {
                **dict(static),
                **_environment_candidate_fields(environment),
                "decision_at": decision_at.isoformat(),
                "signal_time": decision_at.time().replace(microsecond=0).isoformat(),
                "evaluation_time": decision_at.time().replace(microsecond=0).isoformat(),
                "entry_window_passed": scheduled_execution.is_entry_time(
                    decision_at.time()
                ),
                "state": str(
                    environment.get("capture_state")
                    or environment.get("state")
                    or "near_limit"
                ),
                "capture_state": str(
                    environment.get("capture_state") or "pre_radar"
                ),
                "action": "observe",
                "last_price": _number(environment.get("last_price")),
                "change_pct": _number(environment.get("change_pct")),
                "turnover_rate": _number(environment.get("turnover_rate")),
                "volume_ratio": _number(environment.get("volume_ratio")),
                "path_prefix": dict(path_prefix),
                "candidate_first_observed_at": first_observed_at[pair].isoformat(),
                "transaction_status": (
                    "flow_ready" if transaction_ready else "missing"
                ),
                "transaction_feature_at": (
                    transaction["bar_time"].isoformat()
                    if transaction_ready and transaction is not None
                    else None
                ),
                "transaction_features": (
                    transaction_values if transaction_ready else {}
                ),
                "snapshot_fresh": _environment_fresh(environment, decision_at),
                "quote_fresh": _quote_fresh(environment, decision_at),
                "_recent_available_bars": available_bars,
            }
            visible.append(apply_preboard_parity_contract(candidate))

        market_gate = _market_gate_from_environment(
            frames[decision_at][0] if frames[decision_at] else None
        )
        pools = build_preboard_pools(
            visible,
            decision_at=decision_at,
            market_gate=market_gate,
        )
        rejection_counts.update(pools.rejection_counts)
        for audit_row in pools.candidate_audit:
            pair = _row_pair(audit_row)
            if pair is not None:
                _update_recent_pool_metrics(
                    metrics[pair],
                    audit_row,
                    decision_at=decision_at,
                )
        capture_pairs.update(
            pair
            for row in pools.capture_pool
            if (pair := _row_pair(row)) is not None
        )
        eligible_pairs.update(
            pair
            for row in pools.eligible_first_board_pool
            if (pair := _row_pair(row)) is not None
        )
        quality_pairs.update(
            pair
            for row in pools.quality_pool
            if (pair := _row_pair(row)) is not None
        )
        quality_buffer.ingest_quality_pool(decision_at, pools.quality_pool)
        cross_sections = quality_buffer.completed_quality_pool_snapshots(decision_at)
        projected_at_frame: list[dict[str, object]] = []
        for quality in pools.quality_pool:
            pair = _row_pair(quality)
            if pair is None:
                continue
            pair_metrics = metrics[pair]
            pair_metrics["quality_point_count"] = int(
                pair_metrics["quality_point_count"]
            ) + 1
            quality_point_count += 1
            available_bars = quality.get("_recent_available_bars")
            available_bars = (
                available_bars
                if isinstance(available_bars, Sequence)
                and not isinstance(available_bars, (str, bytes))
                else ()
            )
            prepared = {
                **dict(quality),
                "candidate": {
                    key: value
                    for key, value in quality.items()
                    if key != "_recent_available_bars"
                },
                "decision_at": decision_at.isoformat(),
                "source_quality": "official_historical_minute",
            }
            projection = project_prepared_historical_decision_features(
                prepared,
                minute_bars=available_bars,
                cross_section_snapshots=cross_sections,
            )
            projected_at_frame.append(
                {
                    **prepared,
                    **projection,
                    "trade_date": pair[1].isoformat(),
                    "signal_date": pair[1].isoformat(),
                }
            )

        scored_at_frame: list[dict[str, object]] = []
        scored_rows = (
            score_preboard_rows(model_bundle, projected_at_frame)
            if projected_at_frame
            else ()
        )
        for scored in scored_rows:
            scored.pop("_recent_available_bars", None)
            pair = _row_pair(scored)
            if pair is None:
                continue
            pair_metrics = metrics[pair]
            if scored.get("feature_status") == "scoreable":
                pair_metrics["scoreable_point_count"] = int(
                    pair_metrics["scoreable_point_count"]
                ) + 1
                pair_metrics.setdefault("first_scoreable_at", decision_at.isoformat())
                scoreable_point_count += 1
                scoreable_pairs.add(pair)
            if scored.get("probability_status") == "ready":
                pair_metrics["probability_point_count"] = int(
                    pair_metrics["probability_point_count"]
                ) + 1
                probability_point_count += 1
                probability_pairs.add(pair)
                pair_metrics.setdefault(
                    "first_probability_ready_at",
                    decision_at.isoformat(),
                )
                _update_recent_probability_peak(
                    pair_metrics,
                    scored,
                    decision_at=decision_at,
                )
                _update_recent_ranking_evidence(pair_metrics, scored)
                scored_at_frame.append(scored)

        product_ranked = sorted(scored_at_frame, key=preboard_action_sort_key)
        for rank, scored in enumerate(product_ranked, start=1):
            pair = _row_pair(scored)
            if pair is None:
                continue
            pair_metrics = metrics[pair]
            best = _integer_or_none(pair_metrics.get("best_preboard_rank"))
            pair_metrics["best_preboard_rank"] = rank if best is None else min(best, rank)
            if rank <= MAX_POSITIONS:
                pair_metrics.setdefault(
                    "first_probability_rank_top2_at",
                    decision_at.isoformat(),
                )
        touch_ranked = sorted(
            scored_at_frame,
            key=lambda row: (
                -float(_number(row.get("touch_probability_3m")) or 0.0),
                -float(_number(row.get("eventual_touch_probability")) or 0.0),
                str(row.get("vt_symbol") or ""),
            ),
        )
        for rank, scored in enumerate(touch_ranked, start=1):
            pair = _row_pair(scored)
            if pair is None:
                continue
            pair_metrics = metrics[pair]
            best = _integer_or_none(
                pair_metrics.get("best_touch_probability_rank")
            )
            pair_metrics["best_touch_probability_rank"] = (
                rank if best is None else min(best, rank)
            )
            if rank <= MAX_POSITIONS:
                pair_metrics.setdefault(
                    "first_touch_probability_rank_top2_at",
                    decision_at.isoformat(),
                )

    observed_pairs = {
        pair
        for row in observations
        if (pair := _row_pair(row)) in inputs.candidates
    }
    fingerprint_payload = [
        {
            "vt_symbol": pair[0],
            "trade_date": pair[1].isoformat(),
        }
        for pair in sorted(inputs.candidates, key=lambda value: (value[1], value[0]))
    ]
    fingerprint = sha256(
        json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    summary = {
        "status": "ready",
        **dict(inputs.audit),
        "candidate_index_fingerprint": f"sha256:{fingerprint}",
        "observed_pair_count": len(observed_pairs),
        "observation_count": sum(len(rows) for rows in frames.values()),
        "capture_pair_count": len(capture_pairs),
        "eligible_pair_count": len(eligible_pairs),
        "quality_pair_count": len(quality_pairs),
        "quality_point_count": quality_point_count,
        "scoreable_pair_count": len(scoreable_pairs),
        "scoreable_point_count": scoreable_point_count,
        "probability_pair_count": len(probability_pairs),
        "probability_point_count": probability_point_count,
        "rejection_counts": dict(rejection_counts.most_common()),
    }
    return summary, {pair: dict(values) for pair, values in metrics.items()}


def _update_recent_pool_metrics(
    metrics: dict[str, object],
    audit_row: Mapping[str, object],
    *,
    decision_at: datetime,
) -> None:
    stage = str(audit_row.get("pool_stage") or "unknown")
    rejection_codes = tuple(
        str(value) for value in audit_row.get("rejection_codes") or ()
    )
    metrics["last_pool_stage"] = stage
    metrics["last_pool_stage_at"] = decision_at.isoformat()
    metrics["last_rejection_codes"] = list(rejection_codes)
    if stage != "capture_rejected":
        metrics.setdefault("first_capture_pool_at", decision_at.isoformat())
    if stage in {
        "eligible_below_observation_floor",
        "eligible_already_touched_or_failed",
        "quality_pool",
    }:
        metrics.setdefault("first_quality_pass_at", decision_at.isoformat())
    change_pct = _number(audit_row.get("change_pct"))
    if change_pct is not None and change_pct >= 3.0:
        metrics.setdefault("first_ge_3_at", decision_at.isoformat())
    if stage == "quality_pool":
        metrics.setdefault("first_quality_pool_at", decision_at.isoformat())
    counts = metrics.setdefault("rejection_counts", {})
    if isinstance(counts, dict):
        for code in rejection_codes:
            counts[code] = int(counts.get(code, 0)) + 1
    if (
        audit_row.get("strictly_preboard") is not True
        or stage == "eligible_already_touched_or_failed"
    ):
        return
    last_price = _number(audit_row.get("last_price"))
    limit_price = _number(audit_row.get("limit_price"))
    if (
        change_pct is None
        or last_price is None
        or limit_price is None
        or last_price >= limit_price - 0.001
    ):
        return
    previous = _number(metrics.get("maximum_replayed_preboard_gain_pct"))
    if previous is not None and change_pct <= previous:
        return
    metrics["maximum_replayed_preboard_gain_pct"] = change_pct
    metrics["maximum_replayed_preboard_gain_at"] = decision_at.isoformat()
    metrics["maximum_replayed_preboard_pool_stage"] = stage
    metrics["maximum_replayed_preboard_rejection_codes"] = list(rejection_codes)
    metrics["maximum_replayed_preboard_hard_blockers"] = list(
        audit_row.get("preboard_hard_blockers") or ()
    )
    metrics["maximum_replayed_preboard_deferred_blockers"] = list(
        audit_row.get("preboard_deferred_blockers") or ()
    )
    metrics["maximum_replayed_preboard_environment_failures"] = list(
        audit_row.get("failed_environment_checks") or ()
    )
    metrics["maximum_replayed_preboard_environment_diagnostics"] = list(
        audit_row.get("diagnostic_environment_checks") or ()
    )


def _update_recent_probability_peak(
    metrics: dict[str, object],
    row: Mapping[str, object],
    *,
    decision_at: datetime,
) -> None:
    for probability_field, metric_name in (
        ("touch_probability_3m", "best_touch_probability_3m"),
        ("eventual_touch_probability", "best_eventual_touch_probability"),
    ):
        value = _number(row.get(probability_field))
        previous = _number(metrics.get(metric_name))
        if value is None or (previous is not None and value <= previous):
            continue
        metrics[metric_name] = value
        metrics[f"{metric_name}_at"] = decision_at.isoformat()


def _update_recent_ranking_evidence(
    metrics: dict[str, object],
    row: Mapping[str, object],
) -> None:
    """Keep the prior-only values that explain product ordering."""

    for field_name in (
        "expected_d1_net_return_pct",
        "d1_win_probability",
        "seal_probability_given_touch",
        "d1_win_probability_given_seal",
        "lane_support_score",
    ):
        value = _number(row.get(field_name))
        if value is not None:
            metrics[field_name] = value


def _integer_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def load_recent_live_timing_audit(
    start: date,
    end: date,
    *,
    model_bundle: object | None = None,
) -> dict[str, object]:
    from alphaagent.server.services.limit_up import (
        preboard_decision_repository,
        radar_observation_repository,
    )

    formal_orders = _recent_formal_baseline_orders(start, end)
    formal_by_pair = {
        pair: dict(order)
        for order in formal_orders
        if not _is_relay_order(order)
        and (pair := _row_pair(order)) is not None
    }
    frames = radar_observation_repository.load_frames(start, end)
    selected_at: dict[tuple[str, date], datetime] = {}
    for frame in frames:
        captured_at = _local_naive_datetime(frame.get("captured_at"))
        trade_date = _as_date(frame.get("trade_date"))
        symbols = frame.get("formal_two_slot_symbols")
        if (
            captured_at is None
            or trade_date is None
            or frame.get("formal_two_slot_observed") is not True
            or not isinstance(symbols, Sequence)
            or isinstance(symbols, (str, bytes))
        ):
            continue
        for symbol in symbols:
            pair = (str(symbol), trade_date)
            selected_at.setdefault(pair, captured_at)
    old_action_pairs = {
        pair
        for row in radar_observation_repository.load_action_observation_pairs(
            start,
            end,
        )
        if (pair := _row_pair(row)) is not None
    }
    actions = preboard_decision_repository.load_decision_actions(
        start=start,
        end=end,
    )
    current_action_pairs = {
        pair for row in actions if (pair := _row_pair(row)) is not None
    }
    replay_inputs = (
        _load_recent_replay_inputs(start, end)
        if model_bundle is not None
        else RecentReplayInputs("not_run", {}, (), (), {})
    )
    scope_pairs = (
        set(formal_by_pair)
        | set(selected_at)
        | old_action_pairs
        | current_action_pairs
        | set(replay_inputs.candidates)
        | set(replay_inputs.static_pair_audit)
    )
    query_symbols = sorted({pair[0] for pair in scope_pairs})
    if not query_symbols:
        return {
            "status": "unavailable",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "formal_positive_count": 0,
            "queried_symbol_count": 0,
            "observation_count": 0,
            "active_feature_row_count": 0,
            "active_shadow_action_count": len(actions),
            "selected_pair_count": 0,
            "selected_already_touched_count": 0,
            "rows": [],
        }
    observations = radar_observation_repository.load_observations(
        start,
        end,
        symbols=query_symbols,
    )
    scope_dates = sorted({pair[1] for pair in scope_pairs})
    feature_rows = preboard_decision_repository.load_decision_feature_rows(
        scope_dates,
        symbols=query_symbols,
    )
    replay_summary, replay_by_pair = _replay_recent_current_code(
        replay_inputs,
        observations,
        model_bundle=model_bundle,
    )
    grouped: defaultdict[tuple[str, date], list[dict[str, object]]] = defaultdict(list)
    for raw in observations:
        row = dict(raw)
        pair = _row_pair(row)
        if pair in scope_pairs:
            grouped[pair].append(row)
    features_by_pair: defaultdict[
        tuple[str, date], list[dict[str, object]]
    ] = defaultdict(list)
    for raw in feature_rows:
        row = dict(raw)
        pair = _row_pair(row)
        if pair in scope_pairs:
            features_by_pair[pair].append(row)
    actions_by_pair: defaultdict[
        tuple[str, date], list[dict[str, object]]
    ] = defaultdict(list)
    for raw in actions:
        row = dict(raw)
        pair = _row_pair(row)
        if pair in scope_pairs:
            actions_by_pair[pair].append(row)
    rows = []
    for pair in sorted(scope_pairs, key=lambda value: (value[1], value[0])):
        formal_order = formal_by_pair.get(pair)
        static_audit = replay_inputs.static_pair_audit.get(pair, {})
        formal_touch_at = _formal_order_touch_at(formal_order or {})
        observations_for_pair = sorted(
            grouped.get(pair, ()),
            key=lambda row: _local_naive_datetime(row.get("captured_at"))
            or datetime.max,
        )
        features_for_pair = sorted(
            features_by_pair.get(pair, ()),
            key=lambda row: _local_naive_datetime(row.get("decision_at"))
            or datetime.max,
        )
        actions_for_pair = sorted(
            actions_by_pair.get(pair, ()),
            key=lambda row: _local_naive_datetime(
                row.get("captured_at") or row.get("decision_at")
            )
            or datetime.max,
        )
        first_capture = observations_for_pair[0] if observations_for_pair else None
        replayed = replay_by_pair.get(pair, {})
        first_ge_3 = next(
            (row for row in observations_for_pair if (_number(row.get("change_pct")) or 0.0) >= 3.0),
            None,
        )
        first_scoreable = next(
            (
                row
                for row in features_for_pair
                if row.get("feature_status") == "scoreable"
            ),
            None,
        )
        first_probability_gate = next(
            (
                row
                for row in features_for_pair
                if row.get("probability_status") == "ready"
                and str(row.get("decision_state") or "")
                in {"prepare", "actionable"}
            ),
            None,
        )
        first_shadow_action = actions_for_pair[0] if actions_for_pair else None
        first_action = next(
            (row for row in observations_for_pair if row.get("formal_action") == "buy_now"),
            None,
        )
        first_touch = next(
            (
                row
                for row in observations_for_pair
                if str(row.get("capture_state") or "")
                in {"sealed", "resealed", "failed"}
                or (
                    (_number(row.get("last_price")) or 0.0)
                    >= (_number(row.get("limit_price")) or float("inf")) - 0.001
                )
            ),
            None,
        )
        observed_touch_at = _local_naive_datetime(
            (first_touch or {}).get("captured_at")
        )
        touch_at = formal_touch_at or observed_touch_at
        preboard_observations = [
            row
            for row in observations_for_pair
            if _is_observation_strictly_preboard(row)
            and (
                touch_at is None
                or (
                    (captured_at := _local_naive_datetime(row.get("captured_at")))
                    is not None
                    and captured_at < touch_at
                )
            )
        ]
        last_preboard = (
            preboard_observations[-1] if preboard_observations else None
        )
        last_preboard_at = _local_naive_datetime(
            (last_preboard or {}).get("captured_at")
        )
        last_feature = next(
            (
                row
                for row in reversed(features_for_pair)
                if touch_at is None
                or (
                    (feature_at := _local_naive_datetime(row.get("decision_at")))
                    is not None
                    and feature_at < touch_at
                )
            ),
            None,
        )
        selection_at = selected_at.get(pair)
        action_at = _local_naive_datetime((first_action or {}).get("captured_at"))
        shadow_at = _local_naive_datetime(
            (first_shadow_action or {}).get("captured_at")
            or (first_shadow_action or {}).get("decision_at")
        )
        probability_rank_at = _local_naive_datetime(
            replayed.get("first_probability_rank_top2_at")
        )
        touch_probability_rank_at = _local_naive_datetime(
            replayed.get("first_touch_probability_rank_top2_at")
        )
        if selection_at is not None and touch_at is not None and touch_at <= selection_at:
            classification = "already_touched_when_selected"
        elif formal_order is not None and last_preboard is None:
            classification = "formal_positive_without_saved_preboard_frame"
        elif touch_at is None:
            classification = "selected_or_observed_without_later_touch"
        else:
            classification = "preboard_then_touch"
        source = (
            formal_order
            or last_preboard
            or first_shadow_action
            or first_scoreable
            or first_action
            or first_touch
            or first_ge_3
            or static_audit
            or {}
        )
        gate_matrix = _recent_gate_matrix(
            formal_order=formal_order,
            last_preboard=last_preboard,
            last_feature=last_feature,
            selection_at=selection_at,
            replayed=replayed,
            static_audit=static_audit,
        )
        blockers = _recent_timing_blockers(
            observations_for_pair,
            features_for_pair,
            actions_for_pair,
        )
        blockers = list(
            dict.fromkeys(
                [
                    *blockers,
                    *(
                        [str(static_audit.get("static_hazard_gate_reason"))]
                        if static_audit
                        and static_audit.get("static_hazard_gate_passed") is not True
                        else []
                    ),
                    *(
                        str(item["code"])
                        for item in gate_matrix
                        if item.get("status") in {"failed", "unavailable"}
                    ),
                ]
            )
        )
        preboard_blocker_counts = Counter(
            str(value)
            for observation in preboard_observations
            for field in ("lane_blocker_codes", "blocker_codes")
            for value in observation.get(field) or ()
        )
        if formal_touch_at is None or action_at is None:
            old_buy_timing = "missing"
        elif action_at < formal_touch_at:
            old_buy_timing = "preboard"
        else:
            old_buy_timing = "at_or_after_touch"
        rows.append(
            {
                "trade_date": pair[1].isoformat(),
                "vt_symbol": pair[0],
                "name": source.get("name"),
                "formal_baseline_positive": formal_order is not None,
                "current_static_candidate": pair in replay_inputs.candidates,
                "static_hazard_gate_passed": static_audit.get(
                    "static_hazard_gate_passed"
                ),
                "static_hazard_gate_reason": static_audit.get(
                    "static_hazard_gate_reason"
                ),
                "static_prior_evidence": {
                    field_name: static_audit.get(field_name)
                    for field_name in (
                        "stock_d1_sample_count",
                        "stock_d1_win_rate",
                        "stock_d1_average_return_pct",
                        "stock_gene_combined_win_rate",
                    )
                },
                "formal_touch_at": (
                    formal_touch_at.isoformat() if formal_touch_at else None
                ),
                "first_capture_pool_at": _datetime_text(
                    replayed.get("first_capture_pool_at")
                ),
                "first_saved_observation_at": _datetime_text(
                    (first_capture or {}).get("captured_at")
                ),
                "first_quality_pass_at": _datetime_text(
                    replayed.get("first_quality_pass_at")
                ),
                "first_ge_3_at": _datetime_text(
                    replayed.get("first_ge_3_at")
                    or (first_ge_3 or {}).get("captured_at")
                ),
                "first_quality_pool_at": _datetime_text(
                    replayed.get("first_quality_pool_at")
                ),
                "first_scoreable_at": _datetime_text(
                    replayed.get("first_scoreable_at")
                    or (first_scoreable or {}).get("decision_at")
                ),
                "first_probability_gate_at": _datetime_text(
                    (first_probability_gate or {}).get("decision_at")
                ),
                "first_shadow_action_at": (
                    shadow_at.isoformat() if shadow_at is not None else None
                ),
                "first_probability_ready_at": _datetime_text(
                    replayed.get("first_probability_ready_at")
                ),
                "first_probability_rank_top2_at": replayed.get(
                    "first_probability_rank_top2_at"
                ),
                "first_touch_probability_rank_top2_at": replayed.get(
                    "first_touch_probability_rank_top2_at"
                ),
                "best_preboard_rank": replayed.get("best_preboard_rank"),
                "best_touch_probability_rank": replayed.get(
                    "best_touch_probability_rank"
                ),
                "best_touch_probability_3m": replayed.get(
                    "best_touch_probability_3m"
                ),
                "best_touch_probability_3m_at": replayed.get(
                    "best_touch_probability_3m_at"
                ),
                "best_eventual_touch_probability": replayed.get(
                    "best_eventual_touch_probability"
                ),
                "best_eventual_touch_probability_at": replayed.get(
                    "best_eventual_touch_probability_at"
                ),
                "expected_d1_net_return_pct": replayed.get(
                    "expected_d1_net_return_pct"
                ),
                "d1_win_probability": replayed.get("d1_win_probability"),
                "seal_probability_given_touch": replayed.get(
                    "seal_probability_given_touch"
                ),
                "replayed_quality_point_count": replayed.get(
                    "quality_point_count",
                    0,
                ),
                "replayed_scoreable_point_count": replayed.get(
                    "scoreable_point_count",
                    0,
                ),
                "current_code_rejection_counts": replayed.get(
                    "rejection_counts",
                    {},
                ),
                "maximum_replayed_preboard_gain_pct": replayed.get(
                    "maximum_replayed_preboard_gain_pct"
                ),
                "maximum_replayed_preboard_gain_at": replayed.get(
                    "maximum_replayed_preboard_gain_at"
                ),
                "maximum_replayed_preboard_pool_stage": replayed.get(
                    "maximum_replayed_preboard_pool_stage"
                ),
                "maximum_replayed_preboard_rejection_codes": replayed.get(
                    "maximum_replayed_preboard_rejection_codes",
                    [],
                ),
                "maximum_replayed_preboard_hard_blockers": replayed.get(
                    "maximum_replayed_preboard_hard_blockers",
                    [],
                ),
                "maximum_replayed_preboard_deferred_blockers": replayed.get(
                    "maximum_replayed_preboard_deferred_blockers",
                    [],
                ),
                "maximum_replayed_preboard_environment_failures": replayed.get(
                    "maximum_replayed_preboard_environment_failures",
                    [],
                ),
                "maximum_replayed_preboard_environment_diagnostics": replayed.get(
                    "maximum_replayed_preboard_environment_diagnostics",
                    [],
                ),
                "first_old_buy_now_at": _datetime_text(
                    (first_action or {}).get("captured_at")
                ),
                "first_old_buy_now_gain_pct": _number(
                    (first_action or {}).get("change_pct")
                ),
                "physical_touch_at": touch_at.isoformat() if touch_at else None,
                "observed_physical_touch_at": _datetime_text(
                    (first_touch or {}).get("captured_at")
                ),
                "last_preboard_at": (
                    last_preboard_at.isoformat() if last_preboard_at else None
                ),
                "last_preboard_gain_pct": _number(
                    (last_preboard or {}).get("change_pct")
                ),
                "maximum_preboard_gain_pct": max(
                    (
                        gain
                        for row in preboard_observations
                        if (gain := _number(row.get("change_pct"))) is not None
                    ),
                    default=None,
                ),
                "last_preboard_support_score": _number(
                    (last_preboard or {}).get("support_score")
                ),
                "last_preboard_concept_state": (last_preboard or {}).get(
                    "concept_state"
                ),
                "last_preboard_concept_leader_rank": (last_preboard or {}).get(
                    "concept_leader_rank"
                ),
                "last_preboard_sector_main_net_inflow": _number(
                    (last_preboard or {}).get("sector_main_net_inflow")
                ),
                "last_preboard_stock_main_net_inflow": _number(
                    (last_preboard or {}).get("stock_main_net_inflow")
                ),
                "last_preboard_turnover_rate": _number(
                    (last_preboard or {}).get("turnover_rate")
                ),
                "last_preboard_lane_blockers": list(
                    (last_preboard or {}).get("lane_blocker_codes") or ()
                ),
                "last_preboard_execution_blockers": list(
                    (last_preboard or {}).get("blocker_codes") or ()
                ),
                "preboard_blocker_counts": dict(
                    preboard_blocker_counts.most_common()
                ),
                "first_portfolio_at": selection_at.isoformat() if selection_at else None,
                "old_buy_timing": old_buy_timing,
                "formal_touch_lead_seconds": (
                    round((formal_touch_at - last_preboard_at).total_seconds(), 3)
                    if formal_touch_at is not None and last_preboard_at is not None
                    else None
                ),
                "old_action_lead_seconds": (
                    round((touch_at - action_at).total_seconds(), 3)
                    if touch_at is not None and action_at is not None
                    else None
                ),
                "shadow_action_lead_seconds": (
                    round((touch_at - shadow_at).total_seconds(), 3)
                    if touch_at is not None and shadow_at is not None
                    else None
                ),
                "probability_rank_top2_lead_seconds": (
                    round((touch_at - probability_rank_at).total_seconds(), 3)
                    if touch_at is not None and probability_rank_at is not None
                    else None
                ),
                "touch_probability_rank_top2_lead_seconds": (
                    round(
                        (touch_at - touch_probability_rank_at).total_seconds(),
                        3,
                    )
                    if touch_at is not None
                    and touch_probability_rank_at is not None
                    else None
                ),
                "block_reasons": blockers,
                "gate_matrix": gate_matrix,
                "classification": classification,
            }
        )
    selected_rows = [row for row in rows if row.get("first_portfolio_at")]
    return {
        "status": "ready" if rows else "unavailable",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "formal_positive_count": len(formal_by_pair),
        "formal_positive_with_preboard_count": sum(
            row.get("formal_baseline_positive") is True
            and row.get("last_preboard_at") is not None
            for row in rows
        ),
        "formal_positive_old_buy_preboard_count": sum(
            row.get("formal_baseline_positive") is True
            and row.get("old_buy_timing") == "preboard"
            for row in rows
        ),
        "queried_symbol_count": len(query_symbols),
        "observation_count": len(observations),
        "active_feature_row_count": len(feature_rows),
        "active_shadow_action_count": len(actions),
        "current_code_replay": replay_summary,
        "selected_pair_count": len(selected_rows),
        "selected_already_touched_count": sum(
            row["classification"] == "already_touched_when_selected"
            for row in selected_rows
        ),
        "rows": rows,
    }


def _recent_formal_baseline_orders(
    start: date,
    end: date,
) -> list[dict[str, object]]:
    history_days = history_repository.load_history_range(
        HISTORY_STRATEGY_VERSION,
        None,
        end,
        False,
    )
    scoped_days = [
        row
        for row in history_days
        if start
        <= (_as_date(row.get("trade_date")) or date.min)
        <= end
    ]
    orders, _audit = _formal_orders(history_days, scoped_days, start, end)
    return [dict(order) for order in orders if not _is_relay_order(order)]


def _formal_order_touch_at(order: Mapping[str, object]) -> datetime | None:
    trade_date = _as_date(
        order.get("entry_date")
        or order.get("signal_date")
        or order.get("trade_date")
    )
    raw_time = str(
        order.get("buy_time")
        or order.get("signal_time")
        or order.get("first_limit_time")
        or ""
    )[:8]
    if trade_date is None or not raw_time:
        return None
    try:
        return datetime.combine(trade_date, time.fromisoformat(raw_time))
    except ValueError:
        return None


def _is_observation_strictly_preboard(row: Mapping[str, object]) -> bool:
    if str(row.get("capture_state") or "") in {"sealed", "resealed", "failed"}:
        return False
    last_price = _number(row.get("last_price"))
    limit_price = _number(row.get("limit_price"))
    return bool(
        last_price is not None
        and limit_price is not None
        and last_price < limit_price - 0.001
    )


def _recent_gate_matrix(
    *,
    formal_order: Mapping[str, object] | None,
    last_preboard: Mapping[str, object] | None,
    last_feature: Mapping[str, object] | None,
    selection_at: datetime | None,
    replayed: Mapping[str, object],
    static_audit: Mapping[str, object],
) -> list[dict[str, object]]:
    observation = last_preboard or {}
    feature = last_feature or {}
    blockers = {
        str(value)
        for field in ("lane_blocker_codes", "blocker_codes")
        for value in observation.get(field) or ()
    }
    blockers.update(
        str(value)
        for value in replayed.get("maximum_replayed_preboard_hard_blockers") or ()
    )
    lane_blockers = {
        str(value) for value in observation.get("lane_blocker_codes") or ()
    }
    lane_blockers.update(
        str(value)
        for value in replayed.get("maximum_replayed_preboard_rejection_codes") or ()
        if str(value) not in {"below_observation_floor", "already_touched_or_failed"}
    )
    sample_count = _number(
        static_audit.get("stock_d1_sample_count")
        if static_audit.get("stock_d1_sample_count") is not None
        else observation.get("history_sample_count")
    )
    combined_rate = _number(
        static_audit.get("stock_gene_combined_win_rate")
        if static_audit.get("stock_gene_combined_win_rate") is not None
        else observation.get("historical_combined_rate")
    )
    if sample_count is None or combined_rate is None:
        profitability_status = "unknown"
    elif (
        sample_count >= scheduled_execution.FIRST_BOARD_MIN_D1_SAMPLES
        and combined_rate >= scheduled_execution.FIRST_BOARD_MIN_COMBINED_RATE
    ):
        profitability_status = "passed"
    else:
        profitability_status = "failed"
    support_score = _number(
        replayed.get("lane_support_score")
        if replayed.get("lane_support_score") is not None
        else observation.get("support_score")
    )
    if "stock_momentum" in blockers or (
        support_score is not None
        and support_score < FIRST_BOARD_MOMENTUM_MIN_SCORE
    ):
        momentum_status = "failed"
    elif support_score is not None:
        momentum_status = "passed"
    else:
        momentum_status = "unknown"

    def execution_status(code: str, observed_fields: Sequence[str]) -> str:
        if code in blockers:
            return "failed"
        if any(observation.get(field) is not None for field in observed_fields):
            return "passed"
        return "unknown"

    feature_status = (
        "scoreable"
        if int(replayed.get("scoreable_point_count") or 0) > 0
        else str(feature.get("feature_status") or "")
    )
    probability_status = (
        "ready"
        if int(replayed.get("probability_point_count") or 0) > 0
        else str(feature.get("probability_status") or "")
    )
    touch_probability = _number(
        replayed.get("best_touch_probability_3m")
        if replayed.get("best_touch_probability_3m") is not None
        else feature.get("touch_probability_3m")
    )
    eventual_probability = _number(
        replayed.get("best_eventual_touch_probability")
        if replayed.get("best_eventual_touch_probability") is not None
        else feature.get("eventual_touch_probability")
    )
    d1_expected = _number(
        replayed.get("expected_d1_net_return_pct")
        if replayed.get("expected_d1_net_return_pct") is not None
        else feature.get("expected_d1_net_return_pct")
    )
    d1_win = _number(
        replayed.get("d1_win_probability")
        if replayed.get("d1_win_probability") is not None
        else feature.get("d1_win_probability")
    )
    return [
        {
            "code": "formal_baseline_quality",
            "status": "passed" if formal_order is not None else "not_applicable",
            "observed": (formal_order or {}).get("decision"),
        },
        {
            "code": "strict_preboard_price",
            "status": (
                "passed"
                if last_preboard is not None
                and _is_observation_strictly_preboard(last_preboard)
                else "failed"
                if formal_order is not None
                else "unknown"
            ),
            "observed": _number(observation.get("last_price")),
            "required": "last_price < limit_price",
        },
        {
            "code": "profitability_gate",
            "status": profitability_status,
            "observed": {
                "sample_count": sample_count,
                "combined_rate": combined_rate,
            },
        },
        {
            "code": "lane_quality",
            "status": (
                "failed"
                if lane_blockers
                else "passed"
                if last_preboard is not None
                else "unknown"
            ),
            "observed": sorted(lane_blockers),
        },
        {
            "code": "stock_momentum",
            "status": momentum_status,
            "observed": support_score,
            "required": f">={FIRST_BOARD_MOMENTUM_MIN_SCORE:g}",
        },
        {
            "code": "sector_route",
            "status": execution_status(
                "sector_route",
                ("concept_state", "sector_main_net_inflow"),
            ),
            "observed": {
                "concept_state": observation.get("concept_state"),
                "concept_leader_rank": observation.get("concept_leader_rank"),
                "sector_main_net_inflow": _number(
                    observation.get("sector_main_net_inflow")
                ),
            },
        },
        {
            "code": "stock_flow",
            "status": execution_status(
                "stock_flow",
                ("stock_main_net_inflow", "stock_main_net_inflow_ratio"),
            ),
            "observed": _number(observation.get("stock_main_net_inflow")),
        },
        {
            "code": "turnover_rate",
            "status": execution_status("turnover_rate", ("turnover_rate",)),
            "observed": _number(observation.get("turnover_rate")),
        },
        {
            "code": "completed_minute_features",
            "status": "passed" if feature_status == "scoreable" else "failed",
            "observed": feature_status or "not_collected",
        },
        {
            "code": "touch_probability_3m",
            "status": (
                "passed"
                if probability_status == "ready" and touch_probability is not None
                else "unavailable"
            ),
            "observed": touch_probability,
        },
        {
            "code": "eventual_touch_probability",
            "status": (
                "passed"
                if probability_status == "ready" and eventual_probability is not None
                else "unavailable"
            ),
            "observed": eventual_probability,
        },
        {
            "code": "d1_priority",
            "status": (
                "passed"
                if d1_expected is not None and d1_win is not None
                else "unavailable"
            ),
            "observed": {
                "expected_return_pct": d1_expected,
                "win_probability": d1_win,
            },
        },
        {
            "code": "two_slot",
            "status": "passed" if selection_at is not None else "not_selected",
            "observed": selection_at.isoformat() if selection_at else None,
        },
        {
            "code": "current_product_rank_top2",
            "status": (
                "passed"
                if replayed.get("first_probability_rank_top2_at") is not None
                else "not_selected"
            ),
            "observed": replayed.get("first_probability_rank_top2_at"),
        },
        {
            "code": "current_touch_probability_rank_top2",
            "status": (
                "passed"
                if replayed.get("first_touch_probability_rank_top2_at") is not None
                else "not_selected"
            ),
            "observed": replayed.get("first_touch_probability_rank_top2_at"),
        },
    ]


def _recent_timing_blockers(
    observations: Sequence[Mapping[str, object]],
    feature_rows: Sequence[Mapping[str, object]],
    actions: Sequence[Mapping[str, object]],
) -> list[str]:
    if not feature_rows:
        return ["active_shared_decision_not_collected_on_date"]
    reasons: list[str] = []
    if not any(row.get("quality_gate_passed") is True for row in feature_rows):
        reasons.append("quality_gate_not_passed")
    if not any(row.get("feature_status") == "scoreable" for row in feature_rows):
        statuses = sorted(
            {str(row.get("feature_status") or "unknown") for row in feature_rows}
        )
        reasons.extend(f"feature_status:{status}" for status in statuses)
    if not any(row.get("probability_status") == "ready" for row in feature_rows):
        statuses = sorted(
            {str(row.get("probability_status") or "unknown") for row in feature_rows}
        )
        reasons.extend(f"probability_status:{status}" for status in statuses)
    if not actions:
        reasons.append("no_shadow_action")
        reasons.extend(
            str(reason)
            for row in feature_rows
            for reason in row.get("failed_environment_checks") or ()
        )
    if observations and not reasons:
        reasons.append("two_slot_or_probability_threshold_not_reached")
    return list(dict.fromkeys(reasons))


def _blocked_report(dataset: ReplayDataset, started: float) -> dict[str, object]:
    return {
        "study_version": REPLAY_CONTRACT_VERSION,
        "status": "insufficient_for_portfolio_promotion",
        "decision": {
            "status": "insufficient_for_portfolio_promotion",
            "passed": False,
            "reason": dataset.status,
        },
        "formal_strategy_changed": False,
        "dataset": {
            "status": dataset.status,
            "coverage": dataset.coverage,
            "input_fingerprint": dataset.input_fingerprint,
        },
        "performance": {"total_seconds": round(monotonic() - started, 3)},
    }


def _insufficient_report(
    dataset: ReplayDataset,
    split: ReplayDateSplit,
    *,
    reason: str,
    started: float,
) -> dict[str, object]:
    return {
        "study_version": REPLAY_CONTRACT_VERSION,
        "status": "insufficient_for_portfolio_promotion",
        "decision": {
            "status": "insufficient_for_portfolio_promotion",
            "passed": False,
            "reason": reason,
        },
        "formal_strategy_changed": False,
        "date_split": _date_split_report(split),
        "dataset": {
            "status": dataset.status,
            "coverage": dataset.coverage,
            "candidate_index_audit": dataset.candidate_index_audit,
            "feature_parity_audit": _feature_parity_report(dataset.rows, split),
            "pool_audit": dataset.pool_audit,
            "input_fingerprint": dataset.input_fingerprint,
        },
        "performance": {"total_seconds": round(monotonic() - started, 3)},
    }


def _probability_rejected_report(
    dataset: ReplayDataset,
    split: ReplayDateSplit,
    *,
    model: object,
    scored_rows: Sequence[Mapping[str, object]],
    qualification: Mapping[str, object],
    recent_timing: Mapping[str, object],
    started: float,
) -> dict[str, object]:
    reasons = [str(value) for value in qualification.get("reasons") or ()]
    allowed_dates = set(split.validation)
    order_sets = _baseline_only_order_sets(dataset.formal_orders)
    validation_accounts = _phase_accounts(
        order_sets,
        dataset,
        allowed_dates=allowed_dates,
    )
    c_half_hour = _half_hour_report(
        (),
        orders=(),
        dataset=dataset,
        allowed_dates=allowed_dates,
    )
    a_half_hour = _half_hour_report(
        order_sets.get("a_first_board_orders") or (),
        orders=order_sets.get("a_first_board_orders") or (),
        dataset=dataset,
        allowed_dates=allowed_dates,
    )
    return {
        "study_version": REPLAY_CONTRACT_VERSION,
        "status": "probability_rejected",
        "decision": {
            "status": "probability_rejected",
            "passed": False,
            "reason": "probability_qualification_failed",
            "checks": {"probability_qualification": False},
            "details": reasons,
        },
        "formal_strategy_changed": False,
        "adversarial_reuse": True,
        "date_split": _date_split_report(split),
        "dataset": {
            "status": dataset.status,
            "input_fingerprint": dataset.input_fingerprint,
            "quality_point_count": len(dataset.rows),
            "scoreable_point_count": sum(
                row.get("feature_status") == "scoreable" for row in dataset.rows
            ),
            "coverage": dataset.coverage,
            "candidate_index_audit": dataset.candidate_index_audit,
            "pool_audit": dataset.pool_audit,
        },
        "model": _model_report(model, scored_rows, split),
        "calibration": {
            "status": "not_run_probability_rejected",
            "thresholds": None,
            "candidate_threshold_count": 0,
        },
        "validation": {
            "probabilities": dict(qualification),
            "accounts": validation_accounts,
            "stability": {},
            "identity_and_timing": {},
            "daily_pools": _daily_pool_report(
                scored_rows,
                order_sets,
                allowed_dates=allowed_dates,
                pool_audit=dataset.pool_audit,
            ),
            "half_hour": c_half_hour,
            "half_hour_by_account": {
                "a_first_board": a_half_hour,
                "c_first_board": c_half_hour,
            },
            "consecutive_losses": _consecutive_loss_report(
                validation_accounts,
                scored_rows,
                market_diagnostics=dataset.market_diagnostics,
                allowed_dates=allowed_dates,
            ),
        },
        "recent_live_timing": dict(recent_timing),
        "limitations": [
            "概率资格失败后未搜索收益阈值，也未运行严格C账户；A触板基准仍独立报告。",
            "后30日已被既有研究查看，因此标记为adversarial_reuse。",
        ],
        "performance": {"total_seconds": round(monotonic() - started, 3)},
    }


def render_preboard_replay_markdown(report: Mapping[str, object]) -> str:
    decision = _mapping(report.get("decision"))
    dataset = _mapping(report.get("dataset"))
    coverage = _mapping(dataset.get("coverage"))
    quality = _mapping(coverage.get("quality_pool"))
    path_coverage = _mapping(coverage.get("one_minute_paths"))
    transaction_coverage = _mapping(coverage.get("transaction_flow"))
    environment_coverage = _mapping(coverage.get("historical_environment"))
    environment_fields = _mapping(environment_coverage.get("field_coverage"))
    pool_audit = _mapping(dataset.get("pool_audit"))
    pool_distributions = _mapping(pool_audit.get("distributions"))
    validation = _mapping(report.get("validation"))
    accounts = _mapping(validation.get("accounts"))
    identity = _mapping(validation.get("identity_and_timing"))
    calibration = _mapping(report.get("calibration"))
    model = _mapping(report.get("model"))
    split = _mapping(report.get("date_split"))
    fit_split = _mapping(split.get("fit"))
    calibration_split = _mapping(split.get("calibration"))
    validation_split = _mapping(split.get("validation"))
    recent = _mapping(report.get("recent_live_timing"))
    recent_current = _mapping(recent.get("current_code_replay"))
    recent_static_scope = _mapping(recent_current.get("static_scope"))
    all_recent_rows = _mapping_rows(recent.get("rows"))
    daily_pools = _mapping_rows(validation.get("daily_pools"))
    candidate_audit = _mapping(dataset.get("candidate_index_audit"))
    probability = _mapping(validation.get("probabilities"))
    probability_heads = _mapping(probability.get("heads"))
    loss_report = _mapping(validation.get("consecutive_losses"))
    half_hour_by_account = _mapping(validation.get("half_hour_by_account"))

    def daily_distribution(
        field: str,
        fallback_field: str | None = None,
    ) -> dict[str, object]:
        values = [
            value
            for row in daily_pools
            if (value := _number(row.get(field))) is not None
        ]
        if values:
            return _distribution(values)
        return _mapping(pool_distributions.get(fallback_field or field))

    funnel_rows = (
        (
            "raw_capture_pool",
            "每日输入股票数",
            daily_distribution("raw_capture_symbol_count"),
        ),
        (
            "eligible_first_board_pool",
            "每日同源高质量首板股票数",
            daily_distribution("eligible_first_board_symbol_count"),
        ),
        (
            "quality_pool",
            "每日 >=3% 且严格板前股票数",
            daily_distribution("quality_pool_symbol_count"),
        ),
        (
            "action_pool",
            "每日通过环境与概率门的动作点数",
            daily_distribution("action_pool_point_count"),
        ),
        (
            "filled_pool",
            "每日严格下一报价成交数",
            daily_distribution("filled_pool_count"),
        ),
    )
    lines = [
        "# 首板板前决策最终验证",
        "",
        f"- 结论：`{report.get('status')}`",
        f"- 原因：`{decision.get('reason')}`",
        f"- 正式策略是否改变：`{report.get('formal_strategy_changed')}`",
        (
            "- 日期切分（fit / calibration / validation）："
            f"{fit_split.get('date_count', 0)} / "
            f"{calibration_split.get('date_count', 0)} / "
            f"{validation_split.get('date_count', 0)}"
        ),
        "- `>=3%`：仅启动高质量母池观察，不是买点。",
        "",
        "## 数据真实性",
        "",
        f"- 数据指纹：`{dataset.get('input_fingerprint', '-')}`",
        (
            "- 候选索引分层："
            f"{candidate_audit.get('raw_upper_bound_pair_count', 0)} -> "
            f"{candidate_audit.get('complete_minute_path_pair_count', 0)} -> "
            f"{candidate_audit.get('static_high_quality_pair_count', 0)} -> "
            f"{candidate_audit.get('candidate_index_pair_count', 0)}"
        ),
        (
            "- 候选正/负股票日："
            f"{candidate_audit.get('candidate_index_positive_count', 0)} / "
            f"{candidate_audit.get('candidate_index_negative_count', 0)}"
        ),
        (
            "- 标签反转不改变 membership："
            f"`{candidate_audit.get('label_mutation_membership_invariant', False)}`"
        ),
        (
            "- 候选索引指纹："
            f"`{candidate_audit.get('candidate_index_fingerprint', '-')}`"
        ),
        (
            "- 一分钟路径："
            f"{path_coverage.get('pair_count', 0)} / "
            f"{path_coverage.get('expected_pair_count', 0)} 股票日"
        ),
        (
            "- 逐笔资金："
            f"{transaction_coverage.get('pair_count', 0)} / "
            f"{transaction_coverage.get('expected_pair_count', 0)} 股票日"
        ),
        (
            "- 冻结质量池："
            f"{quality.get('point_count', dataset.get('quality_point_count', 0))} "
            "点时行 / "
            f"{quality.get('pair_count', 0)} 股票日"
        ),
        (
            "- 历史实时环境："
            f"{environment_coverage.get('date_count', 0)} 日 / "
            f"{environment_coverage.get('pair_count', 0)} 股票日"
        ),
        f"- 校准状态：`{calibration.get('status', 'not_run')}`",
        (
            "- 标签和 D+1 结果在特征冻结后连接；只有 `parity_status=shared` "
            "的风险、窗口、完整分钟和严格板前价格可以阻断。"
        ),
        "",
        "## 模型证据",
        "",
        f"- 状态：`{model.get('status', 'not_run')}`",
        f"- 模型指纹：`{model.get('model_fingerprint', '-')}`",
        f"- 特征版本：`{model.get('feature_version', '-')}`",
        f"- 声明特征列：{model.get('feature_count', 0)}",
    ]
    heads = _mapping(model.get("heads"))
    if heads:
        lines.extend(
            [
                "",
                "| 概率头 | 状态 | fit 有效列 | fit 删除列 | calibration Brier |",
                "|---|---|---:|---:|---:|",
            ]
        )
        for name, raw_head in heads.items():
            head = _mapping(raw_head)
            lines.append(
                "| "
                + str(name)
                + " | "
                + " | ".join(
                    (
                        str(head.get("status", "-")),
                        str(head.get("active_fit_feature_count", 0)),
                        str(head.get("dropped_fit_feature_count", 0)),
                        _display(head.get("calibration_brier")),
                    )
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "## Validation 概率资格",
            "",
            f"- 状态：`{probability.get('status', 'not_run')}`",
            f"- 股票日：{probability.get('stock_day_count', 0)}",
            "",
            "| 概率头 | 正例股票日 | 负例股票日 | 点时数 | 点时Base | 机会Base | 点时Brier | Brier skill | 点时PR-AUC | 机会Top20%命中率 | 机会Lift |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name in ("touch_3m", "eventual_touch"):
        head = _mapping(probability_heads.get(name))
        lines.append(
            "| "
            + name
            + " | "
            + " | ".join(
                (
                    str(head.get("positive_stock_days", 0)),
                    str(head.get("negative_stock_days", 0)),
                    str(head.get("point_count", 0)),
                    _display(head.get("base_rate")),
                    _display(head.get("opportunity_base_rate")),
                    _display(head.get("brier")),
                    _display(head.get("brier_skill")),
                    _display(head.get("pr_auc")),
                    _display(head.get("top_quintile_rate")),
                    _display(head.get("top_quintile_lift")),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 五层漏斗",
            "",
            "| 层级 | 审计口径 | P50 | P90 | 最大值 |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for name, description, distribution in funnel_rows:
        lines.append(
            "| "
            + name
            + " | "
            + description
            + " | "
            + " | ".join(
                (
                    _display(distribution.get("p50")),
                    _display(distribution.get("p90")),
                    _display(distribution.get("maximum")),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            (
                "冻结适配器只从 `>=3%` 开始生成点时行，因此本次历史证据中的 "
                "eligible 与 quality 数量相同；这不是用涨幅代替高质量过滤。"
            ),
            "",
            "## 环境覆盖",
            "",
            "| 字段 | parity | 是否阻断 | 可复现日期数 | 股票日/点数 |",
            "|---|---|---|---:|---:|",
        ]
    )
    for name in (
        "concept_strength",
        "industry_flow",
        "stock_flow",
        "quote_freshness",
        "snapshot_freshness",
        "market_gate",
        "risk_gate",
    ):
        field = _mapping(environment_fields.get(name))
        lines.append(
            "| "
            + name
            + " | "
            + str(field.get("parity_status", "-"))
            + " | "
            + str(field.get("blocking", False))
            + " | "
            + str(field.get("date_count", "-"))
            + " | "
            + str(
                field.get(
                    "pair_count",
                    field.get("point_count", 0),
                )
            )
            + " |"
        )
    failure_counts = _mapping(pool_audit.get("environment_failure_counts"))
    lines.extend(["", "阻断原因："])
    if failure_counts:
        for reason, count in sorted(
            failure_counts.items(),
            key=lambda item: (-int(_number(item[1]) or 0), str(item[0])),
        ):
            lines.append(f"- `{reason}`：{count}")
    else:
        lines.append("- 无可用阻断统计。")
    lines.extend(
        [
            "",
            "## Validation 严格账户",
            "",
            "| 账户 | 成交 | 胜率 | 复利 | 回撤 | 利润因子 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    account_labels = {
        "a_first_board": "A 正式触板首板",
        "c_first_board": "C 新严格板前首板",
        "a_combined": "A 正式联合账户",
        "c_combined": "C 新严格联合账户",
        "c_combined_double_cost": "C 联合双倍成本",
    }
    for name in account_labels:
        account = _mapping(accounts.get(name))
        lines.append(
            "| "
            + account_labels[name]
            + " | "
            + " | ".join(
                (
                    str(account.get("filled_count", 0)),
                    _display_pct(account.get("win_rate")),
                    _display_signed_pct(account.get("total_return_pct")),
                    _display_signed_pct(account.get("max_drawdown_pct")),
                    _display(account.get("profit_factor")),
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "严格 C 动作质量：",
            "",
            f"- 动作数：{identity.get('action_count', 0)}",
            f"- 可成交数：{identity.get('fillable_count', 0)}",
            (
                "- 3 分钟正式触板率："
                f"{_display_pct(identity.get('formal_touch_within_3m_rate_pct'))}"
            ),
            (
                "- 最终正式触板率："
                f"{_display_pct(identity.get('eventual_formal_touch_rate_pct'))}"
            ),
            (
                "- 未触板误报率："
                f"{_display_pct(identity.get('unreached_false_positive_rate_pct'))}"
            ),
            "",
            "## Validation 分段",
            "",
        ]
    )
    stability = _mapping(validation.get("stability"))
    stability_rows = _mapping_rows(stability.get("blocks"))
    if stability_rows:
        lines.extend(
            [
                "| 段 | 日期 | 成交 | 胜率 | 复利 | 回撤 |",
                "|---:|---|---:|---:|---:|---:|",
            ]
        )
        for row in stability_rows:
            lines.append(
                "| "
                + " | ".join(
                    (
                        str(row.get("block", "-")),
                        f"{row.get('start_date', '-')}..{row.get('end_date', '-')}",
                        str(row.get("filled_count", 0)),
                        _display_pct(row.get("win_rate")),
                        _display_signed_pct(row.get("total_return_pct")),
                        _display_signed_pct(row.get("max_drawdown_pct")),
                    )
                )
                + " |"
            )
    else:
        lines.append("无可用五段稳定性结果。")
    lines.extend(["", "半小时时段账户：", ""])
    rendered_half_hour = False
    for account_name, account_label in (
        ("a_first_board", "A 正式触板首板"),
        ("c_first_board", "C 严格板前首板"),
    ):
        half_hour_rows = _mapping_rows(half_hour_by_account.get(account_name))
        if not half_hour_rows and account_name == "c_first_board":
            half_hour_rows = _mapping_rows(validation.get("half_hour"))
        if not half_hour_rows:
            continue
        rendered_half_hour = True
        lines.extend(
            [
                f"**{account_label}**",
                "",
                "| 时段 | 动作 | 严格成交 | 3分钟触板率 | 最终触板率 | D+1胜率 | D+1期望 | 现金复利 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in half_hour_rows:
            lines.append(
                "| "
                + " | ".join(
                    (
                        str(row.get("time_bucket", "-")),
                        str(row.get("action_count", 0)),
                        str(row.get("strict_fill_count", 0)),
                        _display_pct(row.get("formal_touch_within_3m_rate_pct")),
                        _display_pct(row.get("eventual_formal_touch_rate_pct")),
                        _display_pct(row.get("d1_win_rate_pct")),
                        _display_signed_pct(row.get("d1_expected_return_pct")),
                        _display_signed_pct(row.get("cash_compound_return_pct")),
                    )
                )
                + " |"
            )
        lines.append("")
    if not rendered_half_hour:
        lines.append("A/C 均无可用时段统计。")
    if daily_pools:
        lines.extend(
            [
                "",
                "Validation 每日五层漏斗：",
                "",
                "| 日期 | raw | eligible | quality | action | filled |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in daily_pools:
            lines.append(
                "| "
                + " | ".join(
                    (
                        str(row.get("trade_date", "-")),
                        str(row.get("raw_capture_symbol_count", 0)),
                        str(row.get("eligible_first_board_symbol_count", 0)),
                        str(row.get("quality_pool_symbol_count", 0)),
                        str(
                            row.get(
                                "action_pool_point_count",
                                row.get("action_pool_count", 0),
                            )
                        ),
                        str(row.get("filled_pool_count", 0)),
                    )
                )
                + " |"
            )
    lines.extend(["", "## 连续亏损归因", ""])
    for account_name, label in (
        ("a_first_board", "A 正式触板首板"),
        ("c_first_board", "C 严格板前首板"),
    ):
        account_losses = _mapping(loss_report.get(account_name))
        lines.append(
            f"- {label}：最大连亏 {account_losses.get('maximum_consecutive_losses', 0)}，"
            f"连亏段 {account_losses.get('run_count', 0)}。"
        )
        for run in _mapping_rows(account_losses.get("runs")):
            lines.append(
                f"  - {run.get('start_date')}..{run.get('end_date')}："
                f"{run.get('trade_count', 0)} 笔，"
                f"分类 `{run.get('classification_counts', {})}`，"
                f"未入选正收益候选 {len(_mapping_rows(run.get('unselected_positive_quality_pool')))} 只。"
            )
    lines.extend(
        [
            "",
            "## 最近两日买点根因",
            "",
            f"- 正式触板正标签：{recent.get('formal_positive_count', 0)}",
            f"- 正标签存在板前帧：{recent.get('formal_positive_with_preboard_count', 0)}",
            f"- 旧 buy_now 在触板前：{recent.get('formal_positive_old_buy_preboard_count', 0)}",
            f"- 旧正式两仓股票日：{recent.get('selected_pair_count', 0)}",
            f"- 入选时已触板：{recent.get('selected_already_touched_count', 0)}",
            f"- 当前合同特征行：{recent.get('active_feature_row_count', 0)}",
            f"- 当前合同影子动作：{recent.get('active_shadow_action_count', 0)}",
            f"- 当前代码原始标签无关 >=3% 股票日：{recent_current.get('raw_capture_pair_count') or recent_static_scope.get('raw_capture_pair_count', 0)}",
            f"- prior-only 盈利基因门通过股票日：{recent_current.get('prior_only_quality_pair_count') or recent_static_scope.get('manifest_pair_count', 0)}",
            f"- prior-only 盈利基因门淘汰股票日：{recent_current.get('static_hazard_rejected_pair_count') or recent_static_scope.get('static_hazard_rejected_pair_count', 0)}",
            f"- 其余静态质量门淘汰股票日：{recent_current.get('static_prefilter_rejected_pair_count') or max(int(recent_static_scope.get('manifest_pair_count') or 0) - int(recent_current.get('static_candidate_pair_count') or 0), 0)}",
            f"- 当前代码静态候选股票日：{recent_current.get('static_candidate_pair_count', 0)}",
            f"- 当前代码有保存帧股票日：{recent_current.get('observed_pair_count', 0)}",
            f"- 当前代码质量池股票日：{recent_current.get('quality_pair_count', 0)}",
            f"- 当前代码可评分股票日：{recent_current.get('scoreable_pair_count', 0)}",
            f"- 当前代码概率可用股票日：{recent_current.get('probability_pair_count', 0)}",
            f"- 正式正标签进入当前质量池：{sum(row.get('formal_baseline_positive') is True and row.get('first_quality_pool_at') is not None for row in all_recent_rows)}",
            f"- 正式正标签当前可评分：{sum(row.get('formal_baseline_positive') is True and row.get('first_scoreable_at') is not None for row in all_recent_rows)}",
            f"- 正式正标签进入产品 Top2：{sum(row.get('formal_baseline_positive') is True and row.get('first_probability_rank_top2_at') is not None for row in all_recent_rows)}",
            f"- 正式正标签进入纯触板概率 Top2：{sum(row.get('formal_baseline_positive') is True and row.get('first_touch_probability_rank_top2_at') is not None for row in all_recent_rows)}",
        ]
    )
    recent_rows = [
        row
        for row in all_recent_rows
        if row.get("formal_baseline_positive") is True
    ]
    if recent_rows:
        lines.extend(
            [
                "",
                "| 日期 | 股票 | >=3% | 板前最高涨幅 | 当前质量池 | 当前scoreable | 产品Top2 | 触板概率Top2 | 3m/最终概率 | D+1预期/胜率 | 旧buy_now | 触板 | 最高点层级/阻断 |",
                "|---|---|---|---:|---|---|---|---|---|---|---|---|---|",
            ]
        )
        for row in recent_rows:
            lines.append(
                "| "
                + " | ".join(
                    (
                        str(row.get("trade_date", "-")),
                        str(row.get("vt_symbol", "-")),
                        str(row.get("first_ge_3_at", "-")),
                        _display_pct(row.get("maximum_preboard_gain_pct")),
                        str(row.get("first_quality_pool_at", "-")),
                        str(row.get("first_scoreable_at", "-")),
                        str(row.get("first_probability_rank_top2_at", "-")),
                        str(row.get("first_touch_probability_rank_top2_at", "-")),
                        (
                            _display_probability(row.get("best_touch_probability_3m"))
                            + "/"
                            + _display_probability(
                                row.get("best_eventual_touch_probability")
                            )
                        ),
                        (
                            _display_signed_pct(
                                row.get("expected_d1_net_return_pct")
                            )
                            + "/"
                            + _display_probability(row.get("d1_win_probability"))
                        ),
                        str(row.get("first_old_buy_now_at", "-")),
                        str(row.get("physical_touch_at", "-")),
                        (
                            str(
                                row.get("maximum_replayed_preboard_pool_stage")
                                or (
                                    "capture_rejected"
                                    if row.get("static_hazard_gate_passed") is False
                                    else None
                                )
                                or "-"
                            )
                            + "/"
                            + ",".join(
                                str(value)
                                for value in row.get(
                                    "maximum_replayed_preboard_rejection_codes"
                                )
                                or (
                                    [row.get("static_hazard_gate_reason")]
                                    if row.get("static_hazard_gate_passed") is False
                                    else []
                                )
                                or ()
                            )
                        ),
                    )
                )
                + " |"
            )
    observed_ranked_rows = [
        row
        for row in all_recent_rows
        if row.get("trade_date") == RECENT_TIMING_AUDIT_END.isoformat()
        and row.get("formal_baseline_positive") is not True
        and row.get("physical_touch_at") is not None
        and (
            row.get("first_probability_rank_top2_at") is not None
            or row.get("first_touch_probability_rank_top2_at") is not None
        )
    ]
    if observed_ranked_rows:
        lines.extend(
            [
                "",
                "### 7月22日保存帧触板代理",
                "",
                "该日正式回测首板为 0；下表只是保存帧中后来触板且曾进入当前 Top2 的时序核验，不作为正式收益标签。",
                "",
                "| 股票 | 板前最高涨幅 | 产品Top2 | 产品提前秒 | 触板概率Top2 | 触板提前秒 | 3m/最终概率 | D+1预期/胜率 |",
                "|---|---:|---|---:|---|---:|---|---|",
            ]
        )
        for row in observed_ranked_rows:
            lines.append(
                "| "
                + " | ".join(
                    (
                        f"{row.get('vt_symbol', '-')} {row.get('name') or ''}".strip(),
                        _display_pct(row.get("maximum_preboard_gain_pct")),
                        str(row.get("first_probability_rank_top2_at") or "-"),
                        _display(row.get("probability_rank_top2_lead_seconds")),
                        str(row.get("first_touch_probability_rank_top2_at") or "-"),
                        _display(row.get("touch_probability_rank_top2_lead_seconds")),
                        (
                            _display_probability(row.get("best_touch_probability_3m"))
                            + "/"
                            + _display_probability(
                                row.get("best_eventual_touch_probability")
                            )
                        ),
                        (
                            _display_signed_pct(
                                row.get("expected_d1_net_return_pct")
                            )
                            + "/"
                            + _display_probability(row.get("d1_win_probability"))
                        ),
                    )
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "## 决策",
            "",
            (
                "历史与严格环境账户均通过，下一阶段仅进入前向影子账本。"
                if report.get("status") == "historical_pass_for_shadow"
                else (
                    "双概率排序资格通过，但严格板前账户未通过冻结收益门；"
                    "只保留 `research_only` 观察排序，不替换正式首板买点与两仓。"
                    if report.get("status") == "historical_rejected"
                    else (
                        "概率排序资格未通过；不展示未合格概率，也不替换正式"
                        "首板买点与两仓。"
                        if report.get("status") == "probability_rejected"
                        else "证据不足；正式首板买点与两仓保持不变。"
                    )
                )
            ),
            "",
            "正式首板、二进三、费用和 D+1 官方收盘退出均保持不变。",
            "",
        ]
    )
    return "\n".join(lines)


def _write_output(path_text: str | None, content: str) -> None:
    if not path_text:
        return
    path = Path(path_text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=int, default=180)
    parser.add_argument("--end-date", type=date.fromisoformat, default=FROZEN_PATH_END_DATE)
    parser.add_argument("--json-output")
    parser.add_argument("--markdown-output")
    parser.add_argument(
        "--publish-research-model",
        action="store_true",
        help="publish a probability-qualified model under its frozen execution mode",
    )
    arguments = parser.parse_args(argv)
    session_count = min(max(int(arguments.sessions), 1), FROZEN_PATH_SESSION_COUNT)
    report = evaluate_preboard_replay(
        session_count=session_count,
        end_date=arguments.end_date,
        progress=lambda message: print(message, flush=True),
        publish_research_model=arguments.publish_research_model,
    )
    encoded = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    markdown = render_preboard_replay_markdown(report)
    _write_output(arguments.json_output, encoded + "\n")
    _write_output(arguments.markdown_output, markdown)
    if not arguments.json_output and not arguments.markdown_output:
        print(encoded)


def _datetime_text(value: object) -> str | None:
    parsed = _local_naive_datetime(value)
    return parsed.isoformat() if parsed is not None else None


def _display(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:.4f}" if parsed is not None else "-"


def _display_pct(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:.2f}%" if parsed is not None else "-"


def _display_probability(value: object) -> str:
    parsed = _number(value)
    return f"{parsed * 100:.2f}%" if parsed is not None else "-"


def _display_signed_pct(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:+.2f}%" if parsed is not None else "-"


def build_historical_point_rows(
    points: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Run visible candidates through the same quality and feature functions."""

    rows: list[dict[str, object]] = []
    ordered_points = sorted(
        (dict(point) for point in points),
        key=lambda point: _as_datetime(point.get("decision_at")) or datetime.max,
    )
    for point in ordered_points:
        decision_at = _as_datetime(point.get("decision_at"))
        if decision_at is None:
            continue
        market_gate = _mapping(point.get("market_gate"))
        cross_sections = _mapping_rows(point.get("cross_section_snapshots"))
        visible_candidates: list[dict[str, object]] = []
        source_by_symbol: dict[str, dict[str, object]] = {}
        for raw in _mapping_rows(point.get("candidates")):
            candidate = _visible_candidate(raw, decision_at)
            if candidate is None:
                continue
            symbol = str(candidate.get("vt_symbol") or "").strip()
            if not symbol:
                continue
            source_by_symbol[symbol] = candidate
            visible_candidates.append(candidate)

        pools = build_preboard_pools(
            visible_candidates,
            decision_at=decision_at,
            market_gate=market_gate,
        )
        pool_counts = {
            "adapter_input_count": pools.adapter_input_count,
            "capture_pool_count": len(pools.capture_pool),
            "eligible_first_board_pool_count": len(
                pools.eligible_first_board_pool
            ),
            "quality_pool_count": len(pools.quality_pool),
            "pool_rejection_counts": dict(pools.rejection_counts),
        }
        for quality in pools.quality_pool:
            symbol = str(quality.get("vt_symbol") or "").strip()
            source = source_by_symbol.get(symbol)
            if source is None:
                continue
            observation = {
                **source,
                "decision_at": decision_at.isoformat(),
                "candidate": quality,
                "cross_section_snapshots": cross_sections,
            }
            projection = project_historical_decision_features(observation)
            signal_price = _number(source.get("last_price"))
            limit_price = _number(source.get("limit_price"))
            next_quote_at, next_quote_price = _next_quote(source, decision_at)
            fillable = bool(
                next_quote_at is not None
                and next_quote_at > decision_at
                and next_quote_price is not None
                and limit_price is not None
                and next_quote_price < limit_price - 0.001
            )
            rows.append(
                compact_replay_row(
                    {
                    **quality,
                    **projection,
                    **pool_counts,
                    "decision_at": decision_at.isoformat(),
                    "trade_date": decision_at.date().isoformat(),
                    "signal_date": decision_at.date().isoformat(),
                    "signal_time": decision_at.time().replace(microsecond=0).isoformat(),
                    "signal_price": signal_price,
                    "last_price": signal_price,
                    "limit_price": limit_price,
                    "next_quote_at": (
                        next_quote_at.isoformat() if next_quote_at is not None else None
                    ),
                    "next_quote_price": next_quote_price,
                    "fillable": fillable,
                    "entry_price": next_quote_price if fillable else None,
                    "entry_contract": ENTRY_CONTRACT,
                    "exit_contract": EXIT_CONTRACT,
                    "replay_contract_version": REPLAY_CONTRACT_VERSION,
                    }
                )
            )
    return rows


def compact_replay_row(row: Mapping[str, object]) -> dict[str, object]:
    """Drop source prefixes after their causal feature projection is frozen."""

    return {
        key: value
        for key, value in row.items()
        if key not in TRANSIENT_REPLAY_FIELDS
    }


def attach_replay_labels(
    rows: Sequence[Mapping[str, object]],
    labels: Mapping[tuple[date, str], Mapping[str, object]],
) -> list[dict[str, object]]:
    """Attach touch and D+1 settlement fields after model inputs are frozen."""

    attached: list[dict[str, object]] = []
    for raw in rows:
        row = dict(raw)
        trade_date = _as_date(row.get("trade_date") or row.get("signal_date"))
        symbol = str(row.get("vt_symbol") or "").strip()
        label = dict(labels.get((trade_date, symbol), {})) if trade_date else {}
        decision_at = _as_datetime(row.get("decision_at"))
        touch_at = _label_touch_at(label, trade_date)
        formal_identity = bool(
            label.get("formal_baseline_identity") is True
            or label.get("formal_identity_matched") is True
        )
        future_touch = bool(
            formal_identity
            and decision_at is not None
            and touch_at is not None
            and touch_at >= decision_at
        )
        within_3m = bool(
            future_touch
            and _trading_minute_distance(decision_at, touch_at) <= 3
        )
        d1_close = _number(label.get("d1_close_price"))
        entry_price = _number(row.get("entry_price"))
        limit_price = _number(row.get("limit_price"))
        attached.append(
            {
                **row,
                "physical_touch_at": touch_at.isoformat() if touch_at else None,
                "formal_baseline_identity": formal_identity,
                "formal_touch_within_3m": within_3m,
                "eventual_formal_touch": future_touch,
                "formal_touch_eventually": future_touch,
                "sealed_limit": bool(
                    label.get("sealed_limit") is True
                    or label.get("final_sealed") is True
                ),
                "d1_close_price": d1_close,
                "result_date": _date_text(label.get("result_date")),
                "d1_net_return_pct": _formal_net_return_pct(
                    entry_price,
                    d1_close,
                    limit_price=limit_price,
                ),
            }
        )
    return attached


def split_replay_dates(values: Sequence[date | datetime | str]) -> ReplayDateSplit:
    """Freeze the chronological 44/15/30 research split when 89 days exist."""

    dates = tuple(sorted({parsed for value in values if (parsed := _as_date(value))}))
    if len(dates) < 45:
        return ReplayDateSplit(dates, (), ())
    validation = dates[-30:]
    calibration = dates[-45:-30]
    fit = dates[:-45]
    return ReplayDateSplit(fit, calibration, validation)


def _bounded_replay_dates(
    *,
    start: date,
    end: date,
    trade_dates: Sequence[date | datetime | str],
) -> tuple[date, ...]:
    return tuple(
        sorted(
            {
                parsed
                for value in trade_dates
                if (parsed := _as_date(value)) is not None
                and start <= parsed <= end
            }
        )
    )


def calibrate_policy_thresholds(
    rows: Sequence[Mapping[str, object]],
    *,
    calibration_dates: set[date] | Sequence[date],
    model_fingerprint: str,
    minimum_action_count: int = 10,
) -> ReplayCalibration:
    """Choose one threshold pair using calibration rows and labels only."""

    allowed_dates = tuple(sorted(set(calibration_dates)))
    allowed = set(allowed_dates)
    calibration_rows = [
        dict(row)
        for row in rows
        if _as_date(row.get("trade_date") or row.get("signal_date")) in allowed
    ]
    touch_values = sorted(
        {
            value
            for row in calibration_rows
            if (value := _probability(row.get("touch_probability_3m"))) is not None
        }
    )
    eventual_values = sorted(
        {
            value
            for row in calibration_rows
            if (value := _probability(row.get("eventual_touch_probability")))
            is not None
        }
    )
    metrics: list[dict[str, object]] = []
    candidates: list[tuple[tuple[object, ...], dict[str, object]]] = []
    for touch in touch_values:
        for eventual in eventual_values:
            if eventual < touch:
                continue
            provisional = PreboardPolicyThresholds(
                minimum_touch_probability_3m=touch,
                minimum_eventual_touch_probability=eventual,
                calibrated_dates=allowed_dates,
                fingerprint="calibration-provisional",
            )
            decisions = select_preboard_decisions(calibration_rows, provisional)
            actions = [
                row
                for row in decisions
                if row.get("decision_state") == "actionable"
                and row.get("fillable") is True
                and _number(row.get("d1_net_return_pct")) is not None
            ]
            result = _threshold_metrics(actions, touch, eventual)
            metrics.append(result)
            if len(actions) < minimum_action_count:
                continue
            key = (
                _number(result.get("compounded_return_pct")) or float("-inf"),
                _number(result.get("d1_win_rate_pct")) or float("-inf"),
                _number(result.get("max_drawdown_pct")) or float("-inf"),
                _number(result.get("formal_touch_within_3m_rate_pct"))
                or float("-inf"),
                touch,
                eventual,
            )
            candidates.append((key, result))

    if not candidates:
        return ReplayCalibration(
            status="insufficient_calibration_actions",
            thresholds=None,
            selected_metrics=None,
            metrics_by_threshold=tuple(metrics),
            calibration_dates=allowed_dates,
        )
    selected = max(candidates, key=lambda item: item[0])[1]
    payload = {
        "model_fingerprint": model_fingerprint,
        "calibration_dates": [value.isoformat() for value in allowed_dates],
        "minimum_touch_probability_3m": selected["minimum_touch_probability_3m"],
        "minimum_eventual_touch_probability": selected[
            "minimum_eventual_touch_probability"
        ],
    }
    fingerprint = "sha256:" + sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    thresholds = PreboardPolicyThresholds(
        minimum_touch_probability_3m=float(
            selected["minimum_touch_probability_3m"]
        ),
        minimum_eventual_touch_probability=float(
            selected["minimum_eventual_touch_probability"]
        ),
        calibrated_dates=allowed_dates,
        fingerprint=fingerprint,
    )
    return ReplayCalibration(
        status="ready",
        thresholds=thresholds,
        selected_metrics=selected,
        metrics_by_threshold=tuple(metrics),
        calibration_dates=allowed_dates,
    )


def build_replay_order_sets(
    *,
    rows: Sequence[Mapping[str, object]],
    thresholds: PreboardPolicyThresholds,
    formal_orders: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Build the formal A baseline and strict pre-board C account."""

    quality_rows = [dict(row) for row in rows if row.get("quality_gate_passed") is True]
    c_decisions = evaluate_preboard_decisions(
        quality_rows,
        model_bundle=None,
        thresholds=thresholds,
    )
    c_action_pool = [
        row for row in quality_rows if can_compete_for_action(row, thresholds)
    ]
    c_actions = [
        row for row in c_decisions if row.get("decision_state") == "actionable"
    ]
    c_orders = [order for row in c_actions if (order := _action_order(row))]
    formal = [dict(order) for order in formal_orders]
    relay = [order for order in formal if _is_relay_order(order)]
    formal_first_board = [order for order in formal if not _is_relay_order(order)]
    return {
        "c_action_pool_rows": c_action_pool,
        "c_action_rows": c_actions,
        "c_first_board_orders": c_orders,
        "a_first_board_orders": formal_first_board,
        "relay_orders": relay,
        "a_combined_orders": formal,
        "c_combined_orders": [*relay, *c_orders],
    }


def decide_historical_promotion(
    *,
    strict_first_board: Mapping[str, object],
    formal_first_board: Mapping[str, object],
    strict_combined: Mapping[str, object],
    formal_combined: Mapping[str, object],
    strict_double_cost: Mapping[str, object],
    positive_stability_blocks: int,
    strict_action_count: int,
) -> dict[str, object]:
    """Apply the frozen account gates without tuning after validation."""

    if int(strict_action_count) < MINIMUM_VALIDATION_ACTIONS:
        return {
            "status": "insufficient_for_portfolio_promotion",
            "passed": False,
            "reason": "validation_strict_actions_below_20",
            "strict_action_count": int(strict_action_count),
            "checks": {},
        }
    required_values = (
        _number(strict_first_board.get("win_rate")),
        _number(formal_first_board.get("win_rate")),
        _number(strict_first_board.get("total_return_pct")),
        _number(formal_first_board.get("total_return_pct")),
        _number(strict_combined.get("win_rate")),
        _number(formal_combined.get("win_rate")),
        _number(strict_combined.get("total_return_pct")),
        _number(formal_combined.get("total_return_pct")),
    )
    if any(value is None for value in required_values):
        return {
            "status": "insufficient_for_portfolio_promotion",
            "passed": False,
            "reason": "validation_account_metrics_incomplete",
            "strict_action_count": int(strict_action_count),
            "checks": {},
        }
    checks = {
        "first_board_win_rate": _win_rate_gate(
            strict_first_board,
            formal_first_board,
        ),
        "first_board_compound": _compound_gate(
            strict_first_board,
            formal_first_board,
        ),
        "first_board_drawdown": _drawdown_gate(
            strict_first_board,
            formal_first_board,
        ),
        "first_board_profit_factor": (
            (_number(strict_first_board.get("profit_factor")) or 0.0) >= 1.5
        ),
        "combined_win_rate": _win_rate_gate(strict_combined, formal_combined),
        "combined_compound": _compound_gate(strict_combined, formal_combined),
        "combined_drawdown": _drawdown_gate(strict_combined, formal_combined),
        "double_cost_positive": (
            (_number(strict_double_cost.get("total_return_pct")) or 0.0) > 0.0
        ),
        "time_stability": int(positive_stability_blocks) >= 3,
    }
    passed = all(checks.values())
    return {
        "status": (
            "historical_pass_for_shadow" if passed else "historical_rejected"
        ),
        "passed": passed,
        "reason": "all_frozen_gates_passed" if passed else "frozen_gate_failed",
        "strict_action_count": int(strict_action_count),
        "positive_stability_blocks": int(positive_stability_blocks),
        "checks": checks,
    }


def _win_rate_gate(
    candidate: Mapping[str, object],
    baseline: Mapping[str, object],
) -> bool:
    candidate_rate = _number(candidate.get("win_rate"))
    baseline_rate = _number(baseline.get("win_rate"))
    return bool(
        candidate_rate is not None
        and baseline_rate is not None
        and candidate_rate >= baseline_rate - 2.0
    )


def _compound_gate(
    candidate: Mapping[str, object],
    baseline: Mapping[str, object],
) -> bool:
    candidate_return = _number(candidate.get("total_return_pct"))
    baseline_return = _number(baseline.get("total_return_pct"))
    if candidate_return is None or baseline_return is None or candidate_return <= 0:
        return False
    return candidate_return >= max(baseline_return * 0.9, 0.0)


def _drawdown_gate(
    candidate: Mapping[str, object],
    baseline: Mapping[str, object],
) -> bool:
    candidate_drawdown = _number(candidate.get("max_drawdown_pct"))
    baseline_drawdown = _number(baseline.get("max_drawdown_pct"))
    return bool(
        candidate_drawdown is not None
        and baseline_drawdown is not None
        and candidate_drawdown >= baseline_drawdown - 2.0
    )


def _visible_candidate(
    raw: Mapping[str, object],
    decision_at: datetime,
) -> dict[str, object] | None:
    candidate = {key: value for key, value in raw.items() if key not in _LABEL_ONLY_FIELDS}
    bars = [
        dict(bar)
        for bar in _mapping_rows(raw.get("minute_bars"))
        if (_as_datetime(bar.get("bar_time")) or datetime.max) <= decision_at
    ]
    bars.sort(key=lambda bar: _as_datetime(bar.get("bar_time")) or datetime.max)
    if not bars:
        return None
    previous_close = _number(candidate.get("previous_close"))
    limit_price = _number(candidate.get("limit_price"))
    last_price = _number(bars[-1].get("close_price"))
    if (
        previous_close is None
        or previous_close <= 0
        or limit_price is None
        or last_price is None
    ):
        return None
    if any(
        (_number(bar.get("high_price")) or float("-inf")) >= limit_price - 0.001
        for bar in bars
    ):
        return None
    first_observed_at = next(
        (
            bar_at
            for bar in bars
            if (bar_at := _as_datetime(bar.get("bar_time"))) is not None
            and (_return_pct(previous_close, _number(bar.get("close_price"))) or -1e9)
            >= 3.0
        ),
        None,
    )
    lane_prefix = build_lane_prefix(
        bars,
        len(bars) - 1,
        previous_close=previous_close,
        bar_minutes=1,
    )
    return apply_preboard_parity_contract(
        {
            **candidate,
            "decision_at": decision_at.isoformat(),
            "signal_time": decision_at.time().replace(microsecond=0).isoformat(),
            "minute_bars": bars,
            "last_price": last_price,
            "change_pct": _return_pct(previous_close, last_price),
            "path_prefix": lane_prefix,
            "candidate_first_observed_at": (
                first_observed_at.isoformat() if first_observed_at else None
            ),
        }
    )


def _next_quote(
    candidate: Mapping[str, object],
    decision_at: datetime,
) -> tuple[datetime | None, float | None]:
    explicit_at = _as_datetime(candidate.get("next_quote_at"))
    explicit_price = _number(candidate.get("next_quote_price"))
    if explicit_at is not None and explicit_at > decision_at:
        return explicit_at, explicit_price
    future = sorted(
        (
            (_as_datetime(bar.get("bar_time")), _number(bar.get("open_price")))
            for bar in _mapping_rows(candidate.get("minute_bars"))
        ),
        key=lambda item: item[0] or datetime.max,
    )
    return next(
        ((bar_at, price) for bar_at, price in future if bar_at and bar_at > decision_at),
        (None, None),
    )


def _action_order(row: Mapping[str, object]) -> dict[str, object] | None:
    entry_price = _number(row.get("entry_price"))
    limit_price = _number(row.get("limit_price"))
    if (
        row.get("fillable") is not True
        or entry_price is None
        or limit_price is None
        or entry_price >= limit_price - 0.001
    ):
        return None
    decision_at = _as_datetime(row.get("decision_at"))
    trade_date = _as_date(row.get("trade_date") or row.get("signal_date"))
    return {
        **dict(row),
        "lane": "first_board",
        "board_lane": "first_board",
        "entry_date": trade_date.isoformat() if trade_date else None,
        "signal_date": trade_date.isoformat() if trade_date else None,
        "buy_time": decision_at.time().replace(microsecond=0).isoformat()
        if decision_at
        else row.get("signal_time"),
        "entry_price": entry_price,
        "limit_price": limit_price,
        "entry_contract": ENTRY_CONTRACT,
        "exit_contract": EXIT_CONTRACT,
    }


def _threshold_metrics(
    actions: Sequence[Mapping[str, object]],
    touch_threshold: float,
    eventual_threshold: float,
) -> dict[str, object]:
    returns = [
        value
        for row in actions
        if (value := _number(row.get("d1_net_return_pct"))) is not None
    ]
    equity = 1.0
    peak = 1.0
    maximum_drawdown = 0.0
    for value in returns:
        equity *= 1.0 + value / 100.0
        peak = max(peak, equity)
        maximum_drawdown = min(maximum_drawdown, (equity / peak - 1.0) * 100.0)
    within = sum(row.get("formal_touch_within_3m") is True for row in actions)
    return {
        "minimum_touch_probability_3m": touch_threshold,
        "minimum_eventual_touch_probability": eventual_threshold,
        "action_count": len(actions),
        "d1_win_rate_pct": _percentage(sum(value > 0 for value in returns), len(returns)),
        "compounded_return_pct": round((equity - 1.0) * 100.0, 10),
        "max_drawdown_pct": round(maximum_drawdown, 10),
        "formal_touch_within_3m_rate_pct": _percentage(within, len(actions)),
    }


def _formal_net_return_pct(
    entry_price: float | None,
    exit_price: float | None,
    *,
    limit_price: float | None,
) -> float | None:
    if entry_price is None or exit_price is None or entry_price <= 0 or exit_price <= 0:
        return None
    outcome = cash_backtest.calculate_round_trip_outcome(
        entry_price,
        exit_price,
        limit_price=limit_price,
    )
    return _number((outcome or {}).get("net_return_pct"))


def _label_touch_at(
    label: Mapping[str, object],
    trade_date: date | None,
) -> datetime | None:
    direct = _as_datetime(label.get("physical_touch_at"))
    if direct is not None:
        return direct
    value = label.get("first_limit_time")
    if trade_date is None or value in (None, ""):
        return None
    return _as_datetime(f"{trade_date.isoformat()}T{str(value)[:8]}")


def _trading_minute_distance(start: datetime | None, end: datetime | None) -> int:
    if start is None or end is None or start.date() != end.date() or end < start:
        return 10**9
    return max(session_minute_index(end) - session_minute_index(start), 0)


def _is_relay_order(row: Mapping[str, object]) -> bool:
    return str(row.get("lane") or row.get("board_lane") or "") in {
        "two_to_three",
        "high_board",
    }


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _local_naive_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value in (None, ""):
        return None
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed
    return parsed.astimezone(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)


def _distribution(values: Sequence[float]) -> dict[str, object]:
    ordered = sorted(float(value) for value in values if isfinite(float(value)))
    if not ordered:
        return {"count": 0, "p50": None, "p90": None, "maximum": None}
    return {
        "count": len(ordered),
        "p50": round(median(ordered), 6),
        "p90": round(_quantile(ordered, 0.9), 6),
        "maximum": round(ordered[-1], 6),
    }


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise ValueError("quantile values are empty")
    position = (len(values) - 1) * min(max(probability, 0.0), 1.0)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def _mapping_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _records(value: object) -> list[dict[str, object]]:
    if isinstance(value, pd.DataFrame):
        return [dict(row) for row in value.to_dict(orient="records")]
    return _mapping_rows(value)


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _date_text(value: object) -> str | None:
    parsed = _as_date(value)
    return parsed.isoformat() if parsed else None


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _probability(value: object) -> float | None:
    parsed = _number(value)
    return parsed if parsed is not None and 0.0 <= parsed <= 1.0 else None


def _return_pct(base: float | None, value: float | None) -> float | None:
    if base is None or value is None or base <= 0:
        return None
    return (value / base - 1.0) * 100.0


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100.0, 10) if denominator else None


if __name__ == "__main__":
    main()
