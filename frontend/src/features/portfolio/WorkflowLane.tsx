import type { ReactNode } from "react";
import { SectionCard } from "@/components/dashboard/SectionCard";
import { EmptyState } from "@/components/EmptyState";
import { Badge } from "@/components/ui/badge";
import { HoldingCard, type HoldingCardItem, type DailyBar, type StrategyAdvice } from "./HoldingCard";
import type { SimulationPosition } from "@/api/quant";
import type { RiskBadge } from "@/lib/portfolio-risk";
import type { PortfolioStateMeta } from "@/lib/portfolio-states";

/** One card's worth of assembled data for a lane. */
export interface LaneCardData {
  item: HoldingCardItem;
  position?: SimulationPosition;
  bars?: DailyBar[];
  riskBadges?: RiskBadge[];
  strategyAdvice?: StrategyAdvice | null;
}

interface WorkflowLaneProps {
  state: PortfolioStateMeta;
  cards: LaneCardData[];
  /** Optional right-side action (e.g. batch ops, build button). */
  action?: ReactNode;
  /** Optional alert banner rendered at the top of the lane body. */
  alert?: ReactNode;
  onAddToGroup?: (vtSymbol: string) => void;
  onViewDetail?: (vtSymbol: string) => void;
  onSell?: (vtSymbol: string) => void;
  onAddPosition?: (vtSymbol: string) => void;
  isSelecting?: boolean;
  selectedSymbols?: Set<string>;
  onToggleSelect?: (vtSymbol: string) => void;
  accountId?: number;
  selectedGroupId?: number;
}

/**
 * A single workflow lane — a SectionCard titled with the state name + item
 * count, containing a responsive grid of HoldingCards (or an empty state).
 */
export function WorkflowLane({
  state,
  cards,
  action,
  alert,
  onAddToGroup,
  onViewDetail,
  onSell,
  onAddPosition,
  isSelecting,
  selectedSymbols,
  onToggleSelect,
  accountId,
  selectedGroupId,
}: WorkflowLaneProps) {
  return (
    <SectionCard
      title={
        <span className="flex items-center gap-2">
          {state.label}
          <Badge variant="secondary" className="px-1.5 py-0">
            {cards.length}
          </Badge>
        </span>
      }
      description={state.description}
      action={action}
      bodyClassName="p-4"
    >
      {alert && <div className="mb-3">{alert}</div>}
      {cards.length === 0 ? (
        <EmptyState
          message={`「${state.label}」暂无股票`}
          description={emptyHint(state.key)}
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {cards.map((card) => (
            <HoldingCard
              key={card.item.vt_symbol}
              item={card.item}
              position={card.position}
              dailyBars={card.bars}
              riskBadges={card.riskBadges}
              strategyAdvice={card.strategyAdvice}
              onAddToGroup={onAddToGroup}
              onViewDetail={onViewDetail}
              onSell={card.position ? onSell : undefined}
              onAddPosition={card.position ? onAddPosition : undefined}
              isSelecting={isSelecting}
              isSelected={selectedSymbols?.has(card.item.vt_symbol)}
              onToggleSelect={onToggleSelect}
              accountId={card.position ? accountId : undefined}
              selectedGroupId={selectedGroupId}
            />
          ))}
        </div>
      )}
    </SectionCard>
  );
}

function emptyHint(stateKey: PortfolioStateMeta["key"]): string {
  switch (stateKey) {
    case "watch":
      return "可手动加入股票，或从其他分组移入。";
    case "candidate":
      return "在量化页运行策略研究后会自动同步到此。";
    case "holding":
      return "可从候选池模拟建仓，或手动下模拟单。";
    case "review":
      return "卖出的股票会归档到此用于复盘。";
    default:
      return "";
  }
}
