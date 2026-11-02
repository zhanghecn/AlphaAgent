"""规则页点口诀下钻:历史命中逐笔物化与 API 过滤。"""

from __future__ import annotations

import pandas as pd

from alphaagent.server.services.high_relay import backtest, service


def _frame() -> pd.DataFrame:
    rows = [
        {
            "代码": "001.SZSE", "名称": "弱强双中", "买入日": pd.Timestamp("2023-07-10"),
            "月": "2023-07", "组": "二接三", "四组": "二接三阳", "N": 2,
            "方案点": "A1", "方案子项": "低开等强开", "弱口诀": "K5",
            "买价": 10.0, "买入开盘%": 1.5, "封住": True, "持有天数": 2,
            "E3退出日": "2023-07-14", "E3退出价": 11.0, "E3原因": "break_close",
            "E3%": 10.0, "同票持仓重叠": False,
            "b1开盘%": 2.0, "b2开盘%": 5.0, "b3开盘%": None,
            "b1换手%": 4.0, "b2换手%": 6.0, "b3换手%": None,
            "地基涨跌%": 1.2, "地基姿态": "站线上", "距60日新高%": -12.3,
            "链": "实体→实体",
        },
        {
            "代码": "002.SZSE", "名称": "强中", "买入日": pd.Timestamp("2024-01-05"),
            "月": "2024-01", "组": "二接三", "四组": "二接三阴", "N": 2,
            "方案点": "B1", "方案子项": "转温", "弱口诀": "—",
            "买价": 20.0, "买入开盘%": 3.2, "封住": False, "持有天数": 1,
            "E3退出日": "2024-01-08", "E3退出价": 19.0, "E3原因": "break_day_close",
            "E3%": -5.0, "同票持仓重叠": False,
            "b1开盘%": -1.0, "b2开盘%": 2.0, "b3开盘%": None,
            "b1换手%": 5.0, "b2换手%": 8.0, "b3换手%": None,
            "地基涨跌%": -2.0, "地基姿态": "贴线", "距60日新高%": -20.0,
            "链": "下影→实体",
        },
        {
            "代码": "003.SZSE", "名称": "弱市强参考", "买入日": pd.Timestamp("2020-05-06"),
            "月": "2020-05", "组": "三接四", "四组": "三接四阳", "N": 3,
            "方案点": "A2", "方案子项": "", "弱口诀": "—",
            "买价": 8.0, "买入开盘%": 0.5, "封住": True, "持有天数": 3,
            "E3退出日": "2020-05-12", "E3退出价": 8.24, "E3原因": "break_close",
            "E3%": 3.0, "同票持仓重叠": False,
            "b1开盘%": 1.0, "b2开盘%": 2.0, "b3开盘%": 3.0,
            "b1换手%": 3.0, "b2换手%": 4.0, "b3换手%": 5.0,
            "地基涨跌%": 0.3, "地基姿态": "骑线", "距60日新高%": -8.0,
            "链": "实体→实体→实体",
        },
        {
            "代码": "004.SZSE", "名称": "重叠", "买入日": pd.Timestamp("2024-02-01"),
            "月": "2024-02", "组": "二接三", "四组": "二接三阳", "N": 2,
            "方案点": "A1", "方案子项": "低开等强开", "弱口诀": "—",
            "买价": 12.0, "买入开盘%": 2.0, "封住": True, "持有天数": 1,
            "E3退出日": "2024-02-05", "E3退出价": 12.12, "E3原因": "break_close",
            "E3%": 1.0, "同票持仓重叠": True,
            "b1开盘%": 1.0, "b2开盘%": 4.0, "b3开盘%": None,
            "b1换手%": 2.0, "b2换手%": 3.0, "b3换手%": None,
            "地基涨跌%": 1.8, "地基姿态": "站线上", "距60日新高%": -5.0,
            "链": "实体→下影",
        },
        {
            "代码": "005.SZSE", "名称": "K4分支", "买入日": pd.Timestamp("2020-06-01"),
            "月": "2020-06", "组": "三接四", "四组": "三接四阳", "N": 3,
            "方案点": "—", "方案子项": "", "弱口诀": "K4", "弱子项": "缩量承接",
            "买价": 9.0, "买入开盘%": 1.0, "封住": True, "持有天数": 1,
            "E3退出日": "2020-06-03", "E3退出价": 9.36, "E3原因": "break_close",
            "E3%": 4.0, "同票持仓重叠": False,
            "b1开盘%": 2.0, "b2开盘%": -1.0, "b3开盘%": 1.5,
            "b1换手%": 6.0, "b2换手%": 9.0, "b3换手%": 8.0,
            "地基涨跌%": 0.5, "地基姿态": "骑线", "距60日新高%": -6.0,
            "链": "实体→实体→实体",
        },
    ]
    return pd.DataFrame(rows)


STATES = {"2020-05": "weak", "2020-06": "weak", "2023-07": "weak",
          "2024-01": "strong", "2024-02": "strong"}


def test_koujue_trades_splits_double_hits_and_marks_taken() -> None:
    rows = backtest._koujue_trades(_frame(), STATES)
    assert len(rows) == 6

    by_key = {(row["code"], row["p"]): row for row in rows}
    weak, strong = by_key[("001.SZSE", "K5")], by_key[("001.SZSE", "A1")]
    # 双命中:弱市组 K5 当月成交,强市组 A1 同票只作参考(动态组只走一条)
    assert weak["g"] == "weak" and weak["tk"] is True and weak["tp"] == "K5"
    assert strong["g"] == "strong" and strong["tk"] is False and strong["tp"] == "K5"
    assert weak["r"] == 10.0 and weak["ap"] == 1.5
    assert weak["b2o"] == 5.0 and weak["fp"] == "站线上"

    assert by_key[("002.SZSE", "B1")]["tk"] is True
    assert by_key[("003.SZSE", "A2")]["tk"] is False
    # 弱市分支子项不在「方案子项」里,取「弱子项」(K4 两分支靠它过滤)
    assert by_key[("005.SZSE", "K4")]["s"] == "缩量承接"
    overlap = by_key[("004.SZSE", "A1")]
    assert overlap["ov"] is True and overlap["tk"] is True

    # 最新在前,便于排查
    assert rows[0]["d"] == "2024-02-01"
    assert rows[-1]["d"] == "2020-05-06"


def test_get_koujue_trades_filters_point_and_sub(monkeypatch) -> None:
    payload = {"koujue_trades": backtest._koujue_trades(_frame(), STATES),
               "built_at": "2026-11-01T00:00:00+08:00"}
    monkeypatch.setattr(service.repository, "load_backtest_report",
                        lambda _version: payload)

    out = service.get_koujue_trades("B1", "转温")
    assert out["status"] == "ok"
    assert out["count"] == 1
    assert out["trades"][0]["code"] == "002.SZSE"

    all_b1 = service.get_koujue_trades("B1")
    assert all_b1["count"] == 1
    assert all_b1["sub"] is None

    k4 = service.get_koujue_trades("K4", "缩量承接")
    assert k4["count"] == 1
    assert k4["trades"][0]["code"] == "005.SZSE"


def test_get_koujue_trades_unavailable_before_rebuild(monkeypatch) -> None:
    monkeypatch.setattr(service.repository, "load_backtest_report",
                        lambda _version: {"built_at": None})
    out = service.get_koujue_trades("A1")
    assert out["status"] == "unavailable"
    assert "重新计算" in str(out["reason"])
