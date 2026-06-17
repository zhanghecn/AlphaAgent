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
  const stageLabel = stage === "backtest" ? "自动回测" : stage === "screening" ? "刷新候选" : "准备中";
  return (
    <div className="rounded-lg border bg-muted/30 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="flex items-center gap-2 font-medium">
          <RefreshCw size={14} className="animate-spin text-primary" />
          正在刷新候选并回测{strategyName ? `（${strategyName}）` : ""} · {stageLabel}
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
        {message || "后台会按当前策略版本逐日评分，更新候选前20，并按 BUY 前10和最多10只持仓自动回测。"}
      </p>
    </div>
  );
}
