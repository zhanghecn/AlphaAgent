"""D+1 event feature research for short-horizon A-share setups."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from alphaagent.server.db.session import get_engine, is_database_configured


DEFAULT_START = date(2026, 3, 1)
DEFAULT_MIN_GROUP_SIZE = 120
DEFAULT_SAMPLE_LIMIT = 16


@dataclass(frozen=True)
class EventResearchResult:
    dataset: dict[str, Any]
    baseline: dict[str, Any]
    flag_summary: list[dict[str, Any]]
    stacked_group_summary: list[dict[str, Any]]
    volume_turnover_summary: list[dict[str, Any]]
    target_feature_mix: list[dict[str, Any]]
    samples: dict[str, list[dict[str, Any]]]
    notes: list[str]


FEATURE_FLAG_KEYS = (
    "active_source_compressed_high_close",
    "deep_low_close_rebound_absorption",
    "deep_low_first_sun_confirm",
    "extreme_volume_intraday_fade",
    "active_source_breakdown",
    "hot_reacceleration_exhaustion",
    "weak_repair_high_close_no_source",
)


def run_d1_event_feature_research(
    *,
    start: date = DEFAULT_START,
    end: date | None = None,
    min_group_size: int = DEFAULT_MIN_GROUP_SIZE,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> EventResearchResult:
    """Build a point-in-time feature research set for D signal day and D+1 outcome."""

    if not is_database_configured():
        raise RuntimeError("DATABASE_URL is not configured")
    frame = build_event_feature_frame(start=start, end=end)
    return summarize_event_feature_frame(frame, min_group_size=min_group_size, sample_limit=sample_limit)


def build_event_feature_frame(*, start: date = DEFAULT_START, end: date | None = None) -> pd.DataFrame:
    """Return clean D-day feature rows with D+1 outcome labels."""

    raw = _load_daily_frame(start=start, end=end)
    if raw.empty:
        return raw
    frame = _add_point_in_time_features(raw, start=start)
    frame = _clean_event_universe(frame, start=start, end=end)
    if frame.empty:
        return frame
    group_rows = frame.apply(lambda row: classify_event_feature_groups(row.to_dict()), axis=1, result_type="expand")
    for column in group_rows.columns:
        frame[column] = group_rows[column]
    return frame


def summarize_event_feature_frame(
    frame: pd.DataFrame,
    *,
    min_group_size: int = DEFAULT_MIN_GROUP_SIZE,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> EventResearchResult:
    """Summarize event feature groups and keep representative stock samples."""

    if frame.empty:
        return EventResearchResult(
            dataset={"rows": 0},
            baseline={},
            flag_summary=[],
            stacked_group_summary=[],
            volume_turnover_summary=[],
            target_feature_mix=[],
            samples={},
            notes=_research_notes(),
        )

    dataset = {
        "rows": int(len(frame)),
        "symbols": int(frame["vt_symbol"].nunique()),
        "days": int(frame["trade_date"].nunique()),
        "start_date": _date_text(frame["trade_date"].min()),
        "end_date": _date_text(frame["trade_date"].max()),
    }
    baseline = _metric_summary(frame)
    flag_summary = _flag_summary(frame)
    stacked_group_summary = _group_summary(
        frame,
        ["position_group", "price_action_group", "volume_turnover_group", "active_source_group"],
        min_group_size=min_group_size,
    )
    volume_turnover_summary = _group_summary(
        frame,
        ["pre_volume_pattern", "volume_turnover_group"],
        min_group_size=min_group_size,
    )
    target_feature_mix = _target_feature_mix(frame, sample_limit=18)
    samples = _sample_sets(frame, sample_limit=sample_limit)
    return EventResearchResult(
        dataset=dataset,
        baseline=baseline,
        flag_summary=flag_summary,
        stacked_group_summary=stacked_group_summary,
        volume_turnover_summary=volume_turnover_summary,
        target_feature_mix=target_feature_mix,
        samples=samples,
        notes=_research_notes(),
    )


def classify_event_feature_groups(row: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one D-day event row into reusable feature buckets and flags."""

    ret_d = _num(row.get("ret_d"))
    close_location = _num(row.get("close_location"))
    volume_ratio = _num(row.get("vol_vs_ma20"))
    amount_ratio = _num(row.get("amount_vs_ma20"))
    turnover_proxy = _num(row.get("turnover_to_market_cap_pct"))
    ret20 = _num(row.get("ret20"))
    ma20_distance = _num(row.get("ma20_dist_pct"))
    amp = _num(row.get("intraday_amp_pct"))
    prior_limit_count = _num(row.get("prior_limit_up_20d")) or 0.0
    prior_touch_count = _num(row.get("prior_high_touch_20d")) or 0.0
    lag1_volume = _num(row.get("lag1_vol_vs_ma20"))
    lag2_volume = _num(row.get("lag2_vol_vs_ma20"))
    lag1_turnover = _num(row.get("lag1_turnover_to_market_cap_pct"))
    lag2_turnover = _num(row.get("lag2_turnover_to_market_cap_pct"))

    position_group = _position_group(ret20, ma20_distance)
    active_source_group = _active_source_group(prior_limit_count, prior_touch_count)
    volume_turnover_group = _volume_turnover_group(volume_ratio, amount_ratio, turnover_proxy)
    pre_volume_pattern = _pre_volume_pattern(volume_ratio, lag1_volume, lag2_volume, turnover_proxy, lag1_turnover, lag2_turnover)
    price_action_group = _price_action_group(ret_d, close_location, amp, volume_ratio)

    active_source_compressed_high_close = bool(
        prior_limit_count >= 1.0
        and ret_d is not None
        and ret_d >= 3.0
        and close_location is not None
        and close_location >= 0.75
        and volume_ratio is not None
        and 0.45 <= volume_ratio <= 1.05
    )
    deep_low_close_rebound_absorption = bool(
        position_group == "deep_oversold"
        and close_location is not None
        and close_location <= 0.25
        and volume_ratio is not None
        and 0.50 <= volume_ratio <= 1.80
    )
    deep_low_first_sun_confirm = bool(
        ((ret20 is not None and ret20 <= -15.0) or (ma20_distance is not None and ma20_distance <= -8.0))
        and ret_d is not None
        and ret_d >= 2.0
        and close_location is not None
        and close_location >= 0.65
        and volume_ratio is not None
        and 0.80 <= volume_ratio <= 2.20
    )
    extreme_volume_intraday_fade = bool(
        amp is not None
        and amp >= 8.0
        and close_location is not None
        and close_location <= 0.45
        and volume_ratio is not None
        and volume_ratio >= 2.0
    )
    active_source_breakdown = bool(
        prior_limit_count >= 1.0
        and ret_d is not None
        and ret_d <= -3.0
        and close_location is not None
        and close_location <= 0.35
        and volume_ratio is not None
        and volume_ratio >= 1.0
    )
    hot_reacceleration_exhaustion = bool(
        position_group == "extreme_hot"
        and ret_d is not None
        and ret_d >= 5.0
        and close_location is not None
        and close_location >= 0.75
    )
    weak_repair_high_close_no_source = bool(
        position_group in {"low_repair", "neutral"}
        and prior_limit_count <= 0
        and ret_d is not None
        and 0.0 <= ret_d <= 2.0
        and close_location is not None
        and close_location >= 0.65
        and volume_ratio is not None
        and volume_ratio <= 1.0
    )

    return {
        "position_group": position_group,
        "active_source_group": active_source_group,
        "volume_turnover_group": volume_turnover_group,
        "pre_volume_pattern": pre_volume_pattern,
        "price_action_group": price_action_group,
        "active_source_compressed_high_close": active_source_compressed_high_close,
        "deep_low_close_rebound_absorption": deep_low_close_rebound_absorption,
        "deep_low_first_sun_confirm": deep_low_first_sun_confirm,
        "extreme_volume_intraday_fade": extreme_volume_intraday_fade,
        "active_source_breakdown": active_source_breakdown,
        "hot_reacceleration_exhaustion": hot_reacceleration_exhaustion,
        "weak_repair_high_close_no_source": weak_repair_high_close_no_source,
        "stacked_feature_group": "::".join(
            [position_group, price_action_group, volume_turnover_group, active_source_group, pre_volume_pattern]
        ),
    }


