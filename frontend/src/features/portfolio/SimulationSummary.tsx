import { cn, formatAmount, formatPct, formatPrice, priceColorClass } from "@/lib/utils";
import { formatTime } from "@/lib/backtest-utils";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { Briefcase } from "lucide-react";
import type { SimulationPosition } from "@/api/quant";

export interface SimulationSummaryProps {
  items: SimulationPosition[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}

/**
 * SimulationSummary — bottom panel showing all simulated positions in a compact table.
 */
export function SimulationSummary({ items, isLoading, isError, onRetry }: SimulationSummaryProps) {
  if (isLoading) return <LoadingState rows={4} />;
  if (isError) return <ErrorState message="加载模拟持仓失败" onRetry={onRetry} />;

  return (
    <section className="rounded-lg border">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <Briefcase size={16} />
          <h2 className="text-sm font-semibold">模拟持仓明细</h2>
        </div>
        <span className="text-xs text-muted-foreground">{items.length} 只 · 30 秒轮询刷新</span>
      </div>
      {items.length === 0 ? (
        <div className="p-4">
          <EmptyState
            message="暂无模拟持仓"
            description="可以从量化候选模拟建仓，或手动下模拟单。"
          />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground bg-muted/50">
              <tr>
                <th className="px-4 py-2 text-left">股票</th>
                <th className="px-4 py-2 text-right">成本</th>
                <th className="px-4 py-2 text-right">现价</th>
                <th className="px-4 py-2 text-right">数量</th>
                <th className="px-4 py-2 text-right">浮盈亏</th>
                <th className="px-4 py-2 text-left">买入/卖出时机</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={`${item.account_id}-${item.vt_symbol}`} className="border-t hover:bg-muted/30">
                  <td className="px-4 py-2">
                    <StockIdentityLink
                      name={item.name}
                      vtSymbol={item.vt_symbol}
                      board={item.board}
                      boardLabel={item.board_label}
                      meta={item.account_name ?? "模拟账户"}
                    />
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">{formatPrice(item.cost_price)}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{formatPrice(item.last_price)}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{item.volume.toLocaleString()}</td>
                  <td
                    className={cn(
                      "px-4 py-2 text-right tabular-nums",
                      priceColorClass(item.floating_pnl_pct)
                    )}
                  >
                    <div>{formatAmount(item.floating_pnl)}</div>
                    <div className="text-xs">{formatPct(item.floating_pnl_pct)}</div>
                  </td>
                  <td className="max-w-[320px] px-4 py-2 text-xs text-muted-foreground">
                    <div>
                      买入 {formatTime(item.last_buy_time)} · {formatPrice(item.last_buy_price)}
                      {item.last_buy_volume ? ` · ${item.last_buy_volume} 股` : ""}
                    </div>
                    {item.last_sell_time && (
                      <div className="mt-1">
                        卖出 {formatTime(item.last_sell_time)} · {formatPrice(item.last_sell_price)} · 盈亏{" "}
                        <span className={priceColorClass(item.last_sell_pnl)}>
                          {formatAmount(item.last_sell_pnl)}
                        </span>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
