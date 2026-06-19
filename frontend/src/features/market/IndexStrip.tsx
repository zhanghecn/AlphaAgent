import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchMarketOverview } from "@/api/market";
import { CardSkeleton } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { formatPrice, formatPct, formatAmount, priceColorClass } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { ArrowRight, TrendingUp, TrendingDown, Minus } from "lucide-react";
import type { IndexQuote, StockQuote } from "@/api/types";

function MarketStateBadge({ state }: { state: string }) {
  const variant =
    state === "RISK_ON"
      ? "default"
      : state === "RISK_OFF"
        ? "destructive"
        : "secondary";
  const label =
    state === "RISK_ON"
      ? "偏多"
      : state === "RISK_OFF"
        ? "偏空"
        : state === "RANGE"
          ? "震荡"
          : "未知";
  return <Badge variant={variant}>{label}</Badge>;
}

function IndexCard({ quote }: { quote: IndexQuote }) {
  const colorClass = priceColorClass(quote.change_pct);
  const Icon =
    (quote.change_pct ?? 0) > 0
      ? TrendingUp
      : (quote.change_pct ?? 0) < 0
        ? TrendingDown
        : Minus;

  return (
    <Link
      to={`/indices/${quote.vt_symbol}`}
      className="flex h-full items-center gap-4 rounded-lg border p-4 transition-colors hover:bg-muted/50"
    >
      <Icon size={20} className={colorClass} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-muted-foreground truncate">
          {quote.name}
        </p>
        <p className={`font-display text-xl font-bold tabular-nums ${colorClass}`}>
          {formatPrice(quote.last_price)}
        </p>
      </div>
      <div className="text-right space-y-1">
        <p className={`text-sm font-semibold tabular-nums ${colorClass}`}>
          {formatPct(quote.change_pct)}
        </p>
        <p className="text-xs text-muted-foreground tabular-nums">
          成交额 {formatAmount(quote.turnover)}
        </p>
      </div>
      <ArrowRight size={16} className="text-muted-foreground" />
    </Link>
  );
}

function ActiveStockTable({ items }: { items: StockQuote[] }) {
  if (!items.length) return null;

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-display text-sm font-medium">活跃 A 股</h3>
        <Link to="/stocks" className="text-xs text-muted-foreground hover:text-foreground">
          查看全部
        </Link>
      </div>
      <div className="overflow-x-auto rounded-md border">
        <table className="min-w-[720px] w-full text-sm">
          <thead className="bg-muted/60 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">代码</th>
              <th className="px-3 py-2 text-left">名称</th>
              <th className="px-3 py-2 text-right">最新价</th>
              <th className="px-3 py-2 text-right">涨跌幅</th>
              <th className="px-3 py-2 text-right">成交额</th>
              <th className="px-3 py-2 text-right">换手率</th>
            </tr>
          </thead>
          <tbody>
            {items.slice(0, 10).map((stock) => (
              <tr key={stock.vt_symbol} className="border-t hover:bg-muted/40">
                <td className="px-3 py-2 font-mono text-xs">
                  <Link to={`/stocks/${stock.vt_symbol}`} className="hover:underline">
                    {stock.symbol}
                  </Link>
                </td>
                <td className="px-3 py-2">
                  <StockIdentityLink
                    name={stock.name}
                    vtSymbol={stock.vt_symbol}
                    board={stock.board}
                    boardLabel={stock.board_label}
                  />
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{formatPrice(stock.last_price)}</td>
                <td className={`px-3 py-2 text-right font-medium tabular-nums ${priceColorClass(stock.change_pct)}`}>
                  {formatPct(stock.change_pct)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{formatAmount(stock.turnover)}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {stock.turnover_rate != null ? `${stock.turnover_rate.toFixed(2)}%` : "--"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function IndexStrip() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["market", "overview"],
    queryFn: fetchMarketOverview,
  });

  if (isLoading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "加载市场概览失败"}
        onRetry={() => refetch()}
      />
    );
  }

  if (!data || !data.indices?.length) {
    return <div className="text-sm text-muted-foreground">暂无指数数据</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <MarketStateBadge state={data.market_state} />
        <span className="text-xs text-muted-foreground">
          交易日 {data.trade_date}
        </span>
        {data.updated_at && (
          <span className="text-xs text-muted-foreground">
            更新于 {new Date(data.updated_at).toLocaleTimeString("zh-CN")}
          </span>
        )}
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {data.indices.map((idx) => (
          <IndexCard key={idx.vt_symbol} quote={idx} />
        ))}
      </div>
      <ActiveStockTable items={data.active_stocks ?? []} />
    </div>
  );
}
