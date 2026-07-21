from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from alphaagent.server.services.limit_up import preboard_transaction_data as data


def _pairs() -> list[tuple[str, date]]:
    return [
        ("000001.SZSE", date(2026, 7, 14)),
        ("000002.SZSE", date(2026, 7, 15)),
        ("600000.SSE", date(2026, 7, 16)),
    ]


def _coverage(pairs, ready_count: int) -> dict[str, object]:
    pending = pairs[ready_count:]
    return {
        "requested_pair_count": len(pairs),
        "ready_pair_count": ready_count,
        "ready_pair_pct": round(ready_count / len(pairs) * 100, 4),
        "missing_pair_count": len(pending),
        "status_counts": {"flow_ready": ready_count, "missing": len(pending)},
        "missing_pairs": [
            {"vt_symbol": symbol, "trade_date": day.isoformat()}
            for symbol, day in pending
        ],
        "pending_pairs": [
            {"vt_symbol": symbol, "trade_date": day.isoformat()}
            for symbol, day in pending
        ],
    }


def test_sync_transaction_feature_pairs_is_bounded_and_saves_each_pair(monkeypatch) -> None:
    pairs = _pairs()
    coverage_calls = 0
    requested: list[tuple[str, date]] = []
    saved: list[tuple[dict[str, object], list[dict[str, object]]]] = []

    def load_coverage(received, *, feature_version):
        nonlocal coverage_calls
        assert received == pairs
        assert feature_version == data.TRANSACTION_FEATURE_VERSION
        coverage_calls += 1
        return _coverage(pairs, 0 if coverage_calls == 1 else 2)

    def load_daily(received):
        return {
            pair: {
                "volume": 300.0,
                "high_price": 10.5,
                "low_price": 10.0,
                "close_price": 10.5,
            }
            for pair in received
        }

    def fetch(received, **_kwargs):
        requested.extend(received)
        for symbol, day in received:
            yield {"vt_symbol": symbol, "trade_date": day.isoformat(), "rows": []}

    def capture(symbol, day, fetched, daily):
        fingerprint = "sha256:" + symbol[0] * 64
        scope = {
            "feature_version": data.TRANSACTION_FEATURE_VERSION,
            "vt_symbol": symbol,
            "trade_date": day,
            "status": "flow_ready",
            "source": "tdx.history_transaction",
            "input_fingerprint": fingerprint,
            "feature_row_count": 1,
        }
        rows = [
            {
                "feature_version": data.TRANSACTION_FEATURE_VERSION,
                "vt_symbol": symbol,
                "trade_date": day,
                "bar_time": datetime.combine(day, datetime.strptime("10:00", "%H:%M").time()),
                "input_fingerprint": fingerprint,
                "source": "tdx.history_transaction",
                "values": {"tx_path_efficiency_1m": 0.5},
            }
        ]
        return scope, rows

    def save(scope, rows):
        saved.append((scope, rows))
        return {
            "status": "frozen",
            "rows_written": len(rows),
            "scope_written": 1,
            "input_fingerprint": scope["input_fingerprint"],
        }

    monkeypatch.setattr(data.repository, "load_transaction_feature_coverage", load_coverage)
    monkeypatch.setattr(data, "load_transaction_daily_bars", load_daily)
    monkeypatch.setattr(data, "iter_history_transactions", fetch)
    monkeypatch.setattr(data, "build_transaction_feature_capture", capture)
    monkeypatch.setattr(data.repository, "save_transaction_feature_capture", save)

    result = data.sync_transaction_feature_pairs(pairs, max_pairs=2)

    assert requested == pairs[:2]
    assert len(saved) == 2
    assert result["requested_gap_count"] == 2
    assert result["rows_written"] == 2
    assert result["remaining_pending_pair_count"] == 1
    assert result["status"] == "partial"


def test_sync_transaction_feature_pairs_dry_run_does_not_fetch(monkeypatch) -> None:
    pairs = _pairs()
    monkeypatch.setattr(
        data.repository,
        "load_transaction_feature_coverage",
        lambda received, *, feature_version: _coverage(pairs, 0),
    )
    monkeypatch.setattr(
        data,
        "iter_history_transactions",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("fetched")),
    )

    result = data.sync_transaction_feature_pairs(pairs, max_pairs=2, dry_run=True)

    assert result["status"] == "dry_run"
    assert result["requested_gap_count"] == 2
    assert result["rows_written"] == 0


