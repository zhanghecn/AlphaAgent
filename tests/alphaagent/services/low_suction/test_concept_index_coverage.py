from __future__ import annotations

from datetime import date

import pytest

from alphaagent.server.services.low_suction.concept_index_coverage import (
    build_dynamic_concept_coverage,
)


def _bounds(
    count: int,
    first_date: date,
    last_date: date,
) -> list[tuple[str, date, date]]:
    return [
        (f"BK{index:04d}", first_date, last_date)
        for index in range(count)
    ]


def test_new_concept_counts_only_from_its_first_index_date() -> None:
    first = date(2026, 7, 13)
    second = date(2026, 7, 14)
    third = date(2026, 7, 15)
    bounds = [*_bounds(300, first, third), ("BK_NEW", third, third)]

    coverage = build_dynamic_concept_coverage(
        trading_dates=(third, first, second),
        count_rows=((first, 300), (second, 300), (third, 301)),
        bounds=bounds,
    )

    assert [row.trade_date for row in coverage] == [first, second, third]
    assert [row.expected_active_concepts for row in coverage] == [300, 300, 301]
    assert [row.coverage_pct for row in coverage] == [100.0, 100.0, 100.0]
    assert all(row.qualifies for row in coverage)


def test_dynamic_coverage_enforces_cross_section_and_minimum_active_gates() -> None:
    first = date(2026, 7, 13)
    second = date(2026, 7, 14)
    third = date(2026, 7, 15)
    bounds = [
        *_bounds(299, first, third),
        ("BK0299", second, third),
    ]

    coverage = build_dynamic_concept_coverage(
        trading_dates=(first, second, third),
        count_rows=((first, 299), (second, 269), (third, 270)),
        bounds=bounds,
    )

    assert coverage[0].coverage_pct == 100.0
    assert coverage[0].qualifies is False
    assert coverage[1].coverage_pct == pytest.approx(89.6667)
    assert coverage[1].qualifies is False
    assert coverage[2].coverage_pct == 90.0
    assert coverage[2].qualifies is True


def test_dynamic_coverage_rejects_duplicate_daily_counts() -> None:
    trade_date = date(2026, 7, 15)

    with pytest.raises(ValueError, match="duplicate count row"):
        build_dynamic_concept_coverage(
            trading_dates=(trade_date,),
            count_rows=((trade_date, 300), (trade_date, 300)),
            bounds=_bounds(300, trade_date, trade_date),
        )


def test_dynamic_coverage_rejects_duplicate_concept_bounds() -> None:
    trade_date = date(2026, 7, 15)

    with pytest.raises(ValueError, match="duplicate concept bound"):
        build_dynamic_concept_coverage(
            trading_dates=(trade_date,),
            count_rows=((trade_date, 1),),
            bounds=(
                ("BK0001", trade_date, trade_date),
                ("BK0001", trade_date, trade_date),
            ),
            minimum_active_concepts=1,
        )


def test_dynamic_coverage_rejects_actual_count_above_expected() -> None:
    trade_date = date(2026, 7, 15)

    with pytest.raises(ValueError, match="actual concept count exceeds expected"):
        build_dynamic_concept_coverage(
            trading_dates=(trade_date,),
            count_rows=((trade_date, 301),),
            bounds=_bounds(300, trade_date, trade_date),
        )
