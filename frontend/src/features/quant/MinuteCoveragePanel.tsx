import { AlertTriangle, CheckCircle2, CircleDashed } from "lucide-react";
import type { BacktestMinuteCoverage } from "@/api/quant";
import { InfoCell } from "@/components/InfoCell";
import { cn } from "@/lib/utils";

export function MinuteCoveragePanel({
  coverage,
  isLoading,
}: {
  coverage?: BacktestMinuteCoverage;
  isLoading: boolean;
}) {
  const verdict = coverageVerdict(coverage?.status);
  const VerdictIcon = verdict.icon;

  return (
    <div className="rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div className="flex items-center gap-2">
          <VerdictIcon size={16} className={verdict.iconClassName} />
          <div className="text-sm font-medium">14:30覆盖</div>
        </div>
        <span className={cn("rounded-md border px-2 py-1 text-xs", verdict.className)}>
          {isLoading ? "加载中" : verdict.label}
        </span>
      </div>
      {isLoading ? (
        <div className="p-3 text-sm text-muted-foreground">正在读取覆盖情况...</div>
      ) : !coverage ? (
        <div className="p-3 text-sm text-muted-foreground">暂无覆盖数据。</div>
      ) : coverage.status !== "ready" &&
        coverage.status !== "mixed_proxy" &&
        coverage.status !== "missing_snapshots" &&
        coverage.status !== "strategy_not_triggered" &&
        coverage.status !== "empty" ? (
        <div className="p-3 text-sm text-muted-foreground">{coverage.message || `覆盖状态：${coverage.status}`}</div>
      ) : (
        <div className="space-y-3 p-3">
          <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <InfoCell label="买入笔数" value={coverage.buy_count ?? 0} />
            <InfoCell label="14:30真实" value={`${coverage.minute_1430_count ?? 0}笔 / ${formatCoveragePct(coverage.minute_1430_ratio)}`} />
            <InfoCell label="收盘代理" value={`${coverage.daily_close_proxy_count ?? 0}笔 / ${formatCoveragePct(coverage.daily_close_proxy_ratio)}`} />
            <InfoCell label="缺快照拒单" value={`${coverage.minute_gap_rejected_count ?? 0}笔`} />
          </div>
          {coverage.next_action && (
            <div className="border-t pt-3 text-sm text-muted-foreground">{coverage.next_action}</div>
          )}
        </div>
      )}
    </div>
  );
}

function coverageVerdict(status?: string) {
  if (status === "ready") {
    return {
      label: "可按真实14:30解读",
      className: "border-green-200 bg-green-50 text-rise dark:border-green-500/30 dark:bg-green-500/10",
      icon: CheckCircle2,
      iconClassName: "text-rise",
    };
  }
  if (status === "missing_snapshots") {
    return {
      label: "缺14:30快照",
      className: "border-red-200 bg-red-50 text-fall dark:border-red-500/30 dark:bg-red-500/10",
      icon: AlertTriangle,
      iconClassName: "text-fall",
    };
  }
  if (status === "mixed_proxy") {
    return {
      label: "混合代理",
      className: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300",
      icon: AlertTriangle,
      iconClassName: "text-amber-600 dark:text-amber-300",
    };
  }
  if (status === "strategy_not_triggered") {
    return {
      label: "条件拒单",
      className: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300",
      icon: CircleDashed,
      iconClassName: "text-amber-600 dark:text-amber-300",
    };
  }
  if (status === "empty") {
    return {
      label: "无买入",
      className: "border-muted bg-muted/30 text-muted-foreground",
      icon: CircleDashed,
      iconClassName: "text-muted-foreground",
    };
  }
  return {
    label: "需复核",
    className: "border-muted bg-muted/30 text-muted-foreground",
    icon: CircleDashed,
    iconClassName: "text-muted-foreground",
  };
}

function formatCoveragePct(value?: number | null): string {
  if (value == null) return "--";
  return `${value.toFixed(2)}%`;
}
