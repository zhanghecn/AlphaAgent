"""Causal 14:50 signal contract for the low-suction swing paper strategy."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from alphaagent.server.services.a_share_universe import is_eligible_main_board

from .concept_cycles import (
    FROZEN_MAIN_RISE_DEFINITION,
    build_cycle_candidates,
    build_market_returns,
)
from .forward_leader_identity import FORWARD_LEADER_RANKING_VERSION
from .leader_identity import LeaderIdentityMode
from .leader_waves import build_leader_wave_ledger
from .stock_wave_pullbacks import build_stock_wave_features


SHANGHAI = ZoneInfo("Asia/Shanghai")
STRATEGY_VERSION = "low-suction-swing-paper-v1"
EVIDENCE_LEVEL = "strict_intraday_forward_paper"
IDENTITY_MODE = LeaderIdentityMode.CYCLE_RELATIVE_STRENGTH.value
SIGNAL_CUTOFF = time(14, 50)
ENTRY_TIME = time(14, 55)
PREVIEW_WINDOWS = (
    (time(9, 30), time(11, 31)),
    (time(13, 0), SIGNAL_CUTOFF),
)
MINIMUM_PULLBACK_PCT = 5.0
APPROACH_TOLERANCE_PCT = 2.0
MINIMUM_PRIOR_STRONG_DAYS = 1
STRONG_DAY_THRESHOLD_PCT = 9.5
MAX_LEADER_SPELL_SESSIONS = 40
MAX_POSITIONS = 2
MAX_POSITIONS_PER_CONCEPT = 1
QUOTE_MAX_AGE_SECONDS = 120
SUPPORT_DEPTH = {"ma5": 1, "ma10": 2, "ma20": 3}
PROHIBITED_PREFIXES = (
    "entry_",
    "exit_",
    "future_",
    "mae_",
    "mfe_",
    "outcome_",
)


class SwingSignalInputError(ValueError):
    """Raised when a causal signal input is missing, stale, or inconsistent."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


@dataclass(frozen=True)
class SwingStrategyInputs:
    source_trade_date: date
    signal_trade_date: date
    captured_at: datetime
    leader_rows: pd.DataFrame
    leader_history: pd.DataFrame
    stock_bars: pd.DataFrame
    concept_bars: pd.DataFrame
    benchmark_bars: pd.DataFrame
    stock_quotes: pd.DataFrame
    concept_quotes: pd.DataFrame
    benchmark_quotes: pd.DataFrame
    completed_dates: tuple[date, ...]
    open_positions: pd.DataFrame


@dataclass(frozen=True)
class SwingSignalCandidate:
    signal_id: str
    strategy_version: str
    signal_trade_date: date
    source_trade_date: date
    captured_at: datetime
    feature_cutoff_at: datetime
    identity_mode: str
    vt_symbol: str
    stock_name: str
    sector_id: str
    sector_name: str
    rank: int
    leader_spell_start: date
    current_wave_number: int
    confirmed_higher_highs: int
    wave_start_date: date
    reference_peak_date: date
    reference_peak_price: float
    pullback_confirmation_date: date | None
    support_line: str | None
    support_price: float | None
    line_distance_low_pct: float | None
    provisional_open: float
    provisional_high: float
    provisional_low: float
    provisional_close: float
    provisional_volume: float
    provisional_turnover: float | None
    provisional_ma5: float | None
    previous_close: float
    strong_days_ge_9_5pct: int
    stock_structure_intact: bool
    concept_main_rise_intact: bool
    signal_eligible: bool
    decision_reason: str
    recommendation_state: str
    portfolio_reason: str | None
    quote_source: str
    quote_trade_time: datetime
    input_fingerprint: str
    evidence_level: str
    raw: dict[str, object]


@dataclass(frozen=True)
class SwingSignalCapture:
    strategy_version: str
    signal_trade_date: date
    source_trade_date: date
    captured_at: datetime
    feature_cutoff_at: datetime
    status: str
    input_fingerprint: str
    candidates: tuple[SwingSignalCandidate, ...]
    recommendation_count: int


@dataclass(frozen=True)
class _Stabilization:
    signal_date: date
    confirmation_date: date
    support_line: str
    support_price: float
    line_distance_low_pct: float


