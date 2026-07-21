"""Point-in-time support tests and trade paths inside one leader campaign."""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd


DAILY_BAR_COLUMNS = (
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
)
SUPPORT_LINES = ("ma5", "ma10", "ma20")
SUPPORT_DEPTH = {line: depth for depth, line in enumerate(SUPPORT_LINES, start=1)}
DEFAULT_APPROACH_TOLERANCE_PCT = 2.0
DEFAULT_ROUND_TRIP_COST_PCT = 0.2
DEFAULT_IGNITION_RETURN_PCT = 5.0
DEFAULT_IGNITION_VOLUME_RATIO = 1.5


def build_stock_wave_features(daily_bars: pd.DataFrame) -> pd.DataFrame:
    """Build ordered trailing features for one stock without backward fill."""

    bars = _prepare_daily_bars(daily_bars)
    bars["daily_return_pct"] = (
        bars["close_price"].pct_change(fill_method=None) * 100.0
    )
    for window in (5, 10, 20):
        bars[f"ma{window}"] = bars["close_price"].rolling(
            window,
            min_periods=window,
        ).mean()
        bars[f"ma{window}_slope_3d_pct"] = (
            bars[f"ma{window}"] / bars[f"ma{window}"].shift(3) - 1.0
        ) * 100.0
    bars["prior_high20"] = (
        bars["high_price"].shift(1).rolling(20, min_periods=20).max()
    )
    bars["prior_volume_median_5d"] = (
        bars["volume"].shift(1).rolling(5, min_periods=5).median()
    )
    bars["volume_ratio_prior5"] = bars["volume"] / bars[
        "prior_volume_median_5d"
    ].replace(0.0, np.nan)
    bars["trend_aligned"] = (
        bars["ma5"].gt(bars["ma10"]) & bars["ma10"].gt(bars["ma20"])
    ).fillna(False)
    bars["feature_cutoff_date"] = bars["trade_date"]
    return bars


def find_campaign_ignitions(
    features: pd.DataFrame,
    *,
    minimum_return_pct: float = DEFAULT_IGNITION_RETURN_PCT,
    minimum_volume_ratio: float = DEFAULT_IGNITION_VOLUME_RATIO,
) -> pd.DataFrame:
    """Return the first day of each trailing breakout-and-volume ignition run."""

    if minimum_return_pct <= 0:
        raise ValueError("minimum ignition return must be positive")
    if minimum_volume_ratio <= 0:
        raise ValueError("minimum ignition volume ratio must be positive")
    required = (
        "trade_date",
        "close_price",
        "daily_return_pct",
        "prior_high20",
        "volume_ratio_prior5",
        "trend_aligned",
    )
    _require_columns(features, required, "stock wave feature")
    frame = features.copy()
    qualified = _strict_ignition_mask(
        frame,
        minimum_return_pct=minimum_return_pct,
        minimum_volume_ratio=minimum_volume_ratio,
    )
    starts = qualified & ~qualified.shift(1, fill_value=False)
    ignitions = frame.loc[starts].copy()
    ignitions["ignition_number"] = np.arange(1, len(ignitions) + 1)
    ignitions["ignition_definition"] = (
        "return>=5pct/prior20_high_break/volume>=1.5x/ma5>ma10>ma20"
    )
    return ignitions.reset_index(drop=True)


