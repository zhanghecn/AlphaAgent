"""扫板质量研究：触板瞬间特征 → 封得住/回封预判（主人的「选票问题」假说验证）。

动机（主人 2026-08-01）：扫板与分钟级共用因子、票质相当，炸板率高说明
**问题在选票不在机制**——庄家封板后会微开测试跟随度，扫板够快能抢到；
关键是触板瞬间的特征（第一个触板金额、触板时间等）能否区分
「封得住」vs「封不住」、以及开板后「回封」vs「不回封」。

数据集：v4 口径首板候选（主板非 ST + D-1 未涨停 + 深跌排除）在宽覆盖日的
全日 1m bar 扫描。每个触板事件提取**触板瞬间可观测特征**（全部无未来函数）：

- `first_touch_time`：触板时间（早=强）
- `touch_bar_turnover`：第一个触板 bar 成交额（触板金额）
- `touch_volume_ratio`：触板 bar 量 / 触板前分钟均量（带量突破 vs 缩量偷袭）
- `minutes_to_touch`：开盘到触板的分钟数（上板速度）
- `open_gap_pct`：跳空幅度
- `pre_touch_drawdown_pct`：拉升过程自最高点的最大回撤（分歧/流畅度）
- `touch_bar_close_position`：触板 bar 收盘在 bar 内的位置（收在最高=强势锁单）
- D-1 因子：白名单 + position_126d + prior_limit_count_126

结局标签：
- sealed（收盘封板）/ failed（触板未封）/ no_limit（未触板）
- 触板后开板（其后 bar low < 涨停价）：回封（开板且收盘封板）vs 炸板（开板且未封住）

研究只读 PostgreSQL，只写 ``memory/06_backtests`` 证据文件。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

from alphaagent.server.services.limit_up.consecutive_leader_first_board_factor_research import (
    _auc,
    _auc_direction,
)
from alphaagent.server.services.limit_up.domain import main_board_limit_price
from alphaagent.server.services.limit_up.leader_first_board_deep_factor_research import (
    _bool,
    _number,
    _sample_float,
)
from alphaagent.server.services.limit_up.leader_minute_backtest import (
    DEFAULT_MAX_PRIOR_RETURN_20D_PCT,
    _d1_factors,
    _float,
    _is_first_board_candidate,
    _is_main_board,
    _position_filter_pass,
    build_sector_r20_lookup,
    load_stock_names,
)
from alphaagent.server.services.limit_up.repository import (
    load_daily_bars_all,
    load_sector_daily_bars,
    load_sector_memberships_all,
    load_window_minute_bars,
)

STUDY_VERSION = "leader-sweep-quality-v1"
MIN_QUINTILE_SAMPLES = 20

TOUCH_FEATURES = (
    "first_touch_hour",
    "minutes_to_touch",
    "touch_bar_turnover",
    "touch_volume_ratio",
    "open_gap_pct",
    "pre_touch_drawdown_pct",
    "touch_bar_close_position",
    # D-1 因子同表对照
    "concept_max_return_20d",
    "drawdown_from_126d_high_pct",
    "position_126d",
    "return_20d_pct",
    "volume_ratio_5_60",
    "prior_return_5d_pct",
    "prior_limit_count_126",
    "float_market_cap",
)


# ── 触板事件提取 ───────────────────────────────────────────────────────


def analyze_day_bars(
    day_bars: Sequence[Mapping[str, object]],
    *,
    prev_close: float,
    open_price: float,
) -> dict[str, object]:
    """单票单日：触板判定 + 触板瞬间特征 + 开板/回封结局（特征全部触板时点可观测）。"""

    out: dict[str, object] = {
        "touched": False,
        "opened_after_touch": False,
        "first_touch_time": None,
        "first_touch_hour": None,
        "minutes_to_touch": None,
        "touch_bar_turnover": None,
        "touch_volume_ratio": None,
        "open_gap_pct": round((open_price / prev_close - 1) * 100, 4)
        if open_price > 0 and prev_close > 0
        else None,
        "pre_touch_drawdown_pct": None,
        "touch_bar_close_position": None,
    }
    if prev_close <= 0:
        return out
    limit_price = main_board_limit_price(prev_close)
    tolerance = max(0.02, limit_price * 0.001)
    prior_volumes: list[float] = []
    running_high = 0.0
    max_drawdown = 0.0
    touch_index: int | None = None
    for index, bar in enumerate(day_bars):
        high = _float(bar.get("high_price")) or 0.0
        low = _float(bar.get("low_price")) or 0.0
        volume = _float(bar.get("volume"))
        if high > 0:
            running_high = max(running_high, high)
            if low > 0 and running_high > 0:
                max_drawdown = max(max_drawdown, (running_high - low) / running_high * 100)
        if high >= limit_price - tolerance:
            touch_index = index
            break
        if volume is not None and volume > 0:
            prior_volumes.append(volume)
    if touch_index is None:
        return out
    touch_bar = day_bars[touch_index]
    touch_time = str(touch_bar.get("bar_time") or "")
    out["touched"] = True
    out["first_touch_time"] = touch_time
    out["first_touch_hour"] = (
        int(touch_time.split(":")[0]) if touch_time and ":" in touch_time else None
    )
    out["minutes_to_touch"] = touch_index  # 09:31 起第几根 1m bar
    out["touch_bar_turnover"] = _float(touch_bar.get("turnover"))
    touch_volume = _float(touch_bar.get("volume"))
    if touch_volume is not None and prior_volumes and mean(prior_volumes) > 0:
        out["touch_volume_ratio"] = round(touch_volume / mean(prior_volumes), 4)
    out["pre_touch_drawdown_pct"] = round(max_drawdown, 4)
    touch_high = _float(touch_bar.get("high_price"))
    touch_low = _float(touch_bar.get("low_price"))
    touch_close = _float(touch_bar.get("close_price"))
    if touch_high and touch_low and touch_close and touch_high > touch_low:
        out["touch_bar_close_position"] = round(
            (touch_close - touch_low) / (touch_high - touch_low), 4
        )
    # 开板/回封判定（结局标签）
    for bar in day_bars[touch_index + 1 :]:
        low = _float(bar.get("low_price")) or 0.0
        if low and low < limit_price - tolerance:
            out["opened_after_touch"] = True
            out["first_open_time"] = str(bar.get("bar_time") or "")
            break
    return out


def build_sweep_quality_dataset(
    *,
    start: date,
    end: date,
    min_day_coverage: int = 300,
    calendar: Sequence[str],
    bars_by_symbol: Mapping[str, Sequence[Mapping[str, object]]],
    daily_index: Mapping[tuple[str, str], Mapping[str, object]],
    names: Mapping[str, str],
    sector_r20_lookup,
    position_filter: str = "deep_drop_exclusion",
    max_prior_return_20d_pct: float = DEFAULT_MAX_PRIOR_RETURN_20D_PCT,
) -> list[dict[str, object]]:
    """扫板质量数据集：每个触板事件的触板特征 + 结局标签（纯函数）。"""

    prev_map = {
        calendar[i]: (calendar[i - 1] if i > 0 else None) for i in range(len(calendar))
    }
    symbol_dates: dict[str, list[str]] = {
        symbol: [str(bar.get("trade_date") or "") for bar in rows]
        for symbol, rows in bars_by_symbol.items()
    }
    dataset: list[dict[str, object]] = []
    for today in calendar:
        today_date = date.fromisoformat(today)
        prev_day = prev_map.get(today)
        window_bars = load_window_minute_bars(
            today_date, start_time="09:25:00", end_time="15:01:00"
        )
        if len(window_bars) < min_day_coverage:
            continue
        for symbol, bars in window_bars.items():
            if not _is_main_board(symbol):
                continue
            name = names.get(symbol) or symbol
            if "ST" in name.upper():
                continue
            dates = symbol_dates.get(symbol) or []
            try:
                index = dates.index(today)
            except ValueError:
                continue
            bars_all = list(bars_by_symbol[symbol])
            bars_before = bars_all[:index]
            if not _is_first_board_candidate(bars_before):
                continue
            concept_r20 = sector_r20_lookup(symbol, today) if sector_r20_lookup else None
            if not _position_filter_pass(
                bars_before, position_filter, max_prior_return_20d_pct, concept_r20
            ):
                continue
            dbar = daily_index.get((symbol, today))
            prev_bar = daily_index.get((symbol, prev_day)) if prev_day else None
            if not dbar or not prev_bar:
                continue
            open_price = _float(dbar.get("open_price")) or 0.0
            prev_close = _float(prev_bar.get("close_price")) or 0.0
            outcome = analyze_day_bars(bars, prev_close=prev_close, open_price=open_price)
            if not outcome["touched"]:
                continue
            factors = _d1_factors(bars_all[: index + 1], today) or {}
            # 收盘结局（标签）
            day_close = _float(dbar.get("close_price")) or 0.0
            limit_price = main_board_limit_price(prev_close)
            tolerance = max(0.02, limit_price * 0.001)
            sealed = day_close >= limit_price - tolerance
            opened = bool(outcome["opened_after_touch"])
            if sealed:
                board_status = "sealed"
            else:
                day_high = _float(dbar.get("high_price")) or 0.0
                board_status = "failed" if day_high >= limit_price - tolerance else "no_limit"
            dataset.append(
                {
                    "vt_symbol": symbol,
                    "name": name,
                    "trade_date": today,
                    **{key: outcome.get(key) for key in (
                        "first_touch_time", "first_touch_hour", "minutes_to_touch",
                        "touch_bar_turnover", "touch_volume_ratio", "open_gap_pct",
                        "pre_touch_drawdown_pct", "touch_bar_close_position",
                        "opened_after_touch", "first_open_time",
                    )},
                    "opened_after_touch": opened,
                    "board_status": board_status,
                    "resealed": opened and sealed,
                    "crashed": opened and not sealed,
                    "concept_max_return_20d": concept_r20,
                    **{key: factors.get(key) for key in (
                        "drawdown_from_126d_high_pct", "position_126d", "return_20d_pct",
                        "volume_ratio_5_60", "prior_return_5d_pct", "prior_limit_count_126",
                        "float_market_cap",
                    )},
                }
            )
    return dataset


# ── 对照分析 ───────────────────────────────────────────────────────────


def _rates(members: Sequence[Mapping[str, object]], label_key: str) -> dict[str, object]:
    total = len(members)
    if not total:
        return {"total": 0}
    hits = sum(1 for sample in members if _bool(sample.get(label_key)))
    return {"total": total, "rate": round(hits / total, 4), "hits": hits}


def compare_touch_feature(
    samples: Sequence[Mapping[str, object]],
    factor_key: str,
    label_key: str,
    *,
    buckets: int = 5,
) -> dict[str, object]:
    """单因子 vs 标签（sealed/resealed）的 AUC 与分位桶。"""

    pos = [
        value
        for sample in samples
        if (value := _sample_float(sample.get(factor_key))) is not None
        and _bool(sample.get(label_key))
    ]
    neg = [
        value
        for sample in samples
        if (value := _sample_float(sample.get(factor_key))) is not None
        and not _bool(sample.get(label_key))
    ]
    auc = _auc(pos, neg)
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
            rates = _rates([sample for _, sample in chunk], label_key)
            quintiles.append(
                {
                    "quintile": index + 1,
                    "total": len(chunk),
                    "rate": rates.get("rate"),
                    "value_min": round(chunk[0][0], 4),
                    "value_max": round(chunk[-1][0], 4),
                }
            )
    return {
        "factor_key": factor_key,
        "label": label_key,
        "auc": round(auc, 4) if auc is not None else None,
        "direction": _auc_direction(auc),
        "quintiles": quintiles,
    }


def build_sweep_quality_report(dataset: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """编排扫板质量报告（纯函数）。"""

    touched = [sample for sample in dataset if _bool(sample.get("touched", True))]
    sealed = [sample for sample in touched if sample.get("board_status") == "sealed"]
    opened = [sample for sample in touched if _bool(sample.get("opened_after_touch"))]
    resealed = [sample for sample in opened if _bool(sample.get("resealed"))]
    baseline = {
        "touched": len(touched),
        "sealed": len(sealed),
        "seal_rate": round(len(sealed) / len(touched), 4) if touched else None,
        "opened": len(opened),
        "open_rate": round(len(opened) / len(touched), 4) if touched else None,
        "resealed": len(resealed),
        "reseal_rate_given_open": round(len(resealed) / len(opened), 4) if opened else None,
        "sealed_without_open": len(sealed) - len(resealed),
    }
    # 任务 1：触板特征 → 封得住（sealed vs 非 sealed，全触板集）
    seal_reports = {
        key: compare_touch_feature(touched, key, "_sealed_label")
        for key in TOUCH_FEATURES
    }
    # 任务 2：触板特征 → 回封（resealed vs crashed，开板子集）
    reseal_reports = {
        key: compare_touch_feature(opened, key, "_resealed_label")
        for key in TOUCH_FEATURES
    }
    # 时段对照（触板时间分桶）
    hour_buckets: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for sample in touched:
        hour = sample.get("first_touch_hour")
        if hour is None:
            continue
        bucket = (
            "before_10" if hour < 10 else ("10_11" if hour == 10 else ("11_13" if hour < 13 else ("13_14" if hour == 13 else "after_14")))
        )
        hour_buckets[bucket].append(sample)
    hour_rows = [
        {
            "bucket": bucket,
            "total": len(members),
            "seal_rate": _rates(members, "_sealed_label").get("rate"),
            "open_rate": _rates(members, "opened_after_touch").get("rate"),
            "reseal_rate": _rates(
                [sample for sample in members if _bool(sample.get("opened_after_touch"))],
                "_resealed_label",
            ).get("rate"),
        }
        for bucket, members in sorted(hour_buckets.items())
    ]
    return {
        "status": "ok" if touched else "insufficient_data",
        "mode": "leader_sweep_quality_research",
        "execution_valid": False,
        "study_version": STUDY_VERSION,
        "baseline": baseline,
        "seal_feature_reports": seal_reports,
        "reseal_feature_reports": reseal_reports,
        "touch_hour_rows": hour_rows,
        "notes": [
            "触板特征全部触板时点可观测（无未来函数）；board_status/resealed 为收盘结局标签。",
            "reseal_rate_given_open = 开板后回封占比——排板成交（开板才买到）的生存率上限。",
            "样本为宽覆盖日（≥300 票）触板事件，偏活跃股；结论须前向验证。",
        ],
    }


# ── 数据加载编排 ───────────────────────────────────────────────────────


def run_research(*, start: date, end: date, min_day_coverage: int = 300) -> dict[str, object]:
    """Load data and run the sweep quality research."""

    from alphaagent.server.services.limit_up.leader_first_board_deep_factor_research import (
        _bool as deep_bool,
    )

    daily_bars = load_daily_bars_all(start - timedelta(days=320), end + timedelta(days=7))
    names = load_stock_names()
    bars_by_symbol: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for bar in daily_bars:
        bars_by_symbol[str(bar.get("vt_symbol") or "")].append(bar)
    for rows in bars_by_symbol.values():
        rows.sort(key=lambda row: str(row.get("trade_date") or ""))
    daily_index = {
        (str(bar.get("vt_symbol") or ""), str(bar.get("trade_date") or "")): bar
        for bar in daily_bars
    }
    calendar = sorted(
        {
            str(bar.get("trade_date") or "")
            for bar in daily_bars
            if bar.get("trade_date") and start.isoformat() <= str(bar["trade_date"]) <= end.isoformat()
        }
    )
    sector_r20_lookup = build_sector_r20_lookup(
        load_sector_memberships_all(),
        load_sector_daily_bars(start - timedelta(days=190), end),
    )
    dataset = build_sweep_quality_dataset(
        start=start,
        end=end,
        min_day_coverage=min_day_coverage,
        calendar=calendar,
        bars_by_symbol=bars_by_symbol,
        daily_index=daily_index,
        names=names,
        sector_r20_lookup=sector_r20_lookup,
    )
    for sample in dataset:
        sample["_sealed_label"] = sample["board_status"] == "sealed"
        sample["_resealed_label"] = deep_bool(sample.get("resealed"))
    report = build_sweep_quality_report(dataset)
    report["start"] = start.isoformat()
    report["end"] = end.isoformat()
    report["min_day_coverage"] = min_day_coverage
    report["dataset_size"] = len(dataset)
    report["input_fingerprint"] = hashlib.sha256(
        f"{STUDY_VERSION}|{len(dataset)}|{start}|{end}".encode()
    ).hexdigest()[:16]
    return report


# ── Markdown 渲染 ──────────────────────────────────────────────────────


def render_markdown(result: Mapping[str, object]) -> str:
    baseline = _mapping(result.get("baseline"))
    lines = [
        "# 扫板质量研究：触板瞬间特征 → 封得住/回封预判",
        "",
        "## Boundary",
        "",
        f"- 状态：`{result.get('status')}`；窗口 `{result.get('start')}..{result.get('end')}`；"
        f"覆盖口径 ≥{result.get('min_day_coverage')} 票/日。",
        f"- 触板事件 {_integer(baseline.get('touched'))} 个；特征全部触板时点可观测（无未来函数）。",
        "",
        "## 基线",
        "",
        f"- 封板率 {_pct(baseline.get('seal_rate'))}（{_integer(baseline.get('sealed'))}/{_integer(baseline.get('touched'))}）"
        f"｜触板后开板率 {_pct(baseline.get('open_rate'))}（{_integer(baseline.get('opened'))}）"
        f"｜**开板后回封率 {_pct(baseline.get('reseal_rate_given_open'))}**（{_integer(baseline.get('resealed'))}/{_integer(baseline.get('opened'))}，排板成交的生存率上限）"
        f"｜封死未开（买不到的强板）{_integer(baseline.get('sealed_without_open'))} 个。",
        "",
        "## 触板时段 × 结局",
        "",
        "| 触板时段 | 样本 | 封板率 | 开板率 | 开板后回封率 |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in result.get("touch_hour_rows") or []:
        item = _mapping(row)
        lines.append(
            f"| {item.get('bucket')} | {_integer(item.get('total'))} | {_pct(item.get('seal_rate'))} | "
            f"{_pct(item.get('open_rate'))} | {_pct(item.get('reseal_rate'))} |"
        )
    for label, key in (("封得住（全触板集）", "seal_feature_reports"), ("回封（开板子集）", "reseal_feature_reports")):
        reports = _mapping(result.get(key))
        ranking = sorted(
            reports.values(),
            key=lambda item: abs((item.get("auc") or 0.5) - 0.5),
            reverse=True,
        )
        lines.extend(
            [
                "",
                f"## 因子排行 — {label}",
                "",
                "| 因子 | AUC | 方向 |",
                "|---|---:|---|",
            ]
        )
        for item in ranking:
            row = _mapping(item)
            lines.append(
                f"| {row.get('factor_key')} | {_fmt(row.get('auc'))} | {row.get('direction')} |"
            )
        lines.extend(["", "### Top 因子分位明细", ""])
        for item in ranking[:6]:
            row = _mapping(item)
            quintiles = row.get("quintiles") or []
            if not quintiles:
                continue
            lines.extend(
                [
                    f"#### {row.get('factor_key')} (AUC {_fmt(row.get('auc'))})",
                    "",
                    "| 分位 | 样本 | 比率 | 区间下限 | 区间上限 |",
                    "|---|---:|---:|---:|---:|",
                ]
            )
            for quintile in quintiles:
                q = _mapping(quintile)
                lines.append(
                    f"| Q{_integer(q.get('quintile'))} | {_integer(q.get('total'))} | "
                    f"{_pct(q.get('rate'))} | {_fmt(q.get('value_min'))} | {_fmt(q.get('value_max'))} |"
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
    """Run the sweep quality research and write evidence files."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--min-day-coverage", type=int, default=300)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    arguments = parser.parse_args(argv)

    result = run_research(
        start=arguments.start, end=arguments.end, min_day_coverage=arguments.min_day_coverage
    )
    arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.json_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    arguments.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.markdown_output.write_text(render_markdown(result), encoding="utf-8")


if __name__ == "__main__":
    main()
