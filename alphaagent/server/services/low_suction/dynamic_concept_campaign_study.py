"""Real-data study for dynamic concept campaigns and changing leaders."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd

from .dynamic_concept_campaign import (
    LEADER_OBSERVATION_DAYS,
    MEMBERSHIP_EVIDENCE_LEVEL,
    RESEARCH_STATUS,
    build_concept_campaign_features,
    build_dynamic_leader_ledger,
    build_exploratory_campaigns,
    build_realized_campaign_leader_proxy,
    campaign_candidate_diagnostics,
    evaluate_dynamic_leader_modes,
    evaluate_exploratory_campaigns,
    evaluate_leader_diffusion,
    select_dynamic_leader_campaign_path,
)


STUDY_VERSION = "dynamic-concept-campaign-leader-v1"
CANONICAL_CONCEPT_SOURCE = "eastmoney.board_kline"
RECENT_FLOW_PERIOD = "即时"


@dataclass(frozen=True)
class DynamicCampaignStudyInputs:
    concept_bars: pd.DataFrame
    memberships: pd.DataFrame
    stock_bars: pd.DataFrame
    sector_fund_flows: pd.DataFrame
    stock_fund_flows: pd.DataFrame
    coverage: dict[str, object]
    fingerprints: dict[str, dict[str, object]]


def filter_exploratory_concept_universe(
    concept_bars: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Exclude exact-ID controls already verified by the versioned manifest."""

    from .theme_reference_cohorts import MANIFEST_VERSION, REFERENCE_MANIFEST

    if "sector_id" not in concept_bars:
        raise ValueError("sector_id is required for concept-universe filtering")
    sector_ids = set(concept_bars["sector_id"].astype(str))
    control_ids = {
        sector_id
        for sector_id, record in REFERENCE_MANIFEST.items()
        if record.board_class != "narrative_theme"
    }
    excluded = sorted(sector_ids & control_ids)
    known_narratives = {
        sector_id
        for sector_id, record in REFERENCE_MANIFEST.items()
        if record.board_class == "narrative_theme"
    }
    retained = concept_bars.loc[
        ~concept_bars["sector_id"].astype(str).isin(excluded)
    ].copy()
    retained_ids = set(retained["sector_id"].astype(str))
    return retained, {
        "theme_manifest_version": MANIFEST_VERSION,
        "excluded_control_sector_ids": excluded,
        "excluded_control_sectors": len(excluded),
        "retained_manifest_narrative_sectors": len(retained_ids & known_narratives),
        "retained_unclassified_sectors": len(
            retained_ids - set(REFERENCE_MANIFEST)
        ),
    }


