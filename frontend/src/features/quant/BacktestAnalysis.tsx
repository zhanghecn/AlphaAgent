import { BarChart3, Download, RefreshCw } from "lucide-react";
import { cn, formatAmount, formatPct, priceColorClass } from "@/lib/utils";
import { formatNumber, formatRobustnessValue, robustnessStatus } from "@/lib/backtest-utils";
import { InfoCell } from "@/components/InfoCell";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { backtestValidationGridCsvUrl, fetchBacktestReport, fetchBacktestValidationGrid } from "@/api/quant";
import { BacktestYearlyTable } from "./BacktestTables";

export function BacktestRobustnessPanel({
  checks,
}: {
  checks: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["robustness_checks"]>;
}) {
  return (
    <div className="space-y-3">
      <div className="overflow-hidden rounded-lg border">
        <div className="border-b px-3 py-2 text-sm font-medium">反过拟合检查</div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>检查项</TableHead>
              <TableHead>状态</TableHead>
              <TableHead className="text-right">数值</TableHead>
              <TableHead>结论</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {checks.diagnostics.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-medium">{row.label}</TableCell>
                <TableCell>{robustnessStatus(row.status)}</TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.value))}>
                  {formatRobustnessValue(row.value, row.value_type)}
                </TableCell>
                <TableCell className="text-muted-foreground">{row.message}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {checks.yearly_periods.length > 0 && <BacktestYearlyTable rows={checks.yearly_periods} />}

      <div className="overflow-hidden rounded-lg border">
        <div className="border-b px-3 py-2 text-sm font-medium">成本压力测试</div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>情景</TableHead>
              <TableHead className="text-right">额外成本</TableHead>
              <TableHead className="text-right">收益率</TableHead>
              <TableHead className="text-right">收益变化</TableHead>
              <TableHead className="text-right">期末权益</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {checks.cost_stress.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-medium">{row.label}</TableCell>
                <TableCell className="text-right tabular-nums">{formatAmount(row.extra_cost)}</TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.total_return_pct))}>
                  {formatPct(row.total_return_pct)}
                </TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_delta_pct))}>
                  {formatPct(row.return_delta_pct)}
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatAmount(row.final_equity)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {checks.random_baseline.status === "ready" && (
        <div className="rounded-lg border p-3 text-sm">
          <div className="font-medium">随机样本基准</div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            <InfoCell label="随机次数" value={checks.random_baseline.run_count} />
            <InfoCell label="每组股票" value={checks.random_baseline.sample_size} />
            <InfoCell label="平均收益" value={formatPct(checks.random_baseline.return_avg_pct)} />
            <InfoCell label="中位收益" value={formatPct(checks.random_baseline.return_median_pct)} />
            <InfoCell label="平均回撤" value={formatPct(checks.random_baseline.max_drawdown_avg_pct)} />
          </div>
        </div>
      )}
    </div>
  );
}

