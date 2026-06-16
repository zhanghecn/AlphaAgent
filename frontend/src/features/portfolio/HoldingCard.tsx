import { useState } from "react";
import { ArrowDownToLine, ArrowUpFromLine, Pencil } from "lucide-react";
import { EditCostDialog } from "./EditCostDialog";
import { cn, formatPct, formatPrice, priceColorClass } from "@/lib/utils";
import { formatTime, sourceLabel } from "@/lib/backtest-utils";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { HoldingMiniChart, type SignalMarker } from "./HoldingMiniChart";
import type { SimulationPosition } from "@/api/quant";
import type { RiskBadge } from "@/lib/portfolio-risk";

/**
 * Daily bar for the mini K-line chart inside a holding card.
 */
export interface DailyBar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

/**
 * A stock item in a portfolio group, with optional simulated position data.
 */
export interface HoldingCardItem {
  vt_symbol: string;
  group_id?: number;
  name?: string | null;
  board?: string | null;
  board_label?: string | null;
  source: string;
  reason?: string | null;
  strategy_id?: string | null;
  strategy_version?: string | null;
  updated_at?: string | null;
  created_at?: string | null;
}

export interface StrategyAdvice {
  label: string;
  detail?: string | null;
  tone?: "neutral" | "hold" | "sell" | "warning";
}

export interface HoldingCardProps {
  /** Group item (always present) */
  item: HoldingCardItem;
  /** Simulated position data (present if the stock is held in simulation) */
  position?: SimulationPosition | null;
  /** Recent daily bars for the mini chart */
  dailyBars?: DailyBar[];
  /** Risk badges derived from the position (near stop-loss / deep loss / overdue) */
  riskBadges?: RiskBadge[];
  /** Strategy advice derived from the unified quant execution review. */
  strategyAdvice?: StrategyAdvice | null;
  /** Callback to open the add-to-group dialog */
  onAddToGroup?: (vtSymbol: string) => void;
  /** Callback to navigate to stock detail page */
  onViewDetail?: (vtSymbol: string) => void;
  /** Callback to open the sell dialog (held only) */
  onSell?: (vtSymbol: string) => void;
  /** Callback to open the add-position dialog (held only) */
  onAddPosition?: (vtSymbol: string) => void;
  /** Whether batch selection mode is active */
  isSelecting?: boolean;
  /** Whether this card is selected in batch mode */
  isSelected?: boolean;
  /** Toggle selection for this card */
  onToggleSelect?: (vtSymbol: string) => void;
  /** Simulation account id（用于改成本价） */
  accountId?: number;
  /** Currently selected group in the sidebar; cards belonging to it are highlighted. */
  selectedGroupId?: number;
}

/**
 * HoldingCard renders a single stock card in the portfolio view.
 *
 * Two display modes:
 * - **Held**: Has a matching SimulationPosition → full card with mini chart, metrics, buy/sell info
 * - **Watching**: No position → compact card with basic info and actions
 */
