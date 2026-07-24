"""方向②阶段B:盘中低吸点算法研究(零未来函数 + 防过拟合)。
在 167 个 reclaim 信号日的 5m 数据上,测预登记的盘中触发规则。
红线:所有指标只用决策时点 T 及之前的 5m,入场价=触发那根收盘,退出沿用因果规则。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

STUDY_VERSION = "intraday-low-suction-v1"
ROUND_TRIP_COST_PCT = 0.2
LIMIT_UP_PCT = 9.8  # 涨停线(相对前收)
EARLY_WINDOWS = (("09:35", "10:30"), ("13:00", "14:00"))  # 避开尾盘涨停区

PRE_REGISTERED_RULES = (
    "ma5_reclaim",
    "prior_high_break",
    "volume_confirmed_reclaim",
    "early_window_ma5",
)


def build_intraday_path(
    minute_bars: pd.DataFrame,
    signal_date: date,
    prev_close: float,
    prior_high: float,
) -> pd.DataFrame:
    """对齐单信号日的 5m 路径,挂载 trailing 指标(截至每根,无未来)。"""

    frame = minute_bars.copy()
    frame["bar_time"] = pd.to_datetime(frame["bar_time"])
    frame = frame.loc[frame["bar_time"].dt.date == signal_date].sort_values("bar_time")
    if frame.empty:
        return frame
    close = pd.to_numeric(frame["close_price"], errors="coerce")
    # trailing MA5:截至当前根(含)的最近5根收盘均价——只用当前及之前,无未来
    frame["ma5_trailing"] = close.rolling(5, min_periods=5).mean()
    frame["return_pct"] = (close / prev_close - 1.0) * 100.0
    frame["prior_high"] = prior_high
    frame["prev_close"] = prev_close
    frame["at_limit"] = frame["return_pct"] >= LIMIT_UP_PCT
    vol = pd.to_numeric(frame["volume"], errors="coerce")
    frame["vol_median_prior5"] = vol.rolling(5, min_periods=5).median().shift(1)
    return frame.reset_index(drop=True)


def find_trigger(
    path: pd.DataFrame,
    rule: str,
) -> dict[str, Any] | None:
    """返回首个触发根的时点与价格;无触发返回 None。全部用 trailing,零未来。"""

    if path.empty:
        return None
    ma5_ok = path["ma5_trailing"].notna() & (path["close_price"] >= path["ma5_trailing"])
    high_broken = path["close_price"] > path["prior_high"]
    vol_ok = (
        path["vol_median_prior5"].notna()
        & (pd.to_numeric(path["volume"], errors="coerce") > path["vol_median_prior5"] * 1.2)
    )
    not_at_limit = ~path["at_limit"]
    if rule == "ma5_reclaim":
        mask = ma5_ok & not_at_limit
    elif rule == "prior_high_break":
        mask = high_broken & not_at_limit
    elif rule == "volume_confirmed_reclaim":
        mask = ma5_ok & vol_ok & not_at_limit
    elif rule == "early_window_ma5":
        hm = path["bar_time"].dt.strftime("%H:%M")
        in_window = pd.Series(False, index=path.index)
        for start, end in EARLY_WINDOWS:
            in_window |= hm.between(start, end)
        mask = ma5_ok & not_at_limit & in_window
    else:
        return None
    hits = path.loc[mask]
    if hits.empty:
        return None
    first = hits.iloc[0]
    return {
        "trigger_time": first["bar_time"],
        "trigger_price": float(first["close_price"]),
        "trigger_return_pct": float(first["return_pct"]),
        "at_limit_at_trigger": bool(first["at_limit"]),
    }


def evaluate_rule(
    paths: dict[tuple[str, date], pd.DataFrame],
    exits: pd.DataFrame,
    rule: str,
) -> dict[str, Any]:
    """对每条规则,定位盘中触发点,用因果退出价算收益。"""

    records: list[dict[str, Any]] = []
    for (vt_symbol, signal_date), path in paths.items():
        exit_row = exits.loc[
            (exits["vt_symbol"] == vt_symbol)
            & (pd.to_datetime(exits["signal_date"]).dt.date == signal_date)
        ]
        if exit_row.empty:
            continue
        exit_price = float(exit_row.iloc[0]["exit_price"])
        trigger = find_trigger(path, rule)
        if trigger is None:
            records.append({"rule": rule, "vt_symbol": vt_symbol, "signal_date": signal_date,
                            "triggered": False})
            continue
        entry = trigger["trigger_price"]
        net = (exit_price / entry - 1.0) * 100.0 - ROUND_TRIP_COST_PCT
        records.append({
            "rule": rule, "vt_symbol": vt_symbol, "signal_date": signal_date,
            "triggered": True, "entry_price": entry, "exit_price": exit_price,
            "net_return_pct": net, "trigger_return_pct": trigger["trigger_return_pct"],
            "at_limit_at_trigger": trigger["at_limit_at_trigger"],
            "trigger_time": trigger["trigger_time"],
        })
    return _summarize(records, rule)


def _summarize(records: list[dict[str, Any]], rule: str) -> dict[str, Any]:
    frame = pd.DataFrame(records)
    triggered = frame.loc[frame.get("triggered", pd.Series(dtype=bool)).astype(bool)]
    if triggered.empty:
        return {"rule": rule, "triggered": 0, "win_rate_pct": None,
                "mean_net_return_pct": None, "profit_factor": None,
                "fillable_rate_pct": None}
    rets = pd.to_numeric(triggered["net_return_pct"], errors="coerce").dropna()
    wins = rets[rets > 0]
    loss = rets[rets < 0]
    pf = float(wins.sum() / -loss.sum()) if not loss.empty else None
    at_limit = pd.Series(triggered["at_limit_at_trigger"]).astype(bool)
    fillable = (~at_limit).mean() * 100.0
    return {
        "rule": rule,
        "triggered": int(len(triggered)),
        "win_rate_pct": round(float(rets.gt(0).mean() * 100.0), 2),
        "mean_net_return_pct": round(float(rets.mean()), 4),
        "profit_factor": round(pf, 3) if pf else None,
        "fillable_rate_pct": round(float(fillable), 2),
        "median_trigger_return_pct": round(float(triggered["trigger_return_pct"].median()), 2),
    }
