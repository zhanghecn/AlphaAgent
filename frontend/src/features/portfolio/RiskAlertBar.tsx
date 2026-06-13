import { AlertTriangle } from "lucide-react";
import type { SimulationPosition } from "@/api/quant";
import type { RiskBadge } from "@/lib/portfolio-risk";

interface RiskAlertBarProps {
  positions: SimulationPosition[];
  riskBadgesBySymbol: Map<string, RiskBadge[]>;
  onViewDetail?: (vtSymbol: string) => void;
}

/**
 * RiskAlertBar — compact banner shown only at the top of the holding lane when
 * some positions need attention (near stop-loss / deep loss / overdue).
 * Replaces the always-present bottom RiskEventsPanel: no risk, no banner.
 */
export function RiskAlertBar({ positions, riskBadgesBySymbol, onViewDetail }: RiskAlertBarProps) {
  const risky = positions
    .map((position) => ({ position, badges: riskBadgesBySymbol.get(position.vt_symbol) ?? [] }))
    .filter((entry) => entry.badges.length > 0);

  if (risky.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm">
      <AlertTriangle size={16} className="shrink-0 text-destructive" />
      <span className="font-medium">{risky.length} 只持仓需关注：</span>
      <div className="flex flex-wrap gap-1.5">
        {risky.map(({ position, badges }) => (
          <button
            key={position.vt_symbol}
            type="button"
            className="rounded border border-destructive/20 bg-card px-2 py-0.5 text-xs transition-colors hover:bg-muted"
            onClick={() => onViewDetail?.(position.vt_symbol)}
          >
            <span className="font-medium">{position.name ?? position.vt_symbol}</span>
            <span className="ml-1 text-muted-foreground">{badges.map((b) => b.label).join(" · ")}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
