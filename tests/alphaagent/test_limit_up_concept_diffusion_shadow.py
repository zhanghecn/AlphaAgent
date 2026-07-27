from datetime import date, datetime

import pytest
from sqlalchemy.dialects import postgresql

from alphaagent.server.db import schema
from alphaagent.server.services.limit_up import cash_backtest
from alphaagent.server.services.limit_up import concept_diffusion_shadow_replay
from alphaagent.server.services.limit_up.concept_diffusion_shadow import (
    FORWARD_START_DATE,
    evaluate_quality_rescue_shadow,
    select_causal_quality_rescue_shadow,
    settle_quality_rescue_shadow,
)


TRADE_DATE = date(2026, 7, 28)
PRIOR_DATE = date(2026, 7, 27)


def test_shadow_keeps_rescue_before_later_ab_and_rejects_after_ab() -> None:
    observations = [
        _observation("2026-07-28T10:10:00+08:00", symbol="600001.SSE"),
        _observation(
            "2026-07-28T10:20:00+08:00",
            symbol="600002.SSE",
            formal_action="buy_now",
            core_passed=True,
            core_reason="qualified",
        ),
        _observation("2026-07-28T10:30:00+08:00", symbol="600003.SSE"),
    ]

    selected = select_causal_quality_rescue_shadow(
        observations,
        required_prior_dates={TRADE_DATE: PRIOR_DATE},
    )

    assert [row["vt_symbol"] for row in selected] == ["600001.SSE"]
    assert selected[0]["shadow_components"] == ["static_industry_override"]


def test_shadow_rejects_candidate_when_ab_already_existed() -> None:
    observations = [
        _observation(
            "2026-07-28T10:05:00+08:00",
            symbol="600002.SSE",
            formal_action="buy_now",
            core_passed=True,
            core_reason="qualified",
        ),
        _observation("2026-07-28T10:10:00+08:00", symbol="600001.SSE"),
    ]

    assert select_causal_quality_rescue_shadow(
        observations,
        required_prior_dates={TRADE_DATE: PRIOR_DATE},
    ) == []


def test_broad_rise_industry_rescue_requires_prior_pullback() -> None:
    positive = _observation(
        "2026-07-28T10:10:00+08:00",
        market_phase="broad_rise",
        prior_return=3.0,
    )
    pullback = _observation(
        "2026-07-29T10:10:00+08:00",
        symbol="600002.SSE",
        trade_date=date(2026, 7, 29),
        membership_date=date(2026, 7, 28),
        market_phase="broad_rise",
        prior_return=-3.0,
    )

    selected = select_causal_quality_rescue_shadow(
        [positive, pullback],
        required_prior_dates={
            date(2026, 7, 28): date(2026, 7, 27),
            date(2026, 7, 29): date(2026, 7, 28),
        },
    )

    assert [row["vt_symbol"] for row in selected] == ["600002.SSE"]


def test_pullback_rescue_fails_closed_when_prior_return_is_missing() -> None:
    candidate = _observation(
        "2026-07-28T10:10:00+08:00",
        core_reason="same_stock_d1_samples_below_5",
        industry_ratio=0.5,
        stock_gene_rate=40.0,
        market_phase="mixed",
        prior_return=None,
    )

    assert select_causal_quality_rescue_shadow(
        [candidate],
        required_prior_dates={TRADE_DATE: PRIOR_DATE},
    ) == []


def test_shadow_normalizes_naive_capture_time_to_shanghai() -> None:
    candidate = _observation("2026-07-28T10:10:00", symbol="600001.SSE")
    later_ab = _observation(
        "2026-07-28T10:20:00+08:00",
        symbol="600002.SSE",
        formal_action="buy_now",
        core_passed=True,
        core_reason="qualified",
    )

    selected = select_causal_quality_rescue_shadow(
        [candidate, later_ab],
        required_prior_dates={TRADE_DATE: PRIOR_DATE},
    )

    assert [row["vt_symbol"] for row in selected] == ["600001.SSE"]


