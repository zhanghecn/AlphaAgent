"""Price-calculated stock/concept relationships for true-leader research."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


RELATIONSHIP_WINDOW = 40
MIN_RELATIONSHIP_OBSERVATIONS = 30
MIN_RELATIONSHIP_CORRELATION = 0.10
MIN_SAME_DIRECTION_RATE = 0.50
RELATIONSHIP_POOL_SIZE = 30
STRONG_DAY_PCT = 5.0


@dataclass(frozen=True)
class RelationshipMatrices:
    """Aligned residual-return matrices used by both causal and truth passes."""

    trading_dates: tuple[pd.Timestamp, ...]
    stock_symbols: tuple[str, ...]
    sector_ids: tuple[str, ...]
    stock_residual_returns: np.ndarray
    concept_residual_returns: np.ndarray


def build_calculated_stock_features(stock_bars: pd.DataFrame) -> pd.DataFrame:
    """Build trailing descriptors and strict main-rise eligibility."""

    required = (
        "vt_symbol",
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "turnover",
    )
    _require_columns(stock_bars, required, "stock bar")
    optional = ["stock_name"] if "stock_name" in stock_bars else []
    frame = stock_bars.loc[:, [*required, *optional]].copy()
    frame["vt_symbol"] = frame["vt_symbol"].astype(str).str.strip()
    frame = frame.loc[frame["vt_symbol"].map(is_main_board_symbol)].copy()
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    if frame.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("stock daily bar identities must be unique")

    price_columns = ["open_price", "high_price", "low_price", "close_price"]
    frame[price_columns] = frame[price_columns].apply(pd.to_numeric, errors="coerce")
    price_values = frame[price_columns].to_numpy(dtype=float)
    if not np.isfinite(price_values).all() or (price_values <= 0).any():
        raise ValueError("stock OHLC values must be finite and positive")
    flow_columns = ["volume", "turnover"]
    frame[flow_columns] = (
        frame[flow_columns].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    )
    flow_values = frame[flow_columns].to_numpy(dtype=float)
    if not np.isfinite(flow_values).all() or (flow_values < 0).any():
        raise ValueError("stock volume and turnover must be finite and non-negative")
    if "stock_name" not in frame:
        frame["stock_name"] = frame["vt_symbol"]
    frame["stock_name"] = frame["stock_name"].fillna("").astype(str).str.strip()

    frame = frame.sort_values(
        ["vt_symbol", "trade_date"], kind="stable"
    ).reset_index(drop=True)
    grouped = frame.groupby("vt_symbol", sort=False)
    frame["daily_return_pct"] = (
        grouped["close_price"].pct_change(fill_method=None) * 100.0
    )
    frame["strong_day"] = frame["daily_return_pct"].ge(STRONG_DAY_PCT)
    frame["strong_days_10"] = grouped["strong_day"].transform(
        lambda values: values.rolling(10, min_periods=1).sum()
    )
    frame["return_5d_pct"] = (
        grouped["close_price"].pct_change(5, fill_method=None) * 100.0
    )
    frame["return_10d_pct"] = (
        grouped["close_price"].pct_change(10, fill_method=None) * 100.0
    )
    frame["return_20d_pct"] = (
        grouped["close_price"].pct_change(20, fill_method=None) * 100.0
    )
    prior_five_return = (
        grouped["close_price"].shift(5) / grouped["close_price"].shift(10) - 1.0
    ) * 100.0
    frame["return_acceleration_5d_pct"] = (
        frame["return_5d_pct"] - prior_five_return
    )
    for window in (5, 10, 20):
        frame[f"ma{window}"] = grouped["close_price"].transform(
            lambda values, size=window: values.rolling(
                size, min_periods=size
            ).mean()
        )
    frame["ma5_shift_3"] = grouped["ma5"].shift(3)
    frame["ma10_shift_3"] = grouped["ma10"].shift(3)
    frame["prior_high20"] = grouped["high_price"].transform(
        lambda values: values.shift(1).rolling(20, min_periods=20).max()
    )
    frame["distance_from_prior_high_pct"] = (
        frame["close_price"] / frame["prior_high20"] - 1.0
    ) * 100.0
    volume_mean_5 = grouped["volume"].transform(
        lambda values: values.rolling(5, min_periods=5).mean()
    )
    volume_mean_20 = grouped["volume"].transform(
        lambda values: values.rolling(20, min_periods=20).mean()
    )
    frame["volume_ratio_5_20"] = volume_mean_5 / volume_mean_20.replace(0, np.nan)
    frame["turnover_median_20d"] = grouped["turnover"].transform(
        lambda values: values.rolling(20, min_periods=20).median()
    )
    _attach_first_strong_observation(frame)

    complete_columns = (
        "return_5d_pct",
        "return_10d_pct",
        "return_20d_pct",
        "return_acceleration_5d_pct",
        "ma5",
        "ma10",
        "ma20",
        "ma5_shift_3",
        "ma10_shift_3",
        "prior_high20",
        "distance_from_prior_high_pct",
        "volume_ratio_5_20",
        "turnover_median_20d",
    )
    complete_values = frame.loc[:, list(complete_columns)].to_numpy(dtype=float)
    frame["feature_complete"] = np.isfinite(complete_values).all(axis=1)
    frame["main_rise_alive"] = (
        frame["close_price"].ge(frame["ma5"])
        & frame["ma5"].gt(frame["ma10"])
        & frame["ma10"].gt(frame["ma20"])
        & frame["ma5"].gt(frame["ma5_shift_3"])
        & frame["ma10"].gt(frame["ma10_shift_3"])
    ).fillna(False)
    frame["leader_eligible"] = (
        frame["feature_complete"]
        & frame["main_rise_alive"]
        & frame["strong_days_10"].ge(1)
        & frame["first_strong_date_10d"].notna()
    )
    return frame.reset_index(drop=True)


def build_relationship_matrices(
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
    market_returns: pd.DataFrame,
) -> RelationshipMatrices:
    """Align prices once and calculate broad-market residual returns."""

    stocks = _prepare_price_frame(
        stock_bars,
        entity_column="vt_symbol",
        label="stock",
    )
    stocks = stocks.loc[stocks["vt_symbol"].map(is_main_board_symbol)].copy()
    concepts = _prepare_price_frame(
        concept_bars,
        entity_column="sector_id",
        label="concept",
    )
    _require_columns(
        market_returns,
        ("trade_date", "market_daily_return"),
        "market return",
    )
    market = market_returns.loc[:, ["trade_date", "market_daily_return"]].copy()
    market["trade_date"] = pd.to_datetime(
        market["trade_date"], errors="raise"
    ).dt.normalize()
    if market["trade_date"].duplicated().any():
        raise ValueError("market return dates must be unique")
    market["market_daily_return"] = pd.to_numeric(
        market["market_daily_return"], errors="coerce"
    )
    market = market.sort_values("trade_date", kind="stable").reset_index(drop=True)
    trading_index = pd.DatetimeIndex(market["trade_date"])
    if trading_index.empty:
        raise ValueError("market returns cannot be empty")

    stock_close = stocks.pivot(
        index="trade_date", columns="vt_symbol", values="close_price"
    ).reindex(trading_index)
    concept_close = concepts.pivot(
        index="trade_date", columns="sector_id", values="close_price"
    ).reindex(trading_index)
    stock_close = stock_close.reindex(sorted(stock_close.columns), axis=1)
    concept_close = concept_close.reindex(sorted(concept_close.columns), axis=1)
    stock_returns = stock_close.pct_change(fill_method=None).to_numpy(dtype=float)
    concept_returns = concept_close.pct_change(fill_method=None).to_numpy(dtype=float)
    market_values = market["market_daily_return"].to_numpy(dtype=float)[:, None]
    return RelationshipMatrices(
        trading_dates=tuple(pd.Timestamp(value) for value in trading_index),
        stock_symbols=tuple(str(value) for value in stock_close.columns),
        sector_ids=tuple(str(value) for value in concept_close.columns),
        stock_residual_returns=stock_returns - market_values,
        concept_residual_returns=concept_returns - market_values,
    )


def build_calculated_relationship_pool(
    cycles: pd.DataFrame,
    eligible_features: pd.DataFrame,
    matrices: RelationshipMatrices,
    *,
    direction: Literal["causal", "realized"],
) -> pd.DataFrame:
    """Calculate top price relationships from the eligible main-board universe."""

    if direction not in {"causal", "realized"}:
        raise ValueError("relationship direction must be causal or realized")
    cycle_columns = (
        "cycle_id",
        "sector_id",
        "concept_name",
        "trade_date",
        "concept_return_10d",
    )
    feature_columns = (
        "vt_symbol",
        "stock_name",
        "trade_date",
        "leader_eligible",
        "first_strong_date_10d",
        "first_strong_sessions_ago_10d",
        "strong_days_10",
        "return_10d_pct",
        "return_acceleration_5d_pct",
        "distance_from_prior_high_pct",
        "volume_ratio_5_20",
        "turnover_median_20d",
    )
    _require_columns(cycles, cycle_columns, "concept cycle")
    _require_columns(eligible_features, feature_columns, "eligible stock feature")
    cycle_frame = cycles.loc[:, list(cycle_columns)].copy()
    cycle_frame["trade_date"] = pd.to_datetime(
        cycle_frame["trade_date"], errors="raise"
    ).dt.normalize()
    cycle_frame["cycle_id"] = cycle_frame["cycle_id"].astype(str)
    cycle_frame["sector_id"] = cycle_frame["sector_id"].astype(str)
    if cycle_frame["cycle_id"].duplicated().any():
        raise ValueError("concept cycle IDs must be unique")

    features = eligible_features.loc[:, list(feature_columns)].copy()
    features["trade_date"] = pd.to_datetime(
        features["trade_date"], errors="raise"
    ).dt.normalize()
    features["vt_symbol"] = features["vt_symbol"].astype(str).str.strip()
    if features.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("eligible stock feature identities must be unique")
    features = features.loc[
        features["leader_eligible"].astype(bool)
        & features["vt_symbol"].map(is_main_board_symbol)
    ].copy()

    date_positions = {value: index for index, value in enumerate(matrices.trading_dates)}
    stock_positions = {
        symbol: index for index, symbol in enumerate(matrices.stock_symbols)
    }
    sector_positions = {
        sector: index for index, sector in enumerate(matrices.sector_ids)
    }
    features_by_date = {
        pd.Timestamp(trade_date): group.reset_index(drop=True)
        for trade_date, group in features.groupby("trade_date", sort=False)
    }
    pool_rows: list[pd.DataFrame] = []
    for cycle in cycle_frame.to_dict("records"):
        relation = _relationship_rows_for_cycle(
            cycle,
            features_by_date,
            matrices,
            date_positions,
            stock_positions,
            sector_positions,
            direction=direction,
        )
        if len(relation) >= 3:
            pool_rows.append(relation)
    if not pool_rows:
        return pd.DataFrame()
    return pd.concat(pool_rows, ignore_index=True).sort_values(
        ["trade_date", "cycle_id", "relation_rank"], kind="stable"
    ).reset_index(drop=True)


def is_main_board_symbol(value: object) -> bool:
    """Return whether a vn.py symbol belongs to the SSE/SZSE main board."""

    text = str(value).strip().upper()
    if "." not in text:
        return False
    symbol, exchange = text.rsplit(".", 1)
    if exchange == "SSE":
        return symbol.startswith(("600", "601", "603", "605"))
    if exchange == "SZSE":
        return symbol.startswith(("000", "001", "002", "003"))
    return False


def _relationship_rows_for_cycle(
    cycle: dict[str, object],
    features_by_date: dict[pd.Timestamp, pd.DataFrame],
    matrices: RelationshipMatrices,
    date_positions: dict[pd.Timestamp, int],
    stock_positions: dict[str, int],
    sector_positions: dict[str, int],
    *,
    direction: Literal["causal", "realized"],
) -> pd.DataFrame:
    cycle_date = pd.Timestamp(cycle["trade_date"]).normalize()
    cycle_position = date_positions.get(cycle_date)
    sector_position = sector_positions.get(str(cycle["sector_id"]))
    features = features_by_date.get(cycle_date)
    if cycle_position is None or sector_position is None or features is None:
        return pd.DataFrame()
    bounds = _relationship_window_bounds(
        cycle_position,
        len(matrices.trading_dates),
        direction=direction,
    )
    if bounds is None:
        return pd.DataFrame()
    start, stop, known_position = bounds
    present = features["vt_symbol"].isin(stock_positions)
    features = features.loc[present].copy().reset_index(drop=True)
    if len(features) < 3:
        return pd.DataFrame()
    columns = [stock_positions[symbol] for symbol in features["vt_symbol"]]
    stock_values = matrices.stock_residual_returns[start:stop, columns]
    concept_values = matrices.concept_residual_returns[
        start:stop, sector_position
    ]
    same_session = _columnwise_correlation(stock_values, concept_values)
    lead_session = _columnwise_correlation(stock_values[:-1], concept_values[1:])
    same_direction = _columnwise_same_direction(stock_values, concept_values)
    relation = features.assign(
        residual_correlation_40=same_session,
        stock_lead_correlation_39=lead_session,
        same_direction_rate_40=same_direction,
    )
    relation = relation.loc[
        np.maximum(
            relation["residual_correlation_40"],
            relation["stock_lead_correlation_39"],
        ).ge(MIN_RELATIONSHIP_CORRELATION)
        & relation["same_direction_rate_40"].ge(MIN_SAME_DIRECTION_RATE)
    ].copy()
    if len(relation) < 3:
        return pd.DataFrame()
    percentile_columns = []
    for source in (
        "residual_correlation_40",
        "stock_lead_correlation_39",
        "same_direction_rate_40",
    ):
        target = f"{source}_percentile"
        relation[target] = relation[source].rank(method="average", pct=True)
        percentile_columns.append(target)
    relation["relationship_consensus"] = relation[percentile_columns].mean(axis=1)
    relation = relation.sort_values(
        [
            "relationship_consensus",
            "residual_correlation_40",
            "stock_lead_correlation_39",
            "vt_symbol",
        ],
        ascending=[False, False, False, True],
        kind="stable",
    ).head(RELATIONSHIP_POOL_SIZE)
    relation["relation_rank"] = np.arange(1, len(relation) + 1)
    relation["cycle_id"] = str(cycle["cycle_id"])
    relation["sector_id"] = str(cycle["sector_id"])
    relation["concept_name"] = str(cycle["concept_name"])
    relation["concept_return_10d"] = float(cycle["concept_return_10d"])
    relation["relationship_direction"] = direction
    relation["relationship_known_at"] = matrices.trading_dates[known_position]
    relation["relationship_pool_size"] = len(relation)
    return relation.reset_index(drop=True)


def _relationship_window_bounds(
    cycle_position: int,
    date_count: int,
    *,
    direction: Literal["causal", "realized"],
) -> tuple[int, int, int] | None:
    if direction == "causal":
        start = cycle_position - RELATIONSHIP_WINDOW + 1
        stop = cycle_position + 1
        known_position = cycle_position
    else:
        start = cycle_position + 1
        stop = cycle_position + RELATIONSHIP_WINDOW + 1
        known_position = stop - 1
    if start < 0 or stop > date_count:
        return None
    return start, stop, known_position


def _columnwise_correlation(values: np.ndarray, target: np.ndarray) -> np.ndarray:
    target_column = np.asarray(target, dtype=float)[:, None]
    values = np.asarray(values, dtype=float)
    valid = np.isfinite(values) & np.isfinite(target_column)
    counts = valid.sum(axis=0).astype(float)
    safe_values = np.where(valid, values, 0.0)
    safe_target = np.where(valid, target_column, 0.0)
    sum_values = safe_values.sum(axis=0)
    sum_target = safe_target.sum(axis=0)
    cross = (safe_values * safe_target).sum(axis=0)
    square_values = (safe_values * safe_values).sum(axis=0)
    square_target = (safe_target * safe_target).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        covariance = cross - (sum_values * sum_target / counts)
        variance_values = square_values - (sum_values * sum_values / counts)
        variance_target = square_target - (sum_target * sum_target / counts)
        result = covariance / np.sqrt(variance_values * variance_target)
    result[
        (counts < MIN_RELATIONSHIP_OBSERVATIONS)
        | ~np.isfinite(result)
        | (variance_values <= 0)
        | (variance_target <= 0)
    ] = np.nan
    return np.clip(result, -1.0, 1.0)


def _columnwise_same_direction(values: np.ndarray, target: np.ndarray) -> np.ndarray:
    target_column = np.asarray(target, dtype=float)[:, None]
    values = np.asarray(values, dtype=float)
    valid = np.isfinite(values) & np.isfinite(target_column)
    counts = valid.sum(axis=0)
    agreements = (valid & ((values * target_column) > 0)).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        result = agreements / counts
    result[counts < MIN_RELATIONSHIP_OBSERVATIONS] = np.nan
    return result.astype(float)


def _prepare_price_frame(
    frame: pd.DataFrame,
    *,
    entity_column: str,
    label: str,
) -> pd.DataFrame:
    _require_columns(frame, (entity_column, "trade_date", "close_price"), label)
    result = frame.loc[:, [entity_column, "trade_date", "close_price"]].copy()
    result[entity_column] = result[entity_column].astype(str).str.strip()
    result["trade_date"] = pd.to_datetime(
        result["trade_date"], errors="raise"
    ).dt.normalize()
    result["close_price"] = pd.to_numeric(result["close_price"], errors="coerce")
    if result.duplicated([entity_column, "trade_date"]).any():
        raise ValueError(f"{label} price identities must be unique")
    close_values = result["close_price"].to_numpy(dtype=float)
    if not np.isfinite(close_values).all() or (close_values <= 0).any():
        raise ValueError(f"{label} closes must be finite and positive")
    return result


def _attach_first_strong_observation(frame: pd.DataFrame) -> None:
    positions = pd.Series(np.arange(len(frame), dtype=float), index=frame.index)
    strong_positions = positions.where(frame["strong_day"])
    first_positions = strong_positions.groupby(
        frame["vt_symbol"], sort=False
    ).transform(lambda values: values.rolling(10, min_periods=1).min())
    frame["first_strong_sessions_ago_10d"] = positions - first_positions
    first_dates = np.full(len(frame), np.datetime64("NaT"), dtype="datetime64[ns]")
    valid = first_positions.notna().to_numpy()
    dates = frame["trade_date"].to_numpy(dtype="datetime64[ns]")
    first_dates[valid] = dates[first_positions.loc[valid].astype(int).to_numpy()]
    frame["first_strong_date_10d"] = pd.to_datetime(first_dates)


def _require_columns(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    label: str,
) -> None:
    missing = sorted(set(columns) - set(frame))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
