"""Limit-up Top5 dashboard and conservative proxy backtest."""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import date
from statistics import mean
from typing import Any, Mapping

from alphaagent.market.cache import TTLCache
from alphaagent.server.services.limit_up.domain import (
    analyze_d1_outcome,
    event_fill_status,
    is_eligible_main_board,
    main_board_limit_price,
    normalize_limit_time,
    percentile_ranks,
    rank_dragon_candidates,
    reseal_observation_status,
    summarize_proxy_trades,
)
from alphaagent.server.services.limit_up.features import (
    close_stock_features,
    intraday_observation_features,
    market_snapshot_for_trade,
    prior_stock_features,
    promotion_rate_for_board,
    score_pretrade_candidates,
    sector_score_index,
)
from alphaagent.server.services.limit_up.policy import build_daily_research_plan
from alphaagent.server.services.limit_up.repository import (
    list_limit_up_event_dates,
    load_limit_up_dataset,
)

_TRADE_DATE_CACHE = TTLCache(max_items=1)
_DASHBOARD_CACHE = TTLCache(max_items=32)

_STATUS_THEME_KEYWORDS = (
    "昨日",
    "近期",
    "最近",
    "新高",
    "强势",
    "涨停",
    "连板",
    "打板",
    "炸板",
    "高换手",
    "高振幅",
    "龙虎榜",
    "融资融券",
    "沪股通",
    "深股通",
    "专精特新",
    "大盘股",
    "小盘股",
    "微盘股",
    "年报",
    "中报",
    "季报",
    "预增",
    "预减",
    "首亏",
    "扭亏",
    "亏损",
    "微利股",
    "破净股",
    "低价股",
    "高价股",
    "机构重仓",
    "基金重仓",
    "社保重仓",
    "养老金",
    "证金持股",
    "标准普尔",
    "富时罗素",
    "上证",
    "中证",
    "MSCI",
    "创业板综",
    "风格",
    "热股",
    "股权激励",
    "AH股",
    "QFII",
    "百元股",
    "破增发价",
    "深成",
    "沪深",
    "反转股",
    "HS300",
    "题材股",
    "成份股",
    "成分股",
    "趋势股",
    "大盘成长",
)


def get_limit_up_trade_dates() -> dict[str, object]:
    dates = _TRADE_DATE_CACHE.get_or_set(
        "verified-limit-up-event-dates",
        30,
        list_limit_up_event_dates,
    )
    return _trade_dates_payload(dates)


def get_limit_up_dashboard(target_date: date | None = None) -> dict[str, object]:
    date_payload = get_limit_up_trade_dates()
    available_dates = [str(value) for value in date_payload.get("dates") or []]
    resolved_date = target_date
    if resolved_date is None and available_dates:
        resolved_date = date.fromisoformat(available_dates[-1])
    cache_key = (
        f"dashboard:{resolved_date.isoformat() if resolved_date else 'empty'}:"
        f"{available_dates[-1] if available_dates else 'none'}:{len(available_dates)}"
    )
    ttl_seconds = 30 if resolved_date == date.today() else 3600
    return _DASHBOARD_CACHE.get_or_set(
        cache_key,
        ttl_seconds,
        lambda: _load_selected_dashboard(resolved_date, available_dates),
    )


def get_limit_up_proxy_backtest(
    start: date | None,
    end: date | None,
    exit_mode: str,
) -> dict[str, object]:
    dataset = load_limit_up_dataset(start=start, end=end)
    return build_limit_up_proxy_backtest(dataset, exit_mode=exit_mode)


def build_limit_up_trade_dates(dataset: Mapping[str, object]) -> dict[str, object]:
    dates = _available_event_dates(
        _dict_rows(dataset.get("events")),
        _trading_date_set(dataset),
    )
    return _trade_dates_payload(dates)


def _trade_dates_payload(dates: list[str]) -> dict[str, object]:
    return {
        "status": "ready" if dates else "empty",
        "dates": dates,
        "start": dates[0] if dates else None,
        "end": dates[-1] if dates else None,
        "latest": dates[-1] if dates else None,
        "count": len(dates),
    }


def _load_selected_dashboard(
    target_date: date | None,
    available_dates: list[str],
) -> dict[str, object]:
    target_text = target_date.isoformat() if target_date else None
    dataset = (
        load_limit_up_dataset(start=target_date, end=target_date)
        if target_text in available_dates
        else {}
    )
    dashboard = build_limit_up_dashboard(dataset, target_date=target_date)
    return {
        **dashboard,
        "available_dates": available_dates,
        "navigation": _date_navigation(available_dates, target_text),
    }


def build_limit_up_dashboard(
    dataset: Mapping[str, object],
    *,
    target_date: date | None = None,
) -> dict[str, object]:
    events = _dict_rows(dataset.get("events"))
    trading_dates = _trading_date_set(dataset)
    available_dates = _available_event_dates(events, trading_dates)
    selected_date = target_date.isoformat() if target_date else (available_dates[-1] if available_dates else None)
    navigation = _date_navigation(available_dates, selected_date)
    if not events or selected_date not in available_dates:
        return _empty_dashboard(
            dataset,
            trade_date=selected_date,
            available_dates=available_dates,
            navigation=navigation,
        )

    selected_events = [event for event in events if event.get("trade_date") == selected_date]
    sector_flows = _dict_rows(dataset.get("sector_flows"))
    sector_scores = sector_score_index(_dict_rows(dataset.get("sector_scores")))
    stock_flows = _dict_rows(dataset.get("stock_flows"))
    sentiment_points = _dict_rows(dataset.get("sentiment_points"))
    timing_signals = _dict_rows(dataset.get("timing_signals"))
    memberships = _dict_rows(dataset.get("memberships"))
    daily_bars = _daily_bar_index(_dict_rows(dataset.get("daily_bars")))
    calendar_dates = sorted(trading_dates)
    membership_map = _membership_map(memberships)
    sealed_event_index = {
        (str(event.get("vt_symbol") or ""), str(event.get("trade_date") or "")): event
        for event in events
        if bool(event.get("is_sealed"))
    }
    flow_date = _latest_row_date(sector_flows, selected_date, strict_before=True)
    sector_flow_map = _sector_flow_map(sector_flows, flow_date)
    stock_flow_map = _stock_flow_map(stock_flows, selected_date)
    close_sector_flow_map = _sector_flow_map(sector_flows, selected_date)
    prior_trade_date = max((item for item in calendar_dates if item < selected_date), default=None)
    prior_stock_flow_map = _stock_flow_map(stock_flows, prior_trade_date or "")
    prior_sector_scores = _sector_scores_for_date(sector_scores, prior_trade_date)
    pretrade_market = market_snapshot_for_trade(
        selected_date,
        prior_trade_date,
        sentiment_points,
        timing_signals,
        calendar_dates,
    )
    selected_sector_counts = _observed_sector_membership_counts(selected_events, membership_map)

    sector_events = []
    for event in selected_events:
        if not is_eligible_main_board(
            str(event.get("vt_symbol") or ""), str(event.get("name") or "")
        ):
            continue
        sector = _select_event_sector(
            event,
            membership_map,
            sector_flow_map,
            prior_sector_scores,
            selected_sector_counts,
        )
        if sector is None:
            continue
        sector_events.append({**event, **sector})

    top_dragons = _rank_intraday_sequence(
        selected_events,
        membership_map,
        sector_flow_map,
        sector_scores,
        sentiment_points,
        timing_signals,
        calendar_dates,
        daily_bars,
        sealed_event_index,
        prior_stock_flow_map,
    )
    for candidate in top_dragons:
        _attach_replay_display_scores(
            candidate,
            close_sector_flow_map,
            stock_flow_map,
            daily_bars,
        )
        _attach_dashboard_decision(candidate)
        candidate["outcome"] = _historical_outcome(candidate, daily_bars)

    research_plan = build_daily_research_plan(top_dragons, pretrade_market)

    failed_count = sum(
        1
        for event in selected_events
        if not bool(event.get("is_sealed"))
        and is_eligible_main_board(str(event.get("vt_symbol") or ""), str(event.get("name") or ""))
    )
    sealed_count = sum(
        1
        for event in selected_events
        if bool(event.get("is_sealed"))
        and is_eligible_main_board(str(event.get("vt_symbol") or ""), str(event.get("name") or ""))
    )
    return {
        "status": "ready",
        "mode": "historical_event_replay",
        "trade_date": selected_date,
        "as_of_time": f"{selected_date}T15:00:00+08:00",
        "ranking_basis": "d1_sentiment_timing_sector_heat_flow_board_ladder_first_touch_liquidity",
        "historical_sector_flow_date": flow_date,
        "pretrade_market": pretrade_market,
        "close_sentiment": _sentiment_for_date(sentiment_points, selected_date),
        "available_dates": available_dates,
        "navigation": navigation,
        "summary": {
            "sealed_count": sealed_count,
            "failed_count": failed_count,
            "seal_rate": round(sealed_count / (sealed_count + failed_count) * 100, 4)
            if sealed_count + failed_count
            else None,
            "max_limit_times": max(
                (int(event.get("limit_times") or 0) for event in selected_events),
                default=0,
            ),
            "top_dragon_count": len(top_dragons),
        },
        "top_sectors": _dashboard_sector_rows(
            sector_events,
            top_dragons,
            sector_flow_map,
            prior_sector_scores,
            close_sector_flow_map,
        ),
        "top_dragons": top_dragons,
        "research_plan": research_plan,
        "coverage": dict(dataset.get("coverage") or {}),
        "feature_availability": _feature_availability(),
        "data_sources": [
            "stock_events",
            "stock_daily_bars",
            "sector_period_scores",
            "sector_fund_flows",
            "stock_fund_flows",
            "stock_sector_memberships",
            "market_timing_panel",
        ],
        "limitations": _dashboard_limitations(flow_date),
    }


