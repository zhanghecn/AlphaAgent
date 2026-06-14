import type { BacktestOrderEvent, BacktestSignalEvent, BacktestTrade } from "@/api/quant";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { executionModeLabel } from "@/lib/backtest-utils";
import { formatAmount, formatPct, formatPrice } from "@/lib/utils";

export function BacktestDecisionTimeline({
  signals,
  orders,
  trades,
  positions,
  isLoading,
}: {
  signals: BacktestSignalEvent[];
  orders: BacktestOrderEvent[];
  trades: BacktestTrade[];
  positions: Array<{
    trade_date: string;
    volume: number;
    close_price?: number | null;
    market_value: number;
    floating_pnl?: number | null;
    floating_pnl_pct?: number | null;
    weight_pct?: number | null;
    holding_days: number;
  }>;
  isLoading: boolean;
}) {
  const rows = buildTimelineRows(signals, orders, trades, positions);
  if (isLoading && rows.length === 0) return <div className="text-sm text-muted-foreground">正在加载决策时间线...</div>;
  if (rows.length === 0) return <div className="text-sm text-muted-foreground">暂无该股决策时间线。</div>;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">决策时间线</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>日期</TableHead>
            <TableHead>事件</TableHead>
            <TableHead>方向</TableHead>
            <TableHead>状态</TableHead>
            <TableHead className="text-right">价格</TableHead>
            <TableHead className="text-right">数量/市值</TableHead>
            <TableHead>说明</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.slice(-80).map((row, index) => (
            <TableRow key={`${row.date}-${row.kind}-${index}`}>
              <TableCell className="tabular-nums">{row.date}</TableCell>
              <TableCell>{row.kind}</TableCell>
              <TableCell>{row.side}</TableCell>
              <TableCell>{row.status}</TableCell>
              <TableCell className="text-right tabular-nums">{row.price}</TableCell>
              <TableCell className="text-right tabular-nums">{row.size}</TableCell>
              <TableCell className="text-muted-foreground">{row.note}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function buildTimelineRows(
  signals: BacktestSignalEvent[],
  orders: BacktestOrderEvent[],
  trades: BacktestTrade[],
  positions: Array<{
    trade_date: string;
    volume: number;
    close_price?: number | null;
    market_value: number;
    floating_pnl?: number | null;
    floating_pnl_pct?: number | null;
    holding_days: number;
  }>
) {
  const rows: Array<{ date: string; sort: number; kind: string; side: string; status: string; price: string; size: string; note: string }> = [];
  for (const signal of signals) {
    rows.push({
      date: signal.signal_date || signal.trade_date,
      sort: 1,
      kind: "理论信号",
      side: sideLabel(signal.side),
      status: signal.plan_status_label ?? orderStatusLabel(signal.linked_order_status ?? ""),
      price: formatPrice(signal.price),
      size: "--",
      note: signal.linked_order_reason_label ?? signal.reason_label ?? signal.reason ?? "--",
    });
  }
  for (const order of orders) {
    rows.push({
      date: order.trade_date,
      sort: 2,
      kind: "真实订单",
      side: sideLabel(order.side),
      status: orderStatusLabel(order.status),
      price: formatPrice(order.price),
      size: order.volume == null ? "--" : order.volume.toLocaleString(),
      note: order.reason_label ?? order.reason ?? executionModeLabel(executionMode(order.raw)),
    });
  }
  for (const trade of trades) {
    rows.push({
      date: trade.trade_date,
      sort: 3,
      kind: "成交",
      side: sideLabel(trade.side),
      status: "已成交",
      price: formatPrice(trade.price),
      size: `${trade.volume.toLocaleString()} / ${formatAmount(trade.amount)}`,
      note: trade.reason ?? executionModeLabel(executionMode(trade.raw)),
    });
  }
  for (const position of positions) {
    rows.push({
      date: position.trade_date,
      sort: 4,
      kind: "持仓",
      side: "--",
      status: `第${position.holding_days}天`,
      price: formatPrice(position.close_price),
      size: `${position.volume.toLocaleString()} / ${formatAmount(position.market_value)}`,
      note: `浮盈 ${formatAmount(position.floating_pnl)} / ${formatPct(position.floating_pnl_pct)}`,
    });
  }
  return rows.sort((left, right) => left.date.localeCompare(right.date) || left.sort - right.sort);
}

function executionMode(raw?: Record<string, unknown>): string | null {
  const execution = raw?.execution;
  if (execution && typeof execution === "object" && "mode" in execution) {
    return String((execution as { mode?: unknown }).mode ?? "");
  }
  const mode = raw?.mode;
  return mode == null ? null : String(mode);
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
