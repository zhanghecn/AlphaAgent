/**
 * SectorTrendPanel — 板块趋势指标面板（共享组件）
 *
 * 显示 8 格网格：趋势状态、加权涨幅、涨跌家数、成交额、涨跌停等
 * 数据源: /sectors/{id}/trend API
 */
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { formatAmount, formatPct, priceColorClass } from "@/lib/utils";
import type { SectorTrend } from "@/api/types";

export function SectorTrendPanel({
  trend,
  isLoading,
  isError,
  onRetry,
}: {
  trend?: SectorTrend;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}) {
  if (isLoading) {
    return <LoadingState rows={2} />;
  }
  if (isError) {
    return <ErrorState message="板块趋势指标加载失败" onRetry={onRetry} />;
  }
  if (!trend) {
    return <div className="rounded-md border p-3 text-sm text-muted-foreground">暂无板块趋势指标</div>;
  }

  const primary = trend.turnover_weighted_change_pct ?? trend.avg_change_pct;
  return (
    <div className="rounded-md border">
      <div className="grid gap-0 sm:grid-cols-2 lg:grid-cols-4">
        <TrendMetric label="趋势" value={trendStateLabel(trend.trend_state)} valueClass={priceColorClass(primary)} />
        <TrendMetric label="成交额加权涨幅" value={formatPct(trend.turnover_weighted_change_pct)} valueClass={priceColorClass(trend.turnover_weighted_change_pct)} />
        <TrendMetric label="上涨家数" value={`${trend.rise_count}/${trend.sample_size}`} subValue={formatRatio(trend.rise_ratio)} valueClass={priceColorClass((trend.rise_ratio ?? 50) - 50)} />
        <TrendMetric label="板块成交额" value={formatAmount(trend.turnover)} />
      </div>
      <div className="grid gap-0 border-t sm:grid-cols-2 lg:grid-cols-4">
        <TrendMetric label="平均涨幅" value={formatPct(trend.avg_change_pct)} valueClass={priceColorClass(trend.avg_change_pct)} />
        <TrendMetric label="市值加权涨幅" value={formatPct(trend.market_cap_weighted_change_pct)} valueClass={priceColorClass(trend.market_cap_weighted_change_pct)} />
        <TrendMetric label="下跌家数" value={`${trend.fall_count}/${trend.sample_size}`} subValue={formatRatio(trend.fall_ratio)} valueClass={priceColorClass(50 - (trend.fall_ratio ?? 50))} />
        <TrendMetric label="涨跌停" value={`${trend.limit_up_count} / ${trend.limit_down_count}`} />
      </div>
      <div className="border-t px-3 py-2 text-xs text-muted-foreground">
        样本来自真实板块成分股行情，数据源: {trend.source ?? "--"}
      </div>
    </div>
  );
}

function TrendMetric({
  label,
  value,
  subValue,
  valueClass,
}: {
  label: string;
  value: string;
  subValue?: string;
  valueClass?: string;
}) {
  return (
    <div className="border-b px-3 py-2 last:border-b-0 sm:border-r lg:border-b-0">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-1 flex items-baseline gap-2">
        <span className={`text-sm font-semibold tabular-nums ${valueClass ?? ""}`}>{value}</span>
        {subValue && <span className="text-xs text-muted-foreground tabular-nums">{subValue}</span>}
      </div>
    </div>
  );
}

export function trendStateLabel(state: SectorTrend["trend_state"]) {
  if (state === "STRONG_UP") return "强势上涨";
  if (state === "UP") return "上涨";
  if (state === "STRONG_DOWN") return "强势下跌";
  if (state === "DOWN") return "下跌";
  if (state === "RANGE") return "震荡";
  return "未知";
}

export function formatRatio(value: number | null | undefined) {
  if (value == null) return "--";
  return `${value.toFixed(1)}%`;
}
