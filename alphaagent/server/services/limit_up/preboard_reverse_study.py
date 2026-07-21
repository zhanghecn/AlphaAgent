"""Read-only reverse inference from the current formal touch baseline."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from math import isfinite
from statistics import median

from alphaagent.server.services.limit_up.preboard_baseline_model import (
    BASELINE_FEATURE_NAMES,
    formal_first_board_pairs,
)
from alphaagent.server.services.limit_up.preboard_reverse_profile import (
    RANKING_FIELDS,
    REVERSE_HORIZONS,
    align_pair_to_touch_horizons,
    feature_separation,
    first_observable_leads,
    is_shared_eligible,
    matched_risk_set,
    positive_rank_diagnostics,
    snapshot_pair_at_touch_horizons,
)


STUDY_VERSION = "limit-up-touch-baseline-reverse-inference-v1"


def build_reverse_report(
    prefix_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    baseline_account_orders: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    fit_dates: set[date],
    calibration_dates: set[date],
    validation_dates: set[date],
) -> dict[str, object]:
    """Aggregate reverse-aligned identities by fixed chronological phase."""

    phase_dates: dict[str, set[date] | None] = {
        "full": None,
        "fit": fit_dates,
        "calibration": calibration_dates,
        "viewed_validation": validation_dates,
    }
    phases = {
        phase: _build_phase_report(
            _filter_prefix_dates(prefix_rows, allowed_dates),
            _filter_order_dates(formal_orders, allowed_dates),
            baseline_account_orders.get(
                "validation" if phase == "viewed_validation" else phase,
                [],
            ),
        )
        for phase, allowed_dates in phase_dates.items()
    }
    full = phases["full"]
    return {
        "study_version": STUDY_VERSION,
        "validation_kind": "viewed_historical_time_validation",
        "identity_counts": full["identity_counts"],
        "first_visibility": full["first_visibility"],
        "horizons": full["horizons"],
        "pair_ledger": full["pair_ledger"],
        "phases": phases,
        "registered_feature_directions": _registered_feature_directions(phases),
        "production_changed": False,
    }


def render_reverse_markdown(report: Mapping[str, object]) -> str:
    scope = _mapping(report.get("scope"))
    coverage = _mapping(report.get("coverage"))
    identities = _mapping(report.get("identity_counts"))
    first_visibility = _mapping(report.get("first_visibility"))
    horizons = _mapping(report.get("horizons"))
    phases = _mapping(report.get("phases"))
    parity = _mapping(report.get("baseline_parity"))
    registered = list(report.get("registered_feature_directions") or [])
    registered_summary = _registered_direction_summary(registered)
    lines = [
        "# 触板基线反向推理研究",
        "",
        "## Current state",
        "",
        f"- 状态：`{report.get('status', 'reverse_diagnostic_only')}`。",
        f"- 区间：`{scope.get('date_start')}..{scope.get('date_end')}`，"
        f"{scope.get('session_count', 0)} 个交易日；最后阶段为已查看历史，不是新留出。",
        f"- 正式首板候选 {identities.get('formal_first_board_pairs', 0)} 对；"
        f"触板账户实际成交首板 {identities.get('account_filled_first_board_pairs', 0)} 对。",
        f"- 完整5分钟路径：{coverage.get('complete_pair_count', 0)}/"
        f"{coverage.get('manifest_pair_count', 0)}。",
        f"- 正式触板账户一致性：`{parity.get('passed')}`。",
        "- 本报告从已发生的触板基线向前对齐，只用于发现结构，不能直接成为实时规则。",
        "- `已到3%` 已先通过当前同股成熟样本/联合率门；`已过过滤`再叠加当前lane和support门。",
        "",
        "## First visibility",
        "",
        "| 群体 | 首次达到3%数量/提前中位 | 首次通过过滤数量/提前中位 |",
        "| --- | ---: | ---: |",
    ]
    for cohort, label in (("formal", "正式首板候选"), ("account", "账户成交首板")):
        row = _mapping(first_visibility.get(cohort))
        first_3pct = _mapping(row.get("first_3pct"))
        first_shared = _mapping(row.get("first_shared"))
        lines.append(
            f"| {label} | {first_3pct.get('count', 0)}/"
            f"{_display(first_3pct.get('median'))}分 | "
            f"{first_shared.get('count', 0)}/{_display(first_shared.get('median'))}分 |"
        )
    lines.extend(
        [
        "",
        "## Cumulative tracking reachability",
        "",
        "表示至少提前该时距曾出现过状态，不用于短时排序。",
        "",
        "| 提前时距 | 正式候选曾到3% | 正式候选曾过过滤 | 账户身份曾到3% | 账户身份曾过过滤 |",
        "| ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for horizon in REVERSE_HORIZONS:
        row = _mapping(horizons.get(str(horizon)))
        formal_cumulative = _mapping(
            _mapping(row.get("formal")).get("cumulative_reachability")
        )
        account_cumulative = _mapping(
            _mapping(row.get("account")).get("cumulative_reachability")
        )
        lines.append(
            f"| {horizon}分 | "
            f"{_fraction(_mapping(formal_cumulative.get('observed_3pct')))} | "
            f"{_fraction(_mapping(formal_cumulative.get('shared_eligible')))} | "
            f"{_fraction(_mapping(account_cumulative.get('observed_3pct')))} | "
            f"{_fraction(_mapping(account_cumulative.get('shared_eligible')))} |"
        )
    lines.extend(
        [
        "",
        "## Fixed-horizon snapshots",
        "",
        "使用触板截止点最近一根完成栏，是下一短时模型可使用的即时状态。",
        "",
        "| 提前时距 | 正式候选当前>=3% | 正式候选当前过过滤 | 账户身份当前>=3% | 账户身份当前过过滤 | 当前Rank账户Top2 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for horizon in REVERSE_HORIZONS:
        row = _mapping(horizons.get(str(horizon)))
        formal = _mapping(row.get("formal"))
        account = _mapping(row.get("account"))
        formal_raw = _mapping(formal.get("observed_3pct"))
        formal_shared = _mapping(formal.get("shared_eligible"))
        account_raw = _mapping(account.get("observed_3pct"))
        account_shared = _mapping(account.get("shared_eligible"))
        account_top2 = _mapping(account_shared.get("top2_capture"))
        lines.append(
            f"| {horizon}分 | {_fraction(formal_raw)} | {_fraction(formal_shared)} | "
            f"{_fraction(account_raw)} | {_fraction(account_shared)} | "
            f"{account_top2.get('rank_score', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Account phase stability",
            "",
            "| 阶段 | 时距 | 账户身份当前>=3% | 当前过过滤 | 当前Rank Top2/可排名 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for phase, label in (
        ("fit", "拟合30日"),
        ("calibration", "校准10日"),
        ("viewed_validation", "已查看后20日"),
    ):
        phase_horizons = _mapping(_mapping(phases.get(phase)).get("horizons"))
        for horizon in REVERSE_HORIZONS:
            account = _mapping(
                _mapping(phase_horizons.get(str(horizon))).get("account")
            )
            raw = _mapping(account.get("observed_3pct"))
            shared = _mapping(account.get("shared_eligible"))
            rank_metrics = _mapping(
                _mapping(shared.get("rank_diagnostics")).get("rank_score")
            )
            lines.append(
                f"| {label} | {horizon}分 | {_fraction(raw)} | {_fraction(shared)} | "
                f"{_mapping(shared.get('top2_capture')).get('rank_score', 0)}/"
                f"{rank_metrics.get('ranked_count', 0)} |"
            )
    lines.extend(
        [
            "",
            "## Shared-filter blockers",
            "",
            "只统计固定时距快照当前>=3%、但尚未通过lane/support的账户身份。",
            "",
            "| 时距 | blocker计数 |",
            "| ---: | --- |",
        ]
    )
    for horizon in REVERSE_HORIZONS:
        account = _mapping(_mapping(horizons.get(str(horizon))).get("account"))
        shared = _mapping(account.get("shared_eligible"))
        lines.append(
            f"| {horizon}分 | `"
            f"{json.dumps(shared.get('blocker_counts') or {}, ensure_ascii=False)}` |"
        )
    account_ledger = [
        _mapping(row)
        for row in report.get("pair_ledger") or []
        if _mapping(row).get("account_filled_first_board") is True
    ]
    lines.extend(
        [
            "",
            "## Account identity ledger",
            "",
            "| 日期 | 股票 | 触板 | 首达3%提前 | 首过过滤提前 | 10分钟前状态/Rank | 5分钟前状态/Rank |",
            "| --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in account_ledger:
        visibility = _mapping(row.get("first_visibility"))
        by_horizon = _mapping(row.get("horizons"))
        lines.append(
            f"| {row.get('signal_date')} | {row.get('vt_symbol')} | {row.get('touch_time')} | "
            f"{_display(visibility.get('first_3pct_lead_minutes'))}分 | "
            f"{_display(visibility.get('first_shared_lead_minutes'))}分 | "
            f"{_pair_ledger_cell(by_horizon, 10)} | {_pair_ledger_cell(by_horizon, 5)} |"
        )
    validation_consistent = sum(
        _mapping(row).get("viewed_validation_direction_consistent") is True
        for row in registered
    )
    lines.extend(
        [
            "",
            "## Registered reverse directions",
            "",
            "只有拟合段和校准段方向一致的字段才登记；验证段不能参与选择。"
            f"共登记 {len(registered)} 个时距-字段方向，其中 {validation_consistent} 个在"
            "已查看验证段仍保持同方向。下表只汇总至少覆盖3个时距的重复结构。",
            "",
            "| 群体 | 状态 | 字段 | 方向 | 稳定时距 | 验证同向 |",
            "| --- | --- | --- | --- | --- | ---: |",
        ]
    )
    for raw in registered_summary:
        row = _mapping(raw)
        lines.append(
            f"| {row.get('cohort')} | {row.get('state')} | {row.get('feature')} | "
            f"{row.get('direction')} | "
            f"{','.join(str(value) for value in row.get('horizons') or [])} | "
            f"{row.get('viewed_validation_consistent_count', 0)}/"
            f"{row.get('horizon_count', 0)} |"
        )
    if not registered_summary:
        lines.append("| - | - | 无 | - | - | - |")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- 反向对齐时间、未来触板身份、账户成交身份和D+1结果只作标签或归因。",
            "- 任何下一算法都必须冻结后重新从全体>=3%母池正向运行，并按两仓路径验证。",
            "- 正式 `limit-up-live-v15 / limit-up-scheduled-v9` 未修改。",
            "",
        ]
    )
    return "\n".join(lines)


def _registered_direction_summary(
    rows: Sequence[object],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str, str], list[Mapping[str, object]]] = defaultdict(list)
    for raw in rows:
        row = _mapping(raw)
        key = (
            str(row.get("cohort") or ""),
            str(row.get("state") or ""),
            str(row.get("feature") or ""),
            str(row.get("direction") or ""),
        )
        grouped[key].append(row)
    result = [
        {
            "cohort": key[0],
            "state": key[1],
            "feature": key[2],
            "direction": key[3],
            "horizons": sorted(int(row["horizon_minutes"]) for row in values),
            "horizon_count": len(values),
            "viewed_validation_consistent_count": sum(
                row.get("viewed_validation_direction_consistent") is True
                for row in values
            ),
        }
        for key, values in grouped.items()
        if len(values) >= 3
    ]
    return sorted(
        result,
        key=lambda row: (
            -int(row["horizon_count"]),
            str(row["cohort"]),
            str(row["state"]),
            str(row["feature"]),
        ),
    )


def _pair_ledger_cell(horizons: Mapping[str, object], horizon: int) -> str:
    horizon_row = _mapping(horizons.get(str(horizon)))
    snapshot = _mapping(horizon_row.get("snapshot"))
    shared = _mapping(horizon_row.get("shared_eligible"))
    if not shared:
        raw = _mapping(horizon_row.get("observed_3pct"))
        if raw:
            return "当前>=3%未过过滤"
        if snapshot.get("tracked_after_3pct") is True:
            return f"跟踪中/当前{_display(snapshot.get('gain_pct'))}%"
        return "当前未到3%"
    rank = _mapping(_mapping(shared.get("ranks")).get("rank_score"))
    features = _mapping(shared.get("features"))
    return (
        f"{shared.get('signal_time')}/涨{_display(features.get('gain_pct'))}%/"
        f"Rank {rank.get('rank')}/{rank.get('candidate_count')}"
    )


def _build_phase_report(
    prefix_rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    account_orders: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    formal_pairs = formal_first_board_pairs(formal_orders)
    account_pairs = formal_first_board_pairs(account_orders) & formal_pairs
    touch_times = _formal_touch_times(formal_orders)
    rows_by_pair = _rows_by_pair(prefix_rows)
    cohorts = {"formal": formal_pairs, "account": account_pairs}
    aligned = {
        cohort: _align_cohort(rows_by_pair, touch_times, pairs)
        for cohort, pairs in cohorts.items()
    }
    return {
        "identity_counts": {
            "formal_first_board_pairs": len(formal_pairs),
            "account_filled_first_board_pairs": len(account_pairs),
        },
        "first_visibility": {
            cohort: _visibility_report(rows_by_pair, touch_times, pairs)
            for cohort, pairs in cohorts.items()
        },
        "horizons": {
            str(horizon): {
                cohort: _cohort_horizon_report(
                    prefix_rows,
                    pairs,
                    aligned[cohort],
                    horizon=horizon,
                )
                for cohort, pairs in cohorts.items()
            }
            for horizon in REVERSE_HORIZONS
        },
        "pair_ledger": _pair_ledger(
            prefix_rows,
            rows_by_pair,
            formal_orders,
            formal_pairs,
            account_pairs,
            touch_times,
        ),
    }


def _align_cohort(
    rows_by_pair: Mapping[tuple[str, str], Sequence[Mapping[str, object]]],
    touch_times: Mapping[tuple[str, str], str],
    pairs: set[tuple[str, str]],
) -> dict[str, dict[tuple[str, str], dict[int, dict[str, object] | None]]]:
    cumulative_raw: dict[tuple[str, str], dict[int, dict[str, object] | None]] = {}
    cumulative_shared: dict[tuple[str, str], dict[int, dict[str, object] | None]] = {}
    snapshots: dict[tuple[str, str], dict[int, dict[str, object] | None]] = {}
    snapshot_raw: dict[tuple[str, str], dict[int, dict[str, object] | None]] = {}
    snapshot_shared: dict[tuple[str, str], dict[int, dict[str, object] | None]] = {}
    for pair in sorted(pairs):
        touch_time = touch_times.get(pair)
        if not touch_time:
            continue
        rows = rows_by_pair.get(pair, [])
        cumulative_raw[pair] = align_pair_to_touch_horizons(
            rows,
            touch_time=touch_time,
        )
        cumulative_shared[pair] = align_pair_to_touch_horizons(
            [row for row in rows if is_shared_eligible(row)],
            touch_time=touch_time,
        )
        snapshots[pair] = snapshot_pair_at_touch_horizons(
            rows,
            touch_time=touch_time,
        )
        snapshot_raw[pair] = {
            horizon: row
            if row is not None and row.get("snapshot_current_gte_3pct") is True
            else None
            for horizon, row in snapshots[pair].items()
        }
        snapshot_shared[pair] = {
            horizon: row
            if row is not None and row.get("snapshot_shared_eligible") is True
            else None
            for horizon, row in snapshots[pair].items()
        }
    return {
        "observed_3pct": snapshot_raw,
        "shared_eligible": snapshot_shared,
        "snapshots": snapshots,
        "cumulative_observed_3pct": cumulative_raw,
        "cumulative_shared_eligible": cumulative_shared,
    }


def _cohort_horizon_report(
    prefix_rows: Sequence[Mapping[str, object]],
    pairs: set[tuple[str, str]],
    aligned: Mapping[
        str,
        Mapping[tuple[str, str], Mapping[int, Mapping[str, object] | None]],
    ],
    *,
    horizon: int,
) -> dict[str, object]:
    raw_rows = _rows_at_horizon(aligned.get("observed_3pct", {}), horizon)
    shared_rows = _rows_at_horizon(aligned.get("shared_eligible", {}), horizon)
    return {
        "observed_3pct": _state_report(
            prefix_rows,
            pairs,
            raw_rows,
            require_shared=False,
        ),
        "shared_eligible": _state_report(
            prefix_rows,
            pairs,
            shared_rows,
            require_shared=True,
            fallback_rows=raw_rows,
        ),
        "cumulative_reachability": {
            "observed_3pct": _reachability_only(
                pairs,
                aligned.get("cumulative_observed_3pct", {}),
                horizon,
            ),
            "shared_eligible": _reachability_only(
                pairs,
                aligned.get("cumulative_shared_eligible", {}),
                horizon,
            ),
        },
    }


def _reachability_only(
    pairs: set[tuple[str, str]],
    aligned: Mapping[tuple[str, str], Mapping[int, Mapping[str, object] | None]],
    horizon: int,
) -> dict[str, object]:
    reachable = len(_rows_at_horizon(aligned, horizon))
    return {
        "positive_pair_count": len(pairs),
        "reachable_count": reachable,
        "reachable_rate_pct": _percentage(reachable, len(pairs)),
    }


def _state_report(
    prefix_rows: Sequence[Mapping[str, object]],
    pairs: set[tuple[str, str]],
    aligned_rows: Mapping[tuple[str, str], Mapping[str, object]],
    *,
    require_shared: bool,
    fallback_rows: Mapping[tuple[str, str], Mapping[str, object]] | None = None,
) -> dict[str, object]:
    ranks: list[dict[str, dict[str, object]]] = []
    controls: list[dict[str, object]] = []
    competitors: list[int] = []
    for pair, anchor in aligned_rows.items():
        risk = matched_risk_set(prefix_rows, anchor, require_shared=require_shared)
        ranks.append(positive_rank_diagnostics(risk, pair))
        controls.extend(row for row in risk if _row_pair(row) != pair)
        competitors.append(max(len(risk) - 1, 0))
    rank_report = _aggregate_ranks(ranks)
    return {
        "positive_pair_count": len(pairs),
        "reachable_count": len(aligned_rows),
        "reachable_rate_pct": _percentage(len(aligned_rows), len(pairs)),
        "competitor_count": _distribution(competitors),
        "top1_capture": {
            field: int(rank_report[field]["top1_count"]) for field in RANKING_FIELDS
        },
        "top2_capture": {
            field: int(rank_report[field]["top2_count"]) for field in RANKING_FIELDS
        },
        "rank_diagnostics": rank_report,
        "feature_separation": feature_separation(
            list(aligned_rows.values()),
            controls,
        ),
        "blocker_counts": _blocker_counts(
            pairs,
            aligned_rows,
            fallback_rows or {},
        ),
    }


def _aggregate_ranks(
    rows: Sequence[Mapping[str, Mapping[str, object]]],
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for field in RANKING_FIELDS:
        metrics = [_mapping(row.get(field)) for row in rows]
        ranks = [int(value) for row in metrics if (value := row.get("rank")) is not None]
        percentiles = [
            float(value)
            for row in metrics
            if (value := _number(row.get("percentile"))) is not None
        ]
        result[field] = {
            "ranked_count": len(ranks),
            "top1_count": sum(row.get("top1") is True for row in metrics),
            "top2_count": sum(row.get("top2") is True for row in metrics),
            "median_rank": _median(ranks),
            "median_percentile": _median(percentiles),
        }
    return result


def _visibility_report(
    rows_by_pair: Mapping[tuple[str, str], Sequence[Mapping[str, object]]],
    touch_times: Mapping[tuple[str, str], str],
    pairs: set[tuple[str, str]],
) -> dict[str, object]:
    leads = [
        first_observable_leads(rows_by_pair.get(pair, []), touch_time=touch_times[pair])
        for pair in sorted(pairs)
        if pair in touch_times
    ]
    return {
        "positive_pair_count": len(pairs),
        "first_3pct": _distribution(
            [
                float(value)
                for row in leads
                if (value := _number(row.get("first_3pct_lead_minutes"))) is not None
            ]
        ),
        "first_shared": _distribution(
            [
                float(value)
                for row in leads
                if (value := _number(row.get("first_shared_lead_minutes"))) is not None
            ]
        ),
    }


def _pair_ledger(
    prefix_rows: Sequence[Mapping[str, object]],
    rows_by_pair: Mapping[tuple[str, str], Sequence[Mapping[str, object]]],
    formal_orders: Sequence[Mapping[str, object]],
    formal_pairs: set[tuple[str, str]],
    account_pairs: set[tuple[str, str]],
    touch_times: Mapping[tuple[str, str], str],
) -> list[dict[str, object]]:
    order_by_pair = {
        _row_pair(order): order
        for order in formal_orders
        if _row_pair(order) in formal_pairs
    }
    result: list[dict[str, object]] = []
    for pair in sorted(formal_pairs, key=lambda item: (item[1], item[0])):
        touch_time = touch_times.get(pair)
        rows = rows_by_pair.get(pair, [])
        if not touch_time:
            continue
        raw = align_pair_to_touch_horizons(rows, touch_time=touch_time)
        cumulative_shared = align_pair_to_touch_horizons(
            [row for row in rows if is_shared_eligible(row)],
            touch_time=touch_time,
        )
        snapshots = snapshot_pair_at_touch_horizons(rows, touch_time=touch_time)
        result.append(
            {
                "vt_symbol": pair[0],
                "signal_date": pair[1],
                "touch_time": touch_time,
                "account_filled_first_board": pair in account_pairs,
                "first_visibility": first_observable_leads(rows, touch_time=touch_time),
                "outcome_attribution": _outcome_attribution(order_by_pair.get(pair, {})),
                "horizons": {
                    str(horizon): _pair_horizon_ledger(
                        prefix_rows,
                        pair,
                        snapshots.get(horizon),
                        cumulative_raw=raw.get(horizon),
                        cumulative_shared=cumulative_shared.get(horizon),
                    )
                    for horizon in REVERSE_HORIZONS
                },
            }
        )
    return result


def _pair_horizon_ledger(
    prefix_rows: Sequence[Mapping[str, object]],
    pair: tuple[str, str],
    snapshot: Mapping[str, object] | None,
    *,
    cumulative_raw: Mapping[str, object] | None,
    cumulative_shared: Mapping[str, object] | None,
) -> dict[str, object]:
    raw = (
        snapshot
        if snapshot is not None and snapshot.get("snapshot_current_gte_3pct") is True
        else None
    )
    shared = (
        snapshot
        if snapshot is not None and snapshot.get("snapshot_shared_eligible") is True
        else None
    )
    return {
        "snapshot": _snapshot_ledger(snapshot),
        "observed_3pct": _pair_state_ledger(
            prefix_rows,
            pair,
            raw,
            require_shared=False,
        ),
        "shared_eligible": _pair_state_ledger(
            prefix_rows,
            pair,
            shared,
            require_shared=True,
        ),
        "cumulative_observed_3pct": cumulative_raw is not None,
        "cumulative_shared_eligible": cumulative_shared is not None,
    }


def _snapshot_ledger(row: Mapping[str, object] | None) -> dict[str, object] | None:
    if row is None:
        return None
    return {
        "signal_time": row.get("signal_time"),
        "lead_minutes": row.get("reverse_lead_minutes"),
        "tracked_after_3pct": row.get("tracked_after_3pct") is True,
        "current_gte_3pct": row.get("snapshot_current_gte_3pct") is True,
        "shared_eligible": row.get("snapshot_shared_eligible") is True,
        "gain_pct": _feature_value(row, "gain_pct"),
    }


def _pair_state_ledger(
    prefix_rows: Sequence[Mapping[str, object]],
    pair: tuple[str, str],
    row: Mapping[str, object] | None,
    *,
    require_shared: bool,
) -> dict[str, object] | None:
    if row is None:
        return None
    risk = matched_risk_set(prefix_rows, row, require_shared=require_shared)
    return {
        "signal_time": row.get("signal_time"),
        "lead_minutes": row.get("reverse_lead_minutes"),
        "competitor_count": max(len(risk) - 1, 0),
        "features": {
            field: _feature_value(row, field) for field in BASELINE_FEATURE_NAMES
        },
        "blockers": _row_blockers(row),
        "ranks": positive_rank_diagnostics(risk, pair),
    }


def _registered_feature_directions(
    phases: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    fit = _mapping(phases.get("fit"))
    calibration = _mapping(phases.get("calibration"))
    validation = _mapping(phases.get("viewed_validation"))
    result: list[dict[str, object]] = []
    for horizon in REVERSE_HORIZONS:
        for cohort in ("formal", "account"):
            for state in ("observed_3pct", "shared_eligible"):
                fit_features = _phase_features(fit, horizon, cohort, state)
                calibration_features = _phase_features(
                    calibration,
                    horizon,
                    cohort,
                    state,
                )
                validation_features = _phase_features(
                    validation,
                    horizon,
                    cohort,
                    state,
                )
                for feature in BASELINE_FEATURE_NAMES:
                    fit_auc = _number(_mapping(fit_features.get(feature)).get("rank_auc"))
                    calibration_auc = _number(
                        _mapping(calibration_features.get(feature)).get("rank_auc")
                    )
                    direction = _stable_direction(fit_auc, calibration_auc)
                    if direction is None:
                        continue
                    validation_auc = _number(
                        _mapping(validation_features.get(feature)).get("rank_auc")
                    )
                    result.append(
                        {
                            "cohort": cohort,
                            "state": state,
                            "horizon_minutes": horizon,
                            "feature": feature,
                            "direction": direction,
                            "fit_auc": fit_auc,
                            "calibration_auc": calibration_auc,
                            "viewed_validation_auc": validation_auc,
                            "viewed_validation_direction_consistent": (
                                _direction_matches(direction, validation_auc)
                            ),
                        }
                    )
    return result


def _phase_features(
    phase: Mapping[str, object],
    horizon: int,
    cohort: str,
    state: str,
) -> Mapping[str, object]:
    horizons = _mapping(phase.get("horizons"))
    horizon_row = _mapping(horizons.get(str(horizon)))
    cohort_row = _mapping(horizon_row.get(cohort))
    state_row = _mapping(cohort_row.get(state))
    return _mapping(state_row.get("feature_separation"))


def _stable_direction(
    fit_auc: float | None,
    calibration_auc: float | None,
) -> str | None:
    if fit_auc is None or calibration_auc is None:
        return None
    if fit_auc >= 0.55 and calibration_auc >= 0.55:
        return "higher"
    if fit_auc <= 0.45 and calibration_auc <= 0.45:
        return "lower"
    return None


def _direction_matches(direction: str, auc: float | None) -> bool | None:
    if auc is None:
        return None
    if direction == "higher":
        return auc > 0.5
    if direction == "lower":
        return auc < 0.5
    return None


def _rows_at_horizon(
    aligned: Mapping[tuple[str, str], Mapping[int, Mapping[str, object] | None]],
    horizon: int,
) -> dict[tuple[str, str], Mapping[str, object]]:
    return {
        pair: row
        for pair, by_horizon in aligned.items()
        if (row := by_horizon.get(horizon)) is not None
    }


def _blocker_counts(
    pairs: set[tuple[str, str]],
    aligned_rows: Mapping[tuple[str, str], Mapping[str, object]],
    fallback_rows: Mapping[tuple[str, str], Mapping[str, object]],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for pair in pairs - set(aligned_rows):
        fallback = fallback_rows.get(pair)
        if fallback is not None:
            counts.update(_row_blockers(fallback))
    return dict(sorted(counts.items()))


def _row_blockers(row: Mapping[str, object]) -> list[str]:
    blockers = [str(value) for value in row.get("shared_lane_blockers") or []]
    if row.get("profitability_gate_passed") is False:
        blockers.append(str(row.get("profitability_gate_reason") or "profitability_gate"))
    if row.get("current_momentum_gate_passed") is False:
        blockers.append("support_below_55")
    return sorted(set(blockers))


def _formal_touch_times(
    orders: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for order in orders:
        if str(order.get("lane") or order.get("board_lane") or "") != "first_board":
            continue
        pair = _row_pair(order)
        touch_time = str(order.get("buy_time") or order.get("signal_time") or "")[:8]
        if not all(pair) or not touch_time:
            continue
        current = result.get(pair)
        if current is None or touch_time < current:
            result[pair] = touch_time
    return result


def _rows_by_pair(
    rows: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str], list[Mapping[str, object]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        pair = _row_pair(row)
        if all(pair):
            grouped[pair].append(row)
    return dict(grouped)


def _filter_prefix_dates(
    rows: Sequence[Mapping[str, object]],
    allowed_dates: set[date] | None,
) -> list[Mapping[str, object]]:
    if allowed_dates is None:
        return list(rows)
    return [row for row in rows if _as_date(row.get("signal_date")) in allowed_dates]


def _filter_order_dates(
    rows: Sequence[Mapping[str, object]],
    allowed_dates: set[date] | None,
) -> list[Mapping[str, object]]:
    if allowed_dates is None:
        return list(rows)
    return [
        row
        for row in rows
        if _as_date(row.get("entry_date") or row.get("signal_date")) in allowed_dates
    ]


def _outcome_attribution(order: Mapping[str, object]) -> dict[str, object]:
    outcome = order.get("outcome")
    return {
        "result_date": str(order.get("result_date") or "")[:10] or None,
        "d_board_status": order.get("d_board_status"),
        "outcome": dict(outcome) if isinstance(outcome, Mapping) else {},
    }


def _feature_value(row: Mapping[str, object], field: str) -> float | None:
    direct = _number(row.get(field))
    if direct is not None:
        return direct
    for container_name in ("ignition_features", "features"):
        container = row.get(container_name)
        if isinstance(container, Mapping):
            value = _number(container.get(field))
            if value is not None:
                return value
    return None


def _row_pair(row: Mapping[str, object]) -> tuple[str, str]:
    return (
        str(row.get("vt_symbol") or ""),
        str(row.get("signal_date") or row.get("entry_date") or "")[:10],
    )


def _distribution(values: Sequence[float | int]) -> dict[str, object]:
    numeric = sorted(float(value) for value in values)
    return {
        "count": len(numeric),
        "p25": _quantile(numeric, 0.25),
        "median": _quantile(numeric, 0.50),
        "p75": _quantile(numeric, 0.75),
        "maximum": round(max(numeric), 4) if numeric else None,
    }


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(float(values[0]), 4)
    index = (len(values) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    value = values[lower] + (values[upper] - values[lower]) * (index - lower)
    return round(float(value), 4)


def _median(values: Sequence[float | int]) -> float | None:
    return round(float(median(values)), 4) if values else None


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator else None


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _fraction(row: Mapping[str, object]) -> str:
    return f"{row.get('reachable_count', 0)}/{row.get('positive_pair_count', 0)}"


def _display(value: object) -> str:
    parsed = _number(value)
    return f"{parsed:.4f}" if parsed is not None else "-"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reverse formal touch prefixes")
    parser.add_argument("command", choices=("evaluate",))
    parser.add_argument("--sessions", type=int, default=60)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = evaluate_reverse_study(session_count=args.sessions)
    if args.format == "markdown":
        print(render_reverse_markdown(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


def evaluate_reverse_study(*, session_count: int = 60) -> dict[str, object]:
    from alphaagent.server.services.limit_up import history_repository
    from alphaagent.server.services.limit_up.history_service import (
        get_scheduled_history_backtest,
    )
    from alphaagent.server.services.limit_up.preboard_momentum_data import (
        attach_preboard_prior_evidence,
        load_five_minute_coverage,
        load_preboard_manifest,
        load_preboard_minute_bars,
        load_reliable_trade_dates,
    )
    from alphaagent.server.services.limit_up.preboard_strategy_study import (
        FEATURE_LOOKBACK_SESSIONS,
        _account_summary,
        _baseline_account_orders_by_phase,
        _build_all_strategy_prefix_rows,
        _coverage_report,
        _date_split,
        _feature_index,
        _formal_orders,
        _load_bounded_feature_frame,
        _load_financial_index,
        compare_baseline_summaries,
    )
    from alphaagent.server.services.limit_up.versions import HISTORY_STRATEGY_VERSION

    manifest = load_preboard_manifest(session_count=session_count)
    if manifest.empty:
        return _blocked_reverse_report("blocked_by_manifest", session_count)
    dates = sorted(
        {
            parsed
            for value in manifest["trade_date"]
            if (parsed := _as_date(value)) is not None
        }
    )
    if not dates:
        return _blocked_reverse_report("blocked_by_manifest_dates", session_count)
    start, end = dates[0], dates[-1]
    history_days = history_repository.load_history_range(
        HISTORY_STRATEGY_VERSION,
        None,
        end,
        False,
    )
    scoped_history_days = [
        day
        for day in history_days
        if start <= (_as_date(day.get("trade_date")) or date.min) <= end
    ]
    manifest = attach_preboard_prior_evidence(manifest, history_days)
    coverage = load_five_minute_coverage(manifest)
    coverage_report = _coverage_report(manifest, coverage)
    if float(coverage_report["complete_pair_pct"]) < 95.0:
        return {
            **_blocked_reverse_report("blocked_by_minute_coverage", session_count),
            "coverage": coverage_report,
        }

    complete_pairs = {
        (str(row.vt_symbol), _as_date(row.trade_date) or date.min)
        for row in coverage.loc[coverage["coverage_status"].eq("complete")].itertuples()
    }
    minute_rows = load_preboard_minute_bars(manifest)
    feature_frame, feature_coverage = _load_bounded_feature_frame(
        manifest,
        lookback_sessions=FEATURE_LOOKBACK_SESSIONS,
    )
    feature_by_pair = _feature_index(feature_frame, set(dates))
    financial_index = _load_financial_index()
    prefix_rows, filter_audit = _build_all_strategy_prefix_rows(
        manifest,
        minute_rows,
        complete_pairs,
        feature_by_pair,
        financial_index,
    )
    fit_dates, calibration_dates, validation_dates = _date_split(dates)
    formal_orders, profitability_audit = _formal_orders(
        history_days,
        scoped_history_days,
        start,
        end,
    )
    formal_symbols = sorted(
        {
            str(order.get("vt_symbol") or "")
            for order in formal_orders
            if str(order.get("vt_symbol") or "")
        }
    )
    result_dates = [
        parsed
        for order in formal_orders
        if (parsed := _as_date(order.get("result_date"))) is not None
    ]
    account_end = max(result_dates, default=end)
    formal_bars = history_repository.load_account_daily_bars(
        formal_symbols,
        start,
        account_end,
    )
    trade_dates = load_reliable_trade_dates(start, account_end)
    baseline_account_orders = _baseline_account_orders_by_phase(
        formal_orders,
        formal_bars,
        trade_dates,
        fit_dates=set(fit_dates),
        calibration_dates=set(calibration_dates),
        validation_dates=set(validation_dates),
    )
    reverse = build_reverse_report(
        prefix_rows,
        formal_orders,
        baseline_account_orders,
        fit_dates=set(fit_dates),
        calibration_dates=set(calibration_dates),
        validation_dates=set(validation_dates),
    )
    service_baseline = get_scheduled_history_backtest(start, end, trade_limit=None)
    expected_summary = _mapping(service_baseline.get("summary"))
    actual_summary = _account_summary(
        formal_orders,
        formal_bars,
        trade_dates,
        cost_multiplier=1.0,
    )
    baseline_parity = compare_baseline_summaries(expected_summary, actual_summary)
    status = (
        "ready_reverse_diagnostic"
        if baseline_parity.get("passed") is True
        else "blocked_by_baseline_mismatch"
    )
    return {
        **reverse,
        "status": status,
        "decision": "reverse_structure_only_requires_causal_forward_model",
        "scope": {
            "requested_session_count": int(session_count),
            "session_count": len(dates),
            "date_start": start.isoformat(),
            "date_end": end.isoformat(),
            "fit_dates": [value.isoformat() for value in fit_dates],
            "calibration_dates": [value.isoformat() for value in calibration_dates],
            "validation_dates": [value.isoformat() for value in validation_dates],
        },
        "coverage": {**coverage_report, **feature_coverage},
        "filter_audit": {
            **filter_audit,
            "formal_profitability_filter": profitability_audit,
        },
        "baseline_parity": baseline_parity,
        "contract": {
            "reverse_horizons_trading_minutes": list(REVERSE_HORIZONS),
            "cumulative_state": "ever_observed_no_later_than_horizon_cutoff",
            "snapshot_state": "nearest_completed_prefix_to_horizon_cutoff",
            "raw_state": "snapshot_gain_gte_3_before_first_touch_after_profitability_gate",
            "shared_state": "snapshot_unchanged_lane_and_support_filters",
            "matched_controls": "same_date_exact_completed_prefix_time",
            "feature_fields": list(BASELINE_FEATURE_NAMES),
            "ranking_fields": list(RANKING_FIELDS),
            "reverse_timestamp_is_live_feature": False,
            "formal_strategy_changed": False,
        },
        "limitations": [
            "80/100/120-session manifests have no complete five-minute pairs before the existing 60-session window.",
            "The final twenty sessions were already viewed and cannot select a rule or support a new unbiased claim.",
            "Reverse touch alignment is an outcome diagnostic and must never be read by a live recommendation.",
            "Five-minute bars cannot recover second-level order flow, queue position, or true large-order direction.",
        ],
    }


def _blocked_reverse_report(status: str, session_count: int) -> dict[str, object]:
    return {
        "study_version": STUDY_VERSION,
        "status": status,
        "decision": "no_reverse_result",
        "scope": {"requested_session_count": int(session_count)},
        "production_changed": False,
    }


if __name__ == "__main__":
    main()
