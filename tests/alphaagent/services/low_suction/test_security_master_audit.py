from __future__ import annotations

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

from alphaagent.server.services.low_suction import cli
from alphaagent.server.services.low_suction.baostock_security_source import (
    SecurityMasterRecord,
    SecurityMasterResult,
)
from alphaagent.server.services.low_suction.security_master_audit import (
    build_security_master_audit,
    render_security_master_audit_json,
    render_security_master_audit_markdown,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _master() -> SecurityMasterResult:
    return SecurityMasterResult(
        records=(
            SecurityMasterRecord(
                vt_symbol="600000.SSE",
                name="浦发银行",
                listed_on=date(1999, 11, 10),
                delisted_on=None,
                status="LISTED",
                board="main",
                source_code="sh.600000",
            ),
            SecurityMasterRecord(
                vt_symbol="600001.SSE",
                name="邯郸钢铁",
                listed_on=date(1998, 1, 22),
                delisted_on=date(2009, 12, 29),
                status="DELISTED",
                board="main",
                source_code="sh.600001",
            ),
            SecurityMasterRecord(
                vt_symbol="600002.SSE",
                name="齐鲁石化",
                listed_on=date(1998, 4, 8),
                delisted_on=date(2006, 4, 24),
                status="DELISTED",
                board="main",
                source_code="sh.600002",
            ),
            SecurityMasterRecord(
                vt_symbol="600003.SSE",
                name="近期退市",
                listed_on=date(1999, 8, 10),
                delisted_on=date(2025, 2, 26),
                status="DELISTED",
                board="main",
                source_code="sh.600003",
            ),
            SecurityMasterRecord(
                vt_symbol="300001.SZSE",
                name="特锐德",
                listed_on=date(2009, 10, 30),
                delisted_on=None,
                status="LISTED",
                board="chinext",
                source_code="sz.300001",
            ),
        ),
        observed_at=datetime(2026, 7, 16, 12, tzinfo=SHANGHAI),
        total_source_rows=6,
        stock_rows=5,
        main_board_rows=4,
        delisted_main_board_rows=3,
    )


def _local_rows() -> list[dict[str, object]]:
    return [
        {
            "vt_symbol": "600000.SSE",
            "raw": {"list_date": "19991110", "delist_date": ""},
        },
        {"vt_symbol": "600002.SSE", "raw": {}},
        {"vt_symbol": "600003.SSE", "raw": {}},
        {"vt_symbol": "300001.SZSE", "raw": {}},
    ]


def _local_daily_rows() -> list[dict[str, object]]:
    return [
        {
            "vt_symbol": "600000.SSE",
            "row_count": 600,
            "start": date(2024, 1, 15),
            "end": date(2026, 7, 15),
        },
        {
            "vt_symbol": "600002.SSE",
            "row_count": 20,
            "start": date(2006, 3, 20),
            "end": date(2006, 4, 21),
        },
        {
            "vt_symbol": "300001.SZSE",
            "row_count": 600,
            "start": date(2024, 1, 15),
            "end": date(2026, 7, 15),
        },
    ]


def test_audit_quantifies_missing_delisted_main_board_without_metrics() -> None:
    report = build_security_master_audit(
        _master(),
        _local_rows(),
        _local_daily_rows(),
    )

    assert report["status"] == "reconstructed_only"
    assert report["strict_ready"] is False
    assert report["formal_metrics"] is None
    assert report["master"]["main_board_rows"] == 4
    assert report["local"]["stock_rows"] == 4
    assert report["local"]["listing_date_rows"] == 1
    assert report["local"]["delisting_date_rows"] == 0
    assert report["local"]["daily_bar_symbols"] == 3
    assert report["survivorship_gap"]["missing_main_board_symbols"] == 1
    assert report["survivorship_gap"]["missing_delisted_main_board_symbols"] == 1
    assert report["survivorship_gap"]["missing_listed_main_board_symbols"] == 0
    assert report["survivorship_gap"]["missing_delisted_examples"] == [
        {
            "vt_symbol": "600001.SSE",
            "name": "邯郸钢铁",
            "listed_on": "1998-01-22",
            "delisted_on": "2009-12-29",
        }
    ]
    assert report["daily_history_gap"] == {
        "target_window_start": "2023-07-17",
        "delisted_main_board_symbols": 3,
        "delisted_with_daily_bars": 1,
        "delisted_without_daily_bars": 2,
        "missing_daily_examples": [
            {
                "vt_symbol": "600001.SSE",
                "name": "邯郸钢铁",
                "listed_on": "1998-01-22",
                "delisted_on": "2009-12-29",
            },
            {
                "vt_symbol": "600003.SSE",
                "name": "近期退市",
                "listed_on": "1999-08-10",
                "delisted_on": "2025-02-26",
            },
        ],
        "window_delisted_main_board_symbols": 1,
        "window_delisted_with_daily_bars": 0,
        "window_delisted_without_daily_bars": 1,
        "window_missing_daily_examples": [
            {
                "vt_symbol": "600003.SSE",
                "name": "近期退市",
                "listed_on": "1999-08-10",
                "delisted_on": "2025-02-26",
            }
        ],
    }


def test_audit_renderers_are_deterministic_and_keep_warning() -> None:
    report = build_security_master_audit(
        _master(),
        _local_rows(),
        _local_daily_rows(),
    )

    payload = json.loads(render_security_master_audit_json(report))
    markdown = render_security_master_audit_markdown(report)

    assert payload["formal_metrics"] is None
    assert payload["evidence_level"] == "reconstructed"
    assert "幸存者偏差" in markdown
    assert "不能解除严格门禁" in markdown
    assert "600001.SSE" in markdown


def test_cli_registers_security_master_audit_command() -> None:
    args = cli.build_parser().parse_args(
        ["security-master-audit", "--format", "markdown"]
    )

    assert args.command == "security-master-audit"
    assert args.format == "markdown"
