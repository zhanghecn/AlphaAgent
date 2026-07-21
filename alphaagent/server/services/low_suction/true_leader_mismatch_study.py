"""Mismatch attribution for the frozen true-leader wave study."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


FROZEN_REPORT_PATH = Path(
    "memory/06_backtests/low_suction_true_leader_wave_study_20260717.json"
)
FROZEN_REPORT_SHA256 = (
    "c0aeca850a7b58ef651497a6dd2a24751cedfc3c210a9e5c172acff5ad82b48f"
)
FROZEN_STUDY_VERSION = "true-leader-wave-identification-v1"
MIN_TOP1_EXACT_RATE_PCT = 30.0
MIN_TOP3_CAPTURE_RATE_PCT = 60.0
MIN_TOP3_OVERLAP_PCT = 50.0
NEAR_DUPLICATE_JACCARD = 0.80
PROHIBITED_RANK_TOKENS = (
    "truth_",
    "future_",
    "net_return",
    "gross_return",
    "entry_price",
    "exit_price",
    "mfe",
    "mae",
    "outcome",
)


@dataclass(frozen=True)
class TrueLeaderMismatchInputs:
    prior_report: dict[str, Any]
    frozen_truth: pd.DataFrame
    cycle_rows: pd.DataFrame
    candidates: pd.DataFrame
    memberships: pd.DataFrame
    reason_relations: pd.DataFrame
    trading_dates: tuple[date, ...]
    coverage: dict[str, Any]
    fingerprints: dict[str, dict[str, Any]]


def load_frozen_true_leader_report(
    path: Path = FROZEN_REPORT_PATH,
) -> dict[str, Any]:
    """Load only the exact prior report frozen for this audit."""

    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != FROZEN_REPORT_SHA256:
        raise ValueError(
            f"frozen true-leader report SHA256 mismatch: {digest}"
        )
    try:
        report = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("frozen true-leader report is not valid JSON") from exc
    if report.get("study_version") != FROZEN_STUDY_VERSION:
        raise ValueError("unexpected frozen true-leader study version")
    if report.get("formal_metrics") is not None:
        raise ValueError("frozen report must not contain formal metrics")
    if report.get("formal_selected_mode") is not None:
        raise ValueError("frozen report must not select a formal mode")
    return report


def build_frozen_truth_ledger(report: Mapping[str, Any]) -> pd.DataFrame:
    """Expand every cycle's immutable causal and truth Top3 identities."""

    if report.get("study_version") != FROZEN_STUDY_VERSION:
        raise ValueError("unexpected frozen true-leader study version")
    cycles = report.get("cycle_summaries")
    if not isinstance(cycles, list) or not cycles:
        raise ValueError("frozen report has no cycle summaries")
    seen_cycles: set[str] = set()
    rows: list[dict[str, Any]] = []
    for cycle in cycles:
        cycle_id = str(cycle.get("cycle_id") or "")
        if not cycle_id or cycle_id in seen_cycles:
            raise ValueError("frozen cycle IDs must be non-empty and unique")
        seen_cycles.add(cycle_id)
        causal = _validate_leader_list(
            cycle.get("causal_top3"),
            "causal",
            require_complete=False,
        )
        truth = _validate_leader_list(
            cycle.get("truth_top3"),
            "truth",
            require_complete=True,
        )
        causal_by_symbol = {
            str(item["vt_symbol"]): int(item["rank"]) for item in causal
        }
        causal_symbols = tuple(
            str(item["vt_symbol"])
            for item in sorted(causal, key=lambda item: int(item["rank"]))
        )
        causal_ranked_symbols = tuple(
            (int(item["rank"]), str(item["vt_symbol"]))
            for item in sorted(causal, key=lambda item: int(item["rank"]))
        )
        truth_top1 = str(
            next(item for item in truth if int(item["rank"]) == 1)["vt_symbol"]
        )
        captured = truth_top1 in causal_by_symbol
        if bool(cycle.get("causal_top3_captured_truth_top1")) != captured:
            raise ValueError("frozen cycle capture flag conflicts with identities")
        for item in sorted(truth, key=lambda value: int(value["rank"])):
            symbol = str(item["vt_symbol"])
            rows.append(
                {
                    "cycle_id": cycle_id,
                    "trade_date": pd.Timestamp(cycle["trade_date"]).normalize(),
                    "sector_id": str(cycle["sector_id"]),
                    "concept_name": str(cycle.get("concept_name") or ""),
                    "candidate_count": int(cycle["candidate_count"]),
                    "captured": captured,
                    "causal_top3_symbols": causal_symbols,
                    "frozen_causal_ranked_symbols": causal_ranked_symbols,
                    "frozen_causal_top3_reported_count": len(causal),
                    "truth_rank": int(item["rank"]),
                    "vt_symbol": symbol,
                    "stock_name": str(item.get("stock_name") or ""),
                    "frozen_causal_rank": causal_by_symbol.get(symbol),
                    "frozen_causal_top3": symbol in causal_by_symbol,
                    "future_wave_count": _finite_or_none(
                        item.get("future_wave_count")
                    ),
                    "future_40d_max_excess_pct": _finite_or_none(
                        item.get("future_40d_max_excess_pct")
                    ),
                }
            )
    result = pd.DataFrame(rows)
    if result.duplicated(["cycle_id", "truth_rank"]).any():
        raise ValueError("frozen truth ranks must be unique within every cycle")
    return result.sort_values(
        ["trade_date", "sector_id", "truth_rank"], kind="stable"
    ).reset_index(drop=True)


def build_cycle_audit_rows(frozen_truth: pd.DataFrame) -> pd.DataFrame:
    """Collapse frozen truth rows into one immutable row per cycle."""

    _require_columns(
        frozen_truth,
        (
            "cycle_id",
            "trade_date",
            "sector_id",
            "concept_name",
            "candidate_count",
            "captured",
            "causal_top3_symbols",
            "frozen_causal_ranked_symbols",
            "frozen_causal_top3_reported_count",
            "truth_rank",
            "vt_symbol",
            "stock_name",
        ),
        "frozen truth",
    )
    top1 = frozen_truth.loc[frozen_truth["truth_rank"].eq(1)].copy()
    if top1["cycle_id"].duplicated().any():
        raise ValueError("every cycle must have exactly one truth Top1")
    return top1.rename(
        columns={
            "vt_symbol": "truth_top1_symbol",
            "stock_name": "truth_top1_stock_name",
        }
    ).loc[
        :,
        [
            "cycle_id",
            "trade_date",
            "sector_id",
            "concept_name",
            "candidate_count",
            "captured",
            "truth_top1_symbol",
            "truth_top1_stock_name",
            "causal_top3_symbols",
            "frozen_causal_ranked_symbols",
            "frozen_causal_top3_reported_count",
        ],
    ].reset_index(drop=True)