def load_dynamic_campaign_study_inputs() -> DynamicCampaignStudyInputs:
    """Load canonical themes, current main-board members and recent real flows."""

    from sqlalchemy import and_, func, or_, select

    from alphaagent.server.db import schema
    from alphaagent.server.db.session import get_engine

    from .research_protocol import fingerprint_frame

    engine = get_engine()
    concept_statement = (
        select(
            schema.sector_daily_bars.c.sector_id,
            schema.sectors.c.name.label("concept_name"),
            schema.sector_daily_bars.c.trade_date,
            schema.sector_daily_bars.c.open_price,
            schema.sector_daily_bars.c.high_price,
            schema.sector_daily_bars.c.low_price,
            schema.sector_daily_bars.c.close_price,
            schema.sector_daily_bars.c.volume,
            schema.sector_daily_bars.c.turnover,
            schema.sector_daily_bars.c.source,
        )
        .select_from(
            schema.sector_daily_bars.join(
                schema.sectors,
                schema.sector_daily_bars.c.sector_id == schema.sectors.c.id,
            )
        )
        .where(
            schema.sectors.c.type == "theme",
            schema.sector_daily_bars.c.source == CANONICAL_CONCEPT_SOURCE,
        )
        .order_by(
            schema.sector_daily_bars.c.sector_id,
            schema.sector_daily_bars.c.trade_date,
        )
    )
    raw_concept_bars = pd.read_sql(
        concept_statement,
        engine,
        parse_dates=["trade_date"],
    )
    concept_bars, universe_audit = filter_exploratory_concept_universe(
        raw_concept_bars
    )
    if concept_bars.empty:
        raise ValueError("canonical concept history is empty")
    concept_start = pd.Timestamp(concept_bars["trade_date"].min()).date()
    concept_end = pd.Timestamp(concept_bars["trade_date"].max()).date()
    sector_ids = tuple(sorted(concept_bars["sector_id"].astype(str).unique()))

    main_board_filter = or_(
        and_(
            schema.stocks.c.exchange == "SSE",
            or_(
                schema.stocks.c.symbol.like("600%"),
                schema.stocks.c.symbol.like("601%"),
                schema.stocks.c.symbol.like("603%"),
                schema.stocks.c.symbol.like("605%"),
            ),
        ),
        and_(
            schema.stocks.c.exchange == "SZSE",
            or_(
                schema.stocks.c.symbol.like("000%"),
                schema.stocks.c.symbol.like("001%"),
                schema.stocks.c.symbol.like("002%"),
                schema.stocks.c.symbol.like("003%"),
            ),
        ),
    )
    membership_statement = (
        select(
            schema.stock_sector_memberships.c.sector_id,
            schema.stock_sector_memberships.c.vt_symbol,
            schema.stocks.c.name.label("stock_name"),
            schema.stock_sector_memberships.c.source,
        )
        .select_from(
            schema.stock_sector_memberships.join(
                schema.stocks,
                schema.stock_sector_memberships.c.vt_symbol
                == schema.stocks.c.vt_symbol,
            )
        )
        .where(
            schema.stock_sector_memberships.c.sector_type == "theme",
            schema.stock_sector_memberships.c.sector_id.in_(sector_ids),
            main_board_filter,
        )
        .order_by(
            schema.stock_sector_memberships.c.sector_id,
            schema.stock_sector_memberships.c.vt_symbol,
        )
    )
    memberships = pd.read_sql(membership_statement, engine)
    memberships["stock_name"] = memberships["stock_name"].fillna("").astype(str)
    memberships = memberships.loc[
        ~memberships["stock_name"].map(_is_current_risk_name)
    ].copy()
    memberships["evidence_level"] = MEMBERSHIP_EVIDENCE_LEVEL
    if memberships.empty:
        raise ValueError("current main-board concept memberships are empty")
    symbols = tuple(sorted(memberships["vt_symbol"].astype(str).unique()))

    stock_statement = (
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.turnover,
            schema.stock_daily_bars.c.source,
        )
        .where(
            schema.stock_daily_bars.c.vt_symbol.in_(symbols),
            schema.stock_daily_bars.c.trade_date.between(
                concept_start - timedelta(days=60),
                concept_end,
            ),
        )
        .order_by(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
        )
    )
    stock_bars = pd.read_sql(
        stock_statement,
        engine,
        parse_dates=["trade_date"],
    )

    sector_flow_statement = (
        select(
            schema.sector_fund_flows.c.sector_id,
            schema.sector_fund_flows.c.trade_date,
            schema.sector_fund_flows.c.period,
            schema.sector_fund_flows.c.main_net_inflow,
            schema.sector_fund_flows.c.main_net_inflow_ratio,
            schema.sector_fund_flows.c.rank,
            schema.sector_fund_flows.c.source,
        )
        .select_from(
            schema.sector_fund_flows.join(
                schema.sectors,
                schema.sector_fund_flows.c.sector_id == schema.sectors.c.id,
            )
        )
        .where(
            schema.sectors.c.type == "theme",
            schema.sector_fund_flows.c.period == RECENT_FLOW_PERIOD,
        )
        .order_by(
            schema.sector_fund_flows.c.trade_date,
            schema.sector_fund_flows.c.sector_id,
        )
    )
    stock_flow_statement = (
        select(
            schema.stock_fund_flows.c.vt_symbol,
            schema.stock_fund_flows.c.trade_date,
            schema.stock_fund_flows.c.period,
            schema.stock_fund_flows.c.main_net_inflow,
            schema.stock_fund_flows.c.main_net_inflow_ratio,
            schema.stock_fund_flows.c.source,
        )
        .where(
            schema.stock_fund_flows.c.vt_symbol.in_(symbols),
            schema.stock_fund_flows.c.period == RECENT_FLOW_PERIOD,
        )
        .order_by(
            schema.stock_fund_flows.c.trade_date,
            schema.stock_fund_flows.c.vt_symbol,
        )
    )
    sector_fund_flows = pd.read_sql(sector_flow_statement, engine)
    stock_fund_flows = pd.read_sql(stock_flow_statement, engine)
    for frame in (sector_fund_flows, stock_fund_flows):
        if not frame.empty:
            frame["trade_date"] = pd.to_datetime(
                frame["trade_date"], errors="raise"
            ).dt.normalize()

    with engine.connect() as connection:
        strict_membership_rows = int(
            connection.execute(
                select(func.count()).select_from(
                    schema.low_suction_concept_membership_history
                )
            ).scalar_one()
        )
        membership_snapshot_dates = int(
            connection.execute(
                select(
                    func.count(
                        func.distinct(
                            schema.stock_sector_membership_snapshots.c.snapshot_date
                        )
                    )
                )
            ).scalar_one()
        )
    if strict_membership_rows:
        raise ValueError(
            "strict historical memberships now exist; current-proxy loader must be replaced"
        )

    fingerprint_frames = {
        "canonical_concept_bars": (
            concept_bars,
            ("sector_id", "trade_date"),
        ),
        "current_membership_survivorship_proxy": (
            memberships,
            ("sector_id", "vt_symbol"),
        ),
        "main_board_member_stock_bars": (
            stock_bars,
            ("vt_symbol", "trade_date"),
        ),
        "recent_sector_fund_flows": (
            sector_fund_flows,
            ("sector_id", "trade_date", "period"),
        ),
        "recent_stock_fund_flows": (
            stock_fund_flows,
            ("vt_symbol", "trade_date", "period"),
        ),
    }
    fingerprints = {
        name: fingerprint_frame(frame, identity_columns=identity).as_dict()
        for name, (frame, identity) in fingerprint_frames.items()
    }
    coverage = {
        "raw_concept_bar_rows": int(len(raw_concept_bars)),
        "raw_concepts": int(raw_concept_bars["sector_id"].nunique()),
        "concept_bar_rows": int(len(concept_bars)),
        "concepts": int(concept_bars["sector_id"].nunique()),
        "concept_start": concept_start.isoformat(),
        "concept_end": concept_end.isoformat(),
        "current_membership_rows": int(len(memberships)),
        "current_membership_symbols": int(memberships["vt_symbol"].nunique()),
        "strict_historical_membership_rows": strict_membership_rows,
        "membership_snapshot_dates": membership_snapshot_dates,
        "stock_bar_rows": int(len(stock_bars)),
        "stock_symbols": int(stock_bars["vt_symbol"].nunique()),
        "sector_fund_flow_rows": int(len(sector_fund_flows)),
        "sector_fund_flow_dates": int(
            sector_fund_flows["trade_date"].nunique()
            if not sector_fund_flows.empty
            else 0
        ),
        "stock_fund_flow_rows": int(len(stock_fund_flows)),
        "stock_fund_flow_dates": int(
            stock_fund_flows["trade_date"].nunique()
            if not stock_fund_flows.empty
            else 0
        ),
        "minute_rows_read": 0,
        "timing_rows_read": 0,
        "low_suction_outcome_rows_read": 0,
        **universe_audit,
    }
    return DynamicCampaignStudyInputs(
        concept_bars=concept_bars,
        memberships=memberships,
        stock_bars=stock_bars,
        sector_fund_flows=sector_fund_flows,
        stock_fund_flows=stock_fund_flows,
        coverage=coverage,
        fingerprints=fingerprints,
    )


