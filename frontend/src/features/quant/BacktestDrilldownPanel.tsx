import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchBacktestDailyDecisions,
  fetchBacktestDayDetail,
  fetchBacktestDrilldownOptions,
  fetchBacktestPathDiagnostics,
  fetchBacktestReport,
  fetchBacktestSignalEvents,
  fetchBacktestSymbolDetail,
  fetchBacktestTradeAttribution,
  type BacktestClosedTrade,
  type BacktestDailyDecisionRow,
  type BacktestDailyDecisionSummary,
  type BacktestDrilldownDateOption,
  type BacktestDrilldownSymbolOption,
  type BacktestOrderEvent,
  type BacktestPathDiagnosticsResponse,
  type BacktestTrade,
  type BacktestTradeAttribution,
  type BacktestTradeAttributionSummary,
} from "@/api/quant";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { InfoCell } from "@/components/InfoCell";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { BacktestDecisionTimeline } from "@/features/quant/BacktestDecisionTimeline";
import { executionModeLabel } from "@/lib/backtest-utils";
import { cn, formatPct, formatPrice, priceColorClass } from "@/lib/utils";

type BacktestReportData = Awaited<ReturnType<typeof fetchBacktestReport>>;

export function BacktestDrilldownPanel({
  backtestId,
  report,
}: {
  backtestId: number;
  report: BacktestReportData;
}) {
  const equityTail = report.equity_tail ?? [];
  const defaultDate = equityTail[equityTail.length - 1]?.trade_date ?? report.recent_trades?.[0]?.trade_date ?? report.trades[0]?.trade_date ?? report.end_date;
  const defaultSymbol = report.recent_trades?.[0]?.vt_symbol ?? report.trades[0]?.vt_symbol ?? report.symbol_performance?.[0]?.vt_symbol ?? "";
  const [selectedDate, setSelectedDate] = useState(defaultDate);
  const [selectedSymbol, setSelectedSymbol] = useState(defaultSymbol);
  const dailyPageSize = 30;
  const attributionPageSize = 30;
  const [dailyPage, setDailyPage] = useState(0);
  const [attributionPage, setAttributionPage] = useState(0);

  const optionsQuery = useQuery({
    queryKey: ["backtest-drilldown-options", backtestId],
    queryFn: () => fetchBacktestDrilldownOptions(backtestId),
    enabled: Boolean(backtestId),
  });

  const fallbackDateOptions = useMemo<BacktestDrilldownDateOption[]>(() => {
    const byDate = new Map<string, BacktestDrilldownDateOption>();
    for (const row of report.equity_tail ?? []) {
      byDate.set(row.trade_date, {
        trade_date: row.trade_date,
        cash: row.cash,
        market_value: row.market_value,
        total_equity: row.total_equity,
        drawdown_pct: row.drawdown_pct,
        position_count: row.position_count,
        buy_trade_count: 0,
        sell_trade_count: 0,
        buy_candidate_count: 0,
        watch_candidate_count: 0,
        buy_signal_count: 0,
        sell_signal_count: 0,
        filled_order_count: 0,
        rejected_order_count: 0,
        signal_event_count: 0,
        position_snapshot_count: 0,
      });
    }
    for (const row of report.recent_trades ?? report.trades) {
      const current = byDate.get(row.trade_date) ?? {
        trade_date: row.trade_date,
        position_count: 0,
        buy_trade_count: 0,
        sell_trade_count: 0,
        filled_order_count: 0,
        rejected_order_count: 0,
        signal_event_count: 0,
        position_snapshot_count: 0,
      };
      if (row.side === "BUY") current.buy_trade_count += 1;
      if (row.side === "SELL") current.sell_trade_count += 1;
      byDate.set(row.trade_date, current);
    }
    return [...byDate.values()].sort((left, right) => right.trade_date.localeCompare(left.trade_date));
  }, [report.equity_tail, report.recent_trades, report.trades]);

  const fallbackSymbolOptions = useMemo<BacktestDrilldownSymbolOption[]>(() => {
    const bySymbol = new Map<string, BacktestDrilldownSymbolOption>();
    for (const row of [...(report.recent_trades ?? report.trades), ...(report.symbol_performance ?? [])]) {
      if (!row.vt_symbol || bySymbol.has(row.vt_symbol)) continue;
      bySymbol.set(row.vt_symbol, {
        vt_symbol: row.vt_symbol,
        name: row.name,
        board: row.board,
        board_label: row.board_label,
        trade_count: 0,
        buy_trade_count: 0,
        sell_trade_count: 0,
        order_count: 0,
        filled_order_count: 0,
        rejected_order_count: 0,
        signal_event_count: 0,
        buy_signal_count: 0,
        sell_signal_count: 0,
        position_day_count: 0,
        status: "traded",
        status_label: "有成交",
      });
    }
    return [...bySymbol.values()];
  }, [report.recent_trades, report.symbol_performance, report.trades]);

  const dateOptions = optionsQuery.data?.dates?.length ? optionsQuery.data.dates : fallbackDateOptions;
  const symbolOptions = optionsQuery.data?.symbols?.length ? optionsQuery.data.symbols : fallbackSymbolOptions;
  const selectedDateSummary = dateOptions.find((item) => item.trade_date === selectedDate);
  const selectedSymbolSummary = symbolOptions.find((item) => item.vt_symbol === selectedSymbol);

  useEffect(() => {
    if (dateOptions.length > 0 && (!selectedDate || !dateOptions.some((item) => item.trade_date === selectedDate))) {
      setSelectedDate(dateOptions[0].trade_date);
    }
  }, [dateOptions, selectedDate]);

  useEffect(() => {
    if (symbolOptions.length > 0 && (!selectedSymbol || !symbolOptions.some((item) => item.vt_symbol === selectedSymbol))) {
      setSelectedSymbol(symbolOptions[0].vt_symbol);
    }
  }, [selectedSymbol, symbolOptions]);

  const dayQuery = useQuery({
    queryKey: ["backtest-day-detail", backtestId, selectedDate],
    queryFn: () => fetchBacktestDayDetail(backtestId, selectedDate),
    enabled: Boolean(backtestId && selectedDate),
  });

  const symbolQuery = useQuery({
    queryKey: ["backtest-symbol-detail", backtestId, selectedSymbol],
    queryFn: () => fetchBacktestSymbolDetail(backtestId, selectedSymbol),
    enabled: Boolean(backtestId && selectedSymbol),
  });

  const symbolSignalsQuery = useQuery({
    queryKey: ["backtest-symbol-signals", backtestId, selectedSymbol],
    queryFn: () => fetchBacktestSignalEvents(backtestId, { vt_symbol: selectedSymbol, limit: 2000 }),
    enabled: Boolean(backtestId && selectedSymbol),
    staleTime: 30_000,
  });

  const dailyDecisionsQuery = useQuery({
    queryKey: ["backtest-daily-decisions", backtestId, dailyPageSize, dailyPage],
    queryFn: () => fetchBacktestDailyDecisions(backtestId, { limit: dailyPageSize, offset: dailyPage * dailyPageSize, order: "desc" }),
    enabled: Boolean(backtestId),
    staleTime: 30_000,
  });

  const tradeAttributionQuery = useQuery({
    queryKey: ["backtest-trade-attribution", backtestId, attributionPageSize, attributionPage],
    queryFn: () => fetchBacktestTradeAttribution(backtestId, { limit: attributionPageSize, offset: attributionPage * attributionPageSize, sort: "pnl_asc" }),
    enabled: Boolean(backtestId),
    staleTime: 30_000,
  });
  const pathDiagnosticsQuery = useQuery({
    queryKey: ["backtest-path-diagnostics", backtestId],
    queryFn: () => fetchBacktestPathDiagnostics(backtestId),
    enabled: Boolean(backtestId),
    staleTime: 60_000,
  });

  const day = dayQuery.data;
  const symbol = symbolQuery.data;

  return (
    <div className="space-y-4">
      <DailyDecisionTable
        rows={dailyDecisionsQuery.data?.items ?? []}
        total={dailyDecisionsQuery.data?.total ?? 0}
        page={dailyPage}
        pageSize={dailyPageSize}
        isLoading={dailyDecisionsQuery.isFetching}
        onPageChange={setDailyPage}
        onSelectDate={setSelectedDate}
      />
      <PortfolioAttributionTable
        rows={tradeAttributionQuery.data?.items ?? []}
        summary={tradeAttributionQuery.data?.summary}
        total={tradeAttributionQuery.data?.total ?? 0}
        page={attributionPage}
        pageSize={attributionPageSize}
        isLoading={tradeAttributionQuery.isFetching}
        onPageChange={setAttributionPage}
        onSelectSymbol={setSelectedSymbol}
      />
      <PathDiagnosticsPanel diagnostics={pathDiagnosticsQuery.data} isLoading={pathDiagnosticsQuery.isFetching} onSelectSymbol={setSelectedSymbol} />
      <section className="rounded-lg border">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
          <div className="text-sm font-medium">按日期查看</div>
          <select
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={selectedDate}
            onChange={(event) => setSelectedDate(event.target.value)}
          >
            {dateOptions.map((item) => (
              <option key={item.trade_date} value={item.trade_date}>
                {item.trade_date} · 候选{item.buy_candidate_count ?? 0}/{item.watch_candidate_count ?? 0} · 计划{item.buy_signal_count ?? 0}/{item.sell_signal_count ?? 0} · 成交{item.buy_trade_count}/{item.sell_trade_count} · 拒{item.rejected_order_count}
              </option>
            ))}
          </select>
        </div>
        {dayQuery.isLoading ? (
          <div className="p-3 text-sm text-muted-foreground">加载中...</div>
        ) : !day ? (
          <div className="p-3 text-sm text-muted-foreground">暂无日期明细。</div>
        ) : (
          <div className="space-y-3 p-3">
            {selectedDateSummary && (
              <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
                <InfoCell label="买入成交" value={selectedDateSummary.buy_trade_count} />
                <InfoCell label="卖出成交" value={selectedDateSummary.sell_trade_count} />
                <InfoCell label="BUY候选" value={selectedDateSummary.buy_candidate_count ?? 0} />
                <InfoCell label="WATCH候选" value={selectedDateSummary.watch_candidate_count ?? 0} />
                <InfoCell label="买入计划" value={selectedDateSummary.buy_signal_count ?? 0} />
                <InfoCell label="卖出计划" value={selectedDateSummary.sell_signal_count ?? 0} />
                <InfoCell label="拒单" value={selectedDateSummary.rejected_order_count} />
                <InfoCell label="理论信号" value={selectedDateSummary.signal_event_count} />
              </div>
            )}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
              <InfoCell label="持仓数" value={day.equity?.position_count ?? 0} />
              <InfoCell label="回撤" value={formatPct(day.equity?.drawdown_pct)} />
              <InfoCell label="持仓快照" value={day.positions.length} />
            </div>
            <DailyDecisionSummaryPanel summary={day.decision_summary} />
            {!day.snapshot_available && <div className="text-xs text-muted-foreground">{day.note}</div>}
            <DayTradeTable title="当天买入" rows={day.buy_trades} />
            <DayTradeTable title="当天卖出" rows={day.sell_trades} />
            <OrderTable title="当天订单" rows={day.orders} />
            <PositionTable rows={day.positions} onSelectSymbol={setSelectedSymbol} />
          </div>
        )}
      </section>

      <section className="rounded-lg border">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
          <div className="text-sm font-medium">按股票查看</div>
          <select
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={selectedSymbol}
            onChange={(event) => setSelectedSymbol(event.target.value)}
          >
            {symbolOptions.map((item) => (
              <option key={item.vt_symbol} value={item.vt_symbol}>
                {item.name ? `${item.name} ${item.vt_symbol}` : item.vt_symbol} · {item.status_label}
              </option>
            ))}
          </select>
        </div>
        {symbolQuery.isLoading ? (
          <div className="p-3 text-sm text-muted-foreground">加载中...</div>
        ) : !symbol ? (
          <div className="p-3 text-sm text-muted-foreground">暂无股票明细。</div>
        ) : (
          <div className="space-y-3 p-3">
            <StockIdentityLink name={symbol.name} vtSymbol={symbol.vt_symbol} board={symbol.board} boardLabel={symbol.board_label} />
            {selectedSymbolSummary && (
              <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
                <InfoCell label="状态" value={selectedSymbolSummary.status_label} />
                <InfoCell label="理论买入" value={selectedSymbolSummary.buy_signal_count} />
                <InfoCell label="真实买入" value={selectedSymbolSummary.buy_trade_count} />
                <InfoCell label="拒单" value={selectedSymbolSummary.rejected_order_count} />
                <InfoCell label="首次信号" value={selectedSymbolSummary.first_signal_date ?? "--"} />
                <InfoCell label="主因" value={selectedSymbolSummary.main_reason_label ?? "--"} />
              </div>
            )}
            {!symbol.snapshot_available && <div className="text-xs text-muted-foreground">{symbol.note}</div>}
            <DayTradeTable title="该股成交" rows={symbol.trades} />
            <OrderTable title="该股订单" rows={symbol.orders} />
            <BacktestDecisionTimeline
              signals={symbolSignalsQuery.data?.items ?? []}
              orders={symbol.orders}
              trades={symbol.trades}
              positions={symbol.positions}
              isLoading={symbolSignalsQuery.isFetching}
            />
            <ClosedTradeTable rows={symbol.closed_trades} />
            <TradeAttributionTable rows={symbol.trade_attribution ?? []} />
            <PositionPathTable rows={symbol.positions} />
          </div>
        )}
      </section>
    </div>
  );
}

