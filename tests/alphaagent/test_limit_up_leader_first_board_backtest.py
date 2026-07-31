"""Tests for the leader first-board backtest (v3)."""

from __future__ import annotations

from alphaagent.server.services.limit_up import leader_first_board_backtest as study
from alphaagent.server.services.limit_up.cash_backtest import CashBacktestConfig


def _sample(first_limit_time, trade_date, is_leader=False, vt_symbol="600001.SSE", **factors):
    sample = {
        "first_limit_time": first_limit_time,
        "trade_date": trade_date,
        "is_leader": is_leader,
        "vt_symbol": vt_symbol,
    }
    sample.update(factors)
    return sample


def _calendar_from(start, n):
    from datetime import date, timedelta

    base = date.fromisoformat(start)
    return [(base + timedelta(days=i)).isoformat() for i in range(n)]


def _four_months_strong():
    """4 个独立月份：月1/2/3(06/07/08) 作 train，月4(09) 发信号；momentum 完美区分。

    用 31 天步进确保每月落在不同 YYYY-MM（连续自然日，非交易日）。
    """

    cal = _calendar_from("2025-06-01", 130)
    samples = []
    for m_start in (0, 31, 62):  # 月1=06, 月2=07, 月3=08
        for i in range(8):
            momentum = 100.0 + i if i < 3 else float(i)
            samples.append(
                _sample(
                    "09:30:00", cal[m_start + i], is_leader=(i < 3),
                    vt_symbol=f"train{m_start}{i}", momentum=momentum,
                )
            )
    for i in range(5):  # 月4=09（cal[93]=2025-09-02）
        momentum = 100.0 + i if i < 2 else float(i)
        samples.append(
            _sample(
                "09:30:00", cal[93], is_leader=(i < 2),
                vt_symbol=f"m4{i}", momentum=momentum,
            )
        )
    return cal, samples


# ── Task 1: expanding signal generation ────────────────────────────────


def test_no_signal_before_min_train_months() -> None:
    cal, samples = _four_months_strong()
    signals = study.generate_leader_signals(
        samples, cal, candidate_factors=["momentum"],
        min_train_months=3, max_picks=3, draws=50, seed=42,
    )
    months = sorted({s["trade_date"][:7] for s in signals})
    assert cal[0][:7] not in months  # 月1(06) 无
    assert cal[31][:7] not in months  # 月2(07) 无
    assert cal[62][:7] not in months  # 月3(08) 无
    assert cal[93][:7] in months  # 月4(09) 有（train=06,07,08）


def test_top_picks_per_day_limit() -> None:
    cal, samples = _four_months_strong()
    signals = study.generate_leader_signals(
        samples, cal, candidate_factors=["momentum"],
        min_train_months=3, max_picks=3, draws=50, seed=42,
    )
    day_signals = [s for s in signals if s["trade_date"] == cal[93]]
    assert len(day_signals) == 3  # 5 个候选取 TOP3


def test_expanding_no_future_leak() -> None:
    cal, base = _four_months_strong()
    original = study.generate_leader_signals(
        base, cal, candidate_factors=["momentum"],
        min_train_months=3, max_picks=3, draws=50, seed=42,
    )
    mutated = [dict(s) for s in base]
    for s in mutated:
        if str(s.get("trade_date") or "")[:7] == cal[93][:7]:
            s["is_leader"] = not s["is_leader"]
    rerun = study.generate_leader_signals(
        mutated, cal, candidate_factors=["momentum"],
        min_train_months=3, max_picks=3, draws=50, seed=42,
    )
    orig_m4 = sorted((s["vt_symbol"], s["score"]) for s in original if s["trade_date"] == cal[93])
    rerun_m4 = sorted((s["vt_symbol"], s["score"]) for s in rerun if s["trade_date"] == cal[93])
    assert orig_m4 == rerun_m4  # 当月 is_leader 不进 train，信号不变


# ── Task 2: backtest engine (auction branch + limit-half) ──────────────


def _bar(symbol, trade_date, open_price, close_price, high_price=None, low_price=None):
    return {
        "vt_symbol": symbol,
        "trade_date": trade_date,
        "open_price": open_price,
        "close_price": close_price,
        "high_price": high_price if high_price is not None else close_price,
        "low_price": low_price if low_price is not None else close_price,
    }


def _first_board_bars(symbol, d2_open, d2_close, d2_high=None, d2_low=None):
    """D-1(d0) close=10 → D(d1) 涨停11买入 → D+1(d2) 给定开/收。"""

    return [
        _bar(symbol, "d0", 10.0, 10.0),
        _bar(symbol, "d1", 11.0, 11.0),
        _bar(symbol, "d2", d2_open, d2_close, d2_high, d2_low),
    ]


