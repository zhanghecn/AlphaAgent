"""Causal research helpers for a later formally qualified limit-up touch."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up import core_quality


SHANGHAI = ZoneInfo("Asia/Shanghai")
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_EVIDENCE_PATH = (
    REPOSITORY_ROOT
    / "memory"
    / "06_backtests"
    / "limit_up_formal_touch_readiness_20260728.json"
)

QualityRequirement = Literal["mandatory", "progressive", "trigger"]

_TRIGGER_REQUIREMENTS = frozenset(
    {
        "trigger_not_observed",
        "limit_trigger_not_observed",
        "seal_not_observed",
        "reseal_not_observed",
    }
)
_PROGRESSIVE_REQUIREMENTS = frozenset(
    {
        *core_quality.C_RESCUABLE_REASONS,
        "c_components_not_qualified",
        "concept_state",
        "concept_diffusion",
        "industry_flow",
        "sector_flow",
        "stock_flow",
        "turnover_rate",
        "momentum",
    }
)
MINIMUM_PRIOR_SESSIONS = 120
LANDMARK_CHANGE_LEVELS = (3.0, 5.0, 7.0, 8.0, 9.0)
ROUND_TRIP_COST_RATE = 0.0031
MINIMUM_THRESHOLD_SAMPLE_COUNT = 30
MINIMUM_FORMAL_TOUCH_RECALL = 0.30
MINIMUM_MEDIAN_LEAD_MINUTES = 2.0
MINIMUM_D1_WIN_RATE = 0.60
MAXIMUM_CALIBRATION_GAP = 0.05


@dataclass(frozen=True)
class ResearchDateSplit:
    fit: tuple[date, ...]
    calibration: tuple[date, ...]
    validation: tuple[date, ...]


def load_frozen_research_evidence(
    path: str | Path = DEFAULT_EVIDENCE_PATH,
) -> dict[str, object]:
    """Load the durable result artifact without refitting on validation data."""

    evidence_path = Path(path)
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("frozen research evidence must be a JSON object")
    return payload


def audit_frozen_research_evidence(
    evidence: Mapping[str, object],
) -> dict[str, object]:
    """Reapply the registered release gate to the frozen research result."""

    ablations = _mapping(evidence.get("ablations"))
    validation = _mapping(_mapping(evidence.get("split")).get("validation"))
    base_rate_brier = _optional_number(
        validation.get("constant_base_rate_brier")
    )
    threshold_audits: list[dict[str, object]] = []
    for model_name, raw_model in ablations.items():
        model = _mapping(raw_model)
        threshold_rows: dict[str, Mapping[str, object]] = {
            key.removeprefix("threshold_"): _mapping(value)
            for key, value in model.items()
            if key.startswith("threshold_")
        }
        threshold_rows.update(
            {
                str(key): _mapping(value)
                for key, value in _mapping(model.get("thresholds")).items()
            }
        )
        for threshold, metrics in sorted(threshold_rows.items()):
            try:
                displayed_probability = float(threshold) / 100
            except ValueError:
                continue
            model_brier = _optional_number(model.get("point_brier"))
            model_pr_auc = _optional_number(model.get("stock_day_pr_auc"))
            shuffled_p95 = _optional_number(model.get("shuffle_p95_pr_auc"))
            beats_base_rate = model.get("beats_base_rate_brier") is True or (
                model_brier is not None
                and base_rate_brier is not None
                and model_brier < base_rate_brier
            )
            beats_shuffled = model.get("beats_shuffled_pr_auc") is True or (
                model_pr_auc is not None
                and shuffled_p95 is not None
                and model_pr_auc > shuffled_p95
            )
            decision = assess_probability_threshold(
                {
                    **metrics,
                    "beats_base_rate": beats_base_rate,
                    "beats_shuffled_control": beats_shuffled,
                },
                displayed_probability=displayed_probability,
            )
            threshold_audits.append(
                {
                    "model": str(model_name),
                    "threshold_pct": int(round(displayed_probability * 100)),
                    **decision,
                }
            )

    strict_concept = _mapping(evidence.get("strict_concept"))
    minimum = _mapping(strict_concept.get("minimum_required"))
    strict_concept_ready = all(
        _integer(strict_concept.get(f"{part}_trade_date_count"))
        >= _integer(minimum.get(part))
        for part in ("fit", "calibration", "validation")
    )
    eligible_thresholds = [
        row for row in threshold_audits if row.get("eligible") is True
    ]
    target_valid = (
        evidence.get("target") == "later_physical_touch_and_formal_buy_now"
    )
    product_eligible = bool(
        target_valid and strict_concept_ready and eligible_thresholds
    )
    reasons = []
    if not target_valid:
        reasons.append("joint_target_mismatch")
    if not strict_concept_ready:
        reasons.append("strict_concept_coverage_insufficient")
    if not eligible_thresholds:
        reasons.append("no_probability_threshold_passed")
    return {
        "status": "pass" if product_eligible else "rejected",
        "product_eligible": product_eligible,
        "target_valid": target_valid,
        "strict_concept_ready": strict_concept_ready,
        "eligible_threshold_count": len(eligible_thresholds),
        "eligible_thresholds": eligible_thresholds,
        "threshold_audits": threshold_audits,
        "reason_codes": reasons,
        "frozen_decision_consistent": (
            evidence.get("decision") == "REJECT/INSUFFICIENT"
            and not product_eligible
        ),
    }


def assess_probability_threshold(
    metrics: Mapping[str, object],
    *,
    displayed_probability: float,
) -> dict[str, object]:
    """Apply the frozen product gate to one validation threshold report."""

    if not 0 < displayed_probability < 1:
        raise ValueError("displayed_probability must be between zero and one")
    sample_count = _integer(metrics.get("sample_count"))
    precision = _optional_number(metrics.get("precision"))
    recall = _optional_number(metrics.get("recall"))
    lead_minutes = _optional_number(metrics.get("median_lead_minutes"))
    d1_win_rate = _optional_number(metrics.get("d1_win_rate"))
    d1_mean_return = _optional_number(metrics.get("d1_mean_net_return_pct"))
    checks = {
        "sample_count": sample_count >= MINIMUM_THRESHOLD_SAMPLE_COUNT,
        "calibrated_precision": (
            precision is not None
            and precision >= displayed_probability - MAXIMUM_CALIBRATION_GAP
        ),
        "formal_touch_recall": (
            recall is not None and recall >= MINIMUM_FORMAL_TOUCH_RECALL
        ),
        "lead_time": (
            lead_minutes is not None
            and lead_minutes >= MINIMUM_MEDIAN_LEAD_MINUTES
        ),
        "d1_win_rate": (
            d1_win_rate is not None and d1_win_rate >= MINIMUM_D1_WIN_RATE
        ),
        "d1_mean_return": d1_mean_return is not None and d1_mean_return > 0,
        "beats_base_rate": metrics.get("beats_base_rate") is True,
        "beats_shuffled_control": metrics.get("beats_shuffled_control") is True,
    }
    return {
        "eligible": all(checks.values()),
        "displayed_probability": displayed_probability,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }


def joint_event_label(*, later_touched: bool, formal_actionable: bool) -> int:
    """Return the registered joint target, never the physical-touch target alone."""

    return int(later_touched and formal_actionable)


def evaluate_touch_now(
    candidate: Mapping[str, object],
    observed_at: datetime,
    *,
    prior_ab_seen: bool = False,
    c_already_selected: bool = False,
) -> dict[str, object]:
    """Evaluate the shared formal contract as if the first touch occurred now."""

    local_at = _local_datetime(observed_at)
    signal_time = local_at.strftime("%H:%M:%S")
    counterfactual = {
        **dict(candidate),
        "entry_date": local_at.date().isoformat(),
        "signal_time": signal_time,
        "buy_time": signal_time,
        "first_limit_time": signal_time,
        "signal_kind": "first_touch",
    }
    return core_quality.public_quality_gate(
        counterfactual,
        prior_ab_seen=prior_ab_seen,
        c_already_selected=c_already_selected,
        trigger_observed=True,
    )


def classify_quality_requirement(blocker_code: str) -> QualityRequirement:
    """Classify one observed blocker without inventing a second quality gate."""

    code = str(blocker_code or "").strip()
    if code in _TRIGGER_REQUIREMENTS or "trigger_not_observed" in code:
        return "trigger"
    if (
        code in _PROGRESSIVE_REQUIREMENTS
        or code.startswith(("concept_", "sector_", "stock_flow_"))
        or code.endswith("_outside_entry_window")
    ):
        return "progressive"
    return "mandatory"


def build_mother_pool(
    static_rows: Sequence[Mapping[str, object]],
    outcomes: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    """Freeze the label-independent stock-day pool after its first 3% crossing."""

    del outcomes
    selected: dict[tuple[str, str], dict[str, object]] = {}
    for raw in static_rows:
        row = dict(raw)
        symbol = str(row.get("vt_symbol") or "").strip().upper()
        trade_date = _date_text(row.get("trade_date"))
        first_three = _datetime_or_none(
            row.get("first_three_pct_at") or row.get("observed_at")
        )
        if not symbol or not trade_date or first_three is None:
            continue
        if row.get("eligible_main_board") is not True:
            continue
        if row.get("mandatory_gate_passed") is not True:
            continue
        if _integer(row.get("prior_history_count")) < MINIMUM_PRIOR_SESSIONS:
            continue
        if _number(row.get("previous_close")) <= 0:
            continue
        row["vt_symbol"] = symbol
        row["trade_date"] = trade_date
        row["first_three_pct_at"] = first_three
        selected.setdefault((trade_date, symbol), row)
    return [selected[key] for key in sorted(selected)]


def pool_fingerprint(rows: Sequence[Mapping[str, object]]) -> str:
    """Hash only stock-day membership, not any outcome or feature value."""

    pairs = sorted(
        {
            (_date_text(row.get("trade_date")), str(row.get("vt_symbol") or ""))
            for row in rows
            if _date_text(row.get("trade_date")) and row.get("vt_symbol")
        }
    )
    payload = json.dumps(pairs, ensure_ascii=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def build_pre_touch_rows(
    observations: Sequence[Mapping[str, object]],
    touch_at: datetime | None,
) -> list[dict[str, object]]:
    """Return ordered observations strictly before the first physical touch."""

    cutoff = _local_datetime(touch_at) if touch_at is not None else None
    rows: list[dict[str, object]] = []
    for raw in observations:
        observed_at = _datetime_or_none(
            raw.get("observed_at") or raw.get("captured_at")
        )
        if observed_at is None or (cutoff is not None and observed_at >= cutoff):
            continue
        rows.append({**dict(raw), "observed_at": observed_at})
    return sorted(rows, key=lambda row: row["observed_at"])


def leave_one_out_concept_metrics(
    concept: Mapping[str, object],
    *,
    candidate_change_pct: float,
    candidate_near_limit: bool = False,
) -> dict[str, object]:
    """Remove the candidate from exactly recoverable persisted concept breadth."""

    observed = max(_integer(concept.get("observed_count")), 0)
    remaining = max(observed - 1, 0)
    change = float(candidate_change_pct)

    def subtract_count(field: str, included: bool) -> int:
        return max(_integer(concept.get(field)) - int(included), 0)

    average = _optional_number(concept.get("average_change_pct"))
    average_ex_self = (
        round((average * observed - change) / remaining, 6)
        if average is not None and remaining > 0
        else None
    )
    rise_count = subtract_count("rise_count", change > 0)
    return {
        "observed_count_ex_self": remaining,
        "rise_count_ex_self": rise_count,
        "rise_ratio_ex_self": (
            round(rise_count / remaining, 6) if remaining > 0 else None
        ),
        "strong_3_count_ex_self": subtract_count("strong_3_count", change >= 3),
        "strong_5_count_ex_self": subtract_count("strong_5_count", change >= 5),
        "strong_7_count_ex_self": subtract_count("strong_7_count", change >= 7),
        "near_limit_count_ex_self": subtract_count(
            "near_limit_count", candidate_near_limit
        ),
        "average_change_pct_ex_self": average_ex_self,
        "median_change_pct_ex_self": None,
        "weighted_change_pct_ex_self": None,
        "strength_score_ex_self": None,
        "strength_rank_ex_self": None,
        "exact_leave_one_out": False,
        "unavailable_exact_fields": [
            "median_change_pct_ex_self",
            "weighted_change_pct_ex_self",
            "strength_score_ex_self",
            "strength_rank_ex_self",
        ],
    }


def chronological_split(values: Sequence[date | datetime | str]) -> ResearchDateSplit:
    """Freeze non-overlapping fit/calibration/validation dates in market order."""

    dates = tuple(sorted({_as_date(value) for value in values}))
    if len(dates) < 40:
        raise ValueError("at least 40 distinct dates are required")
    if len(dates) >= 75:
        calibration_count = 15
        validation_count = 30
    elif len(dates) >= 50:
        calibration_count = 10
        validation_count = 15
    else:
        calibration_count = 10
        validation_count = 10
    validation = dates[-validation_count:]
    calibration = dates[-(validation_count + calibration_count) : -validation_count]
    fit = dates[: -(validation_count + calibration_count)]
    if len(fit) < 20:
        raise ValueError("at least 20 fit dates are required")
    return ResearchDateSplit(fit, calibration, validation)


def build_landmark_rows(
    candidate: Mapping[str, object],
    minute_rows: Sequence[Mapping[str, object]],
    *,
    formal_actionable: bool,
) -> list[dict[str, object]]:
    """Build one causal row at each first 3/5/7/8/9 percent crossing."""

    previous_close = _number(candidate.get("previous_close"))
    limit_price = _number(candidate.get("limit_price"))
    if previous_close <= 0 or limit_price <= 0:
        return []
    ordered = sorted(
        (
            {**dict(raw), "bar_time": _datetime_or_none(raw.get("bar_time"))}
            for raw in minute_rows
        ),
        key=lambda row: row["bar_time"] or datetime.max.replace(tzinfo=SHANGHAI),
    )
    ordered = [row for row in ordered if row["bar_time"] is not None]
    physical_touch_at = next(
        (
            row["bar_time"]
            for row in ordered
            if _number(row.get("high_price")) >= limit_price - 0.001
        ),
        None,
    )
    joint_label = joint_event_label(
        later_touched=physical_touch_at is not None,
        formal_actionable=formal_actionable,
    )
    d1_close = _optional_number(candidate.get("d1_close_price"))
    formal_d1_return = _net_return_pct(limit_price, d1_close)
    close_changes: list[float] = []
    rows: list[dict[str, object]] = []
    emitted: set[float] = set()
    session_high = previous_close
    for index, minute in enumerate(ordered):
        observed_at = minute["bar_time"]
        if physical_touch_at is not None and observed_at >= physical_touch_at:
            break
        close_price = _number(minute.get("close_price"))
        high_price = _number(minute.get("high_price"))
        if close_price <= 0 or high_price <= 0:
            continue
        close_change = (close_price / previous_close - 1) * 100
        high_change = (high_price / previous_close - 1) * 100
        close_changes.append(close_change)
        session_high = max(session_high, high_price)
        crossed = [
            level
            for level in LANDMARK_CHANGE_LEVELS
            if level not in emitted and high_change + 1e-9 >= level
        ]
        if not crossed:
            continue
        quality = evaluate_touch_now(candidate, observed_at)
        volume = _number(minute.get("volume"))
        turnover = _number(minute.get("turnover"))
        prior_minutes = ordered[max(0, index - 3) : index]
        rows.extend(
            {
                **dict(candidate),
                "observed_at": observed_at,
                "landmark_change_pct": level,
                "observed_change_pct": round(close_change, 6),
                "distance_to_limit_pct": round(
                    max((limit_price - close_price) / limit_price * 100, 0.0),
                    6,
                ),
                "price_slope_1m": _lag_delta(close_changes, 1),
                "price_slope_3m": _lag_delta(close_changes, 3),
                "price_slope_5m": _lag_delta(close_changes, 5),
                "volume_ratio_3m": _current_to_prior_mean(
                    volume, prior_minutes, "volume"
                ),
                "turnover_ratio_3m": _current_to_prior_mean(
                    turnover, prior_minutes, "turnover"
                ),
                "pullback_from_intraday_high_pct": round(
                    (close_price / session_high - 1) * 100,
                    6,
                ),
                "recovery_slope_5m": round(
                    close_change - min(close_changes[-6:]), 6
                ),
                "session_minute_index": _session_minute_index(observed_at),
                "current_price": close_price,
                "physical_touch_at": physical_touch_at,
                "lead_minutes": (
                    _trading_minute_distance(observed_at, physical_touch_at)
                    if physical_touch_at is not None
                    else None
                ),
                "formal_actionable_at_touch": formal_actionable,
                "joint_event_label": joint_label,
                "early_entry_d1_net_return_pct": _net_return_pct(
                    close_price, d1_close
                ),
                "formal_d1_net_return_pct": formal_d1_return,
                "hypothetical_quality_actionable": quality.get(
                    "public_quality_actionable"
                )
                is True,
                "hypothetical_quality_tier": quality.get(
                    "quality_priority_tier"
                ),
                "hypothetical_quality_win_probability": quality.get(
                    "quality_win_probability"
                ),
                "hypothetical_quality_expected_d1_return_pct": quality.get(
                    "quality_expected_d1_net_return_pct"
                ),
                "hypothetical_quality_reason": quality.get(
                    "public_quality_reason"
                ),
            }
            for level in crossed
        )
        emitted.update(crossed)
    return rows


def research_coverage_audit() -> dict[str, object]:
    """Read compact source coverage without creating research or product rows."""

    from sqlalchemy import case, distinct, func, select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import session_scope

    frame = schema.limit_up_radar_frames
    observation = schema.limit_up_radar_observations
    concept = schema.limit_up_concept_strength_snapshots
    frame_statement = (
        select(
            frame.c.trade_date,
            frame.c.strategy_version,
            func.count().label("frame_count"),
            func.sum(frame.c.capture_count).label("declared_observation_count"),
            func.min(frame.c.captured_at).label("first_captured_at"),
            func.max(frame.c.captured_at).label("last_captured_at"),
            func.avg(case((frame.c.quality_status == "ready", 1.0), else_=0.0)).label(
                "ready_frame_ratio"
            ),
        )
        .group_by(frame.c.trade_date, frame.c.strategy_version)
        .order_by(frame.c.trade_date, frame.c.strategy_version)
    )
    observation_statement = (
        select(
            frame.c.trade_date,
            frame.c.strategy_version,
            func.count().label("observation_count"),
            func.count(distinct(observation.c.vt_symbol)).label("symbol_count"),
        )
        .select_from(observation.join(frame, observation.c.frame_id == frame.c.id))
        .group_by(frame.c.trade_date, frame.c.strategy_version)
    )
    concept_statement = (
        select(
            concept.c.trade_date,
            func.count().label("row_count"),
            func.count(distinct(concept.c.concept_id)).label("concept_count"),
            func.min(concept.c.captured_at).label("first_captured_at"),
            func.max(concept.c.captured_at).label("last_captured_at"),
        )
        .group_by(concept.c.trade_date)
        .order_by(concept.c.trade_date)
    )
    with session_scope() as session:
        frame_rows = [dict(row) for row in session.execute(frame_statement).mappings()]
        observation_rows = {
            (row["trade_date"], row["strategy_version"]): dict(row)
            for row in session.execute(observation_statement).mappings()
        }
        concept_rows = [
            dict(row) for row in session.execute(concept_statement).mappings()
        ]

    radar_days = []
    for row in frame_rows:
        observed = observation_rows.get(
            (row["trade_date"], row["strategy_version"]), {}
        )
        radar_days.append(
            _plain_json(
                {
                    **row,
                    "observation_count": int(observed.get("observation_count") or 0),
                    "symbol_count": int(observed.get("symbol_count") or 0),
                    "source_role": (
                        "natural_v2"
                        if row["strategy_version"]
                        == core_quality.PUBLIC_QUALITY_CONTRACT_VERSION
                        else "old_frame_diagnostic"
                    ),
                }
            )
        )
    strict_concept_dates = sorted(
        {
            str(row["trade_date"])
            for row in concept_rows
            if int(row.get("concept_count") or 0) > 0
        }
    )
    return {
        "status": "ready" if radar_days else "unavailable",
        "target": "later_physical_touch_and_formal_buy_now",
        "formal_contract": core_quality.PUBLIC_QUALITY_CONTRACT_VERSION,
        "radar_days": radar_days,
        "radar_trade_date_count": len(
            {str(row["trade_date"]) for row in frame_rows}
        ),
        "natural_v2_trade_dates": sorted(
            {
                str(row["trade_date"])
                for row in frame_rows
                if row["strategy_version"]
                == core_quality.PUBLIC_QUALITY_CONTRACT_VERSION
            }
        ),
        "strict_concept_trade_dates": strict_concept_dates,
        "strict_concept_trade_date_count": len(strict_concept_dates),
        "strict_concept_split_ready": len(strict_concept_dates) >= 40,
        "concept_days": [_plain_json(row) for row in concept_rows],
    }


def _local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def _datetime_or_none(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return _local_datetime(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return _local_datetime(datetime.fromisoformat(text))
    except ValueError:
        return None


def _date_text(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return ""


def _as_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _integer(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _number(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _optional_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _lag_delta(values: Sequence[float], lag: int) -> float | None:
    if len(values) <= lag:
        return None
    return round(values[-1] - values[-(lag + 1)], 6)


def _current_to_prior_mean(
    current: float,
    prior_rows: Sequence[Mapping[str, object]],
    field: str,
) -> float | None:
    values = [
        value
        for row in prior_rows
        if (value := _optional_number(row.get(field))) is not None and value > 0
    ]
    if not values:
        return None
    baseline = sum(values) / len(values)
    return round(current / baseline, 6) if baseline > 0 else None


def _session_minute_index(value: datetime) -> int:
    local = _local_datetime(value)
    minutes = local.hour * 60 + local.minute
    morning_start = 9 * 60 + 30
    morning_end = 11 * 60 + 30
    afternoon_start = 13 * 60
    if minutes <= morning_end:
        return max(minutes - morning_start, 0)
    return 120 + max(minutes - afternoon_start, 0)


def _trading_minute_distance(start: datetime, end: datetime) -> int:
    return max(_session_minute_index(end) - _session_minute_index(start), 0)


def _net_return_pct(entry_price: float, exit_price: float | None) -> float | None:
    if entry_price <= 0 or exit_price is None or exit_price <= 0:
        return None
    return round(((exit_price / entry_price - 1) - ROUND_TRIP_COST_RATE) * 100, 6)


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_plain_json(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--evidence", default=str(DEFAULT_EVIDENCE_PATH))
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    coverage = research_coverage_audit()
    if args.audit_only:
        report = coverage
    else:
        evidence = load_frozen_research_evidence(args.evidence)
        report = {
            "status": "completed",
            "current_coverage": coverage,
            "frozen_evidence": evidence,
            "acceptance_audit": audit_frozen_research_evidence(evidence),
        }
    content = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(content + "\n", encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()
