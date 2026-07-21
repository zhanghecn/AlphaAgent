"""Runtime guardrails for CPU-intensive offline research commands."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path


def require_research_runtime(
    *,
    environ: Mapping[str, str] | None = None,
    containerized: bool | None = None,
) -> None:
    """Reject heavy research launched through the always-on API container."""

    values = os.environ if environ is None else environ
    is_container = (
        Path("/.dockerenv").exists() if containerized is None else containerized
    )
    if not is_container:
        return

    pgoptions = str(values.get("PGOPTIONS") or "")
    required_options = (
        "application_name=alphaagent-research",
        "max_parallel_workers_per_gather=0",
    )
    if all(option in pgoptions for option in required_options):
        return
    raise RuntimeError(
        "CPU-intensive research must run through the alphaagent-research service: "
        "docker compose run --rm --no-deps alphaagent-research ..."
    )