def validate_frozen_candidate_rebuild(
    candidates: pd.DataFrame,
    frozen_truth: pd.DataFrame,
) -> None:
    """Fail closed unless the causal candidate rebuild matches frozen identities."""

    _require_columns(
        candidates,
        (
            "cycle_id",
            "trade_date",
            "sector_id",
            "vt_symbol",
            "causal_rank",
            "baseline_rank",
        ),
        "rebuilt candidate",
    )
    _require_columns(
        frozen_truth,
        (
            "cycle_id",
            "trade_date",
            "sector_id",
            "candidate_count",
            "causal_top3_symbols",
            "frozen_causal_ranked_symbols",
        ),
        "frozen truth",
    )
    candidate_cycles = set(candidates["cycle_id"].astype(str))
    frozen_cycles = set(frozen_truth["cycle_id"].astype(str))
    if candidate_cycles != frozen_cycles:
        raise ValueError("rebuilt candidates do not cover the frozen cycle universe")
    if candidates.duplicated(["cycle_id", "vt_symbol"]).any():
        raise ValueError("rebuilt candidate identities must be unique")

    frozen_cycles_frame = frozen_truth.drop_duplicates("cycle_id").set_index(
        "cycle_id"
    )
    for cycle_id, group in candidates.groupby("cycle_id", sort=False):
        frozen = frozen_cycles_frame.loc[str(cycle_id)]
        expected_count = int(frozen["candidate_count"])
        if len(group) < expected_count:
            raise ValueError(
                f"rebuilt candidate count is below frozen complete rows for {cycle_id}: "
                f"{len(group)} < {expected_count}"
            )
        trade_dates = pd.to_datetime(group["trade_date"], errors="raise").dt.normalize()
        if not trade_dates.eq(pd.Timestamp(frozen["trade_date"]).normalize()).all():
            raise ValueError(f"rebuilt trade date changed for {cycle_id}")
        if not group["sector_id"].astype(str).eq(str(frozen["sector_id"])).all():
            raise ValueError(f"rebuilt sector changed for {cycle_id}")

        causal_ranks = pd.to_numeric(group["causal_rank"], errors="raise")
        baseline_ranks = pd.to_numeric(group["baseline_rank"], errors="raise")
        rebuilt_count = len(group)
        expected_ranks = set(range(1, rebuilt_count + 1))
        if set(causal_ranks.astype(int)) != expected_ranks:
            raise ValueError(f"rebuilt causal ranks are invalid for {cycle_id}")
        if set(baseline_ranks.astype(int)) != expected_ranks:
            raise ValueError(f"rebuilt baseline ranks are invalid for {cycle_id}")
        actual_by_rank = {
            int(row["causal_rank"]): str(row["vt_symbol"])
            for row in group.to_dict("records")
            if int(row["causal_rank"]) <= 3
        }
        expected_ranked = tuple(frozen["frozen_causal_ranked_symbols"])
        for rank, symbol in expected_ranked:
            if actual_by_rank.get(int(rank)) != str(symbol):
                raise ValueError(
                    f"rebuilt causal Top3 changed for {cycle_id} rank {rank}: "
                    f"{actual_by_rank.get(int(rank))} != {symbol}"
                )


def load_true_leader_mismatch_inputs(
    report_path: Path = FROZEN_REPORT_PATH,
) -> TrueLeaderMismatchInputs:
    """Rebuild discovery-only ranks and attach the immutable truth universe."""

    from .research_protocol import fingerprint_frame
    from .true_leader_study import (
        build_emotion_cycle_candidates,
        build_point_in_time_stock_features,
        load_true_leader_study_inputs,
        rank_causal_cycle_leaders,
    )

    prior_report = load_frozen_true_leader_report(report_path)
    frozen_truth = build_frozen_truth_ledger(prior_report)
    cycle_rows = build_cycle_audit_rows(frozen_truth)

    source_inputs = load_true_leader_study_inputs(include_reference_bars=False)
    _validate_frozen_input_fingerprints(
        source_inputs.fingerprints,
        prior_report.get("fingerprints"),
    )
    stock_features = build_point_in_time_stock_features(source_inputs.stock_bars)
    all_candidates = build_emotion_cycle_candidates(
        source_inputs.cycle_starts,
        source_inputs.memberships,
        stock_features,
    )
    all_ranks = rank_causal_cycle_leaders(all_candidates)
    frozen_cycle_ids = set(frozen_truth["cycle_id"].astype(str))
    candidates = all_ranks.loc[
        all_ranks["cycle_id"].astype(str).isin(frozen_cycle_ids)
    ].copy()
    validate_frozen_candidate_rebuild(candidates, frozen_truth)
    cycle_rows = _attach_rebuilt_causal_top3(cycle_rows, candidates)
    candidates = rank_active_consensus(candidates)

    candidate_fingerprint = fingerprint_frame(
        candidates,
        identity_columns=("cycle_id", "vt_symbol"),
    ).as_dict()
    coverage = {
        **source_inputs.coverage,
        "frozen_report_path": str(report_path),
        "frozen_report_sha256": FROZEN_REPORT_SHA256,
        "frozen_truth_cycles": int(frozen_truth["cycle_id"].nunique()),
        "rebuilt_candidate_rows": int(len(candidates)),
        "rebuilt_candidate_symbols": int(candidates["vt_symbol"].nunique()),
        "rebuilt_cycle_count": int(candidates["cycle_id"].nunique()),
        "frozen_causal_top3_incomplete_cycles": int(
            cycle_rows["causal_top3_reconstructed"].astype(bool).sum()
        ),
    }
    fingerprints = {
        **source_inputs.fingerprints,
        "frozen_report": {
            "algorithm": "sha256",
            "digest": f"sha256:{FROZEN_REPORT_SHA256}",
            "rows": int(frozen_truth["cycle_id"].nunique()),
            "columns": ["cycle_summaries"],
        },
        "rebuilt_frozen_candidates": candidate_fingerprint,
    }
    return TrueLeaderMismatchInputs(
        prior_report=prior_report,
        frozen_truth=frozen_truth,
        cycle_rows=cycle_rows,
        candidates=candidates,
        memberships=source_inputs.memberships,
        reason_relations=source_inputs.reason_relations,
        trading_dates=source_inputs.trading_dates,
        coverage=coverage,
        fingerprints=fingerprints,
    )