def test_shadow_selects_dynamic_concept_from_all_memberships() -> None:
    leaders = [
        _observation(
            "2026-07-28T10:01:00+08:00",
            symbol="600011.SSE",
            board_level=2,
            core_reason="prior_limit_count_126_below_2",
            concept_candidates=[
                _concept("wide", 100),
                _concept("specific", 20),
            ],
        ),
        _observation(
            "2026-07-28T10:02:00+08:00",
            symbol="600012.SSE",
            board_level=3,
            core_reason="prior_limit_count_126_below_2",
            concept_candidates=[
                _concept("wide", 100),
                _concept("specific", 20),
            ],
        ),
        _observation(
            "2026-07-28T10:03:00+08:00",
            symbol="600013.SSE",
            board_level=1,
            core_reason="prior_limit_count_126_below_2",
            concept_candidates=[_concept("wide", 100)],
        ),
    ]
    candidate = _observation(
        "2026-07-28T10:10:00+08:00",
        symbol="600020.SSE",
        core_reason="prior_limit_count_126_above_6",
        industry_ratio=0.5,
        stock_gene_rate=40.0,
        market_phase="mixed",
        prior_return=2.0,
        concept_candidates=[
            _concept("wide", 100),
            _concept("specific", 20),
        ],
    )

    selected = select_causal_quality_rescue_shadow(
        [*leaders, candidate],
        required_prior_dates={TRADE_DATE: PRIOR_DATE},
    )

    assert len(selected) == 1
    assert selected[0]["vt_symbol"] == "600020.SSE"
    assert selected[0]["intraday_concept_id"] == "specific"
    assert selected[0]["intraday_concept_prior_sealed_count"] == 2
    assert selected[0]["intraday_concept_candidate_rank"] == 3
    assert selected[0]["intraday_concept_prior_max_board"] == 3
    assert selected[0]["shadow_components"] == ["concept_diffusion"]


def test_concept_rescue_fails_closed_without_strict_d1_membership() -> None:
    leaders = [
        _observation(
            "2026-07-28T10:01:00+08:00",
            symbol="600011.SSE",
            board_level=2,
            core_reason="prior_limit_count_126_below_2",
            concept_candidates=[_concept("specific", 20)],
            membership_date=date(2026, 7, 25),
        ),
        _observation(
            "2026-07-28T10:02:00+08:00",
            symbol="600012.SSE",
            board_level=3,
            core_reason="prior_limit_count_126_below_2",
            concept_candidates=[_concept("specific", 20)],
            membership_date=date(2026, 7, 25),
        ),
    ]
    candidate = _observation(
        "2026-07-28T10:10:00+08:00",
        symbol="600020.SSE",
        core_reason="prior_limit_count_126_above_6",
        industry_ratio=0.5,
        stock_gene_rate=40.0,
        market_phase="mixed",
        prior_return=2.0,
        concept_candidates=[_concept("specific", 20)],
        membership_date=date(2026, 7, 25),
    )

    assert select_causal_quality_rescue_shadow(
        [*leaders, candidate],
        required_prior_dates={TRADE_DATE: PRIOR_DATE},
    ) == []


def test_shadow_settlement_uses_next_official_close_and_formal_costs() -> None:
    selected = [
        {
            "trade_date": TRADE_DATE,
            "captured_at": datetime.fromisoformat("2026-07-28T10:03:10+08:00"),
            "vt_symbol": "600001.SSE",
            "name": "测试股份",
            "limit_price": 10.0,
        }
    ]
    rows, metadata = settle_quality_rescue_shadow(
        selected,
        [
            {
                "trade_date": date(2026, 7, 29),
                "vt_symbol": "600001.SSE",
                "close_price": 11.0,
            }
        ],
        trade_dates=[TRADE_DATE, date(2026, 7, 29)],
    )
    expected = cash_backtest.calculate_round_trip_outcome(
        10.0,
        11.0,
        limit_price=10.0,
    )

    assert len(rows) == 1
    assert rows[0]["result_date"] == date(2026, 7, 29)
    assert rows[0]["return_pct"] == pytest.approx(expected["net_return_pct"])
    assert metadata["closed_count"] == 1


