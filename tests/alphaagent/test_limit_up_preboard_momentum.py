from __future__ import annotations

from copy import deepcopy

from alphaagent.server.services.limit_up.preboard_momentum import (
    ALGORITHMS,
    build_prefix_rows,
    first_rule_signal,
)
from alphaagent.server.services.limit_up.preboard_momentum_data import (
    official_five_minute_close_times,
)


def test_acceleration_signal_uses_only_completed_prefix_and_next_open() -> None:
    bars = _acceleration_bars()
    manifest = _manifest()

    baseline_rows = build_prefix_rows(manifest, bars)
    baseline = first_rule_signal(baseline_rows, "acceleration")
    mutated_bars = deepcopy(bars)
    for row in mutated_bars:
        if row["bar_time"] >= "2026-07-01T10:15:00":
            row.update(close_price=5.0, high_price=5.0, low_price=5.0, volume=99_000.0)
    mutated_manifest = {**manifest, "sealed_limit": False, "d1_close_price": 1.0}
    mutated = first_rule_signal(
        build_prefix_rows(mutated_manifest, mutated_bars),
        "acceleration",
    )

    assert baseline is not None
    assert baseline["signal_time"] == "10:05:00"
    assert baseline["entry_time"] == "10:06:00"
    assert baseline["entry_price"] == 10.45
    assert baseline["features"] == mutated["features"]
    assert baseline["signal_time"] == mutated["signal_time"]
    assert baseline["entry_price"] == mutated["entry_price"]


def test_compression_breakout_waits_for_observable_break() -> None:
    signal = first_rule_signal(
        build_prefix_rows(_manifest(), _compression_bars()),
        "compression_breakout",
    )

    assert signal is not None
    assert signal["signal_time"] == "10:10:00"
    assert signal["features"]["prior_30m_range_pct"] <= 1.5
    assert signal["features"]["prior_30m_floor_pct"] >= 2.0
    assert signal["features"]["breakout_margin_pct"] >= 0.2


def test_hybrid_takes_first_chronological_rule_signal() -> None:
    rows = build_prefix_rows(_manifest(), _acceleration_bars())

    acceleration = first_rule_signal(rows, "acceleration")
    hybrid = first_rule_signal(rows, "hybrid_rule")

    assert acceleration is not None
    assert hybrid is not None
    assert hybrid["signal_time"] == acceleration["signal_time"]
    assert hybrid["algorithm"] == "hybrid_rule"


def test_every_frozen_rule_rejects_a_limit_price_next_open() -> None:
    bars = _acceleration_bars()
    next_bar = next(row for row in bars if row["bar_time"].endswith("10:10:00"))
    next_bar["open_price"] = 11.0
    rows = build_prefix_rows(_manifest(), bars)

    assert "support_3pct" in ALGORITHMS
    assert all(
        first_rule_signal(rows, algorithm) is None
        for algorithm in ("support_3pct", "acceleration", "hybrid_rule")
    )


def test_support_rule_accepts_gain_above_nine_point_five_before_exact_touch() -> None:
    closes = [10.0] * 6 + [10.98, 10.99]
    bars = _bars(closes, [100.0] * len(closes))
    bars[6]["high_price"] = 10.99
    bars[6]["low_price"] = 10.0

    signal = first_rule_signal(build_prefix_rows(_manifest(), bars), "support_3pct")

    assert signal is not None
    assert signal["features"]["gain_pct"] == 9.8
    assert signal["before_first_limit_touch"] is True
    assert signal["entry_price"] == 10.98


def test_prefix_features_carry_normalized_prior_recommendation_evidence() -> None:
    manifest = {
        **_manifest(),
        "prior_limit_count_126": 6,
        "prior_touch_count_126": 8,
        "prior_seal_success_rate_126": 0.75,
        "stock_d1_sample_count": 5,
        "stock_d1_win_rate": 60.0,
        "stock_d1_average_return_pct": 1.25,
        "stock_gene_combined_win_rate": 45.0,
    }

    rows = build_prefix_rows(manifest, _acceleration_bars())

    features = rows[-1]["features"]
    assert features["prior_seal_success_rate_pct_126"] == 75.0
    assert features["stock_d1_sample_count"] == 5.0
    assert features["stock_gene_combined_win_rate"] == 45.0


def _manifest() -> dict[str, object]:
    return {
        "vt_symbol": "600001.SSE",
        "name": "Alpha",
        "trade_date": "2026-07-01",
        "previous_close": 10.0,
        "limit_price": 11.0,
        "result_date": "2026-07-02",
        "d1_close_price": 11.2,
        "touched_limit": True,
        "sealed_limit": True,
    }


def _acceleration_bars() -> list[dict[str, object]]:
    closes = [10.00, 10.03, 10.08, 10.12, 10.18, 10.25, 10.45, 10.48]
    volumes = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 220.0, 100.0]
    return _bars(closes, volumes)


def _compression_bars() -> list[dict[str, object]]:
    closes = [10.25, 10.26, 10.27, 10.25, 10.28, 10.27, 10.29, 10.38, 10.40]
    volumes = [100.0] * 7 + [220.0, 100.0]
    return _bars(closes, volumes)


def _bars(closes: list[float], volumes: list[float]) -> list[dict[str, object]]:
    slots = official_five_minute_close_times()
    rows = []
    previous = closes[0]
    for slot, close, volume in zip(slots, closes, volumes, strict=False):
        open_price = previous
        spread = 0.03
        rows.append(
            {
                "vt_symbol": "600001.SSE",
                "trade_date": "2026-07-01",
                "bar_time": f"2026-07-01T{slot}:00",
                "interval": "5m",
                "open_price": round(open_price, 4),
                "high_price": round(max(open_price, close) + spread, 4),
                "low_price": round(min(open_price, close) - spread, 4),
                "close_price": close,
                "volume": volume,
                "turnover": volume * close,
            }
        )
        previous = close
    return rows