def render_markdown_report(result: EventResearchResult) -> str:
    """Render a compact Chinese markdown report for the research set."""

    lines: list[str] = [
        "# D+1 Event Feature Research Set",
        "",
        "## Dataset",
        "",
        f"- rows: `{result.dataset.get('rows', 0)}`",
        f"- symbols: `{result.dataset.get('symbols', 0)}`",
        f"- days: `{result.dataset.get('days', 0)}`",
        f"- range: `{result.dataset.get('start_date')}` .. `{result.dataset.get('end_date')}`",
        "",
        "## Baseline",
        "",
    ]
    lines.extend(_metric_lines(result.baseline))
    lines.extend(["", "## Feature Flags", ""])
    lines.extend(_markdown_table(result.flag_summary, ["flag", "n", "win_rate", "avg_return", "median_return", "d1_limit_rate", "d1_big_up7_rate", "d1_big_down7_rate"]))
    lines.extend(["", "## Stacked Feature Groups", ""])
    lines.extend(
        _markdown_table(
            result.stacked_group_summary[:40],
            [
                "feature_group",
                "n",
                "win_rate",
                "avg_return",
                "median_return",
                "d1_limit_rate",
                "d1_big_up7_rate",
                "d1_big_down7_rate",
            ],
        )
    )
    lines.extend(["", "## Volume And Turnover Groups", ""])
    lines.extend(
        _markdown_table(
            result.volume_turnover_summary[:40],
            ["feature_group", "n", "win_rate", "avg_return", "median_return", "d1_limit_rate", "d1_big_down7_rate"],
        )
    )
    lines.extend(["", "## Target Feature Mix", ""])
    lines.extend(
        _markdown_table(
            result.target_feature_mix,
            ["target", "feature", "n", "share_in_target", "avg_return", "median_return"],
        )
    )
    lines.extend(["", "## Samples", ""])
    for title, rows in result.samples.items():
        lines.extend(["", f"### {title}", ""])
        lines.extend(
            _markdown_table(
                rows,
                [
                    "trade_date",
                    "next_trade_date",
                    "vt_symbol",
                    "name",
                    "d1_return",
                    "ret_d",
                    "position_group",
                    "price_action_group",
                    "volume_turnover_group",
                    "pre_volume_pattern",
                    "active_source_group",
                    "turnover_proxy",
                    "lag1_turnover_proxy",
                    "lag2_turnover_proxy",
                    "vol_vs_ma20",
                    "lag1_vol_vs_ma20",
                    "lag2_vol_vs_ma20",
                ],
            )
        )
    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {note}" for note in result.notes)
    return "\n".join(lines).rstrip() + "\n"


