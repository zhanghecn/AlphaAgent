import * as React from "react";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";

interface SectionCardProps {
  /** 区块标题 */
  title?: React.ReactNode;
  /** 标题下方的说明文字 */
  description?: React.ReactNode;
  /** 右侧操作区（按钮、筛选器、Tab 切换等） */
  action?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  children: React.ReactNode;
}

/**
 * 区块容器：带可选标题 / 说明 / 操作区的统一页面骨架。
 * 让各页面用一致的区块结构，避免每页各写一套 header。
 */
export function SectionCard({
  title,
  description,
  action,
  className,
  bodyClassName,
  children,
}: SectionCardProps) {
  const hasHeader = title || action || description;
  return (
    <Card className={cn("wick-top overflow-hidden", className)}>
      {hasHeader && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
          <div className="min-w-0">
            {title && (
              <h3 className="font-display truncate text-sm font-semibold tracking-tight text-foreground">
                {title}
              </h3>
            )}
            {description && (
              <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
            )}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </div>
      )}
      <div className={cn("p-4", bodyClassName)}>{children}</div>
    </Card>
  );
}
