# -*- coding: utf-8 -*-
"""一接二综合最终版：统一规则、去重账本、分年收益与稳健性复核。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "量化因子研究" / "一接二"
OUT = BASE / "汇总"

RULE_NAMES = {
    "F1": "五日深跌·地基实体跌3~5",
    "F2": "地基巨震·首板换手3~5",
    "F3": "阴地基站线·二板开7.5~8.5",
    "F4": "全空头大阴·首板开口8~12",
    "F5": "阴地基强开·前20日涨30以上",
    "F6": "二板高开·首板低开未破60高",
    "F7": "地基大阴放量·首板换手微增",
    "F8": "急跌缩量·首板换手5~8",
    "F9": "全空头高开·首板换手微增",
    "F10": "近60日高·阳地基·前三日走强",
}


def _between(frame: pd.DataFrame, column: str, low: float, high: float) -> pd.Series:
    return frame[column].ge(low) & frame[column].lt(high)


def final_rule_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """返回最终十条入场规则；所有区间均为左闭右开，缺值不命中。"""
    return {
        "F1": frame["pre5_pct"].lt(-15) & _between(frame, "foundation_body", -5, -3),
        "F2": _between(frame, "b1_turn", 3, 5) & frame["foundation_amplitude"].ge(12),
        "F3": (
            _between(frame, "today_open", 7.5, 8.5)
            & frame["foundation_yang"].eq(False)
            & frame["foundation_pose"].eq("站线上")
        ),
        "F4": (
            frame["ma_state"].eq("---")
            & frame["foundation_body"].lt(-5)
            & _between(frame, "b1_gap", 8, 12)
        ),
        "F5": (
            frame["foundation_yang"].eq(False)
            & _between(frame, "b1_gap", 5, 8)
            & frame["pre20_pct"].ge(30)
        ),
        "F6": (
            _between(frame, "today_open", 8.5, 9.5)
            & frame["b1_open"].lt(0)
            & frame["b1_break60"].eq(False)
        ),
        "F7": (
            frame["foundation_body"].lt(-5)
            & _between(frame, "foundation_vol_rel5", 1.2, 1.5)
            & _between(frame, "b1_turn_change", 0, 2)
        ),
        "F8": (
            _between(frame, "b1_turn", 5, 8)
            & _between(frame, "b1_vol_rel5", 0.5, 0.8)
            & _between(frame, "pre3_pct", -15, -8)
        ),
        "F9": (
            frame["ma_state"].eq("---")
            & _between(frame, "today_open", 7.5, 8.5)
            & _between(frame, "b1_turn_change", 0, 2)
        ),
        "F10": (
            _between(frame, "dist_h60", -10, -8)
            & _between(frame, "foundation_body", 5, 7)
            & _between(frame, "pre3_pct", 5, 10)
        ),
    }


def build_final_ledger(frame: pd.DataFrame) -> pd.DataFrame:
    """同一股票同一交易日只保留一笔，并记录全部命中规则。"""
    valid = frame.copy()
    for column in ("unfinished", "data_bad_gap"):
        if column in valid:
            valid = valid[~valid[column].fillna(False).astype(bool)]
    masks = final_rule_masks(valid)
    selected = pd.Series(False, index=valid.index)
    labels = pd.Series("", index=valid.index, dtype=object)
    for rule_id, mask in masks.items():
        selected |= mask
        labels.loc[mask] = labels.loc[mask].where(
            labels.loc[mask].eq(""), labels.loc[mask] + "+"
        ) + rule_id
    ledger = valid.loc[selected].copy()
    ledger["rule_ids"] = labels.loc[selected]
    return ledger


def trade_stats(frame: pd.DataFrame) -> dict[str, float | int]:
    tail = frame["tail_pct"].dropna()
    return {
        "n": len(tail),
        "win": tail.gt(0).mean() * 100,
        "avg": tail.mean(),
        "median": tail.median(),
        "sum": tail.sum(),
        "trim3": tail.sort_values().iloc[:-3].mean() if len(tail) > 3 else np.nan,
    }


def robustness_stats(frame: pd.DataFrame, population: pd.DataFrame) -> dict[str, object]:
    rng = np.random.default_rng(20261029)
    tail = frame["tail_pct"]
    grouped = frame.groupby("month")["tail_pct"].agg(["count", "sum"])
    draws = rng.integers(0, len(grouped), size=(5000, len(grouped)))
    means = (
        grouped["sum"].to_numpy()[draws].sum(axis=1)
        / grouped["count"].to_numpy()[draws].sum(axis=1)
    )
    ci = np.quantile(means, [0.025, 0.975])

    sampled_sum = np.zeros(5000)
    sampled_n = np.zeros(5000)
    for month, chosen in frame.groupby("month"):
        pool = population.loc[population["month"].eq(month), "tail_pct"].to_numpy()
        picks = rng.integers(0, len(pool), size=(5000, len(chosen)))
        sampled_sum += pool[picks].sum(axis=1)
        sampled_n += len(chosen)
    null = sampled_sum / sampled_n

    months = frame.groupby("month").size().sort_values(ascending=False)
    days = frame.groupby("trade_date").size().sort_values(ascending=False)
    without_month = frame.loc[frame["month"].ne(months.index[0])]
    without_day = frame.loc[frame["trade_date"].ne(days.index[0])]
    oos = frame.loc[frame["segment"].eq("样本外")]
    return {
        **trade_stats(frame),
        "oos_n": len(oos),
        "oos_win": oos["tail_pct"].gt(0).mean() * 100,
        "oos_avg": oos["tail_pct"].mean(),
        "oos_trim3": trade_stats(oos)["trim3"],
        "month_ci_low": ci[0],
        "month_ci_high": ci[1],
        "month_null_p": (1 + int((null >= tail.mean()).sum())) / 5001,
        "null_median": float(np.median(null)),
        "null_p95": float(np.quantile(null, 0.95)),
        "top_month": months.index[0],
        "top_month_n": int(months.iloc[0]),
        "drop_month_win": without_month["tail_pct"].gt(0).mean() * 100,
        "drop_month_avg": without_month["tail_pct"].mean(),
        "top_day": days.index[0],
        "top_day_n": int(days.iloc[0]),
        "drop_day_win": without_day["tail_pct"].gt(0).mean() * 100,
        "drop_day_avg": without_day["tail_pct"].mean(),
    }


def main() -> None:
    events = pd.read_csv(BASE / "全量明细-open9.csv", low_memory=False)
    events["data_bad_gap"] = (
        events["today_open"].abs().gt(11)
        | events["b1_open"].abs().gt(11)
        | events["foundation_chg"].abs().gt(11)
    )
    ledger = build_final_ledger(events)
    clean = events.loc[~events["unfinished"] & ~events["data_bad_gap"]].copy()
    masks = final_rule_masks(clean)

    rule_rows = []
    for rule_id, mask in masks.items():
        other = np.logical_or.reduce([m for key, m in masks.items() if key != rule_id])
        total = clean.loc[mask]
        unique = clean.loc[mask & ~other]
        rule_rows.append({
            "rule_id": rule_id,
            "rule_cn": RULE_NAMES[rule_id],
            **{f"all_{key}": value for key, value in trade_stats(total).items()},
            **{f"unique_{key}": value for key, value in trade_stats(unique).items()},
        })

    yearly = []
    for year, group in ledger.groupby("year"):
        yearly.append({"year": year, **trade_stats(group)})

    ledger.to_csv(OUT / "open9_综合最终命中明细.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(rule_rows).to_csv(OUT / "open9_综合最终规则.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(yearly).to_csv(OUT / "open9_综合最终分年.csv", index=False, encoding="utf-8-sig")
    robust = robustness_stats(ledger, clean)
    pd.DataFrame([robust]).to_csv(OUT / "open9_综合最终稳健性.csv", index=False, encoding="utf-8-sig")

    print("FINAL", {key: round(value, 4) if isinstance(value, float) else value
                  for key, value in trade_stats(ledger).items()})
    print(pd.DataFrame(yearly).round(4).to_string(index=False))
    print("ROBUST", {key: round(value, 4) if isinstance(value, float) else value
                   for key, value in robust.items()})


if __name__ == "__main__":
    main()
