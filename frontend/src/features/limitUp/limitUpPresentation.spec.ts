import { describe, expect, it } from "vitest";

import {
  firstBoardCompositeReasons,
  limitUpLaneLabel,
} from "@/features/limitUp/limitUpPresentation";

describe("limit-up presentation", () => {
  it("presents first_board as one composite strategy", () => {
    expect(limitUpLaneLabel("first_board")).toBe("综合首板");
    expect(limitUpLaneLabel("two_to_three")).toBe("二进三");
  });

  it("merges only positive first-board research evidence", () => {
    expect(firstBoardCompositeReasons({
      board_lane: "first_board",
      warmup_group_name: "创新药",
      warmup_state: "warming",
      rotation_shadow_state: "trigger",
    })).toEqual([
      "创新药资金预热",
      "板块扩散龙头确认",
    ]);
  });

  it("hides unavailable and rejected shadow evidence", () => {
    expect(firstBoardCompositeReasons({
      board_lane: "first_board",
      warmup_group_name: "机器人",
      warmup_state: "unavailable",
      rotation_shadow_state: "rejected",
    })).toEqual([]);
  });

  it("does not expose first-board research on another lane", () => {
    expect(firstBoardCompositeReasons({
      board_lane: "two_to_three",
      warmup_group_name: "创新药",
      warmup_state: "launch",
      rotation_shadow_state: "trigger",
    })).toEqual([]);
  });
});
