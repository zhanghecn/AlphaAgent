import { cn, formatAmount, formatPct, formatPrice, priceColorClass } from "@/lib/utils";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { BacktestClosedTrade } from "@/api/quant";
import { fetchBacktestReport } from "@/api/quant";

// ── 1. Recent trades ────────────────────────────────────────────────────────

export function BacktestTradeTable({ trades }: { trades: Awaited<ReturnType<typeof fetchBacktestReport>>["trades"] }) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div className="text-sm font-medium">最近买卖点</div>
      </div>
      {trades.length === 0 ? (
        <div className="p-3 text-sm text-muted-foreground">当前回测没有成交记录。</div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>日期</TableHead>
              <TableHead>股票</TableHead>
              <TableHead>方向</TableHead>
              <TableHead className="text-right">价格</TableHead>
              <TableHead className="text-right">数量</TableHead>
              <TableHead className="text-right">盈亏</TableHead>
              <TableHead>原因</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {trades.slice(0, 12).map((trade, index) => (
              <TableRow key={`${trade.trade_date}-${trade.vt_symbol}-${index}`}>
                <TableCell className="tabular-nums">{trade.trade_date}</TableCell>
                <TableCell>
                  <StockIdentityLink name={trade.name} vtSymbol={trade.vt_symbol} board={trade.board} boardLabel={trade.board_label} />
                </TableCell>
                <TableCell>{trade.side === "BUY" ? "买入" : "卖出"}</TableCell>
                <TableCell className="text-right tabular-nums">{formatPrice(trade.price)}</TableCell>
                <TableCell className="text-right tabular-nums">{trade.volume.toLocaleString()}</TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(trade.pnl))}>
                  {trade.pnl == null ? "--" : formatAmount(trade.pnl)}
                </TableCell>
                <TableCell className="text-muted-foreground">{trade.reason ?? "--"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

// ── 2. Benchmark comparison ─────────────────────────────────────────────────

export function BacktestBenchmarkTable({
  benchmarks,
}: {
  benchmarks: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["benchmark"]>["benchmarks"];
}) {
  if (benchmarks.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">基准对比</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>基准</TableHead>
            <TableHead>状态</TableHead>
            <TableHead className="text-right">基准收益</TableHead>
            <TableHead className="text-right">策略收益</TableHead>
            <TableHead className="text-right">超额收益</TableHead>
            <TableHead className="text-right">基准回撤</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {benchmarks.map((row) => (
            <TableRow key={row.id}>
              <TableCell>
                <div className="font-medium">{row.name}</div>
                {row.reason && <div className="text-xs text-muted-foreground">{row.reason}</div>}
              </TableCell>
              <TableCell>{row.status === "ready" ? "可用" : "缺失"}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>
                {formatPct(row.return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.strategy_return_pct))}>
                {formatPct(row.strategy_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.excess_return_pct))}>
                {formatPct(row.excess_return_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-fall">{formatPct(row.max_drawdown_pct)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ── 3. In-sample / out-sample ───────────────────────────────────────────────

export function BacktestPeriodTable({
  analysis,
}: {
  analysis: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["period_analysis"]>;
}) {
  if (analysis.periods.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">样本内 / 样本外</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>分段</TableHead>
            <TableHead>区间</TableHead>
            <TableHead className="text-right">策略收益</TableHead>
            <TableHead className="text-right">基准收益</TableHead>
            <TableHead className="text-right">超额收益</TableHead>
            <TableHead className="text-right">回撤</TableHead>
            <TableHead className="text-right">胜率</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {analysis.periods.map((row) => (
            <TableRow key={row.id}>
              <TableCell className="font-medium">{row.label}</TableCell>
              <TableCell className="text-muted-foreground">
                {row.start_date} 至 {row.end_date}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>
                {formatPct(row.return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.benchmark_return_pct))}>
                {formatPct(row.benchmark_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.excess_return_pct))}>
                {formatPct(row.excess_return_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-fall">{formatPct(row.max_drawdown_pct)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPct(row.win_rate * 100)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {analysis.note && <div className="border-t px-3 py-2 text-xs text-muted-foreground">{analysis.note}</div>}
    </div>
  );
}

// ── 4. Market regime ────────────────────────────────────────────────────────

export function BacktestRegimeTable({
  analysis,
}: {
  analysis: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["regime_analysis"]>;
}) {
  if (analysis.periods.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">市场环境分段</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>环境</TableHead>
            <TableHead className="text-right">窗口</TableHead>
            <TableHead className="text-right">策略均值</TableHead>
            <TableHead className="text-right">基准均值</TableHead>
            <TableHead className="text-right">回撤</TableHead>
            <TableHead className="text-right">胜率</TableHead>
            <TableHead className="text-right">盈亏</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {analysis.periods.map((row) => (
            <TableRow key={row.regime}>
              <TableCell className="font-medium">{row.label}</TableCell>
              <TableCell className="text-right tabular-nums">{row.window_count}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_strategy_return_pct))}>
                {formatPct(row.avg_strategy_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_benchmark_return_pct))}>
                {formatPct(row.avg_benchmark_return_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-fall">{formatPct(row.max_drawdown_pct)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPct(row.win_rate * 100)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.pnl))}>
                {formatAmount(row.pnl)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {analysis.note && <div className="border-t px-3 py-2 text-xs text-muted-foreground">{analysis.note}</div>}
    </div>
  );
}

// ── 5. Monthly returns ──────────────────────────────────────────────────────

export function BacktestMonthlyTable({ rows }: { rows: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["monthly_returns"]> }) {
  if (rows.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">月度收益</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>月份</TableHead>
            <TableHead>区间</TableHead>
            <TableHead className="text-right">月收益</TableHead>
            <TableHead className="text-right">月内回撤</TableHead>
            <TableHead className="text-right">期末权益</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.month}>
              <TableCell className="font-medium tabular-nums">{row.month}</TableCell>
              <TableCell className="text-muted-foreground">
                {row.start_date ?? "--"} 至 {row.end_date ?? "--"}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>
                {formatPct(row.return_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-fall">{formatPct(row.max_drawdown_pct)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatAmount(row.end_equity)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ── 6. Per-stock performance ────────────────────────────────────────────────

export function BacktestSymbolTable({
  rows,
  compact = false,
  onAddToPortfolio,
}: {
  rows: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["symbol_performance"]>;
  compact?: boolean;
  onAddToPortfolio?: (vtSymbol: string) => void;
}) {
  if (rows.length === 0) return null;
  const showAction = !compact && onAddToPortfolio;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">个股贡献</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>股票</TableHead>
            <TableHead className="text-right">闭仓</TableHead>
            <TableHead className="text-right">胜率</TableHead>
            <TableHead className="text-right">收益</TableHead>
            <TableHead className="text-right">投入回报</TableHead>
            <TableHead className="text-right">最差单笔</TableHead>
            {showAction && <TableHead className="text-right">操作</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.slice(0, compact ? 6 : 12).map((row) => (
            <TableRow key={row.vt_symbol}>
              <TableCell>
                <StockIdentityLink name={row.name} vtSymbol={row.vt_symbol} board={row.board} boardLabel={row.board_label} />
              </TableCell>
              <TableCell className="text-right tabular-nums">{row.trade_count}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPct(row.win_rate * 100)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.pnl))}>
                {formatAmount(row.pnl)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>
                {formatPct(row.return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.worst_trade))}>
                {formatAmount(row.worst_trade)}
              </TableCell>
              {showAction && (
                <TableCell className="text-right">
                  <button
                    type="button"
                    className="text-xs text-primary hover:underline"
                    onClick={() => onAddToPortfolio(row.vt_symbol)}
                  >
                    加入持仓
                  </button>
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {compact && rows.length > 6 && (
        <div className="border-t px-3 py-2 text-xs text-muted-foreground">更多个股贡献在"交易归因"页签查看。</div>
      )}
    </div>
  );
}

// ── 7. Worst trades ─────────────────────────────────────────────────────────

export function BacktestWorstTrades({ rows }: { rows: BacktestClosedTrade[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">最差交易</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>股票</TableHead>
            <TableHead>买入/卖出</TableHead>
            <TableHead className="text-right">持仓</TableHead>
            <TableHead className="text-right">收益率</TableHead>
            <TableHead className="text-right">盈亏</TableHead>
            <TableHead>退出原因</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.slice(0, 10).map((row, index) => (
            <TableRow key={`${row.vt_symbol}-${row.exit_date}-${index}`}>
              <TableCell>
                <StockIdentityLink name={row.name} vtSymbol={row.vt_symbol} board={row.board} boardLabel={row.board_label} />
              </TableCell>
              <TableCell className="text-muted-foreground">
                {row.entry_date ?? "--"} / {row.exit_date ?? "--"}
              </TableCell>
              <TableCell className="text-right tabular-nums">{row.holding_days ?? "--"}天</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>
                {formatPct(row.return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.pnl))}>
                {formatAmount(row.pnl)}
              </TableCell>
              <TableCell className="text-muted-foreground">{row.exit_reason ?? "--"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

// ── 8. Yearly performance breakdown ─────────────────────────────────────────

export function BacktestYearlyTable({
  rows,
}: {
  rows: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["robustness_checks"]>["yearly_periods"];
}) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">年度分段</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>年份</TableHead>
            <TableHead className="text-right">策略收益</TableHead>
            <TableHead className="text-right">基准收益</TableHead>
            <TableHead className="text-right">超额收益</TableHead>
            <TableHead className="text-right">回撤</TableHead>
            <TableHead className="text-right">胜率</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.id}>
              <TableCell className="font-medium">{row.label}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>
                {formatPct(row.return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.benchmark_return_pct))}>
                {formatPct(row.benchmark_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.excess_return_pct))}>
                {formatPct(row.excess_return_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-fall">{formatPct(row.max_drawdown_pct)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPct(row.win_rate * 100)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