def run_dynamic_concept_campaign_study() -> dict[str, object]:
    """Run campaign and leader research without reading low-suction outcomes."""

    inputs = load_dynamic_campaign_study_inputs()
    concept_features = build_concept_campaign_features(inputs.concept_bars)
    campaigns, compact_path = build_exploratory_campaigns(
        concept_features,
        retained_path_days=LEADER_OBSERVATION_DAYS,
    )
    if campaigns.empty:
        raise ValueError("dynamic campaign study found no campaign candidates")
    campaign_metrics = evaluate_exploratory_campaigns(
        campaigns,
        compact_path,
        block_count=5,
    )
    diagnostics = campaign_candidate_diagnostics(campaign_metrics)
    leader_path = select_dynamic_leader_campaign_path(
        campaigns,
        compact_path,
        max_episodes_per_mode=250,
    )
    dynamic_leaders = build_dynamic_leader_ledger(
        leader_path,
        inputs.memberships,
        inputs.stock_bars,
    )
    if dynamic_leaders.empty:
        raise ValueError("dynamic campaign study found no member leader rows")
    realized_proxy = build_realized_campaign_leader_proxy(dynamic_leaders)
    leader_metrics = evaluate_dynamic_leader_modes(
        dynamic_leaders,
        realized_proxy,
        block_count=5,
    )
    leader_diffusion_metrics = evaluate_leader_diffusion(
        dynamic_leaders,
        block_count=5,
    )
    recent_fund_evidence = evaluate_recent_fund_corroboration(
        concept_features,
        inputs.sector_fund_flows,
        dynamic_leaders,
        inputs.stock_fund_flows,
    )
    coverage = {
        **inputs.coverage,
        "campaign_candidates": int(len(campaigns)),
        "campaign_definitions": int(
            campaigns[
                [
                    "anchor_mode",
                    "exit_drawdown_pct",
                    "exit_confirm_sessions",
                ]
            ]
            .drop_duplicates()
            .shape[0]
        ),
        "compact_campaign_path_rows": int(len(compact_path)),
        "leader_sample_campaigns": int(leader_path["campaign_id"].nunique()),
        "dynamic_leader_rows": int(len(dynamic_leaders)),
        "dynamic_leader_episodes": int(dynamic_leaders["episode_id"].nunique()),
        "realized_leader_rows": int(len(realized_proxy)),
        "leader_diffusion_metric_rows": int(len(leader_diffusion_metrics)),
    }
    examples = _representative_campaigns(campaigns)
    return build_dynamic_campaign_report(
        coverage=coverage,
        fingerprints=inputs.fingerprints,
        campaign_metrics=campaign_metrics,
        campaign_diagnostics=diagnostics,
        leader_metrics=leader_metrics,
        recent_fund_evidence=recent_fund_evidence,
        examples=examples,
        leader_diffusion_metrics=leader_diffusion_metrics,
    )


