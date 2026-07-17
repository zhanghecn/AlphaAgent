"""Read-only survivorship audit for the local stock master."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope

from .baostock_security_source import (
    SecurityMasterRecord,
    SecurityMasterResult,
    fetch_security_master,
)

RESEARCH_VERSION = "low-suction-security-master-audit-v1"
LISTING_DATE_KEYS = ("list_date", "listDate", "listing_date", "ipoDate")
DELISTING_DATE_KEYS = (
    "delist_date",
    "delistDate",
    "delisting_date",
    "outDate",
)


def load_security_master_audit() -> dict[str, Any]:
    """Fetch BaoStock's master and compare it with the local current table."""

    master = fetch_security_master()
    with session_scope() as session:
        rows = session.execute(
            select(schema.stocks.c.vt_symbol, schema.stocks.c.raw).order_by(
                schema.stocks.c.vt_symbol
            )
        ).mappings().all()
        daily_rows = session.execute(
            select(
                schema.stock_daily_bars.c.vt_symbol,
                func.count().label("row_count"),
                func.min(schema.stock_daily_bars.c.trade_date).label("start"),
                func.max(schema.stock_daily_bars.c.trade_date).label("end"),
            )
            .group_by(schema.stock_daily_bars.c.vt_symbol)
            .order_by(schema.stock_daily_bars.c.vt_symbol)
        ).mappings().all()
    return build_security_master_audit(master, rows, daily_rows)


