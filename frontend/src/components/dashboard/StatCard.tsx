import * as React from "react";
import { cn, formatPct, priceColorClass } from "@/lib/utils";
import { Card } from "@/components/ui/card";

interface StatCardProps {
  /** 指标名称（如「营业总收入」） */
  label: string;
  /** 主数值，支持任意 ReactNode 以便自定义格式化 */
  value: React.ReactNode;
  /** 涨跌幅（百分比数值）。正数显示红、负数绿，遵循 A 股涨红跌绿 */
  delta?: number | null;
  /** delta 文字说明，默认「同比」 */
  deltaLabel?: string;
  /** 右侧附加区（sparkline / 图标 / 徽章） */
  extra?: React.ReactNode;
  className?: string;
}

/**
 * KPI 指标卡：标题 + 大数值 + 涨跌徽章 + 可选附加区。
 * 仪表盘式信息密度的核心积木，hover 时随 Card 微抬升。
 */
export function StatCard({
  label,
  value,
  delta,
  deltaLabel = "同比",
  extra,
  className,
}: StatCardProps) {
  return (
    <Card className={cn("p-4", className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-xs font-medium text-muted-foreground">
            {label}
          </p>
          <p className="mt-1 font-display text-2xl font-bold tabular-nums tracking-tight text-foreground">
            {value}
          </p>
          {delta != null && (
            <div className="mt-1 flex items-center gap-1">
              <span
                className={cn(
                  "text-xs font-semibold tabular-nums",
                  priceColorClass(delta),
                )}
              >
                {formatPct(delta)}
              </span>
              <span className="text-xs text-muted-foreground">{deltaLabel}</span>
            </div>
          )}
        </div>
        {extra && <div className="shrink-0">{extra}</div>}
      </div>
    </Card>
  );
}
