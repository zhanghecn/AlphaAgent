from __future__ import annotations

from datetime import date

import pytest
import pandas as pd

from alphaagent.server.services.low_suction import daily_factor_case_gate
from alphaagent.server.services.low_suction import cli
from alphaagent.server.services.low_suction import daily_factor_repository as repository


def _case_row(
    name: str,
    *,
    narrative_status: str = "complete",
    case_model_matched: bool = True,
) -> dict[str, object]:
    return {
        "name": name,
        "vt_symbol": "600000.SSE",
        "trade_date": date(2026, 1, 5),
        "expected_setup_type": "trend_pullback",
        "setup_type": "trend_pullback" if case_model_matched else None,
        "case_model_matched": case_model_matched,
        "case_match_status": (
            "baseline_matched"
            if case_model_matched
            else "source_narrative_incomplete"
            if narrative_status != "complete"
            else "unmatched"
        ),
        "process_probe_rule_keys": [],
        "narrative_status": narrative_status,
        "data_status": "available",
        "d1_close_return_pct": 1.0,
        "failed_predicates": [],
    }


def test_case_gate_allows_recent_half_year_after_complete_cases_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (
        _case_row("complete case"),
        _case_row(
            "incomplete case",
            narrative_status="source_narrative_incomplete",
            case_model_matched=False,
        ),
    )
    monkeypatch.setattr(
        daily_factor_case_gate,
        "audit_personal_cases",
        lambda bars, calendar: list(rows),
    )

    report = daily_factor_case_gate.run_personal_case_gate(
        bars=(),
        market_calendar=(date(2026, 1, 5),),
        evidence_level="exploratory_raw_unadjusted",
        blockers=(),
        coverage={"price_basis": "raw_unadjusted"},
        input_sha256="case-input",
    )

    assert report["case_gate_status"] == "case_model_ready_with_source_gap"
    assert report["can_run_recent_half_year"] is True
    assert report["complete_case_count"] == 1
    assert report["complete_case_model_match_count"] == 1
    assert report["source_narrative_gap_count"] == 1


def test_case_gate_blocks_recent_half_year_when_a_complete_case_is_unmatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        daily_factor_case_gate,
        "audit_personal_cases",
        lambda bars, calendar: [_case_row("unmatched", case_model_matched=False)],
    )

    report = daily_factor_case_gate.run_personal_case_gate(
        bars=(),
        market_calendar=(date(2026, 1, 5),),
        evidence_level="exploratory_raw_unadjusted",
        blockers=(),
        coverage={"price_basis": "raw_unadjusted"},
        input_sha256="case-input",
    )

    assert report["case_gate_status"] == "complete_case_unmatched"
    assert report["can_run_recent_half_year"] is False
    assert report["unmatched_complete_case_names"] == ["unmatched"]


def test_case_gate_renderer_shows_case_status_without_factor_statistics() -> None:
    markdown = daily_factor_case_gate.render_personal_case_gate_markdown(
        {
            "research_version": "test",
            "evidence_level": "exploratory_raw_unadjusted",
            "case_gate_status": "case_model_ready",
            "can_run_recent_half_year": True,
            "case_audit": [_case_row("case")],
        }
    )

    assert "个人研究案例门禁" in markdown
    assert "case_model_ready" in markdown
    assert "D+1 均值" not in markdown


def test_cli_declares_targeted_personal_case_gate(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inputs = repository.DailyFactorInputs(
        market_calendar=(date(2026, 1, 5),),
        bars=pd.DataFrame(),
        security_status=pd.DataFrame(),
        evidence_level="exploratory_raw_unadjusted",
        blockers=(),
        coverage={"price_basis": "raw_unadjusted"},
        input_sha256="case-input",
    )
    calls: list[dict[str, object]] = []

    def load_inputs(**kwargs: object) -> repository.DailyFactorInputs:
        calls.append(dict(kwargs))
        return inputs

    monkeypatch.setattr(repository, "load_daily_factor_inputs", load_inputs)
    monkeypatch.setattr(
        daily_factor_case_gate,
        "run_personal_case_gate",
        lambda **kwargs: {"case_gate_status": "case_model_ready"},
    )
    monkeypatch.setattr(
        daily_factor_case_gate,
        "render_personal_case_gate_json",
        lambda report: "case-gate-report\n",
    )

    assert cli.main(
        [
            "daily-factor-case-audit",
            "--start",
            "2025-05-01",
            "--end",
            "2026-07-31",
            "--price-basis",
            "raw_unadjusted",
        ]
    ) == 0

    assert calls[0]["price_basis"] == "raw_unadjusted"
    assert set(calls[0]["vt_symbols"]) == {
        "000859.SZSE",
        "003032.SZSE",
        "605179.SSE",
        "001258.SZSE",
        "603221.SSE",
        "600721.SSE",
        "603758.SSE",
        "600683.SSE",
        # 2026-08 趋势族重构新增案例票（连板后补涨/弱转强）
        "603626.SSE",
        "605218.SSE",
        "601086.SSE",
        "600110.SSE",
        "601566.SSE",
        "000547.SZSE",
        "603216.SSE",
        "603696.SSE",
        "002931.SZSE",
        "603045.SSE",
        "603137.SSE",
        "600664.SSE",
        "603928.SSE",
        "002693.SZSE",
        "600396.SSE",
    }
    assert capsys.readouterr().out == "case-gate-report\n"
