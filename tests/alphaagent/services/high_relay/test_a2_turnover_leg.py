"""hpr-v7.23 A2 一板/地基换手中等扩张腿：边界、镜像与字段同源。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alphaagent.server.db import schema
from alphaagent.server.services.high_relay import contracts, pool, quiz


def _a2(**overrides):
    kwargs = {
        "b1_open": 0.0, "b2_open": 10.0, "b3_open": None,
        "auction_pct": 7.5, "b2_turn": 3.0,
        "pre10_pct": 5.0, "dist_ma10": 2.0,
    }
    kwargs.update(overrides)
    return pool.tag_scheme("二接三阳", **kwargs)


def test_a2_blocks_only_middle_turnover_ratio():
    for value in (1.45, 1.5, 1.6, 1.749):
        assert _a2(b1_f_turn_ratio=value) is None
    for value in (1.44, 1.75, 0.8, 2.2, None):
        hit = _a2(b1_f_turn_ratio=value)
        assert hit is not None and hit["no"] == "A2"


def test_a2_other_legs_still_apply():
    # 换手带只影响 A2 自身；C3 不应被这条腿拦住。
    hit = pool.tag_scheme(
        "三接四阳", b1_open=0.0, b2_open=10.0, b3_open=0.0,
        auction_pct=7.0, b3_turn=4.0, b1_f_turn_ratio=1.6,
    )
    assert hit["no"] == "C3"


def test_match_schemes_and_entry_candidates_share_leg():
    assert pool.match_schemes(
        "二接三阳", 0.0, 10.0, None, b2_turn=3.0,
        pre10_pct=5.0, dist_ma10=2.0, b1_f_turn_ratio=1.6,
    ) == []
    assert pool.match_schemes(
        "二接三阳", 0.0, 10.0, None, b2_turn=3.0,
        pre10_pct=5.0, dist_ma10=2.0, b1_f_turn_ratio=1.44,
    )
    entry = {
        "group4": "二接三阳", "b1_open": 0.0, "b2_open": 10.0,
        "b3_open": None, "b2_turn": 3.0, "pre10_pct": 5.0,
        "dist_ma10": 2.0, "b1_f_turn_ratio": 1.6,
    }
    assert pool.entry_candidates(entry) == []


def _stock_bars() -> pd.DataFrame:
    closes = [10.0, 12.0, 11.0, 11.5, 10.8, 12.5, 10.5, 11.0, 10.0, 11.2]
    closes += [11.0 + (i % 5) * 0.15 for i in range(20)]
    rows = []
    previous = closes[0]
    dates = pd.bdate_range("2024-01-01", periods=len(closes) + 2)
    for index, close in enumerate(closes):
        rows.append({
            "vt_symbol": "000001.SZSE", "trade_date": dates[index],
            "open_price": close, "high_price": close * 1.01, "low_price": close * 0.99,
            "close_price": close, "volume": 10000 + index * 100,
            "turnover_rate": 2.0 + index % 4,
        })
        previous = close
    for _ in range(2):
        limit = round(previous * 1.10 + 1e-9, 2)
        rows.append({
            "vt_symbol": "000001.SZSE", "trade_date": dates[len(rows)],
            "open_price": previous * 1.02, "high_price": limit, "low_price": previous * 0.98,
            "close_price": limit, "volume": 15000, "turnover_rate": 6.0,
        })
        previous = limit
    return pd.DataFrame(rows)


def test_static_fields_computes_ratio_from_past_bars_only():
    bars = pool.derive_daily(_stock_bars())
    i_last = len(bars) - 1
    rec = pool.static_fields(pool.make_ctx(bars), i_last, 2)
    foundation = bars.iloc[i_last - 2]
    expected = float(bars.iloc[i_last - 1]["turnover_rate"]) / float(foundation["turnover_rate"])
    assert rec["b1_f_turn_ratio"] == pytest.approx(round(expected, 4))

    changed = bars.copy()
    changed.loc[changed.index > i_last, ["high_price", "low_price", "close_price", "volume"]] *= 5
    assert pool.static_fields(pool.make_ctx(changed), i_last, 2) == rec


def test_quiz_explains_turnover_leg():
    reasons, _, fail_fields, _ = quiz.explain_miss(
        n_board=2, yang=True, group4="二接三阳",
        b1_open=0.0, b2_open=10.0, b3_open=None,
        b2_turn=3.0, b3_turn=None, buy_open=7.5,
        pre20_pct=5.0, pre10_pct=5.0, foundation_chg=0.0,
        dist_ma10=2.0, b1_f_turn_ratio=1.6,
    )
    assert "一板/地基换手" in fail_fields
    assert any("一板/地基换手" in line for line in reasons)
    assert quiz._row_fails(fail_fields) == ["ground"]


def test_version_and_schema_column():
    assert contracts.HPR_RULES_VERSION == "hpr-v7.23"
    assert quiz.QUIZ_CONTENT_VERSION == 56
    assert "b1_f_turn_ratio" in schema.hpr_pool_entries.c
