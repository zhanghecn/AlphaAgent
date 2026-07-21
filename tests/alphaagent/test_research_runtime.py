from __future__ import annotations

import pytest

from alphaagent.server.services.research_runtime import require_research_runtime


def test_container_research_requires_dedicated_database_identity() -> None:
    with pytest.raises(RuntimeError, match="alphaagent-research"):
        require_research_runtime(
            environ={"PGOPTIONS": "-c application_name=alphaagent-api"},
            containerized=True,
        )


def test_dedicated_research_container_passes_runtime_guard() -> None:
    require_research_runtime(
        environ={
            "PGOPTIONS": (
                "-c application_name=alphaagent-research "
                "-c max_parallel_workers_per_gather=0"
            )
        },
        containerized=True,
    )


def test_host_research_does_not_require_compose_identity() -> None:
    require_research_runtime(environ={}, containerized=False)
