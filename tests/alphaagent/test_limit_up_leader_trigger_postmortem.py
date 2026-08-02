"""Tests for trigger minute features and the trigger postmortem analysis."""

from __future__ import annotations

from alphaagent.server.services.limit_up import leader_minute_backtest as engine
from alphaagent.server.services.limit_up import leader_trigger_postmortem as pm


def _bar(bar_time: str, close: float, volume: float = 1.0e6) -> dict:
    return {
        "bar_time": bar_time,
        "close_price": close,
        "open_price": close,
        "high_price": close,
        "low_price": close,
        "volume": volume,
    }


# ── 触发类型/序号（_trigger_buy 增强）─────────────────────────────────


def test_trigger_buy_reports_kind_and_index() -> None:
    bars = [
        _bar("09:31:00", 10.1),
        _bar("09:32:00", 10.15),
        _bar("09:33:00", 10.4),  # surge 2.46% ≥ 2% → surge 触发，第 3 根（index 2）
    ]
    trigger = engine._trigger_buy(
        bars,
        open_price=10.0,
        prev_close=10.0,
        surge_pct=2.0,
        cum_pct=7.0,
        window_start="09:31:00",
        window_end="09:40:00",
    )
    assert trigger["trigger_kind"] == "surge"
    assert trigger["trigger_index"] == 2
    assert trigger["surge_pct_at_trigger"] == 2.4631


def test_trigger_buy_cum_kind_when_no_single_surge() -> None:
    # 每根 surge <2% 但累计到 7.2% → cum 触发
    bars = [
        _bar("09:31:00", 10.15),
        _bar("09:32:00", 10.3),
        _bar("09:33:00", 10.45),
        _bar("09:34:00", 10.6),
        _bar("09:35:00", 10.72),
    ]
    trigger = engine._trigger_buy(
        bars,
        open_price=10.0,
        prev_close=10.0,
        surge_pct=2.0,
        cum_pct=7.0,
        window_start="09:31:00",
        window_end="09:40:00",
    )
    assert trigger["trigger_kind"] == "cum"


# ── 分时特征 ───────────────────────────────────────────────────────────


def test_trigger_minute_features() -> None:
    bars = [
        _bar("09:31:00", 10.05, volume=1.0e6),
        _bar("09:32:00", 10.02, volume=1.0e6),
        _bar("09:33:00", 10.3, volume=4.0e6),
    ]
    trigger = {"buy_price": 10.3, "buy_time": "09:33:00"}
    features = engine._trigger_minute_features(
        bars, trigger, open_price=10.0, prev_close=9.8
    )
    assert features["open_gap_pct"] == 2.0408  # 10/9.8-1
    # 涨停价 9.8×1.1=10.78 → 距涨停 (10.3/10.78-1)×100
    assert features["distance_to_limit_at_trigger_pct"] == -4.4527
    assert features["pre_trigger_consolidation_pct"] == 0.3  # (10.05-10.02)/10×100
    assert features["trigger_volume_ratio"] == 4.0  # 触发 bar 量 / 前 2 根均量


# ── 日线位置/量能补充因子 ──────────────────────────────────────────────


def test_daily_position_volume_features() -> None:
    bars = []
    for index in range(20):
        close = 9.0 + index * 0.05  # 9.0 → 9.95 缓涨
        bars.append(
            {
                "close_price": close,
                "high_price": close + 0.1,
                "low_price": close - 0.1,
                "turnover": 1.0e8 if index < 19 else 3.0e8,
            }
        )
    features = engine._daily_position_volume_features(bars)
    assert features["position_20d"] is not None and features["position_20d"] > 0.9  # 接近区间顶
    assert features["bias_ma5_pct"] is not None and features["bias_ma5_pct"] > 0  # 站上 MA5
    assert features["bias_ma20_pct"] is not None and features["bias_ma20_pct"] > 0
    assert features["turnover_1d_vs_20d"] is not None and features["turnover_1d_vs_20d"] > 2.5
    # 不足 20 根 → 全 None
    assert engine._daily_position_volume_features(bars[:10])["position_20d"] is None


# ── 归因分析 ───────────────────────────────────────────────────────────


def _sample(
    value: float,
    *,
    win: bool,
    status: str = "sealed",
    kind: str = "surge",
    cum: float = 5.0,
    dist: float = -2.0,
) -> dict:
    return {
        "factor_x": value,
        "is_leader": win,
        "board_status": status,
        "trigger_kind": kind,
        "cum_pct": cum,
        "distance_to_limit_at_trigger_pct": dist,
    }


def test_compare_feature_win_and_seal_auc() -> None:
    # 值大 → 赢且封板；值小 → 亏且未封
    samples = [_sample(v, win=v > 50, status="sealed" if v > 50 else "no_limit") for v in range(100)]
    report = pm.compare_feature(samples, "factor_x")
    assert report["win_auc"] is not None and report["win_auc"] > 0.99
    assert report["seal_auc"] is not None and report["seal_auc"] > 0.99
    assert report["win_direction"] == "higher"
    assert len(report["quintiles"]) == 5
    assert report["quintiles"][0]["win_rate"] == 0.0
    assert report["quintiles"][-1]["seal_rate"] == 1.0


def test_group_stats_rates() -> None:
    samples = [
        _sample(1, win=True, status="sealed"),
        _sample(2, win=True, status="sealed"),
        _sample(3, win=False, status="failed"),
        _sample(4, win=False, status="no_limit"),
    ]
    stats = pm._group_stats(samples)
    assert stats["win_rate"] == 0.5
    assert stats["seal_rate"] == 0.5
    assert stats["touch_rate"] == 0.75
    assert stats["sealed_win_share"] == 0.5
    assert stats["sealed_win_rate"] == 1.0


def test_cum_distance_matrix_filters_thin_cells() -> None:
    samples = [
        _sample(i, win=i % 2 == 0, cum=5.0, dist=-2.0) for i in range(25)
    ] + [
        _sample(i, win=True, cum=9.0, dist=-1.0) for i in range(3)  # n=3 < 20 → 格被过滤
    ]
    matrix = pm.build_cum_distance_matrix(samples)
    assert len(matrix) == 1
    cell = matrix[0]
    assert cell["total"] == 25
    assert cell["win_rate"] == 0.52


def test_postmortem_report_end_to_end() -> None:
    samples = [
        _sample(v, win=v > 40, status="sealed" if v > 60 else ("failed" if v > 30 else "no_limit"))
        for v in range(100)
    ]
    report = pm.build_postmortem_report(samples, source="test")
    assert report["status"] == "ok"
    assert report["labeled_count"] == 100
    assert report["baseline"]["total"] == 100
    assert len(report["trigger_kind"]) == 2
    markdown = pm.render_markdown(report)
    assert "基线" in markdown and "因子排行" in markdown