def attach_relation_risk(
    cycles: pd.DataFrame,
    reason_relations: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
    source_start: date | None,
) -> pd.DataFrame:
    """Classify causal reason evidence without treating absence as false."""

    _require_columns(
        cycles,
        (
            "cycle_id",
            "trade_date",
            "sector_id",
            "truth_top1_symbol",
            "causal_top3_symbols",
        ),
        "cycle audit",
    )
    relation_columns = (
        "source_date",
        "sector_id",
        "vt_symbol",
        "relation_method",
    )
    _require_columns(reason_relations, relation_columns, "reason relation")
    calendar = tuple(sorted(set(pd.to_datetime(tuple(trading_dates)).normalize())))
    positions = {value: index for index, value in enumerate(calendar)}
    relations = reason_relations.loc[:, list(relation_columns)].copy()
    relations["source_date"] = pd.to_datetime(
        relations["source_date"], errors="raise"
    ).dt.normalize()
    relation_groups = {
        (str(sector_id), str(symbol)): group.sort_values(
            ["source_date", "relation_method"], kind="stable"
        )
        for (sector_id, symbol), group in relations.groupby(
            ["sector_id", "vt_symbol"], sort=False
        )
    }
    rows = []
    for cycle in cycles.to_dict("records"):
        result = dict(cycle)
        cycle_date = pd.Timestamp(cycle["trade_date"]).normalize()
        position = positions.get(cycle_date)
        if position is None:
            raise ValueError("cycle date is absent from the trading calendar")
        window_dates = set(calendar[max(0, position - 19) : position + 1])
        truth_match = _latest_relation_match(
            relation_groups.get(
                (str(cycle["sector_id"]), str(cycle["truth_top1_symbol"]))
            ),
            window_dates,
        )
        causal_confirmed = 0
        for symbol in tuple(cycle["causal_top3_symbols"]):
            match = _latest_relation_match(
                relation_groups.get((str(cycle["sector_id"]), str(symbol))),
                window_dates,
            )
            causal_confirmed += int(match is not None)
        if truth_match is not None:
            status = "reason_confirmed_precycle"
            relation_date = pd.Timestamp(truth_match["source_date"])
            relation_method = str(truth_match["relation_method"])
        elif source_start is None or cycle_date.date() < source_start:
            status = "reason_source_unavailable"
            relation_date = None
            relation_method = None
        else:
            status = "reason_source_available_but_unconfirmed"
            relation_date = None
            relation_method = None
        result.update(
            {
                "truth_relation_status": status,
                "truth_relation_date": relation_date,
                "truth_relation_method": relation_method,
                "causal_top3_reason_confirmed_count": causal_confirmed,
            }
        )
        rows.append(result)
    return pd.DataFrame(rows)


def attach_board_risk(
    cycles: pd.DataFrame,
    memberships: pd.DataFrame,
) -> pd.DataFrame:
    """Attach static-member breadth, duplicate-leader and overlap risks."""

    _require_columns(
        cycles,
        (
            "cycle_id",
            "trade_date",
            "sector_id",
            "candidate_count",
            "truth_top1_symbol",
        ),
        "cycle audit",
    )
    _require_columns(memberships, ("sector_id", "vt_symbol"), "membership")
    members = memberships.loc[:, ["sector_id", "vt_symbol"]].copy()
    members["sector_id"] = members["sector_id"].astype(str)
    members["vt_symbol"] = members["vt_symbol"].astype(str)
    if members.duplicated(["sector_id", "vt_symbol"]).any():
        raise ValueError("membership identities must be unique")
    member_sets = {
        str(sector_id): set(group["vt_symbol"])
        for sector_id, group in members.groupby("sector_id", sort=False)
    }
    result = cycles.copy()
    result["trade_date"] = pd.to_datetime(
        result["trade_date"], errors="raise"
    ).dt.normalize()
    if result.duplicated(["cycle_id"]).any():
        raise ValueError("cycle audit IDs must be unique")
    result["current_member_count"] = result["sector_id"].map(
        lambda value: len(member_sets.get(str(value), set()))
    )
    result["candidate_count_bin"] = result["candidate_count"].map(
        _candidate_count_bin
    )
    result["truth_top1_concept_count_same_date"] = result.groupby(
        ["trade_date", "truth_top1_symbol"], sort=False
    )["cycle_id"].transform("nunique")
    max_jaccard: dict[str, float] = {str(value): 0.0 for value in result["cycle_id"]}
    closest_sector: dict[str, str | None] = {
        str(value): None for value in result["cycle_id"]
    }
    for _, group in result.groupby("trade_date", sort=False):
        records = group.loc[:, ["cycle_id", "sector_id"]].to_dict("records")
        for index, left in enumerate(records):
            left_set = member_sets.get(str(left["sector_id"]), set())
            for right in records[index + 1 :]:
                if str(left["sector_id"]) == str(right["sector_id"]):
                    raise ValueError("same-date audited cycles must have unique sectors")
                right_set = member_sets.get(str(right["sector_id"]), set())
                union = left_set | right_set
                score = len(left_set & right_set) / len(union) if union else 0.0
                for source, target in ((left, right), (right, left)):
                    cycle_id = str(source["cycle_id"])
                    if score > max_jaccard[cycle_id]:
                        max_jaccard[cycle_id] = float(score)
                        closest_sector[cycle_id] = str(target["sector_id"])
    result["max_same_date_member_jaccard"] = result["cycle_id"].astype(str).map(
        max_jaccard
    )
    result["closest_same_date_sector_id"] = result["cycle_id"].astype(str).map(
        closest_sector
    )
    result["near_duplicate_board"] = result[
        "max_same_date_member_jaccard"
    ].ge(NEAR_DUPLICATE_JACCARD)
    return result


def classify_mismatch_categories(cycles: pd.DataFrame) -> pd.DataFrame:
    """Separate uncertain concept relations from evidence-backed rank misses."""

    _require_columns(
        cycles,
        (
            "cycle_id",
            "captured",
            "truth_relation_status",
            "truth_top1_concept_count_same_date",
            "near_duplicate_board",
        ),
        "audited cycle",
    )
    allowed_statuses = {
        "reason_confirmed_precycle",
        "reason_source_available_but_unconfirmed",
        "reason_source_unavailable",
    }
    unknown = set(cycles["truth_relation_status"].astype(str)) - allowed_statuses
    if unknown:
        raise ValueError(f"unknown relation statuses: {sorted(unknown)}")

    rows = []
    for cycle in cycles.to_dict("records"):
        reasons: list[str] = []
        relation_status = str(cycle["truth_relation_status"])
        if relation_status != "reason_confirmed_precycle":
            reasons.append(relation_status)
        if int(cycle["truth_top1_concept_count_same_date"]) > 1:
            reasons.append("truth_top1_shared_by_multiple_concepts_same_date")
        if bool(cycle["near_duplicate_board"]):
            reasons.append("near_duplicate_current_member_board")
        captured = bool(cycle["captured"])
        if captured:
            category = "captured_by_frozen_causal_top3"
        elif reasons:
            category = "relation_or_board_data_risk"
        else:
            category = "credible_relation_ranking_failure"
        result = dict(cycle)
        result.update(
            {
                "relation_board_risk_reasons": tuple(reasons),
                "mismatch_category": category,
                "eligible_for_rank_failure_comparison": (
                    category == "credible_relation_ranking_failure"
                ),
            }
        )
        rows.append(result)
    return pd.DataFrame(rows)


