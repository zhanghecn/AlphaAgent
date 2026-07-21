"""Stock-by-stock audit of main-rise waves and close-price pullback entries."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.db.session import get_engine
from alphaagent.server.services.a_share_universe import is_eligible_main_board

from .leader_waves import build_leader_wave_ledger
from .research_protocol import fingerprint_frame
from .stock_wave_pullbacks import build_stock_wave_features, classify_volume_ratio


STUDY_VERSION = "individual-leader-wave-audit-v1"
MINIMUM_PULLBACK_PCT = 5.0
SUPPORT_APPROACH_TOLERANCE_PCT = 2.5
ROUND_TRIP_COST_PCT = 0.2
SUPPORT_DEPTH = {"ma5": 1, "ma10": 2, "ma20": 3}
CASE_HYPOTHESIS_DEFINITIONS = {
    "base_support_confirmation": "all audited support confirmations",
    "non_contraction_confirmation": "volume_ratio_prior5>=0.8",
    "up_close_non_contraction": (
        "signal_daily_return_pct>0 and volume_ratio_prior5>=0.8"
    ),
}


@dataclass(frozen=True)
class LeaderCampaignCase:
    campaign_id: str
    vt_symbol: str
    stock_name: str
    load_start: date
    campaign_start: date
    campaign_end: date
    evidence_end: date
    anchor_basis: str


CAMPAIGN_CASES = (
    LeaderCampaignCase(
        campaign_id="dongshan_2025_main_rise",
        vt_symbol="002384.SZSE",
        stock_name="东山精密",
        load_start=date(2025, 1, 2),
        campaign_start=date(2025, 6, 16),
        campaign_end=date(2025, 9, 24),
        evidence_end=date(2025, 10, 31),
        anchor_basis="user_inspected_then_price_volume_ignition_validated",
    ),
    LeaderCampaignCase(
        campaign_id="jinan_2026_main_rise",
        vt_symbol="002636.SZSE",
        stock_name="金安国纪",
        load_start=date(2025, 10, 1),
        campaign_start=date(2026, 1, 15),
        campaign_end=date(2026, 7, 6),
        evidence_end=date(2026, 7, 17),
        anchor_basis="user_inspected_then_price_volume_ignition_validated",
    ),
    LeaderCampaignCase(
        campaign_id="hengtong_2025_first_main_rise",
        vt_symbol="600487.SSE",
        stock_name="亨通光电",
        load_start=date(2025, 4, 1),
        campaign_start=date(2025, 8, 8),
        campaign_end=date(2025, 10, 14),
        evidence_end=date(2025, 12, 16),
        anchor_basis="price_volume_ignition_then_structural_reset_audit",
    ),
    LeaderCampaignCase(
        campaign_id="hengtong_2025_2026_second_main_rise",
        vt_symbol="600487.SSE",
        stock_name="亨通光电",
        load_start=date(2025, 9, 1),
        campaign_start=date(2025, 12, 17),
        campaign_end=date(2026, 7, 1),
        evidence_end=date(2026, 7, 17),
        anchor_basis="price_volume_reignition_after_structural_reset",
    ),
)


def _validate_campaign_cases(cases: Sequence[LeaderCampaignCase]) -> None:
    campaign_ids = [case.campaign_id for case in cases]
    if len(campaign_ids) != len(set(campaign_ids)):
        raise ValueError("campaign case ids must be unique")
    for case in cases:
        if not is_eligible_main_board(case.vt_symbol, case.stock_name):
            raise ValueError(
                f"campaign case must be an eligible main-board stock: {case.vt_symbol}"
            )
        if not (
            case.load_start
            <= case.campaign_start
            <= case.campaign_end
            <= case.evidence_end
        ):
            raise ValueError(f"campaign case dates are out of order: {case.campaign_id}")

    by_symbol: dict[str, list[LeaderCampaignCase]] = {}
    for case in cases:
        by_symbol.setdefault(case.vt_symbol, []).append(case)
    for symbol, symbol_cases in by_symbol.items():
        ordered = sorted(symbol_cases, key=lambda item: item.campaign_start)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current.campaign_start <= previous.campaign_end:
                raise ValueError(f"campaign cases overlap for {symbol}")


def find_price_volume_ignitions(
    features: pd.DataFrame,
    *,
    minimum_return_pct: float = 5.0,
    minimum_volume_ratio: float = 1.5,
) -> pd.DataFrame:
    """Find causal breakout candidates without requiring prior MA alignment."""

    required = (
        "trade_date",
        "close_price",
        "daily_return_pct",
        "prior_high20",
        "volume_ratio_prior5",
    )
    _require_columns(features, required, "price-volume ignition feature")
    frame = features.copy()
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    qualified = (
        pd.to_numeric(frame["daily_return_pct"], errors="coerce").ge(
            minimum_return_pct
        )
        & pd.to_numeric(frame["close_price"], errors="coerce").gt(
            pd.to_numeric(frame["prior_high20"], errors="coerce")
        )
        & pd.to_numeric(frame["volume_ratio_prior5"], errors="coerce").ge(
            minimum_volume_ratio
        )
    ).fillna(False)
    result = frame.loc[qualified].copy()
    result["price_volume_ignition"] = True
    result["ignition_definition"] = (
        "return>=5pct/close_above_prior20_high/volume>=1.5x"
    )
    return result.sort_values("trade_date", kind="stable").reset_index(drop=True)


def build_support_candidate_ledger(
    features: pd.DataFrame,
    waves: pd.DataFrame,
    *,
    approach_tolerance_pct: float = SUPPORT_APPROACH_TOLERANCE_PCT,
) -> pd.DataFrame:
    """List every causal support hold after a wave has pulled back at least 5%."""

    if not 0 <= approach_tolerance_pct <= 10:
        raise ValueError("support approach tolerance must be between zero and 10")
    bars = _prepare_features(features)
    wave_frame = _prepare_waves(waves)
    rows: list[dict[str, Any]] = []
    for wave in wave_frame.to_dict("records"):
        rows.extend(
            _support_candidates_for_wave(
                bars,
                wave,
                approach_tolerance_pct=approach_tolerance_pct,
            )
        )
    if not rows:
        return pd.DataFrame(columns=_candidate_columns())
    result = pd.DataFrame.from_records(rows, columns=_candidate_columns())
    if result.duplicated(
        ["campaign_id", "vt_symbol", "wave_number", "signal_date"]
    ).any():
        raise ValueError("support candidate identities must be unique")
    return result.sort_values(
        ["campaign_id", "wave_number", "signal_date"], kind="stable"
    ).reset_index(drop=True)


def execute_d1_loss_exit_trades(
    candidates: pd.DataFrame,
    features: pd.DataFrame,
    waves: pd.DataFrame,
    *,
    round_trip_cost_pct: float = ROUND_TRIP_COST_PCT,
) -> pd.DataFrame:
    """Exit a losing D+1 close and permit a later, newly confirmed entry."""

    if round_trip_cost_pct < 0:
        raise ValueError("round-trip cost cannot be negative")
    if candidates.empty:
        return pd.DataFrame(columns=_trade_columns())
    _require_columns(
        candidates,
        (
            "campaign_id",
            "vt_symbol",
            "wave_number",
            "signal_date",
            "signal_close",
            "support_line",
            "support_depth",
            "running_pullback_low",
            "reference_peak_price",
        ),
        "support candidate",
    )
    bars = _prepare_features(features)
    wave_frame = _prepare_waves(waves).set_index(
        ["campaign_id", "vt_symbol", "wave_number"], drop=False
    )
    candidate_frame = candidates.copy()
    candidate_frame["signal_date"] = pd.to_datetime(
        candidate_frame["signal_date"], errors="raise"
    ).dt.normalize()
    rows: list[dict[str, Any]] = []
    group_columns = ["campaign_id", "vt_symbol", "wave_number"]
    for identity, group in candidate_frame.groupby(group_columns, sort=False):
        if identity not in wave_frame.index:
            raise ValueError(f"support candidate has no matching wave: {identity}")
        wave = wave_frame.loc[identity]
        if isinstance(wave, pd.DataFrame):
            raise ValueError(f"wave identity is not unique: {identity}")
        rows.extend(
            _execute_wave_candidates(
                group,
                bars,
                wave.to_dict(),
                round_trip_cost_pct=round_trip_cost_pct,
            )
        )
    return pd.DataFrame.from_records(rows, columns=_trade_columns()).sort_values(
        ["entry_date", "campaign_id", "wave_number", "attempt_number"],
        kind="stable",
    ).reset_index(drop=True)


def build_case_hypothesis_replays(
    candidates: pd.DataFrame,
    features: pd.DataFrame,
    waves: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Replay case-derived candidate filters from the candidate ledger itself."""

    if candidates.empty:
        empty = execute_d1_loss_exit_trades(candidates, features, waves)
        return {name: empty.copy() for name in CASE_HYPOTHESIS_DEFINITIONS}
    _require_columns(
        candidates,
        ("signal_daily_return_pct", "signal_volume_ratio_prior5"),
        "case hypothesis candidate",
    )
    daily_return = pd.to_numeric(
        candidates["signal_daily_return_pct"], errors="coerce"
    )
    volume_ratio = pd.to_numeric(
        candidates["signal_volume_ratio_prior5"], errors="coerce"
    )
    masks = {
        "base_support_confirmation": pd.Series(True, index=candidates.index),
        "non_contraction_confirmation": volume_ratio.ge(0.8),
        "up_close_non_contraction": daily_return.gt(0) & volume_ratio.ge(0.8),
    }
    return {
        name: execute_d1_loss_exit_trades(candidates.loc[mask], features, waves)
        for name, mask in masks.items()
    }