def build_declared_continuation_trade(
    features: pd.DataFrame,
    *,
    anchor_date: date,
    round_trip_cost_pct: float = DEFAULT_ROUND_TRIP_COST_PCT,
) -> dict[str, Any]:
    """Diagnose one declared continuation date against its visible prior peak."""

    if round_trip_cost_pct < 0:
        raise ValueError("round-trip cost cannot be negative")
    bars = _prepare_feature_dates(features).reset_index(drop=True)
    _require_columns(
        bars,
        ("daily_return_pct", "prior_high20", "trend_aligned"),
        "stock wave feature",
    )
    anchor = pd.Timestamp(anchor_date).normalize()
    matches = bars.loc[bars["trade_date"].eq(anchor)]
    if len(matches) != 1:
        raise ValueError("declared continuation anchor must have one feature row")
    anchor_row = matches.iloc[0]
    peak_row = _prior_reference_peak(bars, anchor_row)
    pre_anchor = bars.loc[
        bars["trade_date"].gt(peak_row["trade_date"])
        & bars["trade_date"].le(anchor)
    ]
    trough = pre_anchor.loc[pre_anchor["low_price"].idxmin()]
    path = bars.loc[bars["trade_date"].ge(anchor)].copy()
    reference_peak = float(peak_row["high_price"])
    target = _first_higher_high(path, anchor, reference_peak)
    defensive = _second_close_below_ma20(path, anchor)
    exit_row, exit_reason = _first_exit(target, defensive)
    metrics = _path_metrics(
        path,
        entry_date=anchor,
        entry_price=float(anchor_row["close_price"]),
        exit_row=exit_row,
        round_trip_cost_pct=round_trip_cost_pct,
    )
    if exit_reason == "higher_high_confirmed":
        exit_reason = "prior_peak_rebroken"
    return {
        **_declared_anchor_features(anchor_row, peak_row, trough),
        "entry_date": anchor,
        "entry_price": float(anchor_row["close_price"]),
        "entry_proxy": "declared_anchor_day_close",
        "executable_exit_reason": exit_reason,
        **metrics,
        "eventually_rebroke_reference_peak": target is not None,
        "unrestricted_rebreak_date": (
            pd.Timestamp(target["trade_date"]) if target is not None else pd.NaT
        ),
        "round_trip_cost_pct": round_trip_cost_pct,
        "feature_cutoff_date": anchor,
    }


def build_first_support_approaches(
    features: pd.DataFrame,
    wave_ledger: pd.DataFrame,
    *,
    approach_tolerance_pct: float = DEFAULT_APPROACH_TOLERANCE_PCT,
) -> pd.DataFrame:
    """Emit the first MA5, MA10 and MA20 approach after every wave peak."""

    if not 0 <= approach_tolerance_pct <= 10:
        raise ValueError("approach tolerance must be between zero and 10")
    bars = _prepare_feature_dates(features)
    waves = _prepare_wave_dates(wave_ledger)
    rows: list[dict[str, Any]] = []
    for wave in waves.to_dict("records"):
        pullback = _pullback_window(bars, wave)
        if pullback.empty:
            continue
        impulse_volume = _impulse_volume_median(bars, wave)
        for support_line in SUPPORT_LINES:
            first = _first_line_approach(
                pullback,
                support_line,
                approach_tolerance_pct,
            )
            if first is None:
                continue
            rows.append(
                _approach_row(
                    wave,
                    first,
                    support_line=support_line,
                    impulse_volume_median=impulse_volume,
                    tolerance_pct=approach_tolerance_pct,
                )
            )
    if not rows:
        return pd.DataFrame(columns=_approach_columns())
    result = pd.DataFrame.from_records(rows)
    result["execution_selected"] = False
    deepest = result.groupby(
        ["wave_number", "approach_date"],
        sort=False,
    )["support_depth"].idxmax()
    result.loc[deepest, "execution_selected"] = True
    return result.sort_values(
        ["wave_number", "support_depth", "approach_date"],
        kind="stable",
    ).reset_index(drop=True)


def build_wave_pullback_trades(
    approaches: pd.DataFrame,
    features: pd.DataFrame,
    wave_ledger: pd.DataFrame,
    *,
    round_trip_cost_pct: float = DEFAULT_ROUND_TRIP_COST_PCT,
) -> pd.DataFrame:
    """Execute selected tail entries until a new high, structural exit, or censor."""

    if round_trip_cost_pct < 0:
        raise ValueError("round-trip cost cannot be negative")
    required = (
        "wave_number",
        "support_line",
        "approach_date",
        "entry_price",
        "peak_price",
        "execution_selected",
    )
    _require_columns(approaches, required, "support approach")
    bars = _prepare_feature_dates(features).reset_index(drop=True)
    waves = _prepare_wave_dates(wave_ledger).set_index("wave_number", drop=False)
    selected = approaches.loc[approaches["execution_selected"].astype(bool)].copy()
    selected["approach_date"] = pd.to_datetime(
        selected["approach_date"], errors="raise"
    ).dt.normalize()
    rows: list[dict[str, Any]] = []
    for approach in selected.to_dict("records"):
        wave_number = int(approach["wave_number"])
        if wave_number not in waves.index:
            raise ValueError(f"missing wave {wave_number} for support approach")
        wave = waves.loc[wave_number].to_dict()
        rows.append(
            _trade_row(
                approach,
                wave,
                bars,
                round_trip_cost_pct=round_trip_cost_pct,
            )
        )
    return pd.DataFrame.from_records(rows, columns=_trade_columns()).sort_values(
        ["entry_date", "wave_number", "support_depth"],
        kind="stable",
    ).reset_index(drop=True)