export function HoldingCard({
  item,
  position,
  dailyBars,
  strategyAdvice,
  onAddToGroup,
  onViewDetail,
  onSell,
  onAddPosition,
  isSelecting,
  isSelected,
  onToggleSelect,
  accountId,
  selectedGroupId,
}: HoldingCardProps) {
  const [editCostOpen, setEditCostOpen] = useState(false);
  const isHeld = Boolean(position);

  // Build buy/sell signal markers from position data
  const buySignals: SignalMarker[] = [];
  const sellSignals: SignalMarker[] = [];

  if (position?.last_buy_time && position.last_buy_price) {
    // Convert ISO timestamp to YYYY-MM-DD for chart marker
    const buyDate = position.last_buy_time.slice(0, 10);
    buySignals.push({
      time: buyDate,
      price: position.last_buy_price,
      type: "buy",
      reason: position.last_buy_reason || position.reason || "买入",
    });
  }
  if (position?.last_sell_time && position.last_sell_price) {
    const sellDate = position.last_sell_time.slice(0, 10);
    sellSignals.push({
      time: sellDate,
      price: position.last_sell_price,
      type: "sell",
      reason: "卖出",
    });
  }

  return (
    <Card
      className={cn(
        "p-4 text-sm",
        !isHeld && "bg-card/60",
        isSelecting && isSelected && "ring-2 ring-primary",
        item.group_id != null && item.group_id === selectedGroupId && "ring-2 ring-brand",
      )}
      onClick={isSelecting && onToggleSelect ? () => onToggleSelect(item.vt_symbol) : undefined}
      style={isSelecting ? { cursor: "pointer" } : undefined}
    >
      {/* Realtime exit advice (held only) — live stop-loss/take-profit/trailing/time
          evaluation from the strategy exit rules, shared with the backtest engine. */}
      {isHeld && position?.advice && (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Badge
            variant="outline"
            className={cn("px-2 py-0.5", strategyAdviceClass(ADVICE_TONE[position.advice]))}
            title="实时止损止盈规则评估（按成本价/现价动态计算）"
          >
            {ADVICE_LABEL[position.advice] ?? position.advice}
          </Badge>
        </div>
      )}

      {/* Strategy advice (held only) — historical hold/sell from the quant execution review,
          complements the realtime exit advice above. */}
      {isHeld && strategyAdvice && (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Badge
            variant={strategyAdvice.tone === "sell" || strategyAdvice.tone === "warning" ? "secondary" : "outline"}
            className={cn("px-2 py-0.5", strategyAdviceClass(strategyAdvice.tone))}
            title={strategyAdvice.detail ?? undefined}
          >
            {strategyAdvice.label}
          </Badge>
          {strategyAdvice.detail && (
            <span className="text-xs text-muted-foreground">{strategyAdvice.detail}</span>
          )}
        </div>
      )}

      {/* Header: checkbox + stock identity + P&L */}
      <div className="flex items-start justify-between gap-3">
        {isSelecting && (
          <input
            type="checkbox"
            checked={Boolean(isSelected)}
            onChange={() => onToggleSelect?.(item.vt_symbol)}
            className="mt-1 shrink-0"
            onClick={(e) => e.stopPropagation()}
          />
        )}
        <div className="min-w-0">
          <StockIdentityLink
            name={item.name}
            vtSymbol={item.vt_symbol}
            board={item.board}
            boardLabel={item.board_label}
          />
          <div className="mt-0.5 text-xs text-muted-foreground">
            {sourceLabel(item.source)}
            {item.reason && <span className="ml-2">· {item.reason}</span>}
          </div>
        </div>
        {isHeld && position && (
          <div
            className={cn(
              "text-right text-sm font-semibold tabular-nums shrink-0",
              priceColorClass(position.floating_pnl_pct)
            )}
          >
            {formatPct(position.floating_pnl_pct)}
          </div>
        )}
        {!isHeld && dailyBars && dailyBars.length > 0 && (
          <div
            className={cn(
              "text-right text-sm font-semibold tabular-nums shrink-0",
              priceColorClass(dailyChangePct(dailyBars))
            )}
          >
            {formatPct(dailyChangePct(dailyBars))}
          </div>
        )}
      </div>

      {/* Mini K-line chart */}
      {dailyBars && dailyBars.length > 0 && (
        <div className="mt-3">
          <HoldingMiniChart
            bars={dailyBars}
            costPrice={position?.cost_price}
            stopLossPrice={position?.stop_loss_price ?? undefined}
            takeProfitPrice={position?.take_profit_price ?? undefined}
            buySignals={buySignals}
            sellSignals={sellSignals}
            height={isHeld ? 120 : 80}
            onClick={onViewDetail ? () => onViewDetail(item.vt_symbol) : undefined}
          />
        </div>
      )}

      {/* Metrics row */}
      {isHeld && position && (
        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <MetricRow label="现价" value={formatPrice(position.last_price)} />
          <MetricRow label="成本" value={formatPrice(position.cost_price)} />
          {accountId != null && (
            <div className="col-span-2 -mt-1">
              <button
                type="button"
                className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary"
                onClick={() => setEditCostOpen(true)}
              >
                <Pencil size={11} /> 修改成本价
              </button>
            </div>
          )}
          <MetricRow
            label="收益率"
            value={formatPct(position.floating_pnl_pct)}
            valueClass={priceColorClass(position.floating_pnl_pct)}
          />
          <MetricRow label="持仓" value={`${position.volume.toLocaleString()} 股`} />
        </div>
      )}

      {!isHeld && dailyBars && dailyBars.length > 0 && (
        <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <MetricRow label="最新" value={formatPrice(dailyBars[dailyBars.length - 1]?.close)} />
          <MetricRow label="涨跌" value={formatPct(dailyChangePct(dailyBars))} valueClass={priceColorClass(dailyChangePct(dailyBars))} />
        </div>
      )}

      {/* Buy/sell info */}
      {isHeld && position && (
        <div className="mt-2 space-y-1 text-xs text-muted-foreground">
          {(position.last_buy_time || position.last_buy_price) && (
            <div>
              买入 {formatTime(position.last_buy_time)} · {formatPrice(position.last_buy_price)}
              {position.last_buy_volume && ` · ${position.last_buy_volume} 股`}
            </div>
          )}
          {position.last_sell_time && (
            <div>
              最近卖出 {formatTime(position.last_sell_time)} · {formatPrice(position.last_sell_price)}
            </div>
          )}
          {(position.stop_loss_price || position.take_profit_price) && (
            <div className="flex flex-wrap items-center gap-1">
              <span>
                止损 {formatPrice(position.stop_loss_price)} / 止盈 {formatPrice(position.take_profit_price)}
                {position.trailing_stop_price && ` · 跟踪 ${formatPrice(position.trailing_stop_price)}`}
              </span>
              <span
                className="rounded border px-1 text-[10px] leading-4 text-muted-foreground"
                title="止损止盈当前为策略默认值，后续版本支持手动调整"
              >
                只读
              </span>
            </div>
          )}
        </div>
      )}

      {/* Action buttons */}
      <div className="mt-3 flex flex-wrap gap-2 border-t pt-3">
        {isHeld && onSell && (
          <Button size="sm" variant="outline" onClick={() => onSell(item.vt_symbol)}>
            <ArrowDownToLine className="mr-1" size={14} />
            卖出
          </Button>
        )}
        {isHeld && onAddPosition && (
          <Button size="sm" variant="outline" onClick={() => onAddPosition(item.vt_symbol)}>
            <ArrowUpFromLine className="mr-1" size={14} />
            加仓
          </Button>
        )}
        {onAddToGroup && (
          <Button size="sm" variant="ghost" onClick={() => onAddToGroup(item.vt_symbol)}>
            加入分组
          </Button>
        )}
        {onViewDetail && (
          <Button size="sm" variant="ghost" onClick={() => onViewDetail(item.vt_symbol)}>
            查看详情
          </Button>
        )}
      </div>

      {accountId != null && (
        <EditCostDialog
          open={editCostOpen}
          onOpenChange={setEditCostOpen}
          accountId={accountId}
          vtSymbol={item.vt_symbol}
          defaultCost={position?.cost_price}
        />
      )}
    </Card>
  );
}