def build_security_master_audit(
    master: SecurityMasterResult,
    local_rows: Sequence[Mapping[str, Any]],
    local_daily_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a deterministic non-strict survivorship diagnostic."""

    local_symbols = {
        str(row.get("vt_symbol") or "").strip().upper()
        for row in local_rows
        if str(row.get("vt_symbol") or "").strip()
    }
    main_records = tuple(
        record for record in master.records if record.board == "main"
    )
    missing = tuple(
        sorted(
            (
                record
                for record in main_records
                if record.vt_symbol not in local_symbols
            ),
            key=lambda record: record.vt_symbol,
        )
    )
    missing_delisted = tuple(
        record for record in missing if record.status == "DELISTED"
    )
    missing_listed = tuple(
        record for record in missing if record.status != "DELISTED"
    )
    daily_symbols = {
        str(row.get("vt_symbol") or "").strip().upper()
        for row in local_daily_rows
        if str(row.get("vt_symbol") or "").strip()
        and int(row.get("row_count") or 0) > 0
    }
    delisted_records = tuple(
        record for record in main_records if record.status == "DELISTED"
    )
    delisted_with_daily = tuple(
        record for record in delisted_records if record.vt_symbol in daily_symbols
    )
    delisted_without_daily = tuple(
        record for record in delisted_records if record.vt_symbol not in daily_symbols
    )
    target_window_start = master.observed_at.date() - timedelta(days=1_095)
    window_delisted = tuple(
        record
        for record in delisted_records
        if record.delisted_on is not None
        and record.delisted_on >= target_window_start
    )
    window_with_daily = tuple(
        record for record in window_delisted if record.vt_symbol in daily_symbols
    )
    window_without_daily = tuple(
        record for record in window_delisted if record.vt_symbol not in daily_symbols
    )
    listing_date_rows = sum(
        _has_raw_date(row.get("raw"), LISTING_DATE_KEYS) for row in local_rows
    )
    delisting_date_rows = sum(
        _has_raw_date(row.get("raw"), DELISTING_DATE_KEYS) for row in local_rows
    )
    return {
        "research_version": RESEARCH_VERSION,
        "as_of_date": master.observed_at.date().isoformat(),
        "observed_at": master.observed_at.isoformat(),
        "status": "reconstructed_only",
        "strict_ready": False,
        "evidence_level": "reconstructed",
        "formal_metrics": None,
        "master": {
            "source": "baostock.query_stock_basic",
            "total_source_rows": master.total_source_rows,
            "stock_rows": master.stock_rows,
            "main_board_rows": master.main_board_rows,
            "listed_main_board_rows": sum(
                record.status == "LISTED" for record in main_records
            ),
            "delisted_main_board_rows": master.delisted_main_board_rows,
        },
        "local": {
            "source": "stocks",
            "stock_rows": len(local_rows),
            "listing_date_rows": listing_date_rows,
            "delisting_date_rows": delisting_date_rows,
            "daily_bar_symbols": len(daily_symbols),
        },
        "survivorship_gap": {
            "missing_main_board_symbols": len(missing),
            "missing_delisted_main_board_symbols": len(missing_delisted),
            "missing_listed_main_board_symbols": len(missing_listed),
            "missing_delisted_examples": [
                _master_example(record) for record in missing_delisted[:20]
            ],
            "missing_listed_examples": [
                _master_example(record) for record in missing_listed[:20]
            ],
        },
        "daily_history_gap": {
            "target_window_start": target_window_start.isoformat(),
            "delisted_main_board_symbols": len(delisted_records),
            "delisted_with_daily_bars": len(delisted_with_daily),
            "delisted_without_daily_bars": len(delisted_without_daily),
            "missing_daily_examples": [
                _master_example(record) for record in delisted_without_daily[:20]
            ],
            "window_delisted_main_board_symbols": len(window_delisted),
            "window_delisted_with_daily_bars": len(window_with_daily),
            "window_delisted_without_daily_bars": len(window_without_daily),
            "window_missing_daily_examples": [
                _master_example(record) for record in window_without_daily[:20]
            ],
        },
        "source_limitation": (
            "BaoStock exposes reconstructed master fields but no verified publication-time "
            "commitment proving historical availability by D 09:25 Asia/Shanghai"
        ),
    }


def render_security_master_audit_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def render_security_master_audit_markdown(report: Mapping[str, Any]) -> str:
    master = _mapping(report.get("master"))
    local = _mapping(report.get("local"))
    gap = _mapping(report.get("survivorship_gap"))
    history_gap = _mapping(report.get("daily_history_gap"))
    examples = gap.get("missing_delisted_examples")
    lines = [
        "# AlphaAgent 低吸证券主表幸存者偏差审计",
        "",
        f"- 研究版本：`{report.get('research_version')}`",
        f"- 观测时间：`{report.get('observed_at')}`",
        f"- 证据等级：`{report.get('evidence_level')}`",
        "- 正式指标：`null`",
        "- 结论：BaoStock 主表只能作为重建证据，不能解除严格门禁。",
        "",
        "## Coverage",
        "",
        "| 项目 | 数量 |",
        "| --- | ---: |",
        f"| BaoStock 股票 | {int(master.get('stock_rows') or 0):,} |",
        f"| BaoStock 沪深主板 | {int(master.get('main_board_rows') or 0):,} |",
        f"| BaoStock 历史退市主板 | {int(master.get('delisted_main_board_rows') or 0):,} |",
        f"| 本地 stocks | {int(local.get('stock_rows') or 0):,} |",
        f"| 本地含上市日期 | {int(local.get('listing_date_rows') or 0):,} |",
        f"| 本地含退市日期 | {int(local.get('delisting_date_rows') or 0):,} |",
        f"| 本地有日线的股票 | {int(local.get('daily_bar_symbols') or 0):,} |",
        f"| 本地缺失主板 | {int(gap.get('missing_main_board_symbols') or 0):,} |",
        f"| 本地缺失历史退市主板 | {int(gap.get('missing_delisted_main_board_symbols') or 0):,} |",
        f"| 历史退市主板无任何日线 | {int(history_gap.get('delisted_without_daily_bars') or 0):,} |",
        f"| 三年窗退市主板 | {int(history_gap.get('window_delisted_main_board_symbols') or 0):,} |",
        f"| 三年窗退市主板无日线 | {int(history_gap.get('window_delisted_without_daily_bars') or 0):,} |",
        "",
        "## Missing Delisted Examples",
        "",
        "| 股票 | 名称 | 上市 | 退市 |",
        "| --- | --- | --- | --- |",
    ]
    if isinstance(examples, Sequence) and examples:
        for value in examples:
            row = _mapping(value)
            lines.append(
                "| {vt_symbol} | {name} | {listed_on} | {delisted_on} |".format(
                    vt_symbol=row.get("vt_symbol") or "-",
                    name=row.get("name") or "-",
                    listed_on=row.get("listed_on") or "-",
                    delisted_on=row.get("delisted_on") or "-",
                )
            )
    else:
        lines.append("| - | - | - | - |")
    lines.extend(
        [
            "",
            "## Limitation",
            "",
            f"- {report.get('source_limitation')}",
            "- 该审计只证明本地当前股票清单存在或不存在幸存者偏差缺口，不产生胜率、复利或生产规则。",
        ]
    )
    return "\n".join(lines) + "\n"


def _master_example(record: SecurityMasterRecord) -> dict[str, str | None]:
    return {
        "vt_symbol": record.vt_symbol,
        "name": record.name,
        "listed_on": record.listed_on.isoformat(),
        "delisted_on": (
            record.delisted_on.isoformat() if record.delisted_on else None
        ),
    }


def _has_raw_date(value: Any, keys: Sequence[str]) -> bool:
    if not isinstance(value, Mapping):
        return False
    return any(_date_text(value.get(key)) for key in keys)


def _date_text(value: Any) -> bool:
    text = str(value or "").strip()
    return text not in {"", "0", "00000000", "0000-00-00", "None"}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}
