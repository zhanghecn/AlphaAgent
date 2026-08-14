"""Focused checks for the fixed top-five-per-family daily portfolio."""

from dataclasses import replace
from datetime import date, timedelta

from alphaagent.server.services.low_suction.daily_factor_extended_discovery import (
    FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
    STAGED_MA10_SUPPORT_RULE_KEY,
)
from alphaagent.server.services.low_suction.daily_picks_backtest import (
    ALLOCATION_PER_PICK_PCT,
    BACKTEST_VERSION,
    MAX_POSITIONS,
    PICKS_PER_FAMILY,
    build_backtest_payload,
)
from alphaagent.server.services.low_suction.daily_picks_scanner import (
    LowSuctionCandidate,
    candidate_ranking_key,
)
from alphaagent.server.services.low_suction.daily_picks_scoring import (
    SCORE_VERSION,
    QuietStreak,
)


def _candidate(
    *,
    day: date,
    setup_type: str,
    ordinal: int,
    score: float,
    d1_return: float | None,
) -> LowSuctionCandidate:
    symbol_ordinal = ordinal if setup_type == "trend_pullback" else 100 + ordinal
    return LowSuctionCandidate(
        vt_symbol=f"60{symbol_ordinal:04d}.SSE",
        trade_date=day,
        setup_type=setup_type,
        rule_key="test_rule",
        matched_rule_keys=("test_rule",),
        score=score,
        band="90-100",
        streak=QuietStreak(total=ordinal, yin=ordinal, yang=0),
        components=(),
        close_price=10.0,
        daily_return_pct=0.0,
        turnover_rate_pct=float(ordinal),
        candle_range_pct=1.0,
        d1_trade_date=day + timedelta(days=1),
        d1_close_return_pct=d1_return,
    )


def test_backtest_uses_top_five_per_family_and_leaves_unfilled_slots_as_cash() -> None:
    start = date(2026, 1, 1)
    calendar = [start + timedelta(days=offset) for offset in range(40)]
    full_day = calendar[20]
    sparse_day = calendar[34]
    candidates: list[LowSuctionCandidate] = []
    for setup_type in ("trend_pullback", "oversold_rebound"):
        for ordinal in range(1, 7):
            candidates.append(
                _candidate(
                    day=full_day,
                    setup_type=setup_type,
                    ordinal=ordinal,
                    score=101 - ordinal,
                    # The sixth item is intentionally a large winner: score, not future return,
                    # must decide whether it is selected.
                    d1_return=float(ordinal if ordinal < 6 else 99),
                )
            )
    candidates.append(
        _candidate(
            day=sparse_day,
            setup_type="oversold_rebound",
            ordinal=7,
            score=95.0,
            d1_return=10.0,
        )
    )

    payload = build_backtest_payload(
        candidates,
        calendar,
        market_regimes={full_day: "above_ma20", sparse_day: "below_ma20"},
    )

    assert payload["version"] == BACKTEST_VERSION
    assert payload["score_version"] == SCORE_VERSION
    assert payload["selection"] == {
        "picks_per_family": PICKS_PER_FAMILY,
        "max_positions": MAX_POSITIONS,
        "allocation_per_pick_pct": ALLOCATION_PER_PICK_PCT,
        "unfilled_slots_are_cash": True,
    }

    ledger_days = payload["ledger_days"]
    full_ledger = next(day for day in ledger_days if day["trade_date"] == full_day.isoformat())
    assert len(full_ledger["legs"]) == MAX_POSITIONS
    assert [leg["rank"] for leg in full_ledger["legs"] if leg["setup_type"] == "trend_pullback"] == [1, 2, 3, 4, 5]
    assert [leg["rank"] for leg in full_ledger["legs"] if leg["setup_type"] == "oversold_rebound"] == [1, 2, 3, 4, 5]
    assert all(leg["d1_close_return_pct"] != 99.0 for leg in full_ledger["legs"])
    assert full_ledger["day_return_pct"] == 3.0

    sparse_ledger = next(day for day in ledger_days if day["trade_date"] == sparse_day.isoformat())
    assert len(sparse_ledger["legs"]) == 1
    assert sparse_ledger["day_return_pct"] == 1.0

    position_sim = payload["position_sim"]
    assert position_sim["combined"]["positions"] == 11
    assert position_sim["market_regimes"]["above_ma20"]["positions"] == 10
    assert position_sim["market_regimes"]["below_ma20"]["positions"] == 1
    assert position_sim["time_segments"]["development"]["positions"] == 10
    assert position_sim["time_segments"]["holdout"]["positions"] == 1