def build_limit_up_proxy_backtest(
    dataset: Mapping[str, object],
    *,
    exit_mode: str = "next_open",
    commission_rate: float = 0.0003,
    stamp_tax_rate: float = 0.0005,
    slippage_bps: float = 10.0,
) -> dict[str, object]:
    if exit_mode not in {"next_open", "next_close"}:
        raise ValueError(f"Unsupported exit mode: {exit_mode}")

    trading_dates = _trading_date_set(dataset)
    events = [
        event
        for event in _dict_rows(dataset.get("events"))
        if is_eligible_main_board(str(event.get("vt_symbol") or ""), str(event.get("name") or ""))
        and str(event.get("trade_date") or "") in trading_dates
    ]
    if not events:
        return _empty_backtest(dataset, exit_mode)

    memberships = _membership_map(_dict_rows(dataset.get("memberships")))
    sector_flows = _dict_rows(dataset.get("sector_flows"))
    sector_scores = sector_score_index(_dict_rows(dataset.get("sector_scores")))
    stock_flows = _dict_rows(dataset.get("stock_flows"))
    sentiment_points = _dict_rows(dataset.get("sentiment_points"))
    timing_signals = _dict_rows(dataset.get("timing_signals"))
    calendar_dates = sorted(trading_dates)
    previous_calendar_date = {
        calendar_dates[index]: calendar_dates[index - 1]
        for index in range(1, len(calendar_dates))
    }
    sector_flows_by_date = _sector_flow_date_index(sector_flows)
    sector_flow_dates = sorted(sector_flows_by_date)
    stock_flows_by_date = _stock_flow_date_index(stock_flows)
    sector_scores_by_date: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    for (score_date, sector_id), row in sector_scores.items():
        sector_scores_by_date[score_date][sector_id] = dict(row)
    daily_bars = _daily_bar_index(_dict_rows(dataset.get("daily_bars")))
    sealed_event_index = {
        (str(event.get("vt_symbol") or ""), str(event.get("trade_date") or "")): event
        for event in events
        if bool(event.get("is_sealed"))
    }
    events_by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    for event in events:
        events_by_date[str(event["trade_date"])].append(event)

    orders: list[dict[str, object]] = []
    scenario_trades: dict[str, list[dict[str, object]]] = {
        "conservative": [],
        "optimistic": [],
    }
    ranked_days = 0
    for trade_date in sorted(events_by_date):
        prior_trade_date = previous_calendar_date.get(trade_date)
        previous_flow_date = _latest_indexed_date(
            sector_flow_dates,
            trade_date,
            strict_before=True,
        )
        sector_flow_map = sector_flows_by_date.get(previous_flow_date or "", {})
        ranked = _rank_intraday_sequence(
            events_by_date[trade_date],
            memberships,
            sector_flow_map,
            sector_scores,
            sentiment_points,
            timing_signals,
            calendar_dates,
            daily_bars,
            sealed_event_index,
            stock_flows_by_date.get(prior_trade_date or "", {}),
            replay_all_touches=False,
            prior_trade_date_override=prior_trade_date,
            prior_sector_scores_override=sector_scores_by_date.get(
                prior_trade_date or "",
                {},
            ),
        )
        if not ranked:
            continue
        ranked_days += 1
        for candidate in ranked:
            _attach_replay_display_scores(
                candidate,
                sector_flows_by_date.get(trade_date, {}),
                stock_flows_by_date.get(trade_date, {}),
                daily_bars,
            )
            _attach_dashboard_decision(candidate)
            order = _proxy_order(candidate, daily_bars)
            orders.append(order)
            for scenario in ("conservative", "optimistic"):
                if not str(order[f"{scenario}_status"]).startswith("filled_"):
                    continue
                trade = _proxy_trade(
                    order,
                    candidate,
                    daily_bars,
                    exit_mode=exit_mode,
                    commission_rate=commission_rate,
                    stamp_tax_rate=stamp_tax_rate,
                    slippage_bps=slippage_bps,
                )
                if trade is not None:
                    scenario_trades[scenario].append(trade)

    scenarios = {
        scenario: _scenario_payload(
            orders,
            trades,
            scenario,
            trade_dates=sorted(events_by_date),
        )
        for scenario, trades in scenario_trades.items()
    }
    research_plan = _research_plan_backtest(
        orders,
        scenario_trades["conservative"],
        sorted(events_by_date),
    )
    coverage = dict(dataset.get("coverage") or {})
    event_days = int(coverage.get("event_trade_days") or 0)
    status = "ready" if orders else "insufficient_data"
    return {
        "status": status,
        "mode": "historical_event_proxy",
        "exit_mode": exit_mode,
        "selection_rule": "d1_sentiment_timing_sector_heat_flow_board_ladder_first_touch_liquidity",
        "orders": orders,
        "scenarios": scenarios,
        "research_plan": research_plan,
        "coverage": {**coverage, "ranked_trade_days": ranked_days},
        "feature_availability": _feature_availability(),
        "limitations": _backtest_limitations(event_days),
    }


def _score_dashboard_candidates(
    candidates: list[dict[str, object]],
    sector_flow_map: Mapping[str, Mapping[str, object]],
    stock_flow_map: Mapping[str, Mapping[str, object]],
) -> None:
    sector_values = {
        str(candidate["vt_symbol"]): _number(
            sector_flow_map.get(str(candidate["sector_id"]), {}).get("main_net_inflow")
        )
        for candidate in candidates
    }
    stock_values = {
        str(candidate["vt_symbol"]): _number(
            stock_flow_map.get(str(candidate["vt_symbol"]), {}).get("main_net_inflow")
        )
        for candidate in candidates
    }
    sector_ranks = percentile_ranks(sector_values)
    stock_ranks = percentile_ranks(stock_values)
    for candidate in candidates:
        symbol = str(candidate["vt_symbol"])
        position_score = min(max(int(candidate.get("limit_times") or 1), 1), 3) / 3
        seal_strength = _seal_strength(candidate)
        turnover_quality = _turnover_quality(_number(candidate.get("turnover_rate")))
        candidate["sector_flow_percentile"] = round(sector_ranks[symbol], 4)
        candidate["stock_flow_percentile"] = round(stock_ranks[symbol], 4)
        candidate["position_score"] = round(position_score, 4)
        candidate["seal_strength_score"] = round(seal_strength, 4)
        candidate["turnover_quality_score"] = round(turnover_quality, 4)
        candidate["dragon_score"] = round(
            35 * sector_ranks[symbol]
            + 25 * position_score
            + 20 * seal_strength
            + 10 * stock_ranks[symbol]
            + 10 * turnover_quality,
            4,
        )
        candidate["prior_sector_main_net_inflow"] = _number(
            sector_flow_map.get(str(candidate.get("sector_id") or ""), {}).get("main_net_inflow")
        )
        candidate["sector_main_net_inflow"] = sector_values[symbol]
        candidate["stock_main_net_inflow"] = stock_values[symbol]
        candidate["seal_to_float_market_cap_ratio"] = _ratio(
            _number(candidate.get("seal_amount")), _number(candidate.get("float_market_cap"))
        )
        candidate["seal_to_turnover_ratio"] = _ratio(
            _number(candidate.get("seal_amount")), _number(candidate.get("turnover"))
        )


def _rank_historical_day(
    day_events: list[dict[str, object]],
    memberships: Mapping[str, list[dict[str, object]]],
    sector_flow_map: Mapping[str, Mapping[str, object]],
    sector_scores: Mapping[tuple[str, str], Mapping[str, object]],
    sentiment_points: list[dict[str, object]],
    timing_signals: list[dict[str, object]],
    calendar_dates: list[str],
    daily_bars: Mapping[str, list[dict[str, object]]],
    sealed_event_index: Mapping[tuple[str, str], dict[str, object]],
    prior_stock_flow_map: Mapping[str, Mapping[str, object]],
    *,
    prior_trade_date_override: str | None = None,
    prior_sector_scores_override: Mapping[str, Mapping[str, object]] | None = None,
) -> list[dict[str, object]]:
    del sealed_event_index
    if not day_events:
        return []
    trade_date = str(day_events[0].get("trade_date") or "")
    prior_trade_date = prior_trade_date_override or max(
        (item for item in calendar_dates if item < trade_date),
        default=None,
    )
    prior_sector_scores = (
        dict(prior_sector_scores_override)
        if prior_sector_scores_override is not None
        else _sector_scores_for_date(sector_scores, prior_trade_date)
    )
    market_snapshot = market_snapshot_for_trade(
        trade_date,
        prior_trade_date,
        sentiment_points,
        timing_signals,
        calendar_dates,
    )
    observed_sector_counts = _observed_sector_membership_counts(day_events, memberships)
    candidates = []
    for event in day_events:
        if not is_eligible_main_board(
            str(event.get("vt_symbol") or ""), str(event.get("name") or "")
        ):
            continue
        sector = _select_event_sector(
            event,
            memberships,
            sector_flow_map,
            prior_sector_scores,
            observed_sector_counts,
        )
        if sector is None:
            continue
        symbol = str(event["vt_symbol"])
        trade_date = str(event["trade_date"])
        symbol_bars = daily_bars.get(symbol, [])
        previous_bar = _adjacent_bar(symbol_bars, trade_date, direction=-1)
        prior_streak = _prior_limit_streak(symbol_bars, trade_date)
        candidates.append(
            {
                **event,
                **sector,
                "prior_streak": prior_streak,
                "signal_board_level": prior_streak + 1,
                "prior_turnover": _number((previous_bar or {}).get("turnover")),
                "prior_stock": prior_stock_features(
                    symbol_bars,
                    trade_date,
                    assume_sorted=True,
                ),
                "prior_stock_flow": dict(prior_stock_flow_map.get(symbol, {})),
            }
        )
    intraday_by_symbol = intraday_observation_features(candidates)
    for candidate in candidates:
        candidate["intraday"] = intraday_by_symbol.get(str(candidate.get("vt_symbol") or ""), {})
        candidate["historical_sector_flow_date"] = next(
            (
                str(row.get("trade_date"))
                for row in sector_flow_map.values()
                if row.get("trade_date")
            ),
            None,
        )
    scored = score_pretrade_candidates(
        candidates,
        sector_flow_map,
        prior_sector_scores,
        market_snapshot,
    )
    for candidate in scored:
        sentiment = market_snapshot.get("sentiment")
        candidate["target_board_promotion_rate"] = promotion_rate_for_board(
            sentiment if isinstance(sentiment, Mapping) else None,
            int(candidate.get("signal_board_level") or 1),
        )
    return rank_dragon_candidates(scored)


