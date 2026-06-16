import { RefreshCw } from "lucide-react";

export function ScreenProgress({
  completed,
  total,
  pct,
  stage,
  message,
  strategyName,
}: {
  completed: number;
  total: number;
  pct?: number;
  stage?: string;
  message?: string | null;
  strategyName?: string;
}) {
  const fallbackPct = total > 0 ? Math.round((completed / total) * 100) : 0;
  const safePct = Math.min(100, Math.max(0, Math.round(pct ?? fallbackPct)));
  const stageLabel = stage === "backtest" ? "组合回测" : stage === "screening" ? "候选和买卖记录" : "策略研究";
  return (
    <div className="rounded-lg border bg-muted/30 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="flex items-center gap-2 font-medium">
          <RefreshCw size={14} className="animate-spin text-primary" />
          正在运行策略研究{strategyName ? `（${strategyName}）` : ""} · {stageLabel}
        </span>
        <span className="tabular-nums text-muted-foreground">
          {total > 0 ? `${completed} / ${total} 交易日 · ` : ""}{safePct}%
        </span>
      </div>
      <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-all duration-500"
          style={{ width: `${safePct}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        {message || "后台会按当前策略版本刷新候选、生成买卖记录并运行组合回测，完成后页面会刷新最新候选和回测结果。"}
      </p>
    </div>
  );
}