def export_research_result(
    result: EventResearchResult,
    *,
    markdown_path: Path | None = None,
    flag_csv_path: Path | None = None,
    group_csv_path: Path | None = None,
    volume_csv_path: Path | None = None,
) -> None:
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown_report(result), encoding="utf-8")
    if flag_csv_path:
        flag_csv_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(result.flag_summary).to_csv(flag_csv_path, index=False)
    if group_csv_path:
        group_csv_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(result.stacked_group_summary).to_csv(group_csv_path, index=False)
    if volume_csv_path:
        volume_csv_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(result.volume_turnover_summary).to_csv(volume_csv_path, index=False)


def _load_daily_frame(*, start: date, end: date | None) -> pd.DataFrame:
    lookback = start - timedelta(days=110)
    where_end = "and b.trade_date <= %(end)s" if end else ""
    sql = f"""
    select
        b.vt_symbol,
        b.trade_date,
        b.open_price,
        b.close_price,
        b.high_price,
        b.low_price,
        b.volume,
        b.turnover,
        b.change_pct,
        s.symbol,
        s.exchange,
        s.name,
        s.industry,
        s.area,
        s.market_cap,
        s.turnover_rate as latest_turnover_rate
    from stock_daily_bars b
    join stocks s on s.vt_symbol = b.vt_symbol
    where b.trade_date >= %(lookback)s
      {where_end}
    order by b.vt_symbol, b.trade_date
    """
    params: dict[str, Any] = {"lookback": lookback}
    if end:
        params["end"] = end
    frame = pd.read_sql(sql, get_engine(), params=params, parse_dates=["trade_date"])
    numeric_columns = (
        "open_price",
        "close_price",
        "high_price",
        "low_price",
        "volume",
        "turnover",
        "change_pct",
        "market_cap",
        "latest_turnover_rate",
    )
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _add_point_in_time_features(frame: pd.DataFrame, *, start: date) -> pd.DataFrame:
    frame = frame.copy()
    frame["code"] = frame["symbol"].astype(str).str.zfill(6)
    frame["board"] = frame["code"].map(_board_group)
    frame["limit_up_threshold"] = frame["board"].map(lambda value: 18.0 if value == "20cm" else 9.2)
    frame["limit_down_threshold"] = frame["board"].map(lambda value: -18.0 if value == "20cm" else -9.2)
    frame["price_cap"] = frame["board"].map(lambda value: 22.5 if value == "20cm" else 11.5)
    grouped = frame.groupby("vt_symbol", sort=False)
    frame["prev_close"] = grouped["close_price"].shift(1)
    frame["next_close"] = grouped["close_price"].shift(-1)
    frame["next_trade_date"] = grouped["trade_date"].shift(-1)
    frame["ret_d"] = frame["change_pct"]
    missing_return = frame["ret_d"].isna() & frame["prev_close"].gt(0)
    frame.loc[missing_return, "ret_d"] = (frame.loc[missing_return, "close_price"] / frame.loc[missing_return, "prev_close"] - 1.0) * 100.0
    frame["d1_return"] = (frame["next_close"] / frame["close_price"] - 1.0) * 100.0
    frame["high_ret_d"] = (frame["high_price"] / frame["prev_close"] - 1.0) * 100.0
    frame["low_ret_d"] = (frame["low_price"] / frame["prev_close"] - 1.0) * 100.0
    global_days = sorted(frame["trade_date"].dropna().unique())
    next_day = {global_days[index]: global_days[index + 1] for index in range(len(global_days) - 1)}
    frame["global_next_trade_date"] = frame["trade_date"].map(next_day)

    daily_range = (frame["high_price"] - frame["low_price"]).replace(0, pd.NA)
    frame["close_location"] = ((frame["close_price"] - frame["low_price"]) / daily_range).clip(0, 1).fillna(0.5)
    frame["intraday_amp_pct"] = (frame["high_price"] - frame["low_price"]) / frame["prev_close"] * 100.0
    frame["d_near_limit"] = frame["ret_d"].ge(frame["limit_up_threshold"])
    frame["d_touch_limit"] = frame["high_ret_d"].ge(frame["limit_up_threshold"])

    frame["vol_ma20_prev"] = grouped["volume"].transform(lambda series: series.shift(1).rolling(20, min_periods=8).mean())
    frame["amount_ma20_prev"] = grouped["turnover"].transform(lambda series: series.shift(1).rolling(20, min_periods=8).mean())
    frame["vol_vs_ma20"] = frame["volume"] / frame["vol_ma20_prev"]
    frame["amount_vs_ma20"] = frame["turnover"] / frame["amount_ma20_prev"]
    frame["turnover_to_market_cap_pct"] = frame["turnover"] / frame["market_cap"].replace(0, pd.NA) * 100.0
    frame["turnover_proxy_ma20_prev"] = grouped["turnover_to_market_cap_pct"].transform(
        lambda series: series.shift(1).rolling(20, min_periods=8).mean()
    )
    frame["turnover_proxy_vs_ma20"] = frame["turnover_to_market_cap_pct"] / frame["turnover_proxy_ma20_prev"]

    for window in (3, 5, 10, 20):
        frame[f"ret{window}"] = (frame["close_price"] / grouped["close_price"].shift(window) - 1.0) * 100.0
    frame["ma20"] = grouped["close_price"].transform(lambda series: series.rolling(20, min_periods=8).mean())
    frame["ma20_dist_pct"] = (frame["close_price"] / frame["ma20"] - 1.0) * 100.0
    frame["prior_limit_up_20d"] = grouped["d_near_limit"].transform(lambda series: series.shift(1).rolling(20, min_periods=1).sum())
    frame["prior_high_touch_20d"] = grouped["d_touch_limit"].transform(lambda series: series.shift(1).rolling(20, min_periods=1).sum())

    lag_columns = (
        "ret_d",
        "close_location",
        "vol_vs_ma20",
        "amount_vs_ma20",
        "turnover_to_market_cap_pct",
        "turnover_proxy_vs_ma20",
    )
    for lag in (1, 2, 5):
        for column in lag_columns:
            frame[f"lag{lag}_{column}"] = grouped[column].shift(lag)

    market_source = frame[
        frame["trade_date"].dt.date.ge(start)
        & frame["vt_symbol"].str.endswith((".SSE", ".SZSE"))
        & ~frame["code"].str.startswith(("8", "4"))
        & ~frame["name"].fillna("").str.contains("ST|退|退市", regex=True)
        & frame["prev_close"].gt(0)
    ]
    market = market_source.groupby("trade_date").agg(
        market_advancing_rate=("ret_d", lambda values: float((values > 0).mean())),
        market_average_return=("ret_d", "mean"),
    )
    frame = frame.join(market, on="trade_date")
    frame["market_phase"] = pd.cut(
        frame["market_advancing_rate"],
        bins=[-0.01, 0.35, 0.50, 0.65, 1.01],
        labels=["retreat", "mixed", "repair", "broad_rise"],
    )
    frame["d1_limit_up"] = frame["d1_return"].ge(frame["limit_up_threshold"])
    frame["d1_big_up7"] = frame["d1_return"].ge(7.0)
    frame["d1_big_down7"] = frame["d1_return"].le(-7.0)
    frame["d1_limit_down"] = frame["d1_return"].le(frame["limit_down_threshold"])
    return frame