export function BacktestValidationGridPanel({
  backtestId,
  grid,
  isLoading,
  onRun,
}: {
  backtestId: number;
  grid?: Awaited<ReturnType<typeof fetchBacktestValidationGrid>>;
  isLoading: boolean;
  onRun: () => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div>
          <div className="text-sm font-medium">参数网格验证</div>
          <div className="text-xs text-muted-foreground">重新撮合 54 组关键参数，检查默认参数是否过拟合。</div>
        </div>
        <div className="flex gap-2">
          {grid?.status === "ready" && (
            <Button asChild variant="outline" size="sm">
              <a href={backtestValidationGridCsvUrl(backtestId, 54)} download>
                <Download size={15} />
                导出网格
              </a>
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={onRun} disabled={isLoading}>
            {isLoading ? <RefreshCw size={15} className="animate-spin" /> : <BarChart3 size={15} />}
            运行网格
          </Button>
        </div>
      </div>

      {!grid ? (
        <div className="p-3 text-sm text-muted-foreground">点击运行后，会用同一股票池和交易区间重跑不同入场分、止损、止盈、严格入场组合。</div>
      ) : grid.status !== "ready" ? (
        <div className="p-3 text-sm text-muted-foreground">网格验证状态：{grid.status}</div>
      ) : (
        <div className="space-y-3 p-3">
          <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-5">
            <InfoCell label="组合数量" value={`${grid.summary.variant_count}组`} />
            <InfoCell label="盈利占比" value={formatPct(grid.summary.positive_ratio)} />
            <InfoCell label="样本外盈利" value={formatPct(grid.summary.out_sample_positive_ratio)} />
            <InfoCell label="跑赢等权" value={formatPct(grid.summary.sample_excess_positive_ratio)} />
            <InfoCell label="当前样本外排名" value={grid.summary.base_out_sample_rank ? `${grid.summary.base_out_sample_rank}/${grid.summary.variant_count}` : "--"} />
          </div>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>检查项</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className="text-right">数值</TableHead>
                <TableHead>结论</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {grid.diagnostics.map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="font-medium">{row.label}</TableCell>
                  <TableCell>{robustnessStatus(row.status)}</TableCell>
                  <TableCell className={cn("text-right tabular-nums", priceColorClass(row.value))}>
                    {formatRobustnessValue(row.value, row.value_type)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{row.message}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {grid.walk_forward && <BacktestWalkForwardPanel analysis={grid.walk_forward} />}

          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>组合</TableHead>
                  <TableHead className="text-right">入场分</TableHead>
                  <TableHead className="text-right">止损</TableHead>
                  <TableHead className="text-right">止盈</TableHead>
                  <TableHead>严格</TableHead>
                  <TableHead className="text-right">总收益</TableHead>
                  <TableHead className="text-right">样本外</TableHead>
                  <TableHead className="text-right">等权超额</TableHead>
                  <TableHead className="text-right">回撤</TableHead>
                  <TableHead className="text-right">交易</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {grid.top_variants.slice(0, 10).map((row) => (
                  <TableRow key={row.variant_id}>
                    <TableCell className="font-medium">
                      #{row.variant_id}{row.is_base_params ? " 当前" : ""}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatNumber(row.min_entry_score, 0)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatPct(row.stop_loss_pct * 100)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatPct(row.take_profit_pct * 100)}</TableCell>
                    <TableCell>{row.strict_entry ? "是" : "否"}</TableCell>
                    <TableCell className={cn("text-right tabular-nums", priceColorClass(row.total_return_pct))}>
                      {formatPct(row.total_return_pct)}
                    </TableCell>
                    <TableCell className={cn("text-right tabular-nums", priceColorClass(row.out_sample_return_pct))}>
                      {formatPct(row.out_sample_return_pct)}
                    </TableCell>
                    <TableCell className={cn("text-right tabular-nums", priceColorClass(row.sample_equal_weight_excess_pct))}>
                      {formatPct(row.sample_equal_weight_excess_pct)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-fall">{formatPct(row.max_drawdown_pct)}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.trade_count ?? "--"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {grid.limitations.length > 0 && (
            <div className="border-t pt-2 text-xs text-muted-foreground">{grid.limitations[0]}</div>
          )}
        </div>
      )}
    </div>
  );
}

export function BacktestWalkForwardPanel({
  analysis,
}: {
  analysis: NonNullable<Awaited<ReturnType<typeof fetchBacktestValidationGrid>>["walk_forward"]>;
}) {
  if (analysis.status !== "ready" || !analysis.summary) {
    return (
      <div className="rounded-lg border p-3 text-sm text-muted-foreground">
        Walk-forward 状态：{analysis.status}
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-lg border p-3">
      <div>
        <div className="text-sm font-medium">Walk-forward 验证</div>
        <div className="text-xs text-muted-foreground">
          训练 {analysis.train_days} 日选参数，随后 {analysis.test_days} 日只验证未来窗口。
        </div>
      </div>

      <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-5">
        <InfoCell label="折叠数量" value={`${analysis.summary.fold_count}个`} />
        <InfoCell label="测试盈利占比" value={formatPct(analysis.summary.positive_test_ratio)} />
        <InfoCell label="测试超额占比" value={formatPct(analysis.summary.excess_positive_ratio)} />
        <InfoCell label="测试平均收益" value={formatPct(analysis.summary.test_return_avg_pct)} />
        <InfoCell label="测试平均超额" value={formatPct(analysis.summary.test_excess_avg_pct)} />
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>检查项</TableHead>
            <TableHead>状态</TableHead>
            <TableHead className="text-right">数值</TableHead>
            <TableHead>结论</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {analysis.diagnostics.map((row) => (
            <TableRow key={row.id}>
              <TableCell className="font-medium">{row.label}</TableCell>
              <TableCell>{robustnessStatus(row.status)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.value))}>
                {formatRobustnessValue(row.value, row.value_type)}
              </TableCell>
              <TableCell className="text-muted-foreground">{row.message}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>折叠</TableHead>
              <TableHead>训练区间</TableHead>
              <TableHead>测试区间</TableHead>
              <TableHead className="text-right">参数</TableHead>
              <TableHead className="text-right">训练收益</TableHead>
              <TableHead className="text-right">测试收益</TableHead>
              <TableHead className="text-right">测试超额</TableHead>
              <TableHead className="text-right">测试回撤</TableHead>
              <TableHead className="text-right">测试交易</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {analysis.folds.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-medium">#{row.selected_variant_id}</TableCell>
                <TableCell className="text-muted-foreground">
                  {row.train_start_date} 至 {row.train_end_date}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {row.test_start_date} 至 {row.test_end_date}
                </TableCell>
                <TableCell className="text-right text-xs tabular-nums">
                  {formatNumber(row.min_entry_score, 0)} / {formatPct(row.stop_loss_pct * 100)} / {formatPct(row.take_profit_pct * 100)} / {row.strict_entry ? "严" : "宽"}
                </TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.train_return_pct))}>
                  {formatPct(row.train_return_pct)}
                </TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.test_return_pct))}>
                  {formatPct(row.test_return_pct)}
                </TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.test_excess_return_pct))}>
                  {formatPct(row.test_excess_return_pct)}
                </TableCell>
                <TableCell className="text-right tabular-nums text-fall">{formatPct(row.test_max_drawdown_pct)}</TableCell>
                <TableCell className="text-right tabular-nums">{row.test_trade_count}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

export function BacktestRealityStats({
  metrics,
}: {
  metrics: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["extended_metrics"]>;
}) {
  const executionModes = metrics.execution_modes ?? {};
  return (
    <div className="grid gap-2 border-t pt-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
      <InfoCell label="平均持仓" value={`${formatNumber(metrics.average_holding_days, 1)}天`} />
      <InfoCell label="持仓中位数" value={`${formatNumber(metrics.median_holding_days, 1)}天`} />
      <InfoCell label="成交额" value={formatAmount(metrics.traded_amount)} />
      <InfoCell label="换手估算" value={formatPct(metrics.turnover_pct)} />
      <InfoCell label="平均仓位" value={formatPct(metrics.average_exposure_pct)} />
      <InfoCell label="最大持仓数" value={`${metrics.max_position_count}只`} />
      <InfoCell label="成交订单" value={`${metrics.filled_order_count}笔`} />
      <InfoCell label="未成交订单" value={`${metrics.rejected_order_count}笔`} />
      <InfoCell label="分钟尾盘买入" value={`${executionModes.minute_tail_ma5 ?? 0}笔`} />
      <InfoCell label="开盘回退买入" value={`${executionModes.daily_next_open_fallback ?? 0}笔`} />
    </div>
  );
}

export function BacktestExecutionQualityPanel({
  quality,
}: {
  quality: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["execution_quality"]>;
}) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div className="text-sm font-medium">成交真实性检查</div>
        <span
          className={cn(
            "rounded-md border px-2 py-1 text-xs",
            quality.status === "pass" ? "border-green-200 bg-green-50 text-rise dark:border-green-500/30 dark:bg-green-500/10" : "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300"
          )}
        >
          {quality.status === "pass" ? "通过" : "有缺口"}
        </span>
      </div>
      <div className="space-y-3 p-3">
        <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-6">
          <InfoCell label="买入笔数" value={`${quality.buy_count}笔`} />
          <InfoCell label="尾盘分钟成交" value={`${quality.minute_tail_entry_count}笔`} />
          <InfoCell label="严格拒单" value={`${quality.strict_tail_rejected_count ?? 0}笔`} />
          <InfoCell label="尾盘成交占比" value={formatPct(quality.minute_tail_entry_ratio)} />
          <InfoCell label="开盘回退占比" value={formatPct(quality.daily_open_fallback_ratio)} />
          <InfoCell label="分钟线条数" value={quality.minute_bar_count.toLocaleString()} />
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>检查项</TableHead>
              <TableHead>状态</TableHead>
              <TableHead className="text-right">数值</TableHead>
              <TableHead>结论</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {quality.diagnostics.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-medium">{row.label}</TableCell>
                <TableCell>{robustnessStatus(row.status)}</TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.value))}>
                  {formatRobustnessValue(row.value, row.value_type)}
                </TableCell>
                <TableCell className="text-muted-foreground">{row.message}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

