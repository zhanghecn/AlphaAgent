from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from alphaagent.server.services.low_suction.contracts import (
    CoverageSnapshot,
    DatasetCoverage,
    PairCoverage,
)
from alphaagent.server.services.low_suction.data_quality import (
    evaluate_data_quality,
    evaluate_qualification,
)
from alphaagent.server.services.low_suction.data_quality_repository import (
    _build_forward_membership_provider_inventory,
    _build_forward_security_provider_inventory,
    _build_security_status_coverage,
    _forward_membership_provider_inventory,
    _select_concept_membership_coverage,
    effective_forward_trade_date,
    effective_membership_date,
)
from alphaagent.server.services.low_suction.theme_reference_cohorts import (
    MANIFEST_VERSION,
)


def _dataset(
    *,
    start: date = date(2023, 1, 3),
    end: date = date(2026, 1, 5),
    trade_days: int = 730,
    coverage_pct: float = 100.0,
    mode: str = "strict",
) -> DatasetCoverage:
    return DatasetCoverage(
        rows=1_000,
        entities=100,
        trade_days=trade_days,
        start=start,
        end=end,
        coverage_pct=coverage_pct,
        mode=mode,
        sources=("fixture",),
    )


def _coverage(**overrides: object) -> CoverageSnapshot:
    values: dict[str, object] = {
        "as_of_date": date(2026, 1, 5),
        "stock_daily": _dataset(),
        "concept_daily": _dataset(),
        "concept_membership": _dataset(),
        "security_status": _dataset(),
        "candidate_minutes": PairCoverage(total_pairs=350, covered_pairs=350),
        "market_timing": _dataset(start=date(2024, 1, 2), trade_days=500),
    }
    values.update(overrides)
    return CoverageSnapshot(**values)


def test_strict_metrics_are_null_when_membership_is_proxy() -> None:
    snapshot = _coverage(
        concept_membership=_dataset(mode="current_proxy"),
    )

    report = evaluate_data_quality(snapshot).as_dict()

    assert report["status"] == "blocked_by_data_quality"
    assert report["strict_ready"] is False
    assert report["formal_metrics"] is None
    assert "historical_concept_membership" in report["blocking_gaps"]


def _membership_provider(
    *,
    source: str = "tushare.dc_member.lag1",
    evidence_level: str = "strict",
    trade_days: int = 799,
    required_pairs: int = 390_000,
    complete_pairs: int = 390_000,
) -> dict[str, object]:
    return {
        "source": source,
        "evidence_level": evidence_level,
        "trade_days": trade_days,
        "start": date(2023, 3, 28),
        "end": date(2026, 7, 15),
        "required_pairs": required_pairs,
        "complete_pairs": complete_pairs,
        "membership_rows": 28_000_000,
        "entities": 5_600,
        "sectors": 498,
        "minimum_daily_coverage_pct": (
            100.0 if required_pairs == complete_pairs else 50.0
        ),
    }


def test_strict_membership_provider_wins_without_mixing_proxy_rows() -> None:
    proxy = _dataset(
        start=date(2026, 7, 14),
        end=date(2026, 7, 15),
        trade_days=2,
        mode="current_proxy",
    )
    coverage, inventory = _select_concept_membership_coverage(
        [_membership_provider()],
        proxy_coverage=proxy,
        proxy_inventory={"mode": "current_proxy", "raw_snapshot_trade_days": 3},
    )

    assert coverage.mode == "strict"
    assert coverage.sources == ("tushare.dc_member.lag1",)
    assert coverage.trade_days == 799
    assert coverage.rows == 28_000_000
    assert inventory["selected_source"] == "tushare.dc_member.lag1"
    assert inventory["proxy"]["raw_snapshot_trade_days"] == 3


def test_incomplete_or_reconstructed_membership_provider_keeps_proxy_active() -> None:
    proxy = _dataset(
        start=date(2026, 7, 14),
        end=date(2026, 7, 15),
        trade_days=2,
        mode="current_proxy",
    )
    providers = [
        _membership_provider(complete_pairs=389_999),
        _membership_provider(
            source="reconstructed.members",
            evidence_level="reconstructed",
        ),
    ]

    coverage, inventory = _select_concept_membership_coverage(
        providers,
        proxy_coverage=proxy,
        proxy_inventory={"mode": "current_proxy"},
    )

    assert coverage.mode == "current_proxy"
    assert inventory["selected_source"] is None
    assert len(inventory["providers"]) == 2


