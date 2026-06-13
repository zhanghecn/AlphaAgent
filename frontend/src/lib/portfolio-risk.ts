/**
 * Portfolio position risk badges.
 *
 * Derives lightweight risk signals (near stop-loss, deep floating loss,
 * holding too long) from a simulated position, so the holding card can
 * surface attention-needed positions without a separate risk service.
 */
import type { SimulationPosition } from "@/api/quant";

export type RiskBadgeType = "near_stop_loss" | "deep_loss" | "holding_too_long";
export type RiskSeverity = "high" | "medium";

export interface RiskBadge {
  type: RiskBadgeType;
  severity: RiskSeverity;
  label: string;
  detail?: string;
}

/** Tunable thresholds for risk detection. */
export const RISK_THRESHOLDS = {
  /** Current price within 2% above the stop-loss line counts as "near". */
  nearStopLossRatio: 1.02,
  /** Floating P&L percentage at or below this is a deep loss. */
  deepLossPct: -8,
  /** Holding longer than N trading days is "too long". */
  holdingTooLongTradingDays: 20,
} as const;

// 20 trading days ~= 28 calendar days (1.4x). We only have last_buy_time
// (an ISO timestamp), not a trading-calendar lookup, so approximate by
// calendar days.
const HOLDING_TOO_LONG_MS =
  RISK_THRESHOLDS.holdingTooLongTradingDays * 1.4 * 24 * 60 * 60 * 1000;

/** Compute risk badges for a single simulated position. */
export function computeRiskBadges(position: SimulationPosition): RiskBadge[] {
  const badges: RiskBadge[] = [];

  const stopLoss = finiteNumber(position.stop_loss_price);
  const lastPrice = finiteNumber(position.last_price);
  if (stopLoss != null && lastPrice != null && lastPrice <= stopLoss * RISK_THRESHOLDS.nearStopLossRatio) {
    badges.push({
      type: "near_stop_loss",
      severity: "high",
      label: "接近止损",
      detail: `现价贴近止损线 ${stopLoss.toFixed(2)}`,
    });
  }

  const pnlPct = finiteNumber(position.floating_pnl_pct);
  if (pnlPct != null && pnlPct <= RISK_THRESHOLDS.deepLossPct) {
    badges.push({
      type: "deep_loss",
      severity: "high",
      label: "浮亏扩大",
      detail: `浮亏 ${pnlPct.toFixed(1)}%`,
    });
  }

  if (position.last_buy_time) {
    const buyMs = Date.parse(position.last_buy_time);
    if (!Number.isNaN(buyMs) && Date.now() - buyMs > HOLDING_TOO_LONG_MS) {
      badges.push({
        type: "holding_too_long",
        severity: "medium",
        label: "持仓超时",
        detail: "持仓时间较长，建议复盘",
      });
    }
  }

  return badges;
}

function finiteNumber(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
