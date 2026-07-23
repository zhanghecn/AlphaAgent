"""Causal completed-minute buffers built from sampled live quotes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from math import isfinite


MAX_BUFFER_MINUTES = 12
MINIMUM_SCOREABLE_LABELS = 8


@dataclass(frozen=True)
class _QuoteSample:
    captured_at: datetime
    price: float
    cumulative_volume: float | None
    cumulative_turnover: float | None


@dataclass
class _SampledMinute:
    bar_time: datetime
    samples: dict[datetime, _QuoteSample] = field(default_factory=dict)

    def add(self, sample: _QuoteSample) -> None:
        self.samples[sample.captured_at] = sample

    def aggregate(self) -> dict[str, object] | None:
        ordered = [self.samples[key] for key in sorted(self.samples)]
        if not ordered:
            return None
        prices = [sample.price for sample in ordered]
        closing = ordered[-1]
        return {
            "bar_time": self.bar_time,
            "open_price": prices[0],
            "high_price": max(prices),
            "low_price": min(prices),
            "close_price": prices[-1],
            "cumulative_volume": closing.cumulative_volume,
            "cumulative_turnover": closing.cumulative_turnover,
        }


@dataclass(frozen=True)
class _QualityPoolSample:
    captured_at: datetime
    candidates: tuple[dict[str, object], ...]


def live_minute_close(captured_at: datetime) -> datetime | None:
    """Map one quote sample to the next completed A-share minute label."""

    clock = captured_at.time().replace(tzinfo=None)
    if not (
        time(9, 30) <= clock < time(11, 30)
        or time(13, 0) <= clock < time(15, 0)
    ):
        return None
    return captured_at.replace(second=0, microsecond=0) + timedelta(minutes=1)


class LiveMinuteBuffer:
    """Keep a bounded, current-day quote and quality-pool prefix."""

    def __init__(self) -> None:
        self._trade_date: date | None = None
        self._bars: dict[str, dict[datetime, _SampledMinute]] = {}
        self._quality_pools: dict[datetime, _QualityPoolSample] = {}

    def ingest(
        self,
        captured_at: datetime,
        quotes: Sequence[Mapping[str, object]],
    ) -> None:
        self._start_trade_date(captured_at.date())
        for quote in quotes:
            sample_at = _datetime(quote.get("quote_observed_at")) or captured_at
            if sample_at.date() != captured_at.date():
                continue
            bar_time = live_minute_close(sample_at)
            symbol = str(quote.get("vt_symbol") or "").strip()
            price = _positive(quote.get("last_price"))
            if bar_time is None or not symbol or price is None:
                continue
            symbol_bars = self._bars.setdefault(symbol, {})
            minute = symbol_bars.setdefault(bar_time, _SampledMinute(bar_time))
            minute.add(
                _QuoteSample(
                    captured_at=sample_at,
                    price=price,
                    cumulative_volume=_nonnegative(quote.get("volume")),
                    cumulative_turnover=_nonnegative(quote.get("turnover")),
                )
            )
            while len(symbol_bars) > MAX_BUFFER_MINUTES:
                del symbol_bars[min(symbol_bars)]

    def completed_bars(
        self,
        vt_symbol: str,
        cutoff: datetime,
        count: int = MINIMUM_SCOREABLE_LABELS,
    ) -> list[dict[str, object]]:
        aggregates = [
            aggregate
            for bar_time in sorted(self._bars.get(vt_symbol, {}))
            if bar_time <= cutoff
            and (
                aggregate := self._bars[vt_symbol][bar_time].aggregate()
            ) is not None
        ]
        completed: list[dict[str, object]] = []
        previous_volume: float | None = None
        previous_turnover: float | None = None
        for aggregate in aggregates:
            current_volume = _nonnegative(aggregate.get("cumulative_volume"))
            current_turnover = _nonnegative(aggregate.get("cumulative_turnover"))
            completed.append(
                {
                    key: value
                    for key, value in aggregate.items()
                    if key not in {"cumulative_volume", "cumulative_turnover"}
                }
                | {
                    "volume": _nonnegative_delta(current_volume, previous_volume),
                    "turnover": _nonnegative_delta(
                        current_turnover,
                        previous_turnover,
                    ),
                }
            )
            previous_volume = current_volume
            previous_turnover = current_turnover
        return completed[-max(int(count), 1) :]

    def source_quality(self, vt_symbol: str, cutoff: datetime) -> str:
        bars = self.completed_bars(vt_symbol, cutoff)
        expected_close = cutoff.replace(second=0, microsecond=0)
        ready = bool(
            len(bars) >= MINIMUM_SCOREABLE_LABELS
            and bars[-1].get("bar_time") == expected_close
            and all(
                bar.get("volume") is not None and bar.get("turnover") is not None
                for bar in bars[-7:]
            )
        )
        return "sampled_quote_proxy" if ready else "insufficient_live_prefix"

    def ingest_quality_pool(
        self,
        captured_at: datetime,
        rows: Sequence[Mapping[str, object]],
    ) -> None:
        self._start_trade_date(captured_at.date())
        bar_time = live_minute_close(captured_at)
        if bar_time is None:
            return
        current = self._quality_pools.get(bar_time)
        if current is not None and current.captured_at > captured_at:
            return
        self._quality_pools[bar_time] = _QualityPoolSample(
            captured_at=captured_at,
            candidates=tuple(dict(row) for row in rows),
        )
        while len(self._quality_pools) > MAX_BUFFER_MINUTES:
            del self._quality_pools[min(self._quality_pools)]

    def completed_quality_pool_snapshots(
        self,
        cutoff: datetime,
    ) -> list[dict[str, object]]:
        return [
            {
                "captured_at": bar_time,
                "candidates": [dict(row) for row in sample.candidates],
            }
            for bar_time, sample in sorted(self._quality_pools.items())
            if bar_time <= cutoff
        ]

    def _start_trade_date(self, trade_date: date) -> None:
        if self._trade_date is None:
            self._trade_date = trade_date
            return
        if trade_date > self._trade_date:
            self._trade_date = trade_date
            self._bars.clear()
            self._quality_pools.clear()


def _datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _positive(value: object) -> float | None:
    parsed = _number(value)
    return parsed if parsed is not None and parsed > 0 else None


def _nonnegative(value: object) -> float | None:
    parsed = _number(value)
    return parsed if parsed is not None and parsed >= 0 else None


def _nonnegative_delta(
    current: float | None,
    previous: float | None,
) -> float | None:
    if current is None or previous is None or current < previous:
        return None
    return current - previous
