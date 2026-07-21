"""Command-line entrypoint for reproducible low-suction research evidence."""

from __future__ import annotations

import argparse
import json
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
    subparsers.add_parser(
        "history-ledger-status",
        help="read the materialized historical replay status without recomputation",
    )
    subparsers.add_parser(
        "history-ledger-materialize",
        help="explicitly recompute the database replay and save its immutable ledger",
    )
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
    true_leader_mismatch_study = subparsers.add_parser(
        "v2-true-leader-mismatch-study",
        help="audit frozen true-leader misses and one exploratory rank",
    )
    true_leader_mismatch_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    true_leader_mismatch_study.add_argument("--output", type=Path)
    true_leader_relation_gap_study = subparsers.add_parser(
        "v2-true-leader-relation-gap-study",
        help="audit unconfirmed true-leader concept relations",
    )
    true_leader_relation_gap_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    true_leader_relation_gap_study.add_argument("--output", type=Path)
    calculated_true_leader_study = subparsers.add_parser(
        "v2-calculated-true-leader-study",
        help="calculate concept relations and leader Top3 from daily prices",
    )
    calculated_true_leader_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    calculated_true_leader_study.add_argument("--output", type=Path)
    dynamic_concept_campaign_study = subparsers.add_parser(
        "v2-dynamic-concept-campaign-study",
        help="compare dynamic concept campaigns and changing leader Top3",
    )
    dynamic_concept_campaign_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    dynamic_concept_campaign_study.add_argument("--output", type=Path)
    daily_leader_spell_date_study = subparsers.add_parser(
        "v2-daily-leader-spell-date-study",
        help="date restart-aware daily concept leaders without future leakage",
    )
    daily_leader_spell_date_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    daily_leader_spell_date_study.add_argument("--output", type=Path)
    stock_wave_case_study = subparsers.add_parser(
        "v2-stock-wave-case-study",
        help="study Xuguang first MA5/MA10/MA20 approaches across its rising waves",
    )
    stock_wave_case_study.add_argument(
        "--campaign",
        choices=("xuguang-2025", "xuguang-2026-continuation"),
        default="xuguang-2025",
    )
    stock_wave_case_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    stock_wave_case_study.add_argument("--output", type=Path)
    cross_leader_wave_study = subparsers.add_parser(
        "v2-cross-leader-wave-study",
        help="apply the frozen Xuguang wave contract to other causal leader proxies",
    )
    cross_leader_wave_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    cross_leader_wave_study.add_argument("--output", type=Path)
    multi_wave_leader_identity_study = subparsers.add_parser(
        "v2-multi-wave-leader-identity-study",
        help="identify resolved second-wave leaders at the first rebreak close",
    )
    multi_wave_leader_identity_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    multi_wave_leader_identity_study.add_argument("--output", type=Path)
    multi_wave_rank_trajectory_study = subparsers.add_parser(
        "v2-multi-wave-rank-trajectory-study",
        help="diagnose daily concept-rank persistence before the first rebreak",
    )
    multi_wave_rank_trajectory_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    multi_wave_rank_trajectory_study.add_argument("--output", type=Path)
    confirmed_multi_wave_pullback_study = subparsers.add_parser(
        "v2-confirmed-multi-wave-pullback-study",
        help="study causal pullbacks after two confirmed higher highs",
    )
    confirmed_multi_wave_pullback_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    confirmed_multi_wave_pullback_study.add_argument("--output", type=Path)
    ma5_case_attribution_study = subparsers.add_parser(
        "v2-ma5-case-attribution-study",
        help="compare every frozen primary MA5 winner and loser stock by stock",
    )
    ma5_case_attribution_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    ma5_case_attribution_study.add_argument("--output", type=Path)
    leader_ma5_manifest = subparsers.add_parser(
        "v2-leader-ma5-scheme-5m-manifest",
        help="audit exact D/D+1 5-minute coverage for the fixed leader MA5 scheme",
    )
    leader_ma5_manifest.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
    )
    leader_ma5_manifest.add_argument("--output", type=Path)
    leader_ma5_backfill = subparsers.add_parser(
        "v2-leader-ma5-scheme-5m-backfill",
        help="backfill exact missing D/D+1 pairs for the fixed leader MA5 scheme",
    )
    leader_ma5_backfill_mode = leader_ma5_backfill.add_mutually_exclusive_group(
        required=True
    )
    leader_ma5_backfill_mode.add_argument("--dry-run", action="store_true")
    leader_ma5_backfill_mode.add_argument("--write", action="store_true")
    leader_ma5_backfill.add_argument("--max-gaps", type=int, default=100)
    leader_ma5_backfill.add_argument("--output", type=Path)
    leader_ma5_study = subparsers.add_parser(
        "v2-leader-ma5-scheme-study",
        help="run the fixed leader MA5 structural and D-tail execution study",
    )
    leader_ma5_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    leader_ma5_study.add_argument("--output", type=Path)
    leader_ma5_close_study = subparsers.add_parser(
        "v2-leader-ma5-close-study",
        help="run the frozen leader MA5 daily-close research proxy",
    )
    leader_ma5_close_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    leader_ma5_close_study.add_argument("--output", type=Path)
    campaign_support_sequence_study = subparsers.add_parser(
        "v2-campaign-support-sequence-study",
        help="study campaign-wide support order and D+1 close failures",
    )
    campaign_support_sequence_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    campaign_support_sequence_study.add_argument("--output", type=Path)
    individual_leader_wave_audit = subparsers.add_parser(
        "v2-individual-leader-wave-audit",
        help="audit every wave and D+1 loss exit in three inspected leaders",
    )
    individual_leader_wave_audit.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    individual_leader_wave_audit.add_argument("--output", type=Path)
    causal_leader_pullback_study = subparsers.add_parser(
        "v2-causal-leader-pullback-study",
        help="run the complete dynamic Top3 main-rise close-pullback algorithm",
    )
    causal_leader_pullback_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    causal_leader_pullback_study.add_argument("--output", type=Path)
    cross_regime_pullback_study = subparsers.add_parser(
        "v3-cross-regime-pullback-study",
        help="validate the phase-routed dynamic Top3 support-reclaim policy",
    )
    cross_regime_pullback_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    cross_regime_pullback_study.add_argument("--output", type=Path)
    cross_regime_product_summary = subparsers.add_parser(
        "v3-cross-regime-product-summary",
        help="compact a frozen cross-regime replay for the read-only API",
    )
    cross_regime_product_summary.add_argument("--source", type=Path, required=True)
    cross_regime_product_summary.add_argument("--output", type=Path)
    warming_failure_study = subparsers.add_parser(
        "v3-warming-failure-study",
        help="attribute V3 warming failures and test one causal support correction",
    )
    warming_failure_study.add_argument("--source", type=Path, required=True)
    warming_failure_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    warming_failure_study.add_argument("--output", type=Path)
    support_contract_study = subparsers.add_parser(
        "v4-support-contract-study",
        help="compare exact MA5/MA10 support with the deeper reclaim contract",
    )
    support_contract_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    support_contract_study.add_argument("--output", type=Path)
    support_day_study = subparsers.add_parser(
        "v5-support-day-study",
        help="freeze and evaluate support-test-day MA5/MA10 close entries",
    )
    support_day_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    support_day_study.add_argument(
        "--input",
        type=Path,
        help="render a saved JSON report without running the database study",
    )
    support_day_study.add_argument("--output", type=Path)
    support_quality_study = subparsers.add_parser(
        "v6-support-quality-study",
        help="test same-day main-rise quality on the frozen exact-support rule",
    )
    support_quality_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    support_quality_study.add_argument(
        "--input",
        type=Path,
        help="render a saved JSON report without running the database study",
    )
    support_quality_study.add_argument("--output", type=Path)
    support_reclaim_confirmation_study = subparsers.add_parser(
        "v7-support-reclaim-confirmation-study",
        help="test the first weak-to-strong close after exact MA5/MA10 support",
    )
    support_reclaim_confirmation_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    support_reclaim_confirmation_study.add_argument(
        "--input",
        type=Path,
        help="render a saved JSON report without running the database study",
    )
    support_reclaim_confirmation_study.add_argument("--output", type=Path)
    leader_tenure_study = subparsers.add_parser(
        "v8-leader-tenure-study",
        help="test persistent causal Top3 tenure with one primary concept",
    )
    leader_tenure_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    leader_tenure_study.add_argument(
        "--input",
        type=Path,
        help="render a saved JSON report without running the database study",
    )
    leader_tenure_study.add_argument("--output", type=Path)
    main_rise_weak_to_strong_study = subparsers.add_parser(
        "v2-main-rise-weak-to-strong-study",
        help="validate dynamic main-rise Top3 divergence-to-strength close entries",
    )
    main_rise_weak_to_strong_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    main_rise_weak_to_strong_study.add_argument("--output", type=Path)
    main_rise_structural_exit_study = subparsers.add_parser(
        "v2-main-rise-structural-exit-study",
        help="validate dynamic main-rise entries with structural swing exits",
    )
    main_rise_structural_exit_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    main_rise_structural_exit_study.add_argument("--output", type=Path)
    prebreakout_ignition_study = subparsers.add_parser(
        "v2-prebreakout-ignition-study",
        help="compare pre-breakout ignition with matched concept controls",
    )
    prebreakout_ignition_study.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    prebreakout_ignition_study.add_argument("--output", type=Path)
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
    forward_ma5_run = subparsers.add_parser(
        "v2-forward-ma5-shadow-run",
        help="advance the strict forward wave-three MA5 research shadow",
    )
    forward_ma5_run.add_argument(
        "--as-of-date",
        type=date.fromisoformat,
        required=True,
    )
    forward_ma5_run.add_argument("--output", type=Path)
    forward_ma5_report = subparsers.add_parser(
        "v2-forward-ma5-shadow-report",
        help="report the immutable forward wave-three MA5 shadow ledger",
    )
    forward_ma5_report.add_argument(
        "--as-of-date",
        type=date.fromisoformat,
    )
    forward_ma5_report.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    forward_ma5_report.add_argument("--output", type=Path)
    cross_regime_forward_run = subparsers.add_parser(
        "v4-cross-regime-forward-run",
        help="capture only today's natural cross-regime causal close and settle outcomes",
    )
    cross_regime_forward_run.add_argument(
        "--as-of-date",
        type=date.fromisoformat,
        required=True,
    )
    cross_regime_forward_run.add_argument("--output", type=Path)
    cross_regime_forward_report = subparsers.add_parser(
        "v4-cross-regime-forward-report",
        help="read the immutable single-identity causal forward ledger",
    )
    cross_regime_forward_report.add_argument(
        "--as-of-date",
        type=date.fromisoformat,
    )
    cross_regime_forward_report.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
    )
    cross_regime_forward_report.add_argument("--output", type=Path)
    cross_regime_recent_audit = subparsers.add_parser(
        "v4-cross-regime-recent-audit",
        help="separate legacy shadow rows from labeled recent causal replays",
    )
    cross_regime_recent_audit.add_argument(
        "--as-of-date",
        type=date.fromisoformat,
        required=True,
    )
    cross_regime_recent_audit.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
    )
    cross_regime_recent_audit.add_argument("--output", type=Path)
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
    requested_output = getattr(args, "output", None)
    output_path = (
        validated_output_path(requested_output)
        if requested_output is not None
        else None
    )
    if args.command == "history-ledger-status":
        from .historical_replay_service import get_historical_replay_overview

        print(
            json.dumps(
                get_historical_replay_overview(),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0
    if args.command == "history-ledger-materialize":
        from .historical_replay_service import (
            materialize_exploratory_three_phase_replay,
        )

        print(
            json.dumps(
                materialize_exploratory_three_phase_replay(),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0
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
    elif args.command == "v2-true-leader-mismatch-study":
        from .true_leader_mismatch_study import (
            render_mismatch_study_json,
            render_mismatch_study_markdown,
            run_true_leader_mismatch_study,
        )

        report = run_true_leader_mismatch_study()
        rendered = (
            render_mismatch_study_json(report)
            if args.format == "json"
            else render_mismatch_study_markdown(report)
        )
    elif args.command == "v2-true-leader-relation-gap-study":
        from .true_leader_relation_gap_study import (
            render_relation_gap_study_json,
            render_relation_gap_study_markdown,
            run_true_leader_relation_gap_study,
        )

        report = run_true_leader_relation_gap_study()
        rendered = (
            render_relation_gap_study_json(report)
            if args.format == "json"
            else render_relation_gap_study_markdown(report)
        )
    elif args.command == "v2-calculated-true-leader-study":
        from .calculated_true_leader_study import (
            render_calculated_true_leader_json,
            render_calculated_true_leader_markdown,
            run_calculated_true_leader_study,
        )

        report = run_calculated_true_leader_study()
        rendered = (
            render_calculated_true_leader_json(report)
            if args.format == "json"
            else render_calculated_true_leader_markdown(report)
        )
    elif args.command == "v2-dynamic-concept-campaign-study":
        from .dynamic_concept_campaign_study import (
            render_dynamic_campaign_json,
            render_dynamic_campaign_markdown,
            run_dynamic_concept_campaign_study,
        )

        report = run_dynamic_concept_campaign_study()
        rendered = (
            render_dynamic_campaign_json(report)
            if args.format == "json"
            else render_dynamic_campaign_markdown(report)
        )
    elif args.command == "v2-daily-leader-spell-date-study":
        from .daily_leader_spell_date_study import (
            render_daily_leader_spell_date_json,
            render_daily_leader_spell_date_markdown,
            run_daily_leader_spell_date_study,
        )

        report = run_daily_leader_spell_date_study()
        rendered = (
            render_daily_leader_spell_date_json(report)
            if args.format == "json"
            else render_daily_leader_spell_date_markdown(report)
        )
    elif args.command == "v2-stock-wave-case-study":
        from .stock_wave_case_study import (
            render_stock_wave_case_json,
            render_stock_wave_case_markdown,
            run_xuguang_2026_continuation_study,
            run_xuguang_wave_case_study,
        )

        report = (
            run_xuguang_2026_continuation_study()
            if args.campaign == "xuguang-2026-continuation"
            else run_xuguang_wave_case_study()
        )
        rendered = (
            render_stock_wave_case_json(report)
            if args.format == "json"
            else render_stock_wave_case_markdown(report)
        )
    elif args.command == "v2-cross-leader-wave-study":
        from .cross_leader_wave_study import (
            render_cross_leader_wave_json,
            render_cross_leader_wave_markdown,
            run_cross_leader_wave_study,
        )

        report = run_cross_leader_wave_study()
        rendered = (
            render_cross_leader_wave_json(report)
            if args.format == "json"
            else render_cross_leader_wave_markdown(report)
        )
    elif args.command == "v2-multi-wave-leader-identity-study":
        from .multi_wave_leader_identity_study import (
            render_multi_wave_identity_json,
            render_multi_wave_identity_markdown,
            run_multi_wave_leader_identity_study,
        )

        report = run_multi_wave_leader_identity_study()
        rendered = (
            render_multi_wave_identity_json(report)
            if args.format == "json"
            else render_multi_wave_identity_markdown(report)
        )
    elif args.command == "v2-multi-wave-rank-trajectory-study":
        from .multi_wave_rank_trajectory_study import (
            render_rank_trajectory_json,
            render_rank_trajectory_markdown,
            run_multi_wave_rank_trajectory_study,
        )

        report = run_multi_wave_rank_trajectory_study()
        rendered = (
            render_rank_trajectory_json(report)
            if args.format == "json"
            else render_rank_trajectory_markdown(report)
        )
    elif args.command == "v2-confirmed-multi-wave-pullback-study":
        from .confirmed_multi_wave_pullback_study import (
            render_confirmed_pullback_json,
            render_confirmed_pullback_markdown,
            run_confirmed_multi_wave_pullback_study,
        )

        report = run_confirmed_multi_wave_pullback_study()
        rendered = (
            render_confirmed_pullback_json(report)
            if args.format == "json"
            else render_confirmed_pullback_markdown(report)
        )
    elif args.command == "v2-ma5-case-attribution-study":
        from .ma5_case_attribution_study import (
            render_ma5_case_attribution_json,
            render_ma5_case_attribution_markdown,
            run_ma5_case_attribution_study,
        )

        report = run_ma5_case_attribution_study()
        rendered = (
            render_ma5_case_attribution_json(report)
            if args.format == "json"
            else render_ma5_case_attribution_markdown(report)
        )
    elif args.command == "v2-leader-ma5-scheme-5m-manifest":
        from .leader_ma5_scheme_minutes import (
            build_scheme_5m_manifest_report,
            load_scheme_5m_manifest,
            render_scheme_5m_manifest_json,
            render_scheme_5m_manifest_markdown,
        )

        report = build_scheme_5m_manifest_report(load_scheme_5m_manifest())
        rendered = (
            render_scheme_5m_manifest_json(report)
            if args.format == "json"
            else render_scheme_5m_manifest_markdown(report)
        )
    elif args.command == "v2-leader-ma5-scheme-5m-backfill":
        from .leader_ma5_scheme_minutes import backfill_missing_scheme_5m

        rendered = render_audit_json(
            backfill_missing_scheme_5m(
                dry_run=not args.write,
                max_gaps=args.max_gaps,
            )
        )
    elif args.command == "v2-leader-ma5-scheme-study":
        from .leader_ma5_scheme_study import (
            render_leader_ma5_scheme_json,
            render_leader_ma5_scheme_markdown,
            run_leader_ma5_scheme_study,
        )

        report = run_leader_ma5_scheme_study()
        rendered = (
            render_leader_ma5_scheme_json(report)
            if args.format == "json"
            else render_leader_ma5_scheme_markdown(report)
        )
    elif args.command == "v2-leader-ma5-close-study":
        from .leader_ma5_close_study import (
            render_leader_ma5_close_json,
            render_leader_ma5_close_markdown,
            run_leader_ma5_close_study,
        )

        report = run_leader_ma5_close_study()
        rendered = (
            render_leader_ma5_close_json(report)
            if args.format == "json"
            else render_leader_ma5_close_markdown(report)
        )
    elif args.command == "v2-campaign-support-sequence-study":
        from .campaign_support_sequence_study import (
            render_campaign_support_sequence_json,
            render_campaign_support_sequence_markdown,
            run_campaign_support_sequence_study,
        )

        report = run_campaign_support_sequence_study()
        rendered = (
            render_campaign_support_sequence_json(report)
            if args.format == "json"
            else render_campaign_support_sequence_markdown(report)
        )
    elif args.command == "v2-individual-leader-wave-audit":
        from .individual_leader_wave_audit import (
            render_individual_leader_wave_json,
            render_individual_leader_wave_markdown,
            run_individual_leader_wave_audit,
        )

        report = run_individual_leader_wave_audit()
        rendered = (
            render_individual_leader_wave_json(report)
            if args.format == "json"
            else render_individual_leader_wave_markdown(report)
        )
    elif args.command in {
        "v2-causal-leader-pullback-study",
        "v3-cross-regime-pullback-study",
    }:
        from .causal_leader_pullback_study import (
            render_causal_leader_pullback_json,
            render_causal_leader_pullback_markdown,
            run_causal_leader_pullback_study,
        )

        report = run_causal_leader_pullback_study()
        rendered = (
            render_causal_leader_pullback_json(report)
            if args.format == "json"
            else render_causal_leader_pullback_markdown(report)
        )
    elif args.command == "v3-cross-regime-product-summary":
        import hashlib

        from .cross_regime_product_report import (
            build_cross_regime_product_report,
            load_json_report,
            render_cross_regime_product_json,
        )

        source = args.source.resolve()
        source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
        report = build_cross_regime_product_report(
            load_json_report(source),
            source_path=str(source.relative_to(Path.cwd())),
            source_sha256=source_digest,
        )
        rendered = render_cross_regime_product_json(report)
    elif args.command == "v3-warming-failure-study":
        import hashlib

        from .cross_regime_warming_failure_study import (
            archive_warming_failure_report,
            render_warming_failure_json,
            render_warming_failure_markdown,
            run_warming_failure_study,
        )

        source = args.source.resolve()
        source_bytes = source.read_bytes()
        report = run_warming_failure_study(
            json.loads(source_bytes),
            source_path=str(source),
            source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        )
        if args.output is not None:
            output_path = validated_output_path(args.output)
            archived = archive_warming_failure_report(report, output_path)
            print(archived["json"])
            print(archived["markdown"])
            return 0
        rendered = (
            render_warming_failure_json(report)
            if args.format == "json"
            else render_warming_failure_markdown(report)
        )
    elif args.command == "v4-support-contract-study":
        from .support_contract_study import (
            render_support_contract_json,
            render_support_contract_markdown,
            run_support_contract_study,
        )

        report = run_support_contract_study()
        rendered = (
            render_support_contract_json(report)
            if args.format == "json"
            else render_support_contract_markdown(report)
        )
    elif args.command == "v5-support-day-study":
        from .support_day_study import (
            render_support_day_json,
            render_support_day_markdown,
            run_support_day_study,
        )

        report = (
            json.loads(args.input.read_text(encoding="utf-8"))
            if args.input is not None
            else run_support_day_study()
        )
        rendered = (
            render_support_day_json(report)
            if args.format == "json"
            else render_support_day_markdown(report)
        )
    elif args.command == "v6-support-quality-study":
        from .support_quality_study import (
            render_support_quality_json,
            render_support_quality_markdown,
            run_support_quality_study,
        )

        report = (
            json.loads(args.input.read_text(encoding="utf-8"))
            if args.input is not None
            else run_support_quality_study()
        )
        rendered = (
            render_support_quality_json(report)
            if args.format == "json"
            else render_support_quality_markdown(report)
        )
    elif args.command == "v7-support-reclaim-confirmation-study":
        from .support_reclaim_confirmation_study import (
            render_support_reclaim_confirmation_json,
            render_support_reclaim_confirmation_markdown,
            run_support_reclaim_confirmation_study,
        )

        report = (
            json.loads(args.input.read_text(encoding="utf-8"))
            if args.input is not None
            else run_support_reclaim_confirmation_study()
        )
        rendered = (
            render_support_reclaim_confirmation_json(report)
            if args.format == "json"
            else render_support_reclaim_confirmation_markdown(report)
        )
    elif args.command == "v8-leader-tenure-study":
        from .leader_tenure_study import (
            render_leader_tenure_json,
            render_leader_tenure_markdown,
            run_leader_tenure_study,
        )

        report = (
            json.loads(args.input.read_text(encoding="utf-8"))
            if args.input is not None
            else run_leader_tenure_study()
        )
        rendered = (
            render_leader_tenure_json(report)
            if args.format == "json"
            else render_leader_tenure_markdown(report)
        )
    elif args.command == "v2-main-rise-weak-to-strong-study":
        from .main_rise_weak_to_strong_study import (
            render_main_rise_weak_to_strong_json,
            render_main_rise_weak_to_strong_markdown,
            run_main_rise_weak_to_strong_study,
        )

        report = run_main_rise_weak_to_strong_study()
        rendered = (
            render_main_rise_weak_to_strong_json(report)
            if args.format == "json"
            else render_main_rise_weak_to_strong_markdown(report)
        )
    elif args.command == "v2-main-rise-structural-exit-study":
        from .main_rise_structural_exit_study import (
            render_main_rise_structural_exit_json,
            render_main_rise_structural_exit_markdown,
            run_main_rise_structural_exit_study,
        )

        report = run_main_rise_structural_exit_study()
        rendered = (
            render_main_rise_structural_exit_json(report)
            if args.format == "json"
            else render_main_rise_structural_exit_markdown(report)
        )
    elif args.command == "v2-prebreakout-ignition-study":
        from .prebreakout_ignition_study import (
            render_prebreakout_json,
            render_prebreakout_markdown,
            run_prebreakout_ignition_study,
        )

        report = run_prebreakout_ignition_study()
        rendered = (
            render_prebreakout_json(report)
            if args.format == "json"
            else render_prebreakout_markdown(report)
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
    elif args.command == "v2-forward-ma5-shadow-run":
        from .forward_ma5_pullback_repository import (
            advance_forward_ma5_shadow,
            render_forward_ma5_json,
        )

        report = advance_forward_ma5_shadow(
            as_of_date=args.as_of_date,
            attempted_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )
        rendered = render_forward_ma5_json(report)
    elif args.command == "v2-forward-ma5-shadow-report":
        from .forward_ma5_pullback_repository import (
            load_forward_ma5_shadow_report,
            render_forward_ma5_json,
            render_forward_ma5_markdown,
        )

        report = load_forward_ma5_shadow_report(as_of_date=args.as_of_date)
        rendered = (
            render_forward_ma5_json(report)
            if args.format == "json"
            else render_forward_ma5_markdown(report)
        )
    elif args.command == "v4-cross-regime-forward-run":
        from .causal_leader_pullback_forward_repository import (
            advance_causal_forward,
            render_causal_forward_json,
        )

        report = advance_causal_forward(
            as_of_date=args.as_of_date,
            attempted_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )
        rendered = render_causal_forward_json(report)
    elif args.command == "v4-cross-regime-forward-report":
        from .causal_leader_pullback_forward_repository import (
            load_causal_forward_report,
            render_causal_forward_json,
            render_causal_forward_markdown,
        )

        report = load_causal_forward_report(as_of_date=args.as_of_date)
        rendered = (
            render_causal_forward_json(report)
            if args.format == "json"
            else render_causal_forward_markdown(report)
        )
    elif args.command == "v4-cross-regime-recent-audit":
        from .cross_regime_recent_candidate_audit import (
            archive_recent_candidate_audit,
            render_recent_candidate_audit_json,
            render_recent_candidate_audit_markdown,
            run_cross_regime_recent_candidate_audit,
        )

        output_path = (
            validated_output_path(args.output)
            if args.output is not None
            else None
        )
        report = run_cross_regime_recent_candidate_audit(
            as_of_date=args.as_of_date,
            evaluated_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )
        if output_path is not None:
            archived = archive_recent_candidate_audit(report, output_path)
            print(archived["json_path"])
            print(archived["markdown_path"])
            return 0
        rendered = (
            render_recent_candidate_audit_json(report)
            if args.format == "json"
            else render_recent_candidate_audit_markdown(report)
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
    if output_path is None:
        print(rendered, end="" if rendered.endswith("\n") else "\n")
        return 0

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
