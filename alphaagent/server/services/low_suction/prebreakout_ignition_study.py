"""End-to-end study for causal pre-breakout ignition and later diffusion."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from .dynamic_concept_campaign import build_concept_campaign_features
from .dynamic_concept_campaign_study import load_dynamic_campaign_study_inputs
from .prebreakout_ignition import (
    MEMBERSHIP_EVIDENCE_LEVEL,
    PREBREAKOUT_LEADS,
    RESEARCH_STATUS,
    build_breakout_transition_events,
    build_prebreakout_diffusion_outcomes,
    build_prebreakout_member_features,
    build_prebreakout_observation_pairs,
    build_prebreakout_stock_features,
    evaluate_prebreakout_diffusion,
    evaluate_prebreakout_features,
    prebreakout_feature_diagnostics,
)


STUDY_VERSION = "prebreakout-ignition-diffusion-v1"
MINIMUM_RECENT_FUND_PAIRS = 30


def run_prebreakout_ignition_study() -> dict[str, object]:
    """Run matched pre-breakout ignition and later diffusion research."""

    inputs = load_dynamic_campaign_study_inputs()
    concept_features = build_concept_campaign_features(inputs.concept_bars)
    events = build_breakout_transition_events(concept_features)
    if events.empty:
        raise ValueError("prebreakout study found no breakout transitions")

    observations = build_prebreakout_observation_pairs(
        events,
        concept_features,
        max_events_per_block=250,
    )
    if observations.empty:
        raise ValueError("prebreakout study found no matched observation pairs")

    stock_features = build_prebreakout_stock_features(inputs.stock_bars)
    feature_panel, early_member_ledger = build_prebreakout_member_features(
        observations,
        inputs.memberships,
        stock_features,
    )
    if feature_panel.empty:
        raise ValueError("prebreakout study found no complete member feature rows")

    feature_metrics = evaluate_prebreakout_features(feature_panel, block_count=5)
    diagnostics = prebreakout_feature_diagnostics(feature_metrics)
    concept_calendar = concept_features[["sector_id", "trade_date"]]
    diffusion_outcomes = build_prebreakout_diffusion_outcomes(
        observations,
        early_member_ledger,
        inputs.memberships,
        inputs.stock_bars,
        concept_calendar,
    )
    if diffusion_outcomes.empty:
        raise ValueError("prebreakout study found no complete diffusion outcomes")
    diffusion_metrics = evaluate_prebreakout_diffusion(
        diffusion_outcomes,
        block_count=5,
    )
    recent_fund_coverage = evaluate_recent_fund_pair_coverage(
        feature_panel,
        early_member_ledger,
        inputs.sector_fund_flows,
        inputs.stock_fund_flows,
    )
    coverage = _study_coverage(
        inputs.coverage,
        events=events,
        observations=observations,
        feature_panel=feature_panel,
        early_member_ledger=early_member_ledger,
        diffusion_outcomes=diffusion_outcomes,
        feature_metrics=feature_metrics,
        diffusion_metrics=diffusion_metrics,
        diagnostics=diagnostics,
    )
    return build_prebreakout_report(
        coverage=coverage,
        fingerprints=inputs.fingerprints,
        feature_metrics=feature_metrics,
        feature_diagnostics=diagnostics,
        diffusion_metrics=diffusion_metrics,
        recent_fund_coverage=recent_fund_coverage,
        matched_examples=_matched_examples(feature_panel),
    )


def evaluate_recent_fund_pair_coverage(
    observations: pd.DataFrame,
    early_member_ledger: pd.DataFrame,
    sector_fund_flows: pd.DataFrame,
    stock_fund_flows: pd.DataFrame,
) -> dict[str, object]:
    """Count recent flow-key coverage without reading any flow value."""

    observation_columns = (
        "pair_id",
        "sample_role",
        "sector_id",
        "observation_date",
    )
    leader_columns = (
        "pair_id",
        "sample_role",
        "observation_date",
        "vt_symbol",
        "early_leader",
    )
    _require_columns(observations, observation_columns, "observation")
    _require_columns(early_member_ledger, leader_columns, "early member ledger")
    observation_keys = _normalized_observation_keys(observations)
    leader_keys = _normalized_early_leader_keys(early_member_ledger)
    sector_keys = _dated_key_set(
        sector_fund_flows,
        identity_column="sector_id",
    )
    stock_keys = _dated_key_set(
        stock_fund_flows,
        identity_column="vt_symbol",
    )
    observation_keys["covered"] = observation_keys.apply(
        lambda row: (str(row["sector_id"]), row["observation_date"]) in sector_keys,
        axis=1,
    )
    leader_keys["covered"] = leader_keys.apply(
        lambda row: (str(row["vt_symbol"]), row["observation_date"]) in stock_keys,
        axis=1,
    )
    sector_pairs = _complete_covered_pair_ids(observation_keys)
    stock_pairs = _complete_covered_pair_ids(leader_keys)
    joint_pairs = sector_pairs & stock_pairs
    return {
        "selection_role": "coverage_only",
        "sector_trade_dates": _trade_date_count(sector_fund_flows),
        "stock_trade_dates": _trade_date_count(stock_fund_flows),
        "sector_matched_pairs": len(sector_pairs),
        "stock_early_leader_matched_pairs": len(stock_pairs),
        "joint_matched_pairs": len(joint_pairs),
        "minimum_pairs_for_separate_analysis": MINIMUM_RECENT_FUND_PAIRS,
        "separate_analysis_eligible": len(joint_pairs) >= MINIMUM_RECENT_FUND_PAIRS,
        "historical_feature_selection_eligible": False,
        "flow_values_used": False,
    }


def build_prebreakout_report(
    *,
    coverage: Mapping[str, object],
    fingerprints: Mapping[str, Mapping[str, object]],
    feature_metrics: pd.DataFrame,
    feature_diagnostics: Sequence[Mapping[str, object]],
    diffusion_metrics: pd.DataFrame,
    recent_fund_coverage: Mapping[str, object],
    matched_examples: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Build the non-frozen matched prediction and diffusion report."""

    return {
        "study_version": STUDY_VERSION,
        "research_status": RESEARCH_STATUS,
        "frozen_parameters": [],
        "decision": "continue_research_no_rule_frozen",
        "membership_evidence": MEMBERSHIP_EVIDENCE_LEVEL,
        "research_contract": {
            "positive_sample": "false_to_true_20_session_concept_breakout",
            "control_sample": (
                "same_concept_same_time_block_without_breakout_transition_within_10_sessions"
            ),
            "lead_days": list(PREBREAKOUT_LEADS),
            "feature_information_cutoff": "observation_date_and_earlier",
            "leader_identity_frozen_at": "observation_date",
            "future_outcomes_loaded_after_features": True,
            "historical_membership_mode": MEMBERSHIP_EVIDENCE_LEVEL,
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
        "prebreakout_feature_metrics": _records(feature_metrics),
        "prebreakout_feature_diagnostics": _json_safe(list(feature_diagnostics)),
        "diffusion_metrics": _records(diffusion_metrics),
        "recent_fund_coverage": _json_safe(dict(recent_fund_coverage)),
        "matched_examples": _json_safe(list(matched_examples)),
        "limitations": [
            "retained concept boards still include unclassified-board risk after exact-ID control exclusions",
            "historical concept memberships are unavailable; member evidence is a current-membership survivorship proxy",
            "matched controls reduce calendar and concept confounding but do not establish causal prediction",
            "turnover and turnover expansion are not net inflow",
            "recent real fund history is coverage-only and does not select historical features",
            "leader-to-follower diffusion is an association and cannot establish that the leader caused follower buying",
            "no minute data, timing labels or low-suction trade outcomes were read",
        ],
        "next_research": [
            "audit candidate features in later unseen time blocks without changing their definitions",
            "accumulate point-in-time concept memberships and repeat the same matching contract",
            "only after identity and diffusion evidence are stable, define pullback observations without reading their returns",
        ],
    }


def render_prebreakout_json(report: Mapping[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def render_prebreakout_markdown(report: Mapping[str, object]) -> str:
    """Render matched pre-breakout feature and later diffusion evidence."""

    coverage = report["coverage"]
    recent_fund = report["recent_fund_coverage"]
    lines = [
        "# AlphaAgent 突破前点火与扩散研究",
        "",
        "## 结论",
        "",
        "研究状态：`exploratory_not_frozen`，所有点火、宽度、量能和龙头阈值均未冻结。",
        "正样本读取概念 20 日突破前 D-10/D-5/D-3/D-1；反例采用同概念匹配对照。",
        "观察日特征与早期龙头身份先固定，再读取等长后续扩散；这属于历史条件比较，不是低吸收益回测。",
        "",
        *_headline_finding_lines(report),
        "## 数据与匹配",
        "",
        f"- 概念指数：`{coverage.get('concept_start')}..{coverage.get('concept_end')}`，"
        f"`{coverage.get('concept_bar_rows', 0)}` 行 / `{coverage.get('concepts', 0)}` 个概念。",
        f"- 突破转折：`{coverage.get('breakout_transition_events', 0)}` 个；"
        f"完整匹配对：`{coverage.get('matched_pairs', 0)}` 对。",
        f"- 当前成员幸存者代理：`{coverage.get('current_membership_rows', 0)}` 行；"
        f"严格历史成员：`{coverage.get('strict_historical_membership_rows', 0)}` 行。",
        f"- 主板个股日线：`{coverage.get('stock_bar_rows', 0)}` 行 / "
        f"`{coverage.get('stock_symbols', 0)}` 只。",
        "",
        "## 突破前特征",
        "",
        "AUC 和正样本更高比例只衡量区分度；候选标签仍需未见时段前向复验。",
        "",
        "| 提前日 | 特征 | 配对 | 正中位 | 对照中位 | 配对差 | 正样本更高 | AUC | 稳定块 | 状态 |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    diagnostics = {
        (row.get("lead_days"), row.get("feature")): row
        for row in report["prebreakout_feature_diagnostics"]
    }
    pooled_features = [
        row
        for row in report["prebreakout_feature_metrics"]
        if row.get("scope") == "pooled"
    ]
    for row in pooled_features:
        diagnostic = diagnostics.get((row.get("lead_days"), row.get("feature")), {})
        lines.append(
            f"| D-{row['lead_days']} | `{row['feature']}` | {row['pairs']} | "
            f"{_fmt_number(row.get('positive_median'))} | "
            f"{_fmt_number(row.get('control_median'))} | "
            f"{_fmt_number(row.get('median_paired_difference'))} | "
            f"{_fmt_pct(row.get('matched_positive_higher_rate_pct'))} | "
            f"{_fmt_number(row.get('rank_auc'))} | "
            f"{diagnostic.get('stable_blocks', 0)} | "
            f"`{diagnostic.get('status', 'exploratory_not_selected')}` |"
        )
    candidates = [
        row
        for row in report["prebreakout_feature_diagnostics"]
        if row.get("status") == "candidate_for_forward_validation"
    ]
    lines.extend(
        [
            "",
            "## 五时段稳定性",
            "",
            "以下仅列达到预注册门槛的候选；每格为 `完整配对数 / AUC`，不是生产规则。",
            "",
            "| 提前日 | 特征 | B1 | B2 | B3 | B4 | B5 |",
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    metric_lookup = {
        (row.get("lead_days"), row.get("feature"), row.get("scope")): row
        for row in report["prebreakout_feature_metrics"]
    }
    for candidate in candidates:
        cells: list[str] = []
        for block in range(1, 6):
            row = metric_lookup.get(
                (
                    candidate.get("lead_days"),
                    candidate.get("feature"),
                    f"block_{block}",
                ),
                {},
            )
            cells.append(
                f"{row.get('pairs', 0)} / {_fmt_number(row.get('rank_auc'))}"
            )
        lines.append(
            f"| D-{candidate['lead_days']} | `{candidate['feature']}` | "
            + " | ".join(cells)
            + " |"
        )
    if not candidates:
        lines.append("| - | 本轮无候选 | - | - | - | - | - |")
    lines.extend(
        [
            "",
            "## 龙头保持与跟随扩散",
            "",
            "早期龙头在观察日冻结；后续龙头保持和跟随扩散是关联，不能证明因果带动。",
            "",
            "| 提前日 | 未来日 | 配对 | 正跟随收益 | 对照跟随收益 | 配对差 | 正宽度 | 对照宽度 | 正龙头保持 Top3 |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    pooled_diffusion = [
        row for row in report["diffusion_metrics"] if row.get("scope") == "pooled"
    ]
    for row in pooled_diffusion:
        lines.append(
            f"| D-{row['lead_days']} | +{row['future_days']} | {row['pairs']} | "
            f"{_fmt_pct(row.get('positive_follower_median_return_pct'))} | "
            f"{_fmt_pct(row.get('control_follower_median_return_pct'))} | "
            f"{_fmt_pct(row.get('median_follower_return_difference_pct'))} | "
            f"{_fmt_pct(row.get('positive_follower_breadth_pct'))} | "
            f"{_fmt_pct(row.get('control_follower_breadth_pct'))} | "
            f"{_fmt_pct(row.get('positive_leader_retained_top3_rate_pct'))} |"
        )
    lines.extend(
        [
            "",
            "## 近期真实资金覆盖",
            "",
            f"- 板块资金覆盖：`{recent_fund.get('sector_trade_dates', 0)}` 个交易日 / "
            f"`{recent_fund.get('sector_matched_pairs', 0)}` 个完整匹配对。",
            f"- 早期龙头资金覆盖：`{recent_fund.get('stock_trade_dates', 0)}` 个交易日 / "
            f"`{recent_fund.get('stock_early_leader_matched_pairs', 0)}` 个完整匹配对。",
            f"- 联合覆盖：`{recent_fund.get('joint_matched_pairs', 0)}` 对；至少 "
            f"`{recent_fund.get('minimum_pairs_for_separate_analysis', 30)}` 对才单独分析，"
            "本报告不使用净流入数值选择历史特征。",
            "",
            "## 限制与下一步",
            "",
            "- 当前成员幸存者代理不能还原历史点时成员，个股身份结论不能正式冻结。",
            "- 同概念匹配对照降低部分混杂，但仍不能把相关性解释成因果预测。",
            "- 下一步只把达到预注册门槛的候选带到未见时间块复验；未通过则保留为否证。",
            "- 身份和扩散稳定前，不读取低吸买卖收益。",
            "",
        ]
    )
    return "\n".join(lines)


def _headline_finding_lines(report: Mapping[str, object]) -> list[str]:
    pooled_features = {
        (row.get("lead_days"), row.get("feature")): row
        for row in report["prebreakout_feature_metrics"]
        if row.get("scope") == "pooled"
    }
    lines = ["## 本轮发现", ""]
    trend = pooled_features.get((10, "concept_return_10d_pct"))
    turnover = pooled_features.get((10, "concept_turnover_expansion"))
    breadth = pooled_features.get((10, "positive_breadth_5d_pct"))
    if trend and turnover and breadth:
        lines.extend(
            [
                "- D-10 已出现板块级信号：概念 10 日涨幅正样本/对照中位数为 "
                f"`{_fmt_pct(trend.get('positive_median'))}/"
                f"{_fmt_pct(trend.get('control_median'))}`，AUC "
                f"`{_fmt_number(trend.get('rank_auc'))}`；成交额扩张为 "
                f"`{_fmt_number(turnover.get('positive_median'))}/"
                f"{_fmt_number(turnover.get('control_median'))}`，AUC "
                f"`{_fmt_number(turnover.get('rank_auc'))}`。",
                "- D-10 成员 5 日上涨宽度为 "
                f"`{_fmt_pct(breadth.get('positive_median'))}/"
                f"{_fmt_pct(breadth.get('control_median'))}`，AUC "
                f"`{_fmt_number(breadth.get('rank_auc'))}`；板块扩散在正式突破前已经存在。",
            ]
        )
    ignition = pooled_features.get((10, "ignition_share_5d_pct"))
    turnover_share = pooled_features.get((10, "top3_turnover_share_pct"))
    gain_concentration = pooled_features.get(
        (10, "top3_positive_gain_concentration_pct")
    )
    if ignition and turnover_share and gain_concentration:
        lines.append(
            "- 反例同样清楚：D-10 成员强势日点火占比 AUC 仅 "
            f"`{_fmt_number(ignition.get('rank_auc'))}`，配对中位差 "
            f"`{_fmt_pct(ignition.get('median_paired_difference'))}`；Top3 成交额占比和 "
            "Top3 正收益集中度 AUC 仅 "
            f"`{_fmt_number(turnover_share.get('rank_auc'))}/"
            f"{_fmt_number(gain_concentration.get('rank_auc'))}`。单日爆发或少数股票集中"
            "不是当前数据里的早期主信号。"
        )
    pooled_diffusion = [
        row for row in report["diffusion_metrics"] if row.get("scope") == "pooled"
    ]
    if pooled_diffusion:
        positive_retention = _metric_range(
            pooled_diffusion,
            "positive_leader_retained_top3_rate_pct",
        )
        control_retention = _metric_range(
            pooled_diffusion,
            "control_leader_retained_top3_rate_pct",
        )
        short_diffusion = _metric_range(
            [row for row in pooled_diffusion if row.get("future_days") in {3, 5}],
            "median_follower_return_difference_pct",
        )
        long_diffusion = _metric_range(
            [row for row in pooled_diffusion if row.get("future_days") == 10],
            "median_follower_return_difference_pct",
        )
        lines.extend(
            [
                "- 观察日 5 日涨幅龙头后续保持 Top3 仅 "
                f"`{_fmt_range(positive_retention, percent=True)}`，对照也有 "
                f"`{_fmt_range(control_retention, percent=True)}`；因此它只能作为时点排名，"
                "不能冻结为整段行情龙头，排名必须动态更新。",
                "- 跟随股相对对照的中位收益差在 +3/+5 为 "
                f"`{_fmt_range(short_diffusion, percent=True)}`，到 +10 收敛为 "
                f"`{_fmt_range(long_diffusion, percent=True)}`；当前证据更像短期扩散，"
                "不是长期龙头带动。",
            ]
        )
    late_trend = pooled_features.get((1, "concept_return_10d_pct"))
    if late_trend:
        lines.append(
            "- D-1 概念 10 日涨幅 AUC 升至 "
            f"`{_fmt_number(late_trend.get('rank_auc'))}`，但它紧邻机械定义的 20 日突破；"
            "D-10 结果才是更严格的早期证据，二者都只能进入未见时段复验。"
        )
    lines.append("")
    return lines


def _study_coverage(
    base: Mapping[str, object],
    *,
    events: pd.DataFrame,
    observations: pd.DataFrame,
    feature_panel: pd.DataFrame,
    early_member_ledger: pd.DataFrame,
    diffusion_outcomes: pd.DataFrame,
    feature_metrics: pd.DataFrame,
    diffusion_metrics: pd.DataFrame,
    diagnostics: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    complete_pair_ids = _complete_pair_ids(feature_panel)
    return {
        **base,
        "breakout_transition_events": int(len(events)),
        "sampled_breakout_events": int(observations["event_id"].nunique()),
        "observation_rows": int(len(observations)),
        "matched_pairs": len(complete_pair_ids),
        "matched_pairs_by_lead": {
            str(int(lead)): int(group.loc[group["pair_id"].isin(complete_pair_ids), "pair_id"].nunique())
            for lead, group in feature_panel.groupby("lead_days", sort=True)
        },
        "feature_panel_rows": int(len(feature_panel)),
        "early_member_ledger_rows": int(len(early_member_ledger)),
        "feature_metric_rows": int(len(feature_metrics)),
        "candidate_feature_count": sum(
            row.get("status") == "candidate_for_forward_validation"
            for row in diagnostics
        ),
        "diffusion_outcome_rows": int(len(diffusion_outcomes)),
        "diffusion_metric_rows": int(len(diffusion_metrics)),
    }


def _matched_examples(panel: pd.DataFrame) -> list[dict[str, object]]:
    required = (
        "pair_id",
        "lead_days",
        "sample_role",
        "sector_id",
        "concept_name",
        "breakout_date",
        "observation_date",
        "early_leader_symbol",
    )
    _require_columns(panel, required, "feature panel")
    complete_ids = _complete_pair_ids(panel)
    records: list[dict[str, object]] = []
    complete = panel.loc[panel["pair_id"].isin(complete_ids)].copy()
    for _, lead_rows in complete.groupby("lead_days", sort=True):
        pair_ids = sorted(lead_rows["pair_id"].astype(str).unique())[:2]
        for pair_id in pair_ids:
            pair = lead_rows.loc[lead_rows["pair_id"].astype(str).eq(pair_id)]
            positive = pair.loc[pair["sample_role"].eq("positive")].iloc[0]
            control = pair.loc[pair["sample_role"].eq("control")].iloc[0]
            records.append(
                {
                    "pair_id": pair_id,
                    "lead_days": int(positive["lead_days"]),
                    "sector_id": str(positive["sector_id"]),
                    "concept_name": str(positive["concept_name"]),
                    "breakout_date": positive["breakout_date"],
                    "positive_observation_date": positive["observation_date"],
                    "control_observation_date": control["observation_date"],
                    "positive_early_leader_symbol": str(positive["early_leader_symbol"]),
                    "control_early_leader_symbol": str(control["early_leader_symbol"]),
                }
            )
    return _json_safe(records)


def _normalized_observation_keys(observations: pd.DataFrame) -> pd.DataFrame:
    columns = ["pair_id", "sample_role", "sector_id", "observation_date"]
    frame = observations[columns].copy()
    frame["observation_date"] = pd.to_datetime(
        frame["observation_date"], errors="raise"
    ).dt.normalize()
    if frame.duplicated(["pair_id", "sample_role"]).any():
        raise ValueError("observation pair-role identities must be unique")
    return frame


def _normalized_early_leader_keys(ledger: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "pair_id",
        "sample_role",
        "observation_date",
        "vt_symbol",
        "early_leader",
    ]
    frame = ledger.loc[ledger["early_leader"].astype(bool), columns].copy()
    frame["observation_date"] = pd.to_datetime(
        frame["observation_date"], errors="raise"
    ).dt.normalize()
    if frame.duplicated(["pair_id", "sample_role"]).any():
        raise ValueError("early leader pair-role identities must be unique")
    return frame


def _dated_key_set(
    frame: pd.DataFrame,
    *,
    identity_column: str,
) -> set[tuple[str, pd.Timestamp]]:
    if frame.empty:
        return set()
    _require_columns(frame, (identity_column, "trade_date"), "fund coverage")
    dates = pd.to_datetime(frame["trade_date"], errors="raise").dt.normalize()
    return set(zip(frame[identity_column].astype(str), dates, strict=True))


def _complete_covered_pair_ids(frame: pd.DataFrame) -> set[str]:
    summary = frame.groupby("pair_id", sort=False).agg(
        roles=("sample_role", "nunique"),
        rows=("sample_role", "size"),
        covered=("covered", "all"),
    )
    return set(
        summary.index[
            summary["roles"].eq(2) & summary["rows"].eq(2) & summary["covered"]
        ].astype(str)
    )


def _complete_pair_ids(frame: pd.DataFrame) -> set[str]:
    summary = frame.groupby("pair_id", sort=False)["sample_role"].agg(
        roles="nunique",
        rows="size",
    )
    return set(summary.index[summary["roles"].eq(2) & summary["rows"].eq(2)].astype(str))


def _trade_date_count(frame: pd.DataFrame) -> int:
    if frame.empty or "trade_date" not in frame:
        return 0
    return int(pd.to_datetime(frame["trade_date"], errors="coerce").nunique())


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
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if pd.isna(value):
        return None
    return value


def _fmt_pct(value: object) -> str:
    number = _number_or_none(value)
    return "-" if number is None else f"{number:.4f}%"


def _fmt_number(value: object) -> str:
    number = _number_or_none(value)
    return "-" if number is None else f"{number:.4f}"


def _metric_range(
    rows: Sequence[Mapping[str, object]],
    key: str,
) -> tuple[float, float] | None:
    values = [_number_or_none(row.get(key)) for row in rows]
    finite = [value for value in values if value is not None]
    return (min(finite), max(finite)) if finite else None


def _fmt_range(
    value_range: tuple[float, float] | None,
    *,
    percent: bool,
) -> str:
    if value_range is None:
        return "-"
    suffix = "%" if percent else ""
    return f"{value_range[0]:.4f}..{value_range[1]:.4f}{suffix}"


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
