"""Reverse-inference study: which touch-day features precede a successful reclaim.

正向试错(回踩日入场变体)已被全量回测否决(31.84% 胜率)。
本研究反向归纳:在同一批支撑触碰母集合上,用「1-2 个交易日内是否出现强转强」
作为标签,检验预登记的触碰日因果特征能否提前区分将转强与将跌破,
为"预筛选回踩日入场"提供证据或封死该方向。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .causal_leader_pullback import (
    GOLD_STRONG_RECLAIM_MAX_PEAK_GAP_PCT,
    GOLD_STRONG_RECLAIM_MAX_SUPPORT_SESSIONS,
    GOLD_STRONG_RECLAIM_RETURN_PCT,
    SUPPORT_DEPTH,
)


STUDY_VERSION = "support-touch-reclaim-feature-v1"

# 预登记特征清单(触碰日收盘前已知,经济含义先行,不做事后增补)
PRE_REGISTERED_FEATURES = (
    "daily_return_pct",
    "close_location",
    "close_holds_support",
    "undercut_depth_pct",
    "volume_ratio_prior5",
    "turnover_expansion",
    "peak_distance_pct",
    "leg_gain_pct",
    "sessions_since_ignition",
    "wave_number",
    "dynamic_rank",
)

_TOUCH_REQUIRED = (
    "opportunity_id",
    "campaign_id",
    "sector_id",
    "concept_name",
    "vt_symbol",
    "stock_name",
    "entry_date",
    "entry_price",
    "wave_number",
    "support_line",
    "ma5",
    "ma10",
    "prior_high20",
    "dynamic_rank",
    "low_price",
    "daily_return_pct",
    "close_location",
    "volume_ratio_prior5",
    "turnover_expansion",
    "sessions_since_ignition",
    "last_ignition_base_close",
)


def attach_reclaim_labels(
    opportunities: pd.DataFrame,
    signals: pd.DataFrame,
) -> pd.DataFrame:
    """Label each touch by whether an official-strength reclaim followed in 1-2 sessions."""

    required = (
        "campaign_id",
        "vt_symbol",
        "support_test_date",
        "support_line",
        "signal_daily_return_pct",
        "signal_close",
        "reference_peak_price",
        "support_test_session_gap",
    )
    _require_columns(signals, required, "reclaim signal")
    frame = opportunities.copy()
    frame["entry_date"] = pd.to_datetime(frame["entry_date"], errors="raise").dt.normalize()
    confirmations = signals.loc[:, list(required)].copy()
    confirmations["support_test_date"] = pd.to_datetime(
        confirmations["support_test_date"], errors="coerce"
    ).dt.normalize()
    numeric = ("signal_daily_return_pct", "signal_close", "reference_peak_price", "support_test_session_gap")
    confirmations[list(numeric)] = confirmations[list(numeric)].apply(pd.to_numeric, errors="coerce")
    strong = confirmations.loc[
        confirmations["signal_daily_return_pct"].ge(GOLD_STRONG_RECLAIM_RETURN_PCT)
        & confirmations["signal_close"].ge(
            confirmations["reference_peak_price"]
            * (1.0 - GOLD_STRONG_RECLAIM_MAX_PEAK_GAP_PCT / 100.0)
        )
        & confirmations["support_test_session_gap"].between(
            1, GOLD_STRONG_RECLAIM_MAX_SUPPORT_SESSIONS
        )
    ]
    keys = set(
        zip(
            strong["campaign_id"].astype(str),
            strong["vt_symbol"].astype(str),
            strong["support_test_date"],
            strong["support_line"].astype(str),
        )
    )
    frame["reclaimed"] = [
        (str(c), str(s), d, str(line)) in keys
        for c, s, d, line in zip(
            frame["campaign_id"], frame["vt_symbol"], frame["entry_date"], frame["support_line"]
        )
    ]
    return frame


def build_touch_feature_frame(opportunities: pd.DataFrame) -> pd.DataFrame:
    """Attach the pre-registered causal touch-day features."""

    _require_columns(opportunities, _TOUCH_REQUIRED, "support touch")
    frame = opportunities.copy()
    support_price = np.where(
        frame["support_line"].eq("ma5"), frame["ma5"], frame["ma10"]
    ).astype(float)
    frame["support_price"] = support_price
    frame["support_depth"] = frame["support_line"].map(SUPPORT_DEPTH).astype(int)
    entry = pd.to_numeric(frame["entry_price"], errors="coerce")
    low = pd.to_numeric(frame["low_price"], errors="coerce")
    peak = pd.to_numeric(frame["prior_high20"], errors="coerce")
    base = pd.to_numeric(frame["last_ignition_base_close"], errors="coerce")
    frame["close_holds_support"] = entry >= frame["support_price"]
    frame["undercut_depth_pct"] = ((low / frame["support_price"]) - 1.0) * 100.0
    frame["peak_distance_pct"] = ((entry / peak) - 1.0) * 100.0
    frame["leg_gain_pct"] = ((entry / base) - 1.0) * 100.0
    return frame


def rank_auc(features: pd.Series, labels: pd.Series) -> float | None:
    """Mann-Whitney AUC: P(feature_reclaimed > feature_not) + 0.5 * P(tie)."""

    pairs = pd.DataFrame({"f": pd.to_numeric(features, errors="coerce"), "y": labels.astype(bool)}).dropna()
    positives = pairs.loc[pairs["y"], "f"]
    negatives = pairs.loc[~pairs["y"], "f"]
    if positives.empty or negatives.empty:
        return None
    greater = (positives.to_numpy()[:, None] > negatives.to_numpy()[None, :]).mean()
    ties = (positives.to_numpy()[:, None] == negatives.to_numpy()[None, :]).mean()
    return float(greater + 0.5 * ties)


def summarize_feature_stability(
    block_aucs: dict[str, float | None],
    *,
    threshold: float = 0.55,
) -> dict[str, Any]:
    evaluated = {block: auc for block, auc in block_aucs.items() if auc is not None}
    stable = [block for block, auc in evaluated.items() if auc >= threshold]
    return {
        "evaluated_blocks": len(evaluated),
        "stable_blocks": len(stable),
        "block_aucs": {block: round(auc, 4) for block, auc in evaluated.items()},
    }


def run_support_touch_reclaim_feature_study(
    *,
    start: date = date(2024, 8, 1),
    end: date | None = None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Score every pre-registered feature against the reclaim label."""

    from .causal_leader_pullback_study import (
        assign_trade_time_blocks,
        build_causal_stock_features,
        build_concept_campaign_ledger,
        build_dynamic_leader_paths,
        load_causal_leader_pullback_inputs,
        prepare_dynamic_leader_paths,
    )
    from .cross_regime_validation import DEVELOPMENT_BLOCKS, VALIDATION_BLOCKS
    from .leader_pullback_opportunity_funnel_study import build_support_touch_opportunities

    inputs = load_causal_leader_pullback_inputs()
    features = build_causal_stock_features(inputs.stock_bars)
    _, campaign_paths = build_concept_campaign_ledger(inputs.concept_bars)
    leader_paths, coverage = build_dynamic_leader_paths(
        campaign_paths, inputs.memberships, features
    )
    prepared = prepare_dynamic_leader_paths(leader_paths, inputs.market_timing)
    opportunities = build_support_touch_opportunities(
        prepared.campaigns.daily_ledger, leader_paths, features
    )
    end_date = pd.Timestamp(end or opportunities["entry_date"].max()).normalize()
    opportunities = opportunities.loc[
        opportunities["entry_date"].between(pd.Timestamp(start), end_date)
    ].reset_index(drop=True)
    feature_extra = features.loc[
        :,
        [
            "vt_symbol",
            "trade_date",
            "daily_return_pct",
            "close_location",
            "volume_ratio_prior5",
            "turnover_expansion",
            "sessions_since_ignition",
            "last_ignition_base_close",
        ],
    ].copy()
    feature_extra["trade_date"] = pd.to_datetime(feature_extra["trade_date"], errors="raise").dt.normalize()
    opportunities = opportunities.merge(
        feature_extra.rename(columns={"trade_date": "entry_date", "vt_symbol": "vt_symbol"}),
        on=["vt_symbol", "entry_date"],
        how="left",
        validate="many_to_one",
        sort=False,
    )
    if "prior_high20" not in opportunities.columns:
        peak_lookup = leader_paths.loc[:, ["campaign_id", "vt_symbol", "trade_date", "prior_high20"]].copy()
        peak_lookup["trade_date"] = pd.to_datetime(peak_lookup["trade_date"], errors="raise").dt.normalize()
        opportunities = opportunities.merge(
            peak_lookup.rename(columns={"trade_date": "entry_date"}),
            on=["campaign_id", "vt_symbol", "entry_date"],
            how="left",
            validate="one_to_one",
            sort=False,
        )
    labeled = attach_reclaim_labels(opportunities, prepared.signals)
    frame = build_touch_feature_frame(labeled)
    frame = assign_trade_time_blocks(
        frame.assign(variant="support_touch", signal_id=frame["opportunity_id"])
    )

    # 与变体研究一致的行情门:只看 GOLD/NORMAL 且非退潮的可交易触碰
    timing = inputs.market_timing.copy()
    timing["source_date"] = pd.to_datetime(timing["source_date"], errors="raise").dt.normalize()
    frame = frame.merge(
        timing.rename(columns={"source_date": "entry_date"}),
        on="entry_date",
        how="left",
        validate="many_to_one",
        sort=False,
    )
    tradable = frame.loc[
        frame["active_direction"].astype(str).eq("GOLD")
        & frame["danger_state"].astype(str).eq("NORMAL")
        & frame["market_phase"].astype(str).isin(["uptrend", "warming", "rotation"])
    ].reset_index(drop=True)

    labels = tradable["reclaimed"]
    development = tradable["time_block"].isin(DEVELOPMENT_BLOCKS)
    validation = tradable["time_block"].isin(VALIDATION_BLOCKS)
    feature_reports: dict[str, Any] = {}
    for name in PRE_REGISTERED_FEATURES:
        full_auc = rank_auc(tradable[name], labels)
        dev_auc = rank_auc(tradable.loc[development, name], labels.loc[development])
        val_auc = rank_auc(tradable.loc[validation, name], labels.loc[validation])
        block_aucs = {
            block: rank_auc(tradable.loc[mask, name], labels.loc[mask])
            for block, mask in tradable.groupby("time_block").indices.items()
        }
        stability = summarize_feature_stability(block_aucs)
        reclaimed_values = pd.to_numeric(tradable.loc[labels, name], errors="coerce").dropna()
        other_values = pd.to_numeric(tradable.loc[~labels, name], errors="coerce").dropna()
        same_direction = (
            full_auc is not None
            and dev_auc is not None
            and val_auc is not None
            and (dev_auc - 0.5) * (val_auc - 0.5) > 0
        )
        feature_reports[name] = {
            "full_auc": _round(full_auc),
            "development_auc": _round(dev_auc),
            "validation_auc": _round(val_auc),
            **stability,
            "reclaimed_median": _round(float(reclaimed_values.median()) if len(reclaimed_values) else None),
            "other_median": _round(float(other_values.median()) if len(other_values) else None),
            "candidate": bool(
                same_direction
                and full_auc is not None
                and abs(full_auc - 0.5) >= 0.05
                and stability["stable_blocks"] >= 4
            ),
        }

    report = {
        "study_version": STUDY_VERSION,
        "period": {"start": str(start), "end": end_date.date().isoformat()},
        "coverage": coverage,
        "touches": int(len(tradable)),
        "reclaimed": int(labels.sum()),
        "reclaim_rate_pct": round(float(labels.mean() * 100.0), 4),
        "features": feature_reports,
        "boundaries": [
            "Labels are market facts (>=8% reclaim near the visible peak in 1-2 sessions), "
            "not strategy gate outcomes.",
            "Features are discovered on already-viewed history; any candidate needs "
            "out-of-sample or forward confirmation before it may gate entries.",
            "Current concept memberships are replayed backward and create survivorship bias.",
        ],
    }
    return report, tradable


def _round(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _require_columns(frame: pd.DataFrame, required: set[str] | tuple[str, ...], label: str) -> None:
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"{label} missing columns: {sorted(missing)}")
