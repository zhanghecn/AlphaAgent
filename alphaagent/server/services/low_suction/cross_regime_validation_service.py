"""Read-only product view for the latest cross-regime candidate evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from .causal_leader_pullback_forward_repository import (
    load_causal_forward_report,
)


REPORT_SHA256 = "59bee1d182c511d4c26f586a2593ca52c42f5a817197fa6aca7a9a4b695cdb42"
REPORT_PATH = (
    Path(__file__).resolve().parents[4]
    / "memory/06_backtests/low_suction_cross_regime_rotation_timeliness_v5_20260721.json"
)
REPORT_VERSION = "cross-regime-validation-product-v1"
STUDY_VERSION = "cross-regime-warming-failure-study-v5"
THREE_PHASE_REPORT_SHA256 = (
    "ccfeed5e4254c435d9821fdca96c9670adfc9fa3965b0d53f68da416e1c7a111"
)
THREE_PHASE_REPORT_PATH = (
    Path(__file__).resolve().parents[4]
    / "memory/06_backtests/low_suction_three_phase_adaptive_diagnostic_20260721.json"
)


def get_cross_regime_validation() -> dict[str, Any]:
    """Combine immutable historical evidence with the live natural ledger."""

    report, digest = _load_verified_report()
    three_phase_report, three_phase_digest = _load_verified_three_phase_report()
    candidate = _required_mapping(report, "candidate")
    adaptive = _required_mapping(report, "adaptive_diagnostic")
    forward = load_causal_forward_report()
    diagnostics = _required_mapping(forward, "diagnostic_policies")
    natural = _required_mapping(
        diagnostics,
        str(adaptive["policy_version"]),
    )
    three_phase_policy = str(three_phase_report["policy_version"])
    three_phase_natural = _required_mapping(diagnostics, three_phase_policy)
    return {
        "report_version": REPORT_VERSION,
        "formal_strategy": False,
        "current_candidate": _candidate_view(candidate),
        "adaptive_candidate": _adaptive_view(adaptive),
        "three_phase_candidate": _three_phase_view(three_phase_report),
        "natural_forward": natural,
        "three_phase_natural_forward": three_phase_natural,
        "boundaries": [
            "历史 86/81 笔均为已查看样本，不是自然前向绩效",
            "rotation 次日确认不改变当前 V2 信号，也不创建推荐或订单",
            "只有自然前向 40/20 样本门与全部绩效门通过才公开验证指标",
            "三行情候选独立使用 50/10/20/20 自然样本门，retreat 始终空仓",
        ],
        "artifact": {
            "path": str(REPORT_PATH.relative_to(REPORT_PATH.parents[2])),
            "sha256": digest,
        },
        "three_phase_artifact": {
            "path": str(
                THREE_PHASE_REPORT_PATH.relative_to(THREE_PHASE_REPORT_PATH.parents[2])
            ),
            "sha256": three_phase_digest,
        },
    }


def _candidate_view(candidate: Mapping[str, Any]) -> dict[str, Any]:
    audit = _required_mapping(candidate, "sequential_audit")
    return {
        "policy_version": candidate["policy_version"],
        "formal_strategy": False,
        "rule": candidate["rule"],
        "full_history": candidate["full_history"],
        "development": audit["development"],
        "validation": audit["validation"],
        "validation_market_phases": audit["validation_market_phases"],
        "cash": candidate["cash"],
        "qualification": candidate["qualification"],
        "formal_blockers": candidate["formal_blockers"],
    }


def _adaptive_view(adaptive: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "policy_version": adaptive["policy_version"],
        "selection_origin": adaptive["selection_origin"],
        "formal_strategy": False,
        "rule": adaptive["rule"],
        "full_history": adaptive["full_history"],
        "development": adaptive["development"],
        "validation": adaptive["validation"],
        "development_market_phases": adaptive["development_market_phases"],
        "validation_market_phases": adaptive["validation_market_phases"],
        "cash": adaptive["cash"],
        "qualification": adaptive["qualification"],
        "formal_blockers": adaptive["formal_blockers"],
    }


def _three_phase_view(report: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _required_mapping(report, "historical_metrics")
    robustness = _required_mapping(report, "robustness_diagnostics")
    return {
        "policy_version": report["policy_version"],
        "selection_origin": report["research_status"],
        "formal_strategy": False,
        "rule": report["rule"],
        "execution_contract": dict(_required_mapping(report, "execution_contract")),
        "full_history": _three_phase_return_metrics(
            _required_mapping(metrics, "full_history")
        ),
        "development": _three_phase_return_metrics(
            _required_mapping(metrics, "development")
        ),
        "validation": _three_phase_return_metrics(
            _required_mapping(metrics, "validation")
        ),
        "development_market_phases": _three_phase_market_phases(
            report, robustness, "development"
        ),
        "validation_market_phases": _three_phase_market_phases(
            report, robustness, "validation"
        ),
        "robustness": dict(robustness),
        "cash": dict(_required_mapping(metrics, "two_slot_cash")),
        "qualification": {
            "historical_numeric_gates_passed": False,
            "status": "pre_registered_posthoc_historical_diagnostic",
            "failed_gates": ["natural_forward_50_10_20_20_not_met"],
        },
        "formal_blockers": list(report.get("boundaries") or []),
    }


def _three_phase_market_phases(
    report: Mapping[str, Any],
    robustness: Mapping[str, Any],
    split: str,
) -> list[dict[str, Any]]:
    diagnostics = _required_mapping(report, "phase_diagnostics")
    split_robustness = _required_mapping(robustness, split)
    rows = []
    for phase in ("uptrend", "rotation", "warming"):
        phase_metrics = _required_mapping(_required_mapping(diagnostics, phase), split)
        phase_robustness = _required_mapping(split_robustness, phase)
        rows.append(
            {
                "id": phase,
                "closed_trades": int(phase_metrics["trades"]),
                "win_rate_pct": phase_metrics["win_rate_pct"],
                "mean_net_return_pct": phase_metrics["mean_net_return_pct"],
                "profit_factor": None,
                "wilson_95_lower_pct": phase_robustness["wilson_95_lower_pct"],
            }
        )
    return rows


def _three_phase_return_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "closed_trades": int(metrics["trades"]),
        "win_rate_pct": metrics["win_rate_pct"],
        "mean_net_return_pct": metrics["mean_net_return_pct"],
        "profit_factor": metrics["profit_factor"],
    }


@lru_cache(maxsize=1)
def _load_verified_report() -> tuple[Mapping[str, Any], str]:
    raw = REPORT_PATH.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != REPORT_SHA256:
        raise ValueError(f"cross-regime validation fingerprint changed: {digest}")
    report = json.loads(raw.decode("utf-8"))
    if not isinstance(report, Mapping):
        raise ValueError("cross-regime validation artifact must be an object")
    if report.get("study_version") != STUDY_VERSION:
        raise ValueError("unexpected cross-regime validation study version")
    if report.get("formal_strategy") is not False:
        raise ValueError("historical validation must remain non-formal")
    return report, digest


@lru_cache(maxsize=1)
def _load_verified_three_phase_report() -> tuple[Mapping[str, Any], str]:
    raw = THREE_PHASE_REPORT_PATH.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != THREE_PHASE_REPORT_SHA256:
        raise ValueError(f"three-phase diagnostic fingerprint changed: {digest}")
    report = json.loads(raw.decode("utf-8"))
    if not isinstance(report, Mapping):
        raise ValueError("three-phase diagnostic artifact must be an object")
    if report.get("formal_strategy") is not False:
        raise ValueError("three-phase historical diagnostic must remain non-formal")
    return report, digest


def _required_mapping(row: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = row.get(field)
    if not isinstance(value, Mapping):
        raise ValueError(f"cross-regime validation {field} must be an object")
    return value
