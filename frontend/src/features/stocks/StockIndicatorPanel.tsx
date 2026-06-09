import { useQuery } from "@tanstack/react-query";
import { fetchStockIndicators } from "@/api/stocks";
import type { TechnicalIndicators } from "@/api/types";
import { CardSkeleton } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { dataSourceLabel, formatAmount, formatPct, formatPrice, priceColorClass } from "@/lib/utils";

interface StockIndicatorPanelProps {
  vtSymbol: string;
}

export function StockIndicatorPanel({ vtSymbol }: StockIndicatorPanelProps) {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["stock-indicators", vtSymbol],
    queryFn: () => fetchStockIndicators(vtSymbol),
  });

  if (isLoading) return <CardSkeleton />;
  if (isError)
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "指标加载失败"}
        onRetry={() => refetch()}
      />
    );

  return <TechnicalIndicatorView indicators={data as TechnicalIndicators | undefined} />;
}

export function TechnicalIndicatorView({ indicators }: { indicators: TechnicalIndicators | undefined }) {
  const status = indicators?.status;
  const message = indicators?.message;

  if (status === "pending" || !indicators) {
    return (
      <EmptyState
        message="暂无技术指标"
        description={message ?? "当前 AkShare K 线样本不足或数据源暂时不可用"}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <IndicatorValue label="最新收盘" value={formatPrice(indicators.latest_close)} />
        <IndicatorValue
          label="最新涨跌"
          value={formatPct(indicators.latest_change_pct)}
          className={priceColorClass(indicators.latest_change_pct)}
        />
        <IndicatorValue label="样本日线" value={`${indicators.sample_size ?? 0} 条`} />
        <IndicatorValue label="数据" value={dataSourceLabel(indicators.source)} />
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <IndicatorGroup
          title="均线"
          items={[
            ["MA5", formatPrice(indicators.moving_average?.ma5)],
            ["MA10", formatPrice(indicators.moving_average?.ma10)],
            ["MA20", formatPrice(indicators.moving_average?.ma20)],
            ["MA60", formatPrice(indicators.moving_average?.ma60)],
          ]}
        />
        <IndicatorGroup
          title="阶段表现"
          items={[
            ["20 日涨跌", formatPct(indicators.period_return?.return_20d)],
            ["60 日涨跌", formatPct(indicators.period_return?.return_60d)],
            ["60 日最大回撤", formatPct(indicators.drawdown?.max_drawdown_60d)],
          ]}
        />
        <IndicatorGroup
          title="波动与量能"
          items={[
            ["20 日波动率", formatPct(indicators.volatility?.volatility_20d)],
            ["60 日波动率", formatPct(indicators.volatility?.volatility_60d)],
            ["量 MA5", formatAmount(indicators.volume_average?.volume_ma5)],
            ["量 MA20", formatAmount(indicators.volume_average?.volume_ma20)],
          ]}
        />
      </div>

      <div className="grid gap-3 lg:grid-cols-4">
        <IndicatorGroup
          title="BOLL"
          items={[
            ["上轨", formatPrice(indicators.bollinger?.upper)],
            ["中轨", formatPrice(indicators.bollinger?.mid)],
            ["下轨", formatPrice(indicators.bollinger?.lower)],
            ["带宽", formatPct(indicators.bollinger?.width)],
          ]}
        />
        <IndicatorGroup
          title="MACD"
          items={[
            ["DIF", formatSignedNumber(indicators.macd?.dif)],
            ["DEA", formatSignedNumber(indicators.macd?.dea)],
            ["MACD", formatSignedNumber(indicators.macd?.macd)],
          ]}
        />
        <IndicatorGroup
          title="KDJ"
          items={[
            ["K", formatNumber(indicators.kdj?.k)],
            ["D", formatNumber(indicators.kdj?.d)],
            ["J", formatNumber(indicators.kdj?.j)],
          ]}
        />
        <IndicatorGroup
          title="RSI"
          items={[
            ["RSI6", formatNumber(indicators.rsi?.rsi6)],
            ["RSI12", formatNumber(indicators.rsi?.rsi12)],
            ["RSI24", formatNumber(indicators.rsi?.rsi24)],
          ]}
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <IndicatorValue label="站上 MA20" value={formatBool(indicators.price_position?.above_ma20)} />
        <IndicatorValue label="站上 MA60" value={formatBool(indicators.price_position?.above_ma60)} />
        <IndicatorValue
          label="BOLL %B"
          value={
            indicators.price_position?.boll_percent_b == null
              ? "--"
              : indicators.price_position.boll_percent_b.toFixed(2)
          }
        />
      </div>
    </div>
  );
}

function IndicatorValue({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return (
    <div className="rounded-md border bg-background p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`mt-1 break-words text-sm font-semibold tabular-nums ${className}`}>{value}</p>
    </div>
  );
}

function IndicatorGroup({ title, items }: { title: string; items: [string, string][] }) {
  return (
    <div className="rounded-md border bg-background p-3">
      <h4 className="text-xs font-medium text-muted-foreground">{title}</h4>
      <dl className="mt-2 space-y-2">
        {items.map(([label, value]) => (
          <div key={label} className="flex items-center justify-between gap-3 text-sm">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="text-right font-medium tabular-nums">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function formatNumber(value: number | null | undefined): string {
  if (value == null) return "--";
  return value.toFixed(2);
}

function formatSignedNumber(value: number | null | undefined): string {
  if (value == null) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(3)}`;
}

function formatBool(value: boolean | null | undefined): string {
  if (value == null) return "--";
  return value ? "是" : "否";
}
