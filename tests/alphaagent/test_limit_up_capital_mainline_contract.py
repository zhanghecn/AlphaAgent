from __future__ import annotations

from datetime import date

import pytest

from alphaagent.server.services.limit_up.capital_mainline_contract import (
    CapitalRole,
    CapitalRoleRow,
    EvidenceLevel,
    capital_evidence_level,
    validate_asof_fields,
)


def test_future_outcomes_cannot_enter_asof_role_features() -> None:
    with pytest.raises(ValueError, match="future feature"):
        validate_asof_fields(["capital_rank", "final_role", "d1_return"])


def test_role_row_separates_asof_roles_from_realized_labels() -> None:
    row = CapitalRoleRow(
        market_cycle_id="market-1",
        concept_cycle_id="concept-1",
        trade_date=date(2026, 7, 20),
        vt_symbol="600001.SSE",
        sector_id="BK0001",
        role_asof=(CapitalRole.IGNITION_CANDIDATE,),
        role_realized=(CapitalRole.CONFIRMED_IGNITION_LEADER,),
        membership_evidence_level=EvidenceLevel.POINT_IN_TIME,
        asof_features={"capital_rank": 1},
        realized_labels={"d1_return": 4.2},
    )

    assert row.as_dict()["role_asof"] == ["ignition_candidate"]
    assert row.as_dict()["role_realized"] == ["confirmed_ignition_leader"]


def test_missing_fund_flow_is_not_treated_as_zero_or_negative() -> None:
    assert capital_evidence_level(
        has_real_flow=False,
        flow_known_before_decision=False,
        has_turnover_proxy=True,
    ) is EvidenceLevel.TURNOVER_PROXY
    assert capital_evidence_level(
        has_real_flow=False,
        flow_known_before_decision=False,
        has_turnover_proxy=False,
    ) is EvidenceLevel.UNAVAILABLE
