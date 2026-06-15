/**
 * Trade actions hook.
 *
 * Wraps placeOrder (manual sell / add position) and autoBuyRecommendations
 * (batch build from quant candidates) mutations, with cache invalidation
 * that mirrors the existing PortfolioPage set so QuantTradingPage stays in
 * sync. Every outcome surfaces a toast (filled / rejected / invalid / error)
 * so the user always knows whether the click worked.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { autoBuyRecommendations, placeOrder } from "@/api/quant";
import type { AutoBuyResult, PlaceOrderResult } from "@/api/quant";
import { useToast } from "@/components/ui/toast";

export function useTradeActions(accountId?: number) {
  const queryClient = useQueryClient();
  const toast = useToast();

  const placeOrderMutation = useMutation({
    mutationFn: (payload: Parameters<typeof placeOrder>[1]) => {
      if (!accountId) throw new Error("暂无可用持仓账户，请先刷新持仓数据");
      return placeOrder(accountId, payload);
    },
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["portfolioHoldings"] });
      queryClient.invalidateQueries({ queryKey: ["simulationAccounts"] });
      if (accountId) queryClient.invalidateQueries({ queryKey: ["riskEvents", accountId] });
      if (data.status === "filled") {
        // Use variables.side (what we sent), not data.side — the backend
        // _fill_order result does not echo back the side field.
        const action = variables.side === "SELL" ? "卖出" : "买入";
        toast({
          title: `${action}成功`,
          description: data.vt_symbol ? `${data.vt_symbol}${data.volume ? ` · ${data.volume} 股` : ""}` : undefined,
          variant: "success",
        });
      } else {
        toast({
          title: "交易未成交",
          description: data.reason || data.message || data.status,
          variant: "error",
        });
      }
    },
    onError: (error) => {
      toast({ title: "交易失败", description: error.message, variant: "error" });
    },
  });

  const autoBuyMutation = useMutation({
    mutationFn: (payload: Parameters<typeof autoBuyRecommendations>[0]) =>
      autoBuyRecommendations({ account_id: accountId, ...payload }),
    onSuccess: (data) => {
      // Mirror PortfolioPage.tsx invalidation set (auto-buy upserts
      // simulation_auto group items, so groups + items must refresh too).
      queryClient.invalidateQueries({ queryKey: ["portfolioGroups"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioHoldings"] });
      queryClient.invalidateQueries({ queryKey: ["simulationAccounts"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems"] });

      if (data.status === "empty") {
        toast({ title: "无可建仓候选", description: data.message, variant: "default" });
        return;
      }
      const items = (data.items ?? []) as Array<{ status?: string }>;
      const filled = items.filter((i) => i.status === "filled").length;
      const skipped = items.filter((i) => i.status === "skipped").length;
      const rejected = items.filter((i) => i.status === "rejected").length;
      const detail = [`成功 ${filled}`, skipped > 0 ? `跳过 ${skipped}` : "", rejected > 0 ? `拒绝 ${rejected}` : ""]
        .filter(Boolean)
        .join(" · ");
      toast({
        title: filled > 0 ? "建仓完成" : "建仓未成功",
        description: detail || undefined,
        variant: filled > 0 ? "success" : "error",
      });
    },
    onError: (error) => {
      toast({ title: "建仓失败", description: error.message, variant: "error" });
    },
  });

  return {
    placeOrder: placeOrderMutation.mutate,
    placeOrderAsync: placeOrderMutation.mutateAsync,
    placeOrderResult: placeOrderMutation.data as PlaceOrderResult | undefined,
    isPlacing: placeOrderMutation.isPending,
    placeOrderError: placeOrderMutation.error,
    resetPlaceOrder: placeOrderMutation.reset,
    autoBuy: autoBuyMutation.mutate,
    autoBuyResult: autoBuyMutation.data as AutoBuyResult | undefined,
    isAutoBuying: autoBuyMutation.isPending,
    autoBuyError: autoBuyMutation.error,
    resetAutoBuy: autoBuyMutation.reset,
  };
}
