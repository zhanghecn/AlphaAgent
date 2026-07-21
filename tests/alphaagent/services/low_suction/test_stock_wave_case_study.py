from __future__ import annotations

import json
from datetime import date

import pandas as pd

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.stock_wave_case_study import (
    build_declared_continuation_case_report,
    build_stock_wave_case_report,
    render_stock_wave_case_json,
    render_stock_wave_case_markdown,
)


def _case_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-02", periods=32)
    path = (
        (11.0, 9.9, 10.8, 200.0),
        (12.0, 10.7, 11.8, 160.0),
        (11.7, 10.9, 11.4, 70.0),
        (11.3, 10.55, 10.7, 90.0),
        (10.8, 9.9, 10.1, 180.0),
        (11.5, 10.0, 11.2, 120.0),
        (12.5, 11.1, 12.3, 150.0),
    )
    rows: list[dict[str, object]] = []
    for index, trade_date in enumerate(dates):
        if index < 25:
            high, low, close, volume = 10.2, 9.8, 10.0, 100.0
        else:
            high, low, close, volume = path[index - 25]
        rows.append(
            {
                "trade_date": trade_date,
                "open_price": close,
                "high_price": high,
                "low_price": low,
                "close_price": close,
                "volume": volume,
            }
        )
    return pd.DataFrame(rows)


def _report() -> dict[str, object]:
    bars = _case_bars()
    return build_stock_wave_case_report(
        vt_symbol="600001.SSE",
        stock_name="测试龙头",
        daily_bars=bars,
        campaign_start=pd.Timestamp(bars.iloc[25]["trade_date"]).date(),
        observation_end=pd.Timestamp(bars.iloc[-1]["trade_date"]).date(),
        coverage={"source": "fixture"},
        fingerprint={"digest": "sha256:test"},
    )


def test_report_separates_case_execution_from_population_claims() -> None:
    report = _report()

    assert report["research_status"] == "exploratory_single_stock_case"
    assert report["formal_strategy"] is False
    assert report["population_metrics"] == {
        "win_rate_pct": None,
        "compounded_return_pct": None,
        "profit_factor": None,
        "maximum_drawdown_pct": None,
    }
    assert report["tables_read"]["low_suction_outcomes"] == 0
    assert report["campaign_summary"]["confirmed_higher_highs"] == 1
    assert len(report["waves"]) == 2
    assert {row["support_line"] for row in report["first_campaign_supports"]} == {
        "ma5",
        "ma10",
        "ma20",
    }
    assert report["case_trade_summary"]["closed_entries"] == 3
    assert len(report["wave_path"]) == 1
    assert report["case_wave_path_summary"]["trades"] == 1
    assert report["case_wave_path_summary"]["compounded_return_pct"] is not None
    assert report["case_wave_path_summary"]["positive_trade_share_pct"] == 100.0
    assert [state["state"] for state in report["emotion_state_machine"]] == [
        "ignition",
        "rising_tide",
        "ebb_support_test",
        "return_flow_higher_high",
        "structural_exit",
        "retrospective_terminal",
    ]


def test_report_records_explicit_signal_and_hindsight_boundaries() -> None:
    report = _report()

    assert report["evidence_boundaries"]["signal_features"] == "point_in_time"
    assert report["evidence_boundaries"]["wave_resolution"] == "retrospective_label"
    assert report["evidence_boundaries"]["entry_fill"] == "daily_close_proxy"
    assert report["evidence_boundaries"]["minute_bars_read"] == 0
    assert report["evidence_boundaries"]["wave_path"] == "one_earliest_entry_per_wave_non_overlapping"
    assert report["trade_rules"]["primary_exit"] == "first_later_high_above_pre_pullback_peak_then_close"


def test_json_and_markdown_render_complete_case_evidence() -> None:
    report = _report()
    payload = json.loads(render_stock_wave_case_json(report))
    markdown = render_stock_wave_case_markdown(report)

    assert payload["case"]["stock_name"] == "测试龙头"
    assert "不是全市场胜率" in markdown
    assert "首次接近 MA5/MA10/MA20" in markdown
    assert "事后波浪标签" in markdown
    assert "尾盘代理买入与因果退出" in markdown
    assert "每浪第一次机会的非重叠路径" in markdown
    assert "资金情绪波浪状态机" in markdown


def test_cli_registers_stock_wave_case_study() -> None:
    args = build_parser().parse_args(["v2-stock-wave-case-study"])

    assert args.command == "v2-stock-wave-case-study"
    assert args.format == "markdown"
    assert args.campaign == "xuguang-2025"


def test_declared_continuation_report_preserves_non_ignition_boundary() -> None:
    bars = _case_bars()
    anchor = pd.Timestamp(bars.iloc[28]["trade_date"]).date()
    report = build_declared_continuation_case_report(
        vt_symbol="600001.SSE",
        stock_name="测试龙头",
        daily_bars=bars,
        campaign_start=anchor,
        observation_end=pd.Timestamp(bars.iloc[-1]["trade_date"]).date(),
    )

    assert report["research_status"] == "exploratory_declared_continuation_case"
    assert report["case"]["anchor_contract"] == "user_declared_continuation_candidate"
    assert report["declared_continuation"]["strict_ignition"] is False
    assert report["declared_continuation"]["entry_date"] == anchor.isoformat()
    assert report["wave_impulse_diagnostics"]
    assert {
        "impulse_gain_pct",
        "strong_days_ge_9_5pct",
        "max_volume_ratio_prior5",
    }.issubset(report["wave_impulse_diagnostics"][0])
    assert report["population_metrics"]["win_rate_pct"] is None
    markdown = render_stock_wave_case_markdown(report)
    assert "声明续浪点诊断" in markdown
    assert "起浪加速与高潮对比" in markdown


def test_cli_selects_xuguang_2026_continuation_campaign() -> None:
    args = build_parser().parse_args(
        [
            "v2-stock-wave-case-study",
            "--campaign",
            "xuguang-2026-continuation",
            "--format",
            "json",
        ]
    )

    assert args.campaign == "xuguang-2026-continuation"
    assert args.format == "json"


def test_case_report_requires_campaign_anchor_to_be_an_ignition() -> None:
    bars = _case_bars()

    try:
        build_stock_wave_case_report(
            vt_symbol="600001.SSE",
            stock_name="测试龙头",
            daily_bars=bars,
            campaign_start=date(2025, 1, 2),
            observation_end=pd.Timestamp(bars.iloc[-1]["trade_date"]).date(),
        )
    except ValueError as exc:
        assert "campaign start must be a point-in-time ignition" in str(exc)
    else:
        raise AssertionError("invalid campaign anchor was accepted")
