import { describe, expect, it } from "vitest";

import {
  DEFAULT_LADDER_DAYS,
  LADDER_DAY_OPTIONS,
  parseDaysParam,
} from "./LadderHistoryPage";

describe("parseDaysParam（?days= 窗口参数）", () => {
  it("falls back to the 60 日 default when missing", () => {
    expect(parseDaysParam(null)).toBe(DEFAULT_LADDER_DAYS);
    expect(parseDaysParam("")).toBe(DEFAULT_LADDER_DAYS);
    expect(DEFAULT_LADDER_DAYS).toBe(60);
  });

  it("accepts the documented options", () => {
    expect(parseDaysParam("30")).toBe(30);
    expect(parseDaysParam("60")).toBe(60);
    expect(parseDaysParam("120")).toBe(120);
    expect(parseDaysParam("250")).toBe(250);
  });

  it("rejects values outside the option set instead of proxying garbage to the API", () => {
    expect(parseDaysParam("7")).toBe(DEFAULT_LADDER_DAYS);
    expect(parseDaysParam("61")).toBe(DEFAULT_LADDER_DAYS);
    expect(parseDaysParam("abc")).toBe(DEFAULT_LADDER_DAYS);
    expect(parseDaysParam("9999")).toBe(DEFAULT_LADDER_DAYS);
  });
});

describe("LADDER_DAY_OPTIONS", () => {
  it("exposes the 30/60/120/250 window options", () => {
    expect([...LADDER_DAY_OPTIONS]).toEqual([30, 60, 120, 250]);
  });
});
