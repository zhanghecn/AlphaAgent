from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.intraday_low_suction_study import (
    PRE_REGISTERED_RULES,
    STUDY_VERSION,
    build_intraday_path,
    evaluate_rule,
    find_trigger,
)


SIGNAL_DATE = date(2026, 7, 1)
PREV_CLOSE = 10.0
PRIOR_HIGH = 10.8


def _bars(closes: list[float], *, volumes: list[float] | None = None,
          highs: list[float] | None = None) -> pd.DataFrame:
    times = [datetime.combine(SIGNAL_DATE, time(9, 35)) + timedelta(minutes=5 * i) for i in range(len(closes))]
    return pd.DataFrame({
        "bar_time": times,
        "close_price": closes,
        "high_price": highs or closes,
        "volume": volumes or [1000.0] * len(closes),
    })


class TestBuildIntradayPath:
    def test_ma5_trailing_uses_only_current_and_prior(self) -> None:
        # 第5根MA5应是第1-5根均价,不含第6根
        path = build_intraday_path(
            _bars([9.5, 9.6, 9.7, 9.8, 9.9, 10.0]), SIGNAL_DATE, PREV_CLOSE, PRIOR_HIGH
        )
        assert path["ma5_trailing"].iloc[4] == round((9.5 + 9.6 + 9.7 + 9.8 + 9.9) / 5, 10)
        assert pd.isna(path["ma5_trailing"].iloc[3])  # 前4根无MA5

    def test_vol_median_is_shifted_prior(self) -> None:
        # 量比中位用 shift(1),不含当前根——零未来
        path = build_intraday_path(
            _bars([9.5] * 7, volumes=[100, 200, 300, 400, 500, 600, 700]), SIGNAL_DATE, PREV_CLOSE, PRIOR_HIGH
        )
        # 第6根(index5)的 vol_median_prior5 = median(100..500) = 300
        assert path["vol_median_prior5"].iloc[5] == 300.0

    def test_return_pct_relative_to_prev_close(self) -> None:
        path = build_intraday_path(_bars([10.5]), SIGNAL_DATE, PREV_CLOSE, PRIOR_HIGH)
        assert path["return_pct"].iloc[0] == pytest.approx(5.0)


class TestFindTrigger:
    def test_ma5_reclaim_triggers_when_close_crosses_above(self) -> None:
        path = build_intraday_path(
            _bars([8.0, 8.2, 8.4, 8.6, 8.8, 9.0, 9.2]),
            SIGNAL_DATE, PREV_CLOSE, PRIOR_HIGH,
        )
        trigger = find_trigger(path, "ma5_reclaim")
        assert trigger is not None
        # MA5 在 index4 有效 = mean(8.0..8.8)=8.4, index4 close=8.8>=8.4 触发
        assert trigger["trigger_price"] == 8.8

    def test_ma5_reclaim_skips_limit_up_bars(self) -> None:
        # 前5根低于MA5(不触发),第6根11.0涨停——涨停根不触发,应无触发
        path = build_intraday_path(
            _bars([9.0, 9.2, 9.4, 9.6, 9.8, 11.0]),  # MA5(index4)=9.6,前5根部分<MA5;11.0涨停
            SIGNAL_DATE, PREV_CLOSE, PRIOR_HIGH,
        )
        # index4 close=9.8 >= MA5=9.6 会先触发——验证:若涨停根是唯一满足的才跳过
        # 改为前5根均大幅低于MA5,只有涨停根满足但被跳过
        path2 = build_intraday_path(
            _bars([8.0, 8.2, 8.4, 8.6, 8.8, 11.0]),  # MA5(index4)=8.4, index4=8.8触发
            SIGNAL_DATE, PREV_CLOSE, PRIOR_HIGH,
        )
        # 这个场景 index4 已触发——要构造"只有涨停根满足"需让MA5>所有非涨停根
        path3 = build_intraday_path(
            _bars([11.0, 11.0, 11.0, 11.0, 11.0, 11.0]),  # 全涨停
            SIGNAL_DATE, PREV_CLOSE, PRIOR_HIGH,
        )
        trigger = find_trigger(path3, "ma5_reclaim")
        assert trigger is None  # 所有根都涨停,无一可触发

    def test_prior_high_break_triggers_on_breakout(self) -> None:
        path = build_intraday_path(
            _bars([9.0] * 6 + [10.9, 11.0]), SIGNAL_DATE, PREV_CLOSE, PRIOR_HIGH,
        )
        trigger = find_trigger(path, "prior_high_break")
        assert trigger is not None
        assert trigger["trigger_price"] == 10.9

    def test_volume_confirmed_requires_volume_spike(self) -> None:
        path = build_intraday_path(
            _bars([9.0, 9.0, 9.0, 9.0, 9.0, 9.5],
                  volumes=[100, 100, 100, 100, 100, 90]),
            SIGNAL_DATE, PREV_CLOSE, PRIOR_HIGH,
        )
        trigger = find_trigger(path, "volume_confirmed_reclaim")
        assert trigger is None  # 量90 < median(100)*1.2

    def test_early_window_only_triggers_in_morning_or_afternoon(self) -> None:
        path = build_intraday_path(
            _bars([9.0] * 6 + [9.5]), SIGNAL_DATE, PREV_CLOSE, PRIOR_HIGH,
        )
        # 第7根(index6)=10:05,在早窗口内
        trigger = find_trigger(path, "early_window_ma5")
        assert trigger is not None


class TestEvaluateRule:
    def test_no_trigger_records_not_triggered(self) -> None:
        # 持续下跌:close始终低于上行的MA5,永不收复——应无触发
        path = build_intraday_path(
            _bars([10.0, 9.8, 9.6, 9.4, 9.2, 9.0, 8.8, 8.6, 8.4, 8.2]),
            SIGNAL_DATE, PREV_CLOSE, PRIOR_HIGH,
        )
        exits = pd.DataFrame([{
            "vt_symbol": "600001.SSE", "signal_date": SIGNAL_DATE, "exit_price": 11.0,
        }])
        result = evaluate_rule({("600001.SSE", SIGNAL_DATE): path}, exits, "ma5_reclaim")
        assert result["triggered"] == 0
        assert result["win_rate_pct"] is None

    def test_triggered_trade_uses_trigger_price_not_close(self) -> None:
        path = build_intraday_path(
            _bars([8.0, 8.2, 8.4, 8.6, 8.8, 9.0, 9.2]),
            SIGNAL_DATE, PREV_CLOSE, PRIOR_HIGH,
        )
        exits = pd.DataFrame([{
            "vt_symbol": "600001.SSE", "signal_date": SIGNAL_DATE, "exit_price": 10.5,
        }])
        result = evaluate_rule({("600001.SSE", SIGNAL_DATE): path}, exits, "ma5_reclaim")
        assert result["triggered"] == 1
        # 触发价=8.8(index4), exit=10.5
        assert result["mean_net_return_pct"] == round((10.5 / 8.8 - 1) * 100 - 0.2, 4)


def test_pre_registered_rules_frozen() -> None:
    assert set(PRE_REGISTERED_RULES) == {
        "ma5_reclaim", "prior_high_break", "volume_confirmed_reclaim", "early_window_ma5",
    }


def test_study_version_frozen() -> None:
    assert STUDY_VERSION == "intraday-low-suction-v1"