def rank_active_consensus(candidates: pd.DataFrame) -> pd.DataFrame:
    """Rank repeat and recent market consensus before truth is attached."""

    leaked = sorted(
        column
        for column in candidates
        if any(token in str(column).lower() for token in PROHIBITED_RANK_TOKENS)
    )
    if leaked:
        raise ValueError(f"truth or future columns are prohibited: {leaked}")
    required = (
        "cycle_id",
        "trade_date",
        "vt_symbol",
        "main_rise_alive",
        "ignition_precedes_concept",
        "first_strong_sessions_ago_10d",
        "last_strong_sessions_ago_10d",
        "strong_days_10",
        "stock_excess_concept_10d_pct",
        "distance_from_prior_high_pct",
        "turnover_median_20d",
        "causal_rank",
        "baseline_rank",
    )
    _require_columns(candidates, required, "candidate feature")
    if candidates.duplicated(["cycle_id", "vt_symbol"]).any():
        raise ValueError("candidate identities must be unique")
    ranked = candidates.sort_values(
        [
            "trade_date",
            "cycle_id",
            "main_rise_alive",
            "ignition_precedes_concept",
            "strong_days_10",
            "last_strong_sessions_ago_10d",
            "stock_excess_concept_10d_pct",
            "first_strong_sessions_ago_10d",
            "distance_from_prior_high_pct",
            "turnover_median_20d",
            "vt_symbol",
        ],
        ascending=[
            True,
            True,
            False,
            False,
            False,
            True,
            False,
            False,
            False,
            False,
            True,
        ],
        na_position="last",
        kind="stable",
    ).copy()
    ranked["active_consensus_rank"] = (
        ranked.groupby("cycle_id", sort=False).cumcount() + 1
    )
    ranked["active_consensus_top1"] = ranked["active_consensus_rank"].eq(1)
    ranked["active_consensus_top3"] = ranked["active_consensus_rank"].le(3)
    return ranked.sort_values(
        ["trade_date", "cycle_id", "active_consensus_rank"], kind="stable"
    ).reset_index(drop=True)


def build_decisive_miss_reasons(
    cycles: pd.DataFrame,
    candidates: pd.DataFrame,
) -> pd.DataFrame:
    """Explain which causal component kept truth Top1 outside Top3."""

    _require_columns(
        cycles,
        ("cycle_id", "captured", "truth_top1_symbol"),
        "cycle audit",
    )
    required_candidate = (
        "cycle_id",
        "vt_symbol",
        "causal_rank",
        "main_rise_alive",
        "ignition_precedes_concept",
        "first_strong_sessions_ago_10d",
        "strong_days_10",
        "stock_excess_concept_10d_pct",
        "distance_from_prior_high_pct",
        "turnover_median_20d",
    )
    _require_columns(candidates, required_candidate, "candidate rank")
    groups = {
        str(cycle_id): group.set_index("vt_symbol", drop=False)
        for cycle_id, group in candidates.groupby("cycle_id", sort=False)
    }
    rows = []
    for cycle in cycles.loc[~cycles["captured"].astype(bool)].to_dict("records"):
        group = groups.get(str(cycle["cycle_id"]))
        if group is None:
            raise ValueError("mismatch cycle is absent from rebuilt candidates")
        cutoff_rows = group.loc[pd.to_numeric(group["causal_rank"]).eq(3)]
        if len(cutoff_rows) != 1:
            raise ValueError("mismatch cycle must have one causal rank-3 boundary")
        truth_symbol = str(cycle["truth_top1_symbol"])
        if truth_symbol not in group.index:
            raise ValueError("truth Top1 is absent from rebuilt candidates")
        truth = group.loc[truth_symbol]
        cutoff = cutoff_rows.iloc[0]
        reason = _first_causal_disadvantage(truth, cutoff)
        if "active_consensus_rank" in group:
            active_top3_symbols = tuple(
                group.loc[
                    pd.to_numeric(
                        group["active_consensus_rank"], errors="coerce"
                    ).le(3)
                ]
                .sort_values("active_consensus_rank", kind="stable")["vt_symbol"]
                .astype(str)
            )
        else:
            active_top3_symbols = ()
        result = dict(cycle)
        result.update(
            {
                "truth_causal_rank": int(truth["causal_rank"]),
                "causal_top3_cutoff_symbol": str(cutoff["vt_symbol"]),
                "decisive_miss_reason": reason,
                "truth_active_consensus_rank": _integer_or_none(
                    truth.get("active_consensus_rank")
                ),
                "truth_baseline_rank": _integer_or_none(truth.get("baseline_rank")),
                "active_consensus_top3_symbols": active_top3_symbols,
                "active_consensus_recaptured_truth_top1": (
                    truth_symbol in active_top3_symbols
                    if active_top3_symbols
                    else None
                ),
            }
        )
        for column in (
            "main_rise_alive",
            "ignition_precedes_concept",
            "first_strong_sessions_ago_10d",
            "last_strong_sessions_ago_10d",
            "strong_days_10",
            "stock_excess_concept_10d_pct",
            "distance_from_prior_high_pct",
            "turnover_median_20d",
        ):
            if column in group:
                result[f"truth_feature_{column}"] = truth.get(column)
                result[f"cutoff_feature_{column}"] = cutoff.get(column)
        rows.append(result)
    return pd.DataFrame(rows)


def evaluate_mismatch_rank_modes(
    candidates: pd.DataFrame,
    frozen_truth: pd.DataFrame,
    *,
    block_count: int = 5,
) -> pd.DataFrame:
    """Evaluate three frozen ranks against immutable truth identities."""

    _require_columns(
        candidates,
        (
            "cycle_id",
            "trade_date",
            "vt_symbol",
            "causal_rank",
            "active_consensus_rank",
            "baseline_rank",
        ),
        "rank mode candidate",
    )
    _require_columns(
        frozen_truth,
        ("cycle_id", "trade_date", "vt_symbol", "truth_rank"),
        "frozen truth",
    )
    candidate_cycles = set(candidates["cycle_id"].astype(str))
    truth_cycles = set(frozen_truth["cycle_id"].astype(str))
    if candidate_cycles != truth_cycles:
        raise ValueError("rank modes and frozen truth must cover identical cycles")
    truth_counts = frozen_truth.groupby("cycle_id", sort=False)["vt_symbol"].nunique()
    if not truth_counts.eq(3).all():
        raise ValueError("every frozen cycle must have exactly three truth leaders")
    calendar_dates = tuple(
        sorted(pd.to_datetime(frozen_truth["trade_date"]).dt.normalize().unique())
    )
    if block_count < 1 or len(calendar_dates) < block_count:
        raise ValueError("frozen cycles do not cover every requested block")
    date_blocks: dict[pd.Timestamp, int] = {}
    for block, values in enumerate(
        np.array_split(np.array(calendar_dates, dtype="datetime64[ns]"), block_count),
        start=1,
    ):
        date_blocks.update({pd.Timestamp(value): block for value in values})
    truth_sets = {
        str(cycle_id): {
            "top1": set(group.loc[group["truth_rank"].eq(1), "vt_symbol"].astype(str)),
            "top3": set(group["vt_symbol"].astype(str)),
        }
        for cycle_id, group in frozen_truth.groupby("cycle_id", sort=False)
    }
    frame = candidates.copy()
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    frame["block"] = frame["trade_date"].map(date_blocks)
    modes = (
        ("causal_leadership", "causal_rank"),
        ("active_consensus", "active_consensus_rank"),
        ("ten_day_excess_baseline", "baseline_rank"),
    )
    segments: list[tuple[str, pd.DataFrame]] = [("all", frame)]
    segments.extend(
        (f"block_{block}", frame.loc[frame["block"].eq(block)])
        for block in range(1, block_count + 1)
    )
    rows = []
    for segment_name, segment in segments:
        for mode, rank_column in modes:
            exact_values = []
            capture_values = []
            overlap_values = []
            for cycle_id, group in segment.groupby("cycle_id", sort=False):
                selected_top1 = set(
                    group.loc[group[rank_column].eq(1), "vt_symbol"].astype(str)
                )
                selected_top3 = set(
                    group.loc[group[rank_column].le(3), "vt_symbol"].astype(str)
                )
                if len(selected_top1) != 1 or len(selected_top3) != 3:
                    raise ValueError("every rank mode must select one Top1 and three Top3")
                truth = truth_sets[str(cycle_id)]
                exact_values.append(selected_top1 == truth["top1"])
                capture_values.append(bool(selected_top3 & truth["top1"]))
                overlap_values.append(len(selected_top3 & truth["top3"]) / 3.0)
            rows.append(
                {
                    "segment": segment_name,
                    "mode": mode,
                    "qualified_cycles": len(exact_values),
                    "top1_exact_rate_pct": _boolean_rate(exact_values),
                    "top3_truth_top1_capture_rate_pct": _boolean_rate(
                        capture_values
                    ),
                    "mean_truth_top3_overlap_pct": (
                        float(np.mean(overlap_values) * 100.0)
                        if overlap_values
                        else None
                    ),
                }
            )
    return pd.DataFrame(rows)