def evaluate_recent_fund_corroboration(
    concept_features: pd.DataFrame,
    sector_fund_flows: pd.DataFrame,
    dynamic_leaders: pd.DataFrame,
    stock_fund_flows: pd.DataFrame,
) -> dict[str, object]:
    """Compare short real net-flow history with price ranks without tuning history."""

    base: dict[str, object] = {
        "historical_selection_eligible": False,
        "selection_role": "corroboration_only",
        "sector_trade_dates": _date_count(sector_fund_flows),
        "stock_trade_dates": _date_count(stock_fund_flows),
        "sector_return_1d_inflow_spearman": None,
        "sector_return_5d_inflow_spearman": None,
        "sector_turnover_expansion_inflow_spearman": None,
        "stock_gain_top3_inflow_top3_overlap_pct": None,
        "stock_overlap_groups": 0,
    }
    sector_evidence = _sector_fund_corroboration(
        concept_features,
        sector_fund_flows,
    )
    stock_evidence = _stock_fund_corroboration(
        dynamic_leaders,
        stock_fund_flows,
    )
    return {**base, **sector_evidence, **stock_evidence}


def build_dynamic_campaign_report(
    *,
    coverage: Mapping[str, object],
    fingerprints: Mapping[str, Mapping[str, object]],
    campaign_metrics: pd.DataFrame,
    campaign_diagnostics: Sequence[Mapping[str, object]],
    leader_metrics: pd.DataFrame,
    recent_fund_evidence: Mapping[str, object],
    examples: Sequence[Mapping[str, object]],
    leader_diffusion_metrics: pd.DataFrame | None = None,
) -> dict[str, object]:
    """Build an explicitly non-frozen two-track evidence report."""

    return {
        "study_version": STUDY_VERSION,
        "research_status": RESEARCH_STATUS,
        "frozen_parameters": [],
        "decision": "continue_research_no_rule_frozen",
        "research_tracks": {
            "historical_campaign": {
                "role": "candidate_comparison",
                "concept_history": CANONICAL_CONCEPT_SOURCE,
                "membership_evidence": MEMBERSHIP_EVIDENCE_LEVEL,
                "capital_measure": "turnover_and_turnover_expansion",
                "net_inflow_used": False,
            },
            "recent_real_fund": {
                "role": "directional_corroboration",
                "selection_role": "corroboration_only",
                "historical_selection_eligible": False,
            },
        },
        "tables_read": {
            "concept_daily_bars": int(coverage.get("concept_bar_rows", 0)),
            "current_memberships": int(coverage.get("current_membership_rows", 0)),
            "stock_daily_bars": int(coverage.get("stock_bar_rows", 0)),
            "sector_fund_flows": int(coverage.get("sector_fund_flow_rows", 0)),
            "stock_fund_flows": int(coverage.get("stock_fund_flow_rows", 0)),
            "minute_bars": 0,
            "market_timing": 0,
            "low_suction_outcomes": 0,
        },
        "coverage": _json_safe(dict(coverage)),
        "fingerprints": _json_safe(dict(fingerprints)),
        "campaign_candidate_metrics": _records(campaign_metrics),
        "campaign_candidate_diagnostics": _json_safe(list(campaign_diagnostics)),
        "dynamic_leader_metrics": _records(leader_metrics),
        "leader_diffusion_metrics": _records(
            leader_diffusion_metrics
            if leader_diffusion_metrics is not None
            else pd.DataFrame()
        ),
        "recent_fund_corroboration": _json_safe(dict(recent_fund_evidence)),
        "representative_campaigns": _json_safe(list(examples)),
        "limitations": [
            "the versioned exact-ID manifest excludes verified mechanical, style and report controls, but most retained boards remain unclassified",
            "historical concept memberships are unavailable; stock-level evidence uses a current-membership survivorship proxy",
            "historical turnover is not net inflow",
            "recent real sector and stock net-inflow history is too short for historical selection",
            "realized leader ranks use repeated observed highs and concept excess; they remain descriptive endpoint proxies, not production truth",
            "leader-to-follower diffusion is an association and cannot establish that the leader caused follower buying",
            "no low-suction entry, exit or return was read",
        ],
        "next_research": [
            "accumulate complete point-in-time concept membership snapshots",
            "accumulate sector and stock real net inflow across multiple campaign cycles",
            "repeat the same five-block comparison before selecting one campaign definition",
            "only after identity stability, test pullback entry and exit outcomes",
        ],
    }


