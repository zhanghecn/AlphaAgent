import { describe, it, expect } from "vitest";

import { buildUnifiedDateList, pickDataSource } from "./unifiedTimeline";

describe("buildUnifiedDateList", () => {
  it("把 live 最新日放在最前，并对重复日期去重", () => {
    const dates = buildUnifiedDateList("2026-07-03", [
      "2026-07-02",
      "2026-07-01",
      "2026-07-03",
    ]);
    expect(dates).toEqual(["2026-07-03", "2026-07-02", "2026-07-01"]);
  });

  it("liveDate 缺失时只返回 history 日期降序", () => {
    expect(buildUnifiedDateList(null, ["2026-07-01", "2026-07-02"])).toEqual([
      "2026-07-02",
      "2026-07-01",
    ]);
    expect(buildUnifiedDateList(undefined, ["2026-07-01"])).toEqual(["2026-07-01"]);
  });

  it("history 为空且只有 live 时返回单元素列表", () => {
    expect(buildUnifiedDateList("2026-07-03", [])).toEqual(["2026-07-03"]);
  });

  it("liveDate 比所有 history 都新时排在最前（盘中今天场景）", () => {
    const dates = buildUnifiedDateList("2026-07-05", [
      "2026-07-03",
      "2026-07-02",
    ]);
    expect(dates).toEqual(["2026-07-05", "2026-07-03", "2026-07-02"]);
  });
});

describe("pickDataSource", () => {
  it("选中日期 == liveDate → live", () => {
    expect(pickDataSource("2026-07-03", "2026-07-03")).toBe("live");
  });

  it("选中日期 != liveDate → history", () => {
    expect(pickDataSource("2026-07-02", "2026-07-03")).toBe("history");
  });

  it("liveDate 缺失 → history（无实时数据兜底）", () => {
    expect(pickDataSource("2026-07-03", null)).toBe("history");
    expect(pickDataSource("2026-07-03", undefined)).toBe("history");
  });

  it("选中为空 → history", () => {
    expect(pickDataSource(null, "2026-07-03")).toBe("history");
    expect(pickDataSource("", "2026-07-03")).toBe("history");
  });
});
