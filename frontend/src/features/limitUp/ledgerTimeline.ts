import type { LimitUpLaneLedger, LimitUpLaneLedgerTrade } from "@/api/limitUp";

export interface LedgerDaySummary {
  date: string;
  trades: LimitUpLaneLedgerTrade[];
  observations: LimitUpLaneLedgerTrade[];
  tradeCount: number;
  closedCount: number;
  winCount: number;
  totalReturnPct: number | null;
  observationOnly: boolean;
}

export function summarizeLedgerDay(ledger: LimitUpLaneLedger): LedgerDaySummary {
  const trades = ledger.trades ?? [];
  const observations = ledger.observations ?? [];
  const closed = trades.filter((trade) => trade.return_pct != null);
  const winCount = closed.filter((trade) => (trade.return_pct ?? 0) > 0).length;
  const totalReturnPct = closed.length
    ? closed.reduce((sum, trade) => sum + (trade.return_pct ?? 0), 0)
    : null;
  return {
    date: ledger.trade_date,
    trades,
    observations,
    tradeCount: trades.length,
    closedCount: closed.length,
    winCount,
    totalReturnPct,
    observationOnly: trades.length === 0 && observations.length > 0,
  };
}

export function weekdayLabel(date: string): string {
  try {
    return new Intl.DateTimeFormat("zh-CN", { weekday: "short" }).format(new Date(`${date}T00:00:00`));
  } catch {
    return "";
  }
}
