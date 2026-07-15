import type { BoardLaneKey, LimitUpLiveSignal } from "@/api/limitUp";

type FirstBoardCompositeSignal = Pick<
  LimitUpLiveSignal,
  "board_lane" | "warmup_group_name" | "warmup_state" | "rotation_shadow_state"
>;

const BOARD_LANE_LABELS: Record<BoardLaneKey, string> = {
  first_board: "综合首板",
  two_to_three: "二进三",
  high_board: "高板",
};

export function limitUpLaneLabel(lane: BoardLaneKey): string {
  return BOARD_LANE_LABELS[lane];
}

export function firstBoardCompositeReasons(signal: FirstBoardCompositeSignal): string[] {
  if (signal.board_lane !== "first_board") return [];

  const reasons: string[] = [];
  if (
    signal.warmup_group_name
    && (signal.warmup_state === "warming" || signal.warmup_state === "launch")
  ) {
    reasons.push(`${signal.warmup_group_name}资金预热`);
  }
  if (signal.rotation_shadow_state === "trigger") {
    reasons.push("板块扩散龙头确认");
  }
  return reasons;
}
