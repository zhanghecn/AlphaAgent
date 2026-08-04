from __future__ import annotations

from alphaagent.server.services.low_suction.swing_research_service import (
    get_swing_research,
)


def test_swing_research_fails_closed_after_historical_archive_retirement() -> None:
    research = get_swing_research()

    assert research["research_status"] == "historical_evidence_retired"
    assert research["formal_strategy"] is False
    assert research["formal_metrics"] is None
    assert research["historical_proxy_available"] is False
