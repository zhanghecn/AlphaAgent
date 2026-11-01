"""全连板全景研究：从生产同源日线发现规律，再映射回口诀交易。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from hpr_hidden_range_research import assign_take_points, compute_event_features, summarize


DATA_DIR = Path("/tmp")
NODES_PATH = DATA_DIR / "hpr_chain_landscape.csv"
EVENTS_PATH = DATA_DIR / "hpr_chain_events.csv"


def _ratio(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator and np.isfinite(denominator) else np.nan


def classify_next_outcome(frame: pd.DataFrame) -> pd.Series:
    has_next = frame["decision_date"].notna()
    return pd.Series(
        np.select(
            [~has_next, frame["next_is_lim"].eq(True), frame["next_touch"].eq(True)],
            ["pending", "continue", "touch_break"],
            default="no_touch",
        ),
        index=frame.index,
        dtype="object",
    )


def build_chain_nodes(bars: pd.DataFrame, start: str = "2020-01-01") -> pd.DataFrame:
    """从同票相邻日线构建 N>=2 锚点，不因可交易性或特征缺失预过滤。"""
    required = {"vt_symbol", "trade_date", "sid", "streak", "is_lim", "touch", "one_word",
                "open_price", "prev_close"}
    missing = required - set(bars.columns)
    if missing:
        raise ValueError(f"连板锚点缺少字段: {sorted(missing)}")
    if not bars.index.equals(pd.RangeIndex(len(bars))):
        raise ValueError("bars 必须是生产 derive_daily 后的连续行号")
    frame = bars.copy()
    grouped = frame.groupby("sid", sort=False)
    next_sid = grouped["sid"].shift(-1)
    same_stock = next_sid.eq(frame["sid"])
    for target, source in (("decision_date", "trade_date"), ("next_is_lim", "is_lim"),
                           ("next_touch", "touch"), ("next_one_word", "one_word"),
                           ("next_open", "open_price"), ("next_prev_close", "prev_close")):
        shifted = grouped[source].shift(-1)
        frame[target] = shifted.where(same_stock)
    frame["_decision_i"] = pd.Series(np.arange(len(frame)) + 1, index=frame.index).where(same_stock, -1).astype(int)
    chain_start = frame["is_lim"] & frame["streak"].eq(1)
    chain_number = chain_start.groupby(frame["sid"], sort=False).cumsum()
    first_dates = frame["trade_date"].where(chain_start).groupby(frame["sid"], sort=False).ffill()
    final_height = frame["streak"].groupby([frame["sid"], chain_number], sort=False).transform("max")
    anchors = frame[frame["is_lim"] & frame["streak"].ge(2)].copy()
    anchors["N"] = anchors["streak"].astype(int)
    anchors["chain_id"] = (anchors["vt_symbol"].astype(str) + "|"
                           + first_dates.loc[anchors.index].dt.strftime("%Y-%m-%d"))
    anchors["first_board_date"] = first_dates.loc[anchors.index]
    anchors["final_height"] = final_height.loc[anchors.index].astype(int)
    anchors["remaining_boards"] = anchors["final_height"] - anchors["N"]
    anchors["outcome"] = classify_next_outcome(anchors)
    anchors["next_open_pct"] = ((anchors["next_open"] / anchors["next_prev_close"] - 1) * 100).round(2)
    anchors["calendar_gap"] = (anchors["decision_date"] - anchors["trade_date"]).dt.days
    start_date = pd.Timestamp(start)
    anchors = anchors[(anchors["decision_date"].ge(start_date))
                      | (anchors["decision_date"].isna() & anchors["trade_date"].ge(start_date))].copy()
    anchors.rename(columns={"vt_symbol": "代码", "trade_date": "anchor_date"}, inplace=True)
    anchors["_anchor_i"] = anchors.index.astype(int)
    records = []
    sid = bars["sid"].to_numpy()
    dates = bars["trade_date"].to_numpy()
    for _, row in anchors.iterrows():
        anchor_i = int(row["_anchor_i"])
        n_board = int(row["N"])
        foundation_i = anchor_i - n_board
        foundation_date = dates[foundation_i] if foundation_i >= 0 and sid[foundation_i] == row["sid"] else pd.NaT
        records.append({
            "anchor_id": f"{row['代码']}|{row['anchor_date']:%Y-%m-%d}",
            "代码": row["代码"],
            "anchor_date": row["anchor_date"],
            "decision_date": row["decision_date"],
            "N": n_board,
            "chain_id": row["chain_id"],
            "first_board_date": row["first_board_date"],
            "foundation_date": foundation_date,
            "final_height": int(row["final_height"]),
            "remaining_boards": int(row["remaining_boards"]),
            "outcome": row["outcome"],
            "next_open_pct": row["next_open_pct"],
            "next_is_lim": bool(row["next_is_lim"]) if pd.notna(row["next_is_lim"]) else False,
            "next_touch": bool(row["next_touch"]) if pd.notna(row["next_touch"]) else False,
            "next_one_word": bool(row["next_one_word"]) if pd.notna(row["next_one_word"]) else False,
            "calendar_gap": row["calendar_gap"],
            "_anchor_i": anchor_i,
            "_decision_i": int(row["_decision_i"]),
        })
    result = pd.DataFrame(records)
    result["month"] = result["decision_date"].fillna(result["anchor_date"]).dt.strftime("%Y-%m")
    result["year"] = result["decision_date"].fillna(result["anchor_date"]).dt.year.astype(int)
    return result.reset_index(drop=True)


def link_trade_events(nodes: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """保留原事件，分别关联买入前来源锚点与封住后新达到锚点。"""
    source = nodes[nodes["_decision_i"].ge(0)].drop_duplicates("_decision_i").set_index("_decision_i")
    reached = nodes.drop_duplicates("_anchor_i").set_index("_anchor_i")
    result = events.copy()
    columns = ["source_anchor_id", "reached_anchor_id", "chain_id", "link_status"]
    for column in columns:
        result[column] = pd.Series(pd.NA, index=result.index, dtype="object")
    for index, event in result.iterrows():
        i = int(event["_bar_i"])
        if i not in source.index:
            result.at[index, "link_status"] = "missing_source"
            continue
        node = source.loc[i]
        matches = (str(node["代码"]) == str(event["代码"]) and int(node["N"]) == int(event["N"])
                   and pd.Timestamp(node["decision_date"]) == pd.Timestamp(event["买入日"]))
        if not matches:
            result.at[index, "link_status"] = "key_mismatch"
            continue
        result.at[index, "source_anchor_id"] = node["anchor_id"]
        result.at[index, "chain_id"] = node["chain_id"]
        result.at[index, "link_status"] = "ok"
        if bool(event["封住"]) and i in reached.index:
            reached_node = reached.loc[i]
            if int(reached_node["N"]) == int(event["N"]) + 1:
                result.at[index, "reached_anchor_id"] = reached_node["anchor_id"]
    return result


def build_node_features(bars: pd.DataFrame, decision_i: int, n_board: int) -> dict[str, float]:
    """只计算决策日开盘及此前可见的特征。"""
    result = compute_event_features(bars, decision_i, n_board)
    row = bars.iloc[decision_i]
    previous_close = float(row["prev_close"]) if "prev_close" in bars.columns else float(bars["close_price"].iloc[decision_i - 1])
    result["today_open"] = (float(row["open_price"]) / previous_close - 1) * 100
    return result


def sequence_features(record: dict[str, object], n_board: int) -> dict[str, float | int]:
    types = [str(record.get(f"b{board}_type") or "") for board in range(1, n_board + 1)]
    opens = np.array([pd.to_numeric(record.get(f"b{board}_open"), errors="coerce")
                      for board in range(1, n_board + 1)], dtype=float)
    turns = np.array([pd.to_numeric(record.get(f"b{board}_turn"), errors="coerce")
                      for board in range(1, n_board + 1)], dtype=float)

    def position(kind: str) -> int:
        return types.index(kind) + 1 if kind in types else 0

    def extreme_position(values: np.ndarray, mode: str) -> int:
        if not np.isfinite(values).any():
            return 0
        index = np.nanargmax(values) if mode == "max" else np.nanargmin(values)
        return int(index + 1)

    return {
        "one_word_count": types.count("一字"),
        "entity_count": types.count("实体"),
        "lshadow_count": types.count("下影"),
        "first_one_word": int(types[0] == "一字"),
        "last_one_word": int(types[-1] == "一字"),
        "last_entity": int(types[-1] == "实体"),
        "last_lshadow": int(types[-1] == "下影"),
        "first_entity_pos": position("实体"),
        "first_lshadow_pos": position("下影"),
        "first_open": opens[0],
        "last_open": opens[-1],
        "open_slope": opens[-1] - opens[0],
        "open_max": np.nanmax(opens),
        "open_min": np.nanmin(opens),
        "open_peak_pos": extreme_position(opens, "max"),
        "open_up_steps": int(np.nansum(np.diff(opens) > 0)),
        "open_down_steps": int(np.nansum(np.diff(opens) < 0)),
        "first_turn": turns[0],
        "last_turn": turns[-1],
        "prev_turn": turns[-2] if len(turns) > 1 else np.nan,
        "turn_slope": turns[-1] - turns[0],
        "turn_last_change": turns[-1] - turns[-2] if len(turns) > 1 else np.nan,
        "last_turn_vs_first": _ratio(turns[-1], turns[0]),
        "last_turn_vs_prev": _ratio(turns[-1], turns[-2]) if len(turns) > 1 else np.nan,
        "turn_max": np.nanmax(turns),
        "turn_min": np.nanmin(turns),
        "turn_sum": np.nansum(turns),
        "turn_peak_pos": extreme_position(turns, "max"),
        "turn_low_pos": extreme_position(turns, "min"),
    }


def attach_node_features(nodes: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    from alphaagent.server.services.high_relay import pool

    ctx = pool.make_ctx(bars)
    records: list[dict[str, object]] = []
    for _, node in nodes.iterrows():
        record: dict[str, object] = {"features_missing": False}
        try:
            static = pool.static_fields(ctx, int(node["_anchor_i"]), int(node["N"]))
            if static is None:
                raise ValueError("地基缺失")
            record.update(static)
            record.update(sequence_features(static, int(node["N"])))
            if int(node["_decision_i"]) < 0:
                raise ValueError("下一交易日待定")
            record.update(build_node_features(bars, int(node["_decision_i"]), int(node["N"])))
        except (IndexError, TypeError, ValueError):
            record = {"features_missing": True}
        records.append(record)
    features = pd.DataFrame(records, index=nodes.index)
    return pd.concat([nodes.copy(), features], axis=1)


def interval_mask(frame: pd.DataFrame, feature: str, lo: float, hi: float) -> pd.Series:
    values = pd.to_numeric(frame[feature], errors="coerce")
    return values.ge(lo) & values.lt(hi)


def candidate_condition_mask(nodes: pd.DataFrame, candidate: dict[str, object]) -> pd.Series:
    if "conditions" not in candidate:
        return interval_mask(nodes, str(candidate["feature"]), float(candidate["lo"]), float(candidate["hi"]))
    mask = pd.Series(True, index=nodes.index)
    for feature, operator, threshold in candidate["conditions"]:  # type: ignore[index]
        values = pd.to_numeric(nodes[str(feature)], errors="coerce")
        mask &= values.le(float(threshold)) if operator == "<=" else values.gt(float(threshold))
    return mask


def trade_stats(frame: pd.DataFrame) -> dict[str, object]:
    stats = summarize(frame)
    chain_stats = chain_aware_summary(frame, "E3%") if len(frame) else {
        "chains": 0, "stocks": 0, "months": 0, "trim3_chain": None}
    return {**stats, **{key: chain_stats[key] for key in ("chains", "stocks", "months", "trim3_chain")}}


def trade_evidence(nodes: pd.DataFrame, candidate: dict[str, object], context_mask: pd.Series) -> dict[str, object]:
    condition = candidate_condition_mask(nodes, candidate)
    context = context_mask.reindex(nodes.index, fill_value=False).astype(bool)
    events = nodes[nodes["trade_event"].eq(True)].copy()
    events["出手点"] = events["出手点"].fillna("")
    selected = events[context.reindex(events.index, fill_value=False)
                      & condition.reindex(events.index, fill_value=False)]
    active_base = events[context.reindex(events.index, fill_value=False) & events["出手点"].ne("")]
    periods = research_periods(events, include_final=False)
    result: dict[str, object] = {}
    for period, frame in periods.items():
        selected_period = selected[selected.index.isin(frame.index)]
        base_period = active_base[active_base.index.isin(frame.index)]
        removed = selected_period[selected_period["出手点"].ne("")]
        kept = base_period[~condition.reindex(base_period.index, fill_value=False)]
        result[period] = {
            "new": trade_stats(selected_period[selected_period["出手点"].eq("")]),
            "baseline_active": trade_stats(base_period),
            "removed_active": trade_stats(removed),
            "kept_active": trade_stats(kept),
        }
    return result


def search_evolution_factors(nodes: pd.DataFrame, features: list[str],
                             contexts: dict[str, pd.Series] | None = None,
                             bins: int = 6, min_train: int = 60,
                             min_validation: int = 15, target: str = "continue") -> list[dict[str, object]]:
    """只用发现段确定区间，2025 按原区间验证，2026 不进入函数计算。"""
    if target not in {"continue", "multi"}:
        raise ValueError(f"未知演变目标: {target}")
    metric = "continue" if target == "continue" else "multi_continue"
    chain_metric = "chain_continue" if target == "continue" else "chain_multi"
    periods = research_periods(nodes, include_final=False)
    discovery_all, validation_all = periods["discovery"], periods["validation"]
    contexts = contexts or {"全部": pd.Series(True, index=nodes.index)}
    results: list[dict[str, object]] = []
    for context_name, context_mask in contexts.items():
        aligned = context_mask.reindex(nodes.index, fill_value=False).astype(bool)
        train = discovery_all[aligned.reindex(discovery_all.index, fill_value=False)]
        validation = validation_all[aligned.reindex(validation_all.index, fill_value=False)]
        train, validation = train[train["outcome"] != "pending"], validation[validation["outcome"] != "pending"]
        if len(train) < min_train or len(validation) < min_validation:
            continue
        baseline_train, baseline_validation = outcome_summary(train), outcome_summary(validation)
        for feature in features:
            if feature not in train:
                continue
            train_values = pd.to_numeric(train[feature], errors="coerce")
            if train_values.notna().mean() < 0.6 or train_values.nunique() < 4:
                continue
            thresholds = quantile_thresholds(train, feature, bins)
            if not thresholds:
                continue
            edges = [-np.inf, *thresholds, np.inf]
            for lower in range(len(edges) - 1):
                for upper in range(lower, len(edges) - 1):
                    lo, hi = edges[lower], edges[upper + 1]
                    selected_train = train[interval_mask(train, feature, lo, hi)]
                    selected_validation = validation[interval_mask(validation, feature, lo, hi)]
                    if (len(selected_train) < min_train or len(selected_validation) < min_validation
                            or selected_train["chain_id"].nunique() < max(2, min_train // 2)
                            or selected_validation["chain_id"].nunique() < max(2, min_validation // 2)):
                        continue
                    train_stats, validation_stats = outcome_summary(selected_train), outcome_summary(selected_validation)
                    lift_train = train_stats[metric] - baseline_train[metric]
                    lift_validation = validation_stats[metric] - baseline_validation[metric]
                    chain_lift_train = train_stats[chain_metric] - baseline_train[chain_metric]
                    chain_lift_validation = validation_stats[chain_metric] - baseline_validation[chain_metric]
                    year_lifts = []
                    for year, yearly in selected_train.groupby(selected_train["decision_date"].dt.year):
                        base_year = train[train["decision_date"].dt.year.eq(year)]
                        if len(yearly) >= max(5, min_train // 6) and len(base_year) >= max(5, min_train // 6):
                            yearly_target = (yearly["outcome"].eq("continue") if target == "continue"
                                             else yearly["remaining_boards"].ge(2))
                            base_target = (base_year["outcome"].eq("continue") if target == "continue"
                                           else base_year["remaining_boards"].ge(2))
                            year_lifts.append(yearly_target.mean() - base_target.mean())
                    results.append({
                        "context": context_name, "feature": feature, "lo": lo, "hi": hi, "target": target,
                        "discovery": train_stats, "validation": validation_stats,
                        "baseline_discovery": baseline_train, "baseline_validation": baseline_validation,
                        "lift_discovery": round(lift_train, 3),
                        "lift_validation": round(lift_validation, 3),
                        "chain_lift_discovery": round(chain_lift_train, 3),
                        "chain_lift_validation": round(chain_lift_validation, 3),
                        "min_lift": round(min(lift_train, lift_validation), 3),
                        "min_chain_lift": round(min(chain_lift_train, chain_lift_validation), 3),
                        "positive_years": int(sum(value > 0 for value in year_lifts)),
                        "tested_years": len(year_lifts),
                    })
    results.sort(key=lambda item: (item["min_chain_lift"] + item["min_lift"]) / 2, reverse=True)
    return results


def research_features(nodes: pd.DataFrame) -> list[str]:
    explicit = {
        "next_open_pct", "foundation_chg", "dist_h60", "dist_ma10", "prev_wave60", "prev_wave120",
        "prior_height", "prior_gap", "pre20_pct", "pre10_pct", "pre3_pct", "anchor_pos", "anchor_dist",
        "turn_grad", "one_word_count", "entity_count", "lshadow_count", "first_one_word", "last_one_word",
        "last_entity", "last_lshadow", "first_entity_pos", "first_lshadow_pos", "first_open", "last_open",
        "open_slope", "open_max", "open_min", "open_peak_pos", "open_up_steps", "open_down_steps",
        "first_turn", "last_turn", "prev_turn", "turn_slope", "turn_last_change", "last_turn_vs_first",
        "last_turn_vs_prev", "turn_max", "turn_min", "turn_sum", "turn_peak_pos", "turn_low_pos",
        "float_cap", "price", "lower_max", "lower_trend", "open_chain_slope", "today_open_accel",
        "pre3_up_days", "days_since_high60", "days_since_low60", "days_since_failed_limit",
    }
    safe_prefixes = ("f_", "b1_", "b2_", "b3_", "pre20_", "pre60_", "pre_f", "chain_",
                     "last_", "today_open_")
    excluded = {"chain_id"}
    features = [column for column in nodes.columns
                if column in explicit or (column.startswith(safe_prefixes) and column not in excluded)]
    return list(dict.fromkeys(features))


def evolution_contexts(nodes: pd.DataFrame, include_rules: bool = False) -> dict[str, pd.Series]:
    foundation = nodes["foundation_yang"].map(
        {True: True, False: False, "True": True, "False": False, "1": True, "0": False})
    normal_open = pd.to_numeric(nodes["next_open_pct"], errors="coerce").lt(9.5)
    contexts = {
        "全部正常开盘": normal_open,
        "N2": normal_open & nodes["N"].eq(2),
        "N3": normal_open & nodes["N"].eq(3),
        "N4": normal_open & nodes["N"].eq(4),
        "N5+": normal_open & nodes["N"].ge(5),
        "N3+": normal_open & nodes["N"].ge(3),
        "二接三阳": normal_open & nodes["N"].eq(2) & foundation.eq(True),
        "二接三阴": normal_open & nodes["N"].eq(2) & foundation.eq(False),
        "三接四阳": normal_open & nodes["N"].eq(3) & foundation.eq(True),
        "三接四阴": normal_open & nodes["N"].eq(3) & foundation.eq(False),
        "末板一字": normal_open & nodes["last_one_word"].eq(1),
        "末板实体": normal_open & nodes["last_entity"].eq(1),
        "末板下影": normal_open & nodes["last_lshadow"].eq(1),
        "链有一字": normal_open & nodes["one_word_count"].gt(0),
        "一字后实体": normal_open & nodes["one_word_count"].gt(0) & nodes["last_entity"].eq(1),
    }
    if include_rules:
        contexts.update({f"口诀本体·{label}": mask for label, mask in rule_core_masks(nodes).items()})
    return contexts


def flatten_search_result(item: dict[str, object]) -> dict[str, object]:
    row = {key: item.get(key) for key in ("context", "feature", "lo", "hi", "target", "lift_discovery",
                                          "lift_validation", "chain_lift_discovery", "chain_lift_validation",
                                          "min_lift", "min_chain_lift", "positive_years", "tested_years")}
    row["conditions"] = json.dumps(item.get("conditions", ""), ensure_ascii=False)
    for period in ("discovery", "validation"):
        stats = item[period]
        for key in ("n", "chains", "stocks", "months", "continue", "chain_continue",
                    "multi_continue", "chain_multi", "touch_break", "no_touch"):
            row[f"{period}_{key}"] = stats[key]
    return row


def discover_and_persist(nodes: pd.DataFrame, target: str) -> tuple[list[dict[str, object]], pd.DataFrame]:
    found = search_evolution_factors(nodes, research_features(nodes), evolution_contexts(nodes), target=target)
    flat = pd.DataFrame([flatten_search_result(item) for item in found])
    suffix = "" if target == "continue" else "_multi"
    flat.to_csv(DATA_DIR / f"hpr_chain_factor_search{suffix}.csv", index=False)
    (DATA_DIR / f"hpr_chain_factor_search{suffix}.json").write_text(
        json.dumps(found, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return found, flat


def search_evolution_trees(nodes: pd.DataFrame, features: list[str], contexts: dict[str, pd.Series],
                           target: str = "multi", depths: tuple[int, ...] = (2, 3),
                           leaf_sizes: tuple[int, ...] = (30, 60), min_train: int = 60,
                           min_validation: int = 15) -> list[dict[str, object]]:
    """浅树只提出候选；叶子最终都用原始缺失值掩码重新统计。"""
    from sklearn.tree import DecisionTreeClassifier

    if target not in {"continue", "multi"}:
        raise ValueError(f"未知演变目标: {target}")
    metric = "continue" if target == "continue" else "multi_continue"
    chain_metric = "chain_continue" if target == "continue" else "chain_multi"
    periods = research_periods(nodes, include_final=False)
    discovery_all, validation_all = periods["discovery"], periods["validation"]
    results: list[dict[str, object]] = []
    for context_name, context_mask in contexts.items():
        aligned = context_mask.reindex(nodes.index, fill_value=False).astype(bool)
        train = discovery_all[aligned.reindex(discovery_all.index, fill_value=False)]
        validation = validation_all[aligned.reindex(validation_all.index, fill_value=False)]
        train, validation = train[train["outcome"] != "pending"], validation[validation["outcome"] != "pending"]
        if len(train) < min_train or len(validation) < min_validation:
            continue
        baseline_train, baseline_validation = outcome_summary(train), outcome_summary(validation)
        usable = []
        for feature in features:
            if feature not in train:
                continue
            values = pd.to_numeric(train[feature], errors="coerce")
            if values.notna().mean() >= 0.7 and values.nunique() > 3:
                usable.append(feature)
        if not usable:
            continue
        numeric_train = train[usable].apply(pd.to_numeric, errors="coerce")
        medians = numeric_train.median()
        x_train = numeric_train.fillna(medians)
        y_train = (train["outcome"].eq("continue") if target == "continue"
                   else train["remaining_boards"].ge(2)).astype(int)
        weights = 1 / train.groupby("chain_id")["chain_id"].transform("size")
        for depth in depths:
            for leaf_size in leaf_sizes:
                model = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=leaf_size, random_state=42)
                model.fit(x_train, y_train, sample_weight=weights)
                tree = model.tree_

                def visit(node: int, conditions: list[list[object]]) -> None:
                    if tree.feature[node] >= 0:
                        feature = usable[tree.feature[node]]
                        threshold = float(tree.threshold[node])
                        visit(tree.children_left[node], [*conditions, [feature, "<=", threshold]])
                        visit(tree.children_right[node], [*conditions, [feature, ">", threshold]])
                        return
                    candidate = {"context": context_name, "conditions": conditions, "target": target}
                    selected_train = train[candidate_condition_mask(train, candidate)]
                    selected_validation = validation[candidate_condition_mask(validation, candidate)]
                    if (len(selected_train) < min_train or len(selected_validation) < min_validation
                            or selected_train["chain_id"].nunique() < max(2, min_train // 2)
                            or selected_validation["chain_id"].nunique() < max(2, min_validation // 2)):
                        return
                    train_stats, validation_stats = outcome_summary(selected_train), outcome_summary(selected_validation)
                    lift_train = train_stats[metric] - baseline_train[metric]
                    lift_validation = validation_stats[metric] - baseline_validation[metric]
                    chain_lift_train = train_stats[chain_metric] - baseline_train[chain_metric]
                    chain_lift_validation = validation_stats[chain_metric] - baseline_validation[chain_metric]
                    year_lifts = []
                    for year, yearly in selected_train.groupby(selected_train["decision_date"].dt.year):
                        base_year = train[train["decision_date"].dt.year.eq(year)]
                        if len(yearly) >= max(5, min_train // 6) and len(base_year) >= max(5, min_train // 6):
                            yearly_target = (yearly["outcome"].eq("continue") if target == "continue"
                                             else yearly["remaining_boards"].ge(2))
                            base_target = (base_year["outcome"].eq("continue") if target == "continue"
                                           else base_year["remaining_boards"].ge(2))
                            year_lifts.append(yearly_target.mean() - base_target.mean())
                    results.append({
                        **candidate, "discovery": train_stats, "validation": validation_stats,
                        "baseline_discovery": baseline_train, "baseline_validation": baseline_validation,
                        "lift_discovery": round(lift_train, 3), "lift_validation": round(lift_validation, 3),
                        "chain_lift_discovery": round(chain_lift_train, 3),
                        "chain_lift_validation": round(chain_lift_validation, 3),
                        "min_lift": round(min(lift_train, lift_validation), 3),
                        "min_chain_lift": round(min(chain_lift_train, chain_lift_validation), 3),
                        "positive_years": int(sum(value > 0 for value in year_lifts)),
                        "tested_years": len(year_lifts),
                    })
                visit(0, [])
    unique: dict[str, dict[str, object]] = {}
    for item in results:
        key = str(item["context"]) + repr(sorted(item["conditions"])) + str(item["target"])
        score = (item["min_lift"] + item["min_chain_lift"]) / 2
        if key not in unique or score > (unique[key]["min_lift"] + unique[key]["min_chain_lift"]) / 2:
            unique[key] = item
    return sorted(unique.values(), key=lambda item: (item["min_chain_lift"] + item["min_lift"]) / 2,
                  reverse=True)


def production_view(nodes: pd.DataFrame) -> pd.DataFrame:
    """将全景字段映射到现有生产判定审计器，不另写口诀规则。"""
    result = pd.DataFrame(index=nodes.index)
    result["买入日"] = pd.to_datetime(nodes["decision_date"])
    result["N"] = nodes["N"]
    foundation = nodes["foundation_yang"].map(
        {True: True, False: False, "True": True, "False": False, "1": True, "0": False})
    prefix = nodes["N"].map({2: "二接三", 3: "三接四"}).fillna("其他")
    result["四组"] = prefix + foundation.map({True: "阳", False: "阴"}).fillna("未知")
    mapping = {
        "买入开盘%": "next_open_pct", "地基涨跌%": "foundation_chg", "距60日新高%": "dist_h60",
        "距MA10%": "dist_ma10", "前波60日最高板": "prev_wave60", "前10日涨幅%": "pre10_pct",
        "地基姿态": "foundation_pose", "锚位%": "anchor_pos", "锚距": "anchor_dist",
        "chain_lower_sum": "chain_lower_sum", "pre20_max_drawdown": "pre20_max_drawdown",
    }
    for board in range(1, 4):
        mapping[f"b{board}开盘%"] = f"b{board}_open"
        mapping[f"b{board}换手%"] = f"b{board}_turn"
    for target, source in mapping.items():
        result[target] = nodes[source] if source in nodes else np.nan
    result["E3%"] = nodes["E3%"] if "E3%" in nodes else np.nan
    return result


def rule_core_masks(nodes: pd.DataFrame) -> dict[str, pd.Series]:
    import hpr_rule_root_audit as audit

    view = production_view(nodes)
    masks = {}
    for branch in audit.branch_catalog():
        label = str(branch["no"]) + (f'·{branch["sub"]}' if branch["sub"] else "")
        variants = dict(audit.variant_definitions(branch))
        changes = variants.get("形态本体", variants["完整规则"])
        masks[label] = audit.match_branch(view, branch, changes)
    return masks


def outcome_summary(frame: pd.DataFrame) -> dict[str, object]:
    complete = frame[frame["outcome"].isin(["continue", "touch_break", "no_touch"])]
    if complete.empty:
        return {"n": 0, "chains": 0, "stocks": 0, "months": 0, "continue": None,
                "chain_continue": None, "multi_continue": None, "chain_multi": None,
                "touch_break": None, "no_touch": None, "avg_remaining": None}
    counts = complete["outcome"].value_counts()
    by_chain = complete["outcome"].eq("continue").groupby(complete["chain_id"]).mean()
    multi = complete["remaining_boards"].ge(2)
    multi_by_chain = multi.groupby(complete["chain_id"]).mean()
    return {
        "n": int(len(complete)),
        "chains": int(complete["chain_id"].nunique()),
        "stocks": int(complete["代码"].nunique()),
        "months": int(pd.to_datetime(complete["decision_date"]).dt.to_period("M").nunique()),
        "continue": round(float(counts.get("continue", 0) / len(complete) * 100), 2),
        "chain_continue": round(float(by_chain.mean() * 100), 2),
        "multi_continue": round(float(multi.mean() * 100), 2),
        "chain_multi": round(float(multi_by_chain.mean() * 100), 2),
        "touch_break": round(float(counts.get("touch_break", 0) / len(complete) * 100), 2),
        "no_touch": round(float(counts.get("no_touch", 0) / len(complete) * 100), 2),
        "avg_remaining": round(float(complete["remaining_boards"].mean()), 3),
    }


def landscape_report(nodes: pd.DataFrame) -> dict[str, pd.DataFrame]:
    complete = nodes[nodes["outcome"] != "pending"].copy()
    complete["foundation_group"] = complete["foundation_yang"].map({True: "阳", False: "阴"}).fillna("未知")

    def grouped(keys: list[str]) -> pd.DataFrame:
        rows = []
        for values, frame in complete.groupby(keys, dropna=False):
            if not isinstance(values, tuple):
                values = (values,)
            rows.append({**dict(zip(keys, values, strict=True)), **outcome_summary(frame)})
        return pd.DataFrame(rows)

    return {
        "yearly": grouped(["year"]),
        "monthly": grouped(["month"]),
        "by_board": grouped(["N"]),
        "by_board_foundation": grouped(["N", "foundation_group"]),
        "monthly_board": grouped(["month", "N"]),
    }


def quantile_thresholds(frame: pd.DataFrame, feature: str, bins: int = 6) -> list[float]:
    values = pd.to_numeric(frame[feature], errors="coerce").dropna().unique()
    if len(values) < 2:
        return []
    quantiles = np.linspace(0, 1, bins + 1)[1:-1]
    return sorted(set(float(value) for value in np.quantile(values, quantiles)))


def factor_spectrum(frame: pd.DataFrame, feature: str, thresholds: list[float]) -> pd.DataFrame:
    values = pd.to_numeric(frame[feature], errors="coerce")
    edges = [-np.inf, *thresholds, np.inf]
    buckets = pd.cut(values, bins=edges, include_lowest=True, duplicates="drop")
    rows = []
    for index, bucket in enumerate(buckets.cat.categories):
        selected = frame[buckets == bucket]
        rows.append({
            "feature": feature,
            "bin": index,
            "lo": float(edges[index]),
            "hi": float(edges[index + 1]),
            **outcome_summary(selected),
        })
    return pd.DataFrame(rows)


def research_periods(nodes: pd.DataFrame, include_final: bool) -> dict[str, pd.DataFrame]:
    dates = pd.to_datetime(nodes["decision_date"])
    periods = {
        "discovery": nodes[dates.dt.year.le(2024)],
        "validation": nodes[dates.dt.year.eq(2025)],
    }
    if include_final:
        periods["final"] = nodes[dates.dt.year.eq(2026)]
    return periods


def chain_aware_summary(frame: pd.DataFrame, value: str) -> dict[str, object]:
    selected = frame[pd.to_numeric(frame[value], errors="coerce").notna()].copy()
    returns = pd.to_numeric(selected[value], errors="coerce")
    if selected.empty:
        return {"n": 0, "chains": 0, "stocks": 0, "months": 0,
                "mean": None, "win": None, "trim3_chain": None}
    chain_returns = returns.groupby(selected["chain_id"]).mean().sort_values()
    core = chain_returns.iloc[:-3] if len(chain_returns) > 3 else chain_returns
    return {
        "n": int(len(selected)),
        "chains": int(selected["chain_id"].nunique()),
        "stocks": int(selected["代码"].nunique()),
        "months": int(pd.to_datetime(selected["decision_date"]).dt.to_period("M").nunique()),
        "mean": round(float(returns.mean()), 3),
        "win": round(float((returns > 0).mean() * 100), 2),
        "trim3_chain": round(float(core.mean()), 3),
    }


def attach_trade_to_nodes(nodes: pd.DataFrame, linked: pd.DataFrame) -> pd.DataFrame:
    trade_columns = ["_bar_i", "买入日", "E3%", "方案点", "方案子项", "弱口诀", "出手点",
                     "封住", "买价", "持有到断板%", "E3退出日", "持有天数"]
    trade = linked[trade_columns].copy()
    trade["trade_event"] = True
    enriched = nodes.merge(trade, how="left", left_on="_decision_i", right_on="_bar_i",
                           validate="many_to_one")
    enriched["trade_event"] = enriched["trade_event"].eq(True)
    matched = enriched[enriched["trade_event"]]
    if matched["_decision_i"].duplicated().any():
        raise ValueError("同一交易被重复关联到多个连板锚点")
    return enriched


def _write_split(frame: pd.DataFrame, path: Path, date_column: str) -> None:
    dates = pd.to_datetime(frame[date_column])
    frame[dates.dt.year.le(2025)].to_csv(path, index=False)
    frame[dates.dt.year.eq(2026)].to_csv(path.with_name(path.stem + "_2026.csv"), index=False)


def build_dataset() -> dict[str, object]:
    from alphaagent.server.services.high_relay import contracts
    from alphaagent.server.services.high_relay.backtest import _dyn_trades, build_events

    events, bars = build_events()
    nodes = attach_node_features(build_chain_nodes(bars), bars)
    names = events.drop_duplicates("代码").set_index("代码")["名称"]
    nodes["名称"] = nodes["代码"].map(names)
    done = events[~events["未完"]].copy()
    month_states = contracts.dyn_month_states(_dyn_trades(done))
    done["出手点"] = assign_take_points(done, month_states)
    linked = link_trade_events(nodes, done)
    enriched = attach_trade_to_nodes(nodes, linked)
    _write_split(enriched, NODES_PATH, "decision_date")
    _write_split(linked, EVENTS_PATH, "买入日")
    (DATA_DIR / "hpr_chain_month_states.json").write_text(
        pd.Series(month_states).to_json(force_ascii=False), encoding="utf-8")
    active = linked[linked["出手点"].fillna("") != ""]
    summary = {
        "nodes": int(len(nodes)),
        "nodes_3plus": int(nodes["N"].ge(3).sum()),
        "chains": int(nodes["chain_id"].nunique()),
        "events": int(len(linked)),
        "active": int(len(active)),
        "active_stats": summarize(active),
        "link_status": {str(key): int(value) for key, value in linked["link_status"].value_counts().items()},
        "sealed_missing_reached": int((linked["封住"] & linked["reached_anchor_id"].isna()).sum()),
        "features_missing": int(nodes["features_missing"].sum()),
    }
    (DATA_DIR / "hpr_chain_build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def load_nodes(include_final: bool = False) -> pd.DataFrame:
    frames = []
    for path in ([NODES_PATH, NODES_PATH.with_name(NODES_PATH.stem + "_2026.csv")]
                 if include_final else [NODES_PATH]):
        if not path.exists():
            raise SystemExit(f"数据不存在: {path}；请先执行 build")
        frames.append(pd.read_csv(path, low_memory=False, parse_dates=["anchor_date", "decision_date", "first_board_date", "foundation_date"]))
    nodes = pd.concat(frames, ignore_index=True)
    required = {"anchor_id", "chain_id", "decision_date", "N", "outcome", "next_open_pct"}
    missing = required - set(nodes.columns)
    if missing:
        raise SystemExit(f"全景数据缺少字段: {sorted(missing)}；请重新 build")
    return nodes


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "panorama"
    if command == "build":
        print(json.dumps(build_dataset(), ensure_ascii=False, indent=2))
    elif command == "panorama":
        data = load_nodes()
        reports = landscape_report(data)
        for name, report in reports.items():
            report.to_csv(DATA_DIR / f"hpr_chain_{name}.csv", index=False)
        print(json.dumps({
            "nodes": len(data),
            "nodes_3plus": int(data["N"].ge(3).sum()),
            "chains": int(data["chain_id"].nunique()),
            "outcomes": data["outcome"].value_counts().to_dict(),
            "yearly": reports["yearly"].to_dict("records"),
            "by_board": reports["by_board"].to_dict("records"),
        }, ensure_ascii=False, indent=2, default=str))
    elif command == "neighbors":
        data = load_nodes()
        cores = rule_core_masks(data)
        report = []
        for label, mask in cores.items():
            selected = data[mask & data["outcome"].ne("pending")]
            report.append({"rule": label, **outcome_summary(selected)})
        output = pd.DataFrame(report)
        output.to_csv(DATA_DIR / "hpr_chain_rule_core_outcomes.csv", index=False)
        print(output.to_json(orient="records", force_ascii=False, indent=2))
    elif command == "discover-trees":
        data = load_nodes()
        contexts = evolution_contexts(data)
        contexts = {key: value for key, value in contexts.items()
                    if key in {"全部正常开盘", "N2", "N3", "N4", "二接三阳", "二接三阴",
                               "三接四阳", "三接四阴", "末板一字", "末板实体", "末板下影", "链有一字"}}
        found = search_evolution_trees(data, research_features(data), contexts)
        flat = pd.DataFrame([flatten_search_result(item) for item in found])
        flat.to_csv(DATA_DIR / "hpr_chain_tree_search.csv", index=False)
        (DATA_DIR / "hpr_chain_tree_search.json").write_text(
            json.dumps(found, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps({"candidates": len(found), "top": flat.head(30).to_dict("records")},
                         ensure_ascii=False, indent=2, default=str))
    elif command == "discover-neighbors":
        data = load_nodes()
        found = []
        for label, mask in rule_core_masks(data).items():
            found.extend(search_evolution_factors(
                data, research_features(data), {label: mask}, bins=4,
                min_train=15, min_validation=4, target="multi"))
        found.sort(key=lambda item: (item["min_chain_lift"] + item["min_lift"]) / 2, reverse=True)
        flat = pd.DataFrame([flatten_search_result(item) for item in found])
        flat.to_csv(DATA_DIR / "hpr_chain_neighbor_search.csv", index=False)
        (DATA_DIR / "hpr_chain_neighbor_search.json").write_text(
            json.dumps(found, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps({"candidates": len(found), "top": flat.head(30).to_dict("records")},
                         ensure_ascii=False, indent=2, default=str))
    elif command in {"discover", "discover-multi"}:
        data = load_nodes()
        target = "multi" if command == "discover-multi" else "continue"
        found, flat = discover_and_persist(data, target)
        print(json.dumps({"candidates": len(found), "target": target, "top": flat.head(30).to_dict("records")},
                         ensure_ascii=False, indent=2, default=str))
    else:
        raise SystemExit(f"未知命令: {command}；当前可用 build / panorama / neighbors / discover / discover-multi / discover-neighbors / discover-trees")