function DailyDecisionTable({
  rows,
  total,
  page,
  pageSize,
  isLoading,
  onPageChange,
  onSelectDate,
}: {
  rows: BacktestDailyDecisionRow[];
  total: number;
  page: number;
  pageSize: number;
  isLoading: boolean;
  onPageChange: (page: number) => void;
  onSelectDate: (tradeDate: string) => void;
}) {
  const offset = page * pageSize;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + rows.length, total);
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div>
          <div className="text-sm font-medium">每日候选到成交复盘</div>
          <div className="mt-0.5 text-xs text-muted-foreground">{total > 0 ? `${from}-${to} / ${total}` : "0 / 0"}</div>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => onPageChange(Math.max(page - 1, 0))} disabled={page === 0 || isLoading}>
            上一页
          </Button>
          <Button size="sm" variant="outline" onClick={() => onPageChange(page + 1)} disabled={isLoading || offset + pageSize >= total}>
            下一页
          </Button>
        </div>
      </div>
      {rows.length === 0 ? (
        <div className="p-3 text-sm text-muted-foreground">{isLoading ? "每日复盘加载中。" : "暂无每日复盘记录。"}</div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>执行日</TableHead>
              <TableHead>信号日</TableHead>
              <TableHead>状态</TableHead>
              <TableHead className="text-right">候选</TableHead>
              <TableHead className="text-right">计划</TableHead>
              <TableHead className="text-right">成交</TableHead>
              <TableHead className="text-right">拒单</TableHead>
              <TableHead>拒单原因</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.trade_date}>
                <TableCell>
                  <button type="button" className="text-sm text-primary hover:underline" onClick={() => onSelectDate(row.trade_date)}>
                    {row.trade_date}
                  </button>
                </TableCell>
                <TableCell className="text-muted-foreground">{row.source_signal_dates?.join("、") || "--"}</TableCell>
                <TableCell>{row.status_label}</TableCell>
                <TableCell className="text-right tabular-nums">{row.buy_candidate_count}/{row.watch_candidate_count}</TableCell>
                <TableCell className="text-right tabular-nums">{row.buy_signal_count}/{row.sell_signal_count}</TableCell>
                <TableCell className="text-right tabular-nums">{row.buy_trade_count}/{row.sell_trade_count}</TableCell>
                <TableCell className="text-right tabular-nums">{row.rejected_order_count}</TableCell>
                <TableCell className="text-muted-foreground">{rejectedReasonsLabel(row.rejected_reasons)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

function PortfolioAttributionTable({
  rows,
  summary,
  total,
  page,
  pageSize,
  isLoading,
  onPageChange,
  onSelectSymbol,
}: {
  rows: BacktestTradeAttribution[];
  summary?: BacktestTradeAttributionSummary;
  total: number;
  page: number;
  pageSize: number;
  isLoading: boolean;
  onPageChange: (page: number) => void;
  onSelectSymbol: (vtSymbol: string) => void;
}) {
  const offset = page * pageSize;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + rows.length, total);
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div>
          <div className="text-sm font-medium">组合亏损归因</div>
          <div className="mt-0.5 text-xs text-muted-foreground">{total > 0 ? `${from}-${to} / ${total}` : "0 / 0"}</div>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" onClick={() => onPageChange(Math.max(page - 1, 0))} disabled={page === 0 || isLoading}>
            上一页
          </Button>
          <Button size="sm" variant="outline" onClick={() => onPageChange(page + 1)} disabled={isLoading || offset + pageSize >= total}>
            下一页
          </Button>
        </div>
      </div>
      {summary && (
        <div className="grid grid-cols-2 gap-3 border-b p-3 md:grid-cols-6">
          <InfoCell label="交易合计" value={summary.total_count} />
          <InfoCell label="闭仓" value={summary.closed_count} />
          <InfoCell label="持仓中" value={summary.open_count} />
          <InfoCell label="胜率" value={formatPct(summary.win_rate)} />
        </div>
      )}
      {rows.length === 0 ? (
        <div className="p-3 text-sm text-muted-foreground">{isLoading ? "归因加载中。" : "暂无组合交易归因。"}</div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>股票</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>买入</TableHead>
              <TableHead>卖出</TableHead>
              <TableHead>入场依据</TableHead>
              <TableHead className="text-right">收益率</TableHead>
              <TableHead className="text-right">最大浮盈</TableHead>
              <TableHead className="text-right">最大浮亏</TableHead>
              <TableHead>执行</TableHead>
              <TableHead>卖出原因</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row, index) => (
              <TableRow key={`${row.vt_symbol}-${row.entry_date}-${row.exit_date ?? "open"}-${index}`}>
                <TableCell>
                  <div className="flex items-center justify-between gap-2">
                    <StockIdentityLink name={row.name} vtSymbol={row.vt_symbol} board={row.board} boardLabel={row.board_label} />
                    <button type="button" className="shrink-0 text-xs text-primary hover:underline" onClick={() => onSelectSymbol(row.vt_symbol)}>
                      查看
                    </button>
                  </div>
                </TableCell>
                <TableCell>{row.status === "closed" ? "已平仓" : "持仓中"}</TableCell>
                <TableCell className="tabular-nums">{row.entry_date ?? "--"}</TableCell>
                <TableCell className="tabular-nums">{row.exit_date ?? "--"}</TableCell>
                <TableCell className="text-xs leading-5 text-muted-foreground">{entryEvidenceLabel(row)}</TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>
                  {formatPct(row.return_pct)}
                </TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.max_floating_pnl_pct))}>
                  {formatPct(row.max_floating_pnl_pct)}
                </TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.min_floating_pnl_pct))}>
                  {formatPct(row.min_floating_pnl_pct)}
                </TableCell>
                <TableCell className="text-muted-foreground">{executionModeLabel(row.execution_mode ?? "")}</TableCell>
                <TableCell className="text-muted-foreground">{row.exit_reason_label ?? row.exit_reason ?? "--"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

function PathDiagnosticsPanel({
  diagnostics,
  isLoading,
  onSelectSymbol,
}: {
  diagnostics?: BacktestPathDiagnosticsResponse;
  isLoading: boolean;
  onSelectSymbol: (vtSymbol: string) => void;
}) {
  const rows = diagnostics?.items ?? [];
  const summary = diagnostics?.summary ?? {};
  const worstRows = [...rows]
    .filter((row) => row.return_pct != null)
    .sort((left, right) => (left.return_pct ?? 0) - (right.return_pct ?? 0))
    .slice(0, 6);

  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div>
          <div className="text-sm font-medium">买卖路径诊断</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {diagnostics ? `卖出后观察 ${diagnostics.lookahead_days} 天` : "MAE/MFE 和卖飞复盘"}
          </div>
        </div>
      </div>
      {!diagnostics && isLoading ? (
        <div className="p-3 text-sm text-muted-foreground">路径诊断加载中。</div>
      ) : rows.length === 0 ? (
        <div className="p-3 text-sm text-muted-foreground">暂无可诊断的闭仓路径。</div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 border-b p-3 md:grid-cols-5">
            <InfoCell label="交易数" value={metricValue(summary.trade_count)} />
            <InfoCell label="亏损数" value={metricValue(summary.loss_count)} />
            <InfoCell label="卖飞数" value={metricValue(summary.sold_before_rebound_count)} />
            <InfoCell label="平均MAE" value={formatPct(asNumber(summary.avg_mae_pct))} />
            <InfoCell label="平均MFE" value={formatPct(asNumber(summary.avg_mfe_pct))} />
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>股票</TableHead>
                <TableHead>买入</TableHead>
                <TableHead>卖出</TableHead>
                <TableHead>入场</TableHead>
                <TableHead className="text-right">收益</TableHead>
                <TableHead className="text-right">MAE</TableHead>
                <TableHead className="text-right">MFE</TableHead>
                <TableHead className="text-right">卖后高点</TableHead>
                <TableHead>卖出</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {worstRows.map((row) => (
                <TableRow key={`${row.vt_symbol}-${row.entry_date}-${row.exit_date}`}>
                  <TableCell>
                    <div className="flex items-center justify-between gap-2">
                      <StockIdentityLink name={row.name} vtSymbol={row.vt_symbol} board={row.board} boardLabel={row.board_label} />
                      <button type="button" className="shrink-0 text-xs text-primary hover:underline" onClick={() => onSelectSymbol(row.vt_symbol)}>
                        查看
                      </button>
                    </div>
                  </TableCell>
                  <TableCell className="tabular-nums">{row.entry_date ?? "--"}</TableCell>
                  <TableCell className="tabular-nums">{row.exit_date ?? "--"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{entrySetupLabel(row.entry_setup)}</TableCell>
                  <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>{formatPct(row.return_pct)}</TableCell>
                  <TableCell className={cn("text-right tabular-nums", priceColorClass(row.mae_pct))}>{formatPct(row.mae_pct)}</TableCell>
                  <TableCell className={cn("text-right tabular-nums", priceColorClass(row.mfe_pct))}>{formatPct(row.mfe_pct)}</TableCell>
                  <TableCell className={cn("text-right tabular-nums", priceColorClass(row.post_exit_max_return_pct))}>
                    {formatPct(row.post_exit_max_return_pct)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {row.sold_before_rebound ? "卖后反弹" : pathExitReasonLabel(row.exit_reason)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </div>
  );
}

function DailyDecisionSummaryPanel({ summary }: { summary?: BacktestDailyDecisionSummary }) {
  if (!summary) return null;
  const sourceDates = summary.source_signal_dates?.filter(Boolean).join("、") || "--";
  return (
    <div className="rounded-lg border p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-medium">候选到成交复盘</div>
        <div className="text-xs text-muted-foreground">信号日 {sourceDates}</div>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        <InfoCell label="状态" value={summary.status_label} />
        <InfoCell label="BUY候选" value={summary.buy_candidate_count} />
        <InfoCell label="WATCH候选" value={summary.watch_candidate_count} />
        <InfoCell label="买入计划" value={summary.buy_signal_count} />
        <InfoCell label="卖出计划" value={summary.sell_signal_count} />
        <InfoCell label="拒单" value={summary.rejected_order_count} />
        <InfoCell label="买入成交" value={summary.buy_trade_count} />
        <InfoCell label="卖出成交" value={summary.sell_trade_count} />
        <InfoCell
          label="拒单原因"
          value={rejectedReasonsLabel(summary.rejected_reasons)}
        />
      </div>
    </div>
  );
}

function DayTradeTable({ title, rows }: { title: string; rows: BacktestTrade[] }) {
  if (rows.length === 0) return <div className="text-sm text-muted-foreground">{title}：无</div>;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">{title}</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>日期</TableHead>
            <TableHead>股票</TableHead>
            <TableHead>方向</TableHead>
            <TableHead className="text-right">价格</TableHead>
            <TableHead className="text-right">数量</TableHead>
            <TableHead>执行</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${row.trade_date}-${row.vt_symbol}-${row.side}-${index}`}>
              <TableCell className="tabular-nums">{row.trade_date}</TableCell>
              <TableCell>
                <StockIdentityLink name={row.name} vtSymbol={row.vt_symbol} board={row.board} boardLabel={row.board_label} />
              </TableCell>
              <TableCell>{sideLabel(row.side)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(row.price)}</TableCell>
              <TableCell className="text-right tabular-nums">{row.volume.toLocaleString()}</TableCell>
              <TableCell className="text-muted-foreground">{executionModeLabel(executionMode(row.raw))}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function OrderTable({ title, rows }: { title: string; rows: BacktestOrderEvent[] }) {
  if (rows.length === 0) return <div className="text-sm text-muted-foreground">{title}：无</div>;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">{title}</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>日期</TableHead>
            <TableHead>股票</TableHead>
            <TableHead>方向</TableHead>
            <TableHead>状态</TableHead>
            <TableHead className="text-right">价格</TableHead>
            <TableHead className="text-right">数量</TableHead>
            <TableHead>执行</TableHead>
            <TableHead>原因</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${row.trade_date}-${row.vt_symbol}-${row.side}-${index}`}>
              <TableCell className="tabular-nums">{row.trade_date}</TableCell>
              <TableCell>
                <StockIdentityLink name={row.name} vtSymbol={row.vt_symbol} board={row.board} boardLabel={row.board_label} />
              </TableCell>
              <TableCell>{sideLabel(row.side)}</TableCell>
              <TableCell>{orderStatusLabel(row.status)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(row.price)}</TableCell>
              <TableCell className="text-right tabular-nums">{row.volume == null ? "--" : row.volume.toLocaleString()}</TableCell>
              <TableCell className="text-muted-foreground">{executionModeLabel(executionMode(row.raw))}</TableCell>
              <TableCell className="text-muted-foreground">{row.reason_label ?? row.reason ?? "--"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function ClosedTradeTable({ rows }: { rows: BacktestClosedTrade[] }) {
  if (rows.length === 0) return <div className="text-sm text-muted-foreground">暂无闭仓记录。</div>;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">闭仓记录</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>买入</TableHead>
            <TableHead>卖出</TableHead>
            <TableHead className="text-right">买入价</TableHead>
            <TableHead className="text-right">卖出价</TableHead>
            <TableHead className="text-right">数量</TableHead>
            <TableHead className="text-right">收益率</TableHead>
            <TableHead>原因</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${row.vt_symbol}-${row.entry_date}-${row.exit_date}-${index}`}>
              <TableCell className="tabular-nums">{row.entry_date ?? "--"}</TableCell>
              <TableCell className="tabular-nums">{row.exit_date ?? "--"}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(row.entry_price)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(row.exit_price)}</TableCell>
              <TableCell className="text-right tabular-nums">{row.volume.toLocaleString()}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>{formatPct(row.return_pct)}</TableCell>
              <TableCell className="text-muted-foreground">{row.exit_reason ?? "--"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function TradeAttributionTable({ rows }: { rows: BacktestTradeAttribution[] }) {
  if (rows.length === 0) return <div className="text-sm text-muted-foreground">暂无交易归因。</div>;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">交易归因</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>状态</TableHead>
            <TableHead>买入</TableHead>
            <TableHead>卖出</TableHead>
            <TableHead>入场依据</TableHead>
            <TableHead className="text-right">买入价</TableHead>
            <TableHead className="text-right">卖出价</TableHead>
            <TableHead className="text-right">收益率</TableHead>
            <TableHead className="text-right">最大浮盈</TableHead>
            <TableHead className="text-right">最大浮亏</TableHead>
            <TableHead>执行</TableHead>
            <TableHead>卖出原因</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${row.vt_symbol}-${row.entry_date}-${row.exit_date ?? "open"}-${index}`}>
              <TableCell>{row.status === "closed" ? "已平仓" : "持仓中"}</TableCell>
              <TableCell className="tabular-nums">{row.entry_date ?? "--"}</TableCell>
              <TableCell className="tabular-nums">{row.exit_date ?? "--"}</TableCell>
              <TableCell className="text-xs leading-5 text-muted-foreground">{entryEvidenceLabel(row)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(row.entry_price)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(row.exit_price)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>
                {formatPct(row.return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.max_floating_pnl_pct))}>
                {formatPct(row.max_floating_pnl_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.min_floating_pnl_pct))}>
                {formatPct(row.min_floating_pnl_pct)}
              </TableCell>
              <TableCell className="text-muted-foreground">{executionModeLabel(row.execution_mode ?? "")}</TableCell>
              <TableCell className="text-muted-foreground">{row.exit_reason_label ?? row.exit_reason ?? "--"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function entryEvidenceLabel(row: BacktestTradeAttribution): string {
  const parts = [
    row.entry_score == null ? "" : `总分 ${formatFixed(row.entry_score, 1)}`,
    row.entry_state ? entryStateLabel(row.entry_state) : "",
    row.entry_support_type ? supportTypeLabel(row.entry_support_type) : "",
    row.low_suction_days == null ? "" : `低吸 ${formatFixed(row.low_suction_days, 0)}天`,
    row.ma_convergence_pct == null ? "" : `收敛 ${formatFixed(row.ma_convergence_pct, 1)}%`,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "--";
}

function entrySetupLabel(setup?: string | null): string {
  const labels: Record<string, string> = {
    dragon_pullback: "龙回头",
    stealth_low_suction: "低吸洗盘",
    ma5_pullback: "MA5回踩",
  };
  return setup ? labels[setup] ?? setup : "--";
}

function pathExitReasonLabel(reason?: string | null): string {
  const labels: Record<string, string> = {
    support_stop: "支撑止损",
    profit_protection_stop: "利润保护",
    trend_trailing_stop: "趋势回撤",
    trend_break: "趋势破位",
    time_efficiency_stop: "时间效率",
    fragile_structure_stop: "脆弱结构",
    rotation_for_stronger_signal: "换仓",
    rotation_for_stealth_low_suction: "换入低吸",
  };
  return reason ? labels[reason] ?? reason : "--";
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function metricValue(value: unknown): string | number {
  return typeof value === "number" && Number.isFinite(value) ? value : "--";
}

function formatFixed(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return "--";
  return value.toFixed(digits);
}

function entryStateLabel(state: string): string {
  const labels: Record<string, string> = {
    TAIL_BUY_READY: "龙回头买点",
    LOW_SUCTION_BUILDUP: "低吸蓄势",
    SUPPORT_ACCEPTED: "均线承接",
    PULLBACK_OBSERVE: "回踩观察",
    DISTRIBUTION_RISK: "派发风险",
    INVALIDATED: "破位失效",
  };
  return labels[state] ?? state;
}

function supportTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    ma5_reclaim: "MA5承接",
    ma10_support: "MA10承接",
    ma20_support: "MA20承接",
    none: "无承接",
  };
  return labels[type] ?? type;
}

function executionMode(raw?: Record<string, unknown>): string | null {
  const execution = raw?.execution;
  if (execution && typeof execution === "object" && "mode" in execution) {
    return String((execution as { mode?: unknown }).mode ?? "");
  }
  const mode = raw?.mode;
  return mode == null ? null : String(mode);
}

function rejectedReasonsLabel(reasons: BacktestDailyDecisionSummary["rejected_reasons"]): string {
  if (!reasons.length) return "--";
  return reasons.map((item) => `${item.reason_label ?? item.reason} ${item.count}`).join("、");
}

function sideLabel(side: string): string {
  if (side === "BUY") return "买入";
  if (side === "SELL") return "卖出";
  return side || "--";
}

function orderStatusLabel(status: string): string {
  if (status === "filled") return "成交";
  if (status === "rejected") return "拒单";
  if (status === "pending") return "待执行";
  return status || "--";
}

function PositionTable({
  rows,
  onSelectSymbol,
}: {
  rows: Array<{
    vt_symbol: string;
    name?: string | null;
    board?: string;
    board_label?: string | null;
    volume: number;
    cost_price: number;
    close_price?: number | null;
    market_value: number;
    floating_pnl?: number | null;
    floating_pnl_pct?: number | null;
    weight_pct?: number | null;
    holding_days: number;
  }>;
  onSelectSymbol: (vtSymbol: string) => void;
}) {
  if (rows.length === 0) return <div className="text-sm text-muted-foreground">当日无持仓快照。</div>;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">当日持仓</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>股票</TableHead>
            <TableHead className="text-right">数量</TableHead>
            <TableHead className="text-right">成本</TableHead>
            <TableHead className="text-right">收盘</TableHead>
            <TableHead className="text-right">浮盈率</TableHead>
            <TableHead className="text-right">仓位</TableHead>
            <TableHead className="text-right">持仓天数</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.vt_symbol}>
              <TableCell className="min-w-40">
                <div className="flex items-center justify-between gap-2">
                  <StockIdentityLink name={row.name} vtSymbol={row.vt_symbol} board={row.board} boardLabel={row.board_label} />
                  <button type="button" className="shrink-0 text-xs text-primary hover:underline" onClick={() => onSelectSymbol(row.vt_symbol)}>
                    查看
                  </button>
                </div>
              </TableCell>
              <TableCell className="text-right tabular-nums">{row.volume.toLocaleString()}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(row.cost_price)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(row.close_price)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.floating_pnl_pct))}>
                {formatPct(row.floating_pnl_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatPct(row.weight_pct)}</TableCell>
              <TableCell className="text-right tabular-nums">{row.holding_days}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function PositionPathTable({ rows }: { rows: Array<{ trade_date: string; volume: number; close_price?: number | null; market_value: number; floating_pnl?: number | null; floating_pnl_pct?: number | null; weight_pct?: number | null; holding_days: number }> }) {
  if (rows.length === 0) return <div className="text-sm text-muted-foreground">暂无持仓路径。</div>;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">持仓路径</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>日期</TableHead>
            <TableHead className="text-right">数量</TableHead>
            <TableHead className="text-right">收盘</TableHead>
            <TableHead className="text-right">浮盈率</TableHead>
            <TableHead className="text-right">持仓天数</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.slice(-20).map((row) => (
            <TableRow key={row.trade_date}>
              <TableCell className="tabular-nums">{row.trade_date}</TableCell>
              <TableCell className="text-right tabular-nums">{row.volume.toLocaleString()}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(row.close_price)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.floating_pnl_pct))}>
                {formatPct(row.floating_pnl_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums">{row.holding_days}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
