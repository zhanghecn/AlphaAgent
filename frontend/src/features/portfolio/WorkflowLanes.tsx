import type { ReactNode } from "react";
import { PORTFOLIO_STATES } from "@/lib/portfolio-states";
import type { PortfolioState } from "@/lib/portfolio-states";
import type { PortfolioGroup, PortfolioItem, SimulationPosition } from "@/api/quant";
import type { DailyBar } from "./HoldingCard";
import type { RiskBadge } from "@/lib/portfolio-risk";
import { WorkflowLane, type LaneCardData } from "./WorkflowLane";
import { CandidateTable } from "./CandidateTable";
import { RiskAlertBar } from "./RiskAlertBar";

interface WorkflowLanesProps {
  itemsByState: Record<PortfolioState, PortfolioItem[]>;
  groupsByState: Record<PortfolioState, PortfolioGroup[]>;
  /** Real simulated positions — drive the holding lane. */
  positions: SimulationPosition[];
  positionsBySymbol: Map<string, SimulationPosition>;
  barsBySymbol: Map<string, DailyBar[]>;
  riskBadgesBySymbol: Map<string, RiskBadge[]>;
  /** Optional per-lane action keyed by state (e.g. build button on candidate). */
  laneAction?: (state: PortfolioState) => ReactNode;
  onAddToGroup?: (vtSymbol: string) => void;
  onViewDetail?: (vtSymbol: string) => void;
  onSell?: (vtSymbol: string) => void;
  onAddPosition?: (vtSymbol: string) => void;
  /** Build a single candidate into a position (candidate lane only). */
  onBuild?: (vtSymbol: string) => void;
  isSelecting?: boolean;
  selectedSymbols?: Set<string>;
  onToggleSelect?: (vtSymbol: string) => void;
  accountId?: number;
}

/**
 * Renders the four workflow lanes (watch / candidate / holding / review).
 * The holding lane is driven by real simulated positions; the others by their
 * group items. Blacklist is rendered separately by BlacklistSidebar.
 */
export function WorkflowLanes({
  itemsByState,
  positions,
  positionsBySymbol,
  barsBySymbol,
  riskBadgesBySymbol,
  laneAction,
  onAddToGroup,
  onViewDetail,
  onSell,
  onAddPosition,
  onBuild,
  isSelecting,
  selectedSymbols,
  onToggleSelect,
  accountId,
}: WorkflowLanesProps) {
  return (
    <div className="space-y-4">
      {PORTFOLIO_STATES.map((state) => {
        if (state.key === "candidate") {
          return (
            <CandidateTable
              key={state.key}
              items={itemsByState.candidate ?? []}
              action={laneAction?.("candidate")}
              onBuild={onBuild}
              onViewDetail={onViewDetail}
            />
          );
        }
        const cards =
          state.key === "holding"
            ? buildHoldingCards(positions, barsBySymbol, riskBadgesBySymbol)
            : buildCards(itemsByState[state.key] ?? [], positionsBySymbol, barsBySymbol, riskBadgesBySymbol);

        return (
          <WorkflowLane
            key={state.key}
            state={state}
            cards={cards}
            action={laneAction?.(state.key)}
            alert={
              state.key === "holding" ? (
                <RiskAlertBar
                  positions={positions}
                  riskBadgesBySymbol={riskBadgesBySymbol}
                  onViewDetail={onViewDetail}
                />
              ) : null
            }
            onAddToGroup={onAddToGroup}
            onViewDetail={onViewDetail}
            onSell={onSell}
            onAddPosition={onAddPosition}
            isSelecting={isSelecting}
            selectedSymbols={selectedSymbols}
            onToggleSelect={onToggleSelect}
            accountId={accountId}
          />
        );
      })}
    </div>
  );
}

function buildCards(
  items: PortfolioItem[],
  positionsBySymbol: Map<string, SimulationPosition>,
  barsBySymbol: Map<string, DailyBar[]>,
  riskBadgesBySymbol: Map<string, RiskBadge[]>,
): LaneCardData[] {
  return items.map((item) => ({
    // PortfolioItem already satisfies HoldingCardItem structurally.
    item,
    position: positionsBySymbol.get(item.vt_symbol),
    bars: barsBySymbol.get(item.vt_symbol),
    riskBadges: riskBadgesBySymbol.get(item.vt_symbol),
  }));
}

function buildHoldingCards(
  positions: SimulationPosition[],
  barsBySymbol: Map<string, DailyBar[]>,
  riskBadgesBySymbol: Map<string, RiskBadge[]>,
): LaneCardData[] {
  return positions.map((position) => ({
    item: {
      vt_symbol: position.vt_symbol,
      name: position.name,
      board: position.board,
      board_label: position.board_label,
      source: position.source,
      reason: position.reason,
    },
    position,
    bars: barsBySymbol.get(position.vt_symbol),
    riskBadges: riskBadgesBySymbol.get(position.vt_symbol),
  }));
}
