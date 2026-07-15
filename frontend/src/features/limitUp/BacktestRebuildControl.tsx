import { RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface BacktestRebuildControlProps {
  running: boolean;
  error: string | null;
  onRebuild: () => void;
}

export function BacktestRebuildControl({
  running,
  error,
  onRebuild,
}: BacktestRebuildControlProps) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <Button
        type="button"
        size="sm"
        variant="outline"
        className="gap-2"
        disabled={running}
        onClick={onRebuild}
      >
        <RefreshCw size={15} className={cn(running && "animate-spin")} />
        {running ? "计算中" : "重新计算"}
      </Button>
      <span aria-live="polite" className="text-xs text-muted-foreground">
        {running ? "历史账本重算中，当前显示上次结果" : null}
        {!running && error ? `重算失败：${error}` : null}
      </span>
    </div>
  );
}