def classify_volume_ratio(value: object) -> str:
    """Classify one causal volume ratio using fixed descriptive bands."""

    numeric = _finite_or_none(value)
    if numeric is None:
        return "unavailable"
    if numeric < 0.8:
        return "contraction"
    if numeric <= 1.2:
        return "normal"
    if numeric < 1.5:
        return "expansion"
    return "explosion"


def _strict_ignition_mask(
    frame: pd.DataFrame,
    *,
    minimum_return_pct: float,
    minimum_volume_ratio: float,
) -> pd.Series:
    return (
        frame["daily_return_pct"].ge(minimum_return_pct)
        & frame["close_price"].gt(frame["prior_high20"])
        & frame["volume_ratio_prior5"].ge(minimum_volume_ratio)
        & frame["trend_aligned"].astype(bool)
    ).fillna(False)


def _prior_reference_peak(
    bars: pd.DataFrame,
    anchor_row: pd.Series,
) -> pd.Series:
    peak_price = _finite_or_none(anchor_row["prior_high20"])
    if peak_price is None:
        raise ValueError("declared continuation anchor requires a prior-20 high")
    history = bars.loc[bars["trade_date"].lt(anchor_row["trade_date"])].tail(20)
    matches = history.loc[np.isclose(history["high_price"], peak_price)]
    if matches.empty:
        raise ValueError("prior-20 high date is unavailable")
    return matches.iloc[-1]


def _declared_anchor_features(
    anchor: pd.Series,
    peak: pd.Series,
    trough: pd.Series,
) -> dict[str, Any]:
    peak_price = float(peak["high_price"])
    close_price = float(anchor["close_price"])
    strict_ignition = bool(
        _strict_ignition_mask(
            anchor.to_frame().T,
            minimum_return_pct=DEFAULT_IGNITION_RETURN_PCT,
            minimum_volume_ratio=DEFAULT_IGNITION_VOLUME_RATIO,
        ).iloc[0]
    )
    result: dict[str, Any] = {
        "anchor_contract": "user_declared_continuation_candidate",
        "strict_ignition": strict_ignition,
        "reference_peak_date": pd.Timestamp(peak["trade_date"]),
        "reference_peak_price": peak_price,
        "pre_anchor_trough_date": pd.Timestamp(trough["trade_date"]),
        "pre_anchor_trough_price": float(trough["low_price"]),
        "pre_anchor_pullback_pct": (
            float(trough["low_price"]) / peak_price - 1.0
        )
        * 100.0,
        "anchor_daily_return_pct": _finite_or_none(anchor["daily_return_pct"]),
        "anchor_prior_high_break_pct": (close_price / peak_price - 1.0) * 100.0,
        "anchor_volume_ratio_prior5": _finite_or_none(anchor["volume_ratio_prior5"]),
        "anchor_volume_class_prior5": classify_volume_ratio(
            anchor["volume_ratio_prior5"]
        ),
        "anchor_trend_aligned": bool(anchor["trend_aligned"]),
    }
    for line in SUPPORT_LINES:
        support = float(anchor[line])
        result[f"anchor_{line}"] = support
        result[f"anchor_low_to_{line}_pct"] = (
            float(anchor["low_price"]) / support - 1.0
        ) * 100.0
        result[f"anchor_close_above_{line}"] = bool(close_price >= support)
    return result


def _prepare_daily_bars(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, DAILY_BAR_COLUMNS, "daily bar")
    bars = frame.loc[:, list(DAILY_BAR_COLUMNS)].copy()
    bars["trade_date"] = pd.to_datetime(
        bars["trade_date"], errors="raise"
    ).dt.normalize()
    if bars["trade_date"].duplicated().any():
        raise ValueError("daily bar dates must be unique for one stock")
    numeric_columns = list(DAILY_BAR_COLUMNS[1:])
    bars[numeric_columns] = bars[numeric_columns].apply(pd.to_numeric, errors="raise")
    values = bars[numeric_columns].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("daily OHLCV values must be finite and positive")
    invalid_range = (
        bars["high_price"].lt(bars[["open_price", "close_price"]].max(axis=1))
        | bars["high_price"].lt(bars["low_price"])
        | bars["low_price"].gt(bars[["open_price", "close_price"]].min(axis=1))
    )
    if invalid_range.any():
        raise ValueError("daily OHLC ranges are inconsistent")
    return bars.sort_values("trade_date", kind="stable").reset_index(drop=True)


