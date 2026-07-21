"""Point-in-time evidence audit for unconfirmed true-leader relations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .reason_relations import (
    build_normalized_reason_relations,
    normalize_reason_name,
)


FROZEN_MISMATCH_PATH = Path(
    "memory/06_backtests/low_suction_true_leader_mismatch_study_20260717.json"
)
FROZEN_MISMATCH_SHA256 = (
    "b933d0cd5894dcdf0b3dfb36d91d36236550174eabf9de284b3fde6ada0ccc41"
)
FROZEN_MISMATCH_VERSION = "true-leader-mismatch-audit-v1"
STUDY_VERSION = "true-leader-relation-gap-audit-v1"
EXPECTED_GAP_CASES = 23
RELATION_WINDOW_SESSIONS = 20
CANONICAL_EVENT_SOURCE = "akshare.stock_ztb_em"
EVENT_TYPES = ("limit_pool_zt", "limit_pool_zbgc")
UNCONFIRMED_STATUS = "reason_source_available_but_unconfirmed"


@dataclass(frozen=True)
class RelationGapInputs:
    prior_report: dict[str, Any]
    cases: pd.DataFrame
    events: pd.DataFrame
    concepts: pd.DataFrame
    trading_dates: tuple[date, ...]
    evidence_dates: tuple[date, ...]
    discovery_end: date
    coverage: dict[str, Any]
    fingerprints: dict[str, dict[str, Any]]


def load_frozen_mismatch_report(
    path: Path = FROZEN_MISMATCH_PATH,
) -> dict[str, Any]:
    """Load only the exact mismatch report frozen for this audit."""

    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != FROZEN_MISMATCH_SHA256:
        raise ValueError(f"frozen mismatch report SHA256 mismatch: {digest}")
    try:
        report = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("frozen mismatch report is not valid JSON") from exc
    if report.get("study_version") != FROZEN_MISMATCH_VERSION:
        raise ValueError("unexpected frozen mismatch study version")
    if report.get("formal_metrics") is not None:
        raise ValueError("frozen mismatch report must not contain formal metrics")
    if report.get("formal_selected_mode") is not None:
        raise ValueError("frozen mismatch report must not select a formal mode")
    if report.get("low_suction_outcomes_read") is not False:
        raise ValueError("frozen mismatch report crossed the low-suction boundary")
    return report


def build_relation_gap_cases(
    report: Mapping[str, Any],
    *,
    expected_count: int | None = None,
) -> pd.DataFrame:
    """Extract every source-started unconfirmed mismatch exactly once."""

    if report.get("study_version") != FROZEN_MISMATCH_VERSION:
        raise ValueError("unexpected frozen mismatch study version")
    ledger = report.get("mismatch_ledger")
    if not isinstance(ledger, list) or not ledger:
        raise ValueError("frozen mismatch report has no mismatch ledger")
    frame = pd.DataFrame(ledger)
    required = (
        "cycle_id",
        "trade_date",
        "sector_id",
        "concept_name",
        "truth_top1_symbol",
        "truth_top1_stock_name",
        "truth_relation_status",
        "mismatch_category",
        "decisive_miss_reason",
        "truth_causal_rank",
        "truth_top1_concept_count_same_date",
    )
    _require_columns(frame, required, "frozen mismatch")
    cases = frame.loc[
        frame["truth_relation_status"].astype(str).eq(UNCONFIRMED_STATUS),
        list(required),
    ].copy()
    cases["cycle_id"] = cases["cycle_id"].astype(str)
    cases["trade_date"] = pd.to_datetime(
        cases["trade_date"], errors="raise"
    ).dt.normalize()
    for column in (
        "sector_id",
        "concept_name",
        "truth_top1_symbol",
        "truth_top1_stock_name",
    ):
        cases[column] = cases[column].fillna("").astype(str).str.strip()
    if cases.empty or cases["cycle_id"].duplicated().any():
        raise ValueError("relation-gap cycle identities must be non-empty and unique")
    if cases[
        ["sector_id", "concept_name", "truth_top1_symbol"]
    ].eq("").any(axis=None):
        raise ValueError("relation-gap concept and stock identities cannot be empty")
    if expected_count is not None and len(cases) != expected_count:
        raise ValueError(
            f"frozen relation-gap population changed: {len(cases)} != {expected_count}"
        )
    return cases.sort_values(
        ["trade_date", "sector_id", "truth_top1_symbol"], kind="stable"
    ).reset_index(drop=True)


def audit_relation_gap_cases(
    cases: pd.DataFrame,
    events: pd.DataFrame,
    concepts: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
    evidence_dates: Sequence[date],
    discovery_end: date,
) -> pd.DataFrame:
    """Explain relation gaps without converting absence into a false relation."""

    case_columns = (
        "cycle_id",
        "trade_date",
        "sector_id",
        "concept_name",
        "truth_top1_symbol",
        "truth_top1_stock_name",
    )
    event_columns = (
        "event_id",
        "source_date",
        "vt_symbol",
        "event_type",
        "source",
        "reason",
    )
    _require_columns(cases, case_columns, "relation-gap case")
    _require_columns(events, event_columns, "limit event")
    _require_columns(concepts, ("sector_id", "concept_name"), "concept")
    if cases["cycle_id"].astype(str).duplicated().any():
        raise ValueError("relation-gap cycle identities must be unique")

    calendar = tuple(sorted(set(pd.to_datetime(tuple(trading_dates)).normalize())))
    if not calendar:
        raise ValueError("relation-gap trading calendar is empty")
    calendar_positions = {value: index for index, value in enumerate(calendar)}
    inventory = set(pd.to_datetime(tuple(evidence_dates)).normalize())
    if not inventory:
        raise ValueError("canonical event inventory dates are empty")
    inventory_start = min(inventory)

    event_frame = events.loc[:, list(event_columns)].copy()
    event_frame["source_date"] = pd.to_datetime(
        event_frame["source_date"], errors="raise"
    ).dt.normalize()
    event_frame["event_id"] = pd.to_numeric(
        event_frame["event_id"], errors="raise"
    ).astype(int)
    for column in ("vt_symbol", "event_type", "source", "reason"):
        event_frame[column] = (
            event_frame[column].fillna("").astype(str).str.strip()
        )
    if event_frame["event_id"].duplicated().any():
        raise ValueError("event IDs must be unique")
    if not event_frame["event_type"].isin(EVENT_TYPES).all():
        raise ValueError("relation-gap events contain unsupported event types")
    if not event_frame["source"].eq(CANONICAL_EVENT_SOURCE).all():
        raise ValueError("relation-gap events contain a non-canonical source")
    if event_frame["source_date"].dt.date.gt(discovery_end).any():
        raise ValueError("relation-gap events cross the frozen discovery end")
    event_frame = event_frame.sort_values(
        ["source_date", "event_id"], kind="stable"
    ).reset_index(drop=True)

    concept_frame = concepts.loc[:, ["sector_id", "concept_name"]].copy()
    concept_frame["sector_id"] = concept_frame["sector_id"].astype(str).str.strip()
    concept_frame["concept_name"] = (
        concept_frame["concept_name"].astype(str).str.strip()
    )
    concept_by_sector = concept_frame.set_index("sector_id")["concept_name"].to_dict()
    for case in cases.to_dict("records"):
        if concept_by_sector.get(str(case["sector_id"])) != str(
            case["concept_name"]
        ):
            raise ValueError("frozen case concept conflicts with current catalog")

    reason_events = event_frame.loc[event_frame["reason"].ne("")].copy()
    relation_input = reason_events.assign(stock_name="")
    relation_input = relation_input.loc[
        :, ["event_id", "source_date", "vt_symbol", "stock_name", "reason"]
    ]
    relations = build_normalized_reason_relations(
        relation_input,
        concept_frame,
    )
    events_by_symbol = {
        str(symbol): group
        for symbol, group in event_frame.groupby("vt_symbol", sort=False)
    }
    relations_by_symbol = {
        str(symbol): group
        for symbol, group in relations.groupby("vt_symbol", sort=False)
    }

    rows: list[dict[str, Any]] = []
    for case in cases.to_dict("records"):
        result = dict(case)
        cycle_date = pd.Timestamp(case["trade_date"]).normalize()
        position = calendar_positions.get(cycle_date)
        if position is None or position + 1 < RELATION_WINDOW_SESSIONS:
            raise ValueError("case date cannot form the frozen 20-session window")
        required_dates = tuple(
            calendar[position - RELATION_WINDOW_SESSIONS + 1 : position + 1]
        )
        covered_dates = tuple(value for value in required_dates if value in inventory)
        available_required = tuple(
            value for value in required_dates if value >= inventory_start
        )
        missing_available = tuple(
            value for value in available_required if value not in inventory
        )
        if missing_available:
            window_status = "inventory_date_gap"
        elif len(covered_dates) < RELATION_WINDOW_SESSIONS:
            window_status = "partial_inventory_window"
        else:
            window_status = "full_inventory_window"

        symbol_events = events_by_symbol.get(
            str(case["truth_top1_symbol"]),
            event_frame.iloc[0:0],
        )
        precycle_events = symbol_events.loc[
            symbol_events["source_date"].isin(required_dates)
        ].copy()
        precycle_reason_events = precycle_events.loc[
            precycle_events["reason"].ne("")
        ].copy()
        reason_tokens = _ordered_reason_tokens(precycle_reason_events)
        symbol_relations = relations_by_symbol.get(
            str(case["truth_top1_symbol"]),
            relations.iloc[0:0],
        )
        target_relations = symbol_relations.loc[
            symbol_relations["sector_id"].astype(str).eq(str(case["sector_id"]))
        ].copy()
        precycle_target = target_relations.loc[
            target_relations["source_date"].isin(required_dates)
        ]
        if not precycle_target.empty:
            raise ValueError(
                "frozen unconfirmed case has a precycle exact target relation"
            )
        outside_window_precycle = target_relations.loc[
            target_relations["source_date"].lt(required_dates[0])
            & target_relations["source_date"].le(cycle_date)
        ]
        postcycle_target = target_relations.loc[
            target_relations["source_date"].gt(cycle_date)
            & target_relations["source_date"].le(pd.Timestamp(discovery_end))
        ]
        other_relations = symbol_relations.loc[
            symbol_relations["source_date"].isin(required_dates)
            & ~symbol_relations["sector_id"].astype(str).eq(str(case["sector_id"]))
        ].copy()
        other_matches = tuple(
            {
                "source_date": pd.Timestamp(row["source_date"]).date(),
                "reason_token": str(row["reason_token"]),
                "sector_id": str(row["sector_id"]),
                "concept_name": str(row["concept_name"]),
                "relation_method": str(row["relation_method"]),
            }
            for row in other_relations.sort_values(
                ["source_date", "sector_id", "reason_token"], kind="stable"
            ).to_dict("records")
        )
        lexical_tokens = _lexical_containment_tokens(
            str(case["concept_name"]),
            reason_tokens,
        )
        if precycle_events.empty:
            evidence_status = "no_stock_limit_event"
        elif precycle_reason_events.empty:
            evidence_status = "stock_limit_event_without_reason"
        else:
            evidence_status = "reason_target_unconfirmed"

        if window_status == "partial_inventory_window":
            resolution = "unresolved_partial_inventory_window"
        elif window_status == "inventory_date_gap":
            resolution = "unresolved_inventory_date_gap"
        elif evidence_status == "no_stock_limit_event":
            resolution = "unresolved_no_stock_limit_event"
        elif evidence_status == "stock_limit_event_without_reason":
            resolution = "unresolved_reason_missing"
        elif lexical_tokens:
            resolution = (
                "unresolved_lexical_candidate_requires_external_verification"
            )
        elif other_matches:
            resolution = "unresolved_event_points_to_other_concepts"
        else:
            resolution = "unresolved_unmapped_event_narrative"

        result.update(
            {
                "window_start": required_dates[0],
                "window_end": required_dates[-1],
                "required_sessions": RELATION_WINDOW_SESSIONS,
                "inventory_covered_sessions": len(covered_dates),
                "inventory_missing_dates": tuple(
                    value.date() for value in missing_available
                ),
                "window_coverage_status": window_status,
                "sealed_event_count": int(
                    precycle_events["event_type"].eq("limit_pool_zt").sum()
                ),
                "failed_event_count": int(
                    precycle_events["event_type"].eq("limit_pool_zbgc").sum()
                ),
                "reason_event_count": int(len(precycle_reason_events)),
                "reason_events": tuple(
                    {
                        "source_date": pd.Timestamp(row["source_date"]).date(),
                        "event_type": str(row["event_type"]),
                        "reason": str(row["reason"]),
                    }
                    for row in precycle_reason_events.to_dict("records")
                ),
                "reason_tokens": reason_tokens,
                "other_concept_matches": other_matches,
                "other_concept_names": tuple(
                    sorted({item["concept_name"] for item in other_matches})
                ),
                "lexical_containment_tokens": lexical_tokens,
                "outside_window_precycle_target_relation_dates": _date_tuple(
                    outside_window_precycle["source_date"]
                ),
                "postcycle_target_relation_dates": _date_tuple(
                    postcycle_target["source_date"]
                ),
                "stock_evidence_status": evidence_status,
                "gap_resolution": resolution,
                "promoted_to_precycle_confirmed": False,
                "current_membership_proven_wrong": False,
            }
        )
        rows.append(result)
    return pd.DataFrame(rows).sort_values(
        ["trade_date", "sector_id", "truth_top1_symbol"], kind="stable"
    ).reset_index(drop=True)


def load_relation_gap_inputs(
    report_path: Path = FROZEN_MISMATCH_PATH,
) -> RelationGapInputs:
    """Load only canonical discovery events and the frozen concept catalog."""

    from sqlalchemy import select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import session_scope

    from .concept_cycles import load_cycle_research_calendar
    from .contracts import CONCEPT_SECTOR_TYPES
    from .research_protocol import (
        build_protocol_split,
        default_protocol,
        fingerprint_frame,
    )

    prior_report = load_frozen_mismatch_report(report_path)
    cases = build_relation_gap_cases(
        prior_report,
        expected_count=EXPECTED_GAP_CASES,
    )
    coverage_value = prior_report.get("coverage")
    if not isinstance(coverage_value, Mapping):
        raise ValueError("frozen mismatch report has no coverage contract")
    discovery_start = date.fromisoformat(str(coverage_value["discovery_start"]))
    discovery_end = date.fromisoformat(str(coverage_value["discovery_end"]))
    outer_holdout_end = date.fromisoformat(str(coverage_value["outer_holdout_end"]))
    reliable_dates = load_cycle_research_calendar(as_of_date=outer_holdout_end)
    split = build_protocol_split(reliable_dates, default_protocol())
    if (
        split.discovery_dates[0] != discovery_start
        or split.discovery_dates[-1] != discovery_end
        or split.holdout_dates[-1] != outer_holdout_end
    ):
        raise ValueError("rebuilt research calendar differs from frozen mismatch input")

    source_start = date.fromisoformat(
        str(coverage_value["reason_event_source_start"])
    )
    start_text = source_start.strftime("%Y%m%d")
    end_text = discovery_end.strftime("%Y%m%d")
    symbols = tuple(sorted(cases["truth_top1_symbol"].astype(str).unique()))
    with session_scope() as session:
        event_rows = session.execute(
            select(
                schema.stock_events.c.id,
                schema.stock_events.c.vt_symbol,
                schema.stock_events.c.event_date,
                schema.stock_events.c.event_type,
                schema.stock_events.c.source,
                schema.stock_events.c.raw,
            )
            .where(
                schema.stock_events.c.source == CANONICAL_EVENT_SOURCE,
                schema.stock_events.c.event_type.in_(EVENT_TYPES),
                schema.stock_events.c.vt_symbol.in_(symbols),
                schema.stock_events.c.event_date.between(start_text, end_text),
            )
            .order_by(schema.stock_events.c.event_date, schema.stock_events.c.id)
        ).mappings().all()
        inventory_rows = session.execute(
            select(schema.stock_events.c.event_date)
            .where(
                schema.stock_events.c.source == CANONICAL_EVENT_SOURCE,
                schema.stock_events.c.event_type.in_(EVENT_TYPES),
                schema.stock_events.c.event_date.between(start_text, end_text),
            )
            .distinct()
            .order_by(schema.stock_events.c.event_date)
        ).scalars().all()
        concept_rows = session.execute(
            select(schema.sectors.c.id, schema.sectors.c.name)
            .where(schema.sectors.c.type.in_(CONCEPT_SECTOR_TYPES))
            .order_by(schema.sectors.c.id)
        ).all()

    events = _normalize_database_events(event_rows)
    concepts = pd.DataFrame(concept_rows, columns=["sector_id", "concept_name"])
    evidence_dates = tuple(
        sorted(
            {
                parsed
                for value in inventory_rows
                if (parsed := _event_date(value)) is not None
                and parsed in set(split.discovery_dates)
            }
        )
    )
    if not evidence_dates or evidence_dates[0] != source_start:
        raise ValueError("canonical event inventory start changed")

    case_fingerprint_frame = cases.loc[
        :,
        [
            "cycle_id",
            "trade_date",
            "sector_id",
            "concept_name",
            "truth_top1_symbol",
            "truth_top1_stock_name",
        ],
    ]
    inventory_frame = pd.DataFrame({"source_date": evidence_dates})
    fingerprints = {
        "frozen_mismatch_report": {
            "algorithm": "sha256",
            "digest": f"sha256:{FROZEN_MISMATCH_SHA256}",
            "rows": EXPECTED_GAP_CASES,
            "columns": ["mismatch_ledger"],
        },
        "relation_gap_cases": fingerprint_frame(
            case_fingerprint_frame,
            identity_columns=("cycle_id",),
        ).as_dict(),
        "case_symbol_events": fingerprint_frame(
            events,
            identity_columns=("event_id",),
        ).as_dict(),
        "canonical_event_inventory_dates": fingerprint_frame(
            inventory_frame,
            identity_columns=("source_date",),
        ).as_dict(),
        "concept_catalog": fingerprint_frame(
            concepts,
            identity_columns=("sector_id",),
        ).as_dict(),
    }
    coverage = {
        "discovery_start": discovery_start.isoformat(),
        "discovery_end": discovery_end.isoformat(),
        "outer_holdout_end": outer_holdout_end.isoformat(),
        "canonical_event_source": CANONICAL_EVENT_SOURCE,
        "event_inventory_start": evidence_dates[0].isoformat(),
        "event_inventory_end": evidence_dates[-1].isoformat(),
        "event_inventory_dates": len(evidence_dates),
        "gap_cases": int(len(cases)),
        "gap_symbols": int(cases["truth_top1_symbol"].nunique()),
        "case_symbol_event_rows": int(len(events)),
        "case_symbol_reason_rows": int(events["reason"].ne("").sum()),
        "concept_catalog_rows": int(len(concepts)),
        "stock_price_rows_read": 0,
        "minute_rows_read": 0,
    }
    return RelationGapInputs(
        prior_report=prior_report,
        cases=cases,
        events=events,
        concepts=concepts,
        trading_dates=split.discovery_dates,
        evidence_dates=evidence_dates,
        discovery_end=discovery_end,
        coverage=coverage,
        fingerprints=fingerprints,
    )


def run_true_leader_relation_gap_study() -> dict[str, Any]:
    """Run the relation-gap audit without reading ranking or trade outcomes."""

    inputs = load_relation_gap_inputs()
    audited = audit_relation_gap_cases(
        inputs.cases,
        inputs.events,
        inputs.concepts,
        trading_dates=inputs.trading_dates,
        evidence_dates=inputs.evidence_dates,
        discovery_end=inputs.discovery_end,
    )
    return build_relation_gap_report(inputs, audited_cases=audited)


def build_relation_gap_report(
    inputs: RelationGapInputs,
    *,
    audited_cases: pd.DataFrame,
) -> dict[str, Any]:
    """Build a deterministic machine report containing every gap case."""

    required = (
        "cycle_id",
        "window_coverage_status",
        "stock_evidence_status",
        "gap_resolution",
        "other_concept_names",
        "lexical_containment_tokens",
        "postcycle_target_relation_dates",
        "promoted_to_precycle_confirmed",
    )
    _require_columns(audited_cases, required, "audited relation gap")
    expected = set(inputs.cases["cycle_id"].astype(str))
    actual = set(audited_cases["cycle_id"].astype(str))
    if expected != actual or audited_cases["cycle_id"].duplicated().any():
        raise ValueError("audited relation gaps must preserve every frozen case")
    if audited_cases["promoted_to_precycle_confirmed"].astype(bool).any():
        raise ValueError("unverified relation gap cannot be promoted")

    window_counts = _value_counts(audited_cases["window_coverage_status"])
    evidence_counts = _value_counts(audited_cases["stock_evidence_status"])
    resolution_counts = _value_counts(audited_cases["gap_resolution"])
    partial = audited_cases["window_coverage_status"].eq(
        "partial_inventory_window"
    )
    full = audited_cases["window_coverage_status"].eq("full_inventory_window")
    coverage = {
        **inputs.coverage,
        "audited_cases": int(len(audited_cases)),
        "partial_inventory_window_cases": int(partial.sum()),
        "full_inventory_window_cases": int(full.sum()),
        "inventory_date_gap_cases": int(
            audited_cases["window_coverage_status"].eq(
                "inventory_date_gap"
            ).sum()
        ),
        "lexical_candidate_cases": int(
            audited_cases["lexical_containment_tokens"].map(bool).sum()
        ),
        "other_exact_concept_cases": int(
            audited_cases["other_concept_names"].map(bool).sum()
        ),
        "postcycle_target_relation_cases": int(
            audited_cases["postcycle_target_relation_dates"].map(bool).sum()
        ),
        "promoted_cases": 0,
    }
    credible_count = int(
        inputs.prior_report.get("coverage", {}).get(
            "credible_relation_ranking_failure_misses",
            0,
        )
    )
    report = {
        "study_version": STUDY_VERSION,
        "overall_conclusion": "no_gap_promoted_to_credible_rank_failure",
        "formal_metrics": None,
        "formal_selected_mode": None,
        "strict_top3_claim": False,
        "low_suction_rule_selected": False,
        "low_suction_outcomes_read": False,
        "minute_bars_read": False,
        "market_timing_read": False,
        "gold_silver_read": False,
        "stock_price_values_read": False,
        "leader_ranking_recomputed": False,
        "semantic_aliases_promoted": False,
        "frozen_input": {
            "path": str(FROZEN_MISMATCH_PATH),
            "sha256": FROZEN_MISMATCH_SHA256,
            "mismatch_truth_changed": False,
        },
        "audit_contract": {
            "relation_window_sessions": RELATION_WINDOW_SESSIONS,
            "canonical_event_source": CANONICAL_EVENT_SOURCE,
            "event_types": list(EVENT_TYPES),
            "inventory_date_presence_is_formal_scope": False,
            "reason_absence_proves_wrong_membership": False,
            "other_concept_match_proves_wrong_membership": False,
            "lexical_containment_confirms_relation": False,
            "postcycle_relation_moves_backward": False,
        },
        "coverage": coverage,
        "window_coverage_counts": window_counts,
        "stock_evidence_counts": evidence_counts,
        "gap_resolution_counts": resolution_counts,
        "credible_ranking_failure_count_before": credible_count,
        "credible_ranking_failure_count_after": credible_count,
        "case_ledger": _records(audited_cases),
        "fingerprints": _json_safe(inputs.fingerprints),
        "limitations": [
            "historical canonical event scopes were not persisted; inventory-date presence is a weaker coverage indicator",
            "no stock event or no reason remains unknown rather than a false concept membership",
            "event reasons describe the observed catalyst and do not define the complete historical member set",
            "lexical containment requires independent semantic verification and was not promoted",
            "postcycle exact relations cannot confirm an earlier cycle",
            "current concept membership remains a survivorship proxy",
        ],
        "next_stage": "expand_verified_point_in_time_relation_evidence_before_new_rank",
        "reproduce": (
            "docker compose run --rm --no-deps "
            "-v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api "
            "python -m alphaagent.server.services.low_suction.cli "
            "v2-true-leader-relation-gap-study --format markdown"
        ),
    }
    return _json_safe(report)


def render_relation_gap_study_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_relation_gap_study_markdown(report: Mapping[str, Any]) -> str:
    coverage = report["coverage"]
    lines = [
        "# AlphaAgent 真龙头关系缺口审计",
        "",
        f"结论：`{report['overall_conclusion']}`。升级为可信排序失败：`0`；正式模式：`null`。",
        "",
        "本报告冻结上一轮 23 个来源已启动但关系未确认的漏抓，逐股检查 20 个交易日的",
        "事件库存、涨停/炸板、原始原因、其他概念精确命中和后周期证据，不读取价格或低吸结果。",
        "",
        "## Coverage",
        "",
        f"- 个股周期：`{coverage['audited_cases']}`；股票：`{coverage.get('gap_symbols', '-')}`。",
        f"- 完整 20 日库存窗口：`{coverage['full_inventory_window_cases']}`；部分窗口：`{coverage['partial_inventory_window_cases']}`；库存日期缺口：`{coverage['inventory_date_gap_cases']}`。",
        f"- 词面包含候选：`{coverage['lexical_candidate_cases']}`；命中其他精确概念：`{coverage['other_exact_concept_cases']}`；仅后周期命中目标：`{coverage['postcycle_target_relation_cases']}`。",
        "",
        "## Classifications",
        "",
        "| Dimension | Status | Cases |",
        "| --- | --- | ---: |",
    ]
    for key, value in report["window_coverage_counts"].items():
        lines.append(f"| window | `{key}` | {value} |")
    for key, value in report["stock_evidence_counts"].items():
        lines.append(f"| stock evidence | `{key}` | {value} |")
    for key, value in report["gap_resolution_counts"].items():
        lines.append(f"| resolution | `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Individual Cases",
            "",
            "| Date | Concept | Truth leader | Window | Events/reasons | Other exact concepts | Lexical | Postcycle target | Resolution |",
            "| --- | --- | --- | --- | ---: | --- | --- | --- | --- |",
        ]
    )
    for row in report["case_ledger"]:
        event_count = int(row["sealed_event_count"]) + int(
            row["failed_event_count"]
        )
        lines.append(
            f"| `{row['trade_date']}` | {row['concept_name']} | "
            f"{row['truth_top1_stock_name']} `{row['truth_top1_symbol']}` | "
            f"`{row['window_coverage_status']}` "
            f"({row['inventory_covered_sessions']}/20) | "
            f"{event_count}/{row['reason_event_count']} | "
            f"{_joined(row['other_concept_names'])} | "
            f"{_joined(row['lexical_containment_tokens'])} | "
            f"{_joined(row['postcycle_target_relation_dates'])} | "
            f"`{row['gap_resolution']}` |"
        )
    lines.extend(
        [
            "",
            "## Raw Reason Evidence",
            "",
            "| Date | Target concept | Stock | Observed reason events |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in report["case_ledger"]:
        if not row["reason_events"]:
            continue
        reasons = "；".join(
            f"`{item['source_date']}` {item['reason']}"
            for item in row["reason_events"]
        )
        lines.append(
            f"| `{row['trade_date']}` | {row['concept_name']} | "
            f"{row['truth_top1_stock_name']} `{row['truth_top1_symbol']}` | "
            f"{reasons} |"
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"可信关系排序失败仍为 `{report['credible_ranking_failure_count_before']}`，审计后仍为 `{report['credible_ranking_failure_count_after']}`。",
            "这 23 个案例没有一个获得事前精确关系证据，因此不能用于增加排序权重或反推低吸收益。",
            "",
            "## Boundary",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(
        [
            "",
            "## Reproduce",
            "",
            "```bash",
            str(report["reproduce"]),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _normalize_database_events(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    records = []
    for row in rows:
        event_date = _event_date(row["event_date"])
        if event_date is None:
            raise ValueError("canonical event date is invalid")
        raw = dict(row["raw"] or {})
        reason = str(raw.get("涨停原因") or raw.get("reason_type") or "").strip()
        records.append(
            {
                "event_id": int(row["id"]),
                "source_date": pd.Timestamp(event_date),
                "vt_symbol": str(row["vt_symbol"]),
                "event_type": str(row["event_type"]),
                "source": str(row["source"]),
                "reason": reason,
            }
        )
    return pd.DataFrame(
        records,
        columns=[
            "event_id",
            "source_date",
            "vt_symbol",
            "event_type",
            "source",
            "reason",
        ],
    )


def _ordered_reason_tokens(events: pd.DataFrame) -> tuple[str, ...]:
    seen: set[str] = set()
    tokens = []
    for reason in events["reason"].astype(str):
        for token in reason.split("+"):
            value = token.strip()
            if value and value not in seen:
                seen.add(value)
                tokens.append(value)
    return tuple(tokens)


def _lexical_containment_tokens(
    concept_name: str,
    reason_tokens: Sequence[str],
) -> tuple[str, ...]:
    target = normalize_reason_name(concept_name)
    matches = []
    for token in reason_tokens:
        normalized = normalize_reason_name(token)
        if (
            target != normalized
            and len(target) >= 2
            and len(normalized) >= 2
            and (target in normalized or normalized in target)
        ):
            matches.append(str(token))
    return tuple(dict.fromkeys(matches))


def _event_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if len(text) < 8:
        return None
    try:
        return pd.to_datetime(text[:8], format="%Y%m%d", errors="raise").date()
    except (TypeError, ValueError):
        return None


def _date_tuple(values: pd.Series) -> tuple[date, ...]:
    return tuple(
        sorted({pd.Timestamp(value).date() for value in values.tolist()})
    )


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in frame.to_dict("records")
    ]


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, np.ndarray)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, date)):
        return pd.Timestamp(value).date().isoformat()
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(float(value)) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _value_counts(values: pd.Series) -> dict[str, int]:
    counts = values.fillna("missing").astype(str).value_counts().to_dict()
    return {str(key): int(counts[key]) for key in sorted(counts)}


def _joined(values: Any) -> str:
    if not values:
        return "-"
    return "、".join(str(value) for value in values)


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = sorted(set(columns) - set(frame))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
