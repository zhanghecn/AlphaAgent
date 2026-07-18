import type { LimitUpLaneBacktest } from "@/api/limitUp";
import type { Bar } from "@/api/types";

export interface BacktestChartPoint {
  result_date: string;
  account_return_pct: number | null;
  account_drawdown_pct: number | null;
  recommendation_return_pct: number | null;
  index_return_pct: number | null;
}

/**
 * 把两仓账户、全量推荐质量和上证指数对齐到同一交易日序列。
 * 指数收益从区间首个有行情的日期归一；非交易日沿用此前最近收盘价。
 */
export function buildBacktestChartPoints(
  report: LimitUpLaneBacktest,
  indexBars: Bar[] = [],
): BacktestChartPoint[] {
  const dates = report.daily_results.map((day) => day.result_date);
  const indexReturns = alignIndexReturns(indexBars, dates);
  const recommendationByDate = new Map(
    (report.recommendation_quality?.daily_results ?? []).map((day) => [day.result_date, day]),
  );
  return report.daily_results.map((day) => ({
    result_date: day.result_date,
    account_return_pct: day.total_return_pct,
    account_drawdown_pct: day.drawdown_pct,
    recommendation_return_pct: recommendationByDate.get(day.result_date)?.total_return_pct ?? null,
    index_return_pct: indexReturns.get(day.result_date) ?? null,
  }));
}

export function alignIndexReturns(bars: Bar[], dates: string[]): Map<string, number> {
  const result = new Map<string, number>();
  if (!bars.length || !dates.length) return result;

  const closeByDate = new Map<string, number>();
  for (const bar of bars) {
    if (Number.isFinite(bar.close)) closeByDate.set(bar.trade_date, bar.close);
  }

  const sortedDates = [...dates].sort();
  let baseClose: number | null = null;
  let lastClose: number | null = null;
  for (const date of sortedDates) {
    const close = closeByDate.get(date);
    if (close != null) lastClose = close;
    if (lastClose == null) continue;
    baseClose ??= lastClose;
    result.set(date, ((lastClose - baseClose) / baseClose) * 100);
  }
  return result;
}