def build_swing_signal_capture(
    inputs: SwingStrategyInputs,
    *,
    preview: bool = False,
) -> SwingSignalCapture:
    """Build a provisional preview or the immutable 14:50 recommendation."""

    prepared = _validate_and_prepare_inputs(inputs, preview=preview)
    fingerprint = _fingerprint_inputs(prepared)
    active_concepts = _live_active_concepts(prepared)
    stock_features = _provisional_stock_features(prepared)
    candidates = tuple(
        _build_candidate(
            prepared,
            leader,
            stock_features=stock_features,
            active_concepts=active_concepts,
            fingerprint=fingerprint,
        )
        for leader in _deduplicated_leaders(prepared.leader_rows)
    )
    allocated = _allocate_recommendations(candidates, prepared.open_positions)
    feature_cutoff = (
        prepared.captured_at
        if preview
        else _feature_cutoff(prepared.signal_trade_date)
    )
    if preview:
        allocated = tuple(
            replace(candidate, feature_cutoff_at=feature_cutoff)
            for candidate in allocated
        )
    return SwingSignalCapture(
        strategy_version=STRATEGY_VERSION,
        signal_trade_date=prepared.signal_trade_date,
        source_trade_date=prepared.source_trade_date,
        captured_at=prepared.captured_at,
        feature_cutoff_at=feature_cutoff,
        status="ready",
        input_fingerprint=fingerprint,
        candidates=allocated,
        recommendation_count=sum(
            candidate.recommendation_state == "recommended"
            for candidate in allocated
        ),
    )


def _validate_and_prepare_inputs(
    inputs: SwingStrategyInputs,
    *,
    preview: bool = False,
) -> SwingStrategyInputs:
    _require_aware(inputs.captured_at, "captured_at")
    captured_local = inputs.captured_at.astimezone(SHANGHAI)
    if captured_local.date() != inputs.signal_trade_date:
        raise SwingSignalInputError("capture_trade_date_mismatch")
    captured_time = captured_local.time().replace(tzinfo=None)
    if preview:
        if not any(start <= captured_time < end for start, end in PREVIEW_WINDOWS):
            raise SwingSignalInputError("outside_intraday_preview_window")
    elif not SIGNAL_CUTOFF <= captured_time < ENTRY_TIME:
        raise SwingSignalInputError("outside_1450_signal_window")
    if inputs.source_trade_date >= inputs.signal_trade_date:
        raise SwingSignalInputError("source_session_must_precede_signal")
    completed_dates = tuple(sorted(set(inputs.completed_dates)))
    if not completed_dates or completed_dates[-1] != inputs.source_trade_date:
        raise SwingSignalInputError("d_minus_one_completed_session_missing")
    _reject_future_or_outcome_columns(
        inputs.leader_rows,
        inputs.leader_history,
        inputs.stock_bars,
        inputs.concept_bars,
        inputs.benchmark_bars,
        inputs.stock_quotes,
        inputs.concept_quotes,
        inputs.benchmark_quotes,
        inputs.open_positions,
    )
    leaders = _prepare_leaders(inputs.leader_rows, inputs.source_trade_date)
    history = _prepare_leader_history(inputs.leader_history, inputs.source_trade_date)
    stock_bars = _prepare_stock_bars(inputs.stock_bars, inputs.source_trade_date)
    concept_bars = _prepare_concept_bars(inputs.concept_bars, inputs.source_trade_date)
    benchmark_bars = _prepare_benchmark_bars(
        inputs.benchmark_bars,
        inputs.source_trade_date,
    )
    stock_quotes = _prepare_quotes(
        inputs.stock_quotes,
        identity_column="vt_symbol",
        required_identities=set(leaders["vt_symbol"].astype(str)),
        observed_column="trade_time",
        inputs=inputs,
        label="stock",
    )
    concept_quotes = _prepare_quotes(
        inputs.concept_quotes,
        identity_column="sector_id",
        required_identities=set(leaders["sector_id"].astype(str)),
        observed_column="captured_at",
        inputs=inputs,
        label="concept",
    )
    benchmark_symbols = set(_benchmark_symbols())
    benchmark_quotes = _prepare_quotes(
        inputs.benchmark_quotes,
        identity_column="vt_symbol",
        required_identities=benchmark_symbols,
        observed_column="trade_time",
        inputs=inputs,
        label="benchmark",
    )
    positions = inputs.open_positions.copy()
    if positions.empty:
        positions = pd.DataFrame(columns=["vt_symbol", "sector_id"])
    _require_columns(positions, {"vt_symbol", "sector_id"}, "open position")
    positions["vt_symbol"] = positions["vt_symbol"].astype(str)
    positions["sector_id"] = positions["sector_id"].astype(str)
    return SwingStrategyInputs(
        source_trade_date=inputs.source_trade_date,
        signal_trade_date=inputs.signal_trade_date,
        captured_at=inputs.captured_at,
        leader_rows=leaders,
        leader_history=history,
        stock_bars=stock_bars,
        concept_bars=concept_bars,
        benchmark_bars=benchmark_bars,
        stock_quotes=stock_quotes,
        concept_quotes=concept_quotes,
        benchmark_quotes=benchmark_quotes,
        completed_dates=completed_dates,
        open_positions=positions,
    )


