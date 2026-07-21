"""Sequential robustness audit for the frozen cross-regime proxy rule."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from statistics import median
from typing import Any


AUDIT_VERSION = "cross-regime-sequential-audit-v1"
VARIANT = "cross_regime_support_reclaim_confirmation"
DEVELOPMENT_BLOCKS = ("block_1", "block_2", "block_3")
VALIDATION_BLOCKS = ("block_4", "block_5")
EXTRA_COST_LEVELS_PCT = (0.0, 0.2, 0.4, 0.8)
MIN_VALIDATION_TRADES = 40
MIN_VALIDATION_BLOCK_TRADES = 15
MIN_MATERIAL_PHASE_TRADES = 20
MIN_QUALIFIED_PHASES = 2
MIN_WIN_RATE_PCT = 60.0
MIN_PROFIT_FACTOR = 1.2
DEFAULT_BOOTSTRAP_DRAWS = 10_000
DEFAULT_BOOTSTRAP_SEED = 20_260_720
WILSON_Z_95 = 1.959963984540054


def build_sequential_regime_audit(
    trades: Sequence[Mapping[str, Any]],
    signals: Sequence[Mapping[str, Any]],
    *,
    bootstrap_draws: int = DEFAULT_BOOTSTRAP_DRAWS,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Evaluate a frozen rule; validation rows can reject but never refine it."""

    rows = _joined_variant_rows(trades, signals)
    development = _rows_in_blocks(rows, DEVELOPMENT_BLOCKS)
    validation = _rows_in_blocks(rows, VALIDATION_BLOCKS)
    full_metrics = _return_metrics(rows)
    development_metrics = _return_metrics(development)
    validation_metrics = _return_metrics(validation)
    validation_blocks = _group_metrics(
        validation,
        "time_block",
        VALIDATION_BLOCKS,
    )
    validation_phases = _group_metrics(validation, "market_phase")
    cost_stress = _cost_stress(rows, validation)
    confidence = _confidence(
        rows,
        validation,
        bootstrap_draws=bootstrap_draws,
        bootstrap_seed=bootstrap_seed,
    )
    qualification = _qualification(
        validation_metrics,
        validation_blocks,
        validation_phases,
        cost_stress,
        confidence,
    )
    return {
        "audit_version": AUDIT_VERSION,
        "variant": VARIANT,
        "trade_identity_sha256": _trade_identity_sha256(rows),
        "split": {
            "development_blocks": list(DEVELOPMENT_BLOCKS),
            "validation_blocks": list(VALIDATION_BLOCKS),
            "validation_policy": "frozen_rule_rejection_only",
        },
        "full_history": full_metrics,
        "development": development_metrics,
        "validation": validation_metrics,
        "validation_time_blocks": validation_blocks,
        "validation_market_phases": validation_phases,
        "cost_stress": cost_stress,
        "concentration": _positive_profit_concentration(rows),
        "confidence": confidence,
        "qualification": qualification,
    }


