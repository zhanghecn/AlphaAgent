import { cn } from "@/lib/utils";

export function QuantWorkflowGuide({
  recommendationLoading,
  recommendationError,
  recommendationStatus,
  recommendationMessage,
  recommendationCount,
  backtestCount,
  holdingsCount,
  latestTradeDate,
  latestScreenDate,
}: {
  recommendationLoading: boolean;
  recommendationError: boolean;
  recommendationStatus?: string;
  recommendationMessage?: string;
  recommendationCount: number;
  backtestCount: number;
  holdingsCount: number;
  latestTradeDate?: string | null;
  latestScreenDate?: string | null;
}) {
  const dataState: "ready" | "warning" | "pending" =
    recommendationLoading
      ? "pending"
      : recommendationError || recommendationStatus === "unavailable"
        ? "warning"
        : "ready";
  const steps: Array<{
    label: string;
    status: "ready" | "warning" | "pending";
    value: string;
    note: string;
  }> = [
    {
      label: "日线",
      status: dataState,
      value: latestTradeDate ? `至 ${latestTradeDate}` : dataState === "pending" ? "检查中" : "待配置",
      note: recommendationMessage || "显示本地日线库最新交易日；没有同步到今天时不会显示今天。",
    },
    {
      label: "候选",
      status: latestTradeDate && latestScreenDate && latestScreenDate < latestTradeDate ? "warning" : recommendationCount > 0 ? "ready" : "pending",
      value: latestScreenDate ? `至 ${latestScreenDate}` : "未生成",
      note: "刷新候选并回测会按当前策略版本重算历史交易日，并把最新候选同步到量化候选分组。",
    },
    {
      label: "回测",
      status: backtestCount > 0 ? "ready" : "pending",
      value: backtestCount > 0 ? `${backtestCount}份` : "未运行",
      note: "历史研究先统计每日Top20候选独立D+1开盘买入后的收益胜率；组合买卖只作为执行诊断。",
    },
    {
      label: "持仓",
      status: holdingsCount > 0 ? "ready" : "pending",
      value: holdingsCount > 0 ? `${holdingsCount}只` : "空仓",
      note: "自动建仓只写模拟账户，不会下实盘委托。",
    },
  ];

  return (
    <section className="rounded-lg border">
      <div className="grid divide-y md:grid-cols-4 md:divide-x md:divide-y-0">
        {steps.map((step) => (
          <div key={step.label} className="p-2.5" title={step.note}>
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm font-medium">{step.label}</div>
              <WorkflowStatus status={step.status} />
            </div>
            <div className="mt-1 text-sm tabular-nums text-muted-foreground">{step.value}</div>
          </div>
        ))}
      </div>
      {latestTradeDate && (
        <div className="border-t px-3 py-2 text-xs text-muted-foreground">
          策略研究截止到本地日线库最新交易日 {latestTradeDate}；如果今天是交易日但这里未显示今天，需要先同步今天的日线数据再启动策略流程。
        </div>
      )}
    </section>
  );
}

function WorkflowStatus({ status }: { status: "ready" | "warning" | "pending" }) {
  const cls =
    status === "ready"
      ? "border-green-200 bg-green-50 text-green-700 dark:border-green-500/30 dark:bg-green-500/10 dark:text-green-300"
      : status === "warning"
        ? "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300"
        : "border-gray-200 bg-gray-50 text-gray-600 dark:border-gray-500/30 dark:bg-gray-500/10 dark:text-gray-300";
  const text = status === "ready" ? "就绪" : status === "warning" ? "需处理" : "待执行";
  return <span className={cn("rounded-md border px-2 py-0.5 text-xs", cls)}>{text}</span>;
}