def _rank_intraday_sequence(
    day_events: list[dict[str, object]],
    memberships: Mapping[str, list[dict[str, object]]],
    sector_flow_map: Mapping[str, Mapping[str, object]],
    sector_scores: Mapping[tuple[str, str], Mapping[str, object]],
    sentiment_points: list[dict[str, object]],
    timing_signals: list[dict[str, object]],
    calendar_dates: list[str],
    daily_bars: Mapping[str, list[dict[str, object]]],
    sealed_event_index: Mapping[tuple[str, str], dict[str, object]],
    prior_stock_flow_map: Mapping[str, Mapping[str, object]],
    *,
    limit: int = 5,
    replay_all_touches: bool = True,
    prior_trade_date_override: str | None = None,
    prior_sector_scores_override: Mapping[str, Mapping[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Choose candidates as their first limit-up touch becomes observable."""

    if limit <= 0:
        return []

    events_by_time: dict[str, list[dict[str, object]]] = defaultdict(list)
    for event in day_events:
        first_touch = normalize_limit_time(event.get("first_limit_time"))
        if first_touch is not None:
            events_by_time[first_touch].append(event)

    if replay_all_touches:
        observed_events: list[dict[str, object]] = []
        latest_ranked: list[dict[str, object]] = []
        entry_order_by_symbol: dict[str, int] = {}
        touch_rank_by_symbol: dict[str, int] = {}
        for first_touch in sorted(events_by_time):
            observed_events.extend(events_by_time[first_touch])
            latest_ranked = _rank_historical_day(
                observed_events,
                memberships,
                sector_flow_map,
                sector_scores,
                sentiment_points,
                timing_signals,
                calendar_dates,
                daily_bars,
                sealed_event_index,
                prior_stock_flow_map,
                prior_trade_date_override=prior_trade_date_override,
                prior_sector_scores_override=prior_sector_scores_override,
            )
            for candidate in latest_ranked:
                symbol = str(candidate.get("vt_symbol") or "")
                if symbol not in entry_order_by_symbol:
                    entry_order_by_symbol[symbol] = len(entry_order_by_symbol) + 1
                touch_rank_by_symbol.setdefault(
                    symbol,
                    int(candidate.get("market_dragon_rank") or 99),
                )
        return [
            {
                **candidate,
                "selection_order": entry_order_by_symbol.get(
                    str(candidate.get("vt_symbol") or "")
                ),
                "touch_market_dragon_rank": touch_rank_by_symbol.get(
                    str(candidate.get("vt_symbol") or "")
                ),
            }
            for candidate in latest_ranked[:limit]
        ]

    touch_times = sorted(events_by_time)
    observable_events = [
        event
        for first_touch in touch_times
        for event in events_by_time[first_touch]
    ]
    latest_ranked = _rank_historical_day(
        observable_events,
        memberships,
        sector_flow_map,
        sector_scores,
        sentiment_points,
        timing_signals,
        calendar_dates,
        daily_bars,
        sealed_event_index,
        prior_stock_flow_map,
        prior_trade_date_override=prior_trade_date_override,
        prior_sector_scores_override=prior_sector_scores_override,
    )
    if not latest_ranked:
        return []

    # Bulk backtests only trade the final Top5. Replaying every touch prefix
    # changes explanatory touch ranks, not that final set, and makes a
    # 252-day request quadratic. Keep exact prefix replay for the single-day
    # dashboard and derive an explicitly labelled visible-prefix proxy here.
    final_candidates = latest_ranked[:limit]
    final_time_by_symbol = {
        str(candidate.get("vt_symbol") or ""): normalize_limit_time(
            candidate.get("first_limit_time")
        )
        for candidate in latest_ranked
    }
    arrival_order = sorted(
        latest_ranked,
        key=lambda candidate: (
            final_time_by_symbol.get(str(candidate.get("vt_symbol") or "")) or "99:99:99",
            int(candidate.get("market_dragon_rank") or 99),
        ),
    )
    entry_order_by_symbol = {
        str(candidate.get("vt_symbol") or ""): index
        for index, candidate in enumerate(arrival_order, start=1)
    }
    touch_rank_by_symbol: dict[str, int] = {}
    for candidate in final_candidates:
        symbol = str(candidate.get("vt_symbol") or "")
        first_touch = final_time_by_symbol.get(symbol)
        if first_touch is None:
            continue
        visible = [
            row
            for row in latest_ranked
            if (final_time_by_symbol.get(str(row.get("vt_symbol") or "")) or "99:99:99")
            <= first_touch
        ]
        touch_rank_by_symbol[symbol] = next(
            (
                index
                for index, row in enumerate(visible, start=1)
                if str(row.get("vt_symbol") or "") == symbol
            ),
            int(candidate.get("market_dragon_rank") or 99),
        )

    result: list[dict[str, object]] = []
    for candidate in final_candidates:
        item = dict(candidate)
        symbol = str(item.get("vt_symbol") or "")
        item["selection_order"] = entry_order_by_symbol.get(
            symbol,
            int(item.get("market_dragon_rank") or 99),
        )
        item["touch_market_dragon_rank"] = touch_rank_by_symbol.get(
            symbol,
            int(item.get("market_dragon_rank") or 99),
        )
        item["touch_rank_mode"] = "final_score_visible_prefix_proxy"
        result.append(item)
    return result


def _proxy_order(
    candidate: Mapping[str, object],
    daily_bars: Mapping[str, list[dict[str, object]]],
) -> dict[str, object]:
    symbol = str(candidate["vt_symbol"])
    trade_date = str(candidate["trade_date"])
    previous_bar = _adjacent_bar(daily_bars.get(symbol, []), trade_date, direction=-1)
    entry_price = (
        main_board_limit_price(float(previous_bar["close_price"]))
        if previous_bar and previous_bar.get("close_price") is not None
        else None
    )
    return {
        "trade_date": trade_date,
        "vt_symbol": symbol,
        "name": candidate.get("name"),
        "sector_id": candidate.get("sector_id"),
        "sector_name": candidate.get("sector_name"),
        "industry_name": candidate.get("industry_name"),
        "core_industry_name": candidate.get("core_industry_name"),
        "sector_relevance": candidate.get("sector_relevance"),
        "observed_sector_member_touches": candidate.get("observed_sector_member_touches"),
        "market_dragon_rank": candidate.get("market_dragon_rank"),
        "sector_dragon_rank": candidate.get("sector_dragon_rank"),
        "dragon_score": candidate.get("dragon_score"),
        "score_components": candidate.get("score_components"),
        "signal_board_level": int(candidate.get("prior_streak") or 0) + 1,
        "first_limit_time": candidate.get("first_limit_time"),
        "open_times": candidate.get("open_times"),
        "is_sealed": candidate.get("is_sealed"),
        "entry_price": entry_price,
        "historical_sector_flow_date": candidate.get("historical_sector_flow_date"),
        "market_context": candidate.get("market_context"),
        "prior_sector_score": candidate.get("prior_sector_score"),
        "prior_sector_heat_score": candidate.get("prior_sector_heat_score"),
        "prior_sector_trend_state": candidate.get("prior_sector_trend_state"),
        "prior_sector_main_net_inflow": candidate.get("prior_sector_main_net_inflow"),
        "prior_sector_main_net_inflow_ratio": candidate.get("prior_sector_main_net_inflow_ratio"),
        "prior_stock_main_net_inflow": candidate.get("prior_stock_main_net_inflow"),
        "prior_stock_main_net_inflow_ratio": candidate.get("prior_stock_main_net_inflow_ratio"),
        "target_board_promotion_rate": candidate.get("target_board_promotion_rate"),
        "prior_stock": candidate.get("prior_stock"),
        "prior_stock_flow": candidate.get("prior_stock_flow"),
        "intraday": candidate.get("intraday"),
        "pretrade_gates": candidate.get("pretrade_gates"),
        "pretrade_gate_passed": candidate.get("pretrade_gate_passed"),
        "pretrade_data_confidence": candidate.get("pretrade_data_confidence"),
        "pretrade_supporting_factors": candidate.get("pretrade_supporting_factors"),
        "pretrade_risk_factors": candidate.get("pretrade_risk_factors"),
        "execution_trigger": candidate.get("execution_trigger", "first_reseal"),
        "direct_board_allowed": False,
        "conservative_status": event_fill_status(candidate, "conservative"),
        "optimistic_status": event_fill_status(candidate, "optimistic"),
        "strict_reseal_status": reseal_observation_status(candidate),
        "decision": candidate.get("decision"),
        "decision_reason": candidate.get("decision_reason"),
    }


def _proxy_trade(
    order: Mapping[str, object],
    candidate: Mapping[str, object],
    daily_bars: Mapping[str, list[dict[str, object]]],
    *,
    exit_mode: str,
    commission_rate: float,
    stamp_tax_rate: float,
    slippage_bps: float,
) -> dict[str, object] | None:
    entry_price = _number(order.get("entry_price"))
    if not entry_price:
        return None
    next_bar = _adjacent_bar(
        daily_bars.get(str(order["vt_symbol"]), []),
        str(order["trade_date"]),
        direction=1,
    )
    if not next_bar:
        return None
    exit_price = _number(next_bar.get("open_price" if exit_mode == "next_open" else "close_price"))
    if not exit_price:
        return None
    total_cost_rate = commission_rate * 2 + stamp_tax_rate + slippage_bps * 2 / 10_000
    return_pct = ((exit_price / entry_price - 1) - total_cost_rate) * 100
    signal_bar = _bar_for_date(
        daily_bars.get(str(order["vt_symbol"]), []),
        str(order["trade_date"]),
    )
    d1_analysis = _attach_d1_review_evidence(
        analyze_d1_outcome(
            signal_bar,
            next_bar,
            entry_price=entry_price,
            total_cost_rate=total_cost_rate,
            signal_was_sealed=bool(candidate.get("is_sealed")),
        ),
        candidate,
        order,
    )
    return {
        "signal_date": order["trade_date"],
        "exit_date": next_bar["trade_date"],
        "vt_symbol": order["vt_symbol"],
        "name": order.get("name"),
        "sector_name": order.get("sector_name"),
        "industry_name": order.get("industry_name"),
        "core_industry_name": order.get("core_industry_name"),
        "sector_relevance": order.get("sector_relevance"),
        "market_dragon_rank": order.get("market_dragon_rank"),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "return_pct": round(return_pct, 4),
        "result_mode": exit_mode,
        "d1_open_return_pct": _net_return_pct(
            entry_price,
            _number(next_bar.get("open_price")),
            total_cost_rate,
        ),
        "d1_high_return_pct": _net_return_pct(
            entry_price,
            _number(next_bar.get("high_price")),
            total_cost_rate,
        ),
        "d1_low_return_pct": _net_return_pct(
            entry_price,
            _number(next_bar.get("low_price")),
            total_cost_rate,
        ),
        "d1_close_return_pct": _net_return_pct(
            entry_price,
            _number(next_bar.get("close_price")),
            total_cost_rate,
        ),
        "is_sealed": bool(candidate.get("is_sealed")),
        "strict_reseal_status": order.get("strict_reseal_status"),
        "first_limit_time": candidate.get("first_limit_time"),
        "open_times": candidate.get("open_times"),
        "signal_board_level": int(candidate.get("prior_streak") or 0) + 1,
        "dragon_score": candidate.get("dragon_score"),
        "score_components": candidate.get("score_components"),
        "market_context": candidate.get("market_context"),
        "prior_sector_score": candidate.get("prior_sector_score"),
        "prior_sector_heat_score": candidate.get("prior_sector_heat_score"),
        "prior_sector_trend_state": candidate.get("prior_sector_trend_state"),
        "target_board_promotion_rate": candidate.get("target_board_promotion_rate"),
        "prior_stock": candidate.get("prior_stock"),
        "intraday": candidate.get("intraday"),
        "close_review": candidate.get("close_review"),
        "turnover_rate": candidate.get("turnover_rate"),
        "prior_sector_main_net_inflow": candidate.get("prior_sector_main_net_inflow"),
        "prior_sector_main_net_inflow_ratio": candidate.get("prior_sector_main_net_inflow_ratio"),
        "prior_stock_main_net_inflow": candidate.get("prior_stock_main_net_inflow"),
        "prior_stock_main_net_inflow_ratio": candidate.get("prior_stock_main_net_inflow_ratio"),
        "prior_stock_flow": candidate.get("prior_stock_flow"),
        "pretrade_gates": candidate.get("pretrade_gates"),
        "pretrade_gate_passed": candidate.get("pretrade_gate_passed"),
        "pretrade_data_confidence": candidate.get("pretrade_data_confidence"),
        "seal_to_turnover_ratio": _ratio(
            _number(candidate.get("seal_amount")), _number(candidate.get("turnover"))
        ),
        "final_status": "sealed" if bool(candidate.get("is_sealed")) else "failed",
        "d1_analysis": d1_analysis,
    }


def _net_return_pct(entry_price: float, price: float | None, total_cost_rate: float) -> float | None:
    if not price:
        return None
    return round(((price / entry_price - 1) - total_cost_rate) * 100, 4)


def _scenario_payload(
    orders: list[dict[str, object]],
    trades: list[dict[str, object]],
    scenario: str,
    *,
    trade_dates: list[str],
) -> dict[str, object]:
    status_key = f"{scenario}_status"
    filled_orders = [order for order in orders if str(order[status_key]).startswith("filled_")]
    sealed_filled_orders = sum(1 for order in filled_orders if bool(order.get("is_sealed")))
    summary = summarize_proxy_trades(trades)
    daily_results = _daily_result_ledger(orders, trades, status_key, trade_dates)
    equity = _equity_rows(daily_results)
    trade_compound_return = summary.get("total_return_pct")
    summary.update(
        {
            "order_count": len(orders),
            "filled_order_count": len(filled_orders),
            "fill_rate": round(len(filled_orders) / len(orders) * 100, 4) if orders else None,
            "seal_success_rate": round(sealed_filled_orders / len(filled_orders) * 100, 4) if filled_orders else None,
            "trade_compound_return_pct": trade_compound_return,
            "total_return_pct": equity[-1]["total_return_pct"] if equity else 0.0,
            "max_drawdown_pct": _max_drawdown_pct(equity),
            "trade_day_count": len(daily_results),
            "closed_trade_day_count": sum(1 for row in daily_results if row["closed_trade_count"]),
        }
    )
    return {
        "summary": summary,
        "equity": equity,
        "daily_results": daily_results,
        "trades": sorted(trades, key=lambda item: (str(item["signal_date"]), int(item["market_dragon_rank"] or 99))),
        "outcome_summary": _outcome_summary(trades),
        "factor_buckets": _factor_buckets(trades),
        "factor_contrasts": _factor_contrasts(trades),
    }


def _research_plan_backtest(
    orders: list[dict[str, object]],
    conservative_trades: list[dict[str, object]],
    trade_dates: list[str],
) -> dict[str, object]:
    orders_by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    for order in orders:
        orders_by_date[str(order.get("trade_date") or "")].append(order)

    selected_orders: list[dict[str, object]] = []
    daily_policies: list[dict[str, object]] = []
    for trade_date in trade_dates:
        day_orders = orders_by_date.get(trade_date, [])
        market_context = day_orders[0].get("market_context") if day_orders else {}
        plan = build_daily_research_plan(
            day_orders,
            market_context if isinstance(market_context, Mapping) else {},
        )
        plan_orders = [dict(item) for item in plan.pop("plans")]
        selected_orders.extend(plan_orders)
        daily_policies.append(
            {
                "trade_date": trade_date,
                **plan,
                "plan_symbols": [str(item.get("vt_symbol") or "") for item in plan_orders],
            }
        )

    selected_keys = {
        (str(order.get("trade_date") or ""), str(order.get("vt_symbol") or ""))
        for order in selected_orders
    }
    selected_trades = [
        trade
        for trade in conservative_trades
        if (str(trade.get("signal_date") or ""), str(trade.get("vt_symbol") or ""))
        in selected_keys
    ]
    scenario = _scenario_payload(
        selected_orders,
        [],
        "strict_reseal",
        trade_dates=trade_dates,
    )
    scenario["summary"].update(
        {
            "plan_days": sum(1 for row in daily_policies if row["plan_symbols"]),
            "no_trade_days": sum(1 for row in daily_policies if not row["plan_symbols"]),
        }
    )
    return {
        "selection_stage": "D_FIRST_TOUCH",
        "entry_trigger": "first_reseal",
        "verification_status": "blocked_by_missing_reseal_queue_data",
        "verification_reason": "炸板池没有最后封板时间，且全样本没有历史队列穿透证据；严格回封计划不生成伪成交。",
        "daily_policies": daily_policies,
        "orders": selected_orders,
        "scenario": scenario,
        "observational_first_open": {
            "warning": "以下仅是所选候选触板后开板成交代理，不等于回封策略可成交收益。",
            "summary": summarize_proxy_trades(selected_trades),
            "trades": selected_trades,
        },
    }


def _daily_result_ledger(
    orders: list[dict[str, object]],
    trades: list[dict[str, object]],
    status_key: str,
    trade_dates: list[str],
) -> list[dict[str, object]]:
    orders_by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    trades_by_date: dict[str, list[dict[str, object]]] = defaultdict(list)
    for order in orders:
        orders_by_date[str(order["trade_date"])].append(order)
    for trade in trades:
        trades_by_date[str(trade["signal_date"])].append(trade)

    equity = 1.0
    peak = 1.0
    rows: list[dict[str, object]] = []
    for trade_date in sorted(set(trade_dates) | set(orders_by_date)):
        day_orders = orders_by_date.get(trade_date, [])
        filled_orders = [
            order
            for order in day_orders
            if str(order.get(status_key) or "").startswith("filled_")
        ]
        day_trades = trades_by_date.get(trade_date, [])
        returns = [float(trade["return_pct"]) for trade in day_trades]
        daily_return = sum(returns) / len(returns) if returns else 0.0
        if returns:
            equity *= 1 + daily_return / 100
        peak = max(peak, equity)
        result_dates = sorted({str(trade["exit_date"]) for trade in day_trades if trade.get("exit_date")})
        if day_trades:
            result_status = "closed"
        elif filled_orders:
            result_status = "awaiting_d1_bar"
        elif day_orders:
            result_status = "not_filled"
        else:
            result_status = "no_candidate"
        rows.append(
            {
                "trade_date": trade_date,
                "result_date": result_dates[0] if len(result_dates) == 1 else None,
                "result_status": result_status,
                "order_count": len(day_orders),
                "filled_order_count": len(filled_orders),
                "closed_trade_count": len(day_trades),
                "win_count": sum(1 for value in returns if value > 0),
                "win_rate": round(sum(1 for value in returns if value > 0) / len(returns) * 100, 4) if returns else None,
                "daily_return_pct": round(daily_return, 4),
                "equity": round(equity, 6),
                "total_return_pct": round((equity - 1) * 100, 4),
                "drawdown_pct": round((equity / peak - 1) * 100, 4),
            }
        )
    return rows


def _equity_rows(daily_results: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "trade_date": row["trade_date"],
            "daily_return_pct": row["daily_return_pct"],
            "equity": row["equity"],
            "total_return_pct": row["total_return_pct"],
            "drawdown_pct": row["drawdown_pct"],
        }
        for row in daily_results
    ]


def _max_drawdown_pct(equity_rows: list[dict[str, object]]) -> float | None:
    if not equity_rows:
        return None
    peak = 1.0
    max_drawdown = 0.0
    for row in equity_rows:
        equity = float(row["equity"])
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, (equity / peak - 1) * 100)
    return round(max_drawdown, 4)


def _dashboard_sector_rows(
    sector_events: list[dict[str, object]],
    top_dragons: list[dict[str, object]],
    prior_sector_flow_map: Mapping[str, Mapping[str, object]],
    prior_sector_score_map: Mapping[str, Mapping[str, object]],
    close_sector_flow_map: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    dragons_by_sector: dict[str, list[dict[str, object]]] = defaultdict(list)
    for dragon in top_dragons:
        dragons_by_sector[str(dragon["sector_id"])].append(dragon)
    events_by_sector: dict[str, list[dict[str, object]]] = defaultdict(list)
    for event in sector_events:
        events_by_sector[str(event["sector_id"])].append(event)
    rows = []
    for sector_id, events in events_by_sector.items():
        prior_flow = prior_sector_flow_map.get(sector_id, {})
        close_flow = close_sector_flow_map.get(sector_id, {})
        score = prior_sector_score_map.get(sector_id, {})
        dragons = dragons_by_sector.get(sector_id, [])
        rows.append(
            {
                "sector_id": sector_id,
                "sector_name": events[0].get("sector_name"),
                "prior_heat_score": score.get("heat_score"),
                "prior_trend_state": score.get("trend_state"),
                "prior_main_net_inflow": prior_flow.get("main_net_inflow"),
                "prior_main_net_inflow_ratio": prior_flow.get("main_net_inflow_ratio"),
                "close_main_net_inflow": close_flow.get("main_net_inflow"),
                "close_main_net_inflow_ratio": close_flow.get("main_net_inflow_ratio"),
                "main_net_inflow": prior_flow.get("main_net_inflow"),
                "main_net_inflow_ratio": prior_flow.get("main_net_inflow_ratio"),
                "touched_count": len(events),
                "sealed_count": sum(
                    1
                    for event in events
                    if bool(event.get("is_sealed"))
                ),
                "failed_count": sum(
                    1
                    for event in events
                    if not bool(event.get("is_sealed"))
                ),
                "dragon_symbols": [str(item["vt_symbol"]) for item in dragons],
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            _number(row.get("prior_heat_score")) or 0.0,
            _number(row.get("prior_main_net_inflow")) or 0.0,
        ),
        reverse=True,
    )[:10]


def _membership_map(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        sector_name = str(row.get("sector_name") or "")
        if _is_trade_theme(sector_name):
            result[str(row.get("vt_symbol") or "")].append(row)
    return result


def _select_event_sector(
    event: Mapping[str, object],
    memberships: Mapping[str, list[dict[str, object]]],
    sector_flow_map: Mapping[str, Mapping[str, object]],
    sector_score_map: Mapping[str, Mapping[str, object]] | None = None,
    observed_sector_counts: Mapping[str, int] | None = None,
) -> dict[str, object] | None:
    choices = memberships.get(str(event.get("vt_symbol") or ""), [])
    if not choices:
        return None
    counts = observed_sector_counts or {}
    industry_name = str(event.get("industry_name") or "").strip()
    resonant_themes = [
        row
        for row in choices
        if str(row.get("sector_type") or "") in {"theme", "concept"}
        and int(counts.get(str(row.get("sector_id") or ""), 0)) >= 2
        and _sector_is_actionable(
            (sector_score_map or {}).get(str(row.get("sector_id") or ""), {})
        )
    ]
    exact_industries = [
        row
        for row in choices
        if str(row.get("sector_type") or "") == "industry"
        and _industry_matches(industry_name, str(row.get("sector_name") or ""))
    ]
    industries = [row for row in choices if str(row.get("sector_type") or "") == "industry"]
    if resonant_themes:
        pool = resonant_themes
        relevance = "intraday_theme_resonance"
    elif exact_industries:
        pool = exact_industries
        relevance = "provider_core_industry"
    elif industries:
        pool = industries
        relevance = "industry_fallback"
    else:
        pool = choices
        relevance = "unverified_theme_fallback"
    selected = max(pool, key=lambda row: _sector_choice_key(row, counts, sector_score_map or {}, sector_flow_map))
    sector_id = str(selected.get("sector_id") or "")
    return {
        "sector_id": sector_id,
        "sector_name": str(selected.get("sector_name") or ""),
        "core_industry_name": industry_name or None,
        "sector_relevance": relevance,
        "observed_sector_member_touches": int(counts.get(sector_id, 0)),
    }


def _observed_sector_membership_counts(
    events: list[dict[str, object]],
    memberships: Mapping[str, list[dict[str, object]]],
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for event in events:
        if not is_eligible_main_board(
            str(event.get("vt_symbol") or ""), str(event.get("name") or "")
        ):
            continue
        seen: set[str] = set()
        for row in memberships.get(str(event.get("vt_symbol") or ""), []):
            sector_id = str(row.get("sector_id") or "")
            if sector_id and sector_id not in seen:
                counts[sector_id] += 1
                seen.add(sector_id)
    return counts


def _sector_choice_key(
    row: Mapping[str, object],
    observed_counts: Mapping[str, int],
    sector_score_map: Mapping[str, Mapping[str, object]],
    sector_flow_map: Mapping[str, Mapping[str, object]],
) -> tuple[int, float, float, int, str]:
    sector_id = str(row.get("sector_id") or "")
    return (
        int(observed_counts.get(sector_id, 0)),
        _number(sector_score_map.get(sector_id, {}).get("heat_score")) or float("-inf"),
        _number(sector_flow_map.get(sector_id, {}).get("main_net_inflow")) or float("-inf"),
        -int(row.get("rank") or 9999),
        sector_id,
    )


def _sector_is_actionable(score: Mapping[str, object]) -> bool:
    heat = _number(score.get("heat_score"))
    sentiment = _number(score.get("sentiment_score"))
    trend = str(score.get("trend_state") or "")
    return bool(
        heat is not None
        and heat >= 60
        and (sentiment is None or sentiment >= 45)
        and trend in {"MAINLINE_UP", "FAST_UP", "ROTATION"}
    )


def _industry_matches(provider_name: str, membership_name: str) -> bool:
    left = provider_name.replace("Ⅱ", "").replace("Ⅲ", "").strip()
    right = membership_name.replace("Ⅱ", "").replace("Ⅲ", "").strip()
    return bool(left and right and (left == right or left in right or right in left))


def _sector_flow_map(
    rows: list[dict[str, object]],
    trade_date: str | None,
) -> dict[str, dict[str, object]]:
    if not trade_date:
        return {}
    return {
        str(row["sector_id"]): row
        for row in rows
        if _normalized_date(row.get("trade_date")) == trade_date and row.get("sector_id")
    }


def _sector_flow_date_index(
    rows: list[dict[str, object]],
) -> dict[str, dict[str, dict[str, object]]]:
    result: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        trade_date = _normalized_date(row.get("trade_date"))
        sector_id = str(row.get("sector_id") or "")
        if trade_date and sector_id:
            result[trade_date][sector_id] = row
    return dict(result)


def _stock_flow_map(
    rows: list[dict[str, object]],
    trade_date: str,
) -> dict[str, dict[str, object]]:
    return {
        str(row["vt_symbol"]): row
        for row in rows
        if _normalized_date(row.get("trade_date")) == trade_date and row.get("vt_symbol")
    }


def _stock_flow_date_index(
    rows: list[dict[str, object]],
) -> dict[str, dict[str, dict[str, object]]]:
    result: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        trade_date = _normalized_date(row.get("trade_date"))
        symbol = str(row.get("vt_symbol") or "")
        if trade_date and symbol:
            result[trade_date][symbol] = row
    return dict(result)


def _latest_indexed_date(
    dates: list[str],
    target: str,
    *,
    strict_before: bool,
) -> str | None:
    index = bisect_left(dates, target)
    if not strict_before and index < len(dates) and dates[index] == target:
        return dates[index]
    index -= 1
    return dates[index] if index >= 0 else None


def _sector_scores_for_date(
    rows: Mapping[tuple[str, str], Mapping[str, object]],
    trade_date: str | None,
) -> dict[str, dict[str, object]]:
    if trade_date is None:
        return {}
    return {
        sector_id: dict(row)
        for (score_date, sector_id), row in rows.items()
        if score_date == trade_date
    }


def _sentiment_for_date(
    rows: list[dict[str, object]],
    trade_date: str,
) -> dict[str, object] | None:
    return next(
        (row for row in rows if _normalized_date(row.get("date")) == trade_date),
        None,
    )


def _daily_bar_index(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        result[str(row.get("vt_symbol") or "")].append(row)
    for symbol_rows in result.values():
        symbol_rows.sort(key=lambda row: str(row.get("trade_date") or ""))
    return result


def _prior_limit_streak(
    bars: list[dict[str, object]],
    trade_date: str,
) -> int:
    position = _sorted_service_bar_index(bars, trade_date)
    if position is None:
        return 0
    index = position - 1
    streak = 0
    while index >= 0:
        change = _number(bars[index].get("change_pct"))
        if change is None or change < 9.5:
            break
        streak += 1
        index -= 1
    return streak


def _adjacent_bar(
    bars: list[dict[str, object]],
    trade_date: str,
    *,
    direction: int,
) -> dict[str, object] | None:
    index = _sorted_service_bar_index(bars, trade_date)
    if index is None:
        return None
    target = index + direction
    return bars[target] if 0 <= target < len(bars) else None


def _bar_for_date(bars: list[dict[str, object]], trade_date: str) -> dict[str, object] | None:
    index = _sorted_service_bar_index(bars, trade_date)
    return bars[index] if index is not None else None


def _sorted_service_bar_index(
    bars: list[dict[str, object]],
    trade_date: str,
) -> int | None:
    index = bisect_left(
        bars,
        trade_date,
        key=lambda row: str(row.get("trade_date") or ""),
    )
    if index >= len(bars) or str(bars[index].get("trade_date") or "") != trade_date:
        return None
    return index


def _latest_row_date(
    rows: list[dict[str, object]],
    target: str,
    *,
    strict_before: bool,
) -> str | None:
    dates = sorted(
        {
            normalized
            for row in rows
            if (normalized := _normalized_date(row.get("trade_date")))
            and (normalized < target if strict_before else normalized <= target)
        }
    )
    return dates[-1] if dates else None


def _seal_strength(event: Mapping[str, object]) -> float:
    first_touch = _first_touch_score(event.get("first_limit_time"))
    stability = max(0.0, 1.0 - int(event.get("open_times") or 0) * 0.2)
    queue_ratio = _ratio(_number(event.get("seal_amount")), _number(event.get("float_market_cap")))
    queue_score = min((queue_ratio or 0.0) / 0.02, 1.0)
    return 0.3 * first_touch + 0.3 * stability + 0.4 * queue_score


def _first_touch_score(value: object) -> float:
    time_text = normalize_limit_time(value)
    if time_text is None:
        return 0.0
    if time_text <= "10:00:00":
        return 1.0
    if time_text <= "11:30:00":
        return 0.8
    if time_text <= "14:00:00":
        return 0.55
    return 0.3


def _turnover_quality(turnover_rate: float | None) -> float:
    if turnover_rate is None:
        return 0.0
    if 5 <= turnover_rate <= 20:
        return 1.0
    if 2 <= turnover_rate < 5 or 20 < turnover_rate <= 30:
        return 0.6
    return 0.2


def _attach_d1_review_evidence(
    analysis: dict[str, object],
    candidate: Mapping[str, object],
    order: Mapping[str, object],
) -> dict[str, object]:
    """Separate pre-trade evidence, D-close review, and the D+1 label."""

    pretrade_support = _factor_rows(candidate.get("pretrade_supporting_factors"))
    pretrade_risks = _factor_rows(candidate.get("pretrade_risk_factors"))
    close_support: list[dict[str, str]] = []
    close_risks: list[dict[str, str]] = []
    board_level = int(order.get("signal_board_level") or 1)
    market_rank = int(order.get("market_dragon_rank") or 99)
    prior_sector_flow = _number(candidate.get("prior_sector_main_net_inflow"))
    turnover_rate = _number(candidate.get("turnover_rate"))
    seal_ratio = _ratio(_number(candidate.get("seal_amount")), _number(candidate.get("turnover")))
    open_times = int(candidate.get("open_times") or 0)
    first_touch = normalize_limit_time(candidate.get("first_limit_time"))
    close_review = candidate.get("close_review")
    close_review = close_review if isinstance(close_review, Mapping) else {}
    timing_direction = _nested_value(candidate, "market_context", "timing", "active_direction")

    if not pretrade_support and market_rank <= 2:
        pretrade_support.append({"code": "market_front_row", "label": "市场前排", "detail": f"当时龙{market_rank}"})
    if board_level >= 3:
        pretrade_risks.append({"code": "high_board_exhaustion", "label": "高位接力", "detail": _board_level_bucket(board_level)})
    if prior_sector_flow is not None:
        evidence = {
            "code": "prior_sector_inflow" if prior_sector_flow > 0 else "prior_sector_outflow",
            "label": "D-1板块资金",
            "detail": f"{prior_sector_flow / 100_000_000:+.2f}亿",
        }
        (pretrade_support if prior_sector_flow > 0 else pretrade_risks).append(evidence)
    if timing_direction:
        evidence = {
            "code": "timing_gold" if timing_direction == "GOLD" else "timing_silver",
            "label": "已确认金银手指",
            "detail": "金手指" if timing_direction == "GOLD" else "银手指",
        }
        (pretrade_support if timing_direction == "GOLD" else pretrade_risks).append(evidence)
    if turnover_rate is not None:
        evidence = {
            "code": "turnover_moderate" if 5 <= turnover_rate <= 20 else "turnover_extreme",
            "label": "D日换手",
            "detail": f"{turnover_rate:.2f}%",
        }
        (close_support if 5 <= turnover_rate <= 20 else close_risks).append(evidence)
    if bool(candidate.get("is_sealed")):
        close_support.append({"code": "final_sealed", "label": "D日最终封住", "detail": "盘后复盘字段"})
    else:
        close_risks.append({"code": "final_failed", "label": "D日最终炸板", "detail": "盘后复盘字段"})
    if open_times >= 2:
        close_risks.append({"code": "repeated_open", "label": "反复开板", "detail": f"开板{open_times}次"})
    elif open_times == 1:
        close_support.append({"code": "reseal", "label": "换手回封", "detail": "开板1次后回封"})
    if seal_ratio is not None:
        evidence = {
            "code": "seal_ratio_strong" if seal_ratio >= 0.05 else "seal_ratio_weak",
            "label": "D日封单 / 成交",
            "detail": f"{seal_ratio * 100:.2f}%",
        }
        (close_support if seal_ratio >= 0.05 else close_risks).append(evidence)
    stock_flow_ratio = _number(close_review.get("stock_main_net_inflow_ratio"))
    stock_flow_amount = _number(close_review.get("stock_main_net_inflow"))
    if stock_flow_ratio is not None or stock_flow_amount is not None:
        positive = (stock_flow_ratio or 0.0) > 0 or (stock_flow_amount or 0.0) > 0
        detail = f"{stock_flow_ratio:+.2f}%" if stock_flow_ratio is not None else f"{stock_flow_amount / 100_000_000:+.2f}亿"
        evidence = {
            "code": "stock_flow_in" if positive else "stock_flow_out",
            "label": "D日个股主力资金",
            "detail": detail,
        }
        (close_support if positive else close_risks).append(evidence)
    sector_flow_ratio = _number(close_review.get("sector_main_net_inflow_ratio"))
    sector_flow_amount = _number(close_review.get("sector_main_net_inflow"))
    if sector_flow_ratio is not None or sector_flow_amount is not None:
        positive = (sector_flow_ratio or 0.0) > 0 or (sector_flow_amount or 0.0) > 0
        detail = f"{sector_flow_ratio:+.2f}%" if sector_flow_ratio is not None else f"{sector_flow_amount / 100_000_000:+.2f}亿"
        evidence = {
            "code": "sector_flow_in" if positive else "sector_flow_out",
            "label": "D日板块主力资金",
            "detail": detail,
        }
        (close_support if positive else close_risks).append(evidence)
    relative_turnover = _number(close_review.get("d_turnover_ratio_5d"))
    if relative_turnover is not None:
        evidence = {
            "code": "relative_turnover_normal" if 0.7 <= relative_turnover <= 2 else "relative_turnover_extreme",
            "label": "D日相对成交额",
            "detail": f"{relative_turnover:.2f}x",
        }
        (close_support if 0.7 <= relative_turnover <= 2 else close_risks).append(evidence)
    if first_touch and first_touch >= "14:00:00":
        pretrade_risks.append({"code": "late_touch", "label": "午后触板", "detail": first_touch})

    supporting = _dedupe_factor_rows([*pretrade_support, *close_support])
    risks = _dedupe_factor_rows([*pretrade_risks, *close_risks])
    outcome_code = str(analysis.get("outcome_code") or "awaiting_d1_bar")

    return {
        **analysis,
        "pretrade_supporting_factors": _dedupe_factor_rows(pretrade_support)[:8],
        "pretrade_risk_factors": _dedupe_factor_rows(pretrade_risks)[:8],
        "close_supporting_factors": _dedupe_factor_rows(close_support)[:8],
        "close_risk_factors": _dedupe_factor_rows(close_risks)[:8],
        "supporting_factors": supporting[:10],
        "risk_factors": risks[:10],
        "diagnosis_summary": _diagnosis_summary(outcome_code, supporting, risks),
        "review_note": "前置字段只使用D-1收盘和D日首次触板时可见信息；封单、最终开板次数、D日资金和最终封板仅用于盘后归因，D+1字段只作为结果。这里展示相关证据，不断言主力意图或单一因果。",
    }


def _attach_dashboard_decision(candidate: dict[str, object]) -> None:
    board_level = int(candidate.get("signal_board_level") or int(candidate.get("prior_streak") or 0) + 1)
    score = float(candidate.get("dragon_score") or 0.0)
    market_context = candidate.get("market_context")
    market_context = market_context if isinstance(market_context, Mapping) else {}
    sentiment = market_context.get("sentiment")
    sentiment = sentiment if isinstance(sentiment, Mapping) else {}
    prior_sector_score = candidate.get("prior_sector_score")
    prior_sector_score = prior_sector_score if isinstance(prior_sector_score, Mapping) else {}
    first_touch = normalize_limit_time(candidate.get("first_limit_time"))
    pretrade_support: list[dict[str, str]] = []
    pretrade_risks: list[dict[str, str]] = []

    if int(candidate.get("market_dragon_rank") or 99) <= 2:
        pretrade_support.append({"code": "market_front", "label": "市场前排", "detail": f"龙{candidate.get('market_dragon_rank')}"})
    for gate in candidate.get("pretrade_gates") or []:
        if not isinstance(gate, Mapping):
            continue
        evidence = {
            "code": f"gate_{gate.get('code')}",
            "label": str(gate.get("label") or "准入检查"),
            "detail": str(gate.get("detail") or "--"),
        }
        target = pretrade_support if gate.get("status") == "pass" else pretrade_risks
        target.append(evidence)
    promotion = _number(candidate.get("target_board_promotion_rate"))
    if promotion is not None:
        target = pretrade_support if promotion >= 0.25 else pretrade_risks
        target.append({"code": "board_promotion", "label": "D-1对应板型成功率", "detail": f"{promotion * 100:.1f}%"})
    stock_flow = _number(candidate.get("prior_stock_main_net_inflow"))
    stock_flow_ratio = _number(candidate.get("prior_stock_main_net_inflow_ratio"))
    if stock_flow is not None or stock_flow_ratio is not None:
        positive = (stock_flow or 0.0) > 0 or (stock_flow_ratio or 0.0) > 0
        detail = f"{stock_flow_ratio:+.2f}%" if stock_flow_ratio is not None else f"{stock_flow / 100_000_000:+.2f}亿"
        target = pretrade_support if positive else pretrade_risks
        target.append({"code": "prior_stock_flow", "label": "D-1个股资金", "detail": detail})
    if first_touch and first_touch <= "09:31:00":
        pretrade_risks.append({"code": "fast_board", "label": "秒板排队", "detail": "只等开板回封"})
    phase_label = str(sentiment.get("phase_label") or "数据缺失")
    phase_target = pretrade_risks if str(sentiment.get("phase") or "") in {"ice", "ebb"} else pretrade_support
    phase_target.append({"code": "sentiment", "label": "D-1情绪", "detail": phase_label})

    if board_level >= 3:
        candidate["decision"] = "watch"
        candidate["decision_reason"] = "high_board_requires_l2"
    elif not sentiment or not prior_sector_score:
        candidate["decision"] = "watch"
        candidate["decision_reason"] = "pretrade_context_incomplete"
    elif not bool(candidate.get("pretrade_gate_passed")):
        candidate["decision"] = "blocked"
        candidate["decision_reason"] = _first_failed_gate_reason(candidate.get("pretrade_gates"))
    elif first_touch and first_touch <= "09:31:00":
        candidate["decision"] = "watch"
        candidate["decision_reason"] = "fast_board_wait_reseal"
    elif score >= 65:
        candidate["decision"] = "eligible"
        candidate["decision_reason"] = "pretrade_multifactor_pass"
    else:
        candidate["decision"] = "watch"
        candidate["decision_reason"] = "pretrade_score_below_threshold"
    candidate["execution_trigger"] = "first_reseal"
    candidate["direct_board_allowed"] = False
    candidate["pretrade_supporting_factors"] = _dedupe_factor_rows(pretrade_support)[:8]
    candidate["pretrade_risk_factors"] = _dedupe_factor_rows(pretrade_risks)[:8]


def _first_failed_gate_reason(value: object) -> str:
    reason_by_code = {
        "market_phase": "market_phase_blocked",
        "sector_hot": "sector_not_hot",
        "sector_flow": "sector_fund_not_positive",
        "sector_confirmation": "sector_resonance_missing",
        "board_level": "high_board_requires_l2",
    }
    if isinstance(value, list):
        for gate in value:
            if isinstance(gate, Mapping) and gate.get("status") == "fail":
                return reason_by_code.get(str(gate.get("code") or ""), "pretrade_gate_failed")
    return "pretrade_gate_failed"


def _factor_rows(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {
            "code": str(item.get("code") or ""),
            "label": str(item.get("label") or ""),
            "detail": str(item.get("detail") or ""),
        }
        for item in value
        if isinstance(item, Mapping)
    ]


def _dedupe_factor_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("code") or row.get("label") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _diagnosis_summary(
    outcome_code: str,
    supporting: list[dict[str, str]],
    risks: list[dict[str, str]],
) -> str:
    positive = "、".join(row["label"] for row in supporting[:3]) or "正向证据不足"
    negative = "、".join(row["label"] for row in risks[:3]) or "显著风险证据不足"
    if outcome_code in {"continuation_limit_up", "next_limit_up_after_failed_board"}:
        return f"与D+1涨停同时出现的主要证据：{positive}；仍需注意：{negative}。"
    if outcome_code == "close_premium":
        return f"D+1收盘保住溢价，伴随证据：{positive}；未形成连板的风险侧证据：{negative}。"
    if outcome_code in {"direct_breakdown", "low_open_weak"}:
        return f"D+1低开走弱/闷杀，D日前后同时出现的风险证据：{negative}；可观察承接：{positive}。"
    if outcome_code in {"high_open_dump", "rush_and_fall", "intraday_premium_lost"}:
        return f"D+1曾有溢价但未守住，风险证据：{negative}；盘前与D日承接证据：{positive}。"
    return f"当前结果证据不足；可观察承接：{positive}；可观察风险：{negative}。"


def _attach_replay_display_scores(
    candidate: dict[str, object],
    sector_flow_map: Mapping[str, Mapping[str, object]],
    stock_flow_map: Mapping[str, Mapping[str, object]],
    daily_bars: Mapping[str, list[dict[str, object]]],
) -> None:
    sector_flow = sector_flow_map.get(str(candidate.get("sector_id") or ""), {})
    stock_flow = stock_flow_map.get(str(candidate.get("vt_symbol") or ""), {})
    close_features = close_stock_features(
        daily_bars.get(str(candidate.get("vt_symbol") or ""), []),
        str(candidate.get("trade_date") or ""),
        assume_sorted=True,
    )
    candidate["close_sector_main_net_inflow"] = _number(sector_flow.get("main_net_inflow"))
    candidate["close_sector_main_net_inflow_ratio"] = _number(
        sector_flow.get("main_net_inflow_ratio")
    )
    candidate["sector_main_net_inflow"] = candidate["close_sector_main_net_inflow"]
    candidate["stock_main_net_inflow"] = _number(stock_flow.get("main_net_inflow"))
    candidate["stock_main_net_inflow_ratio"] = _number(stock_flow.get("main_net_inflow_ratio"))
    candidate["sector_flow_percentile"] = candidate.get("sector_flow_percentile", 0.0)
    candidate["stock_flow_percentile"] = 0.0
    candidate["position_score"] = round(min(int(candidate.get("prior_streak") or 0) + 1, 3) / 3, 4)
    candidate["seal_strength_score"] = round(_seal_strength(candidate), 4)
    candidate["turnover_quality_score"] = _turnover_quality(_number(candidate.get("turnover_rate")))
    candidate["seal_to_float_market_cap_ratio"] = _ratio(
        _number(candidate.get("seal_amount")), _number(candidate.get("float_market_cap"))
    )
    candidate["seal_to_turnover_ratio"] = _ratio(
        _number(candidate.get("seal_amount")), _number(candidate.get("turnover"))
    )
    candidate["close_review"] = {
        "data_cutoff": "D_CLOSE",
        "available_at": "D日收盘后",
        "final_status": "sealed" if bool(candidate.get("is_sealed")) else "failed",
        "open_times": int(candidate.get("open_times") or 0),
        "seal_amount": _number(candidate.get("seal_amount")),
        "seal_to_turnover_ratio": candidate["seal_to_turnover_ratio"],
        "seal_to_float_market_cap_ratio": candidate["seal_to_float_market_cap_ratio"],
        "turnover_rate": _number(candidate.get("turnover_rate")),
        "stock_main_net_inflow": candidate["stock_main_net_inflow"],
        "stock_main_net_inflow_ratio": candidate["stock_main_net_inflow_ratio"],
        "sector_main_net_inflow": candidate["close_sector_main_net_inflow"],
        "sector_main_net_inflow_ratio": candidate["close_sector_main_net_inflow_ratio"],
        **close_features,
    }


def _historical_outcome(
    candidate: Mapping[str, object],
    daily_bars: Mapping[str, list[dict[str, object]]],
) -> dict[str, object]:
    order = _proxy_order(candidate, daily_bars)
    next_open = _proxy_trade(
        order,
        candidate,
        daily_bars,
        exit_mode="next_open",
        commission_rate=0.0003,
        stamp_tax_rate=0.0005,
        slippage_bps=10.0,
    )
    next_close = _proxy_trade(
        order,
        candidate,
        daily_bars,
        exit_mode="next_close",
        commission_rate=0.0003,
        stamp_tax_rate=0.0005,
        slippage_bps=10.0,
    )
    return {
        "final_status": "sealed" if bool(candidate.get("is_sealed")) else "failed",
        "conservative_status": order["conservative_status"],
        "optimistic_status": order["optimistic_status"],
        "strict_reseal_status": order["strict_reseal_status"],
        "entry_price": order.get("entry_price"),
        "exit_date": (next_open or next_close or {}).get("exit_date"),
        "next_open_return_pct": (next_open or {}).get("return_pct"),
        "next_close_return_pct": (next_close or {}).get("return_pct"),
        "d1_analysis": (next_open or next_close or {}).get(
            "d1_analysis",
            analyze_d1_outcome(None, None, entry_price=_number(order.get("entry_price"))),
        ),
    }


def _factor_buckets(trades: list[dict[str, object]]) -> list[dict[str, object]]:
    factors = {
        "market_rank": lambda trade: "龙1-2" if int(trade.get("market_dragon_rank") or 99) <= 2 else "龙3-5",
        "board_level": lambda trade: _board_level_bucket(int(trade.get("signal_board_level") or 1)),
        "first_touch_time": lambda trade: _first_touch_bucket(trade.get("first_limit_time")),
        "market_phase": _market_phase_bucket,
        "sentiment_score": _sentiment_score_bucket,
        "promotion_rate": _promotion_rate_bucket,
        "target_board_promotion": _target_promotion_bucket,
        "gold_silver_state": _timing_state_bucket,
        "prior_sector_heat": _sector_heat_bucket,
        "prior_sector_trend": _sector_trend_bucket,
        "intraday_sector_expansion": _sector_expansion_bucket,
        "prior_relative_turnover": _prior_relative_turnover_bucket,
        "prior_stock_flow": _prior_stock_flow_bucket,
        "open_times": lambda trade: _open_times_bucket(int(trade.get("open_times") or 0)),
        "prior_sector_flow": lambda trade: _prior_sector_flow_bucket(
            _number(trade.get("prior_sector_main_net_inflow"))
        ),
        "final_board_status": lambda trade: "最终封住" if trade.get("final_status") == "sealed" else "最终炸板",
        "seal_to_turnover": lambda trade: _seal_to_turnover_bucket(
            _number(trade.get("seal_to_turnover_ratio"))
        ),
        "turnover_quality": lambda trade: _turnover_bucket(_number(trade.get("turnover_rate"))),
        "d_stock_flow": _stock_flow_bucket,
        "d_relative_turnover": _d_relative_turnover_bucket,
    }
    review_only_factors = {
        "open_times",
        "final_board_status",
        "seal_to_turnover",
        "turnover_quality",
        "d_stock_flow",
        "d_relative_turnover",
    }
    rows: list[dict[str, object]] = []
    for factor, bucket_fn in factors.items():
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for trade in trades:
            grouped[bucket_fn(trade)].append(trade)
        for bucket, bucket_trades in grouped.items():
            summary = summarize_proxy_trades(bucket_trades)
            rows.append(
                {
                    "factor": factor,
                    "bucket": bucket,
                    "trade_count": summary["trade_count"],
                    "win_rate": summary["win_rate"],
                    "average_return_pct": summary["average_return_pct"],
                    "total_return_pct": summary["total_return_pct"],
                    "availability": "D_CLOSE_REVIEW" if factor in review_only_factors else "PRETRADE",
                    "sample_status": "usable" if len(bucket_trades) >= 5 else "insufficient",
                }
            )
    return rows


def _factor_contrasts(trades: list[dict[str, object]]) -> list[dict[str, object]]:
    definitions = [
        ("dragon_score", "综合前置分", "PRETRADE", "score", lambda row: _number(row.get("dragon_score"))),
        ("sentiment_score", "D-1情绪分", "PRETRADE", "score", lambda row: _nested_number(row, "market_context", "sentiment", "score")),
        ("promotion_rate", "D-1整体晋级率", "PRETRADE", "pct", lambda row: _scale_pct(_nested_number(row, "market_context", "sentiment", "promotion_rate"))),
        ("target_board_promotion", "D-1对应板位晋级率", "PRETRADE", "pct", lambda row: _scale_pct(_number(row.get("target_board_promotion_rate")))),
        ("sector_heat", "D-1板块热度", "PRETRADE", "score", lambda row: _number(row.get("prior_sector_heat_score"))),
        ("sector_flow_amount", "D-1板块净流入", "PRETRADE", "amount_yi", lambda row: _amount_yi(_number(row.get("prior_sector_main_net_inflow")))),
        ("sector_flow_ratio", "D-1板块净流入占比", "PRETRADE", "pct", lambda row: _number(row.get("prior_sector_main_net_inflow_ratio"))),
        ("stock_flow_amount", "D-1个股净流入", "PRETRADE", "amount_yi", lambda row: _amount_yi(_number(row.get("prior_stock_main_net_inflow")))),
        ("stock_flow_ratio", "D-1个股净流入占比", "PRETRADE", "pct", lambda row: _number(row.get("prior_stock_main_net_inflow_ratio"))),
        ("sector_expansion", "触板时板块扩散数", "PRETRADE", "count", lambda row: _nested_number(row, "intraday", "observed_sector_touch_count")),
        ("prior_turnover_ratio", "D-1相对成交额", "PRETRADE", "ratio", lambda row: _nested_number(row, "prior_stock", "prior_turnover_ratio_5d")),
        ("prior_turnover_rate", "D-1换手率", "PRETRADE", "pct", lambda row: _nested_number(row, "prior_stock", "prior_turnover_rate")),
        ("pretrade_confidence", "买入前数据完整度", "PRETRADE", "pct", lambda row: _scale_pct(_number(row.get("pretrade_data_confidence")))),
        ("open_times", "D日开板次数", "D_CLOSE_REVIEW", "count", lambda row: _number(row.get("open_times"))),
        ("seal_to_turnover", "D日封单/成交", "D_CLOSE_REVIEW", "pct", lambda row: _scale_pct(_number(row.get("seal_to_turnover_ratio")))),
        ("stock_flow_ratio", "D日个股主力净占比", "D_CLOSE_REVIEW", "pct", lambda row: _nested_number(row, "close_review", "stock_main_net_inflow_ratio")),
        ("d_turnover_ratio", "D日相对成交额", "D_CLOSE_REVIEW", "ratio", lambda row: _nested_number(row, "close_review", "d_turnover_ratio_5d")),
    ]
    rows: list[dict[str, object]] = []
    for key, label, availability, unit, getter in definitions:
        winner_values = [value for trade in trades if _number(trade.get("return_pct")) is not None and float(trade["return_pct"]) > 0 and (value := getter(trade)) is not None]
        loser_values = [value for trade in trades if _number(trade.get("return_pct")) is not None and float(trade["return_pct"]) <= 0 and (value := getter(trade)) is not None]
        values = winner_values + loser_values
        winner_average = mean(winner_values) if winner_values else None
        loser_average = mean(loser_values) if loser_values else None
        rows.append(
            {
                "factor": key,
                "label": label,
                "availability": availability,
                "unit": unit,
                "coverage_count": len(values),
                "trade_count": len(trades),
                "winner_count": len(winner_values),
                "loser_count": len(loser_values),
                "winner_average": round(winner_average, 4) if winner_average is not None else None,
                "loser_average": round(loser_average, 4) if loser_average is not None else None,
                "winner_minus_loser": (
                    round(winner_average - loser_average, 4)
                    if winner_average is not None and loser_average is not None
                    else None
                ),
                "sample_status": "usable" if len(values) >= 10 else "insufficient",
            }
        )
    return rows


def _outcome_summary(trades: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    labels: dict[str, str] = {}
    for trade in trades:
        analysis = trade.get("d1_analysis")
        if not isinstance(analysis, Mapping):
            continue
        code = str(analysis.get("outcome_code") or "awaiting_d1_bar")
        grouped[code].append(trade)
        labels[code] = str(analysis.get("outcome_label") or code)

    rows: list[dict[str, object]] = []
    for code, group in grouped.items():
        summary = summarize_proxy_trades(group)
        rows.append(
            {
                "outcome_code": code,
                "outcome_label": labels.get(code, code),
                "trade_count": summary["trade_count"],
                "win_rate": summary["win_rate"],
                "average_return_pct": summary["average_return_pct"],
                "total_return_pct": summary["total_return_pct"],
                "sample_status": "usable" if len(group) >= 5 else "insufficient",
            }
        )
    return sorted(rows, key=lambda item: (-int(item["trade_count"]), str(item["outcome_code"])))


def _board_level_bucket(level: int) -> str:
    return {1: "首板", 2: "一进二", 3: "二进三"}.get(level, "三板以上")


def _first_touch_bucket(value: object) -> str:
    time_text = normalize_limit_time(value)
    if time_text is None:
        return "时间缺失"
    if time_text <= "09:31:00":
        return "09:31前"
    if time_text <= "10:00:00":
        return "09:31-10:00"
    if time_text <= "11:30:00":
        return "10:00-11:30"
    return "午后"


def _market_phase_bucket(trade: Mapping[str, object]) -> str:
    label = _nested_value(trade, "market_context", "sentiment", "phase_label")
    return str(label or "情绪缺失")


def _sentiment_score_bucket(trade: Mapping[str, object]) -> str:
    value = _nested_number(trade, "market_context", "sentiment", "score")
    if value is None:
        return "情绪分缺失"
    if value >= 65:
        return "强(>=65)"
    if value >= 50:
        return "中(50-65)"
    if value >= 35:
        return "弱(35-50)"
    return "极弱(<35)"


def _promotion_rate_bucket(trade: Mapping[str, object]) -> str:
    return _rate_bucket(
        _nested_number(trade, "market_context", "sentiment", "promotion_rate"),
        "晋级率",
    )


def _target_promotion_bucket(trade: Mapping[str, object]) -> str:
    return _rate_bucket(_number(trade.get("target_board_promotion_rate")), "板位晋级")


def _rate_bucket(value: float | None, label: str) -> str:
    if value is None:
        return f"{label}缺失"
    if value >= 0.30:
        return "高(>=30%)"
    if value >= 0.20:
        return "中(20%-30%)"
    if value >= 0.12:
        return "低(12%-20%)"
    return "极低(<12%)"


def _timing_state_bucket(trade: Mapping[str, object]) -> str:
    timing = _nested_value(trade, "market_context", "timing")
    if not isinstance(timing, Mapping):
        return "金银手指缺失"
    latest = timing.get("latest_candidate")
    if isinstance(latest, Mapping) and latest.get("as_of_status") == "PENDING":
        return f"{latest.get('direction', 'UNKNOWN')}候选待确认"
    state = str(timing.get("signal_state") or "NONE")
    return {
        "GOLD_ACTIVE": "金手指有效(<=5日)",
        "SILVER_ACTIVE": "银手指有效(<=5日)",
        "GOLD_FADING": "金手指衰减(6-10日)",
        "SILVER_FADING": "银手指衰减(6-10日)",
        "STALE": "金银手指已过期",
        "NONE": "无已确认信号",
    }.get(state, state)


def _sector_heat_bucket(trade: Mapping[str, object]) -> str:
    value = _number(trade.get("prior_sector_heat_score"))
    if value is None:
        return "热度缺失"
    if value >= 75:
        return "主线热度(>=75)"
    if value >= 60:
        return "活跃(60-75)"
    if value >= 45:
        return "轮动(45-60)"
    return "冷(<45)"


def _sector_trend_bucket(trade: Mapping[str, object]) -> str:
    return str(trade.get("prior_sector_trend_state") or "趋势缺失")


def _sector_expansion_bucket(trade: Mapping[str, object]) -> str:
    count = int(_nested_number(trade, "intraday", "observed_sector_touch_count") or 0)
    if count >= 3:
        return "涨停潮(>=3只)"
    if count == 2:
        return "板块共振(2只)"
    if count == 1:
        return "单兵触板"
    return "扩散缺失"


def _prior_relative_turnover_bucket(trade: Mapping[str, object]) -> str:
    value = _nested_number(trade, "prior_stock", "prior_turnover_ratio_5d")
    if value is None:
        return "前量缺失"
    if value >= 2:
        return "前日巨量(>=2x)"
    if value >= 1.2:
        return "前日放量(1.2-2x)"
    if value >= 0.7:
        return "前日常量(0.7-1.2x)"
    return "前日缩量(<0.7x)"


def _prior_stock_flow_bucket(trade: Mapping[str, object]) -> str:
    ratio = _number(trade.get("prior_stock_main_net_inflow_ratio"))
    amount = _number(trade.get("prior_stock_main_net_inflow"))
    if ratio is None and amount is None:
        return "D-1个股资金缺失"
    if (ratio is not None and ratio >= 10) or (amount is not None and amount >= 100_000_000):
        return "D-1个股强流入"
    if (ratio or 0.0) > 0 or (amount or 0.0) > 0:
        return "D-1个股净流入"
    return "D-1个股净流出"


def _open_times_bucket(open_times: int) -> str:
    if open_times <= 0:
        return "未开板"
    if open_times == 1:
        return "开板1次"
    return "开板2次以上"


def _prior_sector_flow_bucket(value: float | None) -> str:
    if value is None:
        return "资金缺失"
    if value > 0:
        return "前日净流入"
    if value < 0:
        return "前日净流出"
    return "前日持平"


def _seal_to_turnover_bucket(value: float | None) -> str:
    if value is None:
        return "封单缺失"
    if value >= 0.05:
        return "封单强(>=5%)"
    if value >= 0.01:
        return "封单中等(1%-5%)"
    return "封单弱(<1%)"


def _turnover_bucket(value: float | None) -> str:
    if value is None:
        return "换手缺失"
    if value < 5:
        return "低换手(<5%)"
    if value <= 20:
        return "中等换手(5%-20%)"
    if value <= 30:
        return "高换手(20%-30%)"
    return "极高换手(>30%)"


def _stock_flow_bucket(trade: Mapping[str, object]) -> str:
    value = _nested_number(trade, "close_review", "stock_main_net_inflow_ratio")
    if value is None:
        return "个股资金缺失"
    if value >= 10:
        return "强流入(>=10%)"
    if value > 0:
        return "净流入(0%-10%)"
    return "净流出"


def _d_relative_turnover_bucket(trade: Mapping[str, object]) -> str:
    value = _nested_number(trade, "close_review", "d_turnover_ratio_5d")
    if value is None:
        return "当日量能缺失"
    if value >= 2:
        return "巨量(>=2x)"
    if value >= 1.2:
        return "放量(1.2-2x)"
    if value >= 0.7:
        return "常量(0.7-1.2x)"
    return "缩量(<0.7x)"


def _dashboard_limitations(flow_date: str | None) -> list[str]:
    return [
        "当前为盘后快照，封单金额和炸板次数是日终字段，不代表盘中实时决策。",
        "炸板池没有最后封板时间，不能从日终事件证明盘中曾完成回封。",
        "概念成员使用当前快照，尚未具备完整历史版本。",
        f"板块资金使用最近可用日期 {flow_date or '无'}。",
        "没有 Tick/L2 队列数据，页面不声称秒板能够成交。",
    ]


def _feature_availability() -> list[dict[str, object]]:
    return [
        {
            "stage": "D-1_CLOSE",
            "label": "买入前可见",
            "fields": [
                "情绪周期与情绪分",
                "首板封板率及分板位晋级率",
                "按交易日衰减的金银手指与待确认候选",
                "板块20日热度/趋势/持续性/龙头分",
                "前一交易日板块资金",
                "个股前日资金、换手和相对成交额",
            ],
            "used_for_selection": True,
        },
        {
            "stage": "D_FIRST_TOUCH",
            "label": "首次触板时可见",
            "fields": ["首次触板时间", "首板/一进二/二进三", "当时板块触板扩散", "市场龙/板块龙排名"],
            "used_for_selection": True,
        },
        {
            "stage": "D_CLOSE_REVIEW",
            "label": "仅盘后归因",
            "fields": ["最终封板/炸板", "最终封单金额及比例", "最终开板次数", "D日个股/板块资金", "D日换手与相对成交额"],
            "used_for_selection": False,
        },
        {
            "stage": "D+1_OUTCOME",
            "label": "仅结果标签",
            "fields": ["开盘/最高/最低/收盘收益", "连板", "收盘溢价", "冲高回落", "低开闷杀"],
            "used_for_selection": False,
        },
    ]


def _backtest_limitations(event_days: int) -> list[str]:
    return [
        f"日终涨停/炸板事件覆盖 {event_days} 个交易日，仍不等于逐笔盘口成交证据。",
        "批量回测的触板时龙排名使用最终同口径分数在当时已触板集合中的排序代理；单日工作台保留逐触板重放。",
        "历史排序使用前一可用板块资金，不能代表盘中实时资金流。",
        "概念成员使用当前快照，存在历史成员偏差。",
        "保守基线只把触板后开板视为限价单可能成交的代理，不等于回封成交。",
        "炸板池没有最后封板时间，严格回封计划因缺少回封路径和队列数据不生成成交收益。",
        "没有 Tick/L2 队列数据，早盘秒板和队列未知订单不会计入保守收益。",
    ]


def _available_event_dates(
    events: list[dict[str, object]],
    trading_dates: set[str],
) -> list[str]:
    return sorted(
        {
            str(event["trade_date"])
            for event in events
            if event.get("trade_date")
            and str(event["trade_date"]) in trading_dates
            and is_eligible_main_board(
                str(event.get("vt_symbol") or ""), str(event.get("name") or "")
            )
        }
    )


def _trading_date_set(dataset: Mapping[str, object]) -> set[str]:
    return {
        normalized
        for row in _dict_rows(dataset.get("daily_bars"))
        if (normalized := _normalized_date(row.get("trade_date")))
    }


def _date_navigation(dates: list[str], selected_date: str | None) -> dict[str, str | None]:
    previous = max((item for item in dates if selected_date and item < selected_date), default=None)
    next_date = min((item for item in dates if selected_date and item > selected_date), default=None)
    return {"previous": previous, "next": next_date}


def _empty_dashboard(
    dataset: Mapping[str, object],
    *,
    trade_date: str | None = None,
    available_dates: list[str] | None = None,
    navigation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "status": "empty",
        "mode": "historical_event_replay",
        "trade_date": trade_date,
        "available_dates": available_dates or [],
        "navigation": dict(navigation or {"previous": None, "next": None}),
        "summary": {},
        "top_sectors": [],
        "top_dragons": [],
        "pretrade_market": None,
        "close_sentiment": None,
        "research_plan": build_daily_research_plan([], {}),
        "coverage": dict(dataset.get("coverage") or {}),
        "feature_availability": _feature_availability(),
        "data_sources": [],
        "limitations": ["本地尚无涨停/炸板事件。"],
    }


def _empty_backtest(dataset: Mapping[str, object], exit_mode: str) -> dict[str, object]:
    empty_scenario = {
        "summary": summarize_proxy_trades([]),
        "equity": [],
        "daily_results": [],
        "trades": [],
        "outcome_summary": [],
        "factor_buckets": [],
        "factor_contrasts": [],
    }
    return {
        "status": "insufficient_data",
        "mode": "historical_event_proxy",
        "exit_mode": exit_mode,
        "orders": [],
        "scenarios": {
            "conservative": dict(empty_scenario),
            "optimistic": dict(empty_scenario),
        },
        "research_plan": {
            "selection_stage": "D_FIRST_TOUCH",
            "entry_trigger": "first_reseal",
            "daily_policies": [],
            "orders": [],
            "scenario": dict(empty_scenario),
        },
        "coverage": dict(dataset.get("coverage") or {}),
        "feature_availability": _feature_availability(),
        "limitations": ["当前范围内没有可回测的主板涨停/炸板事件。"],
    }


def _is_trade_theme(name: str) -> bool:
    normalized = str(name or "").strip()
    return bool(normalized) and not any(keyword in normalized for keyword in _STATUS_THEME_KEYWORDS)


def _dict_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _normalized_date(value: object) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10] if len(text) >= 10 else None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    return round(numerator / denominator, 6) if numerator is not None and denominator else None


def _nested_value(row: Mapping[str, object], *keys: str) -> object:
    value: object = row
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _nested_number(row: Mapping[str, object], *keys: str) -> float | None:
    return _number(_nested_value(row, *keys))


def _scale_pct(value: float | None) -> float | None:
    return round(value * 100, 4) if value is not None else None


def _amount_yi(value: float | None) -> float | None:
    return round(value / 100_000_000, 4) if value is not None else None


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