def build_individual_leader_wave_report(
    *,
    campaign_summaries: pd.DataFrame,
    ignition_ledger: pd.DataFrame,
    daily_ledger: pd.DataFrame,
    wave_ledger: pd.DataFrame,
    support_candidates: pd.DataFrame,
    trades: pd.DataFrame,
    fingerprints: Mapping[str, Mapping[str, Any]],
    case_hypothesis_replays: Mapping[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """Build detailed case evidence without presenting it as population validation."""

    return _json_safe(
        {
            "study_version": STUDY_VERSION,
            "research_status": "individual_case_audit_complete",
            "formal_strategy": False,
            "formal_metrics": None,
            "invalidated_interpretation": (
                "main-rise-weak-to-strong-v6 pullback_opportunity_ordinal "
                "is not a true campaign wave number"
            ),
            "contracts": {
                "campaign_anchor": (
                    "user-inspected case anchor checked against a causal price-volume "
                    "ignition; not yet a production anchor selector"
                ),
                "wave_label": (
                    "ordered record high, later intraday pullback of at least 5%, "
                    "then a still-later higher high"
                ),
                "support_signal": (
                    "after the 5% pullback is visible, a completed close holds the "
                    "deepest approached MA5/MA10/MA20 and either closes in the upper "
                    "half of its range or not below the prior close"
                ),
                "entry": "signal-day completed close",
                "d1_exit": "exit D+1 close when cost-adjusted D+1 return is <=0",
                "positive_d1_exit": (
                    "otherwise exit at the first completed close after either the "
                    "reference peak is exceeded or the point-in-time structure breaks"
                ),
                "round_trip_cost_pct": ROUND_TRIP_COST_PCT,
            },
            "coverage": {
                "stocks": _nunique(campaign_summaries, "vt_symbol"),
                "campaigns": int(len(campaign_summaries)),
                "daily_rows": int(len(daily_ledger)),
                "pullback_daily_rows": int(
                    daily_ledger.get("pullback_active", pd.Series(dtype=bool))
                    .astype(bool)
                    .sum()
                ),
                "waves": int(len(wave_ledger)),
                "continued_waves": int(
                    wave_ledger.get("resolution_status", pd.Series(dtype=str))
                    .eq("continued_to_higher_high")
                    .sum()
                ),
                "support_candidates": int(len(support_candidates)),
                "executed_attempts": int(len(trades)),
                "closed_attempts": int(
                    trades.get("exit_date", pd.Series(dtype="datetime64[ns]"))
                    .notna()
                    .sum()
                ),
                "minute_rows_read": 0,
                "fund_flow_rows_read": 0,
                "old_low_suction_outcomes_read": 0,
            },
            "descriptive_trade_metrics": _trade_metrics(trades),
            "wave_sequence_summary": _records(
                _wave_sequence_summary(wave_ledger, trades)
            ),
            "candidate_feature_summaries": _candidate_feature_summaries(trades),
            "case_hypothesis_comparison": _case_hypothesis_comparison(
                wave_ledger,
                case_hypothesis_replays
                or {"base_support_confirmation": trades},
            ),
            "campaign_summaries": _records(campaign_summaries),
            "stock_summaries": _records(_stock_summaries(campaign_summaries, trades)),
            "ignition_ledger": _records(ignition_ledger),
            "wave_ledger": _records(wave_ledger),
            "support_candidate_ledger": _records(support_candidates),
            "trade_ledger": _records(trades),
            "daily_ledger": _records(daily_ledger),
            "loss_attribution": _records(_loss_attribution(trades)),
            "fingerprints": dict(fingerprints),
            "boundaries": [
                "The named stocks and campaign boundaries were already inspected by the user.",
                "Campaign end and wave resolution are retrospective labels; they never select D.",
                "The anchor rule is diagnosed here but is not yet validated across all leaders.",
                "These case metrics are not a population win rate or formal compound return.",
                "Case-hypothesis filters were proposed after inspecting these stocks and are replayed only to prevent post-filtering bias.",
                "Concept Top3 and GOLD/SILVER must be reattached only after this stock chronology is frozen.",
            ],
            "next_validation": (
                "Replace the old episode ordinal with this audited wave identity, then "
                "replay the unchanged close/D+1 contract and declared case hypotheses "
                "across all calculated historical leaders."
            ),
            "reproduce": (
                "docker compose run --rm --no-deps "
                "-v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api "
                "python -m alphaagent.server.services.low_suction.cli "
                "v2-individual-leader-wave-audit --format markdown"
            ),
        }
    )


def run_individual_leader_wave_audit() -> dict[str, Any]:
    """Run all declared individual campaign audits from PostgreSQL daily bars."""

    bars = _load_case_daily_bars(CAMPAIGN_CASES)
    campaign_parts: list[pd.DataFrame] = []
    ignition_parts: list[pd.DataFrame] = []
    daily_parts: list[pd.DataFrame] = []
    wave_parts: list[pd.DataFrame] = []
    candidate_parts: list[pd.DataFrame] = []
    trade_parts: list[pd.DataFrame] = []
    hypothesis_parts: dict[str, list[pd.DataFrame]] = {
        name: [] for name in CASE_HYPOTHESIS_DEFINITIONS
    }
    for case in CAMPAIGN_CASES:
        case_bars = bars.loc[
            bars["vt_symbol"].eq(case.vt_symbol)
            & bars["trade_date"].between(
                pd.Timestamp(case.load_start), pd.Timestamp(case.evidence_end)
            )
        ].copy()
        result = _audit_campaign(case, case_bars)
        campaign_parts.append(result["summary"])
        ignition_parts.append(result["ignitions"])
        daily_parts.append(result["daily"])
        wave_parts.append(result["waves"])
        candidate_parts.append(result["candidates"])
        trade_parts.append(result["trades"])
        for name, replay in result["case_hypothesis_replays"].items():
            hypothesis_parts[name].append(replay)

    campaigns = _concat(campaign_parts)
    ignitions = _concat(ignition_parts)
    daily = _concat(daily_parts)
    waves = _concat(wave_parts)
    candidates = _concat(candidate_parts)
    trades = _concat(trade_parts)
    case_hypothesis_replays = {
        name: _concat(parts) for name, parts in hypothesis_parts.items()
    }
    _assert_real_case_landmarks(campaigns, daily, candidates)
    fingerprints = {
        "source_daily_bars": fingerprint_frame(
            bars, identity_columns=("vt_symbol", "trade_date")
        ).as_dict(),
        "campaigns": fingerprint_frame(
            campaigns, identity_columns=("campaign_id",)
        ).as_dict(),
        "waves": fingerprint_frame(
            waves, identity_columns=("campaign_id", "wave_number")
        ).as_dict(),
        "support_candidates": fingerprint_frame(
            candidates,
            identity_columns=(
                "campaign_id",
                "wave_number",
                "signal_date",
            ),
        ).as_dict(),
        "trades": fingerprint_frame(
            trades,
            identity_columns=("campaign_id", "wave_number", "attempt_number"),
        ).as_dict(),
    }
    for name, replay in case_hypothesis_replays.items():
        fingerprints[f"case_hypothesis_{name}"] = fingerprint_frame(
            replay,
            identity_columns=("campaign_id", "wave_number", "attempt_number"),
        ).as_dict()
    return build_individual_leader_wave_report(
        campaign_summaries=campaigns,
        ignition_ledger=ignitions,
        daily_ledger=daily,
        wave_ledger=waves,
        support_candidates=candidates,
        trades=trades,
        fingerprints=fingerprints,
        case_hypothesis_replays=case_hypothesis_replays,
    )


def render_individual_leader_wave_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"


def render_individual_leader_wave_markdown(report: Mapping[str, Any]) -> str:
    coverage = _mapping(report.get("coverage"))
    metrics = _mapping(report.get("descriptive_trade_metrics"))
    lines = [
        "# AlphaAgent 三只主升龙头逐股逐浪审计",
        "",
        f"状态：`{report.get('research_status')}`；正式策略：`false`；正式绩效：`null`。",
        "",
        "## 先纠正旧结论",
        "",
        "`main-rise-weak-to-strong-v6.pullback_opportunity_ordinal` 不是完整主升波段号。",
        "它从算法较晚的 episode 起点编号，因此金安国纪 `2026-01-30` 被误写成第一次，",
        "实际属于从 `2026-01-15` 开始的第 2 浪。旧总体表不能继续解释真实低吸位置。",
        "",
        "## Coverage",
        "",
        f"- 股票 `{coverage.get('stocks', 0)}`；主升 campaign `{coverage.get('campaigns', 0)}`；"
        f"完整波段 `{coverage.get('waves', 0)}`；其中再创新高 `{coverage.get('continued_waves', 0)}`。",
        f"- 支撑站稳候选 `{coverage.get('support_candidates', 0)}`；顺序执行 "
        f"`{coverage.get('executed_attempts', 0)}` 笔。分钟线、资金流、旧低吸结果均未读取。",
        f"- 逐日账本 `{coverage.get('daily_rows', 0)}` 行，其中回调路径 "
        f"`{coverage.get('pullback_daily_rows', 0)}` 行；每行保留当日支撑区、最深支撑和是否形成候选。",
        "",
        "## Campaigns",
        "",
        "| 股票 | 区间 | 波段 | 再创新高 | 终止浪 | 起点到最高 | 候选 | 交易 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        *_campaign_lines(report.get("campaign_summaries")),
        "",
        "亨通光电从 `2025-08-08` 连续按记录高点看共 17 浪；但 `2025-10-14` 已发生",
        "明确结构重置，所以审计拆成前 4 浪和 `2025-12-17` 再点火后的 13 浪。",
        "",
        "## D+1 亏损退出结果",
        "",
        f"- 闭合 `{metrics.get('closed_trades', 0)}` 笔；成本后正收益比例 "
        f"`{_percent(metrics.get('positive_rate_pct'))}`；均值 "
        f"`{_percent(metrics.get('mean_net_return_pct'))}`。",
        f"- D+1 止损 `{metrics.get('d1_loss_stops', 0)}` 笔；其中后来该浪仍创新高 "
        f"`{metrics.get('d1_stops_before_later_higher_high', 0)}` 笔。后者不是主升判断错误，"
        "而是第一次支撑站稳过早。",
        "",
        "| 原因 | 笔数 | 均值 | 后来创新高 |",
        "| --- | ---: | ---: | ---: |",
        *_loss_lines(report.get("loss_attribution")),
        "",
        "## 波段级顺序结果",
        "",
        "同一浪可以先 D+1 止损、后重新站稳再买；下表把这些尝试按时间复合成一个波段结果。",
        "",
        "| 波段组 | 全部波段 | 有入场 | 盈利波段 | 有入场胜率 | 平均波段净收益 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        *_wave_sequence_lines(report.get("wave_sequence_summary")),
        "",
        "## 当日特征对照",
        "",
        "这些分组来自已经看过的三只股票，只用于提出下一轮全体历史假设。",
        "",
        "| 维度 | 分组 | N | 胜率 | 均值 |",
        "| --- | --- | ---: | ---: | ---: |",
        *_feature_summary_lines(report.get("candidate_feature_summaries")),
        "",
        "## 案例后假设的正确重放",
        "",
        "下面三行先过滤原始候选、再从头顺序执行，不能从基础交易结果中事后挑选。",
        "这些股票已经被查看，只能用于确定下一轮假设，不能发布为历史胜率。",
        "",
        "| 案例假设 | 交易 | 单次胜率 | 均值 | 入场波段 | 波段胜率 | 包含东山 07-02 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
        *_case_hypothesis_lines(report.get("case_hypothesis_comparison")),
        "",
        "`up_close_non_contraction` 会排除用户确认有效的东山精密 `2025-07-02`，",
        "即使案例内数字更高，也不能把“D 日必须收涨”定成最终规则。",
        "",
        "## 完整波段账本",
        "",
        "| 股票/campaign | 浪 | 峰值 | 首次 5% 回调 | 最低点/支撑 | 再创新高 | 结构破坏 | 结果 |",
        "| --- | ---: | --- | --- | --- | --- | --- | --- |",
        *_wave_lines(report.get("wave_ledger")),
        "",
        "## 每次实际入场与退出",
        "",
        "| 股票 | 浪/尝试 | D 收盘买 | 支撑 | D+1 | 退出 | 净收益 | 后来创新高 | 归因 |",
        "| --- | --- | --- | --- | ---: | --- | ---: | --- | --- |",
        *_trade_lines(report.get("trade_ledger")),
        "",
        "## 研究边界",
        "",
        *[f"- {item}" for item in _sequence(report.get("boundaries"))],
        "",
        "下一步：" + str(report.get("next_validation") or ""),
        "",
        "## Reproduce",
        "",
        "```bash",
        str(report.get("reproduce") or ""),
        "```",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _audit_campaign(
    case: LeaderCampaignCase,
    daily_bars: pd.DataFrame,
) -> dict[str, Any]:
    features = _case_features(daily_bars, case.vt_symbol)
    anchor = pd.Timestamp(case.campaign_start)
    boundary = pd.Timestamp(case.campaign_end)
    evidence_end = pd.Timestamp(case.evidence_end)
    anchor_row = _one_bar(features, anchor, "campaign anchor")
    _one_bar(features, boundary, "campaign end")
    if pd.isna(anchor_row["ma60"]):
        raise ValueError(f"campaign anchor lacks MA60 history: {case.campaign_id}")

    ignitions = find_price_volume_ignitions(features)
    anchor_is_ignition = bool(ignitions["trade_date"].eq(anchor).any())
    if not anchor_is_ignition:
        raise ValueError(f"campaign anchor is not a price-volume ignition: {case.campaign_id}")
    ignitions = ignitions.loc[
        ignitions["trade_date"].between(anchor, boundary)
    ].copy()
    ignitions["campaign_id"] = case.campaign_id
    ignitions["vt_symbol"] = case.vt_symbol
    ignitions["stock_name"] = case.stock_name

    waves = build_leader_wave_ledger(
        features,
        anchor_date=case.campaign_start,
        observation_end=case.campaign_end,
        minimum_pullback_pct=MINIMUM_PULLBACK_PCT,
    )
    waves = _enrich_waves(case, waves, features)
    _assert_wave_rows_match_bars(waves, features)
    candidates = build_support_candidate_ledger(features, waves)
    candidates.insert(2, "stock_name", case.stock_name)
    case_hypothesis_replays = build_case_hypothesis_replays(
        candidates,
        features,
        waves,
    )
    for replay in case_hypothesis_replays.values():
        replay.insert(2, "stock_name", case.stock_name)
    trades = case_hypothesis_replays["base_support_confirmation"]
    daily = _daily_campaign_ledger(case, features, waves, candidates)
    summary = _campaign_summary(
        case,
        features,
        waves,
        candidates,
        trades,
        anchor_is_ignition=anchor_is_ignition,
    )
    if evidence_end not in set(features["trade_date"]):
        raise ValueError(f"campaign evidence end has no daily bar: {case.campaign_id}")
    return {
        "summary": pd.DataFrame([summary]),
        "ignitions": ignitions,
        "daily": daily,
        "waves": waves,
        "candidates": candidates,
        "trades": trades,
        "case_hypothesis_replays": case_hypothesis_replays,
    }


def _case_features(daily_bars: pd.DataFrame, vt_symbol: str) -> pd.DataFrame:
    features = build_stock_wave_features(daily_bars)
    features["ma60"] = features["close_price"].rolling(60, min_periods=60).mean()
    features["close_location"] = (
        (features["close_price"] - features["low_price"])
        / (features["high_price"] - features["low_price"]).replace(0.0, np.nan)
    ).fillna(0.5)
    below_ma10 = features["close_price"].lt(features["ma10"])
    features["structural_break"] = features["close_price"].lt(features["ma20"]) | (
        below_ma10
        & below_ma10.shift(1, fill_value=False)
        & features["ma5"].le(features["ma10"])
    )
    features["vt_symbol"] = vt_symbol
    return features


def _prepare_features(features: pd.DataFrame) -> pd.DataFrame:
    required = (
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "ma5",
        "ma10",
        "ma20",
    )
    _require_columns(features, required, "individual leader daily feature")
    frame = features.copy()
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], errors="raise"
    ).dt.normalize()
    if frame["trade_date"].duplicated().any():
        raise ValueError("individual leader daily dates must be unique")
    if "vt_symbol" not in frame:
        frame["vt_symbol"] = ""
    if "daily_return_pct" not in frame:
        frame["daily_return_pct"] = frame["close_price"].pct_change() * 100.0
    if "volume_ratio_prior5" not in frame:
        prior_volume = frame["volume"].shift(1).rolling(5, min_periods=5).median()
        frame["volume_ratio_prior5"] = frame["volume"] / prior_volume.replace(0, np.nan)
    if "close_location" not in frame:
        spread = (frame["high_price"] - frame["low_price"]).replace(0.0, np.nan)
        frame["close_location"] = (
            (frame["close_price"] - frame["low_price"]) / spread
        ).fillna(0.5)
    if "structural_break" not in frame:
        below_ma10 = frame["close_price"].lt(frame["ma10"])
        frame["structural_break"] = frame["close_price"].lt(frame["ma20"]) | (
            below_ma10
            & below_ma10.shift(1, fill_value=False)
            & frame["ma5"].le(frame["ma10"])
        )
    return frame.sort_values("trade_date", kind="stable").reset_index(drop=True)


def _prepare_waves(waves: pd.DataFrame) -> pd.DataFrame:
    required = (
        "campaign_id",
        "vt_symbol",
        "wave_number",
        "wave_start_date",
        "peak_date",
        "peak_price",
        "higher_high_date",
        "structural_break_date",
        "resolution_status",
        "observation_end",
    )
    _require_columns(waves, required, "individual leader wave")
    frame = waves.copy()
    for column in (
        "wave_start_date",
        "peak_date",
        "higher_high_date",
        "structural_break_date",
        "observation_end",
    ):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.normalize()
    frame["wave_number"] = pd.to_numeric(
        frame["wave_number"], errors="raise"
    ).astype(int)
    if frame.duplicated(["campaign_id", "vt_symbol", "wave_number"]).any():
        raise ValueError("individual leader wave identities must be unique")
    return frame.sort_values(
        ["campaign_id", "wave_number"], kind="stable"
    ).reset_index(drop=True)


def _support_candidates_for_wave(
    bars: pd.DataFrame,
    wave: Mapping[str, Any],
    *,
    approach_tolerance_pct: float,
) -> list[dict[str, Any]]:
    peak_date = pd.Timestamp(wave["peak_date"])
    higher_high_date = wave.get("higher_high_date")
    boundary = pd.Timestamp(wave["observation_end"])
    before_resolution = bars["trade_date"].le(boundary)
    if higher_high_date is not None and not pd.isna(higher_high_date):
        before_resolution = bars["trade_date"].lt(pd.Timestamp(higher_high_date))
    window = bars.loc[bars["trade_date"].gt(peak_date) & before_resolution].copy()
    if window.empty:
        return []
    peak_price = float(wave["peak_price"])
    confirmation_mask = window["low_price"].le(
        peak_price * (1.0 - MINIMUM_PULLBACK_PCT / 100.0)
    )
    if not confirmation_mask.any():
        return []
    confirmation_date = pd.Timestamp(window.loc[confirmation_mask, "trade_date"].iloc[0])
    running_low = np.inf
    deepest_support: str | None = None
    rows: list[dict[str, Any]] = []
    ordered = bars.reset_index(drop=True)
    positions = {pd.Timestamp(value): index for index, value in enumerate(ordered["trade_date"])}
    for bar in window.loc[window["trade_date"].ge(confirmation_date)].itertuples(
        index=False
    ):
        trade_date = pd.Timestamp(bar.trade_date)
        position = positions[trade_date]
        running_low = min(running_low, float(bar.low_price))
        approached = _approached_supports(bar, approach_tolerance_pct)
        if approached:
            deepest_today = max(approached, key=SUPPORT_DEPTH.__getitem__)
            if (
                deepest_support is None
                or SUPPORT_DEPTH[deepest_today] > SUPPORT_DEPTH[deepest_support]
            ):
                deepest_support = deepest_today
        if deepest_support is None or bool(bar.structural_break):
            continue
        support_price = _finite_or_none(getattr(bar, deepest_support))
        if support_price is None or float(bar.close_price) < support_price:
            continue
        previous = ordered.iloc[position - 1] if position > 0 else None
        structure_reclaimed_today = bool(
            previous is not None
            and bool(previous["structural_break"])
            and not bool(bar.structural_break)
        )
        previous_close = (
            float(previous["close_price"]) if previous is not None else float(bar.close_price)
        )
        previous_support = (
            _finite_or_none(previous[deepest_support]) if previous is not None else None
        )
        reclaimed_today = bool(
            previous_support is not None
            and previous_close < previous_support
            and float(bar.close_price) >= support_price
        )
        approached_today = deepest_support in approached
        closes_well = bool(
            float(bar.close_location) >= 0.5
            or float(bar.close_price) >= previous_close
        )
        if not closes_well or not (
            approached_today or reclaimed_today or structure_reclaimed_today
        ):
            continue
        rows.append(
            {
                "campaign_id": str(wave["campaign_id"]),
                "vt_symbol": str(wave["vt_symbol"]),
                "wave_number": int(wave["wave_number"]),
                "signal_date": trade_date,
                "pullback_confirmation_date": confirmation_date,
                "reference_peak_date": peak_date,
                "reference_peak_price": peak_price,
                "support_line": deepest_support,
                "support_depth": SUPPORT_DEPTH[deepest_support],
                "support_price": support_price,
                "signal_open": float(bar.open_price),
                "signal_high": float(bar.high_price),
                "signal_low": float(bar.low_price),
                "signal_close": float(bar.close_price),
                "signal_daily_return_pct": _finite_or_none(bar.daily_return_pct),
                "signal_volume_ratio_prior5": _finite_or_none(
                    bar.volume_ratio_prior5
                ),
                "signal_volume_class": classify_volume_ratio(
                    bar.volume_ratio_prior5
                ),
                "close_location": float(bar.close_location),
                "signal_close_not_below_previous": bool(
                    float(bar.close_price) >= previous_close
                ),
                "approached_support_today": approached_today,
                "reclaimed_support_today": reclaimed_today,
                "structure_reclaimed_today": structure_reclaimed_today,
                "running_pullback_low": float(running_low),
                "running_drawdown_pct": (float(running_low) / peak_price - 1.0)
                * 100.0,
                "feature_cutoff_date": trade_date,
            }
        )
    return rows


def _approached_supports(bar: Any, tolerance_pct: float) -> list[str]:
    for line in SUPPORT_DEPTH:
        support = _finite_or_none(getattr(bar, line))
        if support is not None and float(bar.low_price) >= support * (
            1.0 - tolerance_pct / 100.0
        ):
            return [line]
    return ["ma20"]


def _execute_wave_candidates(
    candidates: pd.DataFrame,
    bars: pd.DataFrame,
    wave: Mapping[str, Any],
    *,
    round_trip_cost_pct: float,
) -> list[dict[str, Any]]:
    ordered = bars.reset_index(drop=True)
    positions = {pd.Timestamp(value): index for index, value in enumerate(ordered["trade_date"])}
    previous_exit: pd.Timestamp | None = None
    attempts: list[dict[str, Any]] = []
    for candidate in candidates.sort_values("signal_date", kind="stable").to_dict(
        "records"
    ):
        signal_date = pd.Timestamp(candidate["signal_date"])
        if previous_exit is not None and signal_date <= previous_exit:
            continue
        attempt = _execute_candidate(
            candidate,
            ordered,
            positions,
            wave,
            attempt_number=len(attempts) + 1,
            round_trip_cost_pct=round_trip_cost_pct,
        )
        attempts.append(attempt)
        exit_date = attempt.get("exit_date")
        if exit_date is None or pd.isna(exit_date):
            break
        previous_exit = pd.Timestamp(exit_date)
        if attempt["exit_reason"] != "d1_loss_stop":
            break
    return attempts


def _execute_candidate(
    candidate: Mapping[str, Any],
    bars: pd.DataFrame,
    positions: Mapping[pd.Timestamp, int],
    wave: Mapping[str, Any],
    *,
    attempt_number: int,
    round_trip_cost_pct: float,
) -> dict[str, Any]:
    entry_date = pd.Timestamp(candidate["signal_date"])
    entry_position = positions.get(entry_date)
    if entry_position is None:
        raise ValueError("support candidate date has no daily bar")
    entry_price = float(candidate["signal_close"])
    d1_position = entry_position + 1
    if d1_position >= len(bars):
        return _censored_trade(candidate, wave, attempt_number, entry_date, entry_price)
    d1 = bars.iloc[d1_position]
    d1_date = pd.Timestamp(d1["trade_date"])
    d1_close = float(d1["close_price"])
    d1_net_return = _net_return(entry_price, d1_close, round_trip_cost_pct)
    if d1_net_return <= 0:
        exit_row = d1
        exit_reason = "d1_loss_stop"
        exit_causality = "point_in_time_d1_close"
    else:
        exit_row, exit_reason = _positive_d1_exit(
            bars,
            wave,
            entry_date=entry_date,
            reference_peak=float(candidate["reference_peak_price"]),
        )
        exit_causality = (
            "point_in_time_reference_peak_target"
            if exit_reason == "higher_high_confirmed"
            else (
                "point_in_time_structural_break"
                if exit_reason == "structural_break"
                else "right_censored"
            )
        )
    exit_date = pd.Timestamp(exit_row["trade_date"]) if exit_row is not None else pd.NaT
    exit_price = float(exit_row["close_price"]) if exit_row is not None else None
    path_end = exit_date if not pd.isna(exit_date) else pd.Timestamp(wave["observation_end"])
    path = bars.loc[bars["trade_date"].between(entry_date, path_end)]
    later_higher_high = _later_higher_high(
        bars,
        after_date=exit_date if not pd.isna(exit_date) else entry_date,
        through_date=pd.Timestamp(wave["observation_end"]),
        reference_peak=float(candidate["reference_peak_price"]),
    )
    net_return = (
        _net_return(entry_price, exit_price, round_trip_cost_pct)
        if exit_price is not None
        else None
    )
    result = {
        "campaign_id": str(candidate["campaign_id"]),
        "vt_symbol": str(candidate["vt_symbol"]),
        "wave_number": int(candidate["wave_number"]),
        "attempt_number": attempt_number,
        "entry_date": entry_date,
        "entry_price": entry_price,
        "support_line": str(candidate["support_line"]),
        "support_depth": int(candidate["support_depth"]),
        "running_pullback_low_at_entry": float(candidate["running_pullback_low"]),
        "reference_peak_price": float(candidate["reference_peak_price"]),
        "d1_date": d1_date,
        "d1_close": d1_close,
        "d1_net_return_pct": d1_net_return,
        "d1_loss_exit_triggered": bool(d1_net_return <= 0),
        "signal_daily_return_pct": _finite_or_none(
            candidate.get("signal_daily_return_pct")
        ),
        "signal_volume_ratio_prior5": _finite_or_none(
            candidate.get("signal_volume_ratio_prior5")
        ),
        "signal_volume_class": candidate.get("signal_volume_class"),
        "signal_close_location": _finite_or_none(candidate.get("close_location")),
        "signal_close_not_below_previous": bool(
            candidate.get("signal_close_not_below_previous", False)
        ),
        "approached_support_today": bool(
            candidate.get("approached_support_today", False)
        ),
        "reclaimed_support_today": bool(
            candidate.get("reclaimed_support_today", False)
        ),
        "structure_reclaimed_today": bool(
            candidate.get("structure_reclaimed_today", False)
        ),
        "exit_date": exit_date,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "exit_causality": exit_causality,
        "holding_sessions": int(len(path) - 1) if exit_price is not None else None,
        "net_return_pct": net_return,
        "mfe_pct": (
            (float(path["high_price"].max()) / entry_price - 1.0) * 100.0
            if not path.empty
            else None
        ),
        "mae_pct": (
            (float(path["low_price"].min()) / entry_price - 1.0) * 100.0
            if not path.empty
            else None
        ),
        "wave_resolution_status": str(wave["resolution_status"]),
        "wave_higher_high_date": wave.get("higher_high_date"),
        "later_higher_high_after_exit": later_higher_high,
        "loss_cause": None,
    }
    result["loss_cause"] = _loss_cause(result)
    return result


def _positive_d1_exit(
    bars: pd.DataFrame,
    wave: Mapping[str, Any],
    *,
    entry_date: pd.Timestamp,
    reference_peak: float,
) -> tuple[pd.Series | None, str]:
    boundary = pd.Timestamp(wave["observation_end"])
    path = bars.loc[
        bars["trade_date"].gt(entry_date) & bars["trade_date"].le(boundary)
    ]
    if path.empty:
        return None, "right_censored"
    higher_high = path.loc[path["high_price"].gt(reference_peak)]
    structural_break = path.loc[path["structural_break"].astype(bool)]
    higher_high_row = higher_high.iloc[0] if not higher_high.empty else None
    structural_break_row = (
        structural_break.iloc[0] if not structural_break.empty else None
    )
    if higher_high_row is not None and (
        structural_break_row is None
        or pd.Timestamp(higher_high_row["trade_date"])
        <= pd.Timestamp(structural_break_row["trade_date"])
    ):
        return higher_high_row, "higher_high_confirmed"
    if structural_break_row is not None:
        return structural_break_row, "structural_break"
    return None, "right_censored"


def _later_higher_high(
    bars: pd.DataFrame,
    *,
    after_date: pd.Timestamp,
    through_date: pd.Timestamp,
    reference_peak: float,
) -> bool:
    path = bars.loc[
        bars["trade_date"].gt(after_date) & bars["trade_date"].le(through_date)
    ]
    return bool(path["high_price"].gt(reference_peak).any())


def _loss_cause(trade: Mapping[str, Any]) -> str | None:
    net_return = _finite_or_none(trade.get("net_return_pct"))
    if net_return is None:
        return "right_censored"
    if net_return > 0:
        return None
    if bool(trade.get("later_higher_high_after_exit")):
        return "entry_too_early"
    if trade.get("wave_resolution_status") == "terminal_failure_observed":
        return "terminal_wave"
    if bool(trade.get("d1_loss_exit_triggered")):
        return "support_failed_next_day"
    return "support_failed_next_day"


def _censored_trade(
    candidate: Mapping[str, Any],
    wave: Mapping[str, Any],
    attempt_number: int,
    entry_date: pd.Timestamp,
    entry_price: float,
) -> dict[str, Any]:
    return {
        "campaign_id": str(candidate["campaign_id"]),
        "vt_symbol": str(candidate["vt_symbol"]),
        "wave_number": int(candidate["wave_number"]),
        "attempt_number": attempt_number,
        "entry_date": entry_date,
        "entry_price": entry_price,
        "support_line": str(candidate["support_line"]),
        "support_depth": int(candidate["support_depth"]),
        "running_pullback_low_at_entry": float(candidate["running_pullback_low"]),
        "reference_peak_price": float(candidate["reference_peak_price"]),
        "d1_date": pd.NaT,
        "d1_close": None,
        "d1_net_return_pct": None,
        "d1_loss_exit_triggered": False,
        "signal_daily_return_pct": _finite_or_none(
            candidate.get("signal_daily_return_pct")
        ),
        "signal_volume_ratio_prior5": _finite_or_none(
            candidate.get("signal_volume_ratio_prior5")
        ),
        "signal_volume_class": candidate.get("signal_volume_class"),
        "signal_close_location": _finite_or_none(candidate.get("close_location")),
        "signal_close_not_below_previous": bool(
            candidate.get("signal_close_not_below_previous", False)
        ),
        "approached_support_today": bool(
            candidate.get("approached_support_today", False)
        ),
        "reclaimed_support_today": bool(
            candidate.get("reclaimed_support_today", False)
        ),
        "structure_reclaimed_today": bool(
            candidate.get("structure_reclaimed_today", False)
        ),
        "exit_date": pd.NaT,
        "exit_price": None,
        "exit_reason": "right_censored",
        "exit_causality": "right_censored",
        "holding_sessions": None,
        "net_return_pct": None,
        "mfe_pct": None,
        "mae_pct": None,
        "wave_resolution_status": str(wave["resolution_status"]),
        "wave_higher_high_date": wave.get("higher_high_date"),
        "later_higher_high_after_exit": False,
        "loss_cause": "right_censored",
    }


def _enrich_waves(
    case: LeaderCampaignCase,
    waves: pd.DataFrame,
    features: pd.DataFrame,
) -> pd.DataFrame:
    result = waves.copy()
    result.insert(0, "campaign_id", case.campaign_id)
    result.insert(1, "vt_symbol", case.vt_symbol)
    result.insert(2, "stock_name", case.stock_name)
    confirmations: list[pd.Timestamp | pd.NaT] = []
    break_dates: list[pd.Timestamp | pd.NaT] = []
    for wave in result.to_dict("records"):
        peak_date = pd.Timestamp(wave["peak_date"])
        higher_high_date = wave.get("higher_high_date")
        boundary = pd.Timestamp(wave["observation_end"])
        before_end = features["trade_date"].le(boundary)
        if higher_high_date is not None and not pd.isna(higher_high_date):
            before_end = features["trade_date"].lt(pd.Timestamp(higher_high_date))
        path = features.loc[features["trade_date"].gt(peak_date) & before_end]
        confirmed = path.loc[
            path["low_price"].le(float(wave["peak_price"]) * 0.95), "trade_date"
        ]
        breaks = path.loc[path["structural_break"], "trade_date"]
        confirmations.append(
            pd.Timestamp(confirmed.iloc[0]) if not confirmed.empty else pd.NaT
        )
        break_dates.append(pd.Timestamp(breaks.iloc[0]) if not breaks.empty else pd.NaT)
    result["pullback_confirmation_date"] = confirmations
    result["first_structural_break_in_pullback"] = break_dates
    return result


def _assert_wave_rows_match_bars(
    waves: pd.DataFrame,
    features: pd.DataFrame,
) -> None:
    for wave in waves.to_dict("records"):
        peak_date = pd.Timestamp(wave["peak_date"])
        peak_price = float(wave["peak_price"])
        peak_bar = _one_bar(features, peak_date, "wave peak")
        if not np.isclose(float(peak_bar["high_price"]), peak_price):
            raise ValueError("wave peak price does not match its daily bar")

        higher_high_date = wave.get("higher_high_date")
        boundary = pd.Timestamp(wave["observation_end"])
        pullback_end = (
            pd.Timestamp(higher_high_date)
            if higher_high_date is not None and not pd.isna(higher_high_date)
            else boundary
        )
        pullback = features.loc[
            features["trade_date"].gt(peak_date)
            & features["trade_date"].le(pullback_end)
        ]
        confirmed = pullback.loc[
            pullback["low_price"].le(peak_price * 0.95), "trade_date"
        ]
        expected_confirmation = (
            pd.Timestamp(confirmed.iloc[0]) if not confirmed.empty else pd.NaT
        )
        observed_confirmation = wave.get("pullback_confirmation_date")
        if not _same_optional_date(expected_confirmation, observed_confirmation):
            raise ValueError("wave pullback confirmation does not match daily bars")

        trough_date = wave.get("trough_date")
        if trough_date is not None and not pd.isna(trough_date):
            trough_bar = _one_bar(
                features,
                pd.Timestamp(trough_date),
                "wave trough",
            )
            if not np.isclose(
                float(trough_bar["low_price"]),
                float(wave["trough_price"]),
            ):
                raise ValueError("wave trough price does not match its daily bar")
        if higher_high_date is not None and not pd.isna(higher_high_date):
            higher_high = pd.Timestamp(higher_high_date)
            recovery = features.loc[
                features["trade_date"].gt(pd.Timestamp(trough_date))
                & features["trade_date"].le(higher_high)
                & features["high_price"].gt(peak_price),
                "trade_date",
            ]
            if recovery.empty or pd.Timestamp(recovery.iloc[0]) != higher_high:
                raise ValueError("wave higher high is not the first daily recovery")


def _daily_campaign_ledger(
    case: LeaderCampaignCase,
    features: pd.DataFrame,
    waves: pd.DataFrame,
    candidates: pd.DataFrame,
) -> pd.DataFrame:
    start = pd.Timestamp(case.campaign_start)
    boundary = pd.Timestamp(case.campaign_end)
    daily = features.loc[features["trade_date"].between(start, boundary)].copy()
    daily["campaign_id"] = case.campaign_id
    daily["stock_name"] = case.stock_name
    daily["wave_number"] = pd.Series(pd.NA, index=daily.index, dtype="Int64")
    daily["pullback_active"] = False
    daily["support_zone_today"] = pd.Series(None, index=daily.index, dtype="object")
    daily["deepest_support_seen"] = pd.Series(None, index=daily.index, dtype="object")
    daily["support_close_held"] = False
    daily["support_candidate"] = False
    for wave in waves.sort_values("wave_number").to_dict("records"):
        wave_start = pd.Timestamp(wave["wave_start_date"])
        wave_end = wave.get("higher_high_date")
        wave_end = (
            pd.Timestamp(wave_end)
            if wave_end is not None and not pd.isna(wave_end)
            else boundary
        )
        daily.loc[
            daily["trade_date"].between(wave_start, wave_end), "wave_number"
        ] = int(wave["wave_number"])
        confirmation_date = wave.get("pullback_confirmation_date")
        if confirmation_date is None or pd.isna(confirmation_date):
            continue
        pullback_end = wave.get("higher_high_date")
        pullback_mask = daily["trade_date"].ge(pd.Timestamp(confirmation_date))
        if pullback_end is not None and not pd.isna(pullback_end):
            pullback_mask &= daily["trade_date"].lt(pd.Timestamp(pullback_end))
        else:
            pullback_mask &= daily["trade_date"].le(boundary)
        deepest_support: str | None = None
        for bar in daily.loc[pullback_mask].itertuples():
            support_zone = _approached_supports(
                bar,
                SUPPORT_APPROACH_TOLERANCE_PCT,
            )[0]
            if (
                deepest_support is None
                or SUPPORT_DEPTH[support_zone] > SUPPORT_DEPTH[deepest_support]
            ):
                deepest_support = support_zone
            support_price = _finite_or_none(getattr(bar, deepest_support))
            daily.at[bar.Index, "pullback_active"] = True
            daily.at[bar.Index, "support_zone_today"] = support_zone
            daily.at[bar.Index, "deepest_support_seen"] = deepest_support
            daily.at[bar.Index, "support_close_held"] = bool(
                support_price is not None and float(bar.close_price) >= support_price
            )
    if not candidates.empty:
        candidate_dates = pd.to_datetime(
            candidates["signal_date"], errors="raise"
        ).dt.normalize()
        daily.loc[daily["trade_date"].isin(candidate_dates), "support_candidate"] = True
    columns = (
        "campaign_id",
        "vt_symbol",
        "stock_name",
        "trade_date",
        "wave_number",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "daily_return_pct",
        "ma5",
        "ma10",
        "ma20",
        "ma60",
        "volume",
        "volume_ratio_prior5",
        "close_location",
        "structural_break",
        "pullback_active",
        "support_zone_today",
        "deepest_support_seen",
        "support_close_held",
        "support_candidate",
    )
    return daily.loc[:, list(columns)].reset_index(drop=True)


def _campaign_summary(
    case: LeaderCampaignCase,
    features: pd.DataFrame,
    waves: pd.DataFrame,
    candidates: pd.DataFrame,
    trades: pd.DataFrame,
    *,
    anchor_is_ignition: bool,
) -> dict[str, Any]:
    anchor = _one_bar(features, pd.Timestamp(case.campaign_start), "campaign anchor")
    campaign = features.loc[
        features["trade_date"].between(
            pd.Timestamp(case.campaign_start), pd.Timestamp(case.campaign_end)
        )
    ]
    peak = campaign.loc[campaign["high_price"].idxmax()]
    return {
        "campaign_id": case.campaign_id,
        "vt_symbol": case.vt_symbol,
        "stock_name": case.stock_name,
        "campaign_start": pd.Timestamp(case.campaign_start),
        "campaign_end": pd.Timestamp(case.campaign_end),
        "evidence_end": pd.Timestamp(case.evidence_end),
        "anchor_basis": case.anchor_basis,
        "anchor_is_price_volume_ignition": anchor_is_ignition,
        "anchor_close": float(anchor["close_price"]),
        "campaign_peak_date": pd.Timestamp(peak["trade_date"]),
        "campaign_peak_price": float(peak["high_price"]),
        "campaign_gain_pct": (
            float(peak["high_price"]) / float(anchor["close_price"]) - 1.0
        )
        * 100.0,
        "wave_count": int(len(waves)),
        "continued_wave_count": int(
            waves["resolution_status"].eq("continued_to_higher_high").sum()
        ),
        "terminal_wave_count": int(
            waves["resolution_status"].eq("terminal_failure_observed").sum()
        ),
        "support_candidate_count": int(len(candidates)),
        "executed_trade_count": int(len(trades)),
        "d1_loss_stop_count": int(
            trades.get("d1_loss_exit_triggered", pd.Series(dtype=bool)).sum()
        ),
    }


def _load_case_daily_bars(cases: Sequence[LeaderCampaignCase]) -> pd.DataFrame:
    _validate_campaign_cases(cases)
    symbols = tuple(sorted({case.vt_symbol for case in cases}))
    load_start = min(case.load_start for case in cases)
    evidence_end = max(case.evidence_end for case in cases)
    statement = (
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stocks.c.name.label("stock_name"),
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.close_price,
            schema.stock_daily_bars.c.volume,
            schema.stock_daily_bars.c.source,
        )
        .select_from(
            schema.stock_daily_bars.join(
                schema.stocks,
                schema.stock_daily_bars.c.vt_symbol == schema.stocks.c.vt_symbol,
            )
        )
        .where(
            schema.stock_daily_bars.c.vt_symbol.in_(symbols),
            schema.stock_daily_bars.c.trade_date.between(load_start, evidence_end),
        )
        .order_by(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
        )
    )
    bars = pd.read_sql(statement, get_engine(), parse_dates=["trade_date"])
    if bars.empty:
        raise ValueError("individual leader daily bars are unavailable")
    if bars.duplicated(["vt_symbol", "trade_date"]).any():
        raise ValueError("individual leader daily bar identities must be unique")
    observed_names = {
        str(symbol): tuple(sorted(group["stock_name"].dropna().astype(str).unique()))
        for symbol, group in bars.groupby("vt_symbol", sort=False)
    }
    for case in cases:
        if observed_names.get(case.vt_symbol) != (case.stock_name,):
            raise ValueError(f"stock identity mismatch: {case.vt_symbol}")
    reference_calendar = pd.DatetimeIndex(bars["trade_date"].unique()).normalize()
    for case in cases:
        expected_dates = reference_calendar[
            (reference_calendar >= pd.Timestamp(case.campaign_start))
            & (reference_calendar <= pd.Timestamp(case.campaign_end))
        ]
        observed_dates = pd.DatetimeIndex(
            bars.loc[bars["vt_symbol"].eq(case.vt_symbol), "trade_date"]
        ).normalize()
        missing_dates = expected_dates.difference(observed_dates)
        if not missing_dates.empty:
            formatted = ", ".join(value.date().isoformat() for value in missing_dates)
            raise ValueError(
                f"campaign daily sessions are missing for {case.campaign_id}: {formatted}"
            )
    return bars.reset_index(drop=True)


