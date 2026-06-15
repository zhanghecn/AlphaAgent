import type { Bar } from "@/api/types";

export interface ChartBarDiagnostic {
  tradeDate: string;
  previousClose: number | null;
  changeAmount: number | null;
  changePct: number | null;
  gapOpenPct: number | null;
  amplitudePct: number | null;
  intradayReturnPct: number | null;
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  ma60: number | null;
  closeToMa5Pct: number | null;
  closeToMa10Pct: number | null;
  closeToMa20Pct: number | null;
  closeToMa60Pct: number | null;
  volumeMa5: number | null;
  volumeMa20: number | null;
  volumeRatio5: number | null;
  volumeRatio20: number | null;
}

export function diagnosticForBar(bars: Bar[], target: Bar | null): ChartBarDiagnostic | null {
  if (!target) return null;
  const index = bars.findIndex((bar) => bar.trade_date === target.trade_date);
  if (index < 0) return null;
  const previous = index > 0 ? bars[index - 1] : null;
  const previousClose = previous?.close ?? null;
  const ma5 = averageClose(bars, index, 5);
  const ma10 = averageClose(bars, index, 10);
  const ma20 = averageClose(bars, index, 20);
  const ma60 = averageClose(bars, index, 60);
  const volumeMa5 = averageVolume(bars, index, 5);
  const volumeMa20 = averageVolume(bars, index, 20);

  return {
    tradeDate: target.trade_date,
    previousClose,
    changeAmount: previousClose == null ? null : target.close - previousClose,
    changePct: previousClose == null ? target.change_pct ?? null : (target.close / previousClose - 1) * 100,
    gapOpenPct: previousClose == null ? null : (target.open / previousClose - 1) * 100,
    amplitudePct: previousClose == null ? null : ((target.high - target.low) / previousClose) * 100,
    intradayReturnPct: target.open ? (target.close / target.open - 1) * 100 : null,
    ma5,
    ma10,
    ma20,
    ma60,
    closeToMa5Pct: pctDistance(target.close, ma5),
    closeToMa10Pct: pctDistance(target.close, ma10),
    closeToMa20Pct: pctDistance(target.close, ma20),
    closeToMa60Pct: pctDistance(target.close, ma60),
    volumeMa5,
    volumeMa20,
    volumeRatio5: volumeMa5 ? target.volume / volumeMa5 : null,
    volumeRatio20: volumeMa20 ? target.volume / volumeMa20 : null,
  };
}

function averageClose(bars: Bar[], index: number, window: number): number | null {
  if (index + 1 < window) return null;
  const slice = bars.slice(index + 1 - window, index + 1);
  return slice.reduce((sum, bar) => sum + bar.close, 0) / window;
}

function averageVolume(bars: Bar[], index: number, window: number): number | null {
  if (index + 1 < window) return null;
  const slice = bars.slice(index + 1 - window, index + 1);
  return slice.reduce((sum, bar) => sum + (bar.volume ?? 0), 0) / window;
}

function pctDistance(value: number | null | undefined, base: number | null | undefined): number | null {
  if (value == null || base == null || base === 0) return null;
  return (value / base - 1) * 100;
}
