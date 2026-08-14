import { describe, expect, it } from "vitest";

import type { LadderPromotionRow } from "@/api/lianban";
import {
  promotionBarPercent,
  promotionRateText,
  promotionRowLabel,
  sortPromotionRows,
} from "./PromotionMatrixCard";

function makeRow(streak: number | string, rate: number | null = 0.2): LadderPromotionRow {
  return { streak, samples: 10, promoted: 2, rate };
}

describe("promotionRowLabel（档位标签）", () => {
  it("formats numeric streaks as N进N+1", () => {
    expect(promotionRowLabel(1)).toBe("1进2");
    expect(promotionRowLabel(4)).toBe("4进5");
    expect(promotionRowLabel(7)).toBe("7进8");
  });

  it("keeps the merged 8+ bucket as-is", () => {
    expect(promotionRowLabel("8+")).toBe("8+");
  });

  it("tolerates backend serializing numeric streak as string", () => {
    expect(promotionRowLabel("3")).toBe("3进4");
  });
});

describe("promotionRateText（晋级率文案）", () => {
  it("formats a 0-1 ratio with one decimal", () => {
    expect(promotionRateText(0.136, 4122)).toBe("13.6%");
    expect(promotionRateText(0.25, 556)).toBe("25.0%");
  });

  it("degrades to -- for null / NaN rates", () => {
    expect(promotionRateText(null, 10)).toBe("--");
    expect(promotionRateText(undefined, 10)).toBe("--");
    expect(promotionRateText(Number.NaN, 10)).toBe("--");
  });

  it("degrades to -- for 0 样本 even if a rate leaked through", () => {
    expect(promotionRateText(0.5, 0)).toBe("--");
  });
});

describe("promotionBarPercent（横条宽度）", () => {
  it("scales the rate to 0-100", () => {
    expect(promotionBarPercent(0.136)).toBeCloseTo(13.6);
    expect(promotionBarPercent(1)).toBe(100);
  });

  it("clamps out-of-range rates", () => {
    expect(promotionBarPercent(1.5)).toBe(100);
    expect(promotionBarPercent(-0.2)).toBe(0);
  });

  it("renders no bar for missing / invalid rates", () => {
    expect(promotionBarPercent(null)).toBe(0);
    expect(promotionBarPercent(undefined)).toBe(0);
    expect(promotionBarPercent(Number.NaN)).toBe(0);
  });
});

describe("sortPromotionRows（数字升序, 8+ 合并档垫底）", () => {
  it("orders numeric streaks ascending with the merged bucket last", () => {
    const rows = [makeRow("8+"), makeRow(3), makeRow(1), makeRow(2)];
    expect(sortPromotionRows(rows).map((row) => row.streak)).toEqual([1, 2, 3, "8+"]);
  });

  it("does not mutate the input array", () => {
    const rows = [makeRow(2), makeRow(1)];
    sortPromotionRows(rows);
    expect(rows.map((row) => row.streak)).toEqual([2, 1]);
  });

  it("tolerates string-serialized numeric streaks", () => {
    const rows = [makeRow("8+"), makeRow("2"), makeRow(1)];
    expect(sortPromotionRows(rows).map((row) => row.streak)).toEqual([1, "2", "8+"]);
  });
});
