"""Stable identity for the code runtime that captures radar frames."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache
from hashlib import sha256
from importlib.metadata import distributions
import json
import logging
from pathlib import Path
import platform
import sys


CAPTURE_RUNTIME_FINGERPRINT_VERSION = "limit-up-capture-runtime-v1"
LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def capture_runtime_fingerprint() -> str:
    """Hash the shipped capture source and Python dependency runtime once."""

    alphaagent_root = Path(__file__).resolve().parents[3]
    project_root = alphaagent_root.parent
    return build_capture_runtime_fingerprint(
        (
            ("alphaagent", alphaagent_root),
            ("third_party/akshare", project_root / "third_party" / "akshare"),
        ),
        _runtime_metadata(),
    )


@lru_cache(maxsize=1)
def capture_runtime_fingerprint_safely() -> str | None:
    """Keep a fingerprint failure isolated from the formal live snapshot."""

    try:
        return capture_runtime_fingerprint()
    except Exception:  # noqa: BLE001
        LOGGER.exception("limit-up capture runtime fingerprint failed")
        return None


def build_capture_runtime_fingerprint(
    source_roots: Sequence[tuple[str, Path]],
    runtime_metadata: Mapping[str, object],
) -> str:
    """Build a deterministic fingerprint from named source roots and metadata."""

    digest = sha256()
    _update_digest(digest, CAPTURE_RUNTIME_FINGERPRINT_VERSION.encode())
    metadata = json.dumps(
        runtime_metadata,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    _update_digest(digest, metadata)
    for label, root in sorted(source_roots, key=lambda item: item[0]):
        normalized_label = str(label).strip()
        _update_digest(digest, normalized_label.encode())
        if not root.is_dir():
            _update_digest(digest, b"missing")
            continue
        files = sorted(
            path
            for path in root.rglob("*.py")
            if path.is_file() and "__pycache__" not in path.parts
        )
        for path in files:
            relative = path.relative_to(root).as_posix()
            _update_digest(digest, relative.encode())
            _update_digest(digest, path.read_bytes())
    return f"sha256:{digest.hexdigest()}"


def is_capture_runtime_fingerprint(value: object) -> bool:
    text = str(value or "").strip()
    return bool(
        len(text) == 71
        and text.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in text[7:])
    )


def _runtime_metadata() -> dict[str, object]:
    packages = sorted(
        {
            (
                str(distribution.metadata.get("Name") or "").strip().lower(),
                str(distribution.version),
            )
            for distribution in distributions()
            if str(distribution.metadata.get("Name") or "").strip()
        }
    )
    return {
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "packages": packages,
        "python": sys.version,
    }


def _update_digest(digest, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, byteorder="big", signed=False))
    digest.update(value)