def validate_frozen_mode_metric_rebuild(
    metrics: pd.DataFrame,
    prior_report: Mapping[str, Any],
) -> None:
    """Verify rebuilt causal/baseline identities reproduce the frozen metrics."""

    prior_value = prior_report.get("identity_metrics")
    if not isinstance(prior_value, list) or not prior_value:
        raise ValueError("frozen report has no identity metrics")
    prior = pd.DataFrame(prior_value)
    compare_modes = {"causal_leadership", "ten_day_excess_baseline"}
    current = metrics.loc[metrics["mode"].isin(compare_modes)].copy()
    prior = prior.loc[prior["mode"].isin(compare_modes)].copy()
    keys = ["segment", "mode"]
    if current.duplicated(keys).any() or prior.duplicated(keys).any():
        raise ValueError("frozen mode metrics contain duplicate identities")
    merged = current.merge(
        prior,
        on=keys,
        how="outer",
        suffixes=("_rebuilt", "_frozen"),
        indicator=True,
    )
    if not merged["_merge"].eq("both").all():
        raise ValueError("rebuilt mode metric segments differ from frozen report")
    columns = (
        "qualified_cycles",
        "top1_exact_rate_pct",
        "top3_truth_top1_capture_rate_pct",
        "mean_truth_top3_overlap_pct",
    )
    for column in columns:
        left = pd.to_numeric(merged[f"{column}_rebuilt"], errors="coerce")
        right = pd.to_numeric(merged[f"{column}_frozen"], errors="coerce")
        if not np.allclose(left, right, rtol=0.0, atol=1e-12, equal_nan=True):
            raise ValueError(f"rebuilt identity metric changed: {column}")


def evaluate_active_consensus(metrics: pd.DataFrame) -> dict[str, Any]:
    """Classify the inspected alternative as exploratory at most."""

    _require_columns(
        metrics,
        (
            "segment",
            "mode",
            "qualified_cycles",
            "top1_exact_rate_pct",
            "top3_truth_top1_capture_rate_pct",
            "mean_truth_top3_overlap_pct",
        ),
        "mode metric",
    )
    block_segments = sorted(
        value for value in metrics["segment"].astype(str).unique() if value != "all"
    )
    block_winners = []
    active_wins = 0
    for segment in block_segments:
        block = metrics.loc[metrics["segment"].eq(segment)].copy()
        block["metric_tuple"] = block.apply(_metric_tuple, axis=1)
        best = max(block["metric_tuple"])
        winners = sorted(
            block.loc[
                block["metric_tuple"].map(
                    lambda value, expected=best: value == expected
                ),
                "mode",
            ].astype(str)
        )
        winner = winners[0] if len(winners) == 1 else None
        active_wins += int(winner == "active_consensus")
        block_winners.append({"segment": segment, "winner": winner})
    pooled = metrics.loc[metrics["segment"].eq("all")].set_index("mode")
    active = pooled.loc["active_consensus"]
    causal = pooled.loc["causal_leadership"]
    active_better = _metric_tuple(active) > _metric_tuple(causal)
    required_wins = math.floor(len(block_segments) / 2) + 1
    accuracy_passed = (
        float(active["top1_exact_rate_pct"]) >= MIN_TOP1_EXACT_RATE_PCT
        and float(active["top3_truth_top1_capture_rate_pct"])
        >= MIN_TOP3_CAPTURE_RATE_PCT
        and float(active["mean_truth_top3_overlap_pct"])
        >= MIN_TOP3_OVERLAP_PCT
    )
    exploratory = active_better and active_wins >= required_wins
    if exploratory:
        status = "exploratory_forward_candidate"
    else:
        status = "active_consensus_not_improved"
    return {
        "status": status,
        "active_consensus_block_wins": active_wins,
        "required_block_wins": required_wins,
        "active_consensus_pooled_better_than_causal": active_better,
        "identity_accuracy_gate_passed": accuracy_passed,
        "identity_accuracy_gate": {
            "minimum_top1_exact_rate_pct": MIN_TOP1_EXACT_RATE_PCT,
            "minimum_top3_truth_top1_capture_rate_pct": MIN_TOP3_CAPTURE_RATE_PCT,
            "minimum_mean_truth_top3_overlap_pct": MIN_TOP3_OVERLAP_PCT,
        },
        "block_winners": block_winners,
        "formal_selected_mode": None,
    }


def run_true_leader_mismatch_study() -> dict[str, Any]:
    """Run the frozen mismatch audit without loading low-suction outcomes."""

    inputs = load_true_leader_mismatch_inputs()
    source_start = _coverage_date(
        inputs.coverage.get("reason_event_source_start")
    )
    if source_start is None and not inputs.reason_relations.empty:
        source_start = (
            pd.to_datetime(inputs.reason_relations["source_date"], errors="raise")
            .min()
            .date()
        )
    cycle_audit = attach_relation_risk(
        inputs.cycle_rows,
        inputs.reason_relations,
        trading_dates=inputs.trading_dates,
        source_start=source_start,
    )
    cycle_audit = attach_board_risk(cycle_audit, inputs.memberships)
    cycle_audit = classify_mismatch_categories(cycle_audit)
    miss_rows = build_decisive_miss_reasons(cycle_audit, inputs.candidates)
    metrics = evaluate_mismatch_rank_modes(
        inputs.candidates,
        inputs.frozen_truth,
    )
    validate_frozen_mode_metric_rebuild(metrics, inputs.prior_report)
    inputs.coverage["frozen_identity_metrics_reproduced"] = True
    decision = evaluate_active_consensus(metrics)
    return build_mismatch_report(
        inputs,
        cycle_audit=cycle_audit,
        miss_rows=miss_rows,
        metrics=metrics,
        decision=decision,
    )