def _clean_event_universe(frame: pd.DataFrame, *, start: date, end: date | None) -> pd.DataFrame:
    valid_d = frame["ret_d"].abs().le(frame["price_cap"]) & frame["high_ret_d"].le(frame["price_cap"]) & frame["low_ret_d"].ge(
        -frame["price_cap"]
    )
    valid_d1 = frame["d1_return"].abs().le(frame["price_cap"])
    mask = (
        frame["trade_date"].dt.date.ge(start)
        & frame["vt_symbol"].str.endswith((".SSE", ".SZSE"))
        & ~frame["code"].str.startswith(("8", "4"))
        & ~frame["name"].fillna("").str.contains("ST|退|退市", regex=True)
        & frame["prev_close"].gt(0)
        & frame["close_price"].gt(0)
        & frame["next_close"].gt(0)
        & frame["next_trade_date"].eq(frame["global_next_trade_date"])
        & valid_d
        & valid_d1
    )
    if end:
        mask &= frame["trade_date"].dt.date.le(end)
    return frame[mask].copy()


def _flag_summary(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for flag in FEATURE_FLAG_KEYS:
        subset = frame[frame[flag].fillna(False)]
        row = {"flag": flag}
        row.update(_metric_summary(subset))
        rows.append(row)
    return sorted(rows, key=lambda row: (float(row.get("avg_return") or -999), int(row.get("n") or 0)), reverse=True)


def _group_summary(frame: pd.DataFrame, group_columns: list[str], *, min_group_size: int) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    grouped = frame.groupby(group_columns, dropna=False, observed=True)
    rows: list[dict[str, Any]] = []
    for keys, subset in grouped:
        if len(subset) < min_group_size:
            continue
        key_values = keys if isinstance(keys, tuple) else (keys,)
        row = {"feature_group": "::".join(str(value) for value in key_values)}
        row.update(_metric_summary(subset))
        rows.append(row)
    return sorted(rows, key=lambda row: (float(row.get("avg_return") or -999), float(row.get("d1_limit_rate") or 0)), reverse=True)


def _target_feature_mix(frame: pd.DataFrame, *, sample_limit: int) -> list[dict[str, Any]]:
    target_masks = {
        "d1_limit_up": frame["d1_limit_up"].fillna(False),
        "d1_big_up7": frame["d1_big_up7"].fillna(False),
        "d1_big_down7": frame["d1_big_down7"].fillna(False),
        "d1_limit_down": frame["d1_limit_down"].fillna(False),
    }
    rows: list[dict[str, Any]] = []
    for target, mask in target_masks.items():
        subset = frame[mask]
        total = len(subset)
        if total <= 0:
            continue
        for column in ("position_group", "price_action_group", "volume_turnover_group", "active_source_group", "pre_volume_pattern"):
            counts = subset[column].value_counts().head(sample_limit)
            for feature, count in counts.items():
                feature_subset = subset[subset[column].eq(feature)]
                rows.append(
                    {
                        "target": target,
                        "feature": f"{column}={feature}",
                        "n": int(count),
                        "share_in_target": _round(count / total * 100.0),
                        "avg_return": _round(feature_subset["d1_return"].mean()),
                        "median_return": _round(feature_subset["d1_return"].median()),
                    }
                )
        for flag in FEATURE_FLAG_KEYS:
            flag_subset = subset[subset[flag].fillna(False)]
            if flag_subset.empty:
                continue
            rows.append(
                {
                    "target": target,
                    "feature": f"flag={flag}",
                    "n": int(len(flag_subset)),
                    "share_in_target": _round(len(flag_subset) / total * 100.0),
                    "avg_return": _round(flag_subset["d1_return"].mean()),
                    "median_return": _round(flag_subset["d1_return"].median()),
                }
            )
    return rows


def _sample_sets(frame: pd.DataFrame, *, sample_limit: int) -> dict[str, list[dict[str, Any]]]:
    sample_specs = {
        "d1_limit_up_examples": frame[frame["d1_limit_up"].fillna(False)].sort_values("d1_return", ascending=False),
        "d1_big_down_examples": frame[frame["d1_big_down7"].fillna(False)].sort_values("d1_return", ascending=True),
        "active_source_compressed_winners": frame[
            frame["active_source_compressed_high_close"].fillna(False) & frame["d1_big_up7"].fillna(False)
        ].sort_values("d1_return", ascending=False),
        "active_source_compressed_losers": frame[
            frame["active_source_compressed_high_close"].fillna(False) & frame["d1_big_down7"].fillna(False)
        ].sort_values("d1_return", ascending=True),
        "deep_low_close_winners": frame[
            frame["deep_low_close_rebound_absorption"].fillna(False) & frame["d1_big_up7"].fillna(False)
        ].sort_values("d1_return", ascending=False),
        "deep_low_close_losers": frame[
            frame["deep_low_close_rebound_absorption"].fillna(False) & frame["d1_big_down7"].fillna(False)
        ].sort_values("d1_return", ascending=True),
        "deep_low_first_sun_winners": frame[
            frame["deep_low_first_sun_confirm"].fillna(False) & frame["d1_big_up7"].fillna(False)
        ].sort_values("d1_return", ascending=False),
        "risk_flag_losers": frame[
            (
                frame["extreme_volume_intraday_fade"].fillna(False)
                | frame["active_source_breakdown"].fillna(False)
                | frame["hot_reacceleration_exhaustion"].fillna(False)
            )
            & frame["d1_big_down7"].fillna(False)
        ].sort_values("d1_return", ascending=True),
    }
    return {name: [_sample_row(row) for row in subset.head(sample_limit).to_dict("records")] for name, subset in sample_specs.items()}


def _metric_summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "n": 0,
            "win_rate": None,
            "avg_return": None,
            "median_return": None,
            "d1_limit_rate": None,
            "d1_big_up7_rate": None,
            "d1_big_down7_rate": None,
            "d1_limit_down_rate": None,
        }
    returns = frame["d1_return"].dropna()
    return {
        "n": int(len(frame)),
        "win_rate": _round((returns > 0).mean() * 100.0),
        "avg_return": _round(returns.mean()),
        "median_return": _round(returns.median()),
        "d1_limit_rate": _round(frame["d1_limit_up"].fillna(False).mean() * 100.0),
        "d1_big_up7_rate": _round(frame["d1_big_up7"].fillna(False).mean() * 100.0),
        "d1_big_down7_rate": _round(frame["d1_big_down7"].fillna(False).mean() * 100.0),
        "d1_limit_down_rate": _round(frame["d1_limit_down"].fillna(False).mean() * 100.0),
    }


