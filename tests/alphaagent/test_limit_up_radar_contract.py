import pytest

from alphaagent.server.services.limit_up.radar_contract import (
    CAPTURE_MIN_CHANGE_PCT,
    FORMAL_MIN_CHANGE_PCT,
    PRODUCTION_RADAR_CONTRACT,
    capture_state,
    is_formal_candidate,
    resolve_production_radar_contract,
)


def test_three_percent_starts_capture_but_not_formal_execution() -> None:
    assert CAPTURE_MIN_CHANGE_PCT == 3.0
    assert FORMAL_MIN_CHANGE_PCT == 5.0
    assert capture_state(change_pct=3.2, pool_state="quote") == "pre_radar"
    assert is_formal_candidate(change_pct=3.2, state="pre_radar") is False


def test_five_percent_enters_existing_formal_state() -> None:
    assert capture_state(change_pct=5.0, pool_state="quote") == "near_limit"
    assert is_formal_candidate(change_pct=5.0, state="near_limit") is True


def test_limit_pool_state_is_always_formal() -> None:
    assert capture_state(change_pct=1.0, pool_state="sealed") == "sealed"
    assert is_formal_candidate(change_pct=1.0, state="sealed") is True


def test_production_version_and_threshold_are_one_atomic_contract() -> None:
    assert PRODUCTION_RADAR_CONTRACT == "core_abc_formal_5pct"
    assert (
        resolve_production_radar_contract(
            live_version="limit-up-core-abc-v1",
            formal_min_change_pct=5.0,
        )
        == "core_abc_formal_5pct"
    )


@pytest.mark.parametrize(
    ("live_version", "formal_min_change_pct"),
    [
        ("obsolete-version", 3.0),
        ("obsolete-version", 5.0),
        ("limit-up-core-abc-v1", 3.0),
    ],
)
def test_partial_production_activation_fails_closed(
    live_version: str,
    formal_min_change_pct: float,
) -> None:
    with pytest.raises(RuntimeError, match="inconsistent radar production contract"):
        resolve_production_radar_contract(
            live_version=live_version,
            formal_min_change_pct=formal_min_change_pct,
        )