def _joined_variant_rows(
    trades: Sequence[Mapping[str, Any]],
    signals: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    signal_by_id: dict[str, Mapping[str, Any]] = {}
    for signal in signals:
        signal_id = _required_text(signal, "signal_id", "signal")
        if signal_id in signal_by_id:
            raise ValueError("signal identities must be unique")
        signal_by_id[signal_id] = signal

    rows = []
    seen_trade_ids: set[str] = set()
    for trade in trades:
        if str(trade.get("variant") or "") != VARIANT:
            continue
        signal_id = _required_text(trade, "signal_id", "trade")
        if signal_id in seen_trade_ids:
            raise ValueError("trade identities must be unique")
        seen_trade_ids.add(signal_id)
        signal = signal_by_id.get(signal_id)
        if signal is None:
            raise ValueError(f"trade signal is missing: {signal_id}")
        net_return = _required_number(trade, "net_return_pct", "trade")
        time_block = _required_text(trade, "time_block", "trade")
        if time_block not in {*DEVELOPMENT_BLOCKS, *VALIDATION_BLOCKS}:
            raise ValueError(f"unexpected time block: {time_block}")
        rows.append(
            {
                **dict(trade),
                "signal_id": signal_id,
                "net_return_pct": net_return,
                "entry_date": _required_text(trade, "entry_date", "trade"),
                "campaign_id": _required_text(trade, "campaign_id", "trade"),
                "market_phase": _required_text(trade, "market_phase", "trade"),
                "vt_symbol": _required_text(trade, "vt_symbol", "trade"),
                "concept_name": _required_text(signal, "concept_name", "signal"),
            }
        )
    if not rows:
        raise ValueError("cross-regime trades are empty")
    return sorted(rows, key=lambda row: (row["entry_date"], row["signal_id"]))


def _rows_in_blocks(
    rows: Sequence[Mapping[str, Any]],
    blocks: Sequence[str],
) -> list[Mapping[str, Any]]:
    allowed = set(blocks)
    return [row for row in rows if row.get("time_block") in allowed]


def _return_metrics(
    rows: Sequence[Mapping[str, Any]],
    *,
    extra_cost_pct: float = 0.0,
) -> dict[str, Any]:
    returns = [float(row["net_return_pct"]) - extra_cost_pct for row in rows]
    if not returns:
        return {
            "closed_trades": 0,
            "winning_trades": 0,
            "win_rate_pct": None,
            "mean_net_return_pct": None,
            "median_net_return_pct": None,
            "profit_factor": None,
            "signal_compound_return_pct": None,
        }
    wins = [value for value in returns if value > 0.0]
    losses = [value for value in returns if value < 0.0]
    return {
        "closed_trades": len(returns),
        "winning_trades": len(wins),
        "win_rate_pct": len(wins) / len(returns) * 100.0,
        "mean_net_return_pct": sum(returns) / len(returns),
        "median_net_return_pct": median(returns),
        "profit_factor": sum(wins) / -sum(losses) if losses else None,
        "signal_compound_return_pct": (
            math.prod(1.0 + value / 100.0 for value in returns) - 1.0
        )
        * 100.0,
    }


def _group_metrics(
    rows: Sequence[Mapping[str, Any]],
    field: str,
    identifiers: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(field) or "UNKNOWN")].append(row)
    order = list(identifiers) if identifiers is not None else sorted(groups)
    return [
        {"id": identifier, **_return_metrics(groups.get(identifier, []))}
        for identifier in order
    ]


def _cost_stress(
    full_rows: Sequence[Mapping[str, Any]],
    validation_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "extra_cost_pct": extra_cost,
            "full_history": _return_metrics(
                full_rows,
                extra_cost_pct=extra_cost,
            ),
            "validation": _return_metrics(
                validation_rows,
                extra_cost_pct=extra_cost,
            ),
        }
        for extra_cost in EXTRA_COST_LEVELS_PCT
    ]


