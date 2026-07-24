import type { LimitUpSignalSnapshot } from "@/api/limitUp";
import { FlowRail, type FlowRailPhase } from "@/components/FlowRail";
import { cn } from "@/lib/utils";
import { formatTime } from "./liveFormat";
import { isNextSessionPlan } from "./nextSessionPlan";
import { buildOpsPhases, type OpsPhase } from "./opsFlow";

interface OpsFlowRailProps {
  snapshot?: LimitUpSignalSnapshot;
}

/**
 * 打板作战流程导轨：5 个作战阶段 + 次交易日计划 pill + 排程消息。
 * 节点渲染复用通用 FlowRail；打板只负责把 OpsPhase 映射成通用相位。
 */
export function OpsFlowRail({ snapshot }: OpsFlowRailProps) {
  if (!snapshot) return null;
  const phases = buildOpsPhases(snapshot).map(toFlowPhase);
  const schedule = snapshot.recommendations.execution_schedule;
  const planMode = isNextSessionPlan(snapshot);
  return (
    <FlowRail
      label="作战流程 OPS FLOW"
      phases={phases}
      nextAt={schedule?.target_at ? formatTime(schedule.target_at) : undefined}
    >
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
    </FlowRail>
  );
}

function toFlowPhase(phase: OpsPhase): FlowRailPhase {
  return {
    key: phase.key,
    label: phase.label,
    timeLabel: phase.timeLabel,
    state: phase.state,
    tone: phase.entryWindow ? "action" : phase.key === "lunch" ? "lunch" : "default",
  };
}
