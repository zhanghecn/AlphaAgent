import { describe, expect, it } from "vitest";

import {
  adjacentDates,
  formatClockTime,
  formatCnDate,
  reviewModeBadge,
} from "./ReviewHeader";

describe("formatCnDate", () => {
  it("formats an ISO trade date as a Chinese date", () => {
    expect(formatCnDate("2026-08-13")).toBe("2026年8月13日");
    expect(formatCnDate("2026-01-05")).toBe("2026年1月5日");
  });

  it("passes through non-ISO input unchanged", () => {
    expect(formatCnDate("2026/08/13")).toBe("2026/08/13");
    expect(formatCnDate("")).toBe("");
  });
});

describe("reviewModeBadge", () => {
  it("marks live mode as provisional intraday scrolling", () => {
    const badge = reviewModeBadge("live");
    expect(badge.label).toContain("未定版");
    expect(badge.className).toContain("amber");
  });

  it("marks final mode as closed", () => {
    expect(reviewModeBadge("final").label).toBe("已收盘定版");
  });

  it("marks rebuild mode as daily-bar archive and hints at missing quote fields", () => {
    const badge = reviewModeBadge("rebuild");
    expect(badge.label).toContain("历史归档");
    expect(badge.title).toContain("盘口");
  });
});

describe("adjacentDates", () => {
  const dates = ["2026-08-13", "2026-08-12", "2026-08-11", "2026-08-10"];

  it("finds the nearest older and newer trading days around the current date", () => {
    expect(adjacentDates(dates, "2026-08-12")).toEqual({
      prev: "2026-08-11",
      next: "2026-08-13",
    });
  });

  it("disables next when the current date is the latest", () => {
    expect(adjacentDates(dates, "2026-08-13")).toEqual({
      prev: "2026-08-12",
      next: null,
    });
  });

  it("disables prev when the current date is the oldest", () => {
    expect(adjacentDates(dates, "2026-08-10").prev).toBeNull();
  });

  it("handles a live trade date that is not archived yet", () => {
    expect(adjacentDates(dates, "2026-08-14")).toEqual({
      prev: "2026-08-13",
      next: null,
    });
  });

  it("tolerates unsorted input and duplicates", () => {
    expect(adjacentDates(["2026-08-11", "2026-08-13", "2026-08-11"], "2026-08-12")).toEqual({
      prev: "2026-08-11",
      next: "2026-08-13",
    });
  });

  it("returns nulls when no dates are available", () => {
    expect(adjacentDates([], "2026-08-13")).toEqual({ prev: null, next: null });
  });
});

describe("formatClockTime", () => {
  it("renders the fetch time in the Shanghai trading timezone", () => {
    expect(formatClockTime(Date.parse("2026-08-13T07:05:09.000Z"))).toBe("15:05:09");
  });

  it("returns a placeholder for invalid timestamps", () => {
    expect(formatClockTime(Number.NaN)).toBe("--");
  });
});