def _prepare_leaders(frame: pd.DataFrame, source_date: date) -> pd.DataFrame:
    required = {
        "source_trade_date",
        "ranking_version",
        "identity_mode",
        "sector_id",
        "sector_name",
        "vt_symbol",
        "rank",
        "is_top3",
        "cycle_start",
        "input_fingerprint",
        "raw",
    }
    _require_columns(frame, required, "D-1 leader")
    result = frame.copy()
    result["source_trade_date"] = pd.to_datetime(
        result["source_trade_date"], errors="raise"
    ).dt.date
    result = result.loc[
        result["source_trade_date"].eq(source_date)
        & result["ranking_version"].eq(FORWARD_LEADER_RANKING_VERSION)
        & result["identity_mode"].eq(IDENTITY_MODE)
        & result["is_top3"].astype(bool)
    ].copy()
    result["rank"] = pd.to_numeric(result["rank"], errors="raise").astype(int)
    if result.empty:
        raise SwingSignalInputError("d_minus_one_top3_missing")
    if result["rank"].lt(1).any() or result["rank"].gt(3).any():
        raise SwingSignalInputError("d_minus_one_rank_outside_top3")
    return result.reset_index(drop=True)


def _prepare_leader_history(frame: pd.DataFrame, source_date: date) -> pd.DataFrame:
    required = {
        "source_trade_date",
        "ranking_version",
        "identity_mode",
        "sector_id",
        "vt_symbol",
        "is_top3",
    }
    _require_columns(frame, required, "leader history")
    result = frame.copy()
    result["source_trade_date"] = pd.to_datetime(
        result["source_trade_date"], errors="raise"
    ).dt.date
    return result.loc[
        result["source_trade_date"].le(source_date)
        & result["ranking_version"].eq(FORWARD_LEADER_RANKING_VERSION)
        & result["identity_mode"].eq(IDENTITY_MODE)
        & result["is_top3"].astype(bool)
    ].copy()


def _prepare_stock_bars(frame: pd.DataFrame, source_date: date) -> pd.DataFrame:
    required = {
        "vt_symbol",
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
    }
    _require_columns(frame, required, "stock daily bar")
    result = frame.copy()
    result["vt_symbol"] = result["vt_symbol"].astype(str)
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.date
    result = result.loc[result["trade_date"].le(source_date)].copy()
    if result.duplicated(["vt_symbol", "trade_date"]).any():
        raise SwingSignalInputError("stock_daily_bar_identity_duplicated")
    return result.sort_values(["vt_symbol", "trade_date"], kind="stable").reset_index(drop=True)


def _prepare_concept_bars(frame: pd.DataFrame, source_date: date) -> pd.DataFrame:
    _require_columns(
        frame,
        {"sector_id", "trade_date", "close_price"},
        "concept daily bar",
    )
    result = frame.copy()
    result["sector_id"] = result["sector_id"].astype(str)
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.date
    result = result.loc[result["trade_date"].le(source_date)].copy()
    if result.duplicated(["sector_id", "trade_date"]).any():
        raise SwingSignalInputError("concept_daily_bar_identity_duplicated")
    return result


def _prepare_benchmark_bars(frame: pd.DataFrame, source_date: date) -> pd.DataFrame:
    _require_columns(
        frame,
        {"vt_symbol", "trade_date", "close_price"},
        "benchmark daily bar",
    )
    result = frame.copy()
    result["vt_symbol"] = result["vt_symbol"].astype(str)
    result["trade_date"] = pd.to_datetime(result["trade_date"], errors="raise").dt.date
    result = result.loc[
        result["trade_date"].le(source_date)
        & result["vt_symbol"].isin(_benchmark_symbols())
    ].copy()
    if result.duplicated(["vt_symbol", "trade_date"]).any():
        raise SwingSignalInputError("benchmark_daily_bar_identity_duplicated")
    return result