def _prepare_feature_dates(frame: pd.DataFrame) -> pd.DataFrame:
    required = (
        *DAILY_BAR_COLUMNS,
        *SUPPORT_LINES,
        "volume_ratio_prior5",
    )
    _require_columns(frame, required, "stock wave feature")
    features = frame.copy()
    features["trade_date"] = pd.to_datetime(
        features["trade_date"], errors="raise"
    ).dt.normalize()
    if features["trade_date"].duplicated().any():
        raise ValueError("stock wave feature dates must be unique")
    return features.sort_values("trade_date", kind="stable").reset_index(drop=True)


def _prepare_wave_dates(frame: pd.DataFrame) -> pd.DataFrame:
    required = (
        "wave_number",
        "wave_start_date",
        "peak_date",
        "peak_price",
        "higher_high_date",
        "resolution_status",
        "observation_end",
    )
    _require_columns(frame, required, "leader wave")
    waves = frame.copy()
    for column in (
        "wave_start_date",
        "peak_date",
        "higher_high_date",
        "observation_end",
    ):
        waves[column] = pd.to_datetime(waves[column], errors="coerce").dt.normalize()
    waves["wave_number"] = pd.to_numeric(
        waves["wave_number"], errors="raise"
    ).astype(int)
    if waves["wave_number"].duplicated().any():
        raise ValueError("leader wave numbers must be unique")
    return waves.sort_values("wave_number", kind="stable").reset_index(drop=True)


def _pullback_window(
    bars: pd.DataFrame,
    wave: dict[str, Any],
) -> pd.DataFrame:
    peak_date = pd.Timestamp(wave["peak_date"])
    end_date = wave["higher_high_date"]
    if pd.isna(end_date):
        end_date = wave["observation_end"]
        boundary = bars["trade_date"].le(pd.Timestamp(end_date))
    else:
        boundary = bars["trade_date"].lt(pd.Timestamp(end_date))
    return bars.loc[bars["trade_date"].gt(peak_date) & boundary].copy()


def _impulse_volume_median(
    bars: pd.DataFrame,
    wave: dict[str, Any],
) -> float | None:
    impulse = bars.loc[
        bars["trade_date"].between(
            pd.Timestamp(wave["wave_start_date"]),
            pd.Timestamp(wave["peak_date"]),
        ),
        "volume",
    ]
    if impulse.empty:
        return None
    return _finite_or_none(impulse.median())


def _first_line_approach(
    pullback: pd.DataFrame,
    support_line: str,
    tolerance_pct: float,
) -> pd.Series | None:
    line = pd.to_numeric(pullback[support_line], errors="coerce")
    threshold = line * (1.0 + tolerance_pct / 100.0)
    candidates = pullback.loc[line.notna() & pullback["low_price"].le(threshold)]
    return candidates.iloc[0] if not candidates.empty else None


def _approach_row(
    wave: dict[str, Any],
    bar: pd.Series,
    *,
    support_line: str,
    impulse_volume_median: float | None,
    tolerance_pct: float,
) -> dict[str, Any]:
    support_price = float(bar[support_line])
    volume = float(bar["volume"])
    prior_ratio = _finite_or_none(bar["volume_ratio_prior5"])
    impulse_ratio = (
        volume / impulse_volume_median
        if impulse_volume_median is not None and impulse_volume_median > 0
        else None
    )
    close_price = float(bar["close_price"])
    peak_price = float(wave["peak_price"])
    approach_date = pd.Timestamp(bar["trade_date"])
    return {
        "approach_id": (
            f"wave-{int(wave['wave_number'])}:{support_line}:"
            f"{approach_date.date().isoformat()}"
        ),
        "wave_number": int(wave["wave_number"]),
        "wave_start_date": pd.Timestamp(wave["wave_start_date"]),
        "peak_date": pd.Timestamp(wave["peak_date"]),
        "peak_price": peak_price,
        "wave_resolution_status": str(wave["resolution_status"]),
        "unrestricted_higher_high_date": wave["higher_high_date"],
        "support_line": support_line,
        "support_depth": SUPPORT_DEPTH[support_line],
        "approach_date": approach_date,
        "support_price": support_price,
        "approach_tolerance_pct": tolerance_pct,
        "line_distance_low_pct": (
            float(bar["low_price"]) / support_price - 1.0
        ) * 100.0,
        "line_distance_close_pct": (close_price / support_price - 1.0) * 100.0,
        "close_reclaimed_support": bool(close_price >= support_price),
        "entry_price": close_price,
        "peak_to_entry_drawdown_pct": (close_price / peak_price - 1.0) * 100.0,
        "volume": volume,
        "prior_volume_median_5d": _finite_or_none(
            bar.get("prior_volume_median_5d")
        ),
        "impulse_volume_median": impulse_volume_median,
        "volume_ratio_prior5": prior_ratio,
        "volume_ratio_impulse": impulse_ratio,
        "volume_class_prior5": classify_volume_ratio(prior_ratio),
        "volume_class_impulse": classify_volume_ratio(impulse_ratio),
        "ma5": _finite_or_none(bar["ma5"]),
        "ma10": _finite_or_none(bar["ma10"]),
        "ma20": _finite_or_none(bar["ma20"]),
        "trend_aligned": bool(bar.get("trend_aligned", False)),
        "feature_cutoff_date": approach_date,
        "execution_selected": False,
    }


