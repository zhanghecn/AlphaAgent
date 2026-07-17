"""Read-only stage audit for the low-suction V2 research pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, func, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope

from .concept_cycles import (
    FROZEN_MAIN_RISE_DEFINITION,
    load_cycle_research_calendar,
)
from .data_quality_repository import load_data_quality_report
from .leader_identity import LeaderIdentityMode
from .forward_membership import TRADABLE_SCOPE_TYPE
from .research_protocol import (
    ResearchProtocol,
    default_protocol,
    protocol_hash,
)
from .theme_reference_cohorts import MANIFEST_VERSION


@dataclass(frozen=True)
class StrictStageCounts:
    membership_dates: int
    security_dates: int
    membership_rows: int
    security_rows: int
    forward_membership_dates: int = 0
    forward_security_dates: int = 0
    forward_membership_rows: int = 0
    forward_security_rows: int = 0


def load_v2_stage_audit() -> dict[str, Any]:
    protocol = default_protocol()
    return build_v2_stage_audit(
        load_data_quality_report(),
        cycle_dates=load_cycle_research_calendar(),
        strict_counts=_load_strict_stage_counts(),
        protocol=protocol,
    )


def build_v2_stage_audit(
    data_quality: dict[str, Any],
    *,
    cycle_dates: tuple,
    strict_counts: StrictStageCounts,
    protocol: ResearchProtocol,
) -> dict[str, Any]:
    coverage = data_quality.get("coverage") or {}
    membership = coverage.get("concept_membership") or {}
    security = coverage.get("security_status") or {}
    minutes = coverage.get("candidate_minutes") or {}
    cycle_ready = len(cycle_dates) >= 720
    available_membership_dates = max(
        strict_counts.membership_dates,
        strict_counts.forward_membership_dates,
    )
    available_security_dates = max(
        strict_counts.security_dates,
        strict_counts.forward_security_dates,
    )
    leader_ready = available_membership_dates >= 720 and available_security_dates >= 720
    minute_pairs = int(minutes.get("total_pairs") or 0)
    covered_pairs = int(minutes.get("covered_pairs") or 0)
    state_ready = leader_ready and minute_pairs > 0 and covered_pairs == minute_pairs
    inventory = data_quality.get("inventory") or {}
    timing_inventory = inventory.get("market_timing") or {}

    return {
        "protocol_version": protocol.version,
        "protocol_hash": protocol_hash(protocol),
        "conclusion": data_quality.get("status") or "blocked_by_data_quality",
        "formal_metrics": None,
        "blocking_gaps": list(data_quality.get("blocking_gaps") or []),
        "qualification_targets": {
            "closed_trades": f">= {protocol.min_holdout_trades}",
            "win_rate_pct": f"> {protocol.min_holdout_win_rate_pct}",
            "compounded_return_pct": (
                f"> {protocol.min_holdout_compounded_return_pct}"
            ),
            "maximum_drawdown_pct": f">= {protocol.max_drawdown_pct}",
            "profit_factor": "> 1.0",
            "double_cost_compounded_return_pct": "> 0.0",
            "minimum_traded_regimes": protocol.min_traded_regimes,
            "material_regime_days": f">= {protocol.min_material_regime_days}",
            "per_traded_regime_closed_trades": (
                f">= {protocol.min_regime_closed_trades}"
            ),
            "per_traded_regime_win_rate_pct": (
                f"> {protocol.min_regime_win_rate_pct}"
            ),
            "per_traded_regime_compounded_return_pct": "> 0.0",
        },
        "market_regime_inventory": dict(timing_inventory.get("state_counts") or {}),
        "stages": {
            "cycle": {
                "status": "completed" if cycle_ready else "blocked",
                "reliable_dates": len(cycle_dates),
                "frozen_definition": (
                    FROZEN_MAIN_RISE_DEFINITION if cycle_ready else None
                ),
                "holdout_price_values_read": False,
            },
            "leader": {
                "status": "ready" if leader_ready else "blocked",
                "implementation": "complete",
                "strict_membership_dates": strict_counts.membership_dates,
                "strict_security_dates": strict_counts.security_dates,
                "strict_membership_rows": strict_counts.membership_rows,
                "strict_security_rows": strict_counts.security_rows,
                "forward_membership_accumulating_dates": (
                    strict_counts.forward_membership_dates
                ),
                "forward_security_accumulating_dates": (
                    strict_counts.forward_security_dates
                ),
                "forward_membership_rows": strict_counts.forward_membership_rows,
                "forward_security_rows": strict_counts.forward_security_rows,
                "current_proxy_dates": int(membership.get("trade_days") or 0),
                "current_proxy_mode": membership.get("mode"),
                "security_mode": security.get("mode"),
                "identity_modes": [mode.value for mode in LeaderIdentityMode],
                "selected_mode": None,
            },
            "state": {
                "status": "ready" if state_ready else "blocked",
                "candidate_pairs": minute_pairs,
                "covered_pairs": covered_pairs,
            },
            "validation": {
                "status": "ready" if state_ready else "blocked",
                "frozen_pipeline": None,
                "locked_holdout_access_count": 0,
            },
        },
    }


def _load_strict_stage_counts() -> StrictStageCounts:
    membership_scope = schema.low_suction_concept_membership_scopes
    membership_history = schema.low_suction_concept_membership_history
    security_scope = schema.low_suction_security_history_scopes
    security_history = schema.low_suction_security_history
    forward_membership_scope = (
        schema.low_suction_forward_membership_snapshot_scopes
    )
    forward_membership_rows = schema.low_suction_forward_membership_snapshots
    forward_security_scope = schema.low_suction_security_snapshot_scopes
    forward_security_rows = schema.low_suction_security_snapshots
    with session_scope() as session:
        membership_dates = int(
            session.execute(
                select(func.count(func.distinct(membership_scope.c.trade_date))).where(
                    membership_scope.c.evidence_level == "strict",
                    membership_scope.c.pagination_complete.is_(True),
                    membership_scope.c.expected_member_count
                    == membership_scope.c.returned_member_count,
                    membership_scope.c.source_trade_date < membership_scope.c.trade_date,
                )
            ).scalar_one()
            or 0
        )
        security_dates = int(
            session.execute(
                select(func.count(func.distinct(security_scope.c.trade_date))).where(
                    security_scope.c.evidence_level == "strict"
                )
            ).scalar_one()
            or 0
        )
        membership_rows = int(
            session.execute(
                select(func.count()).select_from(membership_history).where(
                    membership_history.c.evidence_level == "strict"
                )
            ).scalar_one()
            or 0
        )
        security_rows = int(
            session.execute(
                select(func.count()).select_from(security_history).where(
                    security_history.c.evidence_level == "strict"
                )
            ).scalar_one()
            or 0
        )
        forward_membership_dates = int(
            session.execute(
                select(
                    func.count(
                        func.distinct(
                            forward_membership_scope.c.source_trade_date
                        )
                    )
                ).where(
                    forward_membership_scope.c.scope_type
                    == TRADABLE_SCOPE_TYPE,
                    forward_membership_scope.c.evidence_level == "strict",
                    forward_membership_scope.c.complete.is_(True),
                    forward_membership_scope.c.manifest_version
                    == MANIFEST_VERSION,
                )
            ).scalar_one()
            or 0
        )
        forward_security_dates = int(
            session.execute(
                select(
                    func.count(func.distinct(forward_security_scope.c.source_trade_date))
                ).where(
                    forward_security_scope.c.evidence_level == "strict",
                    forward_security_scope.c.complete.is_(True),
                )
            ).scalar_one()
            or 0
        )
        current_forward_scopes = (
            select(
                forward_membership_scope.c.source_trade_date,
                forward_membership_scope.c.source,
            )
            .where(
                forward_membership_scope.c.scope_type
                == TRADABLE_SCOPE_TYPE,
                forward_membership_scope.c.evidence_level == "strict",
                forward_membership_scope.c.complete.is_(True),
                forward_membership_scope.c.manifest_version
                == MANIFEST_VERSION,
            )
            .subquery()
        )
        forward_membership_row_count = int(
            session.execute(
                select(func.count())
                .select_from(
                    forward_membership_rows.join(
                        current_forward_scopes,
                        and_(
                            current_forward_scopes.c.source_trade_date
                            == forward_membership_rows.c.source_trade_date,
                            current_forward_scopes.c.source
                            == forward_membership_rows.c.source,
                        ),
                    )
                )
                .where(forward_membership_rows.c.evidence_level == "strict")
            ).scalar_one()
            or 0
        )
        forward_security_row_count = int(
            session.execute(select(func.count()).select_from(forward_security_rows)).scalar_one()
            or 0
        )
    return StrictStageCounts(
        membership_dates=membership_dates,
        security_dates=security_dates,
        membership_rows=membership_rows,
        security_rows=security_rows,
        forward_membership_dates=forward_membership_dates,
        forward_security_dates=forward_security_dates,
        forward_membership_rows=forward_membership_row_count,
        forward_security_rows=forward_security_row_count,
    )