def test_forward_evaluation_enforces_frequency_quality_and_compound_gates() -> None:
    baseline = [
        {
            "trade_date": date(2026, 6, day),
            "vt_symbol": f"600{day:03d}.SSE",
            "return_pct": -2.0 if day % 2 == 0 else 3.0,
        }
        for day in range(1, 11)
    ]
    shadow = [
        {
            "trade_date": date(2026, 7, day),
            "vt_symbol": f"601{day:03d}.SSE",
            "return_pct": -1.0 if day % 3 == 0 else 2.0,
        }
        for day in range(1, 16)
    ]

    result = evaluate_quality_rescue_shadow(baseline, shadow)

    assert result["incremental"]["closed_count"] == 15
    assert result["incremental"]["win_rate_pct"] == pytest.approx(66.6667)
    assert result["added_trade_days"] == 15
    assert result["forward_gate_passed"] is True
    assert result["status"] == "forward_candidate_research_only"
    assert result["formal_strategy_changed"] is False


def test_replay_queries_only_first_stock_day_event() -> None:
    observation = schema.limit_up_radar_observations
    query = concept_diffusion_shadow_replay._first_event_observation_query(
        date(2026, 7, 28),
        date(2026, 7, 31),
        event_filter=observation.c.capture_state.in_(("sealed", "resealed")),
    )

    sql = str(query.compile(dialect=postgresql.dialect()))

    assert (
        "DISTINCT ON (limit_up_radar_frames.trade_date, "
        "limit_up_radar_observations.vt_symbol)" in sql
    )


def test_replay_rejects_window_before_forward_start() -> None:
    assert FORWARD_START_DATE == date(2026, 7, 27)
    with pytest.raises(ValueError, match="ends before forward start"):
        concept_diffusion_shadow_replay.replay_quality_rescue_shadow(
            date(2026, 7, 10),
            date(2026, 7, 24),
        )


def _concept(concept_id: str, member_count: int) -> dict[str, object]:
    return {
        "concept_id": concept_id,
        "concept_name": concept_id,
        "member_count": member_count,
    }


def _observation(
    captured_at: str,
    *,
    symbol: str = "600001.SSE",
    trade_date: date = TRADE_DATE,
    membership_date: date = PRIOR_DATE,
    formal_action: str = "pass",
    core_passed: bool = False,
    core_reason: str = "same_stock_joint_rate_below_30",
    market_phase: str = "retreat",
    prior_return: float | None = -1.0,
    industry_ratio: float = 1.2,
    stock_gene_rate: float = 20.0,
    board_level: int = 1,
    concept_candidates: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "captured_at": datetime.fromisoformat(captured_at),
        "strategy_version": "limit-up-core-abc-v2",
        "quality_status": "ready",
        "is_stale": False,
        "vt_symbol": symbol,
        "name": symbol,
        "board_lane": "first_board",
        "board_level": board_level,
        "capture_state": "sealed",
        "signal_kind": "first_touch",
        "limit_price": 10.0,
        "formal_action": formal_action,
        "core_quality_gate_passed": core_passed,
        "core_quality_gate_reason": core_reason,
        "lane_blocker_codes": [],
        "prior_market_phase": market_phase,
        "prior_return_5d_pct": prior_return,
        "prior_industry_turnover_ratio_5d": industry_ratio,
        "stock_gene_combined_win_rate": stock_gene_rate,
        "concept_candidates": concept_candidates or [],
        "concept_membership_snapshot_date": membership_date,
        "concept_trigger_allowed": True,
    }
