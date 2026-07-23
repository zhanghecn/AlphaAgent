from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from alphaagent.server.services.data_providers import tdx_minute_import
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


def test_static_hazard_pair_audit_preserves_exact_prior_only_rejection() -> None:
    trade_date = date(2026, 7, 21)
    frame = pd.DataFrame(
        [
            {
                "vt_symbol": "605111.SSE",
                "trade_date": trade_date,
                "name": "新洁能",
                "stock_d1_sample_count": 6,
                "stock_d1_win_rate": 66.6667,
                "stock_d1_average_return_pct": -1.5783,
                "stock_gene_combined_win_rate": 29.6296,
                "static_hazard_gate_passed": False,
                "static_hazard_gate_reason": "same_stock_joint_rate_below_30",
            }
        ]
    )

    audited = data._static_hazard_pair_audit(frame)[("605111.SSE", trade_date)]

    assert audited["pool_stage"] == "capture_rejected"
    assert audited["rejection_codes"] == ("same_stock_joint_rate_below_30",)
    assert audited["stock_d1_sample_count"] == 6
    assert audited["stock_d1_average_return_pct"] == -1.5783
    assert audited["stock_gene_combined_win_rate"] == 29.6296


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


def test_decision_minute_backfill_fetches_only_static_scope_gaps(monkeypatch) -> None:
    trade_date = date(2026, 3, 10)
    minute_manifest = pd.DataFrame(
        [
            {"vt_symbol": "600000.SSE", "trade_date": trade_date},
            {"vt_symbol": "600001.SSE", "trade_date": trade_date},
        ]
    )
    scope = data.PreboardDecisionStaticScope(
        manifest=minute_manifest,
        minute_manifest=minute_manifest,
        feature_by_pair={},
        financial_index={},
        feature_coverage={},
        prefilter_audit={},
    )
    before = pd.DataFrame(
        [
            {
                "vt_symbol": "600000.SSE",
                "trade_date": trade_date,
                "coverage_status": "complete",
            },
            {
                "vt_symbol": "600001.SSE",
                "trade_date": trade_date,
                "coverage_status": "missing",
            },
        ]
    )
    after = before.copy()
    after["coverage_status"] = "complete"
    coverage_calls = 0
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        data,
        "load_preboard_decision_static_scope",
        lambda **_kwargs: (
            scope,
            {"status": "ready", "static_scope_pair_count": 2},
        ),
    )

    def load_coverage(_manifest):
        nonlocal coverage_calls
        coverage_calls += 1
        return before if coverage_calls == 1 else after

    def fetch(**kwargs):
        captured.update(kwargs)
        return {"status": "ready", "rows_read": 240, "rows_written": 240}

    monkeypatch.setattr(data, "load_one_minute_coverage", load_coverage)
    monkeypatch.setattr(tdx_minute_import, "import_tdx_minute_bars_for_gaps", fetch)

    result = data.backfill_preboard_decision_minutes(
        session_count=81,
        end_date=trade_date,
        max_gaps=10,
    )

    assert captured["gaps"] == [
        {"vt_symbol": "600001.SSE", "trade_date": trade_date}
    ]
    assert result["status"] == "ready"
    assert result["requested_gap_count"] == 1
    assert result["covered_gap_count"] == 1
    assert result["remaining_missing_pair_count"] == 0


def test_decision_pairs_require_a_point_in_time_quality_pass() -> None:
    rows = [
        {
            "vt_symbol": "000001.SZSE",
            "signal_date": "2026-07-16",
            "quality_gate_passed": True,
        },
        {
            "vt_symbol": "600000.SSE",
            "signal_date": date(2026, 7, 15),
            "quality_gate_passed": True,
        },
        {
            "vt_symbol": "600001.SSE",
            "signal_date": date(2026, 7, 15),
            "quality_gate_passed": False,
        },
    ]

    assert data.decision_pairs_from_prefix_rows(rows) == [
        ("600000.SSE", date(2026, 7, 15)),
        ("000001.SZSE", date(2026, 7, 16)),
    ]


