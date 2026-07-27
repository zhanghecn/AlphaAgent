"""Reverse-research causal rescue factors on days where A+B made no trade."""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from math import isfinite, log1p
from pathlib import Path

import pandas as pd

from alphaagent.server.services.limit_up import cash_backtest
from alphaagent.server.services.limit_up.capital_mainline_evaluation import (
    monthly_summaries,
    performance_summary,
)
from alphaagent.server.services.limit_up.quality_opportunity_reverse import (
    HIGH_RETURN_PCT,
    build_opportunity_reverse_frame,
)


STUDY_VERSION = "limit-up-quality-no-trade-reverse-v1"
RULE_VERSION = "no-trade-capital-diffusion-rescue-v1"
CAUSAL_RULE_VERSION = "no-prior-ab-capital-diffusion-rescue-v2"
DISCOVERY_END = date(2026, 2, 28)
HISTORICAL_VALIDATION_START = date(2026, 3, 1)
MINIMUM_INDUSTRY_TURNOVER_RATIO_5D = 1.0
MAXIMUM_STOCK_GENE_COMBINED_WIN_RATE = 30.0
MINIMUM_CONCEPT_PRIOR_SEALED_COUNT = 2
MAXIMUM_CONCEPT_PRIOR_SEALED_COUNT = 4
MINIMUM_CONCEPT_PRIOR_MAX_BOARD = 2


def attach_intraday_concept_diffusion_proxy(
    frame: pd.DataFrame,
    limit_up_events: Sequence[Mapping[str, object]],
    membership_contexts: Mapping[date, object],
) -> pd.DataFrame:
    """Attach signal-time concept breadth using the membership known for each date."""

    if frame.empty:
        return frame.copy()
    event_index: dict[tuple[date, str], list[dict[str, object]]] = defaultdict(list)
    event_time_count = 0
    for raw_event in limit_up_events:
        trade_date = _as_date(raw_event.get("trade_date"))
        symbol = str(raw_event.get("vt_symbol") or "").upper()
        first_limit_time = _time_text(raw_event.get("first_limit_time"))
        context = membership_contexts.get(trade_date) if trade_date else None
        if (
            trade_date is None
            or not symbol
            or first_limit_time is None
            or not _event_is_sealed(raw_event)
            or context is None
        ):
            continue
        event_time_count += 1
        for sector_id in _context_sector_ids(context, symbol):
            event_index[(trade_date, sector_id)].append(
                {
                    **dict(raw_event),
                    "vt_symbol": symbol,
                    "first_limit_time": first_limit_time,
                }
            )
    for events in event_index.values():
        events.sort(
            key=lambda row: (
                str(row.get("first_limit_time") or ""),
                str(row.get("vt_symbol") or ""),
            )
        )

    records: list[dict[str, object]] = []
    for candidate in frame.to_dict("records"):
        trade_date = _as_date(candidate.get("trade_date"))
        symbol = str(candidate.get("vt_symbol") or "").upper()
        signal_time = _time_text(candidate.get("signal_time"))
        context = membership_contexts.get(trade_date) if trade_date else None
        sector_ids = _context_sector_ids(context, symbol) if context else ()
        choices: list[dict[str, object]] = []
        if trade_date is not None and signal_time is not None and context is not None:
            for sector_id in sector_ids:
                prior_events = [
                    event
                    for event in event_index.get((trade_date, sector_id), ())
                    if str(event.get("vt_symbol") or "") != symbol
                    and str(event.get("first_limit_time") or "") <= signal_time
                ]
                if not prior_events:
                    continue
                member_count = _context_member_count(context, sector_id)
                if member_count <= 0:
                    continue
                sealed_count = len(prior_events)
                density = sealed_count / member_count
                maximum_board = max(_event_board(event) for event in prior_events)
                choices.append(
                    {
                        "sector_id": sector_id,
                        "sector_name": _context_sector_name(context, sector_id),
                        "prior_sealed_count": sealed_count,
                        "prior_max_board": maximum_board,
                        "member_count": member_count,
                        "density": density,
                        "score": density * log1p(sealed_count),
                    }
                )
        selected = max(
            choices,
            key=lambda row: (
                float(row["score"]),
                int(row["prior_max_board"]),
                -int(row["member_count"]),
                str(row["sector_id"]),
            ),
            default=None,
        )
        evidence_level = _context_evidence_level(context)
        records.append(
            {
                **candidate,
                "intraday_concept_feature_ready": selected is not None,
                "intraday_concept_membership_ready": bool(sector_ids),
                "intraday_concept_membership_evidence_level": evidence_level,
                "intraday_concept_membership_snapshot_date": getattr(
                    context, "snapshot_date", None
                ),
                "intraday_concept_id": (
                    selected.get("sector_id") if selected else None
                ),
                "intraday_concept_name": (
                    selected.get("sector_name") if selected else None
                ),
                "intraday_concept_prior_sealed_count": (
                    selected.get("prior_sealed_count") if selected else 0
                ),
                "intraday_concept_candidate_rank": (
                    int(selected["prior_sealed_count"]) + 1 if selected else 1
                ),
                "intraday_concept_prior_max_board": (
                    selected.get("prior_max_board") if selected else 0
                ),
                "intraday_concept_member_count": (
                    selected.get("member_count") if selected else None
                ),
                "intraday_concept_diffusion_density": (
                    selected.get("density") if selected else None
                ),
                "intraday_concept_diffusion_score": (
                    selected.get("score") if selected else None
                ),
                "intraday_limit_event_time_evidence_count": event_time_count,
            }
        )
    return pd.DataFrame.from_records(records).sort_values(
        ["trade_date", "signal_time", "vt_symbol"], kind="stable"
    ).reset_index(drop=True)


