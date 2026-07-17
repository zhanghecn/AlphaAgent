from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.forward_leader_identity import (
    FORWARD_LEADER_RANKING_VERSION,
    ForwardLeaderSourceInputs,
    build_forward_leader_capture,
    render_forward_leader_report_json,
    render_forward_leader_report_markdown,
)
from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.leader_identity import LeaderIdentityMode

SHANGHAI = ZoneInfo("Asia/Shanghai")
SOURCE_DATE = date(2026, 7, 16)
MEMBERSHIP_AT = datetime(2026, 7, 16, 18, 0, tzinfo=SHANGHAI)
SECURITY_AT = datetime(2026, 7, 16, 18, 5, tzinfo=SHANGHAI)


def _trading_dates() -> tuple[date, ...]:
    return tuple(
        timestamp.date()
        for timestamp in pd.bdate_range(end=SOURCE_DATE, periods=80)
    )


def _concept_bars() -> pd.DataFrame:
    rows = []
    for index, trade_date in enumerate(_trading_dates()):
        rows.append(
            {
                "sector_id": "BK_TEST",
                "concept_name": "测试主升",
                "trade_date": trade_date,
                "close_price": 100.0 + index,
                "source": "eastmoney.board_kline",
            }
        )
    return pd.DataFrame(rows)


def _benchmark_bars() -> pd.DataFrame:
    rows = []
    for symbol in ("000300.SSE", "000905.SSE", "000852.SSE"):
        for index, trade_date in enumerate(_trading_dates()):
            rows.append(
                {
                    "vt_symbol": symbol,
                    "trade_date": trade_date,
                    "close_price": 1000.0 + index * 0.2,
                    "source": "test",
                }
            )
    return pd.DataFrame(rows)


def _memberships() -> pd.DataFrame:
    rows = []
    for index in range(1, 7):
        rows.append(
            {
                "source_trade_date": SOURCE_DATE,
                "observed_at": MEMBERSHIP_AT,
                "sector_id": "BK_TEST",
                "sector_name": "测试主升",
                "sector_type": "concept",
                "vt_symbol": f"00000{index}.SZSE",
                "evidence_level": "strict",
                "source": "eastmoney.push2.board.forward",
            }
        )
    rows.append(
        {
            "source_trade_date": SOURCE_DATE,
            "observed_at": MEMBERSHIP_AT,
            "sector_id": "BK_TEST",
            "sector_name": "测试主升",
            "sector_type": "concept",
            "vt_symbol": "300001.SZSE",
            "evidence_level": "strict",
            "source": "eastmoney.push2.board.forward",
        }
    )
    return pd.DataFrame(rows)


def _securities() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_trade_date": SOURCE_DATE,
                "observed_at": SECURITY_AT,
                "vt_symbol": f"00000{index}.SZSE",
                "symbol": f"00000{index}",
                "exchange": "SZSE",
                "name": f"测试{index}",
                "status": "LISTED",
                "listed_on": date(2020, 1, index),
                "delisted_on": None,
                "suspended": False,
                "risk_warning": False,
                "evidence_level": "strict",
                "source": "baostock.query_all_stock.forward",
            }
            for index in range(1, 7)
        ]
    )


def _stock_bars() -> pd.DataFrame:
    rows = []
    for symbol_index in range(1, 7):
        close = 10.0
        for day_index, trade_date in enumerate(_trading_dates()):
            daily_move = 0.004 * symbol_index
            if day_index == 78 - symbol_index:
                daily_move += 0.06
            previous = close
            close = previous * (1.0 + daily_move)
            rows.append(
                {
                    "vt_symbol": f"00000{symbol_index}.SZSE",
                    "trade_date": trade_date,
                    "open_price": previous,
                    "close_price": close,
                    "high_price": close * 1.01,
                    "low_price": previous * 0.99,
                    "volume": 10_000_000.0 + symbol_index,
                    "turnover": float(symbol_index * 50_000_000),
                    "change_pct": daily_move * 100.0,
                    "source": "test",
                }
            )
    return pd.DataFrame(rows)


def _inputs() -> ForwardLeaderSourceInputs:
    return ForwardLeaderSourceInputs(
        source_trade_date=SOURCE_DATE,
        attempted_at=datetime(2026, 7, 17, 10, 0, tzinfo=SHANGHAI),
        membership_scope={
            "source_trade_date": SOURCE_DATE,
            "scope_type": "concept_tradable",
            "source": "eastmoney.push2.board.forward",
            "observed_at": MEMBERSHIP_AT,
            "expected_sector_count": 1,
            "returned_sector_count": 1,
            "row_count": 7,
            "symbol_count": 7,
            "complete": True,
            "evidence_level": "strict",
            "manifest_version": "test-manifest-v1",
        },
        security_scope={
            "source_trade_date": SOURCE_DATE,
            "source": "baostock.query_all_stock.forward",
            "observed_at": SECURITY_AT,
            "expected_symbol_count": 6,
            "returned_symbol_count": 6,
            "complete": True,
            "evidence_level": "strict",
        },
        memberships=_memberships(),
        securities=_securities(),
        trading_dates=_trading_dates(),
        concept_bars=_concept_bars(),
        benchmark_bars=_benchmark_bars(),
        stock_bars=_stock_bars(),
    )


