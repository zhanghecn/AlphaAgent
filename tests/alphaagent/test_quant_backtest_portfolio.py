from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta

from fastapi.testclient import TestClient

from alphaagent.server.main import create_app
from alphaagent.server.db import schema
from alphaagent.server.services.quant.factors import Bar, SignalScore, score_stock


def _bars(days: int = 80) -> list[Bar]:
    start = date(2025, 1, 1)
    result: list[Bar] = []
    price = 10.0
    for index in range(days):
        if index < 60:
            price *= 1.004
        else:
            price *= 1.0
        result.append(
            Bar(
                trade_date=start + timedelta(days=index),
                open_price=price * 0.99,
                high_price=price * 1.02,
                low_price=price * 0.98,
                close_price=price,
                volume=1_000_000 if index < 60 else 600_000,
                turnover=120_000_000,
                change_pct=0.2,
            )
        )
    return result


def test_mainline_pullback_score_generates_entry_candidate() -> None:
    bars = _bars()

    score = score_stock(
        "600000.SSE",
        bars,
        bars[-1].trade_date,
        index_return_20d=-6.0,
        sector_score=78.0,
        financial_score=66.0,
    )

    assert score.evidence["status"] == "ready"
    assert score.total_score > 0
    assert score.relative_strength_score > 50
    assert "daily_close_signal_next_open_execution" == score.evidence["entry_rule"]


def test_mainline_pullback_score_uses_smart_money_proxy_inputs() -> None:
    bars = _bars()

    neutral = score_stock("600000.SSE", bars, bars[-1].trade_date)
    boosted = score_stock(
        "600000.SSE",
        bars,
        bars[-1].trade_date,
        fund_flow_score=90,
        hot_rank_score=80,
        lhb_score=70,
    )

    assert boosted.total_score > neutral.total_score
    assert boosted.evidence["smart_money_proxy_score"] == 83.0
    assert "not proof of main-force intent" in boosted.evidence["smart_money_note"]


def test_mainline_pullback_liquidity_estimates_a_share_volume_lots() -> None:
    bars = _bars()
    bars = [
        Bar(
            trade_date=bar.trade_date,
            open_price=bar.open_price,
            high_price=bar.high_price,
            low_price=bar.low_price,
            close_price=100.0,
            volume=1_000_000,
            turnover=None,
            change_pct=bar.change_pct,
        )
        for bar in bars
    ]

    score = score_stock("600000.SSE", bars, bars[-1].trade_date)

    assert score.evidence["turnover_estimated_from_volume"] is True
    assert score.evidence["turnover20"] == 10_000_000_000
    assert score.liquidity_score == 100.0


def test_quant_smart_money_loaders_score_observable_tables() -> None:
    from alphaagent.server.services.quant import screening

    trade_date = date(2026, 1, 20)

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def mappings(self):
            return self

        def all(self):
            return self._rows

    class FakeSession:
        def __init__(self, rows):
            self.rows = rows

        def execute(self, statement):
            del statement
            return FakeResult(self.rows)

    fund_scores = screening._load_fund_flow_scores(
        FakeSession(
            [
                {
                    "vt_symbol": "600000.SSE",
                    "trade_date": "2026-01-20",
                    "main_net_inflow": 80_000_000,
                    "main_net_inflow_ratio": 6.0,
                    "super_large_net_inflow": 40_000_000,
                    "large_net_inflow": 30_000_000,
                }
            ]
        ),
        ["600000.SSE"],
        trade_date,
    )
    hot_scores = screening._load_hot_rank_scores(
        FakeSession([{"vt_symbol": "600000.SSE", "rank_time": "2026-01-20T10:00:00", "rank": 5, "rank_change": -2}]),
        ["600000.SSE"],
        trade_date,
    )
    lhb_scores = screening._load_lhb_scores(
        FakeSession(
            [
                {
                    "vt_symbol": "600000.SSE",
                    "trade_date": "2026-01-19",
                    "net_amount": 60_000_000,
                    "buy_amount": 120_000_000,
                    "sell_amount": 60_000_000,
                }
            ]
        ),
        ["600000.SSE"],
        trade_date,
    )

    assert fund_scores["600000.SSE"] > 70
    assert hot_scores["600000.SSE"] > 90
    assert lhb_scores["600000.SSE"] > 70


def test_stock_fund_flow_upsert_skips_unknown_symbols(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    inserted: list[dict[str, object]] = []

    class FakeScalarResult:
        def scalars(self):
            return self

        def all(self):
            return ["600000.SSE"]

    class FakeSelectResult:
        def first(self):
            return None

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if text.startswith("SELECT stocks.vt_symbol"):
                return FakeScalarResult()
            if text.startswith("INSERT INTO stock_fund_flows"):
                inserted.append(dict(statement.compile().params))
                return None
            return FakeSelectResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(data_sync, "session_scope", fake_session_scope)

    written = data_sync._upsert_stock_fund_flow_items(
        [
            {"vt_symbol": "600000.SSE", "main_net_inflow": 100_000_000, "main_net_inflow_pct": 6.0},
            {"vt_symbol": "000032.SZSE", "main_net_inflow": 200_000_000, "main_net_inflow_pct": 8.0},
        ],
        "即时",
    )

    assert written == 1
    assert inserted[0]["vt_symbol"] == "600000.SSE"


def test_stock_hot_rank_upsert_skips_unknown_symbols(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    inserted: list[dict[str, object]] = []

    class FakeScalarResult:
        def scalars(self):
            return self

        def all(self):
            return ["600000.SSE"]

    class FakeSelectResult:
        def first(self):
            return None

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if text.startswith("SELECT stocks.vt_symbol"):
                return FakeScalarResult()
            if text.startswith("INSERT INTO stock_hot_ranks"):
                inserted.append(dict(statement.compile().params))
                return None
            return FakeSelectResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(data_sync, "session_scope", fake_session_scope)

    written = data_sync._upsert_stock_hot_ranks(
        [
            {"vt_symbol": "600000.SSE", "rank": 1},
            {"vt_symbol": "300666.SZSE", "rank": 2},
        ]
    )

    assert written == 1
    assert inserted[0]["vt_symbol"] == "600000.SSE"


def test_stock_minute_bar_upsert_parses_intraday_time(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    inserted: list[dict[str, object]] = []

    class FakeScalarResult:
        def scalar(self):
            return "600000.SSE"

    class FakeSelectResult:
        def first(self):
            return None

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if text.startswith("SELECT stocks.vt_symbol"):
                return FakeScalarResult()
            if text.startswith("INSERT INTO stock_minute_bars"):
                inserted.append(dict(statement.compile().params))
                return None
            return FakeSelectResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(data_sync, "session_scope", fake_session_scope)

    written = data_sync._upsert_minute_bars(
        "600000",
        "SSE",
        [
            {
                "trade_date": "2026-06-11 14:56:00",
                "open": 10.0,
                "high": 10.2,
                "low": 9.99,
                "close": 10.05,
                "volume": 1200,
            }
        ],
        "1m",
        "test",
    )

    assert written == 1
    assert inserted[0]["vt_symbol"] == "600000.SSE"
    assert inserted[0]["trade_date"].isoformat() == "2026-06-11"
    assert inserted[0]["bar_time"].strftime("%H:%M:%S") == "14:56:00"


def test_stock_minute_sync_job_is_registered() -> None:
    from alphaagent.server.services import data_sync

    job_ids = {job.id for job in data_sync.DEFAULT_JOBS}

    assert "sync_stock_minute_bars" in job_ids
    assert data_sync.JOB_RUNNERS["sync_stock_minute_bars"] == "_run_sync_stock_minute_bars"


def test_stock_minute_sync_accepts_symbols_and_date_range(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    seen_calls: list[dict[str, object]] = []
    written: list[tuple[str, str, str]] = []

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"symbol": "600000", "exchange": "SSE", "vt_symbol": "600000.SSE"}]

    class FakeSession:
        def execute(self, statement):
            assert "stocks.vt_symbol IN" in str(statement)
            return FakeResult()

    class FakeAdapter:
        def stock_bars(self, symbol, exchange, limit, interval, start_date=None, end_date=None):
            seen_calls.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "limit": limit,
                    "interval": interval,
                    "start_date": start_date,
                    "end_date": end_date,
                }
            )
            return {"source": "fake", "items": [{"trade_date": "2026-06-11 14:56:00", "open": 10, "high": 10.2, "low": 9.9, "close": 10.1}]}

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(data_sync, "session_scope", fake_session_scope)
    monkeypatch.setattr(data_sync, "_upsert_minute_bars", lambda symbol, exchange, items, interval, source: written.append((symbol, exchange, interval)) or len(items))

    runner = data_sync.DataSyncRunner()
    runner.adapter = FakeAdapter()
    result = runner._run_sync_stock_minute_bars(
        {
            "symbols": "600000.SSE",
            "start_date": "2026-06-01",
            "end_date": "2026-06-11",
            "stock_limit": 10,
            "limit": 1200,
            "interval": "1m",
            "only_missing": False,
        }
    )

    assert result == {"rows_read": 1, "rows_written": 1}
    assert seen_calls[0]["start_date"].isoformat() == "2026-06-01"
    assert seen_calls[0]["end_date"].isoformat() == "2026-06-11"
    assert seen_calls[0]["limit"] == 1200
    assert written == [("600000", "SSE", "1m")]


def test_import_stock_minute_bars_csv_groups_and_upserts(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    calls: list[tuple[str, str, list[dict[str, object]], str, str]] = []

    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)
    monkeypatch.setattr(data_sync, "ensure_sync_schema", lambda: None)

    def fake_upsert(symbol, exchange, items, interval, source):
        calls.append((symbol, exchange, items, interval, source))
        return len(items)

    monkeypatch.setattr(data_sync, "_upsert_minute_bars", fake_upsert)

    result = data_sync.import_stock_minute_bars_csv(
        "\ufeffvt_symbol,bar_time,open,high,low,close,volume,turnover\n"
        "600000.SSE,2026-01-08 14:56:00,10,10.2,9.9,10.1,1200,12120\n"
        "000001.SZSE,2026-01-08 14:56:00,20,20.2,19.9,20.1,2200,44220\n",
        interval="1m",
        source="unit_test",
    )

    assert result["status"] == "ready"
    assert result["rows_read"] == 2
    assert result["rows_written"] == 2
    assert result["symbol_count"] == 2
    assert calls[0][0:2] == ("600000", "SSE")
    assert calls[0][2][0]["close"] == 10.1
    assert calls[0][3:] == ("1m", "unit_test")


def test_import_stock_minute_bars_file_uses_allowed_path(monkeypatch, tmp_path) -> None:
    from alphaagent.server.services import data_sync

    import_dir = tmp_path / "data" / "imports"
    import_dir.mkdir(parents=True)
    csv_path = import_dir / "minute.csv"
    csv_path.write_text(
        "vt_symbol,bar_time,open,high,low,close,volume,turnover\n"
        "600000.SSE,2026-01-08 14:56:00,10,10.2,9.9,10.1,1200,12120\n",
        encoding="utf-8",
    )

    calls = []
    monkeypatch.setattr(data_sync, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_sync, "ALLOWED_IMPORT_DIRS", (import_dir,))
    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)
    monkeypatch.setattr(data_sync, "ensure_sync_schema", lambda: None)
    monkeypatch.setattr(data_sync, "_upsert_minute_bars", lambda symbol, exchange, items, interval, source: calls.append((symbol, exchange, source)) or len(items))

    result = data_sync.import_stock_minute_bars_file("data/imports/minute.csv", interval="1m", source="file_test")

    assert result["status"] == "ready"
    assert result["rows_written"] == 1
    assert result["file_path"] == "data/imports/minute.csv"
    assert calls == [("600000", "SSE", "file_test")]


def test_import_stock_minute_bars_file_flushes_large_csv(monkeypatch, tmp_path) -> None:
    from alphaagent.server.services import data_sync

    import_dir = tmp_path / "data" / "imports"
    import_dir.mkdir(parents=True)
    csv_path = import_dir / "minute_large.csv"
    rows = ["vt_symbol,bar_time,open,high,low,close,volume,turnover"]
    for index in range(2001):
        rows.append(f"600000.SSE,2026-01-08 14:{index % 60:02d}:00,10,10.2,9.9,10.1,1200,12120")
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    batch_sizes = []
    monkeypatch.setattr(data_sync, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_sync, "ALLOWED_IMPORT_DIRS", (import_dir,))
    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)
    monkeypatch.setattr(data_sync, "ensure_sync_schema", lambda: None)

    def fake_upsert(symbol, exchange, items, interval, source):
        del symbol, exchange, interval, source
        batch_sizes.append(len(items))
        return len(items)

    monkeypatch.setattr(data_sync, "_upsert_minute_bars", fake_upsert)

    result = data_sync.import_stock_minute_bars_file("data/imports/minute_large.csv", interval="1m")

    assert result["rows_read"] == 2001
    assert result["rows_written"] == 2001
    assert batch_sizes == [2000, 1]


