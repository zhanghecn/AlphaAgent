"""Live quote collection and snapshot construction for the limit-up desk."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime
from zoneinfo import ZoneInfo

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
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
    build_live_market_gate,
    build_live_recommendations,
    rank_live_candidates,
    rank_live_opportunities,
    session_stage,
)
from alphaagent.server.services.limit_up.live_evidence import attach_historical_evidence
from alphaagent.server.services.limit_up.first_board_dual_lane import (
    attach_rotation_shadow,
)
from alphaagent.server.services.limit_up.lane_research import (
    classify_board_lane,
    evaluate_lane_candidate,
    select_daily_lane_portfolio,
)
from alphaagent.server.services.limit_up.live_repository import (
    load_latest_snapshot,
    load_latest_daily_trade_date,
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
from alphaagent.server.services.limit_up import scheduled_execution
from alphaagent.server.services.limit_up.versions import (
    LIVE_STRATEGY_VERSION as STRATEGY_VERSION,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
NEAR_LIMIT_MIN_CHANGE_PCT = 7.0
TRACE_RADAR_MIN_CHANGE_PCT = 5.0
LIVE_SCAN_INTERVAL_SECONDS = 15
LIVE_SNAPSHOT_MAX_AGE_SECONDS = 90
HISTORY_EVIDENCE_UNAVAILABLE_REASON = "历史证据不可用，已禁止执行"
EXECUTABLE_ACTIONS = frozenset({"buy_now", "next_auction"})
PORTFOLIO_EXECUTION_LANES = frozenset({"first_board"})
LIVE_WATCHLIST_LIMIT = 6
ACTIVE_SESSION_STAGES = frozenset(
    {"auction_watch", "auction", "morning", "afternoon", "tail", "close_auction"}
)
logger = logging.getLogger(__name__)


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
    candidates = _enrich_candidates(
        source_rows,
        pool_payload,
        stock_context,
        require_sector=False,
    )
    attach_candidate_concepts(candidates, concept_snapshot or {})
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
            "snapshot_age_seconds": 0,
            "source_age_seconds": _source_age_seconds(source_updated_at, local_at),
            "background_refresh_seconds": LIVE_SCAN_INTERVAL_SECONDS,
            "rate_limit_status": _rate_limit_status(source_errors),
            "source_errors": source_errors,
            "limitations": [
                "公共行情没有L2排队位置、撤单速度和逐笔成交，成交判断仅为盘口代理。",
                "秒板封死不视为可成交；实时推荐只供人工决策。",
            ],
        },
    }


def refresh_live_snapshot(
    captured_at: datetime | None = None,
    *,
    adapter: AkShareAdapter | None = None,
    persist: bool = True,
) -> dict[str, object]:
    """Collect current quotes, build recommendations, and optionally persist them."""

    local_at = _local_datetime(captured_at or datetime.now(SHANGHAI))
    if not _is_active_session(local_at):
        return _latest_snapshot_for_session(local_at)
    live_adapter = adapter or AkShareAdapter()
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
        concept_snapshot = get_latest_live_concept_snapshot(local_at)
        concept_snapshot = _concept_snapshot_with_incremental_quotes(
            concept_snapshot,
            quotes,
            pools,
            local_at,
        )
        radar_quotes = _quote_payload_with_full_radar(quotes, concept_snapshot)
        symbols = _candidate_symbols(
            radar_quotes,
            pools,
            include_previous=stage in {"auction_watch", "auction"},
        )
        market_date = _resolved_market_date(radar_quotes, pools, local_at, {})
        context = load_live_context(symbols, market_date) if symbols else {"by_symbol": {}}
        context = {**context, "source_errors": source_errors}
        lane_validations = _load_lane_validations()
        previous = load_latest_snapshot(market_date, strategy_version=STRATEGY_VERSION)
        snapshot = build_live_snapshot(
            quotes,
            pools,
            local_at,
            context,
            previous_snapshot=previous,
            concept_snapshot=concept_snapshot,
        )
        snapshot = _apply_live_risk_gates(snapshot, lane_validations)
        if persist:
            _set_live_trace_cache_status(
                snapshot,
                _save_live_trace_safely(snapshot),
            )
        if persist and _is_persistable_snapshot(snapshot, local_at):
            return save_snapshot(snapshot)
        return snapshot
    except Exception as exc:
        trace_error = _save_live_trace_error_safely(local_at, exc) if persist else None
        fallback = load_latest_snapshot(strategy_version=STRATEGY_VERSION)
        if fallback is None:
            raise LiveSnapshotUnavailable(str(exc)) from exc
        stale = _stale_snapshot(fallback, exc)
        if persist:
            _set_live_trace_cache_status(stale, trace_error)
        return stale


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
            return _with_snapshot_age(paused, local_now)
    if not _is_active_session(local_now):
        return _with_snapshot_age(_latest_snapshot_for_session(local_now), local_now)

    saved = load_latest_snapshot(local_now.date(), strategy_version=STRATEGY_VERSION)
    if saved is not None:
        return _with_snapshot_age(saved, local_now)
    return _with_snapshot_age(_latest_snapshot_for_session(local_now), local_now)


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
    payloads: dict[str, dict[str, object]] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            "quotes": executor.submit(
                adapter.list_stocks,
                page=1,
                page_size=200,
                sort="change_pct",
                order="desc",
            ),
            "pools": executor.submit(adapter.limit_up_pools, trade_key),
        }
        for name, future in futures.items():
            try:
                payload = future.result()
                payloads[name] = dict(payload) if isinstance(payload, Mapping) else {}
            except Exception as exc:  # noqa: BLE001
                payloads[name] = {}
                errors.append(_source_error(name, exc))
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
                    rows[str(row["vt_symbol"])] = row
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
    if not payloads["quotes"] and not payloads["pools"]:
        raise LiveSnapshotUnavailable("实时涨幅榜和涨停池均不可用")
    return payloads["quotes"], payloads["pools"], errors


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
    if isinstance(concept_snapshot, Mapping):
        for row in concept_snapshot.get("radar_quotes") or []:
            if isinstance(row, Mapping) and row.get("vt_symbol"):
                rows[str(row["vt_symbol"])] = dict(row)
    for row in _items(quote_payload):
        if row.get("vt_symbol"):
            rows[str(row["vt_symbol"])] = {
                **rows.get(str(row["vt_symbol"]), {}),
                **row,
            }
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
    """Re-aggregate cached full coverage with the latest 15-second strong rows."""

    if not isinstance(concept_snapshot, Mapping):
        return None
    membership = concept_snapshot.get("membership")
    if not isinstance(membership, Mapping):
        return dict(concept_snapshot)
    quote_by_symbol = {
        str(row.get("vt_symbol") or ""): dict(row)
        for row in concept_snapshot.get("quotes") or []
        if isinstance(row, Mapping) and row.get("vt_symbol")
    }
    for row in _items(quote_payload):
        symbol = str(row.get("vt_symbol") or "")
        if symbol:
            quote_by_symbol[symbol] = {**quote_by_symbol.get(symbol, {}), **row}
    incremental_rows = _merge_source_rows(
        quote_payload,
        pool_payload,
        min_change_pct=TRACE_RADAR_MIN_CHANGE_PCT,
    )
    for symbol, row in incremental_rows.items():
        quote_by_symbol[symbol] = {**quote_by_symbol.get(symbol, {}), **row}

    base_concepts = {
        str(row.get("concept_id") or ""): row
        for row in concept_snapshot.get("concepts") or []
        if isinstance(row, Mapping) and row.get("concept_id")
    }
    recomputed = aggregate_concept_strength(
        list(quote_by_symbol.values()),
        membership,
        captured_at=captured_at,
        history_by_concept={
            concept_id: [row]
            for concept_id, row in base_concepts.items()
        },
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
    concepts = rank_concepts(recomputed)
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
        **deepcopy(dict(concept_snapshot)),
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
        rows[symbol] = {**raw, "state": "near_limit", "pool_key": "quote"}

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
        board_level = _integer(candidate.get("board_level"), 1)
        candidate["board_lane"] = _board_lane(board_level)
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
    evaluation_time = captured_at.time().replace(microsecond=0).isoformat()
    state = str(candidate.get("state") or "")
    actual_first_touch = (
        normalize_limit_time(candidate.get("first_limit_time"))
        if state in {"sealed", "resealed", "failed"}
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
        "prior_industry_heat_score": candidate.get("concept_strength_score")
        if candidate.get("concept_strength_score") is not None
        else candidate.get("sector_heat"),
        "prior_industry_leader_rank": candidate.get("concept_leader_rank")
        if candidate.get("concept_leader_rank") is not None
        else candidate.get("sector_dragon_rank"),
        "prior_market_phase": sentiment.get("phase"),
        "prior_market_failed_rate": sentiment.get("failed_limit_up_rate"),
        "live_market_repair_confirmed": bool(
            market_gate and market_gate.get("repair_confirmed")
        ),
        "has_l2": False,
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
    recommendations = result.get("recommendations")
    recommendations = recommendations if isinstance(recommendations, Mapping) else {}
    validated = apply_lane_validation_veto(recommendations, lane_validations)
    captured_at = _parsed_datetime(result.get("captured_at")) or datetime.now(SHANGHAI)
    quality = result.get("data_quality")
    quality = quality if isinstance(quality, Mapping) else {}
    snapshot_age = _integer(quality.get("snapshot_age_seconds"), 0)
    validated["execution_schedule"] = scheduled_execution.execution_clock(captured_at)
    validated["portfolio"] = _build_live_portfolio(
        validated,
        captured_at=captured_at,
        snapshot_age_seconds=snapshot_age,
    )
    validated["watchlist"] = _build_live_watchlist(validated)
    return {**result, "recommendations": validated}


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
            symbol = str(signal.get("vt_symbol") or "")
            research_action = str(
                signal.get("research_action") or signal.get("action") or "pass"
            )
            if (
                not symbol
                or signal.get("portfolio_selected") is not True
                or str(signal.get("board_lane") or "") not in PORTFOLIO_EXECUTION_LANES
                or research_action not in {"buy_now", "observe"}
                or signal.get("missed_preseal_entry") is True
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
    return [
        _scheduled_live_signal(signal, schedule, snapshot_age_seconds)
        for signal in sorted(selected.values(), key=_live_portfolio_sort_key)[
            : scheduled_execution.MAX_POSITIONS
        ]
    ]


def _scheduled_live_signal(
    signal: Mapping[str, object],
    schedule: Mapping[str, object],
    snapshot_age_seconds: int,
) -> dict[str, object]:
    result = {
        **dict(signal),
        "execution_permission": "research_only",
        "scheduled_execution_version": scheduled_execution.SCHEDULED_EXECUTION_VERSION,
        "buy_instruction": "仅在10:00-11:30或13:00-14:30满足全部条件时买入",
        "sell_instruction": "D+1 14:30 统一卖出",
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
    research_action = str(
        signal.get("research_action") or signal.get("action") or "pass"
    )
    if research_action != "buy_now":
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
    action = str(signal.get("research_action") or signal.get("action") or "pass")
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
    return (
        action_priority,
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
                or signal.get("missed_preseal_entry") is True
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
            lane_blocked = str(signal.get("lane_decision") or "") == "blocked"
            near_limit = str(signal.get("state") or "") == "near_limit"
            current_signal_state = str(signal.get("signal_state") or "observing")
            observations[symbol] = {
                **signal,
                "action": "observe",
                "research_action": original_action,
                "execution_state": "watch",
                "signal_state": (
                    "rejected"
                    if lane_blocked
                    else "concept_warming"
                    if current_signal_state == "concept_warming"
                    else "approaching_trigger"
                    if near_limit
                    else "observing"
                ),
                "entry_kind": "sweep" if near_limit else signal.get("entry_kind"),
                "buy_instruction": (
                    "板位硬门未通过，今日不买"
                    if lane_blocked
                    else "板块已预热，等待进入距涨停1%触发区"
                    if current_signal_state == "concept_warming"
                    else "距涨停不超过1%且市场、板块、资金和盘口条件保持通过时触发"
                ),
                "reason": (
                    f"今日拒买：{original_reason}"
                    if lane_blocked
                    else f"等待触发：{original_reason}"
                ),
            }
    return sorted(observations.values(), key=_live_watchlist_sort_key)[
        :LIVE_WATCHLIST_LIMIT
    ]


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
        from alphaagent.server.services.limit_up.history_service import (
            get_lane_validation_snapshot,
        )

        return get_lane_validation_snapshot()
    except Exception as exc:  # noqa: BLE001
        reason = f"战法验证暂不可用：{exc.__class__.__name__}"
        return {
            lane: {"passed": False, "status": "unavailable", "reason": reason}
            for lane in ("first_board", "one_to_two", "two_to_three", "high_board")
        }


def _board_lane(board_level: int) -> str:
    if board_level <= 1:
        return "first_board"
    if board_level == 2:
        return "one_to_two"
    if board_level == 3:
        return "two_to_three"
    return "high_board"


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
    for collection in ("portfolio", "watchlist"):
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
