"""hpr-v7.22 轻量质量字段：判定已撤回，字段保留、不再过滤。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alphaagent.server.db import schema
from alphaagent.server.services.high_relay import contracts, pool, quiz


def _a1_warm(**overrides):
    kwargs = {
        "b1_open": 1.0, "b2_open": 0.0, "b3_open": None,
        "auction_pct": 4.0, "b2_turn": 5.0,
    }
    kwargs.update(overrides)
    return pool.tag_scheme("二接三阳", **kwargs)


def _c2(**overrides):
    kwargs = {
        "b1_open": 0.0, "b2_open": 0.0, "b3_open": 0.0,
        "auction_pct": 6.0, "b3_turn": 15.0,
    }
    kwargs.update(overrides)
    return pool.tag_scheme("三接四阳", **kwargs)


def test_a1_warm_branch_ignores_withdrawn_lower_shadow_band():
    # v7.22: 下影合计字段保留，但不再参与 A1·平开等温开判定。
    for value in (4.75, 5.336146, 5.5, 4.749, None):
        hit = _a1_warm(chain_lower_sum=value)
        assert hit is not None and hit["sub"] == "平开等温开"


def test_a1_low_open_branch_is_not_constrained_by_warm_branch_leg():
    hit = pool.tag_scheme(
        "二接三阳", b1_open=-1.0, b2_open=0.0, b3_open=None,
        auction_pct=7.0, b2_turn=5.0, chain_lower_sum=5.336146,
    )
    assert hit["sub"] == "低开等强开"


def test_c2_rejects_only_frozen_drawdown_band():
    assert _c2(pre20_max_drawdown=-7.5) is None
    assert _c2(pre20_max_drawdown=-6.572165) is None
    assert _c2(pre20_max_drawdown=-5.0)["no"] == "C2"
    assert _c2(pre20_max_drawdown=-7.49) is None
    assert _c2(pre20_max_drawdown=-4.99)["no"] == "C2"
    assert _c2(pre20_max_drawdown=None)["no"] == "C2"


def test_c3_is_not_constrained_by_c2_drawdown_leg():
    hit = pool.tag_scheme(
        "三接四阳", b1_open=0.0, b2_open=10.0, b3_open=0.0,
        auction_pct=7.0, b3_turn=4.0, pre20_max_drawdown=-6.0,
    )
    assert hit["no"] == "C3"


def test_match_schemes_and_entry_candidates_apply_only_c2_leg():
    assert pool.match_schemes(
        "二接三阳", 1.0, 0.0, None, b2_turn=5.0, chain_lower_sum=5.2,
    )
    assert not pool.match_schemes(
        "三接四阳", 0.0, 0.0, 0.0, b3_turn=15.0, pre20_max_drawdown=-6.0,
    )
    entry = {
        "group4": "二接三阳", "b1_open": 1.0, "b2_open": 0.0, "b3_open": None,
        "b2_turn": 5.0, "chain_lower_sum": 5.2,
    }
    assert pool.entry_candidates(entry)


def _stock_bars() -> pd.DataFrame:
    closes = [10.0, 12.0, 11.0, 11.5, 10.8, 12.5, 10.5, 11.0, 10.0, 11.2]
    closes += [11.0 + (i % 5) * 0.15 for i in range(20)]
    rows = []
    previous = closes[0]
    for index, close in enumerate(closes):
        rows.append({
            "vt_symbol": "000001.SZSE", "trade_date": pd.bdate_range("2024-01-01", periods=len(closes))[index],
            "open_price": close, "high_price": close * 1.01, "low_price": close * 0.99,
            "close_price": close, "volume": 10000 + index * 100, "turnover_rate": 2.0 + index % 4,
        })
        previous = close
    for _ in range(2):
        limit = round(previous * 1.10 + 1e-9, 2)
        rows.append({
            "vt_symbol": "000001.SZSE", "trade_date": pd.bdate_range("2024-01-01", periods=len(closes) + 2)[len(rows)],
            "open_price": previous * 1.02, "high_price": limit, "low_price": previous * 0.98,
            "close_price": limit, "volume": 15000, "turnover_rate": 6.0,
        })
        previous = limit
    return pd.DataFrame(rows)


def test_static_fields_computes_new_features_from_past_bars_only():
    bars = pool.derive_daily(_stock_bars())
    i_last = len(bars) - 1
    rec = pool.static_fields(pool.make_ctx(bars), i_last, 2)
    expected_lower = 0.0
    for index in (i_last - 1, i_last):
        row = bars.iloc[index]
        expected_lower += ((min(row["open_price"], row["close_price"]) - row["low_price"])
                           / row["prev_close"] * 100)
    assert rec["chain_lower_sum"] == pytest.approx(expected_lower)

    foundation_i = i_last - 2
    close = bars["close_price"].iloc[foundation_i - 19:foundation_i + 1].to_numpy()
    running_high = np.maximum.accumulate(close)
    expected_drawdown = float(np.min(close / running_high - 1) * 100)
    assert rec["pre20_max_drawdown"] == pytest.approx(expected_drawdown)

    changed = bars.copy()
    changed.loc[changed.index > i_last, ["high_price", "low_price", "close_price", "volume"]] *= 5
    assert pool.static_fields(pool.make_ctx(changed), i_last, 2) == rec


def test_quiz_explains_only_c2_drawdown_leg():
    reasons, _, fail_fields, _ = quiz.explain_miss(
        n_board=2, yang=True, group4="二接三阳",
        b1_open=1.0, b2_open=0.0, b3_open=None,
        b2_turn=15.0, b3_turn=None, buy_open=4.0,
        pre20_pct=5.0, foundation_chg=0.0, chain_lower_sum=5.2,
    )
    assert "下影合计" not in fail_fields
    assert not any("下影合计" in line for line in reasons)

    reasons, _, fail_fields, _ = quiz.explain_miss(
        n_board=3, yang=True, group4="三接四阳",
        b1_open=0.0, b2_open=0.0, b3_open=0.0,
        b2_turn=10.0, b3_turn=15.0, buy_open=6.0,
        pre20_pct=5.0, pre10_pct=5.0, foundation_chg=0.0,
        pre20_max_drawdown=-6.0,
    )
    assert "前20日回撤" in fail_fields
    assert any("前20日回撤" in line for line in reasons)


def test_light_quality_version_and_schema_columns():
    assert contracts.HPR_RULES_VERSION == "hpr-v7.22"
    assert quiz.QUIZ_CONTENT_VERSION == 55
    assert "chain_lower_sum" in schema.hpr_pool_entries.c
    assert "pre20_max_drawdown" in schema.hpr_pool_entries.c
