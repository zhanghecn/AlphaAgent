import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchBacktestDayDetail, fetchBacktestReport, fetchBacktestSymbolDetail } from "@/api/quant";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { InfoCell } from "@/components/InfoCell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn, formatAmount, formatPct, formatPrice, priceColorClass } from "@/lib/utils";

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

  const dateOptions = useMemo(() => {
    const values = new Set<string>();
    for (const row of report.equity_tail ?? []) values.add(row.trade_date);
    for (const row of report.recent_trades ?? report.trades) values.add(row.trade_date);
    return [...values].sort().reverse();
  }, [report.equity_tail, report.recent_trades, report.trades]);

  const symbolOptions = useMemo(() => {
    const bySymbol = new Map<string, { vt_symbol: string; name?: string | null; board?: string; board_label?: string | null }>();
    for (const row of [...(report.recent_trades ?? report.trades), ...(report.symbol_performance ?? [])]) {
      if (!row.vt_symbol || bySymbol.has(row.vt_symbol)) continue;
      bySymbol.set(row.vt_symbol, {
        vt_symbol: row.vt_symbol,
        name: row.name,
        board: row.board,
        board_label: row.board_label,
      });
    }
    return [...bySymbol.values()];
  }, [report.recent_trades, report.symbol_performance, report.trades]);

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

  const day = dayQuery.data;
  const symbol = symbolQuery.data;

  return (
    <div className="space-y-4">
      <section className="rounded-lg border">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
          <div className="text-sm font-medium">按日期查看</div>
          <select
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={selectedDate}
            onChange={(event) => setSelectedDate(event.target.value)}
          >
            {dateOptions.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </div>
        {dayQuery.isLoading ? (
          <div className="p-3 text-sm text-muted-foreground">加载中...</div>
        ) : !day ? (
          <div className="p-3 text-sm text-muted-foreground">暂无日期明细。</div>
        ) : (
          <div className="space-y-3 p-3">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
              <InfoCell label="现金" value={formatAmount(day.equity?.cash)} />
              <InfoCell label="持仓市值" value={formatAmount(day.equity?.market_value)} />
              <InfoCell label="总权益" value={formatAmount(day.equity?.total_equity)} />
              <InfoCell label="持仓数" value={day.equity?.position_count ?? 0} />
              <InfoCell label="回撤" value={formatPct(day.equity?.drawdown_pct)} />
            </div>
            {!day.snapshot_available && <div className="text-xs text-muted-foreground">{day.note}</div>}
            <DayTradeTable title="当天买入" rows={day.buy_trades} />
            <DayTradeTable title="当天卖出" rows={day.sell_trades} />
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
                {item.name ? `${item.name} ${item.vt_symbol}` : item.vt_symbol}
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
            {!symbol.snapshot_available && <div className="text-xs text-muted-foreground">{symbol.note}</div>}
            <DayTradeTable title="该股成交" rows={symbol.trades} />
            <PositionPathTable rows={symbol.positions} />
          </div>
        )}
      </section>
    </div>
  );
}

function DayTradeTable({ title, rows }: { title: string; rows: BacktestReportData["trades"] }) {
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
            <TableHead className="text-right">金额</TableHead>
            <TableHead className="text-right">盈亏</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${row.trade_date}-${row.vt_symbol}-${row.side}-${index}`}>
              <TableCell className="tabular-nums">{row.trade_date}</TableCell>
              <TableCell>
                <StockIdentityLink name={row.name} vtSymbol={row.vt_symbol} board={row.board} boardLabel={row.board_label} />
              </TableCell>
              <TableCell>{row.side === "BUY" ? "买入" : "卖出"}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(row.price)}</TableCell>
              <TableCell className="text-right tabular-nums">{row.volume.toLocaleString()}</TableCell>
              <TableCell className="text-right tabular-nums">{formatAmount(row.amount)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.pnl))}>
                {formatAmount(row.pnl)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
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
            <TableHead className="text-right">市值</TableHead>
            <TableHead className="text-right">浮盈</TableHead>
            <TableHead className="text-right">仓位</TableHead>
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
              <TableCell className="text-right tabular-nums">{formatAmount(row.market_value)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.floating_pnl))}>
                {formatAmount(row.floating_pnl)} / {formatPct(row.floating_pnl_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatPct(row.weight_pct)}</TableCell>
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
            <TableHead className="text-right">市值</TableHead>
            <TableHead className="text-right">浮盈</TableHead>
            <TableHead className="text-right">持仓天数</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.slice(-20).map((row) => (
            <TableRow key={row.trade_date}>
              <TableCell className="tabular-nums">{row.trade_date}</TableCell>
              <TableCell className="text-right tabular-nums">{row.volume.toLocaleString()}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(row.close_price)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatAmount(row.market_value)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.floating_pnl))}>
                {formatAmount(row.floating_pnl)} / {formatPct(row.floating_pnl_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums">{row.holding_days}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
