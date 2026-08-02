"""潜龙首板触发样本归因（胜负/封板成败对照研究）。

输入：``leader_minute_backtest --dump-trigger-samples`` 导出的全部触发样本
（D-1 因子 + 打板过程分时特征 + 封板结局 board_status + D+1 净赢标签）。

回答三个问题（主人 2026-08-01 指定维度）：

1. **成功的票 vs 失败的票，特征差在哪**——位置（20 日区间/均线乖离/半年位置）、
   前序量能（换手率/量比/单日量能比）、分时（跳空/距涨停/触发类型/触发时点/
   触发前盘整/触发 bar 量比）。
2. **怎么提高胜率**——找胜负区分度最高的可交易特征（触发时点可观测）。
3. **怎么提高触板成功率**——sealed vs no_limit 的对照（触板失败是最大亏损来源，
   v4-B 大亏笔全是 no_limit 冲板失败）。

所有特征均为触发时点及之前可观测（无未来函数）；``is_leader``（D+1 净赢）与
``board_status`` 是结局标签，仅用于对照分组。

研究脚本只读 JSON 证据文件，不连数据库、不触碰实时链路。
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from alphaagent.server.services.limit_up.consecutive_leader_first_board_factor_research import (
    _auc,
    _auc_direction,
)
from alphaagent.server.services.limit_up.leader_first_board_deep_factor_research import (
    _bool,
    _number,
    _sample_float,
)

STUDY_VERSION = "leader-trigger-postmortem-v1"
MIN_QUINTILE_SAMPLES = 20

# 三类维度（位置 / 前序量能 / 分时）+ 已有白名单因子同表对照
FEATURE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "位置（前序交易日）",
        (
            "position_20d",
            "bias_ma5_pct",
            "bias_ma20_pct",
            "drawdown_from_126d_high_pct",
            "position_126d",
            "return_20d_pct",
            "prior_return_5d_pct",
            "prior_4_10d_up_days",
        ),
    ),
    (
        "前序量能",
        (
            "turnover_rate",
            "volume_ratio_5_60",
            "turnover_1d_vs_20d",
            "turnover_ratio_3d_vs_prev7d",
            "float_market_cap",
        ),
    ),
    (
        "分时（打板过程）",
        (
            "open_gap_pct",
            "distance_to_limit_at_trigger_pct",
            "cum_pct",
            "surge_pct_at_trigger",
            "trigger_index",
            "pre_trigger_consolidation_pct",
            "trigger_volume_ratio",
        ),
    ),
    (
        "板块/基因",
        (
            "concept_max_return_20d",
            "prior_limit_count_126",
            "prior_limit_count_20",
        ),
    ),
)
ALL_FEATURE_KEYS = tuple(key for _, keys in FEATURE_GROUPS for key in keys)

CUM_BUCKETS = ((None, 2.0), (2.0, 4.0), (4.0, 6.0), (6.0, 8.0), (8.0, None))
DIST_BUCKETS = ((None, -8.0), (-8.0, -5.0), (-5.0, -3.0), (-3.0, -1.5), (-1.5, None))


# ── 分组统计 ───────────────────────────────────────────────────────────


def _labeled(samples: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """只要标签齐全的样本（D+1 已结算 + 封板结局已知）。"""

    return [
        sample
        for sample in samples
        if sample.get("is_leader") is not None and sample.get("board_status")
    ]


def _group_stats(samples: Sequence[Mapping[str, object]]) -> dict[str, object]:
    total = len(samples)
    if not total:
        return {"total": 0}
    wins = sum(1 for sample in samples if _bool(sample.get("is_leader")))
    sealed = sum(1 for sample in samples if sample.get("board_status") == "sealed")
    touched = sum(
        1 for sample in samples if sample.get("board_status") in ("sealed", "failed")
    )
    sealed_win = sum(
        1
        for sample in samples
        if sample.get("board_status") == "sealed" and _bool(sample.get("is_leader"))
    )
    return {
        "total": total,
        "win_rate": round(wins / total, 4),
        "seal_rate": round(sealed / total, 4),
        "touch_rate": round(touched / total, 4),
        "sealed_win_share": round(sealed_win / total, 4),
        "sealed_win_rate": round(sealed_win / sealed, 4) if sealed else None,
    }


def compare_feature(
    samples: Sequence[Mapping[str, object]],
    factor_key: str,
    *,
    buckets: int = 5,
) -> dict[str, object]:
    """单因子：vs 胜率 AUC、vs 封板率 AUC、分位桶（胜率+封板率）。"""

    win_pos = [
        value
        for sample in samples
        if (value := _sample_float(sample.get(factor_key))) is not None
        and _bool(sample.get("is_leader"))
    ]
    win_neg = [
        value
        for sample in samples
        if (value := _sample_float(sample.get(factor_key))) is not None
        and not _bool(sample.get("is_leader"))
    ]
    seal_pos = [
        value
        for sample in samples
        if (value := _sample_float(sample.get(factor_key))) is not None
        and sample.get("board_status") == "sealed"
    ]
    seal_neg = [
        value
        for sample in samples
        if (value := _sample_float(sample.get(factor_key))) is not None
        and sample.get("board_status") != "sealed"
    ]
    win_auc = _auc(win_pos, win_neg)
    seal_auc = _auc(seal_pos, seal_neg)
    valued = sorted(
        (
            (value, sample)
            for sample in samples
            if (value := _sample_float(sample.get(factor_key))) is not None
        ),
        key=lambda item: item[0],
    )
    quintiles: list[dict[str, object]] = []
    total = len(valued)
    if total >= max(buckets, MIN_QUINTILE_SAMPLES):
        for index in range(buckets):
            chunk = valued[index * total // buckets : (index + 1) * total // buckets]
            if not chunk:
                continue
            members = [sample for _, sample in chunk]
            stats = _group_stats(members)
            quintiles.append(
                {
                    "quintile": index + 1,
                    "total": len(members),
                    "win_rate": stats.get("win_rate"),
                    "seal_rate": stats.get("seal_rate"),
                    "value_min": round(chunk[0][0], 4),
                    "value_max": round(chunk[-1][0], 4),
                }
            )
    return {
        "factor_key": factor_key,
        "sample_count": len(win_pos) + len(win_neg),
        "win_auc": round(win_auc, 4) if win_auc is not None else None,
        "win_direction": _auc_direction(win_auc),
        "seal_auc": round(seal_auc, 4) if seal_auc is not None else None,
        "seal_direction": _auc_direction(seal_auc),
        "quintiles": quintiles,
    }


def compare_trigger_kind(samples: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """触发类型（surge 急拉 vs cum 阴涨）× 时段分组对照。"""

    rows: list[dict[str, object]] = []
    for kind in ("surge", "cum"):
        members = [sample for sample in samples if sample.get("trigger_kind") == kind]
        rows.append({"trigger_kind": kind, **_group_stats(members)})
    return rows


def build_cum_distance_matrix(
    samples: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """cum 涨幅桶 × 触发时距涨停桶 的胜率/封板率矩阵。"""

    def _bucket(value: float | None, edges: Sequence[tuple[float | None, float | None]]) -> int | None:
        if value is None:
            return None
        for index, (low, high) in enumerate(edges):
            if (low is None or value >= low) and (high is None or value < high):
                return index
        return None

    cells: dict[tuple[int, int], list[Mapping[str, object]]] = defaultdict(list)
    for sample in samples:
        cum_index = _bucket(_sample_float(sample.get("cum_pct")), CUM_BUCKETS)
        dist_index = _bucket(
            _sample_float(sample.get("distance_to_limit_at_trigger_pct")), DIST_BUCKETS
        )
        if cum_index is None or dist_index is None:
            continue
        cells[(cum_index, dist_index)].append(sample)
    rows: list[dict[str, object]] = []
    for cum_index, (cum_low, cum_high) in enumerate(CUM_BUCKETS):
        for dist_index, (dist_low, dist_high) in enumerate(DIST_BUCKETS):
            members = cells.get((cum_index, dist_index), [])
            if len(members) < MIN_QUINTILE_SAMPLES:
                continue
            stats = _group_stats(members)
            rows.append(
                {
                    "cum_bucket": f"{cum_low if cum_low is not None else ''}-{cum_high if cum_high is not None else ''}",
                    "dist_bucket": f"{dist_low if dist_low is not None else ''}..{dist_high if dist_high is not None else ''}",
                    **stats,
                }
            )
    return rows


def build_postmortem_report(
    samples: Sequence[Mapping[str, object]],
    *,
    source: str = "",
) -> dict[str, object]:
    """编排归因报告（纯函数）。"""

    labeled = _labeled(samples)
    baseline = _group_stats(labeled)
    by_status: dict[str, dict[str, object]] = {}
    for status in ("sealed", "failed", "no_limit"):
        by_status[status] = _group_stats(
            [sample for sample in labeled if sample.get("board_status") == status]
        )
    feature_reports = {
        key: compare_feature(labeled, key) for key in ALL_FEATURE_KEYS
    }
    # 排名：max(|win_auc-0.5|, |seal_auc-0.5|) 效应降序
    ranking = sorted(
        feature_reports.values(),
        key=lambda item: max(
            abs((item.get("win_auc") or 0.5) - 0.5),
            abs((item.get("seal_auc") or 0.5) - 0.5),
        ),
        reverse=True,
    )
    return {
        "status": "ok" if labeled else "insufficient_data",
        "mode": "leader_trigger_postmortem",
        "execution_valid": False,
        "study_version": STUDY_VERSION,
        "source": source,
        "trigger_count": len(samples),
        "labeled_count": len(labeled),
        "baseline": baseline,
        "by_board_status": by_status,
        "feature_ranking": [
            {
                "factor_key": item["factor_key"],
                "win_auc": item["win_auc"],
                "win_direction": item["win_direction"],
                "seal_auc": item["seal_auc"],
                "seal_direction": item["seal_direction"],
            }
            for item in ranking
        ],
        "feature_reports": feature_reports,
        "trigger_kind": compare_trigger_kind(labeled),
        "cum_distance_matrix": build_cum_distance_matrix(labeled),
        "feature_groups": [
            {"group": group, "keys": list(keys)} for group, keys in FEATURE_GROUPS
        ],
        "notes": [
            "is_leader = D+1 净赢标签（paper 模拟扣费）；board_status = 日线收盘结局。",
            "触板成功率口径：sealed = 收盘封板；failed = 盘中触板未封住；no_limit = 未触板。",
            "全部特征为触发时点及之前可观测，无未来函数；分桶结论为小样本线索，须前向验证。",
        ],
    }


# ── Markdown 渲染 ──────────────────────────────────────────────────────


def render_markdown(result: Mapping[str, object]) -> str:
    baseline = _mapping(result.get("baseline"))
    by_status = _mapping(result.get("by_board_status"))
    lines = [
        "# 潜龙首板触发样本归因（胜负/封板成败对照）",
        "",
        "## Boundary",
        "",
        f"- 状态：`{result.get('status')}`；来源 `{result.get('source') or '-'}`。",
        f"- 触发样本 {_integer(result.get('trigger_count'))} 个，标签齐全 {_integer(result.get('labeled_count'))} 个。",
        "- 特征全部触发时点可观测（无未来函数）；is_leader/board_status 是结局标签仅作对照。",
        "",
        "## 基线",
        "",
        f"- 胜率 {_pct(baseline.get('win_rate'))}｜封板率 {_pct(baseline.get('seal_rate'))}"
        f"｜触板率 {_pct(baseline.get('touch_rate'))}｜封板且 D+1 赢占比 {_pct(baseline.get('sealed_win_share'))}"
        f"｜封板后 D+1 胜率 {_pct(baseline.get('sealed_win_rate'))}",
        "",
        "| 结局 | 样本 | 占比 | D+1胜率 |",
        "|---|---:|---:|---:|",
    ]
    total = _integer(baseline.get("total")) or 1
    for status, label in (("sealed", "封板"), ("failed", "触板未封"), ("no_limit", "未触板")):
        stats = _mapping(by_status.get(status))
        count = _integer(stats.get("total"))
        lines.append(
            f"| {label} | {count} | {count / total * 100:.1f}% | {_pct(stats.get('win_rate'))} |"
        )
    lines.extend(
        [
            "",
            "## 因子排行（vs 胜率 AUC 与 vs 封板率 AUC，按最大效应排序）",
            "",
            "| 因子 | 胜率AUC | 方向 | 封板AUC | 方向 |",
            "|---|---:|---|---:|---|",
        ]
    )
    for item in result.get("feature_ranking") or []:
        row = _mapping(item)
        lines.append(
            f"| {row.get('factor_key')} | {_fmt(row.get('win_auc'))} | {row.get('win_direction')} | "
            f"{_fmt(row.get('seal_auc'))} | {row.get('seal_direction')} |"
        )
    kind_rows = result.get("trigger_kind") or []
    if kind_rows:
        lines.extend(
            [
                "",
                "## 触发类型对照",
                "",
                "| 类型 | 样本 | 胜率 | 封板率 | 触板率 | 封板后胜率 |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in kind_rows:
            item = _mapping(row)
            label = "surge 急拉（1分钟≥2%）" if item.get("trigger_kind") == "surge" else "cum 阴涨（累计≥7%）"
            lines.append(
                f"| {label} | {_integer(item.get('total'))} | {_pct(item.get('win_rate'))} | "
                f"{_pct(item.get('seal_rate'))} | {_pct(item.get('touch_rate'))} | {_pct(item.get('sealed_win_rate'))} |"
            )
    matrix = result.get("cum_distance_matrix") or []
    if matrix:
        lines.extend(
            [
                "",
                "## cum 涨幅 × 触发时距涨停 矩阵（只列 n≥20 格）",
                "",
                "| cum 桶 | 距涨停桶 | 样本 | 胜率 | 封板率 |",
                "|---|---|---:|---:|---:|",
            ]
        )
        for row in matrix:
            item = _mapping(row)
            lines.append(
                f"| {item.get('cum_bucket')} | {item.get('dist_bucket')} | {_integer(item.get('total'))} | "
                f"{_pct(item.get('win_rate'))} | {_pct(item.get('seal_rate'))} |"
            )
    reports = _mapping(result.get("feature_reports"))
    lines.extend(["", "## Top 因子分位明细", ""])
    for item in (result.get("feature_ranking") or [])[:10]:
        key = str(_mapping(item).get("factor_key") or "")
        report = _mapping(reports.get(key))
        quintiles = report.get("quintiles") or []
        if not quintiles:
            continue
        lines.extend(
            [
                f"### {key}（胜率AUC {_fmt(report.get('win_auc'))} / 封板AUC {_fmt(report.get('seal_auc'))}）",
                "",
                "| 分位 | 样本 | 胜率 | 封板率 | 区间下限 | 区间上限 |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for quintile in quintiles:
            row = _mapping(quintile)
            lines.append(
                f"| Q{_integer(row.get('quintile'))} | {_integer(row.get('total'))} | "
                f"{_pct(row.get('win_rate'))} | {_pct(row.get('seal_rate'))} | "
                f"{_fmt(row.get('value_min'))} | {_fmt(row.get('value_max'))} |"
            )
        lines.append("")
    lines.extend(["## Evidence Boundary", ""])
    for note in result.get("notes") or []:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _integer(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _fmt(value: object) -> str:
    number = _number(value)
    return f"{number:.4f}" if number is not None else "-"


def _pct(value: object) -> str:
    number = _number(value)
    return f"{number * 100:.2f}%" if number is not None else "-"


def main(argv: Sequence[str] | None = None) -> None:
    """Read a backtest JSON with trigger_samples and write the postmortem report."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    arguments = parser.parse_args(argv)

    payload = json.loads(arguments.input.read_text(encoding="utf-8"))
    samples = payload.get("trigger_samples") or []
    result = build_postmortem_report(samples, source=arguments.input.name)
    arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.json_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    arguments.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.markdown_output.write_text(render_markdown(result), encoding="utf-8")


if __name__ == "__main__":
    main()