def test_import_file_rejects_paths_outside_allowed_dirs(monkeypatch, tmp_path) -> None:
    from alphaagent.server.services import data_sync

    outside = tmp_path / "outside.csv"
    outside.write_text("vt_symbol,bar_time,open,high,low,close\n", encoding="utf-8")
    import_dir = tmp_path / "data" / "imports"

    monkeypatch.setattr(data_sync, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_sync, "ALLOWED_IMPORT_DIRS", (import_dir,))
    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)

    try:
        data_sync.import_stock_minute_bars_file(str(outside))
    except data_sync.DataSyncError as exc:
        assert "must be under" in str(exc)
    else:
        raise AssertionError("expected DataSyncError")


def test_import_file_rejects_empty_path(monkeypatch, tmp_path) -> None:
    from alphaagent.server.services import data_sync

    monkeypatch.setattr(data_sync, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_sync, "ALLOWED_IMPORT_DIRS", (tmp_path / "data" / "imports",))
    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)

    try:
        data_sync.import_stock_minute_bars_file(" ")
    except data_sync.DataSyncError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("expected DataSyncError")


def test_import_minute_bars_api_template_and_dry_run(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)

    client = TestClient(create_app())
    template = client.get("/api/data-sync/imports/minute-bars/template.csv")
    assert template.status_code == 200
    assert template.headers["content-type"].startswith("text/csv")
    assert "vt_symbol,bar_time" in template.text

    response = client.post(
        "/api/data-sync/imports/minute-bars",
        json={
            "dry_run": True,
            "csv_text": "vt_symbol,bar_time,open,high,low,close\n600000.SSE,2026-01-08 14:56:00,10,10.2,9.9,10.1\n",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["rows_read"] == 1
    assert response.json()["data"]["dry_run"] is True


def test_import_minute_bars_api_accepts_file_path(monkeypatch) -> None:
    from alphaagent.server.api import data_sync as api

    captured = {}

    def fake_import_file(file_path, interval, source, dry_run):
        captured.update({"file_path": file_path, "interval": interval, "source": source, "dry_run": dry_run})
        return {"status": "ready", "rows_read": 1, "rows_written": 0, "rows_skipped": 0, "file_path": file_path}

    monkeypatch.setattr(api.service, "import_stock_minute_bars_file", fake_import_file)

    client = TestClient(create_app())
    response = client.post(
        "/api/data-sync/imports/minute-bars",
        json={"file_path": "data/imports/minute.csv", "interval": "1m", "source": "file_test", "dry_run": True},
    )

    assert response.status_code == 200
    assert captured == {"file_path": "data/imports/minute.csv", "interval": "1m", "source": "file_test", "dry_run": True}
    assert response.json()["data"]["file_path"] == "data/imports/minute.csv"


def test_audit_minute_gap_csv_reports_missing_and_covered(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        data_sync,
        "_minute_gap_coverage_counts",
        lambda items, interval, start, end: {("600000.SSE", date(2026, 1, 8)): 2},
    )

    result = data_sync.audit_minute_gap_csv(
        "\ufefftrade_date,vt_symbol,reference_date,window,ma5,minute_bar_count,missing_reason\n"
        "2026-01-08,600000.SSE,2026-01-07,14:30-14:57,10.1,0,no_tail_window_minute_bars\n"
        "2026-01-08,000001.SZSE,2026-01-07,14:30-14:57,20.1,0,no_tail_window_minute_bars\n",
        interval="1m",
        tail_entry_start="14:30",
        tail_entry_end="14:57",
    )

    assert result["status"] == "incomplete"
    assert result["gap_count"] == 2
    assert result["covered_count"] == 1
    assert result["missing_count"] == 1
    assert result["coverage_pct"] == 50.0
    assert result["missing_examples"][0]["vt_symbol"] == "000001.SZSE"
    assert result["next_action"].startswith("import historical 1m bars")


def test_audit_minute_gap_file_uses_allowed_path(monkeypatch, tmp_path) -> None:
    from alphaagent.server.services import data_sync

    import_dir = tmp_path / "memory" / "06_backtests"
    import_dir.mkdir(parents=True)
    csv_path = import_dir / "gap.csv"
    csv_path.write_text("trade_date,vt_symbol\n2026-01-08,600000.SSE\n", encoding="utf-8")

    monkeypatch.setattr(data_sync, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(data_sync, "ALLOWED_IMPORT_DIRS", (import_dir,))
    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)
    monkeypatch.setattr(data_sync, "_minute_gap_coverage_counts", lambda items, interval, start, end: {})

    result = data_sync.audit_minute_gap_file("memory/06_backtests/gap.csv")

    assert result["status"] == "incomplete"
    assert result["gap_count"] == 1
    assert result["file_path"] == "memory/06_backtests/gap.csv"


def test_minute_gap_import_template_uses_gap_rows() -> None:
    from alphaagent.server.services import data_sync

    content = data_sync.minute_gap_import_template(
        "trade_date,vt_symbol,reference_date,window,ma5\n"
        "2026-01-08,600000.SSE,2026-01-07,14:30-14:57,10.1\n",
    )

    assert "vt_symbol,bar_time,open,high,low,close,volume,turnover" in content
    assert "600000.SSE,2026-01-08 14:56:00" in content


def test_minute_gap_audit_api(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    monkeypatch.setattr(data_sync, "is_database_configured", lambda: True)
    monkeypatch.setattr(data_sync, "_minute_gap_coverage_counts", lambda items, interval, start, end: {})

    client = TestClient(create_app())
    response = client.post(
        "/api/data-sync/imports/minute-bars/audit-gaps",
        json={
            "gap_csv_text": "trade_date,vt_symbol\n2026-01-08,600000.SSE\n",
            "interval": "1m",
            "tail_entry_start": "14:30",
            "tail_entry_end": "14:57",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "incomplete"
    assert response.json()["data"]["missing_count"] == 1


def test_minute_gap_audit_api_accepts_file_path(monkeypatch) -> None:
    from alphaagent.server.api import data_sync as api

    captured = {}

    def fake_audit_file(file_path, interval, tail_entry_start, tail_entry_end, min_tail_bars):
        captured.update(
            {
                "file_path": file_path,
                "interval": interval,
                "tail_entry_start": tail_entry_start,
                "tail_entry_end": tail_entry_end,
                "min_tail_bars": min_tail_bars,
            }
        )
        return {"status": "ready", "gap_count": 1, "covered_count": 1, "missing_count": 0, "file_path": file_path}

    monkeypatch.setattr(api.service, "audit_minute_gap_file", fake_audit_file)

    client = TestClient(create_app())
    response = client.post(
        "/api/data-sync/imports/minute-bars/audit-gaps",
        json={"file_path": "memory/06_backtests/gap.csv", "tail_entry_start": "14:30", "tail_entry_end": "14:57"},
    )

    assert response.status_code == 200
    assert captured["file_path"] == "memory/06_backtests/gap.csv"
    assert response.json()["data"]["status"] == "ready"


def test_quant_schema_tables_are_registered() -> None:
    table_names = set(schema.metadata.tables)

    assert "quant_stock_signals" in table_names
    assert "backtest_signal_events" in table_names
    assert "backtest_runs" in table_names
    assert "stock_minute_bars" in table_names
    assert "portfolio_groups" in table_names
    assert "simulation_positions" in table_names


def test_new_api_returns_unavailable_when_database_off(monkeypatch) -> None:
    from alphaagent.server.db import session as db_session
    from alphaagent.server.services.backtest import engine
    from alphaagent.server.services.portfolio import groups
    from alphaagent.server.services.quant import screening
    from alphaagent.server.services.simulation import account

    monkeypatch.setattr(db_session, "is_database_configured", lambda: False)
    monkeypatch.setattr(screening, "is_database_configured", lambda: False)
    monkeypatch.setattr(engine, "is_database_configured", lambda: False)
    monkeypatch.setattr(groups, "is_database_configured", lambda: False)
    monkeypatch.setattr(account, "is_database_configured", lambda: False)

    client = TestClient(create_app())

    assert client.get("/api/quant/trading-dates").json()["data"]["status"] == "unavailable"
    assert client.get("/api/quant/recommendations").json()["data"]["status"] == "unavailable"
    assert client.get("/api/backtests").json()["data"]["status"] == "unavailable"
    assert client.get("/api/portfolio/groups").json()["data"]["status"] == "unavailable"
    assert client.get("/api/simulation/accounts").json()["data"]["status"] == "unavailable"


def test_quant_screen_range_api_passes_range_payload(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    captured: dict[str, object] = {}

    def fake_screen_stocks_range(start=None, end=None, **kwargs):
        captured.update({"start": start, "end": end, **kwargs})
        return {
            "status": "ready",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "trade_date": end.isoformat(),
            "total_dates": 2,
            "succeeded_count": 2,
            "recommendation_count": 3,
            "range_recommendation_count": 7,
            "runs": [],
            "items": [],
            "recommendations": [],
        }

    monkeypatch.setattr(screening, "screen_stocks_range", fake_screen_stocks_range)

    client = TestClient(create_app())
    response = client.post(
        "/api/quant/screen-runs/range",
        json={
            "start": "2026-06-10",
            "end": "2026-06-12",
            "max_symbols": 120,
            "recommendation_limit": 20,
            "min_recommendation_score": 60,
            "persist": True,
            "auto_portfolio": True,
            "included_boards": ["main", "chinext"],
        },
    )

    data = response.json()["data"]
    assert response.status_code == 200
    assert data["status"] == "ready"
    assert data["total_dates"] == 2
    assert captured["start"] == date(2026, 6, 10)
    assert captured["end"] == date(2026, 6, 12)
    assert captured["max_symbols"] == 120
    assert captured["included_boards"] == ["main", "chinext"]


def test_backtest_service_bootstraps_schema_without_api_startup(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    calls: list[object] = []

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return []

    class FakeSession:
        def execute(self, statement):
            calls.append(statement)
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(engine, "is_database_configured", lambda: True)
    monkeypatch.setattr(engine, "get_engine", lambda: "fake-engine")
    monkeypatch.setattr(engine.schema, "create_schema", lambda db_engine: calls.append(("create_schema", db_engine)))
    monkeypatch.setattr(engine, "session_scope", fake_session_scope)

    result = engine.list_backtests()

    assert result == {"status": "ready", "items": []}
    assert calls[0] == ("create_schema", "fake-engine")


def test_backtest_list_filters_portfolio_and_symbol_runs(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    class FakeRows:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "id": 2,
                    "strategy_id": "mainline_leader_pullback",
                    "strategy_version": "0.1.1",
                    "start_date": date(2026, 1, 1),
                    "end_date": date(2026, 6, 12),
                    "status": "succeeded",
                    "initial_cash": 100_000,
                    "final_equity": 101_000,
                    "params": {"symbols": ["600000.SSE"]},
                    "metrics": {},
                },
                {
                    "id": 1,
                    "strategy_id": "mainline_leader_pullback",
                    "strategy_version": "0.1.1",
                    "start_date": date(2026, 1, 1),
                    "end_date": date(2026, 6, 12),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 990_000,
                    "params": {"symbols": []},
                    "metrics": {},
                },
            ]

    class FakeSession:
        def execute(self, statement):
            del statement
            return FakeRows()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(engine, "is_database_configured", lambda: True)
    monkeypatch.setattr(engine, "_ensure_backtest_schema", lambda: None)
    monkeypatch.setattr(engine, "session_scope", fake_session_scope)

    portfolio = engine.list_backtests(run_type="portfolio")
    symbol = engine.list_backtests(run_type="symbol")

    assert [item["id"] for item in portfolio["items"]] == [1]
    assert portfolio["items"][0]["run_type"] == "portfolio"
    assert [item["id"] for item in symbol["items"]] == [2]
    assert symbol["items"][0]["run_type"] == "symbol"


def test_backtest_list_fetches_extra_rows_before_run_type_filter(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    captured_limits: list[int] = []

    class FakeRows:
        def mappings(self):
            return self

        def all(self):
            rows = []
            for index in range(220, 20, -1):
                rows.append(
                    {
                        "id": index,
                        "strategy_id": "mainline_leader_pullback",
                        "strategy_version": "0.1.1",
                        "start_date": date(2026, 1, 1),
                        "end_date": date(2026, 6, 12),
                        "status": "succeeded",
                        "initial_cash": 100_000,
                        "final_equity": 101_000,
                        "params": {"symbols": [f"{index:06d}.SSE"]},
                        "metrics": {},
                    }
                )
            rows.append(
                {
                    "id": 20,
                    "strategy_id": "mainline_leader_pullback",
                    "strategy_version": "0.1.1",
                    "start_date": date(2026, 1, 1),
                    "end_date": date(2026, 6, 12),
                    "status": "succeeded",
                    "initial_cash": 1_000_000,
                    "final_equity": 990_000,
                    "params": {"symbols": []},
                    "metrics": {},
                }
            )
            return rows

    class FakeSession:
        def execute(self, statement):
            captured_limits.append(statement._limit_clause.value)
            return FakeRows()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(engine, "is_database_configured", lambda: True)
    monkeypatch.setattr(engine, "_ensure_backtest_schema", lambda: None)
    monkeypatch.setattr(engine, "session_scope", fake_session_scope)

    result = engine.list_backtests(limit=20, run_type="portfolio")

    assert captured_limits == [200]
    assert [item["id"] for item in result["items"]] == [20]


def test_quant_recommendation_marks_buy_only_for_entry_signal() -> None:
    from alphaagent.server.services.quant import screening

    buy_score = SignalScore(
        vt_symbol="600000.SSE",
        trade_date=date(2026, 1, 2),
        total_score=72,
        entry_signal=True,
        evidence={"status": "ready"},
    )
    watch_score = SignalScore(
        vt_symbol="000001.SZSE",
        trade_date=date(2026, 1, 2),
        total_score=72,
        entry_signal=False,
        evidence={"status": "ready"},
    )

    assert screening._recommendation_to_db(1, buy_score, None, "mainline_leader_pullback")["action"] == "BUY"
    assert screening._recommendation_to_db(2, watch_score, None, "mainline_leader_pullback")["action"] == "WATCH"


def test_stock_board_classification_is_display_only_identity() -> None:
    from alphaagent.market.boards import normalize_included_boards, stock_board, stock_board_payload

    assert stock_board("600000.SSE") == "main"
    assert stock_board("000001.SZSE") == "main"
    assert stock_board("300750.SZSE") == "chinext"
    assert stock_board("688981.SSE") == "star"
    assert stock_board("920001.BSE") == "bse"
    assert stock_board_payload("300750.SZSE")["board_label"] == "创业板"
    assert normalize_included_boards(None) == ("main",)
    assert normalize_included_boards("main,chinext,main") == ("main", "chinext")


def test_quant_universe_defaults_to_main_board_only() -> None:
    from alphaagent.server.services.quant import screening

    rows = [
        {"vt_symbol": "300750.SZSE", "exchange": "SZSE", "turnover": 300, "market_cap": 300},
        {"vt_symbol": "600000.SSE", "exchange": "SSE", "turnover": 200, "market_cap": 200},
        {"vt_symbol": "688981.SSE", "exchange": "SSE", "turnover": 100, "market_cap": 100},
        {"vt_symbol": "920001.BSE", "exchange": "BSE", "turnover": 50, "market_cap": 50},
    ]

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return rows

    class FakeSession:
        def execute(self, statement):
            del statement
            return FakeResult()

    default_symbols = [row["vt_symbol"] for row in screening._load_stock_universe(FakeSession(), 10, ("main",))]
    all_symbols = [row["vt_symbol"] for row in screening._load_stock_universe(FakeSession(), 10, ("main", "chinext", "star", "bse"))]

    assert "300750.SZSE" not in default_symbols
    assert "688981.SSE" not in default_symbols
    assert "920001.BSE" not in default_symbols
    assert default_symbols == ["600000.SSE"]
    assert "300750.SZSE" in all_symbols
    assert "688981.SSE" in all_symbols
    assert "920001.BSE" in all_symbols


def test_backtest_universe_filters_boards_only_for_generated_pool() -> None:
    from alphaagent.server.services.backtest import engine

    class FakeAllResult:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if "stocks.vt_symbol IN" in text:
                return FakeAllResult([("300750.SZSE",)])
            return FakeAllResult(
                [
                    ("300750.SZSE", "SZSE"),
                    ("600000.SSE", "SSE"),
                    ("688981.SSE", "SSE"),
                ]
            )

    generated = engine._load_symbol_universe(FakeSession(), 10, None, ("main",))
    requested = engine._load_symbol_universe(FakeSession(), 10, ["300750.SZSE"], ("main",))

    assert generated == ["600000.SSE"]
    assert requested == ["300750.SZSE"]


def test_persist_screen_run_clears_same_day_outputs_before_insert() -> None:
    from alphaagent.server.services.quant import screening

    calls: list[str] = []

    class FakeReturning:
        def scalar_one(self):
            return 7

    class FakeScalar:
        def scalar_one_or_none(self):
            return None

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if text.startswith("INSERT INTO quant_signal_runs"):
                return FakeReturning()
            if text.startswith("DELETE FROM quant_recommendations"):
                calls.append("delete_recommendations")
                return FakeScalar()
            if text.startswith("DELETE FROM quant_stock_signals"):
                calls.append("delete_signals")
                return FakeScalar()
            if text.startswith("INSERT INTO quant_stock_signals"):
                calls.append("insert_signal")
                return FakeScalar()
            if text.startswith("INSERT INTO quant_recommendations"):
                calls.append("insert_recommendation")
                return FakeScalar()
            return FakeScalar()

    score = SignalScore(
        vt_symbol="600000.SSE",
        trade_date=date(2026, 1, 2),
        total_score=72,
        entry_signal=True,
        evidence={"status": "ready"},
    )

    run_id = screening._persist_screen_run(FakeSession(), date(2026, 1, 2), [score], [score], "mainline_leader_pullback", ("main",))

    assert run_id == 7
    assert calls == ["delete_recommendations", "delete_signals", "insert_signal", "insert_recommendation"]


def test_recommendations_use_latest_screen_run_id_when_latest_run_has_no_items(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    executed: list[str] = []

    class FakeRows:
        def __init__(self, rows=None):
            self.rows = rows or []

        def mappings(self):
            return self

        def first(self):
            return self.rows[0] if self.rows else None

        def all(self):
            return []

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            executed.append(text)
            if "FROM quant_signal_runs" in text:
                return FakeRows([
                    {
                        "id": 8,
                        "trade_date": date(2026, 1, 3),
                        "strategy_id": "mainline_leader_pullback",
                        "strategy_version": "0.1.1",
                        "params": {"included_boards": ["main"]},
                    }
                ])
            return FakeRows()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)

    result = screening.list_recommendations()

    assert result["status"] == "empty"
    assert result["trade_date"] == "2026-01-03"
    assert result["run_id"] == 8
    assert result["items"] == []
    assert any("quant_signal_runs.strategy_version = :strategy_version_1" in statement for statement in executed)
    assert any("quant_signal_runs.status = :status_1" in statement for statement in executed)
    assert any("quant_recommendations.run_id = :run_id_1" in statement for statement in executed)


def test_recommendations_use_latest_screen_run_id_not_same_day_old_versions(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    executed: list[str] = []

    class FakeRows:
        def __init__(self, rows=None):
            self.rows = rows or []

        def mappings(self):
            return self

        def first(self):
            return self.rows[0] if self.rows else None

        def all(self):
            return self.rows

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            executed.append(text)
            if "FROM quant_signal_runs" in text:
                return FakeRows([
                    {
                        "id": 6,
                        "trade_date": date(2026, 6, 11),
                        "strategy_id": "mainline_leader_pullback",
                        "strategy_version": "0.1.1",
                        "params": {"included_boards": ["main"]},
                    }
                ])
            return FakeRows([])

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)

    result = screening.list_recommendations()

    assert result["run_id"] == 6
    assert result["strategy_version"] == "0.1.1"
    assert result["included_boards"] == ["main"]
    assert result["trade_date"] == "2026-06-11"
    assert any("quant_signal_runs.strategy_version = :strategy_version_1" in statement for statement in executed)
    assert any("quant_signal_runs.status = :status_1" in statement for statement in executed)
    assert any("quant_recommendations.run_id = :run_id_1" in statement for statement in executed)
    assert not any(
        "quant_recommendations.trade_date = :trade_date_1" in statement
        and "quant_recommendations.run_id = :run_id_1" not in statement
        for statement in executed
    )


def test_list_screen_runs_returns_recent_runs(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    class FakeRows:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "id": 9,
                    "strategy_id": "mainline_leader_pullback",
                    "strategy_version": "0.1.1",
                    "trade_date": date(2026, 6, 12),
                    "status": "succeeded",
                    "params": {"included_boards": ["main"]},
                    "candidate_count": 300,
                    "signal_count": 12,
                    "recommendation_count": 20,
                }
            ]

    class FakeSession:
        def execute(self, statement):
            assert "FROM quant_signal_runs" in str(statement)
            return FakeRows()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)

    result = screening.list_screen_runs()

    assert result["status"] == "ready"
    assert result["items"][0]["trade_date"] == "2026-06-12"
    assert result["items"][0]["recommendation_count"] == 20


def test_list_trading_dates_returns_local_daily_bar_dates(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    class FakeRows:
        def mappings(self):
            return self

        def all(self):
            return [
                {"trade_date": date(2026, 6, 12), "symbol_count": 2},
                {"trade_date": date(2026, 6, 11), "symbol_count": 1},
            ]

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            assert "FROM stock_daily_bars" in text
            assert "GROUP BY stock_daily_bars.trade_date" in text
            assert "ORDER BY stock_daily_bars.trade_date DESC" in text
            return FakeRows()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)

    result = screening.list_trading_dates(limit=20)

    assert result["status"] == "ready"
    assert result["latest_trade_date"] == "2026-06-12"
    assert result["returned_count"] == 2
    assert result["items"] == [
        {"trade_date": "2026-06-12", "symbol_count": 2},
        {"trade_date": "2026-06-11", "symbol_count": 1},
    ]


def test_screen_stocks_range_uses_local_trading_dates_and_syncs_latest_only(monkeypatch) -> None:
    from alphaagent.server.services.quant import screening

    calls: list[tuple[date, bool]] = []

    class FakeRows:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class FakeScalar:
        def scalar(self):
            return date(2026, 6, 12)

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if "max(stock_daily_bars.trade_date)" in text:
                return FakeScalar()
            assert "FROM stock_daily_bars" in text
            assert "GROUP BY stock_daily_bars.trade_date" in text
            assert "ORDER BY stock_daily_bars.trade_date" in text
            return FakeRows([(date(2026, 6, 10),), (date(2026, 6, 11),), (date(2026, 6, 12),)])

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    def fake_screen_stocks(trade_date, **kwargs):
        calls.append((trade_date, kwargs["auto_portfolio"]))
        return {
            "status": "ready",
            "trade_date": trade_date.isoformat(),
            "run_id": len(calls),
            "total": 100 + len(calls),
            "recommendation_count": len(calls),
            "included_boards": kwargs["included_boards"],
            "items": [{"trade_date": trade_date.isoformat()}],
            "recommendations": [{"trade_date": trade_date.isoformat()}],
            "portfolio_sync": {"synced": 1} if kwargs["auto_portfolio"] else None,
        }

    monkeypatch.setattr(screening, "is_database_configured", lambda: True)
    monkeypatch.setattr(screening, "_ensure_quant_schema", lambda: None)
    monkeypatch.setattr(screening, "session_scope", fake_session_scope)
    monkeypatch.setattr(screening, "screen_stocks", fake_screen_stocks)

    result = screening.screen_stocks_range(start=date(2026, 6, 10), included_boards=["main"])

    assert calls == [
        (date(2026, 6, 10), False),
        (date(2026, 6, 11), False),
        (date(2026, 6, 12), True),
    ]
    assert result["status"] == "ready"
    assert result["start_date"] == "2026-06-10"
    assert result["end_date"] == "2026-06-12"
    assert result["trade_date"] == "2026-06-12"
    assert result["total_dates"] == 3
    assert result["succeeded_count"] == 3
    assert result["range_recommendation_count"] == 6
    assert result["recommendation_count"] == 3
    assert result["portfolio_sync"] == {"synced": 1}
    assert [item["trade_date"] for item in result["runs"]] == ["2026-06-10", "2026-06-11", "2026-06-12"]


def test_backtest_metric_rows_are_report_ready() -> None:
    from alphaagent.server.services.backtest import engine

    rows = engine._metric_rows(
        {
            "initial_cash": 1_000_000,
            "final_equity": 1_063_272.4,
            "total_return_pct": 6.3272,
            "win_rate": 0.6,
        }
    )

    assert rows == [
        {"key": "initial_cash", "label": "初始资金", "value": 1_000_000},
        {"key": "final_equity", "label": "期末权益", "value": 1_063_272.4},
        {"key": "total_return_pct", "label": "总收益率", "value": 6.3272},
        {"key": "win_rate", "label": "胜率", "value": 0.6},
    ]


def test_backtest_tail_entry_uses_minute_bar_near_visible_ma5() -> None:
    from datetime import datetime

    from alphaagent.server.services.backtest import engine

    dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(6)]
    symbol_bars = {
        dates[index]: engine.Bar(
            trade_date=dates[index],
            open_price=10 + index * 0.1,
            high_price=10.5 + index * 0.1,
            low_price=9.8 + index * 0.1,
            close_price=10 + index * 0.1,
        )
        for index in range(5)
    }
    execute_day = dates[5]
    daily_bar = engine.Bar(
        trade_date=execute_day,
        open_price=10.9,
        high_price=11.0,
        low_price=10.1,
        close_price=10.3,
    )
    bar_index = {"600000.SSE": {**symbol_bars, execute_day: daily_bar}}
    minute_index = {
        "600000.SSE": {
            execute_day: [
                engine.MinuteBar(
                    bar_time=datetime(2026, 1, 6, 14, 56),
                    trade_date=execute_day,
                    open_price=10.18,
                    high_price=10.22,
                    low_price=10.16,
                    close_price=10.2,
                )
            ]
        }
    }

    fill = engine._resolve_buy_fill(
        {"vt_symbol": "600000.SSE", "signal_date": dates[4]},
        execute_day,
        daily_bar,
        bar_index,
        minute_index,
        engine.BacktestParams(),
    )

    assert fill["status"] == "filled"
    assert fill["mode"] == "minute_tail_ma5"
    assert fill["price"] == 10.2
    assert fill["reference_date"] == dates[4].isoformat()


def test_backtest_can_reject_when_minute_tail_entry_is_required() -> None:
    from alphaagent.server.services.backtest import engine

    execute_day = date(2026, 1, 6)
    daily_bar = engine.Bar(
        trade_date=execute_day,
        open_price=10.9,
        high_price=11.0,
        low_price=10.1,
        close_price=10.3,
    )
    bar_index = {
        "600000.SSE": {
            date(2026, 1, 1) + timedelta(days=index): engine.Bar(
                trade_date=date(2026, 1, 1) + timedelta(days=index),
                open_price=10,
                high_price=10,
                low_price=10,
                close_price=10,
            )
            for index in range(5)
        }
    }
    params = engine.BacktestParams(minute_entry_required=True)

    fill = engine._resolve_buy_fill(
        {"vt_symbol": "600000.SSE", "signal_date": date(2026, 1, 5)},
        execute_day,
        daily_bar,
        bar_index,
        {},
        params,
    )

    assert fill["status"] == "rejected"
    assert fill["reason"] == "tail_entry_not_triggered"


def test_signal_events_use_independent_symbol_state_machine() -> None:
    from alphaagent.server.services.backtest import engine

    symbol = "600000.SSE"
    signal_day = date(2026, 1, 5)
    execute_day = date(2026, 1, 6)
    sell_day = date(2026, 1, 10)
    bar_index = {
        symbol: {
            execute_day: engine.Bar(execute_day, 10, 10.5, 9.8, 10.2),
            sell_day + timedelta(days=1): engine.Bar(sell_day + timedelta(days=1), 8.6, 8.9, 8.4, 8.5),
        }
    }
    today_bars = {
        symbol: engine.Bar(sell_day, 8.8, 9.0, 8.6, 8.7),
    }
    score = SignalScore(
        vt_symbol=symbol,
        trade_date=signal_day,
        total_score=80,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready"},
    )
    params = engine.BacktestParams(stop_loss_pct=0.07)
    positions: dict[str, engine.Position] = {}

    buys = engine._signal_events_for_day(signal_day, execute_day, [score], positions, {}, bar_index, {symbol: {"name": "浦发银行"}}, params)
    duplicate = engine._signal_events_for_day(signal_day + timedelta(days=1), sell_day, [score], positions, {}, bar_index, {}, params)
    sells = engine._signal_events_for_day(sell_day, sell_day + timedelta(days=1), [], positions, today_bars, bar_index, {}, params)

    assert [row["side"] for row in buys] == ["BUY"]
    assert duplicate == []
    assert [row["side"] for row in sells] == ["SELL"]
    assert sells[0]["reason"] == "stop_loss"


def test_signal_amount_preview_uses_equal_capital_budget(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    def fake_events(*args, **kwargs):
        del args, kwargs
        return {
            "status": "ready",
            "backtest_id": 5,
            "items": [
                {"trade_date": "2026-01-02", "vt_symbol": "600000.SSE", "side": "BUY", "price": 10.0},
                {"trade_date": "2026-01-10", "vt_symbol": "600000.SSE", "side": "SELL", "price": 12.0},
            ],
        }

    monkeypatch.setattr(engine, "backtest_signal_events", fake_events)

    result = engine.backtest_signal_amount_preview(5, capital=1_000_000, max_positions=8)

    assert result["per_trade_budget"] == 125_000
    assert result["items"][1]["preview_volume"] == 12_500
    assert result["items"][1]["preview_amount"] == 125_000
    assert result["items"][0]["preview_volume"] == 12_500
    assert result["items"][0]["preview_pnl"] == 25_000


def test_signal_amount_preview_filters_after_pairing_trades(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    def fake_events(*args, **kwargs):
        del args, kwargs
        return {
            "status": "ready",
            "backtest_id": 5,
            "items": [
                {"trade_date": "2026-01-02", "vt_symbol": "600000.SSE", "side": "BUY", "price": 10.0},
                {"trade_date": "2026-06-10", "vt_symbol": "600000.SSE", "side": "SELL", "price": 12.0},
            ],
        }

    monkeypatch.setattr(engine, "backtest_signal_events", fake_events)

    result = engine.backtest_signal_amount_preview(
        5,
        capital=1_000_000,
        max_positions=8,
        start=date(2026, 6, 1),
        side="SELL",
    )

    assert len(result["items"]) == 1
    assert result["items"][0]["side"] == "SELL"
    assert result["items"][0]["preview_volume"] == 12_500
    assert result["items"][0]["preview_pnl"] == 25_000


def test_backtest_sell_signal_executes_next_day_open_without_lookahead() -> None:
    from alphaagent.server.services.backtest import engine

    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)
    d2 = date(2026, 1, 3)
    d3 = date(2026, 1, 4)
    bars_by_symbol = {
        "600000.SSE": [
            engine.Bar(trade_date=d0, open_price=10.0, high_price=10.0, low_price=10.0, close_price=10.0),
            engine.Bar(trade_date=d1, open_price=10.0, high_price=10.1, low_price=9.9, close_price=10.0),
            engine.Bar(trade_date=d2, open_price=5.0, high_price=12.5, low_price=4.9, close_price=12.0),
            engine.Bar(trade_date=d3, open_price=13.0, high_price=13.2, low_price=12.8, close_price=13.1),
        ]
    }
    candidate = SignalScore(
        vt_symbol="600000.SSE",
        trade_date=d0,
        total_score=80,
        liquidity_score=80,
        risk_score=80,
        entry_signal=True,
        evidence={"status": "ready", "note": "unit_test_candidate"},
    )
    params = engine.BacktestParams(
        start=d0,
        end=d3,
        initial_cash=100_000,
        max_positions=1,
        max_position_pct=1.0,
        commission_rate=0.0,
        stamp_tax_rate=0.0,
        slippage_bps=0.0,
        take_profit_pct=0.1,
        stop_loss_pct=0.5,
        trailing_stop_pct=0.9,
        time_stop_days=999,
        intraday_entry=False,
    )

    run = engine._simulate(
        None,
        params,
        bars_by_symbol,
        [d0, d1, d2, d3],
        {"600000.SSE": {"name": "测试股"}},
        score_cache={d0: [candidate], d2: []},
        minute_index={},
        score_context=engine.ScoreContext(),
    )

    sells = [trade for trade in run["trades"] if trade["side"] == "SELL"]
    assert len(sells) == 1
    assert sells[0]["trade_date"] == d3.isoformat()
    assert sells[0]["price"] == 13.0
    assert sells[0]["raw"]["signal_date"] == d2.isoformat()
    assert sells[0]["raw"]["mode"] == "daily_next_open_sell"
    assert not any(trade["side"] == "SELL" and trade["trade_date"] == d2.isoformat() for trade in run["trades"])

    pending_orders = [order for order in run["orders"] if order["side"] == "SELL" and order["status"] == "pending"]
    assert pending_orders[0]["trade_date"] == d2.isoformat()
    assert pending_orders[0]["raw"]["execute_date"] == d3.isoformat()


def test_backtest_persist_filters_api_only_order_fields() -> None:
    from alphaagent.server.services.backtest import engine

    values = engine._table_values(
        engine.schema.backtest_orders,
        {
            "trade_date": "2026-01-03",
            "vt_symbol": "600000.SSE",
            "board": "main",
            "board_label": "主板",
            "side": "SELL",
            "price": 13.0,
            "volume": 1000,
            "status": "filled",
            "reason": "take_profit",
            "raw": {"mode": "daily_next_open_sell"},
        },
    )

    assert values == {
        "trade_date": date(2026, 1, 3),
        "vt_symbol": "600000.SSE",
        "side": "SELL",
        "price": 13.0,
        "volume": 1000,
        "status": "filled",
        "reason": "take_profit",
        "raw": {"mode": "daily_next_open_sell"},
    }


def test_backtest_report_tables_pair_closed_trades_and_symbol_performance() -> None:
    from alphaagent.server.services.backtest import engine

    trades = [
        {
            "id": 1,
            "trade_date": date(2026, 1, 2),
            "vt_symbol": "600000.SSE",
            "name": "浦发银行",
            "side": "BUY",
            "price": 10.0,
            "volume": 1000,
            "amount": 10_000.0,
            "fee": 3.0,
            "pnl": None,
            "reason": "entry_signal",
            "raw": {},
        },
        {
            "id": 2,
            "trade_date": date(2026, 1, 9),
            "vt_symbol": "600000.SSE",
            "name": "浦发银行",
            "side": "SELL",
            "price": 11.0,
            "volume": 1000,
            "amount": 11_000.0,
            "fee": 8.8,
            "pnl": 991.2,
            "reason": "take_profit",
            "raw": {"entry_date": "2026-01-02"},
        },
        {
            "id": 3,
            "trade_date": date(2026, 1, 10),
            "vt_symbol": "000001.SZSE",
            "name": "平安银行",
            "side": "BUY",
            "price": 20.0,
            "volume": 500,
            "amount": 10_000.0,
            "fee": 3.0,
            "pnl": None,
            "reason": "entry_signal",
            "raw": {},
        },
        {
            "id": 4,
            "trade_date": date(2026, 1, 16),
            "vt_symbol": "000001.SZSE",
            "name": "平安银行",
            "side": "SELL",
            "price": 19.0,
            "volume": 500,
            "amount": 9_500.0,
            "fee": 7.6,
            "pnl": -507.6,
            "reason": "stop_loss",
            "raw": {"entry_date": "2026-01-10"},
        },
    ]

    closed = engine._closed_trades(trades)
    symbols = engine._symbol_performance(closed)
    stats = engine._extended_metrics(
        {"initial_cash": 100_000},
        closed,
        trades,
        [{"status": "filled"}, {"status": "rejected", "reason": "limit_up_or_no_bar"}],
        [
            {"trade_date": date(2026, 1, 2), "market_value": 10_000, "total_equity": 100_000, "position_count": 1},
            {"trade_date": date(2026, 1, 9), "market_value": 0, "total_equity": 100_991.2, "position_count": 0},
        ],
    )

    assert len(closed) == 2
    assert closed[0]["name"] == "浦发银行"
    assert closed[0]["entry_price"] == 10.0
    assert closed[0]["holding_days"] == 7
    assert closed[1]["return_pct"] == -5.076
    assert symbols[0]["vt_symbol"] == "600000.SSE"
    assert symbols[0]["name"] == "浦发银行"
    assert symbols[0]["pnl"] == 991.2
    assert stats["closed_trade_count"] == 2
    assert stats["rejected_order_count"] == 1
    assert stats["average_holding_days"] == 6.5


def test_backtest_audit_events_keep_stock_names() -> None:
    from alphaagent.server.services.backtest import engine

    events = engine._audit_events(
        [
            {
                "trade_date": "2026-01-02",
                "vt_symbol": "600000.SSE",
                "name": "浦发银行",
                "side": "BUY",
                "price": 10.0,
                "volume": 1000,
                "status": "filled",
                "reason": "entry_signal",
                "raw": {"execution": {"mode": "minute_tail_ma5"}},
            }
        ],
        [
            {
                "trade_date": "2026-01-02",
                "vt_symbol": "600000.SSE",
                "name": "浦发银行",
                "side": "BUY",
                "price": 10.0,
                "volume": 1000,
                "pnl": None,
                "reason": "entry_signal",
                "raw": {"execution": {"mode": "minute_tail_ma5"}},
            }
        ],
    )

    assert events[0]["name"] == "浦发银行"
    assert events[1]["name"] == "浦发银行"


def test_backtest_monthly_returns_and_order_stats_are_report_ready() -> None:
    from alphaagent.server.services.backtest import engine

    monthly = engine._monthly_returns(
        [
            {"trade_date": date(2026, 1, 2), "total_equity": 100_000},
            {"trade_date": date(2026, 1, 31), "total_equity": 110_000},
            {"trade_date": date(2026, 2, 1), "total_equity": 108_000},
            {"trade_date": date(2026, 2, 28), "total_equity": 120_000},
        ]
    )
    orders = engine._order_stats(
        [
            {"trade_date": date(2026, 1, 2), "vt_symbol": "600000.SSE", "side": "BUY", "status": "filled", "reason": "entry_signal"},
            {"trade_date": date(2026, 1, 3), "vt_symbol": "000001.SZSE", "side": "BUY", "status": "rejected", "reason": "limit_up_or_no_bar"},
        ]
    )

    assert monthly == [
        {
            "month": "2026-01",
            "start_date": "2026-01-02",
            "end_date": "2026-01-31",
            "start_equity": 100_000,
            "end_equity": 110_000,
            "return_pct": 10.000000000000009,
            "max_drawdown_pct": 0.0,
        },
        {
            "month": "2026-02",
            "start_date": "2026-02-01",
            "end_date": "2026-02-28",
            "start_equity": 110_000,
            "end_equity": 120_000,
            "return_pct": 9.090909090909083,
            "max_drawdown_pct": -1.8181818181818188,
        },
    ]
    assert orders["total"] == 2
    assert orders["by_status"] == {"filled": 1, "rejected": 1}
    assert orders["by_reason"]["limit_up_or_no_bar"] == 1
    assert orders["rejected_examples"][0]["trade_date"] == "2026-01-03"


def test_backtest_benchmark_and_period_analysis_are_report_ready() -> None:
    from alphaagent.server.services.backtest import engine

    sample_bars = [
        {"vt_symbol": "600000.SSE", "trade_date": date(2026, 1, 1), "close_price": 10.0},
        {"vt_symbol": "600000.SSE", "trade_date": date(2026, 1, 2), "close_price": 11.0},
        {"vt_symbol": "600000.SSE", "trade_date": date(2026, 1, 3), "close_price": 12.1},
        {"vt_symbol": "000001.SZSE", "trade_date": date(2026, 1, 1), "close_price": 20.0},
        {"vt_symbol": "000001.SZSE", "trade_date": date(2026, 1, 2), "close_price": 19.0},
        {"vt_symbol": "000001.SZSE", "trade_date": date(2026, 1, 3), "close_price": 20.9},
    ]
    equity = [
        {"trade_date": date(2026, 1, 1), "total_equity": 100_000},
        {"trade_date": date(2026, 1, 2), "total_equity": 102_000},
        {"trade_date": date(2026, 1, 3), "total_equity": 104_000},
    ]
    closed = [
        {"exit_date": "2026-01-02", "pnl": 500.0},
        {"exit_date": "2026-01-03", "pnl": -100.0},
    ]

    curve = engine._sample_equal_weight_curve(sample_bars)
    report = engine._benchmark_report(equity, curve)
    periods = engine._period_analysis(equity, closed, curve)

    assert len(curve) == 3
    assert curve[0]["nav"] == 1.0
    assert round(curve[1]["daily_return"], 4) == 0.025
    assert report["benchmarks"][0]["id"] == "sample_equal_weight"
    assert report["benchmarks"][0]["status"] == "ready"
    assert periods["status"] == "ready"
    assert periods["periods"][0]["id"] == "in_sample"
    assert periods["periods"][1]["id"] == "out_of_sample"
    assert periods["periods"][1]["benchmark_return_pct"] is not None


def test_index_benchmark_curve_from_bars_is_report_ready() -> None:
    from alphaagent.server.services.backtest import engine

    curve = engine._bars_nav_curve(
        [
            {"trade_date": "2026-01-01", "close": 100},
            {"trade_date": "2026-01-02", "close": 110},
            {"trade_date": "2026-01-03", "close": 99},
        ],
        date(2026, 1, 1),
        date(2026, 1, 3),
    )
    report = engine._benchmark_report(
        [{"trade_date": date(2026, 1, 1), "total_equity": 100_000}, {"trade_date": date(2026, 1, 3), "total_equity": 105_000}],
        [],
        [{"id": "index_000300_sse", "name": "沪深300", "source": "test", "curve": curve}],
    )

    assert len(curve) == 3
    assert round(curve[-1]["nav"], 4) == 0.99
    assert report["benchmarks"][0]["id"] == "index_000300_sse"
    assert report["benchmarks"][0]["status"] == "ready"
    assert round(report["benchmarks"][0]["return_pct"], 4) == -1.0


def test_backtest_regime_analysis_and_csv_are_report_ready() -> None:
    from alphaagent.server.services.backtest import engine

    equity = [
        {"trade_date": date(2026, 1, 1) + timedelta(days=index), "total_equity": 100_000 + index * 1_000}
        for index in range(60)
    ]
    benchmark_curve = []
    nav = 1.0
    for index in range(60):
        daily_return = 0.01 if index < 20 else -0.004 if index < 40 else 0.001
        nav *= 1 + daily_return
        benchmark_curve.append(
            {
                "trade_date": date(2026, 1, 1) + timedelta(days=index),
                "nav": nav,
                "daily_return": daily_return,
                "member_count": 2,
            }
        )
    closed = [
        {"exit_date": "2026-01-10", "pnl": 1000.0},
        {"exit_date": "2026-01-30", "pnl": -500.0},
        {"exit_date": "2026-02-20", "pnl": 700.0},
    ]

    regimes = engine._regime_analysis(equity, closed, benchmark_curve)
    report = {
        "backtest_id": 7,
        "strategy_id": "mainline_leader_pullback",
        "strategy_version": "0.1.0",
        "start_date": "2026-01-01",
        "end_date": "2026-03-01",
        "assumptions": {"execution": "D close signal, D+1 open simulated fill"},
        "summary_rows": [{"label": "总收益率", "value": 10.0}],
        "sample": {"symbol_count": 2, "bar_count": 120},
        "extended_metrics": {"trade_count": 3},
        "benchmark": {"benchmarks": [{"id": "sample_equal_weight", "status": "ready", "return_pct": 8.0}]},
        "period_analysis": {"periods": []},
        "regime_analysis": regimes,
        "monthly_returns": [],
        "symbol_performance": [],
        "worst_trades": [],
        "trades": [{"trade_date": "2026-01-02", "vt_symbol": "600000.SSE", "side": "BUY"}],
        "closed_trades": closed,
        "order_stats": {"by_status": {"filled": 1}, "by_reason": {"entry_signal": 1}, "rejected_examples": []},
        "data_quality": {"stocks": {"count": 2}, "limitations": ["数据限制"]},
        "limitations": ["回测限制"],
    }

    csv_content = engine._report_csv_content(report)

    assert regimes["status"] == "ready"
    assert {item["regime"] for item in regimes["periods"]} >= {"strong", "choppy"}
    assert csv_content.startswith("\ufeff")
    assert "## 核心指标" in csv_content
    assert "## 市场环境分段" in csv_content
    assert "## 交易明细" in csv_content
    assert "回测限制" in csv_content


def test_backtest_robustness_checks_are_report_ready() -> None:
    from alphaagent.server.services.backtest import engine

    equity = [
        {"trade_date": date(2025, 12, 30), "total_equity": 100_000},
        {"trade_date": date(2025, 12, 31), "total_equity": 101_000},
        {"trade_date": date(2026, 1, 2), "total_equity": 103_000},
        {"trade_date": date(2026, 1, 5), "total_equity": 104_000},
    ]
    closed = [
        {"exit_date": "2025-12-31", "pnl": 1000.0},
        {"exit_date": "2026-01-05", "pnl": 1200.0},
    ]
    trades = [
        {"side": "BUY", "amount": 10_000.0},
        {"side": "SELL", "amount": 11_000.0},
    ]
    sample_bars = [
        {"vt_symbol": "600000.SSE", "trade_date": date(2025, 12, 30), "close_price": 10.0},
        {"vt_symbol": "600000.SSE", "trade_date": date(2025, 12, 31), "close_price": 11.0},
        {"vt_symbol": "600000.SSE", "trade_date": date(2026, 1, 2), "close_price": 12.0},
        {"vt_symbol": "000001.SZSE", "trade_date": date(2025, 12, 30), "close_price": 20.0},
        {"vt_symbol": "000001.SZSE", "trade_date": date(2025, 12, 31), "close_price": 19.0},
        {"vt_symbol": "000001.SZSE", "trade_date": date(2026, 1, 2), "close_price": 21.0},
    ]
    benchmark = engine._sample_equal_weight_curve(sample_bars)

    checks = engine._robustness_checks(
        {"initial_cash": 100_000, "final_equity": 104_000, "total_return_pct": 4.0},
        equity,
        closed,
        trades,
        sample_bars,
        benchmark,
    )
    csv_content = engine._report_csv_content(
        {
            "backtest_id": 8,
            "strategy_id": "mainline_leader_pullback",
            "strategy_version": "0.1.0",
            "start_date": "2025-12-30",
            "end_date": "2026-01-05",
            "assumptions": {"execution": "test"},
            "summary_rows": [],
            "sample": {},
            "extended_metrics": {},
            "benchmark": {"benchmarks": []},
            "period_analysis": {"periods": []},
            "regime_analysis": {"periods": []},
            "robustness_checks": checks,
            "monthly_returns": [],
            "symbol_performance": [],
            "worst_trades": [],
            "trades": [],
            "closed_trades": [],
            "order_stats": {"by_status": {}, "by_reason": {}, "rejected_examples": []},
            "data_quality": {},
            "limitations": [],
        }
    )

    assert checks["status"] == "ready"
    assert len(checks["yearly_periods"]) == 2
    assert checks["cost_stress"][-1]["id"] == "high_friction"
    assert checks["random_baseline"]["status"] == "ready"
    assert {item["id"] for item in checks["diagnostics"]} >= {"high_friction_positive", "random_baseline_excess"}
    assert next(item for item in checks["diagnostics"] if item["id"] == "calendar_periods_positive")["value_type"] == "count"
    assert "## 年度分段" in csv_content
    assert "## 成本压力测试" in csv_content
    assert "## 反过拟合诊断" in csv_content


def test_backtest_validation_grid_summary_and_csv_are_report_ready() -> None:
    from alphaagent.server.services.backtest import engine

    rows = [
        {
            "variant_id": 1,
            "is_base_params": True,
            "min_entry_score": 68.0,
            "stop_loss_pct": 0.07,
            "take_profit_pct": 0.18,
            "strict_entry": True,
            "total_return_pct": 10.0,
            "out_sample_return_pct": 4.0,
            "sample_equal_weight_excess_pct": -2.0,
            "high_friction_return_pct": 8.0,
            "max_drawdown_pct": -5.0,
        },
        {
            "variant_id": 2,
            "is_base_params": False,
            "min_entry_score": 64.0,
            "stop_loss_pct": 0.05,
            "take_profit_pct": 0.14,
            "strict_entry": False,
            "total_return_pct": -1.0,
            "out_sample_return_pct": -2.0,
            "sample_equal_weight_excess_pct": -5.0,
            "high_friction_return_pct": -3.0,
            "max_drawdown_pct": -8.0,
        },
    ]
    summary = engine._validation_grid_summary(rows)
    diagnostics = engine._validation_grid_diagnostics(summary)
    grid = {
        "status": "ready",
        "backtest_id": 9,
        "strategy": "mainline_leader_pullback",
        "strategy_version": "0.1.0",
        "start_date": "2026-01-01",
        "end_date": "2026-03-01",
        "method": "full_resimulation_parameter_grid",
        "variant_count": 2,
        "param_space": {"min_entry_score": [64.0, 68.0]},
        "summary": summary,
        "diagnostics": diagnostics,
        "walk_forward": {
            "summary": {"fold_count": 1, "positive_test_ratio": 100.0},
            "diagnostics": [{"id": "walk_forward_positive_ratio", "status": "pass"}],
            "folds": [{"id": "fold_1", "test_return_pct": 3.0}],
        },
        "top_variants": rows[:1],
        "rows": rows,
        "limitations": ["日线限制"],
    }

    csv_content = engine._validation_grid_csv_content(grid)

    assert summary["positive_ratio"] == 50.0
    assert summary["base_variant_id"] == 1
    assert summary["base_out_sample_rank"] == 1
    assert {item["id"] for item in diagnostics} >= {"grid_positive_ratio", "base_out_sample_rank"}
    assert "## 参数网格摘要" in csv_content
    assert "## Walk Forward 汇总" in csv_content
    assert "## Walk Forward 折叠" in csv_content
    assert "## 全部参数组合" in csv_content
    assert "full_resimulation_parameter_grid" in csv_content


def test_backtest_walk_forward_selects_train_variant_then_scores_future_window() -> None:
    from alphaagent.server.services.backtest import engine

    dates = [date(2026, 1, 1) + timedelta(days=index) for index in range(100)]

    def equity_curve(train_return: float, test_return: float) -> list[dict[str, object]]:
        rows = []
        for index, trade_date in enumerate(dates):
            if index < 60:
                equity = 100_000 * (1 + train_return * index / 59)
            else:
                equity = 100_000 * (1 + train_return) * (1 + test_return * (index - 59) / 20)
            rows.append({"trade_date": trade_date, "total_equity": equity})
        return rows

    benchmark = []
    nav = 1.0
    for trade_date in dates:
        benchmark.append({"trade_date": trade_date, "nav": nav, "daily_return": 0.0, "member_count": 1})
        nav *= 1.001

    variant_runs = [
        {
            "variant_id": 1,
            "params": engine.BacktestParams(min_entry_score=64, stop_loss_pct=0.05, take_profit_pct=0.18, strict_entry=False),
            "equity": equity_curve(0.20, -0.03),
            "closed_trades": [{"exit_date": dates[70].isoformat(), "pnl": -100.0}],
        },
        {
            "variant_id": 2,
            "params": engine.BacktestParams(min_entry_score=68, stop_loss_pct=0.07, take_profit_pct=0.18, strict_entry=True),
            "equity": equity_curve(0.05, 0.04),
            "closed_trades": [{"exit_date": dates[70].isoformat(), "pnl": 200.0}],
        },
    ]

    analysis = engine._walk_forward_grid_analysis(variant_runs, benchmark, train_days=60, test_days=20, step_days=20)

    assert analysis["status"] == "ready"
    assert analysis["summary"]["fold_count"] == 2
    assert analysis["folds"][0]["selected_variant_id"] == 1
    assert analysis["folds"][0]["test_return_pct"] < 0
    assert {item["id"] for item in analysis["diagnostics"]} >= {"walk_forward_positive_ratio", "walk_forward_excess_ratio"}


def test_backtest_validation_grid_small_limit_includes_base_params() -> None:
    from alphaagent.server.services.backtest import engine

    base_params = engine.BacktestParams(
        min_entry_score=68.0,
        stop_loss_pct=0.07,
        take_profit_pct=0.18,
        strict_entry=True,
    )
    variants = engine._validation_param_variants(base_params, 3)

    assert len(variants) == 3
    assert any(engine._same_grid_params(item, base_params) for item in variants)


def test_backtest_validation_grid_reuses_minute_index(monkeypatch) -> None:
    from alphaagent.server.services.backtest import engine

    calls = {"minute_loads": 0}
    trading_days = [date(2026, 1, 1) + timedelta(days=index) for index in range(85)]
    bars_by_symbol = {"600000.SSE": _bars(85)}

    def fake_minute_index(session, vt_symbols, start, end):
        del session, vt_symbols, start, end
        calls["minute_loads"] += 1
        return {}

    def fake_simulate(session, params, bars_by_symbol_arg, trading_days_arg, stock_meta, score_cache=None, minute_index=None, score_context=None):
        del session, params, bars_by_symbol_arg, stock_meta, score_cache, score_context
        assert minute_index == {}
        return {
            "metrics": {
                "initial_cash": 100_000,
                "final_equity": 101_000,
                "total_return_pct": 1.0,
                "annual_return_pct": 3.0,
                "max_drawdown_pct": -1.0,
                "trade_count": 1,
                "win_rate": 1.0,
                "profit_factor": 2.0,
                "sharpe": 1.0,
            },
            "equity": [{"trade_date": item, "total_equity": 100_000 + index} for index, item in enumerate(trading_days_arg)],
            "trades": [],
            "orders": [],
        }

    monkeypatch.setattr(engine, "_load_minute_bar_index", fake_minute_index)
    monkeypatch.setattr(engine, "_simulate", fake_simulate)

    result = engine._run_validation_grid(
        session=None,
        backtest_id=9,
        base_params=engine.BacktestParams(intraday_entry=True),
        bars_by_symbol=bars_by_symbol,
        trading_days=trading_days,
        stock_meta={},
        max_variants=3,
    )

    assert result["status"] == "ready"
    assert result["variant_count"] == 3
    assert calls["minute_loads"] == 1


def test_financial_scores_from_context_respects_publish_date() -> None:
    from alphaagent.server.services.backtest import engine

    context = engine.ScoreContext(
        financial_rows_by_symbol={
            "600000.SSE": [
                {
                    "vt_symbol": "600000.SSE",
                    "report_date": "2026-03-31",
                    "publish_date": "2026-04-30",
                    "revenue_yoy": 30.0,
                    "net_profit_yoy": 40.0,
                    "operating_cash_flow": 10_000_000,
                    "cash_flow_quality": 2.0,
                },
                {
                    "vt_symbol": "600000.SSE",
                    "report_date": "2025-12-31",
                    "publish_date": "2026-03-31",
                    "revenue_yoy": 5.0,
                    "net_profit_yoy": 5.0,
                },
            ]
        }
    )

    before_publish = engine._financial_scores_from_context(context, date(2026, 4, 15))
    after_publish = engine._financial_scores_from_context(context, date(2026, 5, 1))

    assert before_publish["600000.SSE"] < after_publish["600000.SSE"]


def test_backtest_validation_grid_csv_endpoint_returns_download(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    monkeypatch.setattr(
        backtests,
        "backtest_validation_grid_csv",
        lambda backtest_id, max_variants: {
            "status": "ready",
            "filename": f"alphaagent_validation_grid_{backtest_id}.csv",
            "content": "\ufeff## 参数网格摘要\n",
        },
    )

    client = TestClient(create_app())
    response = client.get("/api/backtests/9/validation-grid.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "alphaagent_validation_grid_9.csv" in response.headers["content-disposition"]
    assert "## 参数网格摘要" in response.text


def test_backtest_csv_endpoint_returns_download(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    monkeypatch.setattr(
        backtests,
        "backtest_report_csv",
        lambda backtest_id, trade_limit: {
            "status": "ready",
            "filename": f"alphaagent_backtest_{backtest_id}.csv",
            "content": "\ufeff## 回测摘要\n",
        },
    )

    client = TestClient(create_app())
    response = client.get("/api/backtests/9/report.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "alphaagent_backtest_9.csv" in response.headers["content-disposition"]
    assert "## 回测摘要" in response.text


def test_backtest_api_parses_strict_minute_entry_params(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_run_backtest(params):
        captured["params"] = params
        return {"status": "ready", "backtest_id": 10, "metrics": {}, "trades": [], "start": "2026-01-01", "end": "2026-01-31"}

    monkeypatch.setattr(backtests, "run_backtest", fake_run_backtest)

    client = TestClient(create_app())
    response = client.post(
        "/api/backtests",
        json={
            "start": "2026-01-01",
            "intraday_entry": "true",
            "minute_entry_required": "true",
            "tail_entry_start": "14:35",
            "tail_entry_end": "14:55",
            "tail_entry_ma5_tolerance_pct": 0.8,
            "persist": False,
        },
    )

    assert response.status_code == 200
    assert captured["params"].intraday_entry is True
    assert captured["params"].minute_entry_required is True
    assert captured["params"].tail_entry_start == "14:35"
    assert captured["params"].tail_entry_end == "14:55"
    assert captured["params"].tail_entry_ma5_tolerance_pct == 0.8


def test_symbol_backtest_api_passes_single_symbol_and_returns_audit(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_run_backtest(params):
        captured["params"] = params
        return {"status": "ready", "backtest_id": 11, "metrics": {}, "trades": [], "start": "2026-01-01", "end": "2026-01-31"}

    def fake_audit(backtest_id, vt_symbol=None, limit=200):
        return {"status": "ready", "backtest_id": backtest_id, "vt_symbol": vt_symbol, "events": [], "orders": [], "trades": [], "limit": limit}

    monkeypatch.setattr(backtests, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(backtests, "backtest_audit", fake_audit)

    client = TestClient(create_app())
    response = client.post("/api/backtests/symbol", json={"vt_symbol": "600000.SSE", "start": "2026-01-01", "audit_limit": 88})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["backtest_id"] == 11
    assert data["audit"]["vt_symbol"] == "600000.SSE"
    assert data["audit"]["limit"] == 88
    assert captured["params"].symbols == ["600000.SSE"]
    assert captured["params"].max_symbols == 1
    assert captured["params"].max_positions == 1
    assert captured["params"].candidate_limit == 1
    assert captured["params"].persist is True


def test_backtest_audit_api_passes_symbol_filter(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_audit(backtest_id, vt_symbol=None, limit=200):
        captured.update({"backtest_id": backtest_id, "vt_symbol": vt_symbol, "limit": limit})
        return {"status": "ready", "backtest_id": backtest_id, "vt_symbol": vt_symbol, "events": [], "orders": [], "trades": []}

    monkeypatch.setattr(backtests, "backtest_audit", fake_audit)

    client = TestClient(create_app())
    response = client.get("/api/backtests/11/audit?vt_symbol=600000.SSE&limit=77")

    assert response.status_code == 200
    assert response.json()["data"]["vt_symbol"] == "600000.SSE"
    assert captured == {"backtest_id": 11, "vt_symbol": "600000.SSE", "limit": 77}


def test_backtest_trades_api_passes_pagination(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_trades(backtest_id, limit=500, offset=0, order="desc"):
        captured.update({"backtest_id": backtest_id, "limit": limit, "offset": offset, "order": order})
        return {"status": "ready", "backtest_id": backtest_id, "items": [], "limit": limit, "offset": offset, "total": 0, "has_more": False}

    monkeypatch.setattr(backtests, "backtest_trades", fake_trades)

    client = TestClient(create_app())
    response = client.get("/api/backtests/11/trades?limit=20&offset=40&order=desc")

    assert response.status_code == 200
    assert response.json()["data"]["offset"] == 40
    assert captured == {"backtest_id": 11, "limit": 20, "offset": 40, "order": "desc"}


def test_backtest_execution_quality_flags_minute_fallback_risk() -> None:
    from alphaagent.server.services.backtest import engine

    quality = engine._execution_quality_report(
        {"minute_tail_entry_count": 0, "daily_open_fallback_count": 10},
        {"buy_count": 10, "execution_modes": {"daily_next_open_fallback": 10}},
        {
            "stock_minute_bars": {"count": 0},
            "stock_daily_bars": {"count": 1000},
            "stock_financial_reports": {"count": 3},
        },
        {"coverage_pct": 25.0},
    )

    assert quality["status"] == "warning"
    assert quality["minute_tail_entry_ratio"] == 0.0
    assert quality["daily_open_fallback_ratio"] == 100.0
    assert any(item["id"] == "minute_tail_entry_coverage" and item["status"] == "warning" for item in quality["diagnostics"])


def test_data_sync_truthy_handles_string_params() -> None:
    from alphaagent.server.services import data_sync

    assert data_sync._truthy(True)
    assert data_sync._truthy("true")
    assert data_sync._truthy("1")
    assert not data_sync._truthy(False)
    assert not data_sync._truthy("false")


def test_financial_sync_runner_uses_missing_first_stock_selection(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    seen: list[tuple[int, bool]] = []

    def fake_rows(stock_limit: int, only_missing: bool):
        seen.append((stock_limit, only_missing))
        return []

    monkeypatch.setattr(data_sync, "_financial_sync_stock_rows", fake_rows)

    runner = data_sync.DataSyncRunner()
    result = runner._run_sync_stock_financial_quarterly({"stock_limit": 123, "only_missing": "true"})

    assert result["rows_read"] == 0
    assert seen == [(123, True)]


def test_quarterly_cash_flow_enrichment_maps_operating_cash_quality() -> None:
    from alphaagent.server.services import data_sync

    class FakeAdapter:
        def stock_cash_flow_sheet(self, symbol, exchange=None):
            assert symbol == "600000"
            assert exchange == "SSE"
            return {
                "items": [
                    {
                        "REPORT_DATE": "2026-03-31 00:00:00",
                        "NOTICE_DATE": "2026-04-30 00:00:00",
                        "NETCASH_OPERATE": 30_000_000,
                    }
                ]
            }

    items = [{"report_date": "2026-03-31 00:00:00", "net_profit": 10_000_000}]
    runner = data_sync.DataSyncRunner(adapter=FakeAdapter())

    runner._enrich_quarterly_with_cash_flow(items, "600000", "SSE")

    assert items[0]["publish_date"] == "2026-04-30 00:00:00"
    assert items[0]["operating_cash_flow"] == 30_000_000
    assert items[0]["cash_flow_quality"] == 3.0


def test_financial_report_upsert_persists_publish_and_cash_flow_fields(monkeypatch) -> None:
    from alphaagent.server.services import data_sync

    inserted: list[dict[str, object]] = []

    class FakeSelectResult:
        def first(self):
            return None

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            if text.startswith("INSERT INTO stock_financial_reports"):
                inserted.append(dict(statement.compile().params))
                return None
            return FakeSelectResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(data_sync, "session_scope", fake_session_scope)

    written = data_sync._upsert_stock_financial_reports(
        "600000",
        "SSE",
        [
            {
                "report_date": "2026-03-31 00:00:00",
                "publish_date": "2026-04-30 00:00:00",
                "revenue_qoq": 12.5,
                "net_profit_qoq": 20.0,
                "deducted_net_profit": 9_000_000,
                "operating_cash_flow": 30_000_000,
                "cash_flow_quality": 3.0,
            }
        ],
        "quarterly",
    )

    assert written == 1
    assert inserted[0]["publish_date"] == "2026-04-30 00:00:00"
    assert inserted[0]["operating_cash_flow"] == 30_000_000
    assert inserted[0]["cash_flow_quality"] == 3.0
    assert inserted[0]["deducted_net_profit"] == 9_000_000


def test_simulation_auto_group_item_upsert_records_cost_and_reason() -> None:
    from alphaagent.server.services.simulation import account

    calls: list[object] = []

    class FakeScalarNone:
        def scalar_one_or_none(self):
            return None

    class FakeScalarGroup:
        def scalar_one(self):
            return 9

    class FakeSession:
        def execute(self, statement):
            text = str(statement)
            calls.append(statement)
            if text.startswith("SELECT portfolio_groups.id"):
                return FakeScalarNone()
            if text.startswith("INSERT INTO portfolio_groups"):
                return FakeScalarGroup()
            if text.startswith("SELECT portfolio_group_items.vt_symbol"):
                return FakeScalarNone()
            return FakeScalarGroup()

    written = account._upsert_simulation_auto_group_item(
        FakeSession(),
        "600000.SSE",
        "浦发银行",
        "mainline_leader_pullback",
        "quant recommendation #1",
        {
            "trade_date": date(2026, 6, 11),
            "strategy_version": "0.1.0",
            "total_score": 72.5,
        },
        10.25,
        1000,
    )

    insert_params = [
        dict(statement.compile().params)
        for statement in calls
        if str(statement).startswith("INSERT INTO portfolio_group_items")
    ][0]
    assert written == 1
    assert insert_params["group_id"] == 9
    assert insert_params["source"] == "simulation_auto"
    assert "cost=10.2500" in insert_params["reason"]
    assert "volume=1000" in insert_params["reason"]


def test_holding_trade_summary_exposes_latest_buy_and_sell() -> None:
    from datetime import datetime, timezone

    from alphaagent.server.services.portfolio import groups

    class FakeResult:
        def __init__(self, row):
            self.row = row

        def mappings(self):
            return self

        def first(self):
            return self.row

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def execute(self, statement):
            del statement
            self.calls += 1
            if self.calls == 1:
                return FakeResult(
                    {
                        "trade_time": datetime(2026, 6, 11, 14, 56, tzinfo=timezone.utc),
                        "price": 10.25,
                        "volume": 1000,
                        "amount": 10_250,
                        "order_reason": "quant recommendation #1",
                        "recommendation_id": 7,
                    }
                )
            return FakeResult(
                {
                    "trade_time": datetime(2026, 6, 12, 10, 1, tzinfo=timezone.utc),
                    "price": 11.0,
                    "volume": 500,
                    "amount": 5_500,
                    "pnl": 360.0,
                }
            )

    summary = groups._position_trade_summary(FakeSession(), 1, "600000.SSE")

    assert summary["last_buy_price"] == 10.25
    assert summary["last_buy_reason"] == "quant recommendation #1"
    assert summary["recommendation_id"] == 7
    assert summary["last_sell_price"] == 11.0
    assert summary["last_sell_pnl"] == 360.0


def test_vnpy_status_reports_core_without_claiming_a_share_gateway() -> None:
    from alphaagent.server.services.vnpy_integration.status import vnpy_status

    status = vnpy_status()

    assert status["product"] == "AlphaAgent"
    assert status["vnpy_package_name"] == "vnpy"
    assert status["launcher"]["registered_gateways"] == ["CtpGateway"]
    assert "vnpy_a_share_gateway" in status["capabilities"]
    assert status["launcher"]["a_share_gateway_registered"] is False
    assert "integration_plan" in status
    assert "alphaagent_local_vnpy_bar_adapter" in status["capabilities"]


def test_vnpy_local_data_builds_history_request_and_bardata() -> None:
    from alphaagent.server.services.vnpy_integration import local_data

    request = local_data.history_request("600000.SSE", date(2026, 1, 1), date(2026, 1, 31))
    bar = local_data._row_to_bar(
        {
            "trade_date": date(2026, 1, 2),
            "open_price": 10.0,
            "high_price": 10.5,
            "low_price": 9.8,
            "close_price": 10.2,
            "volume": 1_000_000,
            "turnover": 10_200_000,
        },
        request,
    )

    assert request.vt_symbol == "600000.SSE"
    assert request.interval.value == "d"
    assert bar.vt_symbol == "600000.SSE"
    assert bar.gateway_name == "ALPHAAGENT_LOCAL"
    assert bar.close_price == 10.2


def test_vnpy_database_import_loads_minute_bars(monkeypatch) -> None:
    from datetime import datetime

    from vnpy.trader.constant import Exchange, Interval
    from vnpy.trader.object import BarData

    from alphaagent.server.services.vnpy_integration import database_import

    class FakeDatabase:
        @staticmethod
        def load_bar_data(symbol, exchange, interval, start, end):
            assert symbol == "600000"
            assert exchange == Exchange.SSE
            assert interval == Interval.MINUTE
            assert start.date() == date(2026, 1, 8)
            assert end.date() == date(2026, 1, 8)
            return [
                BarData(
                    gateway_name="VNDB",
                    symbol=symbol,
                    exchange=exchange,
                    datetime=datetime(2026, 1, 8, 14, 56),
                    interval=interval,
                    open_price=10,
                    high_price=10.2,
                    low_price=9.9,
                    close_price=10.1,
                    volume=1200,
                    turnover=12120,
                )
            ]

    calls = []
    monkeypatch.setattr(database_import, "is_database_configured", lambda: True)
    monkeypatch.setattr(database_import, "get_database", lambda: FakeDatabase())
    monkeypatch.setattr(database_import, "_upsert_minute_bars", lambda symbol, exchange, items, interval, source: calls.append((symbol, exchange, interval, source, items[0]["close"])) or len(items))

    result = database_import.import_vnpy_minute_bars("600000.SSE", date(2026, 1, 8), date(2026, 1, 8))

    assert result["status"] == "ready"
    assert result["rows_read"] == 1
    assert result["rows_written"] == 1
    assert calls == [("600000", "SSE", "1m", "vnpy_database", 10.1)]


def test_vnpy_database_import_dry_run_does_not_upsert(monkeypatch) -> None:
    from alphaagent.server.services.vnpy_integration import database_import

    class FakeDatabase:
        @staticmethod
        def load_bar_data(symbol, exchange, interval, start, end):
            del symbol, exchange, interval, start, end
            return []

    monkeypatch.setattr(database_import, "is_database_configured", lambda: True)
    monkeypatch.setattr(database_import, "get_database", lambda: FakeDatabase())
    monkeypatch.setattr(database_import, "_upsert_minute_bars", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not write")))

    result = database_import.import_vnpy_minute_bars("600000.SSE", "2026-01-08", dry_run=True)

    assert result["status"] == "empty"
    assert result["rows_written"] == 0


def test_vnpy_database_imports_gap_minute_bars(monkeypatch) -> None:
    from datetime import datetime

    from vnpy.trader.constant import Exchange, Interval
    from vnpy.trader.object import BarData

    from alphaagent.server.services.vnpy_integration import database_import

    seen_windows = []

    class FakeDatabase:
        @staticmethod
        def load_bar_data(symbol, exchange, interval, start, end):
            seen_windows.append((symbol, exchange, interval, start.strftime("%H:%M"), end.strftime("%H:%M")))
            return [
                BarData(
                    gateway_name="VNDB",
                    symbol=symbol,
                    exchange=exchange,
                    datetime=datetime(2026, 1, 8, 14, 56),
                    interval=interval,
                    open_price=10,
                    high_price=10.2,
                    low_price=9.9,
                    close_price=10.1,
                    volume=1200,
                    turnover=12120,
                )
            ]

    writes = []
    gap_csv = "trade_date,vt_symbol,reference_date,window,ma5\n2026-01-08,600000.SSE,2026-01-07,14:30-14:57,10.0\n"
    monkeypatch.setattr(database_import, "is_database_configured", lambda: True)
    monkeypatch.setattr(database_import, "get_database", lambda: FakeDatabase())
    monkeypatch.setattr(
        database_import,
        "_upsert_minute_bars",
        lambda symbol, exchange, items, interval, source: writes.append((symbol, exchange, len(items), interval, source)) or len(items),
    )
    monkeypatch.setattr(
        database_import,
        "_audit_minute_gap_requirements",
        lambda requirements, **kwargs: {
            "status": "ready",
            "gap_count": len(requirements["items"]),
            "covered_count": len(requirements["items"]),
            "missing_count": 0,
            "coverage_pct": 100.0,
        },
    )

    result = database_import.import_vnpy_minute_bars_for_gaps(gap_csv_text=gap_csv, dry_run=False)

    assert result["status"] == "ready"
    assert result["gap_count"] == 1
    assert result["rows_read"] == 1
    assert result["rows_written"] == 1
    assert seen_windows == [("600000", Exchange.SSE, Interval.MINUTE, "14:30", "14:57")]
    assert writes == [("600000", "SSE", 1, "1m", "vnpy_database_gap")]
    assert result["audit_after"]["status"] == "ready"


def test_vnpy_gap_import_reports_empty_when_database_has_no_bars(monkeypatch) -> None:
    from alphaagent.server.services.vnpy_integration import database_import

    class FakeDatabase:
        @staticmethod
        def load_bar_data(symbol, exchange, interval, start, end):
            del symbol, exchange, interval, start, end
            return []

    gap_csv = "trade_date,vt_symbol,reference_date,window,ma5\n2026-01-08,600000.SSE,2026-01-07,14:30-14:57,10.0\n"
    monkeypatch.setattr(database_import, "is_database_configured", lambda: True)
    monkeypatch.setattr(database_import, "get_database", lambda: FakeDatabase())
    monkeypatch.setattr(
        database_import,
        "_audit_minute_gap_requirements",
        lambda requirements, **kwargs: {
            "status": "incomplete",
            "gap_count": len(requirements["items"]),
            "covered_count": 0,
            "missing_count": len(requirements["items"]),
            "coverage_pct": 0.0,
        },
    )

    result = database_import.import_vnpy_minute_bars_for_gaps(gap_csv_text=gap_csv, dry_run=True)

    assert result["status"] == "empty"
    assert result["rows_read"] == 0
    assert result["empty_request_count"] == 1
    assert result["audit_after"]["status"] == "incomplete"


def test_vnpy_import_minute_bars_endpoint(monkeypatch) -> None:
    from alphaagent.server.api import vnpy_local_data

    captured = {}

    def fake_import(vt_symbol, start, end, interval, dry_run):
        captured.update({"vt_symbol": vt_symbol, "start": start, "end": end, "interval": interval, "dry_run": dry_run})
        return {"status": "ready", "rows_read": 1, "rows_written": 0}

    monkeypatch.setattr(vnpy_local_data, "import_vnpy_minute_bars", fake_import)

    client = TestClient(create_app())
    response = client.post(
        "/api/vnpy/import-minute-bars",
        json={"vt_symbol": "600000.SSE", "start": "2026-01-08", "end": "2026-01-08", "interval": "1m", "dry_run": True},
    )

    assert response.status_code == 200
    assert captured == {"vt_symbol": "600000.SSE", "start": "2026-01-08", "end": "2026-01-08", "interval": "1m", "dry_run": True}
    assert response.json()["data"]["status"] == "ready"


def test_vnpy_import_gap_minute_bars_endpoint(monkeypatch) -> None:
    from alphaagent.server.api import vnpy_local_data

    captured = {}

    def fake_import(**kwargs):
        captured.update(kwargs)
        return {"status": "ready", "rows_read": 2, "rows_written": 0}

    monkeypatch.setattr(vnpy_local_data, "import_vnpy_minute_bars_for_gaps", fake_import)

    client = TestClient(create_app())
    response = client.post(
        "/api/vnpy/import-minute-bars/gaps",
        json={
            "gap_file_path": "memory/06_backtests/gaps.csv",
            "interval": "1m",
            "tail_entry_start": "14:30",
            "tail_entry_end": "14:57",
            "dry_run": True,
            "max_gaps": 50,
        },
    )

    assert response.status_code == 200
    assert captured == {
        "gap_csv_text": "",
        "gap_file_path": "memory/06_backtests/gaps.csv",
        "interval": "1m",
        "tail_entry_start": "14:30",
        "tail_entry_end": "14:57",
        "dry_run": True,
        "max_gaps": 50,
    }
    assert response.json()["data"]["status"] == "ready"


def test_vnpy_local_bars_endpoint_rejects_invalid_symbol() -> None:
    client = TestClient(create_app())
    response = client.get("/api/vnpy/local-bars?vt_symbol=BAD&start=2026-01-01")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_VT_SYMBOL"


def test_tushare_gap_import_requires_token(monkeypatch) -> None:
    from types import SimpleNamespace

    from alphaagent.server.services.data_providers import tushare_minute_import

    monkeypatch.setattr(tushare_minute_import, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        tushare_minute_import,
        "get_settings",
        lambda: SimpleNamespace(tushare_token="", tushare_api_url="https://api.tushare.pro", tushare_timeout_seconds=1),
    )

    result = tushare_minute_import.import_tushare_minute_bars_for_gaps(gap_csv_text="trade_date,vt_symbol\n2026-01-08,600000.SSE\n")

    assert result["status"] == "unavailable"
    assert "TUSHARE_TOKEN" in result["message"]


def test_minute_gap_vendor_manifest_builds_provider_rows() -> None:
    from alphaagent.server.services import data_sync

    gap_csv = (
        "trade_date,vt_symbol,reference_date,window,ma5\n"
        "2026-01-08,600000.SSE,2026-01-07,14:30-14:57,10.0\n"
        "2026-01-08,600000.SSE,2026-01-07,14:30-14:57,10.0\n"
        "2026-01-09,000001.SZSE,2026-01-08,14:30-14:57,12.0\n"
    )

    manifest = data_sync.minute_gap_vendor_manifest(gap_csv, tail_entry_start="14:30", tail_entry_end="14:57")
    csv_text = data_sync.minute_gap_vendor_manifest_csv(gap_csv, tail_entry_start="14:30", tail_entry_end="14:57")

    assert manifest["status"] == "ready"
    assert manifest["request_count"] == 2
    assert manifest["symbol_count"] == 2
    assert manifest["date_count"] == 2
    assert manifest["sample_rows"][0]["tushare_ts_code"] == "600000.SH"
    assert "000001.SZ" in csv_text
    assert "vt_symbol,bar_time,open,high,low,close,volume,turnover" in csv_text


def test_minute_gap_vendor_manifest_endpoint(monkeypatch) -> None:
    from alphaagent.server.api import data_sync

    monkeypatch.setattr(
        data_sync.service,
        "minute_gap_vendor_manifest",
        lambda *args, **kwargs: {"status": "ready", "request_count": 1, "symbol_count": 1, "date_count": 1},
    )
    monkeypatch.setattr(data_sync.service, "minute_gap_vendor_manifest_csv", lambda *args, **kwargs: "\ufeffvt_symbol\n600000.SSE\n")

    client = TestClient(create_app())
    response = client.post("/api/data-sync/imports/minute-bars/vendor-manifest", json={"gap_csv_text": "x"})
    csv_response = client.post("/api/data-sync/imports/minute-bars/vendor-manifest.csv", json={"gap_csv_text": "x"})

    assert response.status_code == 200
    assert response.json()["data"]["request_count"] == 1
    assert csv_response.status_code == 200
    assert "600000.SSE" in csv_response.text


def test_tushare_gap_import_filters_and_upserts(monkeypatch) -> None:
    from types import SimpleNamespace

    from alphaagent.server.services.data_providers import tushare_minute_import

    class FakeResponse:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "code": 0,
                "data": {
                    "fields": ["ts_code", "trade_time", "open", "close", "high", "low", "vol", "amount"],
                    "items": [
                        ["600000.SH", "2026-01-08 14:56:00", 10, 10.1, 10.2, 9.9, 1000, 10100],
                        ["600000.SH", "2026-06-11 14:56:00", 11, 11.1, 11.2, 10.9, 1000, 11100],
                    ],
                },
            }

    posted = []
    writes = []
    gap_csv = "trade_date,vt_symbol,reference_date,window,ma5\n2026-01-08,600000.SSE,2026-01-07,14:30-14:57,10.0\n"
    monkeypatch.setattr(tushare_minute_import, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        tushare_minute_import,
        "get_settings",
        lambda: SimpleNamespace(tushare_token="token", tushare_api_url="https://api.tushare.pro", tushare_timeout_seconds=1),
    )
    monkeypatch.setattr(
        tushare_minute_import.requests,
        "post",
        lambda url, json, timeout: posted.append((url, json, timeout)) or FakeResponse(),
    )
    monkeypatch.setattr(
        tushare_minute_import,
        "_upsert_minute_bars",
        lambda symbol, exchange, items, interval, source: writes.append((symbol, exchange, len(items), interval, source, items[0]["close"])) or len(items),
    )
    monkeypatch.setattr(
        tushare_minute_import,
        "_audit_minute_gap_requirements",
        lambda requirements, **kwargs: {
            "status": "ready",
            "gap_count": len(requirements["items"]),
            "covered_count": len(requirements["items"]),
            "missing_count": 0,
            "coverage_pct": 100.0,
        },
    )

    result = tushare_minute_import.import_tushare_minute_bars_for_gaps(gap_csv_text=gap_csv, dry_run=False)

    assert result["status"] == "ready"
    assert result["rows_read"] == 1
    assert result["wrong_date_row_count"] == 1
    assert result["rows_written"] == 1
    assert writes == [("600000", "SSE", 1, "1m", "tushare_stk_mins", 10.1)]
    assert posted[0][1]["api_name"] == "stk_mins"
    assert posted[0][1]["params"]["ts_code"] == "600000.SH"
    assert posted[0][1]["params"]["start_date"] == "2026-01-08 14:30:00"


def test_tdx_gap_import_writes_real_minute_rows(monkeypatch) -> None:
    from alphaagent.server.services.data_providers import tdx_minute_import

    class FakeApi:
        def get_security_bars(self, category, market, symbol, start, count):
            assert category == 8
            assert market == 1
            assert symbol == "600000"
            assert start == 0
            assert count == 800
            return [
                {
                    "datetime": "2026-01-08 14:30",
                    "open": 10,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "vol": 1200,
                    "amount": 12120,
                },
                {
                    "datetime": "2026-01-08 14:57",
                    "open": 10.1,
                    "high": 10.3,
                    "low": 10.0,
                    "close": 10.2,
                    "vol": 1300,
                    "amount": 13260,
                },
            ]

        @staticmethod
        def disconnect():
            return None

    writes = []
    gap_csv = "trade_date,vt_symbol,reference_date,window,ma5\n2026-01-08,600000.SSE,2026-01-07,14:30-14:57,10.0\n"
    monkeypatch.setattr(tdx_minute_import, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        tdx_minute_import,
        "_connect_tdx",
        lambda timeout_seconds: (FakeApi(), {"name": "fake", "ip": "127.0.0.1", "port": 7709}),
    )
    monkeypatch.setattr(
        tdx_minute_import,
        "_upsert_minute_bars",
        lambda symbol, exchange, items, interval, source: writes.append((symbol, exchange, len(items), interval, source)) or len(items),
    )
    monkeypatch.setattr(
        tdx_minute_import,
        "_audit_minute_gap_requirements",
        lambda requirements, **kwargs: {
            "status": "ready",
            "gap_count": len(requirements["items"]),
            "covered_count": len(requirements["items"]),
            "missing_count": 0,
            "coverage_pct": 100.0,
        },
    )

    result = tdx_minute_import.import_tdx_minute_bars_for_gaps(gap_csv_text=gap_csv, dry_run=False, max_pages_per_symbol=1)

    assert result["status"] == "ready"
    assert result["rows_read"] == 2
    assert result["rows_written"] == 2
    assert result["preview_covered_gap_count"] == 1
    assert writes == [("600000", "SSE", 2, "1m", "tdx_public_hq")]
    assert result["audit_after"]["status"] == "ready"


def test_tdx_gap_import_endpoint(monkeypatch) -> None:
    from alphaagent.server.api import data_sync

    captured = {}

    def fake_import(**kwargs):
        captured.update(kwargs)
        return {"status": "ready", "rows_read": 1, "rows_written": 0}

    monkeypatch.setattr(data_sync, "import_tdx_minute_bars_for_gaps", fake_import)

    client = TestClient(create_app())
    response = client.post(
        "/api/data-sync/imports/minute-bars/tdx-gaps",
        json={
            "gap_file_path": "memory/06_backtests/gaps.csv",
            "interval": "1m",
            "tail_entry_start": "14:30",
            "tail_entry_end": "14:57",
            "dry_run": True,
            "max_gaps": 12,
            "max_pages_per_symbol": 3,
            "timeout_seconds": 1.5,
        },
    )

    assert response.status_code == 200
    assert captured == {
        "gap_csv_text": "",
        "gap_file_path": "memory/06_backtests/gaps.csv",
        "interval": "1m",
        "tail_entry_start": "14:30",
        "tail_entry_end": "14:57",
        "dry_run": True,
        "max_gaps": 12,
        "max_pages_per_symbol": 3,
        "timeout_seconds": 1.5,
    }
    assert response.json()["data"]["status"] == "ready"


def test_backtest_minute_gap_csv_content_uses_rejected_orders() -> None:
    from datetime import date

    from alphaagent.server.services.backtest import engine

    content, gap_count = engine._minute_gap_csv_content(
        [
            {
                "trade_date": date(2026, 5, 11),
                "vt_symbol": "688668.SSE",
                "raw": {
                    "mode": "minute_tail_ma5_required",
                    "reference_date": "2026-05-08",
                    "window": "14:30-14:57",
                    "ma5": 220.918,
                    "minute_bar_count": 0,
                    "reason": "tail_entry_not_triggered",
                },
            },
            {
                "trade_date": date(2026, 5, 11),
                "vt_symbol": "688668.SSE",
                "raw": {
                    "mode": "minute_tail_ma5_required",
                    "reference_date": "2026-05-08",
                    "window": "14:30-14:57",
                    "ma5": 220.918,
                },
            },
        ]
    )

    assert gap_count == 1
    assert "trade_date,vt_symbol,reference_date,window,ma5,minute_bar_count,missing_reason" in content
    assert "2026-05-11,688668.SSE,2026-05-08,14:30-14:57,220.918,0,tail_entry_not_triggered" in content


def test_tushare_gap_import_endpoint(monkeypatch) -> None:
    from alphaagent.server.api import data_sync

    captured = {}

    def fake_import(**kwargs):
        captured.update(kwargs)
        return {"status": "unavailable", "message": "TUSHARE_TOKEN not configured"}

    monkeypatch.setattr(data_sync, "import_tushare_minute_bars_for_gaps", fake_import)

    client = TestClient(create_app())
    response = client.post(
        "/api/data-sync/imports/minute-bars/tushare-gaps",
        json={
            "gap_file_path": "memory/06_backtests/gaps.csv",
            "interval": "1m",
            "tail_entry_start": "14:30",
            "tail_entry_end": "14:57",
            "dry_run": True,
            "max_gaps": 20,
        },
    )

    assert response.status_code == 200
    assert captured == {
        "gap_csv_text": "",
        "gap_file_path": "memory/06_backtests/gaps.csv",
        "interval": "1m",
        "tail_entry_start": "14:30",
        "tail_entry_end": "14:57",
        "dry_run": True,
        "max_gaps": 20,
    }
    assert response.json()["data"]["status"] == "unavailable"


def test_strict_minute_pipeline_blocks_when_gap_audit_incomplete(monkeypatch) -> None:
    from alphaagent.server.services.backtest import strict_pipeline
    from alphaagent.server.services.backtest.engine import BacktestParams

    monkeypatch.setattr(
        strict_pipeline,
        "_audit_gap_coverage",
        lambda **kwargs: {"status": "incomplete", "gap_count": 3, "covered_count": 1, "missing_count": 2, "coverage_pct": 33.3333},
    )
    monkeypatch.setattr(strict_pipeline, "run_backtest", lambda params: (_ for _ in ()).throw(AssertionError("should not run")))

    result = strict_pipeline.run_strict_minute_backtest_pipeline(BacktestParams(max_symbols=20), gap_csv_text="x")

    assert result["status"] == "blocked_by_minute_gaps"
    assert result["audit"]["missing_count"] == 2
    assert result["params"]["minute_entry_required"] is True
    assert result["params"]["max_symbols"] == 1500


def test_strict_minute_pipeline_runs_when_gap_audit_ready(monkeypatch) -> None:
    from alphaagent.server.services.backtest import strict_pipeline
    from alphaagent.server.services.backtest.engine import BacktestParams

    captured = {}

    def fake_run(params):
        captured["params"] = params
        return {"status": "ready", "backtest_id": 99, "metrics": {"total_return_pct": 1.2}, "start": "2026-01-01", "end": "2026-02-01"}

    monkeypatch.setattr(strict_pipeline, "_audit_gap_coverage", lambda **kwargs: {"status": "ready", "gap_count": 1, "covered_count": 1, "missing_count": 0, "coverage_pct": 100.0})
    monkeypatch.setattr(strict_pipeline, "run_backtest", fake_run)
    monkeypatch.setattr(strict_pipeline, "backtest_report", lambda backtest_id, trade_limit: {"status": "ready", "backtest_id": backtest_id, "metrics": {"total_return_pct": 1.2}})
    monkeypatch.setattr(strict_pipeline, "backtest_report_csv", lambda backtest_id, trade_limit: {"status": "ready", "filename": f"alphaagent_backtest_{backtest_id}.csv"})

    result = strict_pipeline.run_strict_minute_backtest_pipeline(BacktestParams(max_symbols=20), gap_csv_text="x")

    assert result["status"] == "ready"
    assert result["backtest"]["backtest_id"] == 99
    assert result["csv"]["filename"] == "alphaagent_backtest_99.csv"
    assert captured["params"].minute_entry_required is True
    assert captured["params"].intraday_entry is True
    assert captured["params"].persist is True


def test_strict_minute_pipeline_endpoint(monkeypatch) -> None:
    from alphaagent.server.api import backtests

    captured = {}

    def fake_pipeline(params, **kwargs):
        captured["params"] = params
        captured.update(kwargs)
        return {"status": "blocked_by_minute_gaps", "audit": {"status": "incomplete"}}

    monkeypatch.setattr(backtests, "run_strict_minute_backtest_pipeline", fake_pipeline)

    client = TestClient(create_app())
    response = client.post(
        "/api/backtests/strict-minute-pipeline",
        json={
            "start": "2026-01-01",
            "max_symbols": 1500,
            "gap_file_path": "memory/06_backtests/gaps.csv",
            "tail_entry_start": "14:30",
            "tail_entry_end": "14:57",
            "trade_limit": 12,
        },
    )

    assert response.status_code == 200
    assert captured["gap_file_path"] == "memory/06_backtests/gaps.csv"
    assert captured["trade_limit"] == 12
    assert captured["params"].start.isoformat() == "2026-01-01"
    assert response.json()["data"]["status"] == "blocked_by_minute_gaps"
