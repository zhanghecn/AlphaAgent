"""Read-only API view for the frozen cross-regime low-suction evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from .cross_regime_product_report import POLICY_VERSION, RESEARCH_VERSION


REPORT_SHA256 = "97c6f5b174549dd4438faf0085e19c3e8ea3ea85db29f69ed976517fcfcfb19a"
REPORT_PATH = (
    Path(__file__).resolve().parents[4]
    / "memory/06_backtests/low_suction_cross_regime_support_reclaim_v3_summary_20260720.json"
)


def get_swing_research() -> dict[str, Any]:
    """Return the cached compact evidence without running historical research."""

    report, digest = _load_verified_product_report()
    return {
        **dict(report),
        "artifact": {
            "path": str(REPORT_PATH.relative_to(REPORT_PATH.parents[2])),
            "sha256": digest,
        },
    }


@lru_cache(maxsize=1)
def _load_verified_product_report() -> tuple[Mapping[str, Any], str]:
    raw = REPORT_PATH.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != REPORT_SHA256:
        raise ValueError(f"low-suction research fingerprint changed: {digest}")
    report = json.loads(raw.decode("utf-8"))
    if not isinstance(report, Mapping):
        raise ValueError("low-suction research artifact must be an object")
    if report.get("research_version") != RESEARCH_VERSION:
        raise ValueError("unexpected low-suction research version")
    if report.get("policy_version") != POLICY_VERSION:
        raise ValueError("unexpected low-suction policy version")
    if report.get("formal_strategy") is not False:
        raise ValueError("historical proxy must not be exposed as a formal strategy")
    return report, digest