def test_low_open_sells_all_at_open() -> None:
    bars = _first_board_bars("A", d2_open=10.5, d2_close=10.0, d2_high=10.8, d2_low=9.9)
    signals = [{"vt_symbol": "A", "trade_date": "d1", "score": 0.9}]
    result = study.simulate_leader_first_board_account(signals, bars, ["d0", "d1", "d2"])
    trades = result["closed_trades"]
    assert len(trades) == 1
    assert trades[0]["exit_reason"] == "open_below_prev_close"


def test_high_open_limit_halves_position() -> None:
    # D+1 高开(11.5>11) + 涨停(close=12.1=limit_price(11)) → 减半，剩余末日清仓
    bars = _first_board_bars("A", d2_open=11.5, d2_close=12.1, d2_high=12.1, d2_low=11.3)
    signals = [{"vt_symbol": "A", "trade_date": "d1", "score": 0.9}]
    result = study.simulate_leader_first_board_account(signals, bars, ["d0", "d1", "d2"])
    trades = result["closed_trades"]
    reasons = [t["exit_reason"] for t in trades]
    assert "limit_half" in reasons
    assert "final_close" in reasons
    half = next(t for t in trades if t["exit_reason"] == "limit_half")
    final = next(t for t in trades if t["exit_reason"] == "final_close")
    assert half["volume"] == final["volume"]  # 各卖一半


def test_high_open_not_limit_sells_at_close() -> None:
    # D+1 高开(11.5>11) 但 close=11.8 < limit 12.1 → 不涨停走人（收盘卖）
    bars = _first_board_bars("A", d2_open=11.5, d2_close=11.8, d2_high=11.9, d2_low=11.2)
    signals = [{"vt_symbol": "A", "trade_date": "d1", "score": 0.9, "name": "示例A"}]
    result = study.simulate_leader_first_board_account(signals, bars, ["d0", "d1", "d2"])
    trades = result["closed_trades"]
    assert len(trades) == 1
    assert trades[0]["exit_reason"] == "close_not_limit"
    assert trades[0]["name"] == "示例A"  # 股票名称已记录


def test_max_positions_caps_entries() -> None:
    bars = []
    for sym in "ABCDE":
        bars += _first_board_bars(sym, d2_open=10.5, d2_close=10.0)  # 都低开走人
    signals = [
        {"vt_symbol": sym, "trade_date": "d1", "score": 0.9 - i * 0.1}
        for i, sym in enumerate("ABCDE")
    ]
    result = study.simulate_leader_first_board_account(
        signals, bars, ["d0", "d1", "d2"], config=CashBacktestConfig(max_positions=3)
    )
    assert len(result["closed_trades"]) <= 3  # 最多买 3 只


# ── Task 3: orchestration, report, CLI ─────────────────────────────────


def _event(vt_symbol, trade_date, limit_times, *, first_limit_time="09:30:00", is_sealed=True, seal_amount=1.0e8, turnover=5.0e8, float_market_cap=5.0e9, turnover_rate=5.0, name="X", close_price=11.0, change_pct=10.0, open_times=0):
    return {
        "vt_symbol": vt_symbol, "trade_date": trade_date, "limit_times": limit_times,
        "is_sealed": is_sealed, "first_limit_time": first_limit_time, "open_times": open_times,
        "seal_amount": seal_amount, "turnover": turnover, "float_market_cap": float_market_cap,
        "turnover_rate": turnover_rate, "name": name, "close_price": close_price, "change_pct": change_pct,
    }


def _series_bars(symbol, dates, base=10.0):
    bars = []
    price = base
    for trade_date in dates:
        close = round(price * 1.01, 2)
        bars.append(_bar(symbol, trade_date, open_price=price, close_price=close, high_price=round(close * 1.005, 2), low_price=round(price * 0.995, 2)))
        price = close
    return bars


def test_build_backtest_report_structure() -> None:
    cal = _calendar_from("2025-06-01", 40)
    events = [_event("A", cal[10], 1), _event("A", cal[11], 2)]  # 2 板段（负样本）
    bars = _series_bars("A", cal[0:15])
    report = study.build_backtest_report(
        events, bars, cal, min_consecutive_boards=3, min_train_months=1, draws=50, seed=42
    )
    assert report["execution_valid"] is False
    assert report["study_version"] == study.STUDY_VERSION
    assert "execution_summary" in report
    assert "equity_curve" in report
    assert isinstance(report["closed_trades"], list)
    assert isinstance(report["signal_count"], int)


def test_render_markdown_contains_required_sections() -> None:
    cal = _calendar_from("2025-06-01", 40)
    events = [_event("A", cal[10], 1), _event("A", cal[11], 2)]
    bars = _series_bars("A", cal[0:15])
    report = study.build_backtest_report(
        events, bars, cal, min_consecutive_boards=3, min_train_months=1, draws=50, seed=42
    )
    markdown = study.render_markdown(report)
    assert "## Boundary" in markdown
    assert "## Summary" in markdown
    assert "## Decision" in markdown