def _sample_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "trade_date": _date_text(row.get("trade_date")),
        "next_trade_date": _date_text(row.get("next_trade_date")),
        "vt_symbol": row.get("vt_symbol"),
        "name": row.get("name"),
        "board": row.get("board"),
        "d1_return": _round(row.get("d1_return")),
        "ret_d": _round(row.get("ret_d")),
        "position_group": row.get("position_group"),
        "price_action_group": row.get("price_action_group"),
        "volume_turnover_group": row.get("volume_turnover_group"),
        "pre_volume_pattern": row.get("pre_volume_pattern"),
        "active_source_group": row.get("active_source_group"),
        "turnover_proxy": _round(row.get("turnover_to_market_cap_pct")),
        "lag1_turnover_proxy": _round(row.get("lag1_turnover_to_market_cap_pct")),
        "lag2_turnover_proxy": _round(row.get("lag2_turnover_to_market_cap_pct")),
        "vol_vs_ma20": _round(row.get("vol_vs_ma20")),
        "lag1_vol_vs_ma20": _round(row.get("lag1_vol_vs_ma20")),
        "lag2_vol_vs_ma20": _round(row.get("lag2_vol_vs_ma20")),
        "amount_vs_ma20": _round(row.get("amount_vs_ma20")),
        "ret20": _round(row.get("ret20")),
        "ma20_dist_pct": _round(row.get("ma20_dist_pct")),
        "prior_limit_up_20d": _round(row.get("prior_limit_up_20d")),
    }


