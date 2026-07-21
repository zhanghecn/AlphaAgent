"""Versioned research protocol and locked outer time split for low suction V2."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


FINGERPRINT_CHUNK_ROWS = 25_000


class ResearchStage(StrEnum):
    COVERAGE = "coverage"
    CYCLE_SELECTION = "cycle_selection"
    LEADER_SELECTION = "leader_selection"
    STATE_DISCOVERY = "state_discovery"
    PIPELINE_VALIDATION = "pipeline_validation"
    LOCKED_HOLDOUT = "locked_holdout"


@dataclass(frozen=True)
class ResearchProtocol:
    version: str = "low-suction-research-v2"
    cycle_contract_version: str = "entry-gate-common-trend-sustain-v1"
    holdout_fraction: float = 0.20
    rolling_folds: int = 5
    embargo_trade_days: int = 5
    max_discovery_rules: int = 5
    tree_max_depth: int = 2
    tree_min_episodes_per_leaf: int = 100
    min_validation_episodes: int = 100
    min_holdout_trades: int = 300
    min_holdout_win_rate_pct: float = 60.0
    min_holdout_compounded_return_pct: float = 60.0
    max_drawdown_pct: float = -10.0
    max_contribution_share: float = 0.20
    min_material_regime_days: int = 20
    min_regime_closed_trades: int = 30
    min_regime_win_rate_pct: float = 60.0
    min_traded_regimes: int = 2
    max_regime_profit_contribution_share: float = 0.70
    slippage_bps: float = 10.0

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("protocol version cannot be empty")
        if not self.cycle_contract_version.strip():
            raise ValueError("cycle contract version cannot be empty")
        if not 0.0 < self.holdout_fraction < 1.0:
            raise ValueError("holdout_fraction must be between zero and one")
        if self.rolling_folds < 1:
            raise ValueError("rolling_folds must be positive")
        if self.embargo_trade_days < 0:
            raise ValueError("embargo_trade_days cannot be negative")
        if self.max_drawdown_pct >= 0:
            raise ValueError("max_drawdown_pct must be negative")
        if not 0.0 <= self.min_holdout_win_rate_pct < 100.0:
            raise ValueError("min_holdout_win_rate_pct must be below 100")
        if self.min_holdout_compounded_return_pct < 0:
            raise ValueError("min_holdout_compounded_return_pct cannot be negative")
        if not 0.0 < self.max_contribution_share <= 1.0:
            raise ValueError("max_contribution_share must be between zero and one")
        if self.min_material_regime_days < 1:
            raise ValueError("min_material_regime_days must be positive")
        if self.min_regime_closed_trades < 1:
            raise ValueError("min_regime_closed_trades must be positive")
        if not 0.0 <= self.min_regime_win_rate_pct < 100.0:
            raise ValueError("min_regime_win_rate_pct must be below 100")
        if self.min_traded_regimes < 2:
            raise ValueError("min_traded_regimes must be at least two")
        if not 0.0 < self.max_regime_profit_contribution_share <= 1.0:
            raise ValueError(
                "max_regime_profit_contribution_share must be between zero and one"
            )


@dataclass(frozen=True)
class RollingFold:
    train_dates: tuple[date, ...]
    validation_dates: tuple[date, ...]


@dataclass(frozen=True)
class ProtocolSplit:
    discovery_dates: tuple[date, ...]
    holdout_dates: tuple[date, ...]
    rolling_folds: tuple[RollingFold, ...]


@dataclass(frozen=True)
class DataFingerprint:
    algorithm: str
    digest: str
    rows: int
    columns: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "digest": self.digest,
            "rows": self.rows,
            "columns": list(self.columns),
        }


@dataclass(frozen=True)
class RegimePerformance:
    regime_key: str
    observation_days: int
    policy: str
    closed_trades: int
    win_rate_pct: float | None
    compounded_return_pct: float
    maximum_drawdown_pct: float
    profit_contribution_share: float

    def __post_init__(self) -> None:
        if not self.regime_key.strip():
            raise ValueError("regime_key cannot be empty")
        if self.policy not in {"trade", "cash"}:
            raise ValueError("regime policy must be trade or cash")
        if self.observation_days < 0 or self.closed_trades < 0:
            raise ValueError("regime counts cannot be negative")
        if self.win_rate_pct is not None and not 0.0 <= self.win_rate_pct <= 100.0:
            raise ValueError("regime win_rate_pct must be between zero and 100")
        if not 0.0 <= self.profit_contribution_share <= 1.0:
            raise ValueError(
                "regime profit_contribution_share must be between zero and one"
            )


@dataclass(frozen=True)
class RegimeAdaptationDecision:
    qualified: bool
    failed_gates: tuple[str, ...]


class HoldoutAccessError(RuntimeError):
    """Raised when an outer holdout access violates the frozen protocol."""


@dataclass
class HoldoutLock:
    frozen_pipeline_hash: str
    access_count: int = 0
    state_path: Path | None = None

    @classmethod
    def create(
        cls,
        frozen_pipeline_hash: str,
        *,
        state_path: Path | None = None,
    ) -> HoldoutLock:
        _validate_pipeline_hash(frozen_pipeline_hash)
        lock = cls(
            frozen_pipeline_hash=frozen_pipeline_hash,
            state_path=state_path.resolve() if state_path else None,
        )
        if lock.state_path is not None:
            lock._create_persisted_state()
        return lock

    @classmethod
    def load(cls, state_path: Path) -> HoldoutLock:
        resolved = state_path.resolve()
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HoldoutAccessError("persisted holdout lock is unreadable") from exc
        frozen_pipeline_hash = str(payload.get("frozen_pipeline_hash") or "")
        _validate_pipeline_hash(frozen_pipeline_hash)
        access_count = int(payload.get("access_count", 0))
        if access_count not in (0, 1):
            raise HoldoutAccessError("persisted holdout access count is invalid")
        if _used_marker(resolved).exists():
            access_count = 1
        return cls(frozen_pipeline_hash, access_count, resolved)

    def authorize(self, candidate_hash: str) -> None:
        if candidate_hash != self.frozen_pipeline_hash:
            raise HoldoutAccessError("candidate does not match frozen pipeline hash")
        if self.access_count:
            raise HoldoutAccessError("locked holdout has already been evaluated")
        if self.state_path is not None:
            _claim_used_marker(self.state_path)
        self.access_count = 1
        if self.state_path is not None:
            self._replace_persisted_state()

    def as_dict(self) -> dict[str, str | int]:
        return {
            "frozen_pipeline_hash": self.frozen_pipeline_hash,
            "access_count": self.access_count,
        }

    def _create_persisted_state(self) -> None:
        assert self.state_path is not None
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = _canonical_json(self.as_dict()) + "\n"
        try:
            descriptor = os.open(
                self.state_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError as exc:
            raise HoldoutAccessError(
                "persisted holdout lock already exists; load it instead"
            ) from exc
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

    def _replace_persisted_state(self) -> None:
        assert self.state_path is not None
        temporary = self.state_path.with_name(
            f".{self.state_path.name}.{os.getpid()}.tmp"
        )
        temporary.write_text(_canonical_json(self.as_dict()) + "\n", encoding="utf-8")
        temporary.replace(self.state_path)


def default_protocol() -> ResearchProtocol:
    return ResearchProtocol()


def protocol_hash(protocol: ResearchProtocol) -> str:
    payload = _canonical_json(asdict(protocol))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_frame(
    frame: pd.DataFrame,
    *,
    identity_columns: Sequence[str],
) -> DataFingerprint:
    identity = tuple(identity_columns)
    missing = [column for column in identity if column not in frame]
    if missing:
        raise ValueError(f"missing fingerprint identity columns: {', '.join(missing)}")
    identity_index = pd.MultiIndex.from_frame(frame.loc[:, list(identity)])
    if identity_index.has_duplicates:
        raise ValueError("fingerprint identity columns must be unique")

    columns = tuple(sorted(str(column) for column in frame.columns))
    ordered = (
        frame
        if identity_index.is_monotonic_increasing
        else frame.sort_values(list(identity), kind="stable")
    )
    metadata = {
        "columns": list(columns),
        "dtypes": {column: str(ordered[column].dtype) for column in columns},
    }
    digest = hashlib.sha256()
    encoded_metadata = _canonical_json(metadata)
    digest.update(encoded_metadata[:-1].encode("utf-8"))
    digest.update(b',"records":[')
    _update_fingerprint_records(digest, ordered, columns)
    digest.update(b"]}")
    return DataFingerprint(
        algorithm="sha256",
        digest=f"sha256:{digest.hexdigest()}",
        rows=len(ordered),
        columns=columns,
    )


def _update_fingerprint_records(
    digest: Any,
    ordered: pd.DataFrame,
    columns: Sequence[str],
) -> None:
    wrote_records = False
    for start in range(0, len(ordered), FINGERPRINT_CHUNK_ROWS):
        chunk = ordered.iloc[start : start + FINGERPRINT_CHUNK_ROWS].loc[:, columns]
        records = json.loads(
            chunk.to_json(
                orient="records",
                date_format="iso",
                date_unit="us",
                double_precision=15,
            )
        )
        if not records:
            continue
        if wrote_records:
            digest.update(b",")
        digest.update(_canonical_json(records)[1:-1].encode("utf-8"))
        wrote_records = True


def build_protocol_split(
    values: Sequence[date],
    protocol: ResearchProtocol,
) -> ProtocolSplit:
    dates = tuple(sorted(set(values)))
    if len(dates) < 100:
        raise ValueError("at least 100 unique dates are required")

    holdout_size = max(1, math.ceil(len(dates) * protocol.holdout_fraction))
    discovery_dates = dates[:-holdout_size]
    holdout_dates = dates[-holdout_size:]
    boundaries = np.linspace(
        0,
        len(discovery_dates),
        protocol.rolling_folds + 2,
        dtype=int,
    )
    folds = []
    for index in range(1, protocol.rolling_folds + 1):
        validation_start = int(boundaries[index])
        validation_end = int(boundaries[index + 1])
        training_end = validation_start - protocol.embargo_trade_days
        if training_end <= 0 or validation_end <= validation_start:
            raise ValueError("rolling fold is empty after embargo")
        folds.append(
            RollingFold(
                train_dates=discovery_dates[:training_end],
                validation_dates=discovery_dates[validation_start:validation_end],
            )
        )
    return ProtocolSplit(discovery_dates, holdout_dates, tuple(folds))


def protocol_payload(
    protocol: ResearchProtocol,
    split: ProtocolSplit,
) -> dict[str, Any]:
    return {
        "protocol": asdict(protocol),
        "protocol_hash": protocol_hash(protocol),
        "date_split": {
            "discovery_dates": len(split.discovery_dates),
            "discovery_start": split.discovery_dates[0].isoformat(),
            "discovery_end": split.discovery_dates[-1].isoformat(),
            "holdout_dates": len(split.holdout_dates),
            "holdout_start": split.holdout_dates[0].isoformat(),
            "holdout_end": split.holdout_dates[-1].isoformat(),
            "rolling_folds": [
                {
                    "fold": index,
                    "train_dates": len(fold.train_dates),
                    "train_start": fold.train_dates[0].isoformat(),
                    "train_end": fold.train_dates[-1].isoformat(),
                    "validation_dates": len(fold.validation_dates),
                    "validation_start": fold.validation_dates[0].isoformat(),
                    "validation_end": fold.validation_dates[-1].isoformat(),
                }
                for index, fold in enumerate(split.rolling_folds, start=1)
            ],
        },
    }


def evaluate_regime_adaptation(
    results: Sequence[RegimePerformance],
    protocol: ResearchProtocol,
) -> RegimeAdaptationDecision:
    keys = [result.regime_key for result in results]
    if len(keys) != len(set(keys)):
        raise ValueError("regime performance keys must be unique")

    material = [
        result
        for result in results
        if result.observation_days >= protocol.min_material_regime_days
    ]
    failed_gates: list[str] = []
    if not material:
        failed_gates.append("material_regimes")

    traded_regimes = 0
    for result in material:
        if result.policy == "cash":
            if (
                result.closed_trades != 0
                or result.win_rate_pct is not None
                or result.compounded_return_pct != 0.0
                or result.maximum_drawdown_pct != 0.0
                or result.profit_contribution_share != 0.0
            ):
                failed_gates.append(f"{result.regime_key}:cash_policy")
            continue

        traded_regimes += 1
        if result.closed_trades < protocol.min_regime_closed_trades:
            failed_gates.append(f"{result.regime_key}:closed_trades")
        if (
            result.win_rate_pct is None
            or result.win_rate_pct <= protocol.min_regime_win_rate_pct
        ):
            failed_gates.append(f"{result.regime_key}:win_rate")
        if result.compounded_return_pct <= 0.0:
            failed_gates.append(f"{result.regime_key}:compounded_return")
        if not protocol.max_drawdown_pct <= result.maximum_drawdown_pct <= 0.0:
            failed_gates.append(f"{result.regime_key}:maximum_drawdown")
        if (
            result.profit_contribution_share
            > protocol.max_regime_profit_contribution_share
        ):
            failed_gates.append(f"{result.regime_key}:profit_concentration")

    if traded_regimes < protocol.min_traded_regimes:
        failed_gates.append("traded_regimes")
    return RegimeAdaptationDecision(
        qualified=not failed_gates,
        failed_gates=tuple(failed_gates),
    )


def _validate_pipeline_hash(value: str) -> None:
    if not value.startswith("sha256:") or len(value) <= len("sha256:"):
        raise ValueError("frozen pipeline hash must use the sha256 prefix")


def _used_marker(state_path: Path) -> Path:
    return state_path.with_suffix(f"{state_path.suffix}.used")


def _claim_used_marker(state_path: Path) -> None:
    marker = _used_marker(state_path)
    try:
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise HoldoutAccessError("locked holdout has already been evaluated") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("used\n")
        handle.flush()
        os.fsync(handle.fileno())


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