def _prepare_quotes(
    frame: pd.DataFrame,
    *,
    identity_column: str,
    required_identities: set[str],
    observed_column: str,
    inputs: SwingStrategyInputs,
    label: str,
) -> pd.DataFrame:
    _require_columns(frame, {identity_column, observed_column}, f"{label} quote")
    result = frame.copy()
    result[identity_column] = result[identity_column].astype(str)
    result = result.loc[result[identity_column].isin(required_identities)].copy()
    if result.duplicated(identity_column).any():
        raise SwingSignalInputError(f"{label}_quote_identity_duplicated")
    missing = sorted(required_identities - set(result[identity_column]))
    if missing:
        raise SwingSignalInputError(f"intraday_{label}_quotes_missing")
    observed = pd.to_datetime(result[observed_column], errors="raise", utc=True)
    captured = pd.Timestamp(inputs.captured_at).tz_convert("UTC")
    if observed.gt(captured).any():
        raise SwingSignalInputError(
            f"intraday_{label}_future_quote",
            f"future quote in intraday {label} snapshot",
        )
    observed_dates = observed.dt.tz_convert(SHANGHAI).dt.date
    if not observed_dates.eq(inputs.signal_trade_date).all():
        raise SwingSignalInputError(f"intraday_{label}_quotes_wrong_trade_date")
    ages = (captured - observed).dt.total_seconds()
    if ages.gt(QUOTE_MAX_AGE_SECONDS).any():
        raise SwingSignalInputError(f"intraday_{label}_quotes_stale")
    result[observed_column] = observed.dt.tz_convert(SHANGHAI)
    return result.reset_index(drop=True)


def _live_active_concepts(inputs: SwingStrategyInputs) -> set[str]:
    quotes = inputs.concept_quotes.set_index("sector_id")
    current_rows = []
    for sector_id, group in inputs.concept_bars.groupby("sector_id", sort=False):
        quote = quotes.loc[str(sector_id)]
        prior_close = float(group.sort_values("trade_date", kind="stable").iloc[-1]["close_price"])
        change_pct = _required_number(quote["change_pct"], "concept change_pct")
        current_rows.append(
            {
                "sector_id": str(sector_id),
                "concept_name": _concept_name(group, str(sector_id)),
                "trade_date": inputs.signal_trade_date,
                "close_price": prior_close * (1.0 + change_pct / 100.0),
                "source": str(quote.get("source") or "intraday.concept.quote"),
            }
        )
    concepts = pd.concat(
        [inputs.concept_bars, pd.DataFrame.from_records(current_rows)],
        ignore_index=True,
    )
    benchmark_quotes = inputs.benchmark_quotes.set_index("vt_symbol")
    current_benchmarks = pd.DataFrame.from_records(
        [
            {
                "vt_symbol": symbol,
                "trade_date": inputs.signal_trade_date,
                "close_price": _required_number(
                    benchmark_quotes.loc[symbol]["last_price"],
                    "benchmark last_price",
                ),
                "source": str(
                    benchmark_quotes.loc[symbol].get("source")
                    or "intraday.benchmark.quote"
                ),
            }
            for symbol in _benchmark_symbols()
        ]
    )
    benchmarks = pd.concat(
        [inputs.benchmark_bars, current_benchmarks],
        ignore_index=True,
    )
    research_dates = (*inputs.completed_dates, inputs.signal_trade_date)
    try:
        market_returns = build_market_returns(
            benchmarks,
            research_dates=research_dates,
        )
        cycles = build_cycle_candidates(concepts, market_returns)
    except ValueError as exc:
        raise SwingSignalInputError(
            "intraday_concept_cycle_unavailable",
            f"intraday concept cycle unavailable: {exc}",
        ) from exc
    active = cycles.loc[
        cycles["definition"].eq(FROZEN_MAIN_RISE_DEFINITION)
        & pd.to_datetime(cycles["trade_date"]).dt.date.eq(inputs.signal_trade_date)
        & cycles["in_cycle"].astype(bool)
    ]
    return set(active["sector_id"].astype(str))


def _provisional_stock_features(
    inputs: SwingStrategyInputs,
) -> dict[str, pd.DataFrame]:
    quotes = inputs.stock_quotes.set_index("vt_symbol")
    result: dict[str, pd.DataFrame] = {}
    for symbol, group in inputs.stock_bars.groupby("vt_symbol", sort=False):
        if symbol not in quotes.index:
            continue
        quote = quotes.loc[symbol]
        provisional = _provisional_bar(inputs.signal_trade_date, quote)
        bars = pd.concat(
            [group.drop(columns="vt_symbol"), pd.DataFrame([provisional])],
            ignore_index=True,
        )
        try:
            result[str(symbol)] = build_stock_wave_features(bars)
        except ValueError as exc:
            raise SwingSignalInputError(
                "provisional_stock_bar_invalid",
                f"provisional stock bar invalid for {symbol}: {exc}",
            ) from exc
    return result