def _trade_row(
    approach: dict[str, Any],
    wave: dict[str, Any],
    bars: pd.DataFrame,
    *,
    round_trip_cost_pct: float,
) -> dict[str, Any]:
    entry_date = pd.Timestamp(approach["approach_date"])
    observation_end = pd.Timestamp(wave["observation_end"])
    path = bars.loc[
        bars["trade_date"].between(entry_date, observation_end)
    ].copy()
    if path.empty or path.iloc[0]["trade_date"] != entry_date:
        raise ValueError("entry date must have a stock wave feature row")
    peak_price = float(approach["peak_price"])
    target = _first_higher_high(path, entry_date, peak_price)
    defensive = _second_close_below_ma20(path, entry_date)
    exit_row, exit_reason = _first_exit(target, defensive)
    unrestricted = _first_higher_high(path, entry_date, peak_price)
    metrics = _path_metrics(
        path,
        entry_date=entry_date,
        entry_price=float(approach["entry_price"]),
        exit_row=exit_row,
        round_trip_cost_pct=round_trip_cost_pct,
    )
    unrestricted_date = (
        pd.Timestamp(unrestricted["trade_date"]) if unrestricted is not None else pd.NaT
    )
    defensive_preceded = (
        exit_reason == "two_closes_below_ma20"
        and unrestricted is not None
        and pd.Timestamp(exit_row["trade_date"]) < unrestricted_date
    )
    return {
        "trade_id": f"tail-close:{approach['approach_id']}",
        "wave_number": int(approach["wave_number"]),
        "support_line": str(approach["support_line"]),
        "support_depth": int(approach["support_depth"]),
        "entry_date": entry_date,
        "entry_price": float(approach["entry_price"]),
        "entry_proxy": "approach_day_close",
        "peak_date": pd.Timestamp(approach["peak_date"]),
        "peak_price": peak_price,
        "close_reclaimed_support": bool(approach["close_reclaimed_support"]),
        "volume_ratio_prior5": approach.get("volume_ratio_prior5"),
        "volume_ratio_impulse": approach.get("volume_ratio_impulse"),
        "volume_class_prior5": approach.get("volume_class_prior5"),
        "volume_class_impulse": approach.get("volume_class_impulse"),
        "executable_exit_reason": exit_reason,
        **metrics,
        "eventually_made_higher_high": unrestricted is not None,
        "unrestricted_higher_high_date": unrestricted_date,
        "unrestricted_higher_high_close": (
            float(unrestricted["close_price"]) if unrestricted is not None else None
        ),
        "unrestricted_return_at_higher_high_close_pct": (
            (
                float(unrestricted["close_price"]) / float(approach["entry_price"])
                - 1.0
            )
            * 100.0
            if unrestricted is not None
            else None
        ),
        "defensive_exit_preceded_later_higher_high": defensive_preceded,
        "wave_resolution_status": str(wave["resolution_status"]),
        "observation_end": observation_end,
        "round_trip_cost_pct": round_trip_cost_pct,
    }


def _first_higher_high(
    path: pd.DataFrame,
    entry_date: pd.Timestamp,
    peak_price: float,
) -> pd.Series | None:
    matches = path.loc[
        path["trade_date"].gt(entry_date) & path["high_price"].gt(peak_price)
    ]
    return matches.iloc[0] if not matches.empty else None


def _second_close_below_ma20(
    path: pd.DataFrame,
    entry_date: pd.Timestamp,
) -> pd.Series | None:
    below = path["close_price"].lt(path["ma20"]).fillna(False)
    second = below & below.shift(1, fill_value=False)
    matches = path.loc[path["trade_date"].gt(entry_date) & second]
    return matches.iloc[0] if not matches.empty else None