def test_forward_capture_freezes_all_modes_without_guessing_target_date() -> None:
    capture = build_forward_leader_capture(_inputs())

    assert capture.complete
    assert capture.source_trade_date == SOURCE_DATE
    assert capture.ranking_version == FORWARD_LEADER_RANKING_VERSION
    assert {scope.identity_mode for scope in capture.scopes} == {
        mode.value for mode in LeaderIdentityMode
    }
    assert all(scope.selected_mode is None for scope in capture.scopes)
    assert all(scope.target_session == "next_trading_session" for scope in capture.scopes)
    assert all(scope.target_trade_date is None for scope in capture.scopes)
    assert all(row.target_trade_date is None for row in capture.rows)
    assert all(scope.active_concept_count == 1 for scope in capture.scopes)
    assert all(scope.raw["board_excluded_rows"] == 1 for scope in capture.scopes)
    assert all(scope.main_board_member_count == 6 for scope in capture.scopes)
    assert all(scope.top3_row_count == 3 for scope in capture.scopes)


def test_future_stock_bars_cannot_change_frozen_ranks_or_fingerprint() -> None:
    original = build_forward_leader_capture(_inputs())
    future = _stock_bars().iloc[[0]].assign(
        trade_date=SOURCE_DATE + timedelta(days=4),
        close_price=9999.0,
        change_pct=999.0,
    )
    mutated = build_forward_leader_capture(
        replace(_inputs(), stock_bars=pd.concat([_stock_bars(), future]))
    )

    assert mutated.input_fingerprint == original.input_fingerprint
    assert [
        (row.identity_mode, row.sector_id, row.vt_symbol, row.rank)
        for row in mutated.rows
    ] == [
        (row.identity_mode, row.sector_id, row.vt_symbol, row.rank)
        for row in original.rows
    ]


@pytest.mark.parametrize(
    "mutate, expected_reason",
    [
        (
            lambda inputs: replace(
                inputs,
                membership_scope={**inputs.membership_scope, "complete": False},
            ),
            "membership_scope_not_strict_complete",
        ),
        (
            lambda inputs: replace(
                inputs,
                security_scope={
                    **inputs.security_scope,
                    "source_trade_date": date(2026, 7, 15),
                },
            ),
            "security_scope_source_date_mismatch",
        ),
    ],
)
def test_incomplete_or_wrong_date_strict_scope_closes_all_modes(
    mutate,
    expected_reason: str,
) -> None:
    capture = build_forward_leader_capture(mutate(_inputs()))

    assert not capture.complete
    assert capture.rows == ()
    assert {scope.status for scope in capture.scopes} == {"blocked"}
    assert {scope.raw["blocking_reason"] for scope in capture.scopes} == {
        expected_reason
    }


def test_missing_source_bar_for_an_eligible_member_closes_ranking() -> None:
    bars = _stock_bars()
    bars = bars.loc[
        ~(
            bars["vt_symbol"].eq("000001.SZSE")
            & pd.to_datetime(bars["trade_date"]).dt.date.eq(SOURCE_DATE)
        )
    ]

    capture = build_forward_leader_capture(replace(_inputs(), stock_bars=bars))

    assert not capture.complete
    assert capture.rows == ()
    assert {scope.raw["blocking_reason"] for scope in capture.scopes} == {
        "eligible_member_source_bar_incomplete"
    }


def test_forward_capture_rejects_future_or_outcome_input_columns() -> None:
    with pytest.raises(ValueError, match="future or outcome"):
        build_forward_leader_capture(
            replace(_inputs(), stock_bars=_stock_bars().assign(future_return=1.0))
        )


def test_forward_cli_and_report_keep_performance_closed() -> None:
    freeze = build_parser().parse_args(
        ["v2-forward-top3-freeze", "--source-date", "2026-07-16"]
    )
    report_args = build_parser().parse_args(
        ["v2-forward-top3-report", "--format", "markdown"]
    )
    report = {
        "ranking_version": FORWARD_LEADER_RANKING_VERSION,
        "source_sessions": 1,
        "bound_sessions": 0,
        "latest_source_trade_date": "2026-07-16",
        "selected_mode": None,
        "selection_status": "accumulating_forward_identity",
        "fold_winners": [],
        "fold_win_counts": {},
        "selection_gate": {"minimum_bound_sessions": 60},
        "mode_metrics": [],
        "mode_top3_overlap": [],
        "latest_top3": [],
        "input_fingerprints": ["sha256:test"],
        "formal_metrics": None,
        "low_suction_outcomes_read": False,
    }

    markdown = render_forward_leader_report_markdown(report)
    payload = render_forward_leader_report_json(report)

    assert freeze.source_date == SOURCE_DATE
    assert report_args.command == "v2-forward-top3-report"
    assert "selected_mode: `null`" in markdown
    assert "formal_metrics: `null`" in markdown
    assert '"formal_metrics": null' in payload
    assert '"low_suction_outcomes_read": false' in payload
