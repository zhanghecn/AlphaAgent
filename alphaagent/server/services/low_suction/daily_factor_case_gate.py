"""Read-only personal-case gate before daily low-suction factor discovery."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date

from .daily_factor_comprehensive_study import audit_personal_cases


RESEARCH_VERSION = "low-suction-personal-case-gate-v3"


def run_personal_case_gate(
    *,
    bars: Sequence[Mapping[str, object]],
    market_calendar: Sequence[date],
    evidence_level: str,
    blockers: Sequence[str],
    coverage: Mapping[str, object],
    input_sha256: str,
) -> dict[str, object]:
    """Audit declared personal cases without computing factor statistics."""

    normalized_blockers = tuple(str(value) for value in blockers if str(value))
    report: dict[str, object] = {
        "research_version": RESEARCH_VERSION,
        "evidence_level": evidence_level,
        "input_sha256": input_sha256,
        "coverage": dict(coverage),
        "blockers": list(normalized_blockers),
        "case_audit": [],
        "complete_case_count": 0,
        "complete_case_model_match_count": 0,
        "source_narrative_gap_count": 0,
        "unmatched_complete_case_names": [],
        "can_run_recent_half_year": False,
    }
    if normalized_blockers:
        report["case_gate_status"] = "data_blocker"
        return report

    cases = audit_personal_cases(bars, market_calendar)
    complete_cases = [
        row for row in cases if row.get("narrative_status") == "complete"
    ]
    unmatched_names = [
        str(row.get("name"))
        for row in complete_cases
        if not bool(row.get("case_model_matched"))
    ]
    source_gaps = [
        row for row in cases if row.get("narrative_status") != "complete"
    ]
    complete_matches = len(complete_cases) - len(unmatched_names)
    if unmatched_names:
        status = "complete_case_unmatched"
    elif source_gaps:
        status = "case_model_ready_with_source_gap"
    else:
        status = "case_model_ready"
    report.update(
        {
            "case_gate_status": status,
            "case_audit": cases,
            "complete_case_count": len(complete_cases),
            "complete_case_model_match_count": complete_matches,
            "source_narrative_gap_count": len(source_gaps),
            "unmatched_complete_case_names": unmatched_names,
            "can_run_recent_half_year": not unmatched_names,
        }
    )
    return report


def render_personal_case_gate_json(report: Mapping[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"


def render_personal_case_gate_markdown(report: Mapping[str, object]) -> str:
    """Render the gate result without any all-market return aggregation."""

    lines = [
        "# 低吸个人研究案例门禁",
        "",
        f"- 研究版本：`{report.get('research_version', RESEARCH_VERSION)}`",
        f"- 证据等级：`{report.get('evidence_level', '-')}`",
        f"- 门禁状态：`{report.get('case_gate_status', '-')}`",
        "- 可进入近半年诊断：`{value}`".format(
            value=str(bool(report.get("can_run_recent_half_year"))).lower()
        ),
        "- 完整叙述案例命中：`{matched}/{total}`；源叙述缺口：`{gaps}`。".format(
            matched=report.get("complete_case_model_match_count", 0),
            total=report.get("complete_case_count", 0),
            gaps=report.get("source_narrative_gap_count", 0),
        ),
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, Sequence) and blockers:
        lines.extend(["", "## 数据门禁", ""])
        lines.extend(f"- `{value}`" for value in blockers)
    cases = report.get("case_audit")
    if isinstance(cases, Sequence):
        lines.extend(["", "## 案例结果", ""])
        lines.append(
            "| 样例 | 代码 | D 日 | 预期 | 源低吸锚点 | 源形态 | 必须过程规则/缺失 | 收盘回测代理 | 静态实际 | 案例结果 | 全部过程探针 | D+1 状态 | 未通过静态硬条件 |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for row in cases:
            if not isinstance(row, Mapping):
                continue
            lines.append(
                "| {name} | {symbol} | {trade_date} | {expected} | {anchor} | {geometry} | {required} | {close_entry} | {actual} | {status} | {probes} | {data_status} | {failed} |".format(
                    name=row.get("name", "-"),
                    symbol=row.get("vt_symbol", "-"),
                    trade_date=row.get("trade_date", "-"),
                    expected=row.get("expected_setup_type", "-"),
                    anchor=row.get("source_anchor", "-"),
                    geometry=row.get("source_geometry_matched", False),
                    required=_cell(
                        {
                            "required": row.get("required_process_rule_keys"),
                            "matched": row.get("required_process_matched"),
                            "missing": row.get("missing_required_process_rule_keys"),
                            "failed_predicates": row.get(
                                "failed_required_process_predicates"
                            ),
                        }
                    ),
                    close_entry=_cell(
                        {
                            "eligible": row.get("close_only_backtest_eligible"),
                            "price": row.get("close_entry_price"),
                            "distance_to_anchor_pct": row.get(
                                "close_entry_anchor_distance_pct"
                            ),
                        }
                    ),
                    actual=row.get("setup_type", "-"),
                    status=row.get("case_match_status", "-"),
                    probes=_cell(row.get("process_probe_rule_keys")),
                    data_status=row.get("data_status", "-"),
                    failed=_cell(row.get("failed_predicates")),
                )
            )
    return "\n".join(lines) + "\n"


def _cell(value: object) -> str:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return ", ".join(str(item) for item in value) or "-"
    return str(value) if value not in (None, "") else "-"