def no_ab_trade_day_mask(frame: pd.DataFrame) -> pd.Series:
    """Return candidates on dates where no row passed the formal A+B gate."""

    selected = _boolean_series(frame, "selected_ab")
    dates = frame.get("trade_date", pd.Series(index=frame.index, dtype=object))
    selected_by_date = selected.groupby(dates).transform("max")
    return ~selected_by_date.fillna(False).astype(bool)


def no_prior_ab_trade_mask(frame: pd.DataFrame) -> pd.Series:
    """Return excluded rows observed before the first A+B signal of each day."""

    selected = _boolean_series(frame, "selected_ab")
    signal_times = _string_series(frame, "signal_time")
    dates = frame.get("trade_date", pd.Series(index=frame.index, dtype=object))
    first_ab_time_by_date = (
        signal_times.loc[selected].groupby(dates.loc[selected]).min().to_dict()
    )
    first_ab_times = dates.map(first_ab_time_by_date)
    before_first_ab = pd.Series(True, index=frame.index, dtype=bool)
    known_first_ab = first_ab_times.notna()
    before_first_ab.loc[known_first_ab] = (
        signal_times.loc[known_first_ab]
        < first_ab_times.loc[known_first_ab].astype(str)
    )
    return ~selected & before_first_ab


def no_trade_reverse_rule_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Return frozen rescue components without consulting D+1 outcomes."""

    return _reverse_rule_masks(frame, no_ab_trade_day_mask(frame))


def causal_reverse_rule_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Return the same factors with a signal-time observable A+B condition."""

    return _reverse_rule_masks(
        frame,
        no_prior_ab_trade_mask(frame),
        broad_rise_industry_requires_pullback=True,
    )


def _reverse_rule_masks(
    frame: pd.DataFrame,
    eligible_pool: pd.Series,
    *,
    broad_rise_industry_requires_pullback: bool = False,
) -> dict[str, pd.Series]:
    first_touch = _string_series(frame, "signal_kind").eq("first_touch")
    market_phase = _string_series(frame, "prior_market_phase")
    mixed = market_phase.eq("mixed")
    not_broad_rise = ~market_phase.eq("broad_rise")
    five_day_pullback = _numeric_series(frame, "prior_return_5d_pct").le(0)
    sample_insufficient = _string_series(frame, "core_quality_gate_reason").eq(
        "same_stock_d1_samples_below_5"
    )
    industry_expanding = _numeric_series(
        frame, "prior_industry_turnover_ratio_5d"
    ).ge(MINIMUM_INDUSTRY_TURNOVER_RATIO_5D)
    weak_stock_gene = _numeric_series(
        frame, "stock_gene_combined_win_rate"
    ).lt(MAXIMUM_STOCK_GENE_COMBINED_WIN_RATE)
    early_concept_diffusion = _numeric_series(
        frame, "intraday_concept_prior_sealed_count"
    ).between(
        MINIMUM_CONCEPT_PRIOR_SEALED_COUNT,
        MAXIMUM_CONCEPT_PRIOR_SEALED_COUNT,
    ) & _numeric_series(frame, "intraday_concept_prior_max_board").ge(
        MINIMUM_CONCEPT_PRIOR_MAX_BOARD
    )

    static_mixed_pullback = (
        eligible_pool
        & sample_insufficient
        & first_touch
        & mixed
        & five_day_pullback
    )
    industry_market_allowed = (
        ~market_phase.eq("broad_rise") | five_day_pullback
        if broad_rise_industry_requires_pullback
        else pd.Series(True, index=frame.index, dtype=bool)
    )
    static_industry_override = (
        eligible_pool
        & industry_expanding
        & weak_stock_gene
        & industry_market_allowed
    )
    concept_mixed_first_touch = (
        eligible_pool & early_concept_diffusion & first_touch & mixed
    )
    concept_pullback_diffusion = (
        eligible_pool
        & early_concept_diffusion
        & not_broad_rise
        & five_day_pullback
    )
    static_rescue = static_mixed_pullback | static_industry_override
    concept_rescue = concept_mixed_first_touch | concept_pullback_diffusion
    return {
        "no_ab_trade_day_pool": eligible_pool,
        "static_mixed_pullback": static_mixed_pullback,
        "static_industry_override": static_industry_override,
        "static_rescue": static_rescue,
        "concept_mixed_first_touch": concept_mixed_first_touch,
        "concept_pullback_diffusion": concept_pullback_diffusion,
        "concept_rescue": concept_rescue,
        "final_rescue": static_rescue | concept_rescue,
    }


