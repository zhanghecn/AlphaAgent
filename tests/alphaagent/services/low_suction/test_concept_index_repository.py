from __future__ import annotations

from datetime import date

from alphaagent.server.services.low_suction.concept_index_coverage import (
    CANONICAL_CONCEPT_INDEX_SOURCE,
)
from alphaagent.server.services.low_suction.data_quality_repository import (
    _concept_daily_coverage,
)
from alphaagent.server.services.low_suction.repository import (
    _complete_concept_dates,
    _concept_bars_query,
)


class _FakeResult:
    def __init__(self, rows=(), *, scalar=None, one=None) -> None:
        self._rows = rows
        self._scalar = scalar
        self._one = one

    def all(self):
        return self._rows

    def scalar_one(self):
        return self._scalar

    def one(self):
        return self._one


class _ConceptCoverageSession:
    def __init__(
        self,
        *,
        count_rows,
        bounds,
        concept_count: int,
        aggregate=(0, 0),
    ) -> None:
        self.count_rows = count_rows
        self.bounds = bounds
        self.concept_count = concept_count
        self.aggregate = aggregate
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        sql = str(statement)
        if "min(sector_daily_bars.trade_date)" in sql:
            return _FakeResult(self.bounds)
        if "GROUP BY sector_daily_bars.trade_date" in sql:
            return _FakeResult(self.count_rows)
        if "SELECT DISTINCT sector_daily_bars.source" in sql:
            return _FakeResult(((CANONICAL_CONCEPT_INDEX_SOURCE,),))
        if "FROM sectors" in sql and "sector_daily_bars" not in sql:
            return _FakeResult(scalar=self.concept_count)
        if "count(distinct(sector_daily_bars.sector_id))" in sql:
            return _FakeResult(one=self.aggregate)
        raise AssertionError(f"unexpected statement: {sql}")


def _bounds(
    count: int,
    first_date: date,
    last_date: date,
) -> list[tuple[str, date, date]]:
    return [
        (f"BK{index:04d}", first_date, last_date)
        for index in range(count)
    ]


def _assert_canonical_bar_queries(statements) -> None:
    bar_statements = [
        statement
        for statement in statements
        if "sector_daily_bars" in str(statement)
    ]
    assert bar_statements
    for statement in bar_statements:
        assert CANONICAL_CONCEPT_INDEX_SOURCE in statement.compile().params.values()


def _assert_bar_queries_capped_at(statements, as_of_date: date) -> None:
    bar_statements = [
        statement
        for statement in statements
        if "sector_daily_bars" in str(statement)
    ]
    assert bar_statements
    for statement in bar_statements:
        assert as_of_date in statement.compile().params.values()


def test_audit_uses_dynamic_denominator_for_all_observed_index_dates() -> None:
    first = date(2026, 7, 14)
    second = date(2026, 7, 15)
    bounds = [*_bounds(300, first, second), ("BK_NEW", second, second)]
    session = _ConceptCoverageSession(
        count_rows=((first, 300), (second, 300)),
        bounds=bounds,
        concept_count=301,
        aggregate=(600, 301),
    )

    coverage, inventory = _concept_daily_coverage(
        session,
        as_of_date=second,
    )

    assert coverage.trade_days == 2
    assert coverage.end == second
    assert coverage.coverage_pct == 99.6678
    assert coverage.sources == (CANONICAL_CONCEPT_INDEX_SOURCE,)
    assert inventory["indexed_concept_count"] == 301
    assert inventory["minimum_expected_active_concepts"] == 300
    assert inventory["maximum_expected_active_concepts"] == 301
    _assert_canonical_bar_queries(session.statements)
    _assert_bar_queries_capped_at(session.statements, second)


def test_proxy_dates_intersect_dynamic_index_coverage_with_reliable_stocks() -> None:
    first = date(2026, 7, 13)
    second = date(2026, 7, 14)
    third = date(2026, 7, 15)
    bounds = [
        *_bounds(299, first, third),
        ("BK0299", second, third),
    ]
    session = _ConceptCoverageSession(
        count_rows=((first, 299), (second, 269), (third, 270)),
        bounds=bounds,
        concept_count=300,
    )

    dates, inventory = _complete_concept_dates(
        session,
        reliable_stock_dates=(first, second, third),
    )

    assert dates == (third,)
    assert inventory["complete_concept_trade_days"] == 1
    assert inventory["minimum_complete_cross_section_pct"] == 90.0
    _assert_canonical_bar_queries(session.statements)


def test_proxy_concept_bar_query_accepts_only_canonical_index_rows() -> None:
    statement = _concept_bars_query(
        date(2026, 7, 1),
        date(2026, 7, 15),
    )

    assert CANONICAL_CONCEPT_INDEX_SOURCE in statement.compile().params.values()
