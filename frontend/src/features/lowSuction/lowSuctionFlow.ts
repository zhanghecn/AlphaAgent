import type { LowSuctionStrategyOverview } from "@/api/lowSuction";

export type LowSuctionPhaseState = "done" | "active" | "next" | "pending";
export type LowSuctionPhaseTone = "default" | "lunch" | "action";

export interface LowSuctionPhase {
  key: string;
  label: string;
  timeLabel: string;
  state: LowSuctionPhaseState;
  /** 行动节点（尾盘确认/纸面买入）用 rise 脉冲，午间休市用 amber */
  tone: LowSuctionPhaseTone;
}

const PHASE_KEYS = ["open_scan", "morning", "lunch", "afternoon", "final", "entry"] as const;
const PHASE_LABELS = ["早盘预警", "上午跟踪", "午间休市", "下午跟踪", "尾盘确认", "纸面买入"];
const PHASE_TIMES = ["09:30", "10:30 · 11:30", "11:30-13:00", "13:30 · 14:30", "14:50", "14:55"];
/** 每个节点生效的起始分钟（上海时间），14:55 买入窗到 15:00 收盘结束 */
const PHASE_START_MINUTES = [9 * 60 + 30, 10 * 60 + 30, 11 * 60 + 30, 13 * 60, 14 * 60 + 50, 14 * 60 + 55];
const MARKET_CLOSE_MINUTES = 15 * 60;

/**
 * 把反包交易日渲染成 6 个作战节点。
 * 状态机以服务端 generated_at 为时钟；休市日重置到早盘预警等待。
 */
export function buildLowSuctionPhases(strategy: LowSuctionStrategyOverview): LowSuctionPhase[] {
  const minutes = shanghaiMinutes(strategy.generated_at);
  const marketClosed = strategy.session.status === "market_closed";

  let activeIndex: number | null = null;
  let nextIndex: number | null = null;
  if (marketClosed || minutes == null || minutes < PHASE_START_MINUTES[0]) {
    nextIndex = 0;
  } else if (minutes >= MARKET_CLOSE_MINUTES) {
    nextIndex = null; // 收盘后：今天流程已走完
  } else {
    activeIndex = PHASE_START_MINUTES.reduce(
      (current, start, index) => (minutes >= start ? index : current),
      0,
    );
  }

  return PHASE_LABELS.map((label, index) => {
    let state: LowSuctionPhaseState = "pending";
    if (minutes != null && !marketClosed && minutes >= MARKET_CLOSE_MINUTES) {
      state = "done";
    } else if (activeIndex != null) {
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
      timeLabel: PHASE_TIMES[index],
      state,
      tone: index === 2 ? "lunch" : index >= 4 ? "action" : "default",
    };
  });
}

/** 从带时区的 ISO 时间提取上海 HH:mm 分钟数，避免本地时区干扰 */
function shanghaiMinutes(value: string): number | null {
  const match = /T(\d{2}):(\d{2})/.exec(value);
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
}