export function BacktestOrderStatsPanel({
  stats,
}: {
  stats: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["order_stats"]>;
}) {
  const reasonRows = Object.entries(stats.by_reason).sort((a, b) => b[1] - a[1]);
  return (
    <div className="rounded-lg border p-3 text-sm">
      <div className="font-medium">成交约束</div>
      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        <InfoCell label="订单总数" value={`${stats.total}笔`} />
        <InfoCell label="已成交" value={`${stats.by_status.filled ?? 0}笔`} />
        <InfoCell label="未成交" value={`${stats.by_status.rejected ?? 0}笔`} />
      </div>
      {reasonRows.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {reasonRows.map(([reason, count]) => (
            <span key={reason} className="rounded-md border px-2 py-1 text-xs text-muted-foreground">
              {reason}: {count}
            </span>
          ))}
        </div>
      )}
      {stats.rejected_examples.length > 0 && (
        <div className="mt-3 overflow-hidden rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>日期</TableHead>
                <TableHead>股票</TableHead>
                <TableHead>方向</TableHead>
                <TableHead>原因</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {stats.rejected_examples.slice(0, 5).map((row, index) => (
                <TableRow key={`${row.trade_date}-${row.vt_symbol}-${index}`}>
                  <TableCell className="tabular-nums">{row.trade_date}</TableCell>
                  <TableCell>
                    <StockIdentityLink name={row.name} vtSymbol={row.vt_symbol} board={row.board} boardLabel={row.board_label} />
                  </TableCell>
                  <TableCell>{row.side === "BUY" ? "买入" : "卖出"}</TableCell>
                  <TableCell className="text-muted-foreground">{row.reason ?? "--"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

export function BacktestDataQuality({
  data,
  limitations,
}: {
  data?: Awaited<ReturnType<typeof fetchBacktestReport>>["data_quality"];
  limitations: string[];
}) {
  const tableNames = ["stocks", "stock_daily_bars", "stock_financial_reports", "sector_period_scores", "stock_fund_flows", "stock_hot_ranks", "stock_lhb_records"];
  const dailyBars = data?.stock_daily_bars;
  const financialReports = data?.stock_financial_reports;
  const turnoverCoverage = !Array.isArray(dailyBars) ? numberValue(dailyBars?.turnover_coverage_pct) : undefined;
  return (
    <div className="rounded-lg border p-3 text-sm">
      <div className="font-medium">数据质量和限制</div>
      {data && (
        <>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {tableNames.map((name) => {
              const item = data[name];
              const count = item && !Array.isArray(item) ? item.count : undefined;
              return <InfoCell key={name} label={name} value={count?.toLocaleString()} />;
            })}
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <InfoCell label="日线成交额覆盖" value={formatPct(turnoverCoverage)} />
            <InfoCell label="可用于回测财报" value={(!Array.isArray(financialReports) ? financialReports?.count : 0)?.toLocaleString()} />
          </div>
        </>
      )}
      <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
        {[...(data?.limitations ?? []), ...limitations].map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function numberValue(value: unknown): number | undefined {
  if (typeof value === "number") return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}
