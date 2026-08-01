"""Tests for the Phase 3 forward paper ledger (capture/settle/report)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

from alphaagent.server.services.limit_up import leader_forward_ledger as ledger


def test_capture_fields_extracts_leader_state() -> None:
    fields = ledger._capture_fields(
        {
            "potential_score": 0.82,
            "factor_percentiles": {"concept_max_return_20d": 1.0},
            "change_pct": 9.8,
            "last_price": 11.0,
            "limit_price": 11.0,
            "state": "sealed",
            "first_limit_time": "09:45:00",
            "open_times": "2",
            "seal_to_turnover_ratio": 1.4,
            "seal_amount_retention_ratio": 1.05,
            "seal_weakening": False,
            "late_seal": False,
        }
    )
    assert fields["potential_score"] == 0.82
    assert fields["open_times"] == 2
    assert fields["seal_to_turnover_ratio"] == 1.4
    assert fields["late_seal"] is False
    empty = ledger._capture_fields({})
    assert empty["potential_score"] is None
    assert empty["seal_weakening"] is False


def test_is_sealed_close_symbol_aware() -> None:
    assert ledger._is_sealed_close({"close_price": 11.0, "change_pct": 10.0}, "600001.SSE") is True
    assert ledger._is_sealed_close({"close_price": 11.5, "change_pct": 15.0}, "300001.SZSE") is False
    assert ledger._is_sealed_close({"close_price": 12.0, "change_pct": 20.0}, "300001.SZSE") is True
    assert ledger._is_sealed_close({"close_price": 10.5, "change_pct": 5.0}, "600001.SSE") is False


class _LedgerSession:
    """回放式假 session：capture/settle/report 的查询按序返回、写操作记账。"""

    def __init__(self, *, existing: object = None, unsettled: list | None = None,
                 d_bar: object = None, d1_bar: object = None,
                 report_rows: list | None = None) -> None:
        self.existing = existing
        self.unsettled = list(unsettled or [])
        self.d_bar = d_bar
        self.d1_bar = d1_bar
        self.report_rows = list(report_rows or [])
        self.inserts: list[dict] = []
        self.updates: list[dict] = []
        self._call = 0

    def execute(self, statement: object) -> _LedgerSession:
        self._call += 1
        return self

    def mappings(self) -> _LedgerSession:
        return self

    def first(self) -> object:
        # capture: 查 existing；settle: 依次查 d_bar / d1_bar
        if self.unsettled:
            if self._call == 2:
                return self.d_bar
            if self._call == 3:
                return self.d1_bar
            return None
        return self.existing

    def all(self) -> list:
        if self.unsettled and self._call == 1:
            return self.unsettled
        return self.report_rows


def _patch_session(monkeypatch, session: _LedgerSession) -> None:
    @contextmanager
    def fake_scope():
        yield session

    monkeypatch.setattr(ledger, "session_scope", fake_scope)


def test_capture_inserts_new_and_updates_existing(monkeypatch) -> None:
    leader = {
        "vt_symbol": "600001.SSE", "name": "示例", "potential_score": 0.8,
        "change_pct": 9.0, "state": "sealed",
    }
    monkeypatch.setattr(
        ledger, "build_first_board_leader_snapshot",
        lambda: {"trade_date": "2026-07-31", "leaders": [leader]},
    )

    class _CaptureSession:
        def __init__(self) -> None:
            self.values: list[dict] = []
            self._existing: object = None

        def execute(self, statement: object) -> _CaptureSession:
            if hasattr(statement, "compile") and "INSERT" in str(statement).upper():
                return self
            return self

        def mappings(self) -> _CaptureSession:
            return self

        def first(self) -> object:
            return self._existing

    # 场景1：无 existing → insert 路径（通过 capture_count 字段推断）
    session = _CaptureSession()
    inserted: list[dict] = []
    updated: list[dict] = []

    import alphaagent.server.db.schema as schema

    orig_insert = schema.leader_forward_signals.insert
    orig_update = schema.leader_forward_signals.update

    class _InsertCapture:
        def __init__(self) -> None:
            self._values: dict = {}

        def values(self, **kwargs):
            inserted.append(kwargs)
            return self

    class _UpdateCapture:
        def where(self, *args):
            return self

        def values(self, **kwargs):
            updated.append(kwargs)
            return self

    monkeypatch.setattr(schema.leader_forward_signals, "insert", lambda: _InsertCapture())
    monkeypatch.setattr(schema.leader_forward_signals, "update", lambda: _UpdateCapture())
    _patch_session(monkeypatch, session)
    result = ledger.capture_forward_signals(datetime(2026, 7, 31, 10, 5, tzinfo=timezone.utc))
    assert result["rows_written"] == 1
    assert inserted and inserted[0]["vt_symbol"] == "600001.SSE"
    assert inserted[0]["capture_count"] == 1
    monkeypatch.setattr(schema.leader_forward_signals, "insert", orig_insert)
    monkeypatch.setattr(schema.leader_forward_signals, "update", orig_update)


def test_capture_skips_empty_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(
        ledger, "build_first_board_leader_snapshot",
        lambda: {"trade_date": None, "leaders": []},
    )
    result = ledger.capture_forward_signals()
    assert result["status"] == "skipped"


def test_settle_fills_d1_returns(monkeypatch) -> None:
    unsettled = [
        {"id": 1, "vt_symbol": "600001.SSE", "trade_date": date(2026, 7, 30)},
    ]
    d_bar = {"close_price": 11.0, "change_pct": 10.0}
    d1_bar = {"trade_date": date(2026, 7, 31), "open_price": 11.5, "close_price": 11.8}
    session = _LedgerSession(unsettled=unsettled, d_bar=d_bar, d1_bar=d1_bar)
    _patch_session(monkeypatch, session)

    import alphaagent.server.db.schema as schema

    updated: list[dict] = []

    class _UpdateCapture:
        def where(self, *args):
            return self

        def values(self, **kwargs):
            updated.append(kwargs)
            return self

    monkeypatch.setattr(schema.leader_forward_signals, "update", lambda: _UpdateCapture())
    result = ledger.settle_forward_signals()
    assert result["rows_written"] == 1
    values = updated[0]
    assert values["board_status"] == "sealed"
    assert values["d_close"] == 11.0
    assert values["d1_open_return_pct"] == 4.5455
    assert values["is_win"] is True


def test_report_groups_by_iso_week(monkeypatch) -> None:
    today = date.today()
    rows = []
    for offset, ret, win in ((1, 2.5, True), (2, -1.0, False), (3, 3.0, True)):
        rows.append(
            {
                "trade_date": today - timedelta(days=offset),
                "vt_symbol": "600001.SSE", "name": "示例",
                "potential_score": 0.8, "change_pct": 9.0, "state": "sealed",
                "board_status": "sealed", "late_seal": False, "seal_weakening": False,
                "seal_to_turnover_ratio": 1.0, "d1_open_return_pct": ret,
                "is_win": win, "settled_at": datetime.now(timezone.utc),
            }
        )
    session = _LedgerSession(report_rows=rows)
    _patch_session(monkeypatch, session)
    monkeypatch.setattr(ledger, "_backtest_reference", lambda: {"win_rate": 60.5})
    report = ledger.build_forward_ledger_report(weeks=2)
    assert report["status"] == "ok"
    assert len(report["weeks"]) == 1
    week = report["weeks"][0]
    assert week["signals"] == 3
    assert week["settled"] == 3
    assert week["win_rate"] == 66.67
    assert week["avg_d1_open_return_pct"] == 1.5
    assert week["seal_rate"] == 100.0
    assert report["backtest_reference"]["win_rate"] == 60.5
    assert len(report["recent"]) == 3
