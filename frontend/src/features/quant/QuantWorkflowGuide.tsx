import { cn } from "@/lib/utils";
import type { MinuteGapAuditResult } from "@/api/dataSync";
import type { VnpyStatus } from "@/api/quant";

export function QuantWorkflowGuide({
  recommendationLoading,
  recommendationError,
  recommendationStatus,
  recommendationMessage,
  recommendationCount,
  backtestCount,
  holdingsCount,
  minuteAudit,
  vnpyStatus,
}: {
  recommendationLoading: boolean;
  recommendationError: boolean;
  recommendationStatus?: string;
  recommendationMessage?: string;
  recommendationCount: number;
  backtestCount: number;
  holdingsCount: number;
  minuteAudit?: MinuteGapAuditResult;
  vnpyStatus?: VnpyStatus;
}) {
  const dataState: "ready" | "warning" | "pending" =
    recommendationLoading
      ? "pending"
      : recommendationError || recommendationStatus === "unavailable"
        ? "warning"
        : "ready";
  const auditReady = minuteAudit?.status === "ready";
  const steps: Array<{
    label: string;
    status: "ready" | "warning" | "pending";
    value: string;
    note: string;
  }> = [
    {
      label: "数据",
      status: dataState,
      value: dataState === "ready" ? "可筛选" : dataState === "pending" ? "检查中" : "待配置",
      note: recommendationMessage || "需要本地股票、日线和可选财报/资金流数据。",
    },
    {
      label: "筛选",
      status: recommendationCount > 0 ? "ready" : "pending",
      value: recommendationCount > 0 ? `${recommendationCount}只` : "未生成",
      note: "运行筛选会写入量化推荐表和量化候选持仓分组。",
    },
    {
      label: "回测",
      status: backtestCount > 0 ? "ready" : "pending",
      value: backtestCount > 0 ? `${backtestCount}份` : "未运行",
      note: auditReady ? "分钟缺口已覆盖，可运行严格尾盘回测。" : "没有分钟线时只能做宽松回测或生成缺口清单。",
    },
    {
      label: "模拟",
      status: holdingsCount > 0 ? "ready" : "pending",
      value: holdingsCount > 0 ? `${holdingsCount}只` : "空仓",
      note: "自动建仓只写模拟账户，不会下实盘委托。",
    },
    {
      label: "vn.py",
      status: vnpyStatus?.status === "ready" ? "ready" : "warning",
      value: vnpyStatus?.status === "ready" ? "A股插件就绪" : "本地回测可用",
      note: "AlphaAgent 本地回测可用；A股实盘和官方数据源仍需要安装并配置对应 Gateway/Datafeed。",
    },
  ];

  return (
    <section className="rounded-lg border">
      <div className="grid divide-y md:grid-cols-5 md:divide-x md:divide-y-0">
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
    </section>
  );
}

function WorkflowStatus({ status }: { status: "ready" | "warning" | "pending" }) {
  const cls =
    status === "ready"
      ? "border-green-200 bg-green-50 text-green-700"
      : status === "warning"
        ? "border-amber-200 bg-amber-50 text-amber-700"
        : "border-gray-200 bg-gray-50 text-gray-600";
  const text = status === "ready" ? "就绪" : status === "warning" ? "待接入" : "待执行";
  return <span className={cn("rounded-md border px-2 py-0.5 text-xs", cls)}>{text}</span>;
}