def _assert_real_case_landmarks(
    campaigns: pd.DataFrame,
    daily: pd.DataFrame,
    candidates: pd.DataFrame,
) -> None:
    expected_waves = {
        "dongshan_2025_main_rise": 8,
        "jinan_2026_main_rise": 16,
        "hengtong_2025_first_main_rise": 4,
        "hengtong_2025_2026_second_main_rise": 13,
    }
    observed = campaigns.set_index("campaign_id")["wave_count"].astype(int).to_dict()
    if observed != expected_waves:
        raise ValueError(f"real campaign wave landmarks changed: {observed}")
    required = {
        ("dongshan_2025_main_rise", 1, date(2025, 6, 26)),
        ("dongshan_2025_main_rise", 2, date(2025, 7, 2)),
        ("jinan_2026_main_rise", 1, date(2026, 1, 21)),
        ("jinan_2026_main_rise", 2, date(2026, 1, 30)),
        ("hengtong_2025_2026_second_main_rise", 4, date(2026, 2, 6)),
        ("hengtong_2025_2026_second_main_rise", 5, date(2026, 2, 12)),
    }
    observed_candidates = {
        (
            str(row.campaign_id),
            int(row.wave_number),
            pd.Timestamp(row.signal_date).date(),
        )
        for row in candidates.itertuples(index=False)
    }
    missing = sorted(required - observed_candidates)
    if missing:
        raise ValueError(f"required real support landmarks are missing: {missing}")
    daily_landmarks = {
        ("dongshan_2025_main_rise", date(2025, 6, 25), "ma5", False),
        ("dongshan_2025_main_rise", date(2025, 6, 26), "ma5", True),
        ("dongshan_2025_main_rise", date(2025, 7, 2), "ma5", True),
    }
    observed_daily = {
        (
            str(row.campaign_id),
            pd.Timestamp(row.trade_date).date(),
            str(row.support_zone_today),
            bool(row.support_candidate),
        )
        for row in daily.loc[daily["pullback_active"].astype(bool)].itertuples(
            index=False
        )
    }
    missing_daily = sorted(daily_landmarks - observed_daily)
    if missing_daily:
        raise ValueError(f"required real daily landmarks are missing: {missing_daily}")