def _provisional_bar(trade_date: date, quote: pd.Series) -> dict[str, object]:
    values = {
        "open_price": _required_number(quote.get("open_price"), "stock open_price"),
        "high_price": _required_number(quote.get("high_price"), "stock high_price"),
        "low_price": _required_number(quote.get("low_price"), "stock low_price"),
        "close_price": _required_number(quote.get("last_price"), "stock last_price"),
        "volume": _required_number(quote.get("volume"), "stock volume"),
    }
    if (
        min(values.values()) <= 0
        or values["high_price"] < max(values["open_price"], values["close_price"])
        or values["low_price"] > min(values["open_price"], values["close_price"])
    ):
        raise SwingSignalInputError("provisional_stock_ohlcv_incoherent")
    turnover = _optional_number(quote.get("turnover"))
    previous_close = _required_number(quote.get("previous_close"), "stock previous_close")
    return {
        "trade_date": trade_date,
        **values,
        "turnover": turnover,
        "change_pct": (values["close_price"] / previous_close - 1.0) * 100.0,
        "source": str(quote.get("source") or "intraday.stock.quote"),
    }


def _deduplicated_leaders(frame: pd.DataFrame) -> list[dict[str, Any]]:
    ordered = frame.sort_values(
        ["vt_symbol", "rank", "sector_id"],
        kind="stable",
    )
    return ordered.drop_duplicates("vt_symbol", keep="first").to_dict("records")


def _build_candidate(
    inputs: SwingStrategyInputs,
    leader: Mapping[str, Any],
    *,
    stock_features: Mapping[str, pd.DataFrame],
    active_concepts: set[str],
    fingerprint: str,
) -> SwingSignalCandidate:
    symbol = str(leader["vt_symbol"])
    sector_id = str(leader["sector_id"])
    raw = leader.get("raw") if isinstance(leader.get("raw"), Mapping) else {}
    stock_name = str(raw.get("stock_name") or "")
    quote = inputs.stock_quotes.loc[inputs.stock_quotes["vt_symbol"].eq(symbol)].iloc[0]
    features = stock_features.get(symbol)
    if not is_eligible_main_board(symbol, stock_name):
        return _unavailable_candidate(
            inputs,
            leader,
            quote,
            fingerprint=fingerprint,
            reason="unsupported_board",
        )
    if features is None:
        return _unavailable_candidate(
            inputs,
            leader,
            quote,
            fingerprint=fingerprint,
            reason="stock_daily_bars_unavailable",
        )
    anchor = _leader_spell_start(inputs, leader)
    try:
        ledger = build_leader_wave_ledger(
            features,
            anchor_date=anchor,
            observation_end=inputs.signal_trade_date,
            minimum_pullback_pct=MINIMUM_PULLBACK_PCT,
        )
    except ValueError:
        return _unavailable_candidate(
            inputs,
            leader,
            quote,
            fingerprint=fingerprint,
            reason="leader_wave_inputs_unavailable",
        )
    current = ledger.iloc[-1]
    wave_number = int(current["wave_number"])
    wave_start = pd.Timestamp(current["wave_start_date"]).date()
    peak_date = pd.Timestamp(current["peak_date"]).date()
    peak_price = float(current["peak_price"])
    stabilization = _first_stabilization(features, wave_start)
    structure_intact = _stock_structure_intact(
        features,
        peak_date=peak_date,
        signal_date=inputs.signal_trade_date,
    )
    concept_intact = sector_id in active_concepts
    impulse = features.loc[
        pd.to_datetime(features["trade_date"]).dt.date.between(wave_start, peak_date)
    ]
    strong_days = int(impulse["daily_return_pct"].ge(STRONG_DAY_THRESHOLD_PCT).sum())
    provisional = features.loc[
        pd.to_datetime(features["trade_date"]).dt.date.eq(inputs.signal_trade_date)
    ].iloc[0]
    previous_close = _required_number(quote.get("previous_close"), "stock previous_close")
    reason = _decision_reason(
        wave_number=wave_number,
        stabilization=stabilization,
        signal_date=inputs.signal_trade_date,
        structure_intact=structure_intact,
        concept_intact=concept_intact,
        strong_days=strong_days,
        provisional_close=float(provisional["close_price"]),
        reference_peak=peak_price,
    )
    eligible = reason == "eligible_swing_signal"
    return SwingSignalCandidate(
        signal_id=_signal_id(inputs.signal_trade_date, sector_id, symbol),
        strategy_version=STRATEGY_VERSION,
        signal_trade_date=inputs.signal_trade_date,
        source_trade_date=inputs.source_trade_date,
        captured_at=inputs.captured_at,
        feature_cutoff_at=_feature_cutoff(inputs.signal_trade_date),
        identity_mode=IDENTITY_MODE,
        vt_symbol=symbol,
        stock_name=stock_name,
        sector_id=sector_id,
        sector_name=str(leader.get("sector_name") or sector_id),
        rank=int(leader["rank"]),
        leader_spell_start=anchor,
        current_wave_number=wave_number,
        confirmed_higher_highs=wave_number - 1,
        wave_start_date=wave_start,
        reference_peak_date=peak_date,
        reference_peak_price=peak_price,
        pullback_confirmation_date=(
            stabilization.confirmation_date if stabilization is not None else None
        ),
        support_line=(stabilization.support_line if stabilization is not None else None),
        support_price=(stabilization.support_price if stabilization is not None else None),
        line_distance_low_pct=(
            stabilization.line_distance_low_pct if stabilization is not None else None
        ),
        provisional_open=float(provisional["open_price"]),
        provisional_high=float(provisional["high_price"]),
        provisional_low=float(provisional["low_price"]),
        provisional_close=float(provisional["close_price"]),
        provisional_volume=float(provisional["volume"]),
        provisional_turnover=_optional_number(provisional.get("turnover")),
        provisional_ma5=_optional_number(provisional.get("ma5")),
        previous_close=previous_close,
        strong_days_ge_9_5pct=strong_days,
        stock_structure_intact=structure_intact,
        concept_main_rise_intact=concept_intact,
        signal_eligible=eligible,
        decision_reason=reason,
        recommendation_state="eligible" if eligible else "not_eligible",
        portfolio_reason=None,
        quote_source=str(quote.get("source") or ""),
        quote_trade_time=pd.Timestamp(quote["trade_time"]).to_pydatetime(),
        input_fingerprint=fingerprint,
        evidence_level=EVIDENCE_LEVEL,
        raw={
            "leader_input_fingerprint": str(leader.get("input_fingerprint") or ""),
            "selection_inputs": [
                "d_minus_one_top3",
                "intraday_concept_main_rise",
                "two_confirmed_higher_highs",
                "first_ma5_stabilization",
                "prior_9_5pct_strong_day",
            ],
        },
    )


