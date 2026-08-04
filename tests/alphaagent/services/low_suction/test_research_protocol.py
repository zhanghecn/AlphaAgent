from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
import json

import pandas as pd
import pytest

from alphaagent.server.services.low_suction import research_protocol
from alphaagent.server.services.low_suction.research_protocol import (
    HoldoutAccessError,
    HoldoutLock,
    RegimePerformance,
    ResearchStage,
    build_protocol_split,
    default_protocol,
    evaluate_regime_adaptation,
    fingerprint_frame,
    protocol_hash,
)


def _dates(count: int) -> list[date]:
    start = date(2025, 1, 1)
    return [start + timedelta(days=index) for index in range(count)]


def test_outer_holdout_is_not_returned_to_discovery_stage() -> None:
    split = build_protocol_split(_dates(100), default_protocol())

    assert len(split.discovery_dates) == 80
    assert len(split.holdout_dates) == 20
    assert set(split.discovery_dates).isdisjoint(split.holdout_dates)
    assert all(
        set(fold.train_dates).isdisjoint(split.holdout_dates)
        and set(fold.validation_dates).isdisjoint(split.holdout_dates)
        for fold in split.rolling_folds
    )


def test_protocol_split_sorts_unique_dates_and_applies_embargo() -> None:
    values = [*_dates(100), _dates(100)[5], _dates(100)[1]]
    split = build_protocol_split(reversed(values), default_protocol())

    assert split.discovery_dates == tuple(_dates(80))
    assert len(split.rolling_folds) == 5
    for fold in split.rolling_folds:
        validation_start = split.discovery_dates.index(fold.validation_dates[0])
        training_end = split.discovery_dates.index(fold.train_dates[-1]) + 1
        assert validation_start - training_end == 5


def test_protocol_split_rejects_short_history() -> None:
    with pytest.raises(ValueError, match="at least 100 unique dates"):
        build_protocol_split(_dates(99), default_protocol())


def test_data_fingerprint_is_stable_across_order_and_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2026-07-15", "2026-07-14"]),
            "sector_id": ["BK0002", "BK0001"],
            "close_price": [102.0, 100.0],
        }
    )

    monkeypatch.setattr(research_protocol, "FINGERPRINT_CHUNK_ROWS", 1)
    chunked = fingerprint_frame(
        frame,
        identity_columns=("trade_date", "sector_id"),
    )
    monkeypatch.setattr(research_protocol, "FINGERPRINT_CHUNK_ROWS", 100)
    reordered = fingerprint_frame(
        frame.iloc[::-1],
        identity_columns=("trade_date", "sector_id"),
    )
    changed = fingerprint_frame(
        frame.assign(close_price=[102.0, 100.1]),
        identity_columns=("trade_date", "sector_id"),
    )

    assert chunked == reordered
    assert chunked.digest == (
        "sha256:ea7bf685d9895e7807ec03b9e2d35d5822b0c6a103f8841a6a0ec749166d0943"
    )
    assert chunked.digest != changed.digest
    assert chunked.rows == 2


def test_data_fingerprint_rejects_duplicate_identity() -> None:
    frame = pd.DataFrame({"trade_date": ["2026-07-15"] * 2, "value": [1, 2]})

    with pytest.raises(ValueError, match="identity columns must be unique"):
        fingerprint_frame(frame, identity_columns=("trade_date",))


def test_protocol_hash_changes_when_protocol_changes() -> None:
    protocol = default_protocol()

    assert protocol_hash(protocol) == protocol_hash(protocol)
    assert protocol_hash(protocol) != protocol_hash(
        replace(protocol, slippage_bps=20.0)
    )
    assert protocol_hash(protocol) != protocol_hash(
        replace(protocol, cycle_contract_version="different-cycle-contract")
    )


def test_holdout_requires_one_frozen_pipeline_hash() -> None:
    lock = HoldoutLock.create("sha256:pipeline-a")
    lock.authorize("sha256:pipeline-a")

    with pytest.raises(HoldoutAccessError, match="frozen pipeline hash"):
        lock.authorize("sha256:pipeline-b")


def test_persisted_holdout_lock_cannot_be_reset_by_process_restart(tmp_path) -> None:
    path = tmp_path / "holdout-lock.json"
    lock = HoldoutLock.create("sha256:pipeline-a", state_path=path)
    lock.authorize("sha256:pipeline-a")

    restored = HoldoutLock.load(path)
    with pytest.raises(HoldoutAccessError, match="already been evaluated"):
        restored.authorize("sha256:pipeline-a")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["frozen_pipeline_hash"] == "sha256:pipeline-a"
    assert payload["access_count"] == 1


def test_protocol_exposes_only_registered_research_stages() -> None:
    assert tuple(stage.value for stage in ResearchStage) == (
        "coverage",
        "cycle_selection",
        "leader_selection",
        "state_discovery",
        "pipeline_validation",
        "locked_holdout",
    )

def test_regime_adaptation_requires_two_profitable_traded_environments() -> None:
    decision = evaluate_regime_adaptation(
        (
            RegimePerformance("GOLD/NORMAL", 80, "trade", 60, 66.0, 35.0, -5.0, 0.55),
            RegimePerformance("SILVER/NORMAL", 40, "trade", 35, 62.0, 8.0, -6.0, 0.45),
            RegimePerformance("SILVER/DANGER", 30, "cash", 0, None, 0.0, 0.0, 0.0),
        ),
        default_protocol(),
    )

    assert decision.qualified is True
    assert decision.failed_gates == ()


def test_regime_adaptation_rejects_threshold_equality_and_one_regime_only() -> None:
    decision = evaluate_regime_adaptation(
        (
            RegimePerformance("GOLD/NORMAL", 80, "trade", 60, 60.0, 35.0, -5.0, 1.0),
            RegimePerformance("SILVER/NORMAL", 40, "cash", 0, None, 0.0, 0.0, 0.0),
        ),
        default_protocol(),
    )

    assert decision.qualified is False
    assert "GOLD/NORMAL:win_rate" in decision.failed_gates
    assert "traded_regimes" in decision.failed_gates