/** Small label-value pair used inside the card metrics grid. */
function MetricRow({
  label,
  value,
  valueClass,
}: {
  label: string;
  value?: string | null;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("tabular-nums", valueClass)}>{value ?? "--"}</span>
    </div>
  );
}

/** Calculate daily change percentage from the last two bars. */
function dailyChangePct(bars: DailyBar[]): number | null {
  if (!bars || bars.length < 2) return null;
  const prev = bars[bars.length - 2]?.close;
  const curr = bars[bars.length - 1]?.close;
  if (!prev || !curr) return null;
  return ((curr - prev) / prev) * 100;
}

function strategyAdviceClass(tone?: StrategyAdvice["tone"]): string {
  if (tone === "hold") return "border-green-200 bg-green-50 text-green-700 dark:border-green-500/30 dark:bg-green-500/10 dark:text-green-300";
  if (tone === "sell") return "border-red-200 bg-red-50 text-fall dark:border-red-500/30 dark:bg-red-500/10";
  if (tone === "warning") return "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300";
  return "";
}

/** Map a realtime exit advice to the badge tone + Chinese label. */
const ADVICE_TONE: Record<string, StrategyAdvice["tone"]> = {
  stop_loss: "sell",
  trailing_stop: "sell",
  take_profit: "hold",
  time_stop: "warning",
};

const ADVICE_LABEL: Record<string, string> = {
  stop_loss: "触发止损",
  trailing_stop: "跟踪止损",
  take_profit: "触发止盈",
  time_stop: "持仓超时",
  hold: "建议持有",
};