def _confidence(
    full_rows: Sequence[Mapping[str, Any]],
    validation_rows: Sequence[Mapping[str, Any]],
    *,
    bootstrap_draws: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    if bootstrap_draws <= 0:
        raise ValueError("bootstrap_draws must be positive")
    full_wins = sum(float(row["net_return_pct"]) > 0.0 for row in full_rows)
    validation_wins = sum(
        float(row["net_return_pct"]) > 0.0 for row in validation_rows
    )
    full_bootstrap = _two_axis_cluster_bootstrap(
        full_rows,
        draws=bootstrap_draws,
        seed=bootstrap_seed,
    )
    validation_bootstrap = _two_axis_cluster_bootstrap(
        validation_rows,
        draws=bootstrap_draws,
        seed=bootstrap_seed + 1,
    )
    return {
        "bootstrap_draws": bootstrap_draws,
        "bootstrap_seed": bootstrap_seed,
        "full_history_wilson_95_lower_win_rate_pct": _wilson_lower_bound(
            full_wins,
            len(full_rows),
        ),
        "validation_wilson_95_lower_win_rate_pct": _wilson_lower_bound(
            validation_wins,
            len(validation_rows),
        ),
        "full_history_cluster_bootstrap": full_bootstrap,
        "validation_cluster_bootstrap": validation_bootstrap,
    }


def _two_axis_cluster_bootstrap(
    rows: Sequence[Mapping[str, Any]],
    *,
    draws: int,
    seed: int,
) -> dict[str, Any]:
    by_trade_date = _cluster_bootstrap(
        rows,
        field="entry_date",
        draws=draws,
        seed=seed,
    )
    by_campaign = _cluster_bootstrap(
        rows,
        field="campaign_id",
        draws=draws,
        seed=seed + 10_000,
    )
    return {
        "trade_date": by_trade_date,
        "concept_cycle": by_campaign,
        "conservative_mean_return_95_lower_pct": min(
            by_trade_date["mean_return_95_lower_pct"],
            by_campaign["mean_return_95_lower_pct"],
        ),
        "conservative_win_rate_95_lower_pct": min(
            by_trade_date["win_rate_95_lower_pct"],
            by_campaign["win_rate_95_lower_pct"],
        ),
    }


def _cluster_bootstrap(
    rows: Sequence[Mapping[str, Any]],
    *,
    field: str,
    draws: int,
    seed: int,
) -> dict[str, float]:
    clusters: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        clusters[str(row[field])].append(float(row["net_return_pct"]))
    cluster_values = list(clusters.values())
    if not cluster_values:
        return {
            "mean_return_95_lower_pct": 0.0,
            "mean_return_95_upper_pct": 0.0,
            "win_rate_95_lower_pct": 0.0,
            "win_rate_95_upper_pct": 0.0,
        }
    rng = random.Random(seed)
    mean_samples = []
    win_rate_samples = []
    for _ in range(draws):
        sampled = [
            value
            for _ in cluster_values
            for value in rng.choice(cluster_values)
        ]
        mean_samples.append(sum(sampled) / len(sampled))
        win_rate_samples.append(
            sum(value > 0.0 for value in sampled) / len(sampled) * 100.0
        )
    return {
        "mean_return_95_lower_pct": _quantile(mean_samples, 0.025),
        "mean_return_95_upper_pct": _quantile(mean_samples, 0.975),
        "win_rate_95_lower_pct": _quantile(win_rate_samples, 0.025),
        "win_rate_95_upper_pct": _quantile(win_rate_samples, 0.975),
    }


def _positive_profit_concentration(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        "symbol": _maximum_positive_share(rows, "vt_symbol"),
        "concept": _maximum_positive_share(rows, "concept_name"),
        "calendar_month": _maximum_positive_share(rows, "entry_month"),
    }


def _maximum_positive_share(
    rows: Sequence[Mapping[str, Any]],
    field: str,
) -> dict[str, Any]:
    contributions: dict[str, float] = defaultdict(float)
    for row in rows:
        identifier = (
            str(row["entry_date"])[:7]
            if field == "entry_month"
            else str(row[field])
        )
        contributions[identifier] += max(float(row["net_return_pct"]), 0.0)
    total = sum(contributions.values())
    if not contributions or total <= 0.0:
        return {"id": None, "positive_profit_pct": 0.0, "share_pct": None}
    identifier, contribution = max(
        contributions.items(),
        key=lambda item: (item[1], item[0]),
    )
    return {
        "id": identifier,
        "positive_profit_pct": contribution,
        "share_pct": contribution / total * 100.0,
    }


def _qualification(
    validation: Mapping[str, Any],
    blocks: Sequence[Mapping[str, Any]],
    phases: Sequence[Mapping[str, Any]],
    cost_stress: Sequence[Mapping[str, Any]],
    confidence: Mapping[str, Any],
) -> dict[str, Any]:
    point_failures = []
    if int(validation["closed_trades"]) < MIN_VALIDATION_TRADES:
        point_failures.append("validation_closed_trades<40")
    if _number_or_zero(validation.get("win_rate_pct")) <= MIN_WIN_RATE_PCT:
        point_failures.append("validation_win_rate<=60pct")
    if _number_or_zero(validation.get("mean_net_return_pct")) <= 0.0:
        point_failures.append("validation_mean_return<=0")
    if _number_or_zero(validation.get("profit_factor")) < MIN_PROFIT_FACTOR:
        point_failures.append("validation_profit_factor<1.2")
    for block in blocks:
        block_id = str(block["id"])
        if int(block["closed_trades"]) < MIN_VALIDATION_BLOCK_TRADES:
            point_failures.append(f"validation_block_trades<15:{block_id}")
        if _number_or_zero(block.get("win_rate_pct")) <= MIN_WIN_RATE_PCT:
            point_failures.append(f"validation_block_win_rate<=60pct:{block_id}")
        if _number_or_zero(block.get("mean_net_return_pct")) <= 0.0:
            point_failures.append(f"validation_block_mean_return<=0:{block_id}")

    material_phases = [
        phase
        for phase in phases
        if int(phase["closed_trades"]) >= MIN_MATERIAL_PHASE_TRADES
    ]
    qualified_phases = []
    for phase in material_phases:
        phase_id = str(phase["id"])
        phase_passed = True
        if _number_or_zero(phase.get("win_rate_pct")) <= MIN_WIN_RATE_PCT:
            point_failures.append(f"validation_phase_win_rate<=60pct:{phase_id}")
            phase_passed = False
        if _number_or_zero(phase.get("mean_net_return_pct")) <= 0.0:
            point_failures.append(f"validation_phase_mean_return<=0:{phase_id}")
            phase_passed = False
        if _number_or_zero(phase.get("profit_factor")) < MIN_PROFIT_FACTOR:
            point_failures.append(f"validation_phase_profit_factor<1.2:{phase_id}")
            phase_passed = False
        if phase_passed:
            qualified_phases.append(phase_id)
    if len(material_phases) < MIN_QUALIFIED_PHASES:
        point_failures.append("material_validation_phases<2")
    if len(qualified_phases) < MIN_QUALIFIED_PHASES:
        point_failures.append("qualified_validation_phases<2")

    double_cost_validation = cost_stress[1]["validation"]
    if _number_or_zero(double_cost_validation.get("mean_net_return_pct")) <= 0.0:
        point_failures.append("validation_double_cost_mean<=0")

    confidence_failures = []
    if (
        _number_or_zero(confidence["full_history_wilson_95_lower_win_rate_pct"])
        <= MIN_WIN_RATE_PCT
    ):
        confidence_failures.append("full_history_wilson_95_lower<=60pct")
    if (
        _number_or_zero(confidence["validation_wilson_95_lower_win_rate_pct"])
        <= MIN_WIN_RATE_PCT
    ):
        confidence_failures.append("validation_wilson_95_lower<=60pct")
    validation_bootstrap = confidence["validation_cluster_bootstrap"]
    if (
        _number_or_zero(
            validation_bootstrap["conservative_mean_return_95_lower_pct"]
        )
        <= 0.0
    ):
        confidence_failures.append("validation_bootstrap_mean_95_lower<=0")

    return {
        "sequential_point_gate_passed": not point_failures,
        "confidence_gate_passed": not confidence_failures,
        "sequential_cross_regime_passed": not point_failures
        and not confidence_failures,
        "material_validation_phases": [str(phase["id"]) for phase in material_phases],
        "qualified_validation_phases": qualified_phases,
        "failed_gates": [*point_failures, *confidence_failures],
    }


def _wilson_lower_bound(wins: int, total: int) -> float:
    if total <= 0:
        return 0.0
    rate = wins / total
    denominator = 1.0 + WILSON_Z_95**2 / total
    center = (rate + WILSON_Z_95**2 / (2.0 * total)) / denominator
    half_width = (
        WILSON_Z_95
        * math.sqrt(
            rate * (1.0 - rate) / total
            + WILSON_Z_95**2 / (4.0 * total**2)
        )
        / denominator
    )
    return (center - half_width) * 100.0


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _trade_identity_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    payload = [
        {
            "signal_id": row["signal_id"],
            "entry_date": row["entry_date"],
            "net_return_pct": row["net_return_pct"],
        }
        for row in rows
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_text(row: Mapping[str, Any], field: str, label: str) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise ValueError(f"{label} {field} is missing")
    return value


def _required_number(row: Mapping[str, Any], field: str, label: str) -> float:
    value = row.get(field)
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} {field} is missing")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} {field} is not finite")
    return number


def _number_or_zero(value: object) -> float:
    return float(value) if value is not None else 0.0
