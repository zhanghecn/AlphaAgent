from __future__ import annotations

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.reason_relations import (
    build_normalized_reason_relations,
    normalize_reason_name,
)


def _events(reason: str = "PCB概念") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": 1,
                "source_date": pd.Timestamp("2025-07-03"),
                "vt_symbol": "002636.SZSE",
                "stock_name": "金安国纪",
                "reason": reason,
            }
        ]
    )


def _concepts() -> pd.DataFrame:
    return pd.DataFrame([{"sector_id": "BK0877", "concept_name": "PCB"}])


def test_normalize_reason_name_removes_one_auditable_suffix() -> None:
    assert normalize_reason_name(" PCB 概念 ") == "pcb"
    assert normalize_reason_name("机器人龙头") == "机器人"
    assert normalize_reason_name("光伏板块") == "光伏"


def test_reason_suffix_normalization_maps_pcb_concept_to_pcb() -> None:
    rows = build_normalized_reason_relations(_events("覆铜板+PCB概念"), _concepts())

    assert len(rows) == 1
    assert rows.loc[0, "reason_token"] == "PCB概念"
    assert rows.loc[0, "concept_name"] == "PCB"
    assert rows.loc[0, "relation_method"] == "normalized_suffix_exact"


def test_exact_relation_takes_precedence() -> None:
    rows = build_normalized_reason_relations(_events("PCB+PCB概念"), _concepts())

    assert len(rows) == 1
    assert rows.loc[0, "reason_token"] == "PCB"
    assert rows.loc[0, "relation_method"] == "exact"


def test_reason_normalization_does_not_invent_semantic_aliases() -> None:
    rows = build_normalized_reason_relations(_events("覆铜板"), _concepts())

    assert rows.empty


def test_ambiguous_normalized_concept_name_is_rejected() -> None:
    concepts = pd.DataFrame(
        [
            {"sector_id": "A", "concept_name": "机器人"},
            {"sector_id": "B", "concept_name": "机器人概念"},
        ]
    )

    with pytest.raises(ValueError, match="ambiguous normalized concept"):
        build_normalized_reason_relations(_events("机器人"), concepts)


def test_relation_is_deterministic_under_input_shuffle() -> None:
    events = pd.concat(
        [
            _events("PCB概念").assign(event_id=2),
            _events("PCB").assign(event_id=1),
        ],
        ignore_index=True,
    )
    baseline = build_normalized_reason_relations(events, _concepts())
    shuffled = build_normalized_reason_relations(
        events.sample(frac=1, random_state=9),
        _concepts(),
    )

    pd.testing.assert_frame_equal(baseline, shuffled)