def _unavailable_candidate(
    inputs: SwingStrategyInputs,
    leader: Mapping[str, Any],
    quote: pd.Series,
    *,
    fingerprint: str,
    reason: str,
) -> SwingSignalCandidate:
    raw = leader.get("raw") if isinstance(leader.get("raw"), Mapping) else {}
    symbol = str(leader["vt_symbol"])
    sector_id = str(leader["sector_id"])
    provisional_close = _required_number(quote.get("last_price"), "stock last_price")
    return SwingSignalCandidate(
        signal_id=_signal_id(inputs.signal_trade_date, sector_id, symbol),
        strategy_version=STRATEGY_VERSION,
        signal_trade_date=inputs.signal_trade_date,
        source_trade_date=inputs.source_trade_date,
        captured_at=inputs.captured_at,
        feature_cutoff_at=_feature_cutoff(inputs.signal_trade_date),
        identity_mode=IDENTITY_MODE,
        vt_symbol=symbol,
        stock_name=str(raw.get("stock_name") or ""),
        sector_id=sector_id,
        sector_name=str(leader.get("sector_name") or sector_id),
        rank=int(leader["rank"]),
        leader_spell_start=inputs.source_trade_date,
        current_wave_number=0,
        confirmed_higher_highs=0,
        wave_start_date=inputs.source_trade_date,
        reference_peak_date=inputs.source_trade_date,
        reference_peak_price=0.0,
        pullback_confirmation_date=None,
        support_line=None,
        support_price=None,
        line_distance_low_pct=None,
        provisional_open=_required_number(quote.get("open_price"), "stock open_price"),
        provisional_high=_required_number(quote.get("high_price"), "stock high_price"),
        provisional_low=_required_number(quote.get("low_price"), "stock low_price"),
        provisional_close=provisional_close,
        provisional_volume=_required_number(quote.get("volume"), "stock volume"),
        provisional_turnover=_optional_number(quote.get("turnover")),
        provisional_ma5=None,
        previous_close=_required_number(quote.get("previous_close"), "stock previous_close"),
        strong_days_ge_9_5pct=0,
        stock_structure_intact=False,
        concept_main_rise_intact=False,
        signal_eligible=False,
        decision_reason=reason,
        recommendation_state="not_eligible",
        portfolio_reason=None,
        quote_source=str(quote.get("source") or ""),
        quote_trade_time=pd.Timestamp(quote["trade_time"]).to_pydatetime(),
        input_fingerprint=fingerprint,
        evidence_level=EVIDENCE_LEVEL,
        raw={"leader_input_fingerprint": str(leader.get("input_fingerprint") or "")},
    )


