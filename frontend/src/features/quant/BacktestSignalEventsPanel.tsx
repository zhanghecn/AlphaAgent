import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { fetchBacktestEquity, fetchBacktestSignalAmountPreview, fetchBacktestSignalEvents } from "@/api/quant";
import { EmptyState } from "@/components/EmptyState";
import { InfoCell } from "@/components/InfoCell";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { TradingDateSelector } from "@/features/quant/TradingDateSelector";
import { cn, formatAmount, formatPrice, priceColorClass } from "@/lib/utils";

export function BacktestSignalEventsPanel({
  backtestId,
  defaultCapital,
  defaultMaxPositions,
  defaultStart,
  defaultEnd,
}: {
  backtestId: number;
  defaultCapital: number;
  defaultMaxPositions: number;
  defaultStart?: string;
  defaultEnd?: string;
}) {
  const [capital, setCapital] = useState(defaultCapital);
  const [maxPositions, setMaxPositions] = useState(defaultMaxPositions);
  const [symbol, setSymbol] = useState("");
  const [side, setSide] = useState("");
  const [start, setStart] = useState(defaultStart ?? "");
  const [end, setEnd] = useState(defaultEnd ?? "");
  const normalizedSymbol = symbol.trim().toUpperCase();

  useEffect(() => {
    setCapital(defaultCapital);
    setMaxPositions(defaultMaxPositions);
    setStart(defaultStart ?? "");
    setEnd(defaultEnd ?? "");
  }, [backtestId, defaultCapital, defaultMaxPositions, defaultStart, defaultEnd]);

  const equityQuery = useQuery({
    queryKey: ["backtestEquity", backtestId],
    queryFn: () => fetchBacktestEquity(backtestId),
    enabled: Boolean(backtestId),
    staleTime: 60_000,
  });

  const eventsQuery = useQuery({
    queryKey: ["backtestSignalEvents", backtestId, normalizedSymbol, side, start, end],
    queryFn: () => fetchBacktestSignalEvents(backtestId, { vt_symbol: normalizedSymbol, side, start, end, limit: 500 }),
    enabled: Boolean(backtestId),
    staleTime: 30_000,
  });

  const previewQuery = useQuery({
    queryKey: ["backtestSignalAmountPreview", backtestId, capital, maxPositions, normalizedSymbol, side, start, end],
    queryFn: () =>
      fetchBacktestSignalAmountPreview(backtestId, {
        capital,
        max_positions: maxPositions,
        vt_symbol: normalizedSymbol,
        side,
        start,
        end,
        limit: 500,
      }),
    enabled: Boolean(backtestId && capital > 0 && maxPositions > 0),
    staleTime: 20_000,
  });

  const rows = useMemo(() => previewQuery.data?.items ?? [], [previewQuery.data?.items]);
  const tradingDates = useMemo(() => {
    const equityDates = equityQuery.data?.items.map((item) => item.trade_date) ?? [];
    return Array.from(new Set([...equityDates, defaultStart, defaultEnd, start, end].filter(Boolean) as string[]));
  }, [defaultEnd, defaultStart, end, equityQuery.data?.items, start]);

  return (
    <section className="space-y-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">全股票信号流水</h3>
          <div className="mt-1 text-xs text-muted-foreground">
            覆盖回测区间内逐日重新选股后的理论买卖点；金额按总资金等权预览，不替代真实组合资金曲线。
          </div>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            eventsQuery.refetch();
            previewQuery.refetch();
          }}
        >
          <Search size={14} />
          查询
        </Button>
      </div>

      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-8">
        <label className="text-xs text-muted-foreground">
          总资金
          <input
            className="mt-1 h-8 w-full rounded-md border bg-background px-2 text-sm"
            type="number"
            min={1}
            value={capital}
            onChange={(event) => setCapital(Number(event.target.value) || 0)}
          />
        </label>
        <label className="text-xs text-muted-foreground">
          最大持仓
          <input
            className="mt-1 h-8 w-full rounded-md border bg-background px-2 text-sm"
            type="number"
            min={1}
            value={maxPositions}
            onChange={(event) => setMaxPositions(Number(event.target.value) || 1)}
          />
        </label>
        <TradingDateSelector
          label="开始日期"
          value={start}
          dates={tradingDates}
          onChange={setStart}
          className="items-start gap-1 text-xs text-muted-foreground xl:col-span-2"
          selectClassName="mt-1 w-full min-w-0"
        />
        <TradingDateSelector
          label="结束日期"
          value={end}
          dates={tradingDates}
          onChange={setEnd}
          className="items-start gap-1 text-xs text-muted-foreground xl:col-span-2"
          selectClassName="mt-1 w-full min-w-0"
        />
        <label className="text-xs text-muted-foreground">
          股票
          <input
            className="mt-1 h-8 w-full rounded-md border bg-background px-2 text-sm"
            value={symbol}
            onChange={(event) => setSymbol(event.target.value)}
            placeholder="600000.SSE"
          />
        </label>
        <label className="text-xs text-muted-foreground">
          方向
          <select
            className="mt-1 h-8 w-full rounded-md border bg-background px-2 text-sm"
            value={side}
            onChange={(event) => setSide(event.target.value)}
          >
            <option value="">全部</option>
            <option value="BUY">买入</option>
            <option value="SELL">卖出</option>
          </select>
        </label>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <InfoCell label="理论信号" value={`${previewQuery.data?.source_count ?? eventsQuery.data?.returned_count ?? rows.length} / 显示 ${rows.length}`} />
        <InfoCell label="每笔预算" value={formatAmount(previewQuery.data?.per_trade_budget)} />
        <InfoCell label="总资金" value={formatAmount(previewQuery.data?.capital ?? capital)} />
        <InfoCell label="最大持仓" value={previewQuery.data?.max_positions ?? maxPositions} />
      </div>

      {eventsQuery.data?.note && <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700">{eventsQuery.data.note}</div>}

      {rows.length === 0 ? (
        <EmptyState message="暂无信号流水" description="旧回测需要重跑组合回测后才会生成全股票理论买卖点。" />
      ) : (
        <div className="overflow-hidden rounded-lg border">
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
                  <TableCell>{row.side === "BUY" ? "买入" : "卖出"}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatPrice(row.price)}</TableCell>
                  <TableCell className="text-right tabular-nums">{row.preview_volume.toLocaleString()}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatAmount(row.preview_amount)}</TableCell>
                  <TableCell className={cn("text-right tabular-nums", priceColorClass(row.preview_pnl))}>
                    {formatAmount(row.preview_pnl)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{row.reason ?? "--"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  );
}