def _position_group(ret20: float | None, ma20_distance: float | None) -> str:
    if (ret20 is not None and ret20 <= -20.0) or (ma20_distance is not None and ma20_distance <= -10.0):
        return "deep_oversold"
    if (ret20 is not None and ret20 <= -10.0) or (ma20_distance is not None and ma20_distance <= -3.0):
        return "low_repair"
    if ret20 is not None and ret20 >= 80.0:
        return "extreme_hot"
    if (ret20 is not None and ret20 >= 25.0) or (ma20_distance is not None and ma20_distance >= 10.0):
        return "high_momentum"
    return "neutral"


def _active_source_group(prior_limit_count: float, prior_touch_count: float) -> str:
    if prior_limit_count >= 4.0:
        return "crowded_active_source"
    if prior_limit_count >= 2.0:
        return "multi_limit_source"
    if prior_limit_count >= 1.0:
        return "single_limit_source"
    if prior_touch_count >= 1.0:
        return "touched_but_not_closed_limit"
    return "no_limit_source"


def _volume_turnover_group(volume_ratio: float | None, amount_ratio: float | None, turnover_proxy: float | None) -> str:
    ratio = amount_ratio if amount_ratio is not None else volume_ratio
    if ratio is None:
        return "unknown_turnover"
    if ratio < 0.70:
        base = "contracted"
    elif ratio < 1.15:
        base = "normal"
    elif ratio < 1.80:
        base = "active"
    elif ratio < 2.80:
        base = "hot"
    else:
        base = "extreme"
    if turnover_proxy is None:
        return base
    if turnover_proxy >= 8.0:
        return f"{base}_high_turnover_proxy"
    if turnover_proxy <= 1.0:
        return f"{base}_low_turnover_proxy"
    return base