def _leader_spell_start(
    inputs: SwingStrategyInputs,
    leader: Mapping[str, Any],
) -> date:
    history = inputs.leader_history.loc[
        inputs.leader_history["sector_id"].eq(str(leader["sector_id"]))
        & inputs.leader_history["vt_symbol"].eq(str(leader["vt_symbol"]))
    ]
    observed = set(history["source_trade_date"])
    calendar = list(inputs.completed_dates)
    position = calendar.index(inputs.source_trade_date)
    anchor = inputs.source_trade_date
    sessions = 0
    while position >= 0 and calendar[position] in observed:
        anchor = calendar[position]
        position -= 1
        sessions += 1
        if sessions >= MAX_LEADER_SPELL_SESSIONS:
            break
    return anchor


def _first_stabilization(
    features: pd.DataFrame,
    wave_start: date,
) -> _Stabilization | None:
    frame = features.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise").dt.date
    window = frame.loc[frame["trade_date"].ge(wave_start)].reset_index(drop=True)
    if len(window) < 2:
        return None
    peak = float(window.iloc[0]["high_price"])
    peak_date = wave_start
    confirmation: date | None = None
    deepest: str | None = None
    for position in range(1, len(window)):
        bar = window.iloc[position]
        trade_date = bar["trade_date"]
        high = float(bar["high_price"])
        low = float(bar["low_price"])
        if confirmation is None:
            if high > peak:
                peak = high
                peak_date = trade_date
            if trade_date > peak_date and low <= peak * (1.0 - MINIMUM_PULLBACK_PCT / 100.0):
                confirmation = trade_date
            else:
                continue
        elif high > peak:
            return None
        approached = [
            line
            for line in SUPPORT_DEPTH
            if (support := _optional_number(bar.get(line))) is not None
            and low <= support * (1.0 + APPROACH_TOLERANCE_PCT / 100.0)
        ]
        if approached:
            deepest_today = max(approached, key=SUPPORT_DEPTH.__getitem__)
            if deepest is None or SUPPORT_DEPTH[deepest_today] > SUPPORT_DEPTH[deepest]:
                deepest = deepest_today
        if deepest is None:
            continue
        support_price = _optional_number(bar.get(deepest))
        previous_close = float(window.iloc[position - 1]["close_price"])
        close = float(bar["close_price"])
        if support_price is not None and close >= support_price and close >= previous_close:
            return _Stabilization(
                signal_date=trade_date,
                confirmation_date=confirmation,
                support_line=deepest,
                support_price=support_price,
                line_distance_low_pct=(low / support_price - 1.0) * 100.0,
            )
    return None


def _stock_structure_intact(
    features: pd.DataFrame,
    *,
    peak_date: date,
    signal_date: date,
) -> bool:
    dates = pd.to_datetime(features["trade_date"], errors="raise").dt.date
    path = features.loc[dates.gt(peak_date) & dates.le(signal_date)].copy()
    if path.empty:
        return True
    below_ma10 = path["close_price"].lt(path["ma10"]).fillna(False)
    broken = path["close_price"].lt(path["ma20"]).fillna(False) | (
        below_ma10
        & below_ma10.shift(1, fill_value=False)
        & path["ma5"].le(path["ma10"]).fillna(False)
    )
    return not bool(broken.any())


def _decision_reason(
    *,
    wave_number: int,
    stabilization: _Stabilization | None,
    signal_date: date,
    structure_intact: bool,
    concept_intact: bool,
    strong_days: int,
    provisional_close: float,
    reference_peak: float,
) -> str:
    if wave_number < 3:
        return "fewer_than_two_confirmed_higher_highs"
    if wave_number > 3:
        return "later_than_first_post_confirmation_pullback"
    if stabilization is None or stabilization.signal_date != signal_date:
        return "first_wave_three_stabilization_not_observed"
    if stabilization.support_line != "ma5":
        return "first_stabilized_support_not_ma5"
    if not structure_intact:
        return "stock_structure_broken"
    if not concept_intact:
        return "concept_main_rise_not_intact_at_1450"
    if strong_days < MINIMUM_PRIOR_STRONG_DAYS:
        return "prior_strong_day_missing"
    if provisional_close >= reference_peak:
        return "reference_peak_already_rebroken"
    return "eligible_swing_signal"


