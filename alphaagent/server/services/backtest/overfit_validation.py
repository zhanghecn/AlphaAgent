"""CPCV / PBO / Deflated Sharpe 过拟合验证框架。

实现 Marcos López de Prado 体系的现代降过拟合三件套：
- CPCV (Combinatorial Purged Cross-Validation)：组合带 purge + embargo 的交叉验证，
  生成多条样本外回测路径，替代单路径 walk-forward。
- PBO (Probability of Backtest Overfitting)：量化策略过拟合的概率。
- Deflated Sharpe Ratio：修正多重检验 + 非正态的 Sharpe 显著性。

纯加法模块：通过 ``run_backtest(persist=False)`` 只读调用现有回测引擎，
不写库、不改任何策略代码，对 mainline_dragon_pullback / 0.1.21 零影响。

参考：Bailey & López de Prado (2014/2018)。
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date
from itertools import combinations
from statistics import NormalDist, mean, pstdev
from typing import Any

from alphaagent.server.services.backtest.engine import run_backtest
from alphaagent.server.services.backtest.schemas import BacktestParams

_EULER_MASCHERONI = 0.5772156649015329
_TRADING_DAYS_PER_YEAR = 252


# ---------------------------------------------------------------------------
# CPCV 路径生成（纯函数，不依赖数据库，便于单测）
# ---------------------------------------------------------------------------

def cpcv_split(
    dates: list[date],
    *,
    n_groups: int = 6,
    n_test_groups: int = 2,
    purge_days: int = 5,
    embargo_days: int = 3,
) -> list[dict[str, Any]]:
    """组合 purged 交叉验证分组。

    把 ``dates`` 按时间序均分 ``n_groups`` 组，取 ``C(n_groups, n_test_groups)`` 种
    组合作 test，其余作 train。train/test 边界各剥 ``purge_days``（防标签泄漏），
    test 之后 ``embargo_days`` 内的 train 样本丢弃（防趋势泄漏）。

    返回 ``[{"path_id", "train": [date], "test": [date], "test_groups": (idx...)}]``，
    跳过 purge 后 train/test 为空的路径。
    """
    if n_groups < 2 or n_test_groups < 1 or n_test_groups >= n_groups:
        raise ValueError(f"无效分组参数: n_groups={n_groups}, n_test_groups={n_test_groups}")
    if len(dates) < n_groups:
        raise ValueError(f"日期数 {len(dates)} 少于分组数 {n_groups}")

    sorted_dates = sorted(dates)
    group_size = len(sorted_dates) // n_groups
    groups: list[list[date]] = []
    for i in range(n_groups):
        start_i = i * group_size
        end_i = (i + 1) * group_size if i < n_groups - 1 else len(sorted_dates)
        groups.append(sorted_dates[start_i:end_i])

    paths: list[dict[str, Any]] = []
    for path_id, test_combo in enumerate(combinations(range(n_groups), n_test_groups)):
        test_idx_set = set(test_combo)
        train_idx = tuple(i for i in range(n_groups) if i not in test_idx_set)

        test_dates = _flatten(groups, test_combo)
        train_dates_raw = _flatten(groups, train_idx)
        if not test_dates or not train_dates_raw:
            continue

        test_min, test_max = min(test_dates), max(test_dates)
        # purge：剔除 train 中紧贴 test 两侧窗口的样本（标签泄漏）。
        purged = [
            d for d in train_dates_raw
            if abs((d - test_min).days) > purge_days and abs((d - test_max).days) > purge_days
        ]
        # embargo：剔除 test 之后的 train 样本（趋势/自相关泄漏）。
        embargoed = [d for d in purged if (d - test_max).days <= embargo_days and d > test_max]
        keep = [d for d in purged if d not in set(embargoed)]
        if not keep or not test_dates:
            continue
        paths.append({
            "path_id": path_id,
            "train": sorted(keep),
            "test": sorted(test_dates),
            "test_groups": test_combo,
        })
    return paths


def _flatten(groups: list[list[date]], idxs: tuple[int, ...]) -> list[date]:
    out: list[date] = []
    for i in idxs:
        out.extend(groups[i])
    return out


# ---------------------------------------------------------------------------
# run_backtest 结果提取
# ---------------------------------------------------------------------------

def _extract_daily_returns(equity: Any) -> list[float]:
    """从 run_backtest 返回的 equity 字段提取日收益率序列。

    equity 预期为 list[dict] 且每项含 ``total_equity``。做防御性提取，
    格式不符或长度不足时返回空列表（调用方据此跳过 DSR）。
    """
    if not equity or not isinstance(equity, list):
        return []
    values: list[float] = []
    for item in equity:
        te = item.get("total_equity") if isinstance(item, dict) else None
        if te is None:
            continue
        try:
            values.append(float(te))
        except (TypeError, ValueError):
            continue
    if len(values) < 2:
        return []
    return [values[i] / values[i - 1] - 1.0 for i in range(1, len(values))]


def _metrics_for_window(
    params: BacktestParams, start: date, end: date
) -> dict[str, Any] | None:
    """在 [start, end] 窗口跑一次回测（persist=False），返回 metrics + daily_returns。

    只读调用，不写库。窗口数据不足（trading_days < 80 或其它非 ready 状态）返回 None。
    """
    win_params = replace(params, start=start, end=end, persist=False)
    result = run_backtest(win_params)
    if result.get("status") != "ready":
        return None
    metrics = dict(result.get("metrics") or {})
    metrics["daily_returns"] = _extract_daily_returns(result.get("equity"))
    return metrics


# ---------------------------------------------------------------------------
# 日收益统计（DSR 需要 skew / kurtosis）
# ---------------------------------------------------------------------------

def skewness(values: list[float]) -> float:
    """样本偏度。数据不足返回 0。"""
    n = len(values)
    if n < 3:
        return 0.0
    m = mean(values)
    var = sum((x - m) ** 2 for x in values) / n
    if var <= 0:
        return 0.0
    sd = math.sqrt(var)
    return sum((x - m) ** 3 for x in values) / n / (sd ** 3)


def kurtosis(values: list[float]) -> float:
    """原点峰度（正态分布 = 3）。数据不足返回 3。"""
    n = len(values)
    if n < 4:
        return 3.0
    m = mean(values)
    var = sum((x - m) ** 2 for x in values) / n
    if var <= 0:
        return 3.0
    sd = math.sqrt(var)
    return sum((x - m) ** 4 for x in values) / n / (sd ** 4)


# ---------------------------------------------------------------------------
# PBO（过拟合概率）
# ---------------------------------------------------------------------------

def probability_of_backtest_overfitting(
    oos_ranks: list[int], *, n_variants: int
) -> dict[str, Any]:
    """PBO = P(IS 最优 variant 在 OOS 排名低于中位数)。

    ``oos_ranks``：每条 CPCV 路径上、IS 最优 variant 在该路径 OOS 中的排名
    （0 = 最差，n_variants-1 = 最好）。PBO 越高越过拟合（接近 1 = 严重过拟合）。

    logit_pbo = ln(pbo / (1-pbo))，越负越稳健。
    """
    if not oos_ranks or n_variants < 2:
        return {"pbo": None, "logit_pbo": None, "oos_ranks": list(oos_ranks), "n_variants": n_variants}
    median_rank = (n_variants - 1) / 2.0
    below = sum(1 for r in oos_ranks if r < median_rank)
    pbo = below / len(oos_ranks)
    if pbo <= 0:
        logit = float("-inf")
    elif pbo >= 1:
        logit = float("inf")
    else:
        logit = math.log(pbo / (1 - pbo))
    return {"pbo": pbo, "logit_pbo": logit, "oos_ranks": list(oos_ranks), "n_variants": n_variants}


# ---------------------------------------------------------------------------
# Deflated Sharpe Ratio
# ---------------------------------------------------------------------------

def deflated_sharpe_ratio(
    observed_sharpe: float | None,
    *,
    n_trials: int,
    sample_len: int,
    skew: float,
    kurt: float,
) -> dict[str, Any]:
    """Deflated Sharpe Ratio（Bailey & López de Prado 2014）。

    修正多重检验（``n_trials``）+ 非正态（``skew``/``kurt``）。

    ``observed_sharpe`` 应为**非年化**（日频）Sharpe。年化 Sharpe 需先除以 √252。
    ``sample_len`` 为日数；``skew``/``kurt`` 为日收益偏度/原点峰度（正态 kurt=3）。

    返回 ``dsr`` ∈ (0,1)：>0.95 才算多重检验后仍显著。
    """
    if observed_sharpe is None or sample_len < 2 or n_trials < 1:
        return {"dsr": None, "expected_max_sharpe": None, "z": None}
    nd = NormalDist()
    n = sample_len
    sr = float(observed_sharpe)
    # 非正态下 Sharpe 估计的标准差（López de Prado 公式）。
    denom_var = 1 - skew * sr + (kurt - 1) / 4.0 * sr * sr
    sigma_sr = math.sqrt(max(denom_var / max(n - 1, 1), 1e-12))
    # 多重检验下的期望最大 Sharpe。
    if n_trials > 1:
        z1 = nd.inv_cdf(1 - 1.0 / n_trials)
        z2 = nd.inv_cdf(1 - 1.0 / (n_trials * math.e))
        expected_max = sigma_sr * ((1 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2)
    else:
        expected_max = 0.0
    z = (sr - expected_max) / sigma_sr if sigma_sr > 0 else 0.0
    dsr = nd.cdf(z)
    return {"dsr": dsr, "expected_max_sharpe": expected_max, "z": z}


# ---------------------------------------------------------------------------
# CPCV 集成分析（调 run_backtest）
# ---------------------------------------------------------------------------

def cpcv_analyze(
    base_params: BacktestParams,
    *,
    variant_params: list[BacktestParams],
    trading_days: list[date],
    n_groups: int = 6,
    n_test_groups: int = 2,
    purge_days: int = 5,
    embargo_days: int = 3,
    metric: str = "sharpe",
    on_progress: Any = None,
) -> dict[str, Any]:
    """对一组参数变体跑 CPCV，算 PBO + Deflated Sharpe。

    流程（对每条 CPCV 路径 p）：
      1. 对每个 variant 在 IS(train) 窗口跑回测，取 IS ``metric``；
      2. 选 IS 最优 variant，在 OOS(test) 窗口跑回测，取它在 OOS 所有 variant 中的排名。
    PBO = IS 最优 variant 在 OOS 落在中位数以下的路径占比。
    DSR 用所有 OOS 路径的非年化 Sharpe + 日收益 skew/kurtosis 综合。

    ``metric`` 默认 ``sharpe``（越高越好）。
    ``on_progress`` 可选回调 ``fn(done, total, info)``，便于长任务上报。
    """
    n_variants = len(variant_params)
    if n_variants < 2:
        raise ValueError("variant_params 至少 2 个变体才能算 PBO")
    paths = cpcv_split(
        trading_days,
        n_groups=n_groups,
        n_test_groups=n_test_groups,
        purge_days=purge_days,
        embargo_days=embargo_days,
    )
    if not paths:
        raise ValueError("CPCV 未生成任何有效路径（日期太少或 purge/embargo 过大）")

    total = len(paths) * n_variants * 2  # 每路径每变体 IS+OOS
    done = 0
    oos_ranks: list[int] = []
    oos_sharpes: list[float] = []
    oos_daily_returns: list[float] = []
    path_reports: list[dict[str, Any]] = []

    for path in paths:
        train_start, train_end = path["train"][0], path["train"][-1]
        test_start, test_end = path["test"][0], path["test"][-1]

        is_metrics: list[dict[str, Any] | None] = []
        oos_metrics: list[dict[str, Any] | None] = []
        for variant in variant_params:
            is_m = _metrics_for_window(variant, train_start, train_end)
            done += 1
            if on_progress:
                on_progress(done, total, {"path_id": path["path_id"], "stage": "IS"})
            oos_m = _metrics_for_window(variant, test_start, test_end)
            done += 1
            if on_progress:
                on_progress(done, total, {"path_id": path["path_id"], "stage": "OOS"})
            is_metrics.append(is_m)
            oos_metrics.append(oos_m)

        # IS 选最优 variant（metric 最高；None 视为 -inf）。
        is_values = [
            (m.get(metric) if m and m.get(metric) is not None else float("-inf"))
            for m in is_metrics
        ]
        best_idx = max(range(n_variants), key=lambda i: is_values[i])
        if is_values[best_idx] == float("-inf"):
            continue  # 该路径全部失败，跳过。

        # best_idx variant 在 OOS 所有 variant 中的排名（按 metric 降序，0=最差）。
        oos_values = [
            (m.get(metric) if m and m.get(metric) is not None else float("-inf"))
            for m in oos_metrics
        ]
        rank = sum(1 for v in oos_values if v > oos_values[best_idx])
        oos_ranks.append(rank)

        best_oos = oos_metrics[best_idx]
        if best_oos and best_oos.get("sharpe") is not None:
            oos_sharpes.append(float(best_oos["sharpe"]))
            oos_daily_returns.extend(best_oos.get("daily_returns") or [])

        path_reports.append({
            "path_id": path["path_id"],
            "test_groups": list(path["test_groups"]),
            "best_variant_idx": best_idx,
            "is_metric": is_values[best_idx],
            "oos_metric": best_oos.get(metric) if best_oos else None,
            "oos_rank": rank,
        })

    pbo_report = probability_of_backtest_overfitting(oos_ranks, n_variants=n_variants)

    # DSR：用 OOS 非年化 Sharpe 的均值 + 所有 OOS 日收益的 skew/kurt。
    dsr_report: dict[str, Any] = {"dsr": None, "expected_max_sharpe": None, "z": None}
    if oos_sharpes and oos_daily_returns:
        observed = mean(oos_sharpes) / math.sqrt(_TRADING_DAYS_PER_YEAR)  # 年化 → 日频
        dsr_report = deflated_sharpe_ratio(
            observed,
            n_trials=n_variants,
            sample_len=len(oos_daily_returns),
            skew=skewness(oos_daily_returns),
            kurt=kurtosis(oos_daily_returns),
        )

    return {
        "metric": metric,
        "n_variants": n_variants,
        "n_paths": len(paths),
        "n_evaluated_paths": len(oos_ranks),
        "paths": path_reports,
        "pbo": pbo_report["pbo"],
        "logit_pbo": pbo_report["logit_pbo"],
        "dsr": dsr_report["dsr"],
        "dsr_expected_max_sharpe": dsr_report["expected_max_sharpe"],
        "oos_rank_distribution": {
            str(r): oos_ranks.count(r) for r in range(n_variants)
        },
        "oos_mean_sharpe_annualized": mean(oos_sharpes) if oos_sharpes else None,
    }