def test_oversold_ranking_keeps_p1_5_before_p1_and_scores_before_turnover() -> None:
    day = date(2026, 8, 3)
    p1 = replace(
        _candidate(
            day=day,
            setup_type="oversold_rebound",
            ordinal=1,
            score=130.0,
            d1_return=0.0,
        ),
        rule_key=STAGED_MA10_SUPPORT_RULE_KEY,
        matched_rule_keys=(STAGED_MA10_SUPPORT_RULE_KEY,),
    )
    p1_5_far = replace(
        _candidate(
            day=day,
            setup_type="oversold_rebound",
            ordinal=2,
            score=120.0,
            d1_return=0.0,
        ),
        rule_key=FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
        matched_rule_keys=(FIRST_LEG_TWO_MA_WRAP_RULE_KEY,),
        turnover_rate_pct=5.0,
    )
    p1_5_near = replace(
        _candidate(
            day=day,
            setup_type="oversold_rebound",
            ordinal=3,
            score=120.0,
            d1_return=0.0,
        ),
        rule_key=FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
        matched_rule_keys=(FIRST_LEG_TWO_MA_WRAP_RULE_KEY,),
        turnover_rate_pct=3.0,
    )
    p1_5_missing_turnover = replace(
        _candidate(
            day=day,
            setup_type="oversold_rebound",
            ordinal=4,
            score=140.0,
            d1_return=0.0,
        ),
        rule_key=FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
        matched_rule_keys=(FIRST_LEG_TWO_MA_WRAP_RULE_KEY,),
        turnover_rate_pct=None,
    )

    ranked = sorted(
        (p1, p1_5_far, p1_5_near, p1_5_missing_turnover),
        key=candidate_ranking_key,
    )

    assert [item.rule_key for item in ranked] == [
        FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
        FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
        FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
        STAGED_MA10_SUPPORT_RULE_KEY,
    ]
    assert [item.vt_symbol for item in ranked[:3]] == [
        p1_5_missing_turnover.vt_symbol,
        p1_5_near.vt_symbol,
        p1_5_far.vt_symbol,
    ]
    assert ranked[3].vt_symbol == p1.vt_symbol


def test_backtest_selects_d_day_top_pick_before_d1_label_availability() -> None:
    start = date(2026, 1, 1)
    calendar = [start + timedelta(days=offset) for offset in range(40)]
    day = calendar[20]
    top_without_label = replace(
        _candidate(
            day=day,
            setup_type="oversold_rebound",
            ordinal=1,
            score=100.0,
            d1_return=0.0,
        ),
        d1_trade_date=None,
        d1_close_return_pct=None,
    )
    lower_with_label = _candidate(
        day=day,
        setup_type="oversold_rebound",
        ordinal=2,
        score=90.0,
        d1_return=1.0,
    )

    payload = build_backtest_payload([top_without_label, lower_with_label], calendar)

    ledger = next(item for item in payload["ledger_days"] if item["trade_date"] == day.isoformat())
    assert [(leg["vt_symbol"], leg["rank"]) for leg in ledger["legs"]] == [
        (top_without_label.vt_symbol, 1),
        (lower_with_label.vt_symbol, 2),
    ]
    assert ledger["legs"][0]["d1_close_return_pct"] is None


def test_backtest_marks_an_entirely_unsettled_ledger_day_without_return() -> None:
    start = date(2026, 1, 1)
    calendar = [start + timedelta(days=offset) for offset in range(40)]
    day = calendar[20]
    unsettled = replace(
        _candidate(
            day=day,
            setup_type="trend_pullback",
            ordinal=1,
            score=100.0,
            d1_return=0.0,
        ),
        d1_trade_date=None,
        d1_close_return_pct=None,
    )

    payload = build_backtest_payload([unsettled], calendar)

    ledger = next(item for item in payload["ledger_days"] if item["trade_date"] == day.isoformat())
    assert ledger["day_return_pct"] is None