def _allocate_recommendations(
    candidates: Sequence[SwingSignalCandidate],
    open_positions: pd.DataFrame,
) -> tuple[SwingSignalCandidate, ...]:
    active_symbols = set(open_positions["vt_symbol"].astype(str))
    active_sectors = set(open_positions["sector_id"].astype(str))
    slots = max(MAX_POSITIONS - len(open_positions), 0)
    ordered = sorted(candidates, key=lambda row: (row.rank, row.vt_symbol, row.sector_id))
    allocated: dict[str, SwingSignalCandidate] = {}
    for candidate in ordered:
        if not candidate.signal_eligible:
            allocated[candidate.signal_id] = candidate
            continue
        if candidate.vt_symbol in active_symbols:
            reason = "active_symbol_position"
        elif candidate.sector_id in active_sectors:
            reason = "same_concept_position"
        elif slots <= 0:
            reason = "capacity_full"
        else:
            allocated[candidate.signal_id] = replace(
                candidate,
                recommendation_state="recommended",
                portfolio_reason=None,
            )
            active_symbols.add(candidate.vt_symbol)
            active_sectors.add(candidate.sector_id)
            slots -= 1
            continue
        allocated[candidate.signal_id] = replace(
            candidate,
            recommendation_state="skipped",
            portfolio_reason=reason,
        )
    return tuple(allocated[candidate.signal_id] for candidate in candidates)


def _feature_cutoff(signal_date: date) -> datetime:
    return datetime.combine(signal_date, SIGNAL_CUTOFF, tzinfo=SHANGHAI)


def _signal_id(signal_date: date, sector_id: str, vt_symbol: str) -> str:
    return ":".join((STRATEGY_VERSION, signal_date.isoformat(), sector_id, vt_symbol))


def _concept_name(group: pd.DataFrame, fallback: str) -> str:
    if "concept_name" not in group or group["concept_name"].dropna().empty:
        return fallback
    return str(group["concept_name"].dropna().iloc[-1])


def _benchmark_symbols() -> tuple[str, ...]:
    return ("000300.SSE", "000905.SSE", "000852.SSE")


def _fingerprint_inputs(inputs: SwingStrategyInputs) -> str:
    payload = {
        "strategy_version": STRATEGY_VERSION,
        "source_trade_date": inputs.source_trade_date.isoformat(),
        "signal_trade_date": inputs.signal_trade_date.isoformat(),
        "captured_at": inputs.captured_at.isoformat(),
        "frames": {
            "leader_rows": _frame_records(inputs.leader_rows),
            "leader_history": _frame_records(inputs.leader_history),
            "stock_bars": _frame_records(inputs.stock_bars),
            "concept_bars": _frame_records(inputs.concept_bars),
            "benchmark_bars": _frame_records(inputs.benchmark_bars),
            "stock_quotes": _frame_records(inputs.stock_quotes),
            "concept_quotes": _frame_records(inputs.concept_quotes),
            "benchmark_quotes": _frame_records(inputs.benchmark_quotes),
            "open_positions": _frame_records(inputs.open_positions),
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _frame_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty:
        return []
    result = frame.copy().reindex(sorted(frame.columns), axis=1)
    return json.loads(
        result.to_json(orient="records", date_format="iso", date_unit="us")
    )


def _reject_future_or_outcome_columns(*frames: pd.DataFrame) -> None:
    prohibited = sorted(
        {
            str(column)
            for frame in frames
            for column in frame.columns
            if str(column).lower().startswith(PROHIBITED_PREFIXES)
        }
    )
    if prohibited:
        raise SwingSignalInputError(
            "future_or_outcome_columns_prohibited",
            "future or outcome columns are prohibited: " + ", ".join(prohibited),
        )


def _required_number(value: object, label: str) -> float:
    number = _optional_number(value)
    if number is None:
        raise SwingSignalInputError(f"{label.replace(' ', '_')}_missing")
    return number


def _optional_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise SwingSignalInputError(
            f"{label.replace(' ', '_')}_columns_missing",
            f"missing {label} columns: {', '.join(missing)}",
        )


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SwingSignalInputError(f"{label}_must_be_timezone_aware")


def _json_default(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")
