import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type FlowPhaseState = "done" | "active" | "next" | "pending";
export type FlowPhaseTone = "default" | "lunch" | "action";

export interface FlowRailPhase {
  key: string;
  label: string;
  timeLabel: string;
  state: FlowPhaseState;
  /** action = 行动时间（rise 脉冲），lunch = 午间 amber，default = primary */
  tone?: FlowPhaseTone;
}

interface FlowRailProps {
  /** eyebrow 标签，如 "作战流程 OPS FLOW" */
  label: string;
  phases: FlowRailPhase[];
  /** 右侧 mono 下一节点时间，如 "14:30:00" */
  nextAt?: string;
  /** 头部附加内容（状态 pill、计划说明等） */
  children?: ReactNode;
}

/**
 * 通用作战流程导轨：把一个交易日渲染成发光节点步进器。
 * 当前阶段脉冲（action 红色 = 行动时间），已完成点亮，未来暗色。
 * 导轨本身即信息——打板与反包共用同一视觉语言。
 */
export function FlowRail({ label, phases, nextAt, children }: FlowRailProps) {
  return (
    <section aria-label="作战流程" className="border-b px-3 py-3 sm:px-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="eyebrow">{label}</span>
        {children}
        {nextAt && (
          <span className="ml-auto font-mono text-[11px] tabular-nums text-muted-foreground">
            下一节点 <span className="text-foreground">{nextAt}</span>
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

function PhaseDot({ phase }: { phase: FlowRailPhase }) {
  if (phase.state === "done") {
    return <span className="h-2 w-2 shrink-0 rounded-full bg-primary" aria-hidden />;
  }
  if (phase.state === "active") {
    const tone =
      phase.tone === "action"
        ? "bg-rise [--pulse-color:rgba(239,68,68,0.45)]"
        : phase.tone === "lunch"
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