def _pre_volume_pattern(
    volume_ratio: float | None,
    lag1_volume: float | None,
    lag2_volume: float | None,
    turnover_proxy: float | None,
    lag1_turnover: float | None,
    lag2_turnover: float | None,
) -> str:
    ratios = [value for value in (lag2_volume, lag1_volume, volume_ratio) if value is not None]
    turnover_values = [value for value in (lag2_turnover, lag1_turnover, turnover_proxy) if value is not None]
    if len(ratios) < 2:
        return "volume_history_unknown"
    if all(value < 0.85 for value in ratios):
        return "multi_day_contraction"
    if len(ratios) >= 3 and ratios[0] < ratios[1] < ratios[2]:
        return "volume_rising_three_day"
    if len(ratios) >= 3 and ratios[0] > ratios[1] > ratios[2]:
        return "volume_contracting_three_day"
    if volume_ratio is not None and volume_ratio >= 2.0 and lag1_volume is not None and lag1_volume < 1.2:
        return "sudden_volume_expansion"
    if turnover_values and turnover_values[-1] >= 8.0:
        return "high_turnover_proxy_latest"
    return "mixed_volume"


def _price_action_group(
    ret_d: float | None,
    close_location: float | None,
    amp: float | None,
    volume_ratio: float | None,
) -> str:
    if ret_d is not None and ret_d <= -5.0 and close_location is not None and close_location <= 0.25:
        return "panic_low_close"
    if ret_d is not None and ret_d >= 2.0 and close_location is not None and close_location >= 0.75:
        return "first_sun_or_strong_close"
    if ret_d is not None and ret_d >= 7.0 and close_location is not None and close_location >= 0.85:
        return "near_limit_strong_close"
    if amp is not None and amp >= 8.0 and close_location is not None and close_location <= 0.45:
        return "intraday_fade"
    if ret_d is not None and -2.0 <= ret_d <= 2.0 and close_location is not None and 0.35 <= close_location <= 0.75:
        if volume_ratio is not None and volume_ratio <= 0.85:
            return "compressed_mid_close"
        return "balanced_mid_close"
    if close_location is not None and close_location <= 0.25:
        return "low_close"
    if close_location is not None and close_location >= 0.75:
        return "high_close"
    return "ordinary"


