import type { LimitUpSignalSnapshot } from "@/api/limitUp";
import { cn } from "@/lib/utils";
import { formatTime } from "./liveFormat";
import { isNextSessionPlan } from "./nextSessionPlan";
import { buildOpsPhases, type OpsPhase } from "./opsFlow";

interface OpsFlowRailProps {
  snapshot?: LimitUpSignalSnapshot;
}

/**
 * 作战流程导轨：把一个交易日渲染成 5 个发光节点的步进器。
 * 当前阶段脉冲（买入窗口红色 = 行动时间），已完成点亮，未来暗色。
 * 导轨本身即信息——节点时间来自 execution_schedule 的真实窗口。
 */
export function OpsFlowRail({ snapshot }: OpsFlowRailProps) {
  if (!snapshot) return null;
  const phases = buildOpsPhases(snapshot);
  const schedule = snapshot.recommendations.execution_schedule;
  const planMode = isNextSessionPlan(snapshot);
  return (
    <section aria-label="作战流程" className="border-b px-3 py-3 sm:px-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="eyebrow">作战流程 OPS FLOW</span>
        {planMode && (
          <span className="rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
            次交易日计划
          </span>
        )}
        {schedule?.message && (
          <span
            className={cn(
              "text-xs",
              schedule.entry_allowed ? "font-medium text-rise" : "text-muted-foreground",
            )}
          >
            {schedule.message}
          </span>
        )}
        {schedule?.target_at && (
          <span className="ml-auto font-mono text-[11px] tabular-nums text-muted-foreground">
            下一节点 <span className="text-foreground">{formatTime(schedule.target_at)}</span>
          </span>
        )}
      </div>
      <div className="overflow-x-auto">
        <ol className="mt-3 flex min-w-[540px]">
          {phases.map((phase, index) => (
            <li key={phase.key} className="min-w-0 flex-1">
              <div className="flex items-center">
                <PhaseDot phase={phase} />
                {index < phases.length - 1 && (
                  <span
                    className={cn(
                      "mx-2 h-px flex-1",
                      phase.state === "done" ? "bg-primary/50" : "bg-border",
                    )}
                  />
                )}
              </div>
              <div
                className={cn(
                  "mt-1.5 truncate text-xs",
                  phase.state === "active"
                    ? "font-semibold text-foreground"
                    : phase.state === "next"
                      ? "font-medium text-foreground/80"
                      : "text-muted-foreground",
                )}
              >
                {phase.label}
              </div>
              <div className="truncate font-mono text-[10px] tabular-nums text-muted-foreground/80">
                {phase.timeLabel}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function PhaseDot({ phase }: { phase: OpsPhase }) {
  if (phase.state === "done") {
    return <span className="h-2 w-2 shrink-0 rounded-full bg-primary" aria-hidden />;
  }
  if (phase.state === "active") {
    // 买入窗口红色脉冲 = 行动时间；午间 amber；盘前/计划 primary
    const tone = phase.entryWindow
      ? "bg-rise [--pulse-color:rgba(239,68,68,0.45)]"
      : phase.key === "lunch"
        ? "bg-amber-500 [--pulse-color:rgba(245,158,11,0.45)]"
        : "bg-primary";
    return (
      <span
        className={cn("ops-pulse h-2.5 w-2.5 shrink-0 rounded-full", tone)}
        aria-hidden
      />
    );
  }
  if (phase.state === "next") {
    return (
      <span
        className="h-2.5 w-2.5 shrink-0 rounded-full border-2 border-primary/50 bg-background"
        aria-hidden
      />
    );
  }
  return <span className="h-2 w-2 shrink-0 rounded-full border border-border bg-muted" aria-hidden />;
}