def select_causal_reverse_signals(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the first causal rescue per day and leave later capacity to A+B."""

    if frame.empty:
        return frame.copy()
    mask = causal_reverse_rule_masks(frame)["final_rescue"]
    return (
        frame.loc[mask]
        .sort_values(
            ["trade_date", "signal_time", "pool_rank", "vt_symbol"],
            kind="stable",
        )
        .groupby("trade_date", sort=False)
        .head(1)
        .copy()
    )


def evaluate_causal_reverse(frame: pd.DataFrame) -> dict[str, object]:
    """Evaluate the executable no-A+B-yet variant against the frozen rule."""

    if frame.empty:
        return {}
    masks = causal_reverse_rule_masks(frame)
    baseline = frame.loc[_boolean_series(frame, "selected_ab")]
    incremental = select_causal_reverse_signals(frame)
    combined = pd.concat([baseline, incremental], ignore_index=True)
    incremental_dates = pd.to_datetime(incremental["trade_date"]).dt.date
    discovery = incremental.loc[incremental_dates.le(DISCOVERY_END)]
    historical_validation = incremental.loc[
        incremental_dates.ge(HISTORICAL_VALIDATION_START)
    ]
    return {
        "rule_version": CAUSAL_RULE_VERSION,
        "pool": performance_summary(
            frame.loc[masks["no_ab_trade_day_pool"]], baseline_count=len(frame)
        ),
        "incremental": performance_summary(incremental, baseline_count=len(frame)),
        "incremental_trade_days": int(incremental["trade_date"].nunique()),
        "incremental_monthly": monthly_summaries(incremental),
        "incremental_discovery": performance_summary(
            discovery,
            baseline_count=len(frame),
        ),
        "incremental_historical_validation": performance_summary(
            historical_validation,
            baseline_count=len(frame),
        ),
        "combined": performance_summary(combined, baseline_count=len(frame)),
        "combined_trade_days": int(combined["trade_date"].nunique()),
    }


def evaluate_no_trade_reverse(frame: pd.DataFrame) -> dict[str, object]:
    """Evaluate the no-trade pool, frozen factors and historical time split."""

    if frame.empty:
        return {}
    masks = no_trade_reverse_rule_masks(frame)
    no_trade_pool = frame.loc[masks["no_ab_trade_day_pool"]]
    baseline = frame.loc[_boolean_series(frame, "selected_ab")]
    high = no_trade_pool.loc[_numeric_series(no_trade_pool, "return_pct").ge(
        HIGH_RETURN_PCT
    )]
    high_dates = set(high["trade_date"])
    factors: dict[str, object] = {}
    for name in (
        "static_mixed_pullback",
        "static_industry_override",
        "static_rescue",
        "concept_mixed_first_touch",
        "concept_pullback_diffusion",
        "concept_rescue",
        "final_rescue",
    ):
        selected = frame.loc[masks[name]]
        discovery = selected.loc[
            pd.to_datetime(selected["trade_date"]).dt.date.le(DISCOVERY_END)
        ]
        historical_validation = selected.loc[
            pd.to_datetime(selected["trade_date"])
            .dt.date.ge(HISTORICAL_VALIDATION_START)
        ]
        factors[name] = {
            "full": performance_summary(selected, baseline_count=len(no_trade_pool)),
            "discovery": performance_summary(
                discovery, baseline_count=len(no_trade_pool)
            ),
            "historical_validation": performance_summary(
                historical_validation, baseline_count=len(no_trade_pool)
            ),
            "monthly": monthly_summaries(selected),
            "trade_days": int(selected["trade_date"].nunique()),
            "high_return_day_recall": len(set(selected["trade_date"]) & high_dates),
            "high_return_count": int(
                _numeric_series(selected, "return_pct").ge(HIGH_RETURN_PCT).sum()
            ),
            "loss_count": int(
                _numeric_series(selected, "return_pct").le(0).sum()
            ),
            "loss_days": int(
                selected.loc[
                    _numeric_series(selected, "return_pct").le(0), "trade_date"
                ].nunique()
            ),
        }
    final = frame.loc[masks["final_rescue"]]
    combined = pd.concat([baseline, final], ignore_index=True)
    return {
        "study_version": STUDY_VERSION,
        "rule_version": RULE_VERSION,
        "status": "historical_proxy_pass_forward_unconfirmed",
        "coverage": {
            "closed_candidate_count": len(frame),
            "candidate_trade_days": int(frame["trade_date"].nunique()),
            "ab_trade_count": len(baseline),
            "ab_trade_days": int(baseline["trade_date"].nunique()),
            "no_ab_trade_day_candidate_count": len(no_trade_pool),
            "no_ab_trade_days": int(no_trade_pool["trade_date"].nunique()),
            "no_trade_high_return_count": len(high),
            "no_trade_high_return_days": len(high_dates),
            "concept_membership_ready_count": int(
                _boolean_series(no_trade_pool, "intraday_concept_membership_ready").sum()
            ),
            "concept_feature_ready_count": int(
                _boolean_series(no_trade_pool, "intraday_concept_feature_ready").sum()
            ),
            "membership_evidence_counts": _value_counts(
                no_trade_pool, "intraday_concept_membership_evidence_level"
            ),
        },
        "outcome_groups": _outcome_group_summaries(no_trade_pool),
        "outcome_feature_medians": _outcome_feature_medians(no_trade_pool),
        "concept_rank_groups": _concept_rank_group_summaries(no_trade_pool),
        "gate_failure_groups": _group_performance(
            no_trade_pool, "core_quality_gate_reason"
        ),
        "baseline": performance_summary(baseline, baseline_count=len(frame)),
        "factors": factors,
        "combined": performance_summary(combined, baseline_count=len(frame)),
        "combined_trade_days": int(combined["trade_date"].nunique()),
    }


def evaluate_reverse_cash_accounts(
    frame: pd.DataFrame,
    official_daily_bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date | str],
) -> dict[str, object]:
    """Replay baseline and proposed signals in strict one/two-position accounts."""

    masks = no_trade_reverse_rule_masks(frame)
    variants = {
        "baseline_ab": _boolean_series(frame, "selected_ab"),
        "proposed": _boolean_series(frame, "selected_ab") | masks["final_rescue"],
    }
    result: dict[str, object] = {}
    for name, mask in variants.items():
        signals = frame.loc[mask].sort_values(
            ["trade_date", "signal_time", "pool_rank", "vt_symbol"],
            kind="stable",
        )
        result[name] = {}
        for positions in (1, 2):
            account = cash_backtest.simulate_limit_up_account(
                signals.to_dict("records"),
                official_daily_bars,
                trade_dates,
                "next_close",
                cash_backtest.CashBacktestConfig(
                    initial_cash=100_000,
                    max_positions=positions,
                ),
            )
            result[name][str(positions)] = account["execution_summary"]
    return result


def evaluate_causal_reverse_cash_accounts(
    frame: pd.DataFrame,
    official_daily_bars: Sequence[Mapping[str, object]],
    trade_dates: Sequence[date | str],
) -> dict[str, object]:
    """Replay the executable no-A+B-yet variant in strict cash accounts."""

    rescue = select_causal_reverse_signals(frame)
    proposed = _boolean_series(frame, "selected_ab") | frame.index.isin(rescue.index)
    signals = frame.loc[proposed].sort_values(
        ["trade_date", "signal_time", "pool_rank", "vt_symbol"],
        kind="stable",
    )
    result: dict[str, object] = {}
    for positions in (1, 2):
        account = cash_backtest.simulate_limit_up_account(
            signals.to_dict("records"),
            official_daily_bars,
            trade_dates,
            "next_close",
            cash_backtest.CashBacktestConfig(
                initial_cash=100_000,
                max_positions=positions,
            ),
        )
        result[str(positions)] = account["execution_summary"]
    return result


def render_no_trade_reverse_report(
    frame: pd.DataFrame,
    evaluation: Mapping[str, object],
    cash_accounts: Mapping[str, object],
    causal_evaluation: Mapping[str, object],
    causal_cash_accounts: Mapping[str, object],
) -> str:
    """Render post-hoc discovery separately from the executable causal rule."""

    coverage = _mapping(evaluation.get("coverage"))
    factors = _mapping(evaluation.get("factors"))
    baseline = _mapping(evaluation.get("baseline"))
    combined = _mapping(evaluation.get("combined"))
    final = _mapping(factors.get("final_rescue"))
    final_full = _mapping(final.get("full"))
    causal = _mapping(causal_evaluation)
    causal_incremental = _mapping(causal.get("incremental"))
    causal_combined = _mapping(causal.get("combined"))
    causal_discovery = _mapping(causal.get("incremental_discovery"))
    causal_validation = _mapping(causal.get("incremental_historical_validation"))
    causal_accounts = _mapping(causal_cash_accounts)
    lines = [
        "# A+B 空仓日高溢价逆向特征与复利修复",
        "",
        "## Current state",
        "",
        f"- 研究版本：`{STUDY_VERSION}`；事后诊断规则：`{RULE_VERSION}`；"
        f"可执行因果规则：`{CAUSAL_RULE_VERSION}`。",
        f"- 母池只含 A+B 当日完全无买点的日期：{_integer(coverage.get('no_ab_trade_days'))} 日、"
        f"{_integer(coverage.get('no_ab_trade_day_candidate_count'))} 笔；不再用全部排除票代替空仓日研究。",
        f"- 空仓日净收益 >=5% 的机会为 {_integer(coverage.get('no_trade_high_return_count'))} 笔、"
        f"{_integer(coverage.get('no_trade_high_return_days'))} 日。",
        f"- 全天无 A+B 的事后代理为 {_integer(final_full.get('win_count'))}/{_integer(final_full.get('closed_count'))}="
        f"{_fmt(final_full.get('win_rate_pct'))}%，与 A+B 合并为 {_integer(combined.get('win_count'))}/"
        f"{_integer(combined.get('closed_count'))}={_fmt(combined.get('win_rate_pct'))}%，日等权复利"
        f" {_signed(combined.get('daily_equal_weight_compounded_pct'))}%；该口径知道当天后来不会出现 A+B，只用于发现特征，不能交易。",
        f"- 增量命中净收益>=5%的 {_integer(final.get('high_return_count'))} 笔，覆盖 "
        f"{_integer(final.get('high_return_day_recall'))}/{_integer(coverage.get('no_trade_high_return_days'))} 个高溢价日；"
        f"同时买入 {_integer(final.get('loss_count'))} 笔亏损，分布在 {_integer(final.get('loss_days'))} 日。",
        f"- 信号时可执行口径新增 {_integer(causal_incremental.get('win_count'))}/"
        f"{_integer(causal_incremental.get('closed_count'))}={_fmt(causal_incremental.get('win_rate_pct'))}%，"
        f"与 A+B 合并 {_integer(causal_combined.get('win_count'))}/"
        f"{_integer(causal_combined.get('closed_count'))}={_fmt(causal_combined.get('win_rate_pct'))}%。",
        "- 状态是 `historical_proxy_pass_forward_unconfirmed`：该轮提出的 C 候选后续已按分层时间门和因果排序接入正式 A+B+C，但 3-7 月增量偏弱且历史概念成员多数为幸存者代理，仍需自然前向确认。",
        "",
        "## Reverse-discovery sample (not executable)",
        "",
        "1. 正式首板/二进三窗口内已经触板或回封，存在正式涨停价入场和 D+1 官方收盘。",
        "2. 当天最终没有任何候选通过 A+B；同日所有候选都保留，不能每天事后只取最高收益票。该条件只定义逆向母池。",
        "3. 规则只读取 D-1 字段、触板时间以及该时刻之前已经封板的概念成员；D+1 收益只做标签。",
        "",
        "## Missing-opportunity groups",
        "",
        "| 结果组 | 笔数 | 胜率 | 均值 | 复利 |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, label in (
        ("high", "D+1净收益 >=5%"),
        ("positive", "0% < D+1净收益 <5%"),
        ("loss", "D+1净收益 <=0%"),
    ):
        summary = _mapping(_mapping(evaluation.get("outcome_groups")).get(name))
        lines.append(_summary_row(label, summary))

    lines.extend(
        [
            "",
            "### Existing gate comparison",
            "",
            "| 当前首个排除原因 | 笔数 | 胜率 | 均值 | 复利 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    gate_labels = {
        "same_stock_d1_samples_below_5": "同股D+1样本不足5",
        "same_stock_joint_rate_below_30": "同股联合率低于30%",
        "prior_limit_count_126_above_6": "半年涨停超过6次",
    }
    for reason, summary_value in _mapping(
        evaluation.get("gate_failure_groups")
    ).items():
        lines.append(
            _summary_row(
                gate_labels.get(str(reason), str(reason)),
                _mapping(summary_value),
            )
        )

    lines.extend(
        [
            "",
            "### Same and different features",
            "",
            "| 点时特征中位数 | >=5%高溢价 | 0-5%正收益 | 亏损 |",
            "|---|---:|---:|---:|",
        ]
    )
    feature_labels = {
        "prior_industry_turnover_ratio_5d": "D-1行业成交额/5日",
        "prior_position_120": "个股120日位置",
        "stock_gene_combined_win_rate": "同股联合率",
        "prior_return_5d_pct": "个股D-1前5日涨幅",
        "prior_market_sealed_count": "D-1市场封板数",
        "intraday_concept_prior_sealed_count": "触板前细分概念已封板数",
        "intraday_concept_prior_max_board": "触板前细分概念最高板",
    }
    for field, values in _mapping(
        evaluation.get("outcome_feature_medians")
    ).items():
        medians = _mapping(values)
        lines.append(
            f"| {feature_labels.get(str(field), str(field))} | {_fmt(medians.get('high'))} | "
            f"{_fmt(medians.get('positive'))} | {_fmt(medians.get('loss'))} |"
        )
    lines.extend(
        [
            "",
            "静态中位数高度重叠，单字段不能区分赢家；差异来自行业资金、市场阶段、个股位置和触板前概念梯队的交叉。",
            "",
            "### Dynamic rank ablation",
            "",
            "| 触板时动态位置 | 笔数 | 胜率 | 均值 | 复利 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    rank_labels = {
        "rank_1": "概念第1只（尚无扩散）",
        "rank_2_3": "概念第2/3只（即时跟随）",
        "rank_3_5": "概念第3-5只（已有2-4只先行）",
        "rank_6_plus": "概念第6只以后（宽扩散/拥挤）",
    }
    for name, summary_value in _mapping(
        evaluation.get("concept_rank_groups")
    ).items():
        lines.append(
            _summary_row(
                rank_labels.get(str(name), str(name)),
                _mapping(summary_value),
            )
        )

    lines.extend(
        [
            "",
            "## Frozen components",
            "",
            "| 分组 | 规则 | 全量笔数/胜率/均值/复利 | 发现段笔数/胜率 | 3-7月历史验证笔数/胜率 |",
            "|---|---|---|---|---|",
        ]
    )
    labels = {
        "static_mixed_pullback": "同股样本不足 + 混合期 + 5日回撤 + 首次触板",
        "static_industry_override": "行业D-1量能扩张 + 同股联合率<30%",
        "static_rescue": "两类静态资金结构并集",
        "concept_mixed_first_touch": "细分概念已有2-4只先行封板、最高>=2板 + 混合期首次触板",
        "concept_pullback_diffusion": "细分概念已有2-4只先行封板、最高>=2板 + 非普涨 + 5日回撤",
        "concept_rescue": "两类概念扩散并集",
        "final_rescue": "静态资金结构 + 动态概念扩散",
    }
    for name, label in labels.items():
        factor = _mapping(factors.get(name))
        full = _mapping(factor.get("full"))
        discovery = _mapping(factor.get("discovery"))
        validation = _mapping(factor.get("historical_validation"))
        lines.append(
            f"| {name} | {label} | {_integer(full.get('closed_count'))}/{_fmt(full.get('win_rate_pct'))}%/"
            f"{_signed(full.get('average_return_pct'))}%/{_signed(full.get('daily_equal_weight_compounded_pct'))}% | "
            f"{_integer(discovery.get('closed_count'))}/{_fmt(discovery.get('win_rate_pct'))}% | "
            f"{_integer(validation.get('closed_count'))}/{_fmt(validation.get('win_rate_pct'))}% |"
        )

    lines.extend(
        [
            "",
            "### Final rescue by month",
            "",
            "| 月份 | 笔数 | 胜率 | 均值 | 复利 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for month, summary_value in _mapping(final.get("monthly")).items():
        summary = _mapping(summary_value)
        lines.append(
            f"| {month} | {_integer(summary.get('closed_count'))} | "
            f"{_fmt(summary.get('win_rate_pct'))}% | {_signed(summary.get('average_return_pct'))}% | "
            f"{_signed(summary.get('daily_equal_weight_compounded_pct'))}% |"
        )

    lines.extend(
        [
            "",
            "## Executable causal correction",
            "",
            "1. 候选触板时，当天此前尚未出现正式 A/B 基座信号；不能读取当天后续信号。",
            "2. 静态回撤组：同股 D+1 样本不足 5、D-1 混合期、个股 5 日回撤、首次触板。",
            "3. 静态资金覆盖组：D-1 行业成交额/5 日均值 >=1 且同股联合率 <30%；普涨期还必须处于 5 日回撤。",
            "4. 动态概念组：从全部 D-1 概念成员中按 `先行封板数/成员数*log(1+先行封板数)` 选细分概念；触板前已有 2-4 只封板且最高至少 2 板，并满足混合期首次触板或非普涨回撤。",
            "5. 覆盖信号每天只取盘中第一笔，后续仓位留给当天稍后可能出现的正式 A。",
            "",
            "| 因果口径 | 笔数 | 胜率 | 均值 | 日等权复利 | 最大回撤 | 交易日 |",
            "|---|---:|---:|---:|---:|---:|---:|",
            _performance_table_row(
                "新增覆盖",
                causal_incremental,
                _integer(causal.get("incremental_trade_days")),
            ),
            _performance_table_row(
                "A+B + 新增覆盖",
                causal_combined,
                _integer(causal.get("combined_trade_days")),
            ),
            "",
            "| 时间分段 | 笔数 | 胜率 | 均值 | 日等权复利 |",
            "|---|---:|---:|---:|---:|",
            _summary_row("发现段（截至2026-02）", causal_discovery),
            _summary_row("2026-03..07（已查看历史）", causal_validation),
            "",
            "| 严格现金账户 | 信号 | 成交 | 胜率 | 均值 | 复利 | 最大回撤 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for positions in (1, 2):
        summary = _mapping(causal_accounts.get(str(positions)))
        lines.append(
            f"| A+B + 因果覆盖 {positions}仓 | {_integer(summary.get('signal_count'))} | "
            f"{_integer(summary.get('trade_count'))} | {_fmt(summary.get('win_rate'))}% | "
            f"{_signed(summary.get('average_return_pct'))}% | {_signed(summary.get('total_return_pct'))}% | "
            f"{_signed(summary.get('max_drawdown_pct'))}% |"
        )

    lines.extend(
        [
            "",
            "## Post-hoc diagnostic performance (not executable)",
            "",
            "| 口径 | 笔数 | 胜率 | 均值 | 复利 | 最大回撤 | 交易日 |",
            "|---|---:|---:|---:|---:|---:|---:|",
            _performance_table_row(
                "A+B",
                baseline,
                _integer(coverage.get("ab_trade_days")),
            ),
            _performance_table_row(
                "空仓日增量",
                final_full,
                _integer(final.get("trade_days")),
            ),
            _performance_table_row(
                "A+B + 空仓日增量",
                combined,
                _integer(evaluation.get("combined_trade_days")),
            ),
            "",
            "| 严格现金账户 | 信号 | 成交 | 胜率 | 均值 | 复利 | 最大回撤 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for variant, label in (("baseline_ab", "A+B"), ("proposed", "候选方案")):
        accounts = _mapping(cash_accounts.get(variant))
        for positions in (1, 2):
            summary = _mapping(accounts.get(str(positions)))
            lines.append(
                f"| {label} {positions}仓 | {_integer(summary.get('signal_count'))} | "
                f"{_integer(summary.get('trade_count'))} | {_fmt(summary.get('win_rate'))}% | "
                f"{_signed(summary.get('average_return_pct'))}% | {_signed(summary.get('total_return_pct'))}% | "
                f"{_signed(summary.get('max_drawdown_pct'))}% |"
            )

    lines.extend(
        [
            "",
            "## What was missing and what was too strict",
            "",
            "- 缺少的不是永久龙头名单，而是触板时的细分概念扩散状态：先按已封板数/概念成员数归一化选主概念，再判断已有2-4只封板且最高板至少2板。概念名称不入规则。",
            "- 动态第2/3只触板本身不是高胜率因子；有效位置是扩散已经得到2-4只先行封板确认、但尚未进入大面积拥挤。",
            "- `stock_d1_sample_count >=5` 对低位新启动过严：样本不足并不直接放行，只在混合期、5日回撤、首次触板同时成立时覆盖。",
            "- `stock_gene_combined_win_rate >=30%` 对板块资金接管的股票过严：只有 D-1 行业成交额扩张时才允许覆盖。",
            "- `prior_limit_count_126 <=6` 没有整体删除；超过6次只在已经形成细分概念早期扩散的 C 分组中可能被重新接纳。",
            "",
            "## Evidence boundary",
            "",
            f"- 概念成员就绪 {_integer(coverage.get('concept_membership_ready_count'))}/"
            f"{_integer(coverage.get('no_ab_trade_day_candidate_count'))}；形成触板前扩散特征 "
            f"{_integer(coverage.get('concept_feature_ready_count'))} 笔。",
            f"- 成员证据分布：{_mapping(coverage.get('membership_evidence_counts'))}。严格历史快照仅覆盖近期；此前为当前成员幸存者代理。",
            "- 全天无 A+B 的事后规则在发现段和 3-7 月段都超过 60%，但可执行因果规则的 3-7 月新增组只有 55%。本轮已查看该段结果，因此它也不能作为锁定盲测。",
            "- 涨停价入场仍是可成交代理，不含 Tick/L2 排队；自然前向必须使用保存的点时成员、概念强度帧和真实雷达观察。",
            "",
            "## Decision",
            "",
            "- 只有信号时可执行口径的历史代理可以用于目标核对；全天无 A+B 口径仅保留为逆向诊断。",
            "- 因果规则全历史代理已经同时达到全量胜率>=60%、严格两仓复利>=200%、严格单仓复利>=400%。",
            "- 候选规则已按正式分层时间门和因果顺序接入 C；历史代理不能替代自然前向，实时缺少严格 D-1 成员时失败关闭。",
        ]
    )
    return "\n".join(lines) + "\n"


def selected_reverse_ledger(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the final rescue ledger with component membership for audit."""

    masks = no_trade_reverse_rule_masks(frame)
    selected = frame.loc[masks["final_rescue"]].copy()
    for name in (
        "static_mixed_pullback",
        "static_industry_override",
        "concept_mixed_first_touch",
        "concept_pullback_diffusion",
    ):
        selected[name] = masks[name].loc[selected.index]
    fields = (
        "trade_date",
        "signal_time",
        "name",
        "vt_symbol",
        "lane",
        "signal_kind",
        "return_pct",
        "core_quality_gate_reason",
        "prior_market_phase",
        "prior_return_5d_pct",
        "prior_industry_turnover_ratio_5d",
        "stock_d1_sample_count",
        "stock_gene_combined_win_rate",
        "prior_limit_count_126",
        "intraday_concept_name",
        "intraday_concept_prior_sealed_count",
        "intraday_concept_candidate_rank",
        "intraday_concept_prior_max_board",
        "intraday_concept_member_count",
        "intraday_concept_diffusion_density",
        "intraday_concept_membership_evidence_level",
        "static_mixed_pullback",
        "static_industry_override",
        "concept_mixed_first_touch",
        "concept_pullback_diffusion",
    )
    return selected[[field for field in fields if field in selected]].sort_values(
        ["trade_date", "signal_time", "vt_symbol"], kind="stable"
    )


def selected_causal_reverse_ledger(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the first signal-time observable rescue on each trade date."""

    masks = causal_reverse_rule_masks(frame)
    selected = select_causal_reverse_signals(frame)
    for name in (
        "static_mixed_pullback",
        "static_industry_override",
        "concept_mixed_first_touch",
        "concept_pullback_diffusion",
    ):
        selected[name] = masks[name].loc[selected.index]
    fields = (
        "trade_date",
        "signal_time",
        "name",
        "vt_symbol",
        "lane",
        "signal_kind",
        "return_pct",
        "core_quality_gate_reason",
        "prior_market_phase",
        "prior_return_5d_pct",
        "prior_industry_turnover_ratio_5d",
        "stock_d1_sample_count",
        "stock_gene_combined_win_rate",
        "prior_limit_count_126",
        "intraday_concept_name",
        "intraday_concept_prior_sealed_count",
        "intraday_concept_candidate_rank",
        "intraday_concept_prior_max_board",
        "intraday_concept_member_count",
        "intraday_concept_diffusion_density",
        "intraday_concept_membership_evidence_level",
        "static_mixed_pullback",
        "static_industry_override",
        "concept_mixed_first_touch",
        "concept_pullback_diffusion",
    )
    return selected[[field for field in fields if field in selected]].sort_values(
        ["trade_date", "signal_time", "vt_symbol"], kind="stable"
    )


def build_official_closed_trade_evidence(
    orders: Sequence[Mapping[str, object]],
    official_daily_bars: Sequence[Mapping[str, object]],
    *,
    start: date,
    end: date,
) -> list[dict[str, object]]:
    """Settle every scheduled order independently at its official D+1 close."""

    close_lookup = {
        (str(row.get("vt_symbol") or ""), _as_date(row.get("trade_date"))): _number(
            row.get("close_price")
        )
        for row in official_daily_bars
    }
    trades: list[dict[str, object]] = []
    for order in orders:
        signal_date = _as_date(order.get("signal_date") or order.get("entry_date"))
        result_date = _as_date(order.get("result_date"))
        symbol = str(order.get("vt_symbol") or "")
        entry_price = _number(order.get("entry_price"))
        exit_price = close_lookup.get((symbol, result_date))
        if (
            signal_date is None
            or result_date is None
            or not start <= signal_date <= end
            or result_date > end
            or entry_price is None
            or exit_price is None
        ):
            continue
        outcome = cash_backtest.calculate_round_trip_outcome(
            entry_price,
            exit_price,
            limit_price=_number(order.get("limit_price")),
        )
        if outcome is None:
            continue
        trades.append(
            {
                "signal_date": signal_date,
                "vt_symbol": symbol,
                "return_pct": outcome["net_return_pct"],
            }
        )
    return trades


def main(argv: Sequence[str] | None = None) -> None:
    """Run the read-only reverse study against the local frozen history."""

    from alphaagent.server.services.limit_up import (
        first_board_stock_gene_research,
        history_repository,
        scheduled_execution,
    )
    from alphaagent.server.services.limit_up.capital_mainline_repository import (
        load_capital_mainline_inputs,
    )
    from alphaagent.server.services.limit_up.capital_mainline_research import (
        build_event_ledger,
        build_membership_contexts,
    )
    from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger-output", type=Path, required=True)
    parser.add_argument("--causal-ledger-output", type=Path)
    arguments = parser.parse_args(argv)

    days = history_repository.load_history_range(
        HISTORY_STRATEGY_VERSION,
        None,
        arguments.end,
        compact=False,
    )
    orders = scheduled_execution.extract_scheduled_orders(days)
    enriched = first_board_stock_gene_research.attach_prior_stock_gene_evidence_to_orders(
        days, orders
    )
    symbols = sorted({str(order.get("vt_symbol") or "") for order in enriched})
    official_bars = history_repository.load_account_daily_bars(
        symbols,
        arguments.start,
        arguments.end,
    )
    closed_trades = build_official_closed_trade_evidence(
        enriched,
        official_bars,
        start=arguments.start,
        end=arguments.end,
    )
    frame = build_opportunity_reverse_frame(enriched, closed_trades)

    inputs = load_capital_mainline_inputs(
        arguments.start,
        arguments.end,
        include_formal_candidates=False,
        include_stock_bars=False,
    )
    event_ledger = build_event_ledger(inputs)
    frame = attach_intraday_concept_diffusion_proxy(
        frame,
        event_ledger.to_dict("records"),
        build_membership_contexts(inputs),
    )
    evaluation = evaluate_no_trade_reverse(frame)
    trade_dates = sorted(
        {
            parsed
            for day in days
            if (parsed := _as_date(day.get("trade_date"))) is not None
        }
    )
    cash_accounts = evaluate_reverse_cash_accounts(
        frame,
        official_bars,
        trade_dates,
    )
    causal_evaluation = evaluate_causal_reverse(frame)
    causal_cash_accounts = evaluate_causal_reverse_cash_accounts(
        frame,
        official_bars,
        trade_dates,
    )
    report = render_no_trade_reverse_report(
        frame,
        evaluation,
        cash_accounts,
        causal_evaluation,
        causal_cash_accounts,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(report, encoding="utf-8")
    arguments.ledger_output.parent.mkdir(parents=True, exist_ok=True)
    selected_reverse_ledger(frame).to_csv(
        arguments.ledger_output,
        index=False,
        encoding="utf-8-sig",
    )
    causal_ledger_output = arguments.causal_ledger_output or (
        arguments.ledger_output.with_name(
            f"{arguments.ledger_output.stem}_causal.csv"
        )
    )
    causal_ledger_output.parent.mkdir(parents=True, exist_ok=True)
    selected_causal_reverse_ledger(frame).to_csv(
        causal_ledger_output,
        index=False,
        encoding="utf-8-sig",
    )


def _outcome_group_summaries(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    returns = _numeric_series(frame, "return_pct")
    masks = {
        "high": returns.ge(HIGH_RETURN_PCT),
        "positive": returns.gt(0) & returns.lt(HIGH_RETURN_PCT),
        "loss": returns.le(0),
    }
    return {name: performance_summary(frame.loc[mask]) for name, mask in masks.items()}


def _outcome_feature_medians(
    frame: pd.DataFrame,
) -> dict[str, dict[str, float | None]]:
    returns = _numeric_series(frame, "return_pct")
    masks = {
        "high": returns.ge(HIGH_RETURN_PCT),
        "positive": returns.gt(0) & returns.lt(HIGH_RETURN_PCT),
        "loss": returns.le(0),
    }
    fields = (
        "prior_industry_turnover_ratio_5d",
        "prior_position_120",
        "stock_gene_combined_win_rate",
        "prior_return_5d_pct",
        "prior_market_sealed_count",
        "intraday_concept_prior_sealed_count",
        "intraday_concept_prior_max_board",
    )
    result: dict[str, dict[str, float | None]] = {}
    for field in fields:
        result[field] = {}
        for name, mask in masks.items():
            values = _numeric_series(frame.loc[mask], field).dropna()
            result[field][name] = (
                round(float(values.median()), 4) if not values.empty else None
            )
    return result


def _concept_rank_group_summaries(
    frame: pd.DataFrame,
) -> dict[str, dict[str, object]]:
    ranks = _numeric_series(frame, "intraday_concept_candidate_rank")
    masks = {
        "rank_1": ranks.eq(1),
        "rank_2_3": ranks.isin([2, 3]),
        "rank_3_5": ranks.between(3, 5),
        "rank_6_plus": ranks.ge(6),
    }
    return {
        name: performance_summary(frame.loc[mask]) for name, mask in masks.items()
    }


def _group_performance(
    frame: pd.DataFrame, field: str
) -> dict[str, dict[str, object]]:
    values = _string_series(frame, field)
    return {
        str(value): performance_summary(frame.loc[values.eq(value)])
        for value in sorted(values.unique())
    }


def _value_counts(frame: pd.DataFrame, field: str) -> dict[str, int]:
    values = _string_series(frame, field).replace("", "unavailable")
    return {str(key): int(value) for key, value in values.value_counts().items()}


def _context_sector_ids(context: object, symbol: str) -> tuple[str, ...]:
    by_symbol = getattr(context, "by_symbol", {})
    values = by_symbol.get(symbol, ()) if isinstance(by_symbol, Mapping) else ()
    return tuple(str(value) for value in values if str(value))


def _context_member_count(context: object, sector_id: str) -> int:
    counts = getattr(context, "member_counts", {})
    if isinstance(counts, Mapping):
        count = _integer(counts.get(sector_id))
        if count > 0:
            return count
    by_sector = getattr(context, "by_sector", {})
    members = by_sector.get(sector_id, ()) if isinstance(by_sector, Mapping) else ()
    return len(members)


def _context_sector_name(context: object, sector_id: str) -> str:
    names = getattr(context, "sector_names", {})
    return str(names.get(sector_id) or sector_id) if isinstance(names, Mapping) else sector_id


def _context_evidence_level(context: object | None) -> str:
    evidence = getattr(context, "evidence_level", None)
    return str(getattr(evidence, "value", evidence) or "unavailable")


def _event_is_sealed(event: Mapping[str, object]) -> bool:
    return bool(event.get("is_limit_up") or event.get("is_sealed"))


def _event_board(event: Mapping[str, object]) -> int:
    return max(
        _integer(event.get("limit_up_streak") or event.get("limit_times")),
        1,
    )


def _time_text(value: object) -> str | None:
    text = str(value or "").strip()
    if len(text) == 5 and text[2] == ":":
        text = f"{text}:00"
    if len(text) >= 8 and text[2] == ":" and text[5] == ":":
        return text[:8]
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) >= 6:
        return f"{digits[:2]}:{digits[2:4]}:{digits[4:6]}"
    return None


def _numeric_series(frame: pd.DataFrame, field: str) -> pd.Series:
    return pd.to_numeric(
        frame.get(field, pd.Series(index=frame.index, dtype=float)),
        errors="coerce",
    )


def _string_series(frame: pd.DataFrame, field: str) -> pd.Series:
    return (
        frame.get(field, pd.Series("", index=frame.index, dtype=object))
        .fillna("")
        .astype(str)
    )


def _boolean_series(frame: pd.DataFrame, field: str) -> pd.Series:
    return frame.get(field, pd.Series(False, index=frame.index, dtype=bool)).eq(True)


def _as_date(value: object) -> date | None:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None


def _integer(value: object) -> int:
    number = _number(value)
    return int(number) if number is not None else 0


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _fmt(value: object) -> str:
    number = _number(value)
    return f"{number:.4f}" if number is not None else "-"


def _signed(value: object) -> str:
    number = _number(value)
    return f"{number:+.4f}" if number is not None else "-"


def _summary_row(label: str, summary: Mapping[str, object]) -> str:
    return (
        f"| {label} | {_integer(summary.get('closed_count'))} | "
        f"{_fmt(summary.get('win_rate_pct'))}% | "
        f"{_signed(summary.get('average_return_pct'))}% | "
        f"{_signed(summary.get('daily_equal_weight_compounded_pct'))}% |"
    )


def _performance_table_row(
    label: str, summary: Mapping[str, object], trade_days: int
) -> str:
    return (
        f"| {label} | {_integer(summary.get('closed_count'))} | "
        f"{_fmt(summary.get('win_rate_pct'))}% | "
        f"{_signed(summary.get('average_return_pct'))}% | "
        f"{_signed(summary.get('daily_equal_weight_compounded_pct'))}% | "
        f"{_signed(summary.get('maximum_drawdown_pct'))}% | {trade_days} |"
    )


if __name__ == "__main__":
    main()