def _board_group(code: str) -> str:
    return "20cm" if str(code).startswith(("300", "301", "688", "689")) else "10cm"


def _research_notes() -> list[str]:
    return [
        "stock_daily_bars 没有历史换手率字段；turnover_proxy 使用 D 日成交额 / 当前 market_cap 近似，只能作为成交活跃度代理，不是严格点位历史换手率。",
        "volume_ratio/amount_ratio 使用 D 日成交量或成交额相对前 20 日均值，前 20 日均值不包含 D 日。",
        "所有正向/负向 flag 都只使用 D 日收盘前可见信息；D+1 只作为标签。",
        "主样本剔除北交所、ST/退市、非连续 D+1、新股/除权或数据异常导致的超涨跌幅样本。",
    ]


def _metric_lines(summary: Mapping[str, Any]) -> list[str]:
    if not summary:
        return ["- empty"]
    return [
        f"- n: `{summary.get('n')}`",
        f"- win_rate: `{summary.get('win_rate')}`",
        f"- avg_return: `{summary.get('avg_return')}`",
        f"- median_return: `{summary.get('median_return')}`",
        f"- d1_limit_rate: `{summary.get('d1_limit_rate')}`",
        f"- d1_big_up7_rate: `{summary.get('d1_big_up7_rate')}`",
        f"- d1_big_down7_rate: `{summary.get('d1_big_down7_rate')}`",
    ]


def _markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    if not rows:
        return ["(empty)"]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        values = [str(row.get(column, "")) for column in columns]
        lines.append("| " + " | ".join(value.replace("|", "/") for value in values) + " |")
    return lines


def _date_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "date"):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: Any, digits: int = 4) -> float | None:
    number = _num(value)
    return None if number is None else round(number, digits)


def _parse_date(value: str | None, default: date | None = None) -> date:
    if not value:
        if default is None:
            raise ValueError("date value is required")
        return default
    return date.fromisoformat(value)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build D+1 event feature research groups.")
    parser.add_argument("--start", default=DEFAULT_START.isoformat())
    parser.add_argument("--end", default=None)
    parser.add_argument("--min-group-size", type=int, default=DEFAULT_MIN_GROUP_SIZE)
    parser.add_argument("--sample-limit", type=int, default=DEFAULT_SAMPLE_LIMIT)
    parser.add_argument("--markdown-out", default=None)
    parser.add_argument("--flag-csv-out", default=None)
    parser.add_argument("--group-csv-out", default=None)
    parser.add_argument("--volume-csv-out", default=None)
    args = parser.parse_args(argv)
    result = run_d1_event_feature_research(
        start=_parse_date(args.start, DEFAULT_START),
        end=_parse_date(args.end) if args.end else None,
        min_group_size=args.min_group_size,
        sample_limit=args.sample_limit,
    )
    export_research_result(
        result,
        markdown_path=Path(args.markdown_out) if args.markdown_out else None,
        flag_csv_path=Path(args.flag_csv_out) if args.flag_csv_out else None,
        group_csv_path=Path(args.group_csv_out) if args.group_csv_out else None,
        volume_csv_path=Path(args.volume_csv_out) if args.volume_csv_out else None,
    )
    if not args.markdown_out:
        print(render_markdown_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
