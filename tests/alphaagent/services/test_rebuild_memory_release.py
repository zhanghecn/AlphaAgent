"""全量回放内存释放:重算结束(含失败)必须 gc+malloc_trim,归还 OS。

实测(worker 容器,2026-10-29):build_events 峰值 7584MiB,del+gc 后 1789MiB,
malloc_trim 后 176MiB——不 trim 时 worker 常驻 2.7GiB。
"""

import pytest

from alphaagent.server.services.fanbao import service as fbb_service
from alphaagent.server.services.high_relay import service as hpr_service


@pytest.mark.parametrize("service", [hpr_service, fbb_service])
def test_run_backtest_sync_releases_rebuild_memory(monkeypatch, service) -> None:
    calls: list[int] = []
    monkeypatch.setattr(service, "_execute_rebuild", lambda run_id: {"summary": {}})
    monkeypatch.setattr(service.repository, "create_rebuild_run", lambda *a, **k: 1)
    monkeypatch.setattr(service, "release_rebuild_memory", lambda: calls.append(1))

    service.run_backtest_sync()

    assert calls == [1]


@pytest.mark.parametrize("service", [hpr_service, fbb_service])
def test_run_backtest_sync_releases_memory_on_failure(monkeypatch, service) -> None:
    def boom(run_id: int) -> None:
        raise RuntimeError("rebuild failed")

    calls: list[int] = []
    monkeypatch.setattr(service, "_execute_rebuild", boom)
    monkeypatch.setattr(service.repository, "create_rebuild_run", lambda *a, **k: 1)
    monkeypatch.setattr(service, "release_rebuild_memory", lambda: calls.append(1))

    with pytest.raises(RuntimeError):
        service.run_backtest_sync()

    assert calls == [1]
