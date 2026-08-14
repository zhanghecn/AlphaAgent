import { describe, expect, it } from "vitest";

import {
  HEAT_TIER_KEYS,
  heatCellClass,
  heatCellText,
  heatCellTitle,
  heatLevel,
  heatTierLabel,
} from "./LadderHeatmap";

describe("heatLevel（热力色阶: 0空 / 1-2浅 / 3-5中 / >=6深）", () => {
  it("maps boundary counts to levels", () => {
    expect(heatLevel(0)).toBe(0);
    expect(heatLevel(1)).toBe(1);
    expect(heatLevel(2)).toBe(1);
    expect(heatLevel(3)).toBe(2);
    expect(heatLevel(5)).toBe(2);
    expect(heatLevel(6)).toBe(3);
    expect(heatLevel(138)).toBe(3); // 近60日1板档实测峰值
  });

  it("degrades invalid input to the empty level", () => {
    expect(heatLevel(null)).toBe(0);
    expect(heatLevel(undefined)).toBe(0);
    expect(heatLevel(Number.NaN)).toBe(0);
    expect(heatLevel(-3)).toBe(0);
  });
});

describe("heatCellClass（rise 红系透明度阶梯）", () => {
  it("level 0 renders no heat background", () => {
    expect(heatCellClass(0)).toBe("");
  });

  it("deepens the background with the level", () => {
    expect(heatCellClass(1)).toContain("bg-rise/10");
    expect(heatCellClass(2)).toContain("bg-rise/25");
    expect(heatCellClass(3)).toContain("bg-rise/45");
  });
});

describe("heatCellText（0 家降噪显示空）", () => {
  it("renders an empty string for 0 / invalid counts", () => {
    expect(heatCellText(0)).toBe("");
    expect(heatCellText(null)).toBe("");
    expect(heatCellText(undefined)).toBe("");
  });

  it("renders the count for positive values", () => {
    expect(heatCellText(1)).toBe("1");
    expect(heatCellText(37)).toBe("37");
  });
});

describe("heatCellTitle（悬浮提示）", () => {
  it("describes date + tier + count", () => {
    expect(heatCellTitle("2026-08-13", "3", 2)).toBe("2026-08-13 3板 2家");
    expect(heatCellTitle("2026-07-31", "6+", 1)).toBe("2026-07-31 6+板 1家");
  });

  it("keeps 0 家 in the tooltip even though the cell renders empty", () => {
    expect(heatCellTitle("2026-08-13", "6+", 0)).toBe("2026-08-13 6+板 0家");
  });
});

describe("HEAT_TIER_KEYS（行序: 6+板在上, 1板在下）", () => {
  it("orders merged 6+ first down to 1", () => {
    expect(HEAT_TIER_KEYS).toEqual(["6+", "5", "4", "3", "2", "1"]);
  });
});

describe("heatTierLabel", () => {
  it("appends 板", () => {
    expect(heatTierLabel("6+")).toBe("6+板");
    expect(heatTierLabel("1")).toBe("1板");
  });
});
