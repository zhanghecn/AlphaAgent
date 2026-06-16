import { RefreshCw, Scale } from "lucide-react";
import type { BacktestStrategyComparison } from "@/api/quant";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn, formatAmount, formatPct, priceColorClass } from "@/lib/utils";

export function BacktestStrategyComparisonPanel({
  comparison,
  isLoading,
  error,
  onRun,
}: {
  comparison?: BacktestStrategyComparison;
  isLoading: boolean;
  error?: unknown;
  onRun: () => void;
}) {
  return (
    <section className="rounded-lg border p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-medium">
            <Scale size={15} />
            策略同口径对比
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            用当前日线回测参数非持久化重跑已注册策略，比较 BUY、成交、拒单、收益和回撤。
          </p>
        </div>
        <Button size="sm" variant="outline" onClick={onRun} disabled={isLoading}>
          {isLoading ? <RefreshCw size={15} className="animate-spin" /> : <Scale size={15} />}
          运行策略对比
        </Button>
      </div>

      {error ? (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-2 text-sm text-fall dark:border-red-500/30 dark:bg-red-500/10">
          {error instanceof Error ? error.message : "策略对比失败"}
        </div>
      ) : null}

      {comparison ? (
        <div className="mt-3 space-y-3">
          {comparison.summary ? (
            <div className="grid gap-3 text-sm md:grid-cols-5">
              <InfoCell label="策略数" value={`${comparison.summary.ready_count ?? 0}/${comparison.summary.strategy_count ?? 0}`} />
              <InfoCell label="收益排序最优" value={comparison.summary.best_strategy_id ?? "--"} />
              <InfoCell
                label="收益排序"
                value={formatPct(comparison.summary.best_total_return_pct)}
                valueClass={priceColorClass(comparison.summary.best_total_return_pct)}
              />
              <InfoCell label="日线最优" value={comparison.summary.best_verifiable_strategy_id ?? "--"} />
              <InfoCell label="完成策略数" value={`${comparison.summary.ready_count ?? comparison.summary.complete_strict_count ?? 0} 个`} />
            </div>
          ) : null}

          <div className="overflow-hidden rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>策略</TableHead>
                  <TableHead>质量</TableHead>
                  <TableHead className="text-right">收益</TableHead>
                  <TableHead className="text-right">回撤</TableHead>
                  <TableHead className="text-right">期末权益</TableHead>
                  <TableHead className="text-right">BUY信号</TableHead>
                  <TableHead className="text-right">买入</TableHead>
                  <TableHead className="text-right">拒单</TableHead>
                  <TableHead className="text-right">成交行</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {comparison.rows.map((row) => (
                  <TableRow key={row.strategy_id}>
                    <TableCell>
                      <div className="font-medium">{row.strategy_name ?? row.strategy_id}</div>
                      <div className="text-xs text-muted-foreground">{row.strategy_id} / {row.strategy_version ?? "--"}</div>
                    </TableCell>
                    <TableCell>
                      <div className={cn("text-sm font-medium", qualityColorClass(row.quality_status))}>
                        {row.quality_label ?? "--"}
                      </div>
                      {row.quality_warning ? (
                        <div className="max-w-64 text-xs text-muted-foreground">{row.quality_warning}</div>
                      ) : null}
                    </TableCell>
                    <TableCell className={cn("text-right tabular-nums", priceColorClass(row.total_return_pct))}>
                      {formatPct(row.total_return_pct)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-fall">{formatPct(row.max_drawdown_pct)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatAmount(row.final_equity)}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.buy_signal_count ?? "--"}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.buy_count ?? "--"}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.rejected_order_count ?? "--"}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.total_trade_rows ?? "--"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="text-xs text-muted-foreground">
            {comparison.summary?.message ?? comparison.note ?? "策略对比不替代多年全 A、walk-forward 和参数敏感性验证。"}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function InfoCell({ label, value, valueClass }: { label: string; value?: string | number | null; valueClass?: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 font-medium tabular-nums", valueClass)}>{value ?? "--"}</div>
    </div>
  );
}

function qualityColorClass(status?: string | null) {
  if (status === "complete_strict") return "text-rise";
  if (status === "strict_condition_rejections") return "text-amber-600 dark:text-amber-400";
  if (status === "missing_snapshots" || status === "uses_daily_close_proxy") return "text-fall";
  if (status === "no_fills") return "text-muted-foreground";
  return "";
}
