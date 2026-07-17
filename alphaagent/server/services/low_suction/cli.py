"""Command-line entrypoint for reproducible low-suction research evidence."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .data_quality_repository import load_data_quality_report
from .reporting import (
    render_audit_json,
    render_audit_markdown,
    validated_output_path,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="low-suction-research")
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit", help="audit strict historical input coverage")
    audit.add_argument("--format", choices=("json", "markdown"), default="json")
    audit.add_argument("--output", type=Path)
    proxy = subparsers.add_parser(
        "proxy-discovery",
        help="run the bounded current-membership proxy study",
    )
    proxy.add_argument("--start", type=date.fromisoformat)
    proxy.add_argument("--end", type=date.fromisoformat)
    proxy.add_argument("--format", choices=("json", "markdown"), default="markdown")
    proxy.add_argument("--output", type=Path)
    v2_protocol = subparsers.add_parser(
        "v2-protocol",
        help="print the read-only V2 protocol and locked date split",
    )
    v2_protocol.add_argument("--format", choices=("json",), default="json")
    v2_protocol.add_argument("--output", type=Path)
    v2_cycle = subparsers.add_parser(
        "v2-cycle-study",
        help="select a stable concept main-rise definition without stock returns",
    )
    v2_cycle.add_argument("--format", choices=("json", "markdown"), default="markdown")
    v2_cycle.add_argument("--output", type=Path)
    v2_audit = subparsers.add_parser(
        "v2-audit",
        help="show read-only readiness for every V2 research stage",
    )
    v2_audit.add_argument("--format", choices=("json",), default="json")
    v2_audit.add_argument("--output", type=Path)
    event_falsification = subparsers.add_parser(
        "v2-event-falsification",
        help="run the discovery-only event-recognition falsification study",
    )
    event_falsification.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    event_falsification.add_argument("--output", type=Path)
    event_5m_manifest = subparsers.add_parser(
        "v2-event-5m-manifest",
        help="audit candidate-only event-recognition 5-minute coverage",
    )
    event_5m_manifest.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
    )
    event_5m_manifest.add_argument("--output", type=Path)
    event_5m_backfill = subparsers.add_parser(
        "v2-event-5m-backfill",
        help="backfill manifest-discovered event-recognition 5-minute gaps",
    )
    event_5m_backfill_mode = event_5m_backfill.add_mutually_exclusive_group(
        required=True
    )
    event_5m_backfill_mode.add_argument("--dry-run", action="store_true")
    event_5m_backfill_mode.add_argument("--write", action="store_true")
    event_5m_backfill.add_argument("--max-gaps", type=int, default=100)
    event_5m_backfill.add_argument("--output", type=Path)
    event_5m_study = subparsers.add_parser(
        "v2-event-5m-study",
        help="run the frozen event-recognition 5-minute recovery study",
    )
    event_5m_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    event_5m_study.add_argument("--output", type=Path)
    first_divergence = subparsers.add_parser(
        "v2-first-divergence-audit",
        help="audit frozen first-divergence candidates without outcomes",
    )
    first_divergence.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
    )
    first_divergence.add_argument("--output", type=Path)
    first_divergence_manifest = subparsers.add_parser(
        "v2-first-divergence-5m-manifest",
        help="audit first-divergence observation-day 5-minute coverage",
    )
    first_divergence_manifest.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
    )
    first_divergence_manifest.add_argument("--output", type=Path)
    first_divergence_backfill = subparsers.add_parser(
        "v2-first-divergence-5m-backfill",
        help="backfill manifest-discovered first-divergence 5-minute gaps",
    )
    first_divergence_backfill_mode = (
        first_divergence_backfill.add_mutually_exclusive_group(required=True)
    )
    first_divergence_backfill_mode.add_argument("--dry-run", action="store_true")
    first_divergence_backfill_mode.add_argument("--write", action="store_true")
    first_divergence_backfill.add_argument("--max-gaps", type=int, default=100)
    first_divergence_backfill.add_argument("--output", type=Path)
    first_divergence_study = subparsers.add_parser(
        "v2-first-divergence-5m-study",
        help="run the frozen first-divergence 5-minute recovery study",
    )
    first_divergence_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    first_divergence_study.add_argument("--output", type=Path)
    event_neutral = subparsers.add_parser(
        "v2-event-neutral-audit",
        help="audit outcome-neutral event-recognition spell days",
    )
    event_neutral.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
    )
    event_neutral.add_argument("--output", type=Path)
    event_neutral_manifest = subparsers.add_parser(
        "v2-event-neutral-5m-manifest",
        help="audit outcome-neutral event-spell 5-minute coverage",
    )
    event_neutral_manifest.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
    )
    event_neutral_manifest.add_argument("--output", type=Path)
    event_neutral_backfill = subparsers.add_parser(
        "v2-event-neutral-5m-backfill",
        help="backfill manifest-discovered neutral event-spell 5-minute gaps",
    )
    event_neutral_backfill_mode = event_neutral_backfill.add_mutually_exclusive_group(
        required=True
    )
    event_neutral_backfill_mode.add_argument("--dry-run", action="store_true")
    event_neutral_backfill_mode.add_argument("--write", action="store_true")
    event_neutral_backfill.add_argument("--max-gaps", type=int, default=2_000)
    event_neutral_backfill.add_argument("--output", type=Path)
    event_neutral_study = subparsers.add_parser(
        "v2-event-neutral-state-study",
        help="run train-only neutral-state surfaces and bounded discovery",
    )
    event_neutral_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    event_neutral_study.add_argument("--output", type=Path)
    outcome_group_manifest = subparsers.add_parser(
        "v2-outcome-group-5m-manifest",
        help="audit D+1 outcome-group candidate 5-minute coverage",
    )
    outcome_group_manifest.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
    )
    outcome_group_manifest.add_argument("--output", type=Path)
    outcome_group_backfill = subparsers.add_parser(
        "v2-outcome-group-5m-backfill",
        help="backfill manifest-discovered D+1 outcome-group 5-minute gaps",
    )
    outcome_group_backfill_mode = outcome_group_backfill.add_mutually_exclusive_group(
        required=True
    )
    outcome_group_backfill_mode.add_argument("--dry-run", action="store_true")
    outcome_group_backfill_mode.add_argument("--write", action="store_true")
    outcome_group_backfill.add_argument("--max-gaps", type=int, default=2_000)
    outcome_group_backfill.add_argument("--output", type=Path)
    outcome_group_study = subparsers.add_parser(
        "v2-outcome-group-study",
        help="run the frozen D+1 winner/loser group comparison",
    )
    outcome_group_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    outcome_group_study.add_argument("--output", type=Path)
    stock_main_rise_audit = subparsers.add_parser(
        "v2-stock-main-rise-audit",
        help="audit stock-level main-rise hold baselines and old entry MA zones",
    )
    stock_main_rise_audit.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    stock_main_rise_audit.add_argument("--output", type=Path)
    individual_leader_study = subparsers.add_parser(
        "v2-individual-leader-study",
        help="build stock-by-stock main-rise leader spell evidence",
    )
    individual_leader_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    individual_leader_study.add_argument("--output", type=Path)
    daily_phase_study = subparsers.add_parser(
        "v2-daily-phase-study",
        help="study causal daily leader phases and D+1 hold baselines",
    )
    daily_phase_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    daily_phase_study.add_argument("--output", type=Path)
    historical_phase_study = subparsers.add_parser(
        "v2-historical-phase-low-suction-study",
        help="validate historical intraday pullbacks by causal stock phase",
    )
    historical_phase_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    historical_phase_study.add_argument("--output", type=Path)
    ma_pullback_study = subparsers.add_parser(
        "v2-ma-pullback-study",
        help="validate causal first-MA5 and second-MA10 pullback entries",
    )
    ma_pullback_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    ma_pullback_study.add_argument("--output", type=Path)
    cycle_leader_pullback_study = subparsers.add_parser(
        "v2-cycle-leader-pullback-study",
        help="list every observed cycle leader and analyze frozen pullback moments",
    )
    cycle_leader_pullback_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    cycle_leader_pullback_study.add_argument("--output", type=Path)
    cycle_leader_identity_study = subparsers.add_parser(
        "v2-cycle-leader-identity-study",
        help="compare frozen D-1 leader identity modes before pullback outcomes",
    )
    cycle_leader_identity_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    cycle_leader_identity_study.add_argument("--output", type=Path)
    true_leader_wave_study = subparsers.add_parser(
        "v2-true-leader-wave-study",
        help="identify causal concept leaders and ordered higher-high waves",
    )
    true_leader_wave_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    true_leader_wave_study.add_argument("--output", type=Path)
    prelaunch_first_explosion_study = subparsers.add_parser(
        "v2-prelaunch-first-explosion-study",
        help="study D-1 features before verified first strong explosions",
    )
    prelaunch_first_explosion_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    prelaunch_first_explosion_study.add_argument("--output", type=Path)
    tail_feature_study = subparsers.add_parser(
        "v2-tail-feature-study",
        help="compare successful and failed D-tail leader-spell entries",
    )
    tail_feature_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    tail_feature_study.add_argument("--output", type=Path)
    tail_gold_feature_study = subparsers.add_parser(
        "v2-tail-gold-feature-study",
        help="study D-tail leader-spell entries in the fixed D-1 GOLD cohort",
    )
    tail_gold_feature_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    tail_gold_feature_study.add_argument("--output", type=Path)
    forward_top3_freeze = subparsers.add_parser(
        "v2-forward-top3-freeze",
        help="freeze all strict return-independent Top3 modes for one source session",
    )
    forward_top3_freeze.add_argument(
        "--source-date",
        type=date.fromisoformat,
        required=True,
    )
    forward_top3_freeze.add_argument("--output", type=Path)
    forward_top3_report = subparsers.add_parser(
        "v2-forward-top3-report",
        help="report the immutable forward Top3 identity ledger",
    )
    forward_top3_report.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    forward_top3_report.add_argument("--output", type=Path)
    minute = subparsers.add_parser(
        "minute-manifest",
        help="audit candidate-only minute gaps from the bounded proxy study",
    )
    minute.add_argument("--start", type=date.fromisoformat)
    minute.add_argument("--end", type=date.fromisoformat)
    minute.add_argument("--format", choices=("json", "csv"), default="json")
    minute.add_argument("--output", type=Path)
    security = subparsers.add_parser(
        "security-master-audit",
        help="compare BaoStock's reconstructed stock master with local stocks",
    )
    security.add_argument("--format", choices=("json", "markdown"), default="json")
    security.add_argument("--output", type=Path)
    source_status = subparsers.add_parser(
        "membership-source-status",
        help="show Tushare DC historical-membership configuration without secrets",
    )
    source_status.add_argument("--output", type=Path)
    probe = subparsers.add_parser(
        "membership-probe",
        help="run a bounded read-only Tushare DC membership probe",
    )
    _add_membership_range_arguments(probe, default_max_dates=5)
    backfill = subparsers.add_parser(
        "membership-backfill",
        help="validate or atomically replace Tushare DC membership history",
    )
    _add_membership_range_arguments(backfill, default_max_dates=800)
    write_mode = backfill.add_mutually_exclusive_group(required=True)
    write_mode.add_argument("--dry-run", action="store_true")
    write_mode.add_argument("--write", action="store_true")
    theme = subparsers.add_parser(
        "theme-eligibility-research",
        help="run the return-independent historical theme taxonomy audit",
    )
    theme.add_argument("--start", type=date.fromisoformat, required=True)
    theme.add_argument("--end", type=date.fromisoformat, required=True)
    theme.add_argument("--format", choices=("json", "markdown"), default="json")
    theme.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "audit":
        report = load_data_quality_report()
        rendered = (
            render_audit_json(report)
            if args.format == "json"
            else render_audit_markdown(report)
        )
    elif args.command == "proxy-discovery":
        from .daily_discovery import run_membership_proxy_discovery
        from .proxy_reporting import (
            build_proxy_evidence,
            render_proxy_json,
            render_proxy_markdown,
        )
        from .repository import load_proxy_research_inputs

        inputs = load_proxy_research_inputs(start=args.start, end=args.end)
        result = run_membership_proxy_discovery(inputs)
        evidence = build_proxy_evidence(
            result.events,
            result.outcomes,
            result.stressed_outcomes,
            coverage=inputs.coverage,
        )
        rendered = (
            render_proxy_json(evidence)
            if args.format == "json"
            else render_proxy_markdown(evidence)
        )
    elif args.command == "v2-protocol":
        from .concept_cycles import load_cycle_research_calendar
        from .research_protocol import (
            build_protocol_split,
            default_protocol,
            protocol_payload,
        )

        protocol = default_protocol()
        split = build_protocol_split(load_cycle_research_calendar(), protocol)
        rendered = render_audit_json(protocol_payload(protocol, split))
    elif args.command == "v2-cycle-study":
        from .concept_cycles import (
            render_cycle_study_json,
            render_cycle_study_markdown,
            run_current_cycle_study,
        )

        report = run_current_cycle_study()
        rendered = (
            render_cycle_study_json(report)
            if args.format == "json"
            else render_cycle_study_markdown(report)
        )
    elif args.command == "v2-audit":
        from .v2_audit import load_v2_stage_audit

        rendered = render_audit_json(load_v2_stage_audit())
    elif args.command == "v2-event-falsification":
        from .event_recognition_falsification import (
            render_event_falsification_json,
            render_event_falsification_markdown,
            run_event_recognition_falsification,
        )

        report = run_event_recognition_falsification()
        rendered = (
            render_event_falsification_json(report)
            if args.format == "json"
            else render_event_falsification_markdown(report)
        )
    elif args.command == "v2-event-5m-manifest":
        from .event_recognition_minutes import (
            build_event_5m_manifest_report,
            load_event_5m_manifest,
            render_event_5m_manifest_json,
            render_event_5m_manifest_markdown,
        )

        report = build_event_5m_manifest_report(load_event_5m_manifest())
        rendered = (
            render_event_5m_manifest_json(report)
            if args.format == "json"
            else render_event_5m_manifest_markdown(report)
        )
    elif args.command == "v2-event-5m-backfill":
        from .event_recognition_minutes import backfill_missing_event_5m

        rendered = render_audit_json(
            backfill_missing_event_5m(
                dry_run=not args.write,
                max_gaps=args.max_gaps,
            )
        )
    elif args.command == "v2-event-5m-study":
        from .event_recognition_5m_study import (
            render_event_5m_study_json,
            render_event_5m_study_markdown,
            run_event_5m_state_study,
        )

        report = run_event_5m_state_study()
        rendered = (
            render_event_5m_study_json(report)
            if args.format == "json"
            else render_event_5m_study_markdown(report)
        )
    elif args.command == "v2-first-divergence-audit":
        from .first_divergence import (
            render_first_divergence_audit_json,
            render_first_divergence_audit_markdown,
            run_first_divergence_candidate_audit,
        )

        report = run_first_divergence_candidate_audit()
        rendered = (
            render_first_divergence_audit_json(report)
            if args.format == "json"
            else render_first_divergence_audit_markdown(report)
        )
    elif args.command == "v2-first-divergence-5m-manifest":
        from .first_divergence_minutes import (
            build_first_divergence_5m_manifest_report,
            load_first_divergence_5m_manifest,
            render_first_divergence_5m_manifest_json,
            render_first_divergence_5m_manifest_markdown,
        )

        report = build_first_divergence_5m_manifest_report(
            load_first_divergence_5m_manifest()
        )
        rendered = (
            render_first_divergence_5m_manifest_json(report)
            if args.format == "json"
            else render_first_divergence_5m_manifest_markdown(report)
        )
    elif args.command == "v2-first-divergence-5m-backfill":
        from .first_divergence_minutes import (
            backfill_missing_first_divergence_5m,
        )

        rendered = render_audit_json(
            backfill_missing_first_divergence_5m(
                dry_run=not args.write,
                max_gaps=args.max_gaps,
            )
        )
    elif args.command == "v2-first-divergence-5m-study":
        from .first_divergence_5m_study import (
            render_first_divergence_5m_json,
            render_first_divergence_5m_markdown,
            run_first_divergence_5m_study,
        )

        report = run_first_divergence_5m_study()
        rendered = (
            render_first_divergence_5m_json(report)
            if args.format == "json"
            else render_first_divergence_5m_markdown(report)
        )
    elif args.command == "v2-event-neutral-audit":
        from .event_neutral_days import (
            render_event_neutral_audit_json,
            render_event_neutral_audit_markdown,
            run_event_neutral_candidate_audit,
        )

        report = run_event_neutral_candidate_audit()
        rendered = (
            render_event_neutral_audit_json(report)
            if args.format == "json"
            else render_event_neutral_audit_markdown(report)
        )
    elif args.command == "v2-event-neutral-5m-manifest":
        from .event_neutral_minutes import (
            build_event_neutral_5m_manifest_report,
            load_event_neutral_5m_manifest,
            render_event_neutral_5m_manifest_json,
            render_event_neutral_5m_manifest_markdown,
        )

        report = build_event_neutral_5m_manifest_report(
            load_event_neutral_5m_manifest()
        )
        rendered = (
            render_event_neutral_5m_manifest_json(report)
            if args.format == "json"
            else render_event_neutral_5m_manifest_markdown(report)
        )
    elif args.command == "v2-event-neutral-5m-backfill":
        from .event_neutral_minutes import backfill_missing_event_neutral_5m

        rendered = render_audit_json(
            backfill_missing_event_neutral_5m(
                dry_run=not args.write,
                max_gaps=args.max_gaps,
            )
        )
    elif args.command == "v2-event-neutral-state-study":
        from .event_neutral_discovery import (
            render_event_neutral_state_json,
            render_event_neutral_state_markdown,
            run_event_neutral_state_study,
        )

        report = run_event_neutral_state_study()
        rendered = (
            render_event_neutral_state_json(report)
            if args.format == "json"
            else render_event_neutral_state_markdown(report)
        )
    elif args.command == "v2-outcome-group-5m-manifest":
        from .outcome_group_minutes import (
            build_outcome_group_5m_manifest_report,
            load_outcome_group_5m_manifest,
            render_outcome_group_5m_manifest_json,
            render_outcome_group_5m_manifest_markdown,
        )

        report = build_outcome_group_5m_manifest_report(
            load_outcome_group_5m_manifest()
        )
        rendered = (
            render_outcome_group_5m_manifest_json(report)
            if args.format == "json"
            else render_outcome_group_5m_manifest_markdown(report)
        )
    elif args.command == "v2-outcome-group-5m-backfill":
        from .outcome_group_minutes import backfill_missing_outcome_group_5m

        rendered = render_audit_json(
            backfill_missing_outcome_group_5m(
                dry_run=not args.write,
                max_gaps=args.max_gaps,
            )
        )
    elif args.command == "v2-outcome-group-study":
        from .outcome_group_study import (
            render_outcome_group_json,
            render_outcome_group_markdown,
            run_outcome_group_study,
        )

        report = run_outcome_group_study()
        rendered = (
            render_outcome_group_json(report)
            if args.format == "json"
            else render_outcome_group_markdown(report)
        )
    elif args.command == "v2-stock-main-rise-audit":
        from .stock_main_rise_audit import (
            render_stock_main_rise_json,
            render_stock_main_rise_markdown,
            run_stock_main_rise_audit,
        )

        report = run_stock_main_rise_audit()
        rendered = (
            render_stock_main_rise_json(report)
            if args.format == "json"
            else render_stock_main_rise_markdown(report)
        )
    elif args.command == "v2-individual-leader-study":
        from .individual_leader_study import (
            render_individual_leader_json,
            render_individual_leader_markdown,
            run_individual_leader_study,
        )

        report = run_individual_leader_study()
        rendered = (
            render_individual_leader_json(report)
            if args.format == "json"
            else render_individual_leader_markdown(report)
        )
    elif args.command == "v2-daily-phase-study":
        from .daily_phase_study import (
            render_daily_phase_json,
            render_daily_phase_markdown,
            run_daily_phase_study,
        )

        report = run_daily_phase_study()
        rendered = (
            render_daily_phase_json(report)
            if args.format == "json"
            else render_daily_phase_markdown(report)
        )
    elif args.command == "v2-historical-phase-low-suction-study":
        from .historical_phase_low_suction_study import (
            render_historical_phase_json,
            render_historical_phase_markdown,
            run_historical_phase_low_suction_study,
        )

        report = run_historical_phase_low_suction_study()
        rendered = (
            render_historical_phase_json(report)
            if args.format == "json"
            else render_historical_phase_markdown(report)
        )
    elif args.command == "v2-ma-pullback-study":
        from .ma_pullback_study import (
            render_ma_pullback_json,
            render_ma_pullback_markdown,
            run_ma_pullback_study,
        )

        report = run_ma_pullback_study()
        rendered = (
            render_ma_pullback_json(report)
            if args.format == "json"
            else render_ma_pullback_markdown(report)
        )
    elif args.command == "v2-cycle-leader-pullback-study":
        from .leader_pullback_moment_study import (
            render_cycle_leader_pullback_json,
            render_cycle_leader_pullback_markdown,
            run_cycle_leader_pullback_study,
        )

        report = run_cycle_leader_pullback_study()
        rendered = (
            render_cycle_leader_pullback_json(report)
            if args.format == "json"
            else render_cycle_leader_pullback_markdown(report)
        )
    elif args.command == "v2-cycle-leader-identity-study":
        from .cycle_leader_identity_study import (
            render_cycle_leader_identity_json,
            render_cycle_leader_identity_markdown,
            run_cycle_leader_identity_study,
        )

        report = run_cycle_leader_identity_study()
        rendered = (
            render_cycle_leader_identity_json(report)
            if args.format == "json"
            else render_cycle_leader_identity_markdown(report)
        )
    elif args.command == "v2-true-leader-wave-study":
        from .true_leader_study import (
            render_true_leader_study_json,
            render_true_leader_study_markdown,
            run_true_leader_wave_study,
        )

        report = run_true_leader_wave_study()
        rendered = (
            render_true_leader_study_json(report)
            if args.format == "json"
            else render_true_leader_study_markdown(report)
        )
    elif args.command == "v2-prelaunch-first-explosion-study":
        from .prelaunch_first_explosion_study import (
            render_prelaunch_first_explosion_json,
            render_prelaunch_first_explosion_markdown,
            run_prelaunch_first_explosion_study,
        )

        report = run_prelaunch_first_explosion_study()
        rendered = (
            render_prelaunch_first_explosion_json(report)
            if args.format == "json"
            else render_prelaunch_first_explosion_markdown(report)
        )
    elif args.command == "v2-tail-feature-study":
        from .tail_feature_study import (
            render_tail_feature_json,
            render_tail_feature_markdown,
            run_tail_feature_study,
        )

        report = run_tail_feature_study()
        rendered = (
            render_tail_feature_json(report)
            if args.format == "json"
            else render_tail_feature_markdown(report)
        )
    elif args.command == "v2-tail-gold-feature-study":
        from .tail_feature_study import (
            render_tail_feature_json,
            render_tail_feature_markdown,
        )
        from .tail_gold_feature_study import run_gold_tail_feature_study

        report = run_gold_tail_feature_study()
        rendered = (
            render_tail_feature_json(report)
            if args.format == "json"
            else render_tail_feature_markdown(report)
        )
    elif args.command == "v2-forward-top3-freeze":
        from .forward_leader_identity import (
            freeze_forward_leader_source,
            render_forward_leader_report_json,
        )

        report = freeze_forward_leader_source(
            args.source_date,
            attempted_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )
        rendered = render_forward_leader_report_json(report)
    elif args.command == "v2-forward-top3-report":
        from .forward_leader_identity import (
            render_forward_leader_report_json,
            render_forward_leader_report_markdown,
        )
        from .forward_leader_identity_repository import (
            load_forward_leader_ledger_report,
        )

        report = load_forward_leader_ledger_report()
        rendered = (
            render_forward_leader_report_json(report)
            if args.format == "json"
            else render_forward_leader_report_markdown(report)
        )
    elif args.command == "minute-manifest":
        from .daily_discovery import run_membership_proxy_discovery
        from .minute_manifest import (
            build_candidate_minute_manifest,
            load_existing_candidate_minutes,
            render_minute_manifest_csv,
            render_minute_manifest_json,
        )
        from .repository import load_proxy_research_inputs

        inputs = load_proxy_research_inputs(start=args.start, end=args.end)
        result = run_membership_proxy_discovery(inputs)
        events = result.events.loc[
            result.events["cohort"] == "main_rise_top3"
        ].copy()
        minute_bars = load_existing_candidate_minutes(events)
        manifest = build_candidate_minute_manifest(events, minute_bars)
        rendered = (
            render_minute_manifest_json(manifest)
            if args.format == "json"
            else render_minute_manifest_csv(manifest)
        )
    elif args.command == "security-master-audit":
        from .security_master_audit import (
            load_security_master_audit,
            render_security_master_audit_json,
            render_security_master_audit_markdown,
        )

        report = load_security_master_audit()
        rendered = (
            render_security_master_audit_json(report)
            if args.format == "json"
            else render_security_master_audit_markdown(report)
        )
    elif args.command == "membership-source-status":
        from .dc_membership_import import membership_source_status

        rendered = render_audit_json(membership_source_status())
    elif args.command in {"membership-probe", "membership-backfill"}:
        from .dc_membership_import import run_dc_membership_import

        report = run_dc_membership_import(
            start_date=args.start,
            end_date=args.end,
            max_dates=args.max_dates,
            dry_run=(args.command == "membership-probe" or not args.write),
        )
        rendered = render_audit_json(report)
    elif args.command == "theme-eligibility-research":
        from .theme_eligibility_research import (
            render_theme_eligibility_markdown,
            run_current_theme_eligibility_audit,
        )

        report = run_current_theme_eligibility_audit(
            start_date=args.start,
            end_date=args.end,
        )
        rendered = (
            render_audit_json(report)
            if args.format == "json"
            else render_theme_eligibility_markdown(report)
        )
    else:
        raise ValueError(f"unsupported command: {args.command}")
    if args.output is None:
        print(rendered, end="" if rendered.endswith("\n") else "\n")
        return 0

    output_path = validated_output_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    print(output_path)
    return 0


def _add_membership_range_arguments(
    parser: argparse.ArgumentParser,
    *,
    default_max_dates: int,
) -> None:
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--max-dates", type=int, default=default_max_dates)
    parser.add_argument("--format", choices=("json",), default="json")
    parser.add_argument("--output", type=Path)


if __name__ == "__main__":
    raise SystemExit(main())
