import { describe, expect, it } from "vitest";

import type { LianbanReview } from "@/api/lianban";
import { brokenItemSuffix } from "./BrokenBoardsSection";

type BrokenItem = LianbanReview["broken_list"][number];

function makeItem(overrides: Partial<BrokenItem> = {}): BrokenItem {
  return {
    vt_symbol: "600179.SSE",
    name: "安通控股",
    first_limit_time: "09:25:03",
    break_count: 2,
    industry: "物流",
    ...overrides,
  };
}

describe("brokenItemSuffix（炸板行后缀）", () => {
  it("combines 首封HH:MM封 + 炸N次（2026-08-13 实测：安通控股 09:25:03 炸2）", () => {
    expect(brokenItemSuffix(makeItem())).toBe("09:25封·炸2次");
  });

  it("trims HH:MM:SS to HH:MM", () => {
    expect(brokenItemSuffix(makeItem({ first_limit_time: "13:05:59", break_count: 1 }))).toBe(
      "13:05封·炸1次",
    );
  });

  it("omits the break clause when break_count is null（只显时间）", () => {
    expect(brokenItemSuffix(makeItem({ break_count: null }))).toBe("09:25封");
  });

  it("omits the break clause when break_count is 0（防御：0 次不构成炸板语义）", () => {
    expect(brokenItemSuffix(makeItem({ break_count: 0 }))).toBe("09:25封");
  });

  it("handles null first_limit_time（rebuild 口径无盘口时间）", () => {
    expect(brokenItemSuffix(makeItem({ first_limit_time: null }))).toBe("炸2次");
  });

  it("returns null when both fields are missing", () => {
    expect(brokenItemSuffix(makeItem({ first_limit_time: null, break_count: null }))).toBeNull();
  });
});
