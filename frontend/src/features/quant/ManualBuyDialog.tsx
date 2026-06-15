import { useEffect, useState } from "react";
import { Modal, ModalHeader, ModalBody, ModalFooter } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";

/**
 * 手动加入持仓对话框。
 *
 * 从候选列表点击"加入持仓"打开，价格默认用候选信号价（risk_control.trade_plan.entry_price），
 * 用户可改；数量按 A 股 100 股整手取整。提交后通过 place_order 进入
 * "手动持仓"组（manual_holding），与策略自动建仓（simulation_auto）分开管理。
 */
export function ManualBuyDialog({
  open,
  onOpenChange,
  vtSymbol,
  name,
  defaultPrice,
  onConfirm,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  vtSymbol: string;
  name?: string | null;
  defaultPrice?: number;
  onConfirm: (price: number, volume: number) => void;
  isPending?: boolean;
}) {
  const [priceText, setPriceText] = useState("");
  const [volumeText, setVolumeText] = useState("100");

  useEffect(() => {
    if (open) {
      setPriceText(defaultPrice ? String(defaultPrice) : "");
      setVolumeText("100");
    }
  }, [open, defaultPrice]);

  const price = Number(priceText) || 0;
  const rawVolume = Number(volumeText) || 0;
  const volume = Math.floor(rawVolume / 100) * 100;
  const canConfirm = price > 0 && volume > 0;

  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <ModalHeader title={`加入手动持仓 · ${name ?? vtSymbol}`} onClose={() => onOpenChange(false)} />
      <ModalBody>
        <div className="space-y-3 text-sm">
          <div>
            <label className="text-muted-foreground">买入价（默认候选信号价，可改）</label>
            <input
              type="number"
              step="0.01"
              min="0"
              className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
              value={priceText}
              onChange={(event) => setPriceText(event.target.value)}
            />
          </div>
          <div>
            <label className="text-muted-foreground">买入数量（股）</label>
            <input
              type="number"
              step="100"
              min="100"
              className="mt-1 h-9 w-full rounded-md border bg-background px-3 text-sm"
              value={volumeText}
              onChange={(event) => setVolumeText(event.target.value)}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            实际记录 {volume > 0 ? `${volume.toLocaleString()} 股` : "数量不足"}（A 股按 100 股整手取整）。
            加入后进入"手动持仓"，与策略自动建仓分开管理。
          </p>
        </div>
      </ModalBody>
      <ModalFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
        <Button disabled={!canConfirm || isPending} onClick={() => onConfirm(price, volume)}>
          {isPending ? "提交中..." : "确认加入"}
        </Button>
      </ModalFooter>
    </Modal>
  );
}
