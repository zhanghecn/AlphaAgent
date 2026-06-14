import { AlertTriangle, CheckCircle2, Database, RefreshCw } from "lucide-react";
import type { BacktestDataQualityDashboard } from "@/api/quant";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function BacktestDataQualityPanel({
  quality,
  isLoading,
}: {
  quality?: BacktestDataQualityDashboard;
  isLoading: boolean;
}) {
  const verdict = qualityVerdict(quality?.status);
  const Icon = isLoading ? RefreshCw : verdict.icon;

  return (
    <section className="rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Database size={16} />
          数据质量
        </div>
        <Badge variant="outline" className={cn("rounded-md", verdict.className)}>
          <Icon size={13} className={cn(isLoading && "animate-spin", verdict.iconClassName)} />
          {isLoading ? "加载中" : verdict.label}
        </Badge>
      </div>
      {isLoading ? (
        <div className="p-3 text-sm text-muted-foreground">正在读取数据质量...</div>
      ) : !quality ? (
        <div className="p-3 text-sm text-muted-foreground">暂无数据质量结果。</div>
      ) : quality.status === "unavailable" || quality.status === "not_found" ? (
        <div className="p-3 text-sm text-muted-foreground">{quality.message ?? `状态：${quality.status}`}</div>
      ) : (
        <div className="space-y-3 p-3">
          <div className="grid gap-2 md:grid-cols-5">
            {quality.checks.map((check) => (
              <div key={check.id} className="rounded-md border p-2 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{check.label}</span>
                  <Badge variant="outline" className={cn("rounded-md", checkClass(check.status))}>
                    {checkLabel(check.status)}
                  </Badge>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {check.value == null ? "--" : check.value}
                  {check.message ? ` · ${check.message}` : ""}
                </div>
              </div>
            ))}
          </div>
          {quality.next_action ? <div className="border-t pt-3 text-sm text-muted-foreground">{quality.next_action}</div> : null}
        </div>
      )}
    </section>
  );
}

function qualityVerdict(status?: string) {
  if (status === "ready") {
    return {
      label: "数据可验证",
      className: "border-green-200 bg-green-50 text-rise dark:border-green-500/30 dark:bg-green-500/10",
      icon: CheckCircle2,
      iconClassName: "text-rise",
    };
  }
  if (status === "missing_snapshots" || status === "mixed_proxy" || status === "warning") {
    return {
      label: "需补充核查",
      className: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300",
      icon: AlertTriangle,
      iconClassName: "text-amber-600 dark:text-amber-300",
    };
  }
  return {
    label: "需复核",
    className: "border-muted bg-muted/30 text-muted-foreground",
    icon: AlertTriangle,
    iconClassName: "text-muted-foreground",
  };
}

function checkClass(status?: string) {
  if (status === "pass") return "border-green-200 bg-green-50 text-rise dark:border-green-500/30 dark:bg-green-500/10";
  if (status === "warning") return "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300";
  if (status === "fail") return "border-red-200 bg-red-50 text-fall dark:border-red-500/30 dark:bg-red-500/10";
  return "border-muted bg-muted/30 text-muted-foreground";
}

function checkLabel(status?: string) {
  if (status === "pass") return "通过";
  if (status === "warning") return "待核查";
  if (status === "fail") return "未通过";
  return status || "--";
}
