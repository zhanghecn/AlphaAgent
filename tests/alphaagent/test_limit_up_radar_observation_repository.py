import json
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from alphaagent.server.db import schema
from alphaagent.server.services.limit_up import radar_observation_repository as repo


def test_compact_radar_tables_are_registered() -> None:
    assert "limit_up_radar_frames" in schema.metadata.tables
    assert "limit_up_radar_observations" in schema.metadata.tables


def test_radar_retention_keeps_ninety_trade_days() -> None:
    start = date(2026, 1, 1)
    dates = [start + timedelta(days=index) for index in range(100)]

    assert repo.retention_cutoff(dates, retain_trade_days=90) == sorted(dates)[-90]


def test_projection_drops_large_nested_payloads() -> None:
    row = repo.project_observation(
        _candidate("600001.SSE"),
        formal_signal=None,
        early_signal={"action": "buy_now", "entry_kind": "momentum"},
    )

    assert row["vt_symbol"] == "600001.SSE"
    assert row["early_action"] == "buy_now"
    assert "financial_snapshot" not in row
    assert "raw" not in row


def test_two_hundred_projected_candidates_stay_below_size_guard() -> None:
    rows = [
        repo.project_observation(
            _candidate(f"{600000 + index:06d}.SSE"),
            formal_signal=None,
            early_signal={"action": "pass", "entry_kind": "none"},
        )
        for index in range(200)
    ]

    encoded = json.dumps(rows, ensure_ascii=True, separators=(",", ":")).encode()
    assert len(encoded) < 300_000


def test_fill_followup_keeps_a_signaled_stock_after_it_falls_below_three_percent() -> None:
    signal = repo.project_observation(
        _candidate("600001.SSE"),
        formal_signal=None,
        early_signal={"action": "buy_now", "entry_kind": "momentum"},
    )
    signal["captured_at"] = "2026-07-20T10:05:00+08:00"
    quote = {
        "vt_symbol": "600001.SSE",
        "name": "测试股份",
        "last_price": 10.25,
        "change_pct": 2.5,
    }

    rows = repo.build_fill_followup_observations(
        [signal],
        [quote],
        quote_observed_at=datetime.fromisoformat(
            "2026-07-20T10:05:25+08:00"
        ),
        current_observation_symbols=set(),
    )

    assert len(rows) == 1
    assert rows[0]["vt_symbol"] == "600001.SSE"
    assert rows[0]["last_price"] == 10.25
    assert rows[0]["change_pct"] == 2.5
    assert rows[0]["capture_state"] == "fill_followup"
    assert rows[0]["formal_action"] == "pass"
    assert rows[0]["early_action"] == "pass"


def test_fill_followup_rejects_stale_late_and_cross_window_quotes() -> None:
    signal = repo.project_observation(
        _candidate("600001.SSE"),
        formal_signal=None,
        early_signal={"action": "buy_now", "entry_kind": "momentum"},
    )
    quote = {
        "vt_symbol": "600001.SSE",
        "last_price": 10.25,
        "change_pct": 2.5,
    }

    for signal_at, quote_at in (
        ("2026-07-20T10:05:00+08:00", "2026-07-20T10:05:19+08:00"),
        ("2026-07-20T10:05:00+08:00", "2026-07-20T10:06:01+08:00"),
        ("2026-07-20T14:29:45+08:00", "2026-07-20T14:30:05+08:00"),
    ):
        signal["captured_at"] = signal_at
        rows = repo.build_fill_followup_observations(
            [signal],
            [quote],
            quote_observed_at=datetime.fromisoformat(quote_at),
            current_observation_symbols=set(),
        )
        assert rows == []


def test_recent_signal_context_keeps_the_earliest_buy_frame(monkeypatch) -> None:
    class Result:
        def mappings(self):
            return self

        def all(self):
            return [
                {
                    "vt_symbol": "600001.SSE",
                    "captured_at": datetime.fromisoformat(
                        "2026-07-20T10:05:00+08:00"
                    ),
                },
                {
                    "vt_symbol": "600001.SSE",
                    "captured_at": datetime.fromisoformat(
                        "2026-07-20T10:05:15+08:00"
                    ),
                },
            ]

    class Session:
        def execute(self, _statement):
            return Result()

    @contextmanager
    def fake_session_scope():
        yield Session()

    monkeypatch.setattr(repo, "session_scope", fake_session_scope)

    rows = repo.load_recent_signal_observations(
        datetime.fromisoformat("2026-07-20T10:05:30+08:00")
    )

    assert len(rows) == 1
    assert rows[0]["captured_at"].isoformat() == "2026-07-20T10:05:00+08:00"


def test_frame_and_observations_use_one_transaction(monkeypatch) -> None:
    session = _InsertSession()

    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(repo, "session_scope", fake_session_scope)
    monkeypatch.setattr(repo, "_prune_once_for_trade_date", lambda _date: None)
    observation = repo.project_observation(
        _candidate("600001.SSE"),
        formal_signal=None,
        early_signal={"action": "pass", "entry_kind": "none"},
    )

    result = repo.save_frame(
        {
            "trade_date": "2026-07-20",
            "captured_at": datetime(
                2026,
                7,
                20,
                10,
                5,
                tzinfo=ZoneInfo("Asia/Shanghai"),
            ),
            "strategy_version": "limit-up-live-v15",
            "source": "test",
            "source_updated_at": "2026-07-20T10:05:00+08:00",
            "data_quality": {"status": "ready", "is_stale": False},
        },
        [observation],
    )

    assert result["frame_id"] == 101
    assert len(session.statements) == 2
    assert all(statement.is_insert for statement in session.statements)


class _ScalarResult:
    def scalar_one(self) -> int:
        return 101


class _InsertSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    def execute(self, statement):
        self.statements.append(statement)
        return _ScalarResult()


def _candidate(symbol: str) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "name": "测试股份",
        "change_pct": 3.6,
        "last_price": 10.36,
        "previous_close": 10.0,
        "limit_price": 11.0,
        "state": "pre_radar",
        "board_lane": "first_board",
        "lane_support_score": 61.0,
        "lane_entry_quality_score": 65.0,
        "concept_id": "BK0877",
        "concept_state": "launch",
        "concept_strength_score": 82.0,
        "concept_leader_rank": 2,
        "concept_strong_5_count": 3,
        "sector_id": "industry:通信",
        "sector_heat": 68.0,
        "sector_touch_count": 4,
        "d1_money_effect_sample_count": 8,
        "historical_win_rate": 42.5,
        "lane_blockers": [],
        "financial_snapshot": {"large": "payload" * 1000},
        "raw": {"large": "payload" * 1000},
    }