def test_decision_scope_ignores_later_touch_seal_and_d1_fields(monkeypatch) -> None:
    trade_date = date(2026, 7, 16)
    pair = ("600000.SSE", trade_date)
    base_manifest = {
        "vt_symbol": pair[0],
        "name": "测试股份",
        "trade_date": trade_date,
        "previous_close": 10.0,
        "limit_price": 11.0,
        "eligible_main_board": True,
        "prior_day_limit_up": False,
        "stock_d1_sample_count": 8,
        "stock_gene_combined_win_rate": 45.0,
    }
    feature_by_pair = {
        pair: {
            "financial_snapshot": {"net_profit_yoy": 20.0},
            "financial_risk": {"blocked": False},
        }
    }
    minute_rows = pd.DataFrame(
        [
            {
                "vt_symbol": pair[0],
                "trade_date": trade_date,
                "bar_time": datetime(2026, 7, 16, 10, 0),
                "open_price": 10.2,
                "high_price": 10.5,
                "low_price": 10.1,
                "close_price": 10.4,
                "volume": 100.0,
                "turnover": 1_000.0,
            }
        ]
    )
    observed_candidates: list[dict[str, object]] = []

    def evaluate(candidate, *, decision_at, market_gate, execution_checks):
        observed_candidates.append(dict(candidate))
        return {
            **candidate,
            "quality_gate_passed": True,
            "lane_decision": "eligible",
            "lane_blockers": (),
            "profitability_gate_passed": True,
            "profitability_gate_reason": "qualified",
        }

    monkeypatch.setattr(data, "evaluate_first_board_quality_at_time", evaluate)

    def build_rows(**outcomes):
        manifest = pd.DataFrame([{**base_manifest, **outcomes}])
        return data._build_decision_scope_prefix_rows(
            manifest,
            minute_rows,
            {pair},
            feature_by_pair,
            {},
        )

    first = build_rows(
        touched_limit=True,
        sealed_limit=True,
        d1_close_price=12.0,
    )
    observed_candidates.clear()
    changed = build_rows(
        touched_limit=False,
        sealed_limit=False,
        d1_close_price=8.0,
    )

    assert first == changed
    assert observed_candidates
    assert all(
        key not in observed_candidates[0]
        for key in ("touched_limit", "sealed_limit", "d1_close_price")
    )


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
            "lane_blockers": [] if marker == "keep" else ["static_block"],
        }

    monkeypatch.setattr(
        data,
        "_evaluate_decision_scope_upper_bound",
        upper_bound,
    )

    selected, audit = data._prefilter_decision_scope_manifest(
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


def test_decision_pair_manifest_has_an_independent_contract() -> None:
    audit = {
        "status": "ready",
        "start_date": "2026-07-14",
        "end_date": "2026-07-16",
        "manifest_pair_count": 3,
        "complete_minute_pair_count": 3,
        "filter_audit": {
            "static_model_prefix_count": 21,
            "static_prefilter": {"static_upper_bound_pair_count": 3},
        },
        "feature_coverage": {"feature_computed_rows": 100},
    }
    pairs = [
        ("600000.SSE", date(2026, 7, 16)),
        ("000001.SZSE", date(2026, 7, 14)),
    ]

    manifest = data.build_preboard_decision_pair_manifest(
        pairs,
        audit,
        session_count=89,
    )

    assert manifest["manifest_version"] == data.DECISION_PAIR_MANIFEST_VERSION
    assert manifest["strategy_filter_version"] == data.PREBOARD_DECISION_VERSION
    assert manifest["shared_pair_count"] == 2
    assert manifest["shared_prefix_count"] == 21


def test_load_decision_pairs_uses_point_in_time_quality_field(monkeypatch) -> None:
    trade_date = date(2026, 7, 16)
    manifest = pd.DataFrame(
        [
            {
                "vt_symbol": "600000.SSE",
                "trade_date": trade_date,
            }
        ]
    )
    coverage = pd.DataFrame(
        [
            {
                "vt_symbol": "600000.SSE",
                "trade_date": trade_date,
                "coverage_status": "complete",
            }
        ]
    )
    minute_rows = pd.DataFrame(
        [
            {
                "vt_symbol": "600000.SSE",
                "trade_date": trade_date,
                "bar_time": datetime(2026, 7, 16, 10, 0),
            }
        ]
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(data, "load_static_hazard_manifest", lambda **kwargs: manifest)
    monkeypatch.setattr(data, "load_one_minute_coverage", lambda _manifest: coverage)
    monkeypatch.setattr(
        data,
        "_load_decision_scope_feature_frame",
        lambda *_args, **_kwargs: (pd.DataFrame(), {"feature_computed_rows": 1}),
    )
    monkeypatch.setattr(
        data,
        "_decision_scope_feature_index",
        lambda *_args, **_kwargs: {("600000.SSE", trade_date): {"ready": True}},
    )
    monkeypatch.setattr(data, "_load_decision_scope_financial_index", lambda: {})
    monkeypatch.setattr(
        data,
        "_prefilter_decision_scope_manifest",
        lambda *args, **kwargs: (
            manifest,
            {"static_upper_bound_pair_count": 1},
        ),
    )
    monkeypatch.setattr(data, "load_one_minute_bars", lambda _manifest: minute_rows)

    def build_prefixes(*args):
        captured["argument_count"] = len(args)
        return (
            [
                {
                    "vt_symbol": "600000.SSE",
                    "signal_date": trade_date.isoformat(),
                    "quality_gate_passed": True,
                }
            ],
            {"static_model_pair_count": 1, "static_model_prefix_count": 1},
        )

    monkeypatch.setattr(data, "_build_decision_scope_prefix_rows", build_prefixes)

    pairs, audit = data.load_preboard_decision_pairs(session_count=89)

    assert pairs == [("600000.SSE", trade_date)]
    assert captured["argument_count"] == 5
    assert audit["decision_pair_count"] == 1


def test_load_decision_pairs_blocks_instead_of_dropping_static_minute_gaps(
    monkeypatch,
) -> None:
    trade_date = date(2026, 3, 10)
    manifest = pd.DataFrame(
        [
            {"vt_symbol": "600000.SSE", "trade_date": trade_date},
            {"vt_symbol": "600001.SSE", "trade_date": trade_date},
        ]
    )
    coverage = pd.DataFrame(
        [
            {
                "vt_symbol": "600000.SSE",
                "trade_date": trade_date,
                "coverage_status": "complete",
            },
            {
                "vt_symbol": "600001.SSE",
                "trade_date": trade_date,
                "coverage_status": "missing",
            },
        ]
    )
    feature_index = {
        ("600000.SSE", trade_date): {"ready": True},
        ("600001.SSE", trade_date): {"ready": True},
    }
    monkeypatch.setattr(data, "load_static_hazard_manifest", lambda **_kwargs: manifest)
    monkeypatch.setattr(data, "load_one_minute_coverage", lambda _manifest: coverage)
    monkeypatch.setattr(
        data,
        "_load_decision_scope_feature_frame",
        lambda *_args, **_kwargs: (pd.DataFrame(), {"feature_computed_rows": 2}),
    )
    monkeypatch.setattr(
        data,
        "_decision_scope_feature_index",
        lambda *_args, **_kwargs: feature_index,
    )
    monkeypatch.setattr(data, "_load_decision_scope_financial_index", lambda: {})
    monkeypatch.setattr(
        data,
        "_prefilter_decision_scope_manifest",
        lambda *args, **kwargs: (
            manifest,
            {"static_upper_bound_pair_count": 2},
        ),
    )
    monkeypatch.setattr(
        data,
        "load_one_minute_bars",
        lambda _manifest: (_ for _ in ()).throw(
            AssertionError("minute rows loaded before coverage passed")
        ),
    )

    pairs, audit = data.load_preboard_decision_pairs(
        session_count=81,
        end_date=trade_date,
    )

    assert pairs == []
    assert audit["status"] == "blocked_by_one_minute_coverage"
    assert audit["static_scope_pair_count"] == 2
    assert audit["complete_minute_pair_count"] == 1
    assert audit["missing_minute_pair_count"] == 1


def test_resolve_decision_pairs_reads_only_the_independent_manifest(monkeypatch) -> None:
    trade_date = date(2026, 7, 16)
    captured: dict[str, object] = {}

    def load_manifest(*, manifest_version, session_count):
        captured.update(
            manifest_version=manifest_version,
            session_count=session_count,
        )
        return {
            "manifest_version": data.DECISION_PAIR_MANIFEST_VERSION,
            "session_count": 89,
            "start_date": trade_date,
            "end_date": trade_date,
            "status": "ready",
            "strategy_filter_version": data.PREBOARD_DECISION_VERSION,
            "feature_version": data.TRANSACTION_FEATURE_VERSION,
            "input_fingerprint": "sha256:" + "a" * 64,
            "manifest_pair_count": 1,
            "complete_minute_pair_count": 1,
            "shared_pair_count": 1,
            "pairs": [
                {"vt_symbol": "600000.SSE", "trade_date": trade_date.isoformat()}
            ],
            "filter_audit": {"static_model_prefix_count": 3},
            "feature_coverage": {},
        }

    monkeypatch.setattr(
        data.repository,
        "load_latest_transaction_pair_manifest",
        load_manifest,
    )
    monkeypatch.setattr(
        data,
        "load_preboard_decision_pairs",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("rebuilt scope")),
    )

    pairs, audit = data.resolve_preboard_decision_pairs(
        session_count=89,
        freeze_manifest=True,
    )

    assert captured == {
        "manifest_version": data.DECISION_PAIR_MANIFEST_VERSION,
        "session_count": 89,
    }
    assert pairs == [("600000.SSE", trade_date)]
    assert audit["decision_pair_count"] == 1
    assert audit["pair_manifest"]["status"] == "already_frozen"


def test_decision_scope_is_keyed_by_session_count_and_end_date(monkeypatch) -> None:
    requested_end = date(2026, 3, 10)
    captured: dict[str, object] = {}

    def load_manifest(*, manifest_version, session_count, end_date):
        captured.update(
            manifest_version=manifest_version,
            session_count=session_count,
            cached_end_date=end_date,
        )
        return None

    def load_pairs(*, session_count, end_date):
        captured.update(
            loaded_session_count=session_count,
            loaded_end_date=end_date,
        )
        return [("600000.SSE", requested_end)], {
            "status": "ready",
            "start_date": "2025-11-06",
            "end_date": requested_end.isoformat(),
            "manifest_pair_count": 1,
            "complete_minute_pair_count": 1,
            "decision_pair_count": 1,
            "filter_audit": {"static_model_prefix_count": 3},
            "feature_coverage": {},
        }

    monkeypatch.setattr(
        data.repository,
        "load_latest_transaction_pair_manifest",
        load_manifest,
    )
    monkeypatch.setattr(data, "load_preboard_decision_pairs", load_pairs)

    pairs, audit = data.resolve_preboard_decision_pairs(
        session_count=81,
        end_date=requested_end,
        freeze_manifest=False,
    )

    assert pairs == [("600000.SSE", requested_end)]
    assert audit["end_date"] == requested_end.isoformat()
    assert captured == {
        "manifest_version": data.DECISION_PAIR_MANIFEST_VERSION,
        "session_count": 81,
        "cached_end_date": requested_end,
        "loaded_session_count": 81,
        "loaded_end_date": requested_end,
    }


def test_backfill_decision_uses_the_independent_pair_scope(monkeypatch) -> None:
    pairs = _pairs()
    captured: dict[str, object] = {}

    def resolve(*, session_count, freeze_manifest):
        captured.update(
            session_count=session_count,
            freeze_manifest=freeze_manifest,
        )
        return pairs, {"status": "ready", "decision_pair_count": len(pairs)}

    def sync(received, *, max_pairs, dry_run):
        assert received == pairs
        captured.update(max_pairs=max_pairs, dry_run=dry_run)
        return {"status": "partial", "ready_pair_count": 2}

    monkeypatch.setattr(data, "resolve_preboard_decision_pairs", resolve)
    monkeypatch.setattr(data, "sync_transaction_feature_pairs", sync)

    result = data.backfill_preboard_decision_transaction_features(
        session_count=89,
        max_pairs=2,
        dry_run=True,
    )

    assert captured == {
        "session_count": 89,
        "freeze_manifest": False,
        "max_pairs": 2,
        "dry_run": True,
    }
    assert result["scope"] == "limit_up_preboard_decision_transaction_flow"
    assert result["pair_audit"]["decision_pair_count"] == 3