def test_strict_readiness_requires_historical_security_status() -> None:
    snapshot = _coverage(
        security_status=_dataset(
            start=None,
            end=None,
            trade_days=0,
            coverage_pct=0.0,
            mode="unavailable",
        ),
    )

    report = evaluate_data_quality(snapshot)

    assert report.strict_ready is False
    assert "historical_security_status" in report.blocking_gaps


def _security_provider_inventory(
    *,
    evidence_level: str,
    source: str,
    coverage_pct: float = 100.0,
) -> dict[str, object]:
    return {
        "evidence_level": evidence_level,
        "source": source,
        "required_pairs": 73_000,
        "covered_pairs": int(73_000 * coverage_pct / 100.0),
        "entities": 3_500,
        "trade_days": 730,
        "start": date(2023, 1, 3),
        "end": date(2026, 1, 5),
        "status_rows": 73_000,
        "risk_warning_rows": 2_000,
        "suspended_rows": 300,
        "delisted_symbols": 291,
    }


def test_reconstructed_security_coverage_never_opens_strict_gate() -> None:
    coverage, inventory = _build_security_status_coverage(
        [
            _security_provider_inventory(
                evidence_level="reconstructed",
                source="baostock.query_history_k_data_plus",
            )
        ]
    )

    report = evaluate_data_quality(_coverage(security_status=coverage))

    assert coverage.mode == "reconstructed"
    assert coverage.trade_days == 730
    assert coverage.coverage_pct == 100.0
    assert inventory["selected_source"] == "baostock.query_history_k_data_plus"
    assert inventory["providers"][0]["delisted_symbols"] == 291
    assert report.strict_ready is False
    assert report.formal_metrics is None
    assert "historical_security_status" in report.blocking_gaps


def test_strict_security_provider_is_selected_without_mixing_sources() -> None:
    reconstructed = _security_provider_inventory(
        evidence_level="reconstructed",
        source="baostock.query_history_k_data_plus",
    )
    strict = _security_provider_inventory(
        evidence_level="strict",
        source="licensed.point_in_time",
        coverage_pct=95.0,
    )

    coverage, inventory = _build_security_status_coverage(
        [reconstructed, strict]
    )

    assert coverage.mode == "strict"
    assert coverage.sources == ("licensed.point_in_time",)
    assert coverage.coverage_pct == 95.0
    assert inventory["selected_source"] == "licensed.point_in_time"
    assert len(inventory["providers"]) == 2


def test_strict_readiness_requires_three_calendar_years() -> None:
    short_span = _dataset(
        start=date(2024, 1, 2),
        end=date(2026, 1, 5),
        trade_days=730,
    )

    report = evaluate_data_quality(_coverage(stock_daily=short_span))

    assert report.strict_ready is False
    assert "stock_daily_history" in report.blocking_gaps


def test_strict_readiness_requires_candidate_minute_assessment() -> None:
    report = evaluate_data_quality(
        _coverage(candidate_minutes=PairCoverage(total_pairs=0, covered_pairs=0))
    )

    assert report.strict_ready is False
    assert "candidate_minute_paths" in report.blocking_gaps


def test_strict_readiness_requires_all_candidate_minutes() -> None:
    report = evaluate_data_quality(
        _coverage(candidate_minutes=PairCoverage(total_pairs=350, covered_pairs=349))
    )

    assert report.strict_ready is False
    assert "candidate_minute_paths" in report.blocking_gaps


def test_complete_strict_snapshot_is_ready() -> None:
    report = evaluate_data_quality(_coverage())

    assert report.status == "ready_for_strict_research"
    assert report.strict_ready is True
    assert report.evidence_level == "strict"
    assert report.blocking_gaps == ()


def test_coverage_contract_is_immutable() -> None:
    snapshot = _coverage()

    with pytest.raises(FrozenInstanceError):
        snapshot.as_of_date = date(2026, 1, 6)  # type: ignore[misc]


def test_zero_closed_trades_never_passes_drawdown_gate() -> None:
    decision = evaluate_qualification(
        closed_trades=0,
        win_rate_pct=0.0,
        compounded_return_pct=0.0,
        profit_factor=None,
        maximum_drawdown_pct=0.0,
        double_cost_return_pct=0.0,
    )

    assert decision.status == "insufficient_sample"
    assert decision.qualified is False


