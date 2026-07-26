"""Live quote collection and snapshot construction for the limit-up desk."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from time import monotonic
from zoneinfo import ZoneInfo

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.market.cache import TTLCache
from alphaagent.server.services.limit_up.domain import (
    is_eligible_main_board,
    main_board_limit_price,
    normalize_limit_time,
)
from alphaagent.server.services.limit_up.concept_live_service import (
    get_latest_live_concept_snapshot,
)
from alphaagent.server.services.limit_up.concept_resonance import (
    aggregate_concept_strength,
    attach_candidate_concepts,
    rank_concepts,
)
from alphaagent.server.services.limit_up.live_policy import (
    MAX_CONSECUTIVE_SNAPSHOT_GAP_MINUTES,
    build_first_board_execution_checks_at_time,
    build_early_radar_signals,
    build_live_market_gate,
    build_live_recommendations,
    rank_live_candidates,
    rank_live_opportunities,
    session_stage,
)
from alphaagent.server.services.limit_up.live_evidence import attach_historical_evidence
from alphaagent.server.services.limit_up.first_board_quality import (
    build_preboard_pools,
    evaluate_first_board_quality_at_time,
)
from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PREBOARD_DECISION_VERSION,
    apply_preboard_parity_contract,
    is_strictly_preboard,
    preboard_market_gate,
)
from alphaagent.server.services.limit_up.preboard_live_minute_buffer import (
    LiveMinuteBuffer,
)
from alphaagent.server.services.limit_up.first_board_dual_lane import (
    attach_rotation_shadow,
)
from alphaagent.server.services.limit_up.first_board_profitability import (
    rank_first_board_signals,
)
from alphaagent.server.services.limit_up.lane_research import (
    classify_board_lane,
    evaluate_lane_candidate,
    select_daily_lane_portfolio,
)
from alphaagent.server.services.limit_up.live_repository import (
    load_latest_daily_trade_date,
    load_latest_lane_validations,
    load_latest_snapshot,
    load_live_context,
    save_snapshot,
)
from alphaagent.server.services.limit_up.live_trace_repository import (
    save_live_trace_error,
    save_live_trace_snapshot,
)
from alphaagent.server.services.limit_up.sector_warmup import (
    attach_dynamic_group_leader_ranks,
    live_warmup_observation,
)
from alphaagent.server.services.limit_up.radar_contract import (
    CAPTURE_MIN_CHANGE_PCT,
    capture_state,
    is_formal_candidate,
)
from alphaagent.server.services.limit_up.radar_observation_repository import (
    build_fill_followup_observations,
    load_recent_signal_observations,
    project_observation as project_radar_observation,
    save_frame as save_radar_frame,
)
from alphaagent.server.services.limit_up import (
    core_quality,
    history_engine,
    history_repository,
    preboard_decision_repository,
    preboard_decision_service,
    regime_shadow,
    scheduled_execution,
)
from alphaagent.server.services.limit_up.versions import (
    LIVE_STRATEGY_VERSION as STRATEGY_VERSION,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
NEAR_LIMIT_MIN_CHANGE_PCT = 7.0
TRACE_RADAR_MIN_CHANGE_PCT = CAPTURE_MIN_CHANGE_PCT
FAST_QUOTE_PAGES = (1, 2, 3, 4)
FAST_QUOTE_PAGE_SIZE = 100
RESEARCH_QUOTE_ENRICHMENT_MAX_AGE_SECONDS = 20.0
RESEARCH_QUOTE_ENRICHMENT_FIELDS = (
    "quote_speed",
    "quote_amplitude_pct",
    "quote_main_net_inflow",
    "quote_main_inflow",
    "quote_main_outflow",
    "quote_main_net_inflow_ratio",
)
LIVE_SCAN_INTERVAL_SECONDS = 10
LIVE_SNAPSHOT_MAX_AGE_SECONDS = 90
HISTORY_EVIDENCE_UNAVAILABLE_REASON = "历史证据不可用，已禁止执行"
EXECUTABLE_ACTIONS = frozenset({"buy_now", "next_auction"})
PORTFOLIO_EXECUTION_LANES = frozenset(
    scheduled_execution.PRODUCT_EXECUTION_LANES
)
LIVE_WATCHLIST_LIMIT = 6
ACTIVE_SESSION_STAGES = frozenset(
    {"auction_watch", "auction", "morning", "afternoon", "tail", "close_auction"}
)
LIVE_PREBOARD_EVIDENCE_FIELDS = (
    "historical_evidence",
    "financial_risk",
    "execution_checks",
    "entry_window_passed",
    "snapshot_fresh",
    "quote_fresh",
    "risk_gate_passed",
    "concept_id",
    "concept_strength_score",
    "concept_leader_rank",
    "transaction_status",
    "transaction_features",
)
DYNAMIC_LEADER_PUBLIC_FIELDS = (
    "policy_version",
    "status",
    "execution_effect",
    "market_gate_passed",
    "concept_id",
    "concept_name",
    "concept_state",
    "concept_leader_rank",
    "locked_at",
    "observed_frames",
    "eligible_frames",
    "consecutive_eligible_frames",
    "persistence_ratio",
    "drop_count",
    "current_concept_top5",
    "global_rank",
    "global_top5",
)
LIVE_PREBOARD_FORBIDDEN_FIELDS = frozenset(
    {
        "action",
        "entry_kind",
        "signal_state",
        "buy_now",
        "portfolio_selected",
        "formal_action",
        "formal_rank",
        "daily_slot",
        "physical_touch_at",
        "first_limit_time",
        "last_limit_time",
        "final_sealed",
        "d1_trade_date",
        "d1_close_price",
        "d1_net_return_pct",
        "net_return_pct",
    }
)
logger = logging.getLogger(__name__)
_LIVE_LANE_VALIDATION_CACHE = TTLCache(max_items=4)
LIVE_LANE_VALIDATION_CACHE_SECONDS = 21_600
_PREBOARD_MINUTE_BUFFER = LiveMinuteBuffer()


class LiveSnapshotUnavailable(RuntimeError):
    """Raised when all live sources fail and no saved snapshot exists."""


def build_live_snapshot(
    quote_payload: Mapping[str, object],
    pool_payload: Mapping[str, object],
    captured_at: datetime,
    stock_context: Mapping[str, object],
    previous_snapshot: Mapping[str, object] | None = None,
    lane_validations: Mapping[str, Mapping[str, object]] | None = None,
    *,
    concept_snapshot: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build a no-lookahead recommendation snapshot from visible market data."""

    local_at = _local_datetime(captured_at)
    radar_quote_payload = _quote_payload_with_full_radar(
        quote_payload,
        concept_snapshot,
    )
    market_date = _resolved_market_date(
        radar_quote_payload,
        pool_payload,
        local_at,
        stock_context,
    )
    source_rows = _merge_source_rows(
        radar_quote_payload,
        pool_payload,
        include_previous=session_stage(local_at) in {"auction_watch", "auction"},
        min_change_pct=TRACE_RADAR_MIN_CHANGE_PCT,
    )
    capture_candidates = _enrich_candidates(
        source_rows,
        pool_payload,
        stock_context,
        require_sector=False,
    )
    attach_candidate_concepts(capture_candidates, concept_snapshot or {})
    candidates = [
        dict(candidate)
        for candidate in capture_candidates
        if candidate.get("previous_limit_up") is True
        or is_formal_candidate(
            change_pct=_number(candidate.get("change_pct")) or -100.0,
            state=str(candidate.get("state") or ""),
        )
    ]
    market_context = _market_context(candidates, stock_context, previous_snapshot)
    market_gate = build_live_market_gate(
        market_context,
        local_at,
        previous_snapshot,
    )
    stale_market_date = market_date != local_at.date() or session_stage(local_at) == "closed"
    snapshot_mode = "stale_snapshot" if stale_market_date else "live_snapshot"
    evaluated = rank_live_candidates(
        candidates,
        limit=len(candidates),
    )
    _attach_lane_decisions(
        evaluated,
        market_context,
        local_at,
        market_gate=market_gate,
    )
    _attach_warmup_shadow(evaluated)
    _attach_stability(evaluated, previous_snapshot, local_at)
    evaluated[:] = attach_rotation_shadow(
        evaluated,
        {
            "trade_date": market_date.isoformat(),
            "captured_at": local_at.isoformat(),
            "session_stage": session_stage(local_at),
            "mode": snapshot_mode,
            "data_quality": {"is_stale": stale_market_date},
        },
    )
    ranked = rank_live_opportunities(evaluated, limit=len(evaluated))
    recommendations = build_live_recommendations(
        ranked,
        market_context,
        local_at,
        previous_snapshot=previous_snapshot,
        market_gate=market_gate,
    )
    recommendations = _without_removed_lane_recommendations(recommendations)
    early_candidates, early_recommendations = _build_early_radar_evaluation(
        capture_candidates,
        market_context,
        local_at,
        previous_snapshot,
        market_gate,
        market_date,
        snapshot_mode,
    )
    ranked = [
        candidate
        for candidate in ranked
        if str(candidate.get("board_lane") or "") != "one_to_two"
    ]
    if lane_validations is not None:
        recommendations = apply_lane_validation_veto(
            recommendations,
            lane_validations,
        )
    source_errors = list(stock_context.get("source_errors") or [])
    concept_quality = (
        concept_snapshot.get("data_quality")
        if isinstance(concept_snapshot, Mapping)
        else None
    )
    concept_quality = concept_quality if isinstance(concept_quality, Mapping) else {}
    if not concept_snapshot:
        source_errors.append("concept_snapshot:unavailable")
    source_updated_at = _latest_source_time(
        radar_quote_payload,
        pool_payload,
        concept_snapshot or {},
    )
    return {
        "trade_date": market_date.isoformat(),
        "captured_at": local_at.isoformat(),
        "session_stage": session_stage(local_at),
        "strategy_version": STRATEGY_VERSION,
        "mode": snapshot_mode,
        "source": _source_name(radar_quote_payload, pool_payload),
        "source_updated_at": source_updated_at,
        "market_context": market_context,
        "trace_capture_candidates": _preboard_capture_candidates(
            early_candidates
        ),
        "early_radar_recommendations": early_recommendations,
        "trace_radar_candidates": [dict(candidate) for candidate in ranked],
        "candidates": ranked,
        "recommendations": recommendations,
        "data_quality": {
            "status": "stale" if stale_market_date else ("degraded" if source_errors else "ready"),
            "is_stale": stale_market_date,
            "execution_confidence": "proxy_without_l2",
            "has_tick": False,
            "has_l2": False,
            "candidate_universe_count": len(candidates),
            "capture_candidate_count": len(capture_candidates),
            "trace_radar_candidate_count": len(ranked),
            "radar_candidate_count": len(ranked),
            "ranked_candidate_count": len(ranked),
            "concept_status": concept_quality.get("status") or "unavailable",
            "concept_snapshot_age_seconds": concept_quality.get("age_seconds"),
            "concept_quote_coverage_ratio": concept_quality.get(
                "quote_coverage_ratio"
            ),
            "concept_trigger_allowed": concept_quality.get("trigger_allowed") is True,
            "concept_membership_snapshot_date": (
                concept_snapshot.get("membership_snapshot_date")
                if isinstance(concept_snapshot, Mapping)
                else None
            ),
            "fast_quote_pages_requested": quote_payload.get(
                "fast_quote_pages_requested"
            )
            or [],
            "fast_quote_pages_succeeded": quote_payload.get(
                "fast_quote_pages_succeeded"
            )
            or [],
            "fast_quote_pages_failed": quote_payload.get(
                "fast_quote_pages_failed"
            )
            or [],
            "fast_quote_page_coverage_ratio": _number(
                quote_payload.get("fast_quote_page_coverage_ratio")
            ),
            "fast_quote_item_count": _integer(
                quote_payload.get("fast_quote_item_count"),
                len(_items(quote_payload)),
            ),
            "snapshot_age_seconds": 0,
            "source_age_seconds": _source_age_seconds(source_updated_at, local_at),
            "background_refresh_seconds": LIVE_SCAN_INTERVAL_SECONDS,
            "rate_limit_status": _rate_limit_status(source_errors),
            "source_errors": source_errors,
            "limitations": [
                "公共行情没有L2排队位置、撤单速度和逐笔成交，成交判断仅为盘口代理。",
                "封板买点仅表示可尝试涨停价排队，不代表成交；必须以委托回报为准。",
            ],
        },
    }