def test_shared_pairs_are_extracted_from_passed_prefixes_only() -> None:
    rows = [
        {
            "vt_symbol": "000001.SZSE",
            "signal_date": "2026-07-16",
            "shared_strategy_passed": True,
        },
        {
            "vt_symbol": "000001.SZSE",
            "signal_date": "2026-07-16",
            "shared_strategy_passed": True,
        },
        {
            "vt_symbol": "600000.SSE",
            "signal_date": date(2026, 7, 15),
            "shared_strategy_passed": False,
        },
    ]

    assert data.shared_pairs_from_prefix_rows(rows) == [
        ("000001.SZSE", date(2026, 7, 16))
    ]


def test_static_prefilter_only_drops_pairs_proven_unreachable(monkeypatch) -> None:
    manifest = pd.DataFrame(
        [
            {"vt_symbol": "000001.SZSE", "trade_date": date(2026, 7, 15)},
            {"vt_symbol": "000002.SZSE", "trade_date": date(2026, 7, 16)},
            {"vt_symbol": "600000.SSE", "trade_date": date(2026, 7, 16)},
        ]
    )
    complete = {
        ("000001.SZSE", date(2026, 7, 15)),
        ("000002.SZSE", date(2026, 7, 16)),
    }
    feature_by_pair = {
        ("000001.SZSE", date(2026, 7, 15)): {"marker": "keep"},
        ("000002.SZSE", date(2026, 7, 16)): {"marker": "drop"},
    }

    def upper_bound(manifest_row, feature_row, *, financial_index):
        assert financial_index == {"financial": "index"}
        marker = feature_row["marker"]
        return {
            "static_upper_bound_passed": marker == "keep",
            "profitability_gate_reason": "qualified",
            "shared_lane_blockers": [] if marker == "keep" else ["static_block"],
        }

    monkeypatch.setattr(
        data,
        "evaluate_static_shared_strategy_upper_bound",
        upper_bound,
    )

    selected, audit = data.prefilter_shared_transaction_manifest(
        manifest,
        complete,
        feature_by_pair,
        {"financial": "index"},
    )

    assert selected[["vt_symbol", "trade_date"]].to_dict(orient="records") == [
        {"vt_symbol": "000001.SZSE", "trade_date": date(2026, 7, 15)}
    ]
    assert audit == {
        "input_pair_count": 3,
        "complete_pair_count": 2,
        "missing_feature_pair_count": 0,
        "static_upper_bound_pair_count": 1,
        "static_rejection_counts": {"static_block": 1},
        "incomplete_pair_count": 1,
    }


def test_pair_manifest_fingerprint_is_stable_and_pair_sensitive() -> None:
    audit = {
        "status": "ready",
        "start_date": "2026-07-14",
        "end_date": "2026-07-16",
        "manifest_pair_count": 3,
        "complete_minute_pair_count": 3,
        "shared_pair_count": 2,
        "filter_audit": {
            "shared_prefix_count": 12,
            "static_prefilter": {"static_upper_bound_pair_count": 3},
        },
        "feature_coverage": {"feature_computed_rows": 100},
    }
    pairs = [
        ("600000.SSE", date(2026, 7, 16)),
        ("000001.SZSE", date(2026, 7, 14)),
    ]

    first = data.build_shared_transaction_pair_manifest(
        pairs,
        audit,
        session_count=89,
    )
    reordered = data.build_shared_transaction_pair_manifest(
        list(reversed(pairs)),
        audit,
        session_count=89,
    )
    changed = data.build_shared_transaction_pair_manifest(
        [("000001.SZSE", date(2026, 7, 14))],
        {**audit, "shared_pair_count": 1},
        session_count=89,
    )

    assert first == reordered
    assert first["start_date"] == date(2026, 7, 14)
    assert first["end_date"] == date(2026, 7, 16)
    assert first["shared_pair_count"] == 2
    assert first["shared_prefix_count"] == 12
    assert first["input_fingerprint"].startswith("sha256:")
    assert first["input_fingerprint"] != changed["input_fingerprint"]
