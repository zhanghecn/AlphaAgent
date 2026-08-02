"""Tests for the sweep quality research (touch features / reseal prediction)."""

from __future__ import annotations

from alphaagent.server.services.limit_up import leader_sweep_quality_research as sweep_q


def _bar(bar_time: str, high: float, low: float, close: float, volume: float = 1.0e6, turnover: float = 1.0e7) -> dict:
    return {
        "bar_time": bar_time,
        "open_price": close,
        "high_price": high,
        "low_price": low,
        "close_price": close,
        "volume": volume,
        "turnover": turnover,
    }


def test_analyze_day_bars_touch_features() -> None:
    # 09:31-09:33 平盘，09:34 放量触板（volume 4x），09:40 开板
    bars = [
        _bar("09:31:00", 10.2, 10.0, 10.1, volume=1.0e6),
        _bar("09:32:00", 10.3, 10.05, 10.2, volume=1.0e6),
        _bar("09:33:00", 10.4, 10.1, 10.3, volume=1.0e6),
        _bar("09:34:00", 11.0, 10.5, 11.0, volume=4.0e6, turnover=4.4e7),  # 触板 bar
        _bar("09:35:00", 11.0, 11.0, 11.0),
        _bar("09:40:00", 11.0, 10.7, 10.75),  # 开板
        _bar("09:50:00", 11.0, 10.9, 11.0),  # 回封
    ]
    outcome = sweep_q.analyze_day_bars(bars, prev_close=10.0, open_price=10.1)
    assert outcome["touched"] is True
    assert outcome["first_touch_time"] == "09:34:00"
    assert outcome["first_touch_hour"] == 9
    assert outcome["minutes_to_touch"] == 3
    assert outcome["touch_bar_turnover"] == 4.4e7
    assert outcome["touch_volume_ratio"] == 4.0
    assert outcome["opened_after_touch"] is True
    assert outcome["first_open_time"] == "09:40:00"
    assert outcome["touch_bar_close_position"] == 1.0  # 收在 bar 最高
    assert outcome["open_gap_pct"] == 1.0  # 10.1/10-1


def test_analyze_day_bars_no_touch() -> None:
    bars = [_bar("09:31:00", 10.3, 10.0, 10.1), _bar("14:00:00", 10.5, 10.2, 10.4)]
    outcome = sweep_q.analyze_day_bars(bars, prev_close=10.0, open_price=10.1)
    assert outcome["touched"] is False
    assert outcome["first_touch_time"] is None
    assert outcome["opened_after_touch"] is False


def test_analyze_day_bars_sealed_never_opens() -> None:
    bars = [
        _bar("09:34:00", 11.0, 10.9, 11.0),  # 触板
        _bar("10:00:00", 11.0, 11.0, 11.0),
        _bar("15:00:00", 11.0, 11.0, 11.0),
    ]
    outcome = sweep_q.analyze_day_bars(bars, prev_close=10.0, open_price=10.0)
    assert outcome["touched"] is True
    assert outcome["opened_after_touch"] is False  # 封死未开


def test_analyze_day_bars_pre_touch_drawdown() -> None:
    bars = [
        _bar("09:31:00", 10.5, 10.0, 10.4),  # 冲高 10.5
        _bar("09:32:00", 10.4, 10.1, 10.2),  # 回撤到 10.1（自高点 -3.8%）
        _bar("09:33:00", 11.0, 10.6, 11.0),  # 触板
    ]
    outcome = sweep_q.analyze_day_bars(bars, prev_close=10.0, open_price=10.0)
    assert outcome["touched"] is True
    assert outcome["pre_touch_drawdown_pct"] > 3.5  # 拉升过程有明显分歧


def _sample(value: float, *, resealed: bool) -> dict:
    return {"factor_x": value, "resealed": resealed, "_resealed_label": resealed}


def test_compare_touch_feature_auc_and_quintiles() -> None:
    samples = [_sample(v, resealed=v > 50) for v in range(100)]
    report = sweep_q.compare_touch_feature(samples, "factor_x", "_resealed_label")
    assert report["auc"] is not None and report["auc"] > 0.99
    assert report["direction"] == "higher"
    assert report["quintiles"][0]["rate"] == 0.0
    assert report["quintiles"][-1]["rate"] == 1.0
