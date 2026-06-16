import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Modal, ModalBody, ModalFooter, ModalHeader } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { fetchQuantStrategies } from "@/api/quant";

const DEFAULT_MANUAL_STRATEGY_ID = "mainline_dragon_pullback";

/**
 * 手动加入持仓对话框。
 *
 * 从候选列表/任意股票列表点击"加入持仓"打开。价格默认用候选信号价
 * （risk_control.trade_plan.entry_price），用户可改；数量按 A 股 100 股整手取整。
 * 绑定一个量化策略（默认候选来源策略或主线回踩），后端据此为该持仓
 * 计算"持有/卖出"实时建议（grill 决策：绑定式策略）。提交后通过
 * place_order 进入"手动持仓"组（manual_holding）。
 */
export function ManualBuyDialog({
  open,
  onOpenChange,
  vtSymbol,
  name,
  defaultPrice,
  defaultStrategyId,
  onConfirm,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  vtSymbol: string;
  name?: string | null;
  defaultPrice?: number;
  defaultStrategyId?: string;
  onConfirm: (price: number, volume: number, strategyId: string) => void;
  isPending?: boolean;
}) {
  const [priceText, setPriceText] = useState("");
  const [volumeText, setVolumeText] = useState("100");
  const [strategyId, setStrategyId] = useState("");

  const strategiesQuery = useQuery({
    queryKey: ["quantStrategies"],
    queryFn: fetchQuantStrategies,
    staleTime: 5 * 60 * 1000,
  });
  const strategies = strategiesQuery.data?.items ?? [];
  const isPublicStrategy = strategies.some((strategy) => strategy.id === defaultStrategyId);
  const fallbackStrategy =
    isPublicStrategy ? defaultStrategyId! : strategiesQuery.data?.default_strategy_id || DEFAULT_MANUAL_STRATEGY_ID;
  const selectedStrategy = strategies.find((strategy) => strategy.id === strategyId);

  useEffect(() => {
    if (open) {
      setPriceText(defaultPrice ? String(defaultPrice) : "");
      setVolumeText("100");
      setStrategyId(fallbackStrategy);
    }
  }, [open, defaultPrice, fallbackStrategy]);

  const price = Number(priceText) || 0;
  const rawVolume = Number(volumeText) || 0;
  const volume = Math.floor(rawVolume / 100) * 100;
  const canConfirm = price > 0 && volume > 0 && Boolean(strategyId);

  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <ModalHeader title={`加入手动持仓 · ${name ?? vtSymbol}`} onClose={() => onOpenChange(false)} />
      <ModalBody>
        <div className="space-y-3 text-sm">
          <div>
            <label className="text-muted-foreground">绑定策略（用于持仓建议评估）</label>
            <div className="mt-1 flex h-9 items-center rounded-md border bg-muted/30 px-3 text-sm">
              {selectedStrategy?.name ?? "主线龙回头回踩低吸"}
            </div>
          </div>
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
            加入后进入"手动持仓"，按所选策略评估持有/卖出建议。
          </p>
        </div>
      </ModalBody>
      <ModalFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
        <Button disabled={!canConfirm || isPending} onClick={() => onConfirm(price, volume, strategyId)}>
          {isPending ? "提交中..." : "确认加入"}
        </Button>
      </ModalFooter>
    </Modal>
  );
}
