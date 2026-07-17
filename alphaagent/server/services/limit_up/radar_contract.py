"""Point-in-time capture and formal-entry boundaries for first-board radar."""

from __future__ import annotations

from alphaagent.server.services.limit_up.versions import LIVE_STRATEGY_VERSION


CAPTURE_MIN_CHANGE_PCT = 3.0
FORMAL_MIN_CHANGE_PCT = 5.0
RADAR_CONTRACT_VERSION = "limit-up-radar-contract-v1"
POOL_STATES = frozenset({"sealed", "resealed", "failed"})
PRODUCTION_CONTRACTS = {
    ("limit-up-live-v15", 5.0): "formal_5pct",
    ("limit-up-live-v16", 3.0): "early_3pct_same_rules",
}


def resolve_production_radar_contract(
    *,
    live_version: str,
    formal_min_change_pct: float,
) -> str:
    key = (str(live_version), float(formal_min_change_pct))
    try:
        return PRODUCTION_CONTRACTS[key]
    except KeyError as exc:
        raise RuntimeError(
            "inconsistent radar production contract: "
            f"live_version={key[0]} formal_min_change_pct={key[1]}"
        ) from exc


PRODUCTION_RADAR_CONTRACT = resolve_production_radar_contract(
    live_version=LIVE_STRATEGY_VERSION,
    formal_min_change_pct=FORMAL_MIN_CHANGE_PCT,
)


def capture_state(*, change_pct: float, pool_state: str) -> str:
    """Classify an observed quote without turning capture into execution."""

    if pool_state in POOL_STATES:
        return pool_state
    return "near_limit" if change_pct >= FORMAL_MIN_CHANGE_PCT else "pre_radar"


def is_formal_candidate(*, change_pct: float, state: str) -> bool:
    """Return whether the candidate belongs to the unchanged v15 public path."""

    return state in POOL_STATES or change_pct >= FORMAL_MIN_CHANGE_PCT
