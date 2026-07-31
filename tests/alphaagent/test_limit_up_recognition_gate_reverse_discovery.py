from alphaagent.server.services.limit_up.recognition_gate_reverse_discovery import (
    render_markdown,
)


def test_rendered_report_marks_daily_winners_as_reverse_discovery_only() -> None:
    markdown = render_markdown(
        {
            "status": "reverse_discovery_only",
            "analysis_layer": "ab_base_recognition_gate_only",
            "high_return_pct": 5.0,
            "high_return_sensitivity_pct": 8.0,
            "time_batches": {},
            "daily_high_return_winners": [],
        }
    )

    assert "不构成可交易规则" in markdown
    assert "A+B 基座识别门" in markdown
    assert "D+1 净收益 >= 5.00%" in markdown
