import { RefreshCw } from "lucide-react";

/**
 * 批量生成候选时的实时进度反馈。
 *
 * 后端 screen_stocks_range 每完成一个交易日就独立 persist 一个 run，
 * 因此前端轮询已 persist 的 run 数 / 交易日总数即可得到实时进度。
 * 多策略预算时，进度 = (已完成策略数 + 当前策略内交易日比例) / 策略总数。
 */
export function ScreenProgress({
  completed,
  total,
  strategyName,
  strategyIndex,
  strategyTotal,
}: {
  completed: number;
  total: number;
  strategyName?: string;
  strategyIndex?: number;
  strategyTotal?: number;
}) {
  const multiStrategy = (strategyTotal ?? 0) > 1;
  const dayRatio = total > 0 ? completed / total : 0;
  const pct = multiStrategy
    ? Math.min(100, Math.round((((strategyIndex ?? 0) + dayRatio) / (strategyTotal as number)) * 100))
    : Math.min(100, Math.round(dayRatio * 100));
  const strategyLabel = multiStrategy && strategyName
    ? `策略 ${(strategyIndex ?? 0) + 1}/${strategyTotal} · ${strategyName}`
    : strategyName;
  return (
    <div className="rounded-lg border bg-muted/30 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="flex items-center gap-2 font-medium">
          <RefreshCw size={14} className="animate-spin text-primary" />
          正在批量生成{multiStrategy ? "全部策略" : "全部交易日"}候选{strategyLabel ? `（${strategyLabel}）` : ""}
        </span>
        <span className="tabular-nums text-muted-foreground">
          {completed} / {total} 交易日 · {pct}%
        </span>
      </div>
      <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-primary transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        {multiStrategy ? "每个策略 × 交易日独立计算并存储买卖计划" : "每个交易日独立计算并存储买卖计划"}，完成后可在候选列表与单股详情直接查看，无需重算。
      </p>
    </div>
  );
}
