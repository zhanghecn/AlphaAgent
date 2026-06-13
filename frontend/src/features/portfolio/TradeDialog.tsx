import { useEffect, useState } from "react";
import { Modal, ModalBody, ModalFooter, ModalHeader } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { cn, formatAmount, formatPrice, priceColorClass } from "@/lib/utils";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import type { SimulationPosition } from "@/api/quant";

export interface TradeOrderPayload {
  vt_symbol: string;
  side: "BUY" | "SELL";
  volume?: number;
  amount?: number;
  price?: number;
  reason?: string;
}

interface TradeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: "sell" | "add";
  position: SimulationPosition | null;
  onConfirm: (payload: TradeOrderPayload) => void;
  isPlacing: boolean;
  error?: Error | null;
}

const HUNDRED = 100;

/**
 * TradeDialog — manual sell / add-position confirmation panel.
 *
 * Sell: volume input floored to 100-share lots, shows proceeds + estimated
 * P&L. Add: amount input converted to lots, with an explicit notice that the
 * existing stop-loss / take-profit lines are kept (backend _apply_buy does not
 * reset them for an existing position).
 */
export function TradeDialog({
  open,
  onOpenChange,
  mode,
  position,
  onConfirm,
  isPlacing,
  error,
}: TradeDialogProps) {
  const isSell = mode === "sell";
  const [volumeInput, setVolumeInput] = useState("");
  const [amountInput, setAmountInput] = useState("100000");

  useEffect(() => {
    if (open && position) {
      setVolumeInput(String(position.available ?? position.volume ?? ""));
      setAmountInput("100000");
    }
  }, [open, position]);

  if (!position) return null;

  const price = position.last_price ?? 0;
  const cost = position.cost_price ?? 0;
  const available = position.available ?? position.volume ?? 0;

  // Sell: floor volume to 100-share lots.
  const rawVolume = Number(volumeInput) || 0;
  const volumeLots = Math.floor(rawVolume / HUNDRED) * HUNDRED;
  const sellProceeds = volumeLots * price;
  const sellPnl = (price - cost) * volumeLots;
  const sellDisabled = volumeLots <= 0 || volumeLots > available;

  // Add: amount -> 100-share lots.
  const amount = Number(amountInput) || 0;
  const addLots = price > 0 ? Math.floor(amount / price / HUNDRED) * HUNDRED : 0;
  const addOccupies = addLots * price;
  const addDisabled = addLots <= 0;

  const handleConfirm = () => {
    if (isSell) {
      if (sellDisabled) return;
      onConfirm({ vt_symbol: position.vt_symbol, side: "SELL", volume: volumeLots, price });
    } else {
      if (addDisabled) return;
      onConfirm({ vt_symbol: position.vt_symbol, side: "BUY", amount, price });
    }
  };

  return (
    <Modal open={open} onOpenChange={onOpenChange} className="max-w-md">
      <ModalHeader title={isSell ? "模拟卖出" : "模拟加仓"} onClose={() => onOpenChange(false)} />
      <ModalBody className="space-y-4">
        <div className="rounded-lg border p-3 text-sm">
          <StockIdentityLink
            name={position.name}
            vtSymbol={position.vt_symbol}
            board={position.board}
            boardLabel={position.board_label}
          />
          <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span>
              现价 <span className="text-foreground tabular-nums">{formatPrice(price)}</span>
            </span>
            <span>
              成本 <span className="text-foreground tabular-nums">{formatPrice(cost)}</span>
            </span>
            <span>
              持仓 <span className="text-foreground tabular-nums">{position.volume.toLocaleString()} 股</span>
            </span>
            <span>
              可卖 <span className="text-foreground tabular-nums">{available.toLocaleString()} 股</span>
            </span>
          </div>
        </div>

        {isSell ? (
          <div className="space-y-2">
            <label className="block text-sm font-medium">卖出数量（股）</label>
            <input
              type="number"
              className="w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/50"
              value={volumeInput}
              onChange={(event) => setVolumeInput(event.target.value)}
              min={HUNDRED}
              step={HUNDRED}
            />
            <p className="text-xs text-muted-foreground">
              按整手成交：实际{" "}
              <span className="text-foreground tabular-nums">{volumeLots.toLocaleString()}</span> 股
              · 预估回收 <span className="text-foreground tabular-nums">{formatAmount(sellProceeds)}</span>{" "}
              · 盈亏{" "}
              <span className={cn("tabular-nums", priceColorClass(sellPnl))}>{formatAmount(sellPnl)}</span>
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            <label className="block text-sm font-medium">加仓金额（元）</label>
            <input
              type="number"
              className="w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/50"
              value={amountInput}
              onChange={(event) => setAmountInput(event.target.value)}
              min={HUNDRED}
            />
            <p className="text-xs text-muted-foreground">
              按整手成交：约{" "}
              <span className="text-foreground tabular-nums">{addLots.toLocaleString()}</span> 股 · 占用{" "}
              <span className="text-foreground tabular-nums">{formatAmount(addOccupies)}</span>
            </p>
            <div className="rounded-md border border-brand-500/30 bg-brand-500/5 px-3 py-2 text-xs text-muted-foreground">
              止损 <span className="text-foreground tabular-nums">{formatPrice(position.stop_loss_price)}</span>{" "}
              / 止盈 <span className="text-foreground tabular-nums">{formatPrice(position.take_profit_price)}</span>{" "}
              维持原值，不会随本次加仓价重置。
            </div>
          </div>
        )}

        {error && <p className="text-xs text-destructive">{error.message}</p>}
      </ModalBody>
      <ModalFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isPlacing}>
          取消
        </Button>
        <Button
          variant={isSell ? "destructive" : "brand"}
          onClick={handleConfirm}
          disabled={(isSell ? sellDisabled : addDisabled) || isPlacing}
        >
          {isPlacing ? "提交中…" : isSell ? "确认卖出" : "确认加仓"}
        </Button>
      </ModalFooter>
    </Modal>
  );
}