def _preboard_capture_candidates(
    candidates: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [
        dict(candidate)
        for candidate in candidates
        if (
            (change_pct := _number(candidate.get("change_pct"))) is not None
            and change_pct >= TRACE_RADAR_MIN_CHANGE_PCT
        )
    ]


def live_preboard_adapter_rows(
    snapshot: Mapping[str, object],
) -> list[dict[str, object]]:
    """Build pre-trigger inputs without letting old recommendations define membership."""

    raw_rows = snapshot.get("trace_capture_candidates")
    raw_rows = raw_rows if isinstance(raw_rows, list) else []
    evidence_by_symbol = _early_preboard_evidence_by_symbol(snapshot)
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            continue
        symbol = str(raw.get("vt_symbol") or "").strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        merged = {
            key: value
            for key, value in raw.items()
            if key not in LIVE_PREBOARD_FORBIDDEN_FIELDS
        }
        evidence = evidence_by_symbol.get(symbol, {})
        merged.update(
            {
                field: evidence[field]
                for field in LIVE_PREBOARD_EVIDENCE_FIELDS
                if field in evidence
            }
        )
        merged["candidate_source_kind"] = "live_trace_capture"
        result.append(apply_preboard_parity_contract(merged))
    return result


def _early_preboard_evidence_by_symbol(
    snapshot: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    recommendations = snapshot.get("early_radar_recommendations")
    recommendations = recommendations if isinstance(recommendations, Mapping) else {}
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, Mapping) else {}
    result: dict[str, dict[str, object]] = {}
    lane_names = [
        *(
            name
            for name in ("now", "tail", "next_auction")
            if name in lanes
        ),
        *(sorted(str(name) for name in lanes if name not in {"now", "tail", "next_auction"})),
    ]
    for lane_name in lane_names:
        rows = lanes.get(lane_name)
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            continue
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            symbol = str(raw.get("vt_symbol") or "").strip()
            if not symbol:
                continue
            evidence = result.setdefault(symbol, {})
            evidence.update(
                {
                    field: raw[field]
                    for field in LIVE_PREBOARD_EVIDENCE_FIELDS
                    if field in raw
                }
            )
    return result


def _build_early_radar_evaluation(
    capture_candidates: Sequence[Mapping[str, object]],
    market_context: Mapping[str, object],
    captured_at: datetime,
    previous_snapshot: Mapping[str, object] | None,
    market_gate: Mapping[str, object],
    market_date: date,
    snapshot_mode: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Evaluate the 3% universe without adding a second public recommendation."""

    evaluated = rank_live_candidates(
        capture_candidates,
        limit=len(capture_candidates),
    )
    _attach_lane_decisions(
        evaluated,
        market_context,
        captured_at,
        market_gate=market_gate,
    )
    _attach_warmup_shadow(evaluated)
    _attach_stability(evaluated, previous_snapshot, captured_at)
    evaluated[:] = attach_rotation_shadow(
        evaluated,
        {
            "trade_date": market_date.isoformat(),
            "captured_at": captured_at.isoformat(),
            "session_stage": session_stage(captured_at),
            "mode": snapshot_mode,
            "data_quality": {"is_stale": snapshot_mode != "live_snapshot"},
        },
    )
    ranked = rank_live_opportunities(evaluated, limit=len(evaluated))
    signals = build_early_radar_signals(ranked, market_gate, captured_at)
    return ranked, {
        "captured_at": captured_at.isoformat(),
        "session_stage": session_stage(captured_at),
        "market_gate": dict(market_gate),
        "lanes": {"now": signals, "tail": [], "next_auction": []},
    }


def refresh_live_snapshot(
    captured_at: datetime | None = None,
    *,
    adapter: AkShareAdapter | None = None,
    persist: bool = True,
) -> dict[str, object]:
    """Collect current quotes, build recommendations, and optionally persist them."""

    fixed_capture_time = captured_at is not None
    local_at = _local_datetime(captured_at or _now_shanghai())
    if not _is_active_session(local_at):
        return _latest_snapshot_for_session(local_at)
    live_adapter = adapter or AkShareAdapter()
    scan_started = monotonic()
    try:
        stage = session_stage(local_at)
        planned_symbols = _planned_symbols() if stage in {"auction_watch", "auction"} else []
        if planned_symbols:
            quotes, pools, source_errors = _fetch_live_payloads(
                live_adapter,
                local_at,
                planned_symbols=planned_symbols,
            )
        else:
            quotes, pools, source_errors = _fetch_live_payloads(live_adapter, local_at)
        quotes_ready_at = local_at if fixed_capture_time else _now_shanghai()
        concept_snapshot = get_latest_live_concept_snapshot(quotes_ready_at)
        concept_snapshot = _concept_snapshot_with_incremental_quotes(
            concept_snapshot,
            quotes,
            pools,
            quotes_ready_at,
        )
        radar_quotes = _quote_payload_with_full_radar(quotes, concept_snapshot)
        _PREBOARD_MINUTE_BUFFER.ingest(quotes_ready_at, _items(radar_quotes))
        symbols = _candidate_symbols(
            radar_quotes,
            pools,
            include_previous=stage in {"auction_watch", "auction"},
        )
        market_date = _resolved_market_date(radar_quotes, pools, quotes_ready_at, {})
        quotes_done = monotonic()
        context = load_live_context(symbols, market_date) if symbols else {"by_symbol": {}}
        context = {**context, "source_errors": source_errors}
        lane_validations = _load_lane_validations()
        previous = load_latest_snapshot(market_date, strategy_version=STRATEGY_VERSION)
        context_done = monotonic()
        evaluation_at = local_at if fixed_capture_time else _now_shanghai()
        snapshot = build_live_snapshot(
            quotes,
            pools,
            evaluation_at,
            context,
            previous_snapshot=previous,
            concept_snapshot=concept_snapshot,
        )
        snapshot = _apply_live_risk_gates(snapshot, lane_validations)
        snapshot = _attach_research_quote_enrichment(
            snapshot,
            quotes.get("_research_quote_enrichment"),
            evaluation_at,
        )
        _attach_preboard_quality_pool_prefix(snapshot, evaluation_at)
        if persist:
            snapshot = regime_shadow.attach_regime_failure_shadow(snapshot)
        policy_done = monotonic()
        if persist:
            _set_live_trace_cache_status(
                snapshot,
                _save_live_trace_safely(snapshot),
            )
        trace_done = monotonic()
        _set_scan_timing(
            snapshot,
            scan_started=scan_started,
            quotes_done=quotes_done,
            context_done=context_done,
            policy_done=policy_done,
            persistence_done=trace_done,
        )
        persisted_formal_snapshot: dict[str, object] | None = None
        if persist and _is_radar_persistable_snapshot(snapshot, evaluation_at):
            full_quotes = (
                concept_snapshot.get("quotes")
                if isinstance(concept_snapshot, Mapping)
                else None
            )
            full_quotes = full_quotes if isinstance(full_quotes, list) else []
            quote_observed_at = _radar_quote_observed_at(
                concept_snapshot,
                radar_quotes,
            )
            radar_error = _save_radar_ledger_safely(
                snapshot,
                full_quotes=full_quotes,
                quote_observed_at=quote_observed_at,
            )
            _set_radar_ledger_status(snapshot, radar_error)
            if radar_error is None:
                if (
                    _has_preboard_scoring_work(snapshot)
                    and _is_persistable_snapshot(snapshot, evaluation_at)
                ):
                    persisted_formal_snapshot = save_snapshot(
                        _without_internal_radar_fields(snapshot)
                    )
                # The formal 10-second scan must never wait for per-symbol
                # minute or transaction network fallbacks.  The shared feature
                # contract records an explicit missing-prefix state until the
                # in-process completed-minute buffer is scoreable.
                _run_preboard_decision_safely(snapshot)
            else:
                _set_preboard_decision_status(
                    snapshot,
                    {"status": "skipped_radar_error"},
                )
        elif persist:
            _set_radar_ledger_status(snapshot, None, skipped=True)
            _set_preboard_decision_status(
                snapshot,
                {"status": "skipped_invalid_frame"},
            )
        public_snapshot = _without_internal_radar_fields(snapshot)
        if persist and _is_persistable_snapshot(public_snapshot, evaluation_at):
            if persisted_formal_snapshot is None:
                return save_snapshot(public_snapshot)
            try:
                return save_snapshot(public_snapshot)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "preboard-enriched live snapshot write failed: %s",
                    exc,
                )
                return persisted_formal_snapshot
        return public_snapshot
    except Exception as exc:
        logger.exception("limit-up live refresh failed")
        trace_error = _save_live_trace_error_safely(local_at, exc) if persist else None
        fallback = load_latest_snapshot(strategy_version=STRATEGY_VERSION)
        if fallback is None:
            raise LiveSnapshotUnavailable(str(exc)) from exc
        stale = _stale_snapshot(fallback, exc)
        if persist:
            _set_live_trace_cache_status(stale, trace_error)
        return stale


def _attach_preboard_quality_pool_prefix(
    snapshot: dict[str, object],
    decision_at: datetime,
) -> None:
    """Record the completed-minute quality cross-section for shared scoring."""

    recommendations = snapshot.get("early_radar_recommendations")
    recommendations = (
        recommendations if isinstance(recommendations, Mapping) else {}
    )
    market_gate = recommendations.get("market_gate")
    market_gate = market_gate if isinstance(market_gate, Mapping) else {}
    quality = snapshot.get("data_quality")
    quality = dict(quality) if isinstance(quality, Mapping) else {}
    try:
        pools = build_preboard_pools(
            live_preboard_adapter_rows(snapshot),
            decision_at=decision_at,
            market_gate=preboard_market_gate(market_gate),
        )
        _PREBOARD_MINUTE_BUFFER.ingest_quality_pool(
            decision_at,
            pools.quality_pool,
        )
        quality["preboard_minute_buffer_status"] = "ready"
        quality["preboard_adapter_input_count"] = pools.adapter_input_count
        quality["preboard_capture_pool_count"] = len(pools.capture_pool)
        quality["preboard_eligible_pool_count"] = len(
            pools.eligible_first_board_pool
        )
        quality["preboard_quality_pool_count"] = len(pools.quality_pool)
        quality["preboard_rejection_counts"] = dict(pools.rejection_counts)
        quality.pop("preboard_minute_buffer_error", None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("preboard minute quality pool failed: %s", exc)
        quality["preboard_minute_buffer_status"] = "error"
        quality["preboard_minute_buffer_error"] = str(exc)[:500]
    snapshot["data_quality"] = quality


def get_latest_live_snapshot(now: datetime | None = None) -> dict[str, object]:
    """Return only persisted background snapshots; GET never calls quote providers."""

    local_now = _local_datetime(now or datetime.now(SHANGHAI))
    if session_stage(local_now) == "lunch":
        morning = load_latest_snapshot(
            local_now.date(),
            strategy_version=STRATEGY_VERSION,
        )
        if morning is not None and morning.get("mode") == "live_snapshot":
            paused = downgrade_snapshot_to_stale(
                morning,
                local_now.date(),
                reason="午间休市，展示上午最后快照；13:00后恢复实时扫描",
                resolved_session_stage="lunch",
            )
            return _without_internal_radar_fields(
                _with_snapshot_age(paused, local_now)
            )
    if not _is_active_session(local_now):
        return _without_internal_radar_fields(
            _with_snapshot_age(_latest_snapshot_for_session(local_now), local_now)
        )

    saved = load_latest_snapshot(local_now.date(), strategy_version=STRATEGY_VERSION)
    if saved is not None:
        return _without_internal_radar_fields(_with_snapshot_age(saved, local_now))
    return _without_internal_radar_fields(
        _with_snapshot_age(_latest_snapshot_for_session(local_now), local_now)
    )


def _latest_snapshot_for_session(local_at: datetime) -> dict[str, object]:
    from alphaagent.server.services.limit_up.next_session_plan import (
        get_latest_next_session_plan,
    )

    plan = get_latest_next_session_plan()
    if plan is not None:
        recommendations = plan.get("recommendations")
        recommendations = dict(recommendations) if isinstance(recommendations, Mapping) else {}
        recommendations["execution_schedule"] = (
            scheduled_execution.next_session_execution_clock()
        )
        return {**dict(plan), "recommendations": recommendations}
    latest_trade_date = load_latest_daily_trade_date(local_at.date())
    snapshot = load_latest_snapshot(strategy_version=STRATEGY_VERSION)
    if snapshot is None:
        return empty_live_snapshot(local_at, trade_date=latest_trade_date)
    return _snapshot_for_session(snapshot, local_at, latest_trade_date)


def _is_persistable_snapshot(
    snapshot: Mapping[str, object],
    captured_at: datetime,
) -> bool:
    quality = snapshot.get("data_quality")
    snapshot_at = _parsed_datetime(snapshot.get("captured_at"))
    return (
        _is_active_session(captured_at)
        and snapshot.get("mode") == "live_snapshot"
        and isinstance(quality, Mapping)
        and quality.get("is_stale") is False
        and _parsed_date(snapshot.get("trade_date")) == captured_at.date()
        and snapshot_at is not None
        and snapshot_at.date() == captured_at.date()
    )


def _is_active_session(value: datetime) -> bool:
    return session_stage(value) in ACTIVE_SESSION_STAGES


def empty_live_snapshot(
    captured_at: datetime | None = None,
    *,
    trade_date: date | None = None,
) -> dict[str, object]:
    local_at = _local_datetime(captured_at or datetime.now(SHANGHAI))
    return {
        "status": "empty",
        "trade_date": (trade_date or local_at.date()).isoformat(),
        "captured_at": None,
        "session_stage": session_stage(local_at),
        "strategy_version": STRATEGY_VERSION,
        "mode": "stale_snapshot" if trade_date and trade_date != local_at.date() else "live_snapshot",
        "source": "unavailable",
        "source_updated_at": None,
        "market_context": {},
        "candidates": [],
        "preboard_candidates": [],
        "recommendations": {
            "captured_at": None,
            "session_stage": session_stage(local_at),
            "market_gate": {"passed": False, "reasons": ["当前没有已保存的盘中快照"]},
            "lanes": {"now": [], "tail": [], "next_auction": []},
        },
        "data_quality": {
            "status": "empty",
            "is_stale": True,
            "execution_confidence": "unavailable",
            "has_tick": False,
            "has_l2": False,
            "snapshot_age_seconds": None,
            "source_age_seconds": None,
            "background_refresh_seconds": LIVE_SCAN_INTERVAL_SECONDS,
            "rate_limit_status": "unknown",
            "source_errors": [],
            "limitations": ["等待交易时段首次实时扫描。"],
        },
    }


def _fetch_live_payloads(
    adapter: AkShareAdapter,
    captured_at: datetime,
    *,
    planned_symbols: Sequence[str] = (),
) -> tuple[dict[str, object], dict[str, object], list[str]]:
    trade_key = captured_at.strftime("%Y%m%d")
    quote_pages: dict[int, dict[str, object]] = {}
    research_pages: dict[int, dict[str, object]] = {}
    research_errors: list[str] = []
    pool_payload: dict[str, object] = {}
    errors: list[str] = []
    research_loader = getattr(adapter, "research_quote_flow_page", None)
    research_enabled = callable(research_loader)
    worker_count = len(FAST_QUOTE_PAGES) + 1
    if research_enabled:
        worker_count += len(FAST_QUOTE_PAGES)
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        quote_futures = {
            page: executor.submit(
                adapter.list_stocks,
                page=page,
                page_size=FAST_QUOTE_PAGE_SIZE,
                sort="change_pct",
                order="desc",
            )
            for page in FAST_QUOTE_PAGES
        }
        research_futures = (
            {
                page: executor.submit(
                    research_loader,
                    page=page,
                    page_size=FAST_QUOTE_PAGE_SIZE,
                )
                for page in FAST_QUOTE_PAGES
            }
            if research_enabled
            else {}
        )
        pool_future = executor.submit(adapter.limit_up_pools, trade_key)
        for page, future in quote_futures.items():
            try:
                quote_pages[page] = _validated_fast_quote_page(future.result())
            except Exception as exc:  # noqa: BLE001
                errors.append(_source_error(f"quotes_page_{page}", exc))
        for page, future in research_futures.items():
            try:
                research_pages[page] = _validated_research_quote_page(
                    future.result()
                )
            except Exception as exc:  # noqa: BLE001
                research_errors.append(
                    _source_error(f"research_quotes_page_{page}", exc)
                )
        try:
            raw_pool_payload = pool_future.result()
            if not isinstance(raw_pool_payload, Mapping) or not raw_pool_payload:
                raise ValueError("empty limit-up pool payload")
            pool_payload = dict(raw_pool_payload)
        except Exception as exc:  # noqa: BLE001
            errors.append(_source_error("pools", exc))

    quote_payload = _merge_fast_quote_pages(quote_pages)
    if research_enabled:
        quote_payload["_research_quote_enrichment"] = (
            _merge_research_quote_pages(research_pages, research_errors)
        )
    payloads = {
        "quotes": quote_payload,
        "pools": pool_payload,
    }
    requests = _planned_quote_requests(planned_symbols)
    if requests:
        try:
            targeted = [quote.to_api() for quote in adapter.get_quotes(requests)]
            quote_payload = dict(payloads["quotes"])
            rows = {
                str(row.get("vt_symbol") or ""): dict(row)
                for row in _items(quote_payload)
                if row.get("vt_symbol")
            }
            for row in targeted:
                if row.get("vt_symbol"):
                    rows[str(row["vt_symbol"])] = {
                        **row,
                        "quote_observed_at": (
                            row.get("quote_observed_at") or captured_at.isoformat()
                        ),
                    }
            sources = [str(quote_payload.get("source") or "").strip()]
            sources.extend(str(row.get("source") or "").strip() for row in targeted)
            payloads["quotes"] = {
                **quote_payload,
                "trade_date": quote_payload.get("trade_date") or trade_key,
                "items": list(rows.values()),
                "source": ",".join(dict.fromkeys(value for value in sources if value)),
                "updated_at": quote_payload.get("updated_at") or captured_at.isoformat(),
            }
        except Exception as exc:  # noqa: BLE001
            errors.append(_source_error("planned_quotes", exc))
    if not quote_pages and not pool_payload:
        raise LiveSnapshotUnavailable("实时涨幅榜和涨停池均不可用")
    return payloads["quotes"], payloads["pools"], errors


def _validated_fast_quote_page(payload: object) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise TypeError("fast quote page must be a mapping")
    result = dict(payload)
    items = _items(result)
    if not items or not any(row.get("vt_symbol") for row in items):
        raise ValueError("fast quote page has no symbol rows")
    if _parsed_datetime(result.get("updated_at")) is None:
        raise ValueError("fast quote page has no valid source time")
    result["items"] = items
    return result


def _validated_research_quote_page(payload: object) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise TypeError("research quote page must be a mapping")
    result = dict(payload)
    items = _items(result)
    if not items or not any(row.get("vt_symbol") for row in items):
        raise ValueError("research quote page has no symbol rows")
    result["items"] = items
    return result


def _merge_fast_quote_pages(
    pages: Mapping[int, Mapping[str, object]],
) -> dict[str, object]:
    succeeded = [page for page in FAST_QUOTE_PAGES if page in pages]
    failed = [page for page in FAST_QUOTE_PAGES if page not in pages]
    payloads = [pages[page] for page in succeeded]
    rows: dict[str, dict[str, object]] = {}
    for payload in payloads:
        for row in _items(payload):
            symbol = str(row.get("vt_symbol") or "")
            if symbol:
                projected = dict(row)
                projected.setdefault("quote_observed_at", payload.get("updated_at"))
                rows.setdefault(symbol, projected)

    first = dict(payloads[0]) if payloads else {}
    sources = [str(payload.get("source") or "").strip() for payload in payloads]
    trade_date = next(
        (payload.get("trade_date") for payload in payloads if payload.get("trade_date")),
        None,
    )
    total = next(
        (payload.get("total") for payload in payloads if payload.get("total") is not None),
        None,
    )
    return {
        **first,
        "items": list(rows.values()),
        "page": 1,
        "page_size": FAST_QUOTE_PAGE_SIZE,
        "total": total,
        "source": ",".join(dict.fromkeys(source for source in sources if source)),
        "updated_at": _earliest_source_time(*payloads),
        "trade_date": trade_date,
        "fast_quote_pages_requested": list(FAST_QUOTE_PAGES),
        "fast_quote_pages_succeeded": succeeded,
        "fast_quote_pages_failed": failed,
        "fast_quote_page_coverage_ratio": round(
            len(succeeded) / len(FAST_QUOTE_PAGES),
            4,
        ),
        "fast_quote_item_count": len(rows),
    }


def _merge_research_quote_pages(
    pages: Mapping[int, Mapping[str, object]],
    errors: Sequence[str],
) -> dict[str, object]:
    succeeded = [page for page in FAST_QUOTE_PAGES if page in pages]
    rows: dict[str, dict[str, object]] = {}
    for page in succeeded:
        for row in _items(pages[page]):
            symbol = str(row.get("vt_symbol") or "")
            if symbol:
                rows.setdefault(symbol, dict(row))
    return {
        "items": list(rows.values()),
        "pages_requested": list(FAST_QUOTE_PAGES),
        "pages_succeeded": succeeded,
        "pages_failed": [page for page in FAST_QUOTE_PAGES if page not in pages],
        "item_count": len(rows),
        "source_errors": list(errors),
    }


def _attach_research_quote_enrichment(
    snapshot: Mapping[str, object],
    payload: object,
    captured_at: datetime,
) -> dict[str, object]:
    """Attach fresh research fields without mutating any official live surface."""

    source = payload if isinstance(payload, Mapping) else {}
    enrichment_by_symbol = {
        str(row.get("vt_symbol") or ""): row
        for row in _items(source)
        if row.get("vt_symbol")
    }
    raw_candidates = snapshot.get("trace_capture_candidates")
    candidates = raw_candidates if isinstance(raw_candidates, list) else []
    enriched_candidates: list[dict[str, object]] = []
    for raw_candidate in candidates:
        candidate = dict(raw_candidate) if isinstance(raw_candidate, Mapping) else {}
        candidate.update({field: None for field in RESEARCH_QUOTE_ENRICHMENT_FIELDS})
        candidate["quote_flow_observed_at"] = None
        symbol = str(candidate.get("vt_symbol") or "")
        enrichment = enrichment_by_symbol.get(symbol)
        if enrichment is not None:
            observed_at = _parsed_datetime(enrichment.get("quote_observed_at"))
            candidate["quote_flow_observed_at"] = enrichment.get(
                "quote_observed_at"
            )
            age = (
                (captured_at - observed_at).total_seconds()
                if observed_at is not None
                else None
            )
            if (
                age is not None
                and 0.0 <= age <= RESEARCH_QUOTE_ENRICHMENT_MAX_AGE_SECONDS
            ):
                candidate.update(
                    {
                        field: _number(enrichment.get(field))
                        for field in RESEARCH_QUOTE_ENRICHMENT_FIELDS
                    }
                )
        enriched_candidates.append(candidate)
    return {
        **dict(snapshot),
        "trace_capture_candidates": enriched_candidates,
    }


def _planned_symbols() -> list[str]:
    from alphaagent.server.services.limit_up.next_session_plan import (
        get_latest_next_session_plan,
    )

    plan = get_latest_next_session_plan()
    if not isinstance(plan, Mapping):
        return []
    recommendations = plan.get("recommendations")
    recommendations = recommendations if isinstance(recommendations, Mapping) else {}
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, Mapping) else {}
    rows = lanes.get("next_auction")
    rows = rows if isinstance(rows, list) else []
    return [
        str(row.get("vt_symbol"))
        for row in rows[:5]
        if isinstance(row, Mapping) and row.get("vt_symbol")
    ]


def _planned_quote_requests(symbols: Sequence[str]) -> list[dict[str, str]]:
    requests: list[dict[str, str]] = []
    for vt_symbol in dict.fromkeys(str(value) for value in symbols if value):
        symbol, separator, exchange = vt_symbol.partition(".")
        if separator and symbol and exchange in {"SSE", "SZSE"}:
            requests.append({"symbol": symbol, "exchange": exchange})
        if len(requests) >= 5:
            break
    return requests


def _quote_payload_with_full_radar(
    quote_payload: Mapping[str, object],
    concept_snapshot: Mapping[str, object] | None,
) -> dict[str, object]:
    """Overlay the latest strong-stock page on the authoritative 30s radar."""

    rows: dict[str, dict[str, object]] = {}
    concept_time = (
        concept_snapshot.get("source_updated_at")
        if isinstance(concept_snapshot, Mapping)
        else None
    )
    if isinstance(concept_snapshot, Mapping):
        for row in concept_snapshot.get("radar_quotes") or []:
            if isinstance(row, Mapping) and row.get("vt_symbol"):
                projected = dict(row)
                projected.setdefault("quote_observed_at", concept_time)
                rows[str(row["vt_symbol"])] = projected
    quote_time = quote_payload.get("updated_at")
    for row in _items(quote_payload):
        if row.get("vt_symbol"):
            projected = {
                **rows.get(str(row["vt_symbol"]), {}),
                **row,
            }
            if row.get("quote_observed_at") is None:
                projected["quote_observed_at"] = quote_time
            rows[str(row["vt_symbol"])] = projected
    return {
        **dict(quote_payload),
        "trade_date": (
            concept_snapshot.get("trade_date")
            if isinstance(concept_snapshot, Mapping)
            else None
        )
        or quote_payload.get("trade_date"),
        "items": list(rows.values()),
        "source": _source_name(quote_payload, concept_snapshot or {}),
        "updated_at": _latest_source_time(quote_payload, concept_snapshot or {}),
    }


def _concept_snapshot_with_incremental_quotes(
    concept_snapshot: Mapping[str, object] | None,
    quote_payload: Mapping[str, object],
    pool_payload: Mapping[str, object],
    captured_at: datetime,
) -> dict[str, object] | None:
    """Re-aggregate cached full coverage with the latest fast strong-stock rows."""

    if not isinstance(concept_snapshot, Mapping):
        return None
    membership = concept_snapshot.get("membership")
    if not isinstance(membership, Mapping):
        return dict(concept_snapshot)
    quote_by_symbol = {
        str(row.get("vt_symbol") or "").upper(): row
        for row in concept_snapshot.get("quotes") or []
        if isinstance(row, Mapping) and row.get("vt_symbol")
    }
    changed_symbols = _merge_incremental_concept_quotes(
        quote_by_symbol,
        quote_payload,
        pool_payload,
    )

    base_concepts = {
        str(row.get("concept_id") or ""): row
        for row in concept_snapshot.get("concepts") or []
        if isinstance(row, Mapping) and row.get("concept_id")
    }
    affected_quotes, affected_membership = _affected_concept_inputs(
        membership,
        quote_by_symbol,
        changed_symbols,
        known_concept_ids=set(base_concepts),
    )
    recomputed = (
        aggregate_concept_strength(
            affected_quotes,
            affected_membership,
            captured_at=captured_at,
            history_by_concept={
                concept_id: [base_concepts[concept_id]]
                for concept_id in affected_membership["by_concept"]
                if concept_id in base_concepts
            },
        )
        if affected_membership["by_concept"]
        else []
    )
    acceleration_fields = tuple(
        f"{metric}_acceleration_{minutes}m"
        for metric in ("change", "diffusion", "turnover")
        for minutes in (1, 3, 5)
    )
    for row in recomputed:
        previous = base_concepts.get(str(row.get("concept_id") or ""), {})
        for field in acceleration_fields:
            if row.get(field) is None and previous.get(field) is not None:
                row[field] = previous[field]
    merged_concepts = dict(base_concepts)
    merged_concepts.update(
        {
            str(row.get("concept_id") or ""): row
            for row in recomputed
            if row.get("concept_id")
        }
    )
    concepts = rank_concepts(list(merged_concepts.values()))
    radar_quotes = [
        dict(row)
        for row in quote_by_symbol.values()
        if is_eligible_main_board(
            str(row.get("vt_symbol") or ""),
            str(row.get("name") or ""),
        )
        and (_number(row.get("change_pct")) or -100.0) >= TRACE_RADAR_MIN_CHANGE_PCT
    ]
    return {
        **dict(concept_snapshot),
        "evaluated_at": captured_at.isoformat(),
        "quotes": list(quote_by_symbol.values()),
        "radar_quotes": radar_quotes,
        "concepts": concepts,
        "concepts_by_id": {
            str(row["concept_id"]): row
            for row in concepts
        },
        "concept_count": len(concepts),
    }


def _merge_incremental_concept_quotes(
    quote_by_symbol: dict[str, Mapping[str, object]],
    quote_payload: Mapping[str, object],
    pool_payload: Mapping[str, object],
) -> set[str]:
    changed_symbols: set[str] = set()
    for row in _items(quote_payload):
        symbol = str(row.get("vt_symbol") or "").upper()
        if not symbol:
            continue
        quote_by_symbol[symbol] = {**quote_by_symbol.get(symbol, {}), **row}
        changed_symbols.add(symbol)

    incremental_rows = _merge_source_rows(
        quote_payload,
        pool_payload,
        min_change_pct=TRACE_RADAR_MIN_CHANGE_PCT,
    )
    for raw_symbol, row in incremental_rows.items():
        symbol = str(raw_symbol).upper()
        quote_by_symbol[symbol] = {**quote_by_symbol.get(symbol, {}), **row}
        changed_symbols.add(symbol)
    return changed_symbols


def _affected_concept_inputs(
    membership: Mapping[str, object],
    quote_by_symbol: Mapping[str, Mapping[str, object]],
    changed_symbols: set[str],
    *,
    known_concept_ids: set[str],
) -> tuple[list[Mapping[str, object]], dict[str, object]]:
    by_symbol = membership.get("by_symbol")
    by_symbol = by_symbol if isinstance(by_symbol, Mapping) else {}
    by_concept = membership.get("by_concept")
    by_concept = by_concept if isinstance(by_concept, Mapping) else {}
    concept_ids = {
        str(concept_id)
        for symbol in changed_symbols
        for concept_id in by_symbol.get(symbol, ())
    }
    concept_ids.update(str(value) for value in by_concept if str(value) not in known_concept_ids)
    selected_concepts = {
        concept_id: by_concept[concept_id]
        for concept_id in concept_ids
        if concept_id in by_concept and isinstance(by_concept[concept_id], Mapping)
    }
    member_symbols = {
        str(symbol).upper()
        for concept in selected_concepts.values()
        for symbol in concept.get("members") or ()
    }
    quotes = [
        quote_by_symbol[symbol]
        for symbol in member_symbols
        if symbol in quote_by_symbol
    ]
    return quotes, {
        **dict(membership),
        "by_concept": selected_concepts,
    }


def _merge_source_rows(
    quote_payload: Mapping[str, object],
    pool_payload: Mapping[str, object],
    *,
    include_previous: bool = False,
    min_change_pct: float = NEAR_LIMIT_MIN_CHANGE_PCT,
) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    previous_symbols = (
        _pool_symbols(pool_payload, "zt_previous") if include_previous else set()
    )
    for raw in _items(quote_payload):
        change_pct = _number(raw.get("change_pct"))
        symbol = str(raw.get("vt_symbol") or "")
        name = str(raw.get("name") or "")
        if (
            change_pct is None
            or (
                change_pct < min_change_pct
                and symbol not in previous_symbols
            )
            or not is_eligible_main_board(symbol, name)
        ):
            continue
        rows[symbol] = {
            **raw,
            "state": (
                "near_limit"
                if symbol in previous_symbols
                else capture_state(
                    change_pct=change_pct,
                    pool_state="quote",
                )
            ),
            "pool_key": "quote",
        }

    pools = pool_payload.get("pools")
    pools = pools if isinstance(pools, Mapping) else {}
    for pool_key in ("zbgc", "zt"):
        pool = pools.get(pool_key)
        pool = pool if isinstance(pool, Mapping) else {}
        for raw in _items(pool):
            symbol = str(raw.get("vt_symbol") or "")
            name = str(raw.get("name") or "")
            if not is_eligible_main_board(symbol, name):
                continue
            open_times = _pool_open_times(raw)
            state = "failed" if pool_key == "zbgc" else ("resealed" if open_times > 0 else "sealed")
            rows[symbol] = {
                **rows.get(symbol, {}),
                **raw,
                "quote_observed_at": (
                    rows.get(symbol, {}).get("quote_observed_at")
                    or raw.get("quote_observed_at")
                    or pool_payload.get("updated_at")
                ),
                "last_price": _number(raw.get("close_price"))
                or _number(rows.get(symbol, {}).get("last_price")),
                "state": state,
                "pool_key": pool_key,
                "open_times": open_times,
            }
    return rows


def _enrich_candidates(
    rows: Mapping[str, Mapping[str, object]],
    pool_payload: Mapping[str, object],
    stock_context: Mapping[str, object],
    *,
    require_sector: bool = True,
) -> list[dict[str, object]]:
    by_symbol = stock_context.get("by_symbol")
    by_symbol = by_symbol if isinstance(by_symbol, Mapping) else {}
    previous_symbols = _pool_symbols(pool_payload, "zt_previous")
    candidates: list[dict[str, object]] = []
    for symbol, raw in rows.items():
        context = by_symbol.get(symbol)
        context = context if isinstance(context, Mapping) else {}
        candidate = _enrich_candidate(raw, context, symbol in previous_symbols)
        if candidate.get("sector_id") or not require_sector:
            candidates.append(candidate)

    touched_by_sector = Counter(
        str(candidate.get("sector_id") or "")
        for candidate in candidates
        if candidate.get("state") != "near_limit"
    )
    for candidate in candidates:
        candidate["sector_touch_count"] = touched_by_sector.get(
            str(candidate.get("sector_id") or ""),
            0,
        )
    return candidates


def _enrich_candidate(
    raw: Mapping[str, object],
    context: Mapping[str, object],
    previous_pool_member: bool,
) -> dict[str, object]:
    raw_detail = raw.get("raw")
    raw_detail = raw_detail if isinstance(raw_detail, Mapping) else {}
    previous_close = _number(raw.get("previous_close")) or _number(context.get("previous_close"))
    last_price = _number(raw.get("last_price")) or _number(raw.get("close_price"))
    open_price = _number(raw.get("open_price")) or _raw_number(raw_detail, "今开", "开盘")
    change_pct = _number(raw.get("change_pct"))
    if previous_close is None and last_price and change_pct is not None and change_pct > -99:
        previous_close = last_price / (1 + change_pct / 100)
    limit_price = _number(raw.get("limit_up_price"))
    if limit_price is None and previous_close:
        limit_price = main_board_limit_price(previous_close)
    turnover = _number(raw.get("turnover")) or _raw_number(raw_detail, "成交额", "amount")
    float_market_cap = _number(raw.get("float_market_cap")) or _raw_number(
        raw_detail,
        "流通市值",
        "流通市值_流通市值",
    )
    seal_amount = _number(raw.get("limit_amount")) or _number(raw.get("seal_amount"))
    prior_streak = _integer(context.get("prior_streak"), 0)
    pool_level = _integer(raw.get("limit_up_count"), 0)
    board_level = pool_level or prior_streak + 1
    previous_limit_up = bool(previous_pool_member or context.get("previous_limit_up") or prior_streak)
    sector_id = str(context.get("sector_id") or "")
    sector_name = str(context.get("sector_name") or "")
    if not sector_id:
        industry = str(raw_detail.get("所属行业") or raw.get("industry_name") or "").strip()
        if industry:
            sector_id, sector_name = f"industry:{industry}", industry
    distance = None
    if limit_price and last_price is not None:
        distance = max((limit_price - last_price) / limit_price * 100, 0.0)
    auction_gap = (
        (open_price / previous_close - 1) * 100
        if open_price is not None and previous_close
        else None
    )
    high_price = _number(raw.get("high_price")) or _raw_number(
        raw_detail,
        "最高",
        "最高价",
        "high",
    )
    low_price = _number(raw.get("low_price")) or _raw_number(
        raw_detail,
        "最低",
        "最低价",
        "low",
    )
    session_low_change = (
        (low_price / previous_close - 1) * 100
        if low_price is not None and previous_close
        else None
    )
    return {
        "vt_symbol": str(raw.get("vt_symbol") or ""),
        "name": str(raw.get("name") or ""),
        "sector_id": sector_id,
        "sector_name": sector_name,
        "board_level": max(board_level, 1),
        "state": str(raw.get("state") or "near_limit"),
        "change_pct": change_pct,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "last_price": last_price,
        "quote_observed_at": raw.get("quote_observed_at"),
        "previous_close": previous_close,
        "limit_price": limit_price,
        "distance_to_limit_pct": round(distance, 4) if distance is not None else None,
        "auction_gap_pct": round(auction_gap, 4) if auction_gap is not None else None,
        "session_low_change_pct": (
            round(session_low_change, 4) if session_low_change is not None else None
        ),
        "previous_limit_up": previous_limit_up,
        "first_limit_time": normalize_limit_time(raw.get("first_limit_time")),
        "last_limit_time": normalize_limit_time(raw.get("last_limit_time")),
        "open_times": _integer(raw.get("open_times"), _pool_open_times(raw)),
        "seal_amount": seal_amount,
        "volume": _number(raw.get("volume")),
        "turnover": turnover,
        "turnover_rate": _number(raw.get("turnover_rate")),
        "volume_ratio": _number(raw.get("volume_ratio")),
        "float_market_cap": float_market_cap,
        "seal_to_turnover_ratio": _ratio(seal_amount, turnover),
        "seal_to_float_market_cap_ratio": _ratio(seal_amount, float_market_cap),
        "sector_heat": _number(context.get("sector_heat")),
        "sector_trend_state": context.get("sector_trend_state"),
        "sector_main_net_inflow": _number(context.get("sector_main_net_inflow")),
        "sector_main_net_inflow_ratio": _number(context.get("sector_main_net_inflow_ratio")),
        "sector_flow_trade_date": context.get("sector_flow_trade_date"),
        "stock_main_net_inflow": _number(context.get("stock_main_net_inflow")),
        "stock_main_net_inflow_ratio": _number(context.get("stock_main_net_inflow_ratio")),
        "stock_flow_trade_date": context.get("stock_flow_trade_date"),
        "prior_turnover_rate": _number(context.get("prior_turnover_rate")),
        "prior_turnover_ratio_5d": _number(context.get("prior_turnover_ratio_5d")),
        "prior_amount_ratio_5d": _number(context.get("prior_amount_ratio_5d")),
        "prior_change_pct": _number(context.get("prior_change_pct")),
        "prior_low_change_pct": _number(context.get("prior_low_change_pct")),
        "prior_return_5d_pct": _number(context.get("prior_return_5d_pct")),
        "prior_return_20d_pct": _number(context.get("prior_return_20d_pct")),
        "prior_amplitude_pct": _number(context.get("prior_amplitude_pct")),
        "prior_streak": prior_streak,
        "prior_break_streak": _integer(context.get("prior_break_streak"), 0),
        "prior_limit_count_126": _integer(context.get("prior_limit_count_126"), 0),
        "prior_industry_turnover_ratio_5d": _number(
            context.get("prior_industry_turnover_ratio_5d")
        ),
        "prior_touch_count_126": _integer(context.get("prior_touch_count_126"), 0),
        "prior_seal_success_rate_126": _number(context.get("prior_seal_success_rate_126")),
        "prior_limit_count_5": _integer(context.get("prior_limit_count_5"), 0),
        "prior_limit_count_10": _integer(context.get("prior_limit_count_10"), 0),
        "trade_days_since_prior_limit": _integer(
            context.get("trade_days_since_prior_limit"),
            0,
        ),
        "pullback_from_prior_limit_pct": _number(
            context.get("pullback_from_prior_limit_pct")
        ),
        "prior_position_120": _number(context.get("prior_position_120")),
        "prior_board": context.get("prior_board"),
        "financial_risk": context.get("financial_risk"),
        "financial_snapshot": context.get("financial_snapshot"),
        "lane_feature_ready": bool(context.get("lane_feature_ready")),
        "warmup_contexts": [
            dict(item)
            for item in (context.get("concept_contexts") or [])
            if isinstance(item, Mapping)
        ],
        "pool_key": raw.get("pool_key"),
    }


def _attach_warmup_shadow(candidates: list[dict[str, object]]) -> None:
    for candidate in candidates:
        contexts = candidate.pop("warmup_contexts", [])
        if str(candidate.get("board_lane") or "") != "first_board":
            continue
        observation = live_warmup_observation(
            contexts if isinstance(contexts, Sequence) else []
        )
        if not observation["available"]:
            continue
        candidate.update(
            {
                "warmup_group": observation["group_id"],
                "warmup_group_name": observation["group_name"],
                "warmup_state": observation["state"],
                "warmup_score": observation["score"],
                "warmup_confidence": observation["confidence"],
                "warmup_execution_effect": observation["execution_effect"],
                "warmup_main_net_inflow": observation.get("main_net_inflow"),
                "warmup_main_net_inflow_ratio": observation.get(
                    "main_net_inflow_ratio"
                ),
                "warmup_trend_state": observation.get("trend_state"),
                "warmup_flow_trade_date": observation.get("flow_trade_date"),
            }
        )
    candidates[:] = attach_dynamic_group_leader_ranks(candidates)


def _attach_lane_decisions(
    candidates: list[dict[str, object]],
    market_context: Mapping[str, object],
    captured_at: datetime,
    *,
    market_gate: Mapping[str, object] | None = None,
) -> None:
    sentiment = market_context.get("sentiment")
    sentiment = sentiment if isinstance(sentiment, Mapping) else {}
    research_candidates: list[dict[str, object]] = []
    for candidate in candidates:
        evaluation_date = captured_at.date().isoformat()
        sector_flow_date = _parsed_date(candidate.get("sector_flow_trade_date"))
        candidate["evaluation_date"] = evaluation_date
        candidate["sector_flow_current"] = (
            sector_flow_date == captured_at.date()
            if sector_flow_date is not None
            else candidate.get("sector_flow_current") is True
        )
        board_level = _integer(candidate.get("board_level"), 1)
        candidate["board_lane"] = classify_board_lane(
            {**candidate, "target_board": board_level}
        )
        if candidate["board_lane"] == "one_to_two":
            candidate.update(
                {
                    "lane_decision": "removed",
                    "lane_setup_type": None,
                    "setup_tags": [],
                    "setup_confidence": None,
                    "lane_blockers": ["one_to_two_removed"],
                    "lane_favorable_factors": [],
                    "lane_quality_tier": None,
                    "lane_risk_count": 0,
                    "lane_risk_flags": [],
                    "lane_rank_score": None,
                }
            )
            continue
        if candidate["board_lane"] in scheduled_execution.RELAY_LANES:
            candidate.update(_live_relay_trigger(candidate, captured_at))
        if not candidate.get("lane_feature_ready"):
            candidate.update(
                {
                    "lane_decision": "blocked",
                    "lane_setup_type": None,
                    "setup_tags": [],
                    "setup_confidence": None,
                    "lane_blockers": ["lane_features_unavailable"],
                    "lane_favorable_factors": [],
                    "lane_quality_tier": None,
                    "lane_risk_count": 0,
                    "lane_risk_flags": [],
                    "lane_rank_score": None,
                }
            )
            continue
        research_candidate = _live_research_candidate(
            candidate,
            sentiment,
            captured_at,
            market_gate=market_gate,
        )
        research_candidates.append(research_candidate)
        evaluated = evaluate_lane_candidate(research_candidate)
        candidate.update(
            {
                "board_lane": evaluated.get("lane"),
                "lane_decision": evaluated.get("decision"),
                "lane_setup_type": evaluated.get("setup_type"),
                "first_board_route": evaluated.get("first_board_route"),
                "setup_tags": list(evaluated.get("setup_tags") or []),
                "setup_confidence": evaluated.get("setup_confidence"),
                "lane_blockers": list(evaluated.get("blockers") or []),
                "lane_favorable_factors": list(
                    evaluated.get("favorable_factors") or []
                ),
                "lane_support_score": evaluated.get("support_score"),
                "lane_seal_gate_passed": evaluated.get("seal_gate_passed"),
                "lane_premium_gate_passed": evaluated.get("premium_gate_passed"),
                "lane_entry_quality_score": evaluated.get("entry_quality_score"),
                "lane_quality_tier": evaluated.get("two_to_three_quality_tier"),
                "lane_risk_count": evaluated.get("two_to_three_risk_count"),
                "lane_risk_flags": list(
                    evaluated.get("two_to_three_risk_flags") or []
                ),
                "lane_rank_score": evaluated.get("rank_score"),
            }
        )

    selected = select_daily_lane_portfolio(research_candidates).get("selected", [])
    selected_symbols = {
        str(row.get("vt_symbol") or "")
        for row in selected
        if isinstance(row, Mapping)
    }
    for candidate in candidates:
        candidate["portfolio_selected"] = (
            str(candidate.get("vt_symbol") or "") in selected_symbols
        )


def _live_research_candidate(
    candidate: Mapping[str, object],
    sentiment: Mapping[str, object],
    captured_at: datetime,
    *,
    market_gate: Mapping[str, object] | None = None,
) -> dict[str, object]:
    board_level = _integer(candidate.get("board_level"), 1)
    is_first_board = board_level == 1
    evaluation_time = captured_at.time().replace(microsecond=0).isoformat()
    state = str(candidate.get("state") or "")
    actual_first_touch = (
        normalize_limit_time(candidate.get("first_limit_time"))
        if board_level >= 3 and state in {"sealed", "resealed", "failed"}
        else None
    )
    return {
        **candidate,
        "target_board": board_level,
        "evaluation_time": evaluation_time,
        "signal_time": actual_first_touch or evaluation_time,
        "signal_kind": (
            "auction" if session_stage(captured_at) == "auction" else "intraday"
        ),
        "qualification_kind": (
            "auction" if board_level >= 3 else candidate.get("signal_kind")
        ),
        "prior_industry_heat_score": candidate.get("concept_strength_score")
        if is_first_board or candidate.get("concept_strength_score") is not None
        else candidate.get("sector_heat"),
        "prior_industry_leader_rank": candidate.get("concept_leader_rank")
        if is_first_board or candidate.get("concept_leader_rank") is not None
        else candidate.get("sector_dragon_rank"),
        "live_sector_gate_managed": is_first_board,
        "prior_market_phase": sentiment.get("phase"),
        "prior_market_failed_rate": sentiment.get("failed_limit_up_rate"),
        "live_market_repair_confirmed": bool(
            market_gate and market_gate.get("repair_confirmed")
        ),
        "has_l2": False,
    }


def _live_relay_trigger(
    candidate: Mapping[str, object],
    captured_at: datetime,
) -> dict[str, object]:
    evaluation_time = captured_at.time().replace(microsecond=0).isoformat()
    if not scheduled_execution.is_entry_time(evaluation_time):
        return {
            "relay_trigger_status": "outside_entry_window",
            "relay_trigger_time": None,
            "relay_trigger_kind": None,
        }
    state = str(candidate.get("state") or "")
    if state not in {"sealed", "resealed"}:
        return {
            "relay_trigger_status": "waiting_touch_or_reseal",
            "relay_trigger_time": None,
            "relay_trigger_kind": None,
        }
    first_time = normalize_limit_time(candidate.get("first_limit_time"))
    last_time = normalize_limit_time(candidate.get("last_limit_time"))
    trigger_time: str | None = None
    trigger_kind: str | None = None
    if first_time and scheduled_execution.is_entry_time(first_time):
        trigger_time = first_time
        trigger_kind = "first_touch"
    elif (
        first_time
        and first_time < "10:00:00"
        and state == "resealed"
        and _integer(candidate.get("open_times"), 0) > 0
        and last_time
        and scheduled_execution.is_entry_time(last_time)
    ):
        trigger_time = last_time
        trigger_kind = "reseal"
    if trigger_time is None:
        return {
            "relay_trigger_status": "waiting_touch_or_reseal",
            "relay_trigger_time": None,
            "relay_trigger_kind": None,
        }
    age_seconds = _session_second(evaluation_time) - _session_second(trigger_time)
    if age_seconds < 0 or age_seconds > LIVE_SNAPSHOT_MAX_AGE_SECONDS:
        return {
            "relay_trigger_status": "stale_trigger",
            "relay_trigger_time": trigger_time,
            "relay_trigger_kind": trigger_kind,
        }
    return {
        "relay_trigger_status": "ready",
        "relay_trigger_time": trigger_time,
        "relay_trigger_kind": trigger_kind,
    }


def apply_lane_validation_veto(
    recommendations: Mapping[str, object],
    lane_validations: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Fail closed when a board lane has not passed out-of-sample validation."""

    result = dict(recommendations)
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, Mapping) else {}
    validated_lanes: dict[str, list[dict[str, object]]] = {}
    for lane_name, raw_signals in lanes.items():
        signals = raw_signals if isinstance(raw_signals, Sequence) else []
        validated_lanes[str(lane_name)] = [
            _apply_signal_validation(signal, lane_validations)
            for signal in signals
            if isinstance(signal, Mapping)
        ]
    result["lanes"] = validated_lanes
    result["board_lane_validations"] = {
        lane: {
            "passed": validation.get("passed") is True,
            "status": str(validation.get("status") or "unavailable"),
            "reason": str(validation.get("reason") or "尚未通过样本外验证"),
            "summary": _compact_validation_summary(validation.get("summary")),
        }
        for lane, validation in lane_validations.items()
    }
    return result


def _apply_live_risk_gates(
    snapshot: Mapping[str, object],
    lane_validations: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Apply prior-only evidence before separating research and execution actions."""

    result = (
        _with_historical_evidence(snapshot)
        if snapshot.get("candidates")
        else dict(snapshot)
    )
    result = _attach_shared_first_board_quality(result)
    recommendations = result.get("recommendations")
    recommendations = recommendations if isinstance(recommendations, Mapping) else {}
    validated = apply_lane_validation_veto(recommendations, lane_validations)
    validated = _rank_first_board_recommendations(validated)
    validated = _apply_core_quality_gate(validated)
    captured_at = _parsed_datetime(result.get("captured_at")) or datetime.now(SHANGHAI)
    quality = result.get("data_quality")
    quality = quality if isinstance(quality, Mapping) else {}
    snapshot_age = _integer(quality.get("snapshot_age_seconds"), 0)
    validated["execution_schedule"] = scheduled_execution.execution_clock(captured_at)
    validated["actionable_recommendations"] = (
        _build_live_actionable_recommendations(
            validated,
            captured_at=captured_at,
            snapshot_age_seconds=snapshot_age,
        )
    )
    validated["portfolio"] = _build_live_portfolio(
        validated,
        captured_at=captured_at,
        snapshot_age_seconds=snapshot_age,
    )
    validated["watchlist"] = _build_live_watchlist(validated)
    result = {**result, "recommendations": validated}
    return _apply_early_radar_risk_gates(result, lane_validations)


def _apply_early_radar_risk_gates(
    snapshot: Mapping[str, object],
    lane_validations: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """Apply the same prior-only and lane validation to internal 3% signals."""

    early = snapshot.get("early_radar_recommendations")
    capture = snapshot.get("trace_capture_candidates")
    if not isinstance(early, Mapping) or not isinstance(capture, list):
        return dict(snapshot)
    early_snapshot = {
        **dict(snapshot),
        "candidates": capture,
        "recommendations": dict(early),
    }
    enriched = _with_historical_evidence(early_snapshot) if capture else early_snapshot
    enriched = _attach_shared_first_board_quality(enriched)
    recommendations = enriched.get("recommendations")
    recommendations = (
        recommendations if isinstance(recommendations, Mapping) else {}
    )
    validated = apply_lane_validation_veto(recommendations, lane_validations)
    validated = _rank_first_board_recommendations(validated)
    validated = _apply_core_quality_gate(validated)
    result = dict(snapshot)
    result["early_radar_recommendations"] = validated
    enriched_quality = enriched.get("data_quality")
    if isinstance(enriched_quality, Mapping):
        result["data_quality"] = dict(enriched_quality)
    return result


_SHARED_FIRST_BOARD_QUALITY_FIELDS = (
    "universe_gate_passed",
    "entry_window_passed",
    "quality_gate_passed",
    "preparation_environment_passed",
    "execution_environment_passed",
    "failed_environment_checks",
    "lane_decision",
    "lane_blockers",
    "lane_support_score",
    "lane_entry_quality_score",
    "lane_rank_score",
    "profitability_gate_version",
    "profitability_gate_applies",
    "profitability_gate_passed",
    "profitability_gate_reason",
    "profitability_gate_minimum_d1_samples",
    "profitability_gate_minimum_combined_rate",
    "profitability_gate_sample_count",
    "profitability_gate_combined_rate",
    "historical_prior_status",
    "expected_d1_net_return_pct",
    "d1_win_probability",
    "seal_probability_given_touch",
    "d1_win_probability_given_seal",
)


def _attach_shared_first_board_quality(
    snapshot: Mapping[str, object],
) -> dict[str, object]:
    """Project live first boards through the shared point-in-time quality gate."""

    result = dict(snapshot)
    recommendations = result.get("recommendations")
    if not isinstance(recommendations, Mapping):
        return result
    captured_at = _parsed_datetime(result.get("captured_at"))
    if captured_at is None:
        return result
    market_context = result.get("market_context")
    market_context = market_context if isinstance(market_context, Mapping) else {}
    sentiment = market_context.get("sentiment")
    sentiment = sentiment if isinstance(sentiment, Mapping) else {}
    market_gate = recommendations.get("market_gate")
    market_gate = market_gate if isinstance(market_gate, Mapping) else {}
    quality = result.get("data_quality")
    quality = quality if isinstance(quality, Mapping) else {}
    snapshot_age = _number(quality.get("snapshot_age_seconds"))
    snapshot_fresh = bool(
        quality.get("is_stale") is not True
        and snapshot_age is not None
        and 0.0 <= snapshot_age <= scheduled_execution.MAX_SNAPSHOT_AGE_SECONDS
    )
    candidates = result.get("candidates")
    candidates = candidates if isinstance(candidates, list) else []
    by_symbol = {
        str(candidate.get("vt_symbol") or ""): candidate
        for candidate in candidates
        if isinstance(candidate, Mapping) and candidate.get("vt_symbol")
    }
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, Mapping) else {}
    projected_lanes: dict[str, list[dict[str, object]]] = {}
    for lane_name, raw_signals in lanes.items():
        signals = raw_signals if isinstance(raw_signals, list) else []
        projected: list[dict[str, object]] = []
        for raw_signal in signals:
            if not isinstance(raw_signal, Mapping):
                continue
            signal = dict(raw_signal)
            if str(signal.get("board_lane") or "") != "first_board":
                projected.append(signal)
                continue
            candidate = by_symbol.get(str(signal.get("vt_symbol") or ""), {})
            research_candidate = _live_research_candidate(
                candidate,
                sentiment,
                captured_at,
                market_gate=market_gate,
            )
            quote_observed_at = _parsed_datetime(
                candidate.get("quote_observed_at")
                or signal.get("quote_observed_at")
            )
            quote_age = (
                (captured_at - quote_observed_at).total_seconds()
                if quote_observed_at is not None
                else None
            )
            financial_risk = research_candidate.get("financial_risk")
            risk_gate_passed = bool(
                isinstance(financial_risk, Mapping)
                and financial_risk.get("blocked") is False
            )
            point_in_time = {
                **research_candidate,
                **signal,
                "historical_evidence": signal.get("historical_evidence"),
                "entry_window_passed": scheduled_execution.is_entry_time(
                    captured_at.time().replace(microsecond=0).isoformat()
                ),
                "snapshot_fresh": snapshot_fresh,
                "quote_fresh": bool(
                    quote_age is not None
                    and 0.0 <= quote_age <= scheduled_execution.MAX_SNAPSHOT_AGE_SECONDS
                ),
                "risk_gate_passed": risk_gate_passed,
            }
            checks = build_first_board_execution_checks_at_time(point_in_time)
            evaluated = evaluate_first_board_quality_at_time(
                point_in_time,
                decision_at=captured_at,
                market_gate=market_gate,
                execution_checks=checks,
            )
            signal.update(
                {
                    field: evaluated.get(field)
                    for field in _SHARED_FIRST_BOARD_QUALITY_FIELDS
                }
            )
            signal.update(
                {
                    "preboard_decision_contract_version": (
                        PREBOARD_DECISION_VERSION
                    ),
                    "strictly_preboard": is_strictly_preboard(evaluated),
                    "quality_evaluated_at": captured_at.isoformat(),
                }
            )
            projected.append(signal)
        projected_lanes[str(lane_name)] = projected
    result["recommendations"] = {
        **dict(recommendations),
        "lanes": projected_lanes,
    }
    return result


def _rank_first_board_recommendations(
    recommendations: Mapping[str, object],
) -> dict[str, object]:
    result = dict(recommendations)
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, Mapping) else {}
    result["lanes"] = {
        str(lane): rank_first_board_signals(
            signals if isinstance(signals, list) else []
        )
        for lane, signals in lanes.items()
    }
    return result


def _apply_core_quality_gate(
    recommendations: Mapping[str, object],
) -> dict[str, object]:
    result = dict(recommendations)
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, Mapping) else {}
    annotated_lanes: dict[str, list[dict[str, object]]] = {}
    for lane_name, raw_signals in lanes.items():
        signals = raw_signals if isinstance(raw_signals, list) else []
        annotated_lanes[str(lane_name)] = [
            _apply_core_quality_to_signal(signal)
            for signal in signals
            if isinstance(signal, Mapping)
        ]
    result["lanes"] = annotated_lanes
    result["core_quality_filter"] = core_quality.core_quality_filter_metadata()
    return result


def _apply_core_quality_to_signal(
    signal: Mapping[str, object],
) -> dict[str, object]:
    result = {**dict(signal), **core_quality.core_quality_gate(signal)}
    if (
        str(result.get("action") or "") in EXECUTABLE_ACTIONS
        and result["core_quality_gate_passed"] is not True
    ):
        result["research_action"] = str(result.get("action") or "pass")
        result["action"] = "pass"
        result["execution_state"] = "cancelled"
        result["reason"] = _core_quality_rejection_text(result)
    return result


def _core_quality_rejection_text(signal: Mapping[str, object]) -> str:
    reason = str(signal.get("core_quality_gate_reason") or "core_quality_rejected")
    if reason.startswith("prior_limit_count_126_below_"):
        return "只观察，不执行：过去126个交易日涨停少于2次"
    if reason.startswith("prior_limit_count_126_above_"):
        return "只观察，不执行：过去126个交易日涨停超过6次"
    if reason == "prior_limit_count_126_unavailable":
        return "只观察，不执行：126日涨停辨识度不可用"
    return f"只观察，不执行：{reason}"


def _apply_signal_validation(
    signal: Mapping[str, object],
    lane_validations: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    result = dict(signal)
    result["research_action"] = str(
        result.get("research_action") or result.get("action") or "pass"
    )
    lane = str(result.get("board_lane") or _board_lane(_integer(result.get("board_level"), 1)))
    validation = lane_validations.get(lane) or {
        "passed": False,
        "status": "unavailable",
        "reason": "战法验证数据不可用",
    }
    passed = validation.get("passed") is True
    reason = str(validation.get("reason") or "尚未通过样本外验证")
    summary = validation.get("summary")
    summary = summary if isinstance(summary, Mapping) else {}
    result.update(
        {
            "board_lane": lane,
            "validation_passed": passed,
            "validation_status": str(validation.get("status") or "unavailable"),
            "validation_reason": reason,
            "strategy_evidence": {
                "win_rate": _number(summary.get("win_rate")),
                "total_return_pct": _number(summary.get("total_return_pct")),
                "max_drawdown_pct": _number(summary.get("max_drawdown_pct")),
                "trade_count": _integer(summary.get("trade_count")),
            },
        }
    )
    if str(result.get("action") or "") in EXECUTABLE_ACTIONS and not passed:
        original_reason = str(result.get("reason") or "买点成立")
        result["action"] = "pass"
        result["execution_state"] = "cancelled"
        result["reason"] = f"只观察，不执行：{original_reason}；{reason}"
    return result


def _build_live_portfolio(
    recommendations: Mapping[str, object],
    *,
    captured_at: datetime | None = None,
    snapshot_age_seconds: int = 0,
) -> list[dict[str, object]]:
    return _build_live_buy_list(
        recommendations,
        captured_at=captured_at,
        snapshot_age_seconds=snapshot_age_seconds,
        require_portfolio_selection=True,
        limit=scheduled_execution.MAX_POSITIONS,
    )


def _build_live_actionable_recommendations(
    recommendations: Mapping[str, object],
    *,
    captured_at: datetime | None = None,
    snapshot_age_seconds: int = 0,
) -> list[dict[str, object]]:
    return _build_live_buy_list(
        recommendations,
        captured_at=captured_at,
        snapshot_age_seconds=snapshot_age_seconds,
        require_portfolio_selection=False,
        limit=None,
    )


def _build_live_buy_list(
    recommendations: Mapping[str, object],
    *,
    captured_at: datetime | None,
    snapshot_age_seconds: int,
    require_portfolio_selection: bool,
    limit: int | None,
) -> list[dict[str, object]]:
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, Mapping) else {}
    selected: dict[str, dict[str, object]] = {}
    for channel in ("now",):
        signals = lanes.get(channel)
        signals = signals if isinstance(signals, list) else []
        for raw_signal in signals:
            if not isinstance(raw_signal, Mapping):
                continue
            signal = dict(raw_signal)
            signal.update(core_quality.core_quality_gate(signal))
            symbol = str(signal.get("vt_symbol") or "")
            action = str(signal.get("action") or "pass")
            if (
                not symbol
                or (
                    require_portfolio_selection
                    and signal.get("portfolio_selected") is not True
                )
                or str(signal.get("board_lane") or "") not in PORTFOLIO_EXECUTION_LANES
                or action != "buy_now"
                or signal.get("core_quality_gate_passed") is not True
                or (
                    signal.get("missed_preseal_entry") is True
                    and signal.get("entry_kind") != "momentum"
                )
            ):
                continue
            current = selected.get(symbol)
            if (
                current is None
                or _live_portfolio_sort_key(signal)
                < _live_portfolio_sort_key(current)
            ):
                selected[symbol] = signal
    local_at = captured_at or datetime.now(SHANGHAI)
    schedule = scheduled_execution.execution_clock(local_at)
    ordered = sorted(selected.values(), key=_live_portfolio_sort_key)
    if limit is not None:
        ordered = ordered[:limit]
    scheduled = [
        _scheduled_live_signal(signal, schedule, snapshot_age_seconds)
        for signal in ordered
    ]
    return [signal for signal in scheduled if signal.get("action") == "buy_now"]


def _scheduled_live_signal(
    signal: Mapping[str, object],
    schedule: Mapping[str, object],
    snapshot_age_seconds: int,
) -> dict[str, object]:
    result = {
        **dict(signal),
        "execution_permission": "research_only",
        "scheduled_execution_version": scheduled_execution.SCHEDULED_EXECUTION_VERSION,
        "buy_instruction": str(
            signal.get("buy_instruction")
            or f"仅在{'或'.join(scheduled_execution.ENTRY_WINDOW_LABELS)}满足全部条件时买入"
        ),
        "sell_instruction": "D+1尾盘按官方收盘价统一卖出",
        "target_position_pct": scheduled_execution.TARGET_POSITION_PCT,
    }
    if snapshot_age_seconds > scheduled_execution.MAX_SNAPSHOT_AGE_SECONDS:
        reason = (
            f"实时快照已超过{scheduled_execution.MAX_SNAPSHOT_AGE_SECONDS}秒，"
            "本次买点失效"
        )
        return {
            **result,
            "action": "observe",
            "execution_state": "cancelled",
            "signal_state": "invalidated",
            "reason": reason,
            "pending_reasons": [reason],
        }
    action = str(signal.get("action") or "pass")
    if action != "buy_now":
        return {
            **result,
            "action": "observe",
            "execution_state": "watch",
            "signal_state": str(signal.get("signal_state") or "observing"),
            "reason": str(signal.get("reason") or "等待市场和盘口条件通过"),
            "pending_reasons": list(signal.get("pending_reasons") or []),
        }
    if schedule.get("entry_allowed") is not True:
        reason = str(schedule.get("message") or "当前不在固定买入窗口")
        return {
            **result,
            "action": "observe",
            "execution_state": "watch",
            "signal_state": "observing",
            "reason": reason,
            "pending_reasons": [reason],
        }
    return {
        **result,
        "action": "buy_now",
        "execution_state": "actionable",
        "signal_state": "trigger_ready",
        "reason": str(signal.get("reason") or "连续盘中评估条件全部通过"),
        "pending_reasons": [],
    }


def _live_portfolio_sort_key(signal: Mapping[str, object]) -> tuple[object, ...]:
    action = str(signal.get("action") or "pass")
    action_priority = {
        "buy_now": 0,
        "next_auction": 1,
        "observe": 2,
        "wait_tail": 2,
        "pass": 3,
    }.get(action, 4)
    history = signal.get("historical_evidence")
    history = history if isinstance(history, Mapping) else {}
    strategy = signal.get("strategy_evidence")
    strategy = strategy if isinstance(strategy, Mapping) else {}
    first_board = str(signal.get("board_lane") or "") == "first_board"
    return (
        action_priority,
        core_quality.quality_tier_priority(signal),
        scheduled_execution.execution_lane_priority(signal.get("board_lane")),
        -(_number(history.get("historical_win_rate")) or 0.0)
        if first_board
        else 0.0,
        -(_number(signal.get("change_pct")) or 0.0) if first_board else 0.0,
        -(_number(history.get("tbox_score")) or 0.0),
        -(_number(history.get("smoothed_win_rate")) or 0.0),
        -(_number(strategy.get("total_return_pct")) or 0.0),
        -(_number(signal.get("leadership_score")) or 0.0),
        str(signal.get("vt_symbol") or ""),
    )


def _build_live_watchlist(
    recommendations: Mapping[str, object],
) -> list[dict[str, object]]:
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, Mapping) else {}
    observations: dict[str, dict[str, object]] = {}
    for channel in ("now", "next_auction", "tail"):
        signals = lanes.get(channel)
        signals = signals if isinstance(signals, list) else []
        for raw_signal in signals:
            if not isinstance(raw_signal, Mapping):
                continue
            signal = dict(raw_signal)
            symbol = str(signal.get("vt_symbol") or "")
            strategy = signal.get("strategy_evidence")
            strategy = strategy if isinstance(strategy, Mapping) else {}
            if (
                not symbol
                or symbol in observations
                or str(signal.get("board_lane") or "") not in PORTFOLIO_EXECUTION_LANES
                or not _can_transition_to_live_buy(signal)
            ):
                continue
            original_action = str(
                signal.get("research_action") or signal.get("action") or "pass"
            )
            reason_parts = [str(signal.get("reason") or "组合硬门未通过")]
            reason_parts.extend(
                str(value)
                for value in signal.get("lane_blocker_reasons") or []
                if value
            )
            original_reason = "；".join(dict.fromkeys(reason_parts))
            first_board_momentum = (
                str(signal.get("board_lane") or "") == "first_board"
                and str(signal.get("state") or "")
                in {"near_limit", "sealed", "resealed"}
            )
            current_signal_state = str(signal.get("signal_state") or "observing")
            observations[symbol] = {
                **signal,
                "action": "observe",
                "research_action": original_action,
                "execution_state": "watch",
                "signal_state": (
                    "concept_warming"
                    if current_signal_state == "concept_warming"
                    else "pending_auction"
                    if current_signal_state == "pending_auction"
                    else "approaching_trigger"
                    if first_board_momentum
                    else "observing"
                ),
                "entry_kind": (
                    "momentum" if first_board_momentum else signal.get("entry_kind")
                ),
                "buy_instruction": (
                    "板块已预热，等待个股动能和其余质量门同步通过"
                    if current_signal_state == "concept_warming"
                    else "等待竞价确认，满足竞价硬门后触发"
                    if current_signal_state == "pending_auction"
                    else "个股动能、市场、板块、历史质量和风险门同步通过时触发"
                ),
                "reason": f"等待触发：{original_reason}",
            }
    ordered = rank_first_board_signals(
        sorted(observations.values(), key=_live_watchlist_sort_key)
    )
    return ordered[:LIVE_WATCHLIST_LIMIT]


def _can_transition_to_live_buy(signal: Mapping[str, object]) -> bool:
    signal_state = str(signal.get("signal_state") or "observing")
    return (
        str(signal.get("blocking_scope") or "") != "structural"
        and signal.get("profitability_gate_passed") is not False
        and signal_state not in {"rejected", "missed", "invalidated"}
        and (
            signal.get("missed_preseal_entry") is not True
            or signal.get("entry_kind") == "momentum"
        )
    )


def _live_watchlist_sort_key(signal: Mapping[str, object]) -> tuple[object, ...]:
    history = signal.get("historical_evidence")
    history = history if isinstance(history, Mapping) else {}
    strategy = signal.get("strategy_evidence")
    strategy = strategy if isinstance(strategy, Mapping) else {}
    state = str(signal.get("state") or "")
    state_priority = {
        "near_limit": 0,
        "failed": 1,
        "resealed": 2,
        "sealed": 3,
    }.get(state, 4)
    distance = _number(signal.get("distance_to_limit_pct"))
    signal_priority = {
        "approaching_trigger": 0,
        "concept_warming": 1,
        "observing": 2,
        "rejected": 3,
    }.get(str(signal.get("signal_state") or ""), 4)
    return (
        signal_priority,
        state_priority,
        _integer(signal.get("concept_strength_rank"), 1_000_000),
        _integer(signal.get("concept_leader_rank"), 1_000_000),
        distance if state == "near_limit" and distance is not None else 99.0,
        -(_number(history.get("tbox_score")) or 0.0),
        -(_number(strategy.get("total_return_pct")) or 0.0),
        -(_number(history.get("smoothed_win_rate")) or 0.0),
        -(_number(signal.get("leadership_score")) or 0.0),
        str(signal.get("vt_symbol") or ""),
    )


def _load_lane_validations() -> dict[str, dict[str, object]]:
    try:
        ledger_updated_at = history_repository.history_ledger_updated_at(
            history_engine.HISTORY_STRATEGY_VERSION
        )
    except Exception:  # noqa: BLE001
        ledger_updated_at = None
    cache_key = (
        f"{STRATEGY_VERSION}:{history_engine.HISTORY_STRATEGY_VERSION}:"
        f"{ledger_updated_at.isoformat() if ledger_updated_at else 'unavailable'}"
    )
    return _LIVE_LANE_VALIDATION_CACHE.get_or_set(
        cache_key,
        LIVE_LANE_VALIDATION_CACHE_SECONDS,
        lambda: _load_lane_validations_uncached(ledger_updated_at),
    )


def _load_lane_validations_uncached(
    ledger_updated_at: datetime | None,
) -> dict[str, dict[str, object]]:
    if ledger_updated_at is not None:
        try:
            persisted = load_latest_lane_validations(
                strategy_version=STRATEGY_VERSION,
                captured_after=ledger_updated_at,
            )
        except Exception:  # noqa: BLE001
            persisted = None
        if _persisted_lane_validations_complete(persisted):
            return persisted

    try:
        from alphaagent.server.services.limit_up.history_service import (
            get_scheduled_history_backtest,
            get_lane_validation_snapshot,
        )

        validations = {
            lane: dict(validation)
            for lane, validation in get_lane_validation_snapshot().items()
        }
        report = get_scheduled_history_backtest(None, None, trade_limit=1)
        comparison = report.get("relay_comparison")
        comparison = comparison if isinstance(comparison, Mapping) else {}
        configured_variant = str(comparison.get("configured_variant") or "")
        variants = comparison.get("variants")
        variants = variants if isinstance(variants, Mapping) else {}
        configured = variants.get(configured_variant)
        configured = configured if isinstance(configured, Mapping) else {}
        if (
            comparison.get("configuration_matches_gate") is True
            and configured.get("passed") is True
        ):
            summary = configured.get("summary")
            summary = dict(summary) if isinstance(summary, Mapping) else {}
            for lane in scheduled_execution.PRODUCT_EXECUTION_LANES:
                validations[lane] = {
                    "passed": True,
                    "status": "portfolio_gate_passed",
                    "reason": "统一盘中两仓组合已通过收益、回撤和双倍成本门槛",
                    "summary": summary,
                }
        return validations
    except Exception as exc:  # noqa: BLE001
        reason = f"战法验证暂不可用：{exc.__class__.__name__}"
        return {
            lane: {"passed": False, "status": "unavailable", "reason": reason}
            for lane in ("first_board", "two_to_three", "high_board")
        }


def _persisted_lane_validations_complete(
    validations: Mapping[str, Mapping[str, object]] | None,
) -> bool:
    if not isinstance(validations, Mapping):
        return False
    return all(
        isinstance(validation := validations.get(lane), Mapping)
        and isinstance(validation.get("summary"), Mapping)
        for lane in scheduled_execution.RESEARCH_EXECUTION_LANES
    )


def _compact_validation_summary(value: object) -> dict[str, object]:
    summary = value if isinstance(value, Mapping) else {}
    return {
        "trade_count": _integer(summary.get("trade_count")),
        "win_rate": _number(summary.get("win_rate")),
        "total_return_pct": _number(summary.get("total_return_pct")),
        "max_drawdown_pct": _number(summary.get("max_drawdown_pct")),
    }


def _without_removed_lane_recommendations(
    recommendations: Mapping[str, object],
) -> dict[str, object]:
    result = dict(recommendations)
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, Mapping) else {}
    result["lanes"] = {
        str(channel): [
            dict(signal)
            for signal in (signals if isinstance(signals, list) else [])
            if isinstance(signal, Mapping)
            and str(signal.get("board_lane") or "") != "one_to_two"
        ]
        for channel, signals in lanes.items()
    }
    return result


def _board_lane(board_level: int) -> str:
    if board_level <= 1:
        return "first_board"
    if board_level == 2:
        return "one_to_two"
    if board_level == 3:
        return "two_to_three"
    return "high_board"


def _session_second(value: str) -> int:
    parts = value.split(":")
    if len(parts) != 3:
        return -1
    try:
        hour, minute, second = (int(part) for part in parts)
    except ValueError:
        return -1
    return hour * 3600 + minute * 60 + second


def _with_historical_evidence(snapshot: Mapping[str, object]) -> dict[str, object]:
    try:
        return attach_historical_evidence(snapshot)
    except Exception as exc:  # noqa: BLE001
        result = _without_executable_actions(snapshot)
        quality = result.get("data_quality")
        quality = dict(quality) if isinstance(quality, Mapping) else {}
        source_errors = list(quality.get("source_errors") or [])
        source_errors.append(f"history_evidence:{exc.__class__.__name__}")
        quality["source_errors"] = source_errors
        limitations = list(quality.get("limitations") or [])
        limitations.append("历史相似样本暂不可用，实时买入动作已禁止执行。")
        quality["limitations"] = limitations
        result["data_quality"] = quality
        return result


def _without_executable_actions(snapshot: Mapping[str, object]) -> dict[str, object]:
    result = dict(snapshot)
    recommendations = result.get("recommendations")
    recommendations = dict(recommendations) if isinstance(recommendations, Mapping) else {}
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, Mapping) else {}
    blocked_lanes: dict[str, list[dict[str, object]]] = {}
    for lane, raw_signals in lanes.items():
        signals = raw_signals if isinstance(raw_signals, list) else []
        blocked_lanes[str(lane)] = [
            _signal_without_history_evidence(signal, str(lane), snapshot.get("trade_date"))
            for signal in signals
            if isinstance(signal, Mapping)
        ]
    recommendations["lanes"] = blocked_lanes
    result["recommendations"] = recommendations
    return result


def _signal_without_history_evidence(
    signal: Mapping[str, object],
    lane: str,
    trade_date: object,
) -> dict[str, object]:
    result = dict(signal)
    if str(result.get("action") or "") in EXECUTABLE_ACTIONS:
        result["action"] = "pass"
        result["execution_state"] = "cancelled"
        result["reason"] = HISTORY_EVIDENCE_UNAVAILABLE_REASON
    result["historical_evidence"] = {
        "status": "unavailable",
        "entry_mode": _entry_mode_for_unavailable_evidence(result, lane),
        "feature_scope": (
            "next_auction_gap_pending" if lane == "next_auction" else "point_in_time_match"
        ),
        "as_of_date": str(trade_date or "") or None,
        "risk_vetoed": str(signal.get("action") or "") in EXECUTABLE_ACTIONS,
        "risk_veto_reasons": [HISTORY_EVIDENCE_UNAVAILABLE_REASON],
        "sample_count": 0,
        "effective_sample_count": 0,
        "smoothed_win_rate": None,
        "average_return_pct": None,
        "hard_loss_rate": None,
        "confidence": "insufficient",
    }
    return result


def _entry_mode_for_unavailable_evidence(signal: Mapping[str, object], lane: str) -> str:
    if lane == "next_auction":
        return "next_auction"
    if lane == "tail":
        return "tail"
    return "auction" if signal.get("entry_kind") == "auction" else "sweep"


def _market_context(
    candidates: Sequence[Mapping[str, object]],
    stock_context: Mapping[str, object],
    previous_snapshot: Mapping[str, object] | None,
) -> dict[str, object]:
    sealed_count = sum(
        1 for row in candidates if row.get("state") in {"sealed", "resealed"}
    )
    failed_count = sum(1 for row in candidates if row.get("state") == "failed")
    previous_market = previous_snapshot.get("market_context") if previous_snapshot else None
    previous_market = previous_market if isinstance(previous_market, Mapping) else {}
    return {
        "sealed_count": sealed_count,
        "failed_count": failed_count,
        "failed_rate": round(failed_count / (sealed_count + failed_count), 4)
        if sealed_count + failed_count
        else None,
        "sealed_change": sealed_count - _integer(previous_market.get("sealed_count"), sealed_count),
        "failed_change": failed_count - _integer(previous_market.get("failed_count"), failed_count),
        "sentiment": dict(stock_context.get("sentiment") or {}),
        "timing": dict(stock_context.get("timing") or {}),
        "data_cutoff": "LIVE_VISIBLE",
    }


def _attach_stability(
    candidates: list[dict[str, object]],
    previous_snapshot: Mapping[str, object] | None,
    captured_at: datetime,
) -> None:
    previous_rows = previous_snapshot.get("candidates") if previous_snapshot else None
    previous_by_symbol = {
        str(row.get("vt_symbol") or ""): row
        for row in previous_rows or []
        if isinstance(row, Mapping) and row.get("vt_symbol")
    }
    previous_at = _parsed_datetime(
        previous_snapshot.get("captured_at") if previous_snapshot else None
    )
    elapsed_minutes = (
        max(0, int((captured_at - previous_at).total_seconds() // 60))
        if previous_at is not None
        else 0
    )
    consecutive_snapshot = (
        previous_at is not None
        and 0 <= (captured_at - previous_at).total_seconds()
        <= MAX_CONSECUTIVE_SNAPSHOT_GAP_MINUTES * 60
    )
    for candidate in candidates:
        symbol = str(candidate.get("vt_symbol") or "")
        previous = previous_by_symbol.get(symbol)
        current_state = str(candidate.get("state") or "")
        currently_sealed = current_state in {"sealed", "resealed"}
        seen_before_seal = (
            current_state in {"near_limit", "failed"}
            or (
                isinstance(previous, Mapping)
                and previous.get("seen_before_seal") is True
            )
        )
        candidate["seen_before_seal"] = seen_before_seal
        candidate["missed_preseal_entry"] = currently_sealed and not seen_before_seal
        continuously_sealed = (
            currently_sealed
            and consecutive_snapshot
            and isinstance(previous, Mapping)
            and previous.get("state") in {"sealed", "resealed"}
        )
        candidate["stable_minutes"] = (
            _integer(previous.get("stable_minutes"), 0) + elapsed_minutes
            if continuously_sealed
            else 0
        )
        current_seal = _number(candidate.get("seal_amount"))
        previous_seal = _number(previous.get("seal_amount")) if previous else None
        if (
            consecutive_snapshot
            and current_seal is not None
            and previous_seal is not None
            and previous_seal > 0
        ):
            retention = current_seal / previous_seal
            candidate["seal_amount_retention_ratio"] = round(retention, 4)
            candidate["seal_amount_change_pct"] = round((retention - 1) * 100, 4)
        else:
            candidate["seal_amount_retention_ratio"] = None
            candidate["seal_amount_change_pct"] = None


def _candidate_symbols(
    quotes: Mapping[str, object],
    pools: Mapping[str, object],
    *,
    include_previous: bool = False,
) -> list[str]:
    return sorted(
        _merge_source_rows(
            quotes,
            pools,
            include_previous=include_previous,
            min_change_pct=TRACE_RADAR_MIN_CHANGE_PCT,
        )
    )


def _trace_candidates_with_ranked_details(
    trace_candidates: Sequence[Mapping[str, object]],
    ranked_candidates: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    ranked_by_symbol = {
        str(candidate.get("vt_symbol") or ""): candidate
        for candidate in ranked_candidates
        if candidate.get("vt_symbol")
    }
    result: list[dict[str, object]] = []
    for candidate in trace_candidates:
        merged = {
            **candidate,
            **dict(ranked_by_symbol.get(str(candidate.get("vt_symbol") or ""), {})),
        }
        if not merged.get("board_lane"):
            merged["board_lane"] = classify_board_lane(
                {
                    **merged,
                    "target_board": _integer(merged.get("board_level"), 1),
                }
            )
        result.append(merged)
    return result


def _save_live_trace_safely(snapshot: Mapping[str, object]) -> str | None:
    try:
        save_live_trace_snapshot(snapshot)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("limit-up live trace write failed: %s", exc)
        return str(exc)[:500]


def _save_live_trace_error_safely(
    captured_at: datetime,
    error: Exception,
) -> str | None:
    try:
        save_live_trace_error(
            captured_at,
            error,
            strategy_version=STRATEGY_VERSION,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("limit-up live trace error write failed: %s", exc)
        return str(exc)[:500]


def _set_live_trace_cache_status(
    snapshot: dict[str, object],
    error: str | None,
) -> None:
    quality = snapshot.get("data_quality")
    quality = dict(quality) if isinstance(quality, Mapping) else {}
    quality["trace_cache_status"] = "error" if error else "ready"
    if error:
        quality["trace_cache_error"] = error
    else:
        quality.pop("trace_cache_error", None)
    snapshot["data_quality"] = quality


def _is_radar_persistable_snapshot(
    snapshot: Mapping[str, object],
    captured_at: datetime,
) -> bool:
    return _is_persistable_snapshot(snapshot, captured_at)


def _has_preboard_scoring_work(snapshot: Mapping[str, object]) -> bool:
    capture = snapshot.get("trace_capture_candidates")
    return isinstance(capture, list) and bool(capture)


def _radar_quote_observed_at(
    concept_snapshot: Mapping[str, object] | None,
    quote_payload: Mapping[str, object],
) -> datetime | None:
    concept_time = (
        concept_snapshot.get("source_updated_at")
        if isinstance(concept_snapshot, Mapping)
        else None
    )
    return _parsed_datetime(concept_time or quote_payload.get("updated_at"))


def _save_radar_ledger_safely(
    snapshot: Mapping[str, object],
    *,
    full_quotes: Sequence[Mapping[str, object]] = (),
    quote_observed_at: datetime | None = None,
) -> str | None:
    try:
        capture = snapshot.get("trace_capture_candidates")
        capture = capture if isinstance(capture, list) else []
        formal_by_symbol = _now_signals_by_symbol(snapshot.get("recommendations"))
        early_by_symbol = _now_signals_by_symbol(
            snapshot.get("early_radar_recommendations")
        )
        observations = [
            project_radar_observation(
                candidate,
                formal_signal=formal_by_symbol.get(
                    str(candidate.get("vt_symbol") or "")
                ),
                early_signal=early_by_symbol.get(
                    str(candidate.get("vt_symbol") or "")
                ),
                quote_observed_at=quote_observed_at,
            )
            for candidate in capture
            if isinstance(candidate, Mapping)
        ]
        captured_at = _parsed_datetime(snapshot.get("captured_at"))
        if captured_at is not None and full_quotes and quote_observed_at is not None:
            recent_signals = load_recent_signal_observations(captured_at)
            observations.extend(
                build_fill_followup_observations(
                    recent_signals,
                    full_quotes,
                    quote_observed_at=quote_observed_at,
                    current_observation_symbols={
                        str(row.get("vt_symbol") or "")
                        for row in observations
                    },
                )
            )
        saved_frame = save_radar_frame(snapshot, observations)
        if isinstance(snapshot, dict) and isinstance(saved_frame, Mapping):
            snapshot["_preboard_frame_id"] = saved_frame.get("frame_id")
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("limit-up radar ledger write failed: %s", exc)
        return str(exc)[:500]


def _now_signals_by_symbol(value: object) -> dict[str, Mapping[str, object]]:
    recommendations = value if isinstance(value, Mapping) else {}
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, Mapping) else {}
    signals = lanes.get("now")
    signals = signals if isinstance(signals, list) else []
    return {
        str(signal.get("vt_symbol") or ""): signal
        for signal in signals
        if isinstance(signal, Mapping) and signal.get("vt_symbol")
    }


def _set_radar_ledger_status(
    snapshot: dict[str, object],
    error: str | None,
    *,
    skipped: bool = False,
) -> None:
    quality = snapshot.get("data_quality")
    quality = dict(quality) if isinstance(quality, Mapping) else {}
    quality["radar_ledger_status"] = (
        "skipped_invalid_frame" if skipped else "error" if error else "ready"
    )
    if error:
        quality["radar_ledger_error"] = error
    else:
        quality.pop("radar_ledger_error", None)
    snapshot["data_quality"] = quality


def _run_preboard_decision_safely(
    snapshot: dict[str, object],
) -> dict[str, object]:
    result = preboard_decision_service.score_active_live_preboard_snapshot_safely(
        snapshot,
        minute_buffer=_PREBOARD_MINUTE_BUFFER,
    )
    frame_id = _integer(snapshot.get("_preboard_frame_id"), 0)
    feature_rows = result.get("feature_rows")
    feature_rows = feature_rows if isinstance(feature_rows, list) else []
    if frame_id > 0 and feature_rows:
        try:
            result["feature_rows_saved"] = (
                preboard_decision_repository.save_decision_feature_rows(
                    [
                        {
                            **dict(row),
                            "frame_id": frame_id,
                            "label_status": "pending",
                        }
                        for row in feature_rows
                        if isinstance(row, Mapping)
                    ]
                )
            )
            result["feature_persistence_status"] = "ready"
        except Exception as exc:  # noqa: BLE001
            logger.warning("preboard live feature persistence failed: %s", exc)
            result["feature_rows_saved"] = 0
            result["feature_persistence_status"] = "error"
            result["feature_persistence_error"] = str(exc)[:500]
    _set_preboard_decision_status(snapshot, result)
    return result


def _set_preboard_decision_status(
    snapshot: dict[str, object],
    result: Mapping[str, object],
) -> None:
    quality = snapshot.get("data_quality")
    quality = dict(quality) if isinstance(quality, Mapping) else {}
    status = str(result.get("status") or "error")
    quality["preboard_status"] = status
    status_fields = {
        "decision_version": "preboard_decision_version",
        "probability_status": "preboard_probability_status",
        "probability_qualification_status": (
            "preboard_probability_qualification_status"
        ),
        "historical_promotion_status": "preboard_historical_promotion_status",
        "execution_mode": "preboard_execution_mode",
        "model_fingerprint": "preboard_model_fingerprint",
        "feature_fingerprint": "preboard_feature_fingerprint",
        "observation_count": "preboard_observation_count",
        "action_saved": "preboard_action_saved",
        "formal_strategy_changed": "preboard_formal_strategy_changed",
        "feature_rows_saved": "preboard_feature_rows_saved",
        "feature_persistence_status": "preboard_feature_persistence_status",
    }
    for source, target in status_fields.items():
        if source in result:
            quality[target] = result.get(source)
    error = str(result.get("error") or "").strip()
    if error:
        quality["preboard_error"] = error[:500]
    else:
        quality.pop("preboard_error", None)
    snapshot["preboard_candidates"] = _public_preboard_candidates(
        result.get("preboard_candidates")
    )
    _apply_formal_preboard_recommendations(snapshot, result)
    snapshot["data_quality"] = quality


def _public_preboard_candidates(value: object) -> list[dict[str, object]]:
    rows = value if isinstance(value, list) else []
    result: list[dict[str, object]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        state = str(raw.get("decision_state") or "observe")
        if state in {"missed", "rejected"}:
            continue
        touch_probability = _number(raw.get("touch_probability_3m"))
        eventual_probability = _number(raw.get("eventual_touch_probability"))
        if (
            str(raw.get("probability_status") or "") != "ready"
            or touch_probability is None
            or not 0.0 <= touch_probability <= 1.0
            or eventual_probability is None
            or not 0.0 <= eventual_probability <= 1.0
        ):
            continue
        candidate = {
            "vt_symbol": str(raw.get("vt_symbol") or ""),
            "name": str(raw.get("name") or raw.get("vt_symbol") or ""),
            "decision_state": state,
            "execution_mode": str(raw.get("execution_mode") or "research_only"),
            "change_pct": _number(raw.get("change_pct")),
            "distance_to_limit_pct": _number(raw.get("distance_to_limit_pct")),
            "expected_d1_net_return_pct": _number(
                raw.get("expected_d1_net_return_pct")
            ),
            "d1_win_probability": _number(raw.get("d1_win_probability")),
            "touch_probability_3m": touch_probability,
            "eventual_touch_probability": eventual_probability,
            "seal_probability_given_touch": _number(
                raw.get("seal_probability_given_touch")
            ),
            "probability_status": str(
                raw.get("probability_status") or "model_unavailable"
            ),
            "source_quality": str(raw.get("source_quality") or "unknown"),
            "updated_at": str(
                raw.get("decision_at") or raw.get("known_at") or ""
            ),
        }
        dynamic_leader = _public_dynamic_leader_shadow(
            raw.get("dynamic_leader_shadow")
        )
        if dynamic_leader is not None:
            candidate["dynamic_leader_shadow"] = dynamic_leader
        result.append(candidate)
    return result


def _public_dynamic_leader_shadow(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return {field: value.get(field) for field in DYNAMIC_LEADER_PUBLIC_FIELDS}


def _apply_formal_preboard_recommendations(
    snapshot: dict[str, object],
    result: Mapping[str, object],
) -> None:
    """Add promoted pre-board rows without removing the formal sweep fallback."""

    if str(result.get("execution_mode") or "") != "formal":
        return
    recommendations = snapshot.get("recommendations")
    if not isinstance(recommendations, Mapping):
        return
    updated = dict(recommendations)
    candidates = result.get("preboard_candidates")
    candidates = candidates if isinstance(candidates, list) else []
    formal_rows = [
        _formal_preboard_signal(row)
        for row in candidates
        if isinstance(row, Mapping)
        and row.get("actionable") is True
        and str(row.get("decision_state") or "") == "actionable"
    ]
    for field in ("actionable_recommendations", "portfolio"):
        existing = updated.get(field)
        existing = existing if isinstance(existing, list) else []
        updated[field] = _merge_preboard_with_formal_rows(formal_rows, existing)
    snapshot["recommendations"] = updated


def _merge_preboard_with_formal_rows(
    preboard_rows: Sequence[Mapping[str, object]],
    formal_rows: Sequence[object],
) -> list[dict[str, object]]:
    existing = _deduplicate_signal_rows(formal_rows)
    existing_symbols = {
        str(row.get("vt_symbol") or "") for row in existing if row.get("vt_symbol")
    }
    new_rows = [
        row
        for row in _deduplicate_signal_rows(preboard_rows)
        if str(row.get("vt_symbol") or "") not in existing_symbols
    ]
    return [*new_rows, *existing]


def _deduplicate_signal_rows(
    rows: Sequence[object],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen_symbols: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        symbol = str(row.get("vt_symbol") or "")
        if symbol and symbol in seen_symbols:
            continue
        if symbol:
            seen_symbols.add(symbol)
        result.append(row)
    return result


def _formal_preboard_signal(row: Mapping[str, object]) -> dict[str, object]:
    return {
        **dict(row),
        "board_lane": "first_board",
        "action": "buy_now",
        "entry_kind": "momentum",
        "signal_state": "trigger_ready",
        "execution_state": "actionable",
        "execution_permission": "formal",
        "portfolio_selected": True,
        "reason": "板前概率排序通过正式双门",
        "pending_reasons": [],
    }


def _set_scan_timing(
    snapshot: dict[str, object],
    *,
    scan_started: float,
    quotes_done: float,
    context_done: float,
    policy_done: float,
    persistence_done: float,
) -> None:
    quality = snapshot.get("data_quality")
    quality = dict(quality) if isinstance(quality, Mapping) else {}
    quality["scan_timing_ms"] = {
        "quotes": round((quotes_done - scan_started) * 1000),
        "context": round((context_done - quotes_done) * 1000),
        "policy": round((policy_done - context_done) * 1000),
        "persistence": round((persistence_done - policy_done) * 1000),
        "total": round((persistence_done - scan_started) * 1000),
    }
    snapshot["data_quality"] = quality


def _without_internal_radar_fields(
    snapshot: Mapping[str, object],
) -> dict[str, object]:
    internal_fields = {
        *RESEARCH_QUOTE_ENRICHMENT_FIELDS,
        "quote_flow_observed_at",
        "trace_capture_candidates",
        "early_radar_recommendations",
        "_preboard_frame_id",
    }

    def project(value: object) -> object:
        if isinstance(value, Mapping):
            return {
                key: project(item)
                for key, item in value.items()
                if key not in internal_fields
            }
        if isinstance(value, list):
            return [project(item) for item in value]
        return value

    result = project(snapshot)
    if not isinstance(result, dict):
        return {"preboard_candidates": []}
    if not isinstance(result.get("preboard_candidates"), list):
        result["preboard_candidates"] = []
    return result


def _pool_symbols(payload: Mapping[str, object], pool_key: str) -> set[str]:
    pools = payload.get("pools")
    pools = pools if isinstance(pools, Mapping) else {}
    pool = pools.get(pool_key)
    pool = pool if isinstance(pool, Mapping) else {}
    return {str(row.get("vt_symbol")) for row in _items(pool) if row.get("vt_symbol")}


def _pool_open_times(row: Mapping[str, object]) -> int:
    raw = row.get("raw")
    raw = raw if isinstance(raw, Mapping) else {}
    return _integer(
        row.get("open_times"),
        _integer(raw.get("炸板次数"), _integer(raw.get("开板次数"), 0)),
    )


def _items(payload: Mapping[str, object]) -> list[dict[str, object]]:
    value = payload.get("items")
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _source_name(*payloads: Mapping[str, object]) -> str:
    names = [str(payload.get("source")) for payload in payloads if payload.get("source")]
    return ",".join(dict.fromkeys(names)) or "unknown"


def _latest_source_time(*payloads: Mapping[str, object]) -> str | None:
    values = [str(payload.get("updated_at")) for payload in payloads if payload.get("updated_at")]
    if not values:
        return None
    return max(values, key=_timestamp_sort_key)


def _earliest_source_time(*payloads: Mapping[str, object]) -> str | None:
    values = [str(payload.get("updated_at")) for payload in payloads if payload.get("updated_at")]
    valid = [value for value in values if _parsed_datetime(value) is not None]
    if not valid:
        return None
    return min(valid, key=_timestamp_sort_key)


def _source_age_seconds(value: str | None, captured_at: datetime) -> int | None:
    source_time = _parsed_datetime(value)
    if source_time is None:
        return None
    return max(0, int((_local_datetime(captured_at) - source_time).total_seconds()))


def _rate_limit_status(errors: Sequence[object]) -> str:
    normalized = " ".join(str(error).lower() for error in errors)
    if "429" in normalized or "ratelimit" in normalized or "rate_limit" in normalized:
        return "limited"
    return "degraded" if errors else "normal"


def _source_error(source: str, exc: Exception) -> str:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    suffix = f":{status_code}" if status_code is not None else ""
    return f"{source}:{exc.__class__.__name__}{suffix}"


def _resolved_market_date(
    quote_payload: Mapping[str, object],
    pool_payload: Mapping[str, object],
    captured_at: datetime,
    stock_context: Mapping[str, object],
) -> date:
    for value in (
        pool_payload.get("trade_date"),
        quote_payload.get("trade_date"),
        stock_context.get("trade_date"),
    ):
        parsed = _parsed_date(value)
        if parsed is not None and parsed <= captured_at.date():
            return parsed
    if captured_at.weekday() >= 5:
        previous = _parsed_date(stock_context.get("previous_trade_date"))
        if previous is not None:
            return previous
        for payload in (pool_payload, quote_payload):
            source_date = _parsed_date(payload.get("updated_at"))
            if source_date is not None and source_date <= captured_at.date():
                return source_date
    return captured_at.date()


def _parsed_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        if len(text) >= 8 and text[:8].isdigit():
            return datetime.strptime(text[:8], "%Y%m%d").date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _snapshot_for_session(
    snapshot: Mapping[str, object],
    now: datetime,
    latest_trade_date: date | None,
) -> dict[str, object]:
    snapshot_date = _parsed_date(snapshot.get("trade_date"))
    active = _is_active_session(now)
    current = active and snapshot_date == now.date()
    if current:
        return dict(snapshot)
    resolved_date = latest_trade_date or snapshot_date or now.date()
    stale_reason = "当前为非交易时段" if not active else "快照不是当前交易日"
    return downgrade_snapshot_to_stale(
        snapshot,
        resolved_date,
        reason=stale_reason,
        resolved_session_stage="closed" if not active else session_stage(now),
    )


def _with_snapshot_age(
    snapshot: Mapping[str, object],
    now: datetime,
) -> dict[str, object]:
    local_now = _local_datetime(now)
    result = dict(snapshot)
    quality = result.get("data_quality")
    quality = dict(quality) if isinstance(quality, Mapping) else {}
    age_seconds = _snapshot_age_seconds(snapshot, local_now)
    quality["snapshot_age_seconds"] = age_seconds
    result["data_quality"] = quality
    if (
        _is_active_session(local_now)
        and result.get("mode") == "live_snapshot"
        and _parsed_date(result.get("trade_date")) == local_now.date()
        and quality.get("is_stale") is False
        and age_seconds is not None
        and age_seconds > LIVE_SNAPSHOT_MAX_AGE_SECONDS
    ):
        return downgrade_snapshot_to_stale(
            result,
            local_now.date(),
            reason=f"实时快照已延迟{age_seconds}秒，等待后台扫描更新",
            resolved_session_stage=session_stage(local_now),
        )
    return result


def _snapshot_age_seconds(snapshot: Mapping[str, object], now: datetime) -> int | None:
    captured_at = _parsed_datetime(snapshot.get("captured_at"))
    if captured_at is None:
        return None
    return max(0, int((_local_datetime(now) - captured_at).total_seconds()))


def downgrade_snapshot_to_stale(
    snapshot: Mapping[str, object],
    resolved_trade_date: date,
    *,
    reason: str,
    resolved_session_stage: str = "closed",
) -> dict[str, object]:
    quality = snapshot.get("data_quality")
    quality = dict(quality) if isinstance(quality, Mapping) else {}
    recommendations = snapshot.get("recommendations")
    recommendations = dict(recommendations) if isinstance(recommendations, Mapping) else {}
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, Mapping) else {}

    def cancelled_signals(signals: object) -> list[dict[str, object]]:
        if not isinstance(signals, list):
            return []
        return [
            {
                **dict(signal),
                "action": "pass",
                "entry_kind": "none",
                "execution_state": "cancelled",
                "reason": reason,
            }
            for signal in signals
            if isinstance(signal, Mapping)
        ]

    stale_lanes = {
        str(lane): cancelled_signals(signals)
        for lane, signals in lanes.items()
        if isinstance(signals, list)
    }
    stale_recommendations = {
        **recommendations,
        "session_stage": resolved_session_stage,
        "market_gate": {
            **dict(recommendations.get("market_gate") or {}),
            "passed": False,
            "repair_confirmed": False,
            "repair_state": "repair_revoked",
            "repair_revoked_reason": reason,
            "reasons": [reason],
        },
        "lanes": stale_lanes,
    }
    for collection in (
        "actionable_recommendations",
        "portfolio",
        "watchlist",
    ):
        if isinstance(recommendations.get(collection), list):
            stale_recommendations[collection] = cancelled_signals(
                recommendations[collection]
            )
    return {
        **dict(snapshot),
        "trade_date": resolved_trade_date.isoformat(),
        "session_stage": resolved_session_stage,
        "mode": "stale_snapshot",
        "recommendations": stale_recommendations,
        "data_quality": {
            **quality,
            "status": "stale",
            "is_stale": True,
        },
    }


def _timestamp_sort_key(value: str) -> datetime:
    try:
        return _local_datetime(datetime.fromisoformat(value))
    except ValueError:
        return datetime.min.replace(tzinfo=SHANGHAI)


def _parsed_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return _local_datetime(datetime.fromisoformat(str(value)))
    except ValueError:
        return None


def _stale_snapshot(snapshot: Mapping[str, object], exc: Exception) -> dict[str, object]:
    quality = snapshot.get("data_quality")
    quality = dict(quality) if isinstance(quality, Mapping) else {}
    errors = list(quality.get("source_errors") or [])
    errors.append(f"refresh:{exc.__class__.__name__}")
    return {
        **dict(snapshot),
        "mode": "stale_snapshot",
        "data_quality": {
            **quality,
            "status": "stale",
            "is_stale": True,
            "source_errors": errors,
        },
    }


def _local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def _now_shanghai() -> datetime:
    return datetime.now(SHANGHAI)


def _raw_number(row: Mapping[str, object], *keys: str) -> float | None:
    for key in keys:
        value = _number(row.get(key))
        if value is not None:
            return value
    return None


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _integer(value: object, default: int = 0) -> int:
    try:
        return int(float(value)) if value not in (None, "", "-") else int(default)
    except (TypeError, ValueError):
        return int(default)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    return round(numerator / denominator, 6) if numerator is not None and denominator else None