def _trade_metrics(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty or "net_return_pct" not in trades:
        return {
            "trades": 0,
            "closed_trades": 0,
            "positive_rate_pct": None,
            "mean_net_return_pct": None,
            "compound_return_pct": None,
            "d1_loss_stops": 0,
            "d1_stops_before_later_higher_high": 0,
        }
    closed = trades.loc[pd.to_numeric(trades["net_return_pct"], errors="coerce").notna()]
    returns = pd.to_numeric(closed["net_return_pct"], errors="coerce")
    compound = (
        (float((1.0 + returns / 100.0).prod()) - 1.0) * 100.0
        if not returns.empty
        else None
    )
    d1_stops = closed["d1_loss_exit_triggered"].astype(bool)
    return {
        "trades": int(len(trades)),
        "closed_trades": int(len(closed)),
        "positive_rate_pct": float(returns.gt(0).mean() * 100.0)
        if not returns.empty
        else None,
        "mean_net_return_pct": float(returns.mean()) if not returns.empty else None,
        "compound_return_pct": compound,
        "d1_loss_stops": int(d1_stops.sum()),
        "d1_stops_before_later_higher_high": int(
            (d1_stops & closed["later_higher_high_after_exit"].astype(bool)).sum()
        ),
    }


def _stock_summaries(
    campaigns: pd.DataFrame,
    trades: pd.DataFrame,
) -> pd.DataFrame:
    if campaigns.empty:
        return pd.DataFrame()
    rows = []
    for (symbol, name), grouped in campaigns.groupby(
        ["vt_symbol", "stock_name"], sort=False
    ):
        stock_trades = (
            trades.loc[trades["vt_symbol"].eq(symbol)]
            if not trades.empty and "vt_symbol" in trades
            else pd.DataFrame()
        )
        rows.append(
            {
                "vt_symbol": symbol,
                "stock_name": name,
                "campaign_count": int(len(grouped)),
                "wave_count": int(grouped["wave_count"].sum()),
                "continued_wave_count": int(grouped["continued_wave_count"].sum()),
                **_trade_metrics(stock_trades),
            }
        )
    return pd.DataFrame.from_records(rows)


def _loss_attribution(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty or "loss_cause" not in trades:
        return pd.DataFrame()
    losses = trades.loc[trades["loss_cause"].notna()].copy()
    if losses.empty:
        return pd.DataFrame()
    rows = []
    for cause, grouped in losses.groupby("loss_cause", sort=True):
        returns = pd.to_numeric(grouped["net_return_pct"], errors="coerce").dropna()
        rows.append(
            {
                "loss_cause": cause,
                "trades": int(len(grouped)),
                "mean_net_return_pct": float(returns.mean())
                if not returns.empty
                else None,
                "later_higher_high_count": int(
                    grouped["later_higher_high_after_exit"].astype(bool).sum()
                ),
            }
        )
    return pd.DataFrame.from_records(rows)


def _wave_sequence_summary(
    waves: pd.DataFrame,
    trades: pd.DataFrame,
) -> pd.DataFrame:
    if waves.empty:
        return pd.DataFrame()
    identities = ["campaign_id", "vt_symbol", "wave_number"]
    base = waves.loc[:, [*identities, "resolution_status"]].copy()
    if trades.empty:
        attempts = pd.DataFrame(columns=[*identities, "attempts", "wave_net_return_pct"])
    else:
        attempts = (
            trades.groupby(identities, sort=False)
            .agg(
                attempts=("attempt_number", "max"),
                wave_net_return_pct=("net_return_pct", _compound_series),
            )
            .reset_index()
        )
    ledger = base.merge(attempts, on=identities, how="left", validate="one_to_one")
    rows = []
    cohorts = (
        ("all", pd.Series(True, index=ledger.index)),
        (
            "continued_to_higher_high",
            ledger["resolution_status"].eq("continued_to_higher_high"),
        ),
        (
            "terminal_failure_observed",
            ledger["resolution_status"].eq("terminal_failure_observed"),
        ),
    )
    for label, mask in cohorts:
        cohort = ledger.loc[mask]
        entered = cohort.loc[cohort["attempts"].notna()]
        returns = pd.to_numeric(entered["wave_net_return_pct"], errors="coerce")
        rows.append(
            {
                "cohort": label,
                "waves": int(len(cohort)),
                "waves_with_entry": int(len(entered)),
                "waves_without_entry": int(len(cohort) - len(entered)),
                "profitable_wave_sequences": int(returns.gt(0).sum()),
                "profitable_rate_among_entered_pct": (
                    float(returns.gt(0).mean() * 100.0)
                    if not returns.empty
                    else None
                ),
                "mean_wave_net_return_pct": (
                    float(returns.mean()) if not returns.empty else None
                ),
                "median_wave_net_return_pct": (
                    float(returns.median()) if not returns.empty else None
                ),
                "mean_attempts_per_entered_wave": (
                    float(entered["attempts"].mean()) if not entered.empty else None
                ),
            }
        )
    return pd.DataFrame.from_records(rows)


def _candidate_feature_summaries(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {}
    frame = trades.copy()
    frame["signal_direction"] = np.where(
        pd.to_numeric(frame["signal_daily_return_pct"], errors="coerce").gt(0),
        "up_close",
        "flat_or_down_close",
    )
    frame["structure_transition"] = np.where(
        frame["structure_reclaimed_today"].astype(bool),
        "structure_reclaimed",
        "ordinary_support_hold",
    )
    return {
        "attempt_number": _records(
            _group_trade_metrics(frame, "attempt_number")
        ),
        "support_line": _records(_group_trade_metrics(frame, "support_line")),
        "volume_class": _records(
            _group_trade_metrics(frame, "signal_volume_class")
        ),
        "signal_direction": _records(
            _group_trade_metrics(frame, "signal_direction")
        ),
        "structure_transition": _records(
            _group_trade_metrics(frame, "structure_transition")
        ),
    }


def _case_hypothesis_comparison(
    waves: pd.DataFrame,
    replays: Mapping[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    rows = []
    for name, definition in CASE_HYPOTHESIS_DEFINITIONS.items():
        trades = replays.get(name, pd.DataFrame())
        wave_summary = _wave_sequence_summary(waves, trades)
        all_waves = (
            wave_summary.loc[wave_summary["cohort"].eq("all")]
            if not wave_summary.empty
            else pd.DataFrame()
        )
        wave_metrics = all_waves.iloc[0].to_dict() if len(all_waves) == 1 else {}
        dongshan_july_second = bool(
            not trades.empty
            and "campaign_id" in trades
            and (
                trades["campaign_id"].eq("dongshan_2025_main_rise")
                & pd.to_datetime(trades["entry_date"], errors="coerce").eq(
                    pd.Timestamp("2025-07-02")
                )
            ).any()
        )
        rows.append(
            {
                "name": name,
                "definition": definition,
                **_trade_metrics(trades),
                "waves_with_entry": wave_metrics.get("waves_with_entry"),
                "profitable_wave_sequences": wave_metrics.get(
                    "profitable_wave_sequences"
                ),
                "profitable_rate_among_entered_pct": wave_metrics.get(
                    "profitable_rate_among_entered_pct"
                ),
                "includes_dongshan_2025_07_02": dongshan_july_second,
                "status": "post_case_hypothesis_not_validated",
            }
        )
    return _json_safe(rows)


def _group_trade_metrics(trades: pd.DataFrame, column: str) -> pd.DataFrame:
    rows = []
    for value, grouped in trades.groupby(column, dropna=False, sort=True):
        rows.append({"group": value, **_trade_metrics(grouped)})
    return pd.DataFrame.from_records(rows)


def _compound_series(values: pd.Series) -> float | None:
    returns = pd.to_numeric(values, errors="coerce").dropna()
    if returns.empty:
        return None
    return (float((1.0 + returns / 100.0).prod()) - 1.0) * 100.0


def _campaign_lines(raw: Any) -> list[str]:
    lines = []
    for row in _sequence(raw):
        item = _mapping(row)
        lines.append(
            f"| {item.get('stock_name')} `{item.get('vt_symbol')}` | "
            f"{item.get('campaign_start')}..{item.get('campaign_end')} | "
            f"{item.get('wave_count')} | {item.get('continued_wave_count')} | "
            f"{item.get('terminal_wave_count')} | "
            f"{_percent(item.get('campaign_gain_pct'))} | "
            f"{item.get('support_candidate_count')} | {item.get('executed_trade_count')} |"
        )
    return lines


def _wave_sequence_lines(raw: Any) -> list[str]:
    lines = []
    for row in _sequence(raw):
        item = _mapping(row)
        lines.append(
            f"| `{item.get('cohort')}` | {item.get('waves')} | "
            f"{item.get('waves_with_entry')} | "
            f"{item.get('profitable_wave_sequences')} | "
            f"{_percent(item.get('profitable_rate_among_entered_pct'))} | "
            f"{_percent(item.get('mean_wave_net_return_pct'))} |"
        )
    return lines


def _feature_summary_lines(raw: Any) -> list[str]:
    lines = []
    summaries = _mapping(raw)
    for dimension, groups in summaries.items():
        for row in _sequence(groups):
            item = _mapping(row)
            lines.append(
                f"| `{dimension}` | `{item.get('group')}` | "
                f"{item.get('closed_trades')} | "
                f"{_percent(item.get('positive_rate_pct'))} | "
                f"{_percent(item.get('mean_net_return_pct'))} |"
            )
    return lines


def _case_hypothesis_lines(raw: Any) -> list[str]:
    lines = []
    for row in _sequence(raw):
        item = _mapping(row)
        lines.append(
            f"| `{item.get('name')}` | {item.get('closed_trades')} | "
            f"{_percent(item.get('positive_rate_pct'))} | "
            f"{_percent(item.get('mean_net_return_pct'))} | "
            f"{item.get('waves_with_entry')} | "
            f"{_percent(item.get('profitable_rate_among_entered_pct'))} | "
            f"{item.get('includes_dongshan_2025_07_02')} |"
        )
    return lines


def _wave_lines(raw: Any) -> list[str]:
    lines = []
    for row in _sequence(raw):
        item = _mapping(row)
        trough = f"{item.get('trough_date')} {_number(item.get('trough_price'))}"
        support = item.get("deepest_tested_support")
        lines.append(
            f"| {item.get('stock_name')} / `{item.get('campaign_id')}` | "
            f"{item.get('wave_number')} | {item.get('peak_date')} "
            f"{_number(item.get('peak_price'))} | "
            f"{item.get('pullback_confirmation_date')} | {trough} `{support}` | "
            f"{item.get('higher_high_date') or '-'} | "
            f"{item.get('first_structural_break_in_pullback') or '-'} | "
            f"`{item.get('resolution_status')}` |"
        )
    return lines


def _trade_lines(raw: Any) -> list[str]:
    lines = []
    for row in _sequence(raw):
        item = _mapping(row)
        lines.append(
            f"| {item.get('stock_name')} | {item.get('wave_number')}/"
            f"{item.get('attempt_number')} | {item.get('entry_date')} "
            f"{_number(item.get('entry_price'))} | `{item.get('support_line')}` | "
            f"{_percent(item.get('d1_net_return_pct'))} | "
            f"{item.get('exit_date') or '-'} `{item.get('exit_reason')}` | "
            f"{_percent(item.get('net_return_pct'))} | "
            f"{item.get('later_higher_high_after_exit')} | "
            f"`{item.get('loss_cause') or 'profitable'}` |"
        )
    return lines


def _loss_lines(raw: Any) -> list[str]:
    lines = []
    for row in _sequence(raw):
        item = _mapping(row)
        lines.append(
            f"| `{item.get('loss_cause')}` | {item.get('trades')} | "
            f"{_percent(item.get('mean_net_return_pct'))} | "
            f"{item.get('later_higher_high_count')} |"
        )
    return lines


def _candidate_columns() -> list[str]:
    return [
        "campaign_id",
        "vt_symbol",
        "wave_number",
        "signal_date",
        "pullback_confirmation_date",
        "reference_peak_date",
        "reference_peak_price",
        "support_line",
        "support_depth",
        "support_price",
        "signal_open",
        "signal_high",
        "signal_low",
        "signal_close",
        "signal_daily_return_pct",
        "signal_volume_ratio_prior5",
        "signal_volume_class",
        "close_location",
        "signal_close_not_below_previous",
        "approached_support_today",
        "reclaimed_support_today",
        "structure_reclaimed_today",
        "running_pullback_low",
        "running_drawdown_pct",
        "feature_cutoff_date",
    ]


def _trade_columns() -> list[str]:
    return [
        "campaign_id",
        "vt_symbol",
        "wave_number",
        "attempt_number",
        "entry_date",
        "entry_price",
        "support_line",
        "support_depth",
        "running_pullback_low_at_entry",
        "reference_peak_price",
        "d1_date",
        "d1_close",
        "d1_net_return_pct",
        "d1_loss_exit_triggered",
        "signal_daily_return_pct",
        "signal_volume_ratio_prior5",
        "signal_volume_class",
        "signal_close_location",
        "signal_close_not_below_previous",
        "approached_support_today",
        "reclaimed_support_today",
        "structure_reclaimed_today",
        "exit_date",
        "exit_price",
        "exit_reason",
        "exit_causality",
        "holding_sessions",
        "net_return_pct",
        "mfe_pct",
        "mae_pct",
        "wave_resolution_status",
        "wave_higher_high_date",
        "later_higher_high_after_exit",
        "loss_cause",
    ]


def _one_bar(frame: pd.DataFrame, trade_date: pd.Timestamp, label: str) -> pd.Series:
    matches = frame.loc[frame["trade_date"].eq(trade_date)]
    if len(matches) != 1:
        raise ValueError(f"{label} must have exactly one daily bar")
    return matches.iloc[0]


def _net_return(entry: float, exit_price: float, cost_pct: float) -> float:
    return (float(exit_price) / float(entry) - 1.0) * 100.0 - cost_pct


def _concat(parts: Sequence[pd.DataFrame]) -> pd.DataFrame:
    usable = [part for part in parts if not part.empty]
    return pd.concat(usable, ignore_index=True, sort=False) if usable else pd.DataFrame()


def _nunique(frame: pd.DataFrame, column: str) -> int:
    return int(frame[column].nunique()) if column in frame else 0


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [_json_safe(row) for row in frame.to_dict("records")]


def _json_safe(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, date)):
        return pd.Timestamp(value).date().isoformat()
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


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, str) else ()


def _finite_or_none(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _percent(value: object) -> str:
    number = _finite_or_none(value)
    return "-" if number is None else f"{number:+.4f}%"


def _number(value: object) -> str:
    number = _finite_or_none(value)
    return "-" if number is None else f"{number:.4f}"


def _same_optional_date(left: object, right: object) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    if pd.isna(left) or pd.isna(right):
        return False
    return pd.Timestamp(left) == pd.Timestamp(right)


def _require_columns(
    frame: pd.DataFrame,
    required: Sequence[str],
    label: str,
) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing columns: {', '.join(missing)}")
