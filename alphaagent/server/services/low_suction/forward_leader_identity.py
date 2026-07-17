"""Strict forward Top3 identity capture built from one completed source session."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .baostock_security_source import (
    FORWARD_EVIDENCE_LEVEL as SECURITY_EVIDENCE_LEVEL,
    FORWARD_SECURITY_SOURCE,
)
from .concept_cycles import (
    FROZEN_MAIN_RISE_DEFINITION,
    build_cycle_candidates,
    build_market_returns,
)
from .concept_index_coverage import CANONICAL_CONCEPT_INDEX_SOURCE
from .forward_membership import (
    FORWARD_MEMBERSHIP_SOURCE,
    TRADABLE_SCOPE_TYPE,
)
from .leader_identity import (
    PROHIBITED_OUTCOME_COLUMNS,
    PROHIBITED_OUTCOME_PREFIXES,
    LeaderIdentityMode,
    rank_prevalidated_leader_identities,
)
from .research_protocol import fingerprint_frame
from .universe import SecurityRecord, eligibility_reason, is_main_board_symbol

SHANGHAI = ZoneInfo("Asia/Shanghai")
FORWARD_LEADER_RANKING_VERSION = "low-suction-forward-top3-v1"
FORWARD_TARGET_SESSION = "next_trading_session"
FORWARD_RANK_EVIDENCE_LEVEL = "strict_forward"
CAPACITY_MIN_MEDIAN_TURNOVER = 100_000_000.0
STRONG_DAY_THRESHOLD_PCT = 5.0
NO_STRONG_SESSION_SENTINEL = 10_000
FEATURE_CUTOFF_TIME = time(15, 0)


class ForwardLeaderIdentityError(ValueError):
    """Raised when strict forward identity inputs are internally inconsistent."""


class _ForwardLeaderNotReady(RuntimeError):
    pass


@dataclass(frozen=True)
class ForwardLeaderSourceInputs:
    source_trade_date: date
    attempted_at: datetime
    membership_scope: Mapping[str, Any]
    security_scope: Mapping[str, Any]
    memberships: pd.DataFrame
    securities: pd.DataFrame
    trading_dates: tuple[date, ...]
    concept_bars: pd.DataFrame
    benchmark_bars: pd.DataFrame
    stock_bars: pd.DataFrame


@dataclass(frozen=True)
class ForwardLeaderRankRow:
    source_trade_date: date
    ranking_version: str
    identity_mode: str
    sector_id: str
    vt_symbol: str
    target_session: str
    target_trade_date: date | None
    known_at: datetime
    feature_cutoff: datetime
    membership_known_at: datetime
    security_known_at: datetime
    sector_name: str
    cycle_id: str
    cycle_start: date
    cycle_days: int
    cycle_relative_return: float | None
    strong_day_count_cycle: int | None
    sessions_since_strong: int | None
    turnover_median_20d: float | None
    capacity_passed: bool
    relative_strength_rank: int | None
    market_recognition_rank: int | None
    rank: int | None
    rank_eligible: bool
    is_top3: bool
    excluded_reason: str | None
    input_fingerprint: str
    evidence_level: str
    raw: dict[str, object]


@dataclass(frozen=True)
class ForwardLeaderRankScope:
    source_trade_date: date
    ranking_version: str
    identity_mode: str
    target_session: str
    target_trade_date: date | None
    known_at: datetime
    feature_cutoff: datetime
    main_rise_definition: str
    active_concept_count: int
    membership_row_count: int
    main_board_member_count: int
    security_eligible_count: int
    ranked_row_count: int
    top3_row_count: int
    excluded_row_count: int
    complete: bool
    status: str
    input_fingerprint: str
    selected_mode: str | None
    evidence_level: str
    raw: dict[str, object]


@dataclass(frozen=True)
class ForwardLeaderCapture:
    source_trade_date: date
    ranking_version: str
    input_fingerprint: str
    rows: tuple[ForwardLeaderRankRow, ...]
    scopes: tuple[ForwardLeaderRankScope, ...]

    @property
    def complete(self) -> bool:
        return bool(self.scopes) and all(scope.complete for scope in self.scopes)


@dataclass(frozen=True)
class _StockFeatureProfile:
    source_bar_available: bool
    close_by_date: pd.Series
    change_by_date: pd.Series
    sessions_since_strong: int | None
    turnover_median_20d: float | None


def build_forward_leader_capture(
    inputs: ForwardLeaderSourceInputs,
) -> ForwardLeaderCapture:
    """Build all three frozen identity modes, or three closed scopes."""

    _reject_future_or_outcome_columns(
        inputs.memberships,
        inputs.securities,
        inputs.concept_bars,
        inputs.benchmark_bars,
        inputs.stock_bars,
    )
    _require_aware(inputs.attempted_at, label="attempted_at")
    try:
        return _build_complete_capture(inputs)
    except _ForwardLeaderNotReady as exc:
        return _closed_capture(inputs, str(exc))


def freeze_forward_leader_source(
    source_trade_date: date,
    *,
    attempted_at: datetime,
) -> dict[str, object]:
    """Bind prior targets and freeze one exact strict source session."""

    from .forward_leader_identity_repository import (
        bind_pending_forward_target_sessions,
        load_forward_leader_source_inputs,
        save_forward_leader_capture,
    )

    bound = bind_pending_forward_target_sessions(as_of_date=source_trade_date)
    inputs = load_forward_leader_source_inputs(
        source_trade_date,
        attempted_at=attempted_at,
    )
    capture = build_forward_leader_capture(inputs)
    saved = save_forward_leader_capture(capture)
    return {
        "source_trade_date": source_trade_date.isoformat(),
        "ranking_version": capture.ranking_version,
        "input_fingerprint": capture.input_fingerprint,
        "complete": capture.complete,
        "save_status": saved.status,
        "rows_written": saved.rows_written,
        "scopes_written": saved.scopes_written,
        "rank_rows": len(capture.rows),
        "top3_rows": sum(row.is_top3 for row in capture.rows),
        "bound_prior_sessions": list(bound),
        "blocking_reasons": sorted(
            {
                str(scope.raw.get("blocking_reason"))
                for scope in capture.scopes
                if scope.raw.get("blocking_reason")
            }
        ),
        "selected_mode": None,
        "formal_metrics": None,
        "low_suction_outcomes_read": False,
    }


def render_forward_leader_report_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_forward_leader_report_markdown(report: Mapping[str, Any]) -> str:
    selected_mode = report.get("selected_mode")
    lines = [
        "# AlphaAgent 低吸真实前向 Top3 身份账本",
        "",
        f"ranking_version: `{report.get('ranking_version')}`  ",
        f"latest_source_trade_date: `{report.get('latest_source_trade_date') or '-'}`  ",
        f"source_sessions: `{report.get('source_sessions', 0)}`  ",
        f"bound_sessions: `{report.get('bound_sessions', 0)}`  ",
        f"selection_status: `{report.get('selection_status')}`  ",
        f"selected_mode: `{'null' if selected_mode is None else selected_mode}`  ",
        "formal_metrics: `null`  ",
        "low_suction_outcomes_read: `false`",
        "",
        "本账本只比较龙头身份留存、后续强势事件领先和容量；不读取低吸买卖收益，",
        "也不输出胜率、复利、利润因子或生产买点。目标日期只在真实完整交易时段出现后绑定。",
        "",
        "## Latest Frozen Scope",
        "",
        "| Mode | Active concepts | Main-board rows | Security eligible | Ranked | Top3 | Excluded | Capacity |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for metric in report.get("latest_scope_metrics", []):
        lines.append(
            f"| `{metric.get('identity_mode')}` | "
            f"{metric.get('active_concept_count', '-')} | "
            f"{metric.get('main_board_member_count', '-')} | "
            f"{metric.get('security_eligible_count', '-')} | "
            f"{metric.get('ranked_row_count', '-')} | "
            f"{metric.get('top3_row_count', 0)} | "
            f"{metric.get('excluded_row_count', '-')} | "
            f"{_report_number(metric.get('capacity_pass_rate'))} |"
        )
    lines.extend(
        [
        "",
        "## Mode Metrics",
        "",
        "| Mode | Bound sessions | Top3 obs | Retention obs | Retention | Strong obs | Strong lead | Capacity |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for metric in report.get("mode_metrics", []):
        lines.append(
            f"| `{metric.get('identity_mode')}` | {metric.get('bound_sessions', 0)} | "
            f"{metric.get('top3_observations', 0)} | "
            f"{metric.get('eligible_retention_observations', 0)} | "
            f"{_report_number(metric.get('next_session_top3_retention'))} | "
            f"{metric.get('strong_event_lead_observations', 0)} | "
            f"{_report_number(metric.get('strong_event_lead_sessions'))} | "
            f"{_report_number(metric.get('capacity_pass_rate'))} |"
        )
    lines.extend(
        [
            "",
            "## Latest Frozen Top3",
            "",
            "| Mode | Concept | Stock | Rank | Capacity | Target |",
            "| --- | --- | --- | ---: | --- | --- |",
        ]
    )
    for row in report.get("latest_top3", []):
        lines.append(
            f"| `{row.get('identity_mode')}` | {row.get('sector_name')} "
            f"(`{row.get('sector_id')}`) | {row.get('stock_name') or '-'} "
            f"(`{row.get('vt_symbol')}`) | {row.get('rank')} | "
            f"{'pass' if row.get('capacity_passed') else 'below'} | "
            f"{row.get('target_trade_date') or 'next_trading_session'} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "样本未达到预注册的 60 个已绑定源交易时段前，`selected_mode` 必须保持 `null`。",
            "身份模式不能用低吸收益选择；分钟低吸研究也不会由本报告自动启动。",
            "",
        ]
    )
    return "\n".join(lines)


def _build_complete_capture(
    inputs: ForwardLeaderSourceInputs,
) -> ForwardLeaderCapture:
    source_date = inputs.source_trade_date
    feature_cutoff = datetime.combine(
        source_date,
        FEATURE_CUTOFF_TIME,
        tzinfo=SHANGHAI,
    )
    membership_known_at = _validate_membership_scope(inputs)
    security_known_at = _validate_security_scope(inputs)
    known_at = max(membership_known_at, security_known_at)
    if known_at <= feature_cutoff:
        _not_ready("strict_snapshots_not_observed_post_close")

    trading_dates = _validated_trading_dates(inputs.trading_dates, source_date)
    memberships = _validated_memberships(inputs, membership_known_at)
    securities = _validated_securities(inputs, security_known_at)
    concept_bars = _validated_concept_bars(inputs.concept_bars, source_date)
    benchmark_bars = _validated_benchmark_bars(inputs.benchmark_bars, source_date)

    source_concepts = set(
        concept_bars.loc[
            concept_bars["trade_date"].dt.date.eq(source_date),
            "sector_id",
        ].astype(str)
    )
    membership_concepts = set(memberships["sector_id"].astype(str))
    if membership_concepts - source_concepts:
        _not_ready("canonical_concept_source_date_incomplete")

    try:
        market_returns = build_market_returns(
            benchmark_bars,
            research_dates=trading_dates,
        )
        cycle_candidates = build_cycle_candidates(concept_bars, market_returns)
    except ValueError as exc:
        _not_ready(f"canonical_cycle_inputs_incomplete:{exc}")

    active_cycles = cycle_candidates.loc[
        cycle_candidates["definition"].eq(FROZEN_MAIN_RISE_DEFINITION)
        & cycle_candidates["trade_date"].dt.date.eq(source_date)
        & cycle_candidates["in_cycle"].astype(bool)
        & cycle_candidates["sector_id"].astype(str).isin(membership_concepts)
    ].copy()
    if active_cycles.duplicated(["sector_id"]).any():
        raise ForwardLeaderIdentityError(
            "active concept cycle identity must be unique on the source date"
        )

    features, feature_counts = _build_rank_features(
        source_date=source_date,
        feature_cutoff=feature_cutoff,
        membership_known_at=membership_known_at,
        security_known_at=security_known_at,
        memberships=memberships,
        securities=securities,
        active_cycles=active_cycles,
        concept_bars=concept_bars,
        stock_bars=inputs.stock_bars,
        trading_dates=trading_dates,
        manifest_version=str(inputs.membership_scope.get("manifest_version") or ""),
    )
    fingerprint = fingerprint_frame(
        features,
        identity_columns=("source_trade_date", "sector_id", "vt_symbol"),
    ).digest

    rows: list[ForwardLeaderRankRow] = []
    scopes: list[ForwardLeaderRankScope] = []
    for mode in LeaderIdentityMode:
        ranked = rank_prevalidated_leader_identities(
            features,
            mode=mode,
            session_column="source_trade_date",
        )
        mode_rows = tuple(
            _rank_row(
                row,
                source_date=source_date,
                mode=mode,
                known_at=known_at,
                feature_cutoff=feature_cutoff,
                membership_known_at=membership_known_at,
                security_known_at=security_known_at,
                fingerprint=fingerprint,
            )
            for _, row in ranked.iterrows()
        )
        rows.extend(mode_rows)
        ranked_count = sum(row.rank is not None for row in mode_rows)
        top3_count = sum(row.is_top3 for row in mode_rows)
        excluded_count = len(mode_rows) - ranked_count
        scopes.append(
            ForwardLeaderRankScope(
                source_trade_date=source_date,
                ranking_version=FORWARD_LEADER_RANKING_VERSION,
                identity_mode=mode.value,
                target_session=FORWARD_TARGET_SESSION,
                target_trade_date=None,
                known_at=known_at,
                feature_cutoff=feature_cutoff,
                main_rise_definition=FROZEN_MAIN_RISE_DEFINITION,
                active_concept_count=int(active_cycles["sector_id"].nunique()),
                membership_row_count=len(memberships),
                main_board_member_count=feature_counts["main_board_member_count"],
                security_eligible_count=feature_counts["security_eligible_count"],
                ranked_row_count=ranked_count,
                top3_row_count=top3_count,
                excluded_row_count=excluded_count,
                complete=True,
                status="frozen_unbound",
                input_fingerprint=fingerprint,
                selected_mode=None,
                evidence_level=FORWARD_RANK_EVIDENCE_LEVEL,
                raw={
                    **feature_counts,
                    "membership_source": FORWARD_MEMBERSHIP_SOURCE,
                    "security_source": FORWARD_SECURITY_SOURCE,
                    "concept_source": CANONICAL_CONCEPT_INDEX_SOURCE,
                    "membership_manifest_version": str(
                        inputs.membership_scope.get("manifest_version") or ""
                    ),
                    "capacity_min_median_turnover": (
                        CAPACITY_MIN_MEDIAN_TURNOVER
                    ),
                    "selected_mode": None,
                    "low_suction_outcomes_read": False,
                },
            )
        )

    return ForwardLeaderCapture(
        source_trade_date=source_date,
        ranking_version=FORWARD_LEADER_RANKING_VERSION,
        input_fingerprint=fingerprint,
        rows=tuple(rows),
        scopes=tuple(scopes),
    )


def _build_rank_features(
    *,
    source_date: date,
    feature_cutoff: datetime,
    membership_known_at: datetime,
    security_known_at: datetime,
    memberships: pd.DataFrame,
    securities: pd.DataFrame,
    active_cycles: pd.DataFrame,
    concept_bars: pd.DataFrame,
    stock_bars: pd.DataFrame,
    trading_dates: tuple[date, ...],
    manifest_version: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    columns = _feature_columns()
    if active_cycles.empty:
        counts = {
            "active_membership_rows": 0,
            "board_excluded_rows": 0,
            "main_board_member_count": 0,
            "security_eligible_count": 0,
            "security_excluded_rows": 0,
        }
        return pd.DataFrame(columns=columns), counts

    cycles = active_cycles.loc[
        :,
        ["sector_id", "concept_name", "cycle_id", "cycle_start", "cycle_days"],
    ].copy()
    cycles["sector_id"] = cycles["sector_id"].astype(str)
    active_members = memberships.merge(
        cycles,
        on="sector_id",
        how="inner",
        validate="many_to_one",
    )
    symbol_parts = active_members["vt_symbol"].map(_symbol_exchange)
    active_members[["symbol", "exchange"]] = pd.DataFrame(
        symbol_parts.tolist(),
        index=active_members.index,
    )
    main_board = active_members.apply(
        lambda row: is_main_board_symbol(row["symbol"], row["exchange"]),
        axis=1,
    )
    board_excluded_rows = int((~main_board).sum())
    candidates = active_members.loc[main_board].copy()

    security_columns = [
        "vt_symbol",
        "name",
        "status",
        "listed_on",
        "delisted_on",
        "suspended",
        "risk_warning",
        "evidence_level",
    ]
    candidates = candidates.merge(
        securities.loc[:, security_columns].rename(
            columns={"evidence_level": "security_evidence_level"}
        ),
        on="vt_symbol",
        how="left",
        validate="many_to_one",
    )
    calendar = pd.DatetimeIndex(pd.to_datetime(trading_dates)).normalize()
    profiles = _stock_feature_profiles(
        stock_bars,
        vt_symbols=tuple(sorted(candidates["vt_symbol"].unique())),
        trading_dates=trading_dates,
        source_date=source_date,
    )
    concept_lookup = (
        concept_bars.set_index(["sector_id", "trade_date"])["close_price"]
        .sort_index()
    )

    rows: list[dict[str, object]] = []
    eligible_count = 0
    security_excluded_rows = 0
    for _, candidate in candidates.iterrows():
        excluded_reason = _candidate_exclusion_reason(
            candidate,
            source_date=source_date,
            calendar=calendar,
        )
        if excluded_reason is None:
            eligible_count += 1
        else:
            security_excluded_rows += 1

        profile = profiles.get(str(candidate["vt_symbol"]))
        cycle_start = pd.Timestamp(candidate["cycle_start"]).normalize()
        cycle_position = calendar.get_indexer([cycle_start])[0]
        if cycle_position <= 0:
            if excluded_reason is None:
                _not_ready("eligible_member_cycle_anchor_incomplete")
            feature_values = _empty_feature_values()
        elif excluded_reason is None:
            if profile is None or not profile.source_bar_available:
                _not_ready("eligible_member_source_bar_incomplete")
            anchor_date = calendar[cycle_position - 1]
            stock_anchor = _positive_number(profile.close_by_date.get(anchor_date))
            stock_close = _positive_number(
                profile.close_by_date.get(pd.Timestamp(source_date))
            )
            concept_anchor = _positive_number(
                concept_lookup.get((str(candidate["sector_id"]), anchor_date))
            )
            concept_close = _positive_number(
                concept_lookup.get(
                    (str(candidate["sector_id"]), pd.Timestamp(source_date))
                )
            )
            turnover_median = _finite_number(profile.turnover_median_20d)
            sessions_since_strong = profile.sessions_since_strong
            if (
                stock_anchor is None
                or stock_close is None
                or concept_anchor is None
                or concept_close is None
                or turnover_median is None
                or sessions_since_strong is None
            ):
                _not_ready("eligible_member_rank_features_incomplete")
            cycle_changes = profile.change_by_date.loc[
                cycle_start : pd.Timestamp(source_date)
            ]
            feature_values = {
                "cycle_relative_return": (
                    (stock_close / stock_anchor - 1.0)
                    - (concept_close / concept_anchor - 1.0)
                )
                * 100.0,
                "strong_day_count_cycle": int(
                    cycle_changes.ge(STRONG_DAY_THRESHOLD_PCT).sum()
                ),
                "sessions_since_strong": int(sessions_since_strong),
                "turnover_median_20d": float(turnover_median),
                "capacity_passed": bool(
                    turnover_median >= CAPACITY_MIN_MEDIAN_TURNOVER
                ),
            }
        else:
            feature_values = _empty_feature_values()

        rows.append(
            {
                "source_trade_date": source_date,
                "sector_id": str(candidate["sector_id"]),
                "sector_name": str(candidate["concept_name"]),
                "vt_symbol": str(candidate["vt_symbol"]),
                "cycle_id": str(candidate["cycle_id"]),
                "cycle_start": cycle_start.date(),
                "cycle_days": int(candidate["cycle_days"]),
                **feature_values,
                "excluded_reason": excluded_reason,
                "feature_cutoff": feature_cutoff,
                "membership_known_at": membership_known_at,
                "security_known_at": security_known_at,
                "membership_source": FORWARD_MEMBERSHIP_SOURCE,
                "security_source": FORWARD_SECURITY_SOURCE,
                "concept_source": CANONICAL_CONCEPT_INDEX_SOURCE,
                "membership_manifest_version": manifest_version,
                "main_rise_definition": FROZEN_MAIN_RISE_DEFINITION,
                "stock_name": str(candidate.get("name") or ""),
                "security_status": str(candidate.get("status") or ""),
            }
        )

    features = pd.DataFrame(rows, columns=columns)
    counts = {
        "active_membership_rows": len(active_members),
        "board_excluded_rows": board_excluded_rows,
        "main_board_member_count": len(candidates),
        "security_eligible_count": eligible_count,
        "security_excluded_rows": security_excluded_rows,
    }
    return features, counts


def _stock_feature_profiles(
    bars: pd.DataFrame,
    *,
    vt_symbols: Sequence[str],
    trading_dates: tuple[date, ...],
    source_date: date,
) -> dict[str, _StockFeatureProfile]:
    required = {"vt_symbol", "trade_date", "close_price", "turnover"}
    missing = sorted(required - set(bars))
    if missing:
        raise ForwardLeaderIdentityError(
            "missing stock bar columns: " + ", ".join(missing)
        )
    source = bars.copy()
    source["trade_date"] = pd.to_datetime(
        source["trade_date"], errors="raise"
    ).dt.normalize()
    source = source.loc[
        source["trade_date"].dt.date.le(source_date)
        & source["vt_symbol"].astype(str).isin(vt_symbols)
    ].copy()
    if source.duplicated(["vt_symbol", "trade_date"]).any():
        raise ForwardLeaderIdentityError("stock bar identity must be unique")

    calendar = pd.DatetimeIndex(pd.to_datetime(trading_dates)).normalize()
    source_timestamp = pd.Timestamp(source_date)
    profiles: dict[str, _StockFeatureProfile] = {}
    for vt_symbol in vt_symbols:
        group = source.loc[source["vt_symbol"].astype(str).eq(vt_symbol)].set_index(
            "trade_date"
        )
        frame = group.reindex(calendar)
        raw_close = pd.to_numeric(frame["close_price"], errors="coerce")
        source_bar_available = bool(
            source_timestamp in group.index
            and pd.notna(group.at[source_timestamp, "close_price"])
        )
        close = raw_close.ffill()
        calculated_change = close.pct_change(fill_method=None) * 100.0
        if "change_pct" in frame:
            change = pd.to_numeric(frame["change_pct"], errors="coerce")
            change = change.fillna(calculated_change)
        else:
            change = calculated_change
        change = change.fillna(0.0)
        turnover = pd.to_numeric(frame["turnover"], errors="coerce")
        turnover = turnover.where(raw_close.notna(), 0.0)
        turnover_median = turnover.rolling(20, min_periods=20).median().iloc[-1]
        strong_positions = np.flatnonzero(
            change.ge(STRONG_DAY_THRESHOLD_PCT).to_numpy(dtype=bool)
        )
        sessions_since_strong = (
            len(calendar) - 1 - int(strong_positions[-1])
            if len(strong_positions)
            else NO_STRONG_SESSION_SENTINEL
        )
        profiles[vt_symbol] = _StockFeatureProfile(
            source_bar_available=source_bar_available,
            close_by_date=close,
            change_by_date=change,
            sessions_since_strong=sessions_since_strong,
            turnover_median_20d=_finite_number(turnover_median),
        )
    return profiles


def _candidate_exclusion_reason(
    candidate: pd.Series,
    *,
    source_date: date,
    calendar: pd.DatetimeIndex,
) -> str | None:
    if pd.isna(candidate.get("security_evidence_level")):
        return "not_in_active_security_scope"
    listed_on = _as_date(candidate.get("listed_on"), label="listed_on")
    listed_sessions = int((calendar.date >= listed_on).sum())
    delisted_on = _optional_date(candidate.get("delisted_on"))
    return eligibility_reason(
        SecurityRecord(
            vt_symbol=str(candidate["vt_symbol"]),
            symbol=str(candidate["symbol"]),
            exchange=str(candidate["exchange"]),
            name=str(candidate.get("name") or ""),
            status=str(candidate.get("status") or ""),
            listed_sessions=listed_sessions,
            suspended=bool(candidate.get("suspended")),
            risk_warning=bool(candidate.get("risk_warning")),
            delisted=bool(delisted_on is not None and delisted_on <= source_date),
            evidence_level=str(candidate["security_evidence_level"]),
        ),
        source_date,
    )


def _validate_membership_scope(inputs: ForwardLeaderSourceInputs) -> datetime:
    scope = inputs.membership_scope
    if _optional_date(scope.get("source_trade_date")) != inputs.source_trade_date:
        _not_ready("membership_scope_source_date_mismatch")
    if str(scope.get("scope_type") or "") != TRADABLE_SCOPE_TYPE:
        _not_ready("membership_scope_type_mismatch")
    if str(scope.get("source") or "") != FORWARD_MEMBERSHIP_SOURCE:
        _not_ready("membership_scope_source_mismatch")
    if not bool(scope.get("complete")) or str(scope.get("evidence_level") or "") != "strict":
        _not_ready("membership_scope_not_strict_complete")
    known_at = _as_aware_datetime(scope.get("observed_at"), "membership observed_at")
    if known_at.astimezone(SHANGHAI).date() != inputs.source_trade_date:
        _not_ready("membership_scope_observation_date_mismatch")
    return known_at


def _validate_security_scope(inputs: ForwardLeaderSourceInputs) -> datetime:
    scope = inputs.security_scope
    if _optional_date(scope.get("source_trade_date")) != inputs.source_trade_date:
        _not_ready("security_scope_source_date_mismatch")
    if str(scope.get("source") or "") != FORWARD_SECURITY_SOURCE:
        _not_ready("security_scope_source_mismatch")
    if (
        not bool(scope.get("complete"))
        or str(scope.get("evidence_level") or "") != SECURITY_EVIDENCE_LEVEL
    ):
        _not_ready("security_scope_not_strict_complete")
    known_at = _as_aware_datetime(scope.get("observed_at"), "security observed_at")
    if known_at.astimezone(SHANGHAI).date() != inputs.source_trade_date:
        _not_ready("security_scope_observation_date_mismatch")
    return known_at


def _validated_memberships(
    inputs: ForwardLeaderSourceInputs,
    known_at: datetime,
) -> pd.DataFrame:
    required = {
        "source_trade_date",
        "observed_at",
        "sector_id",
        "sector_name",
        "sector_type",
        "vt_symbol",
        "evidence_level",
        "source",
    }
    frame = _required_frame(inputs.memberships, required, "membership")
    frame["source_trade_date"] = pd.to_datetime(
        frame["source_trade_date"], errors="raise"
    ).dt.date
    if not frame["source_trade_date"].eq(inputs.source_trade_date).all():
        raise ForwardLeaderIdentityError("membership record source dates must match")
    if frame.duplicated(["sector_id", "vt_symbol"]).any():
        raise ForwardLeaderIdentityError("membership record identity must be unique")
    if not frame["evidence_level"].eq("strict").all():
        raise ForwardLeaderIdentityError("membership records must be strict")
    if not frame["source"].eq(FORWARD_MEMBERSHIP_SOURCE).all():
        raise ForwardLeaderIdentityError("membership record source mismatch")
    observed = frame["observed_at"].map(
        lambda value: _as_aware_datetime(value, "membership record observed_at")
    )
    if any(value != known_at for value in observed):
        raise ForwardLeaderIdentityError("membership record observation mismatch")
    if int(inputs.membership_scope.get("row_count") or -1) != len(frame):
        _not_ready("membership_scope_row_count_mismatch")
    if int(inputs.membership_scope.get("expected_sector_count") or -1) != frame[
        "sector_id"
    ].nunique():
        _not_ready("membership_scope_sector_count_mismatch")
    return frame


def _validated_securities(
    inputs: ForwardLeaderSourceInputs,
    known_at: datetime,
) -> pd.DataFrame:
    required = {
        "source_trade_date",
        "observed_at",
        "vt_symbol",
        "symbol",
        "exchange",
        "name",
        "status",
        "listed_on",
        "delisted_on",
        "suspended",
        "risk_warning",
        "evidence_level",
        "source",
    }
    frame = _required_frame(inputs.securities, required, "security")
    frame["source_trade_date"] = pd.to_datetime(
        frame["source_trade_date"], errors="raise"
    ).dt.date
    if not frame["source_trade_date"].eq(inputs.source_trade_date).all():
        raise ForwardLeaderIdentityError("security record source dates must match")
    if frame.duplicated(["vt_symbol"]).any():
        raise ForwardLeaderIdentityError("security record identity must be unique")
    if not frame["evidence_level"].eq(SECURITY_EVIDENCE_LEVEL).all():
        raise ForwardLeaderIdentityError("security records must be strict")
    if not frame["source"].eq(FORWARD_SECURITY_SOURCE).all():
        raise ForwardLeaderIdentityError("security record source mismatch")
    observed = frame["observed_at"].map(
        lambda value: _as_aware_datetime(value, "security record observed_at")
    )
    if any(value != known_at for value in observed):
        raise ForwardLeaderIdentityError("security record observation mismatch")
    expected = int(inputs.security_scope.get("expected_symbol_count") or -1)
    returned = int(inputs.security_scope.get("returned_symbol_count") or -1)
    if expected != returned or returned != len(frame):
        _not_ready("security_scope_row_count_mismatch")
    return frame


def _validated_concept_bars(frame: pd.DataFrame, source_date: date) -> pd.DataFrame:
    required = {"sector_id", "concept_name", "trade_date", "close_price", "source"}
    result = _required_frame(frame, required, "concept bar")
    result["trade_date"] = pd.to_datetime(
        result["trade_date"], errors="raise"
    ).dt.normalize()
    result = result.loc[result["trade_date"].dt.date.le(source_date)].copy()
    if result.duplicated(["sector_id", "trade_date"]).any():
        raise ForwardLeaderIdentityError("concept bar identity must be unique")
    if not result["source"].eq(CANONICAL_CONCEPT_INDEX_SOURCE).all():
        _not_ready("canonical_concept_source_mismatch")
    return result


def _validated_benchmark_bars(frame: pd.DataFrame, source_date: date) -> pd.DataFrame:
    required = {"vt_symbol", "trade_date", "close_price", "source"}
    result = _required_frame(frame, required, "benchmark bar")
    result["trade_date"] = pd.to_datetime(
        result["trade_date"], errors="raise"
    ).dt.normalize()
    result = result.loc[result["trade_date"].dt.date.le(source_date)].copy()
    if result.duplicated(["vt_symbol", "trade_date"]).any():
        raise ForwardLeaderIdentityError("benchmark bar identity must be unique")
    return result


def _validated_trading_dates(
    values: Sequence[date],
    source_date: date,
) -> tuple[date, ...]:
    dates = tuple(sorted(set(values)))
    if len(dates) < 25 or not dates or dates[-1] != source_date:
        _not_ready("completed_trading_calendar_incomplete")
    return dates


def _rank_row(
    row: pd.Series,
    *,
    source_date: date,
    mode: LeaderIdentityMode,
    known_at: datetime,
    feature_cutoff: datetime,
    membership_known_at: datetime,
    security_known_at: datetime,
    fingerprint: str,
) -> ForwardLeaderRankRow:
    return ForwardLeaderRankRow(
        source_trade_date=source_date,
        ranking_version=FORWARD_LEADER_RANKING_VERSION,
        identity_mode=mode.value,
        sector_id=str(row["sector_id"]),
        vt_symbol=str(row["vt_symbol"]),
        target_session=FORWARD_TARGET_SESSION,
        target_trade_date=None,
        known_at=known_at,
        feature_cutoff=feature_cutoff,
        membership_known_at=membership_known_at,
        security_known_at=security_known_at,
        sector_name=str(row["sector_name"]),
        cycle_id=str(row["cycle_id"]),
        cycle_start=_as_date(row["cycle_start"], label="cycle_start"),
        cycle_days=int(row["cycle_days"]),
        cycle_relative_return=_finite_number(row["cycle_relative_return"]),
        strong_day_count_cycle=_optional_int(row["strong_day_count_cycle"]),
        sessions_since_strong=_optional_int(row["sessions_since_strong"]),
        turnover_median_20d=_finite_number(row["turnover_median_20d"]),
        capacity_passed=bool(row["capacity_passed"]),
        relative_strength_rank=_optional_int(row["relative_strength_rank"]),
        market_recognition_rank=_optional_int(row["market_recognition_rank"]),
        rank=_optional_int(row["rank"]),
        rank_eligible=bool(row["rank_eligible"]),
        is_top3=bool(row["is_top3"]),
        excluded_reason=(
            None if pd.isna(row["excluded_reason"]) else str(row["excluded_reason"])
        ),
        input_fingerprint=fingerprint,
        evidence_level=FORWARD_RANK_EVIDENCE_LEVEL,
        raw={
            "stock_name": str(row.get("stock_name") or ""),
            "security_status": str(row.get("security_status") or ""),
            "membership_manifest_version": str(
                row.get("membership_manifest_version") or ""
            ),
        },
    )


def _closed_capture(
    inputs: ForwardLeaderSourceInputs,
    blocking_reason: str,
) -> ForwardLeaderCapture:
    feature_cutoff = datetime.combine(
        inputs.source_trade_date,
        FEATURE_CUTOFF_TIME,
        tzinfo=SHANGHAI,
    )
    payload = json.dumps(
        {
            "source_trade_date": inputs.source_trade_date.isoformat(),
            "ranking_version": FORWARD_LEADER_RANKING_VERSION,
            "blocking_reason": blocking_reason,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    scopes = tuple(
        ForwardLeaderRankScope(
            source_trade_date=inputs.source_trade_date,
            ranking_version=FORWARD_LEADER_RANKING_VERSION,
            identity_mode=mode.value,
            target_session=FORWARD_TARGET_SESSION,
            target_trade_date=None,
            known_at=inputs.attempted_at,
            feature_cutoff=feature_cutoff,
            main_rise_definition=FROZEN_MAIN_RISE_DEFINITION,
            active_concept_count=0,
            membership_row_count=len(inputs.memberships),
            main_board_member_count=0,
            security_eligible_count=0,
            ranked_row_count=0,
            top3_row_count=0,
            excluded_row_count=0,
            complete=False,
            status="blocked",
            input_fingerprint=fingerprint,
            selected_mode=None,
            evidence_level="rejected_incomplete_forward_inputs",
            raw={
                "blocking_reason": blocking_reason,
                "low_suction_outcomes_read": False,
            },
        )
        for mode in LeaderIdentityMode
    )
    return ForwardLeaderCapture(
        source_trade_date=inputs.source_trade_date,
        ranking_version=FORWARD_LEADER_RANKING_VERSION,
        input_fingerprint=fingerprint,
        rows=(),
        scopes=scopes,
    )


def _feature_columns() -> list[str]:
    return [
        "source_trade_date",
        "sector_id",
        "sector_name",
        "vt_symbol",
        "cycle_id",
        "cycle_start",
        "cycle_days",
        "cycle_relative_return",
        "strong_day_count_cycle",
        "sessions_since_strong",
        "turnover_median_20d",
        "capacity_passed",
        "excluded_reason",
        "feature_cutoff",
        "membership_known_at",
        "security_known_at",
        "membership_source",
        "security_source",
        "concept_source",
        "membership_manifest_version",
        "main_rise_definition",
        "stock_name",
        "security_status",
    ]


def _empty_feature_values() -> dict[str, object]:
    return {
        "cycle_relative_return": np.nan,
        "strong_day_count_cycle": np.nan,
        "sessions_since_strong": np.nan,
        "turnover_median_20d": np.nan,
        "capacity_passed": False,
    }


def _required_frame(
    frame: pd.DataFrame,
    required: set[str],
    label: str,
) -> pd.DataFrame:
    missing = sorted(required - set(frame))
    if missing:
        raise ForwardLeaderIdentityError(
            f"missing {label} columns: " + ", ".join(missing)
        )
    return frame.copy()


def _reject_future_or_outcome_columns(*frames: pd.DataFrame) -> None:
    prohibited: set[str] = set()
    for frame in frames:
        prohibited.update(
            str(column)
            for column in frame.columns
            if str(column) in PROHIBITED_OUTCOME_COLUMNS
            or str(column).lower().startswith(PROHIBITED_OUTCOME_PREFIXES)
            or str(column).lower().startswith(("future_", "outcome_", "exit_"))
        )
    if prohibited:
        raise ValueError(
            "future or outcome columns are prohibited from forward identity inputs: "
            + ", ".join(sorted(prohibited))
        )


def _symbol_exchange(value: object) -> tuple[str, str]:
    parts = str(value).strip().upper().rsplit(".", 1)
    if len(parts) != 2 or not all(parts):
        raise ForwardLeaderIdentityError(f"invalid vt_symbol: {value}")
    return parts[0], parts[1]


def _as_aware_datetime(value: object, label: str) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ForwardLeaderIdentityError(f"{label} must be timezone-aware")
    return timestamp.to_pydatetime()


def _require_aware(value: datetime, *, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ForwardLeaderIdentityError(f"{label} must be timezone-aware")


def _as_date(value: object, *, label: str) -> date:
    parsed = _optional_date(value)
    if parsed is None:
        raise ForwardLeaderIdentityError(f"{label} must be a date")
    return parsed


def _optional_date(value: object) -> date | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date()


def _positive_number(value: object) -> float | None:
    number = _finite_number(value)
    if number is None or number <= 0:
        return None
    return number


def _finite_number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if np.isfinite(number) else None


def _optional_int(value: object) -> int | None:
    number = _finite_number(value)
    return int(number) if number is not None else None


def _report_number(value: object) -> str:
    number = _finite_number(value)
    return f"{number:.4f}" if number is not None else "-"


def _not_ready(reason: str) -> None:
    raise _ForwardLeaderNotReady(reason)