def test_qualification_rejects_drawdown_below_negative_ten_percent() -> None:
    decision = evaluate_qualification(
        closed_trades=300,
        win_rate_pct=61.0,
        compounded_return_pct=61.0,
        profit_factor=1.2,
        maximum_drawdown_pct=-10.01,
        double_cost_return_pct=3.0,
    )

    assert decision.status == "no_qualified_strategy"
    assert "maximum_drawdown" in decision.failed_gates


def test_qualification_accepts_only_complete_positive_strict_result() -> None:
    decision = evaluate_qualification(
        closed_trades=320,
        win_rate_pct=61.0,
        compounded_return_pct=61.0,
        profit_factor=1.2,
        maximum_drawdown_pct=-9.8,
        double_cost_return_pct=3.0,
    )

    assert decision.status == "qualified_research_rule"
    assert decision.qualified is True
    assert decision.failed_gates == ()


def test_qualification_is_blocked_when_inputs_are_not_strict() -> None:
    decision = evaluate_qualification(
        closed_trades=320,
        win_rate_pct=61.0,
        compounded_return_pct=61.0,
        profit_factor=1.2,
        maximum_drawdown_pct=-9.8,
        double_cost_return_pct=3.0,
        strict_data_ready=False,
    )

    assert decision.status == "blocked_by_data_quality"
    assert decision.qualified is False
    assert decision.failed_gates == ("strict_data_quality",)


def test_qualification_requires_win_rate_and_compounding_above_sixty() -> None:
    decision = evaluate_qualification(
        closed_trades=320,
        win_rate_pct=60.0,
        compounded_return_pct=60.0,
        profit_factor=2.0,
        maximum_drawdown_pct=-5.0,
        double_cost_return_pct=5.0,
    )

    assert decision.qualified is False
    assert "win_rate" in decision.failed_gates
    assert "compounded_return" in decision.failed_gates


def test_dataset_replace_helper_keeps_fixture_explicit() -> None:
    original = _dataset()
    proxy = replace(original, mode="current_proxy")

    assert original.mode == "strict"
    assert proxy.mode == "current_proxy"


def test_repository_never_uses_current_members_as_strict_history() -> None:
    source = Path(
        "alphaagent/server/services/low_suction/data_quality_repository.py"
    ).read_text()

    assert "stock_sector_membership_snapshots" in source
    assert ".c.type.in_(CONCEPT_SECTOR_TYPES)" in source
    assert ".c.sector_type.in_(CONCEPT_SECTOR_TYPES)" in source
    assert "_market_timing_coverage(session, as_of_date)" in source
    assert "_supporting_coverage(session, as_of_date)" in source
    assert "parsed <= as_of_date" in source
    assert "cast(date_column, SqlDate) <= as_of_date" in source
    assert '"current_proxy"' in source
    assert "services.limit_up" not in source
    assert "services.quant" not in source


def test_evening_membership_snapshot_is_effective_next_session() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")
    effective = effective_membership_date(
        snapshot_date=date(2026, 7, 13),
        captured_at=datetime(2026, 7, 13, 19, 15, tzinfo=shanghai),
        trading_dates=(date(2026, 7, 13), date(2026, 7, 14), date(2026, 7, 15)),
    )

    assert effective == date(2026, 7, 14)


def test_preopen_membership_snapshot_can_be_effective_same_session() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")
    effective = effective_membership_date(
        snapshot_date=date(2026, 7, 13),
        captured_at=datetime(2026, 7, 13, 9, 20, tzinfo=shanghai),
        trading_dates=(date(2026, 7, 13), date(2026, 7, 14)),
    )

    assert effective == date(2026, 7, 13)


def test_evening_snapshot_without_next_session_is_not_effective() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")
    effective = effective_membership_date(
        snapshot_date=date(2026, 7, 15),
        captured_at=datetime(2026, 7, 15, 19, 7, tzinfo=shanghai),
        trading_dates=(date(2026, 7, 14), date(2026, 7, 15)),
    )

    assert effective is None


def test_forward_capture_maps_friday_to_next_reliable_monday() -> None:
    effective = effective_forward_trade_date(
        source_trade_date=date(2026, 7, 17),
        observed_at=datetime(
            2026,
            7,
            17,
            19,
            5,
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ),
        trading_dates=(date(2026, 7, 17), date(2026, 7, 20)),
    )

    assert effective == date(2026, 7, 20)


