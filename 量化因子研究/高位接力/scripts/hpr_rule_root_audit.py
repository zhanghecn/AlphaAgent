"""逐口诀寻根研究：通过生产判定重放规则变体，不写生产代码或数据库。"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from alphaagent.server.services.high_relay import contracts, pool
from hpr_hidden_range_research import summarize


def _value(row: pd.Series, column: str):
    value = row.get(column)
    return None if value is None or pd.isna(value) else value


def _label(scheme: dict | None) -> str:
    if not scheme:
        return "—"
    no, sub = str(scheme["no"]), str(scheme.get("sub") or "")
    return f"{no}·{sub}" if sub else no


def branch_catalog() -> list[dict[str, object]]:
    branches = [{"no": str(s["no"]), "sub": str(s.get("sub") or ""), "era": "strong", "scheme": s}
                for s in contracts.SCHEMES]
    branches += [{"no": str(s["no"]), "sub": str(s.get("sub") or ""), "era": "weak", "scheme": s}
                 for s in contracts.WEAK_SCHEMES]
    return branches


def match_strong(events: pd.DataFrame, schemes: list[dict] | None = None) -> pd.Series:
    original = contracts.SCHEMES
    contracts.SCHEMES = schemes if schemes is not None else original
    try:
        labels = []
        for _, row in events.iterrows():
            hit = pool.tag_scheme(
                str(row["四组"]), _value(row, "b1开盘%"), _value(row, "b2开盘%"),
                _value(row, "b3开盘%"), auction_pct=_value(row, "买入开盘%"),
                b2_turn=_value(row, "b2换手%"), b3_turn=_value(row, "b3换手%"),
                foundation_chg=_value(row, "地基涨跌%"), pre10_pct=_value(row, "前10日涨幅%"),
                foundation_pose=_value(row, "地基姿态"), anchor_pos=_value(row, "锚位%"),
                anchor_dist=_value(row, "锚距"), dist_ma10=_value(row, "距MA10%"),
                chain_lower_sum=_value(row, "chain_lower_sum"),
                pre20_max_drawdown=_value(row, "pre20_max_drawdown"))
            labels.append(_label(hit))
        return pd.Series(labels, index=events.index, dtype="object")
    finally:
        contracts.SCHEMES = original


def match_weak(events: pd.DataFrame, schemes: list[dict] | None = None) -> pd.Series:
    original = contracts.WEAK_SCHEMES
    contracts.WEAK_SCHEMES = schemes if schemes is not None else original
    try:
        labels = []
        for _, row in events.iterrows():
            hit = pool.tag_weak(
                str(row["四组"]), _value(row, "b1开盘%"), _value(row, "b2开盘%"),
                _value(row, "b3开盘%"), auction_pct=_value(row, "买入开盘%"),
                b1_turn=_value(row, "b1换手%"), b2_turn=_value(row, "b2换手%"),
                b3_turn=_value(row, "b3换手%"), foundation_chg=_value(row, "地基涨跌%"),
                prev_wave60=_value(row, "前波60日最高板"), dist_h60=_value(row, "距60日新高%"))
            labels.append(_label(hit))
        return pd.Series(labels, index=events.index, dtype="object")
    finally:
        contracts.WEAK_SCHEMES = original


def compare_masks(events: pd.DataFrame, baseline: pd.Series, variant: pd.Series,
                  baseline_universe: pd.Series | None = None) -> dict[str, object]:
    baseline = baseline.reindex(events.index, fill_value=False).astype(bool)
    variant = variant.reindex(events.index, fill_value=False).astype(bool)
    added = ~baseline & variant
    if baseline_universe is not None:
        net_added = added & ~baseline_universe.reindex(events.index, fill_value=False).astype(bool)
    else:
        net_added = added
    return {
        "baseline": summarize(events[baseline]),
        "variant": summarize(events[variant]),
        "kept": summarize(events[baseline & variant]),
        "removed": summarize(events[baseline & ~variant]),
        "added": summarize(events[added]),
        "net_added": summarize(events[net_added]),
    }


def era_frames(events: pd.DataFrame, era: str, include_final: bool) -> dict[str, pd.DataFrame]:
    years = pd.to_datetime(events["买入日"]).dt.year
    if era == "strong":
        periods = {"discovery": events[years.between(2023, 2024)],
                   "validation": events[years == 2025]}
        if include_final:
            periods["final"] = events[years == 2026]
        return periods
    if era == "common":
        periods = {"discovery": events[years <= 2024],
                   "weak_era": events[years <= 2022],
                   "strong_era": events[years.between(2023, 2024)],
                   "validation": events[years == 2025]}
        if include_final:
            periods["final"] = events[years == 2026]
        return periods
    if era == "weak":
        periods = {"discovery": events[years.between(2020, 2021)],
                   "validation": events[years == 2022],
                   "reference": events[years.between(2023, 2025)]}
        if include_final:
            periods["reference"] = events[years >= 2023]
        return periods
    raise ValueError(f"未知口诀时代: {era}")


def research_era(branch: dict[str, object]) -> str:
    return "common" if contracts.is_common_scheme(branch["no"], branch["sub"]) else str(branch["era"])


def baseline_report(events: pd.DataFrame, include_final: bool) -> list[dict[str, object]]:
    strong_labels, weak_labels = match_strong(events), match_weak(events)
    report = []
    for branch in branch_catalog():
        label = branch["no"] + (f'·{branch["sub"]}' if branch["sub"] else "")
        labels = strong_labels if branch["era"] == "strong" else weak_labels
        selected = events[labels == label]
        era = research_era(branch)
        periods = {name: summarize(frame) for name, frame in era_frames(
            selected, era, include_final).items()}
        report.append({"no": branch["no"], "sub": branch["sub"], "era": branch["era"],
                       "research_era": era, "periods": periods})
    return report


AUXILIARY_LEGS = {
    "A1": ("vol2",),
    "A2": ("vol2_when_b1_low", "block_pre10", "dist_ma10_min"),
    "B1·转温": ("vol2",),
    "B2·双低": ("foundation_pose_ok",), "B2·承接": ("foundation_pose_ok",),
    "B3": ("foundation_pose_ok",),
    "C2": ("block_foundation_chg", "block_anchor", "block_pre20_drawdown"),
    "C3·二板一字": ("block_foundation_chg", "block_anchor"),
    "C3·三板一字": ("block_foundation_chg", "block_anchor"),
    "K2": ("foundation_chg_max",),
    "K4·缩量承接": ("b1_turn_min", "vol3_lt_vol2"),
    "K4·一板平开": ("b1_turn_min",),
    "K5": ("prev_wave_max",),
    "K3": ("dist_h60_min",),
}


def _branch_label(branch: dict[str, object]) -> str:
    return str(branch["no"]) + (f'·{branch["sub"]}' if branch["sub"] else "")


def _schemes_with_variant(branch: dict[str, object], changes: dict[str, object]):
    weak = branch["era"] == "weak"
    schemes = copy.deepcopy(contracts.WEAK_SCHEMES if weak else contracts.SCHEMES)
    target = None
    for scheme in schemes:
        if str(scheme["no"]) == branch["no"] and str(scheme.get("sub") or "") == branch["sub"]:
            scheme.update(changes)
            target = scheme
    if target is None:
        raise ValueError(f"找不到口诀分支: {_branch_label(branch)}")
    return schemes, target


def match_branch_labels(events: pd.DataFrame, branch: dict[str, object],
                        changes: dict[str, object] | None = None) -> pd.Series:
    schemes, target = _schemes_with_variant(branch, changes or {})
    relevant = events[events["四组"].isin(target["group4"])]
    labels = match_weak(relevant, schemes) if branch["era"] == "weak" else match_strong(relevant, schemes)
    return labels.reindex(events.index, fill_value="—")


def match_branch(events: pd.DataFrame, branch: dict[str, object],
                 changes: dict[str, object] | None = None) -> pd.Series:
    return match_branch_labels(events, branch, changes) == _branch_label(branch)


def variant_definitions(branch: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    label, scheme = _branch_label(branch), branch["scheme"]
    auxiliary = AUXILIARY_LEGS.get(label, AUXILIARY_LEGS.get(str(branch["no"]), ()))
    definitions: list[tuple[str, dict[str, object]]] = [("完整规则", {})]
    if auxiliary:
        definitions.append(("形态本体", {key: None for key in auxiliary}))
    definitions += [(f"去掉辅助腿·{key}", {key: None}) for key in auxiliary]
    if branch["era"] == "strong":
        for index, interval in enumerate(scheme["chain"]):
            if interval is not None:
                chain = list(scheme["chain"])
                chain[index] = None
                definitions.append((f"放开链条件·b{index + 1}", {"chain": tuple(chain)}))
    else:
        definitions += [(f"放开链条件·{key}", {key: None})
                        for key in ("b1", "b2", "b3") if scheme.get(key) is not None]
    definitions.append(("今天开盘全谱", {"today": (-99.0, 9.5)}))
    for key in ("vol2", "vol3"):
        if scheme.get(key) is not None:
            definitions.append((f"{key}全谱", {key: (0.0, 99.0)}))
    groups = tuple(scheme["group4"])
    if len(groups) == 1:
        group = groups[0]
        mirror = group[:-1] + ("阴" if group.endswith("阳") else "阳")
        definitions.append(("对侧阴阳", {"group4": (mirror,)}))
    switched = tuple(("三接四" if group.startswith("二接三") else "二接三") + group[-1]
                     for group in groups)
    definitions.append(("相邻板位", {"group4": switched}))
    unique: list[tuple[str, dict[str, object]]] = []
    seen = set()
    for name, changes in definitions:
        key = repr(changes)
        if key not in seen:
            seen.add(key)
            unique.append((name, changes))
    return unique


def audit_branch(events: pd.DataFrame, branch: dict[str, object],
                 include_final: bool) -> list[dict[str, object]]:
    baseline_labels = match_branch_labels(events, branch)
    baseline = baseline_labels == _branch_label(branch)
    era = research_era(branch)
    if era == "common":
        baseline_universe = (match_strong(events) != "—") | (match_weak(events) != "—")
    else:
        baseline_universe = ((match_weak(events) if branch["era"] == "weak" else match_strong(events)) != "—")
    frames = era_frames(events, era, include_final)
    report = []
    for name, changes in variant_definitions(branch):
        variant_labels = match_branch_labels(events, branch, changes)
        variant = variant_labels == _branch_label(branch)
        periods = {period: compare_masks(frame, baseline, variant, baseline_universe)
                   for period, frame in frames.items()}
        report.append({"no": branch["no"], "sub": branch["sub"], "variant": name,
                       "changes": changes, "periods": periods})
    return report


def attach_open_entry_returns(events: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    result = events.copy()
    indices = result["_bar_i"].astype(int).to_numpy()
    open_prices = bars["open_price"].iloc[indices].to_numpy(dtype=float)
    e3_exit = pd.to_numeric(result["E3退出价"], errors="coerce").to_numpy(dtype=float)
    e0_exit = (pd.to_numeric(result["买价"], errors="coerce").to_numpy(dtype=float)
               * (1 + pd.to_numeric(result["持有到断板%"], errors="coerce").to_numpy(dtype=float) / 100))
    result["开盘买E3%"] = np.round((e3_exit / open_prices - 1) * 100, 2)
    result["开盘买E0%"] = np.round((e0_exit / open_prices - 1) * 100, 2)
    high = bars["high_price"].iloc[indices].to_numpy(dtype=float)
    limit = bars["limit_price"].iloc[indices].to_numpy(dtype=float)
    result["当日触板"] = high >= limit - 1e-6
    return result


def build_all_day_events():
    """仅放开事件枚举的触板要求；其余池、判定和退出逻辑全部复用生产实现。"""
    from alphaagent.server.services.high_relay import backtest

    original = backtest.pool_mod.derive_daily

    def derive_all_days(bars):
        derived = original(bars)
        derived["touch"] = True
        return derived

    backtest.pool_mod.derive_daily = derive_all_days
    try:
        return backtest.build_events()
    finally:
        backtest.pool_mod.derive_daily = original


def load_research_events(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(f"研究数据不存在: {path}；请先在 API 容器执行 build")
    events = pd.read_csv(path, parse_dates=["买入日"])
    if len(events) != 6370:
        raise SystemExit(f"研究数据应为 6370 笔，实际 {len(events)} 笔；请执行 build 重建")
    required = {"_bar_i", "买入日", "方案点", "弱口诀", "E3%"}
    missing = required - set(events.columns)
    if missing:
        raise SystemExit(f"研究数据缺少字段 {sorted(missing)}；请执行 build 重建")
    return events


def _column_stats(frame: pd.DataFrame, column: str) -> dict[str, object]:
    renamed = frame.copy()
    renamed["E3%"] = pd.to_numeric(renamed[column], errors="coerce")
    return summarize(renamed)


def open_entry_report(events: pd.DataFrame) -> dict[str, object]:
    strong_labels = events["方案点"].fillna("—")
    weak_labels = events["弱口诀"].fillna("—")
    report: dict[str, object] = {}
    for no in ("B2", "C1", "K4"):
        selected = events[weak_labels == no] if no == "K4" else events[strong_labels == no]
        era = "weak" if no == "K4" else "strong"
        periods = {}
        for period, frame in era_frames(selected, era, include_final=False).items():
            touch = frame["当日触板"].astype(bool)
            periods[period] = {
                "current_touch": _column_stats(frame[touch], "E3%"),
                "open_touch": _column_stats(frame[touch], "开盘买E3%"),
                "open_non_touch": _column_stats(frame[~touch], "开盘买E3%"),
                "open_all": _column_stats(frame, "开盘买E3%"),
            }
        report[no] = periods
    return report


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    if contracts.HPR_RULES_VERSION != "hpr-v7.22":
        raise SystemExit(f"研究基线仅适用于 hpr-v7.22，当前为 {contracts.HPR_RULES_VERSION}，请重建事件数据")
    data_path = Path("/tmp/hpr_hidden_range_events.csv")
    all_day_path = Path("/tmp/hpr_all_day_events.csv")
    if command == "build":
        from hpr_hidden_range_research import build_dataset
        dataset = build_dataset(Path("/tmp/hpr_hidden_range_events.pkl"))
        print(f"已重建 {len(dataset)} 个事件并生成 pickle/CSV/月状态文件")
    elif command == "build-open-entry":
        dataset, bars = build_all_day_events()
        dataset = dataset[~dataset["未完"]].copy()
        dataset = attach_open_entry_returns(dataset, bars)
        dataset.to_pickle(all_day_path.with_suffix(".pkl"))
        dataset.to_csv(all_day_path, index=False)
        print(f"已重建 {len(dataset)} 个全日事件，其中触板 {int(dataset['当日触板'].sum())} 个")
    elif command == "open-entry":
        if not all_day_path.exists():
            raise SystemExit(f"全日数据不存在: {all_day_path}；请先执行 build-open-entry")
        dataset = pd.read_csv(all_day_path, parse_dates=["买入日"])
        if len(dataset) != 13216 or int(dataset["当日触板"].sum()) != 6370:
            raise SystemExit("全日事件或触板数量不匹配；请执行 build-open-entry 重建")
        report = open_entry_report(dataset)
        output = Path("/tmp/hpr_open_entry_report.json")
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif command == "baseline":
        events = load_research_events(data_path)
        report = baseline_report(events, include_final=False)
        output = Path("/tmp/hpr_rule_root_baseline.json")
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif command == "audit":
        events = load_research_events(data_path)
        report = []
        for branch in branch_catalog():
            print("auditing", _branch_label(branch), flush=True)
            report.extend(audit_branch(events, branch, include_final=False))
        output = Path("/tmp/hpr_rule_root_audit.json")
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"共审计 {len(report)} 个变体，结果写入 {output}；未读取 2026 最终测试段。")
    else:
        raise SystemExit(f"未知命令: {command}；可用 build / baseline / audit / build-open-entry / open-entry")
