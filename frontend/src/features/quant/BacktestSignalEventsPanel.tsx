import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { fetchBacktestEquity, fetchBacktestSignalEvents } from "@/api/quant";
import { EmptyState } from "@/components/EmptyState";
import { InfoCell } from "@/components/InfoCell";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { TradingDateSelector } from "@/features/quant/TradingDateSelector";
import { formatPrice } from "@/lib/utils";

export function BacktestSignalEventsPanel({
  backtestId,
  defaultStart,
  defaultEnd,
}: {
  backtestId: number;
  defaultStart?: string;
  defaultEnd?: string;
}) {
  const [symbol, setSymbol] = useState("");
  const [side, setSide] = useState("");
  const [start, setStart] = useState(defaultStart ?? "");
  const [end, setEnd] = useState(defaultEnd ?? "");
  const normalizedSymbol = symbol.trim().toUpperCase();

  useEffect(() => {
    setStart(defaultStart ?? "");
    setEnd(defaultEnd ?? "");
  }, [backtestId, defaultStart, defaultEnd]);

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

  const rows = useMemo(() => eventsQuery.data?.items ?? [], [eventsQuery.data?.items]);
  const stats = useMemo(() => signalPlanStats(rows), [rows]);
  const tradingDates = useMemo(() => {
    const equityDates = equityQuery.data?.items.map((item) => item.trade_date) ?? [];
    return Array.from(new Set([...equityDates, defaultStart, defaultEnd, start, end].filter(Boolean) as string[]));
  }, [defaultEnd, defaultStart, end, equityQuery.data?.items, start]);

  return (
    <section className="space-y-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">全股票信号计划</h3>
          <div className="mt-1 text-xs text-muted-foreground">
            覆盖回测区间内逐日重新选股后的理论买卖信号；真实成交看订单状态和原因。
          </div>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => eventsQuery.refetch()}
        >
          <Search size={14} />
          查询
        </Button>
      </div>

      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-6">
        <TradingDateSelector
          label="开始日期"
          value={start}
          dates={tradingDates}
          onChange={setStart}
          className="items-start gap-1 text-xs text-muted-foreground"
          selectClassName="mt-1 w-full min-w-0"
        />
        <TradingDateSelector
          label="结束日期"
          value={end}
          dates={tradingDates}
          onChange={setEnd}
          className="items-start gap-1 text-xs text-muted-foreground"
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
        <InfoCell label="信号计划" value={`${eventsQuery.data?.returned_count ?? rows.length} / 显示 ${rows.length}`} />
        <InfoCell label="买入信号" value={`${stats.buyCount} 条`} />
        <InfoCell label="卖出信号" value={`${stats.sellCount} 条`} />
        <InfoCell label="已成交/拒绝" value={`${stats.filledCount} / ${stats.rejectedCount}`} />
      </div>

      {eventsQuery.data?.note && <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">{eventsQuery.data.note}</div>}

      {rows.length === 0 ? (
        <EmptyState message="暂无信号计划" description="旧回测需要重跑组合回测后才会生成全股票理论信号。" />
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>日期</TableHead>
                <TableHead>股票</TableHead>
                <TableHead>方向</TableHead>
                <TableHead className="text-right">价格</TableHead>
                <TableHead className="text-right">评分</TableHead>
                <TableHead>订单</TableHead>
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
                  <TableCell className="text-right tabular-nums">{formatScore(row.score)}</TableCell>
                  <TableCell className="text-muted-foreground">{row.plan_status_label ?? orderLinkLabel(row.linked_order_status)}</TableCell>
                  <TableCell className="text-muted-foreground">{signalReasonText(row)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  );
}

function signalPlanStats(rows: Array<{ side?: string | null; linked_order_status?: string | null }>) {
  let buyCount = 0;
  let sellCount = 0;
  let filledCount = 0;
  let rejectedCount = 0;
  for (const row of rows) {
    const side = String(row.side ?? "").toUpperCase();
    if (side === "BUY") buyCount += 1;
    if (side === "SELL") sellCount += 1;
    if (row.linked_order_status === "filled") filledCount += 1;
    if (row.linked_order_status === "rejected") rejectedCount += 1;
  }
  return { buyCount, sellCount, filledCount, rejectedCount };
}

function formatScore(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(1) : "--";
}

function orderLinkLabel(status?: string | null) {
  if (status === "filled") return "已成交";
  if (status === "rejected") return "已拒单";
  if (status === "pending") return "待执行";
  return "未下单";
}

function signalReasonText(row: {
  reason?: string | null;
  reason_label?: string | null;
  linked_order_reason?: string | null;
  linked_order_reason_label?: string | null;
  raw?: Record<string, unknown>;
}) {
  const rawReason = typeof row.raw?.reason === "string" ? row.raw.reason : "";
  return row.linked_order_reason_label ?? row.reason_label ?? row.linked_order_reason ?? rawReason ?? row.reason ?? "--";
}