@pytest.mark.parametrize(
    "source_trade_date, observed_at, trading_dates",
    [
        (
            date(2026, 7, 16),
            datetime(2026, 7, 16, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            (date(2026, 7, 15), date(2026, 7, 17)),
        ),
        (
            date(2026, 7, 16),
            datetime(2026, 7, 17, 9, 26, tzinfo=ZoneInfo("Asia/Shanghai")),
            (date(2026, 7, 16), date(2026, 7, 17)),
        ),
        (
            date(2026, 7, 16),
            datetime(2026, 7, 16, 14, 59, tzinfo=ZoneInfo("Asia/Shanghai")),
            (date(2026, 7, 16), date(2026, 7, 17)),
        ),
        (
            date(2026, 7, 16),
            datetime(2026, 7, 16, 19, 0),
            (date(2026, 7, 16), date(2026, 7, 17)),
        ),
    ],
)
def test_forward_capture_rejects_non_causal_effective_dates(
    source_trade_date: date,
    observed_at: datetime,
    trading_dates: tuple[date, ...],
) -> None:
    assert (
        effective_forward_trade_date(
            source_trade_date=source_trade_date,
            observed_at=observed_at,
            trading_dates=trading_dates,
        )
        is None
    )


def _forward_membership_row(
    *,
    source: str = "eastmoney.push2.board",
    source_trade_date: date = date(2026, 7, 16),
    observed_at: datetime | None = None,
    complete: bool = True,
    expected_sector_count: int = 320,
    returned_sector_count: int = 320,
    declared_row_count: int = 80_000,
    actual_row_count: int = 80_000,
    manifest_version: str = MANIFEST_VERSION,
) -> dict[str, object]:
    return {
        "source": source,
        "evidence_level": "strict",
        "source_trade_date": source_trade_date,
        "observed_at": observed_at
        or datetime(2026, 7, 16, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        "minimum_observed_at": observed_at
        or datetime(2026, 7, 16, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        "maximum_observed_at": observed_at
        or datetime(2026, 7, 16, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        "complete": complete,
        "expected_sector_count": expected_sector_count,
        "returned_sector_count": returned_sector_count,
        "declared_row_count": declared_row_count,
        "actual_row_count": actual_row_count,
        "declared_symbol_count": 3_192,
        "actual_symbol_count": 3_192,
        "actual_sector_count": returned_sector_count,
        "manifest_version": manifest_version,
    }


def _forward_security_row(
    *,
    source: str = "baostock.query_all_stock.forward",
    source_trade_date: date = date(2026, 7, 16),
    observed_at: datetime | None = None,
    complete: bool = True,
    expected_symbol_count: int = 3_192,
    returned_symbol_count: int = 3_192,
    actual_row_count: int = 3_192,
) -> dict[str, object]:
    return {
        "source": source,
        "evidence_level": "strict",
        "source_trade_date": source_trade_date,
        "observed_at": observed_at
        or datetime(2026, 7, 16, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        "minimum_observed_at": observed_at
        or datetime(2026, 7, 16, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        "maximum_observed_at": observed_at
        or datetime(2026, 7, 16, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        "complete": complete,
        "expected_symbol_count": expected_symbol_count,
        "returned_symbol_count": returned_symbol_count,
        "actual_row_count": actual_row_count,
        "actual_symbol_count": actual_row_count,
        "risk_warning_count": 120,
        "actual_risk_warning_count": 120,
        "suspended_count": 30,
        "actual_suspended_count": 30,
        "delisted_symbols": 1,
    }


def test_forward_membership_inventory_keeps_providers_isolated() -> None:
    providers = _build_forward_membership_provider_inventory(
        [
            _forward_membership_row(),
            _forward_membership_row(source="another.forward.provider"),
        ],
        reliable_stock_dates=(date(2026, 7, 16), date(2026, 7, 17)),
    )

    assert len(providers) == 2
    assert {provider["source"] for provider in providers} == {
        "eastmoney.push2.board",
        "another.forward.provider",
    }
    assert all(provider["trade_days"] == 1 for provider in providers)
    assert all(provider["start"] == date(2026, 7, 17) for provider in providers)
    assert all(provider["required_pairs"] == 320 for provider in providers)
    assert all(provider["complete_pairs"] == 320 for provider in providers)


@pytest.mark.parametrize(
    "row",
    [
        _forward_membership_row(complete=False),
        _forward_membership_row(returned_sector_count=319),
        _forward_membership_row(actual_row_count=79_999),
        _forward_membership_row(expected_sector_count=299, returned_sector_count=299),
        _forward_membership_row(
            observed_at=datetime(
                2026,
                7,
                17,
                9,
                26,
                tzinfo=ZoneInfo("Asia/Shanghai"),
            )
        ),
    ],
)
def test_incomplete_forward_membership_capture_never_qualifies(
    row: dict[str, object],
) -> None:
    providers = _build_forward_membership_provider_inventory(
        [row],
        reliable_stock_dates=(date(2026, 7, 16), date(2026, 7, 17)),
    )

    assert providers[0]["trade_days"] == 0
    assert providers[0]["complete_pairs"] == 0
    assert providers[0]["status"] == "invalid_capture"


def test_forward_membership_requires_the_current_manifest_version() -> None:
    providers = _build_forward_membership_provider_inventory(
        [_forward_membership_row(manifest_version="stale-manifest")],
        reliable_stock_dates=(date(2026, 7, 16), date(2026, 7, 17)),
    )

    assert providers[0]["trade_days"] == 0
    assert providers[0]["complete_pairs"] == 0
    assert providers[0]["status"] == "invalid_capture"


def test_forward_membership_query_uses_the_dedicated_table_columns() -> None:
    class EmptyResult:
        def mappings(self):
            return self

        def all(self):
            return []

    class FakeSession:
        def execute(self, statement):
            assert "low_suction_forward_membership_snapshots" in str(statement)
            assert "low_suction_forward_membership_snapshot_scopes" in str(statement)
            return EmptyResult()

    assert _forward_membership_provider_inventory(
        FakeSession(),
        reliable_stock_dates=(date(2026, 7, 16), date(2026, 7, 17)),
    ) == []


def test_forward_security_inventory_maps_only_complete_scope_to_d1() -> None:
    providers = _build_forward_security_provider_inventory(
        [_forward_security_row()],
        reliable_stock_dates=(date(2026, 7, 16), date(2026, 7, 17)),
    )

    assert providers == [
        {
            "evidence_level": "strict",
            "source": "baostock.query_all_stock.forward",
            "status": "accumulating",
            "required_pairs": 3_192,
            "covered_pairs": 3_192,
            "entities": 3_192,
            "trade_days": 1,
            "source_trade_days": 1,
            "start": date(2026, 7, 17),
            "end": date(2026, 7, 17),
            "status_rows": 3_192,
            "risk_warning_rows": 120,
            "suspended_rows": 30,
            "delisted_symbols": 1,
            "rejected_captures": 0,
        }
    ]


def test_incomplete_forward_security_capture_never_qualifies() -> None:
    providers = _build_forward_security_provider_inventory(
        [
            _forward_security_row(
                expected_symbol_count=3_192,
                returned_symbol_count=3_191,
            )
        ],
        reliable_stock_dates=(date(2026, 7, 16), date(2026, 7, 17)),
    )

    assert providers[0]["trade_days"] == 0
    assert providers[0]["status"] == "invalid_capture"


def test_short_forward_providers_remain_accumulating_and_keep_gates_closed() -> None:
    proxy = _dataset(
        start=date(2026, 7, 17),
        end=date(2026, 7, 17),
        trade_days=1,
        mode="current_proxy",
    )
    membership_provider = _build_forward_membership_provider_inventory(
        [_forward_membership_row()],
        reliable_stock_dates=(date(2026, 7, 16), date(2026, 7, 17)),
    )
    membership, membership_inventory = _select_concept_membership_coverage(
        membership_provider,
        proxy_coverage=proxy,
        proxy_inventory={"mode": "current_proxy"},
    )
    security_provider = _build_forward_security_provider_inventory(
        [_forward_security_row()],
        reliable_stock_dates=(date(2026, 7, 16), date(2026, 7, 17)),
    )
    security, security_inventory = _build_security_status_coverage(
        security_provider
    )

    report = evaluate_data_quality(
        _coverage(concept_membership=membership, security_status=security)
    ).as_dict()

    assert membership.mode == "current_proxy"
    assert membership_inventory["providers"][0]["status"] == "accumulating"
    assert security.mode == "unavailable"
    assert security_inventory["providers"][0]["status"] == "accumulating"
    assert report["strict_ready"] is False
    assert report["formal_metrics"] is None
    assert "historical_concept_membership" in report["blocking_gaps"]
    assert "historical_security_status" in report["blocking_gaps"]
