"""Chronological, return-independent selection of theme eligibility thresholds."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import and_, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import (
    get_engine,
    is_database_configured,
    session_scope,
)

from .contracts import (
    CONCEPT_SECTOR_TYPES,
    STRICT_MIN_CALENDAR_DAYS,
    STRICT_MIN_MEMBERSHIP_COVERAGE_PCT,
    STRICT_MIN_TRADE_DAYS,
)
from .data_quality_repository import load_data_quality_report
from .theme_eligibility import build_theme_features
from .theme_reference_cohorts import ThemeManifestRecord
from .theme_reference_cohorts import (
    MANIFEST_VERSION,
    REFERENCE_MANIFEST,
    validate_manifest_coverage,
)
from .time_split import chronological_split_labels

JACCARD_FLOORS = (0.30, 0.40, 0.50, 0.60, 0.70, 0.80)
SCOPE_FLOORS = (0.90, 0.95, 1.00)
MAX_FALSE_ELIGIBILITY_PCT = 5.0
MIN_THEME_RETENTION_PCT = 70.0
MIN_CLASS_STABILITY_PCT = 90.0


@dataclass(frozen=True)
class ThemeEligibilityRule:
    version: str
    median_jaccard_floor: float
    scope_coverage_floor: float


def run_current_theme_eligibility_audit(
    *,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    if is_database_configured():
        schema.ensure_schema_once(get_engine())
    quality = load_data_quality_report()
    membership = quality["coverage"]["concept_membership"]
    active_sector_ids = _active_concept_ids()
    manifest_report = validate_manifest_coverage(active_sector_ids)
    strict_ready = _strict_membership_ready(membership)
    if not strict_ready:
        return {
            "status": "blocked_by_historical_membership",
            "qualified": False,
            "formal_metrics": None,
            "rule": None,
            "membership_coverage": membership,
            "manifest": manifest_report,
        }
    if not bool(manifest_report["complete"]):
        return {
            "status": "blocked_by_incomplete_manifest",
            "qualified": False,
            "formal_metrics": None,
            "rule": None,
            "membership_coverage": membership,
            "manifest": manifest_report,
        }

    inventory = quality["inventory"]["concept_membership"]
    source = str(inventory.get("selected_source") or "")
    memberships, scopes, board_types = _load_membership_frames(
        source=source,
        start_date=start_date,
        end_date=end_date,
    )
    panel = _build_feature_panel(memberships, scopes, board_types)
    report = run_theme_eligibility_research(
        panel,
        manifest=REFERENCE_MANIFEST,
        strict_membership_ready=True,
    )
    return {
        **report,
        "membership_source": source,
        "membership_coverage": membership,
        "manifest": manifest_report,
        "manifest_version": MANIFEST_VERSION,
        "feature_rows": int(len(panel)),
    }


def render_theme_eligibility_markdown(report: Mapping[str, Any]) -> str:
    rule = report.get("rule") or {}
    manifest = report.get("manifest") or {}
    lines = [
        "# AlphaAgent 低吸题材资格研究",
        "",
        f"结论：`{report.get('status') or 'blocked'}`  ",
        f"合格：`{str(bool(report.get('qualified'))).lower()}`  ",
        "正式策略指标：`null`",
        "",
        "## Manifest",
        "",
        f"- 版本：`{manifest.get('version') or MANIFEST_VERSION}`",
        f"- 活跃板块：`{manifest.get('active_sectors', 0)}`",
        f"- 未分类：`{len(manifest.get('unclassified') or [])}`",
        "",
        "## Frozen Rule",
        "",
    ]
    if rule:
        lines.extend(
            [
                f"- 版本：`{rule.get('version')}`",
                f"- Jaccard 下限：`{rule.get('median_jaccard_floor')}`",
                f"- Scope 覆盖下限：`{rule.get('scope_coverage_floor')}`",
            ]
        )
    else:
        lines.append("- 无；数据或清单门禁尚未通过。")
    return "\n".join(lines) + "\n"


def run_theme_eligibility_research(
    feature_panel: pd.DataFrame,
    *,
    manifest: Mapping[str, ThemeManifestRecord],
    strict_membership_ready: bool,
) -> dict[str, Any]:
    if not strict_membership_ready:
        return {
            "status": "blocked_by_historical_membership",
            "qualified": False,
            "formal_metrics": None,
            "rule": None,
        }
    frame = _normalized_panel(feature_panel, manifest)
    unclassified = sorted(
        set(frame["sector_id"].astype(str)) - set(map(str, manifest))
    )
    if unclassified:
        return {
            "status": "blocked_by_incomplete_manifest",
            "qualified": False,
            "formal_metrics": None,
            "rule": None,
            "unclassified": unclassified,
        }
    labelled = chronological_split_labels(
        frame.rename(columns={"cutoff": "trade_date"})
    ).rename(columns={"trade_date": "cutoff"})
    development = labelled.loc[labelled["time_split"] == "development"].copy()
    validation = labelled.loc[labelled["time_split"] == "validation"].copy()
    holdout = labelled.loc[labelled["time_split"] == "holdout"].copy()
    rule, development_metrics = _select_rule(development)
    if rule is None:
        return {
            "status": "no_qualified_taxonomy",
            "qualified": False,
            "formal_metrics": None,
            "rule": None,
            "development": development_metrics,
            "holdout_rows": int(len(holdout)),
        }
    validation_metrics = _evaluate(validation, rule)
    qualified = _metrics_pass(validation_metrics, require_stability=True)
    return {
        "status": "qualified_taxonomy" if qualified else "taxonomy_failed_validation",
        "qualified": qualified,
        "formal_metrics": None,
        "rule": asdict(rule),
        "development": development_metrics,
        "validation": validation_metrics,
        "holdout_rows": int(len(holdout)),
    }


def classify_with_rule(
    frame: pd.DataFrame,
    rule: ThemeEligibilityRule,
) -> pd.Series:
    narrative = frame["manifest_class"] == "narrative_theme"
    ready = frame["status"] == "ready"
    stable = pd.to_numeric(frame["median_jaccard"], errors="coerce").ge(
        rule.median_jaccard_floor
    )
    complete = pd.to_numeric(frame["scope_coverage"], errors="coerce").ge(
        rule.scope_coverage_floor
    )
    return narrative & ready & stable & complete


def _select_rule(
    development: pd.DataFrame,
) -> tuple[ThemeEligibilityRule | None, dict[str, float]]:
    last_metrics = _empty_metrics()
    for jaccard_floor in JACCARD_FLOORS:
        for scope_floor in SCOPE_FLOORS:
            rule = ThemeEligibilityRule(
                version=(
                    f"theme-eligibility-v1:j{int(jaccard_floor * 100):02d}:"
                    f"s{int(scope_floor * 100):03d}"
                ),
                median_jaccard_floor=jaccard_floor,
                scope_coverage_floor=scope_floor,
            )
            metrics = _evaluate(development, rule)
            last_metrics = metrics
            if _metrics_pass(metrics, require_stability=False):
                return rule, metrics
    return None, last_metrics


def _evaluate(frame: pd.DataFrame, rule: ThemeEligibilityRule) -> dict[str, float]:
    if frame.empty:
        return _empty_metrics()
    evaluated = frame.copy()
    evaluated["eligible"] = classify_with_rule(evaluated, rule)
    narrative = evaluated["manifest_class"] == "narrative_theme"
    controls = evaluated["manifest_class"].isin(
        {"mechanical_event", "style_universe", "report_event", "ambiguous"}
    )
    retention = _rate(evaluated.loc[narrative, "eligible"])
    false_eligibility = _rate(evaluated.loc[controls, "eligible"])
    stability_values: list[bool] = []
    for _, group in evaluated.sort_values("cutoff").groupby("sector_id", sort=True):
        values = group["eligible"].tolist()
        stability_values.extend(
            values[index] == values[index - 1] for index in range(1, len(values))
        )
    stability = (
        round(sum(stability_values) / len(stability_values) * 100.0, 4)
        if stability_values
        else 100.0
    )
    return {
        "narrative_theme_retention_rate": retention,
        "mechanical_or_style_false_eligibility_rate": false_eligibility,
        "class_stability_rate": stability,
    }


def _metrics_pass(metrics: Mapping[str, float], *, require_stability: bool) -> bool:
    return (
        metrics["narrative_theme_retention_rate"] >= MIN_THEME_RETENTION_PCT
        and metrics["mechanical_or_style_false_eligibility_rate"]
        <= MAX_FALSE_ELIGIBILITY_PCT
        and (
            not require_stability
            or metrics["class_stability_rate"] >= MIN_CLASS_STABILITY_PCT
        )
    )


def _normalized_panel(
    frame: pd.DataFrame,
    manifest: Mapping[str, ThemeManifestRecord],
) -> pd.DataFrame:
    required = {
        "cutoff",
        "sector_id",
        "status",
        "median_jaccard",
        "scope_coverage",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"missing theme research columns: {', '.join(missing)}")
    result = frame.copy()
    result["cutoff"] = pd.to_datetime(result["cutoff"], errors="raise").dt.normalize()
    if result.duplicated(["cutoff", "sector_id"]).any():
        raise ValueError("theme feature panel cutoff/sector rows must be unique")
    result["manifest_class"] = result["sector_id"].map(
        lambda sector_id: (
            manifest[str(sector_id)].board_class
            if str(sector_id) in manifest
            else "unlabeled"
        )
    )
    return result


def _rate(values: pd.Series) -> float:
    return round(float(values.mean() * 100.0), 4) if len(values) else 0.0


def _empty_metrics() -> dict[str, float]:
    return {
        "narrative_theme_retention_rate": 0.0,
        "mechanical_or_style_false_eligibility_rate": 0.0,
        "class_stability_rate": 0.0,
    }


def _strict_membership_ready(coverage: Mapping[str, Any]) -> bool:
    return (
        coverage.get("mode") == "strict"
        and int(coverage.get("trade_days") or 0) >= STRICT_MIN_TRADE_DAYS
        and int(coverage.get("calendar_span_days") or 0)
        >= STRICT_MIN_CALENDAR_DAYS
        and float(coverage.get("coverage_pct") or 0.0)
        >= STRICT_MIN_MEMBERSHIP_COVERAGE_PCT
    )


def _active_concept_ids() -> tuple[str, ...]:
    if not is_database_configured():
        return ()
    with session_scope() as session:
        rows = session.execute(
            select(schema.sectors.c.id)
            .where(schema.sectors.c.type.in_(CONCEPT_SECTOR_TYPES))
            .order_by(schema.sectors.c.id)
        ).scalars().all()
    return tuple(str(value) for value in rows)


def _load_membership_frames(
    *,
    source: str,
    start_date: date,
    end_date: date,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str]]:
    if not source:
        raise ValueError("strict membership source is required")
    scopes = schema.low_suction_concept_membership_scopes
    history = schema.low_suction_concept_membership_history
    complete = and_(
        scopes.c.pagination_complete.is_(True),
        scopes.c.expected_member_count == scopes.c.returned_member_count,
    )
    scope_query = (
        select(
            scopes.c.trade_date,
            scopes.c.sector_id,
            complete.label("complete"),
        )
        .where(
            scopes.c.source == source,
            scopes.c.evidence_level == "strict",
            scopes.c.trade_date.between(start_date, end_date),
        )
        .order_by(scopes.c.trade_date, scopes.c.sector_id)
    )
    membership_query = (
        select(
            scopes.c.trade_date,
            scopes.c.sector_id,
            history.c.vt_symbol,
        )
        .select_from(
            scopes.join(
                history,
                and_(
                    history.c.source == scopes.c.source,
                    history.c.evidence_level == scopes.c.evidence_level,
                    history.c.sector_id == scopes.c.sector_id,
                    history.c.in_date <= scopes.c.trade_date,
                    history.c.out_date > scopes.c.trade_date,
                ),
            )
        )
        .where(
            scopes.c.source == source,
            scopes.c.evidence_level == "strict",
            scopes.c.trade_date.between(start_date, end_date),
        )
        .order_by(scopes.c.trade_date, scopes.c.sector_id, history.c.vt_symbol)
    )
    engine = get_engine()
    scope_frame = pd.read_sql(scope_query, engine, parse_dates=["trade_date"])
    membership_frame = pd.read_sql(
        membership_query,
        engine,
        parse_dates=["trade_date"],
    )
    with session_scope() as session:
        board_rows = session.execute(
            select(schema.sectors.c.id, schema.sectors.c.type).where(
                schema.sectors.c.id.in_(
                    tuple(scope_frame["sector_id"].astype(str).unique())
                )
            )
        ).all()
    board_types = {
        str(sector_id): (
            "概念板块" if str(sector_type) in CONCEPT_SECTOR_TYPES else str(sector_type)
        )
        for sector_id, sector_type in board_rows
    }
    return membership_frame, scope_frame, board_types


def _build_feature_panel(
    memberships: pd.DataFrame,
    scopes: pd.DataFrame,
    board_types: Mapping[str, str],
) -> pd.DataFrame:
    if scopes.empty:
        raise ValueError("strict membership scopes are empty")
    dates = tuple(sorted(pd.to_datetime(scopes["trade_date"]).dt.normalize().unique()))
    cutoffs = list(dates[19::20])
    if dates and (not cutoffs or cutoffs[-1] != dates[-1]):
        cutoffs.append(dates[-1])
    frames: list[pd.DataFrame] = []
    for cutoff in cutoffs:
        features = build_theme_features(
            memberships,
            scopes,
            board_types=board_types,
            cutoff=pd.Timestamp(cutoff).date(),
        ).reset_index()
        frames.append(features)
    if len(frames) < 3:
        raise ValueError("at least three theme feature cutoffs are required")
    return pd.concat(frames, ignore_index=True)
