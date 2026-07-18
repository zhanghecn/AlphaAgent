import type { LimitUpSignalSnapshot } from "@/api/limitUp";
import { isNextSessionPlan } from "./nextSessionPlan";

export type OpsPhaseState = "done" | "active" | "next" | "pending";

export interface OpsPhase {
  key: string;
  label: string;
  timeLabel: string;
  state: OpsPhaseState;
  /** 买入窗口阶段（上午/下午），节点用 rise 脉冲强调“行动时间” */
  entryWindow: boolean;
}

/** 后端 session_stage -> 作战阶段下标（0 盘前 / 1 上午 / 2 午间 / 3 下午） */
const STAGE_INDEX: Record<string, number> = {
  preopen: 0,
  auction_watch: 0,
  auction: 0,
  morning: 1,
  lunch: 2,
  afternoon: 3,
  tail: 3,
  close_auction: 3,
};

const PHASE_KEYS = ["preopen", "morning", "lunch", "afternoon", "d1_exit"] as const;
const PHASE_LABELS = ["盘前竞价", "上午窗口", "午间休市", "下午窗口", "D+1 卖出"];
const DEFAULT_WINDOWS = ["09:30-11:30", "13:00-15:00"];

/**
 * 把一个交易日渲染成 5 个作战阶段。
 * 时间标签优先取 execution_schedule 的真实窗口，缺失时退回官方交易时段。
 */
export function buildOpsPhases(snapshot?: LimitUpSignalSnapshot): OpsPhase[] {
  const schedule = snapshot?.recommendations.execution_schedule;
  const windows = schedule?.entry_windows ?? [];
  const exitTime = schedule?.exit_time || "15:00";
  const timeLabels = [
    "09:15-09:30",
    windows[0] ?? DEFAULT_WINDOWS[0],
    "11:30-13:00",
    windows[1] ?? DEFAULT_WINDOWS[1],
    `D+1 ${exitTime}`,
  ];

  let activeIndex: number | null = null;
  let nextIndex: number | null = null;
  if (snapshot) {
    if (isNextSessionPlan(snapshot)) {
      // 次交易日计划模式：盘前即起点，全程等待执行
      activeIndex = 0;
    } else {
      const stage = snapshot.session_stage ?? "";
      if (stage === "closed" || stage === "") {
        // 收盘后（或阶段未知）：今天流程已走完，下一节点是 D+1 卖出
        nextIndex = 4;
      } else {
        activeIndex = STAGE_INDEX[stage] ?? null;
      }
    }
  }

  return PHASE_LABELS.map((label, index) => {
    let state: OpsPhaseState = "pending";
    if (activeIndex != null) {
      if (index < activeIndex) state = "done";
      else if (index === activeIndex) state = "active";
      else if (index === activeIndex + 1) state = "next";
    } else if (nextIndex != null) {
      if (index < nextIndex) state = "done";
      else if (index === nextIndex) state = "next";
    }
    return {
      key: PHASE_KEYS[index],
      label,
      timeLabel: timeLabels[index],
      state,
      entryWindow: index === 1 || index === 3,
    };
  });
}