def _first_exit(
    target: pd.Series | None,
    defensive: pd.Series | None,
) -> tuple[pd.Series | None, str]:
    if target is None and defensive is None:
        return None, "right_censored"
    if target is None:
        return defensive, "two_closes_below_ma20"
    if defensive is None:
        return target, "higher_high_confirmed"
    if pd.Timestamp(target["trade_date"]) <= pd.Timestamp(defensive["trade_date"]):
        return target, "higher_high_confirmed"
    return defensive, "two_closes_below_ma20"


def _path_metrics(
    path: pd.DataFrame,
    *,
    entry_date: pd.Timestamp,
    entry_price: float,
    exit_row: pd.Series | None,
    round_trip_cost_pct: float,
) -> dict[str, Any]:
    if exit_row is None:
        return {
            "exit_date": pd.NaT,
            "exit_price": None,
            "holding_sessions": None,
            "gross_return_pct": None,
            "net_return_pct": None,
            "maximum_adverse_excursion_pct": None,
            "maximum_favorable_excursion_pct": None,
        }
    exit_date = pd.Timestamp(exit_row["trade_date"])
    observed = path.loc[
        path["trade_date"].gt(entry_date) & path["trade_date"].le(exit_date)
    ]
    holding_sessions = int(
        path.index[path["trade_date"].eq(exit_date)][0]
        - path.index[path["trade_date"].eq(entry_date)][0]
    )
    exit_price = float(exit_row["close_price"])
    gross_return = (exit_price / entry_price - 1.0) * 100.0
    return {
        "exit_date": exit_date,
        "exit_price": exit_price,
        "holding_sessions": holding_sessions,
        "gross_return_pct": gross_return,
        "net_return_pct": gross_return - round_trip_cost_pct,
        "maximum_adverse_excursion_pct": (
            min(
                0.0,
                (float(observed["low_price"].min()) / entry_price - 1.0) * 100.0,
            )
            if not observed.empty
            else 0.0
        ),
        "maximum_favorable_excursion_pct": (
            max(
                0.0,
                (float(observed["high_price"].max()) / entry_price - 1.0) * 100.0,
            )
            if not observed.empty
            else 0.0
        ),
    }


def _approach_columns() -> list[str]:
    return [
        "approach_id",
        "wave_number",
        "wave_start_date",
        "peak_date",
        "peak_price",
        "wave_resolution_status",
        "unrestricted_higher_high_date",
        "support_line",
        "support_depth",
        "approach_date",
        "support_price",
        "approach_tolerance_pct",
        "line_distance_low_pct",
        "line_distance_close_pct",
        "close_reclaimed_support",
        "entry_price",
        "peak_to_entry_drawdown_pct",
        "volume",
        "prior_volume_median_5d",
        "impulse_volume_median",
        "volume_ratio_prior5",
        "volume_ratio_impulse",
        "volume_class_prior5",
        "volume_class_impulse",
        "ma5",
        "ma10",
        "ma20",
        "trend_aligned",
        "feature_cutoff_date",
        "execution_selected",
    ]


def _trade_columns() -> list[str]:
    return [
        "trade_id",
        "wave_number",
        "support_line",
        "support_depth",
        "entry_date",
        "entry_price",
        "entry_proxy",
        "peak_date",
        "peak_price",
        "close_reclaimed_support",
        "volume_ratio_prior5",
        "volume_ratio_impulse",
        "volume_class_prior5",
        "volume_class_impulse",
        "executable_exit_reason",
        "exit_date",
        "exit_price",
        "holding_sessions",
        "gross_return_pct",
        "net_return_pct",
        "maximum_adverse_excursion_pct",
        "maximum_favorable_excursion_pct",
        "eventually_made_higher_high",
        "unrestricted_higher_high_date",
        "unrestricted_higher_high_close",
        "unrestricted_return_at_higher_high_close_pct",
        "defensive_exit_preceded_later_higher_high",
        "wave_resolution_status",
        "observation_end",
        "round_trip_cost_pct",
    ]


def _require_columns(
    frame: pd.DataFrame,
    required: tuple[str, ...],
    label: str,
) -> None:
    missing = sorted(set(required) - set(frame))
    if missing:
        raise ValueError(f"{label} missing columns: {', '.join(missing)}")


def _finite_or_none(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None