def render_dynamic_campaign_json(report: Mapping[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def render_dynamic_campaign_markdown(report: Mapping[str, object]) -> str:
    """Render candidate evidence, limitations and the next validation step."""

    coverage = report["coverage"]
    fund = report["recent_fund_corroboration"]
    lines = [
        "# AlphaAgent 动态概念行情与动态龙头探索",
        "",
        "## 结论",
        "",
        "研究状态：`exploratory_not_frozen`，所有启动、回撤、结束和龙头排序参数均未冻结。",
        "本轮只比较板块行情描述能力和龙头身份稳定性，不读取低吸买卖收益。",
        "历史个股层使用当前成员生存偏差代理；近期真实净流入仅作旁证，不能参与三年历史选择。",
        "",
        "## 数据边界",
        "",
        f"- 概念指数：`{coverage.get('concept_start')}..{coverage.get('concept_end')}`，"
        f"`{coverage.get('concept_bar_rows', 0)}` 行 / `{coverage.get('concepts', 0)}` 个概念。",
        f"- 当前成员代理：`{coverage.get('current_membership_rows', 0)}` 行；严格历史成员："
        f"`{coverage.get('strict_historical_membership_rows', 0)}` 行。",
        f"- 个股日线：`{coverage.get('stock_bar_rows', 0)}` 行 / "
        f"`{coverage.get('stock_symbols', 0)}` 只主板股。",
        f"- 候选行情：`{coverage.get('campaign_candidates', 0)}` 段 / "
        f"`{coverage.get('campaign_definitions', 0)}` 组定义。",
        "",
        "## 板块行情候选",
        "",
        "| 启动 | 回撤 | 确认日 | 行情段 | 中位峰值 | 到达 +5% | 到达 +10% | 结束后 10 日再创新高 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    pooled_campaigns = [
        row
        for row in report["campaign_candidate_metrics"]
        if row.get("scope") == "pooled"
    ]
    for row in pooled_campaigns:
        lines.append(
            f"| {row['anchor_mode']} | {row['exit_drawdown_pct']}% | "
            f"{row['exit_confirm_sessions']} | {row['campaigns']} | "
            f"{_fmt_pct(row.get('median_peak_gain_pct'))} | "
            f"{_fmt_pct(row.get('reach_5pct_rate'))} | "
            f"{_fmt_pct(row.get('reach_10pct_rate'))} | "
            f"{_fmt_pct(row.get('higher_high_within_10_after_end_rate'))} |"
        )
    lines.extend(
        [
            "",
            "## 动态龙头",
            "",
            "以下为当前成员代理在关键行情日对最终描述性龙头的身份重合，不是交易结果。",
            "",
            "| 启动 | 时点 | 排序方式 | 样本 | Top1 | Top3 捕获最终龙一 | Top3 重合 |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    pooled_leaders = [
        row
        for row in report["dynamic_leader_metrics"]
        if row.get("scope") == "pooled"
        and row.get("campaign_day_bucket") in {"D", "D+3", "D+5", "D+10"}
    ]
    for row in pooled_leaders:
        lines.append(
            f"| {row['anchor_mode']} | {row['campaign_day_bucket']} | "
            f"{row['leader_mode']} | {row['qualified_campaigns']} | "
            f"{_fmt_pct(row.get('top1_exact_rate_pct'))} | "
            f"{_fmt_pct(row.get('top3_capture_realized_top1_rate_pct'))} | "
            f"{_fmt_pct(row.get('mean_realized_top3_overlap_pct'))} |"
        )
    lines.extend(
        [
            "",
            "## 龙头领先与板块扩散",
            "",
            "龙一在 D 的强度与后续跟随股扩散只表示领先关联，不能证明因果带动。",
            "",
            "| 启动 | 未来日 | 龙头方式 | 样本 | 跟随中位增量 | 上涨宽度变化 | 龙头仍为 Top3 | 领先涨幅/跟随增量相关 |",
            "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    pooled_diffusion = [
        row
        for row in report.get("leader_diffusion_metrics", [])
        if row.get("scope") == "pooled"
    ]
    for row in pooled_diffusion:
        lines.append(
            f"| {row['anchor_mode']} | D+{row['future_day']} | "
            f"{row['leader_mode']} | {row['qualified_campaigns']} | "
            f"{_fmt_pct(row.get('median_follower_gain_delta_pct'))} | "
            f"{_fmt_pct(row.get('median_positive_breadth_delta_pct_points'))} | "
            f"{_fmt_pct(row.get('leader_retained_top3_rate_pct'))} | "
            f"{_fmt_number(row.get('leader_gain_follower_delta_spearman'))} |"
        )
    lines.extend(
        [
            "",
            "## 近期资金旁证",
            "",
            f"- 板块净流入：`{fund.get('sector_trade_dates', 0)}` 个交易日；状态 "
            f"`{fund.get('sector_status')}`。",
            f"- 个股净流入：`{fund.get('stock_trade_dates', 0)}` 个交易日；状态 "
            f"`{fund.get('stock_status')}`。",
            f"- 板块单日涨幅/净流入 Spearman："
            f"`{_fmt_number(fund.get('sector_return_1d_inflow_spearman'))}`。",
            f"- 板块 5 日涨幅/净流入 Spearman："
            f"`{_fmt_number(fund.get('sector_return_5d_inflow_spearman'))}`。",
            f"- 个股涨幅 Top3/净流入 Top3 重合："
            f"`{_fmt_pct(fund.get('stock_gain_top3_inflow_top3_overlap_pct'))}`。",
            "",
            "## 限制与下一步",
            "",
            "- 当前成员不能还原历史点时成员，个股龙头数字只用于比较算法结构。",
            "- 成交额扩张不能称为资金净流入；短期真实资金数据不能选择三年规则。",
            "- 继续积累点时成员与真实资金历史，按同一五时段协议复验后，才决定是否冻结行情和龙头算法。",
            "- 身份研究稳定后，才重新读取低吸买卖结果。",
            "",
        ]
    )
    return "\n".join(lines)


def _sector_fund_corroboration(
    concept_features: pd.DataFrame,
    sector_fund_flows: pd.DataFrame,
) -> dict[str, object]:
    if sector_fund_flows.empty:
        return {"sector_status": "missing_sector_fund_history"}
    required_features = (
        "sector_id",
        "trade_date",
        "return_1d_pct",
        "return_5d_pct",
        "turnover_expansion",
    )
    required_flows = ("sector_id", "trade_date", "main_net_inflow")
    _require_columns(concept_features, required_features, "concept feature")
    _require_columns(sector_fund_flows, required_flows, "sector fund flow")
    features = _normalized_dates(concept_features, ("sector_id", "trade_date"))
    flows = _normalized_dates(sector_fund_flows, ("sector_id", "trade_date"))
    if "period" in flows:
        flows = flows.loc[flows["period"].eq(RECENT_FLOW_PERIOD)]
    joined = features[list(required_features)].merge(
        flows[list(required_flows)],
        on=["sector_id", "trade_date"],
        how="inner",
        validate="one_to_one",
    )
    return {
        "sector_status": (
            "available_short_history" if not joined.empty else "missing_joined_sector_fund_history"
        ),
        "sector_joined_rows": int(len(joined)),
        "sector_return_1d_inflow_spearman": _spearman(
            joined["return_1d_pct"], joined["main_net_inflow"]
        ),
        "sector_return_5d_inflow_spearman": _spearman(
            joined["return_5d_pct"], joined["main_net_inflow"]
        ),
        "sector_turnover_expansion_inflow_spearman": _spearman(
            joined["turnover_expansion"], joined["main_net_inflow"]
        ),
    }


def _stock_fund_corroboration(
    dynamic_leaders: pd.DataFrame,
    stock_fund_flows: pd.DataFrame,
) -> dict[str, object]:
    if stock_fund_flows.empty:
        return {"stock_status": "missing_stock_fund_history"}
    required_leaders = (
        "sector_id",
        "trade_date",
        "vt_symbol",
        "cumulative_gain_rank",
    )
    required_flows = ("vt_symbol", "trade_date", "main_net_inflow")
    _require_columns(dynamic_leaders, required_leaders, "dynamic leader")
    _require_columns(stock_fund_flows, required_flows, "stock fund flow")
    leaders = dynamic_leaders.copy()
    leaders["trade_date"] = pd.to_datetime(
        leaders["trade_date"], errors="raise"
    ).dt.normalize()
    leaders = leaders.sort_values("cumulative_gain_rank").drop_duplicates(
        ["sector_id", "trade_date", "vt_symbol"]
    )
    flows = _normalized_dates(stock_fund_flows, ("vt_symbol", "trade_date"))
    if "period" in flows:
        flows = flows.loc[flows["period"].eq(RECENT_FLOW_PERIOD)]
    joined = leaders[list(required_leaders)].merge(
        flows[list(required_flows)],
        on=["vt_symbol", "trade_date"],
        how="inner",
        validate="many_to_one",
    )
    overlaps: list[float] = []
    for _, group in joined.groupby(["sector_id", "trade_date"], sort=True):
        if group["vt_symbol"].nunique() < 3:
            continue
        gain_top3 = set(
            group.loc[group["cumulative_gain_rank"].le(3), "vt_symbol"].astype(str)
        )
        inflow_top3 = set(
            group.nlargest(3, "main_net_inflow")["vt_symbol"].astype(str)
        )
        overlaps.append(len(gain_top3 & inflow_top3) / 3.0 * 100.0)
    return {
        "stock_status": (
            "available_short_history" if overlaps else "missing_joined_stock_fund_history"
        ),
        "stock_joined_rows": int(len(joined)),
        "stock_gain_top3_inflow_top3_overlap_pct": (
            float(np.mean(overlaps)) if overlaps else None
        ),
        "stock_overlap_groups": len(overlaps),
    }


def _representative_campaigns(
    campaigns: pd.DataFrame,
) -> list[dict[str, object]]:
    complete = campaigns.loc[~campaigns["right_censored"].astype(bool)].copy()
    if complete.empty:
        return []
    reference = complete.loc[
        complete["anchor_mode"].eq("breakout_relative")
        & complete["exit_drawdown_pct"].eq(5.0)
        & complete["exit_confirm_sessions"].eq(3)
    ]
    if reference.empty:
        reference = complete
    columns = (
        "sector_id",
        "concept_name",
        "anchor_date",
        "end_date",
        "campaign_days",
        "peak_gain_pct",
        "terminal_gain_pct",
        "higher_high_within_10_after_end",
    )
    records: list[dict[str, object]] = []
    for label, rows in (
        ("high_peak_gain", reference.nlargest(5, "peak_gain_pct")),
        ("low_peak_gain", reference.nsmallest(5, "peak_gain_pct")),
    ):
        for row in rows.loc[:, list(columns)].to_dict(orient="records"):
            records.append({"label": label, **_json_safe(row)})
    return records


def _normalized_dates(
    frame: pd.DataFrame,
    identity: Sequence[str],
) -> pd.DataFrame:
    result = frame.copy()
    result["trade_date"] = pd.to_datetime(
        result["trade_date"], errors="raise"
    ).dt.normalize()
    if result.duplicated(list(identity)).any():
        raise ValueError(f"duplicate identities for {', '.join(identity)}")
    return result


def _spearman(left: pd.Series, right: pd.Series) -> float | None:
    pairs = pd.concat([left, right], axis=1).dropna()
    if len(pairs) < 3 or pairs.iloc[:, 0].nunique() < 2 or pairs.iloc[:, 1].nunique() < 2:
        return None
    value = pairs.iloc[:, 0].corr(pairs.iloc[:, 1], method="spearman")
    return float(value) if pd.notna(value) else None


def _records(frame: pd.DataFrame) -> list[dict[str, object]]:
    return [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _json_safe(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if pd.isna(value):
        return None
    return value


def _date_count(frame: pd.DataFrame) -> int:
    if frame.empty or "trade_date" not in frame:
        return 0
    return int(pd.to_datetime(frame["trade_date"], errors="coerce").nunique())


def _is_current_risk_name(value: object) -> bool:
    normalized = str(value).upper().replace(" ", "")
    return normalized.startswith(("ST", "*ST", "SST", "S*ST"))


def _fmt_pct(value: object) -> str:
    number = _number_or_none(value)
    return "-" if number is None else f"{number:.4f}%"


def _fmt_number(value: object) -> str:
    number = _number_or_none(value)
    return "-" if number is None else f"{number:.4f}"


def _number_or_none(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _require_columns(
    frame: pd.DataFrame,
    columns: Sequence[str],
    label: str,
) -> None:
    missing = sorted(set(columns) - set(frame))
    if missing:
        raise ValueError(f"missing {label} columns: {', '.join(missing)}")
