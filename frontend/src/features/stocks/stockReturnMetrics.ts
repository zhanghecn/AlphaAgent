import type { BacktestTrade } from "@/api/quant";

export interface ClosedReturnTrade {
  entryDate: string;
  exitDate: string;
  entryPrice: number;
  exitPrice: number;
  returnPct: number;
  holdingDays: number | null;
  exitReason?: string | null;
  exitReasonLabel?: string | null;
}

export interface StockReturnSummary {
  closedCount: number;
  winRatePct: number | null;
  compoundReturnPct: number | null;
  averageReturnPct: number | null;
  bestReturnPct: number | null;
  worstReturnPct: number | null;
  trades: ClosedReturnTrade[];
}

export function deriveStockReturnSummary(trades: BacktestTrade[]): StockReturnSummary {
  const openBuys: BacktestTrade[] = [];
  const closed: ClosedReturnTrade[] = [];
  const sorted = [...trades].sort((left, right) => {
    const dateCompare = String(left.trade_date).localeCompare(String(right.trade_date));
    if (dateCompare !== 0) return dateCompare;
    return (left.id ?? 0) - (right.id ?? 0);
  });

  for (const trade of sorted) {
    const side = String(trade.side || "").toUpperCase();
    if (side === "BUY") {
      openBuys.push(trade);
      continue;
    }
    if (side !== "SELL") continue;
    const entry = openBuys.shift();
    if (!entry?.price || !trade.price) continue;
    const returnPct = (trade.price / entry.price - 1) * 100;
    closed.push({
      entryDate: entry.trade_date,
      exitDate: trade.trade_date,
      entryPrice: entry.price,
      exitPrice: trade.price,
      returnPct,
      holdingDays: holdingDays(entry.trade_date, trade.trade_date),
      exitReason: trade.reason,
      exitReasonLabel: trade.reason_label,
    });
  }

  const returns = closed.map((item) => item.returnPct);
  const wins = returns.filter((value) => value > 0);
  const compound = returns.length
    ? (returns.reduce((nav, value) => nav * (1 + value / 100), 1) - 1) * 100
    : null;

  return {
    closedCount: closed.length,
    winRatePct: closed.length ? (wins.length / closed.length) * 100 : null,
    compoundReturnPct: compound,
    averageReturnPct: returns.length ? returns.reduce((sum, value) => sum + value, 0) / returns.length : null,
    bestReturnPct: returns.length ? Math.max(...returns) : null,
    worstReturnPct: returns.length ? Math.min(...returns) : null,
    trades: closed,
  };
}

function holdingDays(entryDate: string, exitDate: string): number | null {
  const start = Date.parse(`${entryDate.slice(0, 10)}T00:00:00+08:00`);
  const end = Date.parse(`${exitDate.slice(0, 10)}T00:00:00+08:00`);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  return Math.round((end - start) / 86_400_000);
}
