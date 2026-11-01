"""高位接力隐藏范围特征研究；只复用生产回放，不写生产判定或数据库。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def _ratio(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator and np.isfinite(denominator) else np.nan


def _window_features(frame: pd.DataFrame, prefix: str) -> dict[str, float]:
    close = frame["close_price"].to_numpy(dtype=float)
    prev_close = frame["prev_close"].to_numpy(dtype=float)
    volume = frame["volume"].to_numpy(dtype=float)
    returns = close / prev_close - 1
    typical = (frame["high_price"].to_numpy(dtype=float)
               + frame["low_price"].to_numpy(dtype=float) + close) / 3
    base_close = float(close[-1])
    total_volume = float(np.nansum(volume))
    above = close > base_close
    running_high = np.maximum.accumulate(close)
    return {
        f"{prefix}_up_days": float(np.nansum(returns > 0)),
        f"{prefix}_volatility": float(np.nanstd(returns) * 100),
        f"{prefix}_max_drawdown": float(np.nanmin(close / running_high - 1) * 100),
        f"{prefix}_limit_count": float(np.nansum(frame["is_limit"].to_numpy(dtype=float))),
        f"{prefix}_touch_count": float(np.nansum(frame["touch_limit"].to_numpy(dtype=float))),
        f"{prefix}_failed_limit_count": float(np.nansum(
            frame["touch_limit"].to_numpy(dtype=float) - frame["is_limit"].to_numpy(dtype=float))),
        f"{prefix}_above_close_vol_pct": _ratio(float(np.nansum(volume[above])), total_volume) * 100,
        f"{prefix}_above_close_days_pct": float(np.mean(above) * 100),
        f"{prefix}_vwap_gap": (_ratio(base_close, float(np.nansum(typical * volume) / total_volume)) - 1) * 100,
    }


def _bar_features(frame: pd.DataFrame, index: int, prefix: str) -> dict[str, float]:
    row = frame.iloc[index]
    previous = frame.iloc[max(0, index - 20):index]
    prev_close = float(row["prev_close"])
    high, low = float(row["high_price"]), float(row["low_price"])
    open_price, close = float(row["open_price"]), float(row["close_price"])
    volume, turnover = float(row["volume"]), float(row["turnover_rate"])
    return {
        f"{prefix}_lower": (min(open_price, close) - low) / prev_close * 100,
        f"{prefix}_upper": (high - max(open_price, close)) / prev_close * 100,
        f"{prefix}_body": (close - open_price) / prev_close * 100,
        f"{prefix}_range": (high - low) / prev_close * 100,
        f"{prefix}_close_pos": _ratio(close - low, high - low),
        f"{prefix}_vol20": _ratio(volume, float(previous["volume"].mean())),
        f"{prefix}_turn20": _ratio(turnover, float(previous["turnover_rate"].median())),
        f"{prefix}_float_cap": _ratio(close * volume, turnover * 10000),
    }


def compute_event_features(bars: pd.DataFrame, index: int, n_board: int) -> dict[str, float]:
    """只读取 index 当日开盘及此前的数据；index 是买入日在 bars 中的位置。"""
    symbol = bars["vt_symbol"].iat[index]
    if "pos" in bars.columns:
        start = index - int(bars["pos"].iat[index])
    else:
        symbols = bars["vt_symbol"].to_numpy()
        different = np.flatnonzero(symbols[:index + 1] != symbol)
        start = int(different[-1] + 1) if len(different) else 0
    stock = bars.iloc[start:index + 1].copy()
    stock["prev_close"] = stock["close_price"].shift(1)
    limit_price = (stock["prev_close"] * 1.10).round(2)
    stock["is_limit"] = (stock["close_price"] - limit_price).abs() <= 1e-6
    stock["touch_limit"] = stock["high_price"] >= limit_price - 1e-6
    local_i = len(stock) - 1
    foundation_i = local_i - 1 - n_board
    result: dict[str, float] = {"price": float(stock["prev_close"].iloc[-1])}
    result.update(_bar_features(stock, foundation_i, "f"))
    board_indices = list(range(local_i - n_board, local_i))
    for board in range(1, n_board + 1):
        result.update(_bar_features(stock, local_i - n_board + board - 1, f"b{board}"))
    result["f_turn"] = float(stock["turnover_rate"].iloc[foundation_i])
    result["f_amount"] = float(stock["close_price"].iloc[foundation_i]
                               * stock["volume"].iloc[foundation_i] / 1e6)
    result["last_amount"] = float(stock["close_price"].iloc[-2] * stock["volume"].iloc[-2] / 1e6)
    result["chain_turn_sum"] = float(stock["turnover_rate"].iloc[board_indices].sum())
    result["chain_turn_min"] = float(stock["turnover_rate"].iloc[board_indices].min())
    result["chain_turn_max"] = float(stock["turnover_rate"].iloc[board_indices].max())
    result["chain_lower_sum"] = sum(result[f"b{board}_lower"] for board in range(1, n_board + 1))
    result["chain_vol20_mean"] = float(np.mean([result[f"b{board}_vol20"] for board in range(1, n_board + 1)]))
    result["chain_turn20_mean"] = float(np.mean([result[f"b{board}_turn20"] for board in range(1, n_board + 1)]))
    result["chain_amount_sum"] = float((stock["close_price"].iloc[board_indices]
                                        * stock["volume"].iloc[board_indices] / 1e6).sum())
    result["b1_f_turn_ratio"] = _ratio(float(stock["turnover_rate"].iloc[board_indices[0]]), result["f_turn"])
    result["last_f_turn_ratio"] = _ratio(float(stock["turnover_rate"].iloc[-2]), result["f_turn"])
    result["last_turn_raw_vs_b1"] = _ratio(float(stock["turnover_rate"].iloc[-2]),
                                            float(stock["turnover_rate"].iloc[board_indices[0]]))
    result["last_vol20"] = result[f"b{n_board}_vol20"]
    result["last_turn20"] = result[f"b{n_board}_turn20"]
    result["float_cap"] = result[f"b{n_board}_float_cap"]
    result["last_vol_vs_b1"] = _ratio(float(stock["volume"].iloc[-2]), float(stock["volume"].iloc[local_i - n_board]))
    result["last_turn_vs_b1"] = _ratio(result[f"b{n_board}_turn20"], result["b1_turn20"])
    result["lower_max"] = max(result[f"b{board}_lower"] for board in range(1, n_board + 1))
    result["lower_trend"] = result[f"b{n_board}_lower"] - result["b1_lower"]
    result["open_chain_slope"] = ((float(stock["open_price"].iloc[-2]) / float(stock["prev_close"].iloc[-2]))
                                  - (float(stock["open_price"].iloc[local_i - n_board])
                                     / float(stock["prev_close"].iloc[local_i - n_board]))) * 100
    today_open = ((float(stock["open_price"].iloc[-1]) / float(stock["prev_close"].iloc[-1]) - 1)
                  - (float(stock["open_price"].iloc[-2]) / float(stock["prev_close"].iloc[-2]) - 1)) * 100
    result["today_open_accel"] = today_open
    pre20 = stock.iloc[max(0, foundation_i - 19):foundation_i + 1]
    pre60 = stock.iloc[max(0, foundation_i - 59):foundation_i + 1]
    result.update(_window_features(pre20, "pre20"))
    result.update(_window_features(pre60, "pre60"))
    last_volume = float(stock["volume"].iloc[-2])
    last_turnover = float(stock["turnover_rate"].iloc[-2])
    float_shares = last_volume * 10000 / last_turnover if last_turnover > 0 else np.nan
    overhead_volume = float(pre60.loc[pre60["close_price"] > stock["close_price"].iloc[foundation_i], "volume"].sum())
    result["pre60_overhead_turn"] = _ratio(overhead_volume * 10000, float_shares)
    result["pre60_total_turn"] = _ratio(float(pre60["volume"].sum()) * 10000, float_shares)
    result["chain_overhead_ratio"] = _ratio(result["chain_turn_sum"], result["pre60_overhead_turn"])
    high = pre60["high_price"].to_numpy(dtype=float)
    low = pre60["low_price"].to_numpy(dtype=float)
    result["days_since_high60"] = float(np.argmax(high[::-1]))
    result["days_since_low60"] = float(np.argmax(low[::-1]))
    failed = pre60["touch_limit"].to_numpy(dtype=bool) & ~pre60["is_limit"].to_numpy(dtype=bool)
    result["days_since_failed_limit"] = float(len(pre60) - 1 - np.flatnonzero(failed)[-1]) if failed.any() else np.nan
    for offset in (1, 2):
        j = foundation_i - offset
        result[f"pre_f{offset}_chg"] = ((float(stock["close_price"].iloc[j])
                                         / float(stock["prev_close"].iloc[j]) - 1) * 100) if j >= 0 else np.nan
    recent = stock.iloc[max(0, foundation_i - 2):foundation_i + 1]
    result["pre3_up_days"] = float((recent["close_price"] > recent["prev_close"]).sum())
    return result


def persist_dataset(events: pd.DataFrame, output: Path, month_states: dict[str, str]) -> None:
    events.to_pickle(output)
    events.to_csv(output.with_suffix(".csv"), index=False)
    output.with_suffix(".json").write_text(pd.Series(month_states).to_json(force_ascii=False), encoding="utf-8")


def build_dataset(output: Path) -> pd.DataFrame:
    """从生产同源回放构建一次研究样本，并保存到容器临时目录。"""
    from alphaagent.server.services.high_relay import contracts
    from alphaagent.server.services.high_relay.backtest import _dyn_trades, build_events

    events, bars = build_events()
    events = events[~events["未完"]].copy()
    features = [compute_event_features(bars, int(row["_bar_i"]), int(row["N"]))
                for _, row in events.iterrows()]
    feature_frame = pd.DataFrame(features, index=events.index)
    events = pd.concat([events, feature_frame], axis=1)
    month_states = contracts.dyn_month_states(_dyn_trades(events))
    events["出手点"] = assign_take_points(events, month_states)
    persist_dataset(events, output, month_states)
    return events


def assign_take_points(events: pd.DataFrame, month_states: dict[str, str]) -> pd.Series:
    from alphaagent.server.services.high_relay import contracts

    def take(row: pd.Series) -> str:
        state = contracts.dyn_state_at(month_states, str(row["月"]))
        return contracts.dyn_take_point(state, row["方案点"], row["弱口诀"], row.get("方案子项"))

    return events.apply(take, axis=1)


def period_frame(events: pd.DataFrame, period: str) -> pd.DataFrame:
    dates = pd.to_datetime(events["买入日"])
    if period == "discovery":
        return events[dates.dt.year <= 2024].copy()
    if period == "validation":
        return events[dates.dt.year == 2025].copy()
    if period == "final":
        return events[dates.dt.year == 2026].copy()
    raise ValueError(f"未知研究时段: {period}")


def candidate_mask(events: pd.DataFrame, candidate: dict[str, object]) -> pd.Series:
    mask = pd.Series(True, index=events.index)
    action = str(candidate.get("action", ""))
    context = str(candidate.get("context", ""))
    if action == "expand":
        mask &= (events["出手点"].fillna("") == "") & (events["买入开盘%"] < 9.5)
    elif action == "quality":
        mask &= events["出手点"].fillna("") != ""
    matched_group = False
    for group in ("二接三阴", "二接三阳", "三接四阴", "三接四阳"):
        if group in context:
            mask &= events["四组"] == group
            matched_group = True
    matched_n = False
    for n_board in (2, 3):
        if f"N{n_board}" in context:
            mask &= events["N"] == n_board
            matched_n = True
    if action == "quality" and context != "全部" and not matched_group and not matched_n:
        mask &= events["出手点"] == context
    for feature, operator, threshold in candidate["conditions"]:  # type: ignore[index]
        values = pd.to_numeric(events[str(feature)], errors="coerce")
        if operator == "<=":
            mask &= values <= float(threshold)
        elif operator == ">":
            mask &= values > float(threshold)
        else:
            raise ValueError(f"不支持的候选条件: {operator}")
    return mask


def quality_evidence(frame: pd.DataFrame, candidate: dict[str, object]) -> dict[str, object]:
    mask = candidate_mask(frame, candidate)
    return {"baseline": summarize(frame), "removed": summarize(frame[mask]), "kept": summarize(frame[~mask])}


def trade_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    return [{"date": row["买入日"].strftime("%Y-%m-%d"), "name": str(row.get("名称", "")),
             "point": str(row.get("出手点", "")), "e3": float(row["E3%"])}
            for _, row in frame.iterrows()]


def evaluate_candidate(events: pd.DataFrame, candidate: dict[str, object],
                       include_final: bool) -> dict[str, dict[str, float | int | None]]:
    base = events[candidate_mask(events, {**candidate, "conditions": []})]
    selected = base[candidate_mask(base, candidate)]
    periods = ["discovery", "validation"] + (["final"] if include_final else [])
    result = {}
    for period in periods:
        stats = summarize(period_frame(selected, period))
        if candidate.get("action") == "quality":
            evidence = quality_evidence(period_frame(base, period), candidate)
            stats["baseline"] = evidence["baseline"]
            stats["kept"] = evidence["kept"]
        result[period] = stats
    return result


def summarize(events: pd.DataFrame) -> dict[str, float | int | None]:
    returns = pd.to_numeric(events.get("E3%", pd.Series(dtype=float)), errors="coerce").dropna()
    if returns.empty:
        return {"n": 0, "win": None, "mean": None, "median": None, "trim3": None}
    core = returns.sort_values().iloc[:-3] if len(returns) > 3 else returns
    return {
        "n": int(len(returns)),
        "win": round(float((returns > 0).mean() * 100), 2),
        "mean": round(float(returns.mean()), 3),
        "median": round(float(returns.median()), 3),
        "trim3": round(float(core.mean()), 3),
    }


def discover_candidates(events: pd.DataFrame, features: list[str]) -> list[dict[str, object]]:
    """只用发现段与验证段搜索浅层区间；2026 不进入模型、阈值或统计。"""
    from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

    discovery = period_frame(events, "discovery")
    validation = period_frame(events, "validation")
    miss_discovery = discovery[(discovery["出手点"].fillna("") == "") & (discovery["买入开盘%"] < 9.5)]
    miss_validation = validation[(validation["出手点"].fillna("") == "") & (validation["买入开盘%"] < 9.5)]
    active_discovery = discovery[discovery["出手点"].fillna("") != ""]
    active_validation = validation[validation["出手点"].fillna("") != ""]
    contexts: list[tuple[str, str, pd.DataFrame, pd.DataFrame, bool]] = []
    for universal in (False, True):
        train_base = miss_discovery if universal else miss_discovery[miss_discovery["买入日"].dt.year >= 2023]
        for group in sorted(events["四组"].dropna().unique()):
            contexts.append(("expand", f"{'通用' if universal else '强市'}·{group}",
                             train_base[train_base["四组"] == group],
                             miss_validation[miss_validation["四组"] == group], universal))
    for n_board in (2, 3):
        contexts.append(("expand", f"强市·N{n_board}",
                         miss_discovery[(miss_discovery["买入日"].dt.year >= 2023)
                                        & (miss_discovery["N"] == n_board)],
                         miss_validation[miss_validation["N"] == n_board], False))
    quality_contexts = [("全部", active_discovery, active_validation)]
    quality_contexts += [(f"N{n}", active_discovery[active_discovery["N"] == n],
                          active_validation[active_validation["N"] == n]) for n in (2, 3)]
    quality_contexts += [(group, active_discovery[active_discovery["四组"] == group],
                          active_validation[active_validation["四组"] == group])
                         for group in sorted(events["四组"].dropna().unique())]
    quality_contexts += [(point, active_discovery[active_discovery["出手点"] == point],
                          active_validation[active_validation["出手点"] == point])
                         for point in sorted(events["出手点"].dropna().unique()) if point]
    contexts.extend(("quality", name, train, val, False)
                    for name, train, val in quality_contexts if len(train) >= 15)

    candidates: list[dict[str, object]] = []
    for action, context, train, val, universal in contexts:
        usable = [f for f in features if f in train and train[f].notna().mean() >= 0.7
                  and train[f].nunique() > 3]
        if not usable or len(train) < 15 or len(val) < 2:
            continue
        medians = train[usable].median()
        x_train = train[usable].fillna(medians)
        x_val = val[usable].fillna(medians)
        for target in ("clip", "binary"):
            y_train = (np.clip(train["E3%"], -20, 25) if target == "clip"
                       else (train["E3%"] > 0).astype(int))
            depths = (1, 2) if action == "quality" else (2, 3)
            leaf_sizes = (5, 8, 10) if action == "quality" else (10, 20, 30)
            for depth in depths:
                for leaf_size in leaf_sizes:
                    model_class = DecisionTreeClassifier if target == "binary" else DecisionTreeRegressor
                    model = model_class(max_depth=depth, min_samples_leaf=leaf_size, random_state=42)
                    model.fit(x_train, y_train)
                    train_leaves, val_leaves = model.apply(x_train), model.apply(x_val)
                    tree = model.tree_

                    def visit(node: int, conditions: list[list[object]]):
                        if tree.feature[node] >= 0:
                            feature = usable[tree.feature[node]]
                            threshold = float(tree.threshold[node])
                            visit(tree.children_left[node], conditions + [[feature, "<=", threshold]])
                            visit(tree.children_right[node], conditions + [[feature, ">", threshold]])
                            return
                        candidate = {"action": action, "context": context, "conditions": conditions}
                        selected = train[candidate_mask(train, candidate)]
                        selected_val = val[candidate_mask(val, candidate)]
                        train_stats, val_stats = summarize(selected), summarize(selected_val)
                        if action == "quality":
                            passed = (train_stats["n"] >= 5 and val_stats["n"] >= 2
                                      and train_stats["mean"] < 0 and train_stats["win"] < 50
                                      and train_stats["trim3"] < 0 and val_stats["mean"] < 0)
                        else:
                            passed = (train_stats["n"] >= 12 and val_stats["n"] >= 3
                                      and train_stats["mean"] >= 5 and train_stats["win"] >= 60
                                      and train_stats["trim3"] > 0 and val_stats["mean"] > 0
                                      and val_stats["trim3"] > 0)
                            if universal and passed:
                                weak = summarize(selected[selected["买入日"].dt.year <= 2022])
                                strong = summarize(selected[selected["买入日"].dt.year >= 2023])
                                passed = (weak["n"] >= 5 and strong["n"] >= 5
                                          and weak["mean"] > 0 and strong["mean"] > 0)
                        quality = None
                        if action == "quality" and passed:
                            discovery_evidence = quality_evidence(train, candidate)
                            validation_evidence = quality_evidence(val, candidate)
                            passed = all(evidence["kept"]["n"] > 0
                                         and evidence["kept"]["mean"] >= evidence["baseline"]["mean"]
                                         and evidence["kept"]["win"] >= evidence["baseline"]["win"]
                                         for evidence in (discovery_evidence, validation_evidence))
                            if passed:
                                combined = pd.concat([train, val])
                                combined_mask = candidate_mask(combined, candidate)
                                quality = {
                                    "discovery": discovery_evidence, "validation": validation_evidence,
                                    "yearly": {str(year): quality_evidence(frame, candidate)
                                               for year, frame in combined.groupby(combined["买入日"].dt.year)},
                                    "removed_trades": trade_records(combined[combined_mask]),
                                    "kept_trades": trade_records(combined[~combined_mask]),
                                }
                        if not passed:
                            return
                        periods: dict[str, object] = {"discovery": train_stats, "validation": val_stats}
                        if universal:
                            periods["weak_era"] = summarize(selected[selected["买入日"].dt.year <= 2022])
                            periods["strong_era"] = summarize(selected[selected["买入日"].dt.year >= 2023])
                        if quality is not None:
                            candidate["quality"] = quality
                        candidates.append({**candidate, "periods": periods})
                    visit(0, [])
    unique: dict[str, dict[str, object]] = {}
    for candidate in candidates:
        key = pd.json_normalize(candidate).to_json()
        unique[key] = candidate
    return sorted(unique.values(), key=lambda c: (
        float(c["periods"]["discovery"]["mean"]) + float(c["periods"]["validation"]["mean"])), reverse=True)  # type: ignore[index]


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "verify"
    data_path = Path("/tmp/hpr_hidden_range_events.pkl")
    csv_path = data_path.with_suffix(".csv")
    raw_candidates_path = Path("/tmp/hpr_hidden_range_candidates_raw.json")
    frozen_candidates_path = Path("/tmp/hpr_hidden_range_candidates.json")
    if command == "dump":
        dataset = build_dataset(data_path)
        print(json.dumps({"events": len(dataset),
                          "active": summarize(dataset[dataset["出手点"] != ""])}, ensure_ascii=False))
    elif command == "discover":
        dataset = pd.read_csv(csv_path, parse_dates=["买入日"])
        dataset["出手点"] = dataset["出手点"].fillna("")
        original_features = ["买入开盘%", "地基涨跌%", "距60日新高%", "距MA10%", "前板高度",
                             "前波60日最高板", "前波120日最高板", "b1开盘%", "b2开盘%", "b3开盘%",
                             "b1换手%", "b2换手%", "b3换手%", "前20日涨幅%", "前10日涨幅%",
                             "地基距MA20%", "锚位%", "锚距", "换手梯度"]
        hidden_features = list(dataset.columns[dataset.columns.get_loc("price"):dataset.columns.get_loc("出手点")])
        found = discover_candidates(dataset, list(dict.fromkeys(original_features + hidden_features)))
        raw_candidates_path.write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"原始候选 {len(found)} 条，已写入 {raw_candidates_path}；逐票复核后才能冻结。")
    elif command == "verify":
        if not frozen_candidates_path.exists():
            frozen_candidates_path.write_text("[]", encoding="utf-8")
        frozen = json.loads(frozen_candidates_path.read_text(encoding="utf-8"))
        if not frozen:
            print("无冻结候选；未读取 2026 年新特征结果，不执行最终测试。")
        else:
            dataset = pd.read_csv(csv_path, parse_dates=["买入日"])
            dataset["出手点"] = dataset["出手点"].fillna("")
            report = []
            for candidate in frozen:
                base = dataset[candidate_mask(dataset, {**candidate, "conditions": []})]
                selected = base[candidate_mask(base, candidate)]
                item = {**candidate, "final": evaluate_candidate(dataset, candidate, True)["final"]}
                if candidate.get("action") == "quality":
                    kept = base[~candidate_mask(base, candidate)]
                    item["removed_trades"] = trade_records(selected)
                    item["kept_trades"] = trade_records(kept)
                    item["yearly"] = {str(year): quality_evidence(frame, candidate)
                                      for year, frame in base.groupby(base["买入日"].dt.year)}
                else:
                    item["added_trades"] = trade_records(selected)
                report.append(item)
            output = Path("/tmp/hpr_hidden_range_verification.json")
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        raise SystemExit(f"未知命令: {command}；可用 dump / discover / verify")