def build_mismatch_report(
    inputs: TrueLeaderMismatchInputs,
    *,
    cycle_audit: pd.DataFrame,
    miss_rows: pd.DataFrame,
    metrics: pd.DataFrame,
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one deterministic report containing every audited cycle and miss."""

    _require_columns(
        cycle_audit,
        (
            "cycle_id",
            "captured",
            "candidate_count_bin",
            "truth_relation_status",
            "truth_top1_concept_count_same_date",
            "near_duplicate_board",
            "mismatch_category",
        ),
        "cycle audit",
    )
    _require_columns(
        miss_rows,
        (
            "cycle_id",
            "decisive_miss_reason",
            "mismatch_category",
            "active_consensus_recaptured_truth_top1",
        ),
        "mismatch ledger",
    )
    frozen_cycles = set(inputs.frozen_truth["cycle_id"].astype(str))
    audit_cycles = set(cycle_audit["cycle_id"].astype(str))
    if audit_cycles != frozen_cycles or cycle_audit["cycle_id"].duplicated().any():
        raise ValueError("cycle audit must preserve every frozen cycle exactly once")
    expected_misses = set(
        cycle_audit.loc[~cycle_audit["captured"].astype(bool), "cycle_id"].astype(str)
    )
    actual_misses = set(miss_rows["cycle_id"].astype(str))
    if actual_misses != expected_misses or miss_rows["cycle_id"].duplicated().any():
        raise ValueError("mismatch ledger must preserve every frozen causal miss")

    candidate_bin_rows = _candidate_bin_metrics(cycle_audit)
    relation_counts = _value_counts(cycle_audit["truth_relation_status"])
    mismatch_relation_counts = _value_counts(
        cycle_audit.loc[
            ~cycle_audit["captured"].astype(bool), "truth_relation_status"
        ]
    )
    mismatch_category_counts = _value_counts(miss_rows["mismatch_category"])
    decisive_counts = _value_counts(miss_rows["decisive_miss_reason"])
    credible_misses = miss_rows.loc[
        miss_rows["mismatch_category"].eq(
            "credible_relation_ranking_failure"
        )
    ].copy()
    recovered = credible_misses[
        "active_consensus_recaptured_truth_top1"
    ].fillna(False).astype(bool)
    if "truth_active_consensus_rank" in credible_misses:
        active_top1 = pd.to_numeric(
            credible_misses["truth_active_consensus_rank"], errors="coerce"
        ).eq(1)
    else:
        active_top1 = pd.Series(False, index=credible_misses.index)
    coverage = {
        **inputs.coverage,
        "audited_cycles": int(len(cycle_audit)),
        "frozen_causal_captured_cycles": int(
            cycle_audit["captured"].astype(bool).sum()
        ),
        "mismatch_cycles": int(len(miss_rows)),
        "relation_or_board_data_risk_misses": int(
            mismatch_category_counts.get("relation_or_board_data_risk", 0)
        ),
        "credible_relation_ranking_failure_misses": int(len(credible_misses)),
    }
    report = {
        "study_version": "true-leader-mismatch-audit-v1",
        "overall_conclusion": str(decision.get("status") or "unknown"),
        "formal_metrics": None,
        "formal_selected_mode": None,
        "strict_top3_claim": False,
        "low_suction_rule_selected": False,
        "low_suction_outcomes_read": False,
        "minute_bars_read": False,
        "reference_campaign_bars_read": False,
        "market_timing_read": False,
        "gold_silver_read": False,
        "old_holdout_status": "contaminated_not_reusable",
        "frozen_input": {
            "path": str(inputs.coverage.get("frozen_report_path") or FROZEN_REPORT_PATH),
            "sha256": str(
                inputs.coverage.get("frozen_report_sha256")
                or FROZEN_REPORT_SHA256
            ),
            "truth_recomputed": False,
            "causal_top3_rebuild_required_exact_match": True,
            "prior_identity_metrics_reproduced": bool(
                inputs.coverage.get("frozen_identity_metrics_reproduced", False)
            ),
            "incomplete_exported_causal_top3_cycles": int(
                inputs.coverage.get("frozen_causal_top3_incomplete_cycles", 0)
            ),
        },
        "audit_contract": {
            "reason_window_sessions": 20,
            "reason_absence_means_wrong_membership": False,
            "current_membership_is_historical_truth": False,
            "near_duplicate_jaccard_threshold": NEAR_DUPLICATE_JACCARD,
            "rank_failure_requires_precycle_reason_confirmation": True,
            "rank_failure_excludes_shared_truth_leader_same_date": True,
            "rank_failure_excludes_near_duplicate_boards": True,
        },
        "active_consensus_rank_order": [
            "main_rise_alive_desc",
            "ignition_precedes_concept_desc",
            "strong_days_10_desc",
            "last_strong_sessions_ago_10d_asc",
            "stock_excess_concept_10d_pct_desc",
            "first_strong_sessions_ago_10d_desc",
            "distance_from_prior_high_pct_desc",
            "turnover_median_20d_desc",
            "vt_symbol_asc",
        ],
        "coverage": coverage,
        "relation_risk": {
            "source_start": inputs.coverage.get("reason_event_source_start"),
            "source_end": inputs.coverage.get("reason_event_source_end"),
            "all_cycle_status_counts": relation_counts,
            "mismatch_status_counts": mismatch_relation_counts,
            "unconfirmed_relation_is_not_proven_wrong": True,
        },
        "board_risk": {
            "same_date_shared_truth_leader_cycles": int(
                cycle_audit["truth_top1_concept_count_same_date"].gt(1).sum()
            ),
            "same_date_shared_truth_leader_misses": int(
                miss_rows["truth_top1_concept_count_same_date"].gt(1).sum()
            ),
            "near_duplicate_board_cycles": int(
                cycle_audit["near_duplicate_board"].astype(bool).sum()
            ),
            "near_duplicate_board_misses": int(
                miss_rows["near_duplicate_board"].astype(bool).sum()
            ),
            "maximum_observed_same_date_member_jaccard": _series_max(
                cycle_audit["max_same_date_member_jaccard"]
            ),
        },
        "mismatch_classification": {
            "counts": mismatch_category_counts,
            "credible_relation_means_proven_historical_membership": False,
            "credible_relation_definition": (
                "precycle reason confirmed; truth leader not shared across concepts "
                "on the same date; no current-member Jaccard >= 0.80"
            ),
        },
        "capture_by_candidate_count_bin": candidate_bin_rows,
        "decisive_miss_reason_counts": decisive_counts,
        "identity_metrics": _records(metrics),
        "active_consensus_decision": _json_safe(dict(decision)),
        "credible_rank_failure_recovery": {
            "eligible_misses": int(len(credible_misses)),
            "active_consensus_top1_exact_count": int(active_top1.sum()),
            "active_consensus_top1_exact_rate_pct": _boolean_rate(
                active_top1.tolist()
            ),
            "active_consensus_top3_recaptured_count": int(recovered.sum()),
            "active_consensus_top3_recaptured_rate_pct": _boolean_rate(
                recovered.tolist()
            ),
            "descriptive_subset_only": True,
        },
        "credible_rank_failure_cases": _records(credible_misses),
        "cycle_audit": _records(cycle_audit),
        "mismatch_ledger": _records(miss_rows),
        "fingerprints": _json_safe(inputs.fingerprints),
        "limitations": [
            "current concept membership is a survivorship proxy, not historical point-in-time membership",
            "reason-event coverage starts late; absence before source coverage is unknown",
            "same-day overlapping concepts can describe one stock with several labels",
            "all five chronological blocks have already been inspected",
            "active_consensus is exploratory and cannot become a formal identity mode here",
            "identity accuracy does not establish a low-suction entry, win rate, return or compounding",
        ],
        "next_stage": (
            "freeze_active_consensus_for_new_forward_identity_data"
            if decision.get("status") == "exploratory_forward_candidate"
            else "repair_point_in_time_concept_relations_before_new_identity_rank"
        ),
        "reproduce": (
            "docker compose run --rm --no-deps "
            "-v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api "
            "python -m alphaagent.server.services.low_suction.cli "
            "v2-true-leader-mismatch-study --format markdown"
        ),
    }
    return _json_safe(report)


def render_mismatch_study_json(report: Mapping[str, Any]) -> str:
    """Render the exact machine report."""

    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_mismatch_study_markdown(report: Mapping[str, Any]) -> str:
    """Render a concise human view from the same report object."""

    coverage = report["coverage"]
    decision = report["active_consensus_decision"]
    recovery = report["credible_rank_failure_recovery"]
    lines = [
        "# AlphaAgent 真龙头漏抓审计",
        "",
        f"结论：`{report['overall_conclusion']}`。正式模式：`null`；低吸结果读取：`false`。",
        "",
        "本报告冻结既有 1,087 周期真值，只审计概念关系风险与因果排序漏抓。",
        "缺少涨停原因证据只表示未知，不表示当前成员关系已经被证明错误。",
        "",
        "## Coverage",
        "",
        f"- 审计周期：`{coverage['audited_cycles']}`；原有因果 Top3 捕获：`{coverage['frozen_causal_captured_cycles']}`。",
        f"- 漏抓：`{coverage['mismatch_cycles']}`；关系/板块数据风险：`{coverage['relation_or_board_data_risk_misses']}`；关系基本可信的排序失败：`{coverage['credible_relation_ranking_failure_misses']}`。",
        f"- 原报告因未来完整性过滤少写原有因果身份的周期：`{report['frozen_input']['incomplete_exported_causal_top3_cycles']}`；已按冻结数据指纹重建并复核原指标。",
        f"- 冻结输入 SHA256：`{report['frozen_input']['sha256']}`。",
        "",
        "## Candidate Breadth",
        "",
        "| Candidate count | Cycles | Captured | Capture rate | Data-risk misses | Credible rank misses |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["capture_by_candidate_count_bin"]:
        lines.append(
            f"| `{row['candidate_count_bin']}` | {row['cycles']} | {row['captured_cycles']} | "
            f"{_pct(row['capture_rate_pct'])} | {row['relation_or_board_data_risk_misses']} | "
            f"{row['credible_relation_ranking_failure_misses']} |"
        )
    lines.extend(
        [
            "",
            "## Mismatch Classes",
            "",
            "| Class | Count |",
            "| --- | ---: |",
        ]
    )
    for key, value in report["mismatch_classification"]["counts"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Decisive Rank Reasons",
            "",
            "每个原因都将真值 Top1 与原有因果第 3 名准入边界比较。",
            "",
            "| First disadvantage | Misses |",
            "| --- | ---: |",
        ]
    )
    for key, value in report["decisive_miss_reason_counts"].items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Confirmed Relation Rank Misses",
            "",
            "| Date | Concept | Truth leader | Causal rank | Cutoff | First disadvantage | Active rank |",
            "| --- | --- | --- | ---: | --- | --- | ---: |",
        ]
    )
    for row in report["credible_rank_failure_cases"]:
        lines.append(
            f"| `{row['trade_date']}` | {row['concept_name']} | "
            f"{row['truth_top1_stock_name']} `{row['truth_top1_symbol']}` | "
            f"{row['truth_causal_rank']} | `{row['causal_top3_cutoff_symbol']}` | "
            f"`{row['decisive_miss_reason']}` | "
            f"{row['truth_active_consensus_rank']} |"
        )
    lines.append("")
    for row in report["credible_rank_failure_cases"]:
        lines.append(
            f"- {row['truth_top1_stock_name']}：原因关系于 `{row['truth_relation_date']}` "
            f"确认；真龙头/第 3 名边界的主升状态为 "
            f"`{str(row['truth_feature_main_rise_alive']).lower()}/"
            f"{str(row['cutoff_feature_main_rise_alive']).lower()}`，首次强势领先 "
            f"`{_number(row['truth_feature_first_strong_sessions_ago_10d'])}/"
            f"{_number(row['cutoff_feature_first_strong_sessions_ago_10d'])}` 个交易日，"
            f"10 日强势次数 `{_number(row['truth_feature_strong_days_10'])}/"
            f"{_number(row['cutoff_feature_strong_days_10'])}`。"
        )
    lines.extend(
        [
            "",
            "## Identity Modes",
            "",
            "| Segment | Mode | Cycles | Top1 exact | Top3 captures truth Top1 | Top3 overlap |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["identity_metrics"]:
        lines.append(
            f"| `{row['segment']}` | `{row['mode']}` | {row['qualified_cycles']} | "
            f"{_pct(row['top1_exact_rate_pct'])} | "
            f"{_pct(row['top3_truth_top1_capture_rate_pct'])} | "
            f"{_pct(row['mean_truth_top3_overlap_pct'])} |"
        )
    lines.extend(
        [
            "",
            "## Active Consensus",
            "",
            f"- 五块胜数：`{decision['active_consensus_block_wins']}/{len(decision['block_winners'])}`；要求：`{decision['required_block_wins']}`。",
            f"- 全体绝对身份门：`{str(decision['identity_accuracy_gate_passed']).lower()}`。",
            f"- 关系基本可信排序失败组：`{recovery['eligible_misses']}`；新 Top3 找回 "
            f"`{recovery['active_consensus_top3_recaptured_count']}`，找回率 "
            f"`{_pct(recovery['active_consensus_top3_recaptured_rate_pct'])}`。",
            "- 该子组只作漏抓解释；正式模式仍为 `null`。",
            "",
            "## Board And Relation Risk",
            "",
            f"- 同日同一真龙头对应多个概念的漏抓周期：`{report['board_risk']['same_date_shared_truth_leader_misses']}`。",
            f"- 当前成员 Jaccard 不低于 0.80 的漏抓周期：`{report['board_risk']['near_duplicate_board_misses']}`。",
            f"- 涨停原因来源覆盖：`{report['relation_risk']['source_start']}..{report['relation_risk']['source_end']}`。",
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


def _validate_frozen_input_fingerprints(
    current: Mapping[str, Mapping[str, Any]],
    frozen_value: Any,
) -> None:
    if not isinstance(frozen_value, Mapping):
        raise ValueError("frozen report has no input fingerprints")
    required = (
        "cycle_starts",
        "current_memberships",
        "discovery_stock_bars",
        "discovery_concept_bars",
        "normalized_reason_relations",
    )
    for name in required:
        current_value = current.get(name)
        frozen = frozen_value.get(name)
        if current_value is None or not isinstance(frozen, Mapping):
            raise ValueError(f"missing frozen input fingerprint: {name}")
        for field in ("algorithm", "digest", "rows", "columns"):
            if current_value.get(field) != frozen.get(field):
                raise ValueError(
                    f"frozen input fingerprint changed: {name}.{field}"
                )


def _attach_rebuilt_causal_top3(
    cycles: pd.DataFrame,
    candidates: pd.DataFrame,
) -> pd.DataFrame:
    top3_by_cycle = {
        str(cycle_id): tuple(
            group.sort_values("causal_rank", kind="stable")
            .head(3)["vt_symbol"]
            .astype(str)
        )
        for cycle_id, group in candidates.groupby("cycle_id", sort=False)
    }
    result = cycles.copy()
    result["causal_top3_symbols"] = result["cycle_id"].astype(str).map(
        top3_by_cycle
    )
    if result["causal_top3_symbols"].map(
        lambda value: isinstance(value, tuple) and len(value) == 3
    ).all():
        result["causal_top3_reconstructed"] = result[
            "frozen_causal_top3_reported_count"
        ].lt(3)
        return result
    raise ValueError("every frozen cycle must rebuild exactly three causal leaders")


def _candidate_bin_metrics(cycles: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for label in ("3-5", "6-10", "11-20", "21-50", "51+"):
        group = cycles.loc[cycles["candidate_count_bin"].eq(label)]
        if group.empty:
            continue
        captured = group["captured"].astype(bool)
        mismatches = group.loc[~captured]
        category_counts = _value_counts(mismatches["mismatch_category"])
        rows.append(
            {
                "candidate_count_bin": label,
                "cycles": int(len(group)),
                "captured_cycles": int(captured.sum()),
                "capture_rate_pct": float(captured.mean() * 100.0),
                "relation_or_board_data_risk_misses": int(
                    category_counts.get("relation_or_board_data_risk", 0)
                ),
                "credible_relation_ranking_failure_misses": int(
                    category_counts.get("credible_relation_ranking_failure", 0)
                ),
            }
        )
    return rows


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
    return {
        str(key): int(value)
        for key, value in values.fillna("missing").astype(str).value_counts().items()
    }


def _series_max(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.max()) if not numeric.empty else None


def _coverage_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    return date.fromisoformat(str(value))


def _integer_or_none(value: Any) -> int | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return int(numeric) if np.isfinite(numeric) else None


def _pct(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{numeric:.4f}%" if np.isfinite(numeric) else "-"


def _number(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{numeric:.4f}" if np.isfinite(numeric) else "-"


def _validate_leader_list(
    value: Any,
    label: str,
    *,
    require_complete: bool,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 3:
        raise ValueError(f"frozen {label} Top3 must contain at most three rows")
    if require_complete and len(value) != 3:
        raise ValueError(f"frozen {label} Top3 must contain exactly three rows")
    ranks = [int(item.get("rank") or 0) for item in value]
    symbols = [str(item.get("vt_symbol") or "") for item in value]
    expected_ranks = {1, 2, 3}
    if (
        not set(ranks).issubset(expected_ranks)
        or len(set(ranks)) != len(ranks)
        or len(set(symbols)) != len(symbols)
        or "" in symbols
    ):
        raise ValueError(f"frozen {label} Top3 identities are invalid")
    return [dict(item) for item in value]


def _latest_relation_match(
    frame: pd.DataFrame | None,
    window_dates: set[pd.Timestamp],
) -> dict[str, Any] | None:
    if frame is None or frame.empty:
        return None
    matches = frame.loc[frame["source_date"].isin(window_dates)].copy()
    if matches.empty:
        return None
    matches["method_priority"] = matches["relation_method"].map(
        {"exact": 0, "normalized_suffix_exact": 1}
    ).fillna(2)
    return dict(
        matches.sort_values(
            ["source_date", "method_priority"],
            ascending=[False, True],
            kind="stable",
        ).iloc[0]
    )


def _candidate_count_bin(value: Any) -> str:
    count = int(value)
    if count <= 5:
        return "3-5"
    if count <= 10:
        return "6-10"
    if count <= 20:
        return "11-20"
    if count <= 50:
        return "21-50"
    return "51+"


def _first_causal_disadvantage(
    truth: pd.Series,
    cutoff: pd.Series,
) -> str:
    components = (
        ("main_rise_alive", False, "truth_main_rise_not_alive"),
        (
            "ignition_precedes_concept",
            False,
            "truth_ignition_not_precycle",
        ),
        (
            "first_strong_sessions_ago_10d",
            False,
            "truth_ignited_later",
        ),
        ("strong_days_10", False, "truth_fewer_strong_days_10"),
        (
            "stock_excess_concept_10d_pct",
            False,
            "truth_lower_precycle_excess",
        ),
        (
            "distance_from_prior_high_pct",
            False,
            "truth_farther_from_prior_high",
        ),
        (
            "turnover_median_20d",
            False,
            "truth_lower_turnover_capacity",
        ),
    )
    for column, ascending, reason in components:
        truth_value = truth[column]
        cutoff_value = cutoff[column]
        comparison = _rank_comparison(truth_value, cutoff_value, ascending=ascending)
        if comparison < 0:
            return reason
        if comparison > 0:
            raise ValueError(
                f"truth leader is better before rank-3 cutoff at {column}"
            )
    truth_symbol = str(truth["vt_symbol"])
    cutoff_symbol = str(cutoff["vt_symbol"])
    if truth_symbol > cutoff_symbol:
        return "truth_symbol_tiebreak_after_cutoff"
    raise ValueError("truth leader rank conflicts with causal sort order")


def _rank_comparison(
    first: Any,
    second: Any,
    *,
    ascending: bool,
) -> int:
    if pd.isna(first) and pd.isna(second):
        return 0
    if pd.isna(first):
        return -1
    if pd.isna(second):
        return 1
    left = float(first) if not isinstance(first, (bool, np.bool_)) else int(first)
    right = float(second) if not isinstance(second, (bool, np.bool_)) else int(second)
    if left == right:
        return 0
    better = left < right if ascending else left > right
    return 1 if better else -1


def _boolean_rate(values: Sequence[bool]) -> float | None:
    return float(np.mean(values) * 100.0) if values else None


def _metric_tuple(row: pd.Series) -> tuple[float, float, float]:
    return (
        float(row["top3_truth_top1_capture_rate_pct"]),
        float(row["top1_exact_rate_pct"]),
        float(row["mean_truth_top3_overlap_pct"]),
    )


def _finite_or_none(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = sorted(set(columns) - set(frame))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
